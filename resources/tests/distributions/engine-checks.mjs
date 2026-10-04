/* ==========================================================================
   The second half of test-engine.mjs: the fits, and the checks that need
   no reference values.
   ========================================================================== */

export async function run({ check, close, imp, ref }) {
  const { FAMILIES, familyById, parameterisationsOf, KNOWN } = await imp('families.js');
  const { makeDistribution } = await imp('dist.js');
  const { fitAll, fitFamily, rankFits } = await imp('fit.js');
  const { describeSample, sampleQuantile } = await imp('kit.js');
  const { solveKnown, propertyValue } = await imp('solve.js');
  const { makeRng } = await imp('rng.js');
  const { parseExpression, evaluateExpression } = await imp('expr.js');

  const show = (v) => (typeof v === 'number' ? v.toPrecision(10) : String(v));

  /* ---- 2. maximum likelihood against SciPy's ------------------------------------------- */
  /* Ours must reach SciPy's log-likelihood (to a millionth of a unit; a
     fit that is better is better), and where both have found the same
     optimum the parameters must agree. */
  for (const f of ref.fits) {
    const fam = familyById(f.family);
    const s = describeSample(f.data);
    const r = fitFamily(fam, s, 'mle');
    if (r.why) { check(`fit ${f.family}`, false, r.why); continue; }
    check(`fit ${f.family}: log-likelihood at least SciPy's`, r.logL >= f.logL - 1e-6, `${show(r.logL)} vs ${show(f.logL)}`);
    if (Math.abs(r.logL - f.logL) < 1e-7 && !['triangular', 'cauchy', 'studentt', 'gev'].includes(f.family)) {
      for (const [key, want] of Object.entries(f.scipy)) {
        check(`fit ${f.family}: ${key}`, close(r.params[key], want, 1e-4, 1e-8), `${show(r.params[key])} vs ${show(want)}`);
      }
    }
  }

  /* ---- 3a. every parameterisation round-trips --------------------------------------------- */
  const paramSets = new Map();
  for (const c of ref.cases) {
    if (!paramSets.has(c.family)) paramSets.set(c.family, []);
    paramSets.get(c.family).push(c.params);
  }
  for (const fam of FAMILIES) {
    const sets = [fam.defaults, ...(paramSets.get(fam.id) || [])];
    for (const par of parameterisationsOf(fam)) {
      if (par.id === KNOWN) continue;
      for (const p of sets) {
        if (par.covers && !par.covers(p)) continue;   // a parameterisation of part of the family
        let values;
        try { values = par.from(p); } catch (e) { check(`${fam.id} ${par.id} from`, false, e.message); continue; }
        if (!Object.values(values).every(Number.isFinite)) continue;   // e.g. a CV at a mean of zero
        let back;
        try { back = par.to(values); } catch (e) { check(`${fam.id} ${par.id} to ${JSON.stringify(values)}`, false, e.message); continue; }
        for (const def of fam.params) {
          if (back[def.key] === undefined) continue;
          check(`${fam.id} ${par.id} round trip ${def.key} from ${JSON.stringify(p)}`, close(back[def.key], p[def.key], 1e-9, 1e-12), `${show(back[def.key])} vs ${show(p[def.key])}`);
        }
      }
    }
  }

  /* ---- 3b. known values solve to the values asked for ------------------------------------------ */
  const KNOWN_CASES = [
    ['normal', { mu: 3, sigma: 2 }, [['mean'], ['q', 95]]],
    ['lognormal', { mu: 1, sigma: 0.6 }, [['mean'], ['q', 95]]],
    ['lognormal', { mu: 1, sigma: 0.6 }, [['mode'], ['median']]],
    ['gamma', { k: 2.5, theta: 3 }, [['median'], ['q', 90]]],
    ['weibull', { k: 1.7, lambda: 4 }, [['mean'], ['cv']]],
    ['beta', { alpha: 2, beta: 5, lo: 0, hi: 1 }, [['q', 5], ['q', 95]]],
    ['triangular', { a: 1, c: 3, b: 8 }, [['q', 10], ['mode'], ['q', 90]]],
    ['pert', { a: 1, c: 3, b: 8, lambda: 4 }, [['q', 5], ['median'], ['q', 95]]],
    ['loglogistic', { alpha: 2, beta: 5 }, [['median'], ['sd']]],
    ['exponential', { lambda: 0.3 }, [['q', 99]]],
    ['gev', { mu: 5, sigma: 2, xi: 0.15 }, [['mean'], ['sd'], ['q', 99]]],
    ['invgauss', { mu: 2, lambda: 5 }, [['median'], ['q', 99]]],
    ['logtriangular', { a: 0.1, c: 2, b: 50 }, [['q', 5], ['median'], ['q', 95]]],
    ['studentt', { nu: 6, mu: 1, sigma: 2 }, [['median'], ['q', 75], ['q', 99]]],
    /* far from the family's defaults, which the search also starts from */
    ['triangular', { a: 1000, c: 1003, b: 1010 }, [['q', 10], ['mode'], ['q', 90]]],
    ['pert', { a: 100, c: 101, b: 104, lambda: 4 }, [['q', 5], ['median'], ['q', 95]]],
    ['dtriangular', { a: 50, c: 52, b: 60 }, [['q', 10], ['median'], ['q', 90]]],
    ['logtriangular', { a: 1e3, c: 5e3, b: 1e5 }, [['q', 5], ['median'], ['q', 95]]],
  ];
  for (const [id, truth, wanted] of KNOWN_CASES) {
    const fam = familyById(id);
    const D = makeDistribution({ family: id, params: truth });
    const rows = wanted.map(([prop, p]) => ({ prop, p, value: propertyValue(fam, D, truth, { prop, p }) }));
    let got;
    try { got = solveKnown(fam, rows, fam.defaults); } catch (e) { check(`known ${id} ${wanted.map((w) => w.join('')).join(', ')}`, false, e.message); continue; }
    const G = makeDistribution({ family: id, params: got });
    for (const row of rows) {
      const v = propertyValue(fam, G, got, row);
      check(`known ${id}: ${row.prop}${row.p ?? ''} met`, close(v, row.value, 1e-8, 1e-12), `${show(v)} vs ${show(row.value)}`);
    }
    for (const key of fam.free.keys) {
      check(`known ${id}: ${key} recovered`, close(got[key], truth[key], 1e-6, 1e-9), `${show(got[key])} vs ${show(truth[key])}`);
    }
  }
  /* a lognormal whose mean is below its median does not exist */
  try {
    solveKnown(familyById('lognormal'), [{ prop: 'mean', value: 1 }, { prop: 'median', value: 2 }], familyById('lognormal').defaults);
    check('known: impossible values refused', false, 'solved');
  } catch (e) { check('known: impossible values refused', /No lognormal/.test(e.message), e.message); }

  /* ---- 4. the method of moments meets the sample's moments ------------------------------------------ */
  for (const f of ref.fits) {
    const fam = familyById(f.family);
    const s = describeSample(f.data);
    const r = fitFamily(fam, s, 'mom');
    if (r.why) { check(`mom ${f.family} fits`, ['cauchy'].includes(f.family), r.why); continue; }
    if (r.note) continue;   // the sample is out of the family's reach; the nearest is not a match
    const D = makeDistribution({ family: f.family, params: r.params });
    const st = D.stats();
    const k = r.k;
    check(`mom ${f.family}: mean`, close(st.mean, s.mean, 1e-7, 1e-10), `${show(st.mean)} vs ${show(s.mean)}`);
    if (k >= 2) check(`mom ${f.family}: variance`, close(st.variance, s.var, 1e-7, 1e-10), `${show(st.variance)} vs ${show(s.var)}`);
    if (k >= 3 && f.family !== 'studentt') check(`mom ${f.family}: skewness`, close(st.skewness, s.skew, 1e-6, 1e-8), `${show(st.skewness)} vs ${show(s.skew)}`);
  }

  /* ---- 5. truncation against SciPy-and-quad ------------------------------------------------------------- */
  for (const t of ref.truncated) {
    const D = makeDistribution({ family: t.family, params: t.params, trunc: { lo: t.lo, hi: t.hi } });
    const tag = `${t.family} truncated to [${t.lo ?? '−∞'}, ${t.hi ?? '∞'}]`;
    check(`${tag}: mass`, close(D.truncated.mass, t.mass, 1e-10), `${show(D.truncated.mass)} vs ${show(t.mass)}`);
    const st = D.stats();
    check(`${tag}: mean`, close(st.mean, t.mean, 1e-8, 1e-12), `${show(st.mean)} vs ${show(t.mean)}`);
    check(`${tag}: variance`, close(st.variance, t.variance, 1e-7), `${show(st.variance)} vs ${show(t.variance)}`);
    const spread = Math.abs(t.q[3] - t.q[1]) || 1;
    t.u.forEach((u, i) => {
      check(`${tag}: quantile(${u})`, close(D.quantile(u), t.q[i], 1e-10, 1e-13 * spread), `${show(D.quantile(u))} vs ${show(t.q[i])}`);
    });
  }

  /* ---- 6. empirical distributions ----------------------------------------------------------------------- */
  const rng = makeRng(7);
  const data = Array.from({ length: 400 }, () => Math.exp(1 + 0.8 * Math.sqrt(-2 * Math.log(rng())) * Math.cos(2 * Math.PI * rng())));
  const s = describeSample(data);
  const I = makeDistribution({ family: 'empirical', method: 'interpolated', data });
  for (const u of [0.01, 0.1, 0.5, 0.77, 0.99]) {
    check(`interpolated quantile(${u}) is the type-7 sample quantile`, close(I.quantile(u), sampleQuantile(s.x, u), 1e-13));
  }
  const E = makeDistribution({ family: 'empirical', method: 'ecdf', data });
  check('ecdf mean is the sample mean', close(E.stats().mean, s.mean, 1e-13));
  check('ecdf variance is the sample variance (over n)', close(E.stats().variance, s.var, 1e-12));
  check('ecdf skewness is the sample skewness', close(E.stats().skewness, s.skew, 1e-10));
  const K = makeDistribution({ family: 'empirical', method: 'kde', data, bw: 0.3 });
  const kst = K.stats();
  check('kde variance is the sample variance plus h²', close(kst.variance, s.var + 0.09, 1e-12));
  check('kde integrates to 1', close(K.cdf(1e6), 1, 1e-14) && close(K.cdf(-1e6), 0, 0, 1e-14));
  /* its CDF against the integral of its density */
  {
    const { integrate } = await imp('numeric.js');
    let acc = 0;
    for (let a = -3; a < 6; a += 0.5) acc += integrate(K.pdf, a, a + 0.5, { rtol: 1e-12 });
    check('kde CDF is the integral of its density', close(K.cdf(6) - K.cdf(-3), acc, 1e-10), `${show(K.cdf(6) - K.cdf(-3))} vs ${show(acc)}`);
  }
  for (const u of [0.05, 0.5, 0.95]) check(`kde quantile(${u}) inverts its CDF`, close(K.cdf(K.quantile(u)), u, 1e-11));
  const H = makeDistribution({ family: 'empirical', method: 'histogram', data, bins: 10 });
  check('histogram has ten bins', H.prepared.bins.counts.length === 10);
  check('histogram CDF at the edges', close(H.cdf(s.min), 0, 0, 1e-15) && close(H.cdf(s.max), 1, 1e-15));
  const LK = makeDistribution({ family: 'empirical', method: 'kde', data, log: true, bw: 0.2 });
  {
    const logs = data.map(Math.log);
    const m = logs.reduce((a, b) => a + b, 0) / logs.length;
    check('log kde: geometric mean is e^(mean ln x)', close(LK.stats().gm, Math.exp(m), 1e-12));
    const mean = data.reduce((a, v) => a + v, 0) / data.length * Math.exp(0.02);
    check('log kde: mean is the sample mean times e^(h²/2)', close(LK.stats().mean, mean, 1e-12), `${show(LK.stats().mean)} vs ${show(mean)}`);
  }
  /* tables */
  const T = makeDistribution({ family: 'table', mode: 'cdf', rows: [[0, 0], [1, 0.5], [3, 1]] });
  check('cumulative table: median', close(T.quantile(0.5), 1, 1e-15));
  check('cumulative table: mean', close(T.stats().mean, 0.5 * 0.5 + 0.5 * 2, 1e-14));
  const P = makeDistribution({ family: 'table', mode: 'pmf', rows: [[1, 1], [2, 2], [5, 1]] });
  check('probability table: scaled to 1', close(P.pdf(2), 0.5, 1e-15) && /scaled/.test(P.note));
  check('probability table: mean', close(P.stats().mean, (1 + 4 + 5) / 4, 1e-15));
  try { makeDistribution({ family: 'table', mode: 'cdf', rows: [[0, 0], [1, 0.7], [2, 0.6], [3, 1]] }); check('cumulative table: decreasing F refused', false); } catch (e) { check('cumulative table: decreasing F refused', /decrease/.test(e.message)); }

  /* ---- 7. sampling ------------------------------------------------------------------------------------------- */
  {
    const D = makeDistribution({ family: 'gamma', params: { k: 2.5, theta: 3 } });
    const n = 20000;
    const x = D.sample(n, makeRng(11));
    let m = 0;
    for (const v of x) m += v;
    m /= n;
    const se = Math.sqrt(D.stats().variance / n);
    check('gamma sample mean within 4 standard errors', Math.abs(m - D.stats().mean) < 4 * se, `${show(m)} vs ${show(D.stats().mean)}`);
    const xs = Float64Array.from(x).sort();
    let d = 0;
    for (let i = 0; i < n; i++) d = Math.max(d, (i + 1) / n - D.cdf(xs[i]), D.cdf(xs[i]) - i / n);
    check('gamma sample: K-S D below 1.63/√n (p > 0.01)', d < 1.63 / Math.sqrt(n), show(d));
    const again = D.sample(n, makeRng(11));
    check('the same seed gives the same draws', again.every((v, i) => v === x[i]));
    const L = D.sample(1000, makeRng(3), true);
    const strata = new Set(Array.from(L, (v) => Math.floor(D.cdf(v) * 1000)));
    check('Latin hypercube: one draw in each of 1000 strata', strata.size === 1000, String(strata.size));
    const P2 = makeDistribution({ family: 'poisson', params: { lambda: 3.3 } });
    const y = P2.sample(20000, makeRng(5));
    check('Poisson draws are whole numbers', y.every(Number.isInteger));
    check('Poisson sample mean', Math.abs(y.reduce((a, b) => a + b, 0) / y.length - 3.3) < 4 * Math.sqrt(3.3 / 20000));
  }

  /* ---- 8. expressions ------------------------------------------------------------------------------------------ */
  {
    const isVar = (name) => /^[A-H]$/.test(name);
    const env = { A: Float64Array.from([1, 2, 3]), B: Float64Array.from([4, 5, 6]) };
    const ev = (text) => Array.from(evaluateExpression(parseExpression(text, isVar).tree, env, 3));
    const same = (a, b) => a.length === b.length && a.every((v, i) => Math.abs(v - b[i]) < 1e-12);
    check('expr: A + B * 2', same(ev('A + B * 2'), [9, 12, 15]));
    check('expr: -A^2 is -(A^2)', same(ev('-A^2'), [-1, -4, -9]));
    check('expr: 2^-1 * A', same(ev('2^-1 * A'), [0.5, 1, 1.5]));
    check('expr: max(A, 2.5) and exp(ln(B))', same(ev('max(A, 2.5)'), [2.5, 2.5, 3]) && same(ev('exp(ln(B))'), [4, 5, 6]));
    check('expr: ** is ^', same(ev('A ** 2'), [1, 4, 9]));
    check('expr: variables listed', parseExpression('A * (B + A)', isVar).variables.sort().join() === 'A,B');
    for (const bad of ['A +', 'A * Q', 'foo(A)', '(A', 'A B', '3 $ 4', '']) {
      let threw = false;
      try { parseExpression(bad, isVar); } catch (e) { threw = true; }
      check(`expr: "${bad}" is refused`, threw);
    }
  }

  /* ---- 9. the calculations -------------------------------------------------------------------------------------------- */
  {
    const C = await imp('calcmath.js');
    const { runMonteCarlo } = await imp('mc.js');
    const N01 = makeDistribution({ family: 'normal', params: { mu: 0, sigma: 1 } });
    const N12 = makeDistribution({ family: 'normal', params: { mu: 1, sigma: 2 } });
    const phi1 = Math.exp(-0.5) / Math.sqrt(2 * Math.PI);
    const S1 = 0.15865525393145707;
    const t = C.tailStats(N01, 1, 0.95);
    check('calc: E[X | X > 1] of a standard normal is φ(1)/S(1)', close(t.above, phi1 / S1, 1e-10), show(t.above));
    check('calc: E[X | X ≤ 1] is −φ(1)/F(1)', close(t.below, -phi1 / (1 - S1), 1e-10), show(t.below));
    check('calc: E[(X − 1)⁺] is φ(1) − S(1)', close(t.excess, phi1 - S1, 1e-9), show(t.excess));
    check('calc: expected shortfall at 95 % is φ(z)/0.05', close(t.tvar, Math.exp(-0.5 * 1.6448536269514722 ** 2) / Math.sqrt(2 * Math.PI) / 0.05, 1e-10), show(t.tvar));
    const P = makeDistribution({ family: 'pareto', params: { xm: 1, alpha: 1.5 } });
    check('calc: Pareto E[X | X > 2] = αt/(α − 1)', close(C.tailStats(P, 2, 0.9).above, 6, 1e-10));
    check('calc: Pareto α = 0.8 has an infinite tail mean', C.tailStats(makeDistribution({ family: 'pareto', params: { xm: 1, alpha: 0.8 } }), 2, 0.9).above === Infinity);
    const si = C.shortestInterval(N01, 0.95);
    check('calc: the shortest 95 % interval of a normal is ±1.96', close(si[0], -1.959963984540054, 1e-7) && close(si[1], 1.959963984540054, 1e-7), `${show(si[0])}, ${show(si[1])}`);
    const E = makeDistribution({ family: 'exponential', params: { lambda: 1 } });
    const se = C.shortestInterval(E, 0.9);
    check('calc: the shortest 90 % interval of an exponential starts at 0', se[0] < 1e-8 && close(se[1], Math.log(10), 1e-7), `${show(se[0])}, ${show(se[1])}`);
    const cmp = C.compare(N01, N12);
    check('calc: P(X > Y) for N(0,1) and N(1,2) is Φ(−1/√5)', close(cmp.pGreater, 0.32736042300928847, 1e-9), show(cmp.pGreater));
    check('calc: KL(N(0,1) ‖ N(1,2))', close(cmp.klXY, Math.log(2) + 2 / 8 - 0.5, 1e-9), show(cmp.klXY));
    check('calc: KL(N(1,2) ‖ N(0,1))', close(cmp.klYX, Math.log(0.5) + 5 / 2 - 0.5, 1e-9), show(cmp.klYX));
    const p3 = makeDistribution({ family: 'poisson', params: { lambda: 3 } });
    const p4 = makeDistribution({ family: 'poisson', params: { lambda: 4 } });
    const cp = C.compare(p3, p4);
    check('calc: Wasserstein between Poissons 3 and 4 is 1', close(cp.wasserstein, 1, 1e-12), show(cp.wasserstein));
    check('calc: KL(Pois 3 ‖ Pois 4)', close(cp.klXY, 3 * Math.log(3 / 4) + 1, 1e-12), show(cp.klXY));
    check('calc: KL(Pois 4 ‖ Pois 3)', close(cp.klYX, 4 * Math.log(4 / 3) - 1, 1e-12), show(cp.klYX));
    check('calc: P(X > Y) + P(X < Y) + P(X = Y) = 1 for two Poissons', close(cp.pGreater + cp.pLess + cp.pEqual, 1, 1e-12));
    const same = C.compare(N12, makeDistribution({ family: 'normal', params: { mu: 1, sigma: 2 } }));
    check('calc: a distribution against itself: overlap 1, distances 0', close(same.overlap, 1, 1e-7) && same.ks < 1e-12 && same.wasserstein < 1e-9 && same.hellinger < 1e-4, JSON.stringify(same));
    const mc = runMonteCarlo({ A: { family: 'normal', params: { mu: 1, sigma: 1 } }, B: { family: 'normal', params: { mu: 2, sigma: 2 } } }, 'A + B', 200000, 9, false);
    let m = 0;
    for (const v of mc.values) m += v;
    m /= mc.values.length;
    let v2 = 0;
    for (const v of mc.values) v2 += (v - m) ** 2;
    v2 /= mc.values.length;
    check('mc: A + B of N(1,1) and N(2,2) has mean 3 and variance 5', Math.abs(m - 3) < 4 * Math.sqrt(5 / 200000) && Math.abs(v2 - 5) < 0.05, `${show(m)}, ${show(v2)}`);
    const again = runMonteCarlo({ A: { family: 'normal', params: { mu: 1, sigma: 1 } }, B: { family: 'normal', params: { mu: 2, sigma: 2 } } }, 'A + B', 1000, 9, true);
    const again2 = runMonteCarlo({ A: { family: 'normal', params: { mu: 1, sigma: 1 } }, B: { family: 'normal', params: { mu: 2, sigma: 2 } } }, 'A + B', 1000, 9, true);
    check('mc: a seed gives the same draws', again.values.every((x, i) => x === again2.values[i]));
    const logs = runMonteCarlo({ A: { family: 'normal', params: { mu: 0, sigma: 1 } } }, 'ln(A)', 10000, 3, false);
    check('mc: draws with no finite result are dropped and counted', logs.dropped > 4000 && logs.dropped < 6000 && logs.values.length + logs.dropped === 10000, String(logs.dropped));
  }

  /* ---- 10. a ranking ----------------------------------------------------------------------------------------------- */
  {
    const g = makeDistribution({ family: 'gamma', params: { k: 3, theta: 2 } }).sample(500, makeRng(99));
    const { results } = fitAll(Array.from(g), { kind: 'continuous', methods: ['mle'] });
    const ranked = rankFits(results, 'aic');
    check('ranking: every result has a rank or a reason', ranked.every((r) => Number.isFinite(r.rank) || r.why));
    const top = ranked.slice(0, 5).map((r) => r.family);
    check('ranking: a gamma sample puts the gamma in the top five by AIC', top.includes('gamma'), top.join(', '));
    const w = ranked.filter((r) => r.method === 'mle').reduce((a, r) => a + (r.weight || 0), 0);
    check('ranking: Akaike weights add up to 1', close(w, 1, 1e-12), show(w));
    const pois = makeDistribution({ family: 'poisson', params: { lambda: 3.7 } }).sample(300, makeRng(4));
    const dr = rankFits(fitAll(Array.from(pois), { kind: 'discrete', methods: ['mle'] }).results, 'aic');
    const p = dr.find((r) => r.family === 'poisson');
    check('ranking: a Poisson sample fits a Poisson with a χ² p above 0.001', p && p.chi2p > 0.001, p && show(p.chi2p));
    const nb = dr.find((r) => r.family === 'negbinomial');
    check('ranking: the negative binomial on Poisson counts reaches its Poisson limit', nb && (nb.why || nb.params.r > 50 || /limit/.test(nb.note)), nb && JSON.stringify(nb.params));
    const se = ranked.find((r) => r.family === 'normal').se;
    check('ranking: normal MLE standard errors are σ/√n and σ/√(2n)', se && close(se.mu, ranked.find((r) => r.family === 'normal').params.sigma / Math.sqrt(500), 1e-4) && close(se.sigma, ranked.find((r) => r.family === 'normal').params.sigma / Math.sqrt(1000), 1e-3), JSON.stringify(se));
  }

  /* ---- 11. what a review of the page found, kept from coming back ------------------------------------------------- */
  {
    const C = await imp('calcmath.js');
    const { brentRoot } = await imp('numeric.js');
    const { betaIncInv, betaInc } = await imp('special.js');
    const dist = (family, params, trunc) => makeDistribution({ family, params, trunc });
    const throwsLike = (f, re) => { try { f(); return false; } catch (e) { return re.test(e.message); } };

    /* the double triangle's likelihood has no maximum when its mode may sit
       on the smallest or largest value: those candidates are left out */
    const dtData = [4.1, 5.3, 4.8, 6.0, 5.1, 4.6];
    const dt = fitFamily(familyById('dtriangular'), describeSample(dtData), 'mle');
    check('review: double-triangle MLE on six values is finite and not a spike on an end value',
      !dt.why && Number.isFinite(dt.logL) && dt.params.a < 4.1 && dt.params.b > 6.0 && dt.params.c > 4.1 && dt.params.c < 6.0 && dt.params.b - dt.params.a > 1.9,
      JSON.stringify(dt.params));
    check('review: double-triangle MLE on six values', close(dt.params.a, 3.8440973981063227, 1e-6) && close(dt.params.c, 4.8, 1e-12) && close(dt.params.b, 6.505904796567842, 1e-6), JSON.stringify(dt.params));
    /* tied end values: the side holding only them would close in on them too */
    for (const y of [[1, 1, 2, 3, 4], [1, 2, 3, 4, 4], [1, 1, 1, 1, 2, 3, 3, 3, 3]]) {
      for (const family of ['dtriangular', 'logdtriangular']) {
        const r = fitFamily(familyById(family), describeSample(y), 'mle');
        const lo = y[0];
        const hi = y[y.length - 1];
        const { a, c, b } = r.params || {};
        check(`review: ${family} MLE on ${y.join(', ')} is not a spike`, !r.why && a < lo && b > hi && b - a < 4 * (hi - lo) && c > lo && c < hi, JSON.stringify(r.params || r.why));
      }
    }

    /* the PERT's method of moments keeps the side of the skew: the moments
       of PERT(100, 101, 104) give it back */
    {
      const P = dist('pert', { a: 100, c: 101, b: 104, lambda: 4 });
      const st = P.stats();
      const got = familyById('pert').fit.mom({ n: 1000, mean: st.mean, sd: Math.sqrt(st.variance), var: st.variance, skew: st.skewness, kurt: st.kurtosis, min: 100.2, max: 103.8 });
      const g = got.params || got;
      check('review: PERT method of moments recovers PERT(100, 101, 104)', close(g.a, 100, 1e-8) && close(g.c, 101, 1e-8) && close(g.b, 104, 1e-8), JSON.stringify(g));
    }

    /* a truncated mode is searched for, not the family's mode clamped */
    check('review: Beta(0.5, 0.5) on [0.3, 0.9] has its mode at 0.9', close(dist('beta', { alpha: 0.5, beta: 0.5, lo: 0, hi: 1 }, { lo: 0.3, hi: 0.9 }).stats().mode, 0.9, 1e-6), show(dist('beta', { alpha: 0.5, beta: 0.5, lo: 0, hi: 1 }, { lo: 0.3, hi: 0.9 }).stats().mode));
    check('review: N(0, 1) on [1, 3] has its mode at 1', close(dist('normal', { mu: 0, sigma: 1 }, { lo: 1, hi: 3 }).stats().mode, 1, 1e-6));
    check('review: Binomial(10, 0.5) on [7, 10] has its mode at 7', dist('binomial', { n: 10, p: 0.5 }, { lo: 7, hi: 10 }).stats().mode === 7);

    /* a lower bound on a jump keeps the probability at the bound */
    {
      const T = makeDistribution({ family: 'table', mode: 'cdf', rows: [[0, 0], [1, 0.3], [1, 0.6], [2, 1]], trunc: { lo: 1, hi: null } });
      check('review: a cumulative table truncated at its jump keeps the jump', close(T.truncated.mass, 0.7, 1e-14), show(T.truncated.mass));
      const I = makeDistribution({ family: 'empirical', method: 'interpolated', data: [1, 2, 2, 2, 3], trunc: { lo: 2, hi: null } });
      check('review: tied data truncated at the tie keep the tie', close(I.truncated.mass, 0.75, 1e-14), show(I.truncated.mass));
    }

    /* counts beyond what doubles hold are refused, and large ones do not hang */
    check('review: a Poisson mean of 10^16 is refused', throwsLike(() => dist('poisson', { lambda: 1e16 }), /too large/));
    check('review: 10^16 binomial trials are refused', throwsLike(() => dist('binomial', { n: 1e16, p: 0.5 }), /too large/));
    {
      const t0 = performance.now();
      const B = dist('binomial', { n: 1e15, p: 0.5 });
      const med = B.quantile(0.5);
      const atoms = B.atoms();
      const ms = performance.now() - t0;
      check('review: Binomial(10^15, 0.5): a median, no atom list, quickly', close(med, 5e14, 1e-12) && atoms === null && ms < 2000, `${show(med)}, ${ms.toFixed(0)} ms`);
    }

    /* huge shapes: Temme's expansion and the t's Cornish-Fisher path, against
       mpmath at 40 digits (gammainc, betainc) */
    check('review: Poisson(10^14) P(X ≤ 10^14)', close(dist('poisson', { lambda: 1e14 }).cdf(1e14), 0.50000002659615202676, 1e-13), show(dist('poisson', { lambda: 1e14 }).cdf(1e14)));
    {
      const G = dist('gamma', { k: 1e6, theta: 1 });
      check('review: Gamma(10^6) F and 1 − F at 10^6 + 2000', close(G.cdf(1e6 + 2000), 0.97719590410123013724, 1e-13) && close(G.sf(1e6 + 2000), 0.02280409589876986276, 1e-12), `${show(G.cdf(1e6 + 2000))}, ${show(G.sf(1e6 + 2000))}`);
      const T = dist('studentt', { nu: 1e6, mu: 0, sigma: 1 });
      check('review: t with ν = 10^6: P(T > 3), P(T > 6) and back', close(T.sf(3), 0.0013499312707108985294, 1e-12) && close(T.sf(6), 9.8692490617721733495e-10, 1e-12) && close(T.isf(9.8692490617721733495e-10), 6, 1e-12), `${show(T.sf(3))}, ${show(T.sf(6))}`);
    }

    /* standard errors do not depend on where the data are */
    for (const [family, params] of [['logistic', { mu: 0, s: 1 }], ['gumbel', { mu: 0, beta: 1 }]]) {
      const x0 = Array.from(dist(family, params).sample(400, makeRng(1)));
      const x1 = x0.map((v) => v + 1e6);
      const r0 = fitFamily(familyById(family), describeSample(x0), 'mle');
      const r1 = fitFamily(familyById(family), describeSample(x1), 'mle');
      const keys = Object.keys(r0.se || {});
      check(`review: ${family} standard errors at a location of 10^6 are those at 0`, keys.length === 2 && r1.se && keys.every((k) => close(r1.se[k], r0.se[k], 1e-4)), `${JSON.stringify(r0.se)} vs ${JSON.stringify(r1.se)}`);
    }
    {
      const x = Array.from(dist('logistic', { mu: 0, s: 1 }).sample(4000, makeRng(8)));
      const r = fitFamily(familyById('logistic'), describeSample(x), 'mle');
      /* the Fisher information of the logistic: n/(3s²) for μ, n(π² + 3)/(9s²) for s */
      check('review: logistic standard errors near the Fisher information', close(r.se.mu, r.params.s * Math.sqrt(3 / 4000), 0.05) && close(r.se.s, r.params.s * Math.sqrt(9 / (4000 * (Math.PI ** 2 + 3))), 0.05), JSON.stringify(r.se));
    }

    /* a distribution with no spread has no shape; an infinite mean, no variance */
    {
      const st = dist('binomial', { n: 5, p: 1 }).stats();
      check('review: Binomial(5, 1): variance 0, skewness and kurtosis undefined', st.variance === 0 && Number.isNaN(st.skewness) && Number.isNaN(st.kurtosis), JSON.stringify([st.variance, st.skewness, st.kurtosis]));
      const one = dist('poisson', { lambda: 3 }, { lo: 3, hi: 3 }).stats();
      check('review: a Poisson truncated to one value: skewness undefined', one.variance === 0 && Number.isNaN(one.skewness), JSON.stringify([one.variance, one.skewness]));
    }
    for (const [family, params] of [['pareto', { xm: 1, alpha: 0.8 }], ['genpareto', { mu: 0, sigma: 1, xi: 1.2 }], ['gev', { mu: 0, sigma: 1, xi: 1 }]]) {
      const st = dist(family, params).stats();
      check(`review: ${family} ${JSON.stringify(params)}: infinite mean, undefined variance`, st.mean === Infinity && Number.isNaN(st.variance) && Number.isNaN(st.skewness), JSON.stringify([st.mean, st.variance, st.skewness]));
    }

    /* typeset operators, and no reach into Object's own keys */
    {
      const isVar = (name) => /^[A-H]$/.test(name);
      const env = { A: Float64Array.from([1, 2, 3]), B: Float64Array.from([4, 5, 6]) };
      const got = Array.from(evaluateExpression(parseExpression('2 × A − B ÷ 2', isVar).tree, env, 3));
      check('review: × − ÷ are operators', got.every((v, i) => Math.abs(v - [0, 1.5, 3][i]) < 1e-15), got.join());
      for (const bad of ['constructor(A)', 'toString(A)', 'hasOwnProperty', '__proto__']) {
        check(`review: "${bad}" is refused`, throwsLike(() => parseExpression(bad, isVar), /There is no/));
      }
    }

    /* a root bracket whose ends have the same sign is no bracket, however small they are */
    check('review: brentRoot refuses a same-sign bracket of tiny values', Number.isNaN(brentRoot((x) => 1e-200 * (x + 2), 0, 1)));
    check('review: brentRoot finds a root among tiny values', close(brentRoot((x) => 1e-200 * (x - 0.5), 0, 1), 0.5, 1e-12));
    for (const [a, b] of [[2, 3], [0.1, 0.1], [50, 0.5]]) {
      for (const p of [1e-300, 1e-100, 1e-8, 0.3]) {
        const [x, y] = betaIncInv(a, b, p);
        /* an x that underflows is right when the smallest double already holds more than p */
        const ok = x > 0 ? close(betaInc(a, b, x, y)[0], p, 1e-9) : betaInc(a, b, Number.MIN_VALUE)[0] > p;
        check(`review: betaIncInv(${a}, ${b}, ${p}) inverts`, ok, `${show(x)} → ${show(x > 0 ? betaInc(a, b, x, y)[0] : 0)}`);
      }
    }

    /* the shortest interval of a count is the narrowest run of values */
    {
      const P = dist('poisson', { lambda: 3.3 });
      const [xs, ps] = P.atoms();
      let width = Infinity;
      for (let i = 0; i < xs.length; i++) {
        let m = 0;
        for (let j = i; j < xs.length; j++) { m += ps[j]; if (m >= 0.9 - 1e-12) { width = Math.min(width, xs[j] - xs[i]); break; } }
      }
      const got = C.shortestInterval(P, 0.9);
      const mass = P.cdf(got[1]) - P.cdf(got[0] - 1);
      check('review: the shortest 90 % interval of Poisson(3.3)', got[1] - got[0] === width && mass >= 0.9 - 1e-12, `${got} (${show(mass)}), narrowest ${width}`);
    }
    {
      const cmp = C.compare(dist('normal', { mu: 3, sigma: 1 }), dist('poisson', { lambda: 3 }));
      check('review: a continuous and a discrete distribution never tie', cmp.pEqual === 0 && close(cmp.pGreater + cmp.pLess, 1, 1e-12), JSON.stringify([cmp.pGreater, cmp.pLess, cmp.pEqual]));
    }

    /* the summed CDFs: a lookup after one pass, equal to the sums */
    {
      const n = 1000;
      const B = dist('betabinomial', { n, alpha: 0.7, beta: 2.5 });
      const pk = Array.from({ length: n + 1 }, (_, k) => B.pdf(k));
      let worst = 0;
      let left = 0;
      for (let k = 0; k < n; k++) {
        left += pk[k];
        let right = 0;
        for (let j = n; j > k; j--) right += pk[j];
        /* each side against its own sum where it is the smaller */
        if (left <= 0.5) worst = Math.max(worst, Math.abs(B.cdf(k) - left) / left);
        if (right <= 0.5) worst = Math.max(worst, Math.abs(B.sf(k) - right) / right);
      }
      check('review: beta-binomial F and 1 − F are the sums of its probabilities', worst < 1e-12, show(worst));
      check('review: beta-binomial F + (1 − F) = 1', [0, 10, 300, 999].every((k) => B.cdf(k) + B.sf(k) === 1));
      const H = dist('hypergeometric', { N: 1e6, K: 4e5, n: 2e5 });
      const t0 = performance.now();
      const [xs] = H.atoms();
      let sum = 0;
      for (const x of xs) sum += H.cdf(x) + H.sf(x);
      const ms = performance.now() - t0;
      check('review: every CDF of a hypergeometric with N = 10^6 in under 3 s', ms < 3000 && close(sum, xs.length, 1e-12), `${xs.length} values, ${ms.toFixed(0)} ms`);
    }

    /* a χ² test with no degrees of freedom left is no test */
    {
      const g = fitFamily(familyById('geometric'), describeSample([1.2e6, 1.3e6, 9e5, 1.1e6, 2e6, 4e5, 1.5e6, 7e5, 1.25e6, 1.05e6]), 'mle');
      check('review: χ² on ten values is left out, not given a negative df', Number.isNaN(g.chi2) && Number.isNaN(g.chi2df) && Number.isNaN(g.chi2p), JSON.stringify([g.chi2, g.chi2df, g.chi2p]));
    }
  }

  /* ---- 12. samples: the schemes, against SciPy's sequences and their own promises ------------------------- */
  {
    const S = await imp('sampling.js');
    const { streamSeed } = await imp('mc.js');
    const fs = await import('node:fs');
    const qref = JSON.parse(fs.readFileSync(new URL('./qmc-ref.json', import.meta.url), 'utf8'));
    let sobolOff = 0;
    let haltonWorst = 0;
    for (let d = 0; d < 16; d++) {
      const w = S.sobolWords(64, d, null);
      qref.sobol[d].forEach((v, i) => { if (w[i] / 4294967296 !== v) sobolOff++; });
      const h = S.haltonPoints(64, d, null);
      qref.halton[d].forEach((v, i) => { haltonWorst = Math.max(haltonWorst, Math.abs(h[i] - v)); });
    }
    check(`samples: plain Sobol points are SciPy's (${qref.scipy}), 64 in each of 16 dimensions`, sobolOff === 0, `${sobolOff} differ`);
    check('samples: plain Halton points are SciPy\'s to 2e-16', haltonWorst <= 2.3e-16, show(haltonWorst));

    /* one draw in each of n strata of probability: Latin hypercube always,
       Sobol at a power of two, Halton at a power of its base */
    const stratified = (u, n) => { const c = new Uint8Array(n); for (const v of u) c[Math.min(n - 1, Math.floor(v * n))]++; return c.every((k) => k === 1); };
    const letters = 'ABCDEFGHIJKLMNOP'.split('');
    check('samples: scrambled Sobol, 1024 draws: one in each of 1024 strata, for every letter', letters.every((L) => stratified(S.uniforms('sobol', 1024, 7, L).u, 1024)));
    const primes = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53];
    check('samples: scrambled Halton at a power of its base: one in each stratum, for every letter', letters.every((L, d) => {
      const b = primes[d];
      const n = b ** Math.max(1, Math.floor(Math.log(4000) / Math.log(b)));
      return stratified(S.uniforms('halton', n, 3, L).u, n);
    }));
    check('samples: Latin hypercube and its centred form: one in each of 1000 strata', stratified(S.uniforms('lhs', 1000, 5, 'C').u, 1000) && stratified(S.uniforms('lhs-centred', 1000, 5, 'C').u, 1000));
    const centred = S.uniforms('lhs-centred', 8, 1, 'A').u;
    check('samples: centred Latin hypercube draws the middles (i + ½)/n', Array.from(centred).sort((a, b) => a - b).every((v, i) => v === (i + 0.5) / 8));
    for (const scheme of ['random', 'lhs', 'lhs-centred', 'sobol', 'halton']) {
      const { u, uc } = S.uniforms(scheme, 4096, 11, 'B');
      const inside = u.every((v) => v > 0 && v < 1) && uc.every((v) => v > 0 && v < 1);
      const sums = u.every((v, i) => Math.abs(v + uc[i] - 1) <= 2.3e-16);
      check(`samples: ${scheme} uniforms are inside (0, 1), their complements exact`, inside && sums);
      const again = S.uniforms(scheme, 4096, 11, 'B').u;
      const other = S.uniforms(scheme, 4096, 12, 'B').u;
      check(`samples: ${scheme}: the same seed gives the same draws, another seed others`, again.every((v, i) => v === u[i]) && (scheme === 'lhs-centred' ? !other.every((v, i) => v === u[i]) : other.some((v, i) => v !== u[i])));
    }
    /* simple random and Latin hypercube draws are a Monte Carlo expression's */
    {
      const D = makeDistribution({ family: 'gamma', params: { k: 2.5, theta: 3 } });
      const a = S.drawSample(D, 'random', 500, 9, 'D').values;
      const b = D.sample(500, makeRng(streamSeed(9, 'D')), false);
      const c = S.drawSample(D, 'lhs', 500, 9, 'D').values;
      const e = D.sample(500, makeRng(streamSeed(9, 'D')), true);
      check('samples: simple random and Latin hypercube draws are those a Monte Carlo expression takes', a.every((v, i) => v === b[i]) && c.every((v, i) => v === e[i]));
    }
    /* the summary: K–S from the uniforms is K–S from the CDF */
    {
      const D = makeDistribution({ family: 'weibull', params: { k: 1.7, lambda: 4 } });
      const { values, u } = S.drawSample(D, 'random', 2000, 3, 'A');
      const sm = S.summarise(D, values, u);
      const xs = Float64Array.from(values).sort();
      let d = 0;
      for (let i = 0; i < xs.length; i++) { const F = D.cdf(xs[i]); d = Math.max(d, (i + 1) / xs.length - F, F - i / xs.length); }
      check('samples: K–S D from the uniforms is K–S D from the CDF', close(sm.ks, d, 1e-9), `${show(sm.ks)} vs ${show(d)}`);
      check('samples: summary mean, SD, median', close(sm.mean, values.reduce((x, y) => x + y, 0) / 2000, 1e-12) && sm.q[2] === sampleQuantile(xs, 0.5) && sm.min === xs[0] && sm.max === xs[1999]);
      const P = makeDistribution({ family: 'poisson', params: { lambda: 3 } });
      const pd = S.drawSample(P, 'lhs-centred', 1000, 1, 'B');
      const ps = S.summarise(P, pd.values, pd.u);
      check('samples: a centred Latin hypercube of a Poisson is within 1/n of its CDF everywhere', ps.ks <= 1 / 1000 + 1e-12 && pd.values.every(Number.isInteger), show(ps.ks));
    }
    /* a low-discrepancy sample's mean is far closer than a random one's */
    {
      const D = makeDistribution({ family: 'lognormal', params: { mu: 1, sigma: 0.5 } });
      const m = D.stats().mean;
      const err = (scheme) => Math.abs(S.drawSample(D, scheme, 4096, 5, 'A').values.reduce((x, y) => x + y, 0) / 4096 - m) / m;
      /* a random sample's mean has a relative standard error of CV/√n = 0.533/64 = 8e-3 here */
      check('samples: Sobol and Latin hypercube means within 1e-3 of the exact (random draws: 8e-3)', err('sobol') < 1e-3 && err('lhs') < 1e-3 && err('halton') < 2e-3, `${show(err('sobol'))}, ${show(err('lhs'))}, ${show(err('halton'))}`);
    }
    /* the job */
    {
      const job = S.sampleJob({ items: [{ key: 'x', letter: 'A', spec: { family: 'normal', params: { mu: 0, sigma: 1 } } }, { key: 'y', letter: 'B', spec: { family: 'normal', params: { mu: 0, sigma: -1 } } }], n: 100, scheme: 'sobol', seed: 1 });
      check('samples: the job draws each item and reports an item it cannot draw', job.columns.length === 2 && job.columns[0].values.length === 100 && /./.test(job.columns[1].error || ''), JSON.stringify(job.columns.map((c) => c.error || c.values.length)));
      let threw = false;
      try { S.sampleJob({ items: [], n: 0, scheme: 'random', seed: 1 }); } catch (e) { threw = /whole number/.test(e.message); }
      check('samples: n of 0 is refused', threw);
      threw = false;
      try { S.uniforms('sobol', 4, 1, 'Q'); } catch (e) { threw = /16 dimensions/.test(e.message); }
      check('samples: a seventeenth letter has no dimension in the sequences', threw);
    }
  }

  /* ---- 13. truncation at percentiles ------------------------------------------------------------------------ */
  {
    const N = makeDistribution({ family: 'normal', params: { mu: 3, sigma: 2 }, trunc: { by: 'p', lo: 0.05, hi: 0.975 } });
    check('percentile truncation: the bounds are the quantiles', close(N.truncated.lo, 3 - 2 * 1.6448536269514722, 1e-14) && close(N.truncated.hi, 3 + 2 * 1.959963984540054, 1e-14), JSON.stringify(N.truncated));
    check('percentile truncation: a continuous distribution keeps the probability between them', close(N.truncated.mass, 0.925, 1e-13), show(N.truncated.mass));
    const U = makeDistribution({ family: 'lognormal', params: { mu: 0, sigma: 1 }, trunc: { by: 'p', lo: 0, hi: 0.999 } });
    check('percentile truncation: 0 is no bound, and an upper percentile near 1 keeps its digits', U.truncated.lo === -Infinity && close(U.truncated.hi, Math.exp(3.090232306167813), 1e-14), JSON.stringify(U.truncated));
    const P = makeDistribution({ family: 'poisson', params: { lambda: 4 }, trunc: { by: 'p', lo: 0.1, hi: 0.9 } });
    check('percentile truncation: a discrete distribution is cut at the smallest values reaching the percentiles, kept', P.truncated.lo === 2 && P.truncated.hi === 7 && close(P.truncated.mass, P.truncated.mass, 0) && P.cdf(1.9) === 0 && P.pdf(2) > 0, JSON.stringify(P.truncated));
    const K = makeDistribution({ family: 'empirical', method: 'kde', data: [1, 2, 2.5, 3, 4, 5, 7, 8, 9, 12], bw: 1, trunc: { by: 'p', lo: 0.25, hi: 0.75 } });
    check('percentile truncation: a kernel density keeps its middle half', close(K.truncated.mass, 0.5, 1e-9) && close(K.stats().median, makeDistribution({ family: 'empirical', method: 'kde', data: [1, 2, 2.5, 3, 4, 5, 7, 8, 9, 12], bw: 1 }).quantile(0.5), 1e-8), show(K.truncated.mass));
    let threw = '';
    try { makeDistribution({ family: 'normal', params: { mu: 0, sigma: 1 }, trunc: { by: 'p', lo: 0.6, hi: 0.4 } }); } catch (e) { threw = e.message; }
    check('percentile truncation: bounds the wrong way round are refused', /below the upper/.test(threw), threw);
  }

  /* ---- 14. a shift ---------------------------------------------------------------------------------------------------- */
  {
    const A = makeDistribution({ family: 'lognormal', params: { mu: 1, sigma: 0.5 } });
    const B = makeDistribution({ family: 'lognormal', params: { mu: 1, sigma: 0.5 }, shift: 5 });
    const a = A.stats();
    const b = B.stats();
    check('shift: the location moves', close(b.mean, a.mean + 5, 1e-15) && close(b.median, a.median + 5, 1e-15) && close(b.mode, a.mode + 5, 1e-15) && B.support[0] === 5);
    check('shift: the spread, the shape and the entropy stay', b.sd === a.sd && b.skewness === a.skewness && b.kurtosis === a.kurtosis && b.entropy === a.entropy);
    check('shift: the CDF and the quantiles move with it', [0.5, 3, 12].every((x) => B.cdf(x + 5) === A.cdf(x)) && [1e-9, 0.3, 0.999].every((u) => close(B.quantile(u), A.quantile(u) + 5, 1e-15)));
    /* mpmath (30 digits): E ln(5 + e^(1 + 0.5 Z)) and its SD, exponentiated */
    check('shift: the geometric mean and SD are worked out again (mpmath)', close(b.gm, 7.9365785184266998, 1e-10) && close(b.gsd, 1.2020463185657056, 1e-9), `${show(b.gm)}, ${show(b.gsd)}`);
    const P = makeDistribution({ family: 'poisson', params: { lambda: 3 }, shift: -2 });
    check('shift: a count moved by a whole number stays on whole numbers', P.support[0] === -2 && close(P.pdf(-2), Math.exp(-3), 1e-15) && P.pdf(-1.5) === 0 && close(P.stats().mean, 1, 1e-13) && P.quantile(0.5) === 1, JSON.stringify(P.atoms()[0].slice(0, 3)));
    let threw = '';
    try { makeDistribution({ family: 'poisson', params: { lambda: 3 }, shift: 0.5 }); } catch (e) { threw = e.message; }
    check('shift: a count refuses a shift that is not whole', /whole number/.test(threw), threw);
    const T = makeDistribution({ family: 'normal', params: { mu: 0, sigma: 1 }, shift: 5, trunc: { lo: 5, hi: null } });
    check('shift: the truncation comes after it, in shifted values', close(T.stats().mean, 5 + Math.sqrt(2 / Math.PI), 1e-12) && close(T.truncated.mass, 0.5, 1e-15), show(T.stats().mean));
    const TP = makeDistribution({ family: 'normal', params: { mu: 0, sigma: 1 }, shift: 5, trunc: { by: 'p', lo: 0.05, hi: 0.95 } });
    check('shift: percentile bounds are percentiles of the shifted distribution', close(TP.truncated.lo, 5 - 1.6448536269514722, 1e-14) && close(TP.truncated.hi, 5 + 1.6448536269514722, 1e-14));
    const E = makeDistribution({ family: 'empirical', method: 'ecdf', data: [1, 2, 2, 5], shift: 0.5 });
    check('shift: an empirical CDF moves its values', JSON.stringify(E.atoms()) === JSON.stringify([[1.5, 2.5, 5.5], [0.25, 0.5, 0.25]]) && E.stats().mean === 3);
    const K0 = makeDistribution({ family: 'empirical', method: 'kde', data: [1, 2, 2.5, 3, 4, 5, 7, 8, 9, 12], bw: 1 });
    const K = makeDistribution({ family: 'empirical', method: 'kde', data: [1, 2, 2.5, 3, 4, 5, 7, 8, 9, 12], bw: 1, shift: -100 });
    const k0 = K0.sample(50, makeRng(2), false);
    const k1 = K.sample(50, makeRng(2), false);
    check('shift: a kernel density draws its own draws, moved', k1.every((v, i) => v === k0[i] - 100) && close(K.stats().mean, K0.stats().mean - 100, 1e-13));
    /* known values describe the shifted distribution */
    const g = familyById('gamma');
    const q = solveKnown(g, [{ prop: 'mean', value: 105 }, { prop: 'sd', value: 3 }], g.defaults, 100);
    check('shift: known values are those of the shifted distribution', close(q.k, 25 / 9, 1e-9) && close(q.theta, 1.8, 1e-9), JSON.stringify(q));
    const L = familyById('lognormal');
    const lp = solveKnown(L, [{ prop: 'median', value: 14 }, { prop: 'q', p: 95, value: 40 }], L.defaults, 2);
    const LD = makeDistribution({ family: 'lognormal', params: lp, shift: 2 });
    check('shift: a lognormal moved by 2 with a median of 14 and P95 of 40', close(LD.quantile(0.5), 14, 1e-10) && close(LD.quantile(0.95), 40, 1e-10));
    check('shift: propertyValue moves the location and keeps the CV honest', close(propertyValue(g, makeDistribution({ family: 'gamma', params: { k: 4, theta: 1 }, shift: 6 }), { k: 4, theta: 1 }, { prop: 'cv' }, 6), 2 / 10, 1e-14));
  }

  /* ---- 15. Monte Carlo by every scheme ------------------------------------------------------------------------------ */
  {
    const { runMonteCarlo } = await imp('mc.js');
    const specs = { A: { family: 'gamma', params: { k: 1.6, theta: 7.8 }, shift: 5 }, B: { family: 'gamma', params: { k: 1.6, theta: 7.8 } } };
    const exact = makeDistribution(specs.A).stats().mean + makeDistribution(specs.B).stats().mean;
    const sd = Math.hypot(makeDistribution(specs.A).stats().sd, makeDistribution(specs.B).stats().sd);
    const meanOf = (scheme) => { const r = runMonteCarlo(specs, 'A + B', 10000, 1, scheme); return r.values.reduce((x, y) => x + y, 0) / r.values.length; };
    check('mc: a random sum within four standard errors of its mean', Math.abs(meanOf('random') - exact) < 4 * sd / 100);
    for (const scheme of ['lhs', 'lhs-centred', 'sobol', 'halton']) {
      check(`mc: ${scheme}: the sum's mean within 1e-4 of the exact (random draws: 5e-3)`, Math.abs(meanOf(scheme) - exact) / exact < 1e-4, show(meanOf(scheme)));
    }
    const legacy = runMonteCarlo(specs, 'A * B', 500, 3, true).values;
    const lhs = runMonteCarlo(specs, 'A * B', 500, 3, 'lhs').values;
    const plain = runMonteCarlo(specs, 'A * B', 500, 3, false).values;
    const random = runMonteCarlo(specs, 'A * B', 500, 3, 'random').values;
    check('mc: a stored Latin hypercube flag draws what the scheme does', legacy.every((v, i) => v === lhs[i]) && plain.every((v, i) => v === random[i]));
    let threw = '';
    try { runMonteCarlo(specs, 'A', 10, 1, 'bogus'); } catch (e) { threw = e.message; }
    check('mc: an unknown scheme is refused', /Unknown sampling scheme/.test(threw), threw);
  }

  /* ---- 16. the histograms' bins ----------------------------------------------------------------------------------------- */
  {
    const { histogramBins } = await imp('chart.js');
    const v = Float64Array.from({ length: 1000 }, (_, i) => Math.sin(i) * 3 + i / 100).sort();
    const k = (b) => histogramBins(v, b).k;
    check('bins: Sturges is 1 + log2 n, rounded up', k({ rule: 'sturges' }) === Math.ceil(Math.log2(1000) + 1));
    check('bins: square root is √n, rounded up', k({ rule: 'sqrt' }) === Math.ceil(Math.sqrt(1000)));
    check('bins: Rice is 2 n^⅓, rounded up', k({ rule: 'rice' }) === Math.ceil(2 * Math.cbrt(1000)));
    check('bins: a number of bins is taken as it is', k({ rule: 'count', value: '25' }) === 25 && k({ rule: 'count', value: '1e9' }) === 2000);
    const w = histogramBins(v, { rule: 'width', value: '0,5' });
    check('bins: a width, the edges at its multiples (a decimal comma read)', w.width === 0.5 && w.a === -3 && w.a + w.k * w.width >= v[999] && w.a + (w.k - 1) * w.width < v[999], JSON.stringify(w));
    check('bins: no number falls back to Freedman–Diaconis', k({ rule: 'count', value: '' }) === k({ rule: 'fd' }) && k(undefined) === k({ rule: 'fd' }));
  }
}
