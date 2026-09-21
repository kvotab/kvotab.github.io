/* ==========================================================================
   EROSION_CORROSION.HTML: SULPHIDE DISTRIBUTIONS

   The tables of the workbook's sheet "HSData" -- HSForsmark, HSLaxemar and
   HSTest -- with the values the workbook holds (SKBdoc 1895159, v 2.0), plus
   the two generated distributions the later versions use in place of the
   one-point HSGeneric table: a shifted lognormal given by mean, standard
   deviation and shift (the 2.4 Python port), and a log10-normal given by its
   mean and standard deviation in log10 units (the @Risk workbook, SKBdoc
   2057353: 10^RiskNormal(-5.79757, 0.63849)).

   Concentrations are in mol/L. Every table is returned sorted in descending
   order because that is how the model reads it (see ec-model.js).

   HSForsmark: 40 sulphide analyses from Forsmark plus 6 below the detection
   limit set to 10^-6.9 (sheet "History", v 0_4). HSLaxemar: the distribution
   from the review version of the sulphide report (v 0_8). HSTest: 10 values
   1E-4·85/(85+k), k = 0..9, which with the test hydro file give corrosion
   times of 850,000 to 940,000 years in steps of 10,000 (SKBdoc 1895157,
   section 5).
   ========================================================================== */
(function (root, factory) {
  'use strict';
  const api = factory(root.ECModel || (typeof require === 'function' ? require('./ec-model.js') : null));
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ECHS = api;
}(typeof self !== 'undefined' ? self : this, function (ECModel) {
  'use strict';

  const HS_FORSMARK = Float64Array.from([
    0.00012006486621343476, 1.21936006985592e-05, 1.1476330069232181e-05, 1.0603131042225406e-05, 1.0072974490114138e-05, 9.761117694754565e-06,
    6.4242499844071555e-06, 5.363936880184613e-06, 4.9273373666812115e-06, 4.303623775962072e-06, 4.241252416890158e-06, 3.5863531466350657e-06,
    3.3992390694193183e-06, 3.3680533898833637e-06, 2.5260400424125205e-06, 2.3701116447327367e-06, 2.1206262084450826e-06, 1.933512131229336e-06,
    1.8087694130855074e-06, 1.4657269381899803e-06, 1.4657269381899803e-06, 1.060313104222541e-06, 1.0291274246865824e-06, 9.043847065427537e-07,
    8.420133474708392e-07, 7.48456308862968e-07, 7.172706293270124e-07, 5.613422316472265e-07, 5.613422316472265e-07, 4.36599513503399e-07,
    3.742281544314839e-07, 3.4304247489552707e-07, 3.1185679535957037e-07, 2.8067111582361323e-07, 2.8067111582361323e-07, 2.8067111582361323e-07,
    2.494854362876566e-07, 2.1829975675169945e-07, 1.2474271814382826e-07, 1.2474271814382826e-07, 1.2474271814382826e-07, 1.2474271814382826e-07,
    1.2474271814382826e-07, 1.2474271814382826e-07, 1.2474271814382826e-07, 1.2474271814382826e-07,
  ]);

  const HS_LAXEMAR = Float64Array.from([
    7.79641988398927e-05, 3.49279610802719e-05, 2.7568140709786014e-05, 2.3139774215680115e-05, 2.023950601883612e-05, 1.652841015405724e-05,
    1.256782885299068e-05, 9.043847065427545e-06, 8.919104347283718e-06, 5.800536393688016e-06, 5.613422316472261e-06, 5.145637123432909e-06,
    4.147695378282289e-06, 2.80671115823613e-06, 2.5572257219484773e-06, 2.3077402856608215e-06, 2.182997567516993e-06, 1.7152123744776373e-06,
    1.652841015405725e-06, 1.5592839767978535e-06, 1.4345412586540248e-06, 1.1850558223663684e-06, 1.1226844632944531e-06, 9.979417451506246e-07,
    9.66756065614668e-07, 9.355703860787124e-07, 9.043847065427537e-07, 8.73199027006798e-07, 7.796419883989268e-07, 7.796419883989268e-07,
    6.860849497910543e-07, 6.548992702550992e-07, 5.613422316472265e-07, 5.301565521112706e-07, 3.1185679535957037e-07, 3.1185679535957037e-07,
    2.1829975675169945e-07, 2.1829975675169945e-07, 1.871140772157423e-07, 1.2474271814382826e-07, 1.2474271814382826e-07, 1.2474271814382826e-07,
    9.355703860787113e-08, 9.355703860787113e-08, 9.355703860787113e-08, 9.355703860787113e-08, 9.355703860787113e-08, 9.355703860787113e-08,
    9.355703860787113e-08, 9.355703860787113e-08, 9.355703860787113e-08,
  ]);

  /** 1E-4·85/(85+k): the table the code documentation's test case expects. */
  const HS_TEST = Float64Array.from(Array.from({ length: 10 }, (_, k) => 1e-4 * 85 / (85 + k)));

  const TABLES = Object.freeze({
    HSForsmark: { label: 'HSForsmark: Forsmark groundwater, 46 values (PSAR base case)', values: HS_FORSMARK },
    HSLaxemar: { label: 'HSLaxemar: Laxemar groundwater, 51 values', values: HS_LAXEMAR },
    HSTest: { label: 'HSTest: 10 values for the code test', values: HS_TEST },
  });

  /** Defaults of the generated distributions. */
  const GENERIC_DEFAULTS = Object.freeze({
    kind: 'shifted-lognormal',   // or 'log10-normal'
    mean: 6.29301e-6,            // mol/L    (2.4 port: hs_generic_mean)
    std: 3.16131e-5,             // mol/L    (hs_generic_std)
    shift: 1.2e-7,               // mol/L    (hs_generic_shift)
    mu10: -5.79757,              // log10(mol/L)   (@Risk workbook)
    sigma10: 0.63849,
    n: 1000,
  });

  /**
   * Quantiles of a lognormal distribution, descending.
   *
   * Deterministic midpoint quantiles p_k = (k - 1/2)/n rather than random
   * draws: the 2.4 port draws n random probabilities with a fixed seed and
   * the @Risk workbook samples with Latin hypercube; both are approximations
   * of exactly these quantiles, and these need no random number generator to
   * be reproduced.
   */
  function generic(opts) {
    const o = { ...GENERIC_DEFAULTS, ...(opts || {}) };
    const n = Math.max(1, Math.min(200000, Math.round(o.n)));
    const out = new Float64Array(n);
    if (o.kind === 'log10-normal') {
      for (let k = 0; k < n; k++) {
        const p = (k + 0.5) / n;
        out[n - 1 - k] = Math.pow(10, o.mu10 + o.sigma10 * ECModel.normInv(p));
      }
      return out;
    }
    // A shifted lognormal with the given arithmetic mean and standard
    // deviation of the unshifted part: sigma² = ln(1 + (std/mean)²),
    // mu = ln(mean) - sigma²/2.
    const s2 = Math.log(1 + (o.std / o.mean) ** 2);
    const mu = Math.log(o.mean) - s2 / 2;
    const s = Math.sqrt(s2);
    for (let k = 0; k < n; k++) {
      const p = (k + 0.5) / n;
      out[n - 1 - k] = Math.exp(mu + s * ECModel.normInv(p)) + o.shift;
    }
    return out;
  }

  /**
   * Numbers out of pasted text: any separator, decimal comma allowed when no
   * dot occurs in the token, and anything that is not a positive finite
   * number is dropped and counted.
   */
  function parseCustom(text) {
    const values = [];
    let dropped = 0;
    const take = (tok) => {
      const x = Number(tok);
      if (Number.isFinite(x) && x > 0) values.push(x); else if (tok) dropped++;
    };
    for (const chunk of String(text || '').split(/[\s;]+/)) {
      if (!chunk) continue;
      if (!chunk.includes(',')) { take(chunk); continue; }
      // A comma inside a chunk is a decimal comma when the chunk is one
      // number written that way, and a separator otherwise.
      if (!chunk.includes('.') && /^[-+]?\d+,\d+(?:[eE][-+]?\d+)?$/.test(chunk)) { take(chunk.replace(',', '.')); continue; }
      for (const tok of chunk.split(',')) take(tok);
    }
    return { values: Float64Array.from(values).sort((a, b) => b - a), dropped };
  }

  function describe(values) {
    const v = Array.from(values).filter((x) => Number.isFinite(x) && x > 0);
    if (!v.length) return { n: 0, min: null, max: null, mean: null };
    return { n: v.length, min: Math.min(...v), max: Math.max(...v), mean: v.reduce((s, x) => s + x, 0) / v.length };
  }

  return { TABLES, HS_FORSMARK, HS_LAXEMAR, HS_TEST, GENERIC_DEFAULTS, generic, parseCustom, describe };
}));
