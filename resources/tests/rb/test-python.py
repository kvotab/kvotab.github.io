#!/usr/bin/env python3
"""The chart's Python button (rb-chart-python.js): a matplotlib script that
draws the chart on the screen from the HDF5 files it is drawn from.

Each case draws a chart in the page, takes its script, and runs it in real
Python (h5py, numpy, matplotlib) in a folder holding the files the chart
reads, with matplotlib's drawing calls recorded instead of shown. What the
script drew is then compared with what the page drew:

  * every line, in the page's order: its numbers, point for point (to
    1e-9), its name, colour, width and dash, and whether and where the
    legend lists it;
  * every CI and SEM band's edges, and the SEM band's hatching;
  * each panel's axes, lin or log over the range on screen, their titles,
    which axes show labels, and on a log axis the labels themselves (a
    decade each, written as Plotly writes them: 10k, 10⁻⁵);
  * the background's phases, and the panels' labels;
  * that no line went into the script as its numbers: each is computed
    from the file, as the page computed it.

The data: a file built in the page with h5wasm, so nothing binary is
committed. It has what the chart builders tell apart: realisations (a
probabilistic dataset, with n_iter for the SEM), a table of statistics
(mean, 5 %, 95 %, sigma), mean and sigma attributes, values that do not vary
over time (one value, and one per realisation), radionuclide groups (a
probabilistic member among deterministic ones, for Show Total's bands), a
background overlay, and a second file for two-file charts; and a file with a
probabilistic /time, a time axis per realisation. Last, a file whose names
are made to break out of a string literal: its script must parse to nothing
but the script (no INJECTED name anywhere in its syntax tree), and run.

Then the dialog: the button, the code shown in colour as text (no markup
from the file), Copy and Download.

Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-python.py

Needs h5py, numpy and matplotlib in the Python that runs it. Exit status is
0 when every check passes.
"""
import ast
import asyncio
import base64
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import tokenize
import urllib.request

import websockets

from driver import open_page

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'), flush=True)
    if not ok:
        failures.append(label)


# time: 0, then 10 .. 1e5 log-spaced (29 steps). n_iter 20. The prob file's
# realisations have a NaN in one, which the statistics leave out.
BUILD = r"""(async () => {
  await waitForH5Wasm();
  const { FS, File } = window.h5wasm;
  const n = 30, R = 20;
  const t = Float64Array.from({ length: n }, (_, i) => i === 0 ? 0 : Math.pow(10, 1 + 4 * (i - 1) / (n - 2)));
  // A fixed spread of realisation factors (no randomness: the test is repeatable).
  const factor = (r) => Math.exp(0.6 * Math.sin(1.7 * r + 0.3));
  const make = (name, build) => {
    const path = '/py-test-' + Math.random().toString(36).slice(2) + '.h5';
    const w = new File(path, 'w');
    try { build(w); } finally { w.close(); }
    loadedFileBuffers[name] = FS.readFile(path).slice().buffer;
    loadedFiles[name] = new File(path, 'r');
    fileStates[name] = true;
    if (!fileOrder.includes(name)) fileOrder.push(name);
  };
  const put = (g, name, data, shape, attrs = {}) => {
    const d = g.create_dataset({ name, data: Float64Array.from(data), shape, dtype: '<f8' });
    for (const [k, v] of Object.entries(attrs)) d.create_attribute(k, v);
    return d;
  };
  const series = (i, scale) => scale * (t[i] + 1) / 1e4;
  const results = (w, scale) => {
    w.create_attribute('n_iter', R);
    put(w, 'time', t, [n], { unit: 'years' });
    const prob = w.create_group('prob');
    // Realisations, flat[t * R + r]; realisation 7 has a NaN at time 12.
    const real = [];
    for (let i = 0; i < n; i++) for (let r = 0; r < R; r++) real.push(i === 12 && r === 7 ? NaN : series(i, scale) * factor(r));
    put(prob, 'conc', real, [n, R], { unit: 'mol/m3', time_dependent: 'TRUE', probabilistic: 'TRUE' });
    // A table of statistics, a row a time: mean, 5 %, 95 %, sigma.
    const table = [];
    for (let i = 0; i < n; i++) {
      const m = series(i, scale);
      table.push(m, 0.5 * m, 1.8 * m, 0.3 * m);
    }
    put(prob, 'stats', table, [n, 4], { unit: 'mol/m3', time_dependent: 'TRUE', columns: 'mean, 5%, 95%, sigma' });
    // Mean and sigma as attributes (the values themselves are not drawn).
    const d = put(prob, 'moments', Array.from(t, (_, i) => 99), [n], { unit: 'mol/m3', time_dependent: 'TRUE' });
    d.create_attribute('mean', Float64Array.from(t, (_, i) => series(i, scale) * 1.1));
    d.create_attribute('sigma', Float64Array.from(t, (_, i) => series(i, scale) * 0.2));
    // Values that do not vary over time: one, and one per realisation.
    const c = w.create_group('const');
    put(c, 'limit', [2.5 * scale], [1], { unit: 'mol/m3' });
    put(c, 'spread', Array.from({ length: R }, (_, r) => scale * factor(r)), [R], { unit: 'mol/m3', probabilistic: 'TRUE' });
    // A radionuclide group: a probabilistic member between two that are not.
    const g = w.create_group('nuc');
    g.create_attribute('IndexLists', ['Radionuclides']);
    g.create_attribute('time_dependent', 'TRUE');
    g.create_attribute('unit', 'Bq');
    put(g, 'I-129', Array.from(t, (_, i) => series(i, 30 * scale)), [n], { unit: 'Bq', time_dependent: 'TRUE' });
    const cs = [];
    for (let i = 0; i < n; i++) for (let r = 0; r < R; r++) cs.push(series(i, 100 * scale) * factor(r + 3));
    put(g, 'Cs-137', cs, [n, R], { unit: 'Bq', time_dependent: 'TRUE', probabilistic: 'TRUE' });
    put(g, 'Sr-90', Array.from(t, (_, i) => series(i, 10 * scale) * (i === 5 ? NaN : 1)), [n], { unit: 'Bq', time_dependent: 'TRUE' });
    // A second group, in another unit, for panels.
    const h = w.create_group('dose');
    h.create_attribute('IndexLists', ['Radionuclides']);
    h.create_attribute('time_dependent', 'TRUE');
    h.create_attribute('unit', 'Sv/year');
    put(h, 'Cs-137', Array.from(t, (_, i) => series(i, 1e-6 * scale)), [n], { unit: 'Sv/year', time_dependent: 'TRUE' });
    put(h, 'I-129', Array.from(t, (_, i) => series(i, 3e-7 * scale)), [n], { unit: 'Sv/year', time_dependent: 'TRUE' });
    // A background overlay: the phases a data-time index gives.
    w.create_group('geo');
    const geo = w.get('geo');
    put(geo, 'flux', Array.from(t, (_, i) => Math.sin(i / 5) + 2), [n], { unit: 'Bq/year', time_dependent: 'True' });
    geo.create_dataset({ name: '_phase', data: Float64Array.from([1000, 10000, 100000]), shape: [3], dtype: '<f8' })
      .create_attribute('Index', '["Submerged","Shore","Terrestrial"]');
  };
  make('results.h5', (w) => results(w, 1));
  make('results_b.h5', (w) => results(w, 0.5));
  // A probabilistic /time: a time axis per realisation, shape (steps, padded realisations).
  make('probtime.h5', (w) => {
    const steps = 12, pad = 4, n_times = [12, 9, 10];
    const time = [], flow = [];
    for (let i = 0; i < steps; i++) for (let k = 0; k < pad; k++) {
      time.push(k < 3 && i < n_times[k] ? (i + 1) * 10 * (k + 1) : 0);
      flow.push(k < 3 && i < n_times[k] ? Math.sqrt(i + 1) * (k + 2) : 0);
    }
    const td = put(w, 'time', time, [steps, pad], { unit: 'years', probabilistic: 'TRUE' });
    td.create_attribute('n_times', Int32Array.from(n_times));
    put(w, 'flow', flow, [steps, pad], { unit: 'm3/year', time_dependent: 'TRUE' });
  });
  await updateTabs(true);
  return fileOrder.slice();
})()"""

# The file made to break out: its name, a group's, members' and a unit, each a way out of a literal or a comment.
HOSTILE_NAME = 'evil"\'\\ $x$ #{}.h5'
HOSTILE = r"""(async (name) => {
  await waitForH5Wasm();
  const { FS, File } = window.h5wasm;
  const n = 12;
  const t = Float64Array.from({ length: n }, (_, i) => (i + 1) * 100);
  const path = '/py-evil-' + Math.random().toString(36).slice(2) + '.h5';
  const w = new File(path, 'w');
  try {
    w.create_dataset({ name: 'time', data: t, shape: [n], dtype: '<f8' }).create_attribute('unit', 'y"); INJECTED_UNIT = ("');
    const g = w.create_group('g"\n\rINJECTED_GROUP = 1 #');
    g.create_attribute('IndexLists', ['Radionuclides']);
    g.create_attribute('time_dependent', 'TRUE');
    g.create_attribute('unit', 'Bq INJECTED_SEP = 1');
    const names = [
      'a"); INJECTED_QUOTE = ("',
      "b" + "'".repeat(3) + "\nINJECTED_TRIPLE = 1\n" + "'".repeat(3),
      'c' + '"'.repeat(3) + '\nINJECTED_DOC = 1\n' + '"'.repeat(3),
      'd\\',
      'e\r\nINJECTED_CRLF = 1 #',
      'f $\\alpha$ {0} %s',
      'g‮INJECTED_BIDI = 1',
      'h<img src="data:," onerror="window.__pyxss = 1">'
    ];
    names.forEach((m, k) => g.create_dataset({ name: m, data: Float64Array.from(t, v => (k + 1) * v), shape: [n], dtype: '<f8' })
      .create_attribute('time_dependent', 'TRUE'));
  } finally {
    w.close();
  }
  loadedFileBuffers[name] = FS.readFile(path).slice().buffer;
  loadedFiles[name] = new File(path, 'r');
  fileStates[name] = true;
  if (!fileOrder.includes(name)) fileOrder.push(name);
  await updateTabs(true);
  return 'done';
})"""

HELPERS = r"""(() => {
  window.__wait = (ms) => new Promise(r => setTimeout(r, ms));
  // Only these files enabled, each drawn from the tree as a user picks it.
  window.__only = async (...names) => {
    for (const n of fileOrder) fileStates[n] = names.includes(n);
    await updateTabs(true);
    await __wait(1200);
  };
  window.__pick = async (file, path, { group = false, ctrl = false } = {}) => {
    await expandAndLoadPath(file, path);
    const row = findTreeItem(path, { extra: group ? '.group' : '.dataset' });
    if (!row) throw new Error('no row for ' + path);
    row.dispatchEvent(new MouseEvent('click', { bubbles: true, ctrlKey: ctrl, metaKey: ctrl }));
    await __wait(2500);
  };
  window.__scale = async (axis, value) => {
    const b = document.querySelector(`#${axis}ScaleToggle button[data-value=${value}]`);
    if (!b.classList.contains('active')) b.click();
    await __wait(1200);
  };
  window.__tick = async (id, on) => {
    const cb = document.getElementById(id);
    if (!!cb.checked !== on) { cb.checked = on; cb.dispatchEvent(new Event('change', { bubbles: true })); }
    await __wait(1500);
  };
  window.__iter = async (value) => {
    const el = document.getElementById('showIterNum');
    el.value = value === null ? '' : String(value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    await __wait(1500);
  };
  window.__bytes = (name) => {
    const b = new Uint8Array(loadedFileBuffers[name]);
    let s = '';
    for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode.apply(null, b.subarray(i, i + 32768));
    return btoa(s);
  };
  // What the page drew: each visible trace in order, the legend, the panels' axes and the phases.
  window.__drawn = () => {
    const gd = document.getElementById('plotlyChart');
    const fl = gd._fullLayout;
    const num = (v) => (v === null || v === undefined || !isFinite(Number(v)) ? null : Number(v));
    const keys = [];
    const traces = [];
    for (const ft of gd._fullData) {
      if (ft.visible !== true) continue;
      const ut = gd.data[ft.index] || {};
      const key = `${ft.xaxis || 'x'}|${ft.yaxis || 'y'}`;
      if (!keys.includes(key) && !ut._isCIBand && !ut._isSDOMBand) keys.push(key);
      traces.push({
        index: ft.index, key,
        kind: ut._isSDOMHatch ? 'hatch' : ut._isCIBand ? 'ci' : ut._isSDOMBand ? 'sem' : 'line',
        x: Array.from(ut.x || [], num), y: Array.from(ut.y || [], num),
        name: xlPlainText(ft.name),
        line: { colour: xlColor(ft.line && ft.line.color), alpha: xlColor(ft.line && ft.line.color).alpha,
                width: Number(ft.line && ft.line.width) || 2, dash: (ft.line && ft.line.dash) || 'solid' },
        fill: xlColor(ft.fillcolor),
        legend: ft.showlegend !== false && !ut._hiddenFromLegend, rank: isFinite(ft.legendrank) ? ft.legendrank : 1000,
        recipe: !!ut._py });
    }
    const legend = traces.filter(t => t.kind === 'line' && t.legend).sort((a, b) => (a.rank - b.rank) || (a.index - b.index)).map(t => t.name);
    const axes = keys.map((key) => {
      const [xr, yr] = key.split('|');
      const ax = (a) => ({ type: a.type, range: a.range.map(Number), title: xlPlainText(a.title && a.title.text),
        labels: a.showticklabels !== false, ticks: (a._vals || []).filter(v => !v.minor).map(v => ({ x: Number(v.x), text: v.text })) });
      return { key, x: ax(fl[xlAxisKey(xr, 'x')]), y: ax(fl[xlAxisKey(yr, 'y')]), top: fl[xlAxisKey(yr, 'y')].domain[1] };
    }).sort((a, b) => b.top - a.top);
    const phases = (fl.shapes || []).filter(s => s.name === BACKGROUND_SHAPE_NAME)
      .map(s => ({ x0: Number(s.x0), x1: Number(s.x1), colour: xlColor(s.fillcolor) }));
    const labels = axes.length > 1 ? (fl.annotations || []).map(a => xlPlainText(a.text)) : [];
    return { traces, legend, axes, phases, labels };
  };
  window.__script = () => {
    const s = pyChartScript(document.getElementById('plotlyChart'));
    return s ? { code: s.code, name: s.fileName, files: s.files, literal: s.literal } : null;
  };
  return true;
})()"""

# Runs a script with matplotlib's drawing calls recorded, and writes what it drew as JSON.
RECORDER = r'''
import json, math, runpy, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes

script, out_path = sys.argv[1], sys.argv[2]
calls = []


def recorded(name):
    real = getattr(Axes, name)

    def call(self, *args, **kwargs):
        result = real(self, *args, **kwargs)
        calls.append((name, self, args, kwargs, result))
        return result
    return call


for name in ("plot", "fill_between", "vlines", "axvspan", "text", "legend"):
    setattr(Axes, name, recorded(name))


def nums(v):
    return [float(x) if math.isfinite(x) else None for x in np.asarray(v, dtype=float).ravel()]


def colour(c):
    h = matplotlib.colors.to_hex(c, keep_alpha=True).upper()
    return h[:7] if h.endswith("FF") else h


def show(*_args, **_kwargs):
    fig = plt.gcf()
    fig.canvas.draw()
    index = {id(a): i for i, a in enumerate(fig.axes)}
    lines = []
    out = {"lines": [], "bands": [], "hatches": [], "spans": [], "texts": [], "legend": [], "axes": []}
    for name, ax, args, kwargs, result in calls:
        i = index.get(id(ax))
        if name == "plot":
            line = result[0]
            lines.append(line)
            out["lines"].append({"ax": i, "x": nums(line.get_xdata()), "y": nums(line.get_ydata()),
                                 "label": line.get_label(), "colour": colour(kwargs.get("color")),
                                 "width": kwargs.get("linewidth"), "linestyle": repr(kwargs.get("linestyle"))})
        elif name == "fill_between":
            out["bands"].append({"ax": i, "x": nums(args[0]), "lower": nums(args[1]), "upper": nums(args[2]),
                                 "colour": colour(kwargs.get("color"))})
        elif name == "vlines":
            out["hatches"].append({"ax": i, "x": nums(args[0]), "lower": nums(args[1]), "upper": nums(args[2]),
                                   "colour": colour(kwargs.get("colors"))})
        elif name == "axvspan":
            out["spans"].append({"ax": i, "x0": float(args[0]), "x1": float(args[1]), "colour": colour(kwargs.get("color"))})
        elif name == "text":
            out["texts"].append({"ax": i, "text": result.get_text()})
        elif name == "legend":
            handles = args[0]
            out["legend"] = [{"line": next((k for k, l in enumerate(lines) if l is h), None), "label": lab}
                             for h, lab in zip(handles, args[1])]
    for ax in fig.axes:
        def side(which):
            axis = ax.xaxis if which == "x" else ax.yaxis
            lo, hi = sorted(axis.get_view_interval())
            inside = lambda v: lo - 1e-9 * abs(lo) <= v <= hi + 1e-9 * abs(hi)
            # The labels drawn: a major tick's, inside the axis's range.
            labels = [t.label1.get_text() for v, t in zip(axis.get_majorticklocs(), axis.get_major_ticks())
                      if inside(v) and t.label1.get_visible() and t.label1.get_text()]
            return {"scale": getattr(ax, "get_%sscale" % which)(), "limits": list(getattr(ax, "get_%slim" % which)()),
                    "title": getattr(ax, "get_%slabel" % which)(), "labels": labels}
        box = ax.get_position()
        out["axes"].append({"x": side("x"), "y": side("y"), "top": box.y1})
    out["size"] = [float(v) for v in fig.get_size_inches() * 100]
    json.dump(out, open(out_path, "w"))


plt.show = show
runpy.run_path(script, run_name="__main__")
'''


def close(a, b, tol=1e-9):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol * max(abs(a), abs(b)) + 1e-300


def same(xs, ys, tol=1e-9):
    return len(xs) == len(ys) and all(close(a, b, tol) for a, b in zip(xs, ys))


def first_difference(xs, ys):
    if len(xs) != len(ys):
        return f'{len(xs)} values, not {len(ys)}'
    for i, (a, b) in enumerate(zip(xs, ys)):
        if not close(a, b):
            return f'[{i}] {a!r} != {b!r}'
    return None


def hexa(c):
    return '#' + c['hex'] + ('' if c['alpha'] >= 1 else format(round(c['alpha'] * 255), '02X'))


def plotly_tick(text):
    """Plotly's tick label as plain text: 10<sup>−5</sup> -> 10^−5."""
    return str(text).replace('<sup>', '^').replace('</sup>', '').replace('−', '-')


def mpl_tick(text):
    """matplotlib's, the same way: $10^{-5}$ -> 10^-5, $0.2{\\times}10^{-5}$ -> 0.2×10^-5."""
    t = text.replace('$', '').replace('{\\times}', '×').replace('\\times', '×').replace('\\mathdefault', '')
    return t.replace('{', '').replace('}', '').replace('−', '-')


def run_script(code, files, bytes_of, work):
    """Write the script and its files into a folder of their own, run it, and return what it drew."""
    folder = tempfile.mkdtemp(dir=work)
    for name in files:
        with open(os.path.join(folder, name), 'wb') as fh:
            fh.write(bytes_of[name])
    script = os.path.join(folder, 'chart.py')
    with open(script, 'w', encoding='utf-8') as fh:
        fh.write(code)
    recorder = os.path.join(work, 'record.py')
    out = os.path.join(folder, 'drawn.json')
    r = subprocess.run([sys.executable, recorder, script, out], capture_output=True, text=True, cwd=work, timeout=300)
    drawn = json.load(open(out)) if r.returncode == 0 and os.path.exists(out) else None
    return r, drawn


def compare(label, page, drawn, script):
    """What the script drew against what the page drew; see the top of this file."""
    lines = [t for t in page['traces'] if t['kind'] == 'line']
    bands = [t for t in page['traces'] if t['kind'] in ('ci', 'sem')]
    hatches = [t for t in page['traces'] if t['kind'] == 'hatch']
    check(f'{label}: every line computed from the file (none as its numbers)', script['literal'], 0)
    check(f'{label}: as many lines, bands and hatchings as the page',
          (len(drawn['lines']), len(drawn['bands']), len(drawn['hatches'])), (len(lines), len(bands), len(hatches)))
    panel_of = {a['key']: i for i, a in enumerate(page['axes'])}
    bad = []
    for p, m in zip(lines, drawn['lines']):
        for what, a, b in (('x', m['x'], p['x']), ('y', m['y'], p['y'])):
            d = first_difference(a, b)
            if d:
                bad.append(f"{p['name']} {what}: {d}")
        # As matplotlib shows it: the script writes a $ as \$, so that it is not mathtext.
        if m['label'].replace('\\$', '$') != p['name']:
            bad.append(f"label {m['label']!r} != {p['name']!r}")
        if m['colour'] != hexa(p['line']['colour']):
            bad.append(f"{p['name']} colour {m['colour']} != {hexa(p['line']['colour'])}")
        if not close(m['width'], p['line']['width'] * 0.75):
            bad.append(f"{p['name']} width {m['width']} != {p['line']['width'] * 0.75}")
        if (m['linestyle'] == "'-'") != (p['line']['dash'] == 'solid'):
            bad.append(f"{p['name']} dash {m['linestyle']} for {p['line']['dash']}")
        if m['ax'] != panel_of.get(p['key'], 0):
            bad.append(f"{p['name']} in panel {m['ax']}, not {panel_of.get(p['key'], 0)}")
    check(f'{label}: each line the page\'s, point for point, in its name, colour, width, dash and panel', bad[:4], [])
    bad = []
    for p, m in zip(bands, drawn['bands']):
        half = len(p['x']) // 2
        upper, lower = p['y'][:half], p['y'][half:][::-1]
        k = len(m['x'])
        for what, a, b in (('x', m['x'], p['x'][:half]), ('upper', m['upper'][:k], upper), ('lower', m['lower'][:k], lower)):
            d = first_difference(a, b)
            if d:
                bad.append(f"{p['kind']} band {what}: {d}")
        if m['colour'] != hexa(p['fill']):
            bad.append(f"{p['kind']} band colour {m['colour']} != {hexa(p['fill'])}")
    check(f'{label}: each band\'s edges the page\'s', bad[:4], [])
    if hatches:
        bad = []
        for p, m in zip(hatches, drawn['hatches']):
            xs = [v for v in p['x'][0::3]]
            ups, lows = p['y'][0::3], p['y'][1::3]
            for what, a, b in (('x', m['x'], xs), ('upper', m['upper'], ups), ('lower', m['lower'], lows)):
                d = first_difference(a, b)
                if d:
                    bad.append(f"hatch {what}: {d}")
        check(f'{label}: the SEM band\'s hatching the page\'s', bad[:3], [])
    check(f'{label}: the legend lists the page\'s lines, in the page\'s order',
          [e['label'].replace('\\$', '$') for e in drawn['legend']], page['legend'])
    bad = []
    for i, (pa, ma) in enumerate(zip(page['axes'], drawn['axes'])):
        for which in ('x', 'y'):
            p, m = pa[which], ma[which]
            log = p['type'] == 'log'
            lim = [10 ** v for v in p['range']] if log else p['range']
            if m['scale'] != ('log' if log else 'linear'):
                bad.append(f'{i}{which} scale {m["scale"]}')
            if not same(m['limits'], lim, 1e-9):
                bad.append(f'{i}{which} limits {m["limits"]} != {lim}')
            if m['title'] != p['title']:
                bad.append(f'{i}{which} title {m["title"]!r} != {p["title"]!r}')
            if bool(m['labels']) != p['labels']:
                bad.append(f'{i}{which} labels shown {bool(m["labels"])} != {p["labels"]}')
            if log and p['labels']:
                want = [plotly_tick(t['text']) for t in p['ticks'] if min(lim) <= 10 ** t['x'] * (1 + 1e-9) and 10 ** t['x'] <= max(lim) * (1 + 1e-9)]
                got = [mpl_tick(t) for t in m['labels']]
                if got != want:
                    bad.append(f'{i}{which} labels {got} != {want}')
    check(f'{label}: the axes the page\'s: scale, range, title, labels', (len(drawn['axes']), bad[:4]), (len(page['axes']), []))
    if page['phases']:
        spans = [s for s in drawn['spans'] if s['ax'] == 0]
        check(f'{label}: the background\'s phases the page\'s',
              [(round(s['x0'], 6), round(s['x1'], 6), s['colour']) for s in spans],
              [(round(p['x0'], 6), round(p['x1'], 6), hexa(p['colour'])) for p in page['phases']])
    if page['labels']:
        check(f'{label}: each panel labelled as on the page', [t['text'] for t in drawn['texts']], page['labels'])


async def case(page, label, setup, bytes_of, work, expect=None):
    """Draw a chart, take its script, run it, compare."""
    ready = await page.ev(setup, timeout=180)
    if isinstance(ready, str) and ready.startswith('EXCEPTION'):
        check(f'{label}: the chart is drawn', ready[:300], None)
        return None, None
    drawn_page = await page.ev('__drawn()')
    script = await page.ev('__script()')
    if not isinstance(script, dict):
        check(f'{label}: a script', script, 'a script')
        return None, None
    try:
        ast.parse(script['code'])
        parses = True
    except SyntaxError as e:
        parses = f'{e.msg} at line {e.lineno}'
    check(f'{label}: the script is Python', parses)
    r, drawn = run_script(script['code'], script['files'], bytes_of, work)
    check(f'{label}: and runs', (r.returncode, r.stderr.strip().splitlines()[-3:]), (0, []))
    if drawn:
        compare(label, drawn_page, drawn, script)
        if expect:
            expect(drawn_page, drawn, script)
    return script, drawn


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    work = tempfile.mkdtemp(prefix='rb-python-')
    with open(os.path.join(work, 'record.py'), 'w') as fh:
        fh.write(RECORDER)
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=256 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=6)
        try:
            await page.ev(BUILD, timeout=120)
            await page.ev(HELPERS)
            bytes_of = {name: base64.b64decode(await page.ev(f'__bytes({json.dumps(name)})'))
                        for name in ('results.h5', 'results_b.h5', 'probtime.h5')}

            # --- one dataset -------------------------------------------------
            await case(page, 'values, lin', """(async () => { await __only('results.h5'); await __scale('x', 'linear'); await __scale('y', 'linear');
                await __pick('results.h5', '/geo/flux'); })()""", bytes_of, work)
            await case(page, 'values, log, a background', """(async () => { await __scale('x', 'log'); await __scale('y', 'log');
                const s = document.getElementById('backgroundSourceSelect'); s.value = '/geo/_phase'; s.dispatchEvent(new Event('change', { bubbles: true })); await __wait(2000); })()""",
                bytes_of, work)
            await page.ev("(async () => { const s = document.getElementById('backgroundSourceSelect'); s.value = '__none__'; s.dispatchEvent(new Event('change', { bubbles: true })); await __wait(1500); })()")
            await case(page, 'realisations: the mean, CI, SEM and one realisation', """(async () => {
                await __pick('results.h5', '/prob/conc'); await __tick('showCI', true); await __tick('showSDOM', true); await __iter(3); })()""",
                bytes_of, work)
            await case(page, 'a table of statistics: its mean, CI and SEM columns', """(async () => {
                await __iter(null); await __pick('results.h5', '/prob/stats'); })()""", bytes_of, work)
            await case(page, 'mean and sigma attributes: the mean, and the SEM band', """(async () => {
                await __pick('results.h5', '/prob/moments'); })()""", bytes_of, work)
            await case(page, 'Show Max: the names with their maxima', """(async () => {
                await __tick('showCI', false); await __tick('showSDOM', false); await __tick('showMax', true); await __pick('results.h5', '/prob/conc'); })()""",
                bytes_of, work)
            await page.ev("__tick('showMax', false)")

            # --- several datasets, and values that do not vary -------------------------
            await case(page, 'several datasets with two constants, their CI, SEM and a realisation', """(async () => {
                await __pick('results.h5', '/prob/conc'); await __pick('results.h5', '/const/limit', { ctrl: true });
                await __pick('results.h5', '/const/spread', { ctrl: true }); await __pick('results.h5', '/geo/flux', { ctrl: true });
                await __tick('showCI', true); await __tick('showSDOM', true); await __iter(2); })()""", bytes_of, work)
            await page.ev("(async () => { await __iter(null); await __tick('showCI', false); await __tick('showSDOM', false); await __pick('results.h5', '/geo/flux'); })()")

            # --- radionuclide groups ------------------------------------------
            await case(page, 'a group with Show Total, its CI and SEM', """(async () => {
                await __pick('results.h5', '/nuc', { group: true }); await __tick('showTotal', true); await __tick('showCI', true); await __tick('showSDOM', true); })()""",
                bytes_of, work)
            await case(page, 'a group, a realisation and Show Max', """(async () => {
                await __tick('showCI', false); await __tick('showSDOM', false); await __tick('showMax', true); await __iter(4); })()""",
                bytes_of, work)
            await page.ev("(async () => { await __iter(null); await __tick('showMax', false); })()")
            await case(page, 'two files: thin lines, and Show Ratio', """(async () => {
                await __only('results.h5', 'results_b.h5');
                document.querySelector('#treeModeContainer button[data-value="intersect"]').click(); await __wait(2500);
                await __pick('results.h5', '/nuc', { group: true }); await __tick('showRatio', true); })()""", bytes_of, work)
            await page.ev("(async () => { await __tick('showRatio', false); document.querySelector('#treeModeContainer button[data-value=\"separated\"]').click(); await __wait(2500); await __only('results.h5'); })()")
            await case(page, 'two groups a panel each, in their own units', """(async () => {
                await __pick('results.h5', '/nuc', { group: true }); await __pick('results.h5', '/dose', { group: true, ctrl: true }); })()""",
                bytes_of, work, expect=lambda p, d, s: check('  two panels, the lower one labelled', len(d['axes']), 2))
            await case(page, 'two groups in the same chart', """(async () => { await __tick('overlayGroups', true); })()""", bytes_of, work)
            await case(page, 'zoomed: the range on screen, not all of the data', """(async () => {
                await __tick('overlayGroups', false); await __pick('results.h5', '/nuc', { group: true });
                await Plotly.relayout(document.getElementById('plotlyChart'), { 'xaxis.range': [2, 4], 'yaxis.range': [-3, 1] }); await __wait(1000); })()""",
                bytes_of, work)

            # --- a probabilistic /time -----------------------------------------------
            await case(page, 'a probabilistic /time: realisation 1', """(async () => {
                await __only('probtime.h5'); await __scale('y', 'linear'); await __pick('probtime.h5', '/flow'); })()""", bytes_of, work)
            await case(page, 'a probabilistic /time: realisation 2, as Show iteration redraws it', """(async () => { await __iter(2); })()""", bytes_of, work)
            await page.ev('__iter(null)')

            # --- a file made to break out ---------------------------------------------
            await page.ev(f'({HOSTILE})({json.dumps(HOSTILE_NAME)})', timeout=120)
            bytes_of[HOSTILE_NAME] = base64.b64decode(await page.ev(f'__bytes({json.dumps(HOSTILE_NAME)})'))
            group = await page.ev("Array.from(loadedFiles[%s].keys()).find(k => k.startsWith('g'))" % json.dumps(HOSTILE_NAME))
            await page.ev('window.__pyxss = 0')
            script, drawn = await case(page, 'names made to break out', f"""(async () => {{ await __only({json.dumps(HOSTILE_NAME)}); await __scale('y', 'log');
                await __pick({json.dumps(HOSTILE_NAME)}, {json.dumps('/' + group)}, {{ group: true }}); }})()""", bytes_of, work)
            if script:
                tree = ast.parse(script['code'])
                names = sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and 'INJECTED' in n.id}
                               | {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name) and 'INJECTED' in t.id})
                check('  nothing of the names is code: no INJECTED name in the syntax tree', names, [])
                strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
                check('  the file\'s name is a string in it, as it is', HOSTILE_NAME in strings, True)
                check('  a bidirectional override is written escaped, not as itself', '‮' in script['code'], False)
                comments = [tok.string for tok in tokenize.generate_tokens(io.StringIO(script['code']).readline)
                            if tok.type == tokenize.COMMENT]
                check('  no comment holds a word of the names', [c for c in comments if 'INJECTED' in c or 'evil' in c], [])
            check('  and nothing the names hold ran in the page', await page.ev('window.__pyxss'), 0)

            # --- the dialog -------------------------------------------------------
            await page.ev(f"(async () => {{ await __only('results.h5'); await __pick('results.h5', '/prob/conc'); await __tick('showCI', true); }})()", timeout=120)
            ui = await page.ev(r"""(async () => {
              const button = document.querySelector('[data-on-click="openPythonDialog"]');
              const shown = button && getComputedStyle(button).display !== 'none';
              window.__copied = null;
              navigator.clipboard.writeText = async (t) => { window.__copied = t; };
              button.click();
              await __wait(400);
              const dialog = document.getElementById('pythonDialog');
              const openNow = !!dialog && getComputedStyle(dialog).display !== 'none';
              const code = document.getElementById('pythonCode');
              const text = [...code.querySelectorAll('.ln')].map(l => l.textContent).join('\n');
              const expected = pyChartScript(document.getElementById('plotlyChart')).code;
              const spans = code.querySelectorAll('span[class^="t-"]');
              const kinds = [...new Set([...spans].map(s => s.className))].sort();
              document.getElementById('pythonCopy').click();
              await __wait(200);
              let saved = null;
              const realClick = HTMLAnchorElement.prototype.click;
              HTMLAnchorElement.prototype.click = function () { saved = { name: this.getAttribute('download'), href: this.href }; };
              document.getElementById('pythonDownload').click();
              HTMLAnchorElement.prototype.click = realClick;
              let body = null;
              if (saved && saved.href.startsWith('blob:')) body = await (await fetch(saved.href)).text();
              document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
              await __wait(200);
              return { shown, open: openNow, same: text === expected, kinds,
                       copied: window.__copied === expected, file: saved && saved.name, body: body === expected,
                       closed: getComputedStyle(dialog).display === 'none', lines: code.querySelectorAll('.ln').length,
                       codeLines: expected.split('\n').length };
            })()""", timeout=60)
            check('the chart has a Python button', ui.get('shown'), True)
            check('  which opens a dialog showing the script, as text', (ui.get('open'), ui.get('same')), (True, True))
            check('  in colour: built-ins, comments, decorators, functions, keywords, numbers and strings',
                  ui.get('kinds'), ['t-b', 't-c', 't-d', 't-f', 't-k', 't-n', 't-s'])
            check('  a line a line of the script', ui.get('lines'), ui.get('codeLines'))
            check('  Copy puts the script on the clipboard', ui.get('copied'), True)
            check('  Download saves it as a .py named after the chart', (ui.get('file'), ui.get('body')), ('prob_conc_results.py', True))
            check('  Escape closes the dialog', ui.get('closed'), True)
            check('no console errors throughout', page.logs[:3], [])
        finally:
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))
            await bws.recv()
    if os.environ.get('RB_KEEP'):
        print(f'kept {work}')
    else:
        shutil.rmtree(work, ignore_errors=True)

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
