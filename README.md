# SMA SBFspot Runtime 2.1

Unraid/Docker Runtime für SMA Bluetooth Wechselrichter mit Web-Dashboard, MQTT, Home Assistant Discovery und SQLite-Historie.

## Lokal bauen

```bash
cd /mnt/user/appdata
unzip sma-sbfspot-runtime-2.1.zip
cd sma-sbfspot-runtime-2.1
docker build -t local/sma-sbfspot-runtime:2.1 .
```

## Unraid Template

```bash
cp templates/SMA-SBFspot-Runtime-2.1.xml /boot/config/plugins/dockerMan/templates-user/
```

## Web

```text
http://UNRAID-IP:8088
```
