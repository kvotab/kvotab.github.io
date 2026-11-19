/*
  A streaming reader for the cells of large .xlsx and .xlsm workbooks.

  SheetJS turns a whole sheet into cell objects, every column of every row,
  and a workbook of 300 000 rows by 29 columns costs it seconds and a
  gigabyte. A page that wants four of those columns, or only a sheet's first
  row to see what the sheet is, needs none of that. This reader takes the
  ZIP archive apart itself, reads only the parts it is asked for, inflates
  them with the browser's own DecompressionStream, and scans the sheet's XML
  as it arrives, keeping the cells of the columns asked for and passing over
  the rest.

  It reads what Excel, openpyxl and xlsxwriter write: shared strings, inline
  strings, formula strings, numbers, booleans and errors. It gives text as
  stored and numbers as numbers; it applies no number format, so a date is
  the serial number Excel keeps. What it cannot read - a .xls or .xlsb, an
  encrypted workbook, a ZIP64 archive, a part stored with a method other
  than deflate - it refuses with an Error, and the caller reads that
  workbook some other way.

  Runs in a browser and in Node 18 or later; it touches no page.
*/

const EOCD = 0x06054b50, CENTRAL = 0x02014b50, LOCAL = 0x04034b50;
const utf8 = new TextDecoder('utf-8');

/* The ZIP archive's directory: each part's name, method, sizes and offset. */
export async function openZip(blob) {
  const size = blob.size;
  if (size < 22) throw new Error('not a ZIP archive');
  /* The end record is in the last 22 bytes, or up to 64 KiB before them when the archive has a comment. */
  const tail = new Uint8Array(await blob.slice(Math.max(0, size - 65558), size).arrayBuffer());
  const view = new DataView(tail.buffer);
  let end = -1;
  for (let i = tail.length - 22; i >= 0; i--) if (view.getUint32(i, true) === EOCD) { end = i; break; }
  if (end < 0) throw new Error('not a ZIP archive');
  const count = view.getUint16(end + 10, true), dirSize = view.getUint32(end + 12, true), dirOffset = view.getUint32(end + 16, true);
  if (count === 0xffff || dirSize === 0xffffffff || dirOffset === 0xffffffff) throw new Error('a ZIP64 archive');
  if (dirOffset + dirSize > size) throw new Error('the ZIP directory lies outside the file');
  const dir = new Uint8Array(await blob.slice(dirOffset, dirOffset + dirSize).arrayBuffer());
  const dv = new DataView(dir.buffer);
  const parts = new Map();
  for (let p = 0, n = 0; n < count; n++) {
    if (p + 46 > dir.length || dv.getUint32(p, true) !== CENTRAL) throw new Error('a damaged ZIP directory');
    const flags = dv.getUint16(p + 8, true), method = dv.getUint16(p + 10, true);
    const csize = dv.getUint32(p + 20, true), usize = dv.getUint32(p + 24, true);
    const nameLen = dv.getUint16(p + 28, true), extraLen = dv.getUint16(p + 30, true), commentLen = dv.getUint16(p + 32, true);
    const offset = dv.getUint32(p + 42, true);
    const name = utf8.decode(dir.subarray(p + 46, p + 46 + nameLen)).replace(/\\/g, '/').replace(/^\/+/, '');
    parts.set(name, { name, flags, method, csize, usize, offset });
    p += 46 + nameLen + extraLen + commentLen;
  }
  return { blob, parts };
}

/* A part's name as the archive spells it: package names are compared without case. */
function partName(zip, path) {
  if (zip.parts.has(path)) return path;
  const lower = path.toLowerCase();
  for (const name of zip.parts.keys()) if (name.toLowerCase() === lower) return name;
  return null;
}

/* A part's text, chunk by chunk as it is inflated. Leaving the loop early stops the inflating. */
export async function* partText(zip, path) {
  const name = partName(zip, path);
  if (!name) throw new Error(`no part ${path}`);
  const part = zip.parts.get(name);
  if (part.flags & 1) throw new Error('an encrypted workbook');
  if (part.method !== 0 && part.method !== 8) throw new Error(`a part stored with method ${part.method}`);
  const head = new DataView(await zip.blob.slice(part.offset, part.offset + 30).arrayBuffer());
  if (head.byteLength < 30 || head.getUint32(0, true) !== LOCAL) throw new Error('a damaged ZIP entry');
  const start = part.offset + 30 + head.getUint16(26, true) + head.getUint16(28, true);
  let stream = zip.blob.slice(start, start + part.csize).stream();
  if (part.method === 8) stream = stream.pipeThrough(new DecompressionStream('deflate-raw'));
  const reader = stream.pipeThrough(new TextDecoderStream('utf-8')).getReader();
  let done = false;
  try {
    for (;;) {
      const next = await reader.read();
      if (next.done) { done = true; return; }
      yield next.value;
    }
  } finally {
    if (!done) await reader.cancel().catch(() => {});
  }
}

export async function partString(zip, path) {
  let out = '';
  for await (const chunk of partText(zip, path)) out += chunk;
  return out;
}

const ENTITY = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" };
/* XML's character references, then the _xHHHH_ escapes OOXML writes for characters XML cannot hold. */
export function unescapeXml(s) {
  if (s.indexOf('&') >= 0) {
    s = s.replace(/&(#x[0-9a-fA-F]+|#[0-9]+|amp|lt|gt|quot|apos);/g, (m, e) => e[0] === '#'
      ? String.fromCodePoint(e[1] === 'x' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10)) : ENTITY[e]);
  }
  if (s.indexOf('_x') >= 0) s = s.replace(/_x([0-9a-fA-F]{4})_/g, (m, h) => String.fromCharCode(parseInt(h, 16)));
  return s;
}

/* The text of an element that may be rich text: every <t> in it joined, phonetic runs (<rPh>) left out. */
function richText(xml) {
  let out = '';
  const re = /<(\/?)(?:\w+:)?(rPh|t)\b[^>]*?(\/?)>/g;
  let skip = 0, from = -1, m;
  while ((m = re.exec(xml))) {
    const closing = m[1] === '/', name = m[2], empty = m[3] === '/';
    if (name === 'rPh') { if (!empty) skip += closing ? -1 : 1; continue; }
    if (empty) continue;
    if (!closing) from = re.lastIndex;
    else if (from >= 0) { if (!skip) out += xml.slice(from, m.index); from = -1; }
  }
  return unescapeXml(out);
}

const attr = (tag, name) => {
  const m = new RegExp(`\\s${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)')`).exec(tag);
  return m ? unescapeXml(m[1] ?? m[2]) : null;
};
function resolve(base, target) {
  if (target.startsWith('/')) return target.slice(1);
  const parts = base.split('/').slice(0, -1);
  for (const piece of target.split('/')) {
    if (piece === '..') parts.pop();
    else if (piece !== '.' && piece) parts.push(piece);
  }
  return parts.join('/');
}

/* The workbook's sheets in order, each with the part that holds it, and its shared strings' part. */
export async function workbookParts(zip) {
  const bookName = partName(zip, 'xl/workbook.xml');
  if (!bookName) throw new Error('no workbook part: not an Excel workbook');
  const book = await partString(zip, bookName);
  const relsName = partName(zip, 'xl/_rels/workbook.xml.rels');
  const rels = relsName ? await partString(zip, relsName) : '';
  const targets = new Map();
  let strings = null;
  for (const m of rels.matchAll(/<(?:\w+:)?Relationship\b[^>]*>/g)) {
    const id = attr(m[0], 'Id'), target = attr(m[0], 'Target'), type = attr(m[0], 'Type') || '';
    if (!id || !target || attr(m[0], 'TargetMode') === 'External') continue;
    const path = partName(zip, resolve(bookName, target));
    targets.set(id, path);
    if (/\/sharedStrings$/.test(type)) strings = path;
  }
  strings ??= partName(zip, 'xl/sharedStrings.xml');
  const sheets = [];
  for (const m of book.matchAll(/<(?:\w+:)?sheet\b[^>]*>/g)) {
    const rid = attr(m[0], '(?:\\w+:)?id');
    sheets.push({ name: attr(m[0], 'name') ?? '', part: (rid && targets.get(rid)) || null });
  }
  return { sheets, strings };
}

export async function sharedStrings(zip, part) {
  if (!part) return [];
  const out = [];
  let buf = '';
  for await (const chunk of partText(zip, part)) {
    buf += chunk;
    let at = 0;
    for (;;) {
      const s = buf.indexOf('<si', at);
      if (s < 0) { at = Math.max(at, buf.length - 3); break; }
      if (s + 3 >= buf.length) { at = s; break; }
      const c = buf.charCodeAt(s + 3);
      if (c !== 62 && c !== 32 && c !== 47 && c !== 9 && c !== 10 && c !== 13) { at = s + 3; continue; }
      const open = buf.indexOf('>', s);
      if (open < 0) { at = s; break; }
      if (buf.charCodeAt(open - 1) === 47) { out.push(''); at = open + 1; continue; }
      const e = buf.indexOf('</si>', open);
      if (e < 0) { at = s; break; }
      out.push(richText(buf.slice(open + 1, e)));
      at = e + 5;
    }
    buf = buf.slice(at);
  }
  return out;
}

/* "AB" is column 27; columns count from 0 here. */
function columnIndex(s, from) {
  let n = 0;
  for (let i = from; ; i++) {
    const c = s.charCodeAt(i);
    if (c >= 65 && c <= 90) n = n * 26 + (c - 64);
    else if (c >= 97 && c <= 122) n = n * 26 + (c - 96);
    else break;
  }
  return n - 1;
}
const isSpace = (c) => c === 32 || c === 9 || c === 10 || c === 13;

/*
  The rows of a sheet: `onRow(rowNumber, cells)` for each row present, where
  `cells` holds the value of each wanted column that has one (an array index
  per column, counted from 0). `wanted(column)` says which columns to keep;
  without it every column is kept, and a `wanted.last` says that no column
  after that one is, so the rest of each row is not looked at. `onRow`
  returning false ends the reading, which is how a header is read without
  inflating the rows under it.
*/
export async function readRows(zip, part, sst, onRow, wanted = null) {
  let buf = '', rowNumber = 0;
  for await (const chunk of partText(zip, part)) {
    buf += chunk;
    let at = 0;
    for (;;) {
      const s = buf.indexOf('<row', at);
      if (s < 0) { at = Math.max(at, buf.length - 4); break; }
      /* A chunk can end inside a tag: what follows "<row" decides whether it is one. */
      if (s + 4 >= buf.length) { at = s; break; }
      const c4 = buf.charCodeAt(s + 4);
      /* <rowBreaks> and the like are not rows. */
      if (c4 !== 62 && c4 !== 47 && !isSpace(c4)) { at = s + 4; continue; }
      const tagEnd = buf.indexOf('>', s);
      if (tagEnd < 0) { at = s; break; }
      if (buf.charCodeAt(tagEnd - 1) === 47) {
        /* <row r="6"/>: a row with nothing in it. */
        rowNumber = rowAttr(buf, s, tagEnd, rowNumber);
        at = tagEnd + 1;
        if (onRow(rowNumber, []) === false) return;
        continue;
      }
      const e = buf.indexOf('</row>', tagEnd);
      if (e < 0) { at = s; break; }
      rowNumber = rowAttr(buf, s, tagEnd, rowNumber);
      at = e + 6;
      if (onRow(rowNumber, parseCells(buf, tagEnd + 1, e, sst, wanted)) === false) return;
    }
    buf = buf.slice(at);
  }
}
function rowAttr(buf, s, tagEnd, previous) {
  const r = buf.indexOf(' r="', s);
  if (r < 0 || r > tagEnd) return previous + 1;
  let n = 0;
  for (let i = r + 4; ; i++) {
    const c = buf.charCodeAt(i);
    if (c < 48 || c > 57) break;
    n = n * 10 + (c - 48);
  }
  return n || previous + 1;
}

function parseCells(buf, from, to, sst, wanted) {
  const cells = [];
  const last = wanted && wanted.last != null ? wanted.last : Infinity;
  let col = -1, p = from;
  for (;;) {
    const s = buf.indexOf('<c', p);
    if (s < 0 || s >= to) break;
    const c2 = buf.charCodeAt(s + 2);
    if (c2 !== 62 && c2 !== 47 && !isSpace(c2)) { p = s + 2; continue; }
    const tagEnd = buf.indexOf('>', s);
    const tag = buf.slice(s, tagEnd);
    const r = tag.indexOf(' r="');
    col = r >= 0 ? columnIndex(tag, r + 4) : col + 1;
    if (col > last) break;
    if (buf.charCodeAt(tagEnd - 1) === 47) { p = tagEnd + 1; continue; }
    const end = buf.indexOf('</c>', tagEnd);
    p = end + 4;
    if (wanted && !wanted(col)) continue;
    const t = tag.indexOf(' t="');
    const type = t < 0 ? 'n' : tag.slice(t + 4, tag.indexOf('"', t + 4));
    if (type === 'inlineStr') { cells[col] = richText(buf.slice(tagEnd + 1, end)); continue; }
    const v = buf.indexOf('<v', tagEnd);
    if (v < 0 || v > end) continue;
    const vOpen = buf.indexOf('>', v);
    if (buf.charCodeAt(vOpen - 1) === 47) continue;
    const text = buf.slice(vOpen + 1, buf.indexOf('</v>', vOpen));
    if (type === 's') cells[col] = sst[+text] ?? '';
    else if (type === 'str' || type === 'e' || type === 'd') cells[col] = unescapeXml(text);
    else if (type === 'b') cells[col] = text === '1';
    else cells[col] = text === '' ? '' : Number(text);
  }
  return cells;
}

/*
  Each sheet with its first row, or none for a sheet with no rows, and that
  row's number: what a sheet is can be told from its header without reading
  the rows under it. Its shared strings are read once and kept for a later
  readRows.
*/
export async function openWorkbook(blob) {
  const zip = await openZip(blob);
  const { sheets, strings } = await workbookParts(zip);
  const sst = await sharedStrings(zip, strings);
  for (const sheet of sheets) {
    sheet.first = null;
    if (sheet.part && zip.parts.has(sheet.part)) {
      await readRows(zip, sheet.part, sst, (number, cells) => { sheet.first = { number, cells }; return false; });
    }
  }
  return { zip, sst, sheets };
}
