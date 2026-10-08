import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from .services import check_service, validate_services, SERVICE_FIELDS
from .icmp import sample as icmp_sample
from .network import detect
from .evidence import Window, check_targets, classify, OutageTracker

VERSION = '0.7.0'
DEFAULT_DIR = Path.home() / '.netmon'
ICMP_FIELDS = ['timestamp_utc', 'target', 'sent', 'received', 'packet_loss_pct', 'avg_rtt_ms', 'min_rtt_ms', 'max_rtt_ms', 'jitter_ms', 'detail']
FIELDS = ['timestamp_utc', 'kind', 'target', 'success', 'latency_ms', 'download_mbps', 'upload_mbps', 'detail']
EVIDENCE_FIELDS = ['timestamp_utc', 'interface', 'connection_type', 'interface_source', 'gateway', 'target', 'success', 'rtt_ms', 'packet_loss_pct_rolling', 'avg_rtt_ms_rolling', 'jitter_ms_rolling', 'classification', 'detail']
OUTAGE_FIELDS = ['start_utc', 'end_utc', 'duration_seconds', 'classification', 'interface', 'connection_type']
SPEED_FIELDS = ['timestamp_utc', 'interface', 'connection_type', 'download_mbps', 'upload_mbps', 'detail']


# CLI flags take precedence over YAML; absent keys retain previous defaults.
CONFIG_DEFAULTS = {
    'host': '1.1.1.1', 'port': 443, 'interval': 10.0, 'timeout': 3.0,
    'speed_interval': 1800.0, 'icmp_host': '1.1.1.1',
    'icmp_interval': 60.0, 'icmp_count': 4,
    'evidence_interval': 1.0, 'loss_window': 60, 'router': 'auto',
    'external_targets': ['1.1.1.1', '8.8.8.8'],
    'services_enabled': True, 'services_interval': 10.0, 'services_timeout': 5.0,
    'services_targets': {'netflix': 'https://www.netflix.com/', 'youtube': 'https://www.youtube.com/', 'google': 'https://www.google.com/'},
}
CONFIG_TYPES = {
    'host': str, 'port': int, 'interval': float, 'timeout': float,
    'speed_interval': float, 'icmp_host': str, 'icmp_interval': float,
    'icmp_count': int, 'evidence_interval': float, 'loss_window': int,
    'router': str, 'external_targets': list, 'services_enabled': bool,
    'services_interval': float, 'services_timeout': float, 'services_targets': dict,
}

def apply_config(args, parser):
    if args.config:
        import yaml
        try:
            with Path(args.config).expanduser().open(encoding='utf-8') as handle:
                config = yaml.safe_load(handle)
        except (OSError, yaml.YAMLError) as exc:
            parser.error(f'Cannot read config: {exc}')
        if config is None:
            config = {}
        if not isinstance(config, dict):
            parser.error('Config must be a YAML mapping')
        unknown = set(config) - set(CONFIG_DEFAULTS)
        if unknown:
            parser.error(f'Unknown config keys: {", ".join(sorted(map(str, unknown)))}')
    else:
        config = {}
    for key, default in CONFIG_DEFAULTS.items():
        value = getattr(args, key)
        if value is None:
            value = config.get(key, default)
        expected = CONFIG_TYPES[key]
        if ((expected is str and (not isinstance(value, str) or not value.strip()))
                or (expected is int and type(value) is not int)
                or (expected is float and type(value) not in (int, float))
                or (expected is list and not isinstance(value, list))
                or (expected is bool and type(value) is not bool)
                or (expected is dict and not isinstance(value, dict))):
            parser.error(f'Invalid config value for {key}: expected {expected.__name__}')
        if key == 'external_targets' and (not value or not all(isinstance(x, str) and x.strip() for x in value) or len(value) > 5):
            parser.error('external_targets must contain 1-5 nonempty hosts')
        if key == 'services_targets':
            try:
                validate_services(value)
            except ValueError as exc:
                parser.error(str(exc))
        setattr(args, key, value)


def probe(host, port, timeout):
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, round((time.perf_counter() - started) * 1000, 2), ''
    except OSError as exc:
        return False, '', str(exc)


def append_csv(path, row, fields=FIELDS):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        if file.tell() == 0:
            writer.writeheader()
        writer.writerow(row)


def speed_test():
    try:
        import speedtest
        client = speedtest.Speedtest(secure=True)
        client.get_best_server()
        down = round(client.download() / 1_000_000, 2)
        up = round(client.upload(pre_allocate=False) / 1_000_000, 2)
        return down, up, ''
    except Exception as exc:
        return '', '', f'{type(exc).__name__}: {exc}'


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def monitor(args):
    directory = Path(args.data_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    windows = {}
    outage = OutageTracker()
    next_tcp = next_icmp = next_speed = next_network = 0.0
    background = ThreadPoolExecutor(max_workers=5)
    next_services = 0.0
    service_futures = {}
    icmp_future = speed_future = None
    network = detect()
    print(f'Monitoring network; CSV directory: {directory}', flush=True)
    try:
        while True:
            started = time.monotonic()
            if started >= next_network:
                network = detect()
                next_network = started + 10
            gateway = network.gateway if args.router == 'auto' else args.router
            targets = list(dict.fromkeys(([gateway] if gateway else []) + args.external_targets))
            if targets:
                results = check_targets(targets, args.timeout)
                router_ok = results[gateway][0] if gateway else None
                external_states = [results[t][0] for t in args.external_targets]
                classification = classify(router_ok, external_states)
                if not gateway:
                    classification = 'measurement_error'
                completed = outage.update(classification, timestamp(), time.monotonic())
                if completed:
                    append_csv(directory / 'outages.csv', dict(completed, interface=network.interface, connection_type=network.connection_type), OUTAGE_FIELDS)
                for target in targets:
                    ok, rtt, error = results[target]
                    window = windows.setdefault(target, Window(args.loss_window))
                    if ok is not None:
                        window.add(ok, rtt)
                    row = dict(timestamp_utc=timestamp(), interface=network.interface,
                               connection_type=network.connection_type, interface_source=network.source,
                               gateway=gateway, target=target, success='' if ok is None else int(ok),
                               rtt_ms=rtt, classification=classification, detail=error,
                               **{k + '_rolling': v for k, v in window.stats().items()})
                    append_csv(directory / 'evidence.csv', row, EVIDENCE_FIELDS)
                    if args.verbose:
                        print(row, flush=True)
            now = time.monotonic()
            for name, (future, url, iface, kind) in list(service_futures.items()):
                if future.done():
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = dict(dns_ms='', https_ms='', http_status='', success=0,
                                      category='measurement_error', detail=f'{type(exc).__name__}: {exc}')
                    append_csv(directory / 'services.csv', dict(timestamp_utc=timestamp(),
                               service=name, url=url, interface=iface, connection_type=kind,
                               **result), SERVICE_FIELDS)
                    if args.verbose:
                        print(f'service {name}: {result}', flush=True)
                    del service_futures[name]
            if args.services_enabled and now >= next_services:
                for name, url in args.services_targets.items():
                    if name not in service_futures:
                        service_futures[name] = (background.submit(check_service, url, args.services_timeout),
                                                 url, network.interface, network.connection_type)
                next_services = now + args.services_interval
            if now >= next_tcp:
                ok, latency, error = probe(args.host, args.port, args.timeout)
                row = dict(timestamp_utc=timestamp(), kind='connectivity', target=f'{args.host}:{args.port}', success=int(ok), latency_ms=latency, download_mbps='', upload_mbps='', detail=error)
                append_csv(directory / 'measurements.csv', row)
                next_tcp = now + args.interval
            if icmp_future is not None and icmp_future.done():
                try:
                    stats, error = icmp_future.result()
                except Exception as exc:
                    stats, error = None, f'{type(exc).__name__}: {exc}'
                row = dict(timestamp_utc=timestamp(), target=args.icmp_host,
                           **(stats or dict(sent=args.icmp_count, received='', packet_loss_pct='', avg_rtt_ms='', min_rtt_ms='', max_rtt_ms='', jitter_ms='')),
                           detail=error)
                append_csv(directory / 'icmp.csv', row, ICMP_FIELDS)
                icmp_future = None
            if args.icmp_interval > 0 and now >= next_icmp and icmp_future is None:
                icmp_future = background.submit(icmp_sample, args.icmp_host, args.icmp_count, args.timeout)
                next_icmp = now + args.icmp_interval
            if speed_future is not None and speed_future.done():
                try:
                    down, up, error = speed_future.result()
                except Exception as exc:
                    down, up, error = '', '', f'{type(exc).__name__}: {exc}'
                row = dict(timestamp_utc=timestamp(), kind='speed', target='speedtest', success=int(not error), latency_ms='', download_mbps=down, upload_mbps=up, detail=error)
                append_csv(directory / 'measurements.csv', row)
                append_csv(directory / 'speed.csv', dict(timestamp_utc=row['timestamp_utc'], interface=network.interface, connection_type=network.connection_type, download_mbps=down, upload_mbps=up, detail=error), SPEED_FIELDS)
                speed_future = None
            if args.speed_interval > 0 and now >= next_speed and speed_future is None:
                speed_future = background.submit(speed_test)
                next_speed = now + args.speed_interval
            time.sleep(max(0, args.evidence_interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        return 0
    finally:
        background.shutdown(wait=False)


def start(args):
    directory = Path(args.data_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    pidfile = directory / 'netmon.pid'
    if running_pid(pidfile):
        print('Monitor already running', file=sys.stderr)
        return 1
    command = [sys.executable, '-m', 'netmon', 'run', '--data-dir', str(directory), '--host', args.host, '--port', str(args.port), '--interval', str(args.interval), '--timeout', str(args.timeout), '--speed-interval', str(args.speed_interval), '--icmp-host', args.icmp_host, '--icmp-interval', str(args.icmp_interval), '--icmp-count', str(args.icmp_count), '--evidence-interval', str(args.evidence_interval), '--loss-window', str(args.loss_window), '--router', args.router, '--services-interval', str(args.services_interval),
               '--services-timeout', str(args.services_timeout)]
    if not args.services_enabled:
        command.append('--no-services')
    for name, url in args.services_targets.items():
        command.extend(['--service-target', f'{name}={url}'])
    for host in args.external_targets:
        command.extend(['--external-target', host])
    if args.verbose:
        command.append('--verbose')
    output = (directory / 'terminal.log').open('a', encoding='utf-8')
    kwargs = {'stdin': subprocess.DEVNULL, 'stdout': output, 'stderr': subprocess.STDOUT, 'cwd': str(Path(__file__).resolve().parent.parent)}
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs['start_new_session'] = True
    try:
        process = subprocess.Popen(command, **kwargs)
    finally:
        output.close()
    pidfile.write_text(str(process.pid), encoding='utf-8')
    print(f'Started PID {process.pid}. CSV: {directory / "measurements.csv"}')
    return 0


def running_pid(pidfile):
    try:
        pid = int(pidfile.read_text().strip())
        if os.name == 'nt':
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return pid
            return None
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def status(args):
    pid = running_pid(Path(args.data_dir).expanduser() / 'netmon.pid')
    print(f'Running (PID {pid})' if pid else 'Not running')
    return 0 if pid else 1


def stop(args):
    pidfile = Path(args.data_dir).expanduser() / 'netmon.pid'
    pid = running_pid(pidfile)
    if not pid:
        print('Not running')
        return 1
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(pid), '/F'], check=True)
    else:
        os.kill(pid, signal.SIGTERM)
    pidfile.unlink(missing_ok=True)
    print(f'Stopped PID {pid}')
    return 0


def logs(args):
    path = Path(args.data_dir).expanduser() / ('terminal.log' if args.terminal else 'icmp.csv' if args.icmp else 'evidence.csv' if args.evidence else 'outages.csv' if args.outages else 'speed.csv' if args.speed else 'services.csv' if args.services else 'measurements.csv')
    if not path.exists():
        print(f'No log yet: {path}', file=sys.stderr)
        return 1
    with path.open(encoding='utf-8') as file:
        if args.follow:
            print(file.read(), end='', flush=True)
            try:
                while True:
                    chunk = file.read()
                    if chunk:
                        print(chunk, end='', flush=True)
                    time.sleep(1)
            except KeyboardInterrupt:
                return 0
        else:
            from collections import deque
            print(''.join(deque(file, maxlen=args.lines)), end='')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Minimal CSV internet monitor')
    parser.add_argument('--version', action='version', version=f'netmon {VERSION}')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('start', 'run', 'status', 'stop', 'logs', 'dashboard'):
        command = sub.add_parser(name)
        command.add_argument('--data-dir', default=str(DEFAULT_DIR))
        if name == 'dashboard':
            command.add_argument('--host', default='127.0.0.1')
            command.add_argument('--port', type=int, default=8080)
        if name in ('start', 'run'):
            command.add_argument('--config', help='Path to YAML configuration file')
            command.add_argument('--host')
            command.add_argument('--port', type=int, default=None)
            command.add_argument('--interval', type=float, default=None)
            command.add_argument('--timeout', type=float, default=None)
            command.add_argument('--speed-interval', type=float, default=None, help='Seconds; 0 disables speed tests')
            command.add_argument('--icmp-host', default=None)
            command.add_argument('--icmp-interval', type=float, default=None, help='Seconds; 0 disables ICMP')
            command.add_argument('--icmp-count', type=int, default=None)
            command.add_argument('--evidence-interval', type=float, default=None)
            command.add_argument('--loss-window', type=int, default=None)
            command.add_argument('--router', default=None)
            command.add_argument('--external-target', action='append', dest='external_targets', default=None)
            command.add_argument('--services-interval', type=float, default=None)
            command.add_argument('--services-timeout', type=float, default=None)
            command.add_argument('--no-services', action='store_true')
            command.add_argument('--service-target', action='append', default=None, metavar='NAME=HTTPS_URL')
            command.add_argument('--verbose', action='store_true')
        if name == 'logs':
            command.add_argument('--follow', '-f', action='store_true')
            command.add_argument('--terminal', action='store_true')
            command.add_argument('--icmp', action='store_true', help='Show ICMP CSV instead')
            command.add_argument('--evidence', action='store_true')
            command.add_argument('--outages', action='store_true')
            command.add_argument('--speed', action='store_true')
            command.add_argument('--services', action='store_true')
            command.add_argument('--lines', type=int, default=30)
    args = parser.parse_args(argv)
    if args.command in ('start', 'run'):
        # Convert optional CLI service targets before applying YAML precedence.
        if args.service_target is not None:
            entries = {}
            for item in args.service_target:
                if '=' not in item:
                    parser.error('--service-target must be NAME=HTTPS_URL')
                name, url = item.split('=', 1)
                entries[name] = url
            args.services_targets = entries
        else:
            args.services_targets = None
        args.services_enabled = False if args.no_services else None
        apply_config(args, parser)
    if args.command in ('start', 'run') and (args.interval <= 0 or args.timeout <= 0 or args.speed_interval < 0 or args.icmp_interval < 0 or args.icmp_count < 1 or args.evidence_interval <= 0 or args.loss_window < 2 or args.services_interval <= 0 or args.services_timeout <= 0 or not 1 <= args.port <= 65535):
        parser.error('interval and timeout must be positive, speed/ICMP intervals nonnegative, ICMP count positive, and port valid')
    if args.command == 'logs' and args.lines < 1:
        parser.error('--lines must be positive')
    if args.command == 'dashboard':
        if not 1 <= args.port <= 65535:
            parser.error('dashboard port must be between 1 and 65535')
        if args.host not in ('127.0.0.1', 'localhost', '::1'):
            parser.error('dashboard only supports loopback hosts; remote access requires a secure reverse proxy')
        from .dashboard.app import serve
        return serve(args.data_dir, args.host, args.port)
    return {'start': start, 'run': monitor, 'status': status, 'stop': stop, 'logs': logs}[args.command](args)


if __name__ == '__main__':
    sys.exit(main())
