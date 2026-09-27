#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Specialized Modeling > Mediation
and Analyze > Screening > Multiple Imputation.

Both backends import in Pyodide; the platforms are in their menus and their
example tables (Coaching study and Health survey, simulated) in File >
Examples and on the Home tab, row for row the tables the native tests make
(the page's seeded generator is ported here); every (i) has a topic and
Help has both platforms.

Mediation: the launch dialog casts the roles and offers the treatment's two
levels (or two values of a continuous treatment) and the model types; the
report has its outlines and no errors; the effects shown are the engine's
and near the example's known truth, the path diagram carries the models'
coefficients; the red triangles add the simulated distributions, the
interaction, change the outcome model, the method and the contrast; a
binary outcome is said to be on the probability scale; the progress of a
long run shows in the report bar; a theme change and a display option use
the cache; By gives a report per level; the dialog refuses what it must;
a project keeps the options.

Multiple Imputation: the launch dialog builds the analysis model (Add,
Cross); the report has its outlines; the pooled estimates are the
engine's, near the true coefficients where the complete cases are not;
lines of the missing-data reports and a bar of a diagnostic histogram
select their rows; the optional pooled columns are there; Save makes one
imputed table, all imputations stacked and averaged columns; the method
switches to the multivariate normal; the dialog refuses a nominal column
with missing values for the normal.

Every red triangle opens with its submenus; both reports draw in the dark
theme and at phone width without a horizontal scroll.

Start a server on the repository root and headless Chrome (the recipe is in
README.md) on SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-mediation.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import math
import os
import sys
from decimal import ROUND_HALF_UP, Decimal

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()
M32 = 0xffffffff


# ---- the page's seeded generator and the two example tables (as test_mediation.py and test_mi.py make them) ----
class Rng:
    def __init__(self, seed):
        s = str(seed)
        h = (1779033703 ^ len(s)) & M32
        for ch in s:
            h = ((h ^ ord(ch)) * 3432918353) & M32
            h = ((h << 13) & M32) | (h >> 19)
        self.h = h
        self.a, self.b, self.c, self.d = (self._next() for _ in range(4))
        self.spare = None

    def _next(self):
        h = self.h
        h = ((h ^ (h >> 16)) * 2246822507) & M32
        h = ((h ^ (h >> 13)) * 3266489909) & M32
        h ^= h >> 16
        self.h = h
        return h

    def u(self):
        a, b, c, d = self.a, self.b, self.c, self.d
        t = (a + b) & M32
        a = b ^ (b >> 9)
        b = (c + ((c << 3) & M32)) & M32
        c = ((c << 21) & M32) | (c >> 11)
        d = (d + 1) & M32
        t = (t + d) & M32
        c = (c + t) & M32
        self.a, self.b, self.c, self.d = a, b, c, d
        return t / 4294967296

    def normal(self, mu=0.0, sd=1.0):
        if self.spare is not None:
            z, self.spare = self.spare, None
            return mu + sd * z
        while True:
            x, y = 2 * self.u() - 1, 2 * self.u() - 1
            r = x * x + y * y
            if 0 < r < 1:
                break
        f = math.sqrt(-2 * math.log(r) / r)
        self.spare = y * f
        return mu + sd * x * f


def fixed(x, d):
    return float(Decimal(x).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP))


def coaching():
    r = Rng('mediation-coaching')
    n = 600
    arms = [0] * (n // 2) + [1] * (n // 2)
    for i in range(n - 1, 0, -1):
        j = math.floor(r.u() * (i + 1))
        arms[i], arms[j] = arms[j], arms[i]
    out = {'confidence': [], 'score': [], 'program': [], 'baseline': []}
    for i in range(n):
        age = max(20, min(65, math.floor(r.normal(38, 9) + 0.5)))
        sex = 'F' if r.u() < 0.5 else 'M'
        base = fixed(r.normal(50, 10), 1)
        t = arms[i]
        em, ey = r.normal(0, 3), r.normal(0, 5)
        mu = 20 + 0.3 * (base - 50) + 0.05 * (age - 38) + (1.0 if sex == 'F' else 0.0) + em
        m = [fixed(mu, 1), fixed(mu + 4, 1)]
        out['confidence'].append(m[t])
        out['score'].append(fixed(30 + 1.5 * m[t] + 2 * t + 0.4 * (base - 50) - 0.1 * (age - 38) + ey, 1))
        out['program'].append('coaching' if t else 'control')
        out['baseline'].append(base)
    return out


def health():
    r = Rng('incomplete-health-3')
    out = {'bmi': [], 'sbp': []}

    def L(z):
        return 1 / (1 + math.exp(-z))
    for _ in range(400):
        age = 25 + math.floor(r.u() * 51)
        bmi = fixed(20 + 0.08 * age + r.normal(0, 3.2), 1)
        act = fixed(max(0.0, 7 - 0.06 * age - 0.12 * (bmi - 25) + r.normal(0, 2)), 1)
        chol = fixed(3.6 + 0.03 * age + 0.04 * (bmi - 25) + r.normal(0, 0.8), 2)
        sbp = math.floor(60 + 0.45 * age + 1.1 * bmi + 3.5 * chol - 1.2 * act + r.normal(0, 9) + 0.5)
        mb = r.u() < L(-1.0 + 0.12 * (sbp - 130))
        r.u()
        r.u()
        out['bmi'].append(None if mb else bmi)
        out['sbp'].append(sbp)
    return out


async def shot(page, name, scroll=None):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        if scroll is not None:
            await page.ev(f'(() => {{ const rep = SM.app.reports.find(r => r.el.offsetParent !== null); const h = rep && [...rep.body.querySelectorAll(".sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4")].find(h => h.textContent === {json.dumps(scroll)}); if (h) rep.body.scrollTop = h.closest(".sm-ob").offsetTop - 10; }})()')
        await asyncio.sleep(0.9)
        await page.shot(os.path.join(SHOTS, name))


PICK = '''
(async (title, path, wait) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.querySelector('h2, h3, h4').textContent.trim() === title);
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


def pick_js(title, path, wait=True):
    return f'({PICK})({json.dumps(title)}, {json.dumps(path)}, {json.dumps(wait)})'


# Fill the open form dialog (values by field order; a select takes its value) and press OK.
FORM = '''
(async (values, wait) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  await new Promise(r => setTimeout(r, 150));
  const dlgs = [...document.querySelectorAll('.sm-dialog')];
  const d = dlgs[dlgs.length - 1];
  const inputs = [...d.querySelectorAll('.sm-form input, .sm-form select')];
  values.forEach((v, i) => { if (v != null) inputs[i].value = v; });
  const done = wait ? new Promise(res => rep.on('done', res)) : null;
  [...d.querySelectorAll('.sm-dialog-foot button')].find(b => b.textContent === 'OK').click();
  if (done) await done;
  return true;
})
'''


def form_js(values, wait=True):
    return f'({FORM})({json.dumps(values)}, {json.dumps(wait)})'


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
      for (const b of bs.filter(x => x.classList.contains('sm-sub') && !x.disabled)) {
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

# Cast columns into roles in the open launch dialog: [[column, role button], ...]
CAST = '''
((pairs) => {
  const dlg = document.querySelector('.sm-launch-dialog');
  const items = [...dlg.querySelectorAll('.sm-pick-list li')];
  for (const [name, role] of pairs) {
    items.forEach(li => li.classList.remove('is-selected'));
    const li = items.find(x => x.textContent === name);
    li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    [...dlg.querySelectorAll('.sm-role .sm-btn')].find(b => b.textContent === role).click();
  }
  return [...dlg.querySelectorAll('.sm-role-list')].map(u => [...u.querySelectorAll('li')].map(li => li.textContent));
})
'''

OK_DIALOG = '''
(async () => {
  const dlg = document.querySelector('.sm-launch-dialog');
  const n = SM.app.reports.length;
  [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK').click();
  if (SM.app.reports.length === n) return { refused: dlg.querySelector('.sm-launch-msg').textContent };
  const rep = SM.app.reports[SM.app.reports.length - 1];
  await new Promise(res => rep.on('done', res));
  return { title: rep.title, options: rep.spec.options, effects: rep.spec.effects || null,
           outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent),
           errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent), warns: [...rep.body.querySelectorAll('.sm-ob-warn')].map(e => e.textContent) };
})()
'''


def number(s):
    s = s.replace('−', '-').replace('*', '').replace('<', '')
    return float(s)


def rows_of(tbl):
    head = tbl[0]
    return {row[0]: dict(zip(head, row)) for row in tbl[1:]}


# The engine's results for the report's spec, straight from Python.
ENGINE = '''
(async (fn, payload) => { const rep = SM.app.reports[SM.app.reports.length - 1]; return SM.engine.call(fn, { rows: null, ...payload }, rep.table); })
'''


def engine_js(fn, payload):
    return f'({ENGINE})({json.dumps(fn)}, {json.dumps(payload)})'


async def mediation(page):
    # ---- the menu, the example, Help
    menus = await page.ev('''(() => {
      const an = SM.app.menuItems('Analyze');
      const sub = (name) => { const it = an.find(i => i.label === name); return (typeof it.submenu === 'function' ? it.submenu() : it.submenu).filter(i => !i.separator).map(i => i.label); };
      const file = SM.app.menuItems('File').find(i => i.label === 'Examples');
      const ex = (typeof file.submenu === 'function' ? file.submenu() : file.submenu).map(i => i.label);
      const home = [...document.querySelectorAll('.sm-exitem strong')].map(x => x.textContent);
      return { sm: sub('Specialized Modeling'), sc: sub('Screening'), ex, home };
    })()''')
    check('Analyze > Specialized Modeling lists Mediation', 'Mediation…' in menus['sm'], True)
    check('Analyze > Screening lists Multiple Imputation, after Explore Missing Values', 'Multiple Imputation…' in menus['sc'] and menus['sc'].index('Multiple Imputation…') == menus['sc'].index('Explore Missing Values…') + 1, True)
    for label in ('Coaching study (600 people): program, confidence, exam score', 'Health survey (400 people, missing values): blood pressure, age, BMI, cholesterol, activity'):
        check(f'File > Examples and the Home tab have {label.split(" (")[0]}', (label in menus['ex'], label in menus['home']), (True, True))
    ex = await page.ev('''(() => { const t = SM.app.current; const v = (n) => t.col(n).values;
      return { name: t.name, n: t.nrows, cols: t.columns.map(c => c.name + ':' + c.modelingType), confidence: v('confidence'), score: v('score'), program: v('program'), baseline: v('baseline'), truth: SM.io.EXAMPLES.mediation.truth }; })()''')
    check('the example table', (ex['name'], ex['n']), ('Coaching study', 600))
    check('its columns', ex['cols'], ['id:nominal', 'age:continuous', 'sex:nominal', 'baseline:continuous', 'program:nominal', 'confidence:continuous', 'score:continuous', 'passed:nominal'])
    py = coaching()
    check('it is, row for row, the table the native test makes (confidence, score, program, baseline)',
          all(ex[k] == py[k] for k in ('confidence', 'score', 'program', 'baseline')), True)
    truth = ex['truth']
    check.near('its true ACME, from both potential outcomes of everyone', truth['acme'][0], 6.0, 0.005)
    helps = await page.ev('(() => ["help-p-mediation", "help-p-mi"].map(id => { const h = document.getElementById(id); return h ? h.textContent : null; }))()')
    check('Help has Mediation, with statsmodels\' Mediation', bool(helps[0]) and 'statsmodels.stats.mediation.Mediation' in helps[0], True)
    check('Help has Multiple Imputation, with MICEData and BayesGaussMI', bool(helps[1]) and 'MICEData' in helps[1] and 'BayesGaussMI' in helps[1], True)

    # ---- the launch dialog
    await page.ev("SM.app.launch('mediation')")
    await asyncio.sleep(0.3)
    cast = await page.ev(f'({CAST})({json.dumps([["score", "Y, Outcome"], ["program", "Treatment"], ["confidence", "Mediator"], ["age", "Covariates"], ["sex", "Covariates"], ["baseline", "Covariates"]])})')
    check('the roles cast', cast[:4], [['score'], ['program'], ['confidence'], ['age', 'sex', 'baseline']])
    dlg = await page.ev('''(() => { const d = document.querySelector('.sm-launch-dialog'); const sels = [...d.querySelectorAll('.sm-med-launch select')];
      return { levels: [...sels[0].options].map(o => o.textContent), control: sels[0].value, treated: sels[1].value, models: [sels[2].value, sels[3].value], inputsHidden: [...d.querySelectorAll('.sm-med-launch input[type=text]')].slice(0, 2).map(i => i.hidden), nrep: d.querySelectorAll('.sm-med-launch input[type=text]')[2].value }; })()''')
    check('the dialog offers the treatment\'s two levels', dlg['levels'], ['control', 'coaching'])
    check('control is the first level, the treated the last', (dlg['control'], dlg['treated']), ('control', 'coaching'))
    check('the models follow the columns: least squares for both', dlg['models'], ['ols', 'ols'])
    check('the value boxes are for a continuous treatment: hidden', dlg['inputsHidden'], [True, True])
    check('1000 simulations by default', dlg['nrep'], '1000')
    await shot(page, 'mediation-00-launch.png')
    r = await page.ev(OK_DIALOG, timeout=300)
    TOP = 'Mediation of program on score through confidence'
    check('report title', r.get('title'), TOP)
    check('the options from the dialog', {k: r['options'].get(k) for k in ('control', 'treated', 'outcomeModel', 'mediatorModel', 'interaction', 'nRep', 'method', 'seed')},
          {'control': 'control', 'treated': 'coaching', 'outcomeModel': 'ols', 'mediatorModel': 'ols', 'interaction': False, 'nRep': 1000, 'method': 'parametric', 'seed': 1})
    check('the outlines', r['outlines'], [TOP, 'Path Diagram', 'Mediation Effects', 'Mediator Model', 'Outcome Model', 'Assumptions and Method'])
    check('no errors or warnings', (r['errors'], r['warns']), ([], []))
    await shot(page, 'mediation-01-report.png')

    # ---- the numbers: the engine's, near the truth
    base = {'y': 'score', 'treatment': 'program', 'mediator': 'confidence', 'covariates': ['age', 'sex', 'baseline'], 'outcome_model': 'ols', 'mediator_model': 'ols',
            'interaction': False, 'control': 'control', 'treated': 'coaching', 'n_rep': 1000, 'method': 'parametric', 'seed': 1, 'alpha': 0.05}
    eng = await page.ev(engine_js('mediation.fit', base), timeout=300)
    tbl = await page.ev(table_under_js('Mediation Effects', 0))
    check('the effects table: ten lines', [row[0] for row in tbl[1:]], ['ACME (control)', 'ACME (treated)', 'ACME (average)', 'ADE (control)', 'ADE (treated)', 'ADE (average)',
                                                                       'Total Effect', 'Prop. Mediated (control)', 'Prop. Mediated (treated)', 'Prop. Mediated (average)'])
    E = rows_of(tbl)
    fmt7 = await page.ev(f'{json.dumps([x["estimate"] for x in eng["effects"]["rows"]])}.map(v => SM.util.fmt(v))')
    check('every estimate is the engine\'s, as JMP formats it', [row[1] for row in tbl[1:]], fmt7)
    check('the p-values of no simulation across zero show as <0.002*', E['ACME (average)']['P-value'], '<0.002*')
    acme = (number(E['ACME (average)']['Lower 95%']), number(E['ACME (average)']['Upper 95%']))
    check(f'ACME (average) {E["ACME (average)"]["Estimate"]}: its interval covers the truth, {truth["acme"][0]:.3f}', acme[0] < truth['acme'][0] < acme[1], True)
    ade = (number(E['ADE (average)']['Lower 95%']), number(E['ADE (average)']['Upper 95%']))
    check(f'ADE (average) {E["ADE (average)"]["Estimate"]}: covers the truth, 2', ade[0] < 2 < ade[1], True)
    med_tbl = await page.ev(table_under_js('Mediator Model', 1))
    M = rows_of(med_tbl)
    ann = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const p = rep.plots.find(p => p.opts.title === 'mediation path diagram');
      return { texts: (p.userLayout.annotations || []).map(a => a.text), shapes: (p.userLayout.shapes || []).length, arrows: (p.userLayout.annotations || []).filter(a => a.showarrow).length }; })()''')
    a_text = next((t for t in ann['texts'] if t.startswith('a = ')), '')
    check('the path diagram: three boxes and three arrows', (ann['shapes'], ann['arrows']), (3, 3))
    a_model = number(M['program[coaching]']['Estimate'])
    check.near('its a is the mediator model\'s coefficient of the treatment (to 4 digits)', number(a_text[4:].split('<')[0]), float(f'{a_model:.4g}'), 1e-12)
    check('it shows ACME and ADE with their intervals', any(t.startswith('<b>ACME') for t in ann['texts']) and any(t.startswith('<b>ADE') for t in ann['texts']), True)
    forest = await page.ev('(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const p = rep.plots.find(p => p.opts.title === "mediation effects"); return p.traces.map(t => [t.name, t.x.length]); })()')
    check('the effects plot: ACME, ADE and the total', forest, [['ACME (indirect)', 3], ['ADE (direct)', 3], ['Total', 1]])
    notes = await page.ev('[...SM.app.reports[SM.app.reports.length - 1].body.querySelectorAll(".sm-ob-note")].map(n => n.textContent).join(" ")')
    check('the notes: sequential ignorability, and the product a × b of linear models', ('sequential ignorability' in notes, 'a × b' in notes), (True, True))
    code = await page.ev('SM.app.reports[SM.app.reports.length - 1].pythonScript()')
    check('the Python script: Mediation on the formula path, with the seed', all(s in code for s in ('from statsmodels.stats.mediation import Mediation', 'np.random.seed(1)', 'Mediation(outcome_model, mediator_model, "treat", "med").fit(method="parametric", n_rep=1000)')), True)

    # ---- the cache: a display option and the theme redraw without the engine
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      let calls = 0; const orig = SM.engine.call.bind(SM.engine); SM.engine.call = (...a) => { calls++; return orig(...a); };
      rep.spec.options.forest = false; await rep.run(); rep.spec.options.forest = true; await rep.run(); await rep.run('theme');
      SM.engine.call = orig;
      return calls;
    })()''')
    check('a display option and a theme change use the cache: no engine call', r, 0)

    # ---- the red triangles
    out = await page.ev(pick_js('Mediation Effects', ['Simulated Distributions']))
    check('Simulated Distributions: an outline with two histograms', 'Simulated Distributions' in out, True)
    h = await page.ev('(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; return rep.plots.filter(p => / simulated$/.test(p.opts.title || "")).map(p => p.traces[0].y.reduce((a, b) => a + b, 0)); })()')
    check('... of the 1000 simulated values each', h, [1000, 1000])
    await shot(page, 'mediation-02-draws.png', 'Simulated Distributions')
    out = await page.ev(pick_js(TOP, ['Treatment × Mediator Interaction']), timeout=300)
    ot = await page.ev(table_under_js('Outcome Model', 1))
    check('the interaction: its term in the outcome model', 'program[coaching]*confidence' in [row[0] for row in ot[1:]], True)
    lab = await page.ev('(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const p = rep.plots.find(p => p.opts.title === "mediation path diagram"); return (p.userLayout.annotations || []).map(a => a.text).find(t => t.startsWith("b = ")); })()')
    check('... and b at control and at treated on the diagram', 'at control' in lab and 'at treated' in lab, True)
    await page.ev(pick_js(TOP, ['Treatment × Mediator Interaction']), timeout=300)
    await page.ev(pick_js(TOP, ['Simulations…'], wait=False))
    progress = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const seen = [];
      const mo = new MutationObserver(() => seen.push(rep.noteEl.textContent));
      mo.observe(rep.noteEl, { childList: true, characterData: true, subtree: true });
      await new Promise(r => setTimeout(r, 150));
      const d = [...document.querySelectorAll('.sm-dialog')].pop();
      const inp = [...d.querySelectorAll('.sm-form input, .sm-form select')];
      inp[0].value = '3000'; inp[1].value = 'bootstrap'; inp[2].value = '7';
      const done = new Promise(res => rep.on('done', res));
      [...d.querySelectorAll('.sm-dialog-foot button')].find(b => b.textContent === 'OK').click();
      await done;
      mo.disconnect();
      return { seen: [...new Set(seen)].filter(s => /simulations…/.test(s)), opts: [rep.spec.options.nRep, rep.spec.options.method, rep.spec.options.seed] };
    })()''', timeout=600)
    check('Simulations…: 3000 bootstrap samples, seed 7', progress['opts'], [3000, 'bootstrap', 7])
    check('the report bar shows the progress of the run', len(progress['seen']) >= 3 and all('of 3000 simulations' in s for s in progress['seen']), True)
    summ = await page.ev(table_under_js(TOP, 0))
    check('the summary says so', [row[1] for row in summ if row[0] == 'Simulations'][0].startswith('3000, nonparametric bootstrap, seed 7'), True)
    E2 = rows_of(await page.ev(table_under_js('Mediation Effects', 0)))
    check('bootstrap: ACME still covers the truth', number(E2['ACME (average)']['Lower 95%']) < truth['acme'][0] < number(E2['ACME (average)']['Upper 95%']), True)
    await page.ev(pick_js(TOP, ['Method', 'Parametric (quasi-Bayesian)']), timeout=300)
    await page.ev(pick_js(TOP, ['Treatment Contrast…'], wait=False))
    await page.ev(form_js(['coaching', 'control']), timeout=300)
    E3 = rows_of(await page.ev(table_under_js('Mediation Effects', 0)))
    check('Treatment Contrast: control against coaching turns the effects round', number(E3['ACME (average)']['Estimate']) < 0 and number(E3['Total Effect']['Estimate']) < 0, True)
    await page.ev(pick_js(TOP, ['Treatment Contrast…'], wait=False))
    await page.ev(form_js(['control', 'coaching']), timeout=300)
    tri = await page.ev(TRIANGLES)
    check('every red triangle opens, with its submenus', (tri['errors'], tri['triangles'] >= 5, tri['items'] > tri['triangles']), ([], True, True))

    # ---- a project keeps the options
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      rep.spec.options.interaction = true; rep.spec.options.nRep = 400; await rep.run();
      const text = (r) => [...r.body.querySelectorAll('table.sm-rt')][0].textContent;
      const t = rep.table;
      const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] };
      const nrep = SM.app.reports.length;
      SM.app.loadProject(j);
      const r2 = SM.app.reports[nrep];
      await new Promise(res => r2.on('done', res));
      return { same: text(r2) === text(rep), opts: [r2.spec.options.interaction, r2.spec.options.nRep, r2.spec.options.treated] };
    })()''', timeout=300)
    check('a project keeps the options (interaction, simulations, treated level)', r['opts'], [True, 400, 'coaching'])
    check('... and gives the same effects', r['same'], True)

    # ---- a binary outcome, a continuous treatment, By
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === "Coaching study")))')
    r = await page.ev(open_report_js('mediation', {'y': ['passed'], 'treatment': ['program'], 'mediator': ['confidence'], 'covariates': ['age', 'sex', 'baseline']},
                                     {'control': 'control', 'treated': 'coaching', 'outcomeModel': 'probit', 'nRep': 600, 'seed': 3}), timeout=300)
    check('a binary outcome (probit): no errors', r['errors'], [])
    notes = await page.ev('[...SM.app.reports[SM.app.reports.length - 1].body.querySelectorAll(".sm-ob-note")].map(n => n.textContent).join(" ")')
    check('... its effects are said to be on the probability scale', 'passed is binary' in notes and 'probability' in notes, True)
    Eb = rows_of(await page.ev(table_under_js('Mediation Effects', 0)))
    tp = (truth['acmePassed'][0] + truth['acmePassed'][1]) / 2
    check(f'... ACME (average) covers the true change in P(passed), {tp:.3f}', number(Eb['ACME (average)']['Lower 95%']) < tp < number(Eb['ACME (average)']['Upper 95%']), True)
    await shot(page, 'mediation-03-binary.png')
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === "Coaching study")))')
    await page.ev("SM.app.launch('mediation')")
    await asyncio.sleep(0.3)
    await page.ev(f'({CAST})({json.dumps([["score", "Y, Outcome"], ["baseline", "Treatment"], ["confidence", "Mediator"], ["age", "Covariates"]])})')
    vals = await page.ev('''(() => { const d = document.querySelector('.sm-launch-dialog'); const ins = [...d.querySelectorAll('.sm-med-launch input[type=text]')];
      const t = SM.app.current; const v = t.col('baseline').values.filter(Number.isFinite).sort((a, b) => a - b); const n = v.length;
      const q = (p) => { const h = p * (n + 1), lo = Math.floor(h); return v[lo - 1] + (h - lo) * (v[lo] - v[lo - 1]); };
      return { shown: [ins[0].hidden, ins[1].hidden], values: [ins[0].value, ins[1].value], q: [+q(0.25).toPrecision(6), +q(0.75).toPrecision(6)] }; })()''')
    check('a continuous treatment: two values to compare, its quartiles to start with', (vals['shown'], [float(x) for x in vals['values']]), ([False, False], vals['q']))
    await shot(page, 'mediation-04-launch-continuous.png')
    r = await page.ev(OK_DIALOG, timeout=300)
    check('... the report runs', (r.get('errors'), r.get('title')), ([], 'Mediation of baseline on score through confidence'))
    summ = await page.ev(table_under_js('Mediation of baseline on score through confidence', 0))
    tr_row = [row[1] for row in summ if row[0] == 'Treatment'][0]
    check('... and says which two values it compares', f'{vals["q"][1]:g}' in tr_row and f'{vals["q"][0]:g}' in tr_row, True)
    r = await page.ev(open_report_js('mediation', {'y': ['score'], 'treatment': ['program'], 'mediator': ['confidence'], 'covariates': ['age', 'baseline'], 'by': ['sex']},
                                     {'control': 'control', 'treated': 'coaching', 'nRep': 300}), timeout=300)
    check('By: a report per level of sex', [o for o in r['outlines'] if o.startswith('Mediation of')], [f'{TOP} sex=F', f'{TOP} sex=M'])
    check('By: no errors', r['errors'], [])
    v = await page.ev('''(() => { const t = SM.app.tables.find(t => t.name === "Coaching study"); const P = SM.platforms.get('mediation'); const id = (n) => t.col(n).id;
      const o = { control: 'control', treated: 'coaching', outcomeModel: 'ols', mediatorModel: 'ols', nRep: 1000, seed: 1 };
      return [P.launch.validate({ roles: { y: [id('score')], treatment: [id('program')], mediator: [id('score')], covariates: [] }, options: o }, t),
              P.launch.validate({ roles: { y: [id('score')], treatment: [id('program')], mediator: [id('confidence')], covariates: [id('program')] }, options: o }, t),
              P.launch.validate({ roles: { y: [id('score')], treatment: [id('id')], mediator: [id('confidence')], covariates: [] }, options: o }, t),
              P.launch.validate({ roles: { y: [id('passed')], treatment: [id('program')], mediator: [id('confidence')], covariates: [] }, options: { ...o, outcomeModel: 'poisson' } }, t),
              P.launch.validate({ roles: { y: [id('score')], treatment: [id('baseline')], mediator: [id('confidence')], covariates: [] }, options: { ...o, control: 50, treated: 50 } }, t),
              P.launch.validate({ roles: { y: [id('score')], treatment: [id('program')], mediator: [id('confidence')], covariates: [] }, options: { ...o, nRep: 5 } }, t)]; })()''')
    check('the dialog refuses: the mediator as the outcome', v[0], 'The outcome, the treatment and the mediator must be three different columns.')
    check('... the treatment among the covariates', v[1], 'program is the treatment: take it out of the covariates.')
    check('... a treatment with 600 levels', v[2], 'The treatment takes a column with two levels, or a continuous one; id has 600.')
    check('... a Poisson model of a two-level outcome', v[3], 'passed (the outcome) is categorical: a Poisson model takes counts.')
    check('... one value of a continuous treatment', v[4], 'Give baseline two different values to compare: the control value and the treated value.')
    check('... five simulations', v[5], 'Simulations: a number from 20 to 100000.')


async def imputation(page):
    await page.ev("SM.app.openExample('incomplete')")
    await asyncio.sleep(0.5)
    ex = await page.ev('''(() => { const t = SM.app.current; return { name: t.name, n: t.nrows, cols: t.columns.map(c => c.name), bmi: t.col('bmi').values.map(v => Number.isNaN(v) ? null : v), sbp: t.col('sbp').values,
      miss: ['age', 'bmi', 'activity', 'cholesterol', 'sbp'].map(n => t.col(n).values.filter(v => Number.isNaN(v)).length), truth: SM.io.EXAMPLES.incomplete.truth }; })()''')
    check('the Health survey example', (ex['name'], ex['n'], ex['cols']), ('Health survey', 400, ['id', 'age', 'bmi', 'activity', 'cholesterol', 'sbp']))
    check('its missing values: none in age and sbp', ex['miss'], [0, 102, 84, 82, 0])
    py = health()
    check('it is, row for row, the table the native test makes (bmi with its gaps, sbp)', (ex['bmi'] == py['bmi'], ex['sbp'] == py['sbp']), (True, True))
    truth = ex['truth']

    # ---- the launch dialog: roles, the analysis model's effects
    await page.ev("SM.app.launch('mi')")
    await asyncio.sleep(0.3)
    await page.ev(f'({CAST})({json.dumps([[c, "Y, Columns to Impute"] for c in ["age", "bmi", "activity", "cholesterol", "sbp"]] + [["sbp", "Model Response"]])})')
    eff = await page.ev('''(() => {
      const dlg = document.querySelector('.sm-launch-dialog');
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const add = [...dlg.querySelectorAll('.sm-mi-tools .sm-btn')].find(b => b.textContent === 'Add');
      for (const n of ['age', 'bmi', 'cholesterol', 'activity']) {
        items.forEach(li => li.classList.remove('is-selected'));
        items.find(x => x.textContent === n).dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        add.click();
      }
      const effects = [...dlg.querySelectorAll('.sm-mi-effects li')].map(li => li.textContent);
      items.forEach(li => li.classList.remove('is-selected'));
      items.find(x => x.textContent === 'age').dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      items.find(x => x.textContent === 'bmi').dispatchEvent(new MouseEvent('mousedown', { bubbles: true, metaKey: true }));
      [...dlg.querySelectorAll('.sm-mi-tools .sm-btn')].find(b => b.textContent === 'Cross').click();
      const crossed = [...dlg.querySelectorAll('.sm-mi-effects li')].map(li => li.textContent);
      [...dlg.querySelectorAll('.sm-mi-effects li')].find(li => li.textContent === 'age*bmi').click();
      [...dlg.querySelectorAll('.sm-mi-tools .sm-btn')].find(b => b.textContent === 'Remove').click();
      const removed = [...dlg.querySelectorAll('.sm-mi-effects li')].map(li => li.textContent);
      items.forEach(li => li.classList.remove('is-selected'));
      return { effects, crossed, removed, model: dlg.querySelector('.sm-mi-tools select').value,
               placeholders: [...dlg.querySelectorAll('.sm-mi-row input')].slice(1, 3).map(i => i.placeholder) };
    })()''')
    check('Add puts each selected column in the analysis model', eff['effects'], ['age', 'bmi', 'cholesterol', 'activity'])
    check('Cross crosses the selected columns', eff['crossed'][-1], 'age*bmi')
    check('Remove takes the selected effect out', eff['removed'], ['age', 'bmi', 'cholesterol', 'activity'])
    check('the model follows the response: least squares', eff['model'], 'ols')
    check('the burn-in and skip boxes show statsmodels\' defaults for MICE', eff['placeholders'], ['10', '3'])
    await shot(page, 'mi-00-launch.png')
    r = await page.ev(OK_DIALOG, timeout=300)
    TOP = 'Multiple Imputation: sbp'
    check('report title', r.get('title'), TOP)
    check('the outlines', r['outlines'], [TOP, 'Missing Data', 'Missing Columns Report', 'Missing Value Report', 'Pooled Estimates', 'Imputation Diagnostics',
                                          'bmi: 102 missing, 20 imputations', 'activity: 84 missing, 20 imputations', 'cholesterol: 82 missing, 20 imputations', 'Method and Assumptions'])
    check('no errors or warnings', (r['errors'], r['warns']), ([], []))
    check('the options and the effects from the dialog', ({k: r['options'].get(k) for k in ('method', 'm', 'burnin', 'skip', 'seed', 'model')}, [e['names'] for e in r['effects']]),
          ({'method': 'mice', 'm': 20, 'burnin': None, 'skip': None, 'seed': 1, 'model': 'ols'}, [['age'], ['bmi'], ['cholesterol'], ['activity']]))
    await shot(page, 'mi-01-report.png')

    # ---- the pooled estimates: the engine's, near the truth; the complete cases not
    eng = await page.ev(engine_js('mi.fit', {'columns': ['age', 'bmi', 'activity', 'cholesterol', 'sbp'], 'response': 'sbp', 'effects': [['age'], ['bmi'], ['cholesterol'], ['activity']],
                                             'model': 'ols', 'method': 'mice', 'm': 20, 'burnin': None, 'skip': None, 'seed': 1, 'alpha': 0.05}), timeout=300)
    pooled = await page.ev(table_under_js('Pooled Estimates', 1))
    P = rows_of(pooled)
    fm = await page.ev(f'{json.dumps([x["estimate"] for x in eng["analysis"]["pooled"]["rows"]])}.map(v => SM.util.fmt(v))')
    check('the pooled estimates are the engine\'s', [row[1] for row in pooled[1:]], fm)
    check('with an FMI column', pooled[0], ['Term', 'Estimate', 'Std Error', 'z Ratio', 'Prob>|z|', 'Lower 95%', 'Upper 95%', 'FMI'])
    cc = rows_of(await page.ev(table_under_js('Pooled Estimates', 2)))
    names = ['Intercept', 'age', 'bmi', 'cholesterol', 'activity']
    zp = {n: (number(P[n]['Estimate']) - truth[n]) / number(P[n]['Std Error']) for n in names}
    zc = {n: (number(cc[n]['Estimate']) - truth[n]) / number(cc[n]['Std Error']) for n in names}
    check('every pooled estimate is within 2 standard errors of the true coefficient', all(abs(v) < 2 for v in zp.values()), True)
    check('the complete cases miss three or more by over 2 standard errors', sum(abs(v) > 2 for v in zc.values()) >= 3, True)
    hidden = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const t = [...rep.body.querySelectorAll('table.sm-rt')].find(x => x.dataset.rtKey === 'pooled' || (x.querySelector('caption') || {}).textContent === 'Pooled over 20 imputations (Rubin\\'s rules)');
      return t._rt.all.filter(c => c.hidden).map(c => c.label); })()''')
    check('the optional columns: W, B, T, RIV, DF, Prob>|t|, FMI (mice)', hidden, ['Within Var', 'Between Var', 'Total Var', 'RIV', 'DF', 'Prob>|t|', 'FMI (mice)'])

    # ---- linking: the missing-data reports and a diagnostic histogram
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const find = (title) => [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === title).parentElement.querySelector('table.sm-rt');
      [...find('Missing Columns Report').querySelectorAll('tbody tr')].find(tr => tr.children[0].textContent === 'bmi').click();
      const a = t.selectedRows();
      const bmiMiss = a.every(r => Number.isNaN(t.col('bmi').values[r]));
      [...find('Missing Value Report').querySelectorAll('tbody tr')].find(tr => tr.children[2].textContent === '01110').click();
      const b = t.selectedRows();
      const pat = b.every(r => Number.isNaN(t.col('bmi').values[r]) && Number.isNaN(t.col('activity').values[r]) && Number.isNaN(t.col('cholesterol').values[r]));
      const p = rep.plots.find(p => p.opts.title === 'bmi observed and imputed');
      p.box.scrollIntoView(); await new Promise(res => setTimeout(res, 100)); await p.draw();
      const ys = p.traces[0].y; let j = 0; ys.forEach((c, k) => { if (c > ys[j]) j = k; });
      p._click({ points: [{ curveNumber: 0, pointNumber: j }], event: {} });
      const c = t.selectedRows();
      const bins = p.traces[0].x, size = p.traces[0].width;
      const inBin = c.every(r => { const v = t.col('bmi').values[r]; return v >= bins[j] - size / 2 - 1e-9 && v < bins[j] + size / 2 + 1e-9; });
      t.select(c.slice(0, 3));
      await new Promise(res => setTimeout(res, 200));
      const lit = p.companions.map(k => p.box.data[k.at].x.length);
      t.select([]);
      return { a: a.length, bmiMiss, b: b.length, pat, c: c.length, inBin, lit };
    })()''')
    check('a line of the Missing Columns Report selects the rows missing that column', (r['a'], r['bmiMiss']), (102, True))
    check('a line of the Missing Value Report selects the rows with that pattern', (r['b'], r['pat']), (28, True))
    check('a bar of the observed bmi histogram selects its rows, with values in the bar', (r['c'] > 0, r['inBin']), (True, True))
    check('a table selection lights up the bars', sum(r['lit']) > 0, True)
    await shot(page, 'mi-02-diagnostics.png', 'Imputation Diagnostics')

    # ---- Save
    r = await page.ev(pick_js(TOP, ['Save', 'Imputed Table…'], wait=False))
    await page.ev(form_js(['3'], wait=False))
    await asyncio.sleep(0.4)
    one = await page.ev('''(() => { const t = SM.app.current; return { name: t.name, n: t.nrows, miss: ['bmi', 'activity', 'cholesterol'].map(n => t.col(n).values.filter(Number.isNaN).length), bmi: t.col('bmi').values }; })()''')
    check('Save > Imputed Table: a new table, no missing values left', (one['name'], one['n'], one['miss']), ('Health survey imputed 3 of 20', 400, [0, 0, 0]))
    imp_bmi = next(x for x in eng['imputed'] if x['column'] == 'bmi')
    check.near('its bmi is the third imputation where bmi was missing', max(abs(one['bmi'][r] - imp_bmi['draws'][2][k]) for k, r in enumerate(imp_bmi['rows'])), 0.0, 1e-12)
    await page.ev(f'SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.title === {json.dumps(TOP)})))')
    await page.ev(pick_js(TOP, ['Save', 'All 20 Imputations Stacked'], wait=False))
    await asyncio.sleep(0.4)
    st = await page.ev('''(() => { const t = SM.app.current; const imp = t.col('.imp').values, id = t.col('.id').values;
      return { name: t.name, n: t.nrows, first: t.columns.slice(0, 3).map(c => c.name), imps: [...new Set(imp)].length, ids: [id[0], id[399], id[400]], miss: t.col('bmi').values.filter(Number.isNaN).length }; })()''')
    check('Save > All Imputations Stacked: 20 × 400 rows, .imp and .id first', (st['n'], st['first'], st['imps'], st['ids'], st['miss']), (8000, ['.imp', '.id', 'id'], 20, [1, 400, 1], 0))
    await page.ev(f'SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.title === {json.dumps(TOP)})))')
    await page.ev(pick_js(TOP, ['Save', 'Average of the Imputations as New Columns'], wait=False))
    await asyncio.sleep(0.3)
    av = await page.ev('''(() => { const t = SM.app.tables.find(t => t.name === 'Health survey'); const c = t.col('Mean Imputed[bmi]');
      return c ? { n: c.values.filter(Number.isFinite).length, v: c.values, cols: t.columns.map(x => x.name).slice(-3) } : null; })()''')
    check('Save > Average: three new columns in the table', av and av['cols'], ['Mean Imputed[bmi]', 'Mean Imputed[activity]', 'Mean Imputed[cholesterol]'])
    r0 = imp_bmi['rows'][0]
    mean0 = sum(d[0] for d in imp_bmi['draws']) / len(imp_bmi['draws'])
    check.near('... a missing value is the mean of its 20 imputations', av['v'][r0], mean0, 1e-12)
    i0 = next(i for i, v in enumerate(ex['bmi']) if v is not None)
    check('... and the observed values stay', av['v'][i0], ex['bmi'][i0])

    # ---- the multivariate normal
    await page.ev(f'SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.title === {json.dumps(TOP)})))')
    await page.ev(pick_js(TOP, ['Method', 'Bayesian Gaussian (multivariate normal)']), timeout=300)
    summ = await page.ev(table_under_js(TOP, 0))
    check('Method > Bayesian Gaussian: its burn-in and skip are statsmodels\' MI defaults', [row[1] for row in summ if row[0] == 'Imputations'][0].startswith('20: after 100 cycles of burn-in, one every 11 cycles'), True)
    PB = rows_of(await page.ev(table_under_js('Pooled Estimates', 1)))
    zb = {n: (number(PB[n]['Estimate']) - truth[n]) / number(PB[n]['Std Error']) for n in names}
    check('... its pooled estimates are within 2 standard errors of the truth too', all(abs(v) < 2 for v in zb.values()), True)
    await shot(page, 'mi-03-bayes.png', 'Pooled Estimates')
    await page.ev(pick_js(TOP, ['Method', 'MICE (chained equations)']), timeout=300)
    tri = await page.ev(TRIANGLES)
    check('every red triangle opens, with its submenus', (tri['errors'], tri['triangles'] >= 6, tri['items'] > tri['triangles']), ([], True, True))

    # ---- impute only; refusals
    r = await page.ev(open_report_js('mi', {'y': ['age', 'bmi', 'activity', 'cholesterol', 'sbp']}, {'m': 5, 'seed': 2}), timeout=300)
    check('imputing only: the report without pooled estimates', ('Pooled Estimates' in r['outlines'], 'Imputation Diagnostics' in r['outlines'], r['errors']), (False, True, []))
    v = await page.ev('''(() => {
      const t0 = SM.app.tables.find(t => t.name === 'Health survey');
      const grp = t0.col('age').values.map((a, i) => (i % 9 === 0 ? null : a < 40 ? 'young' : a < 60 ? 'middle' : 'old'));
      const t = new SM.Table({ name: 'with a group', columns: [{ name: 'g', dataType: 'character', values: grp }, ...['age', 'bmi', 'sbp'].map(n => ({ name: n, dataType: 'numeric', values: t0.col(n).values.slice() }))] });
      const P = SM.platforms.get('mi'); const id = (n) => t.col(n).id;
      const o = { method: 'mice', m: 20, burnin: null, skip: null, seed: 1, model: 'ols' };
      return [P.launch.validate({ roles: { y: [id('g'), id('bmi')], response: [], by: [] }, options: o }, t),
              P.launch.validate({ roles: { y: [id('age'), id('bmi')], response: [], by: [] }, effects: [{ cols: [id('age')], names: ['age'] }], options: o }, t),
              P.launch.validate({ roles: { y: [id('bmi')], response: [], by: [] }, options: o }, t),
              P.launch.validate({ roles: { y: [id('age'), id('bmi')], response: [], by: [] }, options: { ...o, m: 1 } }, t),
              P.launch.validate({ roles: { y: [id('age'), id('bmi'), id('sbp')], response: [id('sbp')], by: [] }, effects: [{ cols: [id('sbp')], names: ['sbp'] }], options: o }, t)];
    })()''')
    check('the dialog refuses: a nominal column with three levels and missing values', v[0], "g is nominal with 3 levels and missing values: statsmodels' MICE imputes numeric, two-level and ordinal columns only.")
    check('... effects without a response', v[1], 'The analysis model needs a Model Response: cast one, or remove the effects to impute only.')
    check('... a single column', v[2], 'Multiple imputation needs two columns or more: each column is imputed from the others.')
    check('... one imputation', v[3], 'Imputations m: a whole number from 2 to 200.')
    check('... the response among the effects', v[4], 'sbp is the Model Response: take it out of the effects.')


async def main():
    page = await open_page(f'{BASE}/smui.html?example=mediation', height=1150)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "mediation" || f.module === "mi").map(f => f.module + ": " + f.error)')
    check('mediation.py and mi.py import in Pyodide', failed, [])
    check('no script errors at load', page.errors, [])
    await mediation(page)
    await imputation(page)

    # ---- (i) topics, the dark theme, phone width
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    for plat, title, scroll in (('mediation', 'Mediation of program on score through confidence', 'Path Diagram'), ('mi', 'Multiple Imputation: sbp', 'Pooled Estimates')):
        await page.ev(f'SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === {json.dumps(plat)} && r.title === {json.dumps(title)} && !(r.spec.roles.by || []).length)))')
        await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
        await asyncio.sleep(1.8)
        await shot(page, f'{plat}-05-dark.png')
        await shot(page, f'{plat}-06-dark-{scroll.lower().replace(" ", "-")}.png', scroll)
        errs = await page.ev('[...SM.app.reports.find(r => r.el.offsetParent !== null).body.querySelectorAll(".sm-ob-error")].map(e => e.textContent)')
        check(f'{plat}: the dark theme redraws without errors', errs, [])
        await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
        await asyncio.sleep(1.0)
        wide = await page.ev('document.documentElement.scrollWidth <= innerWidth + 1')
        check(f'{plat}: no horizontal page scroll at phone width', wide, True)
        await shot(page, f'{plat}-07-phone-dark.png', scroll)
        await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
        await asyncio.sleep(1.2)
        await shot(page, f'{plat}-08-phone-light.png', scroll)
        await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 1150, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
        await asyncio.sleep(0.6)
    dark = await page.ev('''(async () => { KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark'); await new Promise(r => setTimeout(r, 1500));
      const rep = SM.app.reports.find(r => r.platform.id === 'mediation'); const p = rep.plots.find(p => p.opts.title === 'mediation effects');
      const col = p.traces[0].marker.color; KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light'); return col; })()''')
    check('the dark theme draws the indirect path in its own blue', dark, '#4d8ad6')
    check('no script errors', page.errors, [])
    check('no console errors', [c for c in page.console if 'error' in c.lower() and 'favicon' not in c.lower()], [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
