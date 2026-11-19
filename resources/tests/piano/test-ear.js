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

/* ── A quiet microphone ────────────────────────────────────────────────── */

/* At amp 0.005 these notes peak near -54 dBFS, under the -50 a note needs
   where nothing is known: an iPad heard a piano about that much quieter than
   an iPhone did, and the page heard nothing there but the loudest playing. */
const dB = v => 20 * Math.log10(v);
{
  const sig = S.melody(JB, { bpm: 104, amp: 0.005 });
  const r = listen(sig);
  check('a quiet microphone (notes near -54 dBFS): every key all the same', keys(r), wanted(sig));
  check(`... the level a note needs following the piano down (to ${dB(r.ear.floor()).toFixed(0)} dBFS)`, dB(r.ear.floor()) < -60, true);
  check('... the first note known within 200 ms, the rest as fast as ever (130)',
    r.out.map((e, i) => e.at - sig.times[i].at * 1000).every((late, i) => late <= (i ? 130 : 200)), true);
  const again = listen(sig, { level: r.ear.loudness() });
  check('... and next time, from where it was left, the first note too is known within 130 ms',
    [keys(again).join() === wanted(sig).join(), again.out[0].at - sig.times[0].at * 1000 <= 130], [true, true]);
}
for (const amp of [0.01, 0.003]) {
  const sig = S.melody(JB, { bpm: 104, amp });
  check(`notes near ${dB(amp / 0.3 * 0.12).toFixed(0)} dBFS: every key`, keys(listen(sig)), wanted(sig));
}
{
  const sig = S.melody(JB, { bpm: 104, amp: 0.005, noise: 0.0001 });
  check('a quiet microphone in a room that hisses at -80 dBFS: every key', keys(listen(sig)), wanted(sig));
}
{
  const r = listen(S.melody(JB, { bpm: 104 }));
  check('playing as loud as these tests do leaves the level a note needs at -50 dBFS', Math.abs(dB(r.ear.floor()) + 50.5) < 0.2, true);
}
{
  // A melody played loud, then a quieter one 34 dB down, as a radio might
  // play it in the next room: the piano heard first was much louder.
  const loud = S.melody(JB, { bpm: 104 });
  const far = S.melody(scale(60, 67), { bpm: 100, amp: 0.006 });
  const x = new Float32Array(loud.x.length + far.x.length);
  x.set(loud.x);
  x.set(far.x, loud.x.length);
  const r = listen({ x, sr: loud.sr });
  const after = keys(r).slice(wanted(loud).length);
  check('a tune far quieter than the piano heard before is no piano: its first three notes are not heard',
    [keys(r).slice(0, wanted(loud).length).join() === wanted(loud).join(), [60, 61, 62].some(k => after.includes(k))], [true, false]);
  const short = S.melody([[60, 1], [64, 1], [67, 1]], { bpm: 100, amp: 0.006 });
  check('... nor three such notes after a session that knew the piano was loud', keys(listen(short, { level: r.ear.loudness() })), []);
  // But a piano that keeps coming in that quiet - moved away - is followed after a few notes.
  const moved = S.melody(JB, { bpm: 104, amp: 0.005 });
  const m = listen(moved, { level: r.ear.loudness() });
  check(`... while a piano that keeps coming in that quiet is followed after a few notes (${keys(m).length} of 11, the last 6 at least)`,
    keys(m).slice(-6).join(), wanted(moved).slice(-6).join());
}
check('what is kept for next time is as given: a floor between -70 and -50 dBFS',
  [E.createListener(48000, { level: { floor: 0.0001, typical: 0.01 } }).floor(), E.createListener(48000, { level: { floor: 1, typical: 0.01 } }).floor(),
    E.createListener(48000, { level: { floor: 0.001, typical: 0.01 } }).loudness()], [0.0003, 0.003, { floor: 0.001, typical: 0.01 }]);

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
