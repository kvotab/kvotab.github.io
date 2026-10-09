#!/usr/bin/env python3
"""Ecolego assessments (.eas) opened as files: each run an HDF5 file of its own.

An .eas is a ZIP archive: simulation.xml lists the runs it keeps and what each
saved, and simulation/results/ holds each run's numbers (rb-eas.js has the
format). The assessments here are written by this script, in the two shapes
Ecolego wrote them in (eas_fixtures.py), so nothing that is not ours is in the
repository:

    runs-e6.eas   Ecolego 6: a current run and an archived one, each run's
                  numbers in <GUID>.dta, the index lists named by the run, the
                  first index fastest; outputs of every kind -- not indexed,
                  indexed by one list and by two, a parameter, a transfer (its
                  flux), a sub-system's row, one listed but not kept, one whose
                  numbers do not fit, and one whose name is markup
    old-e5.eas    Ecolego 5: one run in results.dta, written with backslashes,
                  the index lists named only by model.xml, the last index fastest
    prob-e6.eas   a probabilistic run of four realisations

Every value written encodes where it belongs -- the index of each list, the
time, the realisation -- so a value read back from the wrong cell, time or
realisation is a different number. The checks read the HDF5 file the page
wrote, through the page's own h5wasm, and draw it as a reader would: the run
chooser, the tree, a group's chart, a probabilistic series, the Python export.
Damaged and hostile archives are refused with a reason, and nothing in them
reaches the page as markup.

Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-eas.py

Exit status is 0 when every check passes.
"""
import asyncio
import base64
import json
import os
import sys
import tempfile
import urllib.request

import websockets

from driver import open_page
from eas_fixtures import (CROPS, HOSTILE, NUCLIDES, TIMES, archive, bomb, expected, old_e5,
                          prob_e6, runs_e6, value)

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


# --- in the page ---------------------------------------------------------------

WAIT_OPEN = """(async () => {
  for (let i = 0; i < 300; i++) {
    const ask = document.querySelector('.rb-ask');
    if (ask) return 'asked';
    if (document.getElementById('fileLoadTicker').hidden && window.__opened !== fileOrder.join('|')) return 'opened';
    await new Promise(r => setTimeout(r, 100));
  }
  return 'timeout';
})()"""

SETTLE = """(async () => {
  for (let i = 0; i < 300; i++) {
    if (!document.querySelector('.rb-ask') && document.getElementById('fileLoadTicker').hidden) break;
    await new Promise(r => setTimeout(r, 100));
  }
  await new Promise(r => setTimeout(r, 300));
  return fileOrder.slice();
})()"""

# One dataset or group of an open file: its values, shape and attributes.
NODE = """((file, path) => {
  const f = loadedFiles[file];
  if (!f) return 'no file';
  const n = f.get(path);
  if (!n) return null;
  const attrs = {};
  for (const k of Object.keys(n.attrs || {})) {
    const v = n.attrs[k].value;
    attrs[k] = ArrayBuffer.isView(v) ? Array.from(v) : v;
  }
  if (n.type === 'Group') return { group: true, keys: n.keys(), attrs };
  const v = n.value;
  return { shape: n.shape, value: ArrayBuffer.isView(v) || Array.isArray(v) ? Array.from(v) : v, attrs };
})(%s, %s)"""

HELPERS = r"""(() => {
  window.__wait = (ms) => new Promise(r => setTimeout(r, ms));
  window.__row = (path, group) => findTreeItem(path, { extra: group ? '.group' : '', root: document.getElementById('tree') });
  window.__open = async (path) => {
    const t = __row(path, true)?.querySelector('.tree-toggle');
    if (t && t.classList.contains('collapsed')) { t.click(); await __wait(500); }
  };
  window.__click = async (path, group) => {
    const r = __row(path, group);
    if (!r) return false;
    r.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await __wait(2000);
    return true;
  };
  window.__chart = () => {
    const pd = document.getElementById('plotlyChart');
    return { visible: document.getElementById('plotlyChartContainer').classList.contains('visible'),
             names: (pd.data || []).filter(t => t.visible !== false && !t._isCIBand).map(t => t.name),
             y: pd._fullLayout?.yaxis?.title?.text || '' };
  };
  return true;
})()"""


async def node(page, file, path):
    return await page.ev(NODE % (json.dumps(file), json.dumps(path)))


async def pick_files(page, paths):
    await page.ev("window.__opened = fileOrder.join('|'); true")
    doc = await page.send('DOM.getDocument', {})
    found = await page.send('DOM.querySelector', {'nodeId': doc['result']['root']['nodeId'], 'selector': '#fileInput'})
    await page.send('DOM.setFileInputFiles', {'nodeId': found['result']['nodeId'], 'files': paths})
    return await page.ev(WAIT_OPEN, timeout=60)


async def main():
    tmp = tempfile.mkdtemp(prefix='rb-eas-')
    files = {
        'runs-e6.eas': runs_e6(),
        'old-e5.eas': old_e5(),
        'prob-e6.eas': prob_e6(),
        'project.eas': archive([('model.xml', b'<data-model/>')]),
        'bomb.eas': bomb(),
    }
    files['damaged.eas'] = files['runs-e6.eas'][:len(files['runs-e6.eas']) * 3 // 5]
    for name, data in files.items():
        with open(os.path.join(tmp, name), 'wb') as fh:
            fh.write(data)
    at = lambda name: os.path.join(tmp, name)

    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=7)
        try:
            await page.ev(HELPERS)
            check('the file picker offers .eas', '.eas' in (await page.ev(
                "document.getElementById('fileInput').accept")).split(','), True)

            # --- the run chooser ---------------------------------------------
            check('an assessment keeping two runs asks which', await pick_files(page, [at('runs-e6.eas')]), 'asked')
            rows = await page.ev("""[...document.querySelectorAll('.rb-ask .sample-data-item')].map(r =>
                [r.querySelector('.rb-ask-choice').firstChild.textContent, r.querySelector('.rb-ask-detail')?.textContent || '',
                 r.querySelector('input').checked])""")
            check('  every run it kept, all ticked; not the one whose numbers it did not keep',
                  [(r[0], r[2]) for r in rows], [('All runs', True), ('current run', True), ('Base case', True)])
            check('  each said to be deterministic, current or archived',
                  [r[1].split(' · ')[:2] for r in rows[1:]], [['deterministic', 'current'], ['deterministic', 'archived']])
            check('  clearing them all disables Open', await page.ev("""(() => {
                document.querySelector('.rb-ask .rb-ask-all input').click();
                return document.querySelector('.rb-ask .url-btn-load').disabled; })()"""), True)
            await page.ev("""(() => { document.querySelectorAll('.rb-ask .sample-data-item input')[2].click();
                document.querySelector('.rb-ask .url-btn-load').click(); return true; })()""")
            check('  the run picked alone opens, named by the assessment and the run',
                  await page.ev(SETTLE), ['runs-e6.eas · Base case'])
            check('  Cancel opens nothing', (await pick_files(page, [at('runs-e6.eas')]),
                  await page.ev("document.querySelector('.rb-ask .url-btn-cancel').click(), true"),
                  await page.ev(SETTLE)), ('asked', True, ['runs-e6.eas · Base case']))
            await pick_files(page, [at('runs-e6.eas')])
            await page.ev("document.querySelector('.rb-ask .url-btn-load').click(); true")
            check('  all of them, and the one opened before is replaced, not repeated',
                  await page.ev(SETTLE), ['runs-e6.eas · Base case', 'runs-e6.eas · current run'])
            b64 = json.dumps(base64.b64encode(files['runs-e6.eas']).decode())
            check('read again (in VS Code, rewritten on disk), it opens the runs that were open, without asking',
                  await page.ev("""(async (b64) => {
                    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
                    const names = await ingestEcolegoAssessment('runs-e6.eas', bytes.buffer, 'test',
                                                                { reopen: openRunsOf('runs-e6.eas') });
                    return [names, !!document.querySelector('.rb-ask')]; })(%s)""" % b64),
                  [['runs-e6.eas · current run', 'runs-e6.eas · Base case'], False])
            asked = await page.ev("""(async (b64) => {
                const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
                window.__again = ingestEcolegoAssessment('runs-e6.eas', bytes.buffer, 'test', { reopen: ['Gone'] });
                await new Promise(r => setTimeout(r, 500));
                const shown = !!document.querySelector('.rb-ask');
                document.querySelector('.rb-ask .url-btn-cancel')?.click();
                return [shown, await window.__again]; })(%s)""" % b64)
            check('  and asks when none of them is in it any more', asked, [True, []])

            # --- what a run becomes ------------------------------------------
            F = 'runs-e6.eas · current run'
            root = await node(page, F, '/')
            check('the root says what it is', {k: root['attrs'].get(k) for k in
                  ('source', 'assessment', 'run', 'archived', 'simulation type', 'time_unit', 'created_time')},
                  {'source': 'Ecolego 6.0', 'assessment': 'runs-e6.eas', 'run': 'current run', 'archived': 'FALSE',
                   'simulation type': 'DETERMINISTIC', 'time_unit': 'Years',
                   'created_time': await page.ev("easStamp(1700000000000)")})
            check('  and counts what was written and what could not be read',
                  (root['attrs'].get('outputs'), root['attrs'].get('series'), root['attrs'].get('not read')), (7, 18, 1))
            check('  its children: the sub-systems, the lists and the time',
                  sorted(root['keys']), ['Bio', 'IndexLists', 'Sys', 'time'])
            t = await node(page, F, '/time')
            check('/time is the run\'s output times, with their unit', (t['value'], t['attrs'].get('unit')), (TIMES, 'Years'))

            flow = await node(page, F, '/Sys/Flow')
            check('an output not indexed is a dataset of its own', (flow['shape'], flow['value']),
                  ([4], expected(1, [], [], TIMES)))
            check('  saying its unit, that it changes over time, and which block it is',
                  {k: flow['attrs'].get(k) for k in ('unit', 'time_dependent', 'probabilistic', 'block', 'kind')},
                  {'unit': 'm^3/year', 'time_dependent': 'TRUE', 'probabilistic': 'FALSE', 'block': 'Sys.Flow',
                   'kind': 'Expression'})

            inv = await node(page, F, '/Sys/Inventory')
            check('an output indexed by one list is a group of its members', sorted(inv['keys']), sorted(NUCLIDES))
            check('  which says its list, so they are drawn together',
                  {k: inv['attrs'].get(k) for k in ('IndexLists', 'time_dependent', 'unit')},
                  {'IndexLists': ['Radionuclides'], 'time_dependent': 'TRUE', 'unit': 'Bq'})
            check('  each member\'s values are its own',
                  [(await node(page, F, f'/Sys/Inventory/{n}'))['value'] for n in NUCLIDES],
                  [expected(2, [3], [i], TIMES) for i in range(3)])
            check('  and its CSV heading names the block and the member',
                  (await node(page, F, '/Sys/Inventory/I-129'))['attrs'].get('index'), ['Sys.Inventory [I-129]'])

            dose = await node(page, F, '/Bio/Dose_Crops')
            check('indexed by two lists, the nuclide is the leaf: a group per crop', sorted(dose['keys']), CROPS)
            holders = [(await node(page, F, f'/Bio/Dose_Crops/{c}'))['attrs'].get('IndexLists') for c in CROPS]
            check('  every crop\'s group charts its nuclides, not only the last', holders,
                  [['Radionuclides'], ['Radionuclides']])
            check('  each cell where Ecolego 6 put it, the first index fastest',
                  [(await node(page, F, f'/Bio/Dose_Crops/{c}/{n}'))['value'] for c in CROPS for n in NUCLIDES],
                  [expected(3, [3, 2], [i, j], TIMES) for j in range(2) for i in range(3)])

            kd = await node(page, F, '/Sys/Kd/I')
            check('a value that cannot change over the run is one value',
                  (kd['shape'], kd['value'], kd['attrs'].get('time_dependent')), ([1], [value(4, [1], 0)], 'FALSE'))
            leach = await node(page, F, '/Sys/Leach/U-238')
            check('a transfer as Ecolego 6 stored it: its flux, in the unit it was saved with',
                  (leach['value'], leach['attrs'].get('unit'), leach['attrs'].get('kind')),
                  (expected(5, [3], [2], TIMES), 'Bq year^-1', 'Transfer'))
            odd = await node(page, F, '/Sys/Odd')
            check('names HDF5 cannot hold are kept readable: a slash, a lone dot',
                  sorted(odd['keys']), sorted(['A⁄B', '_']))
            check('an output listed but not kept, and one whose numbers do not fit, are not there',
                  (await node(page, F, '/Sys/NotKept'), await node(page, F, '/Sys/Broken')), (None, None))
            lists = await node(page, F, '/IndexLists/Radionuclides')
            check('/IndexLists holds each list used, its members in order', lists['value'], NUCLIDES)
            check('  and only the lists used', sorted((await node(page, F, '/IndexLists'))['keys']),
                  ['Crops', 'Elements', 'Odd', 'Radionuclides'])
            check('a name that is markup is a name', (await node(page, F, '/Sys/' + HOSTILE))['value'],
                  expected(9, [], [], TIMES))

            base = await node(page, 'runs-e6.eas · Base case', '/Sys/Inventory/Cs-137')
            check('the archived run holds its own numbers', base['value'], expected(12, [3], [0], TIMES))
            check('  and says it is archived, under its name',
                  {k: (await node(page, 'runs-e6.eas · Base case', '/'))['attrs'].get(k) for k in ('run', 'archived')},
                  {'run': 'Base case', 'archived': 'TRUE'})

            # --- in the page -------------------------------------------------
            # The current run alone, so the tree is its own.
            await page.ev("(async () => { toggleFileState('runs-e6.eas · Base case'); await __wait(1500); return true; })()")
            await page.ev("(async () => { await __open('/'); await __open('/Sys'); return true; })()")
            check('the tree shows a name that is markup as text', await page.ev("""(() => {
                const row = __row('/Sys/' + %s, false);
                return [!!row, document.querySelectorAll('#tree img').length, typeof window.__ran]; })()"""
                % json.dumps(HOSTILE)), [True, 0, 'undefined'])
            await page.ev("__click('/Sys/Inventory', true)")
            chart = await page.ev('__chart()')
            check('a group of nuclides draws them together, with their total',
                  (chart['visible'], sorted(chart['names'])), (True, sorted(NUCLIDES + ['Total'])))
            check('  its axis in the unit the run saved', chart['y'], 'Inventory (Bq)')
            tip = await page.ev("""(() => {
                const tab = [...document.querySelectorAll('.file-tab')].find(t => t.dataset.file === %s);
                tab.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true, clientX: 100, clientY: 60 }));
                const text = document.getElementById('fileTabTooltip').textContent;
                tab.dispatchEvent(new MouseEvent('mouseleave', { bubbles: true }));
                return text; })()""" % json.dumps(F))
            check('the tab\'s tooltip says which run of which assessment it is',
                  'runs-e6.eas: the current run' in tip and '7 outputs, 18 series; 1 could not be read' in tip, True)

            # --- Python ------------------------------------------------------
            await page.ev("openPythonDialog(); true")
            py = await page.ev("""({ files: (_pythonScript.code.match(/^FILES = .*$/m) || [''])[0],
                                     note: document.getElementById('pythonNote').textContent,
                                     save: [...document.querySelectorAll('#pythonNote .python-save-run')].map(b => b.textContent) })""")
            check('Python reads the run as the HDF5 file it is saved as', py['files'],
                  'FILES = ["runs-e6 - current run.h5"]')
            check('  and the dialog says so, with a button to save it',
                  ('is a run of runs-e6.eas' in py['note'], py['save']), (True, ['Save runs-e6 - current run.h5']))
            saved = await page.ev("""(async () => {
                const keep = [URL.createObjectURL, HTMLAnchorElement.prototype.click];
                let blob = null, name = null;
                URL.createObjectURL = (b) => { blob = b; return 'blob:stub'; };
                HTMLAnchorElement.prototype.click = function () { name = this.download; };
                try { document.querySelector('#pythonNote .python-save-run').click(); }
                finally { [URL.createObjectURL, HTMLAnchorElement.prototype.click] = keep; }
                const a = new Uint8Array(await blob.arrayBuffer()), b = new Uint8Array(loadedFileBuffers[%s]);
                return [name, a.length === b.length && a.every((x, i) => x === b[i])]; })()""" % json.dumps(F))
            check('  which saves the very file the page opened', saved, ['runs-e6 - current run.h5', True])
            await page.ev("closePythonDialog(); true")

            # --- Ecolego 5 ---------------------------------------------------
            check('an assessment keeping one run opens without asking', await pick_files(page, [at('old-e5.eas')]), 'opened')
            await page.ev(SETTLE)
            G = 'old-e5.eas'
            r5 = await node(page, G, '/')
            check('  under the assessment\'s own name, saying which Ecolego wrote it',
                  (G in await page.ev('fileOrder'), r5['attrs'].get('source'), r5['attrs'].get('time_unit')),
                  (True, 'Ecolego 5.0', 'y'))
            check('  each cell where Ecolego 5 put it, the last index fastest',
                  [(await node(page, G, f'/Bio/Dose_Crops/{c}/{n}'))['value'] for c in CROPS for n in NUCLIDES],
                  [expected(3, [3, 2], [i, j], TIMES) for j in range(2) for i in range(3)])
            check('  each cell in its own unit, and each group in its members\'',
                  ((await node(page, G, '/Bio/Dose_Crops/Roots/U-238'))['attrs'].get('unit'),
                   (await node(page, G, '/Bio/Dose_Crops/Roots'))['attrs'].get('unit'),
                   (await node(page, G, '/Bio/Dose_Crops/Cereals'))['attrs'].get('unit')), ('mSv/year', 'mSv/year', 'Sv/year'))
            check('  the lists named as the model names its blocks\', where two lists have the same members',
                  (await node(page, G, '/Sys/Inventory'))['attrs'].get('IndexLists'), ['Radionuclides'])
            check('  a block the model does not name, by the one list with its members',
                  (await node(page, G, '/Sys/CropOnly'))['attrs'].get('IndexLists'), ['Crops'])
            check('  and by a number where no list has them',
                  ((await node(page, G, '/Sys/Mystery'))['attrs'].get('IndexLists'),
                   (await node(page, G, '/IndexLists/Index list 1'))['value']), (['Index list 1'], ['p', 'q']))

            # --- probabilistic -----------------------------------------------
            check('a probabilistic run', await pick_files(page, [at('prob-e6.eas')]), 'opened')
            await page.ev(SETTLE)
            P = 'prob-e6.eas'
            check('  says how many realisations it holds', (await node(page, P, '/'))['attrs'].get('n_iter'), 4)
            cs = await node(page, P, '/Sys/Inventory/I-129')
            check('  a series is time by time, a column per realisation',
                  (cs['shape'], cs['value'], cs['attrs'].get('probabilistic'), cs['attrs'].get('n_iter')),
                  ([3, 4], expected(2, [3], [1], TIMES[:3], S=4), 'TRUE', 4))
            kd = await node(page, P, '/Sys/Kd')
            check('  a varied parameter is one value per realisation',
                  (kd['shape'], kd['value'], kd['attrs'].get('time_dependent')),
                  ([4], [value(4, [], 0, s) for s in range(4)], 'FALSE'))
            check('  the parameters it varied are named on the root',
                  (await node(page, P, '/'))['attrs'].get('simulation inputs'), ['Sys.Kd'])

            # --- by address, under any name ------------------------------------
            by_url = await page.ev("""(async (b64) => {
                const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
                const url = URL.createObjectURL(new Blob([bytes]));
                const name = await ingestHdf5FromUrl(url, 'test');
                await updateTabs(true);
                return [name, loadedFiles[name]?.get('/').attrs.source.value]; })(%s)"""
                % json.dumps(base64.b64encode(files['old-e5.eas']).decode()))
            check('an assessment fetched by address, named as no assessment is, is still read as one',
                  by_url, ['handoff.h5', 'Ecolego 5.0'])

            # --- refused -----------------------------------------------------
            for name, says in [('project.eas', 'it keeps no results'),
                               ('damaged.eas', 'it is not a ZIP archive this page can read'),
                               ('bomb.eas', 'simulation.xml in the archive is damaged')]:
                before = await page.ev('fileOrder.length')
                await pick_files(page, [at(name)])
                await page.ev(SETTLE)
                banner = await page.ev("document.querySelector('#failureBanner .failure-banner-text')?.textContent || ''")
                check(f'{name} is refused, saying why', (says in banner, await page.ev('fileOrder.length')),
                      (True, before))

            expected_errors = ('it keeps no results', 'not a ZIP archive', 'is damaged')
            check('no console errors but the refusals', [m for k, m in page.logs
                  if not any(e in m for e in expected_errors) and 'favicon' not in m][:3], [])
        finally:
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
