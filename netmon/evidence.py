"""Per-second ICMP checks and outage classification."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from .icmp import sample


@dataclass
class Window:
    size: int
    samples: deque = field(default_factory=deque)

    def add(self, success, rtt):
        self.samples.append((success, rtt))
        while len(self.samples) > self.size:
            self.samples.popleft()

    def stats(self):
        values = [rtt for ok, rtt in self.samples if ok and rtt != '']
        count = len(self.samples)
        return {
            'packet_loss_pct': round(100 * (count - sum(ok for ok, _ in self.samples)) / count, 2) if count else '',
            'avg_rtt_ms': round(sum(values) / len(values), 2) if values else '',
            'jitter_ms': round(sum(abs(b - a) for a, b in zip(values, values[1:])) / (len(values) - 1), 2) if len(values) > 1 else '',
        }


def check_targets(targets, timeout):
    """Run independent one-echo probes concurrently to avoid 3s sequential delay."""
    def check(host):
        stats, error = sample(host, count=1, timeout=timeout)
        if error or stats is None:
            return host, None, '', error or 'unknown ping error'
        ok = stats['received'] == 1
        return host, ok, stats['avg_rtt_ms'] if ok else '', ''
    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        return dict((host, (ok, rtt, err)) for host, ok, rtt, err in pool.map(check, targets))


def classify(router_ok, external_states):
    """None means the probe failed operationally: do not call it packet loss."""
    if router_ok is None or any(state is None for state in external_states):
        return 'measurement_error'
    if not all(external_states):
        if router_ok is False:
            return 'local_or_router_failure'
        if not any(external_states):
            return 'suspected_upstream_failure'
        return 'partial_external_failure'
    return 'online' if router_ok else 'router_icmp_unreachable'


@dataclass
class OutageTracker:
    active_start: str = ''
    active_type: str = ''
    active_monotonic: float = 0

    def update(self, status, now_utc, monotonic):
        """Return completed outage, if any. Unknown measurements break continuity."""
        failure = status in ('suspected_upstream_failure', 'local_or_router_failure', 'partial_external_failure')
        if self.active_start and (not failure or status != self.active_type):
            result = {'start_utc': self.active_start, 'end_utc': now_utc,
                      'duration_seconds': round(max(0, monotonic - self.active_monotonic), 2),
                      'classification': self.active_type}
            self.active_start = ''
            self.active_type = ''
            if failure:
                self.active_start, self.active_type, self.active_monotonic = now_utc, status, monotonic
            return result
        if failure and not self.active_start:
            self.active_start, self.active_type, self.active_monotonic = now_utc, status, monotonic
        return None
