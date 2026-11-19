/*
  resources/js/xlsx-stream.mjs and resources/js/skb-qa-read.mjs, run in Node
  on workbooks written here, part by part, so that each case is exactly the
  XML it is about: shared and inline strings, rich text with phonetic runs,
  escapes, formulas, cells without a reference, a sheet that starts in row 3,
  a sheet so long that its rows cross the inflater's chunks, parts stored
  rather than deflated, and what is not a workbook at all.

      node resources/tests/skb_qa_summary/test-xlsx-stream.mjs

  Node before 21 has no 'deflate-raw' DecompressionStream; zlib stands in for
  it here. Exit status is 0 when every check passes.
*/
import { deflateRawSync, createInflateRaw } from 'node:zlib';
import { Duplex } from 'node:stream';

try { new DecompressionStream('deflate-raw'); } catch {
  const Native = globalThis.DecompressionStream;
  globalThis.DecompressionStream = class {
    constructor(format) {
      if (format !== 'deflate-raw') return new Native(format);
      const { readable, writable } = Duplex.toWeb(createInflateRaw());
      this.readable = readable; this.writable = writable;
    }
  };
}
const X = await import('../../js/xlsx-stream.mjs');
const R = await import('../../js/skb-qa-read.mjs');

let failed = 0;
function check(ok, what, detail) {
  console.log(`${ok ? 'ok   ' : 'FAIL '} ${what}${ok ? '' : `\n      ${JSON.stringify(detail)?.slice(0, 600)}`}`);
  if (!ok) failed++;
}
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/* ---- A ZIP archive, written by hand ---------------------------------------- */
const CRC = new Int32Array(256).map((_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c; });
const crc32 = (buf) => { let c = -1; for (const b of buf) c = CRC[(c ^ b) & 0xff] ^ (c >>> 8); return (c ^ -1) >>> 0; };
function zip(parts, { stored = [] } = {}) {
  const enc = new TextEncoder(), chunks = [], central = [];
  let offset = 0;
  for (const [name, text] of Object.entries(parts)) {
    const data = enc.encode(text), nameBytes = enc.encode(name), store = stored.includes(name);
    const body = store ? data : deflateRawSync(data);
    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true); local.setUint16(4, 20, true); local.setUint16(8, store ? 0 : 8, true);
    local.setUint32(14, crc32(data), true); local.setUint32(18, body.length, true); local.setUint32(22, data.length, true);
    local.setUint16(26, nameBytes.length, true);
    chunks.push(new Uint8Array(local.buffer), nameBytes, body);
    const dir = new DataView(new ArrayBuffer(46));
    dir.setUint32(0, 0x02014b50, true); dir.setUint16(4, 20, true); dir.setUint16(6, 20, true); dir.setUint16(10, store ? 0 : 8, true);
    dir.setUint32(16, crc32(data), true); dir.setUint32(20, body.length, true); dir.setUint32(24, data.length, true);
    dir.setUint16(28, nameBytes.length, true); dir.setUint32(42, offset, true);
    central.push(new Uint8Array(dir.buffer), nameBytes);
    offset += 30 + nameBytes.length + body.length;
  }
  const dirSize = central.reduce((n, c) => n + c.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true); end.setUint16(8, central.length / 2, true); end.setUint16(10, central.length / 2, true);
  end.setUint32(12, dirSize, true); end.setUint32(16, offset, true);
  return new Blob([...chunks, ...central, new Uint8Array(end.buffer)]);
}
const NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"';
/* A workbook: sheets is [[name, sheetXmlBody]], strings the shared strings' <si> elements. */
function book(sheets, strings = null, opts = {}) {
  const parts = {
    '[Content_Types].xml': '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
    'xl/workbook.xml': `<?xml version="1.0" encoding="UTF-8"?><workbook ${NS}><sheets>${sheets.map(([name], i) => `<sheet name="${name}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join('')}</sheets></workbook>`,
    'xl/_rels/workbook.xml.rels': `<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${sheets.map((_, i) => `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="${opts.absolute && i === 1 ? '/xl/' : ''}worksheets/sheet${i + 1}.xml"/>`).join('')}${strings ? `<Relationship Id="rIdS" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>` : ''}</Relationships>`,
  };
  sheets.forEach(([, body], i) => { parts[`xl/worksheets/sheet${i + 1}.xml`] = `<?xml version="1.0" encoding="UTF-8"?><worksheet ${NS}><dimension ref="A1"/><sheetData>${body}</sheetData><rowBreaks count="0"/></worksheet>`; });
  if (strings) parts['xl/sharedStrings.xml'] = `<?xml version="1.0" encoding="UTF-8"?><sst ${NS} count="${strings.length}" uniqueCount="${strings.length}">${strings.join('')}</sst>`;
  return zip(parts, opts);
}
const s = (ref, i) => `<c r="${ref}" t="s"><v>${i}</v></c>`;
const n = (ref, v) => `<c r="${ref}"><v>${v}</v></c>`;
const inl = (ref, text) => `<c r="${ref}" t="inlineStr"><is><t>${text}</t></is></c>`;
async function readAll(blob) {
  const zipped = await X.openZip(blob);
  const { sheets, strings } = await X.workbookParts(zipped);
  const sst = await X.sharedStrings(zipped, strings);
  const out = {};
  for (const sheet of sheets) {
    const rows = [];
    if (sheet.part) await X.readRows(zipped, sheet.part, sst, (r, cells) => { rows.push([r, Array.from(cells)]); });
    out[sheet.name] = rows;
  }
  return { out, sst, sheets };
}

/* ---- Cells ------------------------------------------------------------------ */
{
  const strings = [
    '<si><t>ID</t></si>',
    '<si><r><t>Hello </t></r><r><rPr><b/></rPr><t>world</t></r><rPh sb="0" eb="1"><t>ignored</t></rPh></si>',
    '<si><t xml:space="preserve"> a &amp; b &lt;c&gt; &quot;d&quot; &#233;&#x00E9;</t></si>',
    '<si/>',
    '<si><t>line_x000D__x000A_two</t></si>',
  ];
  const sheet1 = `<row r="1">${s('A1', 0)}${s('B1', 1)}${s('C1', 2)}${s('D1', 3)}${s('E1', 4)}</row>`
    + `<row r="2">${inl('A2', 'in&amp;line')}<c r="B2" t="str"><f>A2&amp;"!"</f><v>formula text</v></c>${n('C2', '6.4E-07')}<c r="D2" t="b"><v>1</v></c><c r="E2" t="e"><v>#N/A</v></c><c r="AB2"><v>27</v></c></row>`
    + `<row r="3"><c t="s"><v>0</v></c><c><v>2</v></c><c r="E3" s="1"/><c><v>5</v></c></row>`
    + `<row><c r="A4"><v>4</v></c></row><row r="6" spans="1:2"/><row r="7"><c r="A7" t="inlineStr"><is><r><t>rich </t></r><r><t>inline</t></r></is></c></row>`;
  const sheet2 = `<row r="3">${inl('A3', 'header')}</row><row r="4">${n('A4', 1)}</row>`;
  const { out, sst, sheets } = await readAll(book([['First', sheet1], ['Lower', sheet2], ['Empty', '']], strings, { absolute: true }));
  check(same(sst, ['ID', 'Hello world', ' a & b <c> "d" éé', '', 'line\r\ntwo']), 'shared strings: rich text joined, phonetic runs left out, escapes undone', sst);
  check(same(sheets.map((x) => [x.name, x.part]), [['First', 'xl/worksheets/sheet1.xml'], ['Lower', 'xl/worksheets/sheet2.xml'], ['Empty', 'xl/worksheets/sheet3.xml']]),
    'sheets in the workbook\'s order, a relationship\'s absolute target resolved', sheets);
  const first = out.First;
  check(same(first[0], [1, ['ID', 'Hello world', ' a & b <c> "d" éé', '', 'line\r\ntwo']]), 'a row of shared strings', first[0]);
  const row2 = first[1][1];
  check(row2[0] === 'in&line' && row2[1] === 'formula text' && row2[2] === 6.4e-7 && row2[3] === true && row2[4] === '#N/A' && row2[27] === 27 && row2.length === 28,
    'inline strings, a formula\'s cached text, numbers, booleans, errors and column AB', row2);
  check(same(first[2], [3, ['ID', 2, null, null, null, 5]]),
    'a cell without a reference follows the one before it, an empty one among them', first[2]);
  check(first[3][0] === 4 && first[4][0] === 6 && same(first[4][1], []), 'a row without a number follows the one before, an empty row is a row', first.slice(3));
  check(same(first[5], [7, ['rich inline']]), 'rich inline text');
  check(same(out.Lower, [[3, ['header']], [4, [1]]]), 'a sheet that starts in row 3 says so', out.Lower);
  check(same(out.Empty, []), 'an empty sheet has no rows');

  const zipped = await X.openZip(book([['First', sheet1]], strings));
  const sstOnly = await X.sharedStrings(zipped, 'xl/sharedStrings.xml');
  const seen = [];
  await X.readRows(zipped, 'xl/worksheets/sheet1.xml', sstOnly, (r, cells) => { seen.push([r, Object.keys(cells).map(Number)]); }, Object.assign((c) => c === 0 || c === 2, { last: 2 }));
  check(same(seen[1], [2, [0, 2]]), 'only the columns wanted are kept, and none after the last', seen);
  let calls = 0;
  await X.readRows(zipped, 'xl/worksheets/sheet1.xml', sstOnly, () => { calls++; return false; });
  check(calls === 1, 'returning false ends the reading');
}

/* ---- A long sheet, stored and deflated ---------------------------------------------- */
{
  const many = 30000;
  let body = '';
  for (let r = 1; r <= many; r++) body += `<row r="${r}" spans="1:3">${inl(`A${r}`, `id.${r}`)}${n(`B${r}`, r)}${s(`C${r}`, r % 2)}</row>`;
  for (const stored of [false, true]) {
    const blob = book([['Data', body]], ['<si><t>even</t></si>', '<si><t>odd</t></si>'], { stored: stored ? ['xl/worksheets/sheet1.xml'] : [] });
    const zipped = await X.openZip(blob);
    const sst = await X.sharedStrings(zipped, 'xl/sharedStrings.xml');
    let count = 0, ok = true, last = 0;
    await X.readRows(zipped, 'xl/worksheets/sheet1.xml', sst, (r, cells) => {
      count++;
      if (r !== last + 1 || cells[0] !== `id.${r}` || cells[1] !== r || cells[2] !== (r % 2 ? 'odd' : 'even')) ok = false;
      last = r;
    });
    check(count === many && ok, `${many} rows ${stored ? 'stored' : 'deflated'}, none lost where a chunk ends`, { count, last });
  }
}

/* ---- What is not a workbook ------------------------------------------------------------ */
{
  const tryOpen = async (blob) => { try { await X.openZip(blob); return null; } catch (e) { return e.message; } };
  check(await tryOpen(new Blob(['not a workbook at all, only text'])) === 'not a ZIP archive', 'text is not a ZIP archive');
  const whole = new Uint8Array(await book([['A', '']]).arrayBuffer());
  check(await tryOpen(new Blob([whole.slice(0, 200)])) === 'not a ZIP archive', 'an archive cut short is refused');
  const r = await R.readBook({ file: new Blob(['plain']), path: 'x/plain.xlsx', folder: 'x', name: 'plain.xlsx' });
  check(r.fallback === 'not a ZIP archive', 'readBook hands back what it cannot read', r);
  const xls = await R.readBook({ file: new Blob(['x']), path: 'old.xls', folder: '', name: 'old.xls' });
  check(!!xls.fallback, 'a .xls goes to SheetJS', xls);
}

/* ---- readBook: QC sheets and exports ------------------------------------------------------ */
{
  const qc = `<row r="1">${inl('A1', 'ID')}${inl('B1', 'Value')}${inl('C1', 'QC reviewer')}${inl('D1', 'QC comment')}${inl('E1', 'QC status')}</row>`
    + `<row r="2">${inl('A2', 'p1')}${n('B2', 1)}${inl('C2', 'revA')}${inl('D2', 'PSAR')}${inl('E2', 'OK-PSAR')}</row>`
    + `<row r="3">${n('B3', 2)}</row>`
    + `<row r="4">${inl('A4', 'p2')}${inl('E4', 'Preliminary')}</row>`;
  const qa = `<row r="1">${inl('A1', 'ID')}${inl('B1', 'QA reviewer')}${inl('C1', 'QA comment')}${inl('D1', 'QA Status')}</row><row r="2">${inl('A2', 'p3')}${inl('B2', 'revB')}${inl('D2', 'In review')}</row>`;
  const other = `<row r="1">${inl('A1', 'Topic')}${inl('B1', 'Text')}</row><row r="2">${inl('A2', 'x')}</row>`;
  const exp = `<row r="1">${['id', 'time', 'value', 'linked_file', 'file', 'sheet', 'row', 'reference'].map((h, i) => inl(String.fromCharCode(65 + i) + '1', h)).join('')}</row>`
    + [['nearfield.a', '', 1, '../base_case/x_v2.h5', '/data/excel/base_case/x.xlsx', 'nearfield', 2],
      ['nearfield.b', 100, 2, '../base_case/x_v2.h5', '/data/excel/base_case/x.xlsx', 'nearfield', 3],
      ['flow.q', '', 3, '../hydro/NCC1_v1.h5', '', '', ''],
      ['inv.c', '', 4, '../inv/inv_v1.h5', '/raw/INVENTORY/inv.csv', 'Sheet1', 5],
      ['', '', '', '', '', '', '']]
      .map((v, k) => `<row r="${k + 2}">${v.map((c, i) => c === '' ? '' : typeof c === 'number' ? n(String.fromCharCode(65 + i) + (k + 2), c) : inl(String.fromCharCode(65 + i) + (k + 2), c)).join('')}</row>`).join('');
  const blob = book([['Data', other], ['Params', qc], ['Old', qa], ['Export', exp]]);
  const r = await R.readBook({ file: blob, path: 'f/book.xlsx', folder: 'f', name: 'book.xlsx' });
  check(same(r.sheets.map((x) => [x.name, x.kind]), [['Data', 'other'], ['Params', 'qc'], ['Old', 'qc'], ['Export', 'export']]), 'each sheet\'s kind, told by its header', r.sheets);
  check(same(r.records.map((x) => [x.sheet, x.row, x.id, x.reviewer, x.comment, x.status, x.path, x.folder]),
    [['Params', 2, 'p1', 'revA', 'PSAR', 'OK-PSAR', 'f/book.xlsx', 'f'], ['Params', 4, 'p2', '', '', 'Preliminary', 'f/book.xlsx', 'f'], ['Old', 2, 'p3', 'revB', '', 'In review', 'f/book.xlsx', 'f']]),
    'QC rows with their Excel rows, a row with nothing in the four columns passed over, the QA headings read', r.records);
  const e = r.exports[0];
  check(e.sheet === 'Export' && e.values === 4 && e.ids === 4, 'an export counts its values and IDs; a row without an ID is no value', [e.values, e.ids]);
  const byFile = Object.fromEntries(e.sources.map((x) => [x.file, x]));
  const xs = byFile['/data/excel/base_case/x.xlsx'];
  check(xs.workbook && xs.values === 2 && same([...xs.row], [2, 3]) && same([...xs.sheet].map((i) => e.sheetTable[i]), ['nearfield', 'nearfield'])
    && same([...xs.id].map((i) => e.idTable[i]), ['nearfield.a', 'nearfield.b']) && same(xs.linked, ['../base_case/x_v2.h5']),
    'a workbook source keeps each value\'s sheet, row and ID, and the files it was linked as', xs);
  check(byFile[''].values === 1 && !byFile[''].workbook && byFile[''].row.length === 0, 'a value with no source is counted, not kept', byFile['']);
  check(byFile['/raw/INVENTORY/inv.csv'].values === 1 && !byFile['/raw/INVENTORY/inv.csv'].workbook, 'raw data is counted, not kept');
  check(same([...xs.point], [0, 1]), 'a value with a time is marked as a time point', [...xs.point]);
  check(R.transferables(r).length === 12, 'the typed arrays of an export are handed over, not copied');
  const lower = book([['Lower', `<row r="1"/><row r="2"></row><row r="3">${inl('A3', 'ID')}${inl('B3', 'QC reviewer')}${inl('C3', 'QC comment')}${inl('D3', 'QC status')}</row><row r="4">${inl('A4', 'p6')}${inl('B4', 'revA')}${inl('D4', 'OK-PSAR')}</row>`]]);
  const low = await R.readBook({ file: lower, path: 'low.xlsx', folder: '', name: 'low.xlsx' });
  check(low.sheets[0].kind === 'qc' && same(low.records.map((x) => [x.row, x.id]), [[4, 'p6']]), 'the header is the first row with something in it, below empty rows', low);
}

console.log(failed ? `\n${failed} failed` : '\nall passed');
process.exit(failed ? 1 : 0);
