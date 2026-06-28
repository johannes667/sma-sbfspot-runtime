import re
from typing import Any, Dict, Optional


def _to_number(value: str) -> Optional[float]:
    try:
        number = float(value.strip().replace(',', '.'))
        return int(number) if number.is_integer() else round(number, 3)
    except Exception:
        return None


def _first_number_after(label: str, text: str) -> Optional[float]:
    pattern = rf"^{re.escape(label)}\s*:\s*([-+]?\d+(?:[.,]\d+)?)"
    for line in text.splitlines():
        m = re.search(pattern, line.strip(), re.IGNORECASE)
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
    data = {
        'power_w': _first_number_after('SPOT_PACTOT', text),
        'pac1_w': _first_number_after('SPOT_PAC1', text),
        'pac2_w': _first_number_after('SPOT_PAC2', text),
        'pac3_w': _first_number_after('SPOT_PAC3', text),
        'energy_today_kwh': _first_number_after('SPOT_ETODAY', text),
        'energy_total_kwh': _first_number_after('SPOT_ETOTAL', text),
        'pdc1_w': _first_number_after('SPOT_PDC1', text),
        'pdc2_w': _first_number_after('SPOT_PDC2', text),
        'dc_voltage_1_v': _first_number_after('SPOT_UDC1', text),
        'dc_voltage_2_v': _first_number_after('SPOT_UDC2', text),
        'dc_current_1_a': _first_number_after('SPOT_IDC1', text),
        'dc_current_2_a': _first_number_after('SPOT_IDC2', text),
        'ac_voltage_1_v': _first_number_after('SPOT_UAC1', text),
        'ac_current_1_a': _first_number_after('SPOT_IAC1', text),
        'frequency_hz': _first_number_after('SPOT_FREQ', text),
        'temperature_c': _label_number(r'Device Temperature:\s*([-+]?\d+(?:[.,]\d+)?)', text),
        'operation_time_h': _first_number_after('SPOT_OPERTM', text),
        'feed_in_time_h': _first_number_after('SPOT_FEEDTM', text),
    }
    if data['energy_today_kwh'] is None:
        data['energy_today_kwh'] = _label_number(r'\bEToday:\s*([-+]?\d+(?:[.,]\d+)?)\s*kWh', text)
    if data['energy_total_kwh'] is None:
        data['energy_total_kwh'] = _label_number(r'\bETotal:\s*([-+]?\d+(?:[.,]\d+)?)\s*kWh', text)
    raw_ok = any(data.get(k) is not None for k in ('power_w', 'energy_today_kwh', 'energy_total_kwh', 'temperature_c', 'pdc1_w', 'pac1_w')) and ('INFO: Done.' in text or 'Energy Production:' in text or 'AC Spot Data:' in text)

    # Leistungswerte dürfen für Home Assistant und Diagramme nicht als unknown laufen.
    # Fehlende Leistungen werden deshalb als 0 W veröffentlicht; Energiezähler bleiben unverändert.
    power_keys = ('power_w', 'pac1_w', 'pac2_w', 'pac3_w', 'pdc1_w', 'pdc2_w')
    for key in power_keys:
        if data.get(key) is None:
            data[key] = 0

    p1, p2 = data.get('pdc1_w'), data.get('pdc2_w')
    data['pdc_total_w'] = round((p1 or 0) + (p2 or 0), 3)
    if data['pdc_total_w'] and data.get('power_w') is not None and data['pdc_total_w'] > 0:
        data['efficiency_percent'] = round(data['power_w'] / data['pdc_total_w'] * 100, 2)
    else:
        data['efficiency_percent'] = _label_number(r'Efficiency\s*:\s*([-+]?\d+(?:[.,]\d+)?)\s*%', text)
    serial = None
    for pattern in (r'Serial Nr:.*?\((\d+)\)', r'SN:\s*(\d+)', r'SUSyID:\s*\d+\s*-\s*SN:\s*(\d+)'):
        m = re.search(pattern, text)
        if m:
            serial = m.group(1)
            break
    data['serial'] = serial
    data['raw_ok'] = raw_ok
    return data
