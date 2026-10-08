import argparse
import socket
import ssl
import unittest
from unittest.mock import patch, MagicMock
from netmon.services import check_service, validate_services
from netmon.__main__ import main, SERVICE_FIELDS


class ServiceTests(unittest.TestCase):
    def test_valid_targets(self):
        validate_services({'google': 'https://www.google.com/'})

    def test_reject_insecure_and_credentials(self):
        for url in ['http://example.com', 'https://user:pass@example.com/', 'https://example.com:444/']:
            with self.assertRaises(ValueError):
                validate_services({'bad': url})

    @patch('netmon.services.socket.getaddrinfo', side_effect=socket.gaierror('DNS unavailable'))
    def test_dns_failure(self, _):
        result = check_service('https://www.google.com/')
        self.assertEqual(result['category'], 'dns_failure')
        self.assertEqual(result['success'], 0)

    @patch('netmon.services.http.client.HTTPSConnection')
    @patch('netmon.services.socket.getaddrinfo', return_value=[('ipv4',)])
    def test_http_success(self, _, factory):
        conn = factory.return_value
        conn.getresponse.return_value.status = 302
        conn.getresponse.return_value.read.return_value = b''
        result = check_service('https://www.youtube.com/watch?v=test')
        self.assertEqual(result['category'], 'ok')
        self.assertEqual(result['http_status'], 302)
        self.assertEqual(result['success'], 1)
        conn.request.assert_called_once()
        self.assertEqual(conn.request.call_args.args[0], 'HEAD')
        conn.close.assert_called_once()

    @patch('netmon.services.http.client.HTTPSConnection')
    @patch('netmon.services.socket.getaddrinfo', return_value=[('ipv4',)])
    def test_http_failure(self, _, factory):
        factory.return_value.getresponse.return_value.status = 503
        result = check_service('https://www.netflix.com/')
        self.assertEqual(result['category'], 'http_failure')
        self.assertEqual(result['success'], 0)

    @patch('netmon.services.http.client.HTTPSConnection')
    @patch('netmon.services.socket.getaddrinfo', return_value=[('ipv4',)])
    def test_tls_failure(self, _, factory):
        factory.return_value.connect.side_effect = ssl.SSLError('TLS failed')
        result = check_service('https://www.google.com/')
        self.assertEqual(result['category'], 'tls_failure')
        self.assertIn('TLS failed', result['detail'])

    def test_csv_columns(self):
        self.assertIn('interface', SERVICE_FIELDS)
        self.assertIn('connection_type', SERVICE_FIELDS)
        self.assertIn('dns_ms', SERVICE_FIELDS)

    def test_cli_bad_target(self):
        with self.assertRaises(SystemExit) as error:
            main(['run', '--service-target', 'invalid'])
        self.assertEqual(error.exception.code, 2)

    def test_cli_bad_url(self):
        with self.assertRaises(SystemExit) as error:
            main(['run', '--service-target', 'test=http://example.com'])
        self.assertEqual(error.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
