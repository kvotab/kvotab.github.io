#!/usr/bin/env python3
"""pylab.html in a real browser.

The page loads without a script error and Python starts, its versions in
the status bar; a command typed with real keys runs and shows its result
the way the Command Window does, and the Workspace and Command History list
it; an error is shown as an error; Tab completion, help and the Help panel
answer; the Editor runs a file to a breakpoint, the prompt turns to K>>, a
command runs in the paused function's workspace, Step moves on a line and
Continue finishes the run; input() waits for an answer; Ctrl+C stops a loop
that never ends; the Variable editor shows a matrix as a table and writes a
cell back; a new file in the Current Folder is listed and removed; in a
figure window, zooming by a box, panning, the data tip, the grid button,
turning a 3-D view and Restore reach Python's limits and view; the page
draws in the dark theme; the full window hides the site around the desktop
and is remembered; at phone width the page does not scroll sideways, the
Command Window is there and the Workspace opens from its menu.

Files dragged from the computer (trusted drag events with real files): a
program dropped on the Command Window is copied into the current folder and
opened in the Editor; MAT-files of versions 7 and 7.3 dropped on the
Workspace load, as if typed (waiting their turn while a program runs), string
arrays too; a
name already there asks, and Keep both or
Replace do what they say (an open file shows its new text); on the Current
Folder files are only copied, on a folder row into that folder; a drag given
up leaves no zone; text dragged into the Command Window is still text; a
drop while a dialog is open is ignored; a folder is copied with its files;
a program whose file name is no name runs through run(), never as code.

Start a server on the repository root and headless Chrome (the recipe is in
README.md) on PYLAB_HTTP_PORT and PYLAB_CDP_PORT (defaults 8811, 9311), then

    python3 resources/tests/pylab/test-ui.py

With PYLAB_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile

from cdp import BASE, Checks, open_page, wait_engine

SHOTS = os.environ.get('PYLAB_SHOTS')
check = Checks()
WIN = '[...PL.app.figures.wins.values()].pop()'


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await page.shot(os.path.join(SHOTS, name))


async def until(page, expr, secs=30):
    for _ in range(int(secs * 10)):
        v = await page.ev(expr)
        if v and not (isinstance(v, str) and v.startswith('EXCEPTION')):
            return v
        await asyncio.sleep(0.1)
    return None


async def idle(page):
    await until(page, '!PL.engine.busy')
    await asyncio.sleep(0.2)


# The Command Window writes in the next animation frame; Python has posted
# all of a run's output before the run ends, so writing what is pending
# gives the whole of it.
OUTPUT = '(() => { const c = PL.app.cmd; if (c.pendingRuns && c.pendingRuns.length) { cancelAnimationFrame(c._raf); c._flush(); } return c.out.textContent; })()'


async def command(page, code):
    """Run a command as the page does and wait for it; the Command Window's
    text afterwards."""
    await page.ev(f'PL.app.runCommand({json.dumps(code)}).then(() => 1)', timeout=180)
    await idle(page)
    return await page.ev(OUTPUT)


async def type_line(page, text):
    """Type into the Command Window with real key events and press Enter."""
    await page.ev('PL.app.cmd.ta.focus(); PL.app.cmd.setLine(""); 1')
    await page.call('Input.insertText', {'text': text}, session=page.sid)
    await page.key('Enter', text='\r')


async def tail(page, n=400):
    return (await page.ev(OUTPUT))[-n:]


async def drag(page, x0, y0, x1, y1, steps=6):
    await page.mouse('mouseMoved', x0, y0)
    await page.mouse('mousePressed', x0, y0)
    for k in range(1, steps + 1):
        await page.mouse('mouseMoved', x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps)
    await page.mouse('mouseReleased', x1, y1)
    await asyncio.sleep(0.4)


async def frame_box(page):
    """The page coordinates of the newest figure's first axes: (x, y, w, h)."""
    r = await page.ev(f'(() => {{ const w = {WIN}; const c = w.canvas.getBoundingClientRect(); const f = w.renderer.frames[0].rect; '
                      'return [c.left + f.x, c.top + f.y, f.w, f.h]; })()')
    return r


async def desktop(page):
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    if st != 'ready':
        return
    versions = await page.ev('PL.app.versionEl.textContent')
    check('the status bar names Python, NumPy and SciPy', all(k in (versions or '') for k in ('Python', 'NumPy', 'SciPy')), True)
    await command(page, 'close all; clear; clc; cd /home/user/examples')

    # a command typed with real keys
    await type_line(page, 'x = magic(4)')
    await idle(page)
    out = await tail(page)
    check('typed command echoed', '>> x = magic(4)' in out, True)
    check('the matrix shown as the Command Window does', 'x =\n\n    16     2     3    13\n     5    11    10     8' in out, True)
    rows = await page.ev('PL.app.ws.rows.map(r => [r.name, r.size, r.class])')
    check('Workspace lists x', ['x', '4×4', 'double'] in (rows or []), True)
    hist = await page.ev('PL.app.history.items.slice(-1)[0].c')
    check('Command History has it', hist, 'x = magic(4)')
    await type_line(page, 'y = x(2, :) * 2;')
    await idle(page)
    check('a semicolon hides the result', 'y =\n' in await tail(page, 60), False)
    check('the variable is set', await page.ev("PL.app.ws.rows.find(r => r.name === 'y')?.value"), '[10,22,20,16]')

    # an error
    await type_line(page, 'undefinedThingXyz + 1')
    await idle(page)
    err = await page.ev("[...PL.app.cmd.out.querySelectorAll('.o-err')].map(s => s.textContent).join('')")
    check('an error is shown as one', "Unrecognized function or variable 'undefinedThingXyz'." in (err or ''), True)
    check('and marked in the history', await page.ev('PL.app.history.items.slice(-1)[0].e'), True)

    # completion and help
    comp = await page.ev("PL.app.complete('lins', 4)")
    check('Tab completion knows linspace', 'linspace' in json.dumps(comp), True)
    out = await command(page, 'help sum')
    check('help sum', ' sum - The sum of the elements' in out, True)
    await page.ev("PL.app.openHelp('ode45'); 1")
    help_text = await until(page, "document.querySelector('.pl-help pre')?.textContent")
    check('the Help panel shows a function', 'ode45 - Solve an ODE system' in (help_text or ''), True)
    await page.ev("PL.app.openHelp(); 1")
    n_links = await page.ev("document.querySelectorAll('.pl-help [data-fn]').length")
    check('the Help panel lists the functions', (n_links or 0) > 700, True)
    await page.ev("PL.app.closeDoc(PL.app.docs.find(d => d.kind === 'help')); 1")

    # the debugger
    await page.ev("PL.app.openFile('/home/user/examples/collatz.m').then(d => { PL.app.clearAllBreakpoints(); PL.app.toggleBreakpoint(d, 14); return 1; })")
    await asyncio.sleep(0.5)
    await type_line(page, 'n = collatz(6)')
    line = await until(page, 'PL.app.debug && PL.app.debug.line')
    check('paused at the breakpoint', line, 14)
    check('the prompt is K>>', await page.ev('PL.app.cmd.prompt.textContent'), 'K>> ')
    check('the Editor marks the line', await page.ev("!!document.querySelector('.ple-gl .arrow')"), True)
    await shot(page, 'debugger.png')
    await type_line(page, 'numel(seq)')
    await asyncio.sleep(1.0)
    check('a command runs in the paused workspace', 'ans =\n\n     9' in await tail(page, 80), True)
    await page.ev("PL.app.dbg('step'); 1")
    await until(page, 'PL.app.debug && PL.app.debug.line !== 14', 10)
    check('Step moves on', await page.ev('PL.app.debug && PL.app.debug.line'), 15)
    await page.ev("PL.app.clearAllBreakpoints(); PL.app.dbg('continue'); 1")
    await until(page, '!PL.engine.busy && !PL.app.debug', 30)
    check('Continue finishes the run', 'n =\n\n     8' in await tail(page, 300), True)
    check('the prompt is >> again', await page.ev('PL.app.cmd.prompt.textContent'), '>> ')
    await command(page, 'close all')

    # input() and Ctrl+C
    await type_line(page, "v = input('Number: ') * 2")
    mode = await until(page, "PL.app.cmd.mode === 'input' && PL.app.cmd.prompt.textContent", 20)
    check('input() asks', mode, 'Number: ')
    await page.call('Input.insertText', {'text': '21'}, session=page.sid)
    await page.key('Enter', text='\r')
    await idle(page)
    check('the answer is evaluated', 'v =\n\n    42' in await tail(page, 80), True)
    await type_line(page, 'k = 0; while true, k = k + 1; end')
    await asyncio.sleep(1.5)
    check('the loop runs', await page.ev('PL.engine.busy'), True)
    await page.ev('PL.app.cmd.ta.focus(); 1')
    await page.key('c', code='KeyC', modifiers=2)
    stopped = await until(page, '!PL.engine.busy', 15)
    check('Ctrl+C stops it', stopped, True)
    check('and says so', 'Operation terminated by user.' in await tail(page, 120), True)

    # the Variable editor
    await command(page, 'M = magic(5);')
    await page.ev("PL.app.openVariable('M'); 1")
    cells = await until(page, "(() => { const v = PL.app.docs.find(d => d.kind === 'var'); if (!v) return null; "
                               "const t = v.view.querySelector('tbody'); return t && [...t.rows].map(r => [...r.cells].slice(1).map(c => c.textContent)); })()")
    check('the Variable editor shows the matrix', cells and cells[0], ['17', '24', '1', '8', '15'])
    check('and nothing else under it', await page.ev("PL.app.docs.find(d => d.kind === 'var').view.textContent.includes('null')"), False)
    await page.ev("(() => { const v = PL.app.docs.find(d => d.kind === 'var'); const td = v.view.querySelector('tbody tr td:nth-child(2)'); "
                  "td.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })); const i = td.querySelector('input'); i.value = '99'; "
                  "i.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); return 1; })()")
    await idle(page)
    await asyncio.sleep(0.5)
    out = await command(page, 'm11 = M(1, 1)')
    check('a cell edited in the table is written back', 'm11 =\n\n    99' in out[-60:], True)
    await page.ev("PL.app.closeDoc(PL.app.docs.find(d => d.kind === 'var')); 1")

    # the Current Folder
    await page.ev("PL.engine.fs('write', { path: '/home/user/examples/zzTestFile.m', data: 'disp(42)\\n' }).then(() => PL.app.folder.refresh()).then(() => 1)")
    names = await until(page, "PL.app.folder.items.some(i => i.name === 'zzTestFile.m') && PL.app.folder.items.map(i => i.name)")
    check('a new file is listed', 'zzTestFile.m' in (names or []), True)
    out = await command(page, 'zzTestFile')
    check('and runs by its name', out.rstrip().endswith('42'), True)
    dates = await page.ev("[...PL.app.folder.table.querySelectorAll('tbody tr td:nth-child(2)')].map(t => t.textContent)")
    check('the dates fit their column', all(len(d) <= 10 for d in dates or ['x' * 20]), True)
    await page.ev("PL.engine.fs('remove', { path: '/home/user/examples/zzTestFile.m' }).then(() => PL.app.folder.refresh()).then(() => 1)")
    await asyncio.sleep(0.3)
    check('a removed file is gone', await page.ev("PL.app.folder.items.some(i => i.name === 'zzTestFile.m')"), False)

    # figures
    await command(page, 'close all; x = linspace(0, 10, 11); plot(x, x.^2, "o-"); title("Squares");')
    await until(page, 'PL.app.figures.wins.size === 1')
    await asyncio.sleep(0.6)
    ink = await page.ev(f'(() => {{ const c = {WIN}.canvas; const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data; '
                        'let n = 0; for (let i = 0; i < d.length; i += 4) if (d[i] < 200 || d[i + 1] < 200) n++; return n; })()')
    check('the figure is drawn', (ink or 0) > 500, True)
    x, y, w, h = await frame_box(page)
    await page.ev(f"{WIN}.setTool('zoomin'); 1")
    await drag(page, x + w * 0.25, y + h * 0.25, x + w * 0.75, y + h * 0.75)
    await idle(page)
    out = await command(page, 'xl = round(xlim, 2)')
    check('zoom by a box reaches xlim', 'xl =\n\n    2.5000    7.5000' in out[-60:], True)
    await page.ev(f"{WIN}.setTool('pan'); 1")
    await drag(page, x + w / 2, y + h / 2, x + w / 2 - 100, y + h / 2)
    out = await command(page, 'moved = xlim > [2.6 7.6]')
    check('a pan moves xlim', 'moved =\n\n  1×2 logical array\n\n   1   1' in out[-80:], True)
    await page.ev(f"{WIN}.restoreView(); 1")
    out = await command(page, 'back = xlim')
    check('Restore puts it back', 'back =\n\n     0    10' in out[-60:], True)
    await page.ev(f"{WIN}.setTool('datatip'); 1")
    px, py = await page.ev(f'(() => {{ const w = {WIN}; const c = w.canvas.getBoundingClientRect(); const f = w.renderer.frames[0].fr; return [c.left + f.fx(5), c.top + f.fy(25)]; }})()')
    await page.click(px + 2, py - 2)
    await asyncio.sleep(0.3)
    check('a data tip at the point', await page.ev(f'{WIN}.tips.map(t => t.text)'), ['X 5\nY 25'])
    await shot(page, 'figure.png')
    await page.ev(f"{WIN}.tools.querySelector('[title^=\"Grid\"]').click(); 1")
    await idle(page)
    out = await command(page, "g = get(gca, 'XGrid')")
    check('the grid button sets XGrid', "g =\n\n    'on'" in out[-40:], True)
    png = await page.ev(f'{WIN}.renderTo(1)')
    check('Save as a picture makes a PNG', (png or '').startswith('data:image/png') and len(png) > 5000, True)
    await command(page, 'figure; surf(peaks(25)); [az0, el0] = view;')
    await until(page, 'PL.app.figures.wins.size === 2')
    await asyncio.sleep(0.6)
    x, y, w, h = await frame_box(page)
    await drag(page, x + w / 2, y + h / 2, x + w / 2 + 60, y + h / 2 + 20)
    await idle(page)
    out = await command(page, '[az1, el1] = view; turned = [az1 ~= az0, el1 ~= el0]')
    check('dragging a 3-D view turns it in Python', 'turned =\n\n  1×2 logical array\n\n   1   1' in out[-80:], True)
    await shot(page, 'surface.png')
    await command(page, 'close all')
    check('close all closes the windows', await until(page, 'PL.app.figures.wins.size === 0', 5), True)


def drop_fixtures():
    """Files to drop, written here: a script, MAT-files of version 7 (SciPy)
    and 7.3 (h5py), a file of no known kind, and the script changed."""
    import h5py
    import numpy as np
    import scipy.io as sio
    d = tempfile.mkdtemp(prefix='pylab-drop-')
    with open(os.path.join(d, 'dropped_demo.m'), 'w') as f:
        f.write('% dropped from the computer\ny = 41 + 1;\n')
    sio.savemat(os.path.join(d, 'dropped.mat'), {'q': np.array([[1.0, 2.0, 3.0]]), 's': {'a': 'x'}})
    sio.savemat(os.path.join(d, 'later.mat'), {'w': np.array([[7.0]])})
    from matfixtures import strings_v5
    with open(os.path.join(d, 'dropped_strings.mat'), 'wb') as f:
        f.write(strings_v5({'names': np.array([['alpha', None], ['beta', 'δ']], dtype=object)}))
    with h5py.File(os.path.join(d, 'dropped73.mat'), 'w', userblock_size=512) as f:
        ds = f.create_dataset('h', data=np.array([[1.0, 2.0], [3.0, 4.0]]).T)
        ds.attrs['MATLAB_class'] = np.bytes_('double')
    with open(os.path.join(d, 'dropped73.mat'), 'r+b') as f:
        f.write(b'MATLAB 7.3 MAT-file, written by test-ui.py'.ljust(116, b' ') + b'\0' * 8 + b'\x00\x02IM')
    with open(os.path.join(d, 'a;disp(5).m'), 'w') as f:
        f.write('ran = 1;\n')
    with open(os.path.join(d, 'notes.xyz'), 'wb') as f:
        f.write(b'\x00\x01 not text')
    os.makedirs(os.path.join(d, 'changed'))
    with open(os.path.join(d, 'changed', 'dropped_demo.m'), 'w') as f:
        f.write('% dropped again, changed\ny = 43;\n')
    return d


async def drag_files(page, x, y, paths, kinds=('dragEnter', 'dragOver', 'drop')):
    """A drag of files from the computer: Chrome hands the page trusted drag
    events with real files."""
    data = {'items': [], 'files': paths, 'dragOperationsMask': 1}
    for kind in kinds:
        await page.call('Input.dispatchDragEvent', {'type': kind, 'x': x, 'y': y, 'data': data}, session=page.sid)


async def middle(page, expr):
    return await page.ev(f'(() => {{ const r = ({expr}).getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()')


async def press_button(page, label, secs=10):
    """Click a dialog's button by its text (a click: Escape can hang headless Chrome)."""
    return await until(page, f"(() => {{ const b = [...document.querySelectorAll('.pl-dialog button')].find(b => b.textContent === {json.dumps(label)}); "
                             'if (!b) return false; b.click(); return true; })()', secs)


async def drops(page):
    d = drop_fixtures()
    at = lambda name: os.path.join(d, name)  # noqa: E731
    exists = "(p) => PL.engine.fs('exists', { path: p })"
    await command(page, "clear; clc; mkdir('/home/user/droptest'); cd /home/user/droptest; mkdir sub")
    await page.ev("window.__dropSeen = []; addEventListener('drop', (ev) => __dropSeen.push(ev.defaultPrevented)); 1")

    # a program dropped on the Command Window: copied into the current folder and opened in the Editor
    x, y = await middle(page, 'PL.app.pCmd')
    await drag_files(page, x, y, [at('dropped_demo.m')], ('dragEnter', 'dragOver'))
    check('drop: the desktop shows where files go', await page.ev('!PL.app.deskZone.hidden && PL.app.deskZone.textContent'),
          'Drop to openThey are copied into droptest: programs open in the Editor, MAT-files load into the workspace.')
    await drag_files(page, x, y, [at('dropped_demo.m')], ('drop',))
    check('drop: a program opens in the Editor', await until(page, "PL.app.current && PL.app.current.key === '/home/user/droptest/dropped_demo.m' && PL.app.current.editor.value"),
          '% dropped from the computer\ny = 41 + 1;\n')
    check('drop: the page keeps the drop (the browser opens nothing)', await page.ev('__dropSeen[0]'), True)
    check('drop: the zone is gone after the drop', await page.ev('PL.app.deskZone.hidden'), True)

    # MAT-files dropped on the Workspace load into it, as if typed
    x, y = await middle(page, 'PL.app.pWs')
    await drag_files(page, x, y, [at('dropped.mat'), at('dropped73.mat')])
    got = await until(page, "PL.app.ws.rows.some(r => r.name === 'h') && PL.app.ws.rows.map(r => r.name).join(' ')", 120)
    check('drop: MAT-files of versions 7 and 7.3 load (h5py loads for the second)', got, 'h q s')
    await idle(page)
    out = await tail(page, 600)
    check("drop: the loads show in the Command Window", ">> load('dropped.mat')" in out and ">> load('dropped73.mat')" in out, True)
    check('drop: and in the Command History', await page.ev('PL.app.history.items.slice(-2).map(i => i.c)'), ["load('dropped.mat')", "load('dropped73.mat')"])
    out = await command(page, 'v = [s.a, num2str(h(2, 1) + q(3))]')
    check('drop: the loaded values', "v =\n\n    'x6'" in out, True)
    await drag_files(page, x, y, [at('dropped_strings.mat')])
    check('drop: a string array loads as one', await until(page, "(PL.app.ws.rows.find(r => r.name === 'names') || {}).class", 30), 'string')
    await idle(page)
    out = await command(page, 'g = names(2, 2), k = nnz(ismissing(names))')
    check('drop: with its text and its missing string', ['g = \n\n    "δ"' in out or 'g =\n\n    "δ"' in out, 'k =\n\n     1' in out], [True, True])

    # a name already in the folder asks; Keep both gives the dropped file a new name
    await drag_files(page, x, y, [at('dropped.mat')])
    check('drop: a name already there asks first', await press_button(page, 'Keep both'), True)
    check('drop: kept both, the new one loaded', await until(page, "PL.app.history.items.at(-1).c === \"load('dropped_2.mat')\"", 20), True)
    await idle(page)

    # while a program runs, a dropped MAT-file's load waits its turn, as a typed command does
    await page.ev("PL.app.runCommand('pause(2)'); 1")
    await until(page, 'PL.engine.busy', 5)
    await drag_files(page, x, y, [at('later.mat')])
    check('drop: while a program runs, the load waits its turn', await until(page, "PL.app.cmd.queue.join() === \"load('later.mat')\"", 10), True)
    check('drop: and then runs', await until(page, "PL.app.ws.rows.some(r => r.name === 'w')", 30), True)
    await idle(page)

    # Replace writes over an open file, and the Editor shows the new text
    x, y = await middle(page, 'PL.app.pEditor')
    await drag_files(page, x, y, [at('changed/dropped_demo.m')])
    check('drop: Replace is asked for', await press_button(page, 'Replace'), True)
    check('drop: the Editor shows the replaced file', await until(page, "PL.app.docs.find(d => d.key === '/home/user/droptest/dropped_demo.m').editor.value.includes('y = 43')", 10), True)
    check('drop: and it is not marked changed', await page.ev("PL.app.docs.find(d => d.key === '/home/user/droptest/dropped_demo.m').dirty"), False)

    # a program whose file name is no name runs through run(), its name never code
    await drag_files(page, x, y, [at('a;disp(5).m')])
    await until(page, "PL.app.current && PL.app.current.key === '/home/user/droptest/a;disp(5).m'", 10)
    await page.ev('PL.app.runCurrent(); 1')
    await until(page, "PL.app.ws.rows.some(r => r.name === 'ran')", 20)
    await idle(page)
    out = await tail(page, 300)
    check('drop: a file whose name is no name runs through run()', [">> run('/home/user/droptest/a;disp(5).m')" in out, '     5\n' in out], [True, False])

    # dropped on the Current Folder: only copied, on a folder row into that folder
    tabs = await page.ev('PL.app.docs.length')
    hist = await page.ev('PL.app.history.items.length')
    x, y = await middle(page, 'PL.app.folder.el')
    await drag_files(page, x, y, [at('notes.xyz')], ('dragEnter', 'dragOver'))
    check('drop: the Current Folder says where files go', await page.ev("PL.app.folder.zone && PL.app.folder.zone.textContent"), 'Drop to upload into droptest')
    check('drop: the desktop zone stays hidden over it', await page.ev('PL.app.deskZone.hidden'), True)
    await drag_files(page, x, y, [at('notes.xyz')], ('drop',))
    check('drop: copied into the Current Folder', await until(page, f"({exists})('/home/user/droptest/notes.xyz')", 10), 'file')
    await until(page, "PL.app.folder.items.some(i => i.name === 'notes.xyz')", 10)
    check('drop: and not opened', await page.ev('[PL.app.docs.length, PL.app.history.items.length]'), [tabs, hist])
    x, y = await middle(page, "PL.app.folder.table.querySelector('tr[data-name=\"sub\"]')")
    await drag_files(page, x, y, [at('dropped.mat')], ('dragEnter', 'dragOver'))
    check('drop: a folder row is the target', await page.ev("[PL.app.folder.zone.textContent, !!PL.app.folder.table.querySelector('tr.is-droptarget[data-name=\"sub\"]')]"),
          ['Drop to upload into sub', True])
    await drag_files(page, x, y, [at('dropped.mat')], ('drop',))
    check('drop: copied into that folder', await until(page, f"({exists})('/home/user/droptest/sub/dropped.mat')", 10), 'file')

    # a drag given up hides the zone (Chrome tells the page nothing)
    x, y = await middle(page, 'PL.app.pCmd')
    await drag_files(page, x, y, [at('notes.xyz')], ('dragEnter', 'dragOver', 'dragCancel'))
    await asyncio.sleep(0.5)
    check('drop: a drag given up leaves no zone', await page.ev('PL.app.deskZone.hidden && !PL.app.folder.zone'), True)

    # text dragged into the Command Window is still text
    await page.ev("PL.app.cmd.setLine(''); 1")
    await asyncio.sleep(0.2)
    tx, ty = await middle(page, 'PL.app.cmd.ta')
    check('drop: the prompt stays in view with the Editor open above it', await page.ev(f'document.elementFromPoint({tx}, {ty}) === PL.app.cmd.ta'), True)
    await page.call('Input.dispatchDragEvent', {'type': 'dragEnter', 'x': tx, 'y': ty, 'data': {'items': [{'mimeType': 'text/plain', 'data': 'disp(7)'}], 'dragOperationsMask': 1}}, session=page.sid)
    await page.call('Input.dispatchDragEvent', {'type': 'dragOver', 'x': tx, 'y': ty, 'data': {'items': [{'mimeType': 'text/plain', 'data': 'disp(7)'}], 'dragOperationsMask': 1}}, session=page.sid)
    await page.call('Input.dispatchDragEvent', {'type': 'drop', 'x': tx, 'y': ty, 'data': {'items': [{'mimeType': 'text/plain', 'data': 'disp(7)'}], 'dragOperationsMask': 1}}, session=page.sid)
    check('drop: text dropped in the Command Window is typed there', await until(page, "PL.app.cmd.ta.value === 'disp(7)'", 5), True)
    await page.ev("PL.app.cmd.setLine(''); 1")

    # a drop while a dialog is open is ignored
    await page.ev("PL.util.dialog({ title: 'Test', body: 'x', buttons: [{ label: 'Close it', value: null }] }); 1")
    await drag_files(page, x, y, [at('dropped73.mat')])
    await asyncio.sleep(0.6)
    check('drop: ignored while a dialog is open', await page.ev(f"({exists})('/home/user/droptest/dropped73_2.mat')"), False)
    await press_button(page, 'Close it')
    check('drop: and no Replace question came', await page.ev("document.querySelectorAll('.pl-dialog').length"), 0)

    # a folder: walked with what it holds (dot files left out), as Chrome's entries give it
    walked = await page.ev("""(() => {
      const file = (name, text) => ({ isFile: true, isDirectory: false, name, file: (ok) => ok(new File([text], name)) });
      const dir = (name, kids) => ({ isFile: false, isDirectory: true, name, createReader() { let sent = false; return { readEntries(ok) { ok(sent ? [] : kids); sent = true; } }; } });
      const proj = dir('proj', [file('main.m', 'disp(1)'), file('.DS_Store', 'x'), dir('data', [file('b.txt', '1 2 3')]), dir('empty', [])]);
      return PL.app.copyIn([{ entry: proj, file: null }], '/home/user/droptest', true).then((got) => JSON.stringify(got));
    })()""")
    check('drop: a folder is copied', walked, '[{"name":"proj","dir":true}]')
    found = await page.ev(f"Promise.all(['proj/main.m', 'proj/data/b.txt', 'proj/empty', 'proj/.DS_Store'].map(p => ({exists})('/home/user/droptest/' + p)))")
    check('drop: with its files and folders, dot files left out', found, ['file', 'file', 'dir', False])

    # the Details of a version 7.3 file in a new Python: the worker loads h5py for it, then lists it
    await page.ev('PL.engine.restart(); 1')
    check('drop: Python starts again', await until(page, "PL.engine.state === 'ready'", 240), True)
    await page.ev("PL.app.details.show('/home/user/droptest/dropped73.mat'); 1")
    got = await until(page, "PL.app.details.el.querySelector('tbody') && PL.app.details.el.querySelector('tbody').textContent", 120)
    check('drop: the Details list a version 7.3 file (h5py loaded for them)', got, 'h2×2double')
    check('drop: no script errors', page.errors, [])
    shutil.rmtree(d, ignore_errors=True)


async def full_window(page):
    await page.ev('PL.app.toggleFull(); 1')
    await asyncio.sleep(0.3)
    check('the full window hides the site header',
          await page.ev("document.documentElement.classList.contains('pl-full') && getComputedStyle(document.querySelector('body > header')).display"), 'none')
    check('and is remembered', await page.ev("localStorage.getItem('pylab.full')"), '1')
    await page.ev('PL.app.toggleFull(); 1')
    await asyncio.sleep(0.3)
    check('and goes back', await page.ev("document.documentElement.classList.contains('pl-full')"), False)


def luminance(css):
    nums = [float(v) for v in css[css.index('(') + 1:css.index(')')].split(',')[:3]]
    return (0.2126 * nums[0] + 0.7152 * nums[1] + 0.0722 * nums[2]) / 255


async def main():
    page = await open_page(f'{BASE}/pylab.html')
    try:
        await desktop(page)
        await drops(page)
        await full_window(page)
        await shot(page, 'desktop.png')
        check('no script errors', page.errors, [])
        check('no console errors', [c for c in page.console if 'favicon' not in c], [])
    finally:
        await page.close()

    page = await open_page(f'{BASE}/pylab.html', dark=True)
    try:
        check('dark: engine ready', await wait_engine(page), 'ready')
        bg = await page.ev("getComputedStyle(document.querySelector('.pl-cmd') || document.body).backgroundColor")
        ink = await page.ev("getComputedStyle(PL.app.cmd.out).color")
        check('dark: the Command Window is dark', luminance(bg) < 0.2, True)
        check('dark: its text is light', luminance(ink) > 0.6, True)
        await shot(page, 'dark.png')
        check('dark: no script errors', page.errors, [])
    finally:
        await page.close()

    page = await open_page(f'{BASE}/pylab.html', width=390, height=844, mobile=True)
    try:
        check('phone: engine ready', await wait_engine(page), 'ready')
        check('phone: no sideways scroll', await page.ev('document.documentElement.scrollWidth <= innerWidth'), True)
        check('phone: the Command Window is there', await page.ev('PL.app.cmd.el.getBoundingClientRect().height > 150'), True)
        await command(page, 'x = magic(3);')
        menu = await page.ev("(() => { PL.app.pCmd.querySelector('.pl-panel-head button').click(); "
                             "return [...document.querySelectorAll('.pl-menu [role=menuitem], .pl-menu button, .pl-menu li')].map(e => e.textContent.trim()); })()")
        check('phone: the Command Window menu opens the Workspace', any('Workspace' in m for m in menu or []), True)
        await page.key('Escape')
        await page.ev("PL.util.closeMenu && PL.util.closeMenu(); PL.app.togglePanel('right'); 1")
        await asyncio.sleep(0.4)
        check('phone: the Workspace shows', await page.ev("getComputedStyle(PL.app.right).display !== 'none' && PL.app.right.getBoundingClientRect().height > 100"), True)
        check('phone: with the variable', await page.ev("PL.app.ws.rows.some(r => r.name === 'x')"), True)
        check('phone: still no sideways scroll', await page.ev('document.documentElement.scrollWidth <= innerWidth'), True)
        await shot(page, 'phone.png')
        check('phone: no script errors', page.errors, [])
    finally:
        await page.close()
    return check.done()


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
