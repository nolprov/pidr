#!/usr/bin/env python3
"""Evaluate fidelity (PT vs DT) and emit a small report.

Outputs into the chosen results directory:
  - fidelity_report.json: per-metric mean/median/p90 absolute error
  - fidelity_report.md:   human-readable summary, ready to drop in slides

Designed to run twice (before/after training) and compare; the markdown
also includes a one-line delta if a previous report is found.
"""
from __future__ import annotations

import argparse
import json
import os
from statistics import mean, median
from typing import Dict, List

from .state import load_snapshot_history


def percentile(xs: List[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = int(round(q * (len(s) - 1)))
    return s[k]


def collect_errors(pt_path: str, dt_path: str) -> Dict[str, List[float]]:
    pt = load_snapshot_history(pt_path)
    dt = load_snapshot_history(dt_path)
    errors: Dict[str, List[float]] = {
        "sinr_dl_db": [],
        "sinr_ul_db": [],
        "throughput_mbps": [],
        "delay_ms": [],
        "bler_pct": [],
    }
    n = min(len(pt), len(dt))
    for i in range(n):
        for nid, p_node in pt[i].nodes.items():
            d_node = dt[i].nodes.get(nid)
            if not d_node:
                continue
            if p_node.sinr_dl > -900 and d_node.sinr_dl > -900:
                errors["sinr_dl_db"].append(abs(p_node.sinr_dl - d_node.sinr_dl))
            if p_node.sinr_ul > -900 and d_node.sinr_ul > -900:
                errors["sinr_ul_db"].append(abs(p_node.sinr_ul - d_node.sinr_ul))
        for fid, p_flow in pt[i].flows.items():
            d_flow = dt[i].flows.get(fid)
            if not d_flow:
                continue
            errors["throughput_mbps"].append(abs(p_flow.throughput_mbps - d_flow.throughput_mbps))
            errors["delay_ms"].append(abs(p_flow.delay_ms - d_flow.delay_ms))
            errors["bler_pct"].append(abs(p_flow.bler_pct - d_flow.bler_pct))
    return errors


def summarize(errors: Dict[str, List[float]]) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for k, v in errors.items():
        out[k] = {
            "n": len(v),
            "mean": mean(v) if v else 0.0,
            "median": median(v) if v else 0.0,
            "p90": percentile(v, 0.9),
            "max": max(v) if v else 0.0,
        }
    return out


def render_markdown(summary: Dict[str, Dict[str, float]], previous: Dict[str, Dict[str, float]] | None) -> str:
    lines = ["# Digital Twin fidelity report", ""]
    lines.append("| Metric | n | mean | median | p90 | max | Δ mean vs previous |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for metric, stats in summary.items():
        prev_mean = previous.get(metric, {}).get("mean") if previous else None
        delta = ""
        if prev_mean is not None:
            d = stats["mean"] - prev_mean
            delta = f"{d:+.3f}"
        lines.append(
            f"| {metric} | {stats['n']} | {stats['mean']:.3f} | {stats['median']:.3f} | "
            f"{stats['p90']:.3f} | {stats['max']:.3f} | {delta} |"
        )
    lines.append("")
    lines.append("Lower is better. Mean reward in the env equals the negative weighted sum of these means.")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pt", default="omnet/FiveG_network/simulations/network_state.json")
    p.add_argument("--dt", default="ns3/FiveG_digital_twin/ns3_received_history.json")
    p.add_argument("--results-dir", default="results")
    args = p.parse_args()

    os.makedirs(args.results_dir, exist_ok=True)
    errors = collect_errors(args.pt, args.dt)
    summary = summarize(errors)

    report_json = os.path.join(args.results_dir, "fidelity_report.json")
    previous = None
    if os.path.exists(report_json):
        try:
            with open(report_json, "r", encoding="utf-8") as f:
                previous = json.load(f)
        except json.JSONDecodeError:
            previous = None

    with open(report_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    md_path = os.path.join(args.results_dir, "fidelity_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(summary, previous))

    print(f"[ok] {report_json}")
    print(f"[ok] {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
