#!/usr/bin/env python3
"""Result files that store the attributes of their datasets on the group only.

skbrnt and sfr-fsar-code write the attributes that the datasets of a result
group share -- time_dependent, probabilistic, unit, columns -- on the group
alone (since October 2026); older files have them on every dataset as well. A
dataset that lacks one of them takes it from its group (getAttrOrGroup in
rb-utils.js), so results written either way are drawn the same.

One session -- a series, a probabilistic series, a summary with statistics
columns and its CI band, and a dataset that is not a series -- is run on the
same results written both ways, each read in memory and lazily, and all four
must come out the same, and as the attributes say. The files are built in the
page with h5wasm, so nothing binary is committed for this.

Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-group-attrs.py

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


# The results, with the attributes of the datasets on them as well (onDatasets)
# or on their groups only, read in memory or lazily. ARGS is replaced by the two.
BUILD = r"""(async (onDatasets, lazy) => {
  await waitForH5Wasm();
  const { FS, File } = window.h5wasm;
  const path = '/group-attrs-' + Date.now() + '.h5';
  const w = new File(path, 'w');
  const results = (parent, names, attrs, members) => {
    let g = parent;
    for (const name of names) g = g.create_group(name);
    g.create_attribute('IndexLists', ['Radionuclides']);
    for (const [k, v] of Object.entries(attrs)) g.create_attribute(k, v);
    for (const [name, data, shape] of members) {
      const d = g.create_dataset({ name, data: Float64Array.from(data), shape, dtype: '<f8' });
      if (onDatasets) for (const [k, v] of Object.entries(attrs)) d.create_attribute(k, v);
    }
  };
  try {
    w.create_attribute('Number of iterations', 3);
    const time = w.create_dataset({ name: 'time', data: Float64Array.from([10, 100, 1000, 10000]), shape: [4], dtype: '<f8' });
    time.create_attribute('unit', 'years');
    w.create_group('IndexLists').create_dataset({ name: 'Radionuclides', data: ['Ni-59', 'C-14'] });
    results(w, ['nearfield', 'R', 'release'], { time_dependent: 'TRUE', probabilistic: 'FALSE', unit: 'Bq/year' },
            [['Ni-59', [1, 2, 3, 4], [4]], ['C-14', [4, 3, 2, 1], [4]]]);
    // Beside the results, a background source with only its own attribute: not one of them, and not a series.
    w.get('nearfield/R/release').create_dataset({ name: '_phase', data: Float64Array.from([100, 10000]), shape: [2], dtype: '<f8' })
      .create_attribute('Index', '["Submerged","Terrestrial"]');
    // Four times by three realisations, realisations fastest.
    results(w, ['farfield', 'R', 'release'], { time_dependent: 'TRUE', probabilistic: 'TRUE', unit: 'Bq/year' },
            [['Ni-59', [1, 2, 3, 2, 4, 6, 3, 6, 9, 4, 8, 12], [4, 3]],
             ['C-14', [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4], [4, 3]]]);
    // A summary of realisations, as the repository sums are: mean, sigma, 5 % and 95 % per time.
    results(w, ['biosphere', 'SFR', 'total'],
            { time_dependent: 'TRUE', probabilistic: 'FALSE', unit: 'Sv/year', columns: ['mean', 'sigma', '5%', '95%'] },
            [['Ni-59', [2, 1, 0.5, 3.5, 4, 2, 1, 7, 6, 3, 1.5, 10.5, 8, 4, 2, 14], [4, 4]]]);
  } finally {
    w.close();
  }
  const bytes = FS.readFile(path).slice();
  FS.unlink(path);
  if (lazy) await ingestHdf5Lazy(new window.File([bytes], 'results.h5'));
  else await ingestHdf5Buffer('results.h5', bytes.buffer);
  await updateTabs(true);
  return { lazy: !!loadedFiles['results.h5'].__lazy };
})(ARGS)"""

SESSION = r"""(async () => {
  const wait = (ms) => new Promise(r => setTimeout(r, ms));
  const round = (v) => v == null ? null : Math.round(v * 1e9) / 1e9;
  const chart = () => {
    const pd = document.getElementById('plotlyChart');
    const shown = (id) => { const el = document.getElementById(id); return !!el && el.style.display !== 'none'; };
    const title = (axis) => pd.layout && pd.layout[axis] ? (pd.layout[axis].title.text ?? pd.layout[axis].title) : null;
    return {
      visible: document.getElementById('plotlyChartContainer').classList.contains('visible'),
      traces: (pd.data || []).map(t => ({ name: t.name, type: t.type || 'scatter', band: t._isCIBand ? 'ci' : null,
                                         y: t.y ? Array.from(t.y).map(round) : [] })),
      xTitle: title('xaxis'), yTitle: title('yaxis'),
      toggles: { ci: shown('showCILabel'), sdom: shown('showSDOMLabel'), iter: shown('showIterLabel') }
    };
  };
  const out = {};
  for (const [key, path] of [['series', '/nearfield/R/release/Ni-59'], ['realisations', '/farfield/R/release/Ni-59'],
                             ['statistics', '/biosphere/SFR/total/Ni-59'], ['notSeries', '/IndexLists/Radionuclides']]) {
    selectDataset(path);
    await wait(2500);
    out[key] = chart();
    if (key === 'statistics') {
      showCI.checked = true;
      await toggleShowCI();
      await wait(800);
      out.statisticsCI = chart().traces.filter(t => t.band === 'ci');
      showCI.checked = false;
      await toggleShowCI();
      await wait(500);
    }
  }
  // Read after the selections, which have loaded these groups of a lazy file.
  out.timeDependent = ['/nearfield/R/release/Ni-59', '/nearfield/R/release/_phase', '/IndexLists/Radionuclides']
    .map(p => isTimeDependent(FileService.get(loadedFiles['results.h5'], p)));
  return out;
})()"""


async def page_run(bws, *steps):
    tid, page = await open_page(bws, settle=7)
    try:
        return [await page.ev(step, timeout=180) for step in steps], page.logs
    finally:
        await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget',
                                   'params': {'targetId': tid}}))
        await bws.recv()


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'],
                                  max_size=200 * 1024 * 1024) as bws:
        runs = {}
        for on_datasets in (True, False):
            for lazy in (False, True):
                key = ('on the datasets' if on_datasets else 'on the groups only') + (', lazily' if lazy else ', in memory')
                (opened, session), logs = await page_run(bws, BUILD.replace('ARGS', f'{json.dumps(on_datasets)}, {json.dumps(lazy)}'), SESSION)
                check(f'the results with their attributes {key} open', opened, {'lazy': lazy})
                check('  with nothing on the console', logs[:3], [])
                runs[key] = session

        reference = runs['on the datasets, in memory']
        for key, session in runs.items():
            if session is not reference:
                for step in ('series', 'realisations', 'statistics', 'statisticsCI', 'notSeries'):
                    check(f'{step}: the same with the attributes {key}', session[step], reference[step])

        for key, session in runs.items():
            series, real, stats = session['series'], session['realisations'], session['statistics']
            check(f'with the attributes {key}: a series is drawn over time, in its unit',
                  (series['visible'], [t['name'] for t in series['traces']], series['traces'][0]['y'] if series['traces'] else None,
                   series['xTitle'], 'Bq/year' in (series['yTitle'] or '')),
                  (True, ['Ni-59'], [1, 2, 3, 4], 'Time (years)', True))
            check('  a probabilistic series is its mean, with CI, SEM and Show iteration offered',
                  (real['traces'][0]['y'] if real['traces'] else None, real['toggles']),
                  ([2, 4, 6, 8], {'ci': True, 'sdom': True, 'iter': True}))
            check('  a summary is drawn at its mean column, in its unit',
                  (stats['traces'][0]['y'] if stats['traces'] else None, 'Sv/year' in (stats['yTitle'] or '')),
                  ([2, 4, 6, 8], True))
            # The band's outline: the 95 % column forwards, then the 5 % one backwards.
            check('  and its CI band runs from the 5 % column to the 95 % one',
                  [t['y'] for t in session['statisticsCI']], [[3.5, 7, 10.5, 14, 2, 1.5, 1, 0.5]])
            check('  a dataset that is not a series is not drawn over time', session['notSeries']['visible'], False)
            check('  a member of a time-dependent group is a series; a background source beside it'
                  ' (_phase) and an index list are not', session['timeDependent'], [True, False, False])

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
