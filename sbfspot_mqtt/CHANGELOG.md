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
