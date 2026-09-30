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

It exits 0 when all 91 checks pass and takes about a minute. With
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
- **Dark theme, a 390 px phone and reduced motion:** no horizontal scroll,
  and the key pad above the footer.

The page exposes `WK.inspect()` for this test: the current round, the
status of a fact, and a copy of the store. It is read-only.
