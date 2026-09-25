/* ==========================================================================
   SIMPLEFUNCTIONS.HTML: THE DATA

   The SR-Site thermodynamic dataset of the Simple Functions, and the
   reference groundwaters of TR-10-61.

   THE DATASET is the one the SR-Site calculations used: the reactions and
   equilibrium constants of the SR-Site data report (SKB TR-10-52, tables
   3-29 to 3-32), with the uncertainties ΔlogK that the calculations sample
   as N(logK, ΔlogK/2). The constants carry all the digits the workbooks
   have (HCO3- 10.329, CaCO3(aq) 3.224, CaHCO3+ 11.435, NaHCO3 10.079,
   FeSe2(s) 110.545, Np(CO3)4-4 36.684, PuSO4+ 3.912, Pu(SO4)2- 5.704). Two constants
   are derived in the workbooks and kept as they derive them:
   NpO2(OH)2- = −23.6 + 10.57 with ΔlogK = √(0.5² + 0.12²), and
   PuO2(OH)2·H2O(s) = 5.5 + 15.82 + 17.45 + 17.69 − 62.31 with ΔlogK =
   √(1² + 0.7² + 0.69² + 0.67²).

   Pu(CO3)3-3 has ΔlogK = 1.4. The first SR-Site workbooks (May 2010) had
   10.6 there, which put the upper tail of the plutonium solubility above
   1 mol/kg; the correction of February 2011 ("CSOL korr") is the one the
   PSAR data carry, and the one here.

   Each reaction is written out in full. The page derives the activity
   corrections and the ligand dependence from it (sf-model.js). Where the
   workbooks wrote a different term by hand, `qSRSite` (activity term) and
   `ligSRSite` (ligand exponent) hold the workbook's, so the SR-Site numbers
   come out; the option "every term from the reactions" drops them. They are:
     - NiCO3·5.5H2O(s): the workbook leaves out the 5.5 H2O (0, 0, −2)
       where the reaction gives (−5.5, 0, −2).
     - PaO2OH(aq): the workbook has +2 q0 where the reaction gives 0.
     - SmOHCO3(s): the workbook leaves out the H+ (−1, 0, −1, −1) where the
       reaction gives (−1, 1, −1, −1); at I = 0.1 that puts the SmOHCO3
       solubility 0.10 log units high.
     - (UO2)2CO3(OH)3-: the workbook's dimer term has [CO3-2]^3 for the one
       carbonate of the reaction (U!G32). Under the reducing conditions of
       Version B the dimer is negligible either way.
     - Fe(OH)4- (major ions): the workbook writes the reaction with 2.5 H2O,
       which does not balance; here it is written with 3.5 H2O and the
       workbook's term kept. Only Version A uses this species.

   Species marked `depth: 3` (Ra(OH)+) are sampled in the workbooks as
   RiskNormal(RiskNormal(RiskNormal(logK, σ), σ), σ), a normal with three
   times the variance; the option "sample Ra(OH)+ once" undoes it.

   THE WATERS are table A-1 of TR-10-61 (Grivé et al. 2010), from SKB
   TR-06-09, in mol/kg. Mg is kept apart; the page adds it to Ca, as the
   Simple Functions require. Silicon is not in the table: TR-10-61 asks for
   a very small concentration instead of zero where it is missing, and 1e-20
   is used here. Where the table gives two Eh values, the more reducing is
   used, as TR-10-61 does for its tables B-2 and B-3.
   ========================================================================== */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.SFData = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const SRSITE = {
    id: 'srsite',
    label: 'SR-Site (TR-10-52, as calculated in SKBdoc 1282962; Pu corrected 2011)',
    major: [
      { id: 'CaOH+', rx: 'Ca+2 + H2O = CaOH+ + H+', logK: -12.78, dlogK: 0.30 },
      { id: 'FeOH+', rx: 'Fe+2 + H2O = FeOH+ + H+', logK: -9.50, dlogK: 0.10 },
      { id: 'Fe(OH)3(aq)', rx: 'Fe+2 + 0.25 O2(g) + 2.5 H2O = Fe(OH)3(aq) + 2 H+', logK: -4.80, dlogK: 1.06 },
      { id: 'Fe(OH)4-', rx: 'Fe+2 + 0.25 O2(g) + 3.5 H2O = Fe(OH)4- + 3 H+', logK: -13.84, dlogK: 0.08, qSRSite: [2.75, -4, 1, 0, 0, 0, 0] },
      { id: 'Calcite', rx: 'Ca+2 + CO3-2 = CaCO3(s)', logK: 8.48, dlogK: 0.02 },
      { id: 'HCO3-', rx: 'H+ + CO3-2 = HCO3-', logK: 10.329, dlogK: 0.02 },
      { id: 'CaCO3(aq)', rx: 'Ca+2 + CO3-2 = CaCO3(aq)', logK: 3.224, dlogK: 0.14 },
      { id: 'CaHCO3+', rx: 'Ca+2 + CO3-2 + H+ = CaHCO3+', logK: 11.435, dlogK: 0.09 },
      { id: 'NaCO3-', rx: 'Na+ + CO3-2 = NaCO3-', logK: 1.27, dlogK: 0.30 },
      { id: 'NaHCO3(aq)', rx: 'Na+ + CO3-2 + H+ = NaHCO3(aq)', logK: 10.079, dlogK: 0.30 },
      { id: 'FeCO3(aq)', rx: 'Fe+2 + CO3-2 = FeCO3(aq)', logK: 4.38, dlogK: 1.31 },
      { id: 'FeHCO3+', rx: 'Fe+2 + CO3-2 + H+ = FeHCO3+', logK: 12.33, dlogK: 0.30 },
      { id: 'Magnetite', rx: '3 Fe+2 + 3 H2O + 0.5 O2(g) = Fe3O4(s) + 6 H+', logK: 5.49, dlogK: 0, fixed: true },
      { id: 'Goethite', rx: 'Fe+2 + 1.5 H2O + 0.25 O2(g) = FeOOH(s) + 2 H+', logK: 8.75, dlogK: 0, fixed: true },
      { id: 'HSO4-', rx: 'H+ + SO4-2 = HSO4-', logK: 1.98, dlogK: 0.25 },
      { id: 'CaSO4(aq)', rx: 'Ca+2 + SO4-2 = CaSO4(aq)', logK: 2.30, dlogK: 0.30 },
      { id: 'NaSO4-', rx: 'Na+ + SO4-2 = NaSO4-', logK: 0.70, dlogK: 0.30 },
      { id: 'FeHSO4+', rx: 'Fe+2 + SO4-2 + H+ = FeHSO4+', logK: 3.07, dlogK: 0.30 },
      { id: 'FeSO4(aq)', rx: 'Fe+2 + SO4-2 = FeSO4(aq)', logK: 2.25, dlogK: 0.05 },
      { id: 'FeCl+', rx: 'Fe+2 + Cl- = FeCl+', logK: 0.14, dlogK: 0.23 },
    ],
    elements: [
      {
        el: 'Sr', name: 'Strontium', master: 'Sr+2',
        species: [
          { id: 'SrOH+', rx: 'Sr+2 + H2O = SrOH+ + H+', logK: -13.29, dlogK: 0.30 },
          { id: 'SrCO3(aq)', rx: 'Sr+2 + CO3-2 = SrCO3(aq)', logK: 2.81, dlogK: 0.05 },
          { id: 'SrHCO3+', rx: 'Sr+2 + CO3-2 + H+ = SrHCO3+', logK: 11.51, dlogK: 0.05 },
          { id: 'SrSO4(aq)', rx: 'Sr+2 + SO4-2 = SrSO4(aq)', logK: 2.29, dlogK: 0.26 },
          { id: 'SrCl+', rx: 'Sr+2 + Cl- = SrCl+', logK: 0.32, dlogK: 0.12 },
        ],
        solids: [
          { id: 'Strontianite', rx: 'SrCO3(s) = Sr+2 + CO3-2', logK: -9.27, dlogK: 0.30 },
          { id: 'Celestite', rx: 'SrSO4(s) = Sr+2 + SO4-2', logK: -6.63, dlogK: 0.30 },
        ],
      },
      {
        el: 'Ra', name: 'Radium', master: 'Ra+2',
        species: [
          { id: 'RaOH+', rx: 'Ra+2 + H2O = RaOH+ + H+', logK: -13.50, dlogK: 0.25, depth: 3 },
          { id: 'RaCO3(aq)', rx: 'Ra+2 + CO3-2 = RaCO3(aq)', logK: 2.50, dlogK: 0.40 },
          { id: 'RaSO4(aq)', rx: 'Ra+2 + SO4-2 = RaSO4(aq)', logK: 2.75, dlogK: 0.10 },
          { id: 'RaCl+', rx: 'Ra+2 + Cl- = RaCl+', logK: -0.10, dlogK: 0.30 },
        ],
        solids: [
          { id: 'RaCO3(s)', rx: 'RaCO3(s) = Ra+2 + CO3-2', logK: -8.30, dlogK: 0.30 },
          { id: 'RaSO4(s)', rx: 'RaSO4(s) = Ra+2 + SO4-2', logK: -10.26, dlogK: 0.09 },
        ],
      },
      {
        el: 'Zr', name: 'Zirconium', master: 'Zr+4',
        species: [
          { id: 'Zr(OH)4(aq)', rx: 'Zr+4 + 4 H2O = Zr(OH)4(aq) + 4 H+', logK: -2.19, dlogK: 1.70 },
        ],
        solids: [
          // Computed in the workbooks but left out of the minimum: the aged
          // solid is the one that controls.
          { id: 'Zr(OH)4(am,fresh)', rx: 'Zr(OH)4(am,fresh) + 4 H+ = Zr+4 + 4 H2O', logK: -3.24, dlogK: 0.10, use: false },
          { id: 'Zr(OH)4(am,aged)', rx: 'Zr(OH)4(am,aged) + 4 H+ = Zr+4 + 4 H2O', logK: -5.55, dlogK: 0.20 },
        ],
      },
      {
        el: 'Nb', name: 'Niobium', master: 'NbO3-',
        species: [
          { id: 'Nb(OH)4+', rx: 'NbO3- + 2 H+ + H2O = Nb(OH)4+', logK: 6.90, dlogK: 0.02 },
          { id: 'Nb(OH)5(aq)', rx: 'NbO3- + H+ + 2 H2O = Nb(OH)5(aq)', logK: 7.34, dlogK: 0.02 },
        ],
        solids: [
          { id: 'Nb2O5(s)', rx: 'Nb2O5(s) + H2O = 2 NbO3- + 2 H+', logK: -24.34, dlogK: 0.04 },
        ],
      },
      {
        el: 'Tc', name: 'Technetium', master: 'TcO(OH)2',
        species: [
          { id: 'TcO+2', rx: 'TcO(OH)2 + 2 H+ = TcO+2 + 2 H2O', logK: 4.00, dlogK: 1.42 },
          { id: 'TcO4-', rx: 'TcO(OH)2 + 0.75 O2(g) = TcO4- + 0.5 H2O + H+', logK: 32.94, dlogK: 2.05 },
          { id: 'TcO(OH)+', rx: 'TcO(OH)2 + H+ = TcO(OH)+ + H2O', logK: 2.50, dlogK: 0.30 },
          { id: 'TcO(OH)3-', rx: 'TcO(OH)2 + H2O = TcO(OH)3- + H+', logK: -10.90, dlogK: 0.40 },
          { id: 'TcCO3(OH)2(aq)', rx: 'TcO(OH)2 + CO3-2 + 2 H+ = TcCO3(OH)2(aq) + H2O', logK: 19.30, dlogK: 0.30 },
          { id: 'TcCO3(OH)3-', rx: 'TcO(OH)2 + CO3-2 + H+ = TcCO3(OH)3-', logK: 11.00, dlogK: 0.60 },
        ],
        solids: [
          { id: 'TcO2·1.63H2O(s)', rx: 'TcO2·1.63H2O(s) = TcO(OH)2 + 0.63 H2O', logK: -8.40, dlogK: 0.50 },
        ],
      },
      {
        el: 'Ni', name: 'Nickel', master: 'Ni+2',
        species: [
          { id: 'NiOH+', rx: 'Ni+2 + H2O = NiOH+ + H+', logK: -9.54, dlogK: 0.14 },
          { id: 'Ni(OH)2(aq)', rx: 'Ni+2 + 2 H2O = Ni(OH)2(aq) + 2 H+', logK: -18.00, dlogK: 0.30 },
          { id: 'Ni(OH)3-', rx: 'Ni+2 + 3 H2O = Ni(OH)3- + 3 H+', logK: -29.20, dlogK: 1.70 },
          { id: 'NiCl+', rx: 'Ni+2 + Cl- = NiCl+', logK: 0.08, dlogK: 0.60 },
          { id: 'NiCO3(aq)', rx: 'Ni+2 + CO3-2 = NiCO3(aq)', logK: 4.20, dlogK: 0.40 },
        ],
        solids: [
          { id: 'Ni(OH)2(s)', rx: 'Ni(OH)2(s) + 2 H+ = Ni+2 + 2 H2O', logK: 11.03, dlogK: 0.28 },
          { id: 'NiCO3·5.5H2O(s)', rx: 'NiCO3·5.5H2O(s) = Ni+2 + CO3-2 + 5.5 H2O', logK: -7.52, dlogK: 0.24, qSRSite: [0, 0, -2, 0, 0, 0, 0] },
        ],
      },
      {
        el: 'Pd', name: 'Palladium', master: 'Pd+2',
        species: [
          { id: 'PdOH+', rx: 'Pd+2 + H2O = PdOH+ + H+', logK: -1.86, dlogK: 0.30 },
          { id: 'Pd(OH)2(aq)', rx: 'Pd+2 + 2 H2O = Pd(OH)2(aq) + 2 H+', logK: -3.79, dlogK: 0.30 },
          { id: 'Pd(OH)3-', rx: 'Pd+2 + 3 H2O = Pd(OH)3- + 3 H+', logK: -15.93, dlogK: 0.30 },
          { id: 'Pd(OH)4-2', rx: 'Pd+2 + 4 H2O = Pd(OH)4-2 + 4 H+', logK: -29.36, dlogK: 0.04 },
          { id: 'PdCl+', rx: 'Pd+2 + Cl- = PdCl+', logK: 5.10, dlogK: 0.01 },
          { id: 'PdCl2(aq)', rx: 'Pd+2 + 2 Cl- = PdCl2(aq)', logK: 8.30, dlogK: 0.04 },
          { id: 'PdCl3-', rx: 'Pd+2 + 3 Cl- = PdCl3-', logK: 10.90, dlogK: 0.07 },
          { id: 'PdCl4-2', rx: 'Pd+2 + 4 Cl- = PdCl4-2', logK: 11.70, dlogK: 0.09 },
        ],
        solids: [
          { id: 'Pd(OH)2(s)', rx: 'Pd(OH)2(s) + 2 H+ = Pd+2 + 2 H2O', logK: -1.61, dlogK: 1.16 },
        ],
      },
      {
        el: 'Ag', name: 'Silver', master: 'Ag+',
        species: [
          { id: 'AgCl(aq)', rx: 'Ag+ + Cl- = AgCl(aq)', logK: 3.27, dlogK: 0.17 },
          { id: 'AgCl2-', rx: 'Ag+ + 2 Cl- = AgCl2-', logK: 5.27, dlogK: 0.37 },
          { id: 'AgCl3-2', rx: 'Ag+ + 3 Cl- = AgCl3-2', logK: 5.29, dlogK: 0.39 },
          { id: 'AgCl4-3', rx: 'Ag+ + 4 Cl- = AgCl4-3', logK: 5.51, dlogK: 1.71 },
          { id: 'AgOH(aq)', rx: 'Ag+ + H2O = AgOH(aq) + H+', logK: -12.00, dlogK: 0.30 },
          { id: 'Ag(OH)2-', rx: 'Ag+ + 2 H2O = Ag(OH)2- + 2 H+', logK: -24.00, dlogK: 0.10 },
        ],
        solids: [
          { id: 'AgOH(s)', rx: 'AgOH(s) + H+ = Ag+ + H2O', logK: 6.30, dlogK: 0.05 },
          { id: 'AgCl(cr)', rx: 'AgCl(cr) = Ag+ + Cl-', logK: -9.75, dlogK: 0.04 },
        ],
      },
      {
        el: 'Sn', name: 'Tin', master: 'Sn+4',
        species: [
          { id: 'SnOH+', rx: 'Sn+4 + 2 H2O = SnOH+ + 0.5 O2(g) + 3 H+', logK: -40.28, dlogK: 0.39 },
          { id: 'Sn(OH)2(aq)', rx: 'Sn+4 + 3 H2O = Sn(OH)2(aq) + 0.5 O2(g) + 4 H+', logK: -44.28, dlogK: 0.39 },
          { id: 'Sn(OH)4(aq)', rx: 'Sn+4 + 4 H2O = Sn(OH)4(aq) + 4 H+', logK: -0.53, dlogK: 0.67 },
          { id: 'Sn(OH)5-', rx: 'Sn+4 + 5 H2O = Sn(OH)5- + 5 H+', logK: -8.53, dlogK: 0.73 },
          { id: 'Sn(OH)6-2', rx: 'Sn+4 + 6 H2O = Sn(OH)6-2 + 6 H+', logK: -18.93, dlogK: 1.00 },
        ],
        solids: [
          { id: 'SnO2(am)', rx: 'SnO2(am) + 4 H+ = Sn+4 + 2 H2O', logK: -6.77, dlogK: 0.73 },
          { id: 'CaSn(OH)6(s)', rx: 'CaSn(OH)6(s) + 6 H+ = Sn+4 + 6 H2O + Ca+2', logK: 8.54, dlogK: 0.74 },
        ],
      },
      {
        el: 'Se', name: 'Selenium', master: 'SeO4-2',
        species: [
          { id: 'HSe-', rx: 'SeO4-2 + H+ = HSe- + 2 O2(g)', logK: -84.61, dlogK: 0.44 },
          { id: 'SeO3-2', rx: 'SeO4-2 = SeO3-2 + 0.5 O2(g)', logK: -13.50, dlogK: 0.34 },
          { id: 'Se-2', rx: 'SeO4-2 = Se-2 + 2 O2(g)', logK: -99.52, dlogK: 0.77 },
          { id: 'H2Se(aq)', rx: 'SeO4-2 + 2 H+ = H2Se(aq) + 2 O2(g)', logK: -80.76, dlogK: 0.67 },
          { id: 'HSeO3-', rx: 'SeO4-2 + H+ = HSeO3- + 0.5 O2(g)', logK: -5.15, dlogK: 0.41 },
          { id: 'H2SeO3(aq)', rx: 'SeO4-2 + 2 H+ = H2SeO3(aq) + 0.5 O2(g)', logK: -2.51, dlogK: 0.43 },
          { id: 'HSeO4-', rx: 'SeO4-2 + H+ = HSeO4-', logK: 1.75, dlogK: 0.10 },
          { id: 'CaSeO4(aq)', rx: 'SeO4-2 + Ca+2 = CaSeO4(aq)', logK: 2.00, dlogK: 0.10 },
        ],
        solids: [
          { id: 'FeSe2(s)', rx: 'FeSe2(s) + 3.5 O2(g) + H2O = 2 SeO4-2 + Fe+2 + 2 H+', logK: 110.545, dlogK: 2.80 },
          { id: 'Fe1.04Se(s)', rx: 'Fe1.04Se(s) + 2.02 O2(g) + 0.08 H+ = SeO4-2 + 1.04 Fe+2 + 0.04 H2O', logK: 82.87, dlogK: 0.92 },
          { id: 'Se(s)', rx: 'Se(s) + 1.5 O2(g) + H2O = SeO4-2 + 2 H+', logK: 35.44, dlogK: 0.56 },
        ],
      },
      {
        el: 'Th', name: 'Thorium', master: 'Th+4',
        species: [
          { id: 'ThOH+3', rx: 'Th+4 + H2O = ThOH+3 + H+', logK: -2.50, dlogK: 0.50 },
          { id: 'Th(OH)2+2', rx: 'Th+4 + 2 H2O = Th(OH)2+2 + 2 H+', logK: -6.20, dlogK: 0.50 },
          { id: 'Th(OH)4(aq)', rx: 'Th+4 + 4 H2O = Th(OH)4(aq) + 4 H+', logK: -17.40, dlogK: 0.70 },
          { id: 'ThCO3(OH)3-', rx: 'Th+4 + CO3-2 + 3 H2O = ThCO3(OH)3- + 3 H+', logK: -3.70, dlogK: 0.70 },
          { id: 'ThCO3(OH)4-2', rx: 'Th+4 + CO3-2 + 4 H2O = ThCO3(OH)4-2 + 4 H+', logK: -15.60, dlogK: 0.60 },
          { id: 'Th(CO3)5-6', rx: 'Th+4 + 5 CO3-2 = Th(CO3)5-6', logK: 31.00, dlogK: 0.70 },
          { id: 'ThOH(CO3)4-5', rx: 'Th+4 + 4 CO3-2 + H2O = ThOH(CO3)4-5 + H+', logK: 21.60, dlogK: 0.50 },
          { id: 'Th(CO3)2(OH)2-2', rx: 'Th+4 + 2 CO3-2 + 2 H2O = Th(CO3)2(OH)2-2 + 2 H+', logK: 8.80, dlogK: 0.50 },
          { id: 'ThSO4+2', rx: 'Th+4 + SO4-2 = ThSO4+2', logK: 6.17, dlogK: 0.32 },
          { id: 'Th(SO4)2(aq)', rx: 'Th+4 + 2 SO4-2 = Th(SO4)2(aq)', logK: 9.69, dlogK: 0.27 },
          { id: 'Th(SO4)3-2', rx: 'Th+4 + 3 SO4-2 = Th(SO4)3-2', logK: 10.75, dlogK: 0.07 },
          { id: 'ThCl+3', rx: 'Th+4 + Cl- = ThCl+3', logK: 1.70, dlogK: 0.10 },
        ],
        solids: [
          { id: 'ThO2·2H2O(am,aged)', rx: 'ThO2·2H2O(am,aged) + 4 H+ = Th+4 + 4 H2O', logK: 8.50, dlogK: 0.90 },
        ],
      },
      {
        el: 'Pa', name: 'Protactinium', master: 'PaO2+',
        species: [
          { id: 'PaO2OH(aq)', rx: 'PaO2+ + H2O = PaO2OH(aq) + H+', logK: -4.50, dlogK: 0.20, qSRSite: [2, 0, 0, 0, 0, 0, 0] },
        ],
        solids: [
          { id: 'Pa2O5(s)', rx: 'Pa2O5(s) + 2 H+ = 2 PaO2+ + H2O', logK: -4.00, dlogK: 1.00 },
        ],
      },
      {
        el: 'U', name: 'Uranium', master: 'UO2+2',
        species: [
          { id: 'UO2OH+', rx: 'UO2+2 + H2O = UO2OH+ + H+', logK: -5.25, dlogK: 0.24 },
          { id: 'UO2(OH)2(aq)', rx: 'UO2+2 + 2 H2O = UO2(OH)2(aq) + 2 H+', logK: -12.15, dlogK: 0.07 },
          { id: 'UO2(OH)3-', rx: 'UO2+2 + 3 H2O = UO2(OH)3- + 3 H+', logK: -20.25, dlogK: 1.05 },
          { id: 'UO2(OH)4-2', rx: 'UO2+2 + 4 H2O = UO2(OH)4-2 + 4 H+', logK: -32.40, dlogK: 0.68 },
          { id: '(UO2)3(OH)5+', rx: '3 UO2+2 + 5 H2O = (UO2)3(OH)5+ + 5 H+', logK: -15.55, dlogK: 0.12 },
          { id: '(UO2)3(OH)7-', rx: '3 UO2+2 + 7 H2O = (UO2)3(OH)7- + 7 H+', logK: -32.20, dlogK: 0.80 },
          { id: 'UO2CO3(aq)', rx: 'UO2+2 + CO3-2 = UO2CO3(aq)', logK: 9.94, dlogK: 0.03 },
          { id: 'UO2(CO3)2-2', rx: 'UO2+2 + 2 CO3-2 = UO2(CO3)2-2', logK: 16.61, dlogK: 0.09 },
          { id: 'UO2(CO3)3-4', rx: 'UO2+2 + 3 CO3-2 = UO2(CO3)3-4', logK: 21.84, dlogK: 0.04 },
          // The workbooks (U!G32) multiply by [CO3-2]^3 for the one carbonate.
          { id: '(UO2)2CO3(OH)3-', rx: '2 UO2+2 + CO3-2 + 3 H2O = (UO2)2CO3(OH)3- + 3 H+', logK: -0.86, dlogK: 0.50, ligSRSite: { CO3: 3 } },
          { id: 'UO2+', rx: 'UO2+2 + 0.5 H2O = UO2+ + 0.25 O2(g) + H+', logK: -19.30, dlogK: 0.02 },
          { id: 'U(OH)3+', rx: 'UO2+2 + 2 H2O = U(OH)3+ + H+ + 0.5 O2(g)', logK: -37.22, dlogK: 1.00 },
          { id: 'U(OH)4(aq)', rx: 'UO2+2 + 3 H2O = U(OH)4(aq) + 2 H+ + 0.5 O2(g)', logK: -42.52, dlogK: 1.40 },
          { id: 'U(CO3)4-4', rx: 'UO2+2 + 4 CO3-2 + 2 H+ = U(CO3)4-4 + 0.5 O2(g) + H2O', logK: 2.60, dlogK: 0.93 },
        ],
        solids: [
          { id: 'UO2·2H2O(am)', rx: 'UO2·2H2O(am) + 2 H+ + 0.5 O2(g) = UO2+2 + 3 H2O', logK: 34.02, dlogK: 1.09 },
          { id: 'Coffinite', rx: 'USiO4(s) + 2 H+ + 0.5 O2(g) + H2O = UO2+2 + H4SiO4', logK: 31.02, dlogK: 6.57 },
          { id: 'Schoepite', rx: 'UO3·2H2O(s) + 2 H+ = UO2+2 + 3 H2O', logK: 5.96, dlogK: 0.18 },
          { id: 'CaU2O7·3H2O(s)', rx: 'CaU2O7·3H2O(s) + 6 H+ = 2 UO2+2 + Ca+2 + 6 H2O', logK: 23.40, dlogK: 1.00 },
          { id: 'Becquerelite', rx: 'Ca(UO2)6O4(OH)6·8H2O(s) + 14 H+ = Ca+2 + 6 UO2+2 + 18 H2O', logK: 29.00, dlogK: 1.00 },
          { id: 'Uranophane', rx: 'Ca(UO2)2(SiO3OH)2·5H2O(s) + 6 H+ = Ca+2 + 2 UO2+2 + 2 H4SiO4 + 5 H2O', logK: 9.42, dlogK: 5.06 },
        ],
      },
      {
        el: 'Np', name: 'Neptunium', master: 'Np+4',
        species: [
          { id: 'Np(OH)3+', rx: 'Np+4 + 3 H2O = Np(OH)3+ + 3 H+', logK: -2.80, dlogK: 1.00 },
          { id: 'Np(OH)4(aq)', rx: 'Np+4 + 4 H2O = Np(OH)4(aq) + 4 H+', logK: -8.30, dlogK: 1.10 },
          { id: 'Np(CO3)4-4', rx: 'Np+4 + 4 CO3-2 = Np(CO3)4-4', logK: 36.684, dlogK: 1.03 },
          { id: 'Np(OH)4CO3-2', rx: 'Np+4 + CO3-2 + 4 H2O = Np(OH)4CO3-2 + 4 H+', logK: -6.83, dlogK: 1.13 },
          { id: 'NpCO3(OH)3-', rx: 'Np+4 + CO3-2 + 3 H2O = NpCO3(OH)3- + 3 H+', logK: 3.82, dlogK: 1.13 },
          { id: 'Np(OH)2(CO3)2-2', rx: 'Np+4 + 2 CO3-2 + 2 H2O = Np(OH)2(CO3)2-2 + 2 H+', logK: 15.17, dlogK: 1.50 },
          { id: 'NpO2+', rx: 'Np+4 + 0.25 O2(g) + 1.5 H2O = NpO2+ + 3 H+', logK: 10.57, dlogK: 0.12 },
          { id: 'NpO2OH(aq)', rx: 'Np+4 + 0.25 O2(g) + 2.5 H2O = NpO2OH(aq) + 4 H+', logK: -0.73, dlogK: 0.71 },
          { id: 'NpO2(OH)2-', rx: 'Np+4 + 0.25 O2(g) + 3.5 H2O = NpO2(OH)2- + 5 H+', logK: -23.6 + 10.57, dlogK: Math.sqrt(0.5 * 0.5 + 0.12 * 0.12) },
          { id: 'NpO2CO3-', rx: 'Np+4 + 0.25 O2(g) + CO3-2 + 1.5 H2O = NpO2CO3- + 3 H+', logK: 15.53, dlogK: 0.13 },
          { id: 'NpO2(CO3)2-3', rx: 'Np+4 + 0.25 O2(g) + 2 CO3-2 + 1.5 H2O = NpO2(CO3)2-3 + 3 H+', logK: 17.10, dlogK: 0.16 },
          { id: 'NpO2(OH)2(aq)', rx: 'Np+4 + 0.5 O2(g) + 3 H2O = NpO2(OH)2(aq) + 4 H+', logK: -0.45, dlogK: 1.51 },
          { id: 'NpO2(CO3)2-2', rx: 'Np+4 + 0.5 O2(g) + H2O + 2 CO3-2 = NpO2(CO3)2-2 + 2 H+', logK: 28.28, dlogK: 0.74 },
          { id: 'NpO2(CO3)3-4', rx: 'Np+4 + 0.5 O2(g) + H2O + 3 CO3-2 = NpO2(CO3)3-4 + 2 H+', logK: 31.13, dlogK: 0.24 },
        ],
        solids: [
          { id: 'NpO2·2H2O(am)', rx: 'NpO2·2H2O(am) + 4 H+ = Np+4 + 4 H2O', logK: -0.70, dlogK: 0.50 },
          { id: 'NpO2OH(am,aged)', rx: 'NpO2OH(am,aged) + 4 H+ = Np+4 + 0.25 O2(g) + 2.5 H2O', logK: -5.87, dlogK: 0.23 },
          { id: 'NaNpO2CO3·3.5H2O(s)', rx: 'NaNpO2CO3·3.5H2O(s) + 3 H+ = Np+4 + 0.25 O2(g) + 5 H2O + CO3-2 + Na+', logK: -21.57, dlogK: 0.27 },
        ],
      },
      {
        el: 'Pu', name: 'Plutonium', master: 'Pu+3',
        species: [
          { id: 'PuOH+2', rx: 'Pu+3 + H2O = PuOH+2 + H+', logK: -6.90, dlogK: 0.30 },
          { id: 'Pu(OH)2+', rx: 'Pu+3 + 2 H2O = Pu(OH)2+ + 2 H+', logK: -15.90, dlogK: 1.00 },
          { id: 'Pu(OH)3(aq)', rx: 'Pu+3 + 3 H2O = Pu(OH)3(aq) + 3 H+', logK: -25.30, dlogK: 1.50 },
          { id: 'PuCO3+', rx: 'Pu+3 + CO3-2 = PuCO3+', logK: 7.64, dlogK: 0.86 },
          { id: 'Pu(CO3)2-', rx: 'Pu+3 + 2 CO3-2 = Pu(CO3)2-', logK: 12.54, dlogK: 0.86 },
          { id: 'Pu(CO3)3-3', rx: 'Pu+3 + 3 CO3-2 = Pu(CO3)3-3', logK: 16.40, dlogK: 1.40 },
          { id: 'PuSO4+', rx: 'Pu+3 + SO4-2 = PuSO4+', logK: 3.912, dlogK: 0.66 },
          { id: 'Pu(SO4)2-', rx: 'Pu+3 + 2 SO4-2 = Pu(SO4)2-', logK: 5.704, dlogK: 0.91 },
          { id: 'Pu(OH)3+', rx: 'Pu+3 + 0.25 O2(g) + 2.5 H2O = Pu(OH)3+ + 2 H+', logK: 0.79, dlogK: 0.73 },
          { id: 'Pu(OH)4(aq)', rx: 'Pu+3 + 0.25 O2(g) + 3.5 H2O = Pu(OH)4(aq) + 3 H+', logK: -5.41, dlogK: 0.84 },
          { id: 'Pu(CO3)4-4', rx: 'Pu+3 + 0.25 O2(g) + 4 CO3-2 + H+ = Pu(CO3)4-4 + 0.5 H2O', logK: 40.09, dlogK: 1.29 },
          { id: 'PuO2+', rx: 'Pu+3 + 0.5 O2(g) + H2O = PuO2+ + 2 H+', logK: 6.42, dlogK: 0.96 },
          { id: 'PuO2CO3-', rx: 'Pu+3 + 0.5 O2(g) + CO3-2 + H2O = PuO2CO3- + 2 H+', logK: 11.54, dlogK: 0.97 },
          { id: 'PuO2(OH)2(aq)', rx: 'Pu+3 + 0.75 O2(g) + 2.5 H2O = PuO2(OH)2(aq) + 3 H+', logK: -1.82, dlogK: 1.91 },
          { id: 'PuO2CO3(aq)', rx: 'Pu+3 + 0.75 O2(g) + CO3-2 + 0.5 H2O = PuO2CO3(aq) + H+', logK: 20.88, dlogK: 1.29 },
          { id: 'PuO2(CO3)2-2', rx: 'Pu+3 + 0.75 O2(g) + 2 CO3-2 + 0.5 H2O = PuO2(CO3)2-2 + H+', logK: 26.08, dlogK: 1.29 },
          { id: 'PuO2(CO3)3-4', rx: 'Pu+3 + 0.75 O2(g) + 3 CO3-2 + 0.5 H2O = PuO2(CO3)3-4 + H+', logK: 29.38, dlogK: 1.29 },
        ],
        solids: [
          { id: 'Pu(OH)3(s)', rx: 'Pu(OH)3(s) + 3 H+ = Pu+3 + 3 H2O', logK: 15.80, dlogK: 1.50 },
          { id: 'PuCO3OH(s)', rx: 'PuCO3OH(s) + H+ = Pu+3 + CO3-2 + H2O', logK: -5.94, dlogK: 1.26 },
          { id: 'Pu(OH)4(s)', rx: 'Pu(OH)4(s) + 3 H+ = Pu+3 + 0.25 O2(g) + 3.5 H2O', logK: -3.89, dlogK: 1.47 },
          { id: 'PuO2(OH)2·H2O(s)', rx: 'PuO2(OH)2·H2O(s) + 3 H+ = Pu+3 + 0.75 O2(g) + 3.5 H2O', logK: 5.5 + 15.82 + 17.45 + 17.69 - 62.31, dlogK: Math.sqrt(1 + 0.7 * 0.7 + 0.69 * 0.69 + 0.67 * 0.67) },
        ],
      },
      {
        el: 'Am', name: 'Americium', master: 'Am+3',
        species: [
          { id: 'AmOH+2', rx: 'Am+3 + H2O = AmOH+2 + H+', logK: -7.20, dlogK: 0.50 },
          { id: 'Am(OH)2+', rx: 'Am+3 + 2 H2O = Am(OH)2+ + 2 H+', logK: -15.10, dlogK: 0.70 },
          { id: 'Am(OH)3(aq)', rx: 'Am+3 + 3 H2O = Am(OH)3(aq) + 3 H+', logK: -26.20, dlogK: 0.50 },
          { id: 'AmCO3+', rx: 'Am+3 + CO3-2 = AmCO3+', logK: 8.00, dlogK: 0.40 },
          { id: 'Am(CO3)2-', rx: 'Am+3 + 2 CO3-2 = Am(CO3)2-', logK: 12.90, dlogK: 0.60 },
          { id: 'Am(CO3)3-3', rx: 'Am+3 + 3 CO3-2 = Am(CO3)3-3', logK: 15.00, dlogK: 1.00 },
          { id: 'AmHCO3+2', rx: 'Am+3 + H+ + CO3-2 = AmHCO3+2', logK: 13.43, dlogK: 0.30 },
          { id: 'AmSO4+', rx: 'Am+3 + SO4-2 = AmSO4+', logK: 3.30, dlogK: 0.15 },
          { id: 'Am(SO4)2-', rx: 'Am+3 + 2 SO4-2 = Am(SO4)2-', logK: 3.70, dlogK: 0.15 },
          { id: 'AmCl+2', rx: 'Am+3 + Cl- = AmCl+2', logK: 0.24, dlogK: 0.03 },
          { id: 'AmCl2+', rx: 'Am+3 + 2 Cl- = AmCl2+', logK: -0.74, dlogK: 0.05 },
        ],
        solids: [
          { id: 'Am(OH)3(am)', rx: 'Am(OH)3(am) + 3 H+ = Am+3 + 3 H2O', logK: 16.90, dlogK: 0.80 },
          { id: 'AmCO3OH(s)', rx: 'AmCO3OH(s) + H+ = Am+3 + CO3-2 + H2O', logK: -6.20, dlogK: 1.00 },
          { id: 'Am2(CO3)3(s)', rx: 'Am2(CO3)3(s) = 2 Am+3 + 3 CO3-2', logK: -33.40, dlogK: 2.20 },
          { id: 'NaAm(CO3)2·5H2O(s)', rx: 'NaAm(CO3)2·5H2O(s) = Am+3 + 2 CO3-2 + 5 H2O + Na+', logK: -21.00, dlogK: 0.50 },
        ],
      },
      {
        // The curium data are americium's by chemical analogy (TR-10-52).
        el: 'Cm', name: 'Curium', master: 'Cm+3', analogue: 'Am',
        species: [
          { id: 'CmOH+2', rx: 'Cm+3 + H2O = CmOH+2 + H+', logK: -7.20, dlogK: 0.50 },
          { id: 'Cm(OH)2+', rx: 'Cm+3 + 2 H2O = Cm(OH)2+ + 2 H+', logK: -15.10, dlogK: 0.70 },
          { id: 'Cm(OH)3(aq)', rx: 'Cm+3 + 3 H2O = Cm(OH)3(aq) + 3 H+', logK: -26.20, dlogK: 0.50 },
          { id: 'CmCO3+', rx: 'Cm+3 + CO3-2 = CmCO3+', logK: 8.00, dlogK: 0.40 },
          { id: 'Cm(CO3)2-', rx: 'Cm+3 + 2 CO3-2 = Cm(CO3)2-', logK: 12.90, dlogK: 0.60 },
          { id: 'Cm(CO3)3-3', rx: 'Cm+3 + 3 CO3-2 = Cm(CO3)3-3', logK: 15.00, dlogK: 1.00 },
          { id: 'CmHCO3+2', rx: 'Cm+3 + H+ + CO3-2 = CmHCO3+2', logK: 13.43, dlogK: 0.55 },
          { id: 'CmSO4+', rx: 'Cm+3 + SO4-2 = CmSO4+', logK: 3.30, dlogK: 0.15 },
          { id: 'Cm(SO4)2-', rx: 'Cm+3 + 2 SO4-2 = Cm(SO4)2-', logK: 3.70, dlogK: 0.15 },
          { id: 'CmCl+2', rx: 'Cm+3 + Cl- = CmCl+2', logK: 0.24, dlogK: 0.03 },
          { id: 'CmCl2+', rx: 'Cm+3 + 2 Cl- = CmCl2+', logK: -0.74, dlogK: 0.05 },
        ],
        solids: [
          { id: 'Cm(OH)3(am)', rx: 'Cm(OH)3(am) + 3 H+ = Cm+3 + 3 H2O', logK: 16.90, dlogK: 0.80 },
          { id: 'CmCO3OH(s)', rx: 'CmCO3OH(s) + H+ = Cm+3 + CO3-2 + H2O', logK: -6.20, dlogK: 1.00 },
          { id: 'Cm2(CO3)3(s)', rx: 'Cm2(CO3)3(s) = 2 Cm+3 + 3 CO3-2', logK: -33.40, dlogK: 2.20 },
        ],
      },
      {
        el: 'Sm', name: 'Samarium', master: 'Sm+3',
        species: [
          { id: 'SmOH+2', rx: 'Sm+3 + H2O = SmOH+2 + H+', logK: -7.90, dlogK: 0.10 },
          { id: 'Sm(OH)2+', rx: 'Sm+3 + 2 H2O = Sm(OH)2+ + 2 H+', logK: -16.50, dlogK: 0.20 },
          { id: 'Sm(OH)3(aq)', rx: 'Sm+3 + 3 H2O = Sm(OH)3(aq) + 3 H+', logK: -25.90, dlogK: 1.00 },
          { id: 'Sm(OH)4-', rx: 'Sm+3 + 4 H2O = Sm(OH)4- + 4 H+', logK: -36.90, dlogK: 1.00 },
          { id: 'SmCO3+', rx: 'Sm+3 + CO3-2 = SmCO3+', logK: 7.80, dlogK: 0.50 },
          { id: 'Sm(CO3)2-', rx: 'Sm+3 + 2 CO3-2 = Sm(CO3)2-', logK: 12.80, dlogK: 0.60 },
          { id: 'SmHCO3+2', rx: 'Sm+3 + CO3-2 + H+ = SmHCO3+2', logK: 12.43, dlogK: 0.50 },
          { id: 'SmSO4+', rx: 'Sm+3 + SO4-2 = SmSO4+', logK: 3.50, dlogK: 0.20 },
          { id: 'Sm(SO4)2-', rx: 'Sm+3 + 2 SO4-2 = Sm(SO4)2-', logK: 5.20, dlogK: 0.10 },
          { id: 'SmCl+2', rx: 'Sm+3 + Cl- = SmCl+2', logK: 0.40, dlogK: 0.10 },
        ],
        solids: [
          { id: 'Sm(OH)3(am)', rx: 'Sm(OH)3(am) + 3 H+ = Sm+3 + 3 H2O', logK: 18.60, dlogK: 1.00 },
          { id: 'Sm2(CO3)3(s)', rx: 'Sm2(CO3)3(s) = 2 Sm+3 + 3 CO3-2', logK: -34.50, dlogK: 2.00 },
          { id: 'SmOHCO3(s)', rx: 'SmOHCO3(s) + H+ = Sm+3 + CO3-2 + H2O', logK: -7.70, dlogK: 0.30, qSRSite: [-1, 0, -1, -1, 0, 0, 0] },
        ],
      },
      {
        el: 'Ho', name: 'Holmium', master: 'Ho+3',
        species: [
          { id: 'HoOH+2', rx: 'Ho+3 + H2O = HoOH+2 + H+', logK: -7.90, dlogK: 0.20 },
          { id: 'Ho(OH)2+', rx: 'Ho+3 + 2 H2O = Ho(OH)2+ + 2 H+', logK: -16.10, dlogK: 0.10 },
          { id: 'Ho(OH)3(aq)', rx: 'Ho+3 + 3 H2O = Ho(OH)3(aq) + 3 H+', logK: -24.50, dlogK: 0.10 },
          { id: 'Ho(OH)4-', rx: 'Ho+3 + 4 H2O = Ho(OH)4- + 4 H+', logK: -33.40, dlogK: 0.20 },
          { id: 'HoCO3+', rx: 'Ho+3 + CO3-2 = HoCO3+', logK: 8.00, dlogK: 0.40 },
          { id: 'Ho(CO3)2-', rx: 'Ho+3 + 2 CO3-2 = Ho(CO3)2-', logK: 13.30, dlogK: 0.60 },
          { id: 'HoHCO3+2', rx: 'Ho+3 + CO3-2 + H+ = HoHCO3+2', logK: 12.50, dlogK: 0.50 },
          { id: 'HoSO4+', rx: 'Ho+3 + SO4-2 = HoSO4+', logK: 3.40, dlogK: 0.30 },
          { id: 'Ho(SO4)2-', rx: 'Ho+3 + 2 SO4-2 = Ho(SO4)2-', logK: 4.90, dlogK: 0.30 },
          { id: 'HoCl+2', rx: 'Ho+3 + Cl- = HoCl+2', logK: 0.30, dlogK: 0.50 },
        ],
        solids: [
          { id: 'Ho(OH)3(am)', rx: 'Ho(OH)3(am) + 3 H+ = Ho+3 + 3 H2O', logK: 17.80, dlogK: 0.30 },
          { id: 'Ho2(CO3)3(s)', rx: 'Ho2(CO3)3(s) = 2 Ho+3 + 3 CO3-2', logK: -33.80, dlogK: 1.00 },
        ],
      },
      {
        el: 'Pb', name: 'Lead', master: 'Pb+2',
        species: [
          { id: 'PbOH+', rx: 'Pb+2 + H2O = PbOH+ + H+', logK: -7.51, dlogK: 0.50 },
          { id: 'Pb(OH)2(aq)', rx: 'Pb+2 + 2 H2O = Pb(OH)2(aq) + 2 H+', logK: -16.95, dlogK: 0.20 },
          { id: 'Pb(OH)3-', rx: 'Pb+2 + 3 H2O = Pb(OH)3- + 3 H+', logK: -27.20, dlogK: 0.70 },
          { id: 'Pb(OH)4-2', rx: 'Pb+2 + 4 H2O = Pb(OH)4-2 + 4 H+', logK: -38.90, dlogK: 0.80 },
          { id: 'PbCO3(aq)', rx: 'Pb+2 + CO3-2 = PbCO3(aq)', logK: 7.00, dlogK: 0.50 },
          { id: 'PbCl+', rx: 'Pb+2 + Cl- = PbCl+', logK: 1.55, dlogK: 0.30 },
          { id: 'PbCl2(aq)', rx: 'Pb+2 + 2 Cl- = PbCl2(aq)', logK: 2.00, dlogK: 0.30 },
          { id: 'PbCl3-', rx: 'Pb+2 + 3 Cl- = PbCl3-', logK: 2.01, dlogK: 0.30 },
        ],
        solids: [
          { id: 'PbClOH(s)', rx: 'PbClOH(s) + H+ = Pb+2 + Cl- + H2O', logK: 0.62, dlogK: 0.30 },
          { id: 'Cerussite', rx: 'PbCO3(s) = Pb+2 + CO3-2', logK: -13.29, dlogK: 0.69 },
          { id: 'Hydrocerussite', rx: 'Pb3(CO3)2(OH)2(s) + 2 H+ = 3 Pb+2 + 2 CO3-2 + 2 H2O', logK: -17.91, dlogK: 1.94 },
        ],
      },
    ],
  };

  /* ---------------------------------------------------------------------
     TR-10-61 table A-1 (from TR-06-09), mol/kg. "≈0" and "≤ x" entries are
     written as 1e-20 and x. Si is not in the table (1e-20, see above).
     --------------------------------------------------------------------- */
  const TINY = 1e-20;
  const W = (id, pH, Na, Ca, Mg, K, Fe, HCO3, Cl, SO4, I, Eh) => ({ id, pH, Na, Ca, Mg, K, Fe, HCO3, Cl, SO4, I, Eh, Si: TINY });
  const TR1061_WATERS = [
    W('Forsmark', 7.2, 0.089, 0.023, 0.0093, 0.0009, 33e-6, 0.0022, 0.153, 0.0052, 0.19, -140),
    W('Laxemar', 7.9, 0.034, 0.0058, 0.00044, 0.00014, 8e-6, 0.0031, 0.039, 0.0013, 0.053, -280),
    W('Äspö', 7.7, 0.091, 0.047, 0.0017, 0.0002, 4e-6, 0.00016, 0.181, 0.0058, 0.24, -307),
    W('Finnsjön', 7.9, 0.012, 0.0035, 0.0007, 0.00005, 32e-6, 0.0046, 0.0157, 0.00051, 0.025, -250),
    W('Gideå', 9.3, 0.0046, 0.00052, 0.000045, 0.00005, 9e-7, 0.00023, 0.0050, 0.000001, 0.006, -201),
    W('Grimsel (interacted glacial meltwater)', 9.6, 0.00069, 0.00014, 6e-7, 0.000005, 3e-9, 0.00045, 0.00016, 0.00006, 0.0013, -200),
    W('Most saline groundwater at Laxemar', 7.9, 0.349, 0.464, 0.0001, 0.0007, 8e-6, 0.00010, 1.283, 0.009, 1.75, -314),
    W('Most saline groundwater at Olkiluoto', 7.0, 0.415, 0.449, 0.0053, 0.0007, 6e-5, 0.00014, 1.275, 0.00009, 1.76, -3),
    W('Cement pore water', 12.5, 0.002, 0.018, 0.0001, 0.0057, 10e-6, TINY, TINY, TINY, 0.057, NaN),
    W('Baltic seawater', 7.9, 0.089, 0.0024, 0.010, 0.002, 3e-7, 0.0016, 0.106, 0.0051, 0.13, NaN),
    W('Ocean water', 8.15, 0.469, 0.0103, 0.053, 0.01, 4e-8, 0.0021, 0.546, 0.0282, 0.65, NaN),
    W('Maximum salinity from glacial upconing', 7.9, 0.25, 0.27, 0.0001, 0.0005, 2e-6, 0.00015, 0.82, 0.01, 1.09, -400),
  ];

  /** TR-10-61 table 3-1: the example of the INPUT DATA sheet (Version A). */
  const TR1061_EXAMPLE = { id: 'TR-10-61 table 3-1 example', pH: 6, Eh: -143, I: 0.19, HCO3: 1.77e-3, SO4: 6.80e-3, Cl: 1.53e-1, Ca: 2.33e-2, Na: 8.88e-2, Fe: 3.31e-5, Si: 1.85e-4 };

  /** A deep copy of a dataset, so the page can edit its own. */
  function clone(data) {
    return JSON.parse(JSON.stringify(data));
  }

  return { SRSITE, TR1061_WATERS, TR1061_EXAMPLE, TINY, clone };
}));
