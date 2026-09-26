#!/usr/bin/env node
/* The formula language of smui.html (resources/js/smui-formula.js)
   outside the browser: smui-util.js, smui-table.js and smui-formula.js run
   in a node vm context, as the page loads them.

   Checked: operator precedence and associativity, missing values as JMP has
   them, error messages and their positions, every function against values
   worked out independently, the Col functions with By groups against
   direct computations (JMP's quantiles are numpy's 'weibull'), formula
   columns that recalculate in dependency order when their inputs change,
   refuse cycles, follow renames and survive a JSON round trip, random
   numbers that repeat with the column's seed, that no expression reaches a
   JavaScript name, and the speed over 100 000 rows.

       node resources/tests/smui/test-formula.js

   Exit status 0 when every check passes. */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const JS = path.join(__dirname, '..', '..', 'js');
const sandbox = { console };
sandbox.self = sandbox;
vm.createContext(sandbox);
for (const f of ['smui-util.js', 'smui-table.js', 'smui-formula.js']) {
  vm.runInContext(fs.readFileSync(path.join(JS, f), 'utf8'), sandbox, { filename: f });
}
const SM = sandbox.SM;
const F = SM.formula;

/* ---- checks ------------------------------------------------------------------ */
let n = 0;
const failed = [];
function same(a, b) {
  if (typeof a === 'number' && typeof b === 'number') return (Number.isNaN(a) && Number.isNaN(b)) || a === b;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => same(x, b[i]));
  return a === b;
}
function check(label, got, want) {
  n++;
  const ok = same(got, want);
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok ? '' : `: ${JSON.stringify(got)} (expected ${JSON.stringify(want)})`}`);
  if (!ok) failed.push(label);
  return ok;
}
function near(label, got, want, tol = 1e-12) {
  n++;
  const ok = typeof got === 'number' && Math.abs(got - want) <= tol * Math.max(1, Math.abs(want));
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}: ${got}${ok ? '' : ` (expected ${want})`}`);
  if (!ok) failed.push(label);
  return ok;
}
function throwsAt(label, fn, pos, re) {
  n++;
  let e = null;
  try { fn(); } catch (x) { e = x; }
  const ok = !!e && e.name === 'FormulaError' && (pos == null || e.pos === pos) && (!re || re.test(e.message));
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok ? `: ${e.message}` : `: ${e ? `${e.name} at ${e.pos}: ${e.message}` : 'no error'}`}`);
  if (!ok) failed.push(label);
  return ok;
}

/* ---- a small table ------------------------------------------------------------------ */
const t = new SM.Table({ name: 'T', columns: [
  { name: 'x', dataType: 'numeric', values: [4, 1, NaN, 3, 3, 10] },
  { name: 'g', dataType: 'character', values: ['a', 'b', 'a', 'b', 'a', null] },
  { name: 'name', dataType: 'character', values: ['Ann', 'bo', '', 'Cy D', 'eve', 'Fay'] },
  { name: 'weight (kg)', dataType: 'numeric', values: [60, 70, 80, NaN, 50, 65] },
  { name: 'when', dataType: 'numeric', format: { kind: 'date' }, values: [Date.UTC(2024, 1, 29), Date.UTC(2023, 11, 31), NaN, Date.UTC(2024, 0, 1), Date.UTC(2024, 6, 4, 13, 45, 30), Date.UTC(2020, 5, 15)] },
] });
const v = (expr, row = 0) => F.evaluate(t, expr, [row])[0];
const all = (expr) => Array.from(F.evaluate(t, expr));

/* ---- precedence and associativity ------------------------------------------------- */
check('1 + 2 * 3', v('1 + 2 * 3'), 7);
check('(1 + 2) * 3', v('(1 + 2) * 3'), 9);
check('-2^2 is -4 (power before negation)', v('-2^2'), -4);
check('2^-1', v('2^-1'), 0.5);
check('2^3^2 is 2^9 (right to left)', v('2^3^2'), 512);
check('10 - 4 - 3 (left to right)', v('10 - 4 - 3'), 3);
check('12 / 2 / 3', v('12 / 2 / 3'), 2);
check('2 * 3 == 6: arithmetic before comparison', v('2 * 3 == 6'), 1);
check('1 | 0 & 0: & before |', v('1 | 0 & 0'), 1);
check('(1 | 0) & 0', v('(1 | 0) & 0'), 0);
check('!0', v('!0'), 1);
check('!2', v('!2'), 0);
check('!1 + 1: not before +', v('!1 + 1'), 1);
check('chained 1 < 2 < 3', v('1 < 2 < 3'), 1);
check('chained 1 < 3 < 2', v('1 < 3 < 2'), 0);
check('chained 3 >= 3 > 1', v('3 >= 3 > 1'), 1);
check('= is ==', v('1 = 1'), 1);
check('!= and ≠', [v('1 != 2'), v('1 ≠ 1')], [1, 0]);
check('|| joins text, looser than +', v('1 + 2 || "x"'), '3x');
check('Unicode operators − × ÷ ≤', [v('7 − 2'), v('3 × 4'), v('8 ÷ 2'), v('2 ≤ 2')], [5, 12, 4, 1]);
check('** is ^', v('2 ** 3'), 8);
check('comments', v('1 + /* two */ 2 // three'), 3);
check('a trailing semicolon', v('4;'), 4);
check('scientific numbers', [v('1.5e3'), v('.5'), v('5.')], [1500, 0.5, 5]);
check('text escapes', [v('"a\\"b"'), v('"\\!"q\\!""'), v('\'single\'')], ['a"b', '"q"', 'single']);

/* ---- column references --------------------------------------------------------- */
check(':x', all(':x'), [4, 1, NaN, 3, 3, 10]);
check('a bare name that is a column', v('x + 1'), 5);
check(':"weight (kg)"', v(':"weight (kg)" / 2'), 30);
check(':Name("weight (kg)")', v(':Name("weight (kg)")'), 60);
check('Column("weight (kg)") and As Column', [v('Column("weight (kg)")'), v('As Column("x")')], [60, 4]);
check('names ignore case and runs of spaces', v(':"WEIGHT  (KG)"'), 60);
check('a row subscript :x[2]', v(':x[2]'), 1);
check(':x[Row() - 1] is Lag', all(':x[Row() - 1]'), [NaN, 4, 1, NaN, 3, 3]);

/* ---- missing values ------------------------------------------------------------------ */
check('. + 1 is missing', v('. + 1'), NaN);
check('. < 3 is missing', v('. < 3'), NaN);
check('. == . is missing', v('. == .'), NaN);
check('0 & . is 0', v('0 & .'), 0);
check('1 & . is missing', v('1 & .'), NaN);
check('. & 0 is 0', v('. & 0'), 0);
check('1 | . is 1', v('1 | .'), 1);
check('0 | . is missing', v('0 | .'), NaN);
check('!. is missing', v('!.'), NaN);
check('1/0 and 0/0 are missing', [v('1/0'), v('0/0')], [NaN, NaN]);
check('If with a missing condition is missing', v('If(., 1, 2)'), NaN);
check('If(0, 1, 2)', v('If(0, 1, 2)'), 2);
check('If with no else and no true condition', v('If(0, 1)'), NaN);
check('If with several conditions', v('If(0, 1, 1, 2, 3)'), 2);
check('IfMZ counts missing as false', v('IfMZ(., 1, 2)'), 2);
check('If on a column: row with x missing', all('If(:x > 3, "big", "small")'), ['big', 'small', null, 'small', 'small', 'big']);
check('Sum(1, ., 2) skips missing', v('Sum(1, ., 2)'), 3);
check('Sum(., .) is missing', v('Sum(., .)'), NaN);
check('Mean(1, ., 3)', v('Mean(1, ., 3)'), 2);
check('Min(3, ., 1), Max(3, ., 1)', [v('Min(3, ., 1)'), v('Max(3, ., 1)')], [1, 3]);
check('Std Dev(1, 2, 3, .)', v('Std Dev(1, 2, 3, .)'), 1);
check('Number(1, ., "a", "")', v('Number(1, ., "a", "")'), 2);
check('N Missing(1, ., "")', v('N Missing(1, ., "")'), 2);
check('Is Missing(.), ("") and (0)', [v('Is Missing(.)'), v('Is Missing("")'), v('Is Missing(0)')], [1, 1, 0]);
check('Is Missing(:name) on an empty cell', v('Is Missing(:name)', 2), 1);
check('text comparisons are not missing: "" == "a"', v('"" == "a"'), 0);
check('comparison of a missing number with a column', all(':x > 2'), [1, 0, NaN, 1, 1, 1]);

/* ---- errors and where they are ------------------------------------------------------ */
throwsAt('1 + (nothing after the operator)', () => F.parse('1 +'), 3, /expected a value/);
throwsAt('unknown function', () => F.parse('foo(1)'), 0, /no function “foo”/);
throwsAt('an unclosed parenthesis', () => F.parse('(1 + 2'), 6, /expected “\)”/);
throwsAt('two values in a row', () => F.parse('1 2'), 2, /did not expect the number 2/);
throwsAt('an unclosed text', () => F.parse('"abc'), 0, /not closed/);
throwsAt('If needs two arguments', () => F.parse('If(1)'), 0, /If needs at least 2 arguments/);
throwsAt('Sqrt takes one', () => F.parse('Sqrt(1, 2)'), 0, /at most 1 argument/);
throwsAt('a number running into a name', () => F.parse('2x + 1'), 0, /neither a number nor a name/);
throwsAt('a character that is not part of formulas', () => F.parse('1 ? 2'), 2, /“\?” is not part/);
throwsAt('no such column', () => F.evaluate(t, '1 + :nosuch'), 4, /no column “nosuch”/);
throwsAt('a bare name that is no column', () => F.evaluate(t, 'hieght * 2'), 0, /no column or name “hieght”/);
throwsAt('arithmetic on text', () => F.evaluate(t, ':x + :name'), 5, /Addition \(\+\) needs a number, and :name is text/);
throwsAt('comparing a number with text', () => F.evaluate(t, ':x == "a"'), 3, /compares a number with text/);
throwsAt('a condition of text', () => F.evaluate(t, 'If(:name, 1, 2)'), 3, /needs a number/);
throwsAt('Match of a number against text', () => F.evaluate(t, 'Match(:x, "a", 1)'), 10, /Match compares a number with text/);
throwsAt('a subscript on something that is not a column', () => F.parse('(1 + 2)[1]'), 7, /only a column/);
throwsAt('an unknown option', () => F.parse('Col Mean(:x, <<Tie("average"))'), 13, /no option Tie/);
throwsAt('a wrong Tie', () => F.evaluate(t, 'Col Rank(:x, <<Tie("sideways"))'), 13, /Tie takes/);
throwsAt('the empty formula', () => F.parse('   '), null, /empty/);
throwsAt(':: is not a formula', () => F.parse('::x'), 0, /::/);

/* ---- no way out to JavaScript ------------------------------------------------------ */
sandbox.pwned = 0;
for (const src of ['constructor', '__proto__', 'alert(1)', 'constructor.constructor("return 1")()', 'toString()', 'this', 'globalThis', 'window.alert(1)',
  ':__proto__', 'Column("constructor")', 'hasOwnProperty(1)', 'valueOf()', 'eval("1")', 'Function("return 1")', 'pwned = 1', 'Include("x")', 'Parse("1")', 'x[0].constructor']) {
  let err = null;
  try { F.evaluate(t, src); } catch (e) { err = e; }
  check(`${src} is refused`, !!err && err.name === 'FormulaError', true);
}
check('nothing was changed outside', sandbox.pwned, 0);
check('Object.prototype is untouched', Object.keys(Object.prototype).length, 0);
throwsAt('deep nesting is refused, not a stack overflow', () => F.parse(`${'('.repeat(5000)}1${')'.repeat(5000)}`), null, /nested too deeply/);
throwsAt('a formula over 50 000 characters', () => F.parse(`1${' + 1'.repeat(20000)}`), null, /too long/);
throwsAt('a text that would take all the memory', () => F.evaluate(t, 'Repeat("ab", 1e9)'), null, /longer than/);
{
  const t2 = new SM.Table({ columns: [{ name: 'constructor', dataType: 'numeric', values: [5] }, { name: '__proto__', dataType: 'numeric', values: [6] }] });
  check('a column may be named constructor or __proto__', [F.evaluate(t2, 'constructor + 1')[0], F.evaluate(t2, ':__proto__ * 2')[0]], [6, 12]);
}

/* ---- every function ------------------------------------------------------------------ */
const E = [
  ['Abs(-3)', 3], ['Ceiling(2.1)', 3], ['Floor(-0.5)', -1], ['Round(3.555, 2)', 3.56], ['Round(3.554, 2)', 3.55], ['Round(-2.5)', -3], ['Round(2.5)', 3],
  ['Round(1234.5, -2)', 1200], ['Round(1.005, 2)', 1.01], ['Modulo(7, 3)', 1], ['Mod(-7, 3)', -1], ['Modulo(7, 0)', NaN], ['Sign(-2)', -1],
  ['Power(3)', 9], ['Power(2, 10)', 1024], ['Root(27, 3)', 3], ['Root(-8, 3)', -2], ['Root(16)', 4], ['Sqrt(-1)', NaN], ['Sqrt(9)', 3],
  ['Exp(0)', 1], ['Log(Exp(2))', 2], ['Log(8, 2)', 3], ['Log(0)', NaN], ['Log(-1)', NaN], ['Log10(1000)', 3], ['Log2(8)', 3], ['Log1P(0)', 0],
  ['Squash(0)', 0.5], ['Logit(0.5)', 0], ['Sine(0)', 0], ['Cos(0)', 1], ['Tangent(0)', 0], ['ArcSine(1)', Math.PI / 2], ['ArcCosine(1)', 0],
  ['ArcTangent(1)', Math.PI / 4], ['ArcTangent(1, -1)', 3 * Math.PI / 4], ['Pi()', Math.PI], ['e()', Math.E], ['Empty()', NaN],
  ['Char(1/3)', '0.333333333333333'], ['Char(2)', '2'], ['Char(.)', '.'], ['Char(3.14159, 5, 2)', '3.14'], ['Char(-0.5)', '-0.5'],
  ['Num("2.5")', 2.5], ['Num("x")', NaN], ['Num(" 7 ")', 7], ['Concat("a", 1, "b")', 'a1b'], ['"a" || .', 'a'],
  ['Substr("abcdef", 2, 3)', 'bcd'], ['Substr("abcdef", -2)', 'ef'], ['Substr("abc", 5)', null], ['Left("abc", 2)', 'ab'], ['Right("abc", 2)', 'bc'],
  ['Uppercase("aB")', 'AB'], ['Lowercase("aB")', 'ab'], ['Titlecase("hello wORLD")', 'Hello World'], ['Trim("  a b  ")', 'a b'],
  ['Trim("  a ", "left")', 'a '], ['Trim Whitespace(" a ")', 'a'], ['Collapse Whitespace("  a   b ")', 'a b'],
  ['Contains("banana", "an")', 2], ['Contains("banana", "an", 3)', 4], ['Contains("banana", "x")', 0], ['Contains("banana", "an", -1)', 4],
  ['Starts With("abc", "ab")', 1], ['Ends With("abc", "x")', 0], ['Word(2, "the quick  brown")', 'quick'], ['Word(-1, "a b c")', 'c'],
  ['Word(2, "a,b,,c", ",")', 'b'], ['Item(3, "a,b,,c", ",")', null], ['Item(4, "a,b,,c", ",")', 'c'], ['Length("héllo")', 5],
  ['Substitute("a-b-c", "-", "+")', 'a+b+c'], ['Substitute("abc", "a", "x", "b", "y")', 'xyc'], ['Repeat("ab", 3)', 'ababab'], ['Reverse("abc")', 'cba'],
  ['Match(2, 1, "a", 2, "b", "c")', 'b'], ['Match(9, 1, "a", 2, "b", "c")', 'c'], ['Match(., ., "m", "n")', 'm'], ['Match(., 1, "a")', null],
  ['Match("y", "x", 1, "y", 2)', 2], ['Choose(2, "a", "b")', 'b'], ['Choose(3, "a", "b")', null],
  ['And(1, 1)', 1], ['And(1, 0)', 0], ['And(1, .)', NaN], ['Or(0, .)', NaN], ['Or(1, .)', 1], ['Not(0)', 1], ['AndMZ(1, .)', 0], ['OrMZ(0, .)', 0],
  ['Zero Or Missing(0)', 1], ['Zero Or Missing(.)', 1], ['Zero Or Missing(2)', 0], ['Median(3, 1, 2, .)', 2], ['Median(1, 2, 3, 4)', 2.5],
  ['Normal Quantile(0.5, 10, 2)', 10],
  ['Date MDY(2, 29, 2024)', Date.UTC(2024, 1, 29)], ['Date DMY(29, 2, 2024)', Date.UTC(2024, 1, 29)], ['Year(Date MDY(2, 29, 2024))', 2024],
  ['Month(Date MDY(2, 29, 2024))', 2], ['Day(Date MDY(2, 29, 2024))', 29], ['Day Of Week(Date MDY(2, 29, 2024))', 5], ['Day Of Year(Date MDY(2, 29, 2024))', 60],
  ['Week Of Year(Date MDY(2, 29, 2024))', 9], ['Week Of Year(Date MDY(1, 6, 2024))', 1], ['Week Of Year(Date MDY(1, 7, 2024))', 2], ['Quarter(Date MDY(8, 1, 2024))', 3],
  ['In Days(2)', 2 * 86400000], ['In Hours()', 3600000], ['In Minutes(3)', 180000], ['In Weeks(1)', 7 * 86400000], ['In Years(1)', 365.25 * 86400000],
  ['Date MDY(1, 1, 2024) + In Days(31)', Date.UTC(2024, 1, 1)],
];
for (const [src, want] of E) check(src, v(src), want);
const tm = Date.UTC(2024, 6, 4, 13, 45, 30);
check('Hour, Minute, Second of a date and time', [v(`Hour(${tm})`), v(`Minute(${tm})`), v(`Second(${tm})`)], [13, 45, 30]);
check('Row() and N Row()', [all('Row()'), v('N Row()')], [[1, 2, 3, 4, 5, 6], 6]);
check('Lag(:x)', all('Lag(:x)'), [NaN, 4, 1, NaN, 3, 3]);
check('Lag(:x, 2)', all('Lag(:x, 2)'), [NaN, NaN, 4, 1, NaN, 3]);
check('Lag(:x, -1) looks ahead', all('Lag(:x, -1)'), [1, NaN, 3, 3, 10, NaN]);
check('Lag of text', all('Lag(:g)'), [null, 'a', 'b', 'a', 'b', 'a']);
check('Dif(:x)', all('Dif(:x)'), [NaN, -3, NaN, NaN, 0, 7]);
check('Sequence(1, 3)', all('Sequence(1, 3)'), [1, 2, 3, 1, 2, 3]);
check('Sequence(1, 5, 2, 2)', all('Sequence(1, 5, 2, 2)'), [1, 1, 3, 3, 5, 5]);
check('Year of a date column', all('Year(:when)'), [2024, 2023, NaN, 2024, 2024, 2020]);
check('Today() is now', Math.abs(v('Today()') - Date.now()) < 5000, true);
near('Normal Density(0)', v('Normal Density(0)'), 1 / Math.sqrt(2 * Math.PI), 1e-15);
near('Normal Distribution(1.96)', v('Normal Distribution(1.96)'), 0.9750021048517795, 1e-14);
near('Normal Distribution(-3)', v('Normal Distribution(-3)'), 0.0013498980316300946, 1e-13);
near('Normal Distribution(-5)', v('Normal Distribution(-5)'), 2.866515718791939e-7, 1e-12);
near('Normal Distribution(-8)', v('Normal Distribution(-8)'), 6.22096057427178e-16, 1e-12);
near('Normal Distribution(0.5, 0, 1)', v('Normal Distribution(0.5, 0, 1)'), 0.6914624612740131, 1e-14);
near('Normal Quantile(0.975)', v('Normal Quantile(0.975)'), 1.959963984540054, 1e-13);
near('Normal Quantile(1e-10)', v('Normal Quantile(1e-10)'), -6.361340902404056, 1e-12);
check('And(), Or() and If() of a missing column value', all('If(:x > 3 & :g == "a", 1, 0)'), [1, 0, NaN, 0, 0, 0]);

/* ---- the Col functions, with and without By -------------------------------------------- */
{
  const r = SM.util.rng('col-functions');
  const N = 500;
  const x = [], g = [], h = [];
  for (let i = 0; i < N; i++) {
    x.push(i % 17 === 0 ? NaN : Math.round(r.normal(10, 3) * 4) / 4);   // ties, and missing values
    g.push(['p', 'q', 'r'][Math.floor(r.u() * 3)]);
    h.push(i % 23 === 0 ? null : ['u', 'v'][i % 2]);
  }
  const T = new SM.Table({ columns: [{ name: 'x', dataType: 'numeric', values: x }, { name: 'g', dataType: 'character', values: g }, { name: 'h', dataType: 'character', values: h }] });
  const ev = (e) => Array.from(F.evaluate(T, e));
  const groupsOf = (keys) => { const m = new Map(); keys.forEach((k, i) => { const kk = k == null ? '' : k; if (!m.has(kk)) m.set(kk, []); m.get(kk).push(i); }); return m; };
  // numpy's 'weibull': virtual index p(n + 1) − 1, clipped, linear between order statistics
  const weibull = (vals, p) => { const s = vals.filter((y) => !Number.isNaN(y)).sort((a, b) => a - b); const nn = s.length; const vi = Math.min(Math.max(p * (nn + 1) - 1, 0), nn - 1); const lo = Math.floor(vi); const hi = Math.min(lo + 1, nn - 1); return s[lo] + (vi - lo) * (s[hi] - s[lo]); };
  const stat = (vals, kind) => {
    const s = vals.filter((y) => !Number.isNaN(y));
    const m = s.reduce((a, b) => a + b, 0) / s.length;
    if (kind === 'sum') return s.reduce((a, b) => a + b, 0);
    if (kind === 'mean') return m;
    if (kind === 'sd') return Math.sqrt(s.reduce((a, b) => a + (b - m) ** 2, 0) / (s.length - 1));
    if (kind === 'min') return Math.min(...s);
    if (kind === 'max') return Math.max(...s);
    if (kind === 'n') return s.length;
    return NaN;
  };
  const byGroup = (keys, fn) => { const out = new Array(N); for (const rows of groupsOf(keys).values()) { const val = fn(rows.map((i) => x[i]), rows); rows.forEach((i, k) => { out[i] = Array.isArray(val) ? val[k] : val; }); } return out; };
  const closeAll = (label, got, want, tol = 1e-12) => { n++; const ok = got.length === want.length && got.every((y, i) => (Number.isNaN(y) && Number.isNaN(want[i])) || Math.abs(y - want[i]) <= tol * Math.max(1, Math.abs(want[i]))); console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}`); if (!ok) { failed.push(label); console.log('   got', got.slice(0, 8), 'want', want.slice(0, 8)); } };
  for (const [fn, kind] of [['Col Sum', 'sum'], ['Col Mean', 'mean'], ['Col Std Dev', 'sd'], ['Col Min', 'min'], ['Col Maximum', 'max'], ['Col Number', 'n']]) {
    closeAll(`${fn}(:x)`, ev(`${fn}(:x)`), new Array(N).fill(stat(x, kind)));
    closeAll(`${fn}(:x, :g)`, ev(`${fn}(:x, :g)`), byGroup(g, (vals) => stat(vals, kind)));
    closeAll(`${fn}(:x, :g, :h)`, ev(`${fn}(:x, :g, :h)`), byGroup(g.map((k, i) => `${k}|${h[i]}`), (vals) => stat(vals, kind)));
  }
  closeAll('Col N Missing(:x, :g)', ev('Col N Missing(:x, :g)'), byGroup(g, (vals) => vals.filter((y) => Number.isNaN(y)).length));
  closeAll('Col Median(:x) is the weibull 0.5 quantile', ev('Col Median(:x)'), new Array(N).fill(weibull(x, 0.5)));
  for (const p of [0, 0.001, 0.1, 0.25, 0.5, 0.9, 0.975, 1]) closeAll(`Col Quantile(:x, ${p}, :g) is numpy's weibull`, ev(`Col Quantile(:x, ${p}, :g)`), byGroup(g, (vals) => weibull(vals, p)));
  // mode: the most frequent value, the smallest of equals
  const modeOf = (vals) => { const m = new Map(); for (const y of vals) if (!Number.isNaN(y)) m.set(y, (m.get(y) || 0) + 1); let best = null, bc = 0; for (const [y, c] of m) if (c > bc || (c === bc && y < best)) { best = y; bc = c; } return best; };
  closeAll('Col Mode(:x, :g)', ev('Col Mode(:x, :g)'), byGroup(g, modeOf));
  check('Col Mode of text', F.evaluate(t, 'Col Mode(:g)')[0], 'a');
  // ranks
  const rankOf = (vals, tie) => {
    const idx = vals.map((y, i) => i).filter((i) => !Number.isNaN(vals[i])).sort((a, b) => vals[a] - vals[b] || a - b);
    const out = vals.map(() => NaN);
    for (let i = 0; i < idx.length;) { let j = i; while (j + 1 < idx.length && vals[idx[j + 1]] === vals[idx[i]]) j++; for (let k = i; k <= j; k++) out[idx[k]] = tie === 'average' ? (i + j + 2) / 2 : tie === 'minimum' ? i + 1 : tie === 'maximum' ? j + 1 : k + 1; i = j + 1; }
    return out;
  };
  closeAll('Col Rank(:x): ties in row order', ev('Col Rank(:x)'), rankOf(x, 'row'));
  closeAll('Col Rank(:x, <<Tie("average"))', ev('Col Rank(:x, <<Tie("average"))'), rankOf(x, 'average'));
  closeAll('Col Rank(:x, :g, <<Tie("minimum"))', ev('Col Rank(:x, :g, <<Tie("minimum"))'), byGroup(g, (vals) => rankOf(vals, 'minimum')));
  closeAll('Col Rank(:x, <<Tie("maximum"))', ev('Col Rank(:x, <<Tie("maximum"))'), rankOf(x, 'maximum'));
  closeAll('Rank(:x) is Col Rank', ev('Rank(:x)'), rankOf(x, 'row'));
  const cum = (vals) => { let s = 0; return vals.map((y) => (Number.isNaN(y) ? NaN : (s += y))); };
  closeAll('Col Cumulative Sum(:x): missing stays missing', ev('Col Cumulative Sum(:x)'), cum(x));
  closeAll('Cumulative Sum(:x, :g)', ev('Cumulative Sum(:x, :g)'), byGroup(g, cum));
  closeAll('Col Standardize(:x, :g)', ev('Col Standardize(:x, :g)'), byGroup(g, (vals) => { const m = stat(vals, 'mean'), s = stat(vals, 'sd'); return vals.map((y) => (y - m) / s); }), 1e-12);
  closeAll('Col Mean of an expression', ev('Col Mean(:x * 2 + 1)'), new Array(N).fill(2 * stat(x, 'mean') + 1));
  closeAll('Col Sum of an all-missing group is missing', Array.from(F.evaluate(t, 'Col Sum(If(:g == "b", ., :x), :g)')), [7, NaN, 7, NaN, 7, 10]);
}

/* ---- random numbers: the same with the same seed ----------------------------------------- */
{
  const a = F.evaluate(t, 'Random Normal()', null, { seed: 'c7' });
  const b = F.evaluate(t, 'Random Normal()', null, { seed: 'c7' });
  const c = F.evaluate(t, 'Random Normal()', null, { seed: 'c8' });
  check('the same seed, the same numbers', Array.from(a), Array.from(b));
  check('another seed, other numbers', Array.from(a).some((y, i) => y !== c[i]), true);
  const u = Array.from(F.evaluate(t, 'Random Uniform(5, 6)', null, { seed: 1 }));
  check('Random Uniform(5, 6) is in [5, 6)', u.every((y) => y >= 5 && y < 6), true);
  const k = Array.from(F.evaluate(t, 'Random Integer(1, 6)', null, { seed: 2 }));
  check('Random Integer(1, 6)', k.every((y) => Number.isInteger(y) && y >= 1 && y <= 6), true);
  check('Random Exp() > 0', Array.from(F.evaluate(t, 'Random Exp()', null, { seed: 3 })).every((y) => y > 0), true);
  const big = new SM.Table({ columns: [{ name: 'i', dataType: 'numeric', values: Array.from({ length: 20000 }, (_, i) => i) }] });
  const z = Array.from(F.evaluate(big, 'Random Normal(10, 2)', null, { seed: 'moments' }));
  const m = z.reduce((p, q) => p + q, 0) / z.length;
  const sd = Math.sqrt(z.reduce((p, q) => p + (q - m) ** 2, 0) / (z.length - 1));
  check('Random Normal(10, 2) has about that mean and sd', Math.abs(m - 10) < 0.06 && Math.abs(sd - 2) < 0.05, true);
}

/* ---- types of results ------------------------------------------------------------------------ */
check('numbers give a numeric column', F.evaluate(t, ':x * 2').dataType, 'numeric');
check('text gives a character column', F.evaluate(t, 'Uppercase(:name)').dataType, 'character');
check('If of numbers and text gives character', F.evaluate(t, 'If(:x > 3, "big", 0)').dataType, 'character');
check('a date function gives a date', F.evaluate(t, 'Date MDY(1, 2, 2020)').date, true);
check('a date plus days is a date, a date minus a date is not', [F.evaluate(t, ':when + In Days(1)').date, F.evaluate(t, ':when - Date MDY(1, 1, 2020)').date], [true, false]);

/* ---- formula columns --------------------------------------------------------------------- */
{
  const T = new SM.Table({ name: 'F', columns: [
    { name: 'a', dataType: 'numeric', values: [1, 2, 3, 4] },
    { name: 'b', dataType: 'numeric', values: [10, 20, 30, 40] },
    { name: 's', dataType: 'character', values: ['x', 'y', 'x', 'y'] },
  ] });
  let dataEvents = 0;
  T.on('data', () => { dataEvents++; });
  // c = d + 1 is made before d = a * b: the order of the columns is not the order of computing
  const c = T.addColumn({ name: 'c', dataType: 'numeric', values: [] });
  const d = T.addColumn({ name: 'd', dataType: 'numeric', values: [] });
  F.apply(T, d, ':a * :b');
  F.apply(T, c, ':d + 1');
  check('d = :a * :b', d.values, [10, 40, 90, 160]);
  check('c = :d + 1', c.values, [11, 41, 91, 161]);
  check('refs are column ids', c.formula.refs, [d.id]);
  dataEvents = 0;
  T.setCell(1, 'a', 5);
  check('an edit of :a recomputes d and then c', [d.values[1], c.values[1]], [100, 101]);
  check('one data event for the edit and one for the recalculation', dataEvents, 2);
  T.setValues('b', [1, 1, 1, 1]);
  check('setValues recomputes', c.values, [2, 6, 4, 5]);
  const e = T.addColumn({ name: 'e', dataType: 'numeric', values: [] });
  F.apply(T, e, 'If(:s == "x", "yes", "no")');
  check('a text formula makes a character column', [e.dataType, e.modelingType, e.values], ['character', 'nominal', ['yes', 'no', 'yes', 'no']]);
  T.setCell(0, 's', 'y');
  check('a text input recomputes', e.values[0], 'no');
  // cycles
  throwsAt('a formula that uses itself', () => F.apply(T, d, ':d + 1'), null, /own column/);
  throwsAt('a formula that would go round in a circle', () => F.apply(T, d, ':c * 2'), null, /circle: d uses c uses d/);
  check('the refused formula left d as it was', d.formula.expr, ':a * :b');
  // renames
  T.renameColumn('a', 'alpha one');
  check('a rename is written into the formulas', d.formula.expr, ':"alpha one" * :b');
  T.setCell(0, 'alpha one', 2);
  check('and the formula still works', [d.values[0], c.values[0]], [2, 3]);
  // row order
  const r = T.addColumn({ name: 'r', dataType: 'numeric', values: [] });
  F.apply(T, r, 'Row() * 10 + Lag(:b)');
  T.setValues('b', [4, 3, 2, 1]);
  const before = r.values.slice();
  T.sortBy([{ col: 'b' }]);
  check('sorting recomputes formulas of the row order', r.values, [NaN, 21, 32, 43]);
  check('and moves the others with their rows', d.values, [4, 6, 15, 8]);
  check('before the sort', before, [NaN, 24, 33, 42]);
  // new rows
  T.addRows(1);
  check('added rows get their formula values', [d.values.length, c.values[4], r.values[4]], [5, NaN, 50 + 4]);
  // JSON round trip
  const j = JSON.parse(JSON.stringify(T.toJSON()));
  const U = SM.Table.fromJSON(j);
  F.adopt(U);
  check('a table from JSON keeps its formulas', U.col('c').formula.expr, ':d + 1');
  check('and they are live', (() => { U.setCell(0, 'b', 100); return [U.col('d').values[0], U.col('c').values[0]]; })(), [U.col('alpha one').values[0] * 100, U.col('alpha one').values[0] * 100 + 1]);
  check('refs follow the new ids', U.col('c').formula.refs, [U.col('d').id]);
  // random columns repeat
  const z = T.addColumn({ name: 'z', dataType: 'numeric', values: [] });
  F.apply(T, z, 'Random Normal()');
  const z1 = z.values.slice();
  F.recalc(T);
  check('a random column is the same after a recalculation', z.values, z1);
  const Z = SM.Table.fromJSON(JSON.parse(JSON.stringify(T.toJSON())));
  F.adopt(Z);
  check('and after a JSON round trip', Z.col('z').values, z1);
  // deleting a column that a formula uses
  T.removeColumn('b');
  check('a formula whose column is deleted keeps its values, not its formula', [d.formula, d.values.length], [null, 5]);
  check('its dependants go on working', (() => { T.setCell(0, 'd', 7); return c.values[0]; })(), 8);
  // removing a formula
  F.apply(T, c, '');
  check('an empty formula removes it', c.formula, null);
  // date results get a date format
  const w = T.addColumn({ name: 'w', dataType: 'numeric', values: [] });
  F.apply(T, w, 'Date MDY(1, Row(), 2024)');
  check('a date formula gets a date format', w.format && w.format.kind, 'date');
  // an input that turns into text
  const k = T.addColumn({ name: 'k', dataType: 'numeric', values: [1, 2, 3, 4, 5] });
  const k2 = T.addColumn({ name: 'k2', dataType: 'numeric', values: [] });
  F.apply(T, k2, ':k * 2');
  T.setType('k', { dataType: 'character' });
  check('a formula whose input became text keeps its values', k2.values, [2, 4, 6, 8, 10]);
  const inf = F.info(T, k2);
  check('and reports the error', /needs a number/.test(inf.error || ''), true);
  // restoring a snapshot (Edit > Undo)
  if (typeof T.snapshot === 'function') {
    const snap = T.snapshot();
    F.apply(T, c, ':d * 100');
    T.restore(snap);
    check('undo puts the formula back as it was', c.formula, null);
    const cv = c.values[1];
    T.setCell(1, 'd', 3);
    check('and no formula is left behind by the undo', c.values[1], cv);
    T.setType('k', { dataType: 'numeric' });
    check('a formula whose input is numeric again works again', [k2.values[0], F.info(T, k2).error], [2, null]);
  }
}

/* ---- speed ---------------------------------------------------------------------------------- */
{
  const N = 100000;
  const r = SM.util.rng('speed');
  const x = new Array(N), y = new Array(N), g = new Array(N);
  for (let i = 0; i < N; i++) { x[i] = r.normal(); y[i] = r.normal(5, 2); g[i] = ['a', 'b', 'c', 'd'][i % 4]; }
  const T = new SM.Table({ columns: [{ name: 'x', dataType: 'numeric', values: x }, { name: 'y', dataType: 'numeric', values: y }, { name: 'g', dataType: 'character', values: g }] });
  const expr = 'If(:x > 0, Log(:x) * 2 + Sqrt(Abs(:y)), :y - Col Mean(:y, :g)) + Round(:x, 2)';
  let t0 = Date.now();
  const out = F.evaluate(T, expr);
  const ms1 = Date.now() - t0;
  check('100 000 rows, a formula with If, Log, Sqrt, Col Mean by group and Round', out.length, N);
  console.log(`      (${ms1} ms)`);
  check('evaluates in well under a second', ms1 < 600, true);
  t0 = Date.now();
  const c = T.addColumn({ name: 'f', dataType: 'numeric', values: [] });
  F.apply(T, c, 'Concat(:g, "-", Char(Round(:y, 1)))');
  T.setCell(5, 'y', 1.25);
  const ms2 = Date.now() - t0;
  check('a text formula column over 100 000 rows and one recalculation', c.values[5], 'b-1.3');
  console.log(`      (${ms2} ms)`);
  check('in well under a second', ms2 < 800, true);
}

console.log(`\n${n - failed.length} of ${n} checks passed`);
if (failed.length) console.log('failed:\n  ' + failed.join('\n  '));
process.exit(failed.length ? 1 : 0);
