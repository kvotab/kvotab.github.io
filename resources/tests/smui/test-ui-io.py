#!/usr/bin/env python3
"""smui.html in a real browser: tables read by File > Open (SM.io.readFile).

A CSV table of 200,000 rows opens: the widest row was once found by
spreading every row into Math.max, and a table of some 125,000 rows or more
ran past the stack. Workbooks whose rows and cells leave out where they are
(their r), as the format allows and some programs do, open with each value
in its place, where a cell without one stopped the reading ("Cannot read
properties of null"). A value in Excel's last row opens. A formatted cell
with nothing in it, far out, stretches nothing. A sheet with a cell past
column XFD, a row past 1,048,576, or values over more than 10,000,000 cells
from A1 is not read, and said, where it once held the page for seconds and
took gigabytes; a workbook's other sheets still open, their notes saying
which was not read.

Start a server on the repository root and headless Chrome (the recipe is in
../rb/README.md) on SMUI_HTTP_PORT and SMUI_CDP_PORT (defaults 8791, 9291),
then

    python3 resources/tests/smui/test-ui-io.py

Exit status 0 when every check passes.
"""
import asyncio
import base64
import io
import json
import sys
import zipfile

from cdp import BASE, Checks, open_page

check = Checks()

NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
RNS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def xlsx(sheets):
    """A workbook of sheets [(name, the XML of its rows)]."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="xml" ContentType="application/xml"/></Types>')
        z.writestr('xl/workbook.xml', f'<?xml version="1.0"?><workbook {NS} {RNS}><sheets>'
                   + ''.join(f'<sheet name="{n}" sheetId="{k + 1}" r:id="rId{k + 1}"/>' for k, (n, _) in enumerate(sheets)) + '</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + ''.join(f'<Relationship Id="rId{k + 1}" Target="worksheets/sheet{k + 1}.xml"/>' for k in range(len(sheets))) + '</Relationships>')
        for k, (_, rows) in enumerate(sheets):
            z.writestr(f'xl/worksheets/sheet{k + 1}.xml', f'<?xml version="1.0"?><worksheet {NS}><sheetData>{rows}</sheetData></worksheet>')
    return out.getvalue()


def text(v, ref=None):
    return f'<c{f" r={chr(34)}{ref}{chr(34)}" if ref else ""} t="inlineStr"><is><t>{v}</t></is></c>'


def num(v, ref=None):
    return f'<c{f" r={chr(34)}{ref}{chr(34)}" if ref else ""}><v>{v}</v></c>'


# x and y, then rows 2..5 of k and 2k: each row and cell with its r, or not
def table(row_r=True, cell_r=True):
    row = lambda k: f'<row r="{k}">' if row_r else '<row>'
    ref = lambda c, k: f'{c}{k}' if cell_r else None
    return (row(1) + text('x', ref('A', 1)) + text('y', ref('B', 1)) + '</row>'
            + ''.join(row(k) + num(k, ref('A', k)) + num(2 * k, ref('B', k)) + '</row>' for k in range(2, 6)))


READ = """(async (name, b64) => {
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  try {
    const tables = await SM.io.readFile(new File([bytes], name));
    return tables.map((t) => ({ name: t.name, rows: t.nrows, columns: t.columns.map((c) => c.name),
      first: t.columns.slice(0, 2).map((c) => Array.from(c.values).slice(0, 4)), notes: t.notes }));
  } catch (e) { return `${e.name}: ${e.message}`; }
})(%s, %s)"""


async def main():
    page = await open_page(f'{BASE}/smui.html')
    read = lambda name, data, timeout=120: page.ev(READ % (json.dumps(name), json.dumps(base64.b64encode(data).decode())), timeout=timeout)

    big = 'x,y\n' + ''.join(f'{k},{2 * k}\n' for k in range(200000))
    r = await read('big.csv', big.encode())
    check('a CSV table of 200,000 rows opens', r if isinstance(r, str) else (r[0]['rows'], r[0]['columns'], r[0]['first']),
          (200000, ['x', 'y'], [[0, 1, 2, 3], [0, 2, 4, 6]]))

    want = [{'name': 'places', 'rows': 4, 'columns': ['x', 'y'], 'first': [[2, 3, 4, 5], [4, 6, 8, 10]], 'notes': ''}]
    for label, kw in (('cells', {'cell_r': False}), ('rows', {'row_r': False}), ('rows and cells', {'row_r': False, 'cell_r': False})):
        check(f'a workbook whose {label} leave out where they are: each value in its place',
              await read('places.xlsx', xlsx([('Data', table(**kw))])), want)

    r = await read('last.xlsx', xlsx([('Data', table() + '<row r="1048576">' + num(7, 'A1048576') + '</row>')]))
    check('a value in Excel\'s last row opens', r if isinstance(r, str) else (r[0]['rows'], r[0]['first'][0][:1]), (1048575, [2]))
    # A value in Excel's last column makes a table of 16,384 columns: each
    # column's name was once checked by gathering every name before it again,
    # and the table took five seconds to make. The work counted, not timed.
    r = await page.ev("""(async (b64) => {
      const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      const own = SM.Table.prototype.uniqueName;
      let gathered = 0;
      SM.Table.prototype.uniqueName = function (base) { gathered++; return own.call(this, base); };
      try {
        const [t] = await SM.io.readFile(new File([bytes], 'wide.xlsx'));
        return [t.columns.length, t.columns[16383].name, gathered];
      } catch (e) { return `${e.name}: ${e.message}`; } finally { SM.Table.prototype.uniqueName = own; }
    })(%s)""" % json.dumps(base64.b64encode(xlsx([('Data', table() + '<row r="6">' + num(1, 'XFD6') + '</row>')])).decode()), timeout=120)
    check('a value in column XFD: a table of 16,384 columns, its names made unique without gathering them for each',
          r, [16384, 'Column 16384', 0])
    r = await read('styled.xlsx', xlsx([('Data', table() + '<row r="1048576"><c r="XFD1048576" s="1"/></row>')]))
    check('a formatted cell with nothing in it, at XFD1048576, stretches nothing', r if isinstance(r, str) else (r[0]['rows'], r[0]['columns']),
          (4, ['x', 'y']))
    check('a sheet with a cell past column XFD is not read, and said',
          await read('far.xlsx', xlsx([('Data', table() + '<row r="6">' + num(1, 'ZZZZZZ6') + '</row>')])),
          'Error: no sheet could be read: sheet Data: a cell, ZZZZZZ6, lies past column XFD, the last Excel has')
    check('... a row past 1,048,576 likewise',
          await read('down.xlsx', xlsx([('Data', table() + '<row r="4294967294">' + num(1, 'A4294967294') + '</row>')])),
          'Error: no sheet could be read: sheet Data: a row, 4294967294, lies past row 1,048,576, the last Excel has')
    check('... and values over more than 10,000,000 cells from A1, with how far they reach',
          await read('wide.xlsx', xlsx([('Data', table() + '<row r="1048576">' + num(1, 'XFD1048576') + '</row>')])),
          'Error: no sheet could be read: sheet Data: its values reach row 1,048,576 and column 16,384: 17,179,869,184 cells from A1, '
          'more than the 10,000,000 this reads. A value that far out is often a stray one: clear it in Excel and save the workbook again')
    r = await read('two.xlsx', xlsx([('Far', '<row r="1">' + num(1, 'ZZZZZZ1') + '</row>'), ('Data', table())]))
    check('a workbook\'s other sheets open, their notes saying which was not read',
          r if isinstance(r, str) else (len(r), r[0]['rows'], r[0]['notes']),
          (1, 4, 'Not read: sheet Far: a cell, ZZZZZZ1, lies past column XFD, the last Excel has.'))

    await page.close()
    return check.done()


sys.exit(asyncio.run(main()))
