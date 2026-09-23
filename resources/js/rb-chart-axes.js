/* ==========================================================================
   RB CHART - line styles, axis scale controls, axes lock
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
 * Get the line style (color, dash pattern) for a radionuclide isotope.
 * 
 * Predefined styles are provided for common isotopes in categories:
 * - Actinides (Ac, Am, Cm, Np, Pa, Pu, Th, U)
 * - Fission products (Ag, Cs, I, Pd, Se, Sm, Sn, Sr, Tc, Zr)
 * - Activation products (Be, C, Cl, Co, H, Ni, Nb, Mo)
 * - Other radionuclides (various)
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

  // Exposed groups
  'drained_mire':{color: 'rgb(165,42,42)', dash: 'solid'},
  'forager':{color: 'rgb(147,197,114)', dash: 'solid'},
  'garden_plot':{color: 'rgb(0,191,255)', dash: 'solid'},
  'infield_outland':{color: 'rgb(255,204,0)', dash: 'solid'},
  'drilled_well':{color: 'rgb(0,0,255)', dash: 'solid'},
  'drained_mire_irrig':{color: 'rgb(165,42,42)', dash: 'dash'},

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
    if (yScale === 'log') {
      update['yaxis.dtick'] = 1;
      update['yaxis.minor.ticks'] = 'outside';
      update['yaxis.minor.ticklen'] = 3;
      update['yaxis.minor.showgrid'] = true;
    } else {
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

  Plotly.relayout('plotlyChart', update).then(() => {
    refreshDynamicLegend();
    snapLogRangeToDecades(document.getElementById('plotlyChart'));
  });
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
  // Scale toggle buttons
  document.querySelectorAll('#xScaleToggle button, #yScaleToggle button').forEach(b => {
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
 */
function _applyLockedAxes(layout) {
  if (!_axesLocked || !_lockedAxesState) return;
  const s = _lockedAxesState;

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
    layout.xaxis.range = s.xScale === 'log'
      ? [Math.log10(s.xMin), Math.log10(s.xMax)]
      : [s.xMin, s.xMax];
    layout.xaxis.autorange = false;
  }

  // Apply Y range
  if (s.yMin != null && s.yMax != null) {
    layout.yaxis.range = s.yScale === 'log'
      ? [Math.log10(s.yMin), Math.log10(s.yMax)]
      : [s.yMin, s.yMax];
    layout.yaxis.autorange = false;
  }
}
