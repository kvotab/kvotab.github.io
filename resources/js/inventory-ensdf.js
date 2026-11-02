/* ==========================================================================
   CANISTER_INVENTORY.HTML: ENSDF'S HALF-LIVES AND CHAINS

   The page decays with ICRP Publication 107's data unless an ENSDF release
   on the site is chosen under Half-lives (resources/data/ensdf/, the
   releases the Chart of Nuclides and Radionuclide Decay Chains read). Then
   ENSDF gives the half-lives, the branches and so the chains, as
   rdc-ensdf.js builds them for Radionuclide Decay Chains (ensdf-core.js's
   buildChain(), isomers under a second passed through), and the energy
   each decay gives off, where the release gives it. Where it does not, the
   energy is ICRP 107's for the same state; atomic masses are ICRP 107's
   throughout, as ENSDF has none.

   A nuclide the inventory names is the ENSDF state of that nuclide whose
   half-life is closest to ICRP 107's for the name, within a fifth of a
   decade (the inventory's Am-242m is ENSDF's Am-242m1), or else the ground
   state for a name without m and the first isomer for one with it. The
   state takes the inventory's name, so that the inventory's amounts land on
   it, and every arrow to it is renamed the same.

   One global: KVOT_INV_ENSDF (module.exports under Node). Needs
   KVOT_RDC_ENSDF (rdc-ensdf.js, with ensdf-core.js) and KVOT_INV_JSON.
   ========================================================================== */
(function (root, factory) {
  const node = typeof module === 'object' && module.exports;
  const api = factory(node ? require('./rdc-ensdf.js') : root.KVOT_RDC_ENSDF, node ? require('./inventory-json.js') : root.KVOT_INV_JSON);
  if (node) module.exports = api;
  else root.KVOT_INV_ENSDF = api;
})(typeof self !== 'undefined' ? self : this, function (RE, JSONR) {
  'use strict';

  /* A fifth of a decade: how close ENSDF's half-life must be to ICRP 107's
     for a state to be taken as the one an isomer's name means. */
  const SAME_LIFE = 0.2;
  /* The chains: every branch, isomers under a second passed through, as on
     the Chart of Nuclides. */
  const CHAIN = { minBranch: 0, life: 'iso' };

  const decays = (st) => !!st && !st.st && st.ts > 0;

  /**
   * The ENSDF state a name of the inventory stands for.
   *
   * @param {Object} db - rdc-ensdf.js's database()
   * @param {string} name - Am-242m
   * @param {number} icrpT - ICRP 107's half-life for the name (years), 0 if none
   * @returns {{z, a, k, name: string, how: string}|null} name: ENSDF's
   */
  function stateOf(db, name, icrpT) {
    const n = JSONR.nuclideOf(name);
    if (!n) return null;
    const nuc = db.idx.get(n.z, n.a);
    if (!nuc || !nuc.s || !nuc.s.length) return null;
    const at = (k, how) => ({ z: n.z, a: n.a, k, name: RE.nameOf(n.z, n.a, k, nuc), how });
    if (icrpT > 0) {
      const t = icrpT * RE.YEAR;
      let best = -1, gap = Infinity;
      nuc.s.forEach((st, k) => {
        if (!decays(st)) return;
        const g = Math.abs(Math.log10(st.ts / t));
        if (g < gap) { gap = g; best = k; }
      });
      if (gap <= SAME_LIFE) return at(best, 'half-life');
    }
    if (!n.iso) return at(0, 'ground state');
    const k = nuc.s.findIndex((st, i) => i > 0 && decays(st));
    return k > 0 ? at(k, 'first isomer') : null;
  }

  /**
   * Records in the ICRP 107 file's shape (what inventory-model.js's
   * nuclearData() reads) for every member of the chains below the names.
   *
   * @param {Object} db - rdc-ensdf.js's database()
   * @param {string[]} names - the nuclides the inventory and PSAR's tables give
   * @param {Map} icrp - inventory-model.js's nuclearData() of ICRP 107
   * @param {Array} icrpRecords - ICRP 107's records (rndecaydata.js), for masses
   * @returns {{records: Array, states: Map<string, Object>, missing: string[],
   *   energyFromIcrp: string[], energyUnknown: string[], label: string}}
   *   states: each name -> the ENSDF state it stands for; missing: names
   *   ENSDF has no state for (they keep ICRP 107's data)
   */
  function recordsFor(db, names, icrp, icrpRecords) {
    const states = new Map(), missing = [];
    for (const name of new Set(names)) {
      const rec = icrp.get(name);
      const st = stateOf(db, name, rec ? rec.T : 0);
      if (st) states.set(name, st); else missing.push(name);
    }
    /* ENSDF's names to the inventory's, and any other ENSDF state that
       would take one of them out of the way. */
    const rename = new Map();
    for (const [name, st] of states) if (st.name !== name) rename.set(st.name, name);
    const taken = new Set(states.keys());
    const nameFor = (n) => {
      if (rename.has(n)) return rename.get(n);
      return taken.has(n) && !(states.get(n) && states.get(n).name === n) ? `${n} (ENSDF)` : n;
    };
    const byName = new Map();
    for (const [name, st] of states) {
      const ch = RE.chain(db, st.name, CHAIN);
      if (!ch) {
        /* Stable, or of no known half-life: a member that does not decay. */
        if (!byName.has(st.name)) byName.set(st.name, { name: st.name, Z: st.z, A: st.a, Halflife_y: NaN, Progenies: [] });
        continue;
      }
      for (const r of ch.records.values()) if (!byName.has(r.name)) byName.set(r.name, r);
    }
    const mass = new Map();
    for (const r of icrpRecords || []) if (Number(r.Mass) > 0 && !mass.has(`${r.Z},${r.A}`)) mass.set(`${r.Z},${r.A}`, Number(r.Mass));
    const energyFromIcrp = [], energyUnknown = [];
    const records = [];
    for (const r of byName.values()) {
      const name = nameFor(r.name);
      const out = {
        name, Z: r.Z, A: r.A, Halflife_y: r.Halflife_y, Mass: mass.get(`${r.Z},${r.A}`) || r.A,
        Alpha_energy: r.Alpha_energy || 0, Electron_energy: r.Electron_energy || 0, Photon_energy: r.Photon_energy || 0,
        Progenies: (r.Progenies || []).map((p) => ({ name: p.name === 'SF' ? 'SF' : nameFor(p.name), br: p.br })),
      };
      if (r.energyKnown === false && Number(r.Halflife_y) > 0) {
        /* ICRP 107's energies for the state, where it has it under the same name or the inventory's. */
        const same = icrp.get(name) || icrp.get(r.name);
        if (same && same.E > 0) {
          out.Alpha_energy = same.E;
          out.Electron_energy = 0;
          out.Photon_energy = 0;
          energyFromIcrp.push(name);
        } else energyUnknown.push(name);
      }
      records.push(out);
    }
    /* Names ENSDF has no state for keep ICRP 107's record. */
    for (const name of missing) {
      const r = icrp.get(name);
      if (r) records.push({ name, Z: r.z, A: r.a, Halflife_y: r.T || NaN, Mass: r.mass, Alpha_energy: r.E, Electron_energy: 0, Photon_energy: 0, Progenies: r.prog.map((p) => ({ name: p.name, br: p.br })) });
    }
    return { records, states, missing, energyFromIcrp, energyUnknown, label: db.label };
  }

  return { SAME_LIFE, CHAIN, stateOf, recordsFor };
});
