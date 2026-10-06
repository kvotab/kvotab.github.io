/*
  The names of the states of other decay data, in a system's own names.

  The page names a radionuclide as its system's decay data do (ICRP 107 in
  the ICRP 103 system, ICRP 38 in the ICRP 60 one), and its models, forms
  and cases are listed under those names. Decay data made from a release of
  ENSDF (scripts/gen-dose-ensdf.mjs) name the states as that release
  orders them, and some differ: ENSDF 2026 calls the 2.36 h state of Ta-178
  its ground state, which ICRP 107 calls Ta-178m. So the states of each
  nuclide are paired by half-life, the closest pair first, and an ENSDF state
  paired with an ICRP state takes the ICRP name; a calculation for Ta-178m
  is then of the same radionuclide whichever decay data it uses.

  Two states of different names pair only when their half-lives agree within
  a factor of 2 (the swapped names agree exactly); states of the same name
  always do, however far their half-lives have moved (Te-123's ICRP 107
  6E14 y and ENSDF 2026's limit of 9.2E16 y). A state left unpaired keeps its
  own name, or, when a pairing has given that name to another state, the
  next isomer letter free (m, n, p, q ...): ENSDF 2026's 4.6 s Y-84m becomes
  Y-84n beside the 39.5 min state that ICRP 107 calls Y-84m.
*/

const LETTERS = ['m', 'n', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z'];
const groupOf = (name) => name.replace(/[a-z]+$/, '');
const RENAME_RATIO = Math.log(2);

/**
 * @param {object} own    the system's decay index: name -> {T (days), ...}
 * @param {object} other  the other decay data's index: name -> {T, d: [[daughter, branch]...], ...}
 * @returns {{nuclides: object, pageOf: (name: string) => string, otherOf: (name: string) => string|undefined,
 *            renamed: Array<[string, string]>}}
 *   nuclides: the other index under the page's names, daughters renamed too;
 *   pageOf: the page's name of a state of the other data (unchanged where not
 *   renamed); otherOf: the other data's name of a page name; renamed: the
 *   [other name, page name] pairs that differ.
 */
export function pairNames(own, other) {
  const groups = new Map();
  const at = (g) => { if (!groups.has(g)) groups.set(g, { own: [], other: [] }); return groups.get(g); };
  for (const [n, e] of Object.entries(own)) at(groupOf(n)).own.push([n, e.T]);
  for (const [n, e] of Object.entries(other)) at(groupOf(n)).other.push([n, e.T]);
  const page = new Map(); // other name -> page name
  for (const [g, { own: a, other: b }] of groups) {
    if (!b.length) continue;
    const pairs = [];
    for (const [x, Tx] of a) {
      for (const [y, Ty] of b) {
        const r = Math.abs(Math.log(Tx / Ty));
        if (x === y || r <= RENAME_RATIO) pairs.push([x, y, Number.isFinite(r) ? r : Infinity]);
      }
    }
    // Closest first; at equal distance a pair of the same name first.
    pairs.sort((p, q) => (p[2] - q[2]) || ((p[0] === p[1] ? 0 : 1) - (q[0] === q[1] ? 0 : 1)));
    const usedOwn = new Set(), usedOther = new Set();
    for (const [x, y] of pairs) {
      if (usedOwn.has(x) || usedOther.has(y)) continue;
      usedOwn.add(x); usedOther.add(y);
      page.set(y, x);
    }
    // The rest keep their names where free, else take the next isomer letter.
    const taken = new Set([...a.map(([x]) => x), ...page.values()]);
    for (const [y] of b) {
      if (page.has(y)) continue;
      let name = y;
      if (taken.has(name)) name = LETTERS.map((c) => g + c).find((c) => !taken.has(c)) || `${g}~${y}`;
      taken.add(name);
      page.set(y, name);
    }
  }
  const back = new Map([...page].map(([y, x]) => [x, y]));
  const pageOf = (y) => page.get(y) ?? y;
  const nuclides = {};
  for (const [y, e] of Object.entries(other)) nuclides[pageOf(y)] = { ...e, d: (e.d || []).map(([d, b]) => [pageOf(d), b]) };
  return {
    nuclides, pageOf, otherOf: (x) => back.get(x),
    renamed: [...page].filter(([y, x]) => x !== y),
  };
}
