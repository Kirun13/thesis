# Frozen-model sensitivity to the excluded ambiguous cohort

Evaluate all 524,148 previously excluded records with unchanged legacy models and validation thresholds. These rows contain only 16 distinct ambiguous input vectors; they are not independent observations. Identical input groups are evaluated once and confusion counts weighted by their original label frequencies.

| Model | Seed | Accuracy | Attack F1 | Recall | FPR |
|---|---:|---:|---:|---:|---:|
| mlp-central | 42 | 0.3378 | 0.5051 | 1.0000 | 1.0000 |
| mlp-central | 43 | 0.4771 | 0.5438 | 0.9226 | 0.7502 |
| mlp-central | 44 | 0.4771 | 0.5438 | 0.9226 | 0.7502 |
| gru-central | 42 | 0.3378 | 0.5051 | 1.0000 | 1.0000 |
| gru-central | 43 | 0.3378 | 0.5051 | 1.0000 | 1.0000 |
| gru-central | 44 | 0.3378 | 0.5051 | 1.0000 | 1.0000 |
| gru-fedavg-iid | 42 | 0.3378 | 0.5051 | 1.0000 | 1.0000 |
| gru-fedavg-iid | 43 | 0.3378 | 0.5051 | 1.0000 | 1.0000 |
| gru-fedavg-iid | 44 | 0.3378 | 0.5051 | 1.0000 | 1.0000 |
| gru-fedavg-noniid | 42 | 0.3378 | 0.5051 | 1.0000 | 1.0000 |
| gru-fedavg-noniid | 43 | 0.3378 | 0.5051 | 1.0000 | 1.0000 |
| gru-fedavg-noniid | 44 | 0.3378 | 0.5051 | 1.0000 | 1.0000 |

Conditional sensitivity on all excluded ambiguous inputs, not a new unbiased whole-dataset test. Cohort prevalence differs from the old filtered test. No model or threshold is retuned.

The original filtered benchmark remains unchanged. This audit does not establish generalization to independent captures or real municipal networks.
