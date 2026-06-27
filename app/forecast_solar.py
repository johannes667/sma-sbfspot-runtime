import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from config import (
    FORECAST_API_KEY,
    FORECAST_ARRAYS,
    FORECAST_CACHE_FILE,
    FORECAST_ENABLE,
    FORECAST_INTERVAL,
    FORECAST_LATITUDE,
    FORECAST_LEARNING_DAYS,
    FORECAST_LEARNING_ENABLE,
    FORECAST_LEARNING_FILE,
    FORECAST_LONGITUDE,
)

LOCAL_TZ = ZoneInfo("Europe/Berlin")


def _read_json(path: str, default: Any):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: str, data: Any):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _ts_to_epoch(ts: str) -> float:
    """Forecast.Solar timestamps are usually local time without timezone."""
    try:
        value = str(ts).strip().replace(" ", "T").replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=LOCAL_TZ)
        return dt.timestamp()
    except Exception:
        return 0.0


def _today_key() -> str:
    return datetime.now(LOCAL_TZ).date().isoformat()


def _now_power_from_series(watts: Dict[str, float]) -> float:
    if not watts:
        return 0.0
    now = time.time()
    points = sorted((_ts_to_epoch(k), float(v or 0)) for k, v in watts.items())
    points = [p for p in points if p[0] > 0]
    if not points:
        return 0.0
    if now <= points[0][0]:
        return points[0][1]
    if now >= points[-1][0]:
        return points[-1][1]
    for (t1, v1), (t2, v2) in zip(points, points[1:]):
        if t1 <= now <= t2:
            if t2 == t1:
                return v1
            ratio = (now - t1) / (t2 - t1)
            return v1 + (v2 - v1) * ratio
    return 0.0


def _fetch_array(array: Dict[str, Any]) -> Dict[str, Any]:
    declination = float(array.get("declination", 35))
    azimuth = float(array.get("azimuth", 0))
    peak_power = float(array.get("peak_power", array.get("kwp", 0)))
    damping = array.get("damping", 0)

    base = f"https://api.forecast.solar/estimate/{FORECAST_LATITUDE}/{FORECAST_LONGITUDE}/{declination}/{azimuth}/{peak_power}"
    params = {}
    if damping not in (None, "", 0, "0"):
        params["damping"] = damping
    if FORECAST_API_KEY:
        params["token"] = FORECAST_API_KEY
    url = base + (("?" + urlencode(params)) if params else "")
    req = Request(url, headers={"User-Agent": "sma-sbfspot-runtime/2.2"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _aggregate(results: List[Tuple[Dict[str, Any], Dict[str, Any]]]) -> Dict[str, Any]:
    watts: Dict[str, float] = {}
    watt_hours_period: Dict[str, float] = {}
    watt_hours_day: Dict[str, float] = {}
    arrays = []

    for array, data in results:
        result = data.get("result", {}) if isinstance(data, dict) else {}
        for ts, value in (result.get("watts") or {}).items():
            watts[ts] = watts.get(ts, 0.0) + float(value or 0)
        for ts, value in (result.get("watt_hours_period") or {}).items():
            watt_hours_period[ts] = watt_hours_period.get(ts, 0.0) + float(value or 0)
        for day, value in (result.get("watt_hours_day") or {}).items():
            watt_hours_day[day] = watt_hours_day.get(day, 0.0) + float(value or 0)
        arrays.append({
            "name": array.get("name", "PV"),
            "peak_power": float(array.get("peak_power", array.get("kwp", 0))),
            "declination": float(array.get("declination", 35)),
            "azimuth": float(array.get("azimuth", 0)),
            "damping": float(array.get("damping", 0) or 0),
        })

    return {
        "enabled": True,
        "updated_at": datetime.now(LOCAL_TZ).isoformat(timespec="seconds"),
        "arrays": arrays,
        "watts": dict(sorted(watts.items(), key=lambda kv: _ts_to_epoch(kv[0]))),
        "watt_hours_period": dict(sorted(watt_hours_period.items(), key=lambda kv: _ts_to_epoch(kv[0]))),
        "watt_hours_day": dict(sorted(watt_hours_day.items())),
    }


def get_learning_factor() -> float:
    learning = _read_json(FORECAST_LEARNING_FILE, {})
    try:
        return float(learning.get("factor", 1.0))
    except Exception:
        return 1.0


def learning_days() -> int:
    learning = _read_json(FORECAST_LEARNING_FILE, {})
    samples = learning.get("samples", [])
    return len(samples) if isinstance(samples, list) else 0


def _apply_factor(data: Dict[str, Any], factor: float) -> Dict[str, Any]:
    out = dict(data)
    out["learning_factor"] = round(factor, 4)
    out["learning_days"] = learning_days()
    out["watts_corrected"] = {k: round(float(v or 0) * factor, 3) for k, v in data.get("watts", {}).items()}
    out["watt_hours_period_corrected"] = {k: round(float(v or 0) * factor, 3) for k, v in data.get("watt_hours_period", {}).items()}
    out["watt_hours_day_corrected"] = {k: round(float(v or 0) * factor, 3) for k, v in data.get("watt_hours_day", {}).items()}
    return out


def update_learning_from_state(state: Dict[str, Any]):
    if not FORECAST_LEARNING_ENABLE:
        return
    today = _today_key()
    actual = state.get("energy_today_kwh")
    if actual is None:
        return
    cache = _read_json(FORECAST_CACHE_FILE, {})
    day_wh = (cache.get("watt_hours_day") or {}).get(today)
    if not day_wh:
        return
    forecast_kwh = float(day_wh) / 1000.0
    actual_kwh = float(actual)
    if forecast_kwh <= 0 or actual_kwh <= 0:
        return

    learning = _read_json(FORECAST_LEARNING_FILE, {"samples": [], "factor": 1.0})
    samples = learning.get("samples", []) if isinstance(learning.get("samples", []), list) else []
    samples = [s for s in samples if s.get("date") != today]
    ratio = max(0.5, min(1.5, actual_kwh / forecast_kwh))
    samples.append({"date": today, "actual_kwh": round(actual_kwh, 3), "forecast_kwh": round(forecast_kwh, 3), "ratio": round(ratio, 4)})
    samples = samples[-FORECAST_LEARNING_DAYS:]
    factor = sum(float(s.get("ratio", 1.0)) for s in samples) / max(len(samples), 1)
    _write_json(FORECAST_LEARNING_FILE, {"factor": round(factor, 4), "samples": samples, "updated_at": datetime.now(LOCAL_TZ).isoformat(timespec="seconds")})


def get_forecast(force: bool = False) -> Dict[str, Any]:
    if not FORECAST_ENABLE:
        return {"enabled": False}
    cache = _read_json(FORECAST_CACHE_FILE, {})
    cache_age = time.time() - float(cache.get("cache_timestamp", 0) or 0)
    if cache and not force and cache_age < FORECAST_INTERVAL:
        return _apply_factor(cache, get_learning_factor())

    results = []
    errors = []
    for array in FORECAST_ARRAYS:
        try:
            results.append((array, _fetch_array(array)))
        except Exception as e:
            errors.append(f"{array.get('name','PV')}: {e}")
    if results:
        data = _aggregate(results)
        data["cache_timestamp"] = time.time()
        if errors:
            data["errors"] = errors
        _write_json(FORECAST_CACHE_FILE, data)
        return _apply_factor(data, get_learning_factor())
    if cache:
        cache["errors"] = errors or ["Forecast.Solar Abruf fehlgeschlagen, Cache verwendet"]
        return _apply_factor(cache, get_learning_factor())
    return {"enabled": True, "errors": errors or ["Keine Forecast.Solar Daten verfügbar"], "watts": {}, "watt_hours_day": {}}


def forecast_state_fields() -> Dict[str, Any]:
    data = get_forecast(False)
    if not data.get("enabled", True):
        return {}
    factor = float(data.get("learning_factor", 1.0))
    watts = data.get("watts_corrected") or data.get("watts") or {}
    today = _today_key()
    day_wh = (data.get("watt_hours_day_corrected") or data.get("watt_hours_day") or {}).get(today)
    now_w = _now_power_from_series(watts)
    return {
        "forecast_power_w": round(max(now_w, 0), 1),
        "forecast_today_kwh": round(float(day_wh or 0) / 1000.0, 3),
        "forecast_updated_at": data.get("updated_at"),
        "forecast_learning_factor": round(factor, 4),
        "forecast_learning_days": int(data.get("learning_days", 0) or 0),
    }
