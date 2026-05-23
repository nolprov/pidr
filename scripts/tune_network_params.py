#!/usr/bin/env python3
import argparse
import json
import os
import random
import re
import sys
from typing import Dict, List, Optional, Tuple


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def find_insert_index(text: str) -> int:
    m = re.search(r"^\[Config[^\]]*\]", text, flags=re.MULTILINE)
    if m:
        return m.end()
    m = re.search(r"^\[General\]", text, flags=re.MULTILINE)
    if m:
        return m.end()
    return 0


def update_or_insert(
    text: str,
    patterns: List[re.Pattern],
    new_line: str,
    allow_insert: bool,
) -> Tuple[str, int]:
    count = 0
    for pat in patterns:
        def _repl(match: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{match.group('prefix')}{new_line}"

        text = pat.sub(_repl, text)
    if count == 0 and allow_insert:
        idx = find_insert_index(text)
        insert = "\n" + new_line
        text = text[:idx] + insert + text[idx:]
        count = 1
    return text, count


def update_simple_key(
    text: str,
    key_regex: str,
    value: str,
    allow_insert: bool = True,
) -> Tuple[str, int]:
    patterns = [
        re.compile(rf"^(?P<prefix>\s*{key_regex}\s*=\s*).*$", re.MULTILINE)
    ]
    return update_or_insert(text, patterns, f"{key_regex} = {value}", allow_insert)


def fmt_ini_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if value.startswith('"') and value.endswith('"'):
        return value
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", value):
        return f"\"{value}\""
    return value


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Tune OMNeT++ and ns-3 digital twin parameters.")
    p.add_argument(
        "--omnet-ini",
        action="append",
        default=["omnet/FiveG_network/simulations/omnetpp.ini"],
        help="Path to OMNeT++ ini file (repeatable).",
    )
    p.add_argument(
        "--ns3-file",
        default="ns3/FiveG_digital_twin/FiveG_digital_twin.cc",
        help="Path to ns-3 digital twin source file.",
    )
    p.add_argument("--dry-run", action="store_true", help="Show planned changes without writing files.")

    p.add_argument("--gnb-x", help="GNB initial X (e.g., 500m)")
    p.add_argument("--gnb-y", help="GNB initial Y (e.g., 500m)")
    p.add_argument("--gnb-z", help="GNB initial Z (e.g., 10m)")
    p.add_argument("--gnb-mobility", help="GNB mobility typename (e.g., StationaryMobility)")
    p.add_argument("--gnb-tx-power", help="GNB transmitter power (e.g., 0.1W)")
    p.add_argument("--gnb-noise-figure", help="GNB noise figure (e.g., 5dB)")

    p.add_argument("--ue-linear-x", help="UE[0..2] initial X (e.g., uniform(300m, 700m))")
    p.add_argument("--ue-linear-y", help="UE[0..2] initial Y (e.g., uniform(300m, 700m))")
    p.add_argument("--ue-linear-speed", help="UE[0..2] speed (e.g., 1.5mps)")
    p.add_argument("--ue-linear-angle", help="UE[0..2] angle (e.g., uniform(0deg, 360deg))")
    p.add_argument("--ue-gauss-speed", help="UE[3..5] speed (e.g., 12mps)")
    p.add_argument("--ue-rwp-speed", help="UE[6..8] speed (e.g., uniform(5mps, 20mps))")
    p.add_argument("--ue-rwp-wait", help="UE[6..8] wait time (e.g., 1s)")
    p.add_argument("--ue-stationary-x", help="UE[9] initial X (e.g., 550m)")
    p.add_argument("--ue-stationary-y", help="UE[9] initial Y (e.g., 450m)")

    p.add_argument("--min-x", help="Constraint area min X (e.g., 0m)")
    p.add_argument("--max-x", help="Constraint area max X (e.g., 1000m)")
    p.add_argument("--min-y", help="Constraint area min Y (e.g., 0m)")
    p.add_argument("--max-y", help="Constraint area max Y (e.g., 1000m)")
    p.add_argument("--min-z", help="Constraint area min Z (e.g., 0m)")
    p.add_argument("--max-z", help="Constraint area max Z (e.g., 0m)")
    p.add_argument("--mobility-update", help="Mobility update interval (e.g., 0.1s)")

    p.add_argument("--ns3-gnb-tx", type=float, help="ns-3 GNB TxPower (dBm)")
    p.add_argument("--ns3-ue-tx", type=float, help="ns-3 UE TxPower (dBm)")
    p.add_argument("--ns3-gnb-nf", type=float, help="ns-3 GNB NoiseFigure (dB)")
    p.add_argument("--ns3-ue-nf", type=float, help="ns-3 UE NoiseFigure (dB)")
    p.add_argument("--ns3-gnb-x", type=float, help="ns-3 GNB base X")
    p.add_argument("--ns3-gnb-y", type=float, help="ns-3 GNB base Y")
    p.add_argument("--ns3-gnb-z", type=float, help="ns-3 GNB Z")
    p.add_argument("--ns3-gnb-step-x", type=float, default=50.0, help="ns-3 GNB step X per index")
    p.add_argument("--ns3-gnb-step-y", type=float, default=0.0, help="ns-3 GNB step Y per index")
    p.add_argument("--ns3-ue-x", type=float, help="ns-3 UE base X")
    p.add_argument("--ns3-ue-y", type=float, help="ns-3 UE base Y")
    p.add_argument("--ns3-ue-z", type=float, help="ns-3 UE Z")
    p.add_argument("--ns3-ue-step-x", type=float, default=5.0, help="ns-3 UE step X per index")
    p.add_argument("--ns3-ue-step-y", type=float, default=0.0, help="ns-3 UE step Y per index")

    p.add_argument(
        "--ditto-topology-out",
        default="ditto/FiveG_network/ditto_topology.json",
        help="Path to write Ditto topology JSON.",
    )
    p.add_argument("--ditto-seed", type=int, default=42, help="Seed for Ditto sampling.")
    p.add_argument("--ditto-ue-count", type=int, default=4, help="Number of UE nodes for Ditto.")
    p.add_argument("--ditto-gnb-count", type=int, default=1, help="Number of gNB nodes for Ditto.")

    return p.parse_args()


def parse_numeric_expr(expr: Optional[str], rng: random.Random) -> Optional[float]:
    if expr is None:
        return None
    raw = expr.strip()
    if not raw:
        return None

    def parse_number(token: str) -> Optional[float]:
        m = re.match(r"^([0-9.+-eE]+)", token.strip())
        return float(m.group(1)) if m else None

    m = re.match(r"^uniform\(([^,]+),\s*([^\)]+)\)$", raw)
    if m:
        a = parse_number(m.group(1))
        b = parse_number(m.group(2))
        if a is not None and b is not None:
            return rng.uniform(a, b)
        return None

    m = re.match(r"^normal\(([^,]+),\s*([^\)]+)\)$", raw)
    if m:
        mean = parse_number(m.group(1))
        std = parse_number(m.group(2))
        if mean is not None and std is not None:
            return rng.gauss(mean, std)
        return None

    m = re.match(r"^max\(([^,]+),\s*([^\)]+)\)$", raw)
    if m:
        a = parse_number(m.group(1))
        b = parse_number(m.group(2))
        if a is not None and b is not None:
            return max(a, b)
        return None

    m = re.match(r"^min\(([^,]+),\s*([^\)]+)\)$", raw)
    if m:
        a = parse_number(m.group(1))
        b = parse_number(m.group(2))
        if a is not None and b is not None:
            return min(a, b)
        return None

    return parse_number(raw)


def build_ditto_topology(args: argparse.Namespace, rng: random.Random) -> Dict[str, List[Dict[str, object]]]:
    nodes: List[Dict[str, object]] = []

    gnb_x = parse_numeric_expr(args.gnb_x, rng) if args.gnb_x else 0.0
    gnb_y = parse_numeric_expr(args.gnb_y, rng) if args.gnb_y else 0.0
    gnb_z = parse_numeric_expr(args.gnb_z, rng) if args.gnb_z else 0.0

    for i in range(max(1, args.ditto_gnb_count)):
        gnb_id = "gnb" if args.ditto_gnb_count == 1 else f"gnb{i}"
        nodes.append({
            "id": gnb_id,
            "x": gnb_x,
            "y": gnb_y,
            "z": gnb_z,
            "speed": 0.0,
            "angle": 0.0,
            "serving_gnb": "unknown",
            "sinr_dl": -999,
            "sinr_ul": -999,
            "sinr_d2d": -999,
            "constraints": {
                "min_x": args.min_x,
                "max_x": args.max_x,
                "min_y": args.min_y,
                "max_y": args.max_y,
                "min_z": args.min_z,
                "max_z": args.max_z,
            },
        })

    ue_speed_linear = parse_numeric_expr(args.ue_linear_speed, rng) if args.ue_linear_speed else 0.0
    ue_angle_linear = parse_numeric_expr(args.ue_linear_angle, rng) if args.ue_linear_angle else 0.0
    ue_linear_x = parse_numeric_expr(args.ue_linear_x, rng) if args.ue_linear_x else 0.0
    ue_linear_y = parse_numeric_expr(args.ue_linear_y, rng) if args.ue_linear_y else 0.0

    ue_gauss_speed = parse_numeric_expr(args.ue_gauss_speed, rng) if args.ue_gauss_speed else 0.0
    ue_rwp_speed = parse_numeric_expr(args.ue_rwp_speed, rng) if args.ue_rwp_speed else 0.0
    ue_stationary_x = parse_numeric_expr(args.ue_stationary_x, rng) if args.ue_stationary_x else 0.0
    ue_stationary_y = parse_numeric_expr(args.ue_stationary_y, rng) if args.ue_stationary_y else 0.0

    for i in range(max(0, args.ditto_ue_count)):
        if i <= 2:
            x = parse_numeric_expr(args.ue_linear_x, rng) if args.ue_linear_x else ue_linear_x
            y = parse_numeric_expr(args.ue_linear_y, rng) if args.ue_linear_y else ue_linear_y
            speed = ue_speed_linear
            angle = ue_angle_linear
        elif 3 <= i <= 5:
            x = ue_linear_x
            y = ue_linear_y
            speed = ue_gauss_speed
            angle = 0.0
        elif 6 <= i <= 8:
            x = ue_linear_x
            y = ue_linear_y
            speed = ue_rwp_speed
            angle = 0.0
        else:
            x = ue_stationary_x
            y = ue_stationary_y
            speed = 0.0
            angle = 0.0

        nodes.append({
            "id": f"ue{i}",
            "x": x,
            "y": y,
            "z": 0.0,
            "speed": speed,
            "angle": angle,
            "serving_gnb": "nan",
            "sinr_dl": -999,
            "sinr_ul": -999,
            "sinr_d2d": -999,
            "constraints": {
                "min_x": args.min_x,
                "max_x": args.max_x,
                "min_y": args.min_y,
                "max_y": args.max_y,
                "min_z": args.min_z,
                "max_z": args.max_z,
            },
        })

    flows = [
        {
            "type": "nan",
            "src": "server",
            "dst": f"ue{i}",
            "packet_size": 0,
            "interval": 0,
            "throughput": 0,
            "delay": 0,
            "bler": 0,
            "packet_loss": 0,
        }
        for i in range(max(0, args.ditto_ue_count))
    ]

    return {"nodes": nodes, "flows": flows}


def validate_constraints(args: argparse.Namespace) -> None:
    def to_num(val: Optional[str]) -> Optional[float]:
        if val is None:
            return None
        m = re.match(r"^([0-9.+-eE]+)", val.strip())
        return float(m.group(1)) if m else None

    for min_key, max_key in [
        ("min_x", "max_x"),
        ("min_y", "max_y"),
        ("min_z", "max_z"),
    ]:
        min_v = to_num(getattr(args, min_key))
        max_v = to_num(getattr(args, max_key))
        if min_v is not None and max_v is not None and min_v > max_v:
            raise ValueError(f"Invalid constraints: {min_key} > {max_key}.")


def update_omnet_ini(path: str, args: argparse.Namespace) -> Dict[str, int]:
    text = read_text(path)
    changes: Dict[str, int] = {}

    def apply(key_regex: str, value: Optional[str], allow_insert: bool = True) -> None:
        if value is None:
            return
        nonlocal text
        new_text, count = update_simple_key(text, key_regex, value, allow_insert)
        text = new_text
        changes[key_regex] = changes.get(key_regex, 0) + count

    apply(r"\*\.gnb(\[0\])?\.mobility\.initialX", args.gnb_x)
    apply(r"\*\.gnb(\[0\])?\.mobility\.initialY", args.gnb_y)
    if args.gnb_z is not None:
        apply(r"\*\.gnb(\[0\])?\.mobility\.initialZ", args.gnb_z)

    if args.gnb_mobility:
        gnb_type = fmt_ini_value(args.gnb_mobility)
        apply(r"\*\.gnb(\[0\])?\.mobility\.typename", gnb_type)

    if args.gnb_tx_power:
        apply(r"\*\*\.transmitter\.power", args.gnb_tx_power)
    if args.gnb_noise_figure:
        apply(r"\*\*\.cellularNic\.phy\.receiver\.noiseFigure", args.gnb_noise_figure)

    apply(r"\*\.ue\[0\.\.2\]\.mobility\.initialX", args.ue_linear_x)
    apply(r"\*\.ue\[0\.\.2\]\.mobility\.initialY", args.ue_linear_y)
    apply(r"\*\.ue\[0\.\.2\]\.mobility\.speed", args.ue_linear_speed)
    apply(r"\*\.ue\[0\.\.2\]\.mobility\.angle", args.ue_linear_angle)

    apply(r"\*\.ue\[3\.\.5\]\.mobility\.speed", args.ue_gauss_speed)
    apply(r"\*\.ue\[6\.\.8\]\.mobility\.speed", args.ue_rwp_speed)
    apply(r"\*\.ue\[6\.\.8\]\.mobility\.waitTime", args.ue_rwp_wait)

    apply(r"\*\.ue\[9\]\.mobility\.initialX", args.ue_stationary_x)
    apply(r"\*\.ue\[9\]\.mobility\.initialY", args.ue_stationary_y)

    apply(r"\*\*\.constraintAreaMinX", args.min_x)
    apply(r"\*\*\.constraintAreaMaxX", args.max_x)
    apply(r"\*\*\.constraintAreaMinY", args.min_y)
    apply(r"\*\*\.constraintAreaMaxY", args.max_y)
    apply(r"\*\*\.constraintAreaMinZ", args.min_z)
    apply(r"\*\*\.constraintAreaMaxZ", args.max_z)
    apply(r"\*\*\.mobility\.updateInterval", args.mobility_update)

    if not args.dry_run:
        write_text(path, text)

    return changes


def update_ns3_file(path: str, args: argparse.Namespace) -> Dict[str, int]:
    text = read_text(path)
    changes: Dict[str, int] = {}

    def sub(pattern: str, repl: str, key: str) -> None:
        nonlocal text
        new_text, count = re.subn(pattern, repl, text, flags=re.MULTILINE)
        text = new_text
        if count:
            changes[key] = changes.get(key, 0) + count

    if args.ns3_gnb_tx is not None:
        sub(
            r"nrHelper->SetGnbPhyAttribute\(\"TxPower\",\s*DoubleValue\([^)]*\)\);",
            f"nrHelper->SetGnbPhyAttribute(\"TxPower\", DoubleValue({args.ns3_gnb_tx}));",
            "ns3_gnb_tx",
        )
    if args.ns3_ue_tx is not None:
        sub(
            r"nrHelper->SetUePhyAttribute\(\"TxPower\",\s*DoubleValue\([^)]*\)\);",
            f"nrHelper->SetUePhyAttribute(\"TxPower\", DoubleValue({args.ns3_ue_tx}));",
            "ns3_ue_tx",
        )
    if args.ns3_ue_nf is not None:
        sub(
            r"nrHelper->SetUePhyAttribute\(\"NoiseFigure\",\s*DoubleValue\([^)]*\)\);",
            f"nrHelper->SetUePhyAttribute(\"NoiseFigure\", DoubleValue({args.ns3_ue_nf}));",
            "ns3_ue_nf",
        )
    if args.ns3_gnb_nf is not None:
        sub(
            r"nrHelper->SetGnbPhyAttribute\(\"NoiseFigure\",\s*DoubleValue\([^)]*\)\);",
            f"nrHelper->SetGnbPhyAttribute(\"NoiseFigure\", DoubleValue({args.ns3_gnb_nf}));",
            "ns3_gnb_nf",
        )

    if args.ns3_gnb_x is not None or args.ns3_gnb_y is not None or args.ns3_gnb_z is not None:
        gnb_x = args.ns3_gnb_x if args.ns3_gnb_x is not None else 726.0
        gnb_y = args.ns3_gnb_y if args.ns3_gnb_y is not None else 277.0
        gnb_z = args.ns3_gnb_z if args.ns3_gnb_z is not None else 10.0
        sub(
            r"gnbNodes\.Get\(i\)->GetObject<[^>]+>\(\)->SetPosition\(Vector\([^\)]*\)\);",
            f"gnbNodes.Get(i)->GetObject<MobilityModel>()->SetPosition(Vector({gnb_x} + (i * {args.ns3_gnb_step_x}), {gnb_y} + (i * {args.ns3_gnb_step_y}), {gnb_z}));",
            "ns3_gnb_pos",
        )

    if args.ns3_ue_x is not None or args.ns3_ue_y is not None or args.ns3_ue_z is not None:
        ue_x = args.ns3_ue_x if args.ns3_ue_x is not None else 850.0
        ue_y = args.ns3_ue_y if args.ns3_ue_y is not None else 850.0
        ue_z = args.ns3_ue_z if args.ns3_ue_z is not None else 1.5
        sub(
            r"ueNodes\.Get\(i\)->GetObject<[^>]+>\(\)->SetPosition\(Vector\([^\)]*\)\);",
            f"ueNodes.Get(i)->GetObject<MobilityModel>()->SetPosition(Vector({ue_x} + (i * {args.ns3_ue_step_x}), {ue_y} + (i * {args.ns3_ue_step_y}), {ue_z}));",
            "ns3_ue_pos",
        )

    if not args.dry_run:
        write_text(path, text)

    return changes


def main() -> int:
    args = parse_args()
    try:
        validate_constraints(args)
    except ValueError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    omnet_paths = [os.path.join(root, p) for p in args.omnet_ini]
    ns3_path = os.path.join(root, args.ns3_file)
    ditto_path = os.path.join(root, args.ditto_topology_out)

    total_changes: Dict[str, int] = {}

    for path in omnet_paths:
        if not os.path.exists(path):
            print(f"[error] OMNeT++ ini not found: {path}", file=sys.stderr)
            return 2
        changes = update_omnet_ini(path, args)
        for k, v in changes.items():
            total_changes[f"{path}:{k}"] = v

    if os.path.exists(ns3_path):
        changes = update_ns3_file(ns3_path, args)
        for k, v in changes.items():
            total_changes[f"{ns3_path}:{k}"] = v
    else:
        print(f"[error] ns-3 file not found: {ns3_path}", file=sys.stderr)
        return 2

    if not total_changes:
        print("[warn] No changes applied. Check your arguments.")
        return 1

    print("[ok] Updates applied:" if not args.dry_run else "[ok] Planned updates:")
    for key, count in sorted(total_changes.items()):
        print(f"- {key} (x{count})")

    if not args.dry_run:
        rng = random.Random(args.ditto_seed)
        topology = build_ditto_topology(args, rng)
        os.makedirs(os.path.dirname(ditto_path), exist_ok=True)
        with open(ditto_path, "w", encoding="utf-8") as f:
            json.dump(topology, f, indent=2)
        print(f"[ok] Ditto topology written: {ditto_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
