#!/usr/bin/env node
/* gitarr.html's ear, in Node: resources/js/gitarr-pitch.js against plucked
   strings made in the test (synth.js), with no page and no browser.

       node resources/tests/gitarr/test-pitch.js

   Exit status 0 when every check passes. */
'use strict';

const path = require('path');
const P = require(path.join(__dirname, '../../js/gitarr-pitch.js'));
const S = require(path.join(__dirname, 'synth.js'));

let checks = 0;
const failures = [];
function check(label, ok, detail) {
  checks++;
  if (!ok) failures.push(label);
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok || detail === undefined ? '' : ': ' + detail}`);
}

const NAME = i => `${P.STRINGS[i].name}${P.STRINGS[i].octave}`;
const at = (i, cents) => P.STRINGS[i].freq * Math.pow(2, cents / 1200);

/* Every frame of a signal from `from` seconds on, 30 a second, as the page
   reads them: { hits, none, wrong (string → count), errs (cents minus the
   truth), ms per frame }. */
function frames(x, sr, want, cents, opts) {
  const o = opts || {};
  const det = P.createDetector(sr);
  const gate = P.createGate();
  const hop = Math.round(sr / 30);
  const out = { n: 0, none: 0, wrong: {}, errs: [] };
  const t0 = process.hrtime.bigint();
  for (let end = Math.max(det.need, Math.round((o.from || 0.2) * sr)); end <= x.length; end += hop) {
    out.n++;
    const seg = x.subarray(end - det.need, end);
    const { reading, hit } = P.hear(det, seg, { string: o.string });
    const heard = gate.pass(reading) && hit ? hit : null;
    if (!heard) { out.none++; continue; }
    if (heard.i !== want) { const k = NAME(heard.i); out.wrong[k] = (out.wrong[k] || 0) + 1; continue; }
    out.errs.push(heard.cents - cents);
  }
  out.ms = Number(process.hrtime.bigint() - t0) / 1e6 / out.n;
  out.max = out.errs.length ? Math.max(...out.errs.map(Math.abs)) : NaN;
  return out;
}

function summary(r) {
  return `frames ${r.n}, none ${r.none}, wrong ${JSON.stringify(r.wrong)}, max error ${r.max.toFixed(3)} cents`;
}

/* ── The strings ─────────────────────────────────────────────────────── */

{
  const want = [[6, 'E', 82.4069], [5, 'A', 110], [4, 'D', 146.8324], [3, 'G', 195.9977], [2, 'B', 246.9417], [1, 'E', 329.6276]];
  check('six strings, low E first, A4 = 440 equal temperament',
    P.STRINGS.length === 6 && want.every(([n, name, f], i) => P.STRINGS[i].n === n && P.STRINGS[i].name === name && Math.abs(P.STRINGS[i].freq - f) < 1e-3),
    JSON.stringify(P.STRINGS));
  check('nearestString: every string at itself', P.STRINGS.every((s, i) => P.nearestString(s.freq).i === i));
}

/* ── Accuracy and the right string, every frame ──────────────────────── */

for (const sr of [48000, 44100]) {
  let worst = 0, worstName = '', wrongs = 0, nones = 0, ms = 0, runs = 0;
  for (let i = 0; i < 6; i++) {
    for (const c of [-45, -12, -3, 0, 4, 20, 45]) {
      const r = frames(S.pluck({ sr, f0: at(i, c), seed: 11 + i }), sr, i, c);
      if (r.max > worst) { worst = r.max; worstName = `${NAME(i)} ${c}`; }
      wrongs += Object.keys(r.wrong).length;
      nones += r.none;
      ms += r.ms; runs++;
    }
  }
  check(`${sr} Hz clean plucks, 6 strings × 7 tunings: always the right string`, wrongs === 0 && nones === 0, `${wrongs} wrong, ${nones} missed`);
  check(`${sr} Hz clean plucks: within 0.1 cent in every frame`, worst <= 0.1, `${worst.toFixed(3)} at ${worstName}`);
  check(`${sr} Hz: a frame takes under 3 ms`, ms / runs < 3, `${(ms / runs).toFixed(2)} ms`);
}

/* A stiff string heard through a phone: partials stretched (B), the low end
   cut by the microphone, a little hiss. YIN alone read these 5-6 cents sharp
   while the upper partials rang; the second pass brings it under a cent. */
for (const [B, limit] of [[5e-5, 0.6], [1.5e-4, 1.3]]) {
  let worst = 0, worstName = '', wrongs = 0;
  for (let i = 0; i < 6; i++) {
    for (const c of [-30, 0, 9]) {
      const r = frames(S.pluck({ sr: 48000, f0: at(i, c), B, hp: 150, noise: 0.002, seed: 5 + i }), 48000, i, c);
      if (r.max > worst) { worst = r.max; worstName = `${NAME(i)} ${c}`; }
      wrongs += Object.keys(r.wrong).length + r.none;
    }
  }
  check(`stiff strings (B = ${B}) through a phone microphone: right string every frame`, wrongs === 0);
  check(`stiff strings (B = ${B}): within ${limit} cent of the fundamental`, worst <= limit, `${worst.toFixed(3)} at ${worstName}`);
}

for (const sr of [16000, 22050, 32000, 96000]) {
  let worst = 0, wrongs = 0;
  for (const i of [0, 2, 5]) {
    const r = frames(S.pluck({ sr, f0: at(i, -17) }), sr, i, -17);
    worst = Math.max(worst, r.max);
    wrongs += Object.keys(r.wrong).length + r.none;
  }
  check(`${sr} Hz: right string, within 0.3 cent`, wrongs === 0 && worst <= 0.3, `${wrongs} wrong/missed, ${worst.toFixed(3)} cents`);
}

/* ── The octave trap ─────────────────────────────────────────────────── */

const trap = [
  ['low E, fundamental 34 dB down, odd partials weak', { f0: at(0, 0), weights: [0.02, 1, 0.08, 0.5, 0.05, 0.3, 0.03, 0.2] }, 0],
  ['low E with no odd partials at all (E3 to YIN)', { f0: at(0, 0), weights: [0, 1, 0, 0.5, 0, 0.3, 0, 0.2] }, 0],
  ['low E, third partial loudest', { f0: at(0, 0), weights: [0.05, 0.3, 1, 0.2, 0.1, 0.3] }, 0],
  ['low E 60 cents flat, no odd partials', { f0: at(0, -60), weights: [0, 1, 0, 0.5, 0, 0.3] }, 0, -60],
  ['low E through a 200 Hz high-pass', { f0: at(0, 0), hp: 200 }, 0],
  ['A with no fundamental', { f0: at(1, 0), weights: [0, 1, 0.6, 0.5, 0.3, 0.3] }, 1],
  ['A through a 200 Hz high-pass', { f0: at(1, 0), hp: 200 }, 1],
  ['D through a 200 Hz high-pass', { f0: at(2, 0), hp: 200 }, 2],
  ['high E as a pure tone (3 periods make an A2, 4 an E2)', { f0: at(5, 0), weights: [1] }, 5],
  ['high E 45 cents flat', { f0: at(5, -45) }, 5, -45],
  ['B as a pure tone (3 periods make an E2)', { f0: at(4, 0), weights: [1] }, 4],
  ['low E 120 cents flat', { f0: at(0, -120) }, 0, -120],
  ['low E 180 cents sharp', { f0: at(0, 180) }, 0, 180],
  ['G 200 cents flat stays G (F3, not a sharp low E)', { f0: at(3, -200) }, 3, -200],
  ['D 200 cents flat stays D', { f0: at(2, -200) }, 2, -200],
];
for (const [label, o, want, c] of trap) {
  const r = frames(S.pluck(Object.assign({ sr: 48000 }, o)), 48000, want, c || 0);
  check(`${label}: ${NAME(want)} every frame`, r.none === 0 && !Object.keys(r.wrong).length && r.max < 0.5, summary(r));
}

/* ── Noise, silence, quiet ───────────────────────────────────────────── */

{
  const r = frames(S.noise(48000, 2, 0.05), 48000, -1, 0);
  check('white noise: nothing heard', r.none === r.n, summary(r));
  const s = frames(new Float32Array(96000), 48000, -1, 0);
  check('silence: nothing heard', s.none === s.n);
  const q = frames(S.pluck({ sr: 48000, f0: at(1, 0), amp: 0.0012 }), 48000, 1, 0);
  check('a pluck under the floor (-56 dBFS): nothing heard', q.none === q.n, summary(q));
  const n = frames(S.pluck({ sr: 48000, f0: at(1, 0), noise: 0.03 }), 48000, 1, 0);
  check('A at 10 dB over the noise: right string every frame, within 3 cents', n.none === 0 && !Object.keys(n.wrong).length && n.max < 3, summary(n));
  const n2 = frames(S.pluck({ sr: 48000, f0: at(0, 0), noise: 0.03, hp: 150 }), 48000, 0, 0);
  check('low E at 10 dB over the noise through a phone: right string, within 3 cents', n2.none === 0 && !Object.keys(n2.wrong).length && n2.max < 3, summary(n2));
}

{
  // The room gets louder: a pluck only just over the old floor no longer counts.
  const gate = P.createGate();
  const det = P.createDetector(48000);
  const loud = S.noise(48000, 2, 0.02, 4);
  // the level the detector sees, after its low-pass: well under the 0.02 put in
  const level = det.analyse(loud.subarray(0, det.need)).rms;
  for (let end = det.need; end <= loud.length; end += 1600) gate.pass(det.analyse(loud.subarray(end - det.need, end)));
  check('the gate follows a loud room up', gate.room() > 0.75 * level, `${gate.room()} for a room at ${level}`);
  const pl = S.pluck({ sr: 48000, f0: at(1, 0), amp: 0.01, dur: 1 });
  const rd = det.analyse(pl.subarray(30000 - det.need, 30000));
  check('…and then a faint pluck is not over it', !gate.pass(rd), `rms ${rd.rms}`);
  const st = S.pluck({ sr: 48000, f0: at(1, 0), amp: 0.3, dur: 1 });
  check('…while a real one is', gate.pass(det.analyse(st.subarray(30000 - det.need, 30000))));
  for (let k = 0; k < 40; k++) gate.pass(det.analyse(S.noise(48000, det.need / 48000 + 0.001, 0.0002, k + 1)));
  check('…and it comes down again when the room is quiet', gate.room() < 0.001, gate.room());
  // A ringing string never lifts the room, even where no string is chosen.
  const g2 = P.createGate();
  const ring = S.pluck({ sr: 48000, f0: at(3, 0), dur: 3 });
  for (let end = det.need; end <= ring.length; end += 1600) g2.pass(det.analyse(ring.subarray(end - det.need, end)));
  check('a ringing string does not raise the room', g2.room() < 0.001, g2.room());
}

/* ── A picked string ─────────────────────────────────────────────────── */

{
  const r = frames(S.pluck({ sr: 48000, f0: at(1, -400) }), 48000, 1, -400, { string: 1 });
  check('A 400 cents flat, A picked: read as A, -400', r.none === 0 && !Object.keys(r.wrong).length && r.max < 0.5, summary(r));
  const a = frames(S.pluck({ sr: 48000, f0: at(1, -400) }), 48000, 0, 100);
  check('…while the automatic choice calls it a sharp low E', a.none === 0 && !Object.keys(a.wrong).length, summary(a));
  const o = frames(S.pluck({ sr: 48000, f0: at(0, 30), weights: [0, 1, 0, 0.5, 0, 0.3] }), 48000, 0, 30, { string: 0 });
  check('low E picked, no odd partials: still the low E, not its octave', r.none === 0 && o.max < 0.5, summary(o));
  const far = P.interpret({ freq: 1000, d: 0.01, cands: [{ k: 1, freq: 1000, d: 0.01 }] }, { string: 0 });
  check('picked low E, 1000 Hz heard: more than an octave out, nothing', far === null, JSON.stringify(far));
  const auto = P.interpret({ freq: 600, d: 0.01, cands: [{ k: 1, freq: 600, d: 0.01 }] }, {});
  check('automatic, 600 Hz heard: out of every string\'s range, nothing', auto === null, JSON.stringify(auto));
}

/* ── The tracker ─────────────────────────────────────────────────────── */

function feedTracker(tr, list) {
  let snap = null;
  for (const [t, hit] of list) snap = tr.update(t, hit);
  return snap;
}
const H = (i, cents) => ({ i, cents, freq: at(i, cents) });

{
  const tr = P.createTracker();
  let s = tr.update(0, H(1, -20));
  check('tracker: the first string heard is shown at once', s.string === 1 && s.live && s.shown, JSON.stringify(s));
  s = feedTracker(tr, [[30, H(1, -21)], [60, H(1, -19)], [90, H(4, 3)], [120, H(1, -20)]]);
  check('tracker: one stray reading of another string does not switch', s.string === 1, JSON.stringify(s));
  s = feedTracker(tr, [[150, H(4, 3)], [180, H(4, 3)], [210, H(4, 2)]]);
  check('tracker: a new string under 120 ms does not switch yet', s.string === 1);
  s = feedTracker(tr, [[240, H(4, 3)], [270, H(4, 2)], [300, H(4, 3)]]);
  check('tracker: a new string held 120 ms over three readings does', s.string === 4, JSON.stringify(s));
  s = feedTracker(tr, [[900, H(2, 10)]]);
  check('tracker: after a quiet spell a new string switches at once', s.string === 2);
  s = tr.update(1000 + 1500, null);
  check('tracker: a silent string stays shown, dimmed, for a while', s.shown && !s.live, JSON.stringify(s));
  s = tr.update(1000 + 1700, null);
  check('tracker: …and then goes', !s.shown && s.string === 2);
}

{
  const tr = P.createTracker();
  let s = feedTracker(tr, [[0, H(3, 40)], [30, H(3, 41)], [60, H(3, -200)], [90, H(3, 39)], [120, H(3, 40)]]);
  check('tracker: the median throws out a wild reading', Math.abs(s.cents - 40) < 1.5, s.cents);
  check('tracker: the shown frequency goes with the median', Math.abs(P.centsBetween(s.freq, P.STRINGS[3].freq) - s.cents) < 1e-6);
}

{
  const tr = P.createTracker();
  let s = null, t = 0, first = null, count = 0;
  for (; t <= 2000; t += 30) {
    s = tr.update(t, H(0, -2 + (t % 60 ? 1 : 0)));
    if (s.justTuned !== null) { count++; if (first === null) first = t; }
  }
  check('tracker: in tune once within 5 cents for 300 ms', first !== null && first >= 300 && first <= 360, first);
  check('tracker: "just tuned" fires once, not every frame', count === 1, count);
  check('tracker: the string is marked tuned', s.tuned[0] && s.inTune);
  for (let k = 0; k < 10; k++) s = tr.update(t += 30, H(0, -9));
  check('tracker: 9 cents out leaves the mark (under 12)', s.tuned[0] && !s.inTune);
  for (let k = 0; k < 20; k++) s = tr.update(t += 30, H(0, -30));
  check('tracker: 30 cents out for 400 ms takes the mark away', !s.tuned[0]);
  tr.reset();
  s = tr.update(t += 30, null);
  check('tracker: reset forgets the string, not the marks', s.string === null && Array.isArray(s.tuned));
  tr.clearTuned();
  check('tracker: clearTuned clears the marks', tr.update(t += 30, null).tuned.every(v => !v));
}

/* The low E still ringing when the A is plucked over it. */
{
  const sr = 48000;
  const x = S.mix(sr, 2.6, [
    { x: S.pluck({ sr, f0: at(0, -25), dur: 2.6, amp: 0.25 }), at: 0 },
    { x: S.pluck({ sr, f0: at(1, 15), dur: 1.4, amp: 0.4, seed: 3 }), at: 1.2 },
  ]);
  const det = P.createDetector(sr);
  const tr = P.createTracker();
  const gate = P.createGate();
  let switchedAt = null, beforeOK = true;
  for (let end = det.need; end <= x.length; end += Math.round(sr / 30)) {
    const t = end / sr * 1000;
    const { reading, hit } = P.hear(det, x.subarray(end - det.need, end), {});
    const s = tr.update(t, gate.pass(reading) && hit ? hit : null);
    if (t > 300 && t < 1200 && (s.string !== 0 || Math.abs(s.cents + 25) > 1)) beforeOK = false;
    if (switchedAt === null && s.string === 1) switchedAt = t;
  }
  check('sequence: the low E is shown, 25 cents flat, until the A is plucked', beforeOK);
  check('sequence: the A over the ringing E takes over within 350 ms', switchedAt !== null && switchedAt - 1200 < 350, switchedAt);
}

/* ── Which way to turn ───────────────────────────────────────────────── */

{
  // Seen from the front, headstock up. Posts: the string leaves on the
  // inside, so a left post tightens anticlockwise, a right one clockwise.
  // Keys: one worm gear for both sides, every key tightens anticlockwise
  // seen from its end - the front of a left key rolls up, of a right key down.
  const rows = [];
  let ok = true;
  for (const lefty of [false, true]) {
    for (const reverse of [false, true]) {
      for (let i = 0; i < 6; i++) {
        for (const cents of [-20, 20]) {
          const w = P.turn(i, cents, { lefty, reverse });
          const left = (i < 3) !== lefty;
          const tighten = cents < 0;
          const wantPost = left === tighten ? 'ccw' : 'cw';
          let wantFront = left === tighten ? 'up' : 'down';
          if (reverse) wantFront = wantFront === 'up' ? 'down' : 'up';
          const good = w.side === (left ? 'left' : 'right') && w.tighten === tighten && w.post === wantPost && w.keyFront === wantFront;
          if (!good) { ok = false; rows.push(JSON.stringify({ i, cents, lefty, reverse, w })); }
        }
      }
    }
  }
  check('turn: sides, posts and keys for all 48 cases', ok, rows.join(' '));
  const lowE = P.turn(0, -10, {});
  check('turn: a flat low E (left) → roll the key\'s front up, post anticlockwise', lowE.side === 'left' && lowE.keyFront === 'up' && lowE.post === 'ccw', JSON.stringify(lowE));
  const highE = P.turn(5, -10, {});
  check('turn: a flat high E (right) → roll the key\'s front down, post clockwise', highE.side === 'right' && highE.keyFront === 'down' && highE.post === 'cw', JSON.stringify(highE));
  const lefty = P.turn(0, -10, { lefty: true });
  check('turn: a left-handed low E sits on the right', lefty.side === 'right' && lefty.keyFront === 'down' && lefty.post === 'cw', JSON.stringify(lefty));
}

console.log(`\n${checks - failures.length} of ${checks} checks passed`);
if (failures.length) {
  console.log('FAILED:\n  ' + failures.join('\n  '));
  process.exit(1);
}
