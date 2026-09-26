#!/usr/bin/env python3
"""Large files read lazily, and data compressed with HDF5 filter plugins.

Both are what the HDF Group's myHDF5 (H5Web) does and this page did not.

Compression. A dataset compressed with a filter h5wasm has no decoder for --
LZF here, h5py's own; blosc, zstd and lz4 are the same case -- used to read
as whatever was in memory, with no error on the page: the fixture's first
values came out as 8.8e-308, 0, 4.9e-313, 0. The decoder is now fetched when a
selection needs it, pinned by hash, for a file in memory and for a lazy one.
fixtures/lzf.h5 is made by fixtures/make-lzf.py (h5py).

Lazy files. A file picked from disk at 256 MB or more is opened in a worker
and read as it is looked at (rb-lazy.js). The page's code goes on reading it
synchronously, from what has been fetched: every path when it opens, a
group's children when it is opened, a selection's values before it is drawn.
The check here is that nothing notices: one session -- the tree, a group's
chart, a dataset's, a multi-selection, groups a panel each, a search -- is run
on a file opened lazily and on the same file in memory, and must come out the
same, with nothing read before it was fetched (that would be a warning).

The size rule itself is checked on a stand-in, since a file that size is not
something to commit. Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-lazy.py

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


# Open the fixture the way the page opens a file: in memory, or lazily.
OPEN_FIXTURE = """(async (lazy) => {
  await waitForH5Wasm();
  const bytes = await (await fetch('./resources/tests/rb/fixtures/lzf.h5')).arrayBuffer();
  if (lazy) await ingestHdf5Lazy(new File([bytes], 'lzf.h5'));
  else await ingestHdf5Buffer('lzf.h5', bytes);
  await updateTabs(true);
  return { lazy: !!loadedFiles['lzf.h5'].__lazy };
})(%s)"""

READ_FIXTURE = r"""(async () => {
  const wait = (ms) => new Promise(r => setTimeout(r, ms));
  selectDataset('/x');
  await wait(2500);
  const sec = [...document.querySelectorAll('#info .info-section')]
    .find(s => /Data Preview/.test((s.querySelector('.info-label') || {}).textContent || ''));
  const preview = sec ? sec.querySelector('.info-content').textContent.replace(/\s+/g, ' ') : '';
  const row = findTreeItem('/bio', { extra: '.group', root: document.getElementById('tree') });
  row.click();
  await wait(2500);
  const traces = (document.getElementById('plotlyChart').data || []);
  const cs = traces.find(t => t.name === 'Cs-137');
  return { preview: preview.slice(0, 40), cs: cs ? [cs.y[0], cs.y[cs.y.length - 1]].map(v => Math.round(v * 1e6) / 1e6) : null };
})()"""

# The file the session runs on: two groups that draw a chart, one of them with
# realisations, and a third in another unit.
BUILD = r"""(async (lazy) => {
  await waitForH5Wasm();
  const { FS, File } = window.h5wasm;
  const path = '/lazy-test-' + Date.now() + '.h5';
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
  const bytes = FS.readFile(path).slice();
  FS.unlink(path);
  if (lazy) await ingestHdf5Lazy(new window.File([bytes], 'session.h5'));
  else await ingestHdf5Buffer('session.h5', bytes.buffer);
  await updateTabs(true);
  return { lazy: !!loadedFiles['session.h5'].__lazy };
})(%s)"""

SESSION = r"""(async () => {
  const wait = (ms) => new Promise(r => setTimeout(r, ms));
  const tree = () => document.getElementById('tree');
  const row = (p, kind) => findTreeItem(p, { extra: kind ? '.' + kind : '', root: tree() });
  const click = async (p, kind, ctrl) => {
    row(p, kind).dispatchEvent(new MouseEvent('click', { bubbles: true, ctrlKey: !!ctrl }));
    await wait(2000);
  };
  const chart = () => (document.getElementById('plotlyChart').data || []).map(t => ({
    name: t.name, y: (t.y || []).length, last: t.y && t.y.length ? Math.round(t.y[t.y.length - 1] * 1e6) / 1e6 : null,
    axis: t.yaxis || 'y'
  }));
  const out = {};
  for (const p of ['/', '/bio', '/bio/areaB']) {
    const t = row(p, 'group').querySelector('.tree-toggle');
    if (t.classList.contains('collapsed')) t.click();
    await wait(700);
  }
  out.rows = [...tree().querySelectorAll('.tree-item')].filter(r => r.offsetParent).map(r => r.getAttribute('data-path'));
  await click('/bio/areaA', 'group');
  out.group = chart();
  await click('/bio/areaB/Cs-137', 'dataset');
  out.dataset = chart();
  await click('/bio/areaB/I-129', 'dataset', true);
  out.multi = chart();
  await click('/bio/areaA', 'group');
  await click('/dose', 'group', true);
  out.panels = { labels: (document.getElementById('plotlyChart').layout.annotations || []).map(a => a.text), traces: chart().length };
  out.search = (await asyncFindMatchingPaths(loadedFiles['session.h5'], /I-1/, 50)).sort();
  out.lazy = !!loadedFiles['session.h5'].__lazy;
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
        # --- the size rule --------------------------------------------------
        (rule,), _ = await page_run(bws, """(() => {
          const was = localStorage.getItem('kvot-rb-lazy');
          localStorage.removeItem('kvot-rb-lazy');
          const out = [wantsLazyFile({ size: 256 * 1024 * 1024 - 1 }), wantsLazyFile({ size: 256 * 1024 * 1024 }),
                       wantsLazyFile({ size: 3e9 })];
          localStorage.setItem('kvot-rb-lazy', 'always'); out.push(wantsLazyFile({ size: 10 }));
          localStorage.setItem('kvot-rb-lazy', 'never'); out.push(wantsLazyFile({ size: 3e9 }));
          if (was === null) localStorage.removeItem('kvot-rb-lazy'); else localStorage.setItem('kvot-rb-lazy', was);
          return out;
        })()""")
        check('a file from disk is read lazily from 256 MB, and never a smaller one unless asked',
              rule, [False, True, True, True, False])

        # --- compression ----------------------------------------------------
        for lazy in (False, True):
            how = 'lazily' if lazy else 'in memory'
            (opened, read), logs = await page_run(bws, OPEN_FIXTURE % json.dumps(lazy), READ_FIXTURE)
            check(f'the LZF fixture opens {how}', opened, {'lazy': lazy})
            check(f'  and its LZF data reads as written, not as whatever was in memory',
                  read['preview'].startswith('[ 0, 0.5, 1, 1.5, 2'), True)
            check(f'  a group chart of LZF data draws it right', read['cs'], [0.01, 100.0])
            check(f'  with nothing on the console', logs[:3], [])

        # --- one session, lazily and in memory ------------------------------
        (_, memory), memory_logs = await page_run(bws, BUILD % 'false', SESSION)
        (_, lazy), lazy_logs = await page_run(bws, BUILD % 'true', SESSION)
        check('the session runs on a lazy file and on the same file in memory', (memory['lazy'], lazy['lazy']), (False, True))
        for key in ('rows', 'group', 'dataset', 'multi', 'panels', 'search'):
            check(f'  {key}: the same either way', lazy[key], memory[key])
        check('  the group chart draws both members and their total', [t['name'] for t in lazy['group']], ['Total', 'Cs-137', 'I-129'])
        check('  nothing was read before it was fetched, in memory or lazily', (memory_logs[:3], lazy_logs[:3]), ([], []))

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
