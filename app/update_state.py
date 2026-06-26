import csv
import glob
import os
from datetime import datetime

from storage import write_state, save_sample

DATA_DIR = os.environ.get("DATA_DIR", "/data")


def to_float(value):
    if value is None:
        return None
    value = str(value).strip().replace(",", ".")
    if value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def latest_csv():
    spot_files = glob.glob(os.path.join(DATA_DIR, "*Spot*.csv"))
    if spot_files:
        return max(spot_files, key=os.path.getmtime)

    files = glob.glob(os.path.join(DATA_DIR, "*.csv"))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def read_latest_row(path):
    with open(path, newline="", encoding="utf-8", errors="ignore") as f:
        rows = list(csv.reader(f, delimiter=";"))

    rows = [r for r in rows if r]

    header = None
    data_rows = []

    for row in rows:
        clean = [x.strip() for x in row]

        if "DeviceName" in clean and "PACTot" in clean:
            header = clean
            continue

        if header and len(clean) >= len(header):
            data_rows.append(clean)

    if not header or not data_rows:
        raise RuntimeError("Keine passende SBFspot Spot-CSV-Zeile gefunden")

    row = data_rows[-1]
    return dict(zip(header, row))


def get(row, *names):
    for name in names:
        if name in row:
            return row.get(name)
    return None


def main():
    path = latest_csv()
    if not path:
        raise RuntimeError("Keine CSV-Datei in /data gefunden")

    row = read_latest_row(path)

    pdc1 = to_float(get(row, "Pdc1"))
    pdc2 = to_float(get(row, "Pdc2"))
    udc1 = to_float(get(row, "Udc1"))
    udc2 = to_float(get(row, "Udc2"))
    idc1 = to_float(get(row, "Idc1"))
    idc2 = to_float(get(row, "Idc2"))

    pac1 = to_float(get(row, "Pac1"))
    pac2 = to_float(get(row, "Pac2"))
    pac3 = to_float(get(row, "Pac3"))
    uac1 = to_float(get(row, "Uac1"))
    iac1 = to_float(get(row, "Iac1"))

    power_w = to_float(get(row, "PACTot"))
    today_kwh = to_float(get(row, "EToday"))
    total_kwh = to_float(get(row, "ETotal"))
    freq = to_float(get(row, "Frequency"))
    temp_c = to_float(get(row, "Temperature"))
    efficiency = to_float(get(row, "Efficiency"))
    bt_signal = to_float(get(row, "BT_Signal"))

    timestamp = get(row, "dd/MM/yyyy HH:mm:ss") or datetime.now().isoformat(timespec="seconds")

    state = {
        "status": "online" if power_w is not None else "waiting",
        "timestamp": timestamp,

        "power_w": power_w,
        "energy_today_kwh": today_kwh,
        "energy_total_kwh": total_kwh,
        "temperature_c": temp_c,
        "grid_frequency_hz": freq,
        "efficiency_percent": efficiency,
        "bt_signal_percent": bt_signal,

        "pdc1_w": pdc1,
        "pdc2_w": pdc2,
        "udc1_v": udc1,
        "udc2_v": udc2,
        "idc1_a": idc1,
        "idc2_a": idc2,

        "pac1_w": pac1,
        "pac2_w": pac2,
        "pac3_w": pac3,
        "uac1_v": uac1,
        "iac1_a": iac1,

        "device_name": get(row, "DeviceName"),
        "device_type": get(row, "DeviceType"),
        "serial": get(row, "Serial"),
        "condition": get(row, "Condition"),
        "grid_relay": get(row, "GridRelay"),

        "source_csv": os.path.basename(path),
        "last_error": "",
    }

    write_state(state)
    save_sample(state)
    print(f"state.json updated from {path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        state = {
            "status": "error",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "last_error": str(e),
        }
        write_state(state)
        print(f"ERROR updating state.json: {e}")
        raise