# Edge IDS experiment

Run commands from this folder with npm. Training uses the existing Python 3.13 / PyTorch environment; npm adds no JavaScript dependencies. See PROTOCOL.md for experimental definitions and limits.

```powershell
npm install
npm run data:download
npm run data:prepare
npm run check
npm run smoke
npm run experiment:start
npm run experiment:status
npm run report
```

`experiment:start` starts a hidden detached Python process and saves its PID, run directory, and console log under `runs`. `experiment:stop` requests a graceful stop; the last completed epoch/round is retained. To resume a stopped run:

```powershell
npm run experiment:start -- runs/EXISTING-RUN-DIRECTORY
```

Keep the laptop plugged in and the lid open. Training requests Windows to prevent idle sleep while the process is running, without changing system power settings. Closing the lid, explicit sleep, power loss, or restart can interrupt it. Completed jobs are skipped on resume. Best and last checkpoints are saved after every complete epoch/round. Summary files are generated after completion; `npm run report` also summarizes currently completed jobs.

`runs/<run>/RESULTS.md` and `summary.csv` contain the comparison. Each job has `result.json`, `history.jsonl`, `best.pt`, `last.pt`, and (for full runs) `test_predictions.npz`. Data preparation audit is under `data/processed/audit.json`. Raw data and generated results are git-ignored.

For a fresh Python setup, install the versions recorded in requirements.txt using Python's package installer in an isolated environment, with the CUDA wheel index specified there. Do not replace the GPU build with an unverified CPU installation. The current verified hardware is a GTX 1650 Ti (4 GB); package and environment metadata are saved per run.

## Response experiment

The independent GPT-6 Astra review is in REVIEW_RESPONSE.md; the updated plan is PLAN_RESPONSE.md. The exact implemented measurement protocol and limits are in RESPONSE_PROTOCOL.md. Existing training results are preserved.

```powershell
npm run response:prepare
npm run response:build
npm run response:smoke
npm run response:run
npm run response:report
npm run response:down
```

The full run executes 3,600 predeclared feature-replay/enforcement trials. Results are under `runs/response/full-<UTC timestamp>/`: RESULTS.md, summary.csv, paired-differences.csv, audit-summary.json, response-latency.png and append-only attempts.jsonl. The active run directory is recorded in runs/response/active.json; status.json within it reports progress. A partial report can be generated while running; only the completed report covers the whole ledger.

To request a graceful stop, create a file named STOP inside the active full-run directory. After the process exits, remove that file and resume without changing source/artifacts:

```powershell
npm run response:run -- --resume runs/response/EXISTING-FULL-RUN
```

Completed pairs are retained, including failed outcomes; partial pairs are repeated in a new recorded segment. Source and model/data checksums must match. Rerun smoke after changing the network service code. This experiment prevents idle sleep while active but does not override closing the lid or explicit sleep.

The measured primary duration starts after a standardized feature record is ready at edge and ends when the firewall command returns. Separate UDP packets and kernel DROP counters verify filtering. This does not measure live packet capture/feature extraction and does not classify the generated UDP probe bytes. No ports are published on the host; only the dedicated containers' network namespaces are modified.
