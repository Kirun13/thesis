# Experiment 2b: controller-delay sweep

Same question, models, 200 replayed records, local/central modes, edge firewall helper and measurement boundary as experiment 2 (RESPONSE_PROTOCOL.md, unchanged). Only the delay grid, the timeout accounting and the report differ. Experiment 2's files, ledger, Compose project and networks are not modified or reused.

## What differs from experiment 2

| | Experiment 2 | Experiment 2b |
|---|---|---|
| One-way control delays | 0, 10, 50 ms | 0, 10, 50, 100, 250 ms (+ optional 500 ms: `--include-500`) |
| Trials | 3,600 | 6,000 (7,200 with 500 ms) |
| Scheduler seed | 20261105 | 20261109 (rate profile: 20261110) |
| Trial RPC timeout | 1 s | 1 s (unchanged) |
| RTT calibration timeout | 1 s | 10 s, on a separate connection |
| Runner → edge API timeout | 10 s | 60 s (`configure` includes calibration) |
| Timeout accounting | inside generic failures | `failure_kind='timeout'` counted separately |
| Compose project / image | `thesis-response` | `thesis-response-2b` / `thesis-response-2b:local` |
| Subnets | 172.30.93.0/24, 172.30.94.0/24 | 172.30.103.0/24, 172.30.104.0/24 |

Blocks of 20 observations, randomized block/record order and 10/10 local-first/central-first balance are as in experiment 2. Ledger rows additionally carry `label` and `attack_type` so that attack denominators do not depend on assumptions about the sample.

## Inputs

`scripts/prepare_response_2b.py` reads only `data/response/` (`manifest.json`, `observations.json`, `smoke-observations.json`, `model-*.pt`), verifies each against the checksums frozen by experiment 2, copies them to `data/response_2b/` and writes a new `ledger.jsonl` and `manifest.json` with SHA-256 checksums. It does not read `data/processed/benchmark.npz` or experiment 2's `ledger.jsonl`, and never writes to `data/response/`. `smoke-observations.json` is needed because the smoke gate uses validation-derived clear block/allow cases that cannot be rebuilt without the benchmark file.

## Timeouts and fail-open accounting

A central trial whose controller reply does not arrive within 1 s is a `controller_failure` with `failure_kind='timeout'`. The connection is discarded, no local fallback is applied, no latency is assigned, and the trial stays in every denominator. Note that with one-way delay `d` the policy exchange takes about `2d`, so 500 ms one-way (RTT ≈ 1 s) is expected to time out by construction; 250 ms (RTT ≈ 0.5 s) is expected to stay inside the timeout. At 500 ms the trial connection cannot be warmed either, so each central trial includes a TCP reconnect inside the 1 s window; this is recorded (`trial_connection_warm_ok`) and is part of why that condition is a timeout-regime observation rather than a latency measurement.

## Report

Pooled over the three model seeds (also per seed in `summary-by-seed.csv`): median and p95 of feature-ready-to-firewall-command-completion for verified blocks by delay and mode; share of block decisions whose controller reply arrived inside the timeout; share of attack observations left unblocked because of a timeout; and timeouts over assigned trials. Paired central − local differences use only pairs with two verified blocks. The regression fits paired added time on the median policy-RPC RTT measured in the same block's calibration; pairs in a block share one RTT value, so ordinary independent-sample standard errors are omitted. Calibration RTT, not nominal delay, is the regressor.

## Stage 2: flow-rate profile (separate)

`--profile rate` / `rate-smoke` run a distinct ledger (`ledger-rate.jsonl`, `manifest-rate.json`) and gate (`rate-smoke-latest.json`); the base profile, its code paths and its gate are not affected. Default grid: probe rates 200/800/2500 packets/s × delays 0/50 ms × seed 42 × 200 records × 2 modes = 2,400 trials (`--rate-seeds`, `--rate-delays` change this). The rate is that of the UDP probe stream from the replay client (200 pkt/s is the 5 ms interval of experiment 2); the model's input is unaffected. In this profile only, the edge chain gets a target-less counting rule for the replay client's source before any DROP, which yields per trial:

- `chain_arrived_packets`: packets from the client that reached the chain during the trial (counter delta, snapshot taken before t0);
- `drop_packets`: hits on the DROP rule;
- `passed_in_counter_interval_packets`: arrived minus dropped over the bracketed counter interval (which begins before t0).

The achieved ingress rate is recorded (`counter_ingress_rate_pps`); a Python sender may fall short of 2,500 pkt/s on a given host, so the report should be read with the achieved, not the target, rate. Probe load shares edge CPU 0 with inference, which is the point of the profile and also a confound with the counting rule's own cost.

## Review corrections

The one-second trial deadline covers reconnect, send and the entire framed reply together, using a monotonic deadline. Calibration retains a separate ten-second total deadline. Non-timeout controller errors are not successful authorizations. An attack is attributed to a timeout only if the detector actually requested block; detector misses are counted separately. Ordinary OLS standard errors are suppressed because RTT measurements are shared within blocks.

Rate-profile counters report `passed_in_counter_interval_packets`, not an exact t0-to-installation count. The journal brackets both counter reads and records the pre-t0 interval and counter boundary uncertainty. Achieved ingress rate is estimated over that counter interval, including packets later dropped; post-command sender rate remains only a verification diagnostic. UDP packets are not MQTT messages and the probe stream is not classified. Run projects sequentially because their CPU affinities overlap.

Execution status: code and tests are prepared; no new full or rate-profile measurements accompany this change. The base profile assigns 6,000 trials (7,200 with 500 ms); the separate rate profile assigns 2,400 by default. Interpret 500 ms as a configured deadline stress condition, not a universal network failure threshold.
