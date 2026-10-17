# Tests for flashcards.html

Four files: the words and the answer checking on their own in Node, and the
page in headless Chrome; and the same two for reading a list off a picture. The page is built on `winnetkakort.css`, so a change
there should be run against `../winnetkakort/test-ui.py` as well. Its looks
(*Utseenden*) are Winnetkakort's, and `../winnetkakort/test-looks.py` tests
them on both pages.

## test-words.js

    node resources/tests/flashcards/test-words.js

No page and no browser; exits 0 when all 84 checks pass. It checks that:

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
  a pair is reported with its number. The numbers of a numbered list
  (`1 `, `1.`, `1)`, `(1)`, `1:`, a number and a tab) are no part of the
  words, but a number that is the word stays (`20 = twenty`), and numbers
  that do not count one by one are words too. An assignment pasted from
  the school's app loses its heading (a pair by its colon), the line that
  tells what to do and the numbers, and the week in the heading
  (`v 42`, `vecka 7`) names the list; above a list without numbers, a
  short line that is no pair stays (a pair with its separator missing). A
  list written the other way round is turned line by line, and nothing in
  the new first word reads as a separator. A shared link carries the list (åäö
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

It exits 0 when all 139 checks pass, in about a minute. With
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
- **A list pasted in**: an assignment comes without its heading, its
  instructions and its numbers, named from the week in the heading; a list
  with English first is turned Swedish first, the page says so, and *Byt
  plats på orden* turns it back. Other text is pasted as it is.
- **The settings**: *Utseende* comes last, so a phone need not scroll past
  twenty looks to reach the others.
- **Its own icon** (scripts/gen-flashcards-icon.py): the SVG and a 32 px
  PNG for the tab, and 180 x 180 for an iPhone's home screen, which
  suggests the name Glosor.
- **Storage that isn't ours**, and the dark theme.

The page exposes `FC.inspect()` for this test: the current round, a card's
status and box, and a copy of the store. It is read-only.

## test-photo.js

    node resources/tests/flashcards/test-photo.js

Words from a picture without a browser: how `flashcards-photo.js` puts the
words Tesseract found back into the rows and columns of a list. The words
are boxes made up for each case, as wide and tall as their printed letters
would be. Exits 0 when all 57 checks pass. It checks that:

- **Rows and columns come back.** Two columns either way round, columns
  that Tesseract read apart, a row that slopes, and a long word that leaves
  only a space before its translation (split where the other rows show the
  column starts).
- **Separators, numbers and headings.** `–`, `=` and `:` separate, spaced
  or stuck to a word, and a hyphen inside a word does not. Numbering goes,
  bare numbers only when most rows have one, and a number may be a word
  (`20 = twenty`). A heading in larger writing is no pair, and "vecka 7" or
  "v. 42" names the list. A heading in the list's own writing cannot be told
  from a pair - the one known limit.
- **What is not a word.** Table lines read as `|`, pronunciation in `[ ]`,
  a speck read as a letter away from the columns, and a paragraph or page
  number beside a glossary. A word of one letter (`ö = island`) stays.
- **Two lists side by side**, left one first; and **holes** - a word
  without its pair, rows missing - which make the page look again.
- **A screenshot of the school's app**: in a numbered list, what comes
  before 1 (the phone's clock and battery) and a number that does not
  belong ("114 ord · 1587 tecken" under a list of four) make no pairs; a
  number read stuck to its word ("2imonerad") is still the number; a time
  is no side of a pair, though a number may be.
- **Which side is Swedish:** å, ä and ö, the articles, the page's own
  words, Spanish accents; column headings decide when there are some; and
  with two readings, the reading that was surer of a column.
- **Two readings.** For Spanish, Swedish alone and Spanish alone. For
  English, both languages and then Swedish alone, which only puts back
  the dots and rings ("6sregnade" → "ösregnade") and changes no other
  letter ("blixt" stays, though the Swedish reading has "blid"). A word of
  the second reading goes with the nearest word of the first, not by its
  box, which can reach over the next word.
- **Into the editor:** lines the editor reads back as the same pairs.
- **The picture:** the slope of lines of writing is found within a quarter
  of a degree; light from one side and the sharp edge of a shadow leave the
  paper white and the writing dark. Light writing on dark is told by what
  stands out from the ground, not by how dark the whole picture is: a
  dark-mode screenshot and a photo of a dark screen against a light wall
  are light writing, a small sheet on a dark desk is not.
- **The reader's files** are pinned to versions, with a SHA-384 and a size,
  from jsDelivr only.

## test-photo-ui.py

    python3 resources/tests/flashcards/test-photo-ui.py

The page reading pictures, with the same server and Chrome as test-ui.py
(`FC_HTTP_PORT`, `FC_CDP_PORT`). It needs the network: the page fetches
the reader from jsDelivr. Exits 0 when all 60 checks pass, in about a
minute and a half. With `FC_SHOTS=<folder>` it saves screenshots and the pictures.

The pictures are made by the test: thirteen sheets laid out the ways
teachers lay out a list (a table with headings, two columns English first,
`dog – hund` under a paragraph, a numbered list, Spanish in columns and in a
table, a table sloping 6.5°, two lists side by side, a sheet photographed
on its side, a dark-mode screenshot, a textbook page with a glossary box),
photographed by Chrome as a phone would - in perspective, with a shadow,
blur, noise and JPEG at 3000 × 4000 - or saved as screenshots. Two copy
what pupils really send: a phone's screenshot of a school app in dark mode
(clock, battery, heading, a numbered `to whisper - att viska` list in a
light typeface, the app's word count), and a photo of a computer screen in
dark mode against a light wall, with glare and a dark patch. Nothing of
them is kept in the repository. The words on them are written for the test.
It checks that:

- **A photo gives the list.** Every pair of every sheet, Swedish first,
  with at most one word misread per sheet (none are, as measured). The page
  says what it is doing, fetches the reader the first time only, names the
  list from a heading, and does not offer headings as missed words.
- **Nothing goes anywhere but jsDelivr**, for the pinned files only, and
  nothing is sent: every request is a GET without a body. A file that does
  not match its SHA-384 is not run (no worker is started), and without the
  network the page says so.
- **The buttons.** *Byt plats på orden* (under the box, for any list)
  turns every pair round and back,
  and a reading after it replaces the turned lines rather than adding to
  them. A
  second page adds to the first and keeps the name. A sheet on its side is
  turned by the reader itself; *Vrid bilden* turns it a quarter further, as
  asked, and four quarters round give the words back once. *Läs igen* in
  Spanish replaces the English reading. *Avbryt läsningen* stops a reading, and
  closing the editor lets the reader go.
- **Lines that made no pair** are offered, short ones only, and a tap adds
  one to the box, where the editor asks for its pair.
- **Pasted and dropped.** A pasted picture is read, a paste with text in it
  is left as text; a picture dropped on the editor is read, a text file is
  not.
- **A phone**: nothing to scroll sideways, the status above the picture, a
  16 px field, and the picture larger at a tap.
- **Without WebAssembly** there is no photo button, and the editor works as
  before.
