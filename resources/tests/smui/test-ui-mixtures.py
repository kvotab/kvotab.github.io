#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Clustering > Normal Mixtures.

The simulated Fish ages example opens from the URL and File > Examples, and
the platform sits in Analyze > Clustering after K Means Cluster; the first
fit loads scikit-learn (and no warning of Pyodide's threadpoolctl reaches
the report); the launch dialog casts the columns and takes the options; the
Cluster Comparison, Cluster Summary and Cluster Means are the engine's
numbers, and the −2LogLikelihood is that of the reported proportions, means
and covariances computed here in JavaScript; the clusters are the fish's
ages; points select their rows (one by a real mouse click) and table
selections light up the scatterplot matrix and the biplot; the legend and
the summary select a cluster's rows; every red triangle opens; the Iterative
Clustering panel fits a range with progress, the smallest BIC (or AICc) is
marked and a click opens another fit; the outlier cluster takes the
recording errors; the covariance structures change the counts of parameters;
Save Clusters and Save Mixture Probabilities write the columns; Color
Clusters colours the rows and leaves them alone on a redraw and in the other
theme; the profiler of the cluster probabilities; one column gives the
mixture density; Freq counts rows; By gives one analysis per lake; Redo and
a project keep the options; every (i) has a topic; the launch dialog's (i)
gives every role and option its help, and the Iterative Clustering panel's
(i) each of its fields; the reports draw in the dark theme and at phone
width without a sideways page scroll, and no script error happens.

Start a server on the repository root and headless Chrome (README.md) on
SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-mixtures.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import os
import sys

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine
from test_charts import GRAPHS_JS, maxdiff, points_of, run_graph

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()
Y = ['length (cm)', 'girth (cm)', 'weight (g)']


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.8)
        await page.shot(os.path.join(SHOTS, name))


def num(s):
    return float(str(s).replace('−', '-').replace('%', '').replace('*', '').replace('<', ''))


# Pick an item from an outline's red triangle: path is the labels down the
# submenus; wait: wait for the report to run again; which: the n-th outline
# with that title.
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
           warnings: [...rep.body.querySelectorAll('.sm-ob-warn')].map(e => e.textContent.slice(0, 300)), options: rep.spec.options,
           notes: [...rep.body.querySelectorAll('.sm-ob-note')].map(e => e.textContent) };
})()
'''

# The fit the report shows, from the engine with the report's own payload.
ENGINE_FIT = '''
(async (extra) => {
  const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
  const o = rep.spec.options;
  const cols = rep.spec.roles.y.map(id => t.col(id).name);
  const kmin = o.k ?? 3, kr = o.kRange ?? null;
  const seed = (o.seed !== undefined && o.seed !== '' && o.seed !== null) ? Math.trunc(Number(o.seed)) : o.seedDrawn;
  const payload = { table: t.id, rows: null, columns: cols, freq: rep.spec.roles.freq && rep.spec.roles.freq.length ? t.col(rep.spec.roles.freq[0]).name : null,
    k_min: kmin, k_max: kr && kr > kmin ? kr : kmin, covariance: o.covariance || 'full', tours: o.tours ?? 10, outlier: !!o.outlier, standardize: o.scaled ?? true,
    seed, max_iter: o.maxIter ?? 500, tol: o.tol ?? 1e-6, choose: o.choose || 'bic', ...(extra || {}) };
  return await SM.engine.call('mixtures.fit', payload, t);
})
'''


def engine_fit_js(extra=None):
    return f'({ENGINE_FIT})({json.dumps(extra or {})})'


# The log likelihood of a fit's proportions, means and covariances at the
# report's rows, computed here (Cholesky in JavaScript).
LOGLIK = '''
((f, res) => {
  const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
  const cols = res.names.map(n => t.col(n));
  const p = cols.length;
  const chol = (A) => { const L = A.map(r => r.map(() => 0)); for (let i = 0; i < p; i++) for (let j = 0; j <= i; j++) { let s = A[i][j]; for (let k = 0; k < j; k++) s -= L[i][k] * L[j][k]; L[i][j] = i === j ? Math.sqrt(s) : s / L[j][j]; } return L; };
  const comps = f.covs.slice(0, f.k).map((C, j) => { const L = chol(C); let ld = 0; for (let i = 0; i < p; i++) ld += Math.log(L[i][i]); return { L, ld, mu: f.means[j], w: f.weights[j] }; });
  let ll = 0;
  for (const r of res.rows) {
    const x = cols.map(c => c.values[r]);
    const parts = comps.map(({ L, ld, mu, w }) => { const z = []; for (let i = 0; i < p; i++) { let s = x[i] - mu[i]; for (let k = 0; k < i; k++) s -= L[i][k] * z[k]; z.push(s / L[i][i]); } const q = z.reduce((a, b) => a + b * b, 0); return Math.log(w) - 0.5 * (q + p * Math.log(2 * Math.PI)) - ld; });
    if (f.outlier_weight != null) parts.push(Math.log(f.outlier_weight * f.outlier_density));
    const m = Math.max(...parts);
    ll += m + Math.log(parts.reduce((a, b) => a + Math.exp(b - m), 0));
  }
  return ll;
})
'''


async def rerun(page):
    await page.ev('(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')


async def triangles(page, name, least):
    r = await page.ev(TRIANGLES)
    ok = isinstance(r, dict) and not r['errors'] and r['triangles'] >= least and r['items'] > r['triangles']
    check(f'every red triangle of {name} opens, with its submenus', ok, True)
    if not ok:
        print('   ', r)



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
    page = await open_page(f'{BASE}/smui.html?example=fishages', height=1300)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    check('mixtures.py imports in Pyodide', await page.ev('SM.engine.failed.filter(f => f.module === "mixtures").map(f => f.module + ": " + f.error)'), [])
    check('no script errors at load', page.errors, [])
    check('scikit-learn is not loaded at the start', await page.ev("SM.engine.versions['scikit-learn'] || null"), None)

    # ---- the example and the menu
    ex = await page.ev('''(() => {
      const t = SM.app.current;
      const file = SM.app.menuItems('File');
      const exs = file.find(i => i.label === 'Examples');
      const labels = (typeof exs.submenu === 'function' ? exs.submenu() : exs.submenu).map(i => i.label);
      const an = SM.app.menuItems('Analyze');
      const cl = an.find(i => i.label === 'Clustering');
      const items = (typeof cl.submenu === 'function' ? cl.submenu() : cl.submenu).filter(i => !i.separator).map(i => i.label);
      const err = t.col('age (true)').values.filter(v => Number.isNaN(v)).length;
      return { name: t.name, rows: t.nrows, cols: t.columns.map(c => [c.name, c.modelingType]), about: SM.io.EXAMPLES.fishages.about, inFile: labels.includes(SM.io.EXAMPLES.fishages.label), items, err };
    })()''')
    check('?example=fishages opens the simulated fish table', (ex['name'], ex['rows'], [c[0] for c in ex['cols']]), ('Fish ages', 540, ['lake', 'length (cm)', 'girth (cm)', 'weight (g)', 'age (true)']))
    check('it is simulated, with twelve recording errors (no age)', (ex['about'].startswith('Simulated'), ex['err']), (True, 12))
    check('it is in File > Examples', ex['inFile'], True)
    check('Analyze > Clustering lists Normal Mixtures after K Means Cluster', 'Normal Mixtures…' in ex['items'] and ex['items'].index('Normal Mixtures…') == ex['items'].index('K Means Cluster…') + 1, True)

    # ---- the launch dialog
    r = await page.ev('''(async (Y) => {
      SM.app.launch('mixtures');
      await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      const roles = [...dlg.querySelectorAll('.sm-role .sm-btn')].map(b => b.textContent);
      const opts = [...dlg.querySelectorAll('.sm-launch-opts label')].map(l => [...l.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim());
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => { items.forEach(li => li.classList.remove('is-selected')); items.find(x => x.textContent === name).dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); };
      const role = (label) => [...dlg.querySelectorAll('.sm-role')].find(r => r.querySelector('.sm-btn').textContent === label);
      const ok = [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK');
      pick('lake'); role('Y, Columns').querySelector('.sm-btn').click();
      const refused = dlg.querySelector('.sm-launch-msg').textContent;
      for (const c of Y) { pick(c); role('Y, Columns').querySelector('.sm-btn').click(); }
      ok.click();
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res));
      return { roles, opts, refused, options: rep.spec.options, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent), sk: SM.engine.versions['scikit-learn'] || null };
    })(%s)''' % json.dumps(Y), timeout=600)
    check('the launch roles: Y, Columns, Freq and By', r['roles'], ['Y, Columns', 'Freq', 'By'])
    check('the launch options', r['opts'], ['Number of Clusters', 'Range of Clusters (optional)', 'Tours', 'Covariance Structure', 'Outlier Cluster', 'Columns Scaled Individually', 'Random Seed'])
    check('a character column is refused as a Y', 'continuous' in r['refused'] or 'numeric' in r['refused'], True)
    check('the defaults reach the report', (r['options']['k'], r['options']['tours'], r['options']['covariance'], r['options']['outlier'], r['options']['scaled']), (3, 10, 'full', False, True))
    check('the report\'s outlines', r['outlines'], ['Normal Mixtures', 'Iterative Clustering', 'Cluster Comparison', 'Normal Mixtures NCluster=3', 'Scatterplot Matrix', 'Biplot'])
    check('the first fit loaded scikit-learn 1.8.0', r['sk'], '1.8.0')
    st = await page.ev(STATE)
    check('no errors, and no warning in the report (Pyodide\'s threadpoolctl warning is kept out)', (st['errors'], st['warnings'], 'Messages from statsmodels' in st['outlines']), ([], [], False))
    check('the seed is drawn once and kept with the report', isinstance(st['options'].get('seedDrawn'), int), True)
    await shot(page, 'mix-01-report.png')

    # ---- the numbers: the engine's, and the likelihood computed here
    res = await page.ev(engine_fit_js())
    f = res['fits'][0]
    cmp_ = await page.ev(table_under_js('Cluster Comparison', 0))
    check('Cluster Comparison: its columns', cmp_[0], ['Method', 'NCluster', '-2LogLikelihood', 'Number of Parameters', 'AICc', 'BIC', 'Best'])
    row = cmp_[1]
    check.near('-2LogLikelihood is the engine\'s', num(row[2]), f['m2ll'], tol=1e-6)
    check('the number of parameters: 3 × (3 means + 6 covariances) + 2 proportions', num(row[3]), 29)
    check.near('AICc is the engine\'s', num(row[4]), f['aicc'], tol=1e-6)
    check.near('BIC is the engine\'s', num(row[5]), f['bic'], tol=1e-6)
    check('one fit: marked the best', row[6], 'Optimal BIC')
    ll = await page.ev(f'({LOGLIK})({json.dumps(f)}, {json.dumps(res)})')
    check.near('−2LogLikelihood is that of the reported proportions, means and covariances, computed here', -2 * ll, f['m2ll'], tol=1e-9)
    summ = await page.ev(table_under_js('Normal Mixtures NCluster=3', 0))
    check('Cluster Summary: Cluster, Count, Proportion', summ[0], ['Cluster', 'Count', 'Proportion'])
    check('... the counts are the engine\'s and add to 540', ([num(x[1]) for x in summ[1:]], sum(num(x[1]) for x in summ[1:])), (f['counts'], 540))
    check.near('... the first proportion is the engine\'s', num(summ[1][2]), f['weights'][0], tol=1e-4)
    means = await page.ev(table_under_js('Normal Mixtures NCluster=3', 2))
    check('Cluster Means: a line per cluster, a column per Y', (means[0], len(means)), (['Cluster'] + Y, 4))
    check.near('... the first mean is the engine\'s', num(means[1][1]), f['means'][0][0], tol=1e-6)
    # The fit of the best likelihood depends on the starts: a rare drawn seed finds
    # a better fit (lower -2LogLikelihood) whose clusters are not the ages. So the
    # ages are checked on the fit from seed 1 (every seed tried gives the same).
    age_fit = await page.ev(engine_fit_js({'seed': 1}))
    agree = await page.ev('''((labels, rows) => {
      const t = SM.app.reports[SM.app.reports.length - 1].table; const age = t.col('age (true)').values;
      const tab = {}; let n = 0;
      rows.forEach((r, i) => { if (Number.isNaN(age[r])) return; n++; const k = labels[i] + ':' + age[r]; tab[k] = (tab[k] || 0) + 1; });
      // the best matching of clusters to ages
      const perms = [[1,2,3],[1,3,2],[2,1,3],[2,3,1],[3,1,2],[3,2,1]];
      return Math.max(...perms.map(pm => [0,1,2].reduce((a, c) => a + (tab[c + ':' + pm[c]] || 0), 0))) / n;
    })''' + f'({json.dumps(age_fit["fits"][0]["labels"])}, {json.dumps(age_fit["rows"])})')
    check(f'the three clusters are the fish\'s three ages ({agree:.3f} of the fish, seed 1)', agree > 0.9, True)

    # ---- linking
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const sp = rep.plots.find(p => /^Scatterplot Matrix/.test(p.opts.title));
      const bi = rep.plots.find(p => /^Biplot/.test(p.opts.title));
      sp._click({ points: [{ curveNumber: 0, pointNumber: 7 }], event: {} });
      const sel = t.selectedRows();
      t.select([sp.rows[0][3], sp.rows[0][11]]);
      const cells = sp.box.data.map((d, i) => sp.rows[i] ? d.selectedpoints : undefined).filter(x => x !== undefined);
      const bsel = bi.box.data[0].selectedpoints;
      t.select([]);
      return { sel, want: [sp.rows[0][7]], cells, bsel, colors: sp.traces[0].marker.color.slice(0, 3), rowColors: sp.rowColors };
    })()''')
    check('a click on a point of the scatterplot matrix selects its row', r['sel'], r['want'])
    check('rows selected in the table light up every cell of the matrix and the biplot', (all(c == [3, 11] for c in r['cells']), len(r['cells']), r['bsel']), (True, 3, [3, 11]))
    check('the points take their cluster\'s colour (not the rows\' colours)', (all(c.startswith('#') for c in r['colors']), r['rowColors']), (True, False))
    pos = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const p = rep.plots.find(p => /^Biplot/.test(p.opts.title));
      p.box.scrollIntoView({ block: 'center' });
      await new Promise(r => setTimeout(r, 300));
      for (let n = 0; n < 40 && !p.drawn; n++) await new Promise(r => setTimeout(r, 100));
      const gd = p.box, xa = gd._fullLayout.xaxis, ya = gd._fullLayout.yaxis;
      const xs = p.traces[0].x, ys = p.traces[0].y;
      let best = 0, bestD = -1;
      for (let k = 0; k < xs.length; k++) { let d = Infinity; for (let m = 0; m < xs.length; m++) if (m !== k) d = Math.min(d, (xs[k] - xs[m]) ** 2 + (ys[k] - ys[m]) ** 2); if (d > bestD) { bestD = d; best = k; } }
      const b = gd.getBoundingClientRect();
      return { x: b.left + xa._offset + xa.l2p(xs[best]), y: b.top + ya._offset + ya.l2p(ys[best]), row: p.rows[0][best] };
    })()''')
    await page.click(pos['x'], pos['y'])
    await asyncio.sleep(0.4)
    check('a mouse click on a point of the biplot selects that row', await page.ev('SM.app.reports[SM.app.reports.length - 1].table.selectedRows()'), [pos['row']])
    await page.mouse('mouseMoved', 2, 2)
    r = await page.ev('''((labels, rows) => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const legend = [...rep.body.querySelectorAll('.sm-mix-legend button')];
      legend[1].click();
      const fromLegend = t.selectedRows();
      const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Normal Mixtures NCluster=3');
      head.parentElement.querySelector('table.sm-rt tbody tr:nth-child(3)').click();
      const fromSummary = t.selectedRows();
      t.select([]);
      return { legend: legend.map(b => b.textContent), fromLegend, fromSummary, want1: rows.filter((r, i) => labels[i] === 1), want2: rows.filter((r, i) => labels[i] === 2) };
    })''' + f'({json.dumps(f["labels"])}, {json.dumps(res["rows"])})')
    check('the legend: a button per cluster with its count', r['legend'], [f'Cluster {c + 1}: {int(n)}' for c, n in enumerate(f['counts'])])
    check('a legend button selects its cluster\'s rows', r['fromLegend'], r['want1'])
    check('a line of the Cluster Summary selects its cluster\'s rows', r['fromSummary'], r['want2'])
    await page.ev('SM.app.reports[SM.app.reports.length - 1].table.select([])')

    await triangles(page, 'the report', 3)

    # ---- a range from the Iterative Clustering panel, with progress
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Iterative Clustering');
      const box = head.parentElement;
      const [k, range] = box.querySelectorAll('.sm-mix-num');
      k.value = '1'; k.dispatchEvent(new Event('change'));
      range.value = '5'; range.dispatchEvent(new Event('change'));
      const seen = [];
      const off = SM.engine.on('progress', (p) => seen.push([p.what, p.done, p.total]));
      const done = new Promise(res => rep.on('done', res));
      [...box.querySelectorAll('button')].find(b => b.textContent === 'Go').click();
      await done;
      off();
      return { seen, options: rep.spec.options };
    })()''', timeout=600)
    check('Go: the range 1 to 5 is fitted, a progress event per fit', [s for s in r['seen'] if s[0] == 'mixtures'], [['mixtures', i, 5, ] for i in range(1, 6)])
    check('... the options kept', (r['options']['k'], r['options']['kRange']), (1, 5))
    cmp5 = await page.ev(table_under_js('Cluster Comparison', 0))
    bics = [num(x[5]) for x in cmp5[1:]]
    marked = [x[1] for x in cmp5[1:] if x[6] == 'Optimal BIC']
    check('Cluster Comparison: five fits, the smallest BIC marked', ([x[1] for x in cmp5[1:]], marked), (['1', '2', '3', '4', '5'], [str(1 + bics.index(min(bics)))]))
    st = await page.ev(STATE)
    best_k = int(marked[0])
    check('the best fit\'s outline is open, the others closed', await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1];
      return [...rep.body.querySelectorAll('.sm-ob')].filter(o => /^Normal Mixtures NCluster=/.test(o.querySelector('.sm-ob-head h3')?.textContent || '')).map(o => [o.querySelector('.sm-ob-head h3').textContent, !o.classList.contains('is-closed')]); })()'''),
          [[f'Normal Mixtures NCluster={k}', k == best_k] for k in range(1, 6)])
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Cluster Comparison');
      const tr = [...head.parentElement.querySelectorAll('table.sm-rt tbody tr')].find(x => x.cells[1].textContent === '2');
      const done = new Promise(res => rep.on('done', res));
      tr.click();
      await done;
      const obs = [...rep.body.querySelectorAll('.sm-ob')].filter(o => o.querySelector('.sm-ob-head h3')?.textContent === 'Normal Mixtures NCluster=2');
      return { open: rep.spec.options.open, isOpen: obs.length ? !obs[0].classList.contains('is-closed') : null, plots: rep.plots.filter(p => / 2 clusters$/.test(p.opts.title)).length };
    })()''')
    check('a click on the line of two clusters opens that fit, with its graphs', (r['open'], r['isOpen'], r['plots'] >= 2), (2, True, True))
    lazy = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const ob = [...rep.body.querySelectorAll('.sm-ob')].find(o => o.querySelector('.sm-ob-head h3')?.textContent === 'Normal Mixtures NCluster=4');
      const before = rep.plots.filter(p => / 4 clusters$/.test(p.opts.title)).length;
      ob.querySelector('.sm-ob-toggle').click();
      await new Promise(r => setTimeout(r, 400));
      return { before, after: rep.plots.filter(p => / 4 clusters$/.test(p.opts.title)).length };
    })()''')
    check('a closed fit draws its graphs when it is opened', (lazy['before'], lazy['after'] >= 2), (0, True))
    await page.ev(pick_js('Cluster Comparison', ['Best By', 'AICc']))
    cmpa = await page.ev(table_under_js('Cluster Comparison', 0))
    aiccs = [num(x[4]) for x in cmpa[1:]]
    check('Best By AICc: the smallest AICc is marked', [x[1] for x in cmpa[1:] if x[6] == 'Optimal AICc'], [str(1 + aiccs.index(min(aiccs)))])
    await page.ev(pick_js('Cluster Comparison', ['Best By', 'BIC']))
    await shot(page, 'mix-02-range.png')

    # ---- the outlier cluster takes the recording errors
    await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const d = new Promise(res => rep.on('done', res));
      rep.spec.options.k = 3; rep.spec.options.kRange = null; rep.spec.options.open = null; rep.run(); await d; })()''')
    await page.ev(pick_js('*top*', ['Outlier Cluster']))
    res = await page.ev(engine_fit_js())
    f = res['fits'][0]
    summ = await page.ev(table_under_js('Normal Mixtures NCluster=3', 0))
    check('with the Outlier Cluster the summary has its line', [x[0] for x in summ[1:]], ['1', '2', '3', 'Outlier'])
    r = await page.ev('''((labels, rows) => {
      const t = SM.app.reports[SM.app.reports.length - 1].table; const age = t.col('age (true)').values;
      let errOut = 0, fishOut = 0, err = 0;
      rows.forEach((r, i) => { const isErr = Number.isNaN(age[r]); if (isErr) err++; if (labels[i] === 3) { if (isErr) errOut++; else fishOut++; } });
      return { errOut, fishOut, err };
    })''' + f'({json.dumps(f["labels"])}, {json.dumps(res["rows"])})')
    check(f'the outlier cluster takes most recording errors ({r["errOut"]} of {r["err"]}) and few fish ({r["fishOut"]} of 528)', (r['errOut'] >= 8, r['fishOut'] <= 5), (True, True))
    cmp_ = await page.ev(table_under_js('Cluster Comparison', 0))
    check('with the outlier cluster: one more parameter, the method named', (num(cmp_[1][3]), cmp_[1][0]), (30, 'Normal Mixtures, Outlier Cluster'))
    ll = await page.ev(f'({LOGLIK})({json.dumps(f)}, {json.dumps(res)})')
    check.near('−2LogLikelihood with the uniform cluster is that of the reported parameters, computed here', -2 * ll, f['m2ll'], tol=1e-9)
    st = await page.ev(STATE)
    check('the note gives the outlier cluster\'s box and density', any('uniform over the box' in n for n in st['notes']), True)
    sp = await page.ev('(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const p = rep.plots.find(p => /^Scatterplot Matrix/.test(p.opts.title)); return [...new Set(p.traces[0].marker.color)]; })()')
    check('the outlier cluster\'s rows are grey in the graphs', '#7f7f7f' in sp, True)
    await shot(page, 'mix-03-outlier.png')

    # ---- covariance structures
    for label, key, q in (('Diagonal', 'diag', 21), ('Tied', 'tied', 18), ('Spherical', 'spherical', 15), ('Full', 'full', 30)):
        await page.ev(pick_js('*top*', ['Covariance Structure', label]))
        cmp_ = await page.ev(table_under_js('Cluster Comparison', 0))
        st = await page.ev(STATE)
        check(f'Covariance Structure {label}: {q} parameters (with the outlier cluster), said in the note', (num(cmp_[1][3]), any(f'{label.lower()} covariances' in n for n in st['notes'])), (q, True))
    await page.ev(pick_js('*top*', ['Outlier Cluster']))

    # ---- Save
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const n0 = t.columns.length;
      await (%s)('Normal Mixtures NCluster=3', ['Save Clusters'], false, 0);
      await (%s)('Normal Mixtures NCluster=3', ['Save Mixture Probabilities'], false, 0);
      for (let i = 0; i < 40 && t.columns.length < n0 + 4; i++) await new Promise(r => setTimeout(r, 100));
      const cl = t.col('Cluster');
      const probs = ['Prob[Cluster 1]', 'Prob[Cluster 2]', 'Prob[Cluster 3]'].map(n => t.col(n));
      let worst = 0;
      for (let r = 0; r < t.nrows; r++) worst = Math.max(worst, Math.abs(probs.reduce((a, c) => a + c.values[r], 0) - 1));
      return { names: t.columns.slice(n0).map(c => c.name), type: cl.modelingType, v: cl.values.slice(0, 20), worst };
    })()''' % (PICK, PICK))
    res = await page.ev(engine_fit_js())
    f = res['fits'][0]
    want = [None] * 540
    for i, row_ in enumerate(res['rows']):
        want[row_] = f['labels'][i] + 1
    check('Save Clusters and Save Mixture Probabilities: the columns', r['names'], ['Cluster', 'Prob[Cluster 1]', 'Prob[Cluster 2]', 'Prob[Cluster 3]'])
    check('the saved clusters are nominal, the most likely cluster of each row', (r['type'], r['v']), ('nominal', want[:20]))
    check.near('the saved probabilities of a row add to 1', r['worst'], 0.0, tol=1e-12)
    # Save Mixture Formulas (JMP's Dist Formula, Dist Total and Prob Formula columns, and a Cluster Formula): live formulas
    # that give the saved probabilities and clusters, and follow an edited value
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const n0 = t.columns.length;
      await (%s)('Normal Mixtures NCluster=3', ['Save Mixture Formulas'], false, 0);
      for (let i = 0; i < 60 && t.columns.length < n0 + 8; i++) await new Promise(r => setTimeout(r, 100));
      const made = t.columns.slice(n0);
      const P = [1, 2, 3].map(j => t.col(`Prob Formula ${j}`)), Q = [1, 2, 3].map(j => t.col(`Prob[Cluster ${j}]`));
      let worst = 0;
      for (let r = 0; r < t.nrows; r++) for (let j = 0; j < 3; j++) worst = Math.max(worst, Math.abs(P[j].values[r] - Q[j].values[r]));
      const cf = t.col('Cluster Formula'), cl = t.col('Cluster');
      let same = 0;
      for (let r = 0; r < t.nrows; r++) same += cf.values[r] === cl.values[r];
      const L = t.col('length (cm)'); const before = P[0].values[0]; const old = L.values[0];
      t.setCell(0, L.id, old + 3); await new Promise(r => setTimeout(r, 80)); const after = P[0].values[0]; t.setCell(0, L.id, old);
      const out = { names: made.map(c => c.name), formulas: made.every(c => !!c.formula), worst, same, moved: before !== after };
      for (const c of made) t.removeColumn(c.id);
      return out;
    })()''' % PICK)
    check('Save Mixture Formulas: JMP\'s Dist Formula, Dist Total and Prob Formula columns, and a Cluster Formula', (r['names'], r['formulas']),
          (['Dist Formula 1', 'Dist Formula 2', 'Dist Formula 3', 'Dist Total', 'Prob Formula 1', 'Prob Formula 2', 'Prob Formula 3', 'Cluster Formula'], True))
    check.near('... the Prob formulas give the saved probabilities', r['worst'], 0.0, tol=1e-12)
    check('... the Cluster Formula the saved clusters, on every row', r['same'], 540)
    check('... and they follow an edited value', r['moved'], True)
    # the rows the fit leaves out get their cluster and probabilities too
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      for (const n of ['Cluster', 'Prob[Cluster 1]', 'Prob[Cluster 2]', 'Prob[Cluster 3]']) if (t.col(n)) t.removeColumn(t.col(n).id);
      t.setState([0, 1, 2], 'excluded', true);
      let d = new Promise(res => rep.on('done', res)); rep.run(); await d;
      const n0 = t.columns.length;
      await (%s)('Normal Mixtures NCluster=3', ['Save Clusters'], false, 0);
      for (let i = 0; i < 40 && t.columns.length < n0 + 1; i++) await new Promise(r => setTimeout(r, 100));
      const cl = t.col('Cluster');
      const out = [0, 1, 2].map(r => cl && Number.isFinite(cl.values[r]));
      if (cl) t.removeColumn(cl.id);
      t.setState([0, 1, 2], 'excluded', false);
      d = new Promise(res => rep.on('done', res)); rep.run(); await d;
      return out;
    })()''' % PICK)
    check('Save Clusters: the excluded rows get their most likely cluster too', r, [True, True, True])

    # ---- Color Clusters: once, when the clusters change
    r = await page.ev('''(async (labels, rows) => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      await (%s)('*top*', ['Color Clusters'], true, 0);
      const got = rows.map(r => t.color[r]);
      const want = labels.map(c => c);
      t.setColor([rows[0]], 5);
      let d = new Promise(res => rep.on('done', res)); rep.run(); await d;
      const afterRedo = t.color[rows[0]];
      document.documentElement.setAttribute('data-theme', 'dark');
      await new Promise(r => setTimeout(r, 1500));
      const afterTheme = t.color[rows[0]];
      document.documentElement.setAttribute('data-theme', 'light');
      await new Promise(r => setTimeout(r, 1200));
      return { same: got.every((c, i) => c === want[i]), afterRedo, afterTheme };
    })''' % PICK + f'({json.dumps(f["labels"])}, {json.dumps(res["rows"])})', timeout=300)
    check('Color Clusters gives each row its cluster\'s colour', r['same'], True)
    check('a redraw with the same clusters leaves a row\'s own colour alone, and so does the other theme', (r['afterRedo'], r['afterTheme']), (5, 5))
    # Bootstrap reruns the report headless on resamples: its numbers, and no row colours changed
    rb = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const colors = Array.from(t.color), options = JSON.stringify(rep.spec.options), ncol = t.columns.length;
      const tbl = [...rep.body.querySelectorAll('table.sm-rt')].find(x => x.dataset.rtKey === 'comparison' || (x._rt && x._rt.all.some(c => c.key === 'bic')));
      const col = tbl._rt.all.find(c => c.key === 'bic');
      const res = await SM.bootstrap.run(tbl, col, { B: 3, seed: 5, show: false });
      const summ = [...rep.body.querySelectorAll('table.sm-rt')].find(x => x._rt && x._rt.all.some(c => c.key === 'prop'));
      const res2 = await SM.bootstrap.run(summ, summ._rt.all.find(c => c.key === 'n'), { B: 2, seed: 6, show: false });
      return { names: res.columns.map(c => c.name), n: res.nrows, finite: res.columns[1].values.every(Number.isFinite), original: res.columns[1].values[0], bic: tbl._rt.rows[0].bic,
               varies: new Set(res.columns[1].values).size > 1, summary: res2.columns.map(c => c.name), sums: [1, 2].map(b => res2.columns.slice(1).reduce((a, c) => a + c.values[b], 0)),
               colors: Array.from(t.color).every((c, i) => c === colors[i]), options: JSON.stringify(rep.spec.options) === options, ncol: t.columns.length === ncol };
    })()''', timeout=600)
    check('Bootstrap of the BIC: a column named by the fit\'s text (method and NCluster), the report\'s value first, then the resamples\' own', (rb['names'], rb['n'], rb['finite'], rb['original'] == rb['bic'], rb['varies']), (['BootID', 'Normal Mixtures 3'], 4, True, True, True))
    check('Bootstrap of the Cluster Summary\'s counts: a column per cluster, adding to the rows of each resample', (rb['summary'], rb['sums']), (['BootID', '1', '2', '3'], [540, 540]))
    check('... and the reruns change nothing: no row colours (Color Clusters is on), no options, no columns', (rb['colors'], rb['options'], rb['ncol']), (True, True, True))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const d = new Promise(res => rep.on('done', res)); rep.spec.options.k = 2; rep.run(); await d;
      return t.color[0] !== -1 && t.color.slice(0, 540).every(c => c === 0 || c === 1);
    })()''')
    check('other clusters colour the rows again', r, True)
    await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const d = new Promise(res => rep.on('done', res)); rep.spec.options.k = 3; rep.spec.options.colorClusters = false; rep.run(); await d; rep.table.clearRowStates(); })()''')

    # ---- the profiler of the cluster probabilities
    await page.ev(pick_js('Normal Mixtures NCluster=3', ['Profiler']))
    for _ in range(40):
        pr = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const ob = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim().startsWith('Prediction Profiler'));
          return ob ? { plots: rep.plots.filter(p => /profil/i.test(p.opts.title || '')).length, text: ob.parentElement.textContent } : null; })()''')
        if pr and pr['plots']:
            break
        await asyncio.sleep(0.3)
    res = await page.ev(engine_fit_js())
    cur = await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const o = rep.spec.options; const cols = rep.spec.roles.y.map(id => t.col(id).name);
      const r = await SM.engine.call('mixtures.profile', { table: t.id, rows: null, columns: cols, freq: null, k_min: 3, k_max: 3, covariance: o.covariance || 'full', tours: o.tours ?? 10, outlier: !!o.outlier, standardize: o.scaled ?? true, seed: o.seedDrawn, max_iter: o.maxIter ?? 500, tol: o.tol ?? 1e-6, choose: 'bic', k: 3 }, t);
      return { names: r.responses.map(x => x.name), sum: r.responses.reduce((a, x) => a + x.current.pred, 0), factors: r.factors.map(f => f.name) }; })()''')
    check('the profiler: a probability per cluster over the three columns', (bool(pr and pr['plots']), cur['names'], cur['factors']), (True, ['Prob[Cluster 1]', 'Prob[Cluster 2]', 'Prob[Cluster 3]'], Y))
    check.near('... which add to 1 at the current setting', cur['sum'], 1.0, tol=1e-12)
    await triangles(page, 'the report with the profiler', 4)

    # ---- Redo and a project keep the options
    await page.ev(pick_js('*top*', ['Covariance Structure', 'Tied']))
    await rerun(page)
    st = await page.ev(STATE)
    check('Redo keeps the options', (st['options'].get('covariance'), st['options'].get('k')), ('tied', 3))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const before = [...rep.body.querySelectorAll('table.sm-rt')][0]._rt.rows.map(r => r.m2ll);
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] }));
      SM.app.loadProject(j);
      const back = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => { if (!back.body.classList.contains('is-running') && back.body.querySelector('.sm-ob')) res(); else back.on('done', res); });
      const after = [...back.body.querySelectorAll('table.sm-rt')][0]._rt.rows.map(r => r.m2ll);
      const out = { newTable: back.table !== t, cov: back.spec.options.covariance, seed: back.spec.options.seedDrawn === rep.spec.options.seedDrawn, before, after,
        heads: [...back.body.querySelectorAll('.sm-ob-head h3')].map(h => h.textContent), errors: back.body.querySelectorAll('.sm-ob-error').length };
      SM.app.closeTable(back.table);
      await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop();
      const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close');
      if (yes) yes.click();
      return out;
    })()''', timeout=600)
    check('an opened project has its own table, the covariance structure and the seed', (r['newTable'], r['cov'], r['seed']), (True, 'tied', True))
    check('... and the same fit, without errors', (r['after'] == r['before'], 'Normal Mixtures NCluster=3' in r['heads'], r['errors']), (True, True, 0))
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.filter(r => r.platform.id === "mixtures")[0]))')

    # ---- one column, Freq, By
    rep = await page.ev(open_report_js('mixtures', {'y': ['length (cm)']}, {'k': 3}), timeout=300)
    check('one column: the mixture density with the histogram, no biplot', ('Mixture Density' in rep['outlines'], 'Biplot' in rep['outlines'], rep['errors']), (True, False, []))
    r = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const p = rep.plots.find(p => /with the mixture/.test(p.opts.title));
      return { bars: p.kinds[0], curves: p.traces.filter(t => t.type === 'scatter').map(t => t.name) }; })()''')
    check('... its bars linked to the rows, a curve per cluster and the mixture', (r['bars'], r['curves'][:4]), ('bars', ['Cluster 1', 'Cluster 2', 'Cluster 3', 'Mixture']))
    await page.ev('''(() => { const t = SM.app.tables.find(t => t.name === 'Fish ages'); t.addColumn({ name: 'n', dataType: 'numeric', values: new Array(t.nrows).fill(2) }); })()''')
    await page.ev('SM.app.showTable(SM.app.tables.find(t => t.name === "Fish ages").id)')
    base_ = await page.ev(open_report_js('mixtures', {'y': Y}, {'k': 3, 'seed': 77}), timeout=300)
    one = await page.ev(table_under_js('Cluster Comparison', 0))
    rep = await page.ev(open_report_js('mixtures', {'y': Y, 'freq': ['n']}, {'k': 3, 'seed': 77}), timeout=300)
    two = await page.ev(table_under_js('Cluster Comparison', 0))
    st = await page.ev(STATE)
    check('Freq 2 for every row: 1080 observations', any(n.startswith('1,080 observations') or n.startswith('1080 observations') for n in st['notes']), True)
    check.near('... and twice the −2LogLikelihood', num(two[1][2]), 2 * num(one[1][2]), tol=1e-5)
    rep = await page.ev(open_report_js('mixtures', {'y': Y, 'by': ['lake']}, {'k': 3}), timeout=300)
    check('By lake: one analysis per lake', [o for o in rep['outlines'] if o.startswith('Normal Mixtures lake')], ['Normal Mixtures lake=North', 'Normal Mixtures lake=South'])
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const tbls = [...rep.body.querySelectorAll('table.sm-rt')].filter(t => t.dataset.rtKey === 'comparison');
      const combined = SM.report.combineRT(tbls, 'x');
      const t = rep.table; const lake = t.col('lake').values;
      return { n: tbls.length, groups: tbls.map(t => t.dataset.group), rows: combined.nrows, north: lake.filter(v => v === 'North').length,
               notes: [...rep.body.querySelectorAll('.sm-ob-note')].map(e => e.textContent).filter(t => /observations/.test(t)) };
    })()''')
    check('each lake has its comparison, which combine into one table', (r['n'], r['groups'], r['rows']), (2, ['lake=North', 'lake=South'], 2))
    check('each lake fits its own rows', r['notes'][0].startswith(f"{r['north']} observations"), True)

    # ---- the graphs' matplotlib code, run in the page
    await chart_code(page)

    # ---- the (i) topics and Help
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    helps = await page.ev('(() => { SM.app.showHelp("p-mixtures"); const row = document.getElementById("help-p-mixtures"); return row ? row.textContent : null; })()')
    check('the platform has its line in Help, with scikit-learn\'s GaussianMixture', bool(helps) and 'sklearn.mixture.GaussianMixture' in helps, True)
    topics = await page.ev('Object.keys(SM.platforms.get("mixtures").topics)')
    check('its topics', sorted(topics), sorted(['p:mixtures', 'mix:control', 'mix:comparison', 'mix:fit', 'mix:splom', 'mix:biplot']))

    # ---- the (i) explains every input: the launch dialog and the Iterative Clustering panel
    await page.ev('SM.app.showTable(SM.app.tables.find(t => t.name === "Fish ages").id)')
    await dialog_help(page, "SM.app.launch('mixtures')", 'mixtures', 'Normal Mixtures')
    first = 'SM.app.reports.filter(r => r.platform.id === "mixtures")[0]'
    s = await page.ev(info_js('slot', f"[...{first}.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Iterative Clustering')", f"{first}.body.querySelector('.sm-mix-controls')"))
    check('the Iterative Clustering panel\'s (i) names each of its fields, and Go', (len(s.get('inputs', [])), unexplained(s), [c[0] for cs in s['sections'].values() for c in cs][-1:]), (9, [], ['Go']))
    check('... each with what it does', all(len(t) > 30 for cs in s['sections'].values() for _, t in cs), True)

    # ---- dark theme and phone width
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.filter(r => r.platform.id === "mixtures")[0]))')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(2.5)
    st = await page.ev('''(() => { const rs = SM.app.reports.filter(r => r.platform.id === 'mixtures'); return { errors: rs.flatMap(r => [...r.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent)) }; })()''')
    check('the dark theme redraws the reports without errors', st['errors'], [])
    await shot(page, 'mix-04-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    await page.ev('(async () => { const rep = SM.app.reports.filter(r => r.platform.id === "mixtures")[0]; const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')
    await asyncio.sleep(1.0)
    r = await page.ev('''(() => {
      const rep = SM.app.reports.filter(r => r.platform.id === "mixtures")[0];
      const body = rep.body.getBoundingClientRect();
      // a graph inside a box that scrolls sideways by itself (the profiler's grid) may be wider
      const inScroller = (e) => { for (let x = e.parentElement; x && x !== rep.body; x = x.parentElement) { const o = getComputedStyle(x).overflowX; if (o === 'auto' || o === 'scroll') return true; } return false; };
      const boxes = rep.plots.filter(p => p.drawn && !inScroller(p.box)).map(p => p.box.getBoundingClientRect().right);
      return { page: document.documentElement.scrollWidth <= innerWidth + 1, plots: boxes.every(x => x <= body.right + 1), n: boxes.length, body: rep.body.scrollWidth <= rep.body.clientWidth + 1 };
    })()''')
    check('no horizontal page scroll at phone width', r['page'], True)
    check('the graphs fit the phone\'s width, the report does not scroll sideways', (r['plots'], r['n'] >= 1, r['body']), (True, True, True))
    await shot(page, 'mix-05-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


# ---- the graphs' matplotlib code --------------------------------------------------------------------------
# Each graph has its code block right under it, ending in plt.show(); the block runs in the page's own
# Python (the notebook's runner) and draws the Plotly graph above it: the rows in their clusters' colours,
# each cluster's ellipse, the biplot's centres and rays, the mixture density's bars and curves, the
# criteria of a range of fits, the titles and the size. The profiler has no code: it is interactive.
OPEN_MIX = r'''(async (roles, options) => {
  const t = SM.app.tables.find((x) => x.name === 'Fish ages');
  SM.app.showTab(SM.app.tabOf(t));
  const ids = {};
  for (const [k, names] of Object.entries(roles)) ids[k] = names.map((n) => t.col(n).id);
  const rep = SM.app.openReport(SM.platforms.get('mixtures'), { roles: ids, options }, t);
  await new Promise((res) => rep.on('done', res));
  // every fit's outline open, so that each draws its graphs
  for (const b of rep.body.querySelectorAll('.sm-ob.is-closed > .sm-ob-head .sm-ob-toggle')) b.click();
  await new Promise((r) => setTimeout(r, 600));
  return { g: await __gr.graphs(rep), undrawn: __gr.take(), errors: [...rep.body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent) };
})'''


def cells_of(F):
    return [a for a in F['axes'] if a['visible'] and (a['scatter'] or a['lines'])]


def check_splom(lab, g, F):
    tr = g['traces']
    pts = [t for t in tr if t.get('mode') == 'markers']
    axes = cells_of(F)
    check(f'{lab}: a plot for each pair below the diagonal', len(axes), len(pts))
    for ax, t in zip(axes, pts):
        got = ax['scatter'][0]['xy'] if ax['scatter'] else []
        check.near(f'{lab}: {t["name"]}: the rows', maxdiff([q for p in got for q in p], [q for p in points_of(t) for q in p]), 0, 1e-12)
        check(f'{lab}: {t["name"]}: each row in its cluster\'s colour', [c[:7] for c in ax['scatter'][0]['colors']] if ax['scatter'] else [], t['mcolor'])
    ells = [t for t in tr if t.get('mode') == 'lines']
    got = [ln for ax in axes for ln in ax['lines']]
    check(f'{lab}: an ellipse for each cluster in each plot', len(got), len(ells))
    check.near(f'{lab}: the ellipses are the page\'s', max((max(maxdiff(a['x'], b['x']), maxdiff(a['y'], b['y'])) for a, b in zip(got, ells)), default=0), 0, 1e-9)
    check(f'{lab}: the ellipses in their clusters\' colours', [ln['color'][:7] for ln in got], [t['color'] for t in ells])
    names = [t['name'] for t in pts]
    labels = [f'{a["ylabel"]} by {a["xlabel"]}' for a in axes if a['xlabel'] and a['ylabel']]
    check(f'{lab}: the columns on the axes', all(x in names for x in labels) and len(labels) >= 1, True)
    check(f'{lab}: the title and the size', ((F['suptitle'] or axes[0]['title']), F['size']), (g['label'], [g['w'] / 100, g['h'] / 100]))


def check_biplot(lab, g, F):
    ax = F['axes'][0]
    tr = g['traces']
    got = ax['scatter'][0]['xy'] if ax['scatter'] else []
    check.near(f'{lab}: the rows on the principal components', maxdiff([q for p in got for q in p], [q for p in points_of(tr[0]) for q in p]), 0, 1e-9)
    check(f'{lab}: each row in its cluster\'s colour', [c[:7] for c in ax['scatter'][0]['colors']] if ax['scatter'] else [], tr[0]['mcolor'])
    centres = [t for t in tr if t.get('mode') == 'markers+text']
    cs = [s['xy'][0] for s in ax['scatter'][1:1 + len(centres)] if s['xy']]
    check.near(f'{lab}: each cluster\'s centre', maxdiff([q for p in cs for q in p], [q for t in centres for q in (t['x'][0], t['y'][0])]), 0, 1e-9)
    fills = [t for t in tr if t.get('fill') == 'toself']
    outl = [ln for ln in ax['lines'] if len(ln['x']) == 73]
    check.near(f'{lab}: each cluster\'s ellipse', max((max(maxdiff(a['x'], b['x']), maxdiff(a['y'], b['y'])) for a, b in zip(outl, fills)), default=1e9) if len(outl) == len(fills) else 1e9, 0, 1e-9)
    rays = [t for t in tr if t.get('mode') == 'lines' and not t.get('fill')]
    if rays:
        want = [(a, b) for a, b in zip(rays[0]['x'], rays[0]['y']) if a is not None and not (a == 0 and b == 0)]
        ends = [(ln['x'][1], ln['y'][1]) for ln in ax['lines'] if len(ln['x']) == 2 and (ln['color'] or '')[:7] == '#786b5d']
        check.near(f'{lab}: the rays of the columns', maxdiff([q for p in ends for q in p], [q for p in want for q in p]), 0, 1e-9)
        text = [t for t in tr if t.get('mode') == 'text'][0]
        check(f'{lab}: the columns named at the rays\' ends', [t_['s'] for t_ in ax['texts']][-len(text['text']):], text['text'])
    check(f'{lab}: the legend: the clusters', [t for t in (ax['legend'] or F['legend'])], [t['name'] for t in tr if t.get('showlegend')])
    check(f'{lab}: the titles and the size', (ax['title'], ax['xlabel'], ax['ylabel'], F['size']), (g['label'], g['titles']['x'], g['titles']['y'], [g['w'] / 100, g['h'] / 100]))


def check_density(lab, g, F):
    ax = F['axes'][0]
    tr = g['traces']
    bar = [t for t in tr if t.get('type') == 'bar' and t.get('name') not in (None, '')][0]
    check.near(f'{lab}: the bars: the page\'s bins\' counts', max(maxdiff([b['h'] for b in ax['bars']], bar['y']), maxdiff([b['x'] + b['w'] / 2 for b in ax['bars']], bar['x'])), 0, 1e-9)
    for t in [t for t in tr if t.get('type') == 'scatter']:
        ln = [x for x in ax['lines'] if x['label'] == t['name']]
        check.near(f'{lab}: the curve of {t["name"]}', max(maxdiff(ln[0]['x'], t['x']), maxdiff(ln[0]['y'], t['y'])) if ln else 1e9, 0, 1e-9)
    check(f'{lab}: the legend', ax['legend'], [t['name'] for t in tr if t.get('showlegend') is not False and t.get('name')])
    check(f'{lab}: the titles and the size', (ax['title'], ax['xlabel'], ax['ylabel'], F['size']), (g['label'], g['titles']['x'], g['titles']['y'], [g['w'] / 100, g['h'] / 100]))


async def chart_code(page):
    await page.ev(GRAPHS_JS)
    table_js = "SM.app.tables.find((x) => x.name === 'Fish ages')"
    runs = [('three columns', {'y': Y}, {'k': 3, 'seed': 11}),
            ('a range of fits, 95% ellipses', {'y': Y}, {'k': 2, 'kRange': 4, 'seed': 12, 'tours': 3, 'k2|level': 0.95, 'k3|level': 0.95, 'k4|level': 0.95}),
            ('the outlier cluster, unscaled, no rays', {'y': Y}, {'k': 3, 'seed': 13, 'outlier': True, 'scaled': False, 'rays': False}),
            ('two columns, no ellipses', {'y': Y[:2]}, {'k': 3, 'seed': 14, 'ellipses': False}),
            ('one column, the outlier cluster', {'y': Y[:1]}, {'k': 3, 'seed': 15, 'outlier': True}),
            ('Freq, By lake, rows excluded', {'y': Y, 'freq': ['n'], 'by': ['lake']}, {'k': 2, 'seed': 16, 'tours': 2})]
    for tag, roles, options in runs:
        if tag.startswith('Freq'):   # a row of each lake excluded, and one more
            ex = await page.ev(f'(() => {{ const t = {table_js}; const lake = t.col("lake").values; const ex = [lake.indexOf("North"), lake.indexOf("South"), 30]; t.setState(ex, "excluded", true); return ex; }})()')
        r = await page.ev(f'({OPEN_MIX})({json.dumps(roles)}, {json.dumps(options)})', timeout=600)
        check(f'the graphs\' code ({tag}): no errors, every graph drawn', (r['errors'], r['undrawn']), ([], []))
        labels = [g['label'] for g in r['g']]
        for g in r['g']:
            check(f'the graphs\' code ({tag}): {g["label"]}: its code block is right under it, ending in plt.show()', bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()', True)
        if tag == 'a range of fits, 95% ellipses':
            check('a range of fits: the criteria graph and each fit\'s graphs', labels, ['Cluster criteria'] + [x for k in (2, 3, 4) for x in (f'Scatterplot Matrix, {k} clusters', f'Biplot, {k} clusters')])
        for g in r['g']:
            lab = f'the graphs\' code ({tag}): {g["label"]}'
            F, err = await run_graph(page, g, table_js)
            check(f'{lab}: runs in the page', err, None)
            if not F:
                continue
            F = F[0]
            if g['label'].startswith('Scatterplot'):
                check_splom(lab, g, F)
            elif g['label'].startswith('Biplot'):
                check_biplot(lab, g, F)
            elif ' with the mixture' in g['label']:
                check_density(lab, g, F)
            elif g['label'] == 'Cluster criteria':
                ax = F['axes'][0]
                for t in g['traces']:
                    ln = [x for x in ax['lines'] if x['label'] == t['name']]
                    check.near(f'{lab}: {t["name"]} of each number of clusters', max(maxdiff(ln[0]['x'], t['x']), maxdiff(ln[0]['y'], t['y'])) if ln else 1e9, 0, 1e-9)
                check(f'{lab}: the titles and the size', (ax['title'], ax['xlabel'], ax['ylabel'], F['size']), (g['label'], g['titles']['x'], g['titles']['y'], [g['w'] / 100, g['h'] / 100]))
            if tag.startswith('Freq'):
                check(f'{lab}: keeps its lake\'s rows and drops the excluded ones', ('df = df[df["lake"] == ' in g['code'], 'df = df.drop(index=[' in g['code']), (True, True))
    await page.ev(f'{table_js}.setState({json.dumps(ex)}, "excluded", false)')
    await page.ev("for (const r of SM.app.reports.filter((x) => x.platform.id === 'mixtures').slice(-6)) SM.app.closeReport(r)")


asyncio.run(main())
sys.exit(check.done())
