/* Right and wrong, stars, points and days in a row for piano.html.

     node resources/tests/piano/test-game.js

   Exit status is 0 when every check passes. */
const G = require('../../js/piano-game.js');
const { check, done } = require('./check.js');

const key = (midi, more) => Object.assign({ midi, source: 'screen', t: 0, again: false }, more || {});

/* ── The right key ─────────────────────────────────────────────────────── */

check('the same key is right, another is not', [G.matches(60, key(60)), G.matches(60, key(62)), G.matches(60, key(72))], [true, false, false]);
check('another octave counts only when asked, and only by microphone',
  [G.matches(60, key(72, { source: 'mic' }), { anyOctave: true }), G.matches(60, key(72), { anyOctave: true }), G.matches(60, key(72, { source: 'mic' }), {}), G.matches(60, key(67, { source: 'mic' }), { anyOctave: true })],
  [true, false, false, false]);

/* ── At the player's own pace ──────────────────────────────────────────── */

{
  const w = G.createWait([60, 62, 64]);
  check('wait: the right key moves on', (r => [r.kind, r.index, r.done])(w.hear(key(60))), ['right', 0, false]);
  check('wait: a wrong key stays, with no hint yet', (r => [r.kind, r.index, r.showHint])(w.hear(key(65))), ['wrong', 1, false]);
  check('wait: the second wrong key shows the hint', w.hear(key(67)).showHint, true);
  w.hear(key(69));
  check('wait: three wrong keys on one note cost one mark', w.mistakes(), 1);
  w.hear(key(62));
  check('wait: the last right key ends it', (r => [r.kind, r.done])(w.hear(key(64))), ['right', true]);
  check('wait: two of three right the first time', [w.accuracy().toFixed(3), w.done()], ['0.667', true]);
  check('wait: after the end nothing counts', w.hear(key(60)).kind, 'ignore');
}
{
  const w = G.createWait([60, 62, 62, 64]);
  w.hear(key(60, { source: 'mic', t: 1000 }));
  check('microphone: the note just played, heard again as it rings, is no mistake', w.hear(key(60, { source: 'mic', t: 1400 })).kind, 'ignore');
  check('microphone: a second strike of it much later is', w.hear(key(60, { source: 'mic', t: 3000 })).kind, 'wrong');
  check('microphone: but not when the listener calls it the same note swelling', w.hear(key(60, { source: 'mic', t: 5000, again: true })).kind, 'ignore');
  check('microphone: one wrong key heard twice running costs once', [w.hear(key(67, { source: 'mic', t: 6000 })).kind, w.hear(key(67, { source: 'mic', t: 6300 })).kind], ['wrong', 'ignore']);
  w.hear(key(62, { source: 'mic', t: 7000 }));
  check('microphone: a repeated note in the melody takes a second strike', w.hear(key(62, { source: 'mic', t: 7400, again: true })).kind, 'right');
  check('on the screen a repeated wrong key is wrong each time', (v => [v.hear(key(61)).kind, v.hear(key(61)).kind])(G.createWait([60])), ['wrong', 'wrong']);
}

/* ── In time ───────────────────────────────────────────────────────────── */

{
  const notes = [{ midi: 60, start: 0 }, { midi: 62, start: 1 }, { midi: 62, start: 2 }, { midi: 64, start: 3 }];
  const T = G.createTempo(notes, 120);
  check('tempo: at 120 a beat is half a second', [T.times, T.beat], [[0, 0.5, 1, 1.5], 0.5]);
  check('tempo: the window is never under a quarter second', T.window, 0.26);
  check('tempo: on the beat is a hit', (r => [r.kind, r.index])(T.hear(key(60), 0.02)), ['hit', 0]);
  check('tempo: the wrong key is not', T.hear(key(65), 0.5).kind, 'extra');
  check('tempo: of two notes alike, the nearer one is taken', T.hear(key(62), 0.9).index, 2);
  check('tempo: and the other is still there for its own moment', T.hear(key(62), 0.6).index, 1);
  check('tempo: too late is no hit', T.hear(key(64), 1.9).kind, 'extra');
  check('tempo: a note gone by is swept as missed, once', [T.sweep(1.8), T.sweep(2)], [[3], []]);
  const res = T.result();
  check('tempo: three of four', [res.hits, res.total, res.accuracy], [3, 4, 0.75]);
  check('tempo: the player ran a little late on average', res.late > 0 && res.late < 0.1, true);
  check('tempo: a slow tempo has a wider window, up to half a second', [G.createTempo(notes, 60).window, G.createTempo(notes, 40).window], [0.45, 0.5]);
}
check('stars: 90 % three, 70 % two, anything one', [1, 0.9, 0.89, 0.7, 0.69, 0].map(G.stars), [3, 3, 2, 2, 1, 1]);

/* ── Days ──────────────────────────────────────────────────────────────── */

check('a day is the local date', G.dayKey(new Date(2026, 10, 19, 23, 59)), '2026-11-19');
check('days are added over a month and a year', [G.addDays('2026-11-30', 1), G.addDays('2026-12-31', 1), G.addDays('2026-03-01', -1)], ['2026-12-01', '2027-01-01', '2026-02-28']);

/* ── What is remembered ────────────────────────────────────────────────── */

check('nothing stored is a clean start', G.validate(null), G.blank());
check('rubbish stored is a clean start', G.validate({ xp: -5, days: 'x', lessons: [1], streak: { count: 9 }, settings: { goal: 7, names: 'x' }, own: [{ text: 5 }] }), G.blank());
{
  const s = G.validate({ xp: 120, lessons: { 'u1-cde': { stars: 9, times: 2 }, '<script>': { stars: 1 } }, settings: { names: 'b', goal: 60, sound: false }, streak: { count: 3, last: '2026-11-18', best: 2 }, tune: -80,
    own: [{ id: 'own-a1', title: 'Min låt', text: 'C D E', time: 3, bpm: 500 }] });
  check('what is stored is kept, within bounds', [s.xp, s.lessons, s.settings.names, s.settings.goal, s.settings.sound, s.streak, s.tune],
    [120, { 'u1-cde': { stars: 3, times: 2 } }, 'b', 60, false, { count: 3, last: '2026-11-18', best: 3 }, -50]);
  check('an own song is kept, its tempo within reason', s.own, [{ id: 'own-a1', title: 'Min låt', text: 'C D E', time: 3, pickup: 0, bpm: 160, own: true }]);
}

/* ── Lessons, points, days in a row ────────────────────────────────────── */

{
  const s = G.blank();
  const a = G.finishLesson(s, 'u1-cde', { accuracy: 1, notes: 12, real: false }, '2026-11-19');
  check('a first lesson, all right: three stars, 30 points', [a.stars, a.xp, a.firstTime, s.xp, s.notes], [3, 30, true, 30, 12]);
  check('the first day is one day in a row', [a.streak, s.streak], [{ before: 0, after: 1, grew: true }, { count: 1, last: '2026-11-19', best: 1 }]);
  check('badges: the first lesson and three stars', a.badges.map(b => b.id), ['first', 'three']);
  const b = G.finishLesson(s, 'u1-cde', { accuracy: 0.5, notes: 6, real: true }, '2026-11-19');
  check('the same lesson again, worse: 15 points, the three stars stay', [b.stars, b.best, b.xp, s.lessons['u1-cde']], [1, 3, 15, { stars: 3, times: 2 }]);
  check('a second lesson the same day does not add a day', b.streak, { before: 1, after: 1, grew: false });
  check('the goal of 40 is reached by the second lesson', [a.goal.reached, b.goal.reached, b.goal.after], [false, true, 45]);
  check('badges are given once: now the real piano and the goal', b.badges.map(x => x.id), ['real', 'goal']);
  const c = G.finishLesson(s, 'u1-fg', { accuracy: 0.8, notes: 10 }, '2026-11-20');
  check('the next day makes two in a row', [c.streak.after, c.stars, c.xp], [2, 2, 25]);
  const d = G.finishLesson(s, 'u1-hand', { accuracy: 1, notes: 10 }, '2026-11-21');
  check('three days: the badge', [d.streak.after, d.badges.map(x => x.id)], [3, ['streak3']]);
  check('the count holds through the next day, and is over the day after', [G.streakNow(s, '2026-11-22'), G.streakNow(s, '2026-11-23')], [3, 0]);
  const e = G.finishLesson(s, 'u1-noak1', { accuracy: 1, notes: 10 }, '2026-11-25');
  check('after a missed day it starts again at one, the best kept', [e.streak, s.streak.best], [{ before: 0, after: 1, grew: true }, 3]);
  check('the last seven days', G.week(s, '2026-11-25').map(x => (x.met ? 2 : x.xp ? 1 : 0)), [2, 1, 1, 0, 0, 0, 1]);
  check('stars in all', G.totalStars(s), 11);
}
{
  const s = G.blank();
  const xmas = n => () => n;
  const a = G.finishLesson(s, 'u2-bj5', { accuracy: 0.95, notes: 49 }, '2026-12-01', { concert: true, xmas: xmas(1) });
  check('a concert: its own badge, and the Christmas one', a.badges.map(b => b.id).filter(b => ['concert', 'xmas1', 'perfect'].includes(b)), ['concert', 'xmas1']);
  const b = G.finishLesson(s, 'u2-bj5', { accuracy: 1, notes: 51 }, '2026-12-01', { concert: true, xmas: xmas(1) });
  check('a concert without a miss', [b.badges.some(x => x.id === 'perfect'), b.badges.some(x => x.id === 'concert')], [true, false]);
  const c = G.finishSong(s, 'stilla', { accuracy: 0.75, notes: 30 }, '2026-12-01');
  check('a song from the list: two stars, 8 points', [c.stars, c.xp, s.songs.stilla], [2, 8, { stars: 2, best: 0.75, times: 1 }]);
}
check('levels: 60 points more for each', [0, 59, 60, 179, 180, 360].map(x => G.level(x).level), [1, 1, 2, 2, 3, 4]);
check('level: how far into it', G.level(100), { level: 2, into: 40, need: 120 });
check('nineteen badges, each with a name, a way to it and a picture', [G.BADGES.length, G.BADGES.every(b => b.title && b.how && b.icon && typeof b.test === 'function'), new Set(G.BADGES.map(b => b.id)).size], [19, true, 19]);

done();
