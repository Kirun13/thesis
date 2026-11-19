# Traffic-linked MQTT experiment

Independent captured episodes; all ambiguous/repeated windows retained. Packet/window counts are not treated as independent traffic-episode replications.

## Detector quality on held-out episodes

| Method | Partition seed | Training repeats | F1 mean | FPR mean | Recall mean |
|---|---:|---:|---:|---:|---:|
| fedgru-noniid | 42 | 3 | 0.8804 | 0.0197 | 0.8686 |
| fedmlp-iid | 42 | 3 | 0.9785 | 0.0078 | 0.9976 |
| fedmlp-noniid | 42 | 3 | 0.8072 | 0.0073 | 0.7032 |
| fedmlp-noniid | 43 | 3 | 0.0144 | 0.0009 | 0.0073 |
| fedmlp-noniid | 44 | 3 | 0.8224 | 0.0092 | 0.7324 |
| gru-central | — | 3 | 0.9497 | 0.0078 | 0.9416 |
| mlp-central | — | 3 | 0.9786 | 0.0082 | 1.0000 |
| rate-threshold | — | 1 | 0.9485 | 0.0082 | 0.9416 |

Per-model results, confusion counts and episode-bootstrap intervals are preserved under detectors-v1. The rate-threshold baseline uses the same validation FPR constraint as neural models.

## Service and response, episode-level aggregation

Completed condition episodes: 60/60; valid capture/label reconstructions: 58/60. The regular matrix repeats nine independent workload seeds across six conditions; three additional workload seeds are paired across local/central outage conditions. Repeated conditions are paired measurements, not additional independent workloads.

| Rate level | One-way delay (ms) | Mode | Outage | Episodes | Valid | Responded / assigned | Benign delivery mean | Attack messages mean | Conditional response median (ms) |
|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| 0 | 0 | central | False | 3 | 3 | 1/3 | 1.0000 | 509.0 | 374.57 |
| 0 | 0 | local | False | 3 | 3 | 1/3 | 1.0000 | 507.3 | 376.71 |
| 0 | 0 | none | False | 3 | 3 | 0/3 | 1.0000 | 519.7 | N/A |
| 0 | 50 | central | False | 3 | 3 | 1/3 | 1.0000 | 507.0 | 476.80 |
| 0 | 50 | local | False | 3 | 3 | 1/3 | 1.0000 | 503.0 | 375.91 |
| 0 | 50 | none | False | 3 | 3 | 0/3 | 1.0000 | 519.7 | N/A |
| 1 | 0 | central | False | 3 | 3 | 3/3 | 0.9395 | 975.3 | 260.49 |
| 1 | 0 | central | True | 3 | 3 | 0/3 | 1.0000 | 2067.0 | N/A |
| 1 | 0 | local | False | 3 | 3 | 3/3 | 0.8966 | 1016.7 | 260.43 |
| 1 | 0 | local | True | 3 | 3 | 3/3 | 0.9333 | 875.3 | 183.99 |
| 1 | 0 | none | False | 3 | 3 | 0/3 | 1.0000 | 2053.7 | N/A |
| 1 | 50 | central | False | 3 | 3 | 3/3 | 1.0000 | 1078.7 | 359.09 |
| 1 | 50 | local | False | 3 | 3 | 3/3 | 0.9479 | 990.0 | 259.78 |
| 1 | 50 | none | False | 3 | 3 | 0/3 | 1.0000 | 2053.7 | N/A |
| 2 | 0 | central | False | 3 | 3 | 3/3 | 0.9074 | 1710.0 | 67.58 |
| 2 | 0 | local | False | 3 | 3 | 3/3 | 0.9626 | 2720.3 | 67.32 |
| 2 | 0 | none | False | 3 | 3 | 0/3 | 1.0000 | 7033.7 | N/A |
| 2 | 50 | central | False | 3 | 3 | 3/3 | 0.9834 | 2917.3 | 171.45 |
| 2 | 50 | local | False | 3 | 2 | 2/3 | 0.9082 | 2357.0 | 62.06 |
| 2 | 50 | none | False | 3 | 2 | 0/3 | 1.0000 | 7033.7 | N/A |

## Matched local/controller comparisons

| One-way delay (ms) | Outage | Assigned pairs | Both valid | Both responded | Median central minus local response (ms) |
|---:|---|---:|---:|---:|---:|
| 0 | False | 9 | 9 | 7 | 0.26 |
| 0 | True | 3 | 3 | 0 | N/A |
| 50 | False | 9 | 8 | 6 | 99.27 |

## Response decomposition (conditional on a valid attack-window-triggered response)

| Delay | Mode | Outage | Responded | First attack window ready (ms) | Subsequent-window wait (ms) | Queue (ms) | Inference (ms) | Authorization + enforcement (ms) |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 0 | central | False | 7 | 106.21 | 0.00 | 0.62 | 0.11 | 4.13 |
| 0 | central | True | 0 | N/A | N/A | N/A | N/A | N/A |
| 0 | local | False | 7 | 105.11 | 0.00 | 0.51 | 0.28 | 4.08 |
| 0 | local | True | 3 | 179.35 | 0.00 | 0.56 | 0.08 | 3.44 |
| 50 | central | False | 7 | 104.83 | 0.00 | 0.68 | 0.15 | 104.16 |
| 50 | local | False | 6 | 114.05 | 0.00 | 0.73 | 0.36 | 4.71 |

A missing response is retained as a coverage outcome, not zero latency. A successful detection response requires that the actual triggering source window contains independently reconciled malicious message bytes. Pre-onset blocks and post-onset blocks triggered by benign windows are separately counted in system-episodes.csv. Invalid capture/label reconstructions are retained and flagged; their candidate latencies are excluded from primary response summaries. Service summaries include all completed episodes using independent subscriber records. First-window readiness includes accumulation and the fixed20ms holdback; waiting for later triggering windows is a separate term. Queue, inference and combined authorization/enforcement are directly timestamped; RPC and firewall installation cannot be separately estimated from this journal. Component medians need not sum to the median total. Command return is an observed installation upper bound; historical kernel DROP counters and real subscriber delivery provide separate enforcement evidence.

## Service cost, capture reliability and interpretation

Without mitigation, legitimate-message delivery was 100% in every episode. Thus this workload does not demonstrate an availability improvement. Mitigation reduces delivered attacking messages, but can also suppress legitimate messages from the blocked source. Both other publishers retain 100% legitimate-message delivery in all 60 episodes. Delivery is divided by the independently preplanned offered message count, including messages never attempted or socket-accepted. Normal-message median/p95 columns measure actual send-to-subscriber receipt, conditional on delivery; normal_planned_to_delivery_p95_ms additionally includes scheduling/connection delay. The generator saves exact aggregate attempts/errors/skips and per-message accepted IDs; attempted benign counts are only bounded when a failed attempt lacks a tag. Socket acceptance is not proof of packet ingress or service delivery.

Worst post-attack recovery delivery ratio (scheduled after attack end + nominal TTL): 0.5086. TTL expiry alone does not guarantee immediate recovery: later decisions and TCP state can extend service disruption.

| Invalid episode | Capture/label reconstruction issues | Kernel capture drops | Late packets |
|---|---|---:|---:|
| system-08-d50-local | kernel_drops,mqtt_parse_errors | 2 | 0 |
| system-08-d50-none | kernel_drops,late_packets,missing_tcp_bytes,mqtt_parse_errors,feature_parity | 274 | 1401 |

Valid reconstructed episodes: 58; false triggering-window block commands within them: 0. Invalid reconstruction cannot establish absence of false blocks. Observed historical firewall DROP packets across all completed episodes: 2579. Controller response failures: 16. In central outage episodes, 42/43/44 windows respectively remained unprocessed at episode stop; timeout-induced inference-queue backlog is part of the fail-open outcome.

Primary deployed model was preselected independently of test scores: fedmlp-noniid-p42-s42, threshold 0.499143; held-out F1=0.7966, recall=0.6861. Non-IID partition43 failures are retained. This study does not establish that FedAvg or GRU outperforms centralized MLP or a rate threshold.

## Scope and limits

Synthetic MQTT publish-flood episodes on one Docker Desktop VM. The new12-field causal source-window model is separately trained; earlier34-field public-dataset scores do not transfer to this experiment. The broker sees edge SNAT; publisher attribution is via independent generator/subscriber message IDs. Original source addresses remain available to the edge FORWARD policy before SNAT. No address/port value, payload identifier or ground-truth tag is a model feature. Controller mode authorizes flagged edge alerts. Fail-open outage and TTL recovery trade-offs remain in reported outcomes. Full details and predeclared conditions: ONLINE_PROTOCOL.md.
