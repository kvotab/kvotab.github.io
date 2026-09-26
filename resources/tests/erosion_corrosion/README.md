# Tests for erosion_corrosion.html

Two of them. `test-model.js` is the arithmetic and the file readers and needs
only Node; `test-ui.py` is the page and needs the server and browser of
`../rb/README.md` (other ports with `EC_HTTP_PORT` and `EC_CDP_PORT`).

    node resources/tests/erosion_corrosion/test-model.js [--verbose]
    python3 resources/tests/erosion_corrosion/test-ui.py

Both exit 0 when every check passes.

SKB's code test case is not in the repository (it is theirs, not ours to
publish). With `TestCaseHydro_2_0.xlsx` (SKBdoc 1895160) on the machine,

    python3 resources/tests/erosion_corrosion/make-local-fixtures.py <folder>

writes `local/TestCaseHydro_2_0.csv` (git-ignored), and both tests then run
the checks that need it; without it they skip them and say so.

## What test-model.js checks, and against what

The model has three independent references, and every check is against one
of them rather than against a stored result of its own.

**The code documentation's test case** (SKBdoc 1895157, section 5).
`TestCaseHydro_2_0.xlsx` was built so that the answers can be worked out by
hand: with the SR-Site settings (OldKTH erosion, 25 % dilute time, the
ten-value HSTest table) it must produce exactly 35 failure times -- ten for
hole 1 at 850,000 to 940,000 years in steps of 10,000 (a flow below qlim, so
Qeq = q), ten for hole 2 at 85,000 to 94,000 (above qlim, so Qeq goes as √q),
ten for hole 3 at 900,000 to 990,000 (tAdv = 50,000 with the SR-Site erosion
model) and five for hole 4 at 950,000 to 990,000 (tAdv = 100,000, so only five
sulphide values fail in time) -- and reject 17 holes for stated reasons: 11 by
FPC, 12-16 and 25-33 by EFPC, 17 by fracture length, 18 by T/L, with 19-24
just escaping each criterion. The key outputs of the workbook's Info sheet are
listed in the document and checked one by one. Section 5.7 of the same
document gives the erosion rates of TR-16-11's figure 4-5 at four velocities
and the loss and sedimentation rates of its figure 4-7 at five apertures;
those are held to 4 % and 2 %, which is what reading a log plot allows.

The tests read it as `local/TestCaseHydro_2_0.csv`: the ten columns the
model reads, from sheet Test of the xlsx.

**Several realisations.** The test file is read twice over to check the pooling
of realisations: the rows carry the realisation number, the summary is the
mean over realisations, and identical realisations give identical bounds.

**Closed forms.** The Lambert W function against known values and against
w·e^w = x; Acklam's inverse normal against tabulated quantiles; every derived
constant of the Info sheet (qLim, CorrHoleFact, the effective DR, rRSS_Sed,
SpallingFactor, QeqGeo) against its formula; and single holes through every
buffer model and every option that changes a formula -- pessimistic aperture,
pessimistic geometry, flow averaging, the cubic transmissivity law, the Darcy
and inflow criteria, OKFLAG, initial advection, an unforced rRSS through W.

Then the readers: a ConnectFlow CSV with a BOM and all 29 columns, a PTB
with its comment banner, the two DarcyTools shapes (T/F flags and `Total DHs`
in the `.dtpm`; `iFPC`, porosity and fracture counts in the older CSV, with
the aperture and U0 derived as the 2.0 port derives them), padding to the
layout, an inflow list, a round trip through `toCsv`, and the refusal of a
table without U0 with the header quoted back. And the sulphide tables against
the workbook's HSData sheet to the digit, the generated distributions against
their own quantiles, and the custom-text parser.

## Two mistakes the tests caught, kept as comments in the code

* The NewKTH rim radius uses G/2, and the workbook's cell AB carries that as
  an explicit 0.5 in front of the expression for G. The first version of the
  model dropped it, which put rRSS 2.4 times too far out and every unforced
  erosion rate 55 % too high -- invisible with the PSAR setting "force rRSS",
  and caught only by the TR-16-11 figure values and the Python port's
  SR-Site configuration.
* A Halley refinement of the inverse normal was making it worse, not better,
  because the erfc it leaned on was accurate to 1e-7 and the unrefined
  Acklam value to 1e-9. normInv(0.5) came out as -3.8e-8. The refinement is
  gone.

## What test-ui.py checks

The wiring: that the page loads without a script error and builds one control
per catalogue parameter; that every catalogue parameter, every section heading
of the panel and every result tab's toolbar has its (i), with a topic behind
each slot and every "Read more in Help" link pointing at a heading that exists
(`KvotInfo.audit()`), that no hover tooltips are left on the settings, that the
(i)s line up at the right, and that an (i) opens the panel between the header
and the footer with the title, the value in force and the names of the
parameter, follows a change of the value or of a tab's choice while open,
closes by its ×, by the same (i) and by Escape, and that its Help link opens
the Help tab at the heading; that the code test case, dropped on the panel after
the SR-Site settings are set on it, runs and puts 35 rows, 17 rejected and a
corrected mean of 3.5 in the state, the summary cards and the status line;
that the failure table has the rows in the documented order and sorts; that
the time chart's failed-canister curve ends at the corrected mean and the
distribution plots draw and switch; that the per-hole table pages and filters
to the 17 rejected holes with FPC named on the first; that a parameter change
re-runs and reset puts everything back; that a dropped second file becomes a
second realisation with min/mean/max columns; that a file which is not a
hydro table is refused by name without disturbing the loaded ones; and that
a dropped case file applies its settings and names its unknown key.
