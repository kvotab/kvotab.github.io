/* ==========================================================================
   distributions.html: RANDOM NUMBERS

   xoshiro128** (Blackman and Vigna 2021), seeded through splitmix32 so that
   any integer seed gives a well-mixed state. Doubles take 53 bits from two
   outputs and never equal 0 or 1, since an inverse-transform draw at either
   end would be infinite for an unbounded distribution.
   ========================================================================== */

function splitmix32(a) {
  return () => {
    a = (a + 0x9e3779b9) | 0;
    let t = a ^ (a >>> 16);
    t = Math.imul(t, 0x21f0aaad);
    t ^= t >>> 15;
    t = Math.imul(t, 0x735a2d97);
    t ^= t >>> 15;
    return t >>> 0;
  };
}

/**
 * A generator of doubles uniform on (0, 1) from an integer seed.
 *
 * @param {number} seed
 * @returns {function(): number}
 */
export function makeRng(seed) {
  const mix = splitmix32(Math.trunc(Number(seed) || 0) >>> 0);
  let s0 = mix(); let s1 = mix(); let s2 = mix(); let s3 = mix();
  if (!(s0 | s1 | s2 | s3)) s0 = 1;
  const next = () => {
    const result = Math.imul(rotl(Math.imul(s1, 5), 7), 9) >>> 0;
    const t = s1 << 9;
    s2 ^= s0; s3 ^= s1; s1 ^= s2; s0 ^= s3;
    s2 ^= t;
    s3 = rotl(s3, 11);
    return result;
  };
  return () => {
    for (;;) {
      const hi = next() >>> 5;   // 27 bits
      const lo = next() >>> 6;   // 26 bits
      const u = (hi * 67108864 + lo) / 9007199254740992;
      if (u > 0) return u;
    }
  };
}

function rotl(x, k) { return (x << k) | (x >>> (32 - k)); }

/** A distribution's stream: the run's seed and its letter, mixed. */
export function streamSeed(seed, letter) {
  let h = (Math.trunc(Number(seed) || 0) ^ 0x9e3779b9) >>> 0;
  for (const ch of String(letter)) h = Math.imul(h ^ ch.charCodeAt(0), 0x85ebca6b) >>> 0;
  return h ^ (h >>> 13);
}
