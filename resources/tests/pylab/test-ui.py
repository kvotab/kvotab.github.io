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
turning a 3-D view and Restore reach Python's limits and view; the
property editor opened by the toolbar's arrow, a click on the line, the
title, the legend, the colorbar and by the tick labels picking each, its
fields setting XGrid, limits typed with Enter (one refused, with set's
message), a colour and a line style, Escape putting a field back, a
change the program makes showing there, the program hearing no click and a
control picked, not pressed, inspect and plotedit, and the editor closed
with its figure; the page
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

Figure files: saveas writes PNG, JPEG, BMP, TIFF, SVG, PDF and EPS files
that are what their names say (the SVG well formed, the PDF's objects where
its cross-reference table says, the EPS read through by pscheck.py), print
-dpdf and -r, and a .gif refused; an arrow annotation drawn; getframe of a
figure and of an axes, frame2im and movie; a modal message box laying a
veil over the page until its OK is clicked, and dialog's modal window.

Series: stem in a loop over four subplots shows its stems in each, and
stem, stairs, area and errorbar each draw their data; polaraxes in two
subplots with polarplot and polarscatter; a line given Color=[...] in the
second of four subplots kept in an array.

Maps: worldmap with a route, geographic axes labelled in degrees, a
shapefile written and read; Natural Earth's coastline and land fetched when
a program asks; basemaps: nothing fetched until one is named, then only the
tiles over the view (from a host this test answers itself), each where its
longitude and latitude are, the figure saved with its map and attribution;
grayland's water and land.

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
    links = await page.ev("(() => { const a = [...PL.app.cmd.out.querySelectorAll('a.pl-helplink')].map((e) => e.dataset.help); return a; })()")
    check('help sum: See also, its functions links', 'See also: ' in out and 'prod' in (links or []) and 'cumsum' in (links or []), True)
    await page.ev("(() => { const a = [...PL.app.cmd.out.querySelectorAll('a.pl-helplink')].find((e) => e.dataset.help === 'prod'); a.click(); return 1; })()")
    out2 = await until(page, "(() => { const t = PL.app.cmd.out.textContent; return t.includes(' prod - ') ? t : null; })()")
    check('a click on a link in help shows that function\'s help', bool(out2) and '>> help prod' in out2, True)
    # a function without a page of its own shows its summary, forms and how it is computed (the docs section has the
    # pages): the last in the Help lists whose How it works has two paragraphs or more and whose See also names another
    # without a page, so that the rounds of pages never take it away
    await page.ev("PL.app.openHelp(); 1")
    await until(page, "document.querySelector('.pl-help .pl-fnlist a[data-fn]')")
    bare = await page.ev("[...document.querySelectorAll('.pl-help .pl-fnlist a[data-fn]')].filter((a) => !a.classList.contains('has-doc')).map((a) => a.dataset.fn)") or []
    pick, help_text, see = None, None, []
    for name in reversed(bare):
        await page.ev(f"PL.app.openHelp({json.dumps(name)}); 1")
        info = await until(page, "(() => { const p = document.querySelector('.pl-help pre'); if (!p || !p.textContent.includes(" + json.dumps(name + ' - ') + ")) return null; "
                                 "const s = document.querySelector('.pl-help .pl-how'); return { text: p.textContent, how: s ? s.querySelectorAll('p').length : 0, "
                                 "see: [...document.querySelectorAll('.pl-help .pl-see a[data-help]')].map((a) => a.dataset.help) }; })()", 5)
        other = [x for x in (info or {}).get('see', []) if x in bare and x != name]
        if info and info['how'] >= 2 and other:
            pick, help_text, see = (name, other[0]), info['text'], info['see']
            break
    check('the Help panel shows a function', bool(pick) and f'{pick[0]} - ' in (help_text or ''), True)
    how = await page.ev("(() => { const s = document.querySelector('.pl-help .pl-how'); "
                        "return !!s && s.querySelector('h3').textContent === 'How it works' && s.querySelectorAll('p').length >= 2 "
                        "&& !document.querySelector('.pl-help pre').textContent.includes('How it works'); })()")
    check('and how PyLAB computes it, as paragraphs after the call forms', how, True)
    check('the Help panel ends with See also, each a link', bool(pick) and pick[1] in see, True)
    shown = None
    if pick:
        await page.ev(f"document.querySelector('.pl-help .pl-see a[data-help=' + {json.dumps(json.dumps(pick[1]))} + ']').click(); 1")
        shown = await until(page, "(() => { const p = document.querySelector('.pl-help pre'); return p && p.textContent.includes(" + json.dumps(pick[1] + ' - ') + ") ? p.textContent : null; })()")
    check('a click there shows that function in the Help panel', bool(shown), True)
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
    await command(page, "TV = table([1;2], {'a';'b'}, 'VariableNames', {'n', 'label'}, 'RowNames', {'r1', 'r2'});")
    await page.ev("PL.app.openVariable('TV'); 1")
    tv = await until(page, "(() => { const v = PL.app.docs.find(d => d.kind === 'var'); if (!v) return null; const t = v.view.querySelector('table'); "
                           "return t && t.tBodies[0] && t.tBodies[0].rows.length ? { head: [...t.tHead.rows[0].cells].map(c => c.textContent), "
                           "rows: [...t.tBodies[0].rows].map(r => [...r.cells].map(c => c.textContent)) } : null; })()")
    check('a table in the Variable editor: its variables over its rows, the row names beside',
          tv, {'head': ['Row', 'n', 'label'], 'rows': [['r1', '1', "{'a'}"], ['r2', '2', "{'b'}"]]})
    await page.ev("[...PL.app.docs.find(d => d.kind === 'var').view.querySelectorAll('thead th')].find(t => t.textContent === 'label').click(); 1")
    opened = await until(page, "(() => { const k = PL.app.docs.filter(d => d.kind === 'var').map(d => d.key).join(' '); return k.includes('TV.label') ? k : null; })()")
    check('a click on a variable\'s name opens that variable', 'TV.label' in (opened or ''), True)
    for _ in range(3):
        await page.ev("(() => { const v = PL.app.docs.find(d => d.kind === 'var'); if (v) PL.app.closeDoc(v); return 1; })()")

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
    await page.ev(f"{WIN}.btnSave.click(); 1")
    items = await page.ev("[...document.querySelectorAll('.pl-menu [role=menuitem]')].map(b => b.textContent)")
    check('the save button offers the kinds of file', items,
          ['PNG picture (.png)', 'SVG drawing (.svg)', 'PDF document (.pdf)', 'EPS drawing (.eps)', 'JPEG picture (.jpg)'])
    saved = await page.ev("(async () => { const was = HTMLAnchorElement.prototype.click; let got = null; "
                          "HTMLAnchorElement.prototype.click = function () { got = [this.download, this.href]; }; "
                          "[...document.querySelectorAll('.pl-menu [role=menuitem]')].find(b => b.textContent.startsWith('SVG')).click(); "
                          "for (let i = 0; i < 100 && !got; i++) await new Promise(r => setTimeout(r, 100)); "
                          "HTMLAnchorElement.prototype.click = was; if (!got) return null; "
                          "const t = await (await fetch(got[1])).text(); return [got[0], t.includes('<svg'), t.includes('Squares')]; })()")
    check('its SVG item saves the figure as an SVG drawing, its text as text', saved, ['figure1.svg', True, True])
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


EDITOR = "PL.app.current.view.querySelector('.ple')._editor"

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



async def ink(page):
    """The share of the newest figure's canvas inked (0 while it has none yet)."""
    v = await page.ev(INK)
    return v if isinstance(v, (int, float)) else 0

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
    check('statistics: help answers, and says how PyLAB computes it',
          'Wilcoxon rank sum test' in out[-2500:] and 'How it works' in out[-2500:] and 'scipy.stats.rankdata' in out[-2500:], True)
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

    # a camera zoom (CameraViewAngle): the axes drawn larger about their middle, inside their panel
    await command(page, "close all force; cz = figure('Name', 'Zoomed', 'Position', [100 100 500 400]); cp = uipanel(cz, 'Position', [0 0 0.6 1]); "
                        "ca = axes(cp, 'Position', [0.1 0.1 0.8 0.8]); plot(ca, 0:10, 0:10); xlim(ca, [0 10]); ylim(ca, [0 10]); "
                        "set(ca, 'ButtonDownFcn', 'czp = get(gca, ''CurrentPoint'');');")
    zoomed = '[...PL.app.figures.wins.values()].find(w => w.fig.name === "Zoomed")'
    w0 = await page.ev(f"{zoomed}.renderer.frames[0].rect.w")
    await command(page, 'camzoom(ca, 2)')
    await asyncio.sleep(0.4)
    w1 = await page.ev(f"{zoomed}.renderer.frames[0].rect.w")
    check('gui: camzoom draws the axes twice as large', abs(w1 / w0 - 2) < 0.01, True)
    x, y = await in_axes(page, zoomed, 6, 7)
    await page.click(x, y)
    await idle(page)
    hit = (await command(page, "fprintf('%.1f %.1f\\n', czp(1, 1), czp(1, 2))")).rstrip()
    px, py = await page.ev(f"(() => {{ const w = {zoomed}; const b = w.renderer.frames[0].ax._box; const c = w.canvas.getBoundingClientRect(); "
                           "return [c.left + b.x + b.w + 40, c.top + b.y + b.h / 2]; })()")
    await page.click(px, py)
    await idle(page)
    # the window heard that click (its CurrentPoint is past the panel's 300 pixels), but the axes did not
    past = (await command(page, "fprintf('%.1f %.1f %d\\n', czp(1, 1), czp(1, 2), get(cz, 'CurrentPoint') * [1; 0] > 300)")).rstrip().splitlines()[-1]
    check('gui: a click on the zoomed axes gives the point under it; one past their panel misses them', [hit.endswith('6.0 7.0'), past], [True, '6.0 7.0 1'])

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


FILE_B64 = ("(async (p) => { const b = await PL.engine.fs('read', { path: p, binary: true }); const u = new Uint8Array(b.buffer || b); "
            "let s = ''; for (let i = 0; i < u.length; i += 32768) s += String.fromCharCode.apply(null, u.subarray(i, i + 32768)); return btoa(s); })")


async def engine_file(page, path):
    """A file of the engine's folder, as bytes."""
    import base64
    b = await page.ev(f'{FILE_B64}({json.dumps(path)})', timeout=60)
    return base64.b64decode(b) if isinstance(b, str) and not b.startswith('EXCEPTION') else b''


def pdf_problems(b):
    """What is wrong with a PDF's frame: its header, its trailer, and each object where its cross-reference table says."""
    import re
    if not b.startswith(b'%PDF-1.'):
        return ['no %PDF header']
    m = re.search(rb'startxref\s+(\d+)\s+%%EOF\s*$', b)
    if not m:
        return ['no startxref at the end']
    x = int(m.group(1))
    if not b.startswith(b'xref', x):
        return ['startxref does not point at the table']
    n = int(re.match(rb'xref\s+0\s+(\d+)', b[x:]).group(1))
    rows = re.findall(rb'(\d{10}) (\d{5}) ([nf]) ?\r?\n', b[x:])[:n]
    bad = [i for i, (off, _, kind) in enumerate(rows) if kind == b'n' and not b.startswith(f'{i} 0 obj'.encode(), int(off))]
    return [f'objects not where the table says: {bad[:5]}'] if bad else []


async def figure_files(page):
    import re
    import xml.etree.ElementTree as ET
    from pscheck import check_eps
    out = await command(page, "close all force; wasIn = cd(tempdir); f = figure('Position', [100 100 560 420]); x = linspace(0, 2*pi, 40); "
                        "plot(x, sin(x), 'r-o'); hold on; imagesc([4 6], [-0.5 0.5], magic(4)); title('\\alpha and x^2 \\leq \\infty'); "
                        "annotation('arrow', [0.2 0.5], [0.2 0.5], 'LineWidth', 2); "
                        "annotation('textbox', [0.6 0.75 0.3 0.1], 'String', 'note', 'BackgroundColor', [1 1 0.8]); "
                        "for e = {'png', 'jpg', 'bmp', 'tif', 'svg', 'pdf', 'eps'}, saveas(f, ['fig.' e{1}]); end")
    check('figure files: saveas writes every format', 'Error' not in out[-800:], True)
    folder = re.findall(r'\[(.*?)\]', await command(page, "fprintf('[%s]\\n', pwd)"))[-1]
    files = {e: await engine_file(page, f'{folder}/fig.{e}') for e in ('png', 'jpg', 'bmp', 'tif', 'svg', 'pdf', 'eps')}
    magic = {'png': b'\x89PNG', 'jpg': b'\xff\xd8\xff', 'bmp': b'BM', 'tif': b'II*\x00', 'svg': b'<?xml', 'pdf': b'%PDF-1.4', 'eps': b'%!PS-Adobe-3.0 EPSF-3.0'}
    check('figure files: each is the kind its name says', {e: files[e][:len(m)] == m for e, m in magic.items()}, {e: True for e in magic})
    w = int.from_bytes(files['bmp'][18:22], 'little'), int.from_bytes(files['bmp'][22:26], 'little')
    check('figure files: BMP and PNG of one size, twice the figure on screen',
          (w, (int.from_bytes(files['png'][16:20], 'big'), int.from_bytes(files['png'][20:24], 'big'))) == (w, w) and w[0] > 500, True)
    svg = ET.fromstring(files['svg'])
    ns = '{http://www.w3.org/2000/svg}'
    texts = [e.text or '' for e in svg.iter(f'{ns}text')]
    check('figure files: the SVG is well formed, with paths, text (the TeX made characters) and the picture',
          (svg.tag == f'{ns}svg', len(list(svg.iter(f'{ns}path'))) >= 10, 'note' in texts, any('α' in s for s in texts),
           any('≤' in s for s in texts), len(list(svg.iter(f'{ns}image')))), (True, True, True, True, True, 1))
    check('figure files: the PDF has its objects where its table says', pdf_problems(files['pdf']), [])
    check('figure files: the PDF writes text in Helvetica, Greek in Symbol, and the picture as an image',
          [k in files['pdf'] for k in (b'/BaseFont /Helvetica ', b'/BaseFont /Symbol', b'/Subtype /Image')], [True, True, True])
    problems, counts = check_eps(files['eps'])
    check('figure files: the EPS reads through (operands, balance, fonts, the picture data)', problems, [])
    check('figure files: the EPS shows text and draws its picture', (counts.get('show', 0) > 10, counts.get('image', 0)), (True, 1))
    out = await command(page, "print(f, 'printed', '-dpdf'); print('hi', '-dpng', '-r96'); saveas(f, 'x.gif')")
    check('figure files: print -dpdf adds the extension; a .gif is refused', ('.gif file' in out[-300:], (await engine_file(page, f'{folder}/printed.pdf'))[:5]),
          (True, b'%PDF-'))
    hi = await engine_file(page, f'{folder}/hi.png')
    check('figure files: print -r96 writes the figure at its size on screen', int.from_bytes(hi[16:20], 'big') == w[0] // 2, True)
    # the arrow drawn over the axes, from (0.2, 0.2) to (0.5, 0.5) of the figure
    dark = await page.ev(f"(() => {{ const c = {WIN}.canvas; const g = c.getContext('2d'); const k = c.width / c.clientWidth; "
                         "return [0.3, 0.35, 0.4].map((t) => { const d = g.getImageData(Math.round(t * c.clientWidth * k), Math.round((1 - t) * c.clientHeight * k), 1, 1).data; "
                         "return d[0] + d[1] + d[2] < 200; }); })()")
    check('figure files: the arrow annotation is drawn', dark, [True, True, True])
    # getframe
    await command(page, "F = getframe(f); s = size(F.cdata); k = class(F.cdata); G = getframe(gca); t = size(G.cdata); same = isequal(frame2im(F), F.cdata); movie(G, 1, 50)")
    size = await page.ev(f'[{WIN}.canvas.clientHeight, {WIN}.canvas.clientWidth]')
    vals = await command(page, "fprintf('<%d %d %d %s %d %d %d>\\n', s, k, t(1:2), same)")
    got = re.findall(r'<(\d+) (\d+) (\d+) (\w+) (\d+) (\d+) (\d+)>', vals)[-1]
    check('getframe: the figure at its size on screen, uint8 RGB; an axes smaller; frame2im', (
        [int(got[0]), int(got[1])] == size, got[2], got[3], 0 < int(got[4]) < size[0], 0 < int(got[5]) < size[1], got[6]), (True, '3', 'uint8', True, True, '1'))
    # a modal message box
    await command(page, "m = msgbox('Wait for me', 'Modal', 'modal');")
    veiled = await until(page, "!!document.querySelector('.pl-figveil')", 10)
    check('modal: a modal message box lays a veil over the page', bool(veiled), True)
    hit = await page.ev("(() => { const r = PL.app.cmd.el.getBoundingClientRect(); const e = document.elementFromPoint(r.x + 12, r.y + r.height - 12); "
                        "return e ? e.className : ''; })()")
    check('modal: a click on the Command Window meets the veil', hit, 'pl-figveil')
    await page.ev('PL.app.cmd.ta.focus(); 1')
    check('modal: the focus stays in the modal window', await page.ev("!!document.activeElement.closest('.pl-figwin.is-modal')"), True)
    box = await page.ev("(() => { const b = [...document.querySelectorAll('.pl-figwin.is-modal button')].find((x) => x.textContent === 'OK'); "
                        "if (!b) return null; const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
    if box:
        for kind in ('mousePressed', 'mouseReleased'):
            await page.call('Input.dispatchMouseEvent', {'type': kind, 'x': box[0], 'y': box[1], 'button': 'left', 'clickCount': 1}, session=page.sid)
    gone = await until(page, "!document.querySelector('.pl-figveil')", 10)
    check('modal: its OK button closes it, and the veil goes', (bool(box), bool(gone)), (True, True))
    await command(page, "d = dialog('Name', 'Mine');")
    check("modal: dialog's window is modal", bool(await until(page, "!!document.querySelector('.pl-figveil')", 10)), True)
    await command(page, "set(d, 'WindowStyle', 'normal');")
    check("modal: and an ordinary window when made 'normal'", bool(await until(page, "!document.querySelector('.pl-figveil')", 10)), True)
    await command(page, "close all force; cd(wasIn); clear; clc")
    check('figure files: no script errors', page.errors, [])


# pixels of the first colour of the color order, rgb(0, 114, 189), in each quarter of the newest figure's canvas
FIRST_COLOUR = (f"(() => {{ const c = {WIN}.canvas; const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; "
                "const W = c.width, H = c.height, n = [0, 0, 0, 0]; for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { "
                "const i = (y * W + x) * 4; if (Math.abs(d[i]) < 40 && Math.abs(d[i + 1] - 114) < 40 && Math.abs(d[i + 2] - 189) < 40) "
                "n[(y < H / 2 ? 0 : 2) + (x < W / 2 ? 0 : 1)]++; } return n; })()")


async def series_kinds(page):
    await command(page, "close all force; for k = 1:4\n    data = rand(1,10);\n    subplot(2,2,k)\n    stem(data)\nend")
    n = await page.ev(FIRST_COLOUR)
    check('stem in a loop over four subplots: each axes shows its stems', [v > 40 for v in n], [True] * 4)
    await shot(page, 'stems.png')
    await command(page, "clf; subplot(2, 2, 1); stem(1:5, 'filled'); subplot(2, 2, 2); stairs(rand(1, 8)); "
                        "subplot(2, 2, 3); area(rand(1, 8)); subplot(2, 2, 4); errorbar(1:5, rand(1, 5), 0.1 * ones(1, 5))")
    n = await page.ev(FIRST_COLOUR)
    check('stem, stairs, area and errorbar each draw their data', [v > 40 for v in n], [True] * 4)
    await shot(page, 'series.png')
    await command(page, "close all force; figure\n   ax1 = subplot(2,1,1,polaraxes);\n   theta = linspace(0,2*pi,50);\n"
                        "   rho = sin(theta).*cos(theta);\n   polarplot(ax1,theta,rho)\n   \n   ax2 = subplot(2,1,2,polaraxes);\n"
                        "   polarscatter(ax2,theta,rho)")
    polar = await page.ev(f'{WIN}.renderer.frames.filter((f) => f.fr && f.fr.polar).length')
    # bluish pixels (the thin circles of the markers are mostly blended) in the upper and lower half
    n = await page.ev(f"(() => {{ const c = {WIN}.canvas; const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; const n = [0, 0]; "
                      "for (let y = 0; y < c.height; y++) for (let x = 0; x < c.width; x++) { const i = (y * c.width + x) * 4; "
                      "if (d[i + 2] > 150 && d[i + 2] - d[i] > 60 && d[i + 2] > d[i + 1]) n[y < c.height / 2 ? 0 : 1]++; } return n; })()")
    check('polaraxes in two subplots: polarplot draws above, polarscatter below', (polar, n[0] > 40, n[1] > 40), (2, True, True))
    await shot(page, 'polar.png')
    await command(page, "close all force; for k = 1:4\n    ax(k) = subplot(2,2,k);\nend\nsubplot(ax(2))\nx = linspace(1,50);\n"
                        "plot(x, sin(x), Color=[0.1, 0.5, 0.1])\ntitle(\"Second Subplot\")\naxis([0 50 -1 1])")
    green = await page.ev(f"(() => {{ const c = {WIN}.canvas; const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let a = 0, b = 0; "
                          "for (let y = 0; y < c.height / 2; y++) for (let x = 0; x < c.width; x++) { const i = (y * c.width + x) * 4; "
                          "if (Math.abs(d[i] - 26) < 30 && Math.abs(d[i + 1] - 128) < 30 && Math.abs(d[i + 2] - 26) < 30) { if (x < c.width / 2) a++; else b++; } } return [a, b]; })()")
    check('Name=Value: the green line in the second of four subplots', (green[0] < 5, green[1] > 40), (True, True))
    await command(page, "close all force; x = linspace(0,10);\nfigure\nplot(x, sin(x))\ntitle(\"Line Plot 1\")\nax1 = gca;\nfigure\n"
                        "plot(x, 2*sin(x))\ntitle(\"Line Plot 2\")\nlgd = legend(\"2*Sin(x)\");\nax2 = gca;\nfnew = figure;\n"
                        "ax1_copy = copyobj(ax1,fnew);\nsubplot(2,1,1,ax1_copy)\ncopies = copyobj([ax2,lgd],fnew);\nax2_copy = copies(1);\nsubplot(2,1,2,ax2_copy)")
    frames = await page.ev(f'[{WIN}.renderer.frames.filter((f) => f.ax).length, {WIN}.renderer.frames.filter((f) => f.legend).length]')
    n = await page.ev(FIRST_COLOUR)
    check('copyobj: both axes copied into the new figure, the legend with the lower', (frames, n[0] + n[1] > 40, n[2] + n[3] > 40), ([2, 1], True, True))
    await shot(page, 'copyobj.png')
    await command(page, "close all force; x = 1:20;\n   y = rand(1,20);\n   sz = rand(1,20);\n   bubblechart(x,y,sz,\"red\");")
    # the faces are red at 0.6 over white: (255, 102, 102); the edges whole red
    red = await page.ev(f"(() => {{ const c = {WIN}.canvas; const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; const n = [0, 0]; "
                        "for (let i = 0; i < d.length; i += 4) { if (d[i] > 230 && Math.abs(d[i + 1] - 102) < 25 && Math.abs(d[i + 2] - 102) < 25) n[0]++; "
                        "else if (d[i] > 200 && d[i + 1] < 40 && d[i + 2] < 40) n[1]++; } return n; })()")
    check('bubblechart: see-through red bubbles with red edges', (red[0] > 400, red[1] > 100), (True, True))
    await shot(page, 'bubbles.png')
    await command(page, "close all force; bubblechart([0 1 1.1], [0.5 0.5 0.5], [1 1 1], 'r'); xlim([0 1]); ylim([0 1])")
    await asyncio.sleep(0.4)
    # red to the right of the box: within the bubble's radius of the edge, none farther out
    side = await page.ev(f"(() => {{ const w = {WIN}, c = w.canvas, s = c.width / c.getBoundingClientRect().width; "
                         "const r = w.renderer.frames.find((f) => f.ax).rect, d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; "
                         "const e = (r.x + r.w) * s, n = [0, 0]; for (let y = Math.round(r.y * s); y < (r.y + r.h) * s; y++) for (let x = Math.ceil(e + 2 * s); x < Math.min(c.width, e + 60 * s); x++) { "
                         "const i = (y * c.width + x) * 4; if (d[i] > 200 && d[i + 1] < 160 && d[i + 2] < 160 && d[i] - d[i + 1] > 80) n[x < e + 12 * s ? 0 : 1]++; } "
                         "return [n[0], n[1], s, e, c.width, w.renderer.frames.length, PL.app.figures.wins.size]; })()")
    if not (side[0] > 10 and side[1] == 0):
        print('edge bubbles:', side)
        await shot(page, 'edge-fail.png')
    check('a bubble on the edge of the box is drawn whole, one outside it not at all', (side[0] > 10, side[1]), (True, 0))
    await command(page, 'close all force; clear; clc')
    check('series: no script errors', page.errors, [])


async def optimization(page):
    """The optimization functions on the page's SciPy: Display rows, a plot function's window, HiGHS."""
    out = await command(page, "clear; clc; close all force; o = optimoptions('fmincon', 'Display', 'iter', 'Algorithm', 'sqp');\n"
                              "[x, fval, flag] = fmincon(@(x) 100*(x(2)-x(1)^2)^2 + (1-x(1))^2, [0 0], [1 2], 1, [], [], [], [], [], o);\n"
                              "disp(round(x*1e4)/1e4)")
    check('optimization: fmincon in the page, with its iterations shown', (' Iter  F-count' in out, out.strip().endswith('0.5022    0.2489')), (True, True))
    out = await command(page, "x = intlinprog([8 1], 2, [-1 -2; -4 -1; 2 1], [14; -33; 20]); disp(x')")
    check('optimization: intlinprog on HiGHS in the page', out.strip().endswith('6.5000    7.0000'), True)
    await command(page, "o = optimoptions('fminunc', 'PlotFcn', @optimplotfval, 'Display', 'off');\n"
                        "x = fminunc(@(x) 100*(x(2)-x(1)^2)^2 + (1-x(1))^2, [-1.2 1], o);")
    check('optimization: a plot function draws its window', (await page.ev(f"{WIN}.fig.name"), await drawn(page, 1) > 0.005),
          ('Optimization Plot Functions', True))
    await shot(page, 'optimplot.png')
    await command(page, 'close all force; clear; clc')
    check('optimization: no script errors', page.errors, [])


async def symbolic(page):
    """Symbolic math in the page: SymPy loaded by the first command that needs it, results shown in the language's syntax."""
    out = await command(page, "clear; clc; close all force; syms x y\nf = x^2*sin(y)\ng = diff(f, x)")
    check('symbolic: SymPy loads on first use; a derivative shown in the language', out.rstrip().endswith('2*x*sin(y)'), True)
    out = await command(page, "s = solve(x^2 - 5*x + 6 == 0, x)")
    check('symbolic: solve gives a column of solutions', ('[2]' in out[-40:] and '[3]' in out[-40:]), True)
    out = await command(page, "syms u(t)\nsol = dsolve(diff(u, t) == -2*u, u(0) == 3)")
    check('symbolic: dsolve with a condition', out.rstrip().endswith('3*exp(-2*t)'), True)
    ws = await page.ev("PL.app.ws.rows.filter((r) => r.name === 'f').map((r) => r.cls || r.klass || r.class || r.value)")
    check('symbolic: the Workspace lists a sym', bool(ws), True)
    await command(page, "fplot(x^2 - 1, [-2 2])")
    check('symbolic: fplot of an expression draws', await drawn(page, 1) > 0.003, True)
    await shot(page, 'symbolic.png')
    out = await command(page, "syms C_1 C_2\nsyms u u_c u_r u_f k P_er positive real\nassume(0 < u_c < u_r < u_f)\n"
                              "Pe(u) = piecewise(u < u_c, 0, ...\n                  u_c <= u <= u_r, C_1 + C_2*u^k, ...\n"
                              "                  u_r < u <= u_f, P_er, ...\n                  u_f < u, 0)")
    check('symbolic: chained comparisons in assume and piecewise, conditions shown as written',
          out.rstrip().endswith('piecewise(u < u_c, 0, u_c <= u & u <= u_r, C_1 + C_2*u^k, u_r < u & u <= u_f, P_er, u_f < u, 0)'), True)
    await command(page, "close all force; fplot(subs(Pe, [u_c u_r u_f C_1 C_2 k P_er], [1 2 3 0 1 2 5]), [0 4])")
    check('symbolic: fplot of a piecewise expression draws', await drawn(page, 1) > 0.003, True)
    out = await command(page, "sol = solve([Pe(u_c) == 0; Pe(u_r) == P_er],[C_1 C_2]);\nsol.C_2")
    check('symbolic: solve through piecewise calls settled by the relations assumed',
          ('Unable' not in out[-300:], out.rstrip().endswith('-P_er/(u_c^k - u_r^k)')), (True, True))
    out = await command(page, "syms x(t) m c k F(t)\neq = m*diff(x,t,t) + c*diff(x,t) + k*x == F;\nsyms gamma omega_0\n"
                              "eq = subs(eq,[c k],[m*gamma m*omega_0^2])")
    check('symbolic: syms gamma makes a variable in the same command', out.rstrip().endswith('gamma*m*diff(x(t), t) + m*omega_0^2*x(t) + m*diff(x(t), t, 2) == F(t)'), True)
    out = await command(page, "eq = collect(eq,m)/m")
    check('symbolic: collect and division work on each side of an equation',
          out.rstrip().endswith('eq(t) =\n\ngamma*diff(x(t), t) + omega_0^2*x(t) + diff(x(t), t, 2) == F(t)/m'), True)
    await command(page, "close all force; syms x y\nu = sin(x^2 + y^2);\nv = cos(x*y);\n[X,Y] = meshgrid(-1:.1:1,-1:.1:1);\n"
                        "U = subs(u,[x y],{X,Y});\nV = subs(v,[x y],{X,Y});\nquiver(X,Y,U,V)")
    check('symbolic: quiver of symbolic numbers draws', await drawn(page, 1) > 0.003, True)
    await command(page, "close all force; syms t\nfpolarplot(sin(6*t))")
    check('symbolic: fpolarplot of an expression draws', await drawn(page, 1) > 0.003, True)
    await command(page, "close all force")
    out = await command(page, "syms m a g theta(t) r\neqn = subs(m*a == -m*g*sin(theta), a, r*diff(theta,2));\neqn = isolate(eqn,diff(theta,2))")
    check('symbolic: isolate a derivative', out.rstrip().endswith('diff(theta(t), t, 2) == -g*sin(theta(t))/r'), True)
    await command(page, 'close all force; clear; clc')
    check('symbolic: no script errors', page.errors, [])


DOC_INK = ("(() => [...document.querySelectorAll('.pl-help canvas.pl-doc-fig')].map((c) => { const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; "
           "let n = 0; for (let i = 0; i < d.length; i += 4) if (d[i] < 200 || d[i + 1] < 200 || d[i + 2] < 200) n++; return n / (d.length / 4); }))()")


async def docs(page):
    """Function pages in the Help panel: doc opens one, its examples' stored figures drawn by the figure renderer (single
    precision ones too), Run runs an example in the Command Window, Open in Editor makes a script of it, help links to the
    page, the function lists mark the names with pages, and a function without one keeps its summary page."""
    await command(page, "clear; clc; close all force")
    await command(page, "doc plot")
    ok = await until(page, "document.querySelectorAll('.pl-help .pl-doc-ex').length >= 3", 20)
    head = await page.ev("(() => { const h = document.querySelector('.pl-help'); return [h.querySelector('h2').textContent, h.querySelector('.pl-doc-summary').textContent, "
                         "[...h.querySelectorAll('h3')].map((e) => e.textContent).join('|')]; })()")
    check('docs: doc plot shows its page: summary, forms, inputs, outputs and examples', (ok, head[0], head[1].startswith('Lines and markers'),
          all(s in head[2] for s in ('Syntax', 'Inputs', 'Outputs', 'Examples'))), (True, 'plot', True, True))
    for k in range(4):
        await page.ev(f"document.querySelectorAll('.pl-help canvas.pl-doc-fig')[{k}]?.scrollIntoView(); 1")
        await asyncio.sleep(0.2)
    ink = await page.ev(DOC_INK)
    check("docs: each example's stored figure is drawn on the page", (len(ink) >= 4, all(v > 0.003 for v in ink)), (True, True))
    await page.ev("document.querySelector('.pl-help .pl-doc-tools button').click(); 1")
    await idle(page)
    out = await page.ev(OUTPUT)
    check('docs: Run runs the example in the Command Window, drawing its figure',
          ('x = linspace(0, 2*pi, 100);' in out, await drawn(page, 1) > 0.003), (True, True))
    n0 = await page.ev("PL.app.docs.length")
    await page.ev("document.querySelectorAll('.pl-help .pl-doc-tools button')[1].click(); 1")
    got = await until(page, f"PL.app.docs.length > {n0} && PL.app.current && PL.app.current.editor && PL.app.current.editor.value.includes('plot(x, y)')", 20)
    check('docs: Open in Editor makes a new script of the example', bool(got), True)
    made = await page.ev("PL.app.current.key")
    await page.ev("PL.app.current.setDirty(false); PL.app.closeDoc(PL.app.current); 1")
    await command(page, f"delete('{made}')")
    await command(page, "close all force; clc")
    out = await command(page, "help linspace")
    link = await page.ev("(() => { const a = [...PL.app.cmd.out.querySelectorAll('a[data-run]')].pop(); return a ? a.dataset.run : ''; })()")
    check('docs: help ends with a link to the page', ('Documentation, with examples: doc linspace' in out, link), (True, 'doc linspace'))
    await page.ev("[...PL.app.cmd.out.querySelectorAll('a[data-run]')].pop().click(); 1")
    got = await until(page, "document.querySelector('.pl-help h2')?.textContent === 'linspace'", 20)
    check('docs: the link opens the page', bool(got), True)
    await command(page, "doc surf")
    await until(page, "document.querySelectorAll('.pl-help canvas.pl-doc-fig').length >= 3", 20)
    await page.ev("document.querySelectorAll('.pl-help canvas.pl-doc-fig')[1].scrollIntoView(); 1")
    await asyncio.sleep(0.3)
    ink = await page.ev(DOC_INK)
    check('docs: a surface kept in single precision is drawn', (len(ink) >= 3, len(ink) >= 3 and ink[1] > 0.05), (True, True))
    await shot(page, 'doc-surf.png')
    # the lists first: a name in them without a page (the last, which the rounds of pages reach last)
    await command(page, "doc")
    await until(page, "document.querySelector('.pl-help .pl-fnlist a.has-doc')", 20)
    marks = await page.ev("(() => { const a = [...document.querySelectorAll('.pl-help .pl-fnlist a')]; return [a.filter(e => e.classList.contains('has-doc')).map(e => e.dataset.fn), a.filter(e => !e.classList.contains('has-doc')).map(e => e.dataset.fn)]; })()")
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'pylab-docs', 'index.json'), encoding='utf-8') as fh:
        paged = set(json.load(fh)['names'])
    marked, unmarked = marks
    check('docs: the function lists mark the names that have pages',
          ('plot' in marked, all(n in paged for n in marked), bool(unmarked) and not any(n in paged for n in unmarked)), (True, True, True))
    bare = unmarked[-1] if unmarked else 'plot'
    await command(page, f"doc {bare}")
    await until(page, f"document.querySelector('.pl-help h2')?.textContent === '{bare}'", 20)
    old = await page.ev("(() => { const h = document.querySelector('.pl-help'); return [!!h.querySelector('pre'), h.querySelectorAll('.pl-doc-ex').length]; })()")
    check('docs: a function without a page keeps its summary page', old, [True, 0])
    # an app's components are HTML over its stored figure, only to be looked at
    await command(page, "doc uibutton")
    await until(page, "document.querySelector('.pl-help .pl-doc-uilayer .pl-uictl')", 20)
    comps = await page.ev("(() => { const l = document.querySelector('.pl-help .pl-doc-uilayer'); return [l.querySelectorAll('.pl-uictl').length, l.hasAttribute('inert'), [...l.querySelectorAll('button')].map(b => b.textContent.trim())]; })()")
    check("docs: an app's components drawn over its figure, inert", comps, [2, True, ['Run', 'Hold']])
    await page.ev("PL.app.closeDoc(PL.app.docs.find(d => d.kind === 'help')); 1")
    await command(page, "clear; clc; close all force")
    check('docs: no script errors', page.errors, [])


LAYOUT = "JSON.stringify(PL.app.dock.layout((t) => t.id).root)"
GROUP_OF = "((k) => PL.app.dock.groups.indexOf(PL.app.toolTabs[k].group))"


async def windows(page):
    """The desktop's windows as tabs in groups: the default layout, a file over the Command Window, a tab dragged onto a
    strip (stacked) and onto a group's edge (split), a bar resizing two groups, Layout hiding and showing a window, a figure
    docked by its button and undocked again (the program told its WindowStyle and its docked size), a program's docked
    figure, a docked figure's tab closing it, docking every new figure, and the layout kept for the next visit."""
    await command(page, "clear; clc; close all force")
    await page.ev("PL.app.docs.slice().forEach((d) => { d.setDirty(false); PL.app.closeDoc(d); }); PL.app.resetLayout(); 1")
    await asyncio.sleep(0.4)
    lay = json.loads(await page.ev(LAYOUT))
    check('windows: the default layout: Current Folder over Details, the Command Window, the Workspace over the Command History',
          lay, {'split': 'row', 'sizes': lay.get('sizes'), 'parts': [
              {'split': 'col', 'sizes': [0.65, 0.35], 'parts': [{'tabs': ['tool:folder'], 'shown': 'tool:folder'}, {'tabs': ['tool:details'], 'shown': 'tool:details'}]},
              {'tabs': ['tool:cmd'], 'shown': 'tool:cmd'},
              {'split': 'col', 'sizes': [0.6, 0.4], 'parts': [{'tabs': ['tool:ws'], 'shown': 'tool:ws'}, {'tabs': ['tool:hist'], 'shown': 'tool:hist'}]}]})
    await command(page, "edit dockwin.m")
    above = await page.ev("(() => { const d = PL.app.docs.find((x) => x.key.endsWith('dockwin.m')); const a = d.group.el.getBoundingClientRect(), "
                          "b = PL.app.toolTabs.cmd.group.el.getBoundingClientRect(); return d.group !== PL.app.toolTabs.cmd.group && a.bottom <= b.top + 2 && Math.abs(a.left - b.left) < 3; })()")
    check('windows: a file opens in a group of its own over the Command Window', above, True)
    # a drag onto another strip: the Workspace stacked with the Command History
    x0, y0 = await middle(page, 'PL.app.toolTabs.ws.btn')
    x1, y1 = await page.ev("(() => { const r = PL.app.toolTabs.hist.group.strip.getBoundingClientRect(); return [r.right - 20, r.top + r.height / 2]; })()")
    began = await page.drag_to(x0, y0, x1, y1)
    await asyncio.sleep(0.3)
    stacked = await page.ev("(() => { const g = PL.app.toolTabs.hist.group; return [g === PL.app.toolTabs.ws.group, g.tabs.map((t) => t.key), g.active.key]; })()")
    check('windows: a tab dragged onto another strip stacks there, shown', (began, stacked), (True, [True, ['hist', 'ws'], 'ws']))
    # a drag onto a group's edge: the Workspace in a new group right of the Command Window
    x0, y0 = await middle(page, 'PL.app.toolTabs.ws.btn')
    x1, y1 = await page.ev("(() => { const r = PL.app.toolTabs.cmd.group.views.getBoundingClientRect(); return [r.right - 12, r.top + r.height / 2]; })()")
    began = await page.drag_to(x0, y0, x1, y1)
    await asyncio.sleep(0.3)
    beside = await page.ev("(() => { const w = PL.app.toolTabs.ws.group, c = PL.app.toolTabs.cmd.group; const a = w.el.getBoundingClientRect(), b = c.el.getBoundingClientRect(); "
                           "return [w !== c, w.tabs.length, a.left >= b.right - 2, Math.abs(a.top - b.top) < 3, PL.app.toolTabs.hist.group.tabs.length]; })()")
    check("windows: a tab dragged onto a group's edge splits it off on that side", (began, beside), (True, [True, 1, True, True, 1]))
    # the bar between the Command Window and the Workspace
    sash = await page.ev("(() => { const s = PL.app.toolTabs.ws.group.el.previousElementSibling; const r = s.getBoundingClientRect(); return s.classList.contains('pl-dk-sash') ? [r.left + r.width / 2, r.top + r.height / 2] : null; })()")
    w0 = await page.ev("PL.app.toolTabs.ws.group.el.getBoundingClientRect().width")
    if sash:
        await page.mouse('mouseMoved', sash[0], sash[1])
        await page.mouse('mousePressed', sash[0], sash[1])
        for k in range(1, 6):
            await page.mouse('mouseMoved', sash[0] - 16 * k, sash[1])
        await page.mouse('mouseReleased', sash[0] - 80, sash[1])
    w1 = await page.ev("PL.app.toolTabs.ws.group.el.getBoundingClientRect().width")
    check('windows: the bar between two groups resizes them', bool(sash) and 60 < w1 - w0 < 100, True)
    # Layout: a window closed and shown again, beside its partner
    await page.ev("PL.app.hideTool('details'); 1")
    gone = await page.ev("[PL.app.toolShown('details'), PL.app.pDetails.isConnected, PL.app.dock.tabs.some((t) => t.key === 'details')]")
    await page.ev("PL.app.showTab(PL.app.toolTabs.details); 1")
    back = await page.ev("(() => { const a = PL.app.toolTabs.folder.group.el.getBoundingClientRect(), b = PL.app.toolTabs.details.group.el.getBoundingClientRect(); "
                         "return [PL.app.toolShown('details'), b.top >= a.bottom - 2, Math.abs(a.left - b.left) < 3]; })()")
    check('windows: a window closed from Layout, then shown again under its partner', (gone, back), ([False, True, False], [True, True, True]))
    # a figure docked by its button, and undocked
    await command(page, "close all force; x = linspace(0, 2*pi); plot(x, sin(x))")
    await asyncio.sleep(0.3)
    await page.ev(f"{WIN}.btnDock.click(); 1")
    await asyncio.sleep(0.8)
    docked = await page.ev(f"(() => {{ const w = {WIN}; return [w.docked, !!w.el.closest('.pl-dk-views'), PL.app.figTabs.size, !!PL.app.figTabs.get(w.id).group]; }})()")
    out = await command(page, "s = get(gcf, 'WindowStyle')")
    check('windows: a figure docked by its button is a tab, and the program hears its WindowStyle', (docked, out.rstrip().endswith("'docked'")), ([True, True, 1, True], True))
    await asyncio.sleep(0.6)
    ink = await page.ev(INK)
    sz = await page.ev(f"(() => {{ const r = {WIN}.stage.getBoundingClientRect(); return [Math.floor(r.width), Math.floor(r.height)]; }})()")
    out = await command(page, "p = get(gcf, 'Position'); disp(p(3:4))")
    nums = [float(v) for v in out.strip().split('\n')[-1].split()] if out.strip() else []
    check("windows: a docked figure draws at its tab's size, the size the program sees", (ink > 0.003, nums == [float(v) for v in sz]), (True, True))
    await page.ev(f"{WIN}.btnDock.click(); 1")
    await asyncio.sleep(0.6)
    undocked = await page.ev(f"(() => {{ const w = {WIN}; return [w.docked, w.el.parentNode === PL.app.figLayer, PL.app.figTabs.size, !w.titlebar.hidden]; }})()")
    out = await command(page, "s = get(gcf, 'WindowStyle')")
    check('windows: undocked, it is a window again, and the program hears it', (undocked, out.rstrip().endswith("'normal'")), ([False, True, 0, True], True))
    # a figure the program docks, and closed from its tab
    await command(page, "close all force; f = figure('WindowStyle', 'docked'); bar([3 1 2])")
    await asyncio.sleep(0.6)
    n = await page.ev("PL.app.figTabs.size")
    await page.ev("[...PL.app.figTabs.values()][0].btn.querySelector('.x').click(); 1")
    await asyncio.sleep(0.4)
    out = await command(page, "n = numel(findobj('Type', 'figure'))")
    check("windows: a program's docked figure opens as a tab, and its tab's × closes it", (n, out.rstrip().endswith('0'), await page.ev("PL.app.figTabs.size")), (1, True, 0))
    # every new figure docked
    await page.ev("PL.app.figures.setDockNew(true); 1")
    await command(page, "figure; plot(1:5); figure; plot(5:-1:1)")
    await asyncio.sleep(0.6)
    both = await page.ev("(() => { const t = [...PL.app.figTabs.values()]; return [t.length, t.length === 2 && t[0].group === t[1].group]; })()")
    out = await command(page, "s = get(gcf, 'WindowStyle')")
    await page.ev("PL.app.figures.setDockNew(false); 1")
    check('windows: with docking of new figures on, each opens as a tab, together', (both, out.rstrip().endswith("'docked'")), ([2, True], True))
    await command(page, "close all force")
    # the layout kept for the next visit
    await asyncio.sleep(0.6)
    before = json.loads(await page.ev("JSON.stringify(PL.app.dock.layout((t) => PL.app.tabRef(t)).root)"))
    other = await open_page(f'{BASE}/pylab.html')
    try:
        await wait_engine(other)
        await until(other, "PL.app.docs.some((d) => d.key.endsWith('dockwin.m'))", 20)
        await asyncio.sleep(0.6)
        after = json.loads(await other.ev("JSON.stringify(PL.app.dock.layout((t) => PL.app.tabRef(t)).root)"))
    finally:
        await other.close()
    strip = lambda n: {'tabs': n['tabs']} if 'tabs' in n else {'split': n['split'], 'parts': [strip(q) for q in n['parts']]}
    check('windows: the layout is kept for the next visit, the file in its group', strip(after), strip(before))
    await shot(page, 'windows.png')
    await page.ev("PL.app.docs.slice().forEach((d) => { d.setDirty(false); PL.app.closeDoc(d); }); PL.app.resetLayout(); 1")
    await command(page, "delete dockwin.m; clear; clc")
    check('windows: no script errors', page.errors, [])


async def mapping(page):
    """Maps in the page: a world map with a route on it, geographic axes labelled in degrees, a shapefile written and read."""
    await command(page, "clear; clc; close all force; worldmap('Europe');\nplotm([59.33 48.86 41.9], [18.07 2.35 12.5], 'r-o', 'LineWidth', 2)")
    check('mapping: worldmap draws its frame, graticule, labels and the route', await drawn(page, 1) > 0.01, True)
    await shot(page, 'worldmap.png')
    await command(page, "close all force; geoplot([59.33 57.71 55.6], [18.07 11.97 13.0], 'b-o'); geolimits([54 61], [9 21])")
    labels = await page.ev(f"(() => {{ const w = {WIN}, f = w.renderer.frames.find((q) => q.ax); return [w.renderer.ticksFor(f.ax, 'x', f.rect).labels, w.renderer.ticksFor(f.ax, 'y', f.rect).labels]; }})()")
    check('mapping: geographic axes label their ticks in degrees east and north', (any(s.endswith('°E') for s in labels[0]), any(s.endswith('°N') for s in labels[1])), (True, True))
    await shot(page, 'geoplot.png')
    out = await command(page, "S = struct('Geometry', {'Point', 'Point'}, 'X', {18.07, 11.97}, 'Y', {59.33, 57.71}, 'Name', {'Stockholm', 'Goteborg'});\n"
                              "shapewrite(S, 'cities.shp'); T = shaperead('cities'); disp(T(2).Name); delete('cities.*')")
    check('mapping: a shapefile written and read in the page', out.rstrip().endswith('Goteborg'), True)
    await world_data(page)
    await basemaps(page)
    await command(page, 'close all force; clear; clc')
    check('mapping: no script errors', page.errors, [])


async def world_data(page):
    """Natural Earth's coastline and land, fetched from jsDelivr when a program asks for them."""
    out = await command(page, "clear; clc; close all force; load coastlines; disp([numel(coastlat) == numel(coastlon), numel(coastlat) > 5000, nnz(isnan(coastlat)) > 100])")
    check('mapping: load coastlines gives coastlat and coastlon, the lines parted by NaN', out.rstrip().endswith('1   1   1'), True)
    out = await command(page, "worldmap world; h = geoshow('landareas.shp', 'FaceColor', [0.6 0.8 0.5]); disp([numel(h) > 100, strcmp(get(h(1), 'Type'), 'patch')])")
    check('mapping: geoshow landareas.shp draws the land on a world map', out.rstrip().endswith('1   1'), True)
    await shot(page, 'landareas.png')


def tile_png(z, x, y):
    """A 256 x 256 tile of one colour, which tells its column, row and zoom level."""
    import struct as st
    import zlib
    rgb = bytes(((x * 37) % 256, (y * 53) % 256, 40 + 10 * z))
    raw = b''.join(b'\x00' + rgb * 256 for _ in range(256))
    chunk = lambda t, d: st.pack('>I', len(d)) + t + d + st.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', st.pack('>IIBBBBB', 256, 256, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')


async def basemaps(page):
    """Basemaps: none fetched until a program names one; then the tiles over the view only, each where its
    longitude and latitude are (Web Mercator rows drawn into the axes' latitude), with CORS so that the figure
    can be saved; Natural Earth's land and water for grayland. The tiles come from a host this test answers."""
    import base64
    import math
    asked = []

    async def answer(p):
        url = p['request']['url']
        asked.append(url)
        z, x, y = (int(v) for v in url.rsplit('/', 3)[1:3] + [url.rsplit('/', 1)[1].split('.')[0]])
        await page.call('Fetch.fulfillRequest', {'requestId': p['requestId'], 'responseCode': 200, 'body': base64.b64encode(tile_png(z, x, y)).decode(),
                                                 'responseHeaders': [{'name': 'Content-Type', 'value': 'image/png'}, {'name': 'Access-Control-Allow-Origin', 'value': '*'}]}, session=page.sid)
    page.handlers['Fetch.requestPaused'] = answer
    await page.call('Fetch.enable', {'patterns': [{'urlPattern': 'https://tiles.pylab-test.invalid/*'}]}, session=page.sid)
    try:
        await command(page, "clear; clc; close all force; addCustomBasemap('testtiles', 'https://tiles.pylab-test.invalid/${z}/${x}/${y}.png', 'Attribution', 'Test tiles by PyLAB');"
                            "figure('Position', [100 100 560 420]); geoplot([59.33 57.71], [18.07 11.97], 'k'); geolimits([54 61], [9 21])")
        await drawn(page, 1)
        await asyncio.sleep(0.5)
        check('basemaps: geographic axes fetch nothing until a basemap is named', asked, [])
        await command(page, 'geobasemap testtiles')
        await page.ev(f'{WIN}.ready(1).then(() => 1)', timeout=60)
        await asyncio.sleep(0.5)
        zs = {int(u.rsplit('/', 3)[1]) for u in asked}
        check('basemaps: the tiles over the view, at one zoom level, at most 64', (len(zs), 0 < len(asked) <= 64), (1, True))
        z = zs.pop() if zs else 0
        n = 2 ** z
        pts = [(55.5, 19.0), (60.5, 11.0), (57.5, 14.5)]       # away from the grid lines (every degree north, every 2 east)
        px = await page.ev(f"""(() => {{ const w = {WIN}, f = w.renderer.frames.find((q) => q.ax && q.ax.geo), g = w.canvas.getContext('2d'), d = window.devicePixelRatio || 1;
            return {json.dumps(pts)}.map(([la, lo]) => Array.from(g.getImageData(Math.round(f.fr.fx(lo) * d), Math.round(f.fr.fy(la) * d), 1, 1).data).slice(0, 3)); }})()""")
        want = []
        for la, lo in pts:
            tx = math.floor((lo + 180) / 360 * n)
            s_ = math.sin(math.radians(la))
            ty = math.floor((0.5 - math.log((1 + s_) / (1 - s_)) / (4 * math.pi)) * n)
            want.append([(tx * 37) % 256, (ty * 53) % 256, 40 + 10 * z])
        check('basemaps: each tile drawn where its longitude and latitude are', px, want)
        await shot(page, 'basemap-tiles.png')
        out = await command(page, "cd('/home/user'); saveas(gcf, 'tiles.svg'); s = fileread('tiles.svg'); F = getframe(gcf); delete('tiles.svg');"
                                  "disp([numel(strfind(s, '<image')) >= 1, ~isempty(strfind(s, 'Test tiles by PyLAB')), size(F.cdata, 1) > 100])")
        check('basemaps: the figure saved with its map and attribution, and getframe reads it', out.rstrip().endswith('1   1   1'), True)
        k = len(asked)
        await command(page, 'geobasemap none')
        await asyncio.sleep(0.5)
        check('basemaps: none asks for nothing more', len(asked), k)
    finally:
        await page.call('Fetch.disable', session=page.sid)
        page.handlers.pop('Fetch.requestPaused', None)
    await command(page, 'geobasemap grayland')
    await page.ev(f'{WIN}.ready(1).then(() => 1)', timeout=60)
    await asyncio.sleep(0.5)
    px = await page.ev(f"""(() => {{ const w = {WIN}, f = w.renderer.frames.find((q) => q.ax && q.ax.geo), g = w.canvas.getContext('2d'), d = window.devicePixelRatio || 1;
        return [[55.5, 19.0], [57.5, 14.5]].map(([la, lo]) => Array.from(g.getImageData(Math.round(f.fr.fx(lo) * d), Math.round(f.fr.fy(la) * d), 1, 1).data).slice(0, 3)); }})()""")
    check('basemaps: grayland draws Natural Earth\'s water white and its land grey', px, [[255, 255, 255], [194, 194, 194]])
    await shot(page, 'basemap-grayland.png')


APP_CLASS = """classdef CountApp < matlab.apps.AppBase
    properties (Access = public)
        UIFigure  matlab.ui.Figure
        Grid      matlab.ui.container.GridLayout
        Field     matlab.ui.control.NumericEditField
        Button    matlab.ui.control.Button
        Knob      matlab.ui.control.Knob
        Gauge     matlab.ui.control.Gauge
    end
    methods (Access = private)
        function ButtonPushed(app, event)
            app.Field.Value = app.Field.Value + 1;
            app.Gauge.Value = 10 * app.Field.Value;
        end
    end
    methods (Access = private)
        function createComponents(app)
            app.UIFigure = uifigure('Visible', 'off', 'Position', [100 100 360 260], 'Name', 'Count');
            app.Grid = uigridlayout(app.UIFigure, [2 2]);
            app.Grid.RowHeight = {22, '1x'};
            app.Field = uieditfield(app.Grid, 'numeric');
            app.Button = uibutton(app.Grid, 'push', 'Text', 'Add');
            app.Button.ButtonPushedFcn = createCallbackFcn(app, @ButtonPushed, true);
            app.Knob = uiknob(app.Grid);
            app.Gauge = uigauge(app.Grid);
            app.UIFigure.Visible = 'on';
        end
    end
    methods (Access = public)
        function app = CountApp
            createComponents(app)
            registerApp(app, app.UIFigure)
            if nargout == 0
                clear app
            end
        end
        function delete(app)
            delete(app.UIFigure)
        end
    end
end
"""


async def apps(page):
    """Classes and apps in the page: an app class run and its button pushed; the app designer laying out an app, writing and running it, and opening it again."""
    await page.ev(f"PL.engine.fs('write', {{ path: '/home/user/CountApp.m', data: {json.dumps(APP_CLASS)} }}).then(() => 1)")
    await command(page, "clear; clc; close all force; cd('/home/user'); app = CountApp;")
    ok = await until(page, "document.querySelectorAll('.pl-ua').length >= 4", 15)
    check('apps: an app class makes its window and components in a grid', bool(ok), True)
    for _ in range(3):
        await page.ev("(() => { [...document.querySelectorAll('.pl-ua-button')].find((b) => b.textContent === 'Add').click(); return 1; })()")
        await asyncio.sleep(0.5)
    out = await command(page, 'disp([app.Field.Value app.Gauge.Value])')
    check('apps: its button calls the app\'s method', out.rstrip().endswith('3    30'), True)
    shown = await page.ev("(() => { const f = document.querySelector('.pl-ua-edit input'); const g = document.querySelector('.pl-ua-gauge svg line.needleline'); return [f && f.value, !!g, !!document.querySelector('.pl-ua-knob svg circle.dot')]; })()")
    check('apps: the page shows the new value, the gauge and the knob', shown, ['3', True, True])
    await shot(page, 'app-count.png')
    await command(page, "delete(app); clc; if exist('HiApp.m', 'file'), delete('HiApp.m'), end")
    await page.ev("PL.designer.open(null).then(() => 1)")
    await page.ev("""(() => { const D = PL.designer; D.app.name = 'HiApp'; D.app.title = 'Hi'; D.app.w = 320; D.app.h = 160; D.add('label'); D.add('editfield'); D.add('button');
        const [lab, ed, btn] = D.app.comps; lab.props.Text = 'Name:'; lab.x = 20; lab.y = 110; ed.x = 90; ed.y = 110; ed.w = 150; btn.x = 90; btn.y = 70; btn.props.Text = 'Greet';
        btn.callback = 'GreetPushed'; D.bodies.GreetPushed = "app.Label.Text = ['Hi ' app.EditField.Value];"; D.select(btn); return 1; })()""")
    check('apps: the designer shows the window with its three components and the inspector', await page.ev("[document.querySelectorAll('.pl-ad-comp').length, !!document.querySelector('.pl-ad-inspector textarea')]"), [3, True])
    await shot(page, 'designer.png')
    await page.ev("PL.designer.run().then(() => { PL.designer.close(); return 1; })")
    ok = await until(page, "[...document.querySelectorAll('.pl-ua-button')].some((b) => b.textContent === 'Greet')", 15)
    check('apps: Run writes the class and runs it', bool(ok), True)
    await page.ev("(() => { const ed = document.querySelector('.pl-ua-edit input'); ed.focus(); ed.value = 'Ada'; ed.dispatchEvent(new Event('blur')); return 1; })()")
    await asyncio.sleep(0.5)
    await page.ev("(() => { [...document.querySelectorAll('.pl-ua-button')].find((b) => b.textContent === 'Greet').click(); return 1; })()")
    ok = await until(page, "[...document.querySelectorAll('.pl-ua-label .txt')].some((e) => e.textContent === 'Hi Ada')", 10)
    check('apps: the callback written in the designer runs', bool(ok), True)
    await page.ev("PL.designer.open('/home/user/HiApp.m').then(() => 1)")
    again = await page.ev("[PL.designer.app.comps.map((c) => c.name), PL.designer.bodies.GreetPushed, PL.designer.app.title]")
    check('apps: the designer opens the app it wrote again, layout and callback code', again,
          [['Label', 'EditField', 'Button'], "app.Label.Text = ['Hi ' app.EditField.Value];", 'Hi'])
    # Code, a callback changed in the Editor (not saved), and back with Design App on the EDITOR tab
    await page.ev('PL.designer.showCode().then(() => 1)')
    shown = await page.ev("[!PL.designer.el, PL.app.current && PL.app.current.key, PL.app.designBtn.disabled]")
    check('apps: Code shows the class in the Editor, and Design App there can take it back', shown, [True, '/home/user/HiApp.m', False])
    lint = await page.ev("PL.engine.call('lint', PL.app.current.editor.value)")
    check("apps: the Editor's check finds nothing wrong with the app's class", lint, [])
    await page.ev("""(() => { const d = PL.app.current; d.editor.value = d.editor.value.replace("['Hi ' app", "['Hello ' app"); d.setDirty(true); PL.app.updateRunButtons(); PL.app.designBtn.click(); return 1; })()""")
    ok = await until(page, "PL.designer.el && (PL.designer.bodies.GreetPushed || '').includes('Hello')", 10)
    check('apps: Design App opens the layout again, with the callback as the Editor has it', bool(ok), True)
    await page.ev('PL.designer.save().then(() => 1)')
    synced = await page.ev("(() => { const d = PL.app.current; return [d.dirty, d.editor.value === d.saved, d.editor.value.includes(\"['Hello ' app\")]; })()")
    check("apps: the designer's save puts the class into the Editor tab, which has nothing left to save", synced, [False, True, True])
    await page.ev('PL.designer.close(); 1')
    await command(page, "close all force; delete('HiApp.m'); delete('CountApp.m'); clear; clc")
    check('apps: no script errors', page.errors, [])


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


INSP = 'PL.app.figures.inspector'


async def insp_pick(page, expr):
    """Click the canvas at the middle of what expr (run with w, the window, and c, its canvas box) gives as [x, y, w, h]."""
    b = await page.ev(f"(() => {{ const w = {WIN}; const c = w.canvas.getBoundingClientRect(); const r = {expr}; "
                      "return r && [c.left + r.x + r.w / 2, c.top + r.y + r.h / 2]; })()")
    if b:
        await page.click(*b)
    return b


async def insp_type(page, name, text):
    """Type text into the editor's field for property name, as a person does (all of it replaced), and press Enter."""
    await page.ev(f"(() => {{ const i = {INSP}.fields.get({json.dumps(name)}).input; i.focus(); i.select(); return 1; }})()")
    await page.call('Input.insertText', {'text': text}, session=page.sid)
    await page.key('Enter')


async def insp_field(page, name, js):
    """Run js with f, the editor's field for property name."""
    return await page.ev(f"(() => {{ const f = {INSP}.fields.get({json.dumps(name)}); {js} }})()")


async def property_editor(page):
    """The figure's property editor: the toolbar's edit tool, a click picking
    a part of the figure, its fields setting properties, the program kept
    from the clicks, inspect and plotedit."""
    await command(page, 'close all; clicks = 0; x = 0:10; h = plot(x, x.^2, "o-", "DisplayName", "sq"); title("Squares"); '
                        'xlabel("x"); legend; colorbar; set(gcf, "WindowButtonDownFcn", "clicks = clicks + 1;");')
    await until(page, 'PL.app.figures.wins.size === 1')
    await asyncio.sleep(0.6)
    await page.ev(f"{WIN}.toolBtns.edit.click(); 1")
    label = await until(page, f"{INSP} && !{INSP}.el.hidden && {INSP}.data && {INSP}.data.label")
    check("the toolbar's arrow opens the property editor on the figure", (label, await page.ev(f"{WIN}.tool")), ('Figure 1', 'edit'))
    check("the editor lists the figure's objects", await page.ev(f"[...{INSP}.tree.children].map(b => b.textContent)"),
          ['Figure 1', "Axes 'Squares'", "Title 'Squares'", "X label 'x'", 'Y label', "Line 'sq'", 'Legend', 'Colorbar', 'Label'])
    px, py = await in_axes(page, WIN, 5, 25)
    await page.click(px, py)
    check('a click on the line shows the line', await until(page, f"{INSP}.data.type === 'line' && {INSP}.data.label"), "Line 'sq'")
    check('the program heard no click', 'clicks =\n\n     0' in (await command(page, 'clicks'))[-30:], True)
    await insp_pick(page, 'w.renderer.textBoxes.get(w.fig.axes[0].title.id)')
    check('a click on the title shows its text object', await until(page, f"{INSP}.data.type === 'text' && {INSP}.data.label"), "Text 'Squares'")
    await insp_pick(page, 'w.renderer.frames.find(f => f.legend).rect')
    check('... on the legend, the legend', await until(page, f"{INSP}.data.type === 'legend' && {INSP}.data.label"), 'Legend')
    await insp_pick(page, 'w.renderer.frames.find(f => f.colorbar).rect')
    check('... on the colorbar, the colorbar', await until(page, f"{INSP}.data.type === 'colorbar' && {INSP}.data.label"), 'Colorbar')
    x, y, w, h = await frame_box(page)
    await page.click(x - 14, y + h / 2)
    check('... by the tick labels, the axes', await until(page, f"{INSP}.data.type === 'axes' && {INSP}.data.label"), "Axes 'Squares'")
    check('what is picked is outlined', await page.ev(f"{WIN}.selection === {WIN}.fig.axes[0].id && !!{WIN}.selectionBox({WIN}.selection)"), True)
    await page.ev(f"[...{INSP}.tree.children].find(b => b.textContent.startsWith('Title')).click(); 1")
    await until(page, f"{INSP}.data.type === 'text' && {INSP}.fields.has('Rotation')")
    await insp_type(page, 'Rotation', '90')
    await until(page, f"{WIN}.fig.axes[0].title.rotation === 90", 5)
    await asyncio.sleep(0.3)
    box = 'w.renderer.textBoxes.get(w.fig.axes[0].{0})'
    check('a title turned by 90 in the editor is drawn upright, above its axes',
          await page.ev(f"(() => {{ const w = {WIN}; const b = {box.format('title.id')}; const r = w.renderer.frames[0].rect; return [b.h > 2 * b.w, b.y + b.h <= r.y]; }})()"),
          [True, True])
    await page.ev(f"[...{INSP}.tree.children].find(b => b.textContent.startsWith('Y label')).click(); 1")
    await until(page, f"{INSP}.data.type === 'text' && {INSP}.fields.get('Rotation').input.value === '90'")
    await command(page, 'ylabel("height")')
    await insp_type(page, 'Rotation', '0')
    await until(page, f"{WIN}.fig.axes[0].ylabel.rotation === 0", 5)
    await asyncio.sleep(0.3)
    check('a y label turned to 0 lies flat, left of the tick labels',
          await page.ev(f"(() => {{ const w = {WIN}; const b = {box.format('ylabel.id')}; const r = w.renderer.frames[0].rect; return [b.w > 2 * b.h, b.x + b.w < r.x - 10]; }})()"),
          [True, True])
    check("where a title stands is shown, not offered", await insp_field(page, 'Position', "return f.r.querySelector('output').textContent.endsWith('placed by its axes');"), True)
    await page.ev(f"[...{INSP}.tree.children].find(b => b.textContent.startsWith('Axes')).click(); 1")
    await until(page, f"{INSP}.data.type === 'axes'")
    await insp_field(page, 'XGrid', 'f.input.click(); return 1;')
    await asyncio.sleep(0.6)
    check('a check box sets XGrid', "g =\n\n    'on'" in (await command(page, "g = get(gca, 'XGrid')"))[-30:], True)
    await insp_type(page, 'XLim', '[0 20]')
    await asyncio.sleep(0.6)
    check('a limit typed and Enter sets it', 'xl =\n\n     0    20' in (await command(page, 'xl = xlim'))[-30:], True)
    await insp_type(page, 'XLim', '[5 1]')
    await until(page, f"!{INSP}.msg.hidden", 5)
    check("a value refused says why, beside set's message, and the field shows the value kept",
          await page.ev(f"[{INSP}.msg.textContent.startsWith('XLim: Value must be'), {INSP}.fields.get('XLim').input.value]"), [True, '[0 20]'])
    await page.ev(f"(() => {{ const i = {INSP}.fields.get('XLabel').input; i.focus(); i.select(); return 1; }})()")
    await page.call('Input.insertText', {'text': 'Time'}, session=page.sid)
    await page.key('Escape')
    check('Escape in a field puts back its value', await insp_field(page, 'XLabel', 'return f.input.value;'), 'x')
    await page.ev(f"[...{INSP}.tree.children].find(b => b.textContent.startsWith('Line')).click(); 1")
    await until(page, f"{INSP}.data.type === 'line'")
    await insp_field(page, 'Color', "const s = f.r.querySelector('input[type=color]'); s.value = '#ff0000'; s.dispatchEvent(new Event('change')); return 1;")
    await insp_field(page, 'LineStyle', "f.input.value = '--'; f.input.dispatchEvent(new Event('change')); return 1;")
    await asyncio.sleep(0.8)
    check("the tree picks the line; a colour and a line style are set and drawn",
          ('c =\n\n     1     0     0' in (await command(page, "c = get(h, 'Color')"))[-30:], await page.ev(f"{WIN}.fig.axes[0].children[0].lineStyle")),
          (True, '--'))
    await shot(page, 'property-editor.png')
    await command(page, "set(h, 'LineWidth', 3)")
    check("a change the program makes shows in the editor", await until(page, f"{INSP}.fields.get('LineWidth').input.value === '3'", 5), True)
    await page.ev(f"{WIN}.toolBtns.edit.click(); 1")
    check('the arrow again leaves edit mode and closes the editor', await page.ev(f"[{INSP}.el.hidden, {WIN}.tool, {WIN}.el.classList.contains('is-editing')]"),
          [True, None, False])
    await command(page, 'inspect(gca)')
    check('inspect(h) opens it on h', await until(page, f"!{INSP}.el.hidden && {INSP}.data && {INSP}.data.type"), 'axes')
    await command(page, 'plotedit on')
    check('plotedit on and off', [await page.ev(f"{WIN}.tool")] + [(await command(page, 'plotedit off')) and await page.ev(f"[{WIN}.tool, {INSP}.el.hidden]")],
          ['edit', [None, True]])
    await command(page, "close all; f = figure('MenuBar', 'none', 'ToolBar', 'none'); presses = 0; "
                        "b = uicontrol('String', 'Go', 'Position', [20 20 80 30], 'Callback', 'presses = presses + 1;');")
    await until(page, 'PL.app.figures.wins.size === 1')
    await asyncio.sleep(0.5)
    await command(page, 'plotedit(f, "on")')
    await page.ev(f"{WIN}.ui.layer.querySelector('.pl-uictl').dispatchEvent(new PointerEvent('pointerdown', {{ bubbles: true }})); "
                  f"{WIN}.ui.layer.querySelector('.pl-uictl').click(); 1")
    check("in edit mode a click on a control picks it and does not press it (in a window without the toolbar too)",
          [await until(page, f"{INSP}.data && {INSP}.data.type === 'uicontrol' && {INSP}.data.label"),
           'presses =\n\n     0' in (await command(page, 'presses'))[-30:], await page.ev(f"{WIN}.ui.layer.querySelector('.pl-uictl').classList.contains('is-inspected')")],
          ["UIControl 'Go'", True, True])
    await insp_type(page, 'String', 'Stop')
    await until(page, f"{WIN}.ui.layer.querySelector('.pl-uictl').textContent === 'Stop'", 5)
    check("its String changed there is drawn, and the editor stays open in a window without the toolbar",
          await page.ev(f"[{WIN}.ui.layer.querySelector('.pl-uictl').textContent, {INSP}.el.hidden, {WIN}.tool]"), ['Stop', False, 'edit'])
    await command(page, 'close all')
    check('closing the figure closes its editor', await page.ev(f"{INSP}.el.hidden"), True)



async def editor_draws(page):
    """Properties changed in the property editor are drawn: each change in
    this list (each once ignored by the drawing) changes the figure's
    pixels. The object is found in the editor's tree by its label."""
    look = ("(() => { const w = [...PL.app.figures.wins.values()].pop(); const c = w.canvas; "
            "const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let h = 0; "
            "for (let i = 0; i < d.length; i += 4) h = (h * 31 + d[i] * 65536 + d[i + 1] * 256 + d[i + 2]) | 0; return h; })()")
    change = ("(async (who, name, payload) => { const w = [...PL.app.figures.wins.values()].pop(); const v0 = w.fig.version; "
              "const t = (await PL.engine.call('inspect_object', w.fig.id)).tree.find((n) => n.label.startsWith(who)); "
              "if (!t) return 'no ' + who; const r = await PL.engine.call('inspect_change', t.id, name, JSON.stringify(payload)); "
              "for (let i = 0; i < 40 && w.fig.version === v0; i++) await new Promise((res) => setTimeout(res, 25)); "
              "await new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res))); return r.error || null; })")
    on, red = {'kind': 'onoff', 'value': True}, {'kind': 'color', 'value': [1, 0, 0]}
    cases = [
        ("plot(1:5); title('T'); legend('a'); colorbar;", [
            ('Axes', 'YTickLabelRotation', {'kind': 'number', 'value': '45'}), ('Axes', 'TickLength', {'kind': 'array', 'value': '[0.04 0.1]'}),
            ('Axes', 'XMinorTick', on), ('Axes', 'FontWeight', {'kind': 'enum', 'value': 'bold'}),
            ('Axes', 'TitleFontSizeMultiplier', {'kind': 'number', 'value': '2'}), ('Axes', 'Subtitle', {'kind': 'lines', 'value': ['sub']}),
            ('Legend', 'Title', {'kind': 'text', 'value': 'Key'}), ('Colorbar', 'Direction', {'kind': 'enum', 'value': 'reverse'}),
            ('Colorbar', 'TickDirection', {'kind': 'enum', 'value': 'out'}), ('Colorbar', 'Box', {'kind': 'onoff', 'value': False})]),
        ("plot(1:5); grid on; patch([1 3 3], [1 1 4], 'r');", [('Axes', 'Layer', {'kind': 'enum', 'value': 'top'})]),
        ("bar([1 2 3]);", [('Bar', 'BarWidth', {'kind': 'number', 'value': '0.3'}), ('Bar', 'YData', {'kind': 'array', 'value': '[3 1 2]'})]),
        ("scatter(1:5, 1:5, 100, 'filled');", [('Scatter', 'MarkerFaceAlpha', {'kind': 'number', 'value': '0.2'}), ('Scatter', 'MarkerEdgeColor', red),
                                              ('Scatter', 'LineWidth', {'kind': 'number', 'value': '3'})]),
        ("stem(1:5);", [('Stem', 'MarkerFaceColor', red)]),
        ("pie([1 2 3]);", [('Patch', 'EdgeColor', red)]),
        ("polarplot(1:5);", [('Line', 'Visible', {'kind': 'onoff', 'value': False}), ('PolarAxes', 'GridColor', red)]),
        ("surf(peaks(10));", [('Axes', 'XDir', {'kind': 'enum', 'value': 'reverse'}), ('Axes', 'XColor', red)]),
    ]
    undrawn = []
    for code, changes in cases:
        await command(page, 'close all; figure; ' + code)
        await until(page, 'PL.app.figures.wins.size === 1')
        await asyncio.sleep(0.4)
        for who, name, payload in changes:
            before = await page.ev(look)
            err = await page.ev(f"{change}({json.dumps(who)}, {json.dumps(name)}, {json.dumps(payload)})")
            if err or await page.ev(look) == before:
                undrawn.append(f'{who} {name}' + (f' ({err})' if err else ''))
    check('properties changed in the editor are drawn (axes ticks and fonts, subtitle, legend title, colorbar, Layer, bars, '
          'scatter, stem and pie marks, polar axes, 3-D axis direction and colour)', undrawn, [])
    await command(page, 'close all')



async def language_additions(page):
    """Packages, enumerations, arguments blocks and dictionaries in the page's engine."""
    files = {
        '/home/user/langtest/+lt/twice.m': 'function y = twice(x)\ny = 2 * x;\nend\n',
        '/home/user/langtest/Hue.m': 'classdef Hue\n  enumeration\n    Red, Blue\n  end\nend\n',
        '/home/user/langtest/scaled.m': 'function y = scaled(x, opts)\n  arguments\n    x (1,:) double {mustBePositive}\n    opts.By (1,1) double = 2\n  end\n  y = x * opts.By;\nend\n',
    }
    await page.ev("PL.engine.fs('mkdir', { path: '/home/user/langtest/+lt' }).then(() => 1)")
    for path, text in files.items():
        await page.ev(f"PL.engine.fs('write', {{ path: {json.dumps(path)}, data: {json.dumps(text)} }}).then(() => 1)")
    await command(page, "cd /home/user/langtest")
    out = await command(page, 'a = lt.twice(4), import lt.*, b = twice(5), h = Hue.Blue, c = scaled([1 2], By=3), '
                              'd = dictionary(["x" "y"], [1 2]), try, scaled(-1), catch e, disp(e.message), end')
    tail_ = out[-700:]
    check('in the page: a package function, import, an enumeration member, name=value arguments, a dictionary and a validator\'s error',
          ['a =\n\n     8' in tail_, 'b =\n\n    10' in tail_, 'Hue enumeration' in tail_ and 'Blue' in tail_, 'c =\n\n     3     6' in tail_,
           'dictionary (string ⟼ double) with 2 entries:' in tail_, 'Invalid argument at position 1. Value must be positive.' in tail_], [True] * 6)
    await command(page, 'cd /home/user')



async def signal_processing(page):
    """Signal processing on the page's SciPy: a filter and its numbers, and the forms that draw (freqz, findpeaks, pwelch, spectrogram)."""
    out = await command(page, "close all; [b, a] = butter(4, 0.2); y = filtfilt(b, a, ones(1, 50)); v = round(y(25)*1e6), "
                              "[pks, locs] = findpeaks([0 2 1 3 1 4 1])")
    check('in the page: butter and filtfilt pass a constant unchanged; findpeaks finds the peaks',
          ['v =\n\n     1000000' in out[-300:], 'locs =\n\n     2     4     6' in out[-300:]], [True, True])
    await command(page, "figure; freqz(b, a); figure; findpeaks(sin(0:0.2:20)); figure; pwelch(randn(1000, 1)); figure; spectrogram(randn(1, 4000), [], [], [], 1000);")
    await until(page, 'PL.app.figures.wins.size === 4')
    await asyncio.sleep(0.8)
    drawn = await page.ev("[...PL.app.figures.wins.values()].map(w => [w.fig.axes.length, w.fig.axes.reduce((n, ax) => n + ax.children.length, 0)])")
    check('freqz draws magnitude and phase (two axes); findpeaks, pwelch and spectrogram draw theirs', [d[0] >= 1 and d[1] >= 1 for d in drawn] + [drawn[0][0]],
          [True, True, True, True, 2])
    await shot(page, 'signal.png')
    await command(page, 'close all')


async def regression_fitting(page):
    """Regression and curve fitting on the page's NumPy and SciPy: a linear model shown, a curve fit and its plot, and the residuals."""
    out = await command(page, "close all; x = (1:20)'; y = 1 + 2*x + 0.3*cos(3*x); mdl = fitlm(x, y)")
    check('in the page: fitlm shows the model, its estimates and R-squared',
          ['Linear regression model:' in out, 'y ~ 1 + x1' in out, 'Estimate' in out, 'R-squared' in out], [True] * 4)
    out = await command(page, "f = fit(x, y, 'poly1'); c = round(coeffvalues(f)*100), [tf, p] = islocalmax([1 3 2 5 4]); w = find(tf)")
    check('fit gives the line; islocalmax finds the peaks', ['c =\n\n   200    98' in out[-400:], 'w =\n\n     2     4' in out[-400:]], [True, True])
    await command(page, "figure; plot(f, x, y); figure; plotResiduals(mdl, 'fitted'); figure; plot(fit(x, y, 'smoothingspline'), x, y);")
    await until(page, 'PL.app.figures.wins.size === 3')
    await asyncio.sleep(0.8)
    drawn = await page.ev("[...PL.app.figures.wins.values()].map(w => w.fig.axes.reduce((n, ax) => n + ax.children.length, 0))")
    check('plot(f, x, y) draws the data and the fit; plotResiduals its points', [d >= 1 for d in drawn] + [drawn[0] >= 2], [True, True, True, True])
    await shot(page, 'regression.png')
    await command(page, 'close all')


async def files_and_tools(page):
    """In the page: HDF5 through h5py, a video of a figure through Pillow, an animated line, breakpoints from commands in the Editor,
    stopping at an error, the clipboard, the profiler and the diary."""
    await command(page, "close all; cd /home/user; for f = {'p.h5', 'f.avi', 'd.txt'}, if isfile(f{1}), delete(f{1}); end, end; fid = fopen('stopper.m', 'w'); fprintf(fid, 'function y = stopper(x)\\ny = 2*x;\\nz = y + 1;\\nend\\n'); fclose(fid); "
                        "fid = fopen('errfun.m', 'w'); fprintf(fid, 'function errfun()\\nx = 5;\\nerror(''boom'');\\nend\\n'); fclose(fid);")
    out = await command(page, "h5create('p.h5', '/x', [2 3]); h5write('p.h5', '/x', [1 2 3; 4 5 6]); y = h5read('p.h5', '/x')")
    check('in the page: h5py loads, and h5read gives the matrix back', 'y =\n\n     1     2     3\n     4     5     6' in out[-200:], True)
    out = await command(page, "figure; plot(1:3); v = VideoWriter('f.avi'); open(v); for k = 1:3, writeVideo(v, getframe(gcf)); end; close(v); r = VideoReader('f.avi'); n = r.NumFrames, close all")
    check('a video of getframe frames written and read back', 'n =\n\n     3' in out[-120:], True)
    await command(page, "an = animatedline('Color', 'r'); for k = 1:20, addpoints(an, k, sin(k)); drawnow; end")
    await until(page, 'PL.app.figures.wins.size === 1')
    await asyncio.sleep(0.5)
    kids = await page.ev("[...PL.app.figures.wins.values()].map(w => w.fig.axes.reduce((n, ax) => n + ax.children.length, 0))")
    check('the animated line is drawn as a line', kids, [1])
    await command(page, 'close all')

    path = '/home/user/stopper.m'
    await command(page, 'dbstop in stopper at 3')
    check('dbstop: the page keeps the breakpoint', await page.ev(f"JSON.stringify(PL.app.breakpoints[{json.dumps(path)}])"), '[3]')
    await page.ev(f"PL.app.openFile({json.dumps(path)}).then(() => 1)")
    await asyncio.sleep(0.4)
    check('and the Editor shows it in the margin', await page.ev("document.querySelectorAll('.ple-gl .bp').length"), 1)
    await type_line(page, 'r = stopper(4)')
    line = await until(page, 'PL.app.debug && PL.app.debug.line')
    check('the run stops there', line, 3)
    await page.ev('new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(1))))')
    await page.ev("PL.app.dbg('continue'); 1")
    await until(page, '!PL.engine.busy && !PL.app.debug', 30)
    check('and goes on to the end', 'r =\n\n     8' in await tail(page, 200), True)
    await command(page, 'dbclear all')
    check('dbclear all: the Editor\'s margin is clear', (await page.ev(f"JSON.stringify(PL.app.breakpoints[{json.dumps(path)}] || [])"), await page.ev("document.querySelectorAll('.ple-gl .bp').length")), ('[]', 0))
    await page.ev("PL.app.closeDoc(PL.app.docs.find(d => d.key === '/home/user/stopper.m')); 1")
    await command(page, 'dbstop if error')
    await type_line(page, 'errfun')
    line = await until(page, 'PL.app.debug && PL.app.debug.line', 20)
    check('dbstop if error: stopped at the error, the error shown', (line, 'boom' in await tail(page, 300)), (3, True))
    await page.ev('new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(1))))')
    await type_line(page, 'x')
    seen = await until(page, f"{OUTPUT}.slice(-60).includes('x =\\n\\n     5')", 10)
    check("in the function's workspace", seen, True)
    await page.ev("PL.app.dbg('quit'); 1")
    await until(page, '!PL.engine.busy && !PL.app.debug', 30)
    await command(page, 'dbclear if error')

    try:
        await page.call('Browser.grantPermissions', {'permissions': ['clipboardReadWrite', 'clipboardSanitizedWrite'], 'origin': BASE})
    except Exception:
        pass
    await page.ev('window.focus(); PL.app.cmd.ta.focus(); 1')
    await command(page, "clipboard('copy', 'hello from pylab')")
    got = await page.ev('navigator.clipboard.readText().catch((e) => "ERR " + e.message)')
    check("clipboard('copy') reaches the browser's clipboard", got, 'hello from pylab')
    await page.ev('navigator.clipboard.writeText("pasted text").then(() => 1)')
    out = await command(page, "t = clipboard('paste')")
    check("clipboard('paste') reads it", "t =\n\n    'pasted text'" in out[-80:], True)

    out = await command(page, "profile on; r = stopper(3); profile off\nprofile viewer")
    check('profile viewer lists the function', 'Profile summary' in out[-1500:] and 'stopper' in out[-1500:], True)
    await command(page, "diary('d.txt')")
    await command(page, "disp('hello diary')")
    await command(page, 'diary off')
    out = await command(page, 'type d.txt')
    typed = out[out.rfind('>> type d.txt'):]
    check('the diary file has the commands and their output', "disp('hello diary')\nhello diary\ndiary off" in typed, True)
    await command(page, "delete stopper.m errfun.m p.h5 f.avi d.txt")


async def canvas_shot(page, name):
    """The newest figure window's canvas as a PNG of its own (for looking at a chart)."""
    if not SHOTS:
        return
    import base64
    data = await page.ev(f"{WIN}.canvas.toDataURL('image/png')")
    if data and data.startswith('data:image/png;base64,'):
        os.makedirs(SHOTS, exist_ok=True)
        with open(os.path.join(SHOTS, name), 'wb') as f:
            f.write(base64.b64decode(data.split(',', 1)[1]))


async def charts_and_more(page):
    """The charts drawn (saved as pictures to look at), xline across the axes after a zoom, sound through an audioplayer, the
    microphone through an audiorecorder (Chrome's fake device), patterns and memoize in the page."""
    await command(page, "close all; plot(0:10, 0:10); xlim([0 10]); xline(5, 'r', 'LineWidth', 3); xlim([4 6]); ylim([0 10]);")
    await until(page, 'PL.app.figures.wins.size === 1')
    await asyncio.sleep(0.6)
    col = await page.ev(f"(() => {{ const w = {WIN}; const f = w.renderer.frames[0].fr; const c = w.canvas; const k = c.width / c.getBoundingClientRect().width; "
                        "const x = Math.round(f.fx(5) * k); const y0 = Math.round((f.r.y + 2) * k), y1 = Math.round((f.r.y + f.r.h - 2) * k); "
                        "const d = c.getContext('2d').getImageData(x - 1, y0, 3, y1 - y0).data; let n = 0, rows = y1 - y0; "
                        "for (let r = 0; r < rows; r++) { let red = false; for (let j = 0; j < 3; j++) { const i = (r * 3 + j) * 4; if (d[i] > 180 && d[i + 1] < 90 && d[i + 2] < 90) red = true; } if (red) n++; } "
                        "return n / rows; })()")
    check('xline: drawn from the bottom of the axes to the top after the limits changed', (col or 0) > 0.95, True)
    await command(page, "close all; rng(1); f = figure('Position', [50 50 900 560]); "
                        "subplot(2, 3, 1); heatmap(magic(4)); subplot(2, 3, 2); boxchart(randn(40, 3) + [0 1 2]); "
                        "subplot(2, 3, 3); swarmchart([ones(1,40) 2*ones(1,40)], [randn(1,40) 2+randn(1,40)], 'filled'); "
                        "subplot(2, 3, 4); piechart([3 2 1], {'one', 'two', 'three'}); subplot(2, 3, 5); donutchart([5 3 2], 'CenterLabel', 'Ten'); "
                        "subplot(2, 3, 6); binscatter(randn(2000, 1), randn(2000, 1), 20);")
    await asyncio.sleep(1.0)
    ink = await page.ev(INK)
    check('heatmap, boxchart, swarmchart, piechart, donutchart and binscatter draw', (ink or 0) > 0.08, True)
    await canvas_shot(page, 'charts-1.png')
    await command(page, "figure('Position', [60 60 900 560]); subplot(2, 2, 1); polarhistogram(rand(200, 1)*2*pi, 12); "
                        "subplot(2, 2, 2); parallelplot(rand(15, 4), 'GroupData', [ones(8,1); 2*ones(7,1)]); "
                        "subplot(2, 2, 3); wordcloud({'alpha','beta','gamma','delta','epsilon','zeta','eta'}, [9 7 5 4 3 2 1]); "
                        "subplot(2, 2, 4); plot(1:10, (1:10).^2); xline(4, '--', 'four'); yline(60, ':', 'sixty'); xregion(6, 8); yregion(10, 25);")
    await asyncio.sleep(1.0)
    check('polarhistogram, parallelplot, wordcloud and constant lines and regions draw', (await page.ev(INK) or 0) > 0.05, True)
    await canvas_shot(page, 'charts-2.png')
    await command(page, "figure('Position', [70 70 900 560]); subplot(2, 2, 1); fimplicit3(@(x,y,z) x.^2 + y.^2/2 + z.^2 - 4, [-3 3]); "
                        "subplot(2, 2, 2); [x, y, z] = meshgrid(-2:0.25:2); V = x.^2 + y.^2 + z.^2; p = patch(isosurface(x, y, z, V, 5), 'FaceColor', 'r', 'EdgeColor', 'none'); "
                        "isonormals(x, y, z, V, p); patch(isocaps(x, y, z, V, 5, 'enclose', 'below'), 'FaceColor', 'interp', 'EdgeColor', 'none'); view(3); "
                        "subplot(2, 2, 3); tetramesh([1 2 3 4; 2 3 4 5], [0 0 0; 1 0 0; 0 1 0; 0 0 1; 1 1 1]); view(3); "
                        "subplot(2, 2, 4); [X, Y] = meshgrid(-2:0.1:2); streamslice(X, Y, -Y, X);")
    await asyncio.sleep(1.2)
    check('fimplicit3, isosurface with isocaps, tetramesh and streamslice draw', (await page.ev(INK) or 0) > 0.05, True)
    await canvas_shot(page, 'charts-3.png')
    await command(page, "figure('Position', [80 80 700 500]); TT = timetable(datetime(2024,1,1) + days(0:29)', cumsum(randn(30,1)), rand(30,1), 'VariableNames', {'Walk', 'Noise'}); stackedplot(TT);")
    await asyncio.sleep(0.8)
    check('stackedplot draws an axes for each variable', await page.ev(f'{WIN}.fig.axes.length'), 2)
    await canvas_shot(page, 'charts-4.png')
    await command(page, 'close all')

    await command(page, "p = audioplayer(sin(2*pi*440*(0:1/8000:0.5))', 8000); play(p)")
    snd = await page.ev('PL.app.lastSound || null')
    check('audioplayer: play sends its samples to the page, marked as its own', bool(snd) and snd['rate'] == 8000 and bool(snd.get('id')), True)
    out = await command(page, "a = isplaying(p), stop(p); b = isplaying(p)")
    check('isplaying while it plays; stop ends it', 'a =\n\n  logical\n\n   1' in out and 'b =\n\n  logical\n\n   0' in out, True)
    check('and the page stopped the sound', await page.ev('!PL.app.sounds || Object.keys(PL.app.sounds).length === 0'), True)
    try:
        await page.call('Browser.grantPermissions', {'permissions': ['audioCapture'], 'origin': BASE})
    except Exception:
        pass
    out = await command(page, "r = audiorecorder(8000, 16, 1); recordblocking(r, 1); y = getaudiodata(r); n = numel(y), m = max(abs(y)) > 0, fs = r.SampleRate")
    check("audiorecorder: a second of the microphone (Chrome's fake one) at 8000 Hz", 'm =\n\n  logical\n\n   1' in out and ('n =\n\n        8000' in out or 'n =\n\n        8192' in out or 'n =' in out and 'fs =\n\n        8000' in out), True)
    out = await command(page, 'p = digitsPattern(3) + "-" + digitsPattern(4); e = extract("ring 555-1234 now", p), mf = memoize(@(x) x^2); v = mf(3)')
    check('patterns and memoize in the page', '"555-1234"' in out and 'v =\n\n     9' in out, True)


async def graphs_and_networks(page):
    """Graphs drawn with plot (saved as a picture to look at): a force layout, a layered digraph with a shortest path
    highlighted, nodes coloured by NodeCData with a colorbar, edge labels; a highlighted edge red on the canvas."""
    await command(page, "close all; f = figure('Position', [50 50 900 620]); "
                        "subplot(2, 2, 1); G = graph([1 1 2 3 3 4 5 6 7 8 9 9], [2 3 4 4 5 6 7 8 8 9 10 1]); plot(G); title('force'); "
                        "subplot(2, 2, 2); D = digraph([1 1 2 2 3 4 5], [2 3 4 5 5 6 6], [1 4 2 7 1 3 1]); h = plot(D, 'EdgeLabel', D.Edges.Weight); "
                        "[p, d] = shortestpath(D, 1, 6); highlight(h, p, 'EdgeColor', 'r', 'NodeColor', 'r'); title(sprintf('path %g', d)); "
                        "subplot(2, 2, 3); W = graph([1 2 3 4 5 6 1 2], [2 3 4 5 6 1 4 5]); hc = plot(W, 'Layout', 'circle', 'MarkerSize', 8); hc.NodeCData = centrality(W, 'closeness'); colorbar; title('closeness'); "
                        "subplot(2, 2, 4); T = minspantree(W); hs = plot(W, 'Layout', 'subspace'); highlight(hs, T, 'EdgeColor', [0 0.6 0], 'LineWidth', 3); title('spanning tree');")
    await until(page, 'PL.app.figures.wins.size === 1')
    await asyncio.sleep(1.0)
    check('graph plots draw in four axes', (await page.ev(INK) or 0) > 0.03, True)
    await canvas_shot(page, 'graphs-1.png')
    await command(page, "close all; G = graph(1, 2); h = plot(G, 'Layout', 'circle', 'NodeLabel', {}); highlight(h, 1, 2, 'EdgeColor', 'r', 'LineWidth', 6);")
    await until(page, 'PL.app.figures.wins.size === 1')
    await asyncio.sleep(0.6)
    red = await page.ev(f"(() => {{ const w = {WIN}; const f = w.renderer.frames[0].fr; const c = w.canvas; const k = c.width / c.getBoundingClientRect().width; "
                        "const x = Math.round(f.fx(0) * k), y = Math.round(f.fy(0) * k); const d = c.getContext('2d').getImageData(x - 2, y - 2, 5, 5).data; "
                        "let n = 0; for (let i = 0; i < d.length; i += 4) if (d[i] > 200 && d[i + 1] < 150 && d[i + 2] < 150) n++; return n; })()")
    check('a highlighted edge is drawn red between its nodes (its alpha a lighter red)', (red or 0) >= 10, True)
    await command(page, 'close all')


async def tests_and_python(page):
    """runtests on a test class and a script test written in the page's files; Python called from the page (Pyodide's NumPy,
    its printing, pyenv)."""
    await command(page, "close all; cd /home/user; fid = fopen('WebTest.m', 'w'); "
                        "fprintf(fid, 'classdef WebTest < matlab.unittest.TestCase\\n methods (Test)\\n function testOk(tc)\\n tc.verifyEqual(1 + 1, 2);\\n end\\n "
                        "function testBad(tc)\\n tc.verifyEqual(sqrt(4), 3);\\n end\\n end\\nend\\n'); fclose(fid); "
                        "fid = fopen('webScriptTest.m', 'w'); fprintf(fid, 'x = 3;\\n%%%% Three\\nassert(x == 3)\\n'); fclose(fid);")
    out = await command(page, "r = runtests({'WebTest', 'webScriptTest'})")
    check('runtests in the page: a class and a script, the failure shown and counted',
          all(t in out for t in ('Running WebTest', 'Verification failed in WebTest/testBad.', 'Running webScriptTest', '2 Passed, 1 Failed, 0 Incomplete.')), True)
    out = await command(page, "v = double(py.numpy.linalg.eigvalsh([2 1; 1 2])), pyrun(\"print('hello from Pyodide')\"), e = pyenv; n = e.ProcessName")
    check("py.numpy in the page, Python's printing in the Command Window, pyenv naming the browser's Python",
          all(t in out for t in ('1     3', 'hello from Pyodide', 'Pyodide (the browser)')), True)
    await command(page, "delete WebTest.m webScriptTest.m")


async def boundary_delay_pde(page):
    """bvp4c, dde23 and pdepe in the page, drawn (saved as a picture to look at); the ode object."""
    await command(page, "close all; f = figure('Position', [50 50 900 600]); "
                        "subplot(2, 2, 1); s = bvp4c(@(x, y) [y(2); -abs(y(1))], @(ya, yb) [ya(1); yb(1) + 2], bvpinit(linspace(0, 4, 5), [1 0])); "
                        "s5 = bvp5c(@(x, y) [y(2); -abs(y(1))], @(ya, yb) [ya(1); yb(1) + 2], bvpinit(linspace(0, 4, 5), [-1 0])); "
                        "xs = linspace(0, 4); plot(xs, deval(s, xs, 1), xs, deval(s5, xs, 1), '--'); title('bvp4c, bvp5c'); "
                        "subplot(2, 2, 2); d = dde23(@(t, y, Z) -Z, 1, 1, [0 6]); plot(d.x, d.y, '.-'); title('dde23'); "
                        "subplot(2, 2, [3 4]); x = linspace(0, 1, 30); t = linspace(0, 0.3, 20); "
                        "u = pdepe(0, @(x, t, u, dudx) deal(1, dudx, 0), @(x) sin(pi*x) + 0.5*sin(3*pi*x), @(xl, ul, xr, ur, t) deal(ul, 0, ur, 0), x, t); "
                        "surf(x, t, u); title('pdepe'); xlabel('x'); ylabel('t');")
    await until(page, 'PL.app.figures.wins.size === 1')
    await asyncio.sleep(1.0)
    check('bvp4c and bvp5c, dde23 and pdepe draw', (await page.ev(INK) or 0) > 0.015, True)
    await canvas_shot(page, 'odemore-1.png')
    out = await command(page, "close all; F = ode(ODEFcn=@(t, y) -2*y, InitialValue=1); S = solve(F, 1); e = abs(S.Solution(end) - exp(-2)) < 1e-4")
    check('the ode object solves in the page', 'e =\n\n  logical\n\n   1' in out, True)


async def statistics_learning(page):
    """Clustering, a dendrogram, PCA, a fitted classifier's confusion chart and an ROC curve in the page (saved as a picture to look at)."""
    await command(page, "close all; rng(3); X = [randn(30,2); randn(30,2) + [4 0]; randn(30,2) + [2 4]]; y = [ones(30,1); 2*ones(30,1); 3*ones(30,1)]; "
                        "f = figure('Position', [50 50 900 640]); subplot(2, 2, 1); idx = kmeans(X, 3); gscatter(X(:,1), X(:,2), idx); title('kmeans'); "
                        "subplot(2, 2, 2); dendrogram(linkage(X, 'ward'), 20, 'ColorThreshold', 'default'); title('dendrogram'); "
                        "subplot(2, 2, 3); m = fitcecoc(X, y); confusionchart(y, predict(m, X)); "
                        "subplot(2, 2, 4); s = fitcsvm(X(1:60, :), y(1:60), 'KernelFunction', 'gaussian'); [~, sc] = predict(s, X(1:60, :)); "
                        "[fx, fy, ~, auc] = perfcurve(y(1:60), sc(:, 2), 2); plot(fx, fy); title(sprintf('ROC, AUC %.3f', auc));")
    await until(page, 'PL.app.figures.wins.size === 1')
    await drawn(page, 1)
    await asyncio.sleep(1.0)
    check('kmeans, a dendrogram, a confusion chart and an ROC curve draw', await ink(page) > 0.02, True)
    await canvas_shot(page, 'ml-1.png')
    out = await command(page, "close all; g = fitrgp(X(:, 1), X(:, 2)); [p, sd] = predict(g, 0); ok = isfinite(p) && sd > 0, t = fitctree(X, y); l = resubLoss(t) < 0.2")
    check('fitrgp and fitctree in the page', 'ok =\n\n  logical\n\n   1' in out and 'l =\n\n  logical\n\n   1' in out, True)


async def control_systems(page):
    """Step, impulse, root locus and pole-zero responses, a Bode diagram and the margins of a loop in the page (saved as pictures to look at)."""
    await command(page, "close all; clear; G = tf(4, [1 3 3 1]); f = figure('Position', [50 50 900 640]); subplot(2, 2, 1); step(feedback(G, 1)); "
                        "subplot(2, 2, 2); impulse(G); subplot(2, 2, 3); rlocus(G); subplot(2, 2, 4); pzmap(feedback(G, 1));")
    await until(page, 'PL.app.figures.wins.size === 1')
    await drawn(page, 1)
    await asyncio.sleep(1.0)
    check('step, impulse, rlocus and pzmap draw', await ink(page) > 0.015, True)
    await canvas_shot(page, 'control-1.png')
    out = await command(page, "close all; bode(G); [Gm, Pm] = margin(G); ok = abs(20*log10(Gm) - 6.0206) < 1e-3 && abs(Pm - 27.1) < 0.1, s = stepinfo(feedback(G, 1)); o = s.Overshoot > 0")
    await until(page, 'PL.app.figures.wins.size === 1')
    await drawn(page, 1)
    await asyncio.sleep(0.8)
    check('a Bode diagram draws', await ink(page) > 0.01, True)
    await canvas_shot(page, 'control-2.png')
    check('margin and stepinfo in the page', 'ok =\n\n  logical\n\n   1' in out and 'o =\n\n  logical\n\n   1' in out, True)
    await command(page, 'close all')          # the Editor's checks look at the page under where figures stand


async def global_optimization(page):
    """ga, particleswarm and patternsearch on known minima, and a Pareto front from gamultiobj drawn, in the page."""
    out = await command(page, "close all; rng(1); r = @(x) 10*numel(x) + sum(x.^2 - 10*cos(2*pi*x)); "
                              "x1 = ga(r, 2, [], [], [], [], [-5 -5], [5 5], [], optimoptions('ga', 'Display', 'off', 'MaxGenerations', 120)); "
                              "x2 = particleswarm(r, 2, [-5 -5], [5 5], optimoptions('particleswarm', 'Display', 'off')); "
                              "x3 = patternsearch(@(x) (x(1) - 1)^2 + (x(2) + 2)^2, [0 0], [], [], [], [], [], [], [], optimoptions('patternsearch', 'Display', 'off')); "
                              "ok = norm(x1) < 0.1 && norm(x2) < 1e-3 && norm(x3 - [1 -2]) < 1e-5, "
                              "[xp, fp] = gamultiobj(@(x) [x(1)^2, (x(1) - 2)^2], 1, [], [], [], [], -5, 5, optimoptions('gamultiobj', 'Display', 'off')); "
                              "plot(fp(:, 1), fp(:, 2), 'o'); title('Pareto front'); n = size(fp, 1) > 10")
    await until(page, 'PL.app.figures.wins.size === 1')
    await drawn(page, 1)
    await asyncio.sleep(0.8)
    check('ga, particleswarm and patternsearch find their minima in the page', 'ok =\n\n  logical\n\n   1' in out, True)
    check('a gamultiobj front draws', 'n =\n\n  logical\n\n   1' in out and await ink(page) > 0.002, True)
    await canvas_shot(page, 'globalopt-1.png')
    await command(page, 'close all')          # the Editor's checks look at the page under where figures stand


async def wavelets_and_denoising(page):
    """A decomposition and its reconstruction, a wavelet, a scalogram and a denoised signal in the page (saved as a picture to look at)."""
    out = await command(page, "close all; fs = 1000; t = (0:1999)/fs; x = sin(2*pi*30*t) + 0.5*sin(2*pi*120*t).*(t > 1); "
                              "f = figure('Position', [50 50 900 640]); subplot(2, 2, 1); [c, l] = wavedec(x, 4, 'db4'); plot(t, wrcoef('a', c, l, 'db4', 4)); title('approximation, level 4'); "
                              "subplot(2, 2, 2); [phi, psi, xv] = wavefun('sym8'); plot(xv, psi); title('sym8'); "
                              "subplot(2, 2, 3); cwt(x, fs); subplot(2, 2, 4); rng(2); wdenoise(x(1:512) + 0.3*randn(1, 512)); "
                              "ok = max(abs(waverec(c, l, 'db4') - x)) < 1e-10, tic; h = wfilters('db45'); slow = toc > 10")
    await until(page, 'PL.app.figures.wins.size === 1')
    await drawn(page, 1)
    await asyncio.sleep(1.0)
    check('wavedec and waverec in the page; db45 computed in time', 'ok =\n\n  logical\n\n   1' in out and 'slow =\n\n  logical\n\n   0' in out, True)
    check('a reconstruction, a wavelet, a scalogram and a denoised signal draw', await ink(page) > 0.03, True)
    await canvas_shot(page, 'wavelets-1.png')
    await command(page, 'close all')          # the Editor's checks look at the page under where figures stand


async def quiver_arrows(page):
    """quiver3's arrows drawn in 3-D, red ones counted (saved as a picture to look at)."""
    await command(page, "close all; figure('Position', [50 50 600 480]); [X, Y] = meshgrid(1:4); "
                        "quiver3(X, Y, zeros(4), 0.3*ones(4), zeros(4), ones(4), 'r', 'LineWidth', 2); hold on; quiver3(1, 1, 3, 1, 1, 0, 0, 'b')")
    await until(page, 'PL.app.figures.wins.size === 1')
    await drawn(page, 1)
    await asyncio.sleep(0.8)
    red = await page.ev(f"(() => {{ const c = {WIN}.canvas; const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; "
                        "for (let i = 0; i < d.length; i += 4) if (d[i] > 180 && d[i + 1] < 90 && d[i + 2] < 90) n++; return n; })()")
    check("quiver3 draws its arrows in 3-D (red pixels)", (red or 0) > 300, True)
    await canvas_shot(page, 'quiver3-1.png')
    await command(page, 'close all')


async def core_additions(page):
    """Step 11 in the page: polyshape on Shapely (loaded on first use) drawn with its hole open, a rounded rectangle, polar axes'
    ticks and zero direction, a transform group, NetCDF through h5py and SciPy, ?double (saved as a picture to look at)."""
    out = await command(page, "close all; sq = polyshape([0 4 4 0], [0 0 4 4]); pg = subtract(sq, polyshape([1 3 3 1], [1 1 3 3])); "
                              "pa = area(pg), nh = pg.NumHoles, mc = ?double; mn = mc.Name")
    check('polyshape in the page: Shapely loaded, a square less a hole', 'pa =\n\n    12' in out and 'nh =\n\n     1' in out and "mn =\n\n    'double'" in out, True)
    await command(page, "figure('Position', [50 50 520 480]); plot(pg, 'FaceColor', 'r', 'FaceAlpha', 1); axis equal; xlim([0 4]); ylim([0 4]);")
    await until(page, 'PL.app.figures.wins.size === 1')
    await drawn(page, 1)
    await asyncio.sleep(0.6)
    px = await page.ev(f"(() => {{ const w = {WIN}; const f = w.renderer.frames[0].fr; const c = w.canvas; const k = c.width / c.getBoundingClientRect().width; "
                       "const at = (x, y) => {{ const d = c.getContext('2d').getImageData(Math.round(f.fx(x) * k), Math.round(f.fy(y) * k), 1, 1).data; return [d[0], d[1], d[2]]; }}; "
                       "return [at(0.5, 0.5), at(2, 2)]; })()")
    red = lambda p: p and p[0] > 180 and p[1] < 90 and p[2] < 90
    check("a polyshape's plot: its face filled, its hole left open (even-odd)", bool(px) and bool(red(px[0])) and not red(px[1]), True)
    await canvas_shot(page, 'core11-1.png')
    await command(page, "close all; figure('Position', [60 60 900 450]); subplot(1, 3, 1); rectangle('Position', [0 0 2 1], 'Curvature', [1 1], 'FaceColor', [0 0.6 0]); axis equal; "
                        "subplot(1, 3, 2); polarplot(linspace(0, 2*pi, 100), 1 + cos(linspace(0, 2*pi, 100))); rticks([0 1 2]); thetaticks(0:45:315); "
                        "pax = gca; pax.ThetaZeroLocation = 'top'; pax.ThetaDir = 'clockwise'; subplot(1, 3, 3); t = hgtransform; "
                        "line([0 1], [0 0], 'Parent', t, 'LineWidth', 3, 'Color', 'b'); t.Matrix = makehgtform('zrotate', pi/4); axis([-1 1 -1 1]); ytickformat('%.1f');")
    await asyncio.sleep(1.0)
    check('a rounded rectangle, polar axes with their ticks turned, a transformed line draw', (await ink(page)) > 0.03, True)
    await canvas_shot(page, 'core11-2.png')
    out = await command(page, "close all; nccreate('t4.nc', 'v', 'Dimensions', {'x', 3, 't', Inf}); ncwrite('t4.nc', 'v', magic(3)); r4 = isequal(ncread('t4.nc', 'v'), magic(3)), "
                              "nccreate('t3.nc', 'v', 'Dimensions', {'x', 2}, 'Format', 'classic'); ncwrite('t3.nc', 'v', [7 8]); r3 = ncread('t3.nc', 'v')', "
                              "fi = ncinfo('t4.nc'); fmt = fi.Format")
    check('NetCDF in the page: netCDF-4 through h5py and classic through SciPy', 'r4 =\n\n  logical\n\n   1' in out and 'r3 =\n\n     7     8' in out
          and "fmt =\n\n    'netcdf4_classic'" in out, True)
    await command(page, "delete('t4.nc'); delete('t3.nc')")
    out = await command(page, "clc; [tzd, tzs] = tzoffset(datetime(2026, [1 7], 1, 12, 0, 0, 'TimeZone', 'Europe/Stockholm')); "
                              "tzh = [hours(tzd) hours(tzs)], de = char(dateshift(datetime(2026, 2, 14), 'end', 'month'))")
    check("time zones in the page (the browser's): Stockholm's offsets and summer time; the end of a month is its last day",
          'tzh =\n\n     1     2     0     1' in out and "de =\n\n    '28-Feb-2026'" in out, True)


async def image_additions(page):
    """Step 12 in the page: the Radon transform and back, watershed, imwarp, label2rgb and imshowpair drawn (saved as a picture to look at)."""
    out = await command(page, "close all; I = phantom(96); Rd = radon(I, 0:2:178); J = iradon(Rd, 0:2:178); rc = corr2(J(2:97, 2:97), I) > 0.8, "
                              "L = watershed(imgaussfilt(peaks(60), 2)); ws = max(L(:)) > 1 && any(L(:) == 0), t = rigidtform2d(15, [3 2]); "
                              "B = imwarp(I, t, 'OutputView', imref2d(size(I))); wp = isequal(size(B), size(I)), "
                              "f = figure('Position', [50 50 800 400]); subplot(1, 2, 1); imshow(label2rgb(L)); subplot(1, 2, 2); imshowpair(I, B);")
    check('radon and iradon, watershed and imwarp in the page', 'rc =\n\n  logical\n\n   1' in out and 'ws =\n\n  logical\n\n   1' in out
          and 'wp =\n\n  logical\n\n   1' in out, True)
    await until(page, 'PL.app.figures.wins.size === 1')
    await drawn(page, 2)
    await asyncio.sleep(0.8)
    check('label2rgb and imshowpair draw', (await ink(page)) > 0.2, True)
    await canvas_shot(page, 'image12-1.png')
    await command(page, 'close all')


async def problem_based(page):
    """Step 13 in the page: a mixed-integer problem and a quadratic one solved through solve, show, an equation problem, and paretosearch's front drawn."""
    out = await command(page, "close all; x = optimvar('x', 2, 'LowerBound', 0); y = optimvar('y', 'Type', 'integer', 'LowerBound', 0, 'UpperBound', 10); "
                              "p = optimproblem('ObjectiveSense', 'maximize', 'Objective', x(1) + 2*x(2) + 3*y + 7); "
                              "p.Constraints.c1 = x(1) + x(2) + y <= 4.5; p.Constraints.c2 = x(1) - x(2) >= -1; show(p)\n"
                              "[sol, f, flag, o] = solve(p); mi = isequal(sol.y, 4) && abs(f - 20) < 1e-9 && strcmp(o.solver, 'intlinprog'), "
                              "w = optimvar('w', 3, 'LowerBound', 0); q = optimproblem('Objective', w'*[2 1 0; 1 3 1; 0 1 4]*w - [1 2 3]*w); "
                              "q.Constraints.b = sum(w) == 1; [sw, fq] = solve(q, 'Options', optimoptions('quadprog', 'Display', 'off')); "
                              "[ww, fq2] = quadprog(2*[2 1 0; 1 3 1; 0 1 4], -[1; 2; 3], [], [], [1 1 1], 1, zeros(3, 1), [], [], optimoptions('quadprog', 'Display', 'off')); "
                              "qp = abs(fq - fq2) < 1e-10, u = optimvar('u', 2); eq = eqnproblem('Equations', [u(1)^2 + u(2)^2 == 1; u(1) == u(2)]); "
                              "su = solve(eq, struct('u', [1; 0.5])); en = norm(su.u - [1; 1]/sqrt(2)) < 1e-6, "
                              "fun = @(x) [x(1)^2 + x(2)^2, (x(1) - 2)^2 + x(2)^2]; "
                              "[X, F] = paretosearch(fun, 2, [], [], [], [], [-5 -5], [5 5], [], optimoptions('paretosearch', 'Display', 'off', 'ParetoSetSize', 30)); "
                              "pf = max(abs(sqrt(F(:, 1)) + sqrt(F(:, 2)) - 2)) < 1e-6, f = figure('Position', [50 50 520 400]); plot(F(:, 1), F(:, 2), 'o'); xlabel('f_1'); ylabel('f_2');")
    check('show writes the problem out', all(t in out for t in ('Solving problem using intlinprog.', 'where: y integer', 'x(1) + x(2) + y <= 4.5', 'x(1) - x(2) >= -1')), True)
    check('solve in the page: intlinprog, quadprog and an equation problem; paretosearch on the front',
          all(f'{k} =\n\n  logical\n\n   1' in out for k in ('mi', 'qp', 'en', 'pf')), True)
    await until(page, 'PL.app.figures.wins.size === 1')
    await drawn(page, 1)
    await asyncio.sleep(0.6)
    check("paretosearch's front drawn", (await ink(page)) > 0.02, True)
    await canvas_shot(page, 'optimprob13-1.png')
    await command(page, 'close all')


async def toolbox_fillins(page):
    """Step 14 in the page: a mixed-effects model shown, mnrfit, charpoly of numbers (SymPy loaded for it), stft and istft, csaps, and bodemag of an frd model and a rocmetrics plot drawn."""
    out = await command(page, "close all; rng(1); g = repelem((1:6)', 10); x = randn(60, 1); u = 0.8*randn(6, 1); y = 1 + u(g) + 2*x + 0.3*randn(60, 1); "
                              "tbl = table(x, y, categorical(g), 'VariableNames', {'x', 'y', 'g'}); lme = fitlme(tbl, 'y ~ x + (1 | g)')\n"
                              "b = fixedEffects(lme); fe = abs(b(2) - 2) < 0.2, [B, dev] = mnrfit([1; 2; 3; 4; 5; 6], [1; 1; 2; 1; 2; 2]); mn = isfinite(dev), "
                              "cp = isequal(charpoly([1 2; 3 4]), [1 -5 -2]), xs = randn(400, 1); [s, f] = stft(xs, 'Window', hann(64, 'periodic'), 'OverlapLength', 48); "
                              "xr = istft(s, 'Window', hann(64, 'periodic'), 'OverlapLength', 48); st = max(abs(real(xr(2:end)) - xs(2:numel(xr)))) < 1e-10, "
                              "cs = max(abs(csaps(0:5, [0 1 0 1 0 1], 1, 0:5) - [0 1 0 1 0 1])) < 1e-12, "
                              "f1 = figure('Position', [50 50 900 380]); subplot(1, 2, 1); bodemag(frd(tf(1, [1 0.4 1]), logspace(-1, 1, 60))); subplot(1, 2, 2); "
                              "lab = [ones(30, 1); zeros(30, 1)]; sc = [rand(30, 1) + 0.4; rand(30, 1)]; plot(rocmetrics(lab, [1 - sc, sc], [0 1]));")
    check('fitlme shown in the page', 'Linear mixed-effects model fit by ML' in out and 'Random effects covariance parameters' in out, True)
    check('fitlme, mnrfit, charpoly (SymPy loaded for numbers), stft and istft, csaps in the page',
          all(f'{k} =\n\n  logical\n\n   1' in out for k in ('fe', 'mn', 'cp', 'st', 'cs')), True)
    await until(page, 'PL.app.figures.wins.size === 1')
    await drawn(page, 2)
    await asyncio.sleep(0.8)
    check("bodemag of an frd model and rocmetrics' curves drawn", (await ink(page)) > 0.02, True)
    await canvas_shot(page, 'toolfill14-1.png')
    await command(page, 'close all')


async def pde_toolbox(page):
    """Step 15 in the page: a square less a circle meshed, Poisson's equation solved and drawn with contours, the unit square's eigenvalues, a heat decay."""
    out = await command(page, "close all; model = createpde; gd = [3 4 -1 1 1 -1 -1 -1 1 1; 1 0 0 0.5 0 0 0 0 0 0]'; "
                              "geometryFromEdges(model, decsg(gd, 'R1-C1', char('R1', 'C1')')); generateMesh(model, 'Hmax', 0.1); ar = abs(area(model.Mesh) - (4 - pi/4)) < 1e-5, "
                              "applyBoundaryCondition(model, 'dirichlet', 'Edge', 1:4, 'u', 0); applyBoundaryCondition(model, 'dirichlet', 'Edge', 5:8, 'u', 1); "
                              "specifyCoefficients(model, 'm', 0, 'd', 0, 'c', 1, 'a', 0, 'f', 0); R = solvepde(model); "
                              "mm = max(R.NodalSolution) <= 1 + 1e-9 && min(R.NodalSolution) >= -1e-9, "
                              "f1 = figure('Position', [50 50 900 380]); subplot(1, 2, 1); pdegplot(model, 'EdgeLabels', 'on'); subplot(1, 2, 2); "
                              "pdeplot(model, 'XYData', R.NodalSolution, 'Contour', 'on'); "
                              "sq = createpde; geometryFromEdges(sq, decsg([3; 4; 0; 1; 1; 0; 0; 0; 1; 1])); applyBoundaryCondition(sq, 'dirichlet', 'Edge', 1:4, 'u', 0); "
                              "specifyCoefficients(sq, 'm', 0, 'd', 1, 'c', 1, 'a', 0, 'f', 0); generateMesh(sq, 'Hmax', 0.1); E = solvepdeeig(sq, [0 60]); "
                              "ev = max(abs(E.Eigenvalues'/pi^2 - [2 5 5])) < 2e-3, setInitialConditions(sq, @(l) sin(pi*l.x).*sin(pi*l.y)); "
                              "T = solvepde(sq, [0 0.05]); u = T.NodalSolution; p = sq.Mesh.Nodes; "
                              "ht = max(abs(u(:, 2) - exp(-2*pi^2*0.05)*(sin(pi*p(1,:)).*sin(pi*p(2,:)))')) < 5e-3,")
    check('the PDE toolbox in the page: the mesh\'s area, Laplace between the square and the circle, eigenvalues, heat decay',
          all(f'{k} =\n\n  logical\n\n   1' in out for k in ('ar', 'mm', 'ev', 'ht')), True)
    await until(page, 'PL.app.figures.wins.size === 1')
    await drawn(page, 2)
    await asyncio.sleep(0.8)
    check('the geometry with its edge labels and the solution with contours drawn', (await ink(page)) > 0.05, True)
    await canvas_shot(page, 'pde15-1.png')
    await command(page, 'close all')


async def core_fillins(page):
    """Step 16 in the page: the desktop functions showing panels, Parquet through the page's pyarrow, FITS,
    datastores with tall arrays and mapreduce, a surface fit drawn, the ez plots."""
    await page.ev('PL.app.setPanels(false, false); 1')
    await command(page, 'workspace')
    # (each the tab its group shows, Layout's hiding undone)
    shown = await page.ev("PL.app.toolShown('ws') && !PL.app.pWs.hidden")
    await command(page, 'commandhistory')
    hist = await page.ev("PL.app.toolShown('hist') && !PL.app.pHist.hidden")
    await command(page, 'filebrowser')
    files = await page.ev("PL.app.toolShown('folder') && !PL.app.pFolder.hidden")
    check('workspace, commandhistory and filebrowser open their hidden sides and show their panels', [shown, hist, files], [True, True, True])
    await command(page, 'cfv = magic(3); openvar(\'cfv\')')
    opened = await until(page, "PL.app.docs.some(d => d.key === 'var:cfv') && PL.app.current && PL.app.current.key === 'var:cfv'", 10)
    await command(page, 'commandwindow')
    focused = await page.ev('document.activeElement === PL.app.cmd.ta')
    check('openvar opens the Variables view; commandwindow gives the Command Window the keyboard', [bool(opened), focused], [True, True])
    out = await command(page, "clc; r = matlabRelease; disp(r.Release); n = maxNumCompThreads, memory")
    check('matlabRelease, maxNumCompThreads (one thread in the page) and memory (WebAssembly memory)',
          ['PyLAB' in out, 'n =\n\n     1' in out, 'Memory used by PyLAB' in out, 'grows as it needs up to 4 GB' in out], [True] * 4)
    out = await command(page, "clc; cd /home/user; T = table([1.5;2;3], int32([4;5;6]), [\"a\";\"b\";missing], datetime(2024,1,[1;2;3]), categorical({'r';'g';'r'}), "
                              "'VariableNames', {'d','i','s','t','c'}); parquetwrite('cf16.parquet', T); T2 = parquetread('cf16.parquet'); "
                              "pq = isequal(T2.d, T.d) && isequal(T2.i, T.i) && isequal(T2.t, T.t) && ismissing(T2.s(3)) && isequal(categories(T2.c), {'g';'r'}), "
                              "info = parquetinfo('cf16.parquet'); rg = info.NumRowGroups")
    check('Parquet in the page: pyarrow loaded, a table written and read back with its classes', ['pq =\n\n  logical\n\n   1' in out, 'rg =\n\n     1' in out], [True, True])
    out = await command(page, "clc; fitswrite(uint16([1 2 3; 4 5 65535]), 'cf16.fits'); fitswrite(single(reshape(1:24, 2, 3, 4)), 'cf16.fits', 'WriteMode', 'append'); "
                              "a = fitsread('cf16.fits'); b = fitsread('cf16.fits', 'image'); ft = isequal(a, [1 2 3; 4 5 65535]) && isequal(size(b), [2 3 4]), "
                              "inf = fitsinfo('cf16.fits'); nc = numel(inf.Contents)")
    check('FITS in the page: written and read back', ['ft =\n\n  logical\n\n   1' in out, 'nc =\n\n     2' in out], [True, True])
    out = await command(page, "clc; mkdir cf16; writetable(table((1:5)', (6:10)', 'VariableNames', {'x','y'}), 'cf16/a.csv'); "
                              "writetable(table((11:13)', (14:16)', 'VariableNames', {'x','y'}), 'cf16/b.csv'); ds = datastore('cf16'); ds.ReadSize = 2; "
                              "nb = 0; while hasdata(ds), read(ds); nb = nb + 1; end, nb, t = tall(ds); mt = gather(mean(t.x + t.y)), "
                              "outds = mapreduce(ds, @(d, i, s) add(s, 'n', height(d)), @(k, it, s) add(s, k, nb), 'Display', 'off'); kv = readall(outds); kn = kv.Value{1}")
    check('datastores in the page: blocks read, a tall mean gathered, mapreduce run', ['nb =\n\n     5' in out, 'mt =\n\n    17' in out, 'kn =\n\n     5' in out], [True] * 3)
    out = await command(page, "clc; close all; rng(3); x = rand(40, 1)*4 - 2; y = rand(40, 1)*4 - 2; z = x.^2 - y + 0.01*randn(40, 1); "
                              "f1 = figure('Position', [50 50 900 380]); subplot(1, 2, 1); sf = fit([x y], z, 'poly21'); plot(sf, [x y], z); "
                              "subplot(1, 2, 2); ezsurfc('sin(x)*cos(y)', [-pi pi -pi pi], 30); sfv = abs(sf(1, 1)) < 1.2")
    check('a surface fit drawn with its data, and ezsurfc', 'sfv =\n\n  logical\n\n   1' in out, True)
    await until(page, 'PL.app.figures.wins.size === 1')
    await drawn(page, 2)
    await asyncio.sleep(0.8)
    check('the fitted surface and the ez surface with contours drawn', (await ink(page)) > 0.05, True)
    await canvas_shot(page, 'corefill16-1.png')
    await command(page, "close all; delete('cf16.parquet'); delete('cf16.fits'); rmdir('cf16', 's'); clear cfv")
    await page.ev('PL.app.setPanels(true, true); 1')


async def econometrics(page):
    """Step 17 in the page: an ARMA model estimated with its table, a forecast, a GARCH fit, a VAR, the unit-root tests,
    and the correlation plots drawn."""
    out = await command(page, "clc; close all; rng(5); M = arima('Constant', 0.5, 'AR', {0.6 -0.2}, 'MA', {0.3}, 'Variance', 0.4); y = simulate(M, 400); "
                              "E = estimate(arima(2, 0, 1), y); [f, mse] = forecast(E, 3, y); fm = mse(1) > 0.3 && mse(3) > mse(1), "
                              "rng(2); [V, r] = simulate(garch('Constant', 0.1, 'GARCH', {0.8}, 'ARCH', {0.1}), 1500); G = estimate(garch(1, 1), r, 'Display', 'off'); "
                              "gg = abs(G.GARCH{1} - 0.8) < 0.15, Y = simulate(varm('Constant', [0; 0], 'AR', {[0.5 0.1; 0.2 0.3]}, 'Covariance', eye(2)), 300); "
                              "Ev = estimate(varm(2, 1), Y); rr = irf(Ev, 'NumObs', 4); vr = isequal(size(rr), [4 2 2]), "
                              "[h1, p1] = adftest(cumsum(randn(200, 1))); [h2, p2] = adftest(randn(200, 1), 'model', 'ARD'); ur = ~h1 && h2, "
                              "[hk, pk] = kpsstest(randn(200, 1)); [hq, pq] = lbqtest(randn(200, 1)); ok = pk >= 0.01 && pq > 0")
    check('econometrics in the page: an ARMA estimate shown with its table, forecasts, GARCH, a VAR and the tests',
          ['StandardError' in out, 'AR{2}' in out] + [f'{k} =\n\n  logical\n\n   1' in out for k in ('fm', 'gg', 'vr', 'ur', 'ok')], [True] * 7)
    out = await command(page, "clc; f1 = figure('Position', [50 50 900 380]); subplot(1, 2, 1); autocorr(y); subplot(1, 2, 2); parcorr(y); drawnow")
    await until(page, 'PL.app.figures.wins.size === 1')
    await drawn(page, 2)
    await asyncio.sleep(0.8)
    check('autocorr and parcorr drawn with their bounds', (await ink(page)) > 0.01, True)
    await canvas_shot(page, 'econ17-1.png')
    await command(page, 'close all; clear')


async def finance(page):
    """Step 18 in the page: option prices and an implied volatility, cash flows, dates, indicators, and a portfolio's
    efficient frontier drawn."""
    out = await command(page, "clc; close all; [c, p] = blsprice(100, 95, 0.05, 0.5, 0.25); v = blsimpv(100, 95, 0.05, 0.5, c); bv = abs(v - 0.25) < 1e-8, "
                              "r = irr([-1000; 300; 400; 500; 200]); ir = abs(pvvar([-1000; 300; 400; 500; 200], r)) < 1e-8, "
                              "pm = payper(0.06/12, 360, 250000); py = abs(pvfix(0.06/12, 360, pm) - 250000) < 1e-6, "
                              "hd = numel(holidays(datenum(2024,1,1), datenum(2024,12,31))) == 10 && ~isbusday(datenum(2024,7,4)), "
                              "z = 100 + cumsum(randn(60, 1)); [m, u, l] = bollinger(z); bb = all(isnan(m(1:19))) && all(u(20:end) >= l(20:end)), "
                              "mu = [0.06; 0.08; 0.11; 0.15]; sd = [0.1 0.14 0.2 0.28]; Cv = corr2cov(sd, [1 .3 .2 .1; .3 1 .4 .25; .2 .4 1 .35; .1 .25 .35 1]); "
                              "P = setBounds(setDefaultConstraints(Portfolio('AssetMean', mu, 'AssetCovar', Cv, 'RiskFreeRate', 0.02)), 0, 0.5); "
                              "W = estimateFrontier(P, 8); ws = estimateMaxSharpeRatio(P); pf = all(abs(sum(W) - 1) < 1e-8) && abs(sum(ws) - 1) < 1e-8, "
                              "f1 = figure('Position', [50 50 600 400]); plotFrontier(P);")
    check('finance in the page: blsimpv back, irr, payper, holidays, bollinger, a portfolio frontier',
          [f'{k} =\n\n  logical\n\n   1' in out for k in ('bv', 'ir', 'py', 'hd', 'bb', 'pf')], [True] * 6)
    await until(page, 'PL.app.figures.wins.size === 1')
    await drawn(page, 1)
    await asyncio.sleep(0.8)
    check('the efficient frontier drawn', (await ink(page)) > 0.005, True)
    await canvas_shot(page, 'finance18-1.png')
    await command(page, "close all; figure('Position', [50 50 560 420]); S = 60:140; yyaxis left; plot(S, normcdf((S - 100)/15)); ylabel('call delta'); "
                        "yyaxis right; plot(S, normpdf(S, 100, 15)/15); ylabel('gamma'); xlabel('asset price');")
    await until(page, 'PL.app.figures.wins.size === 1')
    await drawn(page, 1)
    await asyncio.sleep(0.6)
    fit = await page.ev(f"(() => {{ const w = {WIN}; const cw = w.canvas.getBoundingClientRect().width; const base = w.renderer.frames.find((f) => !f.yyRight); "
                        "const r = base.rect; const again = w.renderer.rightRoom(w.canvas.getContext('2d'), base.ax, r, cw); "
                        "return [cw - (r.x + r.w) > 0.095 * cw + 2, again.w === r.w]; })()")
    check("yyaxis: a right y-axis whose tick labels and label need more than the default margin narrows the box, and then fits", fit, [True, True])
    await command(page, 'close all; clear')


async def comms_audio(page):
    """Step 19 in the page: QAM through noise and back, error rates against berawgn, a raised-cosine eye, MFCCs and pitch,
    and a constellation and a mel spectrogram drawn."""
    out = await command(page, "clc; close all; rng(3); x = randi([0 15], 20000, 1); y = awgn(qammod(x, 16, 'UnitAveragePower', true), 12 + 10*log10(4), 'measured'); "
                              "[nb, rb] = biterr(x, qamdemod(y, 16, 'UnitAveragePower', true)); bt = berawgn(12, 'qam', 16); qa = abs(rb - bt) < 4*sqrt(bt/80000) + 1e-4, "
                              "h = rcosdesign(0.35, 6, 8); rc = abs(sum(h.^2) - 1) < 1e-12, fs = 16000; t = (0:fs-1)'/fs; s = sin(2*pi*220*t) + 0.5*sin(2*pi*440*t); "
                              "f0 = median(pitch(s, fs)); pt = abs(f0 - 220) < 1, c = mfcc(s, fs); mc = isequal(size(c, 2), 14), "
                              "f1 = figure('Position', [50 50 900 380]); subplot(1, 2, 1); plot(real(y(1:2000)), imag(y(1:2000)), '.'); axis equal; title('16-QAM at 12 dB'); "
                              "subplot(1, 2, 2); [S, F, T] = melSpectrogram(s + 0.05*randn(fs, 1), fs); imagesc(T, F, 10*log10(S)); axis xy; title('Mel spectrogram');")
    check('communications and audio in the page: 16-QAM bit errors against berawgn, rcosdesign, pitch and mfcc',
          [f'{k} =\n\n  logical\n\n   1' in out for k in ('qa', 'rc', 'pt', 'mc')], [True] * 4)
    await until(page, 'PL.app.figures.wins.size === 1')
    await drawn(page, 2)
    await asyncio.sleep(0.8)
    check('a constellation and a mel spectrogram drawn', (await ink(page)) > 0.05, True)
    await canvas_shot(page, 'comms19-1.png')
    await command(page, 'close all; clear')


async def system_identification(page):
    """Step 20 in the page: ARX, ARMAX, N4SID and TFEST fitted to simulated data, a step response of a model, and compare drawn."""
    out = await command(page, "clc; close all; rng(1); N = 800; u = idinput(N, 'prbs'); e = 0.05*randn(N, 1); "
                              "y = filter([0 0.5 0.3], [1 -1.5 0.7], u) + filter([1 0.4], [1 -1.5 0.7], e); d = iddata(y, u, 0.1); "
                              "m1 = arx(d, [2 2 1]); m2 = armax(d, [2 2 1 1]); s = n4sid(d, 2); t = tfest(d, 2, 1); "
                              "ok1 = max(abs(m2.A - [1 -1.5 0.7])) < 0.05 && max(abs(m2.C - [1 0.4])) < 0.15, "
                              "ok2 = max(abs(sort(abs(eig(s.A))) - sqrt(0.7))) < 0.02, [yc, fit] = compare(d, m2); ok3 = fit > 80, "
                              "ys = step(m1, 2); ok4 = numel(ys) > 2 && all(isfinite(ys)), "
                              "f1 = figure('Position', [50 50 800 400]); compare(d(1:300), m1, m2);")
    check('system identification in the page: ARMAX near the truth, n4sid poles, compare\'s fit, a step response',
          [f'{k} =\n\n  logical\n\n   1' in out for k in ('ok1', 'ok2', 'ok3', 'ok4')], [True] * 4)
    await until(page, 'PL.app.figures.wins.size === 1')
    await drawn(page, 1)
    await asyncio.sleep(0.8)
    check('compare drawn: the measured output and two models', (await ink(page)) > 0.01, True)
    await canvas_shot(page, 'sysid20-1.png')
    await command(page, 'close all; clear')


async def fuzzy_logic(page):
    """Step 21 in the page: a Mamdani system built, evaluated and written to a .fis file and read back, a Sugeno system,
    and the output surface and membership functions drawn."""
    out = await command(page, "clc; close all; cd /home/user; fis = mamfis('Name', 'fan'); fis = addInput(fis, [0 40], 'Name', 'temp'); "
                              "fis = addMF(fis, 'temp', 'trapmf', [-1 0 15 20], 'Name', 'cool'); fis = addMF(fis, 'temp', 'trapmf', [15 25 40 41], 'Name', 'hot'); "
                              "fis = addInput(fis, [0 100], 'Name', 'hum'); fis = addMF(fis, 'hum', 'gaussmf', [20 0], 'Name', 'dry'); fis = addMF(fis, 'hum', 'gaussmf', [20 100], 'Name', 'damp'); "
                              "fis = addOutput(fis, [0 100], 'Name', 'speed'); fis = addMF(fis, 'speed', 'trimf', [0 0 50], 'Name', 'slow'); fis = addMF(fis, 'speed', 'trimf', [50 100 100], 'Name', 'fast'); "
                              "fis = addRule(fis, [\"If temp is cool and hum is dry then speed is slow\"; \"If temp is hot or hum is damp then speed is fast\"]); "
                              "v = evalfis(fis, [30 80; 5 10]); ok1 = v(1) > 50 && v(2) < 50, writefis(fis, 'fan21'); f2 = readfis('fan21.fis'); ok2 = isequal(evalfis(f2, [30 80; 5 10]), v), "
                              "s = sugfis; s = addInput(s, [0 1], 'Name', 'x'); s = addMF(s, 'x', 'trimf', [-1 0 1], 'Name', 'lo'); s = addMF(s, 'x', 'trimf', [0 1 2], 'Name', 'hi'); "
                              "s = addOutput(s, [0 3], 'Name', 'y'); s = addMF(s, 'y', 'constant', 0, 'Name', 'z'); s = addMF(s, 'y', 'linear', [2 1], 'Name', 'l'); "
                              "s = addRule(s, [1 1 1 1; 2 2 1 1]); ok3 = abs(evalfis(s, 0.25) - 0.375) < 1e-12, "
                              "f1 = figure('Position', [50 50 900 380]); subplot(1, 2, 1); gensurf(fis); subplot(1, 2, 2); plotmf(fis, 'input', 1); delete('fan21.fis');")
    check('fuzzy logic in the page: a Mamdani system evaluated and read back from a .fis file, a Sugeno system',
          [f'{k} =\n\n  logical\n\n   1' in out for k in ('ok1', 'ok2', 'ok3')], [True] * 3)
    await until(page, 'PL.app.figures.wins.size === 1')
    await drawn(page, 2)
    await asyncio.sleep(0.8)
    check('the output surface and the membership functions drawn', (await ink(page)) > 0.03, True)
    await canvas_shot(page, 'fuzzy21-1.png')
    await command(page, 'close all; clear')


async def main():
    page = await open_page(f'{BASE}/pylab.html')
    try:
        await desktop(page)
        await property_editor(page)
        await editor_draws(page)
        await language_additions(page)
        await signal_processing(page)
        await regression_fitting(page)
        await files_and_tools(page)
        await charts_and_more(page)
        await graphs_and_networks(page)
        await tests_and_python(page)
        await boundary_delay_pde(page)
        await statistics_learning(page)
        await control_systems(page)
        await global_optimization(page)
        await wavelets_and_denoising(page)
        await quiver_arrows(page)
        await core_additions(page)
        await image_additions(page)
        await problem_based(page)
        await toolbox_fillins(page)
        await pde_toolbox(page)
        await core_fillins(page)
        await econometrics(page)
        await finance(page)
        await comms_audio(page)
        await system_identification(page)
        await fuzzy_logic(page)
        await editor_view(page)
        await drops(page)
        await parallel(page)
        await statistics(page)
        await user_interfaces(page)
        await figure_files(page)
        await series_kinds(page)
        await optimization(page)
        await symbolic(page)
        await docs(page)
        await windows(page)
        await mapping(page)
        await apps(page)
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
        check('phone: the Workspace shows', await page.ev("PL.app.toolShown('ws') && !PL.app.pWs.hidden && PL.app.pWs.getBoundingClientRect().height > 100"), True)
        check('phone: with the variable', await page.ev("PL.app.ws.rows.some(r => r.name === 'x')"), True)
        check('phone: still no sideways scroll', await page.ev('document.documentElement.scrollWidth <= innerWidth'), True)
        await shot(page, 'phone.png')
        check('phone: no script errors', page.errors, [])
    finally:
        await page.close()
    return check.done()


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
