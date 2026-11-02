/* ==========================================================================
   CANISTER_INVENTORY.HTML: AN EARLIER ASSESSMENT TO COMPARE WITH (PSAR)

   SKB's PSAR gave the spent fuel's radionuclide inventory in two documents,
   and the page reads each of them when it is opened:

     the report     "Använt kärnbränsle att hantera i KBS-3-systemet"
                    (SKBdoc 1380282, .docx): Table D-1 (the half-lives used),
                    Table D-2 (the total in Bq per kind of fuel and part,
                    with the number of elements of each), Tables E-1 to E-7
                    (canisters of low, medium and high burnup, and the
                    average BWR and PWR canister with their spread), and the
                    number of canisters of each type from its text;
     the workbook   "Data för radionuklidinventariet PSAR" (SKBdoc 1668003,
                    .xlsx): the same tables to every digit, the average
                    canister over all 5 689, and the encapsulation
                    simulation: every element with its reactor, design,
                    canister, deposition year, decay heat and burnup.

   Tables are found by what they hold (their headings and captions), never by
   where they are, and each value is read as the report writes it: decimal
   commas, spaces between thousands, per cents. Activities are in Bq at the
   year the report gives (2045 for PSAR); the workbook does not say its
   year, and is taken to be the report's.

   Nothing here is built in: every number comes from a file the visitor
   opens. The names of the Swedish reactors are the only knowledge kept
   here.

   One global: KVOT_INV_PSAR (module.exports under Node). Needs
   KVOT_INV_JSON (inventory-json.js) for nuclide names.
   ========================================================================== */
(function (root, factory) {
  const node = typeof module === 'object' && module.exports;
  const api = factory(node ? require('./inventory-json.js') : root.KVOT_INV_JSON);
  if (node) module.exports = api;
  else root.KVOT_INV_PSAR = api;
})(typeof self !== 'undefined' ? self : this, function (JSONR) {
  'use strict';

  /* The Swedish reactors as SKB's simulation names them. */
  const REACTOR_NAMES = {
    B1: 'Barsebäck 1', B2: 'Barsebäck 2', F1: 'Forsmark 1', F2: 'Forsmark 2', F3: 'Forsmark 3',
    O1: 'Oskarshamn 1', O2: 'Oskarshamn 2', O3: 'Oskarshamn 3', R1: 'Ringhals 1', R2: 'Ringhals 2',
    R3: 'Ringhals 3', R4: 'Ringhals 4', 'ÅGESTA': 'Ågesta', AGESTA: 'Ågesta', VAK: 'Kahl', 'KRB-A': 'Gundremmingen A',
    KWO: 'Obrigheim', MZFR: 'Mehrzweckforschungsreaktor',
  };
  const reactorName = (code) => REACTOR_NAMES[String(code || '').trim().toUpperCase()] || String(code || '').trim();

  /* ---------------------------------------------------------------------
     Numbers and names as the documents write them
     --------------------------------------------------------------------- */

  /**
   * A number from a Swedish document: 4,18E+09, 17,3 E+16, 47 314, -2,8%,
   * 1.0e-3. Empty is null; anything else NaN.
   */
  function svNumber(text) {
    if (typeof text === 'number') return text;
    let s = String(text ?? '').replace(/[\s   ]+/g, '').replace(/−/g, '-');
    if (s === '' || s === '-' || s === '–') return null;
    let pct = false;
    if (s.endsWith('%')) { pct = true; s = s.slice(0, -1); }
    if (/^-?\d+,\d+(e[-+]?\d+)?$/i.test(s)) s = s.replace(',', '.');
    if (!/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(s)) return NaN;
    /* A per cent read as its own decimal (-2.8e-2), not divided (-0.027999...). */
    if (pct) return /e/i.test(s) ? Number(s) / 100 : Number(`${s}e-2`);
    return Number(s);
  }

  /** A nuclide name from a table cell (Ac-227, Pa-234m), or null. */
  function cellNuclide(text) {
    const s = String(text ?? '').replace(/[\s ]+/g, '').replace(/‑|‐|–/g, '-');
    if (!/^[A-Z][a-z]?-?\d{1,3}m?\d?$/.test(s)) return null;
    const n = JSONR.nuclideOf(s);
    return n ? n.name : null;
  }

  /* ---------------------------------------------------------------------
     A zip file (a .docx is one)
     --------------------------------------------------------------------- */

  function zipEntries(bytes) {
    const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    let eocd = -1;
    for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i--) {
      if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
    }
    if (eocd < 0) throw new Error('it is not a zip file (no central directory)');
    const count = dv.getUint16(eocd + 10, true);
    let at = dv.getUint32(eocd + 16, true);
    const out = [];
    const dec = new TextDecoder('utf-8');
    for (let n = 0; n < count && at + 46 <= bytes.length; n++) {
      if (dv.getUint32(at, true) !== 0x02014b50) throw new Error('its zip directory is damaged');
      const method = dv.getUint16(at + 10, true);
      const csize = dv.getUint32(at + 20, true);
      const usize = dv.getUint32(at + 24, true);
      const nlen = dv.getUint16(at + 28, true), xlen = dv.getUint16(at + 30, true), clen = dv.getUint16(at + 32, true);
      const local = dv.getUint32(at + 42, true);
      const name = dec.decode(bytes.subarray(at + 46, at + 46 + nlen));
      const lnlen = dv.getUint16(local + 26, true), lxlen = dv.getUint16(local + 28, true);
      out.push({ name, method, csize, usize, offset: local + 30 + lnlen + lxlen });
      at += 46 + nlen + xlen + clen;
    }
    return out;
  }

  async function unzip(bytes, entry, limit = 256 << 20) {
    if (entry.usize > limit) throw new Error(`${entry.name} unpacks to more than this page reads`);
    const raw = bytes.subarray(entry.offset, entry.offset + entry.csize);
    if (entry.method === 0) return raw;
    if (entry.method !== 8) throw new Error(`${entry.name} is packed in a way this page cannot unpack (method ${entry.method})`);
    if (typeof DecompressionStream === 'undefined') throw new Error('this browser cannot unpack zip files');
    const stream = new Blob([raw]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }

  /* ---------------------------------------------------------------------
     A Word document's paragraphs and tables
     --------------------------------------------------------------------- */

  const ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" };
  const unescapeXml = (s) => s.replace(/&(#x[0-9a-f]+|#\d+|\w+);/gi, (m, e) => {
    if (e[0] === '#') return String.fromCodePoint(e[1] === 'x' || e[1] === 'X' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10));
    return ENTITIES[e] ?? m;
  });

  /**
   * The body of word/document.xml as blocks in order: paragraphs
   * {type: 'p', text} and tables {type: 'tbl', rows: [[{text, span}]]}.
   * Read with a tag scanner, not an XML parser, so that it runs anywhere;
   * Word's own markup is regular enough for that. A table inside a table is
   * read as text of its cell.
   */
  function docxBlocks(xml) {
    const blocks = [];
    const tag = /<(\/?)w:(p|tbl|tr|tc|t|tab|br|cr|noBreakHyphen|softHyphen|gridSpan|vMerge|sym)\b([^>]*?)(\/?)>|<\/?(?:[A-Za-z_][\w.-]*:)?[A-Za-z_][\w.-]*\b[^>]*>|([^<]+)/g;
    let tblDepth = 0, inT = false;
    let para = null;               // text of the paragraph being read
    let table = null, row = null, cell = null;
    for (let m = tag.exec(xml); m; m = tag.exec(xml)) {
      const [, close, name, attrs, selfClose, text] = m;
      if (text !== undefined) { if (inT && para !== null) para += unescapeXml(text); continue; }
      if (!name) continue;
      switch (name) {
        case 'tbl':
          if (!close) { tblDepth++; if (tblDepth === 1) table = { type: 'tbl', rows: [] }; }
          else { if (tblDepth === 1 && table) blocks.push(table); tblDepth--; if (!tblDepth) table = null; }
          break;
        case 'tr':
          if (tblDepth !== 1) break;
          if (!close) row = []; else if (row) { table.rows.push(row); row = null; }
          break;
        case 'tc':
          if (tblDepth !== 1) break;
          if (!close) cell = { text: '', span: 1, merged: false }; else if (cell && row) { cell.text = cell.text.replace(/\s+/g, ' ').trim(); row.push(cell); cell = null; }
          break;
        case 'gridSpan': {
          const v = /w:val="(\d+)"/.exec(attrs);
          if (cell && v) cell.span = Number(v[1]);
          break;
        }
        case 'vMerge':
          if (cell && !/w:val="restart"/.test(attrs)) cell.merged = true;
          break;
        case 'p':
          if (!close && !selfClose) para = '';
          else if (close || selfClose) {
            const t = (para || '').replace(/\s+/g, ' ').trim();
            if (tblDepth) { if (cell) cell.text += (cell.text ? ' ' : '') + t; } else if (t) blocks.push({ type: 'p', text: t });
            para = null;
          }
          break;
        case 't':
          inT = !close && !selfClose;
          break;
        case 'tab': case 'br': case 'cr':
          if (para !== null && !close) para += ' ';
          break;
        case 'noBreakHyphen':
          if (para !== null && !close) para += '-';
          break;
        case 'sym':
          break;
        default:
      }
    }
    return blocks;
  }

  /** A table's rows with merged cells spread over the columns they span. */
  function gridRows(table) {
    return table.rows.map((r) => {
      const out = [];
      for (const c of r) for (let i = 0; i < c.span; i++) out.push(i === 0 ? c.text : '');
      return out;
    });
  }

  /**
   * A table's rows with a spanning heading repeated under every column it
   * spans, and, in the first row, an empty heading taking the one before it
   * (a heading over several columns typed in the first of them).
   */
  function headRows(table) {
    return table.rows.map((r, k) => {
      const out = [];
      for (const c of r) for (let i = 0; i < c.span; i++) out.push(c.text);
      if (k === 0) for (let i = 2; i < out.length; i++) if (!out[i]) out[i] = out[i - 1];
      return out;
    });
  }

  const lc = (s) => String(s || '').toLowerCase();

  /* ---------------------------------------------------------------------
     References: an inventory to compare with
     --------------------------------------------------------------------- */

  /**
   * @typedef {Object} Reference
   * @property {string} id
   * @property {string} label       what it is, in words
   * @property {string} scope       'all' | 'BWR' | 'PWR' | a category
   * @property {string} kind        'average' (per canister) | 'total' | 'canister'
   * @property {string} unit        'Bq' | 'mol'
   * @property {number} year        the year its values hold for
   * @property {Map<string, number>} values      by nuclide name
   * @property {Map<string, Map<string, number>>} [parts]   by part: fuel, structural_material, crud, control_rods
   * @property {Map<string, number>} [low]   relative spread to a low-burnup canister (-0.2 is 20 % less)
   * @property {Map<string, number>} [high]
   * @property {number} [count]     canisters (average) or elements (total) it stands for
   * @property {string} source      file name
   * @property {string} where       table or sheet
   * @property {number} digits      significant digits the file gives
   */

  const PART_WORDS = [
    [/kuts|pellet|bränsle-?\s*kutsar|bränslekutsar/i, 'fuel'],
    [/konstr|structur/i, 'structural_material'],
    [/styr|control/i, 'control_rods'],
    [/crud/i, 'crud'],
  ];
  const partOf = (text) => { for (const [re, p] of PART_WORDS) if (re.test(text)) return p; return null; };

  const CATEGORY_WORDS = [
    [/^bwr/i, 'BWR'], [/^pwr/i, 'PWR'], [/ågesta|agesta/i, 'Ågesta'], [/swap\s*-?\s*mox/i, 'Swap MOX'],
    [/stav-?\s*skelett/i, 'Rod skeletons'], [/^total|^summa/i, 'Total'],
  ];
  const categoryOf = (text) => { for (const [re, c] of CATEGORY_WORDS) if (re.test(String(text || '').trim())) return c; return null; };

  /* ---------------------------------------------------------------------
     The report (.docx)
     --------------------------------------------------------------------- */

  function captionBefore(blocks, i) {
    for (let j = i - 1; j >= 0 && j >= i - 3; j--) if (blocks[j].type === 'p' && /^tabell/i.test(blocks[j].text)) return blocks[j].text;
    for (let j = i - 1; j >= 0 && j >= i - 2; j--) if (blocks[j].type === 'p') return blocks[j].text;
    return '';
  }

  /**
   * What the report holds, from its document.xml.
   *
   * @param {string} xml
   * @param {string} source - file name
   */
  function readReportXml(xml, source) {
    const blocks = docxBlocks(xml);
    const out = { kind: 'report', source, year: null, refs: [], halfLives: null, counts: { canisters: {}, elements: {} }, notes: [] };
    /* The year the activities hold for: "... gäller år 2045". */
    for (const b of blocks) {
      const m = b.type === 'p' && /gäller\s+år\s+(\d{4})/i.exec(b.text);
      if (m) { out.year = Number(m[1]); break; }
    }
    for (const b of blocks) {
      if (b.type !== 'p') continue;
      const m = /(\d[\d\s ]*)\s*BWR-kapslar\s+och\s+(\d[\d\s ]*)\s*PWR-kapslar/i.exec(b.text);
      if (m) { out.counts.canisters.BWR = svNumber(m[1]); out.counts.canisters.PWR = svNumber(m[2]); break; }
    }
    const year = () => out.year || 2045;
    blocks.forEach((b, i) => {
      if (b.type !== 'tbl' || b.rows.length < 2) return;
      const caption = captionBefore(blocks, i);
      const head = headRows(b);
      const flat = head.slice(0, 3).map((r) => r.map(lc).join(' | ')).join(' || ');
      const grid = gridRows(b);
      /* Table D-1: half-lives, two nuclides to a row. */
      if (/halver/.test(flat) && /specifik aktivitet/.test(flat)) {
        const hl = new Map();
        for (const r of grid) {
          for (let c = 0; c + 1 < r.length; c++) {
            const name = cellNuclide(r[c]);
            const t = svNumber(r[c + 1]);
            if (name && Number.isFinite(t) && t > 0) hl.set(name, t);
          }
        }
        if (hl.size) out.halfLives = { values: hl, label: 'PSAR report, Table D-1', where: 'Table D-1', source };
        return;
      }
      /* Table D-2: the total per kind of fuel and part, with a row of counts. */
      if (/bwr/.test(flat) && /pwr/.test(flat) && /ågesta/.test(flat) && /antal/.test(flat)) {
        const groups = head[0];
        const countRow = grid.find((r) => /^antal/i.test(r[0])) || [];
        const partRow = grid.find((r) => /^nuklid/i.test(r[0])) || [];
        const cols = [];
        for (let c = 1; c < partRow.length; c++) {
          const cat = categoryOf(groups[c]);
          if (!cat) continue;
          cols.push({ c, cat, part: cat === 'Total' ? null : partOf(partRow[c]), count: svNumber(countRow[c]) });
        }
        const totals = new Map();
        for (const r of grid) {
          const name = cellNuclide(r[0]);
          if (!name) continue;
          for (const col of cols) {
            const v = svNumber(r[col.c]);
            if (!totals.has(col.cat)) totals.set(col.cat, { values: new Map(), parts: new Map(), count: null });
            const t = totals.get(col.cat);
            const x = Number.isFinite(v) ? v : 0;
            t.values.set(name, (t.values.get(name) || 0) + x);
            if (col.part) {
              if (!t.parts.has(col.part)) t.parts.set(col.part, new Map());
              t.parts.get(col.part).set(name, (t.parts.get(col.part).get(name) || 0) + x);
            }
            if (col.part === 'fuel' || (col.part === null && t.count === null)) t.count = col.count;
          }
        }
        for (const [cat, t] of totals) {
          if (cat === 'Total') continue;
          if (Number.isFinite(t.count)) out.counts.elements[cat] = t.count;
          out.refs.push({
            id: `report:total:${cat}`, label: `PSAR total, ${cat}`, scope: cat, kind: 'total', unit: 'Bq', year: year(),
            values: t.values, parts: t.parts.size ? t.parts : null, count: t.count, source, where: 'Table D-2', digits: 3,
          });
        }
        return;
      }
      /* Table E-7: the average BWR and PWR canister and their spread. */
      if (/avvikelse/.test(flat) && /låg bu/.test(flat)) {
        const groups = head[0], sub = head[1] || [];
        const sets = [];
        for (let c = 1; c < groups.length; c++) {
          const type = /bwr/i.test(groups[c]) ? 'BWR' : /pwr/i.test(groups[c]) ? 'PWR' : null;
          if (type && /aktivitet/i.test(sub[c] || '') && !sets.some((s) => s.type === type)) {
            const lowC = sub.findIndex((s, k) => k > c && /låg/i.test(s));
            const highC = sub.findIndex((s, k) => k > c && /hög/i.test(s));
            sets.push({ type, c, lowC, highC });
          }
        }
        for (const s of sets) {
          const values = new Map(), low = new Map(), high = new Map();
          for (const r of grid) {
            const name = cellNuclide(r[0]);
            if (!name) continue;
            const v = svNumber(r[s.c]);
            if (Number.isFinite(v)) values.set(name, v);
            const lo = svNumber(r[s.lowC]), hi = svNumber(r[s.highC]);
            if (Number.isFinite(lo)) low.set(name, lo);
            if (Number.isFinite(hi)) high.set(name, hi);
          }
          if (!values.size) continue;
          out.refs.push({
            id: `report:average:${s.type}`, label: `PSAR average ${s.type} canister`, scope: s.type, kind: 'average', unit: 'Bq', year: year(),
            values, low, high, source, where: 'Table E-7', digits: 2,
          });
        }
        return;
      }
      /* Tables E-1 to E-6: a canister of low, medium or high burnup, by part. */
      const ecap = /tabell\s*e-?\s*(\d)\.?\s*(bwr|pwr)-kapsel med (låg|medelhög|hög) medelutbränning\s*\(([^)]*)\)/i.exec(caption);
      if (ecap && /nuklid/.test(flat)) {
        const type = ecap[2].toUpperCase();
        const level = { 'låg': 'low', 'medelhög': 'medium', 'hög': 'high' }[ecap[3].toLowerCase()];
        const hdr = grid[0];
        const cols = hdr.map((h, c) => ({ c, part: c > 0 && !/total/i.test(h) ? partOf(h) : null, total: /total/i.test(h) }));
        const values = new Map(), parts = new Map();
        for (const r of grid.slice(1)) {
          const name = cellNuclide(r[0]);
          if (!name) continue;
          let sum = 0, tot = null;
          for (const col of cols) {
            const v = svNumber(r[col.c]);
            if (col.total) tot = Number.isFinite(v) ? v : null;
            else if (col.part) {
              const x = Number.isFinite(v) ? v : 0;
              sum += x;
              if (!parts.has(col.part)) parts.set(col.part, new Map());
              parts.get(col.part).set(name, x);
            }
          }
          values.set(name, tot ?? sum);
        }
        const burnup = ecap[4].replace(/\s+/g, ' ');
        out.refs.push({
          id: `report:canister:${type}:${level}`, label: `PSAR ${type} canister, ${level} burnup (${burnup})`, scope: type, kind: 'canister',
          level, unit: 'Bq', year: year(), values, parts, source, where: `Table E-${ecap[1]}`, digits: 3,
        });
      }
    });
    const c = out.counts.canisters;
    if (Number.isFinite(c.BWR) && Number.isFinite(c.PWR)) c.all = c.BWR + c.PWR;
    if (!out.year) out.notes.push('The report does not say which year its activities hold for; 2045 is taken.');
    out.year = year();
    for (const r of out.refs) r.year = out.year;
    if (!out.refs.length && !out.halfLives) throw new Error('none of PSAR’s inventory tables (D-1, D-2, E-1 to E-7) was found in it');
    return out;
  }

  async function readReport(bytes, source) {
    const entries = zipEntries(bytes);
    const doc = entries.find((e) => e.name === 'word/document.xml');
    if (!doc) throw new Error('it is not a Word document (no word/document.xml)');
    const xml = new TextDecoder('utf-8').decode(await unzip(bytes, doc));
    return readReportXml(xml, source);
  }

  /* ---------------------------------------------------------------------
     The workbook (.xlsx), read by SheetJS
     --------------------------------------------------------------------- */

  const cellText = (v) => (v === null || v === undefined ? '' : String(v).trim());
  /* A cell's number; NaN for an empty cell (Number(null) would be 0). */
  const num = (v) => (typeof v === 'number' ? v : typeof v === 'string' && v.trim() !== '' ? (svNumber(v) ?? NaN) : NaN);

  /** Rows of a sheet, as SheetJS gives them (header: 1). */
  function rowsOf(XLSX, ws) {
    return XLSX.utils.sheet_to_json(ws, { header: 1, raw: true, defval: null, blankrows: true });
  }

  const findSheet = (wb, re) => wb.SheetNames.find((n) => re.test(n));

  /** Rows of nuclides: the column a nuclide name is in, and each row's cells. */
  function nuclideRows(rows, col) {
    const out = [];
    for (const r of rows) {
      const name = r && cellNuclide(cellText(r[col]));
      if (name) out.push({ name, r });
    }
    return out;
  }

  /* A label for a column: the nearest text at or above row `upto` in it. */
  function labelAbove(rows, col, upto) {
    for (let i = upto; i >= 0; i--) {
      const t = cellText(rows[i] && rows[i][col]);
      if (t) return t;
    }
    return '';
  }

  /**
   * What the workbook holds.
   *
   * @param {Object} wb - XLSX.read() of it
   * @param {Object} XLSX - SheetJS
   * @param {string} source - file name
   * @param {number} [year] - the year its activities hold for
   */
  function readWorkbook(wb, XLSX, source, year = 2045) {
    const out = { kind: 'workbook', source, year, refs: [], canisters: null, counts: { canisters: {}, elements: {} }, notes: [] };

    /* The total per kind of fuel, and the average canister over them all. */
    const totName = findSheet(wb, /totalt\s+radionuklidinventarium/i);
    if (totName) {
      const rows = rowsOf(XLSX, wb.Sheets[totName]);
      const hr = rows.findIndex((r) => r && r.some((v) => /^nuklid$/i.test(cellText(v))));
      if (hr > 0) {
        const nc = rows[hr].findIndex((v) => /^nuklid$/i.test(cellText(v)));
        const cats = [];
        let avgCol = -1, countCol = -1;
        for (let c = nc + 1; c < Math.max(rows[hr].length, rows[hr - 1].length); c++) {
          const label = cellText(rows[hr - 1][c]);
          /* (anchored: a note beside the table, "Källa antal kapslar: ...", is no heading) */
          if (/^(average|medel)/i.test(label)) { if (avgCol < 0) avgCol = c; continue; }
          if (/^antal\s+kapslar/i.test(label)) { if (countCol < 0) countCol = c; continue; }
          if (/^summa|^totalt?$/i.test(label)) continue;
          const swap = /swap\s*mox\s*(bwr|pwr)/i.exec(label);
          const cat = swap ? 'Swap MOX' : categoryOf(label);
          if (cat && cat !== 'Total') cats.push({ c, cat, sub: swap ? swap[1].toUpperCase() : null });
        }
        const rowsN = nuclideRows(rows.slice(hr + 1), nc);
        const totals = new Map();
        for (const { c, cat } of cats) {
          if (!totals.has(cat)) totals.set(cat, new Map());
          const t = totals.get(cat);
          for (const { name, r } of rowsN) {
            const v = num(r[c]);
            t.set(name, (t.get(name) || 0) + (Number.isFinite(v) ? v : 0));
          }
        }
        for (const [cat, values] of totals) {
          out.refs.push({ id: `workbook:total:${cat}`, label: `PSAR total, ${cat}`, scope: cat, kind: 'total', unit: 'Bq', year, values, parts: null, source, where: totName, digits: 15 });
        }
        const nCan = countCol >= 0 ? num(rows[hr][countCol]) : NaN;
        if (Number.isFinite(nCan)) out.counts.canisters.all = nCan;
        if (avgCol >= 0) {
          const values = new Map();
          for (const { name, r } of rowsN) { const v = num(r[avgCol]); if (Number.isFinite(v)) values.set(name, v); }
          out.refs.push({ id: 'workbook:average:all', label: 'PSAR average canister', scope: 'all', kind: 'average', unit: 'Bq', year, values, count: Number.isFinite(nCan) ? nCan : null, source, where: totName, digits: 15 });
        }
      }
    }

    /* Per element and part, BWR and PWR, for the parts of the averages. */
    const elementParts = {};
    for (const type of ['BWR', 'PWR']) {
      const name = wb.SheetNames.find((n) => n.trim().toUpperCase() === type);
      if (!name) continue;
      const rows = rowsOf(XLSX, wb.Sheets[name]);
      const hr = rows.findIndex((r) => r && r.filter((v) => /^nuklid$/i.test(cellText(v))).length >= 2);
      if (hr < 1) continue;
      const parts = new Map();
      let rodsPerElement = null;
      const head = rows[hr];
      for (let c = 0; c < head.length; c++) {
        if (!/^nuklid$/i.test(cellText(head[c])) || !/aktivitet/i.test(cellText(head[c + 1]))) continue;
        /* The part is named in the row above, over the names or the values. */
        const label = [cellText(rows[hr - 1][c]), cellText(rows[hr - 1][c + 1])].find((t) => partOf(t)) || '';
        const part = partOf(label);
        if (!part || parts.has(part)) continue;
        /* Only the first block of a kind (per element), not the totals beside it. */
        const m = new Map();
        for (const { name: n, r } of nuclideRows(rows.slice(hr + 1), c)) { const v = num(r[c + 1]); m.set(n, Number.isFinite(v) ? v : 0); }
        parts.set(part, m);
      }
      /* Control rods per element: the count of rods over the count of elements. */
      const top = rows[0] || [];
      const nums = top.map((v) => (typeof v === 'number' ? v : NaN));
      const elIdx = top.findIndex((v) => /antal\s+element/i.test(cellText(v)));
      const rodIdx = top.findIndex((v) => /antal\s+styrstavar/i.test(cellText(v)));
      const numAfter = (i) => { for (let k = i + 1; k < nums.length; k++) if (Number.isFinite(nums[k])) return nums[k]; return NaN; };
      const nEl = elIdx >= 0 ? numAfter(elIdx) : NaN;
      const nRod = rodIdx >= 0 ? numAfter(rodIdx) : NaN;
      if (Number.isFinite(nEl)) out.counts.elements[type] = nEl;
      if (Number.isFinite(nEl) && Number.isFinite(nRod) && nEl > 0) rodsPerElement = nRod / nEl;
      elementParts[type] = { parts, rodsPerElement };
    }

    /* The average BWR and PWR canister, and their spread. */
    const avgName = findSheet(wb, /medelkapsl/i);
    if (avgName) {
      const rows = rowsOf(XLSX, wb.Sheets[avgName]);
      const hr = rows.findIndex((r) => r && r.filter((v) => /^nuklid$/i.test(cellText(v))).length >= 2);
      if (hr >= 1) {
        const head = rows[hr];
        const sets = [];
        for (let c = 0; c < head.length; c++) {
          if (!/^nuklid$/i.test(cellText(head[c]))) continue;
          const label = `${labelAbove(rows, c, hr - 1)} ${cellText(head[c + 1])} ${labelAbove(rows, c + 1, hr - 1)}`;
          const type = /bwr/i.test(label) ? 'BWR' : /pwr/i.test(label) ? 'PWR' : null;
          const isCanister = (type === 'BWR' && /medelkapsel/i.test(cellText(head[c + 1])))
            || (type === 'PWR' && /styrstav/i.test(labelAbove(rows, c, hr - 1)) && /\+/.test(labelAbove(rows, c, hr - 1)));
          if (!isCanister) continue;
          const lowC = head.findIndex((v, k) => k > c + 1 && /låg\s*bu/i.test(cellText(v)));
          const highC = head.findIndex((v, k) => k > c + 1 && /hög\s*bu/i.test(cellText(v)));
          sets.push({ type, c, lowC, highC });
        }
        for (const s of sets) {
          const values = new Map(), low = new Map(), high = new Map();
          for (const { name, r } of nuclideRows(rows.slice(hr + 1), s.c)) {
            const v = num(r[s.c + 1]);
            if (Number.isFinite(v)) values.set(name, v);
            if (s.lowC >= 0 && Number.isFinite(num(r[s.lowC]))) low.set(name, num(r[s.lowC]));
            if (s.highC >= 0 && Number.isFinite(num(r[s.highC]))) high.set(name, num(r[s.highC]));
          }
          /* Its parts, in the shares of an element's (control rods at so
             many per element in a PWR canister). */
          let parts = null;
          const ep = elementParts[s.type];
          if (ep && ep.parts.size) {
            parts = new Map();
            for (const [name, total] of values) {
              const share = new Map();
              let sum = 0;
              for (const [p, m] of ep.parts) {
                const x = (m.get(name) || 0) * (p === 'control_rods' ? (ep.rodsPerElement ?? 0) : 1);
                share.set(p, x);
                sum += x;
              }
              for (const [p, x] of share) {
                if (!parts.has(p)) parts.set(p, new Map());
                parts.get(p).set(name, sum > 0 ? total * x / sum : 0);
              }
            }
          }
          out.refs.push({
            id: `workbook:average:${s.type}`, label: `PSAR average ${s.type} canister`, scope: s.type, kind: 'average', unit: 'Bq', year,
            values, low: low.size ? low : null, high: high.size ? high : null, parts, source, where: avgName, digits: 15,
          });
        }
      }
    }

    /* The encapsulation simulation: every element, its canister, year, heat and burnup. */
    const canisters = new Map();
    for (const name of wb.SheetNames) {
      if (!/kapslar/i.test(name) || /alla/i.test(name)) continue;
      const rows = rowsOf(XLSX, wb.Sheets[name]);
      const hr = rows.findIndex((r) => r && r.some((v) => /^kapsel\s*nr/i.test(cellText(v))));
      if (hr < 0) continue;
      const head = rows[hr].map(cellText);
      const col = (re) => head.findIndex((h) => re.test(h));
      const cId = col(/^patron/i), cR = col(/^reaktor$/i), cT = col(/^reaktortyp/i), cD = col(/^bränslekonstr/i);
      const cC = col(/^kapsel\s*nr/i), cY = col(/^dep\.?\s*år/i), cH = col(/^resteffekt/i), cB = col(/^utbränn$/i);
      const sheetType = /pwr/i.test(name) ? 'PWR' : /bwr/i.test(name) ? 'BWR' : null;
      for (const r of rows.slice(hr + 1)) {
        if (!r) continue;
        const cnr = num(r[cC]);
        if (!Number.isFinite(cnr)) continue;
        let can = canisters.get(cnr);
        if (!can) {
          can = { id: String(cnr), type: cT >= 0 && r[cT] ? cellText(r[cT]).toUpperCase() : sheetType, year: num(r[cY]), heat: 0, burnup: 0, n: 0, elements: [] };
          canisters.set(cnr, can);
        }
        const heat = num(r[cH]), bu = num(r[cB]);
        can.heat += Number.isFinite(heat) ? heat : 0;
        can.burnup += Number.isFinite(bu) ? bu : 0;
        can.n++;
        can.elements.push({ id: cellText(r[cId]), reactor: reactorName(r[cR]), design: cellText(r[cD]), heat, burnup: bu });
      }
    }
    if (canisters.size) {
      out.canisters = [...canisters.values()].sort((a, b) => Number(a.id) - Number(b.id));
      for (const c of out.canisters) c.burnup /= c.n || 1;
      const by = (t) => out.canisters.filter((c) => c.type === t).length;
      out.counts.canisters.BWR ??= by('BWR');
      out.counts.canisters.PWR ??= by('PWR');
      out.counts.canisters.all ??= out.canisters.length;
    }
    if (!out.refs.length && !out.canisters) throw new Error('none of PSAR’s inventory sheets was found in it');
    return out;
  }

  return {
    REACTOR_NAMES, reactorName, svNumber, cellNuclide,
    zipEntries, unzip, docxBlocks, gridRows, headRows, readReportXml, readReport,
    readWorkbook,
  };
});
