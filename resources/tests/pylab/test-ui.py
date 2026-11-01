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

Start a server on the repository root and headless Chrome (the recipe is in
README.md) on PYLAB_HTTP_PORT and PYLAB_CDP_PORT (defaults 8811, 9311), then

    python3 resources/tests/pylab/test-ui.py

With PYLAB_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import os
import sys

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
