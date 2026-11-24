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
- the Editor commenting out a file of 200,000 lines.

The Editor's edit took hours through insertText, which keeps an edit for
the browser's undo but takes time as the lines it puts in times the lines
there are. Such an edit now goes in at once, and the Editor keeps its undo:
Ctrl/⌘+Z and Shift+Ctrl/⌘+Z take it back and put it in again, the typing
between two such edits is one step of its own, and the browser's Edit menu
takes it back too. A small edit still goes through insertText, the
browser's own undo taking it back.

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


ED = 'PL.app.current.editor'
# insertText calls counted, the call itself made: an expression run with the spy in place
SPY = ("(() => {{ const e = {ed}; window._ins = 0; const ex = document.execCommand; "
       "document.execCommand = function (c, ...r) {{ if (c === 'insertText') _ins++; return ex.call(document, c, ...r); }}; "
       "try {{ {body} }} finally {{ document.execCommand = ex; }} }})()")
# which of the texts kept in the page the Editor holds
WHICH = (f"(() => {{ const v = {ED}.value; return v === _orig ? 'original' : v === _c1 ? 'commented' : v === _typed ? 'typed' "
         ": v === _u2 ? 'uncommented' : 'other'; })()")


async def zkey(page, redo=False):
    """Ctrl/⌘+Z (with Shift: redo) as a keyboard gives it, the browser's own undo or redo behind it."""
    mods = (4 if await page.ev('PL.util.isMac') else 2) | (8 if redo else 0)
    for kind in ('rawKeyDown', 'keyUp'):
        await page.call('Input.dispatchKeyEvent', {'type': kind, 'key': 'Z' if redo else 'z', 'code': 'KeyZ', 'windowsVirtualKeyCode': 90, 'modifiers': mods,
                                                   'commands': ['redo' if redo else 'undo'] if kind == 'rawKeyDown' else []}, session=page.sid)
    await asyncio.sleep(0.05)


async def editor(page):
    await page.call('Emulation.setFocusEmulationEnabled', {'enabled': True}, session=page.sid)
    await command(page, "cd /home/user; fid = fopen('bigcomment.m', 'w'); fprintf(fid, 'x = %d;\\n', 1:200000); fclose(fid); edit bigcomment.m")
    await until(page, f"PL.app.current && PL.app.current.key === '/home/user/bigcomment.m' && {ED}.value.length > 1000000", 30)
    stack(page)
    # insertText, which keeps an edit for the browser's undo, takes time as the lines it puts in times
    # the lines there are (hours for these): an edit so big goes in at once, the Editor keeping its undo
    got = await page.ev(SPY.format(ed=ED, body="window._orig = e.value; e.ta.setSelectionRange(0, e.value.length); const t0 = performance.now(); "
                                                "e.commentLines(true); window._ms = performance.now() - t0; window._c1 = e.value; "
                                                "const L = e.value.split('\\n'); return [L[0], L[L.length - 2], L.length, _ins];"), timeout=120)
    print(f"     (commented out in {await page.ev('Math.round(_ms)')} ms)")
    check('the Editor comments out a file of 200,000 lines, at once (no insertText)', (got, stack(page)), (['% x = 1;', '% x = 200000;', 200001, 0], []))
    await zkey(page)
    st = await page.ev(f"[{WHICH}, {ED}.ta.selectionStart, {ED}.ta.selectionEnd === _orig.length]")
    check('Ctrl/⌘+Z takes it back: the file as it was, its lines selected again', st, ['original', 0, True])
    await zkey(page, redo=True)
    check('Shift+Ctrl/⌘+Z puts it in again', await page.ev(WHICH), 'commented')

    # typed at the end, then all of it uncommented: undo takes back that edit, the typing as one step
    # (the browser's own steps for it no longer apply), the first edit, then nothing; redo puts each back
    await page.ev(f"(() => {{ const e = {ED}; e.focus(); e.ta.setSelectionRange(e.value.length, e.value.length); return 1; }})()")
    for text in ('abc', 'def'):
        await page.call('Input.insertText', {'text': text}, session=page.sid)
    await page.ev(f"(() => {{ const e = {ED}; window._typed = e.value; e.ta.setSelectionRange(0, e.value.length); e.commentLines(false); "
                  "window._u2 = e.value; return 1; })()")
    states = []
    for _ in range(4):
        await zkey(page)
        states.append(await page.ev(WHICH))
        if len(states) == 2:
            states.append(await page.ev(f'{ED}.ta.selectionStart === _c1.length'))
    check('typing between two such edits: Ctrl/⌘+Z takes back the second edit, the typing as one step (the caret where it began), the first edit, then nothing',
          (states, stack(page)), (['typed', 'commented', True, 'original', 'original'], []))
    states = []
    for _ in range(3):
        await zkey(page, redo=True)
        states.append(await page.ev(WHICH))
    check('and Shift+Ctrl/⌘+Z puts each back', states, ['commented', 'typed', 'uncommented'])
    # the browser's Edit menu sends beforeinput with no key
    st = await page.ev(f"(() => {{ const ev = new InputEvent('beforeinput', {{ inputType: 'historyUndo', cancelable: true, bubbles: true }}); "
                       f"{ED}.ta.dispatchEvent(ev); return [ev.defaultPrevented, {WHICH}]; }})()")
    check("the browser's Edit menu's Undo on such an edit (beforeinput, no key)", st, [True, 'typed'])

    # a small edit is the browser's: through insertText, and its own undo takes it back
    small = 'a = 1;\nb = 2;\nc = 3;\n'
    got = await page.ev(SPY.format(ed=ED, body=f"e.value = {json.dumps(small)}; e.ta.setSelectionRange(0, e.value.length); e.commentLines(true); return [e.value, _ins];"))
    await zkey(page)
    check("a small edit goes through insertText, and the browser's own undo takes it back", (got, await page.ev(f'{ED}.value')),
          (['% a = 1;\n% b = 2;\n% c = 3;\n', 1], small))
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
