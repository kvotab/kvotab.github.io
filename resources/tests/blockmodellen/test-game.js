/* Stars, days in a row, badges and what is kept, in Node:

     node resources/tests/blockmodellen/test-game.js
*/
'use strict';

const G = require('../../js/blockmodellen-game.js');
const P = require('../../js/blockmodellen-problems.js');
const UNITS = P.UNITS.map(u => ({ id: u.id, lessons: u.lessons.map(l => l.id) }));

let checks = 0;
const failures = [];
function check(label, got, want) {
  checks++;
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok ? '' : `: ${JSON.stringify(got)} (expected ${JSON.stringify(want)})`}`);
  if (!ok) failures.push(label);
}

check('stars: 90 % and up three, 70 % two, below one', [1, 0.9, 0.89, 0.7, 0.69, 0].map(G.stars), [3, 3, 2, 2, 1, 1]);
check('days are the pupil\'s own', G.dayKey(new Date(2026, 10, 25, 23, 59)), '2026-11-25');
check('a day later, across a month', G.addDays('2026-11-30', 1), '2026-12-01');

/* What was stored can be anything. */
check('nothing stored: a blank store', G.validate(null), G.blank());
check('rubbish stored: a blank store', G.validate('x'), G.blank());
const bad = G.validate({
  solved: -4, days: { '2026-11-25': 3, 'not a day': 9, '__proto__': 1 }, streak: { count: 5, last: 'yesterday', best: 'a lot' },
  lessons: { 'delhel-1': { stars: 7, times: 2 }, '<img>': { stars: 3 } }, types: { jmf: { tries: 3, right: 9 }, nope: { tries: 1, right: 1 } },
  badges: { first: '2026-11-25', fake: 12 }, flags: { steps: 'yes', built: true }, run: { now: 3, best: 1 },
  settings: { name: '  lisa<script> ', pron: 'den', speech: 'no', level: 3 },
});
check('a negative count is none', bad.solved, 0);
check('only days are kept', Object.keys(bad.days), ['2026-11-25']);
check('days in a row without a last day are none', [bad.streak.count, bad.streak.best], [0, 0]);
check('stars at most three, lessons only by their names', bad.lessons, { 'delhel-1': { stars: 3, times: 2 } });
check('right never more than tried, only known kinds', bad.types, { jmf: { tries: 3, right: 3 } });
check('only badges with a day', bad.badges, { first: '2026-11-25' });
check('only flags that are true', bad.flags, { built: true });
check('the best run is at least the run now', bad.run, { now: 3, best: 3 });
check('a name is letters only, with a capital', bad.settings.name, 'Lisascript');
check('settings out of range are the defaults', [bad.settings.pron, bad.settings.speech, bad.settings.level], ['hen', true, 1]);
check('names: spaces, hyphens and å ä ö kept, 20 letters at most', [G.cleanName('anna-karin'), G.cleanName('Åsa'), G.cleanName('x'.repeat(30)).length, G.cleanName(42)], ['Anna-karin', 'Åsa', 20, '']);

/* Days in a row. */
const s = G.blank();
G.solved(s, '2026-11-20', { type: 'jmf', counts: true, first: true }, { units: UNITS });
check('the first day: one day in a row', [G.streakNow(s, '2026-11-20'), s.streak.best], [1, 1]);
G.solved(s, '2026-11-20', { type: 'jmf', counts: true, first: false }, { units: UNITS });
check('the same day again: still one', s.streak.count, 1);
G.solved(s, '2026-11-21', { type: 'brak', counts: true, first: true }, { units: UNITS });
G.solved(s, '2026-11-22', { type: 'brak', counts: true, first: true }, { units: UNITS });
check('three days running: three in a row', [s.streak.count, G.streakNow(s, '2026-11-23')], [3, 3]);
check('a day missed: the count is over, as of the day after', G.streakNow(s, '2026-11-24'), 0);
G.solved(s, '2026-11-25', { type: 'jmf', counts: true, first: true }, { units: UNITS });
check('and starts again at one, the best kept', [s.streak.count, s.streak.best], [1, 3]);
check('problems solved, by day', [s.solved, s.days['2026-11-20'], s.days['2026-11-25']], [5, 2, 1]);
check('kinds: tried and right the first time', s.types, { jmf: { tries: 3, right: 2 }, brak: { tries: 2, right: 2 } });
check('a problem drawn as help, or in a lesson that draws, is no try', (() => { const t = G.blank(); G.solved(t, '2026-11-25', { type: 'jmf', counts: false }); return t.types; })(), {});
check('the run of firsts: broken by a miss', [s.run.now, s.run.best], [3, 3]);
check('a kind the pupil misses often is a kind to practise', (() => { const t = G.blank(); for (const f of [false, false, true]) G.solved(t, '2026-11-25', { type: 'rest', counts: true, first: f }); for (let i = 0; i < 4; i++) G.solved(t, '2026-11-25', { type: 'jmf', counts: true, first: true }); return G.weakTypes(t); })(), ['rest']);

/* Lessons and badges. */
const b = G.blank();
let res = G.finishLesson(b, 'start-1', 0.8, '2026-11-25', {}, { units: UNITS });
check('a lesson: its stars and the first time', [res.stars, res.best, res.firstTime], [2, 2, true]);
check('the first lesson is a badge', res.badges.map(x => x.id), ['first']);
res = G.finishLesson(b, 'start-1', 0.5, '2026-11-25', {}, { units: UNITS });
check('a worse go keeps the best stars', [res.stars, res.best, b.lessons['start-1']], [1, 2, { stars: 2, times: 2 }]);
res = G.finishLesson(b, 'start-2', 1, '2026-11-25', { steps: true }, { units: UNITS });
check('the eight steps without a slip, and three stars', res.badges.map(x => x.id).sort(), ['steps', 'three']);
check('a badge once only', G.finishLesson(b, 'start-2', 1, '2026-11-25', { steps: true }, { units: UNITS }).badges, []);
for (const u of UNITS) G.finishLesson(b, u.lessons[0], 1, '2026-11-25', {}, { units: UNITS });
check('a lesson in every chapter', !!b.badges.units, true);
check('not yet every fraction lesson with three stars', !!b.badges.brak, false);
for (const u of UNITS.filter(x => x.id === 'brak' || x.id === 'rest')) for (const id of u.lessons) G.finishLesson(b, id, 1, '2026-11-25', {}, { units: UNITS });
check('every fraction lesson with three stars', !!b.badges.brak, true);
const c = G.blank();
for (let i = 0; i < 10; i++) G.solved(c, '2026-11-25', { type: 'lika', counts: true, first: true, built: i === 3 }, { units: UNITS });
check('ten solved, five in a row, a model drawn alone', ['solved10', 'run5', 'built'].map(id => !!c.badges[id]), [true, true, true]);
check('every badge has words and a picture', G.BADGES.every(x => x.title && x.how && x.icon), true);
check('badge ids are unique', new Set(G.BADGES.map(x => x.id)).size, G.BADGES.length);

/* What is kept comes back the same. */
check('stored and read back: the same store', G.validate(JSON.parse(JSON.stringify(b))), b);

console.log(`\n${checks - failures.length} of ${checks} checks passed.`);
process.exit(failures.length ? 1 : 0);
