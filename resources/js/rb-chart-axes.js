/* ==========================================================================
   RB CHART - line styles, axis scale controls, axes lock, unit prefixes
   --------------------------------------------------------------------------
   Split out of rb-chart.js, which had grown past 3 600 lines. These are plain
   scripts sharing globals, not ES modules, so the load order in rb.html is the
   order this code was in before the split, and has to stay that way:

     rb-chart-axes.js  ->  rb-chart-presets.js  ->  rb-chart-export.js
     ->  rb-chart-toggles.js  ->  rb-chart.js

   Nothing here runs at load time; the files hold declarations only. Functions
   call across files freely, since every call happens after all five have
   loaded.
   ========================================================================== */

'use strict';   // see the script manifest in rb.html for why
/* ==========================================================================
   7. RADIONUCLIDE LINE STYLES
   ========================================================================== */

/**
 * Get the line style (color, dash pattern, width) for a line by its name:
 * a radionuclide, a repository, a pathway or an exposed group.
 * 
 * Predefined styles are provided for common isotopes in categories:
 * - Actinides (Ac, Am, Cm, Np, Pa, Pu, Th, U)
 * - Fission products (Ag, Cs, I, Pd, Se, Sm, Sn, Sr, Tc, Zr)
 * - Activation products (Be, C, Cl, Co, H, Ni, Nb, Mo)
 * - Other radionuclides (various)
 * and for the members of the other index lists results files have:
 * Repositories, Pathways and Exposed groups.
 * 
 * Colors are chosen for visual distinction on both light backgrounds
 * and when multiple isotopes are plotted together.
 * 
 * @param {string} name - Isotope name (e.g., 'U-238', 'Cs-137', 'C-14-org')
 * @returns {{color: string|null, dash: string, width: number}} Line style object
 * 
 * @example
 * getLineStyle('U-238')  // { color: 'rgb(255,0,0)', dash: 'solid', width: 2 }
 * getLineStyle('unknown') // { color: null, dash: 'solid', width: 2 }
 */
const NAMED_LINE_STYLES = {
  // Actinides
  'Ac-227': { color: 'rgb(128,0,0)', dash: 'solid' },
  'Am-241': { color: 'rgb(72,209,204)', dash: 'dashdot' },
  'Am-242m': { color: 'rgb(72,209,204)', dash: 'dash' },
  'Am-243': { color: 'rgb(72,209,204)', dash: 'solid' },
  'Cm-242': { color: 'rgb(175,238,238)', dash: 'dash' },
  'Cm-243': { color: 'rgb(175,238,238)', dash: 'solid' },
  'Cm-244': { color: 'rgb(175,238,238)', dash: 'dot' },
  'Cm-245': { color: 'rgb(175,238,238)', dash: 'dash' },
  'Cm-246': { color: 'rgb(175,238,238)', dash: 'dashdot' },
  'Np-237': { color: 'rgb(218,165,32)', dash: 'solid' },
  'Pa-231': { color: 'rgb(85,107,47)', dash: 'solid' },
  'Pu-238': { color: 'rgb(0,255,255)', dash: 'dot' },
  'Pu-239': { color: 'rgb(0,255,255)', dash: 'solid' },
  'Pu-240': { color: 'rgb(0,255,255)', dash: 'dash' },
  'Pu-241': { color: 'rgb(0,255,255)', dash: 'dashdot' },
  'Pu-242': { color: 'rgb(0,255,255)', dash: 'dash' },
  'Th-228': { color: 'rgb(75,0,130)', dash: 'dash' },
  'Th-229': { color: 'rgb(75,0,130)', dash: 'dot' },
  'Th-230': { color: 'rgb(75,0,130)', dash: 'solid' },
  'Th-232': { color: 'rgb(75,0,130)', dash: 'dash' },
  'U-232': { color: 'rgb(255,0,0)', dash: 'longdash' },
  'U-233': { color: 'rgb(255,0,0)', dash: 'dash' },
  'U-234': { color: 'rgb(255,0,0)', dash: 'dot' },
  'U-235': { color: 'rgb(255,0,0)', dash: 'dash' },
  'U-236': { color: 'rgb(255,0,0)', dash: 'dashdot' },
  'U-238': { color: 'rgb(255,0,0)', dash: 'solid' },

  // Fission products
  'Ag-108m': { color: 'rgb(128,128,0)', dash: 'solid' },
  'Cs-135': { color: 'rgb(0,128,0)', dash: 'solid' },
  'Cs-137': { color: 'rgb(0,128,0)', dash: 'dash' },
  'I-129': { color: 'rgb(30,144,255)', dash: 'solid' },
  'Pd-107': { color: 'rgb(216,191,216)', dash: 'solid' },
  'Se-79': { color: 'rgb(112,128,144)', dash: 'solid' },
  'Sm-151': { color: 'rgb(138,43,226)', dash: 'solid' },
  'Sn-126': { color: 'rgb(0,0,0)', dash: 'solid' },
  'Sr-90': { color: 'rgb(255,215,0)', dash: 'solid' },
  'Tc-99': { color: 'rgb(0,0,128)', dash: 'solid' },
  'Zr-93': { color: 'rgb(144,238,144)', dash: 'solid' },

  // Activation products
  'Be-10': { color: 'rgb(65,105,225)', dash: 'solid' },
  'C-14': { color: 'rgb(0,0,255)', dash: 'solid' },
  'C-14-org': { color: 'rgb(0,0,255)', dash: 'solid' },
  'C-14-ind': { color: 'rgb(0,0,255)', dash: 'dash' },
  'C-14-inorg': { color: 'rgb(0,0,255)', dash: 'dot' },
  'Cl-36': { color: 'rgb(210,105,30)', dash: 'solid' },
  'Co-60': { color: 'rgb(0,255,127)', dash: 'solid' },
  'H-3': { color: 'rgb(0,0,205)', dash: 'solid' },
  'Ni-59': { color: 'rgb(255,0,255)', dash: 'solid' },
  'Ni-63': { color: 'rgb(255,0,255)', dash: 'dash' },
  'Nb-93m': { color: 'rgb(210,180,140)', dash: 'solid' },
  'Nb-94': { color: 'rgb(210,180,140)', dash: 'dash' },
  'Mo-93': { color: 'rgb(0,255,0)', dash: 'solid' },

  // Other radionuclides
  'Ar-39': { color: 'rgb(152,251,152)', dash: 'solid' },
  'Ba-133': { color: 'rgb(70,130,180)', dash: 'solid' },
  'Ca-41': { color: 'rgb(128,0,128)', dash: 'solid' },
  'Cd-113m': { color: 'rgb(124,252,0)', dash: 'solid' },
  'Eu-150': { color: 'rgb(205,133,63)', dash: 'dash' },
  'Eu-152': { color: 'rgb(205,133,63)', dash: 'solid' },
  'Gd-148': { color: 'rgb(255,255,0)', dash: 'solid' },
  'Ho-166m': { color: 'rgb(100,149,237)', dash: 'solid' },
  'K-40': { color: 'rgb(139,69,19)', dash: 'solid' },
  'La-137': { color: 'rgb(255,248,220)', dash: 'solid' },
  'Pb-210': { color: 'rgb(148,0,211)', dash: 'dash' },
  'Po-210': { color: 'rgb(148,0,211)', dash: 'dot' },
  'Rn-222': { color: 'rgb(148,0,211)', dash: 'dashdot' },
  'Ra-226': { color: 'rgb(148,0,211)', dash: 'solid' },
  'Ra-228': { color: 'rgb(148,0,211)', dash: 'dash' },
  'Re-186m': { color: 'rgb(255,160,122)', dash: 'solid' },
  'Si-32': { color: 'rgb(255,228,181)', dash: 'solid' },
  'Tb-157': { color: 'rgb(221,160,221)', dash: 'solid' },
  'Tb-158': { color: 'rgb(221,160,221)', dash: 'dash' },
  'Ti-44': { color: 'rgb(218,112,214)', dash: 'solid' },

  // Repositories
  'Silo': { color: 'rgb(255,204,0)', dash: 'solid' },
  'BMA': { color: 'rgb(153,204,51)', dash: 'solid' },
  '1BMA': { color: 'rgb(153,204,51)', dash: 'solid' },
  '2BMA': { color: 'rgb(153,204,51)', dash: 'dash' },
  'BLA': { color: 'rgb(204,102,255)', dash: 'solid' },
  '1BLA': { color: 'rgb(204,102,255)', dash: 'solid' },
  '2-5BLA': { color: 'rgb(204,102,255)', dash: 'dash' },
  '2BLA': { color: 'rgb(204,102,255)', dash: 'dash' },
  '3BLA': { color: 'rgb(204,102,255)', dash: 'dot' },
  '4BLA': { color: 'rgb(204,102,255)', dash: 'dashdot' },
  '5BLA': { color: 'rgb(204,102,255)', dash: 'longdash' },
  'BTF': { color: 'rgb(102,153,204)', dash: 'solid' },
  '1BTF': { color: 'rgb(102,153,204)', dash: 'solid' },
  '2BTF': { color: 'rgb(102,153,204)', dash: 'dash' },
  'BRT': { color: 'rgb(192,80,77)', dash: 'solid' },

  // Pathways: the hues of the PSAR pathway dose charts, where each is the
  // pale fill of a stacked area. As lines they are made strong enough to
  // show on white and on the dark theme, and far enough apart to tell every
  // ingestion pathway from the others; the charts' own colour is in the
  // comment. External and Inhalation keep theirs, lighter than the rest.
  'ext': { color: 'rgb(255,211,158)', dash: 'solid' },         // External; as in the charts
  'inh': { color: 'rgb(180,216,229)', dash: 'solid' },         // Inhalation; charts #C8F0FF
  'ing_water': { color: 'rgb(0,169,212)', dash: 'solid' },     // Water; charts #64FFFF
  'ing_meat': { color: 'rgb(224,48,46)', dash: 'solid' },      // Meat; charts #FFB4B4
  'ing_milk': { color: 'rgb(154,154,154)', dash: 'solid' },    // Milk; charts #FAFAFA
  'ing_tuber': { color: 'rgb(142,90,42)', dash: 'solid' },     // Tuber; charts #E2C5A8
  'ing_root': { color: 'rgb(142,90,42)', dash: 'dash' },       // not in the charts: Tuber's, dashed
  'ing_cereal': { color: 'rgb(232,196,0)', dash: 'solid' },    // Cereal; charts #FFFFC8
  'ing_veg': { color: 'rgb(58,158,58)', dash: 'solid' },       // Vegetable; charts #C8FFC8
  'ing_berry': { color: 'rgb(224,64,160)', dash: 'solid' },    // Berry; charts #FF96FF
  'ing_game': { color: 'rgb(255,140,26)', dash: 'solid' },     // Game; charts #FF9600
  'ing_mush': { color: 'rgb(140,132,36)', dash: 'solid' },     // Mushroom; charts #C87800
  'ing_cray': { color: 'rgb(138,92,240)', dash: 'solid' },     // Crayfish; charts #9664FF
  'ing_fish': { color: 'rgb(42,112,216)', dash: 'solid' },     // Fish; the charts have a blue a lake, #5A87E6 the first

  // Exposed groups: the colours of the PSAR dose charts, where the drilled
  // well is the garden plot's line drawn a little thicker.
  'drained_mire': { color: 'rgb(165,42,42)', dash: 'solid' },
  'forager': { color: 'rgb(147,197,114)', dash: 'solid' },
  'garden_plot': { color: 'rgb(0,191,255)', dash: 'solid' },
  'infield_outland': { color: 'rgb(255,204,0)', dash: 'solid' },
  'drilled_well': { color: 'rgb(0,191,255)', dash: 'solid', width: 3 },
  'drained_mire_irrig': { color: 'rgb(165,42,42)', dash: 'dash' },

  // No color
  'none': { color: 'rgba(255,255,255,0)', dash: 'solid' },

  // Climate domains
  'submerged': { color: 'rgb(0,191,255)', dash: 'solid' },
  'temperate': { color: 'rgb(34,139,34)', dash: 'solid' },
  'permafrost': { color: 'rgb(70,130,180)', dash: 'solid' },
  'periglacial': { color: 'rgb(70,130,180)', dash: 'solid' },
  'glacial': { color: 'rgb(255,250,250)', dash: 'solid' },
  'glacial thawed': { color: 'rgb(224, 234, 239)', dash: 'solid' },

  // Chemical degradation states
  'State I': { color: 'rgb(79,99,39)', dash: 'solid' },
  'State II': { color: 'rgb(119,147,60)', dash: 'solid' },
  'State IIIa': { color: 'rgb(154,187,89)', dash: 'solid' },
  'State IIIb': { color: 'rgb(195,215,156)', dash: 'solid' },
  'State IV': { color: 'rgb(255,255,255)', dash: 'solid' },
  // physical degradation states
  'Intact': { color: 'rgb(54,95,146)', dash: 'solid' },
  'Moderately degraded': { color: 'rgb(149,179,216)', dash: 'solid' },
  'Severely degraded': { color: 'rgb(185,205,229)', dash: 'solid' },
  'Completely degraded': { color: 'rgb(220,230,242)', dash: 'solid' },
  'No barrier': { color: 'rgb(255,255,255)', dash: 'solid' },
  
  // Total line has black color
  'Total': { color: 'rgb(0,0,0)', dash: 'solid' },
};

function getNamedColor(name) {
  if (!name) return null;
  const style = NAMED_LINE_STYLES[name] || NAMED_LINE_STYLES[name.toLowerCase()];
  return style && style.color ? style.color : null;
}

function getLineStyle(name) {
  const defaultStyle = { color: null, dash: 'solid', width: 2 };
  if (name in NAMED_LINE_STYLES) {
    return { ...defaultStyle, ...NAMED_LINE_STYLES[name] };
  }
  const lower = name && name.toLowerCase();
  if (lower && lower in NAMED_LINE_STYLES) {
    return { ...defaultStyle, ...NAMED_LINE_STYLES[lower] };
  }
  return defaultStyle;
}


/* ==========================================================================
   8. CHART CONTROLS
   ========================================================================== */

/**
 * Update the chart axis scales based on dropdown selections.
 * Applies new scale types (linear/log) without rebuilding the entire chart.
 * 
 * @returns {void}
 */
function updateChartScales() {
  if (!currentChartData) return;

  const plotDiv = document.getElementById('plotlyChart');
  const curX = (plotDiv && plotDiv.layout && plotDiv.layout.xaxis && plotDiv.layout.xaxis.type) || 'linear';
  const curY = (plotDiv && plotDiv.layout && plotDiv.layout.yaxis && plotDiv.layout.yaxis.type) || 'linear';

  const xScale = getScaleValue('x');
  const yScale = getScaleValue('y');

  const update = {};
  if (xScale !== curX) {
    update['xaxis.type'] = xScale;
    const bgShapes = backgroundShapesForXScale(plotDiv, xScale);
    if (bgShapes) update.shapes = bgShapes;
    if (xScale === 'log') {
      update['xaxis.dtick'] = 1;
      update['xaxis.minor.ticks'] = 'outside';
      update['xaxis.minor.ticklen'] = 3;
      update['xaxis.minor.showgrid'] = true;
    } else {
      update['xaxis.tickmode'] = 'auto';
      update['xaxis.dtick'] = null;
      update['xaxis.minor.ticks'] = 'outside';
      update['xaxis.minor.showgrid'] = false;
    }
  }
  if (yScale !== curY) {
    update['yaxis.type'] = yScale;
    // An axis on auto range stays on it in the other scale, rather than
    // keeping the log range converted to linear limits.
    if (isAutoLogY(plotDiv)) update['yaxis.autorange'] = true;
    if (yScale === 'log') {
      update['yaxis.dtick'] = 1;
      update['yaxis.minor.ticks'] = 'outside';
      update['yaxis.minor.ticklen'] = 3;
      update['yaxis.minor.showgrid'] = true;
    } else {
      // From zero, as a chart drawn on a linear axis is (createBaseLayout).
      update['yaxis.rangemode'] = 'tozero';
      update['yaxis.tickmode'] = 'auto';
      update['yaxis.dtick'] = null;
      update['yaxis.minor.ticks'] = 'outside';
      update['yaxis.minor.showgrid'] = false;
    }
  }

  if (Object.keys(update).length === 0) return;

  // Background overlays in special group charts are baked into layout.shapes.
  // Rebuild the chart when x-scale changes so segment bounds are recalculated
  // consistently (especially for log scale with non-positive times).
  if (xScale !== curX
      && selectedIsRadionuclidesGroup
      && selectedDatasetPath
      && selectedBackgroundOverlaySource
      && selectedBackgroundOverlaySource !== '__none__') {
    const savedAxis = captureAxisState();
    Promise.resolve().then(() => createRadionuclidesChart(selectedDatasetPath, savedAxis));
    return;
  }

  Plotly.relayout('plotlyChart', forEveryPanel(plotDiv, update)).then(() => {
    refreshDynamicLegend();
    snapLogRangeToDecades(document.getElementById('plotlyChart'));
  });
}

/**
 * A relayout written for `xaxis` and `yaxis`, extended to the other axes of a
 * chart drawn as panels (renderRadionuclidePanels): `xaxis2`, `yaxis2` and on.
 * Those follow the first pair's range (`matches`), but not its type or ticks,
 * and Plotly requires axes that match to have the same type. A range is left
 * to the first pair: the axes that match follow it, and a panel with a unit
 * of its own keeps its own.
 *
 * @param {HTMLElement} plotDiv
 * @param {Object} update - Plotly.relayout keys; extended in place
 * @returns {Object} the same update
 */
function forEveryPanel(plotDiv, update) {
  const fl = plotDiv && plotDiv._fullLayout;
  if (!fl) return update;
  const more = Object.keys(fl).filter(k => /^[xy]axis\d+$/.test(k));
  if (!more.length) return update;
  for (const key of Object.keys(update)) {
    const m = /^([xy])axis\.(.+)$/.exec(key);
    if (!m || m[2].startsWith('range')) continue;
    for (const ax of more) if (ax[0] === m[1]) update[`${ax}.${m[2]}`] = update[key];
  }
  return update;
}

/**
 * Return current scale selection for given axis ('x' or 'y').
 */
function getScaleValue(axis) {
  const container = document.getElementById(axis + 'ScaleToggle');
  if (!container) return 'linear';
  const active = container.querySelector('button.active');
  return active ? active.dataset.value : 'linear';
}

/**
 * Set the scale button state for specified axis and value.
 */
function setScaleValue(axis, value) {
  const container = document.getElementById(axis + 'ScaleToggle');
  if (!container) return;
  const buttons = container.querySelectorAll('button');
  buttons.forEach(btn => {
    if (btn.dataset.value === value) btn.classList.add('active');
    else btn.classList.remove('active');
  });
}

/* ==========================================================================
   AXES LOCK — pin current axes settings for newly selected data
   ========================================================================== */

let _axesLocked = false;
let _lockedAxesState = null;

/** Toggle the axes lock on/off. When locking, capture the current view. */
function toggleAxesLock() {
  // Prevent locking when on Auto range (default preset)
  if (!_axesLocked) {
    const sel = document.getElementById('presetSelect');
    if (sel && sel.value === 'default') return;
  }

  _axesLocked = !_axesLocked;
  const btn = document.getElementById('lockAxesBtn');
  if (btn) {
    btn.classList.toggle('active', _axesLocked);
    btn.title = _axesLocked ? 'Axes locked — click to unlock' : 'Lock current axes settings';
    const shackle = btn.querySelector('.lock-shackle');
    if (shackle) {
      shackle.setAttribute('d', _axesLocked
        ? 'M7 11V7a5 5 0 0 1 10 0v4'   // closed
        : 'M7 11V7a5 5 0 0 1 9.9-.5');  // open
    }
  }
  if (_axesLocked) {
    _lockedAxesState = _captureCurrentView();
  } else {
    _lockedAxesState = null;
  }
  _setAxesControlsDisabled(_axesLocked);
}

/** Enable or disable scale toggles and preset controls based on lock state. */
function _setAxesControlsDisabled(disabled) {
  // Scale toggle buttons, and the unit prefix beside each
  document.querySelectorAll('#xScaleToggle button, #yScaleToggle button, #xPrefixSelect, #yPrefixSelect').forEach(b => {
    b.disabled = disabled;
  });
  // Preset select and action buttons
  const ids = ['presetSelect'];
  ids.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = disabled;
  });
  // Preset bar buttons (save +, manage ⚙) — all preset-icon-btn except the lock itself
  document.querySelectorAll('.preset-bar .preset-icon-btn:not(.lock-axes-btn)').forEach(b => {
    b.disabled = disabled;
  });
}

/**
 * Apply the locked axes state to a layout object.
 * Sets scale types, ranges and disables autorange when locked.
 *
 * The locked limits are in the file's units (_captureCurrentView), and the
 * chart is drawn in the axes' prefixes, which the lock keeps as they were.
 */
function _applyLockedAxes(layout) {
  if (!_axesLocked || !_lockedAxesState) return;
  const s = _lockedAxesState;
  const exp = axisExponents();

  // Apply scale types and update UI toggles
  if (s.xScale) {
    layout.xaxis.type = s.xScale;
    setScaleValue('x', s.xScale);
  }
  if (s.yScale) {
    layout.yaxis.type = s.yScale;
    setScaleValue('y', s.yScale);
  }

  // Apply X range
  if (s.xMin != null && s.xMax != null) {
    const lo = shiftDecimal(s.xMin, -exp.x);
    const hi = shiftDecimal(s.xMax, -exp.x);
    layout.xaxis.range = s.xScale === 'log'
      ? [Math.log10(lo), Math.log10(hi)]
      : [lo, hi];
    layout.xaxis.autorange = false;
  }

  // Apply Y range
  if (s.yMin != null && s.yMax != null) {
    const lo = shiftDecimal(s.yMin, -exp.y);
    const hi = shiftDecimal(s.yMax, -exp.y);
    layout.yaxis.range = s.yScale === 'log'
      ? [Math.log10(lo), Math.log10(hi)]
      : [lo, hi];
    layout.yaxis.autorange = false;
  }
}

/* ==========================================================================
   UNIT PREFIXES — kBq on an axis, its values divided by 1000
   ==========================================================================

   Beside each axis's lin/log is a prefix for its unit: k shows Bq as kBq and
   the values divided by 1000, µ shows Sv/year as µSv/year and the values
   times a million. It is a setting of the page, as lin/log is: it applies to
   the chart on screen at once (changeAxisPrefix) and to every time chart drawn
   after it. A preset can carry one, and the axes lock keeps it.

   What is drawn is in the prefixed unit: the traces' x and y, the background's
   segments, the ranges. What the page keeps -- the files' values, the
   realisations a band is computed from, a preset's or the lock's limits --
   stays in the file's units, and is put in the axes' as it is handed to Plotly
   (inAxisUnits, segmentsInAxisUnits). A trace drawn with a prefix keeps the
   values it was given as _fileX and _fileY: a change of prefix redraws from
   them, and the CSV export writes them.

   Values are moved by their decimal digits, not multiplied: 1.1e-7 Bq is
   1.1e-10 kBq, where 1.1e-7 / 1000 is 1.1000000000000001e-10 -- as one value
   in six or so is, which an export would then write out.
*/

/** The prefixes an axis can be given, largest first, with the power of ten of each. */
const AXIS_PREFIXES = Object.freeze({ P: 15, T: 12, G: 9, M: 6, k: 3, m: -3, 'µ': -6, n: -9, p: -12, f: -15 });

/** A prefix by its power of ten, for a unit that has one already (mSv with k is Sv). */
const PREFIX_OF_EXPONENT = Object.freeze({
  18: 'E', 15: 'P', 12: 'T', 9: 'G', 6: 'M', 3: 'k', '-3': 'm', '-6': 'µ', '-9': 'n', '-12': 'p', '-15': 'f', '-18': 'a'
});

/** The prefixes recognised at the start of a unit: those above, and µ as Greek mu or as u. */
const PREFIX_IN_UNIT = Object.freeze({
  E: 18, P: 15, T: 12, G: 9, M: 6, k: 3, m: -3, 'µ': -6, 'μ': -6, u: -6, n: -9, p: -12, f: -15, a: -18
});

/*
  The units a prefix is put in front of. Only those: a symbol that is not one
  is written with a power of ten (10³ ppm), which is right whatever it is,
  where a letter in front of it could make something else of it -- k before
  pH would read as nanohenry once pH split into p and H. Hours and days are
  left out, and kelvin, coulomb and the like, which take no prefix in use or
  are mistaken for something that does not (C for °C).
*/
const PREFIXABLE_UNITS = new Set(['Bq', 'Ci', 'Sv', 'Gy', 'rem', 'rad', 'g', 't', 'mol', 'm', 's', 'L', 'l',
  'Pa', 'bar', 'J', 'W', 'Wh', 'eV', 'V', 'Hz', 'a', 'yr', 'year', 'years']);

function isPrefixableUnit(symbol) {
  return PREFIXABLE_UNITS.has(symbol) || /^years?$/i.test(symbol);
}

/**
 * v × 10^e, made by moving v's decimal digits e places: the double nearest the
 * shifted decimal, as v's shortest spelling has it. Anything that is not a
 * finite number is returned as it is: a null in a trace is a gap.
 *
 * @param {*} v
 * @param {number} e
 * @returns {*}
 */
function shiftDecimal(v, e) {
  if (!e || typeof v !== 'number' || !Number.isFinite(v) || v === 0) return v;
  const s = v.toExponential();
  const at = s.indexOf('e');
  return Number(`${s.slice(0, at)}e${Number(s.slice(at + 1)) + e}`);
}

/** The power of ten of a prefix: 3 for k; 0 for none, or for anything that is not one of AXIS_PREFIXES. */
function prefixExponent(prefix) {
  return typeof prefix === 'string' && Object.prototype.hasOwnProperty.call(AXIS_PREFIXES, prefix)
    ? AXIS_PREFIXES[prefix] : 0;
}

/** The prefix of a power of ten in AXIS_PREFIXES: 'k' for 3, '' for 0. */
function prefixOf(e) {
  return Object.keys(AXIS_PREFIXES).find(p => AXIS_PREFIXES[p] === e) || '';
}

/** 10³, 10⁻⁶: a power of ten as text, for a title or a note. */
function powerOfTen(e) {
  return '10' + String(e).replace('-', '⁻').replace(/\d/g, d => '⁰¹²³⁴⁵⁶⁷⁸⁹'[d]);
}

/** The prefix chosen beside an axis's lin/log ('x' or 'y'): '' for none. */
function getAxisPrefix(axis) {
  const select = document.getElementById(axis + 'PrefixSelect');
  const value = select ? select.value : '';
  return prefixExponent(value) ? value : '';
}

/** Choose a prefix beside an axis's lin/log; anything that is not one is none. */
function setAxisPrefix(axis, prefix) {
  const select = document.getElementById(axis + 'PrefixSelect');
  if (select) select.value = prefixExponent(prefix) ? prefix : '';
}

/** The prefixes chosen, as powers of ten: what the next chart is drawn in. */
function axisExponents() {
  return { x: prefixExponent(getAxisPrefix('x')), y: prefixExponent(getAxisPrefix('y')) };
}

/** The powers of ten the chart on screen is drawn in: none for no chart, or one that is not a time chart. */
function chartExponents() {
  const units = currentChartData && currentChartData.axisUnits;
  return units ? { x: units.exp.x, y: units.exp.y } : { x: 0, y: 0 };
}

/**
 * A unit as an axis with a prefix of 10^e shows it: Bq as kBq, mSv/year as
 * µSv/year (e = -3), years as kyears. Where a prefix cannot go in front, the
 * power of ten is written before the unit instead: m3/year as 10³ m3/year,
 * since km3 would be 10⁹ m3; a unit not in PREFIXABLE_UNITS; a prefix that
 * would go past E or a; and no unit at all, which is 10³ alone.
 *
 * @param {*} unit - The file's unit, as its 'unit' attribute has it
 * @param {number} e - The prefix's power of ten; 0 leaves the unit as it is
 * @returns {string}
 */
function unitWithPrefix(unit, e) {
  const text = unit === undefined || unit === null ? '' : String(unit);
  if (!e) return text;
  const u = text.trim();
  const power = powerOfTen(e);
  if (u === '' || /^[-–—−1]$/.test(u)) return power;   // none, or a dimensionless "-" or "1"
  // The first symbol, and what follows it: an exponent there (m3, m^3, m²,
  // m-1, m<sup>3</sup>) would raise the prefix with it.
  const m = /^([A-Za-zµμ]+)([\s\S]*)$/.exec(u);
  if (!m || /^(?:[\d^²³¹⁰-⁻]|\*\*|[-−]\d|<sup)/i.test(m[2])) return `${power} ${u}`;
  const [, symbol, rest] = m;
  if (isPrefixableUnit(symbol)) return PREFIX_OF_EXPONENT[e] ? PREFIX_OF_EXPONENT[e] + u : `${power} ${u}`;
  // A unit with a prefix of its own: the two make one.
  const inner = PREFIX_IN_UNIT[symbol[0]];
  if (inner !== undefined && isPrefixableUnit(symbol.slice(1))) {
    const both = inner + e;
    if (both === 0) return symbol.slice(1) + rest;
    if (PREFIX_OF_EXPONENT[both]) return PREFIX_OF_EXPONENT[both] + symbol.slice(1) + rest;
  }
  return `${power} ${u}`;
}

/**
 * An axis title: its name and, in brackets, its units with the axis's prefix:
 * "Value (kBq/year)", "Time (kyears)". A panel's title is its unit alone, or
 * its group's name when it has none; with a prefix and no unit the bracket
 * holds the power of ten, "Value (10³)".
 *
 * @param {{name: string, units: Array}} spec - What the axis shows
 * @param {number} e - The axis's prefix, as a power of ten
 * @returns {string}
 */
function axisTitle({ name, units }, e) {
  const shown = units.length ? units.map(u => unitWithPrefix(u, e)).join(', ') : (e ? powerOfTen(e) : '');
  if (!shown) return name;
  return name ? `${name} (${shown})` : shown;
}

/** Values in units of 10^e of theirs: the same array when e is 0. */
function valuesInUnit(values, e) {
  if (!e || !values) return values;
  return Array.from(values, v => shiftDecimal(v, -e));
}

/**
 * Traces about to be drawn, put in the axes' units: each one's x and y in the
 * prefixes `exp`, the values it was given kept as _fileX and _fileY. Traces
 * drawn with no prefix, which have never had one, are left exactly as they are.
 *
 * @param {Object[]} traces - Modified in place
 * @param {{x: number, y: number}} exp - The axes' prefixes, as powers of ten
 * @returns {Object[]} the traces
 */
function inAxisUnits(traces, exp) {
  for (const t of traces) {
    if (!('_fileX' in t)) {
      if (!exp.x && !exp.y) continue;
      t._fileX = t.x;
      t._fileY = t.y;
    }
    t.x = valuesInUnit(t._fileX, exp.x);
    t.y = valuesInUnit(t._fileY, exp.y);
  }
  return traces;
}

/**
 * Background segments put on an x axis in units of 10^e, each keeping where it
 * is in the file's units as _fileX0 and _fileX1. The segments themselves when
 * there is nothing to move.
 *
 * @param {Object[]} segments - {x0, x1, ...}
 * @param {number} e
 * @returns {Object[]}
 */
function segmentsInAxisUnits(segments, e) {
  return (segments || []).map((s) => {
    if (!('_fileX0' in s) && !e) return s;
    const x0 = '_fileX0' in s ? s._fileX0 : s.x0;
    const x1 = '_fileX1' in s ? s._fileX1 : s.x1;
    return { ...s, x0: shiftDecimal(Number(x0), -e), x1: shiftDecimal(Number(x1), -e), _fileX0: x0, _fileX1: x1 };
  });
}

/* One change of prefix at a time: each redraws from where the last one left it. */
let _axisUnitsQueue = Promise.resolve();

/**
 * The prefix select beside an axis's lin/log. The chart on screen is redrawn
 * in it at once, over the same stretch of data -- 1e4 to 1e9 Bq becomes 10 to
 * 1e6 kBq -- and the charts drawn after it are drawn in it.
 *
 * The preset selected stays selected, since it is the same data, unless it
 * gives this axis a prefix of its own and this is another: then the view is
 * no longer the preset's, and the dropdown says Custom.
 *
 * @param {string} axis - 'x' or 'y'
 * @returns {Promise}
 */
function changeAxisPrefix(axis) {
  const which = axis === 'x' ? 'x' : 'y';
  const selected = document.getElementById('presetSelect');
  const preset = currentChartData && selected ? loadPresets().find(p => p.id === selected.value) : null;
  const own = preset ? preset[which + 'Prefix'] : null;
  if (own !== null && own !== undefined && own !== getAxisPrefix(which)) _markCustomPreset();
  _axisUnitsQueue = _axisUnitsQueue
    .then(() => redrawInAxisUnits(which, prefixExponent(getAxisPrefix(which))))
    .catch(err => reportFailure('changeAxisPrefix', err, { userMessage: 'The axis could not be redrawn in that unit' }));
  return _axisUnitsQueue;
}

/**
 * Redraw the time chart on screen with `axis` in units of 10^e, in place: its
 * traces from their values in the file's units, its title, its range over the
 * same stretch of data (a log y axis on auto range stays on it), the background
 * along a time axis, and Show Max's numbers. The preset selected stays so.
 *
 * @param {string} axis - 'x' or 'y'
 * @param {number} e
 * @returns {Promise}
 */
async function redrawInAxisUnits(axis, e) {
  const plotDiv = document.getElementById('plotlyChart');
  const units = currentChartData && currentChartData.axisUnits;
  const fl = plotDiv && plotDiv._fullLayout;
  if (!units || !fl || !Array.isArray(plotDiv.data)) return;
  const from = units.exp[axis];
  if (from === e) return;

  const field = axis === 'x' ? '_fileX' : '_fileY';
  const values = plotDiv.data.map((t) => {
    if (!('_fileX' in t)) {
      t._fileX = valuesInUnit(t.x, -units.exp.x);
      t._fileY = valuesInUnit(t.y, -units.exp.y);
    }
    return valuesInUnit(t[field], e);
  });

  const update = {};
  for (const [key, spec] of Object.entries(units.titles)) {
    if (key[0] === axis && spec) update[`${key}.title.text`] = axisTitle(spec, e);
  }
  // A range set by hand, a preset or the snap is moved to where the same data
  // is; one Plotly ranges itself follows the data on its own.
  const shift = from - e;
  const keys = Object.keys(fl).filter(k => k[0] === axis && /^[xy]axis\d*$/.test(k));
  const autoLog = keys.filter(k => axis === 'y' && isAutoLogY(plotDiv, k));
  for (const key of keys) {
    const ax = fl[key];
    if (ax.matches || ax.autorange || !Array.isArray(ax.range)) continue;
    const log = ax.type === 'log';
    update[`${key}.range`] = ax.range.map(v => (log ? Number(v) + shift : shiftDecimal(Number(v), shift)));
    update[`${key}.autorange`] = false;
  }
  let segments = null;
  if (axis === 'x' && chartHasBackgroundShapes(plotDiv) && Array.isArray(plotDiv.__bgSegments)) {
    segments = segmentsInAxisUnits(plotDiv.__bgSegments, e);
    update.shapes = backgroundRectShapes(segments, values.map(x => ({ x })), fl.xaxis.type);
  }

  _suppressPresetSync = true;
  try {
    await Plotly.update(plotDiv, { [axis]: values }, update);
  } finally {
    _suppressPresetSync = false;
  }
  units.exp[axis] = e;
  for (const key of autoLog) {
    plotDiv.__autoLogY = Object.assign({}, plotDiv.__autoLogY, { [key]: plotDiv.__autoLogY[key].map(v => v + shift) });
  }
  if (segments) setupBackgroundOverlayTooltip(plotDiv, segments);
  // Show Max's numbers are in the axis's unit.
  const showMax = document.getElementById('showMax');
  const showMaxLabel = document.getElementById('showMaxLabel');
  if (axis === 'y' && showMax && showMax.checked && showMaxLabel && showMaxLabel.style.display !== 'none') toggleShowMax();
  refreshDynamicLegend();
  await snapLogRangeToDecades(plotDiv);
}
