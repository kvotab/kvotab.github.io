/* ==========================================================================
   WINNETKAKORT AND GLOSOR - SOUND EFFECTS

   Loaded by winnetkakort.html and flashcards.html (Glosor): both have the
   same cards, and the same sounds for them. A change here is heard on both.

   Made in the browser with the Web Audio API, from oscillators and a little
   noise: no sound files, nothing downloaded, nothing anybody else owns. The
   sounds are short and soft, and a wrong answer is a gentle "uh-oh", never a
   buzzer - the page is for children practising, not for an exam.

     flip     the card turns: a swish of paper
     land     the card lands in its pile: a soft tap
     right    right, and quick: two rising notes
     okay     right, but slow or with the hint: one softer note
     wrong    two soft falling notes
     hint     the hint opens: a small bubble
     done     the pile is finished
     allKan   every card in the Kan pile
     record   a record for the pile

   Off until the pupil switches it on. A browser only lets a page make sound
   after a tap or a key, so the audio is only started - and resumed, after
   the browser has suspended it - from one. On an iPhone, Web Audio follows
   the ring/silent switch: with the phone on silent, nothing is heard.
   ========================================================================== */

const WK_SOUND = (() => {
  'use strict';

  let ctx = null;
  let master = null;
  let on = false;
  const played = [];
  const noiseBuffers = new WeakMap();

  /* The master gain, and a compressor after it so that sounds which overlap
     (a chime as the card swishes) never clip. */
  function masterChain(c) {
    const squeeze = c.createDynamicsCompressor();
    squeeze.threshold.value = -12;
    squeeze.ratio.value = 3;
    const gain = c.createGain();
    gain.gain.value = 0.9;
    gain.connect(squeeze).connect(c.destination);
    return gain;
  }

  /* The audio, made on first use and only from a tap or a key. */
  function context() {
    if (!ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      ctx = new AC();
      master = masterChain(ctx);
    }
    if (ctx.state === 'suspended') ctx.resume().catch(e => ignoreFailure('sound effects: resume', e));
    return ctx;
  }

  function noise(c) {
    if (!noiseBuffers.has(c)) {
      const n = Math.floor(c.sampleRate * 0.5);
      const buffer = c.createBuffer(1, n, c.sampleRate);
      const data = buffer.getChannelData(0);
      for (let i = 0; i < n; i++) data[i] = Math.random() * 2 - 1;
      noiseBuffers.set(c, buffer);
    }
    return noiseBuffers.get(c);
  }

  /* An envelope that starts and ends at silence: exponential ramps may not
     reach zero, so they go to a ten-thousandth. */
  function envelope(g, t0, peak, attack, dur) {
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(peak, t0 + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  }

  /* A note: an oscillator, with a quieter octave above it for a bell's ring. */
  function tone({ c, out }, t0, freq, dur, { type = 'sine', gain = 0.3, glide = null, bell = 0.25, attack = 0.006 } = {}) {
    for (const [mult, level, length] of [[1, 1, dur], [2, bell, dur * 0.6]]) {
      if (!level) continue;
      const osc = c.createOscillator();
      const g = c.createGain();
      osc.type = type;
      osc.frequency.setValueAtTime(freq * mult, t0);
      if (glide) osc.frequency.exponentialRampToValueAtTime(glide * mult, t0 + length);
      envelope(g, t0, gain * level, attack, length);
      osc.connect(g).connect(out);
      osc.start(t0);
      osc.stop(t0 + length + 0.03);
    }
  }

  /* Noise through a band-pass filter that sweeps: paper, or a tap. */
  function hiss({ c, out }, t0, dur, { from, to, gain, q = 0.9, attack = 0.02 }) {
    const src = c.createBufferSource();
    src.buffer = noise(c);
    const band = c.createBiquadFilter();
    band.type = 'bandpass';
    band.Q.value = q;
    band.frequency.setValueAtTime(from, t0);
    band.frequency.exponentialRampToValueAtTime(to, t0 + dur);
    const g = c.createGain();
    envelope(g, t0, gain, attack, dur);
    src.connect(band).connect(g).connect(out);
    src.start(t0);
    src.stop(t0 + dur + 0.03);
  }

  const G4 = 392, C5 = 523.25, E5 = 659.25, G5 = 783.99, A5 = 880, C6 = 1046.5, E6 = 1318.5, G6 = 1567.98, C7 = 2093, E7 = 2637;

  const SOUNDS = {
    flip: (a, t) => hiss(a, t, 0.14, { from: 1100, to: 3400, gain: 0.9 }),
    land: (a, t) => {
      hiss(a, t, 0.06, { from: 900, to: 300, gain: 0.9, q: 0.7, attack: 0.004 });
      tone(a, t, 170, 0.07, { gain: 0.4, glide: 90, bell: 0 });
    },
    right: (a, t) => {
      tone(a, t, A5, 0.13, { gain: 0.36 });
      tone(a, t + 0.1, E6, 0.4, { gain: 0.34 });
    },
    okay: (a, t) => tone(a, t, E5, 0.28, { gain: 0.5 }),
    wrong: (a, t) => {
      tone(a, t, G4, 0.16, { type: 'triangle', gain: 0.3, bell: 0 });
      tone(a, t + 0.15, 311.13, 0.32, { type: 'triangle', gain: 0.27, bell: 0, glide: 293.66 });
    },
    hint: (a, t) => tone(a, t, 600, 0.14, { gain: 0.48, glide: 900, bell: 0 }),
    done: (a, t) => [G4, C5, E5].forEach((f, i) => tone(a, t + i * 0.1, f, i === 2 ? 0.4 : 0.16, { type: 'triangle', gain: 0.26 })),
    allKan: (a, t) => {
      [C5, E5, G5].forEach((f, i) => tone(a, t + i * 0.09, f, 0.16, { type: 'triangle', gain: 0.26 }));
      tone(a, t + 0.27, C6, 0.5, { type: 'triangle', gain: 0.3 });
      tone(a, t + 0.42, C7, 0.25, { gain: 0.1, bell: 0 });
      tone(a, t + 0.52, E7, 0.3, { gain: 0.09, bell: 0 });
    },
    record: (a, t) => {
      [C5, E5, G5, C6].forEach((f, i) => tone(a, t + i * 0.09, f, 0.15, { type: 'triangle', gain: 0.26 }));
      for (const f of [C6, E6, G6]) tone(a, t + 0.4, f, 0.7, { type: 'triangle', gain: 0.17 });
      tone(a, t + 0.62, E7, 0.3, { gain: 0.09, bell: 0 });
    },
  };

  /**
   * Play a sound, if sounds are on.
   *
   * @param {string} name - one of the SOUNDS
   * @param {number} [delay] - seconds from now
   */
  function play(name, delay = 0) {
    if (!on || !SOUNDS[name]) return;
    const c = context();
    if (!c) return;
    try {
      SOUNDS[name]({ c, out: master }, c.currentTime + 0.01 + delay);
      played.push(name);
      if (played.length > 60) played.shift();
    } catch (e) {
      ignoreFailure(`sound effects: ${name}`, e);
    }
  }

  /* Switched on from the page's button - a tap, so the audio may start -
     or read from storage at load, when it waits for the first tap. */
  function setOn(value, now) {
    on = !!value;
    if (on && now) context();
    if (!on && ctx && ctx.state === 'running') ctx.suspend().catch(e => ignoreFailure('sound effects: suspend', e));
  }

  /* Any tap or key: the moment a browser lets the audio run. */
  function unlock() {
    if (on) context();
  }

  /**
   * A sound rendered silently, offline, as the tests measure it: its peak,
   * its loudness (RMS over the part that sounds) and how long it lasts.
   *
   * @param {string} name
   * @returns {Promise<{peak: number, rms: number, seconds: number}>}
   */
  async function measure(name) {
    const OAC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    const rate = 44100;
    const c = new OAC(1, Math.round(rate * 1.6), rate);
    SOUNDS[name]({ c, out: masterChain(c) }, 0.01);
    const data = (await c.startRendering()).getChannelData(0);
    let peak = 0, sum = 0, first = -1, last = 0;
    for (let i = 0; i < data.length; i++) {
      const v = Math.abs(data[i]);
      if (v > peak) peak = v;
      if (v > 1e-3) { if (first < 0) first = i; last = i; }
    }
    for (let i = Math.max(0, first); i <= last; i++) sum += data[i] * data[i];
    return { peak, rms: Math.sqrt(sum / Math.max(1, last - first + 1)), seconds: (last - Math.max(0, first)) / rate };
  }

  return {
    play, setOn, unlock, measure, names: Object.keys(SOUNDS),
    /* For the tests: what has been played, and whether the audio exists. */
    log: () => played.slice(),
    state: () => (ctx ? ctx.state : 'none'),
  };
})();
