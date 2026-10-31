/* ==========================================================================
   4d. MATLAB MAT-FILES (.mat)

   A MAT-file keeps a MATLAB workspace: named variables, each an array of some
   class. MATLAB has written three formats under the one extension:

       Level 4  (save -v4)     2-D double, char and sparse matrices, each with
                               a 20-byte header of its own and no file header
       Level 5  (-v6 and -v7)  a 128-byte header, then an element per
                               variable; -v7, MATLAB's default, deflates each
       7.3      (-v7.3)        an HDF5 file behind a 512-byte header, laid out
                               by MATLAB's own conventions

   Each opens as an HDF5 file of its own, written here, in memory, with
   h5wasm, as an Ecolego run is (rb-eas.js), and then registered like any file
   read from disk. So a MAT-file is browsed as an HDF5 file is: the tree, a
   dataset's values and attributes, the CSV and Excel downloads, two files
   compared in one tree.

   Every format is first read into one form, an array per variable as MATLAB
   holds it (see matParseMatrix), and that is what is written. A variable
   becomes

       numeric, logical    a dataset in MATLAB's own shape: a 1000×3 double is
                           1000 rows of 3. MATLAB keeps an array a column at a
                           time; the values are put in row order here, as HDF5
                           reads them
       complex             a dataset of (real, imag) pairs
       char                a string for each row
       cell                a group of its elements, {1}, {2}, ..., or {1,2} for
                           a matrix; a cell whose elements are each a number,
                           a row of text or empty -- a table, as from a
                           spreadsheet -- is one dataset of them (matTable)
       struct              a group of its fields. In a struct array, a field
                           is likewise one dataset when each element holds a
                           number, text or nothing in it, as [s.x] gathers
                           it; any other is a group of (1), (2), ...
       sparse              a dataset with its zeros, or its row, column and
                           value when it is too large to hold them
       function handle     its text, @(x)x.^2+1
       string              a dataset of strings
       table               a group of its variables, by name
       other objects       a group of the properties MATLAB saved

   and carries MATLAB_class and MATLAB_size, as MATLAB names them: a dataset of
   strings has no shape that says 1×5 char.

   MATLAB keeps objects (string, table, datetime, ...) apart from the
   variables, in a block of the file its documentation does not describe. The
   reading of that block here follows its layout as MATLAB R2023a wrote it, and
   as earlier releases did in files checked against MATLAB's own reading.
   ========================================================================== */

'use strict';   // see the script manifest in rb.html for why

/* Level 5's data types, by the numbers the format gives them. */
const MAT_MI = Object.freeze({
  INT8: 1, UINT8: 2, INT16: 3, UINT16: 4, INT32: 5, UINT32: 6, SINGLE: 7, DOUBLE: 9,
  INT64: 12, UINT64: 13, MATRIX: 14, COMPRESSED: 15, UTF8: 16, UTF16: 17, UTF32: 18
});

/* The typed array each data type is read into. */
const MAT_MI_ARRAYS = new Map([
  [1, Int8Array], [2, Uint8Array], [3, Int16Array], [4, Uint16Array], [5, Int32Array],
  [6, Uint32Array], [7, Float32Array], [9, Float64Array], [12, BigInt64Array], [13, BigUint64Array],
  [16, Uint8Array], [17, Uint16Array], [18, Uint32Array]
]);

/* How a DataView reads each, for a file in the other byte order. */
const MAT_GETTERS = new Map([
  [Int8Array, 'getInt8'], [Uint8Array, 'getUint8'], [Int16Array, 'getInt16'], [Uint16Array, 'getUint16'],
  [Int32Array, 'getInt32'], [Uint32Array, 'getUint32'], [Float32Array, 'getFloat32'],
  [Float64Array, 'getFloat64'], [BigInt64Array, 'getBigInt64'], [BigUint64Array, 'getBigUint64']
]);

/* MATLAB's classes, by the numbers Level 5 gives them. */
const MAT_CLASSES = [null, 'cell', 'struct', 'object', 'char', 'sparse', 'double', 'single', 'int8',
  'uint8', 'int16', 'uint16', 'int32', 'uint32', 'int64', 'uint64', 'function_handle', 'opaque'];

/* Each numeric class: the typed array it is held in, and the HDF5 type written. */
const MAT_NUMERIC = Object.freeze({
  double: [Float64Array, '<d'], single: [Float32Array, '<f'],
  int8: [Int8Array, '<b'], uint8: [Uint8Array, '<B'], int16: [Int16Array, '<h'], uint16: [Uint16Array, '<H'],
  int32: [Int32Array, '<i'], uint32: [Uint32Array, '<I'], int64: [BigInt64Array, '<q'], uint64: [BigUint64Array, '<Q'],
  logical: [Uint8Array, '<B']
});

/* The class of a dataset in a 7.3 file that does not name one, by its type. */
const MAT_CLASS_OF_DTYPE = Object.freeze({
  '<d': 'double', '<f': 'single', '<b': 'int8', '<B': 'uint8', '<h': 'int16', '<H': 'uint16',
  '<i': 'int32', '<I': 'uint32', '<q': 'int64', '<Q': 'uint64'
});

/* MATLAB's mark at the head of a reference to an object it keeps apart. */
const MAT_OBJECT_MARK = 0xDD000000;

/* How far a file may take the page. */
const MAT_MAX_DEPTH = 64;          // arrays within arrays
const MAT_MAX_ARRAYS = 200000;     // datasets and groups written for one file
const MAT_FULL_SPARSE = 1 << 20;   // elements a sparse matrix may have and be shown with its zeros

/* Typed arrays over the file's bytes can be used as they are when both agree. */
const MAT_HOST_LITTLE = new Uint8Array(new Uint16Array([1]).buffer)[0] === 1;

/**
 * Whether bytes handed over are a MATLAB MAT-file.
 *
 * By name, or for bytes that arrive under another name -- a link that does
 * not end in .mat, a handoff named .h5 -- by the text MATLAB writes at the
 * head of a Level 5 or 7.3 file. A Level 4 file has none, so it is known by
 * its name alone.
 *
 * @param {string} fileName
 * @param {ArrayBuffer|null} buffer - null to decide by the name alone
 * @returns {boolean}
 */
function isMatFile(fileName, buffer) {
  if (/\.mat$/i.test(String(fileName || ''))) return true;
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 128) return false;
  return /^MATLAB (5\.0|7\.3) MAT-file/.test(matLatin1(new Uint8Array(buffer, 0, 19)));
}

/* ── small helpers ───────────────────────────────────────────────────── */

function matLatin1(bytes) {
  let s = '';
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return s;
}

/** A name as a file gives it: ASCII up to its first NUL. */
function matName(bytes) {
  const end = bytes.indexOf(0);
  return matLatin1(end < 0 ? bytes : bytes.subarray(0, end));
}

/**
 * Text from UTF-16 code units. A NUL is shown as ␀: HDF5 keeps a string only
 * up to its first.
 */
function matString(units, from = 0, to = units.length) {
  let s = '';
  for (let i = from; i < to; i += 8192) {
    s += String.fromCharCode.apply(null, units.subarray(i, Math.min(to, i + 8192)));
  }
  return s.indexOf('\u0000') < 0 ? s : s.replace(/\u0000/g, '␀');
}

function matUnits(text) {
  const out = new Uint16Array(text.length);
  for (let i = 0; i < text.length; i++) out[i] = text.charCodeAt(i);
  return out;
}

function matNumel(dims) {
  let n = 1;
  for (const d of dims) n *= d;
  return n;
}

/** How MATLAB writes a size: 1000×3. */
function matSizeText(dims) {
  return dims.join('×');
}

/** Why a file cannot be read, as an error whose message says so. */
function matDamaged(why) {
  return new Error(why);
}

/**
 * The values of an array put in row order. MATLAB keeps the first index
 * fastest; HDF5, and so this page, the last. A vector is the same either way.
 *
 * @param {TypedArray|Array} src - In MATLAB's order
 * @param {number[]} dims
 * @returns {TypedArray|Array} In row order, of the same kind
 */
function matRowMajor(src, dims) {
  const n = src.length;
  if (n < 2 || dims.filter(d => d !== 1).length <= 1) return src;
  const out = new src.constructor(n);
  if (dims.length === 2) {
    const [m, k] = dims;
    for (let j = 0; j < k; j++) {
      for (let i = 0; i < m; i++) out[i * k + j] = src[i + j * m];
    }
    return out;
  }
  // The source walked in MATLAB's order, each index kept, its place in row
  // order carried along.
  const nd = dims.length;
  const stride = new Array(nd);
  stride[nd - 1] = 1;
  for (let d = nd - 2; d >= 0; d--) stride[d] = stride[d + 1] * dims[d + 1];
  const index = new Array(nd).fill(0);
  let at = 0;
  for (let s = 0; s < n; s++) {
    out[at] = src[s];
    for (let d = 0; d < nd; d++) {
      index[d]++;
      at += stride[d];
      if (index[d] < dims[d]) break;
      at -= stride[d] * dims[d];
      index[d] = 0;
    }
  }
  return out;
}

/**
 * Values held in a class's typed array: a double MATLAB stored as small
 * integers, say, back as doubles.
 */
function matAsClass(values, cls) {
  const A = (MAT_NUMERIC[cls] || MAT_NUMERIC.double)[0];
  if (values instanceof A) return values;
  const n = values.length;
  const out = new A(n);
  const big = A === BigInt64Array || A === BigUint64Array;
  for (let i = 0; i < n; i++) {
    const v = values[i];
    if (big) out[i] = typeof v === 'bigint' ? v : (Number.isFinite(v) ? BigInt(Math.trunc(v)) : 0n);
    else if (cls === 'logical') out[i] = v ? 1 : 0;
    else out[i] = typeof v === 'bigint' ? Number(v) : v;
  }
  return out;
}

/**
 * The names of an array's elements, in MATLAB's order: {1}, {2}, ... for a
 * vector, {1,2} for a matrix. Numbers are padded to one width, since the tree
 * sorts names as text and {10} would come before {2}.
 */
function matIndexNames(dims, open, close) {
  const n = matNumel(dims);
  if (dims.filter(d => d !== 1).length <= 1) {
    const width = String(n).length;
    return Array.from({ length: n }, (_, k) => `${open}${String(k + 1).padStart(width, '0')}${close}`);
  }
  const widths = dims.map(d => String(d).length);
  return Array.from({ length: n }, (_, k) => {
    let rest = k;
    const subs = dims.map((d, i) => {
      const s = rest % d;
      rest = Math.floor(rest / d);
      return String(s + 1).padStart(widths[i], '0');
    });
    return `${open}${subs.join(',')}${close}`;
  });
}

/* ── Level 5 ─────────────────────────────────────────────────────────── */

function matReader(bytes, little) {
  return { bytes, little, view: new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength) };
}

/**
 * The element whose tag is at `at`: its type, the size of its data, where the
 * data begins and where the next element does. A tag whose first word has
 * bits in its upper half is the short form: the size there, the data in the
 * four bytes after it.
 */
function matTag(r, at, end) {
  if (at + 8 > end) throw matDamaged('an element runs past the end of the array that holds it');
  const word = r.view.getUint32(at, r.little);
  if (word >>> 16) {
    const size = word >>> 16;
    if (size > 4) throw matDamaged('an element is longer than its tag allows');
    return { type: word & 0xffff, size, data: at + 4, next: at + 8 };
  }
  const size = r.view.getUint32(at + 4, r.little);
  const data = at + 8;
  if (size > end - data) throw matDamaged('an element runs past the end of the array that holds it');
  return { type: word, size, data, next: Math.min(end, data + Math.ceil(size / 8) * 8) };
}

/** An element's values, in the typed array of its data type. */
function matValues(r, tag) {
  const A = MAT_MI_ARRAYS.get(tag.type);
  if (!A) throw matDamaged(`an element holds data of a type MAT-files do not have (${tag.type})`);
  const width = A.BYTES_PER_ELEMENT;
  if (tag.size % width) throw matDamaged('an element\'s data does not divide into whole values');
  if (r.little === MAT_HOST_LITTLE) return new A(r.bytes.slice(tag.data, tag.data + tag.size).buffer);
  const n = tag.size / width;
  const out = new A(n);
  const get = MAT_GETTERS.get(A);
  for (let i = 0; i < n; i++) out[i] = r.view[get](tag.data + i * width, r.little);
  return out;
}

function matText(r, tag) {
  return matName(r.bytes.subarray(tag.data, tag.data + tag.size));
}

/**
 * The code units of a char array, in whichever of its encodings it was
 * written: MATLAB writes UTF-8 for ASCII text and UTF-16 for any other.
 */
function matChars(r, tag, numel, oneRow) {
  let units;
  if (tag.type === MAT_MI.UTF8) {
    units = matUnits(new TextDecoder('utf-8').decode(r.bytes.subarray(tag.data, tag.data + tag.size)));
  } else if (tag.type === MAT_MI.UTF32) {
    let text = '';
    for (const cp of matValues(r, tag)) text += cp <= 0x10ffff ? String.fromCodePoint(cp) : '�';
    units = matUnits(text);
  } else {
    const v = matValues(r, tag);
    units = v instanceof Uint16Array ? v : Uint16Array.from(v, x => Number(x) & 0xffff);
  }
  if (units.length !== numel && !oneRow) {
    throw matDamaged(`a char array has ${units.length} characters where its size says ${numel}`);
  }
  return units;
}

/** An array's size: at least two dimensions, as MATLAB has them. */
function matDims(values) {
  const dims = Array.from(values, Number);
  if (dims.some(d => !Number.isInteger(d) || d < 0)) throw matDamaged('an array has a size below zero');
  while (dims.length < 2) dims.push(1);
  return dims;
}

/**
 * One array, from the contents of its miMATRIX element, in the form every
 * format is read into:
 *
 *   numeric, logical   {cls, dims, re, im}   values in MATLAB's order
 *   char               {cls, dims, units}    UTF-16 code units, likewise
 *   sparse             {cls, dims, logical, ir, jc, re, im}
 *   cell               {cls, dims, items}
 *   struct, object     {cls, dims, fields, items, className}  items[element][field]
 *   function_handle    {cls, dims, inner}    the struct MATLAB describes it by
 *   opaque             {cls, typeSystem, className, data}
 *
 * each with its `name` and `global`.
 *
 * @param {Object} r - matReader over the bytes
 * @param {number} at - Where the element's contents begin
 * @param {number} end - Where they end
 * @param {number} depth - How deep in other arrays this one is
 */
function matParseMatrix(r, at, end, depth) {
  if (at === end) return { cls: 'double', name: '', dims: [0, 0], re: new Float64Array(0), im: null };
  if (depth > MAT_MAX_DEPTH) throw matDamaged(`its arrays are nested more than ${MAT_MAX_DEPTH} deep`);
  let p = at;
  const next = () => {
    const tag = matTag(r, p, end);
    p = tag.next;
    return tag;
  };
  const flagsTag = next();
  if (flagsTag.type !== MAT_MI.UINT32 || flagsTag.size < 8) throw matDamaged('an array has no array flags');
  const flags = r.view.getUint32(flagsTag.data, r.little);
  const cls = MAT_CLASSES[flags & 0xff] || null;
  const complex = !!(flags & 0x800);
  const global = !!(flags & 0x400);
  const logical = !!(flags & 0x200);
  const matrix = (tag) => {
    if (tag.type !== MAT_MI.MATRIX) throw matDamaged('an array holds something other than arrays where arrays belong');
    return matParseMatrix(r, tag.data, tag.data + tag.size, depth + 1);
  };

  // An object kept apart has no size here: its name, the system that keeps it
  // and its class, then the reference to it.
  if (cls === 'opaque') {
    const name = matText(r, next());
    const typeSystem = matText(r, next());
    const className = matText(r, next());
    return { cls, name, global, dims: [1, 1], typeSystem, className, data: matrix(next()) };
  }

  const dims = matDims(matValues(r, next()));
  const name = matText(r, next());
  const numel = matNumel(dims);
  // Each element of a cell or struct is an element of the file, eight bytes
  // at the least: a size the file cannot hold is refused before it is used.
  const fits = (count) => {
    if (count * 8 > end - p) throw matDamaged(`${name ? `the array ${name}` : 'an array'} says it holds more than its bytes can`);
  };
  try {
    if (cls && MAT_NUMERIC[cls]) {
      const kind = logical ? 'logical' : cls;
      const re = matAsClass(matValues(r, next()), kind);
      const im = complex ? matAsClass(matValues(r, next()), kind) : null;
      if (re.length !== numel || (im && im.length !== numel)) {
        throw matDamaged(`it holds ${re.length} values where its size says ${numel}`);
      }
      return { cls: kind, name, global, dims, re, im };
    }
    switch (cls) {
      case 'char': {
        const units = p < end ? matChars(r, next(), numel, dims[0] === 1 && dims.length === 2) : new Uint16Array(0);
        if (units.length !== numel) dims[1] = units.length;
        return { cls, name, global, dims, units };
      }
      case 'sparse': {
        if (dims.length !== 2) throw matDamaged('a sparse array has more than two dimensions');
        const ir = Int32Array.from(matValues(r, next()), Number);
        const jc = Int32Array.from(matValues(r, next()), Number);
        if (jc.length < dims[1] + 1) throw matDamaged('a sparse array has fewer column starts than columns');
        const nnz = jc[dims[1]];
        const kind = logical ? 'logical' : 'double';
        const re = p < end ? matAsClass(matValues(r, next()), kind) : matAsClass(new Uint8Array(nnz).fill(1), kind);
        const im = complex ? matAsClass(matValues(r, next()), kind) : null;
        if (!(nnz >= 0 && nnz <= ir.length && nnz <= re.length && (!im || nnz <= im.length))) {
          throw matDamaged('a sparse array says it holds more values than it does');
        }
        return { cls, name, global, dims, logical, ir, jc, re, im };
      }
      case 'cell': {
        fits(numel);
        const items = [];
        for (let k = 0; k < numel; k++) items.push(matrix(next()));
        return { cls, name, global, dims, items };
      }
      case 'struct':
      case 'object': {
        const className = cls === 'object' ? matText(r, next()) : null;
        const lengthTag = next();
        const width = lengthTag.size >= 4 ? r.view.getInt32(lengthTag.data, r.little) : 0;
        const namesTag = next();
        const fields = [];
        if (namesTag.size) {
          if (!(width > 0) || namesTag.size % width) throw matDamaged('a struct\'s field names do not fit its name length');
          for (let o = 0; o < namesTag.size; o += width) {
            fields.push(matName(r.bytes.subarray(namesTag.data + o, namesTag.data + o + width)));
          }
        }
        fits(numel * fields.length);
        const items = [];
        for (let k = 0; k < numel; k++) items.push(fields.map(() => matrix(next())));
        return { cls: 'struct', className, name, global, dims, fields, items };
      }
      case 'function_handle':
        return { cls, name, global, dims, inner: matrix(next()) };
      default:
        return { cls: 'unknown', code: flags & 0xff, name, global, dims };
    }
  } catch (err) {
    // Named by the variable it is in: arrays inside another have no name.
    if (err && !err.matName && name) err.matName = name;
    throw err;
  }
}

/**
 * Data compressed with zlib, unpacked. A file's variables may unpack to no
 * more than the page reads of a file in all: a small file that would unpack
 * to more is refused, not unpacked.
 *
 * @param {Uint8Array} packed
 * @param {{left: number}} budget - Bytes the file may still unpack to
 * @returns {Promise<Uint8Array>}
 */
async function matInflate(packed, budget) {
  const reader = new Blob([packed]).stream().pipeThrough(new DecompressionStream('deflate')).getReader();
  const chunks = [];
  let total = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > budget.left) {
        throw matDamaged(`its variables unpack to more than ${kvotFormatBytes(KVOT_FILE_SIZE_LIMITS.dataset)}, more than this page reads`);
      }
      chunks.push(value);
    }
  } catch (err) {
    reader.cancel().catch(() => {});
    if (err instanceof TypeError) throw matDamaged('a compressed variable is damaged');
    throw err;
  }
  budget.left -= total;
  if (chunks.length === 1) return chunks[0];
  const out = new Uint8Array(total);
  let at = 0;
  for (const c of chunks) {
    out.set(c, at);
    at += c.byteLength;
  }
  return out;
}

/**
 * Where a Level 5 file's subsystem is: the element that holds the objects it
 * keeps apart, which is no variable of the file's own. Null when it has none.
 */
function matSubsystemOffset(bytes, little) {
  const head = bytes.subarray(116, 124);
  if (head.every(b => b === 0) || head.every(b => b === 0x20)) return null;
  const at = Number(new DataView(bytes.buffer, bytes.byteOffset + 116, 8).getBigUint64(0, little));
  return at >= 128 && at < bytes.length ? at : null;
}

/**
 * The top-level elements of a Level 5 stream, read one at a time: a variable
 * that cannot be read is reported with its name, if it got that far, and the
 * ones after it are still read.
 *
 * @returns {Promise<{arrays: Array<{at: number, array?: Object, name?: string, error?: string}>, compressed: boolean}>}
 */
async function matElements(bytes, start, little, budget) {
  const r = matReader(bytes, little);
  const arrays = [];
  let compressed = false;
  for (let at = start; at + 8 <= bytes.length;) {
    let tag;
    try {
      tag = matTag(r, at, bytes.length);
    } catch (err) {
      arrays.push({ at, name: null, error: 'the file ends part of the way through a variable' });
      break;
    }
    const here = at;
    at = tag.data + tag.size;
    try {
      if (tag.type === MAT_MI.COMPRESSED) {
        compressed = true;
        const inner = await matInflate(bytes.subarray(tag.data, tag.data + tag.size), budget);
        const ir = matReader(inner, little);
        const t = matTag(ir, 0, inner.length);
        if (t.type !== MAT_MI.MATRIX) continue;
        arrays.push({ at: here, array: matParseMatrix(ir, t.data, t.data + t.size, 0) });
      } else if (tag.type === MAT_MI.MATRIX) {
        arrays.push({ at: here, array: matParseMatrix(r, tag.data, tag.data + tag.size, 0) });
      }
    } catch (err) {
      arrays.push({ at: here, name: err && err.matName ? err.matName : null, error: err.message });
    }
  }
  return { arrays, compressed };
}

/**
 * A Level 5 file: its header line, its variables and the objects it keeps.
 *
 * @param {Uint8Array} bytes
 */
async function matReadLevel5(bytes) {
  // 'IM' as a 16-bit number in the file's own order: read the other way round
  // it says 'MI', and every number in the file is big-endian.
  const little = !(bytes[126] === 0x4d && bytes[127] === 0x49);
  const budget = { left: KVOT_FILE_SIZE_LIMITS.dataset };
  const { arrays, compressed } = await matElements(bytes, 128, little, budget);
  const subsystemAt = matSubsystemOffset(bytes, little);
  const variables = [];
  let objects = null;
  for (const a of arrays) {
    if (a.at === subsystemAt) {
      objects = a.array ? await matSubsystem(a.array, budget) : { error: a.error };
      continue;
    }
    variables.push(a.array ? { name: a.array.name, array: a.array } : { name: a.name, error: a.error });
  }
  const header = matLatin1(bytes.subarray(0, 116)).replace(/[\s\u0000]+$/, '');
  return { format: compressed ? 'Level 5, compressed (-v7)' : 'Level 5 (-v6)', header, variables, objects };
}

/**
 * The objects a Level 5 file keeps apart, from its subsystem: a uint8 array
 * that is itself a stream of elements behind a header of eight bytes. Its
 * first element is a struct whose field MCOS holds the objects. An object
 * that cannot be read is left out with the reason, and the file still opens.
 */
async function matSubsystem(array, budget) {
  try {
    if (!(array.re instanceof Uint8Array) || array.re.length < 16) throw matDamaged('its objects are kept in a form this page does not read');
    const bytes = array.re;
    const little = !(bytes[2] === 0x4d && bytes[3] === 0x49);
    const { arrays } = await matElements(bytes, 8, little, budget);
    const first = arrays[0] && arrays[0].array;
    if (!first || first.cls !== 'struct' || !first.items.length) throw matDamaged('its objects are kept in a form this page does not read');
    const field = first.fields.indexOf('MCOS');
    const wrapper = field >= 0 ? first.items[0][field] : null;
    if (!wrapper || wrapper.cls !== 'opaque' || !wrapper.data || wrapper.data.cls !== 'cell') {
      throw matDamaged('its objects are kept in a form this page does not read');
    }
    return matObjects(wrapper.data.items);
  } catch (err) {
    return { error: err.message };
  }
}

/* ── Level 4 ─────────────────────────────────────────────────────────── */

/* A Level 4 header's type, MOPT: machine, 0, precision, matrix type. */
function matLevel4Type(t) {
  return Number.isInteger(t) && t >= 0 && t < 5000 && Math.floor(t / 100) % 10 === 0
    && Math.floor(t / 10) % 10 <= 5 && t % 10 <= 2;
}

/**
 * A Level 4 file: each variable a header of five numbers -- type, rows,
 * columns, whether imaginary parts follow, the name's length -- its name, and
 * its values a column at a time. No header says the file is one: the first
 * variable's header has to make sense or the file is refused.
 *
 * @param {Uint8Array} bytes
 */
function matReadLevel4(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  // The data type of each precision the header can give.
  const precisions = [MAT_MI.DOUBLE, MAT_MI.SINGLE, MAT_MI.INT32, MAT_MI.INT16, MAT_MI.UINT16, MAT_MI.UINT8];
  const variables = [];
  let at = 0;
  while (at < bytes.length) {
    if (bytes.length - at < 20) {
      if (bytes.subarray(at).every(b => b === 0)) break;
      throw matDamaged('it ends part of the way through a variable');
    }
    let little = true;
    let type = view.getInt32(at, true);
    if (!matLevel4Type(type) || Math.floor(type / 1000) !== 0) {
      little = false;
      type = view.getInt32(at, false);
      if (!matLevel4Type(type) || Math.floor(type / 1000) !== 1) {
        throw matDamaged(variables.length ? 'a variable after the first has a header that makes no sense'
          : 'it is not a MAT-file this page can read: it starts with none of the headers MATLAB writes');
      }
    }
    const [rows, cols, imagf, nameLength] = [4, 8, 12, 16].map(o => view.getInt32(at + o, little));
    if (rows < 0 || cols < 0 || (imagf !== 0 && imagf !== 1) || nameLength < 1 || nameLength > 4096) {
      throw matDamaged('a variable\'s header makes no sense');
    }
    const mi = precisions[Math.floor(type / 10) % 10];
    const n = rows * cols;
    const dataAt = at + 20 + nameLength;
    const size = n * MAT_MI_ARRAYS.get(mi).BYTES_PER_ELEMENT;
    const end = dataAt + size * (imagf ? 2 : 1);
    if (end > bytes.length) throw matDamaged('it ends part of the way through a variable');
    const name = matName(bytes.subarray(at + 20, dataAt));
    const r = matReader(bytes, little);
    const read = (from) => Float64Array.from(matValues(r, { type: mi, size, data: from }), Number);
    const re = read(dataAt);
    const im = imagf ? read(dataAt + size) : null;
    at = end;
    const kind = type % 10;
    if (kind === 1) {
      variables.push({ name, array: { cls: 'char', name, dims: [rows, cols], units: Uint16Array.from(re, x => x & 0xffff) } });
    } else if (kind === 2) {
      variables.push({ name, array: matLevel4Sparse(name, rows, cols, re, im) });
    } else {
      variables.push({ name, array: { cls: 'double', name, dims: [rows, cols], re, im } });
    }
  }
  return { format: 'Level 4 (-v4)', header: '', variables, objects: null };
}

/**
 * A Level 4 sparse matrix, from the full matrix it is written as: a row for
 * each value -- its row, its column, its value (and imaginary part) -- and a
 * last row that gives the size.
 */
function matLevel4Sparse(name, rows, cols, re, im) {
  if (rows < 1 || cols < 3) throw matDamaged(`the sparse matrix ${name} is written in a form this page does not read`);
  const nnz = rows - 1;
  const size = [re[nnz], re[rows + nnz]];
  if (!size.every(d => Number.isInteger(d) && d >= 0)) throw matDamaged(`the sparse matrix ${name} gives no size`);
  const entries = [];
  for (let k = 0; k < nnz; k++) {
    const i = re[k] - 1;
    const j = re[rows + k] - 1;
    if (!(Number.isInteger(i) && Number.isInteger(j) && i >= 0 && j >= 0 && i < size[0] && j < size[1])) {
      throw matDamaged(`the sparse matrix ${name} holds a value outside its size`);
    }
    entries.push([j, i, re[2 * rows + k], cols > 3 ? re[3 * rows + k] : (im ? im[2 * rows + k] : 0)]);
  }
  entries.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const jc = new Int32Array(size[1] + 1);
  for (const [j] of entries) jc[j + 1]++;
  for (let j = 0; j < size[1]; j++) jc[j + 1] += jc[j];
  const complex = cols > 3 || !!im;
  return {
    cls: 'sparse', name, dims: size, logical: false,
    ir: Int32Array.from(entries, e => e[1]), jc,
    re: Float64Array.from(entries, e => e[2]),
    im: complex ? Float64Array.from(entries, e => e[3]) : null
  };
}

/* ── 7.3 ─────────────────────────────────────────────────────────────── */

/**
 * A 7.3 file: an HDF5 file, opened with h5wasm, its variables read by
 * MATLAB's conventions into the form the other formats are read into.
 *
 *   A dataset's shape is MATLAB's size the other way round, its values in
 *   MATLAB's order; MATLAB_class names the class. A char array is uint16, a
 *   logical uint8, a complex array (real, imag) pairs, and an empty array a
 *   dataset holding its size, marked MATLAB_empty.
 *   A cell is a dataset of references to its elements, kept in /#refs#.
 *   A struct is a group of its fields; in a struct array each field is a
 *   dataset of references, one per element, and has no class of its own.
 *   A sparse matrix is a group of data, ir and jc, MATLAB_sparse its rows.
 *   An object kept apart is its reference, the objects in /#subsystem#/MCOS.
 *
 * @param {ArrayBuffer} buffer
 * @param {string} header - The file's header line
 */
async function matReadV73(buffer, header) {
  await waitForH5Wasm();
  const { FS, File } = window.h5wasm;
  const path = `/mat_${Date.now()}_${Math.random().toString(36).slice(2, 11)}.h5`;
  FS.writeFile(path, new Uint8Array(buffer));
  let f = null;
  try {
    f = new File(path, 'r');
    const variables = [];
    for (const key of Array.from(f.keys())) {
      if (key === '#refs#' || key === '#subsystem#') continue;
      try {
        const obj = f.get(key);
        const array = matFromHdf5(f, obj, key, 0);
        if (Number(matAttr(obj, 'MATLAB_global')) === 1) array.global = true;
        variables.push({ name: key, array });
      } catch (err) {
        variables.push({ name: key, error: err.message });
      }
    }
    let objects = null;
    let mcos = null;
    try { mcos = f.get('#subsystem#/MCOS'); } catch (_) { mcos = null; }
    if (mcos) {
      try {
        objects = matObjects(Array.from(mcos.value, ref => matFromHdf5(f, f.dereference(ref), '', 1)));
      } catch (err) {
        objects = { error: err.message };
      }
    }
    return { format: '7.3 (-v7.3, HDF5)', header, variables, objects };
  } finally {
    try { if (f) f.close(); } catch (e) { ignoreFailure('matReadV73', e); }
    try { FS.unlink(path); } catch (e) { ignoreFailure('matReadV73', e); }
  }
}

/** An attribute's value, or undefined when it has none or it cannot be read. */
function matAttr(obj, name) {
  try {
    const a = obj.attrs && obj.attrs[name];
    return a ? a.value : undefined;
  } catch (_) {
    return undefined;
  }
}

/** MATLAB_fields: a list of names, each written as a list of its characters. */
function matFieldsAttr(value) {
  if (!value || typeof value === 'string' || typeof value.length !== 'number') return null;
  const out = Array.from(value, f => (typeof f === 'string' ? f : Array.from(f || [], c => String(c)).join('')));
  return out.every(s => typeof s === 'string') ? out : null;
}

/** A 7.3 file's size of an array: its shape the other way round. */
function matReversed(shape) {
  return matDims((shape || []).slice().reverse());
}

/** One object of a 7.3 file as an array (see matParseMatrix). */
function matFromHdf5(f, obj, name, depth) {
  if (depth > MAT_MAX_DEPTH) throw matDamaged(`its arrays are nested more than ${MAT_MAX_DEPTH} deep`);
  if (!obj) throw matDamaged('a reference points at nothing');
  const cls = String(matAttr(obj, 'MATLAB_class') ?? '');
  const type = String(obj.type);
  const child = (o, n) => matFromHdf5(f, o, n, depth + 1);

  if (type === 'Group') {
    const sparse = matAttr(obj, 'MATLAB_sparse');
    if (sparse !== undefined) return matHdf5Sparse(obj, name, cls, Number(sparse));
    const fields = matFieldsAttr(matAttr(obj, 'MATLAB_fields')) || Array.from(obj.keys());
    const members = fields.map(k => { try { return obj.get(k); } catch (_) { return null; } });
    const struct = (items, dims) => ({ cls: 'struct', className: cls && cls !== 'struct' ? cls : null, name, dims, fields, items });
    if (cls === 'function_handle') {
      return { cls, name, dims: [1, 1], inner: struct([members.map((m, k) => child(m, fields[k]))], [1, 1]) };
    }
    // A struct array: every field a dataset of references with no class.
    const isArray = members.length > 0 && members.every(m => m && String(m.type) === 'Dataset'
      && m.dtype === 'Reference' && matAttr(m, 'MATLAB_class') === undefined);
    if (isArray) {
      const dims = matReversed(members[0].shape);
      const refs = members.map(m => Array.from(m.value));
      const numel = matNumel(dims);
      if (refs.some(list => list.length !== numel)) throw matDamaged('a struct array\'s fields differ in size');
      const items = [];
      for (let e = 0; e < numel; e++) items.push(refs.map((list, k) => child(f.dereference(list[e]), fields[k])));
      return struct(items, dims);
    }
    return struct([members.map((m, k) => child(m, fields[k]))], [1, 1]);
  }
  if (type !== 'Dataset') throw matDamaged(`${name || 'an array'} is an HDF5 ${type}, which is no MATLAB array`);

  if (Number(matAttr(obj, 'MATLAB_empty')) === 1) {
    const dims = matDims(Array.from(obj.value || [], Number));
    if (cls === 'char') return { cls, name, dims, units: new Uint16Array(0) };
    if (cls === 'cell') return { cls, name, dims, items: [] };
    if (cls === 'struct') return { cls, className: null, name, dims, fields: [], items: matNumel(dims) === 1 ? [[]] : [] };
    const kind = MAT_NUMERIC[cls] ? cls : 'double';
    return { cls: kind, name, dims, re: new MAT_NUMERIC[kind][0](0), im: null };
  }
  const dims = matReversed(obj.shape);
  if (Number(matAttr(obj, 'MATLAB_object_decode')) === 3) {
    return { cls: 'opaque', name, dims: [1, 1], typeSystem: 'MCOS', className: cls,
             data: { cls: 'uint32', name: '', dims, re: Uint32Array.from(obj.value, Number), im: null } };
  }
  if (cls === 'cell') {
    return { cls, name, dims, items: Array.from(obj.value, ref => child(f.dereference(ref), '')) };
  }
  if (cls === 'char') {
    return { cls, name, dims, units: Uint16Array.from(obj.value, x => Number(x) & 0xffff) };
  }
  const kind = MAT_NUMERIC[cls] ? cls : MAT_CLASS_OF_DTYPE[obj.dtype];
  const value = obj.value;
  if (Array.isArray(obj.dtype) && kind) {
    // (real, imag) pairs
    const pairs = Array.from(value);
    return { cls: kind, name, dims, re: matAsClass(pairs.map(p => p[0]), kind), im: matAsClass(pairs.map(p => p[1]), kind) };
  }
  if (!kind) throw matDamaged(`${name || 'an array'} has a type no MATLAB class has`);
  return { cls: kind, name, dims, re: matAsClass(ArrayBuffer.isView(value) ? value : Array.from(value), kind), im: null };
}

function matHdf5Sparse(group, name, cls, rows) {
  const read = (k) => { try { const d = group.get(k); return d ? d.value : null; } catch (_) { return null; } };
  const jc = Int32Array.from(read('jc') || [0], Number);
  const ir = Int32Array.from(read('ir') || [], Number);
  const data = read('data');
  const logical = cls === 'logical';
  const kind = logical ? 'logical' : 'double';
  let re;
  let im = null;
  if (data && !ArrayBuffer.isView(data) && Array.isArray(data) && Array.isArray(data[0])) {
    re = matAsClass(data.map(p => p[0]), kind);
    im = matAsClass(data.map(p => p[1]), kind);
  } else {
    re = matAsClass(data ? (ArrayBuffer.isView(data) ? data : Array.from(data)) : [], kind);
  }
  const dims = [rows, jc.length - 1];
  const nnz = jc[jc.length - 1];
  if (!(rows >= 0) || !(nnz >= 0 && nnz <= ir.length && nnz <= re.length)) throw matDamaged(`the sparse matrix ${name} is damaged`);
  return { cls: 'sparse', name, dims, logical, ir, jc, re, im };
}

/* ── the objects MATLAB keeps apart ──────────────────────────────────── */

/**
 * The objects of a file, from the cell array MATLAB keeps them in. Its first
 * cell describes them, in a layout of MATLAB's own:
 *
 *   two numbers -- the layout's version, how many names follow -- and the
 *   offsets of the regions below; then the names, each ending in a NUL
 *   region 1  each class: its package's name and its own, as name numbers
 *   region 2  property sets of objects MATLAB saves whole (a string is one)
 *   region 3  each object: its class, its property set in region 2 or 4, its id
 *   region 4  property sets of the other objects
 *
 * A property set is a count, then a name, a kind and a value for each
 * property. The kind says what the value is: a name's number, the place of the
 * property's array among the cells (from the third), or the value itself.
 *
 * @param {Object[]} cells - The cell array's elements, as arrays
 * @returns {{classOf: function(number): string, propsOf: function(number): Array}}
 */
function matObjects(cells) {
  const meta = cells && cells[0];
  const bytes = meta && meta.re instanceof Uint8Array ? meta.re : null;
  if (!bytes || bytes.length < 40) throw matDamaged('the objects it keeps have no description');
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const u32 = (o) => (o >= 0 && o + 4 <= bytes.length ? view.getUint32(o, true) : 0);
  const count = u32(4);
  if (count > bytes.length) throw matDamaged('the description of the objects it keeps is damaged');

  // How many offsets come before the names is the layout's: those MATLAB has
  // written have eight. Each other count is tried in case, and kept only if
  // the names then end where the first region begins.
  let names = null;
  let offsets = null;
  for (const k of [8, 6, 7, 5, 9, 10]) {
    const offs = Array.from({ length: k }, (_, i) => u32(8 + 4 * i));
    const start = 8 + 4 * k;
    if (!(offs[0] > start && offs[0] <= bytes.length)) continue;
    const found = [];
    let s = '';
    for (let o = start; o < offs[0] && found.length < count; o++) {
      if (bytes[o] === 0) {
        found.push(s);
        s = '';
      } else {
        s += String.fromCharCode(bytes[o]);
      }
    }
    if (found.length === count && found.every(n => /^[\x21-\x7e]*$/.test(n))) {
      names = found;
      offsets = offs;
      break;
    }
  }
  if (!names) throw matDamaged('its objects are described in a layout this page does not know');
  const nameOf = (i) => (i >= 1 && i <= names.length ? names[i - 1] : '');
  const region = (i) => [offsets[i] || 0, offsets[i + 1] || 0];

  const classes = [];
  {
    const [from, to] = region(0);
    for (let o = from + 16; o + 16 <= to; o += 16) {
      const pkg = nameOf(u32(o));
      classes.push(pkg ? `${pkg}.${nameOf(u32(o + 4))}` : nameOf(u32(o + 4)));
    }
  }
  const propertySets = (i) => {
    const [from, to] = region(i);
    const sets = [];
    let o = from + 8;
    while (o + 4 <= to) {
      const n = u32(o);
      o += 4;
      if (n > (to - o) / 12) break;
      const props = [];
      for (let k = 0; k < n; k++, o += 12) props.push({ name: nameOf(u32(o)), kind: u32(o + 4), value: u32(o + 8) });
      sets.push(props);
      if ((o - from) % 8) o += 4;
    }
    return sets;
  };
  const saved = propertySets(1);
  const others = propertySets(3);
  const objects = new Map();
  {
    const [from, to] = region(2);
    for (let o = from + 24; o + 24 <= to; o += 24) {
      objects.set(u32(o + 20), { cls: u32(o), saved: u32(o + 12), other: u32(o + 16) });
    }
  }
  return {
    classOf: (classId) => classes[classId - 1] || '',
    propsOf: (id) => {
      const o = objects.get(id);
      if (!o) return null;
      const set = (o.saved ? saved[o.saved - 1] : others[o.other - 1]) || [];
      return set.map(({ name, kind, value }) => ({
        name,
        value: kind === 1 ? cells[value + 2] : kind === 2 ? value : kind === 0 ? nameOf(value) : undefined
      }));
    }
  };
}

/**
 * A reference to objects kept apart: [mark, dimensions, size..., an id per
 * object, the class]. Null when the array is not one.
 */
function matObjectRef(array) {
  if (!array || array.cls !== 'uint32' || !array.re) return null;
  const v = array.re;
  if (v.length < 5 || v[0] !== MAT_OBJECT_MARK) return null;
  const nd = v[1];
  if (nd < 2 || nd > 32 || v.length < 2 + nd + 1) return null;
  const dims = Array.from(v.subarray(2, 2 + nd));
  const numel = matNumel(dims);
  if (v.length !== 2 + nd + numel + 1) return null;
  return { dims, ids: Array.from(v.subarray(2 + nd, 2 + nd + numel)), classId: v[v.length - 1] };
}

/**
 * A string array, from the one property MATLAB saves it by: uint64 words
 * holding a version, the number of dimensions, the size, the length of each
 * string (all ones for a missing one), then the text as UTF-16, four
 * characters to a word.
 */
function matStringArray(any) {
  if (!any || !(any.re instanceof BigUint64Array) || any.re.length < 2) throw matDamaged('a string array is damaged');
  const w = any.re;
  const nd = Number(w[1]);
  if (Number(w[0]) !== 1 || nd < 2 || nd > 32 || w.length < 2 + nd) throw matDamaged('a string array is written in a form this page does not read');
  const dims = Array.from(w.subarray(2, 2 + nd), Number);
  const numel = matNumel(dims);
  if (w.length < 2 + nd + numel) throw matDamaged('a string array is damaged');
  const lengths = w.subarray(2 + nd, 2 + nd + numel);
  // The words as UTF-16 code units: little-endian words hold the first
  // character in their lowest bits, as the code units of their bytes do.
  const start = 2 + nd + numel;
  const units = new Uint16Array(w.buffer, w.byteOffset + start * 8, (w.length - start) * 4);
  const strings = new Array(numel);
  let at = 0;
  let missing = 0;
  for (let k = 0; k < numel; k++) {
    if (lengths[k] === 0xffffffffffffffffn) {
      strings[k] = '<missing>';
      missing++;
      continue;
    }
    const n = Number(lengths[k]);
    if (at + n > units.length) throw matDamaged('a string array is damaged');
    strings[k] = matString(units, at, at + n);
    at += n;
  }
  return { dims, strings, missing };
}

/* ── the HDF5 file ───────────────────────────────────────────────────── */

/**
 * What a file's variables are written as: the tree easWriteHdf5 writes, a
 * group or dataset for each array as the top of this section says.
 *
 * @param {string} fileName
 * @param {Object} mat - From readMatFile
 * @returns {{tree: Object, datasets: number}}
 */
function matTree(fileName, mat) {
  const e = escapeHtml;
  const unread = mat.variables.filter(v => v.error).length;
  const count = mat.variables.length;
  const root = easGroup({
    Information: `<p>${e(fileName)}: ${e(mat.header || 'a MATLAB MAT-file')}.</p>`
      + `<p>MAT-file ${e(mat.format)}, ${count.toLocaleString('en-US')} variable${count === 1 ? '' : 's'}`
      + `${unread ? `; ${unread} could not be read` : ''}.</p>`,
    MATLAB_format: mat.format,
    MATLAB_header: mat.header || undefined
  });
  const ctx = { objects: mat.objects, arrays: 0, datasets: 0, capped: false };
  for (const v of mat.variables) {
    const name = easLinkName(v.name || 'unnamed variable');
    const node = v.error
      ? easGroup({ MATLAB_note: `This variable could not be read: ${v.error}` })
      : matNode(v.array, ctx, 0, new Set());
    if (node) matPut(root, name, node);
  }
  if (ctx.capped) root.attrs.MATLAB_note = `Only the first ${MAT_MAX_ARRAYS.toLocaleString('en-US')} arrays are shown.`;
  return { tree: root, datasets: ctx.datasets };
}

/** A child put in a group under its name, numbered when the name is taken. */
function matPut(group, name, node) {
  let key = name;
  for (let n = 2; group.children.has(key); n++) key = `${name} (${n})`;
  group.children.set(key, node);
}

function matDataset(ctx, attrs, shape, dtype, make) {
  ctx.datasets++;
  return { kind: 'dataset', attrs, shape, dtype, make };
}

/** The attributes every array carries. */
function matAttrs(cls, dims, extra = {}) {
  return { MATLAB_class: cls, MATLAB_size: matSizeText(dims), ...extra };
}

/**
 * The group or dataset one array is written as, or null once a file has used
 * up the arrays it may have.
 *
 * @param {Object} a - An array as read
 * @param {Object} ctx - {objects, arrays, datasets, capped}
 * @param {number} depth
 * @param {Set<number>} within - The objects this one is inside, against a
 *   file whose objects hold one another
 */
function matNode(a, ctx, depth, within) {
  if (++ctx.arrays > MAT_MAX_ARRAYS) {
    ctx.capped = true;
    return null;
  }
  if (depth > MAT_MAX_DEPTH) return easGroup({ MATLAB_note: `Arrays nested more than ${MAT_MAX_DEPTH} deep are not shown.` });
  const extra = a.global ? { MATLAB_global: 'TRUE' } : {};
  const kids = (group, names, arrays) => {
    arrays.forEach((x, k) => {
      const node = matNode(x, ctx, depth + 1, within);
      if (node) matPut(group, easLinkName(names[k]), node);
    });
    return group;
  };

  if (MAT_NUMERIC[a.cls]) {
    const type = MAT_NUMERIC[a.cls][1];
    return matDataset(ctx, matAttrs(a.cls, a.dims, extra), a.dims, a.im ? [['real', type], ['imag', type]] : type,
      () => (a.im ? new Map([['real', matRowMajor(a.re, a.dims)], ['imag', matRowMajor(a.im, a.dims)]])
                  : matRowMajor(a.re, a.dims)));
  }
  switch (a.cls) {
    case 'char': {
      const { shape, strings } = matCharStrings(a);
      return matDataset(ctx, matAttrs('char', a.dims, extra), shape, 'S', () => strings);
    }
    case 'cell': {
      const table = matTable(a.items, a.dims);
      if (table) return matDataset(ctx, { ...matAttrs('cell', a.dims, extra), ...table.attrs }, a.dims, table.dtype, table.make);
      return kids(easGroup(matAttrs('cell', a.dims, extra)), matIndexNames(a.dims, '{', '}'), a.items);
    }
    case 'struct':
      return matStructNode(a, ctx, depth, within, extra);
    case 'sparse':
      return matSparseNode(a, ctx, extra);
    case 'function_handle':
      return matFunctionNode(a, ctx, depth, within, extra);
    case 'opaque':
      return matObjectNode(a, ctx, depth, within, extra);
    default:
      return easGroup(matAttrs(`class ${a.code}`, a.dims, { ...extra, MATLAB_note: 'MAT-files have no class with this number.' }));
  }
}

/** A char array with one row: text a cell of strings is made of. */
function matIsRowText(a) {
  return a.cls === 'char' && a.dims.length === 2 && a.dims[0] <= 1;
}

/**
 * A number as text in a table that also holds text: in full, as MATLAB would
 * read it back -- a single to the fewest digits that give it again.
 */
function matNumberText(x, cls) {
  if (typeof x === 'bigint') return String(x);
  if (cls === 'logical') return x ? 'true' : 'false';
  if (Number.isNaN(x)) return 'NaN';
  if (x === Infinity) return 'Inf';
  if (x === -Infinity) return '-Inf';
  if (cls === 'single') {
    for (let digits = 1; digits < 9; digits++) {
      const s = String(parseFloat(x.toPrecision(digits)));
      if (Math.fround(parseFloat(s)) === x) return s;
    }
  }
  return String(x);
}

/**
 * Arrays that read as one table, as a cell from a spreadsheet does, or a
 * field across a struct array: each a real number alone, a row of text, or
 * empty. The one dataset they are written as, or null when they are anything
 * else and each is written as itself.
 *
 *   text only                 strings
 *   numbers of one class      those numbers; an empty element is NaN, and
 *                             said to be, where the class has NaN
 *   numbers and text          strings, a number written in full and an
 *                             empty element as ''
 *
 * @param {Object[]} values - In MATLAB's order
 * @param {number[]} dims - Their arrangement
 * @returns {{dtype: *, make: function, attrs: Object, classes: string[]}|null}
 */
function matTable(values, dims) {
  if (!values.length) return null;
  const classes = new Set();
  let texts = 0;
  let empties = 0;
  for (const v of values) {
    if (matIsRowText(v)) {
      texts++;
    } else if (MAT_NUMERIC[v.cls] && !v.im && v.re.length <= 1) {
      if (v.re.length) classes.add(v.cls);
      else empties++;
    } else {
      return null;
    }
  }
  if (!classes.size && !texts) return null;
  const order = (rows) => () => matRowMajor(rows, dims);
  const text = (v) => (matIsRowText(v) ? matString(v.units) : v.re.length ? matNumberText(v.re[0], v.cls) : '');
  if (texts === values.length) {
    return { dtype: 'S', make: order(values.map(text)), attrs: {}, classes: ['char'] };
  }
  const [cls] = classes;
  const holdsNaN = cls === 'double' || cls === 'single';
  if (!texts && classes.size === 1 && (!empties || holdsNaN)) {
    const [A, type] = MAT_NUMERIC[cls];
    const out = new A(values.length);
    values.forEach((v, k) => { out[k] = v.re.length ? v.re[0] : NaN; });
    const note = empties ? { empty: empties, MATLAB_note: `${empties} empty element${empties === 1 ? ' is' : 's are'} shown as NaN.` } : {};
    return { dtype: type, make: order(out), attrs: note, classes: [cls] };
  }
  return {
    dtype: 'S', make: order(values.map(text)), classes: [...classes, ...(texts ? ['char'] : [])],
    attrs: { MATLAB_note: 'Numbers and text in one table: each number is shown as text, an empty element as an empty string.' }
  };
}

/**
 * A char array as strings: one for each row, of the characters along the
 * second dimension. A row alone is a scalar string.
 */
function matCharStrings(a) {
  const [rows, cols] = a.dims;
  const rest = a.dims.slice(2);
  const others = matNumel(rest);
  if (rows * others <= 1) return { shape: [], strings: [matString(a.units)] };
  const out = new Array(rows * others);
  const row = new Uint16Array(cols);
  for (let k = 0; k < others; k++) {
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++) row[j] = a.units[i + rows * (j + cols * k)];
      out[i + rows * k] = matString(row);
    }
  }
  const shape = [rows, ...rest];
  while (shape.length > 1 && shape[shape.length - 1] === 1) shape.pop();
  return { shape, strings: matRowMajor(out, shape) };
}

/**
 * A struct: a group of its fields. One struct's field is its value; a struct
 * array's field is one dataset when its values read as a table (matTable),
 * else a group of (1), (2), ...
 */
function matStructNode(a, ctx, depth, within, extra) {
  const group = easGroup(matAttrs(a.className || 'struct', a.dims, { ...extra, MATLAB_fields: a.fields }));
  const numel = matNumel(a.dims);
  a.fields.forEach((field, j) => {
    let node;
    if (numel === 1) {
      node = matNode(a.items[0][j], ctx, depth + 1, within);
    } else if (numel > 1) {
      const values = a.items.map(el => el[j]);
      const table = matTable(values, a.dims);
      if (table) {
        const note = [`The field ${field} of each element.`, table.attrs.MATLAB_note].filter(Boolean).join(' ');
        node = matDataset(ctx, { ...matAttrs(table.classes.join(', '), a.dims), ...table.attrs, MATLAB_note: note },
          a.dims, table.dtype, table.make);
      } else {
        node = easGroup(matAttrs('struct field', a.dims, { MATLAB_note: `The field ${field} of each element.` }));
        const names = matIndexNames(a.dims, '(', ')');
        values.forEach((v, k) => {
          const child = matNode(v, ctx, depth + 2, within);
          if (child) matPut(node, names[k], child);
        });
      }
    }
    if (node) matPut(group, easLinkName(field), node);
  });
  return group;
}

/**
 * A sparse matrix: in full when it is small enough to be held so, else its
 * values with their rows and columns, counted from 1 as MATLAB counts.
 */
function matSparseNode(a, ctx, extra) {
  const [rows, cols] = a.dims;
  const nnz = a.jc[cols];
  const cls = a.logical ? 'logical' : 'double';
  for (let j = 0; j < cols; j++) {
    if (a.jc[j] < 0 || a.jc[j] > a.jc[j + 1]) throw matDamaged('a sparse matrix is damaged');
  }
  for (let k = 0; k < nnz; k++) {
    if (a.ir[k] < 0 || a.ir[k] >= rows) throw matDamaged('a sparse matrix holds a value outside its size');
  }
  const attrs = matAttrs(cls, a.dims, { ...extra, MATLAB_sparse: 'TRUE', nnz });
  const type = MAT_NUMERIC[cls][1];
  if (rows * cols <= MAT_FULL_SPARSE) {
    const A = MAT_NUMERIC[cls][0];
    const full = (part) => {
      const out = new A(rows * cols);
      for (let j = 0; j < cols; j++) {
        for (let k = a.jc[j]; k < a.jc[j + 1]; k++) out[a.ir[k] + rows * j] = part[k];
      }
      return matRowMajor(out, a.dims);
    };
    return matDataset(ctx, attrs, a.dims, a.im ? [['real', type], ['imag', type]] : type,
      () => (a.im ? new Map([['real', full(a.re)], ['imag', full(a.im)]]) : full(a.re)));
  }
  const group = easGroup({ ...attrs, MATLAB_note: 'Too large to show with its zeros: each value with its row and column.' });
  const column = new Int32Array(nnz);
  for (let j = 0; j < cols; j++) {
    for (let k = a.jc[j]; k < a.jc[j + 1]; k++) column[k] = j + 1;
  }
  matPut(group, 'row', matDataset(ctx, {}, [nnz], '<i', () => Int32Array.from(a.ir.subarray(0, nnz), i => i + 1)));
  matPut(group, 'column', matDataset(ctx, {}, [nnz], '<i', () => column));
  matPut(group, 'value', matDataset(ctx, {}, [nnz], a.im ? [['real', type], ['imag', type]] : type,
    () => (a.im ? new Map([['real', a.re.subarray(0, nnz)], ['imag', a.im.subarray(0, nnz)]]) : a.re.subarray(0, nnz))));
  return group;
}

/** A field of a one-element struct, as an array, or null. */
function matField(s, name) {
  if (!s || s.cls !== 'struct' || matNumel(s.dims) !== 1) return null;
  const j = s.fields.indexOf(name);
  return j >= 0 ? s.items[0][j] : null;
}

function matRowText(a) {
  return a && a.cls === 'char' ? matString(a.units) : '';
}

/**
 * A function handle: its text as MATLAB shows it. MATLAB describes one by a
 * struct whose field function_handle says what it is: a function's name, or
 * for an anonymous function its text, after a mark of MATLAB's own.
 */
function matFunctionNode(a, ctx, depth, within, extra) {
  const fh = matField(a.inner, 'function_handle');
  const fn = matRowText(matField(fh, 'function'));
  if (!fh || !fn) return matStructNode({ ...a.inner, className: 'function_handle' }, ctx, depth, within, extra);
  const type = matRowText(matField(fh, 'type'));
  const file = matRowText(matField(fh, 'file'));
  const text = type === 'anonymous' && fn.includes('@') ? fn.slice(fn.indexOf('@')) : `@${fn}`;
  return matDataset(ctx, matAttrs('function_handle', [1, 1], { ...extra, type: type || undefined, file: file || undefined }),
    [], 'S', () => [text]);
}

/**
 * An object kept apart: a string array as its strings, a table as its
 * variables by name, any other object as a group of the properties MATLAB
 * saved, a group of them for each object of an array.
 */
function matObjectNode(a, ctx, depth, within, extra) {
  const note = (why) => easGroup(matAttrs(a.className || 'object', [1, 1], { ...extra, MATLAB_note: why }));
  if (a.typeSystem !== 'MCOS') return note(`A ${a.typeSystem || 'MATLAB'} object, which this page does not read.`);
  const ref = matObjectRef(a.data);
  if (!ref) return note('This object\'s reference is damaged.');
  return matObjects2Node(ref, a.className, ctx, depth, within, extra, note);
}

function matObjects2Node(ref, className, ctx, depth, within, extra, note) {
  const objects = ctx.objects;
  if (!objects) return note('The file keeps no objects, though this variable is one.');
  if (objects.error) return note(`The objects this file keeps could not be read: ${objects.error}`);
  const cls = className || objects.classOf(ref.classId) || 'object';
  const numel = matNumel(ref.dims);
  const propsOf = (id) => {
    if (within.has(id)) return null;
    return objects.propsOf(id);
  };

  if (cls === 'string' && numel === 1) {
    const props = propsOf(ref.ids[0]);
    const any = props && props.find(p => p.name === 'any');
    if (!any) return note('This string array is damaged.');
    const s = matStringArray(any.value);
    return matDataset(ctx, matAttrs('string', s.dims, { ...extra, ...(s.missing ? { missing: s.missing } : {}) }),
      s.dims, 'S', () => matRowMajor(s.strings, s.dims));
  }

  const objectGroup = (id) => {
    const props = propsOf(id);
    if (!props) return easGroup({ MATLAB_note: 'This object is missing from the file, or holds itself.' });
    const inner = new Set(within).add(id);
    if (cls === 'table') {
      const table = matTableNode(props, ctx, depth, inner, extra);
      if (table) return table;
    }
    const group = easGroup({});
    for (const p of props) {
      const node = matPropertyNode(p.value, ctx, depth + 1, inner);
      if (node) matPut(group, easLinkName(p.name || 'property'), node);
    }
    return group;
  };

  if (numel === 1) {
    const group = objectGroup(ref.ids[0]);
    group.attrs = { ...matAttrs(cls, ref.dims, extra), ...group.attrs };
    return group;
  }
  const group = easGroup(matAttrs(cls, ref.dims, extra));
  const names = matIndexNames(ref.dims, '(', ')');
  ref.ids.forEach((id, k) => {
    if (++ctx.arrays > MAT_MAX_ARRAYS) {
      ctx.capped = true;
      return;
    }
    const child = objectGroup(id);
    child.attrs = { ...matAttrs(cls, [1, 1]), ...child.attrs };
    matPut(group, names[k], child);
  });
  return group;
}

/**
 * A property's value: an array, an object inside it (kept as a reference to
 * it), or a number or name MATLAB wrote in place of one.
 */
function matPropertyNode(value, ctx, depth, within) {
  if (value === undefined || value === null) return null;
  if (typeof value === 'number') return matDataset(ctx, matAttrs('double', [1, 1]), [], '<d', () => new Float64Array([value]));
  if (typeof value === 'string') return matDataset(ctx, matAttrs('char', [1, value.length]), [], 'S', () => [value]);
  const ref = matObjectRef(value);
  if (ref && ctx.objects && !ctx.objects.error) {
    const note = (why) => easGroup({ MATLAB_note: why });
    return matObjects2Node(ref, null, ctx, depth, within, {}, note);
  }
  return matNode(value, ctx, depth, within);
}

/**
 * A table as its variables, each under its name, and its row names when it
 * has them. Null when its properties are not those a table saves, and it is
 * shown as any other object is.
 */
function matTableNode(props, ctx, depth, within, extra) {
  const prop = (n) => (props.find(p => p.name === n) || {}).value;
  const data = prop('data');
  const names = prop('varnames');
  if (!data || data.cls !== 'cell' || !names || names.cls !== 'cell' || names.items.length !== data.items.length
      || !names.items.every(matIsRowText)) return null;
  const nrows = typeof prop('nrows') === 'object' && prop('nrows').re ? Number(prop('nrows').re[0]) : null;
  const group = easGroup(matAttrs('table', [nrows ?? 0, data.items.length], { ...extra, MATLAB_fields: names.items.map(n => matString(n.units)) }));
  data.items.forEach((column, k) => {
    const node = matPropertyNode(column, ctx, depth + 1, within);
    if (node) matPut(group, easLinkName(matString(names.items[k].units)), node);
  });
  const rows = prop('rownames');
  if (rows && rows.cls === 'cell' && rows.items.length) {
    const node = matNode(rows, ctx, depth + 1, within);
    if (node) matPut(group, 'Row names', node);
  }
  return group;
}

/* ── reading and opening one ─────────────────────────────────────────── */

/**
 * A MAT-file read whole: its format, its header line, its variables -- each
 * an array as read, or the reason it could not be -- and the objects it keeps.
 *
 * @param {ArrayBuffer} buffer
 * @returns {Promise<{format: string, header: string, variables: Array, objects: Object|null}>}
 */
async function readMatFile(buffer) {
  const bytes = new Uint8Array(buffer);
  const text = bytes.length >= 128 ? matLatin1(bytes.subarray(0, 116)) : '';
  if (/^MATLAB 7\.3 MAT-file/.test(text)) {
    if (!validateHdf5Buffer(buffer).ok) throw matDamaged('it says it is a 7.3 MAT-file, which is HDF5, and it is not HDF5');
    return matReadV73(buffer, text.replace(/[\s\u0000]+$/, ''));
  }
  // A Level 5 file is known by its version and byte-order mark as well as by
  // its text, which other programs write as they please.
  const marked = bytes.length >= 128 && ((bytes[126] === 0x49 && bytes[127] === 0x4d && bytes[124] === 0 && bytes[125] === 1)
    || (bytes[126] === 0x4d && bytes[127] === 0x49 && bytes[124] === 1 && bytes[125] === 0));
  if (/^MATLAB 5\.0 MAT-file/.test(text) || marked) return matReadLevel5(bytes);
  return matReadLevel4(bytes);
}

/**
 * Open a MAT-file: its variables written as an HDF5 file in memory and
 * registered under the file's own name. Does not refresh the tree.
 *
 * @param {string} fileName - Display name
 * @param {ArrayBuffer} buffer - The file's bytes
 * @param {string} [context] - Label for failure reporting
 * @returns {Promise<string[]>} The name it was registered under
 */
async function ingestMatFile(fileName, buffer, context = 'ingestMatFile') {
  if (!buffer || typeof buffer.byteLength !== 'number' || buffer.byteLength === 0) {
    throw new Error(`${fileName} is empty.`);
  }
  if (buffer.byteLength > KVOT_FILE_SIZE_LIMITS.dataset) {
    throw new Error(kvotFileTooLarge({ name: fileName, size: buffer.byteLength },
                                     KVOT_FILE_SIZE_LIMITS.dataset).reason);
  }
  setFileLoadProgress(null, `${fileName} — reading its variables…`);
  await yieldForPaint();
  let mat;
  try {
    mat = await readMatFile(buffer);
  } catch (err) {
    throw new Error(`${fileName} could not be read: ${err.message}`);
  }
  if (!mat.variables.length) throw new Error(`${fileName} holds no variables.`);
  if (mat.variables.every(v => v.error)) throw new Error(`${fileName} could not be read: ${mat.variables[0].error}`);

  const { tree, datasets } = matTree(fileName, mat);
  // The arrays as read are held now by the tree alone, which lets each go as
  // it is written: a file's values are not held three times over at once.
  mat = null;
  setFileLoadProgress(null, `${fileName}: writing ${datasets.toLocaleString('en-US')} arrays…`);
  await yieldForPaint();
  const h5 = await easWriteHdf5(tree, (done) => setFileLoadProgress(datasets ? done / datasets : null,
    `${fileName}: ${done.toLocaleString('en-US')} of ${datasets.toLocaleString('en-US')} arrays written…`));
  return [await ingestHdf5Buffer(fileName, h5, context)];
}
