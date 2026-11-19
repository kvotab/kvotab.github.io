/* What piano.html makes of the microphone: piano notes made here (synth.js)
   go through the listener a reading at a time, as the page's frame loop
   feeds it, and the keys it reports are compared with the keys played.

     node resources/tests/piano/test-ear.js

   Exit status is 0 when every check passes. */
const E = require('../../js/piano-ear.js');
const S = require('./synth.js');
const { check, done } = require('./check.js');

/* A signal through a listener, 50 readings a second of a 4096-sample
   window: the notes it reports, each with the clock at which it did. */
function listen(sig, opts, each) {
  const { x, sr } = sig;
  const ear = E.createListener(sr, opts);
  const size = 4096;
  const hop = Math.round(sr * 0.02);
  const out = [];
  for (let end = size; end <= x.length; end += hop) {
    const now = end / sr * 1000;
    if (each) each(ear, now);
    for (const e of ear.push(x.subarray(end - size, end), now)) out.push(Object.assign({ at: now }, e));
  }
  return { out, ear };
}

const keys = r => r.out.map(e => e.midi);
const wanted = sig => sig.times.map(n => n.midi);

/* Bjällerklang's first four bars: seven E:s to tell apart, then a leap. */
const JB = [[64, 1], [64, 1], [64, 2], [64, 1], [64, 1], [64, 2], [64, 1], [67, 1], [60, 1.5], [62, 0.5], [64, 4]];
const scale = (from, to) => { const a = []; for (let m = from; m <= to; m++) a.push([m, 1]); return a; };

/* ── A melody, as it is played ─────────────────────────────────────────── */

{
  const sig = S.melody(JB, { bpm: 104 });
  const r = listen(sig);
  check('Bjällerklang: every key, the repeated ones each time', keys(r), wanted(sig));
  const late = r.out.map((e, i) => e.at - sig.times[i].at * 1000);
  check('each is known within 130 ms of the hammer', Math.max(...late) <= 130, true);
  const off = r.out.map((e, i) => Math.abs(e.t - sig.times[i].at * 1000));
  check('and the moment it gives for the strike is within 70 ms of it', Math.max(...off) <= 70, true);
  check('a key struck again is told from a new one', r.out.map(e => (e.again ? 1 : 0)), [0, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0]);
}
check('played short and detached', (s => keys(listen(s)).join() === wanted(s).join())(S.melody(JB, { bpm: 104, legato: 0.5 })), true);
check('played fast (150 a minute)', (s => keys(listen(s)).join() === wanted(s).join())(S.melody(JB, { bpm: 150 })), true);
check('played softly', (s => keys(listen(s)).join() === wanted(s).join())(S.melody(JB, { bpm: 104, amp: 0.03 })), true);
check('through a phone (nothing under 250 Hz) in a room that is not silent', (s => keys(listen(s)).join() === wanted(s).join())(S.melody(JB, { bpm: 104, hp: 250, noise: 0.004 })), true);
check('at 44.1 kHz', (s => keys(listen(s)).join() === wanted(s).join())(S.melody(JB, { bpm: 104, sr: 44100 })), true);
check('eighth notes at 108', (s => keys(listen(s)).join() === wanted(s).join())(S.melody([[65, 1], [65, 0.5], [67, 0.5], [65, 0.5], [64, 0.5], [62, 1], [62, 1], [62, 1]], { bpm: 108 })), true);
check("Sankta Lucia's leaps in eighth notes", (s => keys(listen(s)).join() === wanted(s).join())(S.melody([[76, 0.5], [72, 0.5], [72, 0.5], [67, 0.5], [67, 0.5], [64, 0.5], [65, 0.5], [74, 0.5], [74, 2]], { bpm: 96 })), true);

/* ── Every key ─────────────────────────────────────────────────────────── */

for (const [label, from, to, more] of [
  ['the octave below middle C', 48, 60, {}],
  ['the octave below middle C through a phone (nothing under 300 Hz)', 48, 60, { hp: 300 }],
  ['from middle C to high C, black keys too', 60, 72, {}],
  ['from high C to the F above the next', 72, 89, {}],
]) {
  const sig = S.melody(scale(from, to), Object.assign({ bpm: 100 }, more));
  check(`every key: ${label}`, keys(listen(sig)), wanted(sig));
}

/* ── A piano that is not in tune ───────────────────────────────────────── */

for (const cents of [-35, 30]) {
  const sig = S.melody([...JB, ...JB], { bpm: 104, cents });
  const r = listen(sig);
  check(`a piano ${Math.abs(cents)} cents ${cents < 0 ? 'flat' : 'sharp'}: every key still`, keys(r), wanted(sig));
  check(`... and its tuning is followed to within 12 cents (${r.ear.tune().toFixed(0)})`, Math.abs(r.ear.tune() - cents) <= 12, true);
}
{
  // A semitone is 100 cents: started where the piano is, 45 flat is read right from the first note.
  const sig = S.melody(scale(60, 67), { bpm: 100, cents: -45 });
  check('a piano 45 cents flat, known from last time', keys(listen(sig, { tune: -45 })), wanted(sig));
}

/* ── What is not a key struck ──────────────────────────────────────────── */

{
  const r = listen(S.melody([[60, 8]], { bpm: 60, beat: 1.2 }));
  check('a long note whose strings beat slowly is one note', keys(r), [60]);
  const fast = listen(S.melody([[67, 8]], { bpm: 60, beat: 3, beatDepth: 0.6 }));
  check('strings badly out of unison may swell like new strikes: only ever the same key, marked as such',
    [fast.out[0].midi, fast.out[0].again, fast.out.slice(1).every(e => e.midi === 67 && e.again)], [67, false, true]);
}
{
  const G = require('../gitarr/synth.js');
  const r = listen({ x: G.noise(48000, 3, 0.05, 4), sr: 48000 });
  check('noise is no key', keys(r), []);
  check('silence is no key', keys(listen({ x: new Float32Array(48000 * 2), sr: 48000 })), []);
}
{
  // The page plays a note itself from 0.2 s to 1.3 s; the pupil's begin at 1.5 s.
  const sig = S.melody([[72, 2], [null, 0.4], [60, 1], [62, 1]], { bpm: 100, lead: 0.2 });
  const r = listen(sig, {}, (ear, now) => { if (now < 400) ear.deaf(1450); });
  check('while the page sounds, the listener is deaf', keys(r), [60, 62]);
}
{
  const sig = S.melody(JB, { bpm: 104, pedal: true });
  const r = listen(sig);
  check('with the pedal down the repeated key is still followed (the notes after it blur: the help says no pedal)', keys(r).slice(0, 6), [64, 64, 64, 64, 64, 64]);
}
check('the buffer it asks for fits an analyser', [E.createListener(48000).need <= 4096, E.createListener(44100).need <= 4096, E.createListener(96000).need <= 8192], [true, true, true]);

done();
