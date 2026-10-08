"""Bounded, read-only CSV queries. No changes to the monitoring engine or logs."""
import csv
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path

FILES = {'evidence': 'evidence.csv', 'outages': 'outages.csv', 'speed': 'speed.csv',
         'services': 'services.csv', 'measurements': 'measurements.csv', 'icmp': 'icmp.csv'}
MAX_ROWS = 3000

def parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None

def read_rows(data_dir, kind, hours=24, limit=600, now=None):
    if kind not in FILES:
        raise ValueError('Unknown log type')
    if not 1 <= hours <= 720 or not 1 <= limit <= MAX_ROWS:
        raise ValueError('Invalid time range or limit')
    path = Path(data_dir) / FILES[kind]
    if not path.is_file():
        return []
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=hours)
    rows = deque(maxlen=limit)
    try:
        with path.open('r', encoding='utf-8', newline='') as stream:
            for row in csv.DictReader(stream):
                stamp = parse_time(row.get('timestamp_utc') or row.get('end_utc') or row.get('start_utc'))
                if stamp is not None and stamp >= cutoff:
                    rows.append(row)
    except (OSError, UnicodeError, csv.Error):
        return list(rows)
    return list(rows)

def number(value):
    try:
        return float(value) if value not in ('', None) else None
    except (ValueError, TypeError):
        return None

def latest_by(rows, key):
    result = {}
    for row in rows:
        if row.get(key):
            result[row[key]] = row
    return result

def snapshot(data_dir, now=None):
    now = now or datetime.now(timezone.utc)
    evidence = read_rows(data_dir, 'evidence', hours=24, limit=3000, now=now)
    services = read_rows(data_dir, 'services', hours=24, limit=3000, now=now)
    speeds = read_rows(data_dir, 'speed', hours=720, limit=100, now=now)
    outages = read_rows(data_dir, 'outages', hours=720, limit=100, now=now)
    latest_evidence = latest_by(evidence, 'target')
    latest_services = latest_by(services, 'service')
    latest = evidence[-1] if evidence else None
    last_stamp = parse_time(latest.get('timestamp_utc')) if latest else None
    age = (now - last_stamp).total_seconds() if last_stamp else None
    freshness = 'no_data' if age is None else 'stale' if age > 15 else 'live'
    states = [r.get('classification') for r in latest_evidence.values()]
    condition = ('no_data' if freshness == 'no_data' else 'monitor_stopped_or_stale' if freshness == 'stale'
                 else 'outage' if any(x in ('router_down', 'internet_down') for x in states)
                 else 'degraded' if any(x not in ('healthy', '') for x in states) else 'healthy')
    latest_speed = speeds[-1] if speeds else None
    return {
        'updated_utc': now.isoformat(timespec='seconds'), 'freshness': freshness,
        'condition': condition, 'sample_age_seconds': round(age, 1) if age is not None else None,
        'interface': latest.get('interface') if latest else None,
        'connection_type': latest.get('connection_type') if latest else None,
        'gateway': latest.get('gateway') if latest else None,
        'targets': latest_evidence, 'services': latest_services,
        'speed': latest_speed, 'recent_outages': list(reversed(outages[-15:])),
    }
