/* ==========================================================================
   ENSDF.HTML: THE READER

   Turns the text of the Evaluated Nuclear Structure Data File into the two
   things the page draws from:

     summary  one entry per nuclide: its ground state and isomers, their
              half-lives, spins and decay modes, the Q-values, who evaluated
              it, and -- worked out here, once -- where each decay branch
              goes, down to which isomer of the daughter it lands in;

     details  per mass number: every adopted level and gamma ray, the list of
              data sets, and the radiation each state emits when it decays.

   The same file runs in three places: in the page's worker when a visitor
   opens an ENSDF file of their own, on the page itself when there is no
   worker (a file:// visit), and in scripts/gen-ensdf.mjs, which builds the
   release that ships with the site. One reader, so a database opened in the
   browser and the built-in one can never disagree about what a record says.

   THE FORMAT (ENSDF manual, BNL-NCS-51655-01/02-Rev, Tuli 2001)

   Every record is 80 columns and every field sits at a fixed column range.
   Fields are NOT separated by blanks -- `455.84    130.011   5` is an energy
   of 455.84, its uncertainty 13, an intensity of 0.011 and that intensity's
   uncertainty 5 -- so nothing here splits on whitespace; every read is a
   slice at the manual's columns. The slices below are 0-based: the manual's
   "columns 10-19" is slice(9, 19).

   A data set is a run of records ended by a blank one. Column 6 blank (or
   '1') starts a record; any other character there continues the one before
   it, and continuation records carry `NAME=value` fields separated by '$'.
   Column 7 carries C/D/T for a comment; comments are not read.

   One global: KVOT_ENSDF (module.exports under Node).
   ========================================================================== */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.KVOT_ENSDF = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /* ---------------------------------------------------------------------
     Elements. Index is Z. ENSDF writes the neutron as 'NN' and elements
     above 109 either by symbol or as Z - 100 in the two element columns.
     --------------------------------------------------------------------- */
  const ELEMENTS = [
    ['n', 'neutron'], ['H', 'hydrogen'], ['He', 'helium'], ['Li', 'lithium'], ['Be', 'beryllium'],
    ['B', 'boron'], ['C', 'carbon'], ['N', 'nitrogen'], ['O', 'oxygen'], ['F', 'fluorine'],
    ['Ne', 'neon'], ['Na', 'sodium'], ['Mg', 'magnesium'], ['Al', 'aluminium'], ['Si', 'silicon'],
    ['P', 'phosphorus'], ['S', 'sulfur'], ['Cl', 'chlorine'], ['Ar', 'argon'], ['K', 'potassium'],
    ['Ca', 'calcium'], ['Sc', 'scandium'], ['Ti', 'titanium'], ['V', 'vanadium'], ['Cr', 'chromium'],
    ['Mn', 'manganese'], ['Fe', 'iron'], ['Co', 'cobalt'], ['Ni', 'nickel'], ['Cu', 'copper'],
    ['Zn', 'zinc'], ['Ga', 'gallium'], ['Ge', 'germanium'], ['As', 'arsenic'], ['Se', 'selenium'],
    ['Br', 'bromine'], ['Kr', 'krypton'], ['Rb', 'rubidium'], ['Sr', 'strontium'], ['Y', 'yttrium'],
    ['Zr', 'zirconium'], ['Nb', 'niobium'], ['Mo', 'molybdenum'], ['Tc', 'technetium'], ['Ru', 'ruthenium'],
    ['Rh', 'rhodium'], ['Pd', 'palladium'], ['Ag', 'silver'], ['Cd', 'cadmium'], ['In', 'indium'],
    ['Sn', 'tin'], ['Sb', 'antimony'], ['Te', 'tellurium'], ['I', 'iodine'], ['Xe', 'xenon'],
    ['Cs', 'caesium'], ['Ba', 'barium'], ['La', 'lanthanum'], ['Ce', 'cerium'], ['Pr', 'praseodymium'],
    ['Nd', 'neodymium'], ['Pm', 'promethium'], ['Sm', 'samarium'], ['Eu', 'europium'], ['Gd', 'gadolinium'],
    ['Tb', 'terbium'], ['Dy', 'dysprosium'], ['Ho', 'holmium'], ['Er', 'erbium'], ['Tm', 'thulium'],
    ['Yb', 'ytterbium'], ['Lu', 'lutetium'], ['Hf', 'hafnium'], ['Ta', 'tantalum'], ['W', 'tungsten'],
    ['Re', 'rhenium'], ['Os', 'osmium'], ['Ir', 'iridium'], ['Pt', 'platinum'], ['Au', 'gold'],
    ['Hg', 'mercury'], ['Tl', 'thallium'], ['Pb', 'lead'], ['Bi', 'bismuth'], ['Po', 'polonium'],
    ['At', 'astatine'], ['Rn', 'radon'], ['Fr', 'francium'], ['Ra', 'radium'], ['Ac', 'actinium'],
    ['Th', 'thorium'], ['Pa', 'protactinium'], ['U', 'uranium'], ['Np', 'neptunium'], ['Pu', 'plutonium'],
    ['Am', 'americium'], ['Cm', 'curium'], ['Bk', 'berkelium'], ['Cf', 'californium'], ['Es', 'einsteinium'],
    ['Fm', 'fermium'], ['Md', 'mendelevium'], ['No', 'nobelium'], ['Lr', 'lawrencium'], ['Rf', 'rutherfordium'],
    ['Db', 'dubnium'], ['Sg', 'seaborgium'], ['Bh', 'bohrium'], ['Hs', 'hassium'], ['Mt', 'meitnerium'],
    ['Ds', 'darmstadtium'], ['Rg', 'roentgenium'], ['Cn', 'copernicium'], ['Nh', 'nihonium'], ['Fl', 'flerovium'],
    ['Mc', 'moscovium'], ['Lv', 'livermorium'], ['Ts', 'tennessine'], ['Og', 'oganesson'], ['Uue', 'ununennium'],
    ['Ubn', 'unbinilium'],
  ];
  const Z_OF = Object.create(null);
  ELEMENTS.forEach(([sym], z) => { if (z > 0) Z_OF[sym.toUpperCase()] = z; });
  Z_OF.NN = 0;

  /**
   * The mass number and proton number in a NUCID: the mass right-justified
   * in columns 1-3, the element in columns 4-5 (manual V.1). A NUCID with no
   * element -- the mass-chain COMMENTS and REFERENCES data sets -- gives null.
   *
   * @param {string} s - the five columns
   * @returns {{a: number, z: number}|null}
   */
  function parseNucid(s) {
    const t = (s || '').padEnd(5);
    const massText = t.slice(0, 3).trim();
    const el = t.slice(3, 5).trim().toUpperCase();
    if (!/^\d+$/.test(massText) || !el) return null;
    const a = parseInt(massText, 10);
    let z;
    if (/^\d{1,2}$/.test(el)) z = 100 + parseInt(el, 10);
    else z = Z_OF[el];
    if (z === undefined || !(a >= 1) || z > a) return null;
    return { a, z };
  }

  /* ---------------------------------------------------------------------
     Numbers and uncertainties
     --------------------------------------------------------------------- */
  const NUM_RE = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[Ee][+-]?\d+)?$/;

  /**
   * A field's number. Parentheses mean "deduced, not measured" (manual V.13)
   * and do not change the value. Anything else -- blank, 'X', '0+X', '?' --
   * is NaN.
   *
   * @param {string} s
   * @returns {number}
   */
  function num(s) {
    if (!s) return NaN;
    let t = s.trim();
    if (t.charCodeAt(0) === 40 && t.charCodeAt(t.length - 1) === 41) t = t.slice(1, -1).trim();
    return NUM_RE.test(t) ? Number(t) : NaN;
  }

  /**
   * An uncertainty in the manual's "last digits" convention, made absolute.
   * `2822.81` with `21` is +-0.21; `1.51E+6` with `4` is +-0.04E+6. Returns
   * {abs} for a symmetric one, {plus, minus} for `+21-14`, {q} for the
   * non-numeric ones (LT, GT, LE, GE, AP, CA, SY), or null for a blank.
   *
   * @param {string} value
   * @param {string} unc
   * @returns {Object|null}
   */
  function uncertainty(value, unc) {
    const u = (unc || '').trim();
    if (!u) return null;
    const v = (value || '').trim().replace(/^\(|\)$/g, '');
    const m = /^([+-]?)(\d*)(?:\.(\d*))?(?:[Ee]([+-]?\d+))?$/.exec(v);
    const scale = m ? Math.pow(10, (m[4] ? parseInt(m[4], 10) : 0) - (m[3] ? m[3].length : 0)) : 1;
    if (/^\d+$/.test(u)) return { abs: parseInt(u, 10) * scale };
    let a = /^\+(\d+)-(\d+)$/.exec(u);
    if (a) return { plus: parseInt(a[1], 10) * scale, minus: parseInt(a[2], 10) * scale };
    a = /^-(\d+)\+(\d+)$/.exec(u);
    if (a) return { plus: parseInt(a[2], 10) * scale, minus: parseInt(a[1], 10) * scale };
    return { q: u.toUpperCase() };
  }

  /* ---------------------------------------------------------------------
     Half-lives (manual V.14)
     --------------------------------------------------------------------- */
  const YEAR_S = 365.2422 * 86400;
  const TIME_UNIT = {
    Y: YEAR_S, D: 86400, H: 3600, M: 60, MIN: 60, S: 1, MS: 1e-3, US: 1e-6, NS: 1e-9,
    PS: 1e-12, FS: 1e-15, AS: 1e-18,
  };
  /* A level given as a width: T1/2 = hbar ln2 / Gamma, hbar = 6.582119569e-16 eV s. */
  const WIDTH_UNIT = { EV: 1, KEV: 1e3, MEV: 1e6 };
  const HBAR_LN2_EVS = 6.582119569e-16 * Math.LN2;

  /**
   * A half-life field in seconds.
   *
   * @param {string} t - columns 40-49 of a level or parent record
   * @returns {{s: number|null, stable: boolean, width: boolean, doubtful: boolean}}
   *   s is null when there is no number to read; Infinity for STABLE.
   */
  function halfLife(t) {
    const txt = (t || '').trim();
    const out = { s: null, stable: false, width: false, doubtful: /\?\s*$/.test(txt) };
    if (!txt) return out;
    if (/^STABLE/i.test(txt)) { out.stable = true; out.s = Infinity; return out; }
    const m = /^[<>~]?\s*([0-9.]+(?:[Ee][+-]?\d+)?)\s*([A-Za-z]+)/.exec(txt);
    if (!m) return out;
    const value = Number(m[1]);
    const unit = m[2].toUpperCase();
    if (!Number.isFinite(value)) return out;
    if (TIME_UNIT[unit]) out.s = value * TIME_UNIT[unit];
    else if (WIDTH_UNIT[unit] && value > 0) { out.s = HBAR_LN2_EVS / (value * WIDTH_UNIT[unit]); out.width = true; }
    return out;
  }

  /* ---------------------------------------------------------------------
     Level energies (manual V.18): a number, or a number with an unknown
     offset -- '0+X', 'X', '1234.5+Y', 'SN+120'. Two levels can only be
     compared when they carry the same offset, so the offset is kept apart
     from the number.
     --------------------------------------------------------------------- */
  function levelEnergy(s) {
    const txt = (s || '').trim().replace(/^\(|\)$/g, '');
    let n = num(txt);
    if (Number.isFinite(n)) return { n, x: '' };
    let m = /^([0-9.]+(?:[Ee][+-]?\d+)?)\s*\+\s*([A-Z]{1,2})$/i.exec(txt);
    if (m) return { n: Number(m[1]), x: m[2].toUpperCase() };
    m = /^([A-Z]{1,2})\s*\+\s*([0-9.]+(?:[Ee][+-]?\d+)?)$/i.exec(txt);
    if (m) return { n: Number(m[2]), x: m[1].toUpperCase() };
    if (/^[A-Z]{1,2}$/i.test(txt)) return { n: 0, x: txt.toUpperCase() };
    return { n: NaN, x: txt.toUpperCase() };
  }

  /* ---------------------------------------------------------------------
     Continuation fields: `NAME=value $ NAME<value $ NAME EQ value`, with the
     six worded operators needing blanks around them (manual IV.B).
     --------------------------------------------------------------------- */
  const FIELD_RE = /^\s*(%?[A-Z0-9+\-:%]+?)\s*(<=|>=|=|<|>| EQ | AP | LT | LE | GT | GE | CA | SY )\s*(.*?)\s*$/;

  function contFields(text) {
    const out = [];
    for (const part of text.split('$')) {
      if (!part.trim()) continue;
      const m = FIELD_RE.exec(part.replace(/\s+/g, ' '));
      if (m) out.push({ name: m[1].trim(), op: m[2].trim(), value: m[3].trim() });
      else out.push({ name: part.trim(), op: '', value: '' });
    }
    return out;
  }

  /**
   * One decay mode from a level continuation: `%B-=100`, `%EC+%B+=56.3 20`,
   * `%SF<1.0E-4`, `%A=?`, `%IT AP 10`. Returns [mode, op, value, unc] with
   * the percent signs dropped from the mode ('EC+B+').
   */
  function modeFromField(f) {
    if (!f.name.startsWith('%')) return null;
    const mode = f.name.replace(/%/g, '');
    if (!mode) return null;
    const op = f.op === 'EQ' ? '=' : f.op;
    const vm = /^(\?|[+-]?(?:\d+\.?\d*|\.\d+)(?:[Ee][+-]?\d+)?)\s*(\S*)/.exec(f.value);
    let value = vm ? vm[1] : '';
    let unc = vm ? vm[2] : '';
    /* A reference in parentheses is not an uncertainty. */
    if (/^\(/.test(unc)) unc = '';
    if (!value && !op) value = '?';
    return [mode, op || '=', value, unc];
  }

  /* ---------------------------------------------------------------------
     Decay modes: where each one takes the nucleus. [dZ, dN], or null for
     fission, which has no single daughter.
     --------------------------------------------------------------------- */
  const EMIT = {
    N: [0, 1], P: [1, 0], D: [1, 1], T: [1, 2], A: [2, 2], '3H': [1, 2], '3HE': [2, 1],
  };

  function emitted(token) {
    /* '2N', '3P', 'NA' (a neutron then an alpha), '14C', '24NE' */
    if (EMIT[token]) return EMIT[token];
    let m = /^(\d)(N|P|A|D|T)$/.exec(token);
    if (m) { const e = EMIT[m[2]]; return [e[0] * +m[1], e[1] * +m[1]]; }
    m = /^(\d{1,2})([A-Z]{1,2})$/.exec(token);
    if (m && Z_OF[m[2]] !== undefined) { const zc = Z_OF[m[2]]; const ac = +m[1]; if (ac > zc) return [zc, ac - zc]; }
    /* Sequences such as NA or PA. */
    const parts = token.match(/\d?(?:N|P|A|D|T)/g);
    if (parts && parts.join('') === token) {
      let z = 0, n = 0;
      for (const p of parts) { const e = emitted(p); if (!e) return null; z += e[0]; n += e[1]; }
      return [z, n];
    }
    return null;
  }

  /**
   * The change in Z and N a decay mode makes, and whether it is a delayed
   * emission that belongs inside a beta or electron-capture branch.
   *
   * @param {string} mode - 'B-', 'EC+B+', 'B-2N', 'ECP', 'A', '14C', 'SF', ...
   * @returns {{dz: number, dn: number, fission: boolean, family: string, delayed: boolean}|null}
   */
  function modeShift(mode) {
    const m = mode.toUpperCase();
    if (m === 'SF') return { dz: 0, dn: 0, fission: true, family: 'SF', delayed: false };
    if (m === 'IT') return { dz: 0, dn: 0, fission: false, family: 'IT', delayed: false };
    if (m === '2B-') return { dz: 2, dn: -2, fission: false, family: '2B-', delayed: false };
    if (m === '2B+' || m === '2EC' || m === 'ECEC' || m === '2EC+2B+') return { dz: -2, dn: 2, fission: false, family: '2EC', delayed: false };
    let base = null, rest = '';
    for (const [prefix, fam, dz, dn] of [['EC+B+', 'EC', -1, 1], ['B-', 'B-', 1, -1], ['B+', 'EC', -1, 1], ['EC', 'EC', -1, 1]]) {
      if (m.startsWith(prefix)) { base = { fam, dz, dn }; rest = m.slice(prefix.length); break; }
    }
    if (base) {
      if (!rest) return { dz: base.dz, dn: base.dn, fission: false, family: base.fam, delayed: false };
      if (rest === 'SF') return { dz: 0, dn: 0, fission: true, family: base.fam, delayed: true };
      const e = emitted(rest);
      if (!e) return null;
      return { dz: base.dz - e[0], dn: base.dn - e[1], fission: false, family: base.fam, delayed: true };
    }
    const e = emitted(m);
    if (!e) return null;
    return { dz: -e[0], dn: -e[1], fission: false, family: m, delayed: false };
  }

  /**
   * The branches a state actually decays by, with the delayed-particle modes
   * taken out of the beta or electron-capture branch they belong to.
   *
   * ENSDF counts %B-N inside %B-: 11Li is %B-=100 with %B-N=86.3, so only
   * 13.7 % of its decays -- less the other delayed channels -- stop at 11Be.
   * The same holds for ECP, ECA, B+P, ... inside %EC+%B+ (or %EC plus %B+).
   * Every other mode stands on its own.
   *
   * @param {Array} modes - [[mode, op, value, unc], ...] as read
   * @returns {Array} [{mode, pct: number|null, op, shift}]
   */
  function branchesOf(modes) {
    const out = [];
    const fam = { 'B-': null, EC: null };
    const pct = (v) => (v === '?' ? null : num(v));
    /* %EC+%B+ is the whole electron-capture branch; a %EC or %B+ beside it
       is one of its parts and must not be counted again. Given on their own,
       %EC and %B+ add up to the branch. */
    const combined = modes.some(([mode]) => mode === 'EC+B+');
    for (const [mode, op, value] of modes) {
      const sh = modeShift(mode);
      if (!sh) continue;
      if (combined && (mode === 'EC' || mode === 'B+')) continue;
      const p = pct(value);
      const entry = { mode, pct: Number.isFinite(p) ? p : null, op, shift: sh, subtract: 0 };
      if ((sh.family === 'B-' || sh.family === 'EC') && !sh.delayed) {
        const f = fam[sh.family];
        if (f) {
          if (f.pct !== null && entry.pct !== null) f.pct += entry.pct;
          else f.pct = null;
          f.mode = 'EC+B+';
          continue;
        }
        fam[sh.family] = entry;
      }
      out.push(entry);
    }
    for (const e of out) {
      if (!e.shift.delayed) continue;
      const parent = fam[e.shift.family];
      if (parent && parent.pct !== null && e.pct !== null) parent.subtract += e.pct;
    }
    for (const e of out) {
      if (e.subtract && e.pct !== null) e.pct = Math.max(0, e.pct - e.subtract);
      delete e.subtract;
    }
    return out;
  }

  /* ---------------------------------------------------------------------
     Record reading. Every function takes one 80-column line.
     --------------------------------------------------------------------- */
  const col = (ln, a, b) => ln.slice(a, b).trim();

  function readLevel(ln) {
    return {
      e: col(ln, 9, 19), de: col(ln, 19, 21), j: col(ln, 21, 39), t: col(ln, 39, 49), dt: col(ln, 49, 55),
      ms: col(ln, 77, 79), q: ln.charAt(79).trim(), modes: [], mu: '', qm: '', gam: [], feed: [],
    };
  }

  function readGamma(ln) {
    return {
      e: col(ln, 9, 19), de: col(ln, 19, 21), ri: col(ln, 21, 29), dri: col(ln, 29, 31), m: col(ln, 31, 41),
      mr: col(ln, 41, 49), dmr: col(ln, 49, 55), cc: col(ln, 55, 62), dcc: col(ln, 62, 64),
      ti: col(ln, 64, 74), dti: col(ln, 74, 76), flag: ln.charAt(76).trim(), q: ln.charAt(79).trim(),
      fl: '', ig: '', dig: '',
    };
  }

  function readBeta(ln) {
    return {
      kind: 'B', e: col(ln, 9, 19), de: col(ln, 19, 21), ib: col(ln, 21, 29), dib: col(ln, 29, 31),
      logft: col(ln, 41, 49), un: col(ln, 77, 79), q: ln.charAt(79).trim(), eav: '',
    };
  }

  function readEc(ln) {
    return {
      kind: 'E', e: col(ln, 9, 19), de: col(ln, 19, 21), ib: col(ln, 21, 29), dib: col(ln, 29, 31),
      ie: col(ln, 31, 39), die: col(ln, 39, 41), logft: col(ln, 41, 49), ti: col(ln, 64, 74),
      dti: col(ln, 74, 76), q: ln.charAt(79).trim(), eav: '',
    };
  }

  function readAlpha(ln) {
    return {
      kind: 'A', e: col(ln, 9, 19), de: col(ln, 19, 21), ia: col(ln, 21, 29), dia: col(ln, 29, 31),
      hf: col(ln, 31, 39), q: ln.charAt(79).trim(),
    };
  }

  function readParticle(ln) {
    return {
      kind: 'D', delayed: ln.charAt(7) === 'D', particle: ln.charAt(8), e: col(ln, 9, 19), de: col(ln, 19, 21),
      ip: col(ln, 21, 29), dip: col(ln, 29, 31), ei: col(ln, 31, 39), q: ln.charAt(79).trim(),
    };
  }

  function readParent(ln) {
    return {
      nucid: ln.slice(0, 5), e: col(ln, 9, 19), de: col(ln, 19, 21), j: col(ln, 21, 39), t: col(ln, 39, 49),
      dt: col(ln, 49, 55), qp: col(ln, 64, 74), dqp: col(ln, 74, 76), ion: col(ln, 76, 80),
    };
  }

  function readNorm(ln) {
    return {
      nr: col(ln, 9, 19), dnr: col(ln, 19, 21), nt: col(ln, 21, 29), dnt: col(ln, 29, 31), br: col(ln, 31, 39),
      dbr: col(ln, 39, 41), nb: col(ln, 41, 49), dnb: col(ln, 49, 55), np: col(ln, 55, 62), dnp: col(ln, 62, 64),
    };
  }

  function readProdNorm(ln) {
    return { nrbr: col(ln, 9, 19), ntbr: col(ln, 21, 29), nbbr: col(ln, 41, 49), np: col(ln, 55, 62) };
  }

  function readQ(ln) {
    return {
      qb: col(ln, 9, 19), dqb: col(ln, 19, 21), sn: col(ln, 21, 29), dsn: col(ln, 29, 31),
      sp: col(ln, 31, 39), dsp: col(ln, 39, 41), qa: col(ln, 41, 49), dqa: col(ln, 49, 55), qref: col(ln, 55, 80),
    };
  }

  /** History text (manual V.25) into {TYP, AUT, CIT, CUT, DAT, COM}. */
  function historyEntry(text) {
    const out = {};
    for (const part of text.split('$')) {
      const m = /^\s*([A-Z]{3})\s*=\s*(.*?)\s*$/.exec(part);
      if (m) out[m[1]] = out[m[1]] ? out[m[1]] + ' ' + m[2] : m[2];
    }
    return out;
  }

  /**
   * A level's XREF (manual V.24): which data sets saw it, and at what energy
   * when the data set gave it another one. 'ABC', 'A(E1)B', 'A(*E1,E2)',
   * '+' for every data set, '-(AB)' for all but A and B.
   *
   * @param {string} v
   * @returns {{all: boolean, except: Set<string>|null, items: Map<string, string>}}
   */
  function parseXref(v) {
    const t = (v || '').trim();
    if (t === '+') return { all: true, except: null, items: new Map() };
    if (t.startsWith('-(')) {
      const m = /^-\(([^)]*)\)/.exec(t);
      return { all: true, except: new Set((m ? m[1] : '').split('')), items: new Map() };
    }
    const items = new Map();
    let i = 0;
    while (i < t.length) {
      const sym = t[i++];
      let inner = '';
      if (t[i] === '(') {
        const j = t.indexOf(')', i);
        inner = t.slice(i + 1, j < 0 ? t.length : j);
        i = j < 0 ? t.length : j + 1;
      }
      items.set(sym, inner);
    }
    return { all: false, except: null, items };
  }

  /* The data-set kinds the page tells apart. */
  function datasetKind(dsid) {
    if (/^COMMENTS/.test(dsid)) return 'comments';
    if (/^REFERENCES/.test(dsid)) return 'references';
    if (/^ADOPTED LEVELS/.test(dsid)) return 'adopted';
    if (/\bDECAY\b/.test(dsid) && /^\S+\s+\S+\s+DECAY\b/.test(dsid)) return 'decay';
    return 'reaction';
  }

  /* ---------------------------------------------------------------------
     Level schemes: following a cascade
     --------------------------------------------------------------------- */

  /** The index of the level nearest in energy to `e` (same offset), or -1. */
  function nearestLevel(E, e, skip, belowOnly, below) {
    let best = -1, bestD = Infinity;
    if (!e || !Number.isFinite(e.n)) return -1;
    for (let k = 0; k < E.length; k++) {
      if (k === skip || E[k].x !== e.x || !Number.isFinite(E[k].n)) continue;
      if (belowOnly && !(E[k].n < below)) continue;
      const d = Math.abs(E[k].n - e.n);
      if (d < bestD) { bestD = d; best = k; }
    }
    return best;
  }

  /**
   * The level a gamma ray ends in: the one its FL= names, or the one at the
   * initial level's energy less the gamma energy, allowing for the recoil.
   */
  function finalLevel(E, i, g, A) {
    if (g.fl) {
      const fe = levelEnergy(g.fl.replace(/\?$/, ''));
      const k = nearestLevel(E, fe, i, false);
      return k >= 0 && Math.abs(E[k].n - fe.n) <= 1.5 ? k : -1;
    }
    const eg = num(g.e);
    if (!Number.isFinite(eg) || !Number.isFinite(E[i].n)) return -1;
    const target = { n: E[i].n - eg, x: E[i].x };
    const k = nearestLevel(E, target, i, true, E[i].n);
    const tol = 1.0 + 0.001 * eg + (eg * eg) / (2 * 931494 * A);
    return k >= 0 && Math.abs(E[k].n - target.n) <= tol ? k : -1;
  }

  /**
   * Follow a cascade down a level scheme and say where it comes to rest.
   *
   * Level by level from the top, each level's population -- its direct
   * feeding plus whatever came down from above -- is shared among the gamma
   * rays leaving it in proportion to their total transition intensities, TI
   * or RI(1 + alpha). The ground state and the isomers keep what reaches
   * them. Only ratios within one level are used, so the answer does not
   * depend on how a data set is normalised. When a level's gamma rays carry
   * no intensities at all -- 235Pa feeds a 13.1 keV level of 235U whose one
   * gamma ray, unobserved, is placed into the 26-minute isomer -- the flux is
   * shared equally among them. Flux reaching a level with no gamma ray that
   * can be placed is taken to the ground state.
   *
   * With `start` >= 0 the cascade begins there (an isomer decaying by IT) and
   * `direct` is ignored. Without it, and with no direct feeding anywhere,
   * the gamma rays that end in a state are summed instead: the same balance,
   * counted at the bottom of the cascade rather than the top.
   *
   * @param {Array} levels - each with .gam
   * @param {Array} E - levelEnergy() of each level
   * @param {Int32Array} stateAt - state index of each level, -1 for none
   * @param {number} start - level index to start from, or -1
   * @param {Array<number>|null} direct - direct feeding per level
   * @param {function} weightOf - gamma -> transition intensity
   * @param {number} A - mass number, for the recoil correction
   * @returns {Map<number, number>|null} state index -> fraction
   */
  function cascade(levels, E, stateAt, start, direct, weightOf, A) {
    const n = levels.length;
    const pop = new Float64Array(n);
    let total = 0;
    if (start >= 0) { pop[start] = 1; total = 1; } else if (direct) {
      for (let i = 0; i < n; i++) { pop[i] = direct[i] || 0; total += pop[i]; }
    }
    const outsOf = (i) => {
      const all = [];
      let W = 0;
      for (const g of levels[i].gam) {
        const f = finalLevel(E, i, g, A);
        if (f < 0) continue;
        const w = weightOf(g);
        all.push([f, w]);
        W += w;
      }
      if (!all.length) return null;
      if (W > 0) return all.filter(([, w]) => w > 0).map(([f, w]) => [f, w / W]);
      return all.map(([f]) => [f, 1 / all.length]);
    };
    const result = new Map();
    if (total > 0) {
      const order = [...Array(n).keys()].sort((p, q) => ((E[q].n || 0) - (E[p].n || 0)) || (q - p));
      for (const i of order) {
        if (pop[i] <= 0) continue;
        if (stateAt[i] >= 0 && i !== start) continue;
        const outs = outsOf(i);
        if (outs) for (const [f, share] of outs) pop[f] += pop[i] * share;
        pop[i] = 0;
      }
      for (let i = 0; i < n; i++) {
        const k = stateAt[i];
        if (k > 0 && i !== start && pop[i] > 0) result.set(k, (result.get(k) || 0) + pop[i] / total);
      }
    } else {
      /* No feeding numbers: count what arrives at each state instead. */
      const arrive = new Map();
      let sum = 0;
      for (let i = 0; i < n; i++) {
        if (stateAt[i] >= 0) continue;
        for (const g of levels[i].gam) {
          const w = weightOf(g);
          if (w <= 0) continue;
          const f = finalLevel(E, i, g, A);
          if (f < 0 || stateAt[f] < 0) continue;
          arrive.set(stateAt[f], (arrive.get(stateAt[f]) || 0) + w);
          sum += w;
        }
      }
      if (!(sum > 0)) return null;
      for (const [k, w] of arrive) if (k > 0) result.set(k, w / sum);
    }
    let iso = 0;
    for (const v of result.values()) iso += v;
    if (iso > 1) { for (const [k, v] of result) result.set(k, v / iso); iso = 1; }
    result.set(0, Math.max(0, 1 - iso));
    return result;
  }

  /* ---------------------------------------------------------------------
     The builder: feed it files, then ask for the result.
     --------------------------------------------------------------------- */

  /* A level counts as an isomer when the evaluator flagged it metastable, or
     when it lives at least this long. The flag alone is not enough: 90Y at
     682 keV (3.19 h) and 90Rb at 107 keV (258 s) carry no flag in this
     release, and both decay by beta as well as by IT. */
  const ISOMER_MIN_S = 1e-6;

  /* Flags on a state's emitted energies (st.emitx). */
  const EMIT_MISSING = 1;   // a branch has neither decay data set nor Q-value: the energies are low
  const EMIT_SCALED = 2;    // gamma intensities only relative, scaled to the energy they carry
  const EMIT_Q = 4;         // a branch estimated from its Q-value

  /*
    K-shell (1s) binding energies in keV, Z = 1 to 100 (X-ray Data Booklet,
    after Bearden and Burr), for the X-rays and Auger electrons that follow
    electron capture, which ENSDF does not list.
  */
  const K_SHELL_KEV = [0,
    0.0136, 0.0246, 0.0548, 0.111, 0.188, 0.2842, 0.4099, 0.5431, 0.6967, 0.8701,
    1.0708, 1.305, 1.5596, 1.8389, 2.1455, 2.472, 2.8224, 3.206, 3.6074, 4.0381,
    4.4928, 4.9664, 5.4651, 5.9892, 6.539, 7.112, 7.7089, 8.3328, 8.9789, 9.6586,
    10.3671, 11.1031, 11.8667, 12.6578, 13.4737, 14.3256, 15.1997, 16.1046, 17.0384, 17.9976,
    18.9856, 19.9995, 21.044, 22.1172, 23.2199, 24.3503, 25.514, 26.7112, 27.9399, 29.2001,
    30.4912, 31.8138, 33.1694, 34.5614, 35.9846, 37.4406, 38.9246, 40.443, 41.9906, 43.5689,
    45.184, 46.8342, 48.519, 50.2391, 51.9957, 53.7885, 55.6177, 57.4855, 59.3896, 61.3323,
    63.3138, 65.3508, 67.4164, 69.525, 71.6764, 73.8708, 76.111, 78.3948, 80.7249, 83.1023,
    85.5304, 88.0045, 90.5259, 93.105, 95.73, 98.404, 101.137, 103.9218, 106.755, 109.6509,
    112.6014, 115.6061, 118.678, 121.818, 125.027, 128.22, 131.59, 135.96, 139.49, 143.09,
  ];
  function kShellKeV(z) {
    if (z < 1) return 0;
    if (z < K_SHELL_KEV.length) return K_SHELL_KEV[z];
    return K_SHELL_KEV[100] + (z - 100) * 3.8;
  }
  /* K fluorescence yield, the fit of Bambynek et al. (1972); L3, Hubbell et al. (1994). */
  function fluorescenceK(z) {
    const x = Math.pow(0.015 + 0.0327 * z - 0.64e-6 * z * z * z, 4);
    return x / (1 + x);
  }
  function fluorescenceL(z) {
    const x = Math.pow(0.17765 + 0.00298937 * z + 8.91297e-5 * z * z - 2.67184e-7 * z * z * z, 4);
    return x / (1 + x);
  }
  /* L1 and L3 binding energies, near enough, as shares of the K. */
  const l1ShellKeV = (z) => kShellKeV(z) * (0.10 + 0.001 * z);
  const l3ShellKeV = (z) => kShellKeV(z) * (0.085 + 0.0007 * z);

  /*
    What the atom gives off after electron capture with q keV to spare, per
    capture, as [energy, of it in X-rays]. The electron comes from the K,
    L1 or M1 shell in proportion to (q - B)^2 times its density at the
    nucleus, so near the K threshold the K shell falls out: 235Np, with 8.6
    keV over the uranium K edge, captures from it 5 % of the time.
  */
  function captureAtom(q, z) {
    const bk = kShellKeV(z), bl = l1ShellKeV(z), bm = 0.22 * bl;
    const rl = 0.07 + 0.0013 * z;
    const w = (b, r) => (q > b ? (q - b) * (q - b) * r : 0);
    const wk = Number.isFinite(q) ? w(bk, 1) : 1;
    const wl = Number.isFinite(q) ? w(bl, rl) : rl;
    const wm = Number.isFinite(q) ? w(bm, rl * 0.25) : rl * 0.25;
    const sum = wk + wl + wm;
    if (!sum) return [0, 0];
    const pk = wk / sum, pl = wl / sum, pm = wm / sum;
    const energy = pk * bk + pl * bl + pm * bm;
    const xray = pk * fluorescenceK(z) * 0.88 * bk + pl * fluorescenceL(z) * 0.8 * l3ShellKeV(z);
    return [energy, xray];
  }

  /*
    The multipliers that turn a decay data set's relative intensities into
    intensities per 100 decays of the parent: NR x BR for photons, NB x BR
    for beta and electron-capture feedings. The N record's own product comes
    first where it gives both factors; the production-normalisation (PN)
    record is for when it does not. The two can disagree -- 115mIn's beta-
    minus data set has NB = 20 and BR = 0.050 on its N record and "20.0" as
    NB x BR on its PN record, which would make its 5 % branch 100 %.
  */
  function normProducts(n, pn, br) {
    const nr = num(n.nr), nb = num(n.nb), hasBr = Number.isFinite(num(n.br));
    const nrbr = Number.isFinite(nr) && hasBr ? nr * br : Number.isFinite(num(pn.nrbr)) ? num(pn.nrbr) : (Number.isFinite(nr) ? nr * br : NaN);
    const nbbr = Number.isFinite(nb) && hasBr ? nb * br : Number.isFinite(num(pn.nbbr)) ? num(pn.nbbr) : (Number.isFinite(nb) ? nb : 1) * br;
    return { nrbr, nbbr };
  }

  function createBuilder() {
    const nuclides = new Map();      // z*1000+a -> nuclide record
    const decays = [];               // decay data sets, resolved in finish()
    let datasetCount = 0;
    let newest = '';
    let files = 0;

    function nuclide(z, a) {
      const id = z * 1000 + a;
      let n = nuclides.get(id);
      if (!n) {
        n = { z, a, adopted: null, datasets: [] };
        nuclides.set(id, n);
      }
      return n;
    }

    /**
     * Read one data set: an array of 80-column lines, identification first.
     */
    function addDataset(lines) {
      const id = lines[0];
      const nucidText = id.slice(0, 5);
      let dsid = id.slice(9, 39).trim();
      const dsref = id.slice(39, 65).trim();
      const pub = id.slice(65, 74).trim();
      const date = id.slice(74, 80).trim();
      let start = 1;
      /* A DSID too long for its field ends in a comma and goes on in the
         same columns of a second identification record. */
      if (dsid.endsWith(',') && lines.length > 1) {
        const l2 = lines[1];
        if (l2.slice(0, 5) === nucidText && l2.charAt(5) !== ' ' && l2.slice(6, 9) === '   ') {
          dsid += ' ' + l2.slice(9, 39).trim();
          start = 2;
        }
      }
      const firstDsid = id.slice(9, 39).trim();
      const kind = datasetKind(dsid);
      const nucid = parseNucid(nucidText);
      if (!nucid) return;                          // a mass-chain COMMENTS or REFERENCES set
      datasetCount++;
      if (/^\d{6}$/.test(date) && date > newest) newest = date;
      const nuc = nuclide(nucid.z, nucid.a);
      nuc.datasets.push([kind, dsid, dsref, pub, date]);
      if (kind === 'adopted') readAdopted(nuc, lines, start, { dsid, pub, date });
      else if (kind === 'decay') readDecay(nuc, lines, start, dsid, firstDsid);
    }

    function readAdopted(nuc, lines, start, head) {
      const ad = { ...head, hist: [], q: null, levels: [], ungrouped: [], xsym: new Map() };
      let histText = null;
      let level = null;
      let lastGamma = null;
      let lastType = '';
      const flushHist = () => { if (histText !== null) ad.hist.push(historyEntry(histText)); histText = null; };
      for (let i = start; i < lines.length; i++) {
        const ln = lines[i];
        const c7 = ln.charAt(6);
        if (c7 !== ' ') continue;                   // comments and documentation
        const c6 = ln.charAt(5);
        const cont = c6 !== ' ' && c6 !== '1';
        const type = ln.charAt(7);
        if (type === 'X' && !cont) {
          /* Cross-reference: the symbol in column 9 stands for the data set named after it. */
          ad.xsym.set(ln.slice(9, 39).trim(), ln.charAt(8));
          continue;
        }
        if (ln.charAt(8) !== ' ') continue;   // particle records do not occur here
        if (type === 'H') {
          const text = ln.slice(9, 80).trim();
          if (!cont) { flushHist(); histText = text; } else if (histText !== null) {
            histText += (histText.endsWith('$') ? '' : ' ') + text;
          }
          continue;
        }
        if (type === 'Q') {
          if (!cont) ad.q = readQ(ln);
          else if (ad.q) {
            for (const f of contFields(ln.slice(9, 80))) {
              const v = f.value.split(/\s+/);
              if (f.name === 'Q-') { ad.q.qb = v[0] || ''; ad.q.dqb = v[1] || ''; }
              if (f.name === 'SN') { ad.q.sn = v[0] || ''; ad.q.dsn = v[1] || ''; }
              if (f.name === 'SP') { ad.q.sp = v[0] || ''; ad.q.dsp = v[1] || ''; }
              if (f.name === 'QA') { ad.q.qa = v[0] || ''; ad.q.dqa = v[1] || ''; }
            }
          }
          continue;
        }
        if (type === 'L') {
          if (!cont) {
            level = readLevel(ln);
            ad.levels.push(level);
            lastType = 'L';
          } else if (level && lastType === 'L') {
            for (const f of contFields(ln.slice(9, 80))) {
              const mode = modeFromField(f);
              if (mode) level.modes.push(mode);
              else if (f.name === 'XREF') level.xref = (level.xref || '') + f.value.replace(/\s+/g, '');
              else if (f.name === 'MOMM1') level.mu = f.op === '=' ? f.value : `${f.op} ${f.value}`;
              else if (f.name === 'MOME2') level.qm = f.op === '=' ? f.value : `${f.op} ${f.value}`;
            }
          }
          continue;
        }
        if (type === 'G') {
          if (!cont) {
            lastGamma = readGamma(ln);
            (level ? level.gam : ad.ungrouped).push(lastGamma);
            lastType = 'G';
          } else if (lastGamma && lastType === 'G') {
            for (const f of contFields(ln.slice(9, 80))) {
              if (f.name === 'FL') lastGamma.fl = f.value;
            }
          }
          continue;
        }
        if (!cont) lastType = type;
      }
      flushHist();
      if (!nuc.adopted) nuc.adopted = ad;
    }

    function readDecay(nuc, lines, start, dsid, firstDsid) {
      const m = /^(\S+)\s+(\S+)\s+DECAY\b\s*(.*)$/.exec(dsid);
      const ds = {
        dsid, firstDsid, mode: m ? m[2] : '', qualifier: m ? m[3] : '', ionized: m ? m[1].includes('[') : false,
        daughter: nuc, parents: [], norm: null, prod: null, levels: [], unplaced: [],
      };
      let level = null;
      let last = null;
      let lastType = '';
      for (let i = start; i < lines.length; i++) {
        const ln = lines[i];
        const c7 = ln.charAt(6);
        const type = ln.charAt(7);
        const c9 = ln.charAt(8);
        if (c7 === 'P' && type === 'N') { ds.prod = readProdNorm(ln); continue; }
        if (c7 !== ' ') continue;
        const c6 = ln.charAt(5);
        const cont = c6 !== ' ' && c6 !== '1';
        if (!cont) {
          if (type === 'P') { ds.parents.push(readParent(ln)); last = null; lastType = 'P'; continue; }
          if (type === 'N') { if (!ds.norm) ds.norm = readNorm(ln); last = null; lastType = 'N'; continue; }
          if (type === 'L') { level = readLevel(ln); ds.levels.push(level); last = level; lastType = 'L'; continue; }
          let rec = null;
          if (type === 'G' && c9 === ' ') rec = readGamma(ln);
          else if (type === 'B' && c9 === ' ') rec = readBeta(ln);
          else if (type === 'E' && c9 === ' ') rec = readEc(ln);
          else if (type === 'A' && c9 === ' ') rec = readAlpha(ln);
          else if ((type === 'D' || type === ' ') && /[A-Z]/.test(c9)) rec = readParticle(ln);
          if (rec) {
            if (type === 'G') (level ? level.gam : ds.unplaced).push(rec);
            else (level ? level.feed : ds.unplaced).push(rec);
            last = rec;
            lastType = type;
          } else { last = null; lastType = type; }
          continue;
        }
        if (!last || type !== lastType) continue;
        for (const f of contFields(ln.slice(9, 80))) {
          if (type === 'G') {
            if (f.name === 'FL') last.fl = f.value;
            else if (f.name === '%IG') {
              const v = f.value.split(/\s+/);
              last.ig = f.op === '=' ? (v[0] || '') : ''; last.dig = v[1] || '';
            }
          } else if ((type === 'B' || type === 'E') && f.name === 'EAV') {
            last.eav = f.value.split(/\s+/)[0] || '';
          }
        }
      }
      decays.push(ds);
    }

    /**
     * Feed the text of one ENSDF file (any number of data sets).
     *
     * @param {string} text
     */
    function addText(text) {
      files++;
      const all = text.split(/\r?\n/);
      let current = [];
      for (let i = 0; i < all.length; i++) {
        let ln = all[i];
        if (!ln.trim()) {
          if (current.length) addDataset(current);
          current = [];
          continue;
        }
        if (ln.length < 80) ln = ln.padEnd(80);
        current.push(ln);
      }
      if (current.length) addDataset(current);
    }

    /* -------------------------------------------------------------------
       finish(): states, decay branches, isomer feeding, radiation
       ------------------------------------------------------------------- */

    /** The ground state and isomers of an adopted data set, as indices into its levels. */
    function statesOf(ad) {
      const idx = [];
      ad.levels.forEach((lv, i) => {
        if (i === 0) { idx.push(i); return; }
        if (lv.q === 'S') return;
        const hl = halfLife(lv.t);
        const dt = (lv.dt || '').toUpperCase();
        const upper = dt === 'LT' || dt === 'LE';
        if (lv.ms) idx.push(i);
        else if (hl.s !== null && !hl.width && hl.s >= ISOMER_MIN_S && !upper) idx.push(i);
      });
      return idx;
    }

    /**
     * Where a decay data set's feeding ends up: the fraction of the branch
     * that comes to rest in each isomer of the daughter, the rest going to its
     * ground state. The walk itself is cascade(), below; this works out which
     * data-set level is which adopted state and what feeds each level.
     *
     * An IT data set has no feeding: its cascade starts at the parent level
     * itself, which is in the data set as one of the levels.
     *
     * @returns {Map<number, number>|null} daughter state index -> fraction
     */
    function feedingOf(ds, dNuc, dStates, parentLevelE) {
      const levels = ds.levels;
      if (!levels.length) return null;
      const E = levels.map((lv) => levelEnergy(lv.e));
      const norm = ds.norm || {};
      const nr = num(norm.nr), nt = num(norm.nt);
      /*
        Which data-set level is which adopted state. The evaluator's XREF on
        the adopted level says whether that level was seen in this data set
        at all, and under what energy if it was written differently there.
        Energy alone is not enough: 212Pb feeds a 238.6 keV level of 212Bi
        that lives for picoseconds, and the 25-minute 212Bi isomer sits at
        "239 30" -- within a keV of it, but seen only in 216At alpha decay.
        Where there is no XREF to go by, a match must also carry the
        metastable flag or a half-life that agrees.
      */
      const adLevels = dNuc.adopted.levels;
      const sym = dNuc.adopted.xsym.get(ds.firstDsid) || dNuc.adopted.xsym.get(ds.dsid) || '';
      const stateAt = new Int32Array(levels.length).fill(-1);
      dStates.forEach((li, k) => {
        if (k === 0) return;
        const lv = adLevels[li];
        let se = levelEnergy(lv.e);
        let checked = false;
        if (sym && lv.xref) {
          const xr = parseXref(lv.xref);
          const seen = xr.all ? !(xr.except && xr.except.has(sym)) : xr.items.has(sym);
          if (!seen) return;
          checked = true;
          const inner = xr.all ? '' : xr.items.get(sym).replace(/\*/g, '');
          const own = inner ? levelEnergy(inner.split(',')[0].replace(/\?$/, '')) : null;
          if (own && Number.isFinite(own.n)) se = own;
        }
        const best = nearestLevel(E, se, -1, false);
        if (best < 0 || Math.abs(E[best].n - se.n) > Math.max(1.0, 0.002 * se.n) || stateAt[best] >= 0) return;
        if (!checked) {
          const dl = levels[best];
          const th = halfLife(dl.t).s, ti = halfLife(lv.t).s;
          const agree = th !== null && ti !== null && th > 0 && ti > 0 && Math.abs(Math.log10(th / ti)) < 0.7;
          if (!dl.ms && !agree) return;
        }
        stateAt[best] = k;
      });
      /* The ground state is the level at zero, or failing that the lowest. */
      let g0 = E.findIndex((e) => e.x === '' && e.n === 0);
      if (g0 < 0) g0 = 0;
      if (stateAt[g0] < 0) stateAt[g0] = 0;
      let startAt = -1;
      if (parentLevelE) {
        startAt = nearestLevel(E, parentLevelE, -1, false);
        if (startAt < 0 || Math.abs(E[startAt].n - parentLevelE.n) > Math.max(1.0, 0.002 * parentLevelE.n)) return null;
      }
      const weightOf = (g) => {
        const ti = num(g.ti);
        if (Number.isFinite(ti) && ti > 0) return ti * (Number.isFinite(nt) ? nt : (Number.isFinite(nr) ? nr : 1));
        const ri = num(g.ri);
        if (!Number.isFinite(ri) || ri <= 0) return 0;
        const cc = num(g.cc);
        return ri * (Number.isFinite(nr) ? nr : 1) * (1 + (Number.isFinite(cc) && cc > 0 ? cc : 0));
      };
      const direct = levels.map((lv) => {
        let t = 0;
        for (const f of lv.feed) {
          let v = NaN;
          if (f.kind === 'B') v = num(f.ib);
          else if (f.kind === 'E') {
            v = num(f.ti);
            if (!Number.isFinite(v)) { const b = num(f.ib), e = num(f.ie); v = (Number.isFinite(b) ? b : 0) + (Number.isFinite(e) ? e : 0); }
          } else if (f.kind === 'A') v = num(f.ia);
          if (Number.isFinite(v) && v > 0) t += v;
        }
        return t;
      });
      return cascade(levels, E, stateAt, startAt, direct, weightOf, dNuc.a);
    }

    /**
     * Where an isomer goes by IT, from the adopted level scheme: its own
     * gamma rays and the cascade below them, down to the first state that
     * holds. Used when there is no IT decay data set -- the 11 s isomer of
     * 126Sb has none, and its 22.7 keV transition ends in the 19-minute
     * isomer, not in the ground state.
     */
    function adoptedItOf(nuc, sIdx, k) {
      const levels = nuc.adopted.levels;
      const E = levels.map((lv) => levelEnergy(lv.e));
      const stateAt = new Int32Array(levels.length).fill(-1);
      sIdx.forEach((li, kk) => { stateAt[li] = kk; });
      const weightOf = (g) => {
        const ti = num(g.ti);
        if (Number.isFinite(ti) && ti > 0) return ti;
        const ri = num(g.ri);
        if (!Number.isFinite(ri) || ri <= 0) return 0;
        const cc = num(g.cc);
        return ri * (1 + (Number.isFinite(cc) && cc > 0 ? cc : 0));
      };
      return cascade(levels, E, stateAt, sIdx[k], null, weightOf, nuc.a);
    }

    /** The adopted state a parent record describes, as an index into the nuclide's states. */
    function matchParentState(pNuc, pStates, parent) {
      const levels = pNuc.adopted.levels;
      const pe = levelEnergy(parent.e);
      let best = -1, bestD = Infinity;
      pStates.forEach((li, k) => {
        const se = levelEnergy(levels[li].e);
        if (se.x !== pe.x) return;
        const d = Math.abs((se.n || 0) - (pe.n || 0));
        if (d < bestD) { bestD = d; best = k; }
      });
      const tol = Math.max(1.0, 0.003 * (pe.n || 0));
      if (best >= 0 && bestD <= tol) return best;
      /* Energy not given the same way: fall back to the half-life text. */
      const t = (parent.t || '').replace(/\s+/g, ' ');
      if (t) {
        const k = pStates.findIndex((li) => (levels[li].t || '').replace(/\s+/g, ' ') === t);
        if (k >= 0) return k;
      }
      return -1;
    }

    /** Families a decay data set's mode can stand for, to match it to a branch. */
    function dsFamily(mode) {
      const sh = modeShift(mode);
      if (!sh) return mode;
      return sh.delayed ? mode : sh.family;
    }

    function finish(release) {
      const list = [...nuclides.values()].sort((p, q) => (p.z - q.z) || (p.a - q.a));
      const stateIdx = new Map();    // nuclide id -> [level indices]
      for (const n of list) if (n.adopted && n.adopted.levels.length) stateIdx.set(n.z * 1000 + n.a, statesOf(n.adopted));

      /* Decay data sets by parent state, and the radiation they carry. */
      const byParent = new Map();    // 'id:k' -> [ds]
      const radiation = new Map();   // id -> [entries]
      for (const ds of decays) {
        if (ds.ionized || ds.parents.length !== 1) continue;
        const p = ds.parents[0];
        const pn = parseNucid(p.nucid);
        if (!pn) continue;
        const pNuc = nuclides.get(pn.z * 1000 + pn.a);
        const pStates = pNuc && stateIdx.get(pn.z * 1000 + pn.a);
        if (!pStates) continue;
        const k = matchParentState(pNuc, pStates, p);
        if (k < 0) continue;
        ds.parentId = pn.z * 1000 + pn.a;
        ds.parentState = k;
        const key = ds.parentId + ':' + k;
        if (!byParent.has(key)) byParent.set(key, []);
        byParent.get(key).push(ds);
        const rad = radiationOf(ds, k);
        if (rad) {
          if (!radiation.has(ds.parentId)) radiation.set(ds.parentId, []);
          radiation.get(ds.parentId).push(rad);
        }
      }

      const summary = [];
      const details = new Map();    // A -> {a, nuc: {z: detail}}
      let stateCount = 0;
      for (const n of list) {
        const id = n.z * 1000 + n.a;
        const ad = n.adopted;
        const entry = { z: n.z, a: n.a };
        const det = { ds: n.datasets.map(compact) };
        if (!details.has(n.a)) details.set(n.a, { a: n.a, nuc: {} });
        details.get(n.a).nuc[n.z] = det;
        if (radiation.has(id)) det.rad = radiation.get(id);
        if (!ad) { entry.x = 1; entry.s = []; entry.nd = n.datasets.length; summary.push(entry); continue; }
        /* ADOPTED LEVELS:TENTATIVE, :INFERRED, :UNOBSERVED, : NOT OBSERVED -- how sure the
           evaluators are that the nuclide has been seen at all. */
        const qual = /:\s*(.+)$/.exec(ad.dsid);
        if (qual) entry.aq = qual[1].trim().toUpperCase();
        const sIdx = stateIdx.get(id) || [];
        entry.s = sIdx.map((li, k) => stateEntry(n, ad, li, k, byParent.get(id + ':' + k) || []));
        stateCount += entry.s.length;
        if (ad.q) entry.q = [ad.q.qb, ad.q.dqb, ad.q.sn, ad.q.dsn, ad.q.sp, ad.q.dsp, ad.q.qa, ad.q.dqa, ad.q.qref];
        const h = ad.hist[0] || {};
        const ful = ad.hist.find((x) => x.TYP === 'FUL') || h;
        entry.ev = [ad.pub, ad.date, h.TYP || '', ful.AUT || h.AUT || '', ful.CIT || h.CIT || '', ful.CUT || h.CUT || ''];
        entry.nl = ad.levels.length;
        entry.ng = ad.levels.reduce((s, lv) => s + lv.gam.length, 0) + ad.ungrouped.length;
        entry.nd = n.datasets.length;
        if (n.z % 2 === 0 && (n.a - n.z) % 2 === 0) {
          const two = ad.levels.find((lv, i) => i > 0 && /^\(?2\+\)?$/.test(lv.j));
          if (two && Number.isFinite(num(two.e))) entry.e2 = two.e;
        }
        det.lv = ad.levels.map((lv, i) => {
          const row = [lv.e, lv.de, lv.j, lv.t, lv.dt, lv.ms, lv.q];
          const k = sIdx.indexOf(i);
          if (lv.modes.length || k >= 0) row.push(lv.modes.length ? lv.modes : '', k);
          return compact(row);
        });
        det.gm = [];
        ad.levels.forEach((lv, li) => {
          const E = levelEnergy(lv.e);
          for (const g of lv.gam) {
            let lf = -1;
            const target = g.fl ? levelEnergy(g.fl.replace(/\?$/, '')) : { n: E.n - num(g.e), x: E.x };
            if (Number.isFinite(target.n)) {
              let best = -1, bestD = Infinity;
              for (let k = 0; k < li; k++) {
                const le = levelEnergy(ad.levels[k].e);
                if (le.x !== target.x) continue;
                const d = Math.abs(le.n - target.n);
                if (d < bestD) { bestD = d; best = k; }
              }
              const eg = num(g.e) || 0;
              if (best >= 0 && bestD <= 1.0 + 0.001 * eg + (eg * eg) / (2 * 931494 * n.a)) lf = best;
            }
            det.gm.push(compact([li, g.e, g.de, g.ri, g.dri, g.m, g.mr, g.dmr, g.cc, g.ti, lf, g.q]));
          }
        });
        det.hist = ad.hist.map((x) => compact([x.TYP || '', x.AUT || '', x.CIT || '', x.CUT || '', x.DAT || '', x.COM || '']));
        summary.push(entry);
      }

      /*
        Decay modes the file does not give. An excited state with none decays
        by gamma emission, which is how ENSDF means it (IT). A radioactive
        ground state with none -- 127Te, 128La in this release, where the
        percentage sits only in a comment -- or with modes that add up to
        much less than 100 % (251Fm gives only its 1.8 % alpha) is given the
        beta or electron-capture branch its Q-values allow, when only one of
        the two is open. Either way the branch is marked as inferred, and the
        page says so wherever it shows one.
      */
      const entryById = new Map(summary.map((e) => [e.z * 1000 + e.a, e]));
      const qbOf = (z, a) => {
        const e = entryById.get(z * 1000 + a);
        return e && e.q ? num(e.q[0]) : NaN;
      };
      function inferred(entry, st, k, branches) {
        if (st.st) return [];
        if (k > 0) return branches.length ? [] : [{ mode: 'IT', pct: 100, op: '~', shift: modeShift('IT'), inferred: true }];
        if (st.ts === undefined || st.w) return [];
        if (branches.some((b) => b.pct === null)) return [];
        const sum = branches.reduce((t, b) => t + b.pct, 0);
        if (branches.length && sum >= 95) return [];
        const qb = qbOf(entry.z, entry.a);
        const qec = -qbOf(entry.z - 1, entry.a);
        const has = (fam) => branches.some((b) => b.shift.family === fam && !b.shift.delayed);
        let mode = null;
        if (qb > 0 && !(qec > 0) && !has('B-')) mode = 'B-';
        else if (qec > 0 && !(qb > 0) && !has('EC')) mode = 'EC+B+';
        if (!mode) return [];
        return [{ mode, pct: +(branches.length ? 100 - sum : 100).toPrecision(6), op: '~', shift: modeShift(mode), inferred: true }];
      }

      /* Branches: which daughter, and which of its states. */
      for (const entry of summary) {
        entry.s.forEach((st, k) => {
          const all = st._branches.concat(inferred(entry, st, k, st._branches));
          st.br = all.map((b) => {
            const sh = b.shift;
            const row = [b.mode, b.pct, []];
            if (b.inferred) row[3] = 1;
            /* A percentage given as a limit (< 20, >= 99, ~ 5) keeps its sign. */
            const op = { LT: '<', GT: '>', LE: '<=', GE: '>=', AP: '~', '~': '' }[b.op] ?? (b.op === '=' ? '' : b.op || '');
            if (op) { row[3] = row[3] || 0; row[4] = op; }
            if (sh.fission) return row;
            const dz = entry.z + sh.dz;
            const da = entry.a + sh.dz + sh.dn;
            if (b.mode === 'IT') {
              row[2] = itTargets(entry, st);
              return row;
            }
            const dId = dz * 1000 + da;
            if (dz < 0 || da < 1 || !stateIdx.has(dId)) { row[2] = [[dz, da, -1, 1]]; return row; }
            const fed = st._feeding.get(dsFamily(b.mode));
            if (fed) {
              for (const [k, f] of fed.map) if (f > 1e-9) row[2].push([dz, da, k, round(f)]);
              row[2].sort((p, q) => q[3] - p[3]);
            }
            if (!row[2].length) row[2] = [[dz, da, 0, 1]];
            return row;
          });
          delete st._branches;
          delete st._feeding;
        });
      }

      function itTargets(entry, st) {
        const k = entry.s.indexOf(st);
        const out = [];
        const fed = st._feeding.get('IT');
        let map = fed ? fed.map : null;
        if (!map || ![...map.keys()].some((kk) => kk > 0)) {
          const n = nuclides.get(entry.z * 1000 + entry.a);
          const own = adoptedItOf(n, stateIdx.get(entry.z * 1000 + entry.a), k);
          if (own) map = own;
        }
        if (map) for (const [kk, f] of map) if (kk < k && f > 1e-9) out.push([entry.z, entry.a, kk, round(f)]);
        out.sort((p, q) => q[3] - p[3]);
        return out.length ? out : [[entry.z, entry.a, 0, 1]];
      }

      const out = {
        format: 'kvot-ensdf/1',
        release: Object.assign({
          files, datasets: datasetCount,
          nuclides: summary.filter((e) => !e.x && !/OBSERVED/.test(e.aq || '')).length,
          unobserved: summary.filter((e) => /OBSERVED/.test(e.aq || '')).length,
          states: stateCount, newest,
        }, release || {}),
        nuclides: summary,
      };
      return { summary: out, details };

      function stateEntry(n, ad, li, k, dsList) {
        const lv = ad.levels[li];
        const hl = halfLife(lv.t);
        const st = { e: lv.e, j: lv.j, t: lv.t };
        const en = levelEnergy(lv.e);
        st.en = Number.isFinite(en.n) ? en.n : 0;
        if (en.x) st.ex = en.x;
        if (lv.de) st.de = lv.de;
        if (lv.dt) st.dt = lv.dt;
        if (hl.stable) st.st = 1;
        else if (hl.s !== null) st.ts = +hl.s.toPrecision(6);
        if (hl.width) st.w = 1;
        if (lv.ms) st.ms = lv.ms;
        if (lv.q) st.q = lv.q;
        if (lv.modes.length) st.dm = lv.modes;
        if (lv.mu) st.mu = lv.mu;
        if (lv.qm) st.qm = lv.qm;
        st._branches = branchesOf(lv.modes);
        st._feeding = new Map();
        const dStatesFor = (dz, da) => stateIdx.get(dz * 1000 + da);
        for (const ds of dsList) {
          const fam = dsFamily(ds.mode);
          if (st._feeding.has(fam)) continue;
          const dNuc = ds.daughter;
          const dStates = dStatesFor(dNuc.z, dNuc.a);
          if (!dStates || !dNuc.adopted) continue;
          const sh = modeShift(ds.mode);
          if (!sh || sh.fission) continue;
          if (dNuc.z !== n.z + sh.dz || dNuc.a !== n.a + sh.dz + sh.dn) continue;
          const map = feedingOf(ds, dNuc, dStates, fam === 'IT' ? levelEnergy(lv.e) : null);
          if (map) st._feeding.set(fam, { map, dsid: ds.dsid });
        }
        if (!hl.stable) {
          const em = emissionOf(n, ad, st, k, lv, dsList);
          if (em) {
            st.emit = em.v;
            if (em.flags) st.emitx = em.flags;
          }
        }
        return st;
      }

      /*
        What a state gives off per decay, in MeV, as [alpha, electrons,
        photons] -- sorted the way ICRP 107 sorts it: alpha particles with the
        recoil of the nucleus they leave; beta particles, positrons,
        conversion and Auger electrons; gamma rays, X-rays and annihilation
        radiation. Neutrinos and fission fragments are not counted.

        Worked out from the decay data sets, one for each way the state
        decays. A branch gives its particles' own energies -- the alpha
        energies, the mean beta and positron energies -- and the energy of the
        levels it feeds, less whatever is left in a daughter isomer: that is
        given off when the isomer itself decays, and counted there. The
        gamma rays the data set lists take their share of that de-excitation
        energy; conversion electrons take the rest, with the X-rays and Auger
        electrons that follow them. After electron capture the atom gives off
        the binding energy of the captured electron as X-rays and Auger
        electrons, which ENSDF does not list; that is estimated from the K-
        shell binding energy and the fluorescence yield. A branch with no
        decay data set is estimated from its Q-value where it can be (alpha:
        all of Q; beta: a third of it) and flagged.

        @returns {{v: number[], flags: number}|null} flags: EMIT_MISSING where
          a branch other than fission has neither data set nor Q-value,
          EMIT_SCALED where gamma intensities were only relative and are set by
          the energy they must carry, EMIT_Q where a branch is estimated from Q.
      */
      function emissionOf(n, ad, st, k, lv, dsList) {
        const tot = [0, 0, 0];
        let flags = 0;
        let covered = 0;
        const done = new Set();
        for (const ds of dsList) {
          const fam = dsFamily(ds.mode);
          if (done.has(fam) || !['A', 'B-', 'EC', 'IT'].includes(fam)) continue;
          const e = datasetEmission(n, st, fam, ds, lv);
          if (!e) continue;
          done.add(fam);
          for (let i = 0; i < 3; i++) tot[i] += e.v[i];
          flags |= e.flags;
          covered += e.br;
        }
        /* Branches no data set covers. */
        for (const b of st._branches) {
          if (b.pct === null || b.shift.fission || b.shift.delayed) continue;
          const fam = b.shift.family;
          if (done.has(fam)) continue;
          const f = b.pct / 100;
          if (fam === 'IT' && k > 0) {
            const it = adoptedItEmission(n, k, lv);
            if (it) { for (let i = 0; i < 3; i++) tot[i] += f * it[i]; covered += f; continue; }
          }
          const q = ad.q ? num(fam === 'A' ? ad.q.qa : fam === 'B-' ? ad.q.qb : '') : NaN;
          if (Number.isFinite(q) && q > 0) {
            if (fam === 'A') tot[0] += f * (q + st.en);
            else tot[1] += f * (q + st.en) / 3;
            flags |= EMIT_Q;
            covered += f;
          } else if (f > 0.001) flags |= EMIT_MISSING;
        }
        /* An isomer with no modes at all de-excites by IT. */
        if (k > 0 && !st._branches.length && !dsList.length) {
          const it = adoptedItEmission(n, k, lv);
          if (it) { for (let i = 0; i < 3; i++) tot[i] += it[i]; covered = 1; }
        }
        if (!covered) return null;
        return { v: tot.map((x) => +(x / 1000).toPrecision(5)), flags };
      }

      /* One decay data set's share, in keV per decay of the parent. */
      function datasetEmission(n, st, fam, ds, lv) {
        const norm = ds.norm || {};
        const pn = ds.prod || {};
        let br = num(norm.br);
        if (!Number.isFinite(br)) {
          const b = st._branches.find((x) => x.shift.family === fam && !x.shift.delayed && x.pct !== null);
          br = b ? b.pct / 100 : (st._branches.length === 1 && st._branches[0].pct === null ? 1 : NaN);
        }
        if (!Number.isFinite(br) || br <= 0) return null;
        const { nrbr, nbbr } = normProducts(norm, pn, br);
        const d = ds.daughter;
        const dLevels = d.adopted ? d.adopted.levels : [];
        const dStates = stateIdx.get(d.z * 1000 + d.a) || [];
        /* Where the branch comes to rest, and the energy it leaves there. */
        const fed = st._feeding.get(fam);
        const kept = [];
        let retained = 0;
        if (fed) {
          for (const [kk, f] of fed.map) {
            if (kk <= 0 || dStates[kk] === undefined) continue;
            const e = levelEnergy(dLevels[dStates[kk]].e);
            if (!Number.isFinite(e.n)) continue;
            retained += f * e.n;
            kept.push(e.n);
          }
        }
        const isKept = (e) => Number.isFinite(e) && kept.some((x) => Math.abs(x - e) <= Math.max(1, 0.002 * x));
        let flags = 0;
        let alpha = 0, electron = 0, photon = 0;
        let feedE = 0, feedI = 0;
        const qp = num((ds.parents[0] || {}).qp);
        const zd = d.z;
        const bk = kShellKeV(zd);
        const E = ds.levels.map((l) => levelEnergy(l.e));
        ds.levels.forEach((l, i) => {
          const el = Number.isFinite(E[i].n) ? E[i].n : 0;
          for (const f of l.feed) {
            if (f.kind === 'A') {
              const ia = num(f.ia), ea = num(f.e);
              if (!(ia > 0) || !Number.isFinite(ea)) continue;
              const I = ia * br;
              alpha += I * ea * (1 + 4 / Math.max(1, n.a - 4));
              feedE += I * el; feedI += I;
            } else if (f.kind === 'B') {
              const ib = num(f.ib);
              if (!(ib > 0)) continue;
              const I = ib * nbbr;
              let eav = num(f.eav);
              if (!Number.isFinite(eav)) { const e0 = num(f.e); eav = Number.isFinite(e0) ? e0 / 3 : 0; }
              electron += I * eav;
              feedE += I * el; feedI += I;
            } else if (f.kind === 'E') {
              const ib = num(f.ib) > 0 ? num(f.ib) * nbbr : 0;
              let ie = num(f.ie) > 0 ? num(f.ie) * nbbr : 0;
              if (!ib && !ie && num(f.ti) > 0) ie = num(f.ti) * nbbr;
              if (!ib && !ie) continue;
              let eav = num(f.eav);
              if (!Number.isFinite(eav)) { const e0 = num(f.e); eav = Number.isFinite(e0) ? 0.4 * e0 : 0; }
              electron += ib * eav;
              photon += ib * 2 * 510.99895;
              const [atom, xray] = captureAtom(Number.isFinite(qp) ? qp + st.en - el : NaN, zd);
              photon += ie * xray;
              electron += ie * (atom - xray);
              feedE += (ib + ie) * el; feedI += ib + ie;
            }
          }
        });
        /* The de-excitation energy of the branch. */
        let deexc;
        if (fam === 'IT') deexc = 100 * br * Math.max(0, st.en - retained);
        else if (feedI > 0) deexc = Math.max(0, feedE - feedI * retained);
        else deexc = NaN;
        if (feedI === 0 && fam !== 'IT') {
          /* No feeding records: take the whole Q to the ground state. */
          if (fam === 'A' && Number.isFinite(qp)) { alpha = 100 * br * (qp + st.en); flags |= EMIT_Q; }
          else if (fam === 'B-' && Number.isFinite(qp)) { electron = 100 * br * (qp + st.en) / 3; flags |= EMIT_Q; }
        }
        /* Its gamma rays, what conversion they carry, and the K and L
           vacancies conversion leaves: three quarters of it in the K shell
           where the transition can reach it, in the L shell where not. */
        let g = 0, gc = 0, rel = 0, relc = 0, vac = 0, relvac = 0;
        const xk = fluorescenceK(zd) * 0.88 * bk, xl = fluorescenceL(zd) * 0.8 * l3ShellKeV(zd);
        const gammas = [];
        ds.levels.forEach((l, i) => {
          const from = E[i].n;
          if (isKept(from) && !(fam === 'IT' && Math.abs(from - st.en) <= Math.max(1, 0.002 * st.en))) return;
          for (const x of l.gam) gammas.push([x, from]);
        });
        for (const x of ds.unplaced) if (x.ri !== undefined) gammas.push([x, NaN]);
        /* Relative intensity that ends in the ground state or a daughter isomer. */
        let toRest = 0;
        for (const [x, from] of gammas) {
          const eg = num(x.e);
          if (!Number.isFinite(eg)) continue;
          const cc = num(x.cc) > 0 ? num(x.cc) : 0;
          const ig = num(x.ig);
          const ri = num(x.ri);
          const xr = cc * (eg > bk ? 0.75 * xk + 0.2 * xl : 0.75 * xl);
          if (Number.isFinite(ig) || (Number.isFinite(ri) && Number.isFinite(nrbr))) {
            const I = Number.isFinite(ig) ? ig : ri * nrbr;
            g += I * eg; gc += I * cc * eg; vac += I * xr;
          } else if (Number.isFinite(ri)) {
            rel += ri * eg; relc += ri * cc * eg; relvac += ri * xr;
            const fl = x.fl ? levelEnergy(x.fl.replace(/\?$/, '')).n : from - eg;
            if (Number.isFinite(fl) && (Math.abs(fl) <= 1 + 0.001 * eg || isKept(fl))) toRest += ri * (1 + cc);
          }
        }
        if (!g && rel) {
          /* Relative intensities only: scaled to the energy they must carry,
             where the feedings say what that is, or else on the rule that
             every decay ends in the ground state or an isomer. */
          let sc = 0;
          if (Number.isFinite(deexc) && deexc > 0) sc = deexc / (rel + relc);
          else if (toRest > 0) {
            sc = (100 * br) / toRest;
            deexc = sc * (rel + relc);
            if (fam === 'EC') {
              const mean = deexc / (100 * br);
              const [atom, xray] = captureAtom(Number.isFinite(qp) ? qp + st.en - mean : NaN, zd);
              photon += 100 * br * xray;
              electron += 100 * br * (atom - xray);
            }
          }
          if (sc) {
            g = sc * rel; gc = sc * relc; vac = sc * relvac;
            flags |= EMIT_SCALED;
          }
        }
        if (Number.isFinite(deexc)) {
          const gam = Math.min(g, deexc);
          const xray = Math.min(vac, deexc - gam);
          photon += gam + xray;
          electron += deexc - gam - xray;
        } else {
          photon += g + vac;
          electron += Math.max(0, gc - vac);
        }
        return { v: [alpha / 100, electron / 100, photon / 100], flags, br };
      }

      /* An isomer that de-excites by IT with no data set of its own, from its adopted gamma rays. */
      function adoptedItEmission(n, k, lv) {
        const id = n.z * 1000 + n.a;
        const sIdx = stateIdx.get(id);
        if (!sIdx) return null;
        const map = adoptedItOf(n, sIdx, k);
        let retained = 0;
        if (map) for (const [kk, f] of map) if (kk > 0 && kk < k) { const e = levelEnergy(n.adopted.levels[sIdx[kk]].e); if (Number.isFinite(e.n)) retained += f * e.n; }
        const deexc = Math.max(0, levelEnergy(lv.e).n - retained);
        if (!Number.isFinite(deexc)) return null;
        let r = 0, rc = 0;
        for (const x of lv.gam) {
          const eg = num(x.e), ri = num(x.ri);
          if (!Number.isFinite(eg) || !(ri > 0)) continue;
          const cc = num(x.cc) > 0 ? num(x.cc) : 0;
          r += ri * eg; rc += ri * cc * eg;
        }
        const share = r + rc > 0 ? r / (r + rc) : 1;
        return [0, deexc * (1 - share), deexc * share];
      }
    }

    /**
     * What a decay data set says its parent emits, per 100 decays of the
     * parent where the normalisation allows it, relative otherwise.
     */
    function radiationOf(ds, parentState) {
      const n = ds.norm || {};
      const pn = ds.prod || {};
      const br = Number.isFinite(num(n.br)) ? num(n.br) : 1;
      const { nrbr, nbbr } = normProducts(n, pn, br);
      const np = Number.isFinite(num(pn.np)) ? num(pn.np) : num(n.np);
      const scale = (v, f) => (Number.isFinite(v) && Number.isFinite(f) ? v * f : NaN);
      /* An intensity times its normalisation, with its uncertainty, both as
         strings in the NDS convention. A qualifier (LT, AP ...) stays as it is. */
      const scaled = (value, unc, f) => {
        const v = num(value);
        if (!Number.isFinite(v)) return ['', ''];
        /* Nothing to scale: keep the evaluator's own digits ("0.000 2"). */
        if (!Number.isFinite(f) || Math.abs(f - 1) < 1e-9) return [value.replace(/^\(|\)$/g, ''), unc || ''];
        const u = uncertainty(value, unc);
        if (u && u.abs !== undefined) return ndsPair(v * f, u.abs * f);
        return [fmtNum(v * f), u && u.q ? u.q : ''];
      };
      const g = [], a = [], b = [], e = [], p = [];
      let relative = false;
      const levels = [{ e: '', gam: ds.unplaced.filter((r) => r.ri !== undefined), feed: ds.unplaced.filter((r) => r.ri === undefined) }, ...ds.levels];
      for (const lv of levels) {
        for (const x of lv.gam) {
          /* %IG, where the data set gives it, is already per 100 parent decays. */
          let pair;
          if (Number.isFinite(num(x.ig))) pair = [x.ig, x.dig];
          else if (Number.isFinite(nrbr)) pair = scaled(x.ri, x.dri, nrbr);
          else { pair = [x.ri.replace(/^\(|\)$/g, ''), x.dri]; if (Number.isFinite(num(x.ri))) relative = true; }
          g.push(compact([x.e, x.de, pair[0], pair[1], x.m, lv.e]));
        }
        for (const f of lv.feed) {
          if (f.kind === 'B') b.push(compact([f.e, f.de, f.eav, ...scaled(f.ib, f.dib, nbbr), lv.e, f.logft]));
          else if (f.kind === 'E') e.push(compact([f.e, ...scaled(f.ib, f.dib, nbbr), ...scaled(f.ie, f.die, nbbr), f.eav, lv.e, f.logft]));
          else if (f.kind === 'A') a.push(compact([f.e, f.de, ...scaled(f.ia, f.dia, br), lv.e, f.hf]));
          else if (f.kind === 'D') p.push(compact([f.particle, f.e, f.de, ...scaled(f.ip, f.dip, Number.isFinite(np) ? np : 1), lv.e]));
        }
      }
      if (!g.length && !a.length && !b.length && !e.length && !p.length) return null;
      const par = ds.parents[0];
      const out = { s: parentState, dsid: ds.dsid, mode: ds.mode, under: [ds.daughter.z, ds.daughter.a], br: n.br || '', dbr: n.dbr || '', qp: par.qp, dqp: par.dqp };
      if (g.length) out.g = g;
      if (a.length) out.al = a;
      if (b.length) out.b = b;
      if (e.length) out.ec = e;
      if (p.length) out.p = p;
      if (g.length && (relative || !Number.isFinite(nrbr))) out.grel = 1;
      return out;
    }

    return { addText, finish, get datasetCount() { return datasetCount; } };
  }

  function round(f) { return +f.toPrecision(6); }
  /* Rows lose their trailing blank fields; a reader treats a missing one as ''. */
  function compact(row) {
    let n = row.length;
    while (n > 0 && (row[n - 1] === '' || row[n - 1] === undefined || row[n - 1] === null)) n--;
    return n === row.length ? row : row.slice(0, n);
  }
  function fmtNum(x) {
    if (!Number.isFinite(x)) return '';
    if (x === 0) return '0';
    const a = Math.abs(x);
    if (a >= 1e5 || a < 1e-4) return x.toExponential(3).replace(/\.?0+e/, 'e');
    return String(+x.toPrecision(4));
  }
  function fmtOr(x) { return Number.isFinite(x) ? fmtNum(x) : ''; }

  /**
   * A computed value and its absolute uncertainty written the NDS way: the
   * uncertainty in units of the value's last digit, one or two digits of it
   * (two when it would start 1 or 2), and the value rounded to match.
   * 99.9826 with 0.0006 is ["99.9826", "6"]; 0.1188 with 0.028 is ["0.119", "28"].
   */
  function ndsPair(v, u) {
    if (!Number.isFinite(v)) return ['', ''];
    if (!(u > 0) || !Number.isFinite(u)) return [fmtNum(v), ''];
    const e = Math.floor(Math.log10(u));
    const lead = u / Math.pow(10, e);
    const place = lead < 2.5 ? e - 1 : e;
    if (place > 0 || place < -12) return [fmtNum(v), ''];
    let digits = Math.round(u / Math.pow(10, place));
    let dec = -place;
    if (digits >= 100) { digits = Math.round(digits / 10); dec = Math.max(0, dec - 1); }
    /* Small values in exponent form, the uncertainty still on the last digit. */
    if (dec > 5 && v !== 0) {
      const ev = Math.floor(Math.log10(Math.abs(v)));
      const md = dec + ev;
      if (md >= 0) return [`${(v / Math.pow(10, ev)).toFixed(md)}E${ev}`, String(digits)];
    }
    return [v.toFixed(dec), String(digits)];
  }

  /* ---------------------------------------------------------------------
     Reading a .zip without a library. ENSDF releases are zip files of
     stored or deflated entries; the browser's DecompressionStream (and
     Node's zlib, passed in) does the inflating.
     --------------------------------------------------------------------- */

  /**
   * The entries of a zip file.
   *
   * @param {Uint8Array} bytes
   * @returns {Array<{name: string, method: number, offset: number, size: number, csize: number}>}
   */
  function zipEntries(bytes) {
    const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    let eocd = -1;
    for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i--) {
      if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
    }
    if (eocd < 0) throw new Error('not a zip file (no end-of-directory record)');
    const count = dv.getUint16(eocd + 10, true);
    let p = dv.getUint32(eocd + 16, true);
    if (p === 0xffffffff) throw new Error('zip64 archives are not supported');
    const out = [];
    const dec = new TextDecoder('latin1');
    for (let i = 0; i < count; i++) {
      if (dv.getUint32(p, true) !== 0x02014b50) throw new Error('damaged zip directory');
      const method = dv.getUint16(p + 10, true);
      const csize = dv.getUint32(p + 20, true);
      const size = dv.getUint32(p + 24, true);
      const nlen = dv.getUint16(p + 28, true);
      const xlen = dv.getUint16(p + 30, true);
      const clen = dv.getUint16(p + 32, true);
      const local = dv.getUint32(p + 42, true);
      const name = dec.decode(bytes.subarray(p + 46, p + 46 + nlen));
      const lnlen = dv.getUint16(local + 26, true);
      const lxlen = dv.getUint16(local + 28, true);
      out.push({ name, method, offset: local + 30 + lnlen + lxlen, size, csize });
      p += 46 + nlen + xlen + clen;
    }
    return out;
  }

  /** Whether a file name looks like ENSDF text rather than something beside it in an archive. */
  function isEnsdfName(name) {
    const base = name.split('/').pop();
    if (!base || base.startsWith('.') || name.includes('__MACOSX')) return false;
    return /^ensdf\.\d{3}$/i.test(base) || /\.(ens|ensdf|all|dat|txt)$/i.test(base) || /^ensdf/i.test(base);
  }

  return {
    ELEMENTS, parseNucid, num, uncertainty, halfLife, levelEnergy, contFields, modeFromField, parseXref, ndsPair,
    modeShift, branchesOf, createBuilder, zipEntries, isEnsdfName, YEAR_S,
  };
});
