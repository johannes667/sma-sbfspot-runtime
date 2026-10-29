"""Read one SMA inverter via Bluetooth and publish changed MQTT values."""
import json
import logging
import math
import os
import re
import signal
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo

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
        match = re.search(rf"^\s*{re.escape(label)}\s*:\s*([-+]?\d+(?:[.,]\d+)?)(?=\s|\(|°|$)", output, re.M)
        if match:
            value = float(match[1].replace(",", "."))
            if math.isfinite(value) and abs(value) < 1e12 and value not in (-2147483648, 2147483647, 4294967295):
                if unit not in ("°C", "W") and value < 0:
                    continue
                values[key] = int(value) if value.is_integer() else value
    return values


class BridgeError(ValueError):
    """Only fixed, credential-free messages may be exposed to the log."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_options(options):
    """Validate local options before writing secrets or starting any clients."""
    for key in ("mqtt_base_topic", "discovery_prefix"):
        topic = options[key]
        if (not isinstance(topic, str) or not topic.strip("/")
                or any(char in topic for char in "+#")
                or any(ord(char) < 32 or ord(char) == 127 for char in topic)):
            raise BridgeError(f"Ungültiges MQTT-Topic: {key}")
        try:
            if len(topic.encode("utf-8")) > 65000:
                raise BridgeError(f"MQTT-Topic zu lang: {key}")
        except UnicodeError:
            raise BridgeError(f"Ungültiges MQTT-Topic: {key}") from None
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", options["device_id"]):
        raise BridgeError("Ungültige device_id")
    for key, minimum, maximum in (("poll_seconds", 10, 3600),
                                  ("retry_seconds", 1, 60),
                                  ("stale_after_seconds", 30, 7200),
                                  ("mqtt_port", 1, 65535)):
        value = options[key]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise BridgeError(f"Ungültiger Zahlenwert: {key} ({minimum}–{maximum})")
    if options.get("log_level", "info") not in ("info", "debug"):
        raise BridgeError("log_level muss info oder debug sein")
    for key in ("discovery", "mqtt_tls"):
        if not isinstance(options[key], bool):
            raise BridgeError(f"Ungültiger Wahrheitswert: {key}")
    try:
        ZoneInfo(options["timezone"])
    except (ValueError, KeyError, TypeError):
        raise BridgeError("Ungültige Zeitzone") from None


def write_config(options, template, target):
    overrides = {
        "User": "user", "BTAddress": options["inverter_bluetooth_address"],
        "LocalBTAddress": options.get("local_bluetooth_address") or "00:00:00:00:00:00",
        "Password": options["inverter_password"], "Timezone": options["timezone"],
        "Plantname": "SMA", "OutputPath": "/tmp", "OutputPathEvents": "/tmp",
        "CSV_Export": "0", "SynchTime": "0", "MIS_Enabled": "0",
        "Locale": "en-US", "DecimalPoint": "point", "BTConnectRetries": "2",
    }
    mac = r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}"
    for key in ("BTAddress", "LocalBTAddress"):
        if not re.fullmatch(mac, overrides[key]):
            raise BridgeError(f"Ungültige Bluetooth-Adresse: {key}")
    if overrides["BTAddress"] == "00:00:00:00:00:00":
        raise BridgeError("Bitte die Bluetooth-Adresse des Wechselrichters konfigurieren")
    if not 1 <= len(overrides["Password"]) <= 12:
        raise BridgeError("Wechselrichter-Passwort muss 1 bis 12 Zeichen haben")
    for value in overrides.values():
        if any(c in str(value) for c in "\r\n\x00"):
            raise BridgeError("Zeilenumbrüche in SBFspot-Optionen sind unzulässig")
    lines = [line for line in template.splitlines()
             if line.split("=", 1)[0].strip() not in overrides]
    lines += [f"{key}={value}" for key, value in overrides.items()]
    # Atomic replacement also repairs old permissions and never follows a
    # pre-existing target symlink. mkstemp creates the secret with mode 0600.
    fd, temporary = tempfile.mkstemp(prefix=".sbfspot-", dir=Path(target).parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write("\n".join(lines) + "\n")
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def broker_settings(options):
    if options.get("mqtt_host"):
        broker = {"host": options["mqtt_host"], "port": options["mqtt_port"],
                  "username": options.get("mqtt_username"), "password": options.get("mqtt_password"),
                  "ssl": options.get("mqtt_tls", False)}
    else:
        token = os.environ.get("SUPERVISOR_TOKEN", "")
        if not token:
            raise BridgeError("MQTT-Dienst: Supervisor-Token fehlt; alternativ mqtt_host setzen")
        request = Request("http://supervisor/services/mqtt", headers={
            "Authorization": "Bearer " + token})
        # Never forward the Supervisor token through a proxy or HTTP redirect.
        opener = build_opener(ProxyHandler({}), NoRedirect())
        try:
            with opener.open(request, timeout=15) as response:
                raw = response.read(65537)
            if len(raw) > 65536:
                raise BridgeError("MQTT-Dienstantwort zu groß")
            result = json.loads(raw)
            if not isinstance(result, dict) or result.get("result") != "ok":
                raise BridgeError("MQTT-Dienst nicht verfügbar; Mosquitto einrichten oder mqtt_host setzen")
            broker = result.get("data")
        except (OSError, ValueError) as error:
            if isinstance(error, BridgeError):
                raise
            raise BridgeError("MQTT-Dienstabfrage fehlgeschlagen; Supervisor und Mosquitto prüfen") from None
    if (not isinstance(broker, dict) or not isinstance(broker.get("host"), str)
            or not re.fullmatch(r"[a-zA-Z0-9_.:%-]+", broker["host"])
            or isinstance(broker.get("port"), bool) or not isinstance(broker.get("port"), int)
            or not 1 <= broker["port"] <= 65535
            or not isinstance(broker.get("ssl", False), bool)
            or any(broker.get(key) is not None and not isinstance(broker[key], str)
                   for key in ("username", "password"))):
        raise BridgeError("Ungültige MQTT-Broker-Einstellungen")
    return broker


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
                               "model": "SBFspot Bluetooth"},
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
    child_env = {key: value for key, value in os.environ.items()
                 if key not in ("SUPERVISOR_TOKEN", "HASSIO_TOKEN")}
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", env=child_env)
    try:
        while not stop.is_set():
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise BridgeError("SBFspot-Zeitlimit erreicht")
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


def main():
    import paho.mqtt.client as mqtt

    os.umask(0o077)
    options = json.loads(Path("/data/options.json").read_text(encoding="utf-8"))
    # Old WebBox/source keys are deliberately ignored during an upgrade.
    options.setdefault("retry_seconds", 5)
    options.setdefault("stale_after_seconds", 180)
    validate_options(options)
    logging.getLogger().setLevel(options.get("log_level", "info").upper())
    poll_seconds = options["poll_seconds"]
    stale_after = options["stale_after_seconds"]
    retry_seconds = options["retry_seconds"]
    if stale_after <= poll_seconds:
        LOG.warning("stale_after_seconds sollte größer als poll_seconds plus Abfragedauer sein")
    cfg = "/data/SBFspot.cfg"
    write_config(options, Path("/usr/local/share/SBFspot.default.cfg").read_text(encoding="utf-8"), cfg)
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
                output, returncode = read_inverter(cfg, stop, maintain)
                values = parse_output(output)
                if stop.is_set():
                    break
                # SBFspot can return a nonzero exit code for an optional failed
                # getter even though other independently measured values are valid.
                if not values:
                    raise BridgeError(failure_reason(output, returncode))
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
                    delay = retry_seconds
                else:
                    failures += 1
                    second_attempt = False
                    delay = retry_pause(poll_seconds, failures)
                reason = str(error) if isinstance(error, BridgeError) else "Lesefehler (" + type(error).__name__ + ")"
                LOG.warning("Abfrage fehlgeschlagen (%.1fs): %s; nächster Versuch in %ss",
                            time.monotonic() - started, reason, delay)
                next_read = time.monotonic() + delay
            maintain()
    finally:
        publisher.flush_reset()
        publisher.publish(publisher.availability, "offline")
        client.disconnect()
        client.loop_stop()


def log_start_failure(error):
    # Only our fixed messages are safe. Never print arbitrary exception text.
    if isinstance(error, BridgeError):
        LOG.error("Start fehlgeschlagen: %s", error)
    else:
        LOG.error("Start fehlgeschlagen (%s). Add-on- und MQTT-Konfiguration prüfen.", type(error).__name__)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if len(sys.argv) != 1:
            raise BridgeError("Dieses Add-on unterstützt keine Kommandozeilenoptionen")
        main()
    except Exception as error:
        log_start_failure(error)
        raise SystemExit(1) from None
