# Completed experiments

## Detection

Run: runs/overnight-2026-11-04T14-57-07-088Z. All 12 jobs completed (four recipes × three seeds). Mean test F1: MLP 98.81%, centralized GRU 98.63%, FedAvg IID GRU 98.45%, FedAvg non-IID GRU 98.43%. Checkpoints, predictions, convergence plots and exact data audit are preserved. GRU operates across static feature positions, not time windows. Filtered random-record split does not establish unseen-session/device generalization.

## Response

Run: runs/response/full-20261104T153359Z. All 3,600 predeclared trials / 1,800 pairs completed in one uninterrupted segment. Raw journal has 3,600 started and 3,600 terminal attempts, no superseded/incomplete trials, and no technical failures. 1,806 verified block outcomes and 1,794 verified allow outcomes. Every block has kernel DROP evidence, post-command probes absent at the sink, independent health delivery, and restored delivery after reset. Every local/central pair has identical scores and policy decisions.

Across the three frozen non-IID GRU models, median primary block time is about 3.6 ms locally. Controller-mediated medians are about 4.0 ms at nominal zero added delay, 24.5 ms at 10 ms one-way delay, and 104.5 ms at 50 ms one-way delay. Exact per-model medians/p95 and paired differences are in the completed run's RESULTS.md, summary.csv and paired-differences.csv. Actual RPC RTT calibration is preserved rather than inferred from nominal netem settings.

The 200 replayed observations contain 100 attacks and 100 benign records. All 100 attack observations are blocked by each deployed model in this selected small sample. Seed 42 also falsely blocks one benign observation, consistently across every mode/delay; seeds 43/44 falsely block none in this sample. Repeated network conditions are not independent new classification samples. Full detection-quality evidence remains experiment 1, and rare attacks are not covered by this small systems sample.

Measurement boundary: a complete standardized feature vector is decoded and validated at edge; timing then includes tensor creation, inference, policy, controller exchange when used, and return of the firewall command. Command return is an installation upper bound. Separate synthetic UDP probes verify enforcement; their payloads are not the model's classified inputs. Capture, feature extraction and prior preprocessing are excluded. See RESPONSE_PROTOCOL.md for all definitions and limits.

Independent review by GPT-6 Astra covered both the plan and implementation. Smoke passed actual firewall/netem checks, export/decision parity, healthy traffic, reset, controller outage/late/stale replies, enforcement errors and recovery-accounting tests. Eight automated checks passed. Final raw-record/source-hash checks passed and are saved as final-verification.json. Only this dedicated Compose project's containers/networks were stopped after verification; result files remain available.

This experiment retains the feature-ready boundary above. The separately trained traffic-linked extension below adds a real ingress-to-command endpoint; its scores and workloads must be reported separately.

## Traffic-linked extension (completed)

Final report: runs/online/final-v1/RESULTS.md. Protocol: ONLINE_PROTOCOL.md. Paper interpretation: PAPER_ALIGNMENT.md. Independent final review: REVIEW_ONLINE.md.

The extension captures actual MQTT traffic at an edge gateway, forms causal 250 ms source windows, runs a frozen classifier and applies source-scoped firewall DROP to that same traffic. Kernel timestamps, raw PCAP, offline feature replay, TCP byte-stream/message-ID reconciliation, subscriber delivery and historical rule counters are preserved. No payload identity, address or ground-truth tag is a feature. Broker attribution uses application IDs because forwarding includes SNAT.

Three commissioning episodes passed the capture/label gate. Whole-episode splits contain 36 training, 12 validation and 12 held-out test episodes; all repeated and ambiguous windows are retained. Twenty-one neural training jobs plus a rate baseline completed. Central MLP mean F1 is 0.9786; FedMLP IID 0.9785. Non-IID FedMLP depends strongly on partition: means 0.8072/0.0144/0.8224 for partition seeds 42/43/44. FedGRU non-IID mean F1 is 0.8804; it does not establish an advantage over centralized MLP. Primary deployment was fixed before test: fedmlp-noniid-p42-s42, F1 0.7966, recall 0.6861. GRU still traverses feature positions, not temporal sequences.

All 60 assigned system condition episodes completed: nine independent workloads repeated across six regular conditions, plus three outage workloads in two modes. Capture/label reconstruction is valid in 58/60; both invalid episodes remain in the ledger and independent subscriber service statistics, but their response latencies are excluded from primary summaries. Exact matched offered schedules, source snapshots and the actual running image were verified. Eleven automated tests passed. The final audit is runs/online/final-v1/final-verification.json.

Among pairs where both valid responses exist, median controller-minus-local ingress-to-command time is 0.26 ms at zero added delay (7 pairs), and 99.27 ms with 50 ms one-way control delay (6 pairs). Low-rate responses occur in only 1/3 assigned episodes per mode/delay. During real controller-path loss, local responds in 3/3 episodes and central in 0/3; central records 16 timeouts and inference backlog. Missing responses remain in the denominator.

No-mitigation already delivers all scheduled legitimate messages: availability improvement is not established. Mitigation reduces delivered attacking messages at medium/high offered loads; the two other publishers retain 100% legitimate delivery, while the blocked publisher can lose legitimate messages and recover late. The worst post-attack-plus-TTL scheduled delivery ratio is 0.5086. No false triggering-window block commands are observed within the 58 valid reconstructed episodes; invalid episodes cannot establish that claim. All-condition historical firewall counters record 2,579 dropped packets, not 2,579 independent attack messages.

The legacy-data sensitivity audit is runs/extension-audit/EXCLUDED_SENSITIVITY.md: 524,148 excluded rows contain only 16 ambiguous input vectors. Frozen models/thresholds frequently classify this whole cohort as attack. Thus the earlier ~98% F1 applies to the filtered benchmark and cannot be presented as general accuracy on the original corpus or live MQTT workload.

Remaining work is manuscript alignment with these actual methods and mixed findings. This is a bounded synthetic publish-flood experiment on one VM; it does not demonstrate broad attack coverage, temporal GRU superiority, production municipal deployment or formal privacy guarantees.
