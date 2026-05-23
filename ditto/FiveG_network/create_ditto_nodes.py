import json
import os

import requests
from requests.auth import HTTPBasicAuth

URL = os.environ.get("DITTO_URL", "http://localhost:8080/api/2/things")
PRE_AUTH_SUBJECT = os.environ.get("DITTO_PRE_AUTH_SUBJECT", "")
AUTH = None if PRE_AUTH_SUBJECT else HTTPBasicAuth(
  os.environ.get("DITTO_USER", "devops"),
  os.environ.get("DITTO_PASS", "foobar"),
)
HEADERS = {"x-ditto-pre-authenticated": PRE_AUTH_SUBJECT} if PRE_AUTH_SUBJECT else {}
NS = os.environ.get("DITTO_NAMESPACE", "my5GNetwork")
DEFAULT_TOPOLOGY_FILE = os.path.join(os.path.dirname(__file__), "ditto_topology.json")
TOPOLOGY_FILE = os.environ.get("DITTO_TOPOLOGY_FILE", DEFAULT_TOPOLOGY_FILE)

data = {
    "nodes": [
        {"id": "ue0", "x": 0, "y": 0, "z": 0, "speed": 0, "serving_gnb": "nan", "sinr_dl": -999, "sinr_ul": -999, "sinr_d2d": -999},
        {"id": "ue1", "x": 0, "y": 0, "z": 0, "speed": 0, "serving_gnb": "nan", "sinr_dl": -999, "sinr_ul": -999, "sinr_d2d": -999},
        {"id": "ue2", "x": 0, "y": 0, "z": 0, "speed": 0, "serving_gnb": "nan", "sinr_dl": -999, "sinr_ul": -999, "sinr_d2d": -999},
        {"id": "ue3", "x": 0, "y": 0, "z": 0, "speed": 0, "serving_gnb": "nan", "sinr_dl": -999, "sinr_ul": -999, "sinr_d2d": -999},
        {"id": "gnb0", "x": 0, "y": 0, "z": 0, "speed": 0, "serving_gnb": "gnb0", "sinr_dl": -999, "sinr_ul": -999, "sinr_d2d": -999},
    ],
    "flows": [
        {"type": "nan", "src": "server", "dst": "ue0", "packet_size": 0, "interval": 0, "throughput": 0, "delay": 0, "bler": 0, "packet_loss": 0},
        {"type": "nan", "src": "server", "dst": "ue1", "packet_size": 0, "interval": 0, "throughput": 0, "delay": 0, "bler": 0, "packet_loss": 0},
        {"type": "nan", "src": "server", "dst": "ue2", "packet_size": 0, "interval": 0, "throughput": 0, "delay": 0, "bler": 0, "packet_loss": 0},
        {"type": "nan", "src": "server", "dst": "ue3", "packet_size": 0, "interval": 0, "throughput": 0, "delay": 0, "bler": 0, "packet_loss": 0},
    ],
}

if os.path.isfile(TOPOLOGY_FILE):
    try:
        with open(TOPOLOGY_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict) and "nodes" in loaded and "flows" in loaded:
            data = loaded
    except json.JSONDecodeError:
        pass


def put_with_retry(url, payload, retries=20, delay=1.0):
    last_exc = None
    for _ in range(retries):
        try:
            res = requests.put(url, json=payload, auth=AUTH, headers=HEADERS, timeout=5)
            if res.status_code in (200, 201, 204):
                return res
            last_exc = RuntimeError(f"HTTP {res.status_code}: {res.text}")
        except Exception as exc:
            last_exc = exc
        import time
        time.sleep(delay)
    raise RuntimeError(f"Failed to PUT {url}: {last_exc}")

# Création des Nodes
for node in data["nodes"]:
    t_id = f"{NS}:{node['id']}"
    # On balance tout le dictionnaire node directement dans attributes
    payload = {"attributes": node}
    res = put_with_retry(f"{URL}/{t_id}", payload)
    print(f"Node {t_id}: {res.status_code}")

# Création des Flows
for flow in data["flows"]:
    # Nettoyage rapide des noms et création ID
    src, dst = flow['src'].strip("[]"), flow['dst'].strip("[]")
    t_id = f"{NS}:{src}_to_{dst}"
    # Pareil, tout à plat dans attributes
    payload = {"attributes": flow}
    res = put_with_retry(f"{URL}/{t_id}", payload)
    print(f"Flow {t_id}: {res.status_code}")