"""Summarize completed repetitions; never manufacture missing results."""
import argparse
import csv
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def report(run):
    run = Path(run)
    results = [json.loads(path.read_text(encoding='utf-8')) for path in sorted(run.glob('*/result.json'))]
    results = [result for result in results if result.get('profile') == 'overnight']
    if not results:
        print('No completed overnight jobs yet.')
        return
    keys = ['accuracy', 'precision', 'recall', 'f1', 'macro_f1', 'fpr', 'pr_auc_ap', 'roc_auc']
    rows = []
    for method in sorted({result['method'] for result in results}):
        matches = [result for result in results if result['method'] == method]
        row = {'method': method, 'repetitions': len(matches)}
        for key in keys:
            values = [result['metrics'][key] for result in matches]
            row[key + '_mean'] = float(np.mean(values))
            row[key + '_sd'] = float(np.std(values, ddof=1)) if len(values) > 1 else None
        row['training_seconds_mean'] = float(np.mean([result['training_seconds'] for result in matches]))
        rows.append(row)
    with (run / 'summary.csv').open('w', newline='', encoding='utf-8') as output:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    columns = ['f1', 'macro_f1', 'recall', 'fpr', 'pr_auc_ap']
    lines = ['# Detection experiment results', '',
             'Fixed deduplicated random-record split; values are mean ± sample SD over training seeds.', '',
             '| Method | Completed seeds | F1 | Macro-F1 | Recall | FPR | AP |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for row in rows:
        cells = [row['method'], str(row['repetitions'])]
        for key in columns:
            mean, sd = row[key + '_mean'], row[key + '_sd']
            cells.append(f'{mean:.4f}' + (f' ± {sd:.4f}' if sd is not None else ' (one seed)'))
        lines.append('| ' + ' | '.join(cells) + ' |')
    lines += ['', 'These are offline detection results, not full detection-to-response measurements.',
              'The GRU attends over ordered features of one record; no temporal traffic window is modelled.',
              'See PROTOCOL.md and data-audit.json for exclusions and evaluation limits.']
    (run / 'RESULTS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 5))
    for method in sorted({result['method'] for result in results}):
        histories = []
        for result in results:
            if result['method'] == method:
                records = [json.loads(line) for line in (run / result['job'] / 'history.jsonl').read_text().splitlines()]
                # A resumed round can appear twice in a history; retain its last entry.
                records = {record['step']: record['val_ap'] for record in records}
                histories.append([records[step] for step in sorted(records)])
        length = min(map(len, histories))
        values = np.array([history[:length] for history in histories])
        steps = np.arange(1, length + 1)
        mean = values.mean(axis=0)
        curve, = ax.plot(steps, mean, label=method)
        if len(values) > 1:
            sd = values.std(axis=0, ddof=1)
            ax.fill_between(steps, np.maximum(0, mean - sd), np.minimum(1, mean + sd), alpha=0.12, color=curve.get_color())
    ax.set(xlabel='Centralized epoch / FedAvg round (one pass per training record)',
           ylabel='Validation average precision', title='Detection training convergence')
    ax.legend()
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(run / 'validation-convergence.png', dpi=180)
    plt.close(fig)
    print('\n'.join(lines), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', type=Path)
    args = parser.parse_args()
    directory = args.run_dir or Path(json.loads((ROOT / 'runs/active.json').read_text())['runDir'])
    report(directory)
