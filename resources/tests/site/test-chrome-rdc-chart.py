"""Who decides whether rdc.html's chart window is up.

It used to follow the inventory with no way to say otherwise: it appeared the
moment any nuclide had an initial inventory and vanished when the last one was
cleared. There was no toggle and the title bar's close button was hidden, so a
chart in the way could only be got rid of by emptying the model.

It still follows the inventory until somebody says something, so adding a first
becquerel shows what it does. From the first use of the toggle or the × that
choice holds, and the two states it has to survive are the ones the old code
could not express:

  - dismissed, then the inventory changes. The window must stay down;
  - asked for, then the inventory is cleared to nothing. The window must stay
    up, and say why it is empty rather than showing bare axes.

Closing it because there is nothing to show is not the user saying anything, so
that path must not be recorded as their choice — otherwise the first automatic
close would freeze the window down for the rest of the session.

The window also has to be draggable to a different width, which it was not for
three reasons at once. jQuery UI hangs its resize handles off the outside of
the frame and the frame is clipped, leaving a 2px sliver no pointer could
find. The narrowest it was allowed to be was the width it opened at, so even a
caught handle could not narrow it. And jQuery's .trigger() walks a simulated
bubble path that ends at window, so the "resize" jQuery UI fires on the dialog
for every frame of a drag arrived at a $(window).on('resize') handler as though
the screen had changed — that handler set an option, jQuery UI answered by
re-applying options.width, and options.width is the old width until the drag
stops. Every frame was undone as it was drawn. The test drags the real handles
and reads the width back.

The settings row is checked along with it, because a window that can be
narrowed is only useful if what is in it follows: its columns answer to the
window's own width through container queries, the viewport queries they
replaced never having matched a 510px window on a 1400px screen.

Two more things are checked because they are invisible until someone is holding
a phone: that the window fills the screen there rather than floating in a
374px box, and that the quantity menu no longer takes focus the moment the
window opens.

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

ADD_ONE_BQ = """(() => { const n = CY.nodes().filter(x => x.data().type === 1)[0];
    n.data('IC', 1); updateLevel('IC'); runAndUpdateChart(); })()"""
CLEAR_ALL = """(() => { CY.nodes().forEach(n => n.data('IC', 0));
    updateLevel('IC'); runAndUpdateChart(); })()"""
# Tolerates the pieces being absent so a page without them is reported rather
# than raising on the first read: half of what this test guards did not exist
# before, and "no toggle" is a better failure than a ReferenceError.
STATE = """(() => {
    const toggle = document.getElementById('chartToggle');
    return JSON.stringify({
        open: !!$('#chartdialog').dialog('isOpen'),
        choice: typeof chartChoice === 'undefined' ? 'not on the page' : String(chartChoice),
        pressed: toggle ? toggle.getAttribute('aria-pressed') : 'no toggle on the page',
        traces: (CHARTDIALOG[0].data || []).length,
        notes: ((CHARTDIALOG[0].layout || {}).annotations || []).length,
        buttons: CHARTDIALOG[0].querySelectorAll('.modebar-btn').length
    }); })()"""


class Missing(Exception):
    """A control this test is about is not on the page at all."""


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

        async def state(session):
            return json.loads(await ev(STATE, session))

        async def press(selector, session, touch, settle=1.5):
            """Press the real control, and say what was under the finger.

            A control that has been covered still reports its own box; only the
            hit test says whether the press could reach it."""
            box = await ev("""(() => { const el = document.querySelector(%s);
                if (!el) return null; const r = el.getBoundingClientRect();
                const x = Math.round(r.left + r.width / 2), y = Math.round(r.top + r.height / 2);
                const u = document.elementFromPoint(x, y);
                return JSON.stringify({ x: x, y: y,
                                        under: u ? (u.id || u.className || u.tagName) : 'nothing' }); })()"""
                           % json.dumps(selector), session)
            if not box:
                raise Missing('there is no %s on the page to press' % selector)
            box = json.loads(box)
            if touch:
                point = [{'x': box['x'], 'y': box['y'], 'radiusX': 14, 'radiusY': 14, 'force': 1}]
                await cmd('Input.dispatchTouchEvent',
                          {'type': 'touchStart', 'touchPoints': point}, session)
                await asyncio.sleep(0.07)
                await cmd('Input.dispatchTouchEvent',
                          {'type': 'touchEnd', 'touchPoints': []}, session)
            else:
                for kind in ('mousePressed', 'mouseReleased'):
                    await cmd('Input.dispatchMouseEvent',
                              {'type': kind, 'x': box['x'], 'y': box['y'],
                               'button': 'left', 'clickCount': 1}, session)
            await asyncio.sleep(settle)
            return box['under']

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
                      {'enabled': bool(metrics['mobile']), 'maxTouchPoints': 5}, session)
            await cmd('Page.navigate',
                      {'url': 'http://127.0.0.1:8765/rdc.html?n=%d' % int(time.time() * 1000)},
                      session)
            await asyncio.sleep(7)
            return target, session

        failures = []

        def check(condition, message):
            if not condition:
                failures.append(message)

        # ── The window follows the inventory until somebody says otherwise ───
        target, session = await open_page(DESKTOP)

        try:
          boot = await state(session)
          check(boot['open'] is False, 'nothing has an inventory at boot, so there is nothing to chart')
          check(boot['choice'] == 'null', 'nobody has said anything at boot, got %r' % (boot['choice'],))

          await ev(ADD_ONE_BQ, session)
          await asyncio.sleep(1.2)
          opened = await state(session)
          check(opened['open'] is True, 'a first becquerel should still show the chart')
          check(opened['choice'] == 'null',
                'opening by itself is not the user choosing, got %r' % (opened['choice'],))
          check(opened['pressed'] == 'true', 'the toggle should report the window it can see')
          check(opened['traces'] > 1, 'the chain should be on the chart, got %d traces' % (opened['traces'],))

          await ev(CLEAR_ALL, session)
          await asyncio.sleep(1.2)
          emptied = await state(session)
          check(emptied['open'] is False, 'with nothing to chart and nothing said, it goes away again')
          check(emptied['choice'] == 'null',
                'closing by itself is not the user choosing either, got %r' % (emptied['choice'],))

          # ── Dismissing it, and the inventory changing afterwards ─────────────
          await ev(ADD_ONE_BQ, session)
          await asyncio.sleep(1.2)
          under = await press('.ui-dialog-titlebar-close', session, touch=False)
          closed = await state(session)
          check('close' in under.lower(),
                'the × should be the thing under the pointer, found %r' % (under,))
          check(closed['open'] is False, 'the × should close the window, got %r' % (closed['open'],))
          check(closed['choice'] == 'false',
                'the × is the user saying no, got %r' % (closed['choice'],))

          await ev(CLEAR_ALL, session)
          await ev(ADD_ONE_BQ, session)
          await asyncio.sleep(1.2)
          churned = await state(session)
          check(churned['open'] is False,
                'a dismissed window must stay down through an inventory change, got %r'
                % (churned['open'],))

          # ── Asking for it, and the inventory going to nothing ────────────────
          under = await press('#chartToggle', session, touch=False)
          asked = await state(session)
          check(asked['open'] is True,
                'the toggle should bring it back, got %r (pressed on %r)' % (asked['open'], under))
          check(asked['choice'] == 'true', 'the toggle is the user saying yes, got %r' % (asked['choice'],))
          check(asked['traces'] > 1,
                'a window brought back has to be redrawn, got %d traces' % (asked['traces'],))

          await ev(CLEAR_ALL, session)
          await asyncio.sleep(1.3)
          kept = await state(session)
          check(kept['open'] is True,
                'a window asked for must stay up with nothing in it, got %r' % (kept['open'],))
          check(kept['traces'] == 0, 'and must not keep the old chain, got %d traces' % (kept['traces'],))
          check(kept['notes'] == 1,
                'bare axes do not say why they are bare, got %d notes' % (kept['notes'],))
          check(kept['buttons'] == 0,
                'zoom and download over an empty panel are controls for nothing, got %d'
                % (kept['buttons'],))

          await ev(ADD_ONE_BQ, session)
          await asyncio.sleep(1.3)
          refilled = await state(session)
          check(refilled['traces'] > 1, 'the chain should come back, got %d traces' % (refilled['traces'],))
          check(refilled['notes'] == 0, 'and the placeholder should not, got %d notes' % (refilled['notes'],))
          check(refilled['buttons'] == 10,
                'react() applies a config, so the whole modebar comes back with the data, got %d'
                % (refilled['buttons'],))

          focus = await ev("""(() => { const a = document.activeElement;
              return a ? (a.id || a.tagName) + ' ' + (a.className || '') : 'none'; })()""", session)
          check('ui-dialog' in focus,
                'the window takes focus, not the quantity menu inside it, got %r' % (focus,))

          # ── It can be dragged wider and narrower ────────────────────────────
          async def drag_handle(edge, dx):
              """Take hold of one resize handle by its middle and pull."""
              spot = await ev("""(() => {
                  const h = document.querySelector('.ui-dialog .ui-resizable-%s');
                  if (!h) return null; const r = h.getBoundingClientRect();
                  const x = Math.round(r.left + r.width / 2), y = Math.round(r.top + r.height / 2);
                  const u = document.elementFromPoint(x, y);
                  return JSON.stringify({ x: x, y: y, wide: Math.round(r.width),
                      under: u ? (u.className || u.tagName).toString().slice(0, 30) : 'nothing' }); })()"""
                             % edge, session)
              if not spot:
                  raise Missing('there is no %s resize handle on the window' % edge)
              spot = json.loads(spot)
              await cmd('Input.dispatchMouseEvent',
                        {'type': 'mouseMoved', 'x': spot['x'], 'y': spot['y'], 'buttons': 0}, session)
              await cmd('Input.dispatchMouseEvent',
                        {'type': 'mousePressed', 'x': spot['x'], 'y': spot['y'],
                         'button': 'left', 'buttons': 1, 'clickCount': 1}, session)
              for step in range(1, 13):
                  await cmd('Input.dispatchMouseEvent',
                            {'type': 'mouseMoved', 'button': 'left', 'buttons': 1,
                             'x': spot['x'] + dx * step // 12, 'y': spot['y']}, session)
                  await asyncio.sleep(0.02)
              await cmd('Input.dispatchMouseEvent',
                        {'type': 'mouseReleased', 'x': spot['x'] + dx, 'y': spot['y'],
                         'button': 'left', 'buttons': 0}, session)
              await asyncio.sleep(0.8)
              return spot

          async def frame():
              return json.loads(await ev("""(() => {
                  const d = document.querySelector('.ui-dialog').getBoundingClientRect();
                  const settings = document.querySelector('#chartdialog .settings');
                  const plot = document.querySelector('#chartdialog .main-svg');
                  return JSON.stringify({
                      width: Math.round(d.width),
                      columns: getComputedStyle(settings).gridTemplateColumns.split(' ').length,
                      badge: getComputedStyle(document.querySelector('.chart-badge')).display,
                      plot: plot ? Math.round(plot.getBoundingClientRect().width) : 0,
                      spills: settings.scrollWidth > Math.ceil(settings.getBoundingClientRect().width),
                      minWidth: $('#chartdialog').dialog('option', 'minWidth')
                  }); })()""", session))

          start = await frame()
          check(start['minWidth'] < start['width'],
                'the narrowest it may be dragged cannot be the width it opens at, both were %d'
                % (start['width'],))

          spot = await drag_handle('e', -160)
          narrowed = await frame()
          check(spot['wide'] >= 7,
                'the handle is clipped to %dpx by the frame and cannot be grabbed' % (spot['wide'],))
          check('resizable' in spot['under'],
                'the east handle should be the thing under the pointer, found %r' % (spot['under'],))
          check(narrowed['width'] < start['width'] - 100,
                'dragging the east handle in by 160 should narrow the window, %d stayed %d'
                % (start['width'], narrowed['width']))
          check(narrowed['plot'] > 0 and abs(narrowed['plot'] - narrowed['width']) < 12,
                'the plot has to follow the window, %d inside %d'
                % (narrowed['plot'], narrowed['width']))

          await drag_handle('e', -400)
          floored = await frame()
          check(floored['width'] == start['minWidth'],
                'it should stop at its minimum of %d, got %d'
                % (start['minWidth'], floored['width']))
          check(floored['columns'] == 1,
                'the settings answer to the window, not the screen: at %dpx they should be in '
                'one column, got %d' % (floored['width'], floored['columns']))
          check(floored['spills'] is False,
                'and must not spill out of it at %dpx' % (floored['width'],))

          await drag_handle('w', -420)
          widened = await frame()
          check(widened['width'] > floored['width'] + 300,
                'the west handle should widen it, %d became %d' % (floored['width'], widened['width']))
          check(widened['columns'] == 3 and widened['badge'] != 'none',
                'with the room for three columns it should use them and show the badge, got %d '
                'columns and badge %r' % (widened['columns'], widened['badge']))
          check(widened['spills'] is False, 'and still not spill')

          await cmd('Target.closeTarget', {'targetId': target})

          # ── On a phone it is a screen, not a window ──────────────────────────
          target, session = await open_page(PHONE)
          await ev("setTreeCollapsed(true, false);", session)
          await asyncio.sleep(0.5)
          under = await press('#chartToggle', session, touch=True, settle=2.0)
          phone = await state(session)
          check(phone['open'] is True,
                'the toggle should reach the thumb once the list is away, got %r (tapped %r)'
                % (phone['open'], under))
          geometry = json.loads(await ev("""(() => {
              const r = document.querySelector('.ui-dialog').getBoundingClientRect();
              return JSON.stringify({ left: Math.round(r.left), top: Math.round(r.top),
                                      width: Math.round(r.width), height: Math.round(r.height),
                                      screen: [innerWidth, innerHeight],
                                      draggable: !!$('#chartdialog').dialog('option', 'draggable'),
                                      scrolls: document.documentElement.scrollWidth > innerWidth }); })()""",
                                         session))
          check([geometry['left'], geometry['top']] == [0, 0],
                'a screen starts at the corner of the screen, got %r'
                % ([geometry['left'], geometry['top']],))
          check([geometry['width'], geometry['height']] == geometry['screen'],
                'and is the size of it: %r against %r'
                % ([geometry['width'], geometry['height']], geometry['screen']))
          check(geometry['draggable'] is False,
                'dragging a window that covers the screen can only take it off the screen')
          check(geometry['scrolls'] is False, 'and it must not make the page scroll sideways')

          under = await press('.ui-dialog-titlebar-close', session, touch=True)
          check('close' in under.lower(),
                'the menu button is fixed above everything in the same corner as the ×; '
                'it has to be out of the way, found %r under the tap' % (under,))
          after = await state(session)
          check(after['open'] is False, 'the × should close it on a phone too, got %r' % (after['open'],))
          await cmd('Target.closeTarget', {'targetId': target})

        except Missing as absent:
            failures.append(str(absent))

        total = 36
        if failures:
            print('%d failure(s):' % len(failures))
            for failure in failures:
                print('  - ' + failure)
            sys.exit(1)
        print('%d checks passed: the chart follows the inventory until you say otherwise, '
              'can be dragged to any width, and fills the screen on a phone.' % total)


asyncio.run(main())
