/* ==========================================================================
   PIANO - THE PAGE'S OWN SOUNDS

   The notes piano.html plays itself - a key pressed on the screen, a melody
   played for the pupil to hear - and its few effects: right, wrong, done, a
   star, the beat. All made in the browser with the Web Audio API, from an
   oscillator with a piano's overtones under an envelope that strikes and
   dies away: no sound files, nothing downloaded.

   There is one AudioContext, and the microphone listens through the same
   one (piano.js). A browser only lets a page make sound after a tap or a
   key, so it is made, and resumed, from one. On an iPhone, Web Audio follows
   the ring/silent switch: with the phone on silent, nothing is heard.

   THE MICROPHONE HEARS THE PAGE. Whatever is played here comes back through
   the microphone as if the pupil had played it. Every sound therefore says
   how long it lasts (busyUntil, on the page's clock), and piano.js keeps the
   listener deaf until then.
   ========================================================================== */

const PN_SOUND = (() => {
  'use strict';

  let ctx = null;
  let master = null;
  let wave = null;
  let on = true;
  let busy = 0;                 // performance.now() until which the page sounds
  const played = [];

  /* The context, made on first use: from a tap or a key. */
  function context() {
    if (!ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      ctx = new AC();
      const squeeze = ctx.createDynamicsCompressor();
      squeeze.threshold.value = -14;
      squeeze.ratio.value = 3;
      master = ctx.createGain();
      master.gain.value = 0.9;
      master.connect(squeeze).connect(ctx.destination);
      // A struck string: a strong fundamental and overtones falling away.
      const partials = [0, 1, 0.55, 0.32, 0.2, 0.12, 0.07, 0.04, 0.02];
      wave = ctx.createPeriodicWave(new Float32Array(partials.length), Float32Array.from(partials));
    }
    if (ctx.state === 'suspended') ctx.resume().catch(e => ignoreFailure('piano sound: resume', e));
    return ctx;
  }

  function log(name) {
    played.push(name);
    if (played.length > 80) played.shift();
  }

  function claim(seconds) {
    busy = Math.max(busy, performance.now() + seconds * 1000);
  }

  const freqOf = midi => 440 * Math.pow(2, (midi - 69) / 12);

  /**
   * A piano note. opts: delay (seconds from now), dur (how long the key is
   * held), gain. Returns the seconds from now until it has died away.
   */
  function note(midi, opts) {
    const o = opts || {};
    const delay = o.delay || 0;
    const dur = o.dur || 0.6;
    log(`note:${midi}`);
    if (!on) return 0;
    const c = context();
    if (!c) return 0;
    const t0 = c.currentTime + 0.01 + delay;
    const f = freqOf(midi);
    const osc = c.createOscillator();
    osc.setPeriodicWave(wave);
    osc.frequency.value = f;
    // Bright as the hammer lands, mellower as the string rings.
    const tone = c.createBiquadFilter();
    tone.type = 'lowpass';
    tone.frequency.setValueAtTime(Math.min(9000, f * 9), t0);
    tone.frequency.exponentialRampToValueAtTime(Math.min(5000, f * 3), t0 + 0.35);
    const g = c.createGain();
    const peak = (o.gain || 0.5) * Math.min(1, Math.pow(261.6 / f, 0.35) + 0.25);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(peak, t0 + 0.006);
    g.gain.exponentialRampToValueAtTime(peak * 0.42, t0 + Math.max(0.05, dur));
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur + 0.22);
    osc.connect(tone).connect(g).connect(master);
    osc.start(t0);
    osc.stop(t0 + dur + 0.26);
    const total = delay + dur + 0.26;
    claim(total);
    return total;
  }

  /* A plain tone for the effects: an oscillator and an envelope. */
  function ping(c, t0, freq, dur, type, gain) {
    const osc = c.createOscillator();
    const g = c.createGain();
    osc.type = type || 'sine';
    osc.frequency.value = freq;
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(gain, t0 + 0.008);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    osc.connect(g).connect(master);
    osc.start(t0);
    osc.stop(t0 + dur + 0.03);
  }

  const C5 = 523.25, E5 = 659.25, G5 = 783.99, C6 = 1046.5, E6 = 1318.5, G6 = 1567.98;

  /* [seconds it lasts, what it plays] */
  const EFFECTS = {
    right: [0.42, (c, t) => { ping(c, t, 880, 0.12, 'sine', 0.3); ping(c, t + 0.09, E6, 0.32, 'sine', 0.28); }],
    wrong: [0.4, (c, t) => { ping(c, t, 233, 0.16, 'triangle', 0.26); ping(c, t + 0.13, 196, 0.26, 'triangle', 0.22); }],
    done: [0.8, (c, t) => [C5, E5, G5, C6].forEach((f, i) => ping(c, t + i * 0.1, f, i === 3 ? 0.45 : 0.16, 'triangle', 0.26))],
    star: [0.5, (c, t) => { ping(c, t, C6, 0.14, 'sine', 0.22); ping(c, t + 0.07, G6, 0.4, 'sine', 0.2); }],
    fanfare: [1.4, (c, t) => {
      [C5, E5, G5, C6].forEach((f, i) => ping(c, t + i * 0.09, f, 0.16, 'triangle', 0.26));
      for (const f of [C6, E6, G6]) ping(c, t + 0.42, f, 0.9, 'triangle', 0.17);
    }],
  };

  function effect(name, delay) {
    log(name);
    if (!on || !EFFECTS[name]) return 0;
    const c = context();
    if (!c) return 0;
    const [length, make] = EFFECTS[name];
    try {
      make(c, c.currentTime + 0.01 + (delay || 0));
    } catch (e) {
      ignoreFailure(`piano sound: ${name}`, e);
    }
    claim((delay || 0) + length);
    return (delay || 0) + length;
  }

  /* The beat: a short dry click, higher on the first beat of a bar. Short
     enough that the listener is not made deaf for it. */
  function tick(strong, delay) {
    if (!on) return;
    const c = context();
    if (!c) return;
    ping(c, c.currentTime + 0.005 + (delay || 0), strong ? 1760 : 1175, 0.045, 'square', strong ? 0.11 : 0.08);
  }

  function setOn(value) {
    on = !!value;
  }

  return {
    context, note, effect, tick, setOn, freqOf,
    isOn: () => on,
    /* performance.now() until which the page itself is heard, with room for the echo. */
    busyUntil: () => busy + 220,
    names: Object.keys(EFFECTS),
    /* For the tests: what has been played, and whether the audio exists. */
    log: () => played.slice(),
    clearLog: () => { played.length = 0; },
    state: () => (ctx ? ctx.state : 'none'),
  };
})();
