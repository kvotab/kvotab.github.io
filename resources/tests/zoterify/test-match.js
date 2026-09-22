#!/usr/bin/env node
/* zoterify-match.js: similarity, and what a reference is matched to.

   A small library written out here, and references as the parser returns
   them, with the result each must get -- matched, ambiguous, year,
   possible, none -- and the item.

       node resources/tests/zoterify/test-match.js

   The thresholds themselves were calibrated on 758 references whose true
   items are known; that evaluation needs documents that are not part of
   the site and is described in README.md.

   Exit status is 0 when every check passes. */
'use strict';

const M = require('../../js/zoterify-match.js');
const P = require('../../js/zoterify-parse.js');

let checks = 0;
const failures = [];
function check(label, got, want) {
  checks++;
  const a = JSON.stringify(got);
  const b = JSON.stringify(want);
  if (a !== b) failures.push(`${label}\n     got  ${a}\n     want ${b}`);
}

/* ---- Jaro–Winkler, against the values in Winkler's papers ---------------- */
const jw = (a, b) => Math.round(M.jaroWinkler(a, b) * 1000) / 1000;
check('MARTHA / MARHTA', jw('MARTHA', 'MARHTA'), 0.961);
check('DWAYNE / DUANE', jw('DWAYNE', 'DUANE'), 0.84);
check('DIXON / DICKSONX', jw('DIXON', 'DICKSONX'), 0.813);
check('identical', M.jaroWinkler('smith', 'smith'), 1);
check('nothing in common', M.jaroWinkler('abc', 'xyz'), 0);
check('an organisation with and without "AB"', M.nameSimilarity('svensk karnbranslehantering ab', 'svensk karnbranslehantering'), 0.97);

/* ---- the library ------------------------------------------------------------ */
let id = 0;
const item = (key, authors, year, title, extra = {}) => Object.assign({ key, itemId: ++id, libraryId: 1, authors, editors: [], year, title, uri: `u/${key}`, csl: {} }, extra);
const LIB = [
  item('SMITH20', ['Smith'], '2020', 'Buffer erosion in dilute groundwater'),
  item('SMYTH20', ['Smyth'], '2020', 'Something else entirely'),
  item('JONES20A', ['Jones'], '2020', 'Sulphide transport in fractured rock'),
  item('JONES20B', ['Jones'], '2020', 'Copper corrosion under reducing conditions'),
  item('BROWN19', ['Brown', 'Green'], '2019', 'Groundwater flow at Forsmark'),
  item('OHMAN14', ['Öhman', 'Odén', 'Vidstrand'], '2014', 'Hydrogeological modelling of SFR'),
  item('IPCC22', ['Intergovernmental Panel on Climate Change'], '2022', 'Climate change 2022: impacts'),
  item('SKB10', ['SKB'], '2010', 'Long-term safety for the final repository'),
  item('BERG19', ['van der Berg'], '2019', 'Particles in names'),
  item('ANON', ['Anonymous'], '', 'An undated leaflet'),
  item('EDIT05', [], '2005', 'An edited volume', { editors: ['Eriksson'] }),
];
const ref = (authors, yearKey, extra = {}) => Object.assign({ authors, aliases: [], etAl: false, yearKey, letter: '', num: null, entry: null }, extra);
const result = (m, r) => { const x = m.match(r); return [x.status, x.item ? x.item.key : null, x.candidates.map((c) => c.item.key)]; };

const balanced = M.createMatcher(LIB, { level: 'balanced', yearTolerance: 1 });
check('an exact name and year', result(balanced, ref(['Smith'], '2020')), ['matched', 'SMITH20', ['SMITH20']]);
check('accents do not matter', result(balanced, ref(['Ohman'], '2014', { etAl: true })), ['matched', 'OHMAN14', ['OHMAN14']]);
check('particles do not matter', result(balanced, ref(['Berg'], '2019')), ['matched', 'BERG19', ['BERG19']]);
check('two authors', result(balanced, ref(['Brown', 'Green'], '2019')), ['matched', 'BROWN19', ['BROWN19']]);
check('one of two authors cited', result(balanced, ref(['Brown'], '2019')), ['matched', 'BROWN19', ['BROWN19']]);
check('an editor stands in for authors', result(balanced, ref(['Eriksson'], '2005')), ['matched', 'EDIT05', ['EDIT05']]);
check('an acronym for an organisation', result(balanced, ref(['IPCC'], '2022')), ['matched', 'IPCC22', ['IPCC22']]);
check('an organisation with its acronym given', result(balanced, ref(['Intergovernmental Panel on Climate Change'], '2022', { aliases: ['IPCC'] })), ['matched', 'IPCC22', ['IPCC22']]);
check('two items fit: ambiguous', result(balanced, ref(['Jones'], '2020')), ['ambiguous', 'JONES20A', ['JONES20A', 'JONES20B']]);
check('the reference list entry names one: matched to it',
  result(balanced, ref(['Jones'], '2020', { entry: { authors: ['Jones'], text: 'Jones A, 2020. Copper corrosion under reducing conditions. Corrosion Science 5.' } })),
  ['matched', 'JONES20B', ['JONES20B', 'JONES20A']]);
check('... and says so', balanced.match(ref(['Jones'], '2020', { entry: { authors: ['Jones'], text: 'Jones A, 2020. Copper corrosion under reducing conditions.' } })).entryConfirmed, true);
check('a year off: offered', result(balanced, ref(['Smith'], '2021')), ['year', 'SMITH20', ['SMITH20']]);
check('two years off, with tolerance 1: looser fits, near names too', result(balanced, ref(['Smith'], '2022')), ['possible', null, ['SMITH20', 'SMYTH20']]);
check('a year off, with tolerance 0: looser fits', result(M.createMatcher(LIB, { yearTolerance: 0 }), ref(['Smith'], '2021')), ['possible', null, ['SMITH20', 'SMYTH20']]);
check('"n.d." fits an undated item', result(balanced, ref(['Anonymous'], 'nd')), ['matched', 'ANON', ['ANON']]);
check('"et al." does not fit a single author', result(balanced, ref(['Smith'], '2020', { etAl: true })), ['none', null, []]);
check('nothing near', result(balanced, ref(['Zzyzx'], '1999')), ['none', null, []]);
check('a numbered reference, through its entry',
  result(balanced, ref([], '', { num: 3, entry: { authors: ['Brown', 'Green'], yearKey: '2019', letter: '', text: '3. Brown P, Green Q. Groundwater flow at Forsmark. 2019.' } })),
  ['matched', 'BROWN19', ['BROWN19']]);
check('a numbered reference without an entry', result(balanced, ref([], '', { num: 4 })), ['none', null, []]);

// Smyth is 0.89 like Smith: a fit when lenient, not when balanced -- and
// either way Smith, the exact name, wins.
const lenient = M.createMatcher(LIB, { level: 'lenient' });
check('lenient also lets Smyth fit, but Smith is clearly best', result(lenient, ref(['Smith'], '2020')), ['matched', 'SMITH20', ['SMITH20', 'SMYTH20']]);
check('balanced does not count Smyth as a fit for Smith', result(balanced, ref(['Smith'], '2020'))[2], ['SMITH20']);
check('"Smath" (0.89 like Smith) is a fit when lenient', result(lenient, ref(['Smath'], '2020'))[0], 'ambiguous');
check('... only possible when strict', result(M.createMatcher(LIB, { level: 'strict' }), ref(['Smath'], '2020'))[0], 'possible');

/* ---- with the parser -------------------------------------------------------- */
{
  const doc = P.parseDocument([
    { text: 'Erosion (Smith, 2020; Öhman et al. 2014) and as Brown and Green (2019, p. 4) showed.', story: 'body' },
  ]);
  check('parsed references match as they should', doc.refs.map((r) => balanced.match(r)).map((x) => [x.ref.label, x.status, x.item && x.item.key]),
    [['Smith 2020', 'matched', 'SMITH20'], ['Öhman et al. 2014', 'matched', 'OHMAN14'], ['Brown & Green 2019', 'matched', 'BROWN19']]);
}

/* ---- SKB's report numbers, designations and abbreviated names ---------------- */
const SKB_ = { publisher: 'Svensk Kärnbränslehantering AB' };
const LIB2 = [
  item('SR11', ['SKB'], '2011', 'Long-term safety for the final repository for spent nuclear fuel at Forsmark', { csl: { number: 'SKB TR-11-01' } }),
  item('R1105', ['SKB'], '2011', 'Groundwater chemistry at the repository depth', { csl: Object.assign({ number: 'R-11-05' }, SKB_) }),
  item('SKBX11', ['SKB'], '2011', 'A report of 2011 entered without its number'),
  item('DATA10', ['SKB'], '2010', 'Data report for the safety assessment SR-Site', { csl: { number: 'SKB TR-10-52' } }),
  item('CLIM10', ['SKB'], '2010', 'Climate and climate-related issues for the safety assessment SR-Site'),
  item('POS12', ['Posiva'], '2012', 'Olkiluoto site description', { csl: { number: 'Posiva TR-12-01' } }),
  item('SSM0821', ['Strålsäkerhetsmyndigheten'], '2008', 'Strålsäkerhetsmyndighetens föreskrifter om säkerhet i kärntekniska anläggningar', { csl: { number: 'SSMFS 2008:21' } }),
  item('SSMFS12', ['SSMFS'], '2008', 'Föreskrifter om fysiskt skydd av kärntekniska anläggningar', { csl: { number: 'SSMFS 2008:12' } }),
  item('SKIFS95', ['SKI'], '1995', 'SKIFS 1995:1 Statens kärnkraftinspektions föreskrifter'),
  item('SKI0812', ['Smith'], '2008', 'Review of canister corrosion', { csl: { number: 'SKI Report 2008:12' } }),
  item('VALLC01', ['Vallery'], '2001', 'Clay in columns', { csl: { author: [{ family: 'Vallery', given: 'Claire' }] } }),
  item('VALLM01', ['Vallery'], '2001', 'Clay in mixtures', { csl: { author: [{ family: 'Vallery', given: 'Marc' }] } }),
  item('MEMO19', ['Andersson'], '2019', 'Buffer density after installation. SKBdoc 1175208 ver 5.0'),
];
{
  const skb = M.createMatcher(LIB2, { level: 'balanced', yearTolerance: 1 });
  const first = (text) => P.findInParagraph(text)[0].refs[0];
  const how = (r) => { const x = skb.match(r); return [x.status, x.item ? x.item.key : null, x.candidates.map((c) => c.item.key)]; };
  check('a report number names its item', how(first('(SKB TR-11-01)')), ['matched', 'SR11', ['SR11']]);
  check('... and says how', skb.match(first('(SKB TR-11-01)')).by, 'report');
  check('... in running text too', how(first('Data are given in SKB TR-11-01 here.')), ['matched', 'SR11', ['SR11']]);
  check('... without "SKB" in the field when SKB published it', how(first('(SKB R-11-05)')), ['matched', 'R1105', ['R1105']]);
  check('SKB 2011 alone could be any of three', how(first('(SKB 2011)')), ['ambiguous', 'SR11', ['SR11', 'R1105', 'SKBX11']]);
  check('a number no item has: only an item without a number is offered, not other SKB reports of 2011',
    how(first('(SKB TR-11-09)')), ['possible', null, ['SKBX11']]);
  check('... with a note saying so', /TR-11-09/u.test(skb.match(first('(SKB TR-11-09)')).note), true);
  check('another organisation\'s report of the same number is not SKB\'s', how(first('(SKB TR-12-01)'))[1], null);
  check('a designation names its item', how(first('(SSMFS 2008:21)')), ['matched', 'SSM0821', ['SSM0821']]);
  check('... also written "SSMFS (2008:21)"', how(first('as in SSMFS (2008:21).')), ['matched', 'SSM0821', ['SSM0821']]);
  check('another regulation of the same year is not taken for it', how(first('(SSMFS 2008:37)')), ['none', null, []]);
  check('a designation in an item\'s title', how(first('(SKIFS 1995:1)')), ['matched', 'SKIFS95', ['SKIFS95']]);
  check('"SKI 2008:12" is "SKI Report 2008:12"', how(first('(SKI 2008:12)')), ['matched', 'SKI0812', ['SKI0812']]);
  check('an SKBdoc number in a title', how(first('(SKBdoc 1175208)')), ['matched', 'MEMO19', ['MEMO19']]);
  check('two authors of one surname, told apart by initial', [how(first('Vallery C (2001) found.'))[1], how(first('Vallery M (2001) found.'))[1]], ['VALLC01', 'VALLM01']);
  check('... and without it, a choice', how(first('Vallery (2001) found.'))[0], 'ambiguous');

  const doc = P.parseDocument([
    'Rates (Data report, Section 2) and climate (Climate report), and the safety case (SKB 2011).',
    'References', 'References with abbreviated names',
    'Data report, 2010. Data report for the safety assessment SR-Site. SKB TR-10-52, Svensk Kärnbränslehantering AB.',
    'Climate report, 2010. Climate and climate-related issues for the safety assessment SR-Site. Svensk Kärnbränslehantering AB.',
    'Other references',
    'SKB, 2011. Long-term safety for the final repository for spent nuclear fuel at Forsmark. SKB TR-11-01, Svensk Kärnbränslehantering AB.',
  ].map((text) => ({ text, story: 'body' })));
  check('abbreviated names by their entry\'s report number or title; SKB 2011 by its entry\'s number',
    doc.refs.map((r) => { const x = skb.match(r); return [r.label, x.status, x.item && x.item.key, x.by || (x.entryConfirmed ? 'title' : '')]; }),
    [['Data report', 'matched', 'DATA10', 'report'], ['Climate report', 'matched', 'CLIM10', 'title'], ['SKB 2011', 'matched', 'SR11', 'report']]);

  const odd = P.parseDocument(['Chemistry (Jones 2011) was measured.', 'References',
    'Jones A, 2011. Groundwater chemistry at the repository depth. SKB R-11-05, Svensk Kärnbränslehantering AB.',
    'Brown P, 2018. Groundwater flow at Forsmark.', 'Smith J, 2020. Buffer erosion.'].map((text) => ({ text, story: 'body' })));
  const x = skb.match(odd.refs[0]);
  check('an entry\'s number is not taken for an item by other authors', [x.status, x.item && x.item.key], ['none', null]);
  check('... and the page says why', /other authors or another year/u.test(x.note || ''), true);
}

/* ---- picking by hand -------------------------------------------------------- */
check('by report number', M.searchLibrary(LIB2, 'TR-11-01').map((i) => i.key), ['SR11']);
check('by author and title words', M.searchLibrary(LIB, 'jones copper').map((i) => i.key), ['JONES20B']);
check('with accents or without', M.searchLibrary(LIB, 'ohman sfr').map((i) => i.key), ['OHMAN14']);
check('by year', M.searchLibrary(LIB, 'smith 2020').map((i) => i.key), ['SMITH20']);
check('every word must be found', M.searchLibrary(LIB, 'jones nothing'), []);

console.log(`${checks} checks`);
if (failures.length) {
  console.log(`${failures.length} FAILED:`);
  for (const f of failures) console.log(`  ${f}`);
  process.exit(1);
}
console.log('all passed');
