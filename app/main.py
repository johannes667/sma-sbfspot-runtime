import os
from datetime import datetime, timezone
from flask import Flask, Response, jsonify, request

from config import (
    FORECAST_ENABLE,
    HA_DISCOVERY,
    LOG_FILE,
    MQTT_ENABLE,
    VERSION,
    WEB_PORT,
)
from forecast_solar import get_forecast, forecast_summary
from log_utils import clear_log, log_event, read_log_lines
from storage import history, history_day, history_status, read_state

app = Flask(__name__, static_folder="/web/static", static_url_path="")

# Fallback nur für Sonderfälle. Die echte Container-Uptime kommt unten aus /proc/1/stat.
PROCESS_STARTED_AT = datetime.now(timezone.utc)


def _parse_ts(value):
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        pass
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=datetime.now().astimezone().tzinfo)
        except Exception:
            pass
    return None


def _format_ts(value):
    ts = _parse_ts(value)
    if not ts:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return ts.astimezone().strftime("%d.%m.%Y %H:%M:%S")


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



def _start_time_from_file():
    # Wird von /app/entrypoint.sh bei jedem echten Containerstart neu geschrieben.
    # Liegt absichtlich NICHT in /data, damit es nicht über Container-Neustarts persistiert.
    for path in ("/tmp/sbfspot_container_started_at", "/run/sbfspot_container_started_at"):
        try:
            if os.path.exists(path):
                text = open(path, "r", encoding="utf-8").read().strip()
                ts = _parse_ts(text)
                if ts:
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    return ts.astimezone(timezone.utc)
        except Exception:
            pass
    return None

def _container_started_at():
    """Return container start time.

    Primär nutzen wir die Datei, die entrypoint.sh bei jedem echten Docker-Start
    nach /tmp schreibt. Das ist zuverlässiger als /data, weil /data persistent ist,
    und zuverlässiger als reine Python-Prozesszeit, weil der Webprozess neu starten kann.
    Falls die Datei fehlt, fallback auf /proc/1/stat und zuletzt auf Prozessstart.
    """
    start_from_file = _start_time_from_file()
    if start_from_file:
        return start_from_file

    try:
        boot_time = None
        with open("/proc/stat", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("btime "):
                    boot_time = int(line.split()[1])
                    break

        with open("/proc/1/stat", "r", encoding="utf-8") as f:
            stat = f.read().strip()

        after_comm = stat.rsplit(")", 1)[1].strip().split()
        start_ticks = int(after_comm[19])
        ticks_per_second = os.sysconf("SC_CLK_TCK")

        if boot_time and ticks_per_second:
            start_epoch = boot_time + (start_ticks / ticks_per_second)
            return datetime.fromtimestamp(start_epoch, tz=timezone.utc)
    except Exception:
        pass

    return PROCESS_STARTED_AT


def _uptime():
    start = _container_started_at()
    return max(0, int((datetime.now(timezone.utc) - start).total_seconds()))


def _runtime_meta():
    start = _container_started_at()
    uptime = _uptime()
    return {
        "container_started_at": start.isoformat(timespec="seconds"),
        "container_started_at_display": _format_ts(start.isoformat(timespec="seconds")),
        "container_uptime_seconds": uptime,
        "uptime_seconds": uptime,
        "uptime_h": uptime // 3600,
        "uptime_min": (uptime % 3600) // 60,
    }


def service_status():
    s = read_state()
    age = _age_seconds(s.get("timestamp"))
    stale = age is None or age > 900
    services = [
        {
            "name": "SBFspot",
            "status": _traffic(s.get("status") == "online", stale),
            "detail": "läuft" if s.get("status") == "online" else (s.get("last_error") or s.get("status") or "wartet"),
            "last_ok": _format_ts(s.get("last_sbfspot_success") or s.get("last_sbfspot_run") or s.get("timestamp")),
        },
        {
            "name": "MQTT",
            "status": _traffic(bool(s.get("mqtt_publish_ok", MQTT_ENABLE)), False, not MQTT_ENABLE),
            "detail": "verbunden" if s.get("mqtt_publish_ok", MQTT_ENABLE) else "Publish fehlgeschlagen",
            "last_ok": _format_ts(s.get("last_mqtt_publish")),
        },
        {
            "name": "Forecast.Solar",
            "status": _traffic(bool(s.get("forecast_updated_at") or not FORECAST_ENABLE), False, not FORECAST_ENABLE),
            "detail": "aktiv" if FORECAST_ENABLE else "deaktiviert",
            "last_ok": _format_ts(s.get("forecast_updated_at")),
        },
        {
            "name": "CSV / Daten",
            "status": _traffic(age is not None and age <= 900, age is not None and age > 600),
            "detail": f"letzte Aktualisierung vor {age}s" if age is not None else "noch keine Daten",
            "last_ok": _format_ts(s.get("timestamp")),
        },
        {
            "name": "Home Assistant Discovery",
            "status": _traffic(bool(s.get("ha_discovery_ok", HA_DISCOVERY)), False, not HA_DISCOVERY),
            "detail": "gesendet" if s.get("ha_discovery_ok", HA_DISCOVERY) else "Fehler beim Senden",
            "last_ok": _format_ts(s.get("timestamp")),
        },
        {
            "name": "SQLite Historie",
            "status": _traffic(history_status().get("ok", False), False),
            "detail": f"{history_status().get('samples', 0)} Messpunkte · {round(history_status().get('size_bytes', 0) / 1024, 1)} KB",
            "last_ok": history_status().get("last_ts_display") or _format_ts(history_status().get("last_ts")),
        },
        {"name": "Webserver", "status": "ok", "detail": "läuft", "last_ok": _format_ts(datetime.now().astimezone().isoformat(timespec="seconds"))},
    ]
    meta = _runtime_meta()
    return {"version": VERSION, **meta, "last_successful_update": s.get("last_sbfspot_success"), "last_successful_update_display": _format_ts(s.get("last_sbfspot_success")), "last_successful_update_age": _format_age(s.get("last_sbfspot_success")), "services": services, "state": {**s, **meta}, "history": history_status()}


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/live")
@app.route("/api/state")
def api_state():
    s = read_state()
    return jsonify({**s, **_runtime_meta()})


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
    data = get_forecast(False)
    state = read_state()
    if data.get("enabled", True):
        data["summary"] = forecast_summary(data, state.get("energy_today_kwh"))
    return jsonify(data)


@app.route("/api/status")
def api_status():
    s = read_state()
    return jsonify({"version": VERSION, "status": s.get("status"), "timestamp": s.get("timestamp"), "timestamp_display": _format_ts(s.get("timestamp")), "last_error": s.get("last_error", ""), **_runtime_meta(), "last_successful_update": s.get("last_sbfspot_success"), "last_successful_update_display": _format_ts(s.get("last_sbfspot_success")), "last_successful_update_age": _format_age(s.get("last_sbfspot_success"))})


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
