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
    text = str(value).strip()
    # Neu: ISO mit lokaler Zeitzone, z. B. 2026-06-28T16:36:55+02:00
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        pass
    # Altbestand aus früherer SQLite-Version: 26/06/2026 09:50:04
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=datetime.now().astimezone().tzinfo)
        except Exception:
            pass
    return None


def _display_ts(value: Any) -> Optional[str]:
    dt = _parse_ts(value)
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt.astimezone().strftime("%d.%m.%Y %H:%M:%S")


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


def history_status() -> Dict[str, Any]:
    """Return SQLite/history diagnostics for the WebGUI status page."""
    os.makedirs(DATA_DIR, exist_ok=True)
    init_db()
    status: Dict[str, Any] = {
        "ok": False,
        "db_file": DB_FILE,
        "exists": os.path.exists(DB_FILE),
        "size_bytes": 0,
        "samples": 0,
        "first_ts": None,
        "last_ts": None,
        "last_age_seconds": None,
        "filled_buckets_today": 0,
        "real_buckets_today": 0,
    }
    try:
        if os.path.exists(DB_FILE):
            status["size_bytes"] = os.path.getsize(DB_FILE)
        with sqlite3.connect(DB_FILE) as con:
            row = con.execute("SELECT COUNT(*), MIN(ts), MAX(ts) FROM samples").fetchone()
            status["samples"] = int(row[0] or 0)
            status["first_ts"] = row[1]
            status["last_ts"] = row[2]
            status["first_ts_display"] = _display_ts(row[1])
            status["last_ts_display"] = _display_ts(row[2])

            today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
            real_today = con.execute("SELECT COUNT(*) FROM samples WHERE ts >= ?", (today.isoformat(timespec="seconds"),)).fetchone()[0]
            status["real_buckets_today"] = int(real_today or 0)

        last_dt = _parse_ts(status.get("last_ts"))
        if last_dt:
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
            status["last_age_seconds"] = max(0, int((datetime.now().astimezone() - last_dt.astimezone()).total_seconds()))

        status["filled_buckets_today"] = len(history_day(fill_missing=True))
        status["ok"] = bool(status["exists"] and status["samples"] >= 0)
        return status
    except Exception as e:
        status["error"] = str(e)
        return status
