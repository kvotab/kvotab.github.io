# Tests for ensdf.html

Two suites. The first needs only Node; the second a server and headless Chrome.

## The reader, the chains and the release on the site

    node resources/tests/ensdf/test-parse.js

133 checks in four parts:

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
   the parents (the direct ones of 226Ra and 234U, each with its share; none
   for 36Cl; the chain built going up -- 226Ac reaching 226Ra by its 17 %, its
   branch to 226Th not drawn, 238U to 234U via 234Th and 234mPa at 1 y, the
   short-lived parents with nothing drawn above them listed, no stable parent
   though 136Ce keeps a 2EC mode with no percentage, a cut-off chain with no
   member left hanging; going up and going down giving the same share and
   the same arrow for every pair of start and member, at three settings, and
   226Ra grown in from 230Th the same in both),
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

With `--every-setting` the up-and-down comparison runs at all 55 settings the
page offers (about 12 s; 795 290 pairs and 1 121 653 arrows for the 2026-09-01
release), which is what the About tab says was checked.

Part 4 reads the committed data, so run it again after `scripts/gen-ensdf.mjs`
installs a release.

## The page in a browser

Start the server and the browser as in `../rb/README.md`
(`python3 -m http.server 8765 --bind 127.0.0.1` in the repository root, and
Chrome with `--remote-debugging-port=9222`), then

    python3 resources/tests/ensdf/test-ui.py

Where those ports are taken (another session testing at the same time), start
the two on others and say which:

    SITE_HTTP_PORT=8857 SITE_CDP_PORT=9357 python3 resources/tests/ensdf/test-ui.py

133 checks: the built-in release loads; the tab icon (drawn by
`scripts/gen-ensdf-icon.py`) is linked as an SVG, a 32-pixel PNG and a
180-pixel touch icon, each decodes at its size, and the SVG is XML, in the
64-unit square, named for the page and drawn in the kvot mark's three tones
only; the hover card sets its superscripts as
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
the chain; the series layout (the chain as Radionuclide Decay Chains draws it)
draws every member of the 238U chain as a circle and no box, 234Th straight
under 238U, 214Bi a step of 141.4 px to the right of 214Pb on its row, 234mPa
over 234Pa, every arrow labelled with its mode over its share (α over 100 %),
no label on a circle or another label, no circle on another and no arrow over
a circle not its own -- in the 101Br chain too -- no Unicode superscripts, an
`aria-label` that says how it is laid out; pointing at a circle shows its card and
lights its arrows, a click opens that member and keeps the start, the SVG is
of circles, the Inventory tab fills the start's circle to the brim (and says
circles), a row rings its circle, leaving the tab empties them, and the
layout is kept through a reload and back to the grid, where the drawing stands
on the chart's own background inside the view's padding while a series takes
the view's colour and runs to its edges; the chain zooms in and out a quarter
a step from the buttons on its bar, ⤢ shows all of it in the view, + − and 0
do the same from the page, a pinch (the wheel with Ctrl) zooms about the
pointer with the box under it staying put and the wheel alone does not zoom,
the SVG and PNG come out at the drawing's own size however it is zoomed, a
click on a box keeps the zoom and a new chain opens fitted to the width;
the chain settings are there in the chart view as well; the six
panel tabs fit with no scroll bar of their own, also dragged to 330 px, and
the panel's row of tabs ends at the same line as the main area's, whether
the chain settings stand beside the view tabs or above them; the
Levels, Radiation and Data
sets tabs fill; the four downloads produce files; the Inventory tab draws
the 238U chain over time with 1 Bq at its start and that box full, turns
1 g of 226Ra into 3.66E10 Bq, shows the total emitted energy, and pointing at
a line rings its member in the chain and fills the boxes to that time, while
pointing at a row picks out its line and box, while the table under the chart keeps its columns wherever the cursor is; Run through takes the cursor
to the end, the values save as CSV, and leaving the tab puts the boxes back;
the Nuclide tab lists the parents of 226Ra by mode, longest-lived first,
each a link with its share, and says so when there are none (36Cl); with the
chain set to parents the view tab says "Parents of 226Ra", the chart rings
230Th, 234U and 238U and draws an arrow into 226Ra from each direct parent,
the setting is kept, and the Nuclide tab carries no chain card of its own;
the drawing has
230Th, 234U, 238U, 226Ac and 226Fr but not 226Th, no label on a box, opens on
226Ra at its foot, and the table and the tooltips give each member's share
of its decays that reaches 226Ra (226Ac 17 %); at 1 y 238U goes to 234U via
234Th and 234mPa and the note names what was left out, nearest first; a box
opens its member without moving the start; the parents save as
parents-226Ra.svg, .png and .csv; their inventory starts empty, and 1 g of
230Th grows 226Ra into equilibrium with it; a stable nuclide (206Pb) has
parents, and the setting beside the view tabs turns the chain back down, to
nothing after it;
the database menu lists
NNDC's archive back to 2004 less the release on the site, and choosing one
opens a dialog with the right NNDC link (all three parts, with their mass
numbers, for a release before 2022; a warning for one NNDC lists
incomplete) while staying on the database in use, and its open button brings
up the file picker; a zip made from the fixture
opens in the worker, survives a reload and can be forgotten; the button at
the end of the toolbar gives the page the whole window (no site header or
footer, the chart and the panel taller, the kvot mark leading home and a
theme switch that works in the toolbar), keeps it through a reload and puts
the header and footer back; the theme switch recolours the chart; the phone
layout does not overflow, in the full window either; and no error reaches the
console.

The test starts from a clean state (no remembered settings, no remembered
databases, not in the full window) on its first page of the run, and clears
the database it opens and the full window it remembers.
A reload in the test is `Page.reload`, not `Page.navigate`: navigating to the
same address, or one that differs only after the `#`, does not load the page
again.
