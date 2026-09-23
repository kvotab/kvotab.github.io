# skbref.html modules

`skbref.html` used to be one 6,566-line file: markup, ~360 lines of CSS and a
~6,000-line inline `<script>`. It is now 209 lines of markup that loads
`resources/css/skbref.css` and the modules below.

The split moved code and nothing else. It is verifiable: concatenating the
modules in load order reproduces the original script line for line.

## Load order

| module | what is in it |
| --- | --- |
| `skbref-config.js` | element handles, Zotero endpoint config, settings defaults |
| `skbref-rules.js` | the three rule tables and their id/name metadata |
| `skbref-selftests-rules.js` | self-tests for rules, language and the guide fixture |
| `skbref-shell.js` | analysis state, status line, progress bar, reset |
| `skbref-pdf-input.js` | loading pdf.js, reading a PDF, the format notice |
| `skbref-analyse.js` | `handleFile` — the pipeline both formats run through |
| `skbref-docx.js` | reading a .docx: runs, styles, the paragraph model |
| `skbref-references.js` | finding the reference list and reading its entries |
| `skbref-citations.js` | finding citations and cross-referencing them |
| `skbref-zotero.js` | the Zotero client: settings, zotero.sqlite or a web source, matching, the results |
| `skbref-export.js` | the CSV and the standalone HTML report |
| `skbref-checks.js` | the writing-rule engine, chemistry, ordering, collation |
| `skbref-rulepacks.js` | loading, storing and exporting rule packs |
| `skbref-render.js` | turning a finished analysis into the page |
| `skbref-selftests-references.js` | self-tests for names, designations, the guide |
| `skbref-util.js` | section shells, escaping, bold-run rendering |
| `skbref-boot.js` | **everything that runs at load** |

`skbref-zotero.js` matches with zoterify.html's modules, loaded just before
it: `zoterify-parse.js` reads an entry or a citation, `zoterify-match.js`
judges it against library items (matched, choose, year differs, possible, not
found) and `zoterify-zotero.js` opens zotero.sqlite through sql.js and reads a
web-API item into the same form. A change to their interfaces is a change to
this page too.

## Three things to know before adding code

**Put new work in the module whose subject it shares, not at the end.** The
modules are strictly sequential slices of the original file, and top-level
`const` and `let` are initialised in load order. Adding a declaration is always
safe; moving an existing one between modules may not be.

**Anything that *runs* at load belongs in `skbref-boot.js`.** A `function`
declaration hoists to the top of its own script and no further. The original
file called functions at load time that were declared hundreds of lines below,
which worked only because it was all one script. Putting such a call back in
place fails immediately — `runConsolidatedRegressionTests()` left in
`skbref-selftests-rules.js` throws `ReferenceError: renderRuleContext is not
defined`, because that function now lives in a module loaded later.

**The four-space indent is deliberate.** It is left over from the `<script>`
block, and removing it would also remove four spaces from every line inside a
multi-line template literal — changing the whitespace of the HTML the page
generates, and with it what the tests read back. `skbref-boot.js` is the one
module with no template literal in it, so it alone is not indented.

## Checking a change

    python3 -m http.server 8765                     # from the repository root
    "$CHROME" --headless=new --remote-debugging-port=9222 --user-data-dir=/tmp/p
    python3 resources/tests/site/test-chrome-pdf.py

The page also runs ten self-test suites on load; open the console and they
should report ten passes and no errors.
