/* ==========================================================================
   4f. JSON FILES (.json)

   A JSON file opens as an HDF5 file of its own, written here in memory as a
   MAT-file is (rb-mat.js), and then browsed as any file: the tree, a value's
   data and attributes, the charts of a vector or matrix, the downloads.

       object              a group of its members, by name
       array of numbers    one dataset: a vector, or a matrix -- or an array
                           of more dimensions -- when its arrays nest evenly;
                           a null is NaN, and said to be
       array of strings    one dataset of strings, as are booleans
       array of objects    a table, when each object holds only numbers,
                           strings, booleans and nulls: a group with a
                           dataset per member, its values over all of them,
                           as a struct array's field is one in a MAT-file
       any other array     a group of its elements, [0], [1], ...
       number, string,     a dataset of one value; true and false and null
       true, false, null   as their words

   Every node says what it was in JSON_type. A file that is not strict
   JSON -- comments, a comma before a closing bracket, or the NaN and
   Infinity that Python's json module writes -- is read all the same, and
   says so.

   The pieces shared with XML files (rb-xml.js) are here too: the file's
   text from its bytes, a column of a table, the limits on what a file may
   make, the writing and the opening.
   ========================================================================== */

'use strict';   // see the script manifest in rb.html for why

/* How far a file may take the page. */
const DOC_MAX_NODES = 200000;      // groups and datasets written for one file
const DOC_MAX_DEPTH = 64;          // values within values
const JSON_MAX_NESTING = 10000;    // what the lenient reading follows before it stops

/**
 * Whether bytes handed over are a JSON file: by its name, or -- for bytes
 * that arrive under another, as a link without one or a handoff named .h5
 * does -- by being no HDF5 and starting with { or [.
 *
 * @param {string} fileName
 * @param {ArrayBuffer|null} buffer - null to decide by the name alone
 * @returns {boolean}
 */
function isJsonFile(fileName, buffer) {
  if (/\.(json|jsonc|geojson)$/i.test(String(fileName || ''))) return true;
  return docSniff(buffer) === 'json';
}

/* ── shared with rb-xml.js ───────────────────────────────────────────── */

/**
 * What text a file that is not HDF5 starts with: 'json', 'xml', or null. An
 * HTML page is neither: it is what a link to a page about a file gives,
 * which validateHdf5Buffer explains.
 */
function docSniff(buffer) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 2 || validateHdf5Buffer(buffer).ok) return null;
  const head = docDecode(buffer.slice(0, Math.min(buffer.byteLength, 1024)), true).replace(/^\s+/, '');
  if (/^[{[]/.test(head)) return 'json';
  if (/^<!doctype\s+html|^<html/i.test(head)) return null;
  if (/^<(\?xml|!--|!doctype|[A-Za-z_])/i.test(head)) return 'xml';
  return null;
}

/**
 * A file's text from its bytes: UTF-16 or UTF-8 by its byte-order mark,
 * else the encoding its XML declaration names, else UTF-8.
 *
 * @param {ArrayBuffer} buffer
 * @param {boolean} [part] - Only the head of a file: a character cut at its end is not an error
 * @returns {string}
 */
function docDecode(buffer, part = false) {
  const bytes = new Uint8Array(buffer);
  let label = 'utf-8';
  let skip = 0;
  if (bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) skip = 3;
  else if (bytes[0] === 0xff && bytes[1] === 0xfe) { label = 'utf-16le'; skip = 2; }
  else if (bytes[0] === 0xfe && bytes[1] === 0xff) { label = 'utf-16be'; skip = 2; }
  else if (bytes[0] === 0x3c && bytes[1] === 0x00) label = 'utf-16le';
  else if (bytes[0] === 0x00 && bytes[1] === 0x3c) label = 'utf-16be';
  else {
    const declared = /^\s*<\?xml[^>]*\bencoding\s*=\s*["']([A-Za-z0-9._:-]+)["']/.exec(matLatin1(bytes.subarray(0, Math.min(200, bytes.length))));
    if (declared) label = declared[1].toLowerCase();
  }
  let decoder;
  try {
    decoder = new TextDecoder(label, { fatal: false });
  } catch (_) {
    decoder = new TextDecoder('utf-8', { fatal: false });
  }
  return decoder.decode(bytes.subarray(skip), { stream: part });
}

/** A count and a noun, made plural as English makes it. */
function docCount(n, noun, plural = `${noun}s`) {
  return `${n.toLocaleString('en-US')} ${n === 1 ? noun : plural}`;
}

/** A dataset of the tree easWriteHdf5 writes, counted. */
function docDataset(ctx, attrs, shape, dtype, make) {
  ctx.datasets++;
  return { kind: 'dataset', attrs, shape, dtype, make };
}

/** Whether a file has used up the groups and datasets it may make. */
function docFull(ctx) {
  if (++ctx.nodes <= DOC_MAX_NODES) return false;
  ctx.capped = true;
  return true;
}

/** Names for n elements, numbered from `first` and zero-padded so that the tree, which sorts names as text, keeps them in order. */
function docIndexNames(n, first, wrap) {
  const width = String(n - 1 + first).length;
  return Array.from({ length: n }, (_, k) => wrap(String(k + first).padStart(width, '0')));
}

/**
 * A column of a table, its values over the rows: numbers when each is a
 * number or missing -- a missing one NaN, and said to be -- else text, a
 * missing one empty.
 *
 * @param {Array} values - Numbers, strings, or undefined for missing
 * @param {string} kindAttr - The attribute that names what the column holds
 * @returns {{dtype: string, make: function, attrs: Object}}
 */
function docColumn(values, kindAttr) {
  const missing = values.filter(v => v === undefined || v === null).length;
  const numeric = values.every(v => v === undefined || v === null || typeof v === 'number');
  if (numeric && missing < values.length) {
    const out = Float64Array.from(values, v => (typeof v === 'number' ? v : NaN));
    return { dtype: '<d', make: () => out, attrs: { [kindAttr]: 'number', ...(missing ? { note: `${docCount(missing, 'missing value')} shown as NaN.` } : {}) } };
  }
  const text = values.map(v => (v === undefined || v === null ? '' : String(v)));
  const kinds = new Set(values.filter(v => v !== undefined && v !== null).map(v => typeof v));
  return { dtype: 'S', make: () => text, attrs: { [kindAttr]: [...kinds].join(', ') || 'string',
    ...(kinds.size > 1 && kinds.has('number') ? { note: 'Numbers and text in one column: each number is shown as text.' } : {}),
    ...(missing ? { missing } : {}) } };
}

/**
 * A tree written as an HDF5 file in memory and opened under the file's
 * name, as an Ecolego run or a MAT-file is.
 */
async function docOpen(fileName, tree, datasets, context) {
  setFileLoadProgress(null, `${fileName}: writing ${datasets.toLocaleString('en-US')} values…`);
  await yieldForPaint();
  const h5 = await easWriteHdf5(tree, (done) => setFileLoadProgress(datasets ? done / datasets : null,
    `${fileName}: ${done.toLocaleString('en-US')} of ${datasets.toLocaleString('en-US')} values written…`));
  return [await ingestHdf5Buffer(fileName, h5, context)];
}

/** A text file's bytes, refused when there are none or more than the page reads of a document. */
function docCheckSize(fileName, buffer) {
  if (!buffer || typeof buffer.byteLength !== 'number' || buffer.byteLength === 0) throw new Error(`${fileName} is empty.`);
  if (buffer.byteLength > KVOT_FILE_SIZE_LIMITS.document) {
    throw new Error(kvotFileTooLarge({ name: fileName, size: buffer.byteLength }, KVOT_FILE_SIZE_LIMITS.document).reason);
  }
}

/* ── reading JSON ────────────────────────────────────────────────────── */

/**
 * JSON as people write it beside the standard: // and /* *\/ comments, a
 * comma before a closing bracket, and NaN, Infinity and -Infinity, which
 * Python's json module writes for numbers JSON has no word for. Used when
 * JSON.parse refuses a file; its errors say where, by line and column.
 *
 * @param {string} text
 * @returns {*}
 */
function jsonParseLenient(text) {
  let i = 0;
  const n = text.length;
  const where = (at) => {
    const before = text.slice(0, at);
    const line = (before.match(/\n/g) || []).length + 1;
    return `line ${line}, column ${at - before.lastIndexOf('\n')}`;
  };
  const fail = (what, at = i) => { throw new Error(`${what} at ${where(at)}`); };
  const space = () => {
    for (;;) {
      while (i < n && /\s/.test(text[i])) i++;
      if (text[i] === '/' && text[i + 1] === '/') { while (i < n && text[i] !== '\n') i++; continue; }
      if (text[i] === '/' && text[i + 1] === '*') {
        const end = text.indexOf('*/', i + 2);
        if (end < 0) fail('a comment that never ends');
        i = end + 2;
        continue;
      }
      return;
    }
  };
  const NUMBER = /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y;
  const string = () => {
    const start = i++;
    let out = '';
    for (;;) {
      if (i >= n) fail('a string that never ends', start);
      const c = text[i];
      if (c === '"') { i++; return out; }
      if (c !== '\\') { const next = text.indexOf('"', i); const esc = text.indexOf('\\', i); const stop = Math.min(next < 0 ? n : next, esc < 0 ? n : esc); out += text.slice(i, stop); i = stop; continue; }
      const e = text[i + 1];
      i += 2;
      if (e === 'u') {
        const hex = text.slice(i, i + 4);
        if (!/^[0-9a-fA-F]{4}$/.test(hex)) fail('a \\u escape without four hex digits', i - 2);
        out += String.fromCharCode(parseInt(hex, 16));
        i += 4;
      } else {
        const map = { '"': '"', '\\': '\\', '/': '/', b: '\b', f: '\f', n: '\n', r: '\r', t: '\t' };
        if (!(e in map)) fail(`an unknown escape \\${e}`, i - 2);
        out += map[e];
      }
    }
  };
  const value = (depth) => {
    if (depth > JSON_MAX_NESTING) fail('values nested too deeply');
    space();
    const c = text[i];
    if (c === '{') {
      i++;
      const obj = {};
      space();
      if (text[i] === '}') { i++; return obj; }
      for (;;) {
        space();
        if (text[i] === '}') { i++; return obj; }   // after a trailing comma
        if (text[i] !== '"') fail('a name in quotes expected');
        const key = string();
        space();
        if (text[i] !== ':') fail('a colon expected');
        i++;
        Object.defineProperty(obj, key, { value: value(depth + 1), enumerable: true, writable: true, configurable: true });
        space();
        if (text[i] === ',') { i++; continue; }
        if (text[i] === '}') { i++; return obj; }
        fail('a comma or } expected');
      }
    }
    if (c === '[') {
      i++;
      const arr = [];
      space();
      if (text[i] === ']') { i++; return arr; }
      for (;;) {
        space();
        if (text[i] === ']') { i++; return arr; }   // after a trailing comma
        arr.push(value(depth + 1));
        space();
        if (text[i] === ',') { i++; continue; }
        if (text[i] === ']') { i++; return arr; }
        fail('a comma or ] expected');
      }
    }
    if (c === '"') return string();
    for (const [word, v] of [['true', true], ['false', false], ['null', null], ['NaN', NaN], ['Infinity', Infinity],
      ['-Infinity', -Infinity], ['+Infinity', Infinity]]) {
      if (text.startsWith(word, i)) { i += word.length; return v; }
    }
    NUMBER.lastIndex = i;
    const m = NUMBER.exec(text);
    if (m && m[0] && m[0] !== '-') { i += m[0].length; return Number(m[0]); }
    return fail(i >= n ? 'the text ends where a value was expected' : `an unexpected ${JSON.stringify(text[i])}`);
  };
  const out = value(0);
  space();
  if (i < n) fail('more after the value');
  return out;
}

/* ── JSON in the tree ────────────────────────────────────────────────── */

const jsonKind = (v) => (v === null ? 'null' : Array.isArray(v) ? 'array' : typeof v);
const jsonScalar = (v) => v === null || ['number', 'string', 'boolean'].includes(typeof v);

/** A plain object whose members are each a number, string, boolean or null: a row of a table. */
function jsonIsRecord(v) {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return false;
  for (const k in v) if (Object.prototype.hasOwnProperty.call(v, k) && !jsonScalar(v[k])) return false;
  return true;
}

/**
 * Numbers in arrays nested evenly, as a matrix or more is written: their
 * shape, the numbers in row order and the nulls among them; null when an
 * array is anything else.
 */
function jsonNumbers(a) {
  const shape = [];
  for (let x = a; Array.isArray(x); x = x[0]) {
    shape.push(x.length);
    if (!x.length || shape.length > 16) return null;
  }
  const size = shape.reduce((p, d) => p * d, 1);
  if (!(size > 0) || size > 1e8) return null;
  const out = new Float64Array(size);
  let at = 0;
  let nulls = 0;
  const walk = (x, d) => {
    if (d === shape.length) {
      if (typeof x === 'number') out[at++] = x;
      else if (x === null) { out[at++] = NaN; nulls++; }
      else return false;
      return true;
    }
    if (!Array.isArray(x) || x.length !== shape[d]) return false;
    for (const y of x) if (!walk(y, d + 1)) return false;
    return true;
  };
  if (!walk(a, 0) || nulls === size) return null;
  return { shape, values: out, nulls };
}

/**
 * One JSON value as the node it is written as, or null once a file has made
 * the groups and datasets it may.
 */
function jsonNode(v, ctx, depth) {
  if (docFull(ctx)) return null;
  const kind = jsonKind(v);
  if (depth > DOC_MAX_DEPTH) return easGroup({ JSON_type: kind, note: `Values nested more than ${DOC_MAX_DEPTH} deep are not shown.` });
  switch (kind) {
    case 'number': return docDataset(ctx, { JSON_type: 'number' }, [], '<d', () => Float64Array.of(v));
    case 'string': return docDataset(ctx, { JSON_type: 'string' }, [], 'S', () => [v]);
    case 'boolean':
    case 'null': return docDataset(ctx, { JSON_type: kind }, [], 'S', () => [String(v)]);
    case 'array': return jsonArrayNode(v, ctx, depth);
    default: {
      const group = easGroup({ JSON_type: 'object', members: Object.keys(v).length });
      for (const key of Object.keys(v)) {
        const node = jsonNode(v[key], ctx, depth + 1);
        if (!node) break;
        matPut(group, easLinkName(key === '' ? '""' : key), node);
      }
      return group;
    }
  }
}

/** An array: one dataset of its numbers or strings, a table of its objects, or a group of its elements. */
function jsonArrayNode(a, ctx, depth) {
  const n = a.length;
  if (!n) return docDataset(ctx, { JSON_type: 'array', length: 0 }, [0], '<d', () => new Float64Array(0));
  const numbers = jsonNumbers(a);
  if (numbers) {
    return docDataset(ctx, { JSON_type: 'array', size: numbers.shape.join('×'),
      ...(numbers.nulls ? { note: `${docCount(numbers.nulls, 'null')} shown as NaN.` } : {}) },
    numbers.shape, '<d', () => numbers.values);
  }
  if (a.every(jsonScalar)) {
    const kinds = [...new Set(a.map(jsonKind))];
    const text = a.map(x => String(x));
    return docDataset(ctx, { JSON_type: 'array', length: n, of: kinds.join(', '),
      ...(kinds.includes('number') ? { note: 'Numbers and words in one array: each is shown as text.' } : {}) },
    [n], 'S', () => text);
  }
  if (n >= 2 && a.every(jsonIsRecord)) {
    const keys = [];
    const seen = new Set();
    for (const row of a) for (const k of Object.keys(row)) if (!seen.has(k)) { seen.add(k); keys.push(k); }
    const group = easGroup({ JSON_type: 'array', length: n,
      note: `${docCount(n, 'object')} of numbers and text: each member a column, its values over all of them in order.` });
    for (const key of keys) {
      if (docFull(ctx)) break;
      const col = docColumn(a.map(row => (Object.prototype.hasOwnProperty.call(row, key) ? row[key] : undefined)), 'JSON_type');
      matPut(group, easLinkName(key === '' ? '""' : key), docDataset(ctx, col.attrs, [n], col.dtype, col.make));
    }
    return group;
  }
  const group = easGroup({ JSON_type: 'array', length: n });
  const names = docIndexNames(n, 0, s => `[${s}]`);
  for (let k = 0; k < n; k++) {
    const node = jsonNode(a[k], ctx, depth + 1);
    if (!node) break;
    matPut(group, names[k], node);
  }
  return group;
}

/**
 * A JSON value as the tree easWriteHdf5 writes: an object's members at the
 * top, any other value under the file's name.
 */
function jsonTree(fileName, value, lenient) {
  const ctx = { nodes: 0, datasets: 0, capped: false };
  let objects = 0;
  let arrays = 0;
  let values = 0;
  // counted up to a point: past it, a file is said to hold more
  let more = false;
  const count = (v, depth) => {
    if (depth > DOC_MAX_DEPTH) return;
    if (objects + arrays + values >= 5e6) { more = true; return; }
    if (Array.isArray(v)) { arrays++; for (const x of v) count(x, depth + 1); }
    else if (v && typeof v === 'object') { objects++; for (const k of Object.keys(v)) count(v[k], depth + 1); }
    else values++;
  };
  count(value, 0);
  const e = escapeHtml;
  const held = more ? 'more than 5,000,000 values, objects and arrays'
    : `${docCount(values, 'value')} in ${docCount(objects, 'object')} and ${docCount(arrays, 'array')}`;
  const root = easGroup({
    Information: `<p>${e(fileName)}: JSON, ${e(held)}.</p>`
      + (lenient ? '<p>It holds what strict JSON does not -- a comment, a comma before a closing bracket, or NaN or Infinity -- and is read all the same.</p>' : ''),
    JSON_format: lenient ? 'JSON, read leniently' : 'JSON'
  });
  if (jsonKind(value) === 'object') {
    for (const key of Object.keys(value)) {
      const node = jsonNode(value[key], ctx, 1);
      if (!node) break;
      matPut(root, easLinkName(key === '' ? '""' : key), node);
    }
  } else {
    const node = jsonNode(value, ctx, 1);
    if (node) matPut(root, easLinkName(String(fileName).replace(/\.[^.]*$/, '') || 'value'), node);
  }
  if (ctx.capped) root.attrs.note = `Only the first ${DOC_MAX_NODES.toLocaleString('en-US')} values and groups are shown.`;
  return { tree: root, datasets: ctx.datasets };
}

/**
 * Open a JSON file: its values written as an HDF5 file in memory and
 * registered under the file's own name. Does not refresh the tree.
 *
 * @param {string} fileName - Display name
 * @param {ArrayBuffer} buffer - The file's bytes
 * @param {string} [context] - Label for failure reporting
 * @returns {Promise<string[]>} The name it was registered under
 */
async function ingestJsonFile(fileName, buffer, context = 'ingestJsonFile') {
  docCheckSize(fileName, buffer);
  setFileLoadProgress(null, `${fileName} — reading it…`);
  await yieldForPaint();
  let text = docDecode(buffer);
  let value;
  let lenient = false;
  try {
    value = JSON.parse(text);
  } catch (_) {
    try {
      value = jsonParseLenient(text);
      lenient = true;
    } catch (err) {
      throw new Error(`${fileName} could not be read as JSON: ${err.message}.`);
    }
  }
  text = null;
  const { tree, datasets } = jsonTree(fileName, value, lenient);
  value = null;
  return docOpen(fileName, tree, datasets, context);
}
