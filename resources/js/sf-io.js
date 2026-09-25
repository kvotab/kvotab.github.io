/* ==========================================================================
   SIMPLEFUNCTIONS.HTML: FILES IN AND OUT

   Groundwater tables: CSV, TSV or text (comma, semicolon, tab or blank
   separated, decimal comma understood), or an Excel workbook, from which
   the sheet called "Groundwater" is taken if there is one, otherwise the
   first sheet with a pH column (so the PSAR parameter workbook,
   SFKParameters.xlsx, can be dropped as it is).

   Reference solubilities to compare a run with: a table with one column per
   element (CSV or Excel), a MATLAB file (level 5, as SR-Site and the PSAR
   stored CSOL: a struct array with one field per element, or a struct of
   arrays, compressed or not), or an HDF5 file with one dataset per element.
   HDF5 needs h5wasm, fetched from the CDN the first time an .h5 file is
   opened.

   Everything is read in the browser; nothing is sent anywhere.
   ========================================================================== */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.SFIO = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const ELEMENTS = ['Sr', 'Ra', 'Zr', 'Nb', 'Tc', 'Ni', 'Pd', 'Ag', 'Sn', 'Se', 'Th', 'Pa', 'U', 'Np', 'Pu', 'Am', 'Cm', 'Sm', 'Ho', 'Pb'];

  /* ---------------------------------------------------------------------
     Delimited text
     --------------------------------------------------------------------- */
  function splitLine(line, sep) {
    if (sep === 'ws') return line.trim().split(/\s+/);
    const out = [];
    let cur = '';
    let q = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (q) {
        if (ch === '"') { if (line[i + 1] === '"') { cur += '"'; i++; } else q = false; } else cur += ch;
      } else if (ch === '"') q = true;
      else if (ch === sep) { out.push(cur); cur = ''; } else cur += ch;
    }
    out.push(cur);
    return out.map((s) => s.trim());
  }

  function detectSeparator(lines) {
    const sample = lines.slice(0, 20);
    const counts = { '\t': 0, ';': 0, ',': 0 };
    for (const l of sample) for (const s of Object.keys(counts)) counts[s] += l.split(s).length - 1;
    if (counts['\t'] >= sample.length) return '\t';
    if (counts[';'] >= sample.length && counts[';'] >= counts[','] / 2) return ';';
    if (counts[','] >= sample.length) return ',';
    return 'ws';
  }

  /** Text → rows of cells (strings). Numbers are converted later, per column. */
  function parseDelimited(text) {
    const lines = String(text).replace(/^﻿/, '').split(/\r?\n/).filter((l) => l.trim() !== '' && !/^\s*#/.test(l));
    if (!lines.length) return [];
    const sep = detectSeparator(lines);
    return lines.map((l) => splitLine(l, sep));
  }

  /* ---------------------------------------------------------------------
     Excel workbooks (needs JSZip)
     --------------------------------------------------------------------- */
  const XML_ENTITIES = { '&lt;': '<', '&gt;': '>', '&amp;': '&', '&quot;': '"', '&apos;': "'" };
  function unxml(s) {
    return s.replace(/&(lt|gt|amp|quot|apos);/g, (m) => XML_ENTITIES[m]).replace(/&#(\d+);/g, (m, d) => String.fromCodePoint(Number(d)));
  }
  function attrs(tag) {
    const out = {};
    for (const m of tag.matchAll(/([\w:]+)="([^"]*)"/g)) out[m[1]] = m[2];
    return out;
  }
  function colIndex(ref) {
    const m = /^([A-Z]+)/.exec(ref);
    if (!m) return 0;
    let c = 0;
    for (const ch of m[1]) c = c * 26 + (ch.charCodeAt(0) - 64);
    return c - 1;
  }
  function sheetRows(xml, shared) {
    const rows = [];
    for (const rowM of xml.matchAll(/<row\b[^>]*>([\s\S]*?)<\/row>/g)) {
      const cells = [];
      for (const cM of rowM[1].matchAll(/<c\b([^>]*?)(?:\/>|>([\s\S]*?)<\/c>)/g)) {
        const a = attrs(cM[1]);
        const inner = cM[2] || '';
        const ci = colIndex(a.r || '');
        let val = '';
        const vM = /<v>([\s\S]*?)<\/v>/.exec(inner);
        if (a.t === 's') val = shared[Number(vM ? vM[1] : -1)] ?? '';
        else if (a.t === 'inlineStr') val = unxml((inner.match(/<t[^>]*>([\s\S]*?)<\/t>/g) || []).map((t) => t.replace(/<[^>]+>/g, '')).join(''));
        else if (a.t === 'b') val = vM && vM[1] === '1' ? 'TRUE' : 'FALSE';
        else if (a.t === 'str' || a.t === 'e') val = vM ? unxml(vM[1]) : '';
        else val = vM ? Number(vM[1]) : '';
        while (cells.length < ci) cells.push('');
        cells[ci] = val;
      }
      if (cells.some((c) => c !== '')) rows.push(cells);
    }
    return rows;
  }

  function jszip() {
    if (typeof JSZip !== 'undefined') return JSZip;
    if (typeof require === 'function') { try { return require('jszip'); } catch (e) { /* not installed */ } }
    throw new Error('Reading an Excel file needs JSZip, which did not load. Save the sheet as CSV instead.');
  }

  /**
   * The first sheet of a workbook, in the order `rank` gives, for which
   * `accept(rows)` returns something truthy: {name, rows, value, sheets}.
   */
  async function findSheet(buf, accept, rank) {
    const zip = await jszip().loadAsync(buf);
    const wbFile = zip.file('xl/workbook.xml');
    if (!wbFile) throw new Error('not an Excel workbook (no xl/workbook.xml)');
    const wbXml = await wbFile.async('string');
    const relXml = await zip.file('xl/_rels/workbook.xml.rels').async('string');
    const rels = {};
    for (const m of relXml.matchAll(/<Relationship\b([^>]*)\/?>/g)) { const a = attrs(m[1]); rels[a.Id] = a.Target; }
    const sheets = [];
    for (const m of wbXml.matchAll(/<sheet\b([^>]*)\/?>/g)) {
      const a = attrs(m[1]);
      sheets.push({ name: unxml(a.name || ''), path: (rels[a['r:id']] || '').replace(/^\/?(xl\/)?/, 'xl/') });
    }
    let shared = [];
    const ssFile = zip.file('xl/sharedStrings.xml');
    if (ssFile) {
      const ss = await ssFile.async('string');
      shared = Array.from(ss.matchAll(/<si>([\s\S]*?)<\/si>/g), (m) => unxml((m[1].match(/<t[^>]*>([\s\S]*?)<\/t>/g) || []).map((t) => t.replace(/<[^>]+>/g, '')).join('')));
    }
    const order = sheets.map((s, i) => i);
    if (rank) order.sort((a, b) => rank(sheets[b].name) - rank(sheets[a].name));
    const errors = [];
    for (const i of order) {
      const f = zip.file(sheets[i].path);
      if (!f) continue;
      const rows = sheetRows(await f.async('string'), shared);
      if (!rows.length) continue;
      try {
        const value = accept(rows);
        if (value) return { name: sheets[i].name, rows, value, sheets: sheets.map((s) => s.name), errors };
      } catch (e) {
        errors.push(`${sheets[i].name}: ${e.message}`);
      }
    }
    return { name: '', rows: [], value: null, sheets: sheets.map((s) => s.name), errors };
  }

  /* ---------------------------------------------------------------------
     Groundwater tables
     --------------------------------------------------------------------- */
  /**
   * A groundwater table from a File (browser) or {name, text|buffer}.
   * Returns {waters, headers, map, sheet, skipped, note}.
   */
  async function readGroundwater(file, opts = {}) {
    const name = file.name || 'table';
    const SFModel = opts.SFModel || (typeof root !== 'undefined' && root.SFModel) || globalThis.SFModel;
    if (/\.(xlsx|xlsm)$/i.test(name)) {
      const buf = file.buffer || await file.arrayBuffer();
      const got = await findSheet(buf, (rows) => {
        const res = SFModel.watersFromRows(rows, opts);
        return res.waters.length ? res : null;
      }, (n) => (/groundwater|grundvatten/i.test(n) ? 1 : 0));
      if (!got.value) throw new Error(`no sheet of ${name} has a groundwater table (columns pH, [Ca], [Cl], [Na], [SO4], [Si], IS and [HCO3-]). ${got.errors.slice(0, 3).join(' ')}`);
      return { ...got.value, sheet: got.name, note: `sheet “${got.name}”` };
    }
    const text = typeof file.text === 'function' ? await file.text() : file.text;
    const rows = parseDelimited(text);
    const res = SFModel.watersFromRows(rows, opts);
    return { ...res, sheet: '', note: '' };
  }

  /* ---------------------------------------------------------------------
     Inflate (zlib), for compressed MAT elements
     --------------------------------------------------------------------- */
  async function inflate(bytes) {
    if (typeof DecompressionStream === 'function') {
      const ds = new DecompressionStream('deflate');
      const stream = new Blob([bytes]).stream().pipeThrough(ds);
      return new Uint8Array(await new Response(stream).arrayBuffer());
    }
    if (typeof require === 'function') {
      const zlib = require('zlib');
      return new Uint8Array(zlib.inflateSync(Buffer.from(bytes)));
    }
    throw new Error('this browser cannot decompress (no DecompressionStream); save the MAT file with -v6 or as CSV');
  }

  /* ---------------------------------------------------------------------
     MATLAB level 5 MAT files
     --------------------------------------------------------------------- */
  const MI = { INT8: 1, UINT8: 2, INT16: 3, UINT16: 4, INT32: 5, UINT32: 6, SINGLE: 7, DOUBLE: 9, INT64: 12, UINT64: 13, MATRIX: 14, COMPRESSED: 15, UTF8: 16, UTF16: 17, UTF32: 18 };
  const MX = { CELL: 1, STRUCT: 2, OBJECT: 3, CHAR: 4, SPARSE: 5, DOUBLE: 6, SINGLE: 7, INT8: 8, UINT8: 9, INT16: 10, UINT16: 11, INT32: 12, UINT32: 13, INT64: 14, UINT64: 15 };

  function readNumbers(dv, off, type, nbytes, le) {
    const sizes = { 1: 1, 2: 1, 3: 2, 4: 2, 5: 4, 6: 4, 7: 4, 9: 8, 12: 8, 13: 8 };
    const sz = sizes[type];
    if (!sz) throw new Error(`MAT: unsupported numeric type ${type}`);
    const n = Math.floor(nbytes / sz);
    const out = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      const p = off + i * sz;
      switch (type) {
        case 1: out[i] = dv.getInt8(p); break;
        case 2: out[i] = dv.getUint8(p); break;
        case 3: out[i] = dv.getInt16(p, le); break;
        case 4: out[i] = dv.getUint16(p, le); break;
        case 5: out[i] = dv.getInt32(p, le); break;
        case 6: out[i] = dv.getUint32(p, le); break;
        case 7: out[i] = dv.getFloat32(p, le); break;
        case 9: out[i] = dv.getFloat64(p, le); break;
        case 12: out[i] = Number(dv.getBigInt64(p, le)); break;
        case 13: out[i] = Number(dv.getBigUint64(p, le)); break;
        default: break;
      }
    }
    return out;
  }

  /** One data element at `off`: {type, nbytes, dataOff, next}. */
  function tagAt(dv, off, le) {
    const w0 = dv.getUint32(off, le);
    if ((w0 >>> 16) !== 0) {
      // Small data element: two bytes size, two bytes type, four bytes of data.
      const type = w0 & 0xffff;
      const nbytes = w0 >>> 16;
      return { type, nbytes, dataOff: off + 4, next: off + 8 };
    }
    const nbytes = dv.getUint32(off + 4, le);
    const pad = w0 === MI.COMPRESSED ? 0 : (8 - (nbytes % 8)) % 8;
    return { type: w0, nbytes, dataOff: off + 8, next: off + 8 + nbytes + pad };
  }

  function parseMatrix(dv, off, end, le) {
    if (off >= end) return { cls: 'empty' };
    // Array flags
    let t = tagAt(dv, off, le);
    const flags = dv.getUint32(t.dataOff, le);
    const cls = flags & 0xff;
    const complex = !!(flags & 0x0800);
    off = t.next;
    // Dimensions
    t = tagAt(dv, off, le);
    const dims = Array.from(readNumbers(dv, t.dataOff, t.type, t.nbytes, le));
    off = t.next;
    // Name
    t = tagAt(dv, off, le);
    let name = '';
    for (let i = 0; i < t.nbytes; i++) name += String.fromCharCode(dv.getUint8(t.dataOff + i));
    off = t.next;
    const numel = dims.reduce((a, b) => a * b, 1);
    if (cls >= MX.DOUBLE && cls <= MX.UINT64) {
      t = tagAt(dv, off, le);
      const re = readNumbers(dv, t.dataOff, t.type, t.nbytes, le);
      return { cls: 'numeric', name, dims, data: re, complex };
    }
    if (cls === MX.CHAR) {
      t = tagAt(dv, off, le);
      const codes = readNumbers(dv, t.dataOff, t.type, t.nbytes, le);
      return { cls: 'char', name, dims, text: String.fromCharCode(...codes) };
    }
    if (cls === MX.STRUCT || cls === MX.OBJECT) {
      if (cls === MX.OBJECT) { t = tagAt(dv, off, le); off = t.next; }
      t = tagAt(dv, off, le);
      const flen = dv.getInt32(t.dataOff, le);
      off = t.next;
      t = tagAt(dv, off, le);
      const fields = [];
      for (let k = 0; k * flen < t.nbytes; k++) {
        let s = '';
        for (let i = 0; i < flen; i++) {
          const c = dv.getUint8(t.dataOff + k * flen + i);
          if (!c) break;
          s += String.fromCharCode(c);
        }
        if (s) fields.push(s);
      }
      off = t.next;
      const elements = [];
      for (let e = 0; e < numel; e++) {
        const obj = {};
        for (const f of fields) {
          const mt = tagAt(dv, off, le);
          obj[f] = mt.type === MI.MATRIX && mt.nbytes ? parseMatrix(dv, mt.dataOff, mt.dataOff + mt.nbytes, le) : { cls: 'empty' };
          off = mt.next;
        }
        elements.push(obj);
      }
      return { cls: 'struct', name, dims, fields, elements };
    }
    if (cls === MX.CELL) {
      const cells = [];
      for (let e = 0; e < numel; e++) {
        const mt = tagAt(dv, off, le);
        cells.push(mt.nbytes ? parseMatrix(dv, mt.dataOff, mt.dataOff + mt.nbytes, le) : { cls: 'empty' });
        off = mt.next;
      }
      return { cls: 'cell', name, dims, cells };
    }
    return { cls: 'unsupported', name, dims, mxClass: cls };
  }

  /** Every top-level variable of a MAT file: {name: parsed matrix}. */
  async function readMat(buffer) {
    const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
    if (bytes.length < 128) throw new Error('too short for a MAT file');
    const head = String.fromCharCode(...bytes.slice(0, 116));
    if (/^\x89HDF/.test(String.fromCharCode(...bytes.slice(512, 516))) || /MATLAB 7\.3/.test(head)) {
      throw new Error('this is a MATLAB v7.3 file (HDF5); open it as .h5 or save it with -v7');
    }
    if (!/^MATLAB 5\.0 MAT-file/.test(head)) throw new Error('not a MATLAB level 5 MAT file');
    const ei = String.fromCharCode(bytes[126], bytes[127]);
    const le = ei === 'IM';
    const vars = {};
    let off = 128;
    let dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    while (off + 8 <= bytes.length) {
      const t = tagAt(dv, off, le);
      if (t.type === MI.COMPRESSED) {
        const inner = await inflate(bytes.subarray(t.dataOff, t.dataOff + t.nbytes));
        const idv = new DataView(inner.buffer, inner.byteOffset, inner.byteLength);
        const it = tagAt(idv, 0, le);
        if (it.type === MI.MATRIX) {
          const m = parseMatrix(idv, it.dataOff, it.dataOff + it.nbytes, le);
          vars[m.name || `var${Object.keys(vars).length + 1}`] = m;
        }
      } else if (t.type === MI.MATRIX) {
        const m = parseMatrix(dv, t.dataOff, t.dataOff + t.nbytes, le);
        vars[m.name || `var${Object.keys(vars).length + 1}`] = m;
      }
      off = t.next;
      dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    }
    return vars;
  }

  /**
   * Solubilities per element out of a parsed MAT file: a struct array with
   * scalar fields (SR-Site's CSOL(i).U), a scalar struct of vectors, or
   * top-level vectors named after the elements.
   */
  function solubilitiesFromMat(vars) {
    const found = {};
    const take = (el, arr) => { if (arr && arr.length && ELEMENTS.includes(el) && !found[el]) found[el] = arr; };
    for (const v of Object.values(vars)) {
      if (v.cls === 'struct') {
        const els = v.fields.filter((f) => ELEMENTS.includes(f));
        if (!els.length) continue;
        if (v.elements.length > 1) {
          for (const el of els) {
            const a = new Float64Array(v.elements.length);
            v.elements.forEach((o, i) => { const m = o[el]; a[i] = m && m.cls === 'numeric' && m.data.length ? m.data[0] : NaN; });
            take(el, a);
          }
        } else if (v.elements.length === 1) {
          for (const el of els) { const m = v.elements[0][el]; if (m && m.cls === 'numeric') take(el, m.data); }
        }
      } else if (v.cls === 'numeric' && ELEMENTS.includes(v.name)) {
        take(v.name, v.data);
      }
    }
    return found;
  }

  /* ---------------------------------------------------------------------
     HDF5, through h5wasm fetched on demand
     --------------------------------------------------------------------- */
  const H5WASM = {
    src: 'https://cdn.jsdelivr.net/npm/h5wasm@0.9.0/dist/iife/h5wasm.min.js',
    integrity: 'sha384-0kPHehXdhwrXsjsY2cFREoF1T3bEwA7VXlpZGg3zE1DDnW294q/kakEEPAsA5JXW',
  };
  let h5Loading = null;
  function loadH5wasm() {
    if (typeof window === 'undefined') throw new Error('HDF5 needs the browser');
    if (window.h5wasm) return Promise.resolve(window.h5wasm);
    if (!h5Loading) {
      h5Loading = new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = H5WASM.src;
        s.integrity = H5WASM.integrity;
        s.crossOrigin = 'anonymous';
        s.onload = () => resolve(window.h5wasm);
        s.onerror = () => { h5Loading = null; reject(new Error('h5wasm (the HDF5 reader) could not be fetched')); };
        document.head.appendChild(s);
      });
    }
    return h5Loading;
  }

  async function solubilitiesFromH5(buffer) {
    const h5 = await loadH5wasm();
    if (h5.ready instanceof Promise) await h5.ready;
    const name = `/sf_${Date.now()}_${Math.random().toString(36).slice(2)}.h5`;
    h5.FS.writeFile(name, new Uint8Array(buffer));
    const f = new h5.File(name, 'r');
    const found = {};
    try {
      const walk = (g, depth) => {
        if (depth > 4) return;
        for (const k of g.keys()) {
          const o = g.get(k);
          if (!o) continue;
          if (o.type === 'Group') walk(o, depth + 1);
          else if (o.type === 'Dataset' && ELEMENTS.includes(k) && !found[k]) {
            const v = o.value;
            found[k] = Float64Array.from(v, Number);
          }
        }
      };
      walk(f, 0);
    } finally {
      try { f.close(); } catch (e) { /* ignore */ }
      try { h5.FS.unlink(name); } catch (e) { /* ignore */ }
    }
    return found;
  }

  /* ---------------------------------------------------------------------
     Reference solubilities, any of the formats
     --------------------------------------------------------------------- */
  function solubilitiesFromRows(rows) {
    let h = -1;
    for (let r = 0; r < Math.min(rows.length, 30); r++) {
      if (rows[r].filter((c) => ELEMENTS.includes(String(c).trim())).length >= 2) { h = r; break; }
    }
    if (h < 0) return {};
    const head = rows[h].map((c) => String(c).trim());
    const found = {};
    head.forEach((el, c) => {
      if (!ELEMENTS.includes(el)) return;
      const a = [];
      for (let r = h + 1; r < rows.length; r++) {
        const v = rows[r][c];
        const x = typeof v === 'number' ? v : Number(String(v ?? '').trim().replace(/^([-+]?\d+),(\d+)/, '$1.$2'));
        if (Number.isFinite(x)) a.push(x);
      }
      if (a.length) found[el] = Float64Array.from(a);
    });
    return found;
  }

  async function readReference(file) {
    const name = file.name || 'reference';
    const buf = file.buffer || (typeof file.arrayBuffer === 'function' ? await file.arrayBuffer() : null);
    let found = {};
    let format = '';
    if (/\.mat$/i.test(name)) {
      found = solubilitiesFromMat(await readMat(buf));
      format = 'MATLAB MAT file';
    } else if (/\.(h5|hdf5|hdf)$/i.test(name)) {
      found = await solubilitiesFromH5(buf);
      format = 'HDF5';
    } else if (/\.json$/i.test(name)) {
      // A results file written by this page.
      const text = typeof file.text === 'function' ? await file.text() : new TextDecoder().decode(buf);
      const doc = JSON.parse(text);
      if (doc && doc.S && typeof doc.S === 'object') for (const el of ELEMENTS) if (Array.isArray(doc.S[el])) found[el] = Float64Array.from(doc.S[el], Number);
      format = 'results of this page';
    } else if (/\.(xlsx|xlsm)$/i.test(name)) {
      const got = await findSheet(buf, (rows) => { const f = solubilitiesFromRows(rows); return Object.keys(f).length ? f : null; });
      found = got.value || {};
      format = `Excel, sheet “${got.name}”`;
    } else {
      const text = typeof file.text === 'function' ? await file.text() : new TextDecoder().decode(buf);
      found = solubilitiesFromRows(parseDelimited(text));
      format = 'table';
    }
    const els = Object.keys(found);
    if (!els.length) throw new Error(`${name}: no element columns or fields found (expected names such as Sr, Ra, U, Np)`);
    return { name, format, data: found, elements: ELEMENTS.filter((e) => els.includes(e)) };
  }

  /* ---------------------------------------------------------------------
     Writing
     --------------------------------------------------------------------- */
  function csvCell(v) {
    if (v === null || v === undefined) return '';
    if (typeof v === 'number') return Number.isFinite(v) ? String(v) : '';
    const s = String(v);
    return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }

  function toCsv(rows) {
    return rows.map((r) => r.map(csvCell).join(',')).join('\n');
  }

  /**
   * A MATLAB level 5 file holding one struct array CSOL(1×n) with one scalar
   * double per element and realisation — the layout SR-Site and the PSAR
   * used, so the transport tools can read it unchanged. Uncompressed.
   */
  function writeMatStructArray(varName, fields, columns, n) {
    const parts = [];
    const pad8 = (len) => (8 - (len % 8)) % 8;
    const elem = (type, bytes) => {
      const out = new Uint8Array(8 + bytes.length + pad8(bytes.length));
      const dv = new DataView(out.buffer);
      dv.setUint32(0, type, true);
      dv.setUint32(4, bytes.length, true);
      out.set(bytes, 8);
      return out;
    };
    const u32 = (arr) => { const b = new Uint8Array(arr.length * 4); const dv = new DataView(b.buffer); arr.forEach((v, i) => dv.setUint32(i * 4, v, true)); return b; };
    const i32 = (arr) => { const b = new Uint8Array(arr.length * 4); const dv = new DataView(b.buffer); arr.forEach((v, i) => dv.setInt32(i * 4, v, true)); return b; };
    const ascii = (s) => Uint8Array.from(s, (c) => c.charCodeAt(0));
    const concat = (arrs) => { const len = arrs.reduce((a, b) => a + b.length, 0); const o = new Uint8Array(len); let p = 0; for (const a of arrs) { o.set(a, p); p += a.length; } return o; };
    const scalar = (x) => {
      const d = new Uint8Array(8); new DataView(d.buffer).setFloat64(0, x, true);
      const body = concat([elem(MI.UINT32, u32([MX.DOUBLE, 0])), elem(MI.INT32, i32([1, 1])), elem(MI.INT8, new Uint8Array(0)), elem(MI.DOUBLE, d)]);
      return elem(MI.MATRIX, body);
    };
    const flen = Math.max(...fields.map((f) => f.length)) + 1;
    const names = new Uint8Array(flen * fields.length);
    fields.forEach((f, i) => names.set(ascii(f), i * flen));
    const cells = [];
    for (let i = 0; i < n; i++) for (let f = 0; f < fields.length; f++) cells.push(scalar(columns[f][i]));
    const body = concat([
      elem(MI.UINT32, u32([MX.STRUCT, 0])),
      elem(MI.INT32, i32([1, n])),
      elem(MI.INT8, ascii(varName)),
      elem(MI.INT32, i32([flen])),
      elem(MI.INT8, names),
      ...cells,
    ]);
    const header = new Uint8Array(128);
    const text = `MATLAB 5.0 MAT-file, Platform: web, Created on: ${new Date().toUTCString()} by SimpleFunctions.html`;
    header.set(ascii(text.padEnd(116, ' ').slice(0, 116)), 0);
    const hdv = new DataView(header.buffer);
    hdv.setUint16(124, 0x0100, true);
    header[126] = 'I'.charCodeAt(0);
    header[127] = 'M'.charCodeAt(0);
    parts.push(header, elem(MI.MATRIX, body));
    return concat(parts);
  }

  return {
    ELEMENTS, parseDelimited, readGroundwater, readReference, readMat, solubilitiesFromMat, solubilitiesFromRows,
    toCsv, csvCell, writeMatStructArray, inflate,
  };
}));
