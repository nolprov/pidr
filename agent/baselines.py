from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Callable, Dict, List

import numpy as np

from .env import DigitalTwinFidelityEnv


@dataclass
class BaselineResult:
    name: str
    mean_reward: float
    std_reward: float
    component_means: Dict[str, float]
    n_episodes: int


def _run_episode(env: DigitalTwinFidelityEnv, policy: Callable[[np.ndarray], np.ndarray]):
    obs = env.reset()
    if isinstance(obs, tuple):
        obs = obs[0]
    rewards: List[float] = []
    components: Dict[str, List[float]] = {}
    done = False
    while not done:
        action = policy(obs)
        out = env.step(action)
        if len(out) == 5:
            obs, reward, terminated, truncated, info = out
            done = bool(terminated) or bool(truncated)
        else:
            obs, reward, done, info = out
        rewards.append(float(reward))
        for k, v in (info or {}).get("components", {}).items():
            components.setdefault(k, []).append(float(v))
    mean_components = {k: float(np.mean(v)) for k, v in components.items()}
    return float(np.sum(rewards)), mean_components


def _collect(env: DigitalTwinFidelityEnv, policy: Callable[[np.ndarray], np.ndarray], episodes: int, name: str) -> BaselineResult:
    totals: List[float] = []
    components_acc: Dict[str, List[float]] = {}
    for _ in range(episodes):
        ep_total, comps = _run_episode(env, policy)
        totals.append(ep_total)
        for k, v in comps.items():
            components_acc.setdefault(k, []).append(v)
    return BaselineResult(
        name=name,
        mean_reward=float(np.mean(totals)) if totals else 0.0,
        std_reward=float(np.std(totals)) if totals else 0.0,
        component_means={k: float(np.mean(v)) for k, v in components_acc.items()},
        n_episodes=episodes,
    )


def baseline_default(env: DigitalTwinFidelityEnv, episodes: int = 5) -> BaselineResult:
    zero = np.zeros(env.action_space.shape, dtype=np.float32)
    return _collect(env, lambda _obs: zero, episodes, "default")


def baseline_random(env: DigitalTwinFidelityEnv, episodes: int = 5, seed: int = 0) -> BaselineResult:
    rng = np.random.default_rng(seed)
    def _policy(_obs: np.ndarray) -> np.ndarray:
        return rng.uniform(-1.0, 1.0, size=env.action_space.shape).astype(np.float32)
    return _collect(env, _policy, episodes, "random")


def baseline_grid(env: DigitalTwinFidelityEnv, episodes: int = 5, points: int = 3) -> BaselineResult:
    actions_axes = [np.linspace(-1.0, 1.0, points) for _ in range(env.action_space.shape[0])]
    best_total = -math.inf
    best_components: Dict[str, float] = {}
    totals: List[float] = []
    for combo in itertools.product(*actions_axes):
        a = np.array(combo, dtype=np.float32)
        ep_total, comps = _run_episode(env, lambda _obs, a=a: a)
        totals.append(ep_total)
        if ep_total > best_total:
            best_total = ep_total
            best_components = comps
    return BaselineResult(
        name="grid_best",
        mean_reward=best_total,
        std_reward=float(np.std(totals)) if totals else 0.0,
        component_means=best_components,
        n_episodes=len(totals),
    )
