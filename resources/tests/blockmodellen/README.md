# Tests for blockmodellen.html (Blockmodellen)

Three suites. The first two run in Node and need nothing else:

    node resources/tests/blockmodellen/test-problems.js   # the problems, the model checks, the lessons
    node resources/tests/blockmodellen/test-game.js       # stars, days in a row, badges, what is kept

`test-problems.js` makes every template from 400 seeds, with and without the
pupil's own name (`BM_SEEDS` sets how many), and checks each problem against
itself: every number written into the model is what the pieces under its place
add up to, the question mark's place adds up to the answer, every line of
working is the arithmetic it shows and ends in the answer, the blocks the pupil
is asked to draw are the model's, and no answer stands in the text to be copied.

The third drives the page in headless Chrome, with real clicks and key presses:

    python3 resources/tests/serve.py 8863
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      --headless=new --remote-debugging-port=9363 --no-first-run \
      --user-data-dir=/tmp/bmtest --disable-gpu --mute-audio about:blank

    python3 resources/tests/blockmodellen/test-ui.py

It walks lessons step by step as a pupil would, makes a mistake at every step of
a problem to see what the page says back, uses the keyboard alone, practises,
changes the settings, reads a problem aloud through a stand-in for the browser's
voices, and looks at a phone upright (390 x 664) and on its side (844 x 340), the
dark theme and print. About two minutes.

Check the ports first (`lsof -nP -iTCP:8863 -sTCP:LISTEN`, and 9363): other
sessions use ports too. `BM_HTTP_PORT` and `BM_CDP_PORT` choose others, and
`BM_SHOTS=<folder>` saves screenshots. The page makes no sound, but start the
test Chrome with `--mute-audio` all the same.

After a change to `site.js`, run `resources/tests/site/test-chrome-nav-menu.py`
too; the full window is in `resources/tests/site/test-chrome-full-window.py`
(`FW_PAGES=blockmodellen`).

## What the tests cannot say

No test is twelve. Whether the explanations are clear, the hints help at the
right moment and the problems are worth doing is for a pupil, and her teacher,
to say. The page follows the eight steps Swedish schools teach; if a school
draws a model another way (a total brace above rather than at the side, say),
the drawing rules are at the top of `resources/js/blockmodellen-draw.js`.
