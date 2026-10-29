"""Simulated SMA RPC envelopes; not recordings from a Bluetooth WebBox."""
import json
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from test_haos_bridge import bridge, Client, OPTIONS

WB_OPTIONS = {**OPTIONS, 'source': 'webbox', 'webbox_host': '192.0.2.100',
              'poll_seconds': 30, 'webbox_password': 'private-password'}


def channel(meta, value, unit):
    return {'meta': meta, 'value': value, 'unit': unit}


class WebBoxTests(unittest.TestCase):
    def setUp(self):
        self.box = bridge.WebBox(WB_OPTIONS)
        self.stop = Mock()
        self.stop.wait.return_value = False

    def response(self, request, **kwargs):
        payload = json.loads(request.data)
        self.requests.append(payload)
        result = self.results.pop(0)
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({
            'version': '1.0', 'proc': payload['proc'], 'id': payload['id'],
            'result': result}).encode()
        return response

    def simulate(self, results):
        self.requests = []
        self.results = results
        self.box.opener.open = Mock(side_effect=self.response)

    def test_discovery_nested_devices_and_successful_acquisition(self):
        self.simulate([{'devices': [{'key': 'WebBox:1', 'children': [{'key': 'SB21TL:2'}]}]},
                       {'devices': [{'key': 'SB21TL:2', 'channels': [channel('Pac', '1.25', 'kW'),
                          channel('E-Total', '1234000', 'Wh'), channel('Fac', '50', 'Hz')]}]}])
        self.assertEqual(self.box.read(self.stop), {'power_w': 1250, 'energy_total_kwh': 1234, 'frequency_hz': 50})
        self.assertEqual([r['proc'] for r in self.requests], ['GetDevices', 'GetProcessData'])
        self.assertEqual(self.requests[1]['params'], {'devices': [{'key': 'SB21TL:2', 'channels': None}]})
        self.assertNotIn('private-password', json.dumps(self.requests))
        self.assertEqual(self.requests[0]['passwd'], bridge.hashlib.md5(b'private-password').hexdigest())
        args, kwargs = self.box.opener.open.call_args
        self.assertEqual(args[0].full_url, 'http://192.0.2.100:80/rpc')
        self.assertEqual(args[0].method, 'POST')
        self.assertEqual(kwargs['timeout'], 10)
        self.assertGreater(self.stop.wait.call_args.args[0], 29)

    def test_no_implicit_multi_inverter_selection(self):
        self.simulate([{'devices': [{'key': 'SB:1'}, {'key': 'SB:2'}]}])
        with self.assertRaisesRegex(bridge.WebBoxError, 'uneindeutig'):
            self.box.read(self.stop)
        self.assertEqual(len(self.requests), 1)

    def test_explicit_key_selection(self):
        self.box.key = 'custom:2'
        self.simulate([{'devices': [{'key': 'custom:2'}, {'key': 'SB:1'}]},
                       {'devices': [{'key': 'custom:2', 'channels': []}]}])
        self.assertEqual(self.box.read(self.stop), {})
        self.assertEqual(self.box.selected, 'custom:2')

    def test_missing_invalid_and_real_zero(self):
        for invalid in (None, True, 'NaN', 'Infinity', '-2147483648', '4294967295', '1,23', '', '--', '9' * 400):
            with self.subTest(invalid=invalid):
                self.assertEqual(bridge.parse_webbox([channel('Pac', invalid, 'W')], self.box.mapping), {})
        self.assertEqual(bridge.parse_webbox([channel('Pac', '10', {})], self.box.mapping), {})
        self.assertEqual(bridge.parse_webbox([channel('Pac', '0', 'W')], self.box.mapping), {'power_w': 0})
        self.assertEqual(bridge.parse_webbox([channel('E-Total', '-1', 'kWh'),
                                              channel('Pac', '10', 'VA')], self.box.mapping), {})
        self.assertEqual(bridge.parse_webbox([channel('Pac', '10', 'W'), channel('Pac', '11', 'W')], self.box.mapping), {})

    def test_confirmed_custom_mapping_all_sensor_types(self):
        items = [{'sensor': key, 'channel': 'confirmed-' + key} for key in bridge.SENSORS]
        mapping = bridge.webbox_mapping({'webbox_channels': items})
        channels = [channel(meta, '12.5', bridge.SENSORS[key][1]) for key, meta in mapping.items()]
        self.assertEqual(bridge.parse_webbox(channels, mapping), dict.fromkeys(bridge.SENSORS, 12.5))
        self.assertEqual(bridge.parse_webbox([channel(mapping['operation_time_h'], '3600', 's')], mapping),
                         {'operation_time_h': 1})
        with self.assertRaises(ValueError):
            bridge.webbox_mapping({'webbox_channels': [{'sensor': 'made_up', 'channel': 'X'}]})
        with self.assertRaises(ValueError):
            bridge.webbox_mapping({'webbox_channels': [{'sensor': 'pac1_w', 'channel': 'Pac'}]})

    def test_http_rpc_timeout_and_network_errors_are_sanitized(self):
        for error, message in [(HTTPError('private', 503, 'password', None, None), 'HTTP-Fehler 503'),
                               (URLError('private-password'), 'Netzwerkfehler'),
                               (TimeoutError('private-password'), 'Zeitlimit'),
                               (URLError(TimeoutError('private-password')), 'Zeitlimit')]:
            self.box.opener.open = Mock(side_effect=error)
            with self.subTest(error=error), self.assertRaisesRegex(bridge.WebBoxError, message) as raised:
                self.box.rpc('GetDevices', None, self.stop)
            self.assertNotIn('private', str(raised.exception))
        for raw in (b'{"error":"private-password"}', b'invalid', b'[]',
                    b'{"result":{},"id":"wrong","proc":"GetDevices","version":"1.0"}'):
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.read.return_value = raw
            self.box.opener.open = Mock(return_value=response)
            with self.assertRaises(bridge.WebBoxError) as raised:
                self.box.rpc('GetDevices', None, self.stop)
            self.assertNotIn('private', str(raised.exception))

    def test_read_only_and_cancellable_rate_limit(self):
        with self.assertRaisesRegex(bridge.WebBoxError, 'erlaubte'):
            self.box.rpc('SetParameter', {}, self.stop)
        self.stop.wait.return_value = True
        self.box.opener.open = Mock()
        with self.assertRaisesRegex(bridge.WebBoxError, 'abgebrochen'):
            self.box.rpc('GetDevices', None, self.stop)
        self.box.opener.open.assert_not_called()

    def test_source_switch_preserves_unique_ids_and_energy_metadata(self):
        identities = []
        for source in ('bluetooth', 'webbox'):
            client = Client()
            publisher = bridge.Publisher(client, {**OPTIONS, 'source': source})
            publisher.connected.set()
            publisher.send_values({'power_w': 10, 'energy_today_kwh': 1, 'energy_total_kwh': 100})
            configs = {t: json.loads(p) for t, p, _ in client.messages if t.endswith('/config')}
            identities.append({t: p['unique_id'] for t, p in configs.items()})
            for p in configs.values():
                if p['device_class'] == 'energy':
                    self.assertEqual((p['unit_of_measurement'], p['state_class']), ('kWh', 'total_increasing'))
            self.assertEqual(len(configs), 3)
        self.assertEqual(*identities)

    def test_data_loss_expires_without_fake_mqtt_state_and_recovers(self):
        client = Client()
        publisher = bridge.Publisher(client, WB_OPTIONS)
        publisher.connected.set()
        readings = bridge.Measurements(30)
        readings.update({'power_w': 10}, 0)
        publisher.send_values(readings.fresh(0))
        client.messages.clear()
        readings.update({}, 10)
        publisher.send_values(readings.fresh(30), set(bridge.SENSORS) - set(readings.fresh(30)))
        self.assertIn(('sma/sbfspot/availability', 'offline'), [(t, p) for t, p, _ in client.messages])
        self.assertFalse(any(t == 'sma/sbfspot/power_w' for t, _, _ in client.messages))
        readings.update({'power_w': 11}, 31)
        publisher.send_values(readings.fresh(31))
        self.assertIn(('sma/sbfspot/power_w', '11'), [(t, p) for t, p, _ in client.messages])

    def test_source_configuration_never_touches_bluetooth_in_lan_mode(self):
        with patch.object(bridge, 'write_config') as write, patch.object(bridge.Path, 'read_text') as read:
            self.assertIsInstance(bridge.configure_source(WB_OPTIONS), bridge.WebBox)
            write.assert_not_called()
            read.assert_not_called()
            bridge.configure_source({**OPTIONS, 'poll_seconds': 30})
            write.assert_called_once()
        with self.assertRaises(ValueError):
            bridge.configure_source({**WB_OPTIONS, 'poll_seconds': 10})

    def test_start_failure_reports_only_sanitized_webbox_details(self):
        with self.assertLogs(bridge.LOG, level='ERROR') as logs:
            bridge.log_start_failure(bridge.WebBoxError('HTTP-Fehler 503'))
        self.assertIn('WebBox-Start fehlgeschlagen: HTTP-Fehler 503', logs.output[0])
        for error in (ValueError('private-password'), OSError('private-password')):
            with self.assertLogs(bridge.LOG, level='ERROR') as logs:
                bridge.log_start_failure(error)
            self.assertIn(type(error).__name__, logs.output[0])
            self.assertNotIn('private-password', logs.output[0])

    def test_diagnostic_mode_does_not_start_normal_collector(self):
        with patch.object(bridge.Path, 'read_text', return_value=json.dumps({
                **WB_OPTIONS, 'webbox_diagnostics': True})), \
             patch.object(bridge, 'diagnose_webbox') as diagnose, \
             patch.object(bridge, 'configure_source') as configure:
            bridge.main()
        diagnose.assert_called_once()
        configure.assert_not_called()

    def test_diagnostic_output_contains_channels_but_no_password_hash(self):
        import io
        from contextlib import redirect_stdout
        data = [
            {'devices': [{'key': 'SB:1'}]},
            {'devices': [{'key': 'SB:1', 'channels': [channel('Pac', '10', 'W')]}]},
        ]
        output = io.StringIO()
        with patch.object(bridge.Path, 'read_text', return_value=json.dumps({
                **WB_OPTIONS, 'webbox_device_key': 'SB:1'})), \
             patch.object(bridge.WebBox, 'rpc', side_effect=data) as rpc, redirect_stdout(output):
            bridge.diagnose_webbox()
        self.assertEqual([call.args[0] for call in rpc.call_args_list], ['GetDevices', 'GetProcessData'])
        self.assertIn('Pac', output.getvalue())
        self.assertNotIn('private-password', output.getvalue())
        self.assertNotIn(self.box.password_hash, output.getvalue())

    def test_worker_keeps_availability_checks_running_and_does_not_overlap(self):
        entered = threading.Event()
        release = threading.Event()
        self.box.read = Mock(side_effect=lambda stop: (entered.set(), release.wait(2), {'power_w': 10})[-1])
        checks = []
        def maintain():
            checks.append(entered.is_set())
            release.set()
        self.assertEqual(bridge.read_webbox(self.box, threading.Event(), maintain), {'power_w': 10})
        self.assertTrue(checks)
        self.box.read.assert_called_once()


if __name__ == '__main__':
    unittest.main()
