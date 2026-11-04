# Experiment 2: feature-ready to firewall-command completion

## Question and scope

For a fixed edge detector and policy, what additional response delay is introduced by a controller round trip? Evaluate local versus controller-mediated decision making on a single virtualized Docker Desktop laptop. This is a systems experiment using replayed standardized feature observations from Edge-IIoTset and separate synthetic UDP probes for enforcement verification. The model does not classify the probe payloads. Raw packet capture, online feature extraction, feature preprocessing, physical IoT hardware, real city traffic and saturated-load behaviour are outside this experiment.

The independent planning review and its accepted changes are recorded in REVIEW_RESPONSE.md and PLAN_RESPONSE.md. Model training, split construction and detection metrics remain described by PROTOCOL.md and the unchanged experiment-1 outputs.

## Frozen artifacts and selection

Use all three GRU-Attention checkpoints from the completed non-IID FedAvg recipe, seeds 42/43/44. Keep each checkpoint's validation-chosen binary F1 threshold from its result.json. Do not select a model using test results or retune thresholds. Export CPU TorchScript models and verify probability closeness (<1e-5) and identical threshold decisions on the 200 selected observations, including inside the Linux container. GRU positions are feature positions of one static record, not time steps.

Select 100 benign and 100 attack test records once with sampling seed 20261104, independently of model scores. Preserve test-array index, processed row ID, feature hash, feature order and prepared-data SHA-256. The processed row ID is not an original raw-CSV line number. Report the actual attack-type mix; this small balanced systems sample does not establish performance at natural prevalence or cover every rare attack.

The predetermined ledger has 3 model seeds × 3 nominal one-way control delays (0, 10, 50 ms) × 200 records × 2 modes = 3,600 trials and 1,800 matched pairs. Scheduler seed 20261105 randomizes blocks of 20 observations across model/delay conditions, record order, and balanced local-first/central-first pair order. Save the complete ledger before network trials.

## Topology and fixed implementation

Dedicated Compose project thesis-response has two externally isolated bridge networks: data and control. Edge joins both; controller joins control; replay/probe client and independent health client join data. No host ports are published. There is no host networking, privileged container or Docker-socket mount. Only edge/controller get NET_ADMIN for their own network namespaces. Model artifacts mount read-only. Runtime image and source checksums are saved with each run.

Docker VM reports four virtual CPUs. Edge/controller/replay/health processes are pinned to virtual CPUs 0/1/2/3 respectively; memory limits are 1536/256/256/128 MB. CPU PyTorch 2.9.1, one intra/inter-op thread at edge, batch 1, eval mode, 30 warm-up forwards on each configuration. The same frozen model, feature vector, score, threshold, policy and edge firewall helper are used in both modes.

Policy is block iff score >= threshold. Local mode applies it at edge. Central mode transmits score, threshold/model ID and unique request ID to the controller using an established newline-framed TCP connection with TCP_NODELAY; the controller returns the action and edge applies it. Ground-truth labels never enter the edge/controller decision request. Handshake, model loading and warm-up occur outside timing.

Apply tc netem to the two outgoing control interfaces, selected by peer routing lookup; leave data interfaces unchanged. Before each block, configure both sides, warm the same policy RPC twice, and time six policy exchanges using edge monotonic time. Report actual measured RTT, interface names and tc statistics. Nominal d on each egress is expected to add roughly 2d per request/reply, not an assumed measured value.

## Rule and verification

A dedicated THESIS_IDS chain is called only from edge INPUT for the UDP sink destination port. A block appends a DROP for the replay client's source address. The independent health client uses a different source IP and the same UDP sink/port. This evaluates filtering packets delivered to an edge-local socket, not routing through a gateway FORWARD path.

Before each trial flush only THESIS_IDS and confirm the probe client's UDP echo. During the trial send probes every nominal 5 ms; independent health probes run every 10 ms. After command completion, switch to a unique post-command probe token, observe a fixed 25 ms window, then read the kernel DROP counter and edge delivery counts. A block succeeds only if the DROP counter grew, post-command probes were sent but none reached the socket, health probes arrived, and delivery is restored after the dedicated chain is cleared. Allow verification requires delivery without DROP. The unique post-command token prevents pre-installation packets from being misread as packets that bypassed the installed rule.

## Time boundaries

- t0: the complete standardized feature vector has been decoded and validated at edge, immediately before tensor creation.
- Inference: tensor creation plus frozen model forward and sigmoid, measured at edge.
- Decision: inference, policy and (in central mode) the established control RPC.
- Primary block endpoint: return of the successful iptables subprocess. The difference from t0 is **feature-ready-to-firewall-command-completion**. This includes process launch/userspace overhead and is an observed upper bound on actual installation, not an instrumented kernel commit timestamp.
- Verification endpoint: return of the later counter read. Its difference from t0 is a separate observation upper bound containing probe interval, 25 ms verification window, replay-side scheduling, control over the undelayed data path and counter-read overhead. It is not the exact time of the first dropped packet.

All reported duration differences use only the edge monotonic clock. Replay delivery to edge, JSON decoding/validation, prior data preparation, model loading and warm-up are excluded from primary timing and must not be silently included in a claimed raw-traffic end-to-end number.

## Failures, recovery and reporting

RPC timeout is 1 s, enforcement subprocess timeout 2 s, verification command/window limit 1 s. No retry inside timing. Controller failure is fail-open, without local fallback. A timed-out connection is discarded, replies must match the request ID, and a stale response cannot install a later rule. Failure statuses are preserved rather than assigned zero mitigation latency.

Smoke uses validation-derived clear allow/block cases, separately from the full matrix, and checks CPU/export parity, actual kernel filtering, health isolation, reset, controller outage, late/mismatched replies and enforcement failure. Recovery accounting is exercised using an append-only partial-ledger fixture and unit tests; this is not an assertion that a real process crash was injected into the final full run.

Attempts are append-only with started/terminal records, attempt IDs and segment IDs. Completed pairs, including completed failed pairs, are not retried. Partial pairs can be repeated in a new segment while preserving earlier attempts. Paired comparisons must use both outcomes from one segment. Show latest unique-trial outcomes alongside all attempt counts/errors and incomplete/unexecuted ledger slots; never silently replace an earlier failed attempt.

For each seed/delay/mode report assigned and terminal counts; verified blocks / block decisions; mitigated attacks / all assigned attack observations; false block decisions and actual false blocks / all assigned benign observations; failure statuses; median/p95 successful-block time; separate allow-decision time; inference, controller, command and verification components. Paired central-minus-local latency uses only pairs with two verified blocks; show excluded pair counts and causes. Quantiles use NumPy linear interpolation. Three frozen models on one VM are not independent hardware replications, and p95 over about 100 blocks is descriptive.

Save raw attempts, segments, calibration samples, checksums, frozen inputs/models, image/environment/package metadata, source snapshot, tables, plots and audit. Preserve experiment 1. After final verification, tear down only this dedicated Compose project.
