#!/usr/bin/env python3
"""smui.html in a real browser: names and values from a table never become
code.

A table from a file is hostile input, and the page writes the table's names
and values into the Python it shows: in string literals, which must be
escaped, and in comments, which a line break would end. This suite makes a
table whose levels, value labels, texts, table name and one column name
carry a line of Python behind a line break (\\n, \\r), a closing quote (" or
'), braces or a trailing backslash. It runs every platform on it: the
roles filled from the table's columns, once with By where the platform has
it and once with a nominal response and the optional roles filled, and a
few Graph Maker and Tabulate layouts. Then Python's own parser reads
every code block of every report and every report's whole script:

  - every block parses (a quote or backslash left unescaped breaks it);
  - no name INJECTED_* is code: the payloads stay inside strings and
    comments (a line break that ended a comment, or a quote that ended a
    string, would make one a statement or an expression).

The column name with a line break also shows the table's rule: a name is
kept on one line (SM.table.cleanName). And the net under the platforms,
SM.report.unbroken, which every code block and the report's script go
through, is checked by itself: a level, value label or text with a line
break written as it is into a comment goes on one line; a value escaped in
a string literal, and code without table text, are left alone; a table of
20,000 texts with line breaks costs milliseconds.

Start a server on the repository root and headless Chrome (the recipe is in
README.md) on SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-hostile.py [platform ...]

With platform ids, only those run. Exit status 0 when every check passes.
"""
import ast
import asyncio
import json
import re
import sys
import time

from cdp import BASE, Checks, open_page, wait_engine

check = Checks()

HELPERS = r'''
window.__hx = {
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  t: null,
  make() {
    const n = 64;
    let s = 20260930;
    const u = () => (s = (s * 16807) % 2147483647) / 2147483647;
    const nrm = () => Math.sqrt(-2 * Math.log(u())) * Math.cos(2 * Math.PI * u());
    // the payloads: a statement behind a line break, an expression behind a closing quote or
    // inside braces (an f-string), and a backslash that would swallow a closing quote
    const G = ['a\nINJECTED_nl = 1\n#', 'b\rINJECTED_cr = 1\r#', 'c"+INJECTED_dq+"', "d'+INJECTED_sq+'"];
    const H = ['e\\', '{INJECTED_fs}'];
    const O = ['lo\nINJECTED_ord = 1\n#', 'mid\x27\x27\x27+INJECTED_tq+\x27\x27\x27', 'hi\x22\x22\x22+INJECTED_tq2+\x22\x22\x22'];   // triple quotes
    const B = ['yes\nINJECTED_resp = 1\n#', "no'+INJECTED_resp2+'"];
    const TX = ['good fast product\nINJECTED_txt = 1\n# fine', 'bad slow "service"+INJECTED_txt2+"', 'fine good price and service',
      "slow 'delivery'+INJECTED_txt3+'", 'fast good service {INJECTED_txt4}', 'bad price\r\nINJECTED_txt5 = 1\r\n#'];
    const c = { y: [], x: [], x2: [], x3: [], t: [], cnt: [], cens: [], g: [], h: [], o: [], yb: [], txt: [], w: [] };
    for (let i = 0; i < n; i++) {
      const gi = i % 4, hi = Math.floor(i / 4) % 2, oi = Math.floor(i / 8) % 3;
      const x = 1 + 4 * u();
      const y = 8 + gi + 0.8 * x + 0.5 * hi + nrm();
      c.y.push(+y.toFixed(3)); c.x.push(+x.toFixed(3)); c.x2.push([5, 17, 33].includes(i) ? null : +(2 * u() + 0.3 * y).toFixed(3)); c.x3.push(+nrm().toFixed(3));
      c.t.push(i + 1); c.cnt.push(Math.floor(4 * u() * (1 + hi))); c.cens.push(u() < 0.25 ? 1 : 0);
      c.g.push(G[gi]); c.h.push(H[hi]); c.o.push(O[oi]); c.yb.push(u() < 1 / (1 + Math.exp(-(y - 11))) ? B[0] : B[1]);
      c.txt.push(TX[i % TX.length]); c.w.push(+nrm().toFixed(3));
    }
    const t = new SM.Table({ name: 'hostile\nINJECTED_tname = 1\n#', source: 'simulated', columns: [
      { name: 'y', values: c.y }, { name: 'x', values: c.x }, { name: 'x2', values: c.x2 }, { name: 'x3', values: c.x3 }, { name: 't', values: c.t },
      { name: 'cnt', values: c.cnt }, { name: 'cens', values: c.cens, modelingType: 'nominal' },
      { name: 'g', dataType: 'character', values: c.g }, { name: 'h', dataType: 'character', values: c.h },
      { name: 'o', dataType: 'character', values: c.o, modelingType: 'ordinal', valueOrder: O },
      { name: 'yb', dataType: 'character', values: c.yb }, { name: 'txt', dataType: 'character', values: c.txt },
      { name: 'w\nINJECTED_name = 1\n#', values: c.w }] });
    SM.app.addTable(t);
    if (t.setValueLabels) {
      t.setValueLabels('cens', { 0: 'alive\nINJECTED_lab = 1\n#', 1: "dead'+INJECTED_lab2+'" });
      t.setValueLabels('h', { 'e\\': 'E\nINJECTED_lab3 = 1\n#' });
    }
    this.t = t;
    return { name: t.name, cols: t.columns.map((k) => k.name) };
  },
  // A role's columns: the first that the role takes, from a list of preferences.
  pick(role, prefs, k) {
    const out = [];
    for (const name of prefs) {
      const c = this.t.col(name) || this.t.columns.find((x) => x.name.startsWith(name));
      if (!c || out.includes(c.id)) continue;
      if (role.numeric && !c.isNumeric) continue;
      if (role.types && role.types.length && !role.types.includes(c.modelingType)) continue;
      out.push(c.id);
      if (out.length >= k) break;
    }
    return out;
  },
  PREFS: {
    y: ['y', 'x', 'x2', 'x3', 'w', 'cnt'], x: ['g', 'x', 'h', 'x2', 'o'], by: ['g'], group: ['h', 'g'], color: ['g'], label: ['g'], id: ['g', 'h'], subgroup: ['h'],
    phase: ['h'], part: ['h'], block: ['h'], censor: ['cens'], treatment: ['yb', 'h'], text: ['txt'], item: ['g', 'o'], time: ['t'], smooth: ['x', 'x2'],
    linear: ['g'], mediator: ['x'], covariates: ['x', 'g'], effect: ['y'], se: ['x'], pred: ['x', 'x2'], zx: ['h'], inputs: ['x'], exog: ['x'], outcome: ['x3'],
    standard: [], size: ['x'], response: ['yb'], subject: [], repeated: [],
  },
  SKIP_OPTIONAL: new Set(['weight', 'freq', 'validation', 'offset', 'exposure', 'ntrials', 'endog', 'instruments', 'yl', 'standard', 'subject', 'repeated',
    'n1', 'mean1', 'sd1', 'n2', 'mean2', 'sd2', 'events1', 'total1', 'events2', 'total2']),
  // The roles for a platform: 'a' fills what is required and By; 'b' a nominal response where
  // one is taken, and the optional roles that take a column of the table.
  roles(p, variant) {
    let L = p.launch; if (typeof L === 'function') L = L(this.t);
    if (!L || !L.roles) return null;
    const ids = {};
    for (const r of L.roles) {
      const k = r.key, need = r.min || 0;
      let prefs = this.PREFS[k] || ['g', 'y'];
      if (variant === 'b' && k === 'y') prefs = ['yb', 'g', 'y', 'x'];
      if (variant === 'b' && k === 'x') prefs = ['x', 'h', 'x2'];
      // By: a column no other role has (By on the X itself leaves each group one level)
      if (k === 'by') { if (variant === 'a') { const used = new Set(Object.values(ids).flat()); const got = this.pick(r, ['g', 'h', 'o'].filter((n) => !used.has((this.t.col(n) || {}).id)), 1); if (got.length) ids.by = got; } continue; }
      if (need) { ids[k] = this.pick(r, prefs, Math.max(need, k === 'y' && variant === 'b' ? 1 : need)); continue; }
      if (variant === 'b' && !this.SKIP_OPTIONAL.has(k)) { const got = this.pick(r, prefs, 1); if (got.length) ids[k] = got; }
    }
    return ids;
  },
  special: {
    meta: { a: { effect: ['y'], se: ['x'], label: ['g'], by: ['h'] }, b: { effect: ['y'], se: ['x'], label: ['g'], group: ['o'] } },
    matchedpairs: { a: { y: ['y', 'x'], by: ['g'] }, b: { y: ['y', 'x'], x: ['g'] } },
    uplift: { a: { y: ['yb'], treatment: ['h'], x: ['x', 'g'], by: ['o'] }, b: { y: ['y'], treatment: ['cens'], x: ['x', 'o'] } },
    treatment: { a: { y: ['y'], treatment: ['yb'], covariates: ['x'], by: ['g'] }, b: { y: ['y'], treatment: ['h'], covariates: ['x', 'g'] } },
    mediation: { a: { y: ['y'], treatment: ['yb'], mediator: ['x'], by: ['g'] }, b: { y: ['yb'], treatment: ['h'], mediator: ['x'], covariates: ['g'] } },
    compare: { a: { y: ['y'], pred: ['x', 'x2'], by: ['g'] }, b: { y: ['y'], pred: ['x', 'x2'], group: ['h'] } },
    counts: { a: { y: ['cnt'], x: ['g', 'x'], by: ['h'] }, b: { y: ['cnt'], x: ['o', 'x'], zx: ['h'] } },
    variability: { a: { y: ['y'], x: ['g'], by: ['h'] }, b: { y: ['yb'], x: ['g'], part: ['h'] } },
    association: { a: { item: ['g'], id: ['h'], by: ['o'] }, b: { item: ['o'], id: ['g'] } },
    text: { a: { text: ['txt'], by: ['g'] }, b: { text: ['txt'], id: ['g'] } },
    bubble: { a: { y: ['y'], x: ['x'], id: ['g'], by: ['h'] }, b: { y: ['y'], x: ['x'], id: ['g'], color: ['h'], time: ['t'] } },
    treemap: { a: { x: ['g'], size: ['y'], by: ['h'] }, b: { x: ['g', 'h'], color: ['o'] } },
    chart: { a: { x: ['g'], y: ['y'], by: ['h'] }, b: { x: ['g', 'h'], y: ['y', 'x'] } },
    functional: { a: { y: ['y'], id: ['g'], x: ['t'], by: ['h'] }, b: { y: ['y'], id: ['g'], x: ['t'] } },
    evaldesign: { a: { x: ['x', 'x2'], y: ['y'] }, b: { x: ['g', 'x'], y: ['y'] } },
    missing: { a: { y: ['x2', 'g'], by: ['h'] }, b: { y: ['x2', 'o', 'txt'] } },
    mi: { a: { y: ['x2', 'y', 'x'], by: ['h'] }, b: { y: ['x2', 'y', 'g'], response: ['yb'] } },
    survival: { a: { y: ['y'], censor: ['cens'], by: ['g'] }, b: { y: ['y'], censor: ['cens'], group: ['g'] } },
    lifedist: { a: { y: ['y'], censor: ['cens'], by: ['g'] }, b: { y: ['y'], censor: ['cens'] } },
    parametric: { a: { y: ['y'], censor: ['cens'], by: ['g'] }, b: { y: ['y'], censor: ['cens'], x: ['g', 'x'] } },
    phreg: { a: { y: ['y'], censor: ['cens'], x: ['x'], by: ['g'] }, b: { y: ['y'], censor: ['cens'], x: ['g', 'x'] } },
    tsforecast: { a: { y: ['y'], time: ['t'], by: ['h'] }, b: { y: ['y'], time: ['t'], group: ['h'] } },
    timeseries: { a: { y: ['y'], time: ['t'], by: ['h'] }, b: { y: ['y'], time: ['t'], inputs: ['x'] } },
    multits: { a: { y: ['y', 'x'], time: ['t'], by: ['h'] }, b: { y: ['y', 'x'], time: ['t'], exog: ['x3'] } },
    controlchart: { a: { y: ['y'], by: ['h'] }, b: { y: ['y'], subgroup: ['g'], phase: ['h'] } },
    capability: { a: { y: ['y'], by: ['g'] }, b: { y: ['y'], subgroup: ['h'] } },
    pareto: { a: { y: ['g'], by: ['h'] }, b: { y: ['g'], x: ['h'] } },
    gam: { a: { y: ['y'], smooth: ['x'], by: ['h'] }, b: { y: ['yb'], smooth: ['x'], linear: ['g'] } },
    mca: { a: { y: ['g', 'h'], by: ['o'] }, b: { y: ['g', 'h', 'o'] } },
  },
  // options a platform needs before it fits anything: Neural's model (as Go adds it), Explore Outliers' methods
  OPTIONS: {
    neural: { models: [{ id: 'm1', method: 'holdback', portion: 0.3333, folds: 5, t1: 3, l1: 0, g1: 0, t2: 0, l2: 0, g2: 0, boost: 0, rate: 0.1, transform: false, robust: false, penalty: 'squared', tours: 1, max_iter: 200 }],
      modelSeq: 1, seed: '7', 'm1|estimates': true, 'm1|diagram': true },
    outliers: { qro: true, rfo: true, mro: true, knn: true },
  },
  specOf(p, variant) {
    const sp = this.special[p.id];
    if (sp) {
      const ids = {};
      for (const [k, names] of Object.entries(sp[variant])) ids[k] = names.map((nm) => (this.t.col(nm) || {}).id).filter(Boolean);
      return ids;
    }
    return this.roles(p, variant);
  },
  // Every code block of a report and its whole script.
  code(rep) {
    const blocks = [...rep.body.querySelectorAll('details.sm-code')].filter((d) => !d.closest('.sm-ob-error'))
      .map((d) => (d._code ? d._code.get() : (d.querySelector('pre code') || d.querySelector('pre') || {}).textContent || ''));
    return { blocks, script: rep.pythonScript ? rep.pythonScript() : '' };
  },
  async finish(rep, ms) {
    const done = new Promise((res) => rep.on('done', () => res('done')));
    const r = await Promise.race([done, this.sleep(ms).then(() => 'timeout')]);
    await this.sleep(150);
    return r;
  },
  errors(rep) { return [...rep.body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent.slice(0, 300)); },
  async run(id, variant, ms) {
    const p = SM.platforms.get(id);
    if (!p) return { id, variant, skipped: 'no platform' };
    const roles = this.specOf(p, variant);
    if (!roles) return { id, variant, skipped: 'no roles' };
    SM.app.showTab(SM.app.tabOf(this.t));
    let rep;
    try { rep = SM.app.openReport(p, { roles, options: JSON.parse(JSON.stringify(this.OPTIONS[id] || {})) }, this.t); } catch (e) { return { id, variant, thrown: String(e && e.message || e).slice(0, 300) }; }
    const state = await this.finish(rep, ms);
    const out = { id, variant, state, roles: Object.fromEntries(Object.entries(roles).map(([k, v]) => [k, v.map((i) => this.t.col(i).name)])), errors: this.errors(rep), ...this.code(rep) };
    try { SM.app.closeReport(rep); } catch (e) { /* closed already */ }
    return out;
  },
  async graph(zones, ms) {
    const t = this.t;
    SM.app.showTab(SM.app.tabOf(t));
    const rep = SM.app.openReport(SM.platforms.get('graphmaker'), { roles: {}, options: {} }, t);
    await this.finish(rep, ms);
    const gm = SM.platforms.get('graphmaker').builder(rep);
    // the builder draws in place (no new run of the report): its update and idle are the wait
    await gm.update((S) => { for (const k of Object.keys(S.zones)) S.zones[k] = []; for (const [k, names] of Object.entries(zones)) S.zones[k] = names.map((nm) => ({ id: t.col(nm).id, name: t.col(nm).name })); S.auto = true; });
    if (gm.idle) await Promise.race([gm.idle(), this.sleep(ms)]);
    await this.sleep(300);
    const r = SM.app.reports.find((x) => x.platform.id === 'graphmaker') || rep;
    const out = { id: 'graphmaker', variant: JSON.stringify(zones), errors: this.errors(r), ...this.code(r) };
    try { SM.app.closeReport(r); } catch (e) { /* closed already */ }
    return out;
  },
  async tabulate(ms) {
    const t = this.t, c = (nm) => ({ id: t.col(nm).id, name: t.col(nm).name });
    SM.app.showTab(SM.app.tabOf(t));
    const rep = SM.app.openReport(SM.platforms.get('tabulate'), { roles: {}, options: { tab: { rows: [[c('g')]], cols: [[c('h')]], analysis: [c('y')], stats: ['N', 'Mean'], quantiles: [25, 75] } } }, t);
    const state = await this.finish(rep, ms);
    const out = { id: 'tabulate', variant: 'g by h', state, errors: this.errors(rep), ...this.code(rep) };
    try { SM.app.closeReport(rep); } catch (e) { /* closed already */ }
    return out;
  },
};
'''

GRAPHS = [
    {'x': ['x'], 'y': ['y'], 'overlay': ['g']},
    {'x': ['g'], 'y': ['y'], 'groupX': ['h'], 'wrap': ['o']},
    {'x': ['x'], 'y': ['y'], 'color': ['yb'], 'groupY': ['cens']},
]

FLAGS = ast.PyCF_ONLY_AST | ast.PyCF_ALLOW_TOP_LEVEL_AWAIT


def problems(code):
    """None when the code parses and no INJECTED_* name is code in it; else
    what is wrong and the line."""
    lines = re.split(r'\r\n|\r|\n', code)     # Python's line breaks, as the parser counts lines
    try:
        tree = compile(code, '<block>', 'exec', flags=FLAGS)
    except SyntaxError as e:
        at = lines[e.lineno - 1] if e.lineno and 0 < e.lineno <= len(lines) else ''
        return f'does not parse: {e.msg} (line {e.lineno}: {at.strip()[:160]!r})'
    bad = sorted({(n.id, n.lineno) for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id.startswith('INJECTED_')}, key=lambda x: x[1])
    if bad:
        # the line before shows where the text came in: the comment (or string) it broke out of
        return 'code from the table: ' + '; '.join(f'{name} on line {ln}, after {lines[ln - 2].strip()[:150]!r}' for name, ln in bad[:2])
    return None


async def main():
    only = set(sys.argv[1:])
    page = await open_page(f'{BASE}/smui.html')
    st = await wait_engine(page)
    check('the engine starts', st, 'ready')
    await page.ev(HELPERS)
    made = await page.ev('__hx.make()')
    check('the table keeps its name on one line', ('\n' in made['name'], '\r' in made['name']), (False, False))
    check('... and every column name', [n for n in made['cols'] if any(ch in n for ch in '\n\r  \x85')], [])

    ids = await page.ev('SM.platforms.all().map((p) => p.id)')
    skip = {'bootstrap', 'pyscript', 'colviewer', 'power', 'calculators', 'graphmaker', 'tabulate'}
    runs = [(i, v) for i in ids if i not in skip for v in ('a', 'b') if not only or i in only]
    results = []
    t0 = time.time()
    async def ev(expr, pid, variant, timeout):
        try:
            r = await page.ev(expr, timeout=timeout)
        except asyncio.TimeoutError:
            r = {'id': pid, 'variant': variant, 'state': 'timeout'}
        if not isinstance(r, dict):
            r = {'id': pid, 'variant': variant, 'thrown': str(r)[:300]}
        print(f'  ran {pid}/{variant}: {r.get("state") or r.get("skipped") or r.get("thrown") or "done"}, {len(r.get("blocks") or [])} code blocks, {len(r.get("errors") or [])} errors ({time.time() - t0:.0f} s)', flush=True)
        return r

    for pid, variant in runs:
        results.append(await ev(f'__hx.run({json.dumps(pid)}, {json.dumps(variant)}, 240000)', pid, variant, 300))
    if not only or 'graphmaker' in only:
        for z in GRAPHS:
            results.append(await ev(f'__hx.graph({json.dumps(z)}, 60000)', 'graphmaker', json.dumps(z), 150))
    if not only or 'tabulate' in only:
        results.append(await ev('__hx.tabulate(60000)', 'tabulate', 'g by h', 150))

    found, blocks, reports, thrown, timeouts = [], 0, 0, [], []
    for r in results:
        if not isinstance(r, dict) or r.get('skipped'):
            continue
        if r.get('thrown'):
            thrown.append(f"{r['id']}/{r['variant']}: {r['thrown']}")
            continue
        if r.get('state') == 'timeout':
            timeouts.append(f"{r['id']}/{r['variant']}")
        reports += 1
        for k, code in enumerate((r.get('blocks') or []) + [r.get('script') or '']):
            if not code.strip():
                continue
            blocks += 1
            what = problems(code)
            if what:
                where = 'the script' if k == len(r.get('blocks') or []) else f'block {k + 1}'
                found.append(f"{r['id']}/{r['variant']} {where}: {what}")
    print(f'\n{reports} reports, {blocks} code blocks read ({time.time() - t0:.0f} s)')
    for f in found:
        print('   ', f)
    check('every code block parses, and nothing from the table is code', found, [])

    # The net under the platforms (SM.report.unbroken, which every code block and the
    # script go through): a value of the table written as it is into a comment
    net = await page.ev(r'''(() => {
      const t = __hx.t, u = (s) => SM.report.unbroken(s, t);
      const lev = (name) => t.col(name).values.find((v) => /[\r\n]/.test(v));
      return {
        level: u('x = 1   # the rows where g is ' + lev('g') + ', as written'),
        cr: u('# ' + t.col('g').values[1] + ' in a comment'),
        label: u('# the control (' + t.col('h').valueLabels['e\\'] + ')\ny = 2'),
        text: u('print(1)   # ' + lev('txt')),
        escaped: u('df = df[df["g"] == ' + JSON.stringify(lev('g')) + ']'),
        plain: u('a = 1\nb = 2\n'),
      };
    })()''')
    for k in ('level', 'cr', 'label', 'text'):
        check(f'the net: a {k} with a line break written as it is stays in its comment', problems(net[k]), None)
    check('... a value in a string literal (escaped) is left as it is', net['escaped'], 'df = df[df["g"] == "a\\nINJECTED_nl = 1\\n#"]')
    check('... and code without table text too', net['plain'], 'a = 1\nb = 2\n')
    speed = await page.ev(r'''(() => {
      const n = 20000, docs = [];
      for (let i = 0; i < n; i++) docs.push('review ' + i + ' of the product\nsecond line ' + (i % 97) + '\r\nthird');
      const t = new SM.Table({ name: 'long texts', columns: [{ name: 'doc', dataType: 'character', values: docs }] });
      const code = Array.from({ length: 1500 }, (_, i) => `x${i} = ${i}   # a line of code`).join('\n') + '\n# ' + docs[4321] + '\n';
      const t0 = performance.now(); const first = SM.report.unbroken(code, t); const t1 = performance.now(); const again = SM.report.unbroken(code, t); const t2 = performance.now();
      return { index: t1 - t0, lookup: t2 - t1, folded: !first.includes(docs[4321]) && first.includes('review 4321 of the product second line 53 third') };
    })()''')
    check('... finds a long text among 20,000 and puts it on one line', speed['folded'], True)
    check(f'... quickly: {speed["index"]:.0f} ms with the index made, {speed["lookup"]:.1f} ms after', speed['index'] < 1500 and speed['lookup'] < 60, True)
    check('no platform throws on the table', thrown, [])
    check('no report hangs', timeouts, [])
    check('the platforms ran and showed code', reports > 50 and blocks > 200 if not only else reports > 0, True)
    check('no script errors', page.errors, [])
    await page.close()
    return check.done()


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
