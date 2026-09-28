# smui.html: tests, and how a platform is written

The page is a statistics workbench in the working style of JMP, with
statsmodels as its engine. JavaScript draws the table, the dialogs, the
reports and the graphs; the statistics are Python (numpy, scipy, pandas,
patsy, statsmodels) running in Pyodide in a module worker.

## Running the tests

Backend tests run the page's Python package (`resources/py/smui`) outside
the browser, through the same `registry.dispatch` and JSON round trip the
page uses. They need a Python with numpy, scipy, pandas, patsy and
statsmodels 0.14 (Pyodide 314.0.7 has statsmodels 0.14.6), and scikit-learn
1.8 for the predictive platforms' suites and test_fit_model.py (Pyodide has
1.8.0). pingouin 0.7, if installed, is one more reference in some suites
(called, never copied: it is GPL-3.0); its checks are skipped without it:

    python3 resources/tests/smui/test_distribution.py   # and test_<module>.py for each module
    node resources/tests/smui/test-formula.js           # the formula language, no browser

| Suite | Checks | Against |
|---|---|---|
| `test_distribution.py` | 158 | scipy/statsmodels directly, JMP's quantile definition, Garwood and DescTools rate intervals; the one-sample effect size and Bayes factor, the binomial Bayes factor |
| `test_models.py` | 36 | NIST Longley, anova_lm type III, JMP's ANCOVA design built by hand |
| `test_io.py` | 9 | a Stata file written by pandas, statsmodels.datasets |
| `test_jmp.py` | 41 | JMPReader.jl's own test tables and the values its runtests.jl expects (the tables are not ours: `fetch-jmp-fixtures.py` puts them in `local/jmp/`, git-ignored; skipped without them) |
| `test_fit_y_by_x.py` | 563 | NIST NoInt1/2, Wampler1/2, Koenker's Engel, China smoking CMH, R lawstat and exactci, JMP's Car Poll example, DescTools, Conover; effect sizes against noncentrality searches and Bonett's published examples, JZS Bayes factors against BayesFactor's published value and Ly et al.'s closed forms, Games–Howell, pingouin |
| `test_fit_model.py` | 1030 | NIST Longley, Wampler; Greene's Spector logit; random-effects formulas; statsmodels' GEE epil example, R gee, Stata robust/cluster/HAC, R lmtest; Stata ivreg2/ivendog (Griliches), Stata qreg (Engel), R strucchange; Generalized Regression against scikit-learn's lasso_path, ElasticNet, LogisticRegression, PoissonRegressor and LassoCV folds; repeated measures against statsmodels AnovaRM and MANOVA, Hotelling's T², JMP's documented Dogs sphericity test and pingouin; partial η² and ω² |
| `test_multivariate.py` | 306 | statsmodels/scipy, brute force, SAS's iris CCC, the bivariate-normal distance correlation; intraclass correlations against Shrout and Fleiss's published coefficients, McGraw–Wong and pingouin; Kendall's W against scipy's Friedman |
| `test_timeseries.py` | 376 | MacKinnon critical values, Hyndman et al. variances, sunspots AR fits, Durbin–Koopman Nile, KFAS, Hamilton 1989, Stata mswitch, Zivot–Andrews 1992, PSS 2001, statsmodels' ARDL example |
| `test_survival.py` | 145 | Kaplan-Meier and Greenwood by hand, survdiff, PHReg, scipy CensoredData |
| `test_nonlinear.py` | 242 | NIST Misra1a, Thurber, MGH09, DanWood, Rat42, Eckerle4, MGH17 |
| `test_quality.py` | 161 | Montgomery's control-chart constants, the published median-range divisors d4 and a simulation, formulas |
| `test_doe.py` | 160 | design properties, statsmodels power, textbook values |
| `test_graph.py` | 266 | statsmodels/scipy smoothers, fits, densities, interpolation; statsmodels' banddepth, fboxplot, hdrboxplot, rainbowplot, beanplot |
| `test_tables.py` | 129 | pandas group-by, merge, melt/pivot, JMP quantiles |
| `test_multits.py` | 167 | statsmodels' documented VAR example, MHM 1999 and MacKinnon 2010 critical values |
| `test_counts.py` | 432 | the Stata and R results bundled with statsmodels' tests, the pscl Vuong formula |
| `test_meta.py` | 139 | statsmodels directly, the textbook formulas, a small example worked by hand |
| `test_treatment.py` | 294 | statsmodels directly, the estimators' formulas, analytic sandwiches, simulated truth |
| `test_gam.py` | 190 | statsmodels GLMGam directly, the penalty search by hand, known true functions |
| `test_mediation.py` | 158 | statsmodels' Mediation called directly with the same seeds, known truth |
| `test_partition.py` | 136 | brute-force cut and grouping searches, scikit-learn trees on the same column, scipy's f_oneway and chi2_contingency, the LogWorth adjustment, a Monte Carlo under no effect, smoothing by hand, Freq as repeated rows, the code on a CSV |
| `test_ensemble.py` | 131 | scikit-learn's forests and boosting called directly (trees, staged curves, probabilities), brute-force out-of-bag losses and permutation importance, JMP's documented probabilities, the code on a CSV |
| `test_neural.py` | 149 | scikit-learn's MLP replayed exactly, a forward pass from the Estimates, an identity network against OLS, WLS and Logit, the code on a CSV |
| `test_learners.py` | 128 | scikit-learn's KNeighbors, GaussianNB, CategoricalNB, SVC, SVR and folds called directly, missing-value products by hand, the code on a CSV |
| `test_gaussproc.py` | 117 | scikit-learn's GaussianProcessRegressor, the closed-form jackknife, known sensitivity indices, the code on a CSV |
| `test_pls.py` | 120 | scikit-learn's PLSRegression and NIPALS written out, van der Voet's test, VIP by formula, the code on a CSV |
| `test_mixtures.py` | 213 | GaussianMixture for the four structures, the one-cluster MLE, the likelihood by scipy, AICc/BIC, the EM fixed point, planted outliers, the code on a CSV |
| `test_embedding.py` | 39 | scikit-learn's TSNE (identical maps), the learning-rate formula, the exact KL divergence of the map, the code on a CSV |
| `test_text.py` | 188 | Porter's 1980 examples, scikit-learn's stop words and CountVectorizer, independent term and phrase counts, the weightings, numpy's SVD, statsmodels' varimax, NMF and LDA, the code on a CSV |
| `test_screening.py` | 150 | scikit-learn's estimators called directly, statsmodels WLS, MNLogit and OrderedModel, enet_path with AICc by hand, brute-force tuning, K-fold refits, the validation column's rounding, the code on a CSV |
| `test_circular.py` | 126 | scipy's circmean, circvar, circstd and vonmises.fit, pingouin's circ_* (and its bundled Berens data, read at run time), the formulas, interval coverage, test sizes, simulated truth |
| `test_profile.py` | 38 | scipy's PchipInterpolator and sobol_indices, the Ishigami function's Sobol indices, known optima, a tree's best leaf on a grid |
| `test_bootstrap.py` | 51 | scipy.stats.bootstrap on the same resamples (percentile, BCa), the formulas, the code on a CSV |
| `test_predictive.py` | 102 | scikit-learn's metrics (r2, log loss, accuracy, ROC AUC and curve, confusion), the formulas, the code on a CSV |
| `test_mi.py` | 120 | MICE.fit and MI.fit directly, Rubin's rules and Barnard–Rubin by formula, a Monte Carlo |
| `test_copula.py` | 251 | statsmodels directly, closed forms and numerical integrals, simulated truth, the shown code on a CSV |
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

The site is GitHub Pages without Jekyll (`.nojekyll` at the repository
root): Jekyll leaves out files whose names start with an underscore, such
as `resources/py/smui/__init__.py`, which the engine fetches. The local
server serves everything, so test-ui-core.py checks that the file is there.

`page.drag_to(x0, y0, x1, y1)` in cdp.py drags with the mouse as a user
does (the page's own dragstart sets the data; Chrome hands it over by drag
interception).

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
| `resources/js/smui-profiler.js` | `SM.profiler`: the Prediction Profiler of any model a backend exposes |
| `resources/js/smui-bootstrap.js` | `SM.bootstrap`: Bootstrap from any report table's right-click menu, and the Bootstrap report |
| `resources/js/smui-predict.js` | `SM.predict`: the predictive platforms' roles, options, Measures of Fit, confusion, ROC, lift, Column Contributions, Save Columns |
| `resources/js/smui-p-*.js`, `resources/css/smui-*.css` | the platforms, one file and one stylesheet per menu area |
| `resources/py/smui/` | the backend: `registry` (dispatch), `util` (JSON, report tables), `data` (tables as DataFrames), `models` (linear models as JMP reports them), `predictive` (the predictive platforms' data, sets and measures), `profile` (the profiler of any model, desirability, Sobol importance), `bootstrap` (bootstrap confidence limits), one module per platform area; `manifest.json` lists what the worker loads |

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
roles), `api.onRolesChange(fn)`, `api.showRole(key, on)` (a hidden role
takes no columns and is not checked), `api.setRequired(key, on)` and
`api.message(text, 'info')`; `position: 'top'` puts the part above the
roles, and `recall(saved)` runs before the roles are refilled. What `read()` returns beside `roles` and
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
  redraws the report, and `set(key, value, scope, { rerun: false })` does
  not (to set several options before one redraw). Options are saved with
  projects and kept by Redo.
  A scoped lookup falls back to the unscoped option of the same name (so
  one setting can apply to every column), which means unrelated options
  of one report need distinct names.
- `ctx.rt(table)` a report table (p-values as `<.0001*`, sortable, right
  click to copy or make a data table; with By, Make Combined Data Table
  joins the same table of every group). A column with `hidden: true` is an
  optional one the reader can show from the right-click Columns menu (as
  JMP's Std Beta or VIF); `opts.cellClass(row, column)` gives a cell its
  own classes (a minimum marked, a colour-map cell). `ctx.kv(pairs)`, `ctx.note(text)`,
  `ctx.warn(text)`, `ctx.code(text)`, `ctx.row(...nodes)` side by side.
  Save Python Script collects the code of every call, and what `ctx.code`
  shows beyond that (code worked out in the page).
- `ctx.plot(traces, layout, { width, height, title })` a themed Plotly
  graph. Give a trace `rows` and it is linked: clicking or dragging selects
  rows, selected rows are highlighted, row colours, markers, labels and
  hidden rows are applied. `rows` is one row number per point; for a bar
  trace an array of row numbers per bar (the selected share is drawn over
  the bar); for a scatter trace whose points stand for groups of rows
  (subgroup means) an array per point (a point is selected when any of its
  rows is).
- `ctx.saveColumn(name, { rows, values })` adds a column to the table.
- A platform may add an example table of its own with
  `SM.io.addExample(key, { label, about, make })`, `make()` returning an
  `SM.Table`: simulated with `SM.util.rng(seed)`, never a real dataset
  that is not ours. It shows in File > Examples and on the Home tab, and
  `smui.html?example=<key>` opens it.
- `ctx.reason` says why the report is drawn: `'redo'` (first run, Redo,
  an option changed) or `'theme'` (the same results redrawn in the other
  theme). A platform that changes the table while rendering (colours rows
  by cluster) does it only when the reason is not `'theme'`.
- `scattergl` traces fall back to `scatter` where WebGL is missing
  (`SM.report.hasWebGL()`). Text from a table that goes into Plotly's
  text, hovertext or labels goes through `SM.report.plotlyText()`, which
  escapes the little HTML Plotly reads and the `%{` a hovertemplate would
  take for a placeholder. `ctx.plot(..., { rowColors: false })`
  for a graph coloured by a column of its own; `rowsScale` may be one
  number per bar. Mark builder controls `data-noexport` to keep them out
  of Save Report as HTML. Graphs are drawn no wider than the room there is
  (their parent's content box) and follow the window as it narrows; `fit: false` keeps a graph's width
  (it then scrolls inside the report).
- Help for every input: a launch role or option may carry `help` (a sentence
  or two: what it does, when to change it, what the default means); a
  platform's `extra` part may return `help: [[field label, text], ...]` (or a
  function giving that, for fields that come and go); an `SM.ui.form` field
  may carry `help` (or `hint`, which is also shown under the field). The
  dialog's (i) then shows the platform's topic followed by Roles, Options
  and the extra part's fields, or a form's Fields. Controls inside a report
  (a Model Launch panel, Graph Builder's properties) are explained in their
  outline's (i) topic, with a `choices` section; a topic may be a function
  (`SM.info.get(key)` gives a registered topic). Text may use `code` and
  **bold**, nothing else.
- Documents: Save Report as HTML, Save Report as Word and Print… take the
  report's open outlines. Buttons, inputs, selects, (i) slots and anything
  marked `data-noexport` (a Model Launch panel, Graph Builder's zones) are
  left out; a graph becomes an image drawn in the light theme; an inline
  SVG diagram gets its computed paint written in (`SM.report.paintedSvg`,
  the dark theme's colours mapped to the light ones), without elements of
  `role="button"`. The browser's own Print prints the report in view: the
  page's print rules hide the frame, and before printing whatever is wider
  than the paper (a graph, a table, a profiler grid) is scaled to fit it.
- Phones: at 760 px and below a dialog is the whole screen (above the
  site's header, whose menu button steps aside while one is open; it does
  not move), the (i) panel too. HTML drag and drop does not start from a
  finger, so smui-touchdrag.js turns a touch held still for 320 ms and then
  moved into the same drag events a mouse sends (with a stand-in
  dataTransfer), scrolls the box under the finger near its edges, and puts
  dragged text into a text field at its cursor: any `draggable="true"`
  item inside `.sm` or a dialog works by touch with no code of its own.
- The engine's start (smui-engine.js): a browser without WebAssembly or
  module workers gets a plain message at once; while loading, the status
  line shows the time taken, and past `SLOW_AFTER` (90 s) the home page
  says what may hold it (a firewall, proxy or blocker on cdn.jsdelivr.net;
  an old browser or too little memory) with Restart and What it is doing,
  since a stalled download or a worker killed for memory sends no error.
- Loading: smui.html's own scripts are `defer` (fetched together, run in
  their order once the page is parsed; one after another they took a
  phone's latency 48 times over), Plotly is `async` (graphs asked for before
  it comes are drawn when it does), and the app is made at
  DOMContentLoaded. A new script gets `defer` too. Code that needs the app
  at load time waits for it with `SM.whenApp(fn)`, not a timer. Until the
  app takes it away, `#smApp > .sm-boot` stands in: the frame and a
  "Loading the workbench" line.
- A platform's own list that takes columns (Fit Model's Construct Model
  Effects, Multiple Imputation's effects) calls `SM.launch.acceptColumns(el,
  table, onDrop)`, so that columns dragged from the dialog's column list land
  there as they do on a role. Dialogs close only by their buttons, the × and
  Escape: a click beside one makes it flash.
- Lists whose items can be selected together (role lists, effects lists,
  a filter's levels) take clicks through `SM.util.listClick(ev, id, ids,
  sel, mark)`: a click selects one (again on the only one: none), ctrl/⌘
  adds or takes away one, shift the sweep from the item clicked last.
- Graph selections: a handler of `plotly_selected` returns at once while
  `plot.quiet` (the row states are being drawn: Plotly's full redraw
  announces a kept selection box again, and taking that for a new selection
  redrew without end), and selects inside `plot.own(() => ...)`, so that the
  redraw keeps the graph's own box; a selection from elsewhere clears it.
- Everything is built with `SM.util.el()` (text nodes only). Never put
  table-derived text into `innerHTML`: a table from a file is untrusted.

A platform's report must work in both themes (use the CSS variables of
kvot.css, and colours that read on both; `SM.report.BASE`, the points'
colour, is a lighter blue in the dark theme), at phone width, and with By.

### Predictive platforms (scikit-learn)

Pyodide ships scikit-learn 1.8.0 but the page does not load it at the
start: a function that needs it registers
`@api('partition.fit', packages=predictive.SK)` and imports `sklearn`
inside its body; the worker loads the package before the first such call
(the status button says so). Do the same for any other extra package.

- `predictive.prepare(table, y, x, rows, weight, freq, validation, portion,
  seed, missing, coding)` gives `P`: `P.X` (continuous columns as they are;
  a 0/1 column per level of a categorical one, or `coding='ordinal'` its
  level number; Informative Missing: the training mean plus a Missing
  column, a missing level its own column), `P.target` (a number, or the
  level index), `P.levels`/`P.labels`, `P.w` (weight x freq), `P.sets`
  (0 Training, 1 Validation, 2 Test: from a Validation column, or a
  seeded validation portion), `P.train()`, `P.proba(model, X)` (every
  level, in the table's order), `P.encode(frame)`, `P.features` and
  `P.groups` (the X columns of each factor), `P.notes`, and `P.code()`, the
  lines that build the same `d`, `X`, `y`, `w`, `sets` from a CSV export.
- `predictive.report(P, fitted)` (fitted: predictions, or an n x levels
  probability matrix) gives the Measures of Fit per set, the confusion
  matrices, ROC and lift curves, or actual by predicted;
  `predictive.contributions(P, per-feature values)`, `predictive.saved(P,
  predict, proba)` for Save Columns, `predictive.cached(kind, table, rows,
  spec, build)` for the fitted model (the profiler and Save reuse it).
- A predicted probability should never be exactly 0 or 1 when the method
  allows otherwise (JMP's Partition adds a prior to its leaf rates): the
  log-likelihood measures clip at 1e-15, and a 0 on a validation row
  makes them huge.
- `profile.expose(area, build, packages=predictive.SK)` registers
  `<area>.profile`; build(table, rows, **spec) returns
  `predictive.predictor(P, model)` (or any `profile.Predictor`). The page
  draws it with `SM.profiler.render(ctx, parent, { sources: [{ fn:
  '<area>.profile', payload }], scope, option })`.
- `SM.predict.roles()` (Weight, Freq, Validation, By), `SM.predict.options()`
  (Validation Portion, Informative Missing, Random Seed),
  `SM.predict.payload(ctx)` (the seed is drawn once and kept with the
  report when none is given), and the report blocks `measures`,
  `classification` / `classificationItems`, `actualByPredicted`,
  `contributions`, `saveItems`.
- Everything random takes the report's seed (`random_state`), so a redraw
  and the shown code give the same model; `n_jobs` stays 1 (one thread).
- The profiler's red triangle has Desirability Functions, Maximize
  Desirability, Set Desirabilities, Remember Settings and Assess Variable
  Importance for any source exposed with `profile.expose` (one model):
  expose also registers `<area>.maximize` and `<area>.importance`, whose
  own arguments are `des`, `max_seed`, `imp_method`, `imp_n`, `imp_seed`.
  A predictor may carry `data` ({factor: values}) for resampled inputs;
  `predictive.predictor` fills it from the training rows.

### Bootstrap

Any report table (and two-column table) has Bootstrap in its right-click
menu: the report's rows are drawn again with replacement and the platform
renders again on each sample in a headless `ctx` (`ctx.headless`,
`ctx.resampled`): `ctx.plot` draws nothing, `ctx.set` and
`ctx.saveColumn` do nothing, calls skip the cache and the Python script.
So a platform's render must get everything a table shows from its calls
and options, not from side effects; it may test `ctx.headless` to skip
work no table needs. The table is found again by its outline titles and
its place, its rows by their text columns.
  A long fit prints `smui:progress <what> <done> <total>` lines (the engine
  turns them into 'progress' events).

## What the core test checks

`test-ui-profiler.py` (24): the shared profiler on GAM: Desirability Functions, Maximize Desirability against `gam.maximize`, Minimize, Remember Settings, Assess Variable Importance against `gam.importance`, a project, Fit Model's profiler of two responses weighed together by desirability (against `fitmodel.maximize`), dark theme, phone width. Fit Model, GAM, Count Regression and the predictive platforms use the shared profiler.

`test-ui-bootstrap.py` (22): the right-click item, the dialog, progress and Stop, samples against the backend on the same rows, a two-column table with BCa, a By group, the report left untouched, a project, dark theme, phone width.


`test-ui-core.py`: the frame loads without errors, the engine starts, every
(i) has a topic and every Help link a target, the examples, the launch
dialog, the Distribution report against numbers computed in the page,
linking both ways, exclusion and Redo, By and combined By tables, saved
columns, grid editing and Undo, the Local Data Filter and Rows > Data
Filter, a Stata file and a statsmodels dataset read by the engine, the
Python script; the Python code button and Show Python Code by real clicks
(they go by what is open, so a click after a block's own heading closed it
shows it again; an outline closed around the code opens; a report without
code says so), and by a tap on a phone, where the report scrolls to the
code; dialogs moved by their title bar and kept within reach, a
disabled item's submenu shut (the mouse moved by the browser), the tab strip
without a scroll bar; a launch dialog's (i) with its Roles and Options and
a form's with its Fields; Print from a hidden frame (the print dialog stood
in for through the frame's `contentWindow`), Save Report as Word read back
with JSZip (its parts, headings, tables, PNG pictures, the code only when
shown or its block open), the page's own print (emulated print media: the site, menus and
buttons left out, a graph wider than the paper scaled to fit); documents in
the light theme from the dark one, an SVG diagram with its paint; a box
selection in Graph Builder whose edges are then moved (real mouse events)
selects once each time, and a selection made elsewhere takes the kept box
away; clicks, ctrl/⌘ and shift sweeps in a role list and a filter's levels; a click
beside a dialog leaves it open; on a phone (touch emulation) the dialog and
the (i) panel as the whole screen, a swipe that scrolls and a touch drag
onto a role, the model effects, the formula and a Graph Builder zone;
the dark theme and phone width.
