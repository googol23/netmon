import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from netmon.__main__ import append_csv, probe

class MonitorTests(unittest.TestCase):
    def test_csv_header_written_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'samples.csv'
            row = dict(timestamp_utc='now', kind='connectivity', target='host', success=1, latency_ms=1, download_mbps='', upload_mbps='', detail='')
            append_csv(path, row)
            append_csv(path, row)
            with path.open(newline='') as file:
                records = list(csv.DictReader(file))
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]['kind'], 'connectivity')

    def test_probe_failure(self):
        with patch('netmon.__main__.socket.create_connection', side_effect=OSError('offline')):
            ok, latency, error = probe('example.com', 443, 1)
        self.assertFalse(ok)
        self.assertEqual(latency, '')
        self.assertIn('offline', error)

if __name__ == '__main__':
    unittest.main()
