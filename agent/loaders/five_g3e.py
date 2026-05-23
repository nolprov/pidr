from __future__ import annotations

import glob
import json
import math
import os
from typing import List, Optional, Tuple

from ..state import FlowState, NodeState, Snapshot

_FC_GHZ  = 3.5
_BW_MHZ  = 100.0
_H_GNB   = 25.0
_H_UE    = 1.5
_N0_DBM  = -174.0 + 10.0 * math.log10(_BW_MHZ * 1e6)

_DT_GNB_TX  = 46.0
_DT_GNB_NF  = 9.0
_DT_UE_TX   = 23.0
_DT_UE_NF   = 5.0
_DT_PKT_B   = 512.0
_DT_INT_MS  = 80.0

_DT_UE_DIST_M = [80.0, 150.0, 250.0, 350.0, 450.0]

_SINR_CAP = 25.0


def _path_loss(d: float) -> float:
    if d < 1.0:
        d = 1.0
    d_bp = 4.0 * _H_GNB * _H_UE * _FC_GHZ * 1e9 / 3e8
    if d <= d_bp:
        return 28.0 + 22.0 * math.log10(d) + 20.0 * math.log10(_FC_GHZ)
    return (28.0 + 40.0 * math.log10(d) + 20.0 * math.log10(_FC_GHZ)
            - 9.0 * math.log10(d_bp ** 2 + (_H_GNB - _H_UE) ** 2))


def _dt_sinr_ul(dist_m: float) -> float:
    pl  = _path_loss(dist_m)
    sig = 10.0 ** ((_DT_UE_TX - pl) / 10.0)
    nse = 10.0 ** ((_N0_DBM + _DT_GNB_NF) / 10.0)
    return max(-20.0, min(35.0, 10.0 * math.log10(sig / nse)))


def _dt_sinr_dl(dist_m: float) -> float:
    pl  = _path_loss(dist_m)
    sig = 10.0 ** ((_DT_GNB_TX - pl) / 10.0)
    nse = 10.0 ** ((_N0_DBM + _DT_UE_NF) / 10.0)
    return max(-20.0, min(30.0, 10.0 * math.log10(sig / nse)))


def _dt_throughput() -> float:
    return (_DT_PKT_B * 8.0) / (_DT_INT_MS * 1e-3) / 1e6


def _dt_delay_ms(sinr_db: float) -> float:
    if sinr_db >= 15.0:
        return 1.7
    if sinr_db >= 5.0:
        return 1.5 + (15.0 - sinr_db) * 0.6
    return 9.5 + abs(sinr_db) * 1.5


def _dt_bler_pct(sinr_db: float) -> float:
    return max(0.0, min(100.0,
                        100.0 / (1.0 + math.exp(2.0 * (sinr_db - 7.5) / 5.0))))


def _cqi_to_sinr_dl(cqi: float) -> float:
    return -6.0 + (cqi / 15.0) * 31.0


def _make_dt_snapshot(timestamp: float = 0.0) -> Snapshot:
    snap = Snapshot(timestamp=timestamp)
    for idx, dist in enumerate(_DT_UE_DIST_M):
        uid       = f"ue{idx}"
        sinr_dl   = _dt_sinr_dl(dist)
        sinr_ul   = _dt_sinr_ul(dist)
        snap.nodes[uid] = NodeState(node_id=uid, sinr_dl=sinr_dl, sinr_ul=sinr_ul)
        snap.flows[f"gnb0_to_{uid}"] = FlowState(
            src="gnb0",
            dst=uid,
            throughput_mbps=_dt_throughput(),
            delay_ms=_dt_delay_ms(sinr_dl),
            bler_pct=_dt_bler_pct(sinr_dl),
        )
    return snap


def load_gnb_v2(
    gnb_jsonl_path: str,
    max_snapshots: Optional[int] = None,
) -> Tuple[List[Snapshot], List[Snapshot]]:
    pt_history: List[Snapshot] = []
    dt_history: List[Snapshot] = []

    with open(gnb_jsonl_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if max_snapshots is not None and len(pt_history) >= max_snapshots:
                break

            entry    = json.loads(line)
            ue_list  = entry.get("ue_list", [])
            if not ue_list:
                continue

            ts      = float(entry["timestamp"])
            lat_ms  = entry["cell_metrics"]["average_latency"] / 1000.0

            pt_snap = Snapshot(timestamp=ts)
            for idx, ue_dict in enumerate(ue_list):
                uid = f"ue{idx}"
                ue  = ue_dict["ue_container"]

                sinr_dl = min(_cqi_to_sinr_dl(float(ue.get("cqi", 0))), _SINR_CAP)
                sinr_ul = min(float(ue.get("pusch_snr_db", -999.0)), _SINR_CAP)
                pt_snap.nodes[uid] = NodeState(node_id=uid, sinr_dl=sinr_dl, sinr_ul=sinr_ul)

                dl_brate = float(ue.get("dl_brate", 0.0))
                dl_ok    = int(ue.get("dl_nof_ok",  0))
                dl_nok   = int(ue.get("dl_nof_nok", 0))
                bler     = (dl_nok / (dl_ok + dl_nok) * 100.0) if (dl_ok + dl_nok) > 0 else 0.0
                pt_snap.flows[f"gnb0_to_{uid}"] = FlowState(
                    src="gnb0",
                    dst=uid,
                    throughput_mbps=dl_brate / 1e6,
                    delay_ms=lat_ms,
                    bler_pct=bler,
                )

            pt_history.append(pt_snap)
            dt_history.append(_make_dt_snapshot(ts))

    return pt_history, dt_history


def load_site_v2(
    site_dir: str,
    max_snapshots_per_gnb: Optional[int] = None,
) -> Tuple[List[Snapshot], List[Snapshot]]:
    pattern = os.path.join(site_dir, "Sample_gnb*_metrics_*.json")
    gnb_files = sorted(glob.glob(pattern))
    if not gnb_files:
        pattern2 = os.path.join(site_dir, "gnb*.json")
        gnb_files = sorted(glob.glob(pattern2))
    if not gnb_files:
        raise FileNotFoundError(f"No gNB JSONL files found in {site_dir!r}")

    all_pt: List[Snapshot] = []
    all_dt: List[Snapshot] = []
    for path in gnb_files:
        pt, dt = load_gnb_v2(path, max_snapshots=max_snapshots_per_gnb)
        all_pt.extend(pt)
        all_dt.extend(dt)

    return all_pt, all_dt


def load_all_sites_v2(
    ran_dir: str,
    max_snapshots_per_gnb: Optional[int] = None,
) -> Tuple[List[Snapshot], List[Snapshot]]:
    all_pt: List[Snapshot] = []
    all_dt: List[Snapshot] = []
    for site in sorted(os.listdir(ran_dir)):
        site_path = os.path.join(ran_dir, site)
        if not os.path.isdir(site_path):
            continue
        try:
            pt, dt = load_site_v2(site_path, max_snapshots_per_gnb)
            all_pt.extend(pt)
            all_dt.extend(dt)
        except FileNotFoundError:
            continue
    return all_pt, all_dt
