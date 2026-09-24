#!/usr/bin/env python3
"""How the file-structure tree is laid out: where each row sits, and what its
arrow, folder icon and guide line say.

Rows are on one grid. The toggle and its margin are a 20px column, and a
level indents by exactly that column, so each child's arrow sits under its
parent's icon. A dataset has no toggle and keeps its column empty, so its
icon lines up with the folders beside it. It used to start where their arrows
did: a dataset's icon sat 18px left of its own folder's icon, and a level
indented only 6px, so data did not look as if it were in the folder at all.

The arrow is ▶ when closed and ▼ when open. It used to be ▲ closed and ▶ open.
The folder icon opens with the arrow. It used to follow the row's `expanded`
class, which is the selected look, so an opened folder showed a closed icon.
That class now means selected and nothing else. A search no longer puts it
on every folder above a match, and closing the selected folder no longer
takes it off.

The guide line of a level hangs from its parent's arrow. It is drawn in the
accent colour along the level a selected dataset is on, and along the members
of a selected group, which are what its chart draws.

Uses the committed fixture sample-a.h5. Start the server and the browser as in
README.md, then

    python3 resources/tests/rb/test-tree.py

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


TOTAL = '/biosphere/vault_A/mire/total'

HELPERS = r"""(() => {
  window.__wait = (ms) => new Promise(r => setTimeout(r, ms));
  window.__row = (path, kind) => findTreeItem(path, { extra: kind ? '.' + kind : '', root: document.getElementById('tree') });
  // Open every folder down to `path` with its arrow, as a person would.
  window.__open = async (path) => {
    const parts = path.split('/').filter(Boolean);
    for (const p of ['/', ...parts.map((_, i) => '/' + parts.slice(0, i + 1).join('/'))]) {
      const t = __row(p, 'group').querySelector('.tree-toggle');
      if (t.classList.contains('collapsed')) t.click();
      await __wait(400);
    }
  };
  const iconOf = (row) => getComputedStyle(row.querySelector('.tree-icon'), '::before').webkitMaskImage;
  window.__look = () => {
    const tree = document.getElementById('tree');
    const accent = getComputedStyle(document.documentElement).getPropertyValue('--color-kvot-accent').trim();
    const rgb = (() => { const d = document.createElement('div'); d.style.color = accent; tree.appendChild(d);
                         const c = getComputedStyle(d).color; d.remove(); return c; })();
    const rows = [...tree.querySelectorAll('.tree-item')].filter(r => r.offsetParent);
    return rows.map(r => {
      const box = r.nextElementSibling;
      const holder = r.parentElement.closest('.tree-group-children');
      const t = r.querySelector('.tree-toggle');
      return {
        path: r.getAttribute('data-path'),
        group: r.classList.contains('group'),
        selectedLook: r.classList.contains('expanded') || r.classList.contains('selected'),
        icon: Math.round(r.querySelector('.tree-icon').getBoundingClientRect().left),
        arrow: t && !t.classList.contains('no-toggle') ? getComputedStyle(t).transform : null,
        openIcon: r.classList.contains('group') ? iconOf(r).includes('v1') : null,
        guideAccent: holder ? getComputedStyle(holder).borderLeftColor === rgb : null,
        membersAccent: box && box.classList.contains('tree-group-children') && box.offsetParent
          ? getComputedStyle(box).borderLeftColor === rgb : null
      };
    });
  };
  // A hidden toggle keeps the width of a real one.
  window.__noToggleWidth = () => {
    const row = document.createElement('div'); row.className = 'tree-item group';
    row.innerHTML = '<div class="tree-toggle no-toggle"></div><div class="tree-icon folder"></div>';
    document.getElementById('tree').appendChild(row);
    const w = row.firstChild.offsetWidth;   // the layout's width; the rotation is only drawn
    row.remove();
    return w;
  };
  return true;
})()"""

OPEN = 'none'
TURNED = 'matrix(0, 1, -1, 0, 0, 0)'   # rotate(90deg)


def parent_of(path):
    return '/' if path.count('/') == 1 else path.rsplit('/', 1)[0]


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'],
                                  max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=7)
        try:
            check('sample-a.h5 loads', await load_samples(page, ['sample-a.h5']), ['sample-a.h5'])
            await page.ev(HELPERS)
            await asyncio.sleep(1)
            closed = await page.ev('__look()')
            check('a closed folder points ▶ and shows a closed icon',
                  (closed[0]['arrow'], closed[0]['openIcon']), (OPEN, False))

            await page.ev(f"__open({json.dumps(TOTAL)})")
            await page.ev("__open('/geosphere/near_field')")
            rows = {r['path']: r for r in await page.ev('__look()')}

            steps = {p: r['icon'] - rows[parent_of(p)]['icon'] for p, r in rows.items() if p != '/'}
            check('every row is one 20px column right of its parent, datasets too',
                  sorted(set(steps.values())), [20])
            check('  so the datasets in a folder start right of its icon, not left',
                  rows[TOTAL + '/Ra-226']['icon'] > rows[TOTAL]['icon'], True)
            check('a dataset lines up with the folders beside it',
                  (rows['/time']['icon'], rows['/geosphere/near_field/flux']['icon'] - rows['/geosphere/near_field']['icon']),
                  (rows['/biosphere']['icon'], 20))
            check('a hidden toggle keeps the width of a real one', await page.ev('__noToggleWidth()'), 16)
            check('an open folder points ▼ and shows an open icon',
                  {(r['arrow'], r['openIcon']) for r in rows.values() if r['group']}, {(TURNED, True)})

            # --- selection ----------------------------------------------------
            await page.ev(f"(async () => {{ __row({json.dumps(TOTAL + '/Ra-226')}, 'dataset').click(); await __wait(1500); }})()")
            rows = {r['path']: r for r in await page.ev('__look()')}
            check('the guide along a selected dataset\'s level turns accent, and no other',
                  sorted(p for p, r in rows.items() if r['guideAccent']), sorted(p for p in rows if p.startswith(TOTAL + '/')))

            await page.ev(f"(async () => {{ __row({json.dumps(TOTAL)}, 'group').click(); await __wait(1500); }})()")
            rows = {r['path']: r for r in await page.ev('__look()')}
            check('a selected group looks selected, and so does nothing else',
                  [p for p, r in rows.items() if r['selectedLook']], [TOTAL])
            check('  and the guide along its members turns accent',
                  [p for p, r in rows.items() if r['membersAccent']], [TOTAL])
            await page.ev(f"(async () => {{ __row({json.dumps(TOTAL)}, 'group').querySelector('.tree-toggle').click(); await __wait(600); }})()")
            rows = {r['path']: r for r in await page.ev('__look()')}
            check('closing the selected group leaves it looking selected',
                  (rows[TOTAL]['selectedLook'], rows[TOTAL]['arrow'], rows[TOTAL]['openIcon']), (True, OPEN, False))

            # --- search -------------------------------------------------------
            await page.ev("""(async () => {
              selectDataset('/time');
              await __wait(1200);
              const i = document.getElementById('treeSearch'); i.value = 'Ra';
              i.dispatchEvent(new Event('input', { bubbles: true }));
              await __wait(1500);
            })()""")
            rows = {r['path']: r for r in await page.ev('__look()')}
            above = ['/', '/biosphere', '/biosphere/vault_A', '/biosphere/vault_A/mire', TOTAL]
            check('a search opens the folders above a match, arrow and icon',
                  {(rows[p]['arrow'], rows[p]['openIcon']) for p in above}, {(TURNED, True)})
            check('  without making them look selected',
                  [p for p in above if rows[p]['selectedLook']], [])

            check('no console errors throughout', page.logs[:3], [])
        finally:
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget',
                                       'params': {'targetId': tid}}))
            await bws.recv()

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
