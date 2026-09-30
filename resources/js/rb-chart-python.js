/* ==========================================================================
   RB CHART - the chart as Python
   --------------------------------------------------------------------------
   The chart's "Python" button: a script that draws the chart on the screen
   with matplotlib, reading the HDF5 files it is drawn from out of the folder
   the script is in. It is shown, coloured, to copy or download; nothing here
   runs Python.

   Two halves:

     recipes    what a line's numbers are, in the files' terms. The chart
                builders (rb-chart.js) and the toggles (rb-chart-toggles.js)
                compute a line from a dataset in one of several ways -- its
                values, the mean over its realisations, a column of a table of
                statistics, an attribute, one realisation, a sum -- and each
                trace they make carries which, as trace._py, with the numbers
                the way needs (the stride, the column, how many times). Only
                the decision is recorded; the arithmetic is redone in Python.
     the script what is drawn is read from Plotly, as the Excel export reads
                it (xlChartModel): the panels and their axes over the range on
                screen, each line's colour, width and dash, its name, whether
                the legend lists it and where, its bands, and the background's
                phases. Each line's recipe becomes the Python that computes its
                numbers; the rest becomes matplotlib calls.

   Everything a file says -- its name, a dataset's path, a unit, a name in a
   legend -- is untrusted (see kvot-safe.js), and here it is written into a
   program someone will run. So a file's text is only ever written as a
   Python string literal (pyStr), never as code or in a comment; an
   identifier made from it keeps nothing but [a-z0-9_] (pyName). The script
   is shown as text nodes, never as markup (pythonHighlight).

   Nothing here runs at load time; the file holds declarations only.
   ========================================================================== */

'use strict';   // see the script manifest in rb.html for why

/* ── recipes ──────────────────────────────────────────────────────────── */

/*
  A recipe is plain data (it is copied, compared and written out, never run):

    series   { op: 'values', file, path }                 the dataset's values, flat
             { op: 'mean', file, path, n, stride }        the mean over flat[t * stride + r], t < n
             { op: 'column', file, path, n, index, count, layout }
                                                          a column of a table of statistics
                                                          (extractColumnSeriesAt's layout)
             { op: 'attr', file, path, name, n }          an attribute as a series (normalizeAttrSeries)
             { op: 'strided', file, path, stride, k, n }  flat[t * stride + k], t < n: one realisation
    x        { op: 'time', file }                         /time, flat
             { op: 'timeStrided', file, stride, k, n }    one realisation's times, of a probabilistic /time
             { op: 'span', of: [{x, n}, ...] }             every time the chart's time series have

  and a line's recipe, trace._py:

    { x, y, n,                      the first n of each are drawn
      real: { file, path, n, stride } | null
                                    its realisations, flat[t * stride + r]: what the CI band's
                                    percentiles and the SEM band are of (stride null: none found)
      iterStride: number | null     the stride Show iteration reads a realisation with
      nIter: number | null          the file's n_iter, which the SEM divides by (its root)
      ciCols: { p5, p95 } | null    the CI band's edges, from columns
      semCols: { mean, sigma } | null
                                    the SEM band: mean ± sigma / √nIter, from columns or attributes
      constant: { file, path } | null
                                    a value that does not vary over time: its realisations
      total: { parts: [{ y, n, gaps, real: {file, path, stride, n} | null }], n } | null
                                    Show Total: the sum of the parts, and of their realisations
      derived: { kind: 'ci' | 'sem' | 'iteration', of: <a line's recipe>, r } | null }
                                    a band's or an iteration's: which line's, and which realisation
*/

/**
 * The recipe of a series one of the chart builders computed for a dataset
 * (createPlotlyChart, createMultiDatasetChart, computeRadionuclideSeries):
 * which of their paths it went down, in the terms of the file. It takes what
 * they found on the way and decides as they decided:
 *
 *   a table of statistics (colStats)     its mean column, and the 5 % and 95 %
 *                                        columns and sigma when there are those;
 *   realisations (probabilistic)         their mean at each time;
 *   mean and sigma attributes (sdomInfo) the mean attribute, which replaces
 *                                        the values, and the SEM band;
 *   otherwise                            the values.
 *
 * @param {Object} o
 * @param {string} o.fileKey
 * @param {string} o.path - The dataset's
 * @param {number} o.timeLength - How many times it was read against
 * @param {number} o.n - How many points the line has (the builder's minLength)
 * @param {Object|null} o.colStats - getColumnStatisticsSeries's answer
 * @param {boolean} o.probabilistic - Whether it took the realisations path
 * @param {number} o.rawLength - How many values the dataset has
 * @param {number|null} o.shapeStride - getRealizationStride's answer (the realisations' count)
 * @param {Object|null} o.sdomInfo - The SEM band the builder kept, columns' or attributes'
 * @param {number|null} o.nIter - The file's n_iter
 * @returns {Object} the line's recipe (trace._py)
 */
function pySeriesRecipe({ fileKey, path, timeLength, n, colStats, probabilistic, rawLength, shapeStride, sdomInfo, nIter }) {
  const recipe = pyLineRecipe({ x: { op: 'time', file: fileKey }, n, nIter });
  const column = (where) => (where && (where.layout === 'row' || where.layout === 'col')
    ? { op: 'column', file: fileKey, path, n: timeLength, index: where.index, count: colStats.columns.count, layout: where.layout }
    : null);
  const semFromColumns = !!(colStats && nIter > 1 && Array.isArray(colStats.sigmaSeries));
  if (colStats) {
    const cols = colStats.columns || {};
    recipe.y = column(cols.mean);
    if (Array.isArray(colStats.p5Series) && Array.isArray(colStats.p95Series)) {
      const p5 = column(cols.p5);
      const p95 = column(cols.p95);
      recipe.ciCols = p5 && p95 ? { p5, p95 } : null;
    }
    if (semFromColumns) {
      const mean = column(cols.mean);
      const sigma = column(cols.sigma);
      recipe.semCols = mean && sigma ? { mean, sigma } : null;
    }
  } else if (probabilistic) {
    const stride = resolveStride(rawLength, timeLength, shapeStride);
    recipe.y = stride ? { op: 'mean', file: fileKey, path, n: timeLength, stride } : { op: 'values', file: fileKey, path };
    // What the CI and SEM toggles read: the realisations over the line's n times.
    recipe.real = { file: fileKey, path, n, stride: resolveStride(rawLength, n, shapeStride) };
    recipe.iterStride = Number(shapeStride) || null;
  } else {
    recipe.y = { op: 'values', file: fileKey, path };
  }
  // The mean and sigma attributes: their SEM band, and the mean in place of the values.
  if (!probabilistic && !semFromColumns && sdomInfo && Array.isArray(sdomInfo.meanSeries)) {
    const attr = (name) => ({ op: 'attr', file: fileKey, path, name, n: timeLength });
    recipe.y = attr('mean');
    recipe.semCols = { mean: attr('mean'), sigma: attr('sigma') };
  }
  if (!recipe.y) recipe.y = null;   // a layout Python is not given (nested arrays): the numbers go in as they are
  return recipe;
}

/** A line's recipe with nothing but its x, n and n_iter said yet. */
function pyLineRecipe({ x, y = null, n, nIter = null }) {
  return {
    x, y, n,
    real: null, iterStride: null, nIter: Number(nIter) > 1 ? Number(nIter) : null,
    ciCols: null, semCols: null, constant: null, total: null, derived: null
  };
}

/** One realisation of a probabilistic /time, and a dataset read against it (flat[t * stride + k], t < n). */
function pyProbTimeRecipe({ fileKey, path, stride, k, n }) {
  return pyLineRecipe({
    x: { op: 'timeStrided', file: fileKey, stride, k, n },
    y: { op: 'strided', file: fileKey, path, stride, k, n },
    n
  });
}

/**
 * A value that does not vary over time, drawn flat across every time the
 * chart's time series have (constantTrace): the mean of its realisations.
 *
 * @param {Object} o
 * @param {string} o.fileKey
 * @param {string} o.path
 * @param {Object[]} o.series - The time series' traces, which make the span
 * @param {number} o.n - The span's length
 * @param {number|null} o.nIter
 */
function pyConstantRecipe({ fileKey, path, series, n, nIter }) {
  const of = series.map(t => (t._py ? { x: t._py.x, n: t._py.n } : null));
  const recipe = pyLineRecipe({ x: of.every(Boolean) ? { op: 'span', of } : null, n, nIter });
  recipe.constant = { file: fileKey, path };
  return recipe;
}

/**
 * A band or an iteration drawn for a line: the line's recipe says what its
 * edges or its realisation are. Null when the line has none.
 *
 * @param {Object} base - The line's trace
 * @param {string} kind - 'ci', 'sem' or 'iteration'
 * @param {number} [r] - The realisation, 0-based, for an iteration
 */
function pyDerivedRecipe(base, kind, r = null) {
  if (!base || !base._py) return null;
  const recipe = pyLineRecipe({ x: base._py.x, n: base._py.n, nIter: base._py.nIter });
  recipe.derived = { kind, of: base._py, r };
  return recipe;
}

/**
 * Show Total's line for one file: the sum of the members' lines, and of their
 * realisations for its bands (accumulateRadionuclideTotal adds them up, in
 * the members' order). `parts` are what that function saw, one a member.
 *
 * @param {Object} o
 * @param {Object[]} o.parts - {py, n, gaps, real}: a member's recipe and length,
 *   whether its gaps count as nothing in the sum, and its realisations
 * @param {number} o.n - The total's length (its first member's)
 * @param {number|null} o.nIter
 */
function pyTotalRecipe({ parts, n, nIter }) {
  if (!parts.length || parts.some(p => !p.py || !p.py.y)) return null;
  const recipe = pyLineRecipe({ x: parts[0].py.x, n, nIter });
  recipe.total = {
    parts: parts.map(p => ({ y: p.py.y, n: p.n, gaps: p.gaps, real: p.real || null })),
    n
  };
  return recipe;
}

/** Whether a member's series has gaps that Show Total counts as nothing (a column's or an attribute's nulls). */
function pySeriesHasGaps(py) {
  return !!(py && py.y && (py.y.op === 'column' || py.y.op === 'attr'));
}

/* ── Python text: what a file says, written so that it stays text ──────── */

/**
 * Characters written escaped in a string literal, besides the backslash and
 * the quote: controls (a line break would end the literal, and a comment),
 * the line and paragraph separators, and the invisible and bidirectional
 * format characters that can make code read other than it runs (CVE-2021-42574).
 */
function pyEscaped(c) {
  return c < 0x20 || (c >= 0x7f && c <= 0x9f) || c === 0xad || c === 0x61c || c === 0x180e
    || (c >= 0x200b && c <= 0x200f) || (c >= 0x2028 && c <= 0x202e) || (c >= 0x2060 && c <= 0x206f)
    || c === 0xfeff || (c >= 0xfff9 && c <= 0xfffb) || (c >= 0xd800 && c <= 0xdfff) || (c >= 0xe0000 && c <= 0xe007f);
}

/** Text as a Python string literal, which is the only way a file's text goes into the script. */
function pyStr(value) {
  let out = '"';
  for (const ch of String(value ?? '')) {
    const c = ch.codePointAt(0);
    if (ch === '\\') out += '\\\\';
    else if (ch === '"') out += '\\"';
    else if (ch === '\n') out += '\\n';
    else if (ch === '\r') out += '\\r';
    else if (ch === '\t') out += '\\t';
    else if (pyEscaped(c)) out += c > 0xffff ? `\\U${c.toString(16).padStart(8, '0')}` : `\\u${c.toString(16).padStart(4, '0')}`;
    else out += ch;
  }
  return `${out}"`;
}

/**
 * Text matplotlib is to show as it is: a $ would start mathtext, so it is
 * written \$, which matplotlib shows as $ (text/_preprocess_math).
 */
function pyText(value) {
  return pyStr(String(value ?? '').replace(/\$/g, '\\$'));
}

/** A number as a Python literal: JavaScript's shortest spelling is one, NaN and the infinities aside. */
function pyNum(value) {
  const n = Number(value);
  if (Number.isFinite(n)) return String(n);
  if (Number.isNaN(n)) return 'np.nan';
  return n > 0 ? 'np.inf' : '-np.inf';
}

const PY_RESERVED = new Set(('False None True and as assert async await break class continue def del elif else except '
  + 'finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case '
  + 'abs all any bin bool bytes callable chr dict dir divmod enumerate eval exec filter float format frozenset getattr '
  + 'globals hasattr hash help hex id input int isinstance issubclass iter len list locals map max min next object oct '
  + 'open ord pow print property range repr reversed round set setattr slice sorted str sum super tuple type vars zip '
  + 'np plt h5py functools path fig ax axes legend lines x y n values rows lower upper colour color label '
  + 'read attribute strided realisations mean_over_realisations percentile sem_band sem_from column span finite_mean '
  + 'add_up gaps_as_zero total_realisations style band hatch axis plotly_labels plot_area show_legend phases '
  + 'FOLDER TEXT GRID MINOR_GRID PT SI CHART').split(/\s+/));

/**
 * A Python name made from a file's text: lower-case letters, digits and _
 * only, so nothing of the text can be anything but a name; `taken` makes it
 * one of its own.
 */
function pyName(text, taken, fallback = 'series') {
  let base = String(text ?? '').normalize('NFKD').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 32);
  if (!base) base = fallback;
  if (/^[0-9]/.test(base)) base = `${fallback}_${base}`;
  let name = base;
  for (let k = 2; taken.has(name) || PY_RESERVED.has(name); k++) name = `${base}_${k}`;
  taken.add(name);
  return name;
}

/* ── the Python the script is made of ─────────────────────────────────── */

/*
  The script's own functions, each written once here and put in a script
  only when something in it calls them. `needs` are the ones it calls in
  turn. They redo the arithmetic of the functions named in their docstrings,
  in the same order, so that the numbers come out as the page's do.
*/
const PY_HELPERS = [
  { name: 'read', needs: [], code: String.raw`
@functools.lru_cache(maxsize=None)
def _file(name):
    return h5py.File(FOLDER / name, "r")


@functools.lru_cache(maxsize=None)
def read(file, path):
    """A dataset's values, flat and as floats, as the HDF5 Browser reads them (read once, never changed)."""
    values = np.asarray(_file(file)[path][()], dtype=float).ravel()
    values.setflags(write=False)
    return values` },
  { name: 'attribute', needs: ['read'], code: String.raw`
def attribute(file, path, name, n):
    """An attribute of a dataset as a series of n times: its one value throughout, or its first n
    values; one that is not a number is a gap (NaN)."""
    a = np.asarray(_file(file)[path].attrs[name], dtype=float).ravel()
    s = np.full(n, a[0]) if a.size == 1 else a[:n].copy()
    s[~np.isfinite(s)] = np.nan
    return s` },
  { name: 'strided', needs: [], code: String.raw`
def strided(values, stride, k, n):
    """values[t * stride + k] for the first n times: realisation k of a dataset stored time by time."""
    return values[k::stride][:n]` },
  { name: 'realisations', needs: [], code: String.raw`
def realisations(values, n, stride):
    """A dataset's realisations at each of the first n times, a row a time: values[t * stride + r]."""
    return values[: n * stride].reshape(n, stride)` },
  { name: 'mean_over_realisations', needs: ['realisations'], code: String.raw`
def mean_over_realisations(values, n, stride):
    """The mean at each of the first n times of its realisations (computeProbabilisticMean)."""
    return realisations(values, n, stride).mean(axis=1)` },
  { name: 'percentile', needs: [], code: String.raw`
def percentile(rows, q):
    """The q-th percentile of each row's finite values, between the two nearest as the HDF5 Browser
    takes it (computeProbabilisticPercentile); a row with none is a gap."""
    rows = np.atleast_2d(rows)
    finite = np.isfinite(rows)
    count = finite.sum(axis=1)
    ordered = np.sort(np.where(finite, rows, np.inf), axis=1)
    at = q / 100 * np.maximum(count - 1, 0)
    lo, hi = np.floor(at).astype(int), np.ceil(at).astype(int)
    row = np.arange(len(rows))
    a, b = ordered[row, lo], ordered[row, hi]
    with np.errstate(invalid="ignore"):
        out = np.where(lo == hi, a, a * (1 - (at - lo)) + b * (at - lo))
    return np.where(count > 0, out, np.nan)` },
  { name: 'sem_band', needs: [], code: String.raw`
def sem_band(rows, n_iter):
    """The SEM band's edges from realisations: each row's mean ± its standard deviation / √n_iter,
    over its finite values (computeProbabilisticSDOMBand)."""
    rows = np.atleast_2d(rows)
    finite = np.isfinite(rows)
    count = finite.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(finite, rows, 0.0).sum(axis=1) / count
        squares = np.where(finite, (rows - mean[:, None]) ** 2, 0.0).sum(axis=1)
        variance = np.where(count > 1, squares / (count - 1), 0.0)
    sem = np.sqrt(np.maximum(variance, 0.0)) / np.sqrt(n_iter)
    return np.where(count > 0, mean - sem, np.nan), np.where(count > 0, mean + sem, np.nan)` },
  { name: 'sem_from', needs: [], code: String.raw`
def sem_from(mean, sigma, n_iter):
    """The SEM band's edges from a mean and a sigma: mean ± sigma / √n_iter where both are numbers."""
    k = min(len(mean), len(sigma))
    mean, sem = mean[:k], sigma[:k] / np.sqrt(n_iter)
    ok = np.isfinite(mean) & np.isfinite(sem)
    return np.where(ok, mean - sem, np.nan), np.where(ok, mean + sem, np.nan)` },
  { name: 'column', needs: [], code: String.raw`
def column(values, n, index, count, layout):
    """Column index of a table of count statistics over n times, stored a row a time
    (values[t * count + index]) or a column a time (values[index * n + t]); a value that is not a
    number is a gap."""
    s = (values[index::count][:n] if layout == "row" else values[index * n:index * n + n]).copy()
    s[~np.isfinite(s)] = np.nan
    return s` },
  { name: 'span', needs: [], code: String.raw`
def span(*times):
    """Every time the given time series have, once each and in order."""
    t = np.concatenate(times)
    return np.unique(t[np.isfinite(t)])` },
  { name: 'finite_mean', needs: [], code: String.raw`
def finite_mean(values):
    """The mean of the finite values: a value that does not vary over time, drawn flat."""
    return values[np.isfinite(values)].mean()` },
  { name: 'gaps_as_zero', needs: [], code: String.raw`
def gaps_as_zero(series):
    """A series with its gaps as 0: how Show Total adds a column's or an attribute's."""
    return np.where(np.isnan(series), 0.0, series)` },
  { name: 'add_up', needs: [], code: String.raw`
def add_up(n, parts):
    """Show Total: the sum of the parts over the first n times; one that ends early adds nothing after."""
    total = np.zeros(n)
    for part in parts:
        k = min(len(part), n)
        total[:k] += part[:k]
    return total` },
  { name: 'total_realisations', needs: ['gaps_as_zero'], code: String.raw`
def total_realisations(parts):
    """Show Total's realisations, a row a time, for the total's bands, added up part by part as the
    HDF5 Browser adds them (accumulateRadionuclideTotal). A part is its series and its realisations:
    rows, None for a part without them, or False for one whose could not be read. None when they do
    not add up (two parts with different realisations)."""
    rows, before = None, []
    for series, real in parts:
        before.append(series)
        if real is False:
            continue
        if real is not None:
            if rows is None:
                base = np.zeros(len(real))
                for s in before[:-1]:
                    k = min(len(s), len(base))
                    base[:k] += gaps_as_zero(s[:k])
                rows = real + base[:, None]
            elif rows.shape == real.shape:
                rows = rows + real
            else:
                rows = None
        elif rows is not None:
            k = min(len(rows), len(series))
            rows[:k] += series[:k, None]
    return rows` },
  { name: 'style', needs: [], code: String.raw`
def style(colour, width=2, dash="solid"):
    """A line as the page draws it: its colour, width px wide, and Plotly's dash pattern."""
    d = max(width, 3) / width  # Plotly's dash unit, in line widths
    dashes = {"dot": (0, (d, d)), "dash": (0, (3 * d, 3 * d)), "longdash": (0, (5 * d, 5 * d)),
              "dashdot": (0, (3 * d, d, d, d)), "longdashdot": (0, (5 * d, 2 * d, d, 2 * d))}
    return {"color": colour, "linewidth": width * PT, "linestyle": dashes.get(dash, "-")}` },
  { name: 'band', needs: [], code: String.raw`
def band(ax, x, lower, upper, colour):
    """A band between two edges, filled as the page fills it, with no edge of its own."""
    k = min(len(x), len(lower), len(upper))
    ax.fill_between(x[:k], lower[:k], upper[:k], color=colour, linewidth=0, zorder=2)` },
  { name: 'hatch', needs: ['style'], code: String.raw`
def hatch(ax, x, lower, upper, colour):
    """The SEM band's hatching: a dotted stroke across the band every so often."""
    k = min(len(x), len(lower), len(upper))
    i = np.arange(0, k, max(1, k // 36))
    i = i[np.isfinite(lower[i]) & np.isfinite(upper[i])]
    s = style(colour, 1, "dot")
    ax.vlines(x[i], lower[i], upper[i], colors=s["color"], linewidths=s["linewidth"],
              linestyles=[s["linestyle"]], zorder=2)` },
  { name: 'plotly_labels', needs: [], code: String.raw`
SI = {-15: "f", -12: "p", -9: "n", -6: "µ", -3: "m", 3: "k", 6: "M", 9: "B", 12: "T"}


def plotly_labels(fmt, exponent, log):
    """Tick labels written as Plotly writes them: 20k, 1M and 10k in its B format, 0.2×10⁻⁵ and
    10⁻¹¹ in power."""
    def number(v):
        return ("%g" % v).replace("-", "−")

    def label(v, _pos=None):
        if v == 0:
            return "0"
        if log:
            e = int(round(np.log10(abs(v))))
            if fmt == "power":
                return number(v) if e in (0, 1) else r"$10^{%d}$" % e
            if abs(e) >= 4:
                e3 = 3 * (e // 3)
                return number(v / 10.0 ** e3) + SI.get(e3, "e%d" % e3)
            return number(v)
        if not exponent:
            return number(v)
        if fmt == "power":
            return r"$%s{\times}10^{%d}$" % ("%g" % (v / 10.0 ** exponent), exponent)
        return number(v / 10.0 ** exponent) + SI.get(exponent, "e%d" % exponent)
    return label` },
  { name: 'axis', needs: ['plotly_labels'], code: String.raw`
def axis(ax, which, scale, limits, title="", labels=True, fmt="B", exponent=0):
    """An axis as the page draws it: lin or log over limits, its ticks outside, the grid, and its
    labels as Plotly writes them."""
    getattr(ax, "set_%sscale" % which)(scale)
    getattr(ax, "set_%slim" % which)(*limits)
    part = ax.xaxis if which == "x" else ax.yaxis
    if scale == "log":
        part.set_major_locator(LogLocator(base=10, numticks=100))
        part.set_minor_locator(LogLocator(base=10, subs=np.arange(2, 10), numticks=100))
        part.set_minor_formatter(NullFormatter())
        ax.grid(True, axis=which, which="minor", color=MINOR_GRID, linewidth=PT)
    else:
        part.set_minor_locator(AutoMinorLocator())
    part.set_major_formatter(FuncFormatter(plotly_labels(fmt, exponent, scale == "log")))
    ax.grid(True, axis=which, which="major", color=GRID, linewidth=PT)
    ax.tick_params(axis=which, which="major", direction="out", length=5 * PT, width=PT, color=GRID,
                   labelcolor=TEXT, labelsize=9)
    ax.tick_params(axis=which, which="minor", direction="out", length=3 * PT, width=PT, color=GRID)
    if not labels:
        ax.tick_params(axis=which, which="both", **{"label" + ("bottom" if which == "x" else "left"): False})
    if title:
        getattr(ax, "set_%slabel" % which)(title, fontsize=10.5, color=TEXT)` },
  { name: 'plot_area', needs: [], code: String.raw`
def plot_area(fig, left, top, width, height):
    """An axes where Plotly puts the plot: left, top, width and height in px of the figure."""
    w, h = fig.get_size_inches() * 100
    ax = fig.add_axes([left / w, 1 - (top + height) / h, width / w, height / h])
    ax.set_facecolor("white")
    ax.set_axisbelow("line")
    for spine in ax.spines.values():
        spine.set_color(GRID)
        spine.set_linewidth(PT)
    return ax` },
  { name: 'show_legend', needs: [], code: String.raw`
def show_legend(ax, lines):
    """The legend as the page has it: right of the plot from its top, in the page's order; in more
    columns when one would run off the bottom, and the figure wider when it runs off the right."""
    handles = [lines[k] for k in sorted(lines)]
    if not handles:
        return
    fig = ax.figure
    try:
        renderer = fig.canvas.get_renderer()
    except AttributeError:
        renderer = None
    for ncol in range(1, len(handles) + 1):
        legend = ax.legend(handles, [h.get_label() for h in handles], loc="upper left",
                           bbox_to_anchor=(1.02, 1), ncol=ncol, frameon=False, fontsize=9,
                           labelcolor=TEXT, handlelength=3.3, borderaxespad=0, borderpad=0)
        if renderer is None or legend.get_window_extent(renderer).y0 >= 0 or ncol == len(handles):
            break
        legend.remove()
    if renderer is None:
        return
    over = legend.get_window_extent(renderer).x1 + 10 - fig.bbox.width
    if over > 0:
        boxes = [a.get_position() for a in fig.axes]
        width = fig.bbox.width
        fig.set_size_inches(fig.get_size_inches()[0] + over / fig.dpi, fig.get_size_inches()[1])
        scale = width / fig.bbox.width
        for a, p in zip(fig.axes, boxes):
            a.set_position([p.x0 * scale, p.y0, p.width * scale, p.height])` },
  { name: 'phases', needs: [], code: String.raw`
def phases(axes, spans):
    """The background's phases, behind everything: (name, start, end, colour) each."""
    for ax in axes:
        for _name, start, end, colour in spans:
            ax.axvspan(start, end, color=colour, linewidth=0, zorder=0)` }
];

/** The script's functions a set of them needs, in PY_HELPERS's order. */
function pyHelpersFor(used) {
  const need = new Set();
  const add = (name) => {
    if (need.has(name)) return;
    need.add(name);
    for (const dep of (PY_HELPERS.find(h => h.name === name) || { needs: [] }).needs) add(dep);
  };
  for (const name of used) add(name);
  return PY_HELPERS.filter(h => need.has(h.name));
}

/* ── the script ───────────────────────────────────────────────────────── */

/** A whole number from a recipe, as a Python literal (a recipe holds numbers, never text, but it is checked). */
function pyInt(value) {
  const n = Math.trunc(Number(value));
  return String(Number.isFinite(n) ? n : 0);
}

/** A colour as matplotlib takes it: #RRGGBB, or #RRGGBBAA when it is see-through. */
function pyColour(css, fallback = '000000') {
  const c = xlColor(css, fallback);
  if (c.alpha >= 1) return pyStr(`#${c.hex}`);
  return pyStr(`#${c.hex}${Math.round(c.alpha * 255).toString(16).padStart(2, '0').toUpperCase()}`);
}

/** A list of numbers as a numpy array, wrapped at about 100 characters a line. */
function pyArray(values, indent) {
  const parts = Array.from(values || [], v => (v === null || v === undefined ? 'np.nan' : pyNum(v)));
  const rows = [];
  let row = '';
  for (const p of parts) {
    if (row && row.length + p.length > 96) { rows.push(row); row = ''; }
    row += (row ? ' ' : '') + p + ',';
  }
  if (row) rows.push(row);
  if (rows.length <= 1) return `np.array([${(rows[0] || '').replace(/,$/, '')}])`;
  return `np.array([\n${rows.map(r => `${indent}    ${r}`).join('\n')}\n${indent}])`;
}

/** A Python call written on one line, or one argument a line when that is too long. */
function pyCall(head, args, indent = '') {
  const one = `${head}(${args.join(', ')})`;
  if (indent.length + one.length <= 100) return one;
  return `${head}(\n${args.map(a => `${indent}    ${a},`).join('\n')}\n${indent})`;
}

/**
 * The script for the chart in the plot div: see the top of this file.
 *
 * @param {HTMLElement} gd - The plot div
 * @returns {{code: string, fileName: string, files: string[], literal: number}|null}
 *   `literal`: how many lines went in as their numbers, for want of a recipe
 */
function pyChartScript(gd) {
  const fl = gd && gd._fullLayout;
  const fd = gd && gd._fullData;
  // A time chart only: the histogram of a value's realisations is not written.
  if (!fl || !Array.isArray(fd) || fd.some(t => t.visible === true && !/^scatter(gl)?$/.test(String(t.type || 'scatter')))) return null;
  const model = xlChartModel(gd);
  if (!model) return null;
  const subject = xlChartSubject(model);

  const used = new Set(['style', 'axis', 'plot_area', 'show_legend']);
  const use = (...names) => names.forEach(n => used.add(n));
  const taken = new Set();
  const files = [];
  const data = [];                 // the data section: a name for each dataset read
  const reads = new Map();         // file \n path -> its name
  const panelKeys = model.panels.map(p => p.key);
  const several = panelKeys.length > 1;
  const axRef = (i) => (several ? `axes[${i}]` : 'ax');
  const plots = [];                // the chart section, a statement each
  let literal = 0;

  // The files first, so that their times have the plain names.
  const fileOf = (file) => {
    if (!files.includes(file)) files.push(file);
    return file;
  };
  for (const ft of fd) {
    const py = gd.data[ft.index] && gd.data[ft.index]._py;
    const walk = (node) => {
      if (!node || typeof node !== 'object') return;
      if (typeof node.file === 'string') fileOf(node.file);
      for (const v of Object.values(node)) if (v && typeof v === 'object') walk(v);
    };
    if (ft.visible === true) walk(py);
  }
  const read = (file, path) => {
    const key = `${file}\n${path}`;
    if (!reads.has(key)) {
      const name = path === '/time'
        ? pyName(files.length > 1 ? `time_${file.replace(/\.[^.]+$/, '')}` : 'time', taken, 'time')
        : pyName(String(path).split('/').filter(Boolean).pop() || 'values', taken, 'series');
      reads.set(key, name);
      use('read');
      data.push(`${name} = read(${pyStr(fileOf(file))}, ${pyStr(path)})`);
    }
    return reads.get(key);
  };
  for (const file of files.slice()) read(file, '/time');

  // A series recipe as an expression, and how many values it gives (null: all the dataset has).
  const series = (s) => {
    if (!s) return null;
    switch (s.op) {
      case 'values': return { e: read(s.file, s.path), n: null };
      case 'mean':
        use('mean_over_realisations');
        return { e: `mean_over_realisations(${read(s.file, s.path)}, ${pyInt(s.n)}, ${pyInt(s.stride)})`, n: s.n };
      case 'column':
        use('column');
        return { e: `column(${read(s.file, s.path)}, ${pyInt(s.n)}, ${pyInt(s.index)}, ${pyInt(s.count)}, ${pyStr(s.layout === 'col' ? 'col' : 'row')})`, n: s.n };
      case 'attr':
        use('attribute');
        return { e: `attribute(${pyStr(fileOf(s.file))}, ${pyStr(s.path)}, ${pyStr(s.name)}, ${pyInt(s.n)})`, n: null };
      case 'strided':
        use('strided');
        return { e: `strided(${read(s.file, s.path)}, ${pyInt(s.stride)}, ${pyInt(s.k)}, ${pyInt(s.n)})`, n: s.n };
      default: return null;
    }
  };
  const cut = (found, n) => (found.n !== null && Number(found.n) === Number(n) ? found.e : `${found.e}[:${pyInt(n)}]`);
  const xOf = (x, n) => {
    if (!x) return null;
    switch (x.op) {
      case 'time': return `${read(x.file, '/time')}[:${pyInt(n)}]`;
      case 'timeStrided':
        use('strided');
        return `strided(${read(x.file, '/time')}, ${pyInt(x.stride)}, ${pyInt(x.k)}, ${pyInt(x.n)})`;
      case 'span': {
        use('span');
        const of = x.of.map(o => xOf(o.x, o.n));
        return of.every(Boolean) ? `span(${of.join(', ')})` : null;
      }
      default: return null;
    }
  };
  // Show Total: its parts as they are added, and their realisations.
  const totalParts = (total) => total.parts.map((p) => {
    const found = series(p.y);
    if (!found) return null;
    let e = cut(found, p.n);
    if (p.gaps) { use('gaps_as_zero'); e = `gaps_as_zero(${e})`; }
    return e;
  });
  const totalRows = (total) => {
    const parts = totalParts(total);
    if (parts.some(p => p === null)) return null;
    use('total_realisations', 'realisations');
    const pairs = total.parts.map((p, i) => {
      const real = !p.real ? 'None' : (p.real.stride
        ? `realisations(${read(p.real.file, p.real.path)}, ${pyInt(p.real.n)}, ${pyInt(p.real.stride)})` : 'False');
      return `(${parts[i]}, ${real})`;
    });
    return pyCall('total_realisations', [`[${pairs.join(', ')}]`], '');
  };
  // What a line's recipe draws, as an expression; null when it says nothing Python can redo.
  const lineY = (py) => {
    if (!py) return null;
    if (py.total) {
      const parts = totalParts(py.total);
      if (parts.some(p => p === null)) return null;
      use('add_up');
      return { e: `add_up(${pyInt(py.total.n)}, [${parts.join(', ')}])`, parts };
    }
    if (py.constant) {
      use('finite_mean');
      return { e: `np.full(${pyInt(py.n)}, finite_mean(${read(py.constant.file, py.constant.path)}))` };
    }
    if (py.derived && py.derived.kind === 'iteration') {
      const of = py.derived.of;
      const r = pyInt(py.derived.r);
      if (of.constant) return { e: `np.full(${pyInt(of.n)}, ${read(of.constant.file, of.constant.path)}[${r}])` };
      if (of.real && of.iterStride) {
        use('strided');
        return { e: `strided(${read(of.real.file, of.real.path)}, ${pyInt(of.iterStride)}, ${r}, ${pyInt(of.n)})` };
      }
      return null;
    }
    const found = series(py.y);
    return found ? { e: cut(found, py.n) } : null;
  };
  // A band's two edges, as expressions (or one expression for both).
  const bandEdges = (py, kind) => {
    const of = py && py.derived && py.derived.of;
    if (!of) return null;
    const n = pyInt(of.n);
    if (kind === 'ci') {
      if (of.ciCols) {
        const lo = series(of.ciCols.p5);
        const hi = series(of.ciCols.p95);
        return lo && hi ? [lo.e, hi.e] : null;
      }
      if (of.real) {
        const v = read(of.real.file, of.real.path);
        if (!of.real.stride) return [`${v}[:${n}]`, `${v}[:${n}]`];
        use('realisations', 'percentile');
        const rows = `realisations(${v}, ${pyInt(of.real.n)}, ${pyInt(of.real.stride)})`;
        return [`percentile(${rows}, 5)`, `percentile(${rows}, 95)`];
      }
      if (of.constant) {
        use('percentile');
        const v = read(of.constant.file, of.constant.path);
        return [`np.full(${n}, percentile(${v}, 5)[0])`, `np.full(${n}, percentile(${v}, 95)[0])`];
      }
      if (of.total) {
        const rows = totalRows(of.total);
        if (!rows) return null;
        use('percentile');
        return { rows, edges: ['percentile(rows, 5)', 'percentile(rows, 95)'] };
      }
      return null;
    }
    // The SEM band, and its hatching.
    if (of.semCols && of.nIter) {
      const mean = series(of.semCols.mean);
      const sigma = series(of.semCols.sigma);
      if (!mean || !sigma) return null;
      use('sem_from');
      return { both: `sem_from(${mean.e}, ${sigma.e}, ${pyInt(of.nIter)})` };
    }
    if (of.real && of.real.stride && of.nIter) {
      use('realisations', 'sem_band');
      return { both: `sem_band(realisations(${read(of.real.file, of.real.path)}, ${pyInt(of.real.n)}, ${pyInt(of.real.stride)}), ${pyInt(of.nIter)})` };
    }
    if (of.constant && of.nIter) {
      use('sem_band');
      const v = read(of.constant.file, of.constant.path);
      return [`np.full(${n}, sem_band(${v}, ${pyInt(of.nIter)})[0][0])`, `np.full(${n}, sem_band(${v}, ${pyInt(of.nIter)})[1][0])`];
    }
    if (of.total && of.nIter) {
      const rows = totalRows(of.total);
      if (!rows) return null;
      use('sem_band');
      return { rows, both: `sem_band(rows[:${n}], ${pyInt(of.nIter)})` };
    }
    return null;
  };

  // The legend's order: the page's (legendrank, then the order drawn).
  const listed = fd.filter((ft) => {
    const ut = gd.data[ft.index] || {};
    return ft.visible === true && ft.showlegend !== false && !ut._hiddenFromLegend
      && !ut._isCIBand && !ut._isSDOMBand;
  }).map(ft => ({ index: ft.index, rank: isFinite(ft.legendrank) ? Number(ft.legendrank) : 1000 }))
    .sort((a, b) => (a.rank - b.rank) || (a.index - b.index));
  const place = new Map(listed.map((l, k) => [l.index, k]));

  // A comment where the kind of thing drawn changes (fixed words: never a file's).
  const HEADINGS = {
    line: '# The lines.',
    iteration: '# One realisation, dotted.',
    ci: '# CI: the 5th to the 95th percentile, a band.',
    sem: '# SEM: the mean ± the standard deviation / √n_iter, a band and its hatching.'
  };
  let heading = null;
  const headed = (kind) => {
    if (HEADINGS[kind] && kind !== heading) {
      if (plots.length) plots.push('');
      plots.push(HEADINGS[kind]);
    }
    heading = kind === 'hatch' ? 'sem' : kind;
  };
  let lastRows = null;
  for (const ft of fd) {
    if (ft.visible !== true) continue;
    const ut = gd.data[ft.index] || {};
    const panel = Math.max(0, panelKeys.indexOf(`${ft.xaxis || 'x'}|${ft.yaxis || 'y'}`));
    const ax = axRef(panel);
    const py = ut._py || null;
    const xs = Array.from(ut.x || ft.x || []);
    const ys = Array.from(ut.y || ft.y || []);
    if (ut._isCIBand || ut._isSDOMBand) {
      const kind = ut._isSDOMHatch ? 'hatch' : (ut._isCIBand ? 'ci' : 'sem');
      const colour = pyColour(kind === 'hatch' ? (ft.line && ft.line.color) : ft.fillcolor);
      const fn = kind === 'hatch' ? 'hatch' : 'band';
      use(fn);
      const of = py && py.derived && py.derived.of;
      const x = of ? xOf(of.x, of.n) : null;
      const edges = x ? bandEdges(py, kind === 'hatch' ? 'sem' : kind) : null;
      headed(kind);
      if (!edges) {
        if (kind === 'hatch') continue;   // decoration: drawn with its band, which went in as numbers
        literal++;
        const half = Math.floor(xs.length / 2);
        plots.push(`${fn}(${ax}, ${pyArray(xs.slice(0, half), '')}, ${pyArray(ys.slice(half).reverse(), '')},\n    ${pyArray(ys.slice(0, half), '    ')}, ${colour})`);
        continue;
      }
      // Show Total's realisations, computed once for the bands that read them.
      if (edges.rows && edges.rows !== lastRows) {
        plots.push(`rows = ${edges.rows}`);
        lastRows = edges.rows;
      }
      if (Array.isArray(edges)) plots.push(pyCall(fn, [ax, x, edges[0], edges[1], colour]));
      else if (edges.both) plots.push(pyCall(fn, [ax, x, `*${edges.both}`, colour]));
      else plots.push(pyCall(fn, [ax, x, edges.edges[0], edges.edges[1], colour]));
      continue;
    }

    headed(py && py.derived && py.derived.kind === 'iteration' ? 'iteration' : 'line');
    const line = ft.line || {};
    const mode = String(ft.mode || 'lines');
    const args = [];
    let x = py ? xOf(py.x, py.n) : null;
    let y = x ? lineY(py) : null;
    if (!x || !y) {
      literal++;
      x = pyArray(xs, '');
      y = { e: pyArray(ys, '') };
    }
    const stmt = [];
    let yExpr = y.e;
    if (y.parts && yExpr.length > 90) {
      // Show Total's sum, a part a line.
      stmt.push(`y = add_up(${pyInt(py.total.n)}, [\n${y.parts.map(p => `    ${p},`).join('\n')}\n])`);
      yExpr = 'y';
    } else if (yExpr.length > 60 || yExpr.includes('\n')) {
      stmt.push(`y = ${yExpr}`);
      yExpr = 'y';
    }
    args.push(x, yExpr, `label=${pyText(xlPlainText(ft.name) || `Series ${ft.index + 1}`)}`);
    const width = Number(line.width) || 2;
    const dash = String(line.dash || 'solid');
    args.push(`**style(${pyColour(line.color || (ft.marker && ft.marker.color))}, ${pyNum(width)}${dash !== 'solid' ? `, ${pyStr(dash)}` : ''})`);
    if (mode.includes('markers')) args.push('marker="o"', `markersize=${pyNum((Number(ft.marker && ft.marker.size) || 6) * 0.75)}`);
    if (!mode.includes('lines')) args.push('linestyle="none"');
    const call = pyCall(`${ax}.plot`, args);
    stmt.push(place.has(ft.index) ? `legend[${place.get(ft.index)}] = ${call}[0]` : call);
    plots.push(stmt.join('\n'));
  }

  // The figure: its size and each panel where Plotly put it, in px.
  const W = Math.round(fl.width || 960);
  const H = Math.round(fl.height || 500);
  const box = (key) => {
    const [xref, yref] = key.split('|');
    const xa = fl[xlAxisKey(xref, 'x')] || fl.xaxis;
    const ya = fl[xlAxisKey(yref, 'y')] || fl.yaxis;
    return { xa, ya, args: [xa._offset, ya._offset, xa._length, ya._length].map(v => pyNum(Math.round(Number(v) * 10) / 10)) };
  };
  const boxes = panelKeys.map(box);
  const figure = [`fig = plt.figure(figsize=(${pyNum(W / 100)}, ${pyNum(H / 100)}), dpi=100, facecolor="white")`];
  if (several) {
    figure.push(`axes = [  # where the page puts each panel: left, top, width and height, in px\n${boxes.map(b => `    plot_area(fig, ${b.args.join(', ')}),`).join('\n')}\n]`);
    boxes.forEach((b, i) => {
      if (i > 0) figure.push(`axes[${i}].sharex(axes[0])`);
      const matches = b.ya.matches;
      const j = matches ? boxes.findIndex(o => o.ya._name === xlAxisKey(matches, 'y')) : -1;
      if (j >= 0 && j !== i) figure.push(`axes[${i}].sharey(axes[${j}])`);
    });
  } else {
    figure.push(`ax = plot_area(fig, ${boxes[0].args.join(', ')})  # where the page puts the plot: left, top, width, height (px)`);
  }

  // The axes as on screen: lin or log, over the range shown, labelled as Plotly labels them.
  const axisCall = (ax, which, a) => {
    const log = a.type === 'log';
    const r = (a.range || [0, 1]).map(Number);
    const lim = log ? r.map(xlPow10) : r;
    const args = [ax, pyStr(which), pyStr(log ? 'log' : 'linear'), `(${pyNum(lim[0])}, ${pyNum(lim[1])})`];
    const title = xlPlainText(a.title && a.title.text);
    if (title) args.push(pyText(title));
    if (a.showticklabels === false) args.push('labels=False');
    const fmt = String(a.exponentformat || 'B');
    if (fmt !== 'B') args.push(`fmt=${pyStr(fmt)}`);
    const e = Math.round(Number(a._tickexponent) || 0);
    if (!log && e) args.push(`exponent=${pyInt(e)}`);
    return pyCall('axis', args);
  };
  const axesSetup = [];
  boxes.forEach((b, i) => {
    axesSetup.push(axisCall(axRef(i), 'x', b.xa), axisCall(axRef(i), 'y', b.ya));
    const label = model.panels[i] && model.panels[i].label;
    if (several && label) {
      axesSetup.push(`${axRef(i)}.text(0, 1, ${pyText(label)}, transform=${axRef(i)}.transAxes, ha="left", va="bottom", fontsize=8.25, color=TEXT)`);
    }
  });
  if (model.phases.length) {
    use('phases');
    const rows = model.phases.map(p => `    (${pyStr(p.name)}, ${pyNum(p.x0)}, ${pyNum(p.x1)}, ${pyStr(`#${p.color.hex}${Math.round(p.color.alpha * 255).toString(16).padStart(2, '0').toUpperCase()}`)}),`);
    const source = [...new Set(model.phases.map(p => p.source).filter(Boolean))];
    if (source.length) axesSetup.push(`BACKGROUND = ${source.length === 1 ? pyStr(source[0]) : `[${source.map(pyStr).join(', ')}]`}  # the dataset the page read the phases from`);
    axesSetup.push(`phases(${several ? 'axes' : '[ax]'}, [\n${rows.join('\n')}\n])`);
  }

  const date = new Date().toLocaleString('sv-SE').slice(0, 10);
  const imports = ['import functools', 'from pathlib import Path', '', 'import h5py', 'import matplotlib.pyplot as plt',
    'import numpy as np', 'from matplotlib.ticker import AutoMinorLocator, FuncFormatter, LogLocator, NullFormatter'];
  const helpers = pyHelpersFor(used);
  const out = [
    '"""A chart of the HDF5 Browser (kvotab.se/rb.html), drawn with matplotlib.',
    '',
    'Run it in the folder the HDF5 files are in (FILES names them). It needs h5py,',
    'numpy and matplotlib: pip install h5py numpy matplotlib. It reads the datasets',
    'the chart is drawn from and computes from them what the page computed, so it',
    `draws the same lines. Made by the HDF5 Browser on ${date}.`,
    '"""',
    ...imports,
    '',
    `CHART = ${pyStr(subject.title)}`,
    `FILES = [${files.map(pyStr).join(', ')}]`,
    'FOLDER = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()',
    'TEXT, GRID, MINOR_GRID = "#2D2416", "#E5DDD5", "#F0EBE5"  # the page\'s light theme',
    'PT = 0.75  # points in a px: widths and lengths are the page\'s, in px',
    '',
    '',
    helpers.map(h => h.code.replace(/^\n/, '')).join('\n\n\n'),
    '',
    '',
    '# The datasets the chart is drawn from.',
    ...data,
    '',
    '# The chart, line by line in the order the page draws them.',
    ...figure,
    'legend = {}  # the lines the legend lists, by their place in it',
    ...(literal ? [`# ${literal === 1 ? 'One line is' : `${literal} lines are`} given as their numbers: the page did not say how it read ${literal === 1 ? 'it' : 'them'}.`] : []),
    ...plots,
    '',
    ...axesSetup,
    `show_legend(${several ? 'axes[0]' : 'ax'}, legend)`,
    'if fig.canvas.manager is not None:',
    '    fig.canvas.manager.set_window_title(CHART)',
    'plt.show()',
    '# fig.savefig("chart.png", dpi=150, bbox_inches="tight")  # or save it',
    ''
  ];
  return { code: out.join('\n'), fileName: xlFileName(subject).replace(/\.xlsx$/, '.py'), files, literal };
}

/* ── the dialog ───────────────────────────────────────────────────────── */

/* The colours: smui.html's tokenizer (smui-editor.js pythonTokens), read-only here. */
const PY_KEYWORDS = new Set(['False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await', 'break', 'class',
  'continue', 'def', 'del', 'elif', 'else', 'except', 'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is',
  'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'try', 'while', 'with', 'yield']);
const PY_BUILTINS = new Set(('abs all any bool dict enumerate float getattr globals int isinstance len list max min '
  + 'next object open print range repr reversed round set sorted str sum tuple type zip AttributeError').split(' '));
// comment | string (with its prefix; triple-quoted ones span lines) | number | decorator | name | space | anything else
const PY_TOKEN = /(#[^\n]*)|((?:[rRbBuUfF]{1,2})?(?:"""[\s\S]*?(?:"""|$)|'''[\s\S]*?(?:'''|$)|"(?:\\[\s\S]|[^"\\\n])*(?:"|$)|'(?:\\[\s\S]|[^'\\\n])*(?:'|$)))|((?:\b0[xX][\da-fA-F_]+|(?:\b\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)(?:[eE][+-]?\d[\d_]*)?[jJ]?)\b)|(@[A-Za-z_][\w.]*)|([A-Za-z_]\w*)|(\s+)|([\s\S])/y;

/** The script's tokens: [class, text], the class c, s, n, d, f, k or b, or null. */
function pythonTokens(src) {
  const out = [];
  PY_TOKEN.lastIndex = 0;
  let m;
  let prev = '';
  while (PY_TOKEN.lastIndex < src.length && (m = PY_TOKEN.exec(src))) {
    if (m[1]) out.push(['c', m[1]]);
    else if (m[2]) out.push(['s', m[2]]);
    else if (m[3]) out.push(['n', m[3]]);
    else if (m[4]) out.push(['d', m[4]]);
    else if (m[5]) {
      const w = m[5];
      out.push([prev === 'def' || prev === 'class' ? 'f' : PY_KEYWORDS.has(w) ? 'k' : PY_BUILTINS.has(w) ? 'b' : null, w]);
      prev = w;
      continue;
    } else out.push([null, m[6] || m[7]]);
    if (!m[6]) prev = '';
  }
  return out;
}

/**
 * The script in `target`, coloured, a line a block (its number is the
 * block's ::before, so a copy leaves it out). Built of text nodes and spans
 * with a class, never parsed as markup: the script holds the files' text.
 */
function pythonHighlight(target, src) {
  target.textContent = '';
  const frag = document.createDocumentFragment();
  let line = document.createElement('span');
  line.className = 'ln';
  for (const [cls, text] of pythonTokens(src)) {
    const parts = text.split('\n');
    parts.forEach((part, i) => {
      if (i > 0) {
        frag.appendChild(line);
        line = document.createElement('span');
        line.className = 'ln';
      }
      if (!part) return;
      if (cls) {
        const span = document.createElement('span');
        span.className = `t-${cls}`;
        span.textContent = part;
        line.appendChild(span);
      } else {
        line.appendChild(document.createTextNode(part));
      }
    });
  }
  frag.appendChild(line);
  target.appendChild(frag);
}

let _pythonScript = null;

/** The Python button: the script for the chart on screen, in a dialog to read, copy or download. */
function openPythonDialog() {
  const dialog = document.getElementById('pythonDialog');
  const gd = document.getElementById('plotlyChart');
  const script = dialog && gd ? pyChartScript(gd) : null;
  if (!script) {
    notifyUser('Python is written for a time chart: draw one first.');
    return;
  }
  _pythonScript = script;
  pythonHighlight(document.getElementById('pythonCode'), script.code);
  // What it reads and needs; the files' names as text.
  const note = document.getElementById('pythonNote');
  note.textContent = '';
  const add = (text, code = false) => {
    const el = code ? document.createElement('code') : document.createTextNode(text);
    if (code) el.textContent = text;
    note.appendChild(el);
  };
  add('Draws this chart as it is on screen with matplotlib, computing each line from ');
  script.files.forEach((f, i) => {
    if (i) add(i === script.files.length - 1 ? ' and ' : ', ');
    add(f, true);
  });
  add(script.files.length ? '. Save it in the folder the file' + (script.files.length > 1 ? 's are' : ' is') + ' in and run it, with h5py, numpy and matplotlib installed.'
    : '. Run it with numpy and matplotlib installed.');
  if (script.literal) {
    add(` ${script.literal === 1 ? 'One line is' : `${script.literal} lines are`} written as ${script.literal === 1 ? 'its' : 'their'} numbers: the page could not say how it read ${script.literal === 1 ? 'it' : 'them'} from the file.`);
  }
  document.getElementById('pythonCopied').textContent = '';
  dialog.style.display = '';
  const copy = document.getElementById('pythonCopy');
  if (copy) copy.focus();
}

function closePythonDialog() {
  const dialog = document.getElementById('pythonDialog');
  if (dialog) dialog.style.display = 'none';
}

/** Copy: the script as it is, on the clipboard. */
async function copyPythonCode() {
  if (!_pythonScript) return;
  const status = document.getElementById('pythonCopied');
  try {
    await navigator.clipboard.writeText(_pythonScript.code);
    status.textContent = 'Copied.';
  } catch (err) {
    // A page without the clipboard's permission (an old browser, some frames): the selection's copy.
    const area = document.createElement('textarea');
    area.value = _pythonScript.code;
    area.setAttribute('readonly', '');
    area.style.cssText = 'position:fixed;left:-9999px;top:0';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand && document.execCommand('copy');
    area.remove();
    status.textContent = ok ? 'Copied.' : 'Could not copy: select the code and copy it.';
    if (!ok) ignoreFailure('copyPythonCode', err);
  }
}

/** Download: the script as a .py file, named after the chart (as the Excel export names its workbook). */
function downloadPythonCode() {
  if (!_pythonScript) return;
  const blob = new Blob([_pythonScript.code], { type: 'text/x-python' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = _pythonScript.fileName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
