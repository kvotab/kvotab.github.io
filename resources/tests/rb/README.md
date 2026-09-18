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
