"""Kompartment's transfer grid, arranged by hand: a tile on the diagonal
dragged along it to another place among its neighbours.

A block's tile on the Matrix tab's diagonal, or a sub-system's, can be dragged
along the diagonal. Its row and its column go together, a sub-system takes
everything framed in it along, and it can only go among the blocks and
sub-systems of its own sub-system. Where it goes is saved with the model, in
the layout beside its place on the diagram, and changes no number: a step to
undo, and no run. Alt with an arrow key does the same a place at a time, the
right-click on a tile has Move up and Move down, and the right-click on the
margin puts the model's own order back. See kompartment/src/ui/matrix.js
(`wireArrange`) and `moveOnMatrix` in kompartment/src/domain/edit.js.

Checked with real presses, drags and keys:
  - a press on a tile that does not move selects it and moves nothing;
  - a drag of a block up the diagonal shows a line along a row boundary and
    one down a column boundary, crossing on the diagonal, the tile faint and
    its name following the pointer; let go, the block is in its new place,
    selected, with its row and column (a transfer's tile stays between the same
    two blocks), and nothing of the drag is left on the page;
  - Undo puts the order back;
  - a folded sub-system dragged to the top goes there whole, selected, and is
    not unfolded by the release;
  - Escape during a drag puts the tile back;
  - Alt+Down and Alt+Up move the focused tile a place, and the focus stays on it;
  - a tile's right-click has Move up and Move down, the first of them off on the
    first tile, and Move down moves it;
  - inside an unfolded sub-system a block moves among its own neighbours, and a
    drag towards the top of the grid leaves it first among them, inside;
  - the places are in the model's JSON, under its layout;
  - the margin's right-click puts the model's own order back;
  - on a grid larger than its panel, a drag held near the panel's bottom edge
    scrolls the grid;
  - and that the page raised nothing.

Serve the repository and start headless Chrome (the recipe is in README.md),
by default on ports 8765 and 9222; SITE_HTTP_PORT and SITE_CDP_PORT choose
others. Exit status is 0 when every check passes.
"""
import asyncio, json, os, sys, urllib.request
import websockets

HTTP = int(os.environ.get('SITE_HTTP_PORT', '8765'))
CDP = int(os.environ.get('SITE_CDP_PORT', '9222'))
PAGE = 'http://127.0.0.1:%d/kompartment/index.html?model=four-compartment.json' % HTTP

ERRORS = """window.__errors = [];
addEventListener('error', e => window.__errors.push(String(e.message)));
addEventListener('unhandledrejection', e => window.__errors.push('rejected: ' + e.reason));"""

SIM = {'start_time': 0, 'end_time': 10, 'rtol': 1e-6, 'abstol': 1e-9}
MODEL = {
    'name': 'arrange', 'simulation': SIM, 'systems': ['NF'],
    'compartments': [
        {'name': 'A', 'initial': 1}, {'name': 'B', 'initial': 0}, {'name': 'C', 'initial': 0},
        {'name': 'W', 'system': 'NF', 'initial': 0}, {'name': 'V', 'system': 'NF', 'initial': 0},
    ],
    'transfers': [
        {'name': 'AB', 'from': 'A', 'to': 'B', 'rate': '0.1*A'},
        {'name': 'BC', 'from': 'B', 'to': 'C', 'rate': '0.1*B'},
        {'name': 'CW', 'from': 'C', 'to': 'NF.W', 'rate': '0.1*C'},
    ],
}
BIG = {
    'name': 'big', 'simulation': SIM,
    'compartments': [{'name': 'K%02d' % i, 'initial': 0} for i in range(30)],
    'transfers': [{'name': 'T%02d' % i, 'from': 'K%02d' % i, 'to': 'K%02d' % (i + 1), 'rate': '0.1'}
                  for i in range(29)],
}

# The diagonal, in order: each tile's name, `~` for the world outside.
ORDER = """[...document.querySelectorAll('#panel-matrix table.matrix th.matrix-self')]
  .map((th) => th.querySelector('[data-name]')?.dataset.name ?? '~')"""
TILE = "[...document.querySelectorAll('#panel-matrix .matrix-self > button')].find((b) => b.dataset.name === %s)"
# A menu item by its label, in the panel opened last.
ITEM = "[...document.querySelectorAll('.menu-layer .menu-panel:last-child .menu-item')].find((b) => b.textContent.replace('\\u2713', '').trim().startsWith(%s))"
SELECTED = "[...document.querySelectorAll('#panel-matrix .matrix-self > button.is-selected')].map((b) => b.dataset.name)"
# What the drag is showing on the page.
SHOWN = """JSON.stringify({
  lines: [...document.querySelectorAll('.matrix-drop:not(.is-point)')].filter((n) => !n.hidden).map((n) => {
    const r = n.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; }),
  point: [...document.querySelectorAll('.matrix-drop.is-point')].filter((n) => !n.hidden).map((n) => {
    const r = n.getBoundingClientRect(); return [Math.round(r.x + r.width / 2), Math.round(r.y + r.height / 2)]; }),
  ghost: document.querySelector('.matrix-ghost')?.textContent ?? null,
  faint: [...document.querySelectorAll('#panel-matrix .is-dragged')].map((b) => b.dataset.name),
  arranging: document.querySelector('#panel-matrix').classList.contains('is-arranging'),
})"""


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

        async def ev(expression):
            reply = await cmd('Runtime.evaluate',
                              {'expression': expression, 'awaitPromise': True,
                               'returnByValue': True, 'timeout': 30000}, session)
            result = reply.get('result', {})
            if 'exceptionDetails' in result:
                raise AssertionError('page threw: ' + json.dumps(result['exceptionDetails'])[:300])
            return result.get('result', {}).get('value')

        async def mouse(kind, x, y, buttons=0, clicks=1, button='left'):
            # A move with a button held says which, as a real mouse's does:
            # sent as `none`, Chrome takes it for a hover and the pointer
            # capture a drag asked for is never given.
            await cmd('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y,
                      'button': button if kind != 'mouseMoved' or buttons else 'none',
                      'buttons': buttons, 'clickCount': clicks}, session)

        async def centre(expression, dy=0.5):
            # In sight first: an off-screen press hits nothing.
            return await ev("""(() => { const e = %s; if (!e) return null;
              e.scrollIntoView({ block: 'nearest', inline: 'nearest' });
              const b = e.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height * %s]; })()""" % (expression, dy))

        # Something that is not there is pressed nowhere, and the checks after
        # say what did not happen: against code without the arrangement, every
        # check still runs.
        async def click(expression):
            xy = await centre(expression)
            if not xy:
                return False
            await mouse('mouseMoved', *xy)
            await mouse('mousePressed', *xy, 1)
            await mouse('mouseReleased', *xy, 0)
            await asyncio.sleep(0.3)
            return True

        async def right_click(xy):
            if not xy:
                return
            await mouse('mouseMoved', *xy)
            await mouse('mousePressed', *xy, 2, 1, 'right')
            await mouse('mouseReleased', *xy, 0, 1, 'right')
            await asyncio.sleep(0.3)

        async def drag(start, end, steps=14, during=None, release=True):
            """Presses at `start`, moves to `end` a step at a time with the
            button held, a frame or two apart so the page's own frames run,
            looks at the page there when asked, and lets go."""
            if not start or not end:
                return await during() if during else None
            await mouse('mouseMoved', *start)
            await mouse('mousePressed', *start, 1)
            for i in range(1, steps + 1):
                x = start[0] + (end[0] - start[0]) * i / steps
                y = start[1] + (end[1] - start[1]) * i / steps
                await mouse('mouseMoved', x, y, 1)
                await asyncio.sleep(0.03)
            await asyncio.sleep(0.1)
            seen = await during() if during else None
            if release:
                await mouse('mouseReleased', *end, 0)
                await asyncio.sleep(0.35)
            return seen

        KEYS = {'ArrowUp': 38, 'ArrowDown': 40, 'Escape': 27}

        async def key(name, modifiers=0):
            base = {'key': name, 'code': name, 'windowsVirtualKeyCode': KEYS[name],
                    'nativeVirtualKeyCode': KEYS[name], 'modifiers': modifiers}
            await cmd('Input.dispatchKeyEvent', dict(base, type='rawKeyDown'), session)
            await cmd('Input.dispatchKeyEvent', dict(base, type='keyUp'), session)
            await asyncio.sleep(0.25)

        async def load_model(model):
            # Through the JSON tab, as a model would be pasted there: Apply
            # is on once the text has been checked.
            await ev("document.querySelector('.tab[data-tab=\"model\"]').click()")
            await asyncio.sleep(0.3)
            await ev("""(() => { const t = document.querySelector('#json');
              t.value = %s; t.dispatchEvent(new Event('input', { bubbles: true })); })()""" % json.dumps(json.dumps(model)))
            for _ in range(50):
                await asyncio.sleep(0.1)
                if await ev("!document.querySelector('#apply').disabled"):
                    break
            else:
                raise AssertionError('Apply stayed off: %s' % await ev("document.querySelector('#json-check').textContent"))
            await ev("document.querySelector('#apply').click()")
            await asyncio.sleep(0.5)
            await ev("document.querySelector('.tab[data-tab=\"matrix\"]').click()")
            for _ in range(60):
                await asyncio.sleep(0.1)
                if await ev("document.querySelectorAll('#panel-matrix .matrix-self').length") >= len(
                        [c for c in model['compartments'] if 'system' not in c]):
                    break
            await asyncio.sleep(0.3)

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
        await cmd('Network.enable', {}, session)
        await cmd('Network.setCacheDisabled', {'cacheDisabled': True}, session)
        await cmd('Page.addScriptToEvaluateOnNewDocument', {'source': ERRORS}, session)
        await cmd('Emulation.setDeviceMetricsOverride',
                  {'width': 1400, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False}, session)
        await cmd('Page.navigate', {'url': PAGE}, session)
        for _ in range(100):
            await asyncio.sleep(0.15)
            try:
                if await ev("!!document.querySelector('#json') && document.querySelectorAll('.graph-nodes .gnode').length > 1"):
                    break
            except AssertionError:
                pass
        await ev("localStorage.removeItem('kompartment.matrixZoom')")
        await load_model(MODEL)

        order = await ev(ORDER)
        if order != ['A', 'B', 'C', 'NF', '~'][:len(order)] or len(order) < 4:
            print('FAIL the grid did not come up as A B C NF: %s' % order)
            return 1

        # --- a press that does not move is a click --------------------------
        await click(TILE % json.dumps('B'))
        check(await ev(ORDER) == order and await ev(SELECTED) == ['B'],
              'a click on B: order %s, selected %s' % (await ev(ORDER), await ev(SELECTED)))

        # --- a drag up the diagonal ------------------------------------------
        start = await centre(TILE % json.dumps('C'))
        end = await centre(TILE % json.dumps('A'), 0.25)
        a = await ev("(() => { const r = (%s).getBoundingClientRect(); return [r.x, r.y]; })()" % (TILE % json.dumps('A')))
        seen = json.loads(await drag(start, end, during=lambda: ev(SHOWN)))
        lines = seen['lines']
        crossing = len(lines) == 2 and any(h == 2 for (_, _, _, h) in lines) and any(w == 2 for (_, _, w, _) in lines)
        check(crossing and seen['ghost'] == 'C' and seen['faint'] == ['C'] and seen['arranging'],
              'during the drag: %s' % seen)
        # The cross, and the dot on it, are at the top-left corner of A's
        # square, where C goes.
        if crossing:
            row = [l for l in lines if l[3] == 2][0]
            col = [l for l in lines if l[2] == 2][0]
            dot = seen['point'][0] if len(seen['point']) == 1 else [-99, -99]
            check(abs(row[1] + 1 - (a[1] - 2)) <= 3 and abs(col[0] + 1 - (a[0] - 2)) <= 3
                  and abs(dot[0] - (a[0] - 2)) <= 3 and abs(dot[1] - (a[1] - 2)) <= 3,
                  'the cross is at %s,%s and its dot at %s; A starts at %s' % (col[0], row[1], seen['point'], a))
        after = await ev(ORDER)
        check(after[:4] == ['C', 'A', 'B', 'NF'] and await ev(SELECTED) == ['C'],
              'dropped on A: order %s, selected %s' % (after, await ev(SELECTED)))
        # A transfer stays between its two blocks: BC is in B's row and C's column.
        cell = await ev("""(() => { const td = [...document.querySelectorAll('#panel-matrix td[data-names]')]
          .find((t) => t.dataset.names.split('\\u0000').includes('BC')); if (!td) return null;
          const rows = document.querySelectorAll('#panel-matrix table.matrix tr');
          const name = (i) => rows[i].cells[i].querySelector('[data-name]')?.dataset.name;
          return [name(td.parentElement.rowIndex), name(td.cellIndex)]; })()""")
        check(cell == ['B', 'C'], 'BC is in the row and column of %s' % cell)
        left = await ev("document.querySelectorAll('.matrix-drop, .matrix-ghost, #panel-matrix .is-dragged').length")
        check(left == 0 and not await ev("document.querySelector('#panel-matrix').classList.contains('is-arranging')"),
              '%d pieces of the drag are left on the page' % left)

        # --- undo -------------------------------------------------------------
        await ev("document.querySelector('#undo').click()")
        await asyncio.sleep(0.4)
        check((await ev(ORDER))[:4] == ['A', 'B', 'C', 'NF'], 'after Undo: %s' % await ev(ORDER))

        # --- a folded sub-system to the top, whole and still folded -----------
        start = await centre(TILE % json.dumps('NF'))
        end = await centre(TILE % json.dumps('A'), 0.2)
        await drag(start, end)
        folded = await ev("!document.querySelector('#panel-matrix .matrix-system.is-open')")
        check((await ev(ORDER))[:4] == ['NF', 'A', 'B', 'C'] and folded and await ev(SELECTED) == ['NF'],
              'NF dragged to the top: %s, folded %s, selected %s' % (await ev(ORDER), folded, await ev(SELECTED)))

        # --- Escape puts it back ----------------------------------------------
        before = await ev(ORDER)
        start = await centre(TILE % json.dumps('A'))
        end = await centre(TILE % json.dumps('C'), 0.8)
        await drag(start, end, release=False)
        mid = json.loads(await ev(SHOWN))
        await key('Escape')
        gone = json.loads(await ev(SHOWN))
        if end:
            await mouse('mouseReleased', *end, 0)
        await asyncio.sleep(0.35)
        check(mid['ghost'] == 'A' and gone['ghost'] is None and not gone['lines'] and not gone['point'] and not gone['faint']
              and await ev(ORDER) == before and await ev(SELECTED) == ['NF'],
              'Escape: during %s, after %s, order %s, selected %s' % (mid, gone, await ev(ORDER), await ev(SELECTED)))

        # --- the keyboard ------------------------------------------------------
        await ev("(%s)?.focus()" % (TILE % json.dumps('A')))
        await key('ArrowDown', 1)
        down = [await ev(ORDER), await ev("document.activeElement?.dataset?.name ?? null")]
        await key('ArrowUp', 1)
        await key('ArrowUp', 1)
        up = [await ev(ORDER), await ev("document.activeElement?.dataset?.name ?? null")]
        check(down[0][:4] == ['NF', 'B', 'A', 'C'] and down[1] == 'A' and up[0][:4] == ['A', 'NF', 'B', 'C'] and up[1] == 'A',
              'Alt+Down then Alt+Up twice: %s, then %s' % (down, up))

        # --- the right-click on a tile -----------------------------------------
        await right_click(await centre(TILE % json.dumps('A')))
        first = json.loads(await ev("""JSON.stringify([...document.querySelectorAll('.menu-layer .menu-item')].slice(0, 2)
          .map((b) => [b.textContent.trim(), b.disabled]))"""))
        if not await click(ITEM % json.dumps('Move down')):
            await key('Escape')
        check(len(first) == 2 and first[0][0].startswith('Move up') and first[0][1] is True
              and first[1][0].startswith('Move down') and first[1][1] is False
              and (await ev(ORDER))[:4] == ['NF', 'A', 'B', 'C'],
              'the menu starts %s; after Move down: %s' % (first, await ev(ORDER)))

        # --- inside an unfolded sub-system --------------------------------------
        await click(TILE % json.dumps('NF'))
        inside = await ev(ORDER)
        start = await centre(TILE % json.dumps('NF.V'))
        end = await centre(TILE % json.dumps('NF.W'), 0.3)
        await drag(start, end)
        swapped = await ev(ORDER)
        # Towards the very top of the grid: it stays inside, first among its own.
        start = await centre(TILE % json.dumps('NF.W'))
        end = await centre(TILE % json.dumps('NF'), 0.1)
        await drag(start, end and [end[0] - 60, end[1] - 60])
        stayed = await ev(ORDER)
        check(inside[:4] == ['NF', 'NF.W', 'NF.V', 'A'] and swapped[:4] == ['NF', 'NF.V', 'NF.W', 'A']
              and stayed[:4] == ['NF', 'NF.W', 'NF.V', 'A'],
              'inside NF: %s, V up %s, W to the top %s' % (inside, swapped, stayed))

        # --- saved with the model ------------------------------------------------
        await ev("document.querySelector('.tab[data-tab=\"model\"]').click()")
        await asyncio.sleep(0.4)
        saved = json.loads(await ev("document.querySelector('#json').value"))
        places = {k: v.get('matrix') for k, v in (saved.get('layout') or {}).items() if isinstance(v, dict) and 'matrix' in v}
        check(places.get('NF') == 0 and places.get('A') == 1 and places.get('NF.W') == 0 and places.get('NF.V') == 1,
              'the places in the JSON: %s' % places)
        await ev("document.querySelector('.tab[data-tab=\"matrix\"]').click()")
        await asyncio.sleep(0.4)

        # --- the margin puts the model's own order back ---------------------------
        margin = await ev("""(() => { const t = document.querySelector('#panel-matrix table.matrix').getBoundingClientRect();
          const p = document.querySelector('#panel-matrix').getBoundingClientRect();
          return [Math.min(t.right + 60, p.right - 30), t.top + 40]; })()""")
        await right_click(margin)
        item = await ev("(() => { const b = %s; return b ? [b.textContent.trim(), b.disabled] : null; })()"
                        % (ITEM % json.dumps('Back to the model')))
        if item and not item[1]:
            await click(ITEM % json.dumps('Back to the model'))
        restored = await ev(ORDER)
        check(item and not item[1] and restored[:6] == ['A', 'B', 'C', 'NF', 'NF.W', 'NF.V'],
              'the margin offered %s; the order after it: %s' % (item, restored))

        # --- a grid larger than its panel scrolls under a drag ---------------------
        await load_model(BIG)
        await ev("document.querySelector('#panel-matrix').scrollTop = 0")
        start = await centre(TILE % json.dumps('K01'))
        bottom = await ev("""(() => { const p = document.querySelector('#panel-matrix');
          const r = p.getBoundingClientRect(); return r.top + p.clientTop + p.clientHeight - 8; })()""")
        held = start and [start[0] + 40, bottom]
        await drag(start, held, release=False)
        top0 = await ev("document.querySelector('#panel-matrix').scrollTop")
        await asyncio.sleep(0.6)
        top1 = await ev("document.querySelector('#panel-matrix').scrollTop")
        await key('Escape')
        if held:
            await mouse('mouseReleased', *held, 0)
        await asyncio.sleep(0.3)
        check(top1 > top0 and (await ev(ORDER))[:3] == ['K00', 'K01', 'K02'],
              'held at the bottom edge the grid scrolled from %s to %s; order %s' % (top0, top1, (await ev(ORDER))[:3]))

        errors = await ev('window.__errors')
        check(not errors, 'the page raised: %s' % errors)

        await cmd('Target.closeTarget', {'targetId': target})
        total = passed[0] + len(failures)
        for f in failures:
            print('FAIL', f)
        print('%d/%d checks passed' % (passed[0], total))
        return 1 if failures else 0


sys.exit(asyncio.run(main()))
