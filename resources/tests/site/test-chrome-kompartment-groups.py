"""Kompartment's groups: a way of sorting the blocks of one sub-system that
changes none of their names.

On the diagram an open group is an area with a dashed outline round what it
holds and its name in a band along the top; the band moves the group with
everything in it, and its button folds the group up into one node drawn like
a sub-system's, which lines into what it hides end on. A block dragged out of
a group's area leaves the group, and one dropped in one joins it. On the
Matrix a group is framed like a sub-system, dashed, and its tile folds it. In
the tree it is a folder of its own under its sub-system. See
kompartment/src/domain/groups.js, `_foldGroups` and `_groupFrames` in
kompartment/src/ui/graph.js, and `matrixPlan` in kompartment/src/domain/edit.js.

Checked with real presses, drags and keys:
  - the open groups are drawn, each round its own blocks, the inner one inside
    the outer, with their names;
  - a drag on a group's band moves the group, its blocks and the group inside
    it by the same distance, and nothing else, and it is a step to undo that
    runs nothing;
  - a block dragged out of a group's area is in no group, keeps its name, and
    the area it left is drawn round what is left; dragged back in, it is in
    the group again;
  - the band's button folds a group into one node, a line into a block it
    hides ends on that node, and a double-click opens it out where it was;
  - Cmd+G with blocks selected makes a group of them (the name asked for);
  - Del on a group ungroups it and keeps what was in it;
  - on the Matrix a group's tile and dashed frame, and a click on the tile
    folds it into one row;
  - the tree lists a group under its sub-system, holding its blocks;
  - the Information view says what a group holds;
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
    'name': 'grouped', 'simulation': SIM,
    'groups': [{'name': 'Wells'}, {'name': 'Deep', 'group': 'Wells'}],
    'compartments': [
        {'name': 'A', 'initial': 1, 'group': 'Wells'}, {'name': 'B', 'initial': 0, 'group': 'Deep'},
        {'name': 'C', 'initial': 0}, {'name': 'D', 'initial': 0},
    ],
    'transfers': [
        {'name': 'AB', 'from': 'A', 'to': 'B', 'rate': '0.1', 'group': 'Wells'},
        {'name': 'BC', 'from': 'B', 'to': 'C', 'rate': '0.1'},
        {'name': 'CD', 'from': 'C', 'to': 'D', 'rate': '0.1'},
    ],
    'layout': {'A': {'x': 100, 'y': 120}, 'B': {'x': 380, 'y': 120}, 'C': {'x': 700, 'y': 120},
               'D': {'x': 700, 'y': 360}},
}

# Where something is on the screen: a rectangle, or its middle.
RECT = """(() => { const e = %s; if (!e) return null; const r = e.getBoundingClientRect();
  return [r.x, r.y, r.width, r.height]; })()"""
AREA = "document.querySelector('.graph-groups .ggroup[data-group=%s]')"
BAND = "document.querySelector('.graph-groups .ggroup[data-group=%s] .ggroup-head')"
FOLD = "document.querySelector('.graph-groups .ggroup[data-group=%s] .ggroup-fold')"
NODE = "document.querySelector('.graph-nodes .gnode[data-name=%s]')"
MODEL_NOW = "JSON.parse(document.querySelector('#json').value)"
ITEM = "[...document.querySelectorAll('.menu-layer .menu-panel:last-child .menu-item')].find((b) => b.textContent.replace('\\u2713', '').trim().startsWith(%s))"


def q(s):
    """An attribute value in a selector that is itself in a single-quoted string."""
    return '"%s"' % s


def inside(inner, outer, slack=0.5):
    return (inner and outer and inner[0] >= outer[0] - slack and inner[1] >= outer[1] - slack
            and inner[0] + inner[2] <= outer[0] + outer[2] + slack and inner[1] + inner[3] <= outer[1] + outer[3] + slack)


async def main():
    version = json.load(urllib.request.urlopen('http://127.0.0.1:%d/json/version' % CDP))
    async with websockets.connect(version['webSocketDebuggerUrl'], max_size=100 * 1024 * 1024) as bws:
        counter = [0]
        dialogs = []

        async def cmd(method, params=None, session=None):
            counter[0] += 1
            mid = counter[0]
            message = {'id': mid, 'method': method, 'params': params or {}}
            if session:
                message['sessionId'] = session
            await bws.send(json.dumps(message))
            while True:
                reply = json.loads(await bws.recv())
                if reply.get('method') == 'Page.javascriptDialogOpening':
                    # A prompt is answered with the name the test wants, or as
                    # it stands; a confirmation is accepted.
                    dialogs.append(reply['params'].get('message'))
                    answer = {'accept': True}
                    if reply['params'].get('type') == 'prompt':
                        answer['promptText'] = PROMPT[0] or reply['params'].get('defaultPrompt', '')
                    await bws.send(json.dumps({'id': 10 ** 9 + len(dialogs), 'method': 'Page.handleJavaScriptDialog',
                                               'params': answer, 'sessionId': reply.get('sessionId')}))
                    continue
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

        async def mouse(kind, x, y, buttons=0, clicks=1, button='left', modifiers=0):
            await cmd('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y,
                      'button': button if kind != 'mouseMoved' or buttons else 'none',
                      'buttons': buttons, 'clickCount': clicks, 'modifiers': modifiers}, session)

        async def middle(expression):
            r = await ev(RECT % expression)
            return None if not r else [r[0] + r[2] / 2, r[1] + r[3] / 2]

        async def click(xy, modifiers=0):
            if not xy:
                return False
            await mouse('mouseMoved', *xy)
            await mouse('mousePressed', *xy, 1, 1, 'left', modifiers)
            await mouse('mouseReleased', *xy, 0, 1, 'left', modifiers)
            await asyncio.sleep(0.3)
            return True

        async def double_click(xy):
            if not xy:
                return
            await mouse('mouseMoved', *xy)
            await mouse('mousePressed', *xy, 1, 1)
            await mouse('mouseReleased', *xy, 0, 1)
            await mouse('mousePressed', *xy, 1, 2)
            await mouse('mouseReleased', *xy, 0, 2)
            await asyncio.sleep(0.4)

        async def drag(start, end, steps=12):
            if not start or not end:
                return
            await mouse('mouseMoved', *start)
            await mouse('mousePressed', *start, 1)
            for i in range(1, steps + 1):
                await mouse('mouseMoved', start[0] + (end[0] - start[0]) * i / steps,
                            start[1] + (end[1] - start[1]) * i / steps, 1)
                await asyncio.sleep(0.03)
            await asyncio.sleep(0.1)
            await mouse('mouseReleased', *end, 0)
            await asyncio.sleep(0.4)

        KEYS = {'Delete': 46, 'g': 71, 'z': 90}

        async def key(name, modifiers=0):
            base = {'key': name, 'code': 'Key' + name.upper() if len(name) == 1 else name,
                    'windowsVirtualKeyCode': KEYS[name], 'nativeVirtualKeyCode': KEYS[name], 'modifiers': modifiers}
            await cmd('Input.dispatchKeyEvent', dict(base, type='rawKeyDown'), session)
            await cmd('Input.dispatchKeyEvent', dict(base, type='keyUp'), session)
            await asyncio.sleep(0.35)

        async def tab(name):
            await ev("document.querySelector('.tab[data-tab=\"%s\"]').click()" % name)
            await asyncio.sleep(0.4)

        async def model_now():
            await tab('model')
            m = await ev(MODEL_NOW)
            await tab('build')
            return m

        async def load_model(model):
            await tab('model')
            await ev("""(() => { const t = document.querySelector('#json');
              t.value = %s; t.dispatchEvent(new Event('input', { bubbles: true })); })()""" % json.dumps(json.dumps(model)))
            for _ in range(50):
                await asyncio.sleep(0.1)
                if await ev("!document.querySelector('#apply').disabled"):
                    break
            else:
                raise AssertionError('Apply stayed off: %s' % await ev("document.querySelector('#json-check').textContent"))
            await ev("document.querySelector('#apply').click()")
            await asyncio.sleep(0.6)
            await tab('build')

        failures = []
        passed = [0]
        PROMPT = [None]

        def check(condition, message):
            if condition:
                passed[0] += 1
            else:
                failures.append(message)

        target = (await cmd('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
        session = (await cmd('Target.attachToTarget',
                             {'targetId': target, 'flatten': True}))['result']['sessionId']
        await cmd('Page.enable', {}, session)
        await cmd('Network.enable', {}, session)
        await cmd('Network.setCacheDisabled', {'cacheDisabled': True}, session)
        await cmd('Page.addScriptToEvaluateOnNewDocument', {'source': ERRORS}, session)
        await cmd('Emulation.setDeviceMetricsOverride',
                  {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session)
        await cmd('Page.navigate', {'url': PAGE}, session)
        for _ in range(100):
            await asyncio.sleep(0.15)
            try:
                if await ev("!!document.querySelector('#json') && document.querySelectorAll('.graph-nodes .gnode').length > 1"):
                    break
            except AssertionError:
                pass
        await load_model(MODEL)

        # --- the areas -----------------------------------------------------------------
        wells = await ev(RECT % (AREA % q('group:Wells')))
        deep = await ev(RECT % (AREA % q('group:Deep')))
        a = await ev(RECT % (NODE % q('A')))
        b = await ev(RECT % (NODE % q('B')))
        c = await ev(RECT % (NODE % q('C')))
        names = await ev("[...document.querySelectorAll('.graph-groups .ggroup-name')].map((t) => t.textContent)")
        check(wells and deep and inside(a, wells) and inside(b, deep) and inside(deep, wells)
              and not inside(c, wells) and sorted(names or []) == ['Deep', 'Wells'],
              'the areas: Wells %s Deep %s A %s B %s C %s names %s' % (wells, deep, a, b, c, names))

        # --- moved by its band -------------------------------------------------------------
        band = await middle(BAND % q('group:Wells'))
        if band:
            band[0] -= 40
        await drag(band, [band[0] + 60, band[1] + 80] if band else None)
        m = await model_now()
        lay = m.get('layout', {})
        da = (lay.get('A', {}).get('x', 100) - 100, lay.get('A', {}).get('y', 120) - 120)
        db = (lay.get('B', {}).get('x', 380) - 380, lay.get('B', {}).get('y', 120) - 120)
        # The same distance for both, on the lattice as they were, and C where it was.
        check(da == db and da[0] > 0 and da[1] > 0 and da[0] % 10 == 0 and da[1] % 10 == 0
              and lay.get('C', {}).get('x') == 700 and lay.get('C', {}).get('y') == 120,
              'the group moved its blocks by another distance, or something else: %s' % lay)
        check(await ev("!document.querySelector('#run-badge')?.classList.contains('is-stale')") is not False,
              'moving a group made the results stale')
        await key('z', 4 if sys.platform != 'darwin' else 4)
        await asyncio.sleep(0.2)

        # --- a block out of its group, and back -----------------------------------------
        await load_model(MODEL)
        a_mid = await middle(NODE % q('A'))
        await drag(a_mid, [a_mid[0], a_mid[1] + 330] if a_mid else None)
        m = await model_now()
        moved = next((x for x in m.get('compartments', []) if x['name'] == 'A'), {})
        wells_after = await ev(RECT % (AREA % q('group:Wells')))
        a_after = await ev(RECT % (NODE % q('A')))
        check('group' not in moved and moved.get('name') == 'A' and wells_after and not inside(a_after, wells_after),
              'A dragged out of Wells: %s, area %s, A %s' % (moved, wells_after, a_after))
        # Back into the ring of Wells round Deep: what is left of Wells's area
        # once A has gone from it.
        ring = await ev(RECT % (AREA % q('group:Wells')))
        a_mid = await middle(NODE % q('A'))
        await drag(a_mid, [ring[0] + 7, ring[1] + ring[3] / 2] if ring else None)
        m = await model_now()
        back = next((x for x in m.get('compartments', []) if x['name'] == 'A'), {})
        check(back.get('group') in ('Wells', 'Deep'), 'A dragged back in: %s' % back)

        # --- folded, and opened out ---------------------------------------------------------
        await load_model(MODEL)
        await click(await middle(FOLD % q('group:Wells')))
        node = await ev(RECT % (NODE % q('group:Wells')))
        hidden = await ev("!document.querySelector('.graph-nodes .gnode[data-name=\"A\"]')")
        ends = await ev("""[...document.querySelectorAll('.graph-edges [data-edge="BC"]')].map((e) => e.dataset.from)""")
        check(node and hidden and ends == ['group:Wells'], 'folded: node %s, A hidden %s, BC from %s' % (node, hidden, ends))
        m = await model_now()
        check(any(g.get('name') == 'Wells' and g.get('collapsed') is True for g in m.get('groups', [])),
              'folding is not kept with the model: %s' % m.get('groups'))
        await double_click(await middle(NODE % q('group:Wells')))
        check(await ev("!!document.querySelector('.graph-nodes .gnode[data-name=\"A\"]')")
              and not await ev("!!document.querySelector('.graph-nodes .gnode[data-name=\"group:Wells\"]')"),
              'a double-click did not open it out')

        # --- Cmd+G, and Del on a group ------------------------------------------------------
        await load_model(MODEL)
        await click(await middle(NODE % q('C')))
        await click(await middle(NODE % q('D')), 4)
        PROMPT[0] = 'Lower'
        await key('g', 4)
        PROMPT[0] = None
        m = await model_now()
        check(any(g.get('name') == 'Lower' for g in m.get('groups', []))
              and all(x.get('group') == 'Lower' for x in m['compartments'] if x['name'] in ('C', 'D')),
              'Cmd+G made no group of C and D: %s %s' % (m.get('groups'), dialogs[-1:]))
        await click(await middle(BAND % q('group:Lower')))
        await key('Delete')
        m = await model_now()
        check(not any(g.get('name') == 'Lower' for g in m.get('groups', []))
              and {'C', 'D'} <= {x['name'] for x in m['compartments']}
              and all('group' not in x for x in m['compartments'] if x['name'] in ('C', 'D')),
              'Del did not ungroup Lower, or took C and D with it: %s' % m.get('groups'))

        # --- the Matrix -------------------------------------------------------------------
        await load_model(MODEL)
        await tab('matrix')
        tiles = await ev("[...document.querySelectorAll('#panel-matrix .matrix-group')].map((b) => b.dataset.name)")
        dashed = await ev("[...document.querySelectorAll('#panel-matrix td, #panel-matrix th')].some((c) => c.style.backgroundImage.includes('repeating-linear-gradient'))")
        check(tiles == ['group:Wells', 'group:Deep'] and dashed, 'the grid: tiles %s, dashed %s' % (tiles, dashed))
        await click(await middle("document.querySelector('#panel-matrix .matrix-group[data-name=\"group:Wells\"]')"))
        rows = await ev("[...document.querySelectorAll('#panel-matrix th.matrix-self')].map((th) => th.querySelector('[data-name]')?.dataset.name ?? '~')")
        check(rows == ['C', 'D', 'group:Wells'], 'a click on the tile did not fold it: %s' % rows)
        await tab('build')

        # --- the tree and the Information view -----------------------------------------------
        await ev("""(() => { const r = [...document.querySelectorAll('#blocklist .trow')].find((x) => x.dataset.key === '');
            if (r && r.getAttribute('aria-expanded') === 'false') r.querySelector('.twisty')?.click(); })()""")
        await asyncio.sleep(0.3)
        rows = await ev("[...document.querySelectorAll('#blocklist .trow-mgroup')].map((r) => r.dataset.key)")
        check(rows and 'group:Wells' in rows, 'the tree has no group row: %s' % rows)
        await click(await middle("document.querySelector('#blocklist .trow-mgroup[data-key=\"group:Wells\"]')"))
        info = await ev("document.querySelector('#info')?.textContent ?? ''")
        check('group' in info and 'Wells' in info and 'Holds' in info, 'the Information view: %s' % info[:300])

        errors = await ev('window.__errors')
        check(not errors, 'the page raised: %s' % errors)
        await cmd('Target.closeTarget', {'targetId': target})

    for f in failures:
        print('FAIL', f)
    print('%d passed, %d failed' % (passed[0], len(failures)))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
