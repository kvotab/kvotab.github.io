/* ==========================================================================
   distributions.html: THE PAGE

   The state is a list of distributions as the user typed them (strings, so
   that a half-typed number stays as typed), the selected one, and the
   settings of each tab; it is kept in this browser's storage. Everything
   shown is worked out from it: each distribution's spec (dist.js), from the
   spec the evaluated distribution, from those the list, the editor, the
   charts and the tables.

   Four kinds of distribution share one list:
     family      a parametric family in one of its parameterisations
     empirical   made from data (interpolated, kernel density, histogram, ECDF)
     table       a cumulative or probability table typed in
     mc          a Monte Carlo expression of other distributions, by letter

   A Monte Carlo distribution's draws are made in the page's worker and kept
   with a signature of everything they depend on, so they are redrawn only
   when one of their distributions changes. The fits run in the same worker.
   ========================================================================== */

import { FAMILIES, familyById, GROUPS, parameterisationsOf, KNOWN, fixedKeys } from './families.js';
import { makeDistribution } from './dist.js';
import { DOMAINS, PROPERTIES, propertyById, field, describeSample } from './kit.js';
import { solveKnown } from './solve.js';
import { EMPIRICAL_METHODS, BIN_RULES, BANDWIDTH_RULES } from './empirical.js';
import { parseExpression } from './expr.js';
import { MC_MAX, runMonteCarlo } from './mc.js';
import { SCHEMES, SCHEME_SHORT } from './sampling.js';
import { setupSample } from './samplepanel.js';
import { fmt, fmtField, parseNum, parseNumberList, parsePairs, csvText, download } from './format.js';
import { figure, theme, slotStyle, curveRows, describeParams, PLOT_CONFIG, fillBins, syncBinsField, HIST_BINS } from './chart.js';
import { renderStatsTable, statsCsvRows } from './statstable.js';
import { setupFit } from './fitpanel.js';
import { setupCalc } from './calcpanel.js';
import { buildHelp } from './help.js';
import { infoTopics } from './info.js';

/* ---- constants ------------------------------------------------------------------- */

const STORAGE_KEY = 'kvot-distributions';
export const MAX_DISTS = 16;
export const LETTERS = 'ABCDEFGHIJKLMNOP';
const KINDS = [['empirical', 'Empirical, from data'], ['table', 'Table, typed in'], ['mc', 'Monte Carlo of an expression']];
const SHOW_DATA_MAX = 5000;

const $ = (id) => document.getElementById(id);

/* ---- the state --------------------------------------------------------------------- */

function uid() { return 'd' + Math.random().toString(36).slice(2, 9) + Date.now().toString(36).slice(-4); }

/** A new distribution in the first free slot, or null when all sixteen are taken. */
function blankDist(kind = 'family', family = 'normal') {
  const taken = new Set(state.dists.map((d) => d.slot));
  let slot = 0;
  while (taken.has(slot)) slot++;
  if (slot >= MAX_DISTS) return null;
  const fam = familyById(family) || familyById('normal');
  const par = parameterisationsOf(fam)[0];
  return {
    id: uid(), slot, name: '', visible: true, kind,
    family: fam.id, param: par.id, values: { [par.id]: valuesFor(par, fam.defaults) },
    known: [], shift: '', trunc: { lo: '', hi: '', by: 'value' },
    data: null, dataLabel: '', fitInfo: null,
    emp: { method: 'kde', bw: 'silverman', bwValue: '', log: false, bins: 'sturges', binCount: '' },
    table: { mode: 'cdf', text: '0 0\n1 0.25\n3 0.75\n4 1' },
    mc: { expr: '', n: '10000', seed: '1', scheme: 'random', method: 'kde' },
  };
}

function initialState() {
  return {
    v: 1, dists: [], active: null, tab: 'chart', sideWidth: null,
    chart: { top: 'pdf', bottom: 'cdf', logx: false, logy: false, showData: true, showSamples: false, pmin: '0.1', pmax: '99.9', xmin: '', xmax: '', bins: { rule: 'fd', value: '' } },
    stats: { digits: 5, percentiles: '1, 5, 10, 25, 50, 75, 90, 95, 99' },
    fit: { text: '', comma: false, column: 0, kind: 'auto', mle: true, mom: false, criterion: 'aic', trials: '', families: null, plot: 'pdf', plotLogx: false, bins: { rule: 'fd', value: '' } },
    calc: { x: '', a: '', b: '', shade: false, pcts: '0.1, 2.5, 50, 97.5, 99.9', cover: '95', t: '', level: '95', cx: null, cy: null, mcExpr: '', mcN: '10000', mcSeed: '1', mcScheme: 'random' },
    sample: { n: '1000', scheme: 'random', seed: '1', skip: [] },
  };
}

/* The page as a first visit finds it: a lognormal and the gamma with the
   same mean and standard deviation, to show that two numbers do not fix a
   shape. */
function exampleDists() {
  const a = blankDist('family', 'lognormal');
  a.param = 'gm-gsd';
  a.values = { 'gm-gsd': { gm: '10', gsd: '2' } };
  state.dists.push(a);
  const s2 = Math.log(2) ** 2;
  const mean = 10 * Math.exp(s2 / 2);
  const sd = mean * Math.sqrt(Math.expm1(s2));
  const b = blankDist('family', 'gamma');
  b.param = 'mean-sd';
  b.values = { 'mean-sd': { mean: fmtField(mean), sd: fmtField(sd) } };
  state.dists.push(b);
  state.active = a.id;
}

let state = initialState();

function load() {
  let raw = null;
  try { raw = localStorage.getItem(STORAGE_KEY); } catch (e) { raw = null; }
  if (!raw) return false;
  try {
    const got = JSON.parse(raw);
    if (!got || got.v !== 1 || !Array.isArray(got.dists)) return false;
    const base = initialState();
    const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : {});
    /* every stored setting takes the type of its default (text stays text,
       a number written as one becomes text, anything else the default), and
       a choice is one of its choices */
    const like = (def, v) => {
      if (typeof def === 'string') return typeof v === 'string' ? v : typeof v === 'number' && Number.isFinite(v) ? String(v) : def;
      if (typeof def === 'boolean') return typeof v === 'boolean' ? v : def;
      if (typeof def === 'number') return typeof v === 'number' && Number.isFinite(v) ? v : def;
      return typeof v === 'string' ? v : def;   // a distribution's id, or none
    };
    const section = (name) => {
      const g = obj(got[name]);
      return Object.fromEntries(Object.entries(base[name]).map(([k, def]) => [k, k in g ? like(def, g[k]) : def]));
    };
    const oneOf = (v, list, def) => (list.includes(v) ? v : def);
    state = {
      ...base,
      dists: got.dists,
      active: typeof got.active === 'string' ? got.active : null,
      tab: oneOf(got.tab, ['chart', 'stats', 'sample', 'fit', 'calc', 'help'], 'chart'),
      sideWidth: Number.isFinite(got.sideWidth) && got.sideWidth > 0 ? got.sideWidth : null,
      chart: section('chart'), stats: section('stats'), fit: section('fit'), calc: section('calc'), sample: section('sample'),
    };
    state.sample.scheme = oneOf(state.sample.scheme, SCHEMES.map(([k]) => k), 'random');
    /* a histogram's bins: a rule, or a number or width typed */
    const binsOf = (b) => ({ rule: oneOf(obj(b).rule, HIST_BINS.map(([k]) => k), 'fd'), value: typeof obj(b).value === 'string' ? obj(b).value : '' });
    state.chart.bins = binsOf(obj(got.chart).bins);
    state.fit.bins = binsOf(obj(got.fit).bins);
    state.calc.mcScheme = oneOf(state.calc.mcScheme, SCHEMES.map(([k]) => k), obj(got.calc).mcLhs === true ? 'lhs' : 'random');
    const skip = obj(got.sample).skip;
    state.sample.skip = Array.isArray(skip) ? skip.filter((x) => typeof x === 'string') : [];
    const FNS = ['pdf', 'cdf', 'sf', 'quantile', 'hazard'];
    state.chart.top = oneOf(state.chart.top, FNS, base.chart.top);
    state.chart.bottom = oneOf(state.chart.bottom, [...FNS, 'none'], base.chart.bottom);
    state.stats.digits = oneOf(state.stats.digits, [3, 4, 5, 6, 8, 10, 15], base.stats.digits);
    state.fit.kind = oneOf(state.fit.kind, ['auto', 'continuous', 'discrete'], 'auto');
    state.fit.plot = oneOf(state.fit.plot, ['pdf', 'cdf', 'pp', 'qq'], 'pdf');
    state.fit.column = Number.isInteger(state.fit.column) && state.fit.column >= 0 ? state.fit.column : 0;
    const fams = obj(got.fit).families;
    const names = (v) => (Array.isArray(v) ? v.filter((x) => typeof x === 'string') : null);
    state.fit.families = fams && typeof fams === 'object' && !Array.isArray(fams) ? { continuous: names(fams.continuous), discrete: names(fams.discrete) } : null;
    const seen = new Set();
    state.dists = state.dists.filter((d) => d && typeof d === 'object' && Number.isInteger(d.slot) && d.slot >= 0 && d.slot < MAX_DISTS && !seen.has(d.slot) && seen.add(d.slot)).map(repairDist);
    if (!state.dists.find((d) => d.id === state.active)) state.active = state.dists.length ? state.dists[0].id : null;
    return true;
  } catch (e) {
    return false;
  }
}

/* A stored distribution with any part it lacks filled in (and an unknown family replaced). */
function repairDist(d) {
  const blank = {
    id: uid(), name: '', visible: true, kind: 'family', family: 'normal', param: '', values: {}, known: [], trunc: { lo: '', hi: '', by: 'value' },
    data: null, dataLabel: '', fitInfo: null,
    emp: { method: 'kde', bw: 'silverman', bwValue: '', log: false, bins: 'sturges', binCount: '' },
    table: { mode: 'cdf', text: '' }, mc: { expr: '', n: '10000', seed: '1', scheme: 'random', method: 'kde' }, shift: '',
  };
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : {});
  const out = { ...blank, ...d, emp: { ...blank.emp, ...obj(d.emp) }, table: { ...blank.table, ...obj(d.table) }, mc: { ...blank.mc, ...obj(d.mc) }, trunc: { ...blank.trunc, ...obj(d.trunc) } };
  /* what a field holds is text, whatever the storage held */
  const text = (v) => (typeof v === 'string' ? v : typeof v === 'number' && Number.isFinite(v) ? String(v) : '');
  out.id = typeof out.id === 'string' && out.id ? out.id : uid();
  out.name = text(out.name);
  out.visible = out.visible !== false;
  const kept = obj(out.trunc.kept);
  out.trunc = {
    lo: text(out.trunc.lo), hi: text(out.trunc.hi), by: out.trunc.by === 'percentile' ? 'percentile' : 'value',
    ...(kept.by === 'value' || kept.by === 'percentile' ? { kept: { by: kept.by, lo: text(kept.lo), hi: text(kept.hi) } } : {}),
  };
  out.dataLabel = text(out.dataLabel);
  out.table.text = text(out.table.text);
  out.table.mode = out.table.mode === 'pmf' ? 'pmf' : 'cdf';
  for (const k of ['expr', 'n', 'seed']) out.mc[k] = text(out.mc[k]);
  /* a stored Latin hypercube flag is the scheme it was */
  out.mc.scheme = SCHEMES.some(([k]) => k === out.mc.scheme) ? out.mc.scheme : (out.mc.lhs === true ? 'lhs' : 'random');
  delete out.mc.lhs;
  out.shift = text(out.shift);
  out.emp.log = !!out.emp.log;
  for (const k of ['bwValue', 'binCount']) out.emp[k] = text(out.emp[k]);
  if (!['family', 'empirical', 'table', 'mc'].includes(out.kind)) out.kind = 'family';
  if (!familyById(out.family)) { out.family = 'normal'; out.param = ''; out.values = {}; }
  const pars = parameterisationsOf(familyById(out.family));
  if (!pars.find((p) => p.id === out.param)) out.param = pars[0].id;
  out.values = obj(out.values);
  for (const [k, v] of Object.entries(out.values)) out.values[k] = Object.fromEntries(Object.entries(obj(v)).map(([f, x]) => [f, text(x)]));
  if (out.param !== KNOWN && !out.values[out.param]) out.values[out.param] = valuesFor(pars.find((p) => p.id === out.param), familyById(out.family).defaults);
  out.known = Array.isArray(out.known) ? out.known.filter((r) => r && typeof r === 'object' && typeof r.prop === 'string').map((r) => ({ prop: r.prop, p: text(r.p), value: text(r.value) })) : [];
  if (out.data && !Array.isArray(out.data)) out.data = null;
  if (out.data) out.data = out.data.filter(Number.isFinite);
  return out;
}

let saveTimer = null;
let storageWarned = false;
function saveSoon() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(save, 500);
}
function save() {
  const text = JSON.stringify(state);
  try {
    localStorage.setItem(STORAGE_KEY, text);
  } catch (e) {
    /* too much for the browser's storage: keep everything but the largest data */
    try {
      const slim = JSON.parse(text);
      for (const d of slim.dists) if (d.data && d.data.length > 20000) { d.data = null; d.dataLabel = ''; }
      if (slim.fit && slim.fit.text && slim.fit.text.length > 200000) slim.fit.text = '';
      localStorage.setItem(STORAGE_KEY, JSON.stringify(slim));
      if (!storageWarned) status('The largest data sets are too big for this browser’s storage and will not be there on your next visit.', 'error');
      storageWarned = true;
    } catch (e2) {
      if (!storageWarned) status('This browser does not let the page keep its distributions between visits.', 'error');
      storageWarned = true;
    }
  }
}

/* ---- names ----------------------------------------------------------------------------- */

const activeDist = () => state.dists.find((d) => d.id === state.active) || null;
const distById = (id) => state.dists.find((d) => d.id === id) || null;
export const letterOf = (d) => LETTERS[d.slot];

function kindLabel(d) {
  if (d.kind === 'empirical') return `Empirical (${(EMPIRICAL_METHODS.find((m) => m[0] === d.emp.method) || ['', 'interpolated'])[1].split(' (')[0].toLowerCase()})`;
  if (d.kind === 'table') return d.table.mode === 'pmf' ? 'Probability table' : 'Cumulative table';
  if (d.kind === 'mc') return d.mc.expr ? `Monte Carlo: ${d.mc.expr}` : 'Monte Carlo';
  const fam = familyById(d.family);
  return fam ? fam.label : 'Distribution';
}

/** The name shown: what the user typed, or the family. */
export function distName(d) { return (d.name || '').trim() || kindLabel(d); }
const fullName = (d) => `${letterOf(d)}: ${distName(d)}`;

/* ---- parameterisation values --------------------------------------------------------------- */

function valuesFor(par, params, previous) {
  const out = {};
  let v;
  try { v = par.from(params, previous ? Object.fromEntries(Object.entries(previous).map(([k, x]) => [k, parseNum(x)])) : undefined); } catch (e) { v = {}; }
  for (const f of par.fields) out[f.key] = fmtField(v[f.key]);
  return out;
}

/** The current canonical parameters of a family distribution, if it resolves. */
function currentParams(d) {
  const r = derived.get(d.id);
  return r && r.D && r.D.params ? r.D.params : null;
}

/* ---- building a distribution from what was typed ----------------------------------------------- */

const knownCache = new Map();

/** The shift typed for a distribution, as a number (0 for none or a bad one). */
function shiftOf(d) {
  const t = String(d.shift ?? '').trim();
  const v = t === '' ? 0 : parseNum(t);
  return Number.isFinite(v) ? v : 0;
}

function solveKnownCached(fam, rows, fixed, start, shift = 0) {
  const key = JSON.stringify([fam.id, rows, fixed, shift]);
  if (knownCache.has(key)) {
    const hit = knownCache.get(key);
    if (hit.error) { const e = new Error(hit.error); e.closest = hit.closest; throw e; }
    return hit.params;
  }
  try {
    const params = solveKnown(fam, rows, { ...fam.defaults, ...(start || {}), ...fixed }, shift);
    knownCache.set(key, { params });
    if (knownCache.size > 200) knownCache.delete(knownCache.keys().next().value);
    return params;
  } catch (e) {
    knownCache.set(key, { error: e.message, closest: e.closest });
    throw e;
  }
}

/** The bounds of a truncation, or null for none: values, or percentiles as probabilities. */
function truncOf(d, fieldErrors) {
  const byP = d.trunc.by === 'percentile';
  const read = (key) => {
    const t = String(d.trunc[key] ?? '').trim();
    if (t === '') return null;
    const v = parseNum(t);
    if (!Number.isFinite(v)) fieldErrors[`trunc.${key}`] = 'not a number';
    else if (byP && !(v >= 0 && v <= 100)) fieldErrors[`trunc.${key}`] = 'not a percentile';
    return v;
  };
  const lo = read('lo');
  const hi = read('hi');
  if (lo === null && hi === null) return null;
  const ok = (v) => Number.isFinite(v);
  if (byP) return { by: 'p', lo: ok(lo) ? lo / 100 : null, hi: ok(hi) ? hi / 100 : null };
  return { lo: ok(lo) ? lo : null, hi: ok(hi) ? hi : null };
}

/* What the bounds were cut at, read back as the other kind: a value as the
   percentile of the distribution before truncation whose value it is, a
   percentile as its value. Empty where there is no bound or nothing to read. */
function convertTrunc(d, by) {
  const r = derived.get(d.id) || {};
  const D = r.D;
  let base = null;
  try { base = r.spec ? makeDistribution({ ...r.spec, trunc: null }) : null; } catch (e) { base = null; }
  if (!D || !D.truncated || !base) return { lo: '', hi: '' };
  const { lo, hi } = D.truncated;
  if (by === 'percentile') {
    const pct = (x, none) => {
      if (!Number.isFinite(x)) return '';
      const p = 100 * base.cdf(x);
      return p > 0 && p < 100 && p !== none ? fmtField(p) : '';
    };
    return { lo: pct(lo, 0), hi: pct(hi, 100) };
  }
  return { lo: Number.isFinite(lo) ? fmtField(lo) : '', hi: Number.isFinite(hi) ? fmtField(hi) : '' };
}

/**
 * The spec of a distribution, with the fields that are wrong and why.
 * @returns {{spec: ?Object, error: string, fieldErrors: Object, note: string, pending?: boolean}}
 */
function buildSpec(d, specs) {
  const fieldErrors = {};
  const fail = (error) => ({ spec: null, error, fieldErrors, note: '' });
  const shiftText = String(d.shift ?? '').trim();
  const shift = shiftText === '' ? 0 : parseNum(shiftText);
  if (!Number.isFinite(shift)) { fieldErrors.shift = 'not a number'; return fail('The shift is not a number.'); }
  const done = (spec, note = '') => ({ spec: shift ? { ...spec, shift } : spec, error: '', fieldErrors, note });
  const trunc = truncOf(d, fieldErrors);
  if (Object.values(fieldErrors).includes('not a number')) return fail('A bound of the truncation is not a number.');
  if (Object.keys(fieldErrors).length) return fail('A percentile of the truncation must be between 0 and 100.');

  if (d.kind === 'empirical') {
    const data = d.data || [];
    if (data.length < 2) return fail('Paste at least two values into the data box.');
    const spec = { family: 'empirical', method: d.emp.method, data, trunc };
    if (d.emp.method === 'kde') {
      if (d.emp.bw === 'given') {
        const h = parseNum(d.emp.bwValue);
        if (!(h > 0)) { fieldErrors['emp.bwValue'] = 'must be above 0'; return fail('Give a bandwidth above zero.'); }
        spec.bw = h;
      } else spec.bw = d.emp.bw;
      spec.log = !!d.emp.log;
    }
    if (d.emp.method === 'histogram') {
      if (d.emp.bins === 'count') {
        const k = parseNum(d.emp.binCount);
        if (!(Number.isInteger(k) && k >= 1 && k <= 10000)) { fieldErrors['emp.binCount'] = 'a whole number from 1 to 10000'; return fail('Give a number of bins from 1 to 10,000.'); }
        spec.bins = k;
      } else spec.bins = d.emp.bins;
    }
    return done(spec);
  }

  if (d.kind === 'table') {
    const { rows, bad } = parsePairs(d.table.text);
    if (!rows.length) return fail('Type the table, one pair of numbers per line.');
    return done({ family: 'table', mode: d.table.mode, rows, trunc }, bad ? `${bad} line${bad > 1 ? 's' : ''} without exactly two numbers ${bad > 1 ? 'are' : 'is'} left out.` : '');
  }

  if (d.kind === 'mc') {
    if (d._cycle) return fail('The expression uses this distribution itself, through another Monte Carlo distribution.');
    const run = mcRuns.get(d.id);
    const want = mcSignature(d, specs);
    if (want.error) return fail(want.error);
    if (!run || run.sig !== want.sig) { requestMc(d, want); return { spec: null, error: '', fieldErrors, note: '', pending: true }; }
    if (run.status === 'running') return { spec: null, error: '', fieldErrors, note: '', pending: true };
    if (run.status === 'error') return fail(run.error);
    if (run.values.length < 2) return fail('Fewer than two draws gave a finite number.');
    const note = run.dropped ? `${run.dropped.toLocaleString('en')} of the ${Number(d.mc.n).toLocaleString('en')} draws gave no finite number and are left out.` : '';
    return done({ family: 'empirical', method: d.mc.method, data: run.values, trunc }, note);
  }

  /* a family */
  const fam = familyById(d.family);
  if (!fam) return fail('Unknown family.');
  const pars = parameterisationsOf(fam);
  const par = pars.find((p) => p.id === d.param) || pars[0];
  if (par.id === KNOWN) {
    const fixed = {};
    const store = d.values[KNOWN] || {};
    for (const key of fixedKeys(fam)) {
      const def = fam.params.find((p) => p.key === key);
      const v = parseNum(store[key] ?? '');
      const why = !Number.isFinite(v) ? 'is missing' : (DOMAINS[def.domain] || DOMAINS.real).check(v);
      if (why) { fieldErrors[`values.${KNOWN}.${key}`] = why; return fail(`${def.label} ${why}.`); }
      fixed[key] = v;
    }
    const rows = [];
    for (let i = 0; i < d.known.length; i++) {
      const r = d.known[i];
      const value = parseNum(r.value);
      const p = r.prop === 'q' ? parseNum(r.p) : undefined;
      if (!Number.isFinite(value)) { fieldErrors[`known.${i}.value`] = 'missing'; return fail('Give every value.'); }
      if (r.prop === 'q' && !(p > 0 && p < 100)) { fieldErrors[`known.${i}.p`] = 'between 0 and 100'; return fail('A percentile must be between 0 and 100.'); }
      rows.push(r.prop === 'q' ? { prop: 'q', p, value } : { prop: r.prop, value });
    }
    let params;
    try {
      params = solveKnownCached(fam, rows, fixed, d._lastParams, shift);
    } catch (e) {
      let msg = e.message;
      if (e.closest) {
        try {
          const D = makeDistribution({ family: fam.id, params: e.closest, shift });
          msg += ` The nearest, ${describeParams(D)}, has ${rows.map((r) => describeRow(r, D)).join(', ')}.`;
        } catch (e2) { /* no nearest to show */ }
      }
      return fail(msg);
    }
    return done({ family: fam.id, params, trunc });
  }
  const values = {};
  const store = d.values[par.id] || {};
  for (const f of par.fields) {
    const v = parseNum(store[f.key] ?? '');
    if (!Number.isFinite(v)) { fieldErrors[`values.${par.id}.${f.key}`] = 'missing'; return fail(`${f.label} is missing.`); }
    const why = (DOMAINS[f.domain] || DOMAINS.real).check(v);
    if (why) { fieldErrors[`values.${par.id}.${f.key}`] = why; return fail(`${f.label} ${why}.`); }
    values[f.key] = v;
  }
  let params;
  try { params = par.to(values); } catch (e) { return fail(e.message); }
  return done({ family: fam.id, params: { ...fam.defaults, ...params }, trunc });
}

function describeRow(row, D) {
  const st = D.stats();
  const label = row.prop === 'q' ? `P${+row.p}` : (propertyById(row.prop) || { label: row.prop }).label.toLowerCase();
  const v = row.prop === 'q' ? D.quantile(row.p / 100) : { mean: st.mean, median: st.median, mode: st.mode, sd: st.sd, var: st.variance, cv: st.cv, gm: st.gm, gsd: st.gsd }[row.prop];
  return `${label} ${fmt(v, 5)}`;
}

/* ---- Monte Carlo runs ------------------------------------------------------------------------- */

const mcRuns = new Map();   // id -> { sig, status, values, dropped, error }

/* FNV-1a over a string: a short signature of a spec, data and all. */
function hash(text) {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 0x01000193); }
  return (h >>> 0).toString(36);
}

/** What a Monte Carlo distribution's draws depend on, or why it cannot be drawn. */
function mcSignature(d, specs) {
  const expr = String(d.mc.expr || '').trim();
  if (!expr) return { error: 'Type an expression of the distributions’ letters, such as A * B.' };
  const n = parseNum(d.mc.n);
  if (!(Number.isInteger(n) && n >= 2 && n <= MC_MAX)) return { error: `The number of draws must be a whole number from 2 to ${MC_MAX.toLocaleString('en')}.` };
  const seed = parseNum(d.mc.seed);
  if (!Number.isInteger(seed)) return { error: 'The seed must be a whole number.' };
  let vars;
  try {
    vars = parseExpression(expr, (name) => /^[A-P]$/.test(name) && state.dists.some((x) => letterOf(x) === name)).variables;
  } catch (e) { return { error: e.message }; }
  if (!vars.length) return { error: 'The expression names no distribution.' };
  const deps = {};
  for (const letter of vars) {
    const dep = state.dists.find((x) => letterOf(x) === letter);
    if (dep.id === d.id) return { error: 'The expression uses this distribution itself.' };
    const s = specs.get(dep.id);
    if (!s || !s.spec) return { error: s && s.pending ? 'Waiting for the distributions it uses.' : `${letter} has an error; it cannot be drawn.` };
    deps[letter] = s.spec;
  }
  const scheme = SCHEMES.some(([k]) => k === d.mc.scheme) ? d.mc.scheme : 'random';
  const sig = hash(JSON.stringify([expr, n, seed, scheme, Object.keys(deps).sort().map((k) => [k, deps[k]])]));
  return { sig, deps, expr, n, seed, scheme };
}

let worker = null;
let workerBroken = false;
let jobId = 0;
const jobs = new Map();

function getWorker() {
  if (workerBroken) return null;
  if (worker) return worker;
  try {
    worker = new Worker(new URL('./worker.js', import.meta.url), { type: 'module' });
    worker.onmessage = (ev) => {
      const m = ev.data;
      const job = jobs.get(m.id);
      if (!job) return;
      if (m.type === 'progress') { if (job.progress) job.progress(m.done, m.total, m.label); return; }
      jobs.delete(m.id);
      if (m.type === 'error') job.reject(new Error(m.message));
      else job.resolve(m.result);
    };
    worker.onerror = () => {
      workerBroken = true;
      for (const [, job] of jobs) job.reject(new Error('worker failed'));
      jobs.clear();
      worker = null;
    };
  } catch (e) {
    workerBroken = true;
    worker = null;
  }
  return worker;
}

/** A job in the worker, or in the page when there is no worker. */
export function runJob(type, payload, progress) {
  const w = getWorker();
  if (!w) return Promise.resolve().then(() => localJob(type, payload, progress));
  return new Promise((resolve, reject) => {
    const id = ++jobId;
    jobs.set(id, { resolve, reject, progress });
    w.postMessage({ id, type, payload });
  }).catch((e) => {
    if (e.message === 'worker failed') return localJob(type, payload, progress);
    throw e;
  });
}

/** Stop every job in the worker (a fit the user stopped). */
export function stopJobs() {
  if (worker) { worker.terminate(); worker = null; }
  for (const [, job] of jobs) job.reject(new Error('stopped'));
  jobs.clear();
}

let localFit = null;
let localSample = null;
async function localJob(type, payload, progress) {
  if (type === 'mc') return runMonteCarlo(payload.specs, payload.expr, payload.n, payload.seed, payload.scheme);
  if (type === 'sample') {
    if (!localSample) localSample = await import('./sampling.js');
    return localSample.sampleJob(payload, progress);
  }
  if (type === 'fit') {
    if (!localFit) localFit = await import('./fit.js');
    return localFit.fitAll(payload.values, payload.opts, progress);
  }
  throw new Error('unknown job');
}

function requestMc(d, want) {
  mcRuns.set(d.id, { sig: want.sig, status: 'running', values: null, dropped: 0, error: '' });
  status(`Drawing ${fullName(d)}…`);
  runJob('mc', { specs: want.deps, expr: want.expr, n: want.n, seed: want.seed, scheme: want.scheme }).then((res) => {
    const run = mcRuns.get(d.id);
    if (!run || run.sig !== want.sig) return;
    mcRuns.set(d.id, { sig: want.sig, status: 'done', values: Array.from(res.values), dropped: res.dropped, error: '' });
    status('');
    refresh();
  }).catch((e) => {
    const run = mcRuns.get(d.id);
    if (!run || run.sig !== want.sig) return;
    /* stopped with the fits it shared the worker with: drawn again */
    if (e.message === 'stopped') { mcRuns.delete(d.id); setTimeout(() => refresh(), 0); return; }
    mcRuns.set(d.id, { sig: want.sig, status: 'error', values: null, dropped: 0, error: e.message });
    status('');
    refresh();
  });
}

/* ---- evaluating everything ---------------------------------------------------------------------- */

const derived = new Map();   // id -> { spec, D, error, note, fieldErrors, pending }

/* The Monte Carlo distributions after the ones they use. */
function evaluationOrder() {
  const plain = state.dists.filter((d) => d.kind !== 'mc');
  const mc = state.dists.filter((d) => d.kind === 'mc');
  const order = [...plain];
  const placed = new Set(plain.map((d) => d.id));
  let progress = true;
  while (mc.some((d) => !placed.has(d.id)) && progress) {
    progress = false;
    for (const d of mc) {
      if (placed.has(d.id)) continue;
      let uses = [];
      try { uses = parseExpression(String(d.mc.expr || ''), (n) => /^[A-P]$/.test(n)).variables; } catch (e) { uses = []; }
      const ready = uses.every((l) => { const dep = state.dists.find((x) => letterOf(x) === l); return !dep || dep.kind !== 'mc' || placed.has(dep.id) || dep.id === d.id; });
      if (ready) { order.push(d); placed.add(d.id); progress = true; }
    }
  }
  for (const d of mc) if (!placed.has(d.id)) { d._cycle = true; order.push(d); } else d._cycle = false;
  return order;
}

function recompute() {
  const specs = new Map();
  for (const d of evaluationOrder()) {
    const r = buildSpec(d, specs);
    if (r.spec) {
      try {
        r.D = makeDistribution(r.spec);
        if (r.D.note) r.note = r.note ? `${r.note} ${r.D.note}` : r.D.note;
        if (r.D.params) d._lastParams = r.D.params;
      } catch (e) {
        r.error = e.message;
        r.D = null;
        r.spec = null;
      }
    }
    specs.set(d.id, r);
    derived.set(d.id, r);
  }
  for (const id of [...derived.keys()]) if (!distById(id)) derived.delete(id);
  for (const id of [...mcRuns.keys()]) if (!distById(id)) mcRuns.delete(id);
}

/** Every distribution as the charts and tables take it. */
export function items() {
  return state.dists.map((d) => {
    const r = derived.get(d.id) || {};
    const data = d.kind === 'family' && d.data && d.data.length ? Float64Array.from(d.data).sort() : (d.kind === 'empirical' && d.data ? Float64Array.from(d.data).sort() : null);
    const sample = samplePanel ? samplePanel.sortedSample(d.id, letterOf(d)) : null;
    return { key: d.id, dist: d, name: fullName(d), shortName: distName(d), letter: letterOf(d), slot: d.slot, D: r.D || null, error: r.error || '', pending: !!r.pending, visible: d.visible, data, sample };
  });
}

/* ---- the status line ---------------------------------------------------------------------------- */

let statusTimer = null;
export function status(text, tone = '') {
  const el = $('dsStatus');
  if (!el) return;
  el.textContent = text || '';
  el.classList.toggle('error', tone === 'error');
  clearTimeout(statusTimer);
  if (text && tone !== 'sticky') statusTimer = setTimeout(() => { if (el.textContent === text) el.textContent = ''; }, 9000);
}

/* ---- the list ------------------------------------------------------------------------------------ */

function renderList() {
  const list = $('dsList');
  const th = theme();
  list.replaceChildren();
  for (const d of state.dists) {
    const r = derived.get(d.id) || {};
    const { colour, dash } = slotStyle(d.slot, th);
    const li = document.createElement('li');
    li.className = 'ds-item' + (d.id === state.active ? ' active' : '') + (d.visible ? '' : ' hidden-in-chart') + (r.error ? ' invalid' : '');
    li.style.setProperty('--ds-colour', colour);
    li.dataset.id = d.id;
    const sw = document.createElement('button');
    sw.type = 'button';
    sw.className = 'ds-swatch' + (dash === 'dash' ? ' dashed' : '');
    sw.dataset.id = d.id;
    sw.dataset.onClick = 'ds:toggleVisible';
    const what = d.visible ? `Hide ${fullName(d)} in the charts` : `Show ${fullName(d)} in the charts`;
    sw.title = what;
    sw.setAttribute('aria-label', what);
    sw.setAttribute('aria-pressed', String(d.visible));
    const main = document.createElement('button');
    main.type = 'button';
    main.className = 'ds-item-main';
    main.dataset.id = d.id;
    main.dataset.onClick = 'ds:select';
    main.setAttribute('aria-current', d.id === state.active ? 'true' : 'false');
    const nm = document.createElement('span');
    nm.className = 'ds-item-name';
    const letter = document.createElement('span');
    letter.className = 'ds-letter';
    letter.textContent = letterOf(d);
    nm.append(letter, document.createTextNode(distName(d)));
    const desc = document.createElement('span');
    desc.className = 'ds-item-desc' + (r.error ? ' error' : '');
    desc.textContent = r.error ? r.error : r.pending ? 'drawing…' : describeItem(d, r);
    main.append(nm, desc);
    const rm = document.createElement('button');
    rm.type = 'button';
    rm.className = 'ds-remove';
    rm.textContent = '×';
    rm.dataset.id = d.id;
    rm.dataset.onClick = 'ds:remove';
    rm.title = `Remove ${fullName(d)}`;
    rm.setAttribute('aria-label', `Remove ${fullName(d)}`);
    li.append(sw, main, rm);
    list.append(li);
  }
  $('dsCount').textContent = `${state.dists.length} of ${MAX_DISTS}`;
  $('dsAdd').disabled = state.dists.length >= MAX_DISTS;
  $('dsDuplicate').disabled = state.dists.length >= MAX_DISTS || !activeDist();
}

function describeItem(d, r) {
  if (!r.D) return '';
  const tr = r.D.truncated ? ` on [${fmt(r.D.truncated.lo, 4)}, ${fmt(r.D.truncated.hi, 4)}]` : '';
  if (d.kind === 'family') {
    const fam = familyById(d.family);
    const label = (d.name || '').trim() ? `${fam.label}: ` : '';
    return label + describeParams(r.D) + tr;
  }
  const st = r.D.stats();
  const moved = r.D.shift ? `, shifted by ${fmt(r.D.shift, 4)}` : '';
  if (d.kind === 'empirical' || d.kind === 'mc') return `n = ${(d.kind === 'mc' ? (mcRuns.get(d.id)?.values?.length ?? 0) : d.data.length).toLocaleString('en')}, mean ${fmt(st.mean, 4)}, SD ${fmt(st.sd, 4)}${moved}${tr}`;
  return `mean ${fmt(st.mean, 4)}, SD ${fmt(st.sd, 4)}${moved}${tr}`;
}

/* ---- the editor ------------------------------------------------------------------------------------ */

function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else if (k.startsWith('data-')) e.setAttribute(k, v);
    else if (k === 'value') e.value = v;
    else if (k === 'checked') e.checked = !!v;
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children) if (c !== null && c !== undefined && c !== false) e.append(c);
  return e;
}

/* A labelled row of the editor with an (i) on its label line. */
function row(label, infoKey, control, forId) {
  const line = el('div', { class: 'kvot-info-line' }, el('label', { for: forId, text: label }));
  if (infoKey) line.append(KvotInfo.slot(infoKey));
  return el('div', { class: 'ds-row' }, line, control);
}

function kindSelect(d) {
  const sel = el('select', { id: 'dsFamily', 'data-on-change': 'ds:setFamily' });
  for (const [g, glabel] of GROUPS) {
    const og = el('optgroup', { label: glabel });
    for (const f of FAMILIES.filter((x) => x.group === g)) og.append(el('option', { value: f.id, text: f.label }));
    sel.append(og);
  }
  const og = el('optgroup', { label: 'No family' });
  for (const [k, label] of KINDS) og.append(el('option', { value: `kind:${k}`, text: label }));
  sel.append(og);
  sel.value = d.kind === 'family' ? d.family : `kind:${d.kind}`;
  return sel;
}

function inputField(path, value, label, extra = {}) {
  const input = el('input', { type: 'text', inputmode: extra.inputmode || 'decimal', class: 'num', 'data-path': path, 'data-on-input': 'ds:edit', value: value ?? '', 'aria-label': label, placeholder: extra.placeholder || '', spellcheck: 'false', autocomplete: 'off' });
  return input;
}

function renderEditor() {
  const box = $('dsEditor');
  const d = activeDist();
  box.replaceChildren();
  $('dsEditorTitle').textContent = d ? fullName(d) : 'Distribution';
  if (!d) {
    box.append(el('p', { class: 'ds-hint', text: 'No distribution. Add one with + Add.' }));
    return;
  }
  box.append(row('Name', 'set:name', el('input', { type: 'text', id: 'dsName', 'data-path': 'name', 'data-on-input': 'ds:edit', value: d.name, placeholder: kindLabel(d), maxlength: '60', autocomplete: 'off' }), 'dsName'));
  box.append(row('Family', 'set:family', kindSelect(d), 'dsFamily'));
  if (d.kind === 'family') renderFamilyEditor(box, d);
  else if (d.kind === 'empirical') renderEmpiricalEditor(box, d);
  else if (d.kind === 'table') renderTableEditor(box, d);
  else renderMcEditor(box, d);
  box.append(el('p', { class: 'ds-msg error', id: 'dsEditorError', hidden: true }));
  box.append(el('p', { class: 'ds-msg note', id: 'dsEditorNote', hidden: true }));
  box.append(el('dl', { class: 'ds-facts', id: 'dsEditorFacts' }));
  /* shift */
  const sh = el('details', { class: 'ds-sub', id: 'dsShiftBox' });
  if (String(d.shift ?? '').trim() !== '') sh.open = true;
  sh.append(el('summary', { class: 'ds-sub-title', style: 'cursor: pointer' }, 'Shift'));
  const wholeOnly = d.kind === 'family' && (familyById(d.family) || {}).kind === 'discrete';
  sh.append(el('div', { class: 'ds-fields' },
    el('label', { class: 'ds-field' }, el('span', { text: 'Added to every value' }), inputField('shift', d.shift, 'Shift: a number added to every value', { placeholder: '0' }))));
  const shLine = el('div', { class: 'kvot-info-line' }, el('span', { class: 'ds-hint', text: wholeOnly ? 'X + shift: a whole number for counts. The spread and shape stay as they are; the bounds of a truncation are in shifted values.' : 'X + shift: the whole distribution moved along x, its spread and shape as they are. The bounds of a truncation are in shifted values.' }));
  shLine.append(KvotInfo.slot('set:shift'));
  sh.append(shLine);
  box.append(sh);
  /* truncation */
  const tr = el('details', { class: 'ds-sub', id: 'dsTruncBox' });
  if (String(d.trunc.lo).trim() !== '' || String(d.trunc.hi).trim() !== '') tr.open = true;
  const sum = el('summary', { class: 'ds-sub-title', style: 'cursor: pointer' }, 'Truncation');
  tr.append(sum);
  const byP = d.trunc.by === 'percentile';
  const radio = (value, text) => el('label', {}, el('input', { type: 'radio', name: 'dsTruncBy', value, checked: (d.trunc.by || 'value') === value, 'data-on-change': 'ds:truncBy' }), el('span', { text }));
  const by = el('div', { class: 'ds-inline ds-trunc-by' }, el('span', { text: 'Bounds as' }),
    el('span', { class: 'ds-seg', role: 'radiogroup', 'aria-label': 'Bounds of the truncation as' }, radio('value', 'values'), radio('percentile', 'percentiles')));
  const tf = el('div', { class: 'ds-fields' },
    el('label', { class: 'ds-field' }, el('span', { text: byP ? 'Lower percentile (%)' : 'Lower bound' }), inputField('trunc.lo', d.trunc.lo, byP ? 'Lower percentile of the truncation, in per cent' : 'Lower bound of the truncation', { placeholder: 'none' })),
    el('label', { class: 'ds-field' }, el('span', { text: byP ? 'Upper percentile (%)' : 'Upper bound' }), inputField('trunc.hi', d.trunc.hi, byP ? 'Upper percentile of the truncation, in per cent' : 'Upper bound of the truncation', { placeholder: 'none' })));
  tr.append(by);
  const line = el('div', { class: 'kvot-info-line' }, el('span', { class: 'ds-hint', id: 'dsTruncNote', text: '' }));
  line.append(KvotInfo.slot('set:trunc'));
  tr.append(tf, line);
  box.append(tr);
  if (d.kind === 'family' && d.data && d.data.length) {
    const att = el('div', { class: 'ds-sub' },
      el('span', { class: 'ds-sub-title', text: 'Data' }),
      el('p', { class: 'ds-hint', text: `${d.dataLabel || 'Data'}: ${d.data.length.toLocaleString('en')} values, drawn behind the curves when Data is ticked in the chart.` }),
      el('div', { class: 'ds-inline' }, el('button', { type: 'button', class: 'ds-btn small secondary', 'data-on-click': 'ds:detachData', text: 'Remove the data' })));
    box.append(att);
  }
  KvotInfo.mount(box);
  updateEditorState();
}

function renderFamilyEditor(box, d) {
  const fam = familyById(d.family);
  box.append(el('p', { class: 'ds-hint', text: fam.blurb }));
  const pars = parameterisationsOf(fam);
  const par = pars.find((p) => p.id === d.param) || pars[0];
  const psel = el('select', { id: 'dsParam', 'data-on-change': 'ds:setParam' });
  for (const p of pars) psel.append(el('option', { value: p.id, text: p.label }));
  psel.value = par.id;
  box.append(row('Given by', 'set:param', psel, 'dsParam'));
  if (par.id === KNOWN) {
    const fixed = fixedKeys(fam);
    if (fixed.length) {
      const store = d.values[KNOWN] || {};
      const grid = el('div', { class: 'ds-fields' });
      for (const key of fixed) {
        const def = fam.params.find((p) => p.key === key);
        grid.append(el('label', { class: 'ds-field' }, el('span', { text: `${def.label} (kept)` }), inputField(`values.${KNOWN}.${key}`, store[key] ?? '', def.label)));
      }
      box.append(grid);
    }
    const kbox = el('div', { class: 'ds-known', id: 'dsKnown' });
    const usable = PROPERTIES.filter((p) => !p.positive || fam.support(fam.defaults)[0] >= 0);
    d.known.forEach((r, i) => {
      const sel = el('select', { 'data-path': `known.${i}.prop`, 'data-on-change': 'ds:editKnownProp', 'aria-label': `Property ${i + 1}` });
      for (const p of usable) sel.append(el('option', { value: p.id, text: p.label }));
      sel.value = r.prop;
      const pct = inputField(`known.${i}.p`, r.p, `Percentile ${i + 1}, in per cent`, { placeholder: '%' });
      pct.classList.add('pct');
      if (r.prop !== 'q') pct.hidden = true;
      const val = inputField(`known.${i}.value`, r.value, `Value ${i + 1}`);
      kbox.append(el('div', { class: 'ds-known-row' }, sel, pct, val));
    });
    box.append(kbox);
    box.append(el('p', { class: 'ds-hint', text: `Solved for ${fam.free.keys.map((k) => fam.params.find((p) => p.key === k).label).join(', ')}.` }));
    return;
  }
  const store = d.values[par.id] || {};
  const grid = el('div', { class: 'ds-fields' });
  for (const f of par.fields) {
    const note = DOMAINS[f.domain] && f.domain !== 'real' ? DOMAINS[f.domain].note : '';
    grid.append(el('label', { class: 'ds-field' }, el('span', {}, f.label, note ? el('small', { text: ` (${note})` }) : null), inputField(`values.${par.id}.${f.key}`, store[f.key] ?? '', f.label, { inputmode: f.domain.endsWith('int') || f.domain === 'int' ? 'numeric' : 'decimal' })));
  }
  box.append(grid);
  if (par.covers) {
    const p = currentParams(d);
    if (p && !par.covers(p)) box.append(el('p', { class: 'ds-msg note', text: `This parameterisation describes only ${par.coversText}.` }));
  }
}

function renderEmpiricalEditor(box, d) {
  const msel = el('select', { id: 'dsEmpMethod', 'data-path': 'emp.method', 'data-on-change': 'ds:editStructure' });
  for (const [k, label] of EMPIRICAL_METHODS) msel.append(el('option', { value: k, text: label }));
  msel.value = d.emp.method;
  box.append(row('Method', 'set:empMethod', msel, 'dsEmpMethod'));
  if (d.emp.method === 'kde') {
    const bsel = el('select', { 'data-path': 'emp.bw', 'data-on-change': 'ds:editStructure', 'aria-label': 'Bandwidth rule' });
    for (const [k, label] of BANDWIDTH_RULES) bsel.append(el('option', { value: k, text: label }));
    bsel.append(el('option', { value: 'given', text: 'Given' }));
    bsel.value = d.emp.bw;
    const line = el('div', { class: 'ds-inline' }, bsel);
    if (d.emp.bw === 'given') line.append(inputField('emp.bwValue', d.emp.bwValue, 'Bandwidth', { placeholder: 'h' }));
    box.append(row('Bandwidth', 'set:bandwidth', line));
    box.append(el('label', { class: 'ds-check', style: 'margin: -4px 0 9px' }, el('input', { type: 'checkbox', 'data-path': 'emp.log', 'data-on-change': 'ds:editStructure', checked: d.emp.log }), 'in ln x (positive data)'));
  }
  if (d.emp.method === 'histogram') {
    const bsel = el('select', { 'data-path': 'emp.bins', 'data-on-change': 'ds:editStructure', 'aria-label': 'Bin rule' });
    for (const [k, label] of BIN_RULES) bsel.append(el('option', { value: k, text: label }));
    bsel.append(el('option', { value: 'count', text: 'A number of bins' }));
    bsel.value = d.emp.bins;
    const line = el('div', { class: 'ds-inline' }, bsel);
    if (d.emp.bins === 'count') line.append(inputField('emp.binCount', d.emp.binCount, 'Number of bins', { inputmode: 'numeric', placeholder: 'bins' }));
    box.append(row('Bins', 'set:bins', line));
  }
  const n = d.data ? d.data.length : 0;
  const ta = el('textarea', { id: 'dsEmpData', 'data-on-input': 'ds:empData', spellcheck: 'false', rows: '6', 'aria-label': 'Data' });
  if (n && n <= SHOW_DATA_MAX) ta.value = d.data.join('\n');
  else if (n) ta.placeholder = `${n.toLocaleString('en')} values${d.dataLabel ? ' from ' + d.dataLabel : ''}, too many to show here. Paste values to replace them.`;
  else ta.placeholder = 'Paste or type the values, separated by spaces, commas, semicolons or new lines.';
  box.append(row('Data', 'set:empData', ta, 'dsEmpData'));
}

function renderTableEditor(box, d) {
  const msel = el('select', { id: 'dsTableMode', 'data-path': 'table.mode', 'data-on-change': 'ds:editStructure' });
  msel.append(el('option', { value: 'cdf', text: 'Cumulative: x and F(x), straight lines between' }), el('option', { value: 'pmf', text: 'Probabilities: x and P(X = x)' }));
  msel.value = d.table.mode;
  box.append(row('Table', 'set:tableMode', msel, 'dsTableMode'));
  const ta = el('textarea', { id: 'dsTableText', 'data-path': 'table.text', 'data-on-input': 'ds:edit', spellcheck: 'false', rows: '7', 'aria-label': 'Table rows' });
  ta.value = d.table.text;
  box.append(row(d.table.mode === 'pmf' ? 'Rows: x  p' : 'Rows: x  F(x)', 'set:tableRows', ta, 'dsTableText'));
}

function renderMcEditor(box, d) {
  box.append(row('Expression', 'set:mcExpr', el('input', { type: 'text', id: 'dsMcExpr', class: 'num', 'data-path': 'mc.expr', 'data-on-input': 'ds:edit', value: d.mc.expr, placeholder: 'e.g. A * B + 2', spellcheck: 'false', autocomplete: 'off' }), 'dsMcExpr'));
  box.append(el('div', { class: 'ds-fields' },
    el('label', { class: 'ds-field' }, el('span', { text: 'Draws' }), inputField('mc.n', d.mc.n, 'Number of draws', { inputmode: 'numeric' })),
    el('label', { class: 'ds-field' }, el('span', { text: 'Seed' }), inputField('mc.seed', d.mc.seed, 'Seed', { inputmode: 'numeric' }))));
  const ssel = el('select', { id: 'dsMcScheme', 'data-path': 'mc.scheme', 'data-on-change': 'ds:editStructure' });
  for (const [k, label] of SCHEMES) ssel.append(el('option', { value: k, text: label }));
  ssel.value = SCHEMES.some(([k]) => k === d.mc.scheme) ? d.mc.scheme : 'random';
  box.append(row('Sampling scheme', 'set:mcScheme', ssel, 'dsMcScheme'));
  const msel = el('select', { id: 'dsMcMethod', 'data-path': 'mc.method', 'data-on-change': 'ds:editStructure' });
  for (const [k, label] of EMPIRICAL_METHODS) msel.append(el('option', { value: k, text: label }));
  msel.value = d.mc.method;
  box.append(row('The draws as', 'set:mcMethod', msel, 'dsMcMethod'));
}

/* What changes while typing: messages, red fields, facts. The editor itself is not rebuilt. */
function updateEditorState() {
  const d = activeDist();
  if (!d) return;
  const r = derived.get(d.id) || {};
  const err = $('dsEditorError');
  const note = $('dsEditorNote');
  if (err) { err.textContent = r.error || ''; err.hidden = !r.error; }
  if (note) { note.textContent = r.pending ? 'Drawing…' : (r.note || ''); note.hidden = !(r.note || r.pending); }
  for (const input of document.querySelectorAll('#dsEditor [data-path]')) {
    const bad = r.fieldErrors && r.fieldErrors[input.dataset.path];
    input.setAttribute('aria-invalid', bad ? 'true' : 'false');
  }
  const facts = $('dsEditorFacts');
  if (facts) {
    facts.replaceChildren();
    if (r.D) {
      const D = r.D;
      const add = (k, v) => facts.append(el('dt', { text: k }), el('dd', { text: v }));
      add('Support', supportText(D));
      if (d.kind === 'family' && d.param !== familyById(d.family).parameterisations[0].id) add('Parameters', describeParams(D, 6));
      const st = D.stats();
      add('Mean, SD', `${fmtStat(st.mean)}, ${fmtStat(st.sd)}`);
      add('Median', fmt(st.median, 6));
      if (d.kind === 'empirical' && D.prepared && D.prepared.h) add('Bandwidth h', fmt(D.prepared.h, 5) + (d.emp.log ? ' (in ln x)' : ''));
      if (d.kind === 'empirical' && D.prepared && D.prepared.bins) add('Bins', `${D.prepared.bins.counts.length} of width ${fmt(D.prepared.bins.width, 4)}`);
    }
  }
  const tn = $('dsTruncNote');
  if (tn) tn.textContent = truncNote(d, r.D);
  $('dsEditorTitle').textContent = fullName(d);
}

/* The line under the bounds: what they hold, and where percentiles cut. */
function truncNote(d, D) {
  if (!D || !D.truncated) return d.trunc.by === 'percentile' ? 'Leave a percentile empty for none: 0 and 100 are none too.' : 'Leave a bound empty for none.';
  const t = D.truncated;
  const share = `${fmt(100 * t.mass, 5)} % of the distribution before truncation`;
  if (d.trunc.by !== 'percentile') return `The bounds hold ${share}.`;
  const lo = Number.isFinite(t.lo) && t.plo != null;
  const hi = Number.isFinite(t.hi) && t.phi != null;
  if (lo && hi) return `The bounds are ${fmt(t.lo, 6)} and ${fmt(t.hi, 6)}; they hold ${share}.`;
  if (lo) return `The lower bound is ${fmt(t.lo, 6)}; it keeps ${share}.`;
  if (hi) return `The upper bound is ${fmt(t.hi, 6)}; it keeps ${share}.`;
  return `The bounds hold ${share}.`;
}

export function supportText(D) {
  const [a, b] = D.support;
  if (D.kind === 'discrete' && D.integer) return `{${Number.isFinite(a) ? fmt(a, 8) : '…'}, …, ${Number.isFinite(b) ? fmt(b, 8) : '∞'}}`;
  if (D.kind === 'discrete') return `${D.atoms()[0].length.toLocaleString('en')} values from ${fmt(a, 6)} to ${fmt(b, 6)}`;
  return `${Number.isFinite(a) ? '[' + fmt(a, 6) : '(−∞'}, ${Number.isFinite(b) ? fmt(b, 6) + ']' : '∞)'}`;
}

export function fmtStat(v, sig = 5) {
  if (Number.isNaN(v)) return 'undefined';
  return fmt(v, sig);
}

/* ---- changing a distribution ---------------------------------------------------------------------- */

function setPath(obj, path, value) {
  const parts = path.split('.');
  let o = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    const k = parts[i];
    if (o[k] === undefined || o[k] === null || typeof o[k] !== 'object') o[k] = /^\d+$/.test(parts[i + 1]) ? [] : {};
    o = o[k];
  }
  o[parts[parts.length - 1]] = value;
}

/* The member of a new family nearest the distribution as it is: the same
   mean and SD (or mean alone, for one parameter), when the family can have
   them. */
function matchFamily(fam, previous, shift = 0) {
  const p0 = { ...fam.defaults };
  if (!previous) return p0;
  const st = previous.stats();
  /* the new family takes the same shift, so it matches the values before it */
  const mean = st.mean - shift;
  const sd = st.sd;
  if (!(Number.isFinite(mean) && Number.isFinite(sd) && sd > 0)) return p0;
  if (fam.kind === 'continuous' && fam.free) {
    const k = fam.free.keys.length;
    const rows = k === 1 ? [{ prop: 'mean', value: mean }] : k === 2 ? [{ prop: 'mean', value: mean }, { prop: 'sd', value: sd }] : null;
    if (rows) {
      try { return solveKnown(fam, rows, p0); } catch (e) { /* the family cannot have them */ }
    }
    if (k === 3) {
      try { return solveKnown(fam, [{ prop: 'mean', value: mean }, { prop: 'sd', value: sd }, { prop: 'median', value: st.median - shift }], p0); } catch (e) { /* nor these */ }
    }
    return p0;
  }
  if (fam.kind === 'discrete' && mean > 0) {
    try {
      if (fam.id === 'poisson') return { lambda: mean };
      if (fam.id === 'geometric') return { p: 1 / (1 + mean) };
      if (fam.id === 'negbinomial' && sd * sd > mean) return { r: mean * mean / (sd * sd - mean), p: mean / (sd * sd) };
      if (fam.id === 'binomial' && sd * sd < mean) { const p = 1 - sd * sd / mean; const n = Math.max(1, Math.round(mean / p)); return { n, p: Math.min(1, mean / n) }; }
    } catch (e) { /* defaults */ }
  }
  return p0;
}

function setFamily(d, value) {
  const prev = (derived.get(d.id) || {}).D || null;
  if (value.startsWith('kind:')) {
    const kind = value.slice(5);
    if (kind === d.kind) return;
    d.kind = kind;
    if (kind === 'empirical' && !(d.data && d.data.length) && prev) {
      /* a start: a sample of the distribution as it was */
      const n = 200;
      d.data = Array.from({ length: n }, (_, i) => +prev.quantile((i + 0.5) / n).toPrecision(8));
      d.dataLabel = 'percentiles of the previous distribution';
    }
    if (kind === 'mc' && !d.mc.expr) {
      const others = state.dists.filter((x) => x.id !== d.id && x.kind !== 'mc').map(letterOf);
      d.mc.expr = others.length >= 2 ? `${others[0]} + ${others[1]}` : others.length ? `2 * ${others[0]}` : '';
    }
    return;
  }
  const fam = familyById(value);
  if (!fam) return;
  /* a count takes only a whole-number shift (another one is dropped); the
     new family is matched to the values before the shift it will have */
  const famShift = fam.kind === 'discrete' && !Number.isInteger(shiftOf(d)) ? 0 : shiftOf(d);
  if (famShift !== shiftOf(d)) d.shift = '';
  const params = matchFamily(fam, prev, famShift);
  d.kind = 'family';
  d.family = fam.id;
  const par = parameterisationsOf(fam)[0];
  d.param = par.id;
  d.values = { [par.id]: valuesFor(par, params) };
  d.known = [];
  d._lastParams = params;
  if (d.fitInfo) d.fitInfo = null;
}

function setParam(d, id) {
  const fam = familyById(d.family);
  const pars = parameterisationsOf(fam);
  const par = pars.find((p) => p.id === id);
  if (!par) return;
  const params = currentParams(d) || d._lastParams || fam.defaults;
  d.param = par.id;
  if (par.id === KNOWN) {
    const store = {};
    for (const key of fixedKeys(fam)) store[key] = fmtField(params[key]);
    d.values[KNOWN] = store;
    const shift = shiftOf(d);
    if (!d.known.length || d.known.length !== fam.free.keys.length) { d.known = defaultKnownRows(fam, params, shift); return; }
    /* rows typed before are kept while they still give this distribution;
       otherwise they keep their properties and take this distribution's
       values, so that the switch moves nothing */
    if (!knownRowsGive(fam, d.known, store, params, shift)) for (let i = 0; i < d.known.length; i++) d.known[i].value = knownValue(fam, params, d.known[i], shift);
    return;
  }
  /* What was typed under this parameterisation comes back when it still
     describes the distribution (to nine figures): going from GM and GSD to
     mean and SD and back shows the 10 typed, not the 9.99999999995 that
     twelve-figure fields would give. */
  const kept = d.values[par.id];
  if (kept && sameParams(fam, par, kept, params)) return;
  d.values[par.id] = valuesFor(par, params, kept);
}

function sameParams(fam, par, values, params) {
  const v = {};
  for (const f of par.fields) {
    const x = parseNum(values[f.key]);
    if (!Number.isFinite(x)) return false;
    v[f.key] = x;
  }
  let p;
  try { p = par.to(v); } catch (e) { return false; }
  return fam.params.every((def) => {
    const a = p[def.key];
    const b = params[def.key];
    if (a === undefined) return true;
    return Math.abs(a - b) <= 1e-9 * Math.max(Math.abs(a), Math.abs(b), 1e-300);
  });
}

/* Known values to start from: percentiles that span the distribution, filled
   in from it. A symmetric family's three would not fix its shape (the t's ν),
   so it gets the median and two upper percentiles. */
function defaultKnownRows(fam, params, shift = 0) {
  const k = fam.free.keys.length;
  const plan = fam.id === 'studentt' ? [['median'], ['q', 75], ['q', 99]]
    : k === 1 ? [['median']] : k === 2 ? [['median'], ['q', 95]] : k === 3 ? [['q', 5], ['median'], ['q', 95]] : [['q', 5], ['q', 25], ['q', 75], ['q', 95]];
  return plan.map(([prop, p]) => {
    const row = { prop, p: p !== undefined ? String(p) : '', value: '' };
    row.value = knownValue(fam, params, row, shift);
    return row;
  });
}

/* A known-value row's value in the distribution with these parameters (and shift), as a field shows it. */
function knownValue(fam, params, row, shift = 0) {
  let D;
  try { D = makeDistribution({ family: fam.id, params, shift }); } catch (e) { return ''; }
  const st = D.stats();
  const p = parseNum(row.p);
  const v = row.prop === 'q' ? (p > 0 && p < 100 ? D.quantile(p / 100) : NaN)
    : { mean: st.mean, median: st.median, mode: st.mode, sd: st.sd, var: st.variance, cv: st.cv, gm: st.gm, gsd: st.gsd }[row.prop];
  return fmtField(v);
}

/* Whether known-value rows solve to these parameters (to nine figures). */
function knownRowsGive(fam, rows, store, params, shift = 0) {
  const parsed = [];
  for (const r of rows) {
    const value = parseNum(r.value);
    const p = parseNum(r.p);
    if (!Number.isFinite(value) || (r.prop === 'q' && !(p > 0 && p < 100))) return false;
    parsed.push(r.prop === 'q' ? { prop: 'q', p, value } : { prop: r.prop, value });
  }
  const fixed = {};
  for (const key of fixedKeys(fam)) fixed[key] = parseNum(store[key]);
  let got;
  try { got = solveKnownCached(fam, parsed, fixed, params, shift); } catch (e) { return false; }
  return fam.free.keys.every((key) => Math.abs(got[key] - params[key]) <= 1e-9 * Math.max(Math.abs(got[key]), Math.abs(params[key]), 1e-300));
}

function refillKnown(d, i) {
  const r = (derived.get(d.id) || {});
  if (!r.D || !r.D.params) return;
  d.known[i].value = knownValue(familyById(d.family), r.D.params, d.known[i], r.D.shift || 0);
}

/* ---- the refresh ------------------------------------------------------------------------------------ */

let refreshTimer = null;
function refreshSoon() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => refresh(), 90);
}

export function refresh({ editor = false } = {}) {
  clearTimeout(refreshTimer);
  recompute();
  renderList();
  if (editor) renderEditor(); else updateEditorState();
  renderPane();
  saveSoon();
  if (typeof KvotInfo !== 'undefined') KvotInfo.refresh();
}

/* ---- the panes ---------------------------------------------------------------------------------------- */

let fitPanel = null;
let calcPanel = null;
let samplePanel = null;
let helpBuilt = false;

function renderPane() {
  const tab = state.tab;
  for (const b of document.querySelectorAll('.ds-tabs [data-tab]')) {
    const on = b.dataset.tab === tab;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', String(on));
  }
  for (const p of document.querySelectorAll('.ds-pane')) p.hidden = p.id !== `pane-${tab}`;
  if (tab === 'chart') drawCharts();
  else if (tab === 'stats') renderStatsTable($('dsStatsTable'), items(), statsSettings());
  else if (tab === 'fit' && fitPanel) fitPanel.render();
  else if (tab === 'calc' && calcPanel) calcPanel.render();
  else if (tab === 'sample' && samplePanel) samplePanel.render();
  else if (tab === 'help' && !helpBuilt) { helpBuilt = true; buildHelp($('dsHelpFamilies')); }
  /* the draws follow the distributions, while anything shows them */
  if (samplePanel) samplePanel.update();
}

function chartSettings() {
  const c = state.chart;
  return {
    logx: !!c.logx, logy: !!c.logy, showData: !!c.showData, showSamples: !!c.showSamples, bins: c.bins,
    pmin: Number.isFinite(parseNum(c.pmin)) ? parseNum(c.pmin) : 0.1,
    pmax: Number.isFinite(parseNum(c.pmax)) ? parseNum(c.pmax) : 99.9,
    xmin: String(c.xmin).trim() === '' ? NaN : parseNum(c.xmin),
    xmax: String(c.xmax).trim() === '' ? NaN : parseNum(c.xmax),
  };
}

function statsSettings() {
  const pcts = parseNumberList(state.stats.percentiles).values.filter((p) => p > 0 && p < 100);
  return { digits: Number(state.stats.digits) || 5, percentiles: pcts };
}

function shading() {
  const c = state.calc;
  if (!c.shade) return null;
  const a = parseNum(c.a);
  const b = parseNum(c.b);
  return Number.isFinite(a) && Number.isFinite(b) && b > a && state.active ? { key: state.active, a, b } : null;
}

function drawCharts() {
  const its = items();
  const s = chartSettings();
  const th = theme();
  const visible = its.filter((it) => it.visible && it.D);
  $('dsChartEmpty').hidden = visible.length > 0;
  const plots = [['dsPlotTop', state.chart.top], ['dsPlotBottom', state.chart.bottom]];
  for (const [id, fn] of plots) {
    const div = $(id);
    if (fn === 'none' || !visible.length) {
      div.hidden = true;
      if (div.data) Plotly.purge(div);
      continue;
    }
    div.hidden = false;
    const fig = figure(its, fn, s, th, { shade: fn === 'pdf' ? shading() : null });
    Plotly.react(div, fig.data, fig.layout, PLOT_CONFIG);
    if (!div._dsLegend) {
      div._dsLegend = true;
      div.on('plotly_legendclick', (ev) => {
        const trace = ev.data[ev.curveNumber];
        const d = trace && distById(trace.legendgroup);
        if (d) { d.visible = !d.visible; refresh(); }
        return false;
      });
      div.on('plotly_legenddoubleclick', () => false);
    }
  }
  const notes = [];
  if (s.logx && visible.some((it) => it.D.support[0] < 0)) notes.push('A logarithmic x-axis shows only the positive part of a distribution that reaches below zero.');
  if (visible.some((it) => it.D.kind === 'discrete') && visible.some((it) => it.D.kind === 'continuous') && (state.chart.top === 'pdf' || state.chart.bottom === 'pdf')) notes.push('Stems are probabilities, curves densities: comparable where the values are one apart.');
  $('dsChartNote').textContent = notes.join(' ');
  renderStrip();
}

/* The main numbers of every distribution the chart shows, under it, and of
   each one's draws where the chart shows them too; the selected one in bold. */
function renderStrip() {
  const strip = $('dsStrip');
  strip.replaceChildren();
  const its = items().filter((it) => it.visible && it.D);
  if (!its.length) return;
  const digits = statsSettings().digits;
  const th = theme();
  const table = el('table', { class: 'ds-table ds-below', id: 'dsBelowTable' });
  const head = table.createTHead().insertRow();
  for (const label of ['', 'Mean', 'SD', 'Median', 'Mode', '5th percentile', '95th percentile']) head.append(el('th', { text: label }));
  const body = table.createTBody();
  for (const it of its) {
    const st = it.D.stats();
    const { colour, dash } = slotStyle(it.slot, th);
    const key = el('span', { class: 'ds-key' + (dash === 'dash' ? ' dashed' : '') });
    key.style.setProperty('--ds-colour', colour);
    const tr = body.insertRow();
    if (it.key === state.active) tr.classList.add('active');
    tr.insertCell().append(key, document.createTextNode(it.name));
    for (const v of [fmtStat(st.mean, digits), fmtStat(st.sd, digits), fmt(st.median, digits), st.modeText || fmt(st.mode, digits), fmt(it.D.quantile(0.05), digits), fmt(it.D.isf(0.05), digits)]) tr.insertCell().textContent = v;
    const sm = samplePanel ? samplePanel.summaryFor(it.key, it.letter) : null;
    if (sm) {
      const dr = body.insertRow();
      dr.className = 'ds-below-draws';
      const k2 = el('span', { class: 'ds-key dotted' });
      k2.style.setProperty('--ds-colour', colour);
      dr.insertCell().append(k2, document.createTextNode(`its ${sm.n.toLocaleString('en')} draws (${SCHEME_SHORT[state.sample.scheme] || state.sample.scheme})`));
      for (const v of [fmt(sm.mean, digits), fmt(sm.sd, digits), fmt(sm.q[2], digits), '—', fmt(sm.q[1], digits), fmt(sm.q[3], digits)]) dr.insertCell().textContent = v;
    }
  }
  strip.append(el('div', { class: 'ds-table-wrap' }, table));
}

/* ---- actions ----------------------------------------------------------------------------------------------- */

function addDist(d) {
  if (!d) { status(`At most ${MAX_DISTS} distributions.`, 'error'); return null; }
  state.dists.push(d);
  state.dists.sort((a, b) => a.slot - b.slot);
  state.active = d.id;
  refresh({ editor: true });
  return d;
}

/** A new distribution from a fit or a sample, for the other panels. */
export function addFromPanel(make) {
  const d = blankDist('family');
  if (!d) { status(`At most ${MAX_DISTS} distributions. Remove one first.`, 'error'); return null; }
  make(d);
  return addDist(d);
}

registerActions({
  'ds:tab': (ev, b) => { state.tab = b.dataset.tab; renderPane(); saveSoon(); },
  'ds:select': (ev, b) => { if (state.active !== b.dataset.id) { state.active = b.dataset.id; refresh({ editor: true }); } },
  'ds:toggleVisible': (ev, b) => { const d = distById(b.dataset.id); if (d) { d.visible = !d.visible; refresh(); } },
  'ds:remove': (ev, b) => {
    const i = state.dists.findIndex((d) => d.id === b.dataset.id);
    if (i < 0) return;
    const [gone] = state.dists.splice(i, 1);
    if (state.active === gone.id) state.active = state.dists.length ? state.dists[Math.min(i, state.dists.length - 1)].id : null;
    status(`${fullName(gone)} removed.`);
    refresh({ editor: true });
  },
  'ds:add': () => {
    const src = activeDist();
    const d = blankDist('family', 'normal');
    if (!d) return addDist(null);
    /* a normal with the mean and SD of the selected distribution, so that it starts near it */
    const D = src ? (derived.get(src.id) || {}).D : null;
    if (D) {
      const st = D.stats();
      if (Number.isFinite(st.mean) && st.sd > 0 && Number.isFinite(st.sd)) d.values = { 'mu-sigma': { mu: fmtField(st.mean), sigma: fmtField(st.sd) } };
    }
    addDist(d);
  },
  'ds:duplicate': () => {
    const src = activeDist();
    if (!src) return;
    const d = blankDist();
    if (!d) return addDist(null);
    const copy = JSON.parse(JSON.stringify(src));
    addDist({ ...copy, id: d.id, slot: d.slot, name: src.name ? `${src.name} (copy)` : '' });
  },
  'ds:edit': (ev, input) => {
    const d = activeDist();
    if (!d) return;
    const path = input.dataset.path;
    setPath(d, path, input.type === 'checkbox' ? input.checked : input.value);
    if (path === 'name') { renderList(); updateEditorState(); saveSoon(); refreshSoon(); return; }
    refreshSoon();
  },
  'ds:truncBy': (ev, input) => {
    const d = activeDist();
    if (!d || d.trunc.by === input.value) return;
    const had = String(d.trunc.lo).trim() !== '' || String(d.trunc.hi).trim() !== '';
    const conv = convertTrunc(d, input.value);
    /* What was typed under the other choice comes back while it still gives
       these bounds (to nine figures): percentiles to values and back shows
       the 25 typed, not the 24.9999999999 that twelve-figure fields give. */
    const same = (a, b) => {
      const x = String(a ?? '').trim();
      const y = String(b ?? '').trim();
      if (!x || !y) return !x && !y;
      const u = parseNum(x);
      const v = parseNum(y);
      return Number.isFinite(u) && Number.isFinite(v) && Math.abs(u - v) <= 1e-9 * Math.max(Math.abs(u), Math.abs(v), 1e-300);
    };
    const kept = d.trunc.kept;
    const next = kept && kept.by === input.value && same(kept.lo, conv.lo) && same(kept.hi, conv.hi) ? { lo: kept.lo, hi: kept.hi } : conv;
    d.trunc = { ...next, by: input.value, kept: { by: d.trunc.by, lo: d.trunc.lo, hi: d.trunc.hi } };
    if (had && !conv.lo && !conv.hi && !(derived.get(d.id) || {}).D) status('The bounds could not be read as the other kind while the distribution has an error; give them again.', 'error');
    refresh({ editor: true });
  },
  'ds:editStructure': (ev, input) => {
    const d = activeDist();
    if (!d) return;
    setPath(d, input.dataset.path, input.type === 'checkbox' ? input.checked : input.value);
    refresh({ editor: true });
  },
  'ds:setFamily': (ev, sel) => { const d = activeDist(); if (d) { setFamily(d, sel.value); refresh({ editor: true }); } },
  'ds:setParam': (ev, sel) => { const d = activeDist(); if (d) { setParam(d, sel.value); refresh({ editor: true }); } },
  'ds:editKnownProp': (ev, sel) => {
    const d = activeDist();
    if (!d) return;
    const i = Number(sel.dataset.path.split('.')[1]);
    d.known[i].prop = sel.value;
    if (sel.value === 'q' && !d.known[i].p) d.known[i].p = '50';
    refillKnown(d, i);
    refresh({ editor: true });
  },
  'ds:empData': (ev, ta) => {
    const d = activeDist();
    if (!d) return;
    const { values } = parseNumberList(ta.value);
    d.data = values;
    d.dataLabel = '';
    refreshSoon();
  },
  'ds:detachData': () => { const d = activeDist(); if (d) { d.data = null; d.dataLabel = ''; d.fitInfo = null; refresh({ editor: true }); } },
  'ds:chartSetting': () => {
    const c = state.chart;
    c.top = $('dsTop').value;
    c.bottom = $('dsBottom').value;
    c.logx = $('dsLogX').checked;
    c.logy = $('dsLogY').checked;
    c.showData = $('dsShowData').checked;
    c.showSamples = $('dsShowSamples').checked;
    if (samplePanel) samplePanel.syncShow();
    c.bins = { rule: $('dsBins').value, value: $('dsBinsValue').value };
    syncBinsField($('dsBins'), $('dsBinsValue'), c.bins);
    c.pmin = $('dsPmin').value;
    c.pmax = $('dsPmax').value;
    c.xmin = $('dsXmin').value;
    c.xmax = $('dsXmax').value;
    const bad = (id, v, ok) => $(id).setAttribute('aria-invalid', ok(v) ? 'false' : 'true');
    bad('dsPmin', parseNum(c.pmin), (v) => v > 0 && v < 50);
    bad('dsPmax', parseNum(c.pmax), (v) => v > 50 && v < 100);
    bad('dsXmin', c.xmin, (v) => String(v).trim() === '' || Number.isFinite(parseNum(v)));
    bad('dsXmax', c.xmax, (v) => String(v).trim() === '' || Number.isFinite(parseNum(v)));
    drawCharts();
    /* samples just asked for are drawn: what the chart lacks comes after a pause */
    if (samplePanel) samplePanel.update();
    saveSoon();
    KvotInfo.refresh();
  },
  'ds:curvesCsv': () => {
    const rows = curveRows(items(), state.chart.top, chartSettings());
    download('distribution-curves.csv', csvText(rows));
  },
  'ds:statsSetting': () => {
    state.stats.digits = Number($('dsDigits').value);
    state.stats.percentiles = $('dsPercentiles').value;
    renderStatsTable($('dsStatsTable'), items(), statsSettings());
    saveSoon();
  },
  'ds:statsCsv': () => download('distribution-statistics.csv', csvText(statsCsvRows(items(), statsSettings()))),
  'ds:reset': (ev) => {
    ev.preventDefault();
    if (!window.confirm('Start again? Every distribution, the data and the settings on this page are cleared.')) return;
    try { localStorage.removeItem(STORAGE_KEY); } catch (e) { /* nothing kept */ }
    state = initialState();
    exampleDists();
    mcRuns.clear();
    applySettingsToControls();
    if (fitPanel) fitPanel.reset();
    if (samplePanel) samplePanel.reset();
    refresh({ editor: true });
    status('Started again.');
  },
  'ds:helpLink': (ev, a) => {
    ev.preventDefault();
    const id = a.getAttribute('href').slice(1);
    const h = document.getElementById(id);
    if (h) h.scrollIntoView({ block: 'start' });
  },
});

/* ---- the column's width ---------------------------------------------------------------------------------- */

function setupResize() {
  const handle = $('dsResize');
  const root = $('dsRoot');
  const apply = (w) => { root.style.setProperty('--ds-side-width', `${w}px`); };
  if (state.sideWidth) apply(state.sideWidth);
  let start = null;
  handle.addEventListener('pointerdown', (ev) => {
    start = { x: ev.clientX, w: $('dsSide').getBoundingClientRect().width };
    handle.setPointerCapture(ev.pointerId);
    handle.classList.add('active');
  });
  handle.addEventListener('pointermove', (ev) => {
    if (!start) return;
    const w = Math.min(Math.max(250, start.w + ev.clientX - start.x), Math.max(300, window.innerWidth * 0.6));
    apply(w);
    state.sideWidth = w;
  });
  const end = () => { if (start) { start = null; handle.classList.remove('active'); saveSoon(); window.dispatchEvent(new Event('resize')); } };
  handle.addEventListener('pointerup', end);
  handle.addEventListener('pointercancel', end);
  handle.addEventListener('keydown', (ev) => {
    if (ev.key !== 'ArrowLeft' && ev.key !== 'ArrowRight') return;
    ev.preventDefault();
    const w = $('dsSide').getBoundingClientRect().width + (ev.key === 'ArrowLeft' ? -20 : 20);
    state.sideWidth = Math.min(Math.max(250, w), window.innerWidth * 0.6);
    apply(state.sideWidth);
    saveSoon();
    window.dispatchEvent(new Event('resize'));
  });
}

/* ---- boot --------------------------------------------------------------------------------------------------- */

function applySettingsToControls() {
  const c = state.chart;
  $('dsTop').value = c.top;
  $('dsBottom').value = c.bottom;
  $('dsLogX').checked = !!c.logx;
  $('dsLogY').checked = !!c.logy;
  $('dsShowData').checked = !!c.showData;
  $('dsShowSamples').checked = !!c.showSamples;
  fillBins($('dsBins'), $('dsBinsValue'), c.bins);
  $('dsPmin').value = c.pmin;
  $('dsPmax').value = c.pmax;
  $('dsXmin').value = c.xmin;
  $('dsXmax').value = c.xmax;
  $('dsDigits').value = String(state.stats.digits);
  $('dsPercentiles').value = state.stats.percentiles;
}

/** What the other panels need of the page. */
export const app = {
  get state() { return state; },
  items, refresh, status, saveSoon, addFromPanel, runJob, stopJobs, theme, letterOf, distName, fullName,
  activeDist, distById, derived: (id) => derived.get(id) || {}, supportText, fmtStat,
  redraw: () => renderPane(),
  /** Samples in the chart, on or off, from either place that sets it. */
  setShowSamples(on) {
    state.chart.showSamples = !!on;
    $('dsShowSamples').checked = !!on;
    if (samplePanel) samplePanel.syncShow();
    saveSoon();
    renderPane();
  },
};

function boot() {
  if (!load()) exampleDists();
  if (!state.dists.length) exampleDists();
  /* a stored state the page cannot start from is put aside, not left to stop it */
  const restart = () => {
    state = initialState();
    exampleDists();
    try { localStorage.removeItem(STORAGE_KEY); } catch (e) { /* nothing kept */ }
  };
  try { applySettingsToControls(); } catch (e) { restart(); applySettingsToControls(); }
  setupResize();
  KvotInfo.setup({
    topics: infoTopics(app),
    onMore: () => { state.tab = 'help'; renderPane(); },
  });
  let fresh = false;
  try {
    fitPanel = setupFit(app);
    calcPanel = setupCalc(app);
    samplePanel = setupSample(app);
    refresh({ editor: true });
  } catch (e) {
    restart();
    applySettingsToControls();
    if (!fitPanel) fitPanel = setupFit(app); else fitPanel.reset();
    if (!calcPanel) calcPanel = setupCalc(app);
    if (!samplePanel) samplePanel = setupSample(app); else samplePanel.reset();
    refresh({ editor: true });
    fresh = true;
  }
  app.fitPanel = fitPanel;
  if (fresh) status('What this browser had kept for the page could not be read; the page started again.', 'error');
  document.documentElement.addEventListener('kvot-theme-change', () => { renderList(); renderPane(); });
  window.addEventListener('resize', () => {
    for (const id of ['dsPlotTop', 'dsPlotBottom', 'dsFitPlot']) {
      const div = $(id);
      if (div && div.data && !div.hidden && div.offsetParent) Plotly.Plots.resize(div);
    }
  });
}

boot();
