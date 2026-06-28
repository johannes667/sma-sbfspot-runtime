import json
import subprocess
from typing import Any, Dict

from config import (
    DEVICE_ID,
    DEVICE_NAME,
    HA_DISCOVERY,
    HA_DISCOVERY_PREFIX,
    MQTT_BASE_TOPIC,
    MQTT_ENABLE,
    MQTT_HOST,
    MQTT_PASSWORD,
    MQTT_PORT,
    MQTT_RETAIN,
    MQTT_USER,
)

try:
    from log_utils import log_event
except Exception:  # pragma: no cover
    def log_event(level, message):
        pass


def _pub(topic: str, payload: str, retain: bool = True) -> bool:
    if not MQTT_ENABLE:
        return True
    cmd = ["mosquitto_pub", "-h", MQTT_HOST, "-p", str(MQTT_PORT), "-t", topic, "-m", payload]
    if retain and MQTT_RETAIN:
        cmd.append("-r")
    if MQTT_USER:
        cmd += ["-u", MQTT_USER]
    if MQTT_PASSWORD:
        cmd += ["-P", MQTT_PASSWORD]
    try:
        res = subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        return res.returncode == 0
    except Exception as e:
        log_event("ERROR", f"MQTT Publish Fehler auf {topic}: {e}")
        return False


def publish_state(state: Dict[str, Any]) -> bool:
    if not MQTT_ENABLE:
        return True
    ok = True
    ok = _pub(f"{MQTT_BASE_TOPIC}/availability", state.get("availability", "online"), True) and ok
    ok = _pub(f"{MQTT_BASE_TOPIC}/status", state.get("status", "unknown"), True) and ok
    count = 0
    for key, value in state.items():
        if key in ("last_error", "raw_output", "availability"):
            continue
        if value is not None and isinstance(value, (int, float, str)):
            ok = _pub(f"{MQTT_BASE_TOPIC}/{key}", str(value), True) and ok
            count += 1
    state["mqtt_publish_ok"] = ok
    state["mqtt_last_publish_count"] = count
    return ok


def publish_discovery() -> bool:
    if not MQTT_ENABLE or not HA_DISCOVERY:
        return True
    device = {"identifiers": [DEVICE_ID], "name": DEVICE_NAME, "manufacturer": "SMA", "model": "SBFspot Runtime 2.2.1"}
    sensors = {
        "power_w": ("PV Ist-Leistung", "W", "power", "measurement"),
        "forecast_power_w": ("Forecast.Solar Leistung", "W", "power", "measurement"),
        "forecast_today_kwh": ("Forecast.Solar Heute", "kWh", "energy", "total"),
        "forecast_learning_factor": ("Forecast.Solar Lernfaktor", None, None, "measurement"),
        "forecast_learning_days": ("Forecast.Solar Lerntage", None, None, "measurement"),
        "pac1_w": ("AC Leistung L1", "W", "power", "measurement"),
        "pac2_w": ("AC Leistung L2", "W", "power", "measurement"),
        "pac3_w": ("AC Leistung L3", "W", "power", "measurement"),
        "energy_today_kwh": ("Energie Heute", "kWh", "energy", "total_increasing"),
        "energy_total_kwh": ("Energie Gesamt", "kWh", "energy", "total_increasing"),
        "temperature_c": ("Temperatur", "°C", "temperature", "measurement"),
        "dc_voltage_1_v": ("DC1 Spannung", "V", "voltage", "measurement"),
        "dc_current_1_a": ("DC1 Strom", "A", "current", "measurement"),
        "pdc1_w": ("MPPT1", "W", "power", "measurement"),
        "dc_voltage_2_v": ("DC2 Spannung", "V", "voltage", "measurement"),
        "dc_current_2_a": ("DC2 Strom", "A", "current", "measurement"),
        "pdc2_w": ("MPPT2", "W", "power", "measurement"),
        "pdc_total_w": ("DC Gesamt", "W", "power", "measurement"),
        "ac_voltage_1_v": ("AC Spannung L1", "V", "voltage", "measurement"),
        "ac_current_1_a": ("AC Strom L1", "A", "current", "measurement"),
        "frequency_hz": ("Netzfrequenz", "Hz", "frequency", "measurement"),
        "efficiency_percent": ("Wirkungsgrad", "%", None, "measurement"),
    }
    ok = True
    for object_id, (name, unit, device_class, state_class) in sensors.items():
        payload = {
            "name": f"{DEVICE_NAME} {name}",
            "unique_id": f"{DEVICE_ID}_{object_id}",
            "state_topic": f"{MQTT_BASE_TOPIC}/{object_id}",
            "availability_topic": f"{MQTT_BASE_TOPIC}/availability",
            "payload_available": "online",
            "payload_not_available": "offline",
            "state_class": state_class,
            "device": device,
        }
        if unit:
            payload["unit_of_measurement"] = unit
        if device_class:
            payload["device_class"] = device_class
        ok = _pub(f"{HA_DISCOVERY_PREFIX}/sensor/{DEVICE_ID}/{object_id}/config", json.dumps(payload), True) and ok
    return ok
