import os
from datetime import datetime, timezone
from flask import Flask, Response, jsonify, request

from config import (
    FORECAST_ENABLE,
    HA_DISCOVERY,
    LOG_FILE,
    MQTT_ENABLE,
    START_FILE,
    VERSION,
    WEB_PORT,
)
from forecast_solar import get_forecast
from log_utils import clear_log, log_event, read_log_lines
from storage import history, history_day, history_status, read_state

app = Flask(__name__, static_folder="/web/static", static_url_path="")


def _parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _age_seconds(value):
    ts = _parse_ts(value)
    if not ts:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return max(0, int((datetime.now().astimezone() - ts.astimezone()).total_seconds()))



def _format_age(value):
    age = _age_seconds(value)
    if age is None:
        return "Noch kein OK"
    if age < 60:
        return "gerade eben"
    minutes = age // 60
    if minutes < 60:
        return f"vor {minutes} Min"
    hours = minutes // 60
    if hours < 24:
        return f"vor {hours} Std {minutes % 60} Min"
    days = hours // 24
    return f"vor {days} Tage"

def _traffic(ok, warn=False, disabled=False):
    if disabled:
        return "disabled"
    if ok and not warn:
        return "ok"
    if ok and warn:
        return "warn"
    return "error"


def _uptime():
    try:
        with open(START_FILE, "r", encoding="utf-8") as f:
            start = _parse_ts(f.read().strip())
        if not start:
            return None
        return max(0, int((datetime.now(timezone.utc) - start.astimezone(timezone.utc)).total_seconds()))
    except Exception:
        return None


def service_status():
    s = read_state()
    age = _age_seconds(s.get("timestamp"))
    stale = age is None or age > 900
    services = [
        {
            "name": "SBFspot",
            "status": _traffic(s.get("status") == "online", stale),
            "detail": "läuft" if s.get("status") == "online" else (s.get("last_error") or s.get("status") or "wartet"),
            "last_ok": s.get("last_sbfspot_run") or s.get("timestamp"),
        },
        {
            "name": "MQTT",
            "status": _traffic(bool(s.get("mqtt_publish_ok", MQTT_ENABLE)), False, not MQTT_ENABLE),
            "detail": "verbunden" if s.get("mqtt_publish_ok", MQTT_ENABLE) else "Publish fehlgeschlagen",
            "last_ok": s.get("last_mqtt_publish"),
        },
        {
            "name": "Forecast.Solar",
            "status": _traffic(bool(s.get("forecast_updated_at") or not FORECAST_ENABLE), False, not FORECAST_ENABLE),
            "detail": "aktiv" if FORECAST_ENABLE else "deaktiviert",
            "last_ok": s.get("forecast_updated_at"),
        },
        {
            "name": "CSV / Daten",
            "status": _traffic(age is not None and age <= 900, age is not None and age > 600),
            "detail": f"letzte Aktualisierung vor {age}s" if age is not None else "noch keine Daten",
            "last_ok": s.get("timestamp"),
        },
        {
            "name": "Home Assistant Discovery",
            "status": _traffic(bool(s.get("ha_discovery_ok", HA_DISCOVERY)), False, not HA_DISCOVERY),
            "detail": "gesendet" if s.get("ha_discovery_ok", HA_DISCOVERY) else "Fehler beim Senden",
            "last_ok": s.get("timestamp"),
        },
        {
            "name": "SQLite Historie",
            "status": _traffic(history_status().get("ok", False), False),
            "detail": f"{history_status().get('samples', 0)} Messpunkte · {round(history_status().get('size_bytes', 0) / 1024, 1)} KB",
            "last_ok": history_status().get("last_ts"),
        },
        {"name": "Webserver", "status": "ok", "detail": "läuft", "last_ok": datetime.now().astimezone().isoformat(timespec="seconds")},
    ]
    return {"version": VERSION, "uptime_seconds": _uptime(), "container_uptime_seconds": _uptime(), "last_successful_update": s.get("last_sbfspot_success"), "last_successful_update_age": _format_age(s.get("last_sbfspot_success")), "services": services, "state": s, "history": history_status()}


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/live")
@app.route("/api/state")
def api_state():
    return jsonify(read_state())


@app.route("/api/history")
def api_history():
    mode = request.args.get("mode", "day")
    fill = request.args.get("fill", "1") not in ("0", "false", "False", "no")
    if mode == "raw":
        return jsonify(history())
    return jsonify(history_day(fill_missing=fill))




@app.route("/api/history/status")
def api_history_status():
    return jsonify(history_status())

@app.route("/api/forecast")
def api_forecast():
    return jsonify(get_forecast(False))


@app.route("/api/status")
def api_status():
    s = read_state()
    return jsonify({"version": VERSION, "status": s.get("status"), "timestamp": s.get("timestamp"), "last_error": s.get("last_error", ""), "container_uptime_seconds": _uptime(), "last_successful_update": s.get("last_sbfspot_success"), "last_successful_update_age": _format_age(s.get("last_sbfspot_success"))})


@app.route("/api/services")
def api_services():
    return jsonify(service_status())


@app.route("/api/log")
def api_log():
    limit = request.args.get("limit", 300)
    return jsonify({"lines": read_log_lines(limit), "file": LOG_FILE})


@app.route("/api/log/download")
def api_log_download():
    lines = "\n".join(read_log_lines(5000)) + "\n"
    return Response(lines, mimetype="text/plain", headers={"Content-Disposition": "attachment; filename=sma-runtime.log"})


@app.route("/api/log/clear", methods=["POST"])
def api_log_clear():
    clear_log()
    log_event("INFO", "Log über WebGUI geleert")
    return jsonify({"ok": True})


if __name__ == "__main__":
    log_event("INFO", f"Webserver gestartet · Version {VERSION}")
    app.run(host="0.0.0.0", port=WEB_PORT)
