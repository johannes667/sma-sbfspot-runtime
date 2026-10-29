# 1.2.2

- HTTP-RPC-Transport korrigiert: POST-Body verwendet die WebBox-Hülle `RPC={...}`.
- Leeres WebBox-Passwort sendet weiterhin kein `passwd`-Feld; keine geratenen Zugangsdaten.
- HTTP-Test mit lokalem simuliertem WebBox-Server prüft den tatsächlichen Request.

# 1.2.1

- WebBox-Diagnose zeigt die konkrete bereinigte Fehlerursache beim Start
  (HTTP-Status, RPC-Fehler, Zeitlimit oder Netzwerkfehler).
- Fremde Exception-Texte, RPC-Antworten und Zugangsdaten bleiben verborgen.

# 1.2.0

- Neue Datenquelle `webbox`: lesende SMA HTTP-RPC-Abfragen über LAN im selben Add-on.
- Bluetooth bleibt Standard; LAN benötigt keine Bluetooth-Konfiguration oder -Prozesse.
- Geräteerkennung, exakte Geräteauswahl, Kanal-/Einheitenprüfung und konfigurierbares Mapping.
- Lesende Kanaldiagnose zur Verifikation gerätespezifischer Bluetooth-WebBox-Kanäle.
- Mindestens 30 Sekunden zwischen sämtlichen RPC-Anfragen, Timeout und Wiederverbindung.
- Gemeinsame MQTT-Logik mit stabilen Unique IDs, sensorweiser Alterung und Änderungserkennung.
- Simulierte RPC-Tests; reale Bluetooth-WebBox-Kanäle bleiben bis Hardwarediagnose unbestätigt.

# 1.1.0

- Ungültige SMA-Rohwerte werden in SBFspot nicht mehr in 0-Messungen umgewandelt.
- Gültige Teilmessungen werden auch bei Fehlercodes für andere Messgrößen genutzt.
- Kurze Lesefehler werden mit einer Wiederholung und begrenztem Backoff behandelt.
- Messwerte laufen einzeln nach konfigurierbarer Zeit ab; keine erfundenen Nullen.
- MQTT-/HA-Wiederverbindungen senden frische RAM-Werte ohne zusätzliche BT-Abfrage.
- Diagnoseprotokoll mit Fehlerursache, Messdauer, BT-Signal und optionalen Messwerten.

# 1.0.0

- Eigenständiges HAOS-Add-on für SMA Bluetooth und MQTT.
- Veröffentlichung nur geänderter Messwerte, QoS 1, Retain und Last Will.
- Optionale Home-Assistant-Discovery und automatische MQTT-Diensterkennung.
- Keine Weboberfläche, Forecasts, SQL-, CSV- oder Historienfunktion.
