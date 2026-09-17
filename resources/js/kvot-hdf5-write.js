/* ==========================================================================
   WRITING HDF5 IN THE PAGE

   A small, self-contained HDF5 writer: groups, one-dimensional arrays of
   doubles, floats, ints and strings, attributes on both, and nothing else.
   That is what a result file is.

   It exists so that a page which has just computed something can hand it to
   the HDF5 Browser, or offer it as a .h5 download, without pulling in h5wasm
   -- 4.7 MB of WebAssembly from a CDN, which is a great deal to fetch in order
   to *write* a few hundred kilobytes.

   Taken from the Ecolego web port (ecolego-js, src/io/hdf5.js), where every
   structure in it was decoded out of files libhdf5 had written, and where the
   files it produces are read back by h5py, h5ls, h5dump and h5wasm. The only
   changes here are the module wrapper and the indentation; see
   resources/tests/facsimile/test-hdf5.py, which reads what this writes with
   the real library.

   Usage:

     const { group, dataset, put, writeHDF5, F64, STR } = KvotHDF5;
     const root = group({ model: 'something', created_time: '2026-09-17' });
     put(root, ['time'], dataset(times, F64, { unit: 'h' }));
     put(root, ['Results', 'H2'], dataset(values, F64, { time_dependent: true }));
     const bytes = writeHDF5(root);          // Uint8Array

   One global, KvotHDF5. Runs in a page, a Worker and Node.
   ========================================================================== */
(function (root, factory) {
  const api = factory();
  root.KvotHDF5 = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /**
   * Writing HDF5, by hand, in the page.
   *
   * WHY THIS EXISTS. Ecolego saves its results as HDF5 and the tools built
   * around it read that: `rb.html` -- the result browser at kvotab.se -- opens a
   * `.h5`, walks the tree, and draws every radionuclide in a group as one chart.
   * A port that can only write CSV is a port whose results cannot be looked at
   * the way everyone looks at results.
   *
   * WHY IT IS WRITTEN OUT RATHER THAN LINKED. The Java writes through the HDF5
   * library; the browser equivalent is h5wasm, which is 4.7 MB of WebAssembly
   * fetched from a CDN. This port has no build step, no dependencies and no
   * network: `index.html` and the files beside it are the whole of it. So the
   * format is written here. It is a *writer* only, and a narrow one -- groups,
   * one-dimensional arrays of numbers and of strings, and attributes -- which is
   * all a result file is.
   *
   * WHICH HDF5. There are two ways to store a group, and this uses the newer
   * one: version 2 object headers with the links held in the header itself
   * ("compact" storage). The older way -- a symbol table, a local heap and a
   * version 1 B-tree -- is what `h5py` writes by default, and writing it means
   * building and balancing a B-tree for every group in the file. Compact groups
   * need no tree at all: a link is a message, and a group with four hundred
   * children is four hundred messages. The cost is that every version 2
   * structure carries a Jenkins lookup3 checksum, which is forty lines, and the
   * saving is the whole of the tree code. The library reads both; libhdf5 has
   * written version 2 headers since 1.8 and the browser's h5wasm is 1.14.
   *
   * Strings are variable-length, which is what Ecolego writes and what the
   * sample files in the browser hold, and what makes a name read back as a name
   * rather than as a name with trailing NULs. They live in a global heap
   * collection, shared: `TRUE` appears once in the file however many datasets
   * say it.
   *
   * References: the HDF5 File Format Specification version 3.0, sections III.A
   * (superblock version 2), IV.A (object headers version 2 and their messages),
   * and III.E (global heap). The checksum is `H5_checksum_lookup3` from
   * `H5checksum.c`.
   */

  /** What a file starts with: \x89 H D F \r \n \x1a \n. */
  const SIGNATURE = [0x89, 0x48, 0x44, 0x46, 0x0d, 0x0a, 0x1a, 0x0a];

  /** Message types, from the specification's table. */
  const MSG = {
    NIL: 0x00,
    DATASPACE: 0x01,
    LINK_INFO: 0x02,
    DATATYPE: 0x03,
    FILL_VALUE: 0x05,
    LINK: 0x06,
    LAYOUT: 0x08,
    GROUP_INFO: 0x0a,
    ATTRIBUTE: 0x0c,
    ATTRIBUTE_INFO: 0x15,
  };

  /**
   * A global heap collection has to be at least this big, and every
   * variable-length string in the file lives in one of them.
   */
  const HEAP_MINIMUM = 4096;

  /** Past this many objects the two-byte index in a heap ID runs out. */
  const HEAP_MAX_OBJECTS = 60000;

  /** One encoder for the file: a name and a string are both UTF-8. */
  const UTF8 = new TextEncoder();

  /** Thrown when a tree cannot be written. */
  class HDF5Error extends Error {
    constructor(message) {
      super(message);
      this.name = 'HDF5Error';
    }
  }

  // --- the datatypes this writer knows ----------------------------------------

  /** IEEE 754 doubles, little-endian: what a result series is. */
  const F64 = { kind: 'float', size: 8, exp: 11, expLoc: 52, mant: 52, bias: 1023 };
  /** The same, half the size, for a series that does not need the digits. */
  const F32 = { kind: 'float', size: 4, exp: 8, expLoc: 23, mant: 23, bias: 127 };
  /** A signed 32-bit integer: counts. */
  const I32 = { kind: 'int', size: 4, signed: true };
  /** A variable-length UTF-8 string, held in the global heap. */
  const STR = { kind: 'vlenstr', size: 16 };

  /**
   * The datatype message for one of the above.
   *
   * Version 1, which is the version every reader understands and the one the
   * specification describes first. The layout is a class-and-version byte, three
   * bytes of class-specific flags, a four-byte size, and then properties whose
   * shape depends on the class.
   */
  function datatypeBytes(dt) {
    const out = [];
    const prefix = (cls, bits, size) => {
      out.push((1 << 4) | cls);
      out.push(bits & 0xff, (bits >>> 8) & 0xff, (bits >>> 16) & 0xff);
      out.push(size & 0xff, (size >>> 8) & 0xff, (size >>> 16) & 0xff, (size >>> 24) & 0xff);
    };
    const u16 = (v) => out.push(v & 0xff, (v >>> 8) & 0xff);
    const u32 = (v) => out.push(v & 0xff, (v >>> 8) & 0xff, (v >>> 16) & 0xff, (v >>> 24) & 0xff);

    if (dt.kind === 'float') {
      // Bit 0 clear is little-endian; bits 4-5 = 2 is the usual "the leading
      // mantissa bit is implied"; bits 8-15 say where the sign sits, which
      // for these is the top bit.
      const sign = dt.size * 8 - 1;
      prefix(1, 0x20 | (sign << 8), dt.size);
      u16(0); // bit offset
      u16(dt.size * 8); // bit precision
      out.push(dt.expLoc, dt.exp, 0, dt.mant);
      u32(dt.bias);
      return out;
    }
    if (dt.kind === 'int') {
      prefix(0, dt.signed ? 0x08 : 0x00, dt.size);
      u16(0);
      u16(dt.size * 8);
      return out;
    }
    if (dt.kind === 'vlenstr') {
      // Class 9, variable-length. Bits 0-3 = 1 says the sequence is a
      // string; bits 4-7 are its padding rule and bits 8-11 its character
      // set, and both belong to the *string*, so they repeat in the base
      // type below -- which is what the property of a variable-length type
      // is: the type of one element, written out in full.
      prefix(9, 0x01 | (0 << 4) | (1 << 8), 16);
      // The parent type is one character, and libhdf5 writes that as an
      // eight-bit unsigned integer rather than as a one-byte string -- the
      // string-ness is in the bits above, not down here. Written as a string
      // the file still reads, and `h5dump` calls its C type
      // `unknown_one_character_type` rather than `H5T_C_S1`; this is the
      // byte-for-byte shape the library produces.
      out.push((1 << 4) | 0); // version 1, class 0 (fixed-point)
      out.push(0, 0, 0); // little-endian, unsigned, no padding
      u32(1); // one byte wide
      u16(0); // bit offset
      u16(8); // bit precision
      return out;
    }
    throw new HDF5Error(`No datatype for '${dt.kind}'`);
  }

  /**
   * The dataspace message: how many values, in how many dimensions.
   *
   * Version 2, which adds the "type" byte distinguishing a scalar from a
   * one-element array -- a distinction the reader on the other end keeps, and
   * which decides whether an attribute comes back as a string or as a list of
   * one.
   */
  function dataspaceBytes(dims) {
    const out = [2, dims.length, 0, dims.length ? 1 : 0];
    for (const n of dims) {
      for (let i = 0; i < 8; i++) out.push(Math.floor(n / 2 ** (8 * i)) & 0xff);
    }
    return out;
  }

  // --- the tree ---------------------------------------------------------------

  /**
   * A group: attributes and children.
   *
   * Children are kept in insertion order, and written in it. HDF5 has an
   * ordering of its own -- a compact group is searched linearly, so any order
   * reads -- and insertion order is the one that puts a result file's nuclides
   * in the order the model lists them rather than alphabetically.
   */
  function group(attrs = {}) {
    return { kind: 'group', attrs, children: new Map() };
  }

  /**
   * A dataset: values, their type, and attributes.
   *
   * `dims` is for the one case that is not a list of numbers: a probabilistic
   * result, which is a matrix of one row per output time and one column per
   * realisation. The values are still given flat -- HDF5 stores them flat, in
   * exactly this order, with the last dimension varying fastest -- and `dims`
   * says how to read them. Given as `[times, realisations]`, `flat[t * n + r]`
   * is realisation `r` at time `t`, which is the layout the result browser
   * expects; see ./resultfile.js.
   */
  function dataset(data, dt = F64, attrs = {}, dims = null) {
    if (dims) {
      const want = dims.reduce((a, b) => a * b, 1);
      const got = data.length ?? 0;
      if (want !== got) {
        throw new HDF5Error(
          `A ${dims.join('×')} dataset holds ${want} values and was given ${got}`);
      }
    }
    return { kind: 'dataset', data, dt, attrs, dims };
  }

  /**
   * Puts `node` at `path` in `root`, making the groups on the way.
   *
   * A name with a slash in it cannot be a link name -- that is the one character
   * HDF5 reserves -- so the caller is expected to have dealt with it. Adding a
   * second thing at one path is refused rather than silently dropping the first:
   * two results with one name is a bug in whoever built the tree.
   */
  function put(root, path, node) {
    const parts = path.filter((p) => p !== '');
    if (!parts.length) throw new HDF5Error('Nothing can be put at the root itself');
    let at = root;
    for (const part of parts.slice(0, -1)) {
      if (part.includes('/')) throw new HDF5Error(`'${part}' cannot be a name: it has a slash in it`);
      let next = at.children.get(part);
      if (!next) {
        next = group();
        at.children.set(part, next);
      } else if (next.kind !== 'group') {
        throw new HDF5Error(`'${part}' is a dataset, so nothing can be put inside it`);
      }
      at = next;
    }
    const last = parts[parts.length - 1];
    if (last.includes('/')) throw new HDF5Error(`'${last}' cannot be a name: it has a slash in it`);
    if (at.children.has(last)) throw new HDF5Error(`There is already something at ${parts.join('/')}`);
    at.children.set(last, node);
    return node;
  }

  // --- the checksum -----------------------------------------------------------

  const rot = (x, k) => (((x << k) | (x >>> (32 - k))) >>> 0);

  /**
   * Jenkins' lookup3, as `H5_checksum_lookup3` calls it with an initial value of
   * zero. Every version 2 structure ends with four bytes of this over everything
   * before it, and a reader that does not like the answer will not open the file.
   */
  function lookup3(u8, from = 0, length = u8.length - from) {
    let a = (0xdeadbeef + length) >>> 0;
    let b = a;
    let c = a;
    let k = from;
    let n = length;
    const word = (p) => ((u8[p] | (u8[p + 1] << 8) | (u8[p + 2] << 16) | (u8[p + 3] << 24)) >>> 0);
    while (n > 12) {
      a = (a + word(k)) >>> 0;
      b = (b + word(k + 4)) >>> 0;
      c = (c + word(k + 8)) >>> 0;
      a = (a - c) >>> 0; a = (a ^ rot(c, 4)) >>> 0; c = (c + b) >>> 0;
      b = (b - a) >>> 0; b = (b ^ rot(a, 6)) >>> 0; a = (a + c) >>> 0;
      c = (c - b) >>> 0; c = (c ^ rot(b, 8)) >>> 0; b = (b + a) >>> 0;
      a = (a - c) >>> 0; a = (a ^ rot(c, 16)) >>> 0; c = (c + b) >>> 0;
      b = (b - a) >>> 0; b = (b ^ rot(a, 19)) >>> 0; a = (a + c) >>> 0;
      c = (c - b) >>> 0; c = (c ^ rot(b, 4)) >>> 0; b = (b + a) >>> 0;
      k += 12;
      n -= 12;
    }
    // The tail, byte by byte, falling through as the C does.
    /* eslint-disable no-fallthrough */
    switch (n) {
      case 12: c = (c + (u8[k + 11] << 24)) >>> 0;
      case 11: c = (c + (u8[k + 10] << 16)) >>> 0;
      case 10: c = (c + (u8[k + 9] << 8)) >>> 0;
      case 9: c = (c + u8[k + 8]) >>> 0;
      case 8: b = (b + (u8[k + 7] << 24)) >>> 0;
      case 7: b = (b + (u8[k + 6] << 16)) >>> 0;
      case 6: b = (b + (u8[k + 5] << 8)) >>> 0;
      case 5: b = (b + u8[k + 4]) >>> 0;
      case 4: a = (a + (u8[k + 3] << 24)) >>> 0;
      case 3: a = (a + (u8[k + 2] << 16)) >>> 0;
      case 2: a = (a + (u8[k + 1] << 8)) >>> 0;
      case 1: a = (a + u8[k]) >>> 0; break;
      case 0: return c;
    }
    /* eslint-enable no-fallthrough */
    c = (c ^ b) >>> 0; c = (c - rot(b, 14)) >>> 0;
    a = (a ^ c) >>> 0; a = (a - rot(c, 11)) >>> 0;
    b = (b ^ a) >>> 0; b = (b - rot(a, 25)) >>> 0;
    c = (c ^ b) >>> 0; c = (c - rot(b, 16)) >>> 0;
    a = (a ^ c) >>> 0; a = (a - rot(c, 4)) >>> 0;
    b = (b ^ a) >>> 0; b = (b - rot(a, 14)) >>> 0;
    c = (c ^ b) >>> 0; c = (c - rot(b, 24)) >>> 0;
    return c >>> 0;
  }

  // --- the global heap --------------------------------------------------------

  /**
   * Every variable-length string in the file, pooled.
   *
   * A string on disk is not the characters: it is a 16-byte "global heap ID" --
   * how many characters, which collection, which object in it -- and the
   * characters live in the collection. Pooling is this writer's own: libhdf5
   * inserts each string as it comes, so a file of two thousand series has
   * `TRUE` in it two thousand times. Here identical strings share one object,
   * which for a result file is most of them.
   *
   * The two-byte object index is why there can be more than one collection.
   */
  class Strings {
    constructor() {
      this.collections = [[]];
      this.where = new Map();
    }

    /** The heap ID parts for `text`, adding it if it is new. */
    add(text) {
      const s = String(text);
      const found = this.where.get(s);
      if (found) return found;
      let c = this.collections.length - 1;
      if (this.collections[c].length >= HEAP_MAX_OBJECTS) {
        this.collections.push([]);
        c += 1;
      }
      const data = UTF8.encode(s);
      this.collections[c].push(data);
      const id = { collection: c, index: this.collections[c].length, length: data.length };
      this.where.set(s, id);
      return id;
    }

    /** How big collection `c` has to be, header and padding included. */
    size(c) {
      let n = 16;
      for (const data of this.collections[c]) n += 16 + Math.ceil(data.length / 8) * 8;
      // The specification's minimum. Anything left over is described by a
      // free-space object, which is what index 0 means.
      return Math.max(HEAP_MINIMUM, n + 16);
    }
  }

  // --- laying the file out ----------------------------------------------------

  /** The values of an attribute, in a shape the writer can size and write. */
  function attribute(name, value, strings) {
    const list = Array.isArray(value) || ArrayBuffer.isView(value);
    const values = list ? Array.from(value) : [value];
    const dims = list ? [values.length] : [];
    // A boolean is written as TRUE or FALSE, which is what Ecolego's files say
    // (an enumerated type there) and what every reader of them tests for. An
    // enumeration would be two more datatype classes for one bit.
    const text = values.some((v) => typeof v === 'string' || typeof v === 'boolean');
    const dt = text ? STR : F64;
    const out = values.map((v) => {
      if (!text) return Number(v);
      const s = typeof v === 'boolean' ? (v ? 'TRUE' : 'FALSE') : String(v);
      return strings.add(s);
    });
    return { name, dt, dims, values: out, nameBytes: UTF8.encode(name) };
  }

  /** How many values a dataspace holds. */
  const count = (dims) => (dims.length ? dims.reduce((a, b) => a * b, 1) : 1);

  /** The bytes an attribute message takes, header excluded. */
  function attributeSize(a) {
    return 9 + a.nameBytes.length + 1
      + datatypeBytes(a.dt).length + dataspaceBytes(a.dims).length
      + count(a.dims) * a.dt.size;
  }

  /** The bytes a link message takes, header excluded. */
  function linkSize(nameBytes) {
    return 2 + (nameBytes.length > 255 ? 2 : 1) + nameBytes.length + 8;
  }

  /**
   * Walks the tree once: normalises the attributes, pools the strings, and works
   * out how big every object header and data block will be.
   *
   * Nothing here needs an address, which is why it can all be done first -- an
   * address is eight bytes whatever it points at.
   */
  function plan(root) {
    const strings = new Strings();
    const objects = [];

    const visit = (node, name, nameBytes) => {
      const attrs = Object.entries(node.attrs ?? {})
        .filter(([, v]) => v !== null && v !== undefined)
        .map(([k, v]) => attribute(k, v, strings));
      const o = {
        node, name, nameBytes, attrs, addr: 0, headerSize: 0, dataAddr: 0, dataSize: 0,
      };
      objects.push(o);
      // Every object with attributes says so: without it a reader looks for
      // them in a fractal heap that is not there. `AttrInfo` with both
      // addresses undefined is what "they are in this header" means.
      let msgs = attrs.reduce((n, a) => n + 4 + attributeSize(a), 0)
        + (attrs.length ? 4 + 18 : 0);
      if (node.kind === 'group') {
        o.children = [...node.children].map(([childName, child]) => {
          const bytes = UTF8.encode(childName);
          if (!bytes.length) throw new HDF5Error('A link cannot have an empty name');
          return { name: childName, bytes, of: visit(child, childName, bytes) };
        });
        msgs += 4 + 18 + 4 + 2; // link info, group info
        for (const c of o.children) msgs += 4 + linkSize(c.bytes);
      } else {
        const data = node.data;
        const n = data.length ?? 0;
        // A shape the caller gave, or the list it is: `dataset` has already
        // checked that the two agree about how many values there are.
        o.dims = node.dims ?? [n];
        o.dataSize = n * node.dt.size;
        // Nothing to point at, and address zero is the superblock: a
        // dataset with no values says so with the undefined address.
        if (!o.dataSize) o.dataAddr = -1;
        if (node.dt.kind === 'vlenstr') o.ids = Array.from(data, (s) => strings.add(s));
        msgs += 4 + dataspaceBytes(o.dims).length
          + 4 + datatypeBytes(node.dt).length
          + 4 + 2 // fill value
          + 4 + 18; // layout
      }
      o.headerSize = 14 + msgs;
      return o;
    };

    const rootObject = visit(root, '', new Uint8Array(0));

    // Where everything goes. The superblock first, then the strings -- they
    // have to be placed before any header is written, because an attribute's
    // data is the address of the collection holding it.
    let at = 48;
    const heapAt = strings.collections.map((_, c) => {
      const addr = at;
      at += strings.size(c);
      return addr;
    });
    for (const o of objects) {
      o.addr = at;
      at += o.headerSize;
    }
    for (const o of objects) {
      if (o.node.kind !== 'dataset' || !o.dataSize) continue;
      at = Math.ceil(at / 8) * 8;
      o.dataAddr = at;
      at += o.dataSize;
    }
    return { strings, heapAt, objects, root: rootObject, size: at };
  }

  // --- writing ----------------------------------------------------------------

  /** A cursor over the output, with the widths HDF5 uses. */
  class Out {
    constructor(size) {
      this.buf = new ArrayBuffer(size);
      this.u8 = new Uint8Array(this.buf);
      this.at = 0;
    }

    seek(p) { this.at = p; return this; }

    byte(v) { this.u8[this.at++] = v & 0xff; return this; }

    bytes(list) { for (const v of list) this.u8[this.at++] = v & 0xff; return this; }

    u16(v) { return this.byte(v).byte(v >>> 8); }

    u32(v) { return this.byte(v).byte(v >>> 8).byte(v >>> 16).byte(v >>> 24); }

    /**
     * Eight bytes, little-endian, from an ordinary number -- which holds every
     * address a browser can make a file at, and a good deal more. `-1` is the
     * undefined address, which is all ones.
     */
    u64(v) {
      if (v < 0) return this.bytes([255, 255, 255, 255, 255, 255, 255, 255]);
      let n = v;
      for (let i = 0; i < 8; i++) {
        this.u8[this.at++] = n % 256;
        n = Math.floor(n / 256);
      }
      return this;
    }

    /** Four bytes of lookup3 over everything written since `from`. */
    checksum(from) { return this.u32(lookup3(this.u8, from, this.at - from)); }
  }

  /** One message: its four-byte header, then its bytes. */
  function message(out, type, bytes) {
    out.byte(type).u16(bytes.length).byte(0).bytes(bytes);
  }

  /** The 16 bytes that stand for one variable-length string. */
  function heapId(out, id, heapAt) {
    out.u32(id.length).u64(heapAt[id.collection]).u32(id.index);
  }

  /** An attribute's values, whatever kind they are. */
  function attributeData(out, a, heapAt) {
    if (a.dt.kind === 'vlenstr') {
      for (const id of a.values) heapId(out, id, heapAt);
      return;
    }
    const dv = new DataView(out.buf);
    for (const v of a.values) {
      dv.setFloat64(out.at, v, true);
      out.at += 8;
    }
  }

  /**
   * The file, as bytes.
   *
   * @param {object} root the tree, from `group()`, `dataset()` and `put()`
   * @returns {Uint8Array}
   */
  function writeHDF5(root) {
    if (root?.kind !== 'group') throw new HDF5Error('The root of a file is a group');
    const { strings, heapAt, objects, root: rootObject, size } = plan(root);
    const out = new Out(size);

    // --- the superblock, version 2.
    out.bytes(SIGNATURE).byte(2).byte(8).byte(8).byte(0)
      .u64(0) // base address
      .u64(-1) // no superblock extension
      .u64(size) // end of file
      .u64(rootObject.addr)
      .checksum(0);

    // --- the strings.
    strings.collections.forEach((objs, c) => {
      const start = heapAt[c];
      const total = strings.size(c);
      out.seek(start).bytes([0x47, 0x43, 0x4f, 0x4c]).byte(1).bytes([0, 0, 0]).u64(total);
      objs.forEach((data, i) => {
        // The reference count is what libhdf5 writes for a string the file
        // itself points at, which is nothing: it counts *references*, the
        // HDF5 kind, and there are none.
        out.u16(i + 1).u16(0).u32(0).u64(data.length);
        out.bytes(data);
        out.at = Math.ceil(out.at / 8) * 8;
      });
      // What is left is one object with index zero, which is how a
      // collection says "free space" -- and there always is some, because a
      // collection has a minimum size and most hold far less than it.
      const left = start + total - out.at;
      if (left >= 16) out.u16(0).u16(0).u32(0).u64(left);
    });

    // --- the objects.
    for (const o of objects) {
      out.seek(o.addr).bytes([0x4f, 0x48, 0x44, 0x52]).byte(2).byte(2);
      out.u32(o.headerSize - 14);
      const node = o.node;
      if (node.kind === 'group') {
        // Undefined addresses for both indexes: the links are here, in
        // this header, rather than in a fractal heap.
        message(out, MSG.LINK_INFO, [0, 0, ...new Array(16).fill(255)]);
        message(out, MSG.GROUP_INFO, [0, 0]);
        for (const c of o.children) {
          const long = c.bytes.length > 255;
          const link = [1, long ? 1 : 0];
          if (long) link.push(c.bytes.length & 0xff, (c.bytes.length >>> 8) & 0xff);
          else link.push(c.bytes.length);
          for (const b of c.bytes) link.push(b);
          for (let i = 0; i < 8; i++) link.push(Math.floor(c.of.addr / 2 ** (8 * i)) & 0xff);
          message(out, MSG.LINK, link);
        }
      } else {
        message(out, MSG.DATASPACE, dataspaceBytes(o.dims));
        message(out, MSG.DATATYPE, datatypeBytes(node.dt));
        // Version 3, allocated late, with no fill value of its own: every
        // byte of this dataset is written, so there is nothing to fill.
        message(out, MSG.FILL_VALUE, [3, 2]);
        const layout = [3, 1];
        for (let i = 0; i < 8; i++) layout.push(Math.floor(o.dataAddr / 2 ** (8 * i)) & 0xff);
        for (let i = 0; i < 8; i++) layout.push(Math.floor(o.dataSize / 2 ** (8 * i)) & 0xff);
        message(out, MSG.LAYOUT, layout);
      }
      if (o.attrs.length) {
        message(out, MSG.ATTRIBUTE_INFO, [0, 0, ...new Array(16).fill(255)]);
        for (const a of o.attrs) {
          const dt = datatypeBytes(a.dt);
          const ds = dataspaceBytes(a.dims);
          out.byte(MSG.ATTRIBUTE).u16(attributeSize(a)).byte(0);
          out.byte(3).byte(0).u16(a.nameBytes.length + 1).u16(dt.length).u16(ds.length).byte(0);
          out.bytes(a.nameBytes).byte(0).bytes(dt).bytes(ds);
          attributeData(out, a, heapAt);
        }
      }
      out.checksum(o.addr);
    }

    // --- the numbers.
    for (const o of objects) {
      if (o.node.kind !== 'dataset' || !o.dataSize) continue;
      out.seek(o.dataAddr);
      const { dt, data } = o.node;
      if (dt.kind === 'vlenstr') {
        for (const id of o.ids) heapId(out, id, heapAt);
      } else if (dt.kind === 'float' && dt.size === 8) {
        new Float64Array(out.buf, o.dataAddr, data.length).set(data);
      } else if (dt.kind === 'float') {
        new Float32Array(out.buf, o.dataAddr, data.length).set(data);
      } else {
        new Int32Array(out.buf, o.dataAddr, data.length).set(data);
      }
    }
    return out.u8;
  }

  return { HDF5Error, F64, F32, I32, STR, group, dataset, put, lookup3, writeHDF5 };
});
