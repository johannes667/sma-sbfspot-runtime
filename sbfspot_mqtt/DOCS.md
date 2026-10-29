# SMA SBFspot MQTT für Home Assistant OS

Dieses Add-on fragt **einen SMA-Wechselrichter über klassisches Bluetooth** ab
und veröffentlicht Messwerte einzeln per MQTT. Kein Dashboard, Flask, Forecast,
SQLite, CSV-Export oder lokales Messwertarchiv. SBFspot wird ohne SQL-Unterstützung
gebaut; zur Laufzeit läuft nur die Python-Bridge mit dem jeweiligen SBFspot-Aufruf.
Unterstützte Zielarchitekturen: amd64 und aarch64.

## Installation über das Repository

Im Add-on-Store unter **Repositories** diese Adresse hinzufügen:
`https://github.com/johannes667/sma-sbfspot-runtime`.
Danach **SMA SBFspot MQTT** installieren und die folgenden Bluetooth- und
MQTT-Einstellungen konfigurieren. Für Updates im Store nach Updates suchen.

## Installation als lokales Add-on

1. ZIP entpacken und den Ordner `sbfspot_mqtt` nach `/addons/` auf dem HAOS-Host
   kopieren, z. B. über die `addons`-Freigabe des Samba-Add-ons.
   Danach muss `/addons/sbfspot_mqtt/config.yaml` existieren.
2. Unter **Einstellungen → Add-ons → Add-on-Store** im Menü nach Updates suchen.
   Das Add-on erscheint unter **Lokale Add-ons**. Installieren; der erste Build
   kompiliert SBFspot und benötigt Internet sowie etwas Zeit.
3. Einen mit SMA kompatiblen Bluetooth-Adapter am HAOS-Host bereitstellen. Bei
   einer VM muss der Adapter an die HAOS-VM durchgereicht werden. Klassisches
   Bluetooth ist erforderlich; ein ESPHome-Bluetooth-Proxy reicht nicht.
4. `inverter_bluetooth_address` auf die Bluetooth-MAC **des Wechselrichters**
   setzen. `local_bluetooth_address` ist optional die MAC des lokalen Adapters.
   Das Benutzerpasswort des Wechselrichters unter `inverter_password` eintragen.
5. Mosquitto und die MQTT-Integration in Home Assistant einrichten. Bei leerem
   `mqtt_host` liest das Add-on den MQTT-Dienst samt Zugangsdaten über den
   Supervisor aus. Für einen externen Broker Host, Port und Zugangsdaten setzen.
6. Starten und das Add-on-Protokoll prüfen. Bei `discovery: true` erscheinen die
   unterstützten Sensoren automatisch in der MQTT-Integration.

## Änderungsgesteuerte MQTT-Veröffentlichung

SBFspot hat hier keine Push-Schnittstelle für Messwertänderungen. Deshalb wird
nach jedem abgeschlossenen Lauf `poll_seconds` gewartet (Standard 30, Minimum 10).
Die Dauer der Bluetooth-Abfrage kommt dazu. Archive und Ereignisabfragen sind
deaktiviert; jede Abfrage hat ein Zeitlimit von 90 Sekunden.

Nur geänderte Werte werden danach an MQTT gesendet, QoS 1 und retained.
Beispiel: `sma/sbfspot/power_w` mit Payload `1234`. Bleibt die Leistung gleich,
folgt keine weitere Messwertnachricht. Es gibt keinen fortlaufenden Zeitstempel,
der unnötige MQTT-Änderungen erzeugt. MQTT-Keepalive bleibt technisch erforderlich.

Ausnahmen: Beim Start, bei erneuter MQTT-Verbindung und beim Home-Assistant-
Birth-Signal werden Discovery und die noch gültigen Messwerte aus dem RAM erneut
veröffentlicht. Dafür wird keine zusätzliche Bluetooth-Abfrage gestartet. Die
Auslesung läuft auch während eines MQTT-Ausfalls weiter; beim Wiederverbinden
wird der jüngste noch gültige Stand gesendet. Zwischenstände werden nicht gepuffert.
QoS 1 kann auf Protokollebene Duplikate erzeugen. Es wird keine Messwertdatei geschrieben.

Weitere Topics sind z. B. `energy_today_kwh`, `energy_total_kwh`, `pac1_w`,
`dc_voltage_1_v`, `dc_current_1_a`, `temperature_c` und `frequency_hz`.
Discovery wird nur für tatsächlich gelieferte Messgrößen angelegt. Die Bridge
unterstützt einen Wechselrichter sowie DC-Strings 1/2 und AC-Phasen 1/2/3.

## Lesefehler und veraltete Messwerte

Ein fehlgeschlagener Lauf wird einmal nach `retry_seconds` wiederholt (Standard 5).
Nach weiteren Fehlern wächst die Pause schrittweise bis 300 Sekunden; eine größer
konfigurierte normale Abfragepause bleibt dabei erhalten. Erfolgreiche Abfragen
setzen die Pause wieder auf `poll_seconds` zurück. Es läuft nur ein SBFspot-Prozess.

Während kurzer Lesefehler bleiben die letzten echten Messwerte verfügbar. Jeder
Sensor wird nach `stale_after_seconds` ohne eigene gültige Messung auf `offline`
gesetzt (Standard 180 Sekunden). Eine weiterhin gelesene Temperatur hält somit
keine ausgefallene Leistungsmessung unbegrenzt verfügbar. MQTT Discovery nutzt
sowohl `<mqtt_base_topic>/availability` als auch
`<mqtt_base_topic>/<messwert>/availability`; beide müssen `online` sein.
Wenn alle Messwerte abgelaufen sind, ist auch die gemeinsame Availability offline.
Beim Stoppen oder MQTT-Verbindungsabbruch setzt MQTT Last Will die gemeinsame
Availability offline. Ein MQTT-Ausfall kann deshalb weiterhin eine echte Lücke zeigen.

Die Alterungsprüfung läuft auch zwischen Abfragen und während eines laufenden
SBFspot-Prozesses. Bei gestörtem MQTT kann die Übertragung einer Statusänderung
bis zur Wiederverbindung dauern. Im Broker bleiben Retained-Messwerte gespeichert;
die Availability kennzeichnet, ob diese noch gültig sind. Die kurze Überbrückung
ist keine neue Messung. Nach einem Neustart gibt es keine gespeicherten Messwerte;
bis zur ersten gültigen Abfrage bleiben die Sensoren nicht verfügbar.

Fehlende Werte werden nicht als 0 veröffentlicht. Dafür korrigiert ein kleiner
Patch auch die vorgelagerte Umwandlung von SMA-NaN-Markierungen in 0 innerhalb
von SBFspot. Korrekt empfangene Werte eines abgeschlossenen Laufs können auch bei
einem Fehlercode für andere Messgrößen weiterverwendet werden. Echte 0-W-Werte
und schnelle Leistungseinbrüche werden unverändert veröffentlicht; es gibt keine
Glättung oder Ausreißerunterdrückung.

`<mqtt_base_topic>/status` zeigt `waiting`, `online`, `retrying`, `stale` oder
`error`. Status- und Availability-Nachrichten werden ebenfalls nur bei Änderung
bzw. nach einer erneuten MQTT-/HA-Verbindung gesendet.

## Fehlersuche bei PV-Aussetzern

`log_level: debug` protokolliert jede erfolgreiche Abfrage mit Dauer, Exit-Code,
Bluetooth-Signal (falls geliefert) und den echten Messwerten. Fehlermeldungen
unterscheiden Passwortablehnung, Verbindungsinitialisierung, fehlerhafte
SBFspot-Abfragen und Zeitüberschreitungen, ohne Rohdaten oder Passwörter auszugeben.
Nach der Diagnose wieder `log_level: info` wählen. Die Protokollzeit kann von der
Anzeigezeit des Telefons abweichen; beim Abgleich die Zeitzone beachten.

Nur **ein** Programm sollte den Wechselrichter gleichzeitig auslesen. Einen alten
Docker-Collector oder Sunny Explorer zum Vergleich beenden. Bei Verbindungsfehlern
Adapterposition, Funkreichweite, USB-Verlängerung und gegebenenfalls konkurrierenden
Zugriff auf denselben Adapter prüfen. Eine längere Pause kann Funk und Gerät
entlasten, ersetzt aber keine Fehlerdiagnose.

Ein längeres Intervall verpasst kurzzeitige Leistungsänderungen. Die App liest
aktuelle Momentanwerte und rekonstruiert keine Zwischenwerte. Die Energiezähler
im Wechselrichter erfassen den Ertrag unabhängig vom Abfrageintervall weiter.
Historische Aussetzer im HA-Verlauf werden durch dieses Update nicht nachträglich
repariert. Ob ein beobachteter Einbruch real war, lässt sich nur anhand gleichzeitiger
Rohmesswerte, Fehlerprotokolle oder einer unabhängigen Referenz feststellen.

## Optionen

- `poll_seconds`: Pause zwischen Bluetooth-Abfragen, kein MQTT-Sendeintervall.
- `retry_seconds`: Wartezeit vor der einmaligen schnellen Wiederholung, Standard 5.
- `stale_after_seconds`: Maximales Alter einer Sensormessung, Standard 180.
  Größer als Abfragepause plus üblicher Abfragedauer wählen, bei Bedarf auch größer
  als die Dauer eines Fehlversuchs. Dieser Zeitraum hält ausdrücklich alte Werte verfügbar.
- `log_level`: `info` oder vorübergehend `debug`.
- `mqtt_tls`: Bei manuellem Broker TLS mit Prüfung gegen öffentliche System-CAs;
  typischerweise Port 8883. Der automatische MQTT-Dienst liefert seine TLS-Einstellung.
  Private CA-Zertifikate werden in dieser schlanken Version nicht konfiguriert.
- `mqtt_base_topic`: Standard `sma/sbfspot`. Für mehrere Add-on-Instanzen getrennte
  Topics und `device_id` verwenden. Topic-Wechsel löscht alte Retained-Daten nicht.
- `discovery`: Standard `true`; mit `false` nur Messwerte und Availability.
- `discovery_prefix`: Standard `homeassistant`, muss zur MQTT-Integration passen.
- `device_id`: Stabile Kennung; nicht nachträglich ändern, um doppelte Entitäten
  zu vermeiden. Beim Umstieg von der Docker-Version deren Kennung übernehmen,
  sofern dieselben Sensoren weiterverwendet werden sollen.
- `device_name`: Anzeigename in Home Assistant.
- `timezone`: SBFspot-Zeitzone, Standard `Europe/Berlin`.

Die Bridge verändert weder Wechselrichterzeit noch Parameter und meldet sich
als Benutzer an. Die Konfiguration inklusive Wechselrichterpasswort liegt im
privaten Add-on-Datenverzeichnis mit Dateirechten 0600. Es werden keine
Passwörter oder SBFspot-Rohdaten ins Protokoll geschrieben.

## Bluetooth-Zugriff und Größe

Für direkte Linux-HCI-Sockets verwendet das Add-on Host-Netzwerk,
`NET_ADMIN`/`NET_RAW` und ein deaktiviertes AppArmor-Profil. Es startet keinen
eigenen Bluetooth-/D-Bus-Dienst und benötigt keinen Zugriff auf den Docker-Socket.
Adapter und Funkreichweite müssen zum SMA-Gerät passen. Kein vollständiger
privilegierter Containerzugriff (`full_access`).

Der Build enthält Compiler und Git nur in der Builder-Stufe. Das Laufzeitimage
enthält die benötigten Bluetooth-/Boost-Bibliotheken, Python und Paho MQTT.

SBFspot: https://github.com/SBFspot/SBFspot, festgelegter Quellstand
`b77f65047e9f4a136a09677838f6b4e5024862ee`.
SBFspot steht unter CC BY-NC-SA 3.0; seine Lizenz wird im Image mitgeliefert.

Der SBFspot-Build enthält seit Add-on-Version 1.1.0 die Änderung aus
`sbfspot-valid-values.patch`, um ungültige SMA-Werte als fehlend zu behandeln.

## Sunny WebBox mit Bluetooth über LAN (ab 1.2.0)

Die Datenquelle ist umschaltbar. Ohne `source` bleibt das bisherige Bluetooth-
Verhalten erhalten. Mit `source: webbox` spricht nur die WebBox per Bluetooth mit
dem Wechselrichter; am HAOS-/Unraid-Host ist kein Bluetooth-Adapter erforderlich.
Es startet weder SBFspot noch ein Bluetooth-Dienst. MQTT, Discovery, Retain,
Änderungserkennung, Retry/Backoff und sensorweise Alterung werden gemeinsam genutzt.
Es gibt keine zusätzlichen Python-Abhängigkeiten.

```yaml
source: webbox
webbox_host: 192.168.2.100  # Beispiel: durch eigene LAN-Adresse ersetzen
webbox_port: 80
webbox_password: ""       # WebBox-Benutzerpasswort, nicht HTTP Basic Auth
webbox_device_key: ""     # exakten Schlüssel aus Diagnose übernehmen
webbox_timeout_seconds: 10
webbox_diagnostics: false
webbox_channels: []
poll_seconds: 30
stale_after_seconds: 180
```

Bluetooth-Adressen und `inverter_password` werden im LAN-Modus nicht ausgewertet
und dürfen leer bleiben. `timezone` gilt weiterhin nur für SBFspot.
`webbox_host` akzeptiert einen Hostnamen oder eine IPv4-Adresse ohne Schema/Pfad;
IPv6 und HTTPS werden derzeit nicht unterstützt. Port und Timeout sind einstellbar
(Timeout 1–60 Sekunden). Leeres Passwort lässt das optionale `passwd`-Feld weg;
ansonsten wird der MD5-Hash des WebBox-Benutzerpassworts übertragen. Keine
Installer-Zugangsdaten verwenden. HTTP bietet keine Transportverschlüsselung;
die Verbindung gehört ins vertrauenswürdige lokale Netzwerk.

### Verifiziertes Protokoll und bewusste Grenzen

Primärquelle: [SMA Sunny WebBox RPC, Version 1.4](https://files.sma.de/downloads/SWebBoxRPC-BA-en-14.pdf),
Kapitel 2.2, 4–7. HTTP POST an `/rpc`, JSON-Objekt im Body, RPC-Version `1.0`,
`format: JSON`, korrelierte `id` und optionaler MD5-Hash in `passwd`.
Kein JSON-RPC-2.0-Endpunkt und keine Basic-Auth-Anmeldung.

`GetDevices` liefert die hierarchische Geräteliste. Ein konfigurierter Schlüssel
wird exakt ausgewählt. Automatisch wird ausschließlich ein einzelner Schlüssel
mit Präfix `SB` oder `WR` ausgewählt. Bei anderen Typkennungen oder mehreren
Wechselrichtern muss `webbox_device_key` gesetzt werden; keine Summierung.
`GetProcessData` fragt alle gelieferten Kanäle genau dieses Geräts ab und wertet
`meta`, `value` und `unit` aus. Keine Schreibprozeduren sind zugelassen.

`GetPlantOverview` ist dokumentiert, liefert jedoch Anlagenwerte. Deshalb wird
es nicht für bestehende Wechselrichter-Entitäten verwendet. `GetProcessDataChannels`
ist ebenfalls dokumentiert, aber das SMA-Beispiel verwendet abweichend
`GetProDataChannels`. Die Diagnose benötigt diese uneindeutige Prozedur nicht:
`GetProcessData` ohne Kanalauswahl liefert bereits Metanamen, Einheiten und Werte.

SMA empfiehlt mindestens 30 Sekunden **zwischen zwei RPC-Anfragen** (Kapitel 4.3).
Das gilt hier auch zwischen Geräteerkennung und Messabfrage, Diagnoseaufrufen und
Fehlversuchen. `poll_seconds` muss im WebBox-Modus mindestens 30 sein; der
Bluetooth-Modus behält sein Minimum von 10. Nach einer abgeschlossenen Messung
wird das konfigurierte Intervall gewartet. Die Erkennung benötigt beim ersten
Start somit zusätzlich mindestens 30 Sekunden. Keine parallelen RPC-Abfragen;
die MQTT-/Alterungsprüfung läuft während Abfragen und Wartezeiten weiter.
Wiederholungen im WebBox-Modus frühestens nach 30 Sekunden, danach begrenzter
Backoff wie bisher. Andere RPC-Clients während des Tests beenden.

### Tatsächlich unterstützte Messwerte

Die RPC-Dokumentation enthält ausdrücklich **keine Beispielantwort der
Bluetooth-WebBox**. Deshalb sind nur drei eindeutig dokumentierte Prozesskanäle
vorbelegt. Auch sie werden ausschließlich bei tatsächlich geliefertem Metanamen,
gültigem Zahlenwert und passender Einheit veröffentlicht:

| Sensor / bisherige MQTT-Kennung | Vorbelegter Metaname | HA-Einheit |
| --- | --- | --- |
| AC-Gesamtleistung `power_w` | `Pac` | W |
| Gesamtertrag `energy_total_kwh` | `E-Total` | kWh |
| Netzfrequenz `frequency_hz` | `Fac` | Hz |

**Für die konkrete Bluetooth-WebBox bleiben alle Kanalnamen und ihre tatsächliche
Verfügbarkeit bis zur Diagnose unbestätigt.** Die folgenden bestehenden Sensoren
sind über explizites Mapping verwendbar, sobald der reale Kanal und seine
Bedeutung nachgewiesen sind:

| Messgröße | Sensor-Kennung | Ziel-Einheit |
| --- | --- | --- |
| Tagesertrag | `energy_today_kwh` | kWh |
| DC-Leistung String 1/2 | `pdc1_w`, `pdc2_w` | W |
| DC-Spannung String 1/2 | `dc_voltage_1_v`, `dc_voltage_2_v` | V |
| DC-Strom String 1/2 | `dc_current_1_a`, `dc_current_2_a` | A |
| AC-Leistung Phase 1/2/3 | `pac1_w`, `pac2_w`, `pac3_w` | W |
| AC-Spannung Phase 1/2/3 | `ac_voltage_1_v` bis `ac_voltage_3_v` | V |
| AC-Strom Phase 1/2/3 | `ac_current_1_a` bis `ac_current_3_a` | A |
| Temperatur | `temperature_c` | °C |
| Betriebs-/Einspeisestunden | `operation_time_h`, `feed_in_time_h` | h |

`webbox_channels` ist eine Liste von Objekten mit `sensor` (Kennung oben) und
`channel` (exakter, bestätigter `meta`-Wert aus der Diagnose). Ein Eintrag ersetzt
für diesen Sensor die Vorbelegung. Ein Kanal darf nicht mehreren Sensoren
zugewiesen werden. Keine Zuordnung anhand übersetzter Anzeigenamen, kein Raten
von Phasen oder Strings und keine Berechnung fehlender DC-Leistung aus U × I.

Umrechnung ausschließlich anhand der gelieferten Einheit: W/kW → W,
Wh/kWh/MWh → kWh, V/mV → V, A/mA → A, s/h → h; Hz und °C unverändert.
Fehlende/unbekannte Einheiten, doppelte Metanamen, ungültige Werte und SMA-
Fehlwertmarkierungen werden verworfen. Punkt ist das RPC-Dezimalzeichen.
Fehlende Werte erzeugen weder Discovery noch einen Nullzustand. Bereits bekannte,
später fehlende Sensoren laufen individuell ab und bleiben als unavailable erhalten.
Beim Quellenwechsel bleiben Topic und Unique ID `<device_id>_<sensor>` identisch.
`device_id`, `mqtt_base_topic` und `discovery_prefix` deshalb beibehalten.

Beide Energiezähler behalten `device_class: energy`, `state_class: total_increasing`
und kWh. Für das Energy Dashboard vorzugsweise den echten Gesamtertragszähler
als Solarproduktion wählen. Tageszähler nur bei bestätigtem Tagesreset mappen;
kein Ableiten aus dem Gesamtzähler, kein künstliches Zurücksetzen. Vor dem Wechsel
prüfen, dass WebBox und Bluetooth denselben Wechselrichter/Zähler abbilden.

### Sichere Diagnose und Test in Home Assistant

1. Add-on stoppen, mindestens 30 Sekunden seit der letzten WebBox-RPC-Anfrage
   warten. Obige LAN-Konfiguration mit `webbox_diagnostics: true` speichern.
2. Add-on starten. Es liest einmal `GetDevices`, gibt nur die Geräteschlüssel
   im Protokoll aus und beendet sich ohne MQTT-Veröffentlichung.
3. Den Schlüssel des Sunny Boy unter `webbox_device_key` eintragen. Wieder
   mindestens 30 Sekunden warten und starten. Die Diagnose liest Geräte und
   anschließend alle Prozesskanäle des gewählten Geräts. Sie zeigt `meta`,
   `name`, `value`, `unit` und die bereits zugeordneten Messwerte.
4. Zur Zuordnung diese Kanalliste sowie Wechselrichtermodell und WebBox-Firmware
   liefern. Seriennummern/Geräteschlüssel dürfen konsistent anonymisiert werden;
   Kanalnamen, Werte und Einheiten unverändert lassen. **Keine options.json,
   Passwörter, Passwort-Hashes oder vollständigen Request-Dumps teilen.**
   Falls eine Kanalbedeutung unklar bleibt, zusätzlich die Kanalbeschreibung
   aus der SMA-Messwerte-Dokumentation des konkreten Wechselrichters liefern.
5. Bestätigte Zuordnungen als `webbox_channels` eintragen, Diagnose auf `false`
   setzen, mindestens 30 Sekunden warten und Add-on normal starten. Alternativ
   ist die Diagnose im Container mit `python3 /app/bridge.py --diagnose-webbox`
   verfügbar; niemals neben dem laufenden Collector ausführen.
6. In **Einstellungen → Geräte & Dienste → MQTT** Sensoren prüfen. Mit
   `log_level: debug` RPC-Status, Antwortdauer und Anzahl gültiger Messwerte
   prüfen; keine Passwort-/Hash-Ausgaben. MQTT-Topics und vorhandene Unique IDs
   mit dem bisherigen Betrieb vergleichen. Bei unveränderten Werten erfolgen
   keine wiederholten State-Nachrichten.
7. WebBox-LAN trennen: nach `stale_after_seconds` müssen Sensoren unavailable
   werden, ohne neue 0-Werte. Wieder verbinden: automatische Erholung abwarten.
   Auch einen einzelnen fehlenden Kanal prüfen; andere Sensoren bleiben gültig.
8. Für den Rückwechsel `source: bluetooth` sowie gültige bisherige Bluetooth-
   Optionen setzen. `webbox_diagnostics` wird dabei ignoriert.

Die Stale-Erkennung misst die Zeit seit der letzten gültigen RPC-Lieferung.
Das dokumentierte Kanalobjekt enthält keinen Messzeitstempel. Wiederholt eine
WebBox intern eingefrorene Cache-Werte mit gültigen Antworten, kann die Bridge
das nicht von konstanten Messungen unterscheiden. Das Erfassungsintervall und
den Bluetooth-Verbindungsstatus der WebBox zusätzlich prüfen. Ein Intervall
von 30 Sekunden garantiert keine neuen Wechselrichtermessungen alle 30 Sekunden.

### Rechte und Verifikation

HAOS-Containerrechte gelten statisch für das gesamte Add-on und lassen sich nicht
per Laufzeitoption umschalten. `host_network`, `NET_ADMIN`, `NET_RAW` und das
bestehende AppArmor-Verhalten bleiben für Bluetooth-Kompatibilität erhalten.
Der LAN-Code benötigt diese Sonderrechte nicht und verwendet sie nicht; auf einem
separat gepflegten lokalen LAN-only-Build können sie entfernt werden. Dieses
Update erstellt kein zweites Add-on und ändert die Rechte bestehender Installationen
nicht. Das gemeinsame Image enthält weiterhin SBFspot für den Quellenwechsel.

Automatisierte Prüfung: `python3 -m unittest discover -s tests -v` im Repository.
Die WebBox-Tests verwenden simulierte dokumentierte RPC-Antworten, keine reale
Bluetooth-WebBox-Aufzeichnung. Ein Hardwaretest und ein HAOS-Image-Build bleiben
vor produktiver Freigabe erforderlich.
