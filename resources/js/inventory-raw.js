/* ==========================================================================
   CANISTER_INVENTORY.HTML: WRITING A LARGE TABLE

   The raw data -- every fuel element or canister chosen, a column for each
   part and nuclide -- runs to millions of values, more than SheetJS can
   hold as cells. This writes the workbook as it goes: the sheet's XML a few
   hundred rows at a time, deflated as it is made (CompressionStream), and
   the zip archive around it at the end. A CSV file is made the same way,
   unpacked. Only the finished bytes are kept.

   A table is { sheet, nRows, fields, values }:
     fields   columns of their own: [{label, fmt, width, values}], values an
              array of nRows (text, numbers, dates as ms since 1970);
     values   one block of numbers: {labels, fmt, width, matrix}, matrix a
              Float64Array of nRows x labels.length, a row at a time.
   fmt is 'text', 'date', 'int', 'fixed' or 'sci'. What is no finite number
   is an empty cell.

   One global: KVOT_INV_RAW (module.exports under Node). Needs
   CompressionStream('deflate-raw'), as every browser has.
   ========================================================================== */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.KVOT_INV_RAW = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const enc = new TextEncoder();
  const ROWS_AT_ONCE = 256;
  const BOM = String.fromCharCode(0xfeff);

  /* ---------------------------------------------------------------------
     Zip
     --------------------------------------------------------------------- */
  const CRC_TABLE = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c >>> 0;
    }
    return t;
  })();

  /** CRC-32 of bytes, carried on from the CRC of the bytes before them. */
  function crc32(bytes, crc = 0) {
    let c = (crc ^ 0xffffffff) >>> 0;
    for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }

  /** Deflates what a generator of byte chunks yields, as it yields it. */
  async function deflate(chunks) {
    const cs = new CompressionStream('deflate-raw');
    const writer = cs.writable.getWriter();
    const parts = [];
    let csize = 0;
    const reading = (async () => {
      const reader = cs.readable.getReader();
      for (;;) {
        const { value, done } = await reader.read();
        if (done) return;
        parts.push(value);
        csize += value.length;
      }
    })();
    let crc = 0, size = 0;
    for await (const chunk of chunks) {
      crc = crc32(chunk, crc);
      size += chunk.length;
      await writer.write(chunk);
    }
    await writer.close();
    await reading;
    return { parts, crc, size, csize };
  }

  /** A zip archive of deflated files: [{name, packed}], as byte chunks. */
  function zipOf(files, when = new Date()) {
    const time = (when.getHours() << 11) | (when.getMinutes() << 5) | (when.getSeconds() >> 1);
    const date = ((when.getFullYear() - 1980) << 9) | ((when.getMonth() + 1) << 5) | when.getDate();
    const out = [], dir = [];
    let at = 0;
    for (const f of files) {
      const name = enc.encode(f.name), p = f.packed;
      if (p.size > 0xffffffff || at + 30 + name.length + p.csize > 0xffffffff) throw new Error('the file would be over 4 GB');
      const h = new DataView(new ArrayBuffer(30));
      h.setUint32(0, 0x04034b50, true);
      h.setUint16(4, 20, true);
      h.setUint16(6, 0x0800, true);
      h.setUint16(8, 8, true);
      h.setUint16(10, time, true);
      h.setUint16(12, date, true);
      h.setUint32(14, p.crc, true);
      h.setUint32(18, p.csize, true);
      h.setUint32(22, p.size, true);
      h.setUint16(26, name.length, true);
      out.push(new Uint8Array(h.buffer), name, ...p.parts);
      dir.push({ name, p, at });
      at += 30 + name.length + p.csize;
    }
    let size = 0;
    for (const { name, p, at: local } of dir) {
      const c = new DataView(new ArrayBuffer(46));
      c.setUint32(0, 0x02014b50, true);
      c.setUint16(4, 20, true);
      c.setUint16(6, 20, true);
      c.setUint16(8, 0x0800, true);
      c.setUint16(10, 8, true);
      c.setUint16(12, time, true);
      c.setUint16(14, date, true);
      c.setUint32(16, p.crc, true);
      c.setUint32(20, p.csize, true);
      c.setUint32(24, p.size, true);
      c.setUint16(28, name.length, true);
      c.setUint32(42, local, true);
      out.push(new Uint8Array(c.buffer), name);
      size += 46 + name.length;
    }
    const e = new DataView(new ArrayBuffer(22));
    e.setUint32(0, 0x06054b50, true);
    e.setUint16(8, dir.length, true);
    e.setUint16(10, dir.length, true);
    e.setUint32(12, size, true);
    e.setUint32(16, at, true);
    out.push(new Uint8Array(e.buffer));
    return out;
  }

  /* ---------------------------------------------------------------------
     The workbook's parts
     --------------------------------------------------------------------- */
  const NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main';
  const NS_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
  const NS_PR = 'http://schemas.openxmlformats.org/package/2006/relationships';
  const HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
  /* The cell styles of styles.xml, by format. */
  const STYLE = { text: 0, sci: 1, date: 2, int: 3, fixed: 4, head: 5 };
  const DAY_MS = 86400000, EXCEL_EPOCH = 25569;

  /* Characters XML 1.0 does not allow are dropped; the rest escaped. */
  const xmlText = (s) => String(s).replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  /* Text in a cell: kept spaces at its ends said so, as Excel does (only then:
     the schema has no room for it). */
  const inlineStr = (v) => `<is><t${/^\s|\s$/.test(v) ? ' xml:space="preserve"' : ''}>${xmlText(v)}</t></is>`;

  /** A column's letters: 0 -> A, 26 -> AA. */
  function colName(j) {
    let s = '';
    for (let n = j + 1; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s;
    return s;
  }

  const STYLES = `${HEAD}<styleSheet xmlns="${NS}">`
    + '<numFmts count="3"><numFmt numFmtId="164" formatCode="0.000E+00"/><numFmt numFmtId="165" formatCode="yyyy-mm-dd"/><numFmt numFmtId="166" formatCode="0.00"/></numFmts>'
    + '<fonts count="2"><font><sz val="11"/><name val="Calibri"/><family val="2"/></font><font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font></fonts>'
    + '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
    + '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    + '<cellXfs count="6"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    + '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    + '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    + '<xf numFmtId="1" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    + '<xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    + '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
    + '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>';

  function contentTypes(nSheets) {
    let s = `${HEAD}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">`
      + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      + '<Default Extension="xml" ContentType="application/xml"/>'
      + '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
      + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>';
    for (let i = 1; i <= nSheets; i++) s += `<Override PartName="/xl/worksheets/sheet${i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`;
    return `${s}</Types>`;
  }
  const ROOT_RELS = `${HEAD}<Relationships xmlns="${NS_PR}"><Relationship Id="rId1" Type="${NS_R}/officeDocument" Target="xl/workbook.xml"/></Relationships>`;
  function workbookRels(nSheets) {
    let s = `${HEAD}<Relationships xmlns="${NS_PR}">`;
    for (let i = 1; i <= nSheets; i++) s += `<Relationship Id="rId${i}" Type="${NS_R}/worksheet" Target="worksheets/sheet${i}.xml"/>`;
    return `${s}<Relationship Id="rId${nSheets + 1}" Type="${NS_R}/styles" Target="styles.xml"/></Relationships>`;
  }
  /** The workbook: its sheets, and the filter on the first sheet's headings. */
  function workbookXml(names, filterRef) {
    let s = `${HEAD}<workbook xmlns="${NS}" xmlns:r="${NS_R}"><sheets>`;
    names.forEach((n, i) => { s += `<sheet name="${xmlText(n)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`; });
    s += '</sheets>';
    if (filterRef) s += `<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">'${xmlText(names[0].replace(/'/g, "''"))}'!${filterRef}</definedName></definedNames>`;
    return `${s}</workbook>`;
  }

  /* The columns of a table, fields first: {label, fmt, width, get(r)}. */
  function columnsOf(t) {
    const cols = t.fields.map((f) => ({ label: f.label, fmt: f.fmt || 'text', width: f.width || 12, get: (r) => f.values[r] }));
    const v = t.values;
    if (v) {
      const n = v.labels.length;
      v.labels.forEach((label, j) => cols.push({ label, fmt: v.fmt || 'sci', width: v.width || 13, get: (r) => v.matrix[r * n + j] }));
    }
    return cols;
  }

  /** A cell's XML, or '' for an empty one. */
  function cellXml(ref, fmt, v) {
    if (v === null || v === undefined || v === '') return '';
    if (fmt === 'text' || typeof v === 'string') return `<c r="${ref}" t="inlineStr">${inlineStr(String(v))}</c>`;
    if (typeof v !== 'number' || !Number.isFinite(v)) return '';
    if (fmt === 'date') return `<c r="${ref}" s="${STYLE.date}"><v>${v / DAY_MS + EXCEL_EPOCH}</v></c>`;
    return `<c r="${ref}" s="${STYLE[fmt] ?? 0}"><v>${v}</v></c>`;
  }

  /**
   * A worksheet's XML, a few hundred rows at a time: the headings bold and
   * filtered, the first row and column kept in view.
   */
  async function* sheetXml(cols, nRows, opt = {}) {
    const letters = cols.map((_, j) => colName(j));
    const last = `${letters[letters.length - 1] || 'A'}${nRows + 1}`;
    let s = `${HEAD}<worksheet xmlns="${NS}" xmlns:r="${NS_R}"><dimension ref="A1:${last}"/>`;
    if (opt.freeze) s += '<sheetViews><sheetView workbookViewId="0"><pane xSplit="1" ySplit="1" topLeftCell="B2" activePane="bottomRight" state="frozen"/><selection pane="bottomRight"/></sheetView></sheetViews>';
    s += '<sheetFormatPr defaultRowHeight="15"/><cols>';
    /* Neighbours of one width share an entry. */
    for (let j = 0; j < cols.length;) {
      let k = j;
      while (k + 1 < cols.length && cols[k + 1].width === cols[j].width) k++;
      s += `<col min="${j + 1}" max="${k + 1}" width="${cols[j].width}" customWidth="1"/>`;
      j = k + 1;
    }
    s += '</cols><sheetData><row r="1">';
    cols.forEach((c, j) => { s += `<c r="${letters[j]}1" t="inlineStr" s="${STYLE.head}">${inlineStr(String(c.label))}</c>`; });
    s += '</row>';
    for (let r0 = 0; r0 < nRows; r0 += ROWS_AT_ONCE) {
      const parts = [s];
      s = '';
      for (let r = r0, end = Math.min(nRows, r0 + ROWS_AT_ONCE); r < end; r++) {
        const n = r + 2;
        let row = `<row r="${n}">`;
        for (let j = 0; j < cols.length; j++) row += cellXml(`${letters[j]}${n}`, cols[j].fmt, cols[j].get(r));
        parts.push(`${row}</row>`);
      }
      yield enc.encode(parts.join(''));
      if (opt.progress) opt.progress(Math.min(1, (r0 + ROWS_AT_ONCE) / nRows));
    }
    yield enc.encode(`${s}</sheetData>${opt.filter ? `<autoFilter ref="A1:${last}"/>` : ''}</worksheet>`);
  }

  async function* once(text) { yield enc.encode(text); }

  /**
   * The workbook of a table and a sheet of what it is (about: [[what,
   * value]]), as byte chunks of the .xlsx file.
   */
  async function xlsx(table, about = [], opt = {}) {
    const cols = columnsOf(table);
    if (table.nRows + 1 > 1048576 || cols.length > 16384) throw new Error(`a sheet holds at most 1 048 576 rows and 16 384 columns; this one would have ${table.nRows + 1} and ${cols.length}: save it as CSV`);
    const aboutCols = [{ label: 'What', fmt: 'text', width: 22, get: (r) => about[r][0] }, { label: 'Value', fmt: 'text', width: 100, get: (r) => about[r][1] }];
    const names = [table.sheet || 'Data', 'About'];
    const lastRef = `$A$1:$${colName(cols.length - 1)}$${table.nRows + 1}`;
    const files = [
      { name: '[Content_Types].xml', packed: await deflate(once(contentTypes(2))) },
      { name: '_rels/.rels', packed: await deflate(once(ROOT_RELS)) },
      { name: 'xl/workbook.xml', packed: await deflate(once(workbookXml(names, lastRef))) },
      { name: 'xl/_rels/workbook.xml.rels', packed: await deflate(once(workbookRels(2))) },
      { name: 'xl/styles.xml', packed: await deflate(once(STYLES)) },
      { name: 'xl/worksheets/sheet1.xml', packed: await deflate(sheetXml(cols, table.nRows, { freeze: true, filter: true, progress: opt.progress })) },
      { name: 'xl/worksheets/sheet2.xml', packed: await deflate(sheetXml(aboutCols, about.length)) },
    ];
    return zipOf(files);
  }

  /* ---------------------------------------------------------------------
     CSV
     --------------------------------------------------------------------- */
  function csvField(v, fmt) {
    if (v === null || v === undefined) return '';
    if (typeof v === 'number') {
      if (!Number.isFinite(v)) return '';
      return fmt === 'date' ? new Date(v).toISOString().slice(0, 10) : String(v);
    }
    const s = String(v);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }

  /**
   * The table as CSV (UTF-8 with its mark, commas, CRLF), the lines of
   * `head` first as comments (# ...), as byte chunks.
   */
  function csv(table, head = [], opt = {}) {
    const cols = columnsOf(table);
    const out = [enc.encode(`${BOM}${head.map((l) => `# ${l}\r\n`).join('')}${cols.map((c) => csvField(c.label)).join(',')}\r\n`)];
    for (let r0 = 0; r0 < table.nRows; r0 += ROWS_AT_ONCE) {
      const lines = [];
      for (let r = r0, end = Math.min(table.nRows, r0 + ROWS_AT_ONCE); r < end; r++) lines.push(cols.map((c) => csvField(c.get(r), c.fmt)).join(','));
      out.push(enc.encode(`${lines.join('\r\n')}\r\n`));
      if (opt.progress) opt.progress(Math.min(1, (r0 + ROWS_AT_ONCE) / table.nRows));
    }
    return out;
  }

  return { crc32, deflate, zipOf, colName, xmlText, sheetXml, xlsx, csv, STYLE };
});
