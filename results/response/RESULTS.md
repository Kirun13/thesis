# Feature-ready to firewall-command completion

Same frozen non-IID FedAvg GRU and validation threshold in local and controller-mediated modes. CPU inference in isolated Linux containers on Docker Desktop; three model seeds on one laptop.

Assigned trials: 3600. Unique terminal trials: 3600. Unexecuted/incomplete: 0. Completed pairs: 1800.

| Seed | Nominal one-way control delay (ms) | Mode | Successful blocks / block decisions | Median (ms) | p95 (ms) | Failures / assigned |
|---:|---:|---|---:|---:|---:|---:|
| 42 | 0 | central | 101/101 | 3.968 | 5.141 | 0/200 |
| 42 | 0 | local | 101/101 | 3.573 | 4.856 | 0/200 |
| 42 | 10 | central | 101/101 | 24.433 | 25.628 | 0/200 |
| 42 | 10 | local | 101/101 | 3.608 | 4.567 | 0/200 |
| 42 | 50 | central | 101/101 | 104.596 | 105.925 | 0/200 |
| 42 | 50 | local | 101/101 | 3.613 | 4.869 | 0/200 |
| 43 | 0 | central | 100/100 | 4.132 | 5.037 | 0/200 |
| 43 | 0 | local | 100/100 | 3.566 | 4.705 | 0/200 |
| 43 | 10 | central | 100/100 | 24.347 | 26.231 | 0/200 |
| 43 | 10 | local | 100/100 | 3.602 | 4.740 | 0/200 |
| 43 | 50 | central | 100/100 | 104.533 | 105.955 | 0/200 |
| 43 | 50 | local | 100/100 | 3.596 | 4.800 | 0/200 |
| 44 | 0 | central | 100/100 | 4.059 | 5.365 | 0/200 |
| 44 | 0 | local | 100/100 | 3.551 | 4.798 | 0/200 |
| 44 | 10 | central | 100/100 | 24.599 | 25.747 | 0/200 |
| 44 | 10 | local | 100/100 | 3.606 | 4.728 | 0/200 |
| 44 | 50 | central | 100/100 | 104.507 | 105.588 | 0/200 |
| 44 | 50 | local | 100/100 | 3.598 | 4.611 | 0/200 |

## Matched local/central differences

Differences are central minus local within the same record/model/delay pair. Only pairs with two verified block outcomes enter these conditional latency statistics. Allow pairs and failed/incomplete pairs remain in the audit denominators.

| Seed | One-way delay (ms) | Comparable block pairs / assigned pairs | Median added time (ms) | p95 added time (ms) |
|---:|---:|---:|---:|---:|
| 42 | 0 | 101/200 | 0.419 | 1.590 |
| 42 | 10 | 101/200 | 20.799 | 22.223 |
| 42 | 50 | 101/200 | 100.935 | 102.287 |
| 43 | 0 | 100/200 | 0.418 | 1.584 |
| 43 | 10 | 100/200 | 20.797 | 22.323 |
| 43 | 50 | 100/200 | 100.875 | 102.223 |
| 44 | 0 | 100/200 | 0.488 | 1.543 |
| 44 | 10 | 100/200 | 20.896 | 22.128 |
| 44 | 50 | 100/200 | 100.925 | 102.087 |

## Network calibration

| Nominal one-way delay (ms) | Measured policy-RPC median RTT (ms) |
|---:|---:|
| 0 | 0.227 |
| 10 | 20.634 |
| 50 | 100.673 |

## Decisions and verification

See summary.csv for mitigated attacks / 100 attack observations, actual false blocks / 100 benign observations, classification block decisions, allow latency, inference, command execution, verification bounds and every status count, for each model/delay/mode. Raw append-only attempts and every earlier partial attempt are preserved.

Observation attack-type mix: {"Normal": 100, "Backdoor": 8, "DDoS_TCP": 26, "DDoS_HTTP": 9, "Port_Scanning": 5, "DDoS_ICMP": 27, "Vulnerability_scanner": 12, "DDoS_UDP": 8, "Ransomware": 5}.

## Measurement limits

- t0 follows decoding and validation of a complete standardized feature vector; tensor creation and inference are included. Capture, extraction, preprocessing and delivery to edge are excluded.
- Command return is an observed upper bound on installation time, not an instrumented kernel commit timestamp. Independent kernel DROP counters and post-command probes confirm actual filtering; the same UDP service remains reachable from the health source.
- Probe interval is 5 ms; a fixed 25 ms post-command observation window and counter-read overhead are included only in the separate verification upper bound.
- Feature vectors are replayed from Edge-IIoTset. Synthetic UDP probe bytes are not classified by the model; they validate enforcement only.
- 100 benign and 100 attack observations form a balanced, small systems sample, not natural traffic prevalence. No newly observed test result changes a model, threshold or sampling rule.
- Sequential warmed trials describe this virtualized laptop without saturation. Three frozen model seeds are not independent hardware replications; p95 is descriptive.
- All time differences use edge monotonic timestamps. Controller failures are fail-open, with no hidden local retry or fallback.
- This is not raw-packet-arrival-to-response latency and does not show that federated training itself reduces response time.
