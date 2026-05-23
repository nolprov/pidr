# NDT Data Generation

DRL agent (PPO/CEM) that minimizes the fidelity gap between a 5G Physical Twin (OMNeT++) and its Digital Twin (ns-3 NR), synchronized via Eclipse Ditto.

## Prerequisites

- Python 3.9+, `stable-baselines3`, `gymnasium` or `gym`
- OMNeT++ 6 + INET + Simu5G (Physical Twin)
- ns-3-dev + ns3-nr (Digital Twin)
- Eclipse Ditto (synchronization hub, via Docker)

```bash
pip install stable-baselines3 gymnasium numpy
```

## Install (full stack)

```bash
git clone https://github.com/AbdessamedSed/NDT_data_generation.git
cd NDT_data_generation
chmod +x scripts/install_all_tools.sh
./scripts/install_all_tools.sh
```

Builds OMNeT++, INET, Simu5G, and ns-3 from the vendored sources in `external/`.

## Run the full pipeline

```bash
export OMNET_RUN_CMD='../FiveG_network -u Cmdenv -f omnetpp.ini -c DT-Scenario'
export NS3_RUN_CMD='/path/to/ns-3.40/ns3 run scratch/FiveG_digital_twin'
./scripts/run_full_pipeline.sh
```

This starts OMNeT++ (PT), Eclipse Ditto, the synchronization bridges, and ns-3 (DT) in order.

## Agent training

### Offline (no simulators required)

```bash
python -m agent.train \
  --backend offline \
  --pt-history third_party/physical_twin_history.json \
  --dt-history third_party/dt_collected_history.json \
  --timesteps 100000 \
  --results-dir results/
```

### With 5G3E dataset (real srsGNB traces)

```bash
python -m agent.train \
  --backend offline \
  --pt-5g3e 5G3E-dataset/version2/SampleData/RAN_level/site1_2 \
  --timesteps 100000
```

Use `--pt-5g3e-multi-site` with `--pt-5g3e` pointing to `RAN_level/` to train across all sites.

### Live (simulators running)

```bash
python -m agent.train --backend live --timesteps 50000 --live-step-sleep 0.5
```

### Warm start from checkpoint

```bash
python -m agent.train --resume-from results/ppo_model_final.zip --timesteps 50000
```

### Key flags

| Flag | Default | Description |
|------|---------|-------------|
| `--algo` | `auto` | `ppo`, `cem`, or `auto` |
| `--timesteps` | 50000 | Total PPO steps |
| `--episode-steps` | 64 | Steps per episode |
| `--ppo-lr` | 3e-4 | Learning rate |
| `--ppo-n-steps` | 256 | Rollout buffer size |
| `--net-arch` | `128,128` | MLP hidden layers |
| `--unsigned-obs` | off | Absolute instead of signed errors |
| `--fix-param NAME=VAL` | — | Fix an action parameter (repeatable) |
| `--reward-weight NAME=VAL` | — | Override a reward weight (repeatable) |
| `--no-baselines` | off | Skip baseline computation |

## Apply best action to ns-3

```bash
python scripts/tune_network_params.py \
  --ns3-gnb-tx 46.0 --ns3-ue-tx 23.0 \
  --ns3-gnb-nf 5.0  --ns3-ue-nf 7.0
```

Use `--dry-run` to preview without writing.

## Outputs

Written to `--results-dir` (default: `results/`):

| File | Description |
|------|-------------|
| `learning_curve.csv` | Per-episode reward and metric breakdown |
| `best_action.json` | Best action found, ready for ns-3 |
| `baselines.json` | Default / random / grid scores |
| `ppo_model_final.zip` | Final model (resumable with `--resume-from`) |

## Project structure

```
agent/
  train.py          training entry point (PPO + CEM)
  env.py            Gym environment (offline + live backends)
  baselines.py      default / random / grid baselines
  state.py          PT/DT snapshot data structures
  loaders/
    physics.py      3GPP TR 38.901 UMa physics model
    five_g3e.py     5G3E v2 dataset loader (srsGNB JSONL)
scripts/
  tune_network_params.py  apply action to OMNeT++ ini and ns-3 source
  run_full_pipeline.sh    orchestrate full PT + Ditto + DT pipeline
third_party/        recorded PT/DT snapshot histories and mock tools
5G3E-dataset/       real srsGNB measurement traces
omnet/              OMNeT++ Physical Twin project
ns3/                ns-3 NR Digital Twin application
ditto/              Eclipse Ditto configuration and bridges
```
