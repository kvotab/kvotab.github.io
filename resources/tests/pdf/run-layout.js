/*
  Geometry tests for the PDF reconstruction.

  The fixture builder writes fixture-items.json from the same layout it draws
  the PDF from, so the item stream here is what pdf.js sees, and the expected
  paragraph texts are the ones the matching .docx yields. Reconstructing the
  paragraphs is therefore a test with a real oracle rather than a snapshot.

      python3 build-fixture-pair.py .
      node run-layout.js
*/
'use strict';

const fs = require('fs');
const path = require('path');
const SkbPdf = require('../../js/skb-pdf.js');

const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixture-items.json'), 'utf8'));
const failures = [];
const note = message => failures.push(message);

/* ── 1. the fixture document round-trips to the paragraphs the .docx has ── */

const normalise = value => String(value).replace(/\s+/g, ' ').trim();
const want = fixture.expected.map(entry => normalise(entry.text));

/*
  Both item granularities, because pdf.js gives either depending on the PDF:
  one item per word where the kerning changes, one per line where it does not.
  Testing only the word-level stream hid a defect that made every line of a
  reference list read as a wrap, merging the whole list into one paragraph.
*/
const runs = [
  ['word-level items', fixture.pages],
  ['line-level items', fixture.pagesByLine]
].map(([label, pages]) => {
  const result = SkbPdf.reconstructDocument(pages);
  const got = result.paragraphs.map(paragraph => normalise(paragraph.text));
  if (got.length !== want.length) {
    note(`${label}: paragraph count: expected ${want.length}, got ${got.length}`);
  }
  for (let index = 0; index < Math.max(got.length, want.length); index++) {
    if (got[index] !== want[index]) {
      note(`${label}: paragraph ${index}:\n    want: ${want[index] || '(none)'}\n    got:  ${got[index] || '(none)'}`);
    }
  }
  return { label, ...result };
});

/* The remaining checks read the word-level run, which carries the formatting. */
const { paragraphs, diagnostics } = runs[0];

/* ── 2. the running header and the page numbers are gone ── */

for (const run of runs) {
  if (run.paragraphs.some(paragraph => /SKB TR-25-01\s+Hydrogeological/.test(paragraph.text))) {
    note(`${run.label}: the running header survived into the text`);
  }
}
if (diagnostics.removedRunningLines < fixture.pages.length * 2) {
  note(`running lines removed: expected at least ${fixture.pages.length * 2}, got ${diagnostics.removedRunningLines}`);
}

/* ── 3. headings are recovered from size alone ── */

const styleOf = text => (paragraphs.find(paragraph => normalise(paragraph.text) === text) || {}).style;
for (const [text, wanted] of [
  ['Hydrogeological modelling of the repository', 'heading 1'],
  ['1 Introduction', 'heading 2'],
  ['2 Method', 'heading 2'],
  ['References', 'heading 2']
]) {
  if (styleOf(text) !== wanted) note(`style of "${text}": expected ${wanted}, got ${styleOf(text) || '(none)'}`);
}
const referenceEntry = paragraphs.find(paragraph => paragraph.text.startsWith('Andersson J'));
if (referenceEntry && referenceEntry.style) {
  note(`a reference entry was styled as a heading (${referenceEntry.style})`);
}

/* ── 4. italic and superscript survive as spans ── */

const isotope = paragraphs.find(paragraph => paragraph.text.startsWith('Measurements of'));
if (!isotope) {
  note('the paragraph with the superscript was not found');
} else {
  const supAt = isotope.text.indexOf('14');
  const sup = isotope.formatSpans.find(span => span.start === supAt && span.sup);
  if (!sup) note('the superscript 14 in "14C" was not recovered');
  const italicAt = isotope.text.indexOf('Desulfovibrio');
  const italic = isotope.formatSpans.filter(span => span.start >= italicAt && span.italic);
  if (!italic.length) note('the italic species name was not recovered');
  const strayItalic = isotope.formatSpans.filter(span => span.italic && span.end <= italicAt);
  if (strayItalic.length) note(`${strayItalic.length} span(s) outside the italic run were marked italic`);
}

/* ── 5. hyphens at line breaks ── */

const hyphenated = paragraphs.find(paragraph => paragraph.text.startsWith('Waste from the'));
if (!hyphenated) {
  note('the hyphenation paragraph was not found');
} else {
  if (!/\bradioactive\b/.test(hyphenated.text)) note('a break hyphen was not removed: "radioactive" is missing');
  if (!/\bSKB-rapport\b/.test(hyphenated.text)) note('a real compound hyphen was removed: "SKB-rapport" is missing');
}

/* ── 6. the break-hyphen decision, directly ── */

for (const [before, after, keep] of [
  ['radio-', 'active particles', false],
  ['hydro-', 'geological model', false],
  ['SKB-', 'rapport series', true],
  ['TR-', '14-09 was cited', true],
  ['cost-', 'Benefit was assessed', true],
  ['a-', 'symmetric shape', true]
]) {
  const kept = SkbPdf._internal.shouldKeepHyphen(before, after);
  if (kept !== keep) {
    note(`hyphen in "${before}|${after}": expected ${keep ? 'kept' : 'removed'}, got ${kept ? 'kept' : 'removed'}`);
  }
}

/* ── 7. non-breaking spaces are folded, so no rule can read one as evidence ── */

if (SkbPdf.normalisePdfText('12 °C').includes(' ')) {
  note('U+00A0 survived normalisation, which would let the hard-space rules pass on a PDF');
}
if (SkbPdf.PDF_CAPABILITIES['space-characters'] !== false) {
  note('PDF_CAPABILITIES must declare space-characters unavailable');
}

/* ── 8. two columns are read in turn, not interleaved ── */

/*
  The columns share a baseline grid, as they do in any real two-column page,
  so the reconstruction has to find the gutter before grouping the items into
  lines - afterwards the two columns are already one line and unrecoverable.
*/
const columnPage = { pageNumber: 1, width: 595, height: 842, items: [] };
for (let row = 0; row < 14; row++) {
  const y = 700 - row * 13;
  for (let word = 0; word < 3; word++) {
    columnPage.items.push({ str: `left${row}w${word}`, x: 60 + word * 60, y, width: 55, fontSize: 10 });
    columnPage.items.push({ str: `right${row}w${word}`, x: 330 + word * 60, y, width: 55, fontSize: 10 });
  }
}
const columnResult = SkbPdf.reconstructDocument([columnPage]);
const columnText = columnResult.paragraphs.map(paragraph => paragraph.text).join(' | ');
if (columnResult.diagnostics.multiColumnPages !== 1) {
  note('the gutter on a two-column page was not found');
}
if (/left0w0 right0w0/.test(columnText) || !/left0w2 left1w0/.test(columnText)) {
  note(`two-column page read out of order: ${columnText.slice(0, 160)}`);
}
if (columnText.indexOf('right0w0') < columnText.indexOf('left13w0')) {
  note('the right column was read before the left column was finished');
}

/* ── 9. a single-column page must not be split into columns ── */

const singlePage = { pageNumber: 1, width: 595, height: 842, items: [] };
for (let row = 0; row < 10; row++) {
  singlePage.items.push({ str: `word${row} continues to the right margin here`, x: 70, y: 700 - row * 13, width: 440, fontSize: 10 });
}
if (SkbPdf.reconstructDocument([singlePage]).diagnostics.multiColumnPages !== 0) {
  note('a single-column page was split into columns');
}

/* ── report ── */

for (const run of runs) {
  console.log(`${run.label.padEnd(17)} pages ${run.diagnostics.pageCount}  `
    + `lines ${String(run.diagnostics.lineCount).padStart(3)}  `
    + `paragraphs ${run.diagnostics.paragraphCount}  body ${run.diagnostics.bodySize}pt  `
    + `stripped ${run.diagnostics.removedRunningLines}  headings ${run.diagnostics.headingParagraphs}`);
}

if (failures.length) {
  console.error(`\n${failures.length} failure(s):`);
  for (const failure of failures) console.error('  - ' + failure);
  process.exit(1);
}
console.log(`\nPDF layout tests passed (${want.length} paragraphs reconstructed to match the .docx oracle).`);
