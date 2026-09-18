"""Prove that every declared action actually reaches a handler that exists.

For each element carrying data-action, the target global is replaced with a spy,
the element is given the event it declares, and the spy must have fired exactly
once. Firing twice would mean the delegated listener matched both click and
change on the same control — the specific regression this design guards against.

The data-on-* attributes are checked differently and for a different failure.
Those reach KVOT_ACTIONS through registerActions, and each entry there is a
thunk — `() => openUrlDialog()` — written so that load order does not matter.
The cost of the indirection is that a thunk naming a function which does not
exist is perfectly valid JavaScript and says nothing until somebody clicks it,
at which point it is a bare "openUrlDialog is not defined" in a banner. So:
every name a control declares must be registered, and every thunk that simply
forwards to a global must name one that is there.
"""
import asyncio
import json
import sys
import urllib.request

import websockets

from driver import open_page

PROBE = r"""(async () => {
  const results = [];
  // Every control that declares an action, and the event it declares it on.
  const declared = [];
  for (const el of document.querySelectorAll('*')) {
    for (const attr of el.attributes) {
      if (attr.name.startsWith('data-on-')) {
        declared.push({ el, on: attr.name.slice('data-on-'.length), name: attr.value });
      }
    }
  }

  const registry = (typeof KVOT_ACTIONS !== 'undefined') ? KVOT_ACTIONS : {};
  const unregistered = [...new Set(declared.filter(d => typeof registry[d.name] !== 'function')
                                           .map(d => d.name))];

  // The handler is replaced in the registry rather than on window, so the real
  // one never runs: several of these open a file picker or start a download.
  for (const { el, on, name } of declared) {
    if (typeof registry[name] !== 'function') {
      results.push({ action: name, on, calls: null, error: 'no handler registered' });
      continue;
    }
    const original = registry[name];
    let calls = 0;
    registry[name] = function () { calls++; };
    try {
      el.dispatchEvent(on === 'click'
        ? new MouseEvent('click', { bubbles: true })
        : new Event(on, { bubbles: true }));
      await new Promise(r => setTimeout(r, 25));
    } finally {
      registry[name] = original;
    }
    results.push({ action: name, on, calls });
  }

  // A checkbox must not double-fire: a real user click emits click then change.
  const checkbox = document.getElementById('showTotal');
  const origToggle = registry.toggleShowTotal;
  let checkboxCalls = 0;
  registry.toggleShowTotal = function () { checkboxCalls++; };
  checkbox.click();
  await new Promise(r => setTimeout(r, 40));
  registry.toggleShowTotal = origToggle;

  // An unknown action must be reported, not silently ignored.
  const probe = document.createElement('button');
  probe.setAttribute('data-on-click', 'noSuchActionExists');
  document.body.appendChild(probe);
  const errors = [];
  const origError = console.error;
  console.error = (...args) => { errors.push(args.map(String).join(' ')); };
  probe.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  await new Promise(r => setTimeout(r, 30));
  console.error = origError;
  probe.remove();

  // A throwing handler must be caught and reported, and must show the banner.
  // This stands in for the failure this whole file exists to catch: a handler
  // that reaches for something which is not there ("openUrlDialog is not
  // defined") arrives here as exactly this, a throw out of runAction.
  const origPreset = registry.applySelectedPreset;
  registry.applySelectedPreset = function () { throw new Error('deliberate test failure'); };
  const thrownErrors = [];
  const origError2 = console.error;
  console.error = (...args) => { thrownErrors.push(args.map(String).join(' ')); };
  document.getElementById('presetSelect').dispatchEvent(new Event('change', { bubbles: true }));
  await new Promise(r => setTimeout(r, 60));
  console.error = origError2;
  registry.applySelectedPreset = origPreset;
  const banner = document.getElementById('failureBanner');

  return JSON.stringify({
    total: declared.length,
    unregistered,
    firedOnce: results.filter(r => r.calls === 1).length,
    problems: results.filter(r => r.calls !== 1),
    checkboxClickCalls: checkboxCalls,
    unknownActionReported: errors.some(e => /No handler registered/.test(e)),
    throwingHandlerReported: thrownErrors.some(e => /deliberate test failure/.test(e)),
    bannerShown: !!(banner && banner.classList.contains('show')),
    bannerText: banner ? banner.querySelector('.failure-banner-text').textContent : null
  }, null, 1);
})()"""


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=8)
        raw = await page.ev(PROBE, timeout=180)
        print(raw)
        await bws.send(json.dumps({'id': 99, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))

    # Judged, not just printed. This used to report and always exit 0, so a
    # control wired to a handler that does not exist -- which is what
    # "openUrlDialog is not defined" was -- could not fail anything.
    try:
        r = json.loads(raw)
    except Exception:
        print('\nFAIL: the probe did not return JSON')
        return 1

    problems = []
    if r.get('unregistered'):
        problems.append(f"data-on-* names with no handler: {r['unregistered']}")
    if r.get('problems'):
        problems.append(f"controls that did not fire exactly once: {r['problems']}")
    if r.get('checkboxClickCalls') != 1:
        problems.append(f"a checkbox click fired its handler {r.get('checkboxClickCalls')} times, not once")
    if not r.get('unknownActionReported'):
        problems.append('an unknown action was not reported')
    if not r.get('throwingHandlerReported'):
        problems.append('a throwing handler was not reported')
    if not r.get('bannerShown'):
        problems.append('the failure banner was not shown')

    if problems:
        print('\nFAILED:')
        for p in problems:
            print('  - ' + p)
        return 1
    print(f"\nok: {r['total']} controls each reached their handler exactly once, "
          f"all registered, unknown and throwing handlers both reported")
    return 0


sys.exit(asyncio.run(main()))
