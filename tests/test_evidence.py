import unittest
from unittest.mock import patch
from netmon.evidence import Window, classify, OutageTracker, check_targets
from netmon.network import Network, detect


class EvidenceTests(unittest.TestCase):
    def test_rolling_loss_and_jitter(self):
        w = Window(3)
        for ok, rtt in [(True, 10), (False, ''), (True, 16), (True, 20)]:
            w.add(ok, rtt)
        self.assertEqual(w.stats()['packet_loss_pct'], 33.33)
        self.assertEqual(w.stats()['jitter_ms'], 4)

    def test_classification(self):
        self.assertEqual(classify(True, [False, False]), 'suspected_upstream_failure')
        self.assertEqual(classify(False, [False, False]), 'local_or_router_failure')
        self.assertEqual(classify(True, [False, True]), 'partial_external_failure')
        self.assertEqual(classify(True, [True, True]), 'online')
        self.assertEqual(classify(None, [False, False]), 'measurement_error')

    def test_outage_duration(self):
        tracker = OutageTracker()
        self.assertIsNone(tracker.update('suspected_upstream_failure', 'start', 10))
        self.assertIsNone(tracker.update('suspected_upstream_failure', 'during', 11))
        result = tracker.update('online', 'end', 12.5)
        self.assertEqual(result['duration_seconds'], 2.5)
        self.assertEqual(result['start_utc'], 'start')
        self.assertEqual(result['end_utc'], 'end')

    def test_no_false_loss_on_command_failure(self):
        with patch('netmon.evidence.sample', return_value=(None, 'ping missing')):
            results = check_targets(['1.1.1.1'], 1)
        self.assertIsNone(results['1.1.1.1'][0])

    def test_network_detection_fallback(self):
        with patch('netmon.network.sys.platform', 'linux'), patch('netmon.network._wsl', return_value=False), patch('netmon.network._run', side_effect=OSError):
            self.assertEqual(detect().connection_type, 'unknown')

    def test_wsl_host_detection(self):
        with patch('netmon.network.sys.platform', 'linux'), patch('netmon.network._wsl', return_value=True), patch('netmon.network.shutil.which', return_value='/mnt/c/powershell.exe'), patch('netmon.network._run', return_value='{"name":"Wi-Fi","description":"Intel Wireless","gateway":"192.168.1.1"}'):
            network = detect()
        self.assertEqual(network.connection_type, 'wifi')
        self.assertEqual(network.gateway, '192.168.1.1')
        self.assertEqual(network.source, 'windows-host')


if __name__ == '__main__':
    unittest.main()
