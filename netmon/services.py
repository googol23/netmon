"""HTTPS service reachability with separately measured DNS, TCP/TLS and HTTP."""
import http.client
import socket
import ssl
import time
from urllib.parse import urlsplit

SERVICE_FIELDS = ['timestamp_utc', 'service', 'url', 'interface', 'connection_type',
                  'dns_ms', 'https_ms', 'http_status', 'success', 'category', 'detail']


def check_service(url, timeout=5):
    """Return DNS/HTTPS timings and a failure category; no streaming QoE inference."""
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError('Service target must be a valid HTTPS URL without credentials or fragment')
    port = parts.port or 443
    start = time.monotonic()
    try:
        addresses = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        return dict(dns_ms='', https_ms='', http_status='', success=0, category='dns_failure', detail=str(exc))
    dns_ms = round((time.monotonic() - start) * 1000, 2)
    if not addresses:
        return dict(dns_ms=dns_ms, https_ms='', http_status='', success=0, category='dns_failure', detail='No DNS addresses')
    conn = http.client.HTTPSConnection(parts.hostname, port, timeout=timeout, context=ssl.create_default_context())
    started = time.monotonic()
    try:
        # HTTPSConnection.connect performs TCP and TLS negotiation.
        conn.connect()
        https_ms = round((time.monotonic() - started) * 1000, 2)
        path = parts.path or '/'
        if parts.query:
            path += '?' + parts.query
        conn.request('HEAD', path, headers={'User-Agent': 'NetMon/0.6.0'})
        response = conn.getresponse()
        status = response.status
        response.read()
        # Redirects and access restrictions still prove HTTPS reachability.
        ok = 200 <= status < 400
        return dict(dns_ms=dns_ms, https_ms=https_ms, http_status=status,
                    success=int(ok), category='ok' if ok else 'http_failure', detail='')
    except (ssl.SSLError, ssl.CertificateError) as exc:
        category, detail = 'tls_failure', str(exc)
    except (socket.timeout, TimeoutError) as exc:
        category, detail = 'timeout', str(exc)
    except (OSError, http.client.HTTPException) as exc:
        category, detail = 'connection_failure', str(exc)
    finally:
        conn.close()
    return dict(dns_ms=dns_ms, https_ms='', http_status='', success=0, category=category, detail=detail)


def validate_services(services):
    if not isinstance(services, dict) or not services or len(services) > 12:
        raise ValueError('services_targets must be a mapping of 1-12 names to HTTPS URLs')
    for name, url in services.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(url, str):
            raise ValueError('Each service requires a name and HTTPS URL')
        parts = urlsplit(url)
        try:
            port = parts.port
        except ValueError as exc:
            raise ValueError(f'Invalid service URL: {name}') from exc
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.fragment or (port is not None and port != 443):
            raise ValueError(f'Invalid service HTTPS URL: {name}')
