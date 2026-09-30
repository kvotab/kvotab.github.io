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
documents linked to the rows both ways (titled as JMP's, Centered and
Scaled TF IDF by default, with the eigenvalues); Topic Analysis finds the
example's five themes, each topic's terms by the absolute loading (JMP's
order); a recode of a stemmed term by right click recodes its words before
the stemming (JMP's order), Show Text marking them all; Latent Class Analysis (JMP's outlines, a real click
on a cluster, the MDS map, Color by Cluster, Save Probabilities and Save
Cluster), Cluster Terms and Cluster Documents (the SVD plots coloured by
their clusters, + by a real click, a cluster's rows, the saved clusters),
the SVD Scatterplot Matrix (documents below, terms above, linked), Term
Selection of the rating (the engine's terms, a real click, the saved
scores), Sentiment Analysis (vaderSentiment fetched from PyPI, a real click
on the negative documents, the saved scores), the phrase list's Select
Contains, Select Contained and Containing Phrases, and Save Stacked DTM for
Association read by Association Analysis; Save Document Term Matrix, Save Document Singular Vectors, Save
Topic Scores and Save Term Table make the columns and tables they should; By
and an ID column make the cases they should; a project keeps the options
with the column ids remapped; the Python script holds the scikit-learn
calls; hostile text stays text; Bootstrap reruns the report headless; the
defaults on 5,000 rows are timed; the new graphs' code draws the page's
MDS map, dendrogram, scatterplot matrix and bars; every (i) has a topic; the launch dialog's
(i) gives every role, option and Customize Regex field its help, and the
forms' (i) each of their fields; the reports draw in the dark theme and at
phone width without a sideways page scroll, and without script errors.

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
from test_charts import GRAPHS_JS, maxdiff, more_from_outputs, page_probe_more, points_of, run_graph, strip_show

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



# ---- the (i) of a launch dialog, a form or an outline: its sections, as
# { headings, sections: { heading: [[name, text], ...] } }. kind 'dialog':
# arg is JS that opens the dialog (clickPath(rep, title, path) and wait(ms)
# are at hand; it is not awaited, as a form resolves only when it closes);
# kind 'slot': arg is JS giving the element that holds the (i).
INFO = r'''
(async (kind, arg, part) => {
  const wait = (ms) => new Promise(r => setTimeout(r, ms));
  const clickPath = async (rep, title, path) => {
    SM.app.showTab(SM.app.tabOf(rep));
    const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => { const t = h.querySelector('h2, h3, h4'); return t && (title === '*top*' ? t.tagName === 'H2' : t.textContent.trim() === title); });
    if (!head) throw new Error('no outline ' + title);
    head.querySelector('.sm-ob-menu').click();
    await wait(60);
    for (const label of path) {
      const menus = [...document.querySelectorAll('.sm-menu')];
      const b = [...menus[menus.length - 1].querySelectorAll('button')].find(x => x.querySelector('.sm-label') && x.querySelector('.sm-label').textContent === label);
      if (!b) throw new Error('no item ' + label);
      b.click();
      await wait(80);
    }
  };
  const read = () => {
    const p = document.querySelector('.info-panel');
    if (!p) return null;
    const out = { title: p.querySelector('.info-panel-title').textContent, headings: [], sections: {} };
    let cur = '';
    for (const n of p.querySelector('.info-panel-body').children) {
      if (n.tagName === 'H3') { cur = n.textContent; out.headings.push(cur); }
      else if (n.tagName === 'DL') (out.sections[cur] = out.sections[cur] || []).push(...[...n.querySelectorAll(':scope > dt')].map(dt => [dt.textContent, dt.nextElementSibling ? dt.nextElementSibling.textContent : '']));
    }
    return out;
  };
  let dlg = null, btn = null;
  window.__infoError = null;
  if (kind === 'slot') {
    const node = (new Function('return ' + arg))();
    btn = node && (node.matches('.info-btn') ? node : node.querySelector('.info-btn'));
  } else {
    const before = new Set(document.querySelectorAll('.sm-dialog'));
    (new Function('clickPath', 'wait', 'return (async () => {' + arg + '})()'))(clickPath, wait).catch((e) => { window.__infoError = String(e); });
    for (let i = 0; i < 100 && !dlg && !window.__infoError; i++) { await wait(50); dlg = [...document.querySelectorAll('.sm-dialog')].find(d => !before.has(d)) || null; }
    if (!dlg) { SM.ui.closeMenus(0); return { error: window.__infoError || 'no dialog' }; }
    await wait(120);
    btn = dlg.querySelector('.sm-dialog-head .info-btn');
  }
  if (!btn) { if (dlg) dlg.querySelector('.sm-dialog-x').click(); return { error: 'no (i)' }; }
  // the inputs of a part (JS giving an element; a dialog's is dlg): each one's aria-label and label text
  const box = part ? (new Function('dlg', 'return ' + part))(dlg) : null;
  const inputs = box ? [...box.querySelectorAll('input, select, textarea')].map(e => [e.getAttribute('aria-label') || '', e.closest('label') ? e.closest('label').textContent.trim() : '']) : [];
  btn.click();
  await wait(150);
  const out = read() || { error: 'no panel' };
  out.inputs = inputs;
  out.key = KvotInfo.current();
  out.noTopic = KvotInfo.audit().noTopic;
  KvotInfo.close();
  if (dlg) { dlg.querySelector('.sm-dialog-x').click(); await wait(120); }
  return out;
})
'''


def info_js(kind, arg, part=None):
    return f'({INFO})({json.dumps(kind)}, {json.dumps(arg)}, {json.dumps(part)})'


def unexplained(info, heading=None):
    """The inputs of the part that no entry of the panel (of one section) names."""
    secs = info.get('sections') or {}
    names = [n for h, cs in secs.items() if heading is None or h == heading for n, _ in cs]
    return [a or t for a, t in info.get('inputs', []) if not any(a.startswith(n) or t.startswith(n) for n in names)]


async def dialog_help(page, opener, platform_id, name):
    """A launch dialog's (i): one Roles and one Options section, every role and
    option with its help (a role's followed by what it takes), and no (i)
    without a topic while the dialog is open. Returns the panel."""
    d = await page.ev(info_js('dialog', opener))
    if not isinstance(d, dict) or 'sections' not in d:
        check(f'{name}: the launch dialog\'s (i) opens', d, 'a panel')
        return {'headings': [], 'sections': {}}
    want = await page.ev(f'(() => {{ const L = SM.platforms.get({json.dumps(platform_id)}).launch; return {{ roles: L.roles.map(r => [r.label, r.help || ""]), options: (L.options || []).map(o => [o.label, o.help || ""]) }}; }})()')
    roles, opts = dict(d['sections'].get('Roles', [])), dict(d['sections'].get('Options', []))
    check(f'{name}: the launch dialog\'s (i) has one Roles and one Options section', (d['headings'].count('Roles'), d['headings'].count('Options')), (1, 1 if want['options'] else 0))
    check('... every role with its help, then what it takes', [(lab, bool(h) and roles.get(lab, '').startswith(h) and roles[lab].endswith(')')) for lab, h in want['roles']], [(lab, True) for lab, _ in want['roles']])
    check('... every option with its help', [(lab, bool(h) and opts.get(lab) == h) for lab, h in want['options']], [(lab, True) for lab, _ in want['options']])
    check('... and every (i) has a topic while it is open', d['noTopic'], [])
    return d


async def form_help(page, opener, fields, name):
    """A form's (i) lists each of its fields with what it is for."""
    f = await page.ev(info_js('dialog', opener))
    got = dict((f.get('sections') or {}).get('Fields', [])) if isinstance(f, dict) else {}
    check(f'{name}: the form\'s (i) lists its fields, each with its help', [(x, len(got.get(x, '')) > 30) for x in fields], [(x, True) for x in fields])
    check('... and every (i) has a topic while it is open', f.get('noTopic') if isinstance(f, dict) else f, [])
    return f


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
    check('the options and their defaults (JMP\'s: 5000 phrases, words of 1 to 50 characters; the Snowball stemmer)', r['opts'], [['Language', 'english'], ['Maximum Words per Phrase', '4'], ['Maximum Number of Phrases', '5000'], ['Minimum Characters per Word', '1'],
                                                      ['Maximum Characters per Word', '50'], ['Stemming', 'none'], ['Stemmer', 'snowball'], ['Tokenizing', 'regex']])
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
    READING = '''(() => { const rep = SM.app.reports[SM.app.reports.length - 1];
      const ws = [...rep.body.querySelectorAll('svg.sm-tx-cloud text.sm-tx-word')].map(w => ({ t: w.lastChild.textContent, x: Number(w.getAttribute('x')), y: Number(w.getAttribute('y')) }));
      return { n: ws.length, reading: ws.slice().sort((a, b) => a.y - b.y || a.x - b.x).map(w => w.t) }; })()'''
    st = await page.ev(STATE)
    check('the word cloud\'s layout is JMP\'s default, Ordered: in lines, the most frequent first', ((await page.ev(READING))['reading'], st['options'].get(f'{st["id"]}|cloudLayout')), (top100, None))
    await page.ev(pick_js('Word Cloud', ['Layout', 'Alphabetical']))
    od = await page.ev(READING)
    check('Alphabetical: the words alphabetically, in lines', od['reading'], sorted(top100, key=lambda w: w.lower()))
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
    check('Latent Semantic Analysis: its outlines (titled as JMP\'s: SVD Centered and Scaled TF IDF), no errors', (all(o in st['outlines'] for o in ('SVD Centered and Scaled TF IDF', 'Singular Values', 'SVD Plots')), st['errors']), (True, []))
    check('its specification is kept: JMP\'s weighting and centering, TF IDF and Centered and Scaled', st['options'].get(f'{cid}|lsa'), {'maxTerms': 1000, 'minFreq': 4, 'weighting': 'tfidf', 'k': 100, 'centering': 'scaled'})
    lsa = await page.ev('''(async (cid) => { const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      return await SM.engine.call('text.lsa', { table: t.id, rows: null, column: 'comment', stemming: 'combine', stop_add: ['delivery'], recodes: { parcel: 'package' }, phrases: ['customer service'],
        weighting: 'tfidf', centering: 'scaled', min_freq: 4, max_terms: 1000, k: 100, seed: rep.spec.options.seedDrawn, show: 2 }, t); })(%s)''' % json.dumps(cid))
    svt = await page.ev(table_under_js('Singular Values', 0))
    check('Singular Values: Number, Singular Value, Eigenvalue, Percent, Cum Percent (as JMP\'s)', svt[0], ['Number', 'Singular Value', 'Eigenvalue', 'Percent', 'Cum Percent'])
    check.near('the first eigenvalue is the engine\'s', num(svt[1][2]), lsa['singular'][0]['eigen'], tol=1e-6)
    check.near('the first singular value is the engine\'s', num(svt[1][1]), lsa['singular'][0]['value'], tol=1e-6)
    check('as many as the engine gives (cut to the matrix)', len(svt) - 1, lsa['k'])
    check.near('Cum Percent adds up the Percents', num(svt[5][4]), sum(x['percent'] for x in lsa['singular'][:5]), tol=1e-3)
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
    lds = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1];
      return [...rep.body.querySelectorAll('.sm-tx-topics table')].map(t => t._rt.rows.map(r => r.loading)); })()''')
    check('Top Loadings by Topic: each topic\'s terms by the absolute loading, the largest first (JMP\'s order)', all([abs(v) for v in ld] == sorted((abs(v) for v in ld), reverse=True) for ld in lds), True)
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
    await page.ev(pick_form_js('SVD Centered and Scaled TF IDF', ['Save Document Singular Vectors…'], "d.querySelector('.sm-form input').value = '3';", rerun=False))
    sv = await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const v = await SM.engine.call('text.vectors', { table: t.id, rows: null, column: 'comment', stemming: 'combine', stop_add: ['delivery'], recodes: { parcel: 'package' }, phrases: ['customer service'],
        kind: 'svd', weighting: 'tfidf', centering: 'scaled', min_freq: 4, max_terms: 1000, k: 100, seed: rep.spec.options.seedDrawn, count: 3 }, t);
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
    check('the Python script holds the scikit-learn calls and the stemmer (Snowball\'s, the default)', all(x in script for x in ('CountVectorizer(analyzer=', 'ENGLISH_STOP_WORDS', 'def read_terms(', 'class SnowballStemmer', 'def lsa_svd(', 'PCA(', 'def varimax(')), True)
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

    # ---- the analyses added: LCA, the clusters, the scatterplot matrix, Term Selection, Sentiment, the phrase list, the stacked DTM
    await new_analyses(page)

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

    # ---- the graphs' matplotlib code, run in the page
    await chart_code(page)
    await new_chart_code(page)

    # ---- the (i) topics and Help
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    helps = await page.ev('(() => { SM.app.showHelp("p-text"); const row = document.getElementById("help-p-text"); return row ? row.textContent : null; })()')
    check('the platform has its line in Help, with scikit-learn\'s classes', bool(helps) and 'CountVectorizer' in helps and 'TruncatedSVD' in helps, True)
    topics = await page.ev('Object.keys(SM.platforms.get("text").topics)')
    check('its topics', sorted(topics), sorted(['p:text', 'p:text:regex', 'p:text:summary', 'p:text:lists', 'p:text:cloud', 'p:text:stems', 'p:text:manage', 'p:text:lsa', 'p:text:topics', 'p:text:dtm',
                                                'p:text:lca', 'p:text:cluster', 'p:text:spm', 'p:text:termsel', 'p:text:sentiment']))

    # ---- the (i) explains every input: the launch dialog and Customize Regex, the forms of the red triangles
    await page.ev('SM.app.showTable(SM.app.tables.find(t => t.name === "Service comments").id)')
    d = await page.ev(info_js('dialog', "SM.app.launch('text')", "dlg.querySelector('.sm-tx-launch')"))
    check('Text Explorer: the launch dialog\'s (i) explains Customize Regex and its pattern', ([c[0] for c in d.get('sections', {}).get('Customize Regex', [])], len(d.get('inputs', [])), unexplained(d, 'Customize Regex')), (['Customize Regex', 'Regular expression'], 2, []))
    await dialog_help(page, "SM.app.launch('text')", 'text', 'Text Explorer')
    big = 'SM.app.reports.at(-1)'
    for path, fields in ((['Latent Semantic Analysis, SVD…'], ['Maximum Number of Terms', 'Minimum Term Frequency', 'Weighting', 'Number of Singular Vectors', 'Centering and Scaling']),
                         (['Topic Analysis, Rotated SVD…'], ['Number of Topics', 'Method', 'Maximum Number of Terms', 'Minimum Term Frequency', 'Weighting (LDA takes the counts)', 'Centering and Scaling (rotated SVD)']),
                         (['Save Document Term Matrix…'], ['Terms', 'Maximum Number of Terms', 'Minimum Term Frequency', 'Weighting']),
                         (['Term Options', 'Manage Stop Words…'], ['Stop Words']), (['Term Options', 'Manage Recodes…'], ['Recodes']), (['Term Options', 'Manage Phrases…'], ['Phrases'])):
        await form_help(page, f"await clickPath({big}, '*top*', {json.dumps(path)});", fields, path[-1])
    await form_help(page, f"await clickPath({big}, 'SVD Centered and Scaled TF IDF', ['Save Document Singular Vectors…']);", ['Number of singular vectors to save'], 'Save Document Singular Vectors…')
    await form_help(page, f"await clickPath({big}, 'Word Cloud', ['Number of Terms…']);", ['The most frequent terms to show'], 'Word Cloud: Number of Terms…')
    lists = await page.ev('SM.info.get("p:text:lists")')
    check('Term and Phrase Lists\' (i) explains the Show Text dialog\'s buttons', [c[0] for sec in lists['sections'] if sec.get('heading') == 'Show Text' for c in sec['choices']], ['Select These Rows', 'Close'])

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
    r = await page.ev(f'''(async () => {{ const rep = {NEW}; SM.app.showTab(SM.app.tabOf(rep)); const d = new Promise(res => rep.on("done", res)); rep.run(); await d;
      await __gr.drawAll(rep); const body = rep.body.getBoundingClientRect();
      return {{ plots: rep.plots.filter(p => p.drawn).map(p => p.box.getBoundingClientRect().right).every(x => x <= body.right + 1), n: rep.plots.filter(p => p.drawn).length,
               lists: [...rep.body.querySelectorAll('.sm-tx-list, .sm-tx-scroll')].every(l => l.getBoundingClientRect().right <= body.right + 1), page: document.documentElement.scrollWidth <= innerWidth + 1,
               errors: [...rep.body.querySelectorAll('.sm-ob-error')].length }}; }})()''', timeout=900)
    check('the new analyses at phone width in the dark theme: the graphs and tables fit, no sideways scroll, no errors', (r['plots'], r['n'] >= 6, r['lists'], r['page'], r['errors']), (True, True, True, True, 0))
    await shot(page, 'text-09-new-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


# ---- the graphs' matplotlib code ------------------------------------------------------------------------------------------
# Every graph has its code block right under it (the word cloud's under its box), ending in plt.show(); the block
# runs in the page's own Python (the notebook's runner) and draws the page's graph: the cloud's words where the page
# put them, at its font sizes, in its colours (Uniform, Arbitrary Colors, By Column); the singular values' bars;
# the documents' and terms' coordinates with the terms the page names; the topic scores and their axes' terms; in a
# By group with rows excluded, with an ID column.
OPEN_TX = r'''(async (roles, options, byName) => {
  const t = SM.app.tables.find((x) => x.name === 'Service comments');
  SM.app.showTab(SM.app.tabOf(t));
  const ids = {};
  for (const [k, names] of Object.entries(roles)) ids[k] = names.map((n) => t.col(n).id);
  if (byName) options.cloudBy = t.col(byName).id;
  const rep = SM.app.openReport(SM.platforms.get('text'), { roles: ids, options }, t);
  await new Promise((res) => rep.on('done', res));
  const g = await __gr.graphs(rep);
  const titles = Object.fromEntries(rep.plots.map((p) => [p.opts.title, p.box.layout && p.box.layout.title ? p.box.layout.title.text : null]));
  const clouds = [...rep.body.querySelectorAll('svg.sm-tx-cloud')].map((svg) => {
    const box = svg.closest('.sm-tx-cloudbox'), n = box.nextElementSibling;
    return { viewBox: svg.getAttribute('viewBox').split(' ').map(Number), legend: !!box.querySelector('.sm-tx-legend'),
      code: n && n.matches('details.sm-code') ? n.querySelector('code').textContent : null,
      words: [...svg.querySelectorAll('text.sm-tx-word')].map((w) => [w.lastChild.textContent, Number(w.getAttribute('x')), Number(w.getAttribute('y')), Number(w.getAttribute('font-size')), getComputedStyle(w).fill]) };
  });
  return { g, titles, clouds, undrawn: __gr.take(), errors: [...rep.body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent) };
})'''

CLOUD_PROBE = r'''
def _smui_cloud():
    import json as _j
    import matplotlib.pyplot as _plt
    from matplotlib.colors import to_hex as _hex
    fig = _plt.figure(_plt.get_fignums()[0])
    ax = fig.axes[0]
    return {"size": [float(v) for v in fig.get_size_inches()], "xlim": [float(v) for v in ax.get_xlim()], "ylim": [float(v) for v in ax.get_ylim()],
            "words": [[t.get_text(), float(t.get_position()[0]), float(t.get_position()[1]), float(t.get_fontsize()), _hex(t.get_color())] for t in ax.texts],
            "bars": [a.get_xlabel() for a in fig.axes[1:]]}
print("SMUI-CLOUD " + __import__("json").dumps(_smui_cloud()))
'''


def hexcol(c):
    """A CSS colour (#rrggbb or rgb(r, g, b)) as #rrggbb."""
    if isinstance(c, str) and c.startswith('rgb('):
        return '#' + ''.join(f'{int(v):02x}' for v in c[4:-1].split(','))
    return c


async def run_cloud(page, code):
    out = await page.ev(f"__gr.run({json.dumps(strip_show(code) + chr(10) + CLOUD_PROBE)}, SM.app.tables.find((x) => x.name === 'Service comments'))", timeout=600)
    if isinstance(out, str):
        return None, out
    text = ''.join(o.get('text', '') for o in out.get('outputs') or [] if o.get('type') == 'stream' and o.get('name') == 'stdout')
    for line in text.split('\n'):
        if line.startswith('SMUI-CLOUD '):
            return json.loads(line[len('SMUI-CLOUD '):]), None
    errs = [f"{o.get('ename')}: {o.get('evalue')}" for o in out.get('outputs') or [] if o.get('type') == 'error']
    return None, errs[0] if errs else 'the probe printed nothing'


async def run_more(page, g):
    out = await page.ev(f"__gr.run({json.dumps(page_probe_more(g['code']))}, SM.app.tables.find((x) => x.name === 'Service comments'))", timeout=600)
    if isinstance(out, str):
        return None, out
    got, err = more_from_outputs(out.get('outputs'))
    return (got['figures'] if got else None), err


async def chart_code(page):
    await page.ev(GRAPHS_JS)
    lsa = {'k': 10, 'minFreq': 4}
    runs = [('Uniform, Centered; LSA; rotated SVD topics', {'text': ['comment']}, {'cloud': True, 'cloudLayout': 'centered', 'lsa': lsa, 'topics': {'k': 4}}, None),
            ('Arbitrary Colors, Ordered; an ID; NMF topics', {'text': ['comment'], 'id': ['customer']}, {'cloud': True, 'cloudLayout': 'ordered', 'cloudColor': 'colors', 'cloudN': 60, 'lsa': {'k': 4, 'weighting': 'logfreq', 'centering': 'uncentered'}, 'topics': {'k': 3, 'method': 'nmf'}}, None),
            ('By Column (rating); By channel, rows excluded; LDA', {'text': ['comment'], 'by': ['channel']}, {'cloud': True, 'cloudColor': 'column', 'lsa': lsa, 'topics': {'k': 3, 'method': 'lda'}}, 'rating'),
            ('By Column with an ID (the rows without one count for the mean)', {'text': ['comment'], 'id': ['customer']}, {'cloud': True, 'cloudColor': 'column', 'cloudN': 40}, 'rating'),
            ('Arbitrary Grays, 30 terms, stemmed, Alphabetical', {'text': ['comment']}, {'cloud': True, 'cloudColor': 'grays', 'cloudN': 30, 'stemming': 'combine', 'cloudLayout': 'alphabetical'}, None)]
    table_js = "SM.app.tables.find((x) => x.name === 'Service comments')"
    ex, cust6 = None, None
    for tag, roles, options, by_col in runs:
        if 'rows excluded' in tag:
            ex = await page.ev(f'(() => {{ const t = {table_js}; const ch = t.col("channel").values; const ex = ["app", "phone", "web"].map((v) => ch.indexOf(v)).concat([3]); t.setState(ex, "excluded", true); return ex; }})()')
        if 'with an ID' in tag:   # a row without a customer, whose rating still counts for the mean
            cust6 = await page.ev(f'(() => {{ const t = {table_js}; const v = t.col("customer").values[6]; t.setCell(6, "customer", null); return v; }})()')
        r = await page.ev(f'({OPEN_TX})({json.dumps(roles)}, {json.dumps(options)}, {json.dumps(by_col)})', timeout=900)
        if isinstance(r, str):
            check(f'the graphs\' code ({tag}): the report', r, None)
            continue
        check(f'the graphs\' code ({tag}): no errors, every graph drawn', (r['errors'], r['undrawn']), ([], []))
        for g in r['g']:
            check(f'the graphs\' code ({tag}): {g["label"]}: its code block is right under it, ending in plt.show()', bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()', True)
        for c in r['clouds']:
            check(f'the graphs\' code ({tag}): the word cloud: its code block is right under its box, ending in plt.show()', bool(c['code']) and c['code'].rstrip().split('\n')[-1] == 'plt.show()', True)
        for g in r['g']:
            lab = f'the graphs\' code ({tag}): {g["label"]}'
            terms_plot = g['label'].startswith('Term singular vectors')
            F, err = await (run_more(page, g) if terms_plot else run_graph(page, g, table_js))
            check(f'{lab}: runs in the page', err, None)
            if not F:
                continue
            F = F[0]
            ax = F['axes'][0]
            t0 = g['traces'][0]
            if g['label'].startswith('Singular values'):
                check.near(f'{lab}: the bars: the percents, each at its number', max(maxdiff([b['w'] for b in ax['bars']], t0['x']), maxdiff([b['y'] + b['h'] / 2 for b in ax['bars']], t0['y'])), 0, 1e-9)
                check(f'{lab}: the first at the top', ax['yinverted'], True)
            else:
                got = ax['scatter'][0]['xy'] if ax['scatter'] else []
                check.near(f'{lab}: the points', maxdiff([q for p in got for q in p], [q for p in points_of(t0) for q in p]), 0, 1e-9)
            if terms_plot:
                named = [(s, x, y) for s, x, y in zip(t0['text'], t0['x'], t0['y']) if s]
                ann = ax['annotations']
                check(f'{lab}: the terms the page names, at their points', ([a['s'] for a in ann], maxdiff([q for a in ann for q in a['xy']], [q for _, x, y in named for q in (x, y)])), ([s for s, _, _ in named], 0))
            check(f'{lab}: the titles and the size', ((ax['title'] or F['suptitle']), ax['xlabel'] or None, ax['ylabel'] or None, F['size']),
                  (r['titles'].get(g['label']) or g['label'], g['titles']['x'], g['titles']['y'], [g['w'] / 100, g['h'] / 100]))
            if 'rows excluded' in tag:
                check(f'{lab}: keeps its channel\'s rows and drops the excluded ones', ('df = df[df["channel"] == ' in g['code'], 'df = df.drop(index=[' in g['code']), (True, True))
        for c in r['clouds']:
            lab = f'the graphs\' code ({tag}): the word cloud'
            C, err = await run_cloud(page, c['code'])
            check(f'{lab}: runs in the page', err, None)
            if not C:
                continue
            got, want = C['words'], c['words']
            check(f'{lab}: the page\'s words, in its order', [w[0] for w in got], [w[0] for w in want])
            check.near(f'{lab}: each word where the page put it', maxdiff([q for w in got for q in w[1:3]], [q for w in want for q in w[1:3]]), 0, 1e-9)
            check.near(f'{lab}: at the page\'s font sizes (0.72 point a pixel; the page rounds to 0.1)', maxdiff([w[3] / 0.72 for w in got], [w[3] for w in want]), 0, 0.0501)
            check(f'{lab}: in the page\'s colours', [w[4] for w in got], [hexcol(w[4]) for w in want])
            x0, y0, wv, hv = c['viewBox']
            extra = 0.5 if c['legend'] else 0.0
            check.near(f'{lab}: the page\'s view and size', maxdiff(C['xlim'] + C['ylim'] + C['size'], [x0, x0 + wv, y0 + hv, y0, wv / 100, hv / 100 + extra]), 0, 1e-9)
            if c['legend']:
                check(f'{lab}: the legend of the mean', C['bars'], [f'Mean {by_col}'])
            if 'rows excluded' in tag:
                check(f'{lab}: keeps its channel\'s rows and drops the excluded ones', ('df = df[df["channel"] == ' in c['code'], 'df = df.drop(index=[' in c['code']), (True, True))
        if 'with an ID' in tag:
            check('the graphs\' code (By Column with an ID): the mean over every row of the report, the rows without an ID too', ('every = df' in r['clouds'][0]['code'], 'v = pd.to_numeric(every["rating"]' in r['clouds'][0]['code']), (True, True))
            await page.ev(f'{table_js}.setCell(6, "customer", {json.dumps(cust6)})')
        if 'rows excluded' in tag:
            await page.ev(f'{table_js}.setState({json.dumps(ex)}, "excluded", false)')
    await page.ev("for (const r of SM.app.reports.filter((x) => x.platform.id === 'text').slice(-4)) SM.app.closeReport(r)")


# ---- the analyses added in 2026-09: Latent Class Analysis, Cluster Terms and Documents, the SVD scatterplot matrix,
# Term Selection, Sentiment Analysis, the phrase list's containment, Save Stacked DTM for Association ---------------------
NEW = 'SM.app.reports.find((r) => r.platform.id === "text" && r.__new)'

# The engine's result for the new analyses' report, with its own seed.
ENG = r'''(async (fn, extra) => { const rep = %s; const t = rep.table;
  return await SM.engine.call(fn, { table: t.id, rows: null, column: 'comment', seed: rep.spec.options.seedDrawn, ...extra }, t); })''' % NEW


def eng_js(fn, extra=None):
    return f'({ENG})({json.dumps(fn)}, {json.dumps(extra or {})})'


# The centre of a report table's row (by its first cell) or of a button (by its text) under an outline, scrolled into view.
AT = r'''((outline, kind, text) => {
  const rep = %s;
  SM.app.showTab(SM.app.tabOf(rep));
  const head = [...rep.body.querySelectorAll('.sm-ob-head')].find((h) => h.querySelector('h2, h3, h4').textContent.trim() === outline);
  if (!head) return null;
  const body = head.parentElement.querySelector(':scope > .sm-ob-body');
  let node = null;
  if (kind === 'row') { const tbl = body.querySelector('table.sm-rt'); node = [...tbl.tBodies[0].rows].find((tr) => tr.cells[0].textContent === text); node = node && node.cells[0]; }
  else node = [...body.querySelectorAll('button')].find((b) => b.textContent.trim() === text);
  if (!node) return null;
  node.scrollIntoView({ block: 'center' });
  const b = node.getBoundingClientRect();
  return { x: b.left + Math.min(16, b.width / 2), y: b.top + b.height / 2 };
})''' % NEW


def at_js(outline, kind, text):
    return f'({AT})({json.dumps(outline)}, {json.dumps(kind)}, {json.dumps(text)})'


# The last report's red triangle, as PICK and PICK_FORM do, for the new analyses' report.
PICK_NEW = PICK.replace('const rep = SM.app.reports[SM.app.reports.length - 1];', f'const rep = {NEW}; SM.app.showTab(SM.app.tabOf(rep));')


def pick_new(title, path, wait=True):
    return f'({PICK_NEW})({json.dumps(title)}, {json.dumps(path)}, {json.dumps(wait)}, 0)'


def pick_form_new(title, path, fill='', rerun=True):
    form = PICK_FORM.replace('const rep = SM.app.reports[SM.app.reports.length - 1];', f'const rep = {NEW};')
    form = form.replace(PICK, PICK_NEW)
    return f'({form})({json.dumps(title)}, {json.dumps(path)}, {json.dumps(fill)}, {json.dumps(rerun)})'


def under_new(title, n=0):
    return table_under_js(title, n).replace('const rep = SM.app.reports[SM.app.reports.length - 1];', f'const rep = {NEW};')


STATE_NEW = STATE.replace('const rep = SM.app.reports[SM.app.reports.length - 1];', f'const rep = {NEW};')
SELECTED = f'{NEW}.table.selectedRows()'


async def real_click(page, pos):
    await page.click(pos['x'], pos['y'])
    await asyncio.sleep(0.35)
    return await page.ev(SELECTED)


async def settle_new(page):
    await page.ev(f'(async () => {{ const rep = {NEW}; for (let i = 0; i < 2400 && rep.body.classList.contains("is-running"); i++) await new Promise((r) => setTimeout(r, 25)); }})()', timeout=900)


async def new_analyses(page):
    await page.ev('SM.app.showTable(SM.app.tables.find(t => t.name === "Service comments").id)')
    await page.ev(open_report_js('text', {'text': ['comment']}, {}), timeout=600)
    await page.ev('(() => { SM.app.reports[SM.app.reports.length - 1].__new = true; })()')
    cid = (await page.ev(STATE_NEW))['id']
    ex = await page.ev(eng_js('text.explore'))
    trows = {x['term']: ex['term_rows'][k] for k, x in enumerate(ex['terms'])}

    # ---- Latent Class Analysis: from the red triangle's form, with JMP's report
    await page.ev(pick_form_new('*top*', ['Latent Class Analysis…']), timeout=900)
    st = await page.ev(STATE_NEW)
    check('Latent Class Analysis: JMP\'s outlines, no errors', (all(o in st['outlines'] for o in ('Latent Class Analysis for 5 Clusters', 'Cluster Mixture Probabilities', 'Term Probabilities by Cluster', 'Top Terms by Cluster', 'MDS Plot')), st['errors'], st['warnings']), (True, [], []))
    check('... its specification kept', st['options'].get(f'{cid}|lca'), {'k': 5, 'minFreq': 4, 'maxTerms': 1000})
    L = await page.ev(eng_js('text.lca', {'n_clusters': 5, 'min_freq': 4, 'max_terms': 1000}))
    mix = await page.ev(under_new('Cluster Mixture Probabilities'))
    check('Cluster Mixture Probabilities: the engine\'s mixing probabilities and documents', [[row[0], round(num(row[1]), 4), int(row[2])] for row in mix[1:]], [[str(c + 1), round(p, 4), n] for c, (p, n) in enumerate(zip(L['pi'], L['docs_in']))])
    tops = await page.ev(f'[...{NEW}.body.querySelectorAll(".sm-tx-topics")].pop().querySelectorAll("table").length')
    check('Top Terms by Cluster: a table per cluster', tops, 5)
    in1 = sorted(r_ for d, rs in enumerate(L['doc_rows']) if L['likely'][d] == 1 for r_ in rs)
    sel = await real_click(page, await page.ev(at_js('Cluster Mixture Probabilities', 'row', '1')))
    check('a real click on cluster 1 selects the rows of the documents most likely in it', sel, in1)
    mds = await page.ev(f'(() => {{ const p = {NEW}.plots.find(p => p.opts.title === "MDS Plot"); return p ? {{ x: p.traces[0].x, y: p.traces[0].y, n: p.rows[0].map(r => r.length) }} : null; }})()')
    check.near('the MDS Plot: a point per cluster at the engine\'s coordinates', maxdiff(mds['x'] + mds['y'], [c[0] for c in L['coords']] + [c[1] for c in L['coords']]), 0, 1e-12)
    check('... each standing for its documents\' rows', mds['n'], [sum(len(rs) for d, rs in enumerate(L['doc_rows']) if L['likely'][d] == c + 1) for c in range(5)])
    await page.ev(pick_new('Latent Class Analysis for 5 Clusters', ['Color by Cluster'], wait=False))
    await asyncio.sleep(0.4)
    colors = await page.ev(f'Array.from({NEW}.table.color)')
    check('Color by Cluster: each row takes its most likely cluster\'s colour', all(colors[L['doc_rows'][d][0]] == (L['likely'][d] - 1) % 12 for d in range(len(L['doc_rows']))), True)
    await page.ev(pick_new('Latent Class Analysis for 5 Clusters', ['Save Probabilities'], wait=False))
    await asyncio.sleep(1.0)
    await page.ev(pick_new('Latent Class Analysis for 5 Clusters', ['Save Cluster'], wait=False))
    await asyncio.sleep(1.0)
    sv = await page.ev(f'''(() => {{ const t = {NEW}.table; const cs = [1, 2, 3, 4, 5].map((c) => t.col(`Prob Cluster ${{c}}`)); const m = t.col('Most Likely Cluster');
      return {{ have: cs.map(Boolean).concat([!!m]), probs: cs.map((c) => c ? Array.from(c.values) : null), likely: m ? Array.from(m.values) : null, type: m ? m.modelingType : null }}; }})()''')
    ok = all(sv['have']) and all(abs(sv['probs'][c][L['doc_rows'][d][0]] - L['R'][d][c]) < 1e-12 for c in range(5) for d in range(len(L['doc_rows'])))
    check('Save Probabilities and Save Cluster: Prob Cluster 1 to 5 and Most Likely Cluster (nominal), the engine\'s', (ok, sv['type'], all(sv['likely'][L['doc_rows'][d][0]] == L['likely'][d] for d in range(len(L['doc_rows'])))), (True, 'nominal', True))
    await page.ev(f'{NEW}.table.select([])')

    # ---- the SVD: Cluster Terms, Cluster Documents, the scatterplot matrix
    await page.ev(pick_form_new('*top*', ['Latent Semantic Analysis, SVD…'], "d.querySelectorAll('.sm-form input')[2].value = '20';"), timeout=900)
    await page.ev(pick_new('SVD Centered and Scaled TF IDF', ['Cluster Terms']), timeout=900)
    st = await page.ev(STATE_NEW)
    check('Cluster Terms: its outline under the SVD, no errors', ('Cluster Terms' in st['outlines'], st['errors']), (True, []))
    spec = {'weighting': 'tfidf', 'centering': 'scaled', 'min_freq': 4, 'max_terms': 1000, 'k': 20}
    CT = await page.ev(eng_js('text.cluster', {**spec, 'kind': 'terms'}))
    col = await page.ev(f'''(() => {{ const p = {NEW}.plots.find(p => /^Term singular vectors/.test(p.opts.title)); return {{ c: p.traces[0].marker.color, pal: SM.util.PALETTE }}; }})()''')
    check('... the clusters colour the term SVD plot (the palette by cluster)', col['c'], [col['pal'][c % 12] for c in CT['labels']])
    check('... cut where the joining distance jumps most', await page.ev(f'{NEW}.body.querySelector(".sm-tx-controls .sm-tx-hint").textContent'), f'{CT["default_k"]} cluster{"s" if CT["default_k"] > 1 else ""}')
    await page.click(**{k: v for k, v in (await page.ev(at_js('Cluster Terms', 'button', '+'))).items()})
    await asyncio.sleep(0.3)
    await settle_new(page)
    st = await page.ev(STATE_NEW)
    check('a real click on + gives one cluster more', st['options'].get(f'{cid}|termClusters'), CT['default_k'] + 1)
    CT2 = await page.ev(eng_js('text.cluster', {**spec, 'kind': 'terms', 'n_clusters': CT['default_k'] + 1}))
    first = [CT2['names'][i] for i, c in enumerate(CT2['labels']) if c == 0]
    want = sorted({r_ for t in first for r_ in trows.get(t, [])})
    sel = await real_click(page, await page.ev(at_js('Cluster Terms', 'button', f'1: {len(first)}')))
    check('a real click on cluster 1 under the dendrogram selects the rows that hold its terms', sel, want)
    n0 = await page.ev('SM.app.tables.length')
    await page.ev(pick_new('Cluster Terms', ['Save Term Clusters'], wait=False))
    await asyncio.sleep(0.6)
    tt = await page.ev('(() => { const t = SM.app.tables[SM.app.tables.length - 1]; return { name: t.name, cols: t.columns.map(c => c.name), terms: t.col("Term").values, cl: Array.from(t.col("Cluster").values) }; })()')
    check('Save Term Clusters: a table of the terms and their clusters', (await page.ev('SM.app.tables.length') == n0 + 1, tt['cols'], tt['terms'] == CT2['names'], tt['cl'] == [c + 1 for c in CT2['labels']]), (True, ['Term', 'Count', 'Cases', 'Cluster'], True, True))
    await page.ev(f'SM.app.showTab(SM.app.tabOf({NEW}))')
    await page.ev(pick_new('SVD Centered and Scaled TF IDF', ['Cluster Documents']), timeout=900)
    CD = await page.ev(eng_js('text.cluster', {**spec, 'kind': 'docs'}))
    dcol = await page.ev(f'''(() => {{ const p = {NEW}.plots.find(p => /^Document singular vectors/.test(p.opts.title)); return p.traces[0].marker.color; }})()''')
    pal = col['pal']
    check('Cluster Documents: the clusters colour the document SVD plot', dcol, [pal[c % 12] for c in CD['labels']])
    await page.ev(pick_new('Cluster Documents', ['Save Document Clusters'], wait=False))
    await asyncio.sleep(0.6)
    dc = await page.ev(f'Array.from({NEW}.table.col("Document Cluster").values)')
    check('Save Document Clusters: each row its document\'s cluster', all(dc[CD['doc_rows'][d][0]] == CD['labels'][d] + 1 for d in range(CD['n'])), True)
    await page.ev(pick_form_new('SVD Centered and Scaled TF IDF', ['SVD Scatterplot Matrix…'], "d.querySelector('.sm-form input').value = '3';"), timeout=900)
    LS = await page.ev(eng_js('text.lsa', {**spec, 'show': 3}))
    sp = await page.ev(f'''(() => {{ const p = {NEW}.plots.find(p => /^SVD scatterplot matrix/.test(p.opts.title)); return p ? p.traces.map((t) => ({{ x: t.x, y: t.y, name: t.name }})) : null; }})()''')
    check('the SVD Scatterplot Matrix of 3: six panels, the documents below the diagonal and the terms above', [t['name'] for t in sp], ['Terms', 'Terms', 'Documents', 'Terms', 'Documents', 'Documents'])
    check.near('... Doc Vec1 against Doc Vec2 below, Term Vec2 against Term Vec1 above: the engine\'s coordinates',
               max(maxdiff(sp[2]['x'] + sp[2]['y'], LS['docs'][0] + LS['docs'][1]), maxdiff(sp[0]['x'] + sp[0]['y'], LS['term_vectors'][1] + LS['term_vectors'][0]), maxdiff(sp[5]['x'] + sp[5]['y'], LS['docs'][1] + LS['docs'][2])), 0, 1e-12)
    lk = await page.ev(f'''(async () => {{ const rep = {NEW}; const p = rep.plots.find(p => /^SVD scatterplot matrix/.test(p.opts.title)); p.box.scrollIntoView({{ block: 'center' }});
      for (let i = 0; i < 60 && !p.drawn; i++) await new Promise(r => setTimeout(r, 100));
      rep.table.select([7]); await new Promise(r => setTimeout(r, 200)); const s = p.box.data.map((t) => t.selectedpoints || []); rep.table.select([]); return s; }})()''')
    check('... rows selected in the table are marked in every document panel', [lk[k] for k in (2, 4, 5)], [[7], [7], [7]])
    await shot(page, 'text-08-svd-new.png')

    # ---- Term Selection: of the rating
    rid = await page.ev(f'{NEW}.table.col("rating").id')
    await page.ev(pick_form_new('*top*', ['Term Selection…'], f"const s = d.querySelector('select'); s.value = {json.dumps(rid)};"), timeout=900)
    st = await page.ev(STATE_NEW)
    check('Term Selection: its outlines, no errors', (all(o in st['outlines'] for o in ('Term Selection', 'Term Scores', 'Document Scores')), st['errors'], st['warnings']), (True, [], []))
    TS = await page.ev(eng_js('text.termsel', {'response': 'rating', 'weighting': 'binary', 'min_freq': 10, 'max_terms': 1000, 'early': True}))
    tsr = await page.ev(under_new('Term Scores'))
    check('Term Scores: the engine\'s terms, coefficients and LogWorths, the largest coefficient first', [[row[0], round(num(row[1]), 4)] for row in tsr[1:]], [[x['term'], round(x['coef'], 4)] for x in TS['terms']][:1000])
    check('... the planted praise positive and the complaints negative', (TS['terms'][0]['coef'] > 0, TS['terms'][-1]['coef'] < 0, TS['family']), (True, True, 'normal'))
    sel = await real_click(page, await page.ev(at_js('Term Scores', 'row', TS['terms'][0]['term'])))
    check('a real click on a term selects the rows that hold it', sel, trows[TS['terms'][0]['term']])
    await page.ev(pick_new('Term Selection', ['Save Document Scores'], wait=False))
    await asyncio.sleep(1.0)
    ds = await page.ev(f'''(() => {{ const t = {NEW}.table; return ['Positive Contribution', 'Negative Contribution', 'Predicted rating'].map((n) => t.col(n) ? Array.from(t.col(n).values) : null); }})()''')
    D = TS['docs']
    check('Save Document Scores: the positive and negative contributions and the prediction of every row', all(ds) and all(abs(ds[0][rs[0]] - D['positive'][d]) < 1e-12 and abs(ds[2][rs[0]] - D['predicted'][d]) < 1e-12 for d, rs in enumerate(D['rows'])), True)
    await page.ev(f'{NEW}.table.select([])')

    # ---- Sentiment Analysis: vaderSentiment from PyPI (micropip) on its first use
    await page.ev(pick_new('*top*', ['Sentiment Analysis']), timeout=900)
    await settle_new(page)
    st = await page.ev(STATE_NEW)
    check('Sentiment Analysis: vaderSentiment fetched from PyPI, the report without errors', ('Sentiment Analysis' in st['outlines'], 'Sentiment Terms' in st['outlines'], st['errors'], st['warnings']), (True, True, [], []))
    SE = await page.ev(eng_js('text.sentiment'))
    smt = await page.ev(under_new('Sentiment Analysis'))
    check('the Summary: the engine\'s positive, neutral and negative documents', [int(row[1]) for row in smt[1:]], [SE['summary']['positive'], SE['summary']['neutral'], SE['summary']['negative'], SE['n_docs']])
    ver = await page.ev('(async () => { const r = await SM.engine.runCell("check-vader", "import importlib.metadata as md\\nprint(md.version(\\"vaderSentiment\\"))", { label: "check", fresh: true }); return (r.outputs || []).map((o) => o.text || "").join(""); })()')
    check('... VADER 3.3.2, the version the page asks for', ver.strip(), '3.3.2')
    pin = await page.ev('(async () => { const r = await SM.engine.runCell("check-pin", "import hashlib, importlib.metadata as md\\nprint(hashlib.sha256(open(\\"/tmp/vaderSentiment-3.3.2-py2.py3-none-any.whl\\", \\"rb\\").read()).hexdigest(), (md.distribution(\\"vaderSentiment\\").read_text(\\"INSTALLER\\") or \\"\\").strip())", { label: "check", fresh: true }); return (r.outputs || []).map((o) => o.text || o.evalue || "").join(""); })()')
    check('... installed by micropip from the one wheel whose sha256 the page pins', pin.split(), ['3bf1d243b98b1afad575b9f22bc2cb1e212b94ff89ca74f8a23a588d024ea311', 'micropip'])
    negs = sorted(r_ for d, rs in enumerate(SE['docs']['rows']) if SE['docs']['compound'][d] <= -0.05 for r_ in rs)
    sel = await real_click(page, await page.ev(at_js('Sentiment Analysis', 'row', 'Negative (compound ≤ −0.05)')))
    check('a real click on the negative documents selects their rows', sel, negs)
    low = await page.ev(f'''(() => {{ const t = {NEW}.table; const r = t.col('rating').values; const sel = t.selectedRows(); return sel.reduce((a, i) => a + r[i], 0) / sel.length; }})()''')
    check('... and they are rated low (the example\'s complaints)', low < 2.5, True)
    await page.ev(pick_new('Sentiment Analysis', ['Save Document Scores'], wait=False))
    await asyncio.sleep(1.2)
    comp = await page.ev(f'(() => {{ const c = {NEW}.table.col("Sentiment Compound"); return c ? Array.from(c.values) : null; }})()')
    check('Save Document Scores: Sentiment Compound (and Positive, Neutral, Negative), the engine\'s', comp is not None and all(abs(comp[rs[0]] - SE['docs']['compound'][d]) < 1e-12 for d, rs in enumerate(SE['docs']['rows'])), True)
    await page.ev(f'{NEW}.table.select([])')

    # ---- the phrase list: Select Contains, Select Contained, Containing Phrases (right click)
    phr = [row[0] for row in (await page.ev(under_new('Term and Phrase Lists', 1)))[1:]]
    terms_ = [row[0] for row in (await page.ev(under_new('Term and Phrase Lists', 0)))[1:]]
    marked = f'''(() => {{ const rep = {NEW}; const t = [...rep.body.querySelectorAll('table.sm-rt')].filter((x) => x.caption && /^(Term|Phrase) List$/.test(x.caption.textContent));
      return t.map((x) => [...x.querySelectorAll('td.sm-tx-chosen')].filter((td) => td.cellIndex === 0).map((td) => td.textContent)); }})()'''
    CTX_NEW = CONTEXT.replace('const rep = SM.app.reports[SM.app.reports.length - 1];', f'const rep = {NEW};').replace(LIST_ROW, LIST_ROW.replace('const rep = SM.app.reports[SM.app.reports.length - 1];', f'const rep = {NEW};'))

    async def ctx_pick(caption, text, label):
        await page.ev(f'({CTX_NEW.replace("await done;", "await new Promise(r => setTimeout(r, 300));")})({json.dumps(caption)}, {json.dumps(text)}, {json.dumps(label)}, null)')
        return await page.ev(marked)
    inside = lambda a, b: any(b.split()[i:i + len(a.split())] == a.split() for i in range(len(b.split()) - len(a.split()) + 1))  # noqa: E731
    big = 'value for money'
    t_, p_ = await ctx_pick('Phrase List', big, 'Select Contained')
    check(f'Select Contained on "{big}": the shorter phrases inside it and the terms of its words', (sorted(p_), sorted(t_)), (sorted(p for p in phr if p != big and inside(p, big)), sorted(t for t in terms_ if t in big.split())))
    small = next(p for p in phr if len(p.split()) == 2 and any(q != p and inside(p, q) for q in phr))
    t_, p_ = await ctx_pick('Phrase List', small, 'Select Contains')
    check(f'Select Contains on "{small}": the longer phrases that hold it', sorted(p_), sorted(q for q in phr if q != small and inside(small, q)))
    t_, p_ = await ctx_pick('Term List', 'refund', 'Containing Phrases')
    check('Containing Phrases on "refund": the phrases with the word', sorted(p_), sorted(q for q in phr if 'refund' in q.split()))
    await page.ev(f'{NEW}.table.select([])')

    # ---- Save Stacked DTM for Association, and Association Analysis on it
    n0 = await page.ev('SM.app.tables.length')
    await page.ev(pick_new('*top*', ['Save Stacked DTM for Association'], wait=False))
    await asyncio.sleep(0.6)
    stk = await page.ev('(() => { const t = SM.app.tables[SM.app.tables.length - 1]; return { name: t.name, cols: t.columns.map(c => c.name), n: t.nrows, types: t.columns.map(c => c.modelingType) }; })()')
    check('Save Stacked DTM for Association: a row for each document and term it holds', (await page.ev('SM.app.tables.length') == n0 + 1, stk['cols'], stk['n']), (True, ['Row', 'Term'], sum(len(v) for v in ex['term_rows'])))
    await page.ev(TRIANGLES.replace('const rep = SM.app.reports[SM.app.reports.length - 1];', f'const rep = {NEW};'))
    tri = await page.ev(TRIANGLES.replace('const rep = SM.app.reports[SM.app.reports.length - 1];', f'const rep = {NEW};'))
    check(f'every red triangle of the new analyses\' report opens, with its submenus ({tri["triangles"]})', (tri['errors'], tri['triangles'] >= 8, tri['items'] > tri['triangles']), ([], True, True))
    ar = await page.ev(open_report_js('association', {'item': ['Term'], 'id': ['Row']}, {'minSupport': 0.05}), timeout=600)
    await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Frequent Item Sets'); if (h) h.querySelector('.sm-ob-toggle').click(); })()''')
    check('... and Association Analysis reads it (Item: Term, ID: Row) without errors', (ar['errors'], ar['warnings'], 'Rules' in ar['outlines']), ([], [], True))
    top_ = await page.ev(table_under_js('Frequent Item Sets'))
    nonempty = len({r_ for v in ex['term_rows'] for r_ in v})
    check.near('... its most frequent term\'s support: the rows that hold it over the rows with a term', num(top_[1][1]) / 100, max(len(v) for v in ex['term_rows']) / nonempty, tol=6e-4)
    await page.ev(f'SM.app.showTab(SM.app.tabOf({NEW}))')

    # ---- a project keeps the new analyses (the response's column id remapped), and By gives each group its own
    pj = await page.ev(f'''(async () => {{
      const rep = {NEW}; const t = rep.table;
      const j = JSON.parse(JSON.stringify({{ format: 'smui-project', version: 1, tables: [{{ id: t.id, ...t.toJSON() }}], reports: [rep.toJSON()] }}));
      SM.app.loadProject(j);
      const back = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => {{ if (!back.body.classList.contains('is-running') && back.body.querySelector('.sm-ob')) res(); else back.on('done', res); }});
      const heads = (r) => [...r.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent);
      const c = back.table.col('comment').id, ts = back.spec.options[c + '|termsel'];
      const out = {{ same: JSON.stringify(heads(back)) === JSON.stringify(heads(rep)), errors: back.body.querySelectorAll('.sm-ob-error, .sm-ob-warn').length,
                    response: ts && back.table.col(ts.response) ? back.table.col(ts.response).name : null, newTable: back.table !== t,
                    lca: back.spec.options[c + '|lca'], spm: back.spec.options[c + '|spm'], sentiment: back.spec.options[c + '|sentiment'] }};
      SM.app.closeTable(back.table);
      await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop();
      const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close');
      if (yes) yes.click();
      return out; }})()''', timeout=900)
    check('a project keeps the new analyses: the same outlines, no errors, the response remapped to the new table\'s rating', (pj['newTable'], pj['same'], pj['errors'], pj['response'], pj['lca'], pj['spm'], pj['sentiment']),
          (True, True, 0, 'rating', {'k': 5, 'minFreq': 4, 'maxTerms': 1000}, 3, True))
    await page.ev('SM.app.showTable(SM.app.tables.find(t => t.name === "Service comments").id)')
    by = await page.ev(f'''(async () => {{ const t = SM.app.tables.find(t => t.name === 'Service comments'); const c = t.col('comment').id;
      const o = {{}}; o[c + '|lca'] = {{ k: 3 }}; o[c + '|lsa'] = {{ k: 8 }}; o[c + '|clusterTerms'] = true; o[c + '|clusterDocs'] = true; o[c + '|spm'] = 3; o[c + '|termsel'] = {{ response: t.col('rating').id }}; o[c + '|sentiment'] = true;
      const rep = SM.app.openReport(SM.platforms.get('text'), {{ roles: {{ text: [c], by: [t.col('channel').id] }}, options: o }}, t);
      await new Promise(res => rep.on('done', res));
      const heads = [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent);
      const mix = [...rep.body.querySelectorAll('table.sm-rt')].filter((x) => x.dataset.rtKey === 'lcamix').map((x) => x._rt.rows.reduce((a, r) => a + r.n, 0));
      const out = {{ groups: heads.filter(h => /^Text Explorer for comment channel=/.test(h)).length, lca: heads.filter(h => h === 'Latent Class Analysis for 3 Clusters').length,
                    ts: heads.filter(h => h === 'Term Selection').length, se: heads.filter(h => h === 'Sentiment Analysis').length, spm: heads.filter(h => h === 'SVD Scatterplots of Document and Term Spaces').length,
                    mix, want: ['app', 'phone', 'web'].map(v => t.col('channel').values.filter(x => x === v).length), errors: [...rep.body.querySelectorAll('.sm-ob-error, .sm-ob-warn')].map(e => e.textContent.slice(0, 200)) }};
      SM.app.closeReport(rep);
      return out; }})()''', timeout=900)
    check('By channel: each group its own LCA, SVD matrix, Term Selection and Sentiment Analysis, without errors', (by['groups'], by['lca'], by['spm'], by['ts'], by['se'], by['errors']), (3, 3, 3, 3, 3, []))
    check('... each group\'s latent classes hold its own documents', by['mix'], by['want'])
    await page.ev(f'SM.app.showTab(SM.app.tabOf({NEW}))')

    # ---- the new forms' (i): every field with its help
    for title, path, fields in (('*top*', ['Latent Class Analysis…'], ['Maximum Number of Terms', 'Minimum Term Frequency', 'Number of Clusters']),
                                ('*top*', ['Term Selection…'], ['Response', 'Weighting', 'Maximum Number of Terms', 'Minimum Term Frequency', 'Early Stopping']),
                                ('SVD Centered and Scaled TF IDF', ['SVD Scatterplot Matrix…'], ['Number of singular vectors']),
                                ('Cluster Terms', ['Number of Clusters…'], ['Number of clusters'])):
        await form_help(page, f"await clickPath({NEW}, {json.dumps(title)}, {json.dumps(path)});", fields, path[-1])

    # ---- a recode of a stemmed term by right click: its words are recoded before the stemming, as in JMP
    await page.ev(pick_new('*top*', ['Term Options', 'Stemming', 'Stem for Combining']), timeout=900)
    before = {row[0]: int(row[1]) for row in (await page.ev(under_new('Term and Phrase Lists', 0)))[1:]}
    ref0 = next((t for t in ('refund' + DOT, 'refund') if t in before), None)
    recode = CONTEXT.replace('const rep = SM.app.reports[SM.app.reports.length - 1];', f'const rep = {NEW};').replace(LIST_ROW, LIST_ROW.replace('const rep = SM.app.reports[SM.app.reports.length - 1];', f'const rep = {NEW};'))
    await page.ev(f"({recode})('Term List', {json.dumps('return' + DOT)}, 'Recode…', \"d.querySelector('.sm-form input').value = 'refund';\")", timeout=900)
    await settle_new(page)
    after = {row[0]: int(row[1]) for row in (await page.ev(under_new('Term and Phrase Lists', 0)))[1:]}
    st = await page.ev(STATE_NEW)
    check('Recode of a stemmed term (return· -> refund): its words count as refund and stem with refund\'s, return· is gone',
          (ref0 is not None, 'return' + DOT in after, after.get('refund' + DOT, after.get('refund')), st['options'].get(f'{cid}|recodes')), (True, False, before['return' + DOT] + before[ref0], '{"return\u00b7":"refund"}'))
    fr = await page.ev(eng_js('text.explore', {'stemming': 'combine', 'recodes': {'return' + DOT: 'refund'}}))
    ref1 = 'refund' + DOT if 'refund' + DOT in after else 'refund'
    check(f'... and Show Text marks the texts\' words of both, return and returned and {ref1} itself', {'return', 'returned', 'refund'} <= {w for w, _ in fr['forms'].get(ref1, [])}, True)
    check('... the terms counted again, none lost', sum(after.values()), sum(before.values()))


async def new_chart_code(page):
    """The new graphs' matplotlib code, run in the page: the MDS Plot, the dendrogram, the scatterplot matrix, the term
    coefficients and the sentiment histogram draw the page's points, lines and bars."""
    g = await page.ev(f'(async () => {{ const rep = {NEW}; SM.app.showTab(SM.app.tabOf(rep)); return await __gr.graphs(rep); }})()', timeout=600)
    got = {x['label']: x for x in g}
    table_js = "SM.app.tables.find((x) => x.name === 'Service comments')"
    want = [lab for lab in got if any(lab.startswith(p) for p in ('MDS Plot', 'Cluster Terms of', 'SVD scatterplot matrix', 'Term coefficients', 'Sentiment of the documents'))]
    check('the new graphs are there, each with its code right under it, ending in plt.show()', (len(want), all(got[k]['code'] and got[k]['code'].rstrip().split('\n')[-1] == 'plt.show()' for k in want)), (5, True))
    for lab in want:
        G = got[lab]
        F, err = await run_graph(page, G, table_js)
        if not check(f'the new graphs\' code: {lab}: runs in the page', err, None) or not F:
            continue
        axes = F[0]['axes']
        t0 = G['traces'][0]
        if lab.startswith('MDS Plot'):
            check.near(f'{lab}: a point per cluster', maxdiff([q for p in axes[0]['scatter'][0]['xy'] for q in p], [q for p in points_of(t0) for q in p]), 0, 1e-9)
        elif lab.startswith('Cluster Terms of'):
            segs = []
            for t in G['traces'][:-1]:
                xs, ys = t['x'], t['y']
                for k in range(0, len(xs), 5):
                    segs.append(tuple(round(v, 9) for v in xs[k:k + 4] + ys[k:k + 4]))
            lines = [tuple(round(v, 9) for v in ln['x'] + ln['y']) for ln in axes[0]['lines'] if len(ln['x']) == 4]   # the joins (the cut is a line of its own)
            check(f'{lab}: every join drawn where the page draws it', sorted(lines), sorted(segs))
            check.near(f'{lab}: the leaves at their places', maxdiff([q for p in sorted(map(tuple, axes[0]['scatter'][0]['xy'])) for q in p], [q for p in sorted(points_of(G['traces'][-1])) for q in p]), 0, 1e-9)
        elif lab.startswith('SVD scatterplot matrix'):
            check(f'{lab}: a panel per pair', len(axes), len(G['traces']))
            check.near(f'{lab}: each panel\'s points', max(maxdiff([q for p in ax['scatter'][0]['xy'] for q in p], [q for p in points_of(t) for q in p]) for ax, t in zip(axes, G['traces'])), 0, 1e-9)
        elif lab.startswith('Term coefficients'):
            check.near(f'{lab}: a bar per term, its coefficient', maxdiff([b['w'] for b in axes[0]['bars']], t0['x']), 0, 1e-9)
        else:
            check(f'{lab}: the bars: the documents in each 0.1', [round(b['h']) for b in axes[0]['bars']], t0['y'])
            check.near(f'{lab}: at the page\'s places', maxdiff([b['x'] + b['w'] / 2 for b in axes[0]['bars']], t0['x']), 0, 1e-9)


asyncio.run(main())
sys.exit(check.done())
