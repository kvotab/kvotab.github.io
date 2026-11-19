/* Piano notes made in the test, for piano.html's tests.

   note() is a struck string: the partials of gitarr's pluck (stiff, the
   upper ones dying away faster, the thump of the hammer at the start), cut
   short by the damper when the key is let go. melody() puts notes after one
   another as a hand plays them. Options imitate a phone's microphone (`hp`),
   a room (`noise`), a piano out of tune (`cents`), strings of one key not
   quite in unison (`beat`, in Hz; `beatDepth` how loud the second string is
   beside the first) and a held pedal (`pedal`).

   The same file runs in Node (require) and in the page under test (the UI
   test evaluates gitarr's synth.js and then this; it sets window.PN_SYNTH). */

(function (root) {
  'use strict';

  const G = typeof module !== 'undefined' && module.exports ? require('../gitarr/synth.js') : root.GT_SYNTH;

  const freqOf = (midi, cents) => 440 * Math.pow(2, (midi - 69) / 12 + (cents || 0) / 1200);

  /* One key held for `held` seconds, in a buffer of `dur` seconds. */
  function note(o) {
    const sr = o.sr || 48000;
    const dur = o.dur || 1;
    const held = o.held === undefined ? dur : o.held;
    const f0 = freqOf(o.midi, o.cents);
    const base = { sr, dur, f0, B: o.B === undefined ? 0.0004 : o.B, p: 0.12, tau1: o.tau1 || 1.4, amp: o.amp || 0.3, attack: o.attack, seed: o.seed || (o.midi * 7 + 1) };
    let x = G.pluck(base);
    if (o.beat) {
      const y = G.pluck(Object.assign({}, base, { f0: f0 + o.beat, seed: base.seed + 5 }));
      const w = o.beatDepth === undefined ? 0.4 : o.beatDepth;
      for (let i = 0; i < x.length; i++) x[i] = (x[i] + w * y[i]) / (1 + w);
    }
    if (!o.pedal) {
      const off = Math.round(held * sr);
      const tau = 0.035 * sr;
      for (let i = off; i < x.length; i++) x[i] *= Math.exp(-(i - off) / tau);
    }
    return x;
  }

  /* notes: [[midi, beats], ...] at `bpm`; each key is held for `legato` of
     its length (1 = until the next one starts). Returns { x, sr, times }. */
  function melody(notes, o) {
    const q = o || {};
    const sr = q.sr || 48000;
    const beat = 60 / (q.bpm || 100);
    const lead = q.lead === undefined ? 0.3 : q.lead;
    const legato = q.legato === undefined ? 0.9 : q.legato;
    let t = lead;
    const parts = [];
    const times = [];
    notes.forEach(([midi, beats], i) => {
      const len = beats * beat;
      if (midi !== null) {
        parts.push({ x: note(Object.assign({}, q, { midi, sr, dur: q.pedal ? len + 2 : len * legato + 0.4, held: len * legato, seed: 11 + i })), at: t });
        times.push({ midi, at: t });
      }
      t += len;
    });
    const total = t + (q.tail === undefined ? 0.6 : q.tail);
    const x = G.mix(sr, total, parts);
    if (q.hp) { G.highpass(x, sr, q.hp); G.highpass(x, sr, q.hp); }
    if (q.noise) { const r = G.rng(q.seed || 3); for (let i = 0; i < x.length; i++) x[i] += q.noise * G.gauss(r); }
    return { x, sr, times, total };
  }

  const api = { note, melody, freqOf };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.PN_SYNTH = api;
})(typeof window !== 'undefined' ? window : this);
