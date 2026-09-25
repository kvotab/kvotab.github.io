# Tests for SimpleFunctions.html

Two of them. `test-model.js` is the arithmetic and the file readers and needs
only Node; `test-ui.py` is the page and needs the server and browser of
`../rb/README.md` (other ports with `SF_HTTP_PORT` and `SF_CDP_PORT`).

    node resources/tests/simplefunctions/test-model.js [--verbose]
    python3 resources/tests/simplefunctions/test-ui.py

Both exit 0 when every check passes.

## What test-model.js checks, and against what

**TR-10-61, table 3-2** (Grivé et al. 2010, public). The example water of
table 3-1 through Version A: all 19 solubilities to the report's two
decimals, every controlling solid, the constant that carries most of the
uncertainty, and the report's ± — which comes out as this page's
linearised 2σ divided by ln 10, because the report's workbooks take
ΔK = K·ΔlogK and quote 0.434·ΔS/S (Nb, Pa and Pd have derivative slips of
their own and are left out of that one check).

**TR-10-61, tables B-1 and B-3.** Version A for Forsmark and Grimsel of
table A-1. Grimsel comes out to the report's digits with Ca + Mg. Forsmark
does so (within 0.02) only with the free HCO3- of table 3-1, 1.77e-3 m,
rather than the 2.2e-3 of table A-1: the report's appendix B was evidently
run with the bicarbonate after speciation. With 2.2e-3 the carbonate-
sensitive solids are up to 0.29 log units off (uranium the most).

**The dataset.** Every reaction balances; the activity terms and ligand
dependences derived from the reactions agree with the SR-Site workbooks'
hand-written ones everywhere except the four entries sf-data.js names, and
the option `reactionTerms` removes those; a few terms written out by hand;
the Pu correction of 2011 and the Ra(OH)+ nesting.

**The water.** The sulphate and calcium mass balances of Version B and the
iron balance of Version A close to 1e-13; Eh and pO2 follow their formulas.

**Sampling and statistics.** The normal quantile against tabulated values
to 2e-14; the Latin hypercube's strata; the same seed giving the same
realisations and another giving others; editing one constant moving only its
own draws; the mean and spread of a sampled constant; the groundwater draws;
fixed constants giving the deterministic answer; percentiles as NumPy's;
the KS distance and Spearman ρ at their limits; the distribution fits.

**Files.** The PSAR groundwater header, semicolons and decimal commas, a
missing value, a table without the columns; a CSOL MAT file written and read
back; reference columns by element name.

## With the SR-Site files

The SR-Site calculations (SKBdoc 1282962) and the PSAR data are not public,
so they are not in the repository. With them on the machine,

    python3 resources/tests/simplefunctions/make-local-fixtures.py <folder>

writes `local/` (git-ignored), and test-model.js then also checks:

* the cached values of two SR-Site workbooks — the merged 1000-water set at
  its row 500, and the temperate fixed-TD case — for every element and every
  free ligand, to 1e-12 (the agreement is about 7e-14);
* the distributions over the 6916 PSAR groundwaters against the PSAR CSOL,
  by the two-sample Kolmogorov–Smirnov test, for all 20 elements.

## What test-ui.py checks

That a first visit loads the in-range TR-10-61 waters and runs them in the
worker; that the variability split adds its two runs, tabulates all 20
elements and gives uranium's spread to the constants; that every tab draws
without a script error; that Version A on the
table 3-1 water shows the report's uranium; that an edit marks the results
stale, a broken reaction is reported, and reset and a new run bring it back;
that the seven downloads come out with the right first bytes; that the CSOL
MAT file written by the page reads back as a reference with a KS distance of
zero for every element; and that an (i) opens and closes its panel.
