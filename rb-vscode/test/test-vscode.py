#!/usr/bin/env python3
"""The HDF5 Browser extension in a real VS Code: what the site does not have.

characterise-vscode.py shows the page behaves inside VS Code as it does on
the site. This covers what is the extension's own:

  * opening: read whole, read lazily (the extension host's reader), a file
    past 2 GiB, a compressed one both ways, an empty one, and a file dropped
    into the page, which the page's own worker reads;
  * the webview frame: workers, the CDN copies, the policy (nothing blocked,
    nothing logged), VS Code's theme followed as it changes;
  * the header: the file toolbar alone, every tab standing on its line, Add
    Files and the light/dark toggle at the right; the toggle's choice kept in
    hdf5Browser.theme, followed by every view, and undone by toggling back;
  * what needs VS Code's dialogs: Save (CSV, Excel, presets) and Add Files;
    and the preset name, asked in the page since prompt() shows nothing here;
  * Open Together with two files of the same name, and a file rewritten on
    disk being read again;
  * the channel: the page cannot reach a file by a token it was not given.

A big file is made with h5py when it is installed (a hole, so it costs no
disk); without h5py those checks are skipped and say so.

    python3 rb-vscode/test/test-vscode.py

RB_VSCODE_EXE names a VS Code to use; otherwise @vscode/test-electron
downloads one (npm install in rb-vscode first). Exit status 0 when every
check passes.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from vscode_driver import VSCode  # noqa: E402

FIXTURES = os.path.join(HERE, '..', '..', 'resources', 'tests', 'rb', 'fixtures')
GROUP = '/biosphere/vault_A/mire/total'

# Where the header's parts stand, in px: every tab-like thing on its bottom line.
HEADER = """(() => {
  const h = document.querySelector('header');
  const line = h.getBoundingClientRect().bottom - parseFloat(getComputedStyle(h).borderBottomWidth);
  const inner = h.getBoundingClientRect().right - parseFloat(getComputedStyle(h).paddingRight);
  const box = sel => document.querySelector(sel).getBoundingClientRect();
  return {
    logo: !!h.querySelector('.logo, svg'), title: !!h.querySelector('.title'),
    tab: +(line - box('.file-tab').bottom).toFixed(1),
    add: +(line - box('.add-file-btn').bottom).toFixed(1),
    toggle: +(line - box('.rb-theme-toggle').bottom).toFixed(1),
    toggleInset: +(inner - box('.rb-theme-toggle').right).toFixed(1),
    addToToggle: +(box('.rb-theme-toggle').left - box('.add-file-btn').right).toFixed(1),
    tabStart: +(box('.file-tab').left - h.getBoundingClientRect().left).toFixed(1)
  };
})()"""

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


def fixture(name):
    return os.path.abspath(os.path.join(FIXTURES, name))


def make_big(path):
    """A file past 2 GiB whose objects sit past 2 GiB, as a hole: nearly no disk."""
    try:
        import h5py
        import numpy as np
    except ImportError:
        return False
    fid = h5py.h5f.create(path.encode(), h5py.h5f.ACC_TRUNC)
    dcpl = h5py.h5p.create(h5py.h5p.DATASET_CREATE)
    dcpl.set_alloc_time(h5py.h5d.ALLOC_TIME_EARLY)
    dcpl.set_fill_time(h5py.h5d.FILL_TIME_NEVER)
    h5py.h5d.create(fid, b'hole', h5py.h5t.IEEE_F64LE, h5py.h5s.create_simple((300_000_000,)), dcpl=dcpl)
    with h5py.File(fid) as f:
        t = np.logspace(0, 4, 50)
        f.create_dataset('time', data=t).attrs['unit'] = 'years'
        f.create_group('bio').create_dataset('Cs-137', data=t / 100, compression='lzf', chunks=(25,))
    return True


async def wait_for(page, expr, want, seconds=10):
    got = None
    for _ in range(int(seconds / 0.2)):
        got = await page.ev(expr)
        if got == want:
            break
        await asyncio.sleep(0.2)
    return got


async def setting_becomes(vs, key, want, seconds=10):
    got = None
    for _ in range(int(seconds / 0.2)):
        got = vs.command('getSetting', section='hdf5Browser', key=key)
        if got == want:
            break
        await asyncio.sleep(0.2)
    return got


async def opened(vs, since, what, timeout=180):
    return vs.wait_event(lambda e: e['type'] == 'status' and e.get('kind') == 'opened', timeout, what, since=since)


async def main():
    work = tempfile.mkdtemp(prefix='rbv-files-')
    vs = VSCode().start()
    page = None
    try:
        # --- a file read whole ---------------------------------------------
        m = vs.mark()
        vs.command('open', paths=[fixture('sample-a.h5')])
        st = await opened(vs, m, 'sample-a.h5 to open')
        check('a small file opens, read whole', st['opened'], [{'name': 'sample-a.h5', 'mode': 'whole'}])
        page = await vs.page()
        s = await page.ev("""(() => ({
          buttons: [...document.querySelectorAll('header button')].map(b => b.textContent.trim()).filter(Boolean),
          theme: document.documentElement.getAttribute('data-theme'),
          workers: Object.keys(window.KVOT_VSCODE_WORKER_SOURCES).sort()
        }))()""")
        check('the header has Add Files and no URL or Sample Data', 'Add Files' in s['buttons'] and not any('URL' in b or 'Sample' in b for b in s['buttons']))
        check('the page is drawn in VS Code\'s theme (dark)', s['theme'], 'dark')
        await page.ev("(async () => { await expandAndLoadPath('sample-a.h5', %s); findTreeItem(%s, { extra: '.group' }).click();"
                      " await new Promise(r => setTimeout(r, 3500)); return true; })()" % (json.dumps(GROUP), json.dumps(GROUP)))
        traces = await page.ev("(document.getElementById('plotlyChart').data || []).length")
        check('a radionuclide group draws its chart', traces >= 9)

        # --- saving goes through VS Code -----------------------------------
        m = vs.mark()
        await page.ev("downloadChartData(); true")
        saved = vs.wait_event(lambda e: e['type'] == 'saved', 30, 'the CSV to be saved', since=m)
        with open(saved['path']) as fh:
            head = fh.read(200)
        check('Download CSV is saved by the extension', (os.path.basename(saved['path']).endswith('.csv'), head.startswith('Series,X,Y')), (True, True))
        m = vs.mark()
        # The chart's own button, as a reader clicks it: its handler is in rb-init.js.
        await page.ev("EventBus.emit('toolbar:download-excel'); true")
        saved = vs.wait_event(lambda e: e['type'] == 'saved', 30, 'the workbook to be saved', since=m)
        with zipfile.ZipFile(saved['path']) as z:
            check('  and Excel too, from the chart\'s button: a workbook with the chart in it',
                  (saved['path'].endswith('.xlsx'), 'xl/charts/chart1.xml' in z.namelist()), (True, True))
        m = vs.mark()
        await page.ev("exportPresets(); true")
        saved = vs.wait_event(lambda e: e['type'] == 'saved', 30, 'the presets to be saved', since=m)
        with open(saved['path']) as fh:
            check('  and the presets, as JSON', isinstance(json.load(fh), list))

        # --- the preset name is asked in the page ---------------------------
        await page.ev("saveCurrentAsPreset(); true")
        await page.ev("new Promise(r => setTimeout(r, 300))")
        check('Save preset asks in the page (prompt() shows nothing in a webview)',
              await page.ev("!!document.querySelector('.rb-ask input')"))
        await page.ev("(() => { const i = document.querySelector('.rb-ask input'); i.value = 'In VS Code';"
                      " document.querySelector('.rb-ask .url-btn-load').click(); return true; })()")
        check('  and saves it', await page.ev("loadPresets().some(p => p.name === 'In VS Code')"))

        # --- VS Code's theme, followed --------------------------------------
        vs.command('setting', section='workbench', key='colorTheme', value='Default Light Modern')
        theme = None
        for _ in range(50):
            theme = await page.ev("document.documentElement.getAttribute('data-theme')")
            if theme == 'light':
                break
            await asyncio.sleep(0.2)
        check('switching VS Code to a light theme switches the page', theme, 'light')
        vs.command('setting', section='workbench', key='colorTheme', value='Default Dark Modern')
        await wait_for(page, "document.documentElement.getAttribute('data-theme')", 'dark')

        # --- the header: the file toolbar alone, on its line -----------------
        h = await page.ev(HEADER)
        check('the header has no logo and no page name', (h['logo'], h['title']), (False, False))
        check('  so the first tab starts at its left edge', h['tabStart'] <= 8)
        check('the file tabs stand on the header\'s line, with no gap', abs(h['tab']) <= 0.5)
        check('  and Add Files and the light/dark toggle do too', (abs(h['add']) <= 0.5, abs(h['toggle']) <= 0.5), (True, True))
        check('the toggle is at the right end, Add Files just before it', (h['toggleInset'] <= 1, 0 <= h['addToToggle'] <= 8), (True, True))

        # --- the light/dark toggle: kept in the setting ----------------------
        await page.ev("document.querySelector('.rb-theme-toggle').click(); true")
        theme = await wait_for(page, "document.documentElement.getAttribute('data-theme')", 'light')
        check('the toggle switches the page to light', theme, 'light')
        check('  and keeps it in hdf5Browser.theme', await setting_becomes(vs, 'theme', 'light'), 'light')
        check('  and the chart is redrawn light (rb recolours on data-theme)',
              await wait_for(page, "document.getElementById('plotlyChart').layout.plot_bgcolor", '#ffffff'), '#ffffff')
        await page.ev("document.querySelector('.rb-theme-toggle').click(); true")
        theme = await wait_for(page, "document.documentElement.getAttribute('data-theme')", 'dark')
        check('toggling back to VS Code\'s own theme follows VS Code again (auto)',
              (theme, await setting_becomes(vs, 'theme', 'auto')), ('dark', 'auto'))

        # --- Add Files: VS Code's open dialog, answered by the test ---------
        vs.command('nextPick', paths=[fixture('sample-b.h5')])
        m = vs.mark()
        await page.ev("document.querySelector('.add-file-btn').click(); true")
        st = await opened(vs, m, 'the added file')
        check('Add Files adds the chosen file to this view', (st['why'], [f['name'] for f in st['opened']]), ('added', ['sample-b.h5']))
        check('  next to the first', await page.ev("fileOrder.slice()"), ['sample-a.h5', 'sample-b.h5'])

        # --- a file dropped into the page: the page's own lazy worker -------
        r = await page.ev("""(async () => {
          localStorage.setItem('kvot-rb-lazy', 'always');
          try {
            const file = new File([loadedFileBuffers['sample-a.h5']], 'dropped.h5');
            await ingestHdf5Lazy(file, 'test');
            const st = loadedFiles['dropped.h5'].__lazy;
            await st.ensureGroup('/'); await st.ensureValues(['/time']);
            return { paths: st.paths.length, time: Array.from(loadedFiles['dropped.h5'].get('time').value.slice(0, 2)) };
          } finally { localStorage.removeItem('kvot-rb-lazy'); }
        })()""")
        check('a file dropped in the page is read by the page\'s worker', isinstance(r, dict) and r['paths'] == 17 and len(r['time']) == 2, True)

        # --- the channel ------------------------------------------------------
        r = await page.ev("KvotVscodeHost.lazy('not-a-token', 'open', {}).then(() => 'answered', e => e.message)")
        check('a token this view was not given reaches nothing', r, 'that file is not open in this view')
        await page.close()
        page = None

        # --- read lazily: the extension host's reader -----------------------
        vs.command('setting', section='hdf5Browser', key='readLazily', value='always')
        m = vs.mark()
        vs.command('open', paths=[fixture('lzf.h5')], own=True)   # its own view; test-drop.py covers where files go
        st = await opened(vs, m, 'lzf.h5 to open lazily')
        check('with readLazily always, a file is read by the reader', st['opened'], [{'name': 'lzf.h5', 'mode': 'lazy'}])
        page = await vs.page()
        x = await page.ev("(async () => { const st = loadedFiles['lzf.h5'].__lazy; await st.ensureGroup('/'); await st.ensureValues(['/x']);"
                          " return Array.from(loadedFiles['lzf.h5'].get('x').value.slice(0, 4)); })()")
        check('  and LZF data is decoded there (the plugin, in Node)', x, [0, 0.5, 1, 1.5])
        r = await page.ev("loadedFiles['lzf.h5'].__lazy.call('values', { fid: 999, paths: ['/x'] }).then(() => 'answered', e => e.message)")
        check('  and answers only for what it opened for this view (a handle it never gave)', r, 'that file is not open in this view')
        r = await page.ev("loadedFiles['lzf.h5'].__lazy.call('unlink', { fid: 1 }).then(() => 'answered', e => e.message)")
        check('  and only the four questions the page asks', r, 'unknown command unlink')

        # The toggle in one view switches every view (sample-a.h5's is still open).
        first = await vs.page_for('sample-a.h5')
        await page.ev("document.querySelector('.rb-theme-toggle').click(); true")
        check('the toggle in one view switches the others too',
              await wait_for(first, "document.documentElement.getAttribute('data-theme')", 'light'), 'light')
        await first.close()
        await page.close()
        page = None

        vs.command('setting', section='hdf5Browser', key='readLazily', value='never')
        m = vs.mark()
        vs.command('together', paths=[fixture('lzf.h5'), fixture('sample-a.h5')])
        # lzf.h5 is open already, lazily, in its own view: Open Together adds sample-a.h5 to it.
        st = await opened(vs, m, 'sample-a.h5 to be added')
        check('Open Together on an open file adds the rest to its view', [f['name'] for f in st['opened']], ['sample-a.h5'])
        vs.command('closeAll')

        lzf_copy = os.path.join(work, 'copy', 'lzf.h5')
        os.makedirs(os.path.dirname(lzf_copy))
        shutil.copy(fixture('lzf.h5'), lzf_copy)
        m = vs.mark()
        vs.command('open', paths=[lzf_copy])
        st = await opened(vs, m, 'lzf.h5 to open whole')
        page = await vs.page()
        x = await page.ev("(async () => { await rbPrepareSelection({ mode: 'single', path: '/x' });"
                          " return Array.from(loadedFiles['lzf.h5'].get('x').value.slice(0, 4)); })()")
        check('read whole, LZF data is decoded in the page (the plugin through the CDN copy)', (st['opened'][0]['mode'], x), ('whole', [0, 0.5, 1, 1.5]))
        check('a view opened later starts in the chosen theme', await page.ev("document.documentElement.getAttribute('data-theme')"), 'light')
        vs.command('setting', section='hdf5Browser', key='theme', value='auto')
        check('  and setting it back to auto gives VS Code\'s theme again',
              await wait_for(page, "document.documentElement.getAttribute('data-theme')", 'dark'), 'dark')
        await page.close()
        page = None

        # --- two files of the same name, and a rewrite on disk --------------
        for run, src in (('run1', 'sample-a.h5'), ('run2', 'sample-b.h5')):
            os.makedirs(os.path.join(work, run))
            shutil.copy(fixture(src), os.path.join(work, run, 'results.h5'))
        m = vs.mark()
        vs.command('together', paths=[os.path.join(work, 'run1', 'results.h5'), os.path.join(work, 'run2', 'results.h5')])
        vs.wait_event(lambda e: e['type'] == 'status' and any(f['name'] == 'results (run2).h5' for f in e.get('opened', [])),
                      180, 'both results.h5 to open', since=m)
        page = await vs.page()
        check('two results.h5 from two runs are told apart by folder', await page.ev("fileOrder.slice()"), ['results.h5', 'results (run2).h5'])
        m = vs.mark()
        shutil.copy(fixture('sample-b.h5'), os.path.join(work, 'run1', 'results.h5'))
        st = vs.wait_event(lambda e: e['type'] == 'status' and e.get('why') == 'changed', 60, 'the rewritten file to be read again', since=m)
        check('a file rewritten on disk is read again', [f['name'] for f in st['opened']], ['results.h5'])
        await page.close()
        page = None

        # --- an empty file ----------------------------------------------------
        empty = os.path.join(work, 'empty.h5')
        open(empty, 'wb').close()
        m = vs.mark()
        vs.command('open', paths=[empty], own=True)
        e = vs.wait_event(lambda e: e['type'] == 'failed', 60, 'the empty file to be refused', since=m)
        check('an empty file is refused with a reason', e['message'], 'empty.h5 is empty.')

        # --- past 2 GiB, lazily without being asked ---------------------------
        big = os.path.join(work, 'big.h5')
        vs.command('setting', section='hdf5Browser', key='readLazily', value='auto')
        if make_big(big):
            m = vs.mark()
            vs.command('open', paths=[big], own=True)
            st = await opened(vs, m, 'the big file to open')
            page = await vs.page()
            r = await page.ev("(async () => { const st = loadedFiles['big.h5'].__lazy; await st.ensureGroup('/bio'); await st.ensureValues(['/bio/Cs-137']);"
                              " return { time: Array.from(loadedFiles['big.h5'].get('time').value.slice(0, 2)),"
                              " cs: Array.from(loadedFiles['big.h5'].get('bio').get('Cs-137').value.slice(0, 2)) }; })()")
            check(f'a {os.path.getsize(big) / 2**30:.1f} GiB file opens lazily without being asked', st['opened'], [{'name': 'big.h5', 'mode': 'lazy'}])
            check('  and its objects past 2 GiB read right', r, {'time': [1, 1.2067926406393286], 'cs': [0.01, 0.012067926406393285]})
            await page.close()
            page = None
        else:
            print('skip  the big file: h5py is not installed')

        # --- nothing blocked, nothing logged ------------------------------------
        # The empty file's refusal is the one error the pages should have reported.
        logs = [e['text'] for e in vs.events if e['type'] == 'log']
        check('the empty file\'s refusal was reported in its page', any('empty.h5 is empty.' in t for t in logs))
        check('nothing else was blocked by the policy or logged as an error',
              [t[:200] for t in logs if 'empty.h5 is empty.' not in t], [])

        # --- the files replaced under a running extension -------------------
        # As a .vsix of the same version installed over the running one does:
        # the extension keeps its build, the page gets the new files.
        subprocess.run(['node', 'build.mjs'], cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       check=True, capture_output=True)
        m = vs.mark()
        vs.command('open', paths=[fixture('sample-b.h5')], own=True)
        await opened(vs, m, 'sample-b.h5 to open')
        page = await vs.page_for('sample-b.h5')
        bar = ''
        for _ in range(50):
            bar = await page.ev("(document.querySelector('.rb-vscode-stale') || {}).textContent || ''")
            if bar:
                break
            await asyncio.sleep(0.2)
        vs.read_events()
        check('a page from files newer than the extension serving it says to reload the window',
              'Reload Window' in (bar or ''), True)
        check('  and tells the extension\'s log', any('reload the window' in e['text'] for e in vs.events[m:] if e['type'] == 'log'))
    finally:
        if page:
            await page.close()
        vs.stop()
        shutil.rmtree(work, ignore_errors=True)

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
