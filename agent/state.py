from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class NodeState:
    node_id: str
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    speed: float = 0.0
    sinr_dl: float = -999.0
    sinr_ul: float = -999.0
    serving_gnb: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "NodeState":
        return cls(
            node_id=str(d.get("id", "")),
            x=float(d.get("x", 0.0)),
            y=float(d.get("y", 0.0)),
            z=float(d.get("z", 0.0)),
            speed=float(d.get("speed", 0.0)),
            sinr_dl=float(d.get("sinr_dl", -999.0)),
            sinr_ul=float(d.get("sinr_ul", -999.0)),
            serving_gnb=str(d.get("serving_gnb", "")),
        )


@dataclass
class FlowState:
    src: str
    dst: str
    flow_type: str = ""
    throughput_mbps: float = 0.0
    delay_ms: float = 0.0
    bler_pct: float = 0.0
    packet_loss: float = 0.0

    @classmethod
    def from_dict(cls, d: dict) -> "FlowState":
        return cls(
            src=str(d.get("src", "")),
            dst=str(d.get("dst", "")),
            flow_type=str(d.get("type", "")),
            throughput_mbps=float(d.get("throughput", 0.0)),
            delay_ms=float(d.get("delay", 0.0)),
            bler_pct=float(d.get("bler", 0.0)),
            packet_loss=float(d.get("packet_loss", 0.0)),
        )


@dataclass
class Snapshot:
    timestamp: float = 0.0
    nodes: Dict[str, NodeState] = field(default_factory=dict)
    flows: Dict[str, FlowState] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "Snapshot":
        snap = cls(timestamp=float(d.get("timestamp", 0.0)))
        for raw_node in d.get("nodes", []) or []:
            n = NodeState.from_dict(raw_node)
            if n.node_id:
                snap.nodes[n.node_id] = n
        for raw_flow in d.get("flows", []) or []:
            f = FlowState.from_dict(raw_flow)
            key = f"{f.src}_to_{f.dst}"
            snap.flows[key] = f
        return snap


def load_snapshot_history(path: str) -> List[Snapshot]:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return [Snapshot.from_dict(s) for s in data if isinstance(s, dict)]
    if isinstance(data, dict):
        return [Snapshot.from_dict(data)]
    return []


def latest_snapshot(path: str) -> Optional[Snapshot]:
    history = load_snapshot_history(path)
    return history[-1] if history else None
