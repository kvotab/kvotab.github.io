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
| logn | distribution tabs, metric tab set, input count, the computed result text before and after entering μ and σ |
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

## test-chrome-presets.py

Importing chart presets on rb.html must merge, not replace.

    python3 resources/tests/site/test-chrome-presets.py

`importPresets()` used to pass the parsed file straight to
`savePresetsToStorage()`, which overwrites the storage key outright — so
importing a colleague's two presets destroyed every preset the user had built
up, silently, and then reported success. Nothing looked wrong: the imported
presets were all present. What was missing was everything else.

The test seeds a collection, drives the real `importPresets()` (stubbing the
file-input click so a file can be delivered to it), and asserts all four
properties that matter: a preset absent from the file survives, a colliding one
is replaced, a new one is added, and Default stays first.

## test-chrome-bulk-worker.py

proj.html's bulk conversion must run in its worker, and agree with the main
thread.

    python3 resources/tests/site/test-chrome-bulk-worker.py

The worker is assembled by serialising page functions into a blob, which drops
everything they closed over — the gausskruger module state, the zone tables,
and `point_in_ring`. It threw a `ReferenceError` on its first message every
time, and `worker.onerror` fell back to `convertMainThread()` without a word.
Every bulk conversion ran on the main thread, which is precisely what the
worker exists to avoid.

Both halves are asserted, because either alone would have passed while the bug
was present: the fallback is spied on and must not be taken, *and* the worker's
numbers must equal the main thread's. The `sweref_99_1200` pair is the
important one — a local zone with polygon bounds, so it exercises
`point_in_zone_bounds` → `point_in_ring` → `sweref99_zone_polygons`, the
dependencies that were missing.

## test-chrome-file-origin.py

skbref.html opened from the filesystem rather than from a server.

    python3 resources/tests/pdf/build-fixture-pair.py resources/tests/pdf
    "$CHROME" --headless=new --remote-debugging-port=9222 --user-data-dir=/tmp/p
    python3 resources/tests/site/test-chrome-file-origin.py

No server: that is the point. Every other test here loads the page over http,
so none of them could see this. A page opened with `file://` has a null origin,
which makes every blob URL it creates `blob:null/...`. Given a worker URL it
considers cross-origin, pdf.js wraps it in a second blob that calls
`importScripts()` on the first — and a worker started from a blob cannot
`importScripts` a null-origin blob, so the worker died on every PDF:

    Failed to execute 'importScripts' on 'WorkerGlobalScope'
    The script at 'blob:null/...' failed to load

pdf.js then parsed on the main thread. The analysis was still correct, which is
why this went unreported for so long — what was lost was the speed, and what
was gained was an error telling the reader the page had stopped working.

Three things are asserted, because the first passed even while the bug was
present: that a report is produced, that no error reaches the page, and that the
worker actually receives the parsing rather than pdf.js quietly falling back.

## test-chrome-distributions.py

logn.html holding several distributions at once.

    python3 -m http.server 8765 --bind 127.0.0.1
    "$CHROME" --headless=new --remote-debugging-port=9222 --user-data-dir=/tmp/p
    python3 resources/tests/site/test-chrome-distributions.py

Only the selected distribution has panels in the DOM. Every other one is
computed from a store of what was typed into it, and the three ways that store
can go wrong are all silent:

**One distribution's values written into another's store.** The panels are
cleared and rebuilt when the selection changes, so what is on screen is kept
first. After a *distribution* switch the panels still hold the outgoing one's
values while the incoming one is already active — and the fields line up
exactly whenever the two were built from the same metrics. Selecting B after A
copied A's numbers into B and destroyed B's own. The panels are now stamped
with the distribution they were built for, and the store is written only while
that stamp matches. The test builds A and B on μ and σ and C on mean and GSD,
precisely so that A and B collide and C does not.

**A typed value rebuilt from its own result.** Filling each panel from the
distribution's μ and σ is what lets a metric swap carry the distribution
across, and applying it to a value the user typed turns 50 into the 50 that
comes back out of `exp(ln(50))`. A stored value now wins, and the derived value
fills only what has none.

**The distribution forgotten between two metrics.** Swapping σ for GSD passes
through a moment where only one metric is selected and the distribution is
undetermined. Treating that as "no result" threw away the μ and σ that GSD's
starting value is derived from, so it offered the template default of 1 instead
of e^σ. A half-filled form is no longer a reason to forget; a contradictory one
still is.

It also asserts that one distribution that does not resolve leaves the others
on the chart, and that with a single distribution the chart draws the exact
five traces it drew before there could be several — that being the case every
existing user of the page is in.

The chart opens on the log scale, so the linear branch is no longer reached by
simply loading the page. Unticking `ln(x) view` has to give the same
distribution over the same percentiles, which is the same axis range
exponentiated, and that is checked rather than assumed.

Data is fitted to a distribution of its own, so it shares one with nothing: it
is disabled while a metric is selected and every metric is disabled while it
is. Both directions are asserted, and so is the pair of clicks that should
change nothing. What deselecting must not throw away is the pasted values — the
store keeps what μ and σ cannot reconstruct, and losing a data set to a
mis-click would be worse than offering it again. The raw-data switch is checked
to take the histogram and the step CDF off the chart without taking the fit
with them.

The chart is open when the page loads, which is two claims rather than one:
`drawChart()` refuses to run against a closed `<details>` because it has no
dimensions to size to, so the test reads the trace list and the plot width
before touching anything.

Finally the two chart switches, because switching a thing off must also switch
off what validates it. The shade percentiles describe the band and nothing
else; leaving them validated meant a range left over from an earlier chart
blocked every redraw while the band it described was not being drawn at all.
The test puts a shade percentile outside the chart bounds, confirms it is
reported while the band is on, and confirms it stops blocking — and that the
fields grey out — once the band is off.

## test-chrome-rdc-mobile.py

Which selections put rdc.html's element list away on a phone.

    python3 -m http.server 8765 --bind 127.0.0.1
    "$CHROME" --headless=new --remote-debugging-port=9222 --user-data-dir=/tmp/p
    python3 resources/tests/site/test-chrome-rdc-mobile.py

Below 600px the list is laid over the graph rather than beside it, so choosing
a nuclide has to move it out of the way — the chain that was just asked for is
behind it. Everything turns on which selections count as choosing, and jstree
reports all of them through one `changed` event:

- the page picks U-238 for itself once the list has loaded. Putting the list
  away for that would mean it is never seen;
- re-sorting rebuilds the list, and jstree restores the selection afterwards.
  Nothing was chosen;
- a tap, a key press and a name typed into the search field are each a person
  asking to see a chain.

The first attempt asked whether anybody had touched the page yet, which
separates the startup choice from a tap and nothing else: the touch that
re-sorted the list also answered it, so sorting on a phone made the list
vanish. What separates them properly is the DOM event jstree passes on — it has
one for a tap or a key press and none for a selection it restored by itself.
The search field selects on the person's behalf and says so explicitly.

The test taps the real controls with touch events and hit-tests each one before
using it, because a control that has been covered or moved still reports its
old box. It also runs the same selections at desktop width, where the list is
beside the graph and nothing should ever move it.
