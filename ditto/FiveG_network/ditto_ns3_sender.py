#!/usr/bin/env python3
"""Ditto -> ns-3 sender.

Polls Ditto, drops the latest Things array into a RAM buffer, then nudges
ns-3 with a tiny UDP "UPDATE" packet so it re-reads the buffer.

Improvements over the legacy version:
- Auto-detects the TAP MAC (was hardcoded to one developer's machine).
- Configurable polling frequency via DITTO_POLL_INTERVAL (default 100 ms,
  matches the OMNeT sampling).
- Writes a readiness sentinel (/dev/shm/ditto_buffer.ready) when the first
  buffer write succeeds, so ns-3 can wait before pre-parsing entities.
- Skips signal emission when the buffer hasn't actually changed (saves work).
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time

import requests
from scapy.all import Ether, IP, UDP, Raw, sendp

INTERFACE = os.environ.get("DITTO_TAP_IFACE", "thetap")
TARGET_IP = os.environ.get("DITTO_TARGET_IP", "10.1.1.2")
TARGET_MAC = os.environ.get("DITTO_TARGET_MAC", "00:00:00:00:00:02")
TARGET_PORT = int(os.environ.get("DITTO_TARGET_PORT", "5000"))
SRC_IP = os.environ.get("DITTO_SRC_IP", "10.1.1.10")

DITTO_URL = os.environ.get("DITTO_URL", "http://localhost:8080/api/2/things")
DITTO_USER = os.environ.get("DITTO_USER", "ditto")
DITTO_PASS = os.environ.get("DITTO_PASS", "ditto")
DITTO_PRE_AUTH_SUBJECT = os.environ.get("DITTO_PRE_AUTH_SUBJECT", "")
DITTO_HEADERS = {"x-ditto-pre-authenticated": DITTO_PRE_AUTH_SUBJECT} if DITTO_PRE_AUTH_SUBJECT else {}

RAM_BUFFER_PATH = os.environ.get("DITTO_BUFFER_PATH", "/dev/shm/ditto_buffer.json")
READY_FILE = os.environ.get("DITTO_READY_FILE", "/dev/shm/ditto_buffer.ready")
POLL_INTERVAL = float(os.environ.get("DITTO_POLL_INTERVAL", "0.1"))


def detect_tap_mac(iface: str) -> str:
    """Return the MAC address of `iface`, or raise if it does not exist."""
    try:
        out = subprocess.check_output(["ip", "link", "show", iface], text=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Interface {iface} not found: {exc}") from exc
    m = re.search(r"link/ether\s+([0-9a-f:]{17})", out)
    if not m:
        raise RuntimeError(f"Could not extract MAC from `ip link show {iface}` output")
    return m.group(1)


def fetch_things() -> bytes | None:
    if DITTO_PRE_AUTH_SUBJECT:
        r = requests.get(DITTO_URL, headers=DITTO_HEADERS, timeout=2)
    else:
        r = requests.get(DITTO_URL, auth=(DITTO_USER, DITTO_PASS), timeout=2)
    if r.status_code != 200:
        return None
    return r.content


def signal_ready() -> None:
    try:
        with open(READY_FILE, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def main() -> int:
    try:
        src_mac = detect_tap_mac(INTERFACE)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print(f"=== Ditto -> ns-3 bridge ===")
    print(f"    iface={INTERFACE} src_mac={src_mac} target={TARGET_IP}:{TARGET_PORT}")
    print(f"    poll={POLL_INTERVAL}s url={DITTO_URL}")

    last_hash = None
    ready_signaled = False

    while True:
        try:
            payload = fetch_things()
            if not payload:
                time.sleep(POLL_INTERVAL)
                continue

            digest = hashlib.md5(payload).hexdigest()
            if digest == last_hash:
                time.sleep(POLL_INTERVAL)
                continue

            try:
                json.loads(payload)
            except json.JSONDecodeError:
                time.sleep(POLL_INTERVAL)
                continue

            with open(RAM_BUFFER_PATH, "wb") as f:
                f.write(payload)

            packet = (
                Ether(src=src_mac, dst=TARGET_MAC)
                / IP(src=SRC_IP, dst=TARGET_IP)
                / UDP(sport=54321, dport=TARGET_PORT)
                / Raw(load=b"UPDATE")
            )
            sendp(packet, iface=INTERFACE, verbose=False)

            last_hash = digest
            if not ready_signaled:
                signal_ready()
                ready_signaled = True
            print(f"[{time.strftime('%H:%M:%S')}] Update pushed ({len(payload)} bytes)")

        except Exception as exc:
            print(f"[ERROR] {exc}")
            time.sleep(1.0)
        else:
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
