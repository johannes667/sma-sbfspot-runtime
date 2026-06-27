import json
import os
import sqlite3
from datetime import datetime, date
from typing import Any, Dict, List, Optional

from config import DB_FILE, FORECAST_LEARNING_FILE, FORECAST_LEARNING_DAYS, FORECAST_LEARNING_ENABLE


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _date_from_ts(ts: Any) -> Optional[str]:
    if not ts:
        return None
    text = str(ts)
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except Exception:
        return text[:10] if len(text) >= 10 else None


def _load_file() -> Dict[str, Any]:
    try:
        with open(FORECAST_LEARNING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"days": [], "factor": 1.0}


def _save_file(data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(FORECAST_LEARNING_FILE), exist_ok=True)
    tmp = FORECAST_LEARNING_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, FORECAST_LEARNING_FILE)


def current_factor() -> float:
    if not FORECAST_LEARNING_ENABLE:
        return 1.0
    data = _load_file()
    try:
        return _clamp(float(data.get("factor", 1.0)), 0.6, 1.4)
    except Exception:
        return 1.0


def _read_completed_days() -> List[Dict[str, Any]]:
    if not os.path.exists(DB_FILE):
        return []
    today = date.today().isoformat()
    result: Dict[str, Dict[str, Any]] = {}
    with sqlite3.connect(DB_FILE) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT ts, energy_today_kwh, forecast_today_raw_kwh, forecast_today_kwh
            FROM samples
            WHERE ts IS NOT NULL
            ORDER BY ts ASC
            """
        ).fetchall()
    for row in rows:
        day = _date_from_ts(row["ts"])
        if not day or day >= today:
            continue
        actual = row["energy_today_kwh"]
        forecast_raw = row["forecast_today_raw_kwh"] if "forecast_today_raw_kwh" in row.keys() else None
        forecast_old = row["forecast_today_kwh"] if "forecast_today_kwh" in row.keys() else None
        forecast = forecast_raw if forecast_raw not in (None, 0) else forecast_old
        if actual is None or forecast is None:
            continue
        try:
            actual_f = float(actual)
            forecast_f = float(forecast)
        except Exception:
            continue
        if actual_f > 0.2 and forecast_f > 0.2:
            result[day] = {"date": day, "actual_kwh": actual_f, "forecast_raw_kwh": forecast_f}
    return list(result.values())[-FORECAST_LEARNING_DAYS:]


def refresh_learning() -> Dict[str, Any]:
    if not FORECAST_LEARNING_ENABLE:
        return {"factor": 1.0, "days": []}
    days = _read_completed_days()
    ratios: List[float] = []
    for d in days:
        ratio = d["actual_kwh"] / d["forecast_raw_kwh"]
        ratios.append(_clamp(ratio, 0.6, 1.4))
        d["ratio"] = round(ratio, 3)
    if ratios:
        # Neuere Tage etwas stärker gewichten.
        weights = list(range(1, len(ratios) + 1))
        factor = sum(r * w for r, w in zip(ratios, weights)) / sum(weights)
        factor = _clamp(factor, 0.6, 1.4)
    else:
        factor = current_factor()
    data = {
        "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "factor": round(factor, 3),
        "days": days,
        "days_used": len(days),
    }
    _save_file(data)
    return data
