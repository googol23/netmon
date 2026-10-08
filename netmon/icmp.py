"""ICMP echo sampling using the operating system ping executable."""

import re
import subprocess
import sys

# Parse per-reply RTTs, not summary statistics (which vary across platforms).
RTT = re.compile(r'\btime\s*([=<])\s*(\d+(?:[.,]\d+)?)\s*ms\b', re.IGNORECASE)


def parse_rtts(output):
    values = []
    for line in output.splitlines():
        match = RTT.search(line)
        if match:
            value = float(match.group(2).replace(',', '.'))
            values.append(value / 2 if match.group(1) == '<' else value)
    return values


def sample(host, count=4, timeout=3):
    """Return (statistics, error). Unanswered echoes count as lost.

    Jitter is mean absolute delta of adjacent successful RTT samples, not RFC3550 jitter.
    """
    if sys.platform == 'win32':
        command = ['ping', '-n', str(count), '-w', str(int(timeout * 1000)), host]
    else:
        command = ['ping', '-n', '-c', str(count), host]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                errors='replace', timeout=count * timeout + 5,
                                check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f'{type(exc).__name__}: {exc}'
    rtts = parse_rtts(result.stdout + '\n' + result.stderr)
    received = min(len(rtts), count)
    if not received and result.returncode not in (0, 1):
        return None, f'ping failed (exit {result.returncode}): {(result.stderr or result.stdout).strip()[:200]}'
    return {
        'sent': count, 'received': received,
        'packet_loss_pct': round(100 * (count - received) / count, 2),
        'avg_rtt_ms': round(sum(rtts) / received, 2) if received else '',
        'min_rtt_ms': round(min(rtts), 2) if received else '',
        'max_rtt_ms': round(max(rtts), 2) if received else '',
        'jitter_ms': round(sum(abs(b-a) for a, b in zip(rtts, rtts[1:])) / (received - 1), 2) if received > 1 else '',
    }, ''
