import csv
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi.testclient import TestClient
from netmon.dashboard.app import create_app
from netmon.dashboard.readers import read_rows, snapshot
from netmon.__main__ import main

NOW = datetime(2026, 10, 8, 18, 0, tzinfo=timezone.utc)

class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client = TestClient(create_app(self.root))

    def write(self, name, rows):
        with (self.root / name).open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def evidence(self, seconds=0, success='1', classification='healthy'):
        return dict(timestamp_utc=(NOW-timedelta(seconds=seconds)).isoformat(), target='1.1.1.1',
                    gateway='192.168.1.1', interface='wlan0', connection_type='wifi',
                    success=success, rtt_ms='21.5', packet_loss_pct_rolling='0', classification=classification)

    def test_no_data(self):
        data = snapshot(self.root, now=NOW)
        self.assertEqual(data['condition'], 'no_data')
        self.assertEqual(data['targets'], {})

    def test_live_and_stale(self):
        self.write('evidence.csv', [self.evidence()])
        self.assertEqual(snapshot(self.root, now=NOW)['condition'], 'healthy')
        self.assertEqual(snapshot(self.root, now=NOW+timedelta(seconds=16))['condition'], 'monitor_stopped_or_stale')

    def test_outage(self):
        self.write('evidence.csv', [self.evidence(classification='internet_down', success='0')])
        self.assertEqual(snapshot(self.root, now=NOW)['condition'], 'outage')

    def test_time_filter_and_limit(self):
        self.write('evidence.csv', [self.evidence(seconds=7200), self.evidence(seconds=20), self.evidence()])
        rows = read_rows(self.root, 'evidence', hours=1, limit=1, now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['timestamp_utc'], NOW.isoformat())

    def test_malformed_timestamps_ignored(self):
        row = self.evidence();row['timestamp_utc'] = 'invalid'
        self.write('evidence.csv', [row])
        self.assertEqual(read_rows(self.root, 'evidence', now=NOW), [])

    def test_api_root_and_assets(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertIn('NetMon', self.client.get('/').text)
        self.assertEqual(self.client.get('/static/app.js').status_code, 200)
        self.assertEqual(self.client.get('/static/../../config.yaml').status_code, 404)

    def test_summary_api_no_data(self):
        r = self.client.get('/api/summary')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['freshness'], 'no_data')

    def test_history_api(self):
        self.write('evidence.csv', [self.evidence()])
        r = self.client.get('/api/history/evidence?hours=720&limit=10')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['kind'], 'evidence')

    def test_history_validation(self):
        self.assertEqual(self.client.get('/api/history/unknown').status_code, 404)
        self.assertEqual(self.client.get('/api/history/evidence?hours=721').status_code, 422)
        self.assertEqual(self.client.get('/api/history/evidence?limit=3001').status_code, 422)

    def test_download_whitelist_and_missing(self):
        self.assertEqual(self.client.get('/api/download/unknown').status_code, 404)
        self.assertEqual(self.client.get('/api/download/evidence').status_code, 404)
        self.write('evidence.csv', [self.evidence()])
        r=self.client.get('/api/download/evidence')
        self.assertEqual(r.status_code, 200)
        self.assertIn('timestamp_utc', r.text)
        self.assertIn('attachment', r.headers['content-disposition'])

    def test_cli_rejects_non_loopback(self):
        with self.assertRaises(SystemExit) as ctx:
            main(['dashboard', '--host', '0.0.0.0'])
        self.assertEqual(ctx.exception.code, 2)

    def test_cli_rejects_bad_port(self):
        with self.assertRaises(SystemExit):
            main(['dashboard', '--port', '0'])

if __name__ == '__main__': unittest.main()
