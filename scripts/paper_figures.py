"""Paper figures 1-4, generated from results/online/summary.json (no hand-typed numbers)."""
import json
import statistics
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / 'results' / 'figures'
FIG.mkdir(exist_ok=True)
study = json.loads((ROOT / 'results/online/summary.json').read_text())
episodes = study['system_episodes']

plt.rcParams.update({
    'font.family': 'serif', 'font.serif': ['Times New Roman', 'DejaVu Serif'],
    'font.size': 10, 'axes.titlesize': 10, 'axes.labelsize': 10, 'legend.fontsize': 9,
    'xtick.labelsize': 9, 'ytick.labelsize': 9, 'axes.spines.top': False, 'axes.spines.right': False,
    'savefig.dpi': 300, 'savefig.bbox': 'tight', 'savefig.pad_inches': 0.04,
})
LOCAL, CTRL, NONE = '#1f6f8b', '#c8553d', '#8a8a8a'
LOADS = ['Low', 'Medium', 'High']


def ok(e):
    return e['reconciliation_valid'] and e['response_observed']


# Figure 1: testbed and the two authorization paths -------------------------------------------
def box(ax, x, y, w, h, text, fc='#ffffff', ec='#333333', lw=1.0, size=9, weight='normal'):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.02,rounding_size=0.08',
                                fc=fc, ec=ec, lw=lw))
    ax.text(x + w / 2, y + h / 2, text, ha='center', va='center', fontsize=size, weight=weight)


def arrow(ax, a, b, color='#333333', style='-|>', lw=1.1, ls='-', rad=0.0):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle=style, mutation_scale=10, color=color, lw=lw,
                                 linestyle=ls, connectionstyle=f'arc3,rad={rad}'))


fig, ax = plt.subplots(figsize=(6.6, 3.5))
ax.set_xlim(0, 13.2)
ax.set_ylim(0, 7)
ax.axis('off')
for i, label in enumerate(['Publisher A', 'Publisher B', 'Publisher C\n(attack source)']):
    box(ax, 0.1, 4.9 - i * 1.55, 2.0, 1.15, label, fc='#fbe9e5' if i == 2 else '#f3f3f3', size=8.5)
    arrow(ax, (2.1, 5.47 - i * 1.55), (3.35, 3.9 - (1 - i) * 0.35))
ax.text(1.1, 0.75, 'source network', ha='center', fontsize=8, style='italic', color='#555555')
ax.add_patch(FancyBboxPatch((3.35, 0.45), 4.6, 5.9, boxstyle='round,pad=0.02,rounding_size=0.12',
                            fc='#eef4f7', ec=LOCAL, lw=1.4))
ax.text(5.65, 6.05, 'Edge gateway (1 vCPU)', ha='center', fontsize=9.5, weight='bold')
steps = ['AF_PACKET capture\n(kernel timestamps)', '250 ms source windows\n12 causal features',
         'FedMLP inference\n(TorchScript, CPU)', 'Policy + iptables\nsource DROP (TTL 1 s)']
for i, s in enumerate(steps):
    box(ax, 3.7, 4.75 - i * 1.25, 3.9, 0.95, s, size=8.3)
    if i:
        arrow(ax, (5.65, 4.75 - (i - 1) * 1.25), (5.65, 5.7 - i * 1.25))
arrow(ax, (7.95, 3.4), (9.25, 3.4))
ax.text(8.6, 3.55, 'DNAT', ha='center', fontsize=7.5, color='#555555')
box(ax, 9.25, 2.85, 1.75, 1.1, 'Mosquitto\nbroker', size=8.5)
arrow(ax, (11.0, 3.4), (11.5, 3.4))
box(ax, 11.5, 2.85, 1.6, 1.1, 'Subscriber\n(delivery log)', size=8)
ax.text(10.2, 2.4, 'protected network', ha='center', fontsize=8, style='italic', color='#555555')
box(ax, 9.6, 0.95, 3.5, 1.0, 'Controller\n(authorization RPC)', fc='#fbe9e5', ec=CTRL, size=8.5)
arrow(ax, (7.6, 1.7), (9.6, 1.7), color=CTRL, lw=1.3)
arrow(ax, (9.6, 1.2), (7.6, 1.2), color=CTRL, lw=1.3)
ax.text(8.8, 1.78, 'alert', ha='center', fontsize=7.5, color=CTRL)
ax.text(8.8, 0.88, 'allow / block', ha='center', fontsize=7.5, color=CTRL)
ax.text(11.35, 0.35, 'control network: netem 0 / 50 ms\nor 100% loss (outage)', fontsize=7.5,
        color=CTRL, ha='center', va='center')
ax.text(5.65, 0.7, 'local path: decision and rule on edge', ha='center', fontsize=7.5,
        color=LOCAL, style='italic')
fig.savefig(FIG / 'fig1_testbed.png')
plt.close(fig)


# Figure 2: decomposition of arrival-to-command at 50 ms delay --------------------------------
comps = [('onset_to_first_attack_window_ready_ms', 'First attack window ready'),
         ('subsequent_window_wait_ms', 'Wait for triggering window'),
         ('trigger_window_queue_ms', 'Queue'),
         ('trigger_window_inference_ms', 'Inference'),
         ('authorization_and_enforcement_ms', 'Authorization and enforcement')]
colors = ['#c9d6df', '#8fb3c4', '#e7c873', '#7a9e7e', None]
fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.4), sharey=True, gridspec_kw={'wspace': 0.08})
for ax, load_set, title in [(axes[0], {1, 2}, 'Medium and high load'), (axes[1], {0}, 'Low load')]:
    rows = []
    for mode, label in [('local', 'Local'), ('central', 'Controller')]:
        sel = [e for e in episodes if not e['outage'] and e['delay_ms'] == 50 and e['mode'] == mode
               and e['rate_level'] in load_set and ok(e)]
        rows.append((label, mode, len(sel), [statistics.median([e[k] or 0.0 for e in sel]) for k, _ in comps]))
    for y, (label, mode, n, meds) in enumerate(rows):
        left = 0
        for i, (value, color) in enumerate(zip(meds, colors)):
            ax.barh(y, value, left=left, color=color or (LOCAL if mode == 'local' else CTRL),
                    edgecolor='white', lw=0.5, height=0.55, label=comps[i][1] if y == 0 else None)
            left += value
        ax.text(left + 6, y, f'{left:.0f} ms (n={n})', va='center', fontsize=8.5)
    ax.set_yticks([0, 1], [r[0] for r in rows])
    ax.set_title(title)
    ax.set_xlabel('Median component time, ms')
    ax.set_xlim(0, max(sum(r[3]) for r in rows) * 1.45)
    ax.invert_yaxis()
handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in colors[:4]] + \
          [plt.Rectangle((0, 0), 1, 1, color=LOCAL), plt.Rectangle((0, 0), 1, 1, color=CTRL)]
labels = [c[1] for c in comps[:4]] + ['Auth. + enforcement (local)', 'Auth. + enforcement (controller)']
fig.legend(handles, labels, loc='lower center', ncol=3, frameon=False, bbox_to_anchor=(0.5, -0.2), fontsize=8)
fig.savefig(FIG / 'fig2_decomposition.png')
plt.close(fig)


# Figure 3: paired arrival-to-command and attack messages before command ----------------------
fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.9), gridspec_kw={'wspace': 0.32})
by = {(e['workload_id'], e['delay_ms'], e['mode']): e for e in episodes if not e['outage']}
for ax, key, ylabel in [(axes[0], 'attack_arrival_to_command_ms', 'Attack arrival to command, ms'),
                        (axes[1], 'attack_messages_received_before_command', 'Attack messages delivered\nbefore command')]:
    xt = []
    for gi, delay in enumerate([0, 50]):
        for wi in range(9):
            w = f'workload-0{wi}'
            loc, cen = by[(w, delay, 'local')], by[(w, delay, 'central')]
            if not (ok(loc) and ok(cen)):
                continue
            x0 = gi * 3
            jitter = (wi - 4) * 0.06
            ax.plot([x0 + jitter, x0 + 1 + jitter], [loc[key], cen[key]], color='#bbbbbb', lw=0.8, zorder=1)
            ax.scatter(x0 + jitter, loc[key], color=LOCAL, s=16, zorder=2)
            ax.scatter(x0 + 1 + jitter, cen[key], color=CTRL, s=16, zorder=2)
        xt += [(gi * 3, 'Local'), (gi * 3 + 1, 'Ctrl')]
    ax.set_xticks([x for x, _ in xt], [t for _, t in xt])
    for gi, delay in enumerate([0, 50]):
        ax.text(gi * 3 + 0.5, -0.2, f'{delay} ms one-way delay', transform=ax.get_xaxis_transform(),
                ha='center', fontsize=8.5)
    ax.set_ylabel(ylabel)
    ax.set_xlim(-0.6, 4.6)
    ax.set_ylim(bottom=0)
fig.savefig(FIG / 'fig3_paired.png')
plt.close(fig)


# Figure 4: service outcomes at 50 ms and under outage ----------------------------------------
fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.7), gridspec_kw={'wspace': 0.3})
groups = [(f'{LOADS[r]}', [e for e in episodes if not e['outage'] and e['delay_ms'] == 50 and e['rate_level'] == r])
          for r in range(3)] + [('Outage\n(medium)', [e for e in episodes if e['outage']])]
modes = [('none', 'No mitigation', NONE), ('local', 'Local', LOCAL), ('central', 'Controller', CTRL)]
for ax, key, ylabel, scale in [(axes[0], 'benign_delivery_ratio', 'Scheduled benign\nmessages delivered, %', 100),
                               (axes[1], 'delivered_attack_messages', 'Attack messages\ndelivered (mean)', 1)]:
    for gi, (gname, sel) in enumerate(groups):
        for mi, (mode, mlabel, color) in enumerate(modes):
            vals = [e[key] * scale for e in sel if e['mode'] == mode]
            if not vals:
                continue
            x = gi + (mi - 1) * 0.26
            ax.bar(x, statistics.mean(vals), width=0.24, color=color, label=mlabel if gi == 0 else None)
            ax.scatter([x] * len(vals), vals, s=7, color='black', zorder=3, lw=0)
    ax.set_xticks(range(len(groups)), [g for g, _ in groups])
    ax.set_ylabel(ylabel)
axes[0].set_ylim(80, 101)
fig.legend(*axes[0].get_legend_handles_labels(), loc='upper center', ncol=3, frameon=False,
           bbox_to_anchor=(0.5, 1.07), fontsize=8.5)
fig.savefig(FIG / 'fig4_service.png')
plt.close(fig)
print('figures written to', FIG)
