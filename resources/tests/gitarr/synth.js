/* Plucked guitar strings made in the test, for gitarr.html's tests.

   pluck() adds up the partials of a string plucked at `p` of its length
   (amplitude |sin(nπp)|/n, the upper ones dying away faster), each partial
   stretched by the stiffness B as a real string's are, with the click of
   the pick at the start. Options imitate a phone's microphone (`hp`: a
   two-pole high-pass, which takes most of the low E's fundamental),
   background noise, and an explicit list of partial `weights`.

   The same file runs in Node (require) and in the page under test (the
   UI test evaluates it, and it sets window.GT_SYNTH). */

(function (root) {
  'use strict';

  function rng(seed) {
    let s = (seed >>> 0) || 1;
    return () => {
      s ^= s << 13; s >>>= 0;
      s ^= s >> 17;
      s ^= s << 5; s >>>= 0;
      return s / 4294967296;
    };
  }

  function gauss(r) {
    let u = 0;
    while (u === 0) u = r();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r());
  }

  /* RBJ two-pole high-pass, in place. */
  function highpass(x, sr, fc, q) {
    const w = 2 * Math.PI * fc / sr, cs = Math.cos(w), al = Math.sin(w) / (2 * (q || Math.SQRT1_2));
    const b0 = (1 + cs) / 2, b1 = -(1 + cs), b2 = (1 + cs) / 2, a0 = 1 + al, a1 = -2 * cs, a2 = 1 - al;
    let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
    for (let i = 0; i < x.length; i++) {
      const x0 = x[i];
      const y0 = (b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2) / a0;
      x2 = x1; x1 = x0; y2 = y1; y1 = y0;
      x[i] = y0;
    }
    return x;
  }

  function pluck(o) {
    const sr = o.sr || 48000, dur = o.dur || 1.5, f0 = o.f0;
    const B = o.B || 0, p = o.p || 0.2, tau1 = o.tau1 || 2.0, amp = o.amp || 0.3;
    const r = rng(o.seed || 1);
    const n = Math.round(dur * sr);
    const start = Math.round((o.start || 0) * sr);
    const x = new Float64Array(n);
    const parts = [];
    for (let k = 1; k <= 40; k++) {
      const fk = k * f0 * Math.sqrt(1 + B * k * k);
      if (fk > 0.45 * sr || fk > 8000) break;
      const a = o.weights ? (o.weights[k - 1] || 0) : Math.abs(Math.sin(k * Math.PI * p)) / k;
      if (a) parts.push({ w: 2 * Math.PI * fk / sr, a, decay: sr * tau1 / (1 + 0.3 * (k - 1)), ph: 2 * Math.PI * r() });
    }
    for (let i = start; i < n; i++) {
      const t = i - start;
      let v = 0;
      for (const q of parts) v += q.a * Math.exp(-t / q.decay) * Math.sin(q.ph + q.w * t);
      x[i] = v;
    }
    const click = o.attack === undefined ? 0.5 : o.attack;
    for (let i = start; i < Math.min(n, start + Math.round(0.03 * sr)); i++) {
      x[i] += click * 0.3 * gauss(r) * Math.exp(-(i - start) / (0.005 * sr));
    }
    let peak = 0;
    for (let i = 0; i < n; i++) peak = Math.max(peak, Math.abs(x[i]));
    if (peak > 0) for (let i = 0; i < n; i++) x[i] *= amp / peak;
    if (o.hp) { highpass(x, sr, o.hp); highpass(x, sr, o.hp); }
    if (o.noise) for (let i = 0; i < n; i++) x[i] += o.noise * gauss(r);
    return Float32Array.from(x);
  }

  /* Several signals added, each from its own start (seconds). */
  function mix(sr, dur, parts) {
    const out = new Float32Array(Math.round(dur * sr));
    for (const { x, at } of parts) {
      const s0 = Math.round((at || 0) * sr);
      for (let i = 0; i < x.length && s0 + i < out.length; i++) out[s0 + i] += x[i];
    }
    return out;
  }

  function noise(sr, dur, level, seed) {
    const r = rng(seed || 9);
    const out = new Float32Array(Math.round(dur * sr));
    for (let i = 0; i < out.length; i++) out[i] = level * gauss(r);
    return out;
  }

  /* 16-bit PCM mono WAV bytes, for Chrome's fake microphone. */
  function wav(x, sr) {
    const n = x.length, buf = new ArrayBuffer(44 + 2 * n), v = new DataView(buf);
    const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    str(0, 'RIFF'); v.setUint32(4, 36 + 2 * n, true); str(8, 'WAVE');
    str(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, sr, true); v.setUint32(28, 2 * sr, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    str(36, 'data'); v.setUint32(40, 2 * n, true);
    for (let i = 0; i < n; i++) v.setInt16(44 + 2 * i, Math.max(-32767, Math.min(32767, Math.round(x[i] * 32767))), true);
    return new Uint8Array(buf);
  }

  const api = { pluck, mix, noise, highpass, rng, gauss, wav };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.GT_SYNTH = api;
})(typeof window !== 'undefined' ? window : this);
