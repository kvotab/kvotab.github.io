/* rdc.html's records from ENSDF (resources/js/rdc-ensdf.js), in Node.

     node resources/tests/site/test-rdc-ensdf.js

   Against the release on the site (resources/data/ensdf/) and the ICRP 107
   file the page has built in (resources/js/rndecaydata.js):

   - names: the Chart of Nuclides' isomer tags, m for a lone isomer, m1 and
     m2 where there are two, and a name for every state that is no other's;
   - half-lives in the words of the ICRP 107 file, and nothing in them but
     numbers, units and the one <sup> the label may carry;
   - decay modes as the ICRP 107 file writes them;
   - the dose coefficients each state takes from ICRP 107, by half-life;
   - every chain the element list can start, at two settings: each member's
     arrows carry the shares ensdf-core.js's decay system moves -- so the
     page's decay is the Chart of Nuclides' -- every arrow ends at a member
     or in fission, the energies are chainEmission()'s, and no two circles
     of the layout touch.

   Exit status 0 when every check passes. */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..', '..', '..');
const C = require(path.join(ROOT, 'resources/js/ensdf-core.js'));
const R = require(path.join(ROOT, 'resources/js/rdc-ensdf.js'));

let pass = 0, fail = 0;
function check(label, got, want) {
  const ok = typeof want === 'function' ? want(got) : JSON.stringify(got) === JSON.stringify(want);
  if (ok) { pass++; console.log(`ok    ${label}`); } else { fail++; console.log(`FAIL  ${label}\n      got ${JSON.stringify(got)}${typeof want === 'function' ? '' : `\n      want ${JSON.stringify(want)}`}`); }
}

const releases = new Function('KVOT_ENSDF_DATA', fs.readFileSync(path.join(ROOT, 'resources/data/ensdf/releases.js'), 'utf8') + '; return null;');
let list = null;
releases((id, part, payload) => { list = payload; });
let summary = null;
new Function('KVOT_ENSDF_DATA', fs.readFileSync(path.join(ROOT, `resources/data/ensdf/${list[0].id}/summary.js`), 'utf8'))((id, part, payload) => { summary = payload; });
const decaydata = new Function(fs.readFileSync(path.join(ROOT, 'resources/js/rndecaydata.js'), 'utf8') + '; return decaydata;')();

const db = R.database(summary, decaydata);
const st = (name) => { const at = db.states.get(name); return at && db.idx.get(at.z, at.a).s[at.k]; };

/* ── Names ──────────────────────────────────────────────────────────── */
check('the element list holds the radioactive states with a half-life', db.states.size, (n) => n > 4000);
check('a lone isomer is m, as on the Chart of Nuclides', ['Pa-234m', 'Tc-99m', 'Ba-137m', 'U-238m'].every((n) => db.states.has(n)), true);
check('two are m1 and m2 (178m2Hf is the 31-year one)', [st('Hf-178m2') && st('Hf-178m2').t, db.states.has('U-235m1'), db.states.has('U-235m2')], ['31 Y', true, true]);
check('no stable state, and nothing for the neutron', [db.states.has('U-235') && !st('Pb-208'), [...db.states.values()].some((s) => s.z === 0)], [true, false]);
{
  /* Every name for one state, and back again. */
  const seen = new Map();
  let clash = 0, back = 0;
  for (const [name, s] of db.states) {
    const key = `${s.z},${s.a},${s.k}`;
    if (seen.has(key)) clash++;
    seen.set(key, name);
    if (R.nameOf(s.z, s.a, s.k, db.idx.get(s.z, s.a)) !== name) back++;
  }
  check('every state has a name of its own, and the name is its name', [clash, back, seen.size === db.states.size], [0, 0, true]);
  const fallback = [];
  for (const nuc of db.idx.shown) {
    if (!nuc.s || nuc.s.length < 2) continue;
    const tags = R.tagsOf(nuc).slice(1);
    if (new Set(tags).size !== tags.length || tags.some((t) => !/^m\d*$/.test(t))) fallback.push(`${nuc.z},${nuc.a}`);
  }
  check('where the Chart of Nuclides names an isomer by its energy, the tag is still m<n>, and one of its own', fallback, []);
}

/* ── Half-lives ─────────────────────────────────────────────────────── */
check('half-lives as the ICRP 107 file writes them, with the evaluators\' digits',
  ['U-238', 'U-234', 'Th-230', 'Ra-226', 'Rn-222', 'Pa-234m', 'Po-214', 'Po-212', 'Bi-209', 'Kr-101'].map((n) => R.halfLifeLabel(st(n))),
  ['4.468 By', '245.5 ky', '75.584 ky', '1600 y', '3.8222 d', '1.159 m', '163.46 µs', '294.3 ns', '2.01×10<sup>19</sup> y', '>635 ns']);
check('a half-life from a level width, in seconds', R.halfLifeLabel(st('Be-8')), '8.19×10<sup>-17</sup> s');
check('stable, and none known', [R.halfLifeLabel({ st: 1 }), R.halfLifeLabel({ t: '' }), R.halfLifeLabel(null)], ['Stable', '?', '?']);
{
  const odd = [];
  for (const [name] of db.states) {
    const t = R.halfLifeLabel(st(name));
    if (!/^[<>≈≤≥]?[0-9.]+(×10<sup>-?\d+<\/sup>)? (By|My|ky|y|d|h|m|s|ms|µs|ns|ps|fs|as)( \?)?$/.test(t)) odd.push(`${name} ${t}`);
  }
  check('every label is a number, a unit and at most one <sup>: nothing from the file reaches the markup', odd, []);
}

/* ── Decay modes ────────────────────────────────────────────────────── */
check('decay modes as the ICRP 107 file writes them, the rest as ENSDF does',
  ['A', 'B-', 'EC+B+', 'EC', 'IT', 'SF', 'B-N', 'B-2N', 'ECP', '14C'].map(R.modeLabel),
  ['&alpha;', '&beta;-', '&beta;+ & EC', 'EC', 'IT', 'SF', 'β-n', 'β-2n', 'εp', '14C']);

/* ── Dose coefficients ──────────────────────────────────────────────── */
{
  const radio = decaydata.filter((d) => d.Halflife !== 'Stable');
  const taken = new Set([...db.dcc.values()].map((d) => d.name));
  check('nearly every ICRP 107 radionuclide gives its coefficients to an ENSDF state', [taken.size, radio.length], (v) => v[0] >= 1240 && v[1] === 1252);
  const dcc = (n) => { const s = db.states.get(n); const d = db.dcc.get(`${s.z},${s.a},${s.k}`); return d ? [d.name, d.ing, d.ext] : null; };
  check('238U takes its own: 4.5e-8 Sv/Bq on ingestion, 9.2e-22 external', dcc('U-238'), ['U-238', 4.5e-8, 9.2e-22]);
  check('an isomer takes the ICRP 107 isomer with its half-life: 178m2Hf is Hf-178m, 192m2Ir is Ir-192n', [dcc('Hf-178m2')[0], dcc('Ir-192m2')[0]], ['Hf-178m', 'Ir-192n']);
  check('ICRP 107 calls 178Ta\'s 2.36 h state the isomer; ENSDF its ground state, which takes those coefficients', dcc('Ta-178')[0], 'Ta-178m');
  check('a state that ICRP 107 does not have takes none (209Bi, 212m1Bi)', [dcc('Bi-209'), dcc('Bi-212m1')], [null, null]);
}

/* ── Every chain, at two settings ───────────────────────────────────── */
for (const opt of [{}, { life: '1y', minBranch: '1e-6' }]) {
  const t0 = Date.now();
  let chains = 0, missingEnds = 0, shares = 0, energies = 0, touching = 0, years = 0, rooted = 0, cut = 0;
  const examples = [];
  for (const name of db.states.keys()) {
    const made = R.chain(db, name, opt);
    chains++;
    if (made.root && made.root.name === name) rooted++;
    if (made.truncated) cut++;
    const recs = made.records;
    /* The shares the page's decay moves, against ensdf-core's system. */
    const sys = C.decaySystem(made.chain);
    const at = new Map();
    sys.members.forEach((nd, i) => { if (nd.kind !== 'fission') at.set(R.nameOf(nd.z, nd.a, nd.k, nd.nuc), i); });
    const want = new Map();
    sys.rows.forEach((row, i) => {
      if (sys.members[i].kind === 'fission') return;
      for (const [j, f] of row) { const k = `${j}>${i}`; want.set(k, (want.get(k) || 0) + f); }
    });
    const got = new Map();
    for (const r of recs.values()) {
      /* What does not decay moves nothing: a stable member, one with no half-life. */
      if (!(r.Halflife_y > 0)) continue;
      for (const p of r.Progenies) {
        if (p.name === 'SF') continue;
        if (!recs.has(p.name)) { missingEnds++; continue; }
        const k = `${at.get(r.name)}>${at.get(p.name)}`;
        got.set(k, (got.get(k) || 0) + p.br);
      }
    }
    for (const [k, f] of want) if (Math.abs((got.get(k) || 0) - f) > 1e-12) { shares++; if (examples.length < 5) examples.push(`${name} ${k} ${got.get(k)} ${f}`); }
    for (const [k, f] of got) if (f > 0 && !want.has(k)) { shares++; if (examples.length < 5) examples.push(`${name} extra ${k} ${f}`); }
    for (const nd of made.chain.nodes) {
      if (nd.kind !== 'state' || !nd.st || nd.st.st) continue;
      const r = recs.get(R.nameOf(nd.z, nd.a, nd.k, nd.nuc));
      const em = C.chainEmission(db.idx, nd).v;
      if (Math.abs(r.Alpha_energy - em[0]) + Math.abs(r.Electron_energy - em[1]) + Math.abs(r.Photon_energy - em[2]) > 1e-12) energies++;
      if (nd.st.ts > 0 && Math.abs(r.Halflife_y * R.YEAR - nd.st.ts) > 1e-9 * nd.st.ts) years++;
    }
    const ps = [...recs.values()].map((r) => r.pos);
    for (let i = 0; i < ps.length; i++) for (let j = i + 1; j < ps.length; j++) if (Math.hypot(ps[i].x - ps[j].x, ps[i].y - ps[j].y) < R.SERIES.d) touching++;
  }
  const what = opt.life ? 'members under a year left out, branches under 1e-6 % too' : 'the default settings';
  console.log(`      ${chains} chains at ${what} in ${((Date.now() - t0) / 1000).toFixed(1)} s, ${cut} cut short`);
  check(`${what}: every chain starts from its own record`, rooted, chains);
  check(`${what}: every arrow ends at a member of the chain, or in fission`, missingEnds, 0);
  check(`${what}: the arrows move the shares ensdf-core.js's decay system moves`, [shares, examples], [0, []]);
  check(`${what}: the energies per decay are chainEmission()'s, the half-lives the file's`, [energies, years], [0, 0]);
  check(`${what}: no two circles of a chain touch`, touching, 0);
}

console.log(`\n${pass} of ${pass + fail} checks pass`);
process.exit(fail ? 1 : 0);
