#!/usr/bin/env python3
"""
tuya_zabbix.py — Tuya Local LAN Telemetry Collector for Zabbix
================================================================
Reads the full DPS (Data Points) payload from a KaBuM Smart 900
robot vacuum (Tuya OEM, protocol 3.3) over the local network,
serialises the ``dps`` dictionary as JSON and injects it into a
Zabbix Proxy / Server using ``zabbix_sender``.

No Tuya cloud call is made at runtime — all cryptography is
handled locally by the ``tinytuya`` library (AES-ECB, key v3.3).

Usage
-----
Run directly or schedule with cron::

    */1 * * * * /path/to/venv/bin/python /path/to/tuya_zabbix.py

Environment / Config
--------------------
All parameters are read from the CONFIG block below.  Edit them
once during initial setup; do NOT hard-code secrets into the
version-controlled copy of this file (use environment variables
or a separate ``config.env`` file sourced before the script).

Dependencies
------------
- tinytuya >= 1.13.1   (pip install tinytuya)
- zabbix_sender binary available in PATH (from ``zabbix-sender``
  package on the collector host)

Author : José Henrique  /  Antigravity AI
License: MIT
"""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# CONFIGURATION — edit these values (or export as environment variables)
# ---------------------------------------------------------------------------
DEVICE_ID: str = os.getenv("TUYA_DEVICE_ID", "YOUR_DEVICE_ID_HERE")
DEVICE_IP: str = os.getenv("TUYA_DEVICE_IP", "192.168.15.XXX")
LOCAL_KEY: str = os.getenv("TUYA_LOCAL_KEY", "YOUR_16_CHAR_KEY_HERE")
PROTOCOL_VERSION: float = float(os.getenv("TUYA_PROTOCOL_VERSION", "3.3"))

# Zabbix Proxy / Server that receives the trapper data
ZABBIX_PROXY_HOST: str = os.getenv("ZABBIX_PROXY_HOST", "192.168.15.93")
ZABBIX_PROXY_PORT: int = int(os.getenv("ZABBIX_PROXY_PORT", "10051"))

# Hostname as registered in Zabbix (must match exactly)
ZABBIX_HOST_NAME: str = os.getenv("ZABBIX_HOST_NAME", "KaBuM-Smart-900")

# Master trapper item key defined in the Zabbix template
ZABBIX_ITEM_KEY: str = os.getenv("ZABBIX_ITEM_KEY", "tuya.vacuum.raw")

# Path to the zabbix_sender binary (must be installed on the collector)
ZABBIX_SENDER_BIN: str = os.getenv("ZABBIX_SENDER_BIN", "/usr/bin/zabbix_sender")

# Timeout for the local device query (seconds)
DEVICE_TIMEOUT: int = int(os.getenv("TUYA_DEVICE_TIMEOUT", "10"))

# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def fetch_device_status() -> Optional[Dict[str, Any]]:
    """
    Open a local LAN connection to the Tuya device and return the raw
    status dictionary.  Returns ``None`` on any error so the caller
    can decide whether to abort or send a sentinel value.
    """
    try:
        import tinytuya  # imported here so missing dep gives a clear error
    except ImportError as exc:
        log.error(
            "tinytuya is not installed.  "
            "Run: pip install tinytuya  — %s", exc
        )
        return None

    log.info(
        "Connecting to device %s at %s (protocol %.1f) …",
        DEVICE_ID, DEVICE_IP, PROTOCOL_VERSION,
    )

    device = tinytuya.Device(
        dev_id=DEVICE_ID,
        address=DEVICE_IP,
        local_key=LOCAL_KEY,
    )
    device.set_version(PROTOCOL_VERSION)
    device.set_socketTimeout(DEVICE_TIMEOUT)

    status = device.status()
    log.debug("Raw status from device: %s", status)

    if not isinstance(status, dict):
        log.error("Unexpected response type from device: %r", status)
        return None

    if "Error" in status:
        log.error("Device returned error: %s", status["Error"])
        return None

    return status


def build_payload(status: Dict[str, Any]) -> str:
    """
    Extract the ``dps`` sub-dictionary and serialise it as a compact
    JSON string ready to be sent as the Zabbix trapper value.

    The top-level ``dps`` key holds all DP (data point) registers.
    We also inject a ``_collected_at`` ISO-8601 timestamp so that
    Zabbix pre-processing expressions and dashboards can reference
    the exact moment the data was sampled.
    """
    dps: Dict[str, Any] = status.get("dps", {})

    # Stringify numeric DP keys to make JSONPath simpler (".101", ".106" …)
    payload: Dict[str, Any] = {str(k): v for k, v in dps.items()}
    payload["_collected_at"] = (
        datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def send_to_zabbix(json_value: str) -> bool:
    """
    Invoke ``zabbix_sender`` as a subprocess to push the JSON payload
    to the configured Zabbix Proxy / Server.

    Returns ``True`` on success, ``False`` on failure.
    """
    if not os.path.isfile(ZABBIX_SENDER_BIN):
        log.error(
            "zabbix_sender binary not found at %s.  "
            "Install it with: sudo apt install zabbix-sender",
            ZABBIX_SENDER_BIN,
        )
        return False

    cmd = [
        ZABBIX_SENDER_BIN,
        "--zabbix-server", ZABBIX_PROXY_HOST,
        "--port", str(ZABBIX_PROXY_PORT),
        "--host", ZABBIX_HOST_NAME,
        "--key", ZABBIX_ITEM_KEY,
        "--value", json_value,
    ]

    log.info(
        "Sending data to Zabbix Proxy at %s:%s …",
        ZABBIX_PROXY_HOST, ZABBIX_PROXY_PORT,
    )
    log.debug("zabbix_sender command: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            log.info("zabbix_sender: %s", result.stdout.strip())
            return True
        else:
            log.error(
                "zabbix_sender exited %d — stdout: %s — stderr: %s",
                result.returncode,
                result.stdout.strip(),
                result.stderr.strip(),
            )
            return False
    except subprocess.TimeoutExpired:
        log.error("zabbix_sender timed out after 15 s")
        return False
    except OSError as exc:
        log.error("Failed to execute zabbix_sender: %s", exc)
        return False


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main() -> int:
    """Entry point.  Returns a POSIX exit code (0 = success)."""
    log.info("=== tuya_zabbix.py starting ===")

    # 1. Fetch telemetry from the device
    status = fetch_device_status()
    if status is None:
        log.critical("Could not retrieve device status — aborting.")
        return 1

    # 2. Build the JSON payload
    payload = build_payload(status)
    log.info("Payload (%d bytes): %s", len(payload), payload)

    # 3. Push to Zabbix
    success = send_to_zabbix(payload)
    if not success:
        log.critical("Failed to send data to Zabbix.")
        return 2

    log.info("=== tuya_zabbix.py finished successfully ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
