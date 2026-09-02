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

## Known noise

Two fields vary by ±1 between runs on identical code:

    /search/Am*1/hidden
    /search/zzz-no-match/hidden

Lazy tree loading races the search filter, so the count of hidden rows can be
off by one. Treat a diff limited to those two fields, by one, as clean. Anything
else is a real change.
