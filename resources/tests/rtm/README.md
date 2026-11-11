# Tests for rtm.html

Five of them:

- `test-model.js` is the mathematics and needs only Node.
- `test-hdf5.py` is the file the page writes and needs Node and `h5py`.
- `test-ui.py` is the page and needs the server and browser of `../rb/README.md`.
- `test-phreeqc.js` is the hand-off to and from PHREEQC, on the page's own PHREEQC (`vendors/phreeqc`, compiled to WebAssembly), in Node.
- `test-phreeqc-ui.py` is that hand-off in the page, with the same server and browser as `test-ui.py`.

```sh
node resources/tests/rtm/test-model.js [--verbose]
python3 resources/tests/rtm/test-hdf5.py
python3 resources/tests/rtm/test-ui.py
node resources/tests/rtm/test-phreeqc.js
python3 resources/tests/rtm/test-phreeqc-ui.py
```

Each exits 0 when every check passes. The two browser tests expect the server on 8765 and Chrome on 9222. When another session has those, start yours on other ports and name them: `RTM_HTTP_PORT=8811 RTM_CDP_PORT=9311 python3 …`.

## What test-phreeqc.js and test-phreeqc-ui.py check

The hand-off is `resources/js/rtm-phreeqc.js`, with PHREEQC passed in as an engine. In the page, the engine is IPhreeqc compiled to WebAssembly (`rtm-phreeqc-engine.js`, run by `rtm-phreeqc-worker.js`). The tests check it against what has to be true, not against stored numbers:

- **A water as a model** (an illustrative groundwater, round numbers) compiles, and rtm.html's own speciation, from the conditional constants alone, lands on PHREEQC's molalities to 1e-8 (2.4e-10 measured). The database's log K, worked back from PHREEQC's activities, is phreeqc.dat's own (10.329 for HCO3-).
- **A run of that model read back through PHREEQC** starts at exactly the water's pH and calcite saturation. With 1.5 mM HCl added, it ends where PHREEQC adding the same acid by itself ends: pH within 3e-4, calcite SI within 6e-4.
- **With 0.4 mol/kgw of salt added instead**, the conditional constants go wrong, and the drift of the activity coefficients says so: 0.48 in log K.
- **Without a water**, the temperature is read from the top of the model text. A water PHREEQC refuses is reported, and the look goes on without it.
- **The built-in model:** the seven species PHREEQC knows are counted; the hydrated electron, the radicals and the surface sites are not; the missing counter-ion is noticed.
- **Activity coefficients that follow the ionic strength** (`ACTIVITY = debye-huckel`): the database's `-gamma` is read (Ca+2: 5 and 0.165), and a database with LLNL's activity model is refused. The text has the water's `TEMPERATURE`, the water in its relations and the database's own log K. Its start, from the page's own activity coefficients, lands on PHREEQC's molalities (5.6e-12; 9.1e-10 while A and B were pure water's, see below). With 0.4 mol/kgw of NaCl added, every species ends within 1e-5 (3.1e-7 measured) of what PHREEQC alone finds; with the constants fixed at the start, MgSO4 ends 89 % off. The PHREEQC tab then says PHREEQC's activity coefficients moved by 0.48 in log K and the model's own stayed within 1e-6 (7e-15) of them. PHREEQC alone also moves the valence states, which the model never does, so the redox species are left out of that comparison: with acid it re-equilibrates a little carbon, 5e-5, whatever the tolerance.
- **Phases kept at saturation**: a phase's reaction is read from the database's PHASES, and the input's EQUILIBRIUM_PHASES with their SI. Phases are refused unless the relations are held exactly. Calcite and a CO2(g) pressure become minerals and pyrite is not carried (it dissolves with electrons); the start, the amounts included, lands on what PHREEQC left (1.4e-9). With acid in, every species and the calcite left end within 1e-4 of PHREEQC with the same phases (2e-5 measured: PHREEQC leaves CO2(g) about 3e-5 off its SI, which the model then holds). The PHREEQC tab finds the water at saturation with calcite and at that CO2 pressure wherever there is any. Comparisons with PHREEQC alone leave out every species of an element kept in more than one valence state, and the redox species, since PHREEQC alone moves electrons between them.
- **The water held exactly** (`EQUILIBRATE = always`, no `kf`): its start, read from the logarithms and totals the solver keeps, lands on PHREEQC's molalities as closely (2.4e-10). With the same acid it ends 7e-5 in pH from PHREEQC alone, where the fast pairs end 3.3e-4 from it. Exactly and as pairs at once is refused.
- **A reactive column against PHREEQC's own TRANSPORT**: acid entering a water at saturation with calcite, 40 cells at a Peclet number of 40 for two pore volumes. PHREEQC runs TRANSPORT; the page runs the model it writes (activities following, relations held, calcite kept at saturation, limited advection). Read PHREEQC's way (its cell is the downstream face half a shift later), the effluent agrees to 0.009 in pH and 0.026 mM in calcium over the whole run, the calcite left to 0.45 %, and the front to a cell (on 80 cells, measured once: 0.002, 0.008 mM and 0.25 %). The engine is loaded afresh first: TRANSPORT applies every reactant numbered as a cell, and a REACTION 1 left from a test above had put acid into cell 1 at every shift.
- **A mineral dissolving at a rate against PHREEQC's KINETICS**: calcite into an undersaturated water at k(1 − SR), PHREEQC with a RATES block, the page with `SR(Calcite)` from `<PHASES>` (log K PHREEQC gives at the temperature). The way to saturation agrees at 100 s to 10,000 s, calcium to 1.3e-5 and pH to 2.3e-6.
- **An exchanger**: Example 11's column water with an `EXCHANGE` of 1.1 mmol/kgw loaded from it. The hand-off writes `X- exchanger` and the species PHREEQC put on it, with the database's `-gamma` when the activity coefficients follow (none when conditional), and the page's start is PHREEQC's exchanger to 6.7e-16. Not held exactly, the exchanger is not carried and the report says so. Then Example 11 itself: CaCl2 through 40 cells for three pore volumes, PHREEQC's TRANSPORT against the page's model of the water (limited advection), read as in the calcite column. The effluent agrees to 0.022 mM in Na, 0.033 in K (peaking at 1.115), 0.017 in Ca and 0.005 in Cl (on 80 cells, measured once: 0.016, 0.017, 0.007, 0.001). The PHREEQC tab loads PHREEQC's exchanger from each water of a run at the run's capacity, and the run's fractions are within 6.8e-9 of it over 150 waters.

  These found that a BASIC `FOR` over an empty range, as `SYS("ex")` gives for a water with no exchanger, spoils the WebAssembly PHREEQC's memory: a later load of the database failed with "memory access out of bounds", three tests on. The punch block jumps the loop when there is nothing to loop over.
- **Redox**: the groundwater, given as an analysis at pe −3, is written as PHREEQC's next step: its couples on one pe (−2.946), sulfide, methane, H2 and Fe(3) tied to the electron with the database's log K at 15 °C, and the page's start is that water to 1e-8 (9e-10 measured) and its pe to 1e-9, in both activity modes. A water given sulfate and sulfide, Fe(2) and Fe(3) at pe 4 settles at pe −3.42, as PHREEQC's next step has it. Held as fast pairs, no couple is tied. Oxygen fed into the groundwater at 1e-8 mol/kgw/s against PHREEQC adding the same in REACTION: through the iron's equivalence point (where the pe jumps from 1 to 10) and past it, every species above 1e-12 within 1e-4 (5.9e-5 measured, Fe+2 at the point itself) and the pe within 1e-4 (2.6e-5). The PHREEQC tab on that run gives each water its pe, with C, Fe and S each one total, and PHREEQC shares the valence states out as the run has them, to 4e-10. Then a pyrite column: oxygenated water into an aquifer with pyrite, calcite and goethite (20 cells, 30 shifts), PHREEQC's TRANSPORT against the page's model of the column water (floor 0, so that oxygen has a species to arrive as): the effluent within 0.0011 in pH, 0.0016 in pe, 1.5e-6 mol/kgw in sulfate and 6e-10 in iron, the pyrite gone from the same 12 cells and 3.4 % less of it left. On 40 cells PHREEQC itself fails ("S has not converged").
- **A surface** (`SURFACE` with `-no_edl`): PHREEQC's Example 8 water, zinc on hydrous ferric oxide's strong and weak sites. The hand-off writes the bare sites and the species PHREEQC put on them as `surface` species, grouped by site in the order the input lists them, with the database's log K (conditional in the other mode), and the page's start is PHREEQC's surface to 1e-8 (1.5e-9 measured; 2.3e-10 conditional: the relations take the database's log K, not one read back off the water, so PHREEQC's own convergence shows). Not held exactly, the surface is not carried and the report says why. Then zinc, 0.1 mmol/kgw in 10 of NaCl at pH 6.5, into 40 cells of the same sites loaded from that water without the zinc, for three pore volumes against PHREEQC's TRANSPORT: the effluent within 0.34 µmol/kgw of zinc and 0.0094 in pH (on 20 cells, measured once: 2.7 and 0.078, all in the front), and after three pore volumes 0.002 µmol/kgw and 5e-5. NaCl, not Example 8's NaNO3: PHREEQC's every reaction step puts the nitrate on one pe with a trace of N2 and O2, which takes protons, and a model whose valence states are kept apart then sits 5e-5 mmol/kgw of zinc off on the plateau; held at one pe (the default) it does not. The PHREEQC tab loads PHREEQC's surface from each water of a run with the run's sites, without electrostatics, and the run's fractions are within 4.7e-9 of it over 150 waters.
- **The double layer** (`SURFACE` as PHREEQC has it by default): Example 8 itself. The hand-off writes `Hfo_psi potential area=600 grams=0.09` at PHREEQC's potential (9.094343 mV), and the page's start is PHREEQC's water, surface and potential to 1e-8 (1.7e-9 measured; 2.3e-10 conditional, `TEMPERATURE` written for the double layer without `ACTIVITY`). PHREEQC's constants are its own, F 96493.5, R 8.31470 and eps0 8.854e-12 (`global_structures.h`), older than CODATA's: with CODATA's the start was 4.7e-5 off, and PHREEQC's `EDL("psi")` is reported with the same F and R. Sites given as `sites=` and loaded from PHREEQC's first water (in NaCl, so that no redox couple moves its reaction step's pH), the potential with them, then the whole speciated: PHREEQC's `-equilibrate` and its reaction step, to 2e-9. The zinc column with the double layer, 40 cells against TRANSPORT: within 0.34 µmol/kgw of zinc and 0.011 in pH, the plateau at pH 6.02 (5.96 without the layer). The PHREEQC tab loads the surface with its double layer, area and grams from the model's potential, and finds the run's fractions within 4.7e-9 and its potential within 4.6e-12 V.
- **SIT** (`ACTIVITY = sit`, `<SIT>`): always on phreeqc.dat with a SIT block of made-up coefficients put in front (PHREEQC reads a database to its first `END`, and phreeqc.dat has one at line 1909: a block appended after it is never read, which is how an early run of this test compared SIT with PHREEQC's Debye-Hueckel and found 0.15 in log gamma; the page's reader now stops there too); and on PHREEQC's own sit.dat (ThermoChimie v12a, never shipped) where it is on this machine, `~/.cache/kvotab-phreeqc/obj/database/sit.dat` from the PHREEQC build or `RTM_SIT_DAT`, skipped otherwise. `KNOBS -convergence_tolerance 1e-14` (1e-12 for TRANSPORT, which does not settle every shift closer): by default PHREEQC's SIT stops at 1e-7 in log gamma. PHREEQC's SIT takes its A at the a(H2O) a calculation starts from (sit.cpp's PTEMP_SIT caches it once a calculation, at calc_rho_0's ah2o_x): 1 for an initial solution, and for a reaction step that of the water it starts from (step.cpp sets ah2o_x from it). The page's A is the water's own (since 2026-11-08; it was at a(H2O) = 1, PHREEQC's initial solutions), so each water here goes through two steps of nothing, `MIX 1` of solution 1 alone, the second starting from the a(H2O) the first gave. The page's coefficients and water activity at PHREEQC's molalities are then PHREEQC's to 6.7e-16 and 1.9e-15 at I = 1.7 (sit.dat: 1 mol/kgw NaCl at 15 C, U(6) carbonate in 3 mol/kgw NaCl, 0.5 mol/kgw NaCl at 60 C, to 4e-15, 5.5e-14 and 2.2e-16, the U(6) water with 20 pairs where its initial solution had 14, the steps having put every couple on one pe). Against the initial solution they are A's part apart, z^2 D (A - A(1)): 3.6e-8 in log gamma for Ca+2, the rest within 6e-16. At 150 C, on the vapour pressure: 1.5e-5 from the initial solution, and 8.8e-12 after the two steps, all of it A at the pressure the hand-off writes, PHREEQC's after the second step, 7e-8 atm above the one that step started at (PHREEQC keeps the highest pressure a water reaches, p_sat a(H2O), and the step takes A at its start): at that pressure 5.3e-16. A third step does not settle it, and a fourth fails to converge at 1e-14. The Jacobian there on the vapour pressure (1 atm given) and above it (10 atm), not at PHREEQC's own pressure, a hair above the vapour pressure, where a difference straddles the corner. The hand-off writes `ACTIVITY = sit`, no a or b, and the database's coefficients between the species written at the water's temperature (`sitParam`, PHREEQC's `calc_sit_param`); the start lands on PHREEQC's molalities to 1e-13 (sit.dat 1.8e-14, 1.1e-13, 9.8e-15; 3.6e-11 at 150 C). The PHREEQC tab on a run adding 1 mol/kgw of salt: PHREEQC's coefficients move 0.15 in log K and the model's own stay within 1.3e-7 of them, all of it A, the tab's waters being initial solutions (3e-14 while the page's A was at a(H2O) = 1). An exchanger in a saline water: its species without a or b, taking their ions' coefficients, the start PHREEQC's exchanger to 1.9e-8. Brine (2 mol/kgw NaCl) into fresh water over calcite, 40 cells, three pore volumes, against TRANSPORT: the effluent within 0.016 in pH and 5 umol/kgw of Ca where the front passes, and at the end pH 8.4903 (sit.dat: 8.2384) within 1e-5. The pyrite column in 0.5 mol/kgw NaCl under SIT: pH 0.0014, pe 0.0019, sulfate 1.5 umol/kgw, the pyrite gone from the same 12 cells, in 3.6 s (the full speciation of every cell took 30 s: the reduced one with V's sums, see test-model.js).
- **A gas phase** (`GAS_PHASE`): ideal gases on phreeqc.dat with the gases' `-T_c`, `-P_c` and `-Omega` and the species' `-Vm` taken out (PHREEQC then holds them ideal and moves no log K with pressure), real ones on phreeqc.dat as it is (Peng and Robinson). Reading: a GAS_PHASE as PHREEQC reads one (fixed pressure by default, -pressure and -volume 1 unless given), a phase's critical constants, GAS_BINARY_PARAMETERS and PHREEQC's own k for water vapour where none is given (calc_gas_binary_parameter). A bubble of ideal gases at 1.1 atm: the start PHREEQC's to 2.8e-10, CO2 added as REACTION adds it to 5e-10 in pH (the water at the bubble's pressure for A and B, as PHREEQC puts it). Real gases at 10 atm: the page's phi and molar volume at PHREEQC's composition (PR_PHI, GAS_VM) PHREEQC's to 4e-15, the start 1.2e-9, CO2 added 8e-9 in pH; the bubble's CO2 2.7e-6 off, PHREEQC's mass of water losing what the CO2 hydrates (the page's kilogram does not). A fixed volume: the start PHREEQC's to 2e-9 ideal and real with `PRESSURE` = the gas phase's (PHREEQC puts the water there); with CO2 added PHREEQC's A, B and, with molar volumes, log K follow the pressure: 2e-5 in pH ideal (0.76 to 1.13 atm), 4.3e-4 real (17 to 20 atm; CO2's dlogK/dP is about 6e-4 per atm). A bubble forming: PHREEQC keeps 1e-25 mol of a gas phase that is not there (MIN_TOTAL), so a bubble is more than 1e-20; the page's event falls between PHREEQC's last step without and first with, the waters within 1e-7 in pH (1e-8 per mmol of CO2, PHREEQC's water mass again). The PHREEQC tab: the run's partial pressures (fugacities for real gases, from the model's own Peng-Robinson) against 10^SI within 1.3e-7 in log.
- **The temperature** (`dH=`, `analytic=`, `TEMPERATURE` a parameter or a table read at the clock): every reaction of phreeqc.dat (368: species, phases, exchange and surface species) has, from its terms as the page reads them (`log_k`, `delta_h` with its unit, `-analytic`, PHREEQC's option prefixes and named expressions), PHREEQC's `LK_SPECIES` / `LK_PHASE` at 0.01, 10, 25, 50, 75 and 90 C to 5.7e-14; reading them found the page's reader taking `Willemite 289` for no phase, so that Willemite's log K went to Sphalerite (a phase's name is the first word of its line, as PHREEQC's read_phases takes it). Calcite and gypsum heated from 25 to 90 C along a table read at the clock, against REACTION_TEMPERATURE in 14 steps: while there is gypsum, log m(H+) 2e-8, Ca 1.2e-7, the minerals 2.8e-7 mol/kgw; the gypsum goes over to anhydrite at 54.3847593 C where PHREEQC's SI(anhydrite) crosses zero at 54.3847595 (bisection); with anhydrite 3.6e-7, 2.6e-6 and 3.4e-6, PHREEQC's kilogram of water 173 ppm heavier for the gypsum's water of hydration. A column of 20 cells held at 10 to 70 C (`TEMPERATURE = Tc`) taking a water of pH 6 over calcite for four pore volumes, against TRANSPORT with `-thermal_diffusion 1e30 0`, which holds each cell at its solution's temperature (step.cpp moves a cell's temperature by 1/tempr of the difference each step); a REACTION_TEMPERATURE 1 left from the batch would be applied to cell 1, so PHREEQC is loaded afresh first. The effluent within 0.003 in pH and 0.015 mmol/kgw in Ca; at the end each cell, the inflow at calcite saturation at its own temperature (the conservative parts of the water are the inflow's everywhere), within 6.6e-6 in pH and 9.4e-6 in Ca: PHREEQC's TRANSPORT is its own batch steady state to every digit, and the page is off by PHREEQC's kilogram of water (calcite and CO2 take water) and, in a temperature gradient, by the limited scheme limiting each species' slope on its own (2e-5 in a cell's Na total; none with upwinding or without the gradient).
- **Solid solutions** (`SOLID_SOLUTIONS`): aragonite and strontianite, phreeqc.dat's, in a water of 3 mmol/kgw Ca and 0.5 Sr. Reading: `-comp1` and `-comp2` first, the options by PHREEQC's prefix rule, and `-tempc` (and `-temp`) as degrees above 25 C: PHREEQC's read_solid_solutions adds 298.15 to them, and the hand-off writes the temperature PHREEQC used. The model written from the water starts on PHREEQC's water and solid to 7.6e-11, ideal and in each of the ten forms PHREEQC takes Guggenheim's parameters in (ss_calc_a0_a1: `-Gugg_nondimensional`, `-Gugg_kJ`, activity and distribution coefficients, a miscibility or spinodal gap, a critical or alyotropic point, Thompson and Waldbaum, Margules), below the gap (2.5e-10), inside it and above it (2e-10), and given at 50 C by `-tempc 25`, at 310 K by `-tempk`, and in a water at 50 C (2.7e-10). That needs the gap where PHREEQC's solve_misc stops, at 1e-6 in the activities: taken on to round-off, the Thompson and Margules starts were 3e-7 and 1.1e-6 off, so the page does that only where the temperature goes with time (see test-model.js). Strontianite added as REACTION adds it, 0.2 mmol at a time to 6: the solid's x_Sr within 3.9e-7 (ideal) and 1.8e-6 (binary), pH 4.9e-6 and 1.1e-6, PHREEQC's kilogram of water growing by what bicarbonate gives up as it goes to CO2 (7.8e-4 mol of water for 7.8e-4 of CO2 formed, ideal, at 6 mmol); the binary one comes to its gap at 0.27104387 mmol and leaves it at 2.40382323, PHREEQC's (by bisection on the amount added) 0.27104445 and 2.40383374: 2.1e-6 and 4.4e-6. The PHREEQC tab: each member's activity in the run, x lambda or the gap edge's, against 10^SI of the pure member, 3e-10 in log over 24 activities, and the members not looked at as pure minerals.
- **Pitzer** (`ACTIVITY = pitzer`, `<PITZER>`): always on phreeqc.dat with a PITZER block of the tests' own in front, round numbers with terms in the temperature, every type of parameter (B0, B1, B2, C0, THETA, LAMDA with a species and itself, ZETA, PSI, MU, ETA, ALPHAS); and on PHREEQC's own pitzer.dat where it is on this machine, `~/.cache/kvotab-phreeqc/obj/database/pitzer.dat` from the PHREEQC build or `RTM_PITZER_DAT`, skipped otherwise. Reading: the options by PHREEQC's prefix rule (`-mac`, `-use_e`), true unless the word begins with f, a parameter given again either way round replacing the first, and `-Aphi`'s values on the lines after it (read_pitzer takes none from the option's own line: a first version of this test gave them there, and so compared no APHI at all). The page's coefficients and water at PHREEQC's molalities are PHREEQC's at I = 4 to 3.6e-15 in log gamma and 8.9e-15 in ln a(H2O), at 25, 70 and 150 C (the last on the vapour pressure times a(H2O)), without the MacInnes scaling and E-theta, and with APHI; on pitzer.dat 5.6e-16 for seawater, 6.7e-16 for a 60 C brine and 8e-15 for one at 150 C. That needed A_phi from the density of water at the vapour pressure times a(H2O): PHREEQC's calc_rho_0 scales the vapour pressure by the water's activity (Raoult), and the molar volumes (phreeqc.dat's and pitzer.dat's) make k_temp work it out again every iteration, so where PHREEQC settles its A_phi is that of the water's own a(H2O), the one the osmotic coefficient gives with that A_phi, an initial solution's as much as a reaction step's (SIT keeps its A from a calculation's first iteration instead, see SIT); without it the brine was 2e-6 off, as z^2. Until 2026-11-08 the page took A_phi after one pass, at the a(H2O) the pure water's A_phi gives: 5e-13 off at 70 C, 2e-13 for the 60 C brine and 1.6e-9 at 150 C, where the water's pressure, and with it the dielectric constant, goes with a(H2O). It now takes the fixed point (one Newton step), and F1 and F2 read the water's pressure there, under APHI too: with the PRESSURE the hand-off writes taken out of the model at 150 C, the page puts the water on the vapour pressure times its own a(H2O), and its coefficients are PHREEQC's to 1.8e-15, with APHI to 7.4e-14 (PHREEQC's initial solution; 2.2e-15 after two MIX steps), where with the pressure left at one atmosphere, as the page had it under APHI, F1 and F2 were 2.5e-3 off. (APHI here is 0.392 -11 0 0.0005: the 1e-4 on T^2 of the 50 C case would make A_phi 9.4 at 150 C, and PHREEQC does not converge.) The hand-off writes `ACTIVITY = pitzer` and each parameter between the species written with its terms, `MACINNES no`, `ETHETA no` and `APHI` where the database says so, and for the MacInnes scaling the B0, B1 and C0 of K+ and Cl- and every parameter of Cl- with the species written; the start lands on PHREEQC's water to 3e-14 (pitzer.dat: seawater 1e-14, the brine over gypsum 2.9e-15, a water with no chloride, scaled by the Cl- it would have, 2.9e-15, the 150 C brine 3.4e-14). At 150 C the hand-off writes a <VOLUMES> after <PITZER>, which the test reads <PITZER> up to. PHREEQC's Pitzer model holds the pe where the water has it unless its PITZER says `-redox` (model.cpp zeroes the pe's column): with 3 mmol of O2 added to the groundwater its pe stays at -3.0000, and with `-redox true` goes to 14.42; the hand-off fixes the electron at PHREEQC's pe, and leaves it free with `-redox`. The PHREEQC tab on a run adding 1 mol/kgw of salt to a 3 mol/kgw brine: PHREEQC's coefficients move 0.25 in log K and the model's own stay within 5.4e-14 of them. On pitzer.dat: NaCl added to a water over anhydrite to 7 mol/kgw against REACTION, calcium within 1.7e-7 and the minerals 1.3e-8 mol, halite forming at 6.09936973 mol for PHREEQC's 6.09936975 (bisection) -- anhydrite, not gypsum, which gives PHREEQC water as it dissolves; and brine into fresh water over calcite (40 cells, 3 pore volumes, I to 2) against TRANSPORT, the effluent within 0.013 in pH and 4 umol/kgw of Ca, the end within 2.4e-5 in pH, PHREEQC 2.2 s and the page 1.7 s.
- **A and B at the water's activity**: PHREEQC works the density of water out at the vapour pressure times a(H2O) (calc_rho_0), and with phreeqc.dat's molar volumes k_temp does so again every iteration, so its Debye-Hueckel A and B are the water's own (SIT's A0 is kept from a calculation's first iteration: at a(H2O) = 1 for an initial solution, which the page's SIT matched until 2026-11-08, and for a reaction step at the a(H2O) of the water it starts from; the page's SIT now takes A at the water's own, see SIT above). PHREEQC's DH_A and DH_B in 3 mol/kgw of NaCl at 90 C are the page's at that a(H2O) to 7e-16, 1.7e-6 from pure water's; the page's coefficients at PHREEQC's molalities, 0.01 to 3 mol/kgw of NaCl at 25 to 150 C, PHREEQC's to 6e-16 in log gamma (with A and B pure water's, 1e-10 for the dilute water to 8e-6 at 150 C, where the water's pressure is the vapour pressure times a(H2O) and moves the dielectric constant too), and the starts to 4e-14 (7e-11 at 150 C).
- **LLNL** (`ACTIVITY = llnl`, `<LLNL>`): always on a database of the tests' own, phreeqc.dat's species with an LLNL_AQUEOUS_MODEL_PARAMETERS block of made-up tables at 0.01, 25, 60, 100 and 150 C, -llnl_gamma on the ions and -co2_llnl_gamma on CO2 and two gases; and on PHREEQC's own llnl.dat where it is on this machine, `~/.cache/kvotab-phreeqc/obj/database/llnl.dat` from the PHREEQC build or `RTM_LLNL_DAT`, skipped otherwise. Reading: the options by PHREEQC's prefix rule and their numbers on the lines after them, and the last of -gamma, -llnl_gamma and -co2_llnl_gamma the species' rule (PHREEQC's gflag). The page's coefficients and water at PHREEQC's molalities in 2 mol/kgw of NaCl at 40 and 120 C, each between two of the tables' temperatures, are PHREEQC's to 2.2e-16 in log gamma, and the model written from it starts on PHREEQC's water to 5e-15; on llnl.dat a 1 mol/kgw NaCl water at 25, 90 and 200 C to 4.4e-16 and 1.5e-14. A water with an ion the database gives no -llnl_gamma is not written following LLNL's model, and says why (PHREEQC has no coefficient for such an ion). The PHREEQC tab on a run adding 1 mol/kgw of salt: PHREEQC's coefficients move 0.047 in log K and the model's own stay within 6e-16 of them.
- **Molar volumes, log K at the pressure** (`<VOLUMES>`, `PRESSURE`): on phreeqc.dat. -Vm and -Millero are read as PHREEQC reads them (97 species with -Vm, 37 phases; a phase's unit; a reaction read again starts without). Each species' molar volume and the water's at PHREEQC's water, the page's against PHREEQC's VM(), at 25 C and 300 atm, 60 C and 100 atm, and 150 C on the vapour pressure times a(H2O) and at 50 atm: within 7e-15 cm3/mol. The hand-off punches VM() a column each, in a second run of the same input: a VM put into the string of every species' molality left the WebAssembly PHREEQC's memory spoiled, and a database loaded a few runs later fell over it ("memory access out of bounds", as with the empty FOR). It writes PRESSURE, PHREEQC's -- which above 100 C is the vapour pressure times a(H2O), and PHREEQC keeps that with the solution: a REACTION that lowers a(H2O) leaves the water there (calc_rho_0 raises the pressure to the vapour pressure and never lowers it), so writing it, rather than leaving the model to follow the vapour pressure, is what matches -- and <VOLUMES>, and the model starts on PHREEQC's water to 1.7e-14. The log K written are at one atmosphere: the same from PHREEQC's water before and after 2 mol/kgw of NaCl went in, to 7e-15; and every relation of the model written before holds at PHREEQC's water after (I 1.1 to 3.1) to 6e-15 in log K, where without the volumes it would be 1.14 off at 500 atm, 0.006 at 150 C on the vapour pressure, 0.36 at 150 C and 200 atm. 3 mol/kgw of NaCl into a water over anhydrite at 500 atm against REACTION: calcium within 2.8e-11, the anhydrite left within 1e-9 mol, calcium 25 % above what it is at one atmosphere. (A calcite water will not do for that: PHREEQC's mass of water moves by 1e-5 to 6e-5 kg as calcite's acid-base reactions make and take water, which a model in a fixed kilogram does not follow, at one atmosphere alike.) The PHREEQC tab at 500 atm, a run adding 1 mol/kgw of salt: PHREEQC's waters at the model's PRESSURE, its coefficients and log K moving 0.45, the model's own within 5e-15. On pitzer.dat where it is on this machine: a brine at 90 C and 500 atm handed off under Pitzer starts on PHREEQC's water to 6.2e-15, and its relations hold at PHREEQC's after 1.5 mol/kgw of NaCl to 2.9e-14 (4e-12 and 7e-12 while the page took Pitzer's A_phi after one pass, see Pitzer).
- **Sites that go with a phase** (`sites= per=`, PHREEQC's SURFACE with `equilibrium_phase`): Hfo's weak and strong sites on anhydrite, 0.02 and 0.0005 to each mole, without electrostatics, on phreeqc.dat. Anhydrite, because it dissolves into salt without making water: on ferrihydrite PHREEQC's mass of water moves by 3 H2O a mole dissolved, which a model in a fixed kilogram does not follow. The hand-off writes the bare sites `sites=0.02 per=Anhydrite`, and the model starts on PHREEQC's water and surface to 1.4e-14. 0.3 mol/kgw of NaCl added against REACTION: the anhydrite left within 4e-7, the zinc on the surface 2.2e-6 and the pH 4.8e-7 (PHREEQC's water moves by 1.2e-7 kg), the model's sites 0.02 times its anhydrite exactly and PHREEQC's to 1.2e-7. PHREEQC's own numbers show what -equilibrate means: the surface is loaded from the water as from an endless supply of it, and the batch step then adds what it took up to the system -- 4.8e-4 mol of zinc on the sites from a water given 1e-5. With PHREEQC's double layer, its area 600 m2 to each mole of anhydrite: written `Hfo_psi potential area=600 per=Anhydrite`, the start to 2e-14, and with the salt the anhydrite within 4e-7, the zinc on the surface 3e-7, the pH 2e-8 and the potential as PHREEQC's EDL("psi") (PHREEQC's water moves by 7e-7 kg).
- **CD-MUSIC** (`-cd_music`, three potentials `_psi`, `_psib`, `_psid`, `dz0= dz1= dz2=`, `c0= c1=`): on phreeqc.dat with a goethite-like block of the tests' own in front (made-up constants: protons on plane 0, sodium on plane 1, a chloride pair across both, zinc split by PHREEQC's five numbers, f 0.3 of a charge of 2). -cd_music is read as PHREEQC reads it, dz0 + f z, dz1 + (1 - f) z and dz2. The hand-off writes the surface by CD-MUSIC -- its three potentials at PHREEQC's EDL psi, psi1 and psi2, the first with the area and capacitances, each species' planes as dz0 to dz2 and a half charge as z= -- and the model starts on PHREEQC's water and surface to 5.4e-13 in charge balance and 6.2e-13 with a charge of its own. 1 mmol of HCl added against REACTION: pH 3.12364030 for PHREEQC's 3.12364030, the three potentials within 5.2e-11 V; the PHREEQC tab finds the surface PHREEQC loads from each water within 1e-14 of the run's and the potentials 4.4e-14 V. On the way: the diffuse layer's fictitious ion, |sum m z|, has a corner where the water is in charge balance, which is where PHREEQC's waters are; one-sided, the Jacobian put plane 2's row 2x off against H+ and the run's projection 6 % off; it takes the mean of the two sides there, and a water with a charge of its own checks exact.
- **An exchanger's sites that go with a phase or a kinetic reactant** (`sites= per=` on a species on it, PHREEQC's EXCHANGE with `equilibrium_phase` or `kinetic_reactant`): the formula a species on the exchanger with its ion, as PHREEQC's manual has it. CaX2 on anhydrite, 0.05 of it to each mole (0.1 sites), in a sodium chloride water: the hand-off writes `CaX2 ... exchange ... sites=0.1 per=Anhydrite`, the model starts on PHREEQC's water and exchanger to 1.8e-15, and 0.3 mol/kgw of NaCl, dissolving 86 % of the anhydrite, against REACTION: the anhydrite 2.3e-9, CaX2 1.8e-9, NaX 1.0e-9, pH 9.3e-11 (PHREEQC's water moves by 8e-10 kg). NaX on the NaOH host of the kinetics bullet, 0.1 a mole, in a water with calcium and sodium, against KINETICS at its steps: the host 1.4e-9, Ca+2 4.5e-10, Na+ 2.4e-10, CaX2 2.1e-9 and NaX (a trace beside the calcium) 9.1e-8 in moles, pH 2.7e-9. With the capacity held where it started -- the sites= per= taken off -- CaX2 and NaX end 7 times PHREEQC's in both, so the checks can tell. PHREEQC's own reading, which the page follows: as the phase dissolves the system loses the formula times the proportion (build_min_exch; kinetics.cpp for a reactant), the phase's own formula, which must hold the formula's ions, still dissolving whole; and each species' activity is over the exchanger's moles now (gammas, alk = the unknown's moles). A bare `X` for a formula is held, with the reason: PHREEQC takes its sites away and leaves their charge, the water reduced.
- **A column from TRANSPORT** (since 2026-11-08): the input's first TRANSPORT (or ADVECTION) read as PHREEQC's readtr.cpp reads it -- a word with its dash the first option it begins, without it the whole word, a bare line going on with the list before (lengths, dispersivities), `n*x`, the time step's unit, the old direction after -shifts -- with PHREEQC's defaults (flux at both ends, diffusion coefficient 0.3e-9). Everything before it runs as written, then RUN_CELLS with no time puts each cell and each end's water on what is numbered as it, as TRANSPORT's own "Equilibrating initial solutions" does. Cells that come out alike make a zone, started from its first cell: cell 1's in `<SPECIES>`, every other zone's in `<INITIAL>` (its cells counted from 0, as the page counts them). Alike is each element's total within a part in a million, H - 2 O (the water's acid) within a part in a million of the largest total, each valence state's within a part in 1e4 and a part in 1e6 of the largest total (PHREEQC's redox settles no closer), and what is on the exchangers and surfaces and the phases' and reactants' amounts within a part in a million -- not the species: twenty cells of one nitrate water come out of RUN_CELLS 5.7e-6 apart in H+, 7.6e-5 in O2 and 2e-4 in N2, their totals within 2e-14 (a calcite water, every digit alike), and a first version, comparing species, split cells defined alike into zones of their own. Each water, each zone's and each end's, takes 1e-12 of every other. Since 2026-11-09; until then every cell had to come out as cell 1. Example 11's column in an input of the tests' own written as Example 11's is (ADVECTION, COPY, a graph, then TRANSPORT; its calcium and chloride only in SOLUTION 0): the effluent within Na 0.0216, K 0.0301, Ca 0.0155, Cl 0.0048 mM of TRANSPORT's -- the hand-built test above, with traces put into both waters by hand, 0.022, 0.033, 0.017, 0.005. Acid through calcite in every cell: pH 0.0086, Ca 0.026 mM, the calcite gone from 24 cells against 23. Calcite at a rate: the kinetics bullet's 20-cell numbers exactly. Two waters, each half of 40 cells with its exchanger loaded from its own (1.1 and 0.8 mmol), flushed with calcium chloride: zones 1-20 and 21-40, the effluent within Na 0.0215, K 0.0360, Ca 0.0174, Cl 0.0051 mM. Calcite in the first half only, acid flowing in: zones 1-20 and 21-40, `Calcite 20-39 0` in `<INITIAL>`, pH within 0.019 and Ca 0.047 mM, the calcite gone from all 40 cells as in PHREEQC. Stagnant cells (since 2026-11-09), `-stagnant 1 alpha theta_m theta_im`, PHREEQC's first-order exchange (transport.cpp mixes each cell with the stagnant cell n + 1 + i behind it by b(1 - f) and (1 - b)(1 - f), b = theta_m/(theta_m + theta_im) and f = exp(-alpha dt/(b theta_im)): the exchange solved exactly over each mixing step), as the page's rock matrix of one layer -- MATRIX_CELLS = 1, 1 m deep, MATRIX_POROSITY theta_im, WETTED_SURFACE 1/theta_m and every species' Dm alpha/2, which make the cell's rate alpha/theta_m and the layer's alpha/theta_im -- the stagnant cells' zones in `<INITIAL>` with `matrix` after them. The exchange alone (three closed cells of NaCl, KBr stagnant behind them, a little diffusion so that PHREEQC mixes at all: with neither diffusion nor flow its shifts do nothing, not even punch) against TRANSPORT at all 60 values: within 9e-9 of 1 mmol/kgw. A column of 20 and 40 cells, an exchanger in the cells and in the stagnant water behind them, flushed with salt and nitrate (our own input, written the way PHREEQC's Example 13's first one is): the effluent within Na 0.048, Cl 0.034 mM on 20 cells and 0.039, 0.009 on 40; the stagnant cell behind the last 0.019, 0.018 and 0.013, 0.009. Calcite in the stagnant cells only, acid flowing in: Ca 0.060 and 0.027 mM, the calcite behind the last cell 0.089 and 0.041 mmol, pH 0.22 and 0.18 (the first shift's front). RUN_CELLS skips a cell without a SOLUTION, as TRANSPORT leaves a cell without stagnant water out of the exchange; the hand-off refuses that, the page's stagnant water being behind every cell. Found on the way, and in the committed TRANSPORT hand-off already: nitrate that only the inflow brings into a NaCl water at pe 4 was not written at all -- cell 1's 1e-12 of the inflow put its nitrate into N2 in PHREEQC's speciation, MOL("NO3-") reads 0 below 1e-30, and only species cell 1's water has were written, so the K+ came in without it. Such a species is now written at the trace it came in as (the most any water has of it times 1e-12), its relation with the database's LK_SPECIES, and the text names it: the effluent within 0.051 mM in K, N(5) and Na on 20 cells, the valence states apart and the couples tied alike. The options as the column comes out of them, and twenty-two inputs refused with their reasons (stagnant cells with no water behind some cells, in two layers, without an exchange factor, at a temperature of their own, without the cells' exchanger, with a REACTION, or with -multi_D; under -multi_D cells of their own lengths or porosities, a porosity below its limit, coefficients corrected for the ionic strength, a -multi_D neither true nor false; interlayer diffusion; cells at temperatures of their own and an exchanger in some cells only; a gas phase or a solid solution in a column that starts apart or has stagnant cells is refused too). Three traps: PHREEQC keeps a MIX from one run to the next and RUN_CELLS takes a cell's MIX for its water, so a scratch `MIX 1` made cell 1 a mixture in every later run -- the scratch mixes have the number 9999991 and are DELETEd; a trace of 1e-20 of the other water left totals of 1e-24, from which the NDF could not start (at t = 1e-24 without redox, 12 s with it), 1e-12 runs; and the exchange species of what only the inflow brings (CaX2) are below any floor in the column's water, so the species kept are those above it in any of the waters and in each zone's water and an end's mixed half and half on what the zone holds, its exchanger and surfaces. -correct_disp multiplies PHREEQC's mixing between cells, dispersion and diffusion, by 1 + 1/cells for each flux end (transport.cpp), and the page's PECLET and D the same.
- **EQUILIBRIUM_PHASES as PHREEQC reads a line** (since 2026-11-09): name, SI, an alternative formula or phase where the next word begins with a letter, the amount, `d...` or `p...`, and `-force_equality` on the line after. Five waters handed off with their phases (activities following, relations held, redox off, floor 1e-12) and run with what PHREEQC's REACTION adds in five steps put in at a constant rate, against those steps: a pH-stat, `Fix_H+ -8 NaOH 0.01` with `Fix_H+` written into PHASES, acid coming in, written `NaOH_Fix_H ... mineral` held at `SI(Fix_H+) = -8`, the NaOH within 2.1e-7 of the most there was of it and the pH exact; calcite `dissolve_only` in a water supersaturated with it, acid coming in, 5.6e-6 and pH 8.5e-6, held at its 2 mmol until the water is no longer supersaturated, then dissolving, then dissolved away (two events; PHREEQC's steps 1.55, 0.69, 0, 0, 0 mmol); gypsum `precipitate_only` in a water undersaturated in it, CaCl2 coming in, 4.5e-5 and 5.7e-6, its 10 mmol set aside until the water saturates and gypsum precipitates beside it (one event) -- the 4.5e-5 is PHREEQC's kilogram of water going with the gypsum's two waters of hydration; `Fix_H+ -9 HCl 0` with `-force_equality true`, salt coming in, written `force_equality`, 8.3e-7 and exact -- the HCl taken out of the water to raise its pH to 9, 0.14 mmol and growing, so this one does not go below none: below none is checked in test-model.js only (see below); and anhydrite held where calcite is saturated, `Calcite 0 Anhydrite 0.01`, acid coming in, `Anhydrite_Calcite`, 2.1e-5 and 1.1e-6, dissolved away just after the first step (one event; PHREEQC's 0.65 mmol after it, none after the second). A phase at its bound is written held at its target, not at the SI its bound left the water at (a first version wrote the latter, and the mineral sat at the wrong saturation). PHREEQC's own traps the waters had to avoid: `KNOBS -convergence_tolerance 1e-14` fails some of these steps (1e-12 runs); a water charge-balanced on Cl must keep a positive Cl; and PHREEQC itself failed `-force_equality` in two first tries, NaOH driven below none and calcite from none. Trace S(-2) at the 1e-20 floor made the held runs slow, hence 1e-12.
- **Kinetics** (`KINETICS`, `RATES`): each of phreeqc.dat's seven RATES programs as the rate law the hand-off writes (`rateLaw`, PHREEQC's BASIC run symbolically: each variable a name on the line, a condition on the water step(), what is SAVEd over TIME the rate, PHREEQC's x/0 = 0, 0^y = 0 and its unary minus before ^) against the program run by PHREEQC's own BASIC at the same water -- M, M0 and PARM put in as numbers, TIME 1, SAVE as PUNCH -- at an oxic water at 25 C and an anoxic one at 40 C: 14 within 2.8e-14. (A molality is read as 10^LM: PHREEQC's MOL is 0 below 1e-30 where its LM still reads -76, and pyrite's rate in the anoxic water reads LM("O2").) Reading: -m and -m0 each the other's, the formula the name, -parms words and numbers, `-steps 1 day in 4`, `10 4*5`, a RATES given again replacing; and five programs refused with their reasons (a loop, moles not a rate times TIME, a way that saves nothing, PUT, a PARM not given). Handed off and run against PHREEQC's KINETICS at its steps (`-runge_kutta 6`; the page at rtol 1e-10 with a break at each step): calcite into a CO2 water with no calcium, its species from 1e-20 mol of calcite (PHREEQC's REACTION) since a total at none cannot be held, 8.2e-11 in the calcite left and pH 1.8e-10 with PHREEQC's `-tol 1e-14` (1.6e-9 and 9e-10 at `-tol 1e-10`: PHREEQC's error, converging on the page's); K-feldspar 1.5e-13 and 5.1e-9; organic carbon (CH2O, Monod) through the water's O2 into its nitrate, 3.2e-8, 2.2e-7 and pe 4.5e-5 where the pe drops; pyrite with O2 at 1e4 times phreeqc.dat's example area, 8.1e-12, 2.5e-10 and pe 2.1e-9. Organic carbon and pyrite move electrons, CH2O written CO3-2 + 6 H+ + 4 e- less water and pyrite as its PHASES has it, `Pyrite + 2 H+ + 2 e- => Fe+2 + 2 HS-`. Not in the checks: quartz, whose 2 H2O a mole move PHREEQC's kilogram by 1e-5 (the page 1.9e-6 off in Si, 3e-6 in pH), and pyrolusite, phreeqc.dat's rate stopping where Fe(2) falls below 1e-8, around which PHREEQC's steps chatter (pe 3e-3 apart while the Mn is the same). Two bugs the runs found in the page: the derivative in TK of a power whose exponent goes with TK was taken and refused, though TK reads no species; and the negated exponent above. A column, CO2 water through 0.1 m of calcite dissolving at phreeqc.dat's rate for two pore volumes, against PHREEQC's TRANSPORT with KINETICS in each cell, the hand-off's model made a column as in the reactive column above: on 20 cells the effluent within 0.148 in pH and 0.015 mmol/kgw of Ca, the calcite dissolved 0.8 % apart; on 40 cells 0.072, 0.0076 and 0.31 % (80: 0.031, 0.0047, 0.13 %), halving as the cells halve, the velocity and the time kept -- PHREEQC shifts a cell's water whole and then reacts it for the step, the page's cells are mixed, and the two meet. (A first try kept the time step as the cells shrank, which slows the flow and is no refinement.) A surface whose sites go with a kinetic reactant (`Hfo_wOH NaOHs kinetic_reactant 0.2`): a host of the test's own, NaOH, dissolving at a first-order rate into a CO2 water with zinc, 86 % of it, with PHREEQC's SURFACE kinetic_reactant -- PHREEQC wants the surface's H and O in the reactant's formula, which NaOH has and anhydrite has not -- the hand-off writing `sites=0.2 per=NaOHs` and the start water given the sites as PHREEQC loads them at -m (PHREEQC will not load them without the KINETICS): the host within 1.1e-9, Zn+2 2.5e-7 and on the sites 1.2e-6 in moles (PHREEQC's molality times its kilograms, which grow by 3.2e-6 as the OH- makes water with the carbonic acid), pH 6.7e-8; with a double layer of 53300 m2 to each mole 2.7e-10, 3.1e-8, 1.6e-7 and 3.5e-9. Fe(OH)3(a) as the host saturates within the first step, a test of little, and makes 3 H2O a mole. With the valence states apart (redox off) a trace of Fe(2) beside the Fe(3) the reactant brings, 1e-29, is a total no factorisation resolves: the hand-off keeps every species of the valence states a reaction moves, of the whole element only where they are held at one pe. And an exchanger whose capacity goes with the reactant with the bare exchanger for its formula (`X NaOHs kinetic_reactant 0.1`): held at what PHREEQC loads at the start, which the report says, with why -- PHREEQC's manual has the formula a species on it with its ion, and with a bare X PHREEQC takes the sites away and leaves their charge behind, the water reduced (pH 7 to 11.3 and pe 4 to -8.3 as 86 % of an anhydrite host dissolved, in a probe). A formula with its ion is carried: see the exchanger bullet above.
- **The jobs as the page sends them**, through the handler its worker runs. The database the page loads as a script is the file, character for character, and plain ASCII.

With `RTM_PHREEQC_PYTHON` naming a Python that has phreeqpython (`phreeqc-bridge.py` drives it), the same inputs also go through that native PHREEQC on the same database. The WebAssembly build has to agree with it: 1.7e-13 on a model's numbers, and every number of a run's CSV identical.

`test-phreeqc-ui.py` covers the page itself:

- PHREEQC is not fetched until it is used, and then runs in a worker of its own.
- The panel on the Model tab writes the example water and reports the check. By default the activity coefficients follow the ionic strength (`ACTIVITY = debye-huckel` at 15 °C, `H2O` in the relations); fixed at this water, the constants are conditional and the water is left out. By default the relations are held exactly, and the model facts and the Jacobian tab say so (the tab draws the species' 41 × 41 of the 51 × 51 and names the 10 totals it leaves out). Chosen as fast pairs, the rate they relax at is asked for and each of the 30 relations gets its `kf`.
- Keeping the phases needs the relations held exactly (the box is greyed otherwise); with a calcite phase in the example water, calcite becomes a mineral, the report says so, and the model facts count it.
- An `EXCHANGE` in the example water is carried: `X- exchanger`, CaX2 with the database's a and b, the report and the model facts saying so. Run and looked at, the PHREEQC tab finds the run's exchanger within 1e-6 of the one PHREEQC loads from its waters (6e-10 measured).
- A `SURFACE` in the example water is carried with its double layer: the strong and weak sites, what PHREEQC put on them and `Hfo_psi potential area=600 grams=0.09`, the report and the model facts (two kinds of surface site, the potential in mV) saying so. Run and looked at, the PHREEQC tab finds the run's surface within 1e-6 of the one PHREEQC loads from its waters, and its potential within 1e-3 mV.
- The example water's couples are tied to the electron by default, the water PHREEQC's next step (51 species, 41 relations, pe −2.95): the report and the model facts say so, and the run looked at through PHREEQC shares C, Fe and S out at the run's pe as the run has them, within 1e-6.
- A SIT database opened (phreeqc.dat with a SIT block in front, written to a temporary file) is read; with it the example water is written following SIT, `ACTIVITY = sit` and the database's coefficients in `<SIT>`, no a or b, the report and the model facts (SIT at the water's temperature, the pairs) saying so. Run and looked at through PHREEQC on the same database, the model's own coefficients are within 1e-6 of PHREEQC's.
- A `GAS_PHASE` (fixed volume, CO2(g)) in the example water is carried as a real gas: `GAS_VOLUME`, `PRESSURE` and `CO2(g) ... gas Tc=304.2 Pc=72.86 omega=0.225`, the report and the model facts saying so; run and looked at, the PHREEQC tab finds the run's gas within 1e-4 in log of the pressure the water holds it at. (The volume per kilogram of water is 0.49999..., PHREEQC's kilogram not quite one.)
- A `SOLID_SOLUTIONS` (aragonite and strontianite, -Gugg_nondimensional 3.43 -1.82) in the example water with 0.5 mmol/kgw of Sr is carried: the members as minerals, `CaSrCO3  Aragonite  Strontianite  a0=3.43  a1=-1.82`, the report and the model facts (a miscibility gap) saying so; run and looked at, the PHREEQC tab finds each member's activity in the run's solid within 1e-6 in log of 10^SI of the pure member.
- A Pitzer database opened (phreeqc.dat with a PITZER block of the test's own in front, written to a temporary file) is read; with it the example water is written following Pitzer, `ACTIVITY = pitzer` and the database's parameters in `<PITZER>` with their terms in the temperature, no a or b, and the electron fixed at PHREEQC's pe (its Pitzer model holds the pe, the block giving no `-redox`), the report and the model facts (Pitzer at the water's temperature, the parameters, the MacInnes scaling) saying so. Run and looked at through PHREEQC on the same database, the model's own coefficients are within 1e-6 of PHREEQC's.
- The temperature: the example water written again, the report saying how many relations' log K go with temperature as the database's do; with `TEMPERATURE = warm(t)`, a table from 15 to 35 °C over the run, the model facts say so, and the run looked at through PHREEQC gives each water the temperature it has in the run (the worker keeps each stored point's) and finds the model's own activity coefficients within 1e-6 of PHREEQC's at it. Fixed at this water, the water's dissociation is the database's analytic expression moved to the conditional constant, -14.1398953203 at 15 °C, read off the compiled model.
- **Multicomponent diffusion, -multi_D** (since 2026-11-09): `-multi_D true Dw porosity limit n` read with PHREEQC's defaults (1e-9, 0.3, 0, 1, each back at its default unless given), `-porosities` and `-implicit`. Each species' D is PHREEQC's Dw at the water's temperature as fill_spec takes it -- Dw times viscos_0(25 C)/viscos_0, exp(dw_t/T - dw_t/298.15) and (viscos_0/viscos)^dw_a_v_dif where -dw gives them, -multi_D's Dw times the viscosity ratio alone for a species without -dw -- times the porosity to the n (`-stagnant`'s mobile one where both are given, as PHREEQC has it); the text says `DIFFUSION = nernst-planck` and `DIFFUSION_GRADIENT = activity`, PHREEQC's find_J being the zero-current flux with each difference times 1 + (lg_j - lg_i)/(lm_j - lm_i). At 40 C each written D is DIFF_C's there times 0.3 to 1e-10. PHREEQC's own explicit steps converge at first order (1 to 40 mixing steps a shift moves the answer about 1 %, 10 to 40 about 0.1 %), so the tests set its runs at 10 and 40 steps a shift against each other, (4 x40 - x10)/3: HCl against NaCl in ten closed cells of 2 mm for five hours within 4.6e-9 mol/kgw in Na, 3.4e-9 in Cl and 5.5e-7 in pH; the exponent 2, 4.5e-9, 1.5e-8 and 8.4e-6; with pure water held at both ends 2.5e-7, 3.1e-7 and 5.3e-5, with dilute salt there 6.0e-7, 3.7e-7 and 6.8e-5. Without the activity's part the closed column is Cl 2.5e-5 and pH 1.5e-3 from PHREEQC's at 40 steps, where with it 7e-7 and 2e-4. Four traps. (a) PHREEQC uses its factor only between 0.2 and 2.25 and drops it to 1 beyond -- a species nearly level where its gamma is not -- and the flux jumps, upwards as the difference falls below 0.2: an implicit solver stalls on it (HCl against NaCl, pure water held at both ends, two million steps to 54 hours; a tracer across salt, at 339 s). Leaving the factor unbounded (the activity's gradient all the way, its logarithmic-mean form) runs, but puts a level species where its activity is level, where PHREEQC keeps its concentration level: the bromide 12 % from PHREEQC's. Holding the factor at 0.2 or 2.25 beyond the bounds keeps the flux going without a jump, never up a species' own gradient, and a level species level: the bromide within 8 % (1.3e-4 mol/kgw), the pH 0.008, with sea-strength salt held at one end; the dilute-salt ends above, 6e-7 against 1.2e-6 unbounded. (b) The hand-off's waters carry 1e-12 of what they lack, where PHREEQC's have none and take no factor for a species on one side only: at ends held at pure water that was 4.3e-6 mol/kgw in Na and 3.2e-4 in pH, so the factor fades out as one side falls from 1e-6 to 1e-10 of the other (2.5e-7 and 5.3e-5). Writing those ends' traces as none instead drains the end cells' totals to nothing, and the NDF fails after 32 days. (c) PHREEQC's -implicit scheme has the activity's part commented out (diffuse_implicit: `grad = (Ct2[i1] - Ct2[i])/* * ct[i].v_m[cp].D*/`), and goes its own way within that: the text then leaves DIFFUSION_GRADIENT out, and is within 2.0e-6 mol/kgw and 5.8e-4 in pH of PHREEQC's implicit runs at 160 steps, which are 1.2e-5 and 1.8e-3 from its explicit ones. (d) Under -multi_D PHREEQC exchanges with stagnant cells species by species (kinetics.cpp leaves STAG mixing out, multi_D(1.0, i, 2) runs find_J on -stagnant's MIX), each at its Dw over -multi_D's, porosity cancelling, by the mixing fraction for a step divided by the steps once more: a quarter as much over a shift at four times the steps -- refused. A column with an exchanger flushed with calcium chloride (our own input, written the way Example 11's is), -multi_D beside the dispersivity: the effluent within Na 0.0317, K 0.1297, Ca 0.0608, Cl 0.0186 mM on 20 cells and 0.0206, 0.0282, 0.0146, 0.0044 on 40. A hundred days with pure water held at both ends: 4790 steps, 0.4 s. PHREEQC keeps a TRANSPORT's options for the next TRANSPORT in the same instance (-stagnant, -implicit): the tests' inputs each say both, a later implicit run having failed on an earlier test's -stagnant 1.
- **Conductance, density and viscosity, against PHREEQC** (since 2026-11-09): a handed-off water's `SC`, `rho` and `viscos`, worked out by the model from the `<CONDUCTANCE>` the hand-off writes (each solute's `-dw`, `-viscosity` and gram formula weight) and its `<VOLUMES>` at 1 atm, against PHREEQC's `SC`, `RHO` and `VISCOS` -- calc_SC by Falkenhagen's equation, as phreeqc.dat's H+ has a sixth `-dw` number above 24, calc_dens, and viscosity(), Huber's pure water with the Jones-Dole and Falkenhagen-Dole terms: 10 mM NaCl, a carbonate water, brackish water at 50 C (38,494 uS/cm) and sulfate without chloride, whose viscosity takes Cl-'s volume from its `-Vm` (written `Cl- vm`), within 1e-14; a mixed water under SIT and under Pitzer, with this file's coefficients and PHREEQC's convergence tightened, within 7.3e-11 and 5e-15; and acid into the NaCl at 1e-8 mol/kgw a second for a day, pH 7 to 3.1 and 1,178 to 1,529 uS/cm, at the run's end against `REACTION` within 2e-9, the 2e-9 kg of water PHREEQC's kilogram gains from OH-. Acid into the carbonate water instead ends 1.4e-5 apart: the water its CO2 makes from the bicarbonate, 1.5e-5 kg in a day, which PHREEQC's kilogram of water takes and the page's does not, every molality off by that factor. Cl-'s `-Vm` was first written as the database's raw numbers, 0.7 % off in the sulfate water's viscosity; it is converted as `<VOLUMES>` converts a `-Vm`. With `<VOLUMES>` written at 1 atm, the checks that write `left=` after a species line read `<SPECIES>` alone (SPECIES_LINE), as `<VOLUMES>`' lines have the same shape; the SIT hand-off's check reads `<SIT>` to the next section. In the browser (test-phreeqc-ui.py), the example water handed off has `<CONDUCTANCE>`, Na+'s line with its gfw, `-dw` and `-viscosity`, and `<VOLUMES>`, and the report says so.
- **Fitting, against PHREEQC** (since 2026-11-09): zinc on a ferrihydrite's weak sites (`-no_edl`), titrated with HCl at 1e-8 mol/kgw a second for a day -- PHREEQC's REACTION at ten times -- PHREEQC's dissolved zinc taken as what was measured, pH 7.1 to 3.3. The handed-off model with the acid added at the same rate, the weak sites' log K for zinc moved off by a unit, is fitted back by the worker's `fit` (Levenberg-Marquardt): -1.9899998 for phreeqc.dat's -1.99 in 9 runs, within its standard error (1.7e-7).
- **Diagrams, against PHREEQC** (since 2026-11-09): a handed-off water held by the Diagrams tab's computation (`handleRtmMessage` with a `diagram` message, as the worker answers the page) at a pH, a pe or a total, against PHREEQC's `SOLUTION` of the same totals there, which speciates without a charge balance as the tab does: a carbonate water at pH 4, 6, 8 and 10, every species within 7.6e-9 (PHREEQC's own convergence); iron in both valence states at pe 2 to 11 and pH 6 and 7, within 5e-12; pH 6 and 8 against total carbon 1e-4 and 1e-2 mol/kgw, within 7.4e-9. With the pe varied alone the pH floats, and an unbuffered water's goes where reducing the iron's hydroxides takes it: PHREEQC's `SOLUTION` holds it, so the check holds it too.
- **The boundaries of a map, against PHREEQC** (since 2026-11-09): a handed-off iron water's Pourbaix map (pH 2 to 8, pe -2 to 12.5, 13 x 11 points), its boundaries found by the worker's `diagramBounds`: five boundaries and two points where three fields meet. At each of their 34 points PHREEQC's `SOLUTION` at that pH and pe gives the species either side the same amount of iron (n MOL) to 1e-9 (6.3e-11), and no other species more -- the third as much where a line ends at a point where three meet. The map stays where water does, pe + pH from 0 to 20.5: at pe 18 and pH 12 PHREEQC's dissolved O2 runs to molalities it does not converge on. The same water at 60 C over pH and Eh, -0.12 to 0.72 V (since 2026-11-10): each point's pe its Eh over the volts of a pe at 60 C, 0.066100 V, PHREEQC's `SOLUTION` given that pe and `temp 60`: at each of its 36 points the species either side the same amount of iron to 1e-9 (7.5e-11), no other species more.
- **Eh, against what PHREEQC prints** (since 2026-11-10): PHREEQC gives an Eh only where it prints a water's redox couples, each couple's pe and Eh to four decimals, with its own R and F (`R_KJ_DEG_MOL` 0.00831470 and `F_KJ_V_EQ` 96.4935 of global_structures.h, at the water's temperature). Two waters with Fe(2)/Fe(3) and N(-3)/N(5) at 5, 25, 60 and 90 C: 16 couples, pe -0.4 to 13.7, each printed Eh given back by `RtmModel.ehPerPe` from the pe printed beside it within 4.95e-5 V (both rounded to four decimals, 5.4e-5 at most); CODATA's R and F would be 8.6e-5 off. A handed-off iron water at pe 3.5 at the same temperatures: its iron given to PHREEQC again as Fe(2) and Fe(3) apart, as much of each as the water has at its pe, makes a couple at pe 3.5000, whose printed Eh is the page's quantity to the four decimals, 0.1932 V at 5 C to 0.2522 V at 90 C.
- **A silicate stability map, against PHREEQC** (since 2026-11-10): a handed-off water (K, Al, Si, Na, Cl), with phreeqc.dat's K-feldspar, kaolinite, gibbsite and K-mica added as `<PHASES>` at PHREEQC's own log Ks at 25 C (`LK_PHASE`), mapped over log a(H4SiO4) -5 to -2 and log a(K+)/a(H+) 0 to 6, each phase per mole of aluminium: four boundaries and one point where three meet. At each of their 36 points the page's water there, its totals and pH, given to PHREEQC's `SOLUTION` has the phases either side the same saturation index over their aluminium, to 1e-9 (1.1e-10), and no phase a larger one (5.2e-14).
- **A redox ladder, against PHREEQC** (since 2026-11-10): a handed-off water with nitrogen, iron, sulfur and carbon, written with the floor at nought so that every species phreeqc.dat has of them is there, at none where the water has none (sulfide and methane in a water at pe 10, made from its sulfate and carbonate; at pe 4 there would be no nitrate to make the rest of the nitrogen's from, PHREEQC counting none below 1e-30). Every species of the four in the water has the valence state phreeqc.dat has it in -- 22 checked, FeHSO4+2 iron(3) and sulfur(6), FeHSO4+ iron(2), NH4SO4- nitrogen(-3), Fe2(OH)2+4 iron(3), CH4 carbon(-4) -- and the couples are the database's six half-reactions. Its ladder at pH 7 along pe from -7 to 13.5, through the worker's `diagram` and `diagramLadder` messages: NO3-/N2 at 11.931, NO3-/NO2- 7.285, NO3-/NH4+ 6.136, Fe+3/Fe+2 4.532, SO4-2/HS- -3.646 and CO3-2/CH4 -4.046, and at each rung PHREEQC's `SOLUTION` of the model's own totals at pH 7 and that pe gives the couple's two states the same amount of the element (`TOT`) to 7.8e-10; at 40 C, at pH 5 along Eh, each rung's pe its Eh over the volts of a pe at 40 C, to 3.8e-12.
- **The couples across a map, against PHREEQC** (since 2026-11-10): the ladder's handed-off water over pH 4 to 10 and pe -4 to 10.7, where water itself holds (a map past its limits has O2 and H2 at molalities its corners do not settle at), each couple's line found by the worker's `diagramCouples`, a map's boundaries between the couple's two states: all six cross it, and at each of their 82 points PHREEQC's `SOLUTION` of the model's totals at that pH and pe gives the two states the same amount of the element to 7.8e-10. Over Eh across and pH up, the other way round, the same to 1.1e-8: the lines are found to 1e-10 V, 1.7e-9 in pe, and NO3-/N2 moves ten electrons.
- **Redox zones, against PHREEQC** (since 2026-11-10): a water with oxygen, nitrate, sulfate and carbonate, with pyrolusite, ferrihydrite and FeS(ppt) as its EQUILIBRIUM_PHASES, handed off with every species phreeqc.dat has of its elements (`phases`, `redox`, the floor at nought); organic carbon added at a steady rate as `=> CO3-2 + 6 H+ + 4 e-`, against PHREEQC's REACTION adding CH2O in 32 steps. At each step every valence state's total -- the model's twelve, tot(N(5)) to tot(Mn(3)) -- is PHREEQC's TOT within 1.4e-5 of its element's total, each mineral its EQUI within 2.5e-10 mol/kgw, the pH within 5.7e-7 and the pe within 1.6e-4; three mineral events between. The oxygen and the nitrate are used up, then the pyrolusite and the ferrihydrite, the sulfate reduced with FeS forming, then methane; PHREEQC's REACTION makes water as the carbon is oxidised, which the page's kilogram does not count: the parts in 1e5.
- **Redox zones along a plume, against PHREEQC** (since 2026-11-10): a leachate (`SOLUTION 0`: 3 mM of an organic carbon of the test's own, `Doc`, a master species that a KINETICS rate, `PARM(1) * TOT("Doc")` at 5.787e-7 a second, takes out as CH2O; and 15 mM of carbonate) flowing into an oxic aquifer's water (oxygen, nitrate, sulfate), its EQUILIBRIUM_PHASES pyrolusite, Fe(OH)3(a) and calcite, with FeS(ppt) and siderite at none, free to form: PHREEQC's TRANSPORT over 20 m for one pore volume, dispersivity 0.3 m, handed off (`phases`, `redox`, the floor at nought) and run, at 10 cells and at 20. The column's inventory of each zone's mineral and valence state at the end, the page's against PHREEQC's, is nearer at 20 cells than at 10 and within 20 % at 20: Fe(OH)3(a) 11.1 to 2.5 %, siderite 7.3 to 1.7, FeS(ppt) 2.6 to 1.3, calcite 1.2 to 0.4, S(6) 11.0 to 4.2, S(-2) 11.8 to 2.7, C(4) 2.2 to 1.2, C(-4) 28.0 to 16.9, Mn(2) 13.9 to 5.5, the organic carbon 7.3 to 4.2; the pH cell by cell within 0.82 and then 0.34, the organic carbon within 0.20 and then 0.13 mM; 56 mineral events at 20 cells. PHREEQC shifts and then reacts where the page integrates the method of lines, and at a sharp front a cell's value is mostly where the front is: the inventories are compared, and the two meet as the cells shrink. Measured once at 40 cells (100 s, not in the test): C(-4) 6.3 %, pyrolusite 8.6, S(6) 3.3, S(-2) 2.6, the organic carbon 2.3, Fe(OH)3(a) and Mn(2) 2.0, FeS(ppt) and siderite 1.4, calcite 0.24, C(4) 0.18.
- **The water as PHREEQC lists it, against PHREEQC** (since 2026-11-10): the quantities' water handed off -- ion pairs, activities, calcite and an exchanger -- listed by the model (`listingAt`, as the Composition tab reads it): its 25 species' molality, log activity and log gamma, the three on the exchanger, the calcite's SI and log K, the pH, ionic strength, activity of water and percent error, against PHREEQC's MOL, LA, LG, SI, LK_PHASE, MU, ACT("H2O") and PERCENT_ERROR for the same water: the molalities within 1.2e-9 (CaHSO4+, at 4e-11), the log activities 6.1e-10, the log gammas 2.8e-10, the exchanger's 1.5e-11, the SI and log K to rounding, the rest 3.3e-9 (the ionic strength). (CO2)2, which the hand-off writes CO2_2, is asked for by PHREEQC's name. PHREEQC is read through the punch the page's own looks use (`punchBlock`), each phase's LK_PHASE and the percent error after it; until 2026-11-10 through a USER_PUNCH of a line a number, ninety lines of PHREEQC's BASIC, which left its memory spoiled, and a database loaded checks later, in the KINETICS hand-off, fell over it (WebAssembly: memory access out of bounds) on most runs.
- **The listing beside PHREEQC, as the page asks it** (since 2026-11-10): the PHREEQC worker's listing job (`viewRun` with `listing`) on the same water handed off and run, its last water given to PHREEQC as the PHREEQC tab gives a run's -- every species PHREEQC counted within 6.2e-12 in log molality of the model's, calcite at saturation in both. The model's calcite given a log K 0.1 higher, the constant of its analytic expression: its water takes more calcite, the pH 7.30 to 7.38, every species is still within 2.0e-10 of PHREEQC's speciation of it, and PHREEQC's calcite SI is 0.100000 where the model holds it at 0. On the page (test-phreeqc-ui.py), the PHREEQC example water's run, its last water on the Composition tab beside PHREEQC: PHREEQC's molality, log gamma and the difference in the distribution of species, every species within 3.9e-6 in log molality (Fe(OH)4-, the hand-off's log K at 15 °C) and 8.3e-13 in log gamma.
- **Inverse models, through PHREEQC** (since 2026-11-09): PHREEQC's `INVERSE_MODELING` between waters of a run (`viewRun` with `only` and `inverse`), read back from what PHREEQC prints (`engine.printed`): IPhreeqc keeps its inverse models out of every selected output row -- `punch_model` ends a model with a newline, never with the row's end, so the rows hold the heading alone, in PHREEQC 3.8.7 too -- and the module now exports `SetOutputStringOn` and `GetOutputString` for it, rebuilt by `scripts/build-phreeqc-wasm.sh` (with the old exports the build gives the committed `phreeqc.js` byte for byte). A handed-off water whose calcium and carbonate come in at 1e-8 mol/kgw a second for a day: from the run's start to its end the one minimal model is calcite, 8.640e-4, its range at 5 % 7.908e-4 to 9.372e-4. PHREEQC's own waters, the second the first with 1 mmol of calcite and 0.5 of gypsum dissolved by `REACTION`: read back as those two, 1.000e-3 and 5.000e-4, with their ranges and the summary's counts. What flows in, given whole (the summary's `inflow`, each species' `left=` or else its start): a column flushed a hundred times over is that water at its far end, a minimal model of no phase at an uncertainty of 1e-6, no total adjusted. Refused with their reasons: a phase the database lacks, an uncertainty of 1, a phase going a third way. The example of it (water with CO2 through calcite and gypsum, written from PHREEQC by the hand-off and flushed for ten pore volumes): PHREEQC's model is the calcite and gypsum the column dissolved -- the outlet's carbon and sulfur over the inflow's -- to the four figures it prints, the fractions one. Two traps found making it: gypsum's two waters had PHREEQC take 0.9995 of the inflow and nudge Na, Cl and C to fit (`-mineral_water false` now, each water of a run a kilogram of water as the page keeps it); and after three pore volumes a remnant of the column's first water, with the inflow's own Na and Cl, read as calcite 0.3 % off. A hand-written text with fewer species and Davies activities came 2 % off, PHREEQC speciating its waters otherwise. In the page, after the kinetic calcite run: at 5 % the calcite PHREEQC's rate forms in a day (3.9e-7 mol) is inside the calcium's uncertainty and the minimal model has no phase, no bars drawn; at 1e-6 the model is the calcite the run formed, -3.887e-7 for the run's own -3.8869e-7; the note, the CSV and a phase the database lacks; and the example, opening once run on the PHREEQC tab with calcite 1.268e-3 and gypsum 1.470e-2.
- **What a run can be read as, against PHREEQC** (since 2026-11-09): the quantities the model works out of a handed-off water with its own activity model, against PHREEQC's numbers for the same water. A water at calcite saturation with an exchanger: pH, I, a(H2O), the dissolved totals of Ca, C, Na, S, Mg and Cl, SI(Calcite), and CaX2's, NaX's and MgX2's equivalent fractions, within 3.3e-9 (the ionic strength, PHREEQC's own convergence); zinc on Hfo's weak sites: each species' share of the sites within 9.8e-11; CO2(g) in a gas phase of a fixed volume: its partial pressure within 2.7e-8, as 10^SI.
- A `TRANSPORT` in the input becomes a column (5 cells, `SOLUTION 0` flowing in at the left) that compiles and runs; one whose cells start apart, two waters in cells 1-2 and 3-5, is written in two zones, the second in `<INITIAL>` as cells 2-4, the report naming both; one with stagnant cells (`-stagnant 1 5e-6 0.25 0.15`, another water in cells 7-11) is written with a rock matrix of one layer, every species' `Dm=` alpha/2 and the stagnant water in `<INITIAL>` with `matrix`, the report saying so; and a pH-stat, `Fix_H+ -7.5 NaOH 0.01` with `Fix_H+` in the input's PHASES, beside calcite `dissolve_only`, is written as `NaOH_Fix_H` held at `SI(Fix_H+) = -7.5` with the phase in `<PHASES>` and `Calcite ... mineral dissolve_only`, the report saying what holds what; and the column with `-multi_D true 1e-9 0.3 0 1` is written with `DIFFUSION = nernst-planck`, `DIFFUSION_GRADIENT = activity` and K+'s D 1.96e-9 times 0.3, the report saying so; each compiled and run.
- A column is offered against distance as well: each cell at its centre down the column, at one of the times looked at.
- The look takes up to 100 of the waters the run kept. How many the run kept is the solver's business, and a held run keeps fewer than fast pairs do, so the number is read off the run's own status.
- A water PHREEQC refuses is answered in PHREEQC's words, and the text is left alone.
- The PHREEQC tab's chart starts at the water's pH, 7.4 at 15 °C. Before the cache was cleared in this test, a cached worker script ran at 25 °C and gave 7.4012, which is how the test caught it.
- The CSV has a row for each water.
- An earlier look says it is of the run before.
- A database opened is read at once, and a file that is no database is refused.
- All of it also works with no Worker, and from the disk.

PHREEQC's worker fetches its scripts itself, so the test clears the browser's whole cache before each page: turning the cache off for the page does not reach the worker.

## What test-model.js checks, and why those things

A reactive-transport code can be wrong in a way that still looks like
chemistry — the curves bend the right way and settle somewhere plausible — so
nothing here is judged by eye or against a stored result. Every check is
against something independent:

**Chemistry.** A → B → C against the closed solution; 2A → B against the
second-order form, which is the one that catches a stoichiometric coefficient
not being read as an order; a Michaelis–Menten law read straight off the rhs;
a source and a sink reaching source/sink; a reversible pair settling at
kf/kb while conserving A + B; and a `fixed` species driving a rate without
being consumed.

**The functions.** Every one the Help lists, each given an argument whose
answer is only right if the function is the one it claims to be (`log` is the
natural one, `ramp` is zero below zero, `sign` is −1 below), and each checked
against a central difference as well — a function is not much use in a rate law
if it cannot be differentiated. Then the three that are refused there, each for
its own reason, and the same three working in `<PARAMETERS>`, which is where
they are allowed.

**The two ends of the column.** The third-type (`robin`/`cauchy`) inlet and the
`free` outlet are Danckwerts' pair, and together they make the column a closed
account: what the flow brings in, less what it takes out, is all that changes
the mass. That is an identity, so it is checked as one — it holds to 6e-16,
while a `dirichlet` inlet is 6.7 % out, because it adds a diffusive flux on top
of what the water carries. Then the profile against van Genuchten and Alves'
flux-type closed solution, at two grids, since the error has to fall by four per
doubling or it is the formulation that is wrong rather than the resolution; and
the same comparison for a `dirichlet` inlet, which is solving a different
problem and must not come out looking like this one.

That solution needs an `erfc` the rest of this file does not. Its third term
multiplies `erfc` by `exp(v·x/D)`, which reaches e⁵⁰ at the far end of the test
column, and Abramowitz & Stegun 7.1.26 — used everywhere else here — carries an
*absolute* error bound of 1.5e-7, which that factor turns into 1e14. The block
uses the Numerical Recipes form instead, whose bound is fractional.

**A reservoir at an end** (`LEFT = reservoir`, since 2026-11-11). A face held at
the water of a reservoir that the chemistry changes and the column does not
drain: a cell outside the column with the model's chemistry and no transport.
Each check is against something that code does not produce:

- skbrtm's benchmark 5, written out again: A → B diffusing in from a face at
  A₀·exp(−k₀t), against its closed solution, exp(−k₀t) times Crank's slab. On
  100 power-law cells it is 7.7e-5, 1.4e-5, 8.3e-6 and 1.2e-8 of A₀ at 1, 10,
  30 and 100 days.
- The reservoir's own water against the batch solution, to 1e-11.
- With the flow as well: exp(−k₀t) times the same column at a dirichlet face
  where nothing reacts. That is an identity of the discrete equations, and it
  holds to 1e-10. With a rock matrix behind the column and the decay on the
  whole inventory, it holds in the water and the rock alike, to 7e-11.
- What the column gains against what crosses its two ends, the left face read
  off the reservoir: 6e-15.
- With nothing reacting it is the dirichlet face; at the right-hand end, the
  left one mirrored.
- The Jacobian against a difference, with a second-order reaction in the
  reservoir and the column. Nernst-Planck across the face against the
  dirichlet face's rates, and its Jacobian against a difference. The activity
  gradient's Jacobian against the dirichlet face's, entry for entry; it holds
  ln γ at any face, so a difference finds it out on a plain column too.
- Equilibria held all through the run, in the reservoir as in the column: its
  water at the end against a batch run of the same water, to 7e-15.
- `<INITIAL>` naming `left`: over `left=`, an expression read as the cell
  beside it, `fixed` holding it there alone; refused where that end is no
  reservoir, and with `matrix`.
- The worker's budget: a tracer through the reservoir's face against the
  dirichlet face's, to the solver's tolerance. A and B together close within
  the budget's own summing of the flux over the stored points, 2e-5 at
  rtol 1e-8, which a dirichlet face leaves open just the same.

**Transport.** Diffusion against `erfc`, and not at one grid: the error has to
fall by four each time the cells are doubled, which is a far stronger statement
than any single number being close. Advection against Ogata–Banks, compared at
`D + v·Δx/2` because upwind differencing adds exactly that much numerical
dispersion. Mass in a closed box, on both the linear and the log grid, to
within 1e-12. A closed box relaxing flat to the mean. And a species with no
diffusion coefficient staying exactly where it was put.

**The Jacobian.** Against a central difference, on the built-in model in both
modes and in two states. Central rather than forward for a specific reason: a
rate quadratic in a species — and the radiolysis set is full of them — has a
true derivative of zero where that species is zero, and a forward difference
returns `k·h` there. That is an error in the question, not in the Jacobian, and
an earlier version of the check reported hundreds of them.

**Dual porosity: a rock matrix beside the fracture.** Two references that know
nothing of each other. First, SKB's own implementation of the formulation in
TR-19-06 (FARFCOMP), whose layer thicknesses, rates and release curves were
dumped once into `farf-fixture.json` — the same dump the `kompartment` tool
holds its far-field block to, from which this copy was taken. Those cases say
`MATRIX_GRID = reference`, FARFCOMP's own layers, which are no longer the
page's default. The layer
thicknesses come out bit for bit (the FARFCOMP root-find is reproduced step for
step), every rate — advection, dispersion, wall exchange, layer to layer — to
one part in 10¹⁴ in five cases, twenty layers from 4×10⁻⁸ m among them, and two
release curves to 2×10⁻⁹ and 2×10⁻¹⁰ against a bar of 10⁻⁷ at rtol 10⁻⁹. Second,
Neretnieks' closed solution for a step into a fracture beside a semi-infinite
matrix, which the breakthrough follows and converges on at the upwind scheme's
first order as the fracture is refined. Then a closed dual-porosity box
conserving mass to 10⁻¹⁴ and settling to exactly the capacity share between
water and rock; a first-order loss in the rock running at ε·k/R_m on the water
and at k on the inventory; and the refusals and warnings.

**A far-field path as Kompartment has it.** The page's defaults for a rock
matrix are Kompartment's for a new far-field path: twelve layers matched to
diffusion into the rock, the first worked out from the path, and the rock going
on past the release point (`RIGHT = semi-infinite`, with the cells past it
counted as Kompartment counts them). Checked without Kompartment: the defaults
themselves; `TRAVEL_TIME`, `TRANSPORT_RESISTANCE`, `Kd=` and `Kdf=` read back
as the velocity, the wetted surface and the capacities they stand for, and the
refusals where two of them disagree; the extra cells inheriting what a line
reaching the last cell gives, and not a source of the first; the flux through
each end against the column's own balance — what the cells gain is what crosses
the left end less what crosses the right, to 10⁻¹⁴, for six pairs of ends and a
rock matrix; and the model's transfer function, (sI − J)⁻¹ at real s with the
release read off it, against FARF31's exact one from TR 90-01: 2.4 % in ln T
where T is above e⁻⁵, against 9 % for the old layers and a Danckwerts outlet;
four times closer on 40 cells, which is the second order of the fracture's
central scheme; and twelve matched layers no worse than twenty. Then, last
because Kompartment's module is an ES module the test has to wait for, section
9 reads `kompartment/src/domain/farfield.js` itself, on five paths among which
its own far-field example: the matched layers bit for bit, the count of cells
past the release point over twenty pairs of N and Pe, every entry of its
transport matrix and of its chain's ingrowth seen through the capacities
(A = C·J·C⁻¹, C = R in the fracture and a_w·R_m·d_j in layer j) to 5×10⁻¹⁶, and
its release weights.

Three things the block taught, kept as comments:

* The Neretnieks convergence levelled off at 10⁻² whatever the fracture did,
  because the *matrix* grid was the floor: 24 layers from 10⁻⁴ m. With 80 from
  10⁻⁶ m the fracture's own first order shows through (ratios 1.87, 1.83,
  1.71). A convergence test has to know which grid it is refining.
* A `<PARAMETERS>` line naming a fracture cell also applied to the rock behind
  it, so a unit source into the water also fed every layer of rock — and a
  unit release delivered 5.5, which is exactly 1 + a_w·ε_m·d_max. The `fracture`
  and `matrix` words on those lines exist because of it.
* Decay written as a rate on the water is wrong by more than half in a sorbing
  matrix (0.717 against 0.116), because it should remove the same share of the
  sorbed mass too. `on = inventory` is the difference, and the "sorbing" release
  case is what proves it: to 2×10⁻¹⁰ one way, 0.6 out the other.

**Sources that follow the clock: a release history.** `t` in a rate law is the
time, checked against the closed form of a loss that fades, k·exp(−t/τ)·[A]; a
Jacobian that reads it is not called constant; a parameter may not be called
`t`. A `<TABLE>` is read in a rate law at the clock -- `name(t)`, with a column
by name or number when it has several, and `loglog` for a power law between
rows -- and never at a concentration. The run is started again at every corner
of such a table (`model.breaks`, handed to the driver), and the check that this
matters is a pulse of ten years in five thousand: with the restarts it is
integrated to the table's own integral, without them the NDF has grown its
steps over the quiet stretch before it and steps clean over it -- the store
comes out exactly zero. The corners follow the argument when it is a line in
`t`, and there are none for one that is not. End to end, a release history
that rises, holds and falls over twenty thousand years, through Kompartment's
default far-field path, is put beside FARF31.html's convolution of the same
history with the path's exact response: for Ra-226 the peak is 30 %, 7.3 % and
1.8 % high on 20, 40 and 80 cells, the second order of the fracture's scheme.

**What skbrtm's databases needed.** Reading skbrtm-main's examples called for
six things the format lacked, and each is checked against a number worked out
independently rather than against the code's own output:

* *The syntax.* `Fe(OH)3` as a name; `[A]**(2/3)` and `10**-3` in a law, and an
  exponent that is a constant of the line or a parameter varying by cell, each
  with a Jacobian that agrees with a difference; `kr = 1.33*10**12` and
  `kb = kf/4` as constants; `c = [B]` as an alias, whose extra Jacobian entry,
  `-k[A]`, is read out of the pattern; arithmetic in settings and species
  lines; and skbrtm's biotite rate law, passed through verbatim, against its
  value by hand. Since 2026-11-08 a name on the line may stand for an expression
  that reads the water (`x = c*(1 - [B]/cmax)`, `y = exp(-0.1*b2)`), the law the
  same as written out (to the bit) with its Jacobian; a name used before it is
  given, one a rate law reads already (`TK = [B]`) and one given twice are
  refused; and a power's exponent may read the temperature and be negated,
  `10^(-pk)` with pk in TK and `[A]^(-n)`: the derivative of a negated
  exponent was not folded to 0, and `-(n)` read as depending on what n did not.
* *The grids.* A power-law grid's faces at `L(i/N)^3` to 1e-20, `FACES` as a list
  and as an expression in `i`, `GRID_RATIO`, and `SURFACE_LAYER`'s first cell; a
  closed power-law column conserving its content to 4e-15; and skbrtm's own b1
  benchmark -- Crank's slab -- on it: 1.4e-4 at ten days with 50 cells, and
  exactly four times closer with 100, which is second order on a grid this
  uneven.
* *A surface.* `w`, `xl` and `xr` are the cell's width and faces; a site
  density written per m² over `w` is the same amount per m² on three grids; and
  the reason for `SURFACE_LAYER`: a second-order surface reaction whose product
  per m² moves 69 % between 10, 20 and 40 cells without it, and 2.5e-6 % with
  it.
* *Tables.* Interpolated at the cell centres to hand-worked values, held flat
  beyond the ends, the same through `interp(t, x)`, and a `log` table a quarter
  of the way along giving `0.1^(1/4)`; refused when x does not increase, a log
  table holds a zero, or a rate law reads one.
* *Held cells.* A cell held with `fixed` in `<INITIAL>` stays at 1 while feeding
  its neighbours; a species held in cells 5-9 stays at zero there while the
  reaction makes it everywhere else and the reactant still decays under it.
* *The importer.* A small skbrtm case written into the test -- script order and
  time span, decimal commas, bounds, a name in two cases, `<=` and a bare `=`,
  skbrtm's `(kr/kh)`, `boundary_values`, `units:` with a colon, a lone `cell_id`,
  a species constant in one cell, a value per cell width -- opens, compiles and
  runs, with each of skbrtm's four misreadings named. When skbrtm-main is in
  `~/Downloads`, its five cases are opened and run as well. A Dirichlet end
  where something reacts opens as a reservoir holding what skbrtm puts in that
  cell: `boundary_values`, the value per cell width, the `constant` species,
  held there and nowhere else. The first cell starts as the column does, and
  the reservoir's A decays as skbrtm's held cell does. Where nothing reacts
  the end is a face held at that value. One cell in no SOLUTION is said as
  one, and a constant of the parameters dict is written as a number is.

**The examples the page offers.** Every one of them is compiled and run here,
so the picker cannot hand a reader something broken, and the two with a
published answer are held to it: Robertson (1966) at *t* = 0.4 against
0.9851721, 3.3864e-5, 0.0147939, with *A* + *B* + *C* never leaving 1 by more
than 8e-15; and the matrix-diffusion example against the `erfc` its own comment
claims. The U-238 chain is checked on the thing that makes it a chain — deep in
the rock, where nothing flows, each short-lived daughter sits at its parent's
activity, λ·R_m·C, to within 0.2 %, across capacities from R_m = 1.2 to 143,
which puts the concentrations themselves a hundred times apart. In the fracture
it does not, because flow carries a nuclide away before its daughter catches up.

Until 2026-10-06 this check compared concentrations, λ_parent·C_parent with
λ_daughter·C_daughter, and passed to 0.06 % — because `on = inventory` made a
daughter of the parent's *concentration* times the daughter's own capacity, so
a daughter that sorbs harder than its parent was born with more atoms than the
parent lost (a stable daughter with R_m 100 gained 200 times what a parent with
R_m 0.5 lost). Comparing the chain's ingrowth with Kompartment's, entry for
entry, is what showed it. A daughter is now born of the parent's whole
inventory and takes up its own share, as in Kompartment and FARF31, and a
closed rock cell keeps its atoms to 10⁻¹⁶.

That last check was first written the other way round — that decay written
`on = water` would leave *more* Th-230 in the rock, since its own removal is
throttled by ε/R_m. It leaves 3e6 times *less*, because the same throttle is on
its production from U-234, and the source dominates. The secular-equilibrium
form says something true about the chain instead of something plausible about
one term of it.

**The time unit.** `TIME_UNIT` converts nothing, so the check is that two models
differing only in the word give the same numbers, that every spelling resolves
(`s`, `min`, `h`, `d`, `a`, `yr`, `YEARS`), and that one it does not know is
refused.

**The pattern the Jacobian tab draws.** The whole pattern cannot be posted to
the page for a long column, so the worker folds it into three blocks — a cell
against itself and against each of its two neighbours. `test-model.js` checks
that those three put the matrix back together exactly (20×363 + 19×27 + 19×27 =
8286, the model's own `nnz`) and that nothing reaches past one neighbour, so the
picture cannot be silently incomplete. `test-ui.py` then counts painted pixels
on the canvas: an earlier version filled each cell's block solid, which made a
batch model a single square and told the reader nothing, and a filled block is
exactly what a pixel count catches.

Read the counts it prints with one thing in mind. An entry far below the
largest in its column cannot be measured by differencing at all: the change it
makes to the row is lost under the change the big ones make. Those are counted
as *below the noise floor* rather than as failures, and the floor is derived —
roughly `eps·|f_r|/h` — rather than guessed at. Guessing it is what let an
earlier version call an exact zero a disagreement.

**Per-cell parameters.** A dose profile `1.0·exp(-x/3e-5)` against the analytic
profile it is meant to be, in every cell, with the Jacobian still exact; a later
line overriding an earlier one; and a name that is neither parameter nor species
still refused.

**The mass matrix.** `R=2.5` against `exp(-kt/R)`, which is the statement that R
divides the reactions and not just the transport; `R=4` against `erfc` at `D/R`,
which is the statement that it divides the transport too; a per-cell `R` taken
from a parameter; and `R=0` refused rather than quietly turned into an algebraic
equation.

**Equilibrium.** Water autoprotolysis from a badly wrong start, checked on three
counts at once — the product reaches `Kw`, the two come out equal, and the charge
difference is the one it began with — because a speciation routine that hits `K`
by quietly losing mass is the likely way for this to be wrong. Then a carbonate
system of three coupled equilibria, where no hand-written start is right, with
all three `K`, the total carbon and the charge all checked. Then `kf` given as
well, so the pair is integrated: the product has to stay at `K` while the rest
of the chemistry carries on unchanged. Then a transport model, to catch a
speciation that only ever ran in cell 0.

What the conserved totals are is worked out from the stoichiometry alone — the
left null space of the equilibrium matrix — so the check that the basis comes
out as expected is a check on that derivation, not on a table of elements the
page does not have.

**Minerals at saturation** (`mineral`). What a mineral line and a relation
with one may say (no `D`, one mineral to a relation and one relation to a
mineral, no `kf`, never held), and `immobile` keeping a species where advection
carries one with no `D`. The start precipitates calcite from a supersaturated
water (SI 0 to 2e-15, Ca and C conserved) and dissolves what little there is in
an undersaturated one. Held, acid dissolves calcite at saturation (to 2e-15,
the totals to 2e-15) until one event where the last of it goes. The event's
instant is checked apart: the start with all its calcite put in the water and
the acid added by then, speciated afresh, is just saturated with none of it
(SI 9e-11). A point stored before the event is read back with its calcite; a
Ca source precipitates calcite at an event; a column's acid front dissolves it
cell by cell, ten events in order; and under `ACTIVITY` the saturation is in
activities. The Jacobian is checked with the mineral there and with none.

A held column's stored points are read back cell by cell (the run's own
modes found again from each state): at saturation wherever there is calcite,
and none at all where there is not. That check guards two faults the PHREEQC
tab showed: an absent mineral's amount was iterated towards zero with a damped
step and left at 1e-29, which read as "some calcite" in a water at SI -7; and
the polish stopped at the first cell whose residual stayed above a tolerance
set under rounding (1e-16 against relations of size 30), leaving every later
cell as the solver had it. The amount is now set to zero, the tolerance is not
below 1e-13, and every cell is settled whatever another does.

**Activities and saturation in rate laws** (`{X}`, `I`, `SI()`, `SR()`,
`<PHASES>`). Each against the same quantity worked out apart: `{H+}{Ca+2}` the
coefficients times the concentrations, `I` the ionic strength (a parameter
called I wins), `{X}` the concentration without `ACTIVITY`, `SI(Calcite)`
log(IAP/K) in activities and 0 for a mineral held in `<EQUILIBRIUM>` while
there is any. Calcite dissolving at `k*(1 - SR(Calcite))` ends on the state
calcite held at saturation has, every species to 5e-15, and the Jacobian
follows each quantity through every ion it reads. A phase that is nowhere is
refused.

**Diffusion that keeps the charge** (`DIFFUSION = nernst-planck`). A step
of HCl in a closed column, on a column the spread does not reach the ends of:
each species on its own, the acid runs ahead of its chloride (a sixth of the
step in charge) at its own D (5e-4 of the closed solution); coupled, H+ and
Cl- spread together at 2 D_H D_Cl/(D_H + D_Cl), within 2.4e-5 of the closed
solution, the water neutral to 3e-14. Equal coefficients in a neutral water
are left as they were (1.5e-15), the word is read, and the Jacobian holds,
every ion against every other across each face, beside equilibria held too.
The hand-off writes the setting with each species' own D (`-dw`) and not with
one D for all (test-phreeqc.js). At a Dirichlet end the coupling acts too
(since 2026-11-09; until then the end kept each species on its own): acid held
against a salt water puts no charge into the first cell (4e-16 of the largest
flux, where each species on its own puts in 0.86 of it), its Jacobian with
it. `DIFFUSION_GRADIENT = activity`, PHREEQC's multicomponent factor on each
difference, 1 + dln gamma/dln C between the two cells: by hand from the
cells' Davies gammas, every rate to 1.3e-14, with K+ nearly level where the
ionic strength is not held at 2.25 and a trace of Br- on one side (1e-15
against 1e-3) at 1; refused without ACTIVITY; acid against salt, coupled and
down the activities, neutral to 7e-15 and its chloride kept.

**What a run can be read as** (QUANTITIES, `<OUTPUT>`, `<DATA>`, since
2026-11-09). A species' name read as its formula: the charge left off,
parentheses, From PHREEQC's `UO2_2`, Gapon's `Ca0.5X`, a surface's `Hfo_w`, a
hydrate, and `e-` and `(Ca` as no formula. Each quantity of a carbonate water
under Davies against the same worked out by hand from the model's own
activity coefficients, to 1e-12: pH, I, the charge balance, the totals of C,
Ca and Na (Cl, in one species, has none: its total is the species), SI of a
phase of `<PHASES>`, a log activity, and `<OUTPUT>` -- an alkalinity, an
output of an output, `{H+}`, `SI()` and `{H2O}`. In a column, `x` is the
cell's centre, a parameter the cell's and `t` the time asked at. Seven
`<OUTPUT>` lines and six `<DATA>` tables refused, each with its reason.
Without ACTIVITY the noActivity model marks no species a solute (its water's
activity being 1), so the quantities say for themselves what is dissolved,
and list no log activity: it would be the log of the species itself. So
does the worker, for what a diagram can hold. An exchanger without ACTIVITY
makes that model for itself, and the water is still the water (since
2026-11-10, where it had no pH, no totals and nothing dissolved in the
composition): its pH 7, its ionic strength and its dissolved calcium among
the quantities, the calcium in the water and on the exchanger, every
species dissolved among the solutes a diagram can hold.
What each species is made of (since 2026-11-09, the Composition tab): in a
carbonate and sulfate water with calcite and gypsum held at saturation, a
dolomite dissolving at a rate and an exchanger, each element's species --
a solute's and an exchanged one's from the name, a mineral's from its
relation or its reaction (gypsum's water left out, dolomite two C), no H, O
or X; the sulfate's sulfur (SO4-2 and CaSO4, not HS-) and the carbonate's
equivalents (CO3-2 and CaCO3 two, HCO3- and CaHCO3+ one, CO2 none); and the
two quantities they make, `alk(CO3)` and `tot(SO4)`, by hand to 1e-14.
Valence states and couples (since 2026-11-10, the redox ladder): each
species' state of each element in it, from a name that is a formula with
one element left over once H is +1 and O -2 (Fe(OH)3- iron(2), S2O3-2
sulfur(2), a mean) and from the relations -- a complex its ions' (FeSO4
iron(2) and sulfur(6), FeHS+ sulfur(-2)), a mineral and a species on an
exchanger their ions' (calcite, FeX2), pyrolusite manganese(4) from the
electrons its half-reaction moves; a reaction with O2 tells nothing, which
would make pyrite's sulfur sulfur(6), so pyrite's iron and sulfur are left
untold. The couples, each relation with the electron in it between two
states, the oxidised first: NO3-/NO2-, NO3-/N2, NO3-/NH4+, SO4-2/HS-,
SO4-2/S2O3-2, CO3-2/CH4, Fe+3/Fe+2 and Pyrolusite/Mn+2, the water's own O
and H not among them.
Each element's total in each of its valence states (since 2026-11-10),
PHREEQC's TOT("Fe(2)"), the oxidised first: on the redox zones example's
water, nitrogen in three, iron, sulfur and carbon in two, each the sum of
its species by hand to 1e-15; manganese dissolved in one alone, so none;
and none in a model without the electron, the radiolysis default, whose
radicals and peroxides (CO3-, C2O6-2) are carbon(5) by formula.
The example run with steps a tenth of the run long: every point shown
keeps its iron and its manganese to 1e-12 and is its own speciation:
re-speciated from what it shows (`RtmModel.speciate`), each settles at
its first evaluation, its relations and totals holding there to 1e-13 --
the one a step after the pyrolusite has dissolved away among them, whose
FeS(ppt), none in the run, is 3e-45 in the state. (The one polishing step
moves a trace species by what the point's conditioning lets it: 2.8e-8 of
nitrate at 6e-19 at the moment the pyrolusite is gone.) Read as some, before 2026-11-10, its
speciation did not settle and the point was shown as the solver left it,
and before that as the speciation left it, the ferrihydrite dissolved
into the water as iron(3), the pe at 8 between 5.7 and 4.6 and the iron
5.4e-4 off. And the zones in order: oxygen
gone by day 30, nitrate by 52, manganese(2) and iron(2) then, the
ferrihydrite gone by 55, FeS holding the iron and the sulfate reduced by
160, methane. `MAX_STEP`: the same example, `MAX_STEP = 1`, run by the
worker, no step longer than a day and 193 points; the panel's Maximum
step, 5 days, in its place where it is given.
Redox zones along a plume (since 2026-11-10), the example run by the
worker as the page runs it, 3021 points: every tenth point shown is its
own speciation, re-speciated from what it shows settling at its first
evaluation, its relations and totals holding there to 1.5e-13 (the
polishing step moving nitrate at 1e-25 by 7e-7 where a front passes). A
mineral the run holds at none is read back as none: FeS(ppt)
in the oxic water ahead of the plume is 1e-33 or so in the state, the
arithmetic's, and read as some it was held at saturation where it cannot
be -- before 2026-11-10 223 of every tenth point's 303 did not settle and
were shown as the solver left them, the pe up to 6 % off, at 110 ms a
point, and 206 of them re-speciated did not settle either; 1.4 ms now. And the zones from the inlet by the pe -- methane
below -2.5, iron below 3, manganese below 10, nitrate below 12.5, the
oxygen -- at days 20, 30 and 40, each zone's far edge further downstream
each time: 3, 8, 12 and 14 m; 7, 12, 18 and 20; 11, 16, 24 and 26.
The plume's start with more calcite (since 2026-11-10): the example with
5e-3, 1e-2, 0.1 and 1 mol/kgw of calcite compiles and starts in a few
iterations a cell, 7 at most, each cell's water taking the same calcite,
7.43e-4 mol, whatever there is of it. Before, a species that starts at
none was placed by any relation whose other species were there, a
mineral's at none among them: FeS(ppt) at none in the oxic water put
Fe+2 at e^302, capped at the largest total, and every iron species after
it; the capped steps took 95 iterations a cell at 5e-3 and did not settle
in a hundred at 1e-2, which was reported as a singular matrix. A start
that does not settle (three iterations allowed) says so, not that the
matrix is singular.
The water as PHREEQC lists it (since 2026-11-10), as the worker answers
the Composition tab: the redox zones example's water at its last stored
point -- a ln gamma for each species and every quantity -- each phase's
log IAP less its log K its SI, to 8.9e-16 (pyrolusite, ferrihydrite and
FeS); under Davies every ion of one charge one gamma, over five charges;
the carbonate example, without ACTIVITY, every gamma 1; a run the worker
does not have, said so, for the page to send it.
A budget over the run (since 2026-11-10), as the worker answers the
Composition tab: what the column holds of an element or a species at
each stored point, each species weighed by its capacity and its cell's
water as the model's own balance is (a rock layer by the fracture's wall
area per water times its thickness), and what crosses each end summed over
the stored points. What no reaction makes or takes closes: a tracer to
2.4e-7 of what was there and came in, a tracer into the rock matrix, its
rock band among the bands, to 6.4e-6, the acid column's calcium between
the water and the calcite, all of the calcite dissolving, to 2.0e-6. The
redox zones batch's carbon made by its source, 1.6e-3, 1e-5 a day for 160
days, to 1e-9. And at a decaying nuclide's steady state (on its
inventory, R = 10 from a parameter) what comes in less what goes out is
k times what the column holds to 2.0e-10 -- the weights against the
fluxes through the ends, with no summing over stored points in it.
A nuclide's name is one atom of its element (since 2026-11-10): an
element and a number between 0.75 and 1.35 times its atomic weight is a
mass number -- U238, Ra226+2, C14, Cl36, He4, I129, Cs135, and tritium's
H3 -- where a formula's count is far from it and stays a count: O2, H2,
S8, C60, CaCl2. The U-238 chain's tot(U) is then its two uranium
nuclides' sum, by hand, and its uranium's budget the budgets of U238 and
U234 added, to 1.8e-15; the far field's Ra226 and the release history's
I129 and Cs135 each one atom. Until then each counted as its mass number
of atoms: tot(U) was 238 [U238] + 234 [U234].
What each species weighs (since 2026-11-10), for a concentration shown in
mg/kgw: by its name and the standard atomic weights -- Ca+2 40.078,
CaHCO3+ 101.094, CO2(g) 44.009, CaSO4:2H2O 172.164, UO2_2(OH)2+2 -- and
a nuclide by its mass number, U238 238, C14 14, H3 3; none for X-, CaX2,
Hfo_wOH, Tracer or the electron. A mineral by what its relation makes of
it, the water in it counted and the electron weighing nothing, as by
hand: ferrihydrite as Fe(OH)3, 106.866, pyrolusite as MnO2, 86.936, from
Pyrolusite + 4 H+ + 2 e- <=> Mn+2 + 2 H2O, FeS(ppt) 87.905, siderite
115.853, calcite 100.086, gypsum with its two waters; on a surface none.
The worker's summary carries them for the page.
A pore volume (since 2026-11-11), for a time axis counted in them: the
summary's travel time, TRAVEL_TIME where it is given, else LENGTH over
the pore water's speed |VELOCITY|/POROSITY, as by hand -- the freshening
column 2e4 s, the far field 100 a, the tracer 1e6 s, 0.5 m at 0.002 m/h
through a porosity of 0.4 100 h, the same flowing to the left; none where
the water stands, nor in a batch.
What each reaction does (since 2026-11-11): two quantities for each
`<REACTIONS>` line, its rate (on the right, mol/kgw a time unit, or per
time unit without ACTIVITY) and its extent (on the left with the amounts),
named by the line's equation. A first-order decay A => B at k 0.1 a day
over 200 days: its rate k [A] at every stored point to the last digit,
from the code the solver runs; its extent, the rate summed over the stored
points by the trapezoidal rule, A's start less A to 2e-4 of the start
(4.7e-5 measured over 123 points). A reversible C <=> D at kf 0.3 and
kb 0.1: its rate kf [C] - kb [D] exactly, and 1.4e-16 of its first once
it has settled. The plume: its organic carbon's extent, each cell's
times its width and summed over the column, what the budget counts the
reactions as having taken of CH2O, to 1e-6 (1.0e-7 measured): two sums
over the same stored points, the one of the rates, the other of what the
column holds and what crosses its ends.
The budget by each reaction (since 2026-11-11): what each `<REACTIONS>`
line made and took of what a budget is of, its part of the rate of change
the derivative gives it, weighed as the budget weighs it, summed over the
stored points; a line and one written apart that undoes it one reaction.
On the plume, while the worker keeps its run: CH2O's one line all of what
the reactions made of it, to 1e-6 (1.0e-7 measured); carbon, all of it,
made and taken by no line, the line moving it from CH2O to the carbonate;
H+ made six to each CH2O taken, to 1e-12 (1.2e-15), and as much taken
on by the relations, to 7e-6 of it, as they take most of the CO3-2; at cell 5
what the line took of CH2O at every stored point its rate, and its sum
its extent, to the last digit. A pair written apart, A => B and B => A,
does of B what C <=> D at the same constants does of D, to the last digit
measured. A chain A => B => C over 267 stored points: of B, line 1 made
A's start less A and line 2 took C, to 3e-4 of A's start (1.1e-4 and
5.0e-5), neither the other way. The built-in model, which has no
relations: for each of the 32 species a line moves, the reactions'
parts together are what the budget counts the reactions as having made,
to 2e-5 of what they made and took (5.1e-6 the worst).
What the relations moved, relation by relation (since 2026-11-11): for
every species, what the budget counts the reactions as having made less
what the lines made is what the relations moved of it; each relation's
extent is read off the balance of a species of its own, the one fewest
relations share. On the plume, for every species, the lines', the
relations' parts and the summing's error add up to the budget's, the
error under 2e-5 of what was made and taken (1.1e-6, Ca+2, the worst; a
least-squares fit over every species, tried first, let the big species'
errors spread into small relations' extents, NO2-'s as large as its own
flows); HCO3-, which only its own relation makes, all of it from that
relation, to the last digit; carbon, iron and calcium, all of each, moved
by no relation; CO3-2 taken on most into siderite. An acid added at a
steady rate to a water of the test's own held at saturation with
calcite: the calcite relation all that made Ca+2, the calcite dissolved
at every stored point to 1e-12 of it (6.8e-15), and H+ made by the line,
1e-4, and taken by the water, the bicarbonate and the CO2 relations, to
1e-12 of it (6.8e-16).
Each constant in turn (since 2026-11-11): the model as written, then each
constant raised and lowered 1 % of itself, one at a time (`rtmEach`); how
much a result moves is the change in its logarithm over the change in the
constant's. A decay A => B at k 0.1 for 10 days beside a C => D that A
never reads: A at the end, A0 e^-kT, moves -kT = -1 per cent for each per
cent of k, to 1e-4 (4.3e-8), and not for the other's (3.1e-8). A chain
A => B => C at k1 0.4 and k2 0.15 for 5: B's two the closed form's,
0.203102 and -0.451163, to 1e-4 (3.0e-5, the 2 % central difference's
own), and the closed form's own central difference to 1e-5 (1.8e-6, the
solver's). kk, a parameter a rate law reads, as a line's constant. The
built-in model's H2O2 at the end at the fuel surface: up 0.94 per cent
with the radiolysis that makes it, k = G*DOSE, G and DOSE alike to 1e-5
(1.3e-6: G and DOSE raised 1 % give products a bit apart, and the solver
takes 865 steps and 871); down with the three that take most of it. The
whole ranking of the built-in model, 135 constants and 271 runs, takes
218 s and is not in the test: 22 move H2O2 at the fuel surface by more
than 0.01 per cent for 1 %.
Each log K in turn (since 2026-11-11): every relation's and phase's log K
moved by log10 1.01 either way, its K 1 % more and 1 % less, the page
handing the worker each run's value; how much a result moves is the
change in its logarithm over K's. Calcite into water with nothing but its
ions: Ca = sqrt K (1.7e-15), half a per cent for each per cent of K, to
1e-9 (1.2e-13). An ion pair A+ + B- <=> AB at log K 2 with 0.01 of each:
the free A+ the closed form's, x + K x^2 = 0.01, to the last digit; its
exponent, -0.276392907, the closed form's own central difference to the
last digit and its derivative, -K x/(1 + 2 K x) = -0.276393202, to 1e-6
(3e-7, the difference's own).
A mineral's dissolution front, as the Composition tab follows it (since
2026-11-11): halite in a column of the test's own, 20 cells over 1 m,
fresh water flowing in at 1e-5 m/s, the water at saturation holding S =
sqrt K = 0.1 of Na+ and of Cl-. The length of column cleared of halite,
each cell its width times the share of its first amount gone, moves over
the second half of the run at v S/(S + M) to 2 %, M the halite in each
kilogram of water: 0.4, 5.5e-3 fast, and 0.8, 4.4e-3 slow; at the end it
is 0.4047 m from the inlet for 0.4000, and 0.2251 for 0.2222, within a
cell. On 100 cells the speed was 2.4e-4 off, but a run took 200 s.
`speciate` for a diagram: one cell of a column speciated alone, the other
left exactly as it was, and the carbon's total set there to 0.05 mol/kgw
through the conserved total that carries it, to 1e-12, the relations held.
A sweep's text (`RtmModel.withValue`, since 2026-11-09): a setting the
text gives and one it does not, added to `<SETTINGS>`; a species' start, its
comment kept; an exchanger's capacity after its word; a start where the line
has none; what flows in, and where nothing did; every line of a parameter,
its cells and scope kept; a parameter that is not there refused; and the
number the text gives each (`RtmModel.valueIn`), null where it gives none --
an exchanger's capacity, not what it holds at the start. A sweep of a
parameter and a setting, every pair run by the worker's handler: A decays as
exp(-kk t) in each, the run the same to the bit as the text with those
numbers run by itself, and a TEND below zero refused for its runs alone.
A fit (since 2026-11-09, the worker's `fit`): kk of a first-order decay
measured exactly, from 0.1 to 0.25 to the solver's tolerance; measured with a
pattern of noise, kk and its standard error against the hand's (the residual,
log10 of the run over the measurement, is straight in kk: kk to 2e-8, the
standard error to 1e-6 by central differences at the end -- forward ones were
0.1 % off, half a step's bias); kk and the start of A together; a relation's
log K and a reaction's own constant together (B over A is K, the total grows
by q); a velocity fitted to a front measured along a column at one time; and
four refusals with their reasons.
Runs given one by one, as the uncertainty bands draw them (since
2026-11-09): each read at the same times asked for, A exp(-kk t) at each to
2.4e-10, the same to the bit as the text run by itself at those times.
The boundaries of a map (since 2026-11-09, the worker's `diagramBounds`):
iron's Fe+2, Fe+3, FeOH+, FeOH+2 and Fe(OH)2+ without activity
coefficients, where each species is a line in pH and pe from the log Ks, so
each boundary is a straight line and each point where three fields meet is
where two cross. On a grid of 11 x 9 every boundary point is on its line to
1.8e-15 and the three meeting points within 1.8e-15; on 101 x 81, where the
FeOH+2/Fe(OH)2+ boundary lies along the grid line at pH 3.48, to 2.8e-11
(two species within 1e-10 are a tie, the first taken: without that the
points along the line fell to either field as the rounding had it, the
refinement found boundaries along the grid line, and the map lost 7e-6 of
its area); on one with the point where three meet on a grid point, 3.5e-11;
and on 3 x 3 whose middle is that point, 2.9e-11. Each time the seven
boundaries are the same and the fields' areas are the frame's to 1e-15. A
crossing found at a corner of the grid has the corner's coordinates: tidying
an outline took both for points on a straight line and dropped the corner
(25 % of the area gone on 3 x 3), and now goes a point at a time. A mineral
stability map of calcite and gypsum of `<PHASES>`, calcium held, no
complexes: the boundaries where their indices are zero or the same to
3.3e-11, the point all three meet to 1e-15 (when a phase counted as over
saturation at an index of -1e-6, as the page's points do, the boundaries
were 1e-6 off; a mineral of the model's own counts by its amount instead).
Of the water as a run leaves it: the run kept, a run the worker no longer
has answered `missing`, and the run sent the same to the bit.
Eh (since 2026-11-10, `RtmModel.ehPerPe`): the quantity beside pe, in V,
ln 10 RT/F times the pe with PHREEQC's R and F at the cell's temperature --
in a column whose cells are at 10, 45 and 80 C and in a water warmed along
the clock from 10 to 90 C, exactly; none without the electron; a column of
Eh in `<DATA>`. The iron map over pH and Eh at 25 C, and in the same water
at 60 C: every boundary on its line, a point's pe its Eh over the volts of
a pe there, to 4.9e-11, the points where three meet to 3.6e-15, the iron
couple's boundary at 13.02 pe, 0.7702 and 0.8606 V; an Eh beside a pe, or
of a model without the electron, refused.
Activity ratios and the most stable phase per mole of an element (since
2026-11-10): K-feldspar, kaolinite, gibbsite and K-mica of `<PHASES>`
(phreeqc.dat's log Ks at 25 C) over log a(H4SiO4) and log a(K+)/a(H+), each
phase's saturation index over its aluminium, without activity coefficients:
every boundary on the line the log Ks give, to 4.6e-11; gibbsite, kaolinite
and K-mica meeting at (-4.3925, 1.5505) to 6.4e-15; K-feldspar beside K-mica;
no field of none; the same map with a thousand times less aluminium
dissolved; quartz's saturation along -3.98 to 4.4e-16. Each phase's makeup
from what it dissolves into (K-feldspar K, Al and 3 Si), a mineral's from
its relation. Under Davies activities the ratio, the other axis' activity
and the pH the water's, held at each point to 1e-11, where the activity
coefficients stop moving; a ratio of an anion, of a species the model has
not, and a phase weighed by nothing, refused.
Sensitivity indices (since 2026-11-10, `resources/js/rtm-gsa/indices.js`)
through the Uncertainty tab's path, on Kompartment's fixtures: EASI's
corrected first-order index GlobalSensitivity.jl's (4.4e-16); Borgonovo's
delta reduced for its bias GlobalSensitivity.jl's with its bootstrap
replayed (8.4e-15), and its interval SALib's, root B times as wide as
GlobalSensitivity.jl's (9.6e-15); PAWN's median over ten slices SALib's
exactly. On the Ishigami function, 2048 runs and a fourth input it never
reads: each first-order index inside its 95 % interval of the exact one
(0.3139 for 0.3139, 0.4282 for 0.4424, 0 and 0); delta largest for x2, then
x1, then x3 -- which matters only through x1, its first-order index
nothing -- clear of the unused input's; delta off the value's normal
scores, as the page reads it, within 0.015 of delta off the value; the same
seed the same intervals. A value 182 of 400 runs share exactly (x1 cut off
at 0.4): off the value itself delta is 1.5e13, its kernel densities
spikes; off the normal scores x1's 0.59, the unused input's 0.04, what
chance gives 400 runs; x1's first-order index 0.995. (On the sorbing front's
runs, 57 of 100 within 1e-4 of the plateau, delta off the value was 42.)
Principal components (since 2026-11-09, `RtmModel.pca`, Jacobi's rotations
on the correlation matrix): two variables correlated by r give 1 + r and
1 - r and components (1, 1) and (1, -1) over root 2, to 1e-15; six waters of
four variables of the test's own give numpy.linalg.eigh's eigenvalues (2.5.4,
on the same standardised table) to 1e-13 of the largest, each component an
eigenvector of the correlation matrix to 1e-14 and orthonormal, the
eigenvalues summing to four, the scores giving the standardised table back,
and a water put on the components where its own scores are; eleven waters
mixing two end members are one component, and a fifth variable the same in
all of them is left out; two waters, or one variable that varies, refused.

**Ion exchange** (`exchanger`, `exchange`). A binary Na/Ca exchange from an
exchanger all Na, against its closed solution (7e-14), the sites and the totals
kept to 1e-12; the same exchange written between the species on the exchanger,
CaX2 then taking 2 sites from the relations; a capacity loaded from a water
that stays as it is, Gaines–Thomas to 1e-12, with none of an ion the water lacks;
Gapon's Ca0_5X; an exchange species' coefficient its ion's, WATEQ with its own
a and b, Davies where both are 0, none without them, and out of I and the
water; `{NaX}` in a rate law the fraction, times its ion's coefficient under
`ACTIVITY`; a kinetic exchange with a `kf` relaxing to the same answer; and a
column of CaCl2 into an exchanger all Na. There the sites and the relation hold
in every cell to rounding, the Ca front sits at v t/R with R = 1 + CEC/(2 Ca)
and the chloride at v t, each within two cells, and the Jacobian holds, the
exchanger in the relations and out of the totals. Eleven texts are refused,
each with its reason.

**Surface complexation** (`surface`, `sites=`). Sites loaded from a water that
stays as it is, each fraction the closed form's (2e-15), the species out of I
and the water with n/sites for their coefficient; a one-site isotherm at a
fixed pH, the zinc and the sites given, against its closed solution (4e-15); a
bidentate species taking two sites, its fraction 2C/sites, the relation held in
fractions (1e-10); strong and weak sites, each kind its own total; `{Hfo_wOZn+}`
in a rate law the fraction; a sorption with a `kf` relaxing to the same
isotherm; under `ACTIVITY` the ions' coefficients and the surface's fractions in
one relation; and a column of zinc into bare sites with a Langmuir isotherm,
where the sites and the relation hold in every cell to rounding, the front sits
at v t/R with R = 1 + q(C)/C within two cells, and the Jacobian holds. Eleven
texts are refused, each with its reason, and a column whose surface is put on
its relations at the start only is warned of.

**The diffuse double layer** (`potential`, `area=`, `grams=`). A surface whose
one charged species takes protons at a fixed pH, against the same two
equations -- the relation with K exp(-F psi/RT), and Gouy and Chapman's --
solved by bisection: the potential to 1e-10 (60.92 mV, 15.4 % of the sites
charged where without the layer it would be 66 %), as amounts speciated and as
sites loaded from a water that stays. The potential is in the relation by the
charge it puts on the surface and in no total. A column of acid into a surface
that charges: the relation and Gouy and Chapman held in every cell to 1e-14,
and the Jacobian of the projected form at the start and on the way. Twelve
texts are refused, each with its reason, and `TEMPERATURE` is not said to do
nothing without `ACTIVITY` where a potential reads it.

**SIT** (`ACTIVITY = sit`, `<SIT>`). The coefficients against SIT written out
apart from the page's code: the Debye-Hueckel term with A at the water's own
a(H2O) (a fixed point, A taken at the a(H2O) it gives; the page gets there with one
Newton step on A's slope from the pure water's A, falling back to iterating where
the step crosses a corner of A's), the pairs counted both ways, a neutral species
paired with itself, eps1 I, and the water's activity from SIT's osmotic coefficient,
to rounding; their derivatives in I, in each partner, through A in the water's
activity (dGw, at every temperature under SIT: 1e-7 absolute at 25 C, which the
check missed until it was counted) and the water's in each species, against
differences (8e-7 with a step of 1e-4 of the value: at 1e-6 rounding dominates). The start, a run held throughout as salt raises I from
0.1 to 1.6 (every stored point on every relation in SIT's activities to 1e-12), a
fast pair, a rate law reading {X} and SR(phase), a column, and an exchanger whose
species take their ions' coefficients (NaX Na+'s, CaX2 Ca+2's): each with its
Jacobian. The electron under SIT, oxygen into a saline Fe and S water: every stored
point on every relation in SIT's activities to 5e-14, the pe from -2 to 11.5, and
the projected form's Jacobian at the start and the end, with an ion outside every
relation but paired and with an exchanger in a column of three cells; and the same
run at 150 C, on the vapour pressure, where A goes a part in 1e3 as far as ln
a(H2O): every relation to 4e-14 and the Jacobian at the start, the middle and the
end (this found the reduced speciation's later species missing A's ln a(H2O) term
in their gradients, 4e-4 off in the iron total's column; at 25 C it was too small to
see). Each cell is
speciated in its components and the sums of V, a set of species touching every pair
between two of the cell's unknowns; the derivatives run as dense gradients over the
unknowns and the outside species' concentrations. Six texts are refused, each with
its reason, and a and b under SIT are said not to be used. (A fixed species' own
column in the projected form misses its ln C in the relations, under Davies as under
SIT: harmless, as a fixed species never moves, and not checked.)

**A gas phase** (`gas`, `GAS_VOLUME`, `GAS_PRESSURE`, `Tc=`, `Pc=`, `omega=`,
`<GAS_PAIRS>`). A fixed volume: CO2 shared between the water and 0.5 L of gas as
the closed form shares it (bisection; the H+ excess the relations conserve, not a
charge balance, which the first version of the test assumed), Henry's law at every
stored point as CO2 comes in, the Jacobian. A bubble at 1 atm: it forms when the water
holds CO2 and N2 at 1 atm between them, at the time the closed form gives (1e-6), then
holds them in the closed form's shares (1e-9), every stored point on it; made and used
up, it forms and dissolves again, and the Jacobian with it there and gone. The electron
with a bubble: hydrogen from a rate law forms one, with no activity model and under
SIT, and in a column of three cells, each cell speciated in its components (the bubble
among the minerals' rows). Real gases in a fixed volume (25.5 atm) and in a bubble at
10 atm: each relation in fugacity, phi from the model's own Peng-Robinson at the run's
composition, and the Jacobian through every gas. Fifteen texts are refused, each with
its reason. (At the start of the redox column the Jacobian check differs in the column
of a total of 1.4e-9: the same with no gas at all, the difference step too large for
ln C there; with more H2 it checks.)

**The temperature** (`dH=`, `analytic=`, `TEMPERATURE`, `TK`, `TC`). log K at 50 C
against van 't Hoff's closed form and an analytic expression, which replaces logK and
dH; at 25 C logK or K as written. A batch heated from 10 to 80 C and back to 40 along a
table read at the clock: K at every stored point the one at its time (3e-16), the run
started again where the table turns. Each cell of a column held at 5, 25, 60 and 95 C
the one-cell model at its own temperature to the last bit, chemistry by chemistry: an
exchanger, a double layer, a gas in a fixed volume, a real one, a bubble of real gases,
the electron's held form, SIT, a mineral, and a mineral at 500 atm with molar volumes,
whose pressure term goes with the temperature; and heated along the table, every stored
state the start of a model at that time's temperature (4e-15). (An exchanger given a
capacity is loaded from the water at the start temperature, so its amounts are given
here.) One mineral over to another, P2 to P1 where their log K cross along the table,
at the closed form's time to 1e-8, and both given at the start, the other way.
Arrhenius on TK cell by cell, TC along the clock, a phase's saturation with its dH; a
fast pair's kb = kf/K at the cell's temperature without ACTIVITY (through AQ) and with
it, and one following the clock within 6e-7 of K (its kf = 1e6 lagging). Seven texts
refused. (The double layer's projected Jacobian differs in H+'s column, H+ held: the
same at a fixed 25 C, a known limit of the projected form with a fixed species.)

**Solid solutions** (`<SOLID_SOLUTIONS>`, `a0=`, `a1=`, `g0=`, `g1=`, `tc=`). MA and MB,
dissolving to A + X and B + X, the end members of MAB. At the start, ideal, binary and
binary with a gap, from five waters: each relation holds the water at the member's x
lambda, or inside the gap at the gap edge's activity (5e-14 in ln), the totals as given
(1e-15), two of the starts inside the gap; where there is none of it, no composition is
supersaturated (the largest sum x_q ln(IAP_q/(K_q a_q(x))) over x, a grid and then a
ternary search: the grid alone sits up to 1e-6 below the top). The gap for a0 = 3.43,
a1 = -1.82: the two compositions with the members' activities the same (2.9e-10;
PHREEQC's solve_misc stops at 1e-6), the spinodal between them where d2G/dx2 = 0, and
for a1 = 0 the regular solution's ln((1 - x)/x) = a0 (1 - 2x) (1e-8), none at a0 = 1.9
and one at 2.05 (PHREEQC's critical a0 is 2). Forming as X comes in, at the time the
closed form gives, ideal and with a0 = 1.5 (7e-11). Through the gap as B comes in: the
run stops where x_B comes to the gap's lower edge and where it leaves at the upper
(1e-8 at each), every relation held (2.2e-10). Dissolving away as X is taken out: both
members at none after it, no composition supersaturated. Under none, Davies and SIT,
with an electron and without (the projected form): the same run (5e-15), and the
Jacobian a difference's at the end of runs below, inside and above the gap. a0 and a1
at 50 C from 25 C, from `tc=50` and from `g0`/`g1` in kJ: the same start to the bit. A
regular solution (a0 = 2.2) heated along a table leaves its gap where the edge comes to
its composition (1e-15); where the temperature goes with time the gap is taken on to
round-off (the regular solution's to 2e-15), as PHREEQC's stopping point moves in jumps
of 2e-6 within a millikelvin and the run failed on one at 33.6 C. Twelve texts refused,
each with its reason. (Run a second time, the heated model started on the side of the
gap the temperature at the end of the first run gave, 75 C, where there is none, and
the start did not settle: a run's modes are set at t = 0's temperatures.)

**Pitzer** (`ACTIVITY = pitzer`, `<PITZER>`). NaCl alone is the single-salt form: ln
gamma+- and ln a(H2O) in closed form at 0.1 to 6 mol/kg (6e-15 and 3e-16), and without
K+ and Cl- the MacInnes scaling is off with PHREEQC's warning. J(x), which E-theta is
made of, from Harvie's Chebyshev series as PHREEQC takes it, against Pitzer's integral
by 20-point Gauss-Legendre quadrature at x = 0.001 to 100: within 6.6e-10, the series'
own accuracy; E-theta's first and second derivatives in I (the second for the Jacobian,
from the series' second derivative) against differences, 1e-9. Under the MacInnes scaling
ln gamma(Cl-) is KCl's ln gamma+- at the ionic strength, in closed form (1e-15), and a
water with no chloride is scaled by the Cl- it would have, as one with 1e-30 of it is (to
the bit). At 60 C a model is the same model at 25 C given each parameter's value at 60 C
(APHI given, the same at both; to the bit), and a parameter is its six terms as PHREEQC's
calc_pitz_param has them. The Jacobian of a water with every kind of parameter, held,
as fast pairs, in a column of three cells and with an exchanger, at three times each:
1432 entries, none off. At 150 C, on the vapour pressure times a(H2O): NaCl alone in
closed form with A_phi at the water's own a(H2O), the one the osmotic coefficient gives
with it, and F of a charge of 1 at that pressure (to the bit, and 1.4e-17 in ln a(H2O);
A_phi taken after one pass, at the a(H2O) the pure water's A_phi gives, as the page took
it until 2026-11-08, was 9.2e-10 off in ln gamma+- and 3.7e-11 in ln a(H2O)); the
derivatives the Jacobians read, in I, in each species and, through A_phi and the
pressure, in ln a(H2O), and ln a(H2O)'s own, against central differences at two steps
extrapolated (Richardson), on the vapour pressure and at 10 atm at 150 C, with APHI, and
at 250 C: within 5e-7, where without A_phi's and the pressure's part they are 1.3e-2,
5.5e-3, 6.8e-3 and 0.48 off; and the held water's Jacobian at 150 C on the vapour
pressure, with APHI and at 10 atm, 665 entries, none off (38 and 23 off before the part
was in it). Seventeen texts refused, each with its reason. (A held water with
an iron couple tied to the electron differs from the difference in two entries, Fe+3 and
e- in the column of a total, by 2 to 3 %: the same under Davies and SIT, to four digits,
so the projected form's and not Pitzer's.)

**LLNL** (`ACTIVITY = llnl`, `<LLNL>`). The coefficients against LLNL's forms written
out, with the tests' own tables: an ion's B-dot form with A, B and B-dot straight
between the tables' two temperatures on either side (a table temperature's own at
it), a neutral species given a= at 1, one given drummond Drummond's formula in
kelvin, one given neither 0.1 I, at 0 to 100 C on and between the tables' rows
(2.2e-16 in log gamma). A species on an exchanger takes its ion's B-dot form with its
own a, and its fraction (1.1e-16); the Jacobian of a held water with an exchanger and
Drummond's CO2 against differences at three times, 201 entries, none off. Eleven
texts refused, each with its reason.

**Molar volumes** (`<VOLUMES>`). PHREEQC's calc_rho_0, calc_dielectrics and calc_vm written out
in the test: each species' volume (-Vm's ten numbers in PHREEQC's units, with b and the
terms in I; millero's six), a mineral's and the water's, and each relation's ln K less
sum nu V (P - 1)/(R T), at 25 C and 500 atm, 80 C and 50 atm, and 150 C on the vapour
pressure times a(H2O) (to the bit: the same operations). Held while 1 mol/kgw of NaCl
goes in at 500 atm, and at 150 and 110 C on the vapour pressure, which then falls with
a(H2O) (4.54 to 4.38 atm): every stored point on its relations to 7e-15 in ln K, and
the Jacobian against differences at three times each, none of 162 entries off. That
needed A and B's derivative in a(H2O) where the water can be above 100 C -- on the
vapour pressure the dielectric constant follows the pressure, enough to see (33 entries
off at 150 C without it) -- and the volumes' own, through the density, the pressure and
f. A fast pair's backward constant kf/K at the pressure (1e-15); SI in a rate law of a
phase of <PHASES> with its own volume, and an exchanger's relations, ln K less the
ions' volumes alone (exact); their Jacobians. At 1 atm and 25 C the volumes change
nothing and a warning says so; eleven texts refused, each with its reason.

**The conductance, the density and the viscosity** (`<CONDUCTANCE>`, since 2026-11-09).
PHREEQC itself checks them in test-phreeqc.js; here, what needs no PHREEQC. Pure
water's viscosity (Huber et al. 2009) at three of IAPWS R12-08's check values to their
six decimals, and at 25 C and the water's density PHREEQC's 0.8900239182946 mPa s to
2e-14. At infinite dilution the older equation falls below Nernst and Einstein's
conductance as the square root of the salt (8.16e-5 and 8.14e-4 short at 1e-8 and 1e-6
mol/kgw, Kohlrausch), and Falkenhagen's by the Debye-Hueckel-Onsager limiting law, its
relaxation and electrophoretic terms worked out in the test from SI's constants and
PHREEQC's dielectric constant (78.384): the slope -88.954 for -88.956 S cm2/mol to a
square root of mol/kgw. The textbook's 0.2289 and 60.32 take eps 78.54 and are 0.4 %
off it. The ionic strength is floored at 1e-10, so the slope is taken from 2e-10. The SAR
of the dissolved Na, Ca and Mg by hand (11/sqrt(3.5)); none without Ca and Mg; no SC
without `<CONDUCTANCE>`; an `<OUTPUT>` named SC keeping the name; twelve texts refused,
each with its reason.

**Sites that go with a mineral** (`sites= per=`). Made-up constants: calcium taken out of a
water over a mineral, which dissolves, its surface's sites 0.05 to each mole of it. At
every stored point the sites are 0.05 times the mineral (9e-16), the relations hold with
each species' fraction of them (1e-14), the zinc on them comes off into the water and the
total stays; the Jacobian against differences at three times, none of 203 entries off.
With a double layer whose area goes with the mineral too, 500 m2 to each mole: Gouy and
Chapman hold at every stored point at the area the mineral has there, the charge's balance
worked out apart, and the Jacobian against differences has the area's derivative in the
mineral's column. Amounts given with the sites start where loading puts them. Eight texts refused, each
with its reason, and a run that uses the mineral up stops and says why: the event fires
at 1e-4 of what the cell started with, as the species on the sites, held as ln C, cannot
follow them to none (without that the solver stalled at the crossing, 4000 steps in
1e-4 s). Since 2026-11-08 the mineral may have no relation and be made and used at a
rate, PHREEQC's kinetic_reactant: each reaction that changes it takes its sites with it,
0.05 of the bare site to each mole (compile adds them to its stoichiometry), so the sites
stay 0.05 times it (6e-15) as it dissolves to an eighth, the relations hold (1e-14), the
zinc comes off and the total stays; the Jacobian none of three times' entries off; a
reaction that writes the surface's species as well is refused; and one that uses the
mineral up stops the run (an event on its amount, as for the held one: without it the
solver failed at the crossing). The old refusal of a mineral with no relation became one
of a mineral in two relations, which an earlier rule (one saturation) refuses first.

**An exchanger's sites that go with a mineral** (`sites= per=` on a species on it, since
2026-11-08). Made-up constants: calcium taken out of a sodium chloride water over anhydrite
held at saturation, the exchanger's sites 0.1 to each mole of it in the form of CaX2 (0.05
of it a mole, PHREEQC's `CaX2 Anhydrite equilibrium_phase 0.05`). At every stored point what
is on the exchanger is 0.1 times the mineral (1e-15), and the relations hold with each
species' activity its fraction of what is on it now, n C over the sum of n C (2e-15) -- the
coefficient beyond its ion's ln(n/sum) exactly -- as calcium's share falls from 0.78 to 0.69;
the sodium and the sulphate stay; the Jacobian against differences at three times, none
off, without activity coefficients, under Davies and under SIT (each species on it its
ion's coefficient). The derivatives are the new part: a species' fraction reads everything
on its exchanger, d ln(gamma)/dC_j = -n_j/sum, carried through sitPartners into the
speciation, the held rows (actCols) and a rate law's activities. Then the mineral made and
used at a rate (each reaction changing it carries 0.05 CaX2 a mole), a column of 8 cells
with salt coming in, and the electron's projected form: the same to 1e-15 and the
Jacobians exact. Amounts given with the sites start where loading puts them; eleven texts
refused (sites= without per=, two species the form, EQUILIBRATE not always, a kf on it, a
capacity on the exchanger's line, amounts not making the sites, and the surface's rules),
and a run that uses the mineral up, held or at a rate, stops and says so. Before, an
exchanger's capacity was a fixed number of each cell, and the hand-off held one that goes
with a phase at its start: on the kinetic host in test-phreeqc.js that left CaX2 and NaX 7
times PHREEQC's by the end.

**A mineral's bounds, and one held at another phase's saturation** (`dissolve_only`,
`precipitate_only`, `force_equality`, `SI(phase) = target`, since 2026-11-09). Made-up
constants: calcium taken out of a water over anhydrite for 1e4 s, then put back. Under
`dissolve_only` the anhydrite is never above the 0.05 it starts with: the water supersaturated
(SI 0.96) while it is there, the anhydrite dissolving once the water is not (to 0.0386) and back
at 0.05 on the way up, two events ("Anh dissolves", "Anh is back at what it started with, and
precipitates no more (dissolve_only)"), the water supersaturated again after. Under
`precipitate_only` what it starts with is set aside: what precipitates beside it comes and
goes (0.0634 down to 0.0567) at saturation throughout, and in a water undersaturated in it
none of the 0.05 dissolves; with calcium taken out until what precipitated beside it has
dissolved again (17817 s), the 0.05 is left and the event says so, "Anh is back at what it
started with, and dissolves no more (precipitate_only)" -- a first version said it had
dissolved away. Under `force_equality`, from none: held at saturation below none
(-1.6e-4 to -1.1e-3). A pH-stat, NaOH dissolving as much as holds `SI(Fix_H+) = -8` while
acid comes in: the pH 8 exactly, the NaOH used 2.000000e-3 for 2e-3 of acid (2.0014e-3 under
Davies, the carbonate taking a little more as the ionic strength rises), the sodium kept to
4.4e-16. The Jacobians against differences at three times each, 214 entries and 225, none
off. Nine texts refused, each with its reason (a bound on what is no mineral, both bounds,
no relation, the relations not held all through, precipitate_only with force_equality, a rate
law reading a mineral set aside in part, and SI() with no mineral, no such phase or a log K of
its own). The first version held precipitate_only as a lower bound on the whole amount:
the water's part was then the difference of two large numbers, and the run stalled; what it
starts with is now an offset the state does not carry (`model.inert`), added back where the
amount is shown and taken off where a shown amount comes in. Measured once, not in the
checks: a `dissolve_only` mineral at its cap over 14 runs of 401 stored points (seven rates,
with and without Davies) is never shown above it, every point below it is at saturation to
8.9e-16, and none at it undersaturated -- the state at the cap is the cap to the last bit,
which the reading of a stored point's mode (amount at or above the cap) relies on. Rates that
take the last chloride or calcium out with a sink of fixed rate fail there with a plain
mineral as well.

**CD-MUSIC** (`-cd_music`). Made-up constants: a surface of two kinds of site with
protons on plane 0, sodium on plane 1 (and on plane 2 for the second kind), a chloride
pair across planes 0 and 1 and zinc split 0.6 and 1.4, in a water with a charge of its
own, acid going in. Against PHREEQC's equations written out in the test: at every stored
point each relation holds with each plane's potential to the charge it puts there
(7.5e-15), and sigma0 = c0 (psi0 - psi1), sigma0 + sigma1 = c1 (psi1 - psi2) and
sigma0 + sigma1 + sigma2 + sigmad = 0 with the diffuse layer's charge from every ion and
a fictitious one (9.5e-15 of the charges); the Jacobian against differences at three
times, 423 entries, none off. Nine texts refused, each with its reason.

**Redox** (`electron`, `pe=`). One couple at a given pe shares its element as
K/a(e-) has it, from none of one state (1e-12); given no pe, the valence
states set it (1e-12). Two couples tied to the electron are the reaction
between them written without it, as written and from none of the products
(1e-9). A held run with an oxidant consumed at k[Ox] against its closed
solution: the electrons it moves shared by the two couples by their K
(3e-10); fixed, the electron holds the pe and the couple with it. Oxygen past
the last Fe(2), with methane tied to the same pe: the pe jumps by nine and
the run goes through in 27 steps, none failed, at rtol 1e-8. A redox front:
Fe(3) water into a column of immobile reductant, the relations held in every
cell to 5e-15 and the front at v t/R with R = 1 + Y/Fe3_in, within two cells;
the Jacobian of the projected form (each cell's species the speciation of its
totals) against a central difference on a buffered column with ACTIVITY, at
the start and on the way (a cell the front has passed holds Fe(2) at 1e-12,
where no central difference can follow ln Fe(2)). The electron's activity
coefficient is 1, out of I and the water; a rate law reads it as [e-]. Ten
texts are refused, each with its reason. A reaction that takes electrons where
the relations are held (since 2026-11-08, for PHREEQC's kinetic reactants): X +
e- => Fe+2 is X => Fe+3, the couple and O2 sharing out the electrons, run for
run to the bit, and its Jacobian; without the relations held it is refused.

**Limited advection** (`ADVECTION_SCHEME = limited`). A front at a Peclet
number of 400 against van Genuchten and Alves's closed solution for the flux
inlet: the largest error 7.6e-2 on 40 cells and 7.2e-3 on 160, where upwinding
gives 1.9e-1 and 2.9e-2 (the checks: less than half and a third of upwinding's,
and a fall of more than six over four times the cells); nothing below zero; a
Jacobian that moves with the state and that a difference agrees with; and a
calcite column dissolved cell by cell with the relations held.

The slope is 2a²b²(a+b)/((a²+b²)² + E²), zero where the gradients differ in
sign. Van Albada's own, ab(a+b)/(a²+b²), was tried first: scale-free, its
derivatives are O(1) however small the gradients, so in a stretch flat to
rounding behind a front it took a slope of either sign from the rounding, and a
difference of the state could not follow it (55 entries off). This one starts
from zero with zero slope, and E keeps rounding flats smooth. verifyJacobian
also gained two things there: an entry under 1e-7 of its row's terms is set
apart, as one under rounding is, and a disagreement is taken again at half the
step and extrapolated before it is reported, which removes the h² of a central
difference across a slope that varies on not much more than the step. Entries
spoiled by 0.1 % are still caught. It no longer lets a held model's logarithms
set the step floor for its concentrations (ln C of 30 stepped Cl- at 1e-4 by
2 % of itself).

These checks, and the PHREEQC ones, found that the conserved totals were made
from the wrong species. The totals are the free species of the elimination,
and it took them in the order the text lists the species, so a PHREEQC water
(most abundant first) left its trace species free: the total made from Fe+3
was mostly Na+, Ca+2 and Cl-, in which the ferric species are a part in 1e10.
Arithmetic resolved them to a part in a million, the start was 1.6e-5 off
PHREEQC, and a held run stalled, Newton moving Fe+3 by 2e-6 against residuals
of 2e-14. The elimination now takes the least abundant species first, so each
element's most abundant species makes its total; the start lands on PHREEQC to
1e-9 and the runs go through.

**Activity** (`ACTIVITY`). The four forms of PHREEQC's rule worked out by
hand at I = 0.05 (Davies, WATEQ with a and b, b·I for a neutral species, 1 for
the water and for `z=0 b=0`), a(H2O) = 1 − 0.017 ΣC without the water itself,
the derivatives in I against differences, and A and B at 15 and 25 °C against
PHREEQC 3.8.6's DH_A and DH_B (to 1e-9; the formulas agree with PHREEQC to
3e-9 from 0 to 200 °C). `H2O` in a relation changes nothing without
`ACTIVITY`. With it, every relation holds in activities, worked out apart from
the page's code: at the start (9e-16 in log K); held throughout while salt
takes I from 0.1 to 0.5 (4e-15 at every point, carbon to 6e-16, the end a
fresh speciation of its totals, the Jacobian exact); and as a fast pair,
whose backward constant follows I (4e-11 at the end, the Jacobian exact). A
column with every relation held checks the Jacobian across cells. Wrong
words, temperatures and charges are refused, and settings that do nothing
say so. A and B are at the water's activity, as PHREEQC has them (the
density of water at the vapour pressure times a(H2O)): the closed forms
above take them so, and a 3 to 4 mol/kgw brine at 90 C, held throughout, is
the same run speciated in its components (an iron couple tied to the
electron) as whole (the couple untied), 4e-15, which needs the water's ln a
an unknown of the components' speciation wherever A and B read it; its A is
2.3e-6 off pure water's, and ln gamma(Na+) the closed form at its own
a(H2O) to 3e-17.

**Equilibria held throughout the run** (`EQUILIBRATE = always`). Held exactly,
the relations are linear in ln C and the totals are integrated, so the checks
are exact ones. Acid into a carbonate water: every stored point on all three
relations (5e-15 in log K); carbon, the chloride the source put in and the
charge to 1e-12 (about 1e-15 measured); and the state at the end equal to a
speciation, worked out apart, of the totals the end has. Then the Jacobian with
ln C and the totals in it, a state knocked off its relations put back, a method
without a mass matrix refused, `R = 2.5` weighing the carbon inventory, `H+`
fixed, a `kf` pair beside two held relations, and a closed ten-cell column with
five diffusion coefficients, carbon and protons conserved over it to 1e-10
(5e-12 after 800 steps). These checks found two faults, both fixed. The
speciation's convergence test was absolute in mol/L, so a held run started
6.6e-12 off its totals; it is relative now, and takes one Newton step more. And
the NDF weighed ln C against |ln C|, which let the Newton leave a part in 1e9 on
the totals and held a species at 1e-9 mol/L twenty times more loosely than
`rtol` says; ln C is weighed as it stands now, and a point is shown as the exact
speciation of its totals.

**The model text.** Nine things that must be refused with a message that says
what is wrong, and chemical names (`e-`, `H+`, `C2O4-2`, `UO2+2`) surviving the
parser, since those are what a chemist writes.

**Kompartment's solvers.** The derivative works out only the rates and the
Jacobian only their gradients, so the Jacobian is checked against differences
of the derivative once more. Which models say their Jacobian never moves (a
tracer column and the decay chain do, Robertson and the built-in model do not),
and that Rosenbrock 2-3 then forms it once; Rosenbrock 2-3, Dormand-Prince and
Auto against the NDF on the tracer column, Auto handing that to the NDF and
leaving A → B → C explicit; the other new ports on A → B → C against its
closed solution; and the first step and norm control reaching the NDF.

## A limitation the browser test found

The first version of the speciation put every species into the Newton
iteration, including ones no equilibrium mentions. That is fine until such a
species starts at zero — `ln 0` — and the matrix comes out singular. The model
tests all happened to speciate systems where everything took part; the browser
test, which put a product starting at zero next to a water equilibrium, did
not. Speciation is now restricted to the species the equilibria touch, and
`test-model.js` checks that a bystander at zero is left at zero.

## Two mistakes this file made, kept as comments

Both were the test being wrong about a correct answer, which is the failure
mode worth remembering:

* it read `y[1]` as B in a model whose species are declared `W, A, B`, and got
  A — which was exactly `exp(-5.5)`, the right answer to a question it was not
  asking;
* it expected the half-height of an advecting front at `v·t`. At this Péclet
  number the Ogata–Banks solution is 0.586 there, not 0.5. It now compares
  against the analytic half-height, which the model matches to a fiftieth of a
  cell.

## What test-hdf5.py checks

`resources/js/kvot-hdf5-write.js` writes HDF5 by hand rather than through a
library, so the question is whether libhdf5 agrees that the result is a file.
`write-h5.js` runs a model through the page's own worker handler and hands the
reply to `rtm-hdf5.js`, which is exactly what rtm.html sends the Data Browser;
`test-hdf5.py` opens the result with h5py.

Four models, for the shapes the tree can take: a batch, which is one
cell and so has `/Species` and no `/Cells`; a column, where every cell is a
group of series and `/Grid` says where each of them is; and a dual-porosity
column with more cells than one file should hold datasets for, which is the
case where the rock is deliberately left out and `matrix_written` says so (a
text of its own, forty layers behind a hundred cells: the examples no longer
have that many). The far-field example, read at its right-hand end, has
`/Ends` with both ends and every species, `/Species` holding the end the page
showed, a unit release in at the left and all of a tracer out at the right in
the end, and its cells past the release point in `/Cells` and `/Grid`, past
`LENGTH` and saying so.

The numbers are checked, not only the structure: A → B → C ends with the A
spent and nearly all of it in C, and the dose-profile column ends with more in
its first cell than in its last, which is what catches a cell group holding
some other cell's series.

Every series is one-dimensional on purpose. A field of one matrix per species
would be a tidier file and unreadable in the browser it is written for: a
2-D dataset there is a set of realisations, and one that is not probabilistic
is drawn against a clock as long as its first column alone.

## What test-ui.py checks

The wiring rather than the mathematics: that the text compiles through the
worker, that a transport run reaches both chart tabs, that ticking a species
draws it and the chip removes it again, that *Check Jacobian* answers and finds
nothing wrong, that switching to batch recompiles to one cell and the profile
tab says so, that the Example picker offers all 13 in their groups and loading one brings
its text, its description and a run; that a model in years labels its axis,
its panel and its boxes in years rather than seconds; that the Run button does
not move when the status line below it changes size, which it used to do by
127 px, under the pointer as it was clicked;
that a dual-porosity model compiles with the panel saying how deep and what
enters, that the layer picker appears and the time chart follows it, that the
profile can be drawn into the rock with the fracture at depth zero and falls
inward, and that the gradient draws a rock layer along the fracture —
that the far-field example's panel says its layers are matched, how thick the
first came out and why, how many cells stand past its right-hand end and the
travel time the flow makes, that it runs, that choosing *flux through the right
end* draws the release with a unit release of a tracer all coming out in the
end and no layer to pick, and that a cell again brings the layers back —
that the boundary aliases reach the panel as the names they mean and that a
third-type inlet leaves its first cell below the inlet concentration, that a
`robin` face with no flow into it and a `free` face with nothing to carry
anything out are both warned about rather than silently behaving as `neumann`,
that a model naming an undeclared species is refused by name,
that the *Gradient* tab draws a heatmap with a row per cell and time along x
with distance running down y, starting at the *from* time rather than the
solver's first femtosecond, that *log concentration* puts the logarithm into the
data and says so on the colour bar, that smoothing is off unless asked for, that
a batch says there is no distance to plot against —
that the profile's *Times* field draws the times it is given and no others —
with units, as bare seconds, back to the automatic spread when emptied, and
reporting a token it could not read or a time past the end of the run rather
than dropping it silently — that a model typed from scratch runs and puts the
right number on the chart, and
that the syntax colouring lays a second copy of the text exactly over the box
being typed in — the same characters, the same metrics, every one of the 13
examples through the tokeniser unchanged, since a span too many or an escape
too few puts the caret over the wrong letter — and that turning it off puts
the copy away and is remembered; that the page can build the HDF5 file it
offers and says what it wrote;
that a model file dropped on the page outlines the page while it is held
there, loads, switches to the Model tab, is described in the panel -- power-law
grid, table, held cells -- is coloured without a character changed, and runs,
and that skbrtm's files dropped together, a stray `.md` among them, open as one
model with what skbrtm reads differently written at the top;
that a model using a parameter, an `R=` and an equilibrium at once compiles with
all three reported in the panel, runs, verifies, starts its chart from the
speciated state rather than what was typed, and draws a profile whose mean is
`t/R` times the mean of `G·DOSE` — the parameter, the retardation and the two
closed boundaries all in one number.

What a run can be read as (since 2026-11-09): the list puts the species first and the quantities after them in groups, the log activities shut until their heading is clicked; ticking pH, SI(Halite) and an `<OUTPUT>` draws the first two on the right-hand axis and the third, in mol/kgw, on the left, with the pH `<DATA>` measured at 500 s as open circles in the pH line's colour; the pH at 500 s is -log a(H+) of the acid the reaction added, 3.31. CSV, Excel, SVG and PNG are each caught as the page hands them over: the CSV's header names the quantities, the workbook starts with a zip's PK, the figures are an SVG and a PNG. The gradient draws as contours with their values and as a surface, and a quantity on it -- the radiolysis model's pH in every cell, from the worker -- with the picker's groups. The block puts back the model and the picks it found, which the checks after it read; and a CSV leaves out a pick the model on show does not have, where it used to write it an empty column.

The Composition tab (since 2026-11-09), on a water whose major ions are round numbers (Ca 2.2, Mg 1, Na + K 2.1, Cl 2, SO4 1, HCO3 + CO3 3 meq/kgw, CaSO4 and CO3-2 counted) and a water measured at 50 s: where calcium is, in the whole cell -- the calcite, made of what its reaction says, Ca+2 and CaSO4, stacked to 100 % at every point -- and in the water alone; the Piper diagram's three points where the shares put them, to 1e-9 against the geometry worked out in the test, the measured water in all three and the type, Ca–Na–HCO₃, in the note; the Schoeller diagram's lines in meq/kgw on a log axis, the measured one dotted; a Stiff diagram per water; the CSV's header and type; and along a three-cell column, a Piper point per cell coloured by distance. A share of exactly a half came out 0.49999999999999994 and missed the half-or-more rule of the type: the rule allows for the rounding.

A Durov diagram (since 2026-11-10), on the same water: the water in the cations' triangle, the anions' and the square where the two meet, HCO3 + SO4/2 across and Ca + Mg/2 up, to 1e-9; its total dissolved solids, every species dissolved by its formula and IUPAC's atomic weights, 405.00 mg/kgw by hand, on the panel at the right; no pH panel, the model having no H+, and the note saying so; the measured water in both triangles and the square. With a run kept beside the salinisation example's, the kept run's path dashed through all five panels, as the run's own.

The examples of fitting, uncertainty, the irrigation classes and principal components (since 2026-11-09) each open, once run, on their view: the sodic water on a Wilcox diagram, excellent to good at the start and doubtful to unsuitable at 1.39 d; the salinity example as principal components, the first between 80 and 95 % of the variance; the calcite example on the Fit tab, kc and its CO2 at the start fitted from 1e-4 and 5e-4 to within 2 % of 5.1e-4 and 1.01e-3; the sorbing front on the Uncertainty tab, a hundred runs drawn as bands with their median and the model as written, on a linear axis.

The Wilcox diagram (since 2026-11-09), on the composition water: the cations' total by hand, Ca 1.1 mmol with its CaSO4, Mg 0.5, Na 2 and K 0.1 being 5.3 meq/kgw, and the percent sodium 2/5.3, to 1e-9; the measured water's, 6.1 and 3/6.1; the conductance along the top a hundred times the e.p.m., as Wilcox took it; excellent to good in the note. Fifteen measured waters across every class: Wilcox's own example, the Colorado River at Yuma (12.06 e.p.m., 39 %), good to permissible as the bulletin has it, and a water 0.25 % either side of each traced curve where it is checked (56.25 % at 12.06, 85.73 at 10, 93.63 at 25, 71.05 at 5), each in the class the side it is on puts it. The curves are traced from the bulletin's scan (USDA Technical Bulletin 962, 1948, figure 1; the scan and the tracing scripts are not in the repository): each circle centred on its white hole, x set by the frame, the class lines falling at 7.52, 19.95 and 30.00 e.p.m., y by the ticks to 0.14 %; the monotone cubic through the circles lies on the drawn lines' ink to 3 pixels for 95 % of it (0.37 %), 5.3 at worst (0.64 %); the Yuma dot sits on the scan at 11.95 e.p.m. and 38.92 % for the 12.06 and 39 the bulletin gives it. Without an ACTIVITY the diagram is refused: the classes need milliequivalents.

Principal components on the Composition tab (since 2026-11-09), on a column whose four ions only mix (one D, no reactions, another water flowing in), at its last cell: by default each element dissolved, here its one species each; taken as they are, the first component carries 100.0 % of the variance, every water's second score within 1e-9 of the scores' reach, a water `<DATA>` measured half and half put on the same line, an arrow for each ion; as logs, which mixing does not keep on a line, the first carries between 90 and 100 %; a variable the model lacks is said; along the column at the start every cell is one water and nothing varies, which is said; the Excel workbook has the sheets run, loadings, variance and model.

The USSL diagram (since 2026-11-09), on the same water: without `<CONDUCTANCE>` it says the conductance is needed and where it comes from; with it (the solutes' gfw and dw, the tests' own) and an SC of 450 measured, the model's point at its SC, between 250 and 750 uS/cm, and its SAR, 2/sqrt(1.6) by hand from the dissolved Na, Ca and Mg, to 1e-9; the measured water's at 450 and 3/sqrt(1.5) from its Na, Ca and Mg; a log axis with the classes split at 250, 750 and 2,250; and C2-S1 in the note.

The Diagrams tab (since 2026-11-09), on a carbonate water without activities: with one thing varied the second axis's range is hidden; pH from 2 to 12 draws the carbon's shares as Bjerrum's fractions, to 1e-9; pH against log total carbon draws the species that holds most of the carbon, CO2 at pH 6, HCO3- at 7 and CO3-2 at 11, and as contours the total worked out at each point is the one it was held at; the CSV has a row per total. The map's boundaries come once it is drawn: the fields as the shapes they bound, the boundaries at pH 6.352 and 10.329 where the log Ks put them, to 1e-9, the note saying they were found; the Excel workbook has the sheets run, boundaries and model. A saturation index held at zero by a mineral present is zero to the rounding either side: the phase map counts it at saturation and the contours round it, where they drew it speckled and as a maze.

The redox couples as lines (since 2026-11-10), on a water with two couples and no complexes or activities, over pH 2 to 8 and pe -4 to 14: iron(3) over iron(2) flat at pe 13.02, the relation's log K, and sulfate over sulfide along pe = (33.65 - 9 pH)/8, each to 1e-9, from the map's left edge; the note saying two turn over. The couples example opens on its pe-pH diagram over pH 4 to 10: the six couples as lines, nitrate to nitrite falling a pe for each pH to 1e-5 and on its log K's (28.57 - 2 pH)/2 to 1e-4, its two species of one charge and the water's activity in its relation between (9e-7 and 3.2e-5), and ferric to ferrous through the ladder's 4.468 at pH 7; the water's limits dashed, the water itself marked.

The redox zones example (since 2026-11-10) opens on the time chart: oxygen, nitrate, manganese(2), iron(2), sulfate, sulfide and methane, a day at most between points (`MAX_STEP = 1`); each oxidant gone when its electrons are, at a hundredth of a millimole of carbon a day -- the oxygen at day 25, the nitrate at 43.75, the pyrolusite's manganese all dissolved at 48.75, the ferrihydrite's iron at 53.75, each to the day -- and methane half the carbon left after the sulfate's 60 days, to 1 %. The ticks are cleared after it.

The redox zones along a plume example (since 2026-11-10), 30 cells over 40 days, run in the page in about ten seconds: it opens on Gradient, the pe as contours over the 40 days, time not on a log axis, the 30 cells up; at the end, from the inlet by the pe, methane, iron, manganese, nitrate and the oxygen ahead of them. Against distance, Show at its first choice, what is ticked against time together at one time: the nine ticked, at the end of the run, on a log axis from 1e-10, the pe on its own axis on the right; methane and siderite from the inlet, ferrihydrite none there and part gone in the iron zone, manganese(2) beyond it, the oxygen at the far end; its legend under the axis' title, though the chart was drawn while its tab was hidden. With Times `20, 30` the first alone, day 20, the note saying so: methane at the inlet, the iron zone still at 5.5 m. Saved as CSV, `rtm_profile_ticked.csv`: the distance and a column for each of the nine, a row for each cell, with what the log axis cannot show -- the oxygen at the inlet under 1e-60, below the floor, and the ferrihydrite there at 0.

Where a log concentration axis starts (since 2026-11-10), on the same run: Against distance from the example's 1e-10, the axis' lower end at -10 and the note saying so. Against time from 1e-10 as well; from 1e-3 the note names the five curves wholly below it (oxygen, nitrate, manganese(2), sulfate, methane at the inlet); `abc` is not read and the note says so, the axis then reaching the least drawn, the oxygen at the inlet at 1e-73, as it does when the field is empty; the field waits, disabled, while the axis is linear. Gradient, methane by log concentration from 1e-10: as a map the colour scale from -10, what lies below in its colour; saved as CSV, every value, methane at 1e-144 where the water is oxic; as a surface the value axis from -10 too, below it out of the box. An example that gives no floor leaves none.

A redox ladder (since 2026-11-10), on a water with one couple, iron(3) over iron(2), no complexes and no activities: the second thing varied set to the pH held at, one box and no range, 7 to begin with; refused where the pH is what is varied; along pe from 10 to 16 at pH 3, the couple turning over at pe 13.02, the relation's log K, to 1e-9, the water's own pe, 12, dotted, the note saying so; the CSV a row per couple with its pe and its Eh; along Eh, the same couple at 13.02 times the volts of a pe at 25 C, to 1e-9. The redox ladder example opens on its ladder at pH 7: nitrate to nitrogen, to nitrite and to ammonium, ferric to ferrous, sulfate to sulfide and carbonate to methane, each within 0.005 of where test-phreeqc.js has phreeqc.dat's, O2 and H2 at 1 atm dashed at 13.78 and -7, the water itself dotted at pe 4.

The iron example (since 2026-11-10) opens, once run, on an Eh-pH Pourbaix diagram: Eh (V) up, the water's own limits at 1.229 - 0.0592 pH and -0.0592 pH volts across pH 2 to 12, to 1e-12, and Eh among the quantities to draw; worked out again over pe, the same range in pe, the same boundaries, each point's Eh its pe in volts, to 1e-9.

A chart saved as HTML (since 2026-11-10), the iron map: a page of its own with plotly.js 2.27.0 in it and nothing loaded from elsewhere; written to the disk and opened in a tab of its own with the network off, it draws the same traces, the same boundaries and the same axes, under the chart's note, the model text below. A model text whose first line is a comment that would close the script, add an image with an onerror and a script of its own comes through as text: nothing of it runs, no image, the page's own two scripts, the comment shown as written.

The silicate example (since 2026-11-10) opens on its stability diagram: K-feldspar, muscovite (K_mica), kaolinite and gibbsite per mole of aluminium over log a(H4SiO4) and log a(K+)/a(H+), the Show and element its own; gibbsite and kaolinite parted at -4.3925 to 1e-9; quartz and amorphous silica dotted where they come to saturation, at -3.9804 and -2.7118 to 1e-9, and the note saying so.

What matters, by sensitivity indices (since 2026-11-10), on the sorbing front's hundred runs: three kinds of bars, Rf, VELOCITY and the dummy drawn and never used; the retardation factor's first-order index (0.45) clear of the velocity's, its delta (0.51) and PAWN (0.57) above the velocity's intervals and its delta clear of the dummy's; the velocity's first-order index under 0.2; every delta between 0 and 1; the status saying from how many runs.

The examples of the sensitivity indices and the Durov diagram (since 2026-11-10) each open, once run, on their view: fresh water through a salty aquifer on a Durov diagram in linear time, the outlet's water from Na–Cl through Na–HCO₃, its pH highest there, between 8.7 and 9, and Mg–HCO₃ to Ca–HCO₃, its TDS from between 3600 and 3800 mg/kgw to between 450 and 550, the model in all five panels and the four measured waters one of each type; a decaying nuclide on its sensitivity indices from 300 runs, the retardation factor's and the velocity's first-order indices and deltas clear of the dummy's, the retardation factor's clear of the velocity's, the dispersivity's and the concentration flowing in's reaching the dummy's, and each first-order index's interval holding the exact one: the column is steady by the end, its outlet Wehner and Wilhelm's formula for a column with these boundaries (to 1.1e-4 at the corners of the draws), whose first-order indices are 0.709, 0.230, 0.0085 and 0.0040 by four million draws.

The same water as PHREEQC lists it (since 2026-11-10), the freshening example's outlet at the end of the run, on the Composition tab: its blocks in PHREEQC's order -- the solution's composition, its description, the distribution of species, the saturation indices, the minerals, the exchange composition -- H+ and OH- first, CaHCO3+ under C and under Ca, each element's total as its species make it, the calcite at saturation, the exchanger's equivalent fractions adding up to 1; Cell and At in the toolbar, Along and log time not, Text among the saves and the picture's not. At `1 d` its water at the stored point nearest; saved as Text, `rtm_freshening_water_cell19.txt`, in PHREEQC's blocks and columns, and as CSV the distribution of species.

Its calcium as a budget over the run (since 2026-11-10): in the water, on the exchanger and in the calcite, stacked, with what has gone out at the right-hand end on top, what was there at the start and came in at the left dashed along the top of the stack and what reactions made dotted; the note saying it closes, within 1e-5 of what was there and came in; saved as CSV, `rtm_freshening_budget_Ca.csv`, a row for each stored time.

The Composition tab one time at a time (since 2026-11-11), on the same run: along the run no slider; along the column one, at the end of the 514 stored points under At, back to At not to be pressed. At point 400 the column's waters on the Piper diagram the very ones At draws when given that point's time, typing At bringing At back. From point 100 to point 400 the waters move and the axes hold still on the Durov diagram (its pH and dissolved-solids panels, every annotation in place), the Schoeller diagram, where an element is (the same bands, picked by the whole run) and the principal components (the same loadings and variance, the whole run's waters'), the note saying the axes are the whole run's. Play, the run in 5 s, moves on from point 300, the button pause, and stops at the end of the run, 6.94 d; back to At draws At's time again.

The same run in mg/kgw (since 2026-11-10), as the freshening example gives it: the four Units selects at mg, the menu mol, mmol, µmol and nmol per kgw and mg and µg per kgw. Against time at the outlet the calcium, magnesium, sodium and chloride dissolved, the title concentration (mg/kgw), calcium's curve 40078 times its mol/kgw to 1e-12 and what was measured of it 40.078, 2.80546, 22.44368 and 92.1794 mg/kgw; mmol/kgw chosen on Against distance's bar sets all four, a thousand times the model's; in the model's own the title as it was. CaX2 ticked in mg: left off, the note naming it, no formula mass; the CSV `t (s)`, each in mg/kgw and CaX2 in mol/kgw. Kept and run again: beside it, dashed, the kept run in mg/kgw, the same to the last digit. Against distance CaX2 alone as the model has it, the note saying why, and Ca+2 in mg/kgw, every header of the CSV after the distance ending ` (mg/kgw)`; on Gradient Ca+2 (mg/kgw). The water's listing then has a column in mg/kgw after PHREEQC's own: in the Text, calcium's total its molality times 40078 to the four figures printed, and last in the CSV. A model without ACTIVITY with mg/kgw still chosen: drawn as its text has it, the note saying mg/kgw needs ACTIVITY; mg and µg on the menu, not to be chosen; times 10³ a thousand times, the title concentration × 10³.

The redox zones on Gradient (since 2026-11-10), on the plume example's run: first in Show where the model has the electron, and not offered for the freshening run, which has none. Each cell at each stored time by the couple holding its pe, the most poising capacity n Tox Tred/(Tox + Tred), the water's O2 at 2 Tox against the water itself. The zones in the order the couples turn over, O2/H2O, NO3-/N2, Pyrolusite/Mn+2, Fe+3/Fe+2, SO4-2/HS-, CO3-2/CH4, the nitrite never holding the pe; at the end of the run from the inlet sulfate, methane, iron, manganese, nitrate and the oxygen ahead; the note giving each zone's share of the waters; drawn as a map though the example's As is contours, log concentration and smooth not to be had. Cell 15 at each of its 3021 stored times, the couple holding the pe worked out by hand from every species' concentration there -- the time chart's CSV, nothing ticked -- with each couple's species written out in the test, is the zone the map's CSV gives by name: oxic, then nitrate, manganese and iron as the plume reaches it.

Against distance one time at a time (since 2026-11-10), on the same run, Ca+2 in mg/kgw: under the Times the slider at the end of its 514 stored points, the eight curves, Back to Times not to be pressed; moved to point 100, one curve at 1.31 h, the note saying it is the slider's and the axis the whole run's, and the axis the same at point 300; that curve the very one the Times draw when given point 300's stored time, which brings the Times back. Play, the run in 5 s, from point 300: the slider moving on, the button pause and the axis still; at the end of the run it stops at 6.94 d, the button play again; Back to Times the eight curves again. Those ticked against time on the slider: the four at 18.4 min and at 2.04 d, their axis the same.

Time in pore volumes, and several cells at once (since 2026-11-11), on the same run, Ca, Mg, Na and Cl ticked in mg/kgw: Time in at pore volumes on Against time, every stored time over 2e4 s to 1e-12, the "from" turned from 1e-6 s into 5e-11 PV, what was measured of chloride put at 0.5, 2.25, 5 and 20 PV by its own times, the three Time in selects as one, the note giving the pore volume, 5.56 h; the chloride at the outlet half-way from the brackish water's to the fresh one's between 0.9 and 1 pore volume (0.94; the cell's centre is 0.975 of the way along). Cells `4, 9, 14, end`: each species at each, named by its distance, `Cl- at 0.045 m` to `Cl- at 0.195 m`, sixteen curves, the cells in steps of contrast against the page, faintest at the inlet and every step 3:1 or more, cell 9's curve the very one Cell draws when it chooses cell 9, Cell set aside; the CSV `rtm_cell4_9_14_19.csv`, pore volumes first, then t (s), then each key at each cell with its distance, a row's pore volume its time over 2e4 s; `4, 40, x` drawing cell 4 and saying 40 and x are no cells of the 20. Gradient across pore volumes, its hover in them, its "from" 5e-11 PV, its x the time chart's, its CSV headed `distance (m) \ pore volumes: Ca+2 (mg/kgw)`. Against distance's Times `0.5, 1, 2 PV, 5` drawing 0.498, 0.999, 2.00 and 4.97 PV; back in seconds the Times turned into `10000, 20000, 2 PV, 100000`, each "from" into 1e-6, and the same curves drawn, named in hours and days. Then a tracer of the test's own through 0.5 m of a porosity of 0.4 with its dispersion a dispersivity (PECLET 50), kept, and run again at twice the speed for half as long, at cells 4, 12 and 24: in hours each front half-way at half the kept run's time, in pore volumes, each run counted in its own, at the same pore volume within 1e-5 and the curves within 1e-4 of each other (1.1e-5 measured: the NDF's starting step does not scale with the speed, so the two are not bit for bit), the note giving each run's pore volume, 2.08 d and 4.17 d. The Danckwerts example opens on Against time in pore volumes, X at cells 9, 19, 29 and 39, half-way up at 0.29, 0.53, 0.75 and 0.86 pore volumes.

Two runs side by side (since 2026-11-10), on the salinisation example at cell 19, Na+ and pH ticked: Keep this run keeps it, chosen to be drawn beside the next and named by the time it was kept and its example. Run again with the water twice as fast: against time each line ticked again for the kept run, dashed in its colour, its values the first run's to the last digit, pH on its own axis, this run's not; against distance each profile again for it, dashed; on Gradient its own map under this one, on one colour scale; on the Piper diagram its path through all three panels; beside it nothing, the run alone again. A decay run kept in seconds beside the same decay in minutes: its times drawn in minutes, 600 s at 10, the same end to 1e-3; both kept runs on the menu. The test then clears what it ticked.

The Sweeps tab (since 2026-11-09), on a first-order decay at a rate kk of `<PARAMETERS>`: the parameter is offered, and a new choice starts from half its value, the value and twice it (0.05, 0.1, 0.2); 0.1 to 0.4 in 4 makes four runs; against what was varied, A at the end of each is exp(-10 kk) to the solver's tolerance (1.1e-5 at rtol 1e-6); against time, a curve per run named for its value.

Each constant in turn (since 2026-11-11), on the same decay: first in Vary, "its one constant, 1 % either way (3 runs)", the values and the second choice hidden; three runs; A at the end, exp(-10 kk), moving -1 per cent for each per cent of kk, a bar to the left in orange, to 1e-4; the note giving A as written, 0.3679, and kk the one that moves it; the CSV `rtm_each_constant_A_end.csv` a row for kk. Each log K in turn: none offered for the decay, which has no relation; calcite into water with nothing but its ions, "its one log K, K 1 % either way (3 runs)", Ca+2 at the end moving half a per cent for each per cent of K, a bar to the right in blue, to 1e-6, the note giving Ca as written, 5.754e-5.

Breakthrough numbers (since 2026-11-11), under Against time, on a column of the test's own: a tracer X and Y held back with R = 4, 100 cells over 1 m, its dispersion a dispersivity (PECLET 100), for six pore volumes, at cells 24, 49, 74 and the last. Y's semi-discrete equations are X's with time over 4, so its half-way is at four times X's time at every cell, within 1e-3 (3e-6, 3e-6, 2.6e-5 and, at the outlet, where Y is still going at the end of the run and its half-way is of the 0.9987 it got to, 8.8e-4); X's retardation within 1 % of 1 (1.005 to 0.996); only the outlet's Y said to be at its farthest at the end of the run. Out of the column, from the budget: six pore volumes of a unit concentration came in, 0.04 m/d x 150 d = 6 to 1e-12; 5/6 of X gone out to 1e-6 and 1/3 of Y to 1e-3, what reactions made next to nothing. Kept, and run again with Y's R = 2: this run's Y half-way at twice X's time and the kept run's at four, each in rows of its own, and both runs' rows of what has come out.

The run against what was measured, one to one (since 2026-11-11), on the calcite example once it has fitted itself: fitted again from the text's own numbers (kc 5e-4, CO2 1e-3), so that the fit's first misfit is the run on show's, read exactly at the times measured; the run on show, read between its stored points, within 2e-3 of it (6.6e-4 measured), and the fitted run's sum of squares the fit's misfit to the last digit; the CSV `rtm_against_measured.csv` a row per value measured with each run's value and residual, the chart circles for this run and diamonds for the fitted one. Then the run's own values at four stored points written as its `<DATA>`, pH less 0.1 and Ca_mg twice and half by turns: each pH residual +0.1 and each Ca_mg one log10 2 either way to 1e-12, the table pH's bias +0.1 and spread 0.1, Ca_mg's bias a factor of 1 and spread a factor of 2, sums of squares 0.04 and 0.3625, all together 0.2243 and 0.4025; the fit, made against the old measurements, left out and the note saying so. Kept, and run again with kc doubled: the kept run's rows the first run's to the character, its points hollow, this run's sum of squares above the kept one's. A tracer's profile at a stored time, twice over at three cells and before and past the column, as a table in distance: each residual -log10 2, the ends read as the end cells; with a table in time, a value after the run's end and an amount of none, both said.

What each reaction does (since 2026-11-11). On the plume example, at cell 5, where the plume passes: the series list has a group for it after the saturation indices, the one line's rate and extent, `CH2O => CO3-2 + 6 H+ + 4 e-, rate` and `..., extent`. Ticked beside CH2O on a linear axis, the rate is on the right and is kdoc [CH2O], 0.05 of the CH2O drawn, at every stored point to the last digit; the extent is on the left, at each point the trapezoid of the rate's curve up to there, summed step by step as the worker sums it, to the last digit. On Diagrams, cell 5 as the run ends with its pH from 5 to 9: the rate is the same at each pH, the run's last to the last digit (CH2O is in no relation), drawn as `... rate (mol/kgw/d)`, and the extent is not offered. On Sweeps, kk varied in a decay: the rate offered, kk A at the end of each run within 5e-5, as `A => B, rate (/s)`; the extent not. On Uncertainty, the two lines' rates offered and not their extents.

The budget by each reaction (since 2026-11-11). On the built-in model, its H2O2 over the whole column: the radiolysis that makes it first, line 73, nine tenths of what is made; the two equilibria written as two lines each one reaction, `H+ + HO2- <=> H2O2 [135, 149]` and `HO2- + H2O <=> OH- + H2O2 [138, 150]`; the eight that move most named and the rest together, made above nought and taken below; every reaction's net and the summing's error together what the reactions made, to 1e-12, the error under 1e-6 of what they made and took, the model having no relations. At the fuel surface, cell 0, the radiolysis over 95 % of what is made, no leftover row, and the CSV `rtm_budget_H2O2_by_reaction_cell0.csv` each reaction's rates and sum at every stored point. On the plume: of CO3-2 the organic carbon's oxidation all that makes it and nothing taking it, and the relations, relation by relation, taking over nine tenths of it on, the most into siderite, the summing's error under 1e-6 of what was made; HCO3-, which no line makes, the chart saying so and the table its own relation all that made it, the summing's error nought; carbon, all of it, made by no line, the leftover the summing's; and of CH2O at cell 5, in the CSV, what the line took at every stored point the rate Against time draws there and its sum the extent, to the last digit.

Where the minerals' fronts are (since 2026-11-11), on the Composition tab, halite into fresh water in a column of the test's own: the length of column cleared of it, `Halite, cleared to`, moving at v S/(S + M), a fifth of the water's speed, to 2 %, 0.4 m from the inlet by the end to within a cell, and the halite gone at the inlet; with twice the halite, a ninth of the water's speed; the CSV a row per stored time, `t (s),"Halite, cleared to (m)"`.

The Fit tab (since 2026-11-09), on the calcite-at-a-rate example's text: the parameter kc offered from the value the text gives it and both `<DATA>` columns ticked, a relation's log K among what can be fitted; kc fitted, the table giving it and its error as a factor, the chart the run at it beside what was measured; and Put the fitted values in the model writing kc into its line. The check loads the example's text rather than the example, whose view would untick the time chart's log boxes for the checks after it. From the fit, on the Uncertainty tab, then gives kc as a lognormal about its fitted value, times or over its standard error, alone and so without the box of the fit's correlations.

The Uncertainty tab (since 2026-11-09), on a decay at a rate kk and a number zz nothing reads: a number drawn starts as a lognormal about the value the text gives it, times or over 2, and and another takes the next parameter rather than a setting; 101 runs by Latin hypercube from seed 1, kk lognormal times or over 1.5; the 101 values of kk the same as distributions.html's engine draws, imported in the page and run with the same seed and stream; the bands at the end -- 5 %, the median and 95 % of A -- exp(-10 kk) at kk's 95th, 51st and 6th of 101 to the solver's tolerance, as a falling function of kk has them with type-7 percentiles at whole order statistics (101 runs); and what matters, kk's rank correlation with A at the end -1 to 1e-12 and zz's near 0. A hover tooltip on the From the fit button and the rows' leave-it-out buttons broke the page's rule of none; the (i) says what they do.

The examples that show a way of reading results (since 2026-11-09) open on it once they have run: the carbonate example on Diagrams, the carbon against pH worked out; the exchange example on Sweeps, four capacities run and a curve each at the outlet against linear time, the menu naming the exchanger's capacity as the text gives it (0.002); the salinisation example on Composition, the outlet's path through a Piper diagram with the three measured waters there, from Ca–HCO₃ at the start to Na–Cl. The picker offers 35 examples in 12 groups.

That last check was first written expecting the profile to be the shape of the
source. It is not: √(D·t/R) is 2×10⁻⁴ m against a column of 10⁻⁴ m, so by 100 s
the species is very nearly mixed and only the mean is pinned down. Writing it
down wrong is how the check ended up testing something true.

**The (i) beside each setting.** The settings, the two section headings and
the five tab toolbars each have an (i) that opens a panel on the right
(`resources/js/kvot-info.js`, the topics in `rtm-ui.js`), in place of the hover
tooltips they had. The test asks `KvotInfo.audit()` for a slot without a topic
or a "Read more in Help" whose heading is missing, counts an (i) in every one
of the 27 slots, and checks that no `title` is left on the panel or a toolbar.
Then the behaviour: an (i) opens the panel under its own title, between the
header and the footer; the ×, the same (i) and an Escape key press each close
it, the last giving the focus back; the (i) on a section heading leaves the
section open; a topic with choices marks the chosen one and follows the
setting while it is open; its Help link lands on its heading; and the (i)s of
the panel line up at its right-hand edge. A section heading's (i) is in a slot
before its `<details>`, not in the summary, since Chrome reports any control
inside a `<summary>` (`An interactive element was found within a <summary>
element`): the test finds no slot (`audit().inSummary`) and no other control
inside one, and each heading's (i) centred on its line, at its end.

**The full window.** The button at the right end of the tab bar takes away the
site's header, menu and footer, as on smui.html and dose_coefficients.html. The
test presses it with the mouse, so a button covered by something else fails.
It checks that the page then fills the window, that the kvot mark at the left
of the bar leads home, and that the theme switch beside the button works as the
footer's does. The tabs work as before, with the two buttons outside the
tablist. An (i) panel runs from the top of the window to the bottom; before the
fix in `kvot-info.js` it took its height from the hidden header and footer and
had none. A reload is in the full window before `rtm-ui.js` runs. The test
records the page as the parser inserts that script's element: the scripts are
classic, so by readyState `interactive` it would already have run, and only the
page's head can have set the full window. At phone width the tabs scroll
between the mark and the buttons, in either mode, so the last of them can be
reached. The line under the tabs is the bar's background, not a border, because
the scrolling row would clip a tab reaching over a border. So the test also
checks that the open tab reaches the bar's foot in its pane's colour.

The choice is kept in the browser (`kvot.rtm.full`), and the test profile keeps
it from run to run. rtm.html's head reads it before anything else, so the test
clears it before the first load, from `rtm.css`, a file of the same origin that
runs no script. It clears it again after its checks, so an interrupted run
cannot leave the next one without the site's header.
