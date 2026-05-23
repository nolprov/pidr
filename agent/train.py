#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .baselines import baseline_default, baseline_grid, baseline_random
from .env import DEFAULT_ACTION_SPEC, DigitalTwinFidelityEnv, EnvConfig

RESULTS_DIR_DEFAULT = "results"


def _ensure_results_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _save_baselines(path: str, results: List[Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([dataclasses.asdict(r) for r in results], f, indent=2)


def _action_to_dict(env: DigitalTwinFidelityEnv, action_norm: np.ndarray) -> Dict[str, float]:
    denorm = env._denormalize(action_norm)   # noqa: SLF001
    return env._action_dict(denorm)           # noqa: SLF001


def _save_best_action(path: str, action: Dict[str, float]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"action": action, "spec": DEFAULT_ACTION_SPEC}, f, indent=2)


def write_curve(path: str, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def train_with_sb3(
    env_factory,
    total_timesteps: int,
    seed: int,
    results_dir: str,
    n_steps: int = 256,
    batch_size: int = 64,
    n_epochs: int = 10,
    learning_rate: float = 3e-4,
    ent_coef: float = 0.01,
    resume_from: Optional[str] = None,
    net_arch: Optional[List[int]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    from stable_baselines3 import PPO                      # type: ignore
    from stable_baselines3.common.callbacks import (       # type: ignore
        BaseCallback, CheckpointCallback,
    )
    from stable_baselines3.common.monitor import Monitor   # type: ignore

    checkpoint_dir = os.path.join(results_dir, "ppo_model")
    os.makedirs(checkpoint_dir, exist_ok=True)

    class LiveCurveCallback(BaseCallback):
        def __init__(self, best_action_path: str) -> None:
            super().__init__()
            self.curve: List[Dict[str, Any]] = []
            self._ep_reward = 0.0
            self._ep_components: Dict[str, List[float]] = {}
            self._ep_count = 0
            self._best_reward = -np.inf
            self._best_action_path = best_action_path

        def _on_step(self) -> bool:
            reward = float(self.locals["rewards"][0])
            done   = bool(self.locals["dones"][0])
            info   = (self.locals.get("infos") or [{}])[0]

            self._ep_reward += reward
            for k, v in (info.get("components") or {}).items():
                self._ep_components.setdefault(k, []).append(float(v))

            if done:
                comps = {k: float(np.mean(v)) for k, v in self._ep_components.items()}
                row = {"episode": self._ep_count, "total_reward": self._ep_reward, **comps}
                self.curve.append(row)

                if self._ep_reward > self._best_reward:
                    self._best_reward = self._ep_reward
                    env = self.training_env.envs[0].env
                    obs = env.reset()
                    if isinstance(obs, tuple):
                        obs = obs[0]
                    act, _ = self.model.predict(obs, deterministic=True)
                    best = _action_to_dict(env, np.asarray(act, dtype=np.float32))
                    _save_best_action(self._best_action_path, best)

                n = self._ep_count
                if n % 10 == 0:
                    print(
                        f"[PPO ep={n:4d}] reward={self._ep_reward:8.3f}"
                        + (f"  best={self._best_reward:.3f}" if n > 0 else "")
                    )
                self._ep_reward = 0.0
                self._ep_components = {}
                self._ep_count += 1
            return True

    env = Monitor(env_factory())
    best_action_path = os.path.join(results_dir, "best_action.json")

    curve_cb = LiveCurveCallback(best_action_path)
    ckpt_cb  = CheckpointCallback(
        save_freq=max(1000, total_timesteps // 10),
        save_path=checkpoint_dir,
        name_prefix="ppo",
        verbose=0,
    )

    if resume_from and os.path.isfile(resume_from):
        print(f"[PPO] Resuming from {resume_from}")
        model = PPO.load(resume_from, env=env, device="auto")
        model.learning_rate = learning_rate
        model.ent_coef = ent_coef
        for pg in model.policy.optimizer.param_groups:
            pg["lr"] = learning_rate
    else:
        arch = net_arch if net_arch is not None else [128, 128]
        model = PPO(
            "MlpPolicy",
            env,
            verbose=0,
            seed=seed,
            n_steps=n_steps,
            batch_size=batch_size,
            n_epochs=n_epochs,
            learning_rate=learning_rate,
            ent_coef=ent_coef,
            max_grad_norm=0.5,
            policy_kwargs={"net_arch": arch},
        )

    t0 = time.time()
    model.learn(
        total_timesteps=total_timesteps,
        callback=[curve_cb, ckpt_cb],
        reset_num_timesteps=(resume_from is None),
    )
    elapsed = time.time() - t0

    final_path = os.path.join(results_dir, "ppo_model_final.zip")
    model.save(final_path)
    print(f"[PPO] Done in {elapsed:.0f}s — model saved to {final_path}")

    obs = env.reset()
    if isinstance(obs, tuple):
        obs = obs[0]
    final_act, _ = model.predict(obs, deterministic=True)
    final_best = _action_to_dict(env.env, np.asarray(final_act, dtype=np.float32))
    return curve_cb.curve, final_best


def train_with_cem(
    env_factory,
    iterations: int,
    population: int,
    elite_frac: float,
    sigma_init: float,
    seed: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    rng = np.random.default_rng(seed)
    env = env_factory()
    n_actions = env.action_space.shape[0]
    mu    = np.zeros(n_actions, dtype=np.float32)
    sigma = np.full(n_actions, sigma_init, dtype=np.float32)
    n_elite = max(1, int(elite_frac * population))

    curve: List[Dict[str, Any]] = []
    best_action = mu.copy()
    best_total  = -np.inf
    ep_idx = 0

    for it in range(iterations):
        candidates = np.clip(
            rng.normal(mu, sigma, size=(population, n_actions)).astype(np.float32),
            -1.0, 1.0,
        )
        scores = np.zeros(population, dtype=np.float32)

        for i in range(population):
            obs = env.reset()
            if isinstance(obs, tuple):
                obs = obs[0]
            done      = False
            ep_total  = 0.0
            ep_comps: Dict[str, List[float]] = {}
            while not done:
                step_out = env.step(candidates[i])
                if len(step_out) == 5:
                    obs, reward, terminated, truncated, info = step_out
                    done = bool(terminated) or bool(truncated)
                else:
                    obs, reward, done, info = step_out
                ep_total += float(reward)
                for k, v in (info.get("components") or {}).items():
                    ep_comps.setdefault(k, []).append(float(v))
            scores[i] = ep_total
            comps = {k: float(np.mean(v)) for k, v in ep_comps.items()}
            curve.append({"episode": ep_idx, "total_reward": ep_total, **comps})
            ep_idx += 1

        elite_idx = np.argsort(scores)[-n_elite:]
        elite     = candidates[elite_idx]
        mu        = elite.mean(axis=0)
        sigma     = np.maximum(elite.std(axis=0), 0.05)
        gen_best  = float(scores.max())
        gen_best_a = candidates[int(np.argmax(scores))]
        if gen_best > best_total:
            best_total  = gen_best
            best_action = gen_best_a.copy()
        print(f"[CEM] it={it+1}/{iterations} best={gen_best:.3f} mu={mu} sigma={sigma}")

    return curve, _action_to_dict(env, best_action)


def main() -> int:
    p = argparse.ArgumentParser(description="Train DRL agent for digital-twin fidelity.")
    p.add_argument("--backend",          choices=["offline", "live"], default="offline")
    p.add_argument("--algo",             choices=["auto", "ppo", "cem"], default="auto",
                   help="auto → PPO if SB3 is available, else CEM.")
    p.add_argument("--timesteps",        type=int,   default=50000,
                   help="Total PPO environment steps (ignored for CEM).")
    p.add_argument("--episode-steps",    type=int,   default=64,
                   help="Max steps per episode.")
    p.add_argument("--cem-iterations",   type=int,   default=10)
    p.add_argument("--cem-population",   type=int,   default=24)
    p.add_argument("--cem-elite-frac",   type=float, default=0.25)
    p.add_argument("--cem-sigma",        type=float, default=0.5)
    p.add_argument("--ppo-n-steps",      type=int,   default=256,
                   help="Steps collected per update. Higher = more stable but slower.")
    p.add_argument("--ppo-batch-size",   type=int,   default=64)
    p.add_argument("--ppo-lr",           type=float, default=3e-4)
    p.add_argument("--ppo-ent-coef",     type=float, default=0.01,
                   help="Entropy coeff. Raise to 0.05 for live mode (noisy reward).")
    p.add_argument("--seed",             type=int,   default=0)
    p.add_argument("--results-dir",      default=RESULTS_DIR_DEFAULT)
    p.add_argument("--pt-history",       default="third_party/physical_twin_history.json")
    p.add_argument("--dt-history",       default="third_party/dt_collected_history.json")
    p.add_argument("--pt-live",          default="omnet/FiveG_network/simulations/network_state.json")
    p.add_argument("--dt-live",          default="",
                   help="DT live snapshot path. Defaults to $NS3_OUTPUT_DIR/ns3_received_history.json.")
    p.add_argument("--live-step-sleep",  type=float, default=0.5,
                   help="Seconds to wait between live observations (0 = mock/fast mode).")
    p.add_argument("--baselines-only",   action="store_true")
    p.add_argument("--no-baselines",     action="store_true",
                   help="Skip baseline computation (saves time in live mode).")
    p.add_argument("--resume-from",      default="",
                   help="Path to a ppo_model_final.zip from a previous session. "
                        "Loads the saved policy and continues training (warm start). "
                        "Hyperparameters are restored from the checkpoint.")
    p.add_argument("--pt-5g3e",          default="",
                   help="Path to a 5G3E v2 RAN site directory (or single gNB JSONL). "
                        "When set, replaces --pt-history with real srsGNB measurements "
                        "as the Physical Twin and generates paired synthetic DT snapshots.")
    p.add_argument("--unsigned-obs",     action="store_true",
                   help="Use unsigned (absolute) observation errors instead of signed. "
                        "Ablation flag to quantify the contribution of directional obs.")
    p.add_argument("--fix-param",        action="append", default=[], metavar="NAME=VALUE",
                   help="Fix an action parameter to a constant physical value, e.g. "
                        "--fix-param ns3_ue_tx_dbm=23.0. Can be repeated for multiple params.")
    p.add_argument("--reward-weight",    action="append", default=[], metavar="NAME=VALUE",
                   help="Override a reward weight, e.g. --reward-weight throughput_mbps=0.45. "
                        "Can be repeated. Unspecified weights keep their default values.")
    p.add_argument("--net-arch",         default="128,128",
                   help="Hidden layer sizes for MLP policy, comma-separated. "
                        "Default: 128,128. Example: --net-arch 256,256. "
                        "Ignored when --resume-from is set (architecture is locked).")
    p.add_argument("--ue-d-min",         type=float, default=50.0,
                   help="Minimum UE distance (m) for physics-DT topology. Default: 50.")
    p.add_argument("--ue-d-max",         type=float, default=300.0,
                   help="Maximum UE distance (m) for physics-DT topology. Default: 300.")
    p.add_argument("--pt-5g3e-multi-site", action="store_true",
                   help="Multi-site mode: --pt-5g3e must point to the RAN_level directory. "
                        "At each episode reset, a random site is selected to test "
                        "policy generalisation across all available site profiles.")
    args = p.parse_args()

    _ensure_results_dir(args.results_dir)

    fixed_overrides: Dict[str, float] = {}
    for pair in args.fix_param:
        name, _, raw_val = pair.partition("=")
        fixed_overrides[name.strip()] = float(raw_val.strip())

    from .env import DEFAULT_REWARD_WEIGHTS
    reward_weights = dict(DEFAULT_REWARD_WEIGHTS)
    for pair in args.reward_weight:
        name, _, raw_val = pair.partition("=")
        reward_weights[name.strip()] = float(raw_val.strip())

    def env_factory() -> DigitalTwinFidelityEnv:
        cfg = EnvConfig(
            backend=args.backend,
            pt_history_path=args.pt_history,
            dt_history_path=args.dt_history,
            pt_live_path=args.pt_live,
            dt_live_path=args.dt_live if args.dt_live else None,
            max_episode_steps=args.episode_steps,
            history_seed=args.seed,
            live_step_sleep=args.live_step_sleep,
            pt_5g3e_path=args.pt_5g3e if args.pt_5g3e else None,
            ue_d_min=args.ue_d_min,
            ue_d_max=args.ue_d_max,
            pt_5g3e_multi_site=args.pt_5g3e_multi_site,
            signed_observations=not args.unsigned_obs,
            fixed_action_overrides=fixed_overrides,
            reward_weights=reward_weights,
        )
        return DigitalTwinFidelityEnv(cfg)

    if not args.no_baselines:
        print("[*] Computing baselines (default / random / grid_best)...")
        try:
            baseline_results = [
                baseline_default(env_factory(), episodes=3),
                baseline_random(env_factory(), episodes=3, seed=args.seed),
                baseline_grid(env_factory(), episodes=1, points=3),
            ]
        except FileNotFoundError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            print(
                "[hint] Run the pipeline once to populate the histories, or "
                "pass --pt-history / --dt-history to point at snapshot files.",
                file=sys.stderr,
            )
            return 2

        _save_baselines(os.path.join(args.results_dir, "baselines.json"), baseline_results)
        for r in baseline_results:
            print(
                f"  - {r.name:>10} | reward={r.mean_reward:>8.3f} ± {r.std_reward:.3f}"
                f" | thr={r.component_means.get('throughput_mbps', 0):.2f} Mbps"
                f"  sinr_dl={r.component_means.get('sinr_dl', 0):.2f} dB"
            )

    if args.baselines_only:
        return 0

    use_ppo = args.algo == "ppo" or (args.algo == "auto" and _has_sb3())

    if args.algo == "ppo" and not _has_sb3():
        print("[ERROR] --algo ppo requested but stable-baselines3 is not installed.", file=sys.stderr)
        print("        pip install stable-baselines3", file=sys.stderr)
        return 1

    if use_ppo:
        print(
            f"[*] Training PPO  timesteps={args.timesteps}"
            f"  backend={args.backend}"
            f"  episode_steps={args.episode_steps}"
            f"  n_steps={args.ppo_n_steps}"
            f"  lr={args.ppo_lr}"
            f"  ent={args.ppo_ent_coef}"
        )
        try:
            net_arch = [int(x) for x in args.net_arch.split(",")]
            curve, best_action = train_with_sb3(
                env_factory,
                total_timesteps=args.timesteps,
                seed=args.seed,
                results_dir=args.results_dir,
                n_steps=args.ppo_n_steps,
                batch_size=args.ppo_batch_size,
                learning_rate=args.ppo_lr,
                ent_coef=args.ppo_ent_coef,
                resume_from=args.resume_from if args.resume_from else None,
                net_arch=net_arch,
            )
        except Exception as exc:
            print(f"[WARN] PPO failed ({exc}); falling back to CEM.", file=sys.stderr)
            use_ppo = False

    if not use_ppo:
        print(f"[*] Training CEM  iters={args.cem_iterations}  pop={args.cem_population}")
        curve, best_action = train_with_cem(
            env_factory,
            args.cem_iterations,
            args.cem_population,
            args.cem_elite_frac,
            args.cem_sigma,
            args.seed,
        )

    curve_path  = os.path.join(args.results_dir, "learning_curve.csv")
    action_path = os.path.join(args.results_dir, "best_action.json")
    write_curve(curve_path, curve)
    _save_best_action(action_path, best_action)

    print(f"[ok] Learning curve : {curve_path}  ({len(curve)} episodes)")
    print(f"[ok] Best action    : {best_action}")
    return 0


def _has_sb3() -> bool:
    try:
        import stable_baselines3  # noqa: F401
        return True
    except ImportError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
