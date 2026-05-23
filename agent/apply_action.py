#!/usr/bin/env python3
"""Apply the agent's best action to the live ns-3 / OMNeT++ source files.

This is a thin wrapper over scripts/tune_network_params.py — it reads the JSON
emitted by the trainer (results/best_action.json) and forwards the matching
flags. Useful for the post-training "deployment" step shown in the demo.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Dict


def _to_flag(name: str, value: float) -> list[str]:
    mapping = {
        "ns3_gnb_tx_dbm":  ("--ns3-gnb-tx", f"{value:.2f}"),
        "ns3_ue_tx_dbm":   ("--ns3-ue-tx",  f"{value:.2f}"),
        "ns3_gnb_nf_db":   ("--ns3-gnb-nf", f"{value:.2f}"),
        "ns3_ue_nf_db":    ("--ns3-ue-nf",  f"{value:.2f}"),
    }
    if name in mapping:
        flag, val = mapping[name]
        return [flag, val]
    # snapshot interval cannot be tuned by the legacy script; we ignore it here
    return []


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--action-file", default="results/best_action.json")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if not os.path.exists(args.action_file):
        print(f"[ERROR] Missing {args.action_file}; run agent/train.py first.", file=sys.stderr)
        return 2

    with open(args.action_file, "r", encoding="utf-8") as f:
        payload = json.load(f)
    action: Dict[str, float] = payload.get("action", {})
    if not action:
        print("[ERROR] Empty action; nothing to apply.", file=sys.stderr)
        return 2

    cmd = [sys.executable, "scripts/tune_network_params.py"]
    if args.dry_run:
        cmd.append("--dry-run")
    for name, value in action.items():
        cmd.extend(_to_flag(name, float(value)))

    print(f"[*] Applying agent action: {action}")
    print(f"    -> {' '.join(cmd)}")
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
