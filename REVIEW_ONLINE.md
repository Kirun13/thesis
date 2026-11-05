# Online extension review

Reviewer: GPT-6 Astra, read-only subagent /root/review_response_plan, following the user's requested independent plan and implementation review. This is assistance with experimental design and reporting, not journal peer review.

The initial review required randomized attack onset relative to window boundaries, independent source-role and rate combinations, preplanned message schedules, causal feature replay from raw PCAP, TCP byte-stream reconciliation of ground truth, stable controller RPC and preservation of historical firewall counters. These changes were incorporated before the frozen study.

The final review found no need to restart training or rerun the condition matrix. It required the following reporting corrections, now implemented in scripts/report_online.py:

- Count a correct response only when its actual triggering source window contains reconciled attack-message bytes; distinguish benign-window/pre-onset block commands.
- Split onset-to-first-attack-window readiness, subsequent-window waiting, queue, inference and combined authorization/enforcement. The journal cannot separate RPC and firewall installation precisely.
- Preserve all 60 assigned episodes and show response coverage beside conditional latency. Pair comparisons by workload and condition; repeated conditions are not independent new workloads.
- Flag invalid capture/label reconstruction and exclude its candidate response latency from the primary summary while preserving independent subscriber service evidence.

Final review findings retained in the report: 58/60 valid reconstructions; two capture failures; low-rate coverage only 1/3; no demonstrated availability improvement because the unmitigated baseline already delivers every legitimate message; possible loss and delayed recovery for legitimate traffic from the blocked source. Conditional central-minus-local medians use only 7 and 6 responding valid pairs at control delays 0 and 50 ms. False-block absence is assessed only in valid reconstructed episodes.

The reviewer separately checked scripts/audit_excluded.py against the old preprocessing/training code. Feature order, numeric conversion, float32 representation, imputation, saved scaling and weighted confusion counts match. The excluded 524,148 records represent only 16 distinct ambiguous input vectors and cannot be treated as independent new observations or a fresh whole-corpus generalization test.

No material remaining calculation error was identified in the reviewed report. Supported scope: a controlled synthetic MQTT systems evaluation with mixed and negative findings, rather than universal FL/GRU superiority or real municipal deployment.
