"""Numbers typed into rdc.html: the initial inventory and the time horizon.

The Initial inventory dialog (a nuclide's menu, Initial inventory...) takes an
activity in Bq or an amount in mol, each field following the other, and the
chart takes a time horizon. All three were the browser's number fields, which
read a comma by the language the browser is in: in an English-speaking
browser "6,21E12" Bq was 6.21E14 Bq, "1,5" mol was 15 mol and "2,5e3" years
was 25 000 years, with nothing said, and letters could not be typed, so OK
took the empty field for no inventory at all. They are text fields now, read
by rdc.js's readNumber(): a comma or a point for the decimal mark, and an
exponent with e or E, whatever the browser's language.

Checked with real key presses, in the chain of Ca-41:
  - 6,21E12 Bq and 6.21E12 Bq are both 6.21E12 Bq, and the mol field follows;
  - 1,5 mol is 1.5 mol, and the Bq field follows;
  - text on its way to a number (6.21E) leaves the other field as it was;
  - text that is no number, and a negative number, are marked, OK keeps the
    dialog open over them and the inventory stays; a number typed after
    takes the mark off;
  - a time horizon of 2,5e3 years ends the chart at 2500 years, and one that
    is no number is refused and leaves the chart as it was;
  - and that the page raised nothing.

Serve the repository and start headless Chrome (the recipe is in README.md),
by default on ports 8765 and 9222; SITE_HTTP_PORT and SITE_CDP_PORT choose
others. Exit status is 0 when every check passes.
"""
import asyncio, json, os, sys, time, urllib.request
import websockets

HTTP = int(os.environ.get('SITE_HTTP_PORT', '8765'))
CDP = int(os.environ.get('SITE_CDP_PORT', '9222'))

ERRORS = """window.__errors = [];
addEventListener('error', e => window.__errors.push(String(e.message)));
addEventListener('unhandledrejection', e => window.__errors.push('rejected: ' + e.reason));"""

READY = """typeof CY !== 'undefined' && typeof selectExactTreeNode === 'function'
  && typeof DB !== 'undefined' && !dbLoading && typeof readNumber === 'function'"""

# The dialog for Ca-41, opened as its menu opens it. The dialog's close event
# comes after close() returns, and it forgets the nuclide: let it pass first.
OPEN = """(async () => {
  const d = document.getElementById('icdialog');
  if (d.open) d.close();
  await new Promise(r => setTimeout(r, 150));
  updateIC(CY.getElementById('Ca-41'));
  return d.open;
})()"""

DIALOG = """JSON.stringify((() => {
  const bq = document.getElementById('ic-bq'), mol = document.getElementById('ic-mole');
  return { bq: bq.value, mol: mol.value, open: document.getElementById('icdialog').open,
           marked: [bq.getAttribute('aria-invalid'), mol.getAttribute('aria-invalid')],
           message: bq.validationMessage || mol.validationMessage,
           ic: CY.getElementById('Ca-41').data('IC'), perBq: molesPerBq(getRn('Ca-41')) };
})())"""

OK = """(async () => {
  document.getElementById('ic-ok').click();
  await new Promise(r => setTimeout(r, 400));
  return true;
})()"""

CHART = """JSON.stringify((() => {
  const t = CHARTDIALOG[0].data && CHARTDIALOG[0].data.find(d => d.name === 'Ca-41');
  const status = document.getElementById('rdc-status');
  return { end: t ? t.x[t.x.length - 1] : null, unit: document.getElementById('timeunit').value,
           field: document.getElementById('timeinput').value,
           message: document.getElementById('timeinput').validationMessage,
           error: status.hidden ? '' : status.textContent };
})())"""


def close(a, b, rel=1e-12):
    return a is not None and b is not None and abs(float(a) - b) <= rel * abs(b)


async def main():
    version = json.load(urllib.request.urlopen('http://127.0.0.1:%d/json/version' % CDP))
    async with websockets.connect(version['webSocketDebuggerUrl'], max_size=100 * 1024 * 1024) as bws:
        counter = [0]

        async def cmd(method, params=None, session=None):
            counter[0] += 1
            mid = counter[0]
            message = {'id': mid, 'method': method, 'params': params or {}}
            if session:
                message['sessionId'] = session
            await bws.send(json.dumps(message))
            while True:
                reply = json.loads(await bws.recv())
                if reply.get('id') == mid:
                    return reply

        async def ev(expression, session):
            reply = await cmd('Runtime.evaluate',
                              {'expression': expression, 'awaitPromise': True,
                               'returnByValue': True, 'timeout': 30000}, session)
            result = reply.get('result', {})
            if 'exceptionDetails' in result:
                raise AssertionError('page threw: ' + json.dumps(result['exceptionDetails'])[:300])
            return result.get('result', {}).get('value')

        async def keys(session, text):
            # A key at a time, each carrying its character, as from a keyboard.
            for ch in text:
                code, vk = {'.': ('Period', 190), ',': ('Comma', 188), '-': ('Minus', 189)}.get(ch) \
                    or (('Digit' if ch.isdigit() else 'Key') + ch.upper(), ord(ch.upper()))
                await cmd('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': ch, 'code': code,
                                                     'windowsVirtualKeyCode': vk, 'text': ch}, session)
                await cmd('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': ch, 'code': code,
                                                     'windowsVirtualKeyCode': vk}, session)

        async def type_into(session, field, text):
            # What the field holds is selected, so the keys replace it.
            await ev('(() => { const i = document.getElementById(%s); i.focus(); i.select(); return true; })()'
                     % json.dumps(field), session)
            await keys(session, text)

        async def tab(session):
            for kind in ('keyDown', 'keyUp'):
                await cmd('Input.dispatchKeyEvent', {'type': kind, 'key': 'Tab', 'code': 'Tab',
                                                     'windowsVirtualKeyCode': 9}, session)

        async def dialog(session):
            return json.loads(await ev(DIALOG, session))

        failures = []
        passed = [0]

        def check(condition, message):
            if condition:
                passed[0] += 1
            else:
                failures.append(message)

        target = (await cmd('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
        session = (await cmd('Target.attachToTarget',
                             {'targetId': target, 'flatten': True}))['result']['sessionId']
        try:
            await cmd('Runtime.enable', {}, session)
            await cmd('Page.enable', {}, session)
            await cmd('Network.enable', {}, session)
            await cmd('Network.setCacheDisabled', {'cacheDisabled': True}, session)
            await cmd('Page.addScriptToEvaluateOnNewDocument', {'source': ERRORS}, session)
            await cmd('Emulation.setDeviceMetricsOverride',
                      {'width': 1400, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False}, session)
            await cmd('Page.navigate',
                      {'url': 'http://127.0.0.1:%d/rdc.html?n=%d' % (HTTP, int(time.time() * 1000))},
                      session)
            ready = False
            for _ in range(120):
                ready = await ev(READY, session) is True
                if ready:
                    break
                await asyncio.sleep(0.25)
            check(ready, 'the page should load with its chain chart and readNumber()')
            nodes = await ev("""(async () => { selectExactTreeNode('Ca-41', {userInitiated: true});
                await new Promise(r => setTimeout(r, 800)); return CY.nodes().map(n => n.id()); })()""", session)
            check(nodes == ['Ca-41', 'K-41'], 'the chain of Ca-41 should be Ca-41 and K-41, got %r' % (nodes,))
            fields = await ev("[...document.querySelectorAll('#ic-bq, #ic-mole, #timeinput')].map(i => i.type)", session)
            check(fields == ['text', 'text', 'text'], 'the three fields should be text fields, got %r' % (fields,))

            # ── An activity, with a decimal comma and with a point ───────────
            for text in ('6,21E12', '6.21E12'):
                await ev(OPEN, session)
                await type_into(session, 'ic-bq', text)
                shown = await dialog(session)
                await ev(OK, session)
                after = await dialog(session)
                check(shown['bq'] == text and close(shown['mol'], 6.21e12 * shown['perBq']),
                      '%s Bq typed: the mol field should follow with 6.21E12 Bq in mol, got %r' % (text, shown))
                check(after['ic'] == 6.21e12 and not after['open'],
                      '%s Bq and OK: the inventory should be 6.21E12 Bq and the dialog closed, got %r'
                      % (text, after))

            # ── An amount in mol ─────────────────────────────────────────────
            await ev(OPEN, session)
            await type_into(session, 'ic-mole', '1,5')
            shown = await dialog(session)
            await ev(OK, session)
            after = await dialog(session)
            check(shown['mol'] == '1,5' and close(shown['bq'], 1.5 / shown['perBq']),
                  '1,5 mol typed: the Bq field should follow with 1.5 mol in Bq, got %r' % (shown,))
            check(close(after['ic'], 1.5 / after['perBq']) and not after['open'],
                  '1,5 mol and OK: the inventory should be 1.5 mol in Bq, got %r' % (after,))

            # ── Text on its way to a number ──────────────────────────────────
            await ev(OPEN, session)
            await type_into(session, 'ic-bq', '6.21')
            before = await dialog(session)
            await keys(session, 'E')
            during = await dialog(session)
            await keys(session, '12')
            done = await dialog(session)
            check(during['bq'] == '6.21E' and during['mol'] == before['mol'] and during['marked'] == [None, None],
                  '6.21E on its way to 6.21E12 should leave the mol field as it was, unmarked, got %r then %r'
                  % (before, during))
            check(close(done['mol'], 6.21e12 * done['perBq']),
                  '... and 6.21E12 should then set it, got %r' % (done,))
            await ev(OK, session)

            # ── No number, and a negative one ────────────────────────────────
            for text in ('abc', '-5'):
                await ev(OPEN, session)
                await type_into(session, 'ic-bq', text)
                await ev(OK, session)
                refused = await dialog(session)
                check(refused['open'] and refused['marked'][0] == 'true' and 'such as 6.21E12' in refused['message']
                      and refused['ic'] == 6.21e12,
                      '%r and OK: the dialog should stay open with the field marked and the inventory as it was, '
                      'got %r' % (text, refused))
            await type_into(session, 'ic-bq', '5')
            fixed = await dialog(session)
            check(fixed['marked'] == [None, None] and fixed['message'] == '',
                  'a number typed after should take the mark off, got %r' % (fixed,))
            await ev(OK, session)
            after = await dialog(session)
            check(after['ic'] == 5 and not after['open'], '... and OK then take it, got %r' % (after,))

            # ── The time horizon ─────────────────────────────────────────────
            await ev("document.getElementById('timeunit').value = 'year'; true", session)
            await type_into(session, 'timeinput', '2,5e3')
            await tab(session)
            await asyncio.sleep(0.6)
            horizon = json.loads(await ev(CHART, session))
            check(horizon['end'] is not None and close(horizon['end'], 2500, 1e-9) and horizon['error'] == '',
                  'a time horizon of 2,5e3 years should end the chart at 2500 years, got %r' % (horizon,))
            await type_into(session, 'timeinput', 'abc')
            await tab(session)
            await asyncio.sleep(0.6)
            refused = json.loads(await ev(CHART, session))
            check(refused['error'] != '' and refused['message'] != '' and close(refused['end'], 2500, 1e-9),
                  'a time horizon that is no number should be refused and leave the chart, got %r' % (refused,))

            errors = await ev('window.__errors', session)
            check(errors == [], 'the page should raise nothing, got %r' % (errors,))
        finally:
            await cmd('Target.closeTarget', {'targetId': target})

        if failures:
            print('%d of %d check(s) failed:' % (len(failures), len(failures) + passed[0]))
            for failure in failures:
                print('  - ' + failure)
            sys.exit(1)
        print('%d checks passed: the inventory and the time horizon read 6,21E12 and 6.21E12 alike, '
              'and a field that holds no number is refused.' % passed[0])


asyncio.run(main())
