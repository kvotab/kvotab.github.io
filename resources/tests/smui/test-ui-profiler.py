#!/usr/bin/env python3
"""The shared Prediction Profiler's red triangle (smui-profiler.js,
profile.py) in a real browser, on GAM with the simulated ozone example:
Desirability Functions (the Desirability row and each response's function,
the current desirability against the backend's), Maximize Desirability
(the setting and prediction of '<area>.maximize' called directly), Set
Desirabilities (Minimize), Remember Settings (a table; a click goes back),
Assess Variable Importance (the Sobol indices of '<area>.importance'), a
project round trip; then Fit Model's profiler of two responses, whose
Maximize Desirability weighs both (against fitmodel.maximize); the dark
theme and phone width.

    python3 resources/tests/smui/test-ui-profiler.py
"""
import asyncio
import json
import os
import sys

from cdp import BASE, Checks, open_page, wait_engine

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()

H = '''
window.__p = {
  rep: () => SM.app.reports[SM.app.reports.length - 1],
  ob: (title, rep) => [...(rep || __p.rep()).body.querySelectorAll('.sm-ob')].find(o => o.querySelector(':scope > .sm-ob-head').textContent.trim() === title),
  menu: async (label, sub) => {
    __p.ob('Prediction Profiler').querySelector(':scope > .sm-ob-head .sm-ob-menu').click();
    await new Promise(r => setTimeout(r, 120));
    const find = (l) => [...[...document.querySelectorAll('.sm-menu')].pop().querySelectorAll('button')].find(b => b.querySelector('.sm-label') && b.querySelector('.sm-label').textContent === l);
    let b = find(label);
    if (!b) { SM.ui.closeMenus(); return 'missing'; }
    if (b.disabled) { SM.ui.closeMenus(); return 'disabled'; }
    b.click();
    if (sub) { await new Promise(r => setTimeout(r, 120)); b = find(sub); if (!b) { SM.ui.closeMenus(); return 'missing'; } b.click(); }
    return 'ok';
  },
  items: async () => {
    __p.ob('Prediction Profiler').querySelector(':scope > .sm-ob-head .sm-ob-menu').click();
    await new Promise(r => setTimeout(r, 120));
    const out = [...[...document.querySelectorAll('.sm-menu')].pop().querySelectorAll('button')].map(b => [b.querySelector('.sm-label').textContent, !b.disabled]);
    SM.ui.closeMenus(); return out;
  },
  vals: () => [...__p.ob('Prediction Profiler').querySelectorAll('.sm-prof-y .sm-prof-val')].map(e => Number(e.textContent.replace(/−/g, '-'))),
  done: (rep) => new Promise(res => (rep || __p.rep()).on('done', res)),
  // the payload the profiler sends (its source), for calling the backend directly
  payload: (rep) => __p.ob('Prediction Profiler', rep)._profiler.sources[0].payload,
};
true
'''


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await page.shot(os.path.join(SHOTS, name))


async def main():
    page = await open_page(f'{BASE}/smui.html?example=ozone', width=1400, height=1000)
    check('engine ready', await wait_engine(page), 'ready')
    await page.ev(H)
    r = await page.ev('''(async () => { const t = SM.app.current;
      const ids = { y: [t.col('ozone (ppb)').id], smooth: [t.col('temperature (°C)').id, t.col('wind (m/s)').id], linear: [t.col('weekend').id] };
      const rep = SM.app.openReport(SM.platforms.get('gam'), { roles: ids, options: { family: 'normal', smoothing: 'aic', df: 10, degree: 3, folds: 5, penalty: 1 } }, t);
      await __p.done(rep); return { ob: !!__p.ob('Prediction Profiler'), items: await __p.items() }; })()''', timeout=300)
    check('GAM\'s profiler is the shared one', r['ob'], True)
    check('its red triangle: desirability, remember, importance, reset, remove', r['items'], [['Desirability Functions', True], ['Maximize Desirability', False], ['Set Desirabilities…', False], ['Remember Settings', True], ['Assess Variable Importance', True], ['Reset Factor Settings', True], ['Remove', True]])

    # ---- Desirability Functions
    r = await page.ev('''(async () => { const rep = __p.rep(); await __p.menu('Desirability Functions'); await __p.done(rep);
      const ob = __p.ob('Prediction Profiler');
      const des = rep.spec.options['profilerDes:profiler'];
      const direct = await SM.engine.call('gam.profile', { ...__p.payload(rep), current: rep.spec.options['prof:'] || {}, des, alpha: 0.05 }, rep.table);
      return { names: [...ob.querySelectorAll('.sm-prof-y .sm-prof-name')].map(e => e.textContent), desPlots: ob.querySelectorAll('.sm-prof-des').length,
        spec: des, D: __p.vals()[1], want: direct.desirability.current, goal: des['ozone (ppb)'].goal, pts: des['ozone (ppb)'].points.map(p => p[1]) }; })()''', timeout=300)
    check('Desirability Functions: a Desirability row under the response', r['names'], ['ozone (ppb)', 'Desirability'])
    check('... and the response\'s desirability function at the right', r['desPlots'], 1)
    check('JMP\'s default: Maximize, 0.0183, 0.5, 0.9817', (r['goal'], r['pts']), ('max', [0.0183, 0.5, 0.9817]))
    check.near('the current desirability is the backend\'s', r['D'], round(r['want'], 5), 5e-5)
    await shot(page, 'profiler-desirability.png')

    # ---- Maximize Desirability = gam.maximize called directly
    r = await page.ev('''(async () => { const rep = __p.rep(); const before = __p.vals();
      const des = rep.spec.options['profilerDes:profiler'];
      const direct = await SM.engine.call('gam.maximize', { ...__p.payload(rep), current: rep.spec.options['prof:'] || {}, des, max_seed: 1, alpha: 0.05 }, rep.table);
      await __p.menu('Maximize Desirability');
      for (let i = 0; i < 200 && __p.vals()[0] === before[0]; i++) await new Promise(r => setTimeout(r, 50));
      return { before, after: __p.vals(), cur: rep.spec.options['prof:'], best: direct.best }; })()''', timeout=300)
    check('Maximize Desirability: the setting of gam.maximize', all(abs(r['cur'][k] - v) < 1e-9 for k, v in r['best']['setting'].items() if isinstance(v, (int, float))), True)
    check.near('... its prediction', r['after'][0], round(r['best']['predictions']['ozone (ppb)'], 4), 5e-4)
    check('... a higher prediction than before (Maximize)', r['after'][0] > r['before'][0], True)

    # ---- Set Desirabilities: Minimize
    r = await page.ev('''(async () => { const rep = __p.rep(); await __p.menu('Set Desirabilities…'); await new Promise(r => setTimeout(r, 250));
      const dlg = [...document.querySelectorAll('.sm-dialog')].pop();
      const sel = dlg.querySelector('select'); sel.value = 'min';
      const inputs = [...dlg.querySelectorAll('input')];
      inputs[1].value = '0.9817'; inputs[5].value = '0.0183';
      [...dlg.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'OK').click();
      await __p.done(rep);
      const before = __p.vals(); const des = rep.spec.options['profilerDes:profiler'];
      await __p.menu('Maximize Desirability');
      for (let i = 0; i < 200 && __p.vals()[0] === before[0]; i++) await new Promise(r => setTimeout(r, 50));
      const direct = await SM.engine.call('gam.maximize', { ...__p.payload(rep), current: {}, des, max_seed: 1, alpha: 0.05 }, rep.table);
      return { goal: des['ozone (ppb)'].goal, after: __p.vals(), best: direct.best.predictions['ozone (ppb)'], before }; })()''', timeout=300)
    check('Set Desirabilities: the goal is now Minimize', r['goal'], 'min')
    check('Maximize with Minimize: a lower prediction', r['after'][0] < r['before'][0], True)
    check.near('... the lowest gam.maximize finds', r['after'][0], round(r['best'], 4), 5e-3)

    # ---- Remember Settings, and a click back
    r = await page.ev('''(async () => { const rep = __p.rep(); const at = { ...rep.spec.options['prof:'] };
      await __p.menu('Remember Settings'); await __p.done(rep);
      const mem = __p.ob('Remembered Settings');
      const rows = mem ? [...mem.querySelectorAll('tbody tr')].length : 0;
      rep.spec.options['prof:'] = null; rep.run(); await __p.done(rep);
      const moved = { ...(rep.spec.options['prof:'] || {}) };
      __p.ob('Remembered Settings').querySelector('tbody tr').click(); await __p.done(rep);
      return { rows, heads: mem ? [...mem.querySelectorAll('thead th')].map(t => t.textContent) : [], back: rep.spec.options['prof:'], at, moved }; })()''', timeout=300)
    check('Remember Settings: a row with the factors, the prediction and the desirability', (r['rows'], r['heads']), (1, ['Setting', 'temperature (°C)', 'wind (m/s)', 'weekend', 'ozone (ppb)', 'Desirability']))
    check('a click on the row sets the factors back', all(abs(r['back'][k] - v) < 1e-9 if isinstance(v, (int, float)) else r['back'][k] == v for k, v in r['at'].items()), True)

    # ---- Assess Variable Importance = gam.importance
    r = await page.ev('''(async () => { const rep = __p.rep(); await __p.menu('Assess Variable Importance', 'Independent Uniform Inputs'); await __p.done(rep);
      const ob = [...rep.body.querySelectorAll('.sm-ob')].find(o => /^Variable Importance/.test(o.querySelector(':scope > .sm-ob-head').textContent.trim()));
      const rows = ob ? ob.querySelector('table.sm-rt')._rt.rows : [];
      const direct = await SM.engine.call('gam.importance', { ...__p.payload(rep), imp_method: 'uniform', imp_n: 1024, imp_seed: 1, alpha: 0.05 }, rep.table);
      return { title: ob ? ob.querySelector(':scope > .sm-ob-head').textContent.trim() : null, rows, want: direct.responses[0].rows }; })()''', timeout=300)
    check('Assess Variable Importance: its outline', r['title'], 'Variable Importance: Independent Uniform Inputs')
    got = {x['column']: x for x in r['rows']}
    check('main and total effects are gam.importance\'s', all(abs(got[w['column']]['main'] - w['main']) < 1e-12 and abs(got[w['column']]['total'] - w['total']) < 1e-12 for w in r['want']), True)
    check('temperature matters most (the example\'s truth)', max(r['rows'], key=lambda x: x['total'])['column'], 'temperature (°C)')
    await shot(page, 'profiler-importance.png')

    # ---- a project keeps the desirability and the remembered settings
    r = await page.ev('''(async () => { const rep = __p.rep(); const t = rep.table;
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] }));
      SM.app.loadProject(j);
      const back = SM.app.reports[SM.app.reports.length - 1];
      if (back.body.classList.contains('is-running') || !back.body.querySelector('.sm-ob')) await __p.done(back);
      const out = { goal: (back.spec.options['profilerDes:profiler'] || {})['ozone (ppb)']?.goal, mem: !!__p.ob('Remembered Settings', back), imp: back.body.innerText.includes('Variable Importance: Independent Uniform Inputs') };
      SM.app.closeReport(back); SM.app.closeTable(back.table); return out; })()''', timeout=300)
    check('a project keeps the desirability, the remembered settings and the importance', (r['goal'], r['mem'], r['imp']), ('min', True, True))

    # ---- Fit Model: two responses in one profiler, desirability weighing both
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables[0]))')
    r = await page.ev('''(async () => { const t = SM.app.tables[0]; const P = SM.platforms.get('fitmodel');
      const T = t.col('temperature (°C)'), W = t.col('wind (m/s)');
      const rep = SM.app.openReport(P, { roles: { y: [t.col('ozone (ppb)').id, W.id] }, options: { groupProfiler: true },
        effects: [{ cols: [T.id], names: [T.name], nest: [], nestNames: [], random: false }, { cols: [T.id, T.id], names: [T.name, T.name], nest: [], nestNames: [], random: false }] }, t);
      await __p.done(rep);
      const ob = __p.ob('Prediction Profiler');
      const names = [...ob.querySelectorAll('.sm-prof-y .sm-prof-name')].map(e => e.textContent);
      const src = ob._profiler.sources[0];
      // desirability: maximize ozone, match wind to 3 m/s
      rep.spec.options['profilerDes:groupProfiler'] = { 'ozone (ppb)': { goal: 'max', points: [[20, 0.0183], [50, 0.5], [80, 0.9817]], importance: 1 },
        'wind (m/s)': { goal: 'target', points: [[1, 0.0183], [3, 1], [5, 0.0183]], importance: 2 } };
      rep.run(); await __p.done(rep);
      const ob2 = __p.ob('Prediction Profiler');
      const des = rep.spec.options['profilerDes:groupProfiler'];
      const direct = await SM.engine.call('fitmodel.maximize', { ...ob2._profiler.sources[0].payload, current: {}, des, max_seed: 1, alpha: 0.05 }, t);
      ob2.querySelector(':scope > .sm-ob-head .sm-ob-menu').click(); await new Promise(r => setTimeout(r, 120));
      [...[...document.querySelectorAll('.sm-menu')].pop().querySelectorAll('button')].find(b => b.querySelector('.sm-label').textContent === 'Maximize Desirability').click();
      const val = () => [...ob2.querySelectorAll('.sm-prof-y .sm-prof-val')].map(e => Number(e.textContent.replace(/−/g, '-')));
      const before = val();
      for (let i = 0; i < 200 && val()[2] === before[2]; i++) await new Promise(r => setTimeout(r, 50));
      return { names, ys: src.payload.ys.map(e => e.y), kind: src.payload.kind, after: val(), best: direct.best, cur: rep.spec.options['groupProfiler:'] }; })()''', timeout=300)
    check('Fit Model: two responses in one profiler source', (r['names'], r['ys'], r['kind']), (['ozone (ppb)', 'wind (m/s)'], ['ozone (ppb)', 'wind (m/s)'], 'ls'))
    check.near('Fit Model: Maximize weighs both responses (the desirability of fitmodel.maximize)', r['after'][2], round(r['best']['desirability'], 5), 5e-5)
    check.near('... at its temperature', r['cur']['temperature (°C)'], r['best']['setting']['temperature (°C)'], 1e-9)

    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(1.2)
    await shot(page, 'profiler-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    check('phone width: no sideways scroll of the page', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
