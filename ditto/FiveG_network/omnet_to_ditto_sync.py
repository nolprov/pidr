#!/usr/bin/env python3
"""OMNeT++ -> Ditto bridge.

Reads the latest OMNeT++ snapshot (network_state.json) and pushes a normalized
copy into Ditto. Normalization is critical because:

- OMNeT emits MAC throughput in bits/s, ns-3 stores it in Mbps. We unify to Mbps.
- OMNeT emits delay in seconds, ns-3 stores it in ms. We unify to ms.
- OMNeT emits BLER as a ratio [0..1], ns-3 stores it as a percent. We unify to percent.
- OMNeT IDs use brackets (ue[0]); Ditto Thing IDs do not. We strip them.

Both PT and DT therefore read identical units from Ditto.
"""

import json
import os
import re
import time
from hashlib import sha256

import requests
from requests.auth import HTTPBasicAuth

DITTO_URL = os.environ.get("DITTO_URL", "http://localhost:8080/api/2/things")
DITTO_USER = os.environ.get("DITTO_USER", "ditto")
DITTO_PASS = os.environ.get("DITTO_PASS", "ditto")
DITTO_PRE_AUTH_SUBJECT = os.environ.get("DITTO_PRE_AUTH_SUBJECT", "")
NAMESPACE = os.environ.get("DITTO_NAMESPACE", "my5GNetwork")
OMNET_STATE_FILE = os.environ.get(
    "OMNET_STATE_FILE",
    os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "omnet",
            "FiveG_network",
            "simulations",
            "network_state.json",
        )
    ),
)
POLL_INTERVAL = float(os.environ.get("OMNET_POLL_INTERVAL", "0.1"))
READY_FILE = os.environ.get("DITTO_READY_FILE", "/dev/shm/ditto_buffer.ready")

AUTH = None if DITTO_PRE_AUTH_SUBJECT else HTTPBasicAuth(DITTO_USER, DITTO_PASS)
HEADERS = {"x-ditto-pre-authenticated": DITTO_PRE_AUTH_SUBJECT} if DITTO_PRE_AUTH_SUBJECT else {}


def normalize_node_name(name: str) -> str:
    name = (name or "").strip()
    m = re.match(r"^([a-zA-Z_]+)\[(\d+)\]$", name)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    return name


def thing_id(entity_id: str) -> str:
    return f"{NAMESPACE}:{entity_id}"


def normalize_node(node: dict) -> dict:
    """OMNeT node -> Ditto attributes (already in coherent units)."""
    out = dict(node)
    raw_serving = str(out.get("serving_gnb", "")).strip()
    m = re.match(r"^gnb(\d+)$", raw_serving)
    if m:
        out["serving_gnb"] = f"gnb{m.group(1)}"
    return out


def normalize_flow(flow: dict) -> dict:
    """OMNeT flow -> Ditto attributes.

    Unit conversion (bits/s -> Mbps, s -> ms, ratio -> percent) is applied
    at the source in DTConnector.cc, so the JSON snapshot is already
    PT/DT-aligned. Here we only normalize the IDs.
    """
    out = dict(flow)
    out["src"] = normalize_node_name(str(out.get("src", "unknown")))
    out["dst"] = normalize_node_name(str(out.get("dst", "unknown")))
    return out


def put_thing(entity_id: str, attributes: dict) -> None:
    url = f"{DITTO_URL}/{thing_id(entity_id)}"
    response = requests.put(url, json={"attributes": attributes}, auth=AUTH, headers=HEADERS, timeout=3)
    if response.status_code not in (200, 201, 204):
        raise RuntimeError(f"Ditto update failed for {entity_id}: {response.status_code} {response.text}")


def load_latest_snapshot(path: str):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        return None
    if isinstance(data, list) and data:
        return data[-1]
    if isinstance(data, dict):
        return data
    return None


def sync_snapshot(snapshot: dict) -> tuple[int, int]:
    nodes = snapshot.get("nodes", [])
    flows = snapshot.get("flows", [])

    node_count = 0
    flow_count = 0

    for node in nodes:
        node_id = normalize_node_name(str(node.get("id", "")))
        if not node_id:
            continue
        put_thing(node_id, normalize_node(node))
        node_count += 1

    for flow in flows:
        normalized = normalize_flow(flow)
        flow_id = f"{normalized['src']}_to_{normalized['dst']}"
        put_thing(flow_id, normalized)
        flow_count += 1

    return node_count, flow_count


def signal_ready() -> None:
    try:
        with open(READY_FILE, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def main() -> None:
    print("[*] OMNeT->Ditto sync starting")
    print(f"    state file: {OMNET_STATE_FILE}")
    print(f"    Ditto URL:  {DITTO_URL}")

    last_sig = None
    ready_signaled = False

    while True:
        try:
            snapshot = load_latest_snapshot(OMNET_STATE_FILE)
            if not snapshot:
                time.sleep(POLL_INTERVAL)
                continue

            sig_payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
            sig = sha256(sig_payload.encode("utf-8")).hexdigest()

            if sig != last_sig:
                nodes, flows = sync_snapshot(snapshot)
                ts = snapshot.get("timestamp", "?")
                print(f"[SYNC] t={ts} | nodes={nodes} flows={flows}")
                last_sig = sig
                if not ready_signaled and nodes > 0:
                    signal_ready()
                    ready_signaled = True

        except Exception as exc:
            print(f"[ERROR] {exc}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
