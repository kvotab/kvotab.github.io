/*
  The decay data of ICRP Publication 38 as the publication printed them.

  The page's ICRP 38 data are the unabridged file that came with DCAL
  (ICRP38.RAD): every line the evaluation has, yields to six figures.
  Publication 38 itself printed an abridged table for each nuclide, and the
  ICRP's database of dose coefficients shows that Publications 67-72 were
  calculated from those tables, not from the file. A table differs from the
  file in five ways (the format is described in JAERI-Data/Code 99-035,
  Appendix A, which follows Publication 38):

  - A yield has three figures and an energy four ("y(i) 1.03E-01, E(i)
    4.776E-01"). 7Be's one gamma ray is 0.1034 per transformation in the file
    and 0.103 in the table, and every dose of the database after 7Be is 0.39 %
    below the file's. A yield that lies on the half is the lower figure in
    every case the database shows: 65Zn's 0.5075 is 0.507, 95Zr's 0.4455
    0.445, 88Y's 0.9935 0.993, 133Ba's 0.6215 0.621, and so 101Rh's, 175Yb's,
    194mTl's and 115mCd's.

  - A nuclide of more than 32 radiations has the weak ones left out: the
    radiations fall in three categories -- gamma rays, X-rays and annihilation
    photons; beta particles, conversion and Auger electrons; alpha particles
    and their recoil nuclei -- and one is omitted when it gives less than
    0.1 % of the energy of its category ("each omitted transition contributes
    < 0.100 % to the sum of y(i) x E(i) in its category"). Were more than 175
    left, the 0.1 would be raised by 0.1 at a time until they are no more.
    54Mn has 34 lines and one gamma ray of 0.835 MeV; its chromium K X-rays
    of 5.4 keV carry 0.049 %, 0.097 % and less of the photon energy each, so
    the table has none of them.

  - The K X-rays are listed line by line, the L X-rays by series: L-alpha,
    L-beta, L-gamma, L-eta and L-l, each one radiation with the series' yield
    and mean energy. 125I's L-alpha and L-beta are listed (0.55 % and 0.58 %
    of the photon energy), its L-gamma is not (0.08 %); line by line only
    three of its twelve L lines would be. The series of a line is its third
    item in the data, "a52" an L-alpha line of tellurium
    (scripts/lib/dose-decay.mjs writes it).

  - The Auger electrons are listed in groups, "a composite of several Auger
    transitions of similar energy": KLL (six lines of the file), KLX
    (three), KXY, and LMM, LMX and LXY (a line for each L subshell), again
    one radiation each with the group's yield and mean energy. The group is
    the line's third item too, "KLL52". 141Ce's nine K Auger lines carry
    0.02-0.07 % of its electron energy each, its KLL group 0.17 %. 55Fe's
    sixteen Auger lines make six radiations (0.495 KLL electrons of
    5.145 keV, 0.112 KLX of 5.806 keV, ...), and with them the energy the
    alveolar region gets from 55Fe, 59Ni, 53Mn, 49V and 41Ca is the
    database's to its six figures.

  - What a table leaves out it still counts: its last lines give the energy
    of the listed and of the omitted radiations of each category. The
    database has the omitted energy with the listed radiations of the same
    category, each stronger by (listed + omitted) / listed. The 0.17 % of
    54Mn's photon energy that its X-rays carry leaves with the gamma ray:
    every tissue far from the source gets 0.19 % more than by the file (the
    0.17 and the yield of 1.00 for 0.99976), and the source's own, which the
    X-rays would have reached and the gamma ray mostly leaves, gets less --
    the bone surfaces a tenth less, the alveoli 2.4 % (tests' README).

  The beta spectra are the file's (the tables have none), and so are the
  radiations of spontaneous fission.
*/

/** Figures of a yield and of an energy, the most radiations listed in full, the cutoff and its step, the most left after it. */
export const PRINTED_38 = { yield: 3, energy: 4, full: 32, cutoff: 0.001, most: 175 };

/**
 * A number to n figures as the tables have it: rounded, a half going down.
 */
export function figures38(v, n) {
  if (!(v > 0)) return v;
  const p = Math.floor(Math.log10(v)) - n + 1;
  const m = v / 10 ** p;
  const whole = Math.floor(m + 1e-9);
  // The data have six figures, so a half is a half to well within 1e-6.
  const r = m - whole > 0.5 + 1e-6 ? whole + 1 : whole;
  return Number((r * 10 ** p).toPrecision(n));
}

const cache = new WeakMap();

/**
 * A nuclide's radiations as Publication 38's table has them (see the head of
 * this file), made from the unabridged lines.
 *
 * @param {object} em  {r: {p, e, b, a, sf}, bs} of the ICRP 38 decay data; an
 *   L X-ray is [E, y, series], an Auger electron of a group [E, y, group]
 * @param {number} A   mass number (the recoil nuclei are radiations of the
 *   alpha category)
 * @returns {object}  as `em`, with the lines of the table, and
 *   printed: {lines, cutoff, listed, back: [photons, electrons, alphas]} --
 *   the file's lines, the cutoff used (a fraction), the radiations listed
 *   and the factor that puts each category's omitted energy back
 */
export function printed38(em, A) {
  if (!em || !em.r) return em;
  const hit = cache.get(em);
  if (hit) return hit;
  const r = em.r;
  const src = { p: r.p || [], e: r.e || [], b: r.b || [], a: r.a || [] };
  const CAT = { p: 0, e: 1, b: 1, a: 2 };
  const recoil = A > 4 ? 4.0026 / (A - 4) : 0;

  // The radiations of the table: a line each, the L X-rays of a series and
  // the Auger electrons of a group together.
  const rads = [], groups = new Map();
  for (const k of ['p', 'e', 'b', 'a']) {
    src[k].forEach((l, i) => {
      const en = l[0] * l[1];
      if (typeof l[2] === 'string') {
        const key = k + l[2];
        let g = groups.get(key);
        if (!g) { g = { k, cat: CAT[k], lines: [], en: 0, group: true }; groups.set(key, g); rads.push(g); }
        g.lines.push(i); g.en += en;
      } else rads.push({ k, cat: CAT[k], lines: [i], en });
    });
  }
  const total = [0, 0, 0];
  for (const x of rads) total[x.cat] += x.en;
  const alphaCategory = total[2] * (1 + recoil);
  const lines = src.p.length + src.e.length + src.b.length + 2 * src.a.length;

  let cutoff = lines <= PRINTED_38.full ? 0 : PRINTED_38.cutoff, listed, count;
  for (;;) {
    listed = rads.filter((x) => x.en >= cutoff * (x.cat === 2 ? alphaCategory : total[x.cat]));
    // A recoil nucleus is a radiation of its own, listed with its alpha when it too is over the cutoff.
    count = listed.length + listed.filter((x) => x.cat === 2 && x.en * recoil >= cutoff * alphaCategory).length;
    if (cutoff === 0 || count <= PRINTED_38.most) break;
    cutoff += PRINTED_38.cutoff;
  }

  // The omitted energy goes with the listed radiations of its category.
  const kept = [0, 0, 0];
  for (const x of listed) kept[x.cat] += x.en;
  const back = total.map((t, c) => (kept[c] > 0 ? t / kept[c] : 1));

  const out = { p: [], e: [], b: [], a: [] };
  for (const x of listed) {
    const f = back[x.cat];
    if (x.group) {
      const Y = x.lines.reduce((s, i) => s + src[x.k][i][1], 0);
      out[x.k].push([figures38(x.en / Y, PRINTED_38.energy), figures38(Y, PRINTED_38.yield) * f]);
    } else {
      const [e, y] = src[x.k][x.lines[0]];
      out[x.k].push([figures38(e, PRINTED_38.energy), figures38(y, PRINTED_38.yield) * f]);
    }
  }
  const rr = { ...r };
  for (const k of ['p', 'e', 'b', 'a']) if (r[k]) rr[k] = out[k].sort((p, q) => p[0] - q[0]);
  const res = { ...em, r: rr, printed: { lines, cutoff, listed: count, back } };
  cache.set(em, res);
  return res;
}
