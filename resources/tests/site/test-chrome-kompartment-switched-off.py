"""Kompartment's per-index values for an index that is switched off.

A value set for an index that is switched off -- a scenario that is not run,
an object taken out -- stays in the block: it is saved, the influence arrows
draw from its equation, and it applies again when the index is switched back
on. A block's settings window lists it in the per-index grid, greyed, marked
off and in the list's own order, and the counts keep it apart from what is
set. See `switchedOff` in kompartment/src/domain/edit.js. An arrow that no run
reads -- every dependency behind it in such a value, or in a block that is
switched off -- is drawn faded (`influences`, `dormant`).

Checked with real presses on a model of its own, dropped on the page:
  - the arrows out of a parameter: faded into an expression that names it only
    in a scenario's value, into one that names it only in an object's value,
    and into one that is switched off; at full strength into one that reads it;
  - a scenario-indexed expression whose one equation naming a parameter
    belongs to a scenario that is switched off: selected, the arrow from the
    parameter is drawn; its grid lists Base, Quake, Warm and Cold, the two
    that are off greyed, marked and explained, Quake's equation in sight; its
    section counts one of the two set and two off, and the hint under the
    grid says what a greyed row is;
  - the mark is not cut off in a narrow column, and a greyed row's ground is
    not a set row's;
  - x on a row that is off clears it, and the count follows;
  - a parameter's numbers, in plain boxes, the same way;
  - in a grid with a column of values at the start, the row that is off has a
    dash there, and its boxes line up with the other rows';
  - the Information view counts the values and marks them the same way;
  - and that the page raised nothing.

Serve the repository and start headless Chrome (the recipe is in README.md),
by default on ports 8765 and 9222; SITE_HTTP_PORT and SITE_CDP_PORT choose
others. Exit status is 0 when every check passes.
"""
import asyncio, json, os, sys, tempfile, urllib.request
import websockets

HTTP = int(os.environ.get('SITE_HTTP_PORT', '8765'))
CDP = int(os.environ.get('SITE_CDP_PORT', '9222'))
PAGE = 'http://127.0.0.1:%d/kompartment/index.html' % HTTP

ERRORS = """window.__errors = [];
addEventListener('error', e => window.__errors.push(String(e.message)));
addEventListener('unhandledrejection', e => window.__errors.push('rejected: ' + e.reason));"""

# Two scenarios on and two off, and a list of objects with the middle one off.
# Parameters drawn on the diagram, which they are not by default: the arrows
# checked start at one.
MODEL = {
    'name': 'Scenarios switched off',
    'simulation': {'start_time': 0, 'end_time': 10, 'output_points': 11, 'rtol': 1e-6, 'abstol': 1e-9},
    'view': {'show_parameters': True},
    'index_lists': [
        {'name': 'Scenarios', 'for_scenarios': True, 'indices': [
            {'name': 'Base', 'enabled': True}, {'name': 'Quake', 'enabled': False},
            {'name': 'Warm', 'enabled': True}, {'name': 'Cold', 'enabled': False}]},
        {'name': 'Objects', 'indices': [
            {'name': 'A', 'enabled': True}, {'name': 'B', 'enabled': False}, {'name': 'C', 'enabled': True}]},
    ],
    'parameters': [
        {'name': 'quake_time', 'value': 3500, 'unit': 'year'},
        {'name': 'k', 'value': 1, 'index_lists': ['Scenarios'],
         'entries': [{'index': {'Scenarios': 'Cold'}, 'value': 2}]},
    ],
    'expressions': [
        {'name': 'fail_time', 'unit': 'year', 'index_lists': ['Scenarios'], 'equation': '200000.0',
         'entries': [
             {'index': {'Scenarios': 'Quake'}, 'equation': 'min(quake_time,65000.0)'},
             {'index': {'Scenarios': 'Cold'}, 'equation': '65000.0'},
             {'index': {'Scenarios': 'Warm'}, 'equation': '1000.0'}]},
        {'name': 'depth', 'index_lists': ['Objects'], 'equation': '1',
         'entries': [{'index': {'Objects': 'B'}, 'equation': '2*quake_time'}]},
        {'name': 'life', 'equation': 'quake_time*2'},
        {'name': 'old', 'enabled': False, 'equation': 'quake_time+1'},
    ],
}

# The open window's per-index section: its count, its rows and its hint.
GRID = """JSON.stringify((() => {
  const sec = document.querySelector('dialog[open] details[data-section="entries"]');
  if (!sec) return null;
  const badge = sec.querySelector(':scope > summary .panel-section-badge');
  const hints = sec.querySelectorAll('.insp-hint');
  return {
    badge: badge ? badge.textContent : null, badgeTitle: badge ? badge.title : null,
    hint: hints.length ? hints[hints.length - 1].textContent : null,
    rows: [...sec.querySelectorAll('.insp-entry-list > .insp-entry')].map(r => {
      const idx = r.querySelector('.insp-entry-idx'), tag = r.querySelector('.insp-entry-off');
      const field = r.querySelector('.eq-field, input'), start = r.querySelector('.insp-entry-start');
      const name = r.querySelector('.insp-entry-name') || idx;
      return {
        label: name.textContent, off: r.classList.contains('is-off'), set: r.classList.contains('is-set'),
        tag: tag ? tag.textContent : null, title: idx.title, value: field ? field.value : null,
        ground: getComputedStyle(r).backgroundColor,
        tagIn: tag ? tag.getBoundingClientRect().right <= idx.getBoundingClientRect().right + 0.5
                     && tag.getBoundingClientRect().width > 8 : null,
        fieldX: field ? Math.round(field.getBoundingClientRect().x) : null,
        resetX: Math.round(r.querySelector('.insp-entry-reset').getBoundingClientRect().x),
        resetOn: !r.querySelector('.insp-entry-reset').disabled,
        start: start ? start.textContent : null,
      };
    }),
  };
})())"""


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

        async def mouse(kind, x, y, buttons=0, clicks=1):
            await cmd('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, 'button': 'left'
                      if kind != 'mouseMoved' else 'none', 'buttons': buttons, 'clickCount': clicks}, session)

        async def click(x, y, clicks=1):
            await mouse('mouseMoved', x, y)
            await mouse('mousePressed', x, y, 1, clicks)
            await mouse('mouseReleased', x, y, 0, clicks)
            await asyncio.sleep(0.2)

        async def center(expression):
            return await ev("""(() => { const e = %s; if (!e) return null; e.scrollIntoView({block: 'nearest'});
              const b = e.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; })()""" % expression)

        async def grid():
            return json.loads(await ev(GRID) or 'null')

        def row_of(name):
            return "[...document.querySelectorAll('.trow .tname')].find(e => e.textContent.trim() === %s)" % json.dumps(name)

        async def select(block):
            xy = await center(row_of(block))
            if not xy:
                raise AssertionError('no row for %s in the tree' % block)
            await click(*xy)
            await asyncio.sleep(0.3)

        async def settings(block):
            # One window at a time: the one open is closed first, with its x.
            xy = await center("document.querySelector('dialog[open] .modal-close')")
            if xy:
                await click(*xy)
            await select(block)
            xy = await center("[...document.querySelectorAll('button.info-act')].find(b => b.textContent.startsWith('Edit'))")
            await click(*xy)
            await asyncio.sleep(0.5)

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
        await cmd('Network.clearBrowserCache', {}, session)
        await cmd('Network.setCacheDisabled', {'cacheDisabled': True}, session)
        await cmd('Page.addScriptToEvaluateOnNewDocument', {'source': ERRORS}, session)
        await cmd('Emulation.setDeviceMetricsOverride',
                  {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session)
        await cmd('Page.navigate', {'url': PAGE}, session)
        for _ in range(100):
            await asyncio.sleep(0.15)
            try:
                if await ev("!!document.querySelector('.graph-svg') && !!document.querySelector('.trow')"):
                    break
            except AssertionError:
                pass
        await asyncio.sleep(0.5)

        # Opened by dropping the file on the window, as a person would.
        folder = tempfile.mkdtemp(prefix='kompartment-off-')
        path = os.path.join(folder, 'switched-off.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(MODEL, f)
        drop = {'items': [], 'files': [path], 'dragOperationsMask': 1}
        for kind in ('dragEnter', 'dragOver', 'drop'):
            await cmd('Input.dispatchDragEvent', {'type': kind, 'x': 700, 'y': 500, 'data': drop}, session)
        for _ in range(100):
            await asyncio.sleep(0.15)
            if await ev("!!(%s)" % row_of('fail_time')):
                break
        else:
            print('FAIL the model did not open')
            return 1
        await asyncio.sleep(0.5)

        # --- the arrows out of the parameter: faded where no run reads them ---
        await select('quake_time')
        arrows = json.loads(await ev("""JSON.stringify(Object.fromEntries(
          [...document.querySelectorAll('[data-influence^="quake_time->"]')].map(a => [a.dataset.influence.split('->')[1], {
            dormant: a.classList.contains('is-dormant'), chosen: a.classList.contains('is-chosen'),
            opacity: Number(getComputedStyle(a).opacity) }])))"""))
        check(sorted(arrows) == ['depth', 'fail_time', 'life', 'old'], 'the arrows out of quake_time go to %r' % sorted(arrows))
        faded = {name: a['dormant'] and abs(a['opacity'] - 0.4) < 0.01 for name, a in arrows.items()}
        check(faded == {'depth': True, 'fail_time': True, 'life': False, 'old': True},
              'faded: %r, from %r' % (faded, arrows))
        check(arrows.get('life', {}).get('opacity') == 1 and all(a['chosen'] for a in arrows.values()),
              'the arrow into life is %r' % arrows.get('life'))

        # --- the arrow it is all about ---------------------------------------
        await select('fail_time')
        arrow = json.loads(await ev("""JSON.stringify((() => {
          const a = document.querySelector('[data-influence="quake_time->fail_time"]');
          return a ? { chosen: a.classList.contains('is-chosen'), shown: getComputedStyle(a).display !== 'none' } : null;
        })())"""))
        check(arrow and arrow['chosen'] and arrow['shown'],
              'the arrow from quake_time into fail_time is not drawn: %r' % arrow)

        # --- the Information view ---------------------------------------------
        info = json.loads(await ev("""JSON.stringify((() => {
          const l = [...document.querySelectorAll('.info-line')].find(x => x.querySelector('.info-label')?.textContent === 'Indexed by');
          const box = [...document.querySelectorAll('.info-refs')].find(x => x.querySelector('.info-label')?.textContent === 'Set per index');
          return { line: l ? l.textContent : null,
                   refs: box ? [...box.querySelectorAll('.info-ref')].map(r => ({
                     where: r.querySelector('code').textContent, off: !!r.querySelector('.info-ref-off'),
                     title: r.querySelector('.info-ref-off')?.title ?? null, cls: r.className })) : null };
        })())"""))
        check(info['line'] and info['line'].endswith('2 combinations, 1 set, 2 set for indices switched off'),
              'the Information view counts %r' % info['line'])
        refs = {r['where']: r for r in info['refs'] or []}
        check(sorted(refs) == ['Cold', 'Quake', 'Warm'], 'the Information view lists %r' % sorted(refs))
        check(refs.get('Quake', {}).get('off') and refs.get('Cold', {}).get('off') and not refs.get('Warm', {}).get('off'),
              'the Information view marks %r' % [(w, r['off']) for w, r in refs.items()])
        check((refs.get('Quake', {}).get('title') or '').startswith('Quake is switched off in Scenarios'),
              'the mark in the Information view says %r' % refs.get('Quake', {}).get('title'))

        # --- the settings window: an expression per scenario ------------------
        await settings('fail_time')
        g = await grid()
        if not g:
            print('FAIL the settings window has no per-index section')
            return 1
        labels = [(r['label'], r['off']) for r in g['rows']]
        check(labels == [('Base', False), ('Quake', True), ('Warm', False), ('Cold', True)],
              'the grid lists %r' % labels)
        rows = {r['label']: r for r in g['rows']}
        quake = rows.get('Quake', {})
        check(quake.get('value') == 'min(quake_time,65000.0)', "Quake's equation reads %r" % quake.get('value'))
        check(quake.get('tag') == 'off' and rows.get('Cold', {}).get('tag') == 'off'
              and rows.get('Base', {}).get('tag') is None and rows.get('Warm', {}).get('tag') is None,
              'the marks are %r' % [(r['label'], r['tag']) for r in g['rows']])
        check(quake.get('title') == 'Quake is switched off in Scenarios, so no run reads this value. '
              'It is kept, and applies again when Quake is switched on.',
              'the mark is explained as %r' % quake.get('title'))
        check(quake.get('tagIn') is True, 'the mark is cut off by its column')
        check(g['badge'] == '1/2 set \u00b7 2 off', 'the section reads %r' % g['badge'])
        check('2 more are set for indices switched off, which no run reads' in (g['badgeTitle'] or ''),
              'the count is explained as %r' % g['badgeTitle'])
        check('A greyed row marked off' in (g['hint'] or ''), 'the hint says %r' % g['hint'])
        warm, base = rows.get('Warm', {}), rows.get('Base', {})
        check(quake.get('ground') and warm.get('set') and not base.get('set')
              and warm.get('ground') != quake.get('ground') and base.get('ground') != quake.get('ground'),
              'a greyed row is grounded as %r, a set one %r and a default one %r'
              % (quake.get('ground'), warm.get('ground'), base.get('ground')))
        check(quake.get('resetOn') is True, 'a row that is off cannot be cleared')

        # x on Cold clears it, and the count follows.
        xy = await center("[...document.querySelectorAll('dialog[open] .insp-entry')]"
                          ".find(r => (r.querySelector('.insp-entry-name') || {}).textContent === 'Cold')"
                          "?.querySelector('.insp-entry-reset')")
        if xy:
            await click(*xy)
            await asyncio.sleep(0.4)
        g = await grid()
        labels = [(r['label'], r['off']) for r in g['rows']] if g else None
        check(xy and labels == [('Base', False), ('Quake', True), ('Warm', False)]
              and g['badge'] == '1/2 set \u00b7 1 off',
              'after clearing Cold the grid lists %r under %r' % (labels, g and g['badge']))

        # --- a parameter's numbers ---------------------------------------------
        await settings('k')
        g = await grid()
        labels = [(r['label'], r['off'], r['value']) for r in g['rows']] if g else None
        check(labels == [('Base', False, '1'), ('Warm', False, '1'), ('Cold', True, '2')]
              and g['badge'] == '2 \u00b7 1 off',
              "k's grid lists %r under %r" % (labels, g and g['badge']))

        # --- a grid with a column of values at the start -------------------------
        await settings('depth')
        g = await grid()
        labels = [(r['label'], r['off']) for r in g['rows']] if g else None
        check(labels == [('A', False), ('B', True), ('C', False)], "depth's grid lists %r" % labels)
        if labels == [('A', False), ('B', True), ('C', False)]:
            a, b, c = g['rows']
            check(b['start'] == '\u2014' and a['start'] not in (None, '', '\u2014'),
                  'the start column reads %r' % [r['start'] for r in g['rows']])
            check(a['fieldX'] == b['fieldX'] == c['fieldX'] and a['resetX'] == b['resetX'] == c['resetX'],
                  'the row that is off is out of line: boxes at %r, x at %r'
                  % ([r['fieldX'] for r in g['rows']], [r['resetX'] for r in g['rows']]))

        errors = await ev('window.__errors')
        check(not errors, 'the page raised %r' % errors)

        await cmd('Target.closeTarget', {'targetId': target})
        os.remove(path)
        os.rmdir(folder)

    total = passed[0] + len(failures)
    for f in failures:
        print('FAIL', f)
    print('%d/%d checks passed' % (passed[0], total))
    return 0 if not failures else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
