/* ==========================================================================
   FARF31.HTML: FILES

   Readers and writers for FARF31's standalone files and for the page's own:

     in.dat           keyword lines (PRINT, CASENAME, DIFFUSIVITY) and one line
                      per nuclide: NAME THALF(a) IDAUGH ISOURC
     in.par           KEYWORD value, any order: TW PECLET ASPEC EPS DE PENDEP,
                      KDR_XX and (element-specific diffusivity) DE_XX, XX the
                      first two characters of the nuclide name; F (the
                      F-factor) in place of TW or ASPEC; and the page's own
                      KA_XX, the fracture's surface sorption coefficient,
                      written only when one is not zero (it goes beyond
                      FARF31's format)
     in.ts            for each source nuclide, in in.dat's order, its name on a
                      line and then "time rate" lines (a, mol/a)
     casename31.prm   numerical settings: a line naming the inversion
                      routine and KEYWORD value lines (see readPrm)
     out.ts           the output release, per nuclide: time mol/a Bq/a
     out.response     the unit responses (FARF31 writes them under PRINT DEBUG)

   plus the page's case file (JSON) and CSV. '#' starts a comment everywhere.
   No DOM: runs in the page and under Node for the tests.

   ONE GLOBAL: Farf31IO.
   ========================================================================== */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.Farf31IO = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  class Farf31FileError extends Error {
    constructor(file, line, message) {
      super(line ? `${file}, line ${line}: ${message}` : `${file}: ${message}`);
      this.name = 'Farf31FileError';
      this.file = file; this.line = line;
    }
  }

  /** Lines without comments, with their 1-based numbers; blank lines dropped. */
  function lines(text) {
    const out = [];
    String(text).replace(/^﻿/, '').split(/\r\n|\r|\n/).forEach((raw, k) => {
      const hash = raw.indexOf('#');
      const s = (hash >= 0 ? raw.slice(0, hash) : raw).trim();
      if (s) out.push({ n: k + 1, s, w: s.split(/[\s,;]+/).filter(Boolean) });
    });
    return out;
  }

  /** A Fortran-style number: 1.0E-6, 50., 1.0D-6, 3E4. INF/INFINITY allowed
      where `inf` is true. NaN when it is not a number. */
  function fnum(tok, inf) {
    if (tok == null) return NaN;
    const t = String(tok).trim();
    if (inf && /^\+?inf(inity)?$/i.test(t)) return Infinity;
    if (!/^[-+]?(\d+\.?\d*|\.\d+)([eEdD][-+]?\d+)?$/.test(t)) return NaN;
    return Number(t.replace(/[dD]/, 'e'));
  }

  /** FARF31's element key: the first two characters of the name, upper case
      (for a one-letter element the first digit is part of it: U238 -> U2). */
  function elementKey(name) { return String(name).slice(0, 2).toUpperCase(); }

  /* ======================================================================
     in.dat
     ====================================================================== */

  function readDat(text, file = 'in.dat') {
    const out = { print: 'OFF', casename: 'farf', diffusivity: 'SINGLE', nuclides: [], warnings: [] };
    for (const L of lines(text)) {
      const key = L.w[0].toUpperCase();
      if (key === 'PRINT') {
        const v = (L.w[1] || '').toUpperCase();
        if (!['ON', 'OFF', 'DEBUG'].includes(v)) throw new Farf31FileError(file, L.n, 'PRINT takes ON, OFF or DEBUG.');
        out.print = v;
      } else if (key === 'CASENAME') {
        if (!L.w[1]) throw new Farf31FileError(file, L.n, 'CASENAME needs a name.');
        out.casename = L.w[1];
      } else if (key === 'DIFFUSIVITY') {
        const v = (L.w[1] || '').toUpperCase();
        if (!['SINGLE', 'ELEMENT_SPECIFIC'].includes(v)) throw new Farf31FileError(file, L.n, 'DIFFUSIVITY takes SINGLE or ELEMENT_SPECIFIC.');
        out.diffusivity = v;
      } else {
        if (L.w.length < 4) throw new Farf31FileError(file, L.n, `a nuclide line is NAME THALF IDAUGH ISOURC, but this has ${L.w.length} item${L.w.length === 1 ? '' : 's'}.`);
        const [name, th, id, is] = L.w;
        if (/^[-+.\d]/.test(name)) throw new Farf31FileError(file, L.n, `"${name}" is not a nuclide name.`);
        const thalf = fnum(th, true);
        if (!(thalf > 0)) throw new Farf31FileError(file, L.n, `the half-life of ${name} must be a positive number, not "${th}".`);
        const idaugh = fnum(id), isourc = fnum(is);
        if (idaugh !== 0 && idaugh !== 1) throw new Farf31FileError(file, L.n, `IDAUGH of ${name} must be 0 or 1.`);
        if (isourc !== 0 && isourc !== 1) throw new Farf31FileError(file, L.n, `ISOURC of ${name} must be 0 or 1.`);
        if (out.nuclides.some((n) => n.name.toUpperCase() === name.toUpperCase())) throw new Farf31FileError(file, L.n, `${name} appears twice.`);
        out.nuclides.push({ name, thalf, daughter: idaugh === 1, source: isourc === 1 });
      }
    }
    if (!out.nuclides.length) throw new Farf31FileError(file, 0, 'there are no nuclide lines.');
    const last = out.nuclides[out.nuclides.length - 1];
    if (last.daughter) { last.daughter = false; out.warnings.push(`${file}: ${last.name} has IDAUGH = 1 but no line follows it; read as 0.`); }
    return out;
  }

  /** A number for in.par: plain decimals with a point in [1e-3, 1e7), else
      Fortran exponent form (1.0E-06); up to 12 significant digits. */
  function fmtNum(x) {
    if (x === Infinity) return '1.0E+20';
    if (!isFinite(x)) return String(x);
    if (x === 0) return '0.0';
    const a = Math.abs(x);
    if (a >= 1e-3 && a < 1e7) { const s = String(Number(x.toPrecision(12))); return /[.eE]/.test(s) ? s : s + '.'; }
    let [mant, ex] = Number(x.toPrecision(12)).toExponential().split('e');
    if (!mant.includes('.')) mant += '.0';
    const e = Number(ex);
    return `${mant}E${e < 0 ? '-' : '+'}${String(Math.abs(e)).padStart(2, '0')}`;
  }

  /** Scientific notation the Fortran way: 1.57E+07. */
  function fsci(x, digits = 6) {
    if (x === Infinity) return '1.0E+20';
    const s = Number(x).toExponential(digits).toUpperCase();
    return s.replace(/E([-+])(\d)$/, 'E$10$2');
  }

  function writeDat(c) {
    const L = ['# FARF31 nuclides, written by kvotab.se/FARF31.html', `PRINT ${c.print || 'DEBUG'}`,
      `DIFFUSIVITY ${c.diffusivity || 'SINGLE'}`, `CASENAME ${c.casename || 'farf'}`,
      '# NAME   THALF(a)   IDAUGH ISOURC'];
    for (const n of c.nuclides) {
      L.push(`${n.name.padEnd(7)} ${fsci(n.thalf, 4).padEnd(11)}  ${n.daughter ? 1 : 0}  ${n.source ? 1 : 0}`);
    }
    return L.join('\n') + '\n';
  }

  /* ======================================================================
     in.par
     ====================================================================== */

  const PAR_KEYS = ['TW', 'PECLET', 'ASPEC', 'EPS', 'DE', 'PENDEP'];

  /** { TW, PECLET, ASPEC, EPS, DE, PENDEP, kd: {XX: v}, de: {XX: v}, ka: {XX: v},
      extra: {} }; TW or ASPEC worked out from F when that is given in its place. */
  function readPar(text, file = 'in.par') {
    const out = { kd: {}, de: {}, ka: {}, extra: {}, warnings: [] };
    for (const L of lines(text)) {
      if (L.w.length < 2) throw new Farf31FileError(file, L.n, `"${L.s}" is not KEYWORD value.`);
      const key = L.w[0].toUpperCase();
      const v = fnum(L.w[1], key === 'PENDEP' || key === 'PECLET');
      if (!isFinite(v) && !(v === Infinity)) throw new Farf31FileError(file, L.n, `the value of ${key} must be a number, not "${L.w[1]}".`);
      let m;
      if (PAR_KEYS.includes(key)) out[key] = v;
      else if ((m = key.match(/^KDR_(.{1,2})$/))) out.kd[m[1].toUpperCase()] = v;
      else if ((m = key.match(/^DE_(.{1,2})$/))) out.de[m[1].toUpperCase()] = v;
      else if ((m = key.match(/^KA_(.{1,2})$/))) {
        if (!(v >= 0)) throw new Farf31FileError(file, L.n, `${key} must be zero or positive.`);
        out.ka[m[1].toUpperCase()] = v;
      }
      else if (['DENSITY', 'RHO', 'FFACTOR', 'F'].includes(key)) out.extra[key] = v;
      else out.warnings.push(`${file}, line ${L.n}: ${key} is not a FARF31 keyword; ignored.`);
    }
    // FARF31 takes any two of TW, ASPEC and F (the F-factor TW·ASPEC) and works out the third
    const F = out.extra.F != null ? out.extra.F : out.extra.FFACTOR;
    if (F != null) {
      if (out.TW != null && out.ASPEC != null) throw new Farf31FileError(file, 0, 'only two of TW, ASPEC and F can be given.');
      if (out.TW != null) { if (!(out.TW > 0)) throw new Farf31FileError(file, 0, 'F needs a positive TW.'); out.ASPEC = F / out.TW; }
      else if (out.ASPEC != null) { if (!(out.ASPEC > 0)) throw new Farf31FileError(file, 0, 'F needs a positive ASPEC.'); out.TW = F / out.ASPEC; }
    }
    return out;
  }

  function writePar(c) {
    const p = c.params;
    const L = ['# FARF31 parameters, written by kvotab.se/FARF31.html',
      `TW ${fmtNum(p.tw)}`, `PECLET ${p.Pe === Infinity ? '1.0E+20' : fmtNum(p.Pe)}`,
      `ASPEC ${fmtNum(p.aw)}`, `EPS ${fmtNum(p.eps)}`];
    if (c.diffusivity !== 'ELEMENT_SPECIFIC') L.push(`DE ${fmtNum(p.de)}`);
    L.push(`PENDEP ${fmtNum(p.x0)}${p.x0 === Infinity ? '   # an infinite matrix' : ''}`);
    // KA_ lines only when some Ka is not zero: they go beyond FARF31's format
    const withKa = c.nuclides.some((n) => n.ka > 0);
    const done = new Set();
    for (const n of c.nuclides) {
      const k = elementKey(n.name);
      if (done.has(k)) continue;
      done.add(k);
      L.push(`KDR_${k} ${fmtNum(n.kd)}`);
      if (c.diffusivity === 'ELEMENT_SPECIFIC') L.push(`DE_${k} ${fmtNum(n.de)}`);
      if (withKa) L.push(`KA_${k} ${fmtNum(n.ka || 0)}`);
    }
    return L.join('\n') + '\n';
  }

  /* ======================================================================
     in.ts and generic release tables
     ====================================================================== */

  /** { <name>: [[t, rate], ...] } in the order read. */
  function readTs(text, file = 'in.ts') {
    const out = {}, order = [];
    let cur = null;
    for (const L of lines(text)) {
      const a = fnum(L.w[0]);
      if (isNaN(a)) {
        if (L.w.length !== 1) throw new Farf31FileError(file, L.n, `expected a nuclide name alone on the line, found "${L.s}".`);
        cur = L.w[0];
        if (out[cur]) throw new Farf31FileError(file, L.n, `${cur} has two series.`);
        out[cur] = []; order.push(cur);
        continue;
      }
      if (!cur) throw new Farf31FileError(file, L.n, 'numbers before the first nuclide name.');
      const b = fnum(L.w[1]);
      if (L.w.length < 2 || isNaN(b)) throw new Farf31FileError(file, L.n, 'a series line is "time rate".');
      const s = out[cur];
      if (s.length && a < s[s.length - 1][0]) throw new Farf31FileError(file, L.n, `the times of ${cur} decrease (${a} after ${s[s.length - 1][0]}).`);
      s.push([a, b]);
    }
    for (const k of order) if (out[k].length < 2) throw new Farf31FileError(file, 0, `${k} has fewer than two points.`);
    return { series: out, order };
  }

  function writeTs(c) {
    const L = ['# FARF31 release series (time a, rate mol/a), written by kvotab.se/FARF31.html'];
    for (const n of c.nuclides) {
      if (!n.source) continue;
      const s = c.series[n.name] || [];
      L.push(n.name);
      for (const [t, v] of s) L.push(`${fsci(t, 6).padStart(14)}  ${fsci(v, 6).padStart(14)}`);
    }
    return L.join('\n') + '\n';
  }

  /** A release table in CSV/TSV/whitespace form: a header with "time" and
      nuclide names, or two bare numeric columns (for `fallbackName`). */
  function readTable(text, file, fallbackName) {
    const raw = String(text).replace(/^﻿/, '').split(/\r\n|\r|\n/).map((s) => s.replace(/#.*$/, '').trim()).filter(Boolean);
    if (!raw.length) throw new Farf31FileError(file, 0, 'the file is empty.');
    const split = (s) => s.split(/\s*[,;\t]\s*|\s+/).filter((x) => x !== '');
    let head = split(raw[0]);
    let start = 1, names;
    if (head.every((h) => !isNaN(fnum(h)))) {
      if (head.length !== 2) throw new Farf31FileError(file, 1, 'without a header the table must have two columns: time and rate.');
      if (!fallbackName) throw new Farf31FileError(file, 1, 'a two-column table needs a nuclide selected to receive it.');
      names = [fallbackName]; start = 0;
    } else {
      names = head.slice(1);
      if (!names.length) throw new Farf31FileError(file, 1, 'the header needs a time column and at least one nuclide column.');
    }
    const series = {};
    names.forEach((n) => { series[n] = []; });
    for (let k = start; k < raw.length; k++) {
      const w = split(raw[k]).map((x) => fnum(x));
      if (w.length < names.length + 1 || w.some((x) => isNaN(x))) throw new Farf31FileError(file, k + 1, `expected ${names.length + 1} numbers.`);
      names.forEach((n, q) => series[n].push([w[0], w[q + 1]]));
    }
    return { series, order: names };
  }

  /* ======================================================================
     casename31.prm (numerical settings)

     FARF31's own file picks the inversion routine with a line holding only
     BROMEX, TALBOT or STEAMR, and sets the time series manager and the rock
     density with KEYWORD value lines. The page takes what has a meaning for
     it: the method (TALBOT; BROMEX, a Bromwich-line method, maps to de Hoog;
     the steamroller is not offered and maps to the default), NPMIN and NPMAX
     (output points), RELINT (the output grid's interpolation tolerance), BQMIN
     (Bq/a below which out.ts leaves a time out) and RHOP (the rock density),
     plus its own METHOD, TSTART and TEND. Anything else is reported as not
     used.
     ====================================================================== */

  const BROMEX_NOTE = 'BROMEX (Bromwich/Gustafson) is read as the Bromwich-line method of de Hoog, Knight and Stokes.';
  const STEAMR_NOTE = 'The steamroller algorithm is not offered; the saddle-point contour is used.';

  /** FARF31 picks its inversion routine from a line holding only BROMEX,
      TALBOT or STEAMR and skips lines it does not know; the page's own
      method, on a METHOD line, wins when both are there. */
  function readPrm(text, file = 'casename31.prm') {
    const out = { settings: {}, notes: [], unused: [] };
    let farf = null, own = null;
    for (const L of lines(text)) {
      const key = L.w[0].toUpperCase();
      const val = L.w[1];
      const v = fnum(val);
      const need = () => { if (!isFinite(v)) throw new Farf31FileError(file, L.n, `${key} needs a number.`); };
      if (['METHOD', 'INVERSION', 'LAPLACE', 'INVMETHOD'].includes(key)) {
        const m = String(val || '').toUpperCase();
        if (m === 'TALBOT') own = 'talbot';
        else if (m === 'BROMEX' || m === 'BROMWICH' || m === 'DEHOOG') { own = 'dehoog'; if (m !== 'DEHOOG') out.notes.push(BROMEX_NOTE); }
        else if (m === 'STEAMR' || m === 'STEAMROLLER') { own = 'parabola'; out.notes.push(STEAMR_NOTE); }
        else if (m === 'PARABOLA' || m === 'SADDLE') own = 'parabola';
        else throw new Farf31FileError(file, L.n, `unknown inversion method "${val}".`);
      } else if (['TALBOT', 'BROMEX', 'STEAMR', 'STEAMROLLER'].includes(key) && L.w.length === 1) {
        farf = key;
      } else if (key === 'NPMIN') { need(); out.settings.npMin = Math.round(v); }
      else if (key === 'NPMAX') { need(); out.settings.npMax = Math.round(v); }
      else if (key === 'RELINT') { need(); out.settings.relint = v; }
      else if (key === 'BQMIN') { need(); out.settings.bqMin = v; }
      else if (['RHOP', 'DENSITY', 'RHO', 'ROCKDENSITY', 'RHOROCK'].includes(key)) { need(); out.settings.rho = v; }
      else if (key === 'TSTART') { need(); out.settings.tStart = v; }
      else if (key === 'TEND') { need(); out.settings.tEnd = v; }
      else out.unused.push(`${key}${val != null ? ' ' + val : ''}`);
    }
    if (own) out.settings.method = own;
    else if (farf) {
      out.settings.method = farf === 'TALBOT' ? 'talbot' : farf === 'BROMEX' ? 'dehoog' : 'parabola';
      if (farf === 'BROMEX') out.notes.push(BROMEX_NOTE);
      else if (farf !== 'TALBOT') out.notes.push(STEAMR_NOTE);
    }
    return out;
  }

  /* FARF31 takes at most 128 output points (NPMAX); larger values, and an
     NPMIN beyond them, are left out of the file. */
  const FARF_NPMAX = 128;

  function writePrm(c) {
    const s = c.settings || {};
    const m = { parabola: 'PARABOLA', talbot: 'TALBOT', dehoog: 'DEHOOG' }[s.method || 'parabola'];
    const L = ['# Numerical settings, written by kvotab.se/FARF31.html. FARF31 reads the lines',
      '# it knows and skips the others. The next line picks its inversion routine',
      '# (BROMEX, its default); METHOD, TSTART and TEND are for the page alone.',
      'BROMEX', `METHOD ${m}`];
    const npMax = s.npMax && s.npMax <= FARF_NPMAX ? s.npMax : null;
    if (s.npMin && s.npMin <= (npMax || FARF_NPMAX)) L.push(`NPMIN ${s.npMin}`);
    if (npMax) L.push(`NPMAX ${npMax}`);
    if (s.relint) L.push(`RELINT ${fsci(s.relint, 1)}`);
    if (s.bqMin != null) L.push(`BQMIN ${fsci(s.bqMin, 1)}`);
    L.push(`RHOP ${fmtNum(c.params.rho == null ? 2700 : c.params.rho)}`);
    if (s.tStart > 0) L.push(`TSTART ${fsci(s.tStart, 4)}`);
    if (s.tEnd > 0) L.push(`TEND ${fsci(s.tEnd, 4)}`);
    return L.join('\n') + '\n';
  }

  /* ======================================================================
     Combining the three input files into a case
     ====================================================================== */

  /** Nuclides of in.dat with Kd, Ka and De from in.par (Ka 0 when absent). */
  function applyPar(dat, par) {
    const warnings = [];
    for (const n of dat.nuclides) {
      const k = elementKey(n.name);
      if (par.kd[k] != null) n.kd = par.kd[k];
      else { n.kd = 0; warnings.push(`in.par has no KDR_${k} for ${n.name}; Kd = 0.`); }
      n.ka = par.ka && par.ka[k] != null ? par.ka[k] : 0;
      if (dat.diffusivity === 'ELEMENT_SPECIFIC') {
        if (par.de[k] != null) n.de = par.de[k];
        else if (par.DE != null) { n.de = par.DE; warnings.push(`in.par has no DE_${k} for ${n.name}; DE used.`); }
        else throw new Farf31FileError('in.par', 0, `DE_${k} is missing (DIFFUSIVITY ELEMENT_SPECIFIC).`);
      } else {
        if (par.DE == null) throw new Farf31FileError('in.par', 0, 'DE is missing (DIFFUSIVITY SINGLE).');
        n.de = par.DE;
      }
    }
    for (const key of PAR_KEYS) {
      if (key === 'DE') continue;
      if (par[key] == null) throw new Farf31FileError('in.par', 0, `${key} is missing.`);
    }
    return warnings;
  }

  /* ======================================================================
     out.ts and out.response
     ====================================================================== */

  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function runStamp(date) {
    const d = date || new Date();
    const p2 = (x) => String(x).padStart(2, '0');
    return ` Run made on  ${MONTHS[d.getMonth()]}. ${String(d.getDate()).padStart(2)},   ${p2(d.getFullYear() % 100)}  (${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())})`;
  }

  /** out.ts in FARF31's layout. Each nuclide keeps the times where its rate
      reaches bqMin Bq/a (all times when bqMin is not set or 0). */
  function writeOutTs(result, opt = {}) {
    const bqMin = opt.bqMin || 0;
    const L = [runStamp(opt.date), '  ', '  Output migration rate from stream tube:', '  ',
      '      Time (a)                  Rate', '                       (mol/a)         (Bq/a)', '  Nuclide'];
    const t = result.times;
    result.names.forEach((name, i) => {
      if (i > 0) L.push('  ');
      L.push(`  ${name.toUpperCase().padEnd(6)}`);
      const o = result.out[i], b = result.bq[i];
      let first = -1, last = -1;
      for (let k = 0; k < t.length; k++) if (b[k] >= bqMin && o[k] > 0) { if (first < 0) first = k; last = k; }
      if (first < 0) {
        if (t.length) L.push(`   ${fsci(t[0])}    ${fsci(0)}    ${fsci(0)}`);
        return;
      }
      for (let k = first; k <= last; k++) L.push(`   ${fsci(t[k])}    ${fsci(o[k])}    ${fsci(b[k])}`);
    });
    L.push('  ');
    return L.join('\n') + '\n';
  }

  /** Fortran E20.4: 0.dddd mantissa. */
  function fe(x, w = 20, d = 4) {
    if (x === 0 || !isFinite(x)) return (x === 0 ? `0.${'0'.repeat(d)}E+00` : String(x)).padStart(w);
    const neg = x < 0; let a = Math.abs(x);
    let e = Math.floor(Math.log10(a)) + 1;
    let m = Math.round(a / Math.pow(10, e) * Math.pow(10, d));
    if (m >= Math.pow(10, d)) { m /= 10; e += 1; }
    const es = (e < 0 ? '-' : '+') + String(Math.abs(e)).padStart(2, '0');
    return `${neg ? '-' : ''}0.${String(Math.round(m)).padStart(d, '0')}E${es}`.padStart(w);
  }

  /** out.response: every response block as FARF31 writes it under PRINT DEBUG,
      own response first, then those from the parents, nearest first. */
  function writeOutResponse(result) {
    const L = [];
    const byPair = new Map(result.responses.map((r) => [`${r.i},${r.j}`, r]));
    const N = result.names.length;
    for (let i = 0; i < N; i++) {
      for (let j = i; j >= 0; j--) {
        const r = byPair.get(`${i},${j}`);
        if (!r) continue;
        const n = r.t.length;
        const i12 = (x) => String(x).padStart(12);
        if (n < 2) {
          L.push(` NPRESP(MPRES=${i12(i + 1)} ,MSUB=${i12(j + 1)} )=${i12(2)}`);
          L.push(fe(1) + fe(0), fe(2) + fe(0));
        } else {
          L.push(` NPRESP(MPRES=${i12(i + 1)} ,MSUB=${i12(j + 1)} )=${i12(n)}`);
          for (let k = 0; k < n; k++) L.push(fe(r.t[k]) + fe(Math.max(0, r.h[k])));
        }
        L.push(`Integrated curve for ${result.names[i].toUpperCase().padEnd(6)}${fe(n < 2 ? 0 : r.integral)}`);
        L.push('  ');
      }
    }
    return L.join('\n') + '\n';
  }

  /** out.ts read back: { <NAME>: [[t, mol/a, Bq/a], ...] } (for overlays). */
  function readOutTs(text, file = 'out.ts') {
    const out = {}; let cur = null;
    for (const raw of String(text).split(/\r\n|\r|\n/)) {
      const w = raw.trim().split(/\s+/).filter(Boolean);
      if (w.length === 1 && /^[A-Za-z][A-Za-z]?\d+[A-Za-z]*$/.test(w[0])) { cur = w[0].toUpperCase(); out[cur] = []; continue; }
      if (cur && w.length === 3 && w.every((x) => !isNaN(fnum(x)))) out[cur].push(w.map((x) => fnum(x)));
    }
    if (!Object.keys(out).length) throw new Farf31FileError(file, 0, 'no nuclide blocks found.');
    return out;
  }

  function readOutResponse(text) {
    const out = []; let cur = null;
    for (const raw of String(text).split(/\r\n|\r|\n/)) {
      const m = raw.match(/MPRES=\s*(\d+)\s*,MSUB=\s*(\d+)\s*\)=\s*(\d+)/);
      if (m) { cur = { i: +m[1] - 1, j: +m[2] - 1, pts: [] }; out.push(cur); continue; }
      const g = raw.match(/Integrated curve for\s+(\S+)\s+(\S+)/);
      if (g && cur) { cur.name = g[1]; cur.integral = fnum(g[2]); continue; }
      const w = raw.trim().split(/\s+/);
      if (cur && w.length === 2 && w.every((x) => !isNaN(fnum(x)))) cur.pts.push(w.map((x) => fnum(x)));
    }
    return out;
  }

  /* ======================================================================
     CSV of results
     ====================================================================== */

  function csvCell(x) {
    if (typeof x === 'number') return Number.isFinite(x) ? String(x) : '';
    const s = String(x);
    if (typeof kvotCsvCell === 'function') return kvotCsvCell(s);   // the site's formula-safe quoting
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }

  /** The case a result was run with, as comment rows (for the CSV). */
  function caseRows(input, casename) {
    if (!input || !input.params) return [];
    const p = input.params;
    const rows = [];
    if (casename) rows.push(['# case', casename]);
    rows.push(['# tw (a)', p.tw], ['# Pe', p.Pe === Infinity ? 'inf' : p.Pe], ['# aw (1/m)', p.aw], ['# eps', p.eps],
      ['# x0 (m)', p.x0 === Infinity ? 'inf' : p.x0], ['# rho (kg/m3)', p.rho == null ? 2700 : p.rho]);
    rows.push(['# nuclide', 'T1/2 (a)', 'Kd (m3/kg)', 'Ka (m)', 'De (m2/a)', 'R', 'Rf', 'daughter next', 'source']);
    for (const n of input.nuclides || []) {
      const R = p.eps + n.kd * (p.rho == null ? 2700 : p.rho), Rf = 1 + (n.ka || 0) * p.aw;
      rows.push([`# ${n.name}`, n.thalf === Infinity ? 'inf' : n.thalf, n.kd, n.ka || 0, n.de, R, Rf, n.daughter ? 1 : 0, n.source ? 1 : 0]);
    }
    return rows;
  }

  function resultsCsv(result, build, casename) {
    const head = ['time (a)'];
    result.names.forEach((n) => head.push(`${n} (mol/a)`, `${n} (Bq/a)`));
    const rows = [[`# FARF31 model, kvotab.se/FARF31.html${build ? `, build ${build}` : ''}`], ...caseRows(result.input, casename), head];
    for (let k = 0; k < result.times.length; k++) {
      const r = [result.times[k]];
      result.names.forEach((n, i) => r.push(result.out[i][k], result.bq[i][k]));
      rows.push(r);
    }
    return rows.map((r) => r.map(csvCell).join(',')).join('\n') + '\n';
  }

  function responsesCsv(result, build, casename) {
    const rows = [[`# FARF31 unit responses (1/a), kvotab.se/FARF31.html${build ? `, build ${build}` : ''}`], ...caseRows(result.input, casename), ['response', 'from', 'time (a)', 'h (1/a)']];
    for (const r of result.responses) {
      for (let k = 0; k < r.t.length; k++) rows.push([r.nameI, r.nameJ, r.t[k], r.h[k]]);
    }
    return rows.map((r) => r.map(csvCell).join(',')).join('\n') + '\n';
  }

  return {
    Farf31FileError, lines, fnum, elementKey, fsci, fmtNum,
    readDat, writeDat, readPar, writePar, readTs, writeTs, readTable, readPrm, writePrm, applyPar,
    writeOutTs, writeOutResponse, readOutTs, readOutResponse, runStamp, fe, resultsCsv, responsesCsv,
  };
}));
