/* ==========================================================================
   ENSDF.HTML: WHAT THE PAGE KNOWS ABOUT A NUCLIDE

   Everything the chart, the decay-chain drawing and the panel share, with no
   DOM in it, so the browser test and Node can both call it:

     index()        the summary as lookups by Z and A
     names          60Co, 99mTc, 178m2Hf; "cobalt-60"
     formatting     half-lives, uncertainties in the NDS way, decay modes,
                    percentages
     colours        the half-life ramp, the decay-mode set and the continuous
                    scales, per theme
     buildChain()   the decay chain below a state

   One global: KVOT_ENSDF_CORE (module.exports under Node). Reads the element
   list from KVOT_ENSDF (ensdf-parse.js), which must load first.
   ========================================================================== */
(function (root, factory) {
  const parse = (typeof module === 'object' && module.exports) ? require('./ensdf-parse.js') : root.KVOT_ENSDF;
  const api = factory(parse);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.KVOT_ENSDF_CORE = api;
})(typeof self !== 'undefined' ? self : this, function (P) {
  'use strict';

  const ELEMENTS = P.ELEMENTS;
  const YEAR_S = P.YEAR_S;
  const SYMBOL_Z = Object.create(null);
  ELEMENTS.forEach(([sym, name], z) => { SYMBOL_Z[sym.toLowerCase()] = z; SYMBOL_Z[name.toLowerCase()] = z; });
  SYMBOL_Z.aluminum = 13; SYMBOL_Z.cesium = 55; SYMBOL_Z.sulphur = 16;

  /* ---------------------------------------------------------------------
     The summary as lookups
     --------------------------------------------------------------------- */
  function index(summary) {
    const byId = new Map();
    let maxN = 0, maxZ = 0;
    for (const n of summary.nuclides) {
      n.n = n.a - n.z;
      /* Searched for and not seen: in the file, but not a known nuclide. */
      n.hidden = /OBSERVED/.test(n.aq || '');
      byId.set(n.z * 1000 + n.a, n);
      if (n.hidden) continue;
      if (n.n > maxN) maxN = n.n;
      if (n.z > maxZ) maxZ = n.z;
    }
    const shown = summary.nuclides.filter((n) => !n.hidden);
    return { summary, list: summary.nuclides, shown, byId, maxN, maxZ, get: (z, a) => byId.get(z * 1000 + a) || null };
  }

  /* ---------------------------------------------------------------------
     Names
     --------------------------------------------------------------------- */
  const SUPERSCRIPT = { 0: '⁰', 1: '¹', 2: '²', 3: '³', 4: '⁴', 5: '⁵', 6: '⁶', 7: '⁷', 8: '⁸', 9: '⁹', '+': '⁺', '-': '⁻', m: 'ᵐ', '−': '⁻' };
  const sup = (s) => String(s).split('').map((c) => SUPERSCRIPT[c] || c).join('');

  /**
   * The isomer label of state k: the evaluator's metastable flag when there
   * is one (M, M1, M2 -> m, m1, m2), otherwise 'm' for a nuclide with one
   * isomer and 'm' + its place among the states for one with several.
   */
  function isomerLabel(nuc, k) {
    if (!k || !nuc || !nuc.s || !nuc.s[k]) return '';
    const st = nuc.s[k];
    if (nuc.s.length === 2) return 'm';
    const flag = /^M(\d?)$/i.exec(st.ms || '');
    if (flag) return 'm' + flag[1];
    const label = 'm' + k;
    const clash = nuc.s.some((x, i) => i !== k && i > 0 && /^M(\d)$/i.test(x.ms || '') && 'm' + x.ms.slice(1) === label);
    return clash ? `(${st.e})` : label;
  }

  /**
   * @returns {{mass: string, sym: string, text: string, long: string, key: string}}
   *   mass '99m', sym 'Tc', text '99mTc', long 'technetium-99m', key '99mTc'
   */
  function name(z, a, k, nuc) {
    const el = ELEMENTS[z] ? ELEMENTS[z][0] : `Z${z}`;
    const elName = ELEMENTS[z] ? ELEMENTS[z][1] : `element ${z}`;
    const iso = k > 0 ? isomerLabel(nuc, k) : '';
    const energy = iso.startsWith('(');
    const mass = energy ? String(a) : `${a}${iso}`;
    const text = energy ? `${a}${el} ${iso}` : `${mass}${el}`;
    if (z === 0 && a === 1) return { mass: '', sym: 'n', text: 'n', long: 'neutron', key: '1n' };
    return { mass, sym: el, text, long: `${elName}-${a}${energy ? ' ' + iso : iso}`, key: `${a}${energy ? '' : iso}${el}` };
  }

  /*
    Unicode superscripts are how this module hands out 99m, x10^-5 and beta-minus,
    but they must not be drawn as they are: Verdana has glyphs for ¹ ² ³ only
    (they are Latin-1), so in "²³⁸U" two digits come from Verdana and the third
    from a fallback font of another size. Every place that draws text splits it
    into runs first and sets the superscript runs itself -- <sup> in markup,
    raised tspans in SVG, a smaller raised font on the canvas.
  */
  const SUP_PLAIN = { '⁰': '0', '¹': '1', '²': '2', '³': '3', '⁴': '4', '⁵': '5', '⁶': '6', '⁷': '7', '⁸': '8', '⁹': '9', '⁺': '+', '⁻': '−', 'ᵐ': 'm' };

  /** "²³⁸U 4.5×10⁹ y" -> [{t: '238', sup: true}, {t: 'U 4.5×10', sup: false}, {t: '9', sup: true}, {t: ' y', sup: false}] */
  function supRuns(text) {
    const out = [];
    let cur = null;
    for (const ch of String(text ?? '')) {
      const plain = SUP_PLAIN[ch];
      const sup = plain !== undefined;
      if (!cur || cur.sup !== sup) { cur = { t: '', sup }; out.push(cur); }
      cur.t += sup ? plain : ch;
    }
    return out;
  }

  /** The same text with no superscripts at all, for a <select> or a file: "238U 4.5E9 y". */
  function asciiText(text) {
    return String(text ?? '')
      .replace(/×10([⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+)/g, (_, e) => 'E' + e.split('').map((c) => (SUP_PLAIN[c] === '−' ? '-' : SUP_PLAIN[c])).join(''))
      .replace(/[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ᵐ]/g, (c) => (SUP_PLAIN[c] === '−' ? '-' : SUP_PLAIN[c]));
  }

  /** Superscripted, for text that cannot carry markup: ⁹⁹ᵐTc. */
  const plainName = (z, a, k, nuc) => {
    const n = name(z, a, k, nuc);
    return n.mass ? sup(n.mass) + n.sym : n.sym;
  };

  /**
   * What a reader types for a nuclide: 60Co, Co60, Co-60, co 60, cobalt-60,
   * 99mTc, Tc-99m, 178m2Hf, U238, n, 1n. Returns {z, a, iso} with iso the
   * isomer label ('', 'm', 'm2'), or an element {z} alone, or null.
   */
  function parseQuery(q) {
    const t = String(q || '').trim().toLowerCase().replace(/[‐-―]/g, '-');
    if (!t) return null;
    if (t === 'n' || t === '1n' || t === 'neutron') return { z: 0, a: 1, iso: '' };
    /* '99mo' is molybdenum-99, not an isomer of oxygen: the reading without
       an isomer is tried first. */
    let m = /^(\d{1,3})\s*-?\s*([a-z]+)$/.exec(t);
    if (m && SYMBOL_Z[m[2]] !== undefined) return { z: SYMBOL_Z[m[2]], a: +m[1], iso: '' };
    m = /^(\d{1,3})\s*(m\d?)\s*-?\s*([a-z]+)$/.exec(t);
    if (m && SYMBOL_Z[m[3]] !== undefined) return { z: SYMBOL_Z[m[3]], a: +m[1], iso: m[2] };
    m = /^([a-z]+)\s*-?\s*(\d{1,3})\s*(m\d?)?$/.exec(t);
    if (m && SYMBOL_Z[m[1]] !== undefined) return { z: SYMBOL_Z[m[1]], a: +m[2], iso: m[3] || '' };
    m = /^z\s*=?\s*(\d{1,3})$/.exec(t);
    if (m) return { z: +m[1] };
    if (SYMBOL_Z[t] !== undefined) return { z: SYMBOL_Z[t] };
    return null;
  }

  /**
   * The state index an isomer label points at, or -1. A bare 'm' on a nuclide
   * with several isomers means the longest-lived one: "177mLu" is the 160-day
   * isomer (flagged M4), not the 133 ns one below it, and "178mHf" the 31-year
   * one.
   */
  function stateForLabel(nuc, iso) {
    if (!iso) return 0;
    for (let k = 1; k < nuc.s.length; k++) if (isomerLabel(nuc, k) === iso) return k;
    if (iso === 'm' && nuc.s.length > 1) {
      let best = 1;
      for (let k = 2; k < nuc.s.length; k++) if ((nuc.s[k].ts || 0) > (nuc.s[best].ts || 0)) best = k;
      return best;
    }
    const d = /^m(\d)$/.exec(iso);
    if (d && nuc.s[+d[1]]) return +d[1];
    return -1;
  }

  /* ---------------------------------------------------------------------
     Numbers as NDS prints them
     --------------------------------------------------------------------- */
  const UNIT_TEXT = { Y: 'y', D: 'd', H: 'h', M: 'min', MIN: 'min', S: 's', MS: 'ms', US: 'µs', NS: 'ns', PS: 'ps', FS: 'fs', AS: 'as', EV: 'eV', KEV: 'keV', MEV: 'MeV' };
  const QUALIFIER = { LT: '<', GT: '>', LE: '≤', GE: '≥', AP: '≈', CA: '', SY: '' };
  const QUALIFIER_NOTE = { CA: 'calculated', SY: 'from systematics' };

  /** 1.0E-5 -> 1.0×10⁻⁵, as the Nuclear Data Sheets would set it. */
  function expText(s) {
    return String(s).replace(/(\d)E([+-]?)(\d+)/gi, (_, d, sign, e) => `${d}×10${sup((sign === '-' ? '-' : '') + String(+e))}`);
  }

  /**
   * A value with its uncertainty, split for display: 2822.81 and "21", or
   * 0.28 with +21 −14, or 35 with the qualifier "<".
   *
   * @returns {{value: string, unc: string, plus: string, minus: string, q: string, note: string}}
   */
  function valueParts(value, unc) {
    const v = String(value || '').trim();
    const u = String(unc || '').trim().toUpperCase();
    const out = { value: expText(v), unc: '', plus: '', minus: '', q: '', note: '' };
    if (!u) return out;
    if (/^\d+$/.test(u)) out.unc = u;
    else if (/^\+\d+-\d+$/.test(u)) { const m = /^\+(\d+)-(\d+)$/.exec(u); out.plus = m[1]; out.minus = m[2]; }
    else if (/^-\d+\+\d+$/.test(u)) { const m = /^-(\d+)\+(\d+)$/.exec(u); out.plus = m[2]; out.minus = m[1]; }
    else if (QUALIFIER[u] !== undefined) { out.q = QUALIFIER[u]; out.note = QUALIFIER_NOTE[u] || ''; }
    return out;
  }

  /** The absolute uncertainty of a value, as a readable ± string, for a tooltip. */
  function uncertaintyText(value, unc) {
    const u = P.uncertainty(value, unc);
    if (!u) return '';
    const f = (x) => String(+x.toPrecision(3));
    if (u.abs !== undefined) return `± ${f(u.abs)}`;
    if (u.plus !== undefined) return `+${f(u.plus)} −${f(u.minus)}`;
    return QUALIFIER_NOTE[u.q] || '';
  }

  /** A half-life as the file gives it: '1925.28 d', with its uncertainty and qualifier. */
  function halfLifeParts(st) {
    if (!st) return { value: '', unit: '', unc: '', plus: '', minus: '', q: '', note: '', unknown: true };
    if (st.st) return { value: 'stable', unit: '', unc: '', plus: '', minus: '', q: '', note: '', stable: true };
    const t = String(st.t || '').trim();
    const m = /^([<>~]?)\s*([0-9.]+(?:[Ee][+-]?\d+)?)\s*([A-Za-z]+)\s*(\?)?/.exec(t);
    if (!m) return { value: t || '', unit: '', unc: '', plus: '', minus: '', q: '', note: '', unknown: true };
    const parts = valueParts(m[2], st.dt);
    const unit = UNIT_TEXT[m[3].toUpperCase()] || m[3].toLowerCase();
    if (m[1] === '>' || m[1] === '<') parts.q = m[1];
    if (m[1] === '~') parts.q = '≈';
    return Object.assign(parts, { unit, doubtful: !!m[4], width: !!st.w });
  }

  /** '1925.28 d' in plain text, uncertainty after it: for tooltips, cells and CSV. */
  function halfLifeText(st, withUnc) {
    const p = halfLifeParts(st);
    if (p.stable) return 'stable';
    if (p.unknown) return p.value ? p.value : 'unknown';
    let s = `${p.q ? p.q + ' ' : ''}${p.value} ${p.unit}${p.doubtful ? ' ?' : ''}`;
    if (withUnc) {
      if (p.unc) s += ` ${p.unc}`;
      else if (p.plus) s += ` +${p.plus}−${p.minus}`;
    }
    return s;
  }

  /** The half-life in a unit a reader can compare: 1925.28 d is also 5.271 y. */
  function halfLifeAlt(st) {
    if (!st || st.st || !(st.ts > 0)) return '';
    const s = st.ts;
    const f = (x) => String(+x.toPrecision(4));
    if (st.w) return `T½ ≈ ${expText(s.toExponential(2))} s from the width`;
    if (s >= YEAR_S) return `${expText(f(s / YEAR_S))} y`;
    if (s >= 86400) return `${f(s / 86400)} d`;
    if (s >= 3600) return `${f(s / 3600)} h`;
    if (s >= 60) return `${f(s / 60)} min`;
    if (s >= 1) return `${f(s)} s`;
    return `${expText(s.toExponential(3))} s`;
  }

  /** A short half-life for a chart cell: at most about eight characters. */
  function halfLifeShort(st) {
    if (!st) return '';
    if (st.st) return 'stable';
    const p = halfLifeParts(st);
    if (p.unknown) return '';
    let v = p.value;
    const num = Number(String(st.t).trim().split(/\s+/)[0]);
    if (Number.isFinite(num)) {
      const a = Math.abs(num);
      v = a >= 1e5 || (a > 0 && a < 1e-3) ? expText(num.toExponential(1).replace(/\.0e/, 'e')) : String(+num.toPrecision(3));
    }
    return `${p.q && p.q !== '≈' ? p.q : ''}${v} ${p.unit}`;
  }

  /* ---------------------------------------------------------------------
     Decay modes
     --------------------------------------------------------------------- */
  const MODE_TEXT = {
    'B-': 'β⁻', 'B+': 'β⁺', EC: 'EC', 'EC+B+': 'ε', A: 'α', IT: 'IT', SF: 'SF', P: 'p', '2P': '2p', N: 'n', '2N': '2n',
    D: 'd', '3H': 't', '3HE': '³He', '2B-': '2β⁻', '2B+': '2β⁺', '2EC': '2ε',
  };

  /** 'B-2N' -> 'β⁻2n', 'ECP' -> 'εp', '14C' -> '¹⁴C'. */
  function modeText(mode) {
    const m = String(mode || '').toUpperCase();
    if (MODE_TEXT[m]) return MODE_TEXT[m];
    let r = /^(EC\+B\+|B-|B\+|EC)(.+)$/.exec(m);
    if (r) {
      const head = r[1] === 'EC+B+' || r[1] === 'EC' ? 'ε' : MODE_TEXT[r[1]];
      return head + r[2].replace(/SF/, 'SF').replace(/A/g, 'α').replace(/N/g, 'n').replace(/P/g, 'p').replace(/D/g, 'd').replace(/T/g, 't');
    }
    r = /^(\d{1,2})([A-Z]{1,2})$/.exec(m);
    if (r) { const el = ELEMENTS.find(([s]) => s.toUpperCase() === r[2]); return sup(r[1]) + (el ? el[0] : r[2]); }
    return m;
  }

  /** What a mode means, for a tooltip. */
  const MODE_MEANING = {
    'B-': 'beta-minus decay', 'EC+B+': 'electron capture and beta-plus decay together', EC: 'electron capture',
    'B+': 'beta-plus decay', A: 'alpha decay', IT: 'isomeric transition (gamma decay or internal conversion)',
    SF: 'spontaneous fission', P: 'proton emission', '2P': 'two-proton emission', N: 'neutron emission',
    '2N': 'two-neutron emission', '2B-': 'double beta-minus decay', '2EC': 'double electron capture',
  };
  function modeMeaning(mode) {
    const m = String(mode || '').toUpperCase();
    if (MODE_MEANING[m]) return MODE_MEANING[m];
    const sh = P.modeShift(m);
    if (sh && sh.delayed) return `${sh.family === 'B-' ? 'beta-minus' : 'electron-capture'}-delayed ${m.replace(/^(EC\+B\+|B-|B\+|EC)/, '').toLowerCase()} emission`;
    if (sh && !sh.fission) return 'cluster emission';
    return '';
  }

  const LIMIT_OPS = new Set(['<', '>', '<=', '>=', 'LT', 'GT', 'LE', 'GE']);
  const isLimit = (op) => !!op && LIMIT_OPS.has(op);
  const LIMIT_SIGN = { '<': '<', '>': '>', '<=': '≤', '>=': '≥', LT: '<', GT: '>', LE: '≤', GE: '≥', '~': '≈' };
  /** A branch share with the sign of its limit, if it is one: "≤ 20 %". */
  function sharePct(p, op) {
    const sign = op ? LIMIT_SIGN[op] || '' : '';
    return `${sign ? sign + ' ' : ''}${pctText(p)}`;
  }

  /** A branch percentage: 100 %, 99.84 %, 5.45×10⁻⁵ %. */
  function pctText(p) {
    if (p === null || p === undefined || !Number.isFinite(p)) return '?';
    if (p === 0) return '0 %';
    const a = Math.abs(p);
    if (a >= 0.001) return `${String(+p.toPrecision(a >= 1 ? 4 : a >= 0.01 ? 3 : 2))} %`;
    return `${expText(p.toExponential(2).replace(/\.?0+e/, 'e'))} %`;
  }

  /** One decay mode as the file states it: 'β⁻ 99.84 % 4', 'α < 10×10⁻⁵ %', 'IT ?'. */
  function modeStated(dm) {
    const [mode, op, value, unc] = dm;
    const head = modeText(mode);
    if (value === '?' || value === '') return { mode: head, rel: '', value: '?', unc: '' };
    const parts = valueParts(value, unc);
    const rel = op === '=' ? '' : (op === 'AP' ? '≈' : op === 'LT' ? '<' : op === 'GT' ? '>' : op === 'LE' ? '≤' : op === 'GE' ? '≥' : op);
    return { mode: head, rel, value: parts.value, unc: parts.unc || (parts.plus ? `+${parts.plus}−${parts.minus}` : '') };
  }

  /** The largest branch of a state, for colouring by decay mode. */
  function primaryMode(st) {
    if (!st) return 'unknown';
    if (st.st) return 'stable';
    let best = null;
    for (const b of st.br || []) {
      const p = b[1] === null ? -1 : b[1];
      if (!best || p > best.p) best = { m: b[0], p };
    }
    if (!best) return st.ts !== undefined ? 'unknown' : 'unknown';
    return modeFamily(best.m);
  }

  /** The colour family of a mode. */
  function modeFamily(mode) {
    const sh = P.modeShift(mode);
    if (!sh) return 'other';
    if (sh.fission && !sh.delayed) return 'sf';
    if (sh.family === 'B-' || sh.family === '2B-') return 'bm';
    if (sh.family === 'EC' || sh.family === '2EC') return 'ec';
    if (sh.family === 'IT') return 'it';
    if (sh.family === 'A') return 'a';
    if (sh.family === 'P' || sh.family === '2P') return 'p';
    if (sh.family === 'N' || sh.family === '2N') return 'n';
    return 'other';
  }

  /* ---------------------------------------------------------------------
     Colours. Half-life: eleven classes on a warm sequential ramp whose
     lightness only ever moves one way, longest-lived darkest on the light
     theme; the dark theme flips the anchor so the long-lived end is the
     light one and the short-lived end recedes into the dark page. Stable is
     its own colour off the end of the ramp. Checked with the dataviz
     validator: adjacent steps 0.062 apart in OKLCH lightness (0.060 dark),
     stable 16.7 (light) / 10.9 (dark) OKLab ΔE×100 from the longest class.
     --------------------------------------------------------------------- */
  const HALF_LIFE_CLASSES = [
    { min: 1e9 * YEAR_S, label: '> 10⁹ y' },
    { min: 1e6 * YEAR_S, label: '10⁶ – 10⁹ y' },
    { min: 1e3 * YEAR_S, label: '10³ – 10⁶ y' },
    { min: YEAR_S, label: '1 – 10³ y' },
    { min: 86400, label: '1 d – 1 y' },
    { min: 3600, label: '1 h – 1 d' },
    { min: 60, label: '1 min – 1 h' },
    { min: 1, label: '1 s – 1 min' },
    { min: 1e-3, label: '1 ms – 1 s' },
    { min: 1e-6, label: '1 µs – 1 ms' },
    { min: 0, label: '< 1 µs' },
  ];
  const PALETTE = {
    light: {
      halfLife: ['#3a1463', '#5b1b6d', '#7e216e', '#a12968', '#c2355c', '#e04746', '#f0673f', '#fc863e', '#ffa954', '#feca73', '#ffe890'],
      stable: '#1b1511', unknown: '#cfc6bd', missing: '#e6ded5',
      /* decay modes: the documented categorical slots, assigned by search over
         the pairs that touch on the chart; see the note in ensdf.css */
      mode: { stable: '#1b1511', bm: '#2a78d6', ec: '#e87ba4', a: '#eda100', sf: '#008300', p: '#4a3aa7', n: '#1baf7a', it: '#eb6834', other: '#eb6834', unknown: '#cfc6bd' },
      seq: ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#1c5cab', '#104281', '#0d366b'],
      /* Diverging arms run from the midpoint outwards: blue steps 250/400/550/700
         of the documented ramp, and a red arm matched to them step for step in
         OKLCH lightness (0.76, 0.62, 0.48, 0.34) at hue 27. */
      div: { neg: ['#86b6ef', '#3987e5', '#1c5cab', '#0d366b'], mid: '#f0efec', pos: ['#f59389', '#d7584f', '#9e342e', '#681110'] },
    },
    dark: {
      halfLife: ['#ffe890', '#fecf82', '#feb570', '#fc9a63', '#fd7a54', '#f65b58', '#dc4e71', '#be4581', '#9d3f8b', '#7b3c8e', '#593888'],
      stable: '#fbf6ee', unknown: '#5d534a', missing: '#3a312a',
      mode: { stable: '#fbf6ee', bm: '#3987e5', ec: '#d55181', a: '#c98500', sf: '#008300', p: '#9085e9', n: '#199e70', it: '#d95926', other: '#d95926', unknown: '#5d534a' },
      seq: ['#0d366b', '#104281', '#184f95', '#1c5cab', '#2a78d6', '#5598e7', '#86b6ef', '#b7d3f6'],
      /* Dark: the anchor flips, so the arms grow lighter away from a dark midpoint. */
      div: { neg: ['#184f95', '#2a78d6', '#6da7ec', '#b7d3f6'], mid: '#383835', pos: ['#892c27', '#c74941', '#e5857a', '#febeb6'] },
    },
  };
  const MODE_LEGEND = [
    ['stable', 'stable'], ['bm', 'β⁻'], ['ec', 'ε, β⁺'], ['a', 'α'], ['sf', 'fission'], ['p', 'p, 2p'], ['n', 'n, 2n'], ['other', 'other'], ['unknown', 'not known'],
  ];

  function halfLifeClass(st) {
    if (!st) return -1;
    if (st.st) return -2;
    if (!(st.ts >= 0)) return -1;
    for (let i = 0; i < HALF_LIFE_CLASSES.length; i++) if (st.ts >= HALF_LIFE_CLASSES[i].min) return i;
    return HALF_LIFE_CLASSES.length - 1;
  }

  function halfLifeColour(st, theme) {
    const pal = PALETTE[theme === 'dark' ? 'dark' : 'light'];
    const c = halfLifeClass(st);
    if (c === -2) return pal.stable;
    if (c === -1) return pal.unknown;
    return pal.halfLife[c];
  }

  /* sRGB <-> OKLab, for interpolating the continuous scales evenly. */
  const s2l = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const l2s = (c) => { c = Math.max(0, Math.min(1, c)); return c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055; };
  function hexToLab(h) {
    const [r, g, b] = [1, 3, 5].map((i) => s2l(parseInt(h.slice(i, i + 2), 16) / 255));
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    return [0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s, 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s, 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s];
  }
  function labToHex([L, A, B]) {
    const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3;
    const m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3;
    const s = (L - 0.0894841775 * A - 1.2914855480 * B) ** 3;
    const rgb = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s, -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s];
    return '#' + rgb.map((c) => Math.round(l2s(c) * 255).toString(16).padStart(2, '0')).join('');
  }
  const labCache = new Map();
  const lab = (h) => { let v = labCache.get(h); if (!v) { v = hexToLab(h); labCache.set(h, v); } return v; };

  /** A colour t of the way (0..1) along a list of stops. */
  function along(stops, t) {
    const x = Math.max(0, Math.min(1, t)) * (stops.length - 1);
    const i = Math.min(stops.length - 2, Math.floor(x));
    const f = x - i;
    const a = lab(stops[i]), b = lab(stops[i + 1]);
    return labToHex([a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f]);
  }

  /** Relative luminance, to choose ink or white for text laid on a fill. */
  function luminance(h) {
    const [r, g, b] = [1, 3, 5].map((i) => s2l(parseInt(h.slice(i, i + 2), 16) / 255));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }
  const inkOn = (fill) => (luminance(fill) > 0.28 ? '#1b1511' : '#ffffff');

  /* ---------------------------------------------------------------------
     Colour modes of the chart. Each gives a value per nuclide (ground
     state), a colour for it and a legend.
     --------------------------------------------------------------------- */
  const num = (s) => P.num(s);
  const COLOUR_MODES = {
    halflife: { label: 'Half-life', kind: 'class' },
    mode: { label: 'Decay mode', kind: 'category' },
    qb: { label: 'Q(β⁻)', unit: 'keV', kind: 'diverging', get: (n) => (n.q ? num(n.q[0]) : NaN), note: 'Energy released in beta-minus decay of the ground state; negative where beta-minus decay cannot happen.' },
    qa: { label: 'Q(α)', unit: 'keV', kind: 'diverging', get: (n) => (n.q ? num(n.q[6]) : NaN), note: 'Energy released in alpha decay of the ground state; positive where alpha decay is energetically possible.' },
    sn: { label: 'S(n)', unit: 'keV', kind: 'diverging', get: (n) => (n.q ? num(n.q[2]) : NaN), note: 'Neutron separation energy; negative beyond the neutron drip line.' },
    sp: { label: 'S(p)', unit: 'keV', kind: 'diverging', get: (n) => (n.q ? num(n.q[4]) : NaN), note: 'Proton separation energy; negative beyond the proton drip line.' },
    e2: { label: 'E(2⁺₁)', unit: 'keV', kind: 'log', get: (n) => (n.e2 ? num(n.e2) : NaN), note: 'Energy of the first 2⁺ level, for even-even nuclides.' },
    year: { label: 'Evaluation date', unit: '', kind: 'linear', get: (n) => (n.ev && /^\d{6}$/.test(n.ev[1]) ? +n.ev[1].slice(0, 4) + (+n.ev[1].slice(4) - 0.5) / 12 : NaN), note: 'When the adopted data set was last entered in ENSDF.' },
  };

  /**
   * The domain of a continuous colour mode over the loaded nuclides: the 2nd
   * and 98th percentiles, so a handful of extreme values do not flatten the
   * rest; symmetric about zero for the diverging ones.
   */
  function scaleDomain(mode, list) {
    const spec = COLOUR_MODES[mode];
    const vals = list.map(spec.get).filter((v) => Number.isFinite(v) && (spec.kind !== 'log' || v > 0)).sort((a, b) => a - b);
    if (!vals.length) return null;
    const q = (p) => vals[Math.min(vals.length - 1, Math.max(0, Math.round(p * (vals.length - 1))))];
    let lo = q(0.02), hi = q(0.98);
    if (spec.kind === 'diverging') { const m = Math.max(Math.abs(lo), Math.abs(hi)); lo = -m; hi = m; }
    if (spec.kind === 'log') { lo = Math.log10(Math.max(lo, 1e-3)); hi = Math.log10(hi); }
    if (spec.kind === 'linear') { lo = Math.floor(q(0.02)); hi = vals[vals.length - 1]; }
    if (hi === lo) hi = lo + 1;
    return { lo, hi, kind: spec.kind };
  }

  function scaleColour(domain, v, theme) {
    const pal = PALETTE[theme === 'dark' ? 'dark' : 'light'];
    if (!domain || !Number.isFinite(v)) return pal.unknown;
    if (domain.kind === 'diverging') {
      const t = v / domain.hi;
      if (t >= 0) return along([pal.div.mid, ...pal.div.pos], Math.min(1, t));
      return along([pal.div.mid, ...pal.div.neg], Math.min(1, -t));
    }
    const x = domain.kind === 'log' ? Math.log10(Math.max(v, 1e-3)) : v;
    return along(pal.seq, (x - domain.lo) / (domain.hi - domain.lo));
  }

  /** The fill of a nuclide under a colour mode. */
  function nuclideColour(n, mode, domain, theme) {
    const pal = PALETTE[theme === 'dark' ? 'dark' : 'light'];
    const g = n.s && n.s[0];
    if (!g) return pal.missing;
    if (mode === 'halflife') return halfLifeColour(g, theme);
    if (mode === 'mode') return pal.mode[primaryMode(g)] || pal.mode.other;
    return scaleColour(domain, COLOUR_MODES[mode].get(n), theme);
  }

  /* ---------------------------------------------------------------------
     The decay chain
     --------------------------------------------------------------------- */

  /**
   * Every nuclide and state below a starting state, and the branches
   * between them.
   *
   * Branch fractions come from the summary, where the reader already worked
   * out which isomer of the daughter each branch lands in. A member that
   * lives less than `minHalfLifeS` -- nuclide or isomer, but never the state
   * the chain starts from and never a stable one -- is left out, and the
   * chain goes straight on to wherever it decays: with members under a year
   * left out, 238U goes to 234U, 226Ra to 210Pb and 210Pb to 206Pb.
   * `minIsomerS` does the same for isomers alone: 109Cd feeds the 40 s isomer
   * of 109Ag, which is real, but in a chain it can be one box too many.
   * exits() and addEdge() say how the shares and arrows come out.
   *
   * @param {Object} idx - index()
   * @param {number} z
   * @param {number} a
   * @param {number} k - state index of the start
   * @param {{minHalfLifeS?: number, minIsomerS?: number, minBranch?: number, maxNodes?: number}} [opt]
   *   the shortest half-life, in seconds, a member (any member, or isomers
   *   alone) must have to be drawn, 0 for all; minBranch is a percentage of
   *   the parent's decays below which a branch is left out.
   * @returns {{nodes: Array, edges: Array, root: Object, truncated: boolean}}
   */
  function buildChain(idx, z, a, k, opt = {}) {
    const minHalfLifeS = opt.minHalfLifeS || 0;
    const minIsomerS = opt.minIsomerS || 0;
    const minBranch = opt.minBranch || 0;
    const maxNodes = opt.maxNodes || 400;
    const nodes = new Map();
    const edges = new Map();
    let truncated = false;

    const key = (zz, aa, kk) => `${zz},${aa},${kk}`;
    function node(zz, aa, kk) {
      const kkey = key(zz, aa, kk);
      let nd = nodes.get(kkey);
      if (!nd) {
        const nuc = idx.get(zz, aa);
        const st = nuc && kk >= 0 ? nuc.s[kk] : null;
        nd = { key: kkey, z: zz, a: aa, k: kk, nuc, st, kind: st ? 'state' : 'missing', cum: 0, depth: 0, out: [], in: [] };
        nodes.set(kkey, nd);
      }
      return nd;
    }
    function fission(parent) {
      const kkey = `SF:${parent.key}`;
      let nd = nodes.get(kkey);
      if (!nd) {
        nd = { key: kkey, z: parent.z, a: parent.a, k: -1, nuc: null, st: null, kind: 'fission', cum: 0, depth: 0, out: [], in: [], parent: parent.key };
        nodes.set(kkey, nd);
      }
      return nd;
    }

    /* The branches of a state as [mode, percent or null, targets, inferred,
       limit]. Branches that add up to more than 100 % are scaled down to it
       -- but only the ones given as values: "%A=100, %SF<=20" is alpha at
       least 80 %, not 83 %, and the limit stays a limit. Those under
       minBranch are dropped. */
    function branches(st) {
      const br = st.br || [];
      const total = br.reduce((t, b) => t + (b[1] === null || isLimit(b[4]) ? 0 : b[1]), 0);
      const scale = total > 100 ? 100 / total : 1;
      const out = [];
      for (const [mode, pct, targets, inferred, op] of br) {
        const limit = isLimit(op) ? op : '';
        const p = pct === null ? null : (limit ? pct : pct * scale);
        if (p !== null && minBranch && p < minBranch) continue;
        out.push([mode, p, targets, !!inferred, limit]);
      }
      return out;
    }

    /* A state the chain leaves out, as {nuc, st}, or null for one it draws.
       A half-life that is not known does not reach the threshold. */
    function leftOut(zz, aa, kk) {
      if (zz === z && aa === a && kk === k) return null;
      const nuc = idx.get(zz, aa);
      const st = nuc && kk >= 0 ? nuc.s[kk] : null;
      if (!st || st.st || !(st.br || []).length) return null;
      const min = Math.max(minHalfLifeS, kk > 0 ? minIsomerS : 0);
      return min > 0 && !(st.ts >= min) ? { nuc, st } : null;
    }

    /*
      Where the decays of a left-out state come to rest: every branch it has
      is followed, through any other left-out states, to the drawn states --
      or fission -- that it reaches, the share of a route being the product of
      the branches along it. With members under an hour left out, 234mPa
      sends 99.84 % of its decays to 234U and 0.16 % by IT to 234Pa, so 234Th
      reaches 234U by 99.85 % x 99.84 % = 99.69 %. Worked out once for each
      left-out state and kept, not route by route: in a chain of neutron-rich
      nuclides, each with its beta-delayed neutrons, the routes run to
      millions.

      Entries {to, f, more, it, steps, main, mainF, limit, inferred}: to is
      the state reached ({z, a, k}), null for fission; f the fraction of the
      left-out state's decays known to get there, and more whether some of
      the way has no percentage, so that it may be more -- 131mSn's IT is
      listed without one, and must not make all of 131In's decays to 131Sn
      unknown; it whether every step was an IT, so that the route stays in
      one nuclide; steps every left-out state on the way, main the likeliest
      single route and mainF its fraction; limit a limit (<, <=) met on the
      way; inferred whether a step other than an IT is one the reader
      assumed. A step {key, name, t, e, mode, inferred} is a left-out state
      and how it decayed.
    */
    const exitMemo = new Map();
    function exits(zz, aa, kk, lo) {
      const skey = key(zz, aa, kk);
      /* null while being worked out: a cycle, which real data never has. */
      if (exitMemo.has(skey)) return exitMemo.get(skey) || [];
      exitMemo.set(skey, null);
      const out = new Map();
      const put = (x) => {
        const mk = `${x.to ? key(x.to.z, x.to.a, x.to.k) : 'SF'}|${x.it}`;
        const y = out.get(mk);
        if (!y) { out.set(mk, x); return; }
        y.f += x.f;
        y.more = y.more || x.more;
        for (const s of x.steps) if (!y.steps.some((t) => t.key === s.key)) y.steps.push(s);
        if (x.mainF > y.mainF) { y.main = x.main; y.mainF = x.mainF; }
        y.limit = y.limit || x.limit;
        y.inferred = y.inferred || x.inferred;
      };
      for (const [mode, p, targets, inf, lim] of branches(lo.st)) {
        /* A branch with no percentage adds nothing known, and makes it "more". */
        const fp = p === null ? 0 : p / 100;
        const unknown = p === null;
        const step = { key: skey, name: plainName(zz, aa, kk, lo.nuc), t: halfLifeShort(lo.st), e: lo.st.e, mode, inferred: inf };
        const turned = mode !== 'IT' && inf;
        if (!targets.length) {
          put({ to: null, f: fp, more: unknown, it: false, steps: [step], main: [step], mainF: fp, limit: lim, inferred: turned });
          continue;
        }
        for (const [z2, a2, k2, g] of targets) {
          const lo2 = leftOut(z2, a2, k2);
          if (!lo2) {
            put({ to: { z: z2, a: a2, k: k2 }, f: fp * g, more: unknown, it: mode === 'IT', steps: [step], main: [step], mainF: fp * g, limit: lim, inferred: turned });
            continue;
          }
          for (const x of exits(z2, a2, k2, lo2)) {
            put({
              to: x.to, f: fp * g * x.f, more: unknown || x.more, it: mode === 'IT' && x.it,
              steps: [step, ...x.steps.filter((t) => t.key !== skey)], main: [step, ...x.main], mainF: fp * g * x.mainF,
              limit: lim || x.limit, inferred: turned || x.inferred,
            });
          }
        }
      }
      const list = [...out.values()];
      exitMemo.set(skey, list);
      return list;
    }

    const root = node(z, a, k);
    root.cum = 1;
    const queue = [root];
    const seen = new Set([root.key]);
    while (queue.length) {
      const nd = queue.shift();
      const st = nd.st;
      if (!st || st.st || nd.kind !== 'state') continue;
      for (const [mode, p, targets, inferred, limit] of branches(st)) {
        if (!targets.length) {
          addEdge(nd, fission(nd), mode, p, 1, inferred, null, limit);
          continue;
        }
        for (const [z2, a2, k2, g] of targets) {
          const lo = leftOut(z2, a2, k2);
          for (const x of lo ? exits(z2, a2, k2, lo) : [{ to: { z: z2, a: a2, k: k2 }, f: 1, more: false, limit: '' }]) {
            let to;
            if (!x.to) to = fission(nd);
            else {
              if (nodes.size >= maxNodes && !nodes.has(key(x.to.z, x.to.a, x.to.k))) { truncated = true; continue; }
              to = node(x.to.z, x.to.a, x.to.k);
              if (!seen.has(to.key)) { seen.add(to.key); queue.push(to); }
            }
            addEdge(nd, to, mode, p, g * x.f, inferred, lo ? x : null, limit || x.limit, g);
          }
        }
      }
    }

    /*
      One arrow per parent, daughter and first decay mode -- and one more for
      the routes that jumped over left-out states. A route whose left-out
      states were isomers that only de-excited (IT) lands in the nuclide the
      branch itself points at, and joins the plain arrow: 137Cs goes to 137Ba
      by one beta-minus arrow of 100 %, 94.7 % of it through 137mBa. Any other
      route points somewhere no single decay of the parent does -- 234Th to
      234U, two columns across -- and all such routes from one state to
      another make one arrow, which the drawing marks "via 234mPa". On an
      edge, `via` is the likeliest of those routes (its left-out states, in
      order; empty for a plain arrow), `skipped` every left-out state behind
      the arrow, that route's first, and `skippedPct` the share that went
      through them. The arrow is inferred -- dashed -- where its own branch
      is, or a step that moved it: an IT the reader assumed for a left-out
      isomer changes nothing the arrow says, so 234Pa to 234U stays a stated
      100 % although a fifth of it passes through 234mU, for which ENSDF
      gives no decay. A share is the sum of what is known; `more` says that
      part of the arrow had no percentage, so that the share is at least
      that, and it is null only where none of it is known.
    */
    function addEdge(from, to, mode, p, f, branchInferred, x, limit, g = 1) {
      const jump = !!x && !x.it;
      const ekey = `${from.key}>${to.key}>${jump ? 'via' : mode}`;
      let e = edges.get(ekey);
      if (!e) {
        e = { key: ekey, from, to, mode, pct: 0, more: false, inferred: false, via: [], skipped: [], skippedPct: 0, skippedMore: false, limit: '', mainPct: -1 };
        edges.set(ekey, e);
        from.out.push(e);
        to.in.push(e);
      }
      const share = p === null ? 0 : p * f;
      const unknown = p === null || !!(x && x.more);
      e.pct += share;
      e.more = e.more || unknown;
      if (x) {
        e.skippedPct += share;
        e.skippedMore = e.skippedMore || unknown;
        if (jump) {
          const main = p === null ? 0 : p * g * x.mainF;
          if (main > e.mainPct) {
            e.mainPct = main;
            e.via = x.main;
            e.mode = mode;
          }
        }
        for (const s of x.steps) if (!e.skipped.some((t) => t.key === s.key)) e.skipped.push(s);
      }
      if (branchInferred || (x && x.inferred)) e.inferred = true;
      if (limit) e.limit = e.limit || limit;
    }
    for (const e of edges.values()) {
      if (e.more && !e.pct) { e.pct = null; e.more = false; }
      if (e.skippedMore && !e.skippedPct) { e.skippedPct = null; e.skippedMore = false; }
      if (e.via.length) e.skipped = e.via.concat(e.skipped.filter((s) => !e.via.some((v) => v.key === s.key)));
    }

    /* Cumulative fractions and generations, in topological order. A cycle
       cannot happen in real data; if one ever did, the nodes on it are
       simply left where they are. */
    const indeg = new Map([...nodes.values()].map((n) => [n.key, n.in.length]));
    const order = [];
    const ready = [root];
    indeg.set(root.key, 0);
    while (ready.length) {
      const nd = ready.shift();
      order.push(nd);
      for (const e of nd.out) {
        if (e.pct !== null) e.to.cum += nd.cum * e.pct / 100;
        if (e.pct === null || e.more) e.to.cumUnknown = true;
        if (nd.cumUnknown) e.to.cumUnknown = true;
        /* Reached through a limit: the share uses the limit's value. */
        if (e.limit || nd.bounded) e.to.bounded = true;
        e.to.depth = Math.max(e.to.depth, nd.depth + 1);
        const d = indeg.get(e.to.key) - 1;
        indeg.set(e.to.key, d);
        if (d === 0) ready.push(e.to);
      }
    }
    for (const nd of nodes.values()) if (!order.includes(nd)) order.push(nd);
    return { nodes: order, edges: [...edges.values()], root, truncated };
  }

  return {
    ELEMENTS, index, name, plainName, sup, supRuns, asciiText, isomerLabel, parseQuery, stateForLabel,
    expText, valueParts, uncertaintyText, halfLifeParts, halfLifeText, halfLifeAlt, halfLifeShort,
    modeText, modeMeaning, modeStated, pctText, sharePct, isLimit, primaryMode, modeFamily,
    HALF_LIFE_CLASSES, PALETTE, MODE_LEGEND, halfLifeClass, halfLifeColour, along, luminance, inkOn,
    COLOUR_MODES, scaleDomain, scaleColour, nuclideColour, buildChain, YEAR_S,
  };
});
