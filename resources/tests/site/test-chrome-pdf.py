"""Analyse the same report as .docx and as .pdf and require the same answer.

resources/tests/pdf/build-fixture-pair.py writes one document in both formats.
The .docx states its own structure, so the checker's report on it is by
construction the right answer for that text; the .pdf carries the same words
with the structure thrown away. Any difference between the two reports is a
defect in the PDF reconstruction.

Also asserted: the PDF run must not fire a rule whose evidence a PDF does not
carry, and must not invent a rule the .docx run did not fire.

Needs a static server on 127.0.0.1:8765 and Chrome on 127.0.0.1:9222.
"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

FIXTURES = ['resources/tests/pdf/fixture-report.docx',
            'resources/tests/pdf/fixture-report.pdf']

# handleFile and the report state are top-level bindings of a classic script,
# so Runtime.evaluate reaches them by name.
PROBE = r"""(async (path) => {
  const response = await fetch('/' + path + '?nocache=' + Date.now());
  if (!response.ok) return JSON.stringify({ error: 'fetch ' + path + ' -> ' + response.status });
  const name = path.split('/').pop();
  const file = new File([await response.blob()], name);

  currentReport = null;
  await handleFile(file);
  for (let waited = 0; waited < 200 && !currentReport; waited++) {
    await new Promise(r => setTimeout(r, 100));
  }
  if (!currentReport) return JSON.stringify({ error: 'no report produced for ' + name });

  const ruleIds = counts => {
    const out = {};
    for (const issue of counts) out[issue.ruleId || issue.description] = (out[issue.ruleId || issue.description] || 0) + 1;
    return out;
  };
  const notice = document.getElementById('format-notice');

  return JSON.stringify({
    name,
    references: currentRefEntries.map(entry => entry.key),
    citations: [...new Set(currentReport.matchedCites
      ? currentReport.matchedCites.map(c => c.key)
      : [])],
    citedKeys: currentRefEntries.filter(entry => entry.cites.length).map(entry => entry.key),
    orphans: currentReport.orphanCites.map(citation => citation.key).sort(),
    uncited: currentReport.uncitedRefs.map(entry => entry.key).sort(),
    duplicates: currentReport.duplicateKeys.map(group => group.map(e => e.key)),
    official: ruleIds(currentRuleFindings.official),
    citationRules: ruleIds(currentRuleFindings.citation),
    reviewRules: ruleIds(currentRuleFindings.review),
    refTextHtml: [...document.querySelectorAll('td.ref-text')].map(cell => cell.innerHTML),
    noticeShown: notice ? notice.classList.contains('show') : null,
    docInfo: (document.getElementById('doc-info').textContent || '').slice(0, 200)
  });
})(PATH_PLACEHOLDER)"""

# The fixture bolds part of one reference with direct formatting and the whole
# opening of another with a Word character style. Both have to survive into the
# reference text on the page, and neither the body's own bold run nor any other
# entry may pick it up.
BOLD_EXPECTED = {
    'Andersson': 'Groundwater flow modelling in fractured rock',
    'Nilsson': 'Nilsson G, 1998.',
}

# Rules whose evidence a PDF does not carry; none may fire on the PDF run.
UNAVAILABLE_ON_PDF = 'non-breaking-space'

# The reference list is the one table whose cells have no upper bound: a key
# can be a seven-name author list. With the default automatic table layout the
# widest key set the column width, so one long key took 700 of 980 pixels,
# squeezed the reference text into a word-wide ribbon and pushed the Zotero
# column off the right edge. The probe measures the table, then puts an
# oversized key in and measures again — a table that grows has the defect back.
LAYOUT_PROBE = r"""(async () => {
  const response = await fetch('/resources/tests/pdf/fixture-report.pdf?n=' + Date.now());
  currentReport = null;
  await handleFile(new File([await response.blob()], 'fixture-report.pdf'));
  for (let i = 0; i < 200 && !currentReport; i++) await new Promise(r => setTimeout(r, 100));
  const table = document.querySelector('.ref-list-table');
  if (!table) return JSON.stringify({ error: 'no .ref-list-table found' });
  const app = document.getElementById('app');
  const inner = app.clientWidth
    - parseFloat(getComputedStyle(app).paddingLeft) - parseFloat(getComputedStyle(app).paddingRight);
  const width = () => Math.round(table.getBoundingClientRect().width);
  const before = width();

  const cell = table.querySelector('tbody .ref-key');
  const saved = cell.textContent;
  cell.textContent = 'Mårtensson P, Luterkort D, Nyblad B, Wimelius H, Pettersson A, Aghili B, Andolfsson T';
  const withLongKey = width();
  const grewTaller = table.getBoundingClientRect().height > 0;
  cell.textContent = saved;

  return JSON.stringify({
    tableWidth: before, appInnerWidth: Math.round(inner),
    widthWithLongKey: withLongKey,
    tableLayout: getComputedStyle(table).tableLayout,
    keyWhiteSpace: getComputedStyle(cell).whiteSpace,
    columnWidths: [...table.querySelectorAll('thead th')].map(th => Math.round(th.getBoundingClientRect().width)),
    bodyScrollWidth: document.body.scrollWidth,
    layoutWidth: document.documentElement.clientWidth,
    wrapped: grewTaller
  });
})()"""

# A scanned PDF has no text layer. Analysing it would report a document with no
# references and no citations, which reads as a clean bill of health rather than
# as a file that cannot be checked.
SCAN_PROBE = r"""(async () => {
  const response = await fetch('/resources/tests/pdf/fixture-scan-no-text.pdf?n=' + Date.now());
  await handleFile(new File([await response.blob()], 'fixture-scan-no-text.pdf'));
  await new Promise(r => setTimeout(r, 700));
  return JSON.stringify({
    results: (document.getElementById('results').textContent || '').slice(0, 200),
    noticeShown: document.getElementById('format-notice').classList.contains('show'),
    resetOffered: document.getElementById('reset-btn').classList.contains('show')
  });
})()"""

# Italic and superscript are read from the embedded font and from the baseline
# offset, through pdfFontResolver and real pdf.js font objects. The Node
# geometry tests feed those flags in ready-made, so this is the only place the
# resolver itself is exercised.
FORMAT_PROBE = r"""(async () => {
  const pdfjs = await loadPdfJs();
  const response = await fetch('/resources/tests/pdf/fixture-report.pdf?n=' + Date.now());
  const pdf = await pdfjs.getDocument({
    data: new Uint8Array(await response.arrayBuffer()), isEvalSupported: false }).promise;
  const pages = [];
  for (let number = 1; number <= pdf.numPages; number++) {
    const page = await pdf.getPage(number);
    await loadPdfPageFonts(page);
    const item = SkbPdf.itemsFromPdfJs(
      await page.getTextContent(), page.getViewport({ scale: 1 }), pdfFontResolver(page, { resolved: 0, missing: 0 }));
    item.pageNumber = number;
    pages.push(item);
  }
  const { paragraphs } = SkbPdf.reconstructDocument(pages);
  const isotope = paragraphs.find(p => p.text.startsWith('Measurements of'));
  if (!isotope) return JSON.stringify({ error: 'the formatted paragraph was not found' });
  const italicAt = isotope.text.indexOf('Desulfovibrio');
  const supAt = isotope.text.indexOf('14');
  return JSON.stringify({
    text: isotope.text.slice(0, 90),
    italicRun: isotope.formatSpans.some(s => s.italic && s.start >= italicAt && s.end <= italicAt + 26),
    italicElsewhere: isotope.formatSpans.filter(s => s.italic && s.end <= italicAt).length,
    superscript: isotope.formatSpans.some(s => s.sup && s.start === supAt),
    headings: paragraphs.filter(p => p.style).map(p => `${p.style}: ${p.text.slice(0, 30)}`)
  });
})()"""


async def evaluate(bws, session, expression, call_id):
    await bws.send(json.dumps({'id': call_id, 'method': 'Runtime.evaluate',
                               'sessionId': session,
                               'params': {'expression': expression,
                                          'awaitPromise': True,
                                          'returnByValue': True,
                                          'timeout': 120000}}))
    while True:
        message = json.loads(await bws.recv())
        if message.get('id') == call_id:
            result = message.get('result', {})
            if 'exceptionDetails' in result:
                return json.dumps({'error': str(result['exceptionDetails'])[:400]})
            return result.get('result', {}).get('value') or json.dumps(message)[:400]


async def main():
    version = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    stamp = int(time.time() * 1000)
    async with websockets.connect(version['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        # The target opens blank so the cache can be turned off before anything
        # is fetched. Navigating first and disabling the cache afterwards leaves
        # the page's own scripts served from cache, which once had this test
        # reporting a stale resources/js/skb-pdf.js as a code defect.
        await bws.send(json.dumps({'id': 1, 'method': 'Target.createTarget',
                                   'params': {'url': 'about:blank'}}))
        target = None
        while target is None:
            message = json.loads(await bws.recv())
            if message.get('id') == 1:
                target = message['result']['targetId']
        await bws.send(json.dumps({'id': 2, 'method': 'Target.attachToTarget',
                                   'params': {'targetId': target, 'flatten': True}}))
        session = None
        while session is None:
            message = json.loads(await bws.recv())
            if message.get('id') == 2:
                session = message['result']['sessionId']
        await bws.send(json.dumps({'id': 3, 'method': 'Network.enable', 'sessionId': session}))
        await bws.send(json.dumps({'id': 4, 'method': 'Network.setCacheDisabled',
                                   'sessionId': session, 'params': {'cacheDisabled': True}}))
        await bws.send(json.dumps({'id': 5, 'method': 'Page.enable', 'sessionId': session}))
        await bws.send(json.dumps({'id': 6, 'method': 'Page.navigate', 'sessionId': session,
                                   'params': {'url': 'http://127.0.0.1:8765/skbref.html?nocache=%d' % stamp}}))
        await asyncio.sleep(5)

        # A stale script would make every assertion below meaningless, so the
        # build under test is identified before anything is measured.
        loaded = await evaluate(bws, session,
                                "JSON.stringify(Object.keys(SkbPdf))", 50)
        if 'fontStyleFromFont' not in loaded:
            print('the page loaded an out-of-date resources/js/skb-pdf.js: %s' % loaded)
            sys.exit(1)

        reports = {}
        for index, path in enumerate(FIXTURES):
            expression = PROBE.replace('PATH_PLACEHOLDER', json.dumps(path))
            raw = await evaluate(bws, session, expression, 100 + index)
            try:
                reports[path.rsplit('.', 1)[1]] = json.loads(raw)
            except Exception:
                print('HARNESS ERROR for %s: %s' % (path, raw[:400]))
                sys.exit(1)
        formatting = json.loads(await evaluate(bws, session, FORMAT_PROBE, 200))
        layout = json.loads(await evaluate(bws, session, LAYOUT_PROBE, 202))
        scan = json.loads(await evaluate(bws, session, SCAN_PROBE, 201))
        await bws.send(json.dumps({'id': 9, 'method': 'Target.closeTarget',
                                   'params': {'targetId': target}}))

    failures = []
    docx, pdf = reports.get('docx', {}), reports.get('pdf', {})
    for label, report in (('docx', docx), ('pdf', pdf)):
        if report.get('error'):
            failures.append('%s: %s' % (label, report['error']))
    if failures:
        for failure in failures:
            print('  - ' + failure)
        sys.exit(1)

    print('%-24s %s' % ('', 'docx / pdf'))
    for field in ('references', 'citedKeys', 'orphans', 'uncited'):
        print('%-24s %d / %d' % (field, len(docx.get(field) or []), len(pdf.get(field) or [])))
    print('%-24s %d / %d' % ('official findings',
                             sum((docx.get('official') or {}).values()),
                             sum((pdf.get('official') or {}).values())))
    print('%-24s %s / %s' % ('format notice shown', docx.get('noticeShown'), pdf.get('noticeShown')))
    print()
    for rule in sorted(set(docx.get('official') or {}) | set(pdf.get('official') or {})):
        print('  %-6s %-6s %s' % ((docx.get('official') or {}).get(rule, '-'),
                                  (pdf.get('official') or {}).get(rule, '-'), rule))
    print()

    def compare(field, sort=False):
        left = docx.get(field) or []
        right = pdf.get(field) or []
        if sort:
            left, right = sorted(left), sorted(right)
        if left != right:
            failures.append('%s differs\n      docx: %s\n      pdf:  %s' % (field, left, right))

    compare('references', sort=True)
    compare('citedKeys', sort=True)
    compare('orphans')
    compare('uncited')
    if (docx.get('duplicates') or []) != (pdf.get('duplicates') or []):
        failures.append('duplicate detection differs: %s vs %s'
                        % (docx.get('duplicates'), pdf.get('duplicates')))

    # A rule whose evidence a PDF does not carry must be off, not guessing. The
    # fixture writes an ordinary space where the guides require a hard one, so
    # the .docx run has to report it and the PDF run has to stay silent — with
    # neither half of that, the assertion would pass while proving nothing.
    def hard_space(report):
        return sorted(rule for rule in (report.get('official') or {}) if UNAVAILABLE_ON_PDF in rule)

    if not hard_space(docx):
        failures.append('the fixture no longer trips any hard-space rule, so the '
                        'PDF suppression is not being tested')
    if hard_space(pdf):
        failures.append('hard-space rules fired on the PDF: %s' % hard_space(pdf))

    # And the PDF path must not invent findings the .docx path does not have.
    for family in ('official', 'citationRules', 'reviewRules'):
        extra = sorted(set(pdf.get(family) or {}) - set(docx.get(family) or {}))
        if extra:
            failures.append('%s rules fired only on the PDF: %s' % (family, extra))

    # Formatting read back through real pdf.js font objects.
    if formatting.get('error'):
        failures.append('formatting probe: %s' % formatting['error'])
    else:
        print('formatted paragraph: %s' % formatting['text'])
        print('headings inferred: %s' % ', '.join(formatting.get('headings') or []))
        if not formatting.get('italicRun'):
            failures.append('the italic species name was not recovered from the embedded font')
        if formatting.get('italicElsewhere'):
            failures.append('%d span(s) before the italic run were marked italic'
                            % formatting['italicElsewhere'])
        if not formatting.get('superscript'):
            failures.append('the superscript 14 in "14C" was not recovered from the baseline offset')
        print()

    # Bold in the reference text, in both formats.
    for label, report in (('docx', docx), ('pdf', pdf)):
        cells = report.get('refTextHtml') or []
        if len(cells) != len(report.get('references') or []):
            failures.append('%s: %d reference cells for %d entries'
                            % (label, len(cells), len(report.get('references') or [])))
        bolded = 0
        for cell in cells:
            wanted = next((text for key, text in BOLD_EXPECTED.items() if key in cell), None)
            if wanted:
                bolded += 1
                if '<strong>%s</strong>' % wanted not in cell:
                    failures.append('%s: bold not kept in the reference text.\n      wanted <strong>%s</strong>\n      got   %s'
                                    % (label, wanted, cell[:220]))
            elif '<strong>' in cell:
                failures.append('%s: an entry with no bold source was rendered bold: %s'
                                % (label, cell[:180]))
        if bolded != len(BOLD_EXPECTED):
            failures.append('%s: found %d of %d bolded entries'
                            % (label, bolded, len(BOLD_EXPECTED)))
    print('bold runs kept in reference text: docx %d, pdf %d'
          % (sum('<strong>' in c for c in (docx.get('refTextHtml') or [])),
             sum('<strong>' in c for c in (pdf.get('refTextHtml') or []))))
    print()

    # The reference table must stay inside its container, whatever a key holds.
    if layout.get('error'):
        failures.append('layout probe: %s' % layout['error'])
    else:
        print('reference table %dpx in a %dpx container, columns %s'
              % (layout['tableWidth'], layout['appInnerWidth'], layout['columnWidths']))
        if layout['tableWidth'] > layout['appInnerWidth'] + 1:
            failures.append('the reference table (%dpx) is wider than its container (%dpx)'
                            % (layout['tableWidth'], layout['appInnerWidth']))
        if layout['widthWithLongKey'] > layout['tableWidth'] + 1:
            failures.append('an 85-character key widened the table from %dpx to %dpx: '
                            'the key column is sizing to its content again'
                            % (layout['tableWidth'], layout['widthWithLongKey']))
        if layout['tableLayout'] != 'fixed':
            failures.append('the reference table lost table-layout: fixed (got %r)'
                            % layout['tableLayout'])
        if layout['keyWhiteSpace'] == 'nowrap':
            failures.append('the key cell is back to white-space: nowrap, so it cannot wrap')
        if layout['bodyScrollWidth'] > layout['layoutWidth'] + 1:
            failures.append('the page scrolls horizontally (%dpx > %dpx)'
                            % (layout['bodyScrollWidth'], layout['layoutWidth']))
        print()

    # A scan must be refused, not reported clean.
    print('scan refused with: %s' % (scan.get('results') or '')[:110])
    if 'no text layer' not in (scan.get('results') or ''):
        failures.append('a PDF with no text layer was not refused: %r'
                        % (scan.get('results') or '')[:160])
    if scan.get('noticeShown'):
        failures.append('the format notice was shown for a PDF that could not be read')
    if not scan.get('resetOffered'):
        failures.append('no way back was offered after refusing the scan')
    print()

    if pdf.get('noticeShown') is not True:
        failures.append('the PDF run did not show the format notice')
    if docx.get('noticeShown') is not False:
        failures.append('the .docx run showed the PDF format notice')

    if failures:
        print('%d failure(s):' % len(failures))
        for failure in failures:
            print('  - ' + failure)
        sys.exit(1)
    print('PDF and .docx reports agree on %d references and %d cited entries.'
          % (len(docx.get('references') or []), len(docx.get('citedKeys') or [])))


asyncio.run(main())
