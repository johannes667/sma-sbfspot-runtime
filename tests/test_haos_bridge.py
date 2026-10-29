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


class ResilienceTests(unittest.TestCase):
    def test_only_received_sensor_values_refresh_their_age(self):
        readings = bridge.Measurements(stale_after=180)
        readings.update({"power_w": 100, "pac1_w": 100}, now=10)
        readings.update({"power_w": 120}, now=100)
        self.assertEqual(readings.fresh(189), {"power_w": 120, "pac1_w": 100})
        self.assertEqual(readings.fresh(190), {"power_w": 120})
        self.assertEqual(readings.fresh(280), {})

    def test_error_does_not_refresh_or_overwrite_last_measurement(self):
        readings = bridge.Measurements(stale_after=180)
        readings.update({"power_w": 2400}, now=0)
        readings.update({}, now=100)
        self.assertEqual(readings.fresh(179), {"power_w": 2400})
        self.assertEqual(readings.fresh(180), {})

    def test_real_zero_is_not_filtered(self):
        readings = bridge.Measurements(stale_after=180)
        readings.update({"power_w": 2400}, now=0)
        values = bridge.parse_output("SPOT_PACTOT: 0 (W)\nINFO: Done.")
        readings.update(values, now=1)
        self.assertEqual(readings.fresh(2), {"power_w": 0})

    def test_partial_completed_measurement_remains_usable(self):
        values = bridge.parse_output("SPOT_PACTOT: 1250 (W)\ngetSpotGridFrequency returned an error: -1\nINFO: Done.")
        self.assertEqual(values, {"power_w": 1250})
        self.assertNotIn("frequency_hz", values)

    def test_failure_diagnosis_does_not_disclose_raw_output(self):
        private = "Password=secret-value\n"
        self.assertEqual(bridge.failure_reason(private + "Logon failed. Check 'USER' Password", 1),
                         "Anmeldung: Wechselrichter-Passwort abgelehnt")
        self.assertIn("Bluetooth", bridge.failure_reason(private + "bthConnect() returned -1", 1))
        self.assertEqual(bridge.failure_reason(private + "getSpotGridFrequency returned an error: -1", 1),
                         "SBFspot-Lesefehler: getSpotGridFrequency=-1")
        self.assertNotIn("secret-value", bridge.failure_reason(private, 1))

    def test_individual_sensor_expires_and_recovers_without_fake_state(self):
        client = Client()
        publisher = bridge.Publisher(client, OPTIONS)
        publisher.connected.set()
        publisher.send_values({"power_w": 100, "pac1_w": 100})
        client.messages.clear()
        publisher.send_values({"power_w": 120}, unavailable=["pac1_w"])
        self.assertIn(("sma/sbfspot/pac1_w/availability", "offline"),
                      [(t, p) for t, p, _ in client.messages])
        self.assertFalse(any(t == "sma/sbfspot/pac1_w" for t, _, _ in client.messages))
        client.messages.clear()
        publisher.send_values({"power_w": 120, "pac1_w": 100})
        self.assertIn(("sma/sbfspot/pac1_w/availability", "online"),
                      [(t, p) for t, p, _ in client.messages])

    def test_discovery_requires_bridge_and_sensor_availability(self):
        client = Client()
        publisher = bridge.Publisher(client, OPTIONS)
        publisher.connected.set()
        publisher.send_values({"power_w": 100})
        payload = json.loads(next(p for t, p, _ in client.messages if t.endswith('/config')))
        self.assertEqual(payload['availability_mode'], 'all')
        self.assertEqual(payload['availability'], [{'topic': 'sma/sbfspot/availability'},
                                                  {'topic': 'sma/sbfspot/power_w/availability'}])

    def test_backoff_is_bounded_and_respects_long_configured_pause(self):
        self.assertEqual([bridge.retry_pause(30, n) for n in (1, 2, 3, 4, 10)], [30, 60, 120, 240, 300])
        self.assertEqual(bridge.retry_pause(600, 5), 600)

    def test_inflight_query_services_mqtt_then_reaps_child_on_timeout(self):
        from unittest.mock import Mock, patch
        import subprocess
        import threading
        process = Mock()
        process.communicate.side_effect = [subprocess.TimeoutExpired('SBFspot', 1), ('', '')]
        process.poll.return_value = None
        maintain = Mock()
        with patch.object(bridge.subprocess, 'Popen', return_value=process), \
             patch.object(bridge.time, 'monotonic', side_effect=[0, 0, 100]):
            with self.assertRaisesRegex(ValueError, 'Zeitlimit'):
                bridge.read_inverter('/data/SBFspot.cfg', threading.Event(), maintain)
        maintain.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(process.communicate.call_count, 2)


class SecurityAndUpgradeTests(unittest.TestCase):
    def test_all_discovery_payloads_match_1_2_2_with_existing_user_device_id(self):
        import hashlib
        client = Client()
        publisher = bridge.Publisher(client, {**OPTIONS, 'device_id': 'sma_sbfspot_amann',
                                             'device_name': 'SMA Wechselrichter Amann'})
        publisher.connected.set()
        publisher.send_values(dict.fromkeys(bridge.SENSORS, 1))
        payloads = {t: json.loads(v) for t, v, _ in client.messages if t.endswith('/config')}
        self.assertEqual(len(payloads), 22)
        fingerprint = hashlib.sha256(json.dumps(payloads, sort_keys=True).encode()).hexdigest()
        # Frozen from version 1.2.2 before removing WebBox. Covers all payloads,
        # including identifiers, unique IDs, topics, units, classes/availability.
        self.assertEqual(fingerprint, "ee3fc53ef343db1bdc2b6c313bd2653a01b9aa74e9a395b72ea52eb27c4c9333")

    def test_secret_file_replacement_repairs_permissions_and_ignores_target_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'SBFspot.cfg'
            target.write_text('old secret')
            target.chmod(0o644)
            bridge.write_config(OPTIONS, '', target)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            victim = Path(folder) / 'unrelated'
            victim.write_text('preserve me')
            target.unlink()
            target.symlink_to(victim)
            bridge.write_config(OPTIONS, '', target)
            self.assertFalse(target.is_symlink())
            self.assertEqual(victim.read_text(), 'preserve me')
            self.assertIn('User=user', target.read_text())

    def test_failed_secret_replacement_preserves_config_and_removes_temporary_file(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'SBFspot.cfg'
            target.write_text('old secret')
            with patch.object(bridge.os, 'replace', side_effect=OSError('private-password')):
                with self.assertRaises(OSError):
                    bridge.write_config(OPTIONS, '', target)
            self.assertEqual(target.read_text(), 'old secret')
            self.assertEqual(list(Path(folder).iterdir()), [target])

    def test_configuration_validation_rejects_injection_and_invalid_types(self):
        good = {**OPTIONS, 'poll_seconds': 30, 'retry_seconds': 5,
                'stale_after_seconds': 180, 'mqtt_port': 1883, 'mqtt_tls': False}
        bridge.validate_options(good)
        for update in ({'mqtt_base_topic': 'sma/#'}, {'discovery_prefix': 'ha\nsecret'},
                       {'mqtt_base_topic': '\ud800'}, {'device_id': 'bad/id'},
                       {'poll_seconds': 0}, {'retry_seconds': True}, {'mqtt_port': 65536},
                       {'stale_after_seconds': 20}, {'timezone': '/private-password'},
                       {'mqtt_tls': 'false'}, {'log_level': 'private-password'}):
            with self.subTest(update=update), self.assertRaises(bridge.BridgeError) as raised:
                bridge.validate_options({**good, **update})
            self.assertNotIn('private-password', str(raised.exception))

    def test_supervisor_http_errors_never_log_remote_response_or_token(self):
        from unittest.mock import Mock, patch
        from urllib.error import URLError
        with patch.dict(bridge.os.environ, {'SUPERVISOR_TOKEN': 'private-token'}):
            with patch.object(bridge, 'build_opener') as factory:
                factory.return_value.open.side_effect = URLError('private-password')
                with self.assertRaises(bridge.BridgeError) as raised:
                    bridge.broker_settings({})
                self.assertNotIn('private', str(raised.exception))
                request = factory.return_value.open.call_args.args[0]
                self.assertEqual(request.full_url, 'http://supervisor/services/mqtt')
            for raw in (b'[]', b'invalid', b'{"result":"ok","data":{"host":"bad/path"}}', b'x' * 65537):
                response = Mock()
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                response.read.return_value = raw
                with self.subTest(raw=raw[:60]), patch.object(bridge, 'build_opener') as factory:
                    factory.return_value.open.return_value = response
                    with self.assertRaises(bridge.BridgeError):
                        bridge.broker_settings({})

    def test_supervisor_success_and_manual_broker_preserve_auth_and_tls(self):
        from unittest.mock import Mock, patch
        broker = {'host': 'mqtt.example.test', 'port': 8883, 'username': 'user',
                  'password': 'private-password', 'ssl': True}
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({'result': 'ok', 'data': broker}).encode()
        with patch.dict(bridge.os.environ, {'SUPERVISOR_TOKEN': 'private-token'}), \
             patch.object(bridge, 'build_opener') as factory:
            factory.return_value.open.return_value = response
            self.assertEqual(bridge.broker_settings({}), broker)
        with patch.object(bridge, 'build_opener') as factory:
            self.assertEqual(bridge.broker_settings({'mqtt_host': broker['host'],
                'mqtt_port': 8883, 'mqtt_username': 'user', 'mqtt_password': 'private-password',
                'mqtt_tls': True}), broker)
            factory.assert_not_called()

    def test_supervisor_redirects_are_rejected(self):
        self.assertIsNone(bridge.NoRedirect().redirect_request(None, None, 302, '', {},
                                                            'http://untrusted.test'))

    def test_child_environment_excludes_supervisor_credentials_and_uses_no_shell(self):
        import threading
        from unittest.mock import Mock, patch
        process = Mock()
        process.communicate.return_value = ('INFO: Done.', '')
        process.returncode = 0
        process.poll.return_value = 0
        with patch.dict(bridge.os.environ, {'SUPERVISOR_TOKEN': 'private-token', 'HASSIO_TOKEN': 'private-token'}), \
             patch.object(bridge.subprocess, 'Popen', return_value=process) as popen:
            bridge.read_inverter('/data/SBFspot.cfg', threading.Event(), Mock())
        args, kwargs = popen.call_args
        self.assertEqual(args[0][0], '/usr/local/bin/SBFspot')
        self.assertFalse(kwargs.get('shell', False))
        self.assertNotIn('SUPERVISOR_TOKEN', kwargs['env'])
        self.assertNotIn('HASSIO_TOKEN', kwargs['env'])
        self.assertNotIn('private-token', repr(args[0]))

    def test_start_failure_exposes_only_fixed_messages(self):
        with self.assertLogs(bridge.LOG, level='ERROR') as logs:
            bridge.log_start_failure(bridge.BridgeError('Ungültige Zeitzone'))
        self.assertIn('Ungültige Zeitzone', logs.output[0])
        with self.assertLogs(bridge.LOG, level='ERROR') as logs:
            bridge.log_start_failure(OSError('private-password'))
        self.assertNotIn('private-password', logs.output[0])

    def test_nan_sentinels_and_malformed_numeric_tokens_are_not_zero(self):
        for raw in ('-2147483648', '2147483647', '4294967295', 'NaN', 'inf', '123junk', '1e3'):
            with self.subTest(raw=raw):
                self.assertEqual(bridge.parse_output('SPOT_PACTOT: ' + raw + ' (W)\nINFO: Done.'), {})
        self.assertEqual(bridge.parse_output('SPOT_PACTOT: 0 (W)\nINFO: Done.'), {'power_w': 0})


if __name__ == "__main__":
    unittest.main()
