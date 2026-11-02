/* Checks of canister_inventory.html's reading and arithmetic, in Node:

     node resources/tests/inventory/test-model.mjs

   Every file is made here, from made-up numbers: an inventory in JSON (as
   an object and as an array, with NaN, nulls, escapes and a nuclide first
   seen part of the way through), and a PSAR-shaped report (.docx) and
   workbook (.xlsx, by SheetJS). Decay is checked against the Bateman
   solution and the definitions of activity and heat.

   If local/expected.json exists (make-local-fixtures.py writes it from
   real files, which stay out of the repository), the readers are also
   checked against what Python reads from those files. */
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../../..');
const JS = path.join(ROOT, 'resources/js');

/* Node 20's DecompressionStream has no 'deflate-raw'; every browser has. */
const Native = globalThis.DecompressionStream;
globalThis.DecompressionStream = function (format) {
  if (format !== 'deflate-raw') return new Native(format);
  const chunks = [];
  return new TransformStream({ transform(c) { chunks.push(Buffer.from(c)); }, flush(ctrl) { ctrl.enqueue(new Uint8Array(zlib.inflateRawSync(Buffer.concat(chunks)))); } });
};

const J = require(path.join(JS, 'inventory-json.js'));
const M = require(path.join(JS, 'inventory-model.js'));
const PS = require(path.join(JS, 'inventory-psar.js'));
const XLSX = require(path.join(ROOT, 'vendors/js/xlsx-0.20.3.full.min.js'));
const ctx = {};
vm.createContext(ctx);
vm.runInContext(`${fs.readFileSync(path.join(JS, 'rndecaydata.js'), 'utf8')}\nthis.__d = decaydata;`, ctx);
const ND = M.nuclearData(ctx.__d);

let checks = 0;
const failures = [];
function check(label, ok, detail = '') {
  checks++;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok ? '' : `  ${detail}`}`);
  if (!ok) failures.push(label);
}
const near = (a, b, rel) => Math.abs(a - b) <= rel * Math.max(Math.abs(a), Math.abs(b), 1e-300);
const source = (bytes) => ({ size: bytes.length, read: async (a, b) => bytes.slice(a, b) });

/* ---------------------------------------------------------------- names */
for (const [key, want] of [['cs137', 'Cs-137'], ['Cs-137', 'Cs-137'], ['am242m', 'Am-242m'], ['Am-242m1', 'Am-242m'],
  ['pa234m', 'Pa-234m'], ['137Cs', 'Cs-137'], ['h3', 'H-3'], ['U235', 'U-235'], ['Sn-121m', 'Sn-121m'], ['Am-242m2', 'Am-242n']]) {
  const n = J.nuclideOf(key);
  check(`nuclideOf(${key}) is ${want}`, n && n.name === want, JSON.stringify(n));
}
for (const key of ['fuel', 'reactor', 'Xx-12', 'c', '12', 'H-0', 'decay_heat_W']) check(`nuclideOf(${key}) is no nuclide`, J.nuclideOf(key) === null);
check('every inventory name of the test is in ICRP 107', ['Cs-137', 'Sr-90', 'Pu-241', 'Am-241', 'Np-237', 'H-3', 'C-14', 'Ni-59', 'Am-242m'].every((n) => ND.has(n)));

/* ------------------------------------------------------------ the JSON */
const NUC = ['cs137', 'sr90', 'pu241', 'am241', 'np237', 'h3', 'c14', 'ni59'];
const PARTS = ['fuel', 'crud', 'structural_material'];
let seed = 1;
const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
function makeInventory(nCan) {
  const out = {};
  for (let c = 0; c < nCan; c++) {
    const pwr = c % 3 === 0;
    const els = {};
    for (let e = 0; e < (pwr ? 4 : 12); e++) {
      const el = { reactor: pwr ? 'Ringhals 3' : (e === 0 && c === 1 ? 'Ågesta' : e === 1 && c === 2 ? 'Kahl' : 'Forsmark 1'), reactor_type: pwr ? 'PWR' : 'BWR', fuel_type: pwr ? 'W17x17' : 'SVEA 64' };
      for (const p of PARTS) {
        const m = {};
        for (const n of NUC) m[n] = p === 'fuel' ? Number((rnd() * 10).toPrecision(4)) : p === 'crud' ? Number((rnd() * 1e-6).toPrecision(4)) : (n === 'c14' || n === 'ni59' ? Number((rnd() * 0.1).toPrecision(4)) : 0);
        el[p] = m;
      }
      el.decay_heat_W = 50 + c;
      el.declared_heat_W = 49 + c;
      els[`${pwr ? 'P' : 'B'}${c}-${e}`] = el;
    }
    out[String(c + 10)] = { packing_date: `20${40 + (c % 8)}-0${1 + (c % 9)}-15`, fuel_elements: els, decay_heat_W: 1000 + c, declared_heat_W: 990 + c };
  }
  return out;
}
const inv0 = makeInventory(9);
const text0 = JSON.stringify(inv0, null, 1);
const bytes0 = new TextEncoder().encode(text0);
const d0 = await J.readInventory(source(bytes0));
check('canisters read', d0.canisters.n === 9, d0.canisters.n);
check('elements read', d0.elements.n === 3 * 4 + 6 * 12, d0.elements.n);
check('parts found in order', JSON.stringify(d0.parts) === JSON.stringify(PARTS), d0.parts);
check('nuclides found in order', JSON.stringify(d0.nuclides) === JSON.stringify(NUC));
check('the packing date is found', d0.canisters.dateKey === 'packing_date' && d0.canisters.dateText[0] === '2040-01-15');
check('canister numbers kept', Object.keys(d0.canisters.num).join() === 'decay_heat_W,declared_heat_W' && d0.canisters.num.decay_heat_W[3] === 1003);
check('element texts kept', d0.elements.text.reactor.values.includes('Ågesta') && d0.elements.text.fuel_type.values.length === 2);
let sumJs = 0, sumRef = 0;
for (const x of d0.amounts) sumJs += x;
for (const c of Object.values(inv0)) for (const e of Object.values(c.fuel_elements)) for (const p of PARTS) for (const n of NUC) sumRef += e[p][n];
check('every amount read', near(sumJs, sumRef, 1e-14), `${sumJs} vs ${sumRef}`);
for (const chunk of [1, 3, 64, 4093]) {
  const d = await J.readInventory(source(bytes0), null, { chunk });
  check(`slices of ${chunk} bytes give the same`, d.elements.n === d0.elements.n && d.amounts.every((x, i) => x === d0.amounts[i]) && d.canisters.id.join() === d0.canisters.id.join());
}
/* An array of canisters, element arrays, escapes, a BOM, NaN and nulls, a late nuclide. */
const odd = [
  { name: 'A "1" {x}', packed: '2041-02-03', elements: [{ id: 'e\\1', type: 'BWR', fuel: { cs137: 1, sr90: NaN }, decay_heat_W: 2 }, { id: 'e2', type: 'BWR', fuel: { cs137: 2, sr90: null } }] },
  { name: 'B', packed: '2042-12-31', elements: [{ id: 'e3', type: 'PWR', fuel: { cs137: 3, sr90: 4, i129: 5 } }] },
];
/* JSON.stringify writes NaN as null: the first becomes NaN again, the second stays null. */
const oddText = '﻿' + JSON.stringify(odd).replace('"sr90":null', '"sr90":NaN');
const d1 = await J.readInventory(source(new TextEncoder().encode(oddText)), null, { chunk: 5 });
check('an array of canisters with element arrays', d1.canisters.n === 2 && d1.elements.n === 3);
check('NaN as Python writes it is read as missing', d1.notes.lenient >= 1 && d1.notes.nulls >= 1, JSON.stringify(d1.notes));
check('a nuclide first seen later lays the amounts out again', d1.nuclides.length === 3 && d1.amounts[2 * 3 + 2] === 5 && d1.amounts[0] === 1, Array.from(d1.amounts).join());
check('names with quotes and escapes', d1.elements.id[0] === 'e\\1');
check('a date field of another name', d1.canisters.dateKey === 'packed' && d1.canisters.dateText[1] === '2042-12-31');
for (const [bad, why] of [['{"a": {"b": 1}', 'ends part of the way'], ['[1, 2', 'ends part of the way'], ['', 'empty'], ['{"x": 1} {', 'more after the end'], ['nope', 'does not start']]) {
  let msg = '';
  try { await J.readInventory(source(new TextEncoder().encode(bad))); } catch (e) { msg = e.message; }
  check(`broken JSON is refused (${why})`, msg.includes(why) || msg.includes('no canisters'), msg);
}
let none = '';
try { await J.readInventory(source(new TextEncoder().encode('{"a": 1, "b": "x"}'))); } catch (e) { none = e.message; }
check('a JSON with no canisters says so', /no canisters/.test(none), none);

/* -------------------------------------------------------------- decay */
const YEAR = M.YEAR_S;
{
  const sys = M.decaySystem(ND, ['H-3']);
  const n0 = new Float64Array(sys.members.length);
  n0[sys.index.get('H-3')] = 1;
  const t = 50 * YEAR;
  const n = M.decay(sys, n0, t);
  check('a lone nuclide decays as exp(-λt)', near(n[sys.index.get('H-3')], Math.exp(-Math.LN2 / ND.get('H-3').T * 50), 1e-12));
}
{
  const sys = M.decaySystem(ND, ['Pu-241']);
  const iP = sys.index.get('Pu-241'), iA = sys.index.get('Am-241');
  const n0 = new Float64Array(sys.members.length);
  n0[iP] = 1;
  const l1 = sys.lambda[iP], l2 = sys.lambda[iA];
  const br = ND.get('Pu-241').prog.find((p) => p.name === 'Am-241').br;
  let worst = 0;
  for (const y of [1, 14.3, 100, 432, 5000]) {
    const t = y * YEAR;
    const n = M.decay(sys, n0, t);
    const bateman = br * l1 / (l2 - l1) * (Math.exp(-l1 * t) - Math.exp(-l2 * t));
    worst = Math.max(worst, Math.abs(n[iA] / bateman - 1));
  }
  check('Am-241 grows from Pu-241 as Bateman says', worst < 1e-10, worst);
  check('the chain runs on to Np-237 and U-233', sys.index.has('Np-237') && sys.index.has('U-233') && sys.index.has('Th-229'));
}
{
  /* Below the solver's round-off (about 1e-16 of what a chain began with):
     what nothing feeds decays exactly, and what has run down with all that
     feeds it is 0. */
  const sys = M.decaySystem(ND, ['H-3', 'Am-242m', 'Pu-238']);
  const n0 = new Float64Array(sys.members.length);
  for (const n of ['H-3', 'Am-242m', 'Pu-238']) n0[sys.index.get(n)] = 1;
  const t = 1025 * YEAR, iH = sys.index.get('H-3');
  const n = M.decay(sys, M.withDaughters(sys, n0), t);
  check('H-3 after 1025 years is exp(−λt), 1e-25 of what it was', near(n[iH], Math.exp(-sys.lambda[iH] * t), 1e-12), n[iH]);
  const late = M.decay(sys, M.withDaughters(sys, n0), 1e5 * YEAR);
  check('what Am-242m feeds is 0 once Am-242m has run down', ['Am-242', 'Np-238', 'Cm-242', 'Pu-238'].every((m) => late[sys.index.get(m)] === 0));
  check('U-234 under it is not', late[sys.index.get('U-234')] > 0);
  const many = M.decayTimes(sys, n0, [0, t]);
  check('decayTimes gives each time’s amounts and activities', many.N[0][iH] === 1 && near(many.N[1][iH], n[iH], 1e-15) && near(many.A[1][iH], sys.lambda[iH] * n[iH], 1e-15));
}
{
  /* Decay heat of Cs-137 with Ba-137m in equilibrium. */
  const sys = M.decaySystem(ND, ['Cs-137']);
  const n = new Float64Array(sys.members.length);
  n[sys.index.get('Cs-137')] = 1;
  const full = M.withDaughters(sys, n);
  const br = ND.get('Cs-137').prog.find((p) => p.name === 'Ba-137m').br;
  const want = sys.lambda[sys.index.get('Cs-137')] * M.NA * (ND.get('Cs-137').E + br * ND.get('Ba-137m').E) * M.MEV_J;
  check('decay heat counts Ba-137m in equilibrium', near(M.heatOf(sys, full), want, 1e-12), `${M.heatOf(sys, full)} vs ${want}`);
  const eff = M.effectiveEnergy(sys);
  check('the energy of a Cs-137 decay with its daughter', near(eff[sys.index.get('Cs-137')], ND.get('Cs-137').E + br * ND.get('Ba-137m').E, 1e-12));
}
{
  const hl = new Map([['Ni-59', 76000]]);
  const a = M.decaySystem(ND, ['Ni-59']), b = M.decaySystem(ND, ['Ni-59'], hl);
  check('a half-life of PSAR’s replaces ICRP 107’s', b.T[b.index.get('Ni-59')] === 76000 && a.T[a.index.get('Ni-59')] !== 76000);
  check('one mole in Bq is NA λ', near(M.perMole(b, b.index.get('Ni-59'), 'Bq'), M.NA * Math.LN2 / (76000 * YEAR), 1e-15));
  check('one mole in g is the atomic mass', near(M.perMole(a, a.index.get('Ni-59'), 'g'), ND.get('Ni-59').mass, 1e-15));
}
{
  const ref = { values: new Map([['Cs-137', 1e15], ['Pu-239', 1e12]]), unit: 'Bq', year: 2045 };
  const same = M.referenceAt(ref, ND, null, 2045);
  const sys = M.decaySystem(ND, ['Cs-137']);
  check('a reference at its own year is its values', near(same.mol.get('Cs-137') * M.NA * sys.lambda[sys.index.get('Cs-137')], 1e15, 1e-12));
  const later = M.referenceAt(ref, ND, null, 2045 + 30);
  const want = Math.exp(-Math.LN2 * (M.yearMs(2075) - M.yearMs(2045)) / 1000 / (ND.get('Cs-137').T * YEAR));
  check('a reference decays to a later year', near(later.mol.get('Cs-137') / same.mol.get('Cs-137'), want, 1e-10));
  check('a year before a reference’s own is refused', M.referenceAt(ref, ND, null, 2040).ok === false);
}

/* ---------------------------------------------------------- inventory */
const inv = new M.Inventory(d0, ND, { name: 'test.json' });
check('fields found by name', inv.fields.type === 'reactor_type' && inv.fields.reactor === 'reactor' && inv.fields.fuel === 'fuel_type');
check('canister types from their elements', inv.typeNames.length === 2 && inv.select(inv.typeNames.indexOf('PWR')).length === 3);
check('categories as PSAR counts them', inv.categoryNames.includes('Ågesta') && inv.categoryNames.includes('Swap MOX'));
check('the first year every canister is packed by', inv.minYear === 2048, inv.minYear);
{
  const sys = M.decaySystem(ND, inv.names());
  const packed = inv.canistersAt(sys, null, 'k');
  const S = inv.P * inv.N;
  let s = 0;
  for (let e = 0; e < d0.elements.n; e++) if (d0.elements.can[e] === 4) for (let i = 0; i < inv.N; i++) s += d0.amounts[e * S + 2 * inv.N + i];
  let s2 = 0;
  for (let i = 0; i < inv.N; i++) s2 += packed.amounts[4 * S + 2 * inv.N + i];
  check('a canister’s part is the sum of its elements’', near(s, s2, 1e-14));
  const later = inv.canistersAt(sys, M.yearMs(2100), 'k');
  check('no canister is later than the year', later.later === 0);
  const k = inv.nuclides.findIndex((u) => u.name === 'H-3');
  const c = 5;
  const t = (M.yearMs(2100) - d0.canisters.date[c]) / 1000;
  let h0 = 0, h1 = 0;
  for (let p = 0; p < inv.P; p++) { h0 += packed.amounts[c * S + p * inv.N + k]; h1 += later.amounts[c * S + p * inv.N + k]; }
  check('each canister decays from its own date', near(h1, h0 * Math.exp(-Math.LN2 * t / (ND.get('H-3').T * YEAR)), 1e-10));
  const el = inv.elementsAt(sys, M.yearMs(2100), 'k');
  let a = 0;
  for (const e of inv.elementsOf(c)) a += el.amounts[e * inv.N + k];
  check('elements decay as their canister', near(a, h1, 1e-10));
  const tooEarly = inv.canistersAt(sys, M.yearMs(2041), 'k2');
  check('canisters packed after the year are counted', tooEarly.later > 0);
  const sums = inv.sumOver(later.amounts, inv.select(-1));
  check('sums over canisters and parts agree', near(sums.total.reduce((x, y) => x + y, 0), sums.parts.flatMap((r) => Array.from(r)).reduce((x, y) => x + y, 0), 1e-13));
  const sm = M.summary([3, 1, 2, 4]);
  check('percentiles as Excel’s PERCENTILE.INC', sm.p50 === 2.5 && near(sm.p5, 1.15, 1e-12) && sm.max === 4);
}

/* -------------------------------------------------------- PSAR report */
function crc32(buf) {
  let c, crc = 0xffffffff;
  for (let n = 0; n < buf.length; n++) {
    c = (crc ^ buf[n]) & 0xff;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    crc = (crc >>> 8) ^ c;
  }
  return (crc ^ 0xffffffff) >>> 0;
}
function zip(files) {
  const parts = [], dir = [];
  let at = 0;
  for (const [name, text] of Object.entries(files)) {
    const data = Buffer.from(text, 'utf8');
    const packed = zlib.deflateRawSync(data);
    const nm = Buffer.from(name, 'utf8');
    const head = Buffer.alloc(30);
    head.writeUInt32LE(0x04034b50, 0); head.writeUInt16LE(20, 4); head.writeUInt16LE(8, 8);
    head.writeUInt32LE(crc32(data), 14); head.writeUInt32LE(packed.length, 18); head.writeUInt32LE(data.length, 22); head.writeUInt16LE(nm.length, 26);
    const cd = Buffer.alloc(46);
    cd.writeUInt32LE(0x02014b50, 0); cd.writeUInt16LE(20, 4); cd.writeUInt16LE(20, 6); cd.writeUInt16LE(8, 10);
    cd.writeUInt32LE(crc32(data), 16); cd.writeUInt32LE(packed.length, 20); cd.writeUInt32LE(data.length, 24); cd.writeUInt16LE(nm.length, 28); cd.writeUInt32LE(at, 42);
    parts.push(head, nm, packed);
    dir.push(cd, nm);
    at += 30 + nm.length + packed.length;
  }
  const cdBuf = Buffer.concat(dir);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(dir.length / 2, 8); end.writeUInt16LE(dir.length / 2, 10); end.writeUInt32LE(cdBuf.length, 12); end.writeUInt32LE(at, 16);
  return new Uint8Array(Buffer.concat([...parts, cdBuf, end]));
}
const W = (t) => `<w:p><w:r><w:t xml:space="preserve">${t}</w:t></w:r></w:p>`;
const tc = (t, span = 1) => `<w:tc><w:tcPr>${span > 1 ? `<w:gridSpan w:val="${span}"/>` : ''}</w:tcPr>${W(t)}</w:tc>`;
const tr = (...cells) => `<w:tr>${cells.join('')}</w:tr>`;
const tbl = (...rows) => `<w:tbl><w:tblPr/>${rows.join('')}</w:tbl>`;
const sv = (x) => x.toExponential(2).replace('.', ',').replace(/e([+-])(\d)$/, 'E$10$2').replace(/e([+-])(\d\d)$/, 'E$1$2');
const NAMES = ['Cs-137', 'Sr-90', 'Pu-241', 'Am-241'];
const VAL = { 'Cs-137': 1.11e15, 'Sr-90': 2.22e15, 'Pu-241': 3.33e14, 'Am-241': 4.44e13 };
const xml = `<?xml version="1.0"?><w:document xmlns:w="w"><w:body>
${W('Detta ger 3 982 BWR-kapslar och 1 707 PWR-kapslar, och totalt 5 689 kapslar.')}
${W('Tabell D-1. Halveringstider')}
${tbl(tr(tc('nuklid'), tc('halverings-tid(år)'), tc('specifik aktivitet (Bq/g)'), tc('specifik aktivitet(Bq/mol)'), tc('nuklid'), tc('halverings-tid(år)'), tc('specifik aktivitet (Bq/g)'), tc('specifik aktivitet(Bq/mol)')),
    tr(tc('Cs-137'), tc('3,01E+01'), tc('1'), tc('1'), tc('Ni-59'), tc('7,60E+04'), tc('1'), tc('1')))}
${W('Tabell D-2. Totala radionuklidinventariet. Det redovisade aktivitetsinnehållet gäller år 2045.')}
${tbl(tr(tc(''), tc('BWR40 MWd/kgU', 3), tc('PWR45 MWd/kgU', 4), tc('Ågesta'), tc('swap MOX'), tc('stav-skelett'), tc('total aktivitet')),
    tr(tc('antal'), tc('47 314'), tc('47 314'), tc('47 314'), tc('6793'), tc('6793'), tc('586'), tc('6793'), tc('222'), tc('217'), tc('65'), tc('alla delar')),
    tr(tc('nuklid'), tc('bränsle-kutsar'), tc('konstr.mtrl'), tc('crud'), tc('bränsle-kutsar'), tc('konstr.mtrl'), tc('styr-stavar'), tc('crud'), tc('totalt'), tc('totalt'), tc('totalt'), tc('')),
    ...NAMES.map((n) => tr(tc(n), tc(sv(VAL[n])), tc('0'), tc('1,0E+06'), tc(sv(VAL[n] / 2)), tc(''), tc('2,0E+03'), tc('0'), tc('5,0E+10'), tc('6,0E+10'), tc('7,0E+09'), tc(sv(VAL[n] * 1.5)))))}
${W('Tabell E-7. Radionuklidinventarium i medelkapsel')}
${tbl(tr(tc(''), tc('BWR'), tc('avvikelse (%)', 2), tc('PWR +0,0863 styrstav'), tc('avvikelse (%)', 2)),
    tr(tc('nuklid'), tc('aktivitet (Bq)'), tc('låg BU (30)'), tc('hög BU (50)'), tc('aktivitet (Bq)'), tc('låg BU (35)'), tc('hög BU (55)')),
    ...NAMES.map((n) => tr(tc(n), tc(sv(VAL[n] / 5000)), tc('-12,5%'), tc('20,0%'), tc(sv(VAL[n] / 1000)), tc('-30,0%'), tc('25,5%'))))}
${W('Tabell E-2. BWR-kapsel med medelhög medelutbränning (12x40 MWd/kgU)')}
${tbl(tr(tc('nuklid'), tc('kutsar(Bq)'), tc('konstruktionsmaterial (Bq)'), tc('crud+TRU (Bq)'), tc('total aktivitet (Bq)')),
    ...NAMES.map((n) => tr(tc(n), tc(sv(VAL[n] / 4000)), tc(''), tc('1,0E+02'), tc(sv(VAL[n] / 4000 + 100)))))}
</w:body></w:document>`;
const report = await PS.readReport(zip({ '[Content_Types].xml': '<Types/>', 'word/document.xml': xml }), 'report.docx');
check('the report’s year', report.year === 2045);
check('the report’s canisters', report.counts.canisters.BWR === 3982 && report.counts.canisters.PWR === 1707 && report.counts.canisters.all === 5689, JSON.stringify(report.counts));
check('Table D-1’s half-lives, two to a row', report.halfLives && report.halfLives.values.get('Cs-137') === 30.1 && report.halfLives.values.get('Ni-59') === 76000);
const d2 = Object.fromEntries(report.refs.filter((r) => r.kind === 'total').map((r) => [r.scope, r]));
check('Table D-2: a total per kind of fuel', ['BWR', 'PWR', 'Ågesta', 'Swap MOX', 'Rod skeletons'].every((k) => d2[k]), Object.keys(d2));
check('Table D-2: BWR is its parts summed', near(d2.BWR.values.get('Cs-137'), 1.11e15 + 1e6, 1e-12) && d2.BWR.parts.get('crud').get('Sr-90') === 1e6);
check('Table D-2: PWR has its control rods', d2.PWR.parts.get('control_rods').get('Am-241') === 2000 && near(d2.PWR.values.get('Am-241'), 2.22e13 + 2000, 1e-12));
check('Table D-2: the number of elements', d2.BWR.count === 47314 && d2.PWR.count === 6793 && d2['Ågesta'].count === 222 && d2['Swap MOX'].count === 217);
const e7 = Object.fromEntries(report.refs.filter((r) => r.kind === 'average').map((r) => [r.scope, r]));
check('Table E-7: the average BWR and PWR canister', near(e7.BWR.values.get('Pu-241'), 3.33e14 / 5000, 1e-12) && near(e7.PWR.values.get('Am-241'), 4.44e13 / 1000, 1e-12));
check('Table E-7: the spread as fractions', e7.BWR.low.get('Cs-137') === -0.125 && e7.PWR.high.get('Sr-90') === 0.255);
const e2 = report.refs.find((r) => r.kind === 'canister');
check('Tables E: a canister of medium burnup by part', e2 && e2.level === 'medium' && e2.scope === 'BWR' && e2.parts.get('crud').get('Cs-137') === 100);

/* ------------------------------------------------------ PSAR workbook */
const aoa = (rows) => XLSX.utils.aoa_to_sheet(rows);
const wb = XLSX.utils.book_new();
XLSX.utils.book_append_sheet(wb, aoa([
  [null, null, 'BWR', 'PWR', 'Stavskelett', 'Ågesta', 'Swap MOX BWR', 'Swap MOX PWR', 'Summa', 'Antal kapslar', 'Average canister', null, 'Källa antal kapslar: SKBdoc 0'],
  [null, 'Nuklid', 'Aktivitet (Bq)', 'Aktivitet (Bq)', 'Aktivitet (Bq)', 'Aktivitet (Bq)', 'Aktivitet (Bq)', 'Aktivitet (Bq)', 'Totalt', 100, 'Aktivitet (Bq)'],
  ...NAMES.map((n, i) => [i + 1, n, VAL[n], VAL[n] / 2, 1, 2, 3, 4, VAL[n] * 1.5 + 10, null, (VAL[n] * 1.5 + 10) / 100]),
  [null, 'Summa'],
]), 'Totalt radionuklidinventarium');
XLSX.utils.book_append_sheet(wb, aoa([
  [],
  ['BWR', null, null, null, 'BWR', 'Avvikelse (%)', 'Avvikelse (%)', null, 'PWR', null, 'PWR', 'PWR', 'En styrstav', null, 'PWR +0,0863 styrstav ', null, 'Avvikelse (%)', 'Avvikelse (%)'],
  [null, 'Nuklid', 'Medelelement', 'Nuklid', 'Medelkapsel', 'Låg BU (30)', 'Hög BU (50)', 'Nuklid', 'Medelelement', 'Nuklid', 'Medelkapsel utan styrstav', 'Med en styrstav', 'Nuklid', 'Aktivitet (Bq)', 'Nuklid', 'Aktivitet (Bq)', 'Låg BU (35)', 'Hög BU (55)'],
  ...NAMES.map((n, i) => [i + 1, n, 1, n, VAL[n] / 5000, -0.1, 0.2, n, 2, n, 8, 8, null, null, n, VAL[n] / 1000, -0.3, 0.25]),
]), 'Medelkapslar');
XLSX.utils.book_append_sheet(wb, aoa([
  ['Antal element', null, 600, 'Siffra', null, null, null, 'Antal styrstavar', null, 60],
  ['PWR', 'PWR17x17'],
  [null, 'Bränslekutsar', 'Konstruktionsdelar', null, 'Crud + TRU', null, 'Summa', 'Med styrstav', 'Styrstavar'],
  ['Nuklid', 'Aktivitet (Bq)', 'Nuklid', 'Aktivitet (Bq)', 'Nuklid', 'Aktivitet (Bq)', 'Aktivitet (Bq)', 'Aktivitet (Bq)', 'Nuklid', 'Aktivitet (Bq)'],
  ...NAMES.map((n) => [n, 3, n, 1, n, 0, 4, 4, n, n === 'Am-241' ? 100 : 0]),
]), 'PWR');
const sim = [['Patron nr', 'Reaktor', 'Reaktortyp', 'Bränslekonstr.', 'Kapsel nr', 'Dep.år', 'Resteffekt', 'Utbränn']];
for (let c = 1; c <= 3; c++) for (let e = 0; e < 4; e++) sim.push([c * 10 + e, e === 0 ? 'KWO' : 'R3', 'PWR', '17*17', c, 2040 + c, 400 + e, 40 + e]);
XLSX.utils.book_append_sheet(wb, aoa(sim), 'Medelutbränning PWR-kapslar');
const wbBytes = XLSX.write(wb, { type: 'buffer', bookType: 'xlsx' });
const book = PS.readWorkbook(XLSX.read(wbBytes, { type: 'buffer' }), XLSX, 'book.xlsx');
const avgAll = book.refs.find((r) => r.id === 'workbook:average:all');
check('the workbook’s average canister', avgAll && near(avgAll.values.get('Sr-90'), (2.22e15 * 1.5 + 10) / 100, 1e-12));
check('the canister count, not the note beside it', book.counts.canisters.all === 100 && avgAll.count === 100, JSON.stringify(book.counts));
const tw = Object.fromEntries(book.refs.filter((r) => r.kind === 'total').map((r) => [r.scope, r]));
check('swap MOX BWR and PWR summed', tw['Swap MOX'] && tw['Swap MOX'].values.get('Cs-137') === 7);
check('the workbook’s rod skeletons', tw['Rod skeletons'] && tw['Rod skeletons'].values.get('Am-241') === 1);
const pw = book.refs.find((r) => r.id === 'workbook:average:PWR');
check('the average PWR canister with its spread', pw && near(pw.values.get('Am-241'), 4.44e10, 1e-12) && pw.low.get('Cs-137') === -0.3 && pw.high.get('Cs-137') === 0.25);
const rodShare = 100 * 0.1 / (3 + 1 + 0 + 100 * 0.1);
check('its parts in the shares of an element, rods per element', pw.parts && near(pw.parts.get('control_rods').get('Am-241'), 4.44e10 * rodShare, 1e-12), pw.parts && pw.parts.get('control_rods').get('Am-241'));
check('the encapsulation simulation', book.canisters.length === 3 && book.canisters[0].n === 4 && book.canisters[0].heat === 1606 && book.canisters[1].year === 2042);
check('reactor codes as names', book.canisters[0].elements[0].reactor === 'Obrigheim' && book.canisters[0].elements[1].reactor === 'Ringhals 3');

check('numbers as Swedish documents write them', PS.svNumber('4,18E+09') === 4.18e9 && PS.svNumber('17,3 E+16') === 1.73e17 && PS.svNumber('47 314') === 47314
  && PS.svNumber('-2,8%') === -0.028 && PS.svNumber('') === null && Number.isNaN(PS.svNumber('BWR')));

/* ----------------------------------------------------- zipped and gzipped */
/* A zip archive written here: entries deflated or stored, and, with zip64,
   the 64-bit sizes and directory that archives over 4 GB carry. */
function zipArchive(entries, { zip64 = false } = {}) {
  const parts = [], dir = [];
  let at = 0;
  for (const { name, data, method = 8 } of entries) {
    const raw = Buffer.isBuffer(data) ? data : Buffer.from(String(data), 'utf8');
    const packed = method === 8 ? zlib.deflateRawSync(raw) : raw;
    const nm = Buffer.from(name, 'utf8');
    const head = Buffer.alloc(30);
    head.writeUInt32LE(0x04034b50, 0); head.writeUInt16LE(20, 4); head.writeUInt16LE(0x800, 6); head.writeUInt16LE(method, 8);
    head.writeUInt32LE(crc32(raw), 14); head.writeUInt32LE(packed.length, 18); head.writeUInt32LE(raw.length, 22); head.writeUInt16LE(nm.length, 26);
    const extra = zip64 ? Buffer.alloc(28) : Buffer.alloc(0);
    if (zip64) { extra.writeUInt16LE(1, 0); extra.writeUInt16LE(24, 2); extra.writeBigUInt64LE(BigInt(raw.length), 4); extra.writeBigUInt64LE(BigInt(packed.length), 12); extra.writeBigUInt64LE(BigInt(at), 20); }
    const cd = Buffer.alloc(46);
    cd.writeUInt32LE(0x02014b50, 0); cd.writeUInt16LE(45, 4); cd.writeUInt16LE(45, 6); cd.writeUInt16LE(0x800, 8); cd.writeUInt16LE(method, 10);
    cd.writeUInt32LE(crc32(raw), 16);
    cd.writeUInt32LE(zip64 ? 0xffffffff : packed.length, 20); cd.writeUInt32LE(zip64 ? 0xffffffff : raw.length, 24);
    cd.writeUInt16LE(nm.length, 28); cd.writeUInt16LE(extra.length, 30); cd.writeUInt32LE(zip64 ? 0xffffffff : at, 42);
    parts.push(head, nm, packed);
    dir.push(cd, nm, extra);
    at += 30 + nm.length + packed.length;
  }
  const cdBuf = Buffer.concat(dir);
  const tail = [];
  if (zip64) {
    const rec = Buffer.alloc(56);
    rec.writeUInt32LE(0x06064b50, 0); rec.writeBigUInt64LE(44n, 4); rec.writeUInt16LE(45, 12); rec.writeUInt16LE(45, 14);
    rec.writeBigUInt64LE(BigInt(entries.length), 24); rec.writeBigUInt64LE(BigInt(entries.length), 32);
    rec.writeBigUInt64LE(BigInt(cdBuf.length), 40); rec.writeBigUInt64LE(BigInt(at), 48);
    const loc = Buffer.alloc(20);
    loc.writeUInt32LE(0x07064b50, 0); loc.writeBigUInt64LE(BigInt(at + cdBuf.length), 8); loc.writeUInt32LE(1, 16);
    tail.push(rec, loc);
  }
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(zip64 ? 0xffff : entries.length, 8); end.writeUInt16LE(zip64 ? 0xffff : entries.length, 10);
  end.writeUInt32LE(zip64 ? 0xffffffff : cdBuf.length, 12); end.writeUInt32LE(zip64 ? 0xffffffff : at, 16);
  return new Uint8Array(Buffer.concat([...parts, cdBuf, ...tail, end]));
}
const same = (a, b) => a.elements.n === b.elements.n && a.canisters.n === b.canisters.n && a.amounts.length === b.amounts.length && a.amounts.every((x, i) => x === b.amounts[i]);
for (const zip64 of [false, true]) {
  const archive = new Blob([zipArchive([
    { name: 'inventories/', data: '', method: 0 },
    { name: '__MACOSX/inventories/._inventory.json', data: 'resource fork', method: 0 },
    { name: 'inventories/inventory.json', data: text0 },
    { name: 'inventories/.DS_Store', data: 'x', method: 0 },
    { name: 'notes/läs mig.txt', data: 'stored, not packed', method: 0 },
  ], { zip64 })]);
  const entries = await J.zipDirectory(archive);
  const kind = zip64 ? 'a zip64 archive' : 'a zip archive';
  check(`${kind}: its directory, names in UTF-8`, entries.map((e) => e.name).join('|') === 'inventories/|__MACOSX/inventories/._inventory.json|inventories/inventory.json|inventories/.DS_Store|notes/läs mig.txt', entries.map((e) => e.name));
  check(`${kind}: folders and macOS’s own files passed over`, entries.filter(J.zipUsable).map((e) => e.name).join('|') === 'inventories/inventory.json|notes/läs mig.txt');
  const inner = entries.find((e) => e.name === 'inventories/inventory.json');
  check(`${kind}: sizes`, inner.usize === bytes0.length && inner.method === 8 && inner.csize < inner.usize, JSON.stringify(inner));
  let seen = 0;
  const fromZip = await J.readInventoryStream(await J.zipEntryStream(archive, inner, (n) => { seen += n; }));
  check(`${kind}: the inventory in it is read as it unpacks, the same as the file`, same(fromZip, d0));
  check(`${kind}: every packed byte counted for the progress`, seen === inner.csize, `${seen} of ${inner.csize}`);
  const stored = entries.find((e) => e.name === 'notes/läs mig.txt');
  check(`${kind}: a stored entry as it is`, (await new Response(await J.zipEntryStream(archive, stored)).text()) === 'stored, not packed');
}
{
  const gz = new Blob([zlib.gzipSync(Buffer.from(bytes0))]);
  check('a gzip file is read as it unpacks, the same as the file', same(await J.readInventoryStream(J.unpack(gz, 'gzip')), d0));
  const broken = new Blob([zlib.gzipSync(Buffer.from(bytes0)).subarray(0, 4000)]);
  let msg = '';
  try { await J.readInventoryStream(J.unpack(broken, 'gzip')); } catch (e) { msg = e.message; }
  check('a gzip file cut short is refused', /damaged|part of the way/.test(msg), msg);
  let enc = '';
  try { await J.zipEntryStream(new Blob([]), { name: 'x.json', flags: 1, method: 8 }); } catch (e) { enc = e.message; }
  check('an encrypted entry is refused', /encrypted/.test(enc), enc);
  let notZip = '';
  try { await J.zipDirectory(new Blob(['not a zip at all'])); } catch (e) { notZip = e.message; }
  check('a file that is no zip archive says so', /not a zip archive/.test(notZip), notZip);
}

/* ---------------------------------------------------------------- Excel */
{
  const XE = require(path.join(JS, 'inventory-excel.js'));
  const ms = Date.UTC(2038, 2, 7);
  const buf = XE.build(XLSX, [
    { name: 'Nuclides: all [1]?', columns: [{ label: 'Nuclide' }, { label: 'mol', fmt: 'sci' }, { label: 'share', fmt: 'pct' }, { label: 'Packed', fmt: 'date' }, { label: 'n', fmt: 'int' }],
      rows: [['Cs-137', 3.2667e-10, 0.25, ms, 12], ['U-238', 7961.25, NaN, null, 4], ['=1+1', Infinity, 1, ms, 4]] },
    { name: 'Nuclides: all [1]?', columns: [{ label: 'x' }], rows: [[1]] },
  ]);
  const book = XLSX.read(new Uint8Array(buf), { type: 'array', cellNF: true });
  check('Excel: sheet names Excel takes, each once', book.SheetNames.join('|') === 'Nuclides all 1|Nuclides all 1 (2)', book.SheetNames);
  const ws = book.Sheets[book.SheetNames[0]];
  check('Excel: numbers whole, in a format', ws.B2.v === 3.2667e-10 && ws.B2.z === '0.000E+00' && ws.C2.z === '0.0%' && ws.E2.v === 12, `${ws.B2.v} ${ws.B2.z} ${ws.C2.z}`);
  /* 2038-03-07 is day 24 902 after 1970-01-01, which is Excel's day 25 569 */
  check('Excel: a date as Excel’s own', ws.D2.v === 24902 + 25569 && ws.D2.z === 'yyyy-mm-dd', `${ws.D2.v} ${ws.D2.z}`);
  check('Excel: what is no number is an empty cell', !ws.C3 && !ws.D3 && !ws.B4);
  check('Excel: text that looks like a formula stays text', ws.A4.t === 's' && ws.A4.v === '=1+1' && !ws.A4.f);
  check('Excel: a filter on the headings', ws['!autofilter'] && ws['!autofilter'].ref === 'A1:E4');
}

/* ------------------------------------------------------------- raw data */
/* Node 20's CompressionStream has no 'deflate-raw' either. */
const NativeC = globalThis.CompressionStream;
globalThis.CompressionStream = function (format) {
  if (format !== 'deflate-raw') return new NativeC(format);
  const chunks = [];
  return new TransformStream({ transform(c) { chunks.push(Buffer.from(c)); }, flush(ctrl) { ctrl.enqueue(new Uint8Array(zlib.deflateRawSync(Buffer.concat(chunks)))); } });
};
const RAW = require(path.join(JS, 'inventory-raw.js'));
{
  const sys = M.decaySystem(ND, inv.names());
  const S = inv.P * inv.N;
  const all = new Uint8Array(inv.nEl).fill(1);
  const ks = inv.nuclides.map((u) => u.k), ps = inv.parts.map((_, p) => p);
  const run = (o) => {
    const plan = inv.raw(sys, { chosen: all, level: 'el', parts: ps, apart: true, nuclides: ks, ms: null, qty: 'mol', ...o });
    const out = new Float64Array(plan.rows.length * plan.cols.length);
    plan.fill(out, 0, plan.rows.length);
    return { plan, out };
  };
  const a = run({});
  check('raw: as packed, every element, part and nuclide is the file’s own amount', a.plan.rows.length === inv.nEl && a.out.every((v, i) => v === d0.amounts[i]));
  const pieces = new Float64Array(a.out.length);
  for (let i = 0; i < a.plan.rows.length; i += 7) a.plan.fill(pieces, i, Math.min(a.plan.rows.length, i + 7));
  check('raw: filled a piece at a time, the same', pieces.every((v, i) => v === a.out[i]));
  const ms = M.yearMs(2100);
  const b = run({ ms, apart: false });
  const ea = inv.elementsAt(sys, ms, 'raw-test');
  let worst = 0;
  for (let i = 0; i < ea.amounts.length; i++) if (ea.amounts[i] > 0) worst = Math.max(worst, Math.abs(b.out[i] / ea.amounts[i] - 1));
  check('raw: in a year, an element with its parts summed is the same as in the Canisters view', worst < 1e-12, worst);
  const c = run({ ms, level: 'can' });
  const ca = inv.canistersAt(sys, ms, 'raw-test');
  worst = 0;
  c.plan.rows.forEach((cn, r) => { for (let i = 0; i < S; i++) if (ca.amounts[cn * S + i] > 0) worst = Math.max(worst, Math.abs(c.out[r * S + i] / ca.amounts[cn * S + i] - 1)); });
  check('raw: in a year, each part of a canister decays on its own, as in the other views', c.plan.rows.length === inv.nCan && worst < 1e-12, worst);
  const w = run({ qty: 'W', apart: false });
  const e0 = inv.elementsAt(sys, null, 'raw-test');
  worst = 0;
  for (let e = 0; e < inv.nEl; e++) { let s = 0; for (let k = 0; k < inv.N; k++) s += w.out[e * inv.N + k]; worst = Math.max(worst, Math.abs(s / e0.heat[e] - 1)); }
  check('raw: the decay heat of each nuclide, with its short-lived daughters, sums to the element’s', worst < 1e-12, worst);
  const kCs = inv.nuclides.find((u) => u.name === 'Cs-137').k, iCs = sys.index.get('Cs-137');
  const bq = run({ qty: 'Bq', apart: false, nuclides: [kCs] });
  check('raw: becquerels are NA λ times the moles', near(bq.out[0], (d0.amounts[kCs] + d0.amounts[inv.N + kCs] + d0.amounts[2 * inv.N + kCs]) * M.NA * sys.lambda[iCs], 1e-12));
  const order = run({ nuclides: [3, 0], parts: [2], apart: true });
  check('raw: the nuclides and parts asked for, in their order', order.plan.cols.map((x) => `${x.p}:${x.k}`).join() === '2:3,2:0' && order.out[0] === d0.amounts[2 * inv.N + 3] && order.out[1] === d0.amounts[2 * inv.N]);
  const some = new Uint8Array(inv.nEl);
  for (let e = 0; e < inv.nEl; e += 3) some[e] = 1;
  check('raw: a row for each element chosen', run({ chosen: some }).plan.rows.length === Math.ceil(inv.nEl / 3));
  const sc = run({ chosen: some, level: 'can', apart: false, nuclides: [0] });
  let sums = true;
  sc.plan.rows.forEach((cn, r) => {
    let s = 0;
    for (let e = d0.canisters.el0[cn]; e < d0.canisters.el0[cn] + d0.canisters.nEl[cn]; e++) if (some[e]) for (let p = 0; p < inv.P; p++) s += d0.amounts[e * S + p * inv.N];
    if (!near(sc.out[r], s, 1e-14)) sums = false;
  });
  check('raw: a canister sums only its elements chosen, and one with none is left out', sums && sc.plan.rows.every((cn) => [...Array(d0.canisters.nEl[cn]).keys()].some((i) => some[d0.canisters.el0[cn] + i])));
}
{
  const te = new TextEncoder();
  check('CRC-32 of "123456789" is CBF43926', RAW.crc32(te.encode('123456789')) === 0xcbf43926);
  check('CRC-32 carried on from piece to piece', RAW.crc32(te.encode('456789'), RAW.crc32(te.encode('123'))) === 0xcbf43926);
  check('column letters', RAW.colName(0) === 'A' && RAW.colName(25) === 'Z' && RAW.colName(26) === 'AA' && RAW.colName(16383) === 'XFD');
  const BEL = String.fromCharCode(7);
  const table = {
    sheet: 'Fuel elements', nRows: 3,
    fields: [{ label: 'Element', fmt: 'text', width: 20, values: ['E1 <&> "q"', `E2${BEL}`, null] },
      { label: 'Packed', fmt: 'date', width: 11, values: [Date.UTC(2038, 6, 2), NaN, Date.UTC(2040, 0, 1)] },
      { label: 'Elements', fmt: 'int', width: 8, values: [12, 4, 0] }],
    values: { labels: ['Cs-137 fuel (mol)', 'Sr-90 fuel (mol)'], fmt: 'sci', width: 13, matrix: Float64Array.from([1.5e-7, NaN, 3, 4.25e20, 0, Infinity]) },
  };
  const join = (chunks) => Buffer.concat(chunks.map((x) => Buffer.from(x.buffer, x.byteOffset, x.byteLength)));
  const xbytes = join(await RAW.xlsx(table, [['Inventory', 'test.json'], ['Time', 'as packed']]));
  const wb = XLSX.read(xbytes, { type: 'buffer', cellNF: true });
  const ws = wb.Sheets['Fuel elements'];
  check('raw Excel: the sheet and one saying what it is', wb.SheetNames.join() === 'Fuel elements,About' && wb.Sheets.About.B2.v === 'test.json');
  check('raw Excel: the headings', ws.A1.v === 'Element' && ws.D1.v === 'Cs-137 fuel (mol)' && ws.E1.v === 'Sr-90 fuel (mol)');
  check('raw Excel: numbers whole, in 0.000E+00', ws.D2.v === 1.5e-7 && ws.D2.z === '0.000E+00' && ws.E3.v === 4.25e20 && ws.D4.v === 0, `${ws.D2 && ws.D2.v} ${ws.D2 && ws.D2.z}`);
  check('raw Excel: what is no finite number an empty cell', !ws.E2 && !ws.E4 && !ws.B3 && !ws.A4);
  check('raw Excel: text as it was, what XML cannot hold left out', ws.A2.v === 'E1 <&> "q"' && ws.A3.v === 'E2');
  check('raw Excel: a date as Excel’s own day number, whole numbers as such', ws.B2.v === Date.UTC(2038, 6, 2) / 86400000 + 25569 && ws.B2.z === 'yyyy-mm-dd' && ws.C2.v === 12 && ws.C2.z === '0');
  check('raw Excel: a filter on the headings', ws['!autofilter'] && ws['!autofilter'].ref === 'A1:E4');
  /* Every part of the workbook against the SpreadsheetML schema, where SML_XSD names a transitional sml.xsd. */
  const xsd = process.env.SML_XSD;
  if (xsd && fs.existsSync(xsd)) {
    const { spawnSync } = await import('node:child_process');
    const blob = new Blob([xbytes]);
    const dir = fs.mkdtempSync(path.join((await import('node:os')).tmpdir(), 'inv-raw-'));
    const bad = [];
    for (const e of (await J.zipDirectory(blob)).filter((x) => /^xl\/(workbook|styles|worksheets\/sheet\d+)\.xml$/.test(x.name))) {
      const text = Buffer.from(await new Response(await J.zipEntryStream(blob, e)).arrayBuffer());
      const file = path.join(dir, e.name.replace(/\//g, '_'));
      fs.writeFileSync(file, text);
      const res = spawnSync('xmllint', ['--noout', '--nonet', '--schema', xsd, file], { encoding: 'utf8' });
      if (res.status !== 0) bad.push(`${e.name}: ${res.stderr.trim().split('\n').slice(0, 2).join(' ')}`);
    }
    check('raw Excel: workbook, styles and sheets valid SpreadsheetML (sml.xsd)', bad.length === 0, bad.join('; '));
  } else console.log('(SML_XSD is not the path of a transitional sml.xsd: the schema check is skipped)');
  const text = join(RAW.csv(table, ['Inventory: test.json'])).toString('utf8');
  const lines = text.split('\r\n');
  check('raw CSV: its mark, the head as comments, the headings', lines[0] === `${String.fromCharCode(0xfeff)}# Inventory: test.json` && lines[1] === 'Element,Packed,Elements,Cs-137 fuel (mol),Sr-90 fuel (mol)');
  check('raw CSV: text quoted, dates as dates, every digit, nothing for what is no number', lines[2] === '"E1 <&> ""q""",2038-07-02,12,1.5e-7,' && lines[3] === `E2${BEL},,4,3,425000000000000000000` && lines[4] === ',2040-01-01,0,0,', JSON.stringify(lines.slice(2, 5)));
}

/* ---------------------------------------------------------------- ENSDF */
{
  /* The site's newest release, as the page reads it (KVOT_ENSDF_DATA scripts). */
  const RE = require(path.join(JS, 'rdc-ensdf.js')), IE = require(path.join(JS, 'inventory-ensdf.js'));
  const dataDir = path.join(ROOT, 'resources/data/ensdf');
  const loadData = (file) => { let got = null; vm.runInContext(fs.readFileSync(file, 'utf8'), vm.createContext({ KVOT_ENSDF_DATA: (id, part, data) => { got = data; } })); return got; };
  const rel = loadData(path.join(dataDir, 'releases.js'))[0];
  const db = RE.database(loadData(path.join(dataDir, rel.id, 'summary.js')), ctx.__d);
  const am = IE.stateOf(db, 'Am-242m', ND.get('Am-242m').T);
  check(`ENSDF (${rel.label}): Am-242m is the state with ICRP 107’s half-life`, am && am.how === 'half-life' && Math.abs(Math.log10(db.idx.get(95, 242).s[am.k].ts / RE.YEAR / ND.get('Am-242m').T)) < IE.SAME_LIFE, am && am.name);
  check('ENSDF: a name without m is the ground state', IE.stateOf(db, 'Cs-137', ND.get('Cs-137').T).k === 0);
  const names = [...inv.names(), 'Am-242m'];
  const made = IE.recordsFor(db, names, ND, ctx.__d);
  const NE = M.nuclearData(made.records);
  check('ENSDF: a record for every nuclide asked for, under the inventory’s name', names.every((n) => NE.has(n)) && made.missing.length === 0, made.missing);
  const renamed = [...made.states].filter(([n, st]) => st.name !== n).map(([, st]) => st.name);
  check('ENSDF: a state renamed is renamed in every arrow to it', !made.records.some((r) => renamed.includes(r.name) || r.Progenies.some((p) => renamed.includes(p.name))), renamed);
  check('ENSDF: its half-lives, in the page’s years', names.every((n) => { const st = made.states.get(n), s = db.idx.get(st.z, st.a).s[st.k]; return !(s.ts > 0) || near(NE.get(n).T, s.ts / RE.YEAR, 1e-12); }));
  check('ENSDF: the atomic masses ICRP 107’s', near(NE.get('Cs-137').mass, ND.get('Cs-137').mass, 1e-15));
  const sysE = M.decaySystem(NE, names);
  const n0 = new Float64Array(sysE.members.length);
  n0[sysE.index.get('Pu-241')] = 1;
  check('ENSDF: Am-241 grows from Pu-241 along its chain', M.decay(sysE, n0, 50 * YEAR)[sysE.index.get('Am-241')] > 0.85);
  const totals = new Map();
  const packed = inv.packed();
  for (let c = 0; c < inv.nCan; c++) for (let p = 0; p < inv.P; p++) inv.nuclides.forEach((u) => totals.set(u.name, (totals.get(u.name) || 0) + packed[(c * inv.P + p) * inv.N + u.k]));
  const heat = (sys) => { const v = new Float64Array(sys.members.length); for (const [n, x] of totals) if (sys.index.has(n)) v[sys.index.get(n)] = x; return M.heatOf(sys, M.withDaughters(sys, v)); };
  const hE = heat(sysE), hI = heat(M.decaySystem(ND, names));
  check('ENSDF: the decay heat as packed within 2 % of ICRP 107’s', Math.abs(hE / hI - 1) < 0.02, hE / hI);
}

/* ------------------------------------------- real files, when present */
const LOCAL = path.join(HERE, 'local');
if (fs.existsSync(path.join(LOCAL, 'expected.json'))) {
  const exp = JSON.parse(fs.readFileSync(path.join(LOCAL, 'expected.json'), 'utf8'));
  const gone = Object.values(exp.paths).filter((f) => !fs.existsSync(f));
  if (gone.length) {
    console.log(`(local/expected.json names files that are gone: ${gone.join(', ')}; run make-local-fixtures.py again)`);
  } else {
    await realFiles(exp);
  }
} else {
  console.log('(no local/expected.json: the checks on real files are skipped; see README.md)');
}

async function realFiles(exp) {
  let real;
  if (exp.inventoryEntry) {
    /* In a zip archive: read as it unpacks, as the page does. */
    const blob = await fs.openAsBlob(exp.paths.inventory);
    const entry = (await J.zipDirectory(blob)).find((e) => e.name === exp.inventoryEntry);
    real = await J.readInventoryStream(await J.zipEntryStream(blob, entry));
  } else {
    const fd = fs.openSync(exp.paths.inventory, 'r');
    const size = fs.fstatSync(fd).size;
    real = await J.readInventory({ size, read: async (a, b) => { const buf = Buffer.allocUnsafe(b - a); fs.readSync(fd, buf, 0, b - a, a); return new Uint8Array(buf.buffer, buf.byteOffset, buf.length); } });
  }
  check('local: canisters and elements as Python reads them', real.canisters.n === exp.canisters && real.elements.n === exp.elements);
  const S = real.parts.length * real.nuclides.length;
  let worst = 0;
  real.parts.forEach((p, pi) => real.nuclides.forEach((n, k) => {
    let s = 0;
    for (let e = 0; e < real.elements.n; e++) s += real.amounts[e * S + pi * real.nuclides.length + k];
    const want = exp.totals[`${p}:${n}`];
    worst = Math.max(worst, Math.abs(s - want) / Math.max(Math.abs(want), 1e-300));
  }));
  check('local: every part and nuclide totals as Python’s', worst < 1e-12, worst);
  const rinv = new M.Inventory(real, ND);
  const rsys = M.decaySystem(ND, rinv.names());
  const at = rinv.canistersAt(rsys, null, 'local');
  const file = real.canisters.num.decay_heat_W;
  const ratios = Float64Array.from(at.heat, (x, c) => x / file[c]).sort();
  check('local: decay heat from the nuclides is the file’s for the median canister', Math.abs(M.quantileSorted(ratios, 0.5) - 1) < 0.02, M.quantileSorted(ratios, 0.5));
  const lbook = PS.readWorkbook(XLSX.read(fs.readFileSync(exp.paths.workbook), { type: 'buffer' }), XLSX, 'workbook');
  const lavg = lbook.refs.find((r) => r.id === 'workbook:average:all');
  check('local: the workbook’s average canister found', !!lavg && lavg.values.size > 0);
  const lrep = await PS.readReport(new Uint8Array(fs.readFileSync(exp.paths.report)), 'report');
  /* The report's average canisters (Table E-7) are the workbook's, to the report's digits. */
  let worstE7 = 0;
  for (const t of ['BWR', 'PWR']) {
    const w = lbook.refs.find((r) => r.id === `workbook:average:${t}`), r = lrep.refs.find((x) => x.id === `report:average:${t}`);
    for (const [n, v] of r.values) if (v > 0 && w.values.get(n) > 0) worstE7 = Math.max(worstE7, Math.abs(v / w.values.get(n) - 1));
  }
  check('local: the report’s average BWR and PWR canisters are the workbook’s, to its digits', worstE7 < 0.05, worstE7);
  const kinds = (k) => lrep.refs.filter((r) => r.kind === k).length;
  check('local: the report’s tables are all found (D-1, D-2, E-1 to E-7)', lrep.halfLives && lrep.halfLives.values.size === exp.report.halfLives
    && kinds('total') === 5 && kinds('average') === 2 && kinds('canister') === 6, `${lrep.halfLives && lrep.halfLives.values.size} ${kinds('total')} ${kinds('average')} ${kinds('canister')}`);
}

console.log(`\n${checks - failures.length} of ${checks} checks passed.`);
process.exit(failures.length ? 1 : 0);
