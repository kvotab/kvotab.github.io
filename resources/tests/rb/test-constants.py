#!/usr/bin/env python3
"""A multi-selection that mixes time series with values that do not vary over
time: the time chart is drawn, and each such value is a flat line across it.

The chart used to be drawn only when every selected dataset was
time-dependent, so selecting a series together with, say, the parameter that
drives it gave no chart at all (or the parameter's histogram). Now one
time-dependent dataset with a /time in its file is enough, and a value that
does not vary over time is drawn flat across the time the series cover:

  - one value (an HDF5 scalar, or a dataset of one element, which is how
    Kompartment writes a value with time_dependent = FALSE) is drawn at it;
  - one value per realisation (a probabilistic column) is drawn at their mean,
    and the CI, SEM and Show iteration toggles work on it as they do on a
    series, all flat;
  - a string, a table or a value that is not a number is not drawn, and
    neither is a probabilistic column whose length is not the file's n_iter,
    which is not one value per realisation but something else.

The flat line is drawn at every time any series reports, so it covers exactly
the span they do on a linear axis and on a log one (which drops t = 0), and
answers a hover wherever they do. The files are built in the page with h5wasm,
so nothing binary is committed for this.

Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-constants.py

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


def close(a, b, tol=1e-9):
    return len(a) == len(b) and all(abs(x - y) <= tol * max(1, abs(y)) for x, y in zip(a, b))


HELPERS = r"""(() => {
  window.__wait = (ms) => new Promise(r => setTimeout(r, ms));
  window.__build = async (name) => {
    await waitForH5Wasm();
    const { FS, File } = window.h5wasm;
    const path = '/constants-test-' + name + '-' + Date.now() + '.h5';
    const w = new File(path, 'w');
    const put = (g, key, data, shape, attrs = {}) => {
      const d = g.create_dataset({ name: key, data: Float64Array.from(data), shape, dtype: '<f8' });
      for (const [k, v] of Object.entries(attrs)) d.create_attribute(k, v);
      return d;
    };
    try {
      if (name === 'constants.h5') {
        put(w, 'time', [0, 1, 10, 100, 1000, 10000], [6], { unit: 'years' });
        const g = w.create_group('geosphere');
        put(g, 'flux', [5, 6, 7, 8, 9, 10], [6], { unit: 'Bq/year', time_dependent: 'TRUE' });
        put(g, 'k', [3.5], [1], { unit: 'Bq/year', time_dependent: 'FALSE' });
        // An HDF5 scalar with no time_dependent at all, and a distribution.
        put(g, 'c0', [2.25], [], { pdf: JSON.stringify({ type: 'uniform', a: 2, b: 2.5 }) });
        g.create_dataset({ name: 'label', data: 'not a number' });
        put(g, 'table', [1, 2, 3], [3], { time_dependent: 'FALSE' });
        put(g, 'broken', [NaN], [1], { time_dependent: 'FALSE' });
      } else if (name === 'realisations.h5') {
        w.create_attribute('n_iter', 4);
        put(w, 'time', [1, 10, 100], [3], { unit: 'years' });
        // Three times by four realisations, realisations fastest.
        put(w, 'dose', [1, 2, 3, 4, 2, 3, 4, 5, 3, 4, 5, 6], [3, 4],
            { unit: 'Sv/year', time_dependent: 'TRUE', probabilistic: 'TRUE', n_iter: 4 });
        put(w, 'param', [1, 2, 3, 10], [4],
            { unit: 'Sv/year', time_dependent: 'FALSE', probabilistic: 'TRUE', n_iter: 4 });
        // Probabilistic, but three values in a file of four realisations.
        put(w, 'odd', [7, 8, 9], [3], { probabilistic: 'TRUE' });
      } else {
        put(w, 'x', [1, 2, 3], [3], { time_dependent: 'TRUE' });
        put(w, 'k2', [7], [1], { time_dependent: 'FALSE' });
      }
    } finally {
      w.close();
    }
    loadedFileBuffers[name] = FS.readFile(path).slice().buffer;
    loadedFiles[name] = new File(path, 'r');
    fileStates[name] = true;
    if (!fileOrder.includes(name)) fileOrder.push(name);
    await updateTabs(true);
    return fileOrder.slice();
  };
  window.__select = async (items) => {
    EventBus.emit('selection:changed', { mode: 'multi', items });
    await __wait(1500);
  };
  window.__chart = () => {
    const pd = document.getElementById('plotlyChart');
    const box = document.getElementById('plotlyChartContainer');
    const shown = (id) => document.getElementById(id).style.display !== 'none';
    return {
      visible: box.classList.contains('visible'),
      traces: (pd.data || []).map(t => ({
        name: t.name, type: t.type || 'scatter',
        x: t.x ? Array.from(t.x) : [], y: t.y ? Array.from(t.y) : [],
        dash: (t.line || {}).dash || null, hover: t.hovertemplate || '',
        band: t._isCIBand ? 'ci' : t._isSDOMBand ? (t._isSDOMHatch ? 'hatch' : 'sdom') : t._isIterTrace ? 'iter' : null
      })),
      // Where each line is drawn, in pixels: [left, right, height].
      extent: [...pd.querySelectorAll('.scatterlayer .trace')].map(g => {
        const p = g.querySelector('path.js-line');
        if (!p || !p.getAttribute('d')) return null;
        const b = p.getBBox();
        return [Math.round(b.x), Math.round(b.x + b.width), Math.round(b.height)];
      }),
      yTitle: pd.layout && pd.layout.yaxis ? (pd.layout.yaxis.title.text ?? pd.layout.yaxis.title) : null,
      toggles: { ci: shown('showCILabel'), sdom: shown('showSDOMLabel'), iter: shown('showIterLabel'),
                 iterMax: document.getElementById('showIterNum').max }
    };
  };
  window.__preview = () => Object.fromEntries([...document.querySelectorAll('#info .file-data-section')].map(s => {
    const title = s.querySelector('h4').firstChild.textContent.trim();
    const sec = [...s.querySelectorAll('.info-section')]
      .find(x => (x.querySelector('.info-label') || {}).textContent === 'Data Preview');
    return [title, sec ? sec.querySelector('.info-content').textContent : null];
  }));
  window.__hover = (i, j) => {
    const pd = document.getElementById('plotlyChart');
    Plotly.Fx.hover(pd, [{ curveNumber: i, pointNumber: j }]);
    const t = pd.querySelector('.hoverlayer .hovertext');
    return t ? t.textContent : null;
  };
  return true;
})()"""


MISSING = {'name': None, 'x': [], 'y': [], 'dash': None, 'hover': ''}


def spans(chart, n=3):
    # The first n lines' [left, right, height] on screen; one that is not
    # drawn is [None, None, None], so that it fails the checks on it.
    return ([e or [None] * 3 for e in chart['extent']] + [[None] * 3] * n)[:n]


def by_name(chart, name, band=None):
    # A trace that is not there fails the checks on it, rather than the script.
    return next((t for t in chart['traces'] if t['name'] == name and t['band'] == band), MISSING)


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'],
                                  max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=7)
        try:
            await page.ev(HELPERS)
            check('the constants file is built and loaded', await page.ev("__build('constants.h5')"), ['constants.h5'])

            # --- a series and the values beside it, by ctrl-click -------------
            # At a person's pace: each click redraws the chart, and clicks that
            # land before the last drawing has finished each leave their own
            # relayout listeners on the next one, which Plotly warns about.
            await page.ev("""(async () => {
              for (const p of ['flux', 'k', 'c0', 'label', 'table', 'broken']) {
                selectDataset('/geosphere/' + p, { ctrlKey: true, stopPropagation() {} });
                await __wait(600);
              }
              await __wait(1200);
            })()""")
            c = await page.ev('__chart()')
            check('a series with values that do not vary over time gets the time chart', c['visible'])
            check('  the values that are numbers are drawn, in the order they were selected',
                  [t['name'] for t in c['traces']], ['flux', 'k', 'c0'])
            t = [0, 1, 10, 100, 1000, 10000]
            check('  the series is drawn as it was', (by_name(c, 'flux')['x'], by_name(c, 'flux')['y']),
                  (t, [5, 6, 7, 8, 9, 10]))
            check('  a one-element dataset is flat at its value across the time span',
                  (by_name(c, 'k')['x'], by_name(c, 'k')['y']), (t, [3.5] * 6))
            check('  an HDF5 scalar with a pdf is flat at its stored value', by_name(c, 'c0')['y'], [2.25] * 6)
            check('  its hover says it does not vary', 'Not time-dependent' in by_name(c, 'k')['hover'])
            check('  and a hover on it answers', 'Not time-dependent' in (await page.ev('__hover(1, 3)') or ''))
            lines = spans(c)
            check('  on screen the flat lines cover exactly what the series does',
                  [e[:2] for e in lines[1:]], [lines[0][:2]] * 2)
            check('  and are flat', [e[2] for e in lines[1:]], [0, 0])
            check('  the y axis names the unit they share', c['yTitle'], 'Value (Bq/year)')
            check('  and no toggle for realisations is offered', (c['toggles']['ci'], c['toggles']['sdom'], c['toggles']['iter']),
                  (False, False, False))
            p = await page.ev('__preview()')
            check('the panel previews each single value, a one-element dataset too',
                  (p.get('/geosphere/k'), p.get('/geosphere/c0'), p.get('/geosphere/table')), ('3.5', '2.25', None))

            await page.ev("document.querySelector('#xScaleToggle button[data-value=log]').click(); __wait(1200)")
            c = await page.ev('__chart()')
            lines = spans(c)
            check('on a log axis, which drops t = 0, the flat lines still span the series',
                  [e[:2] for e in lines[1:]], [lines[0][:2]] * 2)
            check('  and are drawn at all', all(e[0] is not None and e[1] - e[0] > 100 for e in lines), True)
            await page.ev("document.querySelector('#xScaleToggle button[data-value=linear]').click(); __wait(800)")

            # --- without a series there is still no time chart ---------------
            await page.ev("__select([{ path: '/geosphere/k', fileKey: 'constants.h5' }, { path: '/geosphere/c0', fileKey: 'constants.h5' }])")
            c = await page.ev('__chart()')
            check('values alone still give the histogram of the one with a pdf, not a time chart',
                  (c['visible'], 'histogram' in [t['type'] for t in c['traces']],
                   [t['name'] for t in c['traces'] if t['name'] in ('k', 'c0') and t['type'] == 'scatter']),
                  (True, True, []))
            await page.ev("__select([{ path: '/geosphere/k', fileKey: 'constants.h5' }, { path: '/geosphere/table', fileKey: 'constants.h5' }])")
            check('  and values without one give no chart', (await page.ev('__chart()'))['visible'], False)

            check('a file without /time loads', await page.ev("__build('notime.h5')"), ['constants.h5', 'notime.h5'])
            await page.ev("__select([{ path: '/x', fileKey: 'notime.h5' }, { path: '/k2', fileKey: 'notime.h5' }])")
            check('a series whose file has no /time does not make a time chart', (await page.ev('__chart()'))['visible'], False)

            # --- realisations ------------------------------------------------
            check('the realisations file loads', await page.ev("__build('realisations.h5')"),
                  ['constants.h5', 'notime.h5', 'realisations.h5'])
            await page.ev("__select(['/dose', '/param', '/odd'].map(path => ({ path, fileKey: 'realisations.h5' })))")
            c = await page.ev('__chart()')
            check('a probabilistic series with a probabilistic value gets the time chart,'
                  ' and a column that is not one value per realisation is left out',
                  [t['name'] for t in c['traces']], ['dose', 'param'])
            check('  the series is its mean', by_name(c, 'dose')['y'], [2.5, 3.5, 4.5])
            check('  the value is flat at the mean of its realisations', by_name(c, 'param')['y'], [4, 4, 4])
            check('  and says so on hover', 'Mean of 4 realisations' in by_name(c, 'param')['hover'])
            check('  CI, SEM and Show iteration are all offered, up to realisation 4',
                  c['toggles'], {'ci': True, 'sdom': True, 'iter': True, 'iterMax': '4'})

            await page.ev("(async () => { showCI.checked = true; await toggleShowCI(); })()")
            c = await page.ev('__chart()')
            bands = [t for t in c['traces'] if t['band'] == 'ci'] + [MISSING] * 2
            check('the CI band is drawn for both', len([b for b in bands if b['name']]), 2)
            # 5 % and 95 % of 1, 2, 3, 10 by linear interpolation: 1.15 and 8.95.
            check('  the value\'s band is flat, from its 5th to its 95th percentile',
                  close(bands[1]['y'], [8.95] * 3 + [1.15] * 3), True)
            check('  across the same span', bands[1]['x'], [1, 10, 100, 100, 10, 1])
            await page.ev("(async () => { showCI.checked = false; await toggleShowCI(); })()")

            await page.ev("(async () => { showSDOM.checked = true; await toggleShowSDOM(); })()")
            c = await page.ev('__chart()')
            bands = [t for t in c['traces'] if t['band'] == 'sdom'] + [MISSING] * 2
            # Mean 4, sample standard deviation sqrt(50/3), over sqrt(n_iter = 4).
            sem = (50 / 3) ** 0.5 / 2
            check('the SEM band is flat at mean ± σ/√n_iter', close(bands[1]['y'], [4 + sem] * 3 + [4 - sem] * 3), True)
            await page.ev("(async () => { showSDOM.checked = false; await toggleShowSDOM(); })()")

            await page.ev("showIterNum.value = '4'; toggleShowIteration(); __wait(500)")
            c = await page.ev('__chart()')
            its = {t['name']: t['y'] for t in c['traces'] if t['band'] == 'iter'}
            check('Show iteration draws realisation 4 of each, the value flat at its own number',
                  its, {'Iter. 4 – dose': [4, 5, 6], 'Iter. 4 – param': [10, 10, 10]})
            await page.ev("showIterNum.value = ''; toggleShowIteration(); __wait(300)")

            # --- across files -------------------------------------------------
            await page.ev("__select([{ path: '/geosphere/flux', fileKey: 'constants.h5' }, { path: '/param', fileKey: 'realisations.h5' }])")
            c = await page.ev('__chart()')
            param = next((t for t in c['traces'] if (t['name'] or '').startswith('param')), MISSING)
            check('a value from another file runs across every time the series report',
                  (param['x'], param['y']), (t, [4] * 6))
            check('  in its file\'s line style', param['dash'], 'dash')

            check('no console errors throughout', page.logs[:3], [])
        finally:
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget',
                                       'params': {'targetId': tid}}))
            await bws.recv()

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
