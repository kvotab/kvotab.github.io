#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Specialized Modeling >
Time Series, on the Monthly sales example.

The platform is in the menu; the launch dialog casts sales, month and the
inputs; the report shows the mean, SD and N and the lag 1 autocorrelation
computed in the page, a date axis, the ADF and KPSS tests; ARIMA, seasonal
ARIMA, ARIMA Model Group, a smoothing model, state space smoothing and a
transfer function are added through the red triangle and their dialogs,
and land in the Model Comparison table; forecasts continue the months; the
Report and Graph boxes and the model red triangles do what they say; Save
Columns makes a new table; a click on a point selects its row and a table
selection shows in the graph; excluded rows count as missing values; By
gives a report per level; the models survive a saved and reopened project;
the report draws in the dark theme and at phone width.

Then what JMP does not have, on the Business cycle and Monthly sales
examples: the Zivot-Andrews test in Stationarity Tests with its break date
and options; Regime Switching through its dialog (regimes, transition
matrix, durations, the shaded series and the linked probabilities, the
starts, Save Regime Probabilities); the Hodrick-Prescott, Baxter-King and
Christiano-Fitzgerald filters with Save Columns; ARDL with the long run and
the bounds test at the model's k, forecasts from the future inputs, and
Fit New with fixed orders; the seasonal subseries plot, linked; a
structural model with its components and Save Components; the Theta model
and statsmodels' own intervals; all of them in reopened projects, the
script, the dark theme and at phone width.

Start a server on the repository root and headless Chrome on SMUI_HTTP_PORT
and SMUI_CDP_PORT (see README.md), then

    python3 resources/tests/smui/test-ui-timeseries.py

SMUI_SHOTS=<folder> saves screenshots. Exit status 0 when every check passes.
"""
import asyncio
import json
import os
import sys

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()

# Helpers in the page: pick from a red triangle, fill a form, wait for a report.
HELPERS = r'''
window.__ts = {
  rep() { return SM.app.reports[SM.app.reports.length - 1]; },
  // One-shot: the function rep.on returns cannot unsubscribe (Report's own
  // off field shadows Emitter.off), so a used listener just stays quiet.
  done(rep) { return new Promise((res) => { let once = false; rep.on('done', () => { if (!once) { once = true; res(); } }); }); },
  head(rep, title) { return [...rep.body.querySelectorAll('.sm-ob-head')].find((h) => h.textContent.trim().startsWith(title)); },
  async pick(btn, path) {
    btn.click();
    for (let i = 0; i < path.length; i++) {
      const menus = [...document.querySelectorAll('.sm-menu')];
      const m = menus[menus.length - 1];
      const b = [...m.querySelectorAll('button')].find((x) => x.querySelector('.sm-label') && x.querySelector('.sm-label').textContent === path[i]);
      if (!b) throw new Error('no menu item ' + path[i] + ' in ' + [...m.querySelectorAll('.sm-label')].map((x) => x.textContent).join(' | '));
      b.click();
    }
    await new Promise((r) => setTimeout(r, 60));
  },
  async menu(rep, title, path) {
    const h = title == null ? rep.body.querySelector('.sm-ob.level-0 > .sm-ob-head') : this.head(rep, title);
    if (!h) throw new Error('no outline ' + title);
    await this.pick(h.querySelector('.sm-ob-menu'), path);
  },
  async form(values, button) {
    await new Promise((r) => setTimeout(r, 120));
    const dlgs = [...document.querySelectorAll('.sm-dialog')];
    const dlg = dlgs[dlgs.length - 1];
    if (!dlg) throw new Error('no dialog');
    const title = dlg.querySelector('.sm-dialog-head h2').textContent;
    for (const [label, v] of Object.entries(values)) {
      const lab = [...dlg.querySelectorAll('.sm-form label')].find((l) => l.textContent === label);
      if (!lab) throw new Error('no field ' + label + ' in ' + title);
      const inp = document.getElementById(lab.htmlFor);
      if (inp.type === 'checkbox') inp.checked = !!v; else inp.value = String(v);
    }
    const b = [...dlg.querySelectorAll('.sm-dialog-foot .sm-btn')].find((x) => x.textContent === button);
    if (!b) throw new Error('no button ' + button);
    b.click();
    return title;
  },
  outlines(rep) { return [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map((h) => h.textContent); },
  problems(rep) { return { errors: [...rep.body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent.slice(0, 300)), warns: [...rep.body.querySelectorAll('.sm-ob-warn')].map((e) => e.textContent.slice(0, 200)) }; },
  cmpRows(rep) {
    const t = rep.body.querySelector('table.sm-ts-cmp');
    if (!t) return null;
    return [...t.querySelectorAll('tbody tr')].map((tr) => ({ name: tr.children[2].textContent, report: tr.children[0].querySelector('input').checked, graph: tr.children[1].querySelector('input').checked, id: tr.dataset.model }));
  },
};
true
'''


def num(text):
    """A number as the page shows it: JMP's minus sign (−), a star on a significant p-value."""
    return float(str(text).replace('−', '-').rstrip('*'))


async def shot(page, name, title=None):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    if title:   # scroll the report on show down to the outline (only vertically: the report body also scrolls sideways)
        await page.ev(f'''(() => {{ const rep = SM.app.reports.find(r => r.platform.id === 'timeseries' && r.body.offsetParent !== null) || SM.app.reports.find(r => r.platform.id === 'timeseries');
          document.querySelectorAll('.sm-toast').forEach(t => t.remove()); const h = __ts.head(rep, {json.dumps(title)});
          if (h) rep.body.scrollTop = h.getBoundingClientRect().top - rep.body.getBoundingClientRect().top + rep.body.scrollTop - 8; }})()''')
    await asyncio.sleep(1.0)
    await page.shot(os.path.join(SHOTS, name))


async def act(page, js, timeout=600):
    """Run an action that redraws the last report and wait until it is done."""
    return await page.ev(f'''(async () => {{ const rep = __ts.rep(); const d = __ts.done(rep); const out = await (async () => {{ {js} }})(); await d; return out; }})()''', timeout=timeout)


# ---- help for every input: the (i) of the launch dialog, of the forms and of the report's controls
HELP_JS = r'''
window.__hp = {
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  async waitNew(n0, sel) {
    for (let i = 0; i < 300; i++) { const d = [...document.querySelectorAll(sel)]; if (d.length > n0) return d[d.length - 1]; await this.sleep(50); }
    return null;
  },
  // The open (i) panel: its title and sections, each a heading with its [name, text] entries.
  panel() {
    const p = document.getElementById('kvot-info-panel');
    if (!p) return null;
    const sections = [{ heading: null, entries: [] }];
    for (const node of p.querySelector('.info-panel-body').children) {
      if (node.tagName === 'H3') sections.push({ heading: node.textContent, entries: [] });
      else if (node.matches('dl.info-choices')) {
        const dt = [...node.children].filter((x) => x.tagName === 'DT'), dd = [...node.children].filter((x) => x.tagName === 'DD');
        dt.forEach((t, i) => sections[sections.length - 1].entries.push([t.textContent, dd[i] ? dd[i].textContent : '']));
      }
    }
    return { title: p.querySelector('.info-panel-title').textContent, headings: sections.map((s) => s.heading).filter(Boolean), sections: sections.filter((s) => s.heading || s.entries.length) };
  },
  // Click an (i), read its panel, close it.
  async open(btn) {
    if (!btn) return null;
    btn.click();
    await this.sleep(80);
    const out = { key: btn.dataset.info, ...this.panel() };
    KvotInfo.close();
    return out;
  },
  audit() { const a = KvotInfo.audit(); return { noTopic: a.noTopic, brokenMore: a.brokenMore }; },
  showTable(name) { const t = SM.app.tables.find((x) => x.name === name); if (t) SM.app.showTab(SM.app.tabOf(t)); return !!t; },
  // Cast columns into a role of a launch dialog.
  cast(d, names, role) {
    const items = [...d.querySelectorAll('.sm-pick-list li')];
    names.forEach((n, i) => {
      const li = items.find((x) => x.textContent === n);
      if (!li) throw new Error('no column ' + n);
      li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, ctrlKey: i > 0 }));
    });
    [...d.querySelectorAll('.sm-role .sm-btn')].find((b) => b.textContent === role).click();
  },
  choose(d, aria, value) { const s = d.querySelector(`select[aria-label="${aria}"]`); s.value = value; s.dispatchEvent(new Event('change', { bubbles: true })); },
  // A launch dialog's (i) after prep(dialog), audited while the dialog is open; then Cancel.
  async launch(id, prep) {
    const n0 = document.querySelectorAll('.sm-launch-dialog').length;
    SM.app.launch(id);
    const d = await this.waitNew(n0, '.sm-launch-dialog');
    if (!d) throw new Error('no launch dialog');
    if (prep) { await prep(d); await this.sleep(80); }
    const info = await this.open(d.querySelector('.sm-dialog-head .info-btn'));
    const audit = this.audit();
    const L = SM.platforms.get(id).launch;
    [...d.querySelectorAll('.sm-actions .sm-btn')].find((b) => b.textContent === 'Cancel').click();
    await this.sleep(60);
    return { info, audit, roles: (L.roles || []).map((r) => r.label), options: (L.options || []).map((o) => o.label) };
  },
  head(rep, title) { return [...rep.body.querySelectorAll('.sm-ob-head')].find((h) => { const t = h.querySelector('h2, h3, h4'); return t && t.textContent === title; }); },
  // Pick from the red triangle of an outline (null: the top one), without waiting for a redraw.
  async menu(rep, title, path) {
    const h = title == null ? (rep.body.querySelector('.sm-ob.level-0 > .sm-ob-head') || rep.body.querySelector('.sm-ob-head')) : this.head(rep, title);
    if (!h) throw new Error('no outline ' + title);
    h.querySelector('.sm-ob-menu').click();
    for (const label of path) {
      await this.sleep(40);
      const m = [...document.querySelectorAll('.sm-menu')].pop();
      const b = m && [...m.querySelectorAll('button')].find((x) => x.querySelector('.sm-label') && x.querySelector('.sm-label').textContent === label);
      if (!b) { SM.ui.closeMenus(0); throw new Error('no menu item ' + label); }
      b.click();
    }
  },
  // A form that open() brings up: its fields' labels and its (i), audited while open; then closed.
  async form(open) {
    const n0 = document.querySelectorAll('.sm-dialog').length;
    await open();
    const d = await this.waitNew(n0, '.sm-dialog');
    if (!d) throw new Error('no form opened');
    const info = await this.open(d.querySelector('.sm-dialog-head .info-btn'));
    const audit = this.audit();
    const out = { title: d.querySelector('.sm-dialog-head h2').textContent, labels: [...d.querySelectorAll('.sm-form label')].map((l) => l.textContent), info, audit };
    d.querySelector('.sm-dialog-x').click();
    await this.sleep(60);
    return out;
  },
  // An outline's own (i).
  async outline(rep, title) { const h = this.head(rep, title); return h ? this.open(h.querySelector('.kvot-info-slot .info-btn')) : null; },
};
true
'''


def help_section(info, heading):
    """The [name, text] entries of a section of an (i) panel, as a dict; None when there is none."""
    for s in (info or {}).get('sections', []):
        if s['heading'] == heading:
            return dict(s['entries'])
    return None


async def check_launch_help(page, pid, settings=None, prep='null', what=None):
    """A launch dialog's (i): every role and option with its help, the fields
    of the platform's own part (settings), and a topic for every (i) while the
    dialog is open."""
    what = what or f'{pid}: the launch dialog'
    r = await page.ev(f'__hp.launch({json.dumps(pid)}, {prep})', timeout=300)
    if not isinstance(r, dict):
        check(f'{what}: opens', r, 'a dialog')
        return None
    info = r['info'] or {}
    roles = help_section(info, 'Roles') or {}
    check(f'{what}: its (i) lists every role', list(roles), r['roles'])
    check(f'{what}: every role has help beyond what it takes', [k for k, t in roles.items() if t.startswith('(') or len(t) < 80], [])
    check(f'{what}: one Roles section (the topic\'s gives way to it)', info.get('headings', []).count('Roles'), 1)
    opts = help_section(info, 'Options') or {}
    check(f'{what}: its (i) lists every option', list(opts), r['options'])
    check(f'{what}: every option has help', [k for k, t in opts.items() if len(t) < 60], [])
    if settings is not None:
        got = help_section(info, 'Settings') or {}
        check(f'{what}: its (i) explains the fields of the platform\'s own part', list(got), settings)
        check(f'{what}: none of them in a word', [k for k, t in got.items() if len(t) < 30], [])
    check(f'{what}: every (i) has a topic while it is open', r['audit']['noTopic'], [])
    check(f'{what}: every Help link has a target', r['audit']['brokenMore'], [])
    return info


async def check_form_help(page, open_js, fields, what):
    """A form's (i) lists every field with its help, in order (fields: the names shown)."""
    r = await page.ev(f'__hp.form(async () => {{ {open_js} }})', timeout=300)
    if not isinstance(r, dict):
        check(f'{what}: opens', r, 'a dialog')
        return None
    got = help_section(r['info'], 'Fields') or {}
    check(f'{what}: its (i) explains every field', list(got), fields)
    check(f'{what}: none of them in a word', [k for k, t in got.items() if len(t) < 30], [])
    check(f'{what}: every (i) has a topic while it is open', r['audit']['noTopic'], [])
    return r


async def check_controls_help(page, rep_js, title, names, what, heading='In the report'):
    """An outline's (i) explains the controls inside the report, in a section of choices."""
    info = await page.ev(f'__hp.outline({rep_js}, {json.dumps(title)})')
    got = help_section(info, heading) or {}
    check(f'{what}: its (i) explains the controls in the report', list(got), names)
    check(f'{what}: none of them in a word', [k for k, t in got.items() if len(t) < 30], [])
    return info


async def main():
    page = await open_page(f'{BASE}/smui.html?example=sales')
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "timeseries").map(f => f.error)')
    check('the timeseries module imports', failed, [])
    check('its backend functions are there', await page.ev('["timeseries.series", "timeseries.arima", "timeseries.smooth", "timeseries.ets", "timeseries.spectral"].every(n => SM.engine.has(n))'), True)
    await page.ev(HELPERS)
    menu = await page.ev('''(() => { const it = SM.app.menuItems("Analyze").find(i => i.label === "Specialized Modeling"); const sub = typeof it.submenu === "function" ? it.submenu() : it.submenu; return sub.map(i => i.label); })()''')
    check('Analyze > Specialized Modeling lists Time Series', 'Time Series…' in (menu or []), True)
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    check('the Help tab lists the platform', await page.ev('!!document.getElementById("help-p-timeseries")'), True)

    # ---- the launch dialog
    r = await page.ev('''(async () => {
      SM.app.launch('timeseries');
      await new Promise(r => setTimeout(r, 200));
      const dlg = document.querySelector('.sm-launch-dialog');
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => { const li = items.find(li => li.textContent === name); li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); };
      const role = (label) => [...dlg.querySelectorAll('.sm-role .sm-btn')].find(b => b.textContent === label);
      pick('sales'); role('Y, Time Series').click();
      pick('month'); role('X, Time ID').click();
      pick('promotion'); role('Input List').click();
      pick('temperature'); role('Input List').click();
      const opt = (label) => [...dlg.querySelectorAll('.sm-launch-opts label')].find(l => l.textContent.startsWith(label)).querySelector('input');
      opt('Forecast Periods').value = '12';
      const lists = [...dlg.querySelectorAll('.sm-role-list')].map(u => u.textContent);
      const roles = [...dlg.querySelectorAll('.sm-role .sm-btn')].map(b => b.textContent);
      [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK').click();
      const rep = __ts.rep();
      await __ts.done(rep);
      return { lists, roles, title: rep.title, open: !!document.querySelector('.sm-launch-dialog'), outlines: __ts.outlines(rep), ...__ts.problems(rep) };
    })()''', timeout=600)
    check("JMP's roles", r['roles'], ['Y, Time Series', 'Input List', 'X, Time ID', 'By'])
    check('cast', r['lists'][:3], ['sales', 'promotiontemperature', 'month'])
    check('report title', r['title'], 'Time Series sales')
    check('default outlines', [o for o in r['outlines'] if o in ('Time Series sales', 'Time Series Basic Diagnostics', 'Stationarity Tests', 'Input Time Series Panel')],
          ['Time Series sales', 'Time Series Basic Diagnostics', 'Stationarity Tests', 'Input Time Series Panel'])
    check('no errors', (r['errors'], r['warns']), ([], []))

    # ---- numbers against the page's own arithmetic
    js = await page.ev('''(() => { const v = SM.app.current.col('sales').values; const n = v.length; const m = v.reduce((a, b) => a + b, 0) / n;
      const c0 = v.reduce((a, b) => a + (b - m) ** 2, 0); let c1 = 0; for (let t = 1; t < n; t++) c1 += (v[t] - m) * (v[t - 1] - m);
      return { mean: SM.util.fmt(m), sd: SM.util.fmt(Math.sqrt(c0 / (n - 1))), n: String(n), r1: (c1 / c0).toFixed(4) }; })()''')
    kv = await page.ev('''(() => { const rep = __ts.rep(); const k = rep.body.querySelector('.sm-ob.level-0 > .sm-ob-body table.sm-kv'); return [...k.querySelectorAll('tr')].map(tr => [...tr.children].map(c => c.textContent)); })()''')
    kvd = dict((a, b) for a, b in kv)
    check('Mean, SD and N as computed in the page', [kvd.get('Mean'), kvd.get('SD'), kvd.get('N')], [js['mean'], js['sd'], js['n']])
    check('the ADF tests are listed beside the graph', all(k in kvd for k in ('Zero Mean ADF', 'Single Mean ADF', 'Trend ADF')), True)
    acf = await page.ev(table_under_js('Time Series Basic Diagnostics'))
    check('Autocorrelation columns', acf[0][:2] + acf[0][3:], ['Lag', 'AutoCorr', 'Ljung-Box Q', 'p-Value'])
    check('lag 1 autocorrelation as computed in the page', acf[2][1], js['r1'])
    check('lags 0 to 25', (acf[1][0], acf[-1][0]), ('0', '25'))
    check('a bar in every row', await page.ev('__ts.rep().body.querySelectorAll("table.sm-ts-corr td.sm-ts-barcell svg rect.bar").length >= 52'), True)
    stt = await page.ev(table_under_js('Stationarity Tests'))
    check('stationarity tests', [row[0] for row in stt[1:]], ['Zero Mean ADF', 'Single Mean ADF', 'Trend ADF', 'KPSS Level', 'KPSS Trend'])
    ax = await page.ev('''(async () => { const rep = __ts.rep(); const p = rep.plots.find(p => p.opts.title === 'sales time series'); await p.draw(); return { type: p.box._fullLayout.xaxis.type, x0: p.traces[0].x[0], n: p.traces[0].x.length }; })()''')
    check('the Time ID gives a date axis', ax, {'type': 'date', 'x0': '2016-01-01', 'n': 120})
    check('the note gives the frequency', await page.ev('__ts.rep().body.textContent.includes("Monthly data; seasonal period 12.")'), True)
    await shot(page, 'ts-01-series.png')

    # ---- linking both ways
    r = await page.ev('''(async () => {
      const rep = __ts.rep(); const t = rep.table; const p = rep.plots.find(p => p.opts.title === 'sales time series');
      p._click({ points: [{ curveNumber: 0, pointNumber: 40 }], event: {} });
      const sel = t.selectedRows();
      t.select([5, 6, 7]);
      await new Promise(r => setTimeout(r, 150));
      const sp = p.box.data[0].selectedpoints;
      t.select([]);
      return { sel, sp: Array.from(sp || []) };
    })()''')
    check('a click on a point selects its row', r['sel'], [40])
    check('a table selection lights up the points', r['sp'], [5, 6, 7])

    # ---- ARIMA through the red triangle and its dialog
    r = await act(page, '''await __ts.menu(__ts.rep(), null, ['ARIMA…']); return await __ts.form({ 'p, Autoregressive Order': 1, 'q, Moving Average Order': 1 }, 'Estimate');''')
    check('the ARIMA Specification dialog', r, 'ARIMA Specification: sales')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('ARIMA adds the Model Comparison and the model report', ['Model Comparison' in outl, 'Model: ARMA(1, 1)' in outl], [True, True])
    check('the model report parts', [o for o in outl if o in ('Model Summary', 'Parameter Estimates', 'Forecast', 'Residuals', 'Iteration History')],
          ['Model Summary', 'Parameter Estimates', 'Forecast', 'Residuals', 'Iteration History'])
    pe = await page.ev(table_under_js('Parameter Estimates'))
    check('Parameter Estimates columns', pe[0], ['Term', 'Lag', 'Estimate', 'Std Error', 't Ratio', 'Prob>|t|'])
    check('terms', [row[0] for row in pe[1:]], ['Intercept', 'AR1', 'MA1'])
    ms = dict(tuple(x) for x in await page.ev(table_under_js('Model Summary')))
    check("JMP's Model Summary", all(k in ms for k in ('DF', 'Sum of Squared Innovations', 'Variance Estimate', 'Standard Deviation', "Akaike's 'A' Information Criterion",
                                                     "Schwarz's Bayesian Criterion", 'AICc', 'RSquare', 'RSquare Adj', 'MAPE', 'MAE', '−2LogLikelihood', 'Stable', 'Invertible')), True)
    check('DF = n - k', ms.get('DF'), '117')
    check('forecasts continue the months', await page.ev('__ts.rep().body.textContent.includes("12 periods ahead, from 2026-01-01 to 2026-12-01")'), True)
    fp = await page.ev('''(async () => { const rep = __ts.rep(); const p = rep.plots.find(p => p.opts.title === 'ARMA(1, 1) forecast'); await p.draw();
      const fc = p.traces.find(t => t.name === 'ARMA(1, 1) forecast'); const band = p.traces.find(t => t.name === 'ARMA(1, 1) lower');
      return { type: p.box._fullLayout.xaxis.type, last: fc.x[fc.x.length - 1], n: fc.x.length, fill: band.fill }; })()''')
    check('the forecast plot: dates, 12 periods, a band after the data', fp, {'type': 'date', 'last': '2026-12-01', 'n': 13, 'fill': 'tonexty'})
    await shot(page, 'ts-02-arima.png', 'Model: ARMA(1, 1)')

    # ---- seasonal ARIMA, a smoothing model, the group and state space smoothing, all through the menus
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Seasonal ARIMA…']); return await __ts.form({ 'p, Autoregressive Order': 1, 'Q, Seasonal Moving Average Order': 1, 'D, Seasonal Differencing Order': 1 }, 'Estimate');''')
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Smoothing Models', 'Winters Method…']); return await __ts.form({}, 'Estimate');''')
    rows = await page.ev('__ts.cmpRows(__ts.rep())')
    names = [x['name'] for x in rows]
    check('Model Comparison lists the three models', sorted(names), sorted(['ARMA(1, 1)', 'Seasonal ARIMA(1, 0, 0)(0, 1, 1)12', 'Winters Method (Additive)(12)']))
    cmp_ = await page.ev('''(() => { const t = __ts.rep().body.querySelector('table.sm-ts-cmp'); return [...t.querySelectorAll('thead th')].map(th => th.textContent); })()''')
    check('Model Comparison columns', cmp_, ['Report', 'Graph', 'Model', 'DF', 'Variance', 'AIC', 'SBC', 'AICc', 'RSquare', '−2LogLH', 'Weights', 'MAPE', 'MAE'])
    aic = await page.ev('''(() => { const t = __ts.rep().body.querySelector('table.sm-ts-cmp'); return [...t.querySelectorAll('tbody tr')].map(tr => Number(tr.children[5].textContent.replace('−', '-'))); })()''')
    check('sorted by AIC', aic == sorted(aic), True)
    r = await act(page, '''await __ts.menu(__ts.rep(), null, ['ARIMA Model Group…']); return await __ts.form({ 'p, Autoregressive Order (range)': '0-1', 'q, Moving Average Order (range)': '0-1', 'd, Differencing Order (range)': '1' }, 'Estimate');''')
    rows = await page.ev('__ts.cmpRows(__ts.rep())')
    group = [x for x in rows if x['name'] in ('I(1)', 'ARI(1, 1)', 'IMA(1, 1)', 'ARIMA(1, 1, 1)')]
    check('ARIMA Model Group fits every combination', len(group), 4)
    check('... and shows the report of one (the best by AIC)', sum(1 for x in group if x['report']), 1)
    await act(page, '''await __ts.menu(__ts.rep(), null, ['State Space Smoothing Models…']); return await __ts.form({ 'Error: Multiplicative (M)': false, 'Seasonal: Multiplicative (M)': false, 'Trend: Additive damped (Ad)': false }, 'OK');''')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('State Space Smoothing Model Selection', any(o.startswith('State Space Smoothing Model Selection') for o in outl), True)
    sel = await page.ev(table_under_js('State Space Smoothing Model Selection 2'))
    check('four ETS models, best by AICc first', (len(sel) - 1, sel[1][-1]), (4, '★ best'))
    check('the caution about comparing classes', await page.ev('__ts.problems(__ts.rep()).warns.some(w => w.startsWith("Caution: the state space"))'), True)
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Transfer Function…']); return await __ts.form({ 'Noise p, Autoregressive Order': 1 }, 'Estimate');''')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('the transfer function model', 'Model: Transfer Function AR(1) with promotion, temperature' in outl, True)
    pe = await page.ev('''(() => { const h = __ts.head(__ts.rep(), 'Model: Transfer Function'); const t = h.parentElement.querySelector('table.sm-rt'); return [...t.querySelectorAll('tbody tr')].map(tr => tr.children[0].textContent); })()''')
    check('... with a coefficient for each input', pe, ['Intercept', 'promotion', 'temperature', 'AR1'])
    await shot(page, 'ts-03-comparison.png', 'Model Comparison')
    pr = await page.ev('__ts.problems(__ts.rep())')
    check('no errors with nine models', pr['errors'], [])
    check('no deprecation noise in the messages', any('DeprecationWarning' in w for w in pr['warns']), False)

    # ---- the Report and Graph boxes, and a model's red triangle
    r = await act(page, '''const rep = __ts.rep(); const tr = [...rep.body.querySelectorAll('table.sm-ts-cmp tbody tr')].find(tr => tr.children[2].textContent === 'ARMA(1, 1)');
      const b = tr.children[0].querySelector('input'); b.checked = false; b.dispatchEvent(new Event('change')); return true;''')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('unchecking Report hides the model report', 'Model: ARMA(1, 1)' in outl, False)
    await act(page, '''const rep = __ts.rep(); const tr = [...rep.body.querySelectorAll('table.sm-ts-cmp tbody tr')].find(tr => tr.children[2].textContent === 'ARMA(1, 1)');
      const b = tr.children[0].querySelector('input'); b.checked = true; b.dispatchEvent(new Event('change')); return true;''')
    r = await page.ev('''(async () => { const rep = __ts.rep(); const p = rep.plots.find(p => p.opts.title === 'sales model comparison forecasts'); return p.traces.filter(t => t.showlegend).map(t => t.name); })()''')
    check('the Graph boxes put the models on the comparison plot', 'ARMA(1, 1)' in r and 'Seasonal ARIMA(1, 0, 0)(0, 1, 1)12' in r, True)
    await act(page, '''await __ts.menu(__ts.rep(), 'Model: ARMA(1, 1)', ['Show Points']); return true;''')
    r = await page.ev('''(() => { const p = __ts.rep().plots.find(p => p.opts.title === 'ARMA(1, 1) forecast'); return p.traces.some(t => t.mode === 'markers'); })()''')
    check('Show Points off takes the points away', r, False)
    await act(page, '''await __ts.menu(__ts.rep(), 'Model: ARMA(1, 1)', ['Show Prediction Interval']); return true;''')
    r = await page.ev('''(() => { const p = __ts.rep().plots.find(p => p.opts.title === 'ARMA(1, 1) forecast'); return p.traces.some(t => t.fill === 'tonexty'); })()''')
    check('Show Prediction Interval off takes the band away', r, False)
    await act(page, '''await __ts.menu(__ts.rep(), 'Model: ARMA(1, 1)', ['Residual Statistics', 'Variogram']); return true;''')
    r = await page.ev('''(() => { const h = __ts.head(__ts.rep(), 'Model: ARMA(1, 1)'); return [...h.parentElement.querySelectorAll('table.sm-ts-corr caption')].map(c => c.textContent); })()''')
    check('Residual Statistics: the residual correlations and the variogram', r, ['Residual Autocorrelation', 'Variogram', 'Residual Partial Autocorrelation'])
    r = await page.ev('''(async () => { const before = SM.app.tables.length; await __ts.menu(__ts.rep(), 'Model: ARMA(1, 1)', ['Save Columns']); await new Promise(r => setTimeout(r, 200));
      const t = SM.app.tables[SM.app.tables.length - 1]; const time = t.columns[0];
      return { added: SM.app.tables.length - before, name: t.name, cols: t.columns.map(c => c.name), rows: t.nrows, fmt: time.format && time.format.kind, last: time.values[t.nrows - 1], resid: t.columns[4].values[t.nrows - 1] }; })()''')
    check('Save Columns makes a new table', (r['added'], r['name'], r['rows']), (1, 'sales ARMA(1, 1)', 132))
    check('... with the time, actual, predicted, error, residual and limits', r['cols'], ['month', 'Actual sales', 'Predicted sales', 'Std Err Pred sales', 'Residual sales', 'Upper CL (0.95) sales', 'Lower CL (0.95) sales'])
    check('... the forecast dates continue monthly', (r['fmt'], r['last']), ('date', await page.ev('Date.UTC(2026, 11, 1)')))
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports[SM.app.reports.length - 1]))')
    n0 = len(await page.ev('__ts.cmpRows(__ts.rep())'))
    await act(page, '''await __ts.menu(__ts.rep(), 'Model: ARMA(1, 1)', ['Remove Fit']); return true;''')
    rows = await page.ev('__ts.cmpRows(__ts.rep())')
    check('Remove Fit takes the model out of the comparison', (len(rows), any(x['name'] == 'ARMA(1, 1)' for x in rows)), (n0 - 1, False))

    # ---- differencing, decomposition, the spectral density, the lag plot, cross correlation
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Difference…']); return await __ts.form({ 'Seasonal Differencing Order, D': '1' }, 'Estimate');''')
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Decomposition', 'STL Decomposition…']); return await __ts.form({}, 'OK');''')
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Decomposition', 'Remove Linear Trend']); return true;''')
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Spectral Density']); return true;''')
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Show Lag Plot']); return true;''')
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Cross Correlation']); return true;''')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    for o in ('Difference: (1 − B)(1 − B^12)', 'STL Decomposition (period 12)', 'Linear Trend', 'Time Series Detrended sales', 'Spectral Density', 'White Noise Test', 'Lag Plot (lag 1)', 'Cross Correlation'):
        check(f'outline {o}', o in outl, True)
    wn = dict(tuple(x) for x in await page.ev(table_under_js('White Noise Test')))
    check("Fisher's kappa and Bartlett's test", ("Fisher's Kappa" in wn, 'Prob > Kappa' in wn, "Bartlett's Kolmogorov-Smirnov" in wn), (True, True, True))
    lagn = await act(page, '''const i = __ts.rep().body.querySelector('.sm-ts-lagctl input'); i.value = '12'; i.dispatchEvent(new Event('change')); return true;''')
    check('the lag plot takes another lag', 'Lag Plot (lag 12)' in await page.ev('__ts.outlines(__ts.rep())'), True)
    ccf = await page.ev('''(() => { const h = __ts.head(__ts.rep(), 'Cross Correlation'); return [...h.parentElement.querySelectorAll('table.sm-ts-corr caption')].map(c => c.textContent); })()''')
    check('a cross correlation per input', ccf, ['sales with promotion', 'sales with temperature'])
    r = await page.ev('''(async () => { const rep = __ts.rep(); const t = rep.table; const before = t.columns.length; await __ts.menu(rep, 'Difference', ['Save']); await new Promise(r => setTimeout(r, 100));
      const c = t.columns[t.columns.length - 1]; const out = { added: t.columns.length - before, name: c.name, first: c.values[12], v13: Number.isFinite(c.values[13]) }; t.removeColumn(c.id); return out; })()''')
    check('Difference > Save writes the differenced column', (r['added'], r['first'], r['v13']), (1, None, True))
    await shot(page, 'ts-04-spectral.png', 'Spectral Density')
    pr = await page.ev('__ts.problems(__ts.rep())')
    check('still no errors', pr['errors'], [])

    # ---- the options survive Redo and a saved project
    spec = json.loads(await page.ev('JSON.stringify(__ts.rep().toJSON().spec.options)'))
    mkey = [k for k in spec if k.endswith('|models')]
    check('the models are stored in the options', len(spec[mkey[0]]) if mkey else 0, n0 - 1 + 0)
    r = await page.ev('''(async () => {
      const rep = __ts.rep(); const t = rep.table;
      const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] };
      const n = SM.app.reports.length;
      SM.app.loadProject(JSON.parse(JSON.stringify(j)));
      const r2 = SM.app.reports[n];
      await __ts.done(r2);
      return { outlines: __ts.outlines(r2).filter(o => o.startsWith('Model: ') || o === 'Spectral Density' || o.startsWith('Difference')), n: SM.app.reports.length - n, ...__ts.problems(r2) };
    })()''', timeout=600)
    check('a reopened project redraws the models and the added reports', ('Model: Seasonal ARIMA(1, 0, 0)(0, 1, 1)12' in r['outlines'], 'Spectral Density' in r['outlines'], any(o.startswith('Difference') for o in r['outlines'])), (True, True, True))
    check('... without errors', r['errors'], [])
    await page.ev('(() => { const r = SM.app.reports[SM.app.reports.length - 1]; SM.app.closeReport(r); const t = SM.app.tables[SM.app.tables.length - 1]; SM.app.closeTable(t); })()')
    await page.ev('document.querySelectorAll(".sm-dialog .sm-btn.primary").forEach(b => b.click())')

    # ---- excluded rows count as missing values; Redo
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "timeseries")))')
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(r => r.platform.id === 'timeseries'); const t = rep.table;
      t.setState([30, 31], 'excluded', true);
      const stale = !rep.staleEl.hidden;
      const d = __ts.done(rep); rep.run(); await d;
      const k = rep.body.querySelector('.sm-ob.level-0 > .sm-ob-body table.sm-kv');
      const kv = Object.fromEntries([...k.querySelectorAll('tr')].map(tr => [tr.children[0].textContent, tr.children[1].textContent]));
      const p = rep.plots.find(p => p.opts.title === 'sales time series');
      const out = { stale, n: kv['N'], miss: kv['N Missing'], slots: p.traces[0].x.length, gap: p.traces[0].y[30], note: rep.body.textContent.includes('2 excluded rows count as missing values') };
      t.setState([30, 31], 'excluded', false);
      const d2 = __ts.done(rep); rep.run(); await d2;
      return out;
    })()''', timeout=600)
    check('an exclusion makes the report stale', r['stale'], True)
    check('excluded rows are missing values in their place', (r['n'], r['miss'], r['slots'], r['gap']), ('118', '2', 120, None))
    check('... and the report says so', r['note'], True)

    # ---- By: one report per level of a stacked table
    r = await page.ev('''(async () => {
      const src = SM.app.tables.find(t => t.name === 'Monthly sales');
      const m = src.col('month').values, s = src.col('sales').values;
      const t = new SM.Table({ name: 'Two regions', columns: [
        { name: 'region', dataType: 'character', values: [...m.map(() => 'North'), ...m.map(() => 'South')] },
        { name: 'month', dataType: 'numeric', format: { kind: 'date' }, values: [...m, ...m] },
        { name: 'sales', dataType: 'numeric', values: [...s, ...s.map((v, i) => v * 0.8 + 5 * Math.sin(i))] } ] });
      SM.app.addTable(t);
      const P = SM.platforms.get('timeseries');
      const rep = SM.app.openReport(P, { roles: { y: [t.col('sales').id], time: [t.col('month').id], by: [t.col('region').id] }, options: { forecast: 6 } }, t);
      await __ts.done(rep);
      rep.spec.options['ts:sales|models'] = [{ id: 1, kind: 'arima', p: 1, d: 0, q: 0, P: 0, D: 1, Q: 1, s: 12, intercept: true, constrain: true, level: 0.95 }];
      const d = __ts.done(rep); rep.run(); await d;
      const tops = [...rep.body.querySelectorAll('.sm-ob.level-0 > .sm-ob-head h2')].map(h => h.textContent);
      return { tops, models: __ts.outlines(rep).filter(o => o.startsWith('Model: ')), ...__ts.problems(rep), note: rep.noteEl.textContent };
    })()''', timeout=600)
    check('By gives one report per level', r['tops'], ['Time Series sales region=North', 'Time Series sales region=South'])
    check('... each with the model', r['models'], ['Model: Seasonal ARIMA(1, 0, 0)(0, 1, 1)12', 'Model: Seasonal ARIMA(1, 0, 0)(0, 1, 1)12'])
    check('... without errors', r['errors'], [])
    check('... from 240 rows in two groups', r['note'], 'Two regions: 240 of 240 rows, 2 groups')

    # ---- the Python script
    script = await page.ev('SM.app.reports.find(r => r.platform.id === "timeseries").pythonScript()')
    check('the script has the fits', all(s in script for s in ('from statsmodels.tsa.arima.model import ARIMA', 'acorr_ljungbox', 'ExponentialSmoothing', 'ETSModel', 'asfreq(\'MS\')')), True)

    # ---- dark theme and phone width
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "timeseries")))')
    await page.ev('''(async () => { const rep = SM.app.reports.find(r => r.platform.id === 'timeseries'); const d = __ts.done(rep);
      KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark'); await d; })()''', timeout=600)
    await asyncio.sleep(1.0)
    await shot(page, 'ts-05-dark.png', 'Model Comparison')
    await shot(page, 'ts-06-dark-top.png', 'Time Series sales')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await page.ev('''(async () => { const rep = SM.app.reports.find(r => r.platform.id === 'timeseries'); const d = __ts.done(rep); rep.run(); await d; })()''', timeout=600)
    await asyncio.sleep(1.2)
    check('no horizontal page scroll at phone width', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    await shot(page, 'ts-07-phone.png', 'Model Comparison')
    # ==== beyond JMP: Zivot-Andrews, regime switching, filters, the subseries plot, structural, Theta and ARDL models ====
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev('document.documentElement.setAttribute("data-theme", "light")')
    await asyncio.sleep(0.8)
    r = await page.ev('''(() => { const t = SM.io.example('cycles'); SM.app.addTable(t);
      const p = t.col('price').values; return { name: t.name, rows: t.nrows, cols: t.columns.map(c => c.name), lastPrice: p.slice(-9).map(v => Number.isFinite(v)),
        listed: !!SM.io.EXAMPLES.cycles, date: t.col('quarter').format && t.col('quarter').format.kind }; })()''')
    check('the Business cycle example: simulated quarters with a price missing in the last 8', (r['name'], r['rows'], r['cols'], r['lastPrice'], r['listed'], r['date']),
          ('Business cycle', 184, ['quarter', 'growth', 'output', 'unemployment', 'cost', 'price'], [True] + [False] * 8, True, 'date'))

    async def open_ts(roles, options):
        return await page.ev(f'''(async () => {{ const t = SM.app.current; const P = SM.platforms.get('timeseries');
          const ids = {{}}; for (const [k, names] of Object.entries({json.dumps(roles)})) ids[k] = names.map(n => t.col(n).id);
          const rep = SM.app.openReport(P, {{ roles: ids, options: {json.dumps(options)} }}, t); await __ts.done(rep);
          return {{ title: rep.title, outlines: __ts.outlines(rep), ...__ts.problems(rep) }}; }})()''', timeout=600)

    # ---- Zivot-Andrews, in Stationarity Tests by default
    r = await open_ts({'y': ['unemployment'], 'time': ['quarter']}, {'forecast': 8})
    check('Stationarity Tests hold the Zivot-Andrews Test by default', ('Stationarity Tests' in r['outlines'], 'Zivot-Andrews Test' in r['outlines'], r['errors']), (True, True, []))
    za = await page.ev(table_under_js('Zivot-Andrews Test'))
    check('Zivot-Andrews: the three models and the break date', ([row[0] for row in za[1:]], za[0]),
          (['Break in intercept', 'Break in trend', 'Break in intercept and trend'], ['Model', 'Statistic', 'Prob', 'Lags', 'Break', '1%', '5%', '10%']))
    check('... the level shift after 2005 Q1 is found (a break in the intercept)', za[1][4] in ('2004-10-01', '2005-01-01', '2005-04-01'), True)
    check('... and the unit root is rejected', za[1][2].startswith('<') or num(za[1][2]) < 0.05, True)
    zp = await page.ev('''(() => { const p = __ts.rep().plots.find(p => p.opts.title === 'unemployment Zivot-Andrews breaks'); return p ? { shapes: p.userLayout.shapes.length, labels: p.userLayout.annotations.map(a => a.text.trim()), linked: !!p.rows[0] } : null; })()''')
    n_dates = len({row[4] for row in za[1:]})
    check('... a graph with a line at each break date, labelled with its models, its points linked to the rows', (zp['shapes'], len(zp['labels']), zp['linked'], any('intercept' in x for x in zp['labels'])), (n_dates, n_dates, True, True))
    t = await act(page, '''await __ts.menu(__ts.rep(), 'Zivot-Andrews Test', ['Zivot-Andrews Options…']); return await __ts.form({ 'Trimming at each end (0 to 1/3)': 0.25, 'Lags chosen by': 'BIC' }, 'OK');''')
    check('Zivot-Andrews Options: the dialog', t, 'Zivot-Andrews Test: unemployment')
    spec = json.loads(await page.ev('JSON.stringify(__ts.rep().spec.options)'))
    check('... the options are kept in the report (Redo and projects keep them)', (spec.get('ts:unemployment|zaTrim'), spec.get('ts:unemployment|zaAutolag')), (0.25, 'BIC'))
    check('... and the test is redrawn with them', await page.ev('__ts.rep().body.textContent.includes("trim=0.25") || [...__ts.rep().body.querySelectorAll("details.sm-code code")].some(c => c.textContent.includes("trim=0.25"))'), True)
    await shot(page, 'ts-08-zivot.png', 'Zivot-Andrews Test')
    await act(page, '''await __ts.menu(__ts.rep(), 'Stationarity Tests', ['Zivot-Andrews Test']); return true;''')
    check('the Stationarity Tests red triangle turns it off', 'Zivot-Andrews Test' in await page.ev('__ts.outlines(__ts.rep())'), False)
    r = await page.ev('''(async () => { const rng = SM.util.rng('long'); let x = 0; const v = []; for (let i = 0; i < 5001; i++) { x += rng.normal(); v.push(x); }
      const t = new SM.Table({ name: 'Long walk', columns: [{ name: 'x', dataType: 'numeric', values: v }] }); SM.app.addTable(t);
      const rep = SM.app.openReport(SM.platforms.get('timeseries'), { roles: { y: [t.col('x').id] }, options: {} }, t); await __ts.done(rep);
      const out = { za: __ts.outlines(rep).includes('Zivot-Andrews Test'), note: rep.body.textContent.includes('left out for a series of more than 5000 values'), ...__ts.problems(rep) };
      SM.app.closeReport(rep); SM.app.closeTable(t); document.querySelectorAll('.sm-dialog .sm-btn.primary').forEach(b => b.click());
      const cyc = SM.app.tables.find(x => x.name === 'Business cycle'); if (cyc) SM.app.showTab(SM.app.tabOf(cyc));
      return out; })()''', timeout=600)
    check('a series of more than 5000 values leaves the Zivot-Andrews test out by default, and says so', (r['za'], r['note'], r['errors']), (False, True, []))

    # ---- Regime Switching on growth
    r = await open_ts({'y': ['growth'], 'time': ['quarter']}, {'forecast': 8})
    t = await act(page, '''await __ts.menu(__ts.rep(), null, ['Regime Switching…']); return await __ts.form({ 'Autoregressive Order (0: switching regression)': 1, 'Random Starts': 3 }, 'Estimate');''', timeout=900)
    check('Regime Switching: the dialog', t, 'Regime Switching Specification: growth')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('... the model report and its parts', [o for o in outl if o in ('Model: Regime Switching: 2 regimes, AR(1), switching mean', 'Model Comparison', 'Regimes', 'Regime Probabilities', 'Starts', 'One-Step-Ahead Predictions')],
          ['Model Comparison', 'Model: Regime Switching: 2 regimes, AR(1), switching mean', 'One-Step-Ahead Predictions', 'Regimes', 'Regime Probabilities', 'Starts'])
    pr = await page.ev('__ts.problems(__ts.rep())')
    check('... without errors', pr['errors'], [])
    rg = await page.ev(table_under_js('Regimes'))
    tp = await page.ev(table_under_js('Regimes', 1))
    check('Regimes: the probability of staying, the expected duration, how long each is most likely', rg[0], ['Regime', 'P(Stay)', 'Expected Duration', 'Periods Most Likely', 'Mean Probability'])
    check('... the transition matrix: each row sums to 1', all(abs(num(a) + num(b) - 1) < 2e-6 for _, a, b in tp[1:]), True)
    stay = [num(row[1]) for row in rg[1:]]
    dur = [num(row[2]) for row in rg[1:]]
    check('... the expected duration is 1/(1 − P(Stay))', all(abs(d - 1 / (1 - s_)) < 1e-3 * d for s_, d in zip(stay, dur)), True)
    pe = await page.ev(table_under_js('Parameter Estimates'))
    check('Parameter Estimates with a Regime column', (pe[0], [row[0] for row in pe[1:]]), (['Term', 'Regime', 'Estimate', 'Std Error', 'z Ratio', 'Prob>|z|'], ['P(0 → 0)', 'P(1 → 0)', 'Intercept', 'Intercept', 'Variance', 'AR1']))
    means = sorted(num(row[2]) for row in pe[1:] if row[0] == 'Intercept')
    check('... the two means near the simulated −0.6 and 0.8 (the quantile start finds them)', abs(means[0] + 0.6) < 0.5 and abs(means[1] - 0.8) < 0.4, True)
    rp = await page.ev('''(async () => { const rep = __ts.rep(); const p = rep.plots.find(p => /smoothed probabilities$/.test(p.opts.title)); const s = rep.plots.find(p => /regimes$/.test(p.opts.title));
      await p.draw(); await s.draw(); return { traces: p.traces.filter(t => t.rows || p.rows).length, names: p.traces.map(t => t.name), shapes: s.userLayout.shapes.length, rowsLinked: p.rows.filter(Boolean).length }; })()''')
    check('Regime Probabilities: a probability line per regime, linked to the rows', (rp['names'][:2], rp['rowsLinked']), (['Regime 0', 'Regime 1'], 2))
    check('... the series shaded where each regime is the most likely', rp['shapes'] > 2, True)
    r = await page.ev('''(async () => { const rep = __ts.rep(); const t = rep.table; const p = rep.plots.find(p => /smoothed probabilities$/.test(p.opts.title));
      p._click({ points: [{ curveNumber: 0, pointNumber: 50 }], event: {} }); const sel = t.selectedRows();
      t.select([7, 8]); await new Promise(r => setTimeout(r, 150)); const sp = Array.from(p.box.data[0].selectedpoints || []); t.select([]); return { sel, sp }; })()''')
    check('... a click on a probability selects its row; a selection shows in the graph', (r['sel'], r['sp']), ([50], [7, 8]))
    st = await page.ev(table_under_js('Starts'))
    check('Starts: statsmodels\' default, the quantile start and 3 random starts, one best', ([row[0] for row in st[1:]], sum(1 for row in st[1:] if row[3] == '★ best')),
          (["statsmodels' default", 'regimes at the quantiles', 'random 1', 'random 2', 'random 3'], 1))
    r = await page.ev('''(async () => { const rep = __ts.rep(); const t = rep.table; const before = t.columns.length; await __ts.menu(rep, 'Model: Regime Switching', ['Save Regime Probabilities']);
      await new Promise(r => setTimeout(r, 150)); const added = t.columns.slice(before); const out = { names: added.map(c => c.name), p0: added[0].values[10], p1: added[1].values[10], most: added[2].values[10] };
      for (const c of added) t.removeColumn(c.id); return out; })()''')
    check('Save Regime Probabilities: the smoothed probabilities and the most likely regime', (r['names'], abs(r['p0'] + r['p1'] - 1) < 1e-9, r['most'] == (0 if r['p0'] > r['p1'] else 1)),
          (['P(Regime 0) growth', 'P(Regime 1) growth', 'Most Likely Regime growth'], True, True))
    await shot(page, 'ts-09-regimes.png', 'Regime Probabilities')
    await act(page, '''await __ts.menu(__ts.rep(), 'Model: Regime Switching', ['Filtered Probabilities']); return true;''')
    check('Filtered Probabilities adds the dotted filtered lines', await page.ev('''(() => __ts.rep().plots.find(p => /smoothed probabilities$/.test(p.opts.title)).traces.filter(t => /filtered$/.test(t.name)).length)()'''), 2)

    # ---- Filters on output
    r = await open_ts({'y': ['output'], 'time': ['quarter']}, {'forecast': 8})
    t = await act(page, '''await __ts.menu(__ts.rep(), null, ['Filters', 'Hodrick-Prescott Filter…']); await new Promise(r => setTimeout(r, 250));
      const dlg = [...document.querySelectorAll('.sm-dialog')].pop(); const lab = [...dlg.querySelectorAll('.sm-form label')].find(l => l.textContent === 'λ, Smoothing');
      window.__lam = document.getElementById(lab.htmlFor).value; return await __ts.form({}, 'Estimate');''')
    check('Filters > Hodrick-Prescott: quarterly data propose λ = 1600', (t, await page.ev('window.__lam')), ('Hodrick-Prescott Filter: output', '1600'))
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Filters', 'Baxter-King Filter…']); return await __ts.form({}, 'Estimate');''')
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Filters', 'Christiano-Fitzgerald Filter…']); return await __ts.form({}, 'Estimate');''')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('... three filter reports', [o for o in outl if 'Filter' in o], ['Hodrick-Prescott Filter (λ = 1600)', 'Baxter-King Filter (6 to 32 periods, K = 12)', 'Christiano-Fitzgerald Filter (6 to 32 periods)'])
    kv = dict(tuple(x) for x in await page.ev(table_under_js('Baxter-King Filter (6 to 32 periods, K = 12)')))
    check('... Baxter-King loses K = 12 quarters at each end', kv.get('N (cycle)'), '160')
    r = await page.ev('''(async () => { const rep = __ts.rep(); const t = rep.table; const before = t.columns.length; await __ts.menu(rep, 'Hodrick-Prescott Filter', ['Save Columns']);
      await new Promise(r => setTimeout(r, 150)); const added = t.columns.slice(before); const out = { names: added.map(c => c.name), sum: added[0].values[20] + added[1].values[20], y: t.col('output').values[20] };
      for (const c of added) t.removeColumn(c.id); return out; })()''')
    check('... Save Columns writes the trend and the cycle, which add up to the series', (r['names'], abs(r['sum'] - r['y']) < 1e-9), (['output HP trend', 'output HP cycle'], True))
    await shot(page, 'ts-10-filters.png', 'Hodrick-Prescott Filter')

    # ---- ARDL on price and cost, with the future costs
    r = await open_ts({'y': ['price'], 'time': ['quarter'], 'inputs': ['cost']}, {'forecast': 8})
    t = await act(page, '''await __ts.menu(__ts.rep(), null, ['ARDL…']); return await __ts.form({}, 'Estimate');''', timeout=900)
    check('ARDL: the dialog', t, 'ARDL Specification: price')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    mname = [o for o in outl if o.startswith('Model: ARDL(')]
    check('... the model, named by its orders', (len(mname), mname[0].endswith('with cost') if mname else False), (1, True))
    check('... its parts', [o for o in outl if o in ('Lag Order Selection', 'Long-Run Coefficients', 'Bounds Test', 'Error Correction Form')],
          ['Lag Order Selection', 'Long-Run Coefficients', 'Bounds Test', 'Error Correction Form'])
    lr = await page.ev(table_under_js('Long-Run Coefficients'))
    lrd = {row[0]: row for row in lr[1:]}
    check('Long-Run Coefficients: cost near the simulated 0.75', abs(num(lrd['cost'][1]) - 0.75) < 0.1, True)
    bt = await page.ev('''(() => { const h = __ts.head(__ts.rep(), 'Bounds Test'); const b = h.parentElement; const v = b.querySelector('.sm-ts-verdict');
      return { kv: [...b.querySelectorAll('table.sm-kv tr')].map(tr => [...tr.children].map(c => c.textContent)), crit: [...b.querySelectorAll('table.sm-rt tr')].map(tr => [...tr.children].map(c => c.textContent)), verdict: v && v.className, text: v && v.textContent }; })()''')
    kvb = dict(tuple(x) for x in bt['kv'])
    check('Bounds Test: the F statistic, the case and k = 1 input', (kvb.get('Case'), kvb.get('Inputs (k)'), await page.ev('__ts.rep().body.textContent.includes("Case 3: unrestricted intercept, no trend.")')), ('3', '1', True))
    check('... the critical values of PSS (2001) for one input', (bt['crit'][0], [row[0] for row in bt['crit'][1:]]), (['Level', 'I(0) Bound', 'I(1) Bound'], ['10%', '5%', '1%', '0.1%']))
    check('... the 5% bounds are those of k = 1 (about 4.9 and 5.7), not statsmodels\' k + 1', [round(num(x), 1) for x in bt['crit'][2][1:]], [4.9, 5.7])
    check('... and the verdict: a level relationship', (bt['verdict'], bt['text'].startswith('At 5%, F = ')), ('sm-ts-verdict sm-ts-reject', True))
    check('ARDL forecasts continue the quarters with the 8 future costs', await page.ev('__ts.rep().body.textContent.includes("8 periods ahead, from 2024-01-01 to 2025-10-01")'), True)
    check('... and say where the future inputs came from', await page.ev('__ts.rep().body.textContent.includes("cost: the 8 future values come from the rows after the series in the table.")'), True)
    await shot(page, 'ts-11-ardl.png', 'Bounds Test')
    t = await act(page, '''await __ts.menu(__ts.rep(), 'Model: ARDL(', ['Fit New…']);
      return await __ts.form({ 'Or fixed orders p, q1, q2 … (- leaves an input out)': '2, 1', 'Deterministic Terms': 'ct' }, 'Estimate');''', timeout=900)
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('Fit New… with fixed orders and a trend: ARDL(2, 1)', 'Model: ARDL(2, 1) with cost' in outl, True)
    kv2 = await page.ev('''(() => [...__ts.rep().body.querySelectorAll('.sm-ob-head')].filter(h => h.textContent.trim() === 'Bounds Test').map(h => [...h.parentElement.querySelectorAll('table.sm-kv tr')].map(tr => [...tr.children].map(c => c.textContent)).find(x => x[0] === 'Case')[1]))()''')
    check('... its bounds test takes case 4 (the trend restricted)', (kv2, await page.ev('__ts.rep().body.textContent.includes("Case 4: unrestricted intercept, restricted trend.")')), (['3', '4'], True))

    # ---- the sales example: the subseries plot, a structural model with the promotion, the Theta model
    r = await page.ev(f'''(async () => {{ const t = SM.app.tables.find(t => t.name === 'Monthly sales'); const P = SM.platforms.get('timeseries');
      const rep = SM.app.openReport(P, {{ roles: {{ y: [t.col('sales').id], time: [t.col('month').id], inputs: [t.col('promotion').id] }}, options: {{ forecast: 12 }} }}, t); await __ts.done(rep);
      return {{ title: rep.title, ...__ts.problems(rep) }}; }})()''', timeout=600)
    check('a report on the Monthly sales', (r['title'], r['errors']), ('Time Series sales', []))
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Seasonal Subseries Plot']); return true;''')
    sp = await page.ev('''(async () => { const p = __ts.rep().plots.find(p => p.opts.title === 'sales seasonal subseries'); await p.draw();
      return { n: p.traces.filter(t => t.type === 'scatter').length, ticks: p.userLayout.xaxis.ticktext, means: p.userLayout.shapes.length, rows: p.rows[0].slice(0, 3) }; })()''')
    check('Seasonal Subseries Plot: a small series for each month with its mean line', (sp['n'], sp['ticks'], sp['means']), (12, ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 12))
    check('... January is the rows 0, 12, 24 …', sp['rows'], [0, 12, 24])
    r = await page.ev('''(async () => { const rep = __ts.rep(); const t = rep.table; const p = rep.plots.find(p => p.opts.title === 'sales seasonal subseries');
      p._click({ points: [{ curveNumber: 1, pointNumber: 2 }], event: {} }); const sel = t.selectedRows(); t.select([]); return sel; })()''')
    check('... a click selects the row (the third February)', r, [25])
    mt = await page.ev(table_under_js('Season Means'))
    check('... Season Means gives the numbers', (mt[0], len(mt) - 1), (['Season', 'N', 'Mean', 'Std Dev'], 12))
    await shot(page, 'ts-12-subseries.png', 'Seasonal Subseries Plot')
    t = await act(page, '''await __ts.menu(__ts.rep(), null, ['Structural Model…']); return await __ts.form({}, 'Estimate');''', timeout=900)
    check('Structural Model: the dialog', t, 'Structural Model Specification: sales')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('... the model with its seasonal and the promotion input (the dialog\'s defaults)', 'Model: Structural: local linear trend + seasonal(12) + promotion' in outl, True)
    check('... its parts', [o for o in outl if o in ('Model Summary', 'Parameter Estimates', 'Forecast', 'Residuals', 'Components', 'Iteration History')][:6],
          ['Model Summary', 'Parameter Estimates', 'Forecast', 'Residuals', 'Components', 'Iteration History'])
    pe = await page.ev(table_under_js('Parameter Estimates'))
    check('... the variances and the input coefficient', ([row[0] for row in pe[1:]], pe[0]),
          (['Irregular Variance (σ²ε)', 'Level Variance (σ²η)', 'Slope Variance (σ²ζ)', 'Seasonal Variance (σ²ω)', 'promotion'], ['Term', 'Estimate', 'Std Error', 'z Ratio', 'Prob>|z|']))
    cp = await page.ev('''(async () => { const p = __ts.rep().plots.find(p => /components$/.test(p.opts.title)); await p.draw();
      return { panels: p.userLayout.annotations.map(a => a.text), bands: p.traces.filter(t => t.fill === 'tonexty').length, linked: p.rows.filter(Boolean).length }; })()''')
    check('Components: level, trend, seasonal, regression and irregular panels, with bands', (cp['panels'], cp['bands']), (['Level', 'Trend (slope)', 'Seasonal', 'Regression effect', 'Irregular'], 4))
    check('... the data in the level panel, linked to the rows', cp['linked'], 1)
    check('... forecasts continue the months', await page.ev('__ts.rep().body.textContent.includes("12 periods ahead, from 2026-01-01 to 2026-12-01")'), True)
    await shot(page, 'ts-13-structural.png', 'Components')
    r = await page.ev('''(async () => { const rep = __ts.rep(); const t = rep.table; const before = t.columns.length; await __ts.menu(rep, 'Model: Structural', ['Save Components']);
      await new Promise(r => setTimeout(r, 150)); const added = t.columns.slice(before); const names = added.map(c => c.name); for (const c of added) t.removeColumn(c.id); return names; })()''')
    check('Save Components writes the smoothed components', r, ['Level sales', 'Trend (slope) sales', 'Seasonal sales', 'Regression effect sales', 'Irregular sales'])
    t = await act(page, '''await __ts.menu(__ts.rep(), null, ['Theta Model…']); return await __ts.form({}, 'Estimate');''', timeout=900)
    check('Theta Model: the dialog', t, 'Theta Model: sales')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('... the model report', 'Model: Theta Model (θ = 2)' in outl, True)
    rows = await page.ev('__ts.cmpRows(__ts.rep())')
    check('Model Comparison lists the structural and Theta models', sorted(x['name'] for x in rows), ['Structural: local linear trend + seasonal(12) + promotion', 'Theta Model (θ = 2)'])
    band = await page.ev('''(() => { const p = __ts.rep().plots.find(p => p.opts.title === 'Theta Model (θ = 2) forecast'); const u = p.traces.find(t => t.name === 'Theta Model (θ = 2) upper'); return u.y[u.y.length - 1]; })()''')
    await act(page, '''await __ts.menu(__ts.rep(), 'Model: Theta Model', ["statsmodels' Prediction Intervals"]); return true;''')
    band2 = await page.ev('''(() => { const p = __ts.rep().plots.find(p => p.opts.title === 'Theta Model (θ = 2) forecast'); const u = p.traces.find(t => t.name === 'Theta Model (θ = 2) upper'); return u.y[u.y.length - 1]; })()''')
    check("... statsmodels' own prediction intervals are wider than the IMA(1, 1) ones", band2 > band, True)
    check('... and the note says why', await page.ev('__ts.rep().body.textContent.includes("which is not that model\'s variance")'), True)
    pr = await page.ev('__ts.problems(__ts.rep())')
    check('no errors with the new models', pr['errors'], [])

    # ---- By: the new parts in every group
    r = await page.ev('''(async () => {
      const src = SM.app.tables.find(t => t.name === 'Monthly sales');
      const m = src.col('month').values, s = src.col('sales').values;
      const t = new SM.Table({ name: 'Two regions again', columns: [
        { name: 'region', dataType: 'character', values: [...m.map(() => 'North'), ...m.map(() => 'South')] },
        { name: 'month', dataType: 'numeric', format: { kind: 'date' }, values: [...m, ...m] },
        { name: 'sales', dataType: 'numeric', values: [...s, ...s.map((v, i) => v * 0.8 + 5 * Math.sin(i))] } ] });
      SM.app.addTable(t);
      const P = SM.platforms.get('timeseries');
      const rep = SM.app.openReport(P, { roles: { y: [t.col('sales').id], time: [t.col('month').id], by: [t.col('region').id] }, options: { forecast: 6,
        'ts:sales|models': [{ id: 1, kind: 'uc', trend: 'local level', seasonal: 12, level: 0.95 }, { id: 2, kind: 'theta', theta: 2, deseasonalize: true, period: 12, level: 0.95 }],
        'ts:sales|filters': [{ id: 1, kind: 'hp' }], 'ts:sales|subseries': true } }, t);
      await __ts.done(rep);
      const out = { tops: [...rep.body.querySelectorAll('.sm-ob.level-0 > .sm-ob-head h2')].map(h => h.textContent),
        outl: __ts.outlines(rep).filter(o => o.startsWith('Model: ') || o.includes('Filter') || o === 'Seasonal Subseries Plot' || o === 'Zivot-Andrews Test'), ...__ts.problems(rep),
        code: rep.pythonScript().includes('df = df[df["region"] == \\'North\\']') };
      SM.app.closeReport(rep); SM.app.closeTable(t); document.querySelectorAll('.sm-dialog .sm-btn.primary').forEach(b => b.click());
      return out; })()''', timeout=900)
    per = ['Zivot-Andrews Test', 'Seasonal Subseries Plot', 'Hodrick-Prescott Filter (λ = 129600)', 'Model: Structural: local level + seasonal(12)', 'Model: Theta Model (θ = 2)']
    check('By: the new parts in each group', (r['tops'], r['outl']), (['Time Series sales region=North', 'Time Series sales region=South'], per + per))
    check('... without errors, and the code keeps the group', (r['errors'], r['code']), ([], True))

    # ---- a saved project redraws the new models, filters and options
    n_ts_before = await page.ev('SM.app.reports.filter(r => r.platform.id === "timeseries").length')
    r = await page.ev('''(async () => {
      const out = [];
      for (const rep of SM.app.reports.filter(r => r.platform.id === 'timeseries').slice(-4)) {
        const t = rep.table; const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] };
        const n = SM.app.reports.length; SM.app.loadProject(JSON.parse(JSON.stringify(j))); const r2 = SM.app.reports[n]; await __ts.done(r2);
        out.push({ outlines: __ts.outlines(r2).filter(o => o.startsWith('Model: ') || o.includes('Filter') || o === 'Seasonal Subseries Plot'), ...__ts.problems(r2) });
        const t2 = r2.table; SM.app.closeReport(r2); SM.app.closeTable(t2);   // the copies go again
        document.querySelectorAll('.sm-dialog .sm-btn.primary').forEach(b => b.click());
      }
      return out;
    })()''', timeout=900)
    check('reopened projects redraw the regime model, the filters, ARDL and the sales models', [x['outlines'] for x in r], [
        ['Model: Regime Switching: 2 regimes, AR(1), switching mean'],
        ['Hodrick-Prescott Filter (λ = 1600)', 'Baxter-King Filter (6 to 32 periods, K = 12)', 'Christiano-Fitzgerald Filter (6 to 32 periods)'],
        [o for o in r[2]['outlines'] if o.startswith('Model: ARDL(')],
        ['Seasonal Subseries Plot', 'Model: Structural: local linear trend + seasonal(12) + promotion', 'Model: Theta Model (θ = 2)']])
    check('... without errors', [x['errors'] for x in r], [[], [], [], []])
    check('... ARDL with both its fits', len(r[2]['outlines']), 2)
    script = await page.ev('SM.app.reports.filter(r => r.platform.id === "timeseries").map(r => r.pythonScript()).join("\\n")')
    check('the Python script has the new fits', all(s_ in script for s_ in ('UnobservedComponents', 'MarkovAutoregression', 'hpfilter', 'bkfilter', 'cffilter', 'ThetaModel', 'zivot_andrews', 'ardl_select_order', 'bounds_test', 'month_plot')), True)

    # ---- the new reports in the dark theme and at phone width
    check('the reopened copies are closed again', await page.ev('SM.app.reports.filter(r => r.platform.id === "timeseries").length'), n_ts_before)
    await page.ev('SM.app.showTab(SM.app.tabOf(__ts.rep()))')
    await page.ev('''(async () => { const rep = __ts.rep(); const d = __ts.done(rep); KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark'); await d; })()''', timeout=600)
    await asyncio.sleep(1.0)
    await shot(page, 'ts-14-dark-structural.png', 'Components')
    await shot(page, 'ts-15-dark-subseries.png', 'Seasonal Subseries Plot')
    regime_rep = await page.ev('SM.app.reports.findIndex(r => r.title === "Time Series growth")')
    await page.ev(f'SM.app.showTab(SM.app.tabOf(SM.app.reports[{regime_rep}]))')
    await asyncio.sleep(1.0)
    colors = await page.ev(f'''(() => {{ const rep = SM.app.reports[{regime_rep}]; const p = rep.plots.find(p => /smoothed probabilities$/.test(p.opts.title)); return p.traces.slice(0, 2).map(t => t.line.color); }})()''')
    check('the regime colours are stepped for the dark theme', colors, ['#3987e5', '#d95926'])
    if SHOTS:
        await page.ev(f'''(() => {{ const rep = SM.app.reports[{regime_rep}]; const h = __ts.head(rep, 'Regime Probabilities'); rep.body.scrollTop = h.getBoundingClientRect().top - rep.body.getBoundingClientRect().top + rep.body.scrollTop - 8; }})()''')
        await asyncio.sleep(1.0)
        await page.shot(os.path.join(SHOTS, 'ts-16-dark-regimes.png'))
    ardl_rep = await page.ev('SM.app.reports.findIndex(r => r.title === "Time Series price")')
    await page.ev(f'SM.app.showTab(SM.app.tabOf(SM.app.reports[{ardl_rep}]))')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await page.ev(f'''(async () => {{ const rep = SM.app.reports[{ardl_rep}]; const d = __ts.done(rep); rep.run(); await d; }})()''', timeout=600)
    await asyncio.sleep(1.2)
    check('no horizontal page scroll at phone width (ARDL)', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    if SHOTS:
        await page.ev(f'''(() => {{ const rep = SM.app.reports[{ardl_rep}]; const h = __ts.head(rep, 'Bounds Test'); rep.body.scrollTop = h.getBoundingClientRect().top - rep.body.getBoundingClientRect().top + rep.body.scrollTop - 8; }})()''')
        await asyncio.sleep(1.0)
        await page.shot(os.path.join(SHOTS, 'ts-17-phone-ardl.png'))

    # ---- help for every input: the launch dialog's (i), every dialog of the red triangles, the report's controls
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    await page.ev(HELP_JS)
    check('help: back on the Monthly sales table', await page.ev('__hp.showTable("Monthly sales")'), True)
    await check_launch_help(page, 'timeseries', what='timeseries: the launch dialog')
    models = [{'kind': 'arima', 'p': 1, 'd': 0, 'q': 0, 'P': 0, 'D': 0, 'Q': 0, 's': 0, 'intercept': True, 'constrain': True, 'level': 0.95, 'id': 1},
              {'kind': 'ets', 'error': 'add', 'trend': 'N', 'seasonal': 'N', 's': 0, 'level': 0.95, 'group': 1, 'id': 2},
              {'kind': 'ets', 'error': 'add', 'trend': 'A', 'seasonal': 'N', 's': 0, 'level': 0.95, 'group': 1, 'id': 3}]
    await page.ev(f'''(async () => {{ const t = SM.app.tables.find((x) => x.name === 'Monthly sales'); const id = (n) => t.col(n).id;
      const rep = SM.app.openReport(SM.platforms.get('timeseries'), {{ roles: {{ y: [id('sales')], time: [id('month')], inputs: ['promotion', 'temperature'].map(id) }}, options: {{ lagPlot: 1, models: {json.dumps(models)} }} }}, t);
      await new Promise((r) => rep.on('done', r)); SM.app.showTab(SM.app.tabOf(rep)); return rep.title; }})()''', timeout=600)
    rep = 'SM.app.reports[SM.app.reports.length - 1]'
    orders = ['p, Autoregressive Order', 'd, Differencing Order', 'q, Moving Average Order']
    seas = ['P, Seasonal Autoregressive Order', 'D, Seasonal Differencing Order', 'Q, Seasonal Moving Average Order', 'Observations per Period']
    fit = ['Prediction Interval', 'Intercept', 'Constrain fit']
    forms = [
        (None, ['Difference…'], ['Nonseasonal Differencing Order, d', 'Seasonal Differencing Order, D', 'Observations per Period, s']),
        (None, ['Decomposition', 'Remove Cycle…'], ['Units per Cycle', 'Subtract a constant']),
        (None, ['Decomposition', 'Seasonal Decomposition…'], ['Period', 'Decomposition Type']),
        (None, ['Decomposition', 'STL Decomposition…'], ['Period', 'Robust']),
        (None, ['Filters', 'Hodrick-Prescott Filter…'], ['λ, Smoothing']),
        (None, ['Filters', 'Baxter-King Filter…'], ['Shortest period in the band', 'Longest period in the band', 'K, Lead-lag length']),
        (None, ['Filters', 'Christiano-Fitzgerald Filter…'], ['Shortest period in the band', 'Longest period in the band', 'Remove the drift first']),
        (None, ['ARIMA…'], orders + fit),
        (None, ['Seasonal ARIMA…'], orders + seas + fit),
        (None, ['ARIMA Model Group…'], ['p, d, q, P, D, Q (ranges)', 'Observations per Period'] + fit),
        (None, ['Transfer Function…'], ['Noise p, d, q, P, D, Q', 'Observations per Period', 'Input (each column)', 'Input lag (dead time)', 'Numerator order (more lags)'] + fit),
        (None, ['Smoothing Models', 'Simple Exponential Smoothing…'], ['Prediction Interval']),
        (None, ['Smoothing Models', 'Winters Method…'], ['Prediction Interval', 'Observations per Period', 'Seasonality']),
        (None, ['State Space Smoothing Models…'], ['Error: Additive (A)', 'Error: Multiplicative (M)', 'Trend: None (N)', 'Trend: Additive (A)', 'Trend: Additive damped (Ad)', 'Seasonal: None (N)',
                                                   'Seasonal: Additive (A)', 'Seasonal: Multiplicative (M)', 'Period', 'Leave out additive errors with multiplicative seasonality', 'Prediction Interval']),
        (None, ['Structural Model…'], ['Level and Trend', 'Seasonal', 'Seasonal Period', 'Harmonics', 'Stochastic seasonal', 'Cycle', 'Stochastic cycle', 'Damped cycle', 'Cycle period from',
                                       'Cycle period to', 'Autoregressive Order', 'Input (each column)', 'Exact diffuse initialization', 'Prediction Interval']),
        (None, ['Regime Switching…'], ['Number of Regimes', 'Autoregressive Order', 'Mean', 'Switching mean (and trend)', 'Switching variance', 'Switching AR coefficients', 'Random Starts']),
        (None, ['Theta Model…'], ['θ, Theta', 'Deseasonalize', 'Seasonal Period', 'Test for seasonality first', 'Deseasonalizing', 'Estimate by maximum likelihood', 'Prediction Interval']),
        (None, ['ARDL…'], ['Input (each column)', 'Largest lag of the series, p', 'Largest lag of the inputs, q', 'Choose the orders by', 'Search every subset of lags', 'Fixed orders',
                           'Deterministic Terms', 'Bounds Test Case', 'Causal', 'Seasonal dummies', 'Prediction Interval']),
        (None, ['Number of Forecast Periods…'], ['Forecast periods for every model']),
        (None, ['Maximum Iterations…'], ['Maximum iterations']),
        ('Stationarity Tests', ['Zivot-Andrews Options…'], ['Trimming at each end', 'Largest lag', 'Lags chosen by']),
    ]
    for title, path, fields in forms:
        await check_form_help(page, f"await __hp.menu({rep}, {json.dumps(title)}, {json.dumps(path)})", fields, f'timeseries: {" > ".join(path)}')
    await check_controls_help(page, rep, 'Lag Plot (lag 1)', ['Lag p', '− and +', 'A point'], 'timeseries: Lag Plot')
    await check_controls_help(page, rep, 'Model Comparison', ['Report', 'Graph', 'A column heading', 'Right click the table'], 'timeseries: Model Comparison')
    await check_controls_help(page, rep, 'State Space Smoothing Model Selection 1', ['A line of the selection table'], 'timeseries: State Space Smoothing Model Selection')

    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
