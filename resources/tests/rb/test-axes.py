#!/usr/bin/env python3
"""Changing the chart's axes: a background overlay across lin/log, the preset
manager's Current view and selection rules, and the toggles that redraw a
chart, which keep the preset.

The overlay. Its segments used to be converted to axis units once, when the
chart was drawn. Clicking "log" then compared the pointer's log10(x) with
bounds still in years, so the whole chart named the first segment; clicking
back to "lin" on a chart drawn on log did the reverse and nothing past x = 5
had a tooltip. The rectangles were not redrawn either, so a segment starting
at t = 0 dragged the log axis out to 1e-9. And the listener lives on the plot
div, which the next chart reuses, so a chart WITHOUT an overlay answered with
the last one's names.

The presets window (the gear). At its top are the chart's axes as they are
now: changing them and applying moves the chart, saves nothing, and turns the
dropdown to Custom; applying nothing changed leaves the selection alone.
Editing the SELECTED preset keeps it selected and moves the chart with it;
editing any other preset moves nothing. Closing the window only closes it --
it used to re-apply the selected preset, and since every edit had already
reset the dropdown to Auto range, that threw a zoomed view away.

The toggles. Show Total, the background and the like redraw the chart with
its axes as they were, and the dropdown used to go back to Auto range anyway,
over a view that was still the preset's or a zoom's. It keeps what it said
now. A group's x lin/log with a background rebuilds the chart too, and that
used to hand the new axis the old range as it was: a zoom on 2000 to 6000
years became 10^2000 on log. The range now goes across as Plotly takes it
across when nothing is rebuilt, and the dropdown turns Custom as it does then.

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
    // A radionuclide group, for the toggles that redraw one (Show Total), with
    // a background of its own, for the x lin/log that rebuilds it.
    const nuc = w.create_group('nuclides');
    nuc.create_attribute('IndexLists', ['Radionuclides']);
    nuc.create_attribute('time_dependent', 'TRUE');
    nuc.create_attribute('unit', 'Bq');
    for (const [name, f] of [['Cs-137', 1], ['I-129', 0.3]]) {
      const d = nuc.create_dataset({ name, data: Float64Array.from(t, v => f * (v + 1)), shape: [n], dtype: '<f8' });
      d.create_attribute('unit', 'Bq');
      d.create_attribute('time_dependent', 'TRUE');
    }
    nuc.create_dataset({ name: '_phase', data: Float64Array.from([1000, 10000, 100000]), shape: [3], dtype: '<f8' })
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
  // Deleting a preset asks in the page (rbAskConfirm); test-ask.py drives that dialog itself.
  window.rbAskConfirm = async () => true;
  window.__wait = (ms) => new Promise(r => setTimeout(r, ms));
  window.__row = (id) => [...document.querySelectorAll('#presetManagerList .preset-row')]
    .find(r => r.dataset.presetId === id);
  window.__btn = (id, label) => [...__row(id).querySelectorAll('button')].find(b => b.textContent === label);
  window.__set = (fields) => { for (const [k, v] of Object.entries(fields)) document.getElementById('pe_' + k).value = v; };
  // The chart's axes at the top of the presets window, typed in as a reader types.
  window.__cv = (fields) => {
    for (const [k, v] of Object.entries(fields)) {
      const el = document.getElementById('cv_' + k);
      el.value = v;
      el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
    }
  };
  window.__enter = (id) => document.getElementById(id).dispatchEvent(
    new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
  window.__choose = (id) => {
    const sel = document.getElementById('presetSelect');
    sel.value = id;
    sel.dispatchEvent(new Event('change', { bubbles: true }));   // delegated
    return __wait(700);
  };
  window.__group = async (path) => {
    await expandAndLoadPath('overlay.h5', path);
    findTreeItem(path, { extra: '.group' }).dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await __wait(2000);
  };
  window.__tick = async (id, on) => {
    const cb = document.getElementById(id);
    if (!!cb.checked !== on) { cb.checked = on; cb.dispatchEvent(new Event('change', { bubbles: true })); }
    await __wait(1500);
  };
  window.__background = async (on) => {
    const sel = document.getElementById('backgroundSourceSelect');
    sel.value = on ? [...sel.options].map(o => o.value).find(v => v.endsWith('_phase')) : '__none__';
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    await __wait(1800);
  };
  window.__scale = async (axis, value) => {
    const b = document.querySelector(`#${axis}ScaleToggle button[data-value=${value}]`);
    if (!b.classList.contains('active')) b.click();
    await __wait(1500);
  };
  window.__zoomX = async (lo, hi) => {
    await Plotly.relayout(document.getElementById('plotlyChart'), { 'xaxis.range': [lo, hi] });
    await __wait(500);
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
      open: !document.getElementById('presetPanel').hidden,
      form: !!document.getElementById('presetEditForm'),
      notes: window.__notes.slice(),
      shapes: (pd.layout.shapes || []).map(s => [s.x0, s.x1]),
      cv: document.getElementById('cv_xMin') ? Object.fromEntries(['xScale', 'xMin', 'xMax', 'yScale', 'yMin', 'yMax']
        .map(k => [k, document.getElementById('cv_' + k).value])) : null,
      cvScales: document.getElementById('cv_xScale') ? [...cv_xScale.options].map(o => o.value) : null,
      applyOff: document.getElementById('cv_apply') ? cv_apply.disabled : null,
      chip: (document.getElementById('presetNowState') || {}).textContent || '',
      rows: [...document.querySelectorAll('#presetManagerList .preset-row')].map(r => ({
        id: r.dataset.presetId,
        selected: r.classList.contains('is-selected'),
        axes: [...r.querySelectorAll('.preset-axis')].map(c => c.textContent)
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
        # The presets live in the browser profile, which every test here
        # shares, and this one edits and deletes them. It puts back what it
        # found, or the next characterise.py lists one preset fewer.
        stored = await page.ev("localStorage.getItem('chartPresets')")
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

            # --- the chart's axes, at the top of the window ------------------
            await page.ev("openPresetManager(); __wait(300)")
            s = await st(page)
            check('the window opens on the chart\'s axes, as fields', (s['open'], s['cv'] is not None), (True, True))
            check('  holding the limits on screen', (s['cv']['xScale'], s['cv']['xMin'], s['cv']['xMax']), ('linear', '0', '100000'))
            check('  with no "keep" scale, since a chart always has one', s['cvScales'], ['linear', 'log'])
            check('  and Apply waiting for a change', s['applyOff'], True)
            check('Auto range is marked as the one in use',
                  ([r['id'] for r in s['rows'] if r['selected']], s['chip']), (['default'], 'Auto range'))

            await page.ev("__cv({ xMax: '50000' }); __wait(100)")
            check('a field changed: Apply is offered, and the window says so',
                  ((await st(page))['applyOff'], (await st(page))['chip']), (False, 'Changed: Apply to use'))
            await page.ev("cv_apply.click(); __wait(700)")
            s = await st(page)
            check('applying it turns the dropdown to Custom', s['sel'], '__custom__')
            check('  moves the chart', (s['x']['range'], s['x']['auto']), ([0, 50000], False))
            check('  leaves the axis that was not changed on auto range', s['y']['auto'], True)
            check('  says Custom, with no preset in use',
                  (s['chip'], [r['id'] for r in s['rows'] if r['selected']]), ('Custom view, not saved', []))
            check('  and keeps the window open, its fields the chart\'s again',
                  (s['open'], s['cv']['xMax'], s['applyOff']), (True, '50000', True))

            await page.ev("closePresetManager(); __wait(400)")
            s = await st(page)
            check('closing keeps Custom and the view it describes',
                  (s['sel'], s['x']['range'], s['open']), ('__custom__', [0, 50000], False))

            # --- editing presets ---------------------------------------------
            await page.ev("__choose('dose')")
            dose = await st(page)
            check('choosing SFR Dose moves the chart', (dose['x']['type'], dose['x']['range']), ('log', [3, 5]))
            await page.ev("openPresetManager(); __enter('cv_xMin'); __wait(400)")
            s = await st(page)
            check('Enter with nothing changed leaves the preset selected, and the chart as it was',
                  (s['sel'], s['x'], s['y'], s['chip']), ('dose', dose['x'], dose['y'], 'Preset: SFR Dose'))

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
            check('  but is saved, and its line says so',
                  next(r for r in s['rows'] if r['id'] == 'release')['axes'], ['X log · 10 – 10⁵', 'Y log · 10⁴ – 10⁹'])

            await page.ev("closePresetManager(); __wait(400)")
            s = await st(page)
            check('closing with a preset selected re-applies nothing', (s['sel'], s['x']), ('dose', before['x']))

            # --- the forms refuse what they used to store silently -----------
            await page.ev("__notes.length = 0; openPresetManager(); __cv({ xMin: '' }); cv_apply.click(); __wait(300)")
            s = await st(page)
            check('one limit missing is refused, and says so, the fields as typed',
                  (s['sel'], s['cv']['xMin'], any('both X limits' in n for n in s['notes'])), ('dose', '', True))
            await page.ev("__notes.length = 0; __cv({ xMin: '0', xMax: '100' }); cv_apply.click(); __wait(300)")
            check('zero on a log axis is refused', any('above zero' in n for n in (await st(page))['notes']), True)
            await page.ev("__notes.length = 0; __cv({ xMin: 'abc' }); cv_apply.click(); __wait(300)")
            check('a limit that is not a number is refused', any('not a number' in n for n in (await st(page))['notes']), True)
            await page.ev("cv_revert.click(); __wait(200)")
            check('Revert puts the chart\'s back', ((await st(page))['cv']['xMin'], (await st(page))['applyOff']), ('1000', True))
            await page.ev("__notes.length = 0; __btn('release', 'Edit').click(); __set({ yMax: '' }); pe_save.click(); __wait(300)")
            check('the preset form refuses one limit missing too', any('both Y limits' in n for n in (await st(page))['notes']), True)
            await page.ev("pe_cancel.click(); true")

            # A scale change on its own keeps the limits, as the buttons do.
            y0 = (await st(page))['y']
            await page.ev("__cv({ yScale: 'linear' }); cv_apply.click(); __wait(800)")
            s = await st(page)
            check('changing only the scale is still an edit: Custom', s['sel'], '__custom__')
            check('  the axis and its button both turn linear', (s['y']['type'], s['yButton']), ('linear', 'linear'))
            check('  keeping the limits it had',
                  all(abs(s['y']['range'][i] / 10 ** y0['range'][i] - 1) < 1e-3 for i in (0, 1)), True)

            await page.ev("__choose('release')")
            release = await st(page)
            await page.ev("__btn('release', 'Delete').click(); __wait(400)")
            s = await st(page)
            check('deleting the selected preset keeps its view, now as Custom',
                  (s['sel'], s['x']), ('__custom__', release['x']))
            await page.ev("closePresetManager(); true")

            # --- the overlay and the chart's axes in the window --------------
            await page.ev("""(async () => {
              await __choose('default');
              document.querySelector('#xScaleToggle button[data-value=linear]').click();
              await __wait(1000);
              openPresetManager(); await __wait(300);
              __cv({ xScale: 'log' }); cv_apply.click();
              await __wait(1200);
              closePresetManager();
            })()""")
            s = await st(page)
            check('x to log from the window re-clamps the overlay too',
                  (s['x']['type'], s['shapes'][0][0] > 0, s['x']['range'][0] >= 0), ('log', True, True))
            await phases_named(page, 'x to log from the window')

            # --- the chart's toggles keep the preset ----------------------------
            # A toggle redraws the chart with its axes as they were, so what
            # described them still does: a preset, Custom, Auto range. Each one
            # used to put the dropdown back to Auto range, over a view that was
            # still the preset's.
            await page.ev("__choose('dose')")
            dose = await st(page)
            await page.ev('__background(false)')
            s = await st(page)
            check('a dataset\'s background off: the preset stays selected, over its view',
                  (s['sel'], s['x'], s['y']), ('dose', dose['x'], dose['y']))
            await page.ev('__background(true)')
            s = await st(page)
            check('  and on again', (s['sel'], s['x'], s['y']), ('dose', dose['x'], dose['y']))

            await page.ev("__group('/nuclides')")
            check('a group chosen: a new chart, on Auto range', (await st(page))['sel'], 'default')
            await page.ev("__choose('dose')")
            dose = await st(page)
            for on in (False, True):
                await page.ev(f"__tick('showTotal', {'true' if on else 'false'})")
                s = await st(page)
                check(f'Show Total {"on" if on else "off"}: the preset stays selected, over its view',
                      (s['sel'], s['x'], s['y']), ('dose', dose['x'], dose['y']))
            await page.ev("Plotly.relayout(document.getElementById('plotlyChart'), { 'yaxis.range': [0, 3] }).then(() => __wait(500))")
            zoom = await st(page)
            await page.ev("__tick('showTotal', false)")
            s = await st(page)
            check('a zoom by hand, then Show Total off: still Custom, still the zoom',
                  (zoom['sel'], s['sel'], s['x'], s['y']), ('__custom__', '__custom__', zoom['x'], zoom['y']))
            await page.ev("(async () => { await __choose('default'); await __tick('showTotal', true); })()")
            s = await st(page)
            check('Auto range, then Show Total on: still Auto range, over the decades of the data, 0.1 to 1e6',
                  (s['sel'], s['y']['range']), ('default', [-1, 6]))

            # The x scale of a group with a background rebuilds the chart, and
            # its range used to go across as it was: a zoom on 2000 to 6000
            # years became 10^2000. It goes now as the relayout takes it on any
            # other chart, and so does the dropdown.
            await page.ev("(async () => { await __background(true); await __scale('x', 'linear'); await __zoomX(2000, 6000); })()")
            check('a group with a background, zoomed on 2000 to 6000 years: Custom', (await st(page))['sel'], '__custom__')
            await page.ev("__scale('x', 'log')")
            s = await st(page)
            check('  x to log keeps those years, as the relayout does (log 2000 to log 6000), and Custom',
                  ([round(v, 4) for v in s['x']['range']], s['sel']), ([3.301, 3.7782], '__custom__'))
            await page.ev("(async () => { await __scale('x', 'linear'); await __zoomX(0, 6000); await __scale('x', 'log'); })()")
            check('  a zoom from 0: its lower end a millionth of the upper on log, as Plotly makes it',
                  [round(v, 4) for v in (await st(page))['x']['range']], [-2.2218, 3.7782])
            await page.ev("__choose('dose')")
            dose = await st(page)
            await page.ev("__scale('x', 'linear')")
            s = await st(page)
            check('  a preset, then x to linear: its years on a linear axis, and Custom',
                  ([round(v) for v in s['x']['range']], s['sel']), ([round(10 ** v) for v in dose['x']['range']], '__custom__'))
            await page.ev("(async () => { await __choose('default'); await __scale('x', 'log'); })()")
            check('  Auto range, then x to log: still Auto range', (await st(page))['sel'], 'default')
            await phases_named(page, 'the group, x to log on Auto range')
            # Back to the dataset and its overlay, for the next chart to replace.
            await page.ev("""(async () => { await __background(false); selectDataset('/geosphere/near_field/flux');
                await __wait(1500); await __background(true); })()""")

            # --- a chart without an overlay, in the same div ------------------
            await page.ev("(async () => { selectDataset('/geosphere/near_field/flux2', { ctrlKey: true, stopPropagation() {} }); await __wait(1800); })()")
            n = await page.ev("document.getElementById('plotlyChart').data.length")
            check('a two-dataset chart replaces it', n, 2)
            check('  and nothing on it answers with the old overlay\'s names',
                  await tooltip_at(page, 1500), None)

            check('no console errors throughout', page.logs[:3], [])
        finally:
            await page.ev("(v => { if (v === null) localStorage.removeItem('chartPresets');"
                          " else localStorage.setItem('chartPresets', v); return true; })(%s)" % json.dumps(stored))
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget',
                                       'params': {'targetId': tid}}))

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
