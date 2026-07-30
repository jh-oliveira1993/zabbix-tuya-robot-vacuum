# KaBuM Smart 900 — Zabbix Local LAN Monitor

> **Cloud-free, predictive-maintenance monitoring for the KaBuM Smart 900
> robot vacuum (Tuya OEM, AES-3.3) using Zabbix 7.0.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://www.python.org/)
[![Zabbix 7.0](https://img.shields.io/badge/Zabbix-7.0-red.svg)](https://www.zabbix.com/)

---

## Table of Contents

1. [Overview](#1-overview)  
2. [Architecture](#2-architecture)  
3. [Data Point Catalogue (DPs)](#3-data-point-catalogue-dps)  
4. [Prerequisites](#4-prerequisites)  
5. [Installation — Step by Step](#5-installation--step-by-step)  
   - 5.1 [Extracting the Local Key (Tuya Cloud Bypass)](#51-extracting-the-local-key-tuya-cloud-bypass)  
   - 5.2 [Collector Host Setup](#52-collector-host-setup)  
   - 5.3 [Zabbix Proxy (Docker)](#53-zabbix-proxy-docker)  
   - 5.4 [Configuring the Collector Script](#54-configuring-the-collector-script)  
   - 5.5 [Scheduling with Cron](#55-scheduling-with-cron)  
   - 5.6 [Importing the Zabbix Template](#56-importing-the-zabbix-template)  
   - 5.7 [Creating the Host in Zabbix](#57-creating-the-host-in-zabbix)  
6. [Template Reference](#6-template-reference)  
7. [Triggers & Alerts](#7-triggers--alerts)  
8. [Troubleshooting](#8-troubleshooting)  
9. [Known Issues & Workarounds](#9-known-issues--workarounds)  
10. [License](#10-license)  

---

## 1. Overview

The **KaBuM Smart 900** is a Tuya-based OEM robot vacuum.  By default, all
telemetry passes through the Tuya cloud, which introduces latency, dependency
on internet connectivity, and potential privacy concerns.

This project implements a **fully local monitoring pipeline** that:

- Decrypts AES-3.3 packets directly on the local network using the
  [`tinytuya`](https://github.com/jasonacox/tinytuya) library.
- Forwards a raw JSON payload to a **Zabbix 7.0** instance via
  `zabbix_sender` (Trapper protocol).
- Processes 25 telemetry data points (DPs) — including operational state,
  battery, consumable wear, and hardware sensors — using Zabbix's native
  **Dependent Items** and **JSONPath pre-processing**.
- Triggers predictive-maintenance alerts for consumables before they reach
  end-of-life.

**No Tuya cloud call is made at runtime.**

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        LOCAL NETWORK (LAN)                              │
│                                                                         │
│   ┌───────────────────┐   AES-3.3 (UDP/TCP)   ┌─────────────────────┐  │
│   │  KaBuM Smart 900  │ ──────────────────────►│   Ubuntu 24.04      │  │
│   │  (Tuya OEM)       │                        │   Collector Host    │  │
│   │  IP: 192.168.x.x  │                        │                     │  │
│   └───────────────────┘                        │  Python venv        │  │
│                                                │  tuya_zabbix.py     │  │
│                                                │  (cron: */1 * * * *)│  │
│                                                └────────┬────────────┘  │
│                                                         │               │
│                                          zabbix_sender  │  TCP:10051    │
│                                                         ▼               │
│                                         ┌───────────────────────────┐   │
│                                         │  Zabbix Proxy 7.0         │   │
│                                         │  Docker / SQLite3         │   │
│                                         │  192.168.15.93:10051      │   │
│                                         └────────────┬──────────────┘   │
└──────────────────────────────────────────────────────│──────────────────┘
                                                       │ Internet / VPN
                                                       ▼
                                         ┌───────────────────────────┐
                                         │  Zabbix Server 7.0        │
                                         │  jholiv-zabbix.ddns.net   │
                                         │                           │
                                         │  Master Item (Trapper)    │
                                         │  tuya.vacuum.raw  [TEXT]  │
                                         │          │                │
                                         │  ┌───────▼────────────┐  │
                                         │  │  Dependent Items   │  │
                                         │  │  (×24 JSONPath DPs)│  │
                                         │  └────────────────────┘  │
                                         └───────────────────────────┘
```

### Design Decisions

| Decision | Rationale |
|---|---|
| **Trapper + zabbix_sender** | Collector controls timing; no active polling from Zabbix side |
| **Single master item (JSON blob)** | One network round-trip per collection cycle; Zabbix does all parsing internally |
| **Dependent Items + JSONPath** | Zero CPU overhead on the collector; processing offloaded to the Zabbix engine |
| **Python venv** | Avoids conflicts with system packages (PEP 668 / Ubuntu 24.04) |
| **Zabbix Proxy (Docker)** | Decouples the local LAN segment from the Zabbix Server; provides buffering |

---

## 3. Data Point Catalogue (DPs)

The KaBuM Smart 900 uses **high-register DPs starting at 101**.

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
> - Consumables (DPs 116, 119, 120, 121): device reports seconds → multiplied by **0.000277778** → stored as **hours**
> - Cleaning time (DP 107): device reports seconds → multiplied by **0.0166667** → stored as **minutes**

---

## 4. Prerequisites

### Collector Host (Ubuntu 24.04)

| Package | Version | Purpose |
|---|---|---|
| Python | ≥ 3.10 | Collector runtime |
| `python3-venv` | system | Isolated environment (PEP 668) |
| `zabbix-sender` | 7.x | Trapper injection binary |
| `tinytuya` | ≥ 1.13.1 | Local AES-3.3 decryption |

### Zabbix Infrastructure

| Component | Version | Notes |
|---|---|---|
| Zabbix Server | 7.0 | Receives and processes data |
| Zabbix Proxy | 7.0 | Docker container, SQLite3 backend |
| Proxy port | TCP 10051 | Must be reachable from collector host |

### Tuya Developer Account

- A free account at [platform.tuya.com](https://platform.tuya.com)
- A project configured on the **Western America Data Center**
- The vacuum device linked via the **Smart Life** app (blue icon) — see §5.1

---

## 5. Installation — Step by Step

### 5.1 Extracting the Local Key (Tuya Cloud Bypass)

> **Important:** The standard **Tuya Smart** app causes a persistent OAuth
> cross-tenant error (`"Phones non-cellular"`) when scanning the developer QR
> code.  Always use **Smart Life (blue icon)** instead.

1. **Create a developer project**

   - Go to [platform.tuya.com](https://platform.tuya.com) → Cloud → Development → Create Cloud Project.
   - Select **Western America** as the data centre.
   - Enable the **Smart Home** and **Device Status Notification** APIs.

2. **Link the device**

   - Open **Smart Life** (blue icon, not Tuya Smart).
   - Tap the **+** icon → Scan QR code → scan the QR code shown in your
     developer project's "Devices" tab.
   - The vacuum should appear as linked in the project within a few seconds.

3. **Collect the credentials**

   From your project's **Overview** page, note:
   - `API Key` (Client ID)
   - `API Secret` (Client Secret)
   - `Device ID` (from the Devices tab)

4. **Run the tinytuya wizard**

   ```bash
   # On the collector host, inside the venv (see §5.2)
   python -m tinytuya wizard
   ```

   Provide the API Key, API Secret, and Device ID when prompted.  
   The wizard downloads the device topology and reveals the **Local Key**
   (16-character AES key).  It also saves `devices.json` locally.

   > The Local Key is extracted **once** from the cloud and then used
   > exclusively for local communication.  No further cloud access is needed.

---

### 5.2 Collector Host Setup

```bash
# 1. Install system packages
sudo apt update
sudo apt install -y python3 python3-venv zabbix-sender

# 2. Clone this repository
git clone https://github.com/<your-org>/zabbix-tuya-robot-vacuum.git
cd zabbix-tuya-robot-vacuum

# 3. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 4. Install Python dependencies
pip install --upgrade pip
pip install tinytuya>=1.13.1

# 5. Verify tinytuya can reach the device (optional smoke test)
python -c "
import tinytuya
d = tinytuya.Device('DEVICE_ID', 'DEVICE_IP', 'LOCAL_KEY', version=3.3)
print(d.status())
"
```

---

### 5.3 Zabbix Proxy (Docker)

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
      ZBX_SERVER_HOST: jholiv-zabbix.ddns.net   # Your Zabbix Server FQDN/IP
      ZBX_HOSTNAME: zabbix-proxy-local           # Must match Server config
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

### 5.4 Configuring the Collector Script

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
nano .env
```

```dotenv
# .env — Tuya + Zabbix configuration
TUYA_DEVICE_ID=abcdef1234567890abcdef
TUYA_DEVICE_IP=192.168.15.XXX
TUYA_LOCAL_KEY=1234567890abcdef
TUYA_PROTOCOL_VERSION=3.3

ZABBIX_PROXY_HOST=192.168.15.93
ZABBIX_PROXY_PORT=10051
ZABBIX_HOST_NAME=KaBuM-Smart-900
ZABBIX_ITEM_KEY=tuya.vacuum.raw
ZABBIX_SENDER_BIN=/usr/bin/zabbix_sender
```

Source `.env` before running the script:

```bash
source .env && python tuya_zabbix.py
```

Expected output (success):

```
2026-01-01T12:00:00 [INFO] === tuya_zabbix.py starting ===
2026-01-01T12:00:00 [INFO] Connecting to device abc123 at 192.168.15.xxx (protocol 3.3) ...
2026-01-01T12:00:01 [INFO] Payload (312 bytes): {"101":false,"105":"dormant","106":95,...}
2026-01-01T12:00:01 [INFO] Sending data to Zabbix Proxy at 192.168.15.93:10051 ...
2026-01-01T12:00:01 [INFO] zabbix_sender: info from server: "processed: 1; failed: 0; total: 1; seconds spent: 0.000102"
2026-01-01T12:00:01 [INFO] === tuya_zabbix.py finished successfully ===
```

---

### 5.5 Scheduling with Cron

```bash
crontab -e
```

Add the following line (adjust paths as needed):

```cron
# Collect KaBuM Smart 900 telemetry every minute
* * * * * cd /home/jose/Projects/zabbix/zabbix-tuya-robot-vacuum && \
  source .env && \
  /home/jose/Projects/zabbix/zabbix-tuya-robot-vacuum/.venv/bin/python \
  /home/jose/Projects/zabbix/zabbix-tuya-robot-vacuum/tuya_zabbix.py \
  >> /var/log/tuya_zabbix.log 2>&1
```

Verify the log after a minute:

```bash
tail -f /var/log/tuya_zabbix.log
```

---

### 5.6 Importing the Zabbix Template

1. Log in to your Zabbix frontend (e.g., `https://jholiv-zabbix.ddns.net/zabbix`).
2. Navigate to **Configuration → Templates**.
3. Click **Import** (top-right).
4. Select `zabbix_template_kabum_smart_900.yaml` from this repository.
5. Leave all options at their defaults and click **Import**.

The template group **IoT/Smart Home** and the template **KaBuM Smart 900 Vacuum**
will be created automatically.

---

### 5.7 Creating the Host in Zabbix

1. Navigate to **Configuration → Hosts → Create host**.
2. Fill in:
   - **Host name**: `KaBuM-Smart-900` *(must match `ZABBIX_HOST_NAME` in your `.env`)*
   - **Visible name**: KaBuM Smart 900
   - **Groups**: IoT/Smart Home
3. Under **Templates**, link **KaBuM Smart 900 Vacuum**.
4. Under **Monitored by proxy**, select your Zabbix Proxy.
5. No interface is required (data arrives via Trapper).
6. Click **Add**.

---

## 6. Template Reference

| File | Description |
|---|---|
| [`zabbix_template_kabum_smart_900.yaml`](zabbix_template_kabum_smart_900.yaml) | Zabbix 7.0 YAML export — import directly via the UI |
| [`tuya_zabbix.py`](tuya_zabbix.py) | Python 3 collector script |
| [`.env.example`](.env.example) | Environment variable template |

### Item Counts

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

## 7. Triggers & Alerts

| Trigger | Severity | Condition |
|---|---|---|
| Battery critically low | **Average** | DP 106 < 15% |
| HEPA filter due | **Warning** | DP 116 < 10 h remaining |
| Main brush due | **Warning** | DP 119 < 10 h remaining |
| Side brushes due | **Warning** | DP 120 < 10 h remaining |
| Device error detected | **High** | DP 133 ≠ "0" and ≠ "no_error" |
| Dust bin full | **Info** | DP 139 = "true" |

---

## 8. Troubleshooting

### `tinytuya` returns `{"Error": "..."}` or empty dict

- Ensure the vacuum is **online on the local network** (try pinging its IP).
- Verify the `LOCAL_KEY` is correct — re-run `python -m tinytuya wizard` if you
  reset or re-paired the device (a re-pair generates a new key).
- Check for **protocol version mismatch**: all KaBuM Smart 900 units observed
  use `3.3`, but try `3.4` if you see AES decryption errors.

### `zabbix_sender` fails with "connection refused"

- Confirm the Zabbix Proxy container is running: `docker ps | grep zabbix-proxy`
- Confirm port 10051 is exposed: `ss -tlnp | grep 10051`
- Confirm no firewall rule blocks the collector → proxy path:
  `sudo ufw status` / `sudo iptables -L`

### Items remain "Not supported" in Zabbix

- Confirm the host name in Zabbix **exactly** matches `ZABBIX_HOST_NAME` in `.env`.
- Confirm the item key is `tuya.vacuum.raw` (no trailing space).
- After the first successful `zabbix_sender` injection, dependent items activate
  automatically on the next collection cycle.

### Tuya Developer QR code scan fails with Tuya Smart app

See §5.1 — use **Smart Life (blue icon)** instead of Tuya Smart.

---

## 9. Known Issues & Workarounds

### OAuth Cross-Tenant Error (Tuya Smart vs Smart Life)

When scanning the developer project QR code with the **Tuya Smart** app, the
platform returns a persistent error related to OAuth scope validation
(`"Phones Non-cellular"` or cross-tenant permission denial).

**Root cause:** The Tuya Smart app enforces stricter tenant isolation that
conflicts with developer-project linking in some regions.

**Workaround:** Use the **Smart Life** app (blue icon) to scan the same QR
code.  Smart Life uses a different OAuth tenant that bypasses the restriction.
The device appears in the developer project normally after scanning.

### Local Key Rotation on Re-pairing

If the vacuum is factory-reset or re-paired with a different account, the
AES Local Key changes.  Re-run `python -m tinytuya wizard` after any
re-pairing event and update `TUYA_LOCAL_KEY` in `.env`.

### Zabbix YAML UUID Validation

The Zabbix 7.0 YAML parser enforces strict **RFC 4122 UUIDv4** format:
- Character at position 13 (group 3, first char) must be `4`.
- Character at position 17 (group 4, first char) must be `8`, `9`, `a`, or `b`.
- All other characters must be lowercase hex (`0-9`, `a-f`).

Any deviation causes a silent import failure or XML/YAML parse error.  The
template file in this repository has been pre-validated against this rule.

### Master Item Type: `TRAP` not `TRAPPER`

In Zabbix 7.0 YAML exports the constant for the Trapper item type is `TRAP`
(not `TRAPPER`).  Using `TRAPPER` causes the import to reject the item.

---

## 10. License

MIT License — see [LICENSE](LICENSE) for details.
