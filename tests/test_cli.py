"""CLI regression tests, including the --icmp flag."""
import contextlib
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from netmon.__main__ import ICMP_FIELDS, main, monitor


class CLITests(unittest.TestCase):
    def test_logs_icmp_flag_reads_correct_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'icmp.csv'
            path.write_text('timestamp_utc,packet_loss_pct,jitter_ms\n2026-01-01,25,3.5\n', encoding='utf-8')
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(['logs', '--icmp', '--data-dir', directory])
            self.assertEqual(result, 0)
            self.assertIn('25,3.5', output.getvalue())

    def test_logs_missing_icmp_csv_reports_error(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with contextlib.redirect_stderr(output):
                result = main(['logs', '--icmp', '--follow', '--data-dir', directory])
            self.assertEqual(result, 1)
            self.assertIn('icmp.csv', output.getvalue())

    def test_start_passes_icmp_options_to_background(self):
        with tempfile.TemporaryDirectory() as directory:
            class FakeProcess:
                pid = 424242
            with patch('netmon.__main__.subprocess.Popen', return_value=FakeProcess()) as spawn:
                with contextlib.redirect_stdout(io.StringIO()):
                    result = main(['start', '--data-dir', directory, '--icmp-count', '7', '--icmp-interval', '90'])
            self.assertEqual(result, 0)
            command = spawn.call_args.args[0]
            self.assertEqual(command[command.index('--icmp-count') + 1], '7')
            self.assertEqual(command[command.index('--icmp-interval') + 1], '90.0')

    def test_monitor_writes_evidence_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            class StopAfterOneSample(Exception):
                pass
            def fake_sleep(_):
                raise KeyboardInterrupt
            with patch('netmon.__main__.detect', return_value=__import__('netmon.network', fromlist=['Network']).Network('eth0', 'ethernet', '192.168.1.1', 'test')), \
                 patch('netmon.__main__.check_targets', return_value={'192.168.1.1': (True, 1.0, ''), '1.1.1.1': (True, 10.0, ''), '8.8.8.8': (True, 11.0, '')}), \
                 patch('netmon.__main__.probe', return_value=(True, 12.5, '')), \
                 patch('netmon.__main__.icmp_sample', return_value=({'sent': 4, 'received': 3, 'packet_loss_pct': 25.0, 'avg_rtt_ms': 10.0, 'min_rtt_ms': 8.0, 'max_rtt_ms': 12.0, 'jitter_ms': 2.0}, '')), \
                 patch('netmon.__main__.time.sleep', side_effect=fake_sleep):
                with contextlib.redirect_stdout(io.StringIO()):
                    result = main(['run', '--data-dir', directory, '--speed-interval', '0'])
            self.assertEqual(result, 0)
            with (Path(directory) / 'evidence.csv').open(newline='', encoding='utf-8') as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0]['connection_type'], 'ethernet')
            self.assertEqual(rows[0]['target'], '192.168.1.1')

    def test_invalid_icmp_count(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                main(['start', '--icmp-count', '0'])
        self.assertEqual(error.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
