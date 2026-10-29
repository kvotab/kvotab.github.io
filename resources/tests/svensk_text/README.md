# Tests for svensk_text.html

Two files: the subtitle work (resources/js/svensk_text-core.js) on its own in
Node, and the page in headless Chrome. Neither needs a translator: the core
test uses what translate.google.com returned for the sample scene
(`SAMPLE_GOOGLE` in the core), and the page test replaces Chrome's built-in
translator with a stand-in that answers "SV " and the English.

## test-core.js

    node resources/tests/svensk_text/test-core.js

No page and no browser; under a second, and exits 0 when all 112 checks pass.
It checks that:

- **Files are read** as .srt or .vtt, in UTF-8, UTF-16 or Windows-1252, with
  CRLF, a BOM, a missing blank line, cue settings and coordinates; a
  position tag and italics over a whole subtitle are kept aside and put back.
- **What subtitles for the deaf carry is left out:** [sounds], (SIGHS) and
  ALL-CAPS speaker labels, inside italics and dialogue too, but not a clock
  time or a lone "I:". A sound description that is kept is a sentence of its
  own, even in the middle of one, and with them kept every sentence of the
  sample is still in Google's recording.
- **The English is made ready:** hesitations, stutters and the fillers
  "you know", "I mean", "like" and "well" out, and nothing that only looks
  like them ("Do you know what I mean?", "Her umbrella").
- **Sentences are joined** over subtitles when one goes on into the next (a
  comma, a trailing "...", a lower-case start), and not across a full stop,
  a three-second pause or a new speaker; a name on its own ("Will!",
  "Dr. Patel?") is never sent to the translator.
- **The Swedish is put back:** one sentence divided over its subtitles where
  Google itself breaks it, a dash at the break dropped, lines broken
  bottom-heavy within 42 characters, never after a preposition or between a
  number and what it counts; the phrasebook; and the mending of the usual
  slips (an apology as "Förlåt", eventually, billion, miles to km in figures
  or in words, "Hej killar", "min Gud", numbers two to ten in words but not
  times, dates or thousands, mr and dr).
- **Every subtitle is checked:** reading speed with and without the extra
  time in the pause after it, which stops short of the next subtitle; a line
  over 42; English left as it was; an open italics tag; a lost number; a
  wrong clock time, and a right one as digits or as Swedish says it
  ("halv fyra" for 3:30).
- **The sample end to end:** 23 subtitles, the seven Google left too long
  marked, and the .srt written in UTF-8 with a BOM or in Windows-1252.

## test-ui.py

The page in Chrome. Serve the repository and start Chrome first. The ports
are 8851 and 9351 unless `ST_HTTP_PORT` and `ST_CDP_PORT` say otherwise.
Check them with `lsof -nP -iTCP:<port> -sTCP:LISTEN` first, because other
sessions use ports too:

    python3 -m http.server 8851 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      --headless=new --remote-debugging-port=9351 --no-first-run \
      --user-data-dir=/tmp/sttest --disable-gpu about:blank

    python3 resources/tests/svensk_text/test-ui.py

About 6 s; 56 checks. It needs the `websockets` package. It checks that the
page loads in the site's header, menu and footer without a script error; that
the sample shows Google's Swedish with seven subtitles to look at; that in
the sample, Keep and Leave out and the setting for sound descriptions work
at once from Google's recording, with no translator; that a live run asks
for the translator's model on the click, sends whole sentences twelve to a
request with the fillers already gone, keeps the phrasebook's line, holds the
setting for sound descriptions until it ends, and translates a subtitle kept
while it ran after its own sentences; that an .srt from disk is translated,
the list up to date when the run ends, and saved as `Test.Film.sv.srt` in
UTF-8 with a BOM and Windows line ends; that the work survives a reload; that
after the translation Keep translates a sound description at once, Leave out
leaves it out and Keep brings its Swedish back, and either choice in the
setting translates only the subtitles it changes; that the theme switch
redraws without an error; that a browser without the translator gets the open
model chosen for it; and that the front page has the card. An error a
button's handler throws counts as a script error: the site's dispatcher
catches it and only logs it.

What it cannot check is Google's translator itself: a headless Chrome cannot
fetch its model. That was checked by hand in Chrome 156 on macOS.
