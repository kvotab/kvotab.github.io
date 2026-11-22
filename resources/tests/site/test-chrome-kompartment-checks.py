"""Kompartment's checks on a model and its run, in the page.

Seven things a reader does to check a model or read its run, each with the
mouse or the keyboard where a reader would use them:

  - a model edited and then replaced -- an example picked from the list at the
    top, New, a file -- is put aside first: a line above the tabs names it and
    brings it back, as it was, and the list at the top keeps it, under Put
    aside, after a reload; an example as it comes is not put aside, and an edit
    of the new model puts the line away (see kompartment/src/ui/aside.js);
  - a name an equation writes that no block has comes with the names it was
    probably meant to be, as buttons in the problem strip; one writes the name
    in, the problem goes, and one undo takes it back (src/domain/suggest.js);
  - the Jacobian check differences an entry that disagrees again at smaller
    steps before reporting it, and says how many met the generated value then
    (src/sim/jaccheck.js);
  - the Table's peaks mark a curve still rising when the run ends, and say so
    under the table (src/ui/tableviews.js);
  - the optimisation window shows how well the values found are known -- their
    ranges and correlations -- and offers to work them out for an answer that
    came without them (src/ui/optdialog.js);
  - Check the run solves the run on show again a hundred times more carefully
    and says whether it holds, names what moved most, can be stopped without
    touching the run on show, and writes the careful setting into the model as
    one edit (src/sim/checkrun.js, src/ui/checkdialog.js);
  - Where it goes draws one nuclide's account over the run -- a flow diagram, a
    stacked chart and a row per route -- and answers another nuclide and the
    slider (src/sim/flows.js, src/ui/flowsdialog.js);
  - and that the page raised nothing.

Serve the repository and start headless Chrome (the recipe is in README.md),
by default on ports 8765 and 9222; SITE_HTTP_PORT and SITE_CDP_PORT choose
others. Exit status is 0 when every check passes.
"""
import asyncio, json, os, sys, urllib.request
import websockets

HTTP = int(os.environ.get('SITE_HTTP_PORT', '8765'))
CDP = int(os.environ.get('SITE_CDP_PORT', '9222'))
PAGE = 'http://127.0.0.1:%d/kompartment/index.html' % HTTP

ERRORS = """window.__errors = [];
addEventListener('error', e => window.__errors.push(String(e.message)));
addEventListener('unhandledrejection', e => window.__errors.push('rejected: ' + e.reason));"""

SIM = {'start_time': 0, 'end_time': 10, 'output_points': 11, 'spacing': 'linear',
       'solver': 'ndf', 'rtol': 1e-8, 'abstol': 1e-12, 'time_unit': 'year'}

RAN = "document.querySelector('#run').disabled === false && /step/.test(document.querySelector('#status')?.textContent || '')"


class Page:
    def __init__(self, ws):
        self.ws, self.n, self.session = ws, 0, None
        self.passed, self.failures = 0, []

    async def cmd(self, method, params=None, session=True):
        self.n += 1
        mid = self.n
        msg = {'id': mid, 'method': method, 'params': params or {}}
        if session and self.session:
            msg['sessionId'] = self.session
        await self.ws.send(json.dumps(msg))
        while True:
            reply = json.loads(await self.ws.recv())
            if reply.get('id') == mid:
                return reply

    async def ev(self, expression):
        reply = await self.cmd('Runtime.evaluate', {'expression': expression, 'awaitPromise': True,
                                                    'returnByValue': True, 'timeout': 60000})
        result = reply.get('result', {})
        if 'exceptionDetails' in result:
            raise AssertionError('page threw: ' + json.dumps(result['exceptionDetails'])[:400])
        return result.get('result', {}).get('value')

    async def wait(self, expression, tries=200, pause=0.1):
        for _ in range(tries):
            try:
                if await self.ev(expression):
                    return True
            except AssertionError:
                pass
            await asyncio.sleep(pause)
        return False

    async def click(self, expression):
        xy = await self.ev("""(() => { const e = %s; if (!e) return null; e.scrollIntoView({block: 'nearest'});
          const b = e.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; })()""" % expression)
        if not xy:
            raise AssertionError('nothing to click: ' + expression)
        for kind, buttons in (('mouseMoved', 0), ('mousePressed', 1), ('mouseReleased', 0)):
            await self.cmd('Input.dispatchMouseEvent', {'type': kind, 'x': xy[0], 'y': xy[1],
                           'button': 'left' if kind != 'mouseMoved' else 'none', 'buttons': buttons, 'clickCount': 1})
        await asyncio.sleep(0.15)

    def check(self, condition, message):
        if condition:
            self.passed += 1
        else:
            self.failures.append(message)

    async def open(self, query):
        await self.cmd('Page.navigate', {'url': 'about:blank'})
        await asyncio.sleep(0.2)
        await self.cmd('Page.navigate', {'url': PAGE + query})
        await self.wait("document.readyState === 'complete' && !!document.querySelector('#example option')")
        await asyncio.sleep(0.8)

    async def tab(self, name):
        await self.click("document.querySelector('.tab[data-tab=\"%s\"]')" % name)
        await asyncio.sleep(0.4)

    async def apply(self, change_js=None, model=None):
        """The model edited through the JSON tab, as a reader edits it there."""
        await self.tab('model')
        await self.wait("document.querySelector('#json').value.length > 10")
        body = 'box.value = %s;' % json.dumps(json.dumps(model, indent=1)) if model is not None else \
            'const m = JSON.parse(box.value); %s; box.value = JSON.stringify(m, null, 2);' % change_js
        await self.ev("(() => { const box = document.querySelector('#json'); %s "
                      "box.dispatchEvent(new Event('input', {bubbles: true})); return true; })()" % body)
        if not await self.wait("!document.querySelector('#apply').disabled", tries=50):
            raise AssertionError('Apply stayed disabled: %r' % await self.ev("document.querySelector('#json-check')?.textContent"))
        await self.click("document.querySelector('#apply')")
        await asyncio.sleep(0.6)
        await self.tab('build')

    async def pick(self, value):
        await self.ev("(() => { const s = document.querySelector('#example'); s.value = %s; "
                      "s.dispatchEvent(new Event('change')); return true; })()" % json.dumps(value))
        await asyncio.sleep(1.2)

    async def run(self):
        await self.click("document.querySelector('#run')")
        return await self.wait(RAN, tries=300)


async def put_aside(p):
    await p.open('?model=four-compartment.json')
    await p.ev("new Promise(r => { const q = indexedDB.deleteDatabase('kompartment.aside'); "
               "q.onsuccess = q.onerror = q.onblocked = () => r(true); })")
    await p.open('?model=four-compartment.json')
    await p.pick('decay-chain.json')
    p.check(await p.ev("document.querySelector('#aside-offer').hidden"), 'an example as it came was put aside')
    await p.apply("m.name = 'My edited chain'; m.parameters = (m.parameters || []).concat([{name: 'mine', value: 42}])")
    await p.pick('biosphere.json')
    offer = await p.ev("(() => { const b = document.querySelector('#aside-offer'); return b.hidden ? null : b.textContent; })()")
    p.check(offer and 'My edited chain' in offer and 'Repository to well' in offer, 'the line: %r' % offer)
    visible = await p.ev("document.querySelector('#aside-offer').getBoundingClientRect().height > 0")
    p.check(visible, 'the line is not in sight')
    group = await p.ev("[...document.querySelectorAll('#aside-group option')].map(o => o.textContent)")
    p.check(group and len(group) == 1 and group[0].startswith('My edited chain'), 'the list: %r' % group)
    await p.click("[...document.querySelectorAll('#aside-offer button')].find(b => b.textContent === 'Bring it back')")
    await asyncio.sleep(1.0)
    p.check('My edited chain' in (await p.ev("document.querySelector('#title').textContent") or ''), 'not brought back')
    mine = await p.ev("(async () => { document.querySelector('.tab[data-tab=\"model\"]').click(); "
                      "await new Promise(r => setTimeout(r, 400)); const m = JSON.parse(document.querySelector('#json').value); "
                      "document.querySelector('.tab[data-tab=\"build\"]').click(); return (m.parameters || []).some(x => x.name === 'mine'); })()")
    p.check(mine, 'the edit did not come back')
    await p.click("document.querySelector('#new')")
    await asyncio.sleep(0.8)
    offer = await p.ev("(() => { const b = document.querySelector('#aside-offer'); return b.hidden ? null : b.textContent; })()")
    p.check(offer and 'a new model' in offer, 'New did not put it aside: %r' % offer)
    await p.apply("m.name = 'Fresh'")
    p.check(await p.ev("document.querySelector('#aside-offer').hidden"), 'an edit did not put the line away')
    await asyncio.sleep(0.5)
    await p.open('?model=blank')
    ok = await p.wait("document.querySelectorAll('#aside-group option').length >= 1", tries=60)
    value = await p.ev("[...document.querySelectorAll('#aside-group option')].find(o => o.textContent.startsWith('My edited chain'))?.value")
    p.check(ok and value, 'not kept between visits')
    if value:
        await p.pick(value)
        p.check('My edited chain' in (await p.ev("document.querySelector('#title').textContent") or ''),
                'not brought back from the list')


async def name_fix(p):
    await p.open('?model=blank')
    await p.apply(model={'name': 'typo', 'simulation': SIM, 'parameters': [{'name': 'Leach_rate', 'value': 0.1}],
                         'compartments': [{'name': 'A', 'initial': '1', 'dydt': '-Leach_rat*A'}]})
    row = await p.ev("[...document.querySelectorAll('#error .problem')].find(x => x.textContent.includes('Leach_rat'))?.textContent")
    p.check(row and 'Change to Leach_rate' in row, 'the strip offers no fix: %r' % row)
    await p.click("document.querySelector('#error .problem-fix-btn')")
    await asyncio.sleep(0.6)
    left = await p.ev("[...document.querySelectorAll('#error .problem')].some(x => x.textContent.includes('Leach_rat'))")
    p.check(not left, 'the fix did not clear the problem')
    await p.click("document.querySelector('#undo')")
    await asyncio.sleep(0.6)
    back = await p.ev("[...document.querySelectorAll('#error .problem')].some(x => x.textContent.includes('Leach_rat'))")
    p.check(back, 'one undo did not take the fix back')


async def jacobian(p):
    await p.apply(model={
        'name': 'langmuir at nought', 'simulation': SIM, 'parameters': [{'name': 'k', 'value': 0.1}],
        'compartments': [{'name': 'Big', 'initial': '1e10'}, {'name': 'A', 'initial': '0'}, {'name': 'B', 'initial': '0'}],
        'transfers': [{'name': 'T', 'from': 'A', 'to': 'B', 'rate': 'k',
                       'availability': {'scheme': 'langmuir', 'top': '1e-4', 'bottom': '1e-2'}}]})
    await p.tab('code')
    await p.click("document.querySelector('[data-codeview=\"jacobian\"]')")
    await asyncio.sleep(0.8)
    await p.click("[...document.querySelectorAll('#panel-code button')].find(b => b.textContent === 'Check the values')")
    ok = await p.wait("!!document.querySelector('#panel-code .jac-verdict')", tries=150)
    verdict = await p.ev("document.querySelector('#panel-code .jac-verdict')?.textContent")
    text = await p.ev("document.querySelector('#panel-code').textContent")
    p.check(ok and verdict and verdict.startswith('Agrees'), 'the verdict: %r' % verdict)
    p.check('more differed at the first step and met the generated value' in (text or ''), 'the second look is not said')
    await p.tab('build')


async def rising(p):
    await p.apply(model={
        'name': 'rising', 'simulation': SIM, 'parameters': [{'name': 'k', 'value': 0.1}],
        'compartments': [{'name': 'Source', 'initial': '100'}, {'name': 'Sink', 'initial': '0'}, {'name': 'Mid', 'initial': '0'}],
        'transfers': [{'name': 'T1', 'from': 'Source', 'to': 'Mid', 'rate': '2'},
                      {'name': 'T2', 'from': 'Mid', 'to': 'Sink', 'rate': 'k'}]})
    p.check(await p.run(), 'the run did not finish')
    await p.tab('table')
    await p.ev("(() => { const s = document.querySelector('select[aria-label=\"How the table is laid out\"]'); "
               "s.value = 'peaks'; s.dispatchEvent(new Event('change')); return true; })()")
    await asyncio.sleep(0.8)
    rows = await p.ev("[...document.querySelectorAll('.table-peaks tbody tr')].map(r => [r.className, r.textContent])")
    marked = [r for r in (rows or []) if 'is-rising' in r[0]]
    p.check(any('Sink' in r[1] and 'still rising' in r[1] for r in marked), 'the sink is not marked: %r' % rows)
    p.check(not any(r[1].startswith('Mid') for r in marked), 'Mid, which peaks inside the run, is marked')
    note = await p.ev("document.querySelector('.peak-rising-note')?.textContent")
    p.check(note and 'still rising' in note, 'no line under the table')
    await p.tab('build')


async def precision(p):
    shown = json.loads(await p.ev("""(async () => {
      const { openOptimiseDialog } = await import('/kompartment/src/ui/optdialog.js');
      let asked = null;
      const d = openOptimiseDialog({ outputs: [{ key: 'A', name: 'A' }],
        variables: [{ key: 'k', name: 'k', value: 0.2 }, { key: 'A0', name: 'A0', value: 3 }], times: [0, 1, 2],
        setup: { targets: [{ output: 'A', when: 'end', value: 1, scale: 'log', weight: 1 }],
                 variables: [{ key: 'k', lower: 0.001, upper: 2, space: 'linear' }, { key: 'A0', lower: 0.1, upper: 100, space: 'log' }],
                 method: 'lm', maxEvals: 300 },
        onRun() {}, onStop() {}, onApply() {}, onTry() {}, onPrecision: (setup, result) => { asked = result; } });
      [...document.querySelectorAll('.pdf-foot button')].find(b => b.textContent === 'Optimise')?.click();
      await new Promise(r => setTimeout(r, 100));
      const base = { ok: true, matched: false, method: 'lm', reason: 'converged', evals: 40, ms: 1200, objective: 0.003,
        values: [{ key: 'k', was: 0.2, value: 0.31, lower: 0.001, upper: 2, pinned: null },
                 { key: 'A0', was: 3, value: 5.2, lower: 0.1, upper: 100, pinned: null }],
        targets: [{ output: 'A', want: 1, got: 1.02, scale: 'log' }] };
      d.finished({ ...base, precision: { targets: 5, free: 2, dof: 3, spread: 0.04, t: 3.18, level: 0.95, reason: null, runs: 4,
        values: [{ key: 'k', se: 0.01, low: 0.28, high: 0.34, factor: null, held: null },
                 { key: 'A0', se: 0.4, low: 4.4, high: 6.1, factor: 1.18, held: null }],
        correlations: { keys: ['k', 'A0'], matrix: [[1, 0.93], [0.93, 1]] } } });
      await new Promise(r => setTimeout(r, 200));
      const ranges = [...document.querySelectorAll('.opt-ranges tbody tr')].map(r => r.textContent);
      const strong = document.querySelectorAll('.opt-corr td.is-strong').length;
      d.finished({ ...base });
      await new Promise(r => setTimeout(r, 200));
      const button = [...document.querySelectorAll('.opt-precision button')].find(b => b.textContent === 'How well are they known?');
      button?.click();
      await new Promise(r => setTimeout(r, 100));
      d.handle.close();
      return JSON.stringify({ ranges, strong, button: !!button, asked: !!asked });
    })()"""))
    p.check(len(shown['ranges']) == 2 and '0.28 to 0.34' in shown['ranges'][0] and '× 1.18' in shown['ranges'][1],
            'the ranges: %r' % shown['ranges'])
    p.check(shown['strong'] == 2, 'a correlation of 0.93 is not marked')
    p.check(shown['button'] and shown['asked'], 'an answer without its precision is not offered it')


async def check_run(p):
    await p.open('?model=decay-chain.json')
    await p.apply("m.simulation.rtol = 1e-3; m.simulation.abstol = 1e-6")
    p.check(await p.run(), 'the run did not finish')
    # Pressed as a script presses it: the button is in the Simulation
    # section, which starts folded away.
    await p.ev("document.querySelector('.sb-check').click(), true")
    ok = await p.wait("!!document.querySelector('.check-run-verdict')", tries=300)
    verdict = await p.ev("document.querySelector('.check-run-verdict')?.textContent")
    rows = await p.ev("[...document.querySelectorAll('.check-run-table tbody tr')].map(r => r.textContent)")
    p.check(ok and verdict and ('nearly holds' in verdict or 'does not hold' in verdict), 'the verdict: %r' % verdict)
    p.check(rows and any('Waste [' in r for r in rows), 'the states that moved: %r' % rows)
    await p.click("[...document.querySelectorAll('dialog[open] .pdf-foot button')].find(b => b.textContent === 'Close')")
    await p.ev("document.querySelector('.sb-check').click(), true")
    await p.click("[...document.querySelectorAll('dialog[open] .pdf-foot button')].find(b => b.textContent === 'Stop')")
    await asyncio.sleep(1.5)
    stopped = await p.ev("document.querySelector('dialog[open] .prob-warn')?.textContent")
    p.check(stopped and stopped.startswith('Stopped') and await p.ev("!document.querySelector('.check-run-verdict')"),
            'Stop: %r' % stopped)
    await p.click("[...document.querySelectorAll('dialog[open] .pdf-foot button')].find(b => b.textContent === 'Close')")
    await p.tab('table')
    await asyncio.sleep(1.0)
    p.check((await p.ev("document.querySelectorAll('#table-body td').length") or 0) > 10, 'the run on show no longer answers')
    await p.tab('build')
    await p.ev("document.querySelector('.sb-check').click(), true")
    await p.wait("!!document.querySelector('.check-run-verdict')", tries=300)
    await p.click("[...document.querySelectorAll('dialog[open] .pdf-foot button')].find(b => b.textContent === 'Run with the careful setting')")
    await p.wait(RAN, tries=300)
    undo = await p.ev("document.querySelector('#undo').title")
    p.check('Tolerances a hundred times tighter' in (undo or ''), 'not one named edit: %r' % undo)


async def flows(p):
    await p.open('?model=biosphere.json')
    p.check(await p.run(), 'the run did not finish')
    await p.ev("document.querySelector('.sb-flows').click(), true")
    ok = await p.wait("!!document.querySelector('.flows-svg')", tries=200)
    first = await p.ev("document.querySelector('.flows-summary')?.textContent")
    p.check(ok and first and 'has decayed' in first and 'has left the model' in first, 'the summary: %r' % first)
    rows = await p.ev("[...document.querySelectorAll('.flows-routes tbody tr')].map(r => r.textContent)")
    p.check(len(rows) >= 6 and any(r.startswith('Release') for r in rows), 'the routes: %r' % rows[:3])
    await p.ev("(() => { const s = document.querySelector('.flows-bar select'); s.value = 'I-129'; "
               "s.dispatchEvent(new Event('change')); return true; })()")
    ok = await p.wait("document.querySelector('.flows-bar select')?.value === 'I-129' && !!document.querySelector('.flows-svg')", tries=100)
    second = await p.ev("document.querySelector('.flows-summary')?.textContent")
    p.check(ok and second != first, 'another nuclide was not drawn')
    await p.ev("(() => { const r = document.querySelector('.flows-slider input'); r.value = String(Math.floor(r.max / 2)); "
               "r.dispatchEvent(new Event('input')); return true; })()")
    await asyncio.sleep(0.3)
    third = await p.ev("document.querySelector('.flows-summary')?.textContent")
    p.check(third and third != second, 'the slider did not redraw')


async def main():
    version = json.load(urllib.request.urlopen('http://127.0.0.1:%d/json/version' % CDP))
    async with websockets.connect(version['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as ws:
        p = Page(ws)
        target = (await p.cmd('Target.createTarget', {'url': 'about:blank'}, session=False))['result']['targetId']
        p.session = (await p.cmd('Target.attachToTarget', {'targetId': target, 'flatten': True},
                                 session=False))['result']['sessionId']
        await p.cmd('Network.enable')
        await p.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        await p.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': ERRORS})
        await p.cmd('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False})
        try:
            for step in (put_aside, name_fix, jacobian, rising, precision, check_run, flows):
                try:
                    await step(p)
                except AssertionError as e:
                    p.failures.append('%s: %s' % (step.__name__, e))
                errors = await p.ev('window.__errors')
                p.check(not errors, '%s: the page raised %r' % (step.__name__, errors))
        finally:
            await p.cmd('Target.closeTarget', {'targetId': target}, session=False)
    total = p.passed + len(p.failures)
    for f in p.failures:
        print('FAIL', f)
    print('%d/%d checks passed' % (p.passed, total))
    return 0 if not p.failures else 1


sys.exit(asyncio.run(main()))
