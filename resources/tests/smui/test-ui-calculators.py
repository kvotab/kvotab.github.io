#!/usr/bin/env python3
"""smui.html in a real browser: DOE > Sample Size Explorers > Test Calculators.

The platform sits in DOE > Sample Size Explorers after Sample Size and
Power and opens with no table: a Two Means and a Two Proportions test and
Multiple Tests. Values typed with real keys (Enter, Tab) are worked out at
once, in place: the field keeps the focus and the report is not drawn
again; Welch's t, its degrees of freedom and the pooled test are the ones
computed here from the fields, the proportions' pooled z too; the
Alternative, Variances, Compare and Test Method selects; Add Two Means and
Add Two Proportions (real clicks), and a test's red triangle (Rename,
Duplicate, Move Up, Remove); Multiple Tests against Holm's and
Benjamini-Hochberg's step formulas computed here; Alpha; Sample Size and
Power… opens that platform with the groups seen and computes the sample
size; every graph's code block run in the page's own Python gives the
graph; a project; the (i) topics explain every field; the dark theme,
phone width and no script errors.

Start a server on the repository root and headless Chrome (README.md) on
SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-calculators.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import math
import os
import sys

from cdp import BASE, Checks, open_page, wait_engine
from test_charts import GRAPHS_JS, figures_from_outputs, maxdiff, page_probe

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()
REP = "SM.app.reports.find((r) => r.platform.id === 'calculators')"


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.8)
        await page.shot(os.path.join(SHOTS, name))


def num(s):
    return float(str(s).replace('−', '-').replace('*', '').replace('<', ''))


# the kv tables of each test, as {label: text}; the outlines; errors
STATE = f'''
(() => {{
  const rep = {REP};
  const tests = [...rep.body.querySelectorAll('.sm-calc-results')].map((r) => Object.fromEntries([...r.querySelectorAll('table.sm-kv tr')].map((tr) => [tr.children[0].textContent.trim(), tr.children[1].textContent.trim()])));
  return {{ outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map((h) => h.textContent), tests, seq: rep.seq,
            errors: [...rep.body.querySelectorAll('.sm-ob-error, .sm-ob-warn')].map((e) => e.textContent), options: rep.spec.options }};
}})()
'''

AT = '''
((sel, text, within, n) => {
  const root = within ? (new Function('return ' + within))() : document;
  const els = [...root.querySelectorAll(sel)].filter(e => text == null || e.textContent.trim() === text || e.getAttribute('aria-label') === text);
  const e = els[n || 0];
  if (!e) return null;
  e.scrollIntoView({ block: 'center' });
  const b = e.getBoundingClientRect();
  return [b.left + b.width / 2, b.top + b.height / 2];
})
'''


async def click(page, sel, text=None, within=None, n=0):
    xy = await page.ev(f'({AT})({json.dumps(sel)}, {json.dumps(text)}, {json.dumps(within)}, {n})')
    if not xy:
        return False
    await page.click(xy[0], xy[1])
    await asyncio.sleep(0.15)
    return True


async def type_into(page, aria, text, n=0, end='Enter'):
    """Click the field (the n-th of its label), select what it holds, type text with real key events, then Enter or Tab."""
    ok = await click(page, 'input', aria, REP + '.body', n)
    await page.ev('document.activeElement.select()')
    await page.call('Input.insertText', {'text': text}, session=page.sid)
    await page.key(end, code=end)
    await asyncio.sleep(0.9)
    return ok


async def settle(page):
    for _ in range(100):
        if await page.ev(f'!{REP}.body.classList.contains("is-running")'):
            break
        await asyncio.sleep(0.1)
    await asyncio.sleep(0.5)


def welch(m1, s1, n1, m2, s2, n2):
    v1, v2 = s1 * s1 / n1, s2 * s2 / n2
    return (m1 - m2) / math.sqrt(v1 + v2), (v1 + v2) ** 2 / (v1 * v1 / (n1 - 1) + v2 * v2 / (n2 - 1))


async def run_tableless(page, code):
    out = await page.ev(f'SM.engine.runCell("charts", {json.dumps(page_probe(code))}, {{ tables: [], current: null, label: "chart", fresh: true }})', timeout=300)
    if isinstance(out, str):
        return None, out
    return figures_from_outputs(out.get('outputs'))


async def main():
    page = await open_page(f'{BASE}/smui.html', height=1200)
    check('engine ready', await wait_engine(page), 'ready')
    check('calculators.py imports in Pyodide', await page.ev('SM.engine.failed.filter(f => f.module === "calculators").map(f => f.error)'), [])
    sub = await page.ev('''(() => { const it = SM.app.menuItems('DOE').find(i => i.label === 'Sample Size Explorers'); return (typeof it.submenu === 'function' ? it.submenu() : it.submenu).filter(i => !i.separator).map(i => i.label); })()''')
    check('DOE > Sample Size Explorers: Sample Size and Power, then Test Calculators', sub[:2], ['Sample Size and Power', 'Test Calculators'])
    check('no table is open', await page.ev('SM.app.tables.length'), 0)
    await page.ev("SM.app.menuItems('DOE').find(i => i.label === 'Sample Size Explorers').submenu().find(i => i.label === 'Test Calculators').action()")
    await asyncio.sleep(0.5)
    await settle(page)
    st = await page.ev(STATE)
    check('it opens with no table: a Two Means and a Two Proportions test, and Multiple Tests', st['outlines'],
          ['Test Calculators', 'Test 1: Hypothesis Test for Two Means', 'Test 2: Hypothesis Test for Two Proportions', 'Other Methods', 'Multiple Tests'])
    check('... no errors', st['errors'], [])
    t = st['tests'][0]
    tw, dfw = welch(52.3, 14.1, 480, 49.8, 13.6, 495)
    check.near('Welch\'s t Ratio = the one computed here from the fields', num(t['t Ratio']), round(tw, 6), 1e-6)
    check.near('... its DF (Welch-Satterthwaite)', num(t['DF']), round(dfw, 4), 1e-6)
    p1, p2 = 58 / 1204, 41 / 1187
    pool = (58 + 41) / (1204 + 1187)
    zp = (p1 - p2) / math.sqrt(pool * (1 - pool) * (1 / 1204 + 1 / 1187))
    check.near('the proportions\' z = the pooled z computed here (the default method)', num(st['tests'][1]['z']), round(zp, 6), 1e-6)
    eng = await page.ev(f'SM.engine.call("calculators.compute", {{ tests: {REP}.spec.options.tests || SM.calculators.DEFAULT(), alpha: 0.05 }})')
    check('... and the engine\'s', (abs(num(t['Prob > |t|']) - eng['tests'][0]['p_two']) < 5.1e-5, abs(num(st['tests'][1]['Prob > |z|']) - eng['tests'][1]['p_two']) < 5.1e-5), (True, True))
    await shot(page, 'calc-01-open.png')

    # ---- typing with real keys: worked out in place, the field keeps the focus
    seq0 = st['seq']
    mark = await page.ev(f'(() => {{ const i = [...{REP}.body.querySelectorAll("input")].find(x => x.getAttribute("aria-label") === "Mean 1"); i.dataset.mark = "kept"; return true; }})()')
    await type_into(page, 'Mean 1', '55.5')
    st = await page.ev(STATE)
    tw, dfw = welch(55.5, 14.1, 480, 49.8, 13.6, 495)
    check.near('Mean 1 typed and Enter: the new t Ratio', num(st['tests'][0]['t Ratio']), round(tw, 6), 1e-6)
    f = await page.ev(f'(() => {{ const a = document.activeElement; return [a.getAttribute("aria-label"), a.dataset.mark || null, {REP}.seq]; }})()')
    check('... in place: the same field, still focused, the report not drawn again', (f[0], f[1], f[2]), ('Mean 1', 'kept', seq0))
    check('... kept in the report\'s options', (await page.ev(f'{REP}.spec.options.tests[0].g1.mean')), 55.5)
    await type_into(page, 'Std Dev 2', '21', end='Tab')
    st = await page.ev(STATE)
    tw, dfw = welch(55.5, 14.1, 480, 49.8, 21.0, 495)
    check.near('Std Dev 2 typed and Tab: worked out on leaving the field', num(st['tests'][0]['DF']), round(dfw, 4), 1e-6)
    check('... the focus moved on, to the next field', await page.ev('document.activeElement.getAttribute("aria-label")'), 'N 1')
    r = await page.ev(f'''(async () => {{
      const b = {REP}.body;
      const set = async (aria, v) => {{ const s = [...b.querySelectorAll('select')].find(x => x.getAttribute('aria-label') === aria); s.value = v; s.dispatchEvent(new Event('change')); await new Promise(r => setTimeout(r, 900)); }};
      await set('Variances', 'equal');
      const h4 = [...b.querySelectorAll('.sm-calc-test h4')].map(h => h.textContent);
      await set('Alternative', 'greater');
      const tails = {REP}.plots[0].traces.filter(t => t.fill === 'tozeroy').length;
      const note = [...b.querySelectorAll('.sm-calc-results')][0].querySelector('.sm-ob-note').textContent;
      return {{ h4, tails, note }};
    }})()''')
    st = await page.ev(STATE)
    df_p = 480 + 495 - 2
    sp = math.sqrt((479 * 14.1 ** 2 + 494 * 21.0 ** 2) / df_p)
    tp = (55.5 - 49.8) / (sp * math.sqrt(1 / 480 + 1 / 495))
    check('Variances ▸ Equal (pooled): the pooled t test', r['h4'][0], 't Test, pooled (equal variances)')
    check.near('... its t Ratio computed here', num(st['tests'][0]['t Ratio']), round(tp, 6), 1e-6)
    check('... DF = n₁ + n₂ − 2', num(st['tests'][0]['DF']), df_p)
    check('Alternative ▸ Greater: one tail shaded, the note names Prob > t', (r['tails'], 'Prob > t' in r['note']), (1, True))
    await type_into(page, 'Hypothesized Difference', '2')
    st = await page.ev(STATE)
    check.near('a hypothesized difference of 2: t of the difference less 2', num(st['tests'][0]['t Ratio']), round((55.5 - 49.8 - 2) / (sp * math.sqrt(1 / 480 + 1 / 495)), 6), 1e-6)
    check('... shown above the difference', 'Hypothesized Difference' in st['tests'][0], True)
    r = await page.ev(f'''(async () => {{
      const b = {REP}.body;
      const s = [...b.querySelectorAll('select')].find(x => x.getAttribute('aria-label') === 'Compare'); s.value = 'ratio'; s.dispatchEvent(new Event('change'));
      await new Promise(r => setTimeout(r, 900));
      const m = [...b.querySelectorAll('select')].find(x => x.getAttribute('aria-label') === 'Test Method');
      const nul = [...b.querySelectorAll('input')].find(x => x.getAttribute('aria-label') === 'Hypothesized Value');
      return {{ methods: [...m.options].map(o => o.textContent), placeholder: nul.placeholder }};
    }})()''')
    st = await page.ev(STATE)
    check('Compare ▸ Ratio: the ratio\'s methods, a null of 1', (r['methods'], r['placeholder']), (['Koopman (score)', 'Miettinen-Nurminen (score, n/(n − 1))', 'Katz (log)', 'Adjusted log (0.5 added)'], '1'))
    check.near('... the estimate p₁/p₂', num(st['tests'][1][f'Ratio (Group 1 / Group 2)']), round(p1 / p2, 6), 1e-6)
    await shot(page, 'calc-02-typed.png')

    # ---- adding tests, a test's red triangle, Multiple Tests
    await click(page, '.sm-calc-bar .sm-btn', 'Add Two Means')
    await settle(page)
    await click(page, '.sm-calc-bar .sm-btn', 'Add Two Proportions')
    await settle(page)
    st = await page.ev(STATE)
    check('Add Two Means, Add Two Proportions (clicks): four tests', [o for o in st['outlines'] if 'Hypothesis Test' in o], ['Test 1: Hypothesis Test for Two Means', 'Test 2: Hypothesis Test for Two Proportions', 'Test 3: Hypothesis Test for Two Means', 'Test 4: Hypothesis Test for Two Proportions'])
    r = await page.ev(f'''(async () => {{
      const rep = {REP};
      const pick = async (title, path, fill) => {{
        const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.querySelector('h3, h4') && h.querySelector('h3, h4').textContent === title);
        head.querySelector('.sm-ob-menu').click(); await new Promise(r => setTimeout(r, 60));
        const m = [...document.querySelectorAll('.sm-menu')].pop();
        const d = new Promise(res => rep.on('done', res));
        [...m.querySelectorAll('button')].find(b => b.querySelector('.sm-label').textContent === path).click();
        if (fill) {{ await new Promise(r => setTimeout(r, 300)); const dl = [...document.querySelectorAll('.sm-dialog')].pop(); const i = dl.querySelector('input'); i.value = fill; [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'OK').click(); }}
        await d; await new Promise(r => setTimeout(r, 400));
      }};
      await pick('Test 3: Hypothesis Test for Two Means', 'Rename…', 'Minutes');
      await pick('Minutes: Hypothesis Test for Two Means', 'Move Up');
      await pick('Test 4: Hypothesis Test for Two Proportions', 'Duplicate');
      await pick('Test 4 copy: Hypothesis Test for Two Proportions', 'Remove');
      return [...rep.body.querySelectorAll('.sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent).filter(t => /Hypothesis Test/.test(t));
    }})()''', timeout=300)
    check('a test\'s red triangle: Rename…, Move Up, Duplicate, Remove', r,
          ['Test 1: Hypothesis Test for Two Means', 'Minutes: Hypothesis Test for Two Means', 'Test 2: Hypothesis Test for Two Proportions', 'Test 4: Hypothesis Test for Two Proportions'])
    mt = await page.ev(f'''(() => {{ const rep = {REP}; const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(x => x.textContent.trim() === 'Multiple Tests');
      const tb = h.parentElement.querySelector('table.sm-rt'); return [...tb.querySelectorAll('tr')].map(tr => [...tr.children].map(c => c.textContent.trim())); }})()''')
    check('Multiple Tests: a line per test, the p-value and Holm\'s and Benjamini-Hochberg\'s', (mt[0], [row[0] for row in mt[1:]]),
          (['Test', 'p-Value', 'Holm', 'Benjamini-Hochberg (FDR)'], ['Test 1', 'Minutes', 'Test 2', 'Test 4']))
    eng = await page.ev(f'SM.engine.call("calculators.compute", {{ tests: {REP}.spec.options.tests, alpha: 0.05 }})')
    p = [t_['p'] for t_ in eng['tests']]
    m = len(p)
    o = sorted(range(m), key=lambda i: p[i])
    holm, run_ = [0.0] * m, 0.0
    for k, i in enumerate(o):
        run_ = max(run_, p[i] * (m - k))
        holm[i] = min(1.0, run_)
    bh, run_ = [0.0] * m, 1.0
    for k in range(m - 1, -1, -1):
        i = o[k]
        run_ = min(run_, p[i] * m / (k + 1))
        bh[i] = min(1.0, run_)
    fmtp = lambda v: v   # noqa: E731
    got_h = [num(row[2]) for row in mt[1:]]
    got_b = [num(row[3]) for row in mt[1:]]
    check('... Holm by the step-down formula computed here (4 decimals)', all(abs(a - b) < 5.1e-5 or (b < 1e-4 and a <= 1e-4) for a, b in zip(got_h, holm)), True)
    check('... Benjamini-Hochberg by the step-up formula computed here', all(abs(a - b) < 5.1e-5 or (b < 1e-4 and a <= 1e-4) for a, b in zip(got_b, bh)), True)

    # ---- Alpha, and Sample Size and Power with the groups seen
    await type_into(page, 'Alpha', '0.1')
    await settle(page)
    st = await page.ev(STATE)
    check('Alpha 0.1: every test at 0.1, the intervals at 90%', (st['tests'][0]['Confidence'], 'Lower 90%' in st['tests'][2]), ('0.9', True))
    n0 = await page.ev('SM.app.reports.length')
    await click(page, '.sm-calc-links .sm-btn', 'Sample Size and Power…', REP + '.body', 0)
    for _ in range(100):
        if await page.ev(f'SM.app.reports.length > {n0}'):
            break
        await asyncio.sleep(0.1)
    await asyncio.sleep(1.5)
    pw = await page.ev('''(() => { const rep = SM.app.reports.at(-1); const o = rep.spec.options; return { platform: rep.platform.id, sit: o.situation, inputs: o['in:two_means'],
      kv: [...rep.body.querySelectorAll('table.sm-kv tr')].map(tr => [tr.children[0].textContent.trim(), tr.children[1].textContent.trim()]) }; })()''')
    check('Sample Size and Power…: that platform, Two Sample Means', (pw['platform'], pw['sit']), ('power', 'two_means'))
    check.near('... the pooled standard deviation of the groups', pw['inputs']['sd'], sp, 1e-6)
    check('... the difference seen less the hypothesized one, the groups\' ratio, α and one side', (round(pw['inputs']['diff'], 6), round(pw['inputs']['ratio'], 6), pw['inputs']['alpha'], pw['inputs']['sides']), (round(55.5 - 49.8 - 2, 6), round(495 / 480, 6), 0.1, 1))
    check('... and it computes the sample size', any('(computed)' in k and 'Sample Size' in k and num(v) > 0 for k, v in pw['kv']), True)
    await page.ev('SM.app.closeReport(SM.app.reports.at(-1))')
    await page.ev(f'SM.app.showTab(SM.app.tabOf({REP}))')

    # ---- every graph's code, run in the page's own Python
    await page.ev(GRAPHS_JS)
    gs = await page.ev(f'__gr.graphs({REP})', timeout=300)
    check('every test has its graph, its code block right under it', [(bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()') for g in gs], [True] * 4)
    for g in gs:
        F, err = await run_tableless(page, g['code'])
        lab = f'graph {g["label"]}'
        check(f'{lab}: the code runs in the page', err, None)
        if not F:
            continue
        ax = F[0]['axes'][0]
        dens = [q for q in ax['lines'] if len(q['x']) > 10]
        tr0 = g['traces'][0]
        check.near(f'{lab}: the density, the page\'s', max(maxdiff(dens[0]['x'], tr0['x']), maxdiff(dens[0]['y'], tr0['y'])) if dens else 1.0, 0, 1e-12)
        vx = sorted(q['x'][0] for q in ax['lines'] if len(q['x']) == 2 and q['x'][0] == q['x'][1])
        check.near(f'{lab}: the critical values and the statistic, the page\'s lines', maxdiff(vx, sorted(s['x0'] for s in g['shapes'])), 0, 1e-12)
        check(f'{lab}: a shaded area per tail, the titles, the size', (len(ax['polys']), ax['title'], ax['xlabel'], ax['ylabel'], F[0]['size']),
              (len([t_ for t_ in g['traces'] if t_.get('fill') == 'tozeroy']), g['label'], g['titles']['x'], 'Density', [g['w'] / 100, g['h'] / 100]))

    # ---- a project keeps the tests
    r = await page.ev(f'''(async () => {{
      const rep = {REP};
      const j = JSON.parse(JSON.stringify({{ format: 'smui-project', version: 1, tables: [], reports: [rep.toJSON()] }}));
      SM.app.loadProject(j);
      const back = SM.app.reports.at(-1);
      await new Promise(res => {{ if (!back.body.classList.contains('is-running') && back.body.querySelector('.sm-ob')) res(); else back.on('done', res); }});
      await new Promise(r => setTimeout(r, 800));
      const kv = (r0) => [...r0.body.querySelectorAll('table.sm-kv')].map(t => t.textContent).join('|');
      const out = {{ tests: back.spec.options.tests.map(t => t.name), alpha: back.spec.options.alpha, same: kv(back) === kv(rep) }};
      SM.app.closeReport(back);
      return out;
    }})()''', timeout=300)
    check('a project: the tests, their inputs and α kept, the same results', (r['tests'], r['alpha'], r['same']), (['Test 1', 'Minutes', 'Test 2', 'Test 4'], 0.1, True))

    # ---- (i): every field explained
    for i, (title, heading) in enumerate((('Test 1: Hypothesis Test for Two Means', 'The fields'), ('Test 2: Hypothesis Test for Two Proportions', 'The fields'))):
        r = await page.ev(f'''(async () => {{
          const rep = {REP};
          const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.querySelector('h3, h4') && h.querySelector('h3, h4').textContent === {json.dumps(title)});
          const inputs = [...head.parentElement.querySelectorAll(':scope > .sm-ob-body .sm-calc-fields input, :scope > .sm-ob-body .sm-calc-fields select')].map(e => e.getAttribute('aria-label').replace(/ [12]$/, ''));
          head.querySelector('.info-btn').click(); await new Promise(r => setTimeout(r, 200));
          const p = document.querySelector('.info-panel');
          const names = [...p.querySelectorAll('dt')].map(dt => dt.textContent);
          KvotInfo.close();
          return {{ inputs: [...new Set(inputs)], names }};
        }})()''')
        check(f'{title}: its (i) explains every field', [x for x in r['inputs'] if not any(nm.startswith(x) for nm in r['names'])], [])
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic, every Help link a target', (audit.get('noTopic'), audit.get('brokenMore')), ([], []))
    helps = await page.ev('(() => { SM.app.showHelp("p-calculators"); const row = document.getElementById("help-p-calculators"); return row ? row.textContent : null; })()')
    check('Help lists the platform and what it uses', bool(helps) and 'ttest_ind_from_stats' in helps and 'multipletests' in helps, True)

    # ---- the dark theme, phone width
    await page.ev(f'SM.app.showTab(SM.app.tabOf({REP}))')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(2.5)
    await settle(page)
    st = await page.ev(STATE)
    check('the dark theme: drawn again without errors, the same tests', (st['errors'], len(st['tests'])), ([], 4))
    await shot(page, 'calc-03-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    await page.ev(f'(async () => {{ const rep = {REP}; const d = new Promise(res => rep.on("done", res)); rep.run(); await d; }})()', timeout=300)
    await asyncio.sleep(1.2)
    r = await page.ev(f'''(() => {{
      const rep = {REP}; const body = rep.body.getBoundingClientRect();
      const boxes = rep.plots.filter(p => p.drawn).map(p => p.box.getBoundingClientRect().right);
      const grid = rep.body.querySelector('.sm-calc-grid').getBoundingClientRect();
      return {{ page: document.documentElement.scrollWidth <= innerWidth + 1, plots: boxes.every(x => x <= body.right + 1), n: boxes.length, body: rep.body.scrollWidth <= rep.body.clientWidth + 1, grid: grid.right <= body.right + 1 }};
    }})()''')
    check('phone width: no horizontal page scroll, the graphs and the fields fit', (r['page'], r['plots'], r['n'] >= 1, r['body'], r['grid']), (True, True, True, True, True))
    await shot(page, 'calc-04-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


if __name__ == '__main__':
    asyncio.run(main())
    sys.exit(check.done())
