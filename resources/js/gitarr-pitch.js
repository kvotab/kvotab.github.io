/* ==========================================================================
   GITARR - WHICH STRING IS PLAYED, AND HOW FAR OUT IT IS

   Everything gitarr.html knows about sound lives here, apart from the page,
   so it can be tested in Node (resources/tests/gitarr) with plucks made in
   the test:

     STRINGS          the six strings of standard tuning, low E first;
     createDetector   the pitch of one window of microphone samples (YIN, on
                      a copy brought down to about 12 kHz), with the periods
                      at two, three and four times the one it found;
     interpret        which string a reading belongs to, and how many cents
                      out it is;
     createTracker    what the page shows from one reading per frame: the
                      string, the cents (a median of the last few), whether
                      it is live, and when it counts as in tune.

   THE OCTAVE TRAP. A phone's microphone hears little of the low E string's
   82 Hz: its second harmonic is often the loudest part, so the waveform
   nearly repeats every half period and YIN can take E3 (165 Hz) for the
   note. E3 lies between D and G, 200 cents from D, so the low E would be
   read as a very sharp D. interpret() therefore also weighs the periods at
   two to four times YIN's: one of them (E2 at 0 cents) lies on a string
   where the first does not. The reverse also holds - the high E repeats
   at every three periods, and three periods of E4 make an A2 (2 cents
   apart) - so a longer period has to be closer to a string by PENALTY
   cents before it wins.
   ========================================================================== */

const GT_PITCH = (() => {
  'use strict';

  const A4 = 440;

  /* Standard tuning, from the low E (string 6) to the high E (string 1).
     B is the English name; Swedish tradition calls it H. */
  const STRINGS = Object.freeze([
    { n: 6, name: 'E', octave: 2, midi: 40 },
    { n: 5, name: 'A', octave: 2, midi: 45 },
    { n: 4, name: 'D', octave: 3, midi: 50 },
    { n: 3, name: 'G', octave: 3, midi: 55 },
    { n: 2, name: 'B', octave: 3, midi: 59 },
    { n: 1, name: 'E', octave: 4, midi: 64 },
  ].map(s => Object.freeze(Object.assign(s, { freq: noteFreq(s.midi) }))));

  function noteFreq(midi, a4) {
    return (a4 || A4) * Math.pow(2, (midi - 69) / 12);
  }

  function centsBetween(f, ref) {
    return 1200 * Math.log2(f / ref);
  }

  /* ── The detector ─────────────────────────────────────────────────────── */

  /* A windowed-sinc low-pass, unity gain at DC; fc in cycles per sample. */
  function lowpassTaps(n, fc) {
    const h = new Float64Array(n);
    const m = (n - 1) / 2;
    let sum = 0;
    for (let i = 0; i < n; i++) {
      const t = i - m;
      const sinc = t === 0 ? 2 * fc : Math.sin(2 * Math.PI * fc * t) / (Math.PI * t);
      h[i] = sinc * (0.54 - 0.46 * Math.cos(2 * Math.PI * i / (n - 1)));
      sum += h[i];
    }
    for (let i = 0; i < n; i++) h[i] /= sum;
    return h;
  }

  /* Detector defaults. THRESHOLD is YIN's absolute threshold on the
     cumulative mean normalised difference; a window with no dip under it
     still gives its deepest dip, if that is under MAX_D. */
  const DETECTOR = Object.freeze({
    fmin: 60,          // the low E tuned down by more than 5 semitones
    fmax: 700,         // the high E sharp by more than 13 semitones
    window: 0.1,       // seconds summed in the difference function
    threshold: 0.15,
    maxD: 0.4,
  });

  /**
   * A pitch detector for one sample rate.
   *
   * analyse(samples) reads the newest samples of the array (an
   * AnalyserNode's time-domain buffer, or a slice of a test signal) and
   * returns { rms, freq, d, clarity, cands } - freq 0 when it hears no
   * pitch. cands lists the period YIN chose (k = 1) and the dips near two,
   * three and four times it, each { k, freq, d }.
   */
  function createDetector(sampleRate, options) {
    const o = Object.assign({}, DETECTOR, options || {});
    const decim = Math.max(1, Math.round(sampleRate / 12000));
    const fs = sampleRate / decim;
    const taps = decim > 1 ? lowpassTaps(8 * decim + 1, 0.3 / decim) : new Float64Array([1]);
    const tauMax = Math.ceil(fs / o.fmin) + 1;
    const tauMin = Math.max(2, Math.floor(fs / o.fmax));
    const W = Math.round(o.window * fs);
    const M = W + tauMax + 1;                       // decimated samples used
    const need = (M - 1) * decim + taps.length;     // input samples they come from
    const y = new Float64Array(M);
    const d = new Float64Array(tauMax + 2);
    const dn = new Float64Array(tauMax + 2);

    function decimate(x) {
      const start = x.length - need;
      const L = taps.length;
      let mean = 0;
      for (let m = 0; m < M; m++) {
        const base = start + m * decim;
        let acc = 0;
        for (let k = 0; k < L; k++) acc += taps[k] * x[base + k];
        y[m] = acc;
        mean += acc;
      }
      mean /= M;
      let ss = 0;
      for (let m = 0; m < M; m++) { y[m] -= mean; ss += y[m] * y[m]; }
      return Math.sqrt(ss / M);
    }

    /* The local minimum of dn at or after tau (dn falls until it rises). */
    function descend(tau) {
      while (tau + 1 < tauMax && dn[tau + 1] < dn[tau]) tau++;
      return tau;
    }

    /* Parabolic interpolation of dn around an integer minimum. */
    function refine(tau) {
      if (tau <= 1 || tau >= tauMax - 1) return { tau, d: dn[tau] };
      const a = dn[tau - 1], b = dn[tau], c = dn[tau + 1];
      const den = a - 2 * b + c;
      if (!(den > 0)) return { tau, d: b };
      const shift = Math.max(-0.5, Math.min(0.5, (a - c) / (2 * den)));
      return { tau: tau + shift, d: b - (a - c) * shift / 4 };
    }

    function analyse(x) {
      if (!x || x.length < need) return { rms: 0, freq: 0, d: 1, clarity: 0, cands: [] };
      const rms = decimate(x);
      if (!(rms > 1e-6)) return { rms, freq: 0, d: 1, clarity: 0, cands: [] };

      // YIN's difference function: y[j] against y[j + tau] for j over the
      // first W samples, so the two together end at the newest sample.
      for (let tau = 1; tau <= tauMax; tau++) {
        let s = 0;
        for (let j = 0; j < W; j++) {
          const diff = y[j] - y[j + tau];
          s += diff * diff;
        }
        d[tau] = s;
      }
      dn[0] = 1;
      let run = 0;
      for (let tau = 1; tau <= tauMax; tau++) {
        run += d[tau];
        dn[tau] = run > 0 ? d[tau] * tau / run : 1;
      }

      let pick = -1;
      for (let tau = tauMin; tau < tauMax; tau++) {
        if (dn[tau] < o.threshold) { pick = descend(tau); break; }
      }
      if (pick < 0) {
        let best = tauMin;
        for (let tau = tauMin + 1; tau < tauMax; tau++) if (dn[tau] < dn[best]) best = tau;
        if (dn[best] > o.maxD) return { rms, freq: 0, d: dn[best], clarity: 0, cands: [] };
        pick = best;
      }
      const first = refine(pick);
      const cands = [{ k: 1, freq: fs / first.tau, d: first.d }];
      for (let k = 2; k <= 4; k++) {
        const centre = k * first.tau;
        const span = Math.max(2, Math.round(0.03 * centre));
        const lo = Math.max(tauMin, Math.floor(centre - span));
        const hi = Math.min(tauMax - 1, Math.ceil(centre + span));
        if (lo >= hi) break;
        let best = lo;
        for (let tau = lo + 1; tau <= hi; tau++) if (dn[tau] < dn[best]) best = tau;
        if (best === lo || best === hi) continue;    // no dip inside the span
        const r = refine(best);
        cands.push({ k, freq: fs / r.tau, d: r.d });
      }
      return { rms, freq: cands[0].freq, d: first.d, clarity: Math.max(0, Math.min(1, 1 - first.d)), cands };
    }

    /* The second pass. A real string is stiff, so its partials run sharp of
       whole multiples (partial n by about 865·B·n² cents, B near 5e-5 on a
       guitar), and YIN's period, which all the partials up to 3.6 kHz help
       to choose, comes out sharp too: 5 to 6 cents on the low strings while
       the upper partials still ring. Measured again at the full sample rate,
       on the signal low-passed at 3.2 times the frequency found, the period
       is the fundamental's to within a fraction of a cent - and the high E's
       period, 36 samples at 12 kHz, is 146 at 48 kHz, where the parabola
       through the minimum no longer leaves a cent of error. */
    const fWin = Math.round(o.window * sampleRate);
    const warm = Math.round(0.012 * sampleRate);
    const refineNeed = fWin + Math.ceil(sampleRate / o.fmin * 1.02) + 4 + warm;
    let z = new Float64Array(0);

    function refineFreq(x, f) {
      if (!(f > 0)) return f;
      const tau0 = sampleRate / f;
      const span = Math.max(3, Math.ceil(0.015 * tau0));
      const tauLo = Math.max(2, Math.floor(tau0) - span);
      const tauHi = Math.ceil(tau0) + span;
      const total = warm + fWin + tauHi + 1;
      if (!x || x.length < total) return f;
      if (z.length < total) z = new Float64Array(total);
      const start = x.length - total;
      for (let i = 0; i < total; i++) z[i] = x[start + i];
      const fc = Math.min(3.2 * f, 0.4 * sampleRate);
      biquad(z, total, lowpassCoefs(fc, sampleRate, 0.5412));
      biquad(z, total, lowpassCoefs(fc, sampleRate, 1.3066));
      const dd = [];
      for (let tau = tauLo; tau <= tauHi; tau++) {
        let s = 0;
        for (let j = warm; j < warm + fWin; j++) {
          const diff = z[j] - z[j + tau];
          s += diff * diff;
        }
        dd.push(s);
      }
      // The deepest interior minimum; one on the edge of the span means the
      // first pass was further out than the span allows, so it stands.
      let best = -1;
      for (let k = 1; k < dd.length - 1; k++) {
        if (dd[k] <= dd[k - 1] && dd[k] <= dd[k + 1] && (best < 0 || dd[k] < dd[best])) best = k;
      }
      if (best < 0) return f;
      const a = dd[best - 1], b = dd[best], c = dd[best + 1];
      const den = a - 2 * b + c;
      const shift = den > 0 ? Math.max(-0.5, Math.min(0.5, (a - c) / (2 * den))) : 0;
      return sampleRate / (tauLo + best + shift);
    }

    return { sampleRate, fs, decim, tauMin, tauMax, W, need: Math.max(need, refineNeed), analyse, refineFreq };
  }

  /* RBJ low-pass biquad, normalised: [b0, b1, b2, a1, a2]. */
  function lowpassCoefs(fc, sr, q) {
    const w = 2 * Math.PI * fc / sr;
    const cs = Math.cos(w), al = Math.sin(w) / (2 * q);
    const a0 = 1 + al;
    return [(1 - cs) / 2 / a0, (1 - cs) / a0, (1 - cs) / 2 / a0, -2 * cs / a0, (1 - al) / a0];
  }

  /* One biquad over z[0..n), in place. */
  function biquad(z, n, c) {
    const b0 = c[0], b1 = c[1], b2 = c[2], a1 = c[3], a2 = c[4];
    let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
    for (let i = 0; i < n; i++) {
      const x0 = z[i];
      const y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2;
      x2 = x1; x1 = x0; y2 = y1; y1 = y0;
      z[i] = y0;
    }
  }

  /* ── Which string ─────────────────────────────────────────────────────── */

  /* A period at k > 1 times YIN's must be this many cents closer to a
     string before it is believed (see THE OCTAVE TRAP above). */
  const PENALTY = 35;
  /* ... must itself lie within this many cents of a string - otherwise a
     G string two semitones flat (F3, 200 cents from G) would be heard as
     F2, a low E 100 cents sharp ... */
  const SUB_REACH = 80;
  /* ... and its dip may be this much shallower than the first one's. */
  const DIP_SLACK = 0.1;
  /* Out of range for the automatic choice: further than this from the
     lowest or the highest string. Inside the range every note lies within
     250 cents of some string. */
  const AUTO_RANGE = 300;

  function nearestString(f, a4) {
    let best = 0, bestAbs = Infinity, bestCents = 0;
    for (let i = 0; i < STRINGS.length; i++) {
      const c = centsBetween(f, noteFreq(STRINGS[i].midi, a4));
      if (Math.abs(c) < bestAbs) { best = i; bestAbs = Math.abs(c); bestCents = c; }
    }
    return { i: best, cents: bestCents };
  }

  /**
   * Which string a reading is, and how many cents from it.
   *
   * With `string` (an index into STRINGS) the string is given - the player
   * picked it - and the choice is only between YIN's period and twice it.
   * Returns { i, cents, freq, k } or null.
   */
  function interpret(reading, opts) {
    if (!reading || !(reading.freq > 0) || !reading.cands || !reading.cands.length) return null;
    const o = opts || {};
    const a4 = o.a4 || A4;
    const first = reading.cands[0];
    const fixed = Number.isInteger(o.string) ? o.string : null;
    let best = null;
    for (const c of reading.cands) {
      if (c.k > 1 && c.d > Math.max(first.d + DIP_SLACK, 0.2)) continue;
      if (fixed !== null && c.k > 2) continue;
      const pos = fixed === null
        ? nearestString(c.freq, a4)
        : { i: fixed, cents: centsBetween(c.freq, noteFreq(STRINGS[fixed].midi, a4)) };
      if (c.k > 1 && Math.abs(pos.cents) > SUB_REACH) continue;
      const score = Math.abs(pos.cents) + (c.k > 1 ? PENALTY : 0);
      if (!best || score < best.score) best = { i: pos.i, cents: pos.cents, freq: c.freq, k: c.k, score };
    }
    if (!best) return null;
    if (fixed === null && Math.abs(best.cents) > AUTO_RANGE) return null;
    if (fixed !== null && Math.abs(best.cents) > 1200) return null;
    return { i: best.i, cents: best.cents, freq: best.freq, k: best.k };
  }

  /**
   * One frame of sound, start to end: the reading, which string it is, and
   * its cents from the second pass. Returns { reading, hit }, hit null when
   * no string is heard.
   */
  function hear(detector, x, opts) {
    const reading = detector.analyse(x);
    const hit = interpret(reading, opts);
    if (!hit) return { reading, hit: null };
    const f = detector.refineFreq(x, hit.freq);
    // The second pass only ever nudges; a big move means it lost its way.
    const moved = centsBetween(f, hit.freq);
    if (Math.abs(moved) < 30) {
      hit.freq = f;
      hit.cents += moved;
    }
    return { reading, hit };
  }

  /* ── Loud and clear enough ────────────────────────────────────────────── */

  /* A reading counts when it is periodic enough (clarity, 1 minus YIN's
     dip) and loud enough: over FLOOR (-56 dBFS) and OVER times the room.
     The room's level is followed only in windows with no periodicity to
     speak of (clarity under 0.5) - a ringing string has plenty even where
     no string is chosen, so it never lifts the room, while voices and
     traffic do - falling fast and rising slowly. */
  const GATE = Object.freeze({ floor: 0.0016, over: 2.5, clarity: 0.75 });

  function createGate(options) {
    const o = Object.assign({}, GATE, options || {});
    let room = o.floor / o.over;
    function pass(reading) {
      if (!reading) return false;
      const ok = reading.freq > 0 && reading.clarity >= o.clarity && reading.rms >= Math.max(o.floor, room * o.over);
      if (reading.clarity < 0.5 && reading.rms > 0) {
        room = reading.rms < room ? 0.6 * room + 0.4 * reading.rms : 0.97 * room + 0.03 * reading.rms;
      }
      return ok;
    }
    return { pass, room: () => room, options: o };
  }

  /* ── What the page shows ──────────────────────────────────────────────── */

  const TRACKER = Object.freeze({
    switchMs: 120,     // a new string must hold this long before it is shown...
    switchHits: 3,     // ...over at least this many readings
    quietMs: 250,      // unless the shown one has been silent this long
    holdMs: 1600,      // a silent string stays on screen, dimmed, this long
    historyMs: 450,    // the median runs over readings this recent...
    historyN: 7,       // ...and at most this many
    inTuneCents: 5,    // within this many cents is in tune...
    inTuneMs: 300,     // ...once it has stayed there this long
    offTuneCents: 12,  // a string marked tuned loses its tick past this...
    offTuneMs: 400,    // ...held this long
  });

  function median(values) {
    const s = values.slice().sort((a, b) => a - b);
    const m = s.length >> 1;
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }

  /**
   * Turns one hit per frame ({ i, cents, freq } from interpret, or null)
   * into what the page shows. update(now, hit) returns a snapshot:
   *
   *   string   the string on screen, or null before the first one;
   *   cents    the median of its recent readings;
   *   freq     the frequency that median stands for;
   *   live     the string is sounding now (false once it has been quiet);
   *   shown    something is on screen (live, or quiet for under holdMs);
   *   inTune   within inTuneCents for inTuneMs, and live;
   *   tuned    one flag per string: it has been in tune since it was last
   *            heard clearly out of tune;
   *   justTuned  the string that became in tune on this very update.
   */
  function createTracker(options) {
    const o = Object.assign({}, TRACKER, options || {});
    const tuned = STRINGS.map(() => false);
    let string = null, hist = [], lastAt = -Infinity, cand = null;
    let inTuneSince = null, offSince = null, inTune = false;
    let cents = null, freq = null;

    function show(i, now) {
      string = i;
      hist = [];
      inTuneSince = null;
      offSince = null;
      inTune = false;
      cand = null;
      lastAt = now;
    }

    function update(now, hit) {
      let justTuned = null;
      if (hit) {
        if (string === null) {
          show(hit.i, now);
        } else if (hit.i === string) {
          cand = null;
        } else {
          if (!cand || cand.i !== hit.i) cand = { i: hit.i, since: now, n: 0 };
          cand.n++;
          const quiet = now - lastAt > o.quietMs;
          if (quiet || (now - cand.since >= o.switchMs && cand.n >= o.switchHits)) show(hit.i, now);
        }
        if (hit.i === string) {
          lastAt = now;
          hist.push({ t: now, cents: hit.cents, freq: hit.freq });
          while (hist.length > o.historyN || (hist.length > 1 && now - hist[0].t > o.historyMs)) hist.shift();
          cents = median(hist.map(h => h.cents));
          const ref = hist[0].freq / Math.pow(2, hist[0].cents / 1200);
          freq = ref * Math.pow(2, cents / 1200);
          if (Math.abs(cents) <= o.inTuneCents) {
            offSince = null;
            if (inTuneSince === null) inTuneSince = now;
            if (!inTune && now - inTuneSince >= o.inTuneMs) {
              inTune = true;
              if (!tuned[string]) justTuned = string;
              tuned[string] = true;
            }
          } else {
            inTuneSince = null;
            inTune = false;
            if (Math.abs(cents) > o.offTuneCents) {
              if (offSince === null) offSince = now;
              if (now - offSince >= o.offTuneMs) tuned[string] = false;
            } else {
              offSince = null;
            }
          }
        }
      }
      const live = string !== null && now - lastAt <= o.quietMs;
      if (!live) { inTuneSince = null; offSince = null; }
      return {
        string,
        cents: string === null ? null : cents,
        freq: string === null ? null : freq,
        live,
        shown: string !== null && now - lastAt <= o.holdMs,
        inTune: inTune && live,
        tuned: tuned.slice(),
        justTuned,
      };
    }

    /* The player picked another string, or the auto choice came back. */
    function reset() {
      string = null;
      hist = [];
      cand = null;
      inTuneSince = null;
      offSince = null;
      inTune = false;
      cents = null;
      freq = null;
      lastAt = -Infinity;
    }

    function clearTuned() {
      for (let i = 0; i < tuned.length; i++) tuned[i] = false;
    }

    return { update, reset, clearTuned, options: o };
  }

  /* ── Which way to turn ────────────────────────────────────────────────── */

  /**
   * Where string i's tuner sits and which way its key turns, seen from the
   * front of the headstock with the headstock up.
   *
   * On a 3 + 3 headstock the bass strings (E A D) have their tuners on the
   * left and the treble strings (G B E) on the right; a left-handed guitar
   * is the mirror image. Every string leaves its post on the inside, so a
   * post on the left turns anticlockwise to tighten and one on the right
   * clockwise.
   *
   * The keys are another matter: tuner makers cut the same worm gear for
   * both sides, so every key tightens anticlockwise seen from its own end -
   * which, seen from the front, rolls the front of a left key up (toward
   * the top of the headstock) and the front of a right key down. A few
   * guitars go the other way; `reverse` is for those.
   *
   * Returns { side: 'left'|'right', tighten, keyFront: 'up'|'down',
   *           post: 'ccw'|'cw' } for the turn that brings the string up
   * to pitch when cents < 0 and down to it when cents > 0.
   */
  function turn(i, cents, opts) {
    const o = opts || {};
    const bass = i < 3;
    const side = (bass !== !!o.lefty) ? 'left' : 'right';
    const tighten = cents < 0;
    let up = (side === 'left') === tighten;
    if (o.reverse) up = !up;
    const ccw = (side === 'left') === tighten;
    return { side, tighten, keyFront: up ? 'up' : 'down', post: ccw ? 'ccw' : 'cw' };
  }

  return {
    A4, STRINGS, DETECTOR, TRACKER, GATE, PENALTY, SUB_REACH,
    noteFreq, centsBetween, nearestString, lowpassTaps,
    createDetector, interpret, hear, createGate, createTracker, turn, median,
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = GT_PITCH;
