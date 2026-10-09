#!/usr/bin/env python3
"""smui.html in a real browser: Help > Search (smui-search.js).

The magnifier at the right end of the menu bar, Help > Search… and ⌘K /
ctrl+K open the search, by real clicks and real keys (⌘K in a text field
too; ctrl+K on a Mac there is the field's own; another dialog in front keeps
its keys); every platform's red triangle is read with no error (the crawl's
counts); "word cloud" finds Analyze ▸ Text Analysis… ▸ Display Options ▸
Show Word Cloud first, "cloud" and "clouds" find it, the words found marked;
Enter with no Text Analysis report open opens its launch dialog, and after
OK the report draws its word cloud (a cancelled launch does nothing); with
a Text Analysis report in front the same result turns the cloud on there
directly, and shows ✓ on once it is; an open report's own red-triangle item
(the Word Cloud's Layout) by a real click; menu commands (Make Binning
Column…, Stack…) run, a greyed-out one says why and does nothing; a
Distribution column's item (‹column› ▸ Continuous Fit ▸ Johnson Su) goes to
the report's first column and says so, the report's own item to the other;
an item only some columns have says when it is there; help results open the
(i) panel and the Help tab at their section; ↑/↓/Enter/Escape and the
listbox's ARIA; nothing found says so and offers the Help; recent searches;
the dark theme; a phone (the dialog the whole screen, a 16 px field, no
sideways scroll); a table with hostile column names (an <img onerror>, "a ▸
b") makes no element from them and runs nothing; no script errors.

Start a server on the repository root and headless Chrome (README.md) on
SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-search.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import os
import sys

from cdp import BASE, Checks, open_page, open_report_js, wait_engine

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()
META, CTRL = 4, 2


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.6)
        await page.shot(os.path.join(SHOTS, name))


async def center(page, expr):
    """The middle of the element expr gives (scrolled into view), or None."""
    return await page.ev(f'''(() => {{ const e = {expr}; if (!e) return null; e.scrollIntoView({{ block: 'nearest' }});
      const r = e.getBoundingClientRect(); return r.width ? [r.left + Math.min(r.width / 2, 60), r.top + r.height / 2] : null; }})()''')


async def click(page, expr):
    xy = await center(page, expr)
    if not xy:
        return False
    await page.click(*xy)
    await asyncio.sleep(0.25)
    return True


async def typ(page, text):
    """Real key presses, one per character."""
    for ch in text:
        code = 'Space' if ch == ' ' else ('Key' + ch.upper()) if ch.isalpha() else ('Digit' + ch) if ch.isdigit() else ''
        await page.key(ch, code=code or None, text=ch)
    await asyncio.sleep(0.15)


async def wait_for(page, expr, seconds=30):
    for _ in range(int(seconds * 10)):
        v = await page.ev(expr)
        if v and not (isinstance(v, str) and v.startswith('EXCEPTION')):
            return v
        await asyncio.sleep(0.1)
    return await page.ev(expr)


DIALOG = "document.querySelector('.sm-search-dialog')"

# The search as it shows now: open or not, the field, the options (label, path
# levels, badge, state, the text under, selected), the status and the extra part.
STATE = r'''(() => {
  const d = document.querySelector('.sm-search-dialog');
  if (!d) return { open: false, active: document.activeElement ? (document.activeElement.className || document.activeElement.tagName) : null };
  const inp = d.querySelector('.sm-search-input');
  const opts = [...d.querySelectorAll('[role=option]')].map((o) => ({
    id: o.id, kind: o.dataset.kind, selected: o.getAttribute('aria-selected'), disabled: o.getAttribute('aria-disabled'),
    label: o.querySelector('.sm-search-label').textContent,
    path: [...o.querySelectorAll('.sm-search-lv')].map((l) => l.textContent),
    badge: o.querySelector('.sm-search-badge').textContent,
    state: o.querySelector('.sm-search-state') ? o.querySelector('.sm-search-state').textContent : null,
    under: (o.querySelector('.sm-search-snip, .sm-search-why') || { textContent: '' }).textContent,
    marks: [...o.querySelectorAll('.sm-search-label mark')].map((m) => m.textContent) }));
  return { open: true, value: inp.value, focused: document.activeElement === inp, opts, status: d.querySelector('.sm-search-status').textContent,
    extra: d.querySelector('.sm-search-extra').textContent, active: inp.getAttribute('aria-activedescendant'), expanded: inp.getAttribute('aria-expanded'),
    role: inp.getAttribute('role'), list: d.querySelector('[role=listbox]') ? d.querySelector('[role=listbox]').id : null, controls: inp.getAttribute('aria-controls'),
    title: d.querySelector('.sm-dialog-head h2').textContent, info: d.querySelector('.sm-dialog-head .info-btn') ? d.querySelector('.sm-dialog-head .info-btn').dataset.info : null,
    dialogs: document.querySelectorAll('.sm-dialog').length };
})()'''

# the text and path of the result at index i, joined for a message
JOIN = ' ▸ '


def where(o):
    return JOIN.join(o['path'] + [o['label']])


async def state(page):
    return await page.ev(STATE)


async def close_search(page):
    """Closed by its × (a real click)."""
    if (await state(page))['open']:
        await click(page, f"{DIALOG}.querySelector('.sm-dialog-x')")
        await asyncio.sleep(0.2)
    return not (await state(page))['open']


async def search(page, text, how='button'):
    """Open the search (button, keys) and type text with real keys."""
    st = await state(page)
    if not st['open']:
        if how == 'button':
            await click(page, "document.querySelector('.sm-menuend .sm-searchbtn')")
        else:
            await page.key('k', code='KeyK', modifiers=META)
        await wait_for(page, f'!!{DIALOG}', 10)
        await asyncio.sleep(0.25)
    await page.ev(f"(() => {{ const i = {DIALOG}.querySelector('.sm-search-input'); i.focus(); i.select(); }})()")
    await page.key('Backspace', code='Backspace')
    await typ(page, text)
    await wait_for(page, f"({DIALOG} && !/Reading/.test({DIALOG}.querySelector('.sm-search-status').textContent))", 20)
    return await state(page)


def find(st, pred):
    for i, o in enumerate(st['opts']):
        if pred(o):
            return i, o
    return None, None


async def click_option(page, i):
    return await click(page, f"{DIALOG}.querySelectorAll('[role=option]')[{i}]")


LAST = 'SM.app.reports[SM.app.reports.length - 1]'

# A red triangle's item clicked down its labels (a real menu, clicked by script),
# as test-ui-text's PICK does; waits for the report to run again.
PICK = r'''
(async (title, path) => {
  const rep = SM.app.activeTab.report;
  const heads = [...rep.body.querySelectorAll('.sm-ob-head')].filter(h => (h.querySelector('h2, h3, h4').textContent.trim() === title) || (title === '*top*' && h.querySelector('h2')));
  if (!heads.length) throw new Error('no outline ' + title);
  heads[0].querySelector('.sm-ob-menu').click();
  await new Promise(r => setTimeout(r, 60));
  let done = null;
  for (let i = 0; i < path.length; i++) {
    const menus = [...document.querySelectorAll('.sm-menu')];
    const b = [...menus[menus.length - 1].querySelectorAll('button')].find(x => x.querySelector('.sm-label').textContent === path[i]);
    if (!b) throw new Error('no item ' + path[i]);
    if (i === path.length - 1) done = new Promise(res => rep.on('done', res));
    b.click();
    await new Promise(r => setTimeout(r, 80));
  }
  await done;
  return true;
})
'''


def pick_js(title, path):
    return f'({PICK})({json.dumps(title)}, {json.dumps(path)})'


# The word cloud of the report in front, and the Text Analysis column's options.
CLOUD = r'''(() => { const rep = SM.app.activeTab && SM.app.activeTab.report; if (!rep || rep.platform.id !== 'text') return null;
  const id = rep.spec.roles.text[0];
  const ws = [...rep.body.querySelectorAll('svg.sm-tx-cloud text.sm-tx-word')].map(w => ({ t: w.lastChild.textContent, x: Number(w.getAttribute('x')), y: Number(w.getAttribute('y')) }));
  return { cloud: !!rep.body.querySelector('svg.sm-tx-cloud'), on: rep.spec.options[id + '|cloud'] === true, layout: rep.spec.options[id + '|cloudLayout'] || null,
           reading: ws.slice().sort((a, b) => a.y - b.y || a.x - b.x).map(w => w.t), n: ws.length, reports: SM.app.reports.length, title: rep.title, running: rep.body.classList.contains('is-running') }; })()'''

TOAST = "(document.querySelector('.sm-toast') || { textContent: '' }).textContent"


async def until_drawn(page, seconds=600):
    """The report in front once its run is done."""
    return await wait_for(page, '(() => { const r = SM.app.activeTab && SM.app.activeTab.report; return !!r && !r.body.classList.contains("is-running") && !r.content.querySelector(".sm-waiting"); })()', seconds)


def lum(rgb):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = sorted([lum(a), lum(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


def rgb_of(s):
    """A computed colour as 0-255 sRGB: rgb()/rgba(), and what color-mix()
    computes to in Chrome, oklab(L a b) or color(srgb r g b)."""
    s = s.strip()
    inner = s[s.index('(') + 1:s.rindex(')')].split('/')[0]
    if s.startswith('color('):
        r, g, b = [float(v) for v in inner.split()[1:4]]
        return (r * 255, g * 255, b * 255)
    if s.startswith('oklab('):
        L, a, b = [float(v.rstrip('%')) / (100 if v.endswith('%') else 1) for v in inner.split()[:3]]
        l_, m_, s_ = L + 0.3963377774 * a + 0.2158037573 * b, L - 0.1055613458 * a - 0.0638541728 * b, L - 0.0894841775 * a - 1.2914855480 * b
        l3, m3, s3 = l_ ** 3, m_ ** 3, s_ ** 3
        lin = (4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3, -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3, -0.0041960863 * l3 - 0.7034186147 * m3 + 1.7076147010 * s3)
        gam = lambda c: 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
        return tuple(255 * min(1, max(0, gam(max(0.0, c)))) for c in lin)
    return tuple(float(x) for x in inner.replace(',', ' ').split()[:3])


async def main():
    page = await open_page(f'{BASE}/smui.html?example=service-comments', height=1000)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    check('no script errors at load', page.errors, [])
    await page.ev("localStorage.removeItem('smui.search.recent')")

    # ---- the ways in --------------------------------------------------------------------------------
    b = await page.ev('''(() => { const end = document.querySelector('.sm-menubar .sm-menuend'); const b = end && end.querySelector('.sm-searchbtn');
      if (!b) return null; const r = b.getBoundingClientRect(), bar = document.querySelector('.sm-menubar').getBoundingClientRect();
      return { first: end.firstElementChild === b, label: b.getAttribute('aria-label'), title: b.getAttribute('title'), keys: b.getAttribute('aria-keyshortcuts'), text: b.textContent,
               inBar: r.top >= bar.top - 1 && r.bottom <= bar.bottom + 1 && r.right <= bar.right + 1, one: document.querySelectorAll('.sm-searchbtn').length, mac: SM.search.isMac }; })()''')
    mac = b and b['mac']
    check('a Search button at the right end of the menu bar, in the menu bar\'s end part, once', (bool(b), b and b['first'], b and b['inBar'], b and b['one']), (True, True, True, 1))
    check('... it names its shortcut to screen readers, and has no tooltip', (b['label'], b['keys'], b['title']), (f'Search for a feature ({"⌘K" if mac else "Ctrl+K"})', 'Meta+K' if mac else 'Control+K', None))
    check('... and shows Search and the shortcut', b['text'], f'Search{"⌘K" if mac else "Ctrl+K"}')
    await click(page, "document.querySelector('.sm-menuend .sm-searchbtn')")
    await wait_for(page, f'!!{DIALOG}', 10)
    await asyncio.sleep(0.3)
    s = await state(page)
    check('a real click on the button opens the search, the field focused', (s['open'], s['focused'], s['title']), (True, True, 'Search'))
    check('... a combobox field for a listbox of results', (s['role'], s['controls'] == s['list'] and bool(s['list'])), ('combobox', True))
    check('... with an (i) in its title bar on the search\'s own topic', s['info'], 'help:search')
    check('... with nothing typed: how to search, and some to try', ('Type a word or two' in s['extra'], 'word cloud' in s['extra'], s['opts']), (True, True, []))
    info = await page.ev('''(async () => { document.querySelector('.sm-search-dialog .sm-dialog-head .info-btn').click(); await new Promise(r => setTimeout(r, 200));
      const p = document.querySelector('.info-panel'); const out = p ? { title: p.querySelector('.info-panel-title').textContent, heads: [...p.querySelectorAll('h3')].map(h => h.textContent) } : null;
      KvotInfo.close(); return out; })()''')
    check('the (i) explains the search: what it finds, the order, the keys', (info or {}).get('title'), 'Search')
    check('... its sections', (info or {}).get('heads'), ['What it finds', 'Order', 'Keys', 'Recent'])
    check('the × closes it (a real click)', await close_search(page), True)
    check('... and the focus goes back to the button', await page.ev("document.activeElement === document.querySelector('.sm-searchbtn')"), True)

    # Help > Search…, by real clicks
    await click(page, "document.querySelector('.sm-menubar button[data-menu=\"Help\"]')")
    await asyncio.sleep(0.3)
    item = await page.ev('''(() => { const m = [...document.querySelectorAll('.sm-menu')].pop(); const b = m && [...m.querySelectorAll('button')].find(x => x.querySelector('.sm-label').textContent === 'Search…');
      return b ? { key: (b.querySelector('.sm-key') || {}).textContent || null, after: b.previousElementSibling && b.previousElementSibling.querySelector('.sm-label') ? b.previousElementSibling.querySelector('.sm-label').textContent : null } : null; })()''')
    check('Help has Search…, after Help for This Page, with its shortcut', item, {'key': 'ctrl K', 'after': 'Help for This Page'})
    await click(page, "[...[...document.querySelectorAll('.sm-menu')].pop().querySelectorAll('button')].find(x => x.querySelector('.sm-label').textContent === 'Search…')")
    await wait_for(page, f'!!{DIALOG}', 10)
    s = await state(page)
    check('Help > Search… (real clicks) opens the search, the menu closed', (s['open'], await page.ev("document.querySelectorAll('.sm-menu').length")), (True, 0))
    await close_search(page)

    # ⌘K and ctrl+K, real keys
    await page.ev('document.activeElement && document.activeElement.blur && document.activeElement.blur()')
    await page.key('k', code='KeyK', modifiers=META)
    await asyncio.sleep(0.4)
    s = await state(page)
    check('⌘K (a real key) opens the search', (s['open'], s.get('focused')), (True, True))
    await page.key('k', code='KeyK', modifiers=META)
    await asyncio.sleep(0.3)
    s = await state(page)
    check('... again while it is open: still one search, its field in use', (s['open'], s['dialogs'], s['focused']), (True, 1, True))
    await close_search(page)
    await page.key('k', code='KeyK', modifiers=CTRL)
    await asyncio.sleep(0.4)
    check('ctrl+K (a real key) opens it too', (await state(page))['open'], True)
    await close_search(page)
    # in a text field: the Columns panel's filter
    await click(page, "document.querySelector('.sm-side input')")
    await typ(page, 'co')
    await page.key('k', code='KeyK', modifiers=META)
    await asyncio.sleep(0.4)
    s = await state(page)
    check('in a text field: plain keys are the field\'s (no search), ⌘K opens the search', (await page.ev("document.querySelector('.sm-side input').value"), s['open']), ('co', True))
    await close_search(page)
    await click(page, "document.querySelector('.sm-side input')")
    await page.key('k', code='KeyK', modifiers=CTRL)
    await asyncio.sleep(0.4)
    check('... ctrl+K in a text field on a Mac is the field\'s own (elsewhere it opens the search)', (await state(page))['open'], not mac)
    await close_search(page)
    await page.ev("(() => { const i = document.querySelector('.sm-side input'); i.value = ''; i.dispatchEvent(new Event('input', { bubbles: true })); i.blur(); })()")
    # another dialog in front keeps its keys
    await page.ev("SM.app.launch('distribution')")
    await wait_for(page, "!!document.querySelector('.sm-launch-dialog')", 10)
    await page.key('k', code='KeyK', modifiers=META)
    await asyncio.sleep(0.4)
    check('with another dialog in front, ⌘K leaves it alone', ((await state(page))['open'], await page.ev("!!document.querySelector('.sm-launch-dialog')")), (False, True))
    await click(page, "document.querySelector('.sm-launch-dialog .sm-dialog-x')")

    # ---- the index: every platform's red triangle read, with no error --------------------------------
    stats = await page.ev('(async () => { await SM.search.ready(); return SM.search.stats(); })()', timeout=120)
    menu_platforms = await page.ev('SM.platforms.all().filter(p => p.menu && !p.hidden).length')
    check('every platform of the menus is read', (stats['platforms'], stats['readings'] >= stats['platforms']), (menu_platforms, True))
    check('... with no error, in a red triangle or a column\'s', (stats['errors'], stats['columnErrors']), ([], []))
    check(f'... {stats["items"]:,} red-triangle items read (≥ 2,000), {stats["entries"].get("triangle", 0):,} of them platforms\' own and different (≥ 1,000)', (stats['items'] >= 2000, stats['entries'].get('triangle', 0) >= 1000), (True, True))
    check(f'... the outlines of columns read with the engine never asked ({stats["outlines"]}, {stats["columnItems"]} items)', (stats['outlines'] >= 2, stats['columnItems'] >= 80), (True, True))
    check(f'... the items every report has indexed once ({stats["entries"].get("common", 0)}), the help ({stats["entries"].get("help", 0)} topics and sections)', (stats['entries'].get('common', 0) >= 15, stats['entries'].get('help', 0) >= 200), (True, True))
    check(f'... read in {stats["ms"]} ms (under 2 s)', stats['ms'] < 2000, True)
    check('... and the engine asked nothing for it', await page.ev('SM.engine.busy'), 0)

    # ---- "word cloud" ----------------------------------------------------------------------------------
    s = await search(page, 'word cloud')
    i, o = find(s, lambda o: o['kind'] == 'triangle')
    check('"word cloud": the first red-triangle result is Analyze ▸ Text Analysis… ▸ Display Options ▸ Show Word Cloud', where(o) if o else None, 'Analyze ▸ Text Analysis… ▸ Display Options ▸ Show Word Cloud')
    check('... and it is the first result of all, marked as the one Enter chooses', (i, s['opts'][0]['selected'], s['active'] == s['opts'][0]['id']), (0, 'true', True))
    check('... badged as Text Analysis\'s red triangle, the words found marked', (o['badge'], o['marks']), ('Red triangle · Text Analysis', ['Word', 'Cloud']))
    check('... it says what Enter does here (no Text Analysis report open)', 'Enter opens Text Analysis… first' in o['under'], True)
    check('... help comes after the commands', [x['kind'] for x in s['opts']].index('help') > i, True)
    for q in ('cloud', 'clouds', 'CLOUD', 'word clou'):
        r = await page.ev(f'SM.search.query({json.dumps(q)}).filter(x => x.kind === "triangle").map(x => x.where.join(" ▸ "))')
        check(f'"{q}" finds it among the red-triangle items, first', r[:1], ['Analyze ▸ Text Analysis… ▸ Display Options ▸ Show Word Cloud'])
    r = await page.ev('[SM.search.query("text analysis…")[0], SM.search.query("text analysis")[0]].map(x => x.where.join(" ▸ "))')
    check('with or without "…": "text analysis…" and "text analysis" find Analyze ▸ Text Analysis… first', r, ['Analyze ▸ Text Analysis…', 'Analyze ▸ Text Analysis…'])
    await shot(page, 'search-01-word-cloud.png')

    # Enter: Text Analysis's launch dialog; Cancel does nothing
    await page.key('Enter', code='Enter')
    ok = await wait_for(page, "!!document.querySelector('.sm-launch-dialog')", 15)
    n_rep = await page.ev('SM.app.reports.length')
    check('Enter with no Text Analysis report open: its launch dialog, the search gone', (bool(ok), (await state(page))['open'], await page.ev("document.querySelector('.sm-launch-dialog .sm-dialog-head h2').textContent")), (True, False, 'Text Analysis'))
    await click(page, "[...document.querySelectorAll('.sm-launch-dialog .sm-actions .sm-btn')].find(b => b.textContent === 'Cancel')")
    await asyncio.sleep(1.0)
    check('... a cancelled launch does nothing (no report, nothing applied later)', (await page.ev('SM.app.reports.length'), await page.ev("!!document.querySelector('.sm-dialog')")), (n_rep, False))
    s = await search(page, 'word cloud')
    await page.key('Enter', code='Enter')
    await wait_for(page, "!!document.querySelector('.sm-launch-dialog')", 15)
    await page.ev('''(() => { const dlg = document.querySelector('.sm-launch-dialog');
      const li = [...dlg.querySelectorAll('.sm-pick-list li')].find(x => x.textContent === 'comment'); li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      [...dlg.querySelectorAll('.sm-role')].find(r => r.querySelector('.sm-btn').textContent === 'Text Columns').querySelector('.sm-btn').click(); })()''')
    await click(page, "[...document.querySelectorAll('.sm-launch-dialog .sm-actions .sm-btn')].find(b => b.textContent === 'OK')")
    await until_drawn(page)
    c = await wait_for(page, f'(() => {{ const c = {CLOUD}; return c && c.cloud ? c : null; }})()', 60)
    toast = await page.ev(TOAST)
    check('after OK the report has its word cloud: Show Word Cloud applied', (c or {}).get('cloud'), True)
    check('... the column\'s option on, in the one new report', ((c or {}).get('on'), (c or {}).get('reports'), (c or {}).get('title')), (True, n_rep + 1, 'Text Analysis for comment'))
    check('... and a message says what was applied', toast, 'Turned on Show Word Cloud (Display Options) in Text Analysis for comment')
    await shot(page, 'search-02-launched-cloud.png')

    # with the report in front: the same result turns the cloud on there, directly
    await page.ev(pick_js('*top*', ['Display Options', 'Show Word Cloud']))
    c = await page.ev(CLOUD)
    check('(the cloud turned off by the red triangle)', (c['cloud'], c['on']), (False, False))
    s = await search(page, 'word cloud', how='keys')
    i, o = find(s, lambda o: o['kind'] == 'triangle')
    check('with a Text Analysis report in front: the result says it applies there, now off', (where(o), o['state'], 'Enter applies to Text Analysis for comment' in o['under']), ('Analyze ▸ Text Analysis… ▸ Display Options ▸ Show Word Cloud', 'off', True))
    check('... still the first result (Edit ▸ Undo Show Word Cloud, which names it, comes later)', (i, any(where(x) == 'Edit ▸ Undo Show Word Cloud' for x in s['opts'][1:])), (0, True))
    check('... and the report\'s own copy of the item is not listed twice', [where(x) for x in s['opts'] if x['label'] == 'Show Word Cloud'], ['Analyze ▸ Text Analysis… ▸ Display Options ▸ Show Word Cloud'])
    await page.key('Enter', code='Enter')
    await asyncio.sleep(0.5)
    check('Enter: no launch dialog, no new report', (await page.ev("!!document.querySelector('.sm-launch-dialog')"), await page.ev('SM.app.reports.length')), (False, n_rep + 1))
    await until_drawn(page, 60)
    c = await wait_for(page, f'(() => {{ const c = {CLOUD}; return c && c.cloud ? c : null; }})()', 30)
    check('... the cloud is on again, in the same report', ((c or {}).get('cloud'), (c or {}).get('on')), (True, True))
    check('... said so', await page.ev(TOAST), 'Turned on Show Word Cloud (Display Options) in Text Analysis for comment')
    s = await search(page, 'word cloud')
    check('now the result shows ✓ on', find(s, lambda o: o['kind'] == 'triangle')[1]['state'], '✓ on')
    await close_search(page)

    # an open report's own item (the Word Cloud outline's red triangle), by a real click
    s = await search(page, 'alphabetical')
    i, o = find(s, lambda o: o['kind'] == 'live' and o['label'] == 'Alphabetical')
    check('an open report\'s own red-triangle item: Report in front, its outlines in the path', (o or {}).get('badge'), 'Report in front')
    check('... Text Analysis for comment ▸ Word Cloud ▸ Layout ▸ Alphabetical', where(o) if o else None, 'Text Analysis for comment ▸ Word Cloud ▸ Layout ▸ Alphabetical')
    await click_option(page, i)
    await until_drawn(page, 60)
    await asyncio.sleep(0.3)
    c = await page.ev(CLOUD)
    check('a real click on it: the cloud laid out alphabetically', (c['layout'] is not None, c['reading'] == sorted(c['reading'], key=lambda w: w.lower()), c['n'] > 50), (True, True, True))

    # ---- menu commands -----------------------------------------------------------------------------------
    s = await search(page, 'binning')
    check('"binning": Cols ▸ Utilities ▸ Make Binning Column… first, a Menu result', (where(s['opts'][0]), s['opts'][0]['badge']), ('Cols ▸ Utilities ▸ Make Binning Column…', 'Menu'))
    await page.key('Enter', code='Enter')
    t = await wait_for(page, "(() => { const d = [...document.querySelectorAll('.sm-dialog')].pop(); return d && !d.classList.contains('sm-search-dialog') ? d.querySelector('.sm-dialog-head h2').textContent : null; })()", 10)
    check('... Enter runs it as the menu does: its dialog', t, 'Make Binning Column')
    await click(page, "[...document.querySelectorAll('.sm-dialog')].pop().querySelector('.sm-dialog-x')")
    s = await search(page, 'stack')
    i, o = find(s, lambda o: where(o) == 'Tables ▸ Stack…')
    check('"stack": Tables ▸ Stack… first', i, 0)
    await click_option(page, i)
    t = await wait_for(page, "(() => { const d = [...document.querySelectorAll('.sm-dialog')].pop(); return d && !d.classList.contains('sm-search-dialog') ? d.querySelector('.sm-dialog-head h2').textContent : null; })()", 10)
    check('... a click runs it: the Stack dialog', t, 'Stack')
    await click(page, "[...document.querySelectorAll('.sm-dialog')].pop().querySelector('.sm-dialog-x')")
    # a greyed-out command says why and does nothing
    await page.ev("SM.app.showTable(SM.app.current.id); SM.app.current.select([])")
    s = await search(page, 'exclude unexclude')
    i, o = find(s, lambda o: where(o) == 'Rows ▸ Exclude/Unexclude')
    check('a greyed-out command: shown as not available, with why', (o['disabled'], o['under']), ('true', 'Not available: it works on the selected rows: select some rows first.'))
    await page.ev(f"{DIALOG}.querySelectorAll('[role=option]')[{i}].dispatchEvent(new MouseEvent('mousemove', {{ bubbles: true }}))")
    await page.key('Enter', code='Enter')
    await asyncio.sleep(0.3)
    s = await state(page)
    check('... Enter on it does nothing: the search stays, its status says why, no row excluded',
          (s['open'], 'not available' in s['status'], await page.ev('SM.app.current.rowsWith("excluded").length')), (True, True, 0))
    await close_search(page)

    # ---- a column's red triangle (Distribution), ‹column› --------------------------------------------------
    await page.ev("SM.app.openExample('students')")
    rep = await page.ev(open_report_js('distribution', {'y': ['height (cm)', 'weight (kg)']}))
    check('(a Distribution report of height and weight, in front)', (rep['errors'], await page.ev("SM.app.activeTab.report.platform.id")), ([], 'distribution'))
    s = await search(page, 'johnson su')
    i, o = find(s, lambda o: o['kind'] == 'triangle')
    check('"johnson su": Analyze ▸ Distribution… ▸ ‹column› ▸ Continuous Fit ▸ Johnson Su, applying to the report in front', (where(o) if o else None, 'Enter applies to Distributions' in (o or {}).get('under', '')),
          ('Analyze ▸ Distribution… ▸ ‹column› ▸ Continuous Fit ▸ Johnson Su', True))
    live = [where(x) for x in s['opts'] if x['kind'] == 'live']
    check('... with each column\'s own item of the report in front', live, ['Distributions ▸ height (cm) ▸ Continuous Fit ▸ Johnson Su', 'Distributions ▸ weight (kg) ▸ Continuous Fit ▸ Johnson Su'])
    await click_option(page, i)
    await until_drawn(page, 120)
    fits = await wait_for(page, '''(() => { const rep = SM.app.activeTab.report; const t = rep.table; const f = (n) => rep.spec.options[t.col(n).id + '|fits'] || [];
      const done = [...rep.body.querySelectorAll('.sm-ob-head h3, .sm-ob-head h4')].some(h => h.textContent === 'Fitted Johnson Su Distribution');
      return done ? { h: f('height (cm)'), w: f('weight (kg)') } : null; })()''', 120)
    check('the ‹column› item goes to the report\'s first column: height gets the Johnson Su fit, weight not', fits, {'h': ['johnsonsu'], 'w': []})
    toast = await page.ev(TOAST)
    check('... and the message says it went to the first of two', ('Johnson Su (Continuous Fit)' in toast, 'for height (cm), the first of 2' in toast, 'weight (kg)' in toast), (True, True, True))
    s = await search(page, 'johnson su weight')
    i, o = find(s, lambda o: o['kind'] == 'live')
    check('the report\'s own item for weight', where(o) if o else None, 'Distributions ▸ weight (kg) ▸ Continuous Fit ▸ Johnson Su')
    await page.ev(f"{DIALOG}.querySelectorAll('[role=option]')[{i}].dispatchEvent(new MouseEvent('mousemove', {{ bubbles: true }}))")
    await page.key('Enter', code='Enter')
    await until_drawn(page, 120)
    fits = await wait_for(page, '''(() => { const rep = SM.app.activeTab.report; const t = rep.table; const w = rep.spec.options[t.col('weight (kg)').id + '|fits'] || [];
      return w.includes('johnsonsu') ? w : null; })()''', 60)
    check('... chosen: weight gets it too', fits, ['johnsonsu'])
    s = await search(page, 'frequencies')
    i, o = find(s, lambda o: o['kind'] == 'triangle' and o['label'] == 'Frequencies')
    check('an item only a categorical column has says so', (where(o) if o else None, 'when Y is categorical' in (o or {}).get('under', '')), ('Analyze ▸ Distribution… ▸ ‹column› ▸ Display Options ▸ Frequencies', True))
    await page.ev(f"{DIALOG}.querySelectorAll('[role=option]')[{i}].dispatchEvent(new MouseEvent('mousemove', {{ bubbles: true }}))")
    await page.key('Enter', code='Enter')
    await asyncio.sleep(0.3)
    s = await state(page)
    check('... and chosen for a report of continuous columns: the search stays and says when it is there', (s['open'], 'when Y is categorical' in s['status']), (True, True))
    r = await page.ev('SM.search.query("fit line").filter(x => x.platform === "fitybyx").map(x => [x.where.join(" ▸ "), x.when])[0]')
    check('Bivariate Analysis\'s Fit Line: when Y and X are continuous', r, ['Analyze ▸ Bivariate Analysis… ▸ Fit Line', 'when Y is continuous and X continuous'])
    await close_search(page)

    # ---- help ------------------------------------------------------------------------------------------------
    s = await search(page, 'column switcher')
    i, o = find(s, lambda o: o['kind'] == 'help' and o['label'] == 'Column Switcher')
    check('"column switcher": the (i) topic among the results, after the red-triangle item', (o['badge'] if o else None, i > find(s, lambda o: o['kind'] == 'common')[0]), ('Help', True))
    await click_option(page, i)
    p = await wait_for(page, "(() => { const p = document.querySelector('.info-panel'); return p ? { title: p.querySelector('.info-panel-title').textContent, key: KvotInfo.current() } : null; })()", 10)
    check('... chosen: the (i) panel opens on it', p, {'title': 'Column Switcher', 'key': 'report:switcher'})
    await page.ev('KvotInfo.close()')
    s = await search(page, 'row states')
    i, o = find(s, lambda o: o['kind'] == 'help' and o['badge'] == 'Help tab')
    check('"row states": the Help tab\'s section', (o['label'], o['path']) if o else None, ('Row states', ['Help tab']))
    await click_option(page, i)
    await asyncio.sleep(0.4)
    h = await page.ev('''(() => { const v = SM.app.helpView, h = document.getElementById('help-rowstates');
      return { kind: SM.app.activeTab.kind, top: Math.round(h.getBoundingClientRect().top - v.getBoundingClientRect().top) }; })()''')
    check('... chosen: the Help tab in front, at that section', (h['kind'], abs(h['top']) <= 2), ('help', True))

    # ---- keys and ARIA ------------------------------------------------------------------------------------------------
    s = await search(page, 'filter')
    n = len(s['opts'])
    check('"filter": several results, the first selected', (n >= 5, s['active'] == s['opts'][0]['id'], s['expanded']), (True, True, 'true'))
    await page.key('ArrowDown', code='ArrowDown')
    await page.key('ArrowDown', code='ArrowDown')
    s2 = await state(page)
    check('↓ ↓: the third is selected, the only one, and the field\'s active descendant', ([o['selected'] for o in s2['opts']].count('true'), s2['opts'][2]['selected'], s2['active']), (1, 'true', s2['opts'][2]['id']))
    await page.key('ArrowUp', code='ArrowUp')
    check('↑: the second', (await state(page))['active'], s2['opts'][1]['id'])
    await page.key('ArrowUp', code='ArrowUp')
    await page.key('ArrowUp', code='ArrowUp')
    check('↑ from the first: the last', (await state(page))['active'], s2['opts'][n - 1]['id'])
    await page.key('ArrowDown', code='ArrowDown')
    check('↓ from the last: the first', (await state(page))['active'], s2['opts'][0]['id'])
    s = await search(page, 'keyboard')
    i, o = find(s, lambda o: o['label'] == 'Keyboard')
    check('"keyboard": the Help tab\'s Keyboard section first', i, 0)
    await page.key('Enter', code='Enter')
    await asyncio.sleep(0.4)
    check('... Enter goes there', await page.ev("SM.app.activeTab.kind + ' ' + Math.round(document.getElementById('help-keyboard').getBoundingClientRect().top - SM.app.helpView.getBoundingClientRect().top)"), 'help 0')

    # nothing found
    s = await search(page, 'zzqqxx')
    check('nothing found: no results, and it says so', (s['opts'], s['expanded'], 'No command, red-triangle item or help text matches “zzqqxx”' in s['extra']), ([], 'false', True))
    await click(page, f"[...{DIALOG}.querySelectorAll('.sm-search-none button')].find(b => b.textContent === 'Open the Help tab')")
    await asyncio.sleep(0.3)
    check('... its Open the Help tab button', ((await state(page))['open'], await page.ev('SM.app.activeTab.kind')), (False, 'help'))

    # recent searches
    s = await search(page, '')
    rec = await page.ev("JSON.parse(localStorage.getItem('smui.search.recent') || '[]')")
    check('recent searches (chosen ones) are kept in this browser, the last first', rec[:3], ['keyboard', 'row states', 'column switcher'])
    chips = await page.ev(f"[...{DIALOG}.querySelectorAll('.sm-search-chips')].map(c => [...c.children].map(x => x.textContent))")
    check('... and shown with nothing typed, before the ones to try', (chips[0][:4] if chips else None, len(chips)), (['Recent', 'keyboard', 'row states', 'column switcher'], 2))
    await click(page, f"[...{DIALOG}.querySelectorAll('.sm-search-chip')].find(b => b.textContent === 'row states')")
    s = await state(page)
    check('... a click on one searches it again', (s['value'], any(o['label'] == 'Row states' for o in s['opts'])), ('row states', True))
    await close_search(page)

    # Escape closes it (real key)
    await search(page, 'stack')
    try:
        await asyncio.wait_for(page.key('Escape', code='Escape'), 20)
        await asyncio.sleep(0.3)
        check('Escape (a real key) closes the search', (await state(page))['open'], False)
    except asyncio.TimeoutError:
        check('Escape (a real key) closes the search', 'the key hung', False)
        await close_search(page)

    # ---- hostile column names ---------------------------------------------------------------------------------
    await page.ev("window.__pwned = 0")
    imgs = await page.ev("document.querySelectorAll('img').length")
    await page.ev(r'''(() => { const n = 30; const t = new SM.Table({ name: 'hostile <b>t</b>', columns: [
      { name: '<img src=x onerror=window.__pwned=1>', dataType: 'numeric', values: Array.from({ length: n }, (_, i) => 1 + i * 0.7 + (i % 5)) },
      { name: 'a ▸ b', dataType: 'numeric', values: Array.from({ length: n }, (_, i) => 2 + (i * 13) % 7 + i * 0.1) } ] });
      SM.app.addTable(t); })()''')
    rep = await page.ev(open_report_js('distribution', {'y': ['<img src=x onerror=window.__pwned=1>', 'a ▸ b']}))
    s = await search(page, 'johnson su')
    # the report in front's (the other open reports have columns of their own)
    paths = [o['path'] for o in s['opts'] if o['kind'] == 'live' and o['badge'] == 'Report in front']
    check('hostile column names: the report\'s own items list each column as one level of its path',
          paths, [['Distributions', '<img src=x onerror=window.__pwned=1>', 'Continuous Fit'], ['Distributions', 'a ▸ b', 'Continuous Fit']])
    check('... made into no element: no image in the search, none new in the page, nothing run',
          (await page.ev(f"{DIALOG}.querySelectorAll('img, b').length"), await page.ev("document.querySelectorAll('img').length"), await page.ev('window.__pwned')), (0, imgs, 0))
    i, o = find(s, lambda o: o['kind'] == 'live' and o['path'][1] == 'a ▸ b')
    await click_option(page, i)
    await until_drawn(page, 120)
    fits = await wait_for(page, '''(() => { const rep = SM.app.activeTab.report; const id = rep.table.col('a ▸ b').id; const f = rep.spec.options[id + '|fits'] || [];
      return f.includes('johnsonsu') ? f : null; })()''', 60)
    check('... the item of the column "a ▸ b" goes to that column', fits, ['johnsonsu'])
    s = await search(page, 'johnson su')
    i, o = find(s, lambda o: o['kind'] == 'triangle')
    await click_option(page, i)
    await until_drawn(page, 120)
    await asyncio.sleep(0.3)
    toast = await page.ev(TOAST)
    check('... the ‹column› item goes to the first column, named as text in the message', ('for <img src=x onerror=window.__pwned=1>, the first of 2' in toast, await page.ev("document.querySelectorAll('.sm-toast img, .sm-toast b').length")), (True, 0))
    check('... and still nothing run, no new image', (await page.ev('window.__pwned'), await page.ev("document.querySelectorAll('img').length")), (0, imgs))
    await close_search(page)
    check('no script errors', page.errors, [])
    await page.close()

    # ---- dark theme ------------------------------------------------------------------------------------------------
    page = await open_page(f'{BASE}/smui.html?example=students', dark=True)
    for _ in range(200):
        if await page.ev('!!(window.SM && SM.app && SM.app.started && SM.search)'):
            break
        await asyncio.sleep(0.2)
    s = await search(page, 'normal quantile plot')
    col = await page.ev(r'''(() => { const d = document.querySelector('.sm-search-dialog'), o = d.querySelector('[role=option][aria-selected=true]'), o2 = d.querySelectorAll('[role=option]')[1];
      const cs = (e) => getComputedStyle(e);
      return { theme: document.documentElement.dataset.theme, bg: cs(d).backgroundColor, sel: cs(o).backgroundColor, label: cs(o.querySelector('.sm-search-label')).color,
               path: cs(o.querySelector('.sm-search-path')).color, under: cs(o.querySelector('.sm-search-snip, .sm-search-why')).color, under2: cs(o2.querySelector('.sm-search-snip, .sm-search-why')).color,
               mark: cs(o.querySelector('mark')).textDecorationColor, markBg: cs(o.querySelector('mark')).backgroundColor, input: cs(d.querySelector('.sm-search-input')).color, field: cs(d.querySelector('.sm-search-field')).backgroundColor }; })()''')
    check('dark theme: the dialog in the dark theme\'s surface colour', (col['theme'], col['bg']), ('dark', 'rgb(51, 43, 35)'))
    bg, sel = rgb_of(col['bg']), rgb_of(col['sel'])
    check('... the selected row\'s label, path and help line readable (contrast ≥ 7, 4.5, 4.5)',
          (contrast(rgb_of(col['label']), sel) >= 7, contrast(rgb_of(col['path']), sel) >= 4.5, contrast(rgb_of(col['under']), sel) >= 4.5), (True, True, True))
    check('... another row\'s help line on the dialog too (≥ 4.5)', contrast(rgb_of(col['under2']), bg) >= 4.5, True)
    check('... the words found underlined in the accent, no background', (col['mark'] != col['label'], col['markBg']), (True, 'rgba(0, 0, 0, 0)'))
    check('... the field\'s text readable on the field (≥ 7)', contrast(rgb_of(col['input']), rgb_of(col['field'])) >= 7, True)
    await shot(page, 'search-03-dark.png')
    await close_search(page)

    # ---- a phone ------------------------------------------------------------------------------------------------------
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 844, 'deviceScaleFactor': 2, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.6)
    b = await page.ev('''(() => { const b = document.querySelector('.sm-searchbtn'), r = b.getBoundingClientRect();
      return { right: r.right <= innerWidth + 0.5, w: Math.round(r.width), text: getComputedStyle(b.querySelector('.sm-searchbtn-text')).display, wide: document.documentElement.scrollWidth <= innerWidth + 1 }; })()''')
    check('phone: the button a magnifier only, in sight at the right', (b['right'], b['text'], b['w'] <= 40, b['wide']), (True, 'none', True, True))
    s = await search(page, 'normal quantile plot')
    ph = await page.ev(r'''(() => { const d = document.querySelector('.sm-search-dialog'), r = d.getBoundingClientRect(), l = d.querySelector('.sm-search-list');
      const opts = [...d.querySelectorAll('[role=option]')];
      return { box: [r.left, r.top, r.width, r.height].map(Math.round), inner: [innerWidth, innerHeight], font: parseFloat(getComputedStyle(d.querySelector('.sm-search-input')).fontSize),
               wide: document.documentElement.scrollWidth <= innerWidth + 1, dlgWide: d.scrollWidth <= d.clientWidth + 1, fits: opts.every(o => o.getBoundingClientRect().right <= innerWidth + 0.5),
               listFits: l.getBoundingClientRect().bottom <= innerHeight + 0.5, n: opts.length }; })()''')
    check('... the dialog is the whole screen', ph['box'], [0, 0, 390, 844])
    check('... its field 16 px or more (no zoom on iOS)', ph['font'] >= 16, True)
    check('... nothing wider than the screen: the page, the dialog, every result', (ph['wide'], ph['dlgWide'], ph['fits'], ph['n'] >= 3), (True, True, True, True))
    check('... the results inside the screen (they scroll there)', ph['listFits'], True)
    await shot(page, 'search-04-phone.png')
    await close_search(page)
    check('no script errors (dark, phone)', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
