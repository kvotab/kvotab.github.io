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
python3 resources/tests/serve.py 8791 &
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

Still open: the list at the end of the next section.

## The rest of the open list (2026-11-25)

What the three passes before left open, taken largest first. The annex as a
whole: organ doses more than 5 % off 336 → 2 (the bone surface of a
1-year-old after inhaled Nb-91, both sexes), more than 2 % off 1,584 → 113,
more than 1 % off 5,047 → 2,259 of 561,420. Effective doses more than 1 %
off: 13 → 14 values, all of them 3-month-olds (Ca-41, Ca-47, Po-206,
Po-210). The OIR Data Viewer: e within 0.5 % for 566 → 567 of 572 nuclides,
organ doses outside 2 % 245 → 157 and outside 5 % 91 → 64 of 32,032, of
which 61 are Sr-80 to Sr-83. Printed values that the page's round to: 97.4 %
of 4,104 and 97.6 % of 1,146 as before (69 values moved; one more is off,
Cs-137 ingested in insoluble form at 15 years, 1.451e-9 against a printed
1.4e-9, where the annex gives 1.448e-9).

| | organ doses more than 5 % off | more than 2 % off | what it was |
| --- | --- | --- | --- |
| Te-118 | 138 → 0 | 693 → 0 | antimony formed in tellurium's red cells |
| Bi-214, Pb-214 | 65 and 35 → 0 | 234 and 86 → 0 | the pools of lead that is itself a progeny; the adult age of bone turnover |
| Pb-197m, Pb-195m | 35 and 16 → 0 | 100 and 60 → 0 | mercury's model |
| Se-70, Se-72 | 37 and 8 → 0 | 106 and 104 → 0 | the tissues that only the members before a progeny name |
| Ni-56 | 0 | 30 → 0 | cobalt formed in nickel's kidneys |
| Ca-47 | 0 | 20 → 3 | scandium's model by age |
| Cs-137 | 0 | 8 → 0 (more than 1 %: 144 → 0) | 137mBa's pool in adipose tissue |
| La-129 and the other eleven lanthanum nuclides (viewer) | 17 → 0 | 50 → 0 | barium and caesium on bone surfaces; the tissues only lanthanum names |

One find is a rule of the engine for every chain; the others are in
progeny.json.

- **The tissues that only the members before a progeny name are no part of
  its rest of the body** (`OPTIONS103.ancestorTissues`, dose103.js
  `namedBefore`). They hold what is formed there; what the progeny's own
  model spreads from blood does not go there. Publication 151 describes its
  progeny models so (Annex B: the element's model with compartments added
  for the tissues of the models it is linked to). Tissues that a later member
  names still take their share of an earlier member's rest of the body, as
  before. Two independent cases show it. Arsenic's model has no pancreas,
  spleen or gonads, selenium's has: Se-70 by injection had pancreas
  1.04–1.07, spleen 1.04–1.06 and testes up to 1.06 of the annex, Se-72
  pancreas and spleen 1.03–1.05; with the rule 0.994–0.998, and e 1.000 and
  0.998–0.999.
  And La-129 against the viewer, whose Ba-129 and Cs-129 lack lanthanum's
  liver, kidneys, marrow and gonads: salivary glands 0.84, thymus 0.88,
  breast 0.89 and testes 1.09 without the rule (the bone surfaces already
  set right, below), every tissue 1.000–1.005 with it. Nothing else in the
  annex moves by it but radon (red marrow after ingested Rn-222 1.03 → 1.00
  at 5 and 10 years; muscle and brain, 0.98–1.02 before, 1.00–1.02 now),
  I-118 and I-119 (6 and 2 values more than 1 % off → 0) and Cs-137.
- **137mBa formed from caesium has a pool in adipose tissue.** Publication
  137 para 317 gives it "a set of compartments representing extracellular
  fluids of each of the soft tissues addressed in the model for caesium" and
  then lists 15 of them and other soft tissue; adipose tissue, with 5 % of
  the cardiac output in its Table 6.4, is not on the list. With the adipose
  tissue's 5 % in a pool of its own (9.2 d⁻¹; 7 %, 12.88 d⁻¹, to other soft
  tissue), breast, salivary glands, thymus and gonads after Cs-137 are
  1.000–1.006 of the annex; counted in the other soft tissue they were
  0.979–0.994. (Left there under the new rule they come out 1.01–1.03: the
  rule takes caesium's adipose tissue out of barium's rest of the body.)
- **Lead's chains: the pools of a member that is itself a progeny**
  (`sameOther: 'progeny'` for thallium, lead, bismuth and polonium of the
  lead set, as the radium set has it). After ingested Bi-214 the Pb-210 it
  leaves gives three quarters of the dose to the gonads, and that lead is a
  progeny: its Bi-210, formed in lead's ST1 and ST2, was sent to blood as
  from a place bismuth's model lacks and mostly excreted. Kept in bismuth's
  own pools, Bi-214 by ingestion goes from 3.1 % rms (24 values more than
  5 % off) to 0.4 % (0) and Pb-214 from 1.7 % to 0.2 %; testes 0.87–0.94 →
  0.98–1.00. Where lead is the nuclide taken in (Pb-210) nothing changes,
  and that agrees as before. The radon set starts from the lead set and has
  the rule with it: the testes of boys after ingested Rn-222 0.95–0.96 →
  0.99, skin 0.98–0.99 → 1.00, thoron's kidneys 1.03 → 1.02.
- **Bone turnover is adult from the adult age of the element taken in**
  (`OPTIONS103.chainAdult` now sets it with the progeny's own rates). After
  ingested Bi-214, with bismuth adult from 20 years, the Bi-210 and Po-210
  formed in lead's bone volume left it at a turnover rate still between the
  15-year-old's and the adult's until 25: bone surface 0.990 at 15 years and
  for adults, skin and gonads 1.02–1.03 at 15 years; now 0.999 and 0.99.
- **Mercury formed after lead follows mercury's own model** (the lead set's
  Hg: the divalent-mercury model of the Part 3 draft, 24 d⁻¹ out of Plasma
  1 with 30 % to kidneys and the liver emptied to the small intestine with
  a half-time of 4 d), without its brain compartments and with red marrow,
  skin, testes and ovaries taking para 479's shares (3 %, 0.2 %, 0.03 %,
  0.01 %) from Other 1. Pb-197m and Pb-195m are the annex's only lead
  chains with mercury. With para 479's model (399 d⁻¹ out of plasma read
  from its "16.636 h⁻¹", which it calls a half-time of 1 h; 35 % to kidneys;
  spleen 0.6 %, bone surfaces 1 % each) Pb-197m inhaled as Type F had
  kidneys 1.07–1.10, liver 1.04–1.07 and spleen 1.04–1.09, Pb-195m kidneys
  1.10–1.14; now both are within 0.4 % by injection, ingestion and
  inhalation but Pb-195m's kidneys (1.006–1.009) and the spleen (0.99–1.00).
  Each part was tried alone: para 479's model at 16.636 d⁻¹ leaves the
  kidneys at 1.06–1.09; a spleen compartment with 0.6 % puts the spleen
  4–9 % high; bone surfaces put the bone surface up to 1.7 % and red marrow
  up to 1 % high; the
  brain compartments put a girl's brain 3 % off at 5 and 10 years; without
  red marrow and gonads those are 3–7 % low. Gold formed in mercury's
  kidneys or liver is in gold's own (paras 477 and 479 identify both with
  lead's). The viewer has para 479's model: against it the page was within
  0.2 % before and has liver and spleen 0.98 now. Thallium, mercury and
  gold after lead are the same kind of case as rubidium after strontium:
  the calculation for the public has the element's own model where the OIR
  section gave a model made for the chain.
- **Scandium formed after calcium follows scandium's own model by age** (the
  Part 3 draft's Section 10; the model of Publication 134 paras 247–257 is
  its adult column). A 3-month-old's bone surfaces lose scandium at the bone
  turnover rate of that age, 0.0082 d⁻¹, and 3.7 % of the Sc-47 formed
  there leaves before it decays; with the adult's rates none did. Ca-47's
  liver, kidneys and spleen at 3 months 0.96–0.97 → 1.014–1.016, as its
  other tissues there (calcium's own 1 % at 3 months, below); at 5 to 15
  years 1.007–1.010 → 1.000–1.004.
- **Cobalt formed in nickel's kidneys is in cobalt's kidneys**: nickel's
  Kidneys 1 and Kidneys 2 are cobalt's urinary path and other kidney tissue.
  As a place cobalt's model lacks, the Co-56 formed in Kidneys 1 went back
  to blood at 0.099 d⁻¹: Ni-56's kidneys 1.030–1.038, liver 1.008, e
  1.005–1.006; now 1.000 throughout.
- **Antimony formed in tellurium's red cells is in antimony's red cells**
  (Publication 137 para 177 calls only tellurium's liver and other soft
  tissue ambiguous), and tellurium formed in antimony's is in tellurium's
  (para 134). Sent to plasma, Sb-118 (3.6 min) left the blood with the
  plasma's antimony: Te-118 by injection had the bladder at 1.10–1.19, lungs
  and spleen 0.94–0.95 and e 0.987 for adults, in the annex and the viewer
  alike. Te-118 3.98 % rms → 0.07 %, Te-119m 0.60 → 0.06 %, Sb-127 0.72 →
  0.02 %.
- **Barium formed on a lanthanide's bone surfaces is on barium's own**, and
  caesium formed on barium's leaves at caesium's rate, as the barium set has
  it (Publication 141 para 86 sends both to blood at 1000 d⁻¹). La-129's
  bone surface 0.81 of the viewer's → 1.00.

Tried and not kept: gallium's own model of the Part 3 draft for gallium
formed from zinc (Zn-72's red marrow 0.65–1.07); a spleen compartment for
mercury with 0.05 % of the outflow, which would fit (no source for the
number); for polonium, reabsorbing what the liver secretes with f_A 0.1 at 3
months instead of 0.2 (right for Po-206, 4 % low for Po-210); other
interpolations of the photon SAFs in energy for the bone surface of infants
(linear, log-log, PCHIP in ln E: none gives the signs below).

Still open:

- **Bone surface of 3-month-olds and 1-year-olds** after nuclides that emit
  X-rays of 6 to 35 keV: Fe-55 and Ni-59 0.98 and 0.97, Ba-133 0.98 and
  0.95, Nb-91 1.02 and 1.05 (1.06 inhaled as Type M). From 5 years on all
  are 1.000. (This entry went on to say that the cause lay in the photon
  SAFs themselves "and not in how they are interpolated". That was wrong: it
  was read off the wrong rows of the SAF files. The cause is the
  interpolation in age; see the next section.)
- **3-month-olds of calcium, polonium and zinc.** Ca-41, Ca-45 and Ca-47
  1.010–1.015 in e, every tissue 1.00–1.02 (strontium, barium and radium,
  with the same structure, are right); Po-206 to Po-210 1.009–1.014, the
  heart wall 1.02, skin and testes 1.01; Zn-65 1.007.
- **Radon's kidneys.** 0.96–0.97 after the gas at every age, 0.98 by
  ingestion; 1.02 after thoron at 3 months and 15 years. Ra-226's kidneys
  0.96 for intakes at 15 years, 0.98 at 10 years.
- **Zn-72 and Ca-47 at 10 and 15 years:** thymus 0.97–0.98, thyroid
  0.98–0.99; Zn-72's red marrow 0.98 at 10 years and bone surface 1.01–1.02
  from 5 to 15 years.
- **Bi-214 and Pb-214 by ingestion:** gonads 0.984–0.997, skin 0.989–0.998.
  Mercury's spleen after lead 0.4–0.9 % low; Pb-195m's kidneys 1.006–1.009.
- **Ru-106 inhaled as Type S:** spleen 0.98–1.03 (not looked at).
- Against the viewer only: **240U** (liver 0.93), **235mU** (the female's
  skin 0.94: its 235U is of the parent's element and has the parent's model
  here), **uranium's bone** (238U, 235U and 233U: bone surface 0.97–0.98),
  every uranium value 0.2 % high; **iodine and tritium** 0.3 % and 0.15 %
  high at every age.

## How the reference calculates, not what it models (2026-11-25, later)

What the pass above left open, taken up again. Two of the finds are in the
progeny models; the others are in how the published calculation was done:
how it interpolates in age, how it integrates a beta spectrum, how long its
steps are and how many figures its rates have. The annex as a whole: organ
doses more than 5 % off 2 → 0, more than 2 % off 113 → 37, more than 1 %
off 2,259 → 349 of 561,420. Effective doses: none of the 10,026 is more
than 0.5 % off (47 were, 14 of them more than 1 %); within 0.1 % are
97.9 %, where 78.0 % were; the worst is Pb-210 by injection at 5 years,
0.37 % low. The OIR Data Viewer: e within 0.1 % for 486 → 559 of 572
nuclides, organ doses outside 2 % 157 → 98 and outside 5 % 64 → 60 of
32,032, all 60 of them Sr-80 to Sr-83. Printed values that the page's round
to: 98.9 % of 4,104 (97.4 % before; 67 more round to the printed value, 6
no longer do) and 98.5 % of 1,146 (97.6 %; 14 more, 3 no longer). Those
that no longer do are within 0.1 % of the rounding edge.

| step | organ doses more than 1 % off | more than 2 % | more than 5 % | e within 0.1 % |
| --- | --- | --- | --- | --- |
| as committed (c7774f07) | 2,259 | 113 | 2 | 78.0 % |
| S by age, each radiation type on its own spline | 2,010 | 65 | 0 | 78.4 % |
| the marrow's share as trabecular and cortical marrow | 1,950 | 56 | 0 | 78.6 % |
| plutonium after uranium; the ground state of an isomer (viewer only) | 1,950 | 56 | 0 | 78.6 % |
| beta spectra by the cubic through the product | 1,820 | 57 | 0 | 93.2 % |
| steps of one day for calcium, polonium and zinc | 353 | 35 | 0 | 93.9 % |
| iodide to urine 11.84, barium to the adult's colon 20.16 | 353 | 35 | 0 | 97.8 % |
| the other four-figure rates of Publications 134 and 137 | 349 | 37 | 0 | 97.9 % |

- **S by age: each radiation type on its own spline**
  (`OPTIONS103.ageSpline`, dose103.js `colsFor`, solve.js `slopesOf`). From
  1 year on, S is the PCHIP of the reference ages (Publication 158 para
  174). The spline is not additive: the spline of photons plus electrons is
  not the sum of their splines, and the two differ where the two radiations
  change with age in opposite directions. Publication 155's photon SAFs
  from bone surfaces and marrow to the endosteum are several times lower in
  the newborn than at 1 year (T-bone-S to Endost-BS at 10–30 keV: 1.1
  against 11 kg⁻¹ for electrons), the electrons' higher; the total's spline
  then starts off level at 1 year where the electrons' own falls. With one
  spline for the sum, the bone surface after an intake at 1 year was 0.972
  (Fe-55), 0.974 (Ni-59), 0.953 (Ba-133) and 1.047 (Nb-91) of the annex's,
  and 0.98–1.02 at 3 months; type by type all are 1.000. Twenty-three
  nuclides moved, all towards the annex (Ru-106 inhaled as Type S, whose
  spleen was 0.98–1.03, among them).

  The pass above listed this as open and said that it lay "in the photon
  SAFs to endosteum of the newborn and the 1-year phantom … and not in how
  they are interpolated". That was wrong, and so is the same sentence in the
  message of commit c7774f07. The scripts that printed SAF rows for that
  note took row `target × nS + source`, where the files have
  `source × nT + target`; they showed other pairs' values. With the right
  rows the SAFs are as said here, and the cause is the interpolation in age.

- **The marrow's share of another member's rest of the body**
  (`OPTIONS103.marrowShare`, dose103.js `otherParts`). Where a member's
  model has the marrow of trabecular and cortical bone, the chain names
  those two source regions; another member's "Other" then gives the marrow
  its share as T-marrow and C-marrow and not as red and yellow marrow. The
  mass is the same (adult male 3.371 + 0.279 kg against 1.17 + 2.48), the
  S to bone surfaces and to what lies near bone are not. Uranium's "Other"
  beside thorium's marrow: the bone surface after U-238, U-235 and U-233
  was 0.97–0.98 of the viewer's and the female's red marrow 0.98; zinc's
  beside gallium's and calcium's beside scandium's: the thymus after Zn-72
  and Ca-47 at 10 and 15 years 0.97–0.98 of the annex's, the thyroid
  0.98–0.99. All 1.00 now.

- **Plutonium formed after uranium follows Publication 137 para 921**, the
  reduced model that paragraph gives for it (of what leaves blood 30 % to
  ST0, and of the rest 60 % to the liver and 30 % to bone surfaces), not
  plutonium's own model with skin and spleen added. Only U-239 and U-240
  have it: liver 0.968 and 0.934 of the viewer's → 1.001 and 1.002.

- **The ground state formed from an isomer that was taken in is a progeny**
  (`OPTIONS103.sameElement`). Isotopes of one element share kinetics
  elsewhere in a chain; the daughter of the nuclide taken in itself, where
  the parent's section gives its element a model as a progeny, has that
  model and finds the parent's soft-tissue pools foreign. U-235 after
  U-235m then has the skin, marrow and gonads of uranium as a progeny: the
  female's skin 0.944 of the viewer's and the bone surface 0.98–0.99 on
  the parent's kinetics, every tissue 1.000 so. Am-242 after Am-242m: skin
  and the tissues of the rest of the body 1.03 → 0.99–1.01. (With the
  daughter a progeny but its pools identified with the parent's, Am-242m's
  muscle came out 8.7 times the viewer's.)

- **A beta spectrum is integrated as the cubic through its product with the
  SAF** (`OPTIONS103.betaSpectrum`, see103.js `spectrumOnGrid`,
  `pchipIntegral`): E·N(E)·SAF(E) at the spectrum's tabulated energies, the
  integral of the monotone cubic (PCHIP) through those values. ICRP 107's
  spectra have some 100 energies, few where a spectrum bends most; the
  trapezoidal rule over them is 0.14 % off in a spectrum's energy in the
  root mean square over the 955 spectra and up to 0.5 % in one, against the
  mean energies the same data list (the cubic 0.05 % and 0.27 %). The annex
  has five figures and shows which rule is the reference's. By injection, e
  for adults by the trapezoidal rule and by the cubic: H-3 1.0016 and 1.0000
  of the annex's, Y-92 1.0028 and 1.0000, Y-93 0.9985 and 1.0000, Ni-63
  1.0006 and 1.0000. Scaling the trapezoidal sum to the listed mean energy is not it:
  Ru-106, whose Rh-106 spectrum integrates to 0.11 % above its listed mean,
  is then 0.9987 and by the cubic 0.9998. And one case tells the cubic
  through the product from every rule that integrates the spectrum alone.
  Tritium particles held under the lining of the nose and throat (inhaled
  as Type S) reach its basal cells only with the top of the spectrum: the
  SAF from ET2-seq to ET2-bas is 0 at 10 keV, 0.08 kg⁻¹ at 15 keV and 2.4
  at 20 keV, and the spectrum ends at 18.6 keV. Relative to the trapezoidal
  sum that S is 1.037 by the cubic through the product, 1.047 by parabola
  weights at the tabulated energies, 1.11–1.12 by the cubic through N(E)
  alone integrated finely, 1.26 with N(E) linear; the annex's ET dose needs
  1.036–1.037 at every age (0.984–0.993 of the annex's by the trapezoidal
  rule, 1.02–1.04 by the cubic through N(E), 1.000 now).

- **Steps of one day for calcium, polonium and zinc**
  (`OPTIONS103.shortSteps`). The step of the published calculation was read
  off the annex as the step that makes a continuous calculation agree
  (solve.js): 9.0 to 9.1 days. Done again for every injection case with the
  closer engine, the medians of 23 elements lie between 8.9 and 9.3 days at
  3 months (caesium's at 7.0, with fits from 6.4 to 8.1 that follow the
  half-life: something else). Three elements stand apart: calcium at 3
  months 1.0, 1.4 and 1.5 days (Ca-47, Ca-45, Ca-41) and at 1 year 8.3–8.9;
  polonium 1.0–1.1 days (Po-206, Po-208, Po-210) and at 1 year 8.7–10;
  zinc 1.0 day (Zn-65, Zn-69m, Zn-72), at 1 year 1.1–1.3 days, at 5 years
  the step of all. In the nine-day steps their 3-month-olds were 0.7–1.4 %
  above the annex in e, with bone surface, muscle, skin and gonads apart
  from the rest — the list of open cases the passes before could not
  explain by any change of a transfer rate (the best single rate halved the
  spread). In steps of one day every tissue is within 0.1 %, by injection,
  ingestion and inhalation: the nuclides of the three elements had 1,467
  organ doses more than 1 % off, now none. No rule was found that
  tells these cases from the others: not the rates' change with age
  (strontium's change as calcium's do), not f_A (1, 0.6 and 0.2 at 3
  months; all three have 0.5 at 1 year in food, and nothing else in the
  annex has), not the date or the program in the annex's files (one
  program for all; calcium and zinc dated December 2021 with most others,
  polonium October 2023 with lead, bismuth and radium, which have the nine
  days). The table lists them as found: by the element taken in, the age at
  intake before which the steps are one day (calcium and polonium 1 year,
  zinc 5 years).

- **Rates with four figures.** Publication 158's tables print three. Where
  Publication 134 or 137 prints the adult's rate with four, the published
  coefficients are those of the four. Iodide to the urinary bladder is
  11.84 d⁻¹ in Publication 137 Table 5.4 and 1.18E+01 in Publication 158
  Table 25.3: with 11.8 every tissue of every iodine nuclide was 0.16–0.31 %
  above the annex at every age, growing with the half-life (and Te-131,
  Te-133 0.15 %, by their iodine); with 11.84 they are 1.000. Uranium to the
  bladder is 15.43 (Table 15.4), printed 15.4: every uranium value was
  0.16–0.24 % above the viewer's, now 0.00–0.08 %. Barium to the adult's
  colon is 20.16 (Table 7.3), printed 20.2: adult e of Ba-133 and Ba-140
  0.9986 and 0.9988 → 1.000. The same was then done for every rate that the
  two publications' tables print with four figures (56 rates in fifteen
  elements: tritium, carbon, phosphorus, calcium, yttrium, technetium,
  ruthenium, antimony, tellurium, lead, bismuth, polonium, radium, thorium,
  uranium), at every age where the rate is the same at every age or a plain
  multiple of the adult's that the printed values confirm (carbon and
  tritium: 4, 2.5, 2.5, 2 and 1.2 times; yttrium: two thirds and five
  sixths), else for the adult alone. Each new value was checked to round to
  the printed one. Their effect is small: organ doses within 0.1 % of the
  annex 94.3 → 95.2 %. The rates of the other ages are three-figure
  roundings of products that are printed nowhere; barium's were tried by
  the scale the printed values suggest and left (15 years 0.6 % high).

Tried and not kept: the spectrum as a cubic through N(E) with Gauss points
between the tabulated energies (the tritium case above 2–3.5 % high);
scaling the trapezoidal sum to the listed mean energy (Ru-106 0.13 % low);
other caps than 0.99 on f_A = 1 (caesium and technetium fit 0.99, to 0.1 %
per 0.001); caesium adult from 25 years (15 years 0.6 % low);
the adult age of the progeny's own element for Ra-226's kidneys (no
change).

Still open:

- **Radon's kidneys.** 0.96–0.97 after the gas at every age, 0.98 by
  ingestion; 1.02 after thoron at 3 months and 15 years. Ra-226's kidneys,
  which the radon formed in the body brings, 0.96 for intakes at 15 years
  and 0.98–0.99 at the other ages. Of the 349 organ doses more than 1 % off,
  244 are these three nuclides'.
- **Mo-93 and Tc-97 at 3 months and 1 year** (muscle 1 % low), **Sr-82**
  (kidneys 0.98–1.02 by age), **Sb-119, Ag-115, Se-70** (a few values
  1.0–1.3 % off), **Bi-214 and Pb-214 by ingestion** (gonads 0.984–0.997).
- **Effective doses 0.2–0.4 % off:** Pb-210 at every age but 15 years
  (0.3 % low), Pb-202 and Pb-205 at 15 years (0.3 % high), caesium at 3
  months, 1 year and 15 years (0.2–0.3 % high), barium and radium from 5 to
  15 years (0.2 % high), Ni-59 (0.2 % low at every age), Ag-115. The
  children's rates of these elements are three-figure roundings.
- Against the viewer only: Sb-124 and Sb-125 (e 0.4 and 0.6 % high; the
  annex's own values for adults are matched to 0.01 %, so the two
  references differ there) and Sr-80 to Sr-83 (the public's rubidium).

## Radon formed in the body: its progeny in blood (2026-11-25, last)

The kidneys after radon and after Ra-226 were the last organ doses more than
2 % off. Ra-226's are solved; radon's own are narrowed down and still open.
The annex as a whole: organ doses more than 2 % off 37 → 25, more than 1 %
off 349 → 311 of 561,420; the effective doses do not move.

- **A progeny formed from a noble gas in the gas's blood is in its own blood
  at once** (`OPTIONS103.gasBlood`, model103.js `placeSpec`). Radon, xenon
  and krypton formed in the body have the generic model's one blood
  compartment, from which they are exhaled at 1000 d⁻¹ (Publication 137
  para 711). What they decay to there was moved to its own blood at 1000 d⁻¹,
  as "produced in a blood compartment that is not identifiable with a blood
  compartment" of its model (para 484 for polonium). Only Po-218 (3.1 min)
  tells the two readings apart: a quarter of it decays before such a
  transfer, and polonium entering blood is in Plasma 2, from which a fifth
  goes straight to the kidneys. Ra-226 by injection: the kidneys were 0.989,
  0.996, 0.995, 0.982, 0.963 and 0.987 of the annex's at the six ages, and
  the shortfall followed, age by age, the part of the kidney dose that this
  Po-218 brings (most at 15 years, where radium's own uptake to kidneys is
  least); at once they are 1.002, 1.002, 1.002, 1.000, 1.004 and 1.001, by
  ingestion and inhalation alike, and no other tissue moves (every tissue,
  six ages, both sexes: 0.41 % rms → 0.13 %). The OIR Data Viewer says the
  same for the adult: Ra-226's kidneys 0.987 → 1.001. Ra-224, Ra-223 and
  Ra-228, whose polonium lives a fraction of a second, do not notice.

  Radon that is itself taken in has the two blood compartments of its own
  model (arterial, venous), for which Publication 137 para 654 gives the
  transfer of progeny to plasma at 1000 d⁻¹ in so many words. With the
  progeny of both in plasma at once the kidneys after inhaled Rn-222 come
  out 5–6 % above the annex, and with the transfer from both 3–4 % below
  it. (The next section has what holds: the arterial blood alone.)

Still open, radon taken in (Rn-222 as a gas: kidneys 0.963–0.971 at every
age and liver 0.987–0.992; by ingestion kidneys 0.980–0.984; thoron's
kidneys are right). What is known:

- Of the kidney dose after the gas, Po-214 gives 67 %, Po-218 20 % and
  radon itself 4 %; a further 6 % comes from activity in blood by the
  kidneys' own blood content, 1.5 % from Po-210. Only a seventh of it is
  radon decaying in the kidneys with its progeny held there. The rest
  arrives: Po-218 formed in radon's blood and taken up from Plasma 2 (29 %
  of the dose, 34 % by ingestion), and Bi-214 taken up from plasma, which
  comes from the Bi-214 formed in radon's "Other" (42 % of what passes
  plasma), from bismuth's own fast soft-tissue pool (42 %) and from Pb-214
  in plasma (14 %).
- What the annex asks is a redistribution, not a loss: for the adult
  kidneys +3.9 % and liver +1.3 %, the unnamed tissues −0.3 %, which is
  about the same energy.
- No single reading gives it at every age by both routes. Polonium leaving
  radon's "Other" at about 9 d⁻¹ instead of with a half-time of 7 d fits
  the gas at every age (kidneys within 0.6 %) and a fifth to four fifths of
  ingestion, by age;
  bismuth held 7–14 % less in its fast soft-tissue pool fits ingestion (all
  tissues 0.86 % rms → 0.28 %) and half of the gas, but the same pool is
  right to 0.1 % where lead or bismuth is the nuclide taken in. Bismuth
  leaving radon's "Other" at 85–100 d⁻¹ instead of 66.54, which the pass
  before had as a candidate, is out: skin and gonads, which radon's "Other"
  holds, would then be 2 % low. Neither is the absorption of the progeny
  formed in the gut (lead's f_A is
  right to 1 %: the kidneys of a 3-month-old move by 28 % for 20 % of it),
  or fixed fractions of the plasma outflow for the compartments added to
  lead as a progeny (the gonads of children 2–7 % high). (Corrected: this
  list also had "polonium from arterial blood at once" as ruled out,
  because it gave 70 % of what the gas asks and too little by ingestion. It
  was judged as the one cause of the whole gap; it is one of three. See the
  next section.)
- A second, smaller pattern is shared by radon, thoron and the radium
  isotopes whose lead is formed in the body: at 3 months and at 15 years
  the soft tissues are 1–2 % high and bone surface and red marrow 1–2.5 %
  low; at the other ages 0.3–0.6 %.

## Radon taken in: what the papers behind its model show (2026-11-25, after the papers)

Read: Leggett, Marsh, Gregoratto and Blanchardon, "A generic biokinetic model
for noble gases with application to radon", J. Radiol. Prot. 33 (2013)
413–432, and Samuels, Marsh and Leggett, "An age- and sex-specific
biokinetic model for radon", J. Radiol. Prot. 43 (2023) 041502. Neither says
more about the progeny than Publication 137 does. But the second prints, for
the adult male after inhaled Rn-222, Rn-220 and Rn-219, the doses to six
tissues with Publication 137's radon model and with Publication 158's, each
from radon alone and with its progeny (its Tables 6–8). The annex has neither
the older model nor radon alone. None of the paper's values are in this
repository; the comparison is run from private tools.

What the tables show:

- With progeny and Publication 158's model the paper's values are the
  annex's adult male to three figures (lungs apart, 1–2.5 % higher in the
  paper), so the paper's other columns say how the annex was calculated.
- **Radon alone is right.** With Publication 137's model, whose rates are
  printed with four figures, the page's engine gives the paper's doses
  within 0.3 % in the five tissues other than the lungs. With Publication
  158's, whose tables have three figures, it is 0.2–0.8 % low in each of
  them, 0.5 % on average, for all three isotopes (the adult's uptake from
  the air of the lungs is 1043 d⁻¹ with four figures and 1.04E+03 in the
  table). The whole kidney gap was therefore in the progeny. (The lungs:
  within 0.5 % after Rn-222 and Rn-220, but 13 % lower here than in the
  paper after Rn-219, with either model. The annex has no Rn-219, and its
  lungs after the other two are the page's within 0.3 %.)
- **Radon's arterial blood is the progeny's own blood** (progeny.json, the
  radon set: `identify` "Rn:Blood-A"). With Publication 137's model, for
  which that publication gives every rule, the kidneys with progeny were
  0.979 of the paper's while breast, red marrow, bone surface and liver were
  within 0.3 %, and only after Rn-222: the route of Po-218 (3.1 min) from
  blood to Plasma 2 and from there to the kidneys. With what radon decays to
  in arterial blood in the progeny's blood at once, and the 1000 d⁻¹ kept
  for venous blood: 1.004. The same reading puts the Pb-211 that Rn-219
  leaves in arterial blood (its Po-215 decays where it is formed) in lead's
  plasma: the bone surface after Rn-219 0.987 → 0.999 of the paper's
  (`identify` "Po:Plasma 2" for lead). In the annex the kidneys after
  Rn-222 as a gas go from 0.963–0.971 to 0.986–0.997 at the six ages, both
  sexes. Venous blood at once as well would give 1.07 with Publication
  137's model; two fifths of the venous blood's and none of the arterial
  would fit that model as well, but give 2 % too much by ingestion for
  adults in the annex.
- **Lead leaves a soft tissue that its model does not have at 7.39 d⁻¹ at
  every age** (the lead and radon sets: `unid.soft`). Publication 137 para
  482 gives 7.39 d⁻¹ as "the highest rate of transfer to plasma in the lead
  model", and the page used the rate of lead's fast soft-tissue pool at each
  age, which is 5.28 d⁻¹ at 3 months and 5.32 at 15 years. Thoron's children
  in the annex settle it, tissue by tissue: at 3 months the change is kidneys
  −2.2 %, muscle −1.1 %, red marrow +1.3 %, bone surface +2.0 % where the
  annex asked −1.8, −1.3, +1.3 and +2.0 %; at 15 years −2.3, −1.0, +1.3 and
  +2.5 % for −2.3, −1.7, +1.0 and +2.6 %. This is the "second, smaller
  pattern" of the section before.

The annex as a whole: organ doses more than 1 % off 311 → 160 and more than
2 % off 25 → 3 of 561,420 (Sr-82's adult kidneys twice, Bi-213's testes at
10 years); Rn-220 45 → 0 more than 1 % off, Rn-222 157 → 57 (none more than
1.5 % after the gas, 2.0 % by ingestion), Ra-223 4 → 0. The effective doses
do not move (97.9 % within 0.1 %). Of the printed coefficients only radon's,
thoron's and Ra-226's move, by 0.07 % at most; the OIR Data Viewer's adults
by injection are unchanged.

Still open (all three closed in the next section):

- After the gas, kidneys and liver about 1 % low with Publication 158's
  model, where with Publication 137's they are 0.3 % high. From the older
  model to the newer the progeny passing through blood fall by 7 % here
  (radon's "Other" holds 9 % less) and by about 3.5 % in the paper's
  figures. Not it: a release from the yellow marrow that the newer model
  adds, or from its red marrow (red marrow and bone surface would be
  0.7–1.6 % low for 1 % in the kidneys).
- By ingestion, kidneys 0.984–0.994 and muscle and brain 1.006–1.019, most
  at 3 months. There nine tenths of the lead in blood is Pb-214 formed in
  the stomach and absorbed from the small intestine, and what radon forms in
  its own tissues hardly counts.
- The three-figure rates of Publication 158's radon tables (0.4 % in every
  tissue). The rates follow from blood flows, volumes and partition
  coefficients; not rebuilt, the reference masses of each age would be
  needed to more figures than the paper gives.

## What was left after radon: five rules (2026-11-25, night)

Against the annex: organ doses more than 1 % off 160 → 32 and more than
0.5 % off 1,253 → 238 of 561,420, none more than 2.1 %; within 0.1 %
95.3 → 96.6 %. Effective doses within 0.1 % 97.9 → 98.4 %, within 0.2 %
99.4 → 99.6 %. OIR Data Viewer: effective doses within 0.1 % 97.7 → 97.9 %.
The printed coefficients round as before (98.9 % and 98.5 %).

- **The rest of the body is one source** (`OPTIONS103.otherSAF`, see103.js
  `otherPhantom`). Its S was the mass-weighted mean of the S of each
  target–source pair, each pair interpolated in energy on its own. The
  reference averages the SAFs of the tissues that form it at the tabulated
  energies and interpolates that mean. The monotone cubic is not linear in
  its data, so the two differ where the curves have different shapes: below
  50 keV a tissue's SAF from itself falls with energy and that from its
  neighbours rises. Above, they agree to 0.01 % (Cs-137: no change). Mo-93
  (X-rays of 16.5–18.6 keV, spread through soft tissue) by injection: muscle
  was 0.990, 0.987, 0.994, 0.996, 0.998 and 1.000 of the annex's at the six
  ages, the prostate 0.989 at 1 and 15 years, lymph nodes 0.990 at 10 years,
  salivary glands 1.010 there; the ratio of the two ways is 1.013, 1.006,
  1.005, 1.003 and 1.000 for muscle in the phantoms of 1, 5, 10 and 15 years
  and the adult, 1.011 and 1.013 for the prostate at 1 and 15 years, 1.015
  for the lymph nodes and 0.990 for the salivary glands at 10 years. Mo-93
  31 → 0, Tc-97 8 → 0 and Sb-119 12 → 0 values more than 1 % off. What gave
  it away: liver and kidneys, which Mo's model names, were exact; only
  targets inside "Other" were off, most where the body is small.

- **Radon's rates with more figures than printed** (elements.json, Rn).
  Tables 32.4 and 32.5 have three figures. The rates that follow from
  reference values are rebuilt: RT-air → Blood-A = F × 1440 × 0.43 / V(air),
  Blood-V → RT-air = F × 1440 / (0.73 V(blood)), Blood-A → fat, kidneys,
  liver, bone volume and red marrow = the share of cardiac output × F × 1440
  / (0.27 V(blood)), Blood-A → Other the rest of that flow, and RT-air →
  Environment = ln 2 / T for T = 4.5, 5, 8, 11 and 17 s before adulthood (the
  adult keeps Publication 137's 2600 d⁻¹, which fits better than ln 2 / 23 s).
  F = 0.83, 1.2, 3.4, 5.0, 6.1 and 6.5 (male) or 5.9 (female) l min⁻¹; blood
  0.36067 l at 100 days (382.31 g / 1.06, the mass by body mass between the
  newborn's 290 g and the 530 g at 1 year), then 0.5, 1.4, 2.4, 4.5 or 3.3,
  5.3 or 3.9 l; V(air) = FRC × 3.858 / 3.30. All 132 rebuilt rates round to
  the printed ones; for 100 days the printed rates leave 0.36060–0.36079 l of
  blood with 0.83 l min⁻¹. The mean offset of all tissues from the annex by
  age went from 0.02, −0.33, 0.01, −0.23, 0.23 and 0.09 % to −0.04, 0.01,
  −0.03, −0.08, 0.00 and 0.02 % (the gas, with the bismuth rule below at
  282 d⁻¹); radon alone against the 2023 paper's adult male 0.993–0.998 →
  0.998–1.002. The tissue-to-blood rates stay as printed.

- **Bismuth as a progeny of radon: blood to ST0 at 279 d⁻¹** (progeny.json,
  the radon set: `{op: 'set'}`). Its own model and bismuth as a progeny of
  lead have 300. No source says 279. What says it: after the rules of the
  section before, the annex still asked for kidneys and liver up and the
  unnamed tissues down by amounts that one number explains for the gas,
  for ingestion and for thoron, at every age and in both sexes. By
  ingestion, where it is largest, kidneys asked +1.66, +1.33, +1.34, +1.21,
  +0.66 and +0.83 % at the six ages and muscle −1.82, −0.87, −1.00, −0.69,
  −1.32 and −0.55 %; 282 gives +1.72, +1.34, +1.31, +1.27, +1.16 and +1.04 %
  and −1.63, −1.17, −1.12, −1.05, −0.88 and −0.73 %, and skin, spleen,
  marrow, heart, thyroid and pancreas follow. The best value is 276–282 in
  each of the three cases (rms over all tissues: gas 0.35 → 0.20 %,
  ingestion 0.66 → 0.19 %, thoron 0.23 → 0.18 %). 300 × 3.3248 / 3.576 =
  278.9 would be the fast pool reduced as the fat and breast compartments of
  Publication 137 para 653 reduce the intermediate one; that is a guess.
  Raising the other outflows from blood by 6 % instead does not fit (skin
  and spleen go the wrong way), nor does moving the 18–21 d⁻¹ to fat. Pb-214,
  Pb-212 and Bi-214 taken in themselves are within 0.2 % with 300, and so is
  Publication 137's radon model against the paper (kidneys 1.004 with 300,
  1.015 with 282): the lower rate belongs to Publication 158's radon
  calculation alone.

- **Polonium formed in the ST1 of a bismuth that is itself a progeny is in
  polonium's own soft tissue** (the lead set: `poolNames`, model103.js
  `placeSpec`). Polonium's model has one soft-tissue compartment, "Other"
  here and "ST1" in Publication 137 para 652. Pb-210 by injection had
  kidneys 1.003–1.005 and every soft tissue 0.994–0.998 of the annex's: the
  Po-210 formed in the Bi-210 of the pools was moved to Plasma 2, from where
  a fifth goes to the urinary path. With the three pools one at a time, ST1
  alone gives what is asked (kidneys −0.29 to −0.44 % for −0.31 to −0.45,
  muscle +0.38 to +0.59 for +0.36 to +0.58; 15 years apart, where lead is
  0.2–0.3 % high by itself); ST0 gives a fifth of it and ST2
  half, and all three 1.7 times too much. The same closes the testes after
  ingested Bi-214 and Pb-214 (0.984–0.993 → within 0.3 %). Bi-210 taken in
  is exact with its ST1 foreign, as the pools of the nuclide taken in are
  everywhere. Lead formed from polonium in that soft tissue is in lead's ST1,
  as before. The rule is by element: polonium formed from the radon that
  radium or thorium leaves in its ST1 is not in it (so applied, Ra-228 had
  1,010 values more than 1 % off).

- **Indium formed from the cadmium in silver's liver leaves it** (the silver
  set: `identify` "Ag:Liver 1" and "Ag:Liver 2" null for indium). Silver's
  liver has two compartments and cadmium's one, so cadmium formed there is
  in an ambiguous compartment and leaves at 0.5 d⁻¹ (Publication 151 para
  466). The indium it forms there was placed in indium's own Liver 1 and
  Liver 2, which have the names of silver's. It is ambiguous too and leaves
  at 2.37 d⁻¹: Ag-115 by injection, liver 1.008–1.009 and every other tissue
  0.989–0.999 of the annex's → all 312 organ doses within 0.3 % (rms 0.50 →
  0.10 %).

Still open (nothing more than 2.1 % off; the first two items are closed in
the next section):

- Sr-82: kidneys 0.985, 0.984, 0.992, 1.000, 1.009 and 1.021 at the six
  ages, the adult's heart wall 1.012. Rb-82 lives 76 s; Sr-80, Sr-81 and
  Sr-83 are within 0.5 %.
- Testes by ingestion: Se-70 0.982–0.991, Bi-213 1.004–1.021 (most at 10
  years; by injection and inhalation exact).
- Pancreas, spleen and gonads after Se-70 and Se-72 0.3–0.6 % low. Arsenic
  leaves these four tissues at 0.08 d⁻¹; no single rate fits the three.
- Lead at 15 years 0.2–0.3 % high (Pb-202, Pb-205, Pb-210). Its rates at
  that age are the adult's times 0.72 and bone's share 0.37 to all printed
  figures.
- Effective doses 0.2–0.3 % off: caesium at 3 months, 1 year and 15 years,
  Ra-228 and Ba-133 at 5 years, Ca-41 and Ca-45.

## Strontium-82 and bismuth-213 (2026-11-25, evening)

Against the annex: organ doses more than 1 % off 32 → 6, more than 0.5 % off
238 → 145 of 561,420, and for the first time none more than 2 % (the largest
is 1.8 %, the testes of a 10-year-old after Se-70 swallowed). Effective doses
within 0.1 % 98.4 → 98.5 %. OIR Data Viewer: effective doses within 0.5 %
567 → 568 of 572. Printed coefficients that round to the printed value
98.9 → 99.0 % and 98.5 → 98.6 %.

- **Rubidium formed in strontium's soft tissue leaves at the rate of its own
  "Other" at each age** (progeny.json, the strontium set: `unid.soft` like
  "Other"). The page had the 10.3 d⁻¹ of Publication 134 para 484, which is
  the rate from other tissue of that paragraph's condensed model; the
  calculation for the public has rubidium's characteristic model with rates
  by age (Other to blood 15.3, 13.9, 11.7, 10.2, 8.03 and 7.3 d⁻¹), found
  the day before. Rb-82 lives 76 s, so the kidneys after Sr-82 show how
  much of it reaches blood: with 10.3 d⁻¹ they were 0.985, 0.984, 0.992,
  1.000, 1.009 and 1.021 of the annex's at the six ages, right exactly where
  the two rates meet. With the model's own rate the annex asked +1.48,
  +1.65, +0.78, −0.04, −0.92 and −2.08 % and gets +1.47, +1.64, +0.77, −0.05,
  −0.92 and −2.08 %, liver and the adult's heart wall with them, in both
  sexes. Sr-82 23 → 0 values more than 1 % off. (The opposite of lead's
  7.39 d⁻¹ two sections up, where the stated number holds at every age:
  there the model is the one the number was stated for.)

- **The lesser way to a chain member is not followed where it brings less
  than a thousandth of the chain's energy** (`OPTIONS103.sidePaths`, chain.js
  `lesserWays`). Pb-209 after Bi-213 comes from Po-213 (97.91 %) and from
  Tl-209 (2.09 %); what Tl-209 leaves is 0.0004 of the chain's energy over 50
  years, 0.00002 with the alpha energy weighted by 20. The annex has Bi-213
  without it. By injection and inhalation it cannot be seen. By ingestion
  thallium formed in the gut is absorbed (f_A 1) where bismuth is not
  (0.05), gathers in the testes, and leaves its lead there: the testes were
  1.004, 1.011, 1.016, 1.021, 1.006 and 1.004 of the annex's, colon 1.004,
  red marrow and bone surface 1.003, e 1.0014. Without that Pb-209 the annex
  asked −0.42, −1.07, −1.62, −2.11, −0.59 and −0.42 % for the testes and gets
  −0.42, −1.07, −1.62, −2.14, −0.58 and −0.42 %; every other tissue to
  0.01 %. Thallium's own handling is right as it was: after Bi-212, whose
  Tl-208 gives 63 % of a 10-year-old's testes dose by ingestion, the annex
  asks 0.00 %. The rule as built: for a member with more than one way in,
  the energy the chain loses without a way, by both measures; a way below a
  thousandth is cut unless it is the member's main one. It cuts a way in 116
  of 1,252 chains (Tl-210 to Pb-210 and At-218 to Bi-214 in radium's and
  radon's, Bi-215 to Po-215, Pa-234 to U-234); ways that bring more stay
  (I-131 by Te-131 after Te-131m, Nb-95 by Nb-95m, Pr-144 by Pr-144m, whose
  loss the annex would show). Five other nuclides of the annex move, by up
  to 0.2 % in their most affected organ, four of them towards it (rms over
  their organ doses: Zr-87 0.053 → 0.016 %, I-119 0.023 → 0.012 %, Pb-195m
  0.110 → 0.083 %, Sr-81 0.052 → 0.039 %; Ra-225 0.085 → 0.087 %). Ra-226's
  model is 81 compartments smaller for it (491, with 768 equations).

Still open:

- Testes after Se-70 swallowed 0.982–0.991 (ovaries 0.993–0.997); by
  injection 0.995. Half of what decays there is As-70 formed from the
  selenium of the testes.
- Pancreas, spleen and gonads after Se-70 and Se-72 0.3–0.6 % low.
- Lead at 15 years 0.2–0.3 % high (Pb-202, Pb-205, Pb-210).
- Effective doses 0.2–0.3 % off: caesium at 3 months, 1 year and 15 years
  (the largest, 0.33 %), Ra-228 and Ba-133 at 5 years, Ca-41 and Ca-45.

## Arsenic after selenium, and rates the tables round off (2026-11-25, late)

Against the annex: organ doses more than 1 % off 6 → 0, more than 0.5 % off
145 → 65 and more than 0.2 % off 5,203 → 2,361 of 561,420; within 0.1 %
96.8 → 98.2 %. Effective doses within 0.1 % 98.5 → 99.6 %, within 0.2 %
99.6 → 99.9 % (six of 10,026 are more than 0.2 % off: lead at 15 years and
one of thoron's). OIR Data Viewer unchanged (568 of 572 within 0.5 %).
Printed coefficients that round to the printed value 99.0 % and 98.6 % as
before (at 1 year 98.2 → 98.4 %, at 15 years 98.7 → 99.0 %).

All of it is in the data, none in the engine. The method was the one of the
sections above: what the annex asks tissue by tissue and age by age, beside
what one candidate change gives. Each rule below gives the pattern asked
with nothing fitted but the choice of rule.

- **Arsenic formed from selenium takes a little up into selenium's four
  tissues** (progeny.json, the selenium set). Selenium's model has pancreas,
  spleen, testes and ovaries; arsenic's has not. They are added to arsenic's
  model out of Other 2: 0.004, 0.004, 0.0008 and 0.00028 d⁻¹ from plasma
  (0.01, 0.01, 0.002 and 0.0007 % of the 40 d⁻¹ that leave it), back at
  Other 2's 0.08 d⁻¹. No publication gives the rates. With none, these
  tissues were 0.3–0.6 % low after Se-70 and Se-72, and the testes of a
  10-year-old 1.8 % low after Se-70 swallowed, the largest value left in the
  annex; with a share of arsenic's rest of the body by mass they are 4–7 %
  high (two sections up). With these, every value of both nuclides, both
  routes, both sexes and six ages is within 0.03 %. `ancestorTissues` no
  longer acts here, since arsenic's model names the four tissues itself; its
  evidence is La-129.

- **Caesium's rates before adulthood are worked out, not taken as printed**
  (elements.json). Publication 158 para 448: all rates out of tissue
  compartments are the adult's times 4, 3.5, 2.5, 2.0 and 1.3, and plasma to
  Other 1 keeps the outflow from plasma the same. Table 26.3 prints the
  results with three figures, up to 0.4 % off the product (kidneys to blood
  128 for 127.6). All 185 products round to the printed figures, 26 of them
  exact halves printed upward; plasma to Other 1 is 19.06, 19.06 and 13.06
  for the printed 19.1, 19.1 and 13.1. With the printed figures e of Cs-137
  injected was 1.0032, 1.0023, 0.9999, 1.0009, 1.0022 and 1.0000 of the
  annex's. The annex asked of the liver −0.28, −0.23, +0.01, −0.06, −0.24 %
  and gets −0.27, −0.22, −0.01, −0.07, −0.25; of the testes −0.36, −0.30,
  −0.05, −0.13, −0.22 and gets −0.34, −0.29, −0.04, −0.12, −0.21, which
  needs Other 1 as well (without it −0.18, −0.14, +0.10). No caesium
  coefficient is more than 0.2 % off any longer.

- **Radium's and barium's rates from plasma to soft tissues and excretion
  are the adult's times (1 − B)/(1 − A)**, B the bone's share of the outflow
  from plasma at the age (0.75, 0.45, 0.40, 0.56, 0.74) and A the adult's
  0.25: the scheme of Publication 67, which the tables print with three
  figures. After Ra-226 injected the annex asked of the liver 0.00, +0.12,
  −0.17, +0.26, −0.20 % at the five ages and gets −0.00, +0.11, −0.17,
  +0.25, −0.20; kidneys, muscle, skin, colon and lung the same way.

- **Barium's rates to the bone surfaces at 5, 10 and 15 years are the halves
  that the tables round from**: trabecular 6.225, 9.875 and 14.45 d⁻¹,
  cortical 21.775, 29.325 and 37.35, which add up to 0.40, 0.56 and 0.74 of
  70 d⁻¹. Barium's table prints 6.22, 9.88, 14.5 and radium's 6.23, 9.87,
  14.4: the same numbers rounded each way. After Ba-140 injected at 15 years
  the annex asked −0.05, +0.01, −0.06, −0.17 and −0.18 % of kidneys, liver,
  muscle, red marrow and bone surface and gets −0.06, 0.00, −0.05, −0.16 and
  −0.18; after Ba-133 every tissue was 0.2 % high at 5, 10 and 15 years and
  is within 0.1 % (of Ba-133's values more than 0.1 % off, 608 → 21, all at
  1 year). **Lead's are half of them** (3.1125, 4.9375, 7.225 and
  10.8875, 14.6625, 18.675): after Pb-210 injected the annex asked −0.04 and
  −0.08 % of the kidneys at 5 and 10 years and gets −0.04 and −0.07, liver
  and muscle alike.

- **Calcium is absorbed by 0.499 at 1 to 15 years.** Publication 158 states
  0.5, and so does the head of the annex (which writes 0.99 where the
  fraction is 1). Its numbers are those of 0.499: with 0.5, e after Ca-41
  and Ca-45 swallowed was 1.0020 of the annex's at each of the four ages
  and 1.0000 after an injection. With 0.499 the bone after Ca-45 swallowed
  moves by the −0.20 % asked at all four; the colon after Ca-47, where less
  absorbed means more passing, was asked +0.09, +0.09, +0.12, +0.13 % and
  gets +0.09, +0.09, +0.11, +0.12; what is swallowed from the airways
  follows (bone after Ca-45 inhaled as Type M asked −0.10 to −0.06 %, gets
  −0.08 to −0.06). Zinc, technetium and polonium, absorbed by a half too,
  are at 1.0000: it is calcium's number, not a way of handling a half.

What the annex refused, each tested the same way:

- Radium's bone-surface rates at the halves: with the factor, bone at 15
  years +0.28 % where +0.08 is asked. From the round shares 0.222, 0.252
  and 0.278: bone at 5 years another −0.21 % where nothing more is asked.
  They stay as printed.
- The bone turnover rates with more figures (per cent per year over 36,500):
  bone after Ra-226 up to +0.15 % (10 years) where nothing more is asked.
- The single factor for strontium, calcium and lead. Bone after Sr-90 would
  move by −0.17 % at 5 years and +0.30 % at 10 where the annex asks −0.00
  and −0.01; lead's tissues by +0.07 to +0.14 % at 10 years (kidneys −0.07)
  where it asks −0.06 to +0.05. Their soft-tissue rates stay as printed.

So which tables were computed from their rule and which typed in with three
figures differs from element to element, and only the coefficients tell.

Still open:

- Lead at 15 years: every tissue 0.2 % high after Pb-202, Pb-205 and Pb-210
  (e 1.0023, 1.0024, 1.0015), alike in kidneys, liver, muscle, marrow and
  bone, so it is something that scales the whole systemic burden. Not the
  single factor (half of it, kidneys the wrong way), not the bone rates.
- Radium's bone at 15 years 0.1 % low; the ovaries of a 1-year-old after
  Ra-224 0.5–0.6 % high; muscle and colon after Ra-228 0.3–0.45 % off at 5
  years and for adults.
- Thoron as a gas at 5 years, e 0.21 % high.
- The 65 organ doses more than 0.5 % off: Rn-222 15, Pb-195m, Pb-197m and
  Ag-115 10 each, Pb-200 5, Bi-214, Ra-224 and Te-131 4 each, Rn-220 2,
  Ag-101 1.

## Lead at 15 years: the tract is adult from 20 (2026-11-25, last)

Against the annex: effective doses more than 0.2 % off 6 → 1 of 10,026
(thoron as a gas at 5 years), within 0.1 % 99.6 → 99.7 %; organ doses more
than 0.2 % off 2,361 → 1,792 of 561,420, within 0.1 % 98.2 → 98.4 %. Lead's
values more than 0.1 % off: Pb-202 248 → 0, Pb-205 298 → 12, Pb-210 273 → 0.
OIR Data Viewer and the printed coefficients unchanged.

**The alimentary tract has its adult values from 20 years for every element,
also where the systemic model has its own from 25** (`OPTIONS103.tractAdult`,
model103.js). The transit rates and the absorbed fractions were taken to
their adult values at the element's adult age, 25 years for the alkaline
earths, lead and the actinides. Lead is the one element where that can be
seen: its absorbed fraction changes after 15 years (0.3, then 0.2 for the
adult) and its liver secretes into the small intestine, from where lead is
absorbed again. With the change spread to 25 years a little more comes back
between 15 and 25, and every tissue after Pb-202, Pb-205 and Pb-210 taken in
at 15 years was 0.2 % above the annex's, alike; e 1.0023, 1.0024 and 1.0015,
now 1.0002, 1.0003 and 1.0000.

How it was found: single changes at 15 years, each for its signature.
The red cells' rate with more figures and ST0's: nothing. Bone surface to
blood against bone volume: bone one way, soft tissue the other. Everything
adult from 20: the adult's own doses off by 2 to 10 %. Excretion from plasma
1 % faster: every tissue −0.29 %, alike, with −0.04 at 10 years, the shape
asked. Secreted lead absorbed by 0.2 from 15 years on: −2.3 %, alike. So it
is what comes back from the gut, and a tenth of that step. The adult age of
the tract gives it with no number to choose: after Pb-205 the annex asked
−0.22, −0.20, −0.23, −0.20, −0.17 and −0.27 % of kidneys, liver, muscle, red
marrow, bone surface and colon and gets −0.20, −0.20, −0.21, −0.21, −0.20
and −0.18; after Pb-210 −0.19, −0.19, −0.20, −0.11, −0.16, −0.21 and gets
−0.16, −0.16, −0.16, −0.15, −0.20, −0.16. At 10 years it gives −0.03 to
−0.06 where up to −0.03 was asked (e of Pb-205 0.9996 there, from 1.0000).

No other nuclide of the annex moves by 0.003 % in the rms of its organ doses:
radium, barium, strontium and calcium leave blood for the colon, below
where anything is absorbed, and the actinides' and lanthanides' absorbed
fractions are the same at 15 years and after.

Still open: the last list but for lead.

## Mercury's spleen, and a chain followed way by way (2026-11-25, night)

Against the annex: organ doses more than 0.5 % off 65 → 44 and more than
0.2 % off 1,792 → 1,532 of 561,420, within 0.1 % 98.4 → 98.6 %; effective
doses within 0.1 % 99.7 % as before. Printed coefficients that round to the
printed value 99.0 → 99.1 % and 98.6 → 98.8 %. OIR Data Viewer: 34 nuclides
move, 28 towards it; eleven of them now agree in e and in every organ dose
to the four figures it gives (U-235, U-234, U-238, Am-243, Pm-141, Sm-141,
Sm-141m, Tb-150, Ho-154, Ce-137, Mo-91); organ doses outside 2 % 98 → 96.

It started from the short-lived lead isotopes, 25 of the 65 values that were
left: the spleen after Pb-197m 0.5–0.9 % low, the kidneys after Pb-195m
0.5–0.7 % high. Both are mercury's, and they are two different things.

- **Mercury as lead's progeny has a spleen and bone surfaces after all, at a
  tenth of para 479's shares** (progeny.json, the lead set): 0.06 % of the
  24 d⁻¹ out of Plasma 1 to the spleen (0.0144 d⁻¹) and 0.1 % to each bone
  surface (0.024 d⁻¹), from Other 1, back with 20 days. The day before, a
  spleen at para 479's 0.6 % had put it 4–9 % high and was left out; none is
  0.2–0.9 % low. One rate gives what the annex asks after Pb-197m inhaled as
  Type F, +0.92, +0.68, +0.70, +0.83, +0.80, +0.49 % (got +0.94, +0.70,
  +0.70, +0.80, +0.80, +0.48), and by injection, +0.27 to +0.22 (got +0.28
  to +0.21). A larger uptake in thallium's spleen cannot: it needs 21 % more
  for one route and 9 % for the other. The bone surfaces after Pb-197m as
  Type F asked +0.13 to +0.20 %, get +0.11 to +0.19. The spleen's rate is
  also what its share by mass of the adult's rest of the body takes
  (`ancestorTissues: 'shared'` gives the adult the same and children too
  much): Publication 151's para B.6, with a fixed rate. No publication gives
  the numbers.

- **A chain is followed way by way** (`OPTIONS103.minorMembers`, chain.js
  `waysByEnergy`). A way from one member to the next is followed if what
  comes by it, the next member's own energy and that of everything made
  through it, is a thousandth of what the chain emits in 50 years, with the
  alpha energy weighted by 20 or without; a member no followed way reaches
  is no member. The page had two parts of this, found one at a time: the
  members whose tissues count (`carried`) and the lesser way that is cut
  (`sidePaths`). It still followed the members themselves.
  - Pb-195m: Hg-195m is made by 0.34 % of Tl-195 and brings 0.0006 of the
    energy. It lives 42 hours and gathers in the kidneys: it gave 0.7 % of a
    3-month-old's kidney dose, 0.3 % of the gonads', 0.2 % of the liver's.
    Without it the annex asked −0.71, −0.58, −0.55, −0.53, −0.53, −0.48 % of
    the kidneys and gets −0.69, −0.56, −0.55, −0.55, −0.55, −0.49; liver,
    gonads, and by injection, the same way.
  - Not asked for, and they came with it: Ag-104 after Ag-104m, Po-211 after
    Ra-223, Pb-199 after Po-203, Tc-97m after Ru-97 (rms of their organ
    doses against the annex 0.099 → 0.031 %, 0.118 → 0.053, 0.034 → 0.013,
    0.014 → 0.008).
  - U-235 in the viewer settled what the rule is. Left out member by member
    (each under a thousandth, leading to nothing that is not), everything
    after Th-231 went and e fell from 1.0008 to 0.9987 of the viewer's.
    Judged way by way from the top, with what is below still in place, the
    chain keeps Pa-231, Ac-227, Th-227 and Ra-223 (0.0020 comes by the way
    to Pa-231) and ends there: Rn-219, Po-215, Pb-211 and Bi-211 bring
    0.0009 together. That gives 1.0000 and rms 0.000.
  - A way is judged by what it brings, not the member by what it emits:
    Ra-223 after U-235 emits less than Rn-219 and stays.
  - With the cut-off at none every member is followed, as before.
  - 122 of 1,252 chains lose a member. Ra-226 by ingestion: 9 nuclides
    (At-218, Rn-218 and Tl-210 not followed), 367 compartments, 571
    equations. The Decay chain tab names those not followed.

What stands against the rule:

- Pa-228 in the viewer: with every member and every way followed, rms
  0.043 %; with the lesser way from At-216 to Bi-212 cut (as before this
  step) 0.171; now, without At-216 (0.0009 by its way), 0.372. The viewer
  has that side branch whole. At-216's way brings as much as the way to
  Rn-219 after U-235, which the viewer has not, so no threshold on this
  measure separates the two.
- Pa-231, Th-231, U-231, Np-233 and Pu-243 in the viewer move away by 0.01
  to 0.03 % in rms (Po-211 after Pa-231, Pu-239 after Pu-243).
- Sr-81 in the annex, 0.040 → 0.043 %.

Still open:

- Pb-200 inhaled as Type S at 3 months: bladder wall, prostate, ovaries and
  uterus 0.6–0.7 % low (5 values).
- The 44 organ doses more than 0.5 % off: Rn-222 16, Ag-115 10, Pb-200 5,
  Ra-224 and Te-131 4 each, Bi-214 and Rn-220 2 each, Ag-101 1.
- Thoron as a gas at 5 years, e 0.21 % high; radium's bone at 15 years.

## Five of the leftovers, each a detail of a progeny's model (2026-11-26)

Against the annex: organ doses more than 0.5 % off 44 → 14 and more than
0.2 % off 1,532 → 1,230 of 561,420; within 0.1 % 98.6 → 98.8 %. Effective
doses as they were (99.7 % within 0.1 %, one more than 0.2 % off). Printed
coefficients that round to the printed value 99.1 % as before (at 1 year
98.5 → 98.7 %, at 15 years 99.1 → 99.3 %), Part 3's 98.8 → 98.9 %. OIR Data
Viewer: Te-131, Te-131m, Te-133 and Te-133m now to its four figures, nothing
else moves.

Each of the five was found the same way as before, by what the annex asks
tissue by tissue and age by age; and each turned on one observation.

- **Lead as a progeny: the rates to its five added tissues are held with two
  figures** (progeny.json, the lead set; progeny103.js `carve` takes a rate
  for each age). The ovaries of a 1-year-old were 0.5–0.6 % high after
  Ra-224, Bi-214 and Pb-214, the skin up to 0.5 %. Taking each added tissue's
  uptake away in turn showed that lead's gives 15–18 % of the ovaries' dose
  and 5–18 % of the skin's, and that the annex asks the same of that part in
  both tissues and both chains: −3 % at 1 year, +0.8 % at 5, −1 % at 15. The
  testes carry the same path (24–44 % of their dose) and ask otherwise:
  nothing at 1 year, +0.6 % at 10. So it is tissue by tissue, and ovaries and
  skin go together because their adult rates share a mantissa (0.0014 and
  0.14 d⁻¹): times the factor of 1 year, 0.124 rounds to 0.12 (−3.2 %),
  while the testes' 0.0031 stays. With two figures: after Bi-214 swallowed
  the ovaries asked −0.19, −0.54, +0.13, −0.04, −0.17 % and get −0.18,
  −0.50, +0.13, +0.08, −0.21; red marrow −0.00, −0.05, −0.11, +0.11, −0.01
  and −0.02, −0.06, −0.11, +0.09, −0.06; the testes −0.05, −0.14, −0.14,
  +0.23, −0.22 and −0.01, −0.07, −0.15, +0.30, −0.25. **One exception, kept
  and not understood:** skin and ovaries at 10 years, where two figures
  (0.12, +4.2 %) put them 0.6–0.7 % high and the unrounded 0.1152 fits.
  Rounded there as well, Bi-214 moves away from the annex.

- **Iodine as tellurium's progeny: the organic iodine of other tissue in one
  compartment, its rates by age** (the tellurium set). Te-131 swallowed had
  the brain 0.7 % high at 3 months and 1 year and 0.1 % for adults, muscle,
  skin and testes with it. I-131 taken in itself is exact, so only the
  progeny's variant of the model could differ, and the fall with age is that
  of the organic iodine a young thyroid releases. Publication 137 para 135
  has one compartment for it (15 d⁻¹ in, 9.0 back, 0.09 to blood iodide).
  Two days before, that had been tried with the adult's rates at every age,
  found 0.6 % low at 3 months, and iodine's own two compartments kept. With
  the three rates times the age factor of iodine's own model (26.3 … 15 over
  15) every tissue at every age is as asked, to 0.02 %: Te-131 brain −0.66,
  −0.74, −0.44, −0.27, −0.26, −0.14 % asked and −0.66, −0.72, −0.44, −0.28,
  −0.26, −0.14 got; Te-133, which went the other way, liver −0.42, −0.32,
  −0.20, −0.11, −0.11, −0.06 and −0.42, −0.32, −0.20, −0.11, −0.10, −0.06.

- **Indium as silver's progeny: muscle and pancreas come out of its fast
  pool** (the silver set; the cadmium and tin sets alike). Publication 151
  para 466 adds them, fed from transferrin at 0.2 and 0.001 d⁻¹ and back at
  2.37; the set had them on top, 1.783 d⁻¹ out of transferrin for the
  model's 1.582. Ag-115 had red marrow and bone surface 0.9 % low at
  3 months swallowed and brain, gonads and skin 0.1–0.45 % high. A faster
  release of indium from other soft tissue (2.59 for 2.37 d⁻¹) fitted five
  tissues to 0.01 % with an odd number, marrow short and kidneys over: the
  sign of another mechanism with the same face. Taken out of ST0, which
  returns at the same 2.37, nothing passes through plasma and the kidneys
  stay: red marrow +0.93, +0.20, +0.14, +0.10, +0.06, +0.06 % asked and
  +0.93, +0.20, +0.14, +0.09, +0.06, +0.06 got, every other tissue alike,
  swallowed and inhaled. From ST0 and ST1 in proportion a third too much.

- **Rhodium formed in palladium's ST0–ST2 is in its own** (the silver set:
  `sameOther: 'progeny'`). The two models have one structure with the same
  names (Publication 151 para B.5). Sent to blood as from a compartment its
  model lacks, the adult's testes after Ag-101 inhaled were 0.9 % low; in
  its own pools +0.94 % is asked and +0.93 got. Not palladium in silver's
  pools (three times too much), and not cadmium and indium, whose pools are
  other things.

- **The female's own masses where her model is her own** (dose103.js;
  `sexShares: 'own'`, with `'own-all'` for every age). Radon's two models
  are the same at 3 months to 10 years and differ from 15. With her masses
  for the shares at 5 and 10 years too, where she has 130–180 g less brain
  and as much more adipose tissue and radon names adipose, her skin, spleen
  and ovaries after Rn-222 were 0.5–0.9 % high; with the male's there, as
  for every other element, within 0.26 %.

Still open:

- Pb-200 inhaled as Type S at 3 months: bladder wall, prostate, uterus and
  ovaries 0.6–0.7 % low, colon 0.25 %, exact at 1 year. More thallium
  absorbed from the gut moves them the wrong way; the missing dose is low
  in the gut or in the bladder.
- Rn-222: seven single values of 0.5–0.65 % (testes and pancreas at 10
  years as a gas; brain, oral mucosa, stomach wall, thymus swallowed).
- Thoron as a gas: kidneys 0.5 % high at 15 years and for adults, e 0.21 %
  high at 5 years.
- Pa-228 in the viewer, against the way-by-way rule (the section before).

## A year of 365 days (2026-11-26, later)

Found while looking at Pa-228 in the viewer, organ by organ: 231Pa was a
uniform 0.04 % below the viewer in every soft tissue and 227Ac a uniform
0.03 % above, and a table of every nuclide with a half-life in years showed
the same everywhere, by how long the nuclide lives and stays: +0.06 % for
173Lu, 147Pm, 252Cf, +0.05 % for 55Fe, 244Cm, +0.03 % for 133Ba, 243Cm,
+0.02 % for 60Co, 90Sr, nothing for 241Am (432 y) or 3H. That is 365/365.25:
the calculation behind the coefficients counts a half-life given in years
with 365 days to the year, as it counts the 50 years (18,250 days, which the
page had already). `OPTIONS103.yearDays` (365; model103.js `assemble103`
scales the decay constant of the members whose half-life the decay data give
in years; T, shown in the Decay chain tab, stays the data's).

- OIR Data Viewer: nuclides at its four figures in e and every organ 387 →
  422 of 572, none lost. Of 78 that move 62 come nearer. The 13 farther all
  have another, larger difference in single tissues (rms 0.08 to 1.2 %);
  seven of them have e at 1.0000 with it (238Np, 238Am, 236Pu, 238Cm, 242Am,
  242mAm, 242Cm).
- A progeny counts too: 148Tb (148Gd, 75 y), 60mCo, 134mCs, 152nEu and
  154mEu were 0.02–0.03 % low (the atoms are given, the activity is theirs
  times the decay constant) and are exact.
- Annex: 16 nuclides move, 15 nearer (55Fe rms 0.053 → 0.013, 60Co 0.022 →
  0.006, 125Sb, 134Cs); 214Bi 0.020 → 0.023, its testes, ovaries and skin
  0.05 % higher through 210Pb where bone surface comes nearer. Organ doses
  within 0.1 % 98.78 → 98.81 %, more than 0.2 % off 1,230 → 1,221, more
  than 0.5 % off 14 as before.
- Printed coefficients that round to the printed value 99.1 → 99.2 % (adults
  99.6 → 99.9 %), Part 3's 98.9 → 99.0 % (adults 99.5 → 100 %).

Pa-228, which started it, is as it was. What is known now: the three ways
of following a chain were run for the 90 viewer nuclides they tell apart,
with the year right. The way-by-way rule is the best, or within 0.005 % of
it, for all but 228Pa, 233Np and 231Pa (0.04 % low in e with it). 228Pa
comes out right (rms 0.37 → 0.045 %) if a way is also followed where it
brings a thousandth of what the chain has emitted by some earlier time:
216At and what it leaves are 4 % of the energy of the first ten days and
0.3 % of the first year's, before 228Th's 1.9 years have told. The other
nuclides bracket that time: under 1.5 days 224Ac gets 220Ra and 216Rn, which
the viewer has not (rms 0.036 → 0.117 %); from 9 hours to 12 days 230Pa gets
226Ac, which it has not (0.013 → 0.075 %); from 12 days to 5 years 228Pa is
the only chain of 1,252 that changes. Not put in: one nuclide, a time with a
window that wide, and 233Np (229Pa on a branch of 0.001 %) wanting something
between the rule and every way.

Pb-200 inhaled as Type S at 3 months, looked at once more: it is that case
alone, of the annex's 1,671. The other 17 lead isotopes as Type S at
3 months are within 0.15 % in every organ (the uterus after 196Pb, 197mPb
and 199Pb 0.11 to 0.14 % high, the other way; 201Pb with its thallium
0.04 %), 200Pb as Type M and F, swallowed and injected at 3 months within
0.04 %, and Type S from 1 year on within 0.03 %. The annex states the same
absorbed fractions for all of them. Bladder wall and prostate are low alike,
so what is missing lies behind them, in the contents of the rectosigmoid.
Nothing a rule could be read from; left as it is.

## 228Pa: a chain is judged over its first year too (2026-11-26, last)

`OPTIONS103.minorEarly` (365.25 days; chain.js `waysByEnergy`, which the
chain's `early` option passes on): a way is followed also where what comes
by it is a thousandth of what the chain emits over its first year, by
either measure. 216At after 228Pa, on a side branch (2 % of 228Pa makes
224Ac, 9 % of that 220Fr), brings 0.0009 of the chain's energy over 50
years and 0.003 over the first year, when little of the 228Th made beside
it has decayed. The OIR Data Viewer has it: e 0.9981 -> 1.0000 of the
viewer's, organ doses from up to 0.51 % low (rms 0.37 %) to within 0.09 %
(rms 0.046 %).

Nothing else moves: no other nuclide of the viewer, nothing in the annex
(it has no protactinium), no printed coefficient. 122 of 1,252 chains still
lose a member; 228Pa's are 220Ra and 216Rn. The Decay chain tab's sentence
on the members not followed says "over 50 years and over its first year"
(ui.js, stamp 20261126a).

Which first stretch: judged over a first stretch of anything from half an
hour to 50 years, six of the 1,252 chains change (224Ac, 223Fr, 223Rn,
253Cf, 228Pa, 230Pa), and bisected, 228Pa's alone changes from 14.3 days to
6.0 years. Under 14.3 days 230Pa gains 226Ac,
which the viewer has not (rms 0.012 -> 0.075 % with a day); under 1.6 days
224Ac gains 220Ra and 216Rn (0.036 -> 0.117 % with an hour). A year was
taken, inside that. It rests on one nuclide: it is the simplest rule that
fits, not one a publication states. 233Np (229Pa on a branch of 0.001 %)
still wants something between this rule and every way followed (its bone
surface -0.44 % with the rule, +0.19 % with every way).

## Plutonium in the workers' viewer: three details (2026-11-26, evening)

OIR Data Viewer: nuclides at its four figures in e and every organ dose
422 → 457 of 572, none lost; 46 move, all nearer. Nuclides whose organ doses
are more than 0.2 % (rms) off 22 → 12: four strontium isotopes (the public's
rubidium), five of antimony, 197mPb, 182Ir and 228Ra. The annex of
Publication 158 has no plutonium and does not move. Printed coefficients that round to the
printed value 99.2 → 99.3 % (two more, none fewer).

- **Plutonium's rates are the five figures of Publication 141 Table 18.6**
  (elements.json; the Part 2 draft's Table 22.3 has three). The adult's, and
  every age where the draft has one rate for all ages. 239Pu was 0.20 % low
  in every soft tissue, 0.22 % high in red marrow, 0.20 % in the testes and
  0.16 % on bone surfaces, and exact in the ovaries: the draft's 0.125 to
  trabecular surface is 0.12474, its 0.00027 to the testes 0.0002695, its
  0.000127 out of ST2 0.0001266, and its 0.0000847 to the ovaries is the
  same number. 238Pu, 239Pu, 240Pu, 241Pu and 242Pu now agree to four figures
  in every organ. The other actinides' table (18.9) has three figures, as
  the page has, and 241Am was exact already.
- **Plutonium as a progeny: what leaves the tissues returns by Blood 1
  alone** (progeny.json, the actinide set; progeny103.js: a `remove` of one
  transfer). Para 567 takes out "the transfers from blood to ST0" and adds
  0.33 d⁻¹ from Blood 1 to ST0, 30 % of what leaves Blood 1. The page had
  taken out Blood 0's and kept Blood 2's 28.95 d⁻¹, so that ST0 took 49 % of
  recycled plutonium, and the tissues without a compartment of their own
  were 1.0 to 1.7 % above the viewer after 238Np, 238Am and 236Np and 0.3
  to 0.8 % after 242Cm, 238Cm and 240Cm. With Blood 2 to Blood 1 at 96.5
  and none to ST0 (28.95 is 30 % of 96.5: the same share, once) they are
  within 0.02 %. Blood 2 to ST0 taken out without the 28.95 going to
  Blood 1 puts e 4 % low; no path from Blood 1 to ST0 leaves 0.6 % (rms).
- **The skin and spleen of americium, curium, californium and plutonium as
  progeny take up at round rates.** Para 566 gives the skin its mass
  fraction of what ST1 and ST2 take (0.06) and the spleen a third of that.
  Those are 0.12816 and 0.04272 d⁻¹ for americium and curium, 0.06954 and
  0.02318 for californium, 0.0024967 and 0.00083222 for plutonium. The
  viewer has 0.13 and 0.043, 0.070 and 0.023, 0.0025 and a third of it:
  after 241Pu (the dose is its 241Am's) skin and spleen were 1.30 and 0.64 %
  low, after 249Bk (its 249Cf's) the skin 0.54 % low and the spleen 0.74 %
  high -- the signs of the rounding, each way. Three figures leave them as
  they were. Berkelium keeps the shares (0.004656, 0.001552): with 0.0047
  and 0.0016 the spleen after 247Cf is 0.7 % high. Nothing shows for
  einsteinium, fermium, neptunium, protactinium or actinium, which keep the
  shares. So the numbers are as found, element by element, and no rule says
  how many figures an element has.

Left in the viewer: antimony (125Sb's effective dose 0.6 % above it,
growing with the half-life; the annex agrees with the page, so the workers'
model differs), 197mPb (spleen), 182Ir (thyroid), 228Ra (0.3 %), 233Np.

## The viewer's last four: antimony, 197mPb, 182Ir, 228Ra (2026-11-26, night)

Three of them are differences between the models for workers and for the
public, which the page follows; the annex agrees with the page in all three
to 0.02 % at every age. Help says so (its comparison with the viewer, made
by the private help-checks tool). No engine or data change.

- **Antimony.** Publication 137 Table 3.3 has every rate the page has, but
  its note on Table 3.2 absorbs antimony secreted into the gut again at the
  workers' reference fA, 0.05. The page takes the highest fA for the public,
  the 0.1 of antimony in food (OPTIONS103.secretionFA 'max'), as the annex
  shows. With 0.05, 19 of the 20 antimony isotopes agree with the viewer to
  four figures and 131Sb within 0.03 % (125Sb was 0.62 % above it in every
  tissue, the colon less for the short-lived ones). Polonium (0.5 for the
  public, 0.1 for workers) has no secretion that it matters to; mercury's
  0.1 for workers makes 197mPb worse.
- **197mPb and 195mPb.** Mercury formed from lead has a model of its own
  for workers (Publication 137 para 479: plasma cleared at 16.636 d⁻¹, its
  "h⁻¹" a misprint, 35 % to the kidneys, 20 % to the liver, 3 % to red
  marrow, 0.6 % to the spleen ...). The page has the public's inorganic
  mercury with the tissues read off the annex. With para 479's model the
  viewer's 197mPb comes within 0.2 % (rms 0.60 → 0.16 %), but for the
  kidneys (+0.77 %, perhaps thallium's model); 195mPb 0.16 → 0.05 %.
- **182Ir.** Thyroid 2.2 % and salivary glands 1.1 % below the viewer, the
  gut walls up to 0.8 % above: rhenium (182mRe) reaching blood and osmium
  in the gut. Not found: the workers' rule for rhenium (para 395:
  technetium as a member of ruthenium chains) is what the page does already,
  technetium, ruthenium and osmium are exact in the viewer by themselves,
  and none of these moves it: osmium's or rhenium's fA for secreted
  activity, progeny formed in the gut at the parent's fA, rhenium formed in
  osmium's soft tissue in technetium's pools of the same name (2.6 % off).
  A single rate that fits half of it: technetium's uptake into the thyroid
  5.6 % higher, which no publication gives.
- **228Ra: a gap of the page.** The annex asks the same as the viewer: the
  tissues in "Other" (muscle, brain, bladder and gut walls, thyroid) 0.39 %
  lower for adults, 0.13 % at 1 year and 0.27 % at 5, none at 3 months, 10
  and 15 years; skin, spleen, kidneys, liver, marrow and bone exact. Only
  with radium in blood at once (injection, ingestion, Type F; Type M not),
  and only after 228Ra: 228Ac, 228Th, 232Th and 224Ra taken in agree with
  the viewer within 0.12 %. So it is what actinium and thorium formed from
  radium in the body do in the first days. Of the soft-tissue dose three
  quarters is 224Ra's chain, and thorium returning from radium's bone
  volumes at the turnover rate carries most of it. Excluded (each moves it
  otherwise or not at all): the progeny's adult age, steps of age held all
  the way, every rate of radium's, actinium's and thorium's models alone
  (the best leaves half), the turnover rates by age, actinium or thorium
  formed in the parent's pools in their own, thorium in a foreign pool to
  blood at once (the right tissues, but not the zeros), thorium and
  actinium in their own bone volumes, actinium's 1.386, the carves of skin
  and spleen, the rules for each member's rest of the body. The ages where
  nothing is asked are those where radium's uptake into ST0 is low (0.33,
  0.59, 0.35 of the adult's at 3 months, 10 and 15 years; 0.73, 0.80 and 1
  where it is asked): the next place to look.

## Silver's soft tissue, yttrium's children, an isotope's own compartments (2026-11-26, late)

Against the annex: 35 nuclides move, all nearer; organ doses within 0.1 %
98.8 → 99.3 %, more than 0.2 % off 1,221 → 613 (more than 0.5 % off 14 as
before). OIR Data Viewer: 91Sr to its four figures (457 → 458 of 572).
Printed coefficients that round to the printed value 99.3 → 99.2 %: one
value crosses, 110mAg inhaled as Type F at 5 years, 7.549E-9 → 7.550E-9
for the printed 7.5E-9, while the annex's 110mAg comes six times nearer.

- **Silver goes from blood to ST0 and ST1 at 12.84 d⁻¹** (elements.json),
  21.4 % of the 60 d⁻¹ that leaves Blood 1, with Liver 1 50 %, kidneys and
  each bone surface 2 % and Blood 2 1.2 %: a hundred per cent together (the
  0.13 to the bladder besides). Publications 151 and 158 print 12.8. 111Ag,
  which has no progeny, was 0.2 % low in every soft tissue at every age and
  0.05 % high in liver and kidneys; a single-rate fit gave either ST1's
  inflow +0.3 % or its outflow −0.4 %. The inflow moves all 14 silver
  isotopes nearer, the outflow 6 (113Ag stays at 0.06 %). Scanned: 12.835,
  12.84, 12.845 for both pools give rms 0.0142, 0.0132, 0.0149 % over every
  silver organ dose; none is now more than 0.1 % off (1,541 were).
- **Yttrium's rates out of blood before adulthood are all the adult's x 2/3
  at 3 months and x 5/6 from 1 to 15 years** (elements.json), as ST0 and
  ST1 already were. Table 16.3 prints 1.11 and 1.38 to Liver 0 for 1.1067
  and 1.3833, the kidneys and SI contents alike, the bladder 2.08 for 2.075.
  91Y's liver and kidneys were 0.25 % above the annex at 3 months and 0.25 %
  below from 1 to 15 years, exact for adults; now within 0.02 %. 91Y 0.063
  → 0.009 % rms, 90Y 0.054 → 0.007, 88Y, 93Y and the rest, and 90Sr through
  its 90Y 0.024 → 0.010.
- **A compartment of a progeny's own element is its own** (model103.js,
  placeSpec): an identify entry without an element ("ST1": null) applies to
  other elements' compartments only. The strontium set sends yttrium formed
  in strontium's ST0-ST2 to blood (Publication 134 para 483), and the
  unkeyed entries sent 91Y formed from 91mY in yttrium's own ST1 (leaving
  at 0.0019 d⁻¹) to blood too. 91Sr's soft tissues were 0.1-0.3 % below the
  annex at every age and its liver, kidneys and bone above; 91Sr 0.097 →
  0.010 % rms, and in the viewer 0.158 → 0.000. Nothing else in either
  reference moves. (It first looked like "strontium's ST1 is yttrium's
  ST1": taking the null out did the same, and only a comparison of the two
  assembled systems showed which compartment had changed.)

Still open: 228Ra (the section before) and 224Ra (soft tissues 0.1-0.3 %
low at every age), radon, 85Y and 85mY (brain 0.2-0.3 % low at 1 to 10
years by ingestion), 93Zr's kidneys at 1 and 5 years, 81Sr at 3 months.

## Carbon's organic tissues, zirconium's and niobium's children, phosphorus adult from 25 (2026-11-26, night)

Against the annex: 18 nuclides move, all nearer; organ doses within 0.1 %
99.4 → 99.6 % (more than 0.1 % off 3,704 → 2,557, more than 0.2 % off
613 → 597), effective doses more than 0.1 % off 29 → 18. The printed
tables and the OIR Data Viewer (adults) do not move.

- **Carbon's rates from the tissues of organic carbon to blood are the
  adult's x 4, 2.5, 2.5, 2 and 1.2 before adulthood** (elements.json), the
  factors of Publication 158 para 254 that the rest of the generic model's
  rates to blood (the CO2 submodel's tissues, the bone surfaces) already
  had. Table 6.3 prints 0.0248 and 0.0119 from the long-term tissue at 1
  and 15 years for 0.02475 and 0.01188, and from the short-term tissue 0.37,
  0.185, 0.111 for 0.3696, 0.1848, 0.11088 (to Blood) and 0.277, 0.173,
  0.139, 0.0832 for 0.2772, 0.17325, 0.1386, 0.08316 (to Blood 1). Its rate
  to the right colon is not one to blood and stays 0.0693 at every age, as
  printed; methane's stay the same at every age (para 259). Every tissue
  after 14C taken in as organic carbon was 0.11-0.13 % below the annex at
  1, 5 and 15 years and 0.03 % at 10; 14C 0.059 → 0.010 % rms, carbon's
  organ doses more than 0.1 % off 754 → 20 (none of 14C's).
- **Zirconium's and niobium's rates out of blood before adulthood follow
  the rule of Publication 158 paras 366-367 and 373-374** (elements.json):
  to the bone surfaces the adult's x 1.5 at 3 months and x 1.25 from 1 to
  15 years, to every other place the adult's x (1-B)/(1-A), with A the
  adult's share of the outflow from Blood 1 that goes to bone (zirconium
  0.75 of 5 d⁻¹, 0.15; niobium 0.24 of 8 d⁻¹, 0.03) and B the share at the
  age: x 0.911765 and 0.955882 for zirconium, x 0.984536 and 0.992268 for
  niobium. Tables 17.2 and 18.2 print three figures (zirconium's kidneys
  0.0114 and 0.0119 for 0.011397 and 0.011949, its bone surfaces 0.563 and
  0.469 for 0.5625 and 0.46875). Yttrium's 2/3 and 5/6 of the section
  before are the same rule with A = 0.4. 93Zr's kidneys were 0.26 % below
  the annex at 1 year; now within 0.03 % in every organ (0.063 → 0.006 %
  rms). The zirconium and niobium nuclides' organ doses more than 0.1 % off
  273 → 4: those four are the bladder wall at 3 months after 87Zr and 90Mo
  inhaled as Type F, 0.2-0.27 % low, which the rates do not touch.
- **Phosphorus has its adult values from 25 years** (elements.json:
  adultAge and the systemic model's last age 9125 d), as calcium, whose
  skeletal model it shares: its deposition on the bone surfaces is
  calcium's x 0.8 at each age, translocation and removal calcium's
  (Publication 158 para 269). 33P taken in at 15 years had its bone surface
  and red marrow 0.10-0.13 % below the annex and liver and kidneys 0.13 %
  above, every route; now within 0.03 % (33P 0.060 → 0.039 % rms;
  phosphorus's organ doses more than 0.1 % off 158 → 14, none more than
  0.2 %). 32P's bone and liver come as near, but its soft tissues at 15
  years go from 0.02 % high to 0.05-0.06 % low and the extrathoracic
  airways from 0.06 to 0.12 % high (0.031 → 0.033 % rms); 33P's soft
  tissues at 15 years are left 0.03-0.07 % low. Each
  of the other elements of the annex whose adult is from 20 years was
  tried at 25 against it: none moves nearer (cobalt, caesium, iron, iodine,
  iridium, technetium and others hundreds of organ doses away), and silver,
  sulphur, selenium and polonium do not move at all.
- Calcium and the other alkaline earths were looked at for the same rule:
  their tables already have (1-B)/(1-A) with A = 0.25 to three or more
  figures (1/3, 11/15, 4/5, 44/75, 26/75), and the few rounded ones (calcium
  to ST0 5.1 and 3.02 at 10 and 15 years for 5.104 and 3.016) are kept: all
  of calcium's rates worked out move 41Ca, 45Ca and 47Ca away from the annex
  (organ doses more than 0.1 % off 416 → 460). 41Ca's 0.13 % at 3 months,
  the same in every organ, is what the steps leave ("Steps of one day for
  calcium, polonium and zinc": 41Ca's fits 1.5 days, not one).

224Ra, looked at and left open: every tissue of "Other" 0.10-0.15 % low
(muscle, brain and bladder wall up to 0.3 % at 3 months), kidneys and
spleen 0.1 % high, at every age and in the OIR Data Viewer alike; 212Pb and
212Bi taken in themselves are exact, 226Ra too, 228Th shows 60 % of it.
So it is in how radon-220's short-lived progeny are placed when formed in
radium's soft tissues (56 s: 97 % of it decays where it is formed, where
222Rn mostly leaves). Not it: polonium there in polonium's Other, so lead
in its ST1 (+27 % in soft tissue); lead in lead's pools of the same name
(+14 %) or in its ST0 (soft tissues right, testes −0.9 %, spleen −0.25 %,
228Th and 228Ra 5-12 % off); the shadows counted in each progeny's own
Other (+3.7 %, testes −25 %); lead's age-specific ST0 rate for its
unidentified pools (kidneys +0.9 % at 3 months); any single rate of radon,
lead, bismuth or thallium as radium's progeny (the best leave 0.056 % rms
of the 0.072 asked).

Still open: 228Ra and 224Ra, radon, 85Y and 85mY (brain 0.2-0.3 % low at
1 to 10 years by ingestion), 81Sr at 3 months, 87Zr's and 90Mo's bladder
wall at 3 months, 45Ca's soft tissues at 15 years (0.11-0.15 % low).

## The one-day steps end at 1 year of age (2026-11-26, night)

Against the annex: 5 nuclides move, all nearer (41Ca 0.054 → 0.025 % rms,
208Po and 209Po 0.015 → 0.005, 45Ca, 210Po); organ doses more than 0.1 %
off 2,557 → 2,287, effective doses more than 0.1 % off 18 → 16. Nothing
else moves, in the printed tables or the OIR Data Viewer either.

- **The steps of one day for calcium and polonium last until the child is
  1 year old, for zinc until 5, and the steps of all follow**
  (`OPTIONS103.shortSteps` `until: 'age'`; solve.js takes `dose.firstStep`
  until `dose.firstUntil` days after the intake, then `dose.step`). The
  section "Steps of one day for calcium, polonium and zinc" found the one
  step that fits each case at 3 months: 1.0 d for 47Ca, 1.4 for 45Ca, 1.5
  for 41Ca, the longer the half-life the more of the later steps showing.
  With one-day steps to the end every tissue of 41Ca at 3 months was
  0.09-0.13 % below the annex, 45Ca's 0.05 %, and 208Po and 209Po inhaled
  as Type S 0.12-0.13 % in the extrathoracic airways and the remainder;
  switched at 1 year of age, all are within 0.02 %. Switched a year after
  the intake instead, 65Zn at 3 months and 1 year comes out up to 0.05 %
  high; switched by the age, within 0.03 %.
- 85Y, 85mY and 87Y swallowed (looked at, left open): the brain, salivary
  glands, thyroid and extrathoracic airways 0.1-0.3 % low at 3 months to
  15 years, none for adults; the yttriums whose progeny is not strontium
  are exact. The head organs' dose is mostly the strontium formed in the
  gut and absorbed (51-89 % by age); the ask is 0.1-0.4 % more of it, and
  neither strontium's absorbed fraction nor the transit times change by
  age the way it does.

Still open: 228Ra and 224Ra, radon, 85Y, 85mY and 87Y swallowed, 81Sr at
3 months, 87Zr's and 90Mo's bladder wall at 3 months, 45Ca's soft tissues
at 15 years (0.11-0.15 % low).

## Calcium, phosphorus and lead: more of the children's rates worked out (2026-11-26, night)

Against the annex: 16 nuclides move, all nearer; organ doses more than
0.05 % off 8,585 → 6,204, more than 0.1 % off 2,287 → 1,941; within 0.1 %
99.6 → 99.7 %. The printed tables and the OIR Data Viewer do not move.

- **Calcium's rates from blood to its soft tissues and excretion, and from
  ST0 back to blood, are the adult's x (1-B)/(1-A)** (elements.json), A =
  0.25 and B = 0.75, 0.45, 0.40, 0.56, 0.74, as radium's and barium's.
  Table 9.2 rounds ST0's outflow (0.967, 2.13, 1.7, 1.01 for 0.9667,
  2.1267, 1.7013, 1.0053) and blood to ST0 at 10 and 15 years (5.1, 3.02
  for 5.104, 3.016). 45Ca at 15 years had every soft tissue 0.09-0.15 %
  below the annex; now within 0.01 %, 41Ca and 47Ca within 0.04 % at every
  age, and none of calcium's organ doses more than 0.1 % off (166 were).
  The blood's outflows worked out alone moved the three away (the section
  before last); ST0's outflow with them is what the annex has. Strontium's
  and barium's ST0 outflow worked out the same way move 89Sr, 133mBa and
  135mBa away: they keep the printed figures.
- **Phosphorus's children's rates are worked out by para 269**: to the
  bone surfaces calcium's deposition x 0.8 (calcium's rate / 15 d⁻¹ x 0.8 x
  phosphorus's 40 d⁻¹, i.e. calcium's rates x 32/15: 17.07 to the cortical
  surface at 15 years for the printed 17.1), to every other place the
  adult's x 0.5, 0.8, 0.85, 0.69, 0.51 (B = 0.8 x calcium's, A = 0.2: 7.024
  to ST0 and ST1 at 10 years for 7.02). The adult's stay as printed
  (Publication 134's 4.44 and 3.56; calcium's x 32/15 there, 4.437 and
  3.563, put the adult's bone surface 0.04 % low). 32P and 33P 0.033 and
  0.039 → 0.014 and 0.015 % rms; phosphorus's organ doses more than 0.05 %
  off 611 → 2 (bone surface and red marrow at 5 and 10 years were 0.08-0.09
  % off, 32P's extrathoracic airways at 15 years 0.12 %).
- **Lead's rates from blood to the red cells and to ST0 are worked out**,
  with lead's A = 0.125 and B = 0.375, 0.225, 0.20, 0.28, 0.37 (the bone
  surfaces' share of the 70 d⁻¹, as the halves of the tenth step give it):
  23.04 and 20.16 to the red cells at 10 and 15 years for the printed 23.0
  and 20.2, 18.235 and 15.955 to ST0 for 18.2 and 16.0. 212Pb's soft
  tissues were 0.08 % low at 10 years and 0.10 % high at 15, its bone
  surface the other way; eleven lead nuclides come nearer and none goes
  away (212Pb 0.045 → 0.014 % rms, 209Pb, 205Pb, 211Pb, 214Pb), and none of
  lead's organ doses at 10 and 15 years is more than 0.1 % off (120 were).
  Its other rates keep the printed figures because the annex has them so,
  rate by rate: the kidneys' worked out (2.016 and 1.764 for 2.02 and 1.76)
  put 212Pb's kidneys 0.11 % low at 10 years and 0.14 % high at 15 and move
  202Pb, 205Pb and 210Pb away; ST2's (0.1152 and 0.1008 for 0.115 and
  0.101) put 205Pb's muscle 0.07 % high at 10 years and 0.08 % low at 15;
  the excreta's move 205Pb away; the liver's and ST0's outflow make no
  difference. Why these two and not the others is not known: Table 29.2
  rounds them all alike, and the tables before it (Publication 67) were not
  at hand.

Still open: 228Ra and 224Ra, radon, 85Y, 85mY and 87Y swallowed, 81Sr at
3 months, 87Zr's and 90Mo's bladder wall at 3 months, 133Ba at 1 year
(every organ 0.05-0.14 % low; 226Ra and 90Sr exact there).
