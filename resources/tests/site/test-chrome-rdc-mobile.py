"""On a phone the element list covers the graph, so choosing a nuclide puts it away.

Which selections count as "choosing" is the whole of it, and jstree reports all
of them through one event:

  - the page picks U-238 for itself once the list has loaded. Putting the list
    away for that would mean it is never seen;

  - re-sorting the list rebuilds it and jstree restores the selection
    afterwards. Nothing was chosen, so the list must stay;

  - a tap, a key press, and a name typed into the search field are all a person
    asking to see a chain, and the list has to get out of the way.

What separates them is the DOM event jstree passes on: it has one for a tap or
a key press and none for a selection it restored by itself. The search field
selects on the person's behalf and says so.

The earlier test — has anybody touched the page yet — passed the first two and
failed the third, because the touch that re-sorted the list also answered it.

Needs a static server on 127.0.0.1:8765 and Chrome on 127.0.0.1:9222.
"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

PHONE = {'width': 390, 'height': 844, 'deviceScaleFactor': 2, 'mobile': True}
DESKTOP = {'width': 1400, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False}


async def main():
    version = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
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

        async def tap(x, y, session, settle=1.2):
            point = [{'x': x, 'y': y, 'radiusX': 14, 'radiusY': 14, 'force': 1}]
            await cmd('Input.dispatchTouchEvent',
                      {'type': 'touchStart', 'touchPoints': point}, session)
            await asyncio.sleep(0.07)
            await cmd('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []}, session)
            await asyncio.sleep(settle)

        async def tap_selector(selector, session, settle=1.2):
            """Tap where the control is, and say what was actually under the thumb.

            A control that has been covered or moved reports its old box
            happily, so the hit test is the part that means anything."""
            box = await ev("""(() => { const el = document.querySelector(%s);
                if (!el) return null; const r = el.getBoundingClientRect();
                return JSON.stringify({ x: Math.round(r.left + r.width / 2),
                                        y: Math.round(r.top + r.height / 2) }); })()"""
                           % json.dumps(selector), session)
            if not box:
                raise AssertionError('no %s on the page' % selector)
            box = json.loads(box)
            under = await ev("""(() => { const el = document.elementFromPoint(%d, %d);
                return el ? (el.id || el.className || el.tagName) : 'nothing'; })()"""
                            % (box['x'], box['y']), session)
            await tap(box['x'], box['y'], session, settle)
            return under

        async def state(session):
            return json.loads(await ev("""JSON.stringify({
                list: document.body.classList.contains('tree-collapsed') ? 'away' : 'open',
                order: document.getElementById('sortLabel').textContent,
                firstElement: (document.querySelector('#tree .jstree-anchor') || {}).textContent,
                selected: (($('#tree').jstree(true).get_selected(true)[0]) || {}).text || '',
                chartNodes: CY.nodes().length
            })""", session))

        async def open_page(metrics):
            target = (await cmd('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
            session = (await cmd('Target.attachToTarget',
                                 {'targetId': target, 'flatten': True}))['result']['sessionId']
            await cmd('Runtime.enable', {}, session)
            await cmd('Page.enable', {}, session)
            await cmd('Network.enable', {}, session)
            await cmd('Network.setCacheDisabled', {'cacheDisabled': True}, session)
            await cmd('Emulation.setDeviceMetricsOverride', metrics, session)
            await cmd('Emulation.setTouchEmulationEnabled',
                      {'enabled': metrics['mobile'], 'maxTouchPoints': 5}, session)
            await cmd('Page.navigate',
                      {'url': 'http://127.0.0.1:8765/rdc.html?n=%d' % int(time.time() * 1000)},
                      session)
            await asyncio.sleep(7)
            return target, session

        failures = []

        def check(condition, message):
            if not condition:
                failures.append(message)

        async def ensure_list_open(session):
            """Carry on after a failure instead of dying of its consequences.

            Every step after the first needs the list on screen, so a bug that
            hides it early would otherwise stop the run at the first symptom
            and leave the rest of the checks unreported."""
            if (await state(session))['list'] == 'open':
                return
            await tap_selector('#treeShow', session)

        # ── On a phone ───────────────────────────────────────────────────────
        target, session = await open_page(PHONE)

        boot = await state(session)
        check(boot['list'] == 'open',
              'the list should still be there after the page picks U-238 for itself, got %r'
              % (boot['list'],))
        check(boot['selected'] == 'U-238',
              'the page should start on U-238, got %r' % (boot['selected'],))

        # Re-sorting before anything has been chosen.
        under = await tap_selector('#sortToggle', session, 1.8)
        after_sort = await state(session)
        check(after_sort['list'] == 'open',
              're-sorting the list is not a request to leave it, got %r (tap landed on %r)'
              % (after_sort['list'], under))
        check(after_sort['order'] == 'A–Z',
              'the sort button should report the order it put the list in, got %r'
              % (after_sort['order'],))
        check(after_sort['firstElement'] != boot['firstElement'],
              'sorting should actually re-order the list, %r stayed first'
              % (after_sort['firstElement'],))
        check(after_sort['selected'] == boot['selected'],
              'sorting should keep the chosen nuclide, %r became %r'
              % (boot['selected'], after_sort['selected']))
        check(after_sort['chartNodes'] == boot['chartNodes'],
              'sorting should leave the chain on the graph alone, %d became %d'
              % (boot['chartNodes'], after_sort['chartNodes']))

        # Choosing a nuclide with a thumb.
        await ensure_list_open(session)
        await ev("""(() => { const row = [...document.querySelectorAll('#tree li.jstree-node')]
            .find(li => !li.classList.contains('jstree-leaf'));
            $('#tree').jstree(true).open_node(row.id); })()""", session)
        await asyncio.sleep(0.6)
        nuclide = json.loads(await ev("""(() => {
            /* A nuclide, not an element: its label reads like H-3. */
            const anchor = [...document.querySelectorAll('#tree .jstree-anchor')]
              .find(a => a.offsetParent !== null && /^[A-Z][a-z]?-\\d+m?$/.test(a.textContent.trim()));
            const r = anchor.getBoundingClientRect();
            return JSON.stringify({ name: anchor.textContent.trim(),
                                    x: Math.round(r.left + r.width / 2),
                                    y: Math.round(r.top + r.height / 2) }); })()""", session))
        await tap(nuclide['x'], nuclide['y'], session, 1.8)
        after_pick = await state(session)
        check(after_pick['list'] == 'away',
              'choosing a nuclide should uncover the graph, got %r' % (after_pick['list'],))
        check(after_pick['selected'] == nuclide['name'],
              'the tap should have chosen %r, got %r' % (nuclide['name'], after_pick['selected']))

        # And re-sorting once something has been chosen — the reported bug.
        under = await tap_selector('#treeShow', session)
        back = await state(session)
        check(back['list'] == 'open',
              'the list should come back, got %r (tap landed on %r)' % (back['list'], under))
        await ensure_list_open(session)
        under = await tap_selector('#sortToggle', session, 1.8)
        resorted = await state(session)
        check(resorted['list'] == 'open',
              're-sorting should not put the list away, got %r (tap landed on %r)'
              % (resorted['list'], under))
        check(resorted['selected'] == after_pick['selected'],
              're-sorting should keep %r chosen, got %r'
              % (after_pick['selected'], resorted['selected']))
        check(resorted['firstElement'] != back['firstElement'],
              'the second sort should re-order the list too, %r stayed first'
              % (resorted['firstElement'],))

        # A name typed into the search field is still a person choosing.
        await ev("""(() => { const input = document.getElementById('search-input');
            input.value = 'Cs-137';
            input.dispatchEvent(new Event('input', { bubbles: true })); })()""", session)
        await asyncio.sleep(1.8)
        searched = await state(session)
        check(searched['selected'] == 'Cs-137',
              'searching for Cs-137 should choose it, got %r' % (searched['selected'],))
        check(searched['list'] == 'away',
              'a name found by search should uncover the graph too, got %r' % (searched['list'],))

        phone = [boot, after_sort, after_pick, resorted, searched]
        await cmd('Target.closeTarget', {'targetId': target})

        # ── On a desktop, where the list sits beside the graph ───────────────
        target, session = await open_page(DESKTOP)
        await ev("""document.getElementById('sortToggle').click()""", session)
        await asyncio.sleep(1.2)
        wide_sorted = await state(session)
        check(wide_sorted['list'] == 'open', 'sorting should not touch a wide list')
        await ev("""(() => { const input = document.getElementById('search-input');
            input.value = 'Cs-137';
            input.dispatchEvent(new Event('input', { bubbles: true })); })()""", session)
        await asyncio.sleep(1.8)
        wide_searched = await state(session)
        check(wide_searched['selected'] == 'Cs-137',
              'search should work the same on a wide screen, got %r' % (wide_searched['selected'],))
        check(wide_searched['list'] == 'open',
              'nothing should put a wide list away — it is not covering anything, got %r'
              % (wide_searched['list'],))
        await cmd('Target.closeTarget', {'targetId': target})

        total = 17
        for label, snapshot in zip(['on load', 'sorted', 'picked', 're-sorted', 'searched'], phone):
            print('%-11s list %-5s order %-8s selected %-7s chain %d'
                  % (label, snapshot['list'], snapshot['order'],
                     snapshot['selected'], snapshot['chartNodes']))
        if failures:
            print('%d failure(s):' % len(failures))
            for failure in failures:
                print('  - ' + failure)
            sys.exit(1)
        print('%d checks passed: the list goes away when a nuclide is chosen, and only then.' % total)


asyncio.run(main())
