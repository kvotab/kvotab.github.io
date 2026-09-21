#!/usr/bin/env node
/*
  Runs the browser model engine of facsimile.html under Node and compares it
  with the Python port's results (ref/py_<scenario>.csv, subsampled from
  Scenario_<scenario>_python.xlsx) and, for 13g, with the FACSIMILE output.

    node resources/tests/facsimile/run.js               # Jacobian check + 13g
    node resources/tests/facsimile/run.js 13g 16a 1     # chosen scenarios
    node resources/tests/facsimile/run.js --all

  The comparison is at the reference's own output times (linear interpolation
  of this engine's steps) and reports, per quantity, the largest relative
  difference over the rows where the reference is above a floor.
*/
'use strict';
const fs = require('fs');
const path = require('path');

const here = __dirname;
const jsDir = path.join(here, '..', '..', 'js');
const FacsimileModel = require(path.join(jsDir, 'facsimile-model.js'));
const FacsimileODE = require(path.join(jsDir, 'facsimile-solver.js'));
const FacsimileHDF5 = require(path.join(jsDir, 'facsimile-hdf5.js'));
const { FACSIMILE_DEFAULT_MODEL, FACSIMILE_PRESETS } = require(path.join(jsDir, 'facsimile-default.js'));

const args = process.argv.slice(2);
const opt = { solver: 'ndf', rtol: null, atol: 1e-30, matrix: 'auto', jacobian: 'analytic', nonneg: true, all: false, quiet: false, norm: 'max', maxOrder: 5 };
const scenarios = [];
let speciesAtol = null;
for (let i = 0; i < args.length; i++) {
  const a = args[i];
  if (a === '--all') opt.all = true;
  else if (a === '--solver') opt.solver = args[++i];
  else if (a === '--rtol') opt.rtol = parseFloat(args[++i]);
  else if (a === '--atol') opt.atol = parseFloat(args[++i]);
  else if (a === '--matrix') opt.matrix = args[++i];
  else if (a === '--jacobian') opt.jacobian = args[++i];
  else if (a === '--nonneg') opt.nonneg = true;
  else if (a === '--no-nonneg') opt.nonneg = false;
  else if (a === '--norm') opt.norm = args[++i];
  else if (a === '--maxorder') opt.maxOrder = parseInt(args[++i], 10);
  else if (a === '--noscaling') opt.scaling = false;
  else if (a === '--hmax') opt.hmax = parseFloat(args[++i]);
  else if (a === '--minnewton') opt.minNewton = parseInt(args[++i], 10);
  else if (a === '--belowtol') opt.belowTolRun = parseInt(args[++i], 10);
  else if (a === '--autoatol') opt.autoAtol = true;
  // Repeatable, and a single argument may carry several: --atolspecies "H2O 1e-12, OH 1e-22"
  else if (a === '--atolspecies') opt.atolSpecies = (opt.atolSpecies || '') + '\n' + args[++i];
  // Any setting, by name: --set H2OPAIR=1 runs the case with FACSIMILE's
  // evaporation/condensation pair instead of the saturation substitution.
  else if (a === '--set') { const [k, v] = String(args[++i]).split('='); (opt.set ||= {})[k] = Number(v); }
  else if (a === '--debug') opt.debugFrom = parseFloat(args[++i]);
  else if (a === '--quiet') opt.quiet = true;
  else if (a === '--h5') opt.h5 = args[++i];
  // The model's own <TIMES> grid: written to CSV, or left unbuilt.
  else if (a === '--times') opt.times = args[++i];
  // Which reference to compare against: python, facsimile, or both (default).
  else if (a === '--ref') opt.ref = String(args[++i]).toLowerCase();
  else if (a === '--no-times') opt.noTimes = true;
  else scenarios.push(a);
}
if (opt.atolSpecies) {
  const parsed = FacsimileODE.parseSpeciesTolerances(opt.atolSpecies);
  if (parsed.errors.length) { console.error('--atolspecies: ' + parsed.errors.join('; ')); process.exit(2); }
  speciesAtol = parsed.values;
  console.log('per-species atol: ' + Object.keys(speciesAtol).map((k) => `${k}=${speciesAtol[k]}`).join(' '));
}
if (opt.all) FACSIMILE_PRESETS.forEach((p) => { if (!scenarios.includes(p.id) && p.id !== '13g-fac') scenarios.push(p.id); });
if (!scenarios.length) scenarios.push('13g');

function readCsv(file) {
  const lines = fs.readFileSync(file, 'utf8').trim().split(/\r?\n/);
  const header = lines[0].split(',');
  const rows = lines.slice(1).map((l) => l.split(',').map(Number));
  const col = {};
  header.forEach((h, k) => { col[h] = rows.map((r) => r[k]); });
  return { header, rows, col, n: rows.length };
}

function interpAt(T, series, tq) {
  // T increasing; linear interpolation, clamped
  let lo = 0, hi = T.length - 1;
  if (tq <= T[0]) return series[0];
  if (tq >= T[hi]) return series[hi];
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (T[mid] <= tq) lo = mid; else hi = mid; }
  const f = (tq - T[lo]) / (T[hi] - T[lo]);
  return series[lo] + f * (series[hi] - series[lo]);
}

// --- compile once and check the Jacobian ------------------------------------
const preset13g = FACSIMILE_PRESETS.find((p) => p.id === '13g');
let model = FacsimileModel.compile(FACSIMILE_DEFAULT_MODEL, { settings: preset13g.settings });
console.log(`model: ${model.nspecies} species, ${model.reactions.length} reactions, Jacobian nnz ${model.nnz} (${(100 * model.density).toFixed(1)}% dense), ${model.equations.length} equations, ${model.outputs.length} outputs`);
if (model.warnings.length) console.log('warnings: ' + model.warnings.join('; '));
{
  const y0 = model.initialState(0);
  const check0 = model.verifyJacobian(0, y0);
  // A state with every species present, to exercise every entry of the pattern.
  const y1 = Float64Array.from(y0, (v, i) => (v > 0 ? v : 1e-12 * (1 + (i % 7))));
  const check1 = model.verifyJacobian(3e7, y1);
  const fmt = (c) => `${c.checked} resolvable entries checked, ${c.discrepancies.length} discrepancies` + (c.discrepancies.length ? ' -- worst: ' + c.discrepancies.slice(0, 3).map((d) => `d f[${d.row}]/d ${d.col} analytic ${d.analytic.toExponential(4)} numeric ${d.numeric.toExponential(4)}`).join('; ') : '') + (c.outsidePattern ? `; numeric entry outside the pattern at (${c.outsidePattern.row}, ${c.outsidePattern.col}) = ${c.outsidePattern.numeric.toExponential(2)}` : '; nothing outside the pattern');
  console.log('Jacobian check at t=0, y0:        ' + fmt(check0));
  console.log('Jacobian check at t=1 year, y>0:  ' + fmt(check1));
  const groups = FacsimileODE.colourColumns(model.pattern);
  console.log(`column colouring: ${groups.length} groups (a differenced Jacobian would cost ${groups.length} evaluations instead of ${model.nspecies})`);
}

// --- scenarios --------------------------------------------------------------
const compareCols = ['PRESSP', 'H2OTOTAL', 'H2ORH', 'O2MOL', 'H2MOL', 'HNO3MOL', 'HNO2MOL', 'H2O2MOL', 'N2MOL', 'NH3MOL', 'H2OMOL'];
const floors = { PRESSP: 1e-3, H2OTOTAL: 1e-3, H2ORH: 1e-3, O2MOL: 1e-6, H2MOL: 1e-6, HNO3MOL: 1e-9, HNO2MOL: 1e-9, H2O2MOL: 1e-9, N2MOL: 1e-6, NH3MOL: 1e-6, H2OMOL: 1e-6 };

let failures = 0;
for (const id of scenarios) {
  const preset = FACSIMILE_PRESETS.find((p) => p.id === id);
  if (!preset) { console.log(`\n${id}: no preset`); failures++; continue; }
  // Two references where both exist: the Python port, which this engine was
  // written against, and SKB's own delivered FACSIMILE result for the same
  // case, which is the model's own answer and the one that settles a
  // disagreement. scripts/gen-facsimile-ref.py writes the second from the
  // study's workbooks.
  const refs = [];
  for (const [label, file] of [
    ['Python port', `py_${id}.csv`],
    ['FACSIMILE', `fac_${id}.csv`],
    // The .prn run that came with the model, kept under its own name.
    ...(id === '13g-fac' ? [['FACSIMILE .prn', 'fac_13g_pcair003.csv']] : []),
  ]) {
    const full = path.join(here, 'ref', file);
    if (fs.existsSync(full) && !(opt.ref && opt.ref !== label.split(' ')[0].toLowerCase())) {
      refs.push({ label, file, data: readCsv(full) });
    }
  }
  const ref = refs.length ? refs[0].data : null;
  model = FacsimileModel.compile(FACSIMILE_DEFAULT_MODEL, { settings: { ...preset.settings, ...(opt.set || {}) } });
  const rtol = opt.rtol || preset.solver.rtol || 1e-5;
  const t0 = Date.now();
  let res;
  try {
    res = FacsimileODE.runModel(model, {
      solver: opt.solver, tend: preset.settings.TEND * 365.25 * 86400, rtol, atol: opt.atol,
      matrix: opt.matrix, jacobianMode: opt.jacobian, nonNegative: opt.nonneg, norm: opt.norm, maxOrder: opt.maxOrder, scaling: opt.scaling, hmax: opt.hmax, minNewton: opt.minNewton,
      belowTolRun: opt.belowTolRun, autoAtol: opt.autoAtol, atolSpecies: speciesAtol,
      outputTimes: opt.noTimes ? new Float64Array(0) : undefined,
      debug: opt.debugFrom !== undefined ? (d) => {
        if (d.t < opt.debugFrom) return;
        const names = (top) => top.map(([i, v]) => `${model.species[i]}:${v.toExponential(2)} y=${d.y[i].toExponential(2)} ynew=${d.ynew[i].toExponential(2)}`).join(' | ');
        if (d.errTest !== undefined) console.log(`  ERR  t=${d.t.toExponential(8)} h=${d.h.toExponential(3)} k=${d.k} err/rtol=${(d.errTest / rtol).toExponential(2)} :: ${names(d.top)}`);
        else console.log(`  NEWT t=${d.t.toExponential(8)} h=${d.h.toExponential(3)} k=${d.k} its=${d.newtonIts} norms=[${d.newtonNorms.map((v) => v.toExponential(2)).join(',')}] jacFresh=${d.jacobianFresh} nonfinite=${d.nonfinite} :: ${names(d.top)}`);
      } : undefined,
    });
  } catch (e) {
    console.log(`\n${id}: FAILED ${e.message}`);
    if (e.trace) {
      console.log('  last accepted steps (t s, h s, order, err/rtol, newton its, failed attempts):');
      e.trace.forEach((s) => console.log(`    t=${s.t.toExponential(6)} h=${s.h.toExponential(3)} k=${s.k ?? '-'} err=${(s.err / rtol).toExponential(2)} newton=${s.newton ?? '-'} failed=${s.failed}`));
    }
    if (e.lastY) {
      const obs = model.observe(e.lastT, e.lastY);
      const show = ['TIMH', 'TMP', 'H2ORH', 'H2ORHOFF', 'f1', 'f2', 'O2MOL', 'H2MOL', 'H2OTOTAL', 'H2OEQ', 'c1', 'c2', 'dDUMH2'];
      console.log('  state there: ' + show.map((nm) => `${nm}=${obs[model.observeNames.indexOf(nm)].toExponential(4)}`).join(' '));
      const worst = Array.from(e.lastY).map((v, i) => [model.species[i], v]).filter(([, v]) => v < 0);
      if (worst.length) console.log('  negative species: ' + worst.map(([nm, v]) => `${nm}=${v.toExponential(2)}`).join(' '));
    }
    failures++;
    continue;
  }
  const s = res.stats;
  console.log(`\n${id}: ${preset.label}`);
  console.log(`  ${s.solver} rtol ${rtol} atol ${opt.atol}: ${s.nsteps} steps, ${s.nfailed} failed, ${s.nfevals} f-evals, ${s.npds} Jacobians, ${s.ndecomps} LU, ${s.nsolves} solves, ${s.segments} segment(s), ${(Date.now() - t0) / 1000} s; iteration matrix ${s.sparse ? 'sparse' : 'dense'} (fill ${s.fill}, ${s.ordering})`);
  res.events.forEach((ev) => console.log(`  event at t = ${(ev.t / 3600).toFixed(4)} h: ${
    ev.stop ? `the run stopped here${ev.changed.length ? ` (${ev.changed.join(', ')})` : ''}` : ev.changed.join(', ')}`));
  if (res.grid) console.log(`  output grid: ${res.grid.t.length} of the ${res.grid.wanted} times the model asks for`);
  // Observables at every stored step
  const names = model.observeNames;
  const idx = {};
  names.forEach((nm, k) => { idx[nm] = k; });
  const obs = new Float64Array(names.length);
  const series = {};
  compareCols.forEach((c) => { series[c] = new Float64Array(res.t.length); });
  for (let k = 0; k < res.t.length; k++) {
    model.observe(res.t[k], res.y[k], obs);
    compareCols.forEach((c) => { series[c][k] = obs[idx[c]]; });
  }
  const TIMH = Array.from(res.t, (v) => v / 3600);
  const last = res.t.length - 1;

  // The same file the page hands to the HDF5 Browser, written to disk so the
  // real library can be asked whether it is one. See test-hdf5.py.
  if (opt.h5) {
    const width = names.length;
    const observed = new Float64Array(res.t.length * width);
    const states = new Float64Array(res.t.length * model.nspecies);
    const row = new Float64Array(width);
    for (let k = 0; k < res.t.length; k++) {
      model.observe(res.t[k], res.y[k], row);
      observed.set(row, k * width);
      states.set(res.y[k], k * model.nspecies);
    }
    const run = {
      t: res.t, states, observed, n: res.t.length, nspecies: model.nspecies,
      species: model.species, observeNames: names, events: res.events, stats: res.stats,
      constants: model.constantValues(), seconds: res.stats.seconds,
    };
    const bytes = FacsimileHDF5.resultFile(run, model, {
      reference: preset.reference || '',
      scenario: id, text: FACSIMILE_DEFAULT_MODEL,
      solver: { method: opt.solver, rtol, atol: opt.atol, atolSpecies: speciesAtol || {}, norm: opt.norm, maxOrder: opt.maxOrder, nonNegative: opt.nonneg, clamp: true, jacobianMode: opt.jacobian },
    });
    const out = scenarios.length > 1 ? opt.h5.replace(/(\.h5)?$/i, `_${id}.h5`) : opt.h5;
    fs.writeFileSync(out, bytes);
    console.log(`  wrote ${out}: ${(bytes.length / 1024).toFixed(0)} kB of HDF5`);
  }
  if (opt.times && res.grid && res.grid.t.length) {
    const row = new Float64Array(names.length);
    const lines = [['TIMS', 'TIMH', ...names].join(',')];
    for (let k = 0; k < res.grid.t.length; k++) {
      model.observe(res.grid.t[k], res.grid.y[k], row);
      lines.push([res.grid.t[k], res.grid.t[k] / 3600, ...row].join(','));
    }
    const out = scenarios.length > 1 ? opt.times.replace(/(\.csv)?$/i, `_${id}.csv`) : opt.times;
    fs.writeFileSync(out, lines.join('\n'));
    console.log(`  wrote ${out}: ${res.grid.t.length} rows at the model's output times`);
  }
  console.log(`  at ${TIMH[last].toExponential(3)} h: O2 ${series.O2MOL[last].toExponential(3)} mol, H2 ${series.H2MOL[last].toExponential(4)} mol, NH3 ${series.NH3MOL[last].toExponential(4)} mol, HNO3 ${series.HNO3MOL[last].toExponential(3)} mol, water ${series.H2OTOTAL[last].toFixed(2)} g, RH ${series.H2ORH[last].toFixed(4)}, P ${series.PRESSP[last].toFixed(4)} atm`);
  if (!refs.length) { console.log('  (no reference file)'); continue; }
  const pad = (s, n) => String(s).padStart(n);
  for (const { label, file, data } of refs) {
    const rows = [];
    for (const c of compareCols) {
      if (!data.col[c]) continue;
      let worst = 0, worstT = 0, worstRef = 0, worstMine = 0, count = 0;
      // The median as well as the worst: one reference point in a sharp
      // transient can be out by a lot while the curve as a whole agrees, and
      // a single worst case cannot tell those apart.
      const all = [];
      for (let r = 0; r < data.n; r++) {
        const tq = data.col.TIMH[r];
        const rv = data.col[c][r];
        if (!(Math.abs(rv) > floors[c])) continue;
        // A reference that runs past where this engine got to is not a
        // disagreement about the answer.
        if (tq > TIMH[last] * (1 + 1e-9)) continue;
        const mv = interpAt(TIMH, series[c], tq);
        const rel = Math.abs(mv - rv) / Math.abs(rv);
        count++;
        all.push(rel);
        if (rel > worst) { worst = rel; worstT = tq; worstRef = rv; worstMine = mv; }
      }
      all.sort((a, b) => a - b);
      rows.push({ c, worst, worstT, worstRef, worstMine, count, median: all.length ? all[all.length >> 1] : 0 });
    }
    console.log(`  against the ${label} (${file}, ${data.n} rows)`);
    console.log('  quantity   rows   median  worst rel.diff   at t (h)      reference        this engine');
    for (const r of rows) {
      console.log(`  ${r.c.padEnd(10)} ${pad(r.count, 4)} ${pad(r.median.toExponential(1), 8)}  ${pad(r.worst.toExponential(2), 12)}   ${pad(r.worstT.toExponential(3), 10)}  ${pad(r.worstRef.toExponential(4), 12)}  ${pad(r.worstMine.toExponential(4), 12)}`);
    }
  }
  if (!opt.quiet) {
    console.log('  time (h)      O2 ref      O2 here      H2 ref      H2 here     NH3 ref     NH3 here   water ref  water here');
    for (let r = 0; r < ref.n; r += Math.max(1, Math.floor(ref.n / 14))) {
      const tq = ref.col.TIMH[r];
      const g = (c) => interpAt(TIMH, series[c], tq).toExponential(3).padStart(11);
      const f = (c) => Number(ref.col[c][r]).toExponential(3).padStart(11);
      console.log(`  ${tq.toExponential(3).padStart(9)} ${f('O2MOL')} ${g('O2MOL')} ${f('H2MOL')} ${g('H2MOL')} ${f('NH3MOL')} ${g('NH3MOL')} ${Number(ref.col.H2OTOTAL[r]).toFixed(2).padStart(11)} ${interpAt(TIMH, series.H2OTOTAL, tq).toFixed(2).padStart(11)}`);
    }
  }
}
process.exit(failures ? 1 : 0);
