#!/usr/bin/env python3
"""Simulateur live mock — boucle fermée causale PT/DT pour l'agent DRL.

Ce script remplace OMNeT++/ns-3/Ditto dans les environnements sans
infrastructure simulateur. Il génère en temps réel :
  - PT : Physical Twin avec mobilité UE réaliste (paramètres fixes "vérité terrain")
  - DT : Digital Twin dont les paramètres RF et de trafic sont pilotés par
         les actions de l'agent lues depuis /dev/shm/agent_action.json

La physique utilisée (3GPP TR 38.901 UMa + interférence co-canal) est identique
au script de génération des données synthétiques offline. La différence est que
le DT répond CAUSALEMENT aux actions de l'agent : quand l'agent corrige
ns3_gnb_tx_dbm de 46→43 ou ns3_pkt_size_bytes de 512→1400, les métriques DT
se rapprochent des métriques PT et le reward converge vers 0.

Usage (lancé en arrière-plan avant l'agent) :
    python3 third_party/mock_live_simulator.py &
    python3 -m agent.train --backend live --timesteps 50000 ...

Paramètres PT (vérité terrain) :
    gnb_tx = 43 dBm  gnb_nf = 5 dB  ue_nf = 7 dB
    pkt_size = 1400 B  interval = 10 ms  (1.12 Mbps/flux)

Paramètres DT (initial non calibré, pilotés par l'agent) :
    gnb_tx = 46 dBm  gnb_nf = 9 dB  ue_nf = 5 dB
    pkt_size = 512 B  interval = 80 ms  (0.051 Mbps/flux)
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import random
import signal
import sys
import time
from typing import Dict, List, Optional

# ─── Constantes RF (3GPP TR 38.901 UMa, fc=3.5 GHz, BW=100 MHz) ───────────
FC_GHZ  = 3.5
BW_MHZ  = 100.0
H_GNB   = 25.0
H_UE    = 1.5
N0_DBM  = -174.0 + 10.0 * math.log10(BW_MHZ * 1e6)  # ≈ −94 dBm

# Paramètres PT — vérité terrain, ne changent jamais
PT_PARAMS: Dict[str, float] = {
    "gnb_tx_dbm":    43.0,
    "ue_tx_dbm":     23.0,
    "gnb_nf_db":      5.0,
    "ue_nf_db":       7.0,
    "pkt_size_B":  1400.0,
    "interval_ms":   10.0,
}

# Paramètres DT — état initial (non calibré), remplacés par les actions de l'agent
DT_INITIAL: Dict[str, float] = {
    "gnb_tx_dbm":    46.0,
    "ue_tx_dbm":     23.0,
    "gnb_nf_db":      9.0,
    "ue_nf_db":       5.0,
    "pkt_size_B":   512.0,
    "interval_ms":   80.0,
}


# ─── Modèles physiques ───────────────────────────────────────────────────────

def path_loss(d3d: float) -> float:
    if d3d < 1.0:
        d3d = 1.0
    d_bp = 4.0 * H_GNB * H_UE * FC_GHZ * 1e9 / 3e8
    if d3d <= d_bp:
        return 28.0 + 22.0 * math.log10(d3d) + 20.0 * math.log10(FC_GHZ)
    return (28.0 + 40.0 * math.log10(d3d) + 20.0 * math.log10(FC_GHZ)
            - 9.0 * math.log10(d_bp ** 2 + (H_GNB - H_UE) ** 2))


def dist3d(a: dict, b: dict) -> float:
    return math.sqrt((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2
                     + (a["z"] - b["z"]) ** 2)


def compute_sinr_dl(ue: dict, gnbs: List[dict], gnb_tx: float, ue_nf: float,
                    noise_std: float = 0.3) -> tuple:
    """SINR DL avec interférence co-canal ; renvoie (sinr_db, serving_gnb_id)."""
    rsrps = [gnb_tx - path_loss(dist3d(ue, g)) for g in gnbs]
    best_idx = max(range(len(rsrps)), key=lambda i: rsrps[i])
    sig_lin   = 10.0 ** (rsrps[best_idx] / 10.0)
    intf_lin  = sum(10.0 ** (rsrps[i] / 10.0) for i in range(len(rsrps)) if i != best_idx)
    noise_lin = 10.0 ** ((N0_DBM + ue_nf) / 10.0)
    sinr = 10.0 * math.log10(sig_lin / (intf_lin + noise_lin))
    return max(-20.0, min(30.0, sinr + random.gauss(0, noise_std))), gnbs[best_idx]["id"]


def compute_sinr_ul(ue: dict, serving_gnb: dict, ue_tx: float, gnb_nf: float,
                    noise_std: float = 0.3) -> float:
    """SINR UL sans interférence (un seul émetteur UE)."""
    pl = path_loss(dist3d(ue, serving_gnb))
    sig_lin   = 10.0 ** ((ue_tx - pl) / 10.0)
    noise_lin = 10.0 ** ((N0_DBM + gnb_nf) / 10.0)
    sinr = 10.0 * math.log10(sig_lin / noise_lin)
    return max(-20.0, min(35.0, sinr + random.gauss(0, noise_std)))


def throughput_mbps(sinr_db: float, pkt_B: float, interval_ms: float,
                    eff: float = 0.6) -> float:
    """min(capacité Shannon × eff, débit applicatif)."""
    cap = (BW_MHZ * 1e6 * math.log2(1.0 + 10.0 ** (sinr_db / 10.0)) / 1e6) * eff
    app = (pkt_B * 8.0) / (interval_ms * 1e-3) / 1e6
    return max(0.0, min(cap, app) + random.gauss(0, 0.02 * app))


def delay_ms(sinr_db: float, load_factor: float = 1.0) -> float:
    base = 1.5 * load_factor
    if sinr_db >= 15.0:
        return base + abs(random.gauss(0.2, 0.1))
    if sinr_db >= 5.0:
        return base + (15.0 - sinr_db) * 0.6 * load_factor + abs(random.gauss(0, 0.2))
    return base + 8.0 * load_factor + abs(sinr_db) * 1.5 + abs(random.gauss(0, 0.5))


def bler_pct(sinr_db: float) -> float:
    v = 100.0 / (1.0 + math.exp(2.0 * (sinr_db - 7.5) / 5.0))
    return max(0.0, min(100.0, v + random.gauss(0, 0.3)))


# ─── Topologie 2 gNB + 10 UE ────────────────────────────────────────────────

GNBS = [
    {"id": "gnb0", "x": 300.0, "y": 500.0, "z": H_GNB},
    {"id": "gnb1", "x": 700.0, "y": 500.0, "z": H_GNB},
]

UES_INIT = [
    {"id": "ue0",  "x": 200.0, "y": 520.0, "z": H_UE, "speed": 2.0,  "mob": "linear",  "vx":  1.4, "vy":  1.4},
    {"id": "ue1",  "x": 380.0, "y": 640.0, "z": H_UE, "speed": 2.0,  "mob": "linear",  "vx": -1.4, "vy":  1.4},
    {"id": "ue2",  "x": 140.0, "y": 460.0, "z": H_UE, "speed": 2.0,  "mob": "linear",  "vx":  2.0, "vy":  0.0},
    {"id": "ue3",  "x": 360.0, "y": 310.0, "z": H_UE, "speed": 8.0,  "mob": "gauss",   "vx":  5.6, "vy":  5.6},
    {"id": "ue4",  "x": 500.0, "y": 500.0, "z": H_UE, "speed": 8.0,  "mob": "gauss",   "vx": -5.6, "vy":  5.6},
    {"id": "ue5",  "x": 640.0, "y": 690.0, "z": H_UE, "speed": 8.0,  "mob": "gauss",   "vx":  5.6, "vy": -5.6},
    {"id": "ue6",  "x": 150.0, "y": 250.0, "z": H_UE, "speed": 12.0, "mob": "rwp",     "vx":  8.5, "vy":  8.5},
    {"id": "ue7",  "x": 820.0, "y": 750.0, "z": H_UE, "speed": 12.0, "mob": "rwp",     "vx": -8.5, "vy": -8.5},
    {"id": "ue8",  "x": 490.0, "y": 500.0, "z": H_UE, "speed": 10.0, "mob": "linear",  "vx": 10.0, "vy":  0.0},
    {"id": "ue9",  "x": 500.0, "y": 500.0, "z": H_UE, "speed": 0.0,  "mob": "static",  "vx":  0.0, "vy":  0.0},
]


def step_ue(ue: dict, dt: float = 0.1) -> None:
    if ue["mob"] == "static":
        return
    ue["x"] += ue["vx"] * dt
    ue["y"] += ue["vy"] * dt
    for axis, vk, lo, hi in [("x", "vx", 0.0, 1000.0), ("y", "vy", 0.0, 1000.0)]:
        if not (lo <= ue[axis] <= hi):
            ue[vk] = -ue[vk]
            ue[axis] = max(lo, min(hi, ue[axis]))
    if ue["mob"] == "rwp" and random.random() < 0.015:
        a = random.uniform(0, 2 * math.pi)
        s = ue["speed"]
        ue["vx"] = s * math.cos(a)
        ue["vy"] = s * math.sin(a)


def make_snapshot(timestamp: float, ues: List[dict], gnbs: List[dict],
                  params: Dict[str, float], noise_std: float = 0.3) -> dict:
    nodes, flows = [], []
    for g in gnbs:
        nodes.append({"id": g["id"], "x": round(g["x"], 2), "y": round(g["y"], 2),
                      "z": round(g["z"], 2), "speed": 0.0,
                      "serving_gnb": "none", "sinr_dl": -999.0, "sinr_ul": -999.0})
    for ue in ues:
        sdl, srv_id = compute_sinr_dl(ue, gnbs, params["gnb_tx_dbm"], params["ue_nf_db"], noise_std)
        srv_gnb = next(g for g in gnbs if g["id"] == srv_id)
        sul = compute_sinr_ul(ue, srv_gnb, params["ue_tx_dbm"], params["gnb_nf_db"], noise_std)
        nodes.append({"id": ue["id"], "x": round(ue["x"], 2), "y": round(ue["y"], 2),
                      "z": round(ue["z"], 2), "speed": round(ue["speed"], 2),
                      "serving_gnb": srv_id, "sinr_dl": round(sdl, 4), "sinr_ul": round(sul, 4)})
        load = (params["pkt_size_B"] * 8.0) / (params["interval_ms"] * 1e-3) / 1e6 / 800.0
        thr = throughput_mbps(sdl, params["pkt_size_B"], params["interval_ms"])
        dly = delay_ms(sdl, load_factor=max(0.1, load))
        bl  = bler_pct(sdl)
        flows.append({"type": "DL", "src": "server", "dst": ue["id"],
                      "throughput": round(thr, 4), "delay": round(dly, 4),
                      "bler": round(bl, 4), "packet_loss": round(bl / 100.0 * 0.8, 4)})
    return {"timestamp": round(timestamp, 3), "nodes": nodes, "flows": flows}


def read_agent_action(action_path: str, current: Dict[str, float]) -> Dict[str, float]:
    """Lit l'action de l'agent et la mappe sur les paramètres physiques DT."""
    try:
        with open(action_path, "r") as f:
            data = json.load(f)
        a = data.get("action", {})
        params = dict(current)
        if "ns3_gnb_tx_dbm"    in a: params["gnb_tx_dbm"]  = float(a["ns3_gnb_tx_dbm"])
        if "ns3_ue_tx_dbm"     in a: params["ue_tx_dbm"]   = float(a["ns3_ue_tx_dbm"])
        if "ns3_gnb_nf_db"     in a: params["gnb_nf_db"]   = float(a["ns3_gnb_nf_db"])
        if "ns3_ue_nf_db"      in a: params["ue_nf_db"]    = float(a["ns3_ue_nf_db"])
        if "ns3_pkt_size_bytes" in a: params["pkt_size_B"]  = float(a["ns3_pkt_size_bytes"])
        if "ns3_pkt_interval_ms" in a: params["interval_ms"] = float(a["ns3_pkt_interval_ms"])
        return params
    except Exception:
        return current


def write_history(path: str, snap: dict) -> None:
    """Écrit le snapshot comme liste JSON (format attendu par load_snapshot_history)."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump([snap], f)
    os.replace(tmp, path)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--pt-out",     default="omnet/FiveG_network/simulations/network_state.json")
    p.add_argument("--dt-out",     default="ns3/FiveG_digital_twin/ns3_received_history.json")
    p.add_argument("--action-in",  default="/dev/shm/agent_action.json")
    p.add_argument("--step-s",     type=float, default=0.12,
                   help="Pas de simulation (secondes). 0 = aussi vite que possible.")
    p.add_argument("--seed",       type=int, default=42)
    p.add_argument("--verbose",    action="store_true")
    args = p.parse_args()

    random.seed(args.seed)

    # Créer les dossiers si nécessaire
    for path in [args.pt_out, args.dt_out]:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    ues = copy.deepcopy(UES_INIT)
    dt_params = dict(DT_INITIAL)
    t = 0.0
    step_count = 0

    # Signal handler pour arrêt propre
    running = [True]
    def _stop(sig, frame):
        running[0] = False
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT,  _stop)

    print(f"[MOCK] PT: gnb_tx={PT_PARAMS['gnb_tx_dbm']} dBm, "
          f"gnb_nf={PT_PARAMS['gnb_nf_db']} dB, pkt={PT_PARAMS['pkt_size_B']}B@{PT_PARAMS['interval_ms']}ms")
    print(f"[MOCK] DT initial: gnb_tx={DT_INITIAL['gnb_tx_dbm']} dBm, "
          f"gnb_nf={DT_INITIAL['gnb_nf_db']} dB, pkt={DT_INITIAL['pkt_size_B']}B@{DT_INITIAL['interval_ms']}ms")
    print(f"[MOCK] PT → {args.pt_out}")
    print(f"[MOCK] DT → {args.dt_out}")
    print(f"[MOCK] Actions ← {args.action_in}")
    print("[MOCK] Démarrage de la boucle de simulation…")

    while running[0]:
        t_start = time.time()

        # 1. Avancer la mobilité
        for ue in ues:
            step_ue(ue, dt=0.1)

        # 2. Générer snapshot PT (paramètres fixes)
        pt_snap = make_snapshot(t, ues, GNBS, PT_PARAMS, noise_std=0.3)
        write_history(args.pt_out, pt_snap)

        # 3. Lire action agent → mettre à jour paramètres DT
        dt_params = read_agent_action(args.action_in, dt_params)

        # 4. Générer snapshot DT avec paramètres courants
        dt_snap = make_snapshot(t, ues, GNBS, dt_params, noise_std=0.35)
        write_history(args.dt_out, dt_snap)

        t += 0.1
        step_count += 1

        if args.verbose and step_count % 50 == 0:
            # Afficher une métrique représentative
            ue0_pt = next(n for n in pt_snap["nodes"] if n["id"] == "ue0")
            ue0_dt = next(n for n in dt_snap["nodes"] if n["id"] == "ue0")
            fl_pt  = next(f for f in pt_snap["flows"]  if f["dst"] == "ue0")
            fl_dt  = next(f for f in dt_snap["flows"]  if f["dst"] == "ue0")
            print(f"[MOCK t={t:.1f}s] ue0 SINR_DL PT={ue0_pt['sinr_dl']:.1f} "
                  f"DT={ue0_dt['sinr_dl']:.1f} | "
                  f"Thr PT={fl_pt['throughput']:.3f} DT={fl_dt['throughput']:.3f} Mbps | "
                  f"DT gnb_tx={dt_params['gnb_tx_dbm']:.1f} "
                  f"pkt={dt_params['pkt_size_B']:.0f}B@{dt_params['interval_ms']:.0f}ms")

        elapsed = time.time() - t_start
        if args.step_s > 0 and elapsed < args.step_s:
            time.sleep(args.step_s - elapsed)

    print(f"[MOCK] Arrêt après {step_count} steps (t={t:.1f}s simulés)")


if __name__ == "__main__":
    main()
