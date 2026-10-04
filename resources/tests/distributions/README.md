# Tests for distributions.html

| File | What it proves | Needs |
| --- | --- | --- |
| `test-engine.mjs` (with `engine-checks.mjs`) | The engine in Node: every family's density, CDF, survival function, quantiles in both tails, moments, entropy and median against SciPy (and against mpmath where SciPy loses precision), maximum-likelihood fits at least as good as SciPy's, every parameterisation round-tripping, known values solved and impossible ones refused, the method of moments meeting the sample's moments, truncation, the empirical and table distributions, sampling and Latin hypercube, the expression parser, the calculations and the ranking, one or more checks for each finding of a review of the page (huge shapes against mpmath, standard errors far from zero, the double triangle's likelihood, truncated modes, counts beyond 2^53, the summed CDFs), the sampling schemes (plain Sobol and Halton points against SciPy's, one draw in each stratum for Latin hypercube, scrambled Sobol and Halton, seeds, the draws a Monte Carlo expression takes, K–S from the uniforms), truncation at percentiles, a shift (the statistics that move and those that stay, against mpmath for the geometric mean, counts, the order with truncation, known values of a shifted distribution), Monte Carlo by every scheme, and the histograms' bin rules | Node 20, `scipy-ref.json` and `qmc-ref.json` |
| `gen-qmc-ref.py` | Writes `qmc-ref.json`: SciPy's plain Sobol and Halton points, 64 in each of 16 dimensions | SciPy 1.16 |
| `gen-scipy-ref.py` | Writes `scipy-ref.json`: SciPy's values for 108 cases, 26 samples with SciPy's fits, 11 truncated cases; mpmath (40 digits) where SciPy is known to be imprecise | SciPy 1.16, NumPy, mpmath |
| `test-ui.py` | The page in headless Chrome: loads without a script error, every (i) has a topic, nothing interactive in a `<summary>`, a parameterisation converts without moving the distribution, a bad field is marked and explained, a change of family keeps the mean and SD, known values, truncation, visibility, adding and removing, undefined and infinite moments in the table, a pasted sample fitted and ranked with its best fit and a kernel density added, a table and a Monte Carlo distribution, the Calculate tab's numbers, a random sample handed to the Fit tab, a reload and starting again, the dark theme in the charts, a phone without sideways scroll; and the review's findings on the page: known values after a detour through other numbers, the fit's family choices per kind, outdated fit results dimmed and an answer for old data dropped, a Monte Carlo draw stopped with the fits drawn again, a hypergeometric with N = 10^6 drawn at once, a damaged stored state repaired; and truncation at percentiles and the Sample tab (draws of every distribution, seeds, Latin hypercube and Sobol means, the power-of-two note, draws in the chart, CSV and Excel files, Fit these, a large sample waiting for Draw, a phone); a shift, the numbers under the chart with the draws' rows, the bins of the chart and of the Fit tab, a Monte Carlo expression drawn by the Sobol sequence | a server and Chrome (below) |

```sh
node resources/tests/distributions/test-engine.mjs            # about three seconds; 6,799 checks
node resources/tests/distributions/test-engine.mjs --verbose  # every check, not only failures
python3 resources/tests/distributions/gen-scipy-ref.py        # rewrites scipy-ref.json
python3 resources/tests/distributions/gen-qmc-ref.py          # rewrites qmc-ref.json
```

## The reference values

`scipy-ref.json` holds SciPy's numbers for every family at ordinary and
awkward parameters: tiny shapes (a gamma with k = 0.05), huge counts (a
binomial of five million trials), shapes near a boundary (a GEV with
ξ = 0.0005, a Student's t with ν = 0.7), and points in both tails down to
10⁻¹². The generated values are SciPy's; the file is ours.

Where the engine and SciPy disagreed, mpmath decided, and the generator now
takes those values from mpmath at 40 digits (each such case lists what was
replaced under `arbiter`): the far-tail quantiles of the F and inverse
Gaussian distributions (SciPy is off by about 10⁻⁵ there), the half-normal's
quantiles below 10⁻⁶ (SciPy takes `ndtri((1 + u)/2)`, which loses u),
survival functions SciPy forms as 1 − cdf (the triangular, log-uniform and
Pareto near their ends), the binomial for millions of trials (SciPy is off
by about 10⁻⁹), the GEV's skewness and kurtosis near ξ = 0 and the
log-uniform's over a narrow range (cancellation in SciPy's formulas), and
the entropy of a discrete distribution (SciPy's sum stops early: half the
value for a Poisson of mean 10⁵). Each was confirmed one by one before it
went into the generator.

`mpmath` must convert a double with `mp.mpf(float(x))`, not
`mp.mpf(repr(x))`: the decimal string is a slightly different number, and
the reference is then that of another x (this made the Pareto CDF just
above its minimum look wrong by 3 × 10⁻⁵).

Some moments that do not exist are reported differently on purpose
(`CONVENTION` in `test-engine.mjs`): the page says **∞** when one tail makes
a moment infinite while the moments below it are finite (a Pareto with α = 3
has an infinite skewness), and **undefined** when both tails do (a Student's
t with ν = 0.7 has no mean, where SciPy says inf).

## The browser test

Check the ports first; other sessions use 8765 and 9222 and others:

```sh
lsof -nP -iTCP:8851 -sTCP:LISTEN; lsof -nP -iTCP:9351 -sTCP:LISTEN
python3 -m http.server 8851 --bind 127.0.0.1 &          # from the repository root
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \
    --remote-debugging-port=9351 --no-first-run --user-data-dir=/tmp/dstest --disable-gpu about:blank &
DS_HTTP_PORT=8851 DS_CDP_PORT=9351 python3 resources/tests/distributions/test-ui.py   # 123 checks, about two minutes
DS_SHOTS=/tmp/ds-shots python3 resources/tests/distributions/test-ui.py              # with screenshots
```

A check that reads the page's state imports the page's own module, by the
URL its `<script>` tag gives (`ui.js?v=…`): importing `ui.js` without the
stamp is another module to the browser, which runs the page a second time
beside the first, with its own state and its actions registered twice.

The site-wide guard `resources/tests/site/test-chrome-summary-controls.py`
covers this page too (it opens every page in the root).
