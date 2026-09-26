# Characterisation tests for the HDF5 Browser

These exist to answer one question: **did a change to rb.html alter its
behaviour?** They do not assert that the behaviour is correct — they record what
it currently is, so a refactor can be shown not to have moved it.

## Running

Serve the site and start Chrome with remote debugging:

    python3 -m http.server 8765 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      --headless=new --remote-debugging-port=9222 --no-first-run \
      --user-data-dir=/tmp/rbtest --disable-gpu about:blank

The size of Chrome's window does not matter: `open_page` in `driver.py` gives
every page a 1400 × 1000 viewport. It used to matter. `test-axes.py` points the
mouse at the middle of the chart, and Chrome 153's default headless window,
756 × 469, put that point below the viewport. Every tooltip check then read
nothing, and five checks failed with the page working as it should.

Then, from this directory:

    python3 characterise.py before      # before the change
    # ... make the change ...
    python3 characterise.py after       # after the change
    python3 compare.py before.json after.json

`compare.py` prints `IDENTICAL` or lists every field that moved.

`characterise.py` registers its two fixtures with h5wasm directly. With
`--open` it opens them through the page's file input instead, as a reader
does, and with rb-lazy.js's switch set either way: `--open never` reads them
into memory, `--open always` reads them lazily from disk in a worker. The two
fingerprints are the check that a lazy file behaves as a file in memory:

    python3 characterise.py memory --open never
    python3 characterise.py lazy --open always
    python3 compare.py memory.json lazy.json

Three fields differ, and should: `load.two.files/lazy`, which says which way
the files were read, and `file.toggle.remove/afterRemove/memfsBefore` and
`memfsAfter`, which count files in h5wasm's in-memory filesystem, where a lazy
file never is. Anything else that moves is a difference a reader would see.

## What is covered

`characterise.py` walks seventeen steps: the initial DOM inventory, the expected
set of globals, loading two files, tree expansion, selecting a dataset and a
radionuclide group, the chart toggles, log/linear axes, ctrl-multi-select,
five search terms, all three tree modes, the dialogs, CSV and Excel export,
enabling/disabling/removing a file, the information panel for a dataset and for
a group, a dataset exported to Excel, and the rejection of malformed input.

The last two were added to cover `rb-info.js` before it was refactored. The
panel step reads back the section labels, the attribute rows and whether any
value arrived as markup, plus a count of `script`/`iframe`/`object`/`embed`
nodes that must stay at zero. The export step captures the workbook itself: it
stubs `URL.createObjectURL` to catch the blob, opens it with the JSZip already
on the page, and records the sheet list, the rows per sheet and the shared
strings, with the export timestamp normalised so two runs can be compared.

`test-strict.py` asserts that every page script is really running in strict
mode. Having `'use strict'` in the source is not the same as it taking effect —
the directive counts only as the first statement, so a stray statement above it
silently turns the file back into sloppy mode with no error anywhere. The test
probes the function objects instead of the text: a sloppy function carries own
`arguments` and `caller` properties and a strict one does not. It includes a
control that must read as *sloppy*, or the probe is measuring nothing.

`test-debug-gate.py` covers the console gate in `kvot-errors.js`: `kvotTrace`
silent by default, `kvotWarn` still printing but once per message, and both
fully restored by `?debug=1` or `localStorage.kvotDebug`.

`test-actions.py` covers the control wiring specifically: every element with a
`data-action` attribute is given the event it declares, and its handler must
fire exactly once. It also checks that an unknown action is reported, that a
throwing handler is caught, and that the failure banner appears.

`test-url.py` covers loading by URL: which host a GitHub address is rewritten
to, and -- the check that matters -- that the token is attached only to a URL
the loader built itself for api.github.com, never to one the reader pasted.

`test-sample.py` covers the Sample Data dialog in every state, because the
sample files are deliberately not committed — they were taken out so as not to
publish them — and may come back later. A missing manifest means the same
thing as an empty one, *no samples published*, and says so rather than showing
`HTTP 404` as though the page were broken; with nothing listed the Load button
is disabled rather than answering "Select at least one file"; a name whose file
is not there yet is reported by name; and a manifest that is not JSON still
counts as a fault. The manifest is stubbed by replacing `window.fetch`, so the
test says nothing about what happens to be in `resources/data` when it runs.

    python3 test-sample.py

`test-tabs.py` covers the file tabs and the tooltip hanging off them. A tab's
tooltip is a div on the body, shown on the tab's `mouseenter` and hidden on its
`mouseleave` — and a tab that is *removed* never gets a `mouseleave`, so
closing a file left its tooltip on the screen. Hiding it when the strip is
rebuilt is not enough on its own, which is why this is a test rather than a
one-line change: closing a tab shuffles the ones after it leftwards, one slides
under the stationary pointer, Chrome fires `mouseenter` on it, and a tooltip
appears again at once for the next file along. So the tooltip now stays away
until the pointer really moves, as a `title` attribute does after a click, and
that is checked on both removal paths (an enabled file rebuilds the strip; a
disabled one drops the single element), on the last tab where nothing slides
under the pointer, and — the check that would catch a fix that simply broke the
tooltip — that it comes back on a real move. The pointer is driven with CDP
mouse events, not dispatched DOM events: the thing under test is what the
browser does with hover when the element beneath the pointer is replaced, which
a synthetic `MouseEvent` would not reproduce.

    python3 test-tabs.py

`test-axes.py` covers changing the chart's axes. First, a background overlay
across lin/log: every phase must be named correctly by its tooltip on a linear
chart, after clicking log, on a chart drawn on log, and back again, and the
rectangles must be redrawn for the new scale — left at t = 0 on a log axis they
dragged autorange out to 1e-9. The overlay's tooltip used to convert its bounds
once, at draw time, so after clicking log the whole chart named the first
phase. Second, the preset manager: its Current view row edits the chart
without saving anything and turns the dropdown to Custom, applying it
unchanged leaves the selection alone, editing the *selected* preset keeps it
selected and moves the chart, editing any other preset moves nothing, and
closing the dialog re-applies nothing. The file with the overlay is built in
the page with h5wasm, as `handoff-demo.html` does, so no data file is
committed for it. The presets are kept in the browser profile, which every
test here shares, and this test edits and deletes them. It puts back what it
found when it finishes; it used to leave "release" deleted, and the next
`characterise.py` then listed one preset fewer.

    python3 test-axes.py

`test-handoff.py` covers the in-memory handoff — another page opening a file
here without it ever being saved to disk. It drives both transports (the
postMessage handshake and a `?url=` blob link) and the guards that stop an
unwanted file getting in: a disallowed origin, bytes that are not HDF5, an
empty buffer, a name carrying path separators, and a page opened without the
`#handoff` hash, which must not listen at all. Run it directly:

    python3 test-handoff.py

It drives `handoff-demo.html`, which stands in for a page that produces HDF5
data. That page is also worth opening by hand — its three buttons show the
handoff into a new tab, into a blob URL, and into an iframe — and its source is
the copy-paste starting point for a real producer.

`test-constants.py` covers a multi-selection that mixes time series with
values that do not vary over time. The chart used to be drawn only when every
selected dataset was time-dependent, so a series selected together with the
parameter that drives it gave the parameter's histogram, or no chart at all.
Now one time-dependent dataset with a `/time` in its file is enough, and each
value that does not vary over time is drawn as a flat line across the chart.
A scalar or a one-element dataset is drawn at its value. A probabilistic column
is drawn at the mean of its realisations, and the CI, SEM and Show iteration
toggles work on it as they do on a series. Strings, tables and values that are
not numbers are not drawn. The test checks that on screen the flat lines span
exactly what the series do, on a linear axis and on a log one (which drops
t = 0). It builds its three files in the page with h5wasm.

It also clicks faster than the chart is drawn. Every chart builder sets the
chart up once `Plotly.newPlot` has finished, and a drawing that finishes after
the next click has replaced it sets up the chart that replaced it. That used to
add its relayout listeners again, until fifteen quick clicks left thirty and
Plotly warned of a leak. Now `onPlotEvent` in `rb-utils.js` replaces a
listener's earlier copy, and the test checks that fifteen quick clicks leave
what one click does.

    python3 test-constants.py

`test-tree.py` covers how the file-structure tree is laid out. Rows sit on
one grid: the toggle and its margin are a 20px column, a level indents by
exactly that, and a dataset keeps the column empty, so its icon lines up with
the folders beside it. Before, a dataset's icon sat 18px left of its own
folder's icon and a level indented only 6px, so data did not look as if it
were inside its folder. The test also checks that the arrow is ▶ closed and ▼
open (it was ▲ and ▶), that the folder icon opens with the arrow rather than
with selection, and that the row class `expanded` means selected and nothing
else: a search no longer puts it on every folder above a match, and closing
the selected folder no longer takes it off. The guide line along the selected
item's level, and along a selected group's members, is drawn in the accent
colour. It uses the committed fixture `sample-a.h5`.

    python3 test-tree.py

`test-log-range.py` covers auto range on a log y axis. The top is the decade at
or above the highest value drawn, and the bottom the decade at or below the
lowest, but never more than 12 decades below the top. It used to be Plotly's
padded range snapped outwards, so a series reaching 9.5e3 whose first value was
a 3e-30 left by round-off got an axis from 1e-32 to 1e6. The snap has to turn
Plotly's autorange off to set the range, so the axis counts as on auto range
while it still shows the range the snap chose. The test checks that the axis
follows a CI band on and off, and that Show Total refits rather than cutting
the total off at the old top. A zoom, a preset or the axes lock sets a range
that nothing then moves, and switching an auto axis to linear gives linear
auto range from zero. The file is built in the page with h5wasm.

    python3 test-log-range.py

`test-groups.py` covers several groups selected together. Ctrl-click (Cmd on
a Mac) on a group that draws a chart of its own adds it to the groups selected,
and again takes it out. The groups are drawn as one chart with a panel each,
top to bottom in the order picked, and each panel as that group's own chart
would be drawn, with the same colour and dash for a member. One time axis runs
under all of them, and the legend lists each line once and shows or hides it in
every panel. Panels in the same unit share a y axis, so lin/log, presets and
auto range act on all of them; a group in another unit has an axis of its own.
Show Max and Show Ratio would put a number per panel into one legend entry, so
they are not offered. A CI band goes in its line's panel. A folder that draws
no chart of its own is left to the plain click. While no files are combined,
**Same chart** draws the groups in one chart instead, the way intersect and
union draw files: the first group's lines as its own chart draws them, the
others' at half the width, named with the part of the path that tells them
apart, and Show Ratio across two groups as across two files. With files
combined it is not offered, ticked or not, since a thin line already means the
other file there. The file is built in the page with h5wasm.

    python3 test-groups.py

`test-lazy.py` covers the two things learnt from the HDF Group's myHDF5
(H5Web). First, compression: a dataset compressed with a filter h5wasm has no
decoder for (LZF, h5py's own, and likewise blosc, zstd, lz4, bitshuffle) used
to read as whatever was in memory, with no error on the page: the fixture's
first values came out as 8.8e-308, 0, 4.9e-313, 0. The decoder is now fetched
when a selection needs it, pinned by hash, both for a file in memory and for a
lazy one, and the test reads the fixture both ways. Second, lazy files: one
session -- the tree, a group's chart, a dataset's, a multi-selection, groups a
panel each, a search -- is run on a file opened lazily and on the same file in
memory, and must come out the same with nothing read before it was fetched.
The size rule (lazy from 256 MB, or `localStorage['kvot-rb-lazy']` set to
`always` or `never`) is checked on stand-ins.

    python3 test-lazy.py

## Nothing here needs a committed data file

`handoff-demo.html` used to fetch a sample HDF5 file to get valid bytes, and
`test-handoff.py` did the same in four places. When the samples were taken out
of the repository that fetch 404ed — which `fetch` does not treat as an error,
so the page posted an HTML error document as though it were a file, rb.html
refused it, and the check that waits for `rb-opened` waited for ever. The demo
now builds a small file with h5wasm instead, which is what a page that produces
HDF5 data would really do, and the test uses that same builder. Neither needs
anything from `resources/data`. `test-axes.py` builds its overlay file the
same way, and `test-constants.py` its three files.

The one exception is `fixtures/lzf.h5` (26 KB, made-up values), which h5wasm
cannot write: writing LZF needs the very plugin `test-lazy.py` checks is
fetched. `fixtures/make-lzf.py` makes it again with h5py.

## Known noise

The search step is not reproducible run to run. On identical code, two runs
differed in six fields:

    /search/Am*1/hidden              809 -> 758     (and matches 15 -> 14)
    /search/Am-241/hidden            441 -> 391     (and matches  8 ->  7)
    /search/biosphere/vault_A/hidden   1084 -> 1083
    /search/zzz-no-match/hidden     1520 -> 1519

Lazy tree loading races the search filter: the background expansion that pulls
matching paths into the DOM may or may not have finished when the counts are
taken, so hidden rows swing by about fifty and match counts by one. The swing
is not ±1, despite what this section used to claim.

Treat a diff confined to `/search/**` as inconclusive rather than clean — if it
matters, run the unchanged code twice and compare those two runs, which
separates the noise from a real change. A diff touching any field outside
`/search/**` is a real change.
