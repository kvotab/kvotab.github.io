/* ==========================================================================
   CANISTER_INVENTORY.HTML: EXCEL FILES

   A workbook from sheets described as columns and rows, written by SheetJS
   (vendors/js/xlsx-0.20.3.full.min.js, the copy the page reads PSAR's
   workbook with). Each sheet is a table: one header row with a filter on
   it, then its rows. Numbers are written whole, every digit, and only shown
   in a format: scientific for amounts, per cents for shares, dates as
   Excel's own dates.

     build(XLSX, [{ name, columns: [{label, fmt?, width?}], rows }]) -> ArrayBuffer

   fmt is 'sci' (0.000E+00), 'int', 'pct' (a fraction shown as per cent),
   'date' (milliseconds since 1970, UTC, shown as yyyy-mm-dd), 'fixed'
   (0.00), or none (General). A value that is not a finite number is
   written as an empty cell.

   Runs in a worker (inventory-excel-worker.js) and, where none can start,
   on the page. One global: KVOT_INV_EXCEL (module.exports under Node).
   ========================================================================== */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.KVOT_INV_EXCEL = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const FORMATS = { sci: '0.000E+00', int: '0', pct: '0.0%', date: 'yyyy-mm-dd', fixed: '0.00' };
  const DAY_MS = 86400000;
  const EPOCH_1970 = 25569;          // Excel's serial number of 1 January 1970
  const MAX_TEXT = 32767;            // the most characters Excel holds in a cell

  /** A sheet name Excel takes: at most 31 characters, none of []:*?/\, unique in the book. */
  function sheetName(name, used) {
    let base = String(name || 'Sheet').replace(/[[\]:*?/\\]/g, ' ').replace(/^'+|'+$/g, '').replace(/\s+/g, ' ').trim().slice(0, 31) || 'Sheet';
    let out = base, n = 2;
    while (used.has(out.toLowerCase())) {
      const tail = ` (${n++})`;
      out = base.slice(0, 31 - tail.length) + tail;
    }
    used.add(out.toLowerCase());
    return out;
  }

  function value(v, fmt) {
    if (v === null || v === undefined) return null;
    if (typeof v === 'number') {
      if (!Number.isFinite(v)) return null;
      return fmt === 'date' ? v / DAY_MS + EPOCH_1970 : v;
    }
    if (typeof v === 'boolean') return v;
    const s = String(v);
    return s.length > MAX_TEXT ? s.slice(0, MAX_TEXT) : s;
  }

  /**
   * @param {Object} XLSX - SheetJS
   * @param {Array<{name: string, columns: Array<{label: string, fmt?: string, width?: number}>, rows: Array<Array<*>>}>} sheets
   * @returns {ArrayBuffer} the .xlsx file
   */
  function build(XLSX, sheets) {
    const wb = XLSX.utils.book_new();
    const used = new Set();
    for (const s of sheets) {
      const cols = s.columns;
      const aoa = [cols.map((c) => String(c.label ?? ''))];
      for (const row of s.rows) aoa.push(cols.map((c, j) => value(row[j], c.fmt)));
      const ws = XLSX.utils.aoa_to_sheet(aoa, { dense: true });
      const data = ws['!data'];
      cols.forEach((c, j) => {
        const z = FORMATS[c.fmt];
        if (!z) return;
        for (let r = 1; r < aoa.length; r++) {
          const cell = data[r] && data[r][j];
          if (cell && cell.t === 'n') cell.z = z;
        }
      });
      ws['!cols'] = cols.map((c) => ({ wch: c.width || Math.min(48, Math.max(9, String(c.label ?? '').length + 2)) }));
      if (s.rows.length && cols.length) {
        ws['!autofilter'] = { ref: XLSX.utils.encode_range({ s: { r: 0, c: 0 }, e: { r: s.rows.length, c: cols.length - 1 } }) };
      }
      XLSX.utils.book_append_sheet(wb, ws, sheetName(s.name, used));
    }
    return XLSX.write(wb, { type: 'array', bookType: 'xlsx', compression: true });
  }

  return { FORMATS, build, sheetName };
});
