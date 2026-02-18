(function () {
  'use strict';

  // ---------- inverse-CDF helpers ----------
  function invUnif(p, a, b) { return a + (b - a) * p; }
  function invTriang(p, a, b, m) {
    const fc = (m - a) / (b - a);
    return p < fc
      ? a + Math.sqrt((b - a) * (m - a) * p)
      : b - Math.sqrt((b - a) * (b - m) * (1 - p));
  }
  function invDtriang(p, a, b, m) {
    return p <= 0.5
      ? a + Math.sqrt(2 * p) * (m - a)
      : b - (b - m) * Math.sqrt(2 * (1 - p));
  }
  function invNorm(p, mean, std) { return mean + std * Math.SQRT2 * erfinv(2 * p - 1); }
  function invExp(p, mean) { return -mean * Math.log(1 - p); }
  function invLogu(p, a, b) { return Math.exp(invUnif(p, Math.log(a), Math.log(b))); }
  function invLogt(p, a, b, m) { return Math.exp(invTriang(p, Math.log(a), Math.log(b), Math.log(m))); }
  function invLogdt(p, a, b, m) { return Math.exp(invDtriang(p, Math.log(a), Math.log(b), Math.log(m))); }
  function invLogn(p, gm, gsd) { return Math.exp(invNorm(p, Math.log(gm), Math.log(gsd))); }

  // ---------- empirical/inverse-quantile (accept BigInt) ----------
  function invEmpirical(p, data) {
    const arr = Array.from(data, toNumber).sort((a, b) => a - b);
    if (arr.length === 0) return NaN;
    const idx = p * (arr.length - 1);
    const lo = Math.floor(idx);
    const hi = Math.min(lo + 1, arr.length - 1);
    const frac = idx - lo;
    return arr[lo] + frac * (arr[hi] - arr[lo]);
  }

  // ---------- CDF / PDF helpers ----------
  function cdfForDist(type, x, args) {
    switch (type) {
      case 'uniform': case 'unif': {
        const { a, b } = args; return x <= a ? 0 : x >= b ? 1 : (x - a) / (b - a);
      }
      case 'triangular': case 'triang': {
        const { a, b, m } = args;
        if (x <= a) return 0; if (x >= b) return 1;
        return x <= m ? (x - a) ** 2 / ((m - a) * (b - a)) : 1 - (b - x) ** 2 / ((b - a) * (b - m));
      }
      case 'normal': case 'norm': {
        const { mean, std } = args;
        return 0.5 * (1 + erf((x - mean) / (std * Math.SQRT2)));
      }
      case 'exponential': case 'exp': {
        const { mean } = args; return x <= 0 ? 0 : 1 - Math.exp(-x / mean);
      }
      case 'loguniform': case 'logu': case 'logunif': {
        const { a, b } = args; return x <= a ? 0 : x >= b ? 1 : (Math.log(x) - Math.log(a)) / (Math.log(b) - Math.log(a));
      }
      case 'lognormal': case 'logn': case 'lognorm': {
        const { gm, gsd } = args; return 0.5 * (1 + erf((Math.log(x) - Math.log(gm)) / (Math.log(gsd) * Math.SQRT2)));
      }
      default: return null;
    }
  }

  function pdfEval(type, x, args) {
    switch (type) {
      case 'uniform': case 'unif': {
        const { a, b } = args; return (x >= a && x <= b) ? 1 / (b - a) : 0;
      }
      case 'triangular': case 'triang': {
        const { a, b, m } = args;
        if (x < a || x > b) return 0;
        return x <= m ? 2 * (x - a) / ((b - a) * (m - a)) : 2 * (b - x) / ((b - a) * (b - m));
      }
      case 'dtriangular': case 'dtriang': {
        const { a, b, m } = args;
        if (x < a || x > b) return 0;
        return x <= m ? (x - a) / ((m - a) * (m - a)) : (b - x) / ((b - m) * (b - m));
      }
      case 'normal': case 'norm': {
        const { mean, std } = args; const z = (x - mean) / std; return Math.exp(-0.5 * z * z) / (std * Math.sqrt(2 * Math.PI));
      }
      case 'exponential': case 'exp': {
        const { mean } = args; return x < 0 ? 0 : (1 / mean) * Math.exp(-x / mean);
      }
      case 'loguniform': case 'logu': case 'logunif': {
        const { a, b } = args; return (x <= a || x >= b) ? 0 : 1 / (x * (Math.log(b) - Math.log(a)));
      }
      case 'logtriangular': case 'logt': case 'logtriang': {
        const { a, b, m } = args;
        if (x <= a || x >= b) return 0;
        const la = Math.log(a), lb = Math.log(b), lm = Math.log(m), lx = Math.log(x);
        const fLog = lx <= lm ? 2 * (lx - la) / ((lb - la) * (lm - la)) : 2 * (lb - lx) / ((lb - la) * (lb - lm));
        return fLog / x;
      }
      case 'logdtriangular': case 'logdt': case 'logdtriang': {
        const { a, b, m } = args;
        if (x <= a || x >= b) return 0;
        const la = Math.log(a), lb = Math.log(b), lm = Math.log(m), lx = Math.log(x);
        const fLog = lx <= lm ? (lx - la) / ((lm - la) * (lm - la)) : (lb - lx) / ((lb - lm) * (lb - lm));
        return fLog / x;
      }
      case 'lognormal': case 'logn': case 'lognorm': {
        const { gm, gsd } = args; if (x <= 0) return 0;
        const mu = Math.log(gm), sigma = Math.log(gsd), z = (Math.log(x) - mu) / sigma;
        return Math.exp(-0.5 * z * z) / (x * sigma * Math.sqrt(2 * Math.PI));
      }
      default: return null;
    }
  }

  // ---------- inverse-CDF map ----------
  const DIST_INV = {
    'unif':      (p, a) => invUnif(p, a.a, a.b),
    'uniform':   (p, a) => invUnif(p, a.a, a.b),
    'triang':    (p, a) => invTriang(p, a.a, a.b, a.m),
    'triangular':(p, a) => invTriang(p, a.a, a.b, a.m),
    'dtriang':   (p, a) => invDtriang(p, a.a, a.b, a.m),
    'dtriangular': (p, a) => invDtriang(p, a.a, a.b, a.m),
    'norm':      (p, a) => invNorm(p, a.mean, a.std),
    'normal':    (p, a) => invNorm(p, a.mean, a.std),
    'exp':       (p, a) => invExp(p, a.mean),
    'exponential': (p, a) => invExp(p, a.mean),
    'logu':      (p, a) => invLogu(p, a.a, a.b),
    'logunif':   (p, a) => invLogu(p, a.a, a.b),
    'loguniform':(p, a) => invLogu(p, a.a, a.b),
    'logt':      (p, a) => invLogt(p, a.a, a.b, a.m),
    'logtriang': (p, a) => invLogt(p, a.a, a.b, a.m),
    'logtriangular': (p, a) => invLogt(p, a.a, a.b, a.m),
    'logdt':     (p, a) => invLogdt(p, a.a, a.b, a.m),
    'logdtriang':(p, a) => invLogdt(p, a.a, a.b, a.m),
    'logdtriangular': (p, a) => invLogdt(p, a.a, a.b, a.m),
    'logn':      (p, a) => invLogn(p, a.gm, a.gsd),
    'lognorm':   (p, a) => invLogn(p, a.gm, a.gsd),
    'lognormal': (p, a) => invLogn(p, a.gm, a.gsd),
    'emp':       (p, a) => invEmpirical(p, a.data),
    'empirical': (p, a) => invEmpirical(p, a.data),
  };

  // ---------- sample generator ----------
  function generatePdfSamples(pdf, n = 1000) {
    if (!pdf || !pdf.type) return null;
    const typeKey = pdf.type.toLowerCase();
    if (typeKey === 'raw') return null;
    const invFn = DIST_INV[typeKey];
    if (!invFn) return null;

    const args = { ...pdf }; delete args.type;
    const pmin = pdf.pmin ?? 0, pmax = pdf.pmax ?? 1, trmin = pdf.trmin ?? null, trmax = pdf.trmax ?? null, shift = pdf.shift ?? 0;

    let effPmin = pmin, effPmax = pmax;
    if (trmin !== null) {
      const c = cdfForDist(typeKey, trmin, args);
      if (c !== null) effPmin = Math.max(effPmin, c);
    }
    if (trmax !== null) {
      const c = cdfForDist(typeKey, trmax, args);
      if (c !== null) effPmax = Math.min(effPmax, c);
    }
    if (effPmin >= effPmax) effPmin = pmin;

    const samples = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      const u = Math.random();
      const p = effPmin + (effPmax - effPmin) * u;
      samples[i] = invFn(p, args) + shift;
    }
    return samples;
  }

  // ---------- pretty label ----------
  function pdfLabel(pdf) {
    if (!pdf || !pdf.type) return '';
    const t = pdf.type;
    const parts = [t];
    const keys = Object.keys(pdf).filter(k => !['type','pmin','pmax','trmin','trmax','shift','include_deterministic'].includes(k));
    for (const k of keys) {
      const v = pdf[k];
      if (typeof v === 'number') {
        const s = Number.isInteger(v) ? String(v) : Number(v.toPrecision(4)).toString();
        parts.push(`${k}=${s}`);
      }
    }
    return parts.join(', ');
  }

  // ---------- analytic PDF overlay ----------
  function computePdfOverlay(spec, nPoints = 200) {
    if (!spec || !spec.type) return null;
    const typeKey = spec.type.toLowerCase();
    if (['raw','emp','empirical'].includes(typeKey)) return null;
    const invFn = DIST_INV[typeKey];
    if (!invFn) return null;

    const args = { ...spec };
    const shift = spec.shift ?? 0;
    const pmin = spec.pmin ?? 0, pmax = spec.pmax ?? 1, trmin = spec.trmin ?? null, trmax = spec.trmax ?? null;

    let effPmin = pmin, effPmax = pmax;
    if (trmin !== null) {
      const c = cdfForDist(typeKey, trmin, args);
      if (c !== null) effPmin = Math.max(effPmin, c);
    }
    if (trmax !== null) {
      const c = cdfForDist(typeKey, trmax, args);
      if (c !== null) effPmax = Math.min(effPmax, c);
    }
    if (effPmin >= effPmax) { effPmin = pmin; effPmax = pmax; }

    const eps = 1e-9;
    const xMin = invFn(Math.max(effPmin, eps), args) + shift;
    const xMax = invFn(Math.min(effPmax, 1 - eps), args) + shift;
    if (!isFinite(xMin) || !isFinite(xMax) || xMin >= xMax) return null;

    const normFactor = effPmax - effPmin;
    if (normFactor <= 0) return null;

    const x = [], y = [];
    for (let i = 0; i <= nPoints; i++) {
      const xi = xMin + (xMax - xMin) * i / nPoints;
      const fVal = pdfEval(typeKey, xi - shift, args);
      if (fVal !== null && isFinite(fVal)) {
        x.push(xi);
        y.push(fVal / normFactor);
      }
    }
    return x.length > 0 ? { x, y } : null;
  }

  // ---------- utilities: BigInt -> Number and normalization ----------
  function toNumber(v) {
    if (typeof v === 'bigint') {
      const n = Number(v);
      if (!Number.isSafeInteger(n)) console.warn('BigInt -> Number conversion (precision loss possible):', v);
      return n;
    }
    return v;
  }

  function jsonReplacer(key, value) {
    if (typeof value === 'bigint') return Number(value);
    if (value && typeof value === 'object' && value.length !== undefined) return Array.from(value);
    return value;
  }

  function normalizeDataArray(data) {
    if (Array.isArray(data)) return data.map(toNumber);
    if (data && typeof data === 'object' && data.length !== undefined) return Array.from(data, toNumber);
    return [toNumber(data)];
  }

  // expose API
  window.PDFSampler = {
    generatePdfSamples,
    computePdfOverlay,
    pdfLabel,
    normalizeDataArray,
    toNumber,
    jsonReplacer,
    invEmpirical,
    pdfEval,
    cdfForDist,
    // export a read-only snapshot of supported inverse-CDFs
    DIST_INV: Object.freeze(Object.assign({}, DIST_INV)),    // human-readable list of supported distribution keys
    supported() { return Object.keys(DIST_INV).slice().sort(); },    // expose erf/erfinv if available (pass-through to global functions)
    erf: typeof window.erf === 'function' ? window.erf : undefined,
    erfinv: typeof window.erfinv === 'function' ? window.erfinv : undefined
  };
})();
