"""skbref.html opened from the filesystem, not from a server.

Every other test in this repository loads the page over http, so none of them
could see this: a page opened with file:// has a null origin, which makes every
blob URL it creates `blob:null/...`.

pdf.js, given a worker URL it considers cross-origin, wraps it in a second blob
that calls importScripts() on the first. A worker started from a blob cannot
importScripts a null-origin blob, so the worker died on every PDF with

    Failed to execute 'importScripts' on 'WorkerGlobalScope'
    The script at 'blob:null/...' failed to load

pdf.js then parsed on the main thread, so the analysis was correct and only the
speed was lost — but the failure reached window.onerror and the reader was told
the page had stopped working, which was not true.

The worker is now constructed here and handed to pdf.js as a port, so the
wrapper is never involved. Three things are asserted, because the first two
passed even while the bug was present:

  * the analysis produces a report
  * no error reaches the page
  * the worker actually does the parsing, rather than pdf.js quietly falling
    back to the main thread

Needs Chrome on 127.0.0.1:9222. No server: that is the point.
"""
import asyncio
import base64
import json
import os
import sys
import urllib.request

import websockets

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
PAGE = 'file://' + os.path.join(ROOT, 'skbref.html')
FIXTURE = os.path.join(ROOT, 'resources', 'tests', 'pdf', 'fixture-report.pdf')

PROBE = r"""(async () => {
  const out = { origin: location.origin, errors: [] };
  window.addEventListener('error', event => out.errors.push(String(event.message).slice(0, 200)));
  window.addEventListener('unhandledrejection', event =>
    out.errors.push('rejection: ' + String((event.reason && event.reason.message) || event.reason).slice(0, 200)));

  await loadPdfJs();
  const port = pdfjsLib.GlobalWorkerOptions.workerPort;
  out.hasWorkerPort = !!port;
  let sent = 0;
  if (port) {
    const real = port.postMessage.bind(port);
    port.postMessage = (...args) => { sent++; return real(...args); };
  }

  const raw = atob(PDF_B64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  currentReport = null;
  await handleFile(new File([bytes], 'fixture-report.pdf', { type: 'application/pdf' }));
  for (let i = 0; i < 300 && !currentReport; i++) await new Promise(r => setTimeout(r, 100));

  out.gotReport = !!currentReport;
  out.references = currentReport ? currentRefEntries.length : 0;
  out.messagesToWorker = sent;
  await new Promise(r => setTimeout(r, 300));
  return JSON.stringify(out);
})()"""


async def main():
    if not os.path.exists(FIXTURE):
        print('fixture missing — run resources/tests/pdf/build-fixture-pair.py first')
        sys.exit(1)
    version = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(version['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
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
        await bws.send(json.dumps({'id': 5, 'method': 'Page.navigate',
                                   'sessionId': session, 'params': {'url': PAGE}}))
        await asyncio.sleep(5)
        data = base64.b64encode(open(FIXTURE, 'rb').read()).decode()
        await bws.send(json.dumps({'id': 7, 'method': 'Runtime.evaluate', 'sessionId': session,
                                   'params': {'expression': PROBE.replace('PDF_B64', json.dumps(data)),
                                              'awaitPromise': True, 'returnByValue': True,
                                              'timeout': 180000}}))
        while True:
            message = json.loads(await bws.recv())
            if message.get('id') == 7:
                result = message.get('result', {})
                if 'exceptionDetails' in result:
                    print('EXCEPTION', json.dumps(result['exceptionDetails'])[:400])
                    sys.exit(1)
                report = json.loads(result['result']['value'])
                break

    print('origin             : %s' % report['origin'])
    print('report produced    : %s (%d references)' % (report['gotReport'], report['references']))
    print('worker port in use : %s' % report['hasWorkerPort'])
    print('messages to worker : %d' % report['messagesToWorker'])
    print('errors             : %s' % (report['errors'] or 'none'))

    failures = []
    if not report['gotReport'] or report['references'] != 6:
        failures.append('the PDF did not analyse from file:// (%d references)' % report['references'])
    if report['errors']:
        failures.append('an error reached the page: %s' % report['errors'][0])
    if not report['hasWorkerPort']:
        failures.append('pdf.js was not given a worker port')
    if report['messagesToWorker'] < 5:
        failures.append('the worker received %d messages — the parsing fell back to the main thread'
                        % report['messagesToWorker'])
    if failures:
        print('\n%d failure(s):' % len(failures))
        for failure in failures:
            print('  - ' + failure)
        sys.exit(1)
    print('\nPDF analysis works from a file:// page, in the worker.')

asyncio.run(main())
