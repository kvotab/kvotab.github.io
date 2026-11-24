#!/usr/bin/env python3
"""What the tree's search finds, typed into the search box.

A term is searched in the names of the tree, with * for any characters. A term
with a slash is searched in full paths instead, and so is a term with a dot, a
space or a star that no name holds as written. There the star stands for
slashes too: 'vault*mire' finds /biosphere/vault_A/mire as 'vault*/mire' does.
Until 2026-11-24 a star was tried on names alone, and 'Kd*Po' found nothing in
a file whose Po datasets sit in Kd groups, while 'Kd*/Po' found all eleven.

A star term that some name holds stays a name search, for 'Pu*9' is a search
for Pu-239: on full paths it would also find every name with a 9 below a group
whose name holds 'pu' (input_data).

A search also loads the folders its matches are in, at most 50 matches a file.
Those used to be found by trying the term on whole paths too, so the 50 went
on items the filter then hid -- everything below a match, and every name under
a group whose name held the letters -- and matches further on were never
loaded: in a results file 'Pu*9' showed 5 of its 49 Pu-239 items. The file's
names are now asked first, and its paths only when no name holds the term.
A file built in the page has a group searched first that holds 120 such
items, and three Pu-239 datasets in folders of their own beyond it.

Uses the committed fixture sample-a.h5. Start the server and the browser as in
README.md, then

    python3 resources/tests/rb/test-search.py

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
NUCLIDES = ['Ac-227', 'Cl-36', 'I-129', 'Nb-94', 'Ni-59', 'Ra-226', 'Se-79', 'Th-230', 'U-238']
BELOW_MIRE = sorted(['/biosphere/vault_A/mire', TOTAL] + [f'{TOTAL}/{n}' for n in NUCLIDES])

HELPERS = r"""(() => {
  window.__wait = (ms) => new Promise(r => setTimeout(r, ms));
  // Type a term into the search box as a person does: one input event, then
  // the debounce, the search of the file for groups not yet loaded, and the
  // filter again once they are.
  window.__search = async (term) => {
    const box = document.getElementById('treeSearch');
    box.value = term;
    box.dispatchEvent(new Event('input', { bubbles: true }));
    await __wait(600);
    for (let i = 0; i < 100 && window._searchExpansionState.inProgress; i++) await __wait(100);
    await __wait(600);
    const tree = document.getElementById('tree');
    const rows = [...tree.querySelectorAll('.tree-item')];
    return {
      pathSearch: isPathSearchTerm(term),
      matches: rows.filter(r => r.classList.contains('search-match')).map(r => r.getAttribute('data-path')).sort(),
      shown: rows.filter(r => !r.classList.contains('search-hidden')).map(r => r.getAttribute('data-path')).sort(),
      marked: Object.fromEntries(rows.filter(r => r.querySelector('.search-highlight'))
        .map(r => [r.getAttribute('data-path'), r.querySelector('.search-highlight').textContent]))
    };
  };
  return true;
})()"""

# Three Pu-239 datasets in folders of their own under a_res, and z_input, which
# the search walks first (it is the last pushed), holding a Pu-239 group of 60
# members and 60 names with a 9 in them. On whole paths 'Pu-239' holds for the
# group's members and 'Pu*9' for all 120 ('pu' in z_input); in their own names
# for none of them.
NOISE_BUILD = r"""(async () => {
  await waitForH5Wasm();
  const { FS, File } = window.h5wasm;
  const path = '/noise-' + Date.now() + '.h5';
  const w = new File(path, 'w');
  const data = Float64Array.from([1, 2, 3]);
  const put = (g, name) => g.create_dataset({ name, data, shape: [3], dtype: '<f8' });
  try {
    const res = w.create_group('a_res');
    for (const k of ['one', 'two', 'three']) put(res.create_group(k), 'Pu-239');
    const z = w.create_group('z_input');
    const pu = z.create_group('Pu-239');
    for (let i = 0; i < 60; i++) put(pu, 'g' + String(i).padStart(2, '0'));
    const t = z.create_group('tables');
    for (let i = 0; i < 60; i++) put(t, 'x9' + String(i).padStart(2, '0'));
  } finally {
    w.close();
  }
  loadedFileBuffers['noise.h5'] = FS.readFile(path).slice().buffer;
  loadedFiles['noise.h5'] = new File(path, 'r');
  fileStates['noise.h5'] = true;
  if (!fileOrder.includes('noise.h5')) fileOrder.push('noise.h5');
  await updateTabs(true);
  await new Promise(r => setTimeout(r, 1500));
  return fileOrder.slice();
})()"""

PU239 = ['/a_res/one/Pu-239', '/a_res/three/Pu-239', '/a_res/two/Pu-239', '/z_input/Pu-239']


async def noise_session(bws):
    """A fresh page for each term, so each search starts on a tree with only
    its top level loaded, as a file just opened has."""
    out = {}
    for term in ('Pu-239', 'Pu*9', 'input*x95'):
        tid, page = await open_page(bws, settle=7)
        try:
            out['files'] = await page.ev(NOISE_BUILD, timeout=120)
            await page.ev(HELPERS)
            out['loaded'] = await page.ev("!findTreeItem('/a_res/one', { root: document.getElementById('tree') })")
            out[term] = await page.ev(f"__search({json.dumps(term)})", timeout=120)
            out.setdefault('logs', []).extend(page.logs[:3])
        finally:
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget',
                                       'params': {'targetId': tid}}))
            await bws.recv()
    return out


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'],
                                  max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=7)
        try:
            check('sample-a.h5 loads', await load_samples(page, ['sample-a.h5']), ['sample-a.h5'])
            await page.ev(HELPERS)
            await asyncio.sleep(1)
            check('the folders below the top are not loaded yet',
                  await page.ev(f"!findTreeItem({json.dumps(TOTAL)}, {{ root: document.getElementById('tree') }})"), True)

            # --- a star where a slash is --------------------------------------
            star = await page.ev("__search('vault*mire')", timeout=60)
            check('a star term no name holds is searched in full paths', star['pathSearch'], True)
            check('  so vault*mire finds the mire group and all below it, loaded for it',
                  star['matches'], BELOW_MIRE)
            slash = await page.ev("__search('vault*/mire')", timeout=60)
            check('  as vault*/mire does', star['matches'], slash['matches'])
            check('  and shows the same rows', star['shown'], slash['shown'])
            check('the mire group\'s name marks what follows the star, as with the slash',
                  (star['marked'].get('/biosphere/vault_A/mire'), slash['marked'].get('/biosphere/vault_A/mire')),
                  ('mire', 'mire'))
            check('  and the folders above it are shown unmarked',
                  [p for p in ('/', '/biosphere', '/biosphere/vault_A') if p in star['marked']], [])
            check('  though shown', all(p in star['shown'] for p in ('/biosphere', '/biosphere/vault_A')), True)

            # --- a star within a name -----------------------------------------
            name = await page.ev("__search('e*9')", timeout=60)
            check('a star term a name holds stays a name search', name['pathSearch'], False)
            check('  e*9 finds Se-79 alone, not I-129 or Ni-59 below biosphere',
                  name['matches'], [f'{TOTAL}/Se-79'])
            check('  and marks the term in it', name['marked'], {f'{TOTAL}/Se-79': 'e-79'})

            ra = await page.ev("__search('Ra*6')", timeout=60)
            check('Ra*6 finds Ra-226', (ra['pathSearch'], ra['matches']), (False, [f'{TOTAL}/Ra-226']))

            # --- what has not moved -------------------------------------------
            plain = await page.ev("__search('mire')", timeout=60)
            check('a plain term finds names only', (plain['pathSearch'], plain['matches']),
                  (False, ['/biosphere/vault_A/mire']))
            dot = await page.ev("__search('mire.total')", timeout=60)
            check('a dot no name holds is a slash', (dot['pathSearch'], dot['matches']),
                  (True, sorted([TOTAL] + [f'{TOTAL}/{n}' for n in NUCLIDES])))
            none = await page.ev("__search('vault*zzz')", timeout=60)
            check('a star term nothing holds finds nothing', (none['pathSearch'], none['matches']), (True, []))
            cleared = await page.ev("__search('')", timeout=60)
            check('clearing the search shows every row again',
                  (cleared['matches'], await page.ev("document.querySelectorAll('#tree .tree-item.search-hidden').length")),
                  ([], 0))

            check('no console errors throughout', page.logs[:3], [])
        finally:
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget',
                                       'params': {'targetId': tid}}))
            await bws.recv()

        # --- the 50 matches a file a search loads -------------------------
        noise = await noise_session(bws)
        check('a file built in the page opens, its folders not loaded', (noise['files'], noise['loaded']),
              (['noise.h5'], True))
        check('Pu-239 finds all four, past the 60 members of the first Pu-239 group',
              noise['Pu-239']['matches'], PU239)
        check('Pu*9 finds the same four, past 120 items whose paths alone hold it',
              (noise['Pu*9']['pathSearch'], noise['Pu*9']['matches']), (False, PU239))
        check('  and marks each Pu-239', set(noise['Pu*9']['marked'].values()), {'Pu-239'})
        check('a star term no name holds still finds its paths: input*x95',
              (noise['input*x95']['pathSearch'], noise['input*x95']['matches']),
              (True, [f'/z_input/tables/x95{i}' for i in range(10)]))
        check('no console errors in those pages', noise['logs'], [])

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
