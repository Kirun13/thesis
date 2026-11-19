# Detection experiment results

Fixed deduplicated random-record split; values are mean ± sample SD over training seeds.

| Method | Completed seeds | F1 | Macro-F1 | Recall | FPR | AP |
|---|---:|---:|---:|---:|---:|---:|
| gru-central | 3 | 0.9863 ± 0.0006 | 0.9892 ± 0.0004 | 0.9921 ± 0.0008 | 0.0112 ± 0.0006 | 0.9948 ± 0.0019 |
| gru-fedavg-iid | 3 | 0.9845 ± 0.0005 | 0.9877 ± 0.0004 | 0.9924 ± 0.0008 | 0.0136 ± 0.0005 | 0.9953 ± 0.0011 |
| gru-fedavg-noniid | 3 | 0.9843 ± 0.0007 | 0.9876 ± 0.0005 | 0.9895 ± 0.0027 | 0.0121 ± 0.0024 | 0.9967 ± 0.0020 |
| mlp-central | 3 | 0.9881 ± 0.0002 | 0.9906 ± 0.0001 | 0.9940 ± 0.0009 | 0.0102 ± 0.0007 | 0.9986 ± 0.0001 |

These are offline detection results, not full detection-to-response measurements.
The GRU attends over ordered features of one record; no temporal traffic window is modelled.
See PROTOCOL.md and data-audit.json for exclusions and evaluation limits.
