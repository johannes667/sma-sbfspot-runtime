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


def _pub(topic: str, payload: str, retain: bool = True) -> None:
    if not MQTT_ENABLE:
        return
    cmd = ["mosquitto_pub", "-h", MQTT_HOST, "-p", str(MQTT_PORT), "-t", topic, "-m", payload]
    if retain and MQTT_RETAIN:
        cmd.append("-r")
    if MQTT_USER:
        cmd += ["-u", MQTT_USER]
    if MQTT_PASSWORD:
        cmd += ["-P", MQTT_PASSWORD]
    subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def publish_state(state: Dict[str, Any]) -> None:
    if not MQTT_ENABLE:
        return
    _pub(f"{MQTT_BASE_TOPIC}/availability", state.get("availability", "online"), True)
    _pub(f"{MQTT_BASE_TOPIC}/status", state.get("status", "unknown"), True)
    for key, value in state.items():
        if key in ("last_error", "raw_output", "availability"):
            continue
        if value is not None and isinstance(value, (int, float, str)):
            _pub(f"{MQTT_BASE_TOPIC}/{key}", str(value), True)


def publish_discovery() -> None:
    if not MQTT_ENABLE or not HA_DISCOVERY:
        return
    device = {"identifiers": [DEVICE_ID], "name": DEVICE_NAME, "manufacturer": "SMA", "model": "SBFspot Runtime 2.2"}
    sensors = {
        "power_w": ("PV Ist-Leistung", "W", "power", "measurement"),
        "forecast_power_w": ("Forecast.Solar Leistung", "W", "power", "measurement"),
        "forecast_today_kwh": ("Forecast.Solar Heute", "kWh", "energy", "total"),
        "forecast_learning_factor": ("Forecast.Solar Lernfaktor", None, None, "measurement"),
        "forecast_learning_days": ("Forecast.Solar Lerntage", None, None, "measurement"),
        "pac1_w": ("AC Leistung L1", "W", "power", "measurement"),
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
        _pub(f"{HA_DISCOVERY_PREFIX}/sensor/{DEVICE_ID}/{object_id}/config", json.dumps(payload), True)
