/* ==========================================================================
   SMUI.HTML: HDF5 FILES AS TABLES (the reading, without the page)

   An HDF5 file is a tree of groups and datasets, and nothing in the format
   says which of its arrays make a table. These do, by the conventions of
   the programs that write them:

     a compound dataset      a row per element, a column per field (h5py's
                             structured arrays, PyTables tables): nested
                             fields as a.b, array fields as x[1], x[2] …
     vectors                 1-D datasets, a column each; vectors of one
                             length go side by side into one table (a
                             group of columns, a run's series)
     a matrix                2-D, its rows and columns (either way round);
                             column names from a names attribute or a
                             dimension scale
     a larger array          3-D and up, stacked: a row per value, with a
                             column per dimension saying where it was
     single values           scalars: a row each, name and value
     a pandas object         df.to_hdf (fixed and table formats): its own
                             columns, index and types

   Some files say more, and are read as they mean it:
     netCDF-4                dimensions are dimension scales (the time
                             of a variable is its first column), CF
                             "days since …" units are dates, _FillValue,
                             scale_factor and add_offset apply, char
                             arrays are text
     MATLAB v7.3 .mat        arrays come transposed (MATLAB is column-
                             major): rows as MATLAB has them; char is text,
                             logical is 0/1; cells, objects and tables are
                             MATLAB's own and not read
     Kompartment, Ecolego    /time is the first column of every table of
     and the HDF5 Browser    its length; a run's realisations ([times ×
                             runs], probabilistic) come a row per run, a
                             column per time, beside the sampled values;
                             a data file's lookup table comes with its
                             times (its index attribute), a parameter
                             with its distribution (pdf)

   The worker (smui-hdf5-worker.js) opens a file with h5wasm and calls
   inspect() and read(); the open dialog (smui-hdf5.js) calls plan() as
   boxes are ticked, so both load this file. Nothing here touches the page.

   A file is hostile input. Names and attributes come back as text only,
   and the page never puts them in as markup. pandas keeps column names and
   text columns as Python pickles: unpickle() is a reader of the pickle
   format that builds plain values and never calls anything, so a pickle
   cannot run code here. Sizes are checked before anything is read.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});

  /* ---- limits ------------------------------------------------------------- */
  const MAX_OBJECTS = 200000;       // objects listed from one file
  const MAX_CELLS = 50e6;           // values in one table
  const WIDE = 2000;                // a table wider than this is slow in the grid
  const DEFAULT_COLUMNS = 1000;     // ticked when the file opens, at most
  const MAX_TEXT = 1 << 20;         // characters of one text value
  const MAX_LEAVES = 4096;          // columns from one element (compound fields, array members)
  const CHUNK_BYTES = 8 << 20;      // read at a time
  const ATTR_TEXT = 4000;           // characters of an attribute kept

  /* The datatype classes, as HDF5 (and h5wasm's metadata) numbers them. */
  const T = { INTEGER: 0, FLOAT: 1, TIME: 2, STRING: 3, BITFIELD: 4, OPAQUE: 5, COMPOUND: 6, REFERENCE: 7, ENUM: 8, VLEN: 9, ARRAY: 10 };
  const UNREAD = {
    [T.TIME]: 'HDF5 time values', [T.OPAQUE]: 'opaque bytes', [T.REFERENCE]: 'references to other objects',
    [T.VLEN]: 'variable-length sequences',
  };

  /* The attributes inspect() reads the values of (the rest are only named). */
  const KNOWN = new Set([
    'unit', 'units', 'Unit', 'Units', 'long_name', 'description', 'Description', 'title', 'label', 'standard_name', 'lookup_table', 'pdf', 'reference',
    'time_dependent', 'probabilistic', 'n_iter', 'n_times', 'realisation', 'IndexLists', 'kind', 'block', 'name',
    'CLASS', 'NAME', '_FillValue', 'missing_value', 'scale_factor', 'add_offset', 'calendar', '_Unsigned', '_NCProperties',
    'MATLAB_class', 'MATLAB_empty', 'MATLAB_int_decode',
    'pandas_type', 'pandas_version', 'table_type', 'index_variety', 'columns_variety', 'axis0_variety', 'axis1_variety', 'nblocks', 'ndim', 'value_type', 'transposed', 'PSEUDOATOM',
    'nan_rep', 'non_index_axes', 'values_cols', 'data_columns', 'index_cols', 'levels', 'index_kind', 'info', 'encoding', 'tz', 'freq',
    'columns', 'column_names', 'colnames', 'names', 'fields', 'header', 'labels', 'variables',
    'Information', 'model', 'source', 'created_time', 'time_unit', 'solver', 'start_time', 'end_time', 'series',
  ]);
  // the attributes a column of names may be in, for a matrix
  const NAME_ATTRS = ['columns', 'column_names', 'colnames', 'names', 'fields', 'header', 'labels', 'variables'];
  // what a file says about itself, for the table's notes
  const ROOT_NOTES = ['title', 'description', 'Description', 'model', 'source', 'created_time', 'solver', 'time_unit', 'start_time', 'end_time', 'n_iter', 'realisation', 'Conventions', 'institution', 'history', 'comment', 'references'];

  const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });
  const isTrue = (v) => v === true || v === 1 || (typeof v === 'string' && /^(true|yes|1)$/i.test(v.trim())) || (Array.isArray(v) && v.length === 1 && isTrue(v[0]));
  const prod = (a) => a.reduce((x, y) => x * y, 1);
  const plural = (n, w) => `${n.toLocaleString('en-US')} ${w}${n === 1 ? '' : 's'}`;

  /* ---- what kind of file the first bytes say it is ------------------------- */
  const SIGNATURE = [0x89, 0x48, 0x44, 0x46, 0x0d, 0x0a, 0x1a, 0x0a];
  /* 'hdf5' (the signature at 0, or after a user block of 512, 1024, … bytes:
     MATLAB v7.3 keeps 512), 'netcdf3', 'mat5', 'hdf4' or null. */
  function sniff(u8) {
    const at = (p) => p + 8 <= u8.length && SIGNATURE.every((b, i) => u8[p + i] === b);
    if (at(0)) return 'hdf5';
    for (let p = 512; p + 8 <= u8.length; p *= 2) if (at(p)) return 'hdf5';
    if (u8[0] === 0x43 && u8[1] === 0x44 && u8[2] === 0x46 && [1, 2, 5].includes(u8[3])) return 'netcdf3';
    if (u8[0] === 0x0e && u8[1] === 0x03 && u8[2] === 0x13 && u8[3] === 0x01) return 'hdf4';
    const head = String.fromCharCode(...u8.subarray(0, 19));
    if (head === 'MATLAB 5.0 MAT-file') return 'mat5';
    return null;
  }

  /* ---- text ---------------------------------------------------------------- */
  const UTF8 = new TextDecoder('utf-8');
  const UTF8_STRICT = new TextDecoder('utf-8', { fatal: true });
  const LATIN = new TextDecoder('windows-1252');
  /* HDF5 knows two character sets, ASCII and UTF-8; bytes beyond ASCII in an
     "ASCII" string are almost always UTF-8 (h5py writes bytes so), else
     Latin-1. */
  function decodeText(bytes, cset) {
    let ascii = true;
    for (let i = 0; i < bytes.length; i++) if (bytes[i] > 0x7f) { ascii = false; break; }
    if (ascii) return bytes.length < 64 ? String.fromCharCode.apply(null, bytes) : LATIN.decode(bytes);
    if (cset === 1) return UTF8.decode(bytes);
    try { return UTF8_STRICT.decode(bytes); } catch (e) { return LATIN.decode(bytes); }
  }

  /* An attribute's value as plain data: numbers, texts and arrays of them
     (int64 as numbers; references and the like as null). */
  function plainAttr(v, depth = 0) {
    if (v == null || depth > 4) return null;
    if (typeof v === 'bigint') return Number(v);
    if (typeof v === 'string') return v.length > ATTR_TEXT ? `${v.slice(0, ATTR_TEXT)}…` : v;
    if (typeof v === 'number' || typeof v === 'boolean') return v;
    if (ArrayBuffer.isView(v)) return Array.from(v.subarray(0, 1000), (x) => (typeof x === 'bigint' ? Number(x) : x));
    if (Array.isArray(v)) return v.slice(0, 1000).map((x) => plainAttr(x, depth + 1));
    return null;
  }

  /* An attribute as one line of text, for the dialog and the notes. */
  function attrText(v) {
    if (v == null) return '';
    if (Array.isArray(v)) return v.length === 1 ? attrText(v[0]) : v.slice(0, 20).map(attrText).join(', ') + (v.length > 20 ? ', …' : '');
    if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(+v.toPrecision(10));
    return String(v).replace(/\s+/g, ' ').trim();
  }

  /* Markup in an attribute (Ecolego's and Kompartment's Information) as
     plain text: tags dropped, the common entities decoded. Only ever used
     as text. */
  function markupText(s) {
    return String(s).replace(/<(br|\/p|\/div|\/li|\/h\d)\b[^>]*>/gi, '\n').replace(/<[^>]*>/g, ' ')
      .replace(/&(#x[0-9a-f]+|#\d+|lt|gt|amp|quot|apos|nbsp);/gi, (m, e) => {
        const k = e.toLowerCase();
        if (k[0] === '#') { const c = k[1] === 'x' ? parseInt(k.slice(2), 16) : parseInt(k.slice(1), 10); return c > 0 && c < 0x110000 ? String.fromCodePoint(c) : ' '; }
        return { lt: '<', gt: '>', amp: '&', quot: '"', apos: "'", nbsp: ' ' }[k];
      })
      .split('\n').map((l) => l.replace(/\s+/g, ' ').trim()).filter(Boolean).join(' / ');
  }

  /* ---- Python pickles, read and never run --------------------------------
     pandas writes column names, index names and text columns as pickles.
     This reads the format into plain values: str and bytes, numbers, None,
     True and False, lists and tuples (arrays), dicts (Map) and sets. What
     would make or call an object -- a global, REDUCE, BUILD, NEWOBJ -- is
     only recorded: { $global: 'numpy.dtype' }, { $call, args, $state }. Nothing
     is looked up and nothing is called, so a pickle can do nothing here but
     describe data. The few calls the older protocols spell plain data with
     (bytes as _codecs.encode(text, 'latin1'), a set as set([...]), an
     OrderedDict) are made into that data by name (PLAIN_CALLS), which is a
     reading too. Extension codes, persistent ids and out-of-band buffers
     stop the reading. */
  const latinBytes = (s) => (typeof s === 'string' && [...s].every((c) => c.charCodeAt(0) < 256) ? Uint8Array.from(s, (c) => c.charCodeAt(0)) : null);
  const PLAIN_CALLS = {
    '_codecs.encode': (a) => (a.length === 2 && /^latin[-_]?1$/i.test(String(a[1])) ? latinBytes(a[0]) : null),
    'builtins.set': (a) => (a.length === 0 ? [] : Array.isArray(a[0]) ? a[0].slice() : null),
    'builtins.frozenset': (a) => (a.length === 0 ? [] : Array.isArray(a[0]) ? a[0].slice() : null),
    'builtins.bytearray': (a) => (a.length === 0 ? new Uint8Array(0) : a[0] instanceof Uint8Array ? a[0].slice() : a.length === 2 ? latinBytes(a[0]) : null),
    'builtins.bytes': (a) => (a.length === 0 ? new Uint8Array(0) : a[0] instanceof Uint8Array ? a[0].slice() : null),
    'collections.OrderedDict': (a) => (a.length === 0 ? new Map() : null),
  };
  for (const k of ['set', 'frozenset', 'bytearray', 'bytes']) PLAIN_CALLS[`__builtin__.${k}`] = PLAIN_CALLS[`builtins.${k}`];
  /* A call the pickle asks for: the plain value it stands for when it is
     one of PLAIN_CALLS, else only its record. */
  function callRecord(fn, args, extra = {}) {
    const make = fn && typeof fn.$global === 'string' && Object.prototype.hasOwnProperty.call(PLAIN_CALLS, fn.$global) ? PLAIN_CALLS[fn.$global] : null;
    const v = make && Array.isArray(args) ? make(args) : null;
    return v != null ? v : { $call: fn, args, ...extra };
  }

  function unpickle(input, { maxOps = 5e7 } = {}) {
    const u8 = typeof input === 'string' ? Uint8Array.from(input, (c) => c.charCodeAt(0) & 0xff) : input;
    const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
    let p = 0, ops = 0;
    let stack = [];
    const marks = [];
    const memo = new Map();
    const need = (n) => { if (p + n > u8.length) throw new Error('pickle: cut short'); };
    const line = () => {
      const e = u8.indexOf(0x0a, p);
      if (e < 0) throw new Error('pickle: cut short');
      const s = LATIN.decode(u8.subarray(p, e));
      p = e + 1;
      return s;
    };
    const take = (n) => { need(n); const b = u8.subarray(p, p + n); p += n; return b; };
    const popMark = () => {
      if (!marks.length) throw new Error('pickle: no mark');
      const items = stack;
      stack = marks.pop();
      return items;
    };
    const top = () => { if (!stack.length) throw new Error('pickle: empty stack'); return stack[stack.length - 1]; };
    const pop = () => { if (!stack.length) throw new Error('pickle: empty stack'); return stack.pop(); };
    const tuple = (a) => Object.freeze(a);
    const len8 = () => { need(8); const lo = dv.getUint32(p, true), hi = dv.getUint32(p + 4, true); p += 8; if (hi) throw new Error('pickle: too large'); return lo; };
    const longOf = (b) => {
      // little-endian two's complement
      let v = 0n;
      for (let i = b.length - 1; i >= 0; i--) v = (v << 8n) | BigInt(b[i]);
      if (b.length && b[b.length - 1] & 0x80) v -= 1n << BigInt(8 * b.length);
      return Number(v);
    };
    const textRepr = (s) => {
      // the quoted text of protocol 0's STRING: Python's repr of a str
      const q = s[0];
      let body = s.slice(1, s.lastIndexOf(q));
      body = body.replace(/\\(x[0-9a-fA-F]{2}|[0-7]{1,3}|.)/g, (m, e) => {
        if (e[0] === 'x') return String.fromCharCode(parseInt(e.slice(1), 16));
        if (/^[0-7]/.test(e)) return String.fromCharCode(parseInt(e, 8) & 0xff);
        return { n: '\n', t: '\t', r: '\r', '\\': '\\', "'": "'", '"': '"', a: '\x07', b: '\b', f: '\f', v: '\v' }[e] ?? `\\${e}`;
      });
      return body;
    };
    const rawUnicode = (s) => s.replace(/\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})/g, (m, a, b) => String.fromCodePoint(parseInt(a || b, 16)));
    const setItems = (d, items) => {
      if (!(d instanceof Map)) throw new Error('pickle: SETITEMS on a non-dict');
      for (let i = 0; i + 1 < items.length; i += 2) d.set(items[i], items[i + 1]);
    };
    const appendTo = (l, items) => {
      if (Array.isArray(l) && !Object.isFrozen(l)) l.push(...items);
      else if (l && l.$call) (l.$items || (l.$items = [])).push(...items);
      else throw new Error('pickle: APPEND to a non-list');
    };
    for (;;) {
      if (++ops > maxOps) throw new Error('pickle: too long');
      need(1);
      const op = u8[p++];
      switch (op) {
        case 0x80: take(1); break;                                   // PROTO
        case 0x95: take(8); break;                                   // FRAME
        case 0x2e: if (stack.length !== 1) throw new Error('pickle: bad stop'); return stack[0];   // STOP .
        case 0x28: marks.push(stack); stack = []; break;             // MARK (
        case 0x30: pop(); break;                                     // POP 0
        case 0x31: popMark(); break;                                 // POP_MARK 1
        case 0x32: stack.push(top()); break;                         // DUP 2
        case 0x4e: stack.push(null); break;                          // NONE N
        case 0x88: stack.push(true); break;                          // NEWTRUE
        case 0x89: stack.push(false); break;                         // NEWFALSE
        case 0x49: {                                                 // INT I
          const s = line();
          stack.push(s === '01' ? true : s === '00' ? false : Number(s));
          break;
        }
        case 0x4a: need(4); stack.push(dv.getInt32(p, true)); p += 4; break;       // BININT J
        case 0x4b: need(1); stack.push(u8[p++]); break;                             // BININT1 K
        case 0x4d: need(2); stack.push(dv.getUint16(p, true)); p += 2; break;      // BININT2 M
        case 0x4c: stack.push(Number(line().replace(/L$/, ''))); break;             // LONG L
        case 0x8a: { need(1); const n = u8[p++]; stack.push(longOf(take(n))); break; }      // LONG1
        case 0x8b: { need(4); const n = dv.getInt32(p, true); p += 4; if (n < 0) throw new Error('pickle: bad length'); stack.push(longOf(take(n))); break; }   // LONG4
        case 0x46: stack.push(Number(line())); break;                               // FLOAT F
        case 0x47: need(8); stack.push(dv.getFloat64(p, false)); p += 8; break;    // BINFLOAT G
        case 0x53: stack.push(textRepr(line())); break;                             // STRING S
        case 0x54: { need(4); const n = dv.getInt32(p, true); p += 4; if (n < 0) throw new Error('pickle: bad length'); stack.push(LATIN.decode(take(n))); break; }   // BINSTRING T
        case 0x55: { need(1); const n = u8[p++]; stack.push(LATIN.decode(take(n))); break; }      // SHORT_BINSTRING U
        case 0x56: stack.push(rawUnicode(line())); break;                           // UNICODE V
        case 0x58: { need(4); const n = dv.getUint32(p, true); p += 4; stack.push(UTF8.decode(take(n))); break; }   // BINUNICODE X
        case 0x8c: { need(1); const n = u8[p++]; stack.push(UTF8.decode(take(n))); break; }      // SHORT_BINUNICODE
        case 0x8d: { const n = len8(); stack.push(UTF8.decode(take(n))); break; }                // BINUNICODE8
        case 0x42: { need(4); const n = dv.getUint32(p, true); p += 4; stack.push(take(n).slice()); break; }   // BINBYTES B
        case 0x43: { need(1); const n = u8[p++]; stack.push(take(n).slice()); break; }            // SHORT_BINBYTES C
        case 0x8e: case 0x96: { const n = len8(); stack.push(take(n).slice()); break; }           // BINBYTES8, BYTEARRAY8
        case 0x29: stack.push(tuple([])); break;                                    // EMPTY_TUPLE )
        case 0x85: stack.push(tuple([pop()])); break;                               // TUPLE1
        case 0x86: { const b = pop(), a = pop(); stack.push(tuple([a, b])); break; }               // TUPLE2
        case 0x87: { const c = pop(), b = pop(), a = pop(); stack.push(tuple([a, b, c])); break; } // TUPLE3
        // (popMark replaces the stack: take its items first, then push)
        case 0x74: { const items = popMark(); stack.push(tuple(items)); break; }    // TUPLE t
        case 0x5d: stack.push([]); break;                                           // EMPTY_LIST ]
        case 0x6c: { const items = popMark(); stack.push(items); break; }           // LIST l
        case 0x61: { const v = pop(); appendTo(top(), [v]); break; }                // APPEND a
        case 0x65: { const items = popMark(); appendTo(top(), items); break; }      // APPENDS e
        case 0x7d: stack.push(new Map()); break;                                    // EMPTY_DICT }
        case 0x64: { const items = popMark(); const d = new Map(); setItems(d, items); stack.push(d); break; }   // DICT d
        case 0x73: { const v = pop(), k = pop(); setItems(top(), [k, v]); break; }  // SETITEM s
        case 0x75: { const items = popMark(); setItems(top(), items); break; }      // SETITEMS u
        case 0x8f: stack.push([]); break;                                           // EMPTY_SET
        case 0x90: { const items = popMark(); const s = top(); if (!Array.isArray(s)) throw new Error('pickle: ADDITEMS to a non-set'); s.push(...items); break; }   // ADDITEMS
        case 0x91: { const items = popMark(); stack.push(items); break; }           // FROZENSET
        case 0x63: { const mod = line(), name = line(); stack.push({ $global: `${mod}.${name}` }); break; }     // GLOBAL c
        case 0x93: { const name = pop(), mod = pop(); stack.push({ $global: `${mod}.${name}` }); break; }      // STACK_GLOBAL
        case 0x52: { const args = pop(), fn = pop(); stack.push(callRecord(fn, args)); break; }   // REDUCE R
        case 0x81: { const args = pop(), cls = pop(); stack.push(callRecord(cls, args, { $new: true })); break; }   // NEWOBJ
        case 0x92: { const kw = pop(), args = pop(), cls = pop(); stack.push(callRecord(cls, args, { kwargs: kw, $new: true })); break; }   // NEWOBJ_EX
        case 0x62: {                                                                // BUILD b
          const state = pop();
          const obj = top();
          if (obj && typeof obj === 'object' && !Array.isArray(obj) && !(obj instanceof Map) && !ArrayBuffer.isView(obj)) obj.$state = state;
          else stack[stack.length - 1] = { $call: { $global: 'builtins.object' }, args: [obj], $state: state };
          break;
        }
        case 0x69: { const mod = line(), name = line(); const args = popMark(); stack.push({ $call: { $global: `${mod}.${name}` }, args }); break; }   // INST i
        case 0x6f: { const items = popMark(); stack.push({ $call: items[0], args: items.slice(1) }); break; }   // OBJ o
        case 0x70: memo.set(Number(line()), top()); break;                          // PUT p
        case 0x71: need(1); memo.set(u8[p++], top()); break;                        // BINPUT q
        case 0x72: need(4); memo.set(dv.getUint32(p, true), top()); p += 4; break; // LONG_BINPUT r
        case 0x94: memo.set(memo.size, top()); break;                               // MEMOIZE
        case 0x67: case 0x68: case 0x6a: {                                          // GET g, BINGET h, LONG_BINGET j
          let k;
          if (op === 0x67) k = Number(line());
          else if (op === 0x68) { need(1); k = u8[p++]; } else { need(4); k = dv.getUint32(p, true); p += 4; }
          if (!memo.has(k)) throw new Error('pickle: unknown memo');
          stack.push(memo.get(k));
          break;
        }
        default:
          throw new Error(`pickle: unsupported opcode 0x${op.toString(16)}`);
      }
    }
  }

  /* A numpy array as a pickle describes it (numpy's _reconstruct, then its
     state): { shape, dtype, fortran, data }, data an array of the objects of
     an object array (in C order) or the bytes of any other. Null when the
     value is not one. */
  function numpyArray(v) {
    if (!v || !v.$call || !/^numpy\.(_?core\.)?multiarray\._reconstruct$/.test(v.$call.$global || '')) return null;
    const st = v.$state;
    if (!Array.isArray(st) || st.length < 5) return null;
    const dt = st[2];
    const descr = dt && dt.$call && /^numpy\.(dtype|core\.multiarray\.dtype)$/.test(dt.$call.$global || '') && Array.isArray(dt.args) ? String(dt.args[0]) : null;
    return { shape: Array.isArray(st[1]) ? st[1].map(Number) : [], dtype: descr, fortran: !!st[3], data: st[4] };
  }

  /* ---- datatypes ------------------------------------------------------------
     A dataset's elements as leaves: each value one element holds -- a
     number, a text, a level of an enumeration -- at its byte offset. A
     compound gives a leaf per field (nested names joined with a dot), an
     array type a leaf per member, x[1], x[2] …, numbered from 1. */
  function typeLeaves(md) {
    const leaves = [], bad = [];
    let vlen = false;
    const walk = (t, name, offset, depth) => {
      if (depth > 12 || leaves.length >= MAX_LEAVES) { bad.push({ name, why: 'too deeply nested or too many fields' }); return; }
      switch (t.type) {
        case T.INTEGER: case T.BITFIELD:
          if (![1, 2, 4, 8].includes(t.size)) { bad.push({ name, why: `${t.size * 8}-bit integers` }); return; }
          leaves.push({ name, offset, size: t.size, kind: t.type === T.INTEGER && t.signed ? 'int' : 'uint', le: t.littleEndian !== false });
          return;
        case T.FLOAT:
          if (![2, 4, 8].includes(t.size)) { bad.push({ name, why: `${t.size * 8}-bit floating point` }); return; }
          leaves.push({ name, offset, size: t.size, kind: 'float', le: t.littleEndian !== false });
          return;
        case T.STRING:
          if (t.vlen) vlen = true;
          leaves.push({ name, offset, size: t.size, kind: 'text', vlen: !!t.vlen, cset: t.cset, pad: t.strpad });
          return;
        case T.ENUM: {
          const members = (t.enum_type && t.enum_type.members) || {};
          leaves.push({ name, offset, size: t.size, kind: 'enum', signed: !!t.signed, le: t.littleEndian !== false, members });
          return;
        }
        case T.COMPOUND:
          for (const m of (t.compound_type && t.compound_type.members) || []) walk(m, name ? `${name}.${m.name}` : String(m.name), offset + m.offset, depth + 1);
          return;
        case T.ARRAY: {
          const a = t.array_type;
          const shape = (a && a.shape) || [];
          const k = prod(shape);
          if (!a || k > MAX_LEAVES) { bad.push({ name, why: 'an array type too large to spread into columns' }); return; }
          const base = { ...a, shape: undefined };
          for (let i = 0; i < k; i++) {
            let r = i;
            const idx = shape.map((d, j) => { const s = prod(shape.slice(j + 1)); const q = Math.floor(r / s); r -= q * s; return q + 1; });
            walk(base, `${name}[${idx.join(',')}]`, offset + i * a.size, depth + 1);
          }
          return;
        }
        default:
          if (t.type === T.VLEN) vlen = true;
          bad.push({ name, why: UNREAD[t.type] || 'an unknown datatype' });
      }
    };
    walk(md, '', 0, 0);
    /* Byte order. h5wasm reads a dataset into native (little-endian) order
       when the whole type has one order; a compound whose members differ
       comes as it is stored, each member in its own. */
    const nums = leaves.filter((l) => l.kind !== 'text');
    const mixed = md.type === T.COMPOUND && nums.some((l) => l.le) && nums.some((l) => !l.le);
    if (!mixed) for (const l of nums) l.le = true;
    return { leaves, bad, vlen, compound: md.type === T.COMPOUND };
  }

  function typeText(md, leaves, matlab) {
    if (matlab === 'char') return 'MATLAB text';
    if (matlab === 'logical') return 'MATLAB logical';
    const t = md.type;
    if (t === T.COMPOUND) return `compound (${plural(leaves.length, 'field')})`;
    if (t === T.STRING) return 'text';
    if (t === T.ENUM) {
      const m = (md.enum_type && md.enum_type.members) || {};
      const k = Object.keys(m);
      return k.length === 2 && m.FALSE === 0 && m.TRUE === 1 ? 'true/false' : `enum (${plural(k.length, 'level')})`;
    }
    if (t === T.FLOAT) return `float${md.size * 8}`;
    if (t === T.INTEGER) return `${md.signed ? 'int' : 'uint'}${md.size * 8}`;
    if (t === T.BITFIELD) return `bitfield${md.size * 8}`;
    if (t === T.ARRAY) return `array of ${leaves.length}`;
    return UNREAD[t] || 'unknown';
  }

  /* Reading one leaf from a buffer: (dv, base) -> a number, a text or null.
     heap is the memory a variable-length text points into. */
  function leafReader(leaf, heap) {
    const o = leaf.offset, le = leaf.le;
    if (leaf.kind === 'float') {
      if (leaf.size === 8) return (dv, b) => dv.getFloat64(b + o, le);
      if (leaf.size === 4) return (dv, b) => dv.getFloat32(b + o, le);
      return (dv, b) => half(dv.getUint16(b + o, le));
    }
    if (leaf.kind === 'int' || leaf.kind === 'uint' || leaf.kind === 'enum') {
      const signed = leaf.kind === 'int' || (leaf.kind === 'enum' && leaf.signed);
      switch (leaf.size) {
        case 1: return signed ? (dv, b) => dv.getInt8(b + o) : (dv, b) => dv.getUint8(b + o);
        case 2: return signed ? (dv, b) => dv.getInt16(b + o, le) : (dv, b) => dv.getUint16(b + o, le);
        case 4: return signed ? (dv, b) => dv.getInt32(b + o, le) : (dv, b) => dv.getUint32(b + o, le);
        default: return signed ? (dv, b) => Number(dv.getBigInt64(b + o, le)) : (dv, b) => Number(dv.getBigUint64(b + o, le));
      }
    }
    if (leaf.kind === 'text') {
      if (leaf.vlen) {
        return (dv, b) => {
          const ptr = dv.getUint32(b + o, true);
          if (!ptr) return null;
          let end = heap.indexOf(0, ptr);
          if (end < 0 || end - ptr > MAX_TEXT) end = Math.min(heap.length, ptr + MAX_TEXT);
          const s = decodeText(heap.subarray(ptr, end), leaf.cset);
          return s === '' ? null : s;
        };
      }
      const size = leaf.size, space = leaf.pad === 2;
      return (dv, b) => {
        const start = dv.byteOffset + b + o;
        const all = new Uint8Array(dv.buffer, start, size);
        let n = all.indexOf(0);
        if (n < 0) n = size;
        if (space) while (n > 0 && all[n - 1] === 0x20) n--;
        if (!n) return null;
        return decodeText(all.subarray(0, n), leaf.cset);
      };
    }
    return () => null;
  }

  /* An IEEE half (float16) as a number. */
  function half(h) {
    const s = h & 0x8000 ? -1 : 1, e = (h >> 10) & 0x1f, f = h & 0x3ff;
    if (e === 0) return s * f * 2 ** -24;
    if (e === 31) return f ? NaN : s * Infinity;
    return s * (1 + f / 1024) * 2 ** (e - 15);
  }

  /* ---- the h5wasm side --------------------------------------------------------
     What the rest of this file asks of an open file, over h5wasm's Module
     (the worker's, or the Node build the tests use). ensurePlugins(path) is
     the host's: it fetches the compression plugins a dataset needs. */
  function ioFor(h5wasm, Module, file, { ensurePlugins = null } = {}) {
    const fid = file.file_id;
    const holder = (path) => new h5wasm.Group(fid, path);
    return {
      names() { return Module.get_names(fid, '/', true); },
      kind(path) {
        let t;
        try { t = Module.get_type(fid, path); } catch (e) { return 'missing'; }
        return t === Module.H5G_GROUP ? 'group' : t === Module.H5G_DATASET ? 'dataset' : t === Module.H5G_TYPE ? 'datatype'
          : t === Module.H5G_LINK ? 'broken' : t === Module.H5G_UDLINK ? 'external' : 'missing';
      },
      softTarget(path) { try { return Module.get_symbolic_link(fid, path) || null; } catch (e) { return null; } },
      external(path) { try { const x = Module.get_external_link(fid, path); return x ? `${x.filename}:${x.obj_path}` : null; } catch (e) { return null; } },
      meta(path) { return Module.get_dataset_metadata(fid, path); },
      attrNames(path) { try { return Module.get_attribute_names(fid, path) || []; } catch (e) { return []; } },
      attr(path, name) { try { return plainAttr(holder(path).get_attribute(name, false)); } catch (e) { return null; } },
      scales(path, dim) { try { return Module.get_attached_scales(fid, path, dim) || []; } catch (e) { return []; } },
      filters(path) { try { return (Module.get_dataset_filters(fid, path) || []).map((f) => ({ id: f.id, name: f.name })); } catch (e) { return []; } },
      async ensurePlugins(path) { if (ensurePlugins) await ensurePlugins(path); },
      /* Reads count positions from start along dimension axis (the
         dimensions before it are 1), every other dimension whole, and hands
         the bytes to fn(dv, heap) before they are freed. */
      read(path, md, axis, start, count, fn) {
        const shape = md.shape.map(Number);
        const per = md.size * prod(shape.filter((_, i) => i !== axis)) * count;
        const nbytes = Math.max(1, shape.length ? per : md.size);
        if (nbytes > Module.MAXIMUM_MEMORY) throw new Error('too large to read at once');
        const ptr = Module._malloc(nbytes);
        if (!ptr) throw new Error('out of memory');
        const cnt = shape.length ? shape.map((d, i) => BigInt(i === axis ? count : d)) : null;
        const off = shape.length ? shape.map((d, i) => BigInt(i === axis ? start : 0)) : null;
        const str = shape.length ? shape.map(() => 1n) : null;
        const vlen = md.vlen || md.type === T.VLEN || typeLeaves(md).vlen;
        try {
          Module.get_dataset_data(fid, path, cnt, off, str, BigInt(ptr));
          const heap = Module.HEAPU8;
          fn(new DataView(heap.buffer, ptr, nbytes), heap);
        } finally {
          if (vlen) {
            try {
              if (cnt) Module.reclaim_vlen_memory_count(fid, path, '', BigInt(ptr), cnt);
              else Module.reclaim_vlen_memory(fid, path, '', BigInt(ptr));
            } catch (e) { /* the memory is freed below either way */ }
          }
          Module._free(ptr);
        }
      },
    };
  }

  /* Every element of a dataset, chunk by chunk along its first dimension
     that is not 1: each(dv, heap, first, count, elementSize) with first the
     index of the chunk's first element in the whole array (C order). */
  async function eachChunk(io, node, each) {
    const md = node.md;
    if (!md.shape || !md.shape.length) { io.read(node.path, md, 0, 0, 1, (dv, heap) => each(dv, heap, 0, 1, md.size)); return; }
    const shape = md.shape.map(Number);
    let axis = shape.findIndex((d) => d > 1);
    if (axis < 0) axis = shape.length - 1;
    const per = prod(shape.slice(axis + 1));          // elements per position along axis
    const step = Math.max(1, Math.floor(CHUNK_BYTES / Math.max(1, per * md.size)));
    await io.ensurePlugins(node.path);
    for (let s = 0; s < shape[axis]; s += step) {
      const c = Math.min(step, shape[axis] - s);
      io.read(node.path, md, axis, s, c, (dv, heap) => each(dv, heap, s * per, c * per, md.size));
    }
  }

  /* ---- inspect: the file's tree, each dataset classified ---------------------
     A node: { id, path, name, parent, depth, children, kind ('group',
     'dataset', 'link', 'external', 'broken', 'datatype'), attrs (the KNOWN
     ones' values), attrNames, and for a dataset shape, typeText, form
     ('vector', 'matrix', 'compound', 'cube', 'scalar', 'pandas' on a group),
     rows and cols (as it opens), readable and why not, hidden (a part of a
     pandas object, a netCDF dimension, MATLAB's own), key (a row key: the
     file's time or a dimension scale) and transposed (opens transposed). */
  async function inspect(io, { maxObjects = MAX_OBJECTS, onProgress = null } = {}) {
    const all = io.names();
    const list = all.length > maxObjects ? all.slice(0, maxObjects) : all;
    const rootNode = { id: 0, path: '/', name: '/', parent: -1, depth: 0, children: [], kind: 'group' };
    describeAttrs(io, rootNode);
    const nodes = [rootNode];
    const at = new Map([['/', rootNode]]);
    for (let i = 0; i < list.length; i++) {
      const path = `/${list[i]}`;
      const cut = path.lastIndexOf('/');
      const parent = at.get(cut === 0 ? '/' : path.slice(0, cut));
      if (!parent || parent.kind !== 'group') continue;
      const node = { id: nodes.length, path, name: path.slice(cut + 1), parent: parent.id, depth: parent.depth + 1, children: [] };
      nodes.push(node);
      parent.children.push(node.id);
      at.set(path, node);
      describe(io, node);
      if (onProgress && i % 200 === 0) onProgress(i, list.length);
    }
    const info = { objects: all.length, listed: list.length, capped: all.length > list.length };
    await classify(io, nodes, at, info);
    // children in natural order (N2 before N10), the tree's order and the columns'
    let order = 0;
    const visit = (n) => {
      n.order = order++;
      n.children.sort((a, b) => collator.compare(nodes[a].name, nodes[b].name));
      for (const c of n.children) visit(nodes[c]);
    };
    visit(rootNode);
    return { nodes, info };
  }

  function describeAttrs(io, node) {
    node.attrNames = io.attrNames(node.path);
    node.attrs = {};
    for (const a of node.attrNames) if (KNOWN.has(a)) node.attrs[a] = io.attr(node.path, a);
    // a lookup table's times: Kompartment's say lookup_table, the HDF5
    // Browser's have a pdf per point (a list); a result series' index is its label
    const pdfList = typeof node.attrs.pdf === 'string' && /^\s*\[/.test(node.attrs.pdf);
    if ((node.attrs.lookup_table != null || pdfList) && node.attrNames.includes('index')) node.attrs.index = io.attr(node.path, 'index');
  }

  function describe(io, node) {
    let kind = io.kind(node.path);
    if (kind === 'group' || kind === 'dataset' || kind === 'broken') {
      const target = io.softTarget(node.path);
      if (target) { node.kind = kind === 'broken' ? 'broken' : 'link'; node.target = target; node.attrs = {}; node.attrNames = []; return; }
    }
    node.kind = kind;
    if (kind === 'external') { node.target = io.external(node.path); node.attrs = {}; node.attrNames = []; return; }
    if (kind !== 'group' && kind !== 'dataset') { node.attrs = {}; node.attrNames = []; return; }
    describeAttrs(io, node);
    if (kind === 'group') return;
    let md;
    try { md = io.meta(node.path); } catch (e) { node.md = null; node.why = `could not be read: ${firstLine(e)}`; return; }
    node.md = md;
    node.shape = md.shape ? md.shape.map(Number) : null;
    node.filters = io.filters(node.path).map((f) => f.id);
  }

  /* An error as one line. HDF5's own are a stack of frames: the one that
     says what is missing (a filter) or else the deepest frame's words. */
  function firstLine(e) {
    const text = String((e && e.message) || e);
    const filter = /required filter '([^']+)' is not registered/.exec(text);
    if (filter) return `compressed with ${filter[1]}, and its decoder did not load`;
    const frames = [...text.matchAll(/#\d+: .*?\(\): ([^\n]+)/g)].map((m) => m[1].trim());
    if (frames.length) return frames[frames.length - 1];
    return text.split('\n').map((l) => l.trim()).filter(Boolean).pop() || 'an error';
  }

  async function classify(io, nodes, at, info) {
    const root = nodes[0];
    const ra = root.attrs;
    info.netcdf = ra._NCProperties != null;
    // every dataset's form, size and type (the parts of a pandas object too:
    // its reader uses them)
    for (const n of nodes) if (n.kind === 'dataset') classifyDataset(n);
    // MATLAB's own groups, and PyTables' indexes, are not data
    for (const n of nodes) {
      if (n.kind === 'group' && (/^#(refs|subsystem)#$/.test(n.name) || /^_i_/.test(n.name))) hideBelow(nodes, n, 'internal');
    }
    // pandas objects: the group is the table, its parts are hidden
    for (const n of nodes) {
      if (n.kind !== 'group' || n.hidden || !n.attrs.pandas_type) continue;
      await pandasInspect(io, nodes, at, n);
      for (const c of n.children) hideBelow(nodes, nodes[c], 'pandas');
    }
    // dimension scales: what each dimension of a dataset is measured in
    for (const n of nodes) {
      if (n.kind !== 'dataset' || n.hidden || !n.md) continue;
      if (n.attrs.CLASS === 'DIMENSION_SCALE') {
        n.isScale = true;
        n.scaleName = typeof n.attrs.NAME === 'string' && n.attrs.NAME ? n.attrs.NAME : n.name;
        if (/^This is a netCDF dimension but not a netCDF variable/.test(n.scaleName)) { n.hidden = 'netcdf-dimension'; n.readable = false; }
      }
    }
    for (const n of nodes) {
      if (n.kind !== 'dataset' || n.hidden || !n.md || !n.attrNames.includes('DIMENSION_LIST') || !n.shape) continue;
      n.scales = n.shape.map((_, d) => {
        const s = io.scales(n.path, d)[0];
        const sn = s ? at.get(s.startsWith('/') ? s : `/${s}`) : null;
        return sn && !sn.hidden && sn.readable ? sn.id : null;
      });
    }
    // the row keys: a dimension scale, and the file's time (Kompartment's,
    // Ecolego's and the HDF5 Browser's /time)
    for (const n of nodes) {
      if (n.kind !== 'dataset' || n.hidden || !n.readable || n.form !== 'vector') continue;
      if (n.isScale || (n.parent === 0 && /^(time|times)$/i.test(n.name) && n.numeric)) n.key = true;
    }
    const time = root.children.map((c) => nodes[c]).find((n) => n.key && /^(time|times)$/i.test(n.name)) || null;
    info.timeKey = time ? time.id : null;
    info.results = !!time && nodes.some((n) => n.attrs && (n.attrs.time_dependent != null || n.attrs.IndexLists != null));
    // a run's index lists are the file's vocabulary, not its data
    if (info.results) {
      const lists = root.children.map((c) => nodes[c]).find((n) => n.kind === 'group' && n.name === 'IndexLists');
      if (lists) markBelow(nodes, lists, 'meta');
    }
    // the HDF5 Browser's probabilistic time: [steps, iterations padded], its
    // n_times the steps each iteration has; a series of that shape is laid
    // out alike (a column per iteration, the steps after its last missing)
    const rt = root.children.map((c) => nodes[c]).find((n) => n.form === 'matrix' && /^(time|times)$/i.test(n.name) && isTrue(n.attrs.probabilistic) && Array.isArray(n.attrs.n_times));
    if (rt) {
      const steps = rt.attrs.n_times.map(Number);
      if (steps.length && steps.length <= rt.dims[1] && steps.every((k) => Number.isInteger(k) && k >= 0 && k <= rt.dims[0])) {
        for (const n of nodes) if (n.form === 'matrix' && n.dims[0] === rt.dims[0] && n.dims[1] === rt.dims[1]) { n.ragged = steps; n.cols = steps.length; }
      }
    }
    // a run's realisations: a series [times, runs] marked probabilistic (a
    // group's flags hold for what is in it, as the HDF5 Browser reads them);
    // its times are its first dimension's scale, else the file's /time
    const flag = (n, k) => (n.attrs[k] != null ? n.attrs[k] : n.parent >= 0 ? nodes[n.parent].attrs[k] : null);
    for (const n of nodes) {
      if (n.form !== 'matrix' || n.ragged) continue;
      const td = flag(n, 'time_dependent');
      const sid = n.scales && n.kept ? n.scales[n.kept[0]] : null;
      const own = sid != null && nodes[sid].key ? nodes[sid] : time;
      n.realisations = !!own && isTrue(flag(n, 'probabilistic')) && (td == null || isTrue(td)) && n.dims[0] === own.rows;
      if (n.realisations) n.timeOf = own.id;
    }
    // which way round a matrix opens
    for (const n of nodes) {
      if (n.form !== 'matrix') continue;
      if (n.matlab) n.transposed = true;          // MATLAB's rows are HDF5's second dimension
      else n.transposed = !!n.realisations;       // a row per realisation, a column per time
    }
    // the file's own description, for the notes
    const notes = [];
    for (const k of ROOT_NOTES) if (ra[k] != null && attrText(ra[k])) notes.push(`${k}: ${attrText(ra[k])}`);
    if (typeof ra.Information === 'string' && ra.Information.trim()) notes.push(markupText(ra.Information).slice(0, 600));
    info.notes = notes.join('; ');
    info.matlab = nodes.some((n) => n.matlab);
  }

  function hideBelow(nodes, n, why) {
    n.hidden = why;
    for (const c of n.children) hideBelow(nodes, nodes[c], why);
  }
  function markBelow(nodes, n, mark) {
    n.meta = mark;
    for (const c of n.children) markBelow(nodes, nodes[c], mark);
  }

  /* A dataset's form, size and type, and whether it can be read. */
  function classifyDataset(n) {
    n.readable = false;
    if (!n.md) return;
    const md = n.md;
    const mcls = typeof n.attrs.MATLAB_class === 'string' ? n.attrs.MATLAB_class : null;
    if (mcls) {
      n.matlab = mcls;
      if (isTrue(n.attrs.MATLAB_empty)) { n.why = 'an empty MATLAB array'; return; }
      if (!/^(double|single|u?int(8|16|32|64)|logical|char)$/.test(mcls)) { n.why = `a MATLAB ${mcls} (not read: MATLAB's own format)`; return; }
    }
    const { leaves, bad, vlen, compound } = typeLeaves(md);
    n.leaves = leaves;
    n.badLeaves = bad;
    n.vlen = vlen;
    n.typeText = typeText(md, leaves, mcls);
    if (!leaves.length) { n.why = bad.length ? `${bad[0].why} (not read)` : 'nothing to read'; return; }
    if (!n.shape) { n.why = 'empty (no dataspace)'; return; }
    if (n.shape.some((d) => d === 0)) { n.why = 'empty'; return; }
    if (n.filters && n.filters.some((id) => !FILTERS_OK.has(id) && !PLUGIN_FILTERS.has(id))) { n.why = `compressed with a filter this page has no decoder for (${n.filters.join(', ')})`; return; }
    const one = leaves.length === 1 && !compound;
    const leaf = leaves[0];
    // the dimensions that are not 1 (kept: where each is in the shape)
    let kept = n.shape.map((d, i) => i).filter((i) => n.shape[i] !== 1);
    // text as an array of characters: netCDF's char arrays (one byte
    // each, the text along the last dimension), MATLAB's char (UTF-16 code
    // units, down its first)
    if (one && leaf.kind === 'text' && !leaf.vlen && leaf.size === 1 && n.shape.length >= 1) { n.chars = 'last'; kept = kept.filter((i) => i !== n.shape.length - 1); }
    else if (mcls === 'char' && one && (leaf.kind === 'uint' || leaf.kind === 'int') && n.shape.length >= 2) { n.chars = 'matlab'; kept = kept.filter((i) => i !== 0); }
    const dims = kept.map((i) => n.shape[i]);
    n.kept = kept;
    n.dims = dims;
    n.numeric = one && leaf.kind !== 'text' && !n.chars;
    if (!dims.length) { n.form = compound ? 'compound' : 'scalar'; n.rows = 1; n.cols = compound ? leaves.length : 1; }
    else if (dims.length === 1) { n.form = one ? 'vector' : 'compound'; n.rows = dims[0]; n.cols = one ? 1 : leaves.length; }
    else if (dims.length === 2 && one && !n.chars) { n.form = 'matrix'; n.rows = dims[0]; n.cols = dims[1]; }
    else { n.form = 'cube'; n.rows = prod(dims); n.cols = dims.length + leaves.length; }
    // a lookup table (Kompartment's data files, and the HDF5 Browser's pdf
    // per point): its times beside it
    const pdfList = typeof n.attrs.pdf === 'string' && /^\s*\[/.test(n.attrs.pdf);
    if (n.form === 'vector' && n.numeric && (isTrue(n.attrs.lookup_table) || pdfList)) {
      const t = lookupTimes(n.attrs.index);
      if (t && t.length === n.rows) { n.lookup = t; n.cols = 2; }
    }
    if (n.rows * n.cols > MAX_CELLS * 4) { n.why = `too large (${plural(n.rows * n.cols, 'value')})`; return; }
    n.readable = true;
  }

  /* A lookup table's times: "0,10,100" as Kompartment writes them, or numbers. */
  function lookupTimes(v) {
    const list = typeof v === 'string' ? v.split(',') : Array.isArray(v) ? (v.length === 1 && typeof v[0] === 'string' ? v[0].split(',') : v) : null;
    if (!list || !list.length) return null;
    const t = list.map((x) => (typeof x === 'number' ? x : x.trim() === '' ? NaN : Number(x)));
    return t.every(Number.isFinite) ? t : null;
  }

  // deflate, shuffle, fletcher32, szip, nbit and scale-offset are in h5wasm itself
  const FILTERS_OK = new Set([1, 2, 3, 4, 5, 6]);
  // the rest by plugin (h5wasm-plugins), as the HDF5 Browser fetches them
  const PLUGIN_FILTERS = new Set([307, 32000, 32001, 32004, 32008, 32013, 32015, 32019, 32022, 32023, 32026]);

  /* ---- pandas ---------------------------------------------------------------
     df.to_hdf writes a group per object. fixed format ('frame', 'series'):
     axis0 the column names, axis1 the index, blockN_items and blockN_values
     ([rows, items]) a block of columns of one type; a text block is a
     pickle of a numpy object array. table format ('frame_table',
     'series_table'): a PyTables table (compound) of index, values_block_N
     (an array field per block) and data columns by name; the names, in
     order, are pickles in the attributes. */
  async function pandasInspect(io, nodes, at, g) {
    const pt = String(g.attrs.pandas_type);
    const child = (name) => at.get(`${g.path === '/' ? '' : g.path}/${name}`) || null;
    const dsAttrs = (n, all = false) => {
      if (!n) return {};
      if (all) { const o = {}; for (const a of io.attrNames(n.path)) o[a] = io.attr(n.path, a); return o; }
      return n.attrs || {};
    };
    g.form = 'pandas';
    g.readable = false;
    g.pandas = { type: pt };
    try {
      if (['index_variety', 'columns_variety', 'axis0_variety', 'axis1_variety'].some((k) => g.attrs[k] === 'multi')) throw new Error('a MultiIndex');
      if (pt === 'frame' || pt === 'series') {
        const index = child(pt === 'frame' ? 'axis1' : 'index');
        if (!index || !index.md || !index.shape) throw new Error('no index');
        const rows = index.shape[0];
        let cols;
        if (pt === 'frame') {
          const axis0 = child('axis0');
          if (!axis0 || !axis0.shape) throw new Error('no column names');
          cols = axis0.shape[0];
          const nb = Number(g.attrs.nblocks);
          if (!(nb >= 0)) throw new Error('no blocks');
          for (let b = 0; b < nb; b++) {
            const v = child(`block${b}_values`), it = child(`block${b}_items`);
            if (!v || !it || !v.md) throw new Error(`block ${b} missing`);
          }
        } else {
          if (!child('values') || !child('values').md) throw new Error('no values');
          cols = 1;
        }
        const keep = await pandasKeepsIndex(io, index);
        g.pandas.keepIndex = keep;
        g.rows = rows;
        g.cols = cols + (keep ? 1 : 0);
      } else if (pt === 'frame_table' || pt === 'series_table') {
        const table = child('table');
        if (!table || !table.md || table.md.type !== T.COMPOUND || !table.shape) throw new Error('no table');
        if (Number(g.attrs.levels) > 1) throw new Error('a MultiIndex');
        const ta = dsAttrs(table, true);
        table.attrs = ta;
        const axes = pickleAttr(g.attrs.non_index_axes);
        const names = Array.isArray(axes) && Array.isArray(axes[0]) && Array.isArray(axes[0][1]) ? axes[0][1].map(String) : null;
        if (!names) throw new Error('no column names');
        g.pandas.names = names;
        g.rows = table.shape[0];
        // an index of 0, 1, 2 … is the row numbers; any other comes as a column
        g.pandas.indexKind = typeof ta.index_kind === 'string' ? ta.index_kind : 'integer';
        g.cols = names.length + (g.pandas.indexKind === 'integer' ? 0 : 1);
      } else {
        throw new Error(`a pandas ${pt}`);
      }
      g.readable = true;
    } catch (e) {
      g.why = `${firstLine(e)} (pandas ${pt}: not read)`;
    }
  }

  function pickleAttr(v) {
    if (typeof v !== 'string') return null;
    try { return unpickle(v); } catch (e) { return null; }
  }

  /* Whether a fixed-format index is anything but 0, 1, 2 …, read now: it
     is small (a number per row) and decides the column count. */
  async function pandasKeepsIndex(io, index) {
    const kind = index.attrs.kind;
    if (kind !== 'integer') return true;
    let range = true;
    const md = index.md;
    const node = { ...index, md };
    const leaves = typeLeaves(md).leaves;
    if (leaves.length !== 1) return true;
    await eachChunk(io, node, (dv, heap, first, count) => {
      const r = leafReader(leaves[0], heap);
      for (let i = 0; i < count && range; i++) if (r(dv, i * md.size) !== first + i) range = false;
    });
    return !range;
  }

  /* ---- what opens: plan --------------------------------------------------------
     state: { picked: Set of node ids, transposed: Set of matrix ids that open
     transposed, together: one table for the vectors and matrices of one
     length }. Gives
     { tables: [{ name, rows, cols, key, items: [{ id, transposed }], kind }],
     warnings, blocked }. Pure: the dialog calls it on every tick. */
  function plan(nodes, state, { fileName = 'file' } = {}) {
    const base = baseName(fileName);
    const picked = [...state.picked].map((id) => nodes[id]).filter((n) => n && n.readable && !n.hidden && n.form)
      .sort((a, b) => a.order - b.order);
    const keys = picked.filter((n) => n.key);
    const rest = picked.filter((n) => !n.key && n.form !== 'scalar');
    const scalars = picked.filter((n) => n.form === 'scalar');
    const itemOf = (n) => {
      const t = n.form === 'matrix' && state.transposed.has(n.id);
      // a compound dataset and a pandas object are tables already, and a
      // stacked array is one of its own: they never go side by side
      return { id: n.id, transposed: t, rows: t ? n.cols : n.rows, cols: t ? n.rows : n.cols, alone: n.form === 'cube' || n.form === 'compound' || n.form === 'pandas' };
    };
    const colsOf = (it) => { const n = nodes[it.id]; return n.form === 'matrix' && it.transposed ? n.rows : n.cols; };
    // the scale of an item's rows: items on different scales (two files'
    // times) are on different grids, and are not put side by side
    const rowScale = (n, it) => (n.scales && n.kept ? n.scales[n.kept[it.transposed ? 1 : 0]] : null);
    const tables = [];
    const groups = new Map();
    for (const n of rest) {
      const it = itemOf(n);
      if (it.alone || !state.together) { tables.push({ items: [it], rows: it.rows, kind: n.form === 'cube' ? 'stacked' : 'items' }); continue; }
      const scale = rowScale(n, it);
      // a lookup table's rows are its own times: it goes with lookup tables
      // of the same times only, and takes no key
      const at = n.lookup ? `lookup|${n.lookup.join(',')}` : `${it.rows}|${scale == null ? '' : scale}`;
      if (!groups.has(at)) { const t = { items: [], rows: it.rows, kind: 'items', scale, lookup: !!n.lookup }; groups.set(at, t); tables.push(t); }
      groups.get(at).items.push(it);
    }
    // a row key goes first in each table of its length; one no table uses is a column of its own
    const used = new Set();
    for (const t of tables) {
      if (t.kind === 'stacked' || t.lookup) continue;
      const first = nodes[t.items[0].id];
      const scale = t.scale != null ? t.scale : first.scales && first.kept ? first.scales[first.kept[t.items[0].transposed ? 1 : 0]] : null;
      const cands = keys.filter((k) => k.rows === t.rows && (t.scale == null || k.id === t.scale));
      const key = cands.find((k) => k.id === scale) || cands.find((k) => /^(time|times)$/i.test(k.name) && k.parent === 0) || cands[0] || null;
      if (key) { t.key = key.id; used.add(key.id); }
    }
    for (const k of keys) {
      if (used.has(k.id)) continue;
      const it = itemOf(k);
      const into = state.together ? tables.find((t) => t.kind === 'items' && t.rows === it.rows && t.items.every((x) => nodes[x.id].key)) : null;
      if (into) into.items.push(it);
      else tables.push({ items: [it], rows: it.rows, kind: 'items' });
    }
    if (scalars.length) tables.push({ items: scalars.map((n) => ({ id: n.id, transposed: false })), rows: scalars.length, kind: 'values' });
    // in a table, the columns first and the wide blocks (matrices) after
    // them: a run's sampled values, then its series by time
    const wide = (it) => (nodes[it.id].form === 'matrix' ? 1 : 0);
    for (const t of tables) t.items.sort((a, b) => wide(a) - wide(b) || nodes[a.id].order - nodes[b.id].order);
    // names and sizes
    const warnings = [];
    let blocked = null;
    for (const t of tables) {
      const has = (k) => scalars.some((n) => n.attrs && n.attrs[k] != null && attrText(n.attrs[k]));
      t.cols = t.kind === 'values' ? 1 + (scalars.some((n) => !textual(n)) ? 1 : 0) + (scalars.some(textual) ? 1 : 0) + (scalars.some((n) => unitOf(n)) ? 1 : 0) + (has('pdf') ? 1 : 0) + (has('reference') ? 1 : 0)
        : (t.key != null ? 1 : 0) + t.items.reduce((s, it) => s + colsOf(it), 0);
      t.label = tableLabel(nodes, t);
    }
    tables.sort((a, b) => nodes[a.items[0].id].order - nodes[b.items[0].id].order);
    const seen = new Map();
    for (const t of tables) {
      let name = tables.length === 1 ? base : `${base} — ${t.label}`;
      const k = seen.get(name) || 0;
      seen.set(name, k + 1);
      if (k) name = `${name} ${k + 1}`;
      t.name = name;
      if (t.cols > WIDE) warnings.push(`${t.name} would have ${plural(t.cols, 'column')}: the grid is slow that wide (Tables > Stack makes it long).`);
      if (t.rows * t.cols > MAX_CELLS) blocked = `${t.name} would hold ${plural(t.rows * t.cols, 'value')}, more than this page holds in one table (${(MAX_CELLS / 1e6).toFixed(0)} million).`;
    }
    return { tables: tables.map((t) => ({ name: t.name, label: t.label, rows: t.rows, cols: t.cols, key: t.key == null ? null : t.key, kind: t.kind, items: t.items.map(({ id, transposed }) => ({ id, transposed })) })), warnings, blocked };
  }

  const baseName = (f) => String(f || 'file').replace(/^.*[\\/]/, '').replace(/\.(h5|hdf5|he5|hdf|nc|nc4|cdf|mat|h5ad|hd5)$/i, '') || 'file';

  function tableLabel(nodes, t) {
    if (t.kind === 'values') return 'values';
    const items = t.items.map((it) => nodes[it.id]);
    if (items.length === 1) return items[0].name;
    // the deepest group holding them all
    const chains = items.map((n) => { const c = []; for (let p = n.parent; p >= 0; p = nodes[p].parent) c.unshift(p); return c; });
    let common = 0;
    for (let i = 0; i < Math.min(...chains.map((c) => c.length)); i++) { if (chains.every((c) => c[i] === chains[0][i])) common = chains[0][i]; else break; }
    return common ? nodes[common].name : `${t.rows} rows`;
  }

  /* ---- what is ticked when the dialog opens ------------------------------------
     Every vector, compound, pandas object and small array, when they make
     a few tables of a sensible width, and the single values as one table;
     a run's index lists are left out.
     Matrices come only when all of them fit (a probabilistic run's series
     are a matrix each: those the reader picks). Nothing, when the file is
     too big to guess: the dialog then asks. direct: one table holding
     everything there is, opened without asking. */
  function defaults(nodes, info) {
    const cands = nodes.filter((n) => n.readable && !n.hidden && n.form && n.form !== 'scalar');
    const picked = new Set();
    const transposed = new Set(nodes.filter((n) => n.form === 'matrix' && n.transposed).map((n) => n.id));
    const free = cands.filter((n) => !n.meta);
    const plain = free.filter((n) => n.form === 'vector' || n.form === 'compound' || n.form === 'pandas');
    const mats = free.filter((n) => n.form === 'matrix');
    const cubes = free.filter((n) => n.form === 'cube' && n.rows <= 1e6);
    const width = (list) => list.reduce((s, n) => s + (n.form === 'matrix' && transposed.has(n.id) ? n.rows : n.cols), 0);
    if (width(plain) <= DEFAULT_COLUMNS) plain.forEach((n) => picked.add(n.id));
    if (mats.length && width(mats) + width(plain.filter((n) => picked.has(n.id))) <= DEFAULT_COLUMNS) mats.forEach((n) => picked.add(n.id));
    if (cubes.length <= 8) cubes.forEach((n) => picked.add(n.id));
    // single values, as one table (a data file's parameters, a run's)
    const scalars = nodes.filter((n) => n.readable && !n.hidden && n.form === 'scalar' && !n.meta);
    if (scalars.length <= 5000) scalars.forEach((n) => picked.add(n.id));
    const state = { picked, transposed, together: true };
    let p = plan(nodes, state);
    // a row key is ticked for the tables it starts, not as a table of its own
    const alone = p.tables.filter((t) => t.items.every((it) => nodes[it.id].key)).flatMap((t) => t.items.map((it) => it.id));
    if (alone.length && alone.length < picked.size) { alone.forEach((id) => picked.delete(id)); p = plan(nodes, state); }
    if (p.tables.length > 12 || p.tables.some((t) => t.cols > DEFAULT_COLUMNS + 1) || p.blocked) { picked.clear(); p = plan(nodes, state); }
    const everything = nodes.filter((n) => n.readable && !n.hidden && n.form).every((n) => picked.has(n.id));
    state.direct = p.tables.length === 1 && everything && !info.capped;
    return state;
  }

  /* ---- read: the tables of a plan -------------------------------------------
     { tables, failed }: each table as { name, notes, source, columns }, a
     column as { name, dataType, values (Float64Array, or texts with null
     for missing), modelingType, valueLabels, valueOrder, format, notes };
     failed, [{ name, why }] for a table nothing of which could be read. */
  async function read(io, nodes, info, planned, { fileName = 'file', onProgress = null } = {}) {
    const out = [], failed = [];
    const total = planned.tables.reduce((s, t) => s + t.items.length + (t.key != null ? 1 : 0), 0);
    let done = 0;
    // a key is read once, however many tables start with it
    const ctx = { nodes, io, time: info.timeKey != null ? nodes[info.timeKey] : null, cache: new Map() };
    for (const t of planned.tables) {
      const cols = [];
      // what was not read; skipped.remarks: what was read, with a caveat
      const skipped = [];
      skipped.remarks = [];
      const keyNode = t.key != null ? nodes[t.key] : null;
      const tick = (n) => { if (onProgress) onProgress(done, total, n.path); };
      // a dataset that cannot be read is named in the notes; the rest still come
      const attempt = async (n, fn) => {
        tick(n);
        try { cols.push(...await fn()); } catch (e) { skipped.push(`${n.path}: ${firstLine(e)}`); }
        done++;
      };
      if (keyNode) await attempt(keyNode, async () => [copyColumn(await cachedVector(ctx, keyNode, skipped))]);
      if (t.kind === 'values') {
        cols.push(...await valuesColumns(io, t.items.map((it) => nodes[it.id]), skipped));
        done += t.items.length;
      } else {
        for (const it of t.items) {
          const n = nodes[it.id];
          await attempt(n, async () => {
            if (n.form === 'vector') return n.lookup ? vectorColumns(io, n, skipped) : [copyColumn(await cachedVector(ctx, n, skipped))];
            if (n.form === 'compound') return compoundColumns(io, n, skipped);
            if (n.form === 'matrix') return matrixColumns(io, n, it.transposed, ctx, skipped);
            if (n.form === 'cube') return cubeColumns(io, n, ctx, skipped);
            if (n.form === 'pandas') return pandasColumns(io, nodes, n, skipped);
            return [];
          });
        }
      }
      if (!cols.length) { failed.push({ name: t.name, why: skipped.length ? skipped[0] : 'nothing could be read' }); continue; }
      nameColumns(cols);
      const paths = t.items.map((it) => nodes[it.id].path);
      const notes = [`From ${fileName}: ${paths.slice(0, 8).join(', ')}${paths.length > 8 ? ` and ${paths.length - 8} more` : ''}.`];
      if (info.notes) notes.push(/[.!?]$/.test(info.notes) ? info.notes : `${info.notes}.`);
      const sk = [...new Set(skipped)];
      if (sk.length) notes.push(`Not read: ${sk.slice(0, 12).join('; ')}${sk.length > 12 ? `; and ${sk.length - 12} more` : ''}.`);
      const rk = [...new Set(skipped.remarks)];
      if (rk.length) notes.push(`${rk.slice(0, 6).join('; ')}${rk.length > 6 ? `; and ${rk.length - 6} more` : ''}.`);
      out.push({ name: t.name, source: `${fileName}${paths.length === 1 ? `, ${paths[0]}` : ''}`, notes: notes.join(' '), columns: cols });
    }
    return { tables: out, failed };
  }

  const remark = (skipped, text) => (skipped.remarks || skipped).push(text);

  async function cachedVector(ctx, n, skipped) {
    if (!ctx.cache.has(n.id)) ctx.cache.set(n.id, (await vectorColumns(ctx.io, n, skipped))[0]);
    return ctx.cache.get(n.id);
  }
  // a cached column's values are its own in each table
  const copyColumn = (c) => ({ ...c, values: c.values.slice() });

  /* Column names, each once. A column knows the dataset it came from
     (_origin) and how its name reads with a prefix (_alt); two of one name
     take as much of their datasets' paths as tells them apart:
     Soil/Cs-137 and Water/Cs-137. */
  function nameColumns(cols) {
    const groups = new Map();
    for (const c of cols) { if (!groups.has(c.name)) groups.set(c.name, []); groups.get(c.name).push(c); }
    for (const list of groups.values()) {
      const origins = [...new Set(list.map((c) => c._origin).filter(Boolean))];
      if (list.length < 2 || origins.length < 2) continue;
      const parts = new Map(origins.map((o) => [o, o.split('/').filter(Boolean)]));
      for (const c of list) {
        if (!c._origin || !c._alt) continue;
        const mine = parts.get(c._origin);
        for (let k = 1; k <= mine.length; k++) {
          const tail = mine.slice(-k).join('/');
          if (origins.filter((o) => parts.get(o).slice(-k).join('/') === tail).length === 1) { c.name = c._alt(tail); break; }
        }
      }
    }
    for (const c of cols) { delete c._origin; delete c._alt; }
  }

  function unitOf(n) {
    const a = n.attrs || {};
    for (const k of ['unit', 'units', 'Unit', 'Units']) if (a[k] != null && attrText(a[k])) return attrText(a[k]);
    return '';
  }

  function columnNotes(n) {
    const a = n.attrs || {};
    const bits = [`${n.path}`];
    const unit = unitOf(n);
    if (unit && !n.cf) bits.push(`unit: ${unit}`);
    for (const k of ['long_name', 'description', 'Description', 'title', 'label', 'standard_name']) if (a[k] != null && attrText(a[k])) { bits.push(attrText(a[k])); break; }
    return bits.join('; ');
  }

  /* The values of one leaf over a whole dataset, flat in C order; big says
     whether an integer was beyond 2^53 (rounded as a number). */
  async function leafValues(io, n, leaf, size) {
    const numeric = leaf.kind !== 'text';
    const out = numeric ? new Float64Array(size) : new Array(size).fill(null);
    const wide = numeric && leaf.size === 8 && leaf.kind !== 'float';
    let big = false;
    await eachChunk(io, n, (dv, heap, first, count, esize) => {
      const r = leafReader(leaf, heap);
      for (let i = 0; i < count; i++) out[first + i] = r(dv, i * esize);
      if (wide && !big) for (let i = 0; i < count; i++) { const v = out[first + i]; if (v > 9007199254740992 || v < -9007199254740992) { big = true; break; } }
    });
    return { values: out, big };
  }

  const wholeDays = (values) => { for (let i = 0; i < values.length; i++) { const v = values[i]; if (Number.isFinite(v) && v % 86400000 !== 0) return false; } return true; };

  /* Missing values and packing, as netCDF and CF say: _FillValue and
     missing_value are missing, then scale_factor and add_offset apply; a
     unit "days since 1970-01-01" makes a date. */
  function finishNumbers(n, values, leaf) {
    const a = n.attrs || {};
    const one = (v) => (Array.isArray(v) ? v[0] : v);
    const fills = [a._FillValue, a.missing_value].flatMap((v) => (Array.isArray(v) ? v : [v])).filter((v) => typeof v === 'number');
    const unsigned = isTrue(a._Unsigned) && leaf && leaf.kind === 'int';
    const scale = typeof one(a.scale_factor) === 'number' ? one(a.scale_factor) : 1;
    const offset = typeof one(a.add_offset) === 'number' ? one(a.add_offset) : 0;
    if (fills.length || unsigned || scale !== 1 || offset !== 0) {
      const mod = leaf ? 2 ** (8 * leaf.size) : 0;
      for (let i = 0; i < values.length; i++) {
        let v = values[i];
        if (fills.some((f) => f === v || (Number.isNaN(f) && Number.isNaN(v)))) { values[i] = NaN; continue; }
        if (unsigned && v < 0) v += mod;
        values[i] = v * scale + offset;
      }
    }
    const cf = cfTime(unitOf(n), a.calendar);
    if (cf) {
      n.cf = true;
      for (let i = 0; i < values.length; i++) values[i] = Number.isFinite(values[i]) ? Math.round(cf.origin + values[i] * cf.ms) : NaN;
      return { format: { kind: wholeDays(values) ? 'date' : 'datetime' } };
    }
    return {};
  }

  const CF_UNIT = { millisecond: 1, milliseconds: 1, msec: 1, msecs: 1, second: 1000, seconds: 1000, sec: 1000, secs: 1000, s: 1000, minute: 60000, minutes: 60000, min: 60000, mins: 60000, hour: 3600000, hours: 3600000, hr: 3600000, hrs: 3600000, h: 3600000, day: 86400000, days: 86400000, d: 86400000, microsecond: 1e-3, microseconds: 1e-3 };
  /* "<unit> since <date>[ <time>][ <zone>]" in the calendars that are the
     usual one (standard, gregorian, proleptic_gregorian): ms per unit and
     the origin, or null. */
  function cfTime(units, calendar) {
    if (!units) return null;
    const cal = calendar == null ? '' : attrText(calendar).toLowerCase();
    if (cal && !['standard', 'gregorian', 'proleptic_gregorian'].includes(cal)) return null;
    const m = /^\s*([a-z]+)\s+since\s+(-?\d{1,4})-(\d{1,2})-(\d{1,2})(?:[T\s]+(\d{1,2}):(\d{1,2})(?::(\d{1,2}(?:\.\d+)?))?)?\s*(Z|UTC|GMT|[+-]\d{1,2}(?::?\d{2})?)?\s*$/i.exec(units);
    if (!m || !CF_UNIT[m[1].toLowerCase()]) return null;
    let origin = Date.UTC(+m[2], +m[3] - 1, +m[4], +(m[5] || 0), +(m[6] || 0), 0) + Math.round(+(m[7] || 0) * 1000);
    if (+m[2] < 100 && +m[2] >= 0) { const d = new Date(origin); d.setUTCFullYear(+m[2]); origin = d.getTime(); }
    const z = m[8] && !/^(Z|UTC|GMT)$/i.test(m[8]) ? /^([+-])(\d{1,2}):?(\d{2})?$/.exec(m[8]) : null;
    if (z) origin -= (z[1] === '-' ? -1 : 1) * (+z[2] * 60 + +(z[3] || 0)) * 60000;
    return Number.isFinite(origin) ? { origin, ms: CF_UNIT[m[1].toLowerCase()] } : null;
  }

  // MATLAB's logical is 0 and 1, labelled as MATLAB writes them
  const LOGICAL = { valueLabels: [[0, 'false'], [1, 'true']], modelingType: 'nominal' };

  function columnOf(name, values, leaf, extra = {}) {
    if (leaf.kind === 'text') return { name, dataType: 'character', values, ...extra };
    if (leaf.kind === 'enum') {
      const m = leaf.members || {};
      const pairs = Object.keys(m).map((k) => [Number(m[k]), k]).sort((a, b) => a[0] - b[0]);
      return { name, dataType: 'numeric', modelingType: 'nominal', values, valueLabels: pairs, ...extra };
    }
    return { name, dataType: 'numeric', values, ...extra };
  }

  async function vectorColumns(io, n, skipped) {
    const own = { _origin: n.path, _alt: (p) => p };
    if (n.chars) return [{ name: n.name, dataType: 'character', values: await charStrings(io, n), notes: columnNotes(n), ...own }];
    const leaf = n.leaves[0];
    const { values, big } = await leafValues(io, n, leaf, prod(n.shape));
    if (big) remark(skipped, `${n.path}: integers beyond 2^53 rounded to the nearest double`);
    const extra = leaf.kind === 'text' ? {} : finishNumbers(n, values, leaf);
    const col = columnOf(n.name, values, leaf, { ...extra, ...(n.matlab === 'logical' ? LOGICAL : {}), notes: columnNotes(n), ...own });
    if (!n.lookup) return [col];
    // a lookup table: its times first, then its values
    return [{ name: 'time', dataType: 'numeric', values: Float64Array.from(n.lookup), notes: `${n.path}, the times of the lookup table (its index attribute)`, _origin: n.path, _alt: (p) => `${p} time` }, col];
  }

  /* Text kept as characters: netCDF's along the last dimension (one byte
     each), MATLAB's down the first (UTF-16 code units). */
  async function charStrings(io, n) {
    const shape = n.shape;
    const total = prod(shape);
    const leaf = n.leaves[0];
    const codes = new Uint16Array(total);
    await eachChunk(io, n, (dv, heap, first, count, esize) => {
      const r = n.chars === 'matlab' ? leafReader(leaf, heap) : null;
      for (let i = 0; i < count; i++) codes[first + i] = r ? r(dv, i * esize) : dv.getUint8(i * esize);
    });
    const out = [];
    if (n.chars === 'last') {
      const L = shape[shape.length - 1];
      const bytes = Uint8Array.from(codes);
      for (let s = 0; s < total / L; s++) {
        const b = bytes.subarray(s * L, (s + 1) * L);
        let k = b.indexOf(0);
        if (k < 0) k = L;
        while (k > 0 && b[k - 1] === 0x20) k--;
        out.push(k ? decodeText(b.subarray(0, k), leaf.cset) : null);
      }
    } else {
      // MATLAB: [L, k] holds k texts of L characters, text j down column j
      const L = shape[0], k = total / L;
      for (let j = 0; j < k; j++) {
        let s = '';
        for (let i = 0; i < L; i++) s += String.fromCharCode(codes[i * k + j]);
        s = s.replace(/[\s\0]+$/, '');
        out.push(s || null);
      }
    }
    return out;
  }

  async function compoundColumns(io, n, skipped) {
    const size = prod(n.shape);
    for (const b of n.badLeaves) skipped.push(`${n.path}: ${b.name || 'a field'} (${b.why})`);
    // every field in one pass over the data
    const outs = n.leaves.map((l) => (l.kind === 'text' ? new Array(size).fill(null) : new Float64Array(size)));
    await eachChunk(io, n, (dv, heap, first, count, esize) => {
      const readers = n.leaves.map((l) => leafReader(l, heap));
      for (let i = 0; i < count; i++) {
        const b = i * esize;
        for (let k = 0; k < readers.length; k++) outs[k][first + i] = readers[k](dv, b);
      }
    });
    // a compound's fields by their names; an array type's members after the dataset's, x[1], x[2]
    const field = n.md.type === T.COMPOUND;
    return n.leaves.map((l, k) => columnOf(field ? l.name || n.name : `${n.name}${l.name}`, outs[k], l, {
      notes: field ? `${n.path}, field ${l.name}` : `${n.path}, member ${l.name}`, _origin: n.path, _alt: (p) => (field ? `${p}.${l.name}` : `${p}${l.name}`) }));
  }

  /* A matrix: rows the first dimension, or the second when transposed.
     Column names, in this order of preference: an attribute naming them,
     a dimension scale of that dimension, the file's time when they are
     its times (a run's realisations), or the dataset's name numbered. */
  async function matrixColumns(io, n, transposed, ctx, skipped) {
    const leaf = n.leaves[0];
    const [r0, c0] = n.dims;
    const { values, big } = await leafValues(io, n, leaf, r0 * c0);
    if (big) remark(skipped, `${n.path}: integers beyond 2^53 rounded to the nearest double`);
    const extra = leaf.kind === 'text' ? {} : finishNumbers(n, values, leaf);
    // (iterations padded: only the first ones are, and only to their last step)
    const ragged = n.ragged || null;
    const kept = ragged ? ragged.length : c0;
    if (ragged) remark(skipped, `${n.path}: ${plural(kept, 'iteration')} of ${c0} (n_times), each to its last step`);
    const rows = transposed ? kept : r0, ncol = transposed ? r0 : kept;
    const labels = await matrixLabels(n, transposed ? 0 : 1, ncol, ctx, skipped);
    const notes = columnNotes(n);
    const gone = leaf.kind === 'text' ? null : NaN;
    const cols = [];
    for (let j = 0; j < ncol; j++) {
      const v = leaf.kind === 'text' ? new Array(rows) : new Float64Array(rows);
      if (transposed) for (let i = 0; i < rows; i++) v[i] = ragged && j >= ragged[i] ? gone : values[j * c0 + i];
      else for (let i = 0; i < rows; i++) v[i] = ragged && i >= ragged[j] ? gone : values[i * c0 + j];
      const label = labels.list[j];
      const name = labels.bare ? label : `${n.name} ${label}`;
      cols.push(columnOf(name, v, leaf, { ...extra, ...(n.matlab === 'logical' ? LOGICAL : {}), notes: `${notes}; ${transposed ? 'row' : 'column'} ${j + 1}`, _origin: n.path, _alt: (p) => `${p} ${label}` }));
    }
    return cols;
  }

  async function matrixLabels(n, dim, count, ctx, skipped) {
    const a = n.attrs || {};
    for (const k of NAME_ATTRS) {
      const v = a[k];
      if (Array.isArray(v) && v.length === count && v.every((x) => typeof x === 'string' || typeof x === 'number')) return { list: v.map((x) => attrText(x) || '.'), bare: true };
    }
    const sid = n.scales && n.kept ? n.scales[n.kept[dim]] : null;
    const scale = sid != null ? ctx.nodes[sid] : null;
    if (scale && scale.rows === count) {
      const v = keyLabels(await cachedVector(ctx, scale, skipped));
      // (a run's realisations: a column per time, t=…, as with the file's time)
      if (v) return { list: n.realisations && sid === n.timeOf ? v.map((x) => `t=${x}`) : v };
    }
    const tnode = n.timeOf != null ? ctx.nodes[n.timeOf] : ctx.time;
    if (tnode && tnode.rows === count && n.realisations) {
      const v = keyLabels(await cachedVector(ctx, tnode, skipped));
      if (v) return { list: v.map((x) => `t=${x}`) };
    }
    return { list: Array.from({ length: count }, (_, j) => String(j + 1)) };
  }

  /* A key's values as short text, for column names. */
  function keyLabels(c) {
    const fmt = c.format && c.format.kind;
    return Array.from(c.values, (v) => {
      if (v == null || (typeof v === 'number' && Number.isNaN(v))) return '.';
      if (typeof v === 'string') return v;
      if (fmt) return new Date(v).toISOString().slice(0, fmt === 'date' ? 10 : 19).replace('T', ' ');
      return String(+v.toPrecision(6));
    });
  }

  /* A larger array, stacked: a row per element, a column per dimension
     (the scale's value there, or the position from 1), then the values. */
  async function cubeColumns(io, n, ctx, skipped) {
    const dims = n.dims;
    const total = prod(dims);
    const cols = [];
    for (let k = 0; k < dims.length; k++) {
      const stride = prod(dims.slice(k + 1));
      const sid = n.scales ? n.scales[n.kept[k]] : null;
      const scale = sid != null ? ctx.nodes[sid] : null;
      const scol = scale && scale.rows === dims[k] ? await cachedVector(ctx, scale, skipped) : null;
      const sv = scol ? scol.values : null;
      const text = !!sv && !(sv instanceof Float64Array);
      const v = text ? new Array(total) : new Float64Array(total);
      for (let e = 0; e < total; e++) { const i = Math.floor(e / stride) % dims[k]; v[e] = sv ? sv[i] : i + 1; }
      cols.push({ name: scol ? scale.scaleName || scale.name : `${n.name} dimension ${k + 1}`, dataType: text ? 'character' : 'numeric', values: v,
        ...(scol && scol.format ? { format: scol.format } : {}),
        notes: scol ? `${scale.path}, the scale of dimension ${k + 1} of ${n.path}` : `the position along dimension ${k + 1} of ${n.path}, from 1` });
    }
    if (n.chars) {
      cols.push({ name: n.name, dataType: 'character', values: await charStrings(io, n), notes: columnNotes(n) });
      return cols;
    }
    for (const b of n.badLeaves) skipped.push(`${n.path}: ${b.name || 'a field'} (${b.why})`);
    const outs = n.leaves.map((l) => (l.kind === 'text' ? new Array(total).fill(null) : new Float64Array(total)));
    await eachChunk(io, n, (dv, heap, first, count, esize) => {
      const readers = n.leaves.map((l) => leafReader(l, heap));
      for (let i = 0; i < count; i++) for (let k = 0; k < readers.length; k++) outs[k][first + i] = readers[k](dv, i * esize);
    });
    n.leaves.forEach((l, k) => {
      const extra = l.kind === 'text' || n.leaves.length > 1 ? {} : finishNumbers(n, outs[k], l);
      cols.push(columnOf(n.leaves.length === 1 ? n.name : `${n.name}.${l.name}`, outs[k], l, { ...extra, ...(n.matlab === 'logical' ? LOGICAL : {}), notes: columnNotes(n) }));
    });
    return cols;
  }

  /* Single values: a row each, the name, the value (a number; a text one in
     Text), the unit; and the distribution and reference a Kompartment
     data file gives a parameter. */
  async function valuesColumns(io, list, skipped) {
    const names = [], vals = [], units = [];
    const text = (n, k) => (n.attrs && n.attrs[k] != null && attrText(n.attrs[k]) ? attrText(n.attrs[k]) : null);
    let anyText = false;
    for (const n of list) {
      let v = null;
      try { v = await scalarValue(io, n); } catch (e) { skipped.push(`${n.path}: ${firstLine(e)}`); }
      names.push(n.path.replace(/^\//, ''));
      vals.push(v);
      units.push(unitOf(n) || null);
      if (typeof v === 'string') anyText = true;
    }
    const cols = [{ name: 'Name', dataType: 'character', values: names }];
    if (list.some((n) => !textual(n))) cols.push({ name: 'Value', dataType: 'numeric', values: Float64Array.from(vals, (v) => (typeof v === 'number' ? v : NaN)) });
    if (anyText) cols.push({ name: 'Text', dataType: 'character', values: vals.map((v) => (typeof v === 'string' ? v : null)) });
    if (units.some(Boolean)) cols.push({ name: 'Unit', dataType: 'character', values: units });
    for (const [k, label] of [['pdf', 'Distribution'], ['reference', 'Reference']]) {
      const v = list.map((n) => text(n, k));
      if (v.some(Boolean)) cols.push({ name: label, dataType: 'character', values: v, notes: `the ${k} attribute` });
    }
    return cols;
  }

  // a single value that is text (an enumeration's level is too)
  const textual = (n) => !!(n.chars || (n.leaves && n.leaves[0] && (n.leaves[0].kind === 'text' || n.leaves[0].kind === 'enum')));

  async function scalarValue(io, n) {
    if (n.chars) return (await charStrings(io, n))[0];
    const leaf = n.leaves[0];
    const { values } = await leafValues(io, n, leaf, 1);
    if (leaf.kind === 'text') return values[0];
    finishNumbers(n, values, leaf);
    if (leaf.kind === 'enum') { const m = leaf.members || {}; const k = Object.keys(m).find((x) => m[x] === values[0]); return k != null ? k : values[0]; }
    return values[0];
  }

  /* ---- pandas, read --------------------------------------------------------- */
  async function pandasColumns(io, nodes, g, skipped) {
    const kids = new Map(g.children.map((c) => [nodes[c].name, nodes[c]]));
    const pt = g.pandas.type;
    const cols = pt === 'frame_table' || pt === 'series_table' ? await pandasTable(io, nodes, g, kids, skipped) : await pandasFixed(io, g, kids, skipped);
    for (const c of cols) { c.notes = c.notes || `${g.path} (pandas)`; c._origin = g.path; const nm = c.name; c._alt = (p) => `${p}.${nm}`; }
    return cols;
  }

  async function pandasFixed(io, g, kids, skipped) {
    const pt = g.pandas.type;
    const cols = [];
    const index = kids.get(pt === 'frame' ? 'axis1' : 'index');
    if (g.pandas.keepIndex) cols.push(await pandasArray(io, index, pandasName(index.attrs.name, 'index'), skipped, index.attrs.kind));
    if (pt === 'series') {
      cols.push(await pandasArray(io, kids.get('values'), pandasName(g.attrs.name, g.name), skipped));
      return cols;
    }
    const labels = async (n) => Array.from((await pandasArray(io, n, 'names', skipped, n.attrs.kind)).values, (x) => (x == null ? '' : typeof x === 'number' ? String(x) : x));
    const names = await labels(kids.get('axis0'));
    const byName = new Map();
    const nb = Number(g.attrs.nblocks);
    for (let b = 0; b < nb; b++) {
      const items = await labels(kids.get(`block${b}_items`));
      const blockCols = await pandasBlock(io, kids.get(`block${b}_values`), items, g.rows, skipped);
      items.forEach((name, j) => byName.set(name, blockCols[j]));
    }
    for (const nm of names) {
      const c = byName.get(nm);
      if (c) cols.push({ ...c, name: nm || 'Column' });
      else skipped.push(`${g.path}: column ${nm} (not found in the blocks)`);
    }
    return cols;
  }

  /* A name pandas wrote: plain text, or a pickle (N. is None). */
  function pandasName(v, fallback) {
    if (typeof v !== 'string') return fallback;
    if (/^(N\.|\(|V|S'|I\d)/.test(v) && /\.$/.test(v)) { const p = pickleAttr(v); return p == null ? fallback : String(p); }
    return v || fallback;
  }

  /* One column from a fixed-format array: numbers, text, datetimes
     (value_type datetime64[unit]) or a pickled object array. */
  async function pandasArray(io, n, name, skipped, kind = null) {
    const vt = typeof n.attrs.value_type === 'string' ? n.attrs.value_type : '';
    if (n.md && n.md.type === T.VLEN) {
      const objs = await pandasObjects(io, n, skipped);
      return objectColumn(name, objs ? objs.data : [], skipped, n.path);
    }
    const leaf = n.leaves && n.leaves[0];
    if (!leaf) { skipped.push(`${n.path}: ${n.why || 'not read'}`); return { name, dataType: 'numeric', values: new Float64Array(n.shape ? prod(n.shape) : 0).fill(NaN) }; }
    const { values } = await leafValues(io, n, leaf, prod(n.shape));
    if (/^datetime64/.test(vt) || kind === 'datetime64') return datetimeColumn(name, values, vt || 'datetime64[ns]');
    if (leaf.kind === 'text') return { name, dataType: 'character', values };
    return { name, dataType: 'numeric', values };
  }

  function datetimeColumn(name, values, vt) {
    const unit = (/\[(\w+)/.exec(vt) || [])[1] || 'ns';
    const per = { ns: 1e-6, us: 1e-3, ms: 1, s: 1000, m: 60000, h: 3600000, D: 86400000 }[unit] || 1e-6;
    const out = new Float64Array(values.length);
    for (let i = 0; i < values.length; i++) {
      const v = values[i];
      // NaT is the smallest int64
      out[i] = v <= -9223372036854775000 || !Number.isFinite(v) ? NaN : Math.round(v * per);
    }
    return { name, dataType: 'numeric', values: out, format: { kind: wholeDays(out) ? 'date' : 'datetime' } };
  }

  /* A fixed-format object block: one element, a pickle of the block's
     numpy object array. */
  async function pandasObjects(io, n, skipped) {
    let bytes = null;
    await eachChunk(io, n, (dv, heap, first) => {
      if (first !== 0 || bytes) return;
      const len = dv.getUint32(0, true), ptr = dv.getUint32(4, true);
      if (len > 0 && ptr) bytes = heap.slice(ptr, ptr + len);
    });
    if (!bytes) return null;
    let arr = null;
    try { arr = numpyArray(unpickle(bytes)); } catch (e) { skipped.push(`${n.path}: ${firstLine(e)}`); return null; }
    if (!arr || arr.dtype == null || !/^\|?O/.test(arr.dtype) || !Array.isArray(arr.data)) { skipped.push(`${n.path}: a pickle that is not an object array`); return null; }
    return arr;
  }

  /* An object array's values: texts (None and NaN missing); all numbers stay numbers. */
  function objectColumn(name, data, skipped, where) {
    let nums = true, other = 0;
    for (const v of data) { if (v == null || (typeof v === 'number' && Number.isNaN(v))) continue; if (typeof v !== 'number' && typeof v !== 'boolean') { nums = false; break; } }
    if (nums) return { name, dataType: 'numeric', values: Float64Array.from(data, (v) => (v == null ? NaN : Number(v))) };
    const values = data.map((v) => {
      if (v == null || (typeof v === 'number' && Number.isNaN(v))) return null;
      if (typeof v === 'string') return v === '' ? null : v;
      if (typeof v === 'number' || typeof v === 'boolean') return String(v);
      if (v instanceof Uint8Array) return decodeText(v, 1);
      other++;
      return null;
    });
    if (other) skipped.push(`${where}: ${plural(other, 'value')} of other Python types left out`);
    return { name, dataType: 'character', values };
  }

  async function pandasBlock(io, vn, items, rows, skipped) {
    const k = items.length;
    const vt = typeof vn.attrs.value_type === 'string' ? vn.attrs.value_type : '';
    // the stored array is [rows, items] (pandas' transposed), in C order
    const tr = isTrue(vn.attrs.transposed);
    const at = (i, j) => (tr ? i * k + j : j * rows + i);
    if (vn.md && vn.md.type === T.VLEN) {
      const arr = await pandasObjects(io, vn, skipped);
      return items.map((nm, j) => {
        const col = new Array(rows);
        for (let i = 0; i < rows; i++) col[i] = arr ? arr.data[at(i, j)] : null;
        return objectColumn(nm, col, skipped, vn.path);
      });
    }
    const leaf = vn.leaves && vn.leaves[0];
    if (!leaf) { skipped.push(`${vn.path}: ${vn.why || 'not read'}`); return items.map((nm) => ({ name: nm, dataType: 'numeric', values: new Float64Array(rows).fill(NaN) })); }
    const { values } = await leafValues(io, vn, leaf, rows * k);
    return items.map((nm, j) => {
      const col = leaf.kind === 'text' ? new Array(rows) : new Float64Array(rows);
      for (let i = 0; i < rows; i++) col[i] = values[at(i, j)];
      if (/^datetime64/.test(vt)) return datetimeColumn(nm, col, vt);
      if (vn.md.type === T.BITFIELD || /^bool/.test(vt)) return { name: nm, dataType: 'numeric', modelingType: 'nominal', values: col, valueLabels: [[0, 'False'], [1, 'True']] };
      return leaf.kind === 'text' ? { name: nm, dataType: 'character', values: col } : { name: nm, dataType: 'numeric', values: col };
    });
  }

  /* table format: every field of the PyTables table, then each column
     found by its block (its _kind attribute lists the block's names). */
  async function pandasTable(io, nodes, g, kids, skipped) {
    const table = kids.get('table');
    const ta = table.attrs;
    const size = table.shape[0];
    const leaves = table.leaves;
    const outs = leaves.map((l) => (l.kind === 'text' ? new Array(size).fill(null) : new Float64Array(size)));
    await eachChunk(io, table, (dv, heap, first, count, esize) => {
      const readers = leaves.map((l) => leafReader(l, heap));
      for (let i = 0; i < count; i++) for (let k = 0; k < readers.length; k++) outs[k][first + i] = readers[k](dv, i * esize);
    });
    const field = new Map(leaves.map((l, k) => [l.name, outs[k]]));
    const nanRep = typeof g.attrs.nan_rep === 'string' ? g.attrs.nan_rep : 'nan';
    const info = pickleAttr(g.attrs.info);
    const cols = [];
    // the index, unless it is 0, 1, 2 …
    const idx = field.get('index');
    if (idx) {
      const kind = g.pandas.indexKind;
      let range = kind === 'integer';
      if (range) for (let i = 0; i < size && range; i++) if (idx[i] !== i) range = false;
      if (!range) {
        if (/^datetime64/.test(kind)) cols.push(datetimeColumn('index', idx, kind));
        else if (idx instanceof Float64Array) cols.push({ name: 'index', dataType: 'numeric', values: idx });
        else cols.push({ name: 'index', dataType: 'character', values: idx.map((v) => (v === nanRep ? null : v)) });
      }
    }
    // where each name is: its block (a field), its place in it
    const where = new Map();
    for (const a of Object.keys(ta)) {
      const m = /^(.*)_kind$/.exec(a);
      if (!m || m[1] === 'index') continue;
      const list = pickleAttr(ta[a]);
      if (!Array.isArray(list)) continue;
      list.forEach((nm, j) => where.set(String(nm), { block: m[1], j }));
    }
    for (const nm of g.pandas.names) {
      const w = where.get(nm);
      if (!w) { skipped.push(`${g.path}: column ${nm} (not found)`); continue; }
      const dtype = typeof ta[`${w.block}_dtype`] === 'string' ? ta[`${w.block}_dtype`] : '';
      const meta = ta[`${w.block}_meta`];
      const v = field.get(`${w.block}[${w.j + 1}]`) || (w.j === 0 ? field.get(w.block) : null);
      if (!v) { skipped.push(`${g.path}: column ${nm} (no field ${w.block})`); continue; }
      if (meta === 'category') {
        const cats = await pandasCategories(io, nodes, g, w.block, skipped);
        const bi = info instanceof Map ? info.get(w.block) : null;
        const ordered = bi instanceof Map && bi.get('ordered') === true;
        const values = Array.from(v, (c) => (c >= 0 && c < cats.length ? cats[c] : null));
        const text = cats.some((x) => typeof x === 'string');
        cols.push(text ? { name: nm, dataType: 'character', values: values.map((x) => (x == null ? null : String(x))), valueOrder: cats.map(String), modelingType: ordered ? 'ordinal' : 'nominal' }
          : { name: nm, dataType: 'numeric', values: Float64Array.from(values, (x) => (x == null ? NaN : Number(x))), modelingType: ordered ? 'ordinal' : 'nominal' });
      } else if (/^datetime64/.test(dtype)) cols.push(datetimeColumn(nm, v, dtype));
      else if (/^bool/.test(dtype)) cols.push({ name: nm, dataType: 'numeric', modelingType: 'nominal', values: v, valueLabels: [[0, 'False'], [1, 'True']] });
      else if (!(v instanceof Float64Array)) cols.push({ name: nm, dataType: 'character', values: v.map((x) => (x === nanRep ? null : x)) });
      else cols.push({ name: nm, dataType: 'numeric', values: v });
    }
    if (g.pandas.type === 'series_table' && cols.length && cols[cols.length - 1].name === 'values') cols[cols.length - 1].name = g.name;
    return cols;
  }

  async function pandasCategories(io, nodes, g, block, skipped) {
    const path = `${g.path === '/' ? '' : g.path}/meta/${block}/meta/table`;
    const n = nodes.find((x) => x.path === path);
    const leaf = n && (n.leaves || []).find((l) => l.name === 'values');
    if (!leaf) { skipped.push(`${g.path}: the categories of ${block}`); return []; }
    const { values } = await leafValues(io, n, leaf, n.shape[0]);
    return Array.from(values);
  }

  SM.h5 = Object.freeze({
    sniff, inspect, plan, defaults, read, unpickle, numpyArray, ioFor, cfTime, decodeText, half, markupText, typeLeaves, baseName,
    MAX_CELLS, WIDE,
  });
}(typeof self !== 'undefined' ? self : this));
