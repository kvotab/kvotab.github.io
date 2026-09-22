#!/usr/bin/env node
/*
  ensdf.html: the reader, the chain and the release on the site.

      node resources/tests/ensdf/test-parse.js

  Four parts:

    1. Field reading: NUCIDs, numbers, uncertainties, half-lives, level
       energies, continuation fields, decay modes, XREF -- each against what
       the ENSDF manual says the record means.
    2. A small hand-made data set with an isomer, a decay that feeds it
       through a cascade, and a level beside the isomer that the XREF says is
       not it: the case 212Pb/212Bi taught.
    3. fixture/ensdf.003 (A = 3 from the 2026-09-01 release) read end to end.
    4. The release under resources/data/ensdf/: the isomer feedings that are
       known well (234Th, 99Mo, 137Cs, 239Pu), whole decay chains, and a
       cross-check of every branch against the ICRP Publication 107 data in
       resources/js/rndecaydata.js.

  Exit status 0 when every check passes.
*/
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..', '..');
const P = require(path.join(ROOT, 'resources/js/ensdf-parse.js'));
const C = require(path.join(ROOT, 'resources/js/ensdf-core.js'));

let checks = 0;
const failures = [];
function check(label, got, want) {
  checks++;
  const ok = typeof want === 'function' ? want(got) : JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failures.push(label);
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok ? '' : `: ${JSON.stringify(got)}${typeof want === 'function' ? '' : ` (expected ${JSON.stringify(want)})`}`}`);
}
const near = (x, tol) => (v) => Math.abs(v - x) <= tol;

/* ---------------------------------------------------------------- 1 */
check('NUCID 60CO', P.parseNucid(' 60CO'), { a: 60, z: 27 });
check('NUCID of the neutron', P.parseNucid('  1NN'), { a: 1, z: 0 });
check('NUCID with Z - 100 in the element columns', P.parseNucid('29820'), { a: 298, z: 120 });
check('NUCID of a mass chain is not a nuclide', P.parseNucid(' 60  '), null);
check('number in parentheses (deduced) keeps its value', P.num('(198)'), 198);
check('0+X is not a number', P.num('0+X'), NaN);
check('uncertainty in the last digits', P.uncertainty('2822.81', '21').abs, near(0.21, 1e-12));
check('uncertainty of an exponent value', P.uncertainty('1.51E+6', '4').abs, near(0.04e6, 1e-6));
check('asymmetric uncertainty', P.uncertainty('0.28', '+21-14'), (u) => Math.abs(u.plus - 0.21) < 1e-12 && Math.abs(u.minus - 0.14) < 1e-12);
check('qualifier uncertainty', P.uncertainty('35', 'LT'), { q: 'LT' });
check('half-life in days', P.halfLife('1925.28 D').s, near(1925.28 * 86400, 1e-6));
check('half-life with a lower-case unit', P.halfLife('15.2 min').s, near(912, 1e-9));
check('STABLE', P.halfLife('STABLE'), (h) => h.stable && h.s === Infinity);
check('a width becomes a half-life', P.halfLife('92 KEV'), (h) => h.width && Math.abs(h.s - 6.582119569e-16 * Math.LN2 / 92e3) < 1e-30);
check('? is no half-life', P.halfLife('?').s, null);
check('level energy 0+X', P.levelEnergy('0+X'), { n: 0, x: 'X' });
check('level energy SN+120', P.levelEnergy('SN+120'), { n: 120, x: 'SN' });
check('level energy X alone', P.levelEnergy('X'), { n: 0, x: 'X' });
const modes = (t) => P.contFields(t).map(P.modeFromField).filter(Boolean);
check('%B-=100', modes('%B-=100'), [['B-', '=', '100', '']]);
check('%EC+%B+ with a reference', modes('%EC+%B+=56.3 20 (1977JA04)$%B- EQ 43.7 20 (1977JA04)'), [['EC+B+', '=', '56.3', '20'], ['B-', '=', '43.7', '20']]);
check('%A<1.0E-4 and %IT AP 10', modes('%A<1.0E-4 $ %IT AP 10'), [['A', '<', '1.0E-4', ''], ['IT', 'AP', '10', '']]);
check('%SF=? has no percentage', modes('%SF=?'), [['SF', '=', '?', '']]);
check('moments beside the modes are not modes', modes('MOMM1=+3.799 8 $ MOME2=+0.44 5 $ %B-=100'), [['B-', '=', '100', '']]);
const shift = (m) => { const s = P.modeShift(m); return s && [s.dz, s.dn, s.fission]; };
check('beta-minus shift', shift('B-'), [1, -1, false]);
check('beta-delayed two-neutron shift', shift('B-2N'), [1, -3, false]);
check('beta-delayed alpha shift', shift('B-A'), [-1, -3, false]);
check('EC-delayed proton shift', shift('ECP'), [-2, 1, false]);
check('EC+B+ shift', shift('EC+B+'), [-1, 1, false]);
check('alpha shift', shift('A'), [-2, -2, false]);
check('14C cluster shift', shift('14C'), [-6, -8, false]);
check('34Si cluster shift', shift('34SI'), [-14, -20, false]);
check('fission has no daughter', shift('SF'), [0, 0, true]);
check('double beta-minus', shift('2B-'), [2, -2, false]);
const pcts = (list) => P.branchesOf(list).map((b) => [b.mode, b.pct]);
check('delayed neutrons come out of the beta branch', pcts([['B-', '=', '100', ''], ['B-N', '=', '86.3', ''], ['B-2N', '=', '4.1', '']]).map(([m, p]) => [m, +p.toFixed(6)]), [['B-', 9.6], ['B-N', 86.3], ['B-2N', 4.1]]);
check('%EC and %B+ given apart are one branch', pcts([['EC', '=', '60', ''], ['B+', '=', '40', '']]), [['EC+B+', 100]]);
check('%EC beside %EC+%B+ is not counted twice', pcts([['EC+B+', '=', '100', ''], ['B+', '=', '90', ''], ['ECP', '=', '1', '']]), [['EC+B+', 99], ['ECP', 1]]);
check('XREF letters', [...P.parseXref('ABC').items.keys()], ['A', 'B', 'C']);
check('XREF with an energy', P.parseXref('A(238.6)B').items.get('A'), '238.6');
check('XREF + means every data set', P.parseXref('+').all, true);
check('XREF -(AB) excludes', [...P.parseXref('-(AB)').except], ['A', 'B']);
check('NDS pair 99.9826(6)', P.ndsPair(99.9826, 0.0006), ['99.9826', '6']);
check('NDS pair keeps two digits up to 25', P.ndsPair(2.13, 0.20), ['2.13', '20']);
check('NDS pair rounds 28 to 3', P.ndsPair(0.1188, 0.028), ['0.12', '3']);

/* ---------------------------------------------------------------- 2 */
/* Records built column by column, as the manual lays them out. */
function rec(nucid, fields) {
  const line = new Array(80).fill(' ');
  const put = (col, text) => { for (let i = 0; i < text.length; i++) line[col - 1 + i] = text[i]; };
  put(1, nucid.padStart(5, ' ').slice(0, 5));
  for (const [col, text] of fields) put(col, text);
  return line.join('');
}
const L = (nucid, e, j, t, dt, ms) => rec(nucid, [[8, 'L'], [10, e], [22, j || ''], [40, t || ''], [50, dt || ''], [78, ms || '']]);
const G = (nucid, e, ri, cc, fl) => rec(nucid, [[8, 'G'], [10, e], [22, ri || ''], [56, cc || '']]);
const text = [
  /* The parent, 100XX in this toy: ground state decays by beta-minus. */
  rec('100RU', [[10, 'ADOPTED LEVELS']]),
  L('100RU', '0.0', '0+', '10 D', '1'),
  rec('100RU', [[6, '2'], [8, 'L'], [10, '%B-=100']]),
  '',
  /* The daughter: an isomer at 100 keV, and a picosecond level at 100.4 keV
     that the XREF says was seen only in a reaction (B), not in the decay (A). */
  rec('100RH', [[10, 'ADOPTED LEVELS, GAMMAS']]),
  rec('100RH', [[8, 'X'], [9, 'A'], [10, '100RU B- DECAY']]),
  rec('100RH', [[8, 'X'], [9, 'B'], [10, '99RU(P,G)']]),
  L('100RH', '0.0', '1-', '20 H', '1'),
  rec('100RH', [[6, '2'], [8, 'L'], [10, '%EC+%B+=100']]),
  L('100RH', '100.0', '5+', '5 M', '1', 'M1'),
  rec('100RH', [[6, 'X'], [8, 'L'], [10, 'XREF=B']]),
  rec('100RH', [[6, '2'], [8, 'L'], [10, '%IT=100']]),
  G('100RH', '100.0', '100', '5.0'),
  L('100RH', '300.0', '2-'),
  rec('100RH', [[6, 'X'], [8, 'L'], [10, 'XREF=AB']]),
  G('100RH', '300.0', '100'),
  '',
  /* The decay data set: feeds 300 keV (60) and 100.4 keV (40) directly. The
     300 keV level sends 3/4 of its flux to 100.4 and 1/4 to the ground state.
     Were 100.4 taken for the isomer, 40 + 60 x 3/4 = 85 % would land there;
     it is not the isomer, so everything reaches the ground state. */
  rec('100RH', [[10, '100RU B- DECAY']]),
  rec('100RU', [[8, 'P'], [10, '0.0'], [22, '0+'], [40, '10 D'], [65, '3000']]),
  rec('100RH', [[8, 'N'], [10, '1.0'], [32, '1.0'], [42, '1.0']]),
  L('100RH', '0.0', '1-'),
  L('100RH', '100.4'),
  rec('100RH', [[8, 'B'], [22, '40']]),
  G('100RH', '100.4', '10'),
  L('100RH', '300.0', '2-'),
  rec('100RH', [[8, 'B'], [22, '60']]),
  G('100RH', '199.6', '75'),
  G('100RH', '300.0', '25'),
  '',
].join('\n');
{
  const b = P.createBuilder();
  b.addText(text);
  const { summary } = b.finish({});
  const ru = summary.nuclides.find((n) => n.z === 44 && n.a === 100);
  const rh = summary.nuclides.find((n) => n.z === 45 && n.a === 100);
  check('toy: the isomer is a state of the daughter', rh.s.length, 2);
  check('toy: the XREF keeps a neighbouring level from being taken for the isomer', ru.s[0].br, [['B-', 100, [[45, 100, 0, 1]]]]);

  /* The same set, but with the neighbouring level named in the isomer's XREF:
     now it is the isomer, and the cascade puts 40 + 60 x 0.75 = 85 % there. */
  const b2 = P.createBuilder();
  b2.addText(text.replace(`${rec('100RH', [[6, 'X'], [8, 'L'], [10, 'XREF=B']])}`, `${rec('100RH', [[6, 'X'], [8, 'L'], [10, 'XREF=A(100.4)B']])}`));
  const ru2 = b2.finish({}).summary.nuclides.find((n) => n.z === 44 && n.a === 100);
  const to = new Map(ru2.s[0].br[0][2].map(([z, a, k, f]) => [k, f]));
  check('toy: the cascade shares flux by transition intensity', [+(to.get(1) || 0).toFixed(6), +(to.get(0) || 0).toFixed(6)], [0.85, 0.15]);
}

/* ---------------------------------------------------------------- 3 */
{
  const b = P.createBuilder();
  b.addText(fs.readFileSync(path.join(__dirname, 'fixture', 'ensdf.003'), 'latin1'));
  const { summary, details } = b.finish({});
  const h3 = summary.nuclides.find((n) => n.z === 1 && n.a === 3);
  check('A=3: tritium half-life', h3.s[0].t, '12.32 Y');
  check('A=3: tritium decays to 3He', h3.s[0].br, [['B-', 100, [[2, 3, 0, 1]]]]);
  check('A=3: tritium Q(beta-) as the file gives it', [h3.q[0], h3.q[1]], ['18.5906', '32']);
  const he3 = summary.nuclides.find((n) => n.z === 2 && n.a === 3);
  check('A=3: 3He is stable', !!he3.s[0].st, true);
  const rad = details.get(3).nuc[1].rad;
  check('A=3: the beta spectrum of tritium is in its radiation', rad && rad[0].b && rad[0].b[0][2], '5.6817');
  check('A=3: nuclides searched for and not seen are counted apart', summary.release.unobserved >= 1, true);
}

/* ---------------------------------------------------------------- 4 */
const dataDir = path.join(ROOT, 'resources/data/ensdf');
global.KVOT_ENSDF_DATA = (id, part, payload) => { global.__lastData = payload; };
const loadData = (file) => { new Function(fs.readFileSync(file, 'utf8'))(); return global.__lastData; };
const releases = loadData(path.join(dataDir, 'releases.js'));
check('a release is installed', releases.length >= 1, true);
const summary = loadData(path.join(dataDir, releases[0].id, 'summary.js'));
const idx = C.index(summary);
console.log(`\n${releases[0].label}: ${summary.release.nuclides} nuclides`);
check('the release has the whole chart', summary.release.nuclides > 3300, true);

const feed = (sym, a, k, dz, da) => {
  const z = C.ELEMENTS.findIndex(([s]) => s === sym);
  const st = idx.get(z, a).s[k];
  const out = {};
  for (const [, pct, ds] of st.br) for (const [z2, a2, k2, f] of ds) if (z2 === z + dz && a2 === a + da) out[k2] = (out[k2] || 0) + pct * f;
  return out;
};
check('234Th feeds 234mPa', feed('Th', 234, 0, 1, 0)[1], near(99.85, 0.1));
check('99Mo feeds 99mTc', feed('Mo', 99, 0, 1, 0)[1], near(87.6, 0.3));
check('137Cs feeds 137mBa', feed('Cs', 137, 0, 1, 0)[1], near(94.7, 0.2));
check('239Pu feeds 235mU', feed('Pu', 239, 0, -2, -4)[1], near(99.9, 0.1));
check('212Pb feeds the ground state of 212Bi, not its 25 min isomer', feed('Pb', 212, 0, 1, 0), { 0: 100 });
check('the 11 s isomer of 126Sb goes by IT to the 19 min one', idx.get(51, 126).s[2].br, (br) => br[0][0] === 'IT' && br[0][2][0][2] === 1);
check('90mY is a state though it carries no flag', idx.get(39, 90).s.length > 1 && idx.get(39, 90).s[1].e === '682.01', true);
check('127Te has an inferred beta-minus branch', idx.get(52, 127).s[0].br, (br) => br.length === 1 && br[0][0] === 'B-' && br[0][3] === 1);
check('a nuclide not observed is hidden', idx.get(2, 18).hidden, true);

const ends = (sym, a) => {
  const z = C.ELEMENTS.findIndex(([s]) => s === sym);
  const ch = C.buildChain(idx, z, a, 0, { minIsomerS: 1 });
  const out = {};
  for (const n of ch.nodes) if (n.st && n.st.st) out[`${n.a}${C.ELEMENTS[n.z][0]}`] = +(n.cum * 100).toPrecision(6);
  return { ends: out, members: ch.nodes.map((n) => n.kind === 'fission' ? 'SF' : C.name(n.z, n.a, n.k, n.nuc).text) };
};
const u238 = ends('U', 238);
/* All but the fission branches (5.45e-5 % from 238U itself) and the rare cluster decays. */
check('238U series ends in 206Pb', u238.ends['206Pb'], near(100, 1e-3));
check('238U series passes through 234mPa, 226Ra, 222Rn and 210Po', ['234mPa', '226Ra', '222Rn', '210Po'].every((m) => u238.members.includes(m)), true);
check('232Th series ends in 208Pb', ends('Th', 232).ends['208Pb'], near(100, 1e-4));
check('235U series ends in 207Pb', ends('U', 235).ends['207Pb'], near(100, 1e-3));
check('137Cs ends in 137Ba through 137mBa', ends('Cs', 137), (r) => r.members.join(' ') === '137Cs 137mBa 137Ba' && r.ends['137Ba'] === 100);

/* The half-life filter: a member shorter than the threshold -- nuclide or
   isomer (minHalfLifeS), or isomers alone (minIsomerS) -- is left out and
   the chain goes straight on: every branch it has is followed from the
   state that fed it. What went through an isomer's IT joins the arrow to the
   same nuclide (listed here as "(through ...)"); anything else is an arrow
   "via" the likeliest route's left-out members. */
const members = (sym, a, opt) => {
  const z = C.ELEMENTS.findIndex(([s]) => s === sym);
  return C.buildChain(idx, z, a, 0, opt).nodes.map((n) => C.name(n.z, n.a, n.k, n.nuc).text).join(' ');
};
const routes = (sym, a, opt) => {
  const z = C.ELEMENTS.findIndex(([s]) => s === sym);
  const ch = C.buildChain(idx, z, a, 0, opt);
  const out = {};
  for (const e of ch.root.out) {
    const to = e.to.kind === 'fission' ? 'SF' : C.name(e.to.z, e.to.a, e.to.k, e.to.nuc).text;
    out[`${to}${e.via.length ? ' via ' + e.via.map((x) => C.asciiText(x.name)).join(',') : ''}`] = +e.pct.toPrecision(4);
    if (!e.via.length && e.skipped.length) out[`${to} (through ${e.skipped.map((x) => C.asciiText(x.name)).join(',')})`] = +e.skippedPct.toPrecision(4);
  }
  return out;
};
check('isomers >= 1 h: 137Cs goes to 137Ba by one arrow, 94.7 % of it through 137mBa', routes('Cs', 137, { minIsomerS: 3600 }), { '137Ba': 100, '137Ba (through 137mBa)': 94.7 });
check('isomers >= 1 y: 99mTc is shortcut, beta-minus branch and all', routes('Mo', 99, { minIsomerS: C.YEAR_S }), { '99Tc': 100, '99Tc (through 99mTc)': 87.64, '99Ru via 99mTc': 0.003243 });
check('... and it is no longer a member', members('Mo', 99, { minIsomerS: C.YEAR_S }), '99Mo 99Tc 99Ru');
check('isomers >= 1 h: 234Th -> 234U 99.69 % via 234mPa, 234Pa directly and through its IT', routes('Th', 234, { minIsomerS: 3600 }), { '234Pa': 0.3101, '234Pa (through 234mPa)': 0.1598, '234U via 234mPa': 99.69 });
check('with no threshold 234mPa is drawn', members('Th', 234, {}).includes('234mPa'), true);
check('a branch of a left-out isomer below the smallest branch is left out too', routes('Mo', 99, { minIsomerS: C.YEAR_S, minBranch: 0.1 })['99Ru via 99mTc'], undefined);
check('members >= 1 y: 238U goes to 234U via 234Th and 234mPa', routes('U', 238, { minHalfLifeS: C.YEAR_S }), { SF: 5.45e-5, '234U via 234Th,234mPa': 100 });
check('... 226Ra to 210Pb via 222Rn to 214Po', routes('Ra', 226, { minHalfLifeS: C.YEAR_S })['210Pb via 222Rn,218Po,214Pb,214Bi,214Po'], 100);
check('... 210Pb to 206Pb via 210Bi and 210Po', routes('Pb', 210, { minHalfLifeS: C.YEAR_S }), { '206Pb via 210Bi,210Po': 100 });
{
  const ch = C.buildChain(idx, 92, 238, 0, { minHalfLifeS: C.YEAR_S });
  check('... and no member but the start lives less than a year', ch.nodes.filter((n) => n !== ch.root && n.st && !n.st.st && !(n.st.ts >= C.YEAR_S)).length, 0);
  check('... while 206Pb still takes all the decays', ch.nodes.find((n) => n.key === '82,206,0').cum * 100, near(100, 1e-3));
}
check('the start stays however short it lives: 218Po (3 min) to 210Pb at 1 y', routes('Po', 218, { minHalfLifeS: C.YEAR_S })['210Pb via 214Pb,214Bi,214Po'], 100);
{
  /* 131mSn's IT has no percentage: the arrow keeps what is known and says it may be more. */
  const ch = C.buildChain(idx, 49, 131, 0, { minIsomerS: 60 });
  const e = ch.root.out.find((x) => x.to.key === '50,131,0' && !x.via.length);
  check('a branch with no percentage on the way leaves the known part: 131In -> 131Sn at least 81.5 %', [+e.pct.toPrecision(3), e.more], [81.5, true]);
  const pd = C.buildChain(idx, 46, 131, 0, { minHalfLifeS: C.YEAR_S }).root.out.find((x) => x.to.key === '54,131,0');
  check('... so 131Pd reaches 131Xe at 1 y by a known share, not "?"', pd.pct > 90 && pd.more, true);
}
{
  /* Worked out once per left-out state, not route by route. */
  const t0 = Date.now();
  for (const n of idx.list) if (!n.hidden && n.s.length && !n.s[0].st) C.buildChain(idx, n.z, n.a, 0, { minHalfLifeS: 1000 * C.YEAR_S });
  check('every chain at 1000 y in under 5 s', Date.now() - t0, (ms) => ms < 5000);
}
check('superscript runs', C.supRuns('²³⁸U 4.5×10⁻⁹ y').map((r) => (r.sup ? `^${r.t}` : r.t)).join(''), '^238U 4.5×10^−9 y');
check('plain text for a <select>', C.asciiText('²³⁸U · 5.45×10⁻⁵ %'), '238U · 5.45E-5 %');

check('names: 99mTc from "99mTc"', C.parseQuery('99mTc'), { z: 43, a: 99, iso: 'm' });
check('names: "99Mo" is molybdenum, not an isomer of oxygen', C.parseQuery('99Mo'), { z: 42, a: 99, iso: '' });
check('names: Tc-99m, cobalt-60, 178m2Hf', [C.parseQuery('Tc-99m').a, C.parseQuery('cobalt-60').z, C.parseQuery('178m2Hf').iso], [99, 27, 'm2']);
check('names: a lone isomer is m even when flagged M1', C.name(91, 234, 1, idx.get(91, 234)).text, '234mPa');
check('names: 178m2Hf', C.name(72, 178, 2, idx.get(72, 178)).text, '178m2Hf');
check('percent: 5.45e-5', C.pctText(5.45e-5), '5.45×10⁻⁵ %');
check('percent: 0.0037', C.pctText(0.0037), '0.0037 %');

/* The ICRP 107 cross-check, as the page's About tab states it: isomers under
   a minute that only decay by IT passed through, as ICRP does. */
{
  const src = fs.readFileSync(path.join(ROOT, 'resources/js/rndecaydata.js'), 'utf8');
  const decaydata = new Function(src + '; return decaydata;')();
  const symZ = {};
  C.ELEMENTS.forEach(([s], z) => { symZ[s] = z; });
  const Y = C.YEAR_S;
  const parse = (nm) => { const m = /^([A-Za-z]+)-(\d+)(m|n)?$/.exec(nm); return m ? { z: symZ[m[1]], a: +m[2], iso: !!m[3] } : null; };
  const stateFor = (n, iso, t) => {
    if (!iso) return 0;
    let best = -1, bd = Infinity;
    n.s.forEach((s, k) => { if (k && s.ts) { const d = Math.abs(Math.log10(s.ts / t)); if (d < bd) { bd = d; best = k; } } });
    return bd < 0.2 ? best : -1;
  };
  const byName = new Map(decaydata.map((d) => [d.name, d]));
  let agree = 0, total = 0;
  for (const d of decaydata) {
    const p = parse(d.name);
    const n = p && idx.get(p.z, p.a);
    if (!n || !n.s.length) continue;
    const k = stateFor(n, p.iso, d.Halflife_y * Y);
    if (k < 0) continue;
    total++;
    const ch = C.buildChain(idx, p.z, p.a, k, { minIsomerS: 60, maxNodes: 1e4 });
    const ens = new Map();
    for (const e of ch.root.out) {
      if (e.pct === null) continue;
      const key = e.to.kind === 'fission' ? 'SF' : `${e.to.z},${e.to.a},${e.to.k}`;
      ens.set(key, (ens.get(key) || 0) + e.pct / 100);
    }
    const icrp = new Map();
    for (const pr of d.Progenies || []) {
      let key = 'SF';
      if (pr.name !== 'SF') {
        const q = parse(pr.name);
        const dn = idx.get(q.z, q.a), dd = byName.get(pr.name);
        key = `${q.z},${q.a},${q.iso ? (dn && dd ? stateFor(dn, true, dd.Halflife_y * Y) : -9) : 0}`;
      }
      icrp.set(key, (icrp.get(key) || 0) + pr.br);
    }
    const ok = [...new Set([...ens.keys(), ...icrp.keys()])].every((key) => {
      const x = ens.get(key) || 0, y = icrp.get(key) || 0;
      return Math.abs(x - y) <= 0.02 || Math.abs(x - y) <= 0.1 * Math.max(x, y);
    });
    if (ok) agree++;
  }
  console.log(`ICRP 107: ${agree} of ${total} nuclides agree`);
  check('ICRP 107: at least 1460 of the 1508 nuclides give the same branches', agree >= 1460 && total >= 1500, true);
}

console.log(`\n${checks - failures.length} of ${checks} checks pass`);
if (failures.length) { console.log('failed:\n  ' + failures.join('\n  ')); process.exit(1); }
