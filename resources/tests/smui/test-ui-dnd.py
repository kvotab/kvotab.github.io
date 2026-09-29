#!/usr/bin/env python3
"""smui.html in a real browser: a column dragged out of the place it was
dropped on.

A column that has been dropped on a place (a launch dialog's role, Fit
Model's and Multiple Imputation's model effects, a Graph Builder zone, a
Tabulate zone) can be dragged again, with the mouse as a user drags it
(Chrome's drag interception hands the page's own drag data over) and by
touch (held, then moved). Checked, with what the page shows while the drag
is under way (the item dimmed, the place that takes it marked, the item it
would replace or the side it would land on, the places that refuse it
dimmed, and a label by the pointer where a drop takes it out) and after it:

  - a launch dialog (Distribution): a column moved from one role to
    another, reordered within a role (both ways), put in place of a column
    of another role, refused by a role that does not take its modeling type
    (no drop is shown, the dialog says why, and a drop there changes
    nothing), taken out by a drop on the column list and on the dialog's
    lead, left alone by a drag cancelled (Escape; letting go outside the
    window is the same end, a drag with no drop) and by one let go beside
    the dialog; a column from the list still goes in as before; a role's
    button takes a column as its list does (from another role or from the
    list); the report that follows has
    the roles the drags made (its outlines in the new order, the new Weight
    in its N);
  - Fit Model: the model effects reordered (both ways), an effect taken
    out by a drag onto the column list, a crossing refused by every role, a
    column moved from a role into the effects and a main effect moved from
    the effects onto a role; the fitted model has the effects in their new
    order;
  - Multiple Imputation: its effects reordered, one taken out, a main
    effect moved onto a role; the pooled model is the one the list shows;
  - Graph Builder: a column moved from one zone to another (one step of
    Undo), refused by a zone that does not take it, reordered within a
    zone, put in place of a column of another zone, taken out by a drop on
    the column list and on the graph, a cancelled drag, one let go outside
    the builder; the graph is drawn again each time from the zones the drag
    made (panels, axes, legend, and every point within its panel's range:
    two Y columns with Group X were drawn empty before, at [-1, 4]);
  - Tabulate: a column moved from the columns to the rows, reordered and
    nested within the rows, the analysis columns reordered, a column put
    in place of one in another zone, a continuous column refused by the
    rows, taken out by a drop on the column list and on the table, a
    cancelled drag; the table is computed again each time;
  - the (i) help of every place says that its columns can be dragged out;
  - on a phone (touch emulation): a column held and moved from one role to
    another, one taken out (the dragged item under the finger struck
    through, with the label above it), a touch cancelled mid-drag that
    leaves it, a Graph Builder column moved to another zone and a Tabulate
    column moved to another zone.

Start a server on the repository root and headless Chrome (the recipe is in
README.md) on SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-dnd.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import os
import sys

from cdp import BASE, Checks, open_page, table_under_js, wait_engine

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await page.shot(os.path.join(SHOTS, name))


# In the page: the dialog and its roles, where things are, and what the page
# shows while a drag is under way (marks()). A window listener, which runs
# after every handler of the page, keeps whether the last dragover was taken
# (a place that refuses shows no drop) and counts the drops.
HELPERS = r'''
window.D = {
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  dlg: () => [...document.querySelectorAll('.sm-dialog')].pop() || null,
  roleList: (label) => { const row = [...D.dlg().querySelectorAll('.sm-role')].find((x) => x.querySelector('.sm-btn').textContent === label); return row ? row.querySelector('.sm-role-list') : null; },
  names: (ul) => [...ul.querySelectorAll('li')].map((li) => li.textContent),
  roles: () => Object.fromEntries([...D.dlg().querySelectorAll('.sm-role')].filter((x) => !x.hidden).map((x) => [x.querySelector('.sm-btn').textContent, D.names(x.querySelector('.sm-role-list'))])),
  // (a click on the first: a press on a selected column keeps the others, so that they can be dragged together)
  pick(names) { const items = [...D.dlg().querySelectorAll('.sm-pick-list li')]; names.forEach((n, i) => { const li = items.find((x) => x.textContent === n); if (!li) throw new Error('no column ' + n); li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, metaKey: i > 0 })); if (!i) li.dispatchEvent(new MouseEvent('click', { bubbles: true })); }); },
  button(label, root) { const b = [...(root || D.dlg()).querySelectorAll('button')].find((x) => x.textContent === label); if (!b) throw new Error('no button ' + label); b.click(); },
  cast(names, label) { D.pick(names); D.button(label, D.dlg().querySelector('.sm-roles')); },
  item: (root, name) => [...root.querySelectorAll('li, .sm-gb-chip, .smt-chip')].find((e) => e.textContent.replace('×', '').trim() === name) || null,
  // the point at (dx, dy) of an element's box, the element scrolled into view
  at(e, dx = 0.5, dy = 0.5) { if (!e) return null; e.scrollIntoView({ block: 'nearest' }); const r = e.getBoundingClientRect(); return [r.x + r.width * dx, r.y + r.height * dy]; },
  moving: () => !!SM.launch.moving({ dataTransfer: { types: [SM.launch.PLACE] } }),
  marks() {
    const name = (e) => (e.matches('li, .sm-gb-chip, .smt-chip') ? e.textContent.replace('×', '').trim() : e.dataset.zone ? `zone:${e.dataset.zone}` : e.getAttribute('aria-label') || e.className);
    const of = (sel) => [...document.querySelectorAll(sel)].filter((e) => e.getClientRects().length).map(name);   // (a role the dialog hides is not on show)
    const b = document.querySelector('.sm-dropcue');
    const d = D.dlg(), m = d && d.querySelector('.sm-launch-msg');
    return { badge: b && !b.hidden ? b.textContent : null, touchBadge: !!(b && !b.hidden && b.classList.contains('is-touch')), removeRoot: document.documentElement.classList.contains('sm-drop-remove'),
      dragged: of('.sm-dragged'), removing: of('.sm-removing'), place: of('.sm-role-list.drop, .sm-gb-zone.is-drop, .smt-zone.drop'),
      before: of('.sm-drop-before'), after: of('.sm-drop-after'), replace: of('.sm-drop-replace'), refusing: of('.sm-refusing'),
      msg: m ? m.textContent : null, moving: D.moving(), taken: D.over.taken, drops: D.drops };
  },
  over: { taken: null }, drops: 0,
  // a drop from a column list, for setting a place up (the thing under test is the drag out of it)
  listDrop(target, ids) {
    const dt = new DataTransfer();
    dt.setData(SM.launch.MIME, JSON.stringify(ids));
    target.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }));
    target.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
  },
  done: (rep) => new Promise((res) => rep.on('done', res)),
  last: () => SM.app.reports[SM.app.reports.length - 1],
  outlines: (rep) => [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map((h) => h.textContent),
  errors: (rep) => [...rep.body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent.slice(0, 300)),
};
window.addEventListener('dragover', (e) => { D.over = { taken: e.defaultPrevented }; });
window.addEventListener('drop', () => { D.drops++; });
'''


class Drag:
    """A drag with the mouse, as a user makes it: pressed on the source and
    moved until Chrome starts the drag (the page's own dragstart sets the
    data, handed over by drag interception), then over() a point, and
    drop() or cancel(). A cancelled drag (Escape, or letting go outside the
    window) ends with no drop: Chrome sends the source its dragend."""

    def __init__(self, page):
        self.page = page
        self.data = None
        self.at = None
        self.entered = False

    async def start(self, xy):
        p = self.page
        x, y = xy
        await p.call('Input.setInterceptDrags', {'enabled': True}, session=p.sid)
        p.drags.clear()
        await p.mouse('mouseMoved', x, y)
        await p.mouse('mousePressed', x, y)
        for k in range(1, 10):
            await p.mouse('mouseMoved', x + 5 * k, y + 2 * k)
            await asyncio.sleep(0.05)
            if p.drags:
                break
        if not p.drags:
            await p.mouse('mouseReleased', x, y)
            await p.call('Input.setInterceptDrags', {'enabled': False}, session=p.sid)
            return False
        self.data = p.drags[-1]['data']
        self.at = (x, y)
        return True

    async def _event(self, kind, x, y):
        await self.page.call('Input.dispatchDragEvent', {'type': kind, 'x': x, 'y': y, 'data': self.data}, session=self.page.sid)

    async def over(self, xy):
        x, y = xy
        await self._event('dragOver' if self.entered else 'dragEnter', x, y)
        self.entered = True
        # an element newly under the pointer gets its dragenter first, the dragover with the next move
        await self._event('dragOver', x, y)
        self.at = (x, y)
        await asyncio.sleep(0.05)

    async def _end(self):
        await self.page.mouse('mouseReleased', *self.at)
        await self.page.call('Input.setInterceptDrags', {'enabled': False}, session=self.page.sid)
        await asyncio.sleep(0.15)

    async def drop(self, xy=None):
        if xy is not None:
            await self.over(xy)
        await self._event('drop', *self.at)
        await self._end()

    async def cancel(self):
        await self._event('dragCancel', *self.at)
        await self._end()


async def drag(page, src, dst, mid=None, name=None):
    """Drag from the point src to the point dst (both JS expressions giving
    [x, y]) and drop; mid: a JS expression evaluated while over dst, before
    the drop (what the page shows then), name: a screenshot then. Returns
    (began, mid value)."""
    d = Drag(page)
    a = await page.ev(src)
    if not a or not await d.start(a):
        return False, None
    b = await page.ev(dst)
    await d.over(b)
    seen = await page.ev(mid) if mid else None
    if name:
        await shot(page, name)
    await d.drop()
    return True, seen


# ---- a launch dialog: Distribution on Students ------------------------------------------------------------
async def launch_dialog(page):
    await page.ev('''(async () => { SM.app.launch('distribution'); await D.sleep(300);
      D.cast(['age', 'sex', 'height (cm)', 'weight (kg)'], 'Y, Columns'); D.cast(['id'], 'By'); return 1; })()''')
    check('the dialog to drag in: four columns in Y, id in By', await page.ev('D.roles()'),
          {'Y, Columns': ['age', 'sex', 'height (cm)', 'weight (kg)'], 'Weight': [], 'Freq': [], 'By': ['id']})
    Y, W, F, B = "D.roleList('Y, Columns')", "D.roleList('Weight')", "D.roleList('Freq')", "D.roleList('By')"

    # moved from one role to another
    began, mid = await drag(page, f"D.at(D.item({Y}, 'height (cm)'), 0.3)", f"D.at({W})", 'D.marks()', 'd01-role-to-role.png')
    check('a drag began from a column in a role', began, True)
    check('... while over Weight: the item dimmed, Weight marked as taking it, no remove label', (mid['dragged'], mid['place'], mid['taken'], mid['badge']), (['height (cm)'], ['Weight'], True, None))
    check('dropped on Weight: moved out of Y into Weight', await page.ev('D.roles()'),
          {'Y, Columns': ['age', 'sex', 'weight (kg)'], 'Weight': ['height (cm)'], 'Freq': [], 'By': ['id']})
    check('... and nothing of the drag is left on show', {k: v for k, v in (await page.ev('D.marks()')).items() if k in ('dragged', 'place', 'badge', 'moving')},
          {'dragged': [], 'place': [], 'badge': None, 'moving': False})

    # refused: Freq takes numeric continuous columns, sex is character
    began, mid = await drag(page, f"D.at(D.item({Y}, 'sex'), 0.3)", f"D.at({F})", 'D.marks()', 'd02-refused.png')
    check('a character column over Freq: no drop shown, the numeric roles dimmed', (mid['place'], mid['taken'], mid['refusing']), ([], False, ['Weight', 'Freq']))
    check('... and the dialog says why', mid['msg'], 'Freq needs a numeric column; sex is character')
    check('let go over Freq: nothing changes', await page.ev('D.roles()'),
          {'Y, Columns': ['age', 'sex', 'weight (kg)'], 'Weight': ['height (cm)'], 'Freq': [], 'By': ['id']})
    r = await page.ev('D.marks()')
    check('... the message and the dimming go with the drag', (r['msg'], r['refusing'], r['moving']), ('', [], False))

    # reordered within a role: down (it lands after the one it is dropped on), then up (before it)
    began, mid = await drag(page, f"D.at(D.item({Y}, 'age'), 0.3)", f"D.at(D.item({Y}, 'weight (kg)'))", 'D.marks()', 'd03-reorder.png')
    check('along Y, over the last column: it would land after it', (mid['after'], mid['before'], mid['place'], mid['taken']), (['weight (kg)'], [], ['Y, Columns'], True))
    check('dropped: Y reordered, age last', await page.ev(f'D.names({Y})'), ['sex', 'weight (kg)', 'age'])
    began, mid = await drag(page, f"D.at(D.item({Y}, 'age'), 0.3)", f"D.at(D.item({Y}, 'sex'))", 'D.marks()')
    check('back up, over the first: it would land before it', (mid['before'], mid['after']), (['sex'], []))
    check('dropped: age first again', await page.ev(f'D.names({Y})'), ['age', 'sex', 'weight (kg)'])

    # onto a column of another role: it takes its place
    began, mid = await drag(page, f"D.at(D.item({Y}, 'sex'), 0.3)", f"D.at(D.item({B}, 'id'))", 'D.marks()', 'd04-replace.png')
    check('over id in By: id marked as the one it replaces', (mid['replace'], mid['place']), (['id'], ['By']))
    check('dropped on id: sex in By in its place, out of Y', await page.ev('D.roles()'),
          {'Y, Columns': ['age', 'weight (kg)'], 'Weight': ['height (cm)'], 'Freq': [], 'By': ['sex']})

    # taken out: dropped on the column list, then on the dialog's lead
    began, mid = await drag(page, f"D.at(D.item({Y}, 'age'), 0.3)", "D.at(D.dlg().querySelector('.sm-pick-list'), 0.5, 0.3)", 'D.marks()', 'd05-remove-label.png')
    check('over the column list: a label says it is taken out, the item struck through', (mid['badge'], mid['removing'], mid['removeRoot'], mid['taken']), ('×Remove age from Y, Columns', ['age'], True, True))
    check('dropped on the column list: age out of Y', await page.ev(f'D.names({Y})'), ['weight (kg)'])
    began, mid = await drag(page, f"D.at(D.item({B}, 'sex'), 0.3)", "D.at(D.dlg().querySelector('.sm-dialog-lead'))", 'D.marks()')
    check('over the dialog\'s lead: the same label', mid['badge'], '×Remove sex from By')
    check('dropped on the lead: sex out of By', await page.ev(f'D.names({B})'), [])
    check('... the label and the marks gone', {k: v for k, v in (await page.ev('D.marks()')).items() if k in ('badge', 'removing', 'removeRoot')}, {'badge': None, 'removing': [], 'removeRoot': False})

    # cancelled: Escape (the drag ends with no drop); let go beside the dialog
    d = Drag(page)
    await d.start(await page.ev(f"D.at(D.item({Y}, 'weight (kg)'), 0.3)"))
    await d.over(await page.ev("D.at(D.dlg().querySelector('.sm-pick-list'), 0.5, 0.3)"))
    before = await page.ev('D.marks()')
    drops = before['drops']
    await d.cancel()
    after = await page.ev('D.marks()')
    check('a cancelled drag: the remove label was up', before['badge'], '×Remove weight (kg) from Y, Columns')
    check('... Escape: no drop, weight (kg) still in Y', (after['drops'] - drops, await page.ev(f'D.names({Y})')), (0, ['weight (kg)']))
    check('... and the drag\'s marks gone', (after['badge'], after['dragged'], after['removing'], after['moving']), (None, [], [], False))
    began, mid = await drag(page, f"D.at(D.item({Y}, 'weight (kg)'), 0.3)", '[12, 400]', 'D.marks()')
    check('beside the dialog (the dimmed page): no drop taken, no label', (mid['taken'], mid['badge']), (False, None))
    check('let go there: nothing changes', await page.ev('D.roles()'),
          {'Y, Columns': ['weight (kg)'], 'Weight': ['height (cm)'], 'Freq': [], 'By': []})

    # a column from the column list still goes in as before (after the others; the list keeps it)
    began, _ = await drag(page, "D.at(D.item(D.dlg().querySelector('.sm-pick-list'), 'age'), 0.3)", f"D.at({Y})")
    check('a column dragged from the list onto Y goes in after the others', (began, await page.ev(f'D.names({Y})')), (True, ['weight (kg)', 'age']))

    # a role's button is the role too: dropped on By's button, age moves to By; on Y's, back
    button = lambda label: f"D.at([...D.dlg().querySelectorAll('.sm-role .sm-btn')].find((b) => b.textContent === {json.dumps(label)}))"
    began, mid = await drag(page, f"D.at(D.item({Y}, 'age'), 0.3)", button('By'), 'D.marks()')
    check('a column over another role\'s button: that role takes it', (mid['place'], mid['taken'], mid['badge']), (['By'], True, None))
    check('dropped on By\'s button: age moved to By', await page.ev('D.roles()'), {'Y, Columns': ['weight (kg)'], 'Weight': ['height (cm)'], 'Freq': [], 'By': ['age']})
    await drag(page, f"D.at(D.item({B}, 'age'), 0.3)", button('Y, Columns'))
    check('... and on Y\'s button: back in Y, after weight (kg)', await page.ev('D.roles()'), {'Y, Columns': ['weight (kg)', 'age'], 'Weight': ['height (cm)'], 'Freq': [], 'By': []})
    # and so is it for a column dragged from the list (then taken out again)
    began, mid = await drag(page, "D.at(D.item(D.dlg().querySelector('.sm-pick-list'), 'sex'), 0.3)", button('By'), 'D.marks()')
    check('a column from the list over By\'s button: By takes it', (began, mid['place'], mid['taken']), (True, ['By'], True))
    check('dropped there: sex is in By', await page.ev('D.roles()'), {'Y, Columns': ['weight (kg)', 'age'], 'Weight': ['height (cm)'], 'Freq': [], 'By': ['sex']})
    await drag(page, f"D.at(D.item({B}, 'sex'), 0.3)", "D.at(D.dlg().querySelector('.sm-pick-list'), 0.5, 0.3)")
    check('... and dragged back onto the list: out of By', await page.ev('D.roles()'), {'Y, Columns': ['weight (kg)', 'age'], 'Weight': ['height (cm)'], 'Freq': [], 'By': []})

    # the report is the one the roles make: weight (kg) then age, weighted by height (cm)
    r = await page.ev('''(async () => { D.button('OK', D.dlg().querySelector('.sm-actions')); const rep = D.last(); await D.done(rep);
      const t = rep.table, names = (k) => (rep.spec.roles[k] || []).map((id) => t.col(id).name);
      return { roles: { y: names('y'), weight: names('weight'), by: names('by') }, outlines: [...rep.body.querySelectorAll('.sm-ob-head h3')].map((h) => h.textContent), errors: D.errors(rep),
        sumw: t.col('height (cm)').values.reduce((a, b) => a + b, 0) }; })()''')
    check('OK: the report\'s roles are the ones the drags made', r['roles'], {'y': ['weight (kg)', 'age'], 'weight': ['height (cm)'], 'by': []})
    check('... its outlines in the new order of Y', r['outlines'][:2], ['weight (kg)', 'age'])
    stats = await page.ev(table_under_js('Summary Statistics'))
    n = [row[1] for row in stats if row[0] == 'N']
    check.near('... and weight (kg) weighted by height (cm): N is the sum of the weights', float(n[0].replace(',', '')) if n else None, r['sumw'], 1e-6)
    check('... without an error', r['errors'], [])


# ---- Fit Model's Construct Model Effects, on the plant trial --------------------------------------------------
async def fit_model(page):
    await page.ev('''(async () => { SM.app.openExample('plants'); await D.sleep(300); SM.app.launch('fitmodel'); await D.sleep(300);
      D.cast(['yield (g)'], 'Y'); D.cast(['plot'], 'By');
      D.pick(['fertilizer', 'water', 'light (h)']); D.button('Add', D.dlg().querySelector('.sm-fm-tools'));
      D.pick(['fertilizer', 'water']); D.button('Cross', D.dlg().querySelector('.sm-fm-tools')); return 1; })()''')
    E, B = "D.dlg().querySelector('.sm-fm-effects')", "D.roleList('By')"
    check('Fit Model: the effects to drag', await page.ev(f'D.names({E})'), ['fertilizer', 'water', 'light (h)', 'fertilizer*water'])
    # reordered: up (before the one it is dropped on), then down (after it)
    began, mid = await drag(page, f"D.at(D.item({E}, 'light (h)'), 0.3)", f"D.at(D.item({E}, 'fertilizer'))", 'D.marks()', 'd06-effects-reorder.png')
    check('an effect dragged up the list: it would land before fertilizer', (began, mid['before'], mid['place'], mid['dragged']), (True, ['fertilizer'], ['Model effects'], ['light (h)']))
    check('dropped: light (h) first', await page.ev(f'D.names({E})'), ['light (h)', 'fertilizer', 'water', 'fertilizer*water'])
    began, mid = await drag(page, f"D.at(D.item({E}, 'fertilizer'), 0.3)", f"D.at(D.item({E}, 'water'))", 'D.marks()')
    check('... dragged down onto water: it would land after it', mid['after'], ['water'])
    check('dropped: fertilizer after water', await page.ev(f'D.names({E})'), ['light (h)', 'water', 'fertilizer', 'fertilizer*water'])
    # an effect taken out by a drag onto the column list
    began, mid = await drag(page, f"D.at(D.item({E}, 'water'), 0.3)", "D.at(D.dlg().querySelector('.sm-pick-list'), 0.5, 0.3)", 'D.marks()')
    check('an effect over the column list: the remove label', mid['badge'], '×Remove water from Model Effects')
    check('dropped there: water out of the model', await page.ev(f'D.names({E})'), ['light (h)', 'fertilizer', 'fertilizer*water'])
    # a crossing is not a column: every role refuses it, and a drop on one changes nothing
    began, mid = await drag(page, f"D.at(D.item({E}, 'fertilizer*water'), 0.3)", f"D.at({B})", 'D.marks()')
    check('a crossing over By: no drop, every role dimmed, the dialog says why',
          (mid['place'], mid['taken'], sorted(mid['refusing']), mid['msg']), ([], False, sorted(['Y', 'Weight', 'Freq', 'Validation', 'By']), 'By takes columns; fertilizer*water is an effect'))
    check('let go over By: nothing changes', (await page.ev(f'D.names({E})'), await page.ev(f'D.names({B})')), (['light (h)', 'fertilizer', 'fertilizer*water'], ['plot']))
    # a column moved from a role into the effects (beside them: at the end), and back onto the role as a main effect
    began, mid = await drag(page, f"D.at(D.item({B}, 'plot'), 0.3)", f"D.at({E}, 0.5, 0.85)", 'D.marks()')
    check('a column from By over the effects: the list takes it', (mid['place'], mid['taken']), (['Model effects'], True))
    check('dropped: plot out of By, a main effect at the end', (await page.ev(f'D.names({B})'), await page.ev(f'D.names({E})')), ([], ['light (h)', 'fertilizer', 'fertilizer*water', 'plot']))
    began, mid = await drag(page, f"D.at(D.item({E}, 'plot'), 0.3)", f"D.at({B})", 'D.marks()')
    check('the main effect back onto By: taken there', (mid['place'], mid['taken']), (['By'], True))
    check('dropped: plot in By again, out of the effects', (await page.ev(f'D.names({B})'), await page.ev(f'D.names({E})')), (['plot'], ['light (h)', 'fertilizer', 'fertilizer*water']))
    began, _ = await drag(page, f"D.at(D.item({B}, 'plot'), 0.3)", "D.at(D.dlg().querySelector('.sm-dialog-lead'))")
    check('... and out of By by a drop on the dialog\'s lead', await page.ev(f'D.names({B})'), [])
    # the fitted model has the effects in the list's order
    r = await page.ev('''(async () => { D.button('OK', D.dlg().querySelector('.sm-actions')); const rep = D.last(); await D.done(rep);
      const ob = [...rep.body.querySelectorAll('.sm-ob-head')].find((h) => h.textContent.trim() === 'Effect Tests');
      const t = ob && ob.parentElement.querySelector(':scope > .sm-ob-body table.sm-rt');
      return { effects: rep.spec.effects.map((e) => e.names.join('*')), by: (rep.spec.roles.by || []).length, errors: D.errors(rep),
        sources: t ? [...t.querySelectorAll('tbody tr')].map((tr) => tr.children[0].textContent.trim()) : null }; })()''')
    check('OK: the model\'s effects in the order the drags left them, no By', (r['effects'], r['by']), (['light (h)', 'fertilizer', 'fertilizer*water'], 0))
    check('... and the Effect Tests in that order', r['sources'], ['light (h)', 'fertilizer', 'fertilizer*water'])
    check('... without an error', r['errors'], [])


# ---- Multiple Imputation's analysis model, on the incomplete table -----------------------------------------------
async def multiple_imputation(page):
    await page.ev('''(async () => { SM.app.openExample('incomplete'); await D.sleep(300); SM.app.launch('mi'); await D.sleep(300);
      D.cast(['age', 'bmi', 'activity', 'cholesterol', 'sbp'], 'Y, Columns to Impute'); D.cast(['sbp'], 'Model Response');
      for (const n of ['age', 'bmi', 'cholesterol', 'activity']) { D.pick([n]); D.button('Add', D.dlg().querySelector('.sm-mi-tools')); }
      const m = D.dlg().querySelector('input[aria-label="Imputations"]'); m.value = '5'; return 1; })()''')
    E, R = "D.dlg().querySelector('.sm-mi-effects')", "D.roleList('Model Response')"
    check('Multiple Imputation: the effects to drag', await page.ev(f'D.names({E})'), ['age', 'bmi', 'cholesterol', 'activity'])
    began, mid = await drag(page, f"D.at(D.item({E}, 'activity'), 0.3)", f"D.at(D.item({E}, 'age'))", 'D.marks()')
    check('an effect dragged up the list: it would land before age', (began, mid['before'], mid['place']), (True, ['age'], ['Analysis model effects']))
    check('dropped: activity first', await page.ev(f'D.names({E})'), ['activity', 'age', 'bmi', 'cholesterol'])
    began, mid = await drag(page, f"D.at(D.item({E}, 'bmi'), 0.3)", "D.at(D.dlg().querySelector('.sm-pick-list'), 0.5, 0.3)", 'D.marks()')
    check('an effect over the column list: the remove label', mid['badge'], '×Remove bmi from Analysis Model')
    check('dropped there: bmi out of the model', await page.ev(f'D.names({E})'), ['activity', 'age', 'cholesterol'])
    began, mid = await drag(page, f"D.at(D.item({E}, 'cholesterol'), 0.3)", f"D.at(D.item({R}, 'sbp'))", 'D.marks()')
    check('a main effect over the Model Response: it would take sbp\'s place', (mid['replace'], mid['place']), (['sbp'], ['Model Response']))
    check('dropped: cholesterol the response, out of the effects', (await page.ev(f'D.names({R})'), await page.ev(f'D.names({E})')), (['cholesterol'], ['activity', 'age']))
    r = await page.ev('''(async () => { D.button('OK', D.dlg().querySelector('.sm-actions')); const rep = D.last(); await D.done(rep);
      const ob = [...rep.body.querySelectorAll('.sm-ob-head')].find((h) => h.textContent.trim() === 'Pooled Estimates');
      const t = ob && ob.parentElement.querySelector(':scope > .sm-ob-body table.sm-rt');
      return { title: rep.title, effects: rep.spec.effects.map((e) => e.names.join('*')), errors: D.errors(rep),
        terms: t ? [...t.querySelectorAll('tbody tr')].map((tr) => tr.children[0].textContent.trim()) : null }; })()''', timeout=300)
    check('OK: the pooled model is cholesterol on activity and age', (r['title'], r['effects']), ('Multiple Imputation: cholesterol', ['activity', 'age']))
    check('... its estimates for those terms', r['terms'], ['Intercept', 'activity', 'age'])
    check('... without an error', r['errors'], [])


# ---- Graph Builder's zones, on Students ---------------------------------------------------------------------
# The graph as it is drawn: the zones (the columns in each), the title, the
# Y axes' titles top to bottom, the X axes, the legend, the panels' labels,
# and the points: how many there are and how many lie within the Y range
# their panel is drawn with (a panel drawn at a range beside its data is
# empty).
GB_LOOK = r'''(async () => { await _gb.idle(); const p = _gb.plot(); const L = p.userLayout;
  const ax = (re) => Object.keys(L).filter((k) => re.test(k)).sort();
  const FL = p.box._fullLayout; let points = 0, inside = 0;
  for (const tr of p.box.data) {
    if (!/markers/.test(tr.mode || '')) continue;
    const ya = FL[!tr.yaxis || tr.yaxis === 'y' ? 'yaxis' : `yaxis${tr.yaxis.slice(1)}`], lo = Math.min(...ya.range), hi = Math.max(...ya.range);
    for (const v of tr.y || []) if (Number.isFinite(v)) { points++; if (v >= lo && v <= hi) inside++; }
  }
  return { zones: Object.fromEntries(Object.entries(_gb.state().zones).filter(([k, v]) => v.length).map(([k, v]) => [k, v.map((r) => r.name)])),
    title: L.title && L.title.text ? L.title.text.replace(/&amp;/g, '&') : null, ytitles: ax(/^yaxis\d*$/).map((k) => L[k].title && L[k].title.text).filter(Boolean),
    xaxes: ax(/^xaxis\d*$/).length, legend: p.traces.filter((tr) => tr.showlegend).map((tr) => tr.name), panels: (L.annotations || []).map((a) => a.text).filter((s) => !/[<]/.test(s)),
    points, inside }; })()'''


async def graph_builder(page):
    await page.ev('''(async () => { const t = SM.app.tables.find((x) => x.name === 'Students'); SM.app.showTab(SM.app.tabOf(t));
      SM.app.launch('graphbuilder'); const rep = D.last(); await D.done(rep); window._rep = rep;
      Object.defineProperty(window, '_gb', { configurable: true, get: () => SM.platforms.get('graphbuilder').builder(window._rep) });
      const ref = (n) => ({ id: t.col(n).id, name: n });
      await _gb.update((S) => { S.zones.x = [ref('age')]; S.zones.y = [ref('height (cm)'), ref('weight (kg)')]; S.zones.overlay = [ref('sex')]; });
      return 1; })()''')
    zone = lambda k: f"_rep.body.querySelector('.sm-gb-z-{k}')"
    chip = lambda k, n: f"D.item({zone(k)}, {json.dumps(n)})"
    g = await page.ev(GB_LOOK)
    check('Graph Builder: the graph to drag in', (g['zones'], g['title'], g['legend']),
          ({'x': ['age'], 'y': ['height (cm)', 'weight (kg)'], 'overlay': ['sex']}, 'height (cm) & weight (kg) vs. age', ['F', 'M']))

    # reordered within Y: weight (kg) dropped on height (cm) takes its position, and the panels follow
    began, mid = await drag(page, f"D.at({chip('y', 'weight (kg)')})", f"D.at({chip('y', 'height (cm)')})", 'D.marks()', 'd07-gb-reorder.png')
    check('a column dragged along Y: it would land before height (cm), Y takes it', (began, mid['before'], mid['place'], mid['dragged']), (True, ['height (cm)'], ['zone:y'], ['weight (kg)']))
    g = await page.ev(GB_LOOK)
    check('dropped: Y reordered, the top panel weight (kg)', (g['zones']['y'], g['ytitles'], g['title']), (['weight (kg)', 'height (cm)'], ['weight (kg)', 'height (cm)'], 'weight (kg) & height (cm) vs. age'))

    # moved from Overlay to Group X: one step of Undo; the legend goes, a column of panels for each level comes
    began, mid = await drag(page, f"D.at({chip('overlay', 'sex')})", f"D.at({zone('groupX')})", 'D.marks()', 'd08-gb-move.png')
    check('a column dragged from Overlay over Group X: Group X takes it', (mid['place'], mid['taken'], mid['badge']), (['zone:groupX'], True, None))
    g = await page.ev(GB_LOOK)
    check('dropped: sex moved from Overlay to Group X', (g['zones'].get('overlay'), g['zones'].get('groupX')), (None, ['sex']))
    check('... the graph drawn again: no legend, a column of panels for F and for M', (g['legend'], g['xaxes'], g['panels'][:2]), ([], 4, ['F', 'M']))
    check('... every row a point in its panel, within the Y range the panel is drawn with', (g['points'], g['inside']), (120, 120))
    await page.ev('_gb.undo()')
    g = await page.ev(GB_LOOK)
    check('... and one Undo puts it back in Overlay', (g['zones'].get('overlay'), g['zones'].get('groupX'), g['legend']), (['sex'], None, ['F', 'M']))
    await drag(page, f"D.at({chip('overlay', 'sex')})", f"D.at({zone('groupX')})")

    # refused: Size takes a continuous column, Freq a numeric one
    began, mid = await drag(page, f"D.at({chip('groupX', 'sex')})", f"D.at({zone('size')})", 'D.marks()', 'd09-gb-refused.png')
    check('a nominal column over Size: no drop shown, Size and Freq dimmed', (mid['place'], mid['taken'], sorted(mid['refusing'])), ([], False, ['zone:freq', 'zone:size']))
    check('let go over Size: nothing changes', (await page.ev(GB_LOOK))['zones'], {'x': ['age'], 'y': ['weight (kg)', 'height (cm)'], 'groupX': ['sex']})

    # onto a column of another zone: it takes its place
    began, mid = await drag(page, f"D.at({chip('groupX', 'sex')})", f"D.at({chip('x', 'age')})", 'D.marks()', 'd10-gb-replace.png')
    check('over age in X: age marked as the one it replaces', (mid['replace'], mid['place']), (['age'], ['zone:x']))
    g = await page.ev(GB_LOOK)
    check('dropped on age: sex on X instead of age, out of Group X', (g['zones'], g['title'], g['xaxes']), ({'x': ['sex'], 'y': ['weight (kg)', 'height (cm)']}, 'weight (kg) & height (cm) vs. sex', 2))

    # taken out: dropped on the builder's column list, then on the graph
    began, mid = await drag(page, f"D.at({chip('y', 'height (cm)')})", "D.at(_rep.body.querySelector('.sm-gb-collist'), 0.5, 0.7)", 'D.marks()', 'd11-gb-remove-label.png')
    check('a column over the builder\'s column list: the remove label, the chip struck through', (mid['badge'], mid['removing'], mid['taken']), ('×Remove height (cm) from Y', ['height (cm)'], True))
    g = await page.ev(GB_LOOK)
    check('dropped there: height (cm) out of Y, one panel left', (g['zones'], g['ytitles']), ({'x': ['sex'], 'y': ['weight (kg)']}, ['weight (kg)']))
    began, mid = await drag(page, f"D.at({chip('x', 'sex')})", "D.at(_rep.body.querySelector('.sm-gb-plotwrap .js-plotly-plot'), 0.5, 0.4)", 'D.marks()')
    check('a column over the graph: the remove label', mid['badge'], '×Remove sex from X')
    g = await page.ev(GB_LOOK)
    check('dropped on the graph: sex out of X, weight (kg) alone', (g['zones'], g['title']), ({'y': ['weight (kg)']}, 'weight (kg)'))

    # cancelled, and let go outside the builder: nothing changes
    d = Drag(page)
    await d.start(await page.ev(f"D.at({chip('y', 'weight (kg)')})"))
    await d.over(await page.ev("D.at(_rep.body.querySelector('.sm-gb-collist'), 0.5, 0.7)"))
    before = await page.ev('D.marks()')
    await d.cancel()
    after = await page.ev('D.marks()')
    check('a cancelled drag of a zone\'s column: the label was up, then no drop, nothing moved', (before['badge'], after['badge'], after['moving'], (await page.ev(GB_LOOK))['zones']),
          ('×Remove weight (kg) from Y', None, False, {'y': ['weight (kg)']}))
    began, mid = await drag(page, f"D.at({chip('y', 'weight (kg)')})", "D.at(_rep.body.querySelector('.sm-ob.level-0 > .sm-ob-head'), 0.5, 0.5)", 'D.marks()')
    check('over the report outside the builder: no drop taken, no label', (mid['taken'], mid['badge']), (False, None))
    check('let go there: nothing changes', (await page.ev(GB_LOOK))['zones'], {'y': ['weight (kg)']})


# ---- Tabulate's zones, on Students ------------------------------------------------------------------------
# The builder's state once the report has run again, and the table it made:
# the columns' labels and each row's labels (its row levels, blocks and
# nesting together; 'All' without rows).
TAB_LOOK = r'''(async () => { const rep = window._tab;
  for (let i = 0; i < 800 && rep.body.classList.contains('is-running'); i++) await D.sleep(25);
  await D.sleep(60);
  const s = rep.spec.options.tab, names = (list) => list.map((r) => r.name);
  const tbl = rep.body.querySelector('table.smt-table'), rt = tbl && tbl._rt;
  return { rows: s.rows.map(names), cols: s.cols.map(names), analysis: names(s.analysis), stats: s.stats,
    labels: rt ? rt.columns.map((c) => c.label) : null, errors: D.errors(rep),
    first: rt ? rt.rows.map((r) => { const lv = rt.columns.filter((c) => /^r\d+$/.test(c.key)).map((c) => r[c.key]).filter((v) => v !== ''); return lv.length ? lv.join(' ') : r._label; }) : null }; })()'''


async def tabulate(page):
    await page.ev('''(async () => { const t = SM.app.tables.find((x) => x.name === 'Students'); SM.app.showTab(SM.app.tabOf(t)); SM.app.grid.colSel.clear();
      SM.app.launch('tabulate'); const rep = D.last(); await D.done(rep); window._tab = rep;
      const zone = (k) => rep.body.querySelector(`.smt-zone[data-zone="${k}"]`);
      for (const [k, n] of [['rows', 'sex'], ['cols', 'age'], ['analysis', 'height (cm)'], ['analysis', 'weight (kg)']]) { const p = D.done(rep); D.listDrop(zone(k), [t.col(n).id]); await p; }
      return 1; })()''')
    zone = lambda k: f"window._tab.body.querySelector('.smt-zone[data-zone=\"{k}\"]')"
    label = lambda k: f"{zone(k)}.querySelector('.smt-zonelabel')"
    chip = lambda k, n: f"D.item({zone(k)}, {json.dumps(n)})"
    g = await page.ev(TAB_LOOK)
    check('Tabulate: the table to drag in', (g['rows'], g['cols'], g['analysis'], g['stats']), ([['sex']], [['age']], ['height (cm)', 'weight (kg)'], ['N', 'Mean']))

    # moved from the columns to the rows (beside the rows' columns: a block of its own, after sex)
    began, mid = await drag(page, f"D.at({chip('cols', 'age')}, 0.3)", f"D.at({label('rows')})", 'D.marks()', 'd12-tab-move.png')
    check('a column dragged from the columns over the rows: the rows take it', (began, mid['place'], mid['taken'], mid['dragged']), (True, ['zone:rows'], True, ['age']))
    g = await page.ev(TAB_LOOK)
    check('dropped: age a block of rows after sex, no columns left', (g['rows'], g['cols']), ([['sex'], ['age']], []))
    check('... the table computed again: a row for each sex, then each age', g['first'], ['F', 'M', '12', '13', '14', '15', '16', '17'])

    # along the rows: age dropped on sex lands before it, in its block (sex nested in age)
    began, mid = await drag(page, f"D.at({chip('rows', 'age')}, 0.3)", f"D.at({chip('rows', 'sex')})", 'D.marks()', 'd13-tab-nest.png')
    check('age dragged along the rows onto sex: it would land before sex', (mid['before'], mid['place']), (['sex'], ['zone:rows']))
    g = await page.ev(TAB_LOOK)
    check('dropped: one block, age then sex nested in it', g['rows'], [['age', 'sex']])
    check('... the table: the ages, each with its sexes', g['first'][:4], ['12 F', '12 M', '13 F', '13 M'])

    # the analysis columns reordered
    began, mid = await drag(page, f"D.at({chip('analysis', 'weight (kg)')}, 0.3)", f"D.at({chip('analysis', 'height (cm)')})", 'D.marks()')
    check('weight (kg) dragged onto height (cm): it would land before it', mid['before'], ['height (cm)'])
    g = await page.ev(TAB_LOOK)
    check('dropped: the analysis columns reordered, and the table\'s columns with them', (g['analysis'], [x for x in g['labels'] if x.startswith('Mean')]),
          (['weight (kg)', 'height (cm)'], ['Mean(weight (kg))', 'Mean(height (cm))']))

    # moved out of a block to the columns, then a column of the rows put in its place
    await drag(page, f"D.at({chip('rows', 'sex')}, 0.3)", f"D.at({label('cols')})")
    g = await page.ev(TAB_LOOK)
    check('sex dragged from the rows to the columns', (g['rows'], g['cols']), ([['age']], [['sex']]))
    began, mid = await drag(page, f"D.at({chip('rows', 'age')}, 0.3)", f"D.at({chip('cols', 'sex')})", 'D.marks()', 'd14-tab-replace.png')
    check('age over sex in the columns: sex marked as the one it replaces', (mid['replace'], mid['place']), (['sex'], ['zone:cols']))
    g = await page.ev(TAB_LOOK)
    check('dropped: age in the columns in place of sex, the rows empty', (g['rows'], g['cols']), ([], [['age']]))
    check('... the table: one row of all, a column of cells for each age', (g['first'], len([x for x in g['labels'] if x.startswith('Mean(weight (kg)')])), (['All'], 6))

    # refused: the rows take nominal and ordinal columns
    began, mid = await drag(page, f"D.at({chip('analysis', 'height (cm)')}, 0.3)", f"D.at({label('rows')})", 'D.marks()', 'd15-tab-refused.png')
    check('a continuous column over the rows: no drop shown, the rows and columns dimmed', (mid['place'], mid['taken'], sorted(mid['refusing'])), ([], False, ['zone:cols', 'zone:rows']))
    g = await page.ev(TAB_LOOK)
    check('let go over the rows: nothing changes', (g['rows'], g['cols'], g['analysis']), ([], [['age']], ['weight (kg)', 'height (cm)']))

    # taken out: dropped on the column list, then on the table
    began, mid = await drag(page, f"D.at({chip('analysis', 'weight (kg)')}, 0.3)", "D.at(window._tab.body.querySelector('.smt-cols'), 0.5, 0.6)", 'D.marks()', 'd16-tab-remove-label.png')
    check('a column over Tabulate\'s column list: the remove label', (mid['badge'], mid['removing']), ('×Remove weight (kg) from the analysis columns', ['weight (kg)']))
    g = await page.ev(TAB_LOOK)
    check('dropped there: weight (kg) out of the analysis columns', g['analysis'], ['height (cm)'])
    began, mid = await drag(page, f"D.at({chip('cols', 'age')}, 0.3)", "D.at(window._tab.body.querySelector('table.smt-table'), 0.5, 0.5)", 'D.marks()')
    check('a column over the table: the remove label', mid['badge'], '×Remove age from the columns')
    g = await page.ev(TAB_LOOK)
    check('dropped on the table: age out, the table height (cm) for all rows', (g['cols'], g['first'], g['labels']), ([], ['All'], ['', 'N(height (cm))', 'Mean(height (cm))']))
    check('... without an error', g['errors'], [])

    # cancelled
    d = Drag(page)
    await d.start(await page.ev(f"D.at({chip('analysis', 'height (cm)')}, 0.3)"))
    await d.over(await page.ev("D.at(window._tab.body.querySelector('.smt-cols'), 0.5, 0.6)"))
    before = await page.ev('D.marks()')
    await d.cancel()
    g = await page.ev(TAB_LOOK)
    check('a cancelled drag of a Tabulate column: the label was up, nothing moved', (before['badge'], g['analysis'], (await page.ev('D.marks()'))['moving']),
          ('×Remove height (cm) from the analysis columns', ['height (cm)'], False))


# ---- the (i) of every place says its columns can be dragged out -----------------------------------------------
# A topic's words: its lead, and every section's text, list and choices.
TOPIC_TEXT = r'''((key) => { const t = SM.info.get(key); if (!t) return null;
  const parts = [t.lead || ''];
  for (const s of t.sections || []) parts.push([].concat(s.text || []).join(' '), (s.list || []).join(' '), (s.choices || []).map((c) => `${c[0]}: ${c[1]}`).join(' '));
  return parts.join(' '); })'''


async def help_texts(page):
    # the launch topics are made when a dialog opens: open each once
    await page.ev('''(async () => { const t = SM.app.tables.find((x) => x.name === 'Students'); SM.app.showTab(SM.app.tabOf(t));
      for (const id of ['distribution', 'fitmodel', 'mi']) { SM.app.launch(id); await D.sleep(250); D.dlg().querySelector('.sm-dialog-x').click(); await D.sleep(80); } return 1; })()''')
    # the dialog's (i) as it reads: the Roles section's words
    roles = await page.ev('''(async () => { SM.app.launch('distribution'); await D.sleep(250); D.dlg().querySelector('.sm-dialog-head .info-btn').click(); await D.sleep(250);
      const body = document.querySelector('.info-panel .info-panel-body'); let on = false; const out = [];
      for (const n of body.children) { if (n.tagName === 'H3') on = n.textContent === 'Roles'; else if (on && n.tagName === 'P') out.push(n.textContent); }
      KvotInfo.close(); D.dlg().querySelector('.sm-dialog-x').click(); return out.join(' '); })()''')
    say = lambda key: page.ev(f'({TOPIC_TEXT})({json.dumps(key)})')
    words = {
        'a launch dialog\'s (i), its Roles': roles,
        'Fit Model\'s launch (i)': await say('launch:fitmodel'),
        'Fit Model\'s Construct Model Effects (i)': await say('p:fitmodel:effects'),
        'Multiple Imputation\'s launch (i)': await say('launch:mi'),
        'Multiple Imputation\'s Analysis Model (i)': await say('p:mi:model'),
        'Graph Builder\'s (i)': await say('p:graphbuilder'),
        'Tabulate\'s (i)': await say('p:tabulate'),
    }
    for what, text in words.items():
        t = (text or '').lower()
        check(f'{what} says a column dropped there can be dragged out: to another place, onto a column, along it, elsewhere to take it out',
              all(w in t for w in ('dragged', 'take it out')) and ('along' in t or 'up or down' in t) and ('place' in t or 'replace' in t), True)


# ---- by touch, on a phone: held, then moved ------------------------------------------------------------------
async def touch(page):
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 820, 'deviceScaleFactor': 2, 'mobile': True}, session=page.sid)
    await page.call('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 1}, session=page.sid)
    await asyncio.sleep(0.5)

    async def finger(kind, pts):
        await page.call('Input.dispatchTouchEvent', {'type': kind, 'touchPoints': pts}, session=page.sid)

    async def slide(a, b, steps=8):
        for i in range(1, steps + 1):
            await finger('touchMove', [{'x': a[0] + (b[0] - a[0]) * i / steps, 'y': a[1] + (b[1] - a[1]) * i / steps}])
            await asyncio.sleep(0.03)

    async def hold_and_move(src, dst, mid=None, end='touchEnd', far_top=None, name=None):
        """Held still, then moved (to the bottom edge first while the target
        is below the screen: the box under the finger scrolls), then lifted
        or cancelled; mid: a JS expression evaluated over the target, name: a
        screenshot then."""
        a = await page.ev(src)
        await finger('touchStart', [{'x': a[0], 'y': a[1]}])
        await asyncio.sleep(0.45)
        if far_top is not None:
            await slide(a, (a[0], 806))
            for _ in range(100):
                await finger('touchMove', [{'x': a[0], 'y': 806}])
                await asyncio.sleep(0.05)
                r = await page.ev(f'(() => {{ const p = {dst}; return p && p[1]; }})()')
                if r is not None and r < far_top:
                    break
            a = (a[0], 806)
        b = await page.ev(dst)
        await slide(a, b)
        await finger('touchMove', [{'x': b[0], 'y': b[1]}])
        await asyncio.sleep(0.1)
        seen = await page.ev(mid) if mid else None
        if name:
            await shot(page, name)
        await finger(end, [])
        await asyncio.sleep(0.4)
        return seen

    # (the point of an element without scrolling it: the finger scrolls)
    AT = "((e, dx = 0.5, dy = 0.5) => { if (!e) return null; const r = e.getBoundingClientRect(); return [r.x + Math.min(r.width * dx, 60), r.y + r.height * dy]; })"
    GHOST = '''(() => { const g = document.querySelector('.sm-touchghost'), b = document.querySelector('.sm-dropcue'); const m = D.marks();
      const gr = g && g.getBoundingClientRect(), br = b && !b.hidden && b.getBoundingClientRect();
      return { ...m, ghost: g ? g.textContent : null, struck: g ? getComputedStyle(g).textDecorationLine : null, above: !!(gr && br && br.bottom <= gr.top + 1), seen: !!(br && br.top >= 0 && br.left >= 0 && br.right <= innerWidth) }; })()'''
    await page.ev('''(async () => { const t = SM.app.tables.find((x) => x.name === 'Students'); SM.app.showTab(SM.app.tabOf(t));
      SM.app.launch('distribution'); await D.sleep(300); D.cast(['age', 'height (cm)'], 'Y, Columns'); return 1; })()''')
    Y, W = "D.roleList('Y, Columns')", "D.roleList('Weight')"
    await page.ev(f"{W}.scrollIntoView({{ block: 'center' }})")
    await asyncio.sleep(0.2)
    mid = await hold_and_move(f"({AT})(D.item({Y}, 'height (cm)'))", f"({AT})({W})", GHOST, name='d17-phone-role.png')
    check('phone: a column held in Y and moved over Weight: under the finger, Weight takes it', (mid['ghost'], mid['place'], mid['taken']), ('height (cm)', ['Weight'], True))
    check('phone: let go there: moved from Y to Weight', await page.ev('D.roles()'), {'Y, Columns': ['age'], 'Weight': ['height (cm)'], 'Freq': [], 'By': []})
    mid = await hold_and_move(f"({AT})(D.item({Y}, 'age'))", f"({AT})(D.dlg().querySelector('.sm-pick-list'), 0.5, 0.85)", GHOST, name='d18-phone-remove.png')
    check('phone: over the column list: the label above the item under the finger, which is struck through', (mid['badge'], mid['touchBadge'], mid['above'], mid['seen'], 'line-through' in (mid['struck'] or '')),
          ('×Remove age from Y, Columns', True, True, True, True))
    check('phone: let go there: age out of Y', await page.ev(f'D.names({Y})'), [])
    await page.ev("D.cast(['age'], 'Y, Columns')")
    mid = await hold_and_move(f"({AT})(D.item({Y}, 'age'))", f"({AT})(D.dlg().querySelector('.sm-pick-list'), 0.5, 0.85)", 'D.marks()', end='touchCancel')
    r = await page.ev(GHOST)
    check('phone: a touch cancelled over the column list: the label was up, then nothing moved', (mid['badge'], await page.ev(f'D.names({Y})'), r['ghost'], r['badge'], r['moving']),
          ('×Remove age from Y, Columns', ['age'], None, None, False))
    await page.ev("D.dlg().querySelector('.sm-dialog-x').click()")
    await asyncio.sleep(0.3)

    # Graph Builder: a column held in X and moved to Overlay (the report scrolls to it)
    await page.ev('''(async () => { const t = SM.app.tables.find((x) => x.name === 'Students'); SM.app.showTab(SM.app.tabOf(t));
      SM.app.launch('graphbuilder'); const rep = D.last(); await D.done(rep); window._rep = rep; const ref = (n) => ({ id: t.col(n).id, name: n });
      await _gb.update((S) => { S.zones.x = [ref('age')]; S.zones.y = [ref('height (cm)')]; }); return 1; })()''')
    await page.ev("_rep.body.querySelector('.sm-gb-z-x').scrollIntoView({ block: 'center' })")
    await asyncio.sleep(0.3)
    mid = await hold_and_move(f"({AT})(D.item(_rep.body.querySelector('.sm-gb-z-x'), 'age'))", f"({AT})(_rep.body.querySelector('.sm-gb-z-overlay'))", 'D.marks()', far_top=560, name='d19-phone-gb.png')
    g = await page.ev(GB_LOOK)
    check('phone: a Graph Builder column held in X and moved over Overlay: Overlay takes it', (mid['place'], mid['taken']), (['zone:overlay'], True))
    check('phone: let go there: moved, and the graph drawn again with a legend for each age', (g['zones'], g['legend']), ({'y': ['height (cm)'], 'overlay': ['age']}, ['12', '13', '14', '15', '16', '17']))

    # Tabulate: a column held in the rows and moved to the columns
    await page.ev('''(async () => { const t = SM.app.tables.find((x) => x.name === 'Students'); SM.app.showTab(SM.app.tabOf(t)); SM.app.grid.colSel.clear();
      SM.app.launch('tabulate'); const rep = D.last(); await D.done(rep); window._tab = rep;
      const p = D.done(rep); D.listDrop(rep.body.querySelector('.smt-zone[data-zone="rows"]'), [t.col('sex').id]); await p; return 1; })()''')
    await page.ev("window._tab.body.querySelector('.smt-zone[data-zone=\"cols\"]').scrollIntoView({ block: 'center' })")
    await asyncio.sleep(0.3)
    mid = await hold_and_move(f"({AT})(D.item(window._tab.body.querySelector('.smt-zone[data-zone=\"rows\"]'), 'sex'), 0.3)", f"({AT})(window._tab.body.querySelector('.smt-zone[data-zone=\"cols\"] .smt-zonelabel'))", 'D.marks()')
    g = await page.ev(TAB_LOOK)
    check('phone: a Tabulate column held in the rows and moved over the columns: taken there', (mid['place'], mid['taken']), (['zone:cols'], True))
    check('phone: let go there: moved, and the table computed again', (g['rows'], g['cols'], g['labels'][:2]), ([], [['sex']], ['', 'N(sex=F)']))


async def main():
    page = await open_page(f'{BASE}/smui.html?example=students')
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    await page.ev(HELPERS)
    await launch_dialog(page)
    await fit_model(page)
    await multiple_imputation(page)
    await graph_builder(page)
    await tabulate(page)
    await help_texts(page)
    check('no script errors', page.errors, [])
    await page.close()

    page = await open_page(f'{BASE}/smui.html?example=students', width=400, height=820)
    st = await wait_engine(page)
    check('phone: engine ready', st, 'ready')
    await page.ev(HELPERS)
    await page.ev("Object.defineProperty(window, '_gb', { configurable: true, get: () => SM.platforms.get('graphbuilder').builder(window._rep) })")
    await touch(page)
    check('phone: no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
