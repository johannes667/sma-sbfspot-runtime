import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from config import (
    FORECAST_API_KEY,
    FORECAST_AZIMUTH,
    FORECAST_CACHE_FILE,
    FORECAST_DAMPING,
    FORECAST_DECLINATION,
    FORECAST_ENABLE,
    FORECAST_INTERVAL,
    FORECAST_INVERTER_KW,
    FORECAST_KWP,
    FORECAST_LATITUDE,
    FORECAST_LONGITUDE,
)
from forecast_learning import current_factor, refresh_learning


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(str(value).replace(",", "."))
    except Exception:
        return None


def _read_cache() -> Dict[str, Any]:
    try:
        with open(FORECAST_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_cache(data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(FORECAST_CACHE_FILE), exist_ok=True)
    tmp = FORECAST_CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, FORECAST_CACHE_FILE)


def _api_url() -> str:
    lat = urllib.parse.quote(str(FORECAST_LATITUDE), safe="")
    lon = urllib.parse.quote(str(FORECAST_LONGITUDE), safe="")
    dec = urllib.parse.quote(str(FORECAST_DECLINATION), safe="")
    az = urllib.parse.quote(str(FORECAST_AZIMUTH), safe="")
    kwp = urllib.parse.quote(str(FORECAST_KWP), safe="")
    prefix = f"/{urllib.parse.quote(FORECAST_API_KEY, safe='')}" if FORECAST_API_KEY else ""
    url = f"https://api.forecast.solar{prefix}/estimate/{lat}/{lon}/{dec}/{az}/{kwp}"

    params = {}
    if FORECAST_DAMPING not in ("", "0", "0.0"):
        params["damping"] = FORECAST_DAMPING
    if FORECAST_INVERTER_KW:
        params["inverter"] = FORECAST_INVERTER_KW
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url


def _parse_dt(text: str) -> Optional[datetime]:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is not None:
                return dt.astimezone().replace(tzinfo=None)
            return dt
        except Exception:
            pass
    try:
        return datetime.fromisoformat(text).astimezone().replace(tzinfo=None)
    except Exception:
        return None


def _scale(value: Optional[float], factor: float, digits: int = 3) -> Optional[float]:
    if value is None:
        return None
    return round(max(0.0, value * factor), digits)


def _clean_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    learning = refresh_learning()
    factor = current_factor()

    result = payload.get("result", payload)
    watts = result.get("watts") or result.get("watt") or {}
    watt_hours_day = result.get("watt_hours_day") or {}
    watt_hours_period = result.get("watt_hours_period") or {}

    raw_points: List[Dict[str, Any]] = []
    corrected_points: List[Dict[str, Any]] = []
    for ts, value in watts.items():
        dt = _parse_dt(str(ts))
        val = _to_float(value)
        if dt is not None and val is not None:
            raw_w = max(0.0, val)
            raw_points.append({"ts": dt.isoformat(timespec="minutes"), "w": round(raw_w, 1)})
            corrected_points.append({"ts": dt.isoformat(timespec="minutes"), "w": round(raw_w * factor, 1)})
    raw_points.sort(key=lambda p: p["ts"])
    corrected_points.sort(key=lambda p: p["ts"])

    now = datetime.now()
    today_key = now.date().isoformat()
    tomorrow_key = (now.date() + timedelta(days=1)).isoformat()

    today_wh = _to_float(watt_hours_day.get(today_key))
    tomorrow_wh = _to_float(watt_hours_day.get(tomorrow_key))

    def _nearest_power(points: List[Dict[str, Any]], min_dt: Optional[datetime] = None) -> Optional[float]:
        parsed = [(p, _parse_dt(p["ts"])) for p in points]
        parsed = [(p, dt) for p, dt in parsed if dt is not None]
        if min_dt is not None:
            parsed = [(p, dt) for p, dt in parsed if dt >= min_dt]
            return parsed[0][0]["w"] if parsed else None
        if parsed:
            return min(parsed, key=lambda item: abs((item[1] - now).total_seconds()))[0]["w"]
        return None

    raw_now_power = _nearest_power(raw_points)
    corrected_now_power = _nearest_power(corrected_points)
    corrected_next_hour_power = _nearest_power(corrected_points, now + timedelta(hours=1))

    remaining_wh_raw = 0.0
    for ts, value in watt_hours_period.items():
        dt = _parse_dt(str(ts))
        val = _to_float(value)
        if dt is not None and val is not None and dt >= now and dt.date() == now.date():
            remaining_wh_raw += val

    today_raw_kwh = round(today_wh / 1000, 3) if today_wh is not None else None
    tomorrow_raw_kwh = round(tomorrow_wh / 1000, 3) if tomorrow_wh is not None else None
    remaining_raw_kwh = round(remaining_wh_raw / 1000, 3) if remaining_wh_raw else None

    return {
        "forecast_updated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "forecast_correction_factor": round(factor, 3),
        "forecast_accuracy_days": learning.get("days_used", 0),
        "forecast_today_raw_kwh": today_raw_kwh,
        "forecast_tomorrow_raw_kwh": tomorrow_raw_kwh,
        "forecast_power_now_raw_w": raw_now_power,
        "forecast_today_kwh": _scale(today_raw_kwh, factor),
        "forecast_tomorrow_kwh": _scale(tomorrow_raw_kwh, factor),
        "forecast_remaining_today_kwh": _scale(remaining_raw_kwh, factor),
        "forecast_power_now_w": corrected_now_power,
        "forecast_power_next_hour_w": corrected_next_hour_power,
        "forecast_points": corrected_points[:240],
        "forecast_points_raw": raw_points[:240],
        "forecast_rate_limit": payload.get("message", {}).get("ratelimit", {}) if isinstance(payload.get("message"), dict) else {},
    }


def get_forecast(force: bool = False) -> Dict[str, Any]:
    if not FORECAST_ENABLE:
        return {}

    cache = _read_cache()
    cache_age = time.time() - float(cache.get("fetched_at", 0) or 0)
    if cache and not force and cache_age < FORECAST_INTERVAL:
        data = cache.get("data", {})
        # Faktor auch zwischen API-Abfragen frisch halten.
        factor = current_factor()
        data["forecast_correction_factor"] = round(factor, 3)
        return data

    try:
        req = urllib.request.Request(_api_url(), headers={"User-Agent": "sma-sbfspot-runtime/2.2"})
        with urllib.request.urlopen(req, timeout=25) as res:
            payload = json.loads(res.read().decode("utf-8"))
        data = _clean_payload(payload)
        _write_cache({"fetched_at": time.time(), "data": data})
        return data
    except Exception as e:
        old = cache.get("data", {}) if cache else {}
        if old:
            old["forecast_last_error"] = str(e)
            return old
        return {"forecast_last_error": str(e)}
