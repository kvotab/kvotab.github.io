# CSL style tests

The two styles in [`resources/csl/`](../../csl/) claim to implement SKBdoc
1215757, *Angivande av referenser i publika rapporter*. These tests render
references through them with the same engine Zotero uses and compare the output
with the strings the instruction itself prints.

Nothing here is a judgement call: every expected string is copied from the
instruction. A rule that disagrees with it is a defect in the style.

## Running

    npm install citeproc
    ./fetch-locales.sh
    node run-guide.js      # every reference example in the instruction
    node run-rules.js      # the rules its examples do not exercise

`run-guide.js` exits non-zero on a mismatch. Cases carrying a
`knownLimitation` string are reported separately: those are things CSL cannot
express, recorded in the KNOWN LIMITATIONS block at the top of each style.

## What is covered

`cases-guide-a.js` and `cases-guide-b.js` hold all 43 reference examples from
chapter 4, each with the item as the style's own header tells an author to
enter it in Zotero, the reference-list string the instruction prints, and the
in-text citation.

`run-rules.js` covers what the examples do not:

- page locators (`p 69`, `pp 120–132`, Swedish `s 65–67`)
- several sources in one parenthesis, separated by commas
- several works by one author (`Brown 2002, 2004`) and in one year
  (`Lindroos 1993a, b`)
- `et al.` from three authors in the text, all names in the list
- the three-tier reference-list order of chapter 5, using the guide's own
  nine-entry example
- the Swedish forms of chapter 6: `och`, `s`, `red`, `I`, `u å`,
  `Tillgänglig:`, `uppl`
- the author, the year **and the full stop after it** in bold (section 3.2)
- the Swedish alphabet in both styles: Ü as Y, and Å, Ä/Æ, Ö/Ø after Z
  (chapter 5)
- language notes only for sources in languages other than English
  (section 3.2), in the report's language (chapter 6)
- no term, quotation mark or month from another locale in the output, and a
  space before AD and BC (1469987, section 6.2.2)

## Adding a case

Copy the reference out of the instruction verbatim into `expected`, and enter
the item the way the style's header instructs. If the two disagree, decide
which is wrong before changing either.
