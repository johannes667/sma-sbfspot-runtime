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
MIN_RATIO = 0.75
MAX_RATIO = 1.25
MIN_EXPECTED_KWH_FOR_LEARNING = 1.0
MIN_ACTUAL_KWH_FOR_LEARNING = 0.2


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


def _ts_to_dt(ts: str):
    try:
        value = str(ts).strip().replace(" ", "T").replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=LOCAL_TZ)
        return dt.astimezone(LOCAL_TZ)
    except Exception:
        return None


def _ts_to_epoch(ts: str) -> float:
    dt = _ts_to_dt(ts)
    return dt.timestamp() if dt else 0.0


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


def _period_kwh_until_now(period_wh: Dict[str, float], factor: float = 1.0) -> float:
    today = _today_key()
    now = datetime.now(LOCAL_TZ)
    total_wh = 0.0
    for ts, value in (period_wh or {}).items():
        dt = _ts_to_dt(ts)
        if not dt or dt.date().isoformat() != today:
            continue
        # Forecast.Solar period values are timestamped at/near the end of each period.
        # Nur Perioden bis jetzt zählen, damit der Lernvergleich nicht den ganzen Tag nimmt.
        if dt <= now:
            total_wh += float(value or 0)
    return round((total_wh * factor) / 1000.0, 3)


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
    req = Request(url, headers={"User-Agent": "sma-sbfspot-runtime/2.6"})
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


def _read_learning() -> Dict[str, Any]:
    learning = _read_json(FORECAST_LEARNING_FILE, {})
    if not isinstance(learning, dict):
        learning = {}
    samples = learning.get("samples", [])
    if not isinstance(samples, list):
        samples = []
    learning["samples"] = samples
    learning.setdefault("factor", 1.0)
    return learning


def get_learning_factor() -> float:
    learning = _read_learning()
    try:
        return float(learning.get("factor", 1.0))
    except Exception:
        return 1.0


def learning_days() -> int:
    return len(_read_learning().get("samples", []))


def _learning_status() -> Dict[str, Any]:
    learning = _read_learning()
    days = len(learning.get("samples", []))
    target = max(1, int(FORECAST_LEARNING_DAYS or 14))
    confidence = min(1.0, days / target)
    if days <= 0:
        text = f"lernt (0/{target} Tage)"
    elif days < target:
        text = f"lernt ({days}/{target} Tage)"
    else:
        text = f"stabilisiert ({days}/{target} Tage)"
    return {
        "learning_status": text,
        "learning_confidence": round(confidence, 2),
        "learning_target_days": target,
        "learning_target_factor": round(float(learning.get("target_factor", learning.get("factor", 1.0)) or 1.0), 4),
    }


def _apply_factor(data: Dict[str, Any], factor: float) -> Dict[str, Any]:
    out = dict(data)
    out["learning_factor"] = round(factor, 4)
    out["learning_days"] = learning_days()
    out.update(_learning_status())
    out["watts_corrected"] = {k: round(float(v or 0) * factor, 3) for k, v in data.get("watts", {}).items()}
    out["watt_hours_period_corrected"] = {k: round(float(v or 0) * factor, 3) for k, v in data.get("watt_hours_period", {}).items()}
    out["watt_hours_day_corrected"] = {k: round(float(v or 0) * factor, 3) for k, v in data.get("watt_hours_day", {}).items()}
    today = _today_key()
    raw_day_wh = (data.get("watt_hours_day") or {}).get(today)
    out["forecast_today_raw_kwh"] = round(float(raw_day_wh or 0) / 1000.0, 3)
    out["forecast_expected_until_now_kwh"] = _period_kwh_until_now(data.get("watt_hours_period", {}), factor)
    return out


def _sample_weight(actual_kwh: float, expected_kwh: float) -> float:
    # Vollere Tage sind aussagekräftiger; sehr kleine Morgen-/Abendwerte zählen kaum.
    progress = min(1.0, max(0.1, expected_kwh / 8.0))
    if actual_kwh <= MIN_ACTUAL_KWH_FOR_LEARNING or expected_kwh <= MIN_EXPECTED_KWH_FOR_LEARNING:
        return 0.0
    return round(progress, 3)


def update_learning_from_state(state: Dict[str, Any]):
    if not FORECAST_LEARNING_ENABLE:
        return
    actual = state.get("energy_today_kwh")
    if actual is None:
        return

    cache = _read_json(FORECAST_CACHE_FILE, {})
    raw_period = cache.get("watt_hours_period") or {}
    expected_until_now = _period_kwh_until_now(raw_period, 1.0)
    actual_kwh = float(actual)
    weight = _sample_weight(actual_kwh, expected_until_now)
    if weight <= 0:
        return

    ratio_raw = actual_kwh / expected_until_now
    # Harte Ausreißer ignorieren: Abschaltung, starker Datenfehler, API-Ausreißer.
    if ratio_raw < 0.35 or ratio_raw > 2.2:
        return
    ratio = max(MIN_RATIO, min(MAX_RATIO, ratio_raw))

    today = _today_key()
    target_days = max(1, int(FORECAST_LEARNING_DAYS or 14))
    learning = _read_learning()
    samples = [s for s in learning.get("samples", []) if s.get("date") != today]
    samples.append({
        "date": today,
        "actual_kwh": round(actual_kwh, 3),
        "expected_until_now_kwh": round(expected_until_now, 3),
        "ratio": round(ratio, 4),
        "raw_ratio": round(ratio_raw, 4),
        "weight": weight,
        "updated_at": datetime.now(LOCAL_TZ).isoformat(timespec="seconds"),
    })
    samples = samples[-target_days:]

    weight_sum = sum(float(s.get("weight", 1.0) or 1.0) for s in samples)
    target_factor = sum(float(s.get("ratio", 1.0)) * float(s.get("weight", 1.0) or 1.0) for s in samples) / max(weight_sum, 0.001)
    old_factor = float(learning.get("factor", 1.0) or 1.0)

    # Einlernphase: folgt schneller. Nach Ziel-Tagen: nur noch langsam nachregeln.
    if len(samples) < target_days:
        alpha = 0.35
    else:
        alpha = 0.12
    factor = (old_factor * (1.0 - alpha)) + (target_factor * alpha)
    factor = max(MIN_RATIO, min(MAX_RATIO, factor))

    _write_json(FORECAST_LEARNING_FILE, {
        "factor": round(factor, 4),
        "target_factor": round(target_factor, 4),
        "samples": samples,
        "updated_at": datetime.now(LOCAL_TZ).isoformat(timespec="seconds"),
        "method": "v2.6 weighted_until_now_slow_after_target",
        "target_days": target_days,
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
        "forecast_today_raw_kwh": float(data.get("forecast_today_raw_kwh", 0) or 0),
        "forecast_expected_until_now_kwh": float(data.get("forecast_expected_until_now_kwh", 0) or 0),
        "forecast_updated_at": data.get("updated_at"),
        "forecast_learning_factor": round(factor, 4),
        "forecast_learning_days": int(data.get("learning_days", 0) or 0),
        "forecast_learning_status": data.get("learning_status"),
        "forecast_learning_confidence": data.get("learning_confidence"),
        "forecast_learning_target_days": data.get("learning_target_days"),
        "forecast_learning_target_factor": data.get("learning_target_factor"),
    }
