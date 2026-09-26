#!/usr/bin/env python3
"""Several groups selected together, each one a group that draws a chart of
its own, drawn as one chart with a panel each.

Ctrl-click (Cmd on a Mac) on such a group adds it to the groups selected, and
again takes it out. Each panel is drawn as that group's own chart would be, in
the same colour and dash for a member, and one time axis runs under all of
them. The legend lists each line once and shows or hides it in every panel.

Panels whose groups share a unit share a y axis, so what sets the y axis --
lin/log, a preset, auto range on log -- sets them all. A group in another unit
keeps an axis of its own. Show Max and Show Ratio would write one number per
panel into the one legend entry, so they are not offered. A CI band goes in
the panel of the line it belongs to. A folder that draws no chart of its own
is left to the plain click.

While no files are combined, "Same chart" draws the groups in one chart
instead, the way intersect and union draw files: the first group's lines as
its own chart draws them, the others' at half the width and named with what
tells them apart, and Show Ratio across two groups as across two files. With
files combined it is not offered, since a thin line already means the other
file there.

The file is built in the page with h5wasm, so nothing binary is committed.
Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-groups.py

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


# /bio/areaA and /bio/areaB in Bq, B with three realisations; /dose in Sv/year;
# /plain has no IndexLists, so it draws no chart of its own.
BUILD = r"""(async () => {
  await waitForH5Wasm();
  const { FS, File } = window.h5wasm;
  const path = '/groups-' + Date.now() + '.h5';
  const n = 12;
  const t = Float64Array.from({ length: n }, (_, i) => Math.pow(10, 4 * i / (n - 1)));
  const w = new File(path, 'w');
  const put = (g, name, data, shape, attrs) => {
    const d = g.create_dataset({ name, data: Float64Array.from(data), shape, dtype: '<f8' });
    for (const [k, v] of Object.entries(attrs)) d.create_attribute(k, v);
  };
  const nuclides = (g, unit, scale, runs) => {
    g.create_attribute('IndexLists', ['Radionuclides']);
    g.create_attribute('time_dependent', 'TRUE');
    g.create_attribute('unit', unit);
    for (const [nuc, f] of [['Cs-137', 1], ['I-129', 0.3]]) {
      const series = Array.from(t, v => scale * f * v / 1e4);
      if (runs) put(g, nuc, series.flatMap(v => [0.5 * v, v, 2 * v]), [n, 3],
                    { unit, time_dependent: 'TRUE', probabilistic: 'TRUE', n_iter: 3 });
      else put(g, nuc, series, [n], { unit, time_dependent: 'TRUE' });
    }
  };
  try {
    w.create_attribute('n_iter', 3);
    put(w, 'time', t, [n], { unit: 'years' });
    const bio = w.create_group('bio');
    nuclides(bio.create_group('areaA'), 'Bq', 100, false);
    nuclides(bio.create_group('areaB'), 'Bq', 10, true);
    nuclides(w.create_group('dose'), 'Sv/year', 1e-6, false);
    put(w.create_group('plain'), 'x', t, [n], { time_dependent: 'TRUE' });
  } finally {
    w.close();
  }
  const name = 'groups.h5';
  loadedFileBuffers[name] = FS.readFile(path).slice().buffer;
  loadedFiles[name] = new File(path, 'r');
  fileStates[name] = true;
  if (!fileOrder.includes(name)) fileOrder.push(name);
  await updateTabs(true);
  return fileOrder.slice();
})()"""

HELPERS = r"""(() => {
  window.__wait = (ms) => new Promise(r => setTimeout(r, ms));
  window.__row = (path) => findTreeItem(path, { extra: '.group', root: document.getElementById('tree') });
  // A click as the tree gets one, with or without Ctrl.
  window.__click = async (path, ctrl) => {
    __row(path).dispatchEvent(new MouseEvent('click', { bubbles: true, ctrlKey: !!ctrl }));
    await __wait(2500);
  };
  window.__chart = () => {
    const pd = document.getElementById('plotlyChart');
    const fl = pd._fullLayout || {};
    const shown = (id) => document.getElementById(id).style.display !== 'none';
    const axes = Object.keys(fl).filter(k => /^[xy]axis\d*$/.test(k)).sort();
    return {
      visible: document.getElementById('plotlyChartContainer').classList.contains('visible'),
      axes: Object.fromEntries(axes.map(k => [k, {
        type: fl[k].type, matches: fl[k].matches || null, labels: fl[k].showticklabels,
        range: (fl[k].range || []).map(v => Math.round(v * 1000) / 1000),
        domain: (fl[k].domain || []).map(v => Math.round(v * 1000) / 1000),
        title: (fl[k].title && fl[k].title.text) || ''
      }])),
      traces: (pd.data || []).map(t => ({
        name: t.name, x: t.xaxis || 'x', y: t.yaxis || 'y', color: (t.line || {}).color || null,
        dash: (t.line || {}).dash || null, width: (t.line || {}).width || null,
        legend: t.showlegend !== false, group: t.legendgroup || null,
        band: !!(t._isCIBand), exportName: t._exportName || null
      })),
      labels: (pd.layout.annotations || []).map(a => a.text),
      toggles: { max: shown('showMaxLabel'), ratio: shown('showRatioLabel'), total: shown('showTotalLabel'),
                 ci: shown('showCILabel'), overlay: shown('overlayGroupsLabel') },
      marked: [...document.querySelectorAll('#tree .tree-item.group.expanded')].map(r => r.getAttribute('data-path')),
      header: (document.querySelector('#info .info-multi-header') || {}).textContent || null,
      status: (() => { const e = document.getElementById('legendStatus'); return e.style.display === 'none' ? null : e.textContent; })(),
      // `selectedGroups` is new with this feature; without it the checks fail, not the script.
      selected: { path: selectedDatasetPath, isGroup: selectedIsRadionuclidesGroup,
                  groups: (typeof selectedGroups === 'undefined' ? [] : selectedGroups).map(g => g.path) }
    };
  };
  return true;
})()"""


def A(c, axis, field):
    # An axis the chart does not have reads as nothing, and fails the check.
    return c['axes'].get(axis, {}).get(field)


def legend(c):
    return [t['name'] for t in c['traces'] if t['legend'] and not t['band']]


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'],
                                  max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=7)
        try:
            check('the file is built and loaded', await page.ev(BUILD), ['groups.h5'])
            await page.ev(HELPERS)
            await page.ev("(async () => { __row('/').querySelector('.tree-toggle').click(); await __wait(400);"
                          " __row('/bio').querySelector('.tree-toggle').click(); await __wait(600); })()")

            await page.ev("__click('/bio/areaA', false)")
            one = await page.ev('__chart()')
            check('one group is its own chart, as before', ('yaxis2' in one['axes'], one['labels']), (False, []))
            colours = {t['name']: (t['color'], t['dash']) for t in one['traces']}

            # --- two groups -------------------------------------------------
            await page.ev("__click('/bio/areaB', true)")
            c = await page.ev('__chart()')
            check('Ctrl-click on a second group gives a panel each, named, in the order picked',
                  c['labels'], ['/bio/areaA', '/bio/areaB'])
            check('  both are marked in the tree, and the panel says two groups',
                  (sorted(c['marked']), c['header']), (['/bio/areaA', '/bio/areaB'], '📊 2 groups selected'))
            check('  each group\'s lines are in its own panel',
                  sorted({(t['y'], t['name']) for t in c['traces']}),
                  sorted({('y', 'Cs-137'), ('y', 'I-129'), ('y', 'Total'), ('y2', 'Cs-137'), ('y2', 'I-129'), ('y2', 'Total')}))
            check('  drawn in the colour and dash its own chart gives it',
                  all((t['color'], t['dash']) == colours[t['name']] for t in c['traces'] if t['name'] in colours), True)
            check('  one time axis: the second follows the first, and only the bottom one is labelled',
                  (A(c, 'xaxis2', 'matches'), A(c, 'xaxis', 'labels'), A(c, 'xaxis2', 'labels')), ('x', False, True))
            check('  one y scale, since both are in Bq', (A(c, 'yaxis2', 'matches'), A(c, 'yaxis', 'title')), ('y', 'Bq'))
            top, bottom = A(c, 'yaxis', 'domain') or [0, 0], A(c, 'yaxis2', 'domain') or [1, 1]
            check('  the first panel above the second, apart', top[0] > bottom[1], True)
            check('  the legend lists each line once', sorted(legend(c)), ['Cs-137', 'I-129', 'Total'])
            check('  and does not count the copies as lines it has hidden', c['status'], None)
            check('  and a line and its twin in the other panel are one legend group',
                  all(t['group'] == t['name'] for t in c['traces']), True)
            check('  Show Max and Show Ratio are not offered, Show Total is',
                  (c['toggles']['max'], c['toggles']['ratio'], c['toggles']['total']), (False, False, True))
            check('  an export says which panel a line is from',
                  '/bio/areaB: Cs-137' in [t['exportName'] for t in c['traces']], True)

            # --- or in one chart, thick and thin -----------------------------
            check('with no files combined, Same chart is offered', c['toggles']['overlay'], True)
            await page.ev("(async () => { overlayGroups.click(); await __wait(2500); })()")
            c = await page.ev('__chart()')
            check('Same chart draws both groups on one pair of axes', ('yaxis2' in c['axes'], c['labels']), (False, []))
            check('  whose title names neither group alone', A(c, 'yaxis', 'title'), 'Value (Bq)')
            names = [t['name'] for t in c['traces']]
            check('  the first group\'s lines named as its own chart names them, the second\'s with what tells it apart',
                  sorted(names), sorted(['Total', 'Cs-137', 'I-129', 'Total (areaB)', 'Cs-137 (areaB)', 'I-129 (areaB)']))
            width = {t['name']: t['width'] for t in c['traces']}
            check('  the second group\'s lines half as wide as the first\'s',
                  [width[f'{k} (areaB)'] * 2 == width[k] for k in ('Total', 'Cs-137', 'I-129')], [True] * 3)
            check('  in the colour and dash of the member',
                  all((t['color'], t['dash']) == colours[t['name'].split(' (')[0]] for t in c['traces']), True)
            check('  Show Ratio is offered for two groups, Show Max too',
                  (c['toggles']['ratio'], c['toggles']['max'], c['toggles']['overlay']), (True, True, True))
            await page.ev("(async () => { showRatio.click(); await __wait(2500); })()")
            c = await page.ev('__chart()')
            # areaA peaks at 100 and 30 Bq, total 130; areaB's mean at 11.67 and 3.5, total 15.17.
            check('  Show Ratio puts the first group\'s maximum over the second\'s in the thick line\'s name',
                  sorted(legend(c)), ['Cs-137 (8.57)', 'I-129 (8.57)', 'Total (8.57)'])
            check('  and takes the thin lines out of the legend, drawn still, and Show Max away',
                  (len(c['traces']), c['toggles']['max']), (6, False))
            await page.ev("(async () => { showRatio.click(); await __wait(2000); overlayGroups.click(); await __wait(2500); })()")
            c = await page.ev('__chart()')
            check('unticked, the groups are panels again', c['labels'], ['/bio/areaA', '/bio/areaB'])

            await page.ev("(async () => { showCI.click(); await __wait(1200); })()")
            c = await page.ev('__chart()')
            bands = [t for t in c['traces'] if t['band']]
            check('a CI band goes in the panel of the line it belongs to',
                  (len(bands) > 0, {(t['x'], t['y']) for t in bands}), (True, {('x2', 'y2')}))
            await page.ev("(async () => { showCI.click(); await __wait(800); })()")

            await page.ev("(async () => { document.querySelector('#yScaleToggle button[data-value=log]').click(); await __wait(1500); })()")
            c = await page.ev('__chart()')
            check('log y turns every panel to log', (A(c, 'yaxis', 'type'), A(c, 'yaxis2', 'type')), ('log', 'log'))
            check('  on whole decades, shared', A(c, 'yaxis', 'range') == [round(v) for v in (A(c, 'yaxis', 'range') or [0.5])], True)

            await page.ev("(async () => { await Plotly.relayout('plotlyChart', { 'xaxis.range': [1, 2] }); await __wait(800); })()")
            c = await page.ev('__chart()')
            check('zoomed, the dynamic legend still lists a line once', len(legend(c)) == len(set(legend(c))), True)
            await page.ev("(async () => { await applyPresetById('default'); await __wait(800); })()")

            # --- a third, in another unit -----------------------------------
            await page.ev("__click('/dose', true)")
            c = await page.ev('__chart()')
            check('a group in another unit is a third panel with a y axis of its own',
                  (c['labels'], A(c, 'yaxis3', 'matches'), A(c, 'yaxis3', 'title')),
                  (['/bio/areaA', '/bio/areaB', '/dose'], None, 'Sv/year'))
            check('  while the two in Bq go on sharing theirs',
                  (A(c, 'yaxis2', 'matches'), A(c, 'yaxis2', 'range') == A(c, 'yaxis', 'range')), ('y', True))
            check('  auto range fits it on its own, twelve decades below the others\' top at most',
                  (A(c, 'yaxis3', 'type'), (A(c, 'yaxis3', 'range') or [0, 0])[1] < (A(c, 'yaxis', 'range') or [0, 0])[1] - 3),
                  ('log', True))

            await page.ev("__click('/bio/areaA', true)")
            c = await page.ev('__chart()')
            check('Ctrl-click on a selected group takes it out again', c['labels'], ['/bio/areaB', '/dose'])

            await page.ev("__click('/plain', true)")
            c = await page.ev('__chart()')
            check('a folder without a chart of its own is selected as a plain click would',
                  (c['selected']['path'], c['selected']['groups'], c['marked']), ('/plain', [], ['/plain']))

            await page.ev("__click('/bio/areaB', true)")
            await page.ev("__click('/dose', true)")
            c = await page.ev('__chart()')
            check('Ctrl-clicks start a selection of groups again from there', c['labels'], ['/bio/areaB', '/dose'])
            await page.ev("__click('/bio/areaA', false)")
            c = await page.ev('__chart()')
            check('a plain click on a group is that group\'s chart alone',
                  ('yaxis2' in c['axes'], c['labels'], c['selected']['groups']), (False, [], []))

            await page.ev("(async () => { document.querySelector('#yScaleToggle button[data-value=linear]').click(); await __wait(800); })()")

            # --- with files combined ------------------------------------------
            check('a second file loads', await page.ev(BUILD.replace("const name = 'groups.h5';", "const name = 'groups-b.h5';")),
                  ['groups.h5', 'groups-b.h5'])
            await page.ev("""(async () => {
              document.querySelector('#treeModeContainer button[data-value="union"]').click();
              await __wait(3500);
              for (const p of ['/', '/bio']) {
                const t = __row(p).querySelector('.tree-toggle');
                if (t.classList.contains('collapsed')) t.click();
                await __wait(700);
              }
              if (!overlayGroups.checked) overlayGroups.checked = true;   // asked for, and not given
            })()""")
            await page.ev("__click('/bio/areaA', true)")
            await page.ev("__click('/bio/areaB', true)")
            c = await page.ev('__chart()')
            check('in the union the groups are panels, and Same chart is not offered, ticked or not',
                  (c['labels'], c['toggles']['overlay']), (['/bio/areaA', '/bio/areaB'], False))
            thin = [t for t in c['traces'] if t['y'] == 'y' and t['name'] != (t['name'].split(' (')[0])]
            check('  since in each panel the second file is the thin line', len(thin) > 0 and all(
                t['width'] * 2 == width[t['name'].split(' (')[0]] for t in thin), True)

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
