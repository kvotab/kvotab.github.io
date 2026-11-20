#!/usr/bin/env python3
"""The Total of a group of statistics from the _total_ the group carries.

The summed (SFR) result files keep each radionuclide as a table of statistics
(columns mean, sigma, 5 %, 95 %) and, since 2026-11-20, their sum over the
radionuclides as _total_ with the same columns, taken over the sums of each
iteration. Only means add up, so the Total the chart adds up from the
radionuclides' lines has no band; with _total_ it is drawn from _total_, with
its CI and SEM bands, and the Python export reads it from there too. A group
without _total_ (a file summed before) keeps the sum of the lines, and
_total_ and _total_iterations_ are never drawn as lines of their own.

The file is built in the page with h5wasm, so nothing binary is committed.
Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-saved-total.py

Exit status is 0 when every check passes.
"""
import asyncio
import json
import math
import sys
import urllib.request

import websockets

from driver import open_page

failures = []
checks = 0
N_ITER = 1000


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


def close(a, b, rel=1e-6):
    """The same numbers, to the float32 precision the chart holds them in."""
    return len(a) == len(b) and all(abs(x - y) <= rel * max(abs(x), abs(y), 1e-300) for x, y in zip(a, b))


N = 12
TIMES = [10 ** (4 * i / (N - 1)) for i in range(N)]
# Each radionuclide's rows: mean, sigma, 5 %, 95 %
RNS = {'Cs-137': 1.0, 'I-129': 0.3}
ROWS = {rn: [[f * t, 0.5 * f * t, 0.2 * f * t, 2.0 * f * t] for t in TIMES] for rn, f in RNS.items()}
# The statistics of the sums of each iteration: the mean adds up, the rest does not
TOTAL = [[1.3 * t, 0.6 * t, 0.4 * t, 2.2 * t] for t in TIMES]

BUILD = r"""(async () => {
  await waitForH5Wasm();
  const { FS, File } = window.h5wasm;
  const path = '/saved-total-' + Date.now() + '.h5';
  const t = %(times)s, rows = %(rows)s, total = %(total)s, n = t.length;
  const w = new File(path, 'w');
  const put = (g, name, data, shape, attrs) => {
    const d = g.create_dataset({ name, data: Float64Array.from(data), shape, dtype: '<f8' });
    for (const [k, v] of Object.entries(attrs)) d.create_attribute(k, v);
  };
  const columns = ['mean', 'sigma', '5%%', '95%%'];
  // A group as the summed files have it: the attributes on the group, the radionuclides' tables bare
  const statistics = (g, withTotal) => {
    g.create_attribute('IndexLists', ['Radionuclides']);
    g.create_attribute('time_dependent', 'TRUE');
    g.create_attribute('probabilistic', 'FALSE');
    g.create_attribute('unit', 'Bq/year');
    g.create_attribute('columns', columns);
    for (const [nuc, table] of Object.entries(rows)) put(g, nuc, table.flat(), [n, 4], {});
    if (withTotal) {
      put(g, '_total_', total.flat(), [n, 4],
          { Name: 'Total', columns, time_dependent: 'TRUE', probabilistic: 'FALSE', unit: 'Bq/year' });
      put(g, '_total_iterations_', total.flatMap(r => [0.5 * r[0], r[0], 1.5 * r[0]]), [n, 3],
          { Name: 'Total', time_dependent: 'TRUE', probabilistic: 'TRUE', unit: 'Bq/year' });
    }
  };
  try {
    w.create_attribute('Number of iterations', %(n_iter)d);
    put(w, 'time', t, [n], { unit: 'years' });
    statistics(w.create_group('new'), true);
    statistics(w.create_group('old'), false);
  } finally {
    w.close();
  }
  const name = 'saved-total.h5';
  loadedFileBuffers[name] = FS.readFile(path).slice().buffer;
  loadedFiles[name] = new File(path, 'r');
  fileStates[name] = true;
  if (!fileOrder.includes(name)) fileOrder.push(name);
  await updateTabs(true);
  return fileOrder.slice();
})()""" % {'times': json.dumps(TIMES), 'rows': json.dumps(ROWS), 'total': json.dumps(TOTAL), 'n_iter': N_ITER}

HELPERS = r"""(() => {
  window.__wait = (ms) => new Promise(r => setTimeout(r, ms));
  window.__row = (path) => findTreeItem(path, { extra: '.group', root: document.getElementById('tree') });
  window.__click = async (path) => {
    __row(path).dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await __wait(2500);
  };
  window.__toggle = async (id, on) => {
    const box = document.getElementById(id);
    if (box.checked !== on) { box.checked = on; box.dispatchEvent(new Event('change', { bubbles: true })); }
    await __wait(1200);
  };
  window.__chart = () => {
    const data = document.getElementById('plotlyChart').data || [];
    const arr = (a) => Array.isArray(a) ? a.slice() : (a && a.length !== undefined ? Array.from(a) : null);
    const total = data.find(t => t.name === 'Total') || null;
    // The lines the bands belong to (an SEM band's hatching names none, its fill does)
    const lineOf = (band) => (data.find(l => l._bandKey === band._bandOf) || {}).name || null;
    return {
      names: data.filter(t => !t._isCIBand && !t._isSDOMBand).map(t => t.name),
      ciBands: data.filter(t => t._isCIBand).map(lineOf),
      semBands: data.filter(t => t._isSDOMBand && t._bandOf).map(lineOf),
      total: total && {
        y: arr(total.y), ciP5: arr(total._ciP5), ciP95: arr(total._ciP95),
        semLower: arr(total._sdomLower), semUpper: arr(total._sdomUpper),
        py: total._py ? { yPath: total._py.y && total._py.y.path, ci: !!total._py.ciCols,
                          sem: !!total._py.semCols, sum: !!total._py.total } : null
      }
    };
  };
  return true;
})()"""


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=7)
        try:
            check('the file is built and loaded', await page.ev(BUILD), ['saved-total.h5'])
            await page.ev(HELPERS)
            await page.ev("(async () => { __row('/').querySelector('.tree-toggle').click(); await __wait(600); })()")
            sem = 1 / math.sqrt(N_ITER)

            # --- a group with _total_ ------------------------------------------
            await page.ev("__click('/new')")
            c = await page.ev('__chart()')
            check('the lines are the radionuclides and the Total; _total_ and _total_iterations_ are not drawn',
                  sorted(c['names']), ['Cs-137', 'I-129', 'Total'])
            t = c['total'] or {}
            check('  the Total is _total_\'s mean', close(t.get('y') or [], [r[0] for r in TOTAL]))
            check('  its CI band is _total_\'s 5 % and 95 %',
                  (close(t.get('ciP5') or [], [r[2] for r in TOTAL]), close(t.get('ciP95') or [], [r[3] for r in TOTAL])),
                  (True, True))
            check('  its SEM band is _total_\'s mean -/+ sigma / sqrt(n_iter)',
                  (close(t.get('semLower') or [], [r[0] - r[1] * sem for r in TOTAL]),
                   close(t.get('semUpper') or [], [r[0] + r[1] * sem for r in TOTAL])), (True, True))
            check('  the Python export reads it from _total_, with both bands',
                  t.get('py'), {'yPath': '/new/_total_', 'ci': True, 'sem': True, 'sum': False})
            await page.ev("__toggle('showCI', true)")
            c = await page.ev('__chart()')
            check('  Show CI draws a band for the Total as for each radionuclide',
                  sorted(c['ciBands']), ['Cs-137', 'I-129', 'Total'])
            await page.ev("__toggle('showSDOM', true)")
            check('  and Show SEM', sorted((await page.ev('__chart()'))['semBands']), ['Cs-137', 'I-129', 'Total'])
            await page.ev("__toggle('showSDOM', false)")
            await page.ev("__toggle('showCI', false)")

            # --- a group without _total_ (summed before 2026-11-20) -------------
            await page.ev("__click('/old')")
            c = await page.ev('__chart()')
            t = c['total'] or {}
            check('without _total_ the Total is the sum of the radionuclides\' means, as before',
                  close(t.get('y') or [], [sum(ROWS[rn][i][0] for rn in RNS) for i in range(N)]))
            check('  and has no band of its own, nor a Python recipe other than the sum',
                  (t.get('ciP5'), t.get('semLower'), (t.get('py') or {}).get('sum')), (None, None, True))
            await page.ev("__toggle('showCI', true)")
            await page.ev("__toggle('showSDOM', true)")
            c = await page.ev('__chart()')
            check('  Show CI and Show SEM draw the radionuclides\' bands only',
                  (sorted(c['ciBands']), sorted(c['semBands'])), (['Cs-137', 'I-129'], ['Cs-137', 'I-129']))
            await page.ev("__toggle('showSDOM', false)")
            await page.ev("__toggle('showCI', false)")

            errors = [m for kind, m in page.logs if kind in ('error', 'exception') and 'favicon' not in m.lower()]
            check('no errors in the console', errors, [])
        finally:
            await bws.send(json.dumps({'id': 99, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))
    print(f'\n{checks - len(failures)} of {checks} checks pass')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
