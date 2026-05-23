from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    import gymnasium as gym  # type: ignore
    from gymnasium import spaces  # type: ignore
    _GYM_FLAVOR = "gymnasium"
except ImportError:
    try:
        import gym  # type: ignore
        from gym import spaces  # type: ignore
        _GYM_FLAVOR = "gym"
    except ImportError:
        _GYM_FLAVOR = "shim"

        class _SpaceBox:
            def __init__(self, low, high, shape, dtype):
                self.low = np.asarray(low, dtype=dtype) if not np.isscalar(low) else low
                self.high = np.asarray(high, dtype=dtype) if not np.isscalar(high) else high
                self.shape = tuple(shape)
                self.dtype = dtype

            def sample(self):
                low = -1.0 if np.isscalar(self.low) else self.low
                high = 1.0 if np.isscalar(self.high) else self.high
                return np.random.uniform(low, high, size=self.shape).astype(self.dtype)

        class _SpacesShim:
            Box = _SpaceBox

        class _GymShim:
            class Env:
                metadata = {"render_modes": []}

        gym = _GymShim()  # type: ignore
        spaces = _SpacesShim()  # type: ignore

from .state import (
    FlowState,
    NodeState,
    Snapshot,
    latest_snapshot,
    load_snapshot_history,
)


DEFAULT_ACTION_SPEC: List[Tuple[str, float, float, float]] = [
    ("ns3_gnb_tx_dbm",      20.0,  49.0,   46.0),
    ("ns3_ue_tx_dbm",       10.0,  26.0,   23.0),
    ("ns3_gnb_nf_db",        2.0,   9.0,    5.0),
    ("ns3_ue_nf_db",         3.0,  10.0,    7.0),
    ("ns3_snapshot_s",       0.05,  1.0,    0.2),
    ("ns3_pkt_size_bytes",   64.0, 1500.0, 1400.0),
    ("ns3_pkt_interval_ms",   5.0,  100.0,   10.0),
]


DEFAULT_REWARD_WEIGHTS: Dict[str, float] = {
    "sinr_dl":         0.05,
    "sinr_ul":         0.10,
    "throughput_mbps": 0.15,
    "delay_ms":        0.05,
    "bler_pct":        0.02,
}


def _default_dt_live_path() -> str:
    ns3_out = os.environ.get("NS3_OUTPUT_DIR", "ns3/FiveG_digital_twin")
    return os.path.join(ns3_out, "ns3_received_history.json")


@dataclass
class EnvConfig:
    backend: str = "offline"
    pt_history_path: str = "third_party/physical_twin_history.json"
    dt_history_path: str = "third_party/dt_collected_history.json"
    pt_live_path: str = "omnet/FiveG_network/simulations/network_state.json"
    dt_live_path: Optional[str] = None
    action_file: str = "/dev/shm/agent_action.json"
    max_episode_steps: int = 200
    reward_weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_REWARD_WEIGHTS))
    action_spec: List[Tuple[str, float, float, float]] = field(default_factory=lambda: list(DEFAULT_ACTION_SPEC))
    history_seed: Optional[int] = None
    live_step_sleep: float = 0.5
    pt_5g3e_path: Optional[str] = None
    ue_d_min: float = 50.0
    ue_d_max: float = 300.0
    pt_5g3e_multi_site: bool = False
    signed_observations: bool = True
    fixed_action_overrides: Dict[str, float] = field(default_factory=dict)


class DigitalTwinFidelityEnv(gym.Env):  # type: ignore[misc]

    metadata = {"render_modes": []}

    def __init__(self, config: Optional[EnvConfig] = None):
        super().__init__()
        self.config = config or EnvConfig()
        self._step = 0
        self._rng = random.Random(self.config.history_seed)

        self._action_names = [s[0] for s in self.config.action_spec]
        self._action_low = np.array([s[1] for s in self.config.action_spec], dtype=np.float32)
        self._action_high = np.array([s[2] for s in self.config.action_spec], dtype=np.float32)
        self._action_default = np.array([s[3] for s in self.config.action_spec], dtype=np.float32)

        self.action_space = spaces.Box(
            low=-1.0, high=1.0, shape=(len(self.config.action_spec),), dtype=np.float32
        )
        obs_dim = 5 + len(self.config.action_spec)
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32
        )

        self._last_action_norm = np.zeros_like(self._action_default, dtype=np.float32)

        self._pt_history: List[Snapshot] = []
        self._dt_history: List[Snapshot] = []
        self._cursor: int = 0

        self._physics_dt: bool = False
        self._physics_ue_dists: List[float] = []
        self._physics_gnb_sep_m: float = 400.0
        self._all_sites_histories: List[List[Snapshot]] = []
        self._physics_isolated: bool = False

    def _denormalize(self, action: np.ndarray) -> np.ndarray:
        a = np.clip(action, -1.0, 1.0).astype(np.float32)
        return self._action_low + (a + 1.0) * 0.5 * (self._action_high - self._action_low)

    def _action_dict(self, denorm: np.ndarray) -> Dict[str, float]:
        d = {name: float(val) for name, val in zip(self._action_names, denorm)}
        d.update(self.config.fixed_action_overrides)
        return d

    def _write_action_file(self, denorm: np.ndarray) -> None:
        payload = {
            "timestamp": time.time(),
            "step": self._step,
            "action": self._action_dict(denorm),
        }
        try:
            os.makedirs(os.path.dirname(self.config.action_file) or ".", exist_ok=True)
            with open(self.config.action_file, "w", encoding="utf-8") as f:
                json.dump(payload, f)
        except OSError:
            pass

    @staticmethod
    def _flow_signature(flow: FlowState) -> str:
        return f"{flow.src}_to_{flow.dst}"

    def _pair_snapshots(self, pt: Snapshot, dt: Snapshot) -> Tuple[List[Tuple[NodeState, NodeState]], List[Tuple[FlowState, FlowState]]]:
        node_pairs = []
        for node_id, pt_node in pt.nodes.items():
            dt_node = dt.nodes.get(node_id)
            if dt_node is not None:
                node_pairs.append((pt_node, dt_node))
        flow_pairs = []
        for key, pt_flow in pt.flows.items():
            dt_flow = dt.flows.get(key)
            if dt_flow is not None:
                flow_pairs.append((pt_flow, dt_flow))
        return node_pairs, flow_pairs

    def _compute_observation_and_reward(self, pt: Snapshot, dt: Snapshot) -> Tuple[np.ndarray, float, Dict[str, float]]:
        node_pairs, flow_pairs = self._pair_snapshots(pt, dt)

        def safe_mean(xs: List[float]) -> float:
            return float(np.mean(xs)) if xs else 0.0

        valid_nodes = [(p, d) for p, d in node_pairs if p.sinr_dl > -900 and d.sinr_dl > -900]

        d_sinr_dl = [abs(p.sinr_dl - d.sinr_dl) for p, d in valid_nodes]
        d_sinr_ul = [abs(p.sinr_ul - d.sinr_ul) for p, d in valid_nodes]
        d_thr   = [abs(p.throughput_mbps - d.throughput_mbps) for p, d in flow_pairs]
        d_delay = [abs(p.delay_ms - d.delay_ms) for p, d in flow_pairs]
        d_bler  = [abs(p.bler_pct - d.bler_pct) for p, d in flow_pairs]

        components = {
            "sinr_dl":         safe_mean(d_sinr_dl),
            "sinr_ul":         safe_mean(d_sinr_ul),
            "throughput_mbps": safe_mean(d_thr),
            "delay_ms":        safe_mean(d_delay),
            "bler_pct":        safe_mean(d_bler),
        }

        weights = self.config.reward_weights
        reward = -sum(weights.get(k, 0.0) * v for k, v in components.items())

        if self.config.signed_observations:
            obs_sinr_dl = [p.sinr_dl - d.sinr_dl for p, d in valid_nodes]
            obs_sinr_ul = [p.sinr_ul - d.sinr_ul for p, d in valid_nodes]
            obs_thr     = [p.throughput_mbps - d.throughput_mbps for p, d in flow_pairs]
            obs_delay   = [p.delay_ms - d.delay_ms for p, d in flow_pairs]
            obs_bler    = [p.bler_pct - d.bler_pct for p, d in flow_pairs]
        else:
            obs_sinr_dl = d_sinr_dl
            obs_sinr_ul = d_sinr_ul
            obs_thr     = d_thr
            obs_delay   = d_delay
            obs_bler    = d_bler

        obs = np.array(
            [
                safe_mean(obs_sinr_dl),
                safe_mean(obs_sinr_ul),
                safe_mean(obs_thr),
                safe_mean(obs_delay),
                safe_mean(obs_bler),
                *self._last_action_norm.tolist(),
            ],
            dtype=np.float32,
        )
        return obs, float(reward), components

    def _reset_offline(self) -> None:
        if self.config.pt_5g3e_path:
            from .loaders.five_g3e import load_all_sites_v2, load_gnb_v2, load_site_v2
            from .loaders.physics import random_ue_dists
            p = self.config.pt_5g3e_path

            if self.config.pt_5g3e_multi_site:
                if not self._all_sites_histories:
                    for site_name in sorted(os.listdir(p)):
                        site_path = os.path.join(p, site_name)
                        if not os.path.isdir(site_path):
                            continue
                        try:
                            pt, _ = load_site_v2(site_path)
                            if pt:
                                self._all_sites_histories.append(pt)
                        except FileNotFoundError:
                            continue
                    if not self._all_sites_histories:
                        raise FileNotFoundError(f"No 5G3E sites found in {p!r}")
                self._pt_history = self._rng.choice(self._all_sites_histories)
            elif os.path.isfile(p):
                self._pt_history, _ = load_gnb_v2(p)
            else:
                try:
                    self._pt_history, _ = load_site_v2(p)
                except FileNotFoundError:
                    self._pt_history, _ = load_all_sites_v2(p)

            if not self._pt_history:
                raise FileNotFoundError(f"5G3E loader found no snapshots in {p!r}")
            n_ue = max(1, len(self._pt_history[0].nodes))
            self._physics_ue_dists = random_ue_dists(n_ue, rng=self._rng,
                                                     d_min=self.config.ue_d_min,
                                                     d_max=self.config.ue_d_max)
            self._physics_dt = True
            self._physics_isolated = True
            self._cursor = self._rng.randint(0, max(0, len(self._pt_history) - 1))
            return

        self._pt_history = load_snapshot_history(self.config.pt_history_path)
        self._dt_history = load_snapshot_history(self.config.dt_history_path)
        if not self._pt_history:
            self._pt_history = load_snapshot_history(self.config.pt_live_path)
        if not self._dt_history:
            self._dt_history = load_snapshot_history(self.config.dt_live_path)

        if not self._pt_history or not self._dt_history:
            raise FileNotFoundError(
                "Offline backend needs both PT and DT histories. Looked at: "
                f"{self.config.pt_history_path}, {self.config.dt_history_path}, "
                f"{self.config.pt_live_path}, {self.config.dt_live_path}"
            )
        self._cursor = self._rng.randint(0, max(0, min(len(self._pt_history), len(self._dt_history)) - 1))

    def _step_offline(self) -> Tuple[Snapshot, Snapshot]:
        if self._physics_dt:
            n = len(self._pt_history)
            pt = self._pt_history[self._cursor % max(1, n)]
            self._cursor = (self._cursor + 1) % max(1, n)
            from .loaders.physics import compute_dt_snapshot
            denorm = self._denormalize(self._last_action_norm)
            dt = compute_dt_snapshot(
                self._action_dict(denorm),
                self._physics_ue_dists,
                self._physics_gnb_sep_m,
                pt.timestamp,
                isolated_cells=self._physics_isolated,
            )
            return pt, dt

        n = min(len(self._pt_history), len(self._dt_history))
        idx = self._cursor % n
        pt = self._pt_history[idx]
        dt = self._dt_history[idx]
        self._cursor = (self._cursor + 1) % max(1, n)
        return pt, dt

    def _step_live(self) -> Tuple[Snapshot, Snapshot]:
        if self.config.live_step_sleep > 0:
            time.sleep(self.config.live_step_sleep)
        dt_path = self.config.dt_live_path or _default_dt_live_path()
        pt = latest_snapshot(self.config.pt_live_path) or Snapshot()
        dt = latest_snapshot(dt_path) or Snapshot()
        return pt, dt

    def reset(self, *, seed=None, options=None):  # type: ignore[override]
        if seed is not None:
            self._rng = random.Random(seed)
        self._step = 0
        self._last_action_norm = np.zeros_like(self._action_default, dtype=np.float32)

        if self.config.backend == "offline":
            self._reset_offline()
            pt, dt = self._step_offline()
        else:
            pt, dt = self._step_live()

        obs, _, _ = self._compute_observation_and_reward(pt, dt)
        if _GYM_FLAVOR == "gymnasium":
            return obs, {}
        return obs

    def step(self, action):  # type: ignore[override]
        action = np.asarray(action, dtype=np.float32)
        self._last_action_norm = np.clip(action, -1.0, 1.0)
        denorm = self._denormalize(self._last_action_norm)
        self._write_action_file(denorm)

        if self.config.backend == "offline":
            pt, dt = self._step_offline()
        else:
            pt, dt = self._step_live()

        obs, reward, components = self._compute_observation_and_reward(pt, dt)

        self._step += 1
        terminated = False
        truncated = self._step >= self.config.max_episode_steps

        info = {
            "components": components,
            "action": self._action_dict(denorm),
        }

        if _GYM_FLAVOR == "gymnasium":
            return obs, reward, terminated, truncated, info
        return obs, reward, terminated or truncated, info
