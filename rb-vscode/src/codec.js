/* ==========================================================================
   VALUES ACROSS VS CODE'S WEBVIEW CHANNEL

   What the extension host posts to a webview goes through JSON, with typed
   arrays and ArrayBuffers carried alongside it (VS Code 1.57 and later). The
   JSON part loses what HDF5 attributes are full of: NaN and Infinity arrive
   as null, undefined disappears, and a BigInt -- h5wasm's value for a 64-bit
   integer scalar -- makes the post throw. Measured in VS Code 1.135.

   encode() turns those into small tagged objects and decode() turns them
   back. Typed arrays are left for VS Code to carry, which keeps their type,
   BigInt64Array included; one that is a window onto part of a larger buffer
   is copied first, because VS Code sends the whole buffer under it.

   Loaded by the extension host (require) and by the webview (a <script>).
   ========================================================================== */

(function (root) {
  'use strict';

  const TAG = '__kvot__';

  function isPlainObject(v) {
    if (v === null || typeof v !== 'object') return false;
    const proto = Object.getPrototypeOf(v);
    return proto === Object.prototype || proto === null;
  }

  function compact(view) {
    return view.byteOffset === 0 && view.byteLength === view.buffer.byteLength ? view : view.slice();
  }

  function encode(v) {
    switch (typeof v) {
      case 'number':
        if (Number.isNaN(v)) return { [TAG]: 'NaN' };
        if (v === Infinity) return { [TAG]: 'Inf' };
        if (v === -Infinity) return { [TAG]: '-Inf' };
        if (v === 0 && 1 / v < 0) return { [TAG]: '-0' };
        return v;
      case 'bigint':
        return { [TAG]: 'big', v: v.toString() };
      case 'undefined':
        return { [TAG]: 'undef' };
      case 'object':
        if (v === null) return null;
        if (ArrayBuffer.isView(v)) return v instanceof DataView ? { [TAG]: 'bytes', v: new Uint8Array(v.buffer.slice(v.byteOffset, v.byteOffset + v.byteLength)) } : compact(v);
        if (v instanceof ArrayBuffer) return v;
        if (Array.isArray(v)) return v.map(encode);
        if (isPlainObject(v)) {
          const out = {};
          for (const k of Object.keys(v)) out[k] = encode(v[k]);
          // An object of the file's own that happens to use the tag is wrapped, so it comes back as it went.
          return Object.prototype.hasOwnProperty.call(v, TAG) ? { [TAG]: 'obj', v: out } : out;
        }
        return String(v);
      default:
        return v;
    }
  }

  function decode(v) {
    if (v === null || typeof v !== 'object') return v;
    if (ArrayBuffer.isView(v) || v instanceof ArrayBuffer) return v;
    if (Array.isArray(v)) return v.map(decode);
    if (Object.prototype.hasOwnProperty.call(v, TAG)) {
      switch (v[TAG]) {
        case 'NaN': return NaN;
        case 'Inf': return Infinity;
        case '-Inf': return -Infinity;
        case '-0': return -0;
        case 'big': return BigInt(v.v);
        case 'undef': return undefined;
        case 'bytes': return new DataView(v.v.buffer, v.v.byteOffset, v.v.byteLength);
        case 'obj': {
          const out = {};
          for (const k of Object.keys(v.v)) out[k] = decode(v.v[k]);
          return out;
        }
        default: break;
      }
    }
    const out = {};
    for (const k of Object.keys(v)) out[k] = decode(v[k]);
    return out;
  }

  const api = Object.freeze({ encode, decode });
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.KvotVscodeCodec = api;
})(typeof self !== 'undefined' ? self : this);
