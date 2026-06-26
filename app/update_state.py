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
    files = glob.glob(os.path.join(DATA_DIR, "*.csv"))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def read_latest_row(path):
    with open(path, newline="", encoding="utf-8", errors="ignore") as f:
        sample = f.read(4096)
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","
        f.seek(0)

        rows = list(csv.reader(f, delimiter=delimiter))
        rows = [r for r in rows if r and not str(r[0]).startswith("#")]

    header = None
    data_rows = []

    for row in rows:
        joined = ";".join(row)
        if "Timestamp" in joined and "PACTot" in joined:
            header = [x.strip() for x in row]
            continue

        if header and len(row) >= 5:
            data_rows.append(row)

    if not header or not data_rows:
        raise RuntimeError("Keine passende SBFspot CSV-Zeile gefunden")

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

    power_w = to_float(get(row, "PACTot"))
    today_kwh = to_float(get(row, "EToday"))
    total_kwh = to_float(get(row, "ETotal"))
    temp_c = to_float(get(row, "InvTemperature"))
    freq = to_float(get(row, "GridFreq"))
    pdc1 = to_float(get(row, "PDC1"))
    pdc2 = to_float(get(row, "PDC2"))
    pac1 = to_float(get(row, "PAC1"))
    uac1 = to_float(get(row, "UAC1"))
    iac1 = to_float(get(row, "IAC1"))

    pdctot = to_float(get(row, "PDCTot"))
    efficiency = None
    if power_w is not None and pdctot and pdctot > 0:
        efficiency = round(power_w / pdctot * 100, 2)

    timestamp = get(row, "Timestamp") or datetime.now().isoformat(timespec="seconds")

    state = {
        "status": "online" if power_w is not None else "waiting",
        "timestamp": timestamp,
        "power_w": power_w,
        "energy_today_kwh": today_kwh,
        "energy_total_kwh": total_kwh,
        "temperature_c": temp_c,
        "grid_frequency_hz": freq,
        "pdc1_w": pdc1,
        "pdc2_w": pdc2,
        "pac1_w": pac1,
        "uac1_v": uac1,
        "iac1_a": iac1,
        "efficiency_percent": efficiency,
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