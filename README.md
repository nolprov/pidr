# Codebase NDT Data Generation

## Requirements

- Python 3.9+, `stable-baselines3`, `gymnasium` or `gym`
- OMNeT++ 6 + INET + Simu5G (Physical Twin)
- ns-3-dev + ns3-nr (Digital Twin)
- Eclipse Ditto (synchronization hub, via Docker)

```bash
pip install stable-baselines3 gymnasium numpy
```

## Lancer le pipeline complet

```bash
export OMNET_RUN_CMD='../FiveG_network -u Cmdenv -f omnetpp.ini -c DT-Scenario'
export NS3_RUN_CMD='/path/to/ns-3.40/ns3 run scratch/FiveG_digital_twin'
./scripts/run_full_pipeline.sh
```

Cette commande lance OMNeT++ (PT), Eclipse Ditto, le pont de synchronisation et ns-3 (DT) dans cet ordre.

## Entraînement de l'agent

### Avec le dataset 5G3E (traces srsGNB réelles)

```bash
python -m agent.train \
  --backend offline \
  --pt-5g3e 5G3E-dataset/version2/SampleData/RAN_level/site1_2 \
  --timesteps 100000
```

### Live (simulators running)

```bash
python -m agent.train --backend live --timesteps 50000 --live-step-sleep 0.5
```

### Démarrage à chaud en reprenant le dernier checkpoint

```bash
python -m agent.train --resume-from results/ppo_model_final.zip --timesteps 50000
```

### Arguments utiles

| Flag | Default | Description |
|------|---------|-------------|
| `--algo` | `auto` | `ppo`, `cem`, or `auto` |
| `--timesteps` | 50000 | Nombre total d'étapes |
| `--episode-steps` | 64 | Étapes par épisode |
| `--ppo-lr` | 3e-4 | Learning rate|
| `--ppo-n-steps` | 256 | Rollout buffer size |
| `--net-arch` | `128,128` | Couches cachées MLP  |
| `--unsigned-obs` | off | Erreurs en valeur absolue |
| `--reward-weight NAME=VAL` | — | Remplacer le poids d'une reward |
| `--no-baselines` | off | Ignore le calcul des baselines|

## Appliquer la meilleure action pour ns-3

```bash
python scripts/tune_network_params.py \
  --ns3-gnb-tx 46.0 --ns3-ue-tx 23.0 \
  --ns3-gnb-nf 5.0  --ns3-ue-nf 7.0
```

Utiliser `--dry-run` pour prévisualiser sans écrire.

## Outputs

Écrit dans `--results-dir` (default: `results/`):

| File | Description |
|------|-------------|
| `learning_curve.csv` | Reward par épisode et par métriques |
| `best_action.json` | Meilleure action trouvée, prêt pour ns-3 |
| `baselines.json` | Scores par défaut / aléatoire |
| `ppo_model_final.zip` | Modèle final (peut être appelé avec `--resume-from`) |

