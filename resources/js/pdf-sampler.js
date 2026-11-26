(function () {
  'use strict';

  // ---------- numpy's random numbers ----------
  // A distribution saved with the state of its random generator (pdf.state,
  // {bit_generator: 'PCG64', state: {state, inc}, has_uint32, uinteger}) is
  // sampled as the Python code samples it with numpy: PCG64 (XSL RR 128/64),
  // Generator.random and, for Latin hypercube sampling,
  // Generator.choice(n, n, replace=False). The uniform numbers and their
  // order are numpy's, bit for bit, so value i is the value of iteration i.
  const MASK64 = (1n << 64n) - 1n;
  const MASK128 = (1n << 128n) - 1n;
  const PCG_MULT = (2549297995355413924n << 64n) + 4865540595714422341n;
  const TWO_M53 = 1 / 9007199254740992;

  /** An integer of a saved state as a BigInt: text or BigInt, or a Number that is exact; null if it was rounded. */
  function stateInt(v) {
    if (typeof v === 'bigint') return v;
    if (typeof v === 'string' && /^\d+$/.test(v)) return BigInt(v);
    if (typeof v === 'number' && Number.isSafeInteger(v) && v >= 0) return BigInt(v);
    return null;
  }

  /** A numpy PCG64 generator in a saved state, null if the state is not PCG64 or its integers were rounded. */
  function pcg64(saved) {
    if (!saved || saved.bit_generator !== 'PCG64' || !saved.state) return null;
    let s = stateInt(saved.state.state);
    const inc = stateInt(saved.state.inc);
    if (s === null || inc === null) return null;
    let hasUint32 = Number(saved.has_uint32 || 0);
    let uinteger = Number(saved.uinteger || 0) >>> 0;
    const next64 = () => {
      s = (s * PCG_MULT + inc) & MASK128;
      const hi = s >> 64n, x = hi ^ (s & MASK64), rot = hi >> 58n;
      return ((x >> rot) | (x << ((64n - rot) & 63n))) & MASK64;
    };
    return {
      next64,
      // the low 32 bits of a 64-bit number, then its high 32 bits
      next32() {
        if (hasUint32) { hasUint32 = 0; return uinteger; }
        const v = next64();
        hasUint32 = 1;
        uinteger = Number(v >> 32n);
        return Number(v & 0xFFFFFFFFn);
      },
      nextDouble() { return Number(next64() >> 11n) * TWO_M53; }
    };
  }

  /** numpy's integer in [0, rng] (rng < 2^32): Lemire's method on 32-bit numbers. */
  function boundedLemire32(g, rng) {
    if (rng === 0) return 0;
    const excl = rng + 1, exclBig = BigInt(excl);
    let m = BigInt(g.next32()) * exclBig;
    let leftover = Number(m & 0xFFFFFFFFn);
    if (leftover < excl) {
      const threshold = (0xFFFFFFFF - rng) % excl;
      while (leftover < threshold) {
        m = BigInt(g.next32()) * exclBig;
        leftover = Number(m & 0xFFFFFFFFn);
      }
    }
    return Number(m >> 32n);
  }

  /** numpy's shuffle of data[first..n-1], from the end. */
  function shuffleInt(g, n, first, data) {
    for (let i = n - 1; i >= first; i--) {
      const j = boundedLemire32(g, i);
      const t = data[j]; data[j] = data[i]; data[i] = t;
    }
  }

  function genMask(v) {
    v |= v >>> 1; v |= v >>> 2; v |= v >>> 4; v |= v >>> 8; v |= v >>> 16;
    return v >>> 0;
  }

  /** numpy's Generator.choice(popSize, size, replace=false): a tail shuffle or Floyd's algorithm, then a shuffle. */
  function choiceNoReplace(g, popSize, size) {
    if (popSize > 2 ** 30) throw new RangeError('too many samples');
    if (popSize > 10000 && size > Math.floor(popSize / 50)) {
      const idx = new Array(popSize);
      for (let i = 0; i < popSize; i++) idx[i] = i;
      shuffleInt(g, popSize, Math.max(popSize - size, 1), idx);
      return idx.slice(popSize - size);
    }
    const idx = new Array(size).fill(0);
    const mask = genMask(Math.trunc(1.2 * size));
    const hash = new Int32Array(mask + 1).fill(-1);
    for (let j = popSize - size; j < popSize; j++) {
      const val = boundedLemire32(g, j);
      let loc = val & mask;
      while (hash[loc] !== -1 && hash[loc] !== val) loc = (loc + 1) & mask;
      if (hash[loc] === -1) {
        hash[loc] = val;
        idx[j - popSize + size] = val;
      } else {
        loc = j & mask;
        while (hash[loc] !== -1) loc = (loc + 1) & mask;
        hash[loc] = j;
        idx[j - popSize + size] = j;
      }
    }
    shuffleInt(g, size, 1, idx);
    return idx;
  }

  /**
   * The n uniform numbers of a saved state, as the Python code draws them:
   * numpy's random numbers in [0, 1), and with lhs a stratum each, in
   * numpy's random order. Null if the state can't be used.
   */
  function uniformsFromState(saved, n, lhs) {
    const g = pcg64(saved);
    if (!g || !(n >= 1)) return null;
    const x = new Float64Array(n);
    for (let i = 0; i < n; i++) x[i] = g.nextDouble();
    if (lhs) {
      const strata = choiceNoReplace(g, n, n);
      for (let i = 0; i < n; i++) x[i] = (strata[i] + x[i]) / n;
    }
    return x;
  }

  // ---------- scipy's normal distribution (Cephes ndtri and erfc) ----------
  // The Python code's normal quantiles are scipy's erfcinv(y) = -ndtri(y/2)/sqrt(2)
  // and its normal probabilities scipy's erfc, both Cephes. These are the
  // same algorithms and coefficients; values can differ from scipy's in the
  // last binary digit, where its build fuses a multiply and an add or its
  // math library rounds log or exp otherwise.
  function polevl(x, c) { let a = c[0]; for (let i = 1; i < c.length; i++) a = a * x + c[i]; return a; }
  function p1evl(x, c) { let a = x + c[0]; for (let i = 1; i < c.length; i++) a = a * x + c[i]; return a; }
  const NDTRI_P0 = [-5.99633501014107895267E1, 9.80010754185999661536E1, -5.66762857469070293439E1, 1.39312609387279679503E1, -1.23916583867381258016E0];
  const NDTRI_Q0 = [1.95448858338141759834E0, 4.67627912898881538453E0, 8.63602421390890590575E1, -2.25462687854119370527E2, 2.00260212380060660359E2, -8.20372256168333339912E1, 1.59056225126211695515E1, -1.18331621121330003142E0];
  const NDTRI_P1 = [4.05544892305962419923E0, 3.15251094599893866154E1, 5.71628192246421288162E1, 4.40805073893200834700E1, 1.46849561928858024014E1, 2.18663306850790267539E0, -1.40256079171354495875E-1, -3.50424626827848203418E-2, -8.57456785154685413611E-4];
  const NDTRI_Q1 = [1.57799883256466749731E1, 4.53907635128879210584E1, 4.13172038254672030440E1, 1.50425385692907503408E1, 2.50464946208309415979E0, -1.42182922854787788574E-1, -3.80806407691578277194E-2, -9.33259480895457427372E-4];
  const NDTRI_P2 = [3.23774891776946035970E0, 6.91522889068984211695E0, 3.93881025292474443415E0, 1.33303460815807542389E0, 2.01485389549179081538E-1, 1.23716634817820021358E-2, 3.01581553508235416007E-4, 2.65806974686737550832E-6, 6.23974539184983293730E-9];
  const NDTRI_Q2 = [6.02427039364742014255E0, 3.67983563856160859403E0, 1.37702099489081330271E0, 2.16236993594496635890E-1, 1.34204006088543189037E-2, 3.28014464682127739104E-4, 2.89247864745380683936E-6, 6.79019408009981274425E-9];
  const S2PI = 2.50662827463100050242E0;
  const EXP_M2 = 0.13533528323661269189;

  function ndtri(y0) {
    if (y0 === 0) return -Infinity;
    if (y0 === 1) return Infinity;
    if (!(y0 > 0 && y0 < 1)) return NaN;
    let code = 1, y = y0;
    if (y > 1.0 - EXP_M2) { y = 1.0 - y; code = 0; }
    if (y > EXP_M2) {
      y = y - 0.5;
      const y2 = y * y;
      return (y + y * (y2 * polevl(y2, NDTRI_P0) / p1evl(y2, NDTRI_Q0))) * S2PI;
    }
    const x = Math.sqrt(-2.0 * Math.log(y));
    const x0 = x - Math.log(x) / x;
    const z = 1.0 / x;
    const x1 = x < 8.0 ? z * polevl(z, NDTRI_P1) / p1evl(z, NDTRI_Q1) : z * polevl(z, NDTRI_P2) / p1evl(z, NDTRI_Q2);
    return code !== 0 ? -(x0 - x1) : x0 - x1;
  }

  function erfcinvScipy(y) {
    if (y > 0 && y < 2) return -ndtri(0.5 * y) * Math.SQRT1_2;
    if (y === 0) return Infinity;
    if (y === 2) return -Infinity;
    return NaN;
  }

  const ERFC_P = [2.46196981473530512524E-10, 5.64189564831068821977E-1, 7.46321056442269912687E0, 4.86371970985681366614E1, 1.96520832956077098242E2, 5.26445194995477358631E2, 9.34528527171957607540E2, 1.02755188689515710272E3, 5.57535335369399327526E2];
  const ERFC_Q = [1.32281951154744992508E1, 8.67072140885989742329E1, 3.54937778887819891062E2, 9.75708501743205489753E2, 1.82390916687909736289E3, 2.24633760818710981792E3, 1.65666309194161350182E3, 5.57535340817727675546E2];
  const ERFC_R = [5.64189583547755073984E-1, 1.27536670759978104416E0, 5.01905042251180477414E0, 6.16021097993053585195E0, 7.40974269950448939160E0, 2.97886665372100240670E0];
  const ERFC_S = [2.26052863220117276590E0, 9.39603524938001434673E0, 1.20489539808096656605E1, 1.70814450747565897222E1, 9.60896809063285878198E0, 3.36907645100081516050E0];
  const ERF_T = [9.60497373987051638749E0, 9.00260197203842689217E1, 2.23200534594684319226E3, 7.00332514112805075473E3, 5.55923013010394962768E4];
  const ERF_U = [3.35617141647503099647E1, 5.21357949780152679795E2, 4.59432382970980127987E3, 2.26290000613890934246E4, 4.92673942608635921086E4];
  const MAXLOG = 7.09782712893383996843E2;

  function erfScipy(x) {
    if (Number.isNaN(x)) return NaN;
    if (x < 0) return -erfScipy(-x);
    if (Math.abs(x) > 1.0) return 1.0 - erfcScipy(x);
    const z = x * x;
    return x * polevl(z, ERF_T) / p1evl(z, ERF_U);
  }

  function erfcScipy(a) {
    if (Number.isNaN(a)) return NaN;
    const x = a < 0 ? -a : a;
    if (x < 1.0) return 1.0 - erfScipy(a);
    let z = -a * a;
    if (z < -MAXLOG) return a < 0 ? 2.0 : 0.0;
    z = Math.exp(z);
    const p = x < 8.0 ? polevl(x, ERFC_P) : polevl(x, ERFC_R);
    const q = x < 8.0 ? p1evl(x, ERFC_Q) : p1evl(x, ERFC_S);
    let y = (z * p) / q;
    if (a < 0) y = 2.0 - y;
    return y !== 0 ? y : (a < 0 ? 2.0 : 0.0);
  }

  // ---------- the Python code's distributions ----------
  // The probabilities and quantiles of the Python code, operation for
  // operation, so its samples come out the same.
  const sq = (d) => d * d;
  const PY_UNIF = {
    args: ['a', 'b'], valid: (a) => a.a < a.b,
    cdf: (x, a) => (x >= a.b ? 1 : (a.a < x && x < a.b) ? (x - a.a) / (a.b - a.a) : 0),
    inv: (p, a) => a.a + (a.b - a.a) * p
  };
  const PY_TRIANG = {
    args: ['a', 'b', 'm'], valid: (a) => a.a <= a.m && a.m <= a.b && a.a < a.b,
    cdf: (x, a) => {
      let p = 0;
      if (x > a.a && x <= a.m) p = sq(x - a.a) / ((a.m - a.a) * (a.b - a.a));
      if (x > a.m && x < a.b) p = 1 - sq(a.b - x) / ((a.b - a.a) * (a.b - a.m));
      if (x >= a.b) p = 1;
      return p;
    },
    inv: (p, a) => {
      const fc = (a.m - a.a) / (a.b - a.a);
      if (p < fc) return a.a + Math.sqrt((a.b - a.a) * (a.m - a.a) * p);
      if (p >= fc) return a.b - Math.sqrt((a.b - a.a) * (a.b - a.m) * (1 - p));
      return NaN;
    }
  };
  const PY_DTRIANG = {
    args: ['a', 'b', 'm'], valid: PY_TRIANG.valid,
    cdf: (x, a) => {
      let p = 0;
      if (x > a.a && x <= a.m) p = sq(x - a.a) / (2 * sq(a.m - a.a));
      if (x > a.m && x <= a.b) p = 1 - sq(a.b - x) / (2 * sq(a.b - a.m));
      if (x >= a.b) p = 1;
      return p;
    },
    inv: (p, a) => {
      if (p >= 0 && p <= 0.5) return a.a + Math.sqrt(2 * p) * (a.m - a.a);
      if (p > 0.5 && p <= 1) return a.b - (a.b - a.m) * Math.sqrt(2 * (1 - p));
      return NaN;
    }
  };
  const PY_NORM = {
    args: ['mean', 'std'], valid: (a) => a.std > 0,
    cdf: (x, a) => 0.5 * erfcScipy(-(x - a.mean) / (a.std * Math.SQRT2)),
    inv: (p, a) => -Math.SQRT2 * erfcinvScipy(2 * p) * a.std + a.mean
  };
  const PY_EXP = {
    args: ['mean'], valid: (a) => a.mean > 0,
    cdf: (x, a) => (x > 0 ? 1 - Math.exp(-x / a.mean) : 0),
    inv: (p, a) => -a.mean * Math.log(1 - p)
  };
  // The logarithmic distributions are the linear ones of the logarithms
  const logOf = (lin, names) => ({
    args: lin.args.map(k => names[k] || k),
    cdf: (x, a) => lin.cdf(Math.log(x), Object.fromEntries(lin.args.map(k => [k, Math.log(a[names[k] || k])]))),
    inv: (p, a) => Math.exp(lin.inv(p, Object.fromEntries(lin.args.map(k => [k, Math.log(a[names[k] || k])]))))
  });
  const PY_LOGU = { ...logOf(PY_UNIF, {}), valid: (a) => a.a < a.b && a.a > 0 };
  const PY_LOGT = { ...logOf(PY_TRIANG, {}), valid: (a) => PY_TRIANG.valid(a) && a.a > 0 };
  const PY_LOGDT = { ...logOf(PY_DTRIANG, {}), valid: (a) => PY_TRIANG.valid(a) && a.a > 0 };
  const PY_LOGN = { ...logOf(PY_NORM, { mean: 'gm', std: 'gsd' }), valid: (a) => a.gsd > 0 && a.gm > 0 };
  const PY_DIST = {
    unif: PY_UNIF, uniform: PY_UNIF,
    triang: PY_TRIANG, triangular: PY_TRIANG,
    dtriang: PY_DTRIANG, dtriangular: PY_DTRIANG,
    norm: PY_NORM, normal: PY_NORM,
    exp: PY_EXP, exponential: PY_EXP,
    logu: PY_LOGU, logunif: PY_LOGU, loguniform: PY_LOGU,
    logt: PY_LOGT, logtriang: PY_LOGT, logtriangular: PY_LOGT,
    logdt: PY_LOGDT, logdtriang: PY_LOGDT, logdtriangular: PY_LOGDT,
    logn: PY_LOGN, lognorm: PY_LOGN, lognormal: PY_LOGN
  };

  // How the Python code draws, by default: Latin hypercube sampling
  const sampleOptions = { lhs: true };

  /** Whether a distribution has a usable saved state, so its samples are those of the Python code. */
  function isExact(pdf) {
    return !!(pdf && pdf.state && PY_DIST[String(pdf.type || '').toLowerCase()] && pcg64(pdf.state));
  }

  /**
   * The n samples of a distribution with a saved state, as the Python code
   * draws them (its Distribution(pdf, n, lhs).rnd()): the uniform numbers of
   * the state, scaled into [pmin, pmax] (narrowed to the probabilities of
   * trmin and trmax), through the quantile function, plus shift. Null where
   * the Python code would raise an error, or without a usable state.
   */
  function samplesFromState(pdf, n, lhs = sampleOptions.lhs) {
    const dist = PY_DIST[String(pdf && pdf.type || '').toLowerCase()];
    if (!dist) return null;
    const args = {};
    for (const k of dist.args) {
      const v = pdf[k];
      if (v === undefined || v === null) return null;
      args[k] = Number(v);
    }
    if (!dist.valid(args)) return null;
    let pmin = pdf.pmin ?? 0, pmax = pdf.pmax ?? 1;
    if (pmin < 0 || pmax > 1 || pmin >= pmax) return null;
    const u = uniformsFromState(pdf.state, n, lhs);
    if (!u) return null;
    // as Python's max and min, which keep the first unless the second is larger (smaller)
    if (pdf.trmin !== undefined && pdf.trmin !== null) { const c = dist.cdf(Number(pdf.trmin), args); if (c > pmin) pmin = c; }
    if (pdf.trmax !== undefined && pdf.trmax !== null) { const c = dist.cdf(Number(pdf.trmax), args); if (c < pmax) pmax = c; }
    if (!(pmin < pmax)) return null;
    const shift = pdf.shift ?? 0;
    const out = new Float64Array(n);
    for (let i = 0; i < n; i++) out[i] = dist.inv(pmin + (pmax - pmin) * u[i], args) + shift;
    return out;
  }

  /**
   * A pdf attribute (JSON text) as an object, with the integers of a random
   * state (128-bit) kept as text: JSON.parse would round them to Numbers.
   */
  function parsePdf(text) {
    if (typeof text !== 'string') return text;
    return JSON.parse(text.replace(/("(?:state|inc|uinteger)"\s*:\s*)(\d{16,})(?=\s*[,}])/g, '$1"$2"'));
  }

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
  // erfcinv(2p) rather than erfinv(2p - 1): 2p - 1 rounds away a small p's digits
  function invNorm(p, mean, std) { return mean - std * Math.SQRT2 * erfcinv(2 * p); }
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
        // erfc rather than 1 + erf, which cancels in the lower tail
        const { mean, std } = args;
        return 0.5 * erfc(-(x - mean) / (std * Math.SQRT2));
      }
      case 'exponential': case 'exp': {
        const { mean } = args; return x <= 0 ? 0 : 1 - Math.exp(-x / mean);
      }
      case 'loguniform': case 'logu': case 'logunif': {
        const { a, b } = args; return x <= a ? 0 : x >= b ? 1 : (Math.log(x) - Math.log(a)) / (Math.log(b) - Math.log(a));
      }
      case 'lognormal': case 'logn': case 'lognorm': {
        const { gm, gsd } = args; return 0.5 * erfc(-(Math.log(x) - Math.log(gm)) / (Math.log(gsd) * Math.SQRT2));
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
  // A distribution with a saved random state gives the samples of the Python
  // code (samplesFromState, Latin hypercube sampling unless opts.lhs is
  // false); one without gives random samples of it.
  function generatePdfSamples(pdf, n = 1000, opts = {}) {
    if (!pdf || !pdf.type) return null;
    const typeKey = pdf.type.toLowerCase();
    if (typeKey === 'raw') return null;
    if (isExact(pdf)) {
      const exact = samplesFromState(pdf, n, opts.lhs ?? sampleOptions.lhs);
      if (exact) return exact;
    }
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
      if (!Number.isSafeInteger(n)) kvotWarn('BigInt -> Number conversion (precision loss possible):', v);
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
    // the samples of the Python code, from a distribution's saved random state
    samplesFromState,
    uniformsFromState,
    isExact,
    parsePdf,
    /** Draw as the Python code with Latin hypercube sampling (true, its default) or simple random sampling. */
    setLhs(on) { sampleOptions.lhs = !!on; },
    getLhs() { return sampleOptions.lhs; },
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
