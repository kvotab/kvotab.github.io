/* ==========================================================================
   RDC.HTML: DECAY CHAINS FROM AN ENSDF DATABASE

   Radionuclide Decay Chains draws its chains from records of one shape, the
   shape of the ICRP Publication 107 file it has built in
   (resources/js/rndecaydata.js):

     {name, Z, A, Element, state, Halflife, Halflife_y, Alpha_energy,
      Electron_energy, Photon_energy, DCC_ing, DCC_ext,
      Progenies: [{name, br, mode}]}

   This module makes the same records from an ENSDF database, so that the
   page draws a chain and works out its decay the same way from either.

   The chain is ensdf-core.js's buildChain(), as on the Chart of Nuclides
   (ensdf.html): the decay modes of the adopted data sets, each branch
   landing in the daughter's isomers as the decay data sets' cascades say,
   and the members the half-life setting leaves out passed through -- an
   arrow that jumps over one names it in `via`. A member decays as fast as a
   left-out member below it is made, so a record's energies per decay are
   its own and those of the members it carries in secular equilibrium
   (chainEmission()).

   ENSDF holds no dose coefficients. A state takes the ICRP 72 and FGR 15
   coefficients of the ICRP 107 record of the same nuclide whose half-life
   is closest to its own, within a fifth of a decade, or else, for a ground
   state, of the ground state's record; a state with no such record has
   none, as many of the short-lived members of the ICRP 107 file have none.

   Names are the element list's: U-238, Pa-234m, Hf-178m2, with the isomer
   tags of the Chart of Nuclides (m for a lone isomer, else the evaluators'
   m1, m2 ...). Every text a record carries is made from numbers and fixed
   words, never copied from the file: an opened file is the visitor's own,
   but nothing in it reaches the page's markup.

   One global: KVOT_RDC_ENSDF (module.exports under Node). Needs
   KVOT_ENSDF_CORE (ensdf-core.js).
   ========================================================================== */
(function (root, factory) {
  const core = (typeof module === 'object' && module.exports) ? require('./ensdf-core.js') : root.KVOT_ENSDF_CORE;
  const api = factory(core);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.KVOT_RDC_ENSDF = api;
})(typeof self !== 'undefined' ? self : this, function (C) {
  'use strict';

  /* The page's year. rndecaydata.js gives half-lives in Julian years and
     the page turns days into years with 365.25, so a half-life from ENSDF,
     in seconds, is put into the same years. */
  const YEAR = 365.25 * 86400;

  /* A fifth of a decade: how close an ICRP 107 record's half-life must be
     to a state's for its dose coefficients to be taken as the state's. */
  const SAME_LIFE = 0.2;

  const symbol = (z) => (C.ELEMENTS[z] ? C.ELEMENTS[z][0] : `Z${z}`);
  const decays = (st) => !!st && !st.st && st.ts > 0;

  /* ---------------------------------------------------------------------
     Names
     --------------------------------------------------------------------- */

  /* The isomer tags of a nuclide's states, '' for the ground state. The
     Chart of Nuclides' own (m, m1, m2 ...), and where it names a state by
     its energy instead, or two states the same, the first m<n> not taken. */
  const TAGS = new WeakMap();
  function tagsOf(nuc) {
    let tags = TAGS.get(nuc);
    if (tags) return tags;
    const seen = new Set();
    tags = nuc.s.map((st, k) => {
      if (!k) return '';
      const t = C.isomerLabel(nuc, k);
      if (!/^m\d*$/.test(t) || seen.has(t)) return null;
      seen.add(t);
      return t;
    });
    tags = tags.map((t, k) => {
      if (t !== null) return t;
      let n = k;
      while (seen.has(`m${n}`)) n++;
      seen.add(`m${n}`);
      return `m${n}`;
    });
    TAGS.set(nuc, tags);
    return tags;
  }

  const tagOf = (nuc, k) => (k > 0 ? (nuc && nuc.s && nuc.s[k] ? tagsOf(nuc)[k] : `m${k}`) : '');

  /** U-238, Pa-234m, Hf-178m2; the same for a nuclide not in the database. */
  const nameOf = (z, a, k, nuc) => `${symbol(z)}-${a}${tagOf(nuc, k)}`;

  const nameOfKey = (idx, key) => {
    const [z, a, k] = key.split(',').map(Number);
    return nameOf(z, a, k, idx.get(z, a));
  };

  /* ---------------------------------------------------------------------
     Half-lives, as the ICRP 107 file writes them
     --------------------------------------------------------------------- */

  /* ENSDF's units, as the page writes them: m for minutes, as ICRP 107 does. */
  const UNIT = { Y: 'y', D: 'd', H: 'h', M: 'm', MIN: 'm', S: 's', MS: 'ms', US: 'µs', NS: 'ns', PS: 'ps', FS: 'fs', AS: 'as' };
  const YEAR_SCALE = [[1e9, 'By'], [1e6, 'My'], [1e3, 'ky']];

  /* mantissa x 10^exponent, the exponent raised: the label is markup. */
  function powerText(v, digits, unit) {
    const [m, e] = v.toExponential(Math.max(0, digits - 1)).split('e');
    return `${m}×10<sup>${+e}</sup> ${unit}`;
  }

  /* Significant digits of a number as written: 245.5E3 has four, 0.0050 two. */
  function digitsOf(s) {
    const mant = s.split(/e/i)[0].replace('.', '').replace(/^0+/, '');
    return Math.max(1, mant.length);
  }

  /**
   * A state's half-life in the words of the ICRP 107 file -- 4.468 By,
   * 245.5 ky, 1600 y, 24.10 d, 1.159 m, 163.6 µs -- with the evaluators'
   * digits. A year count past 10^12 and a half-life from a level width are
   * powers of ten, with the exponent in <sup>: the page sets this in a
   * label of markup. 'Stable', or '?' where none is known.
   */
  function halfLifeLabel(st) {
    if (!st) return '?';
    if (st.st) return 'Stable';
    if (!(st.ts > 0)) return '?';
    const p = C.halfLifeParts(st);
    const q = p.q === '<' || p.q === '>' || p.q === '≈' || p.q === '≤' || p.q === '≥' ? p.q : '';
    const doubt = p.doubtful ? ' ?' : '';
    const m = /^[<>~]?\s*([0-9.]+(?:[Ee][+-]?\d+)?)\s*([A-Za-z]+)/.exec(String(st.t || '').trim());
    const unit = m && UNIT[m[2].toUpperCase()];
    if (!m || !unit || st.w || !Number.isFinite(+m[1])) {
      /* A width, or a unit the page has no word for: from the seconds. */
      return q + secondsText(st.ts) + doubt;
    }
    const v = +m[1], digits = digitsOf(m[1]);
    if (unit === 'y' && v >= 1e4) {
      if (v >= 1e12) return q + powerText(v, digits, 'y') + doubt;
      for (const [f, u] of YEAR_SCALE) if (v >= f) return `${q}${+(v / f).toPrecision(digits)} ${u}${doubt}`;
    }
    if (/e/i.test(m[1])) {
      /* 1.2E-4 s and the like: as a power, unless it reads as well without. */
      return (v >= 1e-3 && v < 1e5 ? `${q}${+v.toPrecision(digits)} ${unit}` : q + powerText(v, digits, unit)) + doubt;
    }
    return `${q}${m[1]} ${unit}${doubt}`;
  }

  /* A time in seconds, in the largest unit it is at least one of. */
  function secondsText(s) {
    const units = [[YEAR, 'y'], [86400, 'd'], [3600, 'h'], [60, 'm'], [1, 's'], [1e-3, 'ms'], [1e-6, 'µs'], [1e-9, 'ns']];
    for (const [f, u] of units) if (s >= f) return `${+(s / f).toPrecision(3)} ${u}`;
    return powerText(s, 3, 's');
  }

  /* ---------------------------------------------------------------------
     Decay modes, as the ICRP 107 file writes them
     --------------------------------------------------------------------- */
  const MODE = { A: '&alpha;', 'B-': '&beta;-', 'B+': '&beta;+', EC: 'EC', 'EC+B+': '&beta;+ & EC', IT: 'IT', SF: 'SF' };

  /** α, β-, β+ & EC, IT and SF as the ICRP 107 file has them; anything else in ENSDF's notation: β-n, εp, 14C. */
  function modeLabel(mode) {
    const m = String(mode || '').toUpperCase();
    return MODE[m] || C.asciiText(C.modeText(m));
  }

  /* ---------------------------------------------------------------------
     A database
     --------------------------------------------------------------------- */

  /*
    The dose coefficients of the ICRP 107 records, by ENSDF state: 'z,a,k'
    -> {ing, ext, name}. Each record goes to the state of its nuclide whose
    half-life is closest to its own, within SAME_LIFE decades; failing that,
    a ground state's record goes to the ground state. Ta-178 is the case for
    the first rule: ICRP 107's 9.31 min ground state is ENSDF's isomer, and
    its 2.36 h isomer ENSDF's ground state. Where two records want one
    state, the closer has it.
  */
  function coefficients(idx, icrp) {
    const out = new Map();
    for (const d of icrp || []) {
      if (d.Halflife === 'Stable' || !(d.Halflife_y > 0)) continue;
      const nuc = idx.get(d.Z, d.A);
      if (!nuc || !nuc.s || !nuc.s.length) continue;
      const t = d.Halflife_y * YEAR;
      let best = -1, gap = Infinity;
      nuc.s.forEach((st, k) => {
        if (!decays(st)) return;
        const g = Math.abs(Math.log10(st.ts / t));
        if (g < gap) { gap = g; best = k; }
      });
      if (gap > SAME_LIFE) {
        if (d.state || !decays(nuc.s[0])) continue;
        best = 0;
        gap = Math.abs(Math.log10(nuc.s[0].ts / t));
      }
      const key = `${d.Z},${d.A},${best}`;
      const had = out.get(key);
      if (had && had.gap <= gap) continue;
      out.set(key, { ing: +d.DCC_ing || 0, ext: +d.DCC_ext || 0, name: d.name, gap });
    }
    return out;
  }

  /**
   * An ENSDF database for the page: the index, the states the element list
   * offers, and the dose coefficients each takes from ICRP 107.
   *
   * @param {Object} summary - an ENSDF summary, as ensdf-sources.js hands it over
   * @param {Array} icrp - the ICRP 107 records (rndecaydata.js's decaydata)
   * @returns {{idx: Object, states: Map, byZ: Map, release: Object, dcc: Map, label: string}}
   *   states: name -> {z, a, k} of every radioactive state with a known
   *   half-life; byZ: Z -> those names, by mass number
   */
  function database(summary, icrp) {
    const idx = C.index(summary);
    const states = new Map();
    const byZ = new Map();
    for (const nuc of idx.shown) {
      if (!(nuc.z > 0) || !nuc.s) continue;
      nuc.s.forEach((st, k) => {
        if (!decays(st)) return;
        const name = nameOf(nuc.z, nuc.a, k, nuc);
        if (states.has(name)) return;
        states.set(name, { z: nuc.z, a: nuc.a, k });
        if (!byZ.has(nuc.z)) byZ.set(nuc.z, []);
        byZ.get(nuc.z).push(name);
      });
    }
    const release = summary.release || {};
    return { idx, states, byZ, release, dcc: coefficients(idx, icrp), label: String(release.label || 'ENSDF') };
  }

  /**
   * The element list for a database: the page's elements (rndatatree.js's
   * datatree) with the database's radioactive states under each.
   */
  function elementTree(db, elements) {
    return elements.map((el) => ({
      text: el.text, type: el.type, a_attr: el.a_attr,
      children: (db.byZ.get(+(el.a_attr && el.a_attr.Z)) || []).map((name) => ({ text: name, type: 'radioisotope' })),
    }));
  }

  /* ---------------------------------------------------------------------
     A chain
     --------------------------------------------------------------------- */

  /* The settings of a chain: the smallest branch, a percentage, and the
     half-life setting by its id, as ensdf-core.js lists them. */
  function settings(opt = {}) {
    const life = C.LIFE_OPTIONS.find((o) => o.id === opt.life) || C.LIFE_OPTIONS.find((o) => o.id === C.DEFAULT_LIFE);
    const branch = C.BRANCH_OPTIONS.find((o) => +o.value === +opt.minBranch) || C.BRANCH_OPTIONS[0];
    return { life, branch, minBranch: +branch.value };
  }

  /*
    A member's arrows, one for each daughter: branches of different modes to
    the same daughter make one arrow with both modes (they cannot be told
    apart in the drawing), and each fission branch its own, to fission. A
    share is known, a limit (limit '<='), at least what is known (more), or
    not known at all (known false, br 0); inferred is a branch ENSDF does
    not give, which the Chart of Nuclides infers from the Q-values; via the
    left-out members an arrow jumps over, by name.
  */
  function progenies(idx, nd) {
    const out = [];
    const byName = new Map();
    for (const e of nd.out) {
      const fission = e.to.kind === 'fission';
      const p = {
        name: fission ? 'SF' : nameOf(e.to.z, e.to.a, e.to.k, e.to.nuc),
        br: e.pct === null ? 0 : e.pct / 100,
        mode: modeLabel(e.mode),
        known: e.pct !== null, more: !!e.more, limit: e.limit || '', inferred: !!e.inferred,
        via: (e.via || []).map((v) => nameOfKey(idx, v.key)),
      };
      if (fission) { out.push(p); continue; }
      const same = byName.get(p.name);
      if (!same) { byName.set(p.name, p); out.push(p); continue; }
      if (!same.mode.split(' & ').includes(p.mode)) same.mode += ` & ${p.mode}`;
      same.more = same.more || p.more || (same.known !== p.known);
      same.known = same.known || p.known;
      same.br += p.br;
      same.limit = same.limit || p.limit;
      same.inferred = same.inferred || p.inferred;
      for (const v of p.via) if (!same.via.includes(v)) same.via.push(v);
    }
    return out;
  }

  function record(db, nd) {
    const st = nd.st;
    const r = {
      name: nameOf(nd.z, nd.a, nd.k, nd.nuc), Z: nd.z, A: nd.a, Element: symbol(nd.z),
      state: tagOf(nd.nuc, nd.k),
      k: nd.k, key: nd.key, missing: nd.kind === 'missing',
      Halflife: nd.kind === 'missing' ? '?' : halfLifeLabel(st),
      Halflife_y: decays(st) ? st.ts / YEAR : NaN,
      Alpha_energy: 0, Electron_energy: 0, Photon_energy: 0, DCC_ing: 0, DCC_ext: 0,
      energyKnown: true, energyEstimated: false, Progenies: [],
    };
    if (nd.kind !== 'state' || !st || st.st) return r;
    const em = C.chainEmission(db.idx, nd);
    r.Alpha_energy = em.v[0];
    r.Electron_energy = em.v[1];
    r.Photon_energy = em.v[2];
    r.energyKnown = em.known;
    r.energyEstimated = em.estimated;
    const d = db.dcc.get(nd.key);
    if (d) { r.DCC_ing = d.ing; r.DCC_ext = d.ext; r.icrp = d.name; }
    r.Progenies = progenies(db.idx, nd);
    return r;
  }

  /* ---------------------------------------------------------------------
     Where each circle goes
     --------------------------------------------------------------------- */

  /*
    The page draws ICRP 107's chains on the chart of nuclides turned 45
    degrees: Z - N across, alpha decay straight down, beta-minus a step to
    the right, each mass number a row 35 px below the one before. Its chains
    hold alpha and beta steps, four mass numbers apart down a series. An
    ENSDF chain holds the beta-delayed neutrons too, and members one or two
    mass numbers apart then fall on one another. So an ENSDF chain is laid
    out as the Chart of Nuclides lays out its series (ensdf-chain.js): the
    same steps across and down, but one row for each mass number that holds
    a member, heaviest at the top, and the states of one nuclide one above
    the other, isomers on top. Two circles of a row differ in Z - N by two at
    least, a full step, so none touch. Fission ends in a point a step off the
    state that splits, up and to the right as on the rest of the page, or at
    the first other corner where the point and the way to it are clear.
  */
  const SERIES = { d: 80, unit: 50 * Math.SQRT2, rowGap: 100 * Math.SQRT2 - 80, vGap: 50, reach: 100 };

  function segDist(ax, ay, bx, by, px, py) {
    const dx = bx - ax, dy = by - ay;
    const t = dx || dy ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy))) : 0;
    return Math.hypot(ax + t * dx - px, ay + t * dy - py);
  }

  /** Sets each record's pos {x, y}, the centre of its circle, and fission: the points its fission arrows end in, in order. */
  function layOut(records) {
    const g = SERIES, D = g.d;
    const list = [...records.values()];
    if (!list.length) return;
    const cMin = Math.min(...list.map((r) => 2 * r.Z - r.A));
    const rowsA = [...new Set(list.map((r) => r.A))].sort((p, q) => q - p);
    const cells = new Map();
    for (const r of list) {
      const k = `${r.Z},${r.A}`;
      if (!cells.has(k)) cells.set(k, []);
      cells.get(k).push(r);
    }
    for (const c of cells.values()) c.sort((p, q) => q.k - p.k);
    const rows = new Map();
    let y = 0;
    for (const a of rowsA) {
      let stack = 1;
      for (const c of cells.values()) if (c[0].A === a) stack = Math.max(stack, c.length);
      const h = stack * D + (stack - 1) * g.vGap;
      rows.set(a, { y, h });
      y += h + g.rowGap;
    }
    for (const c of cells.values()) {
      const row = rows.get(c[0].A);
      const h = c.length * D + (c.length - 1) * g.vGap;
      const top = row.y + (row.h - h) / 2;
      const x = (2 * c[0].Z - c[0].A - cMin) * g.unit + D / 2;
      c.forEach((r, i) => { r.pos = { x, y: top + i * (D + g.vGap) + D / 2 }; });
    }
    const centres = list.map((r) => r.pos);
    const points = [];
    for (const r of list) {
      r.fission = [];
      for (const p of r.Progenies) {
        if (p.name !== 'SF') continue;
        const { x: cx, y: cy } = r.pos;
        let best = null;
        for (const [sx, sy] of [[1, -1], [-1, -1], [1, 1], [-1, 1]]) {
          const px = cx + sx * g.reach, py = cy + sy * g.reach;
          let bad = 0;
          for (const c of centres) {
            if (c === r.pos) continue;
            if (Math.hypot(px - c.x, py - c.y) < D / 2 + 18) bad += 10;
            else if (segDist(cx, cy, px, py, c.x, c.y) < D / 2 + 6) bad++;
          }
          for (const [qx, qy] of points) if (Math.hypot(px - qx, py - qy) < 30) bad += 10;
          if (!best || bad < best.bad) best = { x: px, y: py, bad };
          if (!bad) break;
        }
        points.push([best.x, best.y]);
        r.fission.push({ x: best.x, y: best.y });
      }
    }
  }

  /**
   * The chain below a state, as records for the page.
   *
   * @param {Object} db - database()
   * @param {string} name - the state the chain starts from, as the element list names it
   * @param {{minBranch?: number|string, life?: string}} [opt] - the chain settings
   * @returns {{root: Object, records: Map, chain: Object, truncated: boolean, settings: Object}|null}
   *   records: name -> record of every member but fission, with pos, the
   *   centre of its circle, and fission, where its fission arrows end
   *   (layOut())
   */
  function chain(db, name, opt) {
    const at = db.states.get(name);
    if (!at) return null;
    const set = settings(opt);
    const ch = C.buildChain(db.idx, at.z, at.a, at.k, { minBranch: set.minBranch, minHalfLifeS: set.life.life, minIsomerS: set.life.iso });
    const records = new Map();
    for (const nd of ch.nodes) {
      if (nd.kind === 'fission') continue;
      const r = record(db, nd);
      if (!records.has(r.name)) records.set(r.name, r);
    }
    layOut(records);
    return { root: records.get(nameOf(ch.root.z, ch.root.a, ch.root.k, ch.root.nuc)), records, chain: ch, truncated: ch.truncated, settings: set };
  }

  return { YEAR, SERIES, nameOf, tagsOf, halfLifeLabel, modeLabel, coefficients, database, elementTree, settings, chain };
});
