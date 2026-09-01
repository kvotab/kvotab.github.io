# Test fixtures for the SKB Reference Checker

## In-page fixture

`skbref.html` runs `runGuideFixtureRegressionTests()` on every load and reports
to the browser console. The fixture holds lines quoted from the three official
guides: correct lines that must produce no finding, and the errors the guides
name explicitly, each with the finding it must produce. It also checks the
reference-list collation from chapter 5 of 1215757 and that project
identifiers such as SFR1 and CCP33 are never read as chemical formulas.

Open the page with the developer console visible; a green line reads

    Guide fixture passed (33 lines from the SKB guides plus collation and chemistry checks).

Add a case to `GUIDE_FIXTURE_CASES` whenever a rule is added or a false
positive is fixed, so it cannot come back.

## End-to-end fixture

`build-fixture-docx.py` writes a small .docx whose runs carry real character
formatting — superscript, subscript, italic and underline — which is the only
way to exercise the checks that read Word formatting rather than plain text:

    python3 build-fixture-docx.py fixture.docx

Then drop `fixture.docx` on the page. The correct paragraphs at the top must
produce no findings; each paragraph under "ERRORS BELOW" must produce exactly
one. The reference list at the end carries a superscript edition ordinal and
an out-of-order entry.

## HDF5 Browser fixtures

`prob-fixture.h5` is a small padded probabilistic file: `/time` and `/grp/DS`
both have shape (40, 8) with `probabilistic=1` and `n_times=[40, 37, 34]`, so
only three of the eight columns are real iterations. The y values are encoded as
`k * 1000 + t`, which makes the iteration identifiable from any single value.

None of the sample files in `resources/data/` is probabilistic, so this fixture
is the only way to exercise the code that reads one iteration out of a padded
matrix. It is the case where inferring the stride from the flat length fails:
for iteration 1 the time axis has 37 points and 320 / 37 is not an integer, so
the old length division gave up and returned all 320 values as if they were a
37-point series. The stride now comes from the dataset shape.

Rebuild it with `build-prob-fixture.py`, which drives h5wasm's writer in a
headless browser (the page itself has no HDF5 writing path).
