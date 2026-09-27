#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Text Explorer.

The simulated service-comments example opens from the URL and File >
Examples, and the platform sits in Analyze right after Tabulate; the launch
dialog has JMP's roles and options (a numeric column and an empty custom
regex are refused); the first call loads scikit-learn; the Summary Counts
and the Term and Phrase Lists are the engine's, and their counts are the
ones counted here in the page; a click on a term, a phrase or a word of the
cloud selects the rows that hold it; every red triangle opens; the word
cloud's words do not overlap and grow with the count; stemming, Add Stop
Word, Recode, Add Phrase and Show Text work from the menus, and Redo keeps
them; Latent Semantic Analysis gives the engine's singular values, with
documents linked to the rows both ways; Topic Analysis finds the example's
five themes; Save Document Term Matrix, Save Document Singular Vectors,
Save Topic Scores and Save Term Table make the columns and tables they
should; By and an ID column make the cases they should; a project keeps the
options with the column ids remapped; the Python script holds the
scikit-learn calls; hostile text stays text; Bootstrap reruns the report
headless; the defaults on 5,000 rows are timed; every (i) has a topic; the
reports draw in the dark theme and at phone width without a sideways page
scroll, and without script errors.

Start a server on the repository root and headless Chrome (README.md) on
SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-text.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import os
import sys
import time

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()
DOT = '\u00b7'


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.8)
        await page.shot(os.path.join(SHOTS, name))


def num(s):
    return float(str(s).replace('\u2212', '-').replace('%', '').replace('*', '').replace('<', ''))


# An item of an outline's red triangle: path is the labels down the submenus;
# wait: wait for the report to run again; which: the n-th outline so titled.
PICK = '''
(async (title, path, wait, which) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const heads = [...rep.body.querySelectorAll('.sm-ob-head')].filter(h => h.querySelector('h2, h3, h4').textContent.trim() === title || (title === '*top*' && h.querySelector('h2')));
  const head = heads[which || 0];
  if (!head) throw new Error('no outline ' + title);
  head.querySelector('.sm-ob-menu').click();
  await new Promise(r => setTimeout(r, 60));
  let done = null;
  for (let i = 0; i < path.length; i++) {
    const menus = [...document.querySelectorAll('.sm-menu')];
    const m = menus[menus.length - 1];
    const b = [...m.querySelectorAll('button')].find(x => x.querySelector('.sm-label').textContent === path[i]);
    if (!b) throw new Error('no item ' + path[i] + ' in ' + [...m.querySelectorAll('.sm-label')].map(x => x.textContent).join(' | '));
    if (i === path.length - 1 && wait) done = new Promise(res => rep.on('done', res));
    b.click();
    await new Promise(r => setTimeout(r, 80));
  }
  if (done) await done;
  return [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent);
})
'''


def pick_js(title, path, wait=True, which=0):
    return f'({PICK})({json.dumps(title)}, {json.dumps(path)}, {json.dumps(wait)}, {which})'


# The same for an item that opens a form: fill(dialog) runs on the form, then
# OK, then the report runs again (rerun false: a Save, no redraw).
PICK_FORM = '''
(async (title, path, fill, rerun) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  await (%s)(title, path, false, 0);
  for (let i = 0; i < 60 && !document.querySelector('.sm-dialog'); i++) await new Promise(r => setTimeout(r, 100));
  await new Promise(r => setTimeout(r, 100));
  const dlgs = [...document.querySelectorAll('.sm-dialog')];
  const d = dlgs[dlgs.length - 1];
  const done = rerun ? new Promise(res => rep.on('done', res)) : null;
  (new Function('d', fill))(d);
  d.querySelector('.sm-dialog-foot .primary').click();
  if (done) await done; else await new Promise(r => setTimeout(r, 1500));
  return [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent);
})
''' % PICK


def pick_form_js(title, path, fill='', rerun=True):
    return f'({PICK_FORM})({json.dumps(title)}, {json.dumps(path)}, {json.dumps(fill)}, {json.dumps(rerun)})'


TRIANGLES = '''
(async () => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  let items = 0, subs = 0;
  const errors = [];
  const btns = [...rep.body.querySelectorAll('.sm-ob-menu')];
  for (const btn of btns) {
    try {
      btn.click();
      await new Promise(r => setTimeout(r, 20));
      const menus = [...document.querySelectorAll('.sm-menu')];
      const top = menus[menus.length - 1];
      if (!top) { errors.push('no menu'); continue; }
      const bs = [...top.querySelectorAll('button')];
      items += bs.length;
      for (const b of bs.filter(x => x.classList.contains('sm-sub'))) {
        b.click();
        await new Promise(r => setTimeout(r, 20));
        const all = [...document.querySelectorAll('.sm-menu')];
        subs += all[all.length - 1].querySelectorAll('button').length;
      }
    } catch (e) { errors.push(String(e)); }
    SM.ui.closeMenus(0);
  }
  return { triangles: btns.length, items, subs, errors };
})()
'''

STATE = '''
(() => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  return { title: rep.title, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent),
           errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent.slice(0, 400)),
           warnings: [...rep.body.querySelectorAll('.sm-ob-warn')].map(e => e.textContent.slice(0, 300)), options: rep.spec.options, id: rep.spec.roles.text[0] };
})()
'''

# The comments of the example counted here: a word's occurrences and rows
# (whole words, any case), a phrase's (its words with anything but letters
# and digits between).
COUNT = r'''
((words, phrases) => {
  const t = SM.app.tables.find(t => t.name === 'Service comments');
  const vals = t.col('comment').values;
  const out = {};
  const go = (key, pat) => {
    const re = new RegExp(`(?<![\\p{L}\\p{N}'\\-])${pat}(?![\\p{L}\\p{N}'\\-])`, 'giu');
    let n = 0; const rows = [];
    vals.forEach((v, i) => { const m = String(v || '').match(re); if (m) { n += m.length; rows.push(i); } });
    out[key] = { n, rows };
  };
  for (const w of words) go(w, w);
  for (const p of phrases) go(p, p.split(' ').join('[\\W_]+'));
  return out;
})
'''

# The Term List (or Phrase List) of the last report: a row of it by its first cell.
LIST_ROW = '''
((caption, text, kind) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const tbl = [...rep.body.querySelectorAll('table.sm-rt')].find(t => t.caption && t.caption.textContent === caption);
  const tr = [...tbl.tBodies[0].rows].find(tr => tr.cells[0].textContent === text);
  if (!tr) throw new Error('no row ' + text);
  const ev = kind === 'context' ? new MouseEvent('contextmenu', { bubbles: true, clientX: 300, clientY: 300 })
    : new MouseEvent('click', { bubbles: true, shiftKey: kind === 'shift', ctrlKey: kind === 'ctrl' });
  tr.dispatchEvent(ev);
  return { selected: rep.table.selectedRows(), chosen: [...tbl.querySelectorAll('td.sm-tx-chosen')].filter(td => td.cellIndex === 0).map(td => td.textContent) };
})
'''


def list_row_js(caption, text, kind='click'):
    return f'({LIST_ROW})({json.dumps(caption)}, {json.dumps(text)}, {json.dumps(kind)})'


# Right click a term or phrase and choose from its menu; wait for the redraw.
CONTEXT = '''
(async (caption, text, label, fill) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  (%s)(caption, text, 'context');
  await new Promise(r => setTimeout(r, 60));
  const menus = [...document.querySelectorAll('.sm-menu')];
  const m = menus[menus.length - 1];
  const b = [...m.querySelectorAll('button')].find(x => x.querySelector('.sm-label').textContent === label);
  if (!b) throw new Error('no item ' + label + ' in ' + [...m.querySelectorAll('.sm-label')].map(x => x.textContent).join(' | '));
  const done = new Promise(res => rep.on('done', res));
  b.click();
  if (fill != null) {
    for (let i = 0; i < 50 && !document.querySelector('.sm-dialog'); i++) await new Promise(r => setTimeout(r, 100));
    const d = [...document.querySelectorAll('.sm-dialog')].pop();
    (new Function('d', fill))(d);
    d.querySelector('.sm-dialog-foot .primary').click();
  }
  await done;
  return [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent);
})
''' % LIST_ROW


def context_js(caption, text, label, fill=None):
    return f'({CONTEXT})({json.dumps(caption)}, {json.dumps(text)}, {json.dumps(label)}, {json.dumps(fill)})'


def rows_of(tbl, first=1):
    return {row[0]: row for row in tbl[first:]}


async def rerun(page):
    await page.ev('(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')


async def triangles(page, name, least):
    r = await page.ev(TRIANGLES)
    ok = isinstance(r, dict) and not r['errors'] and r['triangles'] >= least and r['items'] > r['triangles']
    check(f'every red triangle of {name} opens, with its submenus ({r["triangles"] if isinstance(r, dict) else r})', ok, True)
    if not ok:
        print('   ', r)


async def drawn(page, title_re):
    """Scroll a plot of the last report into view and wait until it is drawn."""
    return await page.ev('''(async (re) => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const p = rep.plots.find(p => new RegExp(re).test(p.opts.title || ''));
      if (!p) return false;
      p.box.scrollIntoView({ block: 'center' });
      for (let n = 0; n < 60 && !p.drawn; n++) await new Promise(r => setTimeout(r, 100));
      return p.drawn;
    })(%s)''' % json.dumps(title_re))


async def main():
    page = await open_page(f'{BASE}/smui.html?example=service-comments', height=1300)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "text").map(f => f.module + ": " + f.error)')
    check('text.py imports in Pyodide', failed, [])
    check('no script errors at load', page.errors, [])
    check('scikit-learn waits for its first use', await page.ev("(SM.engine.versions['scikit-learn'] || null)"), None)

    # ---- the example and the menu
    ex = await page.ev('''(() => {
      const t = SM.app.current;
      const file = SM.app.menuItems('File');
      const exs = file.find(i => i.label === 'Examples');
      const labels = (typeof exs.submenu === 'function' ? exs.submenu() : exs.submenu).map(i => i.label);
      const an = SM.app.menuItems('Analyze').filter(i => !i.separator).map(i => i.label);
      return { name: t.name, rows: t.nrows, cols: t.columns.map(c => c.name), types: t.columns.map(c => c.dataType + ' ' + c.modelingType), about: SM.io.EXAMPLES['service-comments'].about,
               inFile: labels.includes(SM.io.EXAMPLES['service-comments'].label), an };
    })()''')
    check('?example=service-comments opens the simulated comments', (ex['name'], ex['rows'], ex['cols']), ('Service comments', 1000, ['comment id', 'customer', 'channel', 'rating', 'comment']))
    check('the comment column is character', ex['types'][-1], 'character nominal')
    check('it is simulated, and its notes give the five themes', ex['about'].startswith('Simulated') and all(w in ex['about'] for w in ('delivery', 'quality', 'customer service', 'price', 'app')), True)
    check('it is in File > Examples', ex['inFile'], True)
    check('Analyze lists Text Explorer right after Tabulate', ex['an'].index('Text Explorer…') == ex['an'].index('Tabulate') + 1 if 'Tabulate' in ex['an'] else ex['an'].index('Text Explorer…') == ex['an'].index('Tabulate…') + 1, True)

    # ---- the launch dialog
    r = await page.ev('''(async () => {
      SM.app.launch('text');
      await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => { items.forEach(li => li.classList.remove('is-selected')); items.find(x => x.textContent === name).dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); };
      const role = (label) => [...dlg.querySelectorAll('.sm-role')].find(r => r.querySelector('.sm-btn').textContent === label);
      const ok = [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK');
      const roles = [...dlg.querySelectorAll('.sm-role .sm-btn')].map(b => b.textContent);
      const opts = [...dlg.querySelectorAll('.sm-launch-opts label')].map(l => [[...l.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim(), (l.querySelector('select') || l.querySelector('input')).value]);
      ok.click();
      const needOne = dlg.querySelector('.sm-launch-msg').textContent;
      pick('rating'); role('Text Columns').querySelector('.sm-btn').click();
      ok.click();
      const numeric = dlg.querySelector('.sm-launch-msg').textContent;
      [...role('Text Columns').querySelectorAll('li')].forEach(li => li.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })));
      pick('comment'); role('Text Columns').querySelector('.sm-btn').click();
      const rx = dlg.querySelector('.sm-tx-launch input[type=checkbox]');
      const hiddenBefore = dlg.querySelector('.sm-tx-regexrow').hidden;
      rx.click();
      const hiddenAfter = dlg.querySelector('.sm-tx-regexrow').hidden;
      ok.click();
      const emptyRegex = dlg.querySelector('.sm-launch-msg').textContent;
      rx.click();
      ok.click();
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res));
      return { roles, opts, needOne, numeric, hiddenBefore, hiddenAfter, emptyRegex, options: rep.spec.options, title: rep.title,
               outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent) };
    })()''', timeout=600)
    check('the launch roles are JMP\'s: Text Columns, ID, By', r['roles'], ['Text Columns', 'ID', 'By'])
    check('the options and their defaults', r['opts'], [['Language', 'english'], ['Maximum Words per Phrase', '4'], ['Maximum Number of Phrases', '1000'], ['Minimum Characters per Word', '1'],
                                                      ['Maximum Characters per Word', '100'], ['Stemming', 'none'], ['Tokenizing', 'regex']])
    check('a text column is needed', 'Text Columns: choose a column' in r['needOne'], True)
    check('a numeric column is refused', 'character columns; rating is numeric' in r['numeric'], True)
    check('Customize Regex shows its pattern box', (r['hiddenBefore'], r['hiddenAfter']), (True, False))
    check('an empty custom regex is refused', 'Customize Regex: give a regular expression' in r['emptyRegex'], True)
    check('the report and its outlines', (r['title'], r['outlines']), ('Text Explorer for comment', ['Text Explorer for comment', 'Summary Counts', 'Term and Phrase Lists']))
    check('the launch options reach the report', (r['options'].get('maxWords'), r['options'].get('stemming'), r['options'].get('customRegex')), (4, 'none', False))
    check('the first call loads scikit-learn', await page.ev("SM.engine.versions['scikit-learn'] || null"), '1.8.0')
    st = await page.ev(STATE)
    check('no errors in the report', (st['errors'], st['warnings']), ([], []))
    await shot(page, 'text-01-report.png')

    # ---- the numbers: the engine's, and counts made here
    eng = await page.ev('''(async () => { const t = SM.app.tables.find(t => t.name === 'Service comments');
      return await SM.engine.call('text.explore', { table: t.id, rows: null, column: 'comment' }, t); })()''')
    sc = await page.ev(table_under_js('Summary Counts', 0))
    check('the Summary Counts table\'s columns', sc[0], ['Number of Terms', 'Number of Cases', 'Total Tokens', 'Tokens per Case', 'Portion Non-empty'])
    s = eng['summary']
    check('Summary Counts = the engine\'s', [num(x) for x in sc[1]], [s['terms'], s['cases'], s['tokens'], round(s['tokens_per_case'], 6), s['portion_nonempty']])
    check('1,000 cases, each a row', s['cases'], 1000)
    terms = await page.ev(table_under_js('Term and Phrase Lists', 0))
    phr = await page.ev(table_under_js('Term and Phrase Lists', 1))
    check('the Term List: Term and Count, as the engine lists them', ([row[:2] for row in terms[1:]], terms[0]), ([[x['term'], str(x['count'])] for x in eng['terms']][:1000], ['Term', 'Count']))
    check('the Phrase List: Phrase, Count and N', (phr[0], [row for row in phr[1:6]]), (['Phrase', 'Count', 'N'], [[x['phrase'], str(x['count']), str(x['n'])] for x in eng['phrases'][:5]]))
    check('Total Tokens is the sum of the Term List', sum(int(row[1]) for row in terms[1:]), s['tokens'])
    words = ['delivery', 'courier', 'refund', 'checkout', 'discount', 'agent', 'kettle']
    phrases = ['customer service', 'value for money', 'late delivery']
    here = await page.ev(f'({COUNT})({json.dumps(words)}, {json.dumps(phrases)})')
    tl = {x['term']: (x['count'], eng['term_rows'][k]) for k, x in enumerate(eng['terms'])}
    check('the counts of seven words = those counted here in the page', {w: tl[w][0] for w in words}, {w: here[w]['n'] for w in words})
    check('and the rows that hold them', all(tl[w][1] == here[w]['rows'] for w in words), True)
    pl = {x['phrase']: (x['count'], eng['phrase_rows'][k]) for k, x in enumerate(eng['phrases'])}
    check('three phrases\' counts and rows = those counted here', {p: (pl[p][0], pl[p][1] == here[p]['rows']) for p in phrases}, {p: (here[p]['n'], True) for p in phrases})

    # ---- linking: a click on a term selects its rows
    r = await page.ev(list_row_js('Term List', 'courier'))
    check('a click on a term selects the rows that hold it', r['selected'], here['courier']['rows'])
    check('and marks it in the list', r['chosen'], ['courier'])
    r = await page.ev(list_row_js('Term List', 'refund', 'shift'))
    check('shift adds a term: the rows of both', r['selected'], sorted(set(here['courier']['rows']) | set(here['refund']['rows'])))
    r = await page.ev(list_row_js('Term List', 'courier', 'ctrl'))
    check('ctrl toggles one off', (r['selected'], r['chosen']), (here['refund']['rows'], ['refund']))
    r = await page.ev(list_row_js('Phrase List', 'value for money'))
    check('a click on a phrase selects its rows (and clears the terms)', (r['selected'], r['chosen']), (here['value for money']['rows'], ['value for money']))
    await page.ev('SM.app.reports[SM.app.reports.length - 1].table.select([])')

    # ---- the word cloud
    await page.ev(pick_js('*top*', ['Display Options', 'Show Word Cloud']))
    wc = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const svg = rep.body.querySelector('svg.sm-tx-cloud');
      svg.scrollIntoView({ block: 'center' });
      await new Promise(r => setTimeout(r, 200));
      const ws = [...svg.querySelectorAll('text.sm-tx-word')];
      const boxes = ws.map(w => { const b = w.getBBox(); return [b.x, b.y, b.x + b.width, b.y + b.height]; });
      let overlaps = 0;
      for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i], b = boxes[j];
        if (a[0] < b[2] - 1 && b[0] < a[2] - 1 && a[1] < b[3] - 1 && b[1] < a[3] - 1) overlaps++;
      }
      const sizes = ws.map(w => Number(w.getAttribute('font-size')));
      const texts = ws.map(w => w.lastChild.textContent);
      const tips = ws.map(w => w.querySelector('title').textContent);
      ws[4].dispatchEvent(new MouseEvent('click', { bubbles: true }));
      const sel = rep.table.selectedRows();
      const chosenWord = ws[4].classList.contains('is-chosen');
      const listChosen = [...rep.body.querySelectorAll('table.sm-rt td.sm-tx-chosen')].filter(td => td.cellIndex === 0).map(td => td.textContent);
      rep.table.select([]);
      const fill = getComputedStyle(ws[0]).fill;
      return { n: ws.length, overlaps, sizes, texts, tips, sel, chosenWord, listChosen, fill, width: svg.getBoundingClientRect().width };
    })()''')
    top100 = [x['term'] for x in eng['terms'][:100]]
    check('the Word Cloud: the 100 most frequent terms, in count order', (wc['n'], wc['texts']), (100, top100))
    check('no two words overlap', wc['overlaps'], 0)
    check('a word is never smaller than a less frequent one', all(a >= b - 1e-9 for a, b in zip(wc['sizes'], wc['sizes'][1:])), True)
    check('the largest word is the most frequent, the smallest the least', (wc['sizes'][0] == max(wc['sizes']), wc['sizes'][-1] == min(wc['sizes'])), (True, True))
    check('each word tells its count on hover', wc['tips'][0], f'{top100[0]}: {eng["terms"][0]["count"]}')
    check('a click on a word selects its rows, and marks it in the cloud and the list', (wc['sel'], wc['chosenWord'], wc['listChosen']), (eng['term_rows'][4], True, [top100[4]]))
    await page.ev(pick_js('Word Cloud', ['Layout', 'Ordered']))
    od = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1];
      const ws = [...rep.body.querySelectorAll('svg.sm-tx-cloud text.sm-tx-word')].map(w => ({ t: w.lastChild.textContent, x: Number(w.getAttribute('x')), y: Number(w.getAttribute('y')) }));
      const lines = [...new Set(ws.map(w => w.y))];
      return { n: ws.length, reading: ws.slice().sort((a, b) => a.y - b.y || a.x - b.x).map(w => w.t) }; })()''')
    check('Ordered: the words alphabetically, in lines', od['reading'], sorted(top100, key=lambda w: w.lower()))
    await page.ev(pick_js('Word Cloud', ['Layout', 'Centered']))
    await page.ev(pick_js('Word Cloud', ['Coloring', 'Arbitrary Colors']))
    fills = await page.ev('[...SM.app.reports[SM.app.reports.length - 1].body.querySelectorAll("svg.sm-tx-cloud text.sm-tx-word")].slice(0, 6).map(w => w.getAttribute("fill"))')
    check('Arbitrary Colors: the light theme\'s text colours', fills, ['#1c5cab', '#b4501f', '#0f7a55', '#4a3aa7', '#6a6a00', '#b8336a'])
    await page.ev(pick_form_js('Word Cloud', ['Coloring', 'By Column…'], "const s = d.querySelector('select'); s.value = [...s.options].find(o => o.textContent === 'rating').value;"))
    lg = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const l = rep.body.querySelector('.sm-tx-legend');
      const w = [...rep.body.querySelectorAll('svg.sm-tx-cloud text.sm-tx-word')].find(w => w.lastChild.textContent === 'disappointed');
      const g = [...rep.body.querySelectorAll('svg.sm-tx-cloud text.sm-tx-word')].find(w => w.lastChild.textContent === 'recommended');
      return { legend: l ? l.textContent : null, low: w ? w.getAttribute('fill') : null, high: g ? g.getAttribute('fill') : null, tip: w ? w.querySelector('title').textContent : '' }; })()''')
    check('By Column: a legend of the mean rating', bool(lg['legend']) and lg['legend'].startswith('Mean rating'), True)
    rgb = lambda c: [int(v) for v in c[4:-1].split(',')]   # noqa: E731
    check('"disappointed" is bluer (a low rating), "recommended" redder (a high one)', bool(lg['low'] and lg['high']) and (rgb(lg['low'])[2] > rgb(lg['low'])[0], rgb(lg['high'])[0] > rgb(lg['high'])[2]) == (True, True), True)
    check('and each word tells its mean rating on hover', 'mean rating' in lg['tip'], True)
    await shot(page, 'text-02-cloud.png')
    await triangles(page, 'the report', 3)

    # ---- stemming, stop words, recodes, phrases; Show Text; Redo keeps them
    await page.ev(pick_js('*top*', ['Term Options', 'Stemming', 'Stem for Combining']))
    await page.ev(pick_js('*top*', ['Display Options', 'Show Stem Report']))
    t2 = await page.ev(table_under_js('Term and Phrase Lists', 0))
    stems = {row[0]: int(row[1]) for row in t2[1:] if row[0].endswith(DOT)}
    check('Stem for Combining: stemmed terms end in a dot', len(stems) > 3 and 'return' + DOT in stems, True)
    sr = await page.ev(table_under_js('Stem Report', 0))
    srow = rows_of(sr)['return' + DOT]
    check('the Stem Report lists the words of a stem, with their counts adding up', sum(int(p.rsplit('(', 1)[1][:-1]) for p in srow[3].split(', ')), stems['return' + DOT])
    st = await page.ev(STATE)
    cid = st['id']
    await page.ev(context_js('Term List', 'delivery', 'Add Stop Word'))
    t3 = await page.ev(table_under_js('Term and Phrase Lists', 0))
    check('Add Stop Word (right click): the term is gone', 'delivery' in [row[0] for row in t3[1:]], False)
    st = await page.ev(STATE)
    check('the stop word is kept with the report, as JSON text', st['options'].get(f'{cid}|stopAdd'), '["delivery"]')
    before = {row[0]: int(row[1]) for row in t3[1:]}
    await page.ev(context_js('Term List', 'parcel', 'Recode…', "d.querySelector('.sm-form input').value = 'package';"))
    t4 = {row[0]: int(row[1]) for row in (await page.ev(table_under_js('Term and Phrase Lists', 0)))[1:]}
    check('Recode (right click): parcel is counted as package', (t4.get('package'), 'parcel' in t4), (before['parcel'] + before.get('package', 0), False))
    await page.ev(context_js('Phrase List', 'customer service', 'Add Phrase'))
    t5 = {row[0]: int(row[1]) for row in (await page.ev(table_under_js('Term and Phrase Lists', 0)))[1:]}
    check('Add Phrase: the phrase is a term, its words lose those occurrences', (t5.get('customer service'), t5.get('customer', 0), t5.get('servic' + DOT, t5.get('service', 0))),
          (here['customer service']['n'], t4.get('customer', 0) - here['customer service']['n'], t4.get('servic' + DOT, t4.get('service', 0)) - here['customer service']['n']))
    await rerun(page)
    st = await page.ev(STATE)
    check('Redo keeps the stemming, the stop word, the recode and the phrase', (st['options'].get(f'{cid}|stemming'), st['options'].get(f'{cid}|stopAdd'), st['options'].get(f'{cid}|recodes'), st['options'].get(f'{cid}|phrasesAdd')),
          ('combine', '["delivery"]', '{"parcel":"package"}', '["customer service"]'))
    md = await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1];
      await (%s)('*top*', ['Term Options', 'Manage Stop Words…'], false, 0);
      for (let i = 0; i < 50 && !document.querySelector('.sm-dialog'); i++) await new Promise(r => setTimeout(r, 100));
      const d = [...document.querySelectorAll('.sm-dialog')].pop(); const v = d.querySelector('textarea').value;
      [...d.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Cancel').click(); return v; })()''' % PICK)
    check('Manage Stop Words shows the added stop word', md, 'delivery')
    tx = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      (%s)('Term List', 'refund', 'context');
      await new Promise(r => setTimeout(r, 60));
      const m = [...document.querySelectorAll('.sm-menu')].pop();
      [...m.querySelectorAll('button')].find(x => x.querySelector('.sm-label').textContent === 'Show Text…').click();
      for (let i = 0; i < 50 && !document.querySelector('.sm-tx-dialog'); i++) await new Promise(r => setTimeout(r, 100));
      const d = document.querySelector('.sm-tx-dialog');
      const items = [...d.querySelectorAll('.sm-tx-texts li')];
      const out = { n: items.length, marks: [...d.querySelectorAll('mark')].map(m => m.textContent.toLowerCase()), title: d.querySelector('h2').textContent, lead: d.querySelector('.sm-dialog-lead').textContent };
      [...d.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close').click();
      return out;
    })()''' % LIST_ROW)
    check('Show Text: every row that holds the term, the word marked', (tx['title'], tx['n'], set(tx['marks'])), ('Show Text: refund', len(here['refund']['rows']), {'refund'}))
    await shot(page, 'text-03-options.png')

    # ---- Latent Semantic Analysis
    await page.ev(pick_form_js('*top*', ['Latent Semantic Analysis, SVD…']), timeout=600)
    st = await page.ev(STATE)
    check('Latent Semantic Analysis: its outlines, no errors', (all(o in st['outlines'] for o in ('Latent Semantic Analysis (SVD)', 'Singular Values', 'SVD Plots')), st['errors']), (True, []))
    check('its specification is kept: JMP\'s weightings and centering', st['options'].get(f'{cid}|lsa'), {'maxTerms': 1000, 'minFreq': 4, 'weighting': 'tfidf', 'k': 100, 'centering': 'centered'})
    lsa = await page.ev('''(async (cid) => { const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      return await SM.engine.call('text.lsa', { table: t.id, rows: null, column: 'comment', stemming: 'combine', stop_add: ['delivery'], recodes: { parcel: 'package' }, phrases: ['customer service'],
        weighting: 'tfidf', centering: 'centered', min_freq: 4, max_terms: 1000, k: 100, seed: rep.spec.options.seedDrawn, show: 2 }, t); })(%s)''' % json.dumps(cid))
    svt = await page.ev(table_under_js('Singular Values', 0))
    check('Singular Values: Number, Singular Value, Percent, Cum Percent', svt[0], ['Number', 'Singular Value', 'Percent', 'Cum Percent'])
    check.near('the first singular value is the engine\'s', num(svt[1][1]), lsa['singular'][0]['value'], tol=1e-6)
    check('as many as the engine gives (cut to the matrix)', len(svt) - 1, lsa['k'])
    check.near('Cum Percent adds up the Percents', num(svt[5][3]), sum(x['percent'] for x in lsa['singular'][:5]), tol=1e-3)
    ok = await drawn(page, '^Document singular vectors')
    check('the document plot is drawn', ok, True)
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const p = rep.plots.find(p => /^Document singular vectors/.test(p.opts.title));
      const q = rep.plots.find(p => /^Term singular vectors/.test(p.opts.title));
      p._click({ points: [{ curveNumber: 0, pointNumber: 7 }], event: {} });
      const sel = t.selectedRows();
      t.select([p.rows[0][3], p.rows[0][11]]);
      const sp = p.box.data[0].selectedpoints;
      const terms = q.traces[0].hovertext.map(h => h.split(': ')[0]);
      const refundRows = q.rows[0][terms.indexOf('refund')];
      t.select(refundRows);
      const qsel = (q.box.data[0].selectedpoints || []).map(i => terms[i]);
      t.select([]);
      return { sel, want: [p.rows[0][7]], sp, n: p.traces[0].x.length, x0: p.traces[0].x[0], terms: terms.length, qsel, labels: q.traces[0].text.filter(Boolean).length };
    })()''')
    check('one point per document, at the engine\'s coordinates', (r['n'], abs(r['x0'] - lsa['docs'][0][0]) < 1e-9), (1000, True))
    check('a click on a document selects its row', r['sel'], r['want'])
    check('rows selected in the table highlight their documents', r['sp'], [3, 11])
    check('the term plot: one point per term of the matrix', r['terms'], lsa['n_terms'])
    check('selecting the rows of a term highlights it (and the terms that share rows with it)', 'refund' in r['qsel'], True)
    check('the terms furthest out are named, a few', 3 <= r['labels'] <= 14, True)
    await shot(page, 'text-04-lsa.png')

    # ---- Topic Analysis: the example's five themes come out
    await page.ev(pick_form_js('*top*', ['Topic Analysis, Rotated SVD…']), timeout=600)
    st = await page.ev(STATE)
    check('Topic Analysis, Rotated SVD: its outlines', all(o in st['outlines'] for o in ('Topic Analysis, Rotated SVD', 'Top Loadings by Topic', 'Variance Explained', 'Topic Loadings', 'Topic Scores')), True)
    tops = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1];
      return [...rep.body.querySelectorAll('.sm-tx-topics table')].map(t => [...t.querySelectorAll('tbody tr')].slice(0, 5).map(tr => tr.cells[0].textContent)); })()''')
    check('ten topics, ten terms each', (len(tops), await page.ev('[...SM.app.reports[SM.app.reports.length - 1].body.querySelectorAll(".sm-tx-topics table")].every(t => t.tBodies[0].rows.length === 10)')), (10, True))
    THEMES = {'delivery': {'late', 'package', 'arrived', 'courier', 'tracking', 'waiting', 'wait' + DOT, 'week' + DOT, 'dai' + DOT, 'fast'},
              'quality': {'quality', 'broken', 'damaged', 'sturdy', 'solid', 'lamp', 'chair', 'kettle', 'jacket', 'return' + DOT, 'refund', 'cracked'},
              'service': {'customer service', 'support', 'agent', 'helpful', 'rude', 'hold', 'staff', 'phone', 'answered', 'calls', 'problem'},
              'price': {'price' + DOT, 'value', 'money', 'expensive', 'discount', 'overpriced', 'cheap', 'code'},
              'app': {'app', 'website', 'checkout', 'crash' + DOT, 'crashing', 'log', 'account', 'payment', 'slow', 'easy', 'update', 'updat' + DOT}}
    hits = {th: any(len(set(tp) & ws) >= 2 for tp in tops) for th, ws in THEMES.items()}
    if not check('the five themes of the example each lead a topic (two of its words in a topic\'s top five)', hits, {th: True for th in THEMES}):
        print('   ', tops)
    tv = await page.ev(table_under_js('Variance Explained', 0))
    check('Variance Explained: largest topic first', [num(row[1]) for row in tv[1:]] == sorted((num(row[1]) for row in tv[1:]), reverse=True), True)
    await page.ev(pick_form_js('Topic Analysis, Rotated SVD', ['Specifications…'], "const s = d.querySelector('select'); s.value = 'nmf';"), timeout=600)
    st = await page.ev(STATE)
    check('Specifications: NMF instead', ('Topic Analysis, Non-negative Matrix Factorization' in st['outlines'], 'Topic Sizes' in st['outlines'], st['errors']), (True, True, []))
    nmf = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1];
      return [...rep.body.querySelectorAll('.sm-tx-topics table')].map(t => [...t.querySelectorAll('tbody tr')].slice(0, 5).map(tr => tr.cells[0].textContent)); })()''')
    hits = {th: any(len(set(tp) & ws) >= 2 for tp in nmf) for th, ws in THEMES.items()}
    if not check('NMF finds the five themes too', hits, {th: True for th in THEMES}):
        print('   ', nmf)
    await page.ev('(() => { window.__ldaSteps = []; SM.engine.on("progress", (p) => { if (p.what === "lda") window.__ldaSteps.push(p.done + "/" + p.total); }); })()')
    await page.ev(pick_form_js('Topic Analysis, Non-negative Matrix Factorization', ['Specifications…'], "const s = d.querySelector('select'); s.value = 'lda';"), timeout=900)
    st = await page.ev(STATE)
    lda = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1];
      return { steps: window.__ldaSteps, probs: [...rep.body.querySelectorAll('.sm-tx-topics table')].map(t => t._rt.columns[1].label), fitting: [...rep.body.querySelectorAll('.sm-ob-note')].some(n => /fitting|iteration/.test(n.textContent)) }; })()''')
    check('Specifications: LDA, each topic\'s term probabilities', ('Topic Analysis, Latent Dirichlet Allocation' in st['outlines'], set(lda['probs']), st['errors']), (True, {'Probability'}, []))
    check('LDA reports its iterations while it runs, and the note goes when it is done', (lda['steps'], lda['fitting']), ([f'{i}/10' for i in range(1, 11)], False))
    await page.ev(pick_form_js('Topic Analysis, Latent Dirichlet Allocation', ['Specifications…'], "const s = d.querySelector('select'); s.value = 'varimax';"), timeout=600)
    await shot(page, 'text-05-topics.png')

    # ---- Save
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      (%s)('Term List', 'refund'); (%s)('Term List', 'courier', 'ctrl');
      const n0 = t.columns.length;
      return n0;
    })()''' % (LIST_ROW, LIST_ROW))
    await page.ev(pick_form_js('*top*', ['Save Document Term Matrix…'], '', rerun=False))
    dt = await page.ev('''(() => { const t = SM.app.reports[SM.app.reports.length - 1].table; const a = t.col('refund'), b = t.col('courier');
      return a && b ? { a: a.values, b: b.values, notes: a.notes } : null; })()''')
    check('Save Document Term Matrix: a column for each chosen term, named by it', dt is not None, True)
    if dt:
        check('Binary: 1 where the row\'s text holds the term, else 0', (dt['a'] == [1.0 if i in set(here['refund']['rows']) else 0.0 for i in range(1000)],
                                                                         dt['b'] == [1.0 if i in set(here['courier']['rows']) else 0.0 for i in range(1000)]), (True, True))
    await page.ev(pick_form_js('Latent Semantic Analysis (SVD)', ['Save Document Singular Vectors…'], "d.querySelector('.sm-form input').value = '3';", rerun=False))
    sv = await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const v = await SM.engine.call('text.vectors', { table: t.id, rows: null, column: 'comment', stemming: 'combine', stop_add: ['delivery'], recodes: { parcel: 'package' }, phrases: ['customer service'],
        kind: 'svd', weighting: 'tfidf', centering: 'centered', min_freq: 4, max_terms: 1000, k: 100, seed: rep.spec.options.seedDrawn, count: 3 }, t);
      const cols = ['Doc Vec1', 'Doc Vec2', 'Doc Vec3'].map(n => t.col(n));
      return { have: cols.map(c => !!c), same: cols.every((c, k) => c && v.rows.every((r, i) => Math.abs(c.values[r] - v.values[k][i]) < 1e-12)) }; })()''')
    check('Save Document Singular Vectors: Doc Vec1 to 3, the engine\'s U S', (sv['have'], sv['same']), ([True] * 3, True))
    await page.ev(pick_js('Topic Analysis, Rotated SVD', ['Save Topic Scores'], wait=False))
    await asyncio.sleep(1.5)
    ts = await page.ev('''(() => { const t = SM.app.reports[SM.app.reports.length - 1].table; const cs = t.columns.filter(c => /^Topic Score \\d+$/.test(c.name));
      const v = cs[0] ? cs[0].values.filter(Number.isFinite) : []; const m = v.reduce((a, b) => a + b, 0) / v.length; const s2 = v.reduce((a, b) => a + (b - m) ** 2, 0) / (v.length - 1);
      return { n: cs.length, mean: m, var: s2 }; })()''')
    check('Save Topic Scores: ten columns, standardized scores', (ts['n'], abs(ts['mean']) < 1e-9, abs(ts['var'] - 1) < 1e-9), (10, True, True))
    tt = await page.ev('''(async () => { const n = SM.app.tables.length; await (%s)('*top*', ['Save Term Table'], false, 0); await new Promise(r => setTimeout(r, 300));
      const t = SM.app.tables[SM.app.tables.length - 1]; const out = { made: SM.app.tables.length === n + 1, name: t.name, cols: t.columns.map(c => c.name), rows: t.nrows, first: [t.col('Term').values[0], t.col('Count').values[0]] };
      SM.app.showTab(SM.app.tabOf(SM.app.reports[SM.app.reports.length - 1])); return out; })()''' % PICK)
    t6 = await page.ev(table_under_js('Term and Phrase Lists', 0))
    check('Save Term Table: a table of the terms, counts and cases', (tt['made'], tt['name'], tt['cols'], tt['rows'], tt['first']), (True, 'comment terms', ['Term', 'Count', 'Cases'], len(t6) - 1, [t6[1][0], int(t6[1][1])]))
    script = await page.ev('SM.app.reports[SM.app.reports.length - 1].pythonScript()')
    check('the Python script holds the scikit-learn calls and the stemmer', all(x in script for x in ('CountVectorizer(analyzer=', 'ENGLISH_STOP_WORDS', 'def read_terms(', 'class PorterStemmer', 'def lsa_svd(', 'PCA(', 'def varimax(')), True)
    check('and no copy of the stop words', 'amoungst' in script, False)

    # ---- a project keeps the options, the column ids remapped
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(r => r.platform.id === 'text');
      const t = rep.table;
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] }));
      SM.app.loadProject(j);
      const back = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => { if (!back.body.classList.contains('is-running') && back.body.querySelector('.sm-ob')) res(); else back.on('done', res); });
      const c = back.table.col('comment');
      const heads = [...back.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent);
      const tbl = [...back.body.querySelectorAll('table.sm-rt')].find(x => x.caption && x.caption.textContent === 'Term List');
      const out = { newTable: back.table !== t, newId: c.id !== rep.spec.roles.text[0], stop: back.spec.options[c.id + '|stopAdd'], lsa: back.spec.options[c.id + '|lsa'], heads, same: JSON.stringify(heads) === JSON.stringify([...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent)),
                    errors: back.body.querySelectorAll('.sm-ob-error').length, delivery: [...tbl.tBodies[0].rows].some(tr => tr.cells[0].textContent === 'delivery') };
      SM.app.closeTable(back.table);
      await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop();
      const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close');
      if (yes) yes.click();
      return out;
    })()''', timeout=900)
    check('an opened project has its own table, with new column ids', (r['newTable'], r['newId']), (True, True))
    check('and keeps the stop word and the LSA by the new id', (r['stop'], (r['lsa'] or {}).get('weighting')), ('["delivery"]', 'tfidf'))
    check('and draws the same outlines, without errors, the stop word still left out', (r['same'], r['errors'], r['delivery']), (True, 0, False))

    # ---- By: one explorer per channel; an ID: one case per customer
    await page.ev('SM.app.showTable(SM.app.tables.find(t => t.name === "Service comments").id)')
    rep = await page.ev(open_report_js('text', {'text': ['comment'], 'by': ['channel']}, {}), timeout=600)
    check('By channel: one analysis per channel', [o for o in rep['outlines'] if o.startswith('Text Explorer for')], ['Text Explorer for comment channel=app', 'Text Explorer for comment channel=phone', 'Text Explorer for comment channel=web'])
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const tbls = [...rep.body.querySelectorAll('table.sm-rt')].filter(t => t.dataset.rtKey === 'summary');
      const combined = SM.report.combineRT(tbls, 'x');
      const ch = rep.table.col('channel').values;
      return { n: tbls.length, rows: combined.nrows, cases: tbls.map(t => t._rt.rows[0].cases), want: ['app', 'phone', 'web'].map(v => ch.filter(x => x === v).length) };
    })()''')
    check('each group counts its own rows; the Summary Counts combine', (r['n'], r['rows'], r['cases']), (3, 3, r['want']))
    rep = await page.ev(open_report_js('text', {'text': ['comment'], 'id': ['customer']}, {'lsa': {'k': 5}}), timeout=600)
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const cust = rep.table.col('customer').values;
      const p = rep.plots.find(p => /^Document singular vectors/.test(p.opts.title));
      return { cases: [...rep.body.querySelectorAll('table.sm-rt')].find(t => t.dataset && t._rt && t._rt.rows[0] && 'cases' in t._rt.rows[0])._rt.rows[0].cases, want: new Set(cust).size,
               note: [...rep.body.querySelectorAll('.sm-ob-note')].some(n => /A case is a document: the rows with the same customer/.test(n.textContent)), points: p ? p.traces[0].x.length : null, groups: p ? Array.isArray(p.rows[0][0]) : null };
    })()''')
    check('an ID column: one case per customer, and it says so', (r['cases'], r['note']), (r['want'], True))
    check('the document plot has a point per customer, each for its rows', (r['points'], r['groups']), (r['want'], True))
    check('no errors in the By and ID reports', (await page.ev(STATE))['errors'], [])

    # ---- hostile text stays text
    r = await page.ev(r'''(async () => {
      window.__pwned = 0;
      const vals = ['<img src=x onerror="window.__pwned=1"> hello world', '<b>bold</b> %{x} hello', '<script>window.__pwned=2</script> hello world', '<img src=x onerror="window.__pwned=1"> again world'];
      SM.app.addTable(new SM.Table({ name: 'Hostile', columns: [{ name: 'note', dataType: 'character', values: vals }] }));
      const t = SM.app.tables[SM.app.tables.length - 1];
      const rep = SM.app.openReport(SM.platforms.get('text'), { roles: { text: [t.col('note').id] }, options: { customRegex: true, regex: '\\S+', cloud: true, lsa: { minFreq: 1, k: 2 } } }, t);
      await new Promise(res => rep.on('done', res));
      const p = rep.plots.find(p => /^Term singular vectors/.test(p.opts.title));
      const d = rep.plots.find(p => /^Document singular vectors/.test(p.opts.title));
      const terms = [...rep.body.querySelectorAll('table.sm-rt')].find(x => x.caption && x.caption.textContent === 'Term List');
      return { injected: rep.body.querySelectorAll('img, b, script').length, pwned: window.__pwned, cells: [...terms.tBodies[0].rows].map(tr => tr.cells[0].textContent),
               cloud: [...rep.body.querySelectorAll('svg.sm-tx-cloud text')].map(w => w.lastChild.textContent), hover: p ? p.traces[0].hovertext : null, dhover: d ? d.traces[0].hovertext : null,
               errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent) };
    })()''', timeout=600)
    check('hostile text: no element made from it, nothing run', (r['injected'], r['pwned'], r['errors']), (0, 0, []))
    check('the terms show as typed', all(x in r['cells'] for x in ('<b>bold</b>', '%{x}', '<img', 'onerror="window.__pwned=1">')), True)
    check('and in the word cloud', '<b>bold</b>' in r['cloud'], True)
    check('Plotly gets them escaped (term and document hover)', (any('&lt;b&gt;bold&lt;/b&gt;' in h for h in r['hover']), any('<b>' in h for h in r['hover']), any('&lt;img' in h for h in r['dhover'])), (True, False, True))
    await page.ev('SM.app.showTable(SM.app.tables.find(t => t.name === "Service comments").id)')

    # ---- Bootstrap reruns the report headless
    await page.ev(open_report_js('text', {'text': ['comment']}, {'lsa': {'k': 10}}), timeout=600)
    b = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const tbl = [...rep.body.querySelectorAll('table.sm-rt')].find(t => t._rt && t._rt.columns.some(c => c.label === 'Total Tokens'));
      const col = tbl._rt.columns.find(c => c.label === 'Total Tokens');
      const n0 = rep.plots.length;
      const out = await SM.bootstrap.run(tbl, col, { B: 4, seed: 3, show: false });
      return { rows: out ? out.nrows : null, vals: out ? out.columns[1].values : null, notes: out ? out.notes : '', plots: rep.plots.length === n0, errors: rep.body.querySelectorAll('.sm-ob-error').length };
    })()''', timeout=900)
    check('Bootstrap of Total Tokens: the report and 4 samples, none failed, the report untouched', (b['rows'], all(isinstance(v, (int, float)) for v in b['vals']), 'failed' in b['notes'], b['plots'], b['errors']), (5, True, False, True, 0))

    # ---- the defaults on 5,000 rows
    await page.ev('''(() => {
      const src = SM.app.tables.find(t => t.name === 'Service comments').col('comment').values;
      const vals = Array.from({ length: 5000 }, (_, i) => `${src[(i * 7) % 1000]} ${src[(i * 13 + 5) % 1000]}`);
      SM.app.addTable(new SM.Table({ name: 'Comments 5000', columns: [{ name: 'comment', dataType: 'character', values: vals }] }));
    })()''')
    t0 = time.time()
    rep = await page.ev(open_report_js('text', {'text': ['comment']}, {}), timeout=600)
    t1 = time.time()
    await page.ev(f'''(async () => {{ const rep = SM.app.reports[SM.app.reports.length - 1]; rep.spec.options[rep.spec.roles.text[0] + '|lsa'] = {{}}; const d = new Promise(res => rep.on('done', res)); rep.run(); await d; }})()''', timeout=600)
    t2 = time.time()
    await page.ev(f'''(async () => {{ const rep = SM.app.reports[SM.app.reports.length - 1]; rep.spec.options[rep.spec.roles.text[0] + '|topics'] = {{}}; rep.spec.options[rep.spec.roles.text[0] + '|cloud'] = true; const d = new Promise(res => rep.on('done', res)); rep.run(); await d; }})()''', timeout=600)
    t3 = time.time()
    print(f'      5,000 rows in Pyodide: the report {t1 - t0:.1f} s; with LSA {t2 - t1:.1f} s; with topics and the cloud {t3 - t2:.1f} s')
    st = await page.ev(STATE)
    check('5,000 rows: no errors', st['errors'], [])
    check('5,000 rows: the default report in under 8 s, LSA and topics in under 15 s each', (t1 - t0 < 8, t2 - t1 < 15, t3 - t2 < 15), (True, True, True))

    # ---- the (i) topics and Help
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    helps = await page.ev('(() => { SM.app.showHelp("p-text"); const row = document.getElementById("help-p-text"); return row ? row.textContent : null; })()')
    check('the platform has its line in Help, with scikit-learn\'s classes', bool(helps) and 'CountVectorizer' in helps and 'TruncatedSVD' in helps, True)
    topics = await page.ev('Object.keys(SM.platforms.get("text").topics)')
    check('its topics', sorted(topics), sorted(['p:text', 'p:text:regex', 'p:text:summary', 'p:text:lists', 'p:text:cloud', 'p:text:stems', 'p:text:manage', 'p:text:lsa', 'p:text:topics', 'p:text:dtm']))

    # ---- dark theme and phone width
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "text" && r.table.name === "Service comments")))')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(2.5)
    st = await page.ev('''(() => { const rs = SM.app.reports.filter(r => r.platform.id === 'text'); return { errors: rs.flatMap(r => [...r.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent)) }; })()''')
    check('the dark theme redraws the reports without errors', st['errors'], [])
    fills = await page.ev('''(async () => { const rep = SM.app.reports.find(r => r.platform.id === "text" && r.table.name === "Service comments"); const id = rep.spec.roles.text[0];
      rep.spec.options[id + '|cloud'] = true; rep.spec.options[id + '|cloudColor'] = 'colors'; const d = new Promise(res => rep.on('done', res)); rep.run(); await d;
      return [...rep.body.querySelectorAll('svg.sm-tx-cloud text.sm-tx-word')].slice(0, 6).map(w => w.getAttribute('fill')); })()''')
    check('the word cloud takes the dark theme\'s colours', fills, ['#6da7ec', '#f08a5d', '#3cc494', '#a99ff0', '#d0b24a', '#ee86ad'])
    await shot(page, 'text-06-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    await page.ev('(async () => { const rep = SM.app.reports.find(r => r.platform.id === "text" && r.table.name === "Service comments"); SM.app.showTab(SM.app.tabOf(rep)); const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')
    await asyncio.sleep(1.0)
    r = await page.ev('''(() => {
      const rep = SM.app.reports.find(r => r.platform.id === "text" && r.table.name === "Service comments");
      const body = rep.body.getBoundingClientRect();
      const boxes = rep.plots.filter(p => p.drawn).map(p => p.box.getBoundingClientRect().right);
      const cloud = rep.body.querySelector('svg.sm-tx-cloud').getBoundingClientRect();
      const lists = [...rep.body.querySelectorAll('.sm-tx-list')].map(l => l.getBoundingClientRect().right);
      return { page: document.documentElement.scrollWidth <= innerWidth + 1, plots: boxes.every(x => x <= body.right + 1), n: boxes.length, cloud: cloud.right <= body.right + 1 && cloud.width > 200,
               lists: lists.every(x => x <= body.right + 1), body: rep.body.scrollWidth <= rep.body.clientWidth + 1 };
    })()''')
    check('no horizontal page scroll at phone width', r['page'], True)
    check('the graphs, the word cloud and the lists fit the phone\'s width', (r['plots'], r['n'] >= 1, r['cloud'], r['lists'], r['body']), (True, True, True, True, True))
    await shot(page, 'text-07-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
