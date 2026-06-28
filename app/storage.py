import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from config import DATA_DIR, DB_FILE, STATE_FILE


BUCKET_MINUTES = 5


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with sqlite3.connect(DB_FILE) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS samples ("
            "ts TEXT PRIMARY KEY, power_w REAL, forecast_power_w REAL, energy_today_kwh REAL, "
            "energy_total_kwh REAL, temperature_c REAL, pdc1_w REAL, pdc2_w REAL, efficiency_percent REAL)"
        )
        # Migration alter Datenbank von 2.1.x / 2.2.x.
        cols = [r[1] for r in con.execute("PRAGMA table_info(samples)").fetchall()]
        if "forecast_power_w" not in cols:
            con.execute("ALTER TABLE samples ADD COLUMN forecast_power_w REAL")
        con.execute("CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(ts)")
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


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _bucket_ts(value: Any) -> str:
    """Normalize samples to stable 5-minute buckets for a clean day chart."""
    dt = _parse_ts(value) or datetime.now().astimezone()
    minute = (dt.minute // BUCKET_MINUTES) * BUCKET_MINUTES
    dt = dt.replace(minute=minute, second=0, microsecond=0)
    return dt.isoformat(timespec="seconds")


def _to_float_or_zero(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def save_sample(state: Dict[str, Any]):
    """Persist one data point.

    In v2.3 every collector run writes a sample. If SBFspot has no valid power
    value, power fields are stored as 0 W. This keeps the WebGUI chart stable
    across missing CSV/SBFspot cycles and after container restarts.
    """
    init_db()
    ts = _bucket_ts(state.get("timestamp"))
    with sqlite3.connect(DB_FILE) as con:
        con.execute(
            "INSERT OR REPLACE INTO samples "
            "(ts,power_w,forecast_power_w,energy_today_kwh,energy_total_kwh,temperature_c,pdc1_w,pdc2_w,efficiency_percent) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                ts,
                _to_float_or_zero(state.get("power_w")),
                _to_float_or_zero(state.get("forecast_power_w")),
                state.get("energy_today_kwh"),
                state.get("energy_total_kwh"),
                state.get("temperature_c"),
                _to_float_or_zero(state.get("pdc1_w")),
                _to_float_or_zero(state.get("pdc2_w")),
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


def history_day(fill_missing: bool = True) -> List[Dict[str, Any]]:
    """Return the current local day with optional 5-minute zero fill.

    The zero fill is display-oriented: missing buckets are rendered as 0 W so
    the chart starts at midnight and continues through the current time instead
    of beginning only after a container restart.
    """
    init_db()
    now = datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(second=0, microsecond=0)
    end = end.replace(minute=(end.minute // BUCKET_MINUTES) * BUCKET_MINUTES)
    start_s = start.isoformat(timespec="seconds")

    with sqlite3.connect(DB_FILE) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM samples WHERE ts >= ? ORDER BY ts ASC", (start_s,)).fetchall()
    data = {dict(r)["ts"]: dict(r) for r in rows}

    if not fill_missing:
        return list(data.values())

    result: List[Dict[str, Any]] = []
    ts = start
    while ts <= end:
        key = ts.isoformat(timespec="seconds")
        if key in data:
            result.append(data[key])
        else:
            result.append({
                "ts": key,
                "power_w": 0,
                "forecast_power_w": 0,
                "energy_today_kwh": None,
                "energy_total_kwh": None,
                "temperature_c": None,
                "pdc1_w": 0,
                "pdc2_w": 0,
                "efficiency_percent": None,
                "filled": True,
            })
        ts += timedelta(minutes=BUCKET_MINUTES)
    return result


def cleanup_history(days: int = 90):
    """Keep the database small; enough for useful charts and diagnostics."""
    init_db()
    cutoff = datetime.now().astimezone() - timedelta(days=max(1, int(days)))
    with sqlite3.connect(DB_FILE) as con:
        con.execute("DELETE FROM samples WHERE ts < ?", (cutoff.isoformat(timespec="seconds"),))
        con.commit()
