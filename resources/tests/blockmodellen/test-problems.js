/* The problems of blockmodellen.html, in Node:

     node resources/tests/blockmodellen/test-problems.js

   Every template is made from many seeds, and each problem is checked
   against itself: the number written at each place in the model is what
   the pieces under that place add up to, the question mark's place adds up
   to the answer, every line of working is the arithmetic it shows, the
   blocks the pupil is asked to draw are the blocks of the model, and the
   text is a well-formed Swedish text whose numbers are the model's. Then
   the lessons, the checks of the pupil's work and the small tools. */
'use strict';

const P = require('../../js/blockmodellen-problems.js');

let checks = 0;
const failures = [];
function check(label, got, want) {
  checks++;
  const ok = want === undefined ? !!got : JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failures.push(label);
    if (failures.length <= 40) console.log(`FAIL  ${label}: ${JSON.stringify(got)}${want === undefined ? '' : ` (expected ${JSON.stringify(want)})`}`);
  }
}
/* Many checks, one line in the summary: the first failure is told. */
function every(label, items, fn) {
  checks++;
  for (const it of items) {
    const why = fn(it);
    if (why) { failures.push(label); console.log(`FAIL  ${label}: ${why}`); return; }
  }
  console.log(`ok    ${label}`);
}

const SEEDS = Number(process.env.BM_SEEDS || 400);
const OWN = { name: 'Lisa', pron: 'hon' };
const isWhole = v => Number.isInteger(v) && v > 0;

/* What a place in the model adds up to. */
function slotValue(p, id) {
  if (id === 'T') return p.rows.filter(r => !r.under).reduce((s, r) => s + r.pieces.reduce((a, pc) => a + pc.w, 0), 0);
  const sp = P.slotPieces(p, id);
  if (!sp) return NaN;
  const pieces = sp.pieces || [sp.row.pieces.findIndex(pc => pc.k === 'bit')];
  return pieces.reduce((s, i) => s + sp.row.pieces[i].w, 0);
}

/* The arithmetic a line of working shows: "48 / 4", "3 · 12", "86 − 18". */
function evaluate(show) {
  const s = String(show).replace(/[   ]/g, '').replace(/·/g, '*').replace(/−/g, '-');
  if (!/^[\d+\-*/]+$/.test(s)) return NaN;
  return Function(`"use strict"; return (${s});`)();
}

const made = [];
for (const t of P.TEMPLATES) {
  for (let seed = 1; seed <= SEEDS; seed++) {
    for (const own of [null, OWN]) {
      try { made.push({ t, seed, own, p: P.make(t.id, seed * 7919 + (own ? 3 : 0), own) }); } catch (e) { made.push({ t, seed, own, error: e.message }); }
    }
  }
}
console.log(`${P.TEMPLATES.length} templates, ${made.length} problems`);

every('every template makes a problem from every seed', made, m => m.error && `${m.t.id} ${m.seed}: ${m.error}`);
const probs = made.filter(m => m.p);
const tag = m => `${m.t.id} seed ${m.p.seed}`;

every('the kinds are the known kinds, and every kind has a template', probs, m => !P.TYPES.some(t => t.id === m.p.type) && `${tag(m)}: kind ${m.p.type}`);
check('every kind has a template', P.TYPES.every(t => P.templatesOf(t.id, 2).length > 0));
check('every kind has a template at level 1', P.TYPES.every(t => P.templatesOf(t.id, 1).length > 0));

every('every number is a whole number above 0: in the text, the pieces, the working, the answer', probs, m => {
  const p = m.p;
  for (const s of p.text) for (const tk of s) if (tk.t === 'n' && !isWhole(tk.v)) return `${tag(m)}: text ${tk.v}`;
  for (const r of p.rows) for (const pc of r.pieces) if (!(pc.w > 0) || (!r.under && !isWhole(pc.w)) || (r.under && !isWhole(pc.w))) return `${tag(m)}: piece ${pc.w}`;
  for (const l of p.calc) if (!isWhole(l.v)) return `${tag(m)}: calc ${l.v}`;
  if (!isWhole(p.answer.v)) return `${tag(m)}: answer ${p.answer.v}`;
  return null;
});

every('each sentence starts with a capital, a number or a fraction, and ends with . or ?', probs, m => {
  for (const s of m.p.text) {
    const first = s[0];
    if (first.t === 'w' && !/^[A-ZÅÄÖ]/.test(first.s)) return `${tag(m)}: "${P.plain(s)}"`;
    const last = s[s.length - 1];
    if (last.t !== 'p' || !/[.?]/.test(last.s)) return `${tag(m)}: "${P.plain(s)}"`;
  }
  return null;
});
every('the question is the last sentence, and the only one that asks', probs, m => {
  const ends = m.p.text.map(s => s[s.length - 1].s);
  return (ends[ends.length - 1] !== '?' || ends.slice(0, -1).includes('?')) && `${tag(m)}: ${P.plainText(m.p)}`;
});
every('no word is empty, doubled or glued to a number', probs, m => {
  const txt = P.plainText(m.p);
  if (/\s\s|\b(\w+) \1\b|\d[a-zåäö]|undefined|null|NaN/i.test(txt.replace(/\b(\d+) \1\b/g, ''))) return `${tag(m)}: ${txt}`;
  return null;
});
every('no answer stands in the text to be copied', probs, m => m.p.text.some(s => s.some(tk => tk.t === 'n' && tk.v === m.p.answer.v)) && `${tag(m)}: ${P.plainText(m.p)}`);
every('two people in a problem have two names', probs, m => {
  const names = m.p.who.map(w => w.label);
  return new Set(names).size !== names.length && `${tag(m)}: ${names}`;
});
every('the pupil\'s own name is used now and then, and never twice', probs.filter(m => m.own), m => {
  const n = P.plainText(m.p).split('Lisa').length - 1;
  return n > 0 && m.p.who.filter(w => w.label === 'Lisa').length > 1 && `${tag(m)}: Lisa twice`;
});
check('the pupil\'s own name is in some problems and not in all', (() => {
  const withName = probs.filter(m => m.own && P.plainText(m.p).includes('Lisa')).length;
  const all = probs.filter(m => m.own).length;
  return withName > all * 0.15 && withName < all * 0.6;
})());

every('every number written into the model is in its sentence', probs, m => {
  for (const [i, f] of m.p.facts.entries()) {
    const tok = m.p.text[f.s].find(tk => tk.t === 'n' && tk.fact === i);
    if (!tok || tok.v !== f.v) return `${tag(m)}: fact ${f.v} in sentence ${f.s}`;
  }
  return null;
});
every('each number is written where the pieces add up to it', probs, m => {
  for (const f of m.p.facts) {
    const v = slotValue(m.p, f.slot);
    if (v !== f.v) return `${tag(m)}: ${f.v} at ${f.slot} adds up to ${v} (${P.plainText(m.p)})`;
  }
  return null;
});
every('the question mark stands where the pieces add up to the answer', probs, m => {
  const v = slotValue(m.p, m.p.ask.slot);
  return v !== m.p.answer.v && `${tag(m)}: ${m.p.ask.slot} adds up to ${v}, answer ${m.p.answer.v}`;
});
every('every line of working is the arithmetic it shows', probs, m => {
  for (const l of m.p.calc) {
    if (l.given) continue;
    const v = evaluate(l.show);
    if (v !== l.v) return `${tag(m)}: ${l.left} → ${l.show} = ${v}, not ${l.v}`;
  }
  return null;
});
every('the working ends in the answer', probs, m => m.p.calc[m.p.calc.length - 1].v !== m.p.answer.v && `${tag(m)}: ${m.p.calc.map(l => l.v)} vs ${m.p.answer.v}`);
every('a line of working given is a number the model shows', probs, m => {
  for (const l of m.p.calc.filter(c => c.given)) {
    if (!m.p.facts.some(f => f.v === l.v) && !m.p.calc.some(c => !c.given && c.v === l.v)) return `${tag(m)}: given ${l.left} ${l.v}`;
  }
  return null;
});
every('the check says the answer', probs, m => !m.p.check.includes(P.fmt(m.p.answer.v)) && `${tag(m)}: ${m.p.check}`);
every('no trap is the answer', probs, m => Object.keys(m.p.answer.traps || {}).some(k => Number(k) === m.p.answer.v) && `${tag(m)}: ${JSON.stringify(m.p.answer.traps)}`);

every('the bits of a model are all the same size, and an extra block\'s parts are too', probs, m => {
  const sizes = new Set(m.p.rows.filter(r => !r.under).flatMap(r => r.pieces.filter(pc => pc.k === 'bit').map(pc => pc.w)));
  if (sizes.size > 1) return `${tag(m)}: bits ${[...sizes]}`;
  for (const r of m.p.rows.filter(rw => rw.under)) {
    const us = new Set(r.pieces.map(pc => pc.w));
    if (us.size > 1) return `${tag(m)}: parts ${[...us]}`;
    const parent = P.rowOf(m.p, r.under.row);
    const span = parent.pieces.slice(r.under.from, r.under.to + 1).reduce((s, pc) => s + pc.w, 0);
    const sum = r.pieces.reduce((s, pc) => s + pc.w, 0);
    if (span !== sum) return `${tag(m)}: the extra block is ${sum}, under ${span}`;
  }
  return null;
});
every('a block the pupil draws has the pieces of the model', probs, m => {
  for (const sub of m.p.build) {
    if (sub.do === 'shape') {
      for (const [k, want] of Object.entries(sub.rows)) {
        const r = P.rowOf(m.p, k);
        if (!r) return `${tag(m)}: no row ${k}`;
        const bits = r.pieces.filter(pc => pc.k === 'bit').length, dels = r.pieces.length - bits;
        if (want.n !== undefined ? r.pieces.length !== want.n : bits !== want.bits || dels !== (want.x || 0)) return `${tag(m)}: ${k} ${JSON.stringify(want)} vs ${bits}+${dels}`;
        if (!P.checkShape(m.p, { rows: { [k]: want } }, { [k]: { bits: want.n !== undefined ? want.n : want.bits, x: want.n !== undefined ? 0 : want.x || 0 } }).ok) return `${tag(m)}: own shape refused`;
      }
    } else {
      const g = m.p.groups.find(gr => gr.id === sub.group);
      if (!g || !g.mark || g.row !== sub.row || g.pieces.length !== sub.count) return `${tag(m)}: mark ${sub.group}`;
    }
  }
  return null;
});
every('every row is drawn by a step: found in step 2, or shaped in step 3', probs, m => {
  const shown = new Set(m.p.who.flatMap(w => w.rows));
  m.p.build.forEach(sub => { if (sub.do === 'shape') Object.keys(sub.rows).forEach(k => shown.add(k)); });
  const missing = m.p.rows.filter(r => !shown.has(r.key)).map(r => r.key);
  return missing.length && `${tag(m)}: ${missing}`;
});
every('every row that is shaped is shaped once, after it is there', probs, m => {
  const seen = new Set();
  for (const sub of m.p.build.filter(s => s.do === 'shape')) for (const k of Object.keys(sub.rows)) { if (seen.has(k)) return `${tag(m)}: ${k} twice`; seen.add(k); }
  return null;
});
every('every who is named in the text, and marked groups do not overlap', probs, m => {
  for (let i = 0; i < m.p.who.length; i++) {
    if (!m.p.text.some(s => s.some(tk => tk.who === i))) return `${tag(m)}: who ${i}`;
  }
  const taken = {};
  for (const g of m.p.groups.filter(gr => gr.mark)) for (const i of g.pieces) {
    const k = `${g.row}.${i}`;
    if (taken[k]) return `${tag(m)}: ${k} in two groups`;
    taken[k] = true;
  }
  return null;
});
every('every step has its words: why for each build step, a message when it is wrong', probs, m => {
  for (const sub of m.p.build) {
    if (!sub.why) return `${tag(m)}: no why`;
    if (sub.do === 'mark' && !sub.msg) return `${tag(m)}: no msg`;
  }
  return null;
});

/* ── The checks of the pupil's work ─────────────────────────────────── */

const fler = P.make('jm-fler', 5, null);
check('jmf: the right shape passes', P.checkShape(fler, fler.build[0], { A: { bits: 1, x: 0 }, B: { bits: 1, x: 1 } }).ok, true);
const twice = P.checkShape(fler, fler.build[0], { A: { bits: 1, x: 0 }, B: { bits: 2, x: 0 } });
check('jmf: "more than" drawn as "twice as much" fails, on the right block', [twice.ok, twice.row], [false, 'B']);
check('jmf: and says why', /fler/.test(twice.msg), true);
check('jmf: a block left as it was fails', P.checkShape(fler, fler.build[0], {}).ok, false);
const dh = P.make('dh-sum', 3, null);
check('part and whole: any two pieces pass', [P.checkShape(dh, dh.build[0], { A: { bits: 2, x: 0 } }).ok, P.checkShape(dh, dh.build[0], { A: { bits: 1, x: 1 } }).ok], [true, true]);
check('part and whole: three pieces fail', P.checkShape(dh, dh.build[0], { A: { bits: 3, x: 0 } }).ok, false);
const br = P.make('br-del', 9, null);
check('a fraction: the numerator\'s count of marks passes', P.checkMark(br, br.build[1], br.build[1].count).ok, true);
check('a fraction: one too many fails', P.checkMark(br, br.build[1], br.build[1].count + 1).ok, false);

check('a row of one piece: the row and the piece are one place', P.sameSlot(fler, 'A', 'A.0'), true);
check('the piece that sticks out is not the whole block', P.sameSlot(fler, 'B', 'B.1'), false);
check('all the blocks together is its own place', [P.sameSlot(fler, 'T', 'T'), P.sameSlot(fler, 'T', 'B')], [true, false]);
const li = P.make('li-dela', 3, null);
check('"any bit" is each of the bits', li.rows[0].pieces.map((_, i) => P.sameSlot(li, 'A.bit', `A.${i}`)).every(Boolean), true);
check('"any bit" is not the whole block', P.sameSlot(li, 'A.bit', 'A'), false);
const kvar = P.make('br-kvar', 4, null);
check('a group of all the pieces left is the same place as those pieces', P.canon(kvar, 'A:kvar'), P.canon(kvar, `A[${P.slotPieces(kvar, 'A:kvar').pieces.join(',')}]`));
check('what a place is called', [P.slotNoun(fler, 'B.1'), P.slotNoun(fler, 'T'), P.slotNoun(dh, 'A')], ['biten som sticker ut', 'båda blocken tillsammans', 'hela blocket']);

/* ── The lessons ────────────────────────────────────────────────────── */

const tids = new Set(P.TEMPLATES.map(t => t.id));
every('every lesson\'s problems are templates, and its cards are written', P.LESSONS, l => {
  for (const it of [...(l.items || []), ...(l.fill || []), ...(l.demo ? [l.demo] : [])]) if (!tids.has(it[0])) return `${l.id}: ${it[0]}`;
  if (l.cards && !P.LEARN[l.cards]) return `${l.id}: cards ${l.cards}`;
  return null;
});
check('lesson ids are unique', new Set(P.LESSONS.map(l => l.id)).size, P.LESSONS.length);
check('every kind has its chapter of three lessons', P.TYPES.every(t => {
  const u = P.UNITS.find(un => un.type === t.id);
  return u && ['learn', 'build', 'solve'].every(k => u.lessons.some(l => l.kind === k));
}), true);
check('a chapter\'s problems are of its kind', P.UNITS.filter(u => u.type).every(u => u.lessons.every(l => [...(l.items || []), ...(l.fill || []), ...(l.demo ? [l.demo] : [])].every(it => P.TEMPLATES.find(t => t.id === it[0]).type === u.type))), true);
every('every worked example is made from its seed', P.LESSONS.filter(l => l.demo), l => {
  try { P.make(l.demo[0], l.demo[1], null); return null; } catch (e) { return `${l.id}: ${e.message}`; }
});
check('the eight steps', P.STEPS.map(s => s.n), [1, 2, 3, 4, 5, 6, 7, 8]);
every('every card has a title and text, and its picture\'s numbers are where they can be drawn', Object.entries(P.LEARN).flatMap(([k, cards]) => cards.map(c => [k, c])), ([k, c]) => {
  if (!c.title || !c.text || !c.text.length) return `${k}: ${c.title}`;
  if (c.pic) for (const sid of Object.keys(c.pic.values)) if (sid !== 'T' && P.slotPieces(c.pic, sid) === undefined) return `${k}: ${sid}`;
  return null;
});

const r = P.rng(42);
const mixes = Array.from({ length: 200 }, () => P.mixed(r, 6, 2));
every('a mixed set: six problems, no kind twice in a row, none more than twice', mixes, set => {
  if (set.length !== 6) return `${set.length}`;
  const types = set.map(it => P.TEMPLATES.find(t => t.id === it[0]).type);
  for (let i = 1; i < types.length; i++) if (types[i] === types[i - 1]) return types.join(',');
  const n = {};
  for (const t of types) { n[t] = (n[t] || 0) + 1; if (n[t] > 2) return types.join(','); }
  return null;
});
check('an easy mixed set has only level 1 problems', P.mixed(P.rng(3), 6, 1).every(it => P.TEMPLATES.find(t => t.id === it[0]).level === 1), true);
every('"which model fits": four kinds, the right one among them, none drawn like it', P.TYPES.flatMap(t => Array.from({ length: 30 }, (_, i) => [t.id, i])), ([type, i]) => {
  const ch = P.modelChoices(P.rng(i + 1), type);
  if (ch.length !== 4 || new Set(ch).size !== 4 || !ch.includes(type)) return `${type}: ${ch}`;
  return null;
});

/* ── Small tools ────────────────────────────────────────────────────── */

check('numbers as Swedes write them', [P.fmt(5), P.fmt(999), P.fmt(1200), P.fmt(12345)], ['5', '999', '1 200', '12 345']);
check('numbers as pupils type them', ['36', ' 1 200 ', '36 kr', '12,0', '7.5', 'tolv', '', '3/4', '1e3', '−4'].map(P.parseNumber), [36, 1200, 36, 12, 7.5, null, null, null, null, -4]);
check('fractions read aloud', [P.fracWords(1, 2), P.fracWords(3, 5), P.fracWords(1, 3), P.fracWords(2, 3), P.fracWords(5, 8)], ['en halv', 'tre femtedelar', 'en tredjedel', 'två tredjedelar', 'fem åttondelar']);
check('a problem read aloud says its fractions in words', P.plainText(P.make('br-del', 2, null), true).match(/\d+\/\d+/), null);
check('the same seed makes the same problem', P.plainText(P.make('gg-tills', 77, null)), P.plainText(P.make('gg-tills', 77, null)));
check('another seed makes another problem', P.plainText(P.make('gg-tills', 77, null)) !== P.plainText(P.make('gg-tills', 78, null)), true);

console.log(`\n${checks - failures.length} of ${checks} checks passed.`);
process.exit(failures.length ? 1 : 0);
