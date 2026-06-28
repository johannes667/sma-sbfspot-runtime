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
LEARNING_MIN_FACTOR = 0.75
LEARNING_MAX_FACTOR = 1.25
LEARNING_OUTLIER_MIN = 0.65
LEARNING_OUTLIER_MAX = 1.35
LEARNING_SLOW_ALPHA = 0.15


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


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


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


def _now_epoch() -> float:
    return datetime.now(LOCAL_TZ).timestamp()


def _now_power_from_series(watts: Dict[str, float]) -> float:
    if not watts:
        return 0.0
    now = _now_epoch()
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


def _sum_today_until_now(periods: Dict[str, float], *, raw: bool = False) -> float:
    today = _today_key()
    now = _now_epoch()
    total = 0.0
    for ts, value in (periods or {}).items():
        if not str(ts).startswith(today):
            continue
        epoch = _ts_to_epoch(ts)
        if epoch and epoch <= now:
            total += float(value or 0)
    return total / 1000.0


def _day_kwh(day_map: Dict[str, float], day: str) -> float:
    try:
        return float((day_map or {}).get(day) or 0) / 1000.0
    except Exception:
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
    req = Request(url, headers={"User-Agent": "sma-sbfspot-runtime/2.5"})
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


def _normalise_learning_file(learning: Dict[str, Any]) -> List[Dict[str, Any]]:
    samples = learning.get("samples")
    if isinstance(samples, list):
        return samples
    days = learning.get("days")
    if isinstance(days, list):
        converted = []
        for d in days:
            if not isinstance(d, dict):
                continue
            converted.append({
                "date": d.get("date"),
                "actual_kwh": d.get("actual_kwh"),
                "forecast_kwh": d.get("forecast_raw_kwh") or d.get("forecast_kwh"),
                "ratio": d.get("ratio"),
            })
        return converted
    return []


def _good_learning_samples(samples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    today = _today_key()
    good = []
    for s in samples:
        try:
            day = str(s.get("date") or "")[:10]
            actual = float(s.get("actual_kwh") or 0)
            forecast = float(s.get("forecast_kwh") or 0)
        except Exception:
            continue
        if not day or day >= today:
            continue
        if actual < 0.5 or forecast < 0.5:
            continue
        ratio = actual / forecast
        s["ratio"] = round(ratio, 4)
        if LEARNING_OUTLIER_MIN <= ratio <= LEARNING_OUTLIER_MAX:
            good.append(s)
    return good[-max(1, FORECAST_LEARNING_DAYS):]


def _calculate_learning(samples: List[Dict[str, Any]], previous_factor: float) -> Dict[str, Any]:
    good = _good_learning_samples(samples)
    if not good:
        factor = _clamp(previous_factor or 1.0, LEARNING_MIN_FACTOR, LEARNING_MAX_FACTOR)
        return {"factor": round(factor, 4), "target_factor": round(factor, 4), "good": good, "confidence": 0}

    ratios = [_clamp(float(s.get("ratio", 1.0)), LEARNING_MIN_FACTOR, LEARNING_MAX_FACTOR) for s in good]
    weights = list(range(1, len(ratios) + 1))
    target = sum(r * w for r, w in zip(ratios, weights)) / sum(weights)
    target = _clamp(target, LEARNING_MIN_FACTOR, LEARNING_MAX_FACTOR)
    confidence = min(1.0, len(good) / max(1, FORECAST_LEARNING_DAYS))

    if len(good) < FORECAST_LEARNING_DAYS:
        # Einlernphase: langsam von 1.0 in Richtung Ziel laufen, damit 1-2 Tage nicht alles verziehen.
        factor = 1.0 + (target - 1.0) * confidence
    else:
        # Danach nur noch träge nachregeln.
        prev = _clamp(previous_factor or target, LEARNING_MIN_FACTOR, LEARNING_MAX_FACTOR)
        factor = prev * (1.0 - LEARNING_SLOW_ALPHA) + target * LEARNING_SLOW_ALPHA

    return {"factor": round(_clamp(factor, LEARNING_MIN_FACTOR, LEARNING_MAX_FACTOR), 4), "target_factor": round(target, 4), "good": good, "confidence": round(confidence, 3)}


def get_learning_factor() -> float:
    if not FORECAST_LEARNING_ENABLE:
        return 1.0
    learning = _read_json(FORECAST_LEARNING_FILE, {})
    try:
        return _clamp(float(learning.get("factor", 1.0)), LEARNING_MIN_FACTOR, LEARNING_MAX_FACTOR)
    except Exception:
        return 1.0


def learning_meta() -> Dict[str, Any]:
    learning = _read_json(FORECAST_LEARNING_FILE, {})
    samples = _normalise_learning_file(learning)
    good = _good_learning_samples(samples)
    days = int(learning.get("days_used", len(good)) or 0)
    confidence = float(learning.get("confidence", min(1.0, days / max(1, FORECAST_LEARNING_DAYS))) or 0)
    if days < max(1, FORECAST_LEARNING_DAYS):
        status = f"lernt ({days}/{FORECAST_LEARNING_DAYS} Tage)"
    else:
        status = "stabil · langsame Nachregelung"
    return {
        "learning_days": days,
        "learning_target_days": FORECAST_LEARNING_DAYS,
        "learning_confidence": round(confidence, 3),
        "learning_status": status,
        "learning_target_factor": learning.get("target_factor"),
        "learning_updated_at": learning.get("updated_at") or learning.get("updated"),
    }


def _apply_factor(data: Dict[str, Any], factor: float) -> Dict[str, Any]:
    out = dict(data)
    factor = _clamp(float(factor or 1.0), LEARNING_MIN_FACTOR, LEARNING_MAX_FACTOR)
    meta = learning_meta()
    out["learning_factor"] = round(factor, 4)
    out.update(meta)
    out["watts_corrected"] = {k: round(float(v or 0) * factor, 3) for k, v in data.get("watts", {}).items()}
    out["watt_hours_period_corrected"] = {k: round(float(v or 0) * factor, 3) for k, v in data.get("watt_hours_period", {}).items()}
    out["watt_hours_day_corrected"] = {k: round(float(v or 0) * factor, 3) for k, v in data.get("watt_hours_day", {}).items()}
    out["summary"] = forecast_summary(out)
    return out


def update_learning_from_state(state: Dict[str, Any]):
    """Store today's full-day forecast and actual value, but learn only from completed days.

    v2.5 ignores the current day for factor calculation. After the 14-day learning
    window is filled, new days only move the factor slowly.
    """
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

    try:
        forecast_kwh = float(day_wh) / 1000.0
        actual_kwh = float(actual)
    except Exception:
        return
    if forecast_kwh <= 0 or actual_kwh <= 0:
        return

    learning = _read_json(FORECAST_LEARNING_FILE, {"samples": [], "factor": 1.0})
    previous_factor = get_learning_factor()
    samples = _normalise_learning_file(learning)
    samples = [s for s in samples if str(s.get("date") or "")[:10] != today]
    samples.append({
        "date": today,
        "actual_kwh": round(actual_kwh, 3),
        "forecast_kwh": round(forecast_kwh, 3),
        "ratio": round(actual_kwh / forecast_kwh, 4),
        "complete": False,
    })
    samples = samples[-(max(1, FORECAST_LEARNING_DAYS) + 3):]
    calc = _calculate_learning(samples, previous_factor)

    _write_json(FORECAST_LEARNING_FILE, {
        "version": 2,
        "factor": calc["factor"],
        "target_factor": calc["target_factor"],
        "min_factor": LEARNING_MIN_FACTOR,
        "max_factor": LEARNING_MAX_FACTOR,
        "days_used": len(calc["good"]),
        "target_days": FORECAST_LEARNING_DAYS,
        "confidence": calc["confidence"],
        "updated_at": datetime.now(LOCAL_TZ).isoformat(timespec="seconds"),
        "samples": samples,
        "good_days": calc["good"],
    })


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
    return {"enabled": True, "errors": errors or ["Keine Forecast.Solar Daten verfügbar"], "watts": {}, "watt_hours_day": {}, "summary": {}}


def forecast_summary(data: Dict[str, Any], actual_today_kwh: Any = None) -> Dict[str, Any]:
    today = _today_key()
    raw_day = data.get("watt_hours_day") or {}
    corrected_day = data.get("watt_hours_day_corrected") or raw_day
    raw_period = data.get("watt_hours_period") or {}
    corrected_period = data.get("watt_hours_period_corrected") or raw_period

    forecast_today = _day_kwh(corrected_day, today)
    forecast_raw_today = _day_kwh(raw_day, today)
    expected_until_now = _sum_today_until_now(corrected_period)
    expected_raw_until_now = _sum_today_until_now(raw_period)

    try:
        actual = float(actual_today_kwh) if actual_today_kwh not in (None, "") else None
    except Exception:
        actual = None

    deviation_kwh = None
    deviation_percent = None
    if actual is not None and expected_until_now > 0:
        deviation_kwh = actual - expected_until_now
        deviation_percent = (deviation_kwh / expected_until_now) * 100.0

    meta = learning_meta()
    return {
        "forecast_today_kwh": round(forecast_today, 3),
        "forecast_raw_today_kwh": round(forecast_raw_today, 3),
        "expected_until_now_kwh": round(expected_until_now, 3),
        "expected_raw_until_now_kwh": round(expected_raw_until_now, 3),
        "actual_until_now_kwh": round(actual, 3) if actual is not None else None,
        "deviation_kwh": round(deviation_kwh, 3) if deviation_kwh is not None else None,
        "deviation_percent": round(deviation_percent, 1) if deviation_percent is not None else None,
        **meta,
    }


def forecast_state_fields() -> Dict[str, Any]:
    data = get_forecast(False)
    if not data.get("enabled", True):
        return {}
    factor = float(data.get("learning_factor", 1.0))
    watts = data.get("watts_corrected") or data.get("watts") or {}
    today = _today_key()
    day_wh = (data.get("watt_hours_day_corrected") or data.get("watt_hours_day") or {}).get(today)
    raw_day_wh = (data.get("watt_hours_day") or {}).get(today)
    expected = _sum_today_until_now(data.get("watt_hours_period_corrected") or data.get("watt_hours_period") or {})
    now_w = _now_power_from_series(watts)
    meta = learning_meta()
    return {
        "forecast_power_w": round(max(now_w, 0), 1),
        "forecast_today_kwh": round(float(day_wh or 0) / 1000.0, 3),
        "forecast_today_raw_kwh": round(float(raw_day_wh or 0) / 1000.0, 3),
        "forecast_expected_until_now_kwh": round(expected, 3),
        "forecast_updated_at": data.get("updated_at"),
        "forecast_learning_factor": round(factor, 4),
        "forecast_learning_days": int(meta.get("learning_days", 0) or 0),
        "forecast_learning_target_days": int(meta.get("learning_target_days", FORECAST_LEARNING_DAYS) or FORECAST_LEARNING_DAYS),
        "forecast_learning_confidence": meta.get("learning_confidence", 0),
        "forecast_learning_status": meta.get("learning_status"),
        "forecast_learning_target_factor": meta.get("learning_target_factor"),
    }
