/*
  The compact form in which the page keeps the radiations of a nuclide
  (decay/<El>.json): lines [E, Y] to six figures, sorted by energy, and the
  beta spectrum to four. The same as scripts/lib/dose-decay.mjs writes the
  ICRP data in, for the decay data made from ENSDF (ensdf-make.js), which
  runs in the browser as well as in Node.
*/

/** A number to n significant figures (6), as a number. */
export const sig = (v, n = 6) => (v === 0 ? 0 : Number(v.toPrecision(n)));
const lines = (arr) => arr.map(([e, y]) => [sig(e), sig(y)]).sort((p, q) => p[0] - q[0]);

/** {p, b, e, a, ar, ff, n: [[E, Y]...], sf?: [[Y, E]]} without the empty kinds. */
export function compactRad(rad) {
  const out = {};
  for (const [k, v] of Object.entries(rad)) {
    if (!v.length) continue;
    out[k] = k === 'sf' ? v.map(([y, e]) => [sig(y), sig(e)]) : lines(v);
  }
  return out;
}

/** [[E...], [N...]] or null. */
export function compactSpectrum(bs) {
  if (!bs) return null;
  return [bs[0].map((e) => sig(e)), bs[1].map((n) => sig(n, 4))];
}
