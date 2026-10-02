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
(called, never copied: it is GPL-3.0); its checks are skipped without it.
test_screening.py needs xgboost 2.1.4 and lightgbm 4.6.0 (Pyodide's);
test_text.py needs vaderSentiment 3.3.2 for its sentiment checks (skipped
without it) and fetches snowballstemmer 2.2.0 into `local/snowball2/`
(git-ignored) on its first run; the checks that evaluate a saved formula
with the page's own formula engine need `node` (skipped without it):

    python3 resources/tests/smui/test_distribution.py   # and test_<module>.py for each module
    node resources/tests/smui/test-formula.js           # the formula language, no browser

| Suite | Checks | Against |
|---|---|---|
| `test_distribution.py` | 173 | scipy/statsmodels directly, JMP's quantile definition, Garwood and DescTools rate intervals; the one-sample effect size and Bayes factor, the binomial Bayes factor; the code on the whole table's CSV leaves out the rows the report leaves out; Fit All's searches (no statsmodels warnings, a search that did not converge named by a short Powell search, its progress lines, the single fits' AICc) |
| `test_models.py` | 71 | NIST Longley, anova_lm type III, JMP's ANCOVA design built by hand; the formula text of a model (Match codes, centred crossings, By) evaluated by the page's formula engine (needs node) |
| `test_io.py` | 11 | a Stata file written by pandas (its value labels as the coded column's Value Labels), statsmodels.datasets |
| `test_jmp.py` | 53 | JMPReader.jl's own test tables and the values its runtests.jl expects (the tables are not ours: `fetch-jmp-fixtures.py` puts them in `local/jmp/`, git-ignored; skipped without them); the table scripts JMP 18.2 wrote in them, a copy with its script block rewritten in place, a damaged block |
| `test_fit_y_by_x.py` | 746 | NIST NoInt1/2, Wampler1/2, Koenker's Engel, China smoking CMH, R lawstat and exactci, JMP's Car Poll example, DescTools, Conover; effect sizes against noncentrality searches and Bonett's published examples, JZS Bayes factors against BayesFactor's published value and Ly et al.'s closed forms, Games–Howell, pingouin; Save Formula and Save Probability Formula through the formula engine, the logistic Lack of Fit against the saturated model, Hsu's MCB (the one-sided Dunnett quantile against published values and scipy's dunnett), the Unstable test |
| `test_fit_model.py` | 1288 | NIST Longley, Wampler; Greene's Spector logit; random-effects formulas; statsmodels' GEE epil example, R gee, Stata robust/cluster/HAC, R lmtest; Stata ivreg2/ivendog (Griliches), Stata qreg (Engel), R strucchange; Generalized Regression against scikit-learn's lasso_path, ElasticNet, LogisticRegression, PoissonRegressor and LassoCV folds; repeated measures against statsmodels AnovaRM and MANOVA, Hotelling's T², JMP's documented Dogs sphericity test and pingouin; partial η² and ω²; the saved formulas of every personality through the formula engine; the Validation column's sets and Crossvalidation; Stepwise by BIC and for a categorical Y; the logistic Lack of Fit against the saturated model; Std Beta against standardized fits; the indicator parameterization; singular designs; GenReg's Maximum Likelihood against GLM; Inverse Prediction by Fieller; Test Slices against f_test; FDR over several responses |
| `test_mixed.py` | 296 | Fit Model's mixed models: REML with unbounded variance components against the expected mean squares of balanced designs (negative estimates too), the exact split-plot F tests (Kenward–Roger gives them), a dense reference from the published formulas (the REML likelihood, the observed information, Kenward and Roger's covariance and df, Satterthwaite's df, the BLUPs and their prediction errors) for unbalanced, crossed, nested, random-coefficient and every repeated structure, statsmodels' MixedLM where the model is the same, a spatial range at infinity, the code on a CSV |
| `test_multivariate.py` | 1876 | statsmodels/scipy, brute force, SAS's iris CCC, the bivariate-normal distance correlation; intraclass correlations against Shrout and Fleiss's published coefficients, McGraw–Wong and pingouin; Kendall's W against scipy's Friedman; the saved formulas (scores, clusters, distances, discriminant probabilities) evaluated by the page's formula engine (needs node); scikit-learn's silhouettes, scipy's distances, Gower by brute force, Huber's robust scale, Discriminant's validation sets |
| `test_timeseries.py` | 2092 | MacKinnon critical values, Hyndman et al. variances, sunspots AR fits, Durbin–Koopman Nile, KFAS, Hamilton 1989, Stata mswitch, Zivot–Andrews 1992, PSS 2001, statsmodels' ARDL example; Forecast on Holdback (each model by statsmodels on the training values), the Naive, Seasonal Naive and Drift benchmarks (the forecast package's rwf errors), the moving average three ways, Custom constraints, Box-Cox, multiplicative trends, the runs test (and runstest_1samp's correction slip), rolling-origin cross-validation, Time Series Forecast's candidates by ETSModel; each model's one-step predictions at missing values against statsmodels' own |
| `test_survival.py` | 469 | Kaplan-Meier and Greenwood by hand, survdiff, PHReg, scipy CensoredData |
| `test_nonlinear.py` | 472 | NIST Misra1a, Thurber, MGH09, DanWood, Rat42, Eckerle4, MGH17 |
| `test_quality.py` | 913 | Montgomery's control-chart constants, the published median-range divisors d4 and a simulation, formulas; the Alarm Report's counts and rates by hand |
| `test_doe.py` | 960 | design properties, statsmodels power, textbook values; split plots and blocked full factorials by their structure, the design's model fitted by REML against the exact split-plot F tests (Kenward–Roger df), Simulate Responses' formula; Evaluate Design of a split plot against the closed forms of a balanced one (its variances, Satterthwaite df, the exact noncentral F), 20,000 simulated exact tests and REML + Kenward–Roger simulations of an unbalanced one |
| `test_graph.py` | 371 | statsmodels/scipy smoothers, fits, densities, interpolation; statsmodels' banddepth, fboxplot, hdrboxplot, rainbowplot, beanplot; the automatic bins as Make Binning Column's (JMP quantiles), Axis Settings in the code, the maps' boundaries (cdn.plot.ly, read at run time; skipped offline) |
| `test_tables.py` | 178 | pandas group-by, merge, melt/pivot, JMP quantiles; Missing Value Codes and Value Labels in the engine; Tabulate's bins; the SVD and shrunk EM imputations by their fixed points; Missing Value Clustering against scipy's Ward |
| `test_multits.py` | 321 | statsmodels' documented VAR example, MHM 1999 and MacKinnon 2010 critical values |
| `test_counts.py` | 817 | the Stata and R results bundled with statsmodels' tests, the pscl Vuong formula |
| `test_meta.py` | 474 | statsmodels directly, the textbook formulas, a small example worked by hand |
| `test_treatment.py` | 364 | statsmodels directly, the estimators' formulas, analytic sandwiches, simulated truth |
| `test_gam.py` | 308 | statsmodels GLMGam directly, the penalty search by hand, known true functions |
| `test_mediation.py` | 328 | statsmodels' Mediation called directly with the same seeds, known truth |
| `test_partition.py` | 416 | brute-force cut and grouping searches, scikit-learn trees on the same column, scipy's f_oneway and chi2_contingency, the LogWorth adjustment, a Monte Carlo under no effect, smoothing by hand, Freq as repeated rows, AICc, the prediction and leaf formulas, K-fold crossvalidation, the code on a CSV |
| `test_uplift.py` | 148 | Uplift: the interaction F against OLS and WLS with the split × treatment term, the likelihood-ratio χ² against two binomial GLMs (and the Poisson log-linear model with an empty cell), the best root split by brute force, the LogWorth by Monte Carlo under no interaction, the nodes against pandas and ttest_ind, Freq as repeated rows, the summary against OLS, Go, the Qini curve by brute force, the saved formulas in the page's formula engine (needs node), the code on a CSV |
| `test_ensemble.py` | 318 | scikit-learn's forests and boosting where no X is nominal (the same trees and draws), the forest and boosting written anew with pandas where one is (two groups of levels), every grouping by brute force, out-of-bag losses and permutation importance, JMP's documented probabilities, Score Rows, K-fold crossvalidation, the code on a CSV |
| `test_neural.py` | 171 | the gradients by finite differences, the likelihoods against scipy, Linear networks against OLS, WLS, Logit, MNLogit and QuantReg, the Johnson transforms against scipy, the penalty path, tours and folds, the saved formulas through the page's formula engine (needs node), the code on a CSV |
| `test_learners.py` | 367 | scikit-learn's KNeighbors, GaussianNB, CategoricalNB, SVC, SVR and folds called directly, missing-value products by hand, seeded ties, distance weights, Score Rows (`knn.score`, `svm.score`), the Naive Bayes formula, the code on a CSV |
| `test_gaussproc.py` | 200 | scikit-learn's GaussianProcessRegressor, the closed-form jackknife, known sensitivity indices, the code on a CSV |
| `test_pls.py` | 335 | scikit-learn's PLSRegression and NIPALS written out, van der Voet's test, VIP by formula, the code on a CSV |
| `test_mixtures.py` | 341 | GaussianMixture for the four structures, the one-cluster MLE, the likelihood by scipy, AICc/BIC, the EM fixed point, planted outliers, Save Mixture Formulas evaluated by the page's formula engine (needs node), the code on a CSV |
| `test_embedding.py` | 47 | scikit-learn's TSNE (identical maps), the learning-rate formula, the exact KL divergence of the map, the code on a CSV |
| `test_text.py` | 392 | Porter's 1980 examples, the Snowball English (Porter2) stemmer against snowballstemmer 2.2.0 on 235,779 words (fetched into `local/snowball2/`, git-ignored: the 3.x releases follow Snowball 3's revised English), scikit-learn's stop words and CountVectorizer, independent term and phrase counts, JMP's weightings (log10), numpy's SVD, statsmodels' varimax, NMF and LDA; Latent Class Analysis on planted classes, Ward's clusters against scipy, Term Selection against scikit-learn's ElasticNet, VADER against vaderSentiment (skipped without it), the recodes in JMP's order (before stemming), the top loadings by absolute value, the code on a CSV |
| `test_screening.py` | 273 | scikit-learn's estimators called directly, xgboost, lightgbm and Ridge called directly, statsmodels WLS, MNLogit and OrderedModel, enet_path with AICc by hand, brute-force tuning, K-fold refits, a fold column's crossvalidation, the interaction and square terms, the stacking weights against a grid, the validation column's rounding (K Fold, Stratify by Group, balanced), the code on a CSV |
| `test_circular.py` | 216 | scipy's circmean, circvar, circstd and vonmises.fit, pingouin's circ_* (and its bundled Berens data, read at run time), the formulas, interval coverage, test sizes, simulated truth |
| `test_profile.py` | 50 | scipy's PchipInterpolator and sobol_indices, the Ishigami function's Sobol indices, known optima, a tree's best leaf on a grid; partial dependence and ICE by hand; Shapley values against the linear closed form, exact enumeration and additivity |
| `test_bootstrap.py` | 56 | scipy.stats.bootstrap on the same resamples (percentile, BCa), the formulas, the code on a CSV |
| `test_predictive.py` | 325 | scikit-learn's metrics (r2, log loss, accuracy, ROC AUC and curve, confusion), the formulas; the Decision Threshold's cut tables against confusion_matrix at every threshold with Weight × Freq, the ROC table and Youden's point, gains and deciles by hand, median absolute error, the Naive Model, Group Metrics and equal FPR, the fold helpers; Group Metrics of several models at once against the single call on each, the Crossvalidation set; the code on a CSV |
| `test_compare.py` | 147 | Model Comparison: scikit-learn's metrics with the frequencies as weights, Entropy and Generalized RSquare by formula, Model Averaging, ROC against roc_curve, lift and gains by hand, the AUC Comparison against DeLong's structural components, the code on a CSV |
| `test_association.py` | 105 | Association Analysis: every item set counted by brute force, the rules' measures by definition, scipy's fisher_exact and statsmodels' multipletests (FDR), Apriori against FP-growth, JMP's three data formats and Freq, the code on a CSV |
| `test_calculators.py` | 198 | Test Calculators: scipy's t tests on samples with the calculator's summaries, the effect sizes and proportion intervals by their closed forms (Wald, Agresti–Caffo, Newcombe, Katz, Woolf), Holm and Benjamini–Hochberg against multipletests, the graph's tails, the code |
| `test_mi.py` | 327 | MICE.fit and MI.fit directly, Rubin's rules and Barnard–Rubin by formula, a Monte Carlo |
| `test_copula.py` | 864 | statsmodels directly, closed forms and numerical integrals, simulated truth, the shown code on a CSV |
| `test_charts.py` | 1405 | every graph's matplotlib code (Distribution, Fit Y by X, Fit Model) run with Agg on the exported CSV, its figure against the report's numbers: points, lines, bands, bars, boxes, texts and titles |
| `test_notebook.py` | 41 | the notebook's Python: outputs in the order made (streams joined, the last value, a trailing `;`), rich displays (pandas HTML, a statsmodels summary, Plotly dicts, `display()`), figures at `plt.show()` and at the end (SVG; PNG at twice the size for many points), tracebacks from the cell, namespaces, `reset()`, top-level await, `table()`, `table_names()` and `new_table()` |
| `test_jsl.py` | 439 | JSL to Python: the JSL Syntax Reference's rules (precedence, names, escapes, dates, matrices, scopes, error recovery); every translation compiled, read as Python 3.10, and run on a CSV of a small table of our own against numpy and plain Python; the page's platform specs; 400 damaged scripts; a hostile script (a carriage return in a comment, line breaks in a table's name) whose text stays comments |
| `test-formula.js` | 390 | the parser, missing values, every function, no escape to JS |

Every suite that shows Python code also runs that code on a CSV export of
its table and checks that it gives the report's numbers. The export is the
whole table: code for a report that leaves rows out (excluded, filtered, a
By group) says which (`df = df.drop(index=[...])   # the rows the report
leaves out`), and a graph's code (matplotlib, ending in `plt.show()`) sits
right under its graph. A date column is a number in the page (milliseconds
since 1970) and text in the CSV: code that uses one gets, after its
`read_csv` line, the line that turns it back into that number
(`util.dated_code`, which `registry.dispatch` applies to every result's
code, and `SM.report.datedCode` for code the page writes); code that parses
the column itself (`pd.to_datetime(df[...])`, a Time ID) is left to it.

Browser suites, and their checks on 2026-09-30 (core, distribution, search, tables and text on 2026-10-02): association 56, bootstrap 58, calculators 58, circular 276, compare 194, copula 249, core 252, counts 304, distribution 192, dnd 123, dock 75, doe 298, embedding 124, ensemble 407, fitmodel 846, fitybyx 655, gam 387, gaussproc 217, graph 1186, hostile 16, jsl 24, learners 598, mediation 397, meta 431, mixed 196, mixtures 297, multits 464, multivariate 1526, neural 346, notebook 49, partition 695, pls 684, profiler 32, quality 539, screening 297, scripts 59, search 104, survival 414, tables 252, text 390, timeseries 1639, treatment 346, uplift 232
(15,984 in 43 suites in all).

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

`axis_checks.py` is a helper of the browser suites, not a suite: Axis
Settings checks of a platform's own graphs (opened by a real double-click
or the red triangle, the window filled, the graph's axes and shapes read,
its code run in the page's Python, then Redo, a project and the dark
theme); test-ui-distribution.py and test-ui-quality.py use it.

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
| `resources/js/smui-launch.js` | launch dialogs; `SM.launch.place()` and `dropArea()`: columns dragged out of the places they were dropped on |
| `resources/js/smui-panels.js` | the Table, Columns and Rows panels |
| `resources/js/smui-app.js` | the menu bar, tabs, the platform and command registries |
| `resources/js/smui-dock.js`, `resources/css/smui-dock.css` | `SM.dock`: the work area's tab groups (split, moved and ordered by drag; the bars between them; a project's layout) |
| `resources/js/smui-colprops.js` | `SM.colprops`: the column properties' editors in Column Info and Cols > Column Properties (Missing Value Codes, Value Labels, Profit Matrix), and Cols > Preselect Role |
| `resources/js/smui-scripts.js` | `SM.scripts`: table scripts, as JMP keeps them (the Table panel's list, Save Script to Data Table, a script run by its columns' names) |
| `resources/js/smui-axis.js` | `SM.axis`: Axis Settings on every report graph (log scale, range, increment, reverse order, reference lines), kept in `spec.options.axisSettings` and written into the graph's code |
| `resources/js/smui-search.js`, `resources/css/smui-search.css` | `SM.search`: Help > Search… (ctrl/⌘+K, the magnifier at the right of the menu bar): the menu commands, every platform's red-triangle items (read from a stand-in report that is never run: no action is called, no call reaches Python), the open reports' items and the help, ranked by where the words are; choosing one runs it, applies it to the report in front, or launches the platform and applies it once its report has run |
| `resources/js/smui-help.js` | the Help tab and the (i) topics of the frame |
| `resources/js/smui-profiler.js` | `SM.profiler`: the Prediction Profiler of any model a backend exposes |
| `resources/js/smui-bootstrap.js` | `SM.bootstrap`: Bootstrap from any report table's right-click menu, and the Bootstrap report |
| `resources/js/smui-editor.js` | `SM.editor`: the code editor (a textarea over a coloured `<pre>`; Python and JSL) |
| `resources/js/smui-notebook.js` | `SM.notebook`: the notebook tab, `exec()` and `renderOutputs()` (also the reports' code blocks' Run), .ipynb and .py files |
| `resources/js/smui-jsl.js` | `SM.jsl`: JSL to Python, the page's side (each analysis's code from a report run out of sight) |
| `resources/py/smui/notebook.py`, `nb_backend.py` | the notebook's Python: `run_cell`, outputs, `table()`, `new_table()`; matplotlib's backend for it |
| `resources/py/smui/jsl.py`, `jsl_python.py` | JSL to Python: the lexer and parser (a Pratt parser, with recovery), and the translator with the platforms' specs (`jsl.convert`) |
| `resources/py/smui/mixed.py`, `resources/js/smui-p-mixed.js` | Fit Model's mixed models: this page's own REML (unbounded variance components, Kenward–Roger and Satterthwaite df, repeated and spatial structures, GLMM by RSPL) and every mixed endpoint; the report's parts, the launch part, Simulate and Compare Models |
| `resources/js/smui-predict.js`, `resources/css/smui-predict.css` | `SM.predict`: the predictive platforms' roles, options, Measures of Fit, confusion, ROC, lift and gains, Column Contributions, Save Columns; the Decision Threshold and Group Metrics of any two-level probabilities (`SM.predict.threshold`) |
| `resources/js/smui-p-*.js`, `resources/css/smui-*.css` | the platforms, one file and one stylesheet per menu area |
| `resources/py/smui/` | the backend: `registry` (dispatch), `util` (JSON, report tables), `data` (tables as DataFrames), `models` (linear models as JMP reports them), `predictive` (the predictive platforms' data, sets and measures), `profile` (the profiler of any model, desirability, Sobol importance), `bootstrap` (bootstrap confidence limits), one module per platform area; `manifest.json` lists what the worker loads |

## The notebook and the code blocks

A cell runs in the engine (`smui/notebook.py`, `run_cell`), in a namespace
of its own for each notebook; the worker loads the Pyodide packages its
imports name first (`loadPackagesFromImports`), and the engine writes each
open table's CSV, as File > Export CSV writes it, under the name the
reports' code reads (`<name>.csv`, from `util.code_head`), when that
version of the table is not there yet. matplotlib draws with
`smui/nb_backend.py` (Agg; `plt.show()` hands the open figures to the
cell's outputs). A report's code block runs the same way with a fresh
namespace each time, so a platform's code must run on its own: the
standard head (`util.code_head`, or `SM.report.codeHead` for code the page
writes), everything computed from `df`, and for a graph's block matplotlib
ending in `plt.show()`. HTML from an output, a cell's or a file's, goes
through `kvotSanitizeHtml`; images are `<img>`.

Every graph has a code block right under it (the chart tests find it as the
graph's next sibling) that draws it with matplotlib from the CSV, except
the interactive ones (the profilers). The head reads the CSV with
`keep_default_na=False, na_values=[""]`: missing is an empty field, as the
page writes it, and a level named None or NA stays that text. The time
series platforms return a graph's code as a recipe (its lines, with places
for the graph's size and colour and parts kept or dropped by the display
options) that the page assembles, so that a display option never refits.

`smui.tables` is the Tables platform's module: the notebook's list of
tables is `smui.table_names()`. A user-facing name in the package must not
be a module's name, or the module, imported at start, takes its place.

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
  own classes (a minimum marked, a colour-map cell). A column
  `{ key, label, bar: 'count' }` draws a bar of the `count` column's
  values of zero or more in each row, its length the value against the
  largest in the table (Text Explorer's Count Bars): its heading is empty,
  `label` names it in Columns, and it is no data (`tbl._rt`, Copy Table,
  Make into Data Table and Sort by Column leave it out; Bootstrap on it
  takes the column it draws); Save Report as HTML, Print and Save Report
  as Word draw it. `ctx.kv(pairs)`, `ctx.note(text)`,
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
  `ctx.saveFormula(name, expr, spec)` adds a live formula column in the
  page's formula language (smui-formula.js; a formula that does not compile
  throws and adds nothing): Save Prediction Formula and the saved scores and
  clusters use it, for every row whose inputs are present. Python writes
  the text with `util.formula_ref`, `formula_num` and `formula_str`.
- Column properties (smui-colprops.js, kept in table JSON, projects and
  Undo): `col.values` is what analyses see, a Missing Value Code as a
  missing value; the stored codes are in `col.coded` (`SM.table.storedOf`,
  `t.stored`, `t.storedValues`), the codes in `col.missingCodes`, and code
  that reads the CSV gets the line that masks them (`SM.engine.call` and
  `SM.report.datedCode`). `col.valueLabels` (`SM.table.labelOf`,
  `labelPairs`): `SM.grid.cellText` gives the label, `valueText` the value;
  the engine gets values, never labels (Python: `data.value_labels`,
  `level_label`, `missing_codes`). `col.profitMatrix` (`SM.table.profitAligned`;
  not sent to Python, so a platform puts it in its payload) and
  `col.preselectRole`. Set them with `t.setMissingCodes`, `setValueLabels`,
  `setProfitMatrix`, `setPreselectRole`.
- Names: every column and table name is on one line (`SM.table.cleanName`:
  line breaks and control characters become one space, runs of them
  collapse, the ends are trimmed), whichever way it comes in.
- Table scripts (smui-scripts.js): `t.scripts = [{ name, platform, kind,
  spec, idNames }]`, checked when a table is read (what does not fit is
  dropped); `kind: 'launch'` has the spec by column names and opens the
  launch dialog filled in (`SM.launch.open({ platform, table, recall,
  onOK })`), `kind: 'report'` a report's own spec with `idNames`, remapped
  by name when run. Change them with `t.setScripts(list)`;
  `SM.scripts.run(t, s)`, `SM.scripts.saveFromReport(report)`.
- Axis Settings (smui-axis.js) come with every `ctx.plot`: `{ key }` names
  a graph when its title and place do not, `axisCode(name)` gives a
  graph's code the lines for an axis, `axes` lets a platform keep the
  settings itself (Graph Builder), `plotMenu()` adds to the plot's
  right-click menu, and `axisSettings: false` turns them off.
  `axisAlso(name)` gives the axes of other subplots that share one (the
  box plot under Distribution's histogram): a reference line crosses them
  too, in the graph and in the code. Only a code block that ends in
  `plt.show()` gets the settings written in. On a date axis the page gives
  Plotly UTC date text (millisecond numbers are read in the browser's time
  zone).
- A graph's size: every graph but those drawn with `fit: false` (a
  profiler's cells) or `resize: false` has a grip in its lower right corner
  (dragged, its arrow keys, a double-click for the report's size) and Size…
  and Default Size in its right-click menu. The size is kept in
  `spec.options.plotSizes` by the graph's key (`SM.axis.keyOf`), the
  graph's code draws its figure in the same proportions (its one
  `figsize`, `SM.axis.sizedCode`), and a platform that keeps its own size
  (Graph Builder's Graph Size) passes `sizer: { set(w, h), reset() }`,
  which the grip calls when it is let go. The room a graph fits into is
  measured past a parent that only hugs it (a box of a graph and its code),
  so a graph made narrower by a narrow window grows back.
- A platform's own `Plotly.restyle` of x or y goes through
  `SM.report.restyle(gd, update, traces)`: Plotly 2.27 guesses the axis
  types again after such a restyle (a Pareto's causes that look like
  numbers became a linear axis, a date axis a number axis), and this one
  gives the types the graph was drawn with, and each axis's range.
- Table text in code: a comment that writes a level, a value label or any
  value from the table wraps it in `SM.util.oneLine` (Python:
  `util.one_line`), and a string literal always escapes it (`JSON.stringify`,
  `repr`), since a line break would end the comment and the rest would be
  code. `SM.report.unbroken`, which every code block and the report's
  script go through, is the net under that; `test-ui-hostile.py` runs every
  platform on a table of such values.
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
- A list or zone whose items can be dragged out again (the role lists,
  those effects lists, Graph Builder's and Tabulate's zones) is also a
  `SM.launch.place(el, cfg)`, inside a `SM.launch.dropArea(scope)` (the
  dialog or the builder): an item dragged onto another place of the scope
  moves there by that place's rules (`refuses` says why not), onto an item
  of one takes its place, along its own place changes the order, and let go
  anywhere else in the scope is taken out; only a drop does anything (a
  cancelled drag leaves all as it was). Such a drag also carries
  `SM.launch.PLACE`: a handler of drops from a column list tests
  `SM.launch.fromPlace(ev)` and leaves those alone, whatever order the
  handlers run in.
- Reports can be seen side by side (smui-dock.js): a report's view moves
  in the page when its tab goes to another group, and its room changes with
  the bars between groups. Draw for the room there is (the reports already
  fit their graphs on a resize), find the report's own elements from
  `rep.body`, not with `document.querySelector` (with two groups there are
  two views on show; the one in use is `.sm-group.is-focused`), and keep no
  element's scroll position yourself: the groups keep them.
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
- Decision Threshold for any platform's two-level probabilities (Fit Model
  and Fit Y by X logistic, Discriminant, Model Comparison, Uplift): Python
  `r['threshold'] = predictive.threshold(y, prob, levels, sets, w, rows,
  head=...)`, and the page `SM.predict.threshold(ctx, parent, r.threshold,
  { scope, prefix, probName, save, yCol, title })` with
  `SM.predict.thresholdItem(ctx, scope)` for the red triangle; each By group
  keeps its own threshold (`SM.predict.thresholdOption`). The platforms
  under `SM.predict` get it with `classification` or `decisionParts`,
  with Group Metrics (`predict.groups`).
- A Validation column with 4 to 50 values holds K folds: `prepare()` gives
  `P.folds`, `P.k` and `P.fold_values`, and `predictive.fold_masks(P)` and
  `predictive.crossvalidate(P, fit_predict)` use them; a platform that
  crossvalidates takes the folds when there are some.
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
  A long fit prints `smui:progress <what> <done> <total> [words]` lines (the
  engine turns them into 'progress' events, with the call's owner: the
  report whose `ctx.call` made it). Every report's bar shows a run longer
  than 0.8 s (`Report._progressBegin`): a bar, the words ("Fitting the
  Weibull distribution", shown as "… (3 of 12)") or the counts of its own
  calls' lines, the time gone, and Stop, which restarts the engine; the
  report then says it stopped, and its other By groups are not analysed.
  Words that are a number are not shown. Fit Model's mixed fits tag theirs:
  `reml:<tag> <iteration> 250 <−2LL>`, `remlinfo:<tag> <done> <total>` and
  `rspl:<tag> <iteration> 100`, the tag being `fitmodel.mixed`'s `progress`
  argument, and show them in the bar themselves, with their own Stop: an
  element of the bar marked `data-progress` makes the core's step aside.
  Edit > Undo takes back a report's changes: a run that starts from another
  spec than the last run's is a step (named by the menu item chosen since),
  put back with `Report.restoreSpec` and run again. A platform that keeps
  state in the spec without a run (Graph Builder's `gb`; a graph's size,
  the code shown) is left out of it (`UNDO_SKIP` in smui-report.js); one
  with its own undo sets `report.localUndo = { label, can(), undo() }`,
  which Edit > Undo and ctrl/⌘+Z use first while its report is in front.

## What the core test checks

`test-ui-profiler.py` (24): the shared profiler on GAM: Desirability Functions, Maximize Desirability against `gam.maximize`, Minimize, Remember Settings, Assess Variable Importance against `gam.importance`, a project, Fit Model's profiler of two responses weighed together by desirability (against `fitmodel.maximize`), dark theme, phone width. Fit Model, GAM, Count Regression and the predictive platforms use the shared profiler.

`test-ui-bootstrap.py` (22): the right-click item, the dialog, progress and Stop, samples against the backend on the same rows, a two-column table with BCa, a By group, the report left untouched, a project, dark theme, phone width.


`test-ui-notebook.py` (49): Python > New Notebook; code typed with real keys runs on Shift+Enter (the table is the CSV file the reports' code reads) and Ctrl+Enter; `smui.table()` with the modeling types as dtypes, a date column as datetimes, a table opened later there as a file too; `smui.new_table()` into the page; a report's code run in a cell gives the report's mean; figures as SVG and, with many points, PNG; an HTML output sanitised (no script, image or javascript: link); tracebacks; Run All stops at an error; Markdown text cells (only http(s) links); top-level await; `%matplotlib`, `%time` and `%pip`; Restart; .ipynb and .py both ways, an .ipynb from elsewhere opened without running and sanitised; a project with its notebooks; a report's code block edited, run with Shift+Enter (its output under it, the report's layout kept), Reset and Close; Notebook and Save > Open Script in Notebook; the editor's keys (Enter's indent, Tab and Shift+Tab, Ctrl+/, Backspace in an indent, Undo), its colours; closing a notebook with changes; the editor in a report's code block, its two layers alike (a selection on the text); a date column in Graph Builder's smoother and a Bivariate graph, their code run and the page's curve; dark theme and phone width.

`test-ui-jsl.py` (24): Python > JSL to Python; the page's own sample converts (the table read as the reports' code reads it, a formula column as pandas, each analysis as its report's code on the script's table, the imports once at the top); what did not convert as a comment and a note with its line, a click on which shows the line; Open in Notebook runs clean, graphs too, and gives the report's mean; Open the Reports Here opens the four analyses with their options (Fit Line, Means/Anova, t Test); a table that is not open, a column the script makes, a syntax error (the lines after it still convert), a Where() and its mean; a dropped .jsl file; Ctrl+Enter; phone width.

JSL to Python: `jsl.convert` returns the script with a marker line where each analysis goes and a step for it (the page's platform, roles and options by column name, the script's table variable, a Where as a Python mask). The page maps the names to ids (`SM.specs.remap`), runs the report out of sight, and puts its code at the marker: imports to the top, `df = pd.read_csv(...)` as `df = <table variable>` (or `.loc[<where>]`), and without the lines that drop the rows the page's report left out (the script picks its own rows). The order of JSL's operators is the Scripting Guide's Table 5.3; the Syntax Reference has none.

`test-ui-dock.py` (75): the work area's tab groups (smui-dock.js). One group at the start and the Help text on a hidden shelf; the box and the bar that show where a dragged tab would go (each edge of a group, its own middle refused, a place on a strip), and a tab's drag does not mark the places that take columns; tabs dragged with the mouse (Chrome's drag interception): to an edge (a new group there, the room shared, the moved report still scrolled where it was), to the bottom of another group (a split the other way), onto another strip (the group left empty goes, and the split left with one part), along a strip (the order), onto its own group's middle (nothing); a click in a group makes it the one in use; the arrow keys stay in a strip and ctrl+shift+arrow moves a tab; the context menu's Split (off, and why, for a lone tab), Move to Group and Join All Groups; the bar between two parts (dragged, held at 150 px, a double click, ArrowDown, its role); new tabs and Help open in the group in use, new tabs before Help; the Help text back on its shelf when closed; closing tabs and the groups they leave; a hidden view whose group moved keeps its scroll position; a text field under a dropped tab takes nothing; the page's print shows the group in use; a project saves its layout and opens in it again (an older file without one as before); at phone width the groups stack, no new ones are made, and a tab held by touch moves between them.

`test-ui-dnd.py` (123): a column dragged out of the place it was dropped on, with the mouse (Chrome's drag interception) and by touch; what the page shows during the drag (the item dimmed, the place that takes it, the item it would replace or the side it lands on, the places that refuse it dimmed, the Remove label by the pointer) and after it. A launch dialog (Distribution): moved between roles, reordered both ways, put in place of another role's column, refused by a role that does not take its modeling type (and the dialog says why), taken out on the column list and on the lead, left alone by a cancelled drag and by one let go beside the dialog, a list drag still as before, a role's button taking a column from another role or from the list; the report has the roles the drags made. Fit Model's effects (reordered, one taken out, a crossing refused by every role, a column from a role and back) and the Effect Tests in the new order; Multiple Imputation's effects and its pooled model; Graph Builder (between zones in one Undo step, a refusing zone, reordered, replaced, taken out on the list and on the graph, cancelled, let go outside; every point of two Y columns with Group X inside its panel); Tabulate (columns to rows, reordered and nested, the analysis columns reordered, replaced, taken out; the table computed again); the (i) texts; a phone (touch emulation): the carried item, the label, a touch cancel.

`test-ui-hostile.py`: a table whose levels, value labels, texts, table name and a column name carry a line of Python behind a line break (`\n`, `\r`), a closing quote, braces, triple quotes or a trailing backslash; every platform run on it twice (the roles filled from its columns: once with By, once with a nominal response and the optional roles; the options a platform needs before it fits, such as Neural's model and Explore Outliers' methods), a few Graph Builder and Tabulate layouts; every code block and every report's script parsed with Python's `ast`: each parses, and no `INJECTED_*` name is code. Then `SM.report.unbroken` by itself: a value with a line break written as it is into a comment goes on one line, an escaped literal and plain code are left alone, and 20,000 long texts cost milliseconds. `python3 test-ui-hostile.py fitmodel text` runs only those platforms.

`test-ui-scripts.py`: table scripts; a DOE split plot's Model script opens Fit Model with its random effect, by a real click; Save Script to Data Table and the script run back (the same outlines, a closed one, the numbers), replaced by name; Rename and Delete by a real right click, Undo and Redo; a column renamed inside the scripts; missing columns; projects and Save Table; a hostile table JSON; names kept on one line (a CSV header, a JSON table name, a pasted line break); a JMP table's JSL scripts (JMPReader.jl's compact_UInt8.jmp with its script block rewritten in place, from `local/jmp/`): listed with their JSL mark, an analysis run into its report by a real click, an Open() of a file into JSL to Python, Show JSL, Save Table, a hostile JSL script, a column rename; dark theme and phone width.

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
the dark theme and phone width; a graph's size (its corner grip dragged
with the mouse, and its code's figsize in proportion; the grip's arrow
keys; Redo; Size… and Default Size from a real right-click; a narrower
window and back; a project; a double-click; Graph Builder's own Graph
Size, an outline following the drag; the dark theme); the full window (no site header, menu or
footer; the kvot mark to the home page and the theme switch in the menu
bar; kept for the next visit from before the workbench is made; at phone
width its two buttons at the right edge while the menus scroll).
