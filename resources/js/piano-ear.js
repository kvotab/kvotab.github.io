/* ==========================================================================
   PIANO - WHICH KEY WAS PLAYED

   What piano.html makes of the microphone, apart from the page, so it can be
   tested in Node (resources/tests/piano) with piano notes made in the test.

   The pitch of each moment comes from the guitar tuner's detector
   (gitarr-pitch.js: YIN on a copy of the sound at about 12 kHz), with a
   shorter window, since a melody moves faster than a string being tuned.
   This file turns one reading after another into keys pressed:

     a new note   the same key read CONFIRM times running - one reading alone
                  is often nonsense while one note gives way to the next;
     the same key again
                  the pitch cannot say that a key was struck twice, the
                  loudness can: it jumps when the hammer lands. A note counts
                  again when the level rises RE_RISE times above what it has
                  just been, while rising;
     the end      nothing clear for OFF_MS. A note dying away flickers at
                  the edge of hearing: the same key just after is the same
                  note, unless it is clearly louder than when it went.

   ONE NOTE AT A TIME. The detector hears a melody, not chords: two keys held
   together give it no pitch it can trust. The lessons are melodies for one
   hand, so that is all it needs - and a held pedal blurs it.

   THE PIANO'S OWN TUNING. A piano at home is seldom at 440 Hz, and one that
   has sunk a third of a semitone is still a piano to practise on. The
   listener follows how far the notes it hears lie from the nearest key, a
   little at a time, and reads the next ones from there (tune(), in cents).

   HOW LOUD THE PIANO COMES IN. Microphones differ: at the same piano an
   iPad heard the notes some 15 dB quieter than an iPhone, and a fixed level
   for a note (-50 dBFS) took all but the loudest playing there for silence.
   So the level a note must reach (the floor) follows the piano as heard, as
   the tuning does: it keeps MARGIN under how loud the notes come in, a step
   at a time (FOLLOW), and never rises above FLOOR - the level it starts at
   where nothing is known - nor falls below FLOOR_MIN. A clear key under the
   floor - clearly periodic, well above the room's noise, held as long as a
   note takes to be known - brings the floor down to just under it at once,
   unless the notes heard before were much louder: a radio in the next room
   is no piano. Where it was left is kept for next time (loudness()).

   AN OCTAVE OUT. A small microphone hears little of a low note's
   fundamental, and the detector may then take the octave above. Each note
   therefore carries `alts`: the keys an octave or more below that the same
   sound also fits. The page counts a note as right when the key it wants is
   the note or among its alts.
   ========================================================================== */

const PN_EAR = (() => {
  'use strict';

  const P = typeof GT_PITCH !== 'undefined' ? GT_PITCH : require('./gitarr-pitch.js');

  const EAR = Object.freeze({
    fmin: 95,          // a little under A2, the lowest key listened for
    fmax: 1500,        // a little over F6
    window: 0.045,     // seconds of sound in each reading
    low: 45,           // A2 ...
    high: 89,          // ... to F6: readings outside are not keys
    floor: 0.003,      // quieter than this (-50 dBFS) is silence, at first ...
    floorMin: 0.0003,  // ... and the floor follows the piano down to this (-70 dBFS)
    margin: 0.18,      // the floor's place: this share of how loud notes come in (-15 dB) ...
    follow: 0.15,      // ... toward which it moves this much (in dB) with each note
    sure: 0.8,         // a key under the floor brings it down: this periodic ...
    sureOver: 5,       // ... this many times louder than the room ...
    sureNear: 0.25,    // ... and at least this share of how loud notes have come in
    over: 2.5,         // and a note is this many times louder than the room
    clarity: 0.7,      // how periodic a reading must be
    confirm: 3,        // readings of one key before it is a note
    confirmMs: 45,     // ... over at least this long
    offMs: 110,        // silence this long ends the note
    reRise: 1.5,       // the same key again: the level rises this much ...
    reLookMs: 70,      // ... over what it was at its lowest this recently ...
    rePeak: 0.25,      // ... to at least this share of the note's loudest ...
    reGapMs: 120,      // ... not sooner than this after the note before ...
    reHoldMs: 55,      // ... and the pitch is still the same this long after
    fadeMs: 2500,      // a key that died away is not a new note this soon after ...
    fadeRise: 2.5,     // ... unless it comes back this much louder
    tuneRate: 0.04,    // how fast the piano's tuning is followed
    tuneMax: 45,       // cents
  });

  /* The level of the newest `n` samples. */
  function levelOf(x, n) {
    const from = Math.max(0, x.length - n);
    let ss = 0;
    for (let i = from; i < x.length; i++) ss += x[i] * x[i];
    return Math.sqrt(ss / Math.max(1, x.length - from));
  }

  /**
   * A listener for one sample rate. push(samples, now) takes the newest
   * samples (an AnalyserNode's time-domain buffer) and the clock in
   * milliseconds, and returns the notes that began: [{ midi, alts, t,
   * again }] - t the moment the key was struck, as near as can be told
   * (a note is known some 60 to 100 ms after it), again true when it is the
   * sounding key struck once more.
   *
   * options.tune is where the piano's tuning starts, in cents, and
   * options.level how loud it came in last time ({ floor, typical }, as
   * loudness() gives it).
   */
  function createListener(sampleRate, options) {
    const o = Object.assign({}, EAR, options || {});
    const det = P.createDetector(sampleRate, { fmin: o.fmin, fmax: o.fmax, window: o.window });
    // The gate keeps the room's level and asks for clarity; the floor is this file's.
    const gate = P.createGate({ floor: o.floorMin, over: o.over, clarity: o.clarity });
    const short = Math.round(0.02 * sampleRate);
    const toFloor = v => Math.max(o.floorMin, Math.min(o.floor, v));
    const lv = o.level || {};
    let tune = Number.isFinite(o.tune) ? o.tune : 0;
    let floor = toFloor(lv.floor > 0 ? lv.floor : o.floor);
    let typical = lv.typical > 0 && lv.typical < 1 ? lv.typical : 0;   // how loud notes come in; 0: not known
    let quiet = null;          // a clear key under the floor: { key, n, since, peak }
    let cur = null;            // the key sounding now
    let cand = null;           // a key read, not yet a note
    let struck = null;         // the level jumped on the sounding key: perhaps struck again
    let faded = null;          // the key that last died away, and how loud it was then
    let lastLevel = 0;         // the level when the sounding key was last read
    let peak = 0;              // the loudest the sounding note has been
    let lastClear = -Infinity; // when the sounding key was last read
    let lastOn = -Infinity;    // when a note last began
    let env = [];              // recent levels: { t, v }
    let deafTo = -Infinity;
    let level = 0;
    let last = null;

    function keyOf(freq) {
      return 69 + 12 * Math.log2(freq / P.A4) - tune / 100;
    }

    function reset() {
      cur = null;
      cand = null;
      quiet = null;
      struck = null;
      faded = null;
      peak = 0;
      env = [];
    }

    /* A note heard, this loud as it began: how loud notes come in, and the
       floor a step toward MARGIN under that. */
    function learn(loud) {
      if (!(loud > 0)) return;
      typical = typical ? typical * Math.pow(loud / typical, 0.2) : loud;
      floor = toFloor(floor * Math.pow(toFloor(o.margin * loud) / floor, o.follow));
    }

    /* A reading clear in every way but its level. The same key, sure enough
       and long enough to be a note: the floor comes down to just under it.
       One much quieter than the notes heard before only brings what is
       known of them a step down (in dB, a third of the way), so that a few
       of them in a row are believed: the piano may have been moved away. */
    function underFloor(reading, now) {
      const k = Math.round(keyOf(reading.freq));
      if (k < o.low || k > o.high || reading.clarity < o.sure || reading.rms < o.sureOver * gate.room()) {
        quiet = null;
        return;
      }
      if (!quiet || quiet.key !== k) quiet = { key: k, n: 0, since: now, peak: 0, done: false };
      quiet.n++;
      quiet.peak = Math.max(quiet.peak, reading.rms);
      if (!quiet.done && quiet.n >= o.confirm && now - quiet.since >= o.confirmMs) {
        quiet.done = true;
        if (!typical || quiet.peak >= o.sureNear * typical) floor = toFloor(Math.min(floor, 0.5 * quiet.peak));
        else typical *= Math.pow(quiet.peak / typical, 0.3);
      }
    }

    function push(samples, now) {
      const out = [];
      level = levelOf(samples, short);
      if (now < deafTo) {
        reset();
        last = null;
        return out;
      }
      const reading = det.analyse(samples);
      const passed = gate.pass(reading);
      const clear = passed && reading.rms >= floor;
      if (passed && !clear) underFloor(reading, now);
      else quiet = null;
      let key = null;
      let exact = 0;
      if (clear) {
        exact = keyOf(reading.freq);
        key = Math.round(exact);
        if (key < o.low || key > o.high) key = null;
      }
      last = { key, freq: reading.freq, clarity: reading.clarity, rms: reading.rms };

      if (key === null) {
        cand = null;
        if (cur !== null && now - lastClear > o.offMs) {
          faded = { key: cur, level: lastLevel, t: now };
          cur = null;
          struck = null;
        }
      } else if (key === cur) {
        cand = null;
        lastClear = now;
        lastLevel = level;
        if (level > peak) peak = level;
        // The same key struck again: the level jumps while the pitch stays.
        // The jump alone is not believed - the next key's hammer lands a
        // few readings before its pitch is heard - so it waits (struck)
        // until the pitch has had time to change, and counts if it has not.
        let base = Infinity;
        for (const e of env) if (now - e.t <= o.reLookMs && e.v < base) base = e.v;
        if (!struck && now - lastOn >= o.reGapMs && base < Infinity && level > o.reRise * base && level > o.rePeak * peak) {
          struck = { t: now };
        }
        if (struck && now - struck.t >= o.reHoldMs) {
          lastOn = struck.t;
          learn(reading.rms);
          out.push({ midi: key, alts: altsOf(reading, key), t: struck.t - 10, again: true });
          struck = null;
          peak = level;
          env = [];
        }
        // Follow the piano's tuning by what a clear, settled note says.
        if (reading.clarity > 0.85 && now - lastOn > 80) {
          tune += o.tuneRate * (exact - key) * 100;
          tune = Math.max(-o.tuneMax, Math.min(o.tuneMax, tune));
        }
      } else {
        struck = null;
        if (!cand || cand.key !== key) cand = { key, n: 0, since: now, peak: 0 };
        cand.n++;
        cand.peak = Math.max(cand.peak, reading.rms);
        // A note dying away hovers at the edge of hearing: the same key
        // back again just after it faded is the same note, unless it is
        // clearly louder than it was when it went.
        const tail = faded && faded.key === key && now - faded.t < o.fadeMs && level < o.fadeRise * faded.level;
        if (tail) {
          cand = null;
        } else if (cand.n >= o.confirm && now - cand.since >= o.confirmMs) {
          cur = key;
          lastClear = now;
          lastOn = now;
          peak = level;
          learn(cand.peak);
          out.push({ midi: key, alts: altsOf(reading, key), t: cand.since - 30, again: false });
          cand = null;
          env = [];
        }
      }
      if (struck && now - struck.t > 250) struck = null;
      env.push({ t: now, v: level });
      while (env.length > 24 || (env.length && now - env[0].t > 400)) env.shift();
      return out;
    }

    /* The keys below that the same sound fits: the periods at two, three
       and four times the one the detector chose, where they dip as well. */
    function altsOf(reading, key) {
      const alts = [];
      const first = reading.cands && reading.cands[0];
      if (!first) return alts;
      for (const c of reading.cands) {
        if (c.k === 1 || c.d > Math.max(first.d + 0.1, 0.2)) continue;
        const exact = keyOf(c.freq);
        const k = Math.round(exact);
        if (k !== key && k >= o.low && Math.abs(exact - k) < 0.4 && !alts.includes(k)) alts.push(k);
      }
      return alts;
    }

    return {
      push,
      need: det.need,
      /* Hear nothing until `until` (the page is making a sound itself). */
      deaf(until) { deafTo = Math.max(deafTo, until); },
      reset,
      level: () => level,
      current: () => cur,
      last: () => last,
      tune: () => tune,
      setTune(cents) { tune = Math.max(-o.tuneMax, Math.min(o.tuneMax, Number(cents) || 0)); },
      room: () => gate.room(),
      /* The level a note must reach now. */
      floor: () => floor,
      /* How loud the piano came in, to start from next time (options.level). */
      loudness: () => ({ floor: Math.round(floor * 1e6) / 1e6, typical: Math.round(typical * 1e6) / 1e6 }),
      options: o,
    };
  }

  return { EAR, createListener, levelOf };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = PN_EAR;
