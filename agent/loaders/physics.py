from __future__ import annotations

import math
import random
from typing import Dict, List, Optional

from ..state import FlowState, NodeState, Snapshot

_FC_GHZ = 3.5
_BW_MHZ = 100.0
_H_GNB  = 25.0
_H_UE   = 1.5
_N0_DBM = -174.0 + 10.0 * math.log10(_BW_MHZ * 1e6)


def _path_loss(d3d: float) -> float:
    if d3d < 1.0:
        d3d = 1.0
    d_bp = 4.0 * _H_GNB * _H_UE * _FC_GHZ * 1e9 / 3e8
    if d3d <= d_bp:
        return 28.0 + 22.0 * math.log10(d3d) + 20.0 * math.log10(_FC_GHZ)
    return (28.0 + 40.0 * math.log10(d3d) + 20.0 * math.log10(_FC_GHZ)
            - 9.0 * math.log10(d_bp ** 2 + (_H_GNB - _H_UE) ** 2))


def _sinr_dl(
    d_serving: float,
    d_interferer: float,
    gnb_tx: float,
    ue_nf: float,
) -> float:
    sig  = 10.0 ** ((gnb_tx - _path_loss(d_serving))   / 10.0)
    intf = 10.0 ** ((gnb_tx - _path_loss(d_interferer)) / 10.0)
    nse  = 10.0 ** ((_N0_DBM + ue_nf)                   / 10.0)
    return max(-20.0, min(30.0, 10.0 * math.log10(sig / (intf + nse))))


def _sinr_dl_isolated(d: float, gnb_tx: float, ue_nf: float) -> float:
    sig = 10.0 ** ((gnb_tx - _path_loss(d)) / 10.0)
    nse = 10.0 ** ((_N0_DBM + ue_nf)        / 10.0)
    return max(-20.0, min(30.0, 10.0 * math.log10(sig / nse)))


def _sinr_ul(d: float, ue_tx: float, gnb_nf: float) -> float:
    sig = 10.0 ** ((ue_tx - _path_loss(d)) / 10.0)
    nse = 10.0 ** ((_N0_DBM + gnb_nf)      / 10.0)
    return max(-20.0, min(35.0, 10.0 * math.log10(sig / nse)))


def _throughput(sinr_db: float, pkt_B: float, interval_ms: float) -> float:
    cap  = _BW_MHZ * 1e6 * math.log2(1.0 + 10.0 ** (sinr_db / 10.0)) * 0.6 / 1e6
    app  = (pkt_B * 8.0) / (interval_ms * 1e-3) / 1e6
    return max(0.0, min(cap, app))


def _delay(sinr_db: float) -> float:
    if sinr_db >= 15.0:
        return 1.7
    if sinr_db >= 5.0:
        return 1.5 + (15.0 - sinr_db) * 0.6
    return 9.5 + abs(sinr_db) * 1.5


def _bler(sinr_db: float) -> float:
    return max(0.0, min(100.0,
                        100.0 / (1.0 + math.exp(2.0 * (sinr_db - 7.5) / 5.0))))


def compute_dt_snapshot(
    action_dict: Dict[str, float],
    ue_dists_m: List[float],
    gnb_sep_m: float = 400.0,
    timestamp: float = 0.0,
    isolated_cells: bool = False,
) -> Snapshot:
    gnb_tx  = float(action_dict.get("ns3_gnb_tx_dbm",      46.0))
    gnb_nf  = float(action_dict.get("ns3_gnb_nf_db",        9.0))
    ue_tx   = float(action_dict.get("ns3_ue_tx_dbm",       23.0))
    ue_nf   = float(action_dict.get("ns3_ue_nf_db",         5.0))
    pkt_B   = float(action_dict.get("ns3_pkt_size_bytes",  512.0))
    int_ms  = float(action_dict.get("ns3_pkt_interval_ms",  80.0))

    snap = Snapshot(timestamp=timestamp)
    for idx, d in enumerate(ue_dists_m):
        uid = f"ue{idx}"
        if isolated_cells:
            sinr_d = _sinr_dl_isolated(d, gnb_tx, ue_nf)
        else:
            d_intf = max(10.0, abs(gnb_sep_m - d))
            sinr_d = _sinr_dl(d, d_intf, gnb_tx, ue_nf)
        sinr_u = _sinr_ul(d, ue_tx, gnb_nf)
        snap.nodes[uid] = NodeState(node_id=uid, sinr_dl=sinr_d, sinr_ul=sinr_u)
        snap.flows[f"gnb0_to_{uid}"] = FlowState(
            src="gnb0",
            dst=uid,
            throughput_mbps=_throughput(sinr_d, pkt_B, int_ms),
            delay_ms=_delay(sinr_d),
            bler_pct=_bler(sinr_d),
        )
    return snap


def random_ue_dists(
    n: int,
    rng: Optional[random.Random] = None,
    d_min: float = 50.0,
    d_max: float = 500.0,
) -> List[float]:
    _rng = rng or random
    return [_rng.uniform(d_min, d_max) for _ in range(n)]
