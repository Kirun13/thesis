# Completed experiments

## Detection

Run: runs/overnight-2026-11-04T14-57-07-088Z. All 12 jobs completed (four recipes × three seeds). Mean test F1: MLP 98.81%, centralized GRU 98.63%, FedAvg IID GRU 98.45%, FedAvg non-IID GRU 98.43%. Checkpoints, predictions, convergence plots and exact data audit are preserved. GRU operates across static feature positions, not time windows. Filtered random-record split does not establish unseen-session/device generalization.

## Response

Run: runs/response/full-20261104T153359Z. All 3,600 predeclared trials / 1,800 pairs completed in one uninterrupted segment. Raw journal has 3,600 started and 3,600 terminal attempts, no superseded/incomplete trials, and no technical failures. 1,806 verified block outcomes and 1,794 verified allow outcomes. Every block has kernel DROP evidence, post-command probes absent at the sink, independent health delivery, and restored delivery after reset. Every local/central pair has identical scores and policy decisions.

Across the three frozen non-IID GRU models, median primary block time is about 3.6 ms locally. Controller-mediated medians are about 4.0 ms at nominal zero added delay, 24.5 ms at 10 ms one-way delay, and 104.5 ms at 50 ms one-way delay. Exact per-model medians/p95 and paired differences are in the completed run's RESULTS.md, summary.csv and paired-differences.csv. Actual RPC RTT calibration is preserved rather than inferred from nominal netem settings.

The 200 replayed observations contain 100 attacks and 100 benign records. All 100 attack observations are blocked by each deployed model in this selected small sample. Seed 42 also falsely blocks one benign observation, consistently across every mode/delay; seeds 43/44 falsely block none in this sample. Repeated network conditions are not independent new classification samples. Full detection-quality evidence remains experiment 1, and rare attacks are not covered by this small systems sample.

Measurement boundary: a complete standardized feature vector is decoded and validated at edge; timing then includes tensor creation, inference, policy, controller exchange when used, and return of the firewall command. Command return is an installation upper bound. Separate synthetic UDP probes verify enforcement; their payloads are not the model's classified inputs. Capture, feature extraction and prior preprocessing are excluded. See RESPONSE_PROTOCOL.md for all definitions and limits.

Independent review by GPT-6 Astra covered both the plan and implementation. Smoke passed actual firewall/netem checks, export/decision parity, healthy traffic, reset, controller outage/late/stale replies, enforcement errors and recovery-accounting tests. Eight automated checks passed. Final raw-record/source-hash checks passed and are saved as final-verification.json. Only this dedicated Compose project's containers/networks were stopped after verification; result files remain available.

Remaining paper work: align Methods/Results and the title/claims with the implemented feature-ready measurement boundary. A raw-traffic-arrival endpoint requires an additional validated online capture/feature-extraction pipeline. No additional training is required for the completed controlled placement comparison.
