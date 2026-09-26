/* ==========================================================================
   EROSION_CORROSION.HTML: THE MODEL

   Buffer erosion and sedimentation, and copper canister corrosion by
   sulphide, for every deposition hole of a KBS-3 repository layout -- the
   calculation SKB made in Excel for SR-Site and the PSAR (SKBdoc 1895159,
   ErosionCorrosionModel_2_0, documented in SKBdoc 1895157) and later ported
   to Python (erosion_corrosion_model_2_0.py, _2_4.py).

   This file is the arithmetic only. It knows nothing of files or of the page:
   it takes a hydro table (see ec-hydro.js), a sulphide distribution (see
   ec-hsdata.js) and a parameter object, and returns every per-hole quantity
   the workbook's sheet "Calc" holds, the table of failure times the workbook
   hands to the radionuclide transport calculations ("InputTrptCalcs"), and
   the key outputs of the sheet "Info". It runs under Node for the tests in
   resources/tests/erosion_corrosion/ and in the browser as ECModel.

   Every parameter carries the name it has in the workbook (xl) and in the
   Python port (py), so a number here can be traced to a cell there.

   Conventions, kept from the sources so the answers agree to the last digit:

     - Times in years, lengths in metres, concentrations in mol/L. The year
       is 365 days (Info!SecpYr = 3600*24*365), and scipy.constants.year in
       the Python port is the same number.
     - 1E+99 stands for "never" (tAdv, tFailMin, HSMin), as in the workbook.
     - The sulphide table is sorted in descending order, and the j-th failure
       time of a hole uses the j-th highest concentration: that is how both
       the workbook (INDEX(HSTab, AT)) and the Python port read the table.
   ========================================================================== */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ECModel = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const NEVER = 1e99;
  const PI = Math.PI;

  /* ---------------------------------------------------------------------
     The parameter catalogue

     One entry per setting and per model parameter, in the order and with
     the wording of the workbook's sheet "Info". The page builds its panel
     from this list; the tests read defaults from it; the case file written
     by the page is a {key: value} object over these keys.

     The text: `desc` (and a group's `about`) is the short line the panel
     shows under the label. `info` is what the page's (i) adds to it --
     what the parameter does in the calculation, which models use it, what
     to watch for -- as paragraphs; `optionInfo` says what each choice of a
     select does. Plain text with `code` and **bold** only.
     --------------------------------------------------------------------- */
  const GROUPS = [
    { id: 'rejection', label: 'Rejection of deposition holes',
      about: 'Criteria relating to fracture geometry or flow that would in principle be observable during construction. A rejected hole takes no part in the calculation but still counts in the total the results are normalised against.',
      info: ['A hole is rejected when any criterion that is on holds, and the Rejected by column of the Deposition holes tab names every one that does. Rejected holes have no failure times and are set to zero in the plots “after rejection”.',
        'The corrected mean is scaled by the canisters to normalise to over the accepted holes, the total less the rejected: a rejected hole stays in the total number of positions but not among the holes the result is divided by.',
        'OKFLAG filtering does not reject: it leaves holes out of the failure table but keeps them among the accepted holes.'] },
    { id: 'buffer', label: 'Buffer erosion and sedimentation',
      about: 'How fast the bentonite is lost to the intersecting fracture, and how much must be lost before the buffer is advective. TR-10-66 and TR-16-11.',
      info: ['For every accepted hole with a flowing fracture, tAdv = MBuffAdv / (loss rate · ftDilute). A rejected hole, or one with no flowing fracture, never becomes advective.',
        'Which of the parameters matter depends on the buffer loss model; the information on each says which models use it.'] },
    { id: 'corrosion', label: 'Corrosion, advective buffer',
      about: 'Sulphide in the flowing groundwater reaching the copper through an eroded buffer. TR-10-66, section 4.3.',
      info: ['Once the buffer is advective, tCorr = CorrHoleFact / (Qeq·[HS⁻]) and tFail = tAdv + tCorr. CorrHoleFact = dCan·Acorr·ρCu / (fHS·MCu) is the sulphide, in kmol, that corrodes through the copper over the area Acorr = π·rCan·hCorr; Qeq is the equivalent flow rate through the eroded buffer.',
        'The Summary lists qlim and CorrHoleFact as these parameters make them.'] },
    { id: 'diffusive', label: 'Corrosion, intact buffer',
      about: 'Diffusion through an intact buffer at a fixed sulphide concentration, with and without a spalled zone. Only the distribution plots use these. TR-10-66, sections 4.2 and 4.3.',
      info: ['They feed the plot Corrosion rate, intact buffer of the Distributions tab (the workbook’s CorrDiffPlt), and through the fixed sulphide concentration the plot Corrosion rate, eroded buffer. The failure times do not depend on them.'] },
    { id: 'freshwater', label: 'Dilute-water penetration times',
      about: 'The time for fresh water to reach a deposition hole, printed beside the failure table. R-09-20, section F.2.2.',
      info: ['tFreshWater = tw/ff + ((F/cf)/ff)²·De·εp / (4·erfInv²), with tw and F from the hydro file, ff the flow factor and cf the channelling factor.',
        'It is worked out for the holes that are not skipped, and this page shows it in the tFreshWater column of the Deposition holes tab and on the Calc sheets of the Excel export. Nothing else depends on it.'] },
    { id: 'misc', label: 'Constants and normalisation', about: '',
      info: ['The number of canisters the corrected counts refer to, and the length of the year in seconds.'] },
  ];

  const PARAMS = [
    // ---- rejection --------------------------------------------------
    { key: 'fpcFiltering', group: 'rejection', type: 'bool', def: true, xl: 'FPCFiltering', py: 'fpc_filtering',
      label: 'FPC filtering', desc: 'Reject deposition holes intersected by a fracture that intersects the full tunnel perimeter (FPC ≠ 0 in the hydro data).',
      info: ['FPC is 0, 1 for a fracture that intersects the full tunnel perimeter, or 2 for a deformation zone; either 1 or 2 rejects the hole.'] },
    { key: 'efpcFiltering', group: 'rejection', type: 'bool', def: true, xl: 'EFPCFiltering', py: 'efpc_filtering',
      label: 'EFPC filtering', desc: 'Reject holes fully intersected by a fracture that also intersects the number of consecutive holes below (extended FPC).',
      info: ['EFPC in the hydro data counts the neighbouring holes cut by the same fracture. The hole is rejected when EFPC is at least the number of EFPC holes.',
        'A hole that is not rejected this way, two rows from one that is, on a fracture of the same length and aperture, is an EFPC edge position. It is marked in the tables, and the Summary says whether a failed canister sits in one.'] },
    { key: 'efpcNumber', group: 'rejection', type: 'int', def: 5, xl: 'EFPCNumber', py: 'efpc_number', unit: '',
      label: 'Number of EFPC holes', desc: 'Consecutive deposition holes required for EFPC rejection; a hole is rejected when EFPC > this − 1.',
      info: ['Rounded to a whole number. The default 5 rejects a hole with EFPC ≥ 5. The same number decides which holes are EFPC edge positions.'] },
    { key: 'fracLenFiltering', group: 'rejection', type: 'bool', def: true, xl: 'FracLenFiltering', py: 'frac_len_filtering',
      label: 'Fracture length filtering', desc: 'Reject holes intersected by a fracture longer than the limit below.',
      info: ['FLEN in the hydro data is the length of the largest fracture intersecting the hole. DarcyTools tables have no FLEN, so for them this criterion rejects nothing.'] },
    { key: 'fracLenFilteringLim', group: 'rejection', type: 'number', def: 999, xl: 'FracLenFilteringLim', py: 'frac_len_filtering_lim', unit: 'm',
      label: 'Fracture length limit', desc: 'A deformation-zone fracture is given the length 1000 m in the hydro data, so 999 m rejects exactly those.',
      info: ['With fracture length filtering on, a hole is rejected when FLEN is greater than this limit.'] },
    { key: 'transFiltering', group: 'rejection', type: 'bool', def: true, xl: 'TransFiltering', py: 'trans_filtering',
      label: 'Transmissivity filtering (T/L)', desc: 'Reject holes whose fracture is both more transmissive and longer than the two limits below. TR-11-01, section 5.2.3.',
      info: ['The transmissivity is not in the hydro file: it is worked out from TRAPP by the law chosen under Transmissivity from aperture. DarcyTools tables have no FLEN, so for them this criterion rejects nothing.'] },
    { key: 'transFilteringLim', group: 'rejection', type: 'number', def: 1e-6, xl: 'TransFilteringLim', py: 'trans_filtering_lim', unit: 'm²/s',
      label: 'Transmissivity limit',
      info: ['The T/L criterion rejects a hole when the transmissivity of its fracture is above this limit and the fracture is longer than the fracture length limit for T/L. TR-11-01, section 5.2.3.',
        'With the Doe relation T exceeds 1e-6 m²/s when TRAPP exceeds 0.5 mm; with the cubic law and a = 0.01 m, when TRAPP exceeds 0.1 mm.'] },
    { key: 'minFlenT', group: 'rejection', type: 'number', def: 250 * Math.sqrt(PI), xl: 'MinFLENT', py: 'min_flent', unit: 'm',
      label: 'Fracture length limit for T/L', desc: 'Circular fractures of radius above 250 m are assumed identified in the geo-DFN; the side of the equivalent square in the hydro-DFN is 250·√π = 443 m.',
      info: ['The fracture must be longer than this for the T/L criterion to reject the hole.'] },
    { key: 'transmissivityLaw', group: 'rejection', type: 'select', def: 'Doe', py: 'transmissivity_law',
      options: [['Doe', 'Doe: T = (δ/0.5)²  (SR-Site, PSAR)'], ['Cubic', 'Cubic: T = (δ/a)³']],
      label: 'Transmissivity from aperture', desc: 'How the transmissivity used by the T/L criterion is back-calculated from the transport aperture. The workbook uses the Doe relation (TR-09-20, equation 3-2); the 2.4 Python port offers the cubic law as well.',
      info: ['The transmissivity is used by the T/L criterion and in the hydraulic gradient i = v·δ/T (v in m/s), which is the i column of the Deposition holes tab and the gradient plot; nothing else depends on it. Both laws take TRAPP as read, also with the pessimistic aperture on.'],
      optionInfo: {
        Doe: 'T = (δ/0.5)² m²/s with δ in m (TR-09-20, equation 3-2): the workbook’s relation, as used in SR-Site and the PSAR.',
        Cubic: 'T = (δ/a)³ m²/s with the reference aperture a below: the alternative of the 2.4 Python port, and its default there (FSAR).',
      } },
    { key: 'cubicRefAperture', group: 'rejection', type: 'number', def: 0.01, py: '(2.4: 0.01; 2.0: 0.032)', unit: 'm',
      label: 'Cubic-law reference aperture a', desc: 'Only with the cubic law: T = (δ/a)³ m²/s. 0.01 m in the 2.4 port (FSAR), 0.032 m in the 2.0 port.',
      info: ['The Python ports write the number into their formulas rather than keep it as an attribute, hence the brackets. The workbook has no cubic law.'] },
    { key: 'okFlagFiltering', group: 'rejection', type: 'bool', def: true, xl: 'OKFlagFiltering', py: 'ok_flag_filtering',
      label: 'OKFLAG filtering', desc: 'Leave out holes whose particle did not reach the surface in the hydro model (OKFLAG ≠ 0). These are skipped, not rejected: they still count in the total.',
      info: ['Off, such holes can fail like any other.'] },
    { key: 'highDarcyFiltering', group: 'rejection', type: 'bool', def: false, xl: 'HighDarcyFiltering', py: 'high_darcy_filtering',
      label: 'High Darcy flux filtering', desc: 'Reject holes with U0 above the limit below (saturated conditions). Off in SR-Site and the PSAR.',
      info: ['The limit is compared with the U0 column as read. In a DarcyTools .dtpm table that column holds the velocity Utot, not a Darcy flux.'] },
    { key: 'darcyFilterLim', group: 'rejection', type: 'number', def: 0.01, xl: 'DarcyFilterLim', py: 'darcy_filter_lim', unit: 'm/yr',
      label: 'Darcy flux limit',
      info: ['With high Darcy flux filtering on, a hole is rejected when U0 is above this limit.'] },
    { key: 'highFlowFiltering', group: 'rejection', type: 'bool', def: false, xl: 'HighFlowFiltering', py: 'high_flow_filtering',
      label: 'High inflow filtering', desc: 'Reject holes listed in an inflow-rejection file (open-repository inflow criteria, R-09-19). Off in SR-Site and the PSAR; needs a list of hole IDs loaded beside the hydro data.',
      info: ['Open the list under Hydro data, Inflow-rejection list. Its IDs are matched with the hole IDs of every realisation, whether loaded before or after the list.'] },

    // ---- buffer -----------------------------------------------------
    { key: 'buffModel', group: 'buffer', type: 'select', def: 'NewKTH', xl: 'BuffModel', py: 'buff_model',
      options: [['NewKTH', 'NewKTH: erosion, TR-16-11 (PSAR)'], ['OldKTH', 'OldKTH: erosion, TR-09-35 (SR-Site)'], ['Sediment', 'Sediment: sedimentation, TR-16-11'], ['Ero+Sed', 'Ero+Sed: erosion + sedimentation'], ['Amphos2023', 'Amphos2023: P-23-03, equation 5-1'], ['Amphos2025', 'Amphos2025: P-25-05, equation 7']],
      label: 'Buffer loss model', desc: 'Which expression gives the rate of buffer mass loss to the fracture.',
      info: ['Only the chosen model sets tAdv and the buffer loss rate plot. The information on each buffer parameter says which models use it.'],
      optionInfo: {
        NewKTH: 'The PSAR model (TR-16-11, chapter 4): rate = 4·ρs·δ·φR·√(DR·rRSS·v). DR comes from the cation concentration, or from the temperate and glacial ones as the effective DR. rRSS = rDepHole + 5 cm when forced, the PSAR setting; unforced it is solved with the Lambert W function, and Di and φi enter.',
        OldKTH: 'The SR-Site model (TR-09-35; TR-10-66, section 4.3.1): rate = Aero·δ·v^0.41, v in m/yr. Aero is its only parameter.',
        Sediment: 'TR-16-11: the smaller of the loss rate at the rim, JExp·δ·2π·rRSS,sed·sin α, and the rate at which the lost material can settle in the fracture, δ³/(12·μ)·(ρagg − ρw)·g·φR·ρs·2·rRSS,sed. rRSS,sed = rDepHole + 5 cm when forced.',
        'Ero+Sed': 'The NewKTH erosion rate and the sedimentation rate added, with the parameters of both.',
        Amphos2023: 'The Amphos21 power-law fit of P-23-03, equation 5-1, as the Python ports carry it: the rate goes as v^1.0484·δ^2.0156. None of the buffer parameters enters it.',
        Amphos2025: 'The Amphos21 expression of P-25-05, equation 7, as the Python ports carry it: √v·δ^1.2 (δ in mm) times the hole diameter and a term in c^−0.7, weighted by the temperate and glacial fractions of dilute time at their cation concentrations.',
      } },
    { key: 'initialAdvection', group: 'buffer', type: 'bool', def: false, xl: 'InitialAdvection', py: 'initial_advection',
      label: 'Initial advection', desc: 'No buffer from the start: tAdv = 0 in every hole that has a flowing fracture.',
      info: ['The buffer loss model and its parameters then do not affect the failure times. Rejected holes, and holes with no flowing fracture, still never become advective.'] },
    { key: 'mBuffAdv', group: 'buffer', type: 'number', def: 1200, xl: 'MBuffAdv', py: 'm_buffadv', unit: 'kg',
      label: 'Buffer loss for advection', desc: 'Mass lost before the buffer is advective. TR-11-01, section 10.3.9.',
      info: ['tAdv = MBuffAdv / (loss rate · ftDilute). The buffer loss rate plot draws two reference lines from it: this mass lost over the assessment time, and over the dilute fraction of it.'] },
    { key: 'fTDilute', group: 'buffer', type: 'number', def: 0.5, xl: 'ftDilute', py: 'f_tdilute', unit: '−',
      label: 'Fraction of time dilute', desc: 'Fraction of the assessment period with groundwater dilute enough for erosion. 0.25 in SR-Site, 0.5 in the PSAR. TR-11-01, section 10.3.11.',
      info: ['tAdv = MBuffAdv / (loss rate · ftDilute): halving the fraction doubles every tAdv.'] },
    { key: 'pessAperture', group: 'buffer', type: 'bool', def: false, xl: 'PessAperture', py: 'pess_aperture',
      label: 'Pessimistic aperture', desc: 'Use δ = 0.275·(TRAPP/0.5)^(2·0.297) instead of TRAPP. TR-11-01, section 12.2.2.',
      info: ['For any TRAPP below 0.11 m this δ is the larger: 0.1 mm becomes 1.75 mm. The loss rate of every model goes up with δ. For a ConnectFlow table the velocity v = U0·w/δ goes down and the flow through the eroded hole, q = fconc·U0·w·2·rDepHole, stays as it was.', 'The transmissivity of the T/L criterion is still worked out from TRAPP.'] },
    { key: 'advConst', group: 'buffer', type: 'number', def: 27.210847987074, xl: 'AdvConst', py: 'adv_const', unit: 'kg/(m·yr)',
      label: 'Aero (OldKTH)', desc: 'Rate = Aero·δ·v^0.41 with v in m/yr and δ in m. TR-10-64, equation 5-1.',
      info: ['Only the OldKTH model uses it.'] },
    { key: 'forceRrss', group: 'buffer', type: 'bool', def: true, xl: 'ForceRRSS', py: 'force_rrss',
      label: 'Force rRSS = rDepHole + 5 cm', desc: 'Put the steady-state loss radius 5 cm outside the hole instead of solving for it with the Lambert W function. TR-21-03.',
      info: ['It sets rRSS of the NewKTH erosion rate and rRSS,sed of the sedimentation rate. Off, NewKTH solves rRSS = rDepHole·(G/2 / W(G/2))² hole by hole and the sedimentation model solves rRSS,sed = FExp / W(FExp/rDepHole), and Di and φi then matter.',
        'The page solves W to machine precision; the workbook’s VBA stops at a residual of 1e-3, which shows only with this off.'] },
    { key: 'effectiveDR', group: 'buffer', type: 'bool', def: true, xl: 'EffectiveDRcIon', py: 'effective_d_r_c_ion',
      label: 'Effective DR over temperate and glacial', desc: 'DR = (fTemp·√DR(cTemp) + fGlac·√DR(cGlac))² instead of DR(cIon).',
      info: ['On, DR comes from the temperate and glacial fractions and cation concentrations, and the cation charge concentration is not used; off, DR = DR(cIon). DR(c) is a cubic fit in log10 c, valid for 0.1 to 4 mM. Only the NewKTH erosion rate uses DR, alone or in Ero+Sed.'] },
    { key: 'cIon', group: 'buffer', type: 'number', def: 0.1, xl: 'cIon', py: 'c_ion', unit: 'mM',
      label: 'Cation charge concentration', desc: 'Groundwater cation concentration weighted by charge. The DR fit holds for 0.1 to 4 mM.',
      info: ['Used only with the effective DR off.'] },
    { key: 'fracTemp', group: 'buffer', type: 'number', def: 0.5, xl: 'FracTemp', py: 'frac_temp', unit: '−', label: 'Fraction of dilute time, temperate',
      info: ['The share of the dilute time with temperate groundwater: a weight in the effective DR and in the Amphos2025 rate. The page does not make the temperate and glacial fractions add up to 1.'] },
    { key: 'cIonTemp', group: 'buffer', type: 'number', def: 3, xl: 'cIonTemp', py: 'c_ion_temp', unit: 'mM', label: 'Cation concentration, temperate',
      info: ['The cation charge concentration of temperate groundwater, for the effective DR and the Amphos2025 rate.'] },
    { key: 'fracGlac', group: 'buffer', type: 'number', def: 0.5, xl: 'FracGlac', py: 'frac_glac', unit: '−', label: 'Fraction of dilute time, glacial',
      info: ['The share of the dilute time with glacial groundwater: a weight in the effective DR and in the Amphos2025 rate.'] },
    { key: 'cIonGlac', group: 'buffer', type: 'number', def: 0.1, xl: 'cIonGlac', py: 'c_ion_glac', unit: 'mM', label: 'Cation concentration, glacial',
      info: ['The cation charge concentration of glacial groundwater, for the effective DR and the Amphos2025 rate.'] },
    { key: 'dI', group: 'buffer', type: 'number', def: 1e-9, xl: 'Di', py: 'd_i', unit: 'm²/s', label: 'Smectite diffusivity in the hole, Di',
      info: ['The diffusivity of smectite in the deposition hole. It enters G/2 of the unforced NewKTH rim radius and FExp of the unforced sedimentation radius, so it has no effect with Force rRSS on.'] },
    { key: 'phiI', group: 'buffer', type: 'number', def: 0.574, xl: 'Phi_i', py: 'phi_i', unit: '−', label: 'Smectite volume fraction in the hole, φi',
      info: ['The volume fraction of smectite in the deposition hole. Like Di it enters only the unforced radii, through φi − φR, so it has no effect with Force rRSS on.'] },
    { key: 'phiR', group: 'buffer', type: 'number', def: 0.015, xl: 'Phi_R', py: 'phi_r', unit: '−', label: 'Smectite volume fraction at the rim, φR',
      info: ['The volume fraction of smectite at the rim, where it is lost to the water. It enters the NewKTH rate, 4·ρs·δ·φR·√(DR·rRSS·v), and the settling rate of the sedimentation model.'] },
    { key: 'rhoS', group: 'buffer', type: 'number', def: 2700, xl: 'Rho_s', py: 'rho_s', unit: 'kg/m³', label: 'Smectite density, ρs',
      info: ['The density of the smectite mineral. It enters the NewKTH rate and the settling rate of the sedimentation model.'] },
    { key: 'jExp', group: 'buffer', type: 'number', def: 1000, xl: 'J_Exp', py: 'j_exp', unit: 'kg/(m²·yr)',
      label: 'Loss rate in Schatz’ experiments, JExp', desc: '850 to 1550 kg/(m²·yr) in TR-16-11; the PSAR sensitivity cases used 30.',
      info: ['The loss rate at the rim of the sedimentation model is JExp·δ·2π·rRSS,sed·sin α. Only Sediment and Ero+Sed use it.'] },
    { key: 'alphaDeg', group: 'buffer', type: 'number', def: 90, xl: 'alpha', py: '(π/2)', unit: '°', label: 'Fracture slope α', desc: 'The sedimentation model has sin α; 90° is a vertical fracture.',
      info: ['In degrees here. The workbook’s alpha is in radians, and the Python ports write π/2 into their formulas. Only Sediment and Ero+Sed use it.'] },
    { key: 'muAgg', group: 'buffer', type: 'number', def: 0.001, xl: 'mu_agg', py: 'mu_agg', unit: 'Pa·s', label: 'Viscosity of agglomerate fluid', desc: 'TR-16-11, table 6-2, the value that reproduces its figure 4-7.',
      info: ['It divides the settling rate δ³/(12·μ)·(ρagg − ρw)·g·φR·ρs·2·rRSS,sed. Only Sediment and Ero+Sed use it.'] },
    { key: 'rhoAgg', group: 'buffer', type: 'number', def: 1017, xl: 'rho_agg', py: 'rho_agg', unit: 'kg/m³', label: 'Density of agglomerate fluid',
      info: ['The density of the agglomerate fluid of the sedimentation model, TR-16-11, table 6-2. Its difference from the density of water, ρagg − ρw, drives the settling rate. Only Sediment and Ero+Sed use it.'] },
    { key: 'rhoW', group: 'buffer', type: 'number', def: 1000, xl: 'rho_w', py: 'rho_w', unit: 'kg/m³', label: 'Density of water',
      info: ['The density of water. With the density of the agglomerate fluid it sets the difference that drives the settling rate. Only Sediment and Ero+Sed use it.'] },
    { key: 'g', group: 'buffer', type: 'number', def: 9.81, xl: 'g', py: 'g', unit: 'm/s²', label: 'Gravitational acceleration',
      info: ['The gravitational acceleration, in the settling rate of the sedimentation model. Only Sediment and Ero+Sed use it.'] },

    // ---- corrosion, advective ---------------------------------------
    { key: 'tFailFiltering', group: 'corrosion', type: 'bool', def: true, xl: 'tFailFiltering', py: 't_fail_filtering',
      label: 'Failure time filtering', desc: 'Leave out holes that cannot fail before the limit below even at the highest sulphide concentration.',
      info: ['Such a hole has no rows in the failure table either way. The switch changes which holes count as skipped (the key output Positions left out of the failure table, and the Skipped column), and so which get a tFreshWater. It does not lift the assessment time.'] },
    { key: 'tFailFilteringLim', group: 'corrosion', type: 'number', def: 1e6, xl: 'tFailFilteringLim', py: 't_fail_filtering_lim', unit: 'yr',
      label: 'Assessment time', desc: 'The time the failure counts refer to; normally 1,000,000 years.',
      info: ['Only failure times before it enter the failure table: each hole’s HSmin is the sulphide concentration that fails it exactly then. The key outputs are counted at it, except those at 100,000 years, and the Against time chart ends at it. It applies with failure time filtering on or off.'] },
    { key: 'pessCorrGeo', group: 'corrosion', type: 'bool', def: false, xl: 'PessCorrGeo', py: 'pess_corr_geo',
      label: 'Pessimistic corrosion geometry', desc: 'Corroded height hCorr = dCan·π/2 instead of the buffer thickness. TR-10-66, p. 19.',
      info: ['With the default geometry hCorr falls from 0.35 m, the buffer thickness rDepHole − rCan, to 0.074 m, so CorrHoleFact and every tCorr are 4.7 times smaller.'] },
    { key: 'dCan', group: 'corrosion', type: 'number', def: 0.047, xl: 'dCan', py: 'd_can', unit: 'm', label: 'Copper thickness, dCan',
      info: ['The copper to corrode through: tCorr is proportional to it, and to its square with the pessimistic geometry, where it also sets hCorr. It also sets the copper-thickness reference lines of the corrosion-rate plots.'] },
    { key: 'rCan', group: 'corrosion', type: 'number', def: 0.525, xl: 'rCan', py: 'r_can', unit: 'm', label: 'Canister radius, rCan',
      info: ['The radius of the canister. With rDepHole it sets the buffer thickness dBuffer = rDepHole − rCan (0.35 m) and the volume of the eroded half of the buffer, Vzone = dBuffer·π(rDepHole² − rCan²)/2. It also sets the corroded area Acorr = π·rCan·hCorr.'] },
    { key: 'rDepHole', group: 'corrosion', type: 'number', def: 0.875, xl: 'rDepHole', py: 'r_dep_hole', unit: 'm', label: 'Deposition hole radius, rDepHole',
      info: ['The radius of the deposition hole. With rCan it sets the buffer thickness and Vzone. It also sets the flow through the eroded hole, q = fconc·U0·w·2·rDepHole, and the rim radius of the erosion and sedimentation models, rDepHole + 5 cm when forced.'] },
    { key: 'dWater', group: 'corrosion', type: 'number', def: 0.0315, xl: 'DWater', py: 'd_water', unit: 'm²/yr', label: 'Diffusivity in water, Dw',
      info: ['The diffusivity in water, in the equivalent flow rate through the eroded buffer, Qeq = min(1.13·√(q·Dw·Vzone)/dBuffer, q). The two branches cross at qlim, 0.0885 m³/yr with the defaults.'] },
    { key: 'w', group: 'corrosion', type: 'number', def: 5, xl: 'w', py: 'w', unit: 'm',
      label: 'Fracture width w', desc: 'The height Serco used to turn the fracture flow into U0; v = U0·w/δ. 5 m rather than the canister’s 4.835 m, to match.',
      info: ['For a ConnectFlow table v and q are proportional to it. For a DarcyTools table it has no effect on them: a .dtpm table carries the velocity itself, and the U0 of the older CSV is scaled by 8/w when it is read, which a change of w repeats.'] },
    { key: 'hCan', group: 'corrosion', type: 'number', def: 5, xl: 'hCan', py: 'h_can', unit: 'm', label: 'Canister height, hCan', desc: 'Used by the intact-buffer corrosion rate; 5 m to be compatible with Serco.',
      info: ['Only the intact-buffer corrosion rate without spalling uses it.'] },
    { key: 'flowConcFact', group: 'corrosion', type: 'number', def: 2, xl: 'FlowConcFact', py: 'flow_conc_fact', unit: '−', label: 'Flow concentration factor, fconc', desc: 'The cavity in the eroded buffer draws more flow.',
      info: ['q = fconc·U0·w·2·rDepHole is the flow through the eroded hole. Qeq follows q below qlim and √q above it.'] },
    { key: 'fHS', group: 'corrosion', type: 'number', def: 2, xl: 'fHS', py: 'fhs', unit: '−', label: 'Stoichiometric factor, fHS', desc: '2 Cu + HS⁻ → Cu₂S.',
      info: ['CorrHoleFact, the sulphide that corrodes through, is the copper in the corroded height, dCan·Acorr·ρCu, over fHS·MCu.'] },
    { key: 'moMassCu', group: 'corrosion', type: 'number', def: 63.55, xl: 'MoMassCu', py: 'mo_mass_cu', unit: 'kg/kmol', label: 'Molar mass of copper',
      info: ['The molar mass of copper, in CorrHoleFact and in the corrosion rates of the plots.'] },
    { key: 'rhoCu', group: 'corrosion', type: 'number', def: 8920, xl: 'RhoCu', py: 'rho_cu', unit: 'kg/m³', label: 'Density of copper',
      info: ['The density of copper, in CorrHoleFact and in the corrosion rates of the plots.'] },
    { key: 'averageFlow', group: 'corrosion', type: 'bool', def: false, xl: 'AverageFlow', py: 'average_flow', label: 'Flow averaging', desc: 'Divide the corrosion capacity by the factor below to average variable flow over the assessment time. Not used in SR-Site or the PSAR.',
      info: ['A factor above 1 shortens every tCorr by that factor.'] },
    { key: 'averageFlowFactor', group: 'corrosion', type: 'number', def: 1, xl: 'AverageFlowFactor', py: 'average_flow_factor', unit: '−', label: 'Averaging factor',
      info: ['With flow averaging on, CorrHoleFact is divided by it.'] },

    // ---- corrosion, intact buffer -----------------------------------
    { key: 'fixedSulphideConc', group: 'diffusive', type: 'number', def: 1e-5, xl: 'FixedSulphideConcentration', py: 'fixed_sulphide_conc', unit: 'M', label: 'Fixed sulphide concentration',
      info: ['The [HS⁻] of both corrosion-rate plots, intact and eroded buffer. The failure times use the sulphide distribution instead.'] },
    { key: 'bufferConcFact', group: 'diffusive', type: 'number', def: 7, xl: 'BufferConcentrationFactor', py: 'buffer_conc_fact', unit: '−', label: 'Buffer concentration factor', desc: 'Uneven distribution along the canister when sulphide enters from a fracture.',
      info: ['Only the intact-buffer rate without spalling uses it.'] },
    { key: 'dSulphide', group: 'diffusive', type: 'number', def: 1e-10, xl: 'DeSulphide/SecpYr', py: 'd_sulphide', unit: 'm²/s', label: 'Sulphide diffusivity in buffer',
      info: ['The diffusivity of sulphide in the buffer, in m²/s here; the workbook’s DeSulphide is in m²/yr, hence DeSulphide/SecpYr. It sets QeqGeo = plug length · DeSulphide, which the rate without spalling uses, the rate with spalling, and the rate limited by buffer diffusion alone, a reference line of the intact-buffer plot.'] },
    { key: 'plugLength', group: 'diffusive', type: 'number', def: 5.5 / 3.1, xl: 'BufferRockInterfacePlugLength', py: '(5.5/3.1)', unit: 'm', label: 'Buffer/rock interface plug length', desc: 'TR-10-50, appendix G.',
      info: ['The equivalent length of a plug for the transport resistance of the buffer/rock interface. QeqGeo = plug length · DeSulphide is the Qeq when only the fracture geometry and diffusion in the buffer limit the transport of sulphide; the rate without spalling uses it. The Python ports write 5.5/3.1 into their formulas.'] },
    { key: 'wZone', group: 'diffusive', type: 'number', def: 0.5, xl: 'WZone', py: 'w_zone', unit: 'm', label: 'Width of spalled zone',
      info: ['The width of the thermally spalled zone. With the length, thickness, porosity and pore diffusivity of the zone it sets the spalling factor √(4/π·Dp·WZone·LZone·εZone/DZone), from which the Qeq of the spalled zone is added to the hydro model’s Qeq. The rate with spalling also uses it directly.'] },
    { key: 'lZone', group: 'diffusive', type: 'number', def: 8, xl: 'LZone', py: 'l_zone', unit: 'm', label: 'Length of spalled zone',
      info: ['The length of the spalled zone, in the spalling factor and directly in the rate with spalling.'] },
    { key: 'dZone', group: 'diffusive', type: 'number', def: 0.1, xl: 'DZone', py: 'd_zone', unit: 'm', label: 'Thickness of spalled zone',
      info: ['The thickness of the spalled zone, in the spalling factor.'] },
    { key: 'epsZone', group: 'diffusive', type: 'number', def: 0.02, xl: 'epsZone', py: 'eps_zone', unit: '−', label: 'Porosity of spalled zone',
      info: ['The porosity of the spalled zone, in the spalling factor.'] },
    { key: 'dP', group: 'diffusive', type: 'number', def: 1e-11, xl: 'Dp/SecpYr', py: 'd_p', unit: 'm²/s', label: 'Pore diffusivity in spalled zone',
      info: ['The pore diffusivity in the spalled zone, in m²/s here; the workbook’s Dp is in m²/yr, hence Dp/SecpYr. It enters the spalling factor.'] },

    // ---- fresh water ------------------------------------------------
    { key: 'dE', group: 'freshwater', type: 'number', def: 1.26e-6, xl: 'De', py: 'd_e', unit: 'm²/yr', label: 'Effective diffusivity De',
      info: ['The effective diffusivity in the matrix-diffusion term of tFreshWater, ((F/cf)/ff)²·De·εp / (4·erfInv²). R-09-20, section F.2.2.'] },
    { key: 'ep', group: 'freshwater', type: 'number', def: 0.0037, xl: 'ep', py: 'ep', unit: '−', label: 'Porosity εp',
      info: ['The porosity in the matrix-diffusion term of tFreshWater, with De. R-09-20, section F.2.2.'] },
    { key: 'erfInv', group: 'freshwater', type: 'number', def: 0.088856, xl: 'erfInv', py: 'erf_inv', unit: '−', label: 'erf⁻¹ term',
      info: ['The inverse error function in the matrix-diffusion term of tFreshWater: 0.088856 = erf⁻¹(0.1), so erfc(0.088856) = 0.9. The term goes as 1/erfInv². R-09-20, section F.2.2.'] },
    { key: 'flowFactor', group: 'freshwater', type: 'number', def: 1, xl: 'FlowFactor', py: 'flow_fact', unit: '−', label: 'Flow factor',
      info: ['A factor on the flow for the dilute-water times: tw and F are both divided by it.'] },
    { key: 'channelingFactor', group: 'freshwater', type: 'number', def: 1, xl: 'ChannelingFactor', py: 'channeling_fact', unit: '−', label: 'Channelling factor',
      info: ['A factor on the transport resistance for the dilute-water times: F alone is divided by it.'] },

    // ---- misc ------------------------------------------------------------
    { key: 'nCanisters', group: 'misc', type: 'number', def: 6000, xl: '(6000)', py: '(6000)', unit: '',
      label: 'Canisters to normalise to', desc: 'The corrected failure counts are scaled by this over the number of accepted holes, so that the answer refers to a repository of this many canisters.',
      info: ['Corrected mean = rows of the failure table / sulphide values × this number / (holes − rejected holes). The workbook and the Python ports write 6000 into their formulas instead of naming it, hence the brackets.'] },
    { key: 'secPerYear', group: 'misc', type: 'number', def: 3600 * 24 * 365, xl: 'SecpYr', py: 'scipy.constants.year', unit: 's', label: 'Seconds per year',
      info: ['A year of 365 days, as in the workbook; scipy.constants.year in the Python port is the same number. Every conversion between seconds and years uses it: the diffusivities given in m²/s, the settling rate of the sedimentation model, and the velocity in the NewKTH and Amphos rates and in the gradient.'] },
  ];

  const PARAM_BY_KEY = Object.fromEntries(PARAMS.map((p) => [p.key, p]));

  /** A fresh parameter object with every default. */
  function defaults() {
    const p = {};
    for (const d of PARAMS) p[d.key] = d.def;
    return p;
  }

  /**
   * Defaults, overridden by whatever is in `given` and known to the
   * catalogue; each value is coerced to its declared type. Unknown keys are
   * listed in `unknown` so a case file from a later version says so.
   */
  function normalise(given) {
    const p = defaults();
    const unknown = [];
    for (const [k, v] of Object.entries(given || {})) {
      const d = PARAM_BY_KEY[k];
      if (!d) { unknown.push(k); continue; }
      if (d.type === 'bool') p[k] = (v === true || v === 'true' || v === 1 || v === '1');
      else if (d.type === 'select') p[k] = d.options.some((o) => o[0] === v) ? v : d.def;
      else {
        const x = typeof v === 'number' ? v : parseFloat(String(v).replace(',', '.'));
        p[k] = Number.isFinite(x) ? (d.type === 'int' ? Math.round(x) : x) : d.def;
      }
    }
    return { params: p, unknown };
  }

  /* ---------------------------------------------------------------------
     Special functions
     --------------------------------------------------------------------- */

  /**
   * The Lambert W function, principal branch, for x >= -1/e.
   *
   * The workbook's LambertW_R (VBA) stops at a residual of 1e-3, "fully
   * sufficient for the intended application"; the Python port uses
   * scipy.special.lambertw. This is the scipy answer: a Winitzki start and
   * Halley's iteration to machine precision.
   */
  function lambertW(x) {
    if (!(x >= -1 / Math.E)) return NaN;
    if (x === 0) return 0;
    let w;
    if (x < -0.3) {
      // Series about the branch point, where log(1 + x) is poor.
      const q = Math.sqrt(2 * (Math.E * x + 1));
      w = -1 + q - q * q / 3 + (11 / 72) * q * q * q;
    } else {
      const l = Math.log(1 + x);
      w = l * (1 - Math.log(1 + l) / (2 + l));
    }
    for (let i = 0; i < 60; i++) {
      const ew = Math.exp(w);
      const f = w * ew - x;
      const wp1 = w + 1;
      // At the branch point w = -1 the derivative vanishes and the start
      // value is already exact; a step there would be 0/0.
      if (f === 0 || Math.abs(wp1) < 1e-12) break;
      const dw = f / (ew * wp1 - ((w + 2) * f) / (2 * wp1));
      w -= dw;
      if (Math.abs(dw) <= 4e-16 * (1 + Math.abs(w))) break;
    }
    return w;
  }

  /**
   * The inverse of the standard normal distribution function: Acklam's
   * rational approximation, relative error below 1.2e-9 over (0, 1). Used
   * to draw quantiles of a lognormal sulphide distribution, where nine
   * digits is far more than the distribution itself is known to. (A Halley
   * refinement was tried and dropped: it needs an erfc accurate to better
   * than 1e-9, and the short rational erfc that was to hand is 1e-7, which
   * made the refined answer worse than the unrefined one -- normInv(0.5)
   * came out as -3.8e-8 instead of 0.)
   */
  function normInv(p) {
    if (!(p > 0 && p < 1)) return p === 0 ? -Infinity : (p === 1 ? Infinity : NaN);
    const a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
      1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00];
    const b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
      6.680131188771972e+01, -1.328068155288572e+01];
    const c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
      -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00];
    const d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
      3.754408661907416e+00];
    const plow = 0.02425;
    let x;
    if (p < plow) {
      const q = Math.sqrt(-2 * Math.log(p));
      x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
        / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
    } else if (p <= 1 - plow) {
      const q = p - 0.5;
      const r = q * q;
      x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
    } else {
      const q = Math.sqrt(-2 * Math.log(1 - p));
      x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
        / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
    }
    return x;
  }

  /* ---------------------------------------------------------------------
     Derived constants: the green cells of sheet "Info"
     --------------------------------------------------------------------- */

  /** Smectite diffusion coefficient at the rim, m²/s, valid 0.1 < c < 4 mM. */
  function dCionRim(cIonMM) {
    const l = Math.log10(cIonMM);
    return Math.pow(10, -9.42911 - 1.5309 * l - 1.88737 * l * l - 0.783596 * l * l * l);
  }

  function derived(p) {
    const year = p.secPerYear;
    const dBuffer = p.rDepHole - p.rCan;
    const vZone = dBuffer * PI * (p.rDepHole * p.rDepHole - p.rCan * p.rCan) / 2;
    const hCorr = p.pessCorrGeo ? p.dCan * PI / 2 : dBuffer;
    const aCorr = PI * p.rCan * hCorr;
    const corrHoleFact = p.dCan * aCorr * p.rhoCu / (p.fHS * p.moMassCu * (p.averageFlow ? p.averageFlowFactor : 1));
    const qLim = Math.pow(1.13 / dBuffer, 2) * p.dWater * vZone;
    const dR = p.effectiveDR
      ? Math.pow(p.fracTemp * Math.sqrt(dCionRim(p.cIonTemp)) + p.fracGlac * Math.sqrt(dCionRim(p.cIonGlac)), 2)
      : dCionRim(p.cIon);
    const alpha = p.alphaDeg * PI / 180;
    const fExp = p.dI * year * (p.phiI - p.phiR) * p.rhoS / (p.jExp * Math.sin(alpha));
    const rRssSed = p.forceRrss ? p.rDepHole + 0.05 : fExp / lambertW(fExp / p.rDepHole);
    const spallingFact = Math.sqrt(4 / PI * p.dP * year * p.wZone * p.lZone * p.epsZone / p.dZone);
    const deSulphide = p.dSulphide * year;             // m²/yr
    const corrosionFactor = p.fixedSulphideConc * p.fHS * p.moMassCu * p.bufferConcFact / (2 * PI * p.rCan * p.hCan * p.rhoCu);
    const qeqGeo = p.plugLength * deSulphide;
    const corrRateBuffOnly = p.fixedSulphideConc * p.fHS * p.moMassCu / p.rhoCu * deSulphide / dBuffer;
    return { year, dBuffer, vZone, hCorr, aCorr, corrHoleFact, qLim, dR, alpha, fExp, rRssSed,
      spallingFact, deSulphide, corrosionFactor, qeqGeo, corrRateBuffOnly };
  }

  /* ---------------------------------------------------------------------
     The calculation: sheet "Calc", one row per deposition hole
     --------------------------------------------------------------------- */

  /** Bits of the rejection reason, in the order the workbook lists them. */
  const REJECT = Object.freeze({ FPC: 1, EFPC: 2, FLEN: 4, TL: 8, DARCY: 16, INFLOW: 32 });
  const REJECT_NAMES = Object.freeze({ 1: 'FPC', 2: 'EFPC', 4: 'fracture length', 8: 'T/L', 16: 'Darcy flux', 32: 'inflow' });

  function rejectReasons(bits) {
    const out = [];
    for (const b of [1, 2, 4, 8, 16, 32]) if (bits & b) out.push(REJECT_NAMES[b]);
    return out;
  }

  /**
   * Sort a sulphide table in descending order, dropping anything that is not
   * a positive finite number. Returns a Float64Array.
   */
  function sortHs(hs) {
    const a = Array.from(hs, Number).filter((x) => Number.isFinite(x) && x > 0);
    a.sort((x, y) => y - x);
    return Float64Array.from(a);
  }

  /** How many entries of a descending array are strictly greater than x. */
  function countAbove(desc, x) {
    let lo = 0;
    let hi = desc.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (desc[mid] > x) lo = mid + 1; else hi = mid;
    }
    return lo;
  }

  /**
   * Evaluate one hydro table (one DFN realisation) against one sulphide
   * distribution with one parameter set.
   *
   * @param {object} hydro   see ec-hydro.js: {n, id[], okflag, u0, qeq, tw, f, trapp, fpc, efpc, flen, inflowReject?, velocityIsDirect?}
   * @param {ArrayLike<number>} hs  sulphide concentrations, mol/L (any order)
   * @param {object} params  a parameter object; missing keys take defaults
   * @returns {object} the per-hole columns, the failure table and the key outputs
   */
  function evaluate(hydro, hs, params) {
    const p = normalise(params).params;
    const k = derived(p);
    const n = hydro.n;
    const year = k.year;
    const hsDesc = sortHs(hs);
    const nHs = hsDesc.length;
    if (nHs === 0) throw new Error('The sulphide distribution has no positive values.');
    const hsMax = hsDesc[0];
    const tLim = p.tFailFilteringLim;

    const F64 = (fill) => { const a = new Float64Array(n); if (fill) a.fill(fill); return a; };
    const get = (name) => hydro[name] || new Float64Array(n);
    const u0 = get('u0'); const trapp = get('trapp'); const flen = get('flen');
    const fpc = get('fpc'); const efpc = get('efpc'); const okflag = get('okflag');
    const qeqHydro = get('qeq'); const tw = get('tw'); const fRes = get('f');
    const inflow = hydro.inflowReject || new Float64Array(n);

    const aperture = F64(); const transmissivity = F64(); const v = F64(); const gradient = F64();
    const qEb = F64(); const qeqEb = F64(); const qeqDz = F64();
    const rErosion = F64(); const nErosion = F64(); const nMaxLoss = F64(); const nMaxSed = F64();
    const nSed = F64(); const aErosion23 = F64(); const aErosion25 = F64(); const lossRate = F64();
    const rRss = F64(); const tAdv = F64(NEVER); const hsMin = F64(NEVER); const tFailMin = F64(NEVER);
    const nHsPoints = new Int32Array(n); const rejectBits = new Uint8Array(n);
    const reject = new Uint8Array(n); const skip = new Uint8Array(n); const edge = new Uint8Array(n);
    const tFresh = F64(NaN);

    // Rates that do not depend on the hole. G/2 of TR-16-11 equation 4-13
    // is Calc!AB: 0.5·Di·π·(φi − φR)/(2·φR·sqrt(DR·r·v)); the 0.5 is easy to
    // lose and losing it puts rRSS 2.4 times too far out.
    const gOver2Const = 0.5 * p.dI * PI * (p.phiI - p.phiR) / (2 * p.phiR);   // × 1/sqrt(dR·r·v/yr)
    const eroConst = p.rhoS * p.phiR * 4;                               // × δ·sqrt(dR·rRSS·v/yr)·yr
    const sedGeom = (k.rhoAggMinus = (p.rhoAgg - p.rhoW) * p.g * p.phiR * p.rhoS * 2 * k.rRssSed * year) / (12 * p.muAgg);
    const lossGeom = p.jExp * 2 * PI * k.rRssSed * Math.sin(k.alpha);
    const a25 = (c) => 7.03e3 / 1000 * (2 * p.rDepHole) * Math.pow(c, -0.7);

    for (let i = 0; i < n; i++) {
      // Fracture geometry and flow.
      const d0 = trapp[i];
      const d = p.pessAperture ? 0.275 * Math.pow(d0 / 0.5, 2 * 0.297) : d0;
      aperture[i] = d;
      transmissivity[i] = p.transmissivityLaw === 'Cubic'
        ? Math.pow(d0 / p.cubicRefAperture, 3) : Math.pow(d0 / 0.5, 2);
      // v: the fracture velocity in m/yr. Zero where there is no aperture,
      // i.e. no fracture crossing the hole. A DarcyTools table carries the
      // velocity itself (Utot) in the U0 column.
      const vi = d0 > 0 ? (hydro.velocityIsDirect ? u0[i] : u0[i] * p.w / d) : 0;
      v[i] = vi;
      gradient[i] = vi > 0 ? vi * d / (transmissivity[i] * year) : 0;
      // Flow through the eroded hole and Qeq for it. v·δ = U0·w when the
      // aperture is the transport aperture; with the pessimistic aperture
      // the workbook still uses U0·w (column U), and v·δ reproduces that.
      const q = p.flowConcFact * vi * d * 2 * p.rDepHole;
      qEb[i] = q;
      qeqEb[i] = q > 0 ? Math.min(1.13 * Math.sqrt(q * p.dWater * k.vZone) / k.dBuffer, q) : 0;
      qeqDz[i] = k.spallingFact * Math.sqrt(vi * d * Math.min(2 * 8, flen[i]));

      // Rejection.
      let bits = 0;
      if (p.fpcFiltering && fpc[i] > 0) bits |= REJECT.FPC;
      if (p.efpcFiltering && efpc[i] > p.efpcNumber - 1) bits |= REJECT.EFPC;
      if (p.fracLenFiltering && flen[i] > p.fracLenFilteringLim) bits |= REJECT.FLEN;
      if (p.transFiltering && transmissivity[i] > p.transFilteringLim && flen[i] > p.minFlenT) bits |= REJECT.TL;
      if (p.highDarcyFiltering && u0[i] > p.darcyFilterLim) bits |= REJECT.DARCY;
      if (p.highFlowFiltering && inflow[i] > 0) bits |= REJECT.INFLOW;
      rejectBits[i] = bits;
      reject[i] = bits ? 1 : 0;

      // Buffer loss rates, every model, so the plots can show any of them.
      if (vi > 0) {
        const vs = vi / year;                                   // m/s
        rErosion[i] = p.advConst * Math.pow(vi, 0.41) * d;
        const g2 = gOver2Const / Math.sqrt(k.dR * p.rDepHole * vs);
        const rr = p.forceRrss ? p.rDepHole + 0.05 : p.rDepHole * Math.pow(g2 / lambertW(g2), 2);
        rRss[i] = rr;
        nErosion[i] = eroConst * d * Math.sqrt(k.dR * rr * vs) * year;
        aErosion23[i] = 1.993e13 / 1000 * Math.pow(vs, 1.0484) * Math.pow(d, 2.0156);
        if (d > 0) {
          const dmm = d * 1000;
          aErosion25[i] = Math.sqrt(vs) * Math.pow(dmm, 1.2)
            * (p.fracTemp * a25(p.cIonTemp) + p.fracGlac * a25(p.cIonGlac));
        }
      }
      // The sedimentation rate needs only the aperture (workbook AF-AH).
      nMaxLoss[i] = lossGeom * d;
      nMaxSed[i] = d * d * d * sedGeom;
      nSed[i] = Math.min(nMaxLoss[i], nMaxSed[i]);

      switch (p.buffModel) {
        case 'OldKTH': lossRate[i] = rErosion[i]; break;
        case 'NewKTH': lossRate[i] = nErosion[i]; break;
        case 'Sediment': lossRate[i] = nSed[i]; break;
        case 'Ero+Sed': lossRate[i] = nErosion[i] + nSed[i]; break;
        case 'Amphos2023': lossRate[i] = aErosion23[i]; break;
        case 'Amphos2025': lossRate[i] = aErosion25[i]; break;
        default: lossRate[i] = 0;
      }

      // Time to advective conditions.
      if (!reject[i] && vi > 0) {
        if (p.initialAdvection) tAdv[i] = 0;
        else if (lossRate[i] > 0) tAdv[i] = p.mBuffAdv / (lossRate[i] * p.fTDilute);
        else tAdv[i] = NEVER;
      }

      // The least sulphide that fails the canister inside the assessment
      // time, and the failure time at the highest sulphide in the table.
      if (q > 0 && tAdv[i] < NEVER && tAdv[i] <= tLim && tLim > tAdv[i]) {
        hsMin[i] = (k.corrHoleFact / qeqEb[i]) / (tLim - tAdv[i]);
        tFailMin[i] = tAdv[i] + (tLim - tAdv[i]) * hsMin[i] / hsMax;
        nHsPoints[i] = countAbove(hsDesc, hsMin[i]);
      }
    }

    // EFPC edge positions: partially intersected by the large fracture that
    // rejects the hole two rows away, but not rejected itself. Information
    // only; the workbook reports whether any failed canister sits in one.
    for (let i = 0; i < n; i++) {
      const same = (j) => efpc[i] < p.efpcNumber && efpc[j] > p.efpcNumber - 1
        && flen[j] === flen[i] && trapp[j] === trapp[i];
      edge[i] = ((i + 2 < n && same(i + 2)) || (i >= 2 && same(i - 2))) ? 1 : 0;
    }

    // Skipped: rejected, cannot fail in time, or not reaching the surface.
    let nReject = 0;
    let nSkip = 0;
    for (let i = 0; i < n; i++) {
      skip[i] = (reject[i] || (p.tFailFiltering && tFailMin[i] > tLim) || (p.okFlagFiltering && okflag[i] > 0)) ? 1 : 0;
      nReject += reject[i];
      nSkip += skip[i];
      if (!skip[i]) {
        tFresh[i] = tw[i] / p.flowFactor
          + Math.pow((fRes[i] / p.channelingFactor) / p.flowFactor, 2) * p.dE * p.ep / (p.erfInv * p.erfInv) / 4;
      }
    }

    // The table of failure times: one row per (hole, sulphide value) pair
    // that fails inside the assessment time. Rows in hole order, then in
    // descending sulphide, as the workbook and the Python port produce them.
    const failures = [];
    let nFailedHighestHs = 0;
    let anyEdge = false;
    for (let i = 0; i < n; i++) {
      if (skip[i]) continue;
      const m = nHsPoints[i];
      if (m > 0) nFailedHighestHs++;
      for (let j = 0; j < m; j++) {
        const tCorr = k.corrHoleFact / (qeqEb[i] * hsDesc[j]);
        failures.push({
          hole: i, id: hydro.id ? hydro.id[i] : i + 1, hsIndex: j + 1, hs: hsDesc[j],
          tAdv: tAdv[i], tCorr, tFail: tAdv[i] + tCorr,
          f: fRes[i], tw: tw[i], q: qEb[i], edge: !!edge[i],
        });
        if (edge[i]) anyEdge = true;
      }
    }

    // Key outputs: sheet "Info", rows 27-38.
    const nAccepted = n - nReject;
    const corr = nAccepted > 0 ? p.nCanisters / nAccepted : NaN;
    let nAdvLim = 0; let nAdv1e5 = 0; let earliestAdv = NEVER;
    for (let i = 0; i < n; i++) {
      if (tAdv[i] < tLim) nAdvLim++;
      if (tAdv[i] < 1e5) nAdv1e5++;
      if (tAdv[i] < earliestAdv) earliestAdv = tAdv[i];
    }
    let n1e5 = 0; let earliestFail = NEVER;
    for (const r of failures) {
      if (r.tFail <= 1e5) n1e5++;
      if (r.tFail < earliestFail) earliestFail = r.tFail;
    }
    let sumPoints = 0;
    for (let i = 0; i < n; i++) if (!skip[i]) sumPoints += nHsPoints[i];

    const key = {
      nTot: n,
      nReject,
      nSkip,
      nAccepted,
      nHs,
      hsMax,
      hsMean: hsDesc.reduce((s, x) => s + x, 0) / nHs,
      nFailRows: failures.length,
      meanFailed: failures.length / nHs,
      meanFailedCorrected: failures.length / nHs * corr,
      nFailedHighestHs,
      meanFailed1e5Corrected: n1e5 / nHs * corr,
      earliestFailure: earliestFail < NEVER ? earliestFail : null,
      nAdvAtLim: nAdvLim,
      nAdv1e5,
      earliestAdvection: earliestAdv < NEVER ? earliestAdv : null,
      anyEdge,
      checkSum: failures.length - sumPoints,
      qLim: k.qLim,
      corrHoleFact: k.corrHoleFact,
      tLim,
    };

    return {
      params: p, derived: k, hs: hsDesc, n,
      id: hydro.id || Array.from({ length: n }, (_, i) => i + 1),
      columns: { u0, trapp, flen, fpc, efpc, okflag, qeqHydro, tw, f: fRes, aperture, transmissivity, v, gradient,
        qEb, qeqEb, qeqDz, rErosion, nErosion, nMaxLoss, nMaxSed, nSed, aErosion23, aErosion25, lossRate, rRss,
        tAdv, hsMin, tFailMin, nHsPoints, rejectBits, reject, skip, edge, tFresh },
      failures, key,
    };
  }

  /* ---------------------------------------------------------------------
     Several realisations at once
     --------------------------------------------------------------------- */

  const STAT_KEYS = ['nReject', 'earliestAdvection', 'nAdv1e5', 'nAdvAtLim', 'earliestFailure',
    'meanFailed1e5Corrected', 'meanFailedCorrected', 'meanFailed', 'nFailedHighestHs', 'nFailRows'];

  function stats(values) {
    const xs = values.filter((x) => Number.isFinite(x));
    if (!xs.length) return { min: null, mean: null, max: null, n: 0 };
    return { min: Math.min(...xs), max: Math.max(...xs), mean: xs.reduce((s, x) => s + x, 0) / xs.length, n: xs.length };
  }

  /**
   * Evaluate every realisation and pool the failure tables, the way the
   * Python port accumulates calc() over r1..r12 with reset=False: a DFN
   * column says which realisation a row came from, and the corrected mean
   * over realisations is the mean of the per-realisation values.
   */
  function evaluateMany(realisations, hs, params) {
    const results = realisations.map((h) => evaluate(h, hs, params));
    const table = [];
    results.forEach((r, ri) => {
      for (const row of r.failures) table.push({ index: table.length + 1, dfn: ri + 1, realisation: realisations[ri].name, ...row });
    });
    const summary = {};
    for (const key of STAT_KEYS) summary[key] = stats(results.map((r) => r.key[key]));
    summary.nFailedHighestHsTotal = results.reduce((s, r) => s + r.key.nFailedHighestHs, 0);
    summary.nRealisations = results.length;
    summary.nFailRowsTotal = table.length;
    return { results, table, summary };
  }

  /* ---------------------------------------------------------------------
     Series for the plots: the sheets QeqPlt, CorrDiffPlt, EroPlt,
     CorrAdvPlt, iPlt and the aperture plot of the Python port
     --------------------------------------------------------------------- */

  /**
   * An empirical distribution over the deposition holes. The workbook takes
   * percentiles 1..100 % of the whole column and blanks the zeros; here the
   * sorted values are used directly, with y the fraction of ALL holes at or
   * below x, so the curve starts at the share of holes that are zero -- the
   * same picture without interpolation. Thinned to at most `maxPoints`.
   */
  function ecdf(values, maxPoints = 600) {
    const n = values.length;
    const sorted = Float64Array.from(values).sort();
    let first = 0;
    while (first < n && !(sorted[first] > 0)) first++;
    const m = n - first;
    const x = []; const y = [];
    if (m === 0) return { x, y, zeroFraction: 1 };
    const step = Math.max(1, Math.floor(m / maxPoints));
    for (let j = first; j < n; j += step) { x.push(sorted[j]); y.push((j + 1) / n); }
    if ((n - 1 - first) % step !== 0) { x.push(sorted[n - 1]); y.push(1); }
    return { x, y, zeroFraction: first / n };
  }

  /** `values` with rejected holes set to zero, and holes in deformation zones (FPC = 2) too. */
  function masked(values, res, alsoRejected) {
    const out = Float64Array.from(values);
    const { fpc, reject } = res.columns;
    for (let i = 0; i < out.length; i++) {
      if (fpc[i] === 2 || (alsoRejected && reject[i])) out[i] = 0;
    }
    return out;
  }

  /**
   * The six distributions, each as named series over the holes plus the
   * reference lines the workbook draws on them. Values are in the units of
   * the plots: µm/yr for corrosion rates.
   */
  function distributions(res) {
    const p = res.params;
    const k = res.derived;
    const c = res.columns;
    const n = res.n;
    const year = k.year;

    // Qeq from the hydro model, with and without the spalled-zone addition.
    const qeqWith = new Float64Array(n);
    const qeqWithout = new Float64Array(n);
    for (let i = 0; i < n; i++) { qeqWithout[i] = c.qeqHydro[i]; qeqWith[i] = c.qeqHydro[i] + c.qeqDz[i]; }

    // Corrosion through an intact buffer, µm/yr, at the fixed sulphide.
    const diffWith = new Float64Array(n);
    const diffWithout = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      const qs = qeqWith[i];
      if (qs > 0) {
        diffWith[i] = 1e6 * p.fixedSulphideConc * p.fHS * p.moMassCu
          / (p.rhoCu * p.wZone * p.lZone * (1 / qs + k.dBuffer / (k.deSulphide * p.wZone * p.lZone)));
      }
      if (c.qeqHydro[i] > 0) diffWithout[i] = 1e6 * k.corrosionFactor / (1 / c.qeqHydro[i] + 1 / k.qeqGeo);
    }

    // Corrosion through an eroded buffer, µm/yr, at the fixed sulphide.
    const adv = new Float64Array(n);
    for (let i = 0; i < n; i++) adv[i] = 1e6 * p.fixedSulphideConc * p.dCan / k.corrHoleFact * c.qeqEb[i];

    const lossLabel = { OldKTH: 'Erosion rate, SR-Site model', NewKTH: 'Erosion rate, TR-16-11', Sediment: 'Sedimentation rate, TR-16-11',
      'Ero+Sed': 'Erosion + sedimentation, TR-16-11', Amphos2023: 'Erosion rate, P-23-03', Amphos2025: 'Erosion rate, P-25-05' }[p.buffModel] || 'Buffer loss rate';

    const pair = (values, name) => [
      { name: `${name}, all deposition holes`, values: masked(values, res, false) },
      { name: `${name}, after rejection`, values: masked(values, res, true) },
    ];

    return {
      qeq: {
        title: 'Equivalent flow rate from the hydro model', xLabel: 'Qeq (m³/yr)',
        series: [...pair(qeqWith, 'With spalling'), ...pair(qeqWithout, 'Without spalling')],
        lines: [{ label: `qlim = ${k.qLim.toPrecision(3)} m³/yr (Qeq becomes √q above it)`, x: k.qLim }],
      },
      corrDiff: {
        title: `Corrosion rate, intact buffer, [HS⁻] = ${(1000 * p.fixedSulphideConc).toPrecision(3)} mM`, xLabel: 'Copper corrosion rate (µm/yr)',
        series: [...pair(diffWith, 'With spalling'), ...pair(diffWithout, 'Without spalling')],
        lines: [
          { label: 'Rate limited by buffer diffusion only', x: 1e6 * k.corrRateBuffOnly },
          { label: `${(100 * p.dCan).toPrecision(3)} cm in 1,000,000 years`, x: 1e6 * p.dCan / 1e6, dash: 'dash' },
        ],
      },
      erosion: {
        title: lossLabel, xLabel: 'Buffer loss rate (kg/yr)',
        series: pair(c.lossRate, lossLabel),
        lines: [
          { label: `${p.mBuffAdv} kg in ${p.tFailFilteringLim.toLocaleString('en')} years`, x: p.mBuffAdv / p.tFailFilteringLim, dash: 'dash' },
          { label: `${p.mBuffAdv} kg in ${Math.round(100 * p.fTDilute)} % of ${p.tFailFilteringLim.toLocaleString('en')} years`, x: p.mBuffAdv / p.tFailFilteringLim / p.fTDilute },
        ],
      },
      corrAdv: {
        title: `Corrosion rate, eroded buffer, [HS⁻] = ${(1000 * p.fixedSulphideConc).toPrecision(3)} mM`, xLabel: 'Copper corrosion rate (µm/yr)',
        series: pair(adv, 'Advective conditions'),
        lines: [
          { label: `${(100 * p.dCan).toPrecision(3)} cm in 1,000,000 years`, x: 1e6 * p.dCan / 1e6, dash: 'dash' },
          { label: `${(100 * p.dCan).toPrecision(3)} cm in 100,000 years`, x: 1e6 * p.dCan / 1e5 },
        ],
      },
      gradient: {
        title: 'Hydraulic gradient in the intersecting fracture', xLabel: 'i (m/m)',
        series: pair(c.gradient, 'Gradient'), lines: [],
      },
      aperture: {
        title: 'Transport aperture of the intersecting fracture', xLabel: 'δ (m)',
        series: pair(c.trapp, 'Aperture'), lines: [],
      },
      tAdv: {
        title: 'Time to advective conditions', xLabel: 'tAdv (years)',
        series: [{ name: 'Accepted holes with a flowing fracture', values: Float64Array.from(c.tAdv, (t) => (t < NEVER ? t : 0)) }],
        lines: [{ label: `${p.tFailFilteringLim.toLocaleString('en')} years`, x: p.tFailFilteringLim, dash: 'dash' }],
      },
      velocity: {
        title: 'Water velocity in the intersecting fracture', xLabel: 'v (m/yr)',
        series: pair(c.v, 'Velocity'), lines: [],
      },
      _year: year,
    };
  }

  /**
   * Counts against time: advective positions and the corrected mean number
   * of failed canisters, on a log-spaced grid. Averaged over realisations.
   */
  function timeHistory(results, nPoints = 121, tMin = 100) {
    const tMax = Math.max(...results.map((r) => r.key.tLim));
    const t = [];
    for (let i = 0; i < nPoints; i++) t.push(tMin * Math.pow(tMax / tMin, i / (nPoints - 1)));
    const nAdv = new Float64Array(nPoints);
    const nFail = new Float64Array(nPoints);
    const nFailHi = new Float64Array(nPoints);
    for (const r of results) {
      const corr = r.params.nCanisters / r.key.nAccepted / r.key.nHs;
      const adv = Float64Array.from(r.columns.tAdv).sort();
      const fails = Float64Array.from(r.failures, (x) => x.tFail).sort();
      // The failure time of every accepted hole at the highest sulphide.
      const hi = [];
      for (let i = 0; i < r.n; i++) {
        if (r.columns.skip[i] || !(r.columns.qeqEb[i] > 0) || !(r.columns.tAdv[i] < NEVER)) continue;
        hi.push(r.columns.tAdv[i] + r.key.corrHoleFact / (r.columns.qeqEb[i] * r.key.hsMax));
      }
      hi.sort((a, b) => a - b);
      const below = (sorted, x) => { let lo = 0; let hiI = sorted.length; while (lo < hiI) { const m = (lo + hiI) >> 1; if (sorted[m] < x) lo = m + 1; else hiI = m; } return lo; };
      for (let i = 0; i < nPoints; i++) {
        nAdv[i] += below(adv, t[i]) / results.length;
        nFail[i] += below(fails, t[i]) * corr / results.length;
        nFailHi[i] += below(hi, t[i]) / results.length;
      }
    }
    return { t, nAdv: Array.from(nAdv), nFail: Array.from(nFail), nFailHighestHs: Array.from(nFailHi) };
  }

  /**
   * Remaining copper thickness at time t in every accepted hole, for one
   * sulphide concentration: d = dCan·clamp(1 − (t − tAdv)/tCorr, 0, 1).
   * The Python port's remaining_d_can, for one column of its matrix.
   */
  function remainingThickness(res, t, hsValue) {
    const { tAdv, qeqEb, reject } = res.columns;
    const p = res.params;
    const out = [];
    for (let i = 0; i < res.n; i++) {
      if (reject[i]) continue;
      let d = p.dCan;
      if (qeqEb[i] > 0 && tAdv[i] < NEVER) {
        const tCorr = res.key.corrHoleFact / (qeqEb[i] * hsValue);
        d = p.dCan * Math.max(0, Math.min(1, 1 - (t - tAdv[i]) / tCorr));
      }
      out.push(d);
    }
    return Float64Array.from(out);
  }

  return {
    NEVER, GROUPS, PARAMS, PARAM_BY_KEY, REJECT, REJECT_NAMES, STAT_KEYS,
    defaults, normalise, derived, dCionRim, lambertW, normInv,
    sortHs, countAbove, rejectReasons,
    evaluate, evaluateMany, stats, ecdf, distributions, timeHistory, remainingThickness,
  };
}));
