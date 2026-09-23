#!/usr/bin/env python3
"""Changing the chart's axes: a background overlay across lin/log, and the
preset manager's Current view and selection rules.

The overlay. Its segments used to be converted to axis units once, when the
chart was drawn. Clicking "log" then compared the pointer's log10(x) with
bounds still in years, so the whole chart named the first segment; clicking
back to "lin" on a chart drawn on log did the reverse and nothing past x = 5
had a tooltip. The rectangles were not redrawn either, so a segment starting
at t = 0 dragged the log axis out to 1e-9. And the listener lives on the plot
div, which the next chart reuses, so a chart WITHOUT an overlay answered with
the last one's names.

The preset manager (the gear). Its first row is the chart's current view:
editing it moves the chart, saves nothing, and turns the dropdown to Custom;
applying it unchanged leaves the selection alone. Editing the SELECTED preset
keeps it selected and moves the chart with it; editing any other preset moves
nothing. Closing the dialog only closes it -- it used to re-apply the selected
preset, and since every edit had already reset the dropdown to Auto range, that
threw a zoomed view away.

The file with the overlay is built in the page with h5wasm, so nothing binary
is committed for it. The pointer is driven with real CDP mouse events.

Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-axes.py

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


# time: 0, then 10 .. 1e5 log-spaced. _phase is a data-time background source:
# Submerged 0-1000, Shore 1000-10000, Terrestrial 10000-100000.
BUILD = """(async () => {
  await waitForH5Wasm();
  const { FS, File } = window.h5wasm;
  const path = '/axes-test-' + Date.now() + '.h5';
  const n = 60;
  const t = Float64Array.from({ length: n }, (_, i) => i === 0 ? 0 : Math.pow(10, 1 + 4 * (i - 1) / (n - 2)));
  const w = new File(path, 'w');
  try {
    w.create_dataset({ name: 'time', data: t, shape: [n], dtype: '<f8' }).create_attribute('unit', 'years');
    const g = w.create_group('geosphere').create_group('near_field');
    for (const [name, fn] of [['flux', Math.sin], ['flux2', Math.cos]]) {
      const d = g.create_dataset({ name, data: Float64Array.from(t, (_, i) => fn(i / 5) + 2), shape: [n], dtype: '<f8' });
      d.create_attribute('unit', 'Bq/year');
      d.create_attribute('time_dependent', 'True');
    }
    g.create_dataset({ name: '_phase', data: Float64Array.from([1000, 10000, 100000]), shape: [3], dtype: '<f8' })
      .create_attribute('Index', '["Submerged","Shore","Terrestrial"]');
  } finally {
    w.close();
  }
  const name = 'overlay.h5';
  loadedFileBuffers[name] = FS.readFile(path).slice().buffer;
  loadedFiles[name] = new File(path, 'r');
  fileStates[name] = true;
  if (!fileOrder.includes(name)) fileOrder.push(name);
  await updateTabs(true);
  return fileOrder.slice();
})()"""

HELPERS = r"""(() => {
  window.__notes = [];
  window.notifyUser = (m) => { window.__notes.push(String(m)); };
  window.confirm = () => true;
  window.__wait = (ms) => new Promise(r => setTimeout(r, ms));
  window.__row = (id) => [...document.querySelectorAll('#presetManagerList .preset-manager-row')]
    .find(r => r.dataset.presetId === id);
  window.__btn = (id, label) => [...__row(id).querySelectorAll('button')].find(b => b.textContent === label);
  window.__set = (fields) => { for (const [k, v] of Object.entries(fields)) document.getElementById('pe_' + k).value = v; };
  window.__choose = (id) => {
    const sel = document.getElementById('presetSelect');
    sel.value = id;
    sel.dispatchEvent(new Event('change', { bubbles: true }));   // delegated
    return __wait(700);
  };
  window.__state = () => {
    const pd = document.getElementById('plotlyChart');
    const fl = pd._fullLayout;
    const axis = (a) => ({ type: a.type, range: a.range.map(Number), auto: a.autorange });
    return {
      sel: document.getElementById('presetSelect').value,
      selText: document.getElementById('presetSelect').selectedOptions[0].textContent,
      x: axis(fl.xaxis), y: axis(fl.yaxis),
      yButton: getScaleValue('y'),
      open: document.getElementById('presetManagerOverlay').style.display,
      form: !!document.getElementById('presetEditForm'),
      notes: window.__notes.slice(),
      shapes: (pd.layout.shapes || []).map(s => [s.x0, s.x1]),
      rows: [...document.querySelectorAll('#presetManagerList .preset-manager-row')].map(r => ({
        id: r.dataset.presetId,
        tag: (r.querySelector('.preset-manager-tag') || {}).textContent || '',
        selected: r.classList.contains('is-selected'),
        summary: r.querySelector('.preset-manager-summary').textContent
      }))
    };
  };
  return true;
})()"""

# Where x (in years) is on screen, if it is on the axis at all.
WHERE = """((x) => {
  const pd = document.getElementById('plotlyChart');
  const xa = pd._fullLayout.xaxis, ya = pd._fullLayout.yaxis;
  const r = pd.getBoundingClientRect();
  const lin = xa.type === 'log' ? Math.log10(x) : x;
  if (lin < Math.min(...xa.range) || lin > Math.max(...xa.range)) return null;
  return [r.left + xa._offset + xa.l2p(lin), r.top + ya._offset + ya._length / 2];
})(%s)"""

TIP = """(() => {
  const t = document.getElementById('backgroundOverlayTooltip');
  return t && t.style.display !== 'none' ? t.textContent : null;
})()"""

PHASES = [(30, 'Submerged'), (999, 'Submerged'), (1500, 'Shore'),
          (5000, 'Shore'), (20000, 'Terrestrial'), (60000, 'Terrestrial')]


async def move(page, x, y):
    await page.send('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x, 'y': y})


async def tooltip_at(page, x):
    at = await page.ev(WHERE % json.dumps(x))
    if at is None:
        return 'off the axis'
    await move(page, at[0] - 4, at[1])
    await move(page, at[0], at[1])
    await asyncio.sleep(0.05)
    return await page.ev(TIP)


async def phases_named(page, label):
    named = {x: await tooltip_at(page, x) for x, _ in PHASES}
    check(f'{label}: every phase named correctly', named, {x: want for x, want in PHASES})


async def st(page):
    return await page.ev('__state()')


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'],
                                  max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=7)
        try:
            await page.ev("localStorage.removeItem('chartPresets'); populatePresetDropdown(); true")
            check('overlay file built and loaded', await page.ev(BUILD), ['overlay.h5'])
            await page.ev(HELPERS)
            await page.ev("""(async () => {
              selectDataset('/geosphere/near_field/flux');
              await __wait(1500);
              const sel = document.getElementById('backgroundSourceSelect');
              sel.value = [...sel.options].map(o => o.value).find(v => v.endsWith('_phase'));
              sel.dispatchEvent(new Event('change', { bubbles: true }));
              await __wait(1500);
            })()""")

            # --- the overlay across a change of scale -------------------------
            s = await st(page)
            check('overlay drawn from t = 0 on linear', s['shapes'][:1], [[0, 1000]])
            await phases_named(page, 'linear')

            await page.ev("document.querySelector('#xScaleToggle button[data-value=log]').click(); __wait(1200)")
            s = await st(page)
            check('clicking log: the axis starts at the data, not 1e-9', s['x']['range'][0] >= 0, True)
            check('  and the first rectangle is re-clamped above zero', s['shapes'][0][0] > 0, True)
            await phases_named(page, 'after clicking log')

            await page.ev("(async () => { selectDataset('/geosphere/near_field/flux'); await __wait(1800); })()")
            await phases_named(page, 'drawn on log')
            await page.ev("document.querySelector('#xScaleToggle button[data-value=linear]').click(); __wait(1200)")
            s = await st(page)
            check('back to linear: the first rectangle starts at 0 again', s['shapes'][:1], [[0, 1000]])
            await phases_named(page, 'back to linear from a log drawing')

            # --- the Current view row ----------------------------------------
            await page.ev("openPresetManager(); true")
            s = await st(page)
            check('the manager opens on a Current view row', s['rows'][0]['id'], '__current__')
            check('  summarising the axes on screen', s['rows'][0]['summary'].startswith('X: linear ['), True)
            check('Auto range is marked as the selected one',
                  [r['id'] for r in s['rows'] if r['selected']], ['default'])

            await page.ev("__btn('__current__', 'Edit').click(); true")
            form = await page.ev("""({ name: !!document.getElementById('pe_name'),
                                       scales: [...pe_xScale.options].map(o => o.value),
                                       xMin: pe_xMin.value, xMax: pe_xMax.value })""")
            check('its form has no name field', form['name'], False)
            check('  and no "auto" scale, since a view always has one', form['scales'], ['linear', 'log'])
            check('  and starts from the limits on screen', (form['xMin'], form['xMax']), ('0', '100000'))
            await page.ev("__set({ xMax: '50000' }); pe_save.click(); __wait(700)")
            s = await st(page)
            check('editing it turns the dropdown to Custom', s['sel'], '__custom__')
            check('  moves the chart', (s['x']['range'], s['x']['auto']), ([0, 50000], False))
            check('  leaves the axis that was not edited on auto range', s['y']['auto'], True)
            check('  tags the row Custom', (s['rows'][0]['tag'].startswith('Custom'), s['rows'][0]['selected']), (True, True))
            check('  and keeps the manager open with the form closed', (s['open'], s['form']), ('flex', False))

            await page.ev("closePresetManager(); __wait(400)")
            s = await st(page)
            check('closing keeps Custom and the view it describes',
                  (s['sel'], s['x']['range']), ('__custom__', [0, 50000]))

            # --- editing presets ---------------------------------------------
            await page.ev("__choose('dose')")
            dose = await st(page)
            check('choosing SFR Dose moves the chart', (dose['x']['type'], dose['x']['range']), ('log', [3, 5]))
            await page.ev("openPresetManager(); __btn('__current__', 'Edit').click(); pe_save.click(); __wait(400)")
            s = await st(page)
            check('applying the view unchanged leaves the preset selected',
                  (s['sel'], s['x'], s['y']), ('dose', dose['x'], dose['y']))

            await page.ev("__btn('dose', 'Edit').click(); __set({ xMax: '50000' }); pe_save.click(); __wait(800)")
            s = await st(page)
            check('editing the selected preset keeps it selected', s['sel'], 'dose')
            check('  and the chart follows the edit',
                  [round(v, 4) for v in s['x']['range']], [3, 4.699])
            await page.ev("__btn('dose', 'Edit').click(); __set({ name: 'SFR Dose 2' }); pe_save.click(); __wait(400)")
            s = await st(page)
            check('renaming it keeps it selected under the new name', (s['sel'], s['selText']), ('dose', 'SFR Dose 2'))

            before = s
            await page.ev("__btn('release', 'Edit').click(); __set({ xMin: '10' }); pe_save.click(); __wait(500)")
            s = await st(page)
            check('editing a preset that is not selected changes the selection not at all', s['sel'], 'dose')
            check('  nor the chart', (s['x'], s['y']), (before['x'], before['y']))
            check('  but is saved', 'X: log [10 – 100000]' in next(r for r in s['rows'] if r['id'] == 'release')['summary'], True)

            await page.ev("closePresetManager(); __wait(400)")
            s = await st(page)
            check('closing with a preset selected re-applies nothing', (s['sel'], s['x']), ('dose', before['x']))

            # --- the forms refuse what they used to store silently -----------
            await page.ev("__notes.length = 0; openPresetManager(); __btn('__current__', 'Edit').click(); __set({ xMin: '' }); pe_save.click(); __wait(300)")
            s = await st(page)
            check('one limit missing is refused, and says so',
                  (s['sel'], s['form'], any('both X limits' in n for n in s['notes'])), ('dose', True, True))
            await page.ev("__notes.length = 0; __set({ xMin: '0', xMax: '100' }); pe_save.click(); __wait(300)")
            check('zero on a log axis is refused', any('above zero' in n for n in (await st(page))['notes']), True)
            await page.ev("__notes.length = 0; __set({ xMin: 'abc' }); pe_save.click(); __wait(300)")
            check('a limit that is not a number is refused', any('not a number' in n for n in (await st(page))['notes']), True)
            await page.ev("pe_cancel.click(); __notes.length = 0; __btn('release', 'Edit').click(); __set({ yMax: '' }); pe_save.click(); __wait(300)")
            check('the preset form refuses one limit missing too', any('both Y limits' in n for n in (await st(page))['notes']), True)
            await page.ev("pe_cancel.click(); true")

            # A scale change on its own keeps the limits, as the buttons do.
            y0 = (await st(page))['y']
            await page.ev("__btn('__current__', 'Edit').click(); __set({ yScale: 'linear' }); pe_save.click(); __wait(800)")
            s = await st(page)
            check('changing only the scale is still an edit: Custom', s['sel'], '__custom__')
            check('  the axis and its button both turn linear', (s['y']['type'], s['yButton']), ('linear', 'linear'))
            check('  keeping the limits it had',
                  all(abs(s['y']['range'][i] / 10 ** y0['range'][i] - 1) < 1e-3 for i in (0, 1)), True)

            await page.ev("__choose('release')")
            release = await st(page)
            await page.ev("openPresetManager(); __btn('release', 'Delete').click(); __wait(400)")
            s = await st(page)
            check('deleting the selected preset keeps its view, now as Custom',
                  (s['sel'], s['x']), ('__custom__', release['x']))
            await page.ev("closePresetManager(); true")

            # --- the overlay and the Current view editor ---------------------
            await page.ev("""(async () => {
              await __choose('default');
              document.querySelector('#xScaleToggle button[data-value=linear]').click();
              await __wait(1000);
              openPresetManager(); __btn('__current__', 'Edit').click();
              __set({ xScale: 'log' }); pe_save.click();
              await __wait(1200);
              closePresetManager();
            })()""")
            s = await st(page)
            check('x to log from the editor re-clamps the overlay too',
                  (s['x']['type'], s['shapes'][0][0] > 0, s['x']['range'][0] >= 0), ('log', True, True))
            await phases_named(page, 'x to log from the editor')

            # --- a chart without an overlay, in the same div ------------------
            await page.ev("(async () => { selectDataset('/geosphere/near_field/flux2', { ctrlKey: true, stopPropagation() {} }); await __wait(1800); })()")
            n = await page.ev("document.getElementById('plotlyChart').data.length")
            check('a two-dataset chart replaces it', n, 2)
            check('  and nothing on it answers with the old overlay\'s names',
                  await tooltip_at(page, 1500), None)

            check('no console errors throughout', page.logs[:3], [])
        finally:
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget',
                                       'params': {'targetId': tid}}))

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
