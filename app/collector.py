import os
import subprocess
from datetime import datetime

from config import SBFSPOT_CFG
from forecast_solar import forecast_state_fields, update_learning_from_state
from mqtt_client import publish_discovery, publish_state
from parser import parse_output
from storage import init_db, read_state, save_sample, write_state


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def keep_last_valid_values(new_state):
    old = read_state()
    if old.get("status") not in ("online", "error", "waiting"):
        old = {}
    keep_keys = [
        "power_w", "pac1_w", "pac2_w", "pac3_w", "energy_today_kwh", "energy_total_kwh",
        "temperature_c", "dc_voltage_1_v", "dc_current_1_a", "pdc1_w", "dc_voltage_2_v",
        "dc_current_2_a", "pdc2_w", "pdc_total_w", "ac_voltage_1_v", "ac_current_1_a",
        "frequency_hz", "efficiency_percent", "serial"
    ]
    for key in keep_keys:
        if new_state.get(key) is None and old.get(key) is not None:
            new_state[key] = old.get(key)
    return new_state


def main():
    init_db()
    publish_discovery()

    if not os.path.exists(SBFSPOT_CFG):
        state = {"status": "config_missing", "availability": "online", "timestamp": now_iso(), "last_error": f"{SBFSPOT_CFG} fehlt"}
        state.update(forecast_state_fields())
        write_state(state)
        publish_state(state)
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
            **{k: v for k, v in parsed.items() if k != "raw_ok"},
            "last_error": "" if ok else output[-4000:],
        }
    except Exception as e:
        state = {"status": "error", "availability": "online", "timestamp": now_iso(), "last_error": str(e)}

    state = keep_last_valid_values(state)
    state.update(forecast_state_fields())
    write_state(state)
    publish_state(state)

    if state.get("status") == "online":
        save_sample(state)
        update_learning_from_state(state)

    print(f"collector_status={state.get('status')}")
    if state.get("last_error"):
        print(state.get("last_error"))


if __name__ == "__main__":
    main()
