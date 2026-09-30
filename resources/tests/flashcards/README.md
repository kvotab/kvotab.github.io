# Tests for flashcards.html

Two files: the words and the answer checking on their own in Node, and the
page in headless Chrome. The page is built on `winnetkakort.css`, so a change
there should be run against `../winnetkakort/test-ui.py` as well.

## test-words.js

    node resources/tests/flashcards/test-words.js

No page and no browser; exits 0 when all 71 checks pass. It checks that:

- **The themes hold what they should.** There are five groups in each
  language, and the grammar belongs to its language: irregular verbs for
  English, *el/la* and verb forms for Spanish. No card key appears twice in
  a pile. A word in two piles, like 20 in *Siffror* and *Tal*, is one card.
  Spanish nouns carry their article, and days and months don't.
- **The numbers are written right,** in all three languages (veintidós,
  treinta y uno, tjugoett).
- **An answer is judged the way a teacher would.**
  - Case, punctuation and apostrophes don't matter. "a", "the", "to", "en",
    "ett" and "att" may come along. Every alternative counts, and so does
    each side of " / ".
  - "monday" is right, with a note on how Monday is written.
  - One letter off (a swap counts as one) is *almost*, and doesn't count.
  - å, ä and ö are letters, not accents.
  - A missing Spanish accent or article is right by default, with a note,
    unless the settings require it. A wrong article is wrong.
  - A phrase with a gap ("jag heter …") takes the child's own name.
- **The grammar cards** accept the forms however they are typed ("went,
  gone", "go went gone", "was/were been"). *El/la* accepts the article
  alone or with its noun, and a verb form may come with its pronoun.
- **Hints and choices.** No hint is the whole answer. In every pile,
  exactly one of the four options is right.
- **Lists of one's own are read the way teachers write them.** Any of
  `=`, `-`, `–`, `;`, `:` or a tab separates the words, and a line without
  a pair is reported with its number. A shared link carries the list (åäö
  and ñ included) and nothing else: a hostile link is cut down to text of a
  sane size.
- **Leitner's boxes.** A word right the first time is known (box 3), a
  wrong one goes back to box 1. Box 2 is due again after two days, box 3
  after a week.

## test-ui.py

The page played the way a child plays it: answers typed and keys pressed as
trusted CDP events. Speech is a stub installed before the page loads, with an
English and a Spanish voice (or none), so what is read out can be checked on
any machine. Serve the repository and start Chrome first, by default on ports
8848 and 9348 (`FC_HTTP_PORT` and `FC_CDP_PORT` for others). Check the ports
with `lsof -nP -iTCP:<port> -sTCP:LISTEN` first, because other sessions use
ports too:

    python3 -m http.server 8848 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      --headless=new --remote-debugging-port=9348 --no-first-run \
      --user-data-dir=/tmp/fctest --disable-gpu about:blank

    python3 resources/tests/flashcards/test-ui.py

It exits 0 when all 134 checks pass, in about three minutes. With
`FC_SHOTS=<folder>` it saves screenshots and the printed cards as
`cards.pdf`.

What it plays:

- **A typed round, all right.** The word is read out once the card has
  turned. A Swedish front has no loudspeaker, since it would say the answer.
- **Almost, wrong and the Öva mer pile.** The missed words appear in *Att
  repetera*. Once answered right they leave it, and they come back two days
  later.
- **"monday" in lower case**, the other direction (whose front loudspeaker
  says the front word only), and mixed directions.
- **Choosing among four.** The number keys choose, and the right and
  wrong choices are both marked.
- **Turning the card**, with Space, → and ←.
- **Listening:** the word is read out and there's nothing to read on the
  card.
- **The hint.**
- **Irregular verbs.**
- **Spanish.** Accent keys insert at the cursor and keep the focus. An
  article may be left out, then may not. *El/la* is a choice between two.
  Verb forms can be typed with or without the pronoun. No front loudspeaker
  says the answer ("vosotros sois", the *el* of "el perro").
- **A list of one's own.** The editor opens under *Mina glosor*. A line
  error is reported. A saved list shares its progress with the themes.
  *Dela* gives a link and *Ändra* brings the text back.
- **The link opened by somebody else.** It is offered and nothing is added
  unasked. Accepting clears the address. A hostile list stays text, and a
  link without a list is dropped.
- **Titta först and printing.** Printing gives 27 cards on two sheets, with
  the backs mirrored and four A4 pages in the PDF.
- **No voice:** no listening mode, a note on why, and no loudspeakers.
- **Sound effects.** These are Winnetkakort's, from `winnetkakort-sound.js`.
  Their levels are measured in `../winnetkakort/test-ui.py`.
  - They are off at first, and no audio exists until they are on. The
    loudspeaker is switched on with a real mouse click (`page.click`).
  - Right swishes and chimes, then taps as the card lands. *Nästan* (a
    letter off) and right with the hint get the softer note, and a wrong
    word gets the uh-oh. The hint bubbles.
  - A pile with words left to practise ends with the short fanfare, and all
    in Kan with the bright one. Choosing among four and turning the card
    make the same sounds.
  - With the sounds on, the word is read out at least 600 ms after the
    answer, once the chime has rung. With them off, it comes as the card
    turns.
  - Sounds are per person: a new person starts with them off, and switching
    back turns them on again.
  - After a reload they wait for the first tap. The setting switches them
    off, and off is silent.
- **The full window.**
- **Phones.** An iPhone 13 in Safari at 390 × 664 and 844 × 340, an iPhone
  SE at 375 × 548 and 667 × 325, and a small Android phone at 360 × 560. At
  each size:
  - there is no site chrome, no field under 16 px, and the page is pinned;
  - typing, choosing, and Spanish with its letters all fit with nothing to
    scroll;
  - with the keyboard up (`--fc-vh` set as the page sets it), the word and
    the answer stay above the keyboard.
- **Storage that isn't ours**, and the dark theme.

The page exposes `FC.inspect()` for this test: the current round, a card's
status and box, and a copy of the store. It is read-only.
