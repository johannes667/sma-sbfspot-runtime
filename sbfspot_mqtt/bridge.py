"""Single-inverter Bluetooth or Sunny WebBox -> MQTT bridge. No web server or local history."""
import json
import hashlib
from http.client import HTTPException
import socket
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler
import logging
import math
import os
from pathlib import Path
import re
import signal
import sys
import ssl
import subprocess
import threading
import time
from urllib.request import Request, urlopen

LOG = logging.getLogger("sbfspot")
# key: (SBFspot debug label, unit, HA device class, HA state class)
SENSORS = {
    "power_w": ("SPOT_PACTOT", "W", "power", "measurement"),
    "energy_today_kwh": ("SPOT_ETODAY", "kWh", "energy", "total_increasing"),
    "energy_total_kwh": ("SPOT_ETOTAL", "kWh", "energy", "total_increasing"),
    "temperature_c": ("Device Temperature", "°C", "temperature", "measurement"),
    "frequency_hz": ("SPOT_FREQ", "Hz", "frequency", "measurement"),
    "operation_time_h": ("SPOT_OPERTM", "h", "duration", "total_increasing"),
    "feed_in_time_h": ("SPOT_FEEDTM", "h", "duration", "total_increasing"),
}
for n in (1, 2, 3):
    SENSORS[f"pac{n}_w"] = (f"SPOT_PAC{n}", "W", "power", "measurement")
    SENSORS[f"ac_voltage_{n}_v"] = (f"SPOT_UAC{n}", "V", "voltage", "measurement")
    SENSORS[f"ac_current_{n}_a"] = (f"SPOT_IAC{n}", "A", "current", "measurement")
for n in (1, 2):
    SENSORS[f"pdc{n}_w"] = (f"SPOT_PDC{n}", "W", "power", "measurement")
    SENSORS[f"dc_voltage_{n}_v"] = (f"SPOT_UDC{n}", "V", "voltage", "measurement")
    SENSORS[f"dc_current_{n}_a"] = (f"SPOT_IDC{n}", "A", "current", "measurement")


def parse_output(output):
    values = {}
    if "INFO: Done." not in output:
        return values
    for key, (label, unit, _, _) in SENSORS.items():
        match = re.search(rf"^\s*{re.escape(label)}\s*:\s*([-+]?\d+(?:[.,]\d+)?)", output, re.M)
        if match:
            value = float(match[1].replace(",", "."))
            if math.isfinite(value) and abs(value) < 1e12 and value != -2147483648:
                if unit not in ("°C", "W") and value < 0:
                    continue
                values[key] = int(value) if value.is_integer() else value
    return values


# Only aliases evidenced in SMA SWebBoxRPC-BA-en-14, sections 7.3/7.4.
# Bluetooth WebBox channel names must be confirmed using the diagnostic first.
WEBBOX_CHANNELS = {
    "power_w": "Pac", "energy_total_kwh": "E-Total", "frequency_hz": "Fac",
}
UNIT_FACTORS = {
    "W": {"W": 1, "kW": 1000}, "kWh": {"Wh": .001, "kWh": 1, "MWh": 1000},
    "V": {"V": 1, "mV": .001}, "A": {"A": 1, "mA": .001},
    "Hz": {"Hz": 1}, "°C": {"°C": 1}, "h": {"h": 1, "s": 1 / 3600},
}


class WebBoxError(ValueError):
    """Sanitized error: never include remote text, URLs or credentials."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def webbox_mapping(options):
    mapping = dict(WEBBOX_CHANNELS)
    for item in options.get("webbox_channels", []):
        if (not isinstance(item, dict) or item.get("sensor") not in SENSORS
                or not isinstance(item.get("channel"), str) or not item["channel"].strip()):
            raise ValueError("Ungültiges WebBox-Kanal-Mapping")
        mapping[item["sensor"]] = item["channel"]
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("WebBox-Kanäle dürfen nicht mehrfach zugeordnet werden")
    return mapping


def parse_webbox(channels, mapping):
    if not isinstance(channels, list):
        raise WebBoxError("RPC: ungültige Kanalliste")
    values = {}
    for key, meta in mapping.items():
        matches = [c for c in channels if isinstance(c, dict) and c.get("meta") == meta]
        if len(matches) != 1:
            continue
        channel = matches[0]
        raw = channel.get("value")
        unit = channel.get("unit")
        if not isinstance(unit, str):
            continue
        factor = UNIT_FACTORS[SENSORS[key][1]].get(unit)
        if factor is None or isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
            continue
        # RPC numbers use a decimal point; do not guess localized separators.
        if len(str(raw)) > 64 or not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", str(raw).strip()):
            continue
        number = float(raw)
        if not math.isfinite(number) or number in (-2147483648, 2147483647, 4294967295):
            continue
        value = number * factor
        if abs(value) >= 1e12 or (value < 0 and SENSORS[key][1] not in ("W", "°C")):
            continue
        values[key] = int(value) if value.is_integer() else value
    return values


def device_list(result):
    devices = []
    def visit(items, depth=0):
        if not isinstance(items, list) or depth > 16:
            raise WebBoxError("RPC: ungültige Geräteliste")
        for device in items:
            if not isinstance(device, dict) or not isinstance(device.get("key"), str):
                raise WebBoxError("RPC: ungültiges Gerät")
            devices.append(device)
            if device.get("children") is not None:
                visit(device["children"], depth + 1)
    visit(result.get("devices"))
    return devices


class WebBox:
    def __init__(self, options):
        host = options.get("webbox_host", "")
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", host):
            raise ValueError("webbox_host muss eine IPv4-Adresse oder ein Hostname sein")
        port = int(options.get("webbox_port", 80))
        self.timeout = int(options.get("webbox_timeout_seconds", 10))
        if not 1 <= port <= 65535 or not 1 <= self.timeout <= 60:
            raise ValueError("Ungültiger WebBox-Port oder Timeout")
        self.url = f"http://{host}:{port}/rpc"
        password = options.get("webbox_password", "")
        self.password_hash = hashlib.md5(password.encode("utf-8")).hexdigest() if password else None
        self.key = options.get("webbox_device_key", "")
        self.mapping = webbox_mapping(options)
        self.selected = None
        self.next_rpc = 0
        # LAN requests must not use an external HTTP proxy. Reject redirects.
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def rpc(self, procedure, params, stop):
        if procedure not in ("GetDevices", "GetProcessData", "GetPlantOverview"):
            raise WebBoxError("Nicht erlaubte RPC-Prozedur")
        if stop.wait(max(0, self.next_rpc - time.monotonic())):
            raise WebBoxError("RPC abgebrochen")
        request_id = uuid.uuid4().hex[:16]
        payload = {"version": "1.0", "proc": procedure, "id": request_id, "format": "JSON"}
        if params is not None:
            payload["params"] = params
        if self.password_hash:
            payload["passwd"] = self.password_hash
        # WebBox HTTP transport wraps the serialized RPC object with RPC=.
        # See SunnyWebBoxHTTP._rpc in github.com/ravz/SunnyWebBox.
        request = Request(self.url, data=("RPC=" + json.dumps(payload)).encode("utf-8"),
                          headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        started = time.monotonic()
        status = "error"
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise WebBoxError("RPC-Antwort zu groß")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise WebBoxError("RPC: ungültige Antwort")
            if "error" in result:
                raise WebBoxError("RPC-Fehler (Zugangsdaten und RPC-Freigabe prüfen)")
            if (result.get("id") != request_id or result.get("proc") != procedure
                    or result.get("version") != "1.0" or not isinstance(result.get("result"), dict)):
                raise WebBoxError("RPC: Antwort passt nicht zur Anfrage")
            status = "ok"
            return result["result"]
        except HTTPError as error:
            raise WebBoxError(f"HTTP-Fehler {error.code}") from None
        except (TimeoutError, socket.timeout):
            raise WebBoxError("RPC-Zeitlimit erreicht") from None
        except URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise WebBoxError("RPC-Zeitlimit erreicht") from None
            raise WebBoxError("RPC-Netzwerkfehler") from None
        except (OSError, HTTPException):
            raise WebBoxError("RPC-Netzwerkfehler") from None
        except (UnicodeError, ValueError, RecursionError) as error:
            if isinstance(error, WebBoxError):
                raise
            raise WebBoxError("RPC: ungültiges JSON") from None
        finally:
            # Enforce SMA's minimum for EVERY request, including errors/discovery.
            self.next_rpc = time.monotonic() + 30
            LOG.debug("WebBox RPC %s: Status %s, Dauer %.2fs", procedure, status,
                      time.monotonic() - started)

    def read(self, stop):
        if self.selected is None:
            devices = device_list(self.rpc("GetDevices", None, stop))
            if self.key:
                candidates = [d for d in devices if d["key"] == self.key]
            else:
                # Never silently select a logger, meter or one of several inverters.
                candidates = [d for d in devices if d["key"].startswith(("SB", "WR"))]
            if len(candidates) != 1:
                raise WebBoxError("Geräteauswahl uneindeutig: Diagnose ausführen und webbox_device_key setzen")
            self.selected = candidates[0]["key"]
        result = self.rpc("GetProcessData", {"devices": [{"key": self.selected, "channels": None}]}, stop)
        devices = device_list(result)
        matches = [d for d in devices if d["key"] == self.selected]
        if len(matches) != 1:
            self.selected = None
            raise WebBoxError("RPC: ausgewähltes Gerät fehlt")
        values = parse_webbox(matches[0].get("channels"), self.mapping)
        LOG.debug("WebBox Messung: %s gültige Messwerte", len(values))
        return values


def read_webbox(webbox, stop, maintain):
    # One worker per acquisition; joined before another query can start.
    # Main thread continues sensor expiry/MQTT during HTTP and RPC rate limiting.
    result = []
    errors = []
    def run():
        try:
            result.append(webbox.read(stop))
        except Exception as error:
            errors.append(error)
    worker = threading.Thread(target=run, name="webbox-read", daemon=True)
    worker.start()
    while worker.is_alive():
        worker.join(.25)
        maintain()
    if errors:
        raise errors[0]
    return result[0]


def configure_source(options):
    source = options.get("source", "bluetooth")
    if source not in ("bluetooth", "webbox"):
        raise ValueError("Ungültige Datenquelle")
    if source == "webbox":
        if int(options["poll_seconds"]) < 30:
            raise ValueError("WebBox benötigt poll_seconds >= 30")
        return WebBox(options)
    cfg = "/data/SBFspot.cfg"
    write_config(options, Path("/usr/local/share/SBFspot.default.cfg").read_text(), cfg)
    return cfg


def write_config(options, template, target):
    overrides = {
        "BTAddress": options["inverter_bluetooth_address"],
        "LocalBTAddress": options.get("local_bluetooth_address") or "00:00:00:00:00:00",
        "Password": options["inverter_password"], "Timezone": options["timezone"],
        "Plantname": "SMA", "OutputPath": "/tmp", "OutputPathEvents": "/tmp",
        "CSV_Export": "0", "SynchTime": "0", "MIS_Enabled": "0",
        "Locale": "en-US", "DecimalPoint": "point", "BTConnectRetries": "2",
    }
    mac = r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}"
    for key in ("BTAddress", "LocalBTAddress"):
        if not re.fullmatch(mac, overrides[key]):
            raise ValueError(f"Ungültige Bluetooth-Adresse: {key}")
    if overrides["BTAddress"] == "00:00:00:00:00:00":
        raise ValueError("Bitte die Bluetooth-Adresse des Wechselrichters konfigurieren")
    if not 1 <= len(overrides["Password"]) <= 12:
        raise ValueError("Wechselrichter-Passwort muss 1 bis 12 Zeichen haben")
    for value in overrides.values():
        if any(c in str(value) for c in "\r\n\x00"):
            raise ValueError("Zeilenumbrüche in SBFspot-Optionen sind unzulässig")
    lines = [line for line in template.splitlines()
             if line.split("=", 1)[0].strip() not in overrides]
    lines += [f"{key}={value}" for key, value in overrides.items()]
    # Contains the inverter password; stay in the private add-on data directory.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write("\n".join(lines) + "\n")


def broker_settings(options):
    if options.get("mqtt_host"):
        return {"host": options["mqtt_host"], "port": options["mqtt_port"],
                "username": options.get("mqtt_username"), "password": options.get("mqtt_password"),
                "ssl": options.get("mqtt_tls", False)}
    request = Request("http://supervisor/services/mqtt", headers={
        "Authorization": "Bearer " + os.environ.get("SUPERVISOR_TOKEN", "")})
    with urlopen(request, timeout=15) as response:
        result = json.load(response)
    if result.get("result") != "ok":
        raise ValueError("MQTT-Dienst nicht verfügbar; Mosquitto einrichten oder mqtt_host setzen")
    return result["data"]


class Publisher:
    def __init__(self, client, options):
        self.client = client
        self.options = options
        self.cache = {}
        self.connected = threading.Event()
        self.reset = threading.Event()
        self.base = options["mqtt_base_topic"].strip("/")
        self.availability = self.base + "/availability"

    def publish(self, topic, payload):
        if not self.connected.is_set():
            return False
        payload = str(payload)
        if self.cache.get(topic) == payload:
            return True
        try:
            info = self.client.publish(topic, payload, qos=1, retain=True)
            info.wait_for_publish(timeout=10)
            if info.rc != 0 or not info.is_published():
                return False
        except (RuntimeError, ValueError):
            return False
        self.cache[topic] = payload
        return True

    def flush_reset(self):
        if self.reset.is_set():
            self.reset.clear()
            self.cache.clear()

    def send_values(self, values, unavailable=()):
        for key in unavailable:
            if not self.publish(f"{self.base}/{key}/availability", "offline"):
                return False
        for key, value in values.items():
            if self.options["discovery"]:
                _, unit, device_class, state_class = SENSORS[key]
                device_id = self.options["device_id"]
                payload = {
                    "name": key.replace("_", " "), "unique_id": f"{device_id}_{key}",
                    "state_topic": f"{self.base}/{key}",
                    "availability": [{"topic": self.availability},
                                     {"topic": f"{self.base}/{key}/availability"}],
                    "availability_mode": "all",
                    "unit_of_measurement": unit, "device_class": device_class,
                    "state_class": state_class,
                    "device": {"identifiers": [device_id],
                               "name": self.options["device_name"], "manufacturer": "SMA",
                               "model": "Sunny WebBox LAN" if self.options.get("source") == "webbox" else "SBFspot Bluetooth"},
                }
                topic = f'{self.options["discovery_prefix"].strip("/")}/sensor/{device_id}/{key}/config'
                if not self.publish(topic, json.dumps(payload, sort_keys=True)):
                    return False
            if not self.publish(f"{self.base}/{key}", value):
                return False
            if not self.publish(f"{self.base}/{key}/availability", "online"):
                return False
        return self.publish(self.availability, "online" if values else "offline")



class Measurements:
    """Keep last real reading per sensor, with independent monotonic expiry."""
    def __init__(self, stale_after):
        self.stale_after = stale_after
        self.values = {}
        self.updated = {}

    def update(self, values, now):
        self.values.update(values)
        self.updated.update({key: now for key in values})

    def fresh(self, now):
        return {key: value for key, value in self.values.items()
                if now - self.updated[key] < self.stale_after}


def failure_reason(output, returncode):
    """Only return fixed labels/codes. Never log raw config or inverter output."""
    lower = output.lower()
    if "check 'user' password" in lower or "check 'installer' password" in lower:
        return "Anmeldung: Wechselrichter-Passwort abgelehnt"
    if "logon failed" in lower:
        return "Anmeldung fehlgeschlagen"
    if any(word in lower for word in ("bthconnect() returned", "failed to initialise communication", "no route to host", "connection timed out", "can't connect")):
        return "Bluetooth-Verbindung oder Initialisierung fehlgeschlagen"
    getters = re.findall(r"(get[A-Za-z0-9]+) returned an error:\s*(-?\d+)", output)
    if getters:
        return "SBFspot-Lesefehler: " + ", ".join(f"{name}={code}" for name, code in getters[:4])
    if "info: done." not in lower:
        return f"SBFspot-Ausgabe unvollständig (Exit {returncode})"
    return f"Keine gültigen Messwerte (Exit {returncode})"


def read_inverter(cfg, stop, maintain, timeout=90):
    started = time.monotonic()
    command = ["/usr/local/bin/SBFspot", "-d2", "-v2", "-finq", "-nocsv", "-nosql",
               "-ad0", "-am0", "-ae0", f"-cfg:{cfg}"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, errors="replace")
    try:
        while not stop.is_set():
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise ValueError("SBFspot-Zeitlimit erreicht")
            try:
                output, _ = process.communicate(timeout=min(1, remaining))
                return output, process.returncode
            except subprocess.TimeoutExpired:
                maintain()
        return "", -1
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def retry_pause(poll_seconds, failures):
    return min(max(poll_seconds, 300), poll_seconds * 2 ** min(max(failures - 1, 0), 4))


def diagnose_webbox():
    """Read-only diagnostic. Never output request payloads or credentials."""
    options = json.loads(Path("/data/options.json").read_text())
    webbox = WebBox(options)
    stop = threading.Event()
    devices = device_list(webbox.rpc("GetDevices", None, stop))
    print(json.dumps({"devices": [{"key": d["key"]} for d in devices]}, ensure_ascii=False), flush=True)
    if not webbox.key:
        print("webbox_device_key setzen und Diagnose erneut starten.", flush=True)
        return
    if webbox.key not in [d["key"] for d in devices]:
        raise WebBoxError("Konfiguriertes Gerät nicht gefunden")
    result = webbox.rpc("GetProcessData", {"devices": [{"key": webbox.key, "channels": None}]}, stop)
    for device in device_list(result):
        if device["key"] == webbox.key:
            channels = device.get("channels")
            if not isinstance(channels, list):
                raise WebBoxError("RPC: ungültige Kanalliste")
            print(json.dumps({"channels": [{k: c.get(k) for k in ("meta", "name", "value", "unit")}
                                           for c in channels if isinstance(c, dict)],
                              "mapped_values": parse_webbox(channels, webbox.mapping)},
                             ensure_ascii=False, indent=2), flush=True)


def main():
    options = json.loads(Path("/data/options.json").read_text())
    if options.get("source", "bluetooth") == "webbox" and options.get("webbox_diagnostics", False):
        diagnose_webbox()
        return

    import paho.mqtt.client as mqtt
    logging.getLogger().setLevel(str(options.get("log_level", "info")).upper())
    for key in ("mqtt_base_topic", "discovery_prefix"):
        if not options[key].strip("/") or any(c in options[key] for c in "+#\x00"):
            raise ValueError(f"Ungültiges MQTT-Topic: {key}")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", options["device_id"]):
        raise ValueError("Ungültige device_id")
    poll_seconds = int(options["poll_seconds"])
    stale_after = int(options.get("stale_after_seconds", 180))
    retry_seconds = int(options.get("retry_seconds", 5))
    if not 10 <= poll_seconds <= 3600:
        raise ValueError("poll_seconds muss zwischen 10 und 3600 liegen")
    if not 30 <= stale_after <= 7200 or not 1 <= retry_seconds <= 60:
        raise ValueError("Ungültige Wartezeit für Messwertalter oder Wiederholung")
    if stale_after <= poll_seconds:
        LOG.warning("stale_after_seconds sollte größer als poll_seconds plus Abfragedauer sein")
    reader = configure_source(options)
    broker = broker_settings(options)
    client = mqtt.Client(client_id=options["device_id"] + "_bridge")
    client.max_queued_messages_set(100)
    publisher = Publisher(client, options)
    measurements = Measurements(stale_after)
    stop = threading.Event()
    failures = 0
    had_error = False
    last_success = None
    mqtt_failed = False
    next_read = 0
    second_attempt = False
    last_partial_reason = None

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            publisher.reset.set()
            publisher.connected.set()
            if options["discovery"]:
                client.subscribe(options["discovery_prefix"].strip("/") + "/status", qos=1)
            LOG.info("MQTT verbunden; gültige Messwerte werden erneut übertragen")
        else:
            LOG.error("MQTT-Anmeldung abgelehnt (Code %s)", rc)

    def on_disconnect(client, userdata, rc):
        publisher.connected.clear()
        publisher.reset.set()
        if rc:
            LOG.warning("MQTT-Verbindung unterbrochen (Code %s); automatische Wiederverbindung", rc)

    def on_message(client, userdata, message):
        if message.payload == b"online":
            publisher.reset.set()

    def maintain():
        nonlocal mqtt_failed
        if not publisher.connected.is_set():
            return
        publisher.flush_reset()
        fresh = measurements.fresh(time.monotonic())
        unavailable = sorted(set(SENSORS) - set(fresh))
        success = publisher.send_values(fresh, unavailable)
        status = ("online" if fresh and not had_error else "retrying" if fresh
                  else "stale" if measurements.values else "error" if had_error else "waiting")
        success = publisher.publish(publisher.base + "/status", status) and success
        if not success and not mqtt_failed:
            LOG.warning("MQTT-Übertragung unvollständig; nicht bestätigte Werte werden erneut gesendet")
        elif success and mqtt_failed:
            LOG.info("MQTT-Übertragung wieder vollständig")
        mqtt_failed = not success

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    if broker.get("username"):
        client.username_pw_set(broker["username"], broker.get("password"))
    if broker.get("ssl"):
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    client.will_set(publisher.availability, "offline", qos=1, retain=True)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    client.connect_async(broker["host"], int(broker["port"]), keepalive=30)
    client.loop_start()
    LOG.info("SBFspot MQTT gestartet; Pause %ss, Wiederholung nach %ss, Messwertalter maximal %ss",
             poll_seconds, retry_seconds, stale_after)
    try:
        while not stop.is_set():
            maintain()
            if time.monotonic() < next_read:
                stop.wait(0.5)
                continue
            started = time.monotonic()
            try:
                if isinstance(reader, WebBox):
                    values = read_webbox(reader, stop, maintain)
                    output, returncode = "INFO: Done.", 0
                else:
                    output, returncode = read_inverter(reader, stop, maintain)
                    values = parse_output(output)
                if stop.is_set():
                    break
                # SBFspot can return a nonzero exit code for an optional failed
                # getter even though other independently measured values are valid.
                if not values:
                    raise ValueError("WebBox: keine gültigen zugeordneten Messwerte; Kanaldiagnose prüfen"
                                     if isinstance(reader, WebBox) else failure_reason(output, returncode))
                now = time.monotonic()
                measurements.update(values, now)
                if had_error:
                    age = f"{now - last_success:.0f}s" if last_success is not None else "Start"
                    LOG.info("Messung wieder gültig nach %s; AC=%s W", age, values.get("power_w", "—"))
                partial_reason = failure_reason(output, returncode) if returncode else None
                if partial_reason and partial_reason != last_partial_reason:
                    LOG.warning("Teilweise gültige Messung: %s Werte, Exit %s; %s",
                                len(values), returncode, partial_reason)
                last_partial_reason = partial_reason
                if isinstance(reader, WebBox):
                    LOG.debug("WebBox-Zyklus in %.1fs: %s gültige Messwerte", now - started, len(values))
                else:
                    signal_match = re.search(r"BT Signal=([0-9.]+)%", output)
                    LOG.debug("Messung in %.1fs, Exit %s, BT-Signal %s%%: %s", now - started,
                              returncode, signal_match[1] if signal_match else "—",
                              json.dumps(values, sort_keys=True))
                failures = 0
                had_error = False
                last_success = now
                second_attempt = False
                next_read = now + poll_seconds
            except (OSError, ValueError) as error:
                had_error = True
                if not second_attempt:
                    second_attempt = True
                    delay = max(30, retry_seconds) if isinstance(reader, WebBox) else retry_seconds
                else:
                    failures += 1
                    second_attempt = False
                    delay = retry_pause(poll_seconds, failures)
                LOG.warning("Abfrage fehlgeschlagen (%.1fs): %s; nächster Versuch in %ss",
                            time.monotonic() - started, error, delay)
                next_read = time.monotonic() + delay
            maintain()
    finally:
        publisher.flush_reset()
        publisher.publish(publisher.availability, "offline")
        client.disconnect()
        client.loop_stop()


def log_start_failure(error):
    # Only WebBoxError contains our own fixed, sanitized messages. Never log
    # arbitrary exception text (options, HTTP responses or passwords).
    if isinstance(error, WebBoxError):
        LOG.error("WebBox-Start fehlgeschlagen: %s", error)
    else:
        LOG.error("Start fehlgeschlagen (%s). Add-on- und MQTT-Konfiguration prüfen.", type(error).__name__)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if sys.argv[1:] == ["--diagnose-webbox"]:
            diagnose_webbox()
        elif sys.argv[1:]:
            raise ValueError("Unbekannte Argumente")
        else:
            main()
    except Exception as error:
        log_start_failure(error)
        raise SystemExit(1)
