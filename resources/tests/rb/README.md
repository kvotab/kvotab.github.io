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

Then, from this directory:

    python3 characterise.py before      # before the change
    # ... make the change ...
    python3 characterise.py after       # after the change
    python3 compare.py before.json after.json

`compare.py` prints `IDENTICAL` or lists every field that moved.

## What is covered

`characterise.py` walks fifteen steps: the initial DOM inventory, the expected
set of globals, loading two files, tree expansion, selecting a dataset and a
radionuclide group, the chart toggles, log/linear axes, ctrl-multi-select,
five search terms, all three tree modes, the dialogs, CSV and Excel export,
enabling/disabling/removing a file, and the rejection of malformed input.

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

## Nothing here needs a committed data file

`handoff-demo.html` used to fetch a sample HDF5 file to get valid bytes, and
`test-handoff.py` did the same in four places. When the samples were taken out
of the repository that fetch 404ed — which `fetch` does not treat as an error,
so the page posted an HTML error document as though it were a file, rb.html
refused it, and the check that waits for `rb-opened` waited for ever. The demo
now builds a small file with h5wasm instead, which is what a page that produces
HDF5 data would really do, and the test uses that same builder. Neither needs
anything from `resources/data`.

## Known noise

The search step is not reproducible run to run. On identical code, two runs
differed in six fields:

    /search/Am*1/hidden              809 -> 758     (and matches 15 -> 14)
    /search/Am-241/hidden            441 -> 391     (and matches  8 ->  7)
    /search/biosphere/1BLA/hidden   1084 -> 1083
    /search/zzz-no-match/hidden     1520 -> 1519

Lazy tree loading races the search filter: the background expansion that pulls
matching paths into the DOM may or may not have finished when the counts are
taken, so hidden rows swing by about fifty and match counts by one. The swing
is not ±1, despite what this section used to claim.

Treat a diff confined to `/search/**` as inconclusive rather than clean — if it
matters, run the unchanged code twice and compare those two runs, which
separates the noise from a real change. A diff touching any field outside
`/search/**` is a real change.
