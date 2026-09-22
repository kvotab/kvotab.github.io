#!/usr/bin/env python3
"""zoterify.html in a real browser, and the document it writes.

Loads the page, gives it fixtures/fixture.docx and the fixture Zotero
database (with its -wal file), analyses, makes the decisions a user would,
saves, and then takes the saved .docx apart:

  - every tracked change the page made is by its author and well formed;
  - accepting them gives the original text, with each citation now the
    result of a Zotero field whose JSON names the right items;
  - rejecting them gives the original text exactly, other people's
    revisions untouched;
  - revision ids are unique and above every id the document had;
  - w:trackRevisions sits where the schema puts it, the author is in
    people.xml, and the parts the page did not edit are byte for byte the
    parts it was given.

Start a server at the repository root and a headless Chrome, as in
../rb/README.md (ports can be changed below), then

    python3 resources/tests/zoterify/test-ui.py

Exit status is 0 when every check passes.
"""
import asyncio
import base64
import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from xml.dom import minidom

import websockets

PORT = int(os.environ.get('ZF_PORT', '8765'))
CDP = int(os.environ.get('ZF_CDP', '9222'))
URL = f'http://127.0.0.1:{PORT}/zoterify.html'
FIX = '/resources/tests/zoterify/fixtures/'
HERE = os.path.dirname(os.path.abspath(__file__))
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


class Page:
    def __init__(self, bws):
        self.bws = bws
        self.n = 0
        self.pending = {}
        self.sid = None
        self.errors = []

    async def call(self, method, params=None, session=None):
        self.n += 1
        i = self.n
        msg = {'id': i, 'method': method, 'params': params or {}}
        if session:
            msg['sessionId'] = session
        fut = asyncio.get_event_loop().create_future()
        self.pending[i] = fut
        await self.bws.send(json.dumps(msg))
        return await asyncio.wait_for(fut, 180)

    async def pump(self):
        async for raw in self.bws:
            r = json.loads(raw)
            if r.get('method') == 'Runtime.exceptionThrown':
                d = r['params']['exceptionDetails']
                self.errors.append(str(d.get('exception', {}).get('description') or d.get('text', ''))[:300])
            if r.get('method') == 'Runtime.consoleAPICalled' and r['params'].get('type') == 'error':
                self.errors.append(' '.join(str(a.get('value', a.get('description', ''))) for a in r['params']['args'])[:300])
            if 'id' in r and r['id'] in self.pending and not self.pending[r['id']].done():
                self.pending[r['id']].set_result(r)

    async def ev(self, expr):
        r = await self.call('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True}, session=self.sid)
        res = r.get('result', {})
        if 'exceptionDetails' in res:
            return 'EXCEPTION: ' + str(res['exceptionDetails'].get('exception', {}).get('description', ''))[:400]
        return res.get('result', {}).get('value')


# ---------------------------------------------------------------------------
# Reading a saved document back
# ---------------------------------------------------------------------------

def el_children(node):
    return [c for c in node.childNodes if c.nodeType == c.ELEMENT_NODE]


def local(node):
    return node.localName


def visible_text(p, accept_author=None, reject_author=None):
    """The text of a paragraph with tracked changes applied: as it stands,
    or with one author's changes accepted or rejected."""
    out = []
    stack = []

    def is_ours(node):
        return node.getAttributeNS(W, 'author') == (accept_author or reject_author)

    def walk(node):
        for c in el_children(node):
            name = local(c)
            if name in ('del', 'moveFrom'):
                if reject_author and is_ours(c):
                    walk_deleted(c)
                continue
            if name == 'ins' and reject_author and is_ours(c):
                continue
            if name == 'r':
                run(c, deleted=False)
            elif name in ('ins', 'moveTo', 'hyperlink', 'smartTag', 'customXml', 'fldSimple', 'sdt', 'sdtContent'):
                walk(c)

    def walk_deleted(node):
        for c in el_children(node):
            if local(c) == 'r':
                run(c, deleted=True)
            else:
                walk_deleted(c)

    def run(r, deleted):
        for c in el_children(r):
            name = local(c)
            if name == 'fldChar':
                typ = c.getAttributeNS(W, 'fldCharType')
                if typ == 'begin':
                    stack.append('instr')
                elif typ == 'separate' and stack:
                    stack[-1] = 'result'
                elif typ == 'end' and stack:
                    stack.pop()
            elif name in ('t', 'delText') and all(s == 'result' for s in stack):
                if name == 't' or deleted:
                    out.append(c.firstChild.data if c.firstChild else '')
            elif name in ('tab', 'ptab') and all(s == 'result' for s in stack):
                out.append('\t')
            elif name in ('br', 'cr') and all(s == 'result' for s in stack):
                out.append('\n')
            elif name == 'noBreakHyphen' and all(s == 'result' for s in stack):
                out.append('\u2011')
    walk(p)
    return ''.join(out)


def paragraphs(doc):
    body = doc.getElementsByTagNameNS(W, 'body')[0]
    found = []

    def walk(node):
        for c in el_children(node):
            if local(c) == 'p':
                found.append(c)
            elif local(c) not in ('sectPr', 'pPr'):
                walk(c)
    walk(body)
    return found


def zotero_fields(doc):
    """(instruction JSON, result text) of every ZOTERO_ITEM field, from the
    runs in document order, following w:instrText and w:delInstrText alike."""
    fields = []
    for p in doc.getElementsByTagNameNS(W, 'p'):
        cur = None
        for r in p.getElementsByTagNameNS(W, 'r'):
            deleted = any(local(a) == 'del' for a in ancestors(r))
            for c in el_children(r):
                name = local(c)
                if name == 'fldChar':
                    typ = c.getAttributeNS(W, 'fldCharType')
                    if typ == 'begin' and cur is None:
                        cur = {'instr': '', 'text': '', 'phase': 'instr', 'deleted': deleted, 'depth': 1}
                    elif typ == 'begin':
                        cur['depth'] += 1
                    elif typ == 'separate' and cur and cur['depth'] == 1:
                        cur['phase'] = 'result'
                    elif typ == 'end' and cur:
                        cur['depth'] -= 1
                        if cur['depth'] == 0:
                            fields.append(cur)
                            cur = None
                elif name in ('instrText', 'delInstrText') and cur and cur['phase'] == 'instr' and cur['depth'] == 1:
                    cur['instr'] += c.firstChild.data if c.firstChild else ''
                elif name in ('t', 'delText') and cur and cur['phase'] == 'result':
                    cur['text'] += c.firstChild.data if c.firstChild else ''
    out = []
    for f in fields:
        if 'ZOTERO_ITEM' not in f['instr']:
            continue
        j = f['instr']
        out.append({'json': json.loads(j[j.index('{'):j.rindex('}') + 1]), 'text': f['text'], 'deleted': f['deleted']})
    return out


def ancestors(node):
    a = node.parentNode
    while a is not None and a.nodeType == a.ELEMENT_NODE:
        yield a
        a = a.parentNode


async def main():
    ver = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=400 * 1024 * 1024) as bws:
        page = Page(bws)
        asyncio.create_task(page.pump())
        tid = (await page.call('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
        page.sid = (await page.call('Target.attachToTarget', {'targetId': tid, 'flatten': True}))['result']['sessionId']
        for m in ('Runtime.enable', 'Page.enable', 'Network.enable'):
            await page.call(m, session=page.sid)
        await page.call('Network.setCacheDisabled', {'cacheDisabled': True}, session=page.sid)
        await page.call('Emulation.setDeviceMetricsOverride', {'width': 1400, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
        await page.call('Page.addScriptToEvaluateOnNewDocument', {'source': """
            try { Object.keys(localStorage).filter(k => k.startsWith('kvot-zf-')).forEach(k => localStorage.removeItem(k)); } catch (e) {}
            // Keep what the page downloads instead of saving it.
            window.__downloads = [];
            const origCreate = URL.createObjectURL;
            URL.createObjectURL = (blob) => { window.__downloads.push(blob); return origCreate(blob); };
            HTMLAnchorElement.prototype.click = function () {};
        """}, session=page.sid)
        await page.call('Page.navigate', {'url': URL}, session=page.sid)
        await asyncio.sleep(2.5)
        try:
            await run_checks(page)
        finally:
            await page.call('Target.closeTarget', {'targetId': tid})


async def load(page, names):
    js = ('(async () => { const files = [];'
          + ''.join(f"files.push(new File([await (await fetch('{FIX}{n}')).arrayBuffer()], '{n}'));" for n in names)
          + ' await ZFPage.addFiles(files); return document.getElementById("zfStatus").textContent; })()')
    return await page.ev(js)


async def run_checks(page):
    check('the page loads without a script error', page.errors, [])
    check('the modules are there', await page.ev('[typeof ZFParse, typeof ZFMatch, typeof ZFZotero, typeof ZFDocx, typeof ZFPage].join()'),
          'object,object,object,object,object')
    check('Analyse waits for both files', await page.ev("document.getElementById('zfAnalyse').disabled"), True)
    # renderNav leaves the current page out of its own menu, so: the entry is
    # in site.js for every other page, and this page's menu lists the others.
    check('site.js lists the page for the other pages\' menus',
          await page.ev("fetch('./resources/js/site.js').then(r => r.text()).then(t => t.includes(\"href: './zoterify.html'\"))"), True)
    check('and this page\'s menu lists the others', await page.ev("!!document.querySelector('#menu a[href=\"./skbref.html\"]')"), True)

    status = await load(page, ['fixture.docx'])
    check('the document is read', status, 'Now open your zotero.sqlite.')
    info = await page.ev("document.getElementById('zfDocInfo').textContent")
    check('its tracked changes are counted', '3 tracked changes already in it' in info, True)
    check('and its existing citations', 'Already coded: 1 Zotero citation, 1 EndNote citation.' in info, True)

    status = await load(page, ['fixture-wal.sqlite', 'fixture-wal.sqlite-wal'])
    check('the database opens (sql.js from cdnjs, integrity checked)', status, 'Press Analyse.')
    info = await page.ev("document.getElementById('zfDbInfo').textContent")
    check('the -wal file is replayed', '11 pages of recent changes replayed from the WAL file' in info, True)
    check('13 citable items, Stone from the -wal file among them', '13 citable items in My Library and Team references' in info, True)
    check('the scope list has both libraries and the live collections',
          await page.ev("[...document.getElementById('zfScope').options].map(o => o.textContent).join('|')"),
          'All libraries (13)|My Library (11)|Team references (2)|My Library / Thesis (1)|My Library / Thesis / Chapter 2 (2)|Team references / Site data (1)')

    await page.ev('ZFPage.analyse()')
    st = await page.ev("JSON.stringify(ZFPage.getState().run.results.map((r, i) => [r.ref.label, ZFPage.statusOf(i), r.item ? r.item.key : null, !!r.entryConfirmed]))")
    rows = json.loads(st)
    print('      ', [f'{l}={s}' for l, s, _, _ in rows])
    got = {}
    for label, status, key, confirmed in rows:
        got.setdefault(label, (status, key, confirmed))
    want = {
        'Smith 2020': 'matched', 'Garcia & Lopez 2021': 'matched', 'Brown 2019': 'matched', 'Jones 2020': 'matched',
        'Zzyzx 1999': 'none', 'Öhman et al. 2014': 'matched', 'Lane 2014': 'matched', 'Bildtgård 2010': 'matched',
        'Stone et al. 2017': 'year', 'Nilsson 2015': 'ambiguous',
        'SKB R-13-25': 'matched', 'SKB R-19-01': 'matched',
    }
    for k, v in want.items():
        check(f'{k} is {v}', got.get(k, (None,))[0], v)
    check('the reference list settles the two Jones 2020 papers', got['Jones 2020'][1:], ('JONES20A', True))
    check('report numbers find their items, in the group library too', [got['SKB R-13-25'][1], got['SKB R-19-01'][1]], ['OHMAN014', 'BROWN019'])
    await page.ev("document.querySelector('[data-tab=\"linked\"]').click()")
    check('... and the page says it was by report number',
          await page.ev("[...document.querySelectorAll('#zfLinked tr')].filter(r => r.textContent.includes('SKB R-19-01')).map(r => r.textContent.includes('report number')).join()"), 'true')
    await page.ev("document.querySelector('[data-tab=\"review\"]').click()")
    labels = [r[0] for r in rows]
    check('the deleted "(Jones, 2018)" is not a citation', 'Jones 2018' in labels, False)
    check('the existing Zotero citation is not found again', labels.count('Lane 2014'), 1)
    check('the EndNote citation is found in its field result', labels.count('Brown 2019') >= 4, True)
    check('the footnote citation is found', await page.ev("ZFPage.getState().run.parsed.groups.some(g => g.story === 'footnote' && g.text === '(Smith, 2020)')"), True)
    check('the table citation is found', await page.ev("ZFPage.getState().run.parsed.groups.some(g => ZFPage.getState().run.shown[g.para].startsWith('In a table'))"), True)
    check('one uncited entry', await page.ev("JSON.stringify(ZFPage.getState().run.uncited.map(e => e.text))"), json.dumps(['Uncited U, 2001. Never cited anywhere. Nowhere Press.']))
    check('the review tab shows the choice, the year and the not found',
          await page.ev("[...document.querySelectorAll('#zfReview .zf-item')].map(e => e.className.replace('zf-item ', '')).join()"), 'amb,sug,none')
    check('the choice offers both Nilsson papers',
          await page.ev("document.querySelectorAll('#zfReview .zf-item.amb .zf-cands li').length"), 2)
    check('the context shows the citation marked',
          await page.ev("document.querySelector('#zfReview .zf-item.amb mark').textContent"), '(Nilsson, 2015)')

    # --- decisions --------------------------------------------------------
    # Choose Nilsson 2015 B, confirm the Stone year, and search for nothing
    # useful on Zzyzx.
    await page.ev("[...document.querySelectorAll('#zfReview .zf-item.amb button[data-on-click=\"zf:choose\"]')].find(b => b.closest('li').textContent.includes('erosion rates')).click()")
    await page.ev("document.querySelector('#zfReview .zf-item.sug button[data-on-click=\"zf:choose\"]').click()")
    await page.ev("(() => { const i = document.querySelector('#zfReview .zf-item.none input'); i.value = 'jones copper'; i.dispatchEvent(new Event('input', { bubbles: true })); })()")
    check('searching the library finds by author and title words',
          await page.ev("document.querySelector('#zfReview .zf-item.none .zf-cands li').textContent.includes('Copper corrosion')"), True)
    check('after deciding, only the unmatched is left to review',
          await page.ev("[...document.querySelectorAll('#zfReview .zf-item')].map(e => e.className.replace('zf-item ', '')).join()"), 'none')
    check('the tab count says 1', await page.ev("document.querySelector('[data-tab=\"review\"] .zf-count').textContent"), '1')

    # --- save -------------------------------------------------------------
    await page.ev('ZFPage.save()')
    status = await page.ev("document.getElementById('zfStatus').textContent")
    print('      ', status)
    check('the save reports what it wrote', status.startswith('Saved fixture_zotero.docx:'), True)
    report = await page.ev("document.getElementById('zfSaveReport').textContent")
    check('the footnote-reference case is refused with its reason', 'the text contains a footnote reference' in report, True)
    check('the half-resolved parenthesis is left as text', 'not every reference in it is resolved yet' in report, True)
    check('no script errors while working', page.errors, [])

    saved = await saved_bytes(page)
    with open(os.path.join(HERE, 'fixtures', 'fixture.docx'), 'rb') as f:
        original = f.read()
    check_document(original, saved)

    # --- the report ---------------------------------------------------------
    await page.ev("document.getElementById('zfExport').click()")
    csv = await page.ev("window.__downloads[window.__downloads.length - 1].text()")
    check('the report is CSV with a header', csv.lstrip('\ufeff').startswith('"where","citation","reference","state","zotero key","zotero item","reference list entry"'), True)
    check('with every reference and where it stands', '"¶ 12","(Zzyzx, 1999)","Zzyzx 1999","not found"' in csv, True)
    check('and the entries nothing cites', '"uncited entry","","","Uncited U, 2001.' in csv, True)

    # --- saving without Track Changes -------------------------------------
    await page.ev("(() => { for (const id of ['zfTrack', 'zfKeepTracking']) { const b = document.getElementById(id); b.checked = false; b.dispatchEvent(new Event('change', { bubbles: true })); } })()")
    await page.ev('ZFPage.save()')
    plain = zipfile.ZipFile(io.BytesIO(await saved_bytes(page)))
    doc_p = minidom.parseString(plain.read('word/document.xml'))
    check('without Track Changes: no revision by the page', [e for e in doc_p.getElementsByTagNameNS(W, '*') if local(e) in ('ins', 'del') and e.getAttributeNS(W, 'author') == 'Zoterify'], [])
    check('Alice\'s revisions are still there', len([e for e in doc_p.getElementsByTagNameNS(W, '*') if local(e) in ('ins', 'del', 'rPrChange') and e.getAttributeNS(W, 'author') == 'Alice']) >= 3, True)
    check('the same fields are written', sorted(f['text'] for f in zotero_fields(doc_p) if not f['deleted']),
          sorted(f['text'] for f in zotero_fields(minidom.parseString(zipfile.ZipFile(io.BytesIO(saved)).read('word/document.xml'))) if not f['deleted']))
    check('the old EndNote field is gone, not struck through', 'EN.CITE' in plain.read('word/document.xml').decode(), False)
    check('the text reads the same', all(visible_text(a) == visible_text(b) for a, b in zip(paragraphs(minidom.parseString(zipfile.ZipFile(io.BytesIO(original)).read('word/document.xml'))), paragraphs(doc_p))), True)
    check('Track Changes is not switched on', b'trackRevisions' in plain.read('word/settings.xml'), False)
    check('no people.xml without revisions', 'word/people.xml' in plain.namelist(), False)
    check('no script errors at the end', page.errors, [])


async def saved_bytes(page):
    b64 = await page.ev("(async () => { const b = ZFPage.getState().lastSaved; let s = ''; for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode.apply(null, b.subarray(i, i + 32768)); return btoa(s); })()")
    return base64.b64decode(b64)


def check_document(original, saved):
    zo = zipfile.ZipFile(io.BytesIO(original))
    zs = zipfile.ZipFile(io.BytesIO(saved))
    if os.environ.get('ZF_KEEP'):   # a path: keep the saved document there, to open in Word
        with open(os.environ['ZF_KEEP'], 'wb') as f:
            f.write(saved)
    names_o = set(zo.namelist())
    names_s = set(zs.namelist())
    check('word/people.xml is the one part added', sorted(names_s - names_o), ['word/people.xml'])
    for n in sorted(names_o - {'word/document.xml', 'word/footnotes.xml', 'word/settings.xml', 'word/_rels/document.xml.rels', '[Content_Types].xml'}):
        check(f'{n} is untouched', zs.read(n), zo.read(n))

    doc_o = minidom.parseString(zo.read('word/document.xml'))
    doc_s = minidom.parseString(zs.read('word/document.xml'))
    ps_o = paragraphs(doc_o)
    ps_s = paragraphs(doc_s)
    check('the same number of paragraphs', len(ps_s), len(ps_o))

    author = 'Zoterify'
    ours = [e for e in doc_s.getElementsByTagNameNS(W, '*') if local(e) in ('ins', 'del') and e.getAttributeNS(W, 'author') == author]
    check('every change by the page has an id, author and date without milliseconds',
          all(e.getAttributeNS(W, 'id').isdigit() and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', e.getAttributeNS(W, 'date')) for e in ours), True)
    revision_names = ('ins', 'del', 'moveFrom', 'moveTo', 'rPrChange', 'pPrChange', 'sectPrChange', 'tblPrChange', 'trPrChange', 'tcPrChange')
    ids = [int(e.getAttributeNS(W, 'id')) for part in (doc_s, minidom.parseString(zs.read('word/footnotes.xml')))
           for e in part.getElementsByTagNameNS(W, '*') if e.getAttributeNS(W, 'id').lstrip('-').isdigit() and local(e) in revision_names]
    check('revision ids, formatting changes included, are unique', len(ids), len(set(ids)))
    check('the split run\'s formatting change is in both halves, under two ids',
          sorted(int(e.getAttributeNS(W, 'id')) for e in ps_s[1].getElementsByTagNameNS(W, 'rPrChange'))[0], 43)
    check('... and there are two of them', len(ps_s[1].getElementsByTagNameNS(W, 'rPrChange')), 2)
    new_ids = [int(e.getAttributeNS(W, 'id')) for e in ours]
    check('and the new ones are above every id the document had (57)', min(new_ids) > 57, True)
    check('no w:t is left inside the page\'s deletions',
          sum(len(e.getElementsByTagNameNS(W, 't')) + len(e.getElementsByTagNameNS(W, 'instrText')) for e in ours if local(e) == 'del'), 0)

    # Rejecting the page's changes gives back the original text exactly; the
    # document "as it stands" there includes Alice's insertion and not her
    # deletion.
    for k, (po, ps) in enumerate(zip(ps_o, ps_s)):
        before = visible_text(po)
        rejected = visible_text(ps, reject_author=author)
        if rejected != before:
            check(f'paragraph {k}: rejecting gives the original', rejected, before)
    check('rejecting every change of the page gives the original text of every paragraph',
          all(visible_text(ps, reject_author=author) == visible_text(po) for po, ps in zip(ps_o, ps_s)), True)
    check('accepting them gives the same text too (the field shows the old citation until Zotero refreshes it)',
          all(visible_text(ps) == visible_text(po) for po, ps in zip(ps_o, ps_s)), True)

    fields = zotero_fields(doc_s)
    live = [f for f in fields if not f['deleted']]
    by_text = {}
    for f in live:
        by_text.setdefault(f['text'], []).append(f['json'])
    print('       fields written:', sorted(f['text'] for f in live))
    check('the existing Zotero citation is still there, unchanged', any(f['json']['citationID'] == 'old1' for f in live), True)

    def items(text, n=0):
        return [(ci['uris'][0].rsplit('/', 1)[1], ci.get('locator'), ci.get('label'), ci.get('prefix'), ci.get('suppress-author', False))
                for ci in by_text[text][n]['citationItems']]

    check('the split citation becomes one field', items('(Smith, 2020)')[0], ('SMITH020', None, None, None, False))
    check('the narrative citation: only the parenthesis, author suppressed, page locator',
          items('(2020, p. 4)'), [('SMITH020', '4', 'page', None, True)])
    check('the compound: two items, with its "see" prefix', items('(see Garcia & Lopez, 2021; Brown 2019)'),
          [('GARCI021', None, None, 'see', False), ('BROWN019', None, None, None, False)])
    check('the Jones citation uses the item its reference-list entry names', items('(Jones, 2020)'), [('JONES20A', None, None, None, False)])
    check('the ambiguous citation uses the item chosen', items('(Nilsson, 2015)'), [('NILSS15B', None, None, None, False)])
    check('the accepted suggestion is written', items('(Stone et al., 2017)'), [('STONE018', None, None, None, False)])
    check('narrative et al., with the group URI', by_text['(2014)'][0]['citationItems'][0]['uris'], ['http://zotero.org/groups/777/items/OHMAN014'])
    check('the leading-year compound: Lane suppressed, Bildtgård with cf.',
          items('(2014, 20; cf. Bildtgård 2010)'), [('LANE0014', '20', 'page', None, True), ('BILDT010', None, None, 'cf.', False)])
    check('a report number in a parenthesis, with its section', items('(SKB R-13-25, Section 4.2)'), [('OHMAN014', '4.2', 'section', None, False)])
    check('"SKB (R-19-01)": SKB stays text, the parenthesis is the field', items('(R-19-01)'), [('BROWN019', None, None, None, True)])
    check('"SKB R-19-01" in running text: only the number is the field', items('R-19-01'), [('BROWN019', None, None, None, True)])
    check('the item data is CSL-JSON with the numeric id', by_text['(Jones, 2020)'][0]['citationItems'][0]['itemData']['id'], 11)
    check('the field text and plainCitation agree', all(f['json']['properties']['plainCitation'] == f['text'] for f in live if f['json']['citationID'] != 'old1'), True)
    check('the unmatched citation is still plain text', '(Zzyzx, 1999)' in by_text, False)
    check('so is the half-resolved parenthesis', '(Smith, 2020; Zzyzx, 1999)' in by_text, False)

    # The EndNote field is deleted whole and replaced.
    dels = [e for e in ours if local(e) == 'del']
    check('the EndNote field is deleted as a tracked change, instruction and all',
          any('ADDIN EN.CITE' in ''.join(t.firstChild.data for t in e.getElementsByTagNameNS(W, 'delInstrText') if t.firstChild) for e in dels), True)
    check('its nested EN.CITE.DATA field goes with it',
          any('EN.CITE.DATA' in ''.join(t.firstChild.data for t in e.getElementsByTagNameNS(W, 'delInstrText') if t.firstChild) for e in dels), True)
    check('three fields show (Brown, 2019): the EndNote one, the one in Alice\'s insertion, the one by the comment',
          len(by_text.get('(Brown, 2019)', [])), 3)

    # Alice's insertion: the deletion sits inside it, and it is split around ours.
    p4 = ps_s[4]
    alice = [c for c in el_children(p4) if local(c) == 'ins' and c.getAttributeNS(W, 'author') == 'Alice']
    check('Alice\'s insertion is split in two around the new field', len(alice), 2)
    check('with the deletion of her citation inside the first half',
          any(local(c) == 'del' and c.getAttributeNS(W, 'author') == author for c in el_children(alice[0])), True)
    check('the second half has its own new id', alice[0].getAttributeNS(W, 'id') != alice[1].getAttributeNS(W, 'id'), True)
    kinds = [(local(c), c.getAttributeNS(W, 'author')) for c in el_children(p4) if local(c) in ('ins', 'del')]
    check('in the order her text, our field, her text', kinds, [('ins', 'Alice'), ('ins', author), ('ins', 'Alice')])

    # The hyperlink: split around the field, both halves pointing at the same target.
    p9 = ps_s[9]
    links = [c for c in el_children(p9) if local(c) == 'hyperlink']
    check('the hyperlink is split in two', len(links), 2)
    check('both halves keep the target',
          [l.getAttributeNS('http://schemas.openxmlformats.org/officeDocument/2006/relationships', 'id') for l in links], ['rId20', 'rId20'])
    check('the new field sits between them', [local(c) for c in el_children(p9)], ['r', 'hyperlink', 'ins', 'hyperlink', 'r'])
    inserted = [c for c in el_children(p9) if local(c) == 'ins'][0]
    check('and does not take the Hyperlink character style', len(inserted.getElementsByTagNameNS(W, 'rStyle')), 0)

    # The split runs keep their formatting.
    p1_runs = ps_s[1].getElementsByTagNameNS(W, 'r')
    texts = [(''.join(t.firstChild.data for t in r.getElementsByTagNameNS(W, 't') if t.firstChild)
              + ''.join(t.firstChild.data for t in r.getElementsByTagNameNS(W, 'delText') if t.firstChild),
              bool(r.getElementsByTagNameNS(W, 'b')), bool(r.getElementsByTagNameNS(W, 'i'))) for r in p1_runs]
    check('the runs of the split citation keep their own formatting',
          [x for x in texts if x[0]], [('Erosion is slow ', False, False), ('(Smi', False, False), ('th, ', True, False),
                                       ('2020)', False, True), ('(Smith, 2020)', False, False), (' in most holes.', False, True)])

    # The footnote.
    fn = minidom.parseString(zs.read('word/footnotes.xml'))
    check('the footnote citation is converted too', [f['text'] for f in zotero_fields(fn) if not f['deleted']], ['(Smith, 2020)'])
    check('the footnote mark is untouched', len(fn.getElementsByTagNameNS(W, 'footnoteRef')), 1)

    # Settings, people, relationships, content types.
    st = minidom.parseString(zs.read('word/settings.xml')).documentElement
    check('w:trackRevisions is inserted after proofState and before defaultTabStop',
          [local(c) for c in el_children(st)][:4], ['zoom', 'proofState', 'trackRevisions', 'defaultTabStop'])
    people = minidom.parseString(zs.read('word/people.xml'))
    check('people.xml lists the author', [p.getAttributeNS('http://schemas.microsoft.com/office/word/2012/wordml', 'author') for p in people.getElementsByTagNameNS('http://schemas.microsoft.com/office/word/2012/wordml', 'person')], [author])
    rels = zs.read('word/_rels/document.xml.rels').decode()
    check('it has a relationship', 'relationships/people" Target="people.xml"' in rels, True)
    check('and a content type', '<Override PartName="/word/people.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.people+xml"/>' in zs.read('[Content_Types].xml').decode(), True)
    check('the XML declaration is kept', zs.read('word/document.xml').startswith(b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'), True)
    check('the comment is kept', len(doc_s.getElementsByTagNameNS(W, 'commentReference')), 1)


if __name__ == '__main__':
    asyncio.run(main())
    print(f'\n{checks} checks, {len(failures)} failed')
    sys.exit(1 if failures else 0)
