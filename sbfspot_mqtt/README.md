# SMA SBFspot MQTT

Schlankes Home-Assistant-OS-Add-on: SMA Bluetooth oder Sunny WebBox über LAN → MQTT.
Messwerte werden nur bei Änderung veröffentlicht. Für das Erkennen von
Änderungen bleibt eine regelmäßige Geräteabfrage notwendig.

Installation und Optionen: [DOCS.md](DOCS.md).

Ab Version 1.2.0: `source: bluetooth|webbox`. LAN benötigt keinen Bluetooth-Stick
am HAOS-Host. WebBox-Kanäle vor Ort per lesender Diagnose verifizieren;
Anleitung, unterstützte Sensoren und Grenzen: [DOCS.md](DOCS.md#sunny-webbox-mit-bluetooth-über-lan-ab-120).
