"""Helper for driving rb.html in headless Chrome."""
import asyncio
import json
import urllib.request

import websockets


class Page:
    def __init__(self, ws, send, ev, logs):
        self.ws = ws
        self.send = send
        self.ev = ev
        self.logs = logs


async def open_page(bws, url='http://127.0.0.1:8765/rb.html', settle=6):
    await bws.send(json.dumps({'id': 1, 'method': 'Target.createTarget', 'params': {'url': 'about:blank'}}))
    tid = json.loads(await bws.recv())['result']['targetId']
    lst = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/list'))
    ws_url = [x['webSocketDebuggerUrl'] for x in lst if x['id'] == tid][0]
    ws = await websockets.connect(ws_url, max_size=200 * 1024 * 1024)

    j = [0]
    logs = []

    def grab(r):
        m = r.get('method')
        if m == 'Runtime.consoleAPICalled' and r['params']['type'] in ('error', 'warning'):
            parts = []
            for a in r['params']['args']:
                if 'value' in a:
                    parts.append(str(a['value'])[:200])
                else:
                    parts.append(str(a.get('description', '?'))[:200])
            logs.append((r['params']['type'], ' '.join(parts)))
        elif m == 'Runtime.exceptionThrown':
            d = r['params']['exceptionDetails']
            logs.append(('exception', (d.get('exception', {}).get('description') or d.get('text', ''))[:300]))
        elif m == 'Log.entryAdded' and r['params']['entry'].get('level') in ('error', 'warning'):
            # Failed resource loads only appear here, not via console API calls.
            entry = r['params']['entry']
            logs.append(('log:' + entry['level'], '%s %s' % (entry.get('url', ''), entry.get('text', ''))[:300]))
        elif m == 'Network.loadingFailed':
            logs.append(('netfail', str(r['params'].get('errorText', ''))[:200]))
        elif m == 'Network.responseReceived':
            st = r['params'].get('response', {}).get('status')
            if st and st >= 400:
                logs.append(('http%d' % st, r['params']['response'].get('url', '')[:200]))

    async def send(method, params=None):
        j[0] += 1
        await ws.send(json.dumps({'id': j[0], 'method': method, 'params': params or {}}))
        while True:
            r = json.loads(await ws.recv())
            if r.get('id') == j[0]:
                return r
            grab(r)

    async def ev(expr, timeout=120):
        r = await asyncio.wait_for(
            send('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True}),
            timeout)
        res = r.get('result', {})
        if 'exceptionDetails' in res:
            return 'EXCEPTION: ' + str(res['exceptionDetails'].get('exception', {}).get('description', ''))[:400]
        return res.get('result', {}).get('value')

    await send('Runtime.enable')
    await send('Page.enable')
    await send('Log.enable')
    await send('DOM.enable')
    await send('Network.enable')
    await send('Network.setCacheDisabled', {'cacheDisabled': True})
    await send('Page.navigate', {'url': url})
    await asyncio.sleep(settle)
    return tid, Page(ws, send, ev, logs)


async def load_samples(page, names):
    """Load sample .h5 files through the app's own dialog machinery."""
    expr = """(async () => {
      await waitForH5Wasm();
      const { FS, File } = window.h5wasm;
      const names = %s;
      for (const name of names) {
        const resp = await fetch('./resources/data/' + encodeURIComponent(name));
        const buffer = await resp.arrayBuffer();
        loadedFileBuffers[name] = buffer;
        const internalName = `file_${Date.now()}_${Math.random().toString(36).substr(2,9)}.h5`;
        FS.writeFile('/' + internalName, new Uint8Array(buffer));
        if (loadedFiles[name]) { try { loadedFiles[name].close(); } catch(e){} }
        loadedFiles[name] = new File('/' + internalName, 'r');
        fileStates[name] = true;
        if (!fileOrder.includes(name)) fileOrder.push(name);
      }
      await updateTabs(true);
      return fileOrder.slice();
    })()""" % json.dumps(names)
    return await page.ev(expr)
