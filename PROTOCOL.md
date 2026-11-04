# Experiment 1: offline detection under centralized and federated training

## Scope

Compare the same GRU-Attention detector trained centrally and with FedAvg under IID and non-IID client partitions. Add a centralized MLP reference. This experiment evaluates detection quality and laptop model-only inference cost. It does not evaluate packet capture, local enforcement, actual edge hardware, privacy guarantees, or detection-to-response latency. Those require a separate network experiment.

## Data and split

Author release: https://www.kaggle.com/datasets/mohamedamineferrag/edgeiiotset-cyber-security-dataset-of-iot-iiot

Dataset paper: https://doi.org/10.1109/ACCESS.2022.3165809

Use DNN-EdgeIIoT-dataset.csv with binary Attack_label. Attack_type is used ONLY to stratify records, create non-IID partitions, and report per-attack recall; never as an input. Preserve release file size and SHA-256 in provenance.

Use the fixed 34-column numeric schema in scripts/prepare_data.py. Exclude labels, timestamps, addresses, ports, checksums, stream and transaction IDs, raw TCP acknowledgement numbers, and free text/payload. Retain relative TCP sequence/acknowledgement and ICMP sequence fields as protocol-state inputs; these can retain capture/session artifacts and need a later session-held-out evaluation. Non-numeric numeric-field values and infinities become missing. Deduplicate identical float32 input feature vectors across the complete dataset before sampling and splitting. Remove all records in groups that have conflicting binary labels. Exclude any attack type with fewer than 20 unique eligible records before the three-way split, and report exactly which types were excluded. This changes the original traffic distribution; report counts and resulting class proportions, and do not call the result representative live traffic. Deduplication uses 64-bit feature hashes; hash collisions are theoretically possible.

Use up to 150,000 unique eligible records sampled proportionally by attack type, split 70/15/15 into train/validation/test with seed 42 and attack-type stratification. Split unit is a feature record, not a device, session, or capture day. Correlated records from the same traffic session may remain across splits: no unseen-device/session or production generalization claim is supported. Validation and test remain fixed across training seeds and methods.

Fit missing-value medians and standardization ONLY on training records. Do not fit vocabularies, balance, oversample, or normalize with validation/test data. Imputation and float32 rounding can collapse different raw inputs: without using labels, drop validation inputs matching training, then test inputs matching training or retained validation, and deduplicate each evaluation subset. Report removal counts and actual final class distributions; the final split sizes can differ slightly from 70/15/15. Assert zero exact final-input overlap across splits. All methods share the same transforms. Transform fitting is performed by the offline experimental harness over pooled training records; this is NOT a fully decentralized preprocessing protocol and must not be presented as one.

## Models and federation

GRU input is a single record represented as a fixed sequence of numeric features. Concatenate each scalar with a learned 7-dimensional feature-identity embedding, apply a single GRU with 32 hidden units and additive attention over feature positions, then a small classifier. These positions are NOT time steps. Do not claim temporal attack modelling or equate this model to a temporal GRU in another paper. MLP: 64 and 32 hidden units, ReLU, dropout 0.1.

Five clients simulated sequentially on one laptop/GPU, not five physical edge devices. IID: shuffled equal-size training subsets. Non-IID: attack-type Dirichlet partition with alpha 0.3, seed 42; retry until each client has at least 32 records. Save actual per-client class distributions. Every training record belongs to exactly one client. All five participate every round. FedAvg weights local parameter states by client sample counts; one full local epoch per round, local AdamW reset each round. No Flower/network transport or communication latency is simulated.

Centralized AdamW keeps optimizer state across epochs. This differs from resetting local optimizers in FL and is part of the defined training recipes; a performance difference cannot be attributed solely to data placement. All GRU recipes share initialization for a given seed, learning rate 0.001, weight decay 0.0001, batch size 256, gradient norm limit 1, and a global training-only binary positive-class loss weight. The pooled positive-class weight is experimental shared metadata, not a measured privacy mechanism.

## Training and evaluation

Twenty centralized epochs or twenty FedAvg rounds; each round visits every client's training records once. Three training seeds: 42, 43, 44. No hyperparameter search. Select the checkpoint with maximum validation average precision (AP); select its decision threshold by maximum validation binary F1, with highest-threshold tie breaking. Evaluate test only after both choices. No stopping or retraining based on test scores.

Report attack-class precision, recall, F1, macro-F1, accuracy, FPR, ROC-AUC, AP, confusion matrix, per-attack recall, best epoch/round, parameter count, model bytes, wall training duration. Mean and sample SD describe variation across training seeds on one fixed split; they are NOT confidence intervals across independent datasets. Log validation AP and fixed-0.5 F1 per epoch/round. Compare performance alongside training cost and actual client distributions; do not assume non-IID must be worse.

Batch-1 model-only inference: 30 warmups, 200 timed samples, device synchronization around each forward pass. Report median/p95 and device. Inputs are already on device. This excludes feature extraction, transfer, networking, policy and enforcement; never label it full detection or response latency. Do not compare directly to published timings with different hardware and measurement boundaries.

## Execution and recovery

Smoke profile: two steps, at most 512 records per client, one seed, validation only. Its metrics are debugging evidence, not paper results. Full profile uses the audited data and fixed settings above. Save config, source snapshot, package versions, data checksum, per-step logs, best and last checkpoint, test predictions, and results. Run at most ten hours per invocation. Resume from a completed checkpoint after interruption; a partial round is repeated. No test-based tuning.

The next experiment must compare local and central enforcement using the SAME frozen model and controlled network delays, verify actual packet drops, and distinguish observation/feature-window delay, preprocessing, inference, policy, and rule enforcement. Container traffic can validate enforcement; it should not silently replace the benchmark training data or be described as real city traffic.
