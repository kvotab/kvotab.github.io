# PDF reconstruction tests

`skbref.html` accepts a report as `.docx` or as `.pdf`. The `.docx` states its
own structure — `<w:p>` is a paragraph, `w:pStyle` names the style, `<w:i>` is
italic — while a PDF states none of it and every structural fact has to be
rebuilt from geometry by `resources/js/skb-pdf.js`.

That makes the `.docx` a real oracle rather than a snapshot: build one document
in both formats, and any difference in the two reports is a defect in the PDF
reconstruction.

## Building the fixtures

    python3 build-fixture-pair.py .

writes `fixture-report.docx`, `fixture-report.pdf` and `fixture-items.json`
from one source, `BLOCKS`, defined once at the top of the script. All three are
generated and none is committed.

The PDF is written by hand rather than with a library, because the fixture's
value is in controlling the geometry exactly — indents, leading and line breaks
are the input under test. It is built to be hostile on purpose:

- a running header and a page number on every page, which have to be stripped,
  because they are not in the `.docx` and would otherwise appear as extra text;
- paragraphs that wrap across lines and across pages;
- a reference list set with a hanging indent, entries wrapping to two lines;
- a line broken on a typesetter's hyphen (`radio-active`) and one broken on a
  real compound hyphen (`SKB-rapport`), which have to be rejoined differently;
- an italic run and a superscript, neither of which is a text attribute in a
  PDF;
- headings distinguished from body text only by their type size;
- ordinary spaces where the guides require non-breaking ones.

## run-layout.js

    node run-layout.js

Reconstructs the paragraphs from `fixture-items.json` and requires them to
match, one for one, the paragraphs the `.docx` yields. No browser and no pdf.js
are involved: the module takes plain numbers in and gives paragraphs out.

The fixture is replayed at **both item granularities**, because pdf.js splits a
line into items wherever the kerning changes — for some PDFs that is once per
word, for others not at all. Testing only the word-level stream hid a defect
that made every line of the reference list read as a wrapped line, merging the
whole list into a single paragraph. `firstWordWidth` exists because of it.

Also checked here: header and page-number removal, heading inference, the
italic and superscript spans, the break-hyphen decision, non-breaking-space
folding, and two-column reading order — including that a single-column page is
*not* split.

## Two things the geometry tests cannot see

`test-chrome-pdf.py` in `../site/` covers the rest, in a real browser with real
pdf.js:

- **the reports agree.** Both fixtures go through `handleFile` and the
  reference keys, cited entries, orphans, uncited entries and duplicates must
  match.
- **the capability gating works.** The fixture writes ordinary spaces where the
  guides require hard ones, so the `.docx` run has to report all three hard-space
  violations and the PDF run has to report none — a PDF records a position, not
  a character, and cannot tell U+00A0 from U+0020. The test fails if *either*
  half of that stops holding, so it cannot pass while proving nothing.
- **fonts resolve.** Italic and bold come from the embedded fonts, which pdf.js
  publishes only while building an operator list, never while extracting text.
  `loadPdfPageFonts` requests one per page and throws it away; without it every
  italic run reads as upright and the rule wanting quantity symbols italic
  reports each correct one as an error. This is the only place that path runs.
