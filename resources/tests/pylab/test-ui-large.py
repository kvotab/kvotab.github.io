#!/usr/bin/env python3
"""pylab.html in a real browser: figures, controls, dialogs and the Editor
with 200,000 of a thing.

An array spread into one call (Math.min(...values),
node.replaceChildren(...rows)) runs past the stack at some 125,000 values.
Where the page did that with a plot's data, a list's items or a file's
lines, it failed so, and each check here did:

- a line of 200,000 points picked with the figure's edit tool (its outline);
- a click on a pcolor of 400 by 400 (the surface under the click, whose
  ButtonDownFcn never ran);
- an axes whose XTick holds 200,000 values, and a right y-axis whose YTick
  does (the labels' size: the axes, or the whole figure, not drawn);
- a uitable of 200,000 rows, a listbox, a pop-up menu and a text control of
  200,000 lines, an app's list box and drop-down, editable or not, of
  200,000 items (the window never showed);
- listdlg of 200,000 items (no dialog), and uigetfile on a folder of
  130,000 files (an empty list);
- the Editor commenting out a file of 200,000 lines (the text written as
  the Editor writes it when insertText is refused: through insertText,
  which keeps undo, that many lines take hours).

And a bar picked in the property editor's tree: its outline asked the
heights, a typed array, for concat.

Start a server on the repository root and headless Chrome as README.md
says, on PYLAB_HTTP_PORT and PYLAB_CDP_PORT (defaults 8811 and 9311), then

    python3 resources/tests/pylab/test-ui-large.py

Exit status 0 when every check passes.
"""
import asyncio
import json
import math
import sys

from cdp import BASE, Checks, open_page, wait_engine

check = Checks()
WIN = '[...PL.app.figures.wins.values()].pop()'
INSP = 'PL.app.figures.inspector'
# The Command Window writes in the next animation frame: write what is pending.
OUTPUT = '(() => { const c = PL.app.cmd; if (c.pendingRuns && c.pendingRuns.length) { cancelAnimationFrame(c._raf); c._flush(); } return c.out.textContent; })()'


async def until(page, expr, secs=30):
    for _ in range(int(secs * 10)):
        v = await page.ev(expr)
        if v and not (isinstance(v, str) and v.startswith('EXCEPTION')):
            return v
        await asyncio.sleep(0.1)
    return None


async def idle(page):
    await until(page, '!PL.engine.busy', 120)
    await asyncio.sleep(0.3)


async def command(page, code):
    """Run a command as the page does and wait for it; the end of the Command Window's text."""
    await page.ev(f'PL.app.runCommand({json.dumps(code)}).then(() => 1)', timeout=300)
    await idle(page)
    return (await page.ev(OUTPUT))[-200:]


def stack(page):
    """The script errors and console errors since the last call, their first lines."""
    out = [e.split('\n')[0][:200] for e in page.errors + page.console if 'favicon' not in e]
    page.errors.clear()
    page.console.clear()
    return out


async def in_axes(page, x, y):
    """Page coordinates of a data point in the newest window's first axes."""
    return await page.ev(f"(() => {{ const w = {WIN}; const f = w.renderer.frames[0]; const c = w.canvas.getBoundingClientRect(); "
                         f"return [c.left + f.fr.fx({x}), c.top + f.fr.fy({y})]; }})()")


async def click_dialog(page, label):
    return await page.ev(f"(() => {{ const b = [...document.querySelectorAll('.pl-dialog .pl-dfoot button')].find(b => b.textContent === {json.dumps(label)}); "
                         "if (!b) return false; b.click(); return true; })()")


async def window(page, code):
    """close all, then code, and wait for its window."""
    stack(page)
    await command(page, f'close all; {code}')
    await until(page, 'PL.app.figures.wins.size === 1', 10)
    await asyncio.sleep(0.5)


async def figures(page):
    await window(page, 'x = 1:200000; plot(x, sin(x / 1000));')
    await page.ev(f'{WIN}.toolBtns.edit.click(); 1')
    await until(page, f'{INSP} && !{INSP}.el.hidden && {INSP}.data && {INSP}.data.label')
    px, py = await in_axes(page, 100000, math.sin(100))
    await page.click(px, py)
    picked = await until(page, f"{INSP}.data.type === 'line' && {WIN}.selection", 10)
    box = await page.ev(f'(() => {{ const w = {WIN}; const b = w.selectionBox(w.selection); return !!b && b.w > 100 && b.h > 50; }})()')
    check('the edit tool outlines a line of 200,000 points it picked', (bool(picked), box, stack(page)), (True, True, []))

    await window(page, 'bar([3 5 2 4]);')
    await page.ev(f'{WIN}.toolBtns.edit.click(); 1')
    await until(page, f'{INSP} && !{INSP}.el.hidden && {INSP}.data && {INSP}.data.label')
    bars = await page.ev(f'{WIN}.fig.axes[0].children[0].id')
    await page.ev(f"{INSP}.tree.querySelector('[data-id=\"{bars}\"]').click(); 1")
    picked = await until(page, f'{WIN}.selection === {bars}', 10)
    box = await page.ev(f'(() => {{ const w = {WIN}; const b = w.selectionBox(w.selection); return !!b && b.h > 50; }})()')
    check("a bar picked in the editor's tree is outlined, down to its base", (bool(picked), box, stack(page)), (True, True, []))

    await window(page, "[X, Y] = meshgrid(1:400, 1:400); h = pcolor(X, Y, X + Y); shading flat; hit = 0; set(h, 'ButtonDownFcn', 'hit = hit + 1;');")
    px, py = await in_axes(page, 200, 200)
    await page.click(px, py)
    await asyncio.sleep(0.5)
    await idle(page)
    out = await command(page, 'fprintf("%d\\n", hit)')
    check('a click on a pcolor of 400 by 400 runs its ButtonDownFcn', (out.rstrip()[-1:], stack(page)), ('1', []))

    await window(page, "plot(1:200000); set(gca, 'XTick', 1:200000);")
    check('an axes whose XTick holds 200,000 values is drawn', (await page.ev(f'{WIN}.renderer.frames.length'), stack(page)), (1, []))

    await window(page, 'yyaxis right; plot(1:10);')
    few = await page.ev(f'{WIN}.renderer.frames.length')
    await window(page, "yyaxis right; plot(1:200000); set(gca, 'YTick', 1:200000);")
    check('a right y-axis whose YTick holds 200,000 values is drawn, as with ten', (await page.ev(f'{WIN}.renderer.frames.length'), stack(page)), (few, []))


async def controls(page):
    await command(page, "s = cellstr(num2str((1:200000)'));")

    async def shown(code, count):
        await window(page, code)
        return await until(page, count, 60), stack(page)

    check('a uitable of 200,000 rows shows them', await shown("uitable(figure, 'Data', rand(200000, 2), 'Units', 'normalized', 'Position', [0 0 1 1]);",
                                                             f"{WIN}.el.querySelectorAll('.pl-uilayer table tbody tr').length"), (200000, []))
    for style in ('listbox', 'popupmenu'):
        check(f'a {style} of 200,000 items lists them', await shown(f"uicontrol(figure, 'Style', '{style}', 'String', s, 'Units', 'normalized', 'Position', [0 0 0.5 1]);",
                                                                     f"{WIN}.el.querySelectorAll('select option').length"), (200000, []))
    check('a text control of 200,000 lines shows them', await shown("uicontrol(figure, 'Style', 'text', 'String', s, 'Units', 'normalized', 'Position', [0 0 0.5 1]);",
                                                                    f"{WIN}.el.querySelector('.pl-uitext .lines').childElementCount"), (200000, []))
    check("an app's list box of 200,000 items lists them", await shown("uilistbox(uifigure, 'Items', s);",
                                                                      f"{WIN}.el.querySelectorAll('select option').length"), (200000, []))
    check("an app's drop-down of 200,000 items lists them", await shown("uidropdown(uifigure, 'Items', s);",
                                                                       f"{WIN}.el.querySelectorAll('select option').length"), (200000, []))
    check("... and editable, its suggestions", await shown("uidropdown(uifigure, 'Items', s, 'Editable', 'on');",
                                                          f"{WIN}.el.querySelectorAll('datalist option').length"), (200000, []))
    await command(page, 'close all')


async def dialogs(page):
    stack(page)
    await page.ev("PL.app.runCommand(\"[k, ok] = listdlg('ListString', s);\"); 1")
    n = await until(page, "document.querySelector('.pl-dialog select') && document.querySelector('.pl-dialog select').options.length", 30)
    await click_dialog(page, 'Cancel')
    await idle(page)
    out = await command(page, 'fprintf("%d\\n", ok)')
    check('listdlg of 200,000 items lists them; Cancel', (n, out.rstrip()[-1:], stack(page)), (200000, '0', []))

    await command(page, r"pyrun(sprintf('import os\nos.makedirs(''/tmp/big'', exist_ok=True)\nfor k in range(130000): open(f''/tmp/big/f{k}.txt'', ''w'').close()'))")
    stack(page)
    await page.ev("PL.app.runCommand(\"[fn, fp] = uigetfile('/tmp/big/*.txt');\"); 1")
    n = await until(page, "document.querySelectorAll('.pl-dialog .pl-pick-row').length", 60)
    await click_dialog(page, 'Cancel')
    await idle(page)
    check('uigetfile on a folder of 130,000 files lists them (and ..)', (n, stack(page)), (130001, []))
    await command(page, "pyrun(\"import shutil; shutil.rmtree('/tmp/big')\")")


async def editor(page):
    await command(page, "cd /home/user; fid = fopen('bigcomment.m', 'w'); fprintf(fid, 'x = %d;\\n', 1:200000); fclose(fid); edit bigcomment.m")
    await until(page, "PL.app.current && PL.app.current.key === '/home/user/bigcomment.m' && PL.app.current.editor.value.length > 1000000", 30)
    stack(page)
    # The Editor writes a change through execCommand's insertText, which keeps it for undo but takes
    # time that grows as the square of the lines (seconds for 3,000, hours for 200,000): here it
    # declines, and the Editor writes the text as it does when insertText is refused.
    got = await page.ev("(() => { let out = null; const ex = document.execCommand; document.execCommand = () => false; "
                        "try { PL.app.withEditor((e) => { e.ta.setSelectionRange(0, e.ta.value.length); e.commentLines(true); "
                        "const L = e.ta.value.split('\\n'); out = [L[0], L[L.length - 2], L.length]; }); } finally { document.execCommand = ex; } return out; })()",
                        timeout=120)
    check('the Editor comments out a file of 200,000 lines', (got, stack(page)), (['% x = 1;', '% x = 200000;', 200001], []))
    await page.ev("PL.app.fileRemoved('/home/user/bigcomment.m'); 1")
    await command(page, 'delete bigcomment.m')


async def main():
    page = await open_page(f'{BASE}/pylab.html')
    try:
        check('the engine starts', await wait_engine(page), 'ready')
        await figures(page)
        await controls(page)
        await dialogs(page)
        await editor(page)
        await command(page, 'close all; clear')
        check('no script errors', stack(page), [])
    finally:
        await page.close()
    return check.done()


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
