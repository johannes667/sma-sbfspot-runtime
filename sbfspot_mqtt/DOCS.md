# SMA SBFspot MQTT für Home Assistant OS

Dieses Add-on fragt **einen SMA-Wechselrichter über klassisches Bluetooth** ab
und veröffentlicht Messwerte einzeln per MQTT. Kein Dashboard, Flask, Forecast,
SQLite, CSV-Export oder lokales Messwertarchiv. SBFspot wird ohne SQL-Unterstützung
gebaut; zur Laufzeit läuft nur die Python-Bridge mit dem jeweiligen SBFspot-Aufruf.
Unterstützte Zielarchitekturen: amd64 und aarch64.

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

Im Repository liegen außerdem `repository.yaml` und der Add-on-Ordner, damit es
nach Veröffentlichung dieser Änderungen als Add-on-Repository hinzugefügt werden
kann. Eine lokale Arbeitskopie allein aktualisiert das GitHub-Repository nicht.

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
Birth-Signal werden Discovery und aktuell ausgelesene Werte erneut veröffentlicht.
QoS 1 kann auf Protokollebene Duplikate erzeugen. Der Vergleich erfolgt im RAM;
es wird keine Messwertdatei geschrieben.

Weitere Topics sind z. B. `energy_today_kwh`, `energy_total_kwh`, `pac1_w`,
`dc_voltage_1_v`, `dc_current_1_a`, `temperature_c` und `frequency_hz`.
Discovery wird nur für tatsächlich gelieferte Messgrößen angelegt. Die Bridge
unterstützt einen Wechselrichter sowie DC-Strings 1/2 und AC-Phasen 1/2/3.

`<mqtt_base_topic>/availability` zeigt `online` nach einer gültigen Messung und
`offline` nach einer fehlgeschlagenen Abfrage, beim Stoppen oder über MQTT Last
Will nach einem Verbindungsabbruch. Nach einem Absturz erkennt der Broker den
Ausfall spätestens über die MQTT-Verbindungsüberwachung. Fehlende Werte werden
nicht als 0 erfunden. Retained Messwerte bleiben im Broker; bei einzelnen nicht
mehr gelieferten Messgrößen bleibt der letzte Wert erhalten. Ein Lesefehler kann
insbesondere nachts bei abgeschaltetem Wechselrichter auftreten.

## Optionen

- `poll_seconds`: Pause zwischen Bluetooth-Abfragen, kein MQTT-Sendeintervall.
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
