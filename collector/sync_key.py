#!/usr/bin/env python3
"""
sync_key.py — Automate Local Key renewal from Tuya Developer Platform
=====================================================================
Connects to Tuya Cloud using credentials from tinytuya.json,
fetches the latest Local Key and Device ID for the vacuum,
updates collector/.env automatically, and tests local communication.

Usage:
    /home/jose/Projects/python/zabbix_tuya_poll/venv/bin/python sync_key.py
"""

import json
import os
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TINYTUTA_CFG_PATHS = [
    BASE_DIR / "tinytuya.json",
    BASE_DIR.parent / "tinytuya.json",
    Path("/home/jose/Projects/python/zabbix_tuya_poll/tinytuya.json"),
]
ENV_FILE = BASE_DIR / ".env"

def find_tinytuya_config():
    for p in TINYTUTA_CFG_PATHS:
        if p.exists():
            with open(p) as f:
                return json.load(f), p
    return None, None

def main():
    print("=== Tuya Local Key Sync Utility ===")
    cfg, cfg_path = find_tinytuya_config()
    if not cfg:
        print("[!] Error: tinytuya.json not found.")
        print("    Run 'python -m tinytuya wizard' first or configure tinytuya.json.")
        sys.exit(1)

    print(f"[*] Loaded Tuya Cloud configuration from {cfg_path}")
    print(f"    Region: {cfg.get('apiRegion')}")
    print(f"    Client ID: {cfg.get('apiKey')}")

    try:
        import tinytuya
    except ImportError:
        print("[!] Error: tinytuya module not installed in current Python environment.")
        sys.exit(1)

    cloud = tinytuya.Cloud(
        apiRegion=cfg.get("apiRegion", "us"),
        apiKey=cfg.get("apiKey"),
        apiSecret=cfg.get("apiSecret"),
        apiDeviceID=cfg.get("apiDeviceID"),
    )

    print("[*] Contacting Tuya Cloud API...")
    devices_res = cloud.getdevices()

    if isinstance(devices_res, dict) and "Error" in devices_res:
        payload = str(devices_res.get("Payload", ""))
        print(f"\n[!] Tuya Cloud API Error: {devices_res.get('Error')} ({devices_res.get('Err')})")
        if "28841002" in payload or "expired" in payload.lower():
            print("\n[>>>] ROOT CAUSE: IoT Core service subscription has expired.")
            print("      To fix this:")
            print("      1. Log in to https://platform.tuya.com")
            print("      2. Navigate to: Cloud -> Cloud Services -> My Subscriptions (or IoT Core)")
            print("      3. Click 'Extension / Renew' for the free trial.")
            print("      4. After extending, re-run this script!")
        else:
            print(f"    Details: {payload}")
        sys.exit(2)

    if not isinstance(devices_res, list) or len(devices_res) == 0:
        print("[!] No devices found in Tuya Developer Cloud project.")
        print("    Ensure your Smart Life account is linked under 'Link Tuya App Account'.")
        sys.exit(3)

    print(f"\n[+] Successfully retrieved {len(devices_res)} device(s) from Tuya Cloud:")
    target_dev = None
    for dev in devices_res:
        name = dev.get("name", "Unknown")
        dev_id = dev.get("id", "")
        key = dev.get("key", "")
        mac = dev.get("mac", "")
        print(f"    - {name} (ID: {dev_id}, MAC: {mac}, Key: {'*' * 12 + key[-4:] if key else 'None'})")
        # Match target
        if "aspirador" in name.lower() or "vacuum" in name.lower() or dev_id == cfg.get("apiDeviceID"):
            target_dev = dev

    if not target_dev and len(devices_res) == 1:
        target_dev = devices_res[0]

    if not target_dev:
        print("[!] Could not automatically determine target vacuum device.")
        sys.exit(4)

    new_id = target_dev.get("id")
    new_key = target_dev.get("key")
    print(f"\n[+] Selected Device: {target_dev.get('name')}")
    print(f"    Device ID : {new_id}")
    print(f"    Local Key : {new_key}")

    if not new_key:
        print("[!] Device did not return a local_key. Check cloud project API permissions.")
        sys.exit(5)

    if not ENV_FILE.exists():
        print(f"[!] {ENV_FILE} does not exist. Please create it from .env.example first.")
        sys.exit(6)

    # Read current .env
    env_text = ENV_FILE.read_text()

    # Update TUYA_DEVICE_ID and TUYA_LOCAL_KEY
    # Use single quotes for LOCAL_KEY to avoid shell expansion of special characters (?, $)
    updated_text = re.sub(r'TUYA_DEVICE_ID=.*', f'TUYA_DEVICE_ID={new_id}', env_text)
    updated_text = re.sub(r'TUYA_LOCAL_KEY=.*', f"TUYA_LOCAL_KEY='{new_key}'", updated_text)

    ENV_FILE.write_text(updated_text)
    print(f"[+] Updated {ENV_FILE} with new credentials.")

    # Test connection
    print("\n[*] Testing local LAN connection to device...")
    # Extract IP
    ip_match = re.search(r'TUYA_DEVICE_IP=([^\s]+)', updated_text)
    device_ip = ip_match.group(1) if ip_match else "192.168.15.65"

    d = tinytuya.Device(new_id, device_ip, new_key)
    d.set_version(3.3)
    d.set_socketTimeout(5)
    st = d.status()
    if isinstance(st, dict) and "dps" in st:
        print("[+] SUCCESS! Local communication confirmed! DPS received:")
        print(f"    Battery (DP 106): {st['dps'].get('106')}% | Status (DP 105): {st['dps'].get('105')}")
        print("\n[+] Done! The cron job collect.sh will now resume collecting automatically.")
    else:
        print(f"[!] Warning: Device status query returned: {st}")
        print("    Verify if the device IP address has changed.")

if __name__ == "__main__":
    main()
