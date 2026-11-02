#!/usr/bin/env python3
"""JSON and XML files opened as files: each value a dataset, each object or element a group.

A JSON or XML file opens as an HDF5 file the page writes in memory from its
values (rb-json.js and rb-xml.js have the layout). The files are written by
this script:

    JSON     an object of every kind of value: numbers, a vector, a matrix,
             strings, booleans, null, an array of objects that is a table,
             mixed arrays, nesting, names with a slash or none; JSON as
             Python writes it (NaN, Infinity) with comments and trailing
             commas; a top-level array; values nested too deep; broken JSON
    XML      a configuration as DarcyTools writes one (records that are
             tables, Fortran numbers), GDAL's statistics (a list of numbers
             between |, a decimal comma), elements with attributes, text
             beside elements, entities and CDATA, namespaces, UTF-16 and
             ISO-8859-1; broken XML, an entity bomb, an external entity
    both     markup in every name and value, and JSON handed over under an
             .h5 name, as a link without a name or a handoff hands it

The checks read the HDF5 file the page wrote, through the page's own h5wasm:
each value at its path with its type, a table's columns, numbers as numbers
and text as text; that a vector draws as any vector does; that broken files
are refused saying where; and that nothing in a file reaches the page as
markup or runs.

Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-json-xml.py

Exit status is 0 when every check passes.
"""
import asyncio
import base64
import json
import os
import sys
import tempfile
import time
import urllib.request

import websockets

from driver import open_page

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


XSS = '<img src=x onerror="window.__docXss=1">'

SAMPLE = {
    'name': 'Kd sample', 'version': 3, 'active': True, 'missing': None,
    'times': [0, 1, 2.5, 10, 100],
    'matrix': [[1, 2, 3], [4, 5, 6]],
    'cube': [[[1, 2], [3, 4]], [[5, 6], [7, 8]]],
    'nuclides': ['Cs-135', 'I-129', 'Ra-226'],
    'flags': [True, False, True],
    'mixed': [1, 'two', None, True],
    'rows': [{'nuclide': 'Cs-135', 'kd': 0.01, 'ok': True}, {'nuclide': 'I-129', 'kd': None},
             {'nuclide': 'Ra-226', 'kd': 0.5, 'ok': False}],
    'nested': {'a': {'b': {'c': [1, 2]}}, 'list': [{'x': [1, 2]}, {'y': 'z'}]},
    'ragged': [[1, 2], [3]],
    'a/b': 1, '': 'empty key', 'with nulls': [1, None, 3],
    'many': [{'k': [k]} for k in range(12)],
}

PYTHON_JSON = """// written by Python's json module, a comment added by hand
{"values": [1.5, NaN, Infinity, -Infinity], /* and */ "trailing": [1, 2, 3,], "big": 1e400,}
"""


def deep_json(levels):
    return '{"a":' * levels + '1' + '}' * levels


CIF = """ <cif>
<!-- ============== Case: Testing Case C0029 ============== -->
 <run> <timeout> 3000 </timeout> </run>
 <screen> <all> F </all> </screen>
 <chkp> <name> chk1 </name> <prog> dts </prog> <exp> 2.44E+4 </exp> <tol> 2.E+2 </tol> </chkp>
 <chkp> <name> chk2 </name> <prog> dts </prog> <exp> 5.60E-1 </exp> <tol> 5.D-3 </tol> </chkp>
 <law_mu> <a0> 2.E-3 </a0> <a1> 0.1 </a1> <t0> 5. </t0> </law_mu>
 <var><name>permx </name> <ini> domain 2.04E-14 </ini></var>
 <var><name>permz </name> <ini> domain 4.00E-12 </ini></var>
</cif>
"""

AUX = """<PAMDataset>
  <Metadata domain="ESRI"><MDI key="PyramidResamplingType">NEAREST</MDI></Metadata>
  <PAMRasterBand band="1"><Histograms><HistItem>
    <HistMin>-45,1305046081543</HistMin><HistMax>106</HistMax><BucketCount>8</BucketCount>
    <HistCounts>31|24|21|26|28|26|26|32</HistCounts>
  </HistItem></Histograms></PAMRasterBand>
</PAMDataset>
"""

MIXED = """<?xml version="1.0" encoding="{enc}"?>
<!DOCTYPE doc [<!ENTITY co "Kvot ab">]>
<doc xmlns:x="urn:x" lang="sv">Intro text &co; <![CDATA[<raw & cdata>]]>
  <x:item id="1" value="0.5"/><x:item id="2" value="1.5"/><x:item id="3" value="n/a"/>
  <p>first</p><p>second <b>bold</b></p>
  <zip>007</zip><year>2008</year><when>2008-08-13</when><list>1 2 3; 4</list><empty/>
  <name>Ångström</name>
</doc>
"""

BOMB = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
        + ''.join(f'<!ENTITY lol{k + 1} "{("&lol" + (str(k) if k else "") + ";") * 10}">' for k in range(9))
        + ']><lolz>&lol9;</lolz>')

EXTERNAL = '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r>&x;</r>'

HOSTILE_JSON = {XSS: XSS, 'list': [XSS, 'b'], 'rows': [{XSS: 1, 'v': XSS}, {XSS: 2, 'v': 'ok'}]}
HOSTILE_XML = ('<root a="' + XSS.replace('"', '&quot;').replace('<', '&lt;') + '"><v>'
               + XSS.replace('<', '&lt;') + '</v><v>x</v><t>' + XSS.replace('<', '&lt;') + '</t></root>')

# --- in the page -------------------------------------------------------------------

SETTLE = """(async () => {
  for (let i = 0; i < 300; i++) {
    if (document.getElementById('fileLoadTicker').hidden) break;
    await new Promise(r => setTimeout(r, 100));
  }
  await new Promise(r => setTimeout(r, 300));
  return fileOrder.slice();
})()"""

# Every dataset and group of an open file, by path: shape, type, attributes and
# values, with what JSON cannot say -- NaN and the infinities -- as text.
DUMP = """((file) => {
  const f = loadedFiles[file];
  if (!f) return 'no file';
  const say = (x) => (typeof x === 'number' && !Number.isFinite(x) ? String(x) : x);
  const list = (v) => (ArrayBuffer.isView(v) || Array.isArray(v) ? Array.from(v, say) : say(v));
  const out = {};
  const walk = (g, prefix) => {
    for (const k of Array.from(g.keys()).sort()) {
      const n = g.get(k);
      const path = prefix + '/' + k;
      const attrs = {};
      for (const a of Object.keys(n.attrs || {})) attrs[a] = list(n.attrs[a].value);
      if (n.type === 'Group') { out[path] = { group: true, attrs }; walk(n, path); }
      else out[path] = { shape: n.shape, dtype: n.dtype, attrs, value: list(n.value) };
    }
  };
  walk(f, '');
  const root = {};
  for (const a of Object.keys(f.attrs || {})) root[a] = list(f.attrs[a].value);
  return { root, tree: out };
})(%s)"""


async def pick_files(page, paths):
    doc = await page.send('DOM.getDocument', {})
    found = await page.send('DOM.querySelector', {'nodeId': doc['result']['root']['nodeId'], 'selector': '#fileInput'})
    await page.send('DOM.setFileInputFiles', {'nodeId': found['result']['nodeId'], 'files': paths})
    await page.ev('new Promise(r => setTimeout(r, 300))')
    return await page.ev(SETTLE, timeout=120)


async def banner(page):
    return await page.ev("document.querySelector('#failureBanner .failure-banner-text')?.textContent || ''")


async def ingest(page, name, data):
    """Bytes handed over under a name, as a link or a handoff hands them."""
    return await page.ev("""(async (name, b64) => {
        const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
        try { return await ingestFileBuffer(name, bytes.buffer, 'test-json-xml'); }
        catch (e) { return 'refused: ' + e.message; } })(%s, %s)"""
                         % (json.dumps(name), json.dumps(base64.b64encode(data).decode())), timeout=60)


def node(d, path):
    return d['tree'].get(path, {})


def value(d, path):
    return node(d, path).get('value')


def attr(d, path, name):
    return node(d, path).get('attrs', {}).get(name)


async def main():
    tmp = tempfile.mkdtemp(prefix='rb-docs-')
    written = {
        'sample.json': json.dumps(SAMPLE, ensure_ascii=False).encode('utf-8'),
        'python.json': PYTHON_JSON.encode('utf-8'),
        'array.json': b'[{"x": 1, "y": 2}, {"x": 2, "y": 4}, {"x": 3, "y": 9}]',
        'deep.json': deep_json(80).encode('utf-8'),
        'bad.json': b'{"a": [1, 2,\n  "b": 3}',
        'cif.xml': CIF.encode('utf-8'),
        'aux.xml': AUX.encode('utf-8'),
        'mixed.xml': MIXED.format(enc='UTF-8').encode('utf-8'),
        'latin1.xml': MIXED.format(enc='ISO-8859-1').encode('latin-1'),
        'utf16.xml': '<?xml version="1.0" encoding="UTF-16"?><r><t>héllo</t><n>1 2 3</n></r>'.encode('utf-16'),
        'bad.xml': b'<root><a>1</a></b></root>',
        'bomb.xml': BOMB.encode('utf-8'),
        'external.xml': EXTERNAL.encode('utf-8'),
        'hostile.json': json.dumps(HOSTILE_JSON).encode('utf-8'),
        'hostile.xml': HOSTILE_XML.encode('utf-8'),
    }
    for name, data in written.items():
        with open(os.path.join(tmp, name), 'wb') as fh:
            fh.write(data)
    at = lambda name: os.path.join(tmp, name)

    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=7)
        try:
            accept = (await page.ev("document.getElementById('fileInput').accept")).split(',')
            check('the file picker offers .json and .xml', ('.json' in accept, '.xml' in accept), (True, True))

            # --- JSON ------------------------------------------------------------------
            opened = await pick_files(page, [at('sample.json'), at('python.json'), at('array.json'), at('deep.json')])
            check('JSON files open, each under its own name', opened, ['sample.json', 'python.json', 'array.json', 'deep.json'])
            d = await page.ev(DUMP % json.dumps('sample.json'), timeout=60)
            check('the file says it is JSON and what it holds',
                  (d['root'].get('JSON_format'), 'sample.json: JSON' in d['root'].get('Information', '')), ('JSON', True))
            check('an object\'s members at the top, by name; a slash and an empty name made names',
                  sorted(p for p in d['tree'] if p.count('/') == 1),
                  sorted(['/""', '/a⁄b', '/active', '/cube', '/flags', '/many', '/matrix', '/missing', '/mixed', '/name', '/nested',
                          '/nuclides', '/ragged', '/rows', '/times', '/version', '/with nulls']))
            check('a number, a string, true and null: a dataset of one value, its JSON type said',
                  [(value(d, p), attr(d, p, 'JSON_type')) for p in ['/version', '/name', '/active', '/missing']],
                  [(3, 'number'), ('Kd sample', 'string'), ('true', 'boolean'), ('null', 'null')])
            check('an array of numbers is a vector of them', (node(d, '/times')['shape'], node(d, '/times')['dtype'], value(d, '/times')),
                  ([5], '<d', [0, 1, 2.5, 10, 100]))
            check('  arrays of arrays nested evenly, a matrix and more, in row order',
                  [(node(d, p)['shape'], value(d, p)) for p in ['/matrix', '/cube']],
                  [([2, 3], [1, 2, 3, 4, 5, 6]), ([2, 2, 2], [1, 2, 3, 4, 5, 6, 7, 8])])
            check('  a null among numbers is NaN, and said to be', (value(d, '/with nulls'), attr(d, '/with nulls', 'note')),
                  ([1, 'NaN', 3], '1 null shown as NaN.'))
            check('arrays of strings and of booleans are one dataset of text',
                  [(value(d, p), attr(d, p, 'of')) for p in ['/nuclides', '/flags']],
                  [(['Cs-135', 'I-129', 'Ra-226'], 'string'), (['true', 'false', 'true'], 'boolean')])
            check('  numbers and words in one array are text, and said to be',
                  (value(d, '/mixed'), 'each is shown as text' in attr(d, '/mixed', 'note')), (['1', 'two', 'null', 'true'], True))
            check('an array of objects of values is a table: a column for each member, over all of them',
                  (sorted(p for p in d['tree'] if p.startswith('/rows/')), value(d, '/rows/nuclide'), value(d, '/rows/kd'),
                   value(d, '/rows/ok'), attr(d, '/rows/ok', 'missing')),
                  (['/rows/kd', '/rows/nuclide', '/rows/ok'], ['Cs-135', 'I-129', 'Ra-226'], [0.01, 'NaN', 0.5], ['true', '', 'false'], 1))
            check('any other array is a group of its elements, numbered to sort in order',
                  ([p.split('/')[2] for p in sorted(d['tree']) if p.startswith('/many/') and p.count('/') == 2][:3],
                   value(d, '/many/[11]/k'), sorted(p for p in d['tree'] if p.startswith('/ragged/'))),
                  (['[00]', '[01]', '[02]'], [11], ['/ragged/[0]', '/ragged/[1]']))
            check('objects within objects are groups within groups',
                  (value(d, '/nested/a/b/c'), value(d, '/nested/list/[0]/x'), value(d, '/nested/list/[1]/y')), ([1, 2], [1, 2], 'z'))
            p = await page.ev(DUMP % json.dumps('python.json'), timeout=60)
            check('JSON as Python writes it, with comments and trailing commas, is read, and says so',
                  (value(p, '/values'), value(p, '/trailing'), value(p, '/big'), p['root'].get('JSON_format'),
                   'comment' in p['root'].get('Information', '')),
                  ([1.5, 'NaN', 'Infinity', '-Infinity'], [1, 2, 3], 'Infinity', 'JSON, read leniently', True))
            a = await page.ev(DUMP % json.dumps('array.json'), timeout=60)
            check('a top-level array goes under the file\'s name', (value(a, '/array/x'), value(a, '/array/y')), ([1, 2, 3], [2, 4, 9]))
            dp = await page.ev(DUMP % json.dumps('deep.json'), timeout=60)
            deepest = max((k for k in dp['tree']), key=lambda k: k.count('/'))
            check('values nested too deep stop, and say so',
                  (deepest.count('/'), attr(dp, deepest, 'note')), (65, 'Values nested more than 64 deep are not shown.'))

            # a vector draws as any vector does
            shown = await page.ev("""(async () => {
                const row = findTreeItem('/times', { fileKey: 'sample.json', root: document.getElementById('tree'), allowMissingFile: true });
                row.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                await new Promise(r => setTimeout(r, 1500));
                const pd = document.getElementById('plotlyChart');
                return [document.getElementById('plotlyChartContainer').classList.contains('visible'), (pd.data || []).length > 0,
                        document.getElementById('info').textContent.includes('JSON_type')]; })()""", timeout=30)
            check('a JSON vector clicked is drawn, and its JSON type shown', shown, [True, True, True])

            before = await page.ev('fileOrder.length')
            await pick_files(page, [at('bad.json')])
            check('broken JSON is refused, saying where', ('a comma or ] expected at line 2, column 6' in await banner(page),
                                                          await page.ev('fileOrder.length')), (True, before))
            check('JSON handed over under an .h5 name is read as JSON',
                  await ingest(page, 'handoff.h5', written['array.json']), ['handoff.h5'])
            check('an address ending in .json or .xml keeps its name',
                  [await page.ev(f"hdf5FileNameFromUrl(new URL('https://example.com/data/{n}'))") for n in ('a.json', 'b.xml')],
                  ['a.json', 'b.xml'])

            # --- XML -------------------------------------------------------------------
            opened = await pick_files(page, [at('cif.xml'), at('aux.xml'), at('mixed.xml'), at('latin1.xml'), at('utf16.xml')])
            check('XML files open', opened[-5:], ['cif.xml', 'aux.xml', 'mixed.xml', 'latin1.xml', 'utf16.xml'])
            c = await page.ev(DUMP % json.dumps('cif.xml'), timeout=60)
            check('the root element at the top, by its tag', ([k for k in c['tree'] if k.count('/') == 1], c['root'].get('XML_format')),
                  (['/cif'], 'XML'))
            check('an element of a number is that number; a word is text; Fortran\'s 5. and 5.D-3 are numbers',
                  (value(c, '/cif/run/timeout'), value(c, '/cif/screen/all'), value(c, '/cif/law_mu/t0'), value(c, '/cif/chkp/tol')),
                  (3000, 'F', 5, [200, 0.005]))
            check('elements of one tag that are records are a table, a column for each element',
                  (sorted(k for k in c['tree'] if k.startswith('/cif/chkp/')), value(c, '/cif/chkp/exp'), value(c, '/cif/chkp/name'),
                   attr(c, '/cif/chkp/exp', 'XML_type')),
                  (['/cif/chkp/exp', '/cif/chkp/name', '/cif/chkp/prog', '/cif/chkp/tol'], [24400, 0.56], ['chk1', 'chk2'], 'number'))
            check('  a column of numbers and words is text', value(c, '/cif/var/ini'), ['domain 2.04E-14', 'domain 4.00E-12'])
            x = await page.ev(DUMP % json.dumps('aux.xml'), timeout=60)
            check('numbers between | are a vector; a decimal comma is no list, and stays text',
                  (value(x, '/PAMDataset/PAMRasterBand/Histograms/HistItem/HistCounts'),
                   value(x, '/PAMDataset/PAMRasterBand/Histograms/HistItem/HistMin')),
                  ([31, 24, 21, 26, 28, 26, 26, 32], '-45,1305046081543'))
            check('attributes are attributes, named @name, on groups and datasets',
                  (attr(x, '/PAMDataset/PAMRasterBand', '@band'), attr(x, '/PAMDataset/Metadata/MDI', '@key'),
                   value(x, '/PAMDataset/Metadata/MDI')), ('1', 'PyramidResamplingType', 'NEAREST'))
            m = await page.ev(DUMP % json.dumps('mixed.xml'), timeout=60)
            check('text beside elements is #text: entities and CDATA read as XML reads them',
                  value(m, '/doc/#text'), 'Intro text Kvot ab <raw & cdata>')
            check('elements of one tag that are not records are tag[1], tag[2]',
                  (value(m, '/doc/p[1]'), value(m, '/doc/p[2]/#text'), value(m, '/doc/p[2]/b')), ('first', 'second', 'bold'))
            check('elements of attributes alone are a table of them, a column a number when every value is',
                  (value(m, '/doc/x:item/@id'), value(m, '/doc/x:item/@value'), attr(m, '/doc', '@xmlns:x')),
                  ([1, 2, 3], ['0.5', '1.5', 'n/a'], 'urn:x'))
            check('007 stays a code, 2008 is a number, a date is text, 1 2 3; 4 a list, an empty element empty',
                  [value(m, f'/doc/{t}') for t in ('zip', 'year', 'when', 'list', 'empty')], ['007', 2008, '2008-08-13', [1, 2, 3, 4], ''])
            l1 = await page.ev(DUMP % json.dumps('latin1.xml'), timeout=60)
            u16 = await page.ev(DUMP % json.dumps('utf16.xml'), timeout=60)
            check('read in the encoding the file declares, or its byte-order mark says',
                  (value(m, '/doc/name'), value(l1, '/doc/name'), l1['root'].get('XML_encoding'), value(u16, '/r/t'), value(u16, '/r/n')),
                  ('Ångström', 'Ångström', 'ISO-8859-1', 'héllo', [1, 2, 3]))

            before = await page.ev('fileOrder.length')
            await pick_files(page, [at('bad.xml')])
            check('broken XML is refused, saying where',
                  ('Unexpected closing tag: b != root at line 1, column 18' in await banner(page), await page.ev('fileOrder.length')),
                  (True, before))
            t0 = time.time()
            await pick_files(page, [at('bomb.xml')])
            check('an entity that grows without end is refused, at once',
                  ('Entity too big' in await banner(page), time.time() - t0 < 10, await page.ev('fileOrder.length')), (True, True, before))
            await pick_files(page, [at('external.xml')])
            e = await page.ev(DUMP % json.dumps('external.xml'), timeout=60)
            check('an entity naming a file outside is not read', value(e, '/r'), '')
            check('an HTML page handed over is no XML: it is refused as before, with the reason',
                  'Downloaded content is HTML' in await ingest(page, 'page.h5', b'<!DOCTYPE html><html><body>not data</body></html>'), True)

            # --- hostile ---------------------------------------------------------------
            await pick_files(page, [at('hostile.json'), at('hostile.xml')])
            h = await page.ev(DUMP % json.dumps('hostile.json'), timeout=60)
            hx = await page.ev(DUMP % json.dumps('hostile.xml'), timeout=60)
            check('markup in names and values is text in the file written',
                  (value(h, '/' + XSS), value(h, '/rows/' + XSS), attr(hx, '/root', '@a'), value(hx, '/root/t')), (XSS, [1, 2], XSS, XSS))
            shown = await page.ev("""(async () => {
                for (const f of ['hostile.json', 'hostile.xml']) {
                  for (const path of ['/', f === 'hostile.json' ? '/rows' : '/root']) {
                    await figRevealInTree(f, path);
                    await new Promise(r => setTimeout(r, 600));
                  }
                }
                return [[...document.querySelectorAll('#tree .tree-label')].some(l => l.textContent.includes('<img')),
                        document.querySelectorAll('#tree img, #info img').length]; })()""", timeout=60)
            check('  shown as text in the tree and the panel; nothing in them runs',
                  (shown, await page.ev('typeof window.__docXss')), ([True, 0], 'undefined'))

            expected = ('could not be read as JSON', 'could not be read as XML', 'Downloaded content is HTML')
            check('no console errors but the refusals', [msg for kind, msg in page.logs
                  if not any(s in msg for s in expected) and 'favicon' not in msg][:3], [])
        finally:
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
