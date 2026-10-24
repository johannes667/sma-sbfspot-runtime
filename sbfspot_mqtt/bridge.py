"""Single-inverter SBFspot -> MQTT bridge. No web server or local history."""
import json
import logging
import math
import os
from pathlib import Path
import re
import signal
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

    def send_values(self, values):
        # Mark unavailable until the complete current snapshot is acknowledged.
        if self.availability not in self.cache:
            if not self.publish(self.availability, "offline"):
                return False
        for key, value in values.items():
            if self.options["discovery"]:
                _, unit, device_class, state_class = SENSORS[key]
                device_id = self.options["device_id"]
                payload = {
                    "name": key.replace("_", " "), "unique_id": f"{device_id}_{key}",
                    "state_topic": f"{self.base}/{key}",
                    "availability_topic": self.availability,
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
        return self.publish(self.availability, "online")


def main():
    import paho.mqtt.client as mqtt

    options = json.loads(Path("/data/options.json").read_text())
    for key in ("mqtt_base_topic", "discovery_prefix"):
        if not options[key].strip("/") or any(c in options[key] for c in "+#\x00"):
            raise ValueError(f"Ungültiges MQTT-Topic: {key}")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", options["device_id"]):
        raise ValueError("Ungültige device_id")
    poll_seconds = int(options["poll_seconds"])
    if not 10 <= poll_seconds <= 3600:
        raise ValueError("poll_seconds muss zwischen 10 und 3600 liegen")
    cfg = "/data/SBFspot.cfg"
    write_config(options, Path("/usr/local/share/SBFspot.default.cfg").read_text(), cfg)
    broker = broker_settings(options)
    client = mqtt.Client(client_id=options["device_id"] + "_bridge")
    publisher = Publisher(client, options)
    stop = threading.Event()
    active = None

    def shutdown(*_):
        stop.set()
        if active is not None and active.poll() is None:
            active.terminate()

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            publisher.reset.set()
            publisher.connected.set()
            if options["discovery"]:
                client.subscribe(options["discovery_prefix"].strip("/") + "/status", qos=1)
            LOG.info("MQTT verbunden")
        else:
            LOG.error("MQTT-Anmeldung abgelehnt (Code %s)", rc)

    def on_disconnect(client, userdata, rc):
        publisher.connected.clear()
        publisher.reset.set()

    def on_message(client, userdata, message):
        if message.payload == b"online":
            publisher.reset.set()

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    if broker.get("username"):
        client.username_pw_set(broker["username"], broker.get("password"))
    if broker.get("ssl"):
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    client.will_set(publisher.availability, "offline", qos=1, retain=True)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    client.connect_async(broker["host"], int(broker["port"]), keepalive=30)
    client.loop_start()
    LOG.info("SBFspot MQTT gestartet; Abfragepause %ss, Messwerte nur bei Änderung", poll_seconds)
    try:
        while not stop.is_set():
            if not publisher.connected.wait(timeout=1):
                continue
            publisher.flush_reset()
            try:
                active = subprocess.Popen([
                    "/usr/local/bin/SBFspot", "-d2", "-v2", "-finq", "-nocsv", "-nosql",
                    "-ad0", "-am0", "-ae0", f"-cfg:{cfg}"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
                try:
                    output, _ = active.communicate(timeout=90)
                except subprocess.TimeoutExpired:
                    active.kill()
                    active.communicate()
                    raise ValueError("SBFspot-Zeitlimit erreicht") from None
                values = parse_output(output) if active.returncode == 0 else {}
                active = None
                if stop.is_set():
                    break
                publisher.flush_reset()
                if not values:
                    raise ValueError("Keine gültige Messung; Bluetooth, Passwort und Wechselrichter prüfen")
                if not publisher.send_values(values):
                    LOG.warning("MQTT-Übertragung unvollständig; Wiederholung bei nächster Abfrage")
            except (OSError, ValueError) as error:
                LOG.warning("%s", error)
                publisher.flush_reset()
                publisher.publish(publisher.availability, "offline")
            # Reconnect and HA birth should resend promptly, without busy polling.
            deadline = time.monotonic() + poll_seconds
            while not stop.wait(0.5) and time.monotonic() < deadline:
                if publisher.reset.is_set():
                    break
    finally:
        publisher.flush_reset()
        publisher.publish(publisher.availability, "offline")
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        main()
    except Exception as error:
        # Do not include SBFspot output, Supervisor replies or secrets in logs.
        LOG.error("Start fehlgeschlagen (%s). Add-on- und MQTT-Konfiguration prüfen.", type(error).__name__)
        raise SystemExit(1)
