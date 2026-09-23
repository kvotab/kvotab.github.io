# Tests for zoterify.html

`zoterify.html` turns the plain-text citations in a Word document into Zotero
citations, as tracked changes in the document itself.

| file | what it checks | needs |
| --- | --- | --- |
| `test-parse.js` | the citation finder on 120 paragraphs written out by hand -- parenthetical, narrative, numbered, nested and bare citations, years and locators, the words kept around references, what is not a citation, and SKB's forms: report numbers, designations ("SSMFS 2008:37"), initials after a name -- then reference-list entries with their report numbers, abbreviated names, headings, and whole documents with SKB's two-part list; the user's list of abbreviated names -- how each line is read, and a listed name found in running text in bold or written as listed, not in a heading, a field's result or another citation, nor alone on its line | Node |
| `test-match.js` | Jaro–Winkler against Winkler's published values; the matcher on a small library: folding, co-authors and "et al.", acronyms, year tolerance, the reference list settling a choice, numbered and undated references, the three strictness levels; on a second, SKB library: report numbers and designations in items' numbers and titles, a number no item has, another regulation of the same year, an entry's number settling "SKB 2011", abbreviated names, initials; names from the user's list by report number (SKB's alone when the list says so), designation, item key or URI, author and year, or title words | Node |
| `test-zotero.js` | reading `zotero.sqlite`, the `-wal` replay (clean, torn, foreign, empty), URIs, CSL-JSON, collections and scopes | Node, `sql.js` |
| `test-ui.py` | the page in Chrome: loads the fixtures, analyses, decides, saves, then takes the saved `.docx` apart (see below) | Python `websockets`, Chrome |

    node resources/tests/zoterify/test-parse.js
    node resources/tests/zoterify/test-match.js
    (cd resources/tests/zoterify && npm install --no-save sql.js@1.14.2 && node test-zotero.js)
    python3 resources/tests/zoterify/test-ui.py

`test-ui.py` wants a server at the repository root and a headless Chrome, as
in `../rb/README.md`; `ZF_PORT` and `ZF_CDP` choose other ports, and
`ZF_KEEP=path` keeps the saved document for a look in Word. Each test exits
non-zero on a failure. `build-fixtures.py` rebuilds `fixtures/`.

## What test-ui.py asserts about the saved document

- Rejecting every change by the page's author gives back the text of every
  paragraph exactly, other people's revisions included; accepting them gives
  the same text, now the results of Zotero fields.
- Each field's JSON names the right item, with the page locator, the "see" or
  "cf." prefix, and `suppress-author` for a narrative citation, whose author
  stays as text; the reference list settles two papers of the same author
  and year; a choice made in the page is written.
- A citation inside someone else's tracked insertion gets its deletion inside
  that insertion, which is split around the new field; a citation inside a
  hyperlink splits the hyperlink; an EndNote field is deleted whole, its
  nested `EN.CITE.DATA` field with it.
- A footnote reference inside a citation, and a citation only partly
  resolved, are refused with their reasons.
- SKB report numbers are written as the items whose Report Number they
  are: "(SKB R-13-25, Section 4.2)" with its section, "SKB (R-19-01)" with
  "SKB" left as text, and "SKB R-19-01" in running text with only the
  number replaced.
- With the comment options on, each citation left as text gets a Word
  comment over exactly its text saying why -- the reference not found, the
  other one matched, the footnote reference in the way -- and a summary
  comment sits at the start of the document; comment ids are new, each with
  its range and reference; the text and the fields are as without comments.
  A document with no comments gets `comments.xml` with its relationship and
  content type, and a citation in a footnote gets its comment on the note's
  mark in the body text.
- Revision ids are unique, formatting revisions included, and above every id
  the document had; `w:trackRevisions` sits where the schema puts it;
  `people.xml` lists the author; the parts not edited are byte for byte the
  parts given. Saving without Track Changes writes the same fields with no
  revisions of its own.
- With "Data report: SKB R-19-01" listed, the name becomes a citation where
  it stands in running text -- not in bold but written as listed, and in
  bold -- and in "(Data report, Section 3)", while "the data report" in lower
  case stays prose. Each field keeps its text, run by run, with
  `dontUpdate` so that Zotero leaves it; the names are made bold, `w:b`
  going where the schema puts it among the run's properties; the summary
  counts them. A document's own "References with abbreviated names" offers
  the names not yet listed, and adds one without a report number by its
  title and year.

## Checked against real material, not committed

On 2026-09-22, with documents and a library that are not part of the site:

- **Accuracy.** Two reports already coded with Zotero give 504 citations of
  758 references whose true items are known from the fields themselves. With
  the fields opened up as plain text and the cited items added to a library
  of 22,554, the page found 757 of the 758 references; at the default
  setting it linked 721 to the right item unasked, offered the right item in
  a choice for 25 more, and linked six to another item. One is a paper by
  the same authors in the same year. Five are one report, which the
  document's reference list gives as SKB R-19-20 under a title different
  from the library's record of R-19-20 (same authors, same year): the page
  takes the record with that number. Lenient and strict gave 721 and 723.
  The one reference not found is written without parentheses in running
  text. Without report numbers the same run gives 698, 53 and 1, as before
  SKB's forms were added: report numbers turn 23 of the choices into right
  links and 5 into the R-19-20 record.
  For comparison, Identifyer for Zotero -- the desktop program the idea
  comes from -- run on the same paragraphs and library found no citation in
  89 of the 504 fields and linked 606 references rightly and 3 wrongly.

  Scoring needs care there: the items added from the fields are second
  records of works the library already holds, often with a shorter title
  and without a report number, so a match by report number lands on the
  library's record. Two records count as one work when they share the year
  and one title begins with the other; compared by exact title, those
  matches look wrong (17 instead of 6).
- **SKB's forms.** In three SKB safety-assessment reports (22,000
  paragraphs) the page found 212 citations by report number, 168 by
  abbreviated name and 66 by designation; with the list's own report
  numbers, 200 author-year references of one report were settled by number.
  Every designation stayed unmatched, correctly: the library holds no SSMFS.
  Figures that list the reports ("Initial state report / SKB TR-23-02") and
  the cover's own number are left alone.
- **Integrity.** Six reports of up to 59 MB and 8,320 existing revisions:
  rejecting or accepting the page's changes restored every one of 26,000
  paragraphs, and the Open XML SDK validator (`@xarsh/ooxml-validator`)
  found no error in any saved document that was not already in the
  original. That validator caught a real fault on the way -- a split run
  copying the id of a tracked formatting change -- which `test-ui.py` now
  covers.
- **Comments.** Every plain-text citation of two reports given a comment
  (21 and 465, and a summary): the text read back unchanged, every comment
  id unique with one range and one reference, and nothing new for the
  validator: only two errors in a chart the original already had. It rejected
  comments anchored inside footnotes -- the standard allows them, but the
  SDK does not resolve them -- so those now go on the note's mark.

To repeat the accuracy check: take a `.docx` coded with Zotero, analyse it
with `ZFDocx.analyse(pkg, { recode: { zotero: true } })` so the fields read
as text, keep each field's paragraph, result offsets and `citationItems`,
and score the matcher's result for every reference inside a field against
that field's items (an item with the same year and a title that is the
other's or begins it counts as the same).
