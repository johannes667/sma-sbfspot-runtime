import os
import subprocess
from datetime import datetime

from config import SBFSPOT_CFG
from forecast_solar import forecast_state_fields, update_learning_from_state
from log_utils import log_event
from mqtt_client import publish_discovery, publish_state
from parser import parse_output
from storage import cleanup_history, init_db, read_state, save_sample, write_state


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


POWER_KEYS = {"power_w", "pac1_w", "pac2_w", "pac3_w", "pdc1_w", "pdc2_w", "pdc_total_w"}


def keep_last_valid_values(new_state):
    old = read_state()
    if old.get("status") not in ("online", "error", "waiting"):
        old = {}
    keep_keys = [
        "power_w", "pac1_w", "pac2_w", "pac3_w", "energy_today_kwh", "energy_total_kwh",
        "temperature_c", "dc_voltage_1_v", "dc_current_1_a", "pdc1_w", "dc_voltage_2_v",
        "dc_current_2_a", "pdc2_w", "pdc_total_w", "ac_voltage_1_v", "ac_current_1_a",
        "frequency_hz", "efficiency_percent", "serial", "last_sbfspot_success"
    ]
    for key in keep_keys:
        if new_state.get(key) is None:
            if key in POWER_KEYS:
                new_state[key] = 0
            elif old.get(key) is not None:
                new_state[key] = old.get(key)
    return new_state


def main():
    init_db()
    log_event("INFO", "Collector-Lauf gestartet")
    discovery_ok = publish_discovery()

    if not os.path.exists(SBFSPOT_CFG):
        state = {
            "status": "config_missing",
            "availability": "online",
            "timestamp": now_iso(),
            "last_sbfspot_run": now_iso(),
            "last_error": f"{SBFSPOT_CFG} fehlt",
            "ha_discovery_ok": discovery_ok,
        }
        state.update(forecast_state_fields())
        write_state(state)
        mqtt_ok = publish_state(state)
        state["mqtt_publish_ok"] = mqtt_ok
        write_state(state)
        log_event("ERROR", state["last_error"])
        return

    try:
        proc = subprocess.run(
            ["SBFspot", "-d5", "-v5", "-finq", "-nocsv", f"-cfg:{SBFSPOT_CFG}"],
            cwd="/",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=240,
        )
        output = proc.stdout or ""
        parsed = parse_output(output)
        ok = proc.returncode == 0 and parsed.get("raw_ok")
        state = {
            "status": "online" if ok else "error",
            "availability": "online",
            "timestamp": now_iso(),
            "last_sbfspot_run": now_iso(),
            "ha_discovery_ok": discovery_ok,
            **{k: v for k, v in parsed.items() if k != "raw_ok"},
            "last_error": "" if ok else output[-4000:],
            "last_sbfspot_success": now_iso() if ok else None,
        }
        if ok:
            log_event("INFO", f"SBFspot OK · AC {state.get('power_w', 0)} W · Heute {state.get('energy_today_kwh', '–')} kWh")
        else:
            log_event("WARNING", "SBFspot lieferte keine vollständigen Daten; Leistungswerte laufen auf 0 W")
    except Exception as e:
        state = {
            "status": "error",
            "availability": "online",
            "timestamp": now_iso(),
            "last_sbfspot_run": now_iso(),
            "ha_discovery_ok": discovery_ok,
            "last_error": str(e),
            "power_w": 0,
            "pac1_w": 0,
            "pac2_w": 0,
            "pac3_w": 0,
            "pdc1_w": 0,
            "pdc2_w": 0,
            "pdc_total_w": 0,
        }
        log_event("ERROR", f"SBFspot Fehler: {e}")

    state = keep_last_valid_values(state)
    state.update(forecast_state_fields())
    write_state(state)
    mqtt_ok = publish_state(state)
    state["mqtt_publish_ok"] = mqtt_ok
    state["last_mqtt_publish"] = now_iso()
    write_state(state)

    if mqtt_ok:
        log_event("INFO", f"MQTT Publish OK · {state.get('mqtt_last_publish_count', 0)} Werte")
    else:
        log_event("ERROR", "MQTT Publish fehlgeschlagen")

    # v2.3: always persist one sample per collector run. Missing/invalid power becomes 0 W.
    # This gives the WebGUI a stable day history even after SBFspot errors or restarts.
    save_sample(state)
    cleanup_history(90)

    if state.get("status") == "online":
        update_learning_from_state(state)

    print(f"collector_status={state.get('status')}")
    if state.get("last_error"):
        print(state.get("last_error"))


if __name__ == "__main__":
    main()
