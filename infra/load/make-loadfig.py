#!/usr/bin/env python3
"""Plots the load-study figure used in the report from the raw driver output (no hard-coded numbers).

Panel (a) splits the request rate into successful (2xx) and failed requests; panel (b) shows p50 and p95 latency over all responses with the 10 s client
timeout marked (it caps the p95 at 200 VUs). Sized for 1:1 inclusion at the text width (6.7 in), so the 8 pt labels stay 8 pt in the PDF.
Usage: python3 infra/load/make-loadfig.py infra/load/results/load-2026-10-16.json docs/images/fig-load.png
Needs matplotlib.
"""
import json, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

data = json.load(open(sys.argv[1]))
stages = [s for s in data['stages'] if s['requests'] > 0]
labels = ['%d VUs\n%d s' % (s['vus'], s['duration_s']) for s in stages]
good = [s['ok_2xx'] / s['duration_s'] for s in stages]
total = [s['requests'] / s['duration_s'] for s in stages]
bad = [t - g for t, g in zip(total, good)]
pct = [100.0 * s['ok_2xx'] / s['requests'] for s in stages]
plt.rcParams.update({'font.family': 'serif', 'font.size': 8})
fig, (a, b) = plt.subplots(1, 2, figsize=(6.7, 2.5))
x = range(len(stages))
a.bar(x, good, color='#6b9ac4', label='2xx')
a.bar(x, bad, bottom=good, color='#d98c7a', label='errors (502, timeouts)')
for i, (g, t, p) in enumerate(zip(good, total, pct)):
    a.text(i, t + 3, '%.1f%% 2xx' % (p + 1e-9), ha='center', fontsize=8)
a.set_xticks(list(x)); a.set_xticklabels(labels); a.set_ylabel('requests/s'); a.set_ylim(0, max(total) * 1.18)
a.set_title('(a) Request rate by outcome'); a.legend(fontsize=7, loc='upper left', frameon=False)
w = 0.38
b.bar([i - w / 2 for i in x], [s['p50_ms'] for s in stages], w, color='#7fb069', label='p50')
b.bar([i + w / 2 for i in x], [s['p95_ms'] for s in stages], w, color='#e07a5f', label='p95')
b.axhline(10000, color='k', ls='--', lw=0.7); b.text(-0.45, 12500, '10 s client timeout', fontsize=7)
b.set_yscale('log'); b.set_ylim(50, 250000); b.set_xticks(list(x)); b.set_xticklabels(labels); b.set_ylabel('latency (ms, log scale)')
b.set_title('(b) Latency, all responses'); b.legend(fontsize=7, loc='upper right', ncol=2, frameon=False)
fig.tight_layout(pad=0.5); fig.savefig(sys.argv[2], dpi=300, bbox_inches='tight'); print('wrote', sys.argv[2])
