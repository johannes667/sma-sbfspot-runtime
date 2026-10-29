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

WebBox LAN unit tests (`test_webbox.py`) simulate documented RPC envelopes and
cover discovery, device selection, units, absent/invalid values, HTTP/RPC/network
errors, timeouts, minimum request spacing, read-only procedures, MQTT identity
compatibility, energy metadata, availability expiry/recovery, diagnostics and
source selection without Bluetooth setup. These are not real Bluetooth-WebBox
recordings; obtain the device-specific channels using `webbox_diagnostics: true`
as described in the add-on DOCS.md before claiming hardware compatibility.
