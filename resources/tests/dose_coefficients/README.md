# Tests for dose_coefficients.html

| File | What it proves | Needs |
| --- | --- | --- |
| `test-engine.mjs` | The engines in Node: decay data add up, beta spectra integrate to their mean energies, the S coefficients equal brute-force PCHIP, the Pu-239 alpha self-dose is 20·E/M, the first-year weight, deposition, catalogues, chains, the detriment-adjusted risk coefficients of Publications 60 and 103 recalculated (Tables B-20, 3, 4; A.4.1, 1) and applied to a uniform dose, radon and thoron in homes against Publication 158 (Tables 32.7, 32.8, C.7–C.9), pinned results; then the coefficients against the ICRP's own | `local/` for the comparisons |
| `test-ui.py` | The page in headless Chrome: no script error, the tab icon (its SVG, PNG and touch icon decode; the kvot mark's three tones only), catalogues, every (i), a calculation in each system and an injection, every tab draws (the charts in either theme, with an opaque hover box and no white band at the pointer; the model with the body beside it, numbered alike and lit together; an arrow and its row of the transfer table lit together, and a box with its transfers in and out; after a run, Show fills the boxes as buckets of the activity in the body or of the effective dose (received or its rate, from the member or the whole chain) over time, with what is not drawn listed beside them and the drawing staying put as the time moves; the Risk tab's recalculated Tables 1 and 3 and the nominal detriment of a calculated intake; Radon at home for both gases, recombining at once when F changes), the nuclide field's own suggestions (under the field, keys, reopening), a disabled route that just looks disabled, progeny models of the OIR sections in the chain and model tabs, a link calculates on load, no sideways scroll on a phone, the full window (no site header or footer) by its button, kept for the next visit | a server and Chrome (below) |
| `test-buckets.mjs` | The page's worker in Node over one nuclide of every element and some long chains, each route, both systems: the places the worker sums each member's activity by add up to its whole-body activity, the effective dose by place adds up to e(t) and to the coefficient, and every place holding activity or dose is a box the Model tab draws or one it lists beside them (the airways, the mouth and oesophagus, where a progeny is formed outside its own model). `--quick`: a dozen cases, seconds; otherwise about five minutes | nothing |
| `test-ensdf.mjs` | The ENSDF processor (`resources/js/dose/ensdf-*.js` with `beta-spectrum.js` and `atomic-relax.js`) on ICRP 107's own inputs, run as EDISTR04 ran it (`ensdf-icrp107.mjs`), against ICRP 107: every beta branch's shape and mean energy against EDISTR04's printout; alpha, recoil, annihilation, gamma, conversion-electron, X-ray and Auger energy per decay against ICRP-07.RAD; daughters and branching against the index. About 3 s | your copy of ICRP 107's supplementary data and `local/eadl1991` (below) |
| `test-decay-data.mjs` | The decay data the page offers besides each system's own (`resources/data/dose/ensdf/`), read as the page reads them, in both systems: every name of the system's own data finds its state (but IT isomers under a minute), Ta-178's swapped names pair by half-life, every isomer a record decays to has a record, the catalogues lose nothing, and seven coefficients stay within 1–3 % of those with the system's own data. About 3 s | nothing |
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
