/*
  What skb_qa_summary.html reads out of one workbook, in a worker or, where
  there is none, on the page itself.

  A sheet is one of two kinds, told apart by its header:

  - A QC sheet: a source workbook's sheet with an ID column and the three
    review columns, QC reviewer, QC comment and QC status (or the older QA
    headings). Every row with something in those four is a QC row.
  - An export: what the calculation-case code writes for an input set (the
    parameter file <set>.h5) to be checked, one row per value, with the
    source of each value in the columns file, sheet and row: the workbook,
    sheet and row it was read from. Values read from raw data rather than a
    workbook name that raw file, or nothing.

  An export can be hundreds of thousands of rows, nearly all from raw data,
  so it is not kept row by row. Each source is counted, and for a source
  that is a workbook every value's sheet, row and ID are kept, which is what
  tracing a value to its QC row needs. The page does the tracing, once the
  workbooks are all read.

  The workbook is read with xlsx-stream.mjs: only the columns wanted, as the
  XML is inflated. A .xls or .xlsb, or a workbook that reader refuses, comes
  back as { fallback: reason } for the page to read with SheetJS.
*/
import { openZip, workbookParts, sharedStrings, readRows } from './xlsx-stream.mjs?v=20261119';

export const REVIEW_PREFIXES = ['qc', 'qa'];
export const columnsFor = (prefix) => ['id', `${prefix} reviewer`, `${prefix} comment`, `${prefix} status`];
export const normalize = (v) => String(v ?? '').trim().toLowerCase().replace(/\s+/g, ' ');
export const reviewPrefix = (header) => REVIEW_PREFIXES.find((p) => columnsFor(p).every((key) => header.includes(key)));
export const EXPORT_COLUMNS = ['id', 'file', 'sheet', 'row'];
export const isExport = (header) => EXPORT_COLUMNS.every((key) => header.includes(key));
const WORKBOOK = /\.(xlsx|xlsm|xlsb|xls)$/i;
const ZIPPED = /\.(xlsx|xlsm)$/i;

/* A cell as the page shows it: text as stored, a number as JavaScript writes it. */
const text = (v) => (v == null ? '' : typeof v === 'boolean' ? (v ? 'TRUE' : 'FALSE') : String(v));

class Grow {
  constructor() { this.a = new Int32Array(1024); this.n = 0; }
  push(v) {
    if (this.n === this.a.length) { const b = new Int32Array(this.a.length * 2); b.set(this.a); this.a = b; }
    this.a[this.n++] = v;
  }
  done() { return this.a.slice(0, this.n); }
}

/*
  One workbook: `book` is { file, path, folder, name }. QC rows come back as
  the page keeps them; exports as their counts and their traceable values.
*/
export async function readBook(book) {
  if (!ZIPPED.test(book.name)) return { fallback: 'not an Office Open XML workbook' };
  let zip, parts, sst;
  try {
    zip = await openZip(book.file);
    parts = await workbookParts(zip);
    sst = await sharedStrings(zip, parts.strings);
  } catch (e) {
    return { fallback: String(e.message || e) };
  }
  const sheets = [], records = [], exports = [];
  for (const sheet of parts.sheets) {
    const info = { name: sheet.name, kind: 'empty' };
    sheets.push(info);
    if (!sheet.part || !zip.parts.has(sheet.part)) continue;
    let header = null, prefix = null, columns = null, out = null, want = null;
    const wanted = (col) => want === null || want.has(col);
    await readRows(zip, sheet.part, sst, (number, cells) => {
      if (!header) {
        /* The header is the sheet's first row with something in it. */
        if (!cells.some((c) => text(c).trim() !== '')) return true;
        header = Array.from(cells, (c) => normalize(text(c)));
        prefix = reviewPrefix(header);
        if (prefix) {
          info.kind = 'qc';
          columns = columnsFor(prefix).map((key) => header.indexOf(key));
          want = new Set(columns);
          wanted.last = Math.max(...columns);
          return true;
        }
        if (isExport(header)) {
          info.kind = 'export';
          columns = { id: header.indexOf('id'), time: header.indexOf('time'), file: header.indexOf('file'), sheet: header.indexOf('sheet'), row: header.indexOf('row'), linked: header.indexOf('linked_file') };
          want = new Set(Object.values(columns).filter((c) => c >= 0));
          wanted.last = Math.max(...want);
          out = newExport(sheet.name);
          return true;
        }
        info.kind = 'other';
        return false;
      }
      if (prefix) {
        const [idCol, reviewerCol, commentCol, statusCol] = columns;
        const record = { folder: book.folder, file: book.name, path: book.path, sheet: sheet.name, row: number,
          id: text(cells[idCol]), reviewer: text(cells[reviewerCol]), comment: text(cells[commentCol]), status: text(cells[statusCol]) };
        if (![record.id, record.reviewer, record.comment, record.status].every((v) => v.trim() === '')) records.push(record);
        return true;
      }
      addValue(out, cells, columns);
      return true;
    }, wanted);
    if (info.kind === 'qc') info.prefix = prefix;
    if (out) exports.push(finishExport(out));
  }
  return { sheets, records, exports };
}

function newExport(sheet) {
  return { sheet, values: 0, ids: new Set(), sources: new Map(), idIndex: new Map(), idTable: [], sheetIndex: new Map(), sheetTable: [] };
}

/* One value of an export: counted under its source, and kept when its source is a workbook. */
function addValue(out, cells, columns) {
  const id = text(cells[columns.id]).trim();
  if (!id) return;
  out.values++;
  out.ids.add(id.toLowerCase());
  const file = text(cells[columns.file]).trim().replace(/\\/g, '/');
  let src = out.sources.get(file);
  if (!src) {
    src = { file, values: 0, linked: new Set(), workbook: WORKBOOK.test(file), sheet: new Grow(), row: new Grow(), id: new Grow(), point: new Grow() };
    out.sources.set(file, src);
  }
  src.values++;
  if (columns.linked >= 0) {
    const linked = text(cells[columns.linked]).trim();
    if (linked && src.linked.size < 8) src.linked.add(linked);
  }
  if (!src.workbook) return;
  const sheet = text(cells[columns.sheet]).trim();
  let s = out.sheetIndex.get(sheet);
  if (s === undefined) { s = out.sheetTable.length; out.sheetTable.push(sheet); out.sheetIndex.set(sheet, s); }
  let i = out.idIndex.get(id);
  if (i === undefined) { i = out.idTable.length; out.idTable.push(id); out.idIndex.set(id, i); }
  const row = Number.parseInt(text(cells[columns.row]), 10);
  src.sheet.push(s);
  src.row.push(Number.isFinite(row) ? row : -1);
  src.id.push(i);
  /* A value with a time is a time point of a time series. */
  src.point.push(columns.time >= 0 && text(cells[columns.time]).trim() !== '' ? 1 : 0);
}

function finishExport(out) {
  return {
    sheet: out.sheet,
    values: out.values,
    ids: out.ids.size,
    idTable: out.idTable,
    sheetTable: out.sheetTable,
    sources: [...out.sources.values()].map((s) => ({
      file: s.file, values: s.values, linked: [...s.linked], workbook: s.workbook,
      sheet: s.sheet.done(), row: s.row.done(), id: s.id.done(), point: s.point.done(),
    })),
  };
}

/* The typed arrays of a result, to hand over from a worker instead of copying. */
export function transferables(result) {
  const out = [];
  for (const e of result.exports || []) for (const s of e.sources) out.push(s.sheet.buffer, s.row.buffer, s.id.buffer, s.point.buffer);
  return out;
}
