#!/usr/bin/env python3
"""The in-page questions that replaced prompt() and confirm() (rbAskText,
rbAskConfirm in rb-utils.js), driven with real key events.

Saving a preset asked for its name with prompt() and deleting one asked
confirm(). In a frame sandboxed without allow-modals -- a VS Code webview is
one -- both return at once without showing anything, so a preset could be
neither saved nor deleted there. The questions are dialogs in the page now:

  * Enter in the name field saves, Escape and Cancel save nothing;
  * the delete question opens on top of the preset manager, and an Escape
    that closes it must not close the manager as well (both listen on the
    document; the question stops the key before the manager sees it);
  * a preset's name is shown as text, so one imported from a file cannot
    become markup in the question.

Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-ask.py

Exit status is 0 when every check passes.
"""
import asyncio
import json
import sys
import urllib.request

import websockets

from driver import open_page, load_samples

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


DATASET = '/biosphere/vault_A/mire/total/Ac-227'

STATE = """(() => {
  const ask = document.querySelector('.rb-ask');
  const sel = document.getElementById('presetSelect');
  return {
    open: !!ask,
    title: ask ? ask.querySelector('h3').textContent : null,
    message: ask && ask.querySelector('p') ? ask.querySelector('p').textContent : null,
    focused: ask ? (document.activeElement.tagName + ':' + (document.activeElement.textContent || document.activeElement.className)) : null,
    markupInQuestion: ask ? ask.querySelectorAll('img, script, svg, a').length : 0,
    manager: document.getElementById('presetManagerOverlay').style.display !== 'none',
    names: loadPresets().filter(p => !p.builtIn).map(p => p.name),
    selectedName: sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].textContent : null
  };
})()"""


async def key(page, name, code):
    for kind in ('keyDown', 'keyUp'):
        await page.send('Input.dispatchKeyEvent', {'type': kind, 'key': name, 'code': name,
                                                   'windowsVirtualKeyCode': code})


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=100 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=6)
        stored = await page.ev("localStorage.getItem('chartPresets')")
        try:
            await page.ev("localStorage.removeItem('chartPresets'); populatePresetDropdown(); true")
            await load_samples(page, ['sample-a.h5'])
            await page.ev("(async () => { selectDataset(%s); await new Promise(r => setTimeout(r, 2500)); })()"
                          % json.dumps(DATASET))
            check('a chart is drawn to save a view of', await page.ev("!!currentChartData"))
            base = (await page.ev(STATE))['names']   # the defaults that are not built in

            # --- saving: the name is asked for in the page --------------------
            await page.ev("saveCurrentAsPreset(); true")
            s = await page.ev(STATE)
            check('Save preset opens a question in the page', (s['open'], s['title']), (True, 'Save preset'))
            check('  with the name field focused', s['focused'], 'INPUT:url-input')
            await page.send('Input.insertText', {'text': 'Long term'})
            await key(page, 'Enter', 13)
            await page.ev("new Promise(r => setTimeout(r, 300))")
            s = await page.ev(STATE)
            check('Enter saves the preset under that name', (s['open'], s['names']), (False, base + ['Long term']))
            check('  and selects it', s['selectedName'], 'Long term')

            await page.ev("saveCurrentAsPreset(); true")
            await page.send('Input.insertText', {'text': 'Not wanted'})
            await key(page, 'Escape', 27)
            await page.ev("new Promise(r => setTimeout(r, 300))")
            s = await page.ev(STATE)
            check('Escape closes it and saves nothing', (s['open'], s['names']), (False, base + ['Long term']))

            await page.ev("saveCurrentAsPreset(); true")
            await page.ev("document.querySelector('.rb-ask .url-btn-cancel').click(); new Promise(r => setTimeout(r, 300))")
            s = await page.ev(STATE)
            check('Cancel closes it and saves nothing', (s['open'], s['names']), (False, base + ['Long term']))

            # --- deleting: the question sits on top of the manager -----------
            pid = await page.ev("loadPresets().find(p => p.name === 'Long term').id")
            delete = ("(() => { openPresetManager(); const row = [...document.querySelectorAll("
                      "'#presetManagerList .preset-manager-row')].find(r => r.dataset.presetId === %s);"
                      " [...row.querySelectorAll('button')].find(b => b.textContent === 'Delete').click();"
                      " return true; })()" % json.dumps(pid))
            await page.ev(delete)
            s = await page.ev(STATE)
            check('Delete asks first, naming the preset',
                  (s['open'], s['title'], s['message']), (True, 'Delete preset', 'Delete the preset “Long term”?'))
            check('  with its Delete button focused', s['focused'], 'BUTTON:Delete')
            await key(page, 'Escape', 27)
            await page.ev("new Promise(r => setTimeout(r, 300))")
            s = await page.ev(STATE)
            check('Escape answers no, and leaves the manager open',
                  (s['open'], s['manager'], s['names']), (False, True, base + ['Long term']))

            await page.ev("document.querySelector('#presetManagerOverlay').style.display !== 'none' || openPresetManager(); true")
            await page.ev(delete)
            await page.ev("document.querySelector('.rb-ask .url-btn-load').click(); new Promise(r => setTimeout(r, 300))")
            s = await page.ev(STATE)
            check('Delete in the question deletes it', (s['open'], s['names']), (False, base))
            await page.ev("closePresetManager(); true")

            # --- a name from a file is text ----------------------------------
            await page.ev("""(() => {
              const presets = loadPresets();
              presets.push({ id: 'user_x', name: '<img src=x onerror="window.__owned=1">', builtIn: false,
                             xScale: 'linear', yScale: 'linear', xMin: null, xMax: null, yMin: null, yMax: null });
              savePresetsToStorage(presets);
              populatePresetDropdown();
              return true;
            })()""")
            await page.ev(delete.replace(json.dumps(pid), json.dumps('user_x')))
            s = await page.ev(STATE)
            check('a name with markup in it is shown as text',
                  (s['message'], s['markupInQuestion']), ('Delete the preset “<img src=x onerror="window.__owned=1">”?', 0))
            await page.ev("document.querySelector('.rb-ask .url-btn-cancel').click(); closePresetManager(); true")
            check('  and runs nothing', await page.ev("window.__owned === undefined"))

            check('no console errors throughout', page.logs[:3], [])
        finally:
            await page.ev("(v => { if (v === null) localStorage.removeItem('chartPresets');"
                          " else localStorage.setItem('chartPresets', v); return true; })(%s)" % json.dumps(stored))
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget',
                                       'params': {'targetId': tid}}))

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
