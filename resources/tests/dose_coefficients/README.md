# Tests for dose_coefficients.html

| File | What it proves | Needs |
| --- | --- | --- |
| `test-engine.mjs` | The engines in Node: decay data add up, beta spectra integrate to their mean energies, the S coefficients equal brute-force PCHIP, the Pu-239 alpha self-dose is 20·E/M, the first-year weight, deposition, catalogues, chains, the detriment-adjusted risk coefficients of Publications 60 and 103 recalculated (Tables B-20, 3, 4; A.4.1, 1) and applied to a uniform dose, radon and thoron in homes against Publication 158 (Tables 32.7, 32.8, C.7–C.9), pinned results; then the coefficients against the ICRP's own | `local/` for the comparisons |
| `test-ui.py` | The page in headless Chrome: no script error, the tab icon (its SVG, PNG and touch icon decode; the kvot mark's three tones only), catalogues, every (i), a calculation in each system and an injection, every tab draws (the charts in either theme, with an opaque hover box and no white band at the pointer; the model with the body beside it, numbered alike and lit together; an arrow and its row of the transfer table lit together, and a box with its transfers in and out; after a run, Show fills the boxes as buckets of the activity in the body or of the effective dose (received or its rate, from the member or the whole chain) over time, with what is not drawn listed beside them and the drawing staying put as the time moves; the Risk tab's recalculated Tables 1 and 3 and the nominal detriment of a calculated intake; Radon at home for both gases, recombining at once when F changes), the nuclide field's own suggestions (under the field, keys, reopening), a disabled route that just looks disabled, progeny models of the OIR sections in the chain and model tabs, a link calculates on load, no sideways scroll on a phone, the full window (no site header or footer) by its button, kept for the next visit | a server and Chrome (below) |
| `test-buckets.mjs` | The page's worker in Node over one nuclide of every element and some long chains, each route, both systems: the places the worker sums each member's activity by add up to its whole-body activity, the effective dose by place adds up to e(t) and to the coefficient, and every place holding activity or dose is a box the Model tab draws or one it lists beside them (the airways, the mouth and oesophagus, where a progeny is formed outside its own model). `--quick`: a dozen cases, seconds; otherwise about five minutes | nothing |
| `make-local-fixtures.py` | Writes the reference values into `local/` from your own copies | mdbtools, poppler (pdftotext); the files below |

## The reference values

They are the ICRP's and not ours to publish, so they live in `local/` (in
`.gitignore`) and the comparisons are skipped without them:

- `local/icrp72.json`: the ICRP 72 coefficients with every organ dose, from
  `icrp72.mdb` of ORNL's Radiological Toolbox (`app/data/`), read with
  `mdb-export`. Some of its tables misspell their columns ("Tye", "Kindeys",
  "Thyriod", "Bone Suface", "SKin"); the script maps them.
- `local/icrp119.json`: Tables F.1 and G.1 (ingestion and inhalation by
  members of the public) of the corrected version of ICRP Publication 119,
  read from the PDF with `pdftotext -layout`, which writes the minus sign of
  the exponents as `\x02`. Their values are those of the ICRP 72 database.
- `local/icrp103.json`: every committed effective dose coefficient printed in
  ICRP Publication 158 and the Part 2 and Part 3 consultation drafts, from the
  transcribed element files (their `doses` tables).
- `local/radon.json`: Publication 158's doses per exposure to radon and thoron
  in homes (Tables 32.7, 32.8, C.7, C.8 and C.9), from the radon file's
  `radonExposure` block.
- `local/inmop.json`: the ICRP InMoP Electronic Annex (v.1.23.2.2, dataset
  v.1.2 of 2025.08.25) that accompanies Publication 158: for each of its 290
  nuclides e and the equivalent doses to 30 tissues of the reference male and
  female, for injection, every ingested form, every inhaled material at
  eleven aerosol sizes (organ doses kept at 1 µm) and the gases, plus radon
  and thoron from `RadonData.txt`. The `.eir` files are read as the script's
  comment describes (length-prefixed names, float32 values; the tissue order
  is the data viewer's own). Its licence asks that results obtained with it
  name it as their source: the page's Help does.

```sh
python3 resources/tests/dose_coefficients/make-local-fixtures.py \
    --mdb ~/Downloads/icrp-dc/ornl/x/RadToolbox3_Setup/out/app/data/icrp72.mdb \
    --elements ~/Downloads/icrp-dc/work103/elements \
    --icrp119 ~/Downloads/ICRP/eckerman-et-al-2013-icrp-publication-119-compendium-of-dose-coefficients-based-on-icrp-publication-60.pdf \
    --inmop "$HOME/Downloads/ICRP/InMoP Electronic Annex 2025.08-3.25/InMoPdata"
node resources/tests/dose_coefficients/test-engine.mjs          # about eight minutes: checks and a sample
node resources/tests/dose_coefficients/test-engine.mjs --all    # a few hours: every case of both systems
```

## The browser test

Check the ports first; other sessions use 8765 and 9222:

```sh
lsof -nP -iTCP:8791 -sTCP:LISTEN; lsof -nP -iTCP:9241 -sTCP:LISTEN
python3 -m http.server 8791 --bind 127.0.0.1 &
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \
    --remote-debugging-port=9241 --no-first-run --user-data-dir=/tmp/dctest --disable-gpu about:blank &
DC_HTTP_PORT=8791 DC_CDP_PORT=9241 python3 resources/tests/dose_coefficients/test-ui.py
```

Stop the two by the PIDs you started, not by pattern.

The section headings of the settings follow Chrome's rule that a `<summary>`
holds no control: each heading's (i) is in a slot just before its `<details>`,
in a `<div class="kvot-info-sec">` (kvot-info.css and kvot-info.js place it on
the heading's line). The test checks that with `NO_CONTROL_IN_SUMMARY` and
`HEADING_I_OFF` (as rtm's test has them) and `KvotInfo.audit().inSummary`, and
over CDP with `Audits.enable` that Chrome raises no
`InteractiveContentSummaryDescendant` issue; also that an (i) opens its panel
without folding its section, and that Tab goes from it to its heading.

The full window is kept in the browser's storage (`kvot.dose.full`), which the
test profile keeps from run to run: the test removes it at the start and again
after its full-window checks, so an interrupted run cannot leave the next one
without the site's header. The page keeps a pool
of workers (one per age at intake, as many as the cores allow): a tab left open
by an interrupted run keeps its pool busy and slows the next, so close such tabs
(`curl -s http://127.0.0.1:9241/json/list`, then `/json/close/<id>`).

## Changing the engine

`compare-engines.mjs` runs a copy of the engine as it was against the one in
the repository, case by case, counts the values that differ and gives the
largest relative differences of e, the tissue doses and the transformations:

```sh
mkdir -p /tmp/dose-old && cp -R resources/js/dose resources/js/ode /tmp/dose-old/   # before the change
node resources/tests/dose_coefficients/compare-engines.mjs /tmp/dose-old/dose 0 4 & # and shards 1, 2, 3
```

A change for speed alone should report 0 values differing (the faster matrix
of 2026-10-03 did, over 708,294 values in 544 cases). A change to how the
doses are integrated differs by about the integrator's tolerance: carrying
integrals of activity per source group instead of the doses (2026-10-04)
changed e by at most 1.4e-6 of its value, tissue doses by 1.8e-6 and numbers
of transformations by 6e-6, at three to four times the speed. `--tol 1e-5`
makes the exit status say whether e stayed within that.

## What the comparisons found (2026-10-03)

ICRP 60 system, every case of DCAL's batch files for Federal Guidance
Report 13 against Publication 119, committed effective dose at the six ages:

| | values | within 5 % | within 10 % |
| --- | --- | --- | --- |
| ingestion (Table F.1) | 4512 | 98.0 % | 99.4 % |
| inhalation, Types F, M, S (Table G.1) | 9806 | 96.8 % | 99.2 % |

The values outside 10 % are few and explained in the page's Help (U-232 red
marrow, Pu-246, Cs-125, the 3-month-old for Pb-214, Pb-210 and Pb-212, Si-31,
Rb-86/87 infants).

ICRP 103 system, every coefficient in Publication 158 and the Part 2 and
Part 3 drafts, and every case of the annex:

| | values | within 5 % | within 10 % |
| --- | --- | --- | --- |
| Publication 158 and Part 2 draft, ingestion | 744 | 98.9 % | 99.6 % |
| Publication 158 and Part 2 draft, inhalation | 2214 | 99.5 % | 99.9 % |
| Part 3 draft, ingestion | 342 | 100.0 % | 100.0 % |
| Part 3 draft, inhalation and gases | 804 | 99.9 % | 100.0 % |
| annex, ingestion | 2526 | 99.7 % | 99.9 % |
| annex, inhalation at 1 µm and gases | 5760 | 99.7 % | 99.9 % |
| annex, injection | 1740 | 98.8 % | 99.8 % |
| annex, organ doses (male and female) | 536798 | 97.7 % | 98.8 % |

Progeny follow the models of the OIR sections (`resources/js/dose/progeny103.js`,
`resources/data/dose/icrp103/progeny.json`). What the annex showed beyond the
texts, and the page does: polonium's secreted activity and polonium formed in
the alimentary tract are absorbed with fA 0.1 (not the dietary 0.5);
yttrium, zirconium and niobium take the adult's rates from 25 years; carbon
in methane follows the occupational model of Publication 134 at every age;
the soft-tissue pools (ST0–ST2) of one element's model are not another's;
injection enters where absorption from the lungs does (polonium: Plasma 2).
What the Part 3 draft's tables showed: hafnium, tantalum and francium also take
the adult's rates from 25 years (francium-223's adult was 1.10 and 1.20 times
the table at 20 years: its dose comes from radium formed in the body);
polonium formed from astatine enters blood at Plasma 1 (At-210 is 7–12 % low
with the lead chains' Plasma 2); mercury in "other organic forms and diet"
follows the methyl mercury model, and mercury secreted into the gut is
absorbed with fA 1. Still off by more than 10 %: Ra-228 (+3 to +17 %), and
Ru-94 as RuO4 (about −10 %).
