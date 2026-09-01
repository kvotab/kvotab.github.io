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
