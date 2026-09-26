# smui.html: tests, and how a platform is written

The page is a statistics workbench in the working style of JMP, with
statsmodels as its engine. JavaScript draws the table, the dialogs, the
reports and the graphs; the statistics are Python (numpy, scipy, pandas,
patsy, statsmodels) running in Pyodide in a module worker.

## Running the tests

Backend tests run the page's Python package (`resources/py/smui`) outside
the browser, through the same `registry.dispatch` and JSON round trip the
page uses. They need a Python with numpy, scipy, pandas, patsy and
statsmodels 0.14 (Pyodide 314.0.7 has statsmodels 0.14.6):

    python3 resources/tests/smui/test_distribution.py   # and test_<module>.py for each module
    node resources/tests/smui/test-formula.js           # the formula language, no browser

| Suite | Checks | Against |
|---|---|---|
| `test_distribution.py` | 55 | scipy/statsmodels directly, JMP's quantile definition |
| `test_models.py` | 36 | NIST Longley, anova_lm type III, JMP's ANCOVA design built by hand |
| `test_io.py` | 9 | a Stata file written by pandas, statsmodels.datasets |
| `test_fit_y_by_x.py` | 263 | NIST NoInt1/2, Wampler1/2, Koenker's Engel, China smoking CMH |
| `test_fit_model.py` | 264 | NIST Longley, Wampler; Greene's Spector logit; random-effects formulas |
| `test_multivariate.py` | 176 | statsmodels/scipy, brute force, SAS's iris CCC |
| `test_timeseries.py` | 189 | MacKinnon critical values, Hyndman et al. variances, sunspots AR fits |
| `test_survival.py` | 145 | Kaplan-Meier and Greenwood by hand, survdiff, PHReg, scipy CensoredData |
| `test_nonlinear.py` | 242 | NIST Misra1a, Thurber, MGH09, DanWood, Rat42, Eckerle4, MGH17 |
| `test_quality.py` | 153 | Montgomery's control-chart constants, formulas |
| `test_doe.py` | 159 | design properties, statsmodels power, textbook values |
| `test_graph.py` | 132 | statsmodels/scipy smoothers, fits, densities, interpolation |
| `test_tables.py` | 129 | pandas group-by, merge, melt/pivot, JMP quantiles |
| `test-formula.js` | 326 | the parser, missing values, every function, no escape to JS |

Every suite that shows Python code also runs that code on a CSV export of
its table and checks that it gives the report's numbers.

Browser tests drive headless Chrome over the DevTools protocol (`cdp.py`,
needs the `websockets` package). Start a server on the repository root and
Chrome, as `../rb/README.md` shows, on the ports in `SMUI_HTTP_PORT` and
`SMUI_CDP_PORT` (defaults 8791 and 9291):

    python3 -m http.server 8791 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      --headless=new --remote-debugging-port=9291 --no-first-run \
      --user-data-dir=/tmp/smui-chrome --disable-gpu about:blank
    python3 resources/tests/smui/test-ui-core.py        # then test-ui-<area>.py for each platform area

`SMUI_SHOTS=<folder>` saves screenshots. The first run downloads Pyodide
(about 40 MB) from jsDelivr; the tests turn the cache off for the page, so
every run fetches the page's own files fresh.

## The files

| File | What it is |
|---|---|
| `smui.html` | the page: site header and footer, the scripts in order |
| `resources/js/smui-util.js` | events, JMP number formatting (`fmt`, `fmtP`), `el()`, `qnorm`, `ranks` |
| `resources/js/smui-table.js` | `SM.Table`: columns, modeling types, value order, row states |
| `resources/js/smui-io.js` | CSV, Excel, JSON; the simulated examples |
| `resources/js/smui-engine.js`, `smui-worker.mjs` | the Pyodide worker and `SM.engine.call()` |
| `resources/js/smui-ui.js` | menus, dialogs, `SM.ui.form()`, toasts |
| `resources/js/smui-grid.js` | the data grid |
| `resources/js/smui-report.js` | reports: outline boxes, report tables, linked Plotly graphs, the `ctx` a platform gets |
| `resources/js/smui-launch.js` | launch dialogs |
| `resources/js/smui-panels.js` | the Table, Columns and Rows panels |
| `resources/js/smui-app.js` | the menu bar, tabs, the platform and command registries |
| `resources/js/smui-help.js` | the Help tab and the (i) topics of the frame |
| `resources/js/smui-p-*.js`, `resources/css/smui-*.css` | the platforms, one file and one stylesheet per menu area |
| `resources/py/smui/` | the backend: `registry` (dispatch), `util` (JSON, report tables), `data` (tables as DataFrames), `models` (linear models as JMP reports them), one module per platform area; `manifest.json` lists what the worker loads |

## Writing a platform

`resources/js/smui-p-distribution.js` with `resources/py/smui/distribution.py`
is the reference; copy its patterns.

### The Python side

A module registers its entry points; the page calls them by name.

```python
from . import data
from .registry import api
from .util import code_head, col, table as rtable   # the argument `table` would hide it

@api('oneway.anova')
def anova(table, y, x, rows=None, alpha=0.05, table_name='data'):
    df = data.frame(table, [y, x], rows)     # index = the page's row numbers
    ...
    return {'anova': rtable([col('source', 'Source', 'text'), col('p', 'Prob > F', 'p')], rows_out),
            'code': '\n'.join([code_head(table_name), 'print(...)'])}
```

- `table`, `rows` and `table_name` come with every call from a report;
  columns are passed by **name**. `rows` is `None` when the report uses
  every row of the table (a long list is slow to send); `data.frame` and
  friends take `None` as all rows. Arguments a function does not take are
  dropped by dispatch (with a line in the browser console), so a helper
  that needs no table need not declare `table` or `rows`.
- Python warnings reach the report under Messages from statsmodels;
  DeprecationWarning and FutureWarning go to the console only.
- `data.frame(table, names, rows, dropna=True, as_category=True)`: ordinal
  and nominal columns arrive as pandas Categoricals in the page's level
  order (ordinal ordered); continuous as float. `data.weights()` applies
  Weight and Freq.
- Return plain dicts; `util.clean` turns numpy into JSON, NaN into null.
  Report tables use `util.table(columns, rows)` with `util.col(key, label,
  fmt)`, fmt one of `num`, `int`, `p`, `pct`, `text`.
- Give every result its `code`: runnable Python that computes it from a
  CSV export of the table (`code_head(table_name)` reads it as `df`).
- Python warnings (convergence, singular fits) are collected by dispatch
  and shown under the report; do not silence them.
- A result for rows (residuals, scores) carries `rows`, the page's row
  numbers (`df.index`), so the page can link and save them.
- `models.build()` / `models.fit_ols()` and the tables in `models.py` give
  JMP's term names (`sex[F]`, `(x-12.3)*(x-12.3)`), effect coding and the
  standard report tables; use them for anything that is a linear model.
- Test natively: `resources/tests/smui/test_<module>.py` with `backend.py`,
  checking against statsmodels or scipy called directly, or against
  published reference values (NIST StRD datasets, textbook examples).

### The JavaScript side

```js
SM.platforms.register({
  id: 'oneway', label: 'Fit Y by X', menu: 'Analyze', order: 20,
  info: 'p:fitybyx', topics: { 'p:fitybyx': { title, lead, sections } },
  about: 'one paragraph for the Help tab', uses: ['statsmodels.stats.multicomp.pairwise_tukeyhsd'],
  launch: { lead, roles: [{ key: 'y', label: 'Y, Response', min: 1, hint: 'required' }, ...], options: [...] },
  title: (spec, table) => 'Oneway Analysis',
  triangle: (ctx) => [ ...red-triangle items of the top outline ],
  async render(ctx) { ... },
});
SM.commands.register({ menu: 'Tables', label: 'Sort…', order: 30, action(app) { ... } });
```

A launch dialog's own part (`launch.extra(api, spec)` returning `{ el,
read(), recall(saved) }`) gets `api.selectedColumns()`, `api.state` (the
roles), `api.onRolesChange(fn)`, `api.showRole(key, on)` and
`api.message(text, 'info')`. What `read()` returns beside `roles` and
`options` is kept in the spec; column ids anywhere in it are remapped when
a project is opened.

`render(ctx)` is called once per By group (the framework splits the rows);
it builds outlines into the report:

- `ctx.rows` the included rows of the group; `ctx.roles('y')` Column
  objects; `ctx.name('x')` a column's name for Python; `ctx.table`.
- `ctx.call(fn, payload)` calls the engine with `table` and `rows` filled
  in; results are cached per report, so a redraw is cheap.
- `ctx.outline(title, { parent, menu: () => items, key, closed, info })`;
  `outline.add(...nodes)`. A red triangle is a `menu` function returning
  items `{ label, action, checked, submenu, separator }`;
  `ctx.check(label, key, scope, default)` makes a toggling item.
- `ctx.opt(key, default, scope)` / `ctx.set(key, value, scope)` are the
  report's options (scope: a column id for per-column options); `set()`
  redraws the report. Options are saved with projects and kept by Redo.
- `ctx.rt(table)` a report table (p-values as `<.0001*`, sortable, right
  click to copy or make a data table; with By, Make Combined Data Table
  joins the same table of every group). A column with `hidden: true` is an
  optional one the reader can show from the right-click Columns menu (as
  JMP's Std Beta or VIF). `ctx.kv(pairs)`, `ctx.note(text)`,
  `ctx.warn(text)`, `ctx.code(text)`, `ctx.row(...nodes)` side by side.
- `ctx.plot(traces, layout, { width, height, title })` a themed Plotly
  graph. Give a trace `rows` and it is linked: clicking or dragging selects
  rows, selected rows are highlighted, row colours, markers, labels and
  hidden rows are applied. `rows` is one row number per point; for a bar
  trace an array of row numbers per bar (the selected share is drawn over
  the bar); for a scatter trace whose points stand for groups of rows
  (subgroup means) an array per point (a point is selected when any of its
  rows is).
- `ctx.saveColumn(name, { rows, values })` adds a column to the table.
- `ctx.reason` says why the report is drawn: `'redo'` (first run, Redo,
  an option changed) or `'theme'` (the same results redrawn in the other
  theme). A platform that changes the table while rendering (colours rows
  by cluster) does it only when the reason is not `'theme'`.
- `scattergl` traces fall back to `scatter` where WebGL is missing
  (`SM.report.hasWebGL()`). Text from a table that goes into Plotly's
  text, hovertext or labels goes through `SM.report.plotlyText()`, which
  escapes the little HTML Plotly reads. `ctx.plot(..., { rowColors: false })`
  for a graph coloured by a column of its own; `rowsScale` may be one
  number per bar. Mark builder controls `data-noexport` to keep them out
  of Save Report as HTML.
- Everything is built with `SM.util.el()` (text nodes only). Never put
  table-derived text into `innerHTML`: a table from a file is untrusted.

A platform's report must work in both themes (use the CSS variables of
kvot.css, and colours that read on both), at phone width, and with By.

## What the core test checks

`test-ui-core.py`: the frame loads without errors, the engine starts, every
(i) has a topic and every Help link a target, the examples, the launch
dialog, the Distribution report against numbers computed in the page,
linking both ways, exclusion and Redo, By and combined By tables, saved
columns, grid editing and Undo, the Local Data Filter and Rows > Data
Filter, a Stata file and a statsmodels dataset read by the engine, the
Python script, the dark theme and phone width.
