import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("bridge", Path(__file__).resolve().parents[1] / "sbfspot_mqtt/bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

OPTIONS = {
    "inverter_bluetooth_address": "00:80:25:01:02:03",
    "inverter_password": "0000", "timezone": "Europe/Berlin",
    "mqtt_base_topic": "sma/sbfspot", "discovery": True,
    "discovery_prefix": "homeassistant", "device_id": "sma_sbfspot",
    "device_name": "SMA Wechselrichter",
}


class Ack:
    rc = 0

    def __init__(self, acknowledged):
        self.acknowledged = acknowledged

    def wait_for_publish(self, timeout):
        pass

    def is_published(self):
        return self.acknowledged


class Client:
    def __init__(self):
        self.messages = []
        self.acknowledged = True

    def publish(self, topic, payload, **kwargs):
        self.messages.append((topic, payload, kwargs))
        return Ack(self.acknowledged)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.publisher = bridge.Publisher(self.client, OPTIONS)
        self.publisher.connected.set()

    def test_parse_upstream_debug_units_and_missing_values(self):
        # Matches SBFspot debug_watt/volt/amp/kwh/hour at the pinned revision.
        values = bridge.parse_output('''SPOT_PACTOT : 1200 (W) Sat Oct 24 12:00:00 2026
SPOT_ETODAY : 4.125 (kWh) Sat Oct 24 12:00:00 2026
SPOT_UDC1   : 302.20 (V) Sat Oct 24 12:00:00 2026
SPOT_IDC1   : 2.123 (A) Sat Oct 24 12:00:00 2026
Device Temperature: 32.5°C
INFO: Done.
''')
        self.assertEqual(values, {"power_w": 1200, "energy_today_kwh": 4.125,
                                 "dc_voltage_1_v": 302.2, "dc_current_1_a": 2.123,
                                 "temperature_c": 32.5})
        self.assertNotIn("pdc2_w", values)
        self.assertEqual(bridge.parse_output("SPOT_PACTOT: 0 (W)\nConnection failed"), {})
        self.assertEqual(bridge.parse_output("SPOT_PACTOT: -2147483648 (W)\nINFO: Done."), {})

    def test_changed_value_only(self):
        self.assertTrue(self.publisher.send_values({"power_w": 100, "energy_today_kwh": 1}))
        self.client.messages.clear()
        self.assertTrue(self.publisher.send_values({"power_w": 100, "energy_today_kwh": 1}))
        self.assertEqual(self.client.messages, [])
        self.publisher.send_values({"power_w": 101, "energy_today_kwh": 1})
        self.assertEqual([(t, p) for t, p, _ in self.client.messages], [("sma/sbfspot/power_w", "101")])

    def test_no_cache_until_broker_acknowledges(self):
        self.client.acknowledged = False
        self.assertFalse(self.publisher.publish("state", "100"))
        self.assertNotIn("state", self.publisher.cache)
        self.client.acknowledged = True
        self.assertTrue(self.publisher.publish("state", "100"))
        self.assertEqual(len(self.client.messages), 2)

    def test_reconnect_and_ha_birth_resend_snapshot(self):
        self.publisher.send_values({"power_w": 100})
        self.client.messages.clear()
        self.publisher.reset.set()
        self.publisher.flush_reset()
        self.publisher.send_values({"power_w": 100})
        self.assertIn(("sma/sbfspot/power_w", "100"), [(t, p) for t, p, _ in self.client.messages])
        discovery = [json.loads(p) for t, p, _ in self.client.messages if t.endswith("/config")]
        self.assertEqual(discovery[0]["device_class"], "power")
        self.assertTrue(all(kwargs == {"qos": 1, "retain": True} for _, _, kwargs in self.client.messages))

    def test_offline_and_recovery_are_published_once(self):
        self.publisher.send_values({"power_w": 100})
        self.client.messages.clear()
        self.publisher.publish(self.publisher.availability, "offline")
        self.publisher.publish(self.publisher.availability, "offline")
        self.publisher.send_values({"power_w": 100})
        self.assertEqual([p for t, p, _ in self.client.messages if t.endswith("/availability")], ["offline", "online"])
        self.assertFalse(any(t.endswith("/power_w") for t, _, _ in self.client.messages))

    def test_config_uses_remote_bt_address_and_does_not_change_inverter_clock(self):
        template = Path(__file__).resolve().parents[1] / "config/SBFspot.cfg.example"
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "SBFspot.cfg"
            bridge.write_config(OPTIONS, template.read_text(), target)
            text = target.read_text()
            self.assertIn("BTAddress=00:80:25:01:02:03\n", text)
            self.assertIn("SynchTime=0\n", text)
            self.assertIn("CSV_Export=0\n", text)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError):
                bridge.write_config({**OPTIONS, "inverter_password": "0000\nMQTT_Host=bad"}, "", target)


if __name__ == "__main__":
    unittest.main()
