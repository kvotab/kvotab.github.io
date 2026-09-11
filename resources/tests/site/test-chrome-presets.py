"""rb.html chart presets: importing must merge, not replace.

importPresets() used to hand the parsed file straight to savePresetsToStorage(),
which overwrites the storage key outright. Importing a colleague's two presets
therefore destroyed every preset the user had built up, silently, and reported
success. The results looked right because the imported presets were all there —
what was missing was everything else.

Needs a static server on 127.0.0.1:8765 and Chrome on 127.0.0.1:9222.
"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

PROBE = r"""(() => {
  const KEY = 'chartPresets';
  const out = {};

  /* A curated collection: the built-in default plus two of the user's own. */
  const mine = [
    { id: 'default', name: 'Default' },
    { id: 'mine-a', name: 'My analysis A' },
    { id: 'mine-b', name: 'My analysis B' }
  ];
  localStorage.setItem(KEY, JSON.stringify(mine));

  /* What an import file contains: one preset that collides, one that is new. */
  const incoming = [
    { id: 'mine-a', name: 'My analysis A (from colleague)' },
    { id: 'theirs', name: 'Their preset' }
  ];

  /*
    Drive the real handler rather than a copy of it: importPresets() builds its
    own <input type=file>, so the file is delivered by stubbing the click and
    firing change with a DataTransfer.
  */
  const realClick = HTMLInputElement.prototype.click;
  HTMLInputElement.prototype.click = function () {
    const file = new File([JSON.stringify(incoming)], 'presets.json', { type: 'application/json' });
    const dt = new DataTransfer();
    dt.items.add(file);
    this.files = dt.files;
    this.dispatchEvent(new Event('change'));
  };
  try { importPresets(); } finally { HTMLInputElement.prototype.click = realClick; }

  return new Promise(resolve => setTimeout(() => {
    const after = JSON.parse(localStorage.getItem(KEY) || '[]');
    const byId = Object.fromEntries(after.map(p => [p.id, p.name]));
    out.ids = after.map(p => p.id);
    out.keptOwn = byId['mine-b'] === 'My analysis B';
    out.replacedColliding = byId['mine-a'] === 'My analysis A (from colleague)';
    out.addedNew = byId['theirs'] === 'Their preset';
    out.defaultStillFirst = after[0] && after[0].id === 'default';
    localStorage.removeItem(KEY);
    resolve(JSON.stringify(out));
  }, 400));
})()"""


async def main():
    version = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(version['webSocketDebuggerUrl'], max_size=100 * 1024 * 1024) as bws:
        await bws.send(json.dumps({'id': 1, 'method': 'Target.createTarget',
                                   'params': {'url': 'about:blank'}}))
        target = None
        while target is None:
            message = json.loads(await bws.recv())
            if message.get('id') == 1:
                target = message['result']['targetId']
        await bws.send(json.dumps({'id': 2, 'method': 'Target.attachToTarget',
                                   'params': {'targetId': target, 'flatten': True}}))
        session = None
        while session is None:
            message = json.loads(await bws.recv())
            if message.get('id') == 2:
                session = message['result']['sessionId']
        await bws.send(json.dumps({'id': 3, 'method': 'Network.enable', 'sessionId': session}))
        await bws.send(json.dumps({'id': 4, 'method': 'Network.setCacheDisabled',
                                   'sessionId': session, 'params': {'cacheDisabled': True}}))
        await bws.send(json.dumps({'id': 5, 'method': 'Page.navigate', 'sessionId': session,
                                   'params': {'url': 'http://127.0.0.1:8765/rb.html?n=%d' % int(time.time() * 1000)}}))
        await asyncio.sleep(6)
        await bws.send(json.dumps({'id': 6, 'method': 'Runtime.evaluate', 'sessionId': session,
                                   'params': {'expression': PROBE, 'awaitPromise': True,
                                              'returnByValue': True, 'timeout': 30000}}))
        while True:
            message = json.loads(await bws.recv())
            if message.get('id') == 6:
                result = message.get('result', {})
                if 'exceptionDetails' in result:
                    print('EXCEPTION', json.dumps(result['exceptionDetails'])[:400])
                    sys.exit(1)
                report = json.loads(result['result']['value'])
                break

    print('presets after import :', report['ids'])
    failures = []
    if not report['keptOwn']:
        failures.append('a preset that was not in the imported file was destroyed')
    if not report['replacedColliding']:
        failures.append('an imported preset did not replace the one it collides with')
    if not report['addedNew']:
        failures.append('a new preset from the file was not added')
    if not report['defaultStillFirst']:
        failures.append('the Default preset is no longer first')
    if failures:
        print('%d failure(s):' % len(failures))
        for failure in failures:
            print('  - ' + failure)
        sys.exit(1)
    print('import merges: own presets kept, collisions replaced, new ones added.')

asyncio.run(main())
