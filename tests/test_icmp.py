import subprocess
import unittest
from unittest.mock import patch
from netmon.icmp import parse_rtts, sample


class ICMPTests(unittest.TestCase):
    def test_linux_ping_with_loss(self):
        output = '64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=10.0 ms\n64 bytes from 1.1.1.1: icmp_seq=3 ttl=57 time=14.0 ms\n'
        with patch('netmon.icmp.subprocess.run', return_value=subprocess.CompletedProcess([], 1, output, '')):
            stats, error = sample('1.1.1.1', 4)
        self.assertEqual(error, '')
        self.assertEqual(stats['packet_loss_pct'], 50)
        self.assertEqual(stats['jitter_ms'], 4)
        self.assertEqual(stats['avg_rtt_ms'], 12)

    def test_windows_reply(self):
        self.assertEqual(parse_rtts('Reply from 1.1.1.1: bytes=32 time<1ms TTL=57\nReply from 1.1.1.1: bytes=32 time=20ms TTL=57'), [0.5, 20.0])

    def test_ping_unavailable(self):
        with patch('netmon.icmp.subprocess.run', side_effect=FileNotFoundError('ping')):
            stats, error = sample('1.1.1.1')
        self.assertIsNone(stats)
        self.assertIn('FileNotFoundError', error)

    def test_complete_loss(self):
        with patch('netmon.icmp.subprocess.run', return_value=subprocess.CompletedProcess([], 1, '4 packets transmitted, 0 received', '')):
            stats, error = sample('1.1.1.1')
        self.assertEqual(error, '')
        self.assertEqual(stats['packet_loss_pct'], 100)
        self.assertEqual(stats['jitter_ms'], '')


if __name__ == '__main__':
    unittest.main()
