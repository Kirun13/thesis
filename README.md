# Federated edge IDS for MQTT: detection-to-enforcement latency

Code, protocols and results for the paper *Detection-to-enforcement latency and service trade-offs in a federated edge MQTT intrusion detection testbed*. Everything runs on one laptop with Docker Desktop; it is a controlled laboratory testbed, not a production deployment.

| Experiment | Protocol | Results |
|---|---|---|
| 1. Public-data detection: Edge-IIoTset, centralized vs FedAvg (IID / non-IID) MLP and GRU, 12 jobs | [PROTOCOL.md](PROTOCOL.md) | [results/detection](results/detection) |
| 2. Feature-ready response: local vs controller authorization, 3,600 paired trials | [RESPONSE_PROTOCOL.md](RESPONSE_PROTOCOL.md) | [results/response](results/response) |
| 3. Traffic-linked MQTT detection and mitigation, 21 detectors + 60 system episodes (main paper results) | [ONLINE_PROTOCOL.md](ONLINE_PROTOCOL.md) | [results/online](results/online) |
| Audit of records excluded from Edge-IIoTset | — | [results/data-audit](results/data-audit) |

`response_2b/` holds a prepared controller-delay sweep ([PROTOCOL_2B.md](response_2b/PROTOCOL_2B.md)). It was not executed and is not part of the paper.

## Layout

- `scripts/` — data preparation, training, experiment runners, reports, verification, paper statistics and figures
- `online/`, `response/`, `response_2b/` — Docker images and lab services (edge, controller, MQTT clients)
- `tests/` — unit tests (`npm run check`)
- `results/` — final summaries copied from the git-ignored `runs/`; `results/online/models/` contains the 21 frozen TorchScript detectors, their preprocessing and thresholds (`models.json`); the deployed one is `fedmlp-noniid-p42-s42`

## Paper statistics and figures

These read only `results/` and work on a fresh clone:

```powershell
python scripts/paper_stats.py     # paired Wilcoxon tests -> results/online/paired-tests.json
python scripts/paper_figures.py   # figures 1-4 -> results/figures/
```

## Reproducing the experiments

Requirements: Python 3.13 with the packages in `requirements.txt` (it names the CUDA wheel index), Node.js for the npm scripts, Docker Desktop with Linux containers (iptables and `tc netem` are checked by the smoke tests). Raw data, PCAPs and full run directories are written to `data/` and `runs/`, which are git-ignored.

```powershell
# 1. Public-data detection
npm run data:download; npm run data:prepare; npm run check; npm run smoke
npm run experiment:start        # detached; also experiment:status / experiment:stop; rerun start with a run dir to resume
npm run report

# 2. Feature-ready response
npm run response:prepare; npm run response:build; npm run response:smoke; npm run response:run; npm run response:report
npm run response:down

# 3. Traffic-linked MQTT
npm run online:audit; npm run online:plan; npm run online:build
npm run online:collect; npm run online:study; npm run online:smoke; npm run online:system; npm run online:report
python scripts/verify_online.py   # provenance check, needs the services running
npm run online:down
```

Runs are resumable: completed jobs, trial pairs and episodes are skipped and never overwritten; failed outcomes stay in the denominators. Each run saves its source snapshot, checksums, environment and package versions. The episode plan and recipes of experiment 3 are frozen; a new scientific run needs a new plan version and output directory.
