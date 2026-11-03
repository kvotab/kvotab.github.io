/* Kompartment's designed sensitivity methods on the cases test_gsa.py hands
   it: the functions of kompartment/src/domain/gsa.js and salib.js (checked
   there against GlobalSensitivity.jl and SALib) that PyLAB's builtins/gsa.py
   ports.

     node gsa-kompartment.mjs <cases.json>

   cases.json: a list of { method, ...settings, stream: [uniforms the design
   draws, in order], y: [the outputs of PyLAB's design], and the columns and
   resample indices PyLAB drew }. Prints, per case, the design (row-major
   runs) and the indices, NaN as null. */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const domain = (f) => pathToFileURL(path.join(here, '..', '..', '..', 'kompartment', 'src', 'domain', f)).href;
const G = await import(domain('gsa.js'));
const L = await import(domain('salib.js'));

const cases = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const plain = (v) => (typeof v === 'number' && !Number.isFinite(v) ? null : v);
const list = (a) => (a == null ? null : Array.from(a, plain));
const rows = (u) => {
  // columns per input -> runs, row-major
  const K = u.length, n = K ? u[0].length : 0, out = [];
  for (let i = 0; i < n; i++) for (let k = 0; k < K; k++) out.push(u[k][i]);
  return out;
};
const cols = (m) => m.map((c) => Float64Array.from(c));
const streamOf = (s) => { let i = 0; return () => { if (i >= s.length) throw new Error('stream ran out'); return s[i++]; }; };

const results = [];
for (const c of cases) {
  const next = streamOf(c.stream || []);
  const y = Float64Array.from(c.y || []);
  const r = { method: c.method };
  switch (c.method) {
    case 'morris': {
      const d = G.morrisDesign(c.K, { trajectories: c.trajectories, points: c.points, levels: c.levels, next });
      r.u = rows(d.u);
      const m = G.morrisIndices(y, d, { relative: !!c.relative });
      Object.assign(r, { mean: list(m.mean), meanStar: list(m.meanStar), variance: list(m.variance), count: list(m.count) });
      r.ci = list(L.muStarInterval(m.effects, { resamples: c.R, indices: (k) => Int32Array.from(c.idx[k]) }));
      break;
    }
    case 'morrisTraj': {
      const d = L.morrisTrajectoryDesign(c.K, { trajectories: c.trajectories, levels: c.levels, candidates: c.candidates, next });
      r.u = rows(d.u);
      const m = G.morrisIndices(y, d);
      Object.assign(r, { mean: list(m.mean), meanStar: list(m.meanStar), variance: list(m.variance), count: list(m.count) });
      break;
    }
    case 'sobol': {
      const d = G.sobolDesign(c.K, c.n, { second: c.second, blocks: c.blocks, draw: (k, which, b) => Float64Array.from(c.draws[`${k}${which}${b}`]) });
      r.u = rows(d.u);
      const s = G.sobolIndices(y, { K: c.K, n: c.n, second: c.second, blocks: c.blocks, estimator: c.estimator });
      Object.assign(r, { S1: list(s.S1), ST: list(s.ST), S2: list(s.S2), S1ci: list(s.S1ci), STci: list(s.STci), S2ci: list(s.S2ci) });
      if (c.boot) {
        const b = L.sobolBootstrap(y, { K: c.K, n: c.n, second: c.second }, { resamples: c.R, indices: Int32Array.from(c.boot) });
        Object.assign(r, { bS1ci: list(b.S1ci), bSTci: list(b.STci), bS2ci: list(b.S2ci) });
      }
      break;
    }
    case 'efast': {
      const N = G.efastSamples(c.n, c.M);
      const d = G.efastDesign(c.K, N, { harmonics: c.M, phases: c.phases });
      r.N = N;
      r.u = rows(d.u);
      const s = G.efastIndices(y, d);
      Object.assign(r, { S1: list(s.S1), ST: list(s.ST) });
      break;
    }
    case 'rbdfast': {
      const d = G.rbdFastDesign(c.K, c.N, { perms: c.perms });
      r.u = rows(d.u);
      const s = G.rbdFastIndices(y, d, { harmonics: c.H });
      r.S1 = list(s);
      r.S1c = list(s.map((v) => L.unskew(v, c.H, c.N)));
      break;
    }
    case 'ff': {
      const d = G.ffDesign(c.K, { low: c.low, high: c.high });
      r.u = rows(d.u);
      const s = G.ffIndices(y, d);
      r.main = list(s.main);
      r.pairs = L.ffInteractions(y, d).map((p) => [p.a, p.b, p.value]);
      break;
    }
    case 'dgsm': {
      const d = G.dgsmDesign(c.K, cols(c.base), { step: c.step, crossed: c.crossed });
      r.u = rows(d.u);
      const s = G.dgsmIndices(y, d);
      for (const k of ['a', 'absa', 'asq', 'sigma', 'tao', 'bound']) r[k] = list(s[k]);
      if (s.crossed) r.crossSq = list(s.crossed.sq);
      const sp = L.dgsmSpread(G.dgsmDerivatives(y, d).g, c.K, c.base[0].length, { resamples: c.R, indices: (k) => Int32Array.from(c.idx[k]) });
      r.sd = list(sp.sd);
      r.ci = list(sp.ci);
      break;
    }
    case 'radial': {
      const d = L.radialDesign(c.K, cols(c.base), cols(c.step));
      r.u = rows(d.u);
      const s = L.radialIndices(y, d, { resamples: c.R, indices: Int32Array.from(c.idx) });
      for (const k of ['mu', 'muStar', 'sigma', 'muStarCi', 'ST', 'STci']) r[k] = list(s[k]);
      break;
    }
    case 'shapley': {
      const d = G.shapleyDesign(c.K, { perms: c.perms, nVar: c.nVar, nOuter: c.nOuter, nInner: c.nInner, corr: c.corr ? Float64Array.from(c.corr) : null, next });
      r.u = rows(d.u);
      r.orders = d.orders;
      const s = G.shapleyIndices(y, d);
      r.effects = list(s.effects);
      r.stdErr = list(s.stdErr);
      break;
    }
    default:
      throw new Error(`no method ${c.method}`);
  }
  results.push(r);
}
process.stdout.write(JSON.stringify(results));
