# Response experiment — implementation plan v2.1, after GPT-6 Astra review

Independent review: REVIEW_RESPONSE.md. Original proposal: PLAN_RESPONSE.v1.md. Verdict: proceed after the methodological and operational corrections incorporated below. Review requested explicitly by the user; reviewer model GPT-6 Astra, high reasoning.

Execution completed: 3,600 trials / 1,800 pairs, without technical failures. Final measurement definitions are in RESPONSE_PROTOCOL.md. Version 2.1 removes remaining legacy endpoint wording after the implementation follow-up review; no experimental settings were changed. The executed v2 source snapshot remains unchanged in the completed run directory.

## Objective and existing evidence

Deadline: next day. Experiment 1 is completed: four detection recipes × three training seeds, with checkpoints, validation-chosen thresholds, test predictions and provenance. GRU attends over feature positions of one static record, not a traffic time window. MLP is slightly better than GRU in this benchmark. Do not retrain, select models using test results, or claim GRU superiority.

Implement a bounded second experiment to compare local versus controller-mediated policy/enforcement with the SAME frozen federated GRU, inputs, thresholds and edge enforcement mechanism. Use all three non-IID FedAvg checkpoints (seeds 42/43/44) rather than choosing the best test result. Do not change experiment 1 artifacts.

## Measurement boundary

Existing data contains prepared record features, not a validated online feature extractor. Therefore the primary endpoint starts when a complete replayed feature observation is available at the edge service. Report **feature-ready-to-firewall-command-completion latency**, plus a separate confirmation that synthetic data-plane probe packets actually hit a kernel DROP rule. This is not raw-packet-arrival-to-response latency, a temporal GRU, live attack detection, or physical-edge performance.

The feature replay and synthetic UDP probes are explicitly separate: observations originate from Edge-IIoTset; probe traffic only verifies enforcement. No claim that the trained model classified the probe bytes themselves. Report these limitations prominently in protocol and results. Exact t0: complete standardized vector decoded and validated, before tensor creation. Primary endpoint: return of successful iptables command, called **feature-ready-to-firewall-command-completion**, an observed upper bound on actual rule installation rather than an exact kernel commit timestamp. DROP counter observation is a separate verification upper bound.

## Container topology

Use a dedicated Compose project with isolated data and control bridge networks. Services: edge, controller, replay/probe client and an independent benign health-probe client. No published host ports, no host network, no privileged containers, no Docker socket. Add NET_ADMIN only where required for the experiment network namespaces.

The edge runs the frozen CPU model and owns a dedicated iptables chain scoped to UDP probe port/source addresses. Local mode: edge inference → local threshold policy → apply rule. Central mode: edge inference → send score to controller → controller returns action → same edge enforcement helper applies rule. Thus inference placement, policy and rule execution are constant while controller communication is introduced.

Apply tc netem delay only to the separate control interfaces at edge and controller: nominal 0, 10 and 50 ms one way. Calibrate actual request/reply RTT before each condition. Keep the probe network unchanged. All primary timestamps use the edge's monotonic clock; never subtract clocks across containers.

## Inputs, trials and endpoints

Export all three frozen GRU checkpoints to CPU TorchScript, retaining exact feature order and validation-chosen thresholds. Assert exported predictions match original checkpoints numerically. Reuse standardized benchmark inputs; exclude feature extraction and preprocessing from the timed boundary rather than silently claiming to measure them.

Select 200 test records once, independently of model scores: 100 benign and 100 attack, deterministic sampling. Save test-array index, processed row ID (not original CSV row), feature hash, and prepared-data SHA-256. Replay the identical observations under each seed/delay/mode. Precompute a complete 3,600-row ledger: divide observations into blocks of 20, randomize seed/delay/block order and observation order, and use balanced AB/BA ordering of local/central within matched pairs. Record scheduler seed. Total 3 × 3 × 2 × 200 = 3,600 trials, run sequentially without load saturation. This is a balanced latency/decision benchmark, not natural traffic prevalence.

Each trial starts with a clean dedicated rule chain, confirms probe delivery, receives a feature observation, runs inference, decides allow/block, applies any DROP rule, and verifies actual DROP counters while independent benign probes continue. Clear only experiment-owned rules after each trial. Keep rule-install failures, controller timeouts, classification false negatives and false positive block decisions in denominators; do not give misses zero latency.

Record inference time, controller round trip if applicable, enforcement-command execution time, feature-ready-to-firewall-command-completion time, verification upper-bound time, rule counters, health traffic, classification decision/label and all failure statuses. Firewall-command completion and later observation of a dropped probe are different endpoints. Verification uses a fixed 25 ms post-command window followed by a counter read, with 5 ms probes. For allow decisions, report decision latency separately from block latency.

Aggregate median/p95, sample counts and failure rate for each model/mode/delay; report paired local-central differences and variation across the three frozen model seeds. Do not pool failed or no-action trials as successful mitigations. Preserve raw JSONL, config, source snapshot, model/input/image hashes, host/container environment, calibrated RTT, tables and plot.

## Mandatory controls adopted from review

- Persistent framed TCP control RPC with TCP_NODELAY, warmed outside trials. Calibrate this exact RPC, not ICMP ping. Resolve delayed interfaces by route to the peer IP. Record actual qdisc and achieved RTT.
- Identical policy: block iff score >= the validation threshold saved in each job's result.json. Transmit the exact same float and threshold/model ID; do not transmit the ground-truth label. No model or threshold selection using test results.
- Controller RPC timeout 1 s, enforcement subprocess timeout 2 s, verification timeout 1 s. No measured retries. Fail-open on controller failure without local fallback; log the failure. Every response must match trial_id. Discard timed-out connections, reject late/mismatched replies, and reset the experiment chain before another trial.
- Dedicated INPUT chain inside edge, matching the replay client's source address and the UDP sink port. Independent health source accesses the same port. Verify delivery before, counter increment plus no further probe delivery after, and delivery restoration after reset. Drop only this experiment's chain.
- Append-only attempts, a predeclared ledger, segment IDs and explicit incomplete/unexecuted counts. Resume only fully completed pairs; preserve partial attempts and failures as such, with no silent replacement. Report excluded paired comparisons and their causes.
- Separate denominators: verified enforcement / block decisions; mitigated attacks / attack observations; false blocks / benign observations; all failure statuses / assigned trials. Allow and successful-block latencies are separate. Report descriptive median/p95 by seed/delay/mode; model seeds are not independent hardware replications.
- Docker preflight must demonstrate actual scoped iptables rule/counters and netem on this VM. If netem is unavailable, retain only the measured baseline-delay comparison and explicitly mark controlled-delay conditions unavailable. Never substitute sleep for netem.
- Smoke additionally checks stale responses, controller outage, enforcement failure, reset, health path isolation, export decision parity, and interrupted/resumed ledger accounting. Functional smoke records are separate from the full matrix.

## Implementation sequence and acceptance

1. Independent model review of this plan; save findings and revise before implementation.
2. Export and parity checks; implement the network services and a small deterministic smoke profile.
3. Smoke test: at least one model-driven block and allow; real DROP counter increments, independent benign probes pass, rule reset restores delivery, controller outage is visible, and control delay affects calibrated RTT.
4. Run full fixed matrix only after smoke checks pass. Resume completed pairs without rewriting original records.
5. Generate and inspect report/plots; document limitations and how this extends experiment 1. Tear down only this Compose project and its networks after results are saved.

If netem/kernel firewall support is unavailable, do not replace it silently with sleep or an in-memory blocked flag. Diagnose, record the limitation and use a clearly labelled fallback only if it still measures real network enforcement.
