/* ==========================================================================
   distributions.html: THE STATISTICS TABLE

   Every distribution side by side, a column each, a statistic a row: what
   it is, where it lies, how spread and how shaped it is, the percentiles
   asked for, and, for a distribution that carries data, how well it fits
   them. The CSV carries the numbers at full precision; the table rounds them
   to the significant figures chosen.
   ========================================================================== */

import { fmt } from './format.js';
import { theme, slotStyle, describeParams } from './chart.js';
import { familyById } from './families.js';

/* A moment that does not exist reads "undefined"; anything else missing "—". */
const moment = (v, sig) => (Number.isNaN(v) ? 'undefined' : fmt(v, sig));

function supportOf(D, sig) {
  const [a, b] = D.support;
  if (D.kind === 'discrete' && D.integer) return `${Number.isFinite(a) ? fmt(a, sig) : '…'} to ${Number.isFinite(b) ? fmt(b, sig) : '∞'}`;
  return `${Number.isFinite(a) ? fmt(a, sig) : '−∞'} to ${Number.isFinite(b) ? fmt(b, sig) : '∞'}`;
}

/* How well a distribution describes the data it carries: log-likelihood and K-S D. */
function dataFit(D, data) {
  let ll = 0;
  for (const x of data) ll += D.logpdf(x);
  const n = data.length;
  let d = 0;
  if (D.kind === 'continuous') {
    for (let i = 0; i < n; i++) { const F = D.cdf(data[i]); d = Math.max(d, (i + 1) / n - F, F - i / n); }
  } else {
    let i = 0;
    while (i < n) {
      let j = i;
      while (j + 1 < n && data[j + 1] === data[i]) j++;
      const F = D.cdf(data[i]);
      const below = F - D.pdf(data[i]);
      d = Math.max(d, Math.abs(i / n - below), Math.abs((j + 1) / n - F));
      i = j + 1;
    }
  }
  return { ll, ks: d };
}

/**
 * The rows: [label, kind, value of each item], kind 'group' for a heading.
 * Each value is [shown, exact] so the CSV can carry the exact one.
 */
export function statsRows(items, settings) {
  const sig = settings.digits;
  const rows = [];
  const group = (label) => rows.push({ label, group: true });
  const add = (label, get) => {
    rows.push({
      label,
      values: items.map((it) => {
        if (!it.D) return ['—', ''];
        try { return get(it.D, it.D.stats(), it); } catch (e) { return ['—', '']; }
      }),
    });
  };
  const num = (v) => [fmt(v, sig), Number.isFinite(v) ? String(v) : (v === Infinity ? 'inf' : v === -Infinity ? '-inf' : '')];
  const mom = (v) => [moment(v, sig), Number.isFinite(v) ? String(v) : (v === Infinity ? 'inf' : v === -Infinity ? '-inf' : Number.isNaN(v) ? 'undefined' : '')];

  group('The distribution');
  add('Kind', (D, s, it) => {
    const d = it.dist;
    const text = d.kind === 'family' ? familyById(d.family).label : d.kind === 'empirical' ? `Empirical (${d.emp.method})` : d.kind === 'table' ? (d.table.mode === 'pmf' ? 'Probability table' : 'Cumulative table') : `Monte Carlo: ${d.mc.expr}`;
    return [text, text];
  });
  add('Parameters', (D) => { const t = describeParams(D, sig); return [t || '—', describeParams(D, 17)]; });
  add('Support', (D) => { const t = supportOf(D, sig); return [t, supportOf(D, 17)]; });
  if (items.some((it) => it.D && it.D.shift)) add('Shift', (D) => num(D.shift || 0));
  if (items.some((it) => it.D && it.D.truncated)) {
    add('Truncated to', (D) => (D.truncated ? [`${fmt(D.truncated.lo, sig)} to ${fmt(D.truncated.hi, sig)}`, `${D.truncated.lo} to ${D.truncated.hi}`] : ['—', '']));
    add('Probability kept', (D) => (D.truncated ? num(D.truncated.mass) : ['—', '']));
  }

  group('Location');
  add('Mean', (D, s) => mom(s.mean));
  add('Median', (D, s) => num(s.median));
  add('Mode', (D, s) => (s.modeText ? [s.modeText, s.modeText] : num(s.mode)));
  add('Geometric mean', (D, s) => num(s.gm));

  group('Spread');
  add('Standard deviation', (D, s) => mom(s.sd));
  add('Variance', (D, s) => mom(s.variance));
  add('Coefficient of variation', (D, s) => mom(s.cv));
  add('Geometric SD', (D, s) => num(s.gsd));
  add('Interquartile range', (D, s) => num(s.iqr));
  add('Median absolute deviation', (D, s) => num(s.mad));

  group('Shape');
  add('Skewness', (D, s) => mom(s.skewness));
  add('Excess kurtosis', (D, s) => mom(s.kurtosis));
  add('Entropy (nats)', (D, s) => num(s.entropy));

  group('Percentiles');
  for (const p of settings.percentiles) add(`P${+p}`, (D) => num(p <= 50 ? D.quantile(p / 100) : D.isf(1 - p / 100)));

  if (items.some((it) => it.D && it.data && it.dist.kind === 'family')) {
    group('Against its data');
    add('Values', (D, s, it) => (it.data && it.dist.kind === 'family' ? [it.data.length.toLocaleString('en'), String(it.data.length)] : ['—', '']));
    const fits = new Map();
    const fitOf = (it) => {
      if (!fits.has(it.key)) fits.set(it.key, it.data && it.dist.kind === 'family' ? dataFit(it.D, it.data) : null);
      return fits.get(it.key);
    };
    add('Log-likelihood', (D, s, it) => { const f = fitOf(it); return f ? num(f.ll) : ['—', '']; });
    add('K–S D', (D, s, it) => { const f = fitOf(it); return f ? num(f.ks) : ['—', '']; });
  }
  return rows;
}

/** The table, drawn into a <table>. */
export function renderStatsTable(table, items, settings) {
  const th = theme();
  table.replaceChildren();
  if (!items.length) return;
  const rows = statsRows(items, settings);
  const head = table.createTHead().insertRow();
  const corner = document.createElement('th');
  corner.textContent = 'Statistic';
  head.append(corner);
  for (const it of items) {
    const c = document.createElement('th');
    const { colour, dash } = slotStyle(it.slot, th);
    const key = document.createElement('span');
    key.className = 'ds-key' + (dash === 'dash' ? ' dashed' : '');
    key.style.setProperty('--ds-colour', colour);
    c.append(key, document.createTextNode(it.name));
    if (!it.visible) {
      c.classList.add('dim');
      const note = document.createElement('span');
      note.className = 'ds-th-note';
      note.textContent = ' (hidden in the charts)';
      c.append(note);
    }
    head.append(c);
  }
  const body = table.createTBody();
  const errorRow = items.some((it) => !it.D);
  if (errorRow) {
    const tr = body.insertRow();
    const td = tr.insertCell();
    td.textContent = '';
    for (const it of items) {
      const cell = tr.insertCell();
      if (!it.D) { cell.className = 'err'; cell.textContent = it.pending ? 'drawing…' : (it.error || 'not defined'); }
    }
  }
  for (const r of rows) {
    const tr = body.insertRow();
    if (r.group) {
      tr.className = 'group';
      const td = tr.insertCell();
      td.colSpan = items.length + 1;
      td.textContent = r.label;
      continue;
    }
    tr.insertCell().textContent = r.label;
    for (const [shown] of r.values) {
      const td = tr.insertCell();
      td.textContent = shown;
      if (shown === 'undefined' || shown === '—') td.classList.add('dim');
      if (r.label === 'Kind' || r.label === 'Parameters' || r.label === 'Support' || r.label === 'Truncated to') td.classList.add('text');
    }
  }
}

/** The table as CSV rows, at full precision. */
export function statsCsvRows(items, settings) {
  const rows = statsRows(items, { ...settings, digits: 17 });
  const out = [['Statistic', ...items.map((it) => it.name)]];
  for (const r of rows) {
    if (r.group) continue;
    out.push([r.label, ...r.values.map(([shown, exact]) => (exact !== '' ? exact : shown))]);
  }
  return out;
}
