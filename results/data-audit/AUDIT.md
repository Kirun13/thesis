# Audit of the original selected Edge-IIoTset CSV

Original rows: 2,219,201. Rows in ambiguous selected-input groups: 524,148 (23.62%).

A selected feature vector shared by benign and attack labels is not proof of a mislabeled event. Deleting these groups removes ambiguity specific to the chosen representation. Repeated feature vectors are not necessarily duplicate underlying packet events.

The empirical minimum number of label disagreements for deterministic classification of these raw inputs is 67,975. The corresponding in-sample accuracy ceiling is 96.94%; this is not an out-of-sample estimate.

| Type | Original rows | Ambiguous rows | Repeated unambiguous input rows | Retained unique unambiguous |
|---|---:|---:|---:|---:|
| Backdoor | 24862 | 1655 | 1417 | 21790 |
| DDoS_HTTP | 49911 | 15508 | 20525 | 13878 |
| DDoS_ICMP | 116436 | 8 | 70648 | 45780 |
| DDoS_TCP | 50062 | 1 | 20917 | 29144 |
| DDoS_UDP | 121568 | 110035 | 987 | 10546 |
| Fingerprinting | 1001 | 700 | 300 | 1 |
| MITM | 1214 | 821 | 36 | 357 |
| Normal | 1615643 | 347071 | 1000012 | 268560 |
| Password | 50153 | 13369 | 36734 | 50 |
| Port_Scanning | 22564 | 2590 | 9990 | 9984 |
| Ransomware | 10925 | 1820 | 819 | 8286 |
| SQL_injection | 51203 | 13206 | 36371 | 1626 |
| Uploading | 37634 | 11494 | 25872 | 268 |
| Vulnerability_scanner | 50110 | 1541 | 29127 | 19442 |
| XSS | 15915 | 4329 | 11394 | 192 |

No authoritative capture identifier is present in the aggregated CSV. Session/capture generalization must use verified provenance or independent captured laboratory episodes.

The previous benchmark is preserved. New primary evaluation must retain ambiguous observations and split independent episodes before fitting transforms or selecting models.
