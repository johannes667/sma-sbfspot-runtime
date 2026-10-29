# Bridge verification

Run the standard-library unit tests from the repository root:

```sh
python3 -m unittest discover -s tests -v
```

Build the add-on and run its integration test in a disposable container:

```sh
docker build -t sma-sbfspot-haos:test sbfspot_mqtt
docker run --rm -e RUN_HAOS_SMOKE_TEST=1 \
  -v "$PWD/tests/smoke_haos.py:/test.py:ro" \
  --entrypoint python3 sma-sbfspot-haos:test /test.py
```

The integration test replaces SBFspot inside that temporary container with a
script emitting controlled measurements. It uses the real bridge and Paho client
with a minimal local MQTT server implementing connect, subscribe, QoS 1 publish
acknowledgements and keepalive. It takes about one minute and verifies:

- one failed read retries promptly without creating zero or unavailable states;
- unchanged power is suppressed and a valid partial read with a nonzero exit is used;
- an HA birth republishes the snapshot without an extra hardware query;
- each missing measurement expires independently and sustained failure goes offline;
- SIGTERM cleanly stops the bridge.

The C++ validity patch is checked and compiled during the image build. These tests
do not establish compatibility with a particular Bluetooth adapter, the actual SMA
radio link, HAOS Supervisor or the aarch64 target.

Version 1.3.0 removes WebBox completely. Added regressions freeze all 22 possible
Discovery payloads against 1.2.2 with the existing device_id sma_sbfspot_amann.
Security tests cover atomic 0600 writes, symlinks, failed-write cleanup, topic/type
validation, broker responses, rejected redirects, sanitized logging and excluding
Supervisor credentials from the SBFspot child. Removed WebBox/source options are
included in the container smoke test to prove they cannot activate LAN acquisition.

The PR workflow builds the actual amd64 add-on image and runs the MQTT smoke test
with --cap-drop ALL, --network none and no-new-privileges. The broker uses loopback
inside that disposable container. Python runs in isolated mode and uses the actual
Debian Paho dependency. No host hardware or external MQTT credentials are needed.
The firmware/radio link, actual HAOS AppArmor behavior and aarch64 still require
hardware/target validation. No tests delete Home Assistant entities or MQTT topics.
