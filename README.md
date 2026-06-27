# SMA SBFspot Runtime 2.2

SMA Bluetooth PV-Auslesung für Docker/Unraid mit SBFspot, Web-Dashboard, MQTT, Home Assistant Discovery, SQLite-Historie und Forecast.Solar-Prognose.

## Wichtig ab Version 2.2

Die Konfiguration ist getrennt:

```text
/config/SBFspot.cfg     # nur SBFspot-Konfiguration
/config/config.yaml     # Docker/App-Konfiguration inkl. MQTT und Forecast.Solar
```

Forecast.Solar gehört **nicht** in `SBFspot.cfg`.

## Beispiel `config.yaml`

```yaml
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
```

## Forecast.Solar Werte

- `latitude` / `longitude`: Standort der Anlage
- `peak_power`: Leistung der jeweiligen Dachfläche in kWp
- `declination`: Dachneigung in Grad, 0 = flach, 90 = senkrecht
- `azimuth`: Ausrichtung, 0 = Nord, 90 = Ost, 180 = Süd, 270 = West
- `damping`: optionale Dämpfung der Forecast.Solar-Kurve

Für die Anlage Amann ist die Startaufteilung:

- West: 1,90 kWp, 44°, Azimut 265°
- Süd: 1,71 kWp, 44°, Azimut 185°

## Lernfaktor

Wenn `learning.enabled: true` aktiv ist, vergleicht der Docker den echten Tagesertrag aus SBFspot mit der Forecast.Solar-Tagesprognose. Aus den letzten `days` Tagen wird ein Korrekturfaktor berechnet und auf die Kurve angewendet.

Dateien:

```text
/data/forecast_solar.json      # Forecast.Solar Cache
/data/forecast_learning.json   # Lernfaktor und Lerntage
```

## MQTT/Home Assistant

Neue Sensoren:

```text
sensor.sma_sbfspot_amann_forecast_power_w
sensor.sma_sbfspot_amann_forecast_today_kwh
sensor.sma_sbfspot_amann_forecast_learning_factor
sensor.sma_sbfspot_amann_forecast_learning_days
```

Die MQTT Availability ist getrennt von `status`:

```text
sma/sbfspot/availability = online/offline
sma/sbfspot/status       = online/error/waiting/config_missing
```

Dadurch werden Sensoren nicht mehr wegen eines SBFspot-Fehlers automatisch `unavailable`.

## Update auf Unraid

```bash
cd /mnt/user/appdata/sma-sbfspot-runtime
docker compose build --no-cache
docker compose up -d
```

Danach prüfen:

```bash
docker logs -f SMA-SBFspot-Runtime
```

Weboberfläche:

```text
http://UNRAID-IP:8088
```

## Fix in dieser Copy-Paste-Version

Diese Version zeichnet die gelbe Forecast-Kurve nicht mehr aus den gespeicherten History-Samples, sondern direkt aus `/api/forecast`. Dadurch verschwindet die falsche 0-W-Linie mit senkrechtem Sprung.

Zusätzlich werden Forecast.Solar-Zeitstempel ohne Zeitzone explizit als `Europe/Berlin` behandelt.

Nach dem Update einmal Cache löschen:

```bash
rm -f /mnt/user/appdata/sma-sbfspot/data/forecast_solar.json
rm -f /mnt/user/appdata/sma-sbfspot/data/forecast_learning.json
```

Dann Container neu bauen/starten.
