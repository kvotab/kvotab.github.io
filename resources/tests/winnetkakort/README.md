# Tests for winnetkakort.html

Two files: the card sets on their own in Node, and the page in headless Chrome.

## test-sets.js

    node resources/tests/winnetkakort/test-sets.js

No page and no browser; exits 0 when all 47 checks pass. It checks that:

- **The piles hold what their names say.** Lilla plus is the 45 sums of 1–9 up
  to 10 and stora plus the 36 from 11. Lilla and stora minus mirror them. A
  table is ten cards. No pile holds a fact twice.
- **Every answer is right.** Every operation is recomputed. The text cards
  (dubbelt, procent, bråk, kvadratrötter) are spot-checked. The tiopotenser
  come out exact in spite of floating point (0,05 · 100 is 5, not
  5.000000000000001).
- **The question forms** put the blank where they say, and "Saknat tal" never
  asks for the result.
- **The progress grids find every cell:** plus and minus 9 × 9, gånger
  10 × 10, delat 9 × 10.
- **Typed answers are read as a Swedish child writes them:** decimal comma,
  hyphen, dash or true minus sign, spaces in 4 500, a trailing %.
- **No hint gives its answer away.** A hint may repeat a number the question
  shows (5² = ? may say 5 · 5), but never the hidden answer. This found real
  cases: 100 − 90 said "10 tiotal", 2 · 5 said "· 10" and 95 + ? = 100 said
  "+ 5". Add a pile and this check covers its hints too.

## test-ui.py

The page played the way a child plays it. Answers are typed and Enter,
Space and the arrow keys are pressed as trusted CDP key events, not set from
script. Serve the repository and start Chrome first. The ports are 8847 and
9347 unless `WK_HTTP_PORT` and `WK_CDP_PORT` say otherwise. Check them with
`lsof -nP -iTCP:<port> -sTCP:LISTEN` first, because other sessions use ports
too:

    python3 -m http.server 8847 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      --headless=new --remote-debugging-port=9347 --no-first-run \
      --user-data-dir=/tmp/wktest --disable-gpu about:blank

    python3 resources/tests/winnetkakort/test-ui.py

It exits 0 when all 176 checks pass and takes about two and a half minutes. With
`WK_SHOTS=<folder>` it also saves screenshots and the printed cards as
`cards.pdf`.

What it plays:

- **A round with every answer right:** ten cards, the record kept, each fact
  stored, the tile and the times grid updated.
- **A wrong answer:** the card waits, with Nästa kort focused. It shows up in
  "Mina svåra kort", becomes "på gång" after one right answer and "kan" after
  two.
- **"Öva på de 2 korten igen"**, the Öva mer pile repeated until it is empty.
- **The hint** and a slow answer both send a right answer to Öva mer, and
  with no time limit there is no timer bar.
- **Whole piles typed:** bråk and procent with a decimal comma, negative
  numbers with a hyphen and with the true minus sign, and the tiopotenser.
- **A large pile starts with the facts missed before** (seeded in storage).
- **"Saknat tal"** and the × ÷ signs.
- **Vänd kortet:** Space turns the card. →, ←, K and a tap on a pile sort it,
  and Kan is off once the hint has been used.
- **The key pad,** with `inputmode="none"` so no system keyboard covers it.
- **Settings survive a reload.**
- **People:** add, switch, remove after asking twice. Progress is reset
  after asking twice.
- **Printing:** 21 cards give two sheets, each with a front and a mirrored
  back. The print style shows only the cards, and `Page.printToPDF` gives
  four A4 pages.
- **Storage that is not ours:** broken JSON, a markup name (shown as text,
  cut to 30 characters), unknown settings, a `__proto__` fact key.
- **The full window:** the button hides the site's header, footer and menu,
  and the page then fills the window. The page bar shows the kvot mark
  (linking to the home page), the title and a theme switch that works like
  the footer's. A reload keeps the full window, applied in the page's head
  before first paint. The button in the practice bar brings the chrome back
  without stopping the round.
- **Phones never show the header and footer,** and have no button. The
  sizes are what a page really gets once the browser's own bars have taken
  their share, all with touch emulation so the key pad appears by itself:
  - an iPhone 13 in Safari, 390 × 664 upright and 844 × 340 on its side;
  - an iPhone SE, 375 × 548 upright and 667 × 325 on its side;
  - a small Android phone in Chrome, 360 × 560.

  At each size:
  - no tap can zoom the page: its fields are 16 px (an iPhone zooms into
    anything smaller and stays zoomed), and a double tap does nothing;
  - the page itself cannot move: the document is pinned, and the content
    scrolls up and down only, without carrying on into the page;
  - the card and the key pad fit with nothing to scroll either way, the
    card at 3:2 and at least 150 px tall, its sum on one line;
  - with the hint open all of that still holds, and the card is at most
    30 % smaller.

  A tablet (820 × 1180) keeps the chrome and the button.
- **The cards under the one asked:** two, of opaque paper with the pile's
  band (what shows while the card turns), their band level with the card's.
- **Dark theme and reduced motion.**
- **Sound effects** (resources/js/winnetkakort-sound.js, made with Web
  Audio; there are no sound files):
  - Every sound is rendered silently offline and measured, so nobody has to
    listen. Each must be audible without clipping (peak between 0.08 and
    0.9) and short. Wrong must be gentler than right, the card's own sounds
    and the hint quieter than the chime, and the fanfares must grow from
    done to all-in-Kan to record.
  - Sounds are off at first, and no audio exists until they are on. They
    are switched on with a real mouse click (`page.click`, which counts as a
    user gesture where `element.click()` would not). Switching on plays the
    chime.
  - A right answer swishes, chimes and taps. A wrong one says uh-oh, the
    hint bubbles, and right with the hint plays the softer note. A finished
    pile plays its fanfare. In Vänd kortet the swish, chime and tap come on
    the key presses.
  - After a reload they are still on, and wait for the first tap. The
    setting switches them off, and off is silent. On a phone the loudspeaker
    stays in the practice bar.

The page exposes `WK.inspect()` for this test: the current round, the
status of a fact, and a copy of the store. It is read-only.
