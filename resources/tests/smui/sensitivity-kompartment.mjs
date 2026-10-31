/* Kompartment's sensitivity measures on a sample, for test_sensitivity.py:
   the functions of kompartment/src/domain (sensitivity.js, gsa.js and
   salib.js, themselves checked against GlobalSensitivity.jl and SALib) that
   resources/py/smui/sensitivity.py ports, called as Kompartment's What drove
   it calls them.

     node sensitivity-kompartment.mjs <sample.json>

   sample.json: { X: [[...], ...] one array per input, y: [...],
   resamples: [[...], ...] δ's bootstrap (row indices), shuffles: [[...], ...]
   mutual information's (orders of y), slides, threshold }. Prints, per
   input, what each measure gives (NaN as null), and the regressions'. */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const domain = (f) => pathToFileURL(path.join(here, '..', '..', '..', 'kompartment', 'src', 'domain', f)).href;
const S = await import(domain('sensitivity.js'));
const G = await import(domain('gsa.js'));
const L = await import(domain('salib.js'));

const sample = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const X = sample.X.map((c) => Float64Array.from(c));
const y = Float64Array.from(sample.y);
const n = y.length;
const resamples = (sample.resamples || []).map((r) => Int32Array.from(r));
const shuffles = (sample.shuffles || []).map((r) => Int32Array.from(r));
const plain = (v) => (typeof v === 'number' && !Number.isFinite(v) ? null : v);
const list = (a) => Array.from(a, plain);

const values = S.regressionMeasures(X, y);
const ranks = S.regressionMeasures(X, y, { translate: 'rank' });
const scores = G.normalScores(y);
const yRanks = G.averageRanks(y);
const threshold = sample.threshold ?? null;
const split = G.rsa(X, y, { threshold });
const flag = Float64Array.from(y, (v) => (v > split.threshold ? 1 : 0));
// the discrepancy's shares over the inputs that vary, as What drove it takes them
const varies = (x) => x.some((v) => v !== x[0]);
const spread = X.map((x, k) => k).filter((k) => varies(X[k]));
const yProb = L.rankProbabilities(y);
const got = L.discrepancyShares(spread.map((k) => L.rankProbabilities(X[k])), yProb, 'WD').shares;
const shares = X.map((x, k) => (spread.includes(k) ? got[spread.indexOf(k)] : NaN));

const inputs = X.map((x, k) => {
  const e = G.easi(x, y);
  const d = G.deltaMoment(x, scores, { resamples });
  const m = G.mutualInformation(G.averageRanks(x), yRanks, { shuffles });
  const p = L.pawn(x, y, { slides: sample.slides ?? 10 });
  return {
    pearson: plain(S.pearson(x, y)), spearman: plain(S.spearman(x, y)),
    src: plain(values.src[k]), pcc: plain(values.pcc[k]), srrc: plain(ranks.src[k]), prcc: plain(ranks.pcc[k]),
    s1: plain(S.firstOrderIndex(x, y)),
    easi: plain(e.s1), easi_c: plain(e.s1c),
    delta: plain(d.delta), delta_adjusted: plain(d.adjusted), delta_low: plain(d.low), delta_high: plain(d.high),
    mi: plain(m.mi), mi_bound: plain(m.bound), mi_above: plain(m.s),
    pawn: { minimum: plain(p.minimum), mean: plain(p.mean), median: plain(p.median), maximum: plain(p.maximum), stdev: plain(p.stdev), cv: plain(p.cv) },
    ks: plain(G.rsaScore(x, flag)),
    discrepancy: plain(shares[k]),
  };
});

process.stdout.write(JSON.stringify({
  n, r2: plain(values.r2), r2_rank: plain(ranks.r2), threshold: plain(split.threshold),
  delta_classes: G.deltaClasses(n), inputs,
}));
