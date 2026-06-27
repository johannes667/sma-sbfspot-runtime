# SMA SBFspot Runtime 2.2

SMA Bluetooth PV-Auslesung für Unraid/Docker mit SBFspot, Web-Dashboard, MQTT, Home Assistant Discovery, SQLite-Historie und Forecast.Solar-Prognose mit automatischem Lernfaktor.

## Neu in 2.2

- PVOutput/PV-Output-Zusatzsensor entfernt
- `power_w` ist der echte Live-Istwert aus SBFspot
- Forecast.Solar integriert:
  - `forecast_power_now_w`
  - `forecast_power_next_hour_w`
  - `forecast_today_kwh`
  - `forecast_remaining_today_kwh`
  - `forecast_tomorrow_kwh`
- Lernender Korrekturfaktor:
  - vergleicht abgeschlossene Tage: echter Tagesertrag vs. Forecast.Solar-Rohprognose
  - nutzt standardmäßig die letzten 14 Tage
  - begrenzt den Faktor sicher auf 0.6 bis 1.4
  - speichert Daten in `/data/forecast_learning.json`
- Rohwerte bleiben zusätzlich erhalten:
  - `forecast_today_raw_kwh`
  - `forecast_tomorrow_raw_kwh`
  - `forecast_power_now_raw_w`
- Weboberfläche mit Verlaufskurve: Ist-Leistung + korrigierte Forecast.Solar-Kurve
- MQTT-Availability getrennt von Status: `sma/sbfspot/availability`
- SBFspot-Fehler setzen nur den Status auf `error`, die letzten gültigen Zahlen bleiben erhalten
- Keine Veröffentlichung von `unknown`, `unavailable`, `None` oder `NaN` als Sensorwert

## Forecast.Solar konfigurieren

In `docker-compose.yml`:

```yaml
FORECAST_ENABLE: "true"
FORECAST_LATITUDE: "48.2173"
FORECAST_LONGITUDE: "9.8268"
FORECAST_DECLINATION: "35"   # Dachneigung in Grad
FORECAST_AZIMUTH: "0"        # Forecast.Solar: 0=Süd, -90=Ost, 90=West
FORECAST_KWP: "3.6"          # Anlagenleistung in kWp
FORECAST_INTERVAL: "3600"    # API nur stündlich abrufen
FORECAST_API_KEY: ""         # optional
FORECAST_DAMPING: "0"        # optional
FORECAST_INVERTER_KW: ""     # optional, z.B. "3.0"
FORECAST_LEARNING_ENABLE: "true"
FORECAST_LEARNING_DAYS: "14"
```

Wichtig: Für diese Forecast.Solar-API gilt hier: `0 = Süd`, `-90 = Ost`, `90 = West`.

## MQTT Topics

```text
sma/sbfspot/availability
sma/sbfspot/status
sma/sbfspot/power_w
sma/sbfspot/forecast_power_now_w
sma/sbfspot/forecast_power_next_hour_w
sma/sbfspot/forecast_today_kwh
sma/sbfspot/forecast_remaining_today_kwh
sma/sbfspot/forecast_tomorrow_kwh
sma/sbfspot/forecast_correction_factor
sma/sbfspot/forecast_accuracy_days
sma/sbfspot/forecast_today_raw_kwh
sma/sbfspot/energy_today_kwh
sma/sbfspot/energy_total_kwh
```

## Home Assistant Sensoren

Nach MQTT Discovery bekommst du u.a.:

```text
sensor.sma_sbfspot_amann_pv_leistung_ist
sensor.sma_sbfspot_amann_forecast_solar_jetzt_korrigiert
sensor.sma_sbfspot_amann_forecast_solar_heute_korrigiert
sensor.sma_sbfspot_amann_forecast_solar_rest_heute_korrigiert
sensor.sma_sbfspot_amann_forecast_solar_morgen_korrigiert
sensor.sma_sbfspot_amann_forecast_korrekturfaktor
sensor.sma_sbfspot_amann_forecast_lerntage
```

Alte MQTT-Discovery-Leichen vom entfernten `pv_output_w` Sensor kannst du in HA löschen, falls er noch angezeigt wird.

## Lokal bauen

```bash
cd /mnt/user/appdata/sma-sbfspot-runtime
docker compose build --no-cache
docker compose up -d
```

## Web

```text
http://UNRAID-IP:8088
```
