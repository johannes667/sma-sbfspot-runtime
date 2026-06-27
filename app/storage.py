import json
import os
import sqlite3
from typing import Any, Dict, List

from config import DATA_DIR, DB_FILE, STATE_FILE


SAMPLE_COLUMNS = {
    "power_w": "REAL",
    "energy_today_kwh": "REAL",
    "energy_total_kwh": "REAL",
    "temperature_c": "REAL",
    "pdc1_w": "REAL",
    "pdc2_w": "REAL",
    "pdc_total_w": "REAL",
    "efficiency_percent": "REAL",
    "forecast_power_now_w": "REAL",
    "forecast_power_now_raw_w": "REAL",
    "forecast_today_kwh": "REAL",
    "forecast_today_raw_kwh": "REAL",
    "forecast_remaining_today_kwh": "REAL",
    "forecast_correction_factor": "REAL",
}


def init_db() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with sqlite3.connect(DB_FILE) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS samples (
                ts TEXT PRIMARY KEY,
                power_w REAL,
                energy_today_kwh REAL,
                energy_total_kwh REAL,
                temperature_c REAL,
                pdc1_w REAL,
                pdc2_w REAL,
                pdc_total_w REAL,
                efficiency_percent REAL,
                forecast_power_now_w REAL,
                forecast_power_now_raw_w REAL,
                forecast_today_kwh REAL,
                forecast_today_raw_kwh REAL,
                forecast_remaining_today_kwh REAL,
                forecast_correction_factor REAL
            )
            """
        )
        for column, col_type in SAMPLE_COLUMNS.items():
            _ensure_column(con, "samples", column, col_type)
        con.commit()


def _ensure_column(con: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    columns = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def write_state(state: Dict[str, Any]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


def read_state() -> Dict[str, Any]:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"status": "waiting", "timestamp": None, "last_error": str(e)}


def save_sample(state: Dict[str, Any]) -> None:
    init_db()
    columns = ["ts"] + list(SAMPLE_COLUMNS.keys())
    values = [state.get("timestamp")] + [state.get(c) for c in SAMPLE_COLUMNS.keys()]
    placeholders = ", ".join("?" for _ in columns)
    with sqlite3.connect(DB_FILE) as con:
        con.execute(
            f"INSERT OR REPLACE INTO samples ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
        con.commit()


def history(limit: int = 288) -> List[Dict[str, Any]]:
    init_db()
    with sqlite3.connect(DB_FILE) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM samples ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in reversed(rows)]
