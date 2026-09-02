"""Prove that every declared data-action actually reaches its handler.

For each element carrying data-action, the target global is replaced with a spy,
the element is given the event it declares, and the spy must have fired exactly
once. Firing twice would mean the delegated listener matched both click and
change on the same control — the specific regression this design guards against.
"""
import asyncio
import json
import urllib.request

import websockets

from driver import open_page

PROBE = r"""(async () => {
  const results = [];
  const elements = [...document.querySelectorAll('[data-action]')];

  for (const el of elements) {
    const name = el.dataset.action;
    const on = el.dataset.actionOn || 'click';

    // openFilePicker has no same-named global; it opens the hidden file input.
    if (name === 'openFilePicker') {
      let opened = 0;
      const input = document.getElementById('fileInput');
      const orig = input.click.bind(input);
      input.click = () => { opened++; };
      el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      await new Promise(r => setTimeout(r, 30));
      input.click = orig;
      results.push({ action: name, on, calls: opened, via: 'fileInput.click' });
      continue;
    }

    if (typeof window[name] !== 'function') {
      results.push({ action: name, on, calls: null, error: 'no such global' });
      continue;
    }

    const original = window[name];
    let calls = 0;
    window[name] = function () { calls++; /* do not run the real handler */ };
    try {
      if (on === 'click') {
        el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      } else {
        el.dispatchEvent(new Event(on, { bubbles: true }));
      }
      await new Promise(r => setTimeout(r, 30));
    } finally {
      window[name] = original;
    }
    results.push({ action: name, on, calls });
  }

  // A checkbox must not double-fire: a real user click emits click then change.
  const checkbox = document.getElementById('showTotal');
  const originalToggle = window.toggleShowTotal;
  let checkboxCalls = 0;
  window.toggleShowTotal = function () { checkboxCalls++; };
  checkbox.click();                       // fires click, then change
  await new Promise(r => setTimeout(r, 40));
  window.toggleShowTotal = originalToggle;

  // An unknown action must be reported, not silently ignored.
  const probe = document.createElement('button');
  probe.dataset.action = 'noSuchActionExists';
  document.body.appendChild(probe);
  const errors = [];
  const origError = console.error;
  console.error = (...args) => { errors.push(args.map(String).join(' ')); };
  probe.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  await new Promise(r => setTimeout(r, 30));
  console.error = origError;
  probe.remove();

  // A throwing handler must be caught and reported, and must show the banner.
  const origApply = window.applySelectedPreset;
  window.applySelectedPreset = function () { throw new Error('deliberate test failure'); };
  const thrownErrors = [];
  const origError2 = console.error;
  console.error = (...args) => { thrownErrors.push(args.map(String).join(' ')); };
  document.getElementById('presetSelect').dispatchEvent(new Event('change', { bubbles: true }));
  await new Promise(r => setTimeout(r, 60));
  console.error = origError2;
  window.applySelectedPreset = origApply;
  const banner = document.getElementById('failureBanner');

  return JSON.stringify({
    total: elements.length,
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
        print(await page.ev(PROBE, timeout=180))
        await bws.send(json.dumps({'id': 99, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))

asyncio.run(main())
