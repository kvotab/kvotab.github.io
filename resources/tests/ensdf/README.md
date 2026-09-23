# Tests for ensdf.html

Two suites. The first needs only Node; the second a server and headless Chrome.

## The reader, the chains and the release on the site

    node resources/tests/ensdf/test-parse.js

115 checks in four parts:

1. **Fields**, each against what the ENSDF manual says the record means:
   NUCIDs (including `NN` for the neutron and `Z - 100` above Z = 109),
   uncertainties in the last-digit convention, half-lives and widths, level
   energies with an unknown offset (`0+X`, `SN+120`), continuation fields and
   decay modes (`%EC+%B+`, `%B- EQ`, `%A<1E-4`, `%SF=?`), where each mode
   takes the nucleus, how delayed modes come out of the β or ε branch, XREF.
2. **A hand-made data set** in which a picosecond level sits 0.4 keV from an
   isomer: the XREF keeps it from being taken for the isomer (the 212Pb/212Bi
   case), and when the XREF does name it the cascade shares the feeding by
   transition intensity (85 %).
3. **`fixture/ensdf.003`**, A = 3 from the 2026-09-01 release, read end to end.
4. **The release under `resources/data/ensdf/`**: the isomer feedings that are
   well known (234Th → 234mPa 99.85 %, 99Mo → 99mTc 87.6 %, 137Cs → 137mBa
   94.7 %, 239Pu → 235mU 99.9 %), 212Pb not feeding the 25-minute 212Bi
   isomer, whole chains ending where they must, the page's names for
   nuclides, the half-life filter (a member under the threshold -- nuclide or
   isomer, or isomers alone -- is left out and the chain goes straight on by
   every branch it has; what goes through an isomer's IT joins the arrow to
   the same nuclide, anything else is an arrow "via" what it jumped over: at
   1 h 137Cs → 137Ba is one arrow of 100 %, 94.7 % of it through 137mBa, and
   234Th → 234U 99.69 % via 234mPa; at 1 y 238U → 234U via 234Th and 234mPa,
   226Ra → 210Pb via 222Rn … 214Po, 210Pb → 206Pb via 210Bi and 210Po, no
   member but the start under a year, the start kept however short it lives,
   a branch with no percentage on the way leaving the known part (131In →
   131Sn at least 81.5 %), and every chain at 1000 y built in under 5 s),
   the list of NNDC's archive in `nndc.js` (2004-03 to the release on this
   site, newest first, every part of a split release covering A = 1 on or
   saying what it lacks -- NNDC lists 2017-05-01 and 2021-07-01 without
   A = 1-99), the names opened files get (`ensdf_250101.zip`,
   `ensdf_120307_099.zip`, `ENSDF_0410_099.zip`) matching that list,
   a cross-check of every branch against the ICRP Publication
   107 data in `resources/js/rndecaydata.js` — at least 1460 of the 1508
   nuclides must agree (1470 do for the 2026-09-01 release; the rest are
   evaluations that have moved on since 2008) — and of the energy given off
   per decay (at least 1000 of about 1260 within 5 % in all, with isomers
   under a minute counted with their parents; 1025 are, and 1252 in their
   alpha energy), with 210Po, 60Co, 137Cs, 234mPa and 55Fe by name, and
   226Ra carrying 222Rn to 214Po in equilibrium at T½ >= 1 y. Then the decay
   itself: Bateman's two-member chain (15.7214 Bq after 5 d, as rdc.html
   checks), equal half-lives (where Bateman's formula divides by zero),
   the 238U chain in secular equilibrium after 10 My, and no atom lost over
   10^10 years.

Part 4 reads the committed data, so run it again after `scripts/gen-ensdf.mjs`
installs a release.

## The page in a browser

Start the server and the browser as in `../rb/README.md`
(`python3 -m http.server 8765 --bind 127.0.0.1` in the repository root, and
Chrome with `--remote-debugging-port=9222`), then

    python3 resources/tests/ensdf/test-ui.py

73 checks: the built-in release loads; the hover card sets its superscripts as
`<sup>` and draws no Unicode superscript character (Verdana has only ¹ ² ³, so
"²³⁸" came out in two fonts); a nuclide is reached by address
(`#60Co`), by search, by a click on the chart and by the arrow keys; every
colour mode draws its legend; the 238U chain draws every member with no
branch label on a box, bends the arrows that would cross a box and leaves the
others straight, and has no Unicode superscripts in its text; the half-life
settings run from all members to 1000 years, by default all but isomers
under a second; the options change the chain (branches under 1 %, 109mAg
drawn by default and left out at 1 min; at 1 y the 238U chain keeps 238U,
234U, 230Th, 226Ra, 210Pb and 206Pb, its arrows jump over the rest marked
via, and the note names what was left out; at 1 h 137Cs → 137Ba is one
unlabelled arrow, 234Th → 234U is marked via 234mPa, and the view opens
with 234Th's daughters in it); the crowded 101Br
chain, full of β-delayed neutron branches, has no label on another label or
on a box; a box in the chain opens its member without moving the start of
the chain; the chain settings are there in the chart view as well; the six
panel tabs fit with no scroll bar of their own, also dragged to 330 px; the
Levels, Radiation and Data
sets tabs fill; the four downloads produce files; the Inventory tab draws
the 238U chain over time with 1 Bq at its start and that box full, turns
1 g of 226Ra into 3.66E10 Bq, shows the total emitted energy, and pointing at
a line rings its member in the chain and fills the boxes to that time, while
pointing at a row picks out its line and box, while the table under the chart keeps its columns wherever the cursor is; Run through takes the cursor
to the end, the values save as CSV, and leaving the tab puts the boxes back;
the database menu lists
NNDC's archive back to 2004 less the release on the site, and choosing one
opens a dialog with the right NNDC link (all three parts, with their mass
numbers, for a release before 2022; a warning for one NNDC lists
incomplete) while staying on the database in use, and its open button brings
up the file picker; a zip made from the fixture
opens in the worker, survives a reload and can be forgotten; the theme switch
recolours the chart; the phone layout does not overflow; and no error
reaches the console.

The test starts from a clean state (no remembered settings, no remembered
databases) on its first page of the run, and clears the database it opens.
