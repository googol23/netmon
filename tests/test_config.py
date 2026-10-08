"""YAML configuration regression tests."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from netmon.__main__ import main

class ConfigTests(unittest.TestCase):
    def test_yaml_values_pass_to_background_process(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = Path(folder) / 'config.yaml'
            cfg.write_text('icmp_interval: 17\nicmp_count: 6\ninterval: 2\n')
            with patch('netmon.__main__.subprocess.Popen') as spawn, contextlib.redirect_stdout(io.StringIO()):
                spawn.return_value.pid = 123456
                self.assertEqual(main(['start', '--config', str(cfg), '--data-dir', folder]), 0)
            command = spawn.call_args.args[0]
            self.assertEqual(command[command.index('--icmp-count') + 1], '6')
            self.assertEqual(command[command.index('--icmp-interval') + 1], '17')
            self.assertEqual(command[command.index('--interval') + 1], '2')

    def test_cli_overrides_yaml(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = Path(folder) / 'config.yaml'
            cfg.write_text('icmp_count: 6\n')
            with patch('netmon.__main__.subprocess.Popen') as spawn, contextlib.redirect_stdout(io.StringIO()):
                spawn.return_value.pid = 123456
                self.assertEqual(main(['start', '--config', str(cfg), '--icmp-count', '9', '--data-dir', folder]), 0)
            command = spawn.call_args.args[0]
            self.assertEqual(command[command.index('--icmp-count') + 1], '9')

    def test_invalid_config_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = Path(folder) / 'config.yaml'
            cfg.write_text('icmp_count: abc\n')
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(['start', '--config', str(cfg)])
            self.assertEqual(error.exception.code, 2)

    def test_unknown_config_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = Path(folder) / 'config.yaml'
            cfg.write_text('unknown_option: 4\n')
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(['run', '--config', str(cfg)])
            self.assertEqual(error.exception.code, 2)
