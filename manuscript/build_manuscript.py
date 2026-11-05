"""Create the evidence-aligned manuscript using bundled python-docx."""
import collections
import csv
import hashlib
import json
import statistics
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION, WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'manuscript'
DOCX = OUT / 'Federated_Edge_IDS_Manuscript_v2.docx'
SOURCE = ROOT / 'runs/online/final-v1/summary.json'
study = json.loads(SOURCE.read_text())
detectors = study['detector_results']
episodes = study['system_episodes']
cells = study['system_cells']
literature = json.loads((OUT / 'sources/literature_review.json').read_text(encoding='utf-8'))
legacy = list(csv.DictReader((ROOT / 'runs/overnight-2026-11-04T14-57-07-088Z/summary.csv').open()))

doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21), Cm(29.7)
sec.top_margin, sec.bottom_margin = Cm(1.9), Cm(1.9)
sec.left_margin, sec.right_margin = Cm(2.0), Cm(2.0)
sec.footer_distance = Cm(0.8)

for name in ['Normal', 'Title', 'Subtitle', 'Heading 1', 'Heading 2', 'Heading 3', 'Caption']:
    style = doc.styles[name]
    style.font.name = 'Times New Roman'
    style.font.color.rgb = RGBColor(0, 0, 0)
    style._element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'), 'Times New Roman')
    for border in list(style._element.iter(qn('w:pBdr'))):
        border.getparent().remove(border)
for style in doc.styles:
    for fonts in style._element.iter(qn('w:rFonts')):
        for attr in list(fonts.attrib):
            if attr.lower().endswith('theme'):
                del fonts.attrib[attr]
normal = doc.styles['Normal']
normal.font.size = Pt(11)
normal.paragraph_format.line_spacing = 1.08
normal.paragraph_format.space_after = Pt(6)
normal.paragraph_format.widow_control = True
for name, size in [('Title', 17), ('Heading 1', 13), ('Heading 2', 11.5), ('Heading 3', 11)]:
    style = doc.styles[name]
    style.font.size = Pt(size)
    style.font.bold = True
    style.paragraph_format.space_before = Pt(12 if name != 'Title' else 0)
    style.paragraph_format.space_after = Pt(6)
    style.paragraph_format.keep_with_next = True
doc.styles['Caption'].font.size = Pt(9.5)
doc.styles['Caption'].font.italic = True
doc.styles['Caption'].paragraph_format.space_before = Pt(6)
doc.styles['Caption'].paragraph_format.space_after = Pt(5)
doc.styles['Caption'].paragraph_format.keep_with_next = True

footer = sec.footer.paragraphs[0]
footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
field = OxmlElement('w:fldSimple')
field.set(qn('w:instr'), 'PAGE')
field_run = OxmlElement('w:r')
field_text = OxmlElement('w:t')
field_text.text = '1'
field_run.append(field_text)
field.append(field_run)
footer._p.append(field)
footer.style.font.size = Pt(9)
props = doc.core_properties
props.title = 'Federated Edge-Based Intrusion Detection and Local Mitigation for Smart City IoT Systems'
props.subject = 'Detection to response latency evaluation'
props.author = ''
props.last_modified_by = ''
props.keywords = 'federated learning; edge computing; MQTT; intrusion detection; mitigation latency'


def p(text, style=None):
    return doc.add_paragraph(text, style)


def h(text, level=1):
    doc.add_heading(text, level)


def table(caption, headers, rows, widths):
    rows = list(rows)
    p(caption, 'Caption')
    t = doc.add_table(rows=1, cols=len(headers))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for col, width in zip(t.columns, widths):
        col.width = Cm(width)
    for row_index, values in enumerate([headers] + rows):
        row = t.rows[0] if row_index == 0 else t.add_row()
        trpr = row._tr.get_or_add_trPr()
        no_split = OxmlElement('w:cantSplit')
        trpr.append(no_split)
        if row_index == 0:
            repeat = OxmlElement('w:tblHeader')
            trpr.append(repeat)
        for index, (cell, value, width) in enumerate(zip(row.cells, values, widths)):
            cell.width = Cm(width)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            cp = cell._tc.get_or_add_tcPr()
            sh = OxmlElement('w:shd')
            sh.set(qn('w:fill'), 'E7EDF3' if row_index == 0 else 'FFFFFF')
            cp.append(sh)
            margins = OxmlElement('w:tcMar')
            for edge in ['top', 'left', 'bottom', 'right']:
                element = OxmlElement('w:' + edge)
                element.set(qn('w:w'), '65' if edge in ['left', 'right'] else '55')
                element.set(qn('w:type'), 'dxa')
                margins.append(element)
            cp.append(margins)
            para = cell.paragraphs[0]
            para.alignment = WD_ALIGN_PARAGRAPH.LEFT if index == 0 or len(str(value)) > 40 else WD_ALIGN_PARAGRAPH.CENTER
            para.paragraph_format.space_after = Pt(0)
            para.paragraph_format.line_spacing = 1.02
            para.paragraph_format.keep_with_next = row_index < len(rows)
            run = para.add_run(str(value))
            run.font.name = 'Times New Roman'
            run.font.size = Pt(9.5)
            run.font.bold = row_index == 0
    borders = OxmlElement('w:tblBorders')
    for edge in ['top', 'left', 'bottom', 'right', 'insideH', 'insideV']:
        line = OxmlElement('w:' + edge)
        for attr, val in [('val', 'single'), ('sz', '4'), ('color', 'D9D9D9')]:
            line.set(qn('w:' + attr), val)
        borders.append(line)
    t._tbl.tblPr.append(borders)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return t


def mean(entries, key):
    return statistics.mean(e['test_metrics'][key] for e in entries)


title = ('Federated Edge-Based Intrusion Detection and Local Mitigation for Smart City IoT Systems: '
         'A Detection-to-Response Latency Evaluation')
p(title, 'Title')
h('Abstract')
p('We evaluate the path from intrusion detection to local traffic filtering in a controlled IoT gateway setting. '
  'The evaluation separates an offline Edge-IIoTset benchmark, a paired feature-ready response experiment, '
  'and a traffic-linked MQTT publish-flood experiment. The MQTT study uses whole-episode training, validation '
  'and test splits, 21 neural training runs, and a packet-rate baseline. Sixty system episodes compare local '
  'authorization, controller authorization and observation without mitigation. Fifty-eight episodes have valid '
  'capture and label reconstruction; both capture failures are retained. Among matched workloads with two valid '
  'responses, controller authorization adds a median 99.27 ms at 50 ms one-way control delay, based on six pairs. '
  'Local mitigation responds in all three controller-outage workloads, whereas controller-mediated mitigation '
  'responds in none. These benefits are conditional on detection: low-rate response coverage is only one of '
  'three assigned episodes per condition, and non-IID training is strongly sensitive to client partition. '
  'Mitigation reduces delivered attacking messages while preserving delivery from the other publishers, '
  'but can suppress legitimate traffic from the blocked publisher. Since all legitimate messages are delivered '
  'without mitigation, an improvement in service availability is not demonstrated. The results quantify '
  'the response placement trade-off and its detection, capture and service limitations on one virtualized host.')
p('Keywords: federated learning; edge computing; intrusion detection; MQTT; local mitigation; response latency.')

h('1 Introduction')
p('Utility-oriented IoT systems motivate gateways that can detect harmful traffic and apply a response near '
  'its source. A short model inference time alone does not establish a short response time: traffic must '
  'first arrive, sufficient observations must accumulate, a decision must be made, and the filtering rule '
  'must be installed. If authorization requires a controller exchange, that exchange adds another dependency '
  'to the response path. We therefore evaluate both the measurement boundary and the placement of authorization.')
p('Federated averaging trains a shared model by aggregating locally computed model states [1]. We use this '
  'training recipe with simulated clients and assess its sensitivity to heterogeneous data. Edge-IIoTset [2] '
  'provides the public-data reference. A separate MQTT workload connects causal traffic observations to actual '
  'gateway enforcement. Smart city and utility infrastructure provide the application context; neither dataset '
  'collection nor evaluation is a deployment in an operating municipal network.')
p('The study asks how much controller authorization adds to a fixed response path, how that path behaves '
  'when the controller becomes unreachable, and how detector misses and source-wide blocking affect useful '
  'service. We distinguish those questions from whether federated training or a particular neural architecture '
  'improves classification. The experiments report unsuccessful detections, failed captures and service costs '
  'alongside successful response times.')

h('1 1 Related work', 2)
p('Federated training, edge inference and local response address different parts of an IDS. '
  'FedAvg [1] supplies a training recipe and Edge-IIoTset [2] supplies a public reference corpus. '
  'IDS-MA [3] evaluates centralized and federated MQTT classifiers. Pope et al. [5] examine '
  'federated anomaly detection using system calls at the edge. Neither comparison makes '
  'their classification scores directly interchangeable with our packet-window task.')
p('Prior work also addresses timeliness and mitigation directly. Dash and Acken [4] distinguish '
  'IDS latency from post-detection latency, while Puccetti and Ceccarelli [7] relate detector '
  'latency to false alarms and coverage. Ma and Su [6] combine federated detection with '
  'cooperative SDN mitigation. Thus the present study does not claim to introduce edge IDS, '
  'latency decomposition or federated mitigation. Its focus is the paired authorization '
  'comparison together with capture validity, missed responses and publisher service costs.')
p('Table 1 is a focused comparison of relevant studies, not a systematic review or a ranking '
  'of scores from incompatible datasets. For [6], only the publisher abstract, highlights and '
  'section previews were accessible; exact numeric comparisons are therefore omitted. '
  'Limitations in the last column describe relevance to our question, not exhaustive weaknesses.')
wide = doc.add_section(WD_SECTION.NEW_PAGE)
wide.orientation = WD_ORIENT.LANDSCAPE
wide.page_width, wide.page_height = Cm(29.7), Cm(21)
wide.left_margin, wide.right_margin = Cm(1.5), Cm(1.5)
table('Table 1. Related work and relevance to detection and response measurement.',
      literature['headers'], literature['rows'], [2.8, 3.0, 3.1, 4.4, 4.1, 4.2, 5.1])
portrait = doc.add_section(WD_SECTION.NEW_PAGE)
portrait.orientation = WD_ORIENT.PORTRAIT
portrait.page_width, portrait.page_height = Cm(21), Cm(29.7)
portrait.left_margin, portrait.right_margin = Cm(2), Cm(2)

h('2 Methods')
h('2 1 Evaluation structure', 2)
p('The three experiments address different questions and use different inputs. Their classification scores '
  'and latency boundaries are not interchangeable. Table 2 defines the evidence supplied by each experiment. '
  'All training and inference run on one laptop or its Docker Desktop Linux virtual machine; federated '
  'clients are simulated rather than separate physical gateways.')
table('Table 2. Experiments and measurement boundaries.',
      ['Experiment', 'Data and scale', 'Primary outcome'],
      [('Public-data benchmark', '12 jobs; filtered Edge-IIoTset records', 'Detection quality on one fixed record split'),
       ('Feature-ready comparison', '3,600 trials; 1,800 matched pairs', 'Prepared feature to command completion'),
       ('Traffic-linked MQTT study', '21 neural jobs plus rate baseline; 60 system episodes', 'Ingress to command, coverage and subscriber delivery')],
      [4.0, 6.1, 6.9])

h('2 2 Public data and sensitivity audit', 2)
p('The public-data experiment uses the author-released DNN-EdgeIIoT-dataset.csv with 2,219,201 records and '
  'a fixed 34-column numeric input schema. Labels, attack-type text, addresses, port values, timestamps, raw '
  'payload and several identifiers are excluded. Relative TCP sequence and acknowledgement values and '
  'ICMP sequence fields remain, so capture-specific artifacts are still possible. Binary attack labels are '
  'the target; attack type is used for sampling, stratification and the original non-IID partition only.')
p('The original preprocessing removes 524,148 records belonging to identical float32 input groups with '
  'both binary labels, and removes 1,265,149 repeated feature rows. An attack type with only one remaining '
  'eligible input is excluded. A stratified sample of 150,000 eligible unique inputs is split with seed 42 '
  'in nominal proportions 70/15/15. Training-only median imputation and standardization are applied. '
  'Validation and test inputs that collide with earlier subsets after preprocessing are removed without '
  'using their labels. Final sizes are 105,000 training, 22,102 validation and 22,105 test records. This is '
  'a filtered random-record benchmark, not a capture-, session- or device-held-out evaluation.')
p('To assess the effect of the exclusions, the frozen original models and validation-selected thresholds '
  'are additionally evaluated on all 524,148 excluded ambiguous records. These records contain only 16 '
  'distinct ambiguous input vectors. Each vector is evaluated once and its confusion counts are weighted '
  'by the original benign and attack frequencies. No retraining or threshold change is performed. The result '
  'is a conditional sensitivity audit, not a new independent estimate for the whole original corpus.')

h('2 3 Models and training recipes', 2)
p('The multilayer perceptron has hidden widths 64 and 32, ReLU activations and dropout 0.1 after the first '
  'hidden layer. The GRU model concatenates each scalar feature with a learned seven-dimensional feature '
  'identity embedding, processes the ordered positions with a 32-unit GRU, and applies additive attention '
  'and a classification head. The GRU sequence consists of feature positions within one observation. '
  'Neither the public-data nor MQTT implementation is a temporal GRU over successive traffic windows.')
p('The public-data recipes are centralized MLP, centralized GRU, FedAvg GRU with IID clients, and FedAvg '
  'GRU with non-IID clients. Five clients participate in every round. The non-IID public-data partition uses '
  'attack-type Dirichlet allocation with alpha 0.3 and partition seed 42. Three training seeds, 42, 43 and 44, '
  'are used with 20 centralized epochs or 20 federated rounds, one full local epoch per round, batch size 256, '
  'AdamW learning rate 0.001, weight decay 0.0001 and gradient norm clipping at 1. Training-only class weighting '
  'is used. Checkpoints maximize validation average precision, and thresholds maximize validation binary F1.')
p('For the MQTT study, all neural recipes use 30 centralized passes or federated rounds, batch size 64 and '
  'the same learning rate, weight decay, gradient clipping and class-weighted binary loss. The recipes are '
  'centralized MLP, centralized GRU, FedMLP IID, FedMLP non-IID, and FedGRU non-IID. Training seeds are '
  '42, 43 and 44. FedMLP non-IID additionally varies partition seeds 42, 43 and 44; the remaining federated '
  'recipes use partition seed 42. MQTT non-IID allocation is by binary label with Dirichlet alpha 0.3, '
  'not by attack family. This gives 21 neural runs. A packet-rate threshold is evaluated as a simple baseline.')
p('MQTT preprocessing means and scales are fitted on training windows only. A near-zero scale below '
  '0.000001 is replaced by one. Checkpoints maximize validation average precision. On CPU, the final '
  'threshold maximizes validation F1 subject to validation FPR no greater than 1%, with the higher threshold '
  'breaking ties. The same threshold rule is applied to packet rate. This is a validation constraint, not '
  'a guarantee on test FPR. Each fixed recipe is evaluated on test data without test-based tuning.')
p('FedAvg weights client parameter states by local sample count. All five clients complete one local pass '
  'per round. Local AdamW state is reset each round, whereas centralized AdamW state persists across epochs. '
  'The comparison therefore concerns complete training recipes and cannot attribute every difference '
  'solely to data placement. Preprocessing and class-weight statistics are computed by the pooled offline '
  'harness. No decentralized statistics protocol, secure aggregation or formal privacy mechanism is evaluated.')

h('2 4 Feature ready response comparison', 2)
p('The controlled response experiment freezes all three non-IID public-data GRU models and their existing '
  'thresholds. A score-independent fixed sample contains 100 benign and 100 attack test records. Each '
  'record is replayed in local and controller-mediated modes at nominal one-way control delays of 0, 10 '
  'and 50 ms. Three model seeds, 200 records, three delays and two modes give 3,600 trials in 1,800 pairs. '
  'Trial order and mode order are randomized before execution. Both members of a pair use the same model, '
  'input, score, threshold, binary policy and enforcement helper.')
p('Timing begins after a complete standardized feature vector has been decoded and validated at edge, '
  'before tensor creation. It includes inference, policy, controller exchange when required, and completion '
  'of the iptables command. Capture and feature preparation are excluded. The controller connection is '
  'established and warmed before timing, and actual round-trip times are calibrated. A dedicated INPUT '
  'chain filters UDP probes addressed to an edge-local sink. Kernel DROP counters, absence of uniquely '
  'tagged post-command probes, continued health-source delivery and restoration after reset verify '
  'enforcement. Probe payloads are separate from the classified feature records; this experiment does not '
  'claim to classify those probe bytes.')

h('2 5 Traffic linked MQTT workload', 2)
p('Three publishers connect through an edge gateway to a Mosquitto broker and a subscriber. Each episode '
  'lasts six seconds, with additional setup and a 0.3-second drain period. One source increases its offered '
  'PUBLISH rate during a designated attack interval. The other sources remain legitimate. Training, '
  'validation and test episodes vary source role independently of low, medium and high rate levels, '
  'nominally 200, 800 and 2,500 messages/s with 15% variation. Legitimate publishers send 8–25 messages/s '
  'and 80–180 messages/s bursts. System episodes use 15 messages/s and 120 messages/s legitimate bursts. '
  'Payload size is fixed within an episode and equal across source roles. The modeled attack is a synthetic '
  'publish flood; its designation does not imply that the broker necessarily loses availability.')
p('Attack onset is randomized between 1.125 and 1.375 seconds relative to the observation start, and the '
  'attack interval ends at 3.875 seconds. This varies its phase relative to window boundaries. An exact '
  'message schedule is generated and saved before sending. Workload seeds and relative offered schedules '
  'are identical across matched system conditions. The generator records scheduled messages, aggregate '
  'attempts, socket-accepted message IDs, errors and skips. A message more than 50 ms overdue is skipped '
  'rather than silently moving the offered schedule. TCP blocking and retransmission can therefore change '
  'realized traffic even when offered schedules match. Socket acceptance does not establish ingress or delivery.')
p('The dedicated topology has separate source, protected, control and management networks. Publishers '
  'connect to the edge address; DNAT forwards traffic to the broker and SNAT supplies the edge protected '
  'address. The edge FORWARD chain sees original publisher addresses before SNAT and applies source-specific '
  'DROP rules. Ingress capture retains publisher identities; broker delivery is attributed by independently '
  'instrumented application message IDs. A post-NAT address is not used to infer the original publisher. '
  'No host ports or Docker socket are exposed.')

h('2 6 Causal observations and ground truth', 2)
p('One observation is an active source in a non-overlapping 250 ms window. Empty windows are not classified. '
  'A fixed 20 ms holdback allows capture processing of packets that have already arrived and contributes '
  'to response delay. The 12 numeric features are log packet rate, log byte rate, mean and standard deviation '
  'of frame length and packet interarrival time, SYN/ACK/RST fractions, log count of distinct source ports, '
  'mean TCP payload length and fraction of packets carrying payload. The source-port count is used, but '
  'port values, addresses, contents, message IDs, episode IDs and truth markers are excluded.')
p('AF_PACKET capture records kernel SO_TIMESTAMPNS timestamps and nanosecond PCAP. Offline replay '
  'recomputes the features from raw packets. TCP streams are reassembled by flow and raw sequence position. '
  'PUBLISH message IDs and their independently designated benign/attack tags are reconciled to TCP byte '
  'ranges. A source window is attack-positive only when it contains bytes from a designated malicious '
  'PUBLISH. If those bytes span windows, each corresponding window is positive. ACK-only windows are not '
  'labelled attacks merely because an attack occurs elsewhere in the episode. Instrumentation tags have '
  'equal length and are never classifier inputs.')
p('Three commissioning episodes precede data collection. The dataset contains 36 training, 12 validation '
  'and 12 test episodes with disjoint traffic seeds and no mitigation during collection. Whole episodes '
  'define the split, and repeated or ambiguous feature windows are retained. All 60 dataset episodes '
  'pass the strict capture/feature-replay and TCP/MQTT reconstruction checks. Table 3 reports the resulting '
  'observation counts.')
audit = json.loads((ROOT / 'data/online/dataset-audit.json').read_text())
table('Table 3. Whole-episode splits for the separately trained MQTT detector.',
      ['Split', 'Episodes', 'Active source windows', 'Attack-positive windows'],
      [(name, len(audit['splits'][key]['episodes']), audit['splits'][key]['windows'], audit['splits'][key]['positive'])
       for name, key in [('Training', 'train'), ('Validation', 'val'), ('Test', 'test')]], [3.3, 2.7, 5.5, 5.5])

h('2 7 System conditions and decision policy', 2)
p('The deployed detector is preselected as FedMLP non-IID partition 42, training seed 42, independently of '
  'test scores. The 2,945-parameter model is exported to CPU TorchScript; probability and threshold-decision '
  'parity are checked before deployment. No better-performing test model replaces it. All system conditions '
  'use its fixed threshold 0.499143. Local mode authorizes and installs a one-second source DROP at edge. '
  'Controller mode sends flagged edge alerts over a warmed persistent TCP connection for authorization '
  'and then invokes the same edge rule helper. Inference remains at edge in both modes. Observation-only '
  'mode runs the detector without applying rules. Quarantine is not implemented or evaluated.')
p('Nine independent workload seeds cover three rate levels and three source roles. Each workload runs '
  'under observation-only, local and controller modes at 0 and 50 ms nominal one-way control delay: '
  '54 regular condition episodes. Three additional workloads run in local and controller modes during '
  'actual 100% packet loss on the controller path, giving six outage episodes and 60 assigned episodes '
  'overall. Conditions execute in a predeclared randomized order. Repeated conditions on one workload '
  'are paired observations, not independent new workloads.')
p('Delay is applied to both control-path egresses and actual RPC round trips are calibrated. The data and '
  'management paths are separate. Outage is introduced after normal RPC warmup. Controller timeout is '
  'one second with fail-open behavior and no fallback or retry. Epoch checks prevent delayed responses '
  'from acting in another episode. Capture and window formation continue independently of inference; '
  'a blocking authorization request can therefore create a queue of unprocessed observations. Historical '
  'rule counters are retained before expiry, replacement and episode stop.')

h('2 8 Timing metrics and quality controls', 2)
p('For the traffic-linked experiment, t0 is the converted monotonic kernel ingress timestamp of the first '
  'reconciled malicious PUBLISH bytes. The primary endpoint tc is successful return of the firewall command. '
  'A correct response additionally requires that the actual triggering source window is attack-positive. '
  'A command triggered by a benign window is not reclassified as a correct detection merely because an '
  'attack is active. The endpoint is an observed upper bound on rule installation, not a directly '
  'instrumented kernel commit or first-drop timestamp.')
table('Table 4. Decomposition of traffic-linked arrival-to-command time.',
      ['Component', 'Definition'],
      [('First attack window readiness', 't1 − t0; t1 is readiness of the first attack-positive source window'),
       ('Waiting for a later trigger', 't2 − t1; t2 is readiness of the actual triggering window'),
       ('Trigger queue', 't3 − t2; t3 is inference start'),
       ('Trigger inference', 't4 − t3; t4 is completion of the model decision'),
       ('Authorization and enforcement', 'tc − t4; includes controller exchange when used and command execution')], [5.3, 11.7])
p('The components sum to tc − t0 for each response. Their separate medians need not sum to the median total. '
  'RPC and firewall installation are not separated further because this journal does not timestamp their '
  'individual boundaries. Containers share the kernel boot ID and equal monotonic namespace offsets; '
  'timestamp conversion uncertainty is recorded. The maximum recorded conversion uncertainty is 10.41 µs.')
p('Episode response coverage is reported beside latency. A miss or failure contributes to the assigned '
  'denominator and has no successful response latency. A capture/label reconstruction is invalid if it '
  'has kernel drops, late packets, missing TCP bytes, MQTT parse errors, empty observations or feature '
  'replay error at least 0.00000001. Invalid episodes are retained, and their candidate response times are '
  'excluded from primary timing summaries. Subscriber service records remain independent evidence.')
p('Attack-class F1, recall, FPR and average precision describe held-out classification. Means and sample '
  'standard deviations over training seeds describe optimization variation on the same test episodes. '
  'Per-model F1 intervals use 2,000 bootstrap resamples of whole test episodes; they do not treat windows '
  'as independent replications. System comparisons pair workload IDs and control conditions. The small '
  'number of workloads supports descriptive comparisons rather than broad population inference.')
p('Legitimate delivery is the fraction of scheduled benign messages received by the subscriber, including '
  'scheduled messages never attempted. Normal-message delay is measured from actual send timestamp '
  'to subscriber receipt, conditional on delivery; planned-time-to-delivery is preserved separately. '
  'Failed attempts lack per-message tags, so benign attempt counts are bounded rather than invented. '
  'Attack delivery counts, other-source delivery, recovery after attack end plus nominal TTL, CPU time '
  'per active wall time and sampled resident memory are also recorded.')
p('The host is an AMD Ryzen 5 4600H laptop with 24 GB RAM and a GTX 1650 Ti with 4 GB VRAM. Training uses '
  'PyTorch 2.9.1 with CUDA; online inference uses CPU PyTorch 2.9.1 in the Docker Desktop/WSL2 VM with '
  'four virtual CPUs and approximately 6 GB RAM. The edge is pinned to one virtual CPU and limited to '
  '1,536 MB. The broker has a 0.25-CPU limit. These are virtualized resource settings, not measurements '
  'on Raspberry Pi, Jetson or production gateways.')

h('3 Results')
doc.paragraphs[-1].paragraph_format.page_break_before = True
h('3 1 Public benchmark and exclusion sensitivity', 2)
table('Table 5. Filtered public-data test results as mean ± sample SD over three training seeds.',
      ['Training recipe', 'Attack F1', 'Recall', 'FPR'],
      [(r['method'], f"{float(r['f1_mean']):.4f} ± {float(r['f1_sd']):.4f}",
        f"{float(r['recall_mean']):.4f}", f"{float(r['fpr_mean']):.4f}") for r in legacy], [6.2, 4.8, 3.0, 3.0])
p('The centralized MLP has the highest mean F1 in this filtered benchmark. The small difference between '
  'centralized and federated GRU recipes applies to one fixed random-record split after substantial input '
  'selection. It does not establish equivalence on new devices, independent captures or the live MQTT workload.')
p('The ambiguous-input exclusions affect 23.62% of the original corpus: 347,071 benign and 177,077 attack '
  'records. Most frozen original models predict attack for the entire excluded cohort, giving recall 1.0 '
  'and FPR 1.0 within that cohort. Two MLP seeds retain FPR about 0.7502. The 524,148 rows represent only '
  '16 distinct inputs, so this is not evidence from 524,148 independent tests. These findings show that '
  'the earlier high F1 is sensitive to which inputs are retained. They do not justify calling the original '
  'labels erroneous or presenting the cohort-specific result as whole-corpus accuracy.')

h('3 2 Prepared feature response comparison', 2)
p('All 3,600 assigned trials complete with 1,800 matched pairs and no technical failures. There are 1,806 '
  'verified block outcomes and 1,794 verified allow outcomes. Every local/controller pair has identical '
  'scores and policy decisions. Local successful-block medians across the three models are approximately '
  '3.6 ms. Controller-mediated medians are approximately 4.0 ms at zero added delay, 24.5 ms at 10 ms one-way '
  'delay, and 104.5 ms at 50 ms one-way delay. Measured policy-RPC median round trips are 0.227, 20.634 '
  'and 100.673 ms, respectively.')
p('The selected 200 feature observations contain 100 attack and 100 benign records. All attack observations '
  'are blocked by each frozen model in this small sample; one model also blocks one benign observation, '
  'consistently across conditions. The repeated trials are systems measurements and do not increase the '
  'number of independent classification observations. These results isolate controller-path overhead '
  'after features are ready and must not be reported as raw-traffic arrival-to-response latency.')

h('3 3 Held out MQTT detector quality', 2)
groups = collections.defaultdict(list)
for result in detectors:
    groups[(result['method'], result.get('partition_seed'))].append(result)
names = {'mlp-central': 'Central MLP', 'gru-central': 'Central GRU attention', 'fedmlp-iid': 'FedMLP IID',
         'fedmlp-noniid': 'FedMLP non-IID', 'fedgru-noniid': 'FedGRU non-IID', 'rate-threshold': 'Packet rate'}
quality_rows = []
order = [('mlp-central', None), ('gru-central', None), ('fedmlp-iid', 42), ('fedmlp-noniid', 42),
         ('fedmlp-noniid', 43), ('fedmlp-noniid', 44), ('fedgru-noniid', 42), ('rate-threshold', None)]
for method, part in order:
    entries = groups[(method, part)]
    f1 = [e['test_metrics']['f1'] for e in entries]
    f1text = f'{statistics.mean(f1):.4f}' + (f' ± {statistics.stdev(f1):.4f}' if len(f1) > 1 else '')
    quality_rows.append((names[method], str(part) if part is not None else '—', len(entries),
                         f1text, f'{mean(entries, "recall"):.4f}', f'{mean(entries, "fpr"):.4f}'))
table('Table 6. MQTT test quality on 12 whole held-out episodes. F1 uncertainty here is seed SD.',
      ['Recipe', 'Partition seed', 'Runs', 'Attack F1', 'Recall', 'FPR'], quality_rows,
      [5.0, 2.0, 1.2, 4.0, 2.4, 2.4])
p('Centralized MLP and FedMLP IID obtain similar mean F1, 0.9786 and 0.9785. Packet rate alone obtains '
  'F1 0.9485, and the centralized GRU mean is 0.9497. Thus the workload does not establish a GRU advantage '
  'or a need for a complex recurrent classifier. Non-IID FedMLP is much more sensitive to partition than '
  'to initialization within the better-performing partitions: mean F1 changes from 0.8072 for partition 42 '
  'to 0.0144 for partition 43 and 0.8224 for partition 44. All failed recipes remain in Table 6.')
p('Partition 43 assigns 1,451 of 2,598 training windows to an entirely benign client; another 382-window '
  'client contains about 0.5% attack windows. The imbalance is compatible with client drift and an '
  'unfavorable threshold operating point under this full-local-pass recipe, but the experiment does not '
  'isolate one causal mechanism or establish that FedAvg always fails under non-IID data. The FedGRU '
  'non-IID mean F1 is 0.8804, with mean test FPR 0.0197 despite the validation-only FPR constraint.')
p('The preselected deployed model has attack F1 0.7966, precision 0.9495, recall 0.6861 and FPR 0.0069. '
  'Its test confusion counts are TN 723, FP 5, FN 43 and TP 94. Its whole-episode bootstrap 95% F1 interval '
  'is [0.6047, 0.9249]. This interval is wide, reflecting the small number of held-out episodes. Deployment '
  'retains this model rather than substituting the highest test-scoring recipe.')

h('3 4 Traffic linked response and coverage', 2)
p('All 60 assigned condition episodes complete. Fifty-eight have valid capture and label reconstruction. '
  'Table 7 reports valid episodes, correct responses and conditional ingress-to-command medians separately. '
  'Observation-only mode deliberately installs no rule and is not counted as a detection-response failure. '
  'Its subscriber delivery is included in the service comparison.')
response_rows = []
for c in sorted((c for c in cells if not c['outage'] and c['mode'] != 'none'),
                key=lambda c: (c['rate_level'], c['delay_ms'], c['mode'])):
    response_rows.append((['Low', 'Medium', 'High'][c['rate_level']], c['delay_ms'],
                          'Controller' if c['mode'] == 'central' else 'Local',
                          f'{c["valid_episodes"]}/{c["episodes"]}', f'{c["responded_episodes"]}/{c["episodes"]}',
                          f'{c["arrival_to_command_median_ms"]:.2f}' if c['arrival_to_command_median_ms'] is not None else 'N/A'))
table('Table 7. Regular conditions. Latency is conditional on a valid attack-window-triggered response.',
      ['Load', 'One-way delay ms', 'Mode', 'Valid / assigned', 'Responses / assigned', 'Median ms'],
      response_rows, [2.1, 2.5, 3.1, 3.0, 3.4, 2.9])
p('The low-rate workload produces a response in only one of three assigned episodes per mode and delay. '
  'A short latency among detected episodes must therefore be interpreted together with coverage. '
  'Higher-rate attacks usually trigger earlier within the first attack-positive window, whereas weak '
  'evidence can require a later window or produce no response at all.')
pair_rows = []
for delay in [0, 50]:
    pairs = [r for r in study['paired_conditions'] if r['delay_ms'] == delay and not r['outage']]
    differences = [r['central_minus_local_response_ms'] for r in pairs if r['central_minus_local_response_ms'] is not None]
    pair_rows.append((delay, len(pairs), sum(r['both_valid'] for r in pairs), len(differences),
                      f'{statistics.median(differences):.2f}'))
table('Table 8. Paired controller minus local arrival-to-command differences.',
      ['One-way delay ms', 'Assigned workload pairs', 'Both valid', 'Both respond', 'Median difference ms'],
      pair_rows, [3.0, 4.0, 3.1, 3.1, 3.8])
p('At 50 ms one-way delay, the median paired difference is 99.27 ms among six workloads with two valid '
  'responses; at zero added delay, it is 0.26 ms among seven such workloads. One additional pair at '
  '50 ms lacks two valid reconstructions, and low-rate misses further reduce the paired latency sample. '
  'These are conditional paired results, not a guarantee that local mode always responds earlier in every '
  'realization. Actual TCP packetization, capture timing and the triggering window can vary across matched '
  'offered workloads.')
p('The directly timestamped response components confirm that the controller path dominates the additional '
  'post-decision cost at 50 ms delay: median combined authorization/enforcement is 104.16 ms for controller '
  'mode and 4.71 ms for local mode. Those component medians aggregate seven and six valid responding '
  'episodes respectively. The complete onset-to-command measurement also includes window readiness, '
  'any wait for later triggering windows, queueing and inference. It cannot be replaced by the approximately '
  '3.6 ms feature-ready number from the separate replay experiment.')

h('3 5 Service delivery outage and capture reliability', 2)
service_rows = []
for c in sorted((c for c in cells if c['delay_ms'] == 50 and not c['outage']),
                key=lambda c: (c['rate_level'], ['none', 'local', 'central'].index(c['mode']))):
    service_rows.append((['Low', 'Medium', 'High'][c['rate_level']],
                         {'none': 'No mitigation', 'local': 'Local', 'central': 'Controller'}[c['mode']],
                         f'{100*c["benign_delivery_mean"]:.2f}', f'{c["attack_messages_mean"]:.1f}'))
table('Table 9. Subscriber service at 50 ms one-way delay. Means over three assigned episodes per cell.',
      ['Load', 'Mode', 'Scheduled benign delivered percent', 'Attack messages delivered'],
      service_rows, [2.6, 4.1, 5.2, 5.1])
p('Mitigation reduces delivered attacking messages at medium and high offered loads, while differences '
  'at low load are small. All observation-only episodes deliver every scheduled benign message, so the '
  'experiment does not demonstrate an availability gain. Both other publishers retain 100% benign delivery '
  'in all 60 episodes. Lost legitimate messages belong to the publisher that is also the blocked attack '
  'source. This is collateral cost of source-wide filtering and TCP disruption, not evidence that every '
  'lost benign message was caused by a false-positive triggering window.')
p('After attack end plus nominal TTL, the worst scheduled-benign delivery ratio is 0.5086. Later '
  'decisions, retransmissions and TCP state can delay recovery beyond a single TTL interval. Historical '
  'firewall counters record 2,579 DROP packets across all conditions. Packet drops and delivered PUBLISH '
  'counts are different units, and neither alone establishes exact first-drop latency. Within the 58 valid '
  'reconstructed episodes, no block command is triggered by a benign window. The two invalid episodes '
  'cannot establish absence of false blocks.')
outage_rows = []
for c in sorted((c for c in cells if c['outage']), key=lambda c: c['mode']):
    outage_rows.append(('Controller' if c['mode'] == 'central' else 'Local',
                        f'{c["responded_episodes"]}/{c["episodes"]}', c['response_failures'],
                        f'{100*c["benign_delivery_mean"]:.2f}', f'{c["attack_messages_mean"]:.1f}'))
table('Table 10. Real controller-path outage with otherwise intact data and management paths.',
      ['Mode', 'Responses / assigned', 'Authorization failures', 'Benign delivered percent', 'Attack messages delivered'],
      outage_rows, [3.0, 3.5, 3.5, 3.5, 3.5])
p('Local mode responds in three of three outage workloads and controller mode in none. Controller mode '
  'records 16 authorization failures and leaves 42, 43 and 44 windows unprocessed at the respective '
  'episode stops. Its fail-open policy preserves delivery but also allows the attack workload through. '
  'Local mode restricts attack delivery while retaining the same source-blocking service trade-off. '
  'An asynchronous controller client, fallback policy or different timeout could change this behavior; '
  'those alternatives are not evaluated.')
p('Two high-rate episodes fail capture reconstruction. The local, 50 ms workload-08 episode has two '
  'kernel capture drops and an incomplete MQTT parse. The observation-only counterpart has 274 capture '
  'drops, 1,401 late packets, missing TCP bytes, parse errors and feature replay mismatch. Both remain '
  'in the assigned ledger and subscriber-based service statistics; their response latency candidates are '
  'excluded. Thus the online pipeline is not lossless under every tested condition. Across completed '
  'episodes, measured edge CPU time is about 5.1–24.9% of one core per active wall interval, with sampled '
  'peak resident memory up to 250.2 MB. These resource figures do not establish a saturation capacity.')

h('4 Discussion')
p('The controlled feature-ready comparison and the traffic-linked experiment support a consistent '
  'placement result: when the detector already runs at edge, controller authorization adds approximately '
  'a control round trip to successful reaction. Keeping authorization local also removes that controller '
  'dependency during the tested outage. This placement effect is separate from the training algorithm. '
  'It is not evidence that federated training itself reduces inference or response time.')
p('The more important qualification is that reaction depends on observation quality and detection '
  'coverage. At low rates, a successful local path cannot compensate for a model that fails to trigger. '
  'At high rates, a causal capture implementation can itself lose observations. Reporting only successful '
  'latency would conceal both problems. The paired coverage and validity denominators are therefore '
  'part of the main result rather than supplementary implementation details.')
p('The classification comparisons also change the architectural interpretation. The centralized MLP '
  'performs at least as well as the tested feature-axis GRU recipes, and the packet-rate baseline is '
  'competitive on the publish-flood task. Non-IID partition sensitivity is substantial. The contribution '
  'is a measured detection-to-enforcement path and its limits; the experiments do not establish that '
  'a novel neural architecture or federated recipe is required for this workload.')
p('For a utility gateway, distinguishing the attacking device from other devices is useful but insufficient '
  'to establish safe mitigation. A compromised publisher may still emit legitimate telemetry. Source-wide '
  'DROP suppresses both kinds of traffic and can extend disruption through TCP state. In the tested '
  'workloads, the unmitigated broker already delivers all benign messages, so an availability improvement '
  'would be an unsupported claim. A production policy would need application-specific safety and recovery '
  'requirements beyond the binary rule evaluated here.')

h('5 Limitations')
p('All systems measurements come from one virtualized laptop. CPU pinning and limits improve control '
  'within this environment but do not reproduce production edge hardware, radio links, geographic '
  'distances or independent device failures. Nine regular and three outage workloads, with three '
  'replicates per rate, provide limited replication. Training seeds and repeated network conditions '
  'do not create independent hardware or dataset replications.')
p('The online task is short-duration synthetic MQTT publish-flood detection. It excludes stealthy attacks, '
  'other protocols, novel attack families, drift, adaptive attackers and adversarial client updates. Whole '
  'episodes prevent record mixing across online splits, but they are generated by the same workload '
  'mechanism. The original public-data benchmark has a different, filtered record-level split and remains '
  'vulnerable to session artifacts. Neither benchmark demonstrates generalization to an operating utility.')
p('Federated clients execute sequentially in simulation with pooled preprocessing metadata. No physical '
  'federation transport, differential privacy, secure aggregation, update-inversion test or communication '
  'energy measurement is included. Controller mode is a small alert-authorization service, not a full '
  'SDN controller implementation. Only allow and source DROP with TTL are evaluated, and command '
  'completion is an upper bound on installation. Exact kernel commit, exact first-drop time and separate '
  'RPC-versus-rule execution decomposition remain unmeasured. Two capture failures and delayed recovery '
  'are retained as observed limits of the present implementation.')

h('6 Conclusion')
p('Local authorization shortens successful edge response by the controller-path overhead and retains '
  'the ability to block during the tested controller outage. A complete evaluation must also account for '
  'window formation, detector misses, capture reliability and the service cost of enforcement. In this '
  'MQTT workload, the non-IID detector misses some weak attacks, client partition can severely degrade '
  'classification, and source blocking reduces attack delivery at a cost to that source’s legitimate '
  'messages. These bounded findings support response-latency evaluation of a federated edge architecture '
  'while leaving broad detection superiority, production reliability and privacy guarantees unestablished.')

h('Appendix A Controller delay extension 2b')
p('Experiment 2b is an implemented protocol extension awaiting network execution. It contributes '
  'no new measured result to the abstract, Results or Conclusion. It reuses the three frozen '
  'non-IID GRU models, their thresholds and the same 200 observations from the completed '
  'feature-ready experiment. The base grid is 0, 10, 50, 100 and 250 ms one-way delay '
  '(6,000 trials); optional 500 ms gives 7,200 trials. A separate calibration connection '
  'has a ten-second total deadline. The trial authorization deadline is one second across '
  'reconnect, transmission and the complete reply; failure is fail-open without fallback.')
p('The report separates detector misses, block decisions prevented by timeouts, other controller '
  'errors and verified enforcement. Failed or missing responses stay in the assigned denominator '
  'and receive no successful latency. The 500 ms condition stresses the configured deadline '
  'and connection recovery, rather than identifying a universal failure point for city networks. '
  'Added time is fitted to measured RTT descriptively; shared block calibrations do not justify '
  'ordinary independent-sample standard errors.')
p('A separate rate profile uses one frozen model, 200 observations, delays 0 and 50 ms and '
  'UDP probe rates 200, 800 and 2,500 packets/s, giving 2,400 trials. It isolates probe load '
  'while holding classifier inputs fixed. Counter read intervals and boundary uncertainty '
  'are recorded explicitly. Passed packets in that interval are not exact attack-onset-to-rule '
  'counts, and UDP packets must not be equated with MQTT messages. This profile remains unexecuted.')
p('For a constant realized message rate lambda and an otherwise identical successful response, '
  'an explanatory approximation is delta N = lambda times delta T. Table A1 uses an illustrative '
  'extra delay of 100 ms; it is a calculation, not an experiment 2b result. Missed detections, '
  'TCP backpressure, finite attacks, retransmissions and recovery can invalidate the approximation. '
  'Message volume is an exposure measure; useful-service harm also requires delivery and recovery metrics.')
table('Table A1. Calculated extra messages for an illustrative 100 ms response delay.',
      ['Constant realized rate messages per second', 'Extra delay seconds', 'Calculated extra messages'],
      [('200', '0.100', '20'), ('800', '0.100', '80'), ('2,500', '0.100', '250')], [7, 5, 5])
p('The completed MQTT experiment already varies offered rate and retains subscriber counts '
  'before command completion, total attack delivery and legitimate delivery. Those observations '
  'remain the primary service evidence. Larger netem delays are sensitivity conditions; mapping '
  'them to LTE-M or NB-IoT requires primary measurements of the actual edge-to-controller path.')

h('References')
p('[1] H. B. McMahan, E. Moore, D. Ramage, S. Hampson, and B. Agüera y Arcas. Communication-Efficient '
  'Learning of Deep Networks from Decentralized Data. Proceedings of the 20th International Conference '
  'on Artificial Intelligence and Statistics, PMLR 54, pp. 1273–1282, 2017. '
  'https://proceedings.mlr.press/v54/mcmahan17a.html')
p('[2] M. A. Ferrag, O. Friha, D. Hamouda, L. Maglaras, and H. Janicke. Edge-IIoTset: A New Comprehensive '
  'Realistic Cyber Security Dataset of IoT and IIoT Applications for Centralized and Federated Learning. '
  'IEEE Access, vol. 10, pp. 40281–40306, 2022. https://doi.org/10.1109/ACCESS.2022.3165809')

for item in literature['references']:
    p(f"[{item['id']}] {item['reference']} {item['url']}")

h('Data and reproducibility')
p('The author release of Edge-IIoTset [2], fixed protocols, source snapshots, checkpoints, raw PCAP, '
  'message and subscriber records, predictions and environment metadata are retained locally. '
  'The ledger includes all 60 system episodes. Matched offered schedules, frozen sources and '
  'running container code are verified, and 11 automated checks pass. A public artifact release '
  'is not asserted.')

OUT.mkdir(exist_ok=True)
doc.save(DOCX)
# Retain editable text and exact evidence locations separately from the reader-facing manuscript.
text = '\n\n'.join(para.text for para in doc.paragraphs if para.text)
(OUT / 'manuscript_text.txt').write_text(text, encoding='utf-8')
provenance = {
    'document': str(DOCX.relative_to(ROOT)),
    'language': 'English',
    'scope': 'Evidence-aligned local manuscript with Methods Results Discussion, a verified focused literature matrix and an explicitly unexecuted experiment 2b appendix.',
    'evidence': [str(SOURCE.relative_to(ROOT)), 'ONLINE_PROTOCOL.md', 'PROTOCOL.md', 'RESPONSE_PROTOCOL.md', 'response_2b/PROTOCOL_2B.md', 'manuscript/sources/literature_review.json',
                 'runs/response/full-20261104T153359Z/RESULTS.md',
                 'runs/overnight-2026-11-04T14-57-07-088Z/summary.csv',
                 'runs/extension-audit/excluded-cohort-sensitivity.json', 'data/processed/audit.json',
                 'data/online/dataset-audit.json', 'runs/online/final-v1/final-verification.json'],
    'source_document': 'https://docs.google.com/document/d/1la7B88pgKXWi5_aZNUsmOoPmb0W4u3pBFf1aco5NBnI/edit',
    'verified_external_references': ['https://proceedings.mlr.press/v54/mcmahan17a.html',
                                     'https://doi.org/10.1109/ACCESS.2022.3165809'],
    'literature_sources': literature['references'],
    'experiment_2b_status': 'Implemented and unit tested; network runs not performed',
    'tables': len(doc.tables),
    'main_text_word_count': len(text.split()),
    'docx_sha256': hashlib.sha256(DOCX.read_bytes()).hexdigest(),
}
(OUT / 'document_provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
print(json.dumps(provenance, indent=2))
