import json
import subprocess
from typing import Any, Dict, Optional

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
    VERSION,
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


def _stringify(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        text = str(value)
        if text.lower() in ("nan", "none", "null", "unknown", "unavailable"):
            return None
        return text
    return None


def publish_state(state: Dict[str, Any]) -> None:
    if not MQTT_ENABLE:
        return

    # Wichtig: Availability ist getrennt vom Status. Fehler im SBFspot machen HA nicht unavailable.
    _pub(f"{MQTT_BASE_TOPIC}/availability", "online", True)
    _pub(f"{MQTT_BASE_TOPIC}/status", str(state.get("status", "waiting")), True)
    _pub(f"{MQTT_BASE_TOPIC}/version", VERSION, True)

    for key, value in state.items():
        if key in ("last_error", "raw_output", "raw_ok", "forecast_points", "forecast_points_raw", "forecast_rate_limit"):
            continue
        payload = _stringify(value)
        if payload is not None:
            _pub(f"{MQTT_BASE_TOPIC}/{key}", payload, True)


def publish_discovery() -> None:
    if not MQTT_ENABLE or not HA_DISCOVERY:
        return

    device = {
        "identifiers": [DEVICE_ID],
        "name": DEVICE_NAME,
        "manufacturer": "SMA",
        "model": "SBFspot Bluetooth Runtime",
        "sw_version": VERSION,
    }

    sensors = {
        "power_w": ("PV Leistung Ist", "W", "power", "measurement"),
        "pac1_w": ("AC Leistung L1", "W", "power", "measurement"),
        "pac2_w": ("AC Leistung L2", "W", "power", "measurement"),
        "pac3_w": ("AC Leistung L3", "W", "power", "measurement"),
        "energy_today_kwh": ("Energie Heute", "kWh", "energy", "total_increasing"),
        "energy_total_kwh": ("Energie Gesamt", "kWh", "energy", "total_increasing"),
        "temperature_c": ("Temperatur", "°C", "temperature", "measurement"),
        "dc_voltage_1_v": ("DC1 Spannung", "V", "voltage", "measurement"),
        "dc_current_1_a": ("DC1 Strom", "A", "current", "measurement"),
        "pdc1_w": ("DC1 Leistung", "W", "power", "measurement"),
        "dc_voltage_2_v": ("DC2 Spannung", "V", "voltage", "measurement"),
        "dc_current_2_a": ("DC2 Strom", "A", "current", "measurement"),
        "pdc2_w": ("DC2 Leistung", "W", "power", "measurement"),
        "pdc_total_w": ("DC Leistung Gesamt", "W", "power", "measurement"),
        "ac_voltage_1_v": ("AC Spannung L1", "V", "voltage", "measurement"),
        "ac_current_1_a": ("AC Strom L1", "A", "current", "measurement"),
        "frequency_hz": ("Netzfrequenz", "Hz", "frequency", "measurement"),
        "efficiency_percent": ("Wirkungsgrad", "%", None, "measurement"),
        "operation_time_h": ("Betriebszeit", "h", "duration", "total_increasing"),
        "feed_in_time_h": ("Einspeisezeit", "h", "duration", "total_increasing"),
        "forecast_power_now_w": ("Forecast Solar jetzt korrigiert", "W", "power", "measurement"),
        "forecast_power_next_hour_w": ("Forecast Solar nächste Stunde", "W", "power", "measurement"),
        "forecast_today_kwh": ("Forecast Solar heute korrigiert", "kWh", "energy", "total"),
        "forecast_remaining_today_kwh": ("Forecast Solar Rest heute korrigiert", "kWh", "energy", "total"),
        "forecast_tomorrow_kwh": ("Forecast Solar morgen korrigiert", "kWh", "energy", "total"),
        "forecast_today_raw_kwh": ("Forecast Solar heute roh", "kWh", "energy", "total"),
        "forecast_tomorrow_raw_kwh": ("Forecast Solar morgen roh", "kWh", "energy", "total"),
        "forecast_power_now_raw_w": ("Forecast Solar jetzt roh", "W", "power", "measurement"),
        "forecast_correction_factor": ("Forecast Korrekturfaktor", None, None, "measurement"),
        "forecast_accuracy_days": ("Forecast Lerntage", "d", "duration", "measurement"),
    }

    for object_id, (name, unit, device_class, state_class) in sensors.items():
        payload = {
            "name": f"{DEVICE_NAME} {name}",
            "unique_id": f"{DEVICE_ID}_{object_id}",
            "object_id": f"{DEVICE_ID}_{object_id}",
            "state_topic": f"{MQTT_BASE_TOPIC}/{object_id}",
            "availability_topic": f"{MQTT_BASE_TOPIC}/availability",
            "payload_available": "online",
            "payload_not_available": "offline",
            "unit_of_measurement": unit,
            "state_class": state_class,
            "device": device,
        }
        if device_class:
            payload["device_class"] = device_class
        _pub(f"{HA_DISCOVERY_PREFIX}/sensor/{DEVICE_ID}/{object_id}/config", json.dumps(payload), True)

    status_payload = {
        "name": f"{DEVICE_NAME} Status",
        "unique_id": f"{DEVICE_ID}_status",
        "object_id": f"{DEVICE_ID}_status",
        "state_topic": f"{MQTT_BASE_TOPIC}/status",
        "availability_topic": f"{MQTT_BASE_TOPIC}/availability",
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": device,
    }
    _pub(f"{HA_DISCOVERY_PREFIX}/sensor/{DEVICE_ID}/status/config", json.dumps(status_payload), True)

    version_payload = {
        "name": f"{DEVICE_NAME} Version",
        "unique_id": f"{DEVICE_ID}_version",
        "object_id": f"{DEVICE_ID}_version",
        "state_topic": f"{MQTT_BASE_TOPIC}/version",
        "availability_topic": f"{MQTT_BASE_TOPIC}/availability",
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": device,
    }
    _pub(f"{HA_DISCOVERY_PREFIX}/sensor/{DEVICE_ID}/version/config", json.dumps(version_payload), True)
