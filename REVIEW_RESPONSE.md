# Independent review of the response experiment

Reviewer: GPT-6 Astra, high reasoning. Requested explicitly by the user. Read-only review of PLAN_RESPONSE.md v1, PROTOCOL.md, preparation/training code and completed detection results. No implementation changes were made by the reviewer.

Verdict: proceed after the corrections below; no retraining or complete redesign is required. The experiment supports a virtualized feature-ready-to-filtering-command comparison with real kernel packet-drop verification. It does not demonstrate full live-attack detection latency, GRU superiority, or a latency benefit caused by federated training.

## Required changes accepted into v2

1. Define t0 after complete standardized-vector decoding/validation and before tensor creation. Call the primary endpoint successful firewall-command completion, an observed upper bound on installation, not a precise kernel commit. Counter-observation time is a separate upper bound including probe/polling resolution.
2. Use the validation threshold from result.json, not best.pt. Keep identical score and threshold policy; no ground-truth label goes to the policy. Fix RPC/enforcement/verification timeouts at 1/2/1 seconds. No timed retries; controller failure is explicit fail-open, without hidden local fallback. Match trial IDs and reject late replies.
3. Use persistent framed TCP with TCP_NODELAY, warmed outside measurement. Calibrate the same application RPC, not ping. Netem d on both outgoing control interfaces should add about 2d per exchange, but actual RTT must be measured. Find interfaces by peer routes.
4. Scope real kernel rules to an INPUT chain inside edge for the probe source and UDP destination port. Independent health probes use another source IP and the same sink port. Verify delivery before, DROP counter growth and absent probe delivery during block, and recovery after clearing the rule.
5. Predeclare all 3,600 trial IDs and pairing/order. Preserve append-only attempts, failures and partial trials on resume. Report completed/unexecuted counts and explicit success/failure denominators. Paired latency excludes incomparable pairs with counts/reasons shown.

## Design clarifications

- Keep 200 score-independent observations (100 normal/100 attack), three frozen non-IID model seeds and 0/10/50 ms nominal one-way control delay. Report the attack-type mix. This balanced small benchmark does not estimate natural traffic prevalence.
- row_test is a filtered/deduplicated processed index, not an original CSV row number. Also preserve test-array index, hash_test and prepared-file checksum.
- Randomize small blocks of 20 observations across seed/delay conditions and balance local-first/central-first pairing to limit warming and laptop-load confounds.
- Export is an implementation choice; if used, verify both numerical parity and threshold-decision parity. Keep eval mode, feature order, CPU threads, resource limits and environment fixed. Sequential trials do not evaluate saturation or queues.
- With about 100 block samples per condition, p95 is descriptive. Three model seeds do not establish universal hardware significance.

## Smoke gate

Numerical/decision parity; actual model-driven block and allow; counter, probe and health evidence; reset recovery; controller outage and stale reply; explicit enforcement failure; measured RTT increase with netem while data-path health stays separate; interruption/resume preserving attempts and completed pairs.

## Platform gate and references

NET_ADMIN alone does not guarantee kernel qdisc/firewall support inside Docker Desktop. Test actual iptables backend, rule insertion/removal, counters, tc netem, qdisc statistics and application RTT before full execution. If netem is unavailable, report a baseline-only network result rather than substituting artificial application sleeps.

- https://docs.docker.com/desktop/features/networking/
- https://github.com/iproute2/iproute2/blob/main/man/man8/tc-netem.8

All review items above are incorporated into PLAN_RESPONSE.md v2 before implementation.
