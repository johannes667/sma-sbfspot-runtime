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
