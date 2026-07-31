# Tuya Robot Vacuum — Zabbix Local LAN Monitor

> **Cloud-free, predictive-maintenance monitoring for any Tuya OEM robot
> vacuum using Zabbix 7.0 — no cloud dependency at runtime.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://www.python.org/)
[![Zabbix 7.0](https://img.shields.io/badge/Zabbix-7.0-red.svg)](https://www.zabbix.com/)
[![tinytuya](https://img.shields.io/badge/tinytuya-%E2%89%A51.13.1-orange.svg)](https://github.com/jasonacox/tinytuya)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Compatibility](#2-compatibility)
3. [Architecture](#3-architecture)
4. [Data Point Catalogue (DPs) — Reference Implementation](#4-data-point-catalogue-dps--reference-implementation)
5. [Prerequisites](#5-prerequisites)
6. [Installation — Step by Step](#6-installation--step-by-step)
   - 6.1 [Extracting the Local Key (Tuya Cloud Bypass)](#61-extracting-the-local-key-tuya-cloud-bypass)
   - 6.2 [Collector Host Setup](#62-collector-host-setup)
   - 6.3 [Zabbix Proxy (Docker)](#63-zabbix-proxy-docker)
   - 6.4 [Configuring the Collector Script](#64-configuring-the-collector-script)
   - 6.5 [Scheduling with Cron](#65-scheduling-with-cron)
   - 6.6 [Importing the Zabbix Template](#66-importing-the-zabbix-template)
   - 6.7 [Creating the Host in Zabbix](#67-creating-the-host-in-zabbix)
7. [Adapting to Other Models](#7-adapting-to-other-models)
8. [Template Reference](#8-template-reference)
9. [Triggers & Alerts](#9-triggers--alerts)
10. [Troubleshooting](#10-troubleshooting)
11. [Known Issues & Workarounds](#11-known-issues--workarounds)
12. [License](#12-license)

---

## 1. Overview

Many robot vacuums sold under different brand names — including KaBuM, Multilaser,
Intelbras, Xiaomi (some lines), Philco, and others — are built on **Tuya OEM
hardware** and share the same local communication protocol (AES-3.3 or AES-3.4).

By default, all telemetry from these devices passes through the **Tuya cloud**,
which introduces latency, dependency on internet connectivity, and potential
privacy concerns.

This project implements a **fully local monitoring pipeline** that:

- Decrypts AES packets directly on the local network using the
  [`tinytuya`](https://github.com/jasonacox/tinytuya) library.
- Forwards a raw JSON payload to a **Zabbix 7.0** instance via
  `zabbix_sender` (Trapper protocol).
- Processes telemetry data points (DPs) — operational state, battery,
  consumable wear, and hardware sensors — using Zabbix's native
  **Dependent Items** and **JSONPath pre-processing**.
- Triggers predictive-maintenance alerts for consumables before they reach
  end-of-life.

**No Tuya cloud call is made at runtime.**

The collector script and the Zabbix template included in this repository were
developed and tested against the **KaBuM Smart 900** (reference implementation),
but the pipeline is designed to work with **any Tuya OEM robot vacuum** by
simply adjusting the DP mappings. See [§7 Adapting to Other Models](#7-adapting-to-other-models).

---

## 2. Compatibility

### Confirmed Working

| Brand / Model | Protocol | Notes |
|---|---|---|
| KaBuM Smart 900 | 3.3 | Reference implementation; full DP catalogue in §4 |

### Expected Compatible (same Tuya OEM platform)

The following brands are known to use Tuya-based vacuum controllers. Exact DP
numbers may differ per model — use `python -m tinytuya wizard` to discover
your device's specific DP map.

| Brand | Examples |
|---|---|
| Multilaser | Robô Home Clean series |
| Intelbras | RoboCLEAN series |
| Philco | PH series |
| Cecotec | Some Conga models |
| Various white-label | Any vacuum paired via Smart Life / Tuya Smart apps |

> **How to check:** If your robot vacuum is paired using the **Smart Life** or
> **Tuya Smart** mobile app, it is almost certainly Tuya-based and compatible
> with this pipeline.

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        LOCAL NETWORK (LAN)                              │
│                                                                         │
│   ┌───────────────────┐   AES-3.3/3.4 (UDP/TCP)  ┌──────────────────┐  │
│   │  Tuya OEM Vacuum  │ ─────────────────────────►│  Ubuntu 24.04    │  │
│   │  (any brand)      │                           │  Collector Host  │  │
│   │  IP: 192.168.x.x  │                           │                  │  │
│   └───────────────────┘                           │  Python venv     │  │
│                                                   │  tuya_zabbix.py  │  │
│                                                   │  (cron: */1 * *) │  │
│                                                   └───────┬──────────┘  │
│                                                           │             │
│                                            zabbix_sender │ TCP:10051   │
│                                                           ▼             │
│                                         ┌─────────────────────────┐    │
│                                         │  Zabbix Proxy 7.0       │    │
│                                         │  Docker / SQLite3       │    │
│                                         └────────────┬────────────┘    │
└────────────────────────────────────────────────────── │ ───────────────┘
                                                        │ Internet / VPN
                                                        ▼
                                         ┌─────────────────────────┐
                                         │  Zabbix Server 7.0      │
                                         │                         │
                                         │  Master Item (Trapper)  │
                                         │  tuya.vacuum.raw [TEXT] │
                                         │          │              │
                                         │  ┌───────▼──────────┐  │
                                         │  │ Dependent Items  │  │
                                         │  │ (JSONPath per DP)│  │
                                         │  └──────────────────┘  │
                                         └─────────────────────────┘
```

### Design Decisions

| Decision | Rationale |
|---|---|
| **Trapper + zabbix_sender** | Collector controls timing; no active polling from Zabbix side |
| **Single master item (JSON blob)** | One network round-trip per cycle; Zabbix parses internally |
| **Dependent Items + JSONPath** | Zero CPU overhead on the collector; processing fully offloaded |
| **Python venv** | Avoids system package conflicts (PEP 668 / Ubuntu 24.04) |
| **Zabbix Proxy (Docker)** | Decouples the LAN segment from Zabbix Server; provides buffering |
| **Model-agnostic collector** | Same `tuya_zabbix.py` works for any Tuya device — only DP keys change |

---

## 4. Data Point Catalogue (DPs) — Reference Implementation

The following DP mapping was reverse-engineered from the **KaBuM Smart 900**,
which uses **high-register DPs starting at 101**. Other Tuya vacuum models
typically use lower registers (1–20) for the same concepts.

> Use `python -m tinytuya wizard` to discover the DP map for your specific
> device. See also [§7 Adapting to Other Models](#7-adapting-to-other-models).

| DP | Zabbix Key | Type | Unit | Preprocessing | Description |
|---|---|---|---|---|---|
| 101 | `tuya.vacuum.dp101.dnd` | CHAR | — | JSONPath `$.101` | Do Not Disturb toggle |
| 102 | `tuya.vacuum.dp102.auto_return` | CHAR | — | JSONPath `$.102` | Auto-return to dock |
| 103 | `tuya.vacuum.dp103.auto_boost` | CHAR | — | JSONPath `$.103` | Auto-boost suction |
| 105 | `tuya.vacuum.dp105.status` | CHAR | — | JSONPath `$.105` | Operational status string |
| 106 | `tuya.vacuum.dp106.battery` | FLOAT | % | JSONPath `$.106` | Battery level |
| 107 | `tuya.vacuum.dp107.clean_time` | FLOAT | min | JSONPath → ×0.0166667 | Last session duration |
| 108 | `tuya.vacuum.dp108.clean_area` | FLOAT | m² | JSONPath `$.108` | Last session area |
| 109 | `tuya.vacuum.dp109.suction` | CHAR | — | JSONPath `$.109` | Suction power setting |
| 110 | `tuya.vacuum.dp110.water_level` | CHAR | — | JSONPath `$.110` | Water/mop level |
| 113 | `tuya.vacuum.dp113.carpet_boost` | CHAR | — | JSONPath `$.113` | Carpet boost toggle |
| 114 | `tuya.vacuum.dp114.volume` | CHAR | — | JSONPath `$.114` | Speaker volume |
| 116 | `tuya.vacuum.dp116.hepa_filter` | FLOAT | h | JSONPath → ×0.000277778 | HEPA filter remaining life |
| 119 | `tuya.vacuum.dp119.main_brush` | FLOAT | h | JSONPath → ×0.000277778 | Main brush remaining life |
| 120 | `tuya.vacuum.dp120.side_brushes` | FLOAT | h | JSONPath → ×0.000277778 | Side brushes remaining life |
| 121 | `tuya.vacuum.dp121.sensors` | FLOAT | h | JSONPath → ×0.000277778 | Sensor array remaining life |
| 133 | `tuya.vacuum.dp133.error_code` | CHAR | — | JSONPath `$.133` | Last error code (`0` = nominal) |
| 136 | `tuya.vacuum.dp136.clean_mode` | CHAR | — | JSONPath `$.136` | Cleaning mode |
| 137 | `tuya.vacuum.dp137.water_tank` | CHAR | — | JSONPath `$.137` | Water tank presence |
| 138 | `tuya.vacuum.dp138.mop_pad` | CHAR | — | JSONPath `$.138` | Mop pad presence |
| 139 | `tuya.vacuum.dp139.dust_bin_full` | CHAR | — | JSONPath `$.139` | Dust bin full flag |
| 141 | `tuya.vacuum.dp141.voice` | CHAR | — | JSONPath `$.141` | Voice toggle |
| 144 | `tuya.vacuum.dp144.child_lock` | CHAR | — | JSONPath `$.144` | Child lock toggle |
| 151 | `tuya.vacuum.dp151.continuous_clean` | CHAR | — | JSONPath `$.151` | Continuous cleaning toggle |

> **Unit conversions applied at Zabbix pre-processing stage:**
> - Consumables (DPs 116, 119, 120, 121): device reports seconds → ×**0.000277778** → stored as **hours**
> - Cleaning time (DP 107): device reports seconds → ×**0.0166667** → stored as **minutes**

---

## 5. Prerequisites

### Collector Host (Ubuntu 24.04)

| Package | Version | Purpose |
|---|---|---|
| Python | ≥ 3.10 | Collector runtime |
| `python3-venv` | system | Isolated environment (PEP 668) |
| `zabbix-sender` | 7.x | Trapper injection binary |
| `tinytuya` | ≥ 1.13.1 | Local AES decryption (3.3 / 3.4) |

### Zabbix Infrastructure

| Component | Version | Notes |
|---|---|---|
| Zabbix Server | 7.0 | Receives and processes data |
| Zabbix Proxy | 7.0 | Docker container, SQLite3 backend |
| Proxy port | TCP 10051 | Must be reachable from the collector host |

### Tuya Developer Account

- A free account at [platform.tuya.com](https://platform.tuya.com)
- A project configured on the **Western America Data Center**
- The vacuum device linked via the **Smart Life** app (blue icon) — see §6.1

---

## 6. Installation — Step by Step

### 6.1 Extracting the Local Key (Tuya Cloud Bypass)

> **Important:** The standard **Tuya Smart** app causes a persistent OAuth
> cross-tenant error (`"Phones non-cellular"`) when scanning the developer QR
> code. Always use **Smart Life (blue icon)** instead.

This step is performed **once per device**. The Local Key does not change
unless the device is factory-reset or re-paired.

1. **Create a developer project**

   - Go to [platform.tuya.com](https://platform.tuya.com) → Cloud → Development → Create Cloud Project.
   - Select **Western America** as the data centre.
   - Enable the **Smart Home** and **Device Status Notification** APIs.

2. **Link the device**

   - Open **Smart Life** (blue icon — not Tuya Smart).
   - Tap **+** → Scan QR code → scan the QR code from your developer project's "Devices" tab.
   - The device should appear as linked within a few seconds.

3. **Collect the credentials**

   From your project's **Overview** page, note:
   - `API Key` (Client ID)
   - `API Secret` (Client Secret)
   - `Device ID` (from the Devices tab)

4. **Run the tinytuya wizard**

   ```bash
   # Inside the venv (see §6.2)
   python -m tinytuya wizard
   ```

   Provide the API Key, API Secret, and Device ID when prompted. The wizard
   downloads the full device topology and reveals the **Local Key** (16-character
   AES key). It also saves `devices.json` locally — keep it private.

   > After this step, all communication happens locally. No further cloud
   > access is needed at runtime.

---

### 6.2 Collector Host Setup

```bash
# 1. Install system packages
sudo apt update
sudo apt install -y python3 python3-venv zabbix-sender

# 2. Clone this repository
git clone git@github.com:jh-oliveira1993/zabbix-tuya-robot-vacuum.git
cd zabbix-tuya-robot-vacuum

# 3. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 4. Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 5. Smoke test — verify tinytuya can reach the device
python -c "
import tinytuya
d = tinytuya.Device('YOUR_DEVICE_ID', 'YOUR_DEVICE_IP', 'YOUR_LOCAL_KEY', version=3.3)
print(d.status())
"
```

---

### 6.3 Zabbix Proxy (Docker)

If you do not already have a Zabbix Proxy running, the minimal `docker-compose`
snippet below starts one with a SQLite3 backend:

```yaml
# docker-compose.yml (minimal Zabbix Proxy 7.0)
version: "3.9"
services:
  zabbix-proxy:
    image: zabbix/zabbix-proxy-sqlite3:ubuntu-7.0-latest
    container_name: zabbix-proxy
    restart: unless-stopped
    environment:
      ZBX_SERVER_HOST: your-zabbix-server.example.com  # Zabbix Server FQDN/IP
      ZBX_HOSTNAME: zabbix-proxy-local                 # Must match Server config
      ZBX_TIMEOUT: 10
    ports:
      - "10051:10051"
    volumes:
      - zbx_proxy_data:/var/lib/zabbix/db_data

volumes:
  zbx_proxy_data:
```

```bash
docker compose up -d
docker compose logs -f zabbix-proxy   # verify "proxy started"
```

---

### 6.4 Configuring the Collector Script

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
nano .env
```

```dotenv
# .env — Tuya + Zabbix configuration
TUYA_DEVICE_ID=abcdef1234567890abcdef
TUYA_DEVICE_IP=192.168.1.XXX
TUYA_LOCAL_KEY=1234567890abcdef
TUYA_PROTOCOL_VERSION=3.3        # use 3.4 for newer firmware

ZABBIX_PROXY_HOST=192.168.1.93
ZABBIX_PROXY_PORT=10051
ZABBIX_HOST_NAME=MyTuyaVacuum   # must match the host name in Zabbix
ZABBIX_ITEM_KEY=tuya.vacuum.raw
ZABBIX_SENDER_BIN=/usr/bin/zabbix_sender
```

Test a manual run:

```bash
source .env && python tuya_zabbix.py
```

Expected output (success):

```
2026-01-01T12:00:00 [INFO] === tuya_zabbix.py starting ===
2026-01-01T12:00:00 [INFO] Connecting to device abc123 at 192.168.1.xxx (protocol 3.3) ...
2026-01-01T12:00:01 [INFO] Payload (312 bytes): {"101":false,"105":"dormant","106":95,...}
2026-01-01T12:00:01 [INFO] Sending data to Zabbix Proxy at 192.168.1.93:10051 ...
2026-01-01T12:00:01 [INFO] zabbix_sender: info from server: "processed: 1; failed: 0; total: 1; seconds spent: 0.000102"
2026-01-01T12:00:01 [INFO] === tuya_zabbix.py finished successfully ===
```

---

### 6.5 Scheduling with Cron

```bash
crontab -e
```

Add (adjust paths as needed):

```cron
# Collect Tuya vacuum telemetry every minute
* * * * * cd /path/to/zabbix-tuya-robot-vacuum && \
  source .env && \
  .venv/bin/python tuya_zabbix.py \
  >> /var/log/tuya_zabbix.log 2>&1
```

Verify the log after a minute:

```bash
tail -f /var/log/tuya_zabbix.log
```

---

### 6.6 Importing the Zabbix Template

1. Log in to your Zabbix frontend.
2. Navigate to **Configuration → Templates**.
3. Click **Import** (top-right).
4. Select `zabbix_template_tuya_robot_vacuum.yaml` from this repository.
5. Leave all options at their defaults and click **Import**.

The template **Tuya Robot Vacuum** will be created automatically.

> [!IMPORTANT]
> **UUID identity:** Zabbix identifies templates by UUID, not by name.
> This file shares the same UUID as the production template
> (`Template Tuya Vacuum KaBuM 900`).
>
> - **"Update existing" checked:** Zabbix will update the production template
>   in-place — renaming it to **Tuya Robot Vacuum** and applying any YAML
>   changes. Items, triggers, and host links remain intact.
> - **"Update existing" unchecked:** Zabbix silently skips the template
>   (UUID already exists) — no changes are made.
>
> If you want a **completely independent** template (e.g., for a different
> device model), generate a new UUID for the `template:` block and all its
> items before importing.

> To adapt the template for a different model, duplicate `zabbix_template_tuya_robot_vacuum.yaml`,
> replace all UUIDs with freshly generated v4 UUIDs, adjust item names and
> JSONPath expressions, then import the new file (see §7).

---

### 6.7 Creating the Host in Zabbix

1. Navigate to **Configuration → Hosts → Create host**.
2. Fill in:
   - **Host name**: must match `ZABBIX_HOST_NAME` in your `.env` exactly.
   - **Groups**: IoT/Smart Home
3. Under **Templates**, link the imported template.
4. Under **Monitored by proxy**, select your Zabbix Proxy.
5. No interface is required — data arrives via Trapper.
6. Click **Add**.

---

## 7. Adapting to Other Models

The entire pipeline is model-agnostic. Only the **DP numbers and their
semantics** differ between models. To adapt this project to a different Tuya
robot vacuum:

### Step 1 — Discover your device's DP map

```bash
# With the device online and the venv active:
python -m tinytuya wizard
# Then inspect the generated devices.json and snapshot.json
```

Or query the device directly:

```python
import tinytuya, json
d = tinytuya.Device('DEVICE_ID', 'DEVICE_IP', 'LOCAL_KEY', version=3.3)
status = d.status()
print(json.dumps(status.get('dps', {}), indent=2))
```

The output will show which DP numbers are active on your device and what
values they currently hold.

### Step 2 — Map DPs to meaningful names

Compare the raw DP values against the vacuum's behaviour (e.g., trigger the
charger, start a cleaning cycle, check battery) to identify each register.
Community resources such as the
[tinytuya GitHub Issues](https://github.com/jasonacox/tinytuya/issues) and
[Tuya Developer Docs](https://developer.tuya.com/en/docs/iot/standarddescription?id=K9i5ql6waswzq)
are valuable references.

### Step 3 — Update the Zabbix template

In `zabbix_template_tuya_robot_vacuum.yaml`, each dependent item has a
pre-processing step like:

```yaml
preprocessing:
  - type: JSONPATH
    parameters:
      - $.106        # <-- change this to your DP number
```

Duplicate the template file (e.g., `zabbix_template_my_vacuum.yaml`),
update the item names, keys, and JSONPath expressions, assign new RFC 4122
UUIDs, and import via the Zabbix UI.

### Step 4 — Update `.env`

```dotenv
TUYA_PROTOCOL_VERSION=3.4   # if your device uses protocol 3.4
ZABBIX_HOST_NAME=MyVacuumModel
```

No changes to `tuya_zabbix.py` are needed — the collector script is
fully generic and sends the entire `dps` dictionary regardless of model.

---

## 8. Template Reference

| File | Description |
|---|---|
| [`zabbix_template_tuya_robot_vacuum.yaml`](zabbix_template_tuya_robot_vacuum.yaml) | Zabbix 7.0 YAML — reference template (tested on KaBuM Smart 900) |
| [`tuya_zabbix.py`](tuya_zabbix.py) | Generic Python 3 collector script (works for any Tuya vacuum) |
| [`.env.example`](.env.example) | Environment variable template |

### Item Counts (Reference Template)

| Category | Count |
|---|---|
| Master (Trapper) | 1 |
| Dependent — Operation | 4 |
| Dependent — Settings | 9 |
| Dependent — Consumables | 4 |
| Dependent — Hardware sensors | 3 |
| Dependent — Diagnostics | 1 |
| Dependent — Boolean toggles | 3 |
| **Total items** | **25** |

---

## 9. Triggers & Alerts

| Trigger | Severity | Condition |
|---|---|---|
| Battery critically low | **Average** | DP 106 < 15% |
| HEPA filter due | **Warning** | DP 116 < 10 h remaining |
| Main brush due | **Warning** | DP 119 < 10 h remaining |
| Side brushes due | **Warning** | DP 120 < 10 h remaining |
| Device error detected | **High** | DP 133 ≠ "0" and ≠ "no_error" |
| Dust bin full | **Info** | DP 139 = "true" |

---

## 10. Troubleshooting

### `tinytuya` returns `{"Error": "..."}` or empty dict

- Ensure the vacuum is **online on the local network** (ping its IP).
- Verify the `LOCAL_KEY` is correct — re-run `python -m tinytuya wizard`
  if the device was reset or re-paired.
- Try `TUYA_PROTOCOL_VERSION=3.4` if you see AES decryption errors.

### `zabbix_sender` fails with "connection refused"

- Check the proxy container: `docker ps | grep zabbix-proxy`
- Check port exposure: `ss -tlnp | grep 10051`
- Check firewall: `sudo ufw status` / `sudo iptables -L`

### Items remain "Not supported" in Zabbix

- The host name in Zabbix must **exactly** match `ZABBIX_HOST_NAME` in `.env`.
- The item key must be `tuya.vacuum.raw` (no trailing spaces).
- Dependent items activate automatically after the first successful
  `zabbix_sender` injection.

### Tuya Developer QR code scan fails with Tuya Smart app

See §6.1 — use **Smart Life (blue icon)** instead of Tuya Smart.

---

## 11. Known Issues & Workarounds

### OAuth Cross-Tenant Error (Tuya Smart vs Smart Life)

When scanning the developer project QR code with the **Tuya Smart** app, the
platform returns a persistent error related to OAuth scope validation
(`"Phones Non-cellular"` or cross-tenant permission denial).

**Root cause:** The Tuya Smart app enforces stricter tenant isolation that
conflicts with developer-project linking in some regions.

**Workaround:** Use the **Smart Life** app (blue icon). It uses a different
OAuth tenant that bypasses the restriction. The device appears in the developer
project normally after scanning.

### Local Key Rotation on Re-pairing

If the vacuum is factory-reset or re-paired with a different account, the
AES Local Key changes. Re-run `python -m tinytuya wizard` after any
re-pairing event and update `TUYA_LOCAL_KEY` in `.env`.

### Zabbix YAML UUID Validation

The Zabbix 7.0 YAML parser enforces strict **RFC 4122 UUIDv4** format:
- Character at position 13 (group 3, first char) must be `4`.
- Character at position 17 (group 4, first char) must be `8`, `9`, `a`, or `b`.
- All other characters must be lowercase hex (`0-9`, `a-f`).

Any deviation causes a silent import failure. When creating custom templates
for other models, validate UUIDs before importing:

```bash
python3 -c "
import re, sys
UUID_RE = re.compile(r'uuid:\s+([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', re.I)
uuids = UUID_RE.findall(open('your_template.yaml').read())
errors = [u for u in uuids if u.split('-')[2][0]!='4' or u.split('-')[3][0] not in '89ab']
print(f'{len(uuids)} UUIDs found, {len(errors)} invalid')
if errors: print('\n'.join(errors)); sys.exit(1)
"
```

### Master Item Type: `TRAP` not `TRAPPER`

In Zabbix 7.0 YAML exports the constant for the Trapper item type is `TRAP`
(not `TRAPPER`). Using `TRAPPER` causes the import to reject the item.

---

## 12. License

MIT License — see [LICENSE](LICENSE) for details.
