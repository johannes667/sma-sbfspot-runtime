import os

VERSION = "2.2"
CONFIG_DIR = os.getenv("CONFIG_DIR", "/config")
DATA_DIR = os.getenv("DATA_DIR", "/data")
SBFSPOT_CFG = os.getenv("SBFSPOT_CFG", f"{CONFIG_DIR}/SBFspot.cfg")
INTERVAL = int(os.getenv("INTERVAL", "300"))

MQTT_ENABLE = os.getenv("MQTT_ENABLE", "true").lower() in ("1", "true", "yes", "on")
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_BASE_TOPIC = os.getenv("MQTT_BASE_TOPIC", "sma/sbfspot").strip("/")
MQTT_RETAIN = os.getenv("MQTT_RETAIN", "true").lower() in ("1", "true", "yes", "on")

HA_DISCOVERY = os.getenv("HA_DISCOVERY", "true").lower() in ("1", "true", "yes", "on")
HA_DISCOVERY_PREFIX = os.getenv("HA_DISCOVERY_PREFIX", "homeassistant").strip("/")
DEVICE_NAME = os.getenv("DEVICE_NAME", "SMA Wechselrichter")
DEVICE_ID = os.getenv("DEVICE_ID", "sma_sbfspot").lower().replace(" ", "_")

# Forecast.Solar
FORECAST_ENABLE = os.getenv("FORECAST_ENABLE", "true").lower() in ("1", "true", "yes", "on")
FORECAST_API_KEY = os.getenv("FORECAST_API_KEY", "").strip()
FORECAST_LATITUDE = os.getenv("FORECAST_LATITUDE", os.getenv("LATITUDE", "48.2173")).strip()
FORECAST_LONGITUDE = os.getenv("FORECAST_LONGITUDE", os.getenv("LONGITUDE", "9.8268")).strip()
FORECAST_DECLINATION = os.getenv("FORECAST_DECLINATION", "35").strip()  # Dachneigung in Grad
FORECAST_AZIMUTH = os.getenv("FORECAST_AZIMUTH", "0").strip()          # Forecast.Solar: 0=Süd, -90=Ost, 90=West
FORECAST_KWP = os.getenv("FORECAST_KWP", "3.6").strip()
FORECAST_DAMPING = os.getenv("FORECAST_DAMPING", "0").strip()
FORECAST_INVERTER_KW = os.getenv("FORECAST_INVERTER_KW", "").strip()
FORECAST_INTERVAL = int(os.getenv("FORECAST_INTERVAL", "3600"))
FORECAST_CACHE_FILE = f"{DATA_DIR}/forecast_solar.json"
FORECAST_LEARNING_ENABLE = os.getenv("FORECAST_LEARNING_ENABLE", "true").lower() in ("1", "true", "yes", "on")
FORECAST_LEARNING_DAYS = int(os.getenv("FORECAST_LEARNING_DAYS", "14"))
FORECAST_LEARNING_FILE = f"{DATA_DIR}/forecast_learning.json"

WEB_PORT = int(os.getenv("WEB_PORT", "8088"))
STATE_FILE = f"{DATA_DIR}/state.json"
DB_FILE = f"{DATA_DIR}/history.sqlite3"
