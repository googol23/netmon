# NetMon 0.7.0

Minimal cross-platform internet connectivity and speed logger. Python 3.13+.

## Install

The setup scripts use **uv** to select Python 3.13. If Python 3.13 is missing, they install a managed copy automatically; if uv is missing, they bootstrap it from the official Astral installer. Internet access is required for first-time installation. An existing `.venv` is **recreated** (its installed packages are removed). No `sudo` or system Python replacement is required. Review the bootstrap scripts before running them.

Linux / macOS / WSL2:

```bash
bash scripts/setup.sh
.venv/bin/python -m netmon start
```

Windows PowerShell:

```powershell
.\scripts\setup.ps1
.\.venv\Scripts\python.exe -m netmon start
```

## Commands

Replace `python -m netmon` with `.venv/bin/python -m netmon` (Unix) or `.\.venv\Scripts\python.exe -m netmon` (Windows).

```bash
python -m netmon start                       # detached background process
python -m netmon start --verbose             # detailed events to ~/.netmon/terminal.log
python -m netmon run --verbose               # foreground, live terminal output
python -m netmon status
python -m netmon logs --follow               # follow connectivity/speed CSV
python -m netmon logs --icmp --follow        # follow packet loss/jitter CSV
python -m netmon logs --terminal --follow    # follow process output
python -m netmon stop
```

Default CSV: `~/.netmon/measurements.csv` (UTC timestamps). Connectivity probes are TCP connections to `1.1.1.1:443` every 10 seconds; speed tests run every 30 minutes. Customize with `--host`, `--port`, `--interval`, `--timeout`, `--speed-interval` (all intervals in seconds), and `--data-dir`. `--speed-interval 0` disables speed testing. Tests can consume significant bandwidth.

**Limitations:** TCP connection time is not ICMP ping; it measures TCP handshake latency and reachability, not true packet loss or jitter. Failed connection samples can be used to estimate outages. Speed tests use the third-party `speedtest-cli` package and external test servers. The monitor stops when its OS/WSL instance shuts down or sleeps. WSL2 measurements reflect the WSL2 virtual network and may differ from native Windows measurements. PID files can become stale; `stop` uses process IDs, so avoid manually changing the PID file. No auto-start at boot is configured.

## ICMP packet loss and jitter

NetMon also runs **four ICMP echo requests every 60 seconds** to `1.1.1.1` by default.
It writes `~/.netmon/icmp.csv` separately from the existing connectivity/speed CSV.
The columns include sent, received, packet loss percentage, average/min/max RTT,
and jitter (mean absolute difference between consecutive successful RTTs).
Jitter is blank with fewer than two successful replies; loss is 100% if all
four requests time out. An unavailable/broken `ping` command is logged as an
error instead of being misreported as packet loss.

```bash
.venv/bin/python -m netmon start --icmp-host 8.8.8.8 --icmp-count 5 --icmp-interval 60
.venv/bin/python -m netmon logs --icmp --follow
```

Set `--icmp-interval 0` to disable ICMP checks. The OS `ping` command must be
installed and available on PATH (on Debian/Ubuntu/WSL2: `sudo apt install iputils-ping`).
ICMP can be filtered or rate-limited by destinations; measured loss is ICMP
loss, not necessarily loss of application traffic. WSL2 results measure the
WSL2 virtual network path, not the Windows host directly.

## Tests and troubleshooting

Run all tests from the **project root** (the directory containing `netmon/` and `tests/`):

```bash
.venv/bin/python -m unittest discover -s tests -v  # Linux/macOS/WSL2
# Windows PowerShell: .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

If `logs --icmp` says `unrecognized arguments`, you are running an older project
copy or a different `netmon` module. From the **newly extracted** project root:

```bash
.venv/bin/python -m netmon --version
.venv/bin/python -m netmon logs --help
.venv/bin/python -c 'import netmon; print(netmon.__file__)'
```

The version should match the packaged NetMon release, and `logs --help` should list `--icmp`.
Restart an existing monitor after upgrading: stop it from the old project
before starting the new one. Existing CSV files are retained.

Note: the terminal log (`logs --terminal`) only contains per-sample events
when the monitor was started with `--verbose`; it also captures errors.
`logs --icmp` reads the CSV directly regardless of verbosity.

## YAML configuration (v0.4.0)

Edit the included `config.yaml`, then run:

```bash
.venv/bin/python -m netmon start --config config.yaml
.venv/bin/python -m netmon logs --icmp --follow
```

Use `run --config config.yaml` to run in the foreground. Existing CLI flags
override YAML values (for example `--icmp-interval 15`). Missing YAML keys
use the original defaults. A YAML file is optional; `start` without `--config`
continues to work as before. Stop and restart to apply config changes.

Intervals and timeouts are in seconds; setting either test interval to 0
disables that test. Configuration is validated at startup.

## v0.5: ISP evidence monitoring

The original CLI and CSV files are retained. Configure the new settings in
`config.yaml`, then restart the monitor. From WSL2:

```bash
sudo apt-get install -y iputils-ping iproute2
bash scripts/setup.sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m netmon start --config config.yaml
.venv/bin/python -m netmon logs --evidence --follow
.venv/bin/python -m netmon logs --outages
.venv/bin/python -m netmon logs --speed
```

New configuration keys:

| Key | Default | Meaning |
| --- | --- | --- |
| `evidence_interval` | `1` | Seconds between one-echo ICMP rounds |
| `loss_window` | `60` | Most recent valid ICMP samples per target |
| `router` | `auto` | Default gateway, or explicitly set a router IP |
| `external_targets` | `[1.1.1.1, 8.8.8.8]` | External ICMP targets (1–5) |

Each cycle sends one ICMP echo to the router and each external target in parallel.
`evidence.csv` records UTC timestamps, host interface/type, route gateway, target,
reply, RTT, rolling loss/jitter, and diagnostic classification. `outages.csv`
records completed failure periods and their *observed* durations. `speed.csv`
records speed results and the detected connection type. The original
`measurements.csv` and `icmp.csv` are still written.

The host interface is detected from the default route. On WSL2, NetMon tries
Windows PowerShell to identify the **Windows host** Wi-Fi/Ethernet adapter and
its gateway, not WSL's virtual `eth0`. If host detection is unavailable, values
are recorded as `unknown`; supply `router: 192.168.x.x` manually if needed.

Classification is conservative: `suspected_upstream_failure` requires a
reachable router and failures from **all** external targets;
`local_or_router_failure` means the router and an external target failed;
`partial_external_failure` means only some external targets failed.
`measurement_error` is used when the router cannot be identified or a ping
command fails. ICMP may be filtered or rate-limited; these classifications are
not proof of the fault's owner. When the router does not respond to ICMP,
classification may be misleading even if the connection works.

A one-second polling target is **not** a guarantee of 1-second resolution:
OS scheduling, ping subprocess overhead, suspend/resume, and WSL shutdown may
cause gaps. Monitoring stops when the host or WSL instance stops. Background
speed tests and legacy multi-echo tests run in separate threads to reduce gaps,
but active speed tests may affect latency and loss measurements. Do not interpret
missing samples as outages. For ISP disputes, repeat tests on wired Ethernet,
keep original CSV files, and record contracted speeds and test conditions.

To avoid mixing CSV schemas, v0.5 uses new files for evidence, outages, and
speed results. Existing historical CSV files remain unchanged.

## v0.6.0 HTTPS service monitoring

Netflix, YouTube and Google are checked by HTTPS HEAD requests every 10 seconds
(default), independently of the 1-second ICMP evidence checks. DNS lookup
time, TCP+TLS connection time, HTTP status, success and error category are
appended to `~/.netmon/services.csv`. HTTP 2xx and 3xx count as reachable;
4xx/5xx are logged as HTTP failures. A service may intentionally reject HEAD
requests, so HTTP failure does not by itself establish a service outage.
These probes do **not** measure streaming performance or CDN delivery.

Configure `services_enabled`, `services_interval`, `services_timeout`, and
`services_targets` (a name-to-HTTPS-URL mapping) in `config.yaml`. Disable with
`services_enabled: false` or `--no-services`. Override targets with repeated
`--service-target name=https://example.com/` flags. View results with
`python -m netmon logs --services --follow`. Tests:
`python -m unittest discover -s tests -v`.

## Web dashboard (v0.7.0)

NetMon now includes an **optional, read-only local dashboard**. The monitoring daemon and
web server are independent processes. The dashboard reads the existing CSV files; it
never changes or truncates them.

Install the optional dashboard dependencies after running `scripts/setup.sh`:

```bash
.venv/bin/python -m pip install -r requirements-dashboard.txt
# If your venv was created by uv and pip is unavailable:
# uv pip install --python .venv/bin/python -r requirements-dashboard.txt
```

Run the monitor and web dashboard in **separate terminals**:

```bash
.venv/bin/python -m netmon start --config config.yaml
.venv/bin/python -m netmon dashboard --host 127.0.0.1 --port 8080
```

Open **http://localhost:8080** in a browser. On Windows PowerShell use
`.\.venv\Scripts\python.exe` instead of `.venv/bin/python`.
On WSL2, localhost forwarding normally makes this address available in the
Windows browser; if not, check WSL networking configuration.

The dashboard refreshes every three seconds. It offers 1-hour, 24-hour,
7-day and 30-day history, live status and service health, latency charts,
latest speed tests, completed outages and original CSV downloads. A stale
sample is explicitly labeled instead of shown as a healthy connection.

**Security:** The CLI only allows loopback addresses (`127.0.0.1`, `localhost`,
`::1`) for dashboard binding. The HTTP API has no authentication, so do not
publish it directly to the internet. Use a secure authenticated reverse proxy
if remote access is required. CSV history queries are capped at 3,000 rows;
large logs are scanned sequentially and may eventually benefit from a database
or indexed storage. No external CDN, frontend build tool, or Node.js is needed.

**Tests:** `python -m unittest discover -s tests -v` (requires dashboard
optional dependencies for dashboard API tests).
