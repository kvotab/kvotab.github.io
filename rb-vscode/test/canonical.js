/* Answers as JSON that can be compared: typed arrays named with their type,
   and every number JSON cannot hold spelled out. Used on both sides of
   test/test-reader.py, in Node and in the page. */
(function (root) {
  'use strict';

  function num(v) {
    if (Number.isNaN(v)) return 'NaN';
    if (v === Infinity) return 'Infinity';
    if (v === -Infinity) return '-Infinity';
    if (v === 0 && 1 / v < 0) return '-0';
    return v;
  }

  function canonical(v) {
    if (typeof v === 'number') return num(v);
    if (typeof v === 'bigint') return { bigint: v.toString() };
    if (v === undefined) return { undefined: true };
    if (v === null || typeof v !== 'object') return v;
    if (ArrayBuffer.isView(v)) {
      return { typed: v.constructor.name, data: Array.from(v, x => (typeof x === 'bigint' ? x.toString() : num(x))) };
    }
    if (v instanceof ArrayBuffer) return { buffer: Array.from(new Uint8Array(v)) };
    if (Array.isArray(v)) return v.map(canonical);
    const out = {};
    for (const k of Object.keys(v).sort()) out[k] = canonical(v[k]);
    return out;
  }

  if (typeof module === 'object' && module.exports) module.exports = canonical;
  else root.canonicalAnswer = canonical;
})(typeof self !== 'undefined' ? self : this);
