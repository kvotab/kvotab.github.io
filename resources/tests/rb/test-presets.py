#!/usr/bin/env python3
"""The axis presets window the gear opens (rb-chart-presets.js).

It floats over the page instead of blocking it, and moves by its title bar.
At its top are the chart's axes as fields; below, the saved presets, a line
each. This checks the window itself; the preset rules it keeps (the chart's
axes applied make Custom, editing the selected preset moves the chart, and
so on) are test-axes.py's, and prefixes are test-prefix.py's.

  the gear opens and closes it, says so (aria-expanded), and gets the focus
  back when Escape closes it;
  it blocks nothing: the chart beside it takes the pointer, and a zoom there
  shows in its fields at once -- unless a field has been changed, which then
  stays as typed until applied or reverted;
  Enter applies; a click on a preset's line uses it, with real mouse events;
  a preset's line reads 100 – 10⁵, not 100000;
  Save as new preset asks a name, selects what it saved, and a name a preset
  has already replaces that preset once the reader says so (never a second
  of the same name; the page's own Auto range is refused); Update asks first;
  a preset's form: Escape cancels it and not the window, Enter saves, and a
  name another preset has is refused;
  the axes lock disables everything in it that could move the axes, and says
  why;
  with no chart drawn it says so, and offers no preset to use;
  it moves by its title bar, with real mouse events, stays in view however
  far it is dragged and below the page's header, opens again where it was
  left, goes back to where it first opened on a double click, and moves by
  the arrow keys from its grip;
  its table of fields keeps each axis on one line, and a preset's form
  opening near the bottom of the screen keeps the window in view.

The file is built in the page with h5wasm, as test-axes.py builds its own.

Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-presets.py

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


# time: 0, then 10 .. 1e5 years; two datasets in Bq/year.
BUILD = r"""(async () => {
  await waitForH5Wasm();
  const { FS, File } = window.h5wasm;
  const path = '/presets-test-' + Date.now() + '.h5';
  const n = 60;
  const t = Float64Array.from({ length: n }, (_, i) => i === 0 ? 0 : Math.pow(10, 1 + 4 * (i - 1) / (n - 2)));
  const w = new File(path, 'w');
  try {
    w.create_dataset({ name: 'time', data: t, shape: [n], dtype: '<f8' }).create_attribute('unit', 'years');
    const g = w.create_group('geosphere');
    for (const [name, fn] of [['flux', Math.sin], ['flux2', Math.cos]]) {
      const d = g.create_dataset({ name, data: Float64Array.from(t, (_, i) => fn(i / 5) + 2), shape: [n], dtype: '<f8' });
      d.create_attribute('unit', 'Bq/year');
      d.create_attribute('time_dependent', 'True');
    }
  } finally {
    w.close();
  }
  const name = 'presets.h5';
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
  // The page's questions, answered here; test-ask.py drives them itself.
  window.__answers = [];
  window.__asked = [];
  window.rbAskText = async (o) => { __asked.push(o.title); return __answers.shift() ?? null; };
  window.rbAskConfirm = async (o) => { __asked.push(o.title + ': ' + (o.message || '')); return !!__answers.shift(); };
  window.__wait = (ms) => new Promise(r => setTimeout(r, ms));
  window.__pick = async (path) => {
    await expandAndLoadPath('presets.h5', path);
    findTreeItem(path, { extra: '.dataset' }).dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await __wait(2000);
  };
  window.__row = (id) => [...document.querySelectorAll('#presetManagerList .preset-row')].find(r => r.dataset.presetId === id);
  window.__btn = (id, label) => [...__row(id).querySelectorAll('button')].find(b => b.textContent === label);
  window.__cv = (fields) => {
    for (const [k, v] of Object.entries(fields)) {
      const el = document.getElementById('cv_' + k);
      el.value = v;
      el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
    }
  };
  window.__key = (el, key, extra = {}) => el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...extra }));
  window.__state = () => {
    const panel = document.getElementById('presetPanel');
    const r = panel.getBoundingClientRect();
    const pd = document.getElementById('plotlyChart');
    const fl = pd._fullLayout || {};
    const v = (id) => (document.getElementById(id) || {}).value;
    return {
      open: !panel.hidden,
      rect: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
      inView: r.left >= 0 && r.top >= 0 && r.right <= innerWidth + 0.5 && r.bottom <= innerHeight + 0.5,
      headerBottom: Math.round(document.querySelector('body > header').getBoundingClientRect().bottom),
      gear: { expanded: presetGear.getAttribute('aria-expanded'), active: presetGear.classList.contains('active') },
      focusIn: panel.contains(document.activeElement), focusId: document.activeElement.id,
      sel: presetSelect.value,
      x: fl.xaxis ? fl.xaxis.range.map(Number) : null, y: fl.yaxis ? fl.yaxis.range.map(Number) : null,
      cv: v('cv_xMin') === undefined ? null : { xMin: v('cv_xMin'), xMax: v('cv_xMax'), yMin: v('cv_yMin'), yMax: v('cv_yMax'),
                                               yScale: v('cv_yScale') },
      chip: (document.getElementById('presetNowState') || {}).textContent || '',
      applyOff: document.getElementById('cv_apply') ? cv_apply.disabled : null,
      empty: [...document.querySelectorAll('#presetNow .preset-empty')].map(p => p.textContent),
      locked: { cls: panel.classList.contains('is-locked'), fields: panel.querySelector('.preset-panel-fields').disabled,
                note: getComputedStyle(panel.querySelector('.preset-locked-note')).display !== 'none' },
      rows: [...document.querySelectorAll('#presetManagerList .preset-row')].map(r => ({
        id: r.dataset.presetId, name: r.querySelector('.preset-name').textContent,
        selected: r.classList.contains('is-selected'), checked: r.querySelector('.preset-use').getAttribute('aria-checked'),
        useOff: r.querySelector('.preset-use').disabled,
        axes: [...r.querySelectorAll('.preset-axis')].map(c => c.textContent) })),
      form: !!document.getElementById('presetEditForm'),
      notes: __notes.slice(), asked: __asked.slice(),
      names: loadPresets().map(p => p.name)
    };
  };
  return true;
})()"""


async def mouse(page, kind, x, y, buttons=0, clicks=1):
    params = {'type': kind, 'x': x, 'y': y, 'buttons': buttons}
    if kind in ('mousePressed', 'mouseReleased'):
        params.update({'button': 'left', 'clickCount': clicks})
    await page.send('Input.dispatchMouseEvent', params)


async def drag(page, x0, y0, x1, y1, steps=6):
    await mouse(page, 'mouseMoved', x0, y0)
    await mouse(page, 'mousePressed', x0, y0, buttons=1)
    for i in range(1, steps + 1):
        await mouse(page, 'mouseMoved', x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps, buttons=1)
    await mouse(page, 'mouseReleased', x1, y1)
    await asyncio.sleep(0.2)


async def click(page, x, y, clicks=1):
    await mouse(page, 'mouseMoved', x, y)
    for n in range(1, clicks + 1):
        await mouse(page, 'mousePressed', x, y, buttons=1, clicks=n)
        await mouse(page, 'mouseReleased', x, y, clicks=n)
    await asyncio.sleep(0.2)


async def st(page):
    return await page.ev('__state()')


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=7)
        # The presets and the window's place live in the browser profile, which
        # every test here shares: put back what was found.
        stored = await page.ev("JSON.stringify([localStorage.getItem('chartPresets'), localStorage.getItem('kvot-rb-preset-panel')])")
        try:
            await page.ev("localStorage.removeItem('chartPresets'); localStorage.removeItem('kvot-rb-preset-panel'); populatePresetDropdown(); true")
            check('file built and loaded', await page.ev(BUILD, timeout=120), ['presets.h5'])
            await page.ev(HELPERS)

            # --- with no chart drawn ----------------------------------------
            await page.ev("(async () => { presetGear.disabled = false; openPresetManager(); await __wait(200); })()")
            s = await st(page)
            check('opened with no chart drawn, it says so', (s['open'], s['empty'], s['cv']),
                  (True, ['No chart is drawn. Choose a dataset or a group, and its axes are shown here.'], None))
            check('  and offers no preset to use', all(r['useOff'] for r in s['rows']), True)
            await page.ev("closePresetManager(); true")

            # --- opening and closing ----------------------------------------
            await page.ev("__pick('/geosphere/flux')")
            await page.ev("presetGear.click(); __wait(400)")
            s = await st(page)
            check('the gear opens it, and says so', (s['open'], s['gear']), (True, {'expanded': 'true', 'active': True}))
            check('  the focus in it', s['focusIn'], True)
            check('  the chart\'s axes in its fields, Auto range in use',
                  (s['cv']['xMin'], s['cv']['xMax'], s['chip'], [r['id'] for r in s['rows'] if r['selected']]),
                  ('0', '100000', 'Auto range', ['default']))
            check('  a preset\'s line readable: SFR Release',
                  next(r['axes'] for r in s['rows'] if r['id'] == 'release'), ['X log · 100 – 10⁵', 'Y log · 10⁴ – 10⁹'])
            check('  and SFR Dose', next(r['axes'] for r in s['rows'] if r['id'] == 'dose'), ['X log · 1000 – 10⁵', 'Y log · 10⁻⁷ – 2×10⁻⁵'])
            check('  the window inside the browser\'s, below the page\'s header',
                  (s['inView'], s['rect'][1] >= s['headerBottom']), (True, True))
            controls = "Math.round(document.querySelector('#plotlyChartContainer .chart-controls').getBoundingClientRect().bottom)"
            before = await page.ev(controls)
            check('  and below the chart\'s controls, the gear and the preset list in reach', s['rect'][1] >= before, True)
            await page.ev("""(async () => { legendStatus.style.display = 'block';
              legendStatus.textContent = 'Showing a great many traces of a great many more, said at length so that the controls wrap onto another line';
              await __wait(400); })()""")
            grown = await page.ev(controls)
            check('  the controls grown onto another line, it moves down to keep below them',
                  (grown > before, (await st(page))['rect'][1] >= grown), (True, True))
            await page.ev("(async () => { legendStatus.textContent = ''; legendStatus.style.display = 'none'; await __wait(400); })()")
            # On one line: their middles within 3 px (a select and a text field are not one height).
            fits = await page.ev("""(() => {
              const mid = (id) => { const r = document.getElementById(id).getBoundingClientRect(); return (r.top + r.bottom) / 2; };
              const line = (ids) => { const m = ids.map(mid); return Math.max(...m) - Math.min(...m) <= 3; };
              const panel = document.getElementById('presetPanel').getBoundingClientRect();
              const right = Math.max(...['cv_xUnit', 'cv_yUnit', 'cv_xMax', 'cv_yMax'].map(id => document.getElementById(id).getBoundingClientRect().right));
              return { xRow: line(['cv_xScale', 'cv_xPrefix', 'cv_xMin', 'cv_xMax', 'cv_xUnit']),
                       yRow: line(['cv_yScale', 'cv_yPrefix', 'cv_yMin', 'cv_yMax', 'cv_yUnit']),
                       twoRows: mid('cv_yMin') - mid('cv_xMin') > 10, inside: right <= panel.right };
            })()""")
            check('  each axis\'s fields on a line of their own, inside the window', fits,
                  {'xRow': True, 'yRow': True, 'twoRows': True, 'inside': True})

            await page.ev("__key(document.activeElement, 'Escape'); __wait(200)")
            s = await st(page)
            check('Escape closes it, and the focus goes back to the gear',
                  (s['open'], s['gear']['expanded'], s['focusId']), (False, 'false', 'presetGear'))
            await page.ev("presetGear.click(); __wait(300); presetGear.click(); __wait(300)")
            check('the gear closes it again too', (await st(page))['open'], False)

            # --- it blocks nothing, and follows the chart -------------------
            await page.ev("openPresetManager(); __wait(300)")
            plot = await page.ev("""(() => { const pd = document.getElementById('plotlyChart'); const xa = pd._fullLayout.xaxis, ya = pd._fullLayout.yaxis;
              const r = pd.getBoundingClientRect(); return [r.left + xa._offset + xa._length * 0.15, r.top + ya._offset + ya._length * 0.5]; })()""")
            under = await page.ev("(([x, y]) => { const e = document.elementFromPoint(x, y); return !!e.closest('#plotlyChart'); })(%s)" % json.dumps(plot))
            check('with it open, the chart beside it takes the pointer', under, True)
            await page.ev("Plotly.relayout(document.getElementById('plotlyChart'), { 'xaxis.range': [1000, 30000] }).then(() => __wait(300))")
            s = await st(page)
            check('a zoom on the chart shows in its fields at once, and it says Custom',
                  (s['cv']['xMin'], s['cv']['xMax'], s['chip'], s['sel']), ('1000', '30000', 'Custom view, not saved', '__custom__'))
            await page.ev("__cv({ xMax: '20000' }); Plotly.relayout(document.getElementById('plotlyChart'), { 'xaxis.range': [2000, 40000] }).then(() => __wait(300))")
            s = await st(page)
            check('a field changed stays as typed while the chart moves', (s['cv']['xMax'], s['chip'], s['applyOff']),
                  ('20000', 'Changed: Apply to use', False))
            await page.ev("cv_revert.click(); __wait(200)")
            s = await st(page)
            check('Revert takes the chart\'s as it is now', (s['cv']['xMin'], s['cv']['xMax'], s['applyOff']), ('2000', '40000', True))
            await page.ev("__cv({ xMax: '25000' }); __key(cv_xMax, 'Enter'); __wait(600)")
            s = await st(page)
            check('Enter in a field applies it', (s['x'], s['cv']['xMax'], s['applyOff']), ([2000, 25000], '25000', True))

            # --- using a preset with the pointer ------------------------------
            box = await page.ev("""(() => { const r = __row('release').querySelector('.preset-name').getBoundingClientRect();
              return [r.left + r.width / 2, r.top + r.height / 2]; })()""")
            await click(page, *box)
            await page.ev("__wait(700)")
            s = await st(page)
            check('a click on a preset\'s line uses it: the chart, the dropdown, the line',
                  ([round(v, 3) for v in s['x']], s['sel'], [r['id'] for r in s['rows'] if r['selected']],
                   next(r['checked'] for r in s['rows'] if r['id'] == 'release'), s['chip']),
                  ([2, 5], 'release', ['release'], 'true', 'Preset: SFR Release'))
            await page.ev("__cv({ yScale: 'linear' }); cv_apply.click(); __wait(700)")

            # --- saving ------------------------------------------------------
            await page.ev("__answers.push('Long term'); cv_save.click(); __wait(500)")
            s = await st(page)
            check('Save as new preset asks a name, saves the view, and uses it',
                  ('Long term' in s['names'], s['sel'] == next(r['id'] for r in s['rows'] if r['name'] == 'Long term'),
                   s['chip']), (True, True, 'Preset: Long term'))
            long_id = next(r['id'] for r in s['rows'] if r['name'] == 'Long term')
            # The time axis is log since SFR Release: its range is in decades.
            await page.ev("Plotly.relayout(document.getElementById('plotlyChart'), { 'xaxis.range': [2, 4] }).then(() => __wait(300))")
            await page.ev("__asked.length = 0; __answers.push('long TERM', false); cv_save.click(); __wait(500)")
            s = await st(page)
            check('a name a preset has already: it asks before replacing, and No keeps it',
                  (s['asked'][-1].startswith('Replace preset'), s['names'].count('Long term'), s['sel']), (True, 1, '__custom__'))
            await page.ev("__answers.push('Long term', true); cv_save.click(); __wait(500)")
            s = await st(page)
            stored_x = await page.ev(f"loadPresets().find(p => p.id === {json.dumps(long_id)}).xMax")
            check('  and Yes replaces it in place, no second of the name, and uses it',
                  (s['names'].count('Long term'), stored_x, s['sel']), (1, 10000, long_id))
            await page.ev("__notes.length = 0; __answers.push('auto RANGE'); cv_save.click(); __wait(400)")
            s = await st(page)
            check('the page\'s own Auto range is not a name to save under',
                  (s['names'].count('Auto range'), any('choose another name' in n for n in s['notes'])), (1, True))

            # --- Update asks first --------------------------------------------
            await page.ev("Plotly.relayout(document.getElementById('plotlyChart'), { 'xaxis.range': [1, 3] }).then(() => __wait(300))")
            await page.ev("__asked.length = 0; __answers.push(false); __btn('dose', 'Update').click(); __wait(300)")
            dose_x = await page.ev("loadPresets().find(p => p.id === 'dose').xMax")
            check('Update asks first, and No changes nothing', ((await st(page))['asked'][-1].startswith('Update preset'), dose_x), (True, 1e5))
            await page.ev("__answers.push(true); __btn('dose', 'Update').click(); __wait(400)")
            s = await st(page)
            check('  Yes puts the chart\'s axes in it, and uses it',
                  (await page.ev("loadPresets().find(p => p.id === 'dose').xMax"), s['sel'], s['chip']), (1000, 'dose', 'Preset: SFR Dose'))

            # --- a preset's form ------------------------------------------------
            await page.ev("__btn('release', 'Edit').click(); __wait(200)")
            check('Edit opens its form, the name ready to type over',
                  ((await st(page))['form'], await page.ev("document.activeElement.id"),
                   await page.ev("pe_name.selectionStart === 0 && pe_name.selectionEnd === pe_name.value.length")), (True, 'pe_name', True))
            await page.ev("__key(pe_name, 'Escape'); __wait(200)")
            s = await st(page)
            check('  Escape cancels the form, and not the window', (s['form'], s['open']), (False, True))
            await page.ev("__notes.length = 0; __btn('release', 'Edit').click(); pe_name.value = 'sfr dose'; __key(pe_name, 'Enter'); __wait(300)")
            s = await st(page)
            check('  a name another preset has is refused', (s['form'], any('choose another name' in n for n in s['notes'])), (True, True))
            await page.ev("pe_name.value = 'SFR Release, long'; __key(pe_xMax, 'Enter'); __wait(400)")
            s = await st(page)
            check('  Enter saves it', (s['form'], 'SFR Release, long' in s['names']), (False, True))

            # --- the lock -----------------------------------------------------
            await page.ev("toggleAxesLock(); __wait(300)")
            s = await st(page)
            check('the axes locked: nothing in it may move them, and it says why', s['locked'], {'cls': True, 'fields': True, 'note': True})
            check('  Import too', await page.ev("document.querySelector('#presetPanel [data-on-click=importPresets]').disabled"), True)
            await page.ev("toggleAxesLock(); __wait(300)")
            check('  and unlocked, all of it again', (await st(page))['locked'], {'cls': False, 'fields': False, 'note': False})

            # --- moving it -------------------------------------------------------
            s = await st(page)
            first = s['rect']
            bar = [first[0] + 140, first[1] + 16]
            await drag(page, bar[0], bar[1], bar[0] - 300, bar[1] + 120)
            s = await st(page)
            check('dragged by its title bar, it moves with the pointer',
                  (s['rect'][0] - first[0], s['rect'][1] - first[1]), (-300, 120))
            # Taken to the browser's corners (CDP drops a pointer outside the window).
            moved = s['rect']
            await drag(page, moved[0] + 140, moved[1] + 16, 2, 2)
            s = await st(page)
            check('  dragged into the top left corner, it stops at the edge, below the page\'s header',
                  (s['rect'][0], s['rect'][1] == s['headerBottom'], s['inView']), (0, True, True))
            size = await page.ev("[innerWidth, innerHeight]")
            await drag(page, 140, s['rect'][1] + 16, size[0] - 2, size[1] - 2)
            s = await st(page)
            check('  dragged into the bottom right corner, it stays all in view, at the edges',
                  (s['inView'], s['rect'][0] + s['rect'][2], s['rect'][1] + s['rect'][3]), (True, size[0], size[1]))
            await drag(page, s['rect'][0] + 140, s['rect'][1] + 16, 400, 300)
            placed = (await st(page))['rect']
            await page.ev("closePresetManager(); __wait(200); openPresetManager(); __wait(300)")
            check('closed and opened again, it is where it was left', (await st(page))['rect'][:2], placed[:2])
            await click(page, placed[0] + 200, placed[1] + 16, clicks=2)
            back = (await st(page))['rect']
            await page.ev("closePresetManager(); __wait(200); openPresetManager(); __wait(300)")
            check('a double click on its bar puts it back where it first opens, and forgets where it was',
                  (back[:2] != placed[:2], (await st(page))['rect'][:2] == back[:2],
                   await page.ev("localStorage.getItem('kvot-rb-preset-panel')")), (True, True, None))
            await page.ev("document.querySelector('.preset-panel-grip').focus(); __key(document.activeElement, 'ArrowLeft'); __key(document.activeElement, 'ArrowDown', { shiftKey: true }); __wait(100)")
            s = await st(page)
            check('  its grip moves it by the arrow keys, 10 px, or 50 with Shift',
                  (s['rect'][0] - back[0], s['rect'][1] - back[1]), (-10, 50))
            await page.ev("""(async () => { const p = presetPanel; p.style.top = (innerHeight - p.offsetHeight) + 'px'; await __wait(50);
              __btn('release', 'Edit').click(); await __wait(300); })()""")
            check('a preset\'s form opening near the bottom keeps the window in view', (await st(page))['inView'], True)
            await page.ev("pe_cancel.click(); true")

            # --- a preset from a file is text ------------------------------------
            await page.ev("""(async () => {
              const presets = loadPresets();
              presets.push({ id: 'evil"]><img src=x onerror="window.__owned=1">', name: '<img src=x onerror="window.__owned=2">',
                             builtIn: false, xScale: 'log', yScale: null, xMin: '" autofocus onfocus="window.__owned=3" x="', xMax: 5,
                             yMin: null, yMax: null, xPrefix: '<b>k</b>', yPrefix: null });
              savePresetsToStorage(presets);
              populatePresetDropdown();
              await __wait(200);
              const row = [...document.querySelectorAll('#presetManagerList .preset-row')].find(r => r.dataset.presetId.startsWith('evil'));
              row.querySelector('[data-act=edit]').click();
              await __wait(300);
              return true;
            })()""")
            evil = await page.ev("""(() => {
              const row = [...document.querySelectorAll('#presetManagerList .preset-row')].find(r => r.dataset.presetId.startsWith('evil'));
              return { name: row.querySelector('.preset-name').textContent, field: pe_xMin.value, prefix: pe_xPrefix.value,
                       markup: presetPanel.querySelectorAll('img, script, b:not(.preset-axis b)').length,
                       owned: window.__owned === undefined };
            })()""")
            check('a preset\'s name and numbers from a file stay text, in its line and its form',
                  evil, {'name': '<img src=x onerror="window.__owned=2">', 'field': '" autofocus onfocus="window.__owned=3" x="',
                         'prefix': '', 'markup': 0, 'owned': True})
            await page.ev("pe_cancel.click(); true")

            # --- the chart hidden -------------------------------------------------
            await page.ev("hideChart(); __wait(200)")
            s = await st(page)
            check('the chart gone, it says so and offers no preset to use',
                  (len(s['empty']), s['cv'], all(r['useOff'] for r in s['rows'])), (1, None, True))
            await page.ev("closePresetManager(); true")
            check('no console errors throughout', page.logs[:3], [])
        finally:
            await page.ev("""(([p, place]) => {
              const put = (k, v) => (v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v));
              put('chartPresets', p); put('kvot-rb-preset-panel', place); return true; })(%s)""" % stored)
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
