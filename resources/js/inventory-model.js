/* ==========================================================================
   CANISTER_INVENTORY.HTML: THE INVENTORY, AT ANY TIME, IN ANY UNIT

   An inventory as read (inventory-json.js) gives amounts in moles for each
   fuel element, part (fuel, crud, structural material, ...) and nuclide, at
   the time each canister was packed. This module turns that into what the
   page shows: sums per canister, averages and totals over the canisters
   chosen, in moles, becquerels or grams, as packed or in a given year, and
   the decay heat they give.

   Decay is ICRP Publication 107's (resources/js/rndecaydata.js, the data
   rdc.html is built on): its half-lives, its branches, the energy each decay
   gives off. The chains run through every descendant, so Am-241 grows from
   Pu-241, Np-237 from Am-241 and U-233 from Np-237, whatever the file lists.
   The system is solved with ensdf-core.js's decayAt(): CRAM of order 16, as
   burnup codes do, which handles members from minutes to billions of years
   at any time with no step to take. A half-life may be replaced by another
   assessment's own (PSAR's Table D-1), so that its numbers can be met on
   their own terms, and the whole of the decay data by an ENSDF release's
   (inventory-ensdf.js makes records of the same shape).

   A file lists the nuclides that matter for safety after closure, not the
   short-lived members in equilibrium with them: Ba-137m under Cs-137, Y-90
   under Sr-90, the radon daughters under Ra-226. Those that live less than a
   year are put in secular equilibrium with what feeds them before anything
   decays, so that the decay heat counts them from the start. They are never
   shown as amounts, and sums of activity are of the file's own nuclides, as
   an assessment's tables are.

   Amounts are worked in moles throughout; a unit is applied only to show.
   The year is ICRP 107's, 365.242196 days, and a year Y means 1 January Y.

   One global: KVOT_INV_MODEL (module.exports under Node). Needs
   KVOT_ENSDF_CORE (ensdf-core.js) for the decay, and the records of
   rndecaydata.js handed to nuclearData().
   ========================================================================== */
(function (root, factory) {
  const node = typeof module === 'object' && module.exports;
  const api = factory(node ? require('./ensdf-core.js') : root.KVOT_ENSDF_CORE,
    node ? require('./inventory-json.js') : root.KVOT_INV_JSON);
  if (node) module.exports = api;
  else root.KVOT_INV_MODEL = api;
})(typeof self !== 'undefined' ? self : this, function (CORE, JSONR) {
  'use strict';

  const YEAR_S = 365.242196 * 86400;
  const NA = 6.02214076e23;
  const MEV_J = 1.602176634e-13;
  const SHORT_Y = 1;            // members living less than this are held in equilibrium
  const LN2 = Math.LN2;

  /* ---------------------------------------------------------------------
     Nuclear data
     --------------------------------------------------------------------- */

  /**
   * ICRP 107's records by name, with what the page needs of each.
   *
   * @param {Array} records - rndecaydata.js's decaydata
   * @returns {Map<string, {name, z, a, T, mass, E, dcc, prog: Array<{name, br}>}>}
   *   T in years (0 for stable), E the MeV a decay gives off (alpha,
   *   electrons and photons; neutrinos carry theirs away)
   */
  function nuclearData(records) {
    const out = new Map();
    for (const r of records || []) {
      if (!r || !r.name) continue;
      out.set(r.name, {
        name: r.name,
        z: r.Z, a: r.A,
        T: Number(r.Halflife_y) > 0 ? Number(r.Halflife_y) : 0,
        mass: Number(r.Mass) > 0 ? Number(r.Mass) : r.A,
        E: (Number(r.Alpha_energy) || 0) + (Number(r.Electron_energy) || 0) + (Number(r.Photon_energy) || 0),
        dcc: Number(r.DCC_ing) || 0,
        prog: (r.Progenies || []).filter((p) => p && p.name && p.name !== 'SF' && p.br > 0).map((p) => ({ name: p.name, br: Number(p.br) })),
      });
    }
    return out;
  }

  /* ---------------------------------------------------------------------
     The decay system
     --------------------------------------------------------------------- */

  /**
   * Every nuclide that can arise from the given ones, parents before
   * daughters, with its decay constant and energy.
   *
   * @param {Map} nd - nuclearData()
   * @param {string[]} names - the nuclides amounts are given for
   * @param {Map<string, number>} [halfLives] - years, replacing ICRP 107's
   */
  function decaySystem(nd, names, halfLives = null) {
    const listed = new Set(names);
    const order = [];
    const state = new Map();
    const visit = (name) => {
      if (state.has(name)) return;
      state.set(name, 1);
      const rec = nd.get(name);
      if (rec && rec.T > 0) for (const p of rec.prog) visit(p.name);
      state.set(name, 2);
      order.push(name);
    };
    for (const n of names) visit(n);
    order.reverse();
    /* Stable members collect what reaches them and give nothing; they are
       left out, unless the file lists one. */
    const members = order.filter((n) => listed.has(n) || ((nd.get(n) || {}).T > 0));
    const index = new Map(members.map((n, i) => [n, i]));
    const m = members.length;
    const lambda = new Float64Array(m);
    const T = new Float64Array(m);
    const E = new Float64Array(m);
    const mass = new Float64Array(m);
    const known = new Uint8Array(m);
    const hidden = new Uint8Array(m);
    members.forEach((n, i) => {
      const rec = nd.get(n);
      const t = halfLives && halfLives.has(n) ? halfLives.get(n) : rec ? rec.T : 0;
      T[i] = t;
      lambda[i] = t > 0 ? LN2 / (t * YEAR_S) : 0;
      E[i] = rec ? rec.E : 0;
      mass[i] = rec ? rec.mass : (JSONR.nuclideOf(n) || { a: 0 }).a;
      known[i] = rec || (halfLives && halfLives.has(n)) ? 1 : 0;
      hidden[i] = listed.has(n) ? 0 : 1;
    });
    const rows = members.map(() => []);
    members.forEach((n, j) => {
      const rec = nd.get(n);
      if (!rec || !(lambda[j] > 0)) return;
      for (const p of rec.prog) {
        const i = index.get(p.name);
        if (i !== undefined && i > j) rows[i].push([j, p.br]);
      }
    });
    /* The smallest decay constant among each member and all that feed it
       (parents come before their daughters). */
    const slowest = Float64Array.from(lambda);
    rows.forEach((row, i) => { for (const [j] of row) if (slowest[j] < slowest[i]) slowest[i] = slowest[j]; });
    return { members, index, lambda, T, E, mass, known, hidden, rows, halfLives, slowest };
  }

  /**
   * The amounts of every member, from those of the listed nuclides (by
   * name), with each unlisted member that lives less than SHORT_Y years in
   * secular equilibrium with what feeds it.
   *
   * @param {Object} sys - decaySystem()
   * @param {Float64Array} given - by member index; members not listed are 0
   */
  function withDaughters(sys, given) {
    const n = given.slice();
    const { lambda, rows, hidden, T } = sys;
    for (let i = 0; i < n.length; i++) {
      if (!hidden[i] || !(T[i] > 0 && T[i] < SHORT_Y)) continue;
      let feed = 0;
      for (const [j, f] of rows[i]) feed += f * lambda[j] * n[j];
      n[i] = feed / lambda[i];
    }
    return n;
  }

  const GONE = 36;

  /**
   * Amounts (N, mol) and activities (A, mol/s) of every member at each of
   * `times` (seconds), as decayAt() gives them, except where it cannot tell
   * what is left from its own round-off, about 1e-16 of what a chain began
   * with. A member nothing feeds decays alone, so its amount is worked out
   * exactly: H-3 a thousand years on is 1e-25 of what it was, not the
   * solver's remnant. A member that has run down,
   * with all that feeds it, past e^-GONE is 0.
   */
  function decayTimes(sys, n0, times) {
    const res = CORE.decayAt(sys, n0, times);
    const { lambda, rows, slowest } = sys;
    times.forEach((t, k) => {
      if (!(t > 0)) return;
      const N = res.N[k], A = res.A[k];
      for (let i = 0; i < N.length; i++) {
        const fed = rows[i].length > 0;
        if (fed && slowest[i] * t <= GONE) continue;
        const v = fed ? 0 : n0[i] * Math.exp(-lambda[i] * t);
        N[i] = v > 0 ? v : 0;
        A[i] = lambda[i] * N[i];
      }
    });
    return res;
  }

  /** Amounts (mol, by member) after t seconds. */
  function decay(sys, n0, t) {
    if (!(t > 0)) return n0.slice();
    return decayTimes(sys, n0, [t]).N[0];
  }

  /** Decay heat (W) of amounts by member, in moles. */
  function heatOf(sys, n) {
    let w = 0;
    for (let i = 0; i < n.length; i++) w += n[i] * sys.lambda[i] * sys.E[i];
    return w * NA * MEV_J;
  }

  /**
   * The energy (MeV) each decay of a member gives off together with the
   * short-lived unlisted members below it, held in equilibrium: the heat of
   * a listed nuclide is its activity times this.
   */
  function effectiveEnergy(sys) {
    const m = sys.members.length;
    const out = Float64Array.from(sys.E);
    /* Daughters before parents, so that each daughter's sum is ready. */
    const below = sys.members.map(() => []);
    sys.rows.forEach((row, i) => { for (const [j, f] of row) below[j].push([i, f]); });
    for (let j = m - 1; j >= 0; j--) {
      for (const [i, f] of below[j]) {
        if (sys.hidden[i] && sys.T[i] > 0 && sys.T[i] < SHORT_Y) out[j] += f * out[i];
      }
    }
    return out;
  }

  /* ---------------------------------------------------------------------
     Times
     --------------------------------------------------------------------- */

  const yearMs = (y) => Date.UTC(y, 0, 1);
  /** A date as a decimal year, 2038-07-02 -> 2038.50. */
  function decimalYear(ms) {
    if (!Number.isFinite(ms)) return NaN;
    const y = new Date(ms).getUTCFullYear();
    const a = Date.UTC(y, 0, 1), b = Date.UTC(y + 1, 0, 1);
    return y + (ms - a) / (b - a);
  }

  /* ---------------------------------------------------------------------
     Statistics
     --------------------------------------------------------------------- */

  /** Quantile of sorted values, linear between order statistics (Excel's PERCENTILE.INC). */
  function quantileSorted(sorted, q) {
    const n = sorted.length;
    if (!n) return NaN;
    const h = (n - 1) * q;
    const lo = Math.floor(h), hi = Math.ceil(h);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (h - lo);
  }

  function summary(values) {
    const v = Float64Array.from(values).filter((x) => Number.isFinite(x)).sort();
    if (!v.length) return { n: 0, mean: NaN, min: NaN, p5: NaN, p50: NaN, p95: NaN, max: NaN };
    let s = 0;
    for (const x of v) s += x;
    return { n: v.length, mean: s / v.length, min: v[0], p5: quantileSorted(v, 0.05), p50: quantileSorted(v, 0.5), p95: quantileSorted(v, 0.95), max: v[v.length - 1] };
  }

  /* ---------------------------------------------------------------------
     The inventory
     --------------------------------------------------------------------- */

  const PART_LABELS = {
    fuel: 'Fuel', crud: 'Crud', structural_material: 'Structural material', structural: 'Structural material',
    control_rods: 'Control rods', control_rod: 'Control rods',
  };
  function partLabel(key) {
    if (PART_LABELS[key]) return PART_LABELS[key];
    const s = String(key).replace(/[_]+/g, ' ').trim();
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  /* A field an element's or canister's text is grouped by, found by name. */
  const findField = (text, re) => Object.keys(text).find((k) => re.test(k)) || null;

  /*
    The categories of an assessment's tables. SKB's report on the spent fuel
    to be handled (SKBdoc 1380282) counts BWR and PWR fuel from the twelve
    Swedish reactors, Ågesta's, the "swap MOX" from four German reactors
    (Gundremmingen, Kahl, Obrigheim and the Mehrzweckforschungsreaktor in
    Karlsruhe), and Studsvik's remains apart. An element's reactor name puts
    it in one of the others; the rest go by its reactor type.
  */
  const CATEGORY_RULES = [
    [/ågesta|agesta/i, 'Ågesta'],
    [/kahl|\bvak\b|gundremmingen|krb|obrigheim|\bkwo\b|mehrzweck|mzfr/i, 'Swap MOX'],
    [/studsvik/i, 'Studsvik'],
  ];
  function categoryOf(reactor, type) {
    for (const [re, cat] of CATEGORY_RULES) if (re.test(reactor || '')) return cat;
    return type || 'Other';
  }

  class Inventory {
    /**
     * @param {Object} data - inventory-json.js's readInventory()
     * @param {Map} nd - nuclearData()
     * @param {{name?: string, size?: number}} [file]
     */
    constructor(data, nd, file = {}) {
      this.data = data;
      this.nd = nd;
      this.file = file;
      const can = data.canisters, el = data.elements;
      this.nCan = can.n;
      this.nEl = el.n;
      this.P = data.parts.length;
      this.N = data.nuclides.length;
      this.parts = data.parts.map((key) => ({ key, label: partLabel(key) }));
      this.nuclides = data.nuclides.map((key, k) => {
        const parsed = JSONR.nuclideOf(key);
        const name = parsed ? parsed.name : key;
        return { k, key, name, z: parsed ? parsed.z : 0, a: parsed ? parsed.a : 0, rec: nd.get(name) || null };
      });
      this.unknown = this.nuclides.filter((u) => !u.rec).map((u) => u.name);

      /* The fields to group by: the element's reactor and type, found by name. */
      this.fields = {
        type: findField(el.text, /^(reactor_?type|type)$/i) || findField(el.text, /type/i),
        reactor: findField(el.text, /^reactor$/i) || findField(el.text, /reactor|plant|unit/i),
        fuel: findField(el.text, /^fuel_?type$/i) || findField(el.text, /fuel|design|konstr/i),
      };
      /* A canister's type is that of most of its elements. */
      const typeCol = this.fields.type ? el.text[this.fields.type] : null;
      this.typeNames = typeCol ? typeCol.values.slice() : [];
      this.canType = new Int32Array(this.nCan).fill(-1);
      if (typeCol) {
        const counts = new Int32Array(this.typeNames.length);
        for (let c = 0; c < this.nCan; c++) {
          counts.fill(0);
          for (let e = can.el0[c], end = e + can.nEl[c]; e < end; e++) if (typeCol.codes[e] >= 0) counts[typeCol.codes[e]]++;
          let best = -1;
          for (let t = 0; t < counts.length; t++) if (counts[t] > 0 && (best < 0 || counts[t] > counts[best])) best = t;
          this.canType[c] = best;
        }
      }
      /* Each element's category, as an assessment's tables count them. */
      const reactorCol = this.fields.reactor ? el.text[this.fields.reactor] : null;
      this.categoryNames = [];
      const catIndex = new Map();
      this.elCategory = new Int32Array(this.nEl);
      for (let e = 0; e < this.nEl; e++) {
        const r = reactorCol && reactorCol.codes[e] >= 0 ? reactorCol.values[reactorCol.codes[e]] : '';
        const t = typeCol && typeCol.codes[e] >= 0 ? typeCol.values[typeCol.codes[e]] : '';
        const cat = categoryOf(r, t);
        let i = catIndex.get(cat);
        if (i === undefined) { i = this.categoryNames.length; this.categoryNames.push(cat); catIndex.set(cat, i); }
        this.elCategory[e] = i;
      }

      this.canYear = Float64Array.from(can.date, decimalYear);
      let last = -Infinity, first = Infinity;
      for (const ms of can.date) if (Number.isFinite(ms)) { last = Math.max(last, ms); first = Math.min(first, ms); }
      this.firstPacked = Number.isFinite(first) ? first : NaN;
      this.lastPacked = Number.isFinite(last) ? last : NaN;
      /* The first 1 January every canister has been packed by. */
      this.minYear = Number.isFinite(last) ? new Date(last).getUTCFullYear() + (last > yearMs(new Date(last).getUTCFullYear()) ? 1 : 0) : null;
      this.undated = can.date.reduce((s, ms) => s + (Number.isFinite(ms) ? 0 : 1), 0);
      this.cache = new Map();
    }

    /** Every nuclide name the inventory lists, for decaySystem(). */
    names() { return this.nuclides.map((u) => u.name); }

    /** Sums over each canister's elements: [canister][part][nuclide], moles as packed. */
    packed() {
      if (this.cache.has('packed')) return this.cache.get('packed');
      const { amounts, canisters: can } = this.data;
      const S = this.P * this.N;
      const out = new Float64Array(this.nCan * S);
      for (let c = 0; c < this.nCan; c++) {
        const o = c * S;
        for (let e = can.el0[c], end = e + can.nEl[c]; e < end; e++) {
          const b = e * S;
          for (let i = 0; i < S; i++) out[o + i] += amounts[b + i];
        }
      }
      this.cache.set('packed', out);
      return out;
    }

    /** Positions of the inventory's nuclides among a system's members. */
    positions(sys) {
      return Int32Array.from(this.nuclides, (u) => (sys.index.has(u.name) ? sys.index.get(u.name) : -1));
    }

    /**
     * Each canister at a time: amounts [canister][part][nuclide] in moles,
     * and each canister's decay heat (W) and activity of the listed
     * nuclides (Bq), daughters in equilibrium counted in the heat.
     *
     * @param {Object} sys - decaySystem() over at least names()
     * @param {null|number} ms - null for each canister as packed, else the
     *   time (ms since 1970) to bring every canister to; a canister packed
     *   later is left as packed and counted in `later`
     */
    canistersAt(sys, ms, key) {
      const ck = `can|${key}|${ms}`;
      if (this.cache.has(ck)) return this.cache.get(ck);
      const S = this.P * this.N, N = this.N, P = this.P;
      const packed = this.packed();
      const pos = this.positions(sys);
      const m = sys.members.length;
      const amounts = ms === null ? packed : new Float64Array(this.nCan * S);
      const heat = new Float64Array(this.nCan);
      const activity = new Float64Array(this.nCan);
      /* Every member of the system, daughters too: [canister][member]. */
      const full = new Float64Array(this.nCan * m);
      const dates = this.data.canisters.date;
      let later = 0;
      const vec = new Float64Array(m);
      for (let c = 0; c < this.nCan; c++) {
        const t = ms === null || !Number.isFinite(dates[c]) ? 0 : (ms - dates[c]) / 1000;
        if (t < 0) later++;
        const tt = t > 0 ? t : 0;
        /* The whole canister, for its heat and activity. */
        vec.fill(0);
        for (let p = 0; p < P; p++) for (let k = 0; k < N; k++) if (pos[k] >= 0) vec[pos[k]] += packed[c * S + p * N + k];
        const whole = decay(sys, withDaughters(sys, vec), tt);
        full.set(whole, c * m);
        heat[c] = heatOf(sys, whole);
        let a = 0;
        for (let k = 0; k < N; k++) if (pos[k] >= 0) a += whole[pos[k]] * sys.lambda[pos[k]];
        activity[c] = a * NA;
        if (ms === null) continue;
        /* Each part on its own, for the parts' shares. */
        for (let p = 0; p < P; p++) {
          vec.fill(0);
          let any = false;
          for (let k = 0; k < N; k++) {
            const x = packed[c * S + p * N + k];
            if (x !== 0 && pos[k] >= 0) { vec[pos[k]] = x; any = true; }
          }
          if (!any) continue;
          const n = tt > 0 ? decay(sys, withDaughters(sys, vec), tt) : vec;
          for (let k = 0; k < N; k++) amounts[c * S + p * N + k] = pos[k] >= 0 ? n[pos[k]] : packed[c * S + p * N + k];
        }
      }
      const out = { amounts, heat, activity, later, full, m };
      this.cache.set(ck, out);
      return out;
    }

    /** The sum over a set of canisters of every member (canistersAt().full). */
    fullSum(at, sel) {
      const out = new Float64Array(at.m);
      for (const c of sel) for (let i = 0, o = c * at.m; i < at.m; i++) out[i] += at.full[o + i];
      return out;
    }

    /**
     * Each element at a time, its parts summed: amounts [element][nuclide]
     * in moles, decay heat and activity.
     */
    elementsAt(sys, ms, key) {
      const ck = `el|${key}|${ms}`;
      if (this.cache.has(ck)) return this.cache.get(ck);
      const { amounts: src, canisters: can } = this.data;
      const S = this.P * this.N, N = this.N, P = this.P;
      const pos = this.positions(sys);
      const m = sys.members.length;
      const amounts = new Float64Array(this.nEl * N);
      const heat = new Float64Array(this.nEl);
      const activity = new Float64Array(this.nEl);
      const vec = new Float64Array(m);
      for (let c = 0; c < this.nCan; c++) {
        const t = ms === null || !Number.isFinite(can.date[c]) ? 0 : Math.max(0, (ms - can.date[c]) / 1000);
        for (let e = can.el0[c], end = e + can.nEl[c]; e < end; e++) {
          vec.fill(0);
          for (let p = 0; p < P; p++) for (let k = 0; k < N; k++) if (pos[k] >= 0) vec[pos[k]] += src[e * S + p * N + k];
          const n = decay(sys, withDaughters(sys, vec), t);
          heat[e] = heatOf(sys, n);
          let a = 0;
          for (let k = 0; k < N; k++) {
            if (pos[k] >= 0) { amounts[e * N + k] = n[pos[k]]; a += n[pos[k]] * sys.lambda[pos[k]]; } else {
              let s = 0;
              for (let p = 0; p < P; p++) s += src[e * S + p * N + k];
              amounts[e * N + k] = s;
            }
          }
          activity[e] = a * NA;
        }
      }
      const out = { amounts, heat, activity };
      this.cache.set(ck, out);
      return out;
    }

    /**
     * Raw values for a table: a row for each element chosen, or for each
     * canister holding any, its chosen elements summed; a column for each
     * part and nuclide chosen, or for each nuclide, the parts summed. In mol,
     * Bq, g, or W of decay heat (the nuclide's own with its short-lived
     * daughters'), as the file gives them (ms null) or at a time, each
     * canister decayed from its own packing date. The rows are worked out
     * when asked for, so that a long table can be filled a piece at a time.
     *
     * @param {Object} sys - decaySystem() over names()
     * @param {{chosen: Uint8Array, level: 'el'|'can', parts: number[], apart: boolean,
     *   nuclides: number[], ms: null|number, qty: 'mol'|'Bq'|'g'|'W'}} opt
     * @returns {{rows: Int32Array, cols: Array<{p: number, k: number}>,
     *   fill: function(Float64Array, number, number)}} cols' p is -1 for the
     *   parts summed; fill(out, from, to) writes rows from..to-1 into out, a
     *   row of cols.length at a time
     */
    raw(sys, opt) {
      const { amounts: src, canisters: can, elements: el } = this.data;
      const S = this.P * this.N, N = this.N;
      const { chosen, nuclides, ms, qty } = opt;
      const byEl = opt.level === 'el';
      const pos = this.positions(sys);
      const rows = [];
      if (byEl) {
        for (let e = 0; e < this.nEl; e++) if (chosen[e]) rows.push(e);
      } else {
        for (let c = 0; c < this.nCan; c++) {
          for (let e = can.el0[c], end = e + can.nEl[c]; e < end; e++) if (chosen[e]) { rows.push(c); break; }
        }
      }
      const groups = opt.apart ? opt.parts.map((p) => [p]) : [opt.parts];
      const cols = groups.flatMap((g) => nuclides.map((k) => ({ p: opt.apart ? g[0] : -1, k })));
      const eff = qty === 'W' ? effectiveEnergy(sys) : null;
      const factor = Float64Array.from(nuclides, (k) => {
        const i = pos[k];
        if (qty === 'W') return i >= 0 ? sys.lambda[i] * eff[i] * NA * MEV_J : NaN;
        return perMole(sys, i, qty);
      });
      const vec = new Float64Array(sys.members.length);
      const given = new Float64Array(N);
      const fill = (out, from, to) => {
        const width = cols.length, nk = nuclides.length;
        for (let r = from; r < to; r++) {
          const c = byEl ? el.can[rows[r]] : rows[r];
          const t = ms === null || !Number.isFinite(can.date[c]) ? 0 : Math.max(0, (ms - can.date[c]) / 1000);
          const e0 = byEl ? rows[r] : can.el0[c], e1 = byEl ? rows[r] + 1 : can.el0[c] + can.nEl[c];
          groups.forEach((g, gi) => {
            vec.fill(0);
            given.fill(0);
            for (let e = e0; e < e1; e++) {
              if (!chosen[e]) continue;
              for (const p of g) {
                for (let k = 0, b = e * S + p * N; k < N; k++) {
                  const x = src[b + k];
                  if (x === 0) continue;
                  given[k] += x;
                  if (pos[k] >= 0) vec[pos[k]] += x;
                }
              }
            }
            const n = t > 0 ? decay(sys, withDaughters(sys, vec), t) : vec;
            const o = r * width + gi * nk;
            for (let j = 0; j < nk; j++) {
              const k = nuclides[j], i = pos[k];
              out[o + j] = (i >= 0 ? n[i] : given[k]) * factor[j];
            }
          });
        }
      };
      return { rows: Int32Array.from(rows), cols, fill };
    }

    /**
     * Sums over a set of canisters: [part][nuclide] and each canister's
     * total per nuclide (for the spread among them).
     *
     * @param {Float64Array} amounts - canistersAt().amounts
     * @param {Int32Array|number[]} sel - canister indices
     */
    sumOver(amounts, sel) {
      const S = this.P * this.N, N = this.N;
      const parts = Array.from({ length: this.P }, () => new Float64Array(N));
      for (const c of sel) {
        for (let p = 0; p < this.P; p++) {
          const row = parts[p];
          const o = c * S + p * N;
          for (let k = 0; k < N; k++) row[k] += amounts[o + k];
        }
      }
      const total = new Float64Array(N);
      for (const row of parts) for (let k = 0; k < N; k++) total[k] += row[k];
      return { parts, total, count: sel.length };
    }

    /** Each canister's total of one nuclide over its parts. */
    perCanister(amounts, sel, k) {
      const S = this.P * this.N, N = this.N;
      const out = new Float64Array(sel.length);
      sel.forEach((c, i) => {
        let s = 0;
        for (let p = 0; p < this.P; p++) s += amounts[c * S + p * N + k];
        out[i] = s;
      });
      return out;
    }

    /** The canisters of a type (index into typeNames), or all of them for -1. */
    select(type = -1) {
      const out = [];
      for (let c = 0; c < this.nCan; c++) if (type < 0 || this.canType[c] === type) out.push(c);
      return Int32Array.from(out);
    }

    /** Elements per value of a text field (reactor, fuel type ...), in a set of canisters. */
    countBy(field, sel) {
      const col = this.data.elements.text[field];
      const counts = new Map();
      if (!col) return counts;
      const can = this.data.canisters;
      for (const c of sel) {
        for (let e = can.el0[c], end = e + can.nEl[c]; e < end; e++) {
          const v = col.codes[e] >= 0 ? col.values[col.codes[e]] : '';
          counts.set(v, (counts.get(v) || 0) + 1);
        }
      }
      return counts;
    }

    /** A canister's elements, as indices. */
    elementsOf(c) {
      const can = this.data.canisters;
      return Array.from({ length: can.nEl[c] }, (_, i) => can.el0[c] + i);
    }
  }

  /* ---------------------------------------------------------------------
     Units
     --------------------------------------------------------------------- */

  const UNITS = {
    mol: { label: 'mol', of: 'amount' },
    Bq: { label: 'Bq', of: 'activity' },
    g: { label: 'g', of: 'mass' },
  };

  /** What one mole of a member is in a unit. */
  function perMole(sys, i, unit) {
    if (unit === 'Bq') return i >= 0 ? NA * sys.lambda[i] : NaN;
    if (unit === 'g') return i >= 0 ? sys.mass[i] : NaN;
    return 1;
  }

  /* ---------------------------------------------------------------------
     A reference inventory (an earlier assessment's)
     --------------------------------------------------------------------- */

  /**
   * A reference's values in moles at a time, decayed from its own year.
   *
   * @param {{values: Map<string, number>, unit: string, year: number}} ref
   * @param {Map} nd
   * @param {Map} [halfLives]
   * @param {number|null} year - null for the reference's own year
   * @returns {{mol: Map<string, number>, sys: Object, ok: boolean}} ok is
   *   false when the year is before the reference's own
   */
  function referenceAt(ref, nd, halfLives, year, values = ref.values) {
    const names = [...values.keys()];
    const sys = decaySystem(nd, names, halfLives);
    const n = new Float64Array(sys.members.length);
    for (const [name, v] of values) {
      const i = sys.index.get(name);
      if (i === undefined || !Number.isFinite(v)) continue;
      n[i] = ref.unit === 'Bq' ? (sys.lambda[i] > 0 ? v / (NA * sys.lambda[i]) : 0) : ref.unit === 'g' ? v / sys.mass[i] : v;
    }
    const target = year === null || year === undefined ? ref.year : year;
    const t = (yearMs(target) - yearMs(ref.year)) / 1000;
    const ok = t >= 0;
    const start = withDaughters(sys, n);
    const out = ok && t > 0 ? decay(sys, start, t) : start;
    const mol = new Map();
    for (const name of names) mol.set(name, out[sys.index.get(name)]);
    return { mol, sys, ok, all: out };
  }

  return {
    YEAR_S, NA, MEV_J, SHORT_Y, UNITS,
    nuclearData, decaySystem, withDaughters, decayTimes, decay, heatOf, effectiveEnergy,
    yearMs, decimalYear, quantileSorted, summary,
    partLabel, categoryOf, Inventory, perMole, referenceAt,
  };
});
