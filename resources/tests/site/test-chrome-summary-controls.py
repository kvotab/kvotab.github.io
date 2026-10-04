"""No control inside a <summary>, on any page.

Chrome reports every control inside a <summary> -- a button, a link, a field,
a label, anything with a tabindex or contenteditable -- in the console as "An
interactive element was found within a <summary> element. These elements won't
consistently be accessible to people navigating by keyboard or using assistive
technology." The pages had put an (i), a Copy button, a Ta bort or a pair of
arrows there (2026-10-04). Those now sit in a bar beside the summary, drawn
over a room the summary keeps for them: kvot-info.js for a section's (i),
kvot-summary-tools.js for other buttons, and Kompartment's own parts.js.

Every page at the repository root is loaded, and the states that make such
headings later are reached: two more forms in inkomstdeklaration.html, a
report with Python code in smui.html (whose engine takes a while to load), a
block chosen in Kompartment (inside kompartment.html's frame) and a second
distribution in logn.html. Each is checked twice: by Chrome's rule over the
page and its frames, and by the issues Chrome raised itself
(Audits.issueAdded, InteractiveContentSummaryDescendant).

Serve the repository and start headless Chrome (README.md), by default on
ports 8765 and 9222; SITE_HTTP_PORT and SITE_CDP_PORT choose others. Exit
status is 0 when every check passes.
"""
import asyncio
import glob
import json
import os
import sys
import urllib.request

import websockets

HTTP = int(os.environ.get('SITE_HTTP_PORT', '8765'))
CDP = int(os.environ.get('SITE_CDP_PORT', '9222'))
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))

# Chrome's rule (html_summary_element.cc): the summaries that hold a control,
# in the page and in its same-origin frames, or ''.
CONTROLS_IN_SUMMARIES = r"""(() => {
  const sel = 'a[href], audio[controls], button, details, embed, iframe, img[usemap], input:not([type=hidden]),'
    + ' label, object[usemap], select, textarea, video[controls], [tabindex], [contenteditable]';
  const docs = [document, ...[...document.querySelectorAll('iframe')].map((f) => { try { return f.contentDocument; } catch (e) { return null; } }).filter(Boolean)];
  return docs.flatMap((d) => [...d.querySelectorAll('summary')].filter((s) => s.querySelector(sel))
    .map((s) => s.textContent.trim().replace(/\s+/g, ' ').slice(0, 40))).join(' | ');
})()"""

# What each page needs doing before its headings are all there.
FRAME = "document.getElementById('komp-frame').contentDocument"
STEPS = {
    'inkomstdeklaration.html': [
        # an extra form and a second INK2: both carry Ta bort
        "(() => { for (const n of ['N3B', 'INK2']) { const s = document.getElementById('sru-lagg-till'); s.value = n;"
        " s.dispatchEvent(new Event('change', { bubbles: true })); } return document.querySelectorAll('.sru-ta-bort').length; })()",
    ],
    'smui.html?example=students': [
        "(async () => { for (let i = 0; i < 600 && !(window.SM && SM.engine && ['ready', 'error'].includes(SM.engine.state)); i++)"
        " await new Promise((r) => setTimeout(r, 500));"
        " const t = SM.app.current; const rep = SM.app.openReport(SM.platforms.get('distribution'),"
        " { roles: { y: [t.col('height (cm)').id] }, options: {} }, t);"
        " await new Promise((r) => rep.on('done', r)); return rep.codeBlocks().length; })()",
    ],
    'kompartment.html': [
        "(async () => { for (let i = 0; i < 240 && !(%s && %s.getElementById('example') && %s.getElementById('example').options.length > 3); i++)"
        " await new Promise((r) => setTimeout(r, 250));"
        " const d = %s, s = d.getElementById('example'); s.value = 'biosphere.json'; s.dispatchEvent(new Event('change', { bubbles: true }));"
        " for (let i = 0; i < 240 && d.querySelectorAll('.trow-block').length < 5; i++) await new Promise((r) => setTimeout(r, 250));"
        " d.querySelectorAll('.trow-block')[3].click(); await new Promise((r) => setTimeout(r, 800));"
        " return d.querySelectorAll('.info-act').length; })()" % (FRAME, FRAME, FRAME, FRAME),
    ],
    'logn.html': [
        "(async () => { document.getElementById('dist-add').click(); await new Promise((r) => setTimeout(r, 800));"
        " return !document.getElementById('computed-for').hidden; })()",
    ],
}

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


async def main():
    pages = sorted(os.path.basename(p) for p in glob.glob(os.path.join(REPO, '*.html')))
    pages = [f'{p}?example=students' if p == 'smui.html' else p for p in pages]
    ver = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=256 * 1024 * 1024) as ws:
        counter, pending, events = [0], {}, []

        async def reader():
            async for raw in ws:
                r = json.loads(raw)
                if 'id' in r and r['id'] in pending:
                    pending.pop(r['id']).set_result(r)
                elif 'method' in r:
                    events.append(r)

        task = asyncio.create_task(reader())

        async def send(method, params=None, session=None, timeout=600):
            counter[0] += 1
            fut = asyncio.get_event_loop().create_future()
            pending[counter[0]] = fut
            msg = {'id': counter[0], 'method': method, 'params': params or {}}
            if session:
                msg['sessionId'] = session
            await ws.send(json.dumps(msg))
            return await asyncio.wait_for(fut, timeout)

        for page in pages:
            tid = (await send('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
            sid = (await send('Target.attachToTarget', {'targetId': tid, 'flatten': True}))['result']['sessionId']
            try:
                for m in ('Runtime.enable', 'Audits.enable', 'Network.enable'):
                    await send(m, session=sid)
                await send('Network.setCacheDisabled', {'cacheDisabled': True}, session=sid)
                await send('Emulation.setDeviceMetricsOverride',
                           {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=sid)
                await send('Page.navigate', {'url': f'http://127.0.0.1:{HTTP}/{page}'}, session=sid)
                await asyncio.sleep(6)
                for step in STEPS.get(page, []):
                    r = await send('Runtime.evaluate', {'expression': step, 'returnByValue': True, 'awaitPromise': True},
                                   session=sid, timeout=900)
                    res = r['result']
                    got = 'threw: ' + str(res.get('exceptionDetails', {}).get('exception', {}).get('description', ''))[:200] \
                        if 'exceptionDetails' in res else res['result'].get('value')
                    check(f'{page}: its headings are made', bool(got) and not str(got).startswith('threw'), True)
                    await asyncio.sleep(1)
                r = await send('Runtime.evaluate', {'expression': CONTROLS_IN_SUMMARIES, 'returnByValue': True}, session=sid)
                check(f'{page}: no control inside a <summary>', r['result']['result'].get('value'), '')
                issues = sum(1 for e in events if e.get('sessionId') == sid and e['method'] == 'Audits.issueAdded'
                             and e['params']['issue'].get('details', {}).get('elementAccessibilityIssueDetails', {})
                             .get('elementAccessibilityIssueReason') == 'InteractiveContentSummaryDescendant')
                check(f'{page}: and Chrome reported none', issues, 0)
            finally:
                await send('Target.closeTarget', {'targetId': tid})
        task.cancel()

    print(f'\n{checks - len(failures)}/{checks} passed')
    if failures:
        print('FAILED: ' + '; '.join(failures))
        sys.exit(1)


asyncio.run(main())
