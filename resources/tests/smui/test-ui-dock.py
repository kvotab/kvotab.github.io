#!/usr/bin/env python3
"""smui.html in a real browser: the work area's tab groups (smui-dock.js).

A tab dragged with the mouse onto a group's edge makes a new group on that
side, and onto a tab strip goes into that group where it is let go (which
orders a strip); a group left without tabs goes, and a split left with one
part becomes that part. The box and the bar that show where a tab would
go; the arrow keys stay in a strip and ctrl+shift+arrow moves a tab; the
context menu's Split, Move to Group and Join All Groups; the bar between
two parts (dragged, held to a smallest size, a double click, the arrow
keys); new tabs open in the group in use, before its Help tab; closing
tabs; the Help text stays in the page; scroll positions are kept when
views move; a saved project keeps its groups, and an older one without
them opens as before; the page's print shows the group in use; a tab let
go over a text field does not type its name there; at phone width the
groups stack, no new ones are made, and a tab moves by touch.

Start a server on the repository root and headless Chrome (the recipe is in
../rb/README.md) on SMUI_HTTP_PORT and SMUI_CDP_PORT (defaults 8791, 9291),
then

    python3 resources/tests/smui/test-ui-dock.py

Exit status 0 when every check passes.
"""
import asyncio
import json
import sys

from cdp import BASE, Checks, open_page, wait_engine

check = Checks()

# the groups as nested lists of tabs: {"row": [[...], {"col": ...}]}, a tab
# by the key the test gave it (reports share a title), or its title
SHAPE = '''(() => { const shape = (n) => n.tabs ? n.tabs.map(t => t.__key || t.title) : { [n.dir]: n.children.map(shape) }; return shape(SM.app.dock.root); })()'''
TITLES = '''(() => { const shape = (n) => n.tabs ? n.tabs.map(t => t.title) : { [n.dir]: n.children.map(shape) }; return shape(SM.app.dock.root); })()'''
TAB = "__t({0})"
HELPERS = r'''
window.__t = (key) => SM.app.tabs.find(t => (t.__key || t.title) === key);
window.__k = (t) => t && (t.__key || t.title);
window.__g = (title) => __t(title).group;
// a drag made in the page (a DataTransfer of its own): over a point of an element
window.__over = (title, x, y) => {
  const tab = __t(title);
  if (!window.__dt || window.__dtTab !== tab) {
    window.__dt = new DataTransfer(); window.__dtTab = tab;
    tab.btn.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: __dt }));
  }
  const at = document.elementFromPoint(x, y);
  const ev = new DragEvent('dragover', { bubbles: true, cancelable: true, clientX: x, clientY: y, dataTransfer: __dt });
  at.dispatchEvent(ev);
  const zones = SM.app.dock.groups.map(g => g.overlay.hidden ? null : g.overlay.className.replace('sm-dropzone ', ''));
  const key = (b) => { const t = SM.app.tabs.find(x => x.btn === b); return t.__key || t.title; };
  const marks = [...document.querySelectorAll('.sm-tab.drop-before, .sm-tab.drop-after')].map(b => (b.classList.contains('drop-before') ? 'before ' : 'after ') + key(b));
  return { prevented: ev.defaultPrevented, zones, marks, dragging: document.querySelector('.sm-main').classList.contains('is-dragging-tab') };
};
window.__end = () => { if (window.__dtTab) window.__dtTab.btn.dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: __dt })); window.__dt = null; window.__dtTab = null; };
// the box in a view that scrolls
window.__scroller = (v) => [v, ...v.querySelectorAll('*')].find(e => /auto|scroll/.test(getComputedStyle(e).overflowY) && e.scrollHeight > e.clientHeight + 20);
'''


async def main():
    page = await open_page(f'{BASE}/smui.html?example=students')
    check('the engine starts', await wait_engine(page), 'ready')
    await page.ev(HELPERS)

    async def shape():
        return await page.ev(SHAPE)

    async def rect(js):
        return await page.ev(f'(() => {{ const r = ({js}).getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; }})()')

    async def mid(js):
        x, y, w, h = await rect(js)
        return x + w / 2, y + h / 2

    async def drag(src_js, x1, y1):
        x0, y0 = await mid(src_js)
        ok = await page.drag_to(x0, y0, x1, y1)
        await asyncio.sleep(0.25)
        return ok

    async def report(cols, key):
        await page.ev(f'''(async () => {{ const t = SM.app.tables[0];
          const rep = SM.app.openReport(SM.platforms.get('distribution'), {{ roles: {{ y: {json.dumps(cols)}.map(n => t.col(n).id) }}, options: {{}} }}, t);
          SM.app.tabOf(rep).__key = {json.dumps(key)};
          await new Promise(res => rep.on('done', res)); }})()''', timeout=200)
        return key

    # ---- one group to start with, as the page was before there were groups
    r = await page.ev('''(() => { const m = document.querySelector('.sm-main'), s = m.querySelector('.sm-tabs');
      return { kids: [...m.children].map(e => e.className + (e.hidden ? ' [hidden]' : '')), tabs: SM.app.tabs.map(t => t.title),
        role: s.getAttribute('role'), label: s.getAttribute('aria-label'), drag: SM.app.tabs.map(t => t.btn.getAttribute('draggable')),
        help: !!SM.app.helpView && SM.app.helpView.closest('.sm-shelf') !== null && SM.app.helpView.hidden }; })()''')
    check('one group at the start, and a hidden shelf', r['kids'], ['sm-group is-focused', 'sm-shelf [hidden]'])
    check('its strip is the tab list it was', (r['role'], r['label'], r['tabs']), ('tablist', 'Tables and reports', ['Home', 'Students']))
    check('tabs can be dragged', r['drag'], ['true', 'true'])
    check('the Help text waits on the shelf, hidden', r['help'], True)

    title = await report(['height (cm)', 'weight (kg)', 'age'], 'D1')
    check('a report opens in the group', await shape(), ['Home', 'Students', title])

    # ---- where a tab would go, while it is dragged
    x, y, w, h = await rect('SM.app.dock.groups[0].views')
    zones = {}
    for name, (fx, fy) in {'left': (0.05, 0.5), 'right': (0.95, 0.5), 'top': (0.5, 0.05), 'bottom': (0.5, 0.95), 'middle': (0.5, 0.5)}.items():
        zones[name] = await page.ev(f'__over("Students", {x + fx * w}, {y + fy * h})')
    await page.ev('__end()')
    check('over an edge of its group: a new group there', [zones[k]['zones'][0] for k in ('left', 'right', 'top', 'bottom')], ['is-left', 'is-right', 'is-top', 'is-bottom'])
    check('and the drop is taken', [zones[k]['prevented'] for k in ('left', 'right', 'top', 'bottom')], [True] * 4)
    check('over the middle of its own group: nowhere to go', (zones['middle']['zones'][0], zones['middle']['prevented']), (None, False))
    check('the work area knows a tab is dragged', zones['left']['dragging'], True)
    sx, sy = await mid(TAB.format('"Students"') + '.btn')
    r1 = await page.ev(f'__over("Home", {sx - 10}, {sy})')
    lx, ly, lw, lh = await rect(TAB.format(json.dumps(title)) + '.btn')
    r2 = await page.ev(f'__over("Home", {lx + lw - 3}, {ly + lh / 2})')
    await page.ev('__end()')
    check('over a strip: a bar before the tab it would go before', (r1['marks'], r1['prevented']), (['before Students'], True))
    check('or after the last tab', r2['marks'], [f'after {title}'])
    r = await page.ev('''({ zones: SM.app.dock.groups.map(g => g.overlay.hidden), marks: document.querySelectorAll('.drop-before, .drop-after').length, cls: document.querySelector('.sm-main').classList.contains('is-dragging-tab') })''')
    check('the drag over: no box, no bar', (r['zones'], r['marks'], r['cls']), ([True], 0, False))
    # a tab's drag is not a column's: the places that take columns stay unmarked
    r = await page.ev('''(() => { const z = document.createElement('div'); z.className = 'smt-zone'; SM.app.dock.groups[0].views.append(z);
      document.documentElement.classList.add('sm-dragging'); const m = document.querySelector('.sm-main');
      const col = getComputedStyle(z).outlineStyle; m.classList.add('is-dragging-tab'); const tab = getComputedStyle(z).outlineStyle;
      m.classList.remove('is-dragging-tab'); document.documentElement.classList.remove('sm-dragging'); z.remove(); return [col, tab]; })()''')
    check('a column\'s drag marks the places that take it, a tab\'s does not', r, ['dashed', 'none'])

    # ---- scrolled, then moved to a new group on the right: still where it was scrolled to
    await page.ev(f'SM.app.showTab({TAB.format(json.dumps(title))})')
    await asyncio.sleep(0.4)
    top0 = await page.ev(f'(() => {{ const s = __scroller({TAB.format(json.dumps(title))}.view); s.scrollTop = 400; return s.scrollTop; }})()')
    x, y, w, h = await rect('SM.app.dock.groups[0].views')
    check('dragged to the right edge of its group', await drag(TAB.format(json.dumps(title)) + '.btn', x + w - 20, y + h / 2), True)
    check('it is in a new group on the right', await shape(), {'row': [['Home', 'Students'], [title]]})
    r = await page.ev(f'''(() => {{ const d = SM.app.dock, [a, b] = d.groups, t = {TAB.format(json.dumps(title))};
      return {{ sizes: d.root.sizes, w: [a.el.getBoundingClientRect().width, b.el.getBoundingClientRect().width], focused: d.groups.map(g => g.el.classList.contains('is-focused')),
        shown: d.groups.map(g => __k(g.active)), front: __k(SM.app.activeTab), current: SM.app.current.name, top: __scroller(t.view).scrollTop,
        labels: d.groups.map(g => g.strip.getAttribute('aria-label')), visible: d.groups.map(g => [...g.views.children].filter(v => v.classList.contains('sm-view') && !v.hidden).length) }}; }})()''')
    check('the two groups share the room', (r['sizes'], abs(r['w'][0] - r['w'][1]) < 2), ([0.5, 0.5], True))
    check('the moved tab is in front, in the group in use', (r['front'], r['focused']), (title, [False, True]))
    check('the group it left shows the tab beside it', r['shown'], ['Students', title])
    check('each group shows one view', r['visible'], [1, 1])
    check('the current table is the report\'s', r['current'], 'Students')
    check('the strips are told apart', r['labels'], ['Tables and reports', 'Tables and reports, group 2'])
    check('the moved report is still scrolled to where it was', abs(r['top'] - top0) <= 1 and top0 > 300, True)

    # ---- the table below the report: a split of the other way
    x, y, w, h = await rect('SM.app.dock.groups[1].views')
    check('Students dragged to the bottom of the report\'s group', await drag(TAB.format('"Students"') + '.btn', x + w / 2, y + h - 15), True)
    check('a column split in the report\'s place', await shape(), {'row': [['Home'], {'col': [[title], ['Students']]}]})
    # a click in a group makes it the one in use, and the app follows its tab
    x, y, w, h = await rect('SM.app.dock.groups[0].strip')
    await page.click(x + w - 12, y + h / 2)
    r = await page.ev('({ front: __k(SM.app.activeTab), focused: SM.app.dock.groups.map(g => g.el.classList.contains("is-focused")), title: document.title.split(" — ")[0] })')
    check('a click in a group makes it the one in use', (r['front'], r['focused']), ('Home', [True, False, False]))
    # Home, alone in its group, onto the table's strip: its group goes
    sx, sy, sw, sh = await rect(TAB.format('"Students"') + '.btn')
    check('Home dragged onto the table\'s strip, before it', await drag('SM.app.homeTab.btn', sx + 4, sy + sh / 2), True)
    r = await page.ev(f'''({{ shape: {SHAPE}, groups: SM.app.dock.groups.length, kids: [...document.querySelector('.sm-main').children].map(e => e.className.split(' ')[0]),
      focused: SM.app.dock.groups.map(g => g.el.classList.contains('is-focused')), front: __k(SM.app.activeTab) }})''')
    check('the group left empty goes, the split with one part too', r['shape'], {'col': [[title], ['Home', 'Students']]})
    check('the split is the work area\'s own now', r['kids'], ['sm-split', 'sm-shelf'])
    check('Home is in front, in the group in use', (r['front'], r['focused']), ('Home', [False, True]))
    # along its own strip: the order changes
    hx, hy, hw, hh = await rect('SM.app.homeTab.btn')
    check('Students dragged before Home, on their strip', await drag(TAB.format('"Students"') + '.btn', hx + 3, hy + hh / 2), True)
    check('the strip is in the new order', await shape(), {'col': [[title], ['Students', 'Home']]})
    # onto its own group's middle: nothing happens
    x, y, w, h = await rect('SM.app.dock.groups[1].views')
    await drag(TAB.format('"Students"') + '.btn', x + w / 2, y + h / 2)
    check('onto the middle of its own group: nothing changes', await shape(), {'col': [[title], ['Students', 'Home']]})

    # ---- the keyboard: the arrows stay in a strip; ctrl+shift+arrow moves a tab
    await page.ev('SM.app.showTab(__t("Students")); __t("Students").btn.focus()')
    await page.key('ArrowRight')
    a = await page.ev('document.activeElement.textContent')
    await page.key('ArrowRight')
    b = await page.ev('document.activeElement.textContent')
    check('ArrowRight goes along the strip and comes round, not into the other group', (a, b), ('Home', 'Students×'))
    await page.key('ArrowRight', modifiers=2 | 8)       # ctrl+shift
    r = await page.ev(f'({{ shape: {SHAPE}, focus: document.activeElement.textContent }})')
    check('ctrl+shift+ArrowRight moves the tab right, and it keeps the focus', (r['shape'], r['focus']), ({'col': [[title], ['Home', 'Students']]}, 'Students×'))
    await page.key('ArrowLeft', modifiers=2 | 8)
    check('ctrl+shift+ArrowLeft moves it back', await shape(), {'col': [[title], ['Students', 'Home']]})

    # ---- the context menu
    async def menu_of(js):
        x, y = await mid(js)
        await page.mouse('mouseMoved', x, y)
        await page.mouse('mousePressed', x, y, button='right')
        await page.mouse('mouseReleased', x, y, button='right')
        await asyncio.sleep(0.15)
        return await page.ev('''[...document.querySelectorAll('.sm-menu')].map(m => [...m.querySelectorAll('button, hr')].map(b => b.tagName === 'HR' ? '---' : b.querySelector('.sm-label').textContent + (b.disabled ? ' (off)' : '')))''')

    async def pick(label, level=0):
        x, y = await mid(f'''[...[...document.querySelectorAll('.sm-menu')][{level}].querySelectorAll('button')].find(b => b.querySelector('.sm-label').textContent === {json.dumps(label)})''')
        await page.mouse('mouseMoved', x, y)
        await asyncio.sleep(0.1)
        await page.click(x, y)
        await asyncio.sleep(0.25)

    m = await menu_of(TAB.format(json.dumps(title)) + '.btn')
    check('a report tab\'s menu: its own items, then the groups\'', m[0][-4:], ['---', 'Split (off)', 'Move to Group', 'Join All Groups'])
    why = await page.ev('''[...document.querySelector('.sm-menu').querySelectorAll('button')].find(b => b.querySelector('.sm-label').textContent === 'Split').getAttribute('aria-description')''')
    check('Split is off for the only tab of a group, and says why', why, 'The only tab of its group: drag another tab beside it instead')
    await pick('Move to Group')
    sub = await page.ev('''[...document.querySelectorAll('.sm-menu')][1] ? [...[...document.querySelectorAll('.sm-menu')][1].querySelectorAll('button')].map(b => b.querySelector('.sm-label').textContent + (b.disabled ? ' (off)' : '')) : null''')
    dtitle = await page.ev(f'__t({json.dumps(title)}).title')
    check('Move to Group names the groups by what they show', sub, [f'Group 1 ({dtitle}) (off)', 'Group 2 (Students)'])
    await pick('Group 2 (Students)', 1)
    r = await page.ev(f'({{ shape: {SHAPE}, front: __k(SM.app.activeTab) }})')
    check('Move to Group moves it, and its group goes', r, {'shape': ['Students', 'Home', title], 'front': title})
    m = await menu_of(TAB.format('"Students"') + '.btn')
    check('a table tab\'s menu ends with Split alone when there is one group', m[0][-2:], ['---', 'Split'])
    await pick('Split')
    await pick('Down', 1)
    check('Split > Down puts the tab in a new group below', await shape(), {'col': [['Home', title], ['Students']]})
    m = await menu_of('SM.app.homeTab.btn')
    check('Home\'s menu: the groups\' items only', m[0], ['Split', 'Move to Group', 'Join All Groups'])
    await pick('Join All Groups')
    r = await page.ev(f'({{ shape: {SHAPE}, front: __k(SM.app.activeTab) }})')
    # (the right click made Home's group the one in use, so its report is in front)
    check('Join All Groups: one group, the tab in front still in front', r, {'shape': ['Home', title, 'Students'], 'front': title})

    # ---- the bar between two parts
    await page.ev(f'SM.app.dock.split(__t("Students"), __g("Students"), "bottom")')
    await asyncio.sleep(0.2)
    heights = '(() => SM.app.dock.groups.map(g => Math.round(g.el.getBoundingClientRect().height)))()'
    h0 = await page.ev(heights)
    sx, sy = await mid('document.querySelector(".sm-sash")')
    await page.mouse('mouseMoved', sx, sy)
    await page.mouse('mousePressed', sx, sy)
    for k in range(1, 6):
        await page.mouse('mouseMoved', sx, sy + 20 * k)
        await asyncio.sleep(0.03)
    moving = await page.ev('[document.querySelector(".sm-sash").classList.contains("is-moving"), document.querySelector(".sm-main").classList.contains("is-resizing")]')
    await page.mouse('mouseReleased', sx, sy + 100)
    await asyncio.sleep(0.1)
    h1 = await page.ev(heights)
    check('while the bar is dragged it and the work area say so', moving, [True, True])
    check('dragging the bar down 100 px moves the room between the two', (abs(h1[0] - h0[0] - 100) <= 2, abs(h1[1] - h0[1] + 100) <= 2), (True, True))
    sx, sy = await mid('document.querySelector(".sm-sash")')
    await page.mouse('mouseMoved', sx, sy)
    await page.mouse('mousePressed', sx, sy)
    await page.mouse('mouseMoved', sx, sy + 2000)
    await page.mouse('mouseReleased', sx, sy + 2000)
    await asyncio.sleep(0.1)
    h2 = await page.ev(heights)
    check('the bar keeps the other part 150 px tall at least', 149 <= h2[1] <= 152, True)
    sx, sy = await mid('document.querySelector(".sm-sash")')
    await page.mouse('mouseMoved', sx, sy)
    await page.mouse('mousePressed', sx, sy, clicks=1)
    await page.mouse('mouseReleased', sx, sy, clicks=1)
    await page.mouse('mousePressed', sx, sy, clicks=2)
    await page.mouse('mouseReleased', sx, sy, clicks=2)
    await asyncio.sleep(0.1)
    h3 = await page.ev(heights)
    check('a double click makes the two parts equal', abs(h3[0] - h3[1]) <= 2, True)
    await page.ev('document.querySelector(".sm-sash").focus()')
    await page.key('ArrowDown')
    h4 = await page.ev(heights)
    check('ArrowDown on the bar: 32 px down', abs(h4[0] - h3[0] - 32) <= 2, True)
    r = await page.ev('(() => { const s = document.querySelector(".sm-sash"); return [s.getAttribute("role"), s.getAttribute("aria-orientation"), s.tabIndex]; })()')
    check('the bar is a separator that takes the focus', r, ['separator', 'horizontal', 0])

    # ---- new tabs open in the group in use, before its Help tab
    gx, gy = await mid('SM.app.dock.groups[1].views')
    await page.click(gx, gy)
    t2 = await report(['age'], 'D2')
    check('a new report opens in the group in use', await shape(), {'col': [['Home', title], ['Students', t2]]})
    await page.ev('SM.app.showHelp()')
    t3 = await report(['weight (kg)'], 'D3')
    r = await page.ev(f'({{ shape: {SHAPE}, shelf: SM.app.helpView.closest(".sm-shelf") !== null }})')
    check('Help opens there, and a report after it goes before it', r['shape'], {'col': [['Home', title], ['Students', t2, t3, 'Help']]})
    await page.ev('SM.app.closeTab(SM.app.helpTab)')
    r = await page.ev('({ shelf: SM.app.helpView.closest(".sm-shelf") !== null, hidden: SM.app.helpView.hidden, inPage: !!document.querySelector(".sm-shelf [id^=help-]"), front: __k(SM.app.activeTab) })')
    check('closed, the Help text goes back to the shelf, hidden, its anchors in the page', (r['shelf'], r['hidden'], r['inPage']), (True, True, True))
    check('and the report stays in front', r['front'], t3)

    # ---- closing tabs: the group shows the tab beside; the last one closed, the group goes
    await page.ev(f'SM.app.showTab(__t({json.dumps(t2)})); SM.app.closeReport(__t({json.dumps(t2)}).report)')
    r = await page.ev('({ shown: __k(SM.app.dock.groups[1].active), front: __k(SM.app.activeTab) })')
    check('closing the tab in front shows the one after it', r, {'shown': t3, 'front': t3})
    await page.ev(f'SM.app.closeReport(__t({json.dumps(t3)}).report); SM.app.showTab(__t("Students"))')
    await page.ev('SM.app.dock.move(__t("Students"), SM.app.dock.groups[0])')
    r = await page.ev(f'({{ shape: {SHAPE}, focused: SM.app.dock.groups.map(g => g.el.classList.contains("is-focused")) }})')
    check('the last tab of a group moved away: the group goes, the other is in use', r, {'shape': ['Home', title, 'Students'], 'focused': [True]})
    await page.ev(f'SM.app.dock.split(__t({json.dumps(title)}), __g({json.dumps(title)}), "left"); SM.app.closeReport(__t({json.dumps(title)}).report)')
    r = await page.ev(f'({{ shape: {SHAPE}, front: __k(SM.app.activeTab), focused: SM.app.dock.groups.map(g => g.el.classList.contains("is-focused")) }})')
    check('the last tab of a group closed: the group goes and the other is in front', r, {'shape': ['Home', 'Students'], 'front': 'Students', 'focused': [True]})

    # ---- a hidden view whose group moves in the page keeps its place too
    await page.ev('SM.app.showTab(SM.app.homeTab)')
    await asyncio.sleep(0.2)
    y0 = await page.ev('(() => { const s = __scroller(SM.app.homeTab.view); if (!s) return null; s.scrollTop = 150; return s.scrollTop; })()')
    await page.ev('SM.app.showTab(__t("Students"))')
    t4 = await report(['height (cm)'], 'D4')
    # Home's group (the work area's only one) moves into a new split, below which the report goes
    await page.ev(f'SM.app.dock.split(__t({json.dumps(t4)}), __g({json.dumps(t4)}), "bottom")')
    moved = await page.ev(f'({{ shape: {SHAPE}, inSplit: SM.app.homeTab.group.el.parentElement.classList.contains("sm-split") }})')
    await page.ev('SM.app.showTab(SM.app.homeTab)')
    y1 = await page.ev('__scroller(SM.app.homeTab.view).scrollTop')
    check('Home\'s group moved into a new split while Home was hidden', moved, {'shape': {'col': [['Home', 'Students'], [t4]]}, 'inSplit': True})
    check('shown again, Home is scrolled where it was', (y0, abs(y1 - y0) <= 1), (150, True))

    # ---- a text field under a tab let go does not take its name: over a
    # field in its own group's middle (where it goes nowhere), over the
    # notebook's cell near the top (a new group above), and over the field
    # in the middle of another group (into it)
    await page.ev('SM.notebook.open(SM.app)')
    await asyncio.sleep(0.5)
    nb = await page.ev('SM.app.activeTab.title')
    await page.ev('SM.app.dock.join()')
    await page.ev(f'''(() => {{ const ta = document.createElement('textarea'); ta.id = '__ta';
      ta.style.cssText = 'position:absolute;left:40%;top:45%;width:20%;height:10%;z-index:3'; __t({json.dumps(nb)}).view.append(ta); }})()''')
    texts = f'[document.getElementById("__ta").value, __t({json.dumps(nb)}).view.querySelector(".sm-nb-cell textarea, textarea:not(#__ta)").value]'
    before = await page.ev(texts)
    x, y = await mid('document.getElementById("__ta")')
    await drag(TAB.format('"Students"') + '.btn', x, y)
    r = await page.ev(f'({{ shape: {SHAPE}, text: {texts} }})')
    check('over a field in the middle of its own group: nothing moves, nothing is typed', r, {'shape': ['Home', 'Students', nb, t4], 'text': before})
    x, y = await mid(f'__t({json.dumps(nb)}).view.querySelector(".sm-nb-cell textarea, textarea:not(#__ta)")')
    await drag(TAB.format('"Students"') + '.btn', x, y)
    r = await page.ev(f'({{ shape: {SHAPE}, text: {texts} }})')
    check('over the cell near the top: a new group above, nothing typed', r, {'shape': {'col': [['Students'], ['Home', nb, t4]]}, 'text': before})
    x, y = await mid('document.getElementById("__ta")')
    await drag(TAB.format('"Students"') + '.btn', x, y)
    r = await page.ev(f'({{ shape: {SHAPE}, text: {texts} }})')
    check('over the field in the middle of another group: into it, its own group gone, nothing typed', r, {'shape': ['Home', nb, t4, 'Students'], 'text': before})
    await page.ev('document.getElementById("__ta").remove()')
    await page.ev(f'SM.app.showTab(__t({json.dumps(nb)})); SM.app.dock.split(__t({json.dumps(nb)}), __g({json.dumps(nb)}), "right")')
    check('the notebook split off to the right', await shape(), {'row': [['Home', t4, 'Students'], [nb]]})

    # ---- the page's print: the group in use only
    await page.ev(f'SM.app.showTab(__t({json.dumps(t4)}))')
    await page.call('Emulation.setEmulatedMedia', {'media': 'print'}, session=page.sid)
    await asyncio.sleep(0.2)
    r = await page.ev('''SM.app.dock.groups.map(g => getComputedStyle(g.el).display)''')
    await page.call('Emulation.setEmulatedMedia', {'media': ''}, session=page.sid)
    check('printed, the page shows the group in use only', r, ['block', 'none'])

    # ---- a saved project keeps its groups
    await page.ev('SM.app.showTab(__t("Students"))')
    saved = await page.ev('''(async () => { let blob = null; const url = URL.createObjectURL, click = HTMLAnchorElement.prototype.click;
      URL.createObjectURL = (b) => { blob = b; return 'blob:none'; }; HTMLAnchorElement.prototype.click = function () {};
      try { SM.app.saveProject(); } finally { URL.createObjectURL = url; HTMLAnchorElement.prototype.click = click; }
      return JSON.parse(await blob.text()); })()''')
    check('the project file has the layout', saved.get('layout'), {'root': {'split': 'row', 'sizes': [0.5, 0.5], 'parts': [{'tabs': ['home', 'report:0', 'table:0'], 'shown': 'table:0'}, {'tabs': ['notebook:0'], 'shown': 'notebook:0'}]}, 'active': 0})
    titles = await page.ev(TITLES)
    sv = json.dumps(saved)
    check('no script errors', page.errors, [])
    await page.close()

    page = await open_page(f'{BASE}/smui.html')
    await wait_engine(page)
    await page.ev(HELPERS)
    r = await page.ev(f'''(async () => {{ SM.app.loadProject({sv}); await new Promise(res => setTimeout(res, 800));
      return {{ shape: {TITLES}, shown: SM.app.dock.groups.map(g => g.active.title), front: SM.app.activeTab.title, focused: SM.app.dock.groups.map(g => g.el.classList.contains('is-focused')) }}; }})()''', timeout=200)
    check('opened, the project\'s tabs are in their groups again', r['shape'], titles)
    check('each group shows what it showed, the one in use in front', (r['shown'], r['front'], r['focused']), (['Students', nb], 'Students', [True, False]))
    old = dict(saved)
    old.pop('layout')
    r = await page.ev(f'''(async () => {{ SM.app.dock.join(); const n = SM.app.tabs.length; SM.app.loadProject({json.dumps(old)}); await new Promise(res => setTimeout(res, 800));
      return {{ groups: SM.app.dock.groups.length, added: SM.app.tabs.length - n, front: SM.app.activeTab.kind }}; }})()''', timeout=200)
    check('a project without a layout opens into the group in use, a table in front', r, {'groups': 1, 'added': 3, 'front': 'table'})
    check('no script errors (the project)', page.errors, [])
    await page.close()

    # ---- phone width: the groups stack; no new groups; a tab moves by touch
    page = await open_page(f'{BASE}/smui.html?example=students')
    await wait_engine(page)
    await page.ev(HELPERS)
    title = await report(['height (cm)'], 'D')
    await page.ev(f'SM.app.dock.split(__t({json.dumps(title)}), __g({json.dumps(title)}), "right")')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 820, 'deviceScaleFactor': 2, 'mobile': True}, session=page.sid)
    await page.call('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 1}, session=page.sid)
    await asyncio.sleep(0.4)
    r = await page.ev('''(() => { const d = SM.app.dock, s = document.querySelector('.sm-sash'), [a, b] = d.groups.map(g => g.el.getBoundingClientRect());
      return { dir: getComputedStyle(d.root.el).flexDirection, below: b.top >= a.bottom - 1, sash: Math.round(s.getBoundingClientRect().height), wide: document.documentElement.scrollWidth <= innerWidth + 1 }; })()''')
    check('phone: the groups stack, a finger-high bar between them, nothing wider than the screen', r, {'dir': 'column', 'below': True, 'sash': 9, 'wide': True})
    r = await page.ev('''(() => { const tab = __t('Students'); const made = SM.app.dock.split(tab, tab.group, 'bottom'); const m = SM.app.dock.menuFor(tab)[0]; return { made, off: m.disabled, why: m.title }; })()''')
    check('phone: no new groups, and the menu says why', r, {'made': False, 'off': True, 'why': 'Not at phone width, where the groups stack'})
    x, y, w, h = await rect('SM.app.dock.groups[1].views')
    z = await page.ev(f'__over("Students", {x + 8}, {y + h / 2})')
    await page.ev('__end()')
    check('phone: over the edge of another group, the tab would go into it', z['zones'], [None, 'is-center'])
    # held a moment, then moved onto the other group's strip: it moves there

    async def touch(kind, pts):
        await page.call('Input.dispatchTouchEvent', {'type': kind, 'touchPoints': pts}, session=page.sid)
    x0, y0 = await mid('__t("Students").btn')
    sx, sy, sw, sh = await rect(f'__t({json.dumps(title)}).btn')
    await touch('touchStart', [{'x': x0, 'y': y0}])
    await asyncio.sleep(0.45)
    for k in range(1, 9):
        await touch('touchMove', [{'x': x0 + (sx + sw - 4 - x0) * k / 8, 'y': y0 + (sy + sh / 2 - y0) * k / 8}])
        await asyncio.sleep(0.03)
    await touch('touchEnd', [])
    await asyncio.sleep(0.4)
    check('phone: a tab held and moved onto the other strip goes there', await shape(), {'row': [['Home'], [title, 'Students']]})
    check('no script errors (phone)', page.errors, [])
    await page.close()
    sys.exit(check.done())


asyncio.run(main())
