import os
from pathlib import Path

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

VERSION = "2.4.1"
CONFIG_DIR = os.getenv("CONFIG_DIR", "/config")
DATA_DIR = os.getenv("DATA_DIR", "/data")
APP_CONFIG_FILE = os.getenv("APP_CONFIG_FILE", f"{CONFIG_DIR}/config.yaml")
SBFSPOT_CFG = os.getenv("SBFSPOT_CFG", f"{CONFIG_DIR}/SBFspot.cfg")

DEFAULT_CONFIG_YAML = """# ==========================================
# SMA SBFspot Runtime v2.4.1
# ==========================================
# Diese Datei ist die Docker-/App-Konfiguration.
# SBFspot selbst bleibt separat in /config/SBFspot.cfg.

runtime:
  interval: 300
  web_port: 8088

mqtt:
  enabled: true
  host: 192.168.2.115
  port: 1883
  username: sbfspot
  password: ""
  base_topic: sma/sbfspot
  retain: true

homeassistant:
  discovery: true
  discovery_prefix: homeassistant
  device_name: SMA Wechselrichter Amann
  device_id: sma_sbfspot_amann

forecast_solar:
  enabled: true
  latitude: 48.23
  longitude: 9.88
  interval: 3600
  api_key: ""

  # Mehrere Dachflächen sind möglich.
  # peak_power ist kWp pro Dachfläche.
  arrays:
    - name: West
      peak_power: 1.90
      declination: 44
      azimuth: 265
      damping: 0

    - name: Sued
      peak_power: 1.71
      declination: 44
      azimuth: 185
      damping: 0

  learning:
    enabled: true
    days: 14
"""


def _to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "ja")


def _get(data, path, default=None):
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def ensure_default_config():
    path = Path(APP_CONFIG_FILE)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CONFIG_YAML, encoding="utf-8")
        return True
    return False


def load_config():
    ensure_default_config()
    if yaml is None:
        return {}
    try:
        with open(APP_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


APP_CONFIG = load_config()

INTERVAL = int(os.getenv("INTERVAL", str(_get(APP_CONFIG, "runtime.interval", 300))))
WEB_PORT = int(os.getenv("WEB_PORT", str(_get(APP_CONFIG, "runtime.web_port", 8088))))

MQTT_ENABLE = _to_bool(os.getenv("MQTT_ENABLE", _get(APP_CONFIG, "mqtt.enabled", True)), True)
MQTT_HOST = os.getenv("MQTT_HOST", str(_get(APP_CONFIG, "mqtt.host", "127.0.0.1")))
MQTT_PORT = int(os.getenv("MQTT_PORT", str(_get(APP_CONFIG, "mqtt.port", 1883))))
MQTT_USER = os.getenv("MQTT_USER", str(_get(APP_CONFIG, "mqtt.username", "") or ""))
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", str(_get(APP_CONFIG, "mqtt.password", "") or ""))
MQTT_BASE_TOPIC = os.getenv("MQTT_BASE_TOPIC", str(_get(APP_CONFIG, "mqtt.base_topic", "sma/sbfspot"))).strip("/")
MQTT_RETAIN = _to_bool(os.getenv("MQTT_RETAIN", _get(APP_CONFIG, "mqtt.retain", True)), True)

HA_DISCOVERY = _to_bool(os.getenv("HA_DISCOVERY", _get(APP_CONFIG, "homeassistant.discovery", True)), True)
HA_DISCOVERY_PREFIX = os.getenv("HA_DISCOVERY_PREFIX", str(_get(APP_CONFIG, "homeassistant.discovery_prefix", "homeassistant"))).strip("/")
DEVICE_NAME = os.getenv("DEVICE_NAME", str(_get(APP_CONFIG, "homeassistant.device_name", "SMA Wechselrichter")))
DEVICE_ID = os.getenv("DEVICE_ID", str(_get(APP_CONFIG, "homeassistant.device_id", "sma_sbfspot"))).lower().replace(" ", "_")

FORECAST_CONFIG = _get(APP_CONFIG, "forecast_solar", {}) or {}
FORECAST_ENABLE = _to_bool(os.getenv("FORECAST_ENABLE", FORECAST_CONFIG.get("enabled", True)), True)
FORECAST_LATITUDE = float(os.getenv("FORECAST_LATITUDE", str(FORECAST_CONFIG.get("latitude", os.getenv("LATITUDE", "48.23")))))
FORECAST_LONGITUDE = float(os.getenv("FORECAST_LONGITUDE", str(FORECAST_CONFIG.get("longitude", os.getenv("LONGITUDE", "9.88")))))
FORECAST_API_KEY = os.getenv("FORECAST_API_KEY", str(FORECAST_CONFIG.get("api_key", "") or "")).strip()
FORECAST_INTERVAL = int(os.getenv("FORECAST_INTERVAL", str(FORECAST_CONFIG.get("interval", 3600))))
FORECAST_CACHE_FILE = f"{DATA_DIR}/forecast_solar.json"
FORECAST_LEARNING_FILE = f"{DATA_DIR}/forecast_learning.json"
FORECAST_LEARNING = FORECAST_CONFIG.get("learning", {}) if isinstance(FORECAST_CONFIG.get("learning", {}), dict) else {}
FORECAST_LEARNING_ENABLE = _to_bool(os.getenv("FORECAST_LEARNING_ENABLE", FORECAST_LEARNING.get("enabled", True)), True)
FORECAST_LEARNING_DAYS = int(os.getenv("FORECAST_LEARNING_DAYS", str(FORECAST_LEARNING.get("days", 14))))

# Fallback auf alte ENV-Einflächen-Konfiguration, falls keine arrays in config.yaml stehen.
FORECAST_ARRAYS = FORECAST_CONFIG.get("arrays") or []
if not FORECAST_ARRAYS:
    FORECAST_ARRAYS = [{
        "name": "PV",
        "peak_power": float(os.getenv("FORECAST_KWP", "3.6")),
        "declination": float(os.getenv("FORECAST_DECLINATION", "35")),
        "azimuth": float(os.getenv("FORECAST_AZIMUTH", "0")),
        "damping": float(os.getenv("FORECAST_DAMPING", "0")),
    }]

STATE_FILE = f"{DATA_DIR}/state.json"
DB_FILE = f"{DATA_DIR}/history.sqlite3"
LOG_FILE = f"{DATA_DIR}/runtime.log"
START_FILE = f"{DATA_DIR}/container_start.txt"
