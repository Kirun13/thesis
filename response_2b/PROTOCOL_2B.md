# Experiment 2b: controller-delay sweep (prepared, not executed)

Code and tests are ready; no measurements exist and nothing here is used in the paper. Question, models, the 200 replayed records, local/central modes, edge firewall helper and measurement boundary are those of experiment 2 (RESPONSE_PROTOCOL.md). Experiment 2's files, ledger, Compose project and networks are not modified or reused.

## Differences from experiment 2

| | Experiment 2 | Experiment 2b |
|---|---|---|
| One-way control delays | 0, 10, 50 ms | 0, 10, 50, 100, 250 ms (+ 500 ms with `--include-500`) |
| Trials | 3,600 | 6,000 (7,200 with 500 ms) |
| Scheduler seed | 20261105 | 20261109 (rate profile: 20261110) |
| RTT calibration timeout | 1 s | 10 s, separate connection |
| Runner → edge API timeout | 10 s | 60 s (`configure` includes calibration) |
| Timeouts | among generic failures | `failure_kind='timeout'`, counted separately |
| Compose project / image | `thesis-response` | `thesis-response-2b` / `thesis-response-2b:local` |
| Subnets | 172.30.93.0/24, 172.30.94.0/24 | 172.30.103.0/24, 172.30.104.0/24 |

Ledger rows also carry `label` and `attack_type`. `scripts/prepare_response_2b.py` copies the frozen experiment-2 inputs from `data/response/` to `data/response_2b/` after verifying their checksums and writes a new ledger; it never writes to `data/response/`.

## Timeouts

The trial RPC deadline stays 1 s and covers reconnect, send and the full reply. A central trial without a reply in time is a fail-open `controller_failure` with no latency and no local fallback, and stays in every denominator. With one-way delay `d` the exchange takes about `2d`, so 500 ms is a timeout condition by construction, not a latency measurement. An attack counts as lost to a timeout only if the detector requested a block.

## Report

Median/p95 command-completion time for verified blocks by delay and mode (pooled and per seed); share of block decisions answered in time; attacks left unblocked by timeouts; paired central − local differences over pairs with two verified blocks, regressed on the measured calibration RTT of the same block (no OLS standard errors, since pairs in a block share one RTT).

## Rate profile (`--profile rate`)

Separate ledger and smoke gate. Probe rates 200/800/2,500 packets/s × delays 0/50 ms × seed 42 × 200 records × 2 modes = 2,400 trials. A counting rule before the DROP yields packets arriving at the chain, dropped packets and packets passed in the counter interval (which starts before t0). Report achieved, not target, ingress rate. UDP probes are not MQTT messages and are not classified.
