# SMA SBFspot MQTT für Home Assistant OS

Das Add-on liest einen SMA-Wechselrichter direkt über klassisches Bluetooth
und veröffentlicht echte Messwerte per MQTT. Es startet nur die Python-Bridge
und jeweils einen SBFspot-Prozess. Kein WebBox-Zugriff, HTTP-RPC-Client,
Dashboard, Forecast, Datenbank, CSV-Export oder Bluetooth-/D-Bus-Dienst.
Unterstützte Architekturen: amd64 und aarch64.

## Installation und Bluetooth

1. Im Add-on-Store unter Repositories
   `https://github.com/johannes667/sma-sbfspot-runtime` hinzufügen.
2. **SMA SBFspot MQTT** installieren. SBFspot wird beim Image-Build kompiliert.
3. Einen kompatiblen klassischen Bluetooth-Adapter am HAOS-Host bereitstellen;
   bei Unraid/VM an die HAOS-VM durchreichen. Ein ESPHome-Proxy genügt nicht.
4. `inverter_bluetooth_address` auf die MAC des Wechselrichters setzen,
   `inverter_password` auf dessen Benutzerpasswort. `local_bluetooth_address`
   bleibt bei einem Adapter normalerweise leer. `timezone` ist eine IANA-Zeitzone.
5. MQTT konfigurieren, speichern und starten. Bei `discovery: true` erscheinen
   ausschließlich tatsächlich gelieferte Messgrößen in der MQTT-Integration.

Für eine lokale Installation den Ordner `sbfspot_mqtt` nach `/addons/` kopieren
und im Add-on-Store nach Updates suchen. Ein erster Build benötigt Internet.

## Update auf 1.3.0: vorhandene Entitäten behalten

Die WebBox-Erweiterung aus 1.2.x ist vollständig entfernt. Nur Bluetooth ist
verfügbar. Die bisherigen Optionen `source` und `webbox_*` entfallen; der
Supervisor ignoriert unbekannte Optionen bei der Validierung. Falls sie noch
im YAML-Editor angezeigt werden, können sie entfernt werden. Die Bridge
ignoriert solche alten Schlüssel auch dann, wenn sie noch in options.json stehen.

**Keine Konfiguration zurücksetzen, kein Gerät und keine Entität löschen.**
Folgende bestehenden Werte exakt beibehalten:

```yaml
mqtt_base_topic: sma/sbfspot
discovery_prefix: homeassistant
device_id: sma_sbfspot_amann  # Beispiel: eigene bisherige Kennung beibehalten
device_name: SMA Wechselrichter Amann
```

Die Gerätekennung lautet weiterhin `device_id`, die Unique ID jedes Sensors
`<device_id>_<sensor>`, das Discovery-Topic
`<discovery_prefix>/sensor/<device_id>/<sensor>/config`. State-Topics bleiben
`<mqtt_base_topic>/<sensor>`. Auch Einheiten, State Classes und Availability
bestehender Discovery-Payloads bleiben unverändert. Ein Regressionstest vergleicht
alle 22 möglichen Discovery-Payloads mit Version 1.2.2. Die tatsächlich verwendeten
Entity IDs verwaltet Home Assistant; vorhandene Benutzerbenennungen bleiben dort.

Das Update erzeugt keine neuen Gerätekennungen und löscht keine Discovery-
Nachrichten. Zuvor entfernte Forecast-/DC-Gesamt-/Wirkungsgrad-Sensoren werden
nicht wieder angelegt. Nicht unterstützte Phasen werden nicht künstlich erzeugt.

## MQTT und Energy Dashboard

Bei leerem `mqtt_host` fragt das Add-on die MQTT-Diensteinstellungen beim
Supervisor ab. Alternativ `mqtt_host`, `mqtt_port`, `mqtt_username` und
`mqtt_password` für einen eigenen Broker konfigurieren.
`mqtt_tls: true` aktiviert Zertifikatsprüfung gegen die System-CAs; üblicher
TLS-Port ist 8883. Private CAs sind nicht konfigurierbar. Zugangsdaten nie in
Hostnamen, Topics oder Logausgaben eintragen.

Messwerte, Discovery, Availability und Status werden mit QoS 1 und Retain
veröffentlicht. Nur geänderte Payloads werden gesendet; der Cache wird erst nach
Bestätigung des Brokers aktualisiert. QoS 1 kann protokollbedingt Duplikate liefern.
Nach MQTT-Wiederverbindung oder HA-Birth (`<discovery_prefix>/status = online`)
werden Discovery und noch frische RAM-Werte erneut übertragen, ohne zusätzliche
Bluetooth-Abfrage. Ein Broker-Ausfall stoppt die Auslesung nicht. Keine dauerhafte
Messwertspeicherung, keine Warteschlange mit historischen Messungen.

Unterstützte Sensor-Kennungen:

| Messgröße | MQTT-Kennung | Einheit |
| --- | --- | --- |
| AC-Gesamtleistung | `power_w` | W |
| Tages-/Gesamtertrag | `energy_today_kwh`, `energy_total_kwh` | kWh |
| AC-Leistung je Phase | `pac1_w`, `pac2_w`, `pac3_w` | W |
| AC-Spannung/-Strom | `ac_voltage_1_v` bis `ac_voltage_3_v`, `ac_current_1_a` bis `ac_current_3_a` | V / A |
| DC-Leistung je Eingang | `pdc1_w`, `pdc2_w` | W |
| DC-Spannung/-Strom | `dc_voltage_1_v`, `dc_voltage_2_v`, `dc_current_1_a`, `dc_current_2_a` | V / A |
| Wechselrichtertemperatur | `temperature_c` | °C |
| Netzfrequenz | `frequency_hz` | Hz |
| Betriebs-/Einspeisestunden | `operation_time_h`, `feed_in_time_h` | h |

Nur Werte eines abgeschlossenen Laufs werden übernommen. Fehlende/ungültige
Messwerte werden nie durch 0 ersetzt. Ein SBFspot-Patch verhindert bereits die
Umwandlung von SMA-NaN-Markierungen in Nullen. Echte Nullen bleiben gültig.
Optionale Lesefehler dürfen gültige andere Messwerte desselben Laufs nicht verwerfen.

Beide Energiezähler behalten `device_class: energy`, `state_class: total_increasing`
und kWh. Im Energy Dashboard den bestehenden Gesamtertragszähler als
Solarproduktion weiterverwenden. Kein künstliches Zurücksetzen oder Berechnen
eines Tageszählers. Historische Lücken werden nicht nachträglich aufgefüllt.

## Abfrageintervall, Fehler und Availability

- `poll_seconds`: Pause nach abgeschlossener Abfrage, Standard 30, Minimum 10,
  Maximum 3600 Sekunden. Die Abfragedauer kommt dazu; keine garantierte Echtzeit.
- `retry_seconds`: einmalige schnelle Wiederholung, Standard 5, Bereich 1–60.
  Danach begrenzter exponentieller Backoff bis 300 Sekunden; ein längeres
  normales Abfrageintervall bleibt erhalten.
- `stale_after_seconds`: maximales Alter jedes einzelnen Sensors, Standard 180,
  Bereich 30–7200. Größer als Abfragepause plus übliche Abfragedauer wählen.
- `log_level`: normalerweise `info`; `debug` für Dauer, Exit-Code, Bluetooth-Signal
  und geparste Messwerte. Keine Rohantworten oder Passwörter im Log.

Jede Abfrage hat ein Zeitlimit von 90 Sekunden. Es läuft maximal ein Prozess;
bei Abbruch/Timeout wird er beendet und eingesammelt. MQTT-/Alterungsprüfung
läuft auch während der Abfrage. Nach einem Fehler bleiben echte Messwerte nur
bis zum Ablauf ihrer jeweiligen Altersgrenze verfügbar.

Discovery verlangt sowohl `<mqtt_base_topic>/availability` als auch
`<mqtt_base_topic>/<sensor>/availability` auf `online`. Einzelne fehlende Sensoren
laufen unabhängig ab. Wenn alle Werte abgelaufen sind, geht auch die gemeinsame
Availability offline. Bei sauberem Stoppen wird offline gesendet; bei einem
Verbindungsabbruch übernimmt MQTT Last Will. Retained-State-Werte bleiben im
Broker gespeichert, Availability kennzeichnet ihre Gültigkeit.
`<mqtt_base_topic>/status` zeigt `waiting`, `online`, `retrying`, `stale` oder `error`.

## Sicherheit und Best Practices

- Keine zusätzlichen Container-Capabilities, insbesondere kein `NET_ADMIN` oder
  zusätzlich angefordertes `NET_RAW`. Kein Docker-Socket, kein `full_access`,
  kein Zugriff auf HA-Konfigurationsordner oder eigene Netzwerkdienste.
- Standard-AppArmor-Profil ist aktiviert. Host-Netzwerk bleibt nötig, damit die
  Linux-Bluetooth-Sockets den Host-Adapter erreichen. Der geprüfte SBFspot-Code
  verwendet RFCOMM, keine direkte HCI-Steuerung. Der Adapter muss bereits vom
  Host initialisiert sein. Protection Mode aktiviert lassen.
- Supervisor-Zugriff ausschließlich für den MQTT-Dienst mit Standardrolle;
  keine Manager-/Admin-Rolle. Der Token wird nicht an SBFspot vererbt. HTTP-
  Redirects und Proxy-Nutzung für den Supervisor-Aufruf sind ausgeschaltet.
- SBFspot läuft als Benutzer des Wechselrichters (`User=user`) und ohne
  Zeitabgleich (`SynchTime=0`), Archive, SQL oder CSV. Keine Shell-Ausführung.
- Generierte Passwortkonfiguration: atomischer Austausch mit Dateirechten 0600,
  auch nach älteren zu offenen Dateirechten. Keine Symlink-Verfolgung am Ziel;
  temporäre Dateien werden nach Fehlern entfernt. Die options.json wird vom
  Supervisor verwaltet und enthält weiterhin die vom Nutzer gesetzten Geheimnisse.
- Eigene Fehlermeldungen sind bereinigt. Fremde Exception-Texte, HTTP-Antworten
  und Konfigurationsinhalte werden nicht protokolliert. Eingaben werden vor
  Prozessstart geprüft. Python startet isoliert (`-I`), ohne Bytecode-Dateien.
- Mehrstufiger Build: Compiler und Git bleiben außerhalb des Laufzeitimages.
  Python verwendet nur die Standardbibliothek und das Paho-Paket von Debian.
  Bibliotheken bleiben über Debian-Sicherheitsupdates aktualisierbar.

Grundlagen: [HA App-Sicherheit](https://developers.home-assistant.io/docs/apps/security/),
[MQTT Discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery),
[Python subprocess](https://docs.python.org/3/library/subprocess.html#security-considerations),
[Python tempfile](https://docs.python.org/3/library/tempfile.html#tempfile.mkstemp),
[Docker-AppArmor-Profil](https://github.com/moby/profiles/blob/main/apparmor/template.go).
SBFspot ist auf Quellstand `b77f65047e9f4a136a09677838f6b4e5024862ee` festgelegt;
[Bluetooth-Implementierung](https://github.com/SBFspot/SBFspot/blob/b77f65047e9f4a136a09677838f6b4e5024862ee/SBFspot/Bluetooth.cpp).
Lizenz CC BY-NC-SA 3.0; die Lizenz liegt auch im Image.

## Prüfung nach dem Update

1. Bestehende MQTT-Konfiguration und Gerätekennung behalten; auf 1.3.0 aktualisieren.
2. Starten: `MQTT verbunden` und erfolgreiche Messung im Log prüfen.
3. Vorhandene Sensoren und Energy-Dashboard-Quelle prüfen; keine neuen Duplikate.
4. Kurzer Funkfehler: Wiederholung ohne neue Nullwerte. Längerer Ausfall:
   nach Altersgrenze unavailable. Wiederhergestellte Funkverbindung: automatische Erholung.
5. Bei Bluetooth-Fehlern Adapter-/VM-Zuordnung, Host-Initialisierung und Reichweite
   prüfen. Nur ein Collector soll den Wechselrichter direkt abfragen.

CI prüft Syntax/Lint, Unit-Tests, amd64-Image-Build und reale Paho-Kommunikation
gegen einen simulierten Broker im Container ohne zusätzliche Capabilities.
Das ersetzt keinen Hardwaretest mit deinem Adapter, keine Messwertprüfung am
Wechselrichter und keinen aarch64-/HAOS-AppArmor-Lauf. Bei AppArmor-Problemen
benötigt die Diagnose die entsprechende DENIED-Meldung aus dem Host-Protokoll.
