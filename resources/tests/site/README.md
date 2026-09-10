# Characterisation tests for the whole site

These answer one question: **did a change alter the site's behaviour?** They do
not assert the behaviour is correct — they record what it currently is, so a
refactor can be shown not to have moved it.

## Running

    python3 -m http.server 8765 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      --headless=new --remote-debugging-port=9222 --no-first-run \
      --user-data-dir=/tmp/kvottest --disable-gpu about:blank

Then, from this directory:

    python3 characterise.py before      # before the change
    # ... make the change ...
    python3 characterise.py after
    python3 compare.py before.json after.json

`compare.py` prints `IDENTICAL` or lists every field that moved. One full run
takes roughly 100 seconds and compares 267 fields.

## What is covered

For **every page**: title, header element and tag, nav toggle and its ARIA
state, menu links, footer icon and button counts, theme (applied, stored,
toggled, restored), whether Leaflet is loaded eagerly, the office map's
lazy load and both toggles, and the exported `KVOT` API surface.

Per page, additionally:

| Page | Covered |
|---|---|
| index | project cards, contact icons and their titles, copy buttons, links, meta description |
| 404 | cards, `<base>` resolution, robots |
| logn | tab set, input count, the computed result text before and after entering μ and σ |
| proj | a WGS 84 → RT 90 → SWEREF 99 conversion field by field, bulk conversion, zone tables, `fmt_dms`, point-in-zone |
| rdc | element tree, cytoscape/jQuery/Plotly readiness, decay data loaded, selecting an element |
| skbref | rule counts, the in-page guide fixture, SKB collation, chemical-formula detection, rule packs |
| skb_qa_summary | privacy note, filter ids, `normalize`/`esc`/`csvCell` |
| karaoke | language, control ids, player and lyric stage, page globals |

`test-actions.py <page>` covers the control wiring: every element declaring a
`data-on-<event>` attribute is given that event, and its handler must fire
exactly once. Double-firing is the specific regression the design guards
against — a checkbox emits `click` then `change`. It also checks that an
unknown action name is reported, that a throwing handler is caught, and that
the failure banner appears.

    python3 test-actions.py rb.html      # expect 28/28
    python3 test-actions.py proj.html    # expect 39/39

## Determinism

A full run is byte-identical between runs. Two things had to be handled to get
there:

- the theme-toggle step persists a choice, so the stored theme is cleared at
  the start of each page;
- third-party console noise (the YouTube widget API, CDN and map-tile fetches
  the network happened to drop) varies run to run and is filtered out by
  origin. A failed request for one of *this site's own* files is not external
  and still shows up — that is how a mistyped script URL gets caught.

## test-chrome-buttons.py

Clicks the theme toggle and the office-map button on every page and checks
that the theme attribute, the page background, the button icon and the map's
visibility actually change.

    python3 -m http.server 8765          # from the repository root
    "$CHROME" --headless=new --remote-debugging-port=9222 --user-data-dir=/tmp/p
    python3 resources/tests/site/test-chrome-buttons.py

These two buttons exist only in markup that `site.js` generates at runtime, so
they are invisible to `test-actions.py`: that test enumerates the elements
carrying a `data-on-*` attribute and proves each reaches its handler, which
cannot detect a button that carries the wrong attribute name and therefore
never appears in the inventory. This test starts from the button instead, and
also fails if any element anywhere still uses the superseded `data-action`
name (karaoke.html's own row controls, which bind directly, are exempt).

## test-chrome-pdf.py

Analyses the same report as `.docx` and as `.pdf` and requires the same answer.
`../pdf/build-fixture-pair.py` writes one document in both formats; the `.docx`
states its own structure, so the checker's report on it is by construction the
right answer for that text, and any difference is a defect in the PDF
reconstruction.

    python3 resources/tests/pdf/build-fixture-pair.py resources/tests/pdf
    python3 -m http.server 8765          # from the repository root
    "$CHROME" --headless=new --remote-debugging-port=9222 --user-data-dir=/tmp/p
    python3 resources/tests/site/test-chrome-pdf.py

Beyond report equality it asserts that no rule fires on the PDF whose evidence
a PDF does not carry, that the PDF run invents no rule the `.docx` run did not
fire, and that italic and superscript survive — the one place `pdfFontResolver`
runs against real pdf.js font objects. See `../pdf/README.md` for why each of
those is a separate claim.

The target opens on `about:blank` so the cache can be disabled before anything
is fetched, and the loaded `skb-pdf.js` is identified before any measurement is
taken. Navigating first and disabling the cache afterwards leaves the page's
own scripts served from cache, which had this test reporting a stale
`resources/js/skb-pdf.js` as a code defect.
