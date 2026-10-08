"""Checks that setup scripts enforce the supported Python baseline."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SetupTests(unittest.TestCase):
    def test_unix_setup_syntax(self):
        subprocess.run(['bash', '-n', str(ROOT / 'scripts/setup.sh')], check=True)

    def test_unix_setup_uses_python_313_and_checks_version(self):
        script = (ROOT / 'scripts/setup.sh').read_text()
        self.assertIn('uv python install 3.13', script)
        self.assertIn('uv venv --clear --python', script)
        self.assertIn('sys.version_info >= (3, 13)', script)

    def test_windows_setup_uses_python_313_and_checks_version(self):
        script = (ROOT / 'scripts/setup.ps1').read_text()
        self.assertIn('uv python install 3.13', script)
        self.assertIn('uv venv --clear --python', script)
        self.assertIn('sys.version_info >= (3, 13)', script)


if __name__ == '__main__':
    unittest.main()
