import json
import os
import sqlite3
from typing import Any, Dict, List

from config import DATA_DIR, DB_FILE, STATE_FILE


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with sqlite3.connect(DB_FILE) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS samples ("
            "ts TEXT PRIMARY KEY, power_w REAL, forecast_power_w REAL, energy_today_kwh REAL, "
            "energy_total_kwh REAL, temperature_c REAL, pdc1_w REAL, pdc2_w REAL, efficiency_percent REAL)"
        )
        # Migration alter Datenbank von 2.1.x.
        cols = [r[1] for r in con.execute("PRAGMA table_info(samples)").fetchall()]
        if "forecast_power_w" not in cols:
            con.execute("ALTER TABLE samples ADD COLUMN forecast_power_w REAL")
        con.commit()


def write_state(state: Dict[str, Any]):
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
        return {"status": "waiting", "availability": "online", "timestamp": None, "last_error": str(e)}


def save_sample(state: Dict[str, Any]):
    init_db()
    with sqlite3.connect(DB_FILE) as con:
        con.execute(
            "INSERT OR REPLACE INTO samples "
            "(ts,power_w,forecast_power_w,energy_today_kwh,energy_total_kwh,temperature_c,pdc1_w,pdc2_w,efficiency_percent) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                state.get("timestamp"),
                state.get("power_w"),
                state.get("forecast_power_w"),
                state.get("energy_today_kwh"),
                state.get("energy_total_kwh"),
                state.get("temperature_c"),
                state.get("pdc1_w"),
                state.get("pdc2_w"),
                state.get("efficiency_percent"),
            ),
        )
        con.commit()


def history(limit: int = 288) -> List[Dict[str, Any]]:
    init_db()
    with sqlite3.connect(DB_FILE) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM samples ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in reversed(rows)]
