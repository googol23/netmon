"""Best-effort default-route/interface discovery, including Windows host from WSL2."""
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Network:
    interface: str = 'unknown'
    connection_type: str = 'unknown'
    gateway: str = ''
    source: str = 'unknown'


def _run(command):
    return subprocess.run(command, capture_output=True, text=True, timeout=5, check=True).stdout.strip()


def _windows():
    # Windows host metadata is preferred under WSL2; eth0 inside WSL2 is virtual.
    executable = shutil.which('powershell.exe') if _wsl() else 'powershell.exe'
    if not executable:
        return None
    script = ("$r=Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop | "
              "Where-Object {$_.NextHop -ne '0.0.0.0'} | Sort-Object RouteMetric,InterfaceMetric | Select-Object -First 1; "
              "if($r){$a=Get-NetAdapter -InterfaceIndex $r.InterfaceIndex -ErrorAction Stop; "
              "[pscustomobject]@{name=$a.Name; description=$a.InterfaceDescription; gateway=$r.NextHop} | ConvertTo-Json -Compress}")
    raw = _run([executable, '-NoProfile', '-NonInteractive', '-Command', script])
    if not raw:
        return None
    obj = json.loads(raw)
    name = str(obj.get('name') or 'unknown')
    desc = str(obj.get('description') or '')
    combined = f'{name} {desc}'.lower()
    kind = 'wifi' if re.search(r'wi-?fi|wireless|802\.11|wlan', combined) else ('ethernet' if re.search(r'ethernet|802\.3|lan', combined) else 'unknown')
    return Network(name, kind, str(obj.get('gateway') or ''), 'windows-host' if _wsl() else 'windows')


def _wsl():
    if sys.platform != 'linux':
        return False
    try:
        with open('/proc/sys/kernel/osrelease', encoding='utf-8') as handle:
            return 'microsoft' in handle.read().lower()
    except OSError:
        return False


def _linux():
    raw = _run(['ip', '-4', 'route', 'show', 'default'])
    line = next((line for line in raw.splitlines() if line.startswith('default ')), '')
    parts = line.split()
    if not parts:
        return None
    interface = parts[parts.index('dev') + 1] if 'dev' in parts else 'unknown'
    gateway = parts[parts.index('via') + 1] if 'via' in parts else ''
    wifi = os.path.exists('/sys/class/net/' + interface + '/wireless') or interface.startswith(('wl', 'wlan'))
    kind = 'wifi' if wifi else ('ethernet' if interface.startswith(('en', 'eth')) else 'unknown')
    return Network(interface, kind, gateway, 'linux')


def detect():
    try:
        if sys.platform == 'win32' or _wsl():
            return _windows() or Network(source='wsl-host-unavailable' if _wsl() else 'windows-unavailable')
        if sys.platform == 'linux':
            return _linux() or Network()
        if sys.platform == 'darwin':
            raw = _run(['route', '-n', 'get', 'default'])
            match = re.search(r'interface:\s*(\S+)', raw)
            gateway = re.search(r'gateway:\s*(\S+)', raw)
            interface = match.group(1) if match else 'unknown'
            airport = _run(['networksetup', '-listallhardwareports'])
            # Map the default route interface to the hardware-port description.
            blocks = airport.split('\n\n')
            wifi = any(('Wi-Fi' in block or 'AirPort' in block) and f'Device: {interface}' in block for block in blocks)
            return Network(interface, 'wifi' if wifi else ('ethernet' if interface.startswith('en') else 'unknown'), gateway.group(1) if gateway else '', 'macos')
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, json.JSONDecodeError):
        pass
    return Network()
