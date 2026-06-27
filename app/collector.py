import os
import subprocess
from datetime import datetime
from typing import Any, Dict

from config import SBFSPOT_CFG, VERSION
from forecast_solar import get_forecast
from mqtt_client import publish_discovery, publish_state
from parser import parse_output
from storage import init_db, read_state, save_sample, write_state

VALID_DATA_KEYS = {
    "power_w", "pac1_w", "pac2_w", "pac3_w",
    "energy_today_kwh", "energy_total_kwh", "pdc1_w", "pdc2_w", "pdc_total_w",
    "dc_voltage_1_v", "dc_voltage_2_v", "dc_current_1_a", "dc_current_2_a",
    "ac_voltage_1_v", "ac_current_1_a", "frequency_hz", "temperature_c",
    "operation_time_h", "feed_in_time_h", "efficiency_percent", "serial",
    "forecast_today_kwh", "forecast_tomorrow_kwh", "forecast_remaining_today_kwh",
    "forecast_power_now_w", "forecast_power_next_hour_w", "forecast_updated",
    "forecast_today_raw_kwh", "forecast_tomorrow_raw_kwh", "forecast_power_now_raw_w",
    "forecast_correction_factor", "forecast_accuracy_days",
    "forecast_points", "forecast_points_raw", "forecast_rate_limit", "forecast_last_error",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _merge_with_previous(previous: Dict[str, Any], fresh: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(previous or {})
    for key in VALID_DATA_KEYS:
        value = fresh.get(key)
        if value is not None and str(value).lower() not in ("unknown", "unavailable", "nan", "none", "null"):
            merged[key] = value
    return merged


def main() -> None:
    init_db()
    publish_discovery()
    previous = read_state()

    if not os.path.exists(SBFSPOT_CFG):
        state = _merge_with_previous(previous, {})
        state.update({
            "status": "config_missing",
            "timestamp": now_iso(),
            "version": VERSION,
            "last_error": f"{SBFSPOT_CFG} fehlt",
        })
        write_state(state)
        publish_state(state)
        print("collector_status=config_missing")
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
        ok = proc.returncode == 0 and bool(parsed.get("raw_ok"))

        if ok:
            state = _merge_with_previous(previous, parsed)
            state.update({
                "status": "online",
                "timestamp": now_iso(),
                "version": VERSION,
                "last_error": "",
            })
        else:
            # Bei Fehlern letzte gültige Zahlen behalten, Status aber sichtbar auf error setzen.
            state = _merge_with_previous(previous, parsed)
            state.update({
                "status": "error",
                "timestamp": now_iso(),
                "version": VERSION,
                "last_error": output[-4000:],
            })
    except Exception as e:
        state = _merge_with_previous(previous, {})
        state.update({
            "status": "error",
            "timestamp": now_iso(),
            "version": VERSION,
            "last_error": str(e),
        })

    forecast = get_forecast()
    if forecast:
        state.update(forecast)

    write_state(state)
    publish_state(state)

    if state.get("status") == "online":
        save_sample(state)

    print(f"collector_status={state.get('status')}")
    if state.get("last_error"):
        print(state.get("last_error"))


if __name__ == "__main__":
    main()
