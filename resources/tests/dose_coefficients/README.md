# Tests for dose_coefficients.html

| File | What it proves | Needs |
| --- | --- | --- |
| `test-engine.mjs` | The engines in Node: decay data add up, beta spectra integrate to their mean energies, the S coefficients equal brute-force PCHIP, the Pu-239 alpha self-dose is 20·E/M, the first-year weight, deposition, catalogues, chains, the ICRP 60 remainder tissues' parts adding up to the remainder (by mass as a child grows, or split), the detriment-adjusted risk coefficients of Publications 60 and 103 recalculated (Tables B-20, 3, 4; A.4.1, 1) and applied to a uniform dose, radon and thoron in homes against Publication 158 (Tables 32.7, 32.8, C.7–C.9), pinned results; then the coefficients against the ICRP's own | `local/` for the comparisons |
| `test-ui.py` | The page in headless Chrome: no script error, the tab icon (its SVG, PNG and touch icon decode; the kvot mark's three tones only), catalogues, every (i), a calculation in each system and an injection, every tab draws (the charts in either theme, with an opaque hover box and no white band at the pointer; the model with the body beside it, numbered alike and lit together; an arrow and its row of the transfer table lit together, and a box with its transfers in and out; after a run, Show fills the boxes as buckets of the activity in the body or of the effective dose (received or its rate, from the member or the whole chain) over time, with what is not drawn listed beside them and the drawing staying put as the time moves; the Risk tab's recalculated Tables 1 and 3 and the nominal detriment of a calculated intake; Radon at home for both gases, recombining at once when F changes), the nuclide field's own suggestions (under the field, keys, reopening), a disabled route that just looks disabled, progeny models of the OIR sections in the chain and model tabs, a link calculates on load, external exposure in both systems (the geometry and ages on the side, e alone and with the progeny, per second or hour, the Retention, Model and Decay chain tabs, a nuclide with no model of intakes, a batch), the tissue table's bars of each tissue's share of e (terms adding up to e at every age, the remainder's tissues to its share, each sex's half in the Male and Female views, kept for the next visit), no sideways scroll on a phone, the full window (no site header or footer) by its button, kept for the next visit | a server and Chrome (below) |
| `test-external.mjs` | External exposure (`external.js`): the FGR 12 and FGR 15 data complete, the photon interpolant through its points, the weights of e (and of FGR 12's H_E) adding up to one, a 1 MeV photon giving the table's column, nothing under 10 keV, electrons to the skin only, progeny in equilibrium (secular, transient, never), parts and shares adding up, ages and depths in order, ENSDF decay data within 5 %, pinned results; then every nuclide, geometry, age and tissue against the reports. About 15 s | `local/fgr15.json`, `local/fgr12.json` for the comparisons |
| `test-buckets.mjs` | The page's worker in Node over one nuclide of every element and some long chains, each route, both systems: the places the worker sums each member's activity by add up to its whole-body activity, the effective dose by place adds up to e(t) and to the coefficient, and every place holding activity or dose is a box the Model tab draws or one it lists beside them (the airways, the mouth and oesophagus, where a progeny is formed outside its own model). `--quick`: a dozen cases, seconds; otherwise about five minutes | nothing |
| `test-ensdf.mjs` | The ENSDF processor (`resources/js/dose/ensdf-*.js` with `beta-spectrum.js` and `atomic-relax.js`) on ICRP 107's own inputs, run as EDISTR04 ran it (`ensdf-icrp107.mjs`), against ICRP 107: every beta branch's shape and mean energy against EDISTR04's printout; alpha, recoil, annihilation, gamma, conversion-electron, X-ray and Auger energy per decay against ICRP-07.RAD; daughters and branching against the index. About 3 s | your copy of ICRP 107's supplementary data and `local/eadl1991` (below) |
| `test-decay-data.mjs` | The decay data the page offers besides each system's own (`resources/data/dose/ensdf/`), read as the page reads them, in both systems: every name of the system's own data finds its state (but IT isomers under a minute), Ta-178's swapped names pair by half-life, every isomer a record decays to has a record, the catalogues lose nothing but those isomers, and seven coefficients stay within 1–3 % of those with the system's own data. About 3 s | nothing |
| `compare-ensdf-dose.mjs` | Dose coefficients from processed decay data against those from the ICRP 107 data built in: by default the records the processor makes from ICRP 107's inputs; `--decay DIR` a folder `scripts/gen-dose-ensdf.mjs` made from an ENSDF release, read as the page reads it, its states taking the system's names by half-life (ENSDF 2026 calls ICRP 107's Ta-178m Ta-178, and so on); `--system 60 --base resources/data/dose/icrp103` the ICRP 60 engine on ICRP 107's data both sides. About four minutes on ten cores | as above |
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
- `local/fgr15.json`: the Nuclide_Coefficients of `fgr15_data_2025_05_28.zip`
  from EPA's page of Federal Guidance Report 15 (the July 2025 revision):
  28 tissues, skin and e of 1252 nuclides in seven geometries at six ages,
  read from the zip itself. One file writes `Soil__01` for `Soil_01`.
- `local/fgr12.json`: the DFFUL files of DCAL's `DAT/EXT` folder, FGR 12's
  25 organs, H_R and H_E of 825 nuclides in seven geometries, the ICRP 38
  names mapped to the page's (`Eu-150a` is Eu-150m, and Rh-102 and Ta-180
  swap with their m states, as in `gen-dose-icrp60.mjs`); and the E row of
  its monoenergetic tables. `DFFULINF.GRD` writes H-3's zero as `0.0oE+00`.

```sh
python3 resources/tests/dose_coefficients/make-local-fixtures.py \
    --mdb ~/Downloads/icrp-dc/ornl/x/RadToolbox3_Setup/out/app/data/icrp72.mdb \
    --elements ~/Downloads/icrp-dc/work103/elements \
    --icrp119 ~/Downloads/ICRP/eckerman-et-al-2013-icrp-publication-119-compendium-of-dose-coefficients-based-on-icrp-publication-60.pdf \
    --inmop "$HOME/Downloads/ICRP/InMoP Electronic Annex 2025.08-3.25/InMoPdata" \
    --fgr15 ~/Downloads/fgr/fgr15_data_2025_05_28.zip \
    --fgr12 ~/Downloads/icrp-dc/ornl/x/DCAL01_setup/out/app/DAT/EXT
node resources/tests/dose_coefficients/test-external.mjs        # 15 s
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

Each run starts from a clean origin: the page's saved settings and its
databases are deleted before its scripts run, both `kvot-dose-decay` and
`kvot-ensdf`, which the Chart of Nuclides shares. The suite closes
its tab however the run ends. Another tab of the same origin that holds the
databases open stops it at once, with a message saying so. Opening ensdf.137
waits for the nuclide count to change as well as for the choice: the choice
changes first and the opened data's catalogue after it, so the count read at
once could still be the previous catalogue's (1357).

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

## Decay data from ENSDF

`scripts/gen-dose-ensdf.mjs` makes the engines' decay data from an ENSDF
release; the processor follows EDISTR04 (Endo, Yamaguchi and Eckerman,
JAERI 1347, 2005), the code that made ICRP 107 from ENSDF. ICRP 107's
supplementary data keep EDISTR04's inputs (`ARCHIVE/INPUT`, the ENSDF data
sets as revised in 2004) and its printout (`ARCHIVE/OUTPUT`), so the
processor can be run on the same inputs and held against ICRP 107 itself.
Those files are the ICRP's and are read from your copy (`ICRP107=` the
folder "P 107 JAICRP 38(3) Nuclear Decay Data for Dosimetric
Calculations(supplementary data)", if it is not in `~/Downloads/ICRP/icrp
107/`). EDISTR04 used the atomic data of 1991 (EADL as ENDF/B-VII.1 has it);
make its tables once:

```sh
curl -O https://www.nndc.bnl.gov/endf-b7.1/zips/ENDF-B-VII.1-atomic_relax.zip
node scripts/gen-dose-atomic.mjs ENDF-B-VII.1-atomic_relax.zip resources/tests/dose_coefficients/local/eadl1991
node resources/tests/dose_coefficients/test-ensdf.mjs
node resources/tests/dose_coefficients/compare-ensdf-dose.mjs
```

What EDISTR04 did differently from the processor's defaults, and what the
emulation sets back: its own conversion coefficients (read off its printout
per gamma ray, as ICRP 107's inputs give hardly any); the neutrino energies
of electron capture with the parent atom's binding energies rather than the
daughter's (Np-235's K X-rays are a third of what the daughter's give; the
processor keeps the daughter's, as LOGFT and ENSDF do); no relaxation of
vacancies beyond the O shell; conversion electrons of the M shell at E -
B(M3) and of N+ at the transition energy, which counts N+'s binding energy
twice; ICRP 107's own hand edits (`OUTPUT/Mod_List.pdf`). 46 of the 1033
outputs were made again in 2007-2008 from inputs revised after they were
archived (F-17's has a gamma ray the archived input lacks); `test-ensdf.mjs`
leaves them out.

Found (2026-10-06), on the 1035 parent states with archived inputs:

- beta shapes: all 7214 branches take EDISTR04's, with its reading of the
  spin fields (the first spin listed, the first parity after it; a change of
  4 without a parity change, or more, is taken as allowed);
- alpha particles, recoils and annihilation photons: every nuclide within
  1e-3 of ICRP 107; gamma rays 945 of 952 within 1e-3; conversion electrons
  932 of 952; X-rays and Auger electrons a median 2e-4 to 3e-4 off;
- daughters and branching: 1027 of 1029 as the index has them;
- dose coefficients, ICRP 103 system, 2676 cases (894 nuclides, the default
  form of each route, six ages): 2582 within 0.1 % at every age, 2658 within
  1 %, 2673 within 5 %; per age a median of 3e-6. The ICRP 60 engine on the
  same records (1456 cases, 728 nuclides): 1394 within 0.1 %, 1445 within
  1 %.

What stays apart: unique-forbidden electron capture, where EDISTR04 also
captured from p3/2 shells and the processor's fallback model does not
(Te-123 +22 to +55 %, Pb-205 and Mo-93 1 to 2.5 %; with an ENSDF release the
evaluators' own capture fractions are used instead); Hf-182m (-3 to -5 %),
whose archived input has hand-aligned gamma records that EDISTR04 read a
little differently; outer-shell detail of the X-rays and Auger electrons
(the processor spreads M and N+ vacancies like the L shell's, EDISTR04 had
Rösel's subshell coefficients), which carries little energy.

### From a release of ENSDF

The processor's tables are made once: the atomic data from EPICS2017 (as
ENDF/B-VIII.0 has it), the conversion coefficients from what EDISTR04
printed for ICRP 107 (the theory it applied), the capture fractions from the
release's own; then the decay folder:

```sh
curl -O https://www.nndc.bnl.gov/endf-b8.0/zips/ENDF-B-VIII.0_atomic_relax.zip
node scripts/gen-dose-atomic.mjs ENDF-B-VIII.0_atomic_relax.zip resources/data/dose/atomic
node scripts/gen-dose-icc.mjs "<ICRP 107>/ARCHIVE"
node scripts/gen-dose-capture.mjs ensdf_260901.zip
node scripts/gen-dose-ensdf.mjs ensdf_260901.zip OUT          # about 11 s
node resources/tests/dose_coefficients/compare-ensdf-dose.mjs --decay OUT
```

For the page, `--page` writes only the states it can reach (every state of
at least 10 minutes, every state that takes the name of an ICRP 107 or ICRP
38 nuclide, and their chains: 1376 of 3600 for ENSDF 2026, 13 MB) and enters
the release in `resources/data/dose/ensdf/index.json`, which the Decay data
choices list:

```sh
node scripts/gen-dose-ensdf.mjs ensdf_260901.zip resources/data/dose/ensdf/260901 --page
node resources/tests/dose_coefficients/test-decay-data.mjs
```

The page reads such a folder through `data.js`: its states take the names of
the system's own decay data by half-life (`decay-names.js`; the 2.36 h state
ENSDF 2026 calls Ta-178 is the page's Ta-178m), and the notes of
`notes.json` go to the Decay chain tab.

A release a visitor opens (Open ENSDF…, or files dropped on the page) is
made in the browser by the same module, `ensdf-make.js`, in a worker of its
own (`ensdf-make-worker.js`): a whole release in about 10 s on a desktop
computer, read twice (first its summary, which says what the page can
reach, then the decay data sets of those nuclides only) in some 500 MB of
heap. What it makes is kept in IndexedDB (`decay-store.js`, database
`kvot-dose-decay`), where the calculation workers read it; the files opened
are kept where ensdf.html and rdc.html keep theirs (`ensdf-sources.js`,
`kvot-ensdf`), so a release opened on any of the three pages is offered on
the others. The release on the site made in the browser from its zip gives
the same index as `gen-dose-ensdf.mjs`; the radiations agree to the
round-off of the two JavaScript engines (a line's sixth figure, the order of
two lines of the same energy).

ICRP 107's inputs had been revised by hand before EDISTR04 read them; a
release is read as it is, and a whole release has data sets that EDISTR04's
rules alone turn into nonsense (photons worth twenty times the decay
energy). What `ensdf-release.js` does beyond them, each for a case of ENSDF
2026 (every record's notes go to `OUT/notes.json`):

- states: every ground state, every isomer of a minute or more or that
  decays otherwise than by IT; a shorter IT isomer stays inside the decay
  that makes it, and where a data set stops at one (Hf-177m's at the 1.09 s
  isomer) the isomer's own IT data set carries on; a level above zero is
  never the ground state (Th-229's 8 eV isomer), offset levels ("0.0+X") are
  matched by their letter (Sn-128 to Sb-128m), and a level found by energy
  must agree in half-life or spin (Pb-212's 238.6 keV level is not Bi-212m);
- data sets: one per mode, a single parent's before one shared by two
  (In-108, La-132), a shared one given to its first parent (Ho-160); none
  for a mode the adopted levels do not give (Tb-156's 88 keV isomer); SF
  data sets are single fission fragments' gamma rays and are not used;
- branches: the adopted ones; a minor branch given only as an upper limit
  is left out, a lower limit takes what the others leave (Es-250);
- positrons where a capture branch gives its total only, from the rate
  functions of the two modes with the evaluator's uniqueness flag: against
  the 7931 branches for which ENSDF gives both (LOGFT's), the ratio of
  positrons to capture is a median 1.03 of theirs for allowed branches (10th
  to 90th percentile 0.96 to 1.15) and 1.02 for the first unique;
- feedings: from each level's net outflow of gamma rays where the data set
  gives no feeding intensity (Pr-135, Tm-162, Ag-102), the ground state
  taking what an absolute normalisation leaves;
- normalisation: NT checked against TI = RI (1 + alpha) (Pd-111: NT 1.0 with
  NR 0.0087); NR changed only when three estimates from the data set (the
  levels' net outflows, the fed levels one by one, the excitation energy)
  agree among themselves and all differ from it by more than a factor of 3
  (Pa-228's capture data set: NR 0.0095 where 1997's was 0.095), or agree
  within 5 % and equal NR / BR (Pm-146: gamma rays per parent decay); relative
  intensities scaled to the levels' net outflows (Lu-165: 0.134, ICRP 107's
  input had 0.15), and left out when nothing scales them (Os-178);
- cascades: what a member isomer's own transitions bring down through lower
  levels is the isomer's (Ir-190n's capture through Os-190m); what the
  intensities leave unaccounted goes to the member isomers when the ground
  state is out of the parent's spin reach (Sn-128); a fed level let out by
  no gamma ray, from 200 keV up, sends its energy to the ground state as one
  gamma ray (Lu-165's pseudo levels at 2.8-3.6 MeV);
- conversion: ENSDF's own shell coefficients where given
  (`resources/js/dose/ensdf-icc.js`), else the table; a multipolarity of
  order 3 or more read off uncertain spins is not used, and a level whose
  transitions would carry more than three times what enters it has the
  conversion that nothing measured cut to fit (Th-229's 28.7 keV gamma ray,
  0.1 %, as the default E2: four transitions per decay).

Found against ICRP 107 (2026-10-06, ENSDF 2026-09-01, ICRP 103 system, 2676
cases, states paired by half-life): 637 within 0.1 % at every age, 1685
within 1 %, 2419 within 5 %; per age a median of 4.5e-3 and a 99th
percentile of 0.18. What stays apart is mostly the evaluations: Pu-232's
alpha branch (10 % by systematics, 23 % before), Tb-150's positrons (30 %
of the capture branch, 22 % before), Lu-165's capture strength (now on high
levels from a total-absorption measurement, so fewer positrons), the gamma
normalisations of Yb-175 (NR 0.064 in 2004, 0.1315 now) and Ta-177 (0.0094,
0.015), Te-123's half-life (a limit of 9.2E16 y), Cm-239, Pa-227 and the
like with new decay schemes; and the unique-forbidden capture of Te-123 and
Pb-205 (above). The ICRP 60 engine runs every case on the same folder (1456,
none failing; against ICRP 107's data on that engine 1328 within 5 %).
Errors in ENSDF 2026 itself that the checks above step around: Pa-228's
capture NR (0.0095 for 0.095), Pd-111's beta-minus NT (1.0 beside NR
0.0087), Pm-146's two NR (1, with the gamma rays per 100 decays of the
parent).

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

## Chains in the ICRP 60 system, against DCAL's manual (2026-10-06)

The ICRP 60 engine follows DCAL's user's guide (ORNL/TM-2001/190; its
September 2006 revision is `man/DcalMan.pdf` of the DCAL distribution; the
EPA's edition, dated August 2006, has the same section 9 and lacks the
sections on special lung files and the JAERI decay data). Read again against
its section 9.3.1, two things were done differently, and a third came from
ICRP 72's own numbers:

- a member's source regions are those its own model carries it into,
  "other than by ingrowth" (step 1). DCAL's files for chain members (RAU,
  PBU, BIU, POU, TLU, the radon, astatine and francium files, I-TE) give
  compartments that a member only leaves, such as radium formed from
  thorium in the testes; counted as the member's own, they kept its activity
  in the rest of the body away from them;
- step 5a: a region the parent's model does not name takes, from the first
  member whose model names it on, the region's share of the mass of the
  parent's rest of the body from every member's own, whether that member's
  model names the region or not (the manual's "each member C following B"
  read that way agrees with ICRP 72 in 201 of the 230 series where the two
  readings differ);
- after an inhalation of Type S material, a member with no Type S f1 file of
  its own takes the lower of its f1 and the parent's: the manual is silent,
  and with bismuth's 0.05 (or thallium's, francium's and astatine's 1)
  Pb-211, Pb-212, Pb-214 and Ra-225 Type S had two to three times ICRP 72's
  kidney doses; now every organ is within a few per cent.

Only chains with independent kinetics change (`compare-engines.mjs`: of 544
cases, Ra-224 and U-238 differ; the ICRP 103 cases and the ICRP 60 cases
with shared kinetics are the same value for value). Their 1158 rows (60
nuclides, ingestion and Types F, M, S, six ages) against ICRP 72's organ
doses, share within 10 %:

| | before | after |
| --- | --- | --- |
| committed effective dose (within 5 %) | 94.6 % | 96.3 % |
| testes | 61.6 % | 91.2 % |
| ovaries | 66.4 % | 93.7 % |
| red marrow | 90.4 % | 93.7 % |
| kidneys | 85.2 % | 94.5 % |
| spleen | 69.3 % | 95.2 % |
| all organs | 90.3 % | 95.0 % |

U-232's gonads went from 0.27–0.40 of ICRP 72's to 0.93–1.07 (its e from
0.87–0.89 to 0.98–1.01), Pb-210's from 0.03–0.08 to about 1.0, Ra-225's
from 0.10–0.46. Every case against Publication 119 now: ingestion 4506
values (Pu-238's repeated cases gone), 98.1 % within 5 %, 99.5 % within
10 %; inhalation 9806 values, 96.9 % and 99.2 %; U-232 has left the Help's
list of intakes more than 10 % off at two ages or more. Still off, for other reasons: U-240 Types F and M (testes
and red marrow 1.2–2.7 times ICRP 72's), whose chain ICRP 72 ends at
Np-240m (without Pu-240 they come within 3 %; `chain.js` keeps Pu-240,
which carries 5 % of the energy of 100 years even unweighted, so DCAL's
rule for ending a chain is not the one the manual's words suggest); Ra-223
and Ra-224 Type S (the tissues outside the lungs a quarter to a half of
ICRP 72's); Th-226 by ingestion (testes 4–11 times ICRP 72's doses of
10^-13 to 10^-11 Sv/Bq).

### DCAL itself (2026-10-06)

DCAL's computational modules (ACTACAL, SEECAL, EPACAL) are 32-bit DOS
programs and run in DOSBox-X; its menu and batch driver are Windows programs
and are not needed. `dcal-run.sh` answers ACTACAL's prompts for one case and
runs the three; `dcal-compare.mjs` puts DCAL's committed doses beside the
engine's (and ICRP 72's, with `local/icrp72.json`):

```sh
brew install dosbox-x
export DCAL=~/Downloads/icrp-dc/ornl/x/DCAL01_setup/out/app     # your copy of DCAL
resources/tests/dose_coefficients/dcal-run.sh /tmp/dcal1 U-232 g          # about a minute
node resources/tests/dose_coefficients/dcal-compare.mjs /tmp/dcal1 U-232 ingestion
resources/tests/dose_coefficients/dcal-run.sh /tmp/dcal2 Pb-212 h s       # another folder runs alongside
```

What DCAL itself showed, beyond the manual:

- step 5 as the engine now does it: ACTACAL's log lists, member by member,
  each region's fraction of the rest of the body and whose rest of the body
  it is (`f_Oth`); its activity files hold the activities with those shares
  taken out, the shares varying linearly in age;
- the weight EPACAL gives the older phantom's SEE, the same for every
  target: t^(0.3 + 0.7 (1 - t)^10) for the whole first year (t in years),
  x^(0.5 + 0.5 (1 - x)^5) from 1 to 5 years (x the fraction of the
  interval), linear from 5 years (`dcalWeight` in solve.js; every weight
  read off its dose rates within 0.001). With the shares linear in age, the
  dose from a member's Other is a product of the two (solve.js `cross`).
  With linear weights from 1 to 5 years, Pb-210's 1-year-olds were 6 %
  above DCAL in every organ; with the two-branch first-year weight of
  Publication 158, U-232's 3-month-olds 3-5 %; without the product, U-232's
  testes 7-8 % below DCAL's up to 10 years;
- DCAL's own chain cut keeps Pu-239 after U-239, Pu-240 after U-240, and
  Pb-210 and Po-210 after Th-226, as `chain.js` does; ICRP 72 does not, which
  is why those intakes' liver, bone and gonad doses are well above ICRP 72's;
- after a Type S inhalation DCAL reads each member's own f1 file (BI.GF1 and
  TL.GF1 for Pb-212): ICRP 72's coefficients are of members absorbed no more
  than the parent, which the engine follows (Ra-223 and Ra-224 Type S, whose
  tissues outside the lungs have between a quarter and nine tenths of
  ICRP 72's doses in DCAL and here alike, come out with kidneys 20-25 % below
  DCAL's for it).

This page against DCAL, every organ at every age: within 1-2 % for U-232,
Pb-210, Ra-225, Th-226, Sr-90, Cs-137 and I-131 by ingestion, U-239 and
U-240 Type M, Pu-239 Type M, Co-60 Type S. Where these differ from ICRP 72
(Ra-225's testes at 3 months, 1.18; Cs-137's adult, 1.04) DCAL does too.

## External exposure (2026-10-07)

`external.js` calculates the dose rate coefficients of the Federal Guidance
Reports from their monoenergetic data (`scripts/gen-dose-external.mjs`:
`node scripts/gen-dose-external.mjs <DCAL app folder> <FGR 15 data folder>`,
the folder being the zip unzipped). Neither report spells out its numerics;
these are what reproduce them, found against their nuclide tables (the
first column is the share of FGR 15's 36840 tissue values, adult in air,
within 1 % before the change):

| Choice | Effect |
| --- | --- |
| photons ≥ 10 keV, PCHIP in ln h against ln E, end cubic beyond 5 MeV | photon-dominated nuclides within 0.5 %; linear PCHIP as good, straight lines 1 % high |
| zeros (FGR 15's ground surface at 10 keV) as 1E-100 before the logarithm | Ge-71, Pt-193 and the like exactly; with 1E-60 off by 10^35 |
| bremsstrahlung by eq. C-2, S' by PCHIP in k/T then in ln T | pure beta emitters +1.5 % with S' linear in k/T, +0.2 % linear in ln T; within 0.5 % with both PCHIP |
| the beta spectrum as a PCHIP of its tabulated values, integrated finely | the ground surface's skin: Sn-121 0.65, W-185 0.85 with the spectrum's trapezoid; 1.00-1.02 with PCHIP |
| skin curves log-log PCHIP, zero below the first energy; the air file per uCi (its title says mCi) | electron-dominated skin within 0.2 % |
| a year of 365.25 days in the skin curves' mrem/yr | FGR 12 centred (medians 0.9997-1.0006); FGR 15 0.15 % above |
| no bremsstrahlung from conversion electrons (Appendix C folds the beta spectrum only) | no difference that shows |

FGR 15's effective dose is Table 3-1 on the hermaphrodite phantoms (checked
on its own e column, within its 3 figures). FGR 12's H_E takes the higher
gonad and the five highest of 17 remainder organs (its tables' H_E rows
exactly). Its tables' E rows (ICRP 60, single energies) come out within
0.7 % with the page's ICRP 60 weighting: colon 0.57 ULI + 0.43 LLI, the
ICRP 72 remainder mass-weighted with the splitting rule, without ET.

Against the reports (`test-external.mjs`): FGR 15 e 99.90 % of 51576 values
within 1 %, its tissues 99.89 % of 1495704; FGR 12 H_E 99.70 % of 5628,
organs 99.65 % of 140700. What is left: H-3 (bremsstrahlung above 10 keV
from the top of an 18.6 keV spectrum: e up to 1.03, the colon on the ground
0.8), Ru-106, Ni-63 and Zr-93 (low-energy betas, 1-3 %), and in FGR 12
Sm-151 (H_E 1.3-1.5: FGR 12 gives its 77 keV betas a third less skin dose
than its own curve folded with the ICRP 38 spectrum; with the trapezoid on
the spectrum's grid it is worse). FGR 12 with the trapezoid instead of the
PCHIP spectrum is as good overall (medians 1.0000) but not for Sm-151, so
both reports are calculated the one way.

## What the comparisons found (2026-11-24)

ICRP 103 system against every case of the annex, effective dose at the six
ages and organ doses of both sexes, before the day's changes and after them:

| | values | within 1 % | within 2 % | within 5 % |
| --- | --- | --- | --- | --- |
| injection | 1740 | 91.8 → 99.5 % | 96.6 → 100.0 % | 99.3 → 100.0 % |
| ingestion | 2526 | 96.4 → 99.6 % | 99.2 → 100.0 % | 99.9 → 100.0 % |
| inhalation at 1 µm | 5238 | 98.0 → 99.8 % | 99.7 → 100.0 % | 100.0 % |
| gases and vapours | 522 | 94.8 → 99.4 % | 98.3 → 99.6 % | 100.0 % |
| organ doses (male and female) | 536798 | | 95.8 → 98.9 % | 97.9 → 99.5 % |

Of the annex's 10,026 effective doses 30 are still more than 1 % off (19
cases of nuclide, route and form, of 7 nuclides; 192 values at noon); of its
561,420 organ doses 2,842 are more than 5 % off, in 17 nuclides (5,805 in 45
at noon), and 510 more than 10 % (2,411).
The coefficients the publications print have two figures; the page's value
rounds to the printed one for 92.5 % of the 4,104 of the reference file
(87.8 % before; 3-month-olds 78.5 → 92.8 %) and for 97.3 % of the Part 3
draft's 1,146 (91.7 %; 3-month-olds 76.4 → 96.9 %).

Four of the day's findings are not about one chain but about how the
published coefficients were calculated. None is in the publications' text;
each was read off the annex and then checked on the printed tables:

- **Steps.** The calculation behind the coefficients moves in steps of about
  nine days from the intake on and takes the transfer rates and S at the
  start of each step (`OPTIONS103.ageStep`, 1/40 year; solve.js has the
  detail). Found from the nuclides whose model does not change with age (Ag,
  Bi, Mo, Se, Co, Ir, Ni, Ru, Sb, Tc, Te, S by injection): integrated
  continuously, a 3-month-old's coefficient is low by an amount that grows
  with the half-life, 0.1 % at 6 h, 0.3 % at 17 h, 1 % at 3 d, 1.2–1.8 %
  from 5 d, falling to 0.5–1 % for long-lived ones; a 1-year-old's by
  0.2–0.35 % and a 5-year-old's by 0.1 %. That is S held for the first days
  and half a step late after them. The step that closes each nuclide's gap
  (against its own adult ratio) is 9.06 d in the median at 3 months
  (quartiles 8.9–9.2, 52 nuclides), 8.9 d at 1 year, 9.2 d at 5 years. With
  the rates held too, the bone seekers follow: Sr-90 at 3 months −1.3 %
  continuous, −0.8 % with S in steps, −0.05 % with both (Ba-133 −1.6, −0.9,
  −0.1; Ra-226 −1.4, −0.8, −0.06; Cs-137 −1.35, +0.2, +0.03). This was the
  3-month shortfall: 142 values more than 1 % low at 3 months, none now.
  Tried and worse: PCHIP through a node at 100 d (overshoots 2 %), the
  slope at 1 year from nodes without the newborn, S held over DCAL's time
  grid (spoils 1 and 5 years), the readings listed on 2026-11-24 before.
- **J per MeV.** With the steps in, the densest 0.004 % of the ratios of
  the 93,570 organ doses at each age lies at 1.001354–1.001376:
  1.602176634/1.6 = 1.001360. The annex has 1 MeV = 1.6 × 10⁻¹³ J (the
  factor of Publication 30); see103.js takes it. DCAL's SEECAL has 1.602 ×
  10⁻¹³ (a single-precision constant in the program): the ICRP 60 system
  keeps the exact value, 0.011 % from it.
- **The rest of the body in a chain** (`OPTIONS103.otherShares`, dose103.js
  `otherParts`). A tissue that some member's model names takes its share of
  another member's activity in "Other" by the reference male's masses, for
  both sexes, the masses straight in age between the phantoms', each share
  with its own S; what is left is spread by the masses of the sex whose dose
  it is. It is what DCAL does in the ICRP 60 system (the `cross` columns).
  Found on Bi-210m, whose one progeny Tl-206 names skin, spleen, red marrow
  and gonads: adult female skin 0.841, spleen 1.045, ovaries 1.205, every
  other tissue 1.024, red marrow 0.967; 10-year-old male testes 0.589 and
  skin 0.934 (the shares and S between 10 and 15 years are each
  interpolated, not their product). With the shares all are 1.000 at the six
  ages in both sexes. The same settles the progeny that name muscle (Sr-82's
  adult female muscle 0.87 and breast 1.20; Ag-113 0.79 and 1.23; Ba-129)
  and radium's chains (Ra-226's adult female skin 0.845, ovaries 1.148).
  Three details the annex needs: thallium, bismuth and polonium in lead's
  chains count as naming bone volume (`boneVolume` in progeny.json: without,
  Bi-210m's adult female rest is 1.013); a chain that names trabecular and
  cortical marrow names all marrow (Ra-226's adult female rest 1.008 →
  1.001); and the masses are straight in age from birth (with the 3-month
  masses by eq. 2.16, Bi-210m's skin at 3 months is 0.96). **Chains headed
  by uranium do without** (`"*shares": false` in the uranium set): the Part 2
  draft prints 24 uranium coefficients per age, and at 10 and 15 years and
  for adults 23 or 24 of the page's round to them without the shares, 19
  with; the fraction of the shares' effect that fits is 0 to 0.1 for U-234,
  0.3 to 0.75 for U-238. No annex covers uranium yet. The Part 3 draft needs
  the shares (Sn-113 Type F at 15 years and adult fits only with 0.5 to 1.1
  of them).
- **Progeny formed in the tracts** (`OPTIONS103.giProgenyFA`). Where an
  element has a higher fA in food, its nuclides formed in the gut or the
  lungs take the fA of its other soluble forms, not the highest as paras 130
  and 132 say: antimony from Sb-124n takes 0.05. With 0.1, Sb-124n's brain
  was 1.50–1.70 and thyroid 1.53–1.75 times the annex's after ingestion; the
  annex gives both ingested forms the same coefficient. The same cleared
  Sb-126m, Sb-128m, Y-95, Nb-88, Nb-89, Nb-89m and Te-117 and most of
  Pb-195m and Pb-197m. Secreted antimony keeps the highest (Sb-124 and
  Sb-125 are 0.4–1 % low otherwise), polonium the 0.1 it had.

In radium's chains (progeny.json, the radium set): thallium, lead, bismuth
and polonium formed in the ST0–ST2 of another progeny take their own pools
(Ra-225's kidneys 1.06–1.13 → 1.00, Ra-228's 1.07–1.08 → 1.00), and
thorium's spleen and skin follow ST1's deposition by age instead of being
fixed fractions of the outflow at every age (Ra-228's spleen up to 1.46 and
skin up to 1.45 in children → 1.00).

Checked and kept: full absorption is fA 0.99 (Tc-99 at 3 months is +1.0 %
with 0.999 and −1.2 % with 0.98, −0.06 % with 0.99); actinium from radium's
soft tissue at 1.386 d⁻¹; shadows of a parent's "Other" as the parent has
it.

Each change started from a nuclide the annex had off, split by chain member
and tissue, fitted to the S coefficients of source regions, checked against
the section's text, and then run against the whole annex and the
publications:

- **Caesium formed in barium's bone volume** (db2f3725). A progeny in its
  parent's bone volume has that bone volume as a source region of its own,
  so its "Other" leaves it out (Publication 158 paras 149–150). Ba-129 by
  injection at 3 months 0.908 → 0.999.
- **Thallium formed in lead's or bismuth's red cells** (337b0c7b) stays in
  thallium's red cells: only thallium formed in a part of the blood the
  thallium model lacks goes to plasma (Publication 137 para 481). Pb-194 to
  Pb-200 were up to 7.5 % low; now 0.993–1.007.
- **Lanthanum formed on barium's bone surfaces** (db582b9d) is on its own
  bone surfaces (Publication 137 para 354; para 356's bone turnover rate only
  for barium's bone volume). Cerium formed from lanthanum takes lanthanum's
  compartments, the soft-tissue pools too where they are lanthanum's
  (`sameOther: 'progeny'`). Ba-140 at 3 months 0.954 → 0.981; Ba-141's liver
  0.95 → 1.00.
- **Iodine formed from tellurium or antimony** (45ab9dcc) has one compartment
  for inorganic iodide in other tissue, the simplified model of Publication 137
  para 135 that para 175 assigns. Its organic iodine keeps iodine's
  age-specific compartments: para 135's adult rates take Te-131m at 3 months
  0.6 % low. Te-134 1.04 → 1.00, Te-132 1.02 → 1.00.
- **Saliva** (e6d5967d) passes the oesophagus by the slow transit alone, as
  material cleared from the airways does (Publication 158 section 2.3.2.3). The
  oesophagus of iodine and technetium: I-128 0.62–0.81 → 1.00, I-134
  0.79–0.88 → 1.00, I-131 0.97–0.99 → 1.00.
- **Gallium formed in zinc's kidneys** (3525c2ba) is in gallium's kidneys,
  which empty into the bladder (Publication 134 para 437 gives it their
  half-time). Zn-72 1.02–1.03 → 1.00; its bladder 0.82 → 0.99–1.02.
- **Rubidium formed from strontium** (b0438f09) follows rubidium's own model,
  with kidneys and liver (Publication 151 Table 22.3; the Part 3 draft's
  Table 20.2 by age), not the condensed model of Publication 134 para 484.
  Sr-80's kidneys 0.26 → 1.00; the organ doses of Sr-80, Sr-81 and Sr-83
  within 5 %, 70–88 % → 99–100 %.

Found on the way: Publication 155's photon SAF from cortical marrow
(C-marrow) to red marrow is 20 to 50 times that from trabecular marrow at
every paediatric age (newborn: 5.7 against 0.12 kg⁻¹ near 1 MeV). It is the
ICRP's own data and the annex has it: Ba-140's red marrow at 3 months comes
from the 0.5 % of its La-140 that lanthanum's model carries into cortical
marrow.

Still open: the list at the end of the next section.

## The adult against the OIR Data Viewer, and the chains (2026-11-24, later)

A second reference for the ICRP 103 system, for adults: the OIR Data Viewer
for Publications 134, 137 and 141 (ICRP's electronic annex for workers) has,
for each of its 572 nuclides, an injection record with the effective dose and
the equivalent doses to 30 organs of both sexes, as float32 (the annex's
organ order: fA, 30 male, 30 female, e, after the label "Injection" in each
IRData/*.ird file). Workers are adults on the same systemic models, and
where a nuclide is in the annex too the viewer's values are the annex's
adult values to four figures or more (261 nuclides; all but 32, which are
the strontium isotopes with rubidium progeny, antimony, zirconium and a few
more whose treatment for the public differs). So it is the annex's precision
for the lanthanides, the actinides, thorium and uranium, of which the
publications for the public print two-figure effective doses only. It stays
out of the repository like the annex; the tools read a local copy.

| adult, injection, 572 nuclides | before | after |
| --- | --- | --- |
| e more than 0.5 % off | 228 | 6 |
| e more than 1 % off | 121 | 2 |
| e more than 5 % off | 22 (up to 1.47) | 0 (1.023) |
| organ doses more than 2 % off, of 32,032 | 8,677 | 245 |
| organ doses more than 5 % off | 5,235 | 91 |

The annex at the six ages: organ doses more than 5 % off 2,842 → 796 (of
561,420; more than 2 % off 6,778 → 2,256), effective doses more than 1 % off
30 → 19 (of 10,026). Printed two-figure coefficients: the page's value
rounds to the printed one for 92.5 → 97.2 % of the reference file's 4,104
and 97.3 → 97.6 % of the Part 3 draft's 1,146.

What was found, each from a nuclide that was off, split by tissue and fitted
to source regions as before:

- **A lanthanide formed from another had lanthanum's model.** The
  lanthanide set of progeny.json wrote its entries as "lanthanide:La", which
  gives an element lanthanum's rules and lanthanum's model, liver 50 %.
  Thulium from 167Yb had 41 % of its transformations in the liver; 148Tb,
  whose 148Gd is an alpha emitter, was 1.46 in e and 6.9 in liver; 44
  lanthanide nuclides were off by it. Each entry now has the rules and its own
  model (Publication 141 para 86). All lanthanides but 129La agree.
- **Gadolinium's adult liver rate.** The draft's Table 9.2 prints blood to
  Liver 1 as 5.82 d⁻¹ for adults, europium's value, where its Table 9.1 and
  Publication 141 give 15 %, 3.49 d⁻¹ (with 5.82 the outflow from blood is
  35.6 d⁻¹, not 33.3). 148Gd's liver was 1.615, every gadolinium nuclide 3 to
  11 % high in e; with 3.49 they agree, and 153Gd's printed values 34 → 36 of
  36.
- **Plutonium as a progeny: spleen and skin had no way out.** The added
  compartments leave "as ST1 does", and plutonium's ST1 returns to Blood 2,
  not to the Blood 1 that feeds it, which the code looked for: rate 0. 238Np's
  spleen was 12.3 and its skin 10.5 times the viewer's (238Am, 238Cm, 242Cm,
  242Am alike). progeny103.js now copies the outflows of the compartment the
  added ones are taken from.
- **Marrow.** A model with the marrow of trabecular and cortical bone has
  all marrow there: red and yellow marrow are no part of its "Other"
  (`OPTIONS103.marrowNamed`). 225Ra's tissues outside actinium's named ones
  0.952–0.987 → 0.998–1.000 in the annex; 241Am, 244Cm, 237Np, 238Pu,
  239Pu and 230Th had 7 to 13 of their printed values off each, now none
  or one.
- **Actinium as radium's progeny** takes 0.13 and 0.043 d⁻¹ to skin and
  spleen (para 714's shares to two figures: the annex's 225Ra, spleen and
  skin 0.93 → 1.00), and, formed in the pools of radium that itself grew
  in, keeps its own pools as the other members of the set do (229Th: every
  tissue of the rest 0.79, liver 1.065 → 1.000).
- **Adult ages.** 25 years for actinium, protactinium, berkelium to
  fermium, the lanthanides and aluminium (printed values at 15 years:
  lanthanides 98 → 111 of 114, Bk–Fm 10 → 20 of 20; 227Ra exact). And a
  progeny has its adult rates from the adult age of the element taken in
  (`OPTIONS103.chainAdult`): niobium formed from 93Mo from 20 years (bone
  surface 0.86 and red marrow 0.94 at 15 years and for adults → 1.00;
  90Mo, 200Bi, 201Bi, 203Bi, 203Po follow).
- **Gallium formed from zinc** takes half as much again to bone surfaces
  before adulthood, the rule of zinc's own model and of gallium's in the
  Part 3 draft (para 182): 72Zn's red marrow 0.94–0.96 and bone surface
  0.89–0.93 in children → 0.98–1.02.
- **Bone volume of a progeny model.** Thallium, bismuth and polonium as
  progeny in lead's chains name bone volume whether or not the chain puts
  anything there (`OPTIONS103.progenyBoneVolume`). 210Bi: the kinetics are
  the same at every age, yet the tissues polonium does not name were 4.9 %
  low at 3 months, 5.7, 6.9, 7.4, 7.6 % at 1 to 15 years and 7.7 % for
  adults: the mineral bone's share of the rest of the body. With it out of
  polonium's "Other", every tissue is 1.000–1.001 at every age (585 organ
  doses more than 5 % off → 0).
- **Radium formed in thorium's bone volume** is "produced in
  non-exchangeable bone" (Publication 137 para 812): it leaves at that
  part's rates but stays in thorium's compartment
  (`OPTIONS103.nonexchAt`), so that the actinium and thorium it decays to
  are in their own bone volume, which empties into marrow. 232Th: red
  marrow 0.955 → 0.999, e 0.986 → 0.999; printed 15 → 29 of 30; 229Th 24 →
  30 of 30. Radium that reaches its own non-exchangeable bone the usual
  way is as before (228Ra, exact in the annex).
- **Americium formed in plutonium's Liver 3** stays in the liver, in its
  own Liver 2: with the marrow rule in, 241Pu's liver was 0.877 and its e
  0.967 of the viewer's and 25 of its 48 printed values agreed; now 0.999,
  1.000 and 48. Uranium formed there goes to blood (236Pu: 1.000 so, 1.14
  kept). Plutonium's liver compartments keep the draft table's names, Liver
  1 to 3: with Publication 141's (Liver 0 to 2) 241Pu fits too, but 234Pu's
  liver is 0.51 and 242Cm, whose 238Pu forms in curium's Liver 1 and 2, 2 %
  high.
- **The actinides' own pools.** In the actinide, uranium and thorium sets,
  as in the radium set: formed in the ST0–ST2 of another progeny, a member
  takes its own pool of the same name; the chain parent's pools stay
  foreign. 241Np (whose dose is the 241Am its 241Pu forms), 249Cm, 255Cf,
  248mBk, 236mNp: muscle 0.46–0.78 → 1.00–1.01.
- **Which members count.** The tissues a chain names are those of the
  members the published calculations carry, not of every member the
  cut-off keeps (`OPTIONS103.carried`, chain.js `carriedMembers`): a
  thousandth of the chain's energy over 50 years, with the alpha energy
  weighted by 20 or without. Read off the adult female's skin, which is
  1.20 too high when a member that names skin is counted and was not there,
  and 0.83 when it was there and is not counted. Not carried: 239Pu after
  243Cm (0.0008 either way), 230Th after 234U, 234U after 238Pu, 248Cm
  after 252Cf, 235mU after 239Pu (no energy). Carried: 237Np after 237U
  (0.0045 weighted, 0.0002 not), 234U after 234Np, 148Gd after 152Dy,
  245Cm after 249Cf (0.002), 207Tl and 209Pb at the end of alpha chains
  (0.0008 and 0.0004 weighted, 0.014 and 0.007 not). No single measure
  separates the two lists; the larger of the two shares does.
- **Uranium takes the shares** of the rest of the body like every chain:
  238U, 235U, 233U, 232U, 230U have the adult female's skin at 0.83–0.95
  and her ovaries at 1.03–1.19 without, 1.00 with. The set did without
  since the morning because the Part 2 draft's printed values fitted so;
  what had spoilt them was 234U's 230Th, which is not carried. Printed
  uranium now 238U 48 of 48 (47), 234U 48, 235U 46.

Still open: the list at the end of the next section.

## Radon and thoron against the annex (2026-11-24, last)

Radon was half of what was left in the annex. Rn-222 as a gas and by
ingestion and Rn-220 as a gas, organ doses of both sexes at the six ages:

| | rms of ln(page/annex) | more than 5 % off | e |
| --- | --- | --- | --- |
| Rn-222, gas | 11.0 → 0.9 % | 175 → 0 | 0.977–1.007 → 0.998–1.001 |
| Rn-222, ingestion | 10.9 → 1.1 % | 233 → 0 | 0.987–1.018 → 0.997–1.000 |
| Rn-220, gas | 4.1 → 0.6 % | 32 → 0 | 0.999–1.004 → 0.998–1.002 |

The annex as a whole: organ doses more than 5 % off 796 → 336 (more than 2 %
off 2,256 → 1,584), effective doses more than 1 % off 19 → 13 values (Ca-41,
Po-206 and Po-210 at 3 months, Te-118 for adults). The printed gas and
ingestion coefficients of Tables 32.6 and C.7: 11 of 18 → 18 of 18 round to
the page's; all printed values 97.2 → 97.4 %. The OIR Data Viewer does not
have radon; nothing in it moved.

After the gas is inhaled, 73 % of the chain's transformations are in fat
(82 % in the adult female), 7–10 % in yellow marrow, 4–8 % in other tissue:
what the short-lived progeny do where they are formed decides the organ
doses. Publication 137 paras 652–654 give them the models of lead's chains
with fat and breast compartments added, and rules for the air of the lungs
and for blood only. Read off the annex, variant by variant
(`rn/rnscore.mjs` in the notes):

- **Radon's liver and kidneys are the progeny's own** (identify in the radon
  set). Formed there, lead, bismuth and polonium are in their Liver 1 and
  Kidneys 1; the four compartments of para 652 were added so that every
  compartment of radon's model has its counterpart. Sent to blood at ST0's
  rates (bismuth 66.5 d⁻¹, which takes 57 % of 214Bi away before it decays),
  the liver was 0.87 at 3 months and 1.13 for adults, the kidneys 0.96 and
  1.38, the tissues of the rest 1.03 and 1.17–1.21. Radon's "Other" stays
  foreign: with bismuth leaving it at 200 d⁻¹ the kidneys are 1.07 and muscle
  0.96.
- **Yellow marrow like fat.** Publication 158 added two yellow marrow
  compartments to the model of Publication 137; an adult's hold 10 % of the
  radon (a 3-month-old's as much as the red marrow's). A progeny formed
  there leaves at the rate of its intermediate soft tissue, as from the fat
  compartments (lead 0.004161, bismuth 0.034657, polonium 0.099021, thallium
  2.5 d⁻¹). At ST0's rates, red marrow and bone surface were 0.98 at 3
  months falling to 0.78 and 0.83 for adults; held there for good, 1.16 and
  1.21 for adults, because the 210Pb then stays for decades. Any slow
  release fits (lead at 0.004 to 1 d⁻¹: 0.99–1.01).
- **The breast's inflow by age.** The progeny's uptake to the two breast
  compartments is para 653's for adults, and at other ages in proportion to
  the share of the cardiac output that radon's model gives the compartment
  (`shareOf` in a carve; a 3-month-old's glandular breast has 0.018 of the
  adult's share). With the adult's inflow at every age the breast after
  Rn-220 was 1.12, 1.08 and 1.05 at 3 months, 1 and 5 years, and after
  ingested Rn-222 1.06 at 3 months. The fat compartments' share is 4.0 % at
  every age.
- **Progeny formed in the stomach move on with its contents**
  (`OPTIONS103.contentsTransit`): at radon's own rate, 15.2 d⁻¹ in the
  female from 15 years where the tract's is 20.6. At the tract's rate her
  stomach after ingested Rn-222 was 0.87, her small intestine 1.11 and every
  systemic tissue 1.05–1.08: more of the 214Pb left the stomach before it
  decayed.
- **A side branch is no member.** `carriedMembers` kept what leads to a
  carried member, and 218At, on a branch of 0.02 % of 218Po that joins
  214Po again, was kept for it. Astatine's own model names thyroid,
  salivary glands and stomach wall, which then took shares of radon's
  "Other": a 3-month-old's thyroid 1.06 and salivary glands 1.09, the adult
  female's 0.86 and 0.83, her stomach 0.85. A member now counts for what is
  below it only if a thousandth of that comes through it (the products of
  the branching fractions). 218At, 218Rn and 210Tl are out of radon's
  chains, 219At, 215Bi and 211Po out of 227Ac's.
- **The female's shares.** Radon has a model for each sex, and the female's
  skin, spleen and ovaries at 15 years and for adults tell whose masses
  give her shares. Female over male dose, 15 years and adult: after Rn-222
  1.24, 1.13, 1.31 and 1.30, 1.21, 1.51 in the annex; 1.24, 1.12, 1.30 and
  1.30, 1.20, 1.53 by her own masses; 1.12, 1.00, 1.09 and 1.23, 1.08, 1.22
  by the male's. After Rn-220: 1.23, 1.06, 1.08 and 1.43, 1.20, 1.56 in the
  annex; 1.23, 1.06, 1.08 and 1.43, 1.20, 1.57 by the male's; 1.35, 1.15,
  1.32 and 1.51, 1.29, 1.92 by her own. Each fits to a per cent, and they
  are opposite. Not the male's model for thoron (her breast would be 0.25 of
  the annex's); not lead and bismuth without their added tissues (skin 1.13,
  red marrow 0.85–0.95 in both sexes); not polonium decaying in place
  (kidneys 0.70). The radon set lists the nuclides that take her own
  (`"*sexShares"`: Rn-222); `OPTIONS103.sexShares` is the male's.
- progeny103.js: a spec that starts `from` another keeps that spec's
  identifications and adds its own (it replaced them; astatine's polonium,
  the one spec that had both, repeated the lead set's).

Still open:

- **Radon's kidneys.** 0.96–0.97 after the gas at every age, 0.98 by
  ingestion; 1.01–1.03 after thoron. And the testes of boys after ingested
  Rn-222, 0.95–0.96.
- **Bi-214 and Pb-214 by ingestion and inhalation.** Testes 0.87–0.94 and
  ovaries 0.90–0.94; by injection 0.99–1.00.
- **3-month-olds of calcium, polonium and zinc.** Ca-41, Ca-45 and Ca-47
  1.010–1.012 (strontium, barium and radium are right); Po-206 and Po-210
  1.011–1.014; Zn-65 1.007.
- **Te-118** (Sb-118, 3.6 min): bladder 1.10–1.19, e 0.987 for adults, in
  the annex and in the viewer alike.
- **Se-70** (As-70): spleen and pancreas 1.04–1.07; Se-72.
- **Pb-197m and Pb-195m** (a few tissues; the annex and the viewer differ
  there by 2 % and 0.6 %), **Nb-91**.
- Against the viewer only: **129La** (bone surface 0.81; its 129Ba),
  **240U** (liver 0.93), **235mU** (the female's skin 0.94: its 235U is of
  the parent's element and has the parent's model here).
- **Uranium's bone.** 238U, 235U and 233U: bone surface 0.97–0.98 and the
  female's red marrow 0.98 with everything else at 1.002, where 234U and
  236U are 1.002–1.003 throughout; every uranium value 0.2 % high.
- **Iodine and tritium** (0.3 % and 0.15 % high at every age).
