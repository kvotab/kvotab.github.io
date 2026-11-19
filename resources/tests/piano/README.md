# Tests for piano.html (Pianoskolan)

Four suites. The first three run in Node and need nothing else:

    node resources/tests/piano/test-songs.js    # the notes, the songs, the 49 lessons
    node resources/tests/piano/test-game.js     # right and wrong, stars, points, days in a row
    node resources/tests/piano/test-ear.js      # what the microphone hears

The fourth drives the page in headless Chrome:

    python3 -m http.server 8851 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      --headless=new --remote-debugging-port=9351 --no-first-run \
      --user-data-dir=/tmp/pntest --disable-gpu \
      --autoplay-policy=no-user-gesture-required about:blank

    python3 resources/tests/piano/test-ui.py

Check the ports first (`lsof -nP -iTCP:8851 -sTCP:LISTEN`, and 9351): other
sessions use ports too. `PN_HTTP_PORT` and `PN_CDP_PORT` choose others, and
`PN_SHOTS=<folder>` saves screenshots.

## What the tests can and cannot say about the microphone

No test has a piano. `synth.js` makes piano-like notes - stiff strings, the
hammer's thump, the damper, a phone's thin microphone, room noise, a piano out
of tune, strings not quite in unison, the pedal - and the listener is tested
on those, in Node a reading at a time and in the browser through the page's
real audio path (`PN.test.play`). That shows the logic holds; how it does on
a real piano in a real room is for somebody with a piano to say. If notes are
missed or doubled there, the numbers to look at are `EAR` in
`resources/js/piano-ear.js`, and a recording of the piano fed through
`test-ear.js`'s `listen()` will show which of them it is.

## The melodies

Each song's text in `piano-songs.js` was checked against published notation
(named in a comment beside it), and `test-songs.js` pins how each begins and
ends, so that a slip of the hand in a song's text is caught.
