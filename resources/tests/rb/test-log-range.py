#!/usr/bin/env python3
"""Auto range on a log y axis: the decades a time-series chart shows.

The top is the decade at or above the highest value drawn, and the bottom the
decade at or below the lowest, but never more than 12 decades below the top.
It used to be Plotly's own padded range snapped outwards to whole decades, so
the padding could put the top a decade above the data, and one tiny value (a
1e-30 left by round-off) stretched the axis over thirty decades.

To set the range the snap has to switch Plotly's autorange off. The axis still
counts as on auto range while it shows the range the snap chose, so it follows
the traces as they change. A CI band that reaches past the top raises it, and
turning the band off lowers it again. A redraw such as Show Total fits what it
then draws, where it used to keep the old range and cut the total off. A
zoom, a preset or the axes lock sets a range of its own, and nothing moves it.

The file is built in the page with h5wasm, so nothing binary is committed.
Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-log-range.py

Exit status is 0 when every check passes.
"""
import asyncio
import json
import sys
import urllib.request

import websockets

from driver import open_page

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


# time 1 .. 1e4, twenty points. s(t) = t / 1e4 runs from 1e-4 to 1.
#   a     rises to 9.5e3 from a first value of 3e-30          -> [-8, 4]
#   b     from 2e2 up to exactly 1e3                          -> [2, 3]
#   p     five realisations [100, 200, 300, 400, 3000] * s:
#         mean 800 * s, 95th percentile 2480 * s              -> [-2, 3], with CI [-2, 4]
#   nuc   Cs-137 and I-129 at 600 * s each, their total 1200 * s -> [-2, 3], with total [-2, 4]
BUILD = r"""(async () => {
  await waitForH5Wasm();
  const { FS, File } = window.h5wasm;
  const path = '/log-range-' + Date.now() + '.h5';
  const n = 20;
  const t = Float64Array.from({ length: n }, (_, i) => Math.pow(10, 4 * i / (n - 1)));
  const s = Float64Array.from(t, v => v / 1e4);
  const w = new File(path, 'w');
  const put = (g, name, data, shape, attrs) => {
    const d = g.create_dataset({ name, data: Float64Array.from(data), shape, dtype: '<f8' });
    for (const [k, v] of Object.entries(attrs)) d.create_attribute(k, v);
  };
  try {
    w.create_attribute('n_iter', 5);
    put(w, 'time', t, [n], { unit: 'years' });
    put(w, 'a', Array.from(t, (_, i) => i === 0 ? 3e-30 : 9.5e3 * (i / (n - 1)) ** 2), [n], { unit: 'Sv/year', time_dependent: 'TRUE' });
    put(w, 'b', Array.from(t, (_, i) => 2e2 + 8e2 * i / (n - 1)), [n], { unit: 'Sv/year', time_dependent: 'TRUE' });
    const runs = [100, 200, 300, 400, 3000];
    put(w, 'p', Array.from(s).flatMap(v => runs.map(r => r * v)), [n, 5],
        { unit: 'Sv/year', time_dependent: 'TRUE', probabilistic: 'TRUE', n_iter: 5 });
    const g = w.create_group('nuc');
    g.create_attribute('IndexLists', ['Radionuclides']);
    g.create_attribute('time_dependent', 'TRUE');
    for (const nuc of ['Cs-137', 'I-129']) put(g, nuc, Array.from(s, v => 600 * v), [n], { unit: 'Bq', time_dependent: 'TRUE' });
  } finally {
    w.close();
  }
  const name = 'log-range.h5';
  loadedFileBuffers[name] = FS.readFile(path).slice().buffer;
  loadedFiles[name] = new File(path, 'r');
  fileStates[name] = true;
  if (!fileOrder.includes(name)) fileOrder.push(name);
  await updateTabs(true);
  return fileOrder.slice();
})()"""

HELPERS = r"""(() => {
  window.__wait = (ms) => new Promise(r => setTimeout(r, ms));
  window.__y = () => {
    const ax = document.getElementById('plotlyChart')._fullLayout.yaxis;
    return { type: ax.type, range: ax.range.map(v => Math.round(v * 1000) / 1000), auto: !!ax.autorange };
  };
  window.__do = async (fn, ms = 1500) => { await fn(); await __wait(ms); return __y(); };
  return true;
})()"""


async def y(page, action, ms=1500):
    return await page.ev(f"__do(async () => {{ {action} }}, {ms})")


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'],
                                  max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=7)
        stored = await page.ev("localStorage.getItem('chartPresets')")
        try:
            await page.ev("localStorage.removeItem('chartPresets'); populatePresetDropdown(); true")
            check('the file is built and loaded', await page.ev(BUILD), ['log-range.h5'])
            await page.ev(HELPERS)

            await y(page, "selectDataset('/a');")
            got = await y(page, "document.querySelector('#yScaleToggle button[data-value=log]').click();")
            check('a series up to 9.5e3 tops out at 1e4, the decade above it',
                  (got['type'], got['range'][1]), ('log', 4))
            check('  and a first value of 3e-30 does not take the axis below 12 decades under that',
                  got['range'][0], -8)

            got = await y(page, "selectDataset('/b');")
            check('a series that reaches exactly 1e3 tops out at 1e3, and starts at the decade of its lowest',
                  got['range'], [2, 3])

            # --- a band the axis should follow ---------------------------------
            got = await y(page, "selectDataset('/p');")
            check('a probabilistic series is fitted by its mean', got['range'], [-2, 3])
            got = await y(page, "document.getElementById('showCI').click();")
            check('  showing its CI band, which reaches 2480, raises the top to 1e4', got['range'], [-2, 4])
            got = await y(page, "document.getElementById('showCI').click();")
            check('  and hiding it again lowers the top back to 1e3', got['range'], [-2, 3])

            got = await y(page, "await Plotly.relayout('plotlyChart', { 'yaxis.range': [0, 2] });", 800)
            got = await y(page, "document.getElementById('showCI').click();")
            check('a zoomed axis is left where it was when the band comes on', got['range'], [0, 2])
            await y(page, "document.getElementById('showCI').click();")
            got = await y(page, "await applyPresetById('default');")
            check('  and Auto range fits the data again', got['range'], [-2, 3])

            # --- a redraw -----------------------------------------------------
            got = await y(page, "findTreeItem('/nuc', { extra: '.group' }).click();", 2500)
            check('a group chart with its total fits the total, 1200', got['range'], [-2, 4])
            got = await y(page, "document.getElementById('showTotal').click();", 2500)
            check('  without the total it fits the members, 600, instead of keeping the old top',
                  got['range'], [-2, 3])
            got = await y(page, "document.getElementById('showTotal').click();", 2500)
            check('  and with it again the total is not cut off at 1e3', got['range'], [-2, 4])

            # --- what sets a range of its own ---------------------------------
            # The lock cannot be engaged on Auto range, so zoom first.
            await y(page, "selectDataset('/p');")
            await y(page, "await Plotly.relayout('plotlyChart', { 'yaxis.range': [-1, 2] });", 800)
            await y(page, "document.getElementById('lockAxesBtn').click();", 500)
            got = await y(page, "selectDataset('/a');")
            check('locked axes keep their range for another series', got['range'], [-1, 2])
            got = await y(page, "document.getElementById('showCI').click();")
            check('  and nothing re-fits it while they are locked', got['range'], [-1, 2])
            await y(page, "document.getElementById('showCI').click();")
            await y(page, "document.getElementById('lockAxesBtn').click(); await applyPresetById('default');", 800)

            got = await y(page, "selectDataset('/b');")
            got = await y(page, "document.querySelector('#yScaleToggle button[data-value=linear]').click();")
            check('switching an auto log axis to linear gives linear auto range, from zero',
                  (got['type'], got['auto'], got['range'][0]), ('linear', True, 0))

            check('no console errors throughout', page.logs[:3], [])
        finally:
            await page.ev("(v => { if (v === null) localStorage.removeItem('chartPresets');"
                          " else localStorage.setItem('chartPresets', v); return true; })(%s)" % json.dumps(stored))
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget',
                                       'params': {'targetId': tid}}))
            await bws.recv()

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
