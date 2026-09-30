#!/usr/bin/env node
/*
  The card sets of winnetkakort.html, without a page: every answer is right,
  the piles hold what their names say, the progress grids find every cell,
  a typed answer is read the way a Swedish child writes it, and no hint gives
  its own answer away.

      node resources/tests/winnetkakort/test-sets.js

  Exit status 0 when every check passes.
*/
'use strict';
const path = require('path');
const S = require(path.join(__dirname, '../../js/winnetkakort-sets.js'));

let checks = 0;
const failures = [];
function check(label, got, want = true) {
  checks++;
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok ? '' : `: ${JSON.stringify(got)} (expected ${JSON.stringify(want)})`}`);
  if (!ok) failures.push(label);
}

const sizes = Object.fromEntries(S.allSets.map(s => [s.id, s.facts.length]));
const facts = S.allSets.flatMap(s => s.facts);

// --- the piles --------------------------------------------------------------
check('six groups', S.GROUPS.map(g => g.id), ['inom10', 'inom20', 'storre', 'ganger', 'delat', 'mer']);
check('lilla plus is every sum of 1–9 up to 10, stora plus every one from 11', [sizes.lp, sizes.sp], [45, 36]);
check('lilla and stora minus mirror them', [sizes.lm, sizes.sm], [45, 36]);
check('tiokompisar 0–10 and minus från 10', [sizes.tio, sizes.m10], [11, 11]);
check('a table is ten cards, all tables a hundred', [sizes.t7, sizes.tall, sizes.t15 + sizes.t610], [10, 100, 100]);
check('division by 2–10, ten each', [sizes.d7, sizes.dall], [10, 90]);
check('no pile holds a fact twice',
  S.allSets.filter(s => new Set(s.facts.map(f => f.key)).size !== s.facts.length).map(s => s.id), []);
check('set ids are unique', new Set(S.allSets.map(s => s.id)).size, S.allSets.length);
check('lilla plus sums stay within 10 and stora plus crosses it',
  [S.setById.lp.facts.every(f => f.c <= 10), S.setById.sp.facts.every(f => f.c >= 11 && f.a <= 9 && f.b <= 9)], [true, true]);
check('stora minus is a tens crossing with a one-digit answer',
  S.setById.sm.facts.every(f => f.a >= 11 && f.a <= 18 && f.b <= 9 && f.c <= 9 && f.c >= 1), true);
check('plus 1 och 2 holds only facts with a 1 or a 2', S.setById.p12.facts.every(f => Math.min(f.a, f.b) <= 2), true);
check('dubblor och nästan dubblor inom 20 differ by at most one',
  S.setById.dub20.facts.every(f => Math.abs(f.a - f.b) <= 1 && f.c >= 11), true);
check('the 7:ans tabell is 1 · 7 … 10 · 7', S.setById.t7.facts.map(f => f.c), [7, 14, 21, 28, 35, 42, 49, 56, 63, 70]);
check('a fact in two piles has one key: 8 + 7 in stora plus and in dubblor',
  S.setById.sp.facts.some(f => f.key === 'add:8:7') && S.setById.dub20.facts.some(f => f.key === 'add:8:7'), true);

// --- every answer is right --------------------------------------------------
const calc = { '+': (a, b) => a + b, '-': (a, b) => a - b, '*': (a, b) => a * b, '/': (a, b) => a / b };
check('every operation answers itself',
  facts.filter(f => f.kind === 'op' && !S.sameNumber(calc[f.op](f.a, f.b), f.c)).map(f => f.key), []);
check('division always comes out even in the division piles',
  S.GROUPS.find(g => g.id === 'delat').sets.flatMap(s => s.facts).filter(f => !Number.isInteger(f.c)).map(f => f.key), []);
check('every text card has exactly one blank',
  facts.filter(f => f.kind === 'text' && f.tokens.filter(t => t === S.BLANK).length !== 1).map(f => f.key), []);
const spot = {
  'dbl:25': 50, 'half:30': 15, 'sq:12': 144, 'sqrt:81': 9, 'of:3/4:20': 15, 'of:2/3:30': 20,
  'pct:10:45': 4.5, 'pct:75:40': 30, 'f2p:1/20': 5, 'd2p:0.05': 5, 'p2d:40': 0.4, 'f2d:1/5': 0.2,
};
check('the text cards, spot-checked', Object.keys(spot).filter(k => !S.sameNumber(S.factByKey[k].answer, spot[k])), []);
check('tiopotenser in floating point come out exact',
  S.setById.tiop.facts.map(f => f.c), [70, 450, 35, 8, 600, 240, 5, 3000, 1200, 250, 7, 45, 3.6, 0.5, 8, 2.5, 0.04, 6, 1.5, 0.3]);
check('negative numbers: 3 − 5, −8 + 8, 5 − (−2), −6 − (−2)',
  ['sub:3:5', 'add:-8:8', 'sub:5:-2', 'sub:-6:-2'].map(k => S.factByKey[k].c), [-2, 0, 7, -4]);

// --- question forms -----------------------------------------------------------
const f = S.factByKey['add:7:8'];
check('a ∘ b = ? asks for c', S.question(f, 'c').answer, 15);
check('a ∘ ? = c asks for b', S.question(f, 'b').answer, 8);
check('? ∘ b = c asks for a', S.question(f, 'a').answer, 7);
check('the blank is where the form says',
  ['c', 'b', 'a'].map(form => S.question(f, form).tokens.indexOf(S.BLANK)), [4, 2, 0]);
check('a tiokompis is asked with the missing addend', S.plainText(S.question(S.factByKey['tio:3'], 'b').tokens), '3 + ? = 10');
const always = () => 0.99;
check('"Vanliga" asks each pile its own way',
  [S.pickForm(f, 'vanlig', always), S.pickForm(S.factByKey['tio:3'], 'vanlig', always)], ['c', 'b']);
check('"Saknat tal" never asks for the result', [0, 0.4, 0.99].map(r => S.pickForm(f, 'saknat', () => r)), ['b', 'b', 'a']);
check('"Blandat" can ask all three', [0, 0.4, 0.99].map(r => S.pickForm(f, 'blandat', () => r)), ['c', 'b', 'a']);
check('negative numbers are only asked straight', S.pickForm(S.factByKey['sub:3:5'], 'saknat', always), 'c');
check('text cards have no other form', S.pickForm(S.factByKey['dbl:7'], 'blandat', always), 'text');
check('a negative second term is written in brackets', S.plainText(S.question(S.factByKey['sub:5:-2'], 'c').tokens), '5 − (−2) = ?');
check('the back of the card is the whole statement', S.plainText(S.statement(S.factByKey['mul:6:7']).tokens), '6 · 7 = 42');
check('× and ÷ when chosen', S.plainText(S.question(S.factByKey['div:42:6'], 'c').tokens, 'kryss'), '42 ÷ 6 = ?');
check('percent hugs its number', S.plainText(S.question(S.factByKey['f2p:1/4'], 'text').tokens), '¼ = ? %');
check('decimal comma', S.plainText(S.statement(S.factByKey['p2d:25']).tokens), '25 % = 0,25');
check('numbers of five digits and more are grouped, four digits not', [S.fmtPlain(6000), S.fmtPlain(12000)], ['6000', '12 000']);

// --- the progress grids find every cell --------------------------------------
const grid = (rows, cols, key) => rows.flatMap(r => cols.map(c => key(r, c))).filter(k => !S.factByKey[k]);
const r19 = [1, 2, 3, 4, 5, 6, 7, 8, 9], r110 = [...r19, 10];
check('plus grid 1–9 × 1–9', grid(r19, r19, (a, b) => `add:${a}:${b}`), []);
check('minus grid: subtrahend × difference 1–9', grid(r19, r19, (b, c) => `sub:${b + c}:${b}`), []);
check('times grid 1–10 × 1–10', grid(r110, r110, (k, n) => `mul:${k}:${n}`), []);
check('division grid: divisor 2–10 × quotient 1–10', grid(r110.slice(1), r110, (n, q) => `div:${n * q}:${n}`), []);

// --- reading an answer ---------------------------------------------------------
const reads = ['15', ' 15 ', '3,5', '3.5', '−4', '-4', '–4', '4 500', '4 500', '50%', ',5', '', 'abc', '1,2,3', '--4', '7 8'];
check('typed answers', reads.map(S.parseAnswer), [15, 15, 3.5, 3.5, -4, -4, -4, 4500, 4500, 50, 0.5, null, null, null, null, 78]);

// --- no hint gives its answer away --------------------------------------------
// A hint may repeat a number the question itself shows (5² = ? may say 5 · 5),
// but not the answer when the question hides it.
const unglyph = s => Object.entries(S.FRACTION_GLYPHS).reduce((out, [pq, glyph]) => out.split(glyph).join(pq), s);
const numbersIn = s => (unglyph(s).replace(/(\d),(\d)/g, '$1.$2').match(/−?\d+(\.\d+)?/g) || []).map(x => Number(x.replace('−', '-')));
const leaks = [];
const missing = [];
for (const fact of facts) {
  const forms = fact.kind === 'op' ? fact.forms : ['text'];
  for (const form of forms) {
    const q = S.question(fact, form);
    const h = S.hint(fact, form);
    if (!h.text) { missing.push(`${fact.set} ${fact.key} ${form}`); continue; }
    const shown = numbersIn(S.plainText(q.tokens));
    const said = numbersIn(h.text);
    if (said.some(x => S.sameNumber(x, q.answer)) && !shown.some(x => S.sameNumber(x, q.answer))) {
      leaks.push(`${fact.set} ${S.plainText(q.tokens)}: ${h.text}`);
    }
  }
}
check('every card has a hint in every form it is asked in', missing, []);
check('no hint says the answer', leaks, []);
check('tiokompisar and sums within 20 have tiorutor',
  [S.hint(S.factByKey['tio:3'], 'b').pic?.type, S.hint(S.factByKey['add:8:7'], 'c').pic?.type, S.hint(S.factByKey['sub:13:5'], 'c').pic?.crossed],
  ['ten', 'ten', 5]);
check('a missing number has no picture to count from', S.hint(S.factByKey['add:8:7'], 'b').pic, null);
check('the tables have rows of dots, division too',
  [S.hint(S.factByKey['mul:6:7'], 'c').pic, S.hint(S.factByKey['div:42:6'], 'c').pic],
  [{ type: 'array', rows: 6, cols: 7 }, { type: 'array', rows: 7, cols: 6 }]);
check('negative numbers get the number line, not tiorutor', S.hint(S.factByKey['sub:3:5'], 'c').pic, { type: 'line', mark: 3 });

console.log(`\n${checks - failures.length} of ${checks} checks passed.`);
process.exit(failures.length ? 1 : 0);
