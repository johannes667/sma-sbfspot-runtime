import math
import re
from typing import Any, Dict, Optional

_NUMBER = r"([-+]?\d+(?:[.,]\d+)?)"


def _to_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        text = str(value).strip().replace(",", ".")
        if text == "" or text.lower() in ("nan", "none", "null", "unknown", "unavailable"):
            return None
        number = float(text)
        if not math.isfinite(number):
            return None
        return int(number) if number.is_integer() else round(number, 3)
    except Exception:
        return None


def _first_number_after(label: str, text: str) -> Optional[float]:
    patterns = [
        rf"^{re.escape(label)}\s*[:=]\s*{_NUMBER}",
        rf"\b{re.escape(label)}\b\s*[:=]\s*{_NUMBER}",
    ]
    for line in text.splitlines():
        clean = line.strip()
        for pattern in patterns:
            m = re.search(pattern, clean, re.IGNORECASE)
            if m:
                return _to_number(m.group(1))
    return None


def _label_number(label_regex: str, text: str) -> Optional[float]:
    for line in text.splitlines():
        m = re.search(label_regex, line.strip(), re.IGNORECASE)
        if m:
            return _to_number(m.group(1))
    return None


def parse_output(text: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "power_w": _first_number_after("SPOT_PACTOT", text),
        "pac1_w": _first_number_after("SPOT_PAC1", text),
        "pac2_w": _first_number_after("SPOT_PAC2", text),
        "pac3_w": _first_number_after("SPOT_PAC3", text),
        "energy_today_kwh": _first_number_after("SPOT_ETODAY", text),
        "energy_total_kwh": _first_number_after("SPOT_ETOTAL", text),
        "pdc1_w": _first_number_after("SPOT_PDC1", text),
        "pdc2_w": _first_number_after("SPOT_PDC2", text),
        "dc_voltage_1_v": _first_number_after("SPOT_UDC1", text),
        "dc_voltage_2_v": _first_number_after("SPOT_UDC2", text),
        "dc_current_1_a": _first_number_after("SPOT_IDC1", text),
        "dc_current_2_a": _first_number_after("SPOT_IDC2", text),
        "ac_voltage_1_v": _first_number_after("SPOT_UAC1", text),
        "ac_current_1_a": _first_number_after("SPOT_IAC1", text),
        "frequency_hz": _first_number_after("SPOT_FREQ", text),
        "temperature_c": _label_number(r"Device Temperature:\s*" + _NUMBER, text),
        "operation_time_h": _first_number_after("SPOT_OPERTM", text),
        "feed_in_time_h": _first_number_after("SPOT_FEEDTM", text),
    }

    if data["energy_today_kwh"] is None:
        data["energy_today_kwh"] = _label_number(r"\bEToday:\s*" + _NUMBER + r"\s*kWh", text)
    if data["energy_total_kwh"] is None:
        data["energy_total_kwh"] = _label_number(r"\bETotal:\s*" + _NUMBER + r"\s*kWh", text)

    p1 = data.get("pdc1_w")
    p2 = data.get("pdc2_w")
    data["pdc_total_w"] = round((p1 or 0) + (p2 or 0), 3) if p1 is not None or p2 is not None else None

    # AC-Leistung ohne zusätzlichen PV-Output-Sensor. power_w ist der Live-Istwert.
    ac_parts = [data.get("pac1_w"), data.get("pac2_w"), data.get("pac3_w")]
    if data.get("power_w") is None and any(v is not None for v in ac_parts):
        data["power_w"] = round(sum(v or 0 for v in ac_parts), 3)

    if data.get("pdc_total_w") and data.get("power_w") is not None and data["pdc_total_w"] > 0:
        data["efficiency_percent"] = round(data["power_w"] / data["pdc_total_w"] * 100, 2)
    else:
        data["efficiency_percent"] = _label_number(r"Efficiency\s*:\s*" + _NUMBER + r"\s*%", text)

    serial = None
    for pattern in (r"Serial Nr:.*?\((\d+)\)", r"SN:\s*(\d+)", r"SUSyID:\s*\d+\s*-\s*SN:\s*(\d+)"):
        m = re.search(pattern, text)
        if m:
            serial = m.group(1)
            break
    data["serial"] = serial

    useful_value = any(data.get(k) is not None for k in (
        "power_w", "energy_today_kwh", "energy_total_kwh", "temperature_c", "pdc1_w", "pac1_w"
    ))
    known_good_text = any(marker in text for marker in ("INFO: Done.", "Energy Production:", "AC Spot Data:", "DC Spot Data:"))
    data["raw_ok"] = bool(useful_value and known_good_text)
    return data
