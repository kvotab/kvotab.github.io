/* ==========================================================================
   distributions.html: NUMBERS IN AND OUT

   How a number is shown (to a number of significant figures, with an
   exponent outside 1e-4 to 1e6), how a number typed into a field is read
   (a decimal comma is accepted where it cannot be a separator), and how a
   list of numbers or a table of columns is read from pasted text or a file.
   ========================================================================== */

/** A number for display; '—' for none, ∞ for an infinite one. */
export function fmt(v, sig = 5) {
  if (v === undefined || v === null || Number.isNaN(v)) return '—';
  if (v === Infinity) return '∞';
  if (v === -Infinity) return '−∞';
  if (v === 0) return '0';
  const a = Math.abs(v);
  if (a >= 1e-4 && a < 1e6) return String(+v.toPrecision(sig));
  const [m, e] = v.toExponential(Math.max(0, sig - 1)).split('e');
  const mant = m.includes('.') ? m.replace(/\.?0+$/, '') : m;
  return `${mant}e${e.replace('+', '')}`;
}

/** A number written into a field: twelve figures, which is what a person would type, without the noise of the last bits. */
export function fmtField(v) {
  if (!Number.isFinite(v)) return '';
  if (v === 0) return '0';
  const a = Math.abs(v);
  if (a >= 1e-6 && a < 1e12) return String(+v.toPrecision(12));
  return fmt(v, 12);
}

/** A number typed into a field, or NaN. "1,5" is 1.5; a typographic minus counts. */
export function parseNum(text) {
  if (typeof text === 'number') return text;
  let s = String(text ?? '').trim().replace(/[−–]/g, '-').replace(/\s+/g, '');
  if (!s) return NaN;
  if (/^[-+]?\d+,\d*([eE][-+]?\d+)?$/.test(s)) s = s.replace(',', '.');
  if (!/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(s)) {
    if (/^[-+]?(inf|infinity|∞)$/i.test(s)) return s.startsWith('-') ? -Infinity : Infinity;
    return NaN;
  }
  return Number(s);
}

/**
 * The numbers in a block of text, separated by white space, commas or
 * semicolons (with decimalComma, by white space and semicolons only, a
 * comma being part of a number). Tokens that are not numbers are counted.
 */
export function parseNumberList(text, decimalComma = false) {
  const tokens = String(text ?? '').split(decimalComma ? /[\s;]+/ : /[\s,;]+/).filter(Boolean);
  const values = [];
  let skipped = 0;
  for (const t of tokens) {
    /* parseNum reads a single comma as the decimal mark; without decimalComma
       the commas were separators and none is left in a token */
    const v = parseNum(t);
    if (Number.isFinite(v)) values.push(v);
    else skipped++;
  }
  return { values, skipped };
}

/**
 * Columns of a delimited table (tab, semicolon or comma, whichever the
 * lines agree on), with a header row when the first line is not numbers.
 * null when the text is one column.
 */
export function parseColumns(text, decimalComma = false) {
  const lines = String(text ?? '').split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (lines.length < 2) return null;
  const candidates = decimalComma ? ['\t', ';'] : ['\t', ';', ','];
  let delim = null;
  for (const d of candidates) {
    const counts = lines.slice(0, 50).map((l) => l.split(d).length);
    if (counts[0] > 1 && counts.every((c) => c === counts[0])) { delim = d; break; }
  }
  if (!delim) {
    const counts = lines.slice(0, 50).map((l) => l.split(/\s+/).length);
    if (counts[0] > 1 && counts.every((c) => c === counts[0])) delim = /\s+/;
  }
  if (!delim) return null;
  const rows = lines.map((l) => l.split(delim).map((c) => c.trim().replace(/^"(.*)"$/, '$1')));
  /* a cell with one comma is a decimal comma unless the comma is the delimiter */
  const read = (c) => parseNum(c);
  const headerLike = rows[0].some((c) => c && !Number.isFinite(read(c)));
  const header = headerLike ? rows[0] : rows[0].map((_, i) => `Column ${i + 1}`);
  const body = headerLike ? rows.slice(1) : rows;
  const columns = header.map((_, j) => {
    const values = [];
    let skipped = 0;
    for (const r of body) {
      const v = read(r[j] ?? '');
      if (Number.isFinite(v)) values.push(v); else skipped++;
    }
    return { name: header[j] || `Column ${j + 1}`, values, skipped };
  });
  return { header, columns };
}

/** Pairs of numbers, one pair per line ("x v"), for the tables. */
export function parsePairs(text, decimalComma = false) {
  const rows = [];
  let bad = 0;
  for (const line of String(text ?? '').split(/\r?\n/)) {
    if (!line.trim()) continue;
    const { values } = parseNumberList(line, decimalComma);
    if (values.length === 2) rows.push(values); else bad++;
  }
  return { rows, bad };
}

/** HTML-escaped text, for the one place untrusted text meets markup: Plotly's names. */
export function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/** A CSV cell, safe from formula injection (kvot-safe.js's rule when loaded). */
export function csvCell(v) {
  if (typeof globalThis.kvotCsvCell === 'function') return globalThis.kvotCsvCell(v);
  const s = String(v ?? '');
  const t = /^[=+@\t\r\n-]/.test(s) && !/^-?\d/.test(s) ? `'${s}` : s;
  return /[",\r\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
}

/** A CSV file of rows, with the byte-order mark Excel needs to read UTF-8. */
export function csvText(rows) {
  return '﻿' + rows.map((r) => r.map(csvCell).join(',')).join('\r\n');
}

/** Save text as a file. */
export function download(name, text, type = 'text/csv;charset=utf-8') {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
