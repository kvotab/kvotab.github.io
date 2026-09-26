# Tests for FARF31.html

Two of them. `test-model.js` is the calculation and the file formats and needs
only Node; `test-ui.py` is the page in headless Chrome.

    node resources/tests/farf31/test-model.js [--verbose]
    F31_HTTP_PORT=8794 F31_CDP_PORT=9294 python3 resources/tests/farf31/test-ui.py

Both exit 0 when every check passes. For the browser test, serve the repository
and start Chrome first (check the ports with `lsof -nP -iTCP:<port> -sTCP:LISTEN`;
other sessions use them too, and a server that fails to start looks like one
that works):

    python3 -m http.server 8794 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      --headless=new --remote-debugging-port=9294 --no-first-run \
      --user-data-dir=/tmp/f31test --disable-gpu about:blank

## What test-model.js checks, and against what

**Closed forms.** Without matrix interaction the response is the inverse
Gaussian of advection and dispersion with flux conditions, times e^(−λt), at
Pe from 0.5 to 10^5; under plug flow into an infinite matrix it is the
classical solution k/(2√π u^(3/2)) exp(−k²/4u), u = t − t_w, k = F√(D_e R),
and at Pe = 10^6 the page comes within 10^-3 of it; at finite Pe with an
infinite matrix the reference is the subordination integral
∫ IG(u) K(u, t − u) du by adaptive Gauss–Kronrod. The saddle-point inversion
is held to 10^-9 on all of these (it reaches 10^-12 and better); Talbot's
fixed contour and de Hoog's method to what they can do. The derivatives h′ and
h″ used for the interpolation are checked against the analytic ones.

**Sorption on the fracture surfaces**, the page's addition (K_a, R_f = 1 + K_a a_w).
Without a matrix the transform is H(R_f(s + λ)), so the response is
h(t/R_f)/R_f · e^(−λt), the inverse Gaussian stretched; under plug flow into an
infinite matrix it is the classical solution delayed by R_f t_w, and nothing
arrives before; chains whose members share R_f, R and D_e factorise with
Bateman as below; the mass balance holds with a different K_a per member. A
chain under plug flow whose members the fracture holds back differently has no
single delay and is refused.

**Chains.** When every member has the same R and D_e the response factorises,
h_ij(t) = h(t)·B_ij(t) with B the Bateman solution; checked without a matrix
(h the inverse Gaussian) and with one (h computed for a stable nuclide), for
distinct, close (3000 and 3000.0001 years) and equal half-lives, where the
divided differences have coinciding points; also with fracture sorption. The
transfer matrix is also checked against TR 90-01's recursion itself (Appendix C,
Proposition 3), written out again here, at four complex s with
element-specific D_e, and with the fracture term added (F_k = R_f,k(s + λ_k) +
a_w D_e,k h_k tanh(h_k x_0), the parent's term R_f,i−1 P_i−1,j,k) at five s with
a different K_a per element.

**Mass balance.** T_11(0) + T_21(0) = 1 with a stable daughter; the integral
of every computed response equals T_ij(0); a long constant release reaches its
rate times T(0); a 0.001-year pulse of one mole gives the unit response.

**The 40-digit solution.** `ref/mpmath-ref.json` is written by
`gen-mpmath-ref.py`: TR 90-01's recursion in mpmath at 40 digits (with the
fracture term above for the case with K_a), inverted by mpmath's Talbot
routine, the release from the step and ramp responses summed over the kinks of
the piecewise-linear input (exact for such an input). It shares no code with
farf31-model.js. Its cases are made up: `single`, `pulse`, `elem` and `chain`,
at the times of the original program's out.ts and out.response for them;
`fsorb`, a chain with sorption on the fracture surfaces and element-specific
D_e; and nine tubes `tail-Pe-C` with a sharp front and a long slow tail (a
stable nuclide, Pe 30, 100 and 300, a matrix that holds C = 0.1, 1 and 10
times the water it faces and fills over 12 500 a, 250 travel times, under a
constant release for 2·10^4 a; the working precision grows with Pe, since the
transform reaches e^(Pe/2) at its branch point). `tail-30-1` is the case whose
step input once gave an all-zero release. Each carries its input. The page
agrees with it to 2·10^-8 or better (typically 10^-10) over values above 10^-6
of each peak; for the tails, 2·10^-8 above 10^-4 of the peak and 10^-10 of the
peak in absolute terms up to the run's end (late in a tail after a step down
the release is the part of a response held to 10^-13 of its own peak); T(0) to
10^-12; every response's integral to T(0) within 10^-7, and the run's own mass
balance finds nothing. `gen-mpmath-ref.py --only 'tail-*'` recomputes a family.

**Robustness.** The real axis of the tail case: the tilted mean positive and
falling throughout (next to the rightmost singularity rounding once made it
negative, and every saddle search stopped on it), a saddle at every time from
10 to 10^5 a. The mass balance: a response halved, or ended at 300 a, is caught
(and one ended early is held to what has left by then, by de Hoog's inversion
of T/s); a response grid far too coarse to hold the response is retried and
then named in the run's notes. The automatic end follows a release that lasts
past 10^9 a, and a release that never ends stops at 10^12 a with a note. Plug
flow: a matrix that fills at once makes a spike 0.4 a after a delay of 120 a
(found, and it carries T(0)); a daughter born near the outlet arrives within a
hair of the delay (kept as a point mass). Four sharp-front cases, Pe 1000 to
10^4, two of them chains whose daughter the matrix holds back far longer than
its parent: every response carries what leaves the tube, and agrees with de
Hoog's method at twice its usual terms to 10^-7 above 10^-4 of each peak.

**The original program's outputs.** When the reference cases are on the
machine (`$FARF31_REF`, default `~/Downloads/Farf31-SKB-new/reference-cases`;
made-up inputs and the original FARF31 1.2's outputs, not in the repository),
the page reproduces those outputs: the unit responses of all seven cases
(those carrying more than 10^-10 of a pulse) to 5·10^-3 above half their
peaks, and the releases of `chain-dense`, `pulse-nozero` and `elem-ramp` to
5·10^-3 above half of each peak and 2·10^-2 above 10^-2 of it.

**Files.** The made-up case in `fixture/` read, written and read back;
DE_XX per element; the page's own KA_XX (read per element key, 0 where absent,
written only when some K_a is not zero, since it goes beyond FARF31's format);
F in place of TW or ASPEC; the .prm's bare algorithm line and RHOP; errors
that name the line; out.ts and out.response in the
original's layout (header lines, E12.6 and E20.4 columns); the Bq/a conversion
with FARF31's constants (N_A = 6.022045·10^23, a year of 365.2422 days, found
by fitting the reference outputs' Bq/a over mol/a to seven digits); the shapes;
every built-in example runs; a negative travel time gives an empty output.

## What test-ui.py checks

That a first visit runs the default example in the worker without a script
error; the build stamp at the foot of Help; FARF31's in.dat, in.par, in.ts and a
casename31.prm dropped together by a trusted drag and drop
(`Input.dispatchDragEvent`) become the case and run, and the worker's result
equals the model run on the page; the release and response plots, the table,
the CSV, out.ts, out.response, in.dat/in.par/in.ts and the case file (downloads
captured by stubbing `URL.createObjectURL`); the page's own out.ts dropped back
compares to its rounding; a Kd edit on one uranium isotope moves the other,
and so does a K_a edit, which shows in the side panel, the Summary's R_f column
and the KA_ lines of the in.par written; a bad series line is refused; a shape
builds a series; the (i) panel opens and closes; an example loads from the
select; the tail case `tail-30-1` dropped as a case file runs to its release
(its step input once gave zeros), without a warning, and the Summary shows its
response carrying what leaves the tube by its last time. With the reference cases present, the chain case dropped on the page
gives the 40-digit solution at the original's times, and `chain-dense` dropped
with its out.ts is compared nuclide by nuclide and reproduces it.

Two things the browser test learned: the (i) panel slides in for 140 ms, so a
click on its × straight after opening misses; and out.ts rounds times as well
as rates to seven digits, which moves a rate on a rising edge by a few 10^-6.
Close panels with clicks, not a CDP Escape (headless Chrome 153 can hang).
