#!/usr/bin/env python3
"""Where the work actually runs, and what happens when it cannot run there.

There are two places a solve can happen, and the page has to pick the better
one available and be honest when it cannot:

    a worker      everything, and the page stays alive while it runs
    the page      everything, but nothing else can happen meanwhile

The second is why this test exists. A run on the main thread is a frozen tab:
no repaint, so the progress bar never moves, and no event loop, so Stop cannot
be clicked. For the built-in NDF that lasts a second and nobody notices. For
ports it lasts minutes, and it is indistinguishable from a crash -- which is
how it was reported.

The fallback is forced here by taking Worker away before any of the page's own
scripts run. Also checked: that the worker and the menu agree about which
solvers exist, because a Worker does not inherit the page's cache-busting and a
browser holding an older copy of the worker will otherwise offer solvers that
nothing can run.

Start the server and the browser as in ../rb/README.md, then

    python3 resources/tests/facsimile/test-worker.py

Exit status is 0 when every check passes.
"""
import asyncio
import json
import sys
import urllib.request

import websockets

URL = 'http://127.0.0.1:8765/facsimile.html'

# Installed before the page's scripts, so the page sees a browser with workers
# unavailable -- a file:// visit, or a policy that forbids them.
SHIMS = {
    'worker': '',
    'no worker at all': "window.Worker = undefined;",
}

failures = []
checks = 0


def check(label, got, want):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}: {got!r}' + ('' if ok else f'  (expected {want!r})'))
    if not ok:
        failures.append(label)


class Session:
    def __init__(self, bws):
        self.bws = bws
        self.n = 0
        self.pending = {}
        self.sid = None

    async def call(self, method, params=None, session=None):
        self.n += 1
        i = self.n
        msg = {'id': i, 'method': method, 'params': params or {}}
        if session:
            msg['sessionId'] = session
        fut = asyncio.get_event_loop().create_future()
        self.pending[i] = fut
        await self.bws.send(json.dumps(msg))
        return await asyncio.wait_for(fut, 120)

    async def pump(self):
        async for raw in self.bws:
            r = json.loads(raw)
            if 'id' in r and r['id'] in self.pending and not self.pending[r['id']].done():
                self.pending[r['id']].set_result(r)

    async def ev(self, expr, timeout=20):
        """Evaluate, or report that the page never answered -- which is the
        symptom this test is about and must not look like a hang."""
        try:
            r = await asyncio.wait_for(self.call(
                'Runtime.evaluate',
                {'expression': expr, 'returnByValue': True, 'awaitPromise': True},
                session=self.sid), timeout)
        except asyncio.TimeoutError:
            return '<<the page did not answer>>'
        res = r.get('result', {})
        if 'exceptionDetails' in res:
            return 'EXCEPTION ' + str(res['exceptionDetails'].get(
                'exception', {}).get('description', ''))[:200]
        return res.get('result', {}).get('value')


async def set_control(s, selector, value):
    await s.ev(f"""(() => {{
      const el = document.querySelector({json.dumps(selector)});
      el.value = {json.dumps(value)};
      el.dispatchEvent(new Event('input', {{ bubbles: true }}));
      el.dispatchEvent(new Event('change', {{ bubbles: true }}));
    }})()""")
    await asyncio.sleep(0.5)


async def open_with(bws, shim):
    s = Session(bws)
    task = asyncio.create_task(s.pump())
    tid = (await s.call('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
    s.sid = (await s.call('Target.attachToTarget',
                          {'targetId': tid, 'flatten': True}))['result']['sessionId']
    await s.call('Runtime.enable', session=s.sid)
    await s.call('Page.enable', session=s.sid)
    await s.call('Network.setCacheDisabled', {'cacheDisabled': True}, session=s.sid)
    if shim:
        await s.call('Page.addScriptToEvaluateOnNewDocument', {'source': shim}, session=s.sid)
    await s.call('Page.navigate', {'url': URL}, session=s.sid)
    await asyncio.sleep(4)
    await s.ev("document.querySelector('[data-on-click=\"fac:resetModel\"]').click()")
    for _ in range(120):
        if (await s.ev("document.getElementById('facStatus')"
                       ".textContent.slice(0, 15)")) == 'Model compiled:':
            break
        await asyncio.sleep(0.25)
    return s, tid, task


async def run_method(s, method, seconds=90):
    await set_control(s, '#facMethod', method)
    await s.ev("document.getElementById('facRun').click()")
    status = ''
    for _ in range(seconds):
        await asyncio.sleep(1)
        status = await s.ev("document.getElementById('facStatus').textContent")
        if not isinstance(status, str):
            break
        if status.startswith(('Done', 'The run failed', 'Stopped')) or 'worker' in status:
            break
    return status


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=64 * 1024 * 1024) as bws:

        # --- a worker: everything works ------------------------------------
        s, tid, task = await open_with(bws, SHIMS['worker'])
        try:
            await set_control(s, '[data-setting="TEND"]', '0.01')
            check('worker: the built-in NDF runs',
                  (await run_method(s, 'ndf')).startswith('Done'), True)
            # The same integrator with every kappa set to zero. Its own menu
            # entry, so the worker has to answer to the name.
            check('worker: BDF runs too',
                  (await run_method(s, 'bdf')).startswith('Done'), True)
            # The point of the worker: the long solvers get off the main thread.
            check('worker: a Julia port runs off the main thread',
                  (await run_method(s, 'julia_fbdf')).startswith('Done'), True)

            # The worker and the menu must agree about what exists. They can
            # drift: a Worker does not inherit the page's cache-busting.
            menu = await s.ev("[...document.getElementById('facMethod').options]"
                              ".map(o => o.value)")
            said = await s.ev("""new Promise((ok) => {
              const w = new Worker('resources/js/facsimile-worker-entry.js?v=20260923b');
              w.onmessage = (e) => { ok(e.data.solvers || []); w.terminate(); };
              w.onerror = () => ok(['<<the worker would not start>>']);
              w.postMessage({ type: 'capabilities', id: 1 });
            })""", 30)
            check('the worker can run every solver on the menu',
                  sorted(set(menu) - set(said)), [])
        finally:
            await s.call('Target.closeTarget', {'targetId': tid})
            task.cancel()

        # --- no worker at all: the built-in pair only, and nothing freezes ---
        s, tid, task = await open_with(bws, SHIMS['no worker at all'])
        try:
            await set_control(s, '[data-setting="TEND"]', '0.01')
            check('no worker: the built-in NDF still runs inline',
                  (await run_method(s, 'ndf')).startswith('Done'), True)
            said = await run_method(s, 'julia_fbdf')
            check('no worker: a Julia port is refused rather than freezing the page',
                  isinstance(said, str) and 'no background worker' in said.lower(), True)
            # If any of the above had actually run inline, the page would have
            # stopped answering and every reply above would say so.
            check('and the page answered throughout',
                  await s.ev("document.getElementById('facRun').disabled"), False)
        finally:
            await s.call('Target.closeTarget', {'targetId': tid})
            task.cancel()

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
