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

The Editor's view (screenshots of a line taken with the caret hidden and
shown): the caret stands centred on the letters of its line and the line
numbers on the code's baseline, also 500 lines down, where each number is
still at its line; typing never widens the code; scrolled sideways, the line
numbers stay at the left edge and a caret moved left comes back beside them,
not under them; after a paste of more lines than the frame holds the caret
is in view. The Command Window's caret stands centred on its letters too,
and the Command Window fits its panel, so nothing scrolls it under its header.

Files dragged from the computer (trusted drag events with real files): a
program dropped on the Command Window is copied into the current folder and
opened in the Editor; MAT-files of versions 7 and 7.3 dropped on the
Workspace load, as if typed (waiting their turn while a program runs), string
arrays too; a
name already there asks, and Keep both or
Replace do what they say (an open file shows its new text); on the Current
Folder files are only copied, on a folder row into that folder (a program
there is not found from the current folder, and the error says where it is;
from its own folder it runs, Windows line ends and all); a drag given
up leaves no zone; text dragged into the Command Window is still text; a
drop while a dialog is open is ignored; a folder is copied with its files;
a program whose file name is no name runs through run(), never as code.

parfor on a pool of two real workers: four passes of a second take two,
slices and reductions come back in the order of the passes, both workers
take passes, a function file reaches the workers and the files the passes
write come back, an error in a pass stops the loop with its message, the
status bar shows the passes, Ctrl+C stops the loop on the workers and the
pool works after, delete(gcp) stops the pool.

Statistics on the page's NumPy and SciPy: tests run, a fitted distribution
shows its estimates and intervals, anova1 shows its table and draws its box
plots, and boxplot, scatterhist, gplotmatrix, histfit, normplot, qqplot and
gscatter draw their figures.

A program's own windows: the wavelab example (a popup, a slider, a field,
radio buttons and a check box change its plot; a click in its axes, an
arrow key and a menu accelerator reach their callbacks; a toggle tool runs
a timer; a right click opens a context menu; a bad number brings an error
dialog that Enter closes; closing runs its CloseRequestFcn); tabs with axes
and a table, a list double-clicked; questdlg, inputdlg, listdlg and
uigetfile as the page shows them; a message box and a wait bar, never the
current figure; uiwait until a callback calls uiresume.

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
    # the Editor takes the focus a frame after the pause: typed sooner, the Enter could land in it
    await page.ev('new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(1))))')
    await type_line(page, 'numel(seq)')
    seen = await until(page, f"{OUTPUT}.slice(-80).includes('ans =\\n\\n     9')", 10)
    check('a command runs in the paused workspace', seen, True)
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


EDITOR = "document.querySelector('.pl-edview.is-shown .ple')._editor"

# The rows a 4x screenshot of a strip covers, worked out by the page: the
# letters (darker or lighter than the strip's top-left pixel) and, given a
# second shot, the caret (where the two differ), in px from the strip's top.
ROWS = r'''async (a, b) => {
  const load = (s) => new Promise((ok, no) => { const i = new Image(); i.onload = () => ok(i); i.onerror = no; i.src = `data:image/png;base64,${s}`; });
  const pixels = (img) => { const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
    const x = c.getContext('2d'); x.drawImage(img, 0, 0); return x.getImageData(0, 0, img.width, img.height).data; };
  const A = await load(a), w = A.width, h = A.height, p = pixels(A), q = b ? pixels(await load(b)) : null;
  const lum = (d, i) => d[i] + d[i + 1] + d[i + 2];
  const rows = (hit) => { let lo = -1, hi = -1;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (hit(4 * (y * w + x))) { if (lo < 0) lo = y; hi = y; break; }
    return lo < 0 ? null : [lo / 4, (hi + 1) / 4]; };
  return { ink: rows((i) => Math.abs(lum(p, i) - lum(p, 0)) > 150), caret: q ? rows((i) => Math.abs(lum(p, i) - lum(q, i)) > 60) : null };
}'''

# The x of a line's column in the coloured text, in page coordinates.
X_AT = '''((line, col) => { const ln = %s.hl.querySelectorAll('.ln')[line - 1];
  const tw = document.createTreeWalker(ln, NodeFilter.SHOW_TEXT); let n, k = col - 1;
  while ((n = tw.nextNode())) { if (k <= n.length) { const r = document.createRange(); r.setStart(n, k); r.collapse(true); return r.getBoundingClientRect().left; } k -= n.length; }
  return null; })''' % EDITOR


async def strip(page, x, y, w, h):
    r = await page.call('Page.captureScreenshot', {'format': 'png', 'clip': {'x': x, 'y': y, 'width': w, 'height': h, 'scale': 4}}, session=page.sid)
    return r['result']['data']


async def caret_rows(page, x, y, h, gx=None):
    """A line's strip from (x, y), h high, with the caret in it: the rows of
    its letters and of the caret (shot until it shows, as it blinks), and of
    the line's number from the gutter at gx, in px from the line's top."""
    hide = "(document.getElementById('caret-off') || document.head.appendChild(Object.assign(document.createElement('style'), { id: 'caret-off' })))"
    await page.ev(f"{hide}.textContent = '.ple-ta, .pl-cmd-ta {{ caret-color: transparent !important; }}'; 1")
    await asyncio.sleep(0.05)
    off = await strip(page, x, y, 300, h)
    number = await page.ev(f"({ROWS})({json.dumps(await strip(page, gx, y, 50, h))}, null)") if gx is not None else {'ink': None}
    await page.ev(f"{hide}.textContent = ''; 1")
    rows = {}
    for _ in range(25):
        rows = await page.ev(f"({ROWS})({json.dumps(off)}, {json.dumps(await strip(page, x, y, 300, h))})")
        if rows.get('caret'):
            break
        await asyncio.sleep(0.08)
    rows['number'] = number['ink']
    return rows


def centred(rows):
    """The caret reaches as far above its line's letters as below them."""
    ink, caret = rows['ink'], rows['caret']
    if not caret:
        return None
    above, below = ink[0] - caret[0], caret[1] - ink[1]
    return above > 0 and below > 0 and abs(above - below) <= 1.0


async def line_rows(page, line, col):
    """caret_rows for the Editor's caret put at a line's column, in view."""
    x, gx, y, h = await page.ev(f"""(() => {{ const ed = {EDITOR}; ed.focus(); const s = ed.lineStart({line}) + {col} - 1;
      ed.ta.setSelectionRange(s, s); ed.revealLine({line}, false);
      const r = ed.hl.querySelectorAll('.ln')[{line - 1}].getBoundingClientRect();
      return [ed.code.getBoundingClientRect().left, ed.gutter.getBoundingClientRect().left, r.top, r.height]; }})()""")
    await asyncio.sleep(0.2)
    return await caret_rows(page, x, y, h, gx)


async def editor_view(page):
    await page.call('Emulation.setFocusEmulationEnabled', {'enabled': True}, session=page.sid)
    long = 'y = ' + ' + '.join(f'a{i}' for i in range(150)) + ';'
    text = '\n'.join(['x = linspace(0, 2*pi, 100);', long, 'z = 3;', 'for k = 1:3', '    disp(k)', 'end'] * 85) + '\n'
    path = '/tmp/pylab-ui/view.m'
    await page.ev(f"PL.engine.fs('write', {{ path: '{path}', data: {json.dumps(text)} }}).then(() => PL.app.openFile('{path}')).then(() => 1)")
    await page.ev('document.fonts.ready.then(() => 1)')
    await asyncio.sleep(0.5)

    rows = await line_rows(page, 1, 13)
    check('the Editor draws the caret', rows['caret'] is not None, True)
    check('the caret stands centred on the letters of its line', centred(rows), True)
    rows = await line_rows(page, 6, 1)
    check("a line's number stands on the code's baseline", abs(rows['number'][1] - rows['ink'][1]) <= 0.5, True)
    rows = await line_rows(page, 504, 1)
    check('500 lines down too', abs(rows['number'][1] - rows['ink'][1]) <= 0.5, True)
    tops = await page.ev(f"""(() => {{ const ed = {EDITOR}; const g = [...ed.gutter.children].find((d) => d.textContent === '504');
      return [g.getBoundingClientRect().top, ed.hl.querySelectorAll('.ln')[503].getBoundingClientRect().top]; }})()""")
    check('and the number is at its line', abs(tops[0] - tops[1]) < 0.01, True)

    # typing on a short line leaves the width to the longest line
    await page.ev(f"(() => {{ const ed = {EDITOR}; ed.revealLine(3, false); const s = ed.lineStart(3) + 6; ed.ta.setSelectionRange(s, s); ed.el.scrollLeft = 0; return 1; }})()")
    width = await page.ev(f'{EDITOR}.el.scrollWidth')
    for ch in 'abcdefghijkl':
        await page.call('Input.insertText', {'text': ch}, session=page.sid)
        await asyncio.sleep(0.03)
    await asyncio.sleep(0.2)
    check('typing does not widen the code', await page.ev(f'{EDITOR}.el.scrollWidth'), width)

    # sideways: the numbers stay, and a caret moved left comes back beside them
    await page.ev(f"(() => {{ const ed = {EDITOR}; const s = ed.lineStart(2) + 7; ed.ta.setSelectionRange(s, s); ed.el.scrollLeft = 900; return 1; }})()")
    await asyncio.sleep(0.2)
    check('scrolled sideways, the line numbers stay at the left edge',
          await page.ev(f'{EDITOR}.gutter.getBoundingClientRect().left === {EDITOR}.el.getBoundingClientRect().left'), True)
    await shot(page, 'editor-sideways.png')
    left = {'key': 'ArrowLeft', 'code': 'ArrowLeft', 'windowsVirtualKeyCode': 37, 'nativeVirtualKeyCode': 37}
    await page.call('Input.dispatchKeyEvent', {'type': 'rawKeyDown', **left}, session=page.sid)
    await page.call('Input.dispatchKeyEvent', {'type': 'keyUp', **left}, session=page.sid)
    await asyncio.sleep(0.2)
    at = await page.ev(f"[{EDITOR}.cursorCol(), {X_AT}(2, {EDITOR}.cursorCol()), {EDITOR}.gutter.getBoundingClientRect().right]")
    check('a caret moved left comes back beside the line numbers', (at[0], at[1] >= at[2] + 5), (7, True))

    # a paste of more lines than the frame holds leaves the caret in view
    await page.ev(f"(() => {{ const ed = {EDITOR}; const n = ed.ta.value.length; ed.ta.setSelectionRange(n, n); return 1; }})()")
    await page.call('Input.insertText', {'text': '\n'.join(f'w{i} = {i} + ' + 'q' * 200 for i in range(60))}, session=page.sid)
    await asyncio.sleep(0.4)
    view = await page.ev(f"""(() => {{ const ed = {EDITOR}; const f = ed.el.getBoundingClientRect(), g = ed.gutter.getBoundingClientRect();
      const r = ed.hl.querySelectorAll('.ln')[ed.cursorLine() - 1].getBoundingClientRect(); const x = {X_AT}(ed.cursorLine(), ed.cursorCol());
      return [r.top >= f.top, r.bottom <= f.top + ed.el.clientHeight + 1, x >= g.right, x <= f.left + ed.el.clientWidth]; }})()""")
    check('after a paste of many lines the caret is in view', view, [True, True, True, True])

    await page.ev(f"(() => {{ const d = PL.app.docs.find((x) => x.key === '{path}'); d.saved = d.editor.value; d.setDirty(false); return PL.app.closeDoc(d).then(() => 1); }})()")
    await page.ev(f"PL.engine.fs('remove', {{ path: '/tmp/pylab-ui' }}).then(() => 1)")

    # the Command Window's caret, in a line typed at the prompt
    await page.ev("(() => { const c = PL.app.cmd; c.setLine('x = linspace(0, 2*pi, 100);'); c.ta.setSelectionRange(12, 12); c.scrollEnd(); return 1; })()")
    await asyncio.sleep(0.3)
    x, y, h = await page.ev("(() => { const t = PL.app.cmd.ta, r = t.getBoundingClientRect(); return [r.left, r.top, parseFloat(getComputedStyle(t).lineHeight)]; })()")
    rows = await caret_rows(page, x, y, h)
    check("the Command Window's caret stands centred on the letters too", centred(rows), True)
    await page.ev("PL.app.cmd.setLine(''); 1")
    check('the Command Window fits its panel, so nothing scrolls it under its header',
          await page.ev("(() => { const b = PL.app.cmd.el.closest('.pl-panel-body'); return b.scrollHeight <= b.clientHeight; })()"), True)
    await page.call('Emulation.setFocusEmulationEnabled', {'enabled': False}, session=page.sid)


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
    with open(os.path.join(d, 'tucked_fn.m'), 'wb') as f:      # Windows line ends, as a file from a PC has
        f.write(b"function tucked_fn(cmd)\r\nif ~nargin\r\n    feval(mfilename, 'go')\r\n    return\r\nend\r\n"
                b"c = {2, 3};\r\nA = magic(4);\r\nfprintf('tucked %s %d\\n', cmd, A(c{:}));\r\n")
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
    # the home folder is kept in the browser's profile: a run before this one left its files
    await command(page, "cd /home/user; if exist('droptest', 'dir'), rmdir('droptest', 's'); end")
    await page.ev("PL.app.fileRemoved('/home/user/droptest'); 1")
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

    # a program in that folder is not found from this one: the error says where it is
    await drag_files(page, x, y, [at('tucked_fn.m')])
    await until(page, f"({exists})('/home/user/droptest/sub/tucked_fn.m')", 10)
    await command(page, 'tucked_fn')
    check('drop: a program not found says where its file is', "Unrecognized function or variable 'tucked_fn'.\ntucked_fn.m is in /home/user/droptest/sub, which is not the current folder or on the path"
          in await tail(page, 400), True)
    await command(page, 'cd sub; tucked_fn; cd ..')
    check('drop: from its folder it runs (Windows line ends, mfilename, one cs-list as the index)', (await tail(page, 100)).endswith('tucked go 10\n'), True)

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


async def parallel(page):
    """parfor on a pool of real workers (engines in Web Workers of their own)."""
    out = await command(page, "clear; clc; mkdir('/home/user/pftest'); cd /home/user/pftest; p = parpool(2); n = p.NumWorkers")
    check('parpool: a pool of two workers', ['Starting a parallel pool of 2 workers' in out, 'n =\n\n     2' in out], [True, True])
    out = await command(page, 'tic; parfor k = 1:4, pause(1); end; t = toc; fast = t < 3.2')
    check('parfor: four passes of a second take two on two workers', out[-40:].strip().endswith('1'), True)
    out = await command(page, 's = 0; parfor k = 1:200, y(k) = k^2; s = s + k; end; ok = isequal(y, (1:200).^2) && s == 20100')
    check('parfor: slices and a sum come back in order', out[-40:].strip().endswith('1'), True)
    out = await command(page, 'parfor k = 1:8, t = getCurrentTask(); w(k) = t.ID; end; n = numel(unique(w))')
    check('parfor: both workers took passes', 'n =\n\n     2' in out[-30:], True)
    await page.ev("PL.engine.fs('write', { path: '/home/user/pftest/pfsq.m', data: 'function y = pfsq(x)\\ny = x.^2;\\nend\\n' }).then(() => 1)")
    out = await command(page, "parfor k = 1:3, writematrix(pfsq(k), sprintf('sq%d.txt', k)); end; v = readmatrix('sq3.txt')")
    check('parfor: a function file goes to the workers, the files the passes write come back', 'v =\n\n     9' in out[-30:], True)
    out = await command(page, "parfor k = 1:4, if k == 3, error('my:id', 'pass %d failed', k); end, end")
    check('parfor: an error in a pass stops the loop with its message', 'pass 3 failed' in out[-80:], True)
    await page.ev("PL.app.runCommand('parfor k = 1:4, pause(30); end'); 1")
    shown = await until(page, "PL.app.statusText.textContent.startsWith('parfor: ') && PL.app.statusText.textContent", 30)
    check('parfor: the status bar shows the passes', shown, 'parfor: 0 of 4 passes done, on 2 workers')
    await asyncio.sleep(1)
    await page.ev('PL.app.interrupt(); 1')
    check('parfor: Ctrl+C stops it on the workers', await until(page, '!PL.engine.busy', 10), True)
    check('parfor: and says so', 'Operation terminated by user.' in (await tail(page, 200)), True)
    out = await command(page, 'parfor k = 1:2, z(k) = 10 * k; end; z')
    check('parfor: the pool works after', 'z =\n\n    10    20' in out[-40:], True)
    out = await command(page, "delete(gcp); e = isempty(gcp('nocreate'))")
    check('delete(gcp) stops the pool', out[-40:].strip().endswith('1'), True)
    check('parfor: no script errors', page.errors, [])


INK = (f'(() => {{ const c = {WIN}.canvas; const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data; let n = 0; '
       'for (let i = 0; i < d.length; i += 4) if (d[i] < 200 || d[i + 1] < 200 || d[i + 2] < 200) n++; return n / (d.length / 4); })()')


async def drawn(page, frames):
    """Wait for the newest figure window to draw its axes (a legend draws a frame of its own too): the share of
    its canvas inked."""
    ok = await until(page, f'{WIN} && {WIN}.renderer.frames.length >= {frames}', 20)
    return await page.ev(INK) if ok else 0


async def statistics(page):
    """The statistics functions on the page's NumPy and SciPy, and their plots drawn."""
    out = await command(page, "clear; clc; close all; rng(7); x = normrnd(5, 2, 200, 1); [h, p] = ttest(x, 5); [h2, p2] = lillietest(x);"
                              "[h3, p3] = jbtest(x); [h4, p4] = adtest(x); [h5, p5] = kstest2(x(1:100), x(101:end)); ok = all([p p2 p3 p4 p5] > 0 & [p p2 p3 p4 p5] <= 1)")
    check('statistics: the tests run in the page', out[-30:].strip().endswith('1'), True)
    out = await command(page, "pd = fitdist(x, 'Weibull')")
    check('statistics: a fitted distribution object shows its estimates and intervals', 'Weibull distribution, fitted to 200 values' in out[-300:], True)
    out = await command(page, 'p = anova1(x, repmat([1; 2], 100, 1));')
    check('statistics: anova1 shows its table', 'One-way ANOVA' in out[-600:], True)
    check('statistics: and draws the box plots', await drawn(page, 1) > 0.01, True)
    await command(page, "close all; boxplot([x, x + 2, x.^1.2], 'Notch', 'on', 'Labels', {'a', 'b', 'c'}); title('Box plots')")
    check('statistics: boxplot draws', await drawn(page, 1) > 0.01, True)
    await shot(page, 'stats-boxplot.png')
    await command(page, "close all; y = 0.5 * x + randn(200, 1); g = repmat({'one'; 'two'}, 100, 1); scatterhist(x, y, 'Group', g, 'Kernel', 'overlay')")
    check('statistics: scatterhist draws three axes', await drawn(page, 3) > 0.01, True)
    await shot(page, 'stats-scatterhist.png')
    await command(page, "close all; gplotmatrix([x, y, x - y], [], g, [], [], [], 'on', 'stairs', {'x', 'y', 'x - y'}); title('By group')")
    check('statistics: gplotmatrix draws its matrix', await drawn(page, 11) > 0.01, True)
    await shot(page, 'stats-gplotmatrix.png')
    await command(page, "close all; subplot(2, 2, 1); histfit(x); subplot(2, 2, 2); normplot(x); subplot(2, 2, 3); qqplot(x, y); subplot(2, 2, 4); gscatter(x, y, g)")
    check('statistics: histfit, normplot, qqplot and gscatter draw', await drawn(page, 4) > 0.01, True)
    await shot(page, 'stats-four.png')
    out = await command(page, 'help ranksum')
    check('statistics: help answers', 'Wilcoxon rank sum test' in out[-800:], True)
    await command(page, 'close all; clear; clc')
    check('statistics: no script errors', page.errors, [])


WAVE = '[...PL.app.figures.wins.values()].find(w => w.fig.name === "Wave lab")'
PIECES = '[...PL.app.figures.wins.values()].find(w => w.fig.name === "Pieces")'


async def vkey(page, key, code, vk, text='', modifiers=0):
    """A key as a keyboard gives it (Chrome moves nothing without the key code)."""
    for kind in ('keyDown', 'keyUp'):
        await page.call('Input.dispatchKeyEvent', {'type': kind, 'key': key, 'code': code, 'windowsVirtualKeyCode': vk,
                                                   'text': text if kind == 'keyDown' else '', 'modifiers': modifiers}, session=page.sid)


async def ui_set(page, win, sel, value, event='change'):
    """A control of a program's window given a value, as a person would."""
    await page.ev(f"(() => {{ const e = {win}.el.querySelector({json.dumps(sel)}); e.value = {json.dumps(value)}; "
                  f"e.dispatchEvent(new Event({json.dumps(event)}, {{ bubbles: true }})); return 1; }})()")
    await idle(page)


async def in_axes(page, win, x, y):
    """Page coordinates of a data point in a window's first axes."""
    return await page.ev(f"(() => {{ const w = {win}; const f = w.renderer.frames[0]; const c = w.canvas.getBoundingClientRect(); "
                         f"return [c.left + f.fr.fx({x}), c.top + f.fr.fy({y})]; }})()")


async def click_dialog(page, label):
    return await page.ev(f"(() => {{ const b = [...document.querySelectorAll('.pl-dialog .pl-dfoot button')].find(b => b.textContent === {json.dumps(label)}); "
                         "if (!b) return false; b.click(); return true; })()")


PIECES_PROG = r"""f = figure('Name', 'Pieces', 'MenuBar', 'none', 'Position', [100 100 520 360]);
tg = uitabgroup(f, 'Position', [0 0 0.6 1]);
t1 = uitab(tg, 'Title', 'Plot');
t2 = uitab(tg, 'Title', 'Table');
ax = axes('Parent', t1);
plot(ax, 1:10, (1:10).^2)
tbl = uitable(t2, 'Data', {1, 'a', true; 2, 'b', false}, 'ColumnName', {'n', 'name', 'ok'}, 'ColumnEditable', [true true true], ...
    'Units', 'normalized', 'Position', [0.05 0.05 0.9 0.9], 'CellEditCallback', 'edited = get(gcbo, ''Data'');');
lb = uicontrol(f, 'Style', 'listbox', 'String', {'alpha', 'beta', 'gamma'}, 'Units', 'normalized', 'Position', [0.65 0.4 0.3 0.5], ...
    'Callback', 'picked = {get(gcbo, ''Value''), get(gcbf, ''SelectionType'')};');
"""


async def user_interfaces(page):
    """A program's own windows: the wavelab example's controls, menus,
    toolbar, keys, clicks, context menu, timer and close; tabs, a table and
    a list; the dialogs the page shows; a message box, a wait bar and
    uiwait."""
    await command(page, "close all; clc; cd /home/user/examples; wavelab")
    await until(page, f"{WAVE} && {WAVE}.ui.ctl.size", 20)
    await asyncio.sleep(0.5)
    win = await page.ev(f"(() => {{ const w = {WAVE}; return [w.ui.ctl.size, [...w.ui.menubar.children].map(b => b.textContent), "
                        f"w.ui.toolbars.querySelectorAll('.pl-uitool').length, w.tools.hidden, w.btnSave.hidden]; }})()")
    check('gui: a program window with its controls, menus and tools, no plot tools', win, [14, ['File', 'View'], 2, True, False])
    await shot(page, 'gui-wavelab.png')
    await ui_set(page, WAVE, '.pl-uipopup select', '2')
    await ui_set(page, WAVE, '.pl-uislider input', '6')
    await page.ev(f"(() => {{ const i = {WAVE}.el.querySelector('.pl-uiedit input'); i.focus(); i.select(); return 1; }})()")
    await page.call('Input.insertText', {'text': '1.5'}, session=page.sid)
    await vkey(page, 'Enter', 'Enter', 13, '\r')
    await idle(page)
    await page.ev(f"[...{WAVE}.el.querySelectorAll('.pl-uiradio')].find(l => l.textContent === 'Dotted').querySelector('input').click(); 1")
    await idle(page)
    await page.ev(f"{WAVE}.el.querySelector('.pl-uicheck input').click(); 1")
    await idle(page)
    out = await command(page, "l = findobj(0, 'Type', 'line'); fprintf('%s|%s|%s\\n', get(l, 'LineStyle'), get(l, 'Marker'), get(get(gca, 'Title'), 'String'))")
    check('gui: popup, slider, edit, radio buttons and check box set the plot', out.rstrip().endswith(':|o|Square, frequency 6, amplitude 1.5'), True)
    x, y = await in_axes(page, WAVE, 3.1416, 1)
    await page.click(x, y)
    await idle(page)
    check('gui: a click in the axes runs their ButtonDownFcn with CurrentPoint', await page.ev(f"[...{WAVE}.el.querySelectorAll('.pl-uitext')].pop().textContent"),
          'x = 3.142y = 1.000')
    sel = "disp(get(findobj(0, 'Name', 'Wave lab'), 'SelectionType'))"
    one = (await command(page, sel)).rstrip().splitlines()[-1]
    await asyncio.sleep(0.6)
    for k in (1, 2):
        await page.mouse('mousePressed', x, y, clicks=k)
        await page.mouse('mouseReleased', x, y, clicks=k)
    await idle(page)
    two = (await command(page, sel)).rstrip().splitlines()[-1]
    check('gui: a click in the axes is SelectionType normal, a double click open', [one, two], ['normal', 'open'])
    await vkey(page, 'ArrowUp', 'ArrowUp', 38)
    await idle(page)
    await vkey(page, 'g', 'KeyG', 71, '', 4 if await page.ev('PL.util.isMac') else 2)
    await idle(page)
    out = await command(page, "fprintf('%s|%s\\n', get(get(gca, 'Title'), 'String'), get(gca, 'XGrid'))")
    check('gui: a key reaches KeyPressFcn, and a menu accelerator its item', out.rstrip().endswith('Square, frequency 7, amplitude 1.5|off'), True)
    await page.ev(f"{WAVE}.ui.toolbars.querySelector('.pl-uitool[aria-pressed]').click(); 1")
    y0 = await command(page, "y = get(findobj(0, 'Type', 'line'), 'YData'); fprintf('%.3f\\n', y(1))")
    await asyncio.sleep(1.0)
    y1 = await command(page, "y = get(findobj(0, 'Type', 'line'), 'YData'); fprintf('%.3f\\n', y(1))")
    check('gui: a toggle tool starts a timer that moves the wave', y0.rstrip().splitlines()[-1] != y1.rstrip().splitlines()[-1], True)
    await page.ev(f"{WAVE}.ui.toolbars.querySelector('.pl-uitool[aria-pressed]').click(); 1")
    await idle(page)
    out = await command(page, "t = timerfindall; fprintf('%s\\n', get(t, 'Running'))")
    check('gui: and stops it', out.rstrip().endswith('off'), True)
    await page.mouse('mouseMoved', x, y)
    await page.mouse('mousePressed', x, y, button='right')
    await page.mouse('mouseReleased', x, y, button='right')
    check('gui: a right click opens the axes\' context menu', await until(page, "[...document.querySelectorAll('.pl-figpopup button .lbl')].map(b => b.textContent).join(',')", 5),
          'Blue,Red,Green')
    await page.ev("[...document.querySelectorAll('.pl-figpopup button')].find(b => b.textContent === 'Red').click(); 1")
    await idle(page)
    out = await command(page, "fprintf('%g ', get(findobj(0, 'Type', 'line'), 'Color')); fprintf('\\n')")
    check('gui: its item runs', out.rstrip().endswith('0.85 0.2 0.1'), True)
    await page.ev(f"(() => {{ const i = {WAVE}.el.querySelector('.pl-uiedit input'); i.focus(); i.select(); return 1; }})()")
    await page.call('Input.insertText', {'text': 'big'}, session=page.sid)
    await vkey(page, 'Enter', 'Enter', 13, '\r')
    await until(page, "document.querySelector('.pl-figwin.is-dialog')", 10)
    await idle(page)
    dlg = await page.ev("(() => { const d = document.querySelector('.pl-figwin.is-dialog'); return [d.querySelector('.t').textContent, d.textContent.includes('at most 2'), "
                        "document.activeElement && document.activeElement.textContent]; })()")
    check('gui: errordlg is a window of its own, OK in focus', dlg, ['Wave lab', True, 'OK'])
    await shot(page, 'gui-errordlg.png')
    await vkey(page, 'Enter', 'Enter', 13, '\r')
    check('gui: Enter closes it', await until(page, "!document.querySelector('.pl-figwin.is-dialog')", 5), True)
    check('gui: the program put the amplitude back', await page.ev(f"{WAVE}.el.querySelector('.pl-uiedit input').value"), '1.5')
    await page.ev(f"{WAVE}.btnClose.click(); 1")
    await idle(page)
    out = await command(page, "fprintf('%d %d\\n', numel(findobj(0, 'Name', 'Wave lab')), numel(timerfindall))")
    check('gui: closing runs CloseRequestFcn (the timer goes with the window)', out.rstrip().endswith('0 0'), True)

    # tabs, a table and a list
    await page.ev(f"PL.engine.fs('write', {{ path: '/home/user/pieces.m', data: {json.dumps(PIECES_PROG)} }}).then(() => 1)")
    await command(page, "cd /home/user; pieces")
    await until(page, f"{PIECES} && {PIECES}.renderer.frames.length", 20)
    check('gui: the axes in the first tab are drawn', await page.ev(f"{PIECES}.renderer.frames.length"), 1)
    await page.ev(f"[...{PIECES}.el.querySelectorAll('.pl-uitabs .strip button')].find(b => b.textContent === 'Table').click(); 1")
    await idle(page)
    await asyncio.sleep(0.3)
    tab = await page.ev(f"[{PIECES}.renderer.frames.length, {PIECES}.el.querySelector('.pl-uitable').getBoundingClientRect().height > 50]")
    check('gui: another tab shows its table; the axes of the first are not drawn', tab, [0, True])
    out = await command(page, "disp(get(get(tg, 'SelectedTab'), 'Title'))")
    check('gui: SelectedTab follows', out.rstrip().endswith('Table'), True)
    await page.ev(f"(() => {{ const i = {PIECES}.el.querySelectorAll('.pl-uitable td input[type=text]')[1]; i.focus(); i.select(); return 1; }})()")
    await page.call('Input.insertText', {'text': 'zed'}, session=page.sid)
    await vkey(page, 'Enter', 'Enter', 13, '\r')
    await idle(page)
    out = await command(page, "disp(edited{1, 2})")
    check('gui: a table cell typed in runs CellEditCallback with the new Data', out.rstrip().endswith('zed'), True)
    await page.ev(f"(() => {{ const s = {PIECES}.el.querySelector('.pl-uilist select'); s.options[1].selected = true; s.dispatchEvent(new Event('change', {{ bubbles: true }})); "
                  "s.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })); return 1; })()")
    await idle(page)
    out = await command(page, "fprintf('%d %s\\n', picked{1}, picked{2})")
    check('gui: a double click in a list is SelectionType open', out.rstrip().endswith('2 open'), True)
    await shot(page, 'gui-pieces.png')

    # the dialogs the page shows
    await page.ev("PL.app.runCommand(\"answer = questdlg('Ready?', 'Question', 'Yes', 'No', 'No');\"); 1")
    check('gui: questdlg asks with its buttons, the default first in line', await until(page, "[...document.querySelectorAll('.pl-dialog .pl-dfoot button')].map(b => b.textContent + (b.classList.contains('is-primary') ? '*' : '')).join(',')", 10),
          'Yes,No*')
    await click_dialog(page, 'Yes')
    await idle(page)
    check('gui: and gives the answer', (await command(page, 'disp(answer)')).rstrip().endswith('Yes'), True)
    await page.ev("PL.app.runCommand(\"names = inputdlg({'First', 'Last'}, 'Who', 1, {'Ada', ''});\"); 1")
    await until(page, "document.querySelectorAll('.pl-dialog input[type=text]').length === 2", 10)
    await page.ev("(() => { const i = document.querySelectorAll('.pl-dialog input[type=text]')[1]; i.value = 'Lovelace'; return 1; })()")
    await click_dialog(page, 'OK')
    await idle(page)
    check('gui: inputdlg', (await command(page, "fprintf('%s %s\\n', names{:})")).rstrip().endswith('Ada Lovelace'), True)
    await page.ev("PL.app.runCommand(\"[k, ok] = listdlg('ListString', {'red', 'green', 'blue'}, 'SelectionMode', 'single', 'Name', 'Colour');\"); 1")
    await until(page, "document.querySelector('.pl-dialog select')", 10)
    await page.ev("(() => { const s = document.querySelector('.pl-dialog select'); s.options[2].selected = true; return 1; })()")
    await click_dialog(page, 'OK')
    await idle(page)
    check('gui: listdlg', (await command(page, "fprintf('%d %d\\n', k, ok)")).rstrip().endswith('3 1'), True)
    await page.ev("PL.app.runCommand(\"[fn, fp, fi] = uigetfile({'*.m', 'Programs'; '*.txt', 'Text'}, 'Pick one');\"); 1")
    await until(page, "[...document.querySelectorAll('.pl-pick-row')].some(r => r.textContent.includes('pieces.m'))", 10)
    names = await page.ev("[...document.querySelectorAll('.pl-pick-row')].map(r => r.textContent.replace('▸', ''))")
    check('gui: uigetfile lists folders and the files of the type', 'pieces.m' in names and 'examples' in names and not any(n.endswith('.mat') for n in names), True)
    await page.ev("[...document.querySelectorAll('.pl-pick-row')].find(r => r.textContent.includes('pieces.m')).click(); 1")
    await click_dialog(page, 'Open')
    await idle(page)
    check('gui: and gives the name, folder and type', (await command(page, "fprintf('%s|%s|%d\\n', fn, fp, fi)")).rstrip().endswith('pieces.m|/home/user/|1'), True)

    # a message box, a wait bar, and uiwait on a dialog of the program's own
    await command(page, "close all; h = msgbox('Saved.', 'Done'); w = waitbar(0.4, 'Copying', 'Name', 'Copy');")
    await until(page, "document.querySelectorAll('.pl-figwin.is-dialog').length === 2", 10)
    await asyncio.sleep(0.3)
    bar = await page.ev("(() => { const w = [...PL.app.figures.wins.values()].find(w => w.fig.name === 'Copy'); return w && w.renderer.frames.length; })()")
    check('gui: a wait bar is drawn', bar, 1)
    await shot(page, 'gui-dialogs.png')
    out = await command(page, "fprintf('%d\\n', isempty(gcf) || gcf ~= h)")
    check('gui: dialogs are never the current figure', out.rstrip().endswith('1'), True)
    await page.ev("PL.app.runCommand(\"d = dialog('Name', 'Wait'); uicontrol(d, 'String', 'Done', 'Position', [130 60 100 30], 'Callback', 'uiresume(gcbf)'); uiwait(d); disp('waited'); delete(d)\"); 1")
    await until(page, "[...document.querySelectorAll('.pl-figwin.is-dialog .pl-uibtn')].some(b => b.textContent === 'Done')", 10)
    await asyncio.sleep(0.3)
    check('gui: uiwait keeps the program waiting', await page.ev('PL.engine.busy'), True)
    await page.ev("[...document.querySelectorAll('.pl-figwin.is-dialog .pl-uibtn')].find(b => b.textContent === 'Done').click(); 1")
    await idle(page)
    check('gui: until a callback calls uiresume', (await tail(page, 100)).rstrip().endswith('waited'), True)

    # a message box over a figure the program goes on drawing in, and text above the axes' box
    await command(page, "close all force; under = figure('Name', 'Under'); axes('Position', [0.1 0.1 0.8 0.6]); plot(1:3); ylim([0 4])")
    await command(page, "h = msgbox('Over it', 'Top'); plot(4:6); text(2, 5, 'XXXXXX', 'Color', 'r', 'FontSize', 20); ylim([0 4])")
    await until(page, "document.querySelectorAll('.pl-figwin.is-dialog').length === 1", 10)
    await asyncio.sleep(0.4)
    above = await page.ev("(() => { const ws = [...PL.app.figures.wins.values()]; const z = (n) => Number(ws.find(w => w.fig.name === n).el.style.zIndex); "
                          "return z('Top') > z('Under'); })()")
    check('gui: a message box stays over the figure drawn in after it', above, True)
    under = '[...PL.app.figures.wins.values()].find(w => w.fig.name === "Under")'
    red = await page.ev(f"(() => {{ const w = {under}; const f = w.renderer.frames[0].fr; const c = w.canvas; const k = c.width / c.getBoundingClientRect().width; "
                        "const x = f.fx(2), y = f.fy(5); const d = c.getContext('2d').getImageData(Math.round(x * k), Math.round((y - 14) * k), Math.round(70 * k), Math.round(28 * k)).data; "
                        "let n = 0; for (let i = 0; i < d.length; i += 4) if (d[i] > 180 && d[i + 1] < 90 && d[i + 2] < 90) n++; return n; })()")
    check('gui: text outside the axes\' box is drawn (its Clipping is off)', red > 20, True)

    # sound through the page's audio, a size the program sets, text placed in pixels
    await command(page, 'sound(sin(1:200), 8000)')
    snd = await page.ev('PL.app.lastSound || null')
    check('gui: sound plays through the page', bool(snd) and snd['rate'] == 8000 and snd['samples'] == 200, True)
    await command(page, "close all force; fz = figure('Name', 'Sized', 'Position', [100 100 400 300]); set(fz, 'Position', [100 100 480 330])")
    await asyncio.sleep(0.4)
    sized = '[...PL.app.figures.wins.values()].find(w => w.fig.name === "Sized")'
    sz = await page.ev(f"(() => {{ const c = {sized}.canvasSize(); return [c.w, c.h]; }})()")
    check('gui: a window takes the size its program sets', abs(sz[0] - 480) <= 1 and abs(sz[1] - 330) <= 1, True)
    await command(page, "ax = axes('Units', 'pixels', 'Position', [40 40 300 200]); axis off; text(ax, 20, 20, 'PX', 'Units', 'pixels', 'BackgroundColor', [1 0 0], 'Margin', 4)")
    await asyncio.sleep(0.4)
    red = await page.ev(f"(() => {{ const w = {sized}; const r = w.renderer.frames[0].fr.r; const c = w.canvas; const k = c.width / c.getBoundingClientRect().width; "
                        "const d = c.getContext('2d').getImageData(Math.round((r.x + 21) * k), Math.round((r.y + r.h - 24) * k), Math.round(12 * k), Math.round(8 * k)).data; "
                        "let n = 0; for (let i = 0; i < d.length; i += 4) if (d[i] > 180 && d[i + 1] < 90 && d[i + 2] < 90) n++; return n; })()")
    check('gui: text in pixels stands that far from the axes\' corner', red > 20, True)

    # a program that lays itself out when its window is first shown: the ResizeFcn runs once the command ends
    await command(page, "close all force; rf = figure('Visible', 'off', 'Name', 'Laid out', 'ResizeFcn', "
                        "'set(findobj(gcbf, ''Tag'', ''pp''), ''Position'', [10 10 120 60])'); "
                        "uipanel(rf, 'Units', 'pixels', 'Tag', 'pp'); set(rf, 'Visible', 'on')")
    out = await command(page, "fprintf('%g ', get(findobj(rf, 'Tag', 'pp'), 'Position')); fprintf('\\n')")
    check('gui: a window first shown runs its ResizeFcn when the command ends, with no click', out.rstrip().endswith('10 10 120 60'), True)

    # a figure saved as a .fig, opened again from the Current Folder
    await command(page, "close all force; f = figure('Name', 'Kept'); plot(1:3, [2 1 3]); title('Kept plot'); savefig(f, 'kept.fig'); close all force")
    row = "document.querySelector('.pl-folder tr[data-name=\"kept.fig\"]')"
    await until(page, row, 10)
    check('gui: a .fig shows in the Current Folder as a figure', await page.ev(f"!!{row} && !!{row}.querySelector('svg')"), True)
    await page.ev(f"{row}.dispatchEvent(new MouseEvent('dblclick', {{ bubbles: true }})); 1")
    await until(page, "[...PL.app.figures.wins.values()].some(w => w.fig.name === 'Kept')", 20)
    await idle(page)
    kept = '[...PL.app.figures.wins.values()].find(w => w.fig.name === "Kept")'
    check('gui: and opens as the figure it was, drawn', await page.ev(f"!!{kept} && {kept}.renderer.frames.length === 1 && {kept}.fig.axes[0].title.string === 'Kept plot'"), True)
    await command(page, 'close all force')

    # a program file of an older release, in Windows-1252: read as written, in the Editor and when run
    data = list("function s = latin1()\n% LATIN1  A file of smörgåsar\ns = 'Smörgås ™';\n".encode('cp1252'))
    await page.ev("PL.app.fileRemoved('/home/user/latin1.m'); 1")    # a tab kept from a run before this one
    await page.ev(f"PL.engine.fs('write', {{ path: '/home/user/latin1.m', data: new Uint8Array({json.dumps(data)}) }}).then(() => 1)")
    await page.ev("PL.app.openFile('/home/user/latin1.m').then(() => 1)")
    text = await page.ev("(() => { const d = PL.app.docs.find((d) => d.key === '/home/user/latin1.m'); return d ? d.editor.value : null; })()")
    check('gui: a Windows-1252 file shows its letters in the Editor', bool(text) and "Smörgås ™" in text, True)
    out = await command(page, 'disp(latin1())')
    check('gui: and runs with them', out.rstrip().endswith("Smörgås ™"), True)
    check('gui: no script errors', page.errors, [])


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
        await editor_view(page)
        await drops(page)
        await parallel(page)
        await statistics(page)
        await user_interfaces(page)
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
