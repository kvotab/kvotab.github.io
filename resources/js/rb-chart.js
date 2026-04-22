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
function getLineStyle(name) {
  const lineStyles = {
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
  };
  
  const defaultStyle = { color: null, dash: 'solid', width: 2 };
  
  if (name in lineStyles) {
    return { ...defaultStyle, ...lineStyles[name] };
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

/**
 * Handler for clicks on the scale toggle buttons.
 */
function handleScaleButtonClick(evt) {
  const btn = evt.currentTarget;
  const axis = btn.dataset.axis;
  const val = btn.dataset.value;
  setScaleValue(axis, val);

  // If Auto range is selected, lin/log toggle should not leave Auto range
  const sel = document.getElementById('presetSelect');
  if (sel && sel.value === 'default') {
    _suppressPresetSync = true;
    updateChartScales();
    setTimeout(() => { _suppressPresetSync = false; }, 0);
  } else {
    updateChartScales();
  }
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

/* ==========================================================================
   CHART PRESETS — customizable, persistent axis presets
   ========================================================================== */

const _PRESETS_STORAGE_KEY = 'chartPresets';
let _suppressPresetSync = false;

const _BUILTIN_PRESETS = [
  {
    id: 'default',
    name: 'Auto range',
    builtIn: true,
    xScale: null, yScale: null,
    xMin: null, xMax: null, yMin: null, yMax: null
  },
  {
    id: 'release',
    name: 'SFR Release',
    builtIn: false,
    xScale: 'log', yScale: 'log',
    xMin: 100, xMax: 100000, yMin: 10000, yMax: 1e9
  },
  {
    id: 'dose',
    name: 'SFR Dose',
    builtIn: false,
    xScale: 'log', yScale: 'log',
    xMin: 1000, xMax: 1e5, yMin: 1e-7, yMax: 2e-5
  }
];

/** Load presets from localStorage (falls back to built-in defaults). */
function loadPresets() {
  try {
    const raw = localStorage.getItem(_PRESETS_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length) {
        // Ensure the Default preset is always first
        if (!parsed.find(p => p.id === 'default')) {
          parsed.unshift(_BUILTIN_PRESETS[0]);
        }
        return parsed;
      }
    }
  } catch (_) { /* ignore corrupt data */ }
  return JSON.parse(JSON.stringify(_BUILTIN_PRESETS));
}

/** Save presets array to localStorage. */
function savePresetsToStorage(presets) {
  localStorage.setItem(_PRESETS_STORAGE_KEY, JSON.stringify(presets));
}

/** Populate the preset <select> dropdown. */
function populatePresetDropdown() {
  const sel = document.getElementById('presetSelect');
  if (!sel) return;
  const presets = loadPresets();
  sel.innerHTML = '';
  presets.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = p.name;
    sel.appendChild(opt);
  });
}

/** Apply the selected preset to the chart. */
function applySelectedPreset() {
  const sel = document.getElementById('presetSelect');
  if (!sel) return;
  if (sel.value === '__custom__') return;
  _removeCustomOption();
  applyPresetById(sel.value);
}

/** Apply a preset by its id string. */
function applyPresetById(id) {
  if (!currentChartData) return;
  const presets = loadPresets();
  const preset = presets.find(p => p.id === id);
  if (!preset) return;

  // Default preset → reset to autorange with current scale toggles
  if (preset.id === 'default') {
    const xScale = getScaleValue('x');
    const yScale = getScaleValue('y');
    _suppressPresetSync = true;
    Plotly.relayout('plotlyChart', {
      'xaxis.autorange': true,
      'yaxis.autorange': true,
      'xaxis.dtick': xScale === 'log' ? 1 : null,
      'xaxis.tickmode': xScale === 'log' ? null : 'auto',
      'xaxis.minor.ticks': 'outside',
      'xaxis.minor.ticklen': 3,
      'xaxis.minor.showgrid': xScale === 'log',
      'yaxis.dtick': yScale === 'log' ? 1 : null,
      'yaxis.tickmode': yScale === 'log' ? null : 'auto',
      'yaxis.minor.ticks': 'outside',
      'yaxis.minor.ticklen': 3,
      'yaxis.minor.showgrid': yScale === 'log'
    }).then(() => { _suppressPresetSync = false; refreshDynamicLegend(); snapLogRangeToDecades(document.getElementById('plotlyChart')); });
    return;
  }

  const update = {};
  if (preset.xScale) {
    setScaleValue('x', preset.xScale);
    update['xaxis.type'] = preset.xScale;
    if (preset.xScale === 'log') {
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
  if (preset.yScale) {
    setScaleValue('y', preset.yScale);
    update['yaxis.type'] = preset.yScale;
    if (preset.yScale === 'log') {
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

  if (preset.xMin != null && preset.xMax != null) {
    update['xaxis.range'] = preset.xScale === 'log'
      ? [Math.log10(preset.xMin), Math.log10(preset.xMax)]
      : [preset.xMin, preset.xMax];
    update['xaxis.autorange'] = false;
  } else {
    update['xaxis.autorange'] = true;
  }

  if (preset.yMin != null && preset.yMax != null) {
    update['yaxis.range'] = preset.yScale === 'log'
      ? [Math.log10(preset.yMin), Math.log10(preset.yMax)]
      : [preset.yMin, preset.yMax];
    update['yaxis.autorange'] = false;
  } else {
    update['yaxis.autorange'] = true;
  }

  _suppressPresetSync = true;
  Plotly.relayout('plotlyChart', update).then(() => { _suppressPresetSync = false; refreshDynamicLegend(); snapLogRangeToDecades(document.getElementById('plotlyChart')); });
}

/** Capture the current chart view state as a preset object (without id/name). */
function _captureCurrentView() {
  const plotDiv = document.getElementById('plotlyChart');
  if (!plotDiv || !plotDiv.layout) return null;
  const xaxis = plotDiv.layout.xaxis || {};
  const yaxis = plotDiv.layout.yaxis || {};
  const xScale = getScaleValue('x');
  const yScale = getScaleValue('y');

  let xMin = null, xMax = null, yMin = null, yMax = null;
  if (xaxis.range && xaxis.autorange !== true) {
    xMin = xScale === 'log' ? Math.pow(10, xaxis.range[0]) : xaxis.range[0];
    xMax = xScale === 'log' ? Math.pow(10, xaxis.range[1]) : xaxis.range[1];
  }
  if (yaxis.range && yaxis.autorange !== true) {
    yMin = yScale === 'log' ? Math.pow(10, yaxis.range[0]) : yaxis.range[0];
    yMax = yScale === 'log' ? Math.pow(10, yaxis.range[1]) : yaxis.range[1];
  }
  return { xScale, yScale, xMin, xMax, yMin, yMax };
}

/** Save the current chart view as a new preset (prompts for name). */
function saveCurrentAsPreset() {
  if (!currentChartData) { alert('No chart to capture.'); return; }
  const name = prompt('Preset name:');
  if (!name || !name.trim()) return;

  const view = _captureCurrentView();
  if (!view) return;

  const presets = loadPresets();
  const id = 'user_' + Date.now();
  presets.push(Object.assign({ id, name: name.trim(), builtIn: false }, view));
  savePresetsToStorage(presets);
  populatePresetDropdown();

  // Select the newly created preset
  const sel = document.getElementById('presetSelect');
  if (sel) sel.value = id;
}

/* ---------- Preset Manager Dialog ---------- */

function openPresetManager() {
  const overlay = document.getElementById('presetManagerOverlay');
  if (!overlay) return;
  _renderPresetManagerList();
  overlay.style.display = 'flex';
}

function closePresetManager() {
  const overlay = document.getElementById('presetManagerOverlay');
  if (overlay) overlay.style.display = 'none';

  // Re-sync dropdown: keep current selection if it still exists, else fall back to default
  const sel = document.getElementById('presetSelect');
  if (sel) {
    const prev = sel.value;
    populatePresetDropdown();
    const presets = loadPresets();
    if (presets.find(p => p.id === prev)) {
      sel.value = prev;
    } else {
      sel.value = 'default';
    }
    // Apply the (possibly updated) selected preset to the chart
    applyPresetById(sel.value);
  }
}

function _renderPresetManagerList() {
  const list = document.getElementById('presetManagerList');
  if (!list) return;
  const presets = loadPresets();
  list.innerHTML = '';

  presets.forEach((p, idx) => {
    const row = document.createElement('div');
    row.className = 'preset-manager-row';
    row.dataset.presetId = p.id;

    const nameSpan = document.createElement('span');
    nameSpan.className = 'preset-manager-name';
    nameSpan.textContent = p.name;
    if (p.id === 'default') nameSpan.style.fontStyle = 'italic';

    // Summary line showing current axis settings
    const summary = document.createElement('span');
    summary.className = 'preset-manager-summary';
    if (p.id === 'default') {
      summary.textContent = 'auto';
    } else {
      const parts = [];
      const xS = p.xScale || 'auto';
      const yS = p.yScale || 'auto';
      const fmtR = (lo, hi) => (lo != null && hi != null) ? lo + ' – ' + hi : 'auto';
      parts.push('X: ' + xS + ' [' + fmtR(p.xMin, p.xMax) + ']');
      parts.push('Y: ' + yS + ' [' + fmtR(p.yMin, p.yMax) + ']');
      summary.textContent = parts.join('   ');
    }

    const nameBlock = document.createElement('div');
    nameBlock.className = 'preset-manager-name-block';
    nameBlock.appendChild(nameSpan);
    nameBlock.appendChild(summary);
    row.appendChild(nameBlock);

    if (p.id !== 'default') {
      const btnGroup = document.createElement('span');
      btnGroup.className = 'preset-manager-actions';

      const editBtn = document.createElement('button');
      editBtn.textContent = 'Edit';
      editBtn.title = 'Edit preset settings';
      editBtn.onclick = () => _editPreset(p.id);
      btnGroup.appendChild(editBtn);

      const captureBtn = document.createElement('button');
      captureBtn.textContent = 'Capture';
      captureBtn.title = 'Overwrite with current chart view';
      captureBtn.onclick = () => _updatePresetFromView(p.id);
      btnGroup.appendChild(captureBtn);

      const deleteBtn = document.createElement('button');
      deleteBtn.textContent = 'Delete';
      deleteBtn.title = 'Delete preset';
      deleteBtn.className = 'preset-delete-btn';
      deleteBtn.onclick = () => _deletePreset(p.id);
      btnGroup.appendChild(deleteBtn);

      row.appendChild(btnGroup);
    }
    list.appendChild(row);
  });
}

/** Show inline edit form for a preset. */
function _editPreset(id) {
  const presets = loadPresets();
  const p = presets.find(x => x.id === id);
  if (!p) return;

  // Remove any existing edit form first
  const prev = document.getElementById('presetEditForm');
  if (prev) prev.remove();

  const list = document.getElementById('presetManagerList');
  if (!list) return;

  // Find the row for this preset
  const rows = list.querySelectorAll('.preset-manager-row');
  let targetRow = null;
  rows.forEach(r => { if (r.dataset.presetId === id) targetRow = r; });
  if (!targetRow) return;

  const form = document.createElement('div');
  form.id = 'presetEditForm';
  form.className = 'preset-edit-form';

  const fmtVal = (v) => (v == null ? '' : v);

  form.innerHTML =
    '<div class="preset-edit-row">' +
      '<label>Name <input type="text" id="pe_name" class="preset-name-input" value="' + _escAttr(p.name) + '"></label>' +
    '</div>' +
    '<div class="preset-edit-row">' +
      '<label>X scale ' +
        '<select id="pe_xScale">' +
          '<option value=""' + (p.xScale == null ? ' selected' : '') + '>auto</option>' +
          '<option value="linear"' + (p.xScale === 'linear' ? ' selected' : '') + '>linear</option>' +
          '<option value="log"' + (p.xScale === 'log' ? ' selected' : '') + '>log</option>' +
        '</select>' +
      '</label>' +
      '<label>X min <input type="text" id="pe_xMin" value="' + fmtVal(p.xMin) + '" placeholder="auto"></label>' +
      '<label>X max <input type="text" id="pe_xMax" value="' + fmtVal(p.xMax) + '" placeholder="auto"></label>' +
    '</div>' +
    '<div class="preset-edit-row">' +
      '<label>Y scale ' +
        '<select id="pe_yScale">' +
          '<option value=""' + (p.yScale == null ? ' selected' : '') + '>auto</option>' +
          '<option value="linear"' + (p.yScale === 'linear' ? ' selected' : '') + '>linear</option>' +
          '<option value="log"' + (p.yScale === 'log' ? ' selected' : '') + '>log</option>' +
        '</select>' +
      '</label>' +
      '<label>Y min <input type="text" id="pe_yMin" value="' + fmtVal(p.yMin) + '" placeholder="auto"></label>' +
      '<label>Y max <input type="text" id="pe_yMax" value="' + fmtVal(p.yMax) + '" placeholder="auto"></label>' +
    '</div>' +
    '<div class="preset-edit-btns">' +
      '<button id="pe_save" class="preset-edit-save">Save</button>' +
      '<button id="pe_cancel">Cancel</button>' +
    '</div>';

  targetRow.insertAdjacentElement('afterend', form);

  document.getElementById('pe_save').onclick = () => _savePresetEdit(id);
  document.getElementById('pe_cancel').onclick = () => _cancelPresetEdit();
}

function _escAttr(s) {
  return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
}

function _parseNum(s) {
  if (s == null) return null;
  const t = String(s).trim();
  if (t === '') return null;
  const n = Number(t);
  return isNaN(n) ? null : n;
}

function _savePresetEdit(id) {
  const presets = loadPresets();
  const p = presets.find(x => x.id === id);
  if (!p) return;

  const nameVal = (document.getElementById('pe_name').value || '').trim();
  if (!nameVal) { alert('Name cannot be empty.'); return; }

  p.name   = nameVal;
  p.xScale = document.getElementById('pe_xScale').value || null;
  p.yScale = document.getElementById('pe_yScale').value || null;
  p.xMin   = _parseNum(document.getElementById('pe_xMin').value);
  p.xMax   = _parseNum(document.getElementById('pe_xMax').value);
  p.yMin   = _parseNum(document.getElementById('pe_yMin').value);
  p.yMax   = _parseNum(document.getElementById('pe_yMax').value);

  savePresetsToStorage(presets);
  populatePresetDropdown();
  _renderPresetManagerList();
}

function _cancelPresetEdit() {
  const f = document.getElementById('presetEditForm');
  if (f) f.remove();
}

function _updatePresetFromView(id) {
  if (!currentChartData) { alert('No chart to capture.'); return; }
  const presets = loadPresets();
  const p = presets.find(x => x.id === id);
  if (!p) return;
  const view = _captureCurrentView();
  if (!view) return;
  Object.assign(p, view);
  savePresetsToStorage(presets);
  populatePresetDropdown();
  _renderPresetManagerList();
}

function _deletePreset(id) {
  if (!confirm('Delete this preset?')) return;
  let presets = loadPresets();
  presets = presets.filter(x => x.id !== id);
  savePresetsToStorage(presets);
  populatePresetDropdown();
  _renderPresetManagerList();
}

/** Export all presets as a JSON file download. */
function exportPresets() {
  const presets = loadPresets();
  const blob = new Blob([JSON.stringify(presets, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'chart-presets.json';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/** Reset the preset dropdown back to Default (e.g. when a new chart is drawn). */
function resetPresetDropdown() {
  const sel = document.getElementById('presetSelect');
  if (!sel) return;
  const customOpt = sel.querySelector('option[value="__custom__"]');
  if (customOpt) customOpt.remove();
  sel.value = 'default';
}

/** Add/select a temporary "Custom *" option in the preset dropdown. */
function _markCustomPreset() {
  const sel = document.getElementById('presetSelect');
  if (!sel) return;
  let opt = sel.querySelector('option[value="__custom__"]');
  if (!opt) {
    opt = document.createElement('option');
    opt.value = '__custom__';
    opt.textContent = 'Custom \u2731';
    sel.appendChild(opt);
  }
  sel.value = '__custom__';
}

/** Remove the temporary "Custom *" option from the preset dropdown. */
function _removeCustomOption() {
  const sel = document.getElementById('presetSelect');
  if (!sel) return;
  const opt = sel.querySelector('option[value="__custom__"]');
  if (opt) opt.remove();
}

/**
 * Snap log-scale axes to full-decade boundaries so the last major
 * gridline and its tick label are always visible.
 */
let _snappingLog = false;
function snapLogRangeToDecades(plotDiv) {
  if (!plotDiv || _snappingLog) return Promise.resolve();
  var fl = plotDiv._fullLayout;
  if (!fl) return Promise.resolve();
  var update = {};
  ['xaxis', 'yaxis'].forEach(function(axis) {
    var ax = fl[axis];
    if (!ax || ax.type !== 'log') return;
    // Only snap auto-ranged axes; preserve explicit user/preset limits
    if (!ax.autorange) return;
    var r = ax.range;
    if (!r || r.length < 2) return;
    var r0 = r[0], r1 = r[1];
    var target0 = Math.floor(r0);
    var target1 = Math.ceil(r1);
    if (Math.abs(r0 - target0) > 0.001 || Math.abs(r1 - target1) > 0.001) {
      update[axis + '.range'] = [target0, target1];
      update[axis + '.autorange'] = false;
    }
  });
  if (Object.keys(update).length > 0) {
    _suppressPresetSync = true;
    _snappingLog = true;
    return Plotly.relayout(plotDiv, update).then(function() {
      _suppressPresetSync = false;
      _snappingLog = false;
    });
  }
  return Promise.resolve();
}

/**
 * Listen for user-initiated axis changes and sync the preset dropdown.
 * - Manual zoom/pan → switch to "Custom *"
 * - Autoscale (double-click or button) → switch to "Auto range"
 * Programmatic relayouts are ignored via _suppressPresetSync flag.
 */
function setupPresetRelayoutSync(plotDiv) {
  plotDiv.on('plotly_relayout', function(eventData) {
    if (_suppressPresetSync) return;
    if (!eventData) return;

    // Autoscale → select Auto range, then snap log decades
    if (eventData['xaxis.autorange'] || eventData['yaxis.autorange']) {
      _removeCustomOption();
      const sel = document.getElementById('presetSelect');
      if (sel) sel.value = 'default';
      snapLogRangeToDecades(plotDiv);
      return;
    }

    // Any user-initiated range or type change → Custom
    const axisKeys = ['xaxis.range[0]', 'xaxis.range[1]', 'xaxis.range',
                      'yaxis.range[0]', 'yaxis.range[1]', 'yaxis.range',
                      'xaxis.type', 'yaxis.type'];
    const isAxisChange = axisKeys.some(k => k in eventData);
    if (isAxisChange) {
      const sel = document.getElementById('presetSelect');
      if (sel && sel.value !== '__custom__') _markCustomPreset();
    }
  });
}

/** Import presets from a JSON file. */
function importPresets() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.json,application/json';
  input.onchange = () => {
    const file = input.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const imported = JSON.parse(reader.result);
        if (!Array.isArray(imported)) { alert('Invalid preset file.'); return; }
        // Validate each entry has at least id and name
        for (const p of imported) {
          if (!p.id || !p.name) { alert('Invalid preset entry found.'); return; }
        }
        savePresetsToStorage(imported);
        populatePresetDropdown();
        _renderPresetManagerList();
        alert('Imported ' + imported.length + ' preset(s).');
      } catch (e) {
        alert('Failed to parse preset file.');
      }
    };
    reader.readAsText(file);
  };
  input.click();
}

/**
 * Export current chart data to a CSV file.
 * Creates a downloadable file with columns: Series, X, Y.
 * Each trace in the chart becomes a series in the CSV.
 * 
 * @returns {void}
 */
function downloadChartData() {
  if (!currentChartData) {
    alert('No chart data available');
    return;
  }
  
  let csv = 'Series,X,Y\n';
  
  for (const trace of currentChartData.traces) {
    const name = trace.name;
    for (let i = 0; i < trace.x.length; i++) {
      csv += `"${name}",${trace.x[i]},${trace.y[i]}\n`;
    }
  }
  
  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `chart_data_${Date.now()}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * Export current chart data to an Excel file (.xlsx).
 * Creates a workbook with two sheets:
 * - "Chart": Contains a native Excel scatter chart with the same look as Plotly
 * - "Data": Contains the chart data with time column and one column per trace
 * 
 * Uses xlsxwrite.js for native Excel chart creation with full feature support.
 * Creates a chart that matches the Plotly chart styling:
 * - Same axis type (log/linear) with proper logarithmic scale support
 * - Same line colors from traces
 * - Same dash patterns (solid, dash, dot, dashdot, longdash)
 * - Gridlines matching the Plotly style
 * - Lines without markers
 * 
 * @returns {Promise<void>}
 */
async function downloadChartDataAsExcel() {
  if (!currentChartData) {
    alert('No chart data available');
    return;
  }
  
  // Check if xlsxwrite.js is ready
  if (!window.xlsxReady || !window.XlsxWriter) {
    alert('Excel export library is not loaded. Please refresh the page.');
    return;
  }
  
  try {
    const allTraces = currentChartData.traces;
    const layout = currentChartData.layout;
    
    // Get current state from the actual Plotly chart element
    const chartDiv = document.getElementById('plotlyChart');
    const plotlyTraces = chartDiv && chartDiv.data ? chartDiv.data : allTraces;
    const plotlyLayout = chartDiv && chartDiv.layout ? chartDiv.layout : layout;
    
    // Check if Dynamic Legend is enabled and we should filter by viewport
    const dynamicLegendCheckbox = document.getElementById('dynamicLegend');
    const isDynamicLegendEnabled = dynamicLegendCheckbox && dynamicLegendCheckbox.checked;
    
    let traces;
    
    if (isDynamicLegendEnabled && plotlyLayout.xaxis && plotlyLayout.yaxis) {
      // Filter traces based on whether they have data points in the current viewport
      const xRange = plotlyLayout.xaxis.range;
      const yRange = plotlyLayout.yaxis.range;
      
      if (xRange && yRange) {
        const xIsLog = plotlyLayout.xaxis.type === 'log';
        const yIsLog = plotlyLayout.yaxis.type === 'log';
        
        const xMin = xIsLog ? Math.pow(10, xRange[0]) : xRange[0];
        const xMax = xIsLog ? Math.pow(10, xRange[1]) : xRange[1];
        const yMin = yIsLog ? Math.pow(10, yRange[0]) : yRange[0];
        const yMax = yIsLog ? Math.pow(10, yRange[1]) : yRange[1];
        
        traces = plotlyTraces.filter(trace => {
          // Check if trace has any data points in the current viewport
          for (let j = 0; j < trace.x.length; j++) {
            const x = trace.x[j];
            const y = trace.y[j];
            if (x !== null && x !== undefined && y !== null && y !== undefined) {
              if (x >= xMin && x <= xMax && y >= yMin && y <= yMax) {
                return true;
              }
            }
          }
          return false;
        });
      } else {
        traces = plotlyTraces;
      }
    } else {
      // Dynamic Legend off - export all traces (or filter by visible property)
      traces = plotlyTraces.filter(trace => {
        const visible = trace.visible;
        return visible === undefined || visible === true;
      });
    }
    
    if (traces.length === 0) {
      alert('No visible traces to export. Please show at least one trace in the chart.');
      return;
    }
    
    // Find the longest x array to determine row count
    const maxLength = Math.max(...traces.map(t => t.x ? t.x.length : 0));
    
    // Extract chart metadata
    const chartTitle = layout && layout.title && layout.title.text 
      ? layout.title.text 
      : 'Chart Data';
    const xAxisTitle = layout && layout.xaxis && layout.xaxis.title && layout.xaxis.title.text
      ? layout.xaxis.title.text
      : 'Time';
    const yAxisTitle = layout && layout.yaxis && layout.yaxis.title && layout.yaxis.title.text
      ? layout.yaxis.title.text
      : 'Value';
    
    // Detect axis types from Plotly layout
    const xAxisType = plotlyLayout && plotlyLayout.xaxis && plotlyLayout.xaxis.type ? plotlyLayout.xaxis.type : 'linear';
    const yAxisType = plotlyLayout && plotlyLayout.yaxis && plotlyLayout.yaxis.type ? plotlyLayout.yaxis.type : 'linear';
    
    // Helper function to parse rgb color string to [R, G, B] array
    const parseRgbColor = (colorStr) => {
      if (!colorStr) return null;
      // Handle rgb(r,g,b) format
      const rgbMatch = colorStr.match(/rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)/i);
      if (rgbMatch) {
        return [parseInt(rgbMatch[1]), parseInt(rgbMatch[2]), parseInt(rgbMatch[3])];
      }
      // Handle hex format #RRGGBB or RRGGBB
      const hexMatch = colorStr.match(/#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i);
      if (hexMatch) {
        return [parseInt(hexMatch[1], 16), parseInt(hexMatch[2], 16), parseInt(hexMatch[3], 16)];
      }
      // Handle short hex format #RGB
      const shortHexMatch = colorStr.match(/^#?([a-f\d])([a-f\d])([a-f\d])$/i);
      if (shortHexMatch) {
        return [
          parseInt(shortHexMatch[1] + shortHexMatch[1], 16),
          parseInt(shortHexMatch[2] + shortHexMatch[2], 16),
          parseInt(shortHexMatch[3] + shortHexMatch[3], 16)
        ];
      }
      return null;
    };
    
    // Map Plotly dash type to Excel dash type (using sys variants for standard Excel look)
    const mapDashType = (plotlyDash) => {
      if (!plotlyDash || plotlyDash === 'solid') return 'solid';
      switch (plotlyDash) {
        case 'dash': return 'sysDash';
        case 'dot': return 'sysDot';
        case 'dashdot': return 'sysDashDot';
        case 'longdash': return 'lgDash';
        case 'longdashdot': return 'lgDashDot';
        default: return 'solid';
      }
    };
    
    // Fallback Plotly-like color palette (brighter colors)
    const plotlyColors = [
      [0x1F, 0x77, 0xB4], // blue
      [0xFF, 0x7F, 0x0E], // orange
      [0x2C, 0xA0, 0x2C], // green
      [0xD6, 0x27, 0x28], // red
      [0x94, 0x67, 0xBD], // purple
      [0x8C, 0x56, 0x4B], // brown
      [0xE3, 0x77, 0xC2], // pink
      [0x7F, 0x7F, 0x7F], // gray
      [0xBC, 0xBD, 0x22], // olive
      [0x17, 0xBE, 0xCF]  // cyan
    ];
    
    // Create workbook using xlsxwrite.js
    const xlsx = new XlsxWriter();
    
    // Plotly-like gridline color (light gray)
    const gridColor = 'E5ECF6';
    const minorGridColor = 'EEF2F8';
    
    // ============ CREATE CHART ============
    // Configure chart with axis settings
    const chartConfig = {
      width: 800,
      height: 500,
      scatterStyle: 'line',  // Line without markers
      showBorder: false,     // Remove chart border
      xAxis: {
        title: { text: xAxisTitle },
        numberFormat: '[>1000]### ### ### ##0;General',
        fontSize: 9,
        majorGridlines: { color: gridColor, width: 0.75 }
      },
      yAxis: {
        title: { text: yAxisTitle, customAngle: -90 },
        numberFormat: '0E+0',
        fontSize: 9,
        majorGridlines: { color: gridColor, width: 0.75 }
      },
      legend: { position: 'r', fontSize: 8 }
    };
    
    // Set logarithmic scale if Plotly uses it, and add minor gridlines/ticks
    if (xAxisType === 'log') {
      chartConfig.xAxis.logBase = 10;
      chartConfig.xAxis.minorGridlines = { color: minorGridColor, width: 0.5 };
      chartConfig.xAxis.minorTickMark = 'out';
    }
    if (yAxisType === 'log') {
      chartConfig.yAxis.logBase = 10;
      chartConfig.yAxis.minorGridlines = { color: minorGridColor, width: 0.5 };
      chartConfig.yAxis.minorTickMark = 'out';
    }
    
    // Set axis min/max to match current Plotly view
    // For log scale: always set limits (needed for proper scaling)
    // For linear scale: only set limits if user has zoomed (autorange is false)
    if (plotlyLayout.xaxis && plotlyLayout.xaxis.range) {
      const xRange = plotlyLayout.xaxis.range;
      const xIsLog = xAxisType === 'log';
      const xIsZoomed = plotlyLayout.xaxis.autorange === false;
      if (xIsLog || xIsZoomed) {
        chartConfig.xAxis.minimum = xIsLog ? Math.pow(10, xRange[0]) : xRange[0];
        chartConfig.xAxis.maximum = xIsLog ? Math.pow(10, xRange[1]) : xRange[1];
      }
    }
    if (plotlyLayout.yaxis && plotlyLayout.yaxis.range) {
      const yRange = plotlyLayout.yaxis.range;
      const yIsLog = yAxisType === 'log';
      const yIsZoomed = plotlyLayout.yaxis.autorange === false;
      if (yIsLog || yIsZoomed) {
        chartConfig.yAxis.minimum = yIsLog ? Math.pow(10, yRange[0]) : yRange[0];
        chartConfig.yAxis.maximum = yIsLog ? Math.pow(10, yRange[1]) : yRange[1];
      }
    }
    
    const chart = xlsx.newChart(chartConfig);
    
    // Get x values from the first trace
    const xValues = traces.length > 0 && traces[0].x ? traces[0].x : [];
    
    // Add series to chart
    traces.forEach((trace, idx) => {
      // Get color from trace or use fallback
      let color = plotlyColors[idx % plotlyColors.length];
      const traceColor = trace.line?.color || trace.marker?.color || null;
      if (traceColor) {
        const parsedColor = parseRgbColor(traceColor);
        if (parsedColor) {
          color = parsedColor;
        }
      }
      
      // Get dash type from trace
      const dashType = mapDashType(trace.line?.dash);
      
      // Get line width from trace (default to 2 if not specified)
      const lineWidth = trace.line?.width || 2;
      
      // Filter out null/undefined values
      const yVals = trace.y || [];
      const xVals = trace.x || xValues;
      
      // Create series with xlsxwrite.js
      const series = xlsx.newSeries({
        name: { text: trace.name || `Series ${idx + 1}` },
        x: { values: xVals.map(v => v === null || v === undefined ? NaN : v) },
        y: { values: yVals.map(v => v === null || v === undefined ? NaN : v) },
        length: Math.max(xVals.length, yVals.length),
        line: {
          color: { option: 'Solid', value: color },
          width: lineWidth,
          dashType: dashType,
          capType: 'rnd',
          compoundType: 'sng',
          joinType: 'round',
          beginType: 'none',
          endType: 'none'
        },
        marker: { option: 'NoMarker' }
      });
      
      chart.series.push(series);
    });
    
    // ============ PREPARE DATA ============
    // Build data array with headers
    const headers = ['Time', ...traces.map((t, i) => t.name || `Series ${i + 1}`)];
    const dataRows = [];
    
    for (let i = 0; i < maxLength; i++) {
      const row = [xValues[i] !== undefined ? xValues[i] : null];
      traces.forEach(trace => {
        row.push(trace.y && trace.y[i] !== undefined ? trace.y[i] : null);
      });
      dataRows.push(row);
    }
    
    // Position chart to the right of the data (after all data columns)
    chart.x = (traces.length + 2) * 64;  // Offset by number of columns + margin
    chart.y = 0;
    
    // Write Data sheet with both data AND chart
    xlsx.writeData([headers, ...dataRows], 'Data', { chart: chart });
    
    // Generate filename
    const safeTitle = chartTitle.replace(/[^a-z0-9]/gi, '_').substring(0, 50);
    const filename = `${safeTitle}_${Date.now()}.xlsx`;
    
    // Save and download the file
    await xlsx.saveAs(filename);
    
  } catch (err) {
    console.error('Excel export failed:', err);
    alert('Failed to export to Excel: ' + err.message);
  }
}

/**
 * Handle "Show Total" checkbox toggle for radionuclides charts.
 * When checked, adds a trace showing the sum of all radionuclide activities.
 * Only applicable when viewing a radionuclides group.
 * 
 * @returns {void}
 */
function toggleShowTotal() {
  if (selectedIsRadionuclidesGroup && selectedDatasetPath) {
    const savedAxis = captureAxisState();
    Promise.resolve().then(() => createRadionuclidesChart(selectedDatasetPath, savedAxis));
  }
}

/**
 * Handle "Show Ratio" checkbox toggle for radionuclides charts.
 * When checked, appends the ratio of max values (thick/thin) to the legend
 * name of thick-line traces.
 * 
 * @returns {void}
 */
function toggleShowRatio() {
  const ratioChecked = getElement('showRatio')?.checked;
  setShowMaxVisible(!ratioChecked);
  if (selectedIsRadionuclidesGroup && selectedDatasetPath) {
    const savedAxis = captureAxisState();
    Promise.resolve().then(() => createRadionuclidesChart(selectedDatasetPath, savedAxis));
  }
}

/**
 * Handle "Show Max" checkbox toggle.
 * When checked, appends the maximum value to each trace's legend name.
 * Re-renders the current chart (single, multi-select, or radionuclides).
 * 
 * @returns {void}
 */
function toggleShowMax() {
  const plotDiv = getElement('plotlyChart');
  if (!plotDiv || !plotDiv.data) {
    return;
  }
  const showMax = getElement('showMax')?.checked;
  const newNames = plotDiv.data.map(trace => {
    if (trace._hiddenFromLegend) return trace.name;
    // Strip any existing " (…)" max suffix added by us.
    // Keep suffixes added by other features (ratio, file-diff) by only
    // removing a trailing parenthesised numeric value we appended.
    let baseName = trace._baseName || trace.name;
    if (showMax && trace.y && trace.y.length > 0) {
      const maxVal = Math.max(...trace.y);
      const formatted = maxVal === 0 || !isFinite(maxVal) ? String(maxVal) : maxVal.toPrecision(3);
      trace._baseName = baseName;
      return `${baseName} (${formatted})`;
    }
    // Unchecked — restore base name
    trace._baseName = baseName;
    return baseName;
  });
  Plotly.restyle(plotDiv, { name: newNames });
}

/**
 * Toggle the confidence interval band display.
 * Adds or removes CI band traces from the current chart.
 * CI band colors match the corresponding mean trace line colors.
 */
async function toggleShowCI() {
  const plotDiv = getElement('plotlyChart');
  if (!plotDiv || !plotDiv.data) {
    return;
  }
  const chartContainer = getElement('plotlyChartContainer');
  
  const showCI = getElement('showCI')?.checked;
  const shouldShowLoader = !!showCI;
  if (shouldShowLoader) {
    showChartLoading(chartContainer, 'Calculating confidence interval...');
    await new Promise(requestAnimationFrame);
    await new Promise(resolve => setTimeout(resolve, 0));
  }
  try {
    // Find existing CI band traces and remove them
    const existingCIIndices = [];
    plotDiv.data.forEach((trace, idx) => {
      if (trace._isCIBand) {
        existingCIIndices.push(idx);
      }
    });
    
    if (existingCIIndices.length > 0) {
      await Plotly.deleteTraces(plotDiv, existingCIIndices);
    }
    
    // If checkbox is now checked, add CI bands for all probabilistic traces
    if (showCI) {
      const ciTraces = [];
      plotDiv.data.forEach((trace) => {
        const hasColumnCI = Array.isArray(trace._ciP5) && Array.isArray(trace._ciP95) && trace._timeData;
        const hasProbCI = trace._isProbabilistic && trace._rawData && trace._timeData;
        if (hasColumnCI || hasProbCI) {
          const p5 = hasColumnCI ? trace._ciP5 : computeProbabilisticPercentile(trace._rawData, trace._timeData, 5);
          const p95 = hasColumnCI ? trace._ciP95 : computeProbabilisticPercentile(trace._rawData, trace._timeData, 95);
          const minLength = Math.min(trace._timeData.length, p5.length, p95.length);
          const timeSlice = trace._timeData.slice(0, minLength);
          const p5Slice = p5.slice(0, minLength);
          const p95Slice = p95.slice(0, minLength);
          
          // Get the trace's line color and convert to semi-transparent fill
          let traceColor = 'rgba(100, 150, 200, 0.2)';
          if (trace.line && trace.line.color) {
            const color = trace.line.color;
            if (color.startsWith('rgba')) {
              traceColor = color.replace(/,[\s]*[\d.]+\s*\)$/, ', 0.2)');
            } else if (color.startsWith('rgb')) {
              traceColor = color.replace(/^rgb\(/, 'rgba(').replace(/\)$/, ', 0.2)');
            } else if (color.startsWith('#')) {
              const hex = color.slice(1);
              const r = parseInt(hex.substr(0, 2), 16);
              const g = parseInt(hex.substr(2, 2), 16);
              const b = parseInt(hex.substr(4, 2), 16);
              traceColor = `rgba(${r}, ${g}, ${b}, 0.2)`;
            }
          }
          
          const ciBandTrace = {
            x: [...timeSlice, ...timeSlice.slice().reverse()],
            y: [...p95Slice, ...p5Slice.slice().reverse()],
            fill: 'tozeroy',
            fillcolor: traceColor,
            line: { color: 'rgba(255, 255, 255, 0)' },
            showlegend: false,
            hoverinfo: 'skip',
            _hiddenFromLegend: true,
            _isCIBand: true,
            mode: 'lines',
            name: 'CI Band'
          };
          ciTraces.push(ciBandTrace);
        }
      });
      
      if (ciTraces.length > 0) {
        await Plotly.addTraces(plotDiv, ciTraces);
      }
    }
  } finally {
    if (shouldShowLoader) {
      hideChartLoading(chartContainer);
    }
  }
}

/**
 * Append the maximum y-value to each trace's legend name.
 * Formats as "name (max)" using 3 significant digits.
 * Skips traces that are hidden from the legend.
 * @param {Object[]} traces - Plotly trace objects (modified in-place)
 */
function annotateTracesWithMax(traces) {
  for (const trace of traces) {
    if (trace._hiddenFromLegend) continue;
    if (!trace.y || trace.y.length === 0) continue;
    trace._baseName = trace.name;
    const maxVal = Math.max(...trace.y);
    const formatted = maxVal === 0 || !isFinite(maxVal) ? String(maxVal) : maxVal.toPrecision(3);
    trace.name = `${trace.name} (${formatted})`;
  }
}


/* ==========================================================================
   9. CHART CREATION
   ========================================================================== */

/**
 * Create a Plotly chart for a single time-dependent dataset.
 * Plots the dataset from all enabled files as separate traces,
 * allowing comparison across files.
 * 
 * @param {string} path - HDF5 path to the dataset
 * @returns {void}
 */
function createPlotlyChart(path) {
  if (!_axesLocked) resetPresetDropdown();
  const chartContainer = getElement('plotlyChartContainer');
  showChartLoading(chartContainer);
  const plotDiv = getElement('plotlyChart');

  let wasCIChecked = false;
  try {
    const ciCheckbox = getElement('showCI');
    if (ciCheckbox) {
      wasCIChecked = !!ciCheckbox.checked;
    }
  } catch (e) {
    // Ignore missing CI control during initial render.
  }

  plotDiv.innerHTML = '';

  // Hide "Show Total" and "Show Ratio" checkboxes (only for radionuclides groups)
  setShowTotalVisible(false);
  setShowRatioVisible(false);
  setShowMaxVisible(true);
  setShowCIVisible(false);  // Will be enabled if we have probabilistic data

  const traces = [];
  const enabledFiles = getEffectiveFiles();
  const probDataInfo = [];  // Track raw data for probabilistic datasets
  let hasProbabilistic = false;

  let timeUnit = '';
  let yAxisUnit = '';
  let yAxisName = path.split('/').pop();

  if (enabledFiles.length > 0) {
    const firstFile = loadedFiles[enabledFiles[0]];
    timeUnit = getTimeUnit(firstFile);

    // Get y-axis unit from the first file's dataset (best-effort)
    try {
      const dataset = FileService.get(firstFile, path);
      const unit = getAttr(dataset, 'unit');
      if (unit !== undefined && unit !== null) yAxisUnit = unit;
    } catch (e) {
      console.warn('Could not read unit from dataset:', e);
    }
  }

  // Build traces for each enabled file
  for (const fileKey of enabledFiles) {
    const file = loadedFiles[fileKey];

    if (!checkDatasetExistsInFile(file, path)) {
      continue;
    }

    try {
      const dataset = FileService.get(file, path);

      if (!isTimeDependent(dataset)) {
        continue;
      }

      const timeData = getTimeData(file);
      if (!timeData) {
        console.warn(`No /time dataset found in ${fileKey}`);
        continue;
      }

      let yData;
      if (typeof dataset.value !== 'undefined') {
        yData = dataset.value;
      } else if (typeof dataset.toArray === 'function') {
        yData = dataset.toArray();
      }

      if (yData) {
        const normalizedRawData = PDFSampler.normalizeDataArray(yData);
        let yArray = normalizedRawData;
        let isProbabilistic = false;
        let ciFromColumns = null;

        const colStats = getColumnStatisticsSeries(dataset, normalizedRawData, timeData);
        if (colStats && Array.isArray(colStats.meanSeries)) {
          yArray = colStats.meanSeries;
          if (Array.isArray(colStats.p5Series) && Array.isArray(colStats.p95Series)) {
            hasProbabilistic = true;
            ciFromColumns = { p5: colStats.p5Series, p95: colStats.p95Series };
          }
        }

        // Handle probabilistic data (take mean)
        if (!colStats && checkIsProbabilistic(dataset)) {
          isProbabilistic = true;
          hasProbabilistic = true;
          // Store raw data for CI band computation later
          probDataInfo.push({ yArray, timeData: timeData.slice() });
          yArray = computeProbabilisticMean(yArray, timeData);
        }

        // Handle length mismatch
        const minLength = Math.min(timeData.length, yArray.length);
        if (timeData.length !== yArray.length) {
          console.warn(`Time data length (${timeData.length}) doesn't match data length (${yArray.length}) for ${fileKey}`);
        }

        const traceObj = ChartService.timeSeriesTrace({ x: timeData.slice(0, minLength), y: yArray.slice(0, minLength), name: buildTraceName(yAxisName, path, fileKey, [path], enabledFiles) });
        traceObj._isProbabilistic = isProbabilistic || !!ciFromColumns;
        if (isProbabilistic) {
          // Store raw data and time data on the trace for CI computation
          traceObj._rawData = normalizedRawData;
          traceObj._timeData = timeData.slice(0, minLength);
        } else if (ciFromColumns) {
          traceObj._ciP5 = ciFromColumns.p5.slice(0, minLength);
          traceObj._ciP95 = ciFromColumns.p95.slice(0, minLength);
          traceObj._timeData = timeData.slice(0, minLength);
        }
        traces.push(traceObj);
      }
    } catch (e) {
      console.error(`Error creating trace for ${fileKey}:`, e);
    }
  }

  // Render chart if we have data
  if (traces.length > 0) {
    // Show CI checkbox if we have probabilistic data
    if (hasProbabilistic) {
      setShowCIVisible(true);
    }

    // Annotate legend with max values if "Show Max" is checked
    const showMaxCb = getElement('showMax');
    if (showMaxCb && showMaxCb.checked) {
      annotateTracesWithMax(traces);
    }

    const { xScale, yScale } = getChartScales();

    let yAxisTitle = 'Value';
    if (yAxisUnit) {
      yAxisTitle = `Value (${yAxisUnit})`;
    }

    const paths = [path];
    const layout = ChartService.createBaseLayout({
      title: path,
      xAxisTitle: timeUnit ? `Time (${timeUnit})` : 'Time',
      yAxisTitle,
      xScale,
      yScale
    });
    layout.margin.r = 200; // Extra room for longer legend names
    _applyLockedAxes(layout);

    // Show CI checkbox if we have probabilistic data
    setShowCIVisible(hasProbabilistic);
    
    const config = getPlotlyConfig('multi_dataset_chart');

    currentChartData = { traces, layout, paths };
    if (chartContainer) chartContainer.classList.add('visible');
    if (dynamicLegendEnabled) {
      assignLegendRanks(traces);
    }
    Plotly.newPlot('plotlyChart', traces, layout, config).then(() => {
      const pDiv = getElement('plotlyChart');
      setupDynamicLegend(pDiv);
      setupPresetRelayoutSync(pDiv);
      refreshDynamicLegend();
      snapLogRangeToDecades(pDiv);
      // Restore CI state if we have probabilistic data and it was previously checked
      if (hasProbabilistic && wasCIChecked) {
        const ciCheckboxNew = getElement('showCI');
        if (ciCheckboxNew) {
          ciCheckboxNew.checked = true;
          toggleShowCI();
        }
      }
      hideChartLoading(chartContainer);
    });
  } else {
    hideChart();
  }
}

/**
 * Create a Plotly chart comparing multiple selected datasets.
 * Each selection item carries its own fileKey so cross-file comparisons work.
 * 
 * Used in multi-select mode (Ctrl+click on datasets, possibly from different files).
 * 
 * @param {{path: string, fileKey: string|null}[]} items - Array of selected dataset items
 * @returns {void}
 */
function createMultiDatasetChart(items) {
  if (!_axesLocked) resetPresetDropdown();
  const plotDiv = getElement('plotlyChart');
  const chartContainer = getElement('plotlyChartContainer');
  showChartLoading(chartContainer);
  
    // Save CI state and checkbox reference before clearing
    let wasCIChecked = false;
    try {
      const ciCheckbox = getElement('showCI');
      if (ciCheckbox) {
        wasCIChecked = ciCheckbox.checked || false;
      }
    } catch (e) {
      // If checkbox doesn't exist yet, that's fine
    }
  
  if (plotDiv) plotDiv.innerHTML = '';
  
  // Hide "Show Total" and "Show Ratio" checkboxes (only for radionuclides groups)
  setShowTotalVisible(false);
  setShowRatioVisible(false);
  setShowMaxVisible(true);
  setShowCIVisible(false);  // Will be enabled if we have probabilistic data
  
  const traces = [];
  const yAxisUnits = new Set();
  const probDataInfo = [];  // Track raw data for probabilistic datasets
  let hasProbabilistic = false;
  let timeUnit = '';
  const meanTracesByIndex = {};  // Map CI trace back to mean trace for color matching
  
  // Normalize items: if fileKey is null (intersect mode), expand to all enabled files
  // Deduplicate so each (path, fileKey) pair is unique
  const normalizedItems = [];
  const seen = new Set();
  for (const item of items) {
    if (item.fileKey && loadedFiles[item.fileKey]) {
      const key = item.path + '|' + item.fileKey;
      if (!seen.has(key)) {
        normalizedItems.push(item);
        seen.add(key);
      }
    } else {
      // Intersect mode — expand to all enabled files
      for (const fk of getEnabledFiles()) {
        const key = item.path + '|' + fk;
        if (!seen.has(key)) {
          normalizedItems.push({ path: item.path, fileKey: fk });
          seen.add(key);
        }
      }
    }
  }
  
  // Collect unique file keys from items
  const uniqueFileKeys = [...new Set(normalizedItems.map(d => d.fileKey).filter(Boolean))];
  if (uniqueFileKeys.length === 0) return hideChart();
  
  // Use first file for time unit
  const firstFile = loadedFiles[uniqueFileKeys[0]];
  if (firstFile) timeUnit = getTimeUnit(firstFile);
  
  // Color palette for different datasets
  const colors = [
    '#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6',
    '#1abc9c', '#e67e22', '#34495e', '#c0392b', '#2980b9',
    '#27ae60', '#f1c40f', '#8e44ad', '#16a085', '#d35400'
  ];
  
  // Unique paths for color assignment
  const uniquePaths = [...new Set(normalizedItems.map(d => d.path))];
  const multiFile = uniqueFileKeys.length > 1;
  const multiPath = uniquePaths.length > 1;
  
  // Pre-compute context arrays for buildTraceName
  const allPaths = normalizedItems.map(d => d.path);
  const allFileKeys = normalizedItems.map(d => d.fileKey);

  for (const [itemIndex, item] of normalizedItems.entries()) {
    const { path, fileKey } = item;
    const datasetName = path.split('/').pop();
    const pathIdx = uniquePaths.indexOf(path);
    const baseColor = colors[pathIdx % colors.length];
    
    const file = loadedFiles[fileKey];
    if (!file || !checkDatasetExistsInFile(file, path)) continue;
    
    try {
      const dataset = FileService.get(file, path);
      if (!isTimeDependent(dataset)) continue;
      
      // Get unit
      let yAxisUnit = '';
      const unitVal = getAttr(dataset, 'unit');
      if (unitVal !== undefined && unitVal !== null) {
        yAxisUnit = unitVal;
        yAxisUnits.add(yAxisUnit);
      }
      
      const timeData = getTimeData(file);
      if (!timeData) {
        console.warn(`No /time dataset found in ${fileKey}`);
        continue;
      }
      
      let yData;
      if (typeof dataset.value !== 'undefined') {
        yData = dataset.value;
      } else if (typeof dataset.toArray === 'function') {
        yData = dataset.toArray();
      }
      
      if (yData) {
        const normalizedRawData = PDFSampler.normalizeDataArray(yData);
        let yArray = normalizedRawData;
        let isProbabilistic = false;
        let ciFromColumns = null;

        const colStats = getColumnStatisticsSeries(dataset, normalizedRawData, timeData);
        if (colStats && Array.isArray(colStats.meanSeries)) {
          yArray = colStats.meanSeries;
          if (Array.isArray(colStats.p5Series) && Array.isArray(colStats.p95Series)) {
            hasProbabilistic = true;
            ciFromColumns = { p5: colStats.p5Series, p95: colStats.p95Series };
          }
        }
        
        // Handle probabilistic data (take mean)
        if (!colStats && checkIsProbabilistic(dataset)) {
          isProbabilistic = true;
          hasProbabilistic = true;
          // Store raw data for CI band computation later
          probDataInfo.push({ yArray, timeData: timeData.slice() });
          yArray = computeProbabilisticMean(yArray, timeData);
        }

        const minLength = Math.min(timeData.length, yArray.length);
        const trimmedTimeData = timeData.slice(0, minLength);
        const trimmedYData = yArray.slice(0, minLength);
        
        // Build trace name — harmonized via buildTraceName
        const traceName = buildTraceName(datasetName, path, fileKey, allPaths, allFileKeys);
        let lineWidth = 2;
        let lineDash = 'solid';
        if (multiFile) {
          const fileIdx = uniqueFileKeys.indexOf(fileKey);
          const dashStyles = ['solid', 'dash', 'dot', 'dashdot'];
          lineDash = dashStyles[fileIdx % dashStyles.length];
          lineWidth = 1.5;
        }
        const traceObj = ChartService.timeSeriesTrace({ x: trimmedTimeData, y: trimmedYData, name: traceName, line: { color: baseColor, dash: lineDash, width: lineWidth }, hovertemplate: `<b>${traceName}</b><br>Time: %{x}<br>Value: %{y}<extra></extra>` });
        traceObj._isProbabilistic = isProbabilistic || !!ciFromColumns;
        if (isProbabilistic) {
          // Store raw data and time data on the trace for CI computation
          traceObj._rawData = normalizedRawData;
          traceObj._timeData = trimmedTimeData;
        } else if (ciFromColumns) {
          traceObj._ciP5 = ciFromColumns.p5.slice(0, minLength);
          traceObj._ciP95 = ciFromColumns.p95.slice(0, minLength);
          traceObj._timeData = trimmedTimeData;
        }
        traces.push(traceObj);
      }
    } catch (e) {
      console.error(`Error creating trace for ${path} in ${fileKey}:`, e);
    }
  }
  
  if (traces.length > 0) {
    // Show CI checkbox if we have probabilistic data
    if (hasProbabilistic) {
      setShowCIVisible(true);
    }

    // Annotate legend with max values if "Show Max" is checked
    const showMaxCb = getElement('showMax');
    if (showMaxCb && showMaxCb.checked) {
      annotateTracesWithMax(traces);
    }

    const { xScale, yScale } = getChartScales();
    
    let yAxisTitle = 'Value';
    if (yAxisUnits.size === 1) {
      yAxisTitle = `Value (${Array.from(yAxisUnits)[0]})`;
    } else if (yAxisUnits.size > 1) {
      yAxisTitle = `Value (${Array.from(yAxisUnits).join(', ')})`;
    }
    
    const paths = normalizedItems.map(d => d.path);
    const layout = ChartService.createBaseLayout({
      title: `Comparing ${normalizedItems.length} dataset${normalizedItems.length > 1 ? 's' : ''}`,
      xAxisTitle: timeUnit ? `Time (${timeUnit})` : 'Time',
      yAxisTitle,
      xScale,
      yScale
    });
    layout.margin.r = 200; // Extra room for longer legend names
    _applyLockedAxes(layout);
    
    const config = getPlotlyConfig('multi_dataset_chart');

    currentChartData = { traces, layout, paths };
    const container = getElement('plotlyChartContainer');
    if (container) container.classList.add('visible');
    if (dynamicLegendEnabled) {
      assignLegendRanks(traces);
    }
      Plotly.newPlot('plotlyChart', traces, layout, config).then(() => {
        const pDiv = getElement('plotlyChart');
        setupDynamicLegend(pDiv);
        setupPresetRelayoutSync(pDiv);
        refreshDynamicLegend();
        snapLogRangeToDecades(pDiv);
        // Restore CI state if we have probabilistic data and it was previously checked
        if (hasProbabilistic && wasCIChecked) {
          const ciCheckboxNew = getElement('showCI');
          if (ciCheckboxNew) {
            ciCheckboxNew.checked = true;
            toggleShowCI();
          }
        }
        hideChartLoading(container);
      });
  } else {
    hideChart();
  }
}

/**
 * Create a Plotly chart for a radionuclides data group.
 * Plots all child datasets (isotopes) with predefined line styles.
 * 
 * Features:
 * - Each isotope uses its characteristic color and dash pattern
 * - "Show Total" checkbox adds a summed trace
 * - Supports multi-file comparison with thinner lines for secondary files
 * 
 * @param {string} path - HDF5 path to the radionuclides group
 * @returns {void}
 */
async function createRadionuclidesChart(path, savedAxisState) {
  if (!_axesLocked) resetPresetDropdown();
  const plotDiv = getElement('plotlyChart');
  const chartContainer = getElement('plotlyChartContainer');
  showChartLoading(chartContainer);
  let wasCIChecked = false;
  try {
    const ciCheckbox = getElement('showCI');
    if (ciCheckbox) {
      wasCIChecked = !!ciCheckbox.checked;
    }
  } catch (e) {
    // Ignore missing CI control during initial render.
  }
  try {
  if (plotDiv) plotDiv.innerHTML = '';
  // Yield to browser for immediate UI update before heavy processing (cross-browser)
  await new Promise(requestAnimationFrame);
  await new Promise(resolve => setTimeout(resolve, 0));
  // Show "Show Total" checkbox for radionuclides groups
  setShowTotalVisible(true);
  setShowMaxVisible(true);
  
  const traces = [];
  const enabledFiles = getEffectiveFiles();
  
  // Show "Show Ratio" checkbox only when exactly 2 files are enabled (thick + thin lines)
  // and secondary file has data for this path — will be set after building traces
  const hasTwoFiles = enabledFiles.length === 2;
  setShowRatioVisible(false);
  
  // Store data for computing total
  const totalDataByFile = {};

  /**
   * Convert probabilistic raw data into per-timestep realization arrays.
   * Returns null when the shape is not probabilistic.
   * @param {Array} rawData
   * @param {Array} timeData
   * @returns {Array<Array<number>>|null}
   */
  function toProbabilisticTimeSlices(rawData, timeData) {
    if (!Array.isArray(rawData) || !timeData || timeData.length === 0) {
      return null;
    }
    if (Array.isArray(rawData[0])) {
      return rawData.slice(0, timeData.length).map(timeSlice => {
        if (!Array.isArray(timeSlice)) return [PDFSampler.toNumber(timeSlice)];
        return timeSlice.map(PDFSampler.toNumber);
      });
    }
    if (rawData.length > timeData.length && rawData.length % timeData.length === 0) {
      const numRealizations = Math.floor(rawData.length / timeData.length);
      const timeSlices = [];
      for (let t = 0; t < timeData.length; t++) {
        const values = [];
        for (let r = 0; r < numRealizations; r++) {
          values.push(PDFSampler.toNumber(rawData[t * numRealizations + r]));
        }
        timeSlices.push(values);
      }
      return timeSlices;
    }
    return null;
  }
  
  // Track the starting index of each file's traces in the traces array
  const fileTraceStartIndex = {};
  
  // Track if any probabilistic data exists
  let hasProbabilistic = false;

  let timeUnit = '';
  let yAxisUnit = '';
  let yAxisName = path.split('/').pop();
  
  if (enabledFiles.length > 0) {
    const firstFile = loadedFiles[enabledFiles[0]];
    timeUnit = getTimeUnit(firstFile);
  }
  
  // Build traces for each file and each radionuclide
  for (const fileKey of enabledFiles) {
    const file = loadedFiles[fileKey];
    
    // Record where this file's traces begin
    fileTraceStartIndex[fileKey] = traces.length;
    
    if (!checkDatasetExistsInFile(file, path)) {
      continue;
    }
    
    try {
      const group = FileService.get(file, path);
      if (!group || group.type.toLowerCase() !== 'group') {
        continue;
      }
      
      const timeData = getTimeData(file);
      if (!timeData) {
        console.warn(`No /time dataset found in ${fileKey}`);
        continue;
      }
      
      let datasetKeys = [];
      try {
        if (typeof group.keys === 'function') {
          datasetKeys = Array.from(group.keys());
        }
      } catch (e) {
        console.error('Error getting dataset keys:', e);
        continue;
      }
      
      for (const datasetKey of datasetKeys) {
        try {
          const dataset = group.get(datasetKey);
          if (!dataset || dataset.type.toLowerCase() !== 'dataset') {
            continue;
          }
          let yData;
          if (typeof dataset.value !== 'undefined') {
            yData = dataset.value;
          } else if (typeof dataset.toArray === 'function') {
            yData = dataset.toArray();
          }
          if (yData) {
            const normalizedRawData = PDFSampler.normalizeDataArray(yData);
            let yArray = normalizedRawData;
            let isProbabilistic = false;
            let ciFromColumns = null;

            const colStats = getColumnStatisticsSeries(dataset, normalizedRawData, timeData);
            if (colStats && Array.isArray(colStats.meanSeries)) {
              yArray = colStats.meanSeries;
              if (Array.isArray(colStats.p5Series) && Array.isArray(colStats.p95Series)) {
                hasProbabilistic = true;
                ciFromColumns = { p5: colStats.p5Series, p95: colStats.p95Series };
              }
            }
            // Handle probabilistic data
            if (!colStats && checkIsProbabilistic(dataset)) {
              isProbabilistic = true;
              hasProbabilistic = true;
              yArray = computeProbabilisticMean(yArray, timeData);
            }
            const minLength = Math.min(timeData.length, yArray.length);
            const trimmedTimeData = timeData.slice(0, minLength);
            const trimmedYData = yArray.slice(0, minLength);
            // Store data for computing total
            if (!totalDataByFile[fileKey]) {
              totalDataByFile[fileKey] = {
                timeData: trimmedTimeData,
                dataArrays: [],
                probabilisticSlices: null
              };
            }
            totalDataByFile[fileKey].dataArrays.push(trimmedYData);
            if (isProbabilistic) {
              const datasetSlices = toProbabilisticTimeSlices(normalizedRawData, trimmedTimeData);
              if (datasetSlices) {
                if (!totalDataByFile[fileKey].probabilisticSlices) {
                  totalDataByFile[fileKey].probabilisticSlices = datasetSlices.map((values, idx) => {
                    const deterministicBase = totalDataByFile[fileKey].dataArrays.length > 1
                      ? totalDataByFile[fileKey].dataArrays
                          .slice(0, totalDataByFile[fileKey].dataArrays.length - 1)
                          .reduce((sum, arr) => sum + (arr[idx] || 0), 0)
                      : 0;
                    return values.map(v => v + deterministicBase);
                  });
                } else {
                  const totalSlices = totalDataByFile[fileKey].probabilisticSlices;
                  const compatible = totalSlices.length === datasetSlices.length
                    && totalSlices.every((values, idx) => values.length === datasetSlices[idx].length);
                  if (compatible) {
                    for (let t = 0; t < totalSlices.length; t++) {
                      for (let r = 0; r < totalSlices[t].length; r++) {
                        totalSlices[t][r] += datasetSlices[t][r];
                      }
                    }
                  } else {
                    totalDataByFile[fileKey].probabilisticSlices = null;
                  }
                }
              }
            } else if (totalDataByFile[fileKey].probabilisticSlices) {
              const totalSlices = totalDataByFile[fileKey].probabilisticSlices;
              for (let t = 0; t < Math.min(totalSlices.length, trimmedYData.length); t++) {
                for (let r = 0; r < totalSlices[t].length; r++) {
                  totalSlices[t][r] += trimmedYData[t];
                }
              }
            }
            // Get line style for this radionuclide
            const lineStyle = getLineStyle(datasetKey);
            let traceName = datasetKey;
            let lineWidth = lineStyle.width;
            if (enabledFiles.length > 1 && enabledFiles.indexOf(fileKey) > 0) {
              traceName = `${datasetKey} (${filenameDiff(enabledFiles[0], fileKey)})`;
              lineWidth = lineWidth / 2;
            }
            const traceObj = ChartService.timeSeriesTrace({ x: trimmedTimeData, y: trimmedYData, name: traceName, line: { color: lineStyle.color, dash: lineStyle.dash, width: lineWidth }, _datasetKey: datasetKey });
            traceObj._isProbabilistic = isProbabilistic || !!ciFromColumns;
            if (isProbabilistic) {
              // Store raw data and time data on the trace for CI computation
              traceObj._rawData = normalizedRawData;
              traceObj._timeData = trimmedTimeData;
            } else if (ciFromColumns) {
              traceObj._ciP5 = ciFromColumns.p5.slice(0, minLength);
              traceObj._ciP95 = ciFromColumns.p95.slice(0, minLength);
              traceObj._timeData = trimmedTimeData;
            }
            traces.push(traceObj);
          }
          // Yield to browser for UI update after each dataset
          await Promise.resolve();
        } catch (e) {
          console.error(`Error creating trace for ${datasetKey} in ${fileKey}:`, e);
        }
      }
    } catch (e) {
      console.error(`Error processing group for ${fileKey}:`, e);
    }
  }
  
  // Now that traces are built, show "Show Ratio" only if both files contributed data
  if (hasTwoFiles) {
    const secondaryFile = enabledFiles[1];
    const secondaryStart = fileTraceStartIndex[secondaryFile] != null ? fileTraceStartIndex[secondaryFile] : traces.length;
    const secondaryHasTraces = secondaryStart < traces.length;
    setShowRatioVisible(secondaryHasTraces);
  }

  // Collect max values per radionuclide per file (needed for ratio display)
  const showRatioCheckbox = getElement('showRatio');
  const showRatioChecked = hasTwoFiles && showRatioCheckbox && showRatioCheckbox.checked;

  // Hide "Show Max" when ratio is active
  setShowMaxVisible(!showRatioChecked);
  const maxByFileAndName = {}; // { datasetKey: { fileKey: maxVal } }
  if (showRatioChecked) {
    for (const fileKey of enabledFiles) {
      const fileData = totalDataByFile[fileKey];
      if (!fileData) continue;
      const file = loadedFiles[fileKey];
      const group = FileService.get(file, path);
      let datasetKeys = [];
      try {
        if (typeof group.keys === 'function') {
          datasetKeys = Array.from(group.keys());
        }
      } catch (e) { /* ignore */ }
      // Match datasetKeys to dataArrays by index
      for (let i = 0; i < datasetKeys.length && i < fileData.dataArrays.length; i++) {
        const key = datasetKeys[i];
        const arr = fileData.dataArrays[i];
        const maxVal = Math.max(...arr);
        if (!maxByFileAndName[key]) maxByFileAndName[key] = {};
        maxByFileAndName[key][fileKey] = maxVal;
      }
    }
  }

  const primaryFile = enabledFiles[0];
  const secondaryFile = hasTwoFiles ? enabledFiles[1] : null;

  /**
   * Format a ratio value to a display string (3 significant digits).
   * @param {number} ratio
   * @returns {string}
   */
  function formatRatio(ratio) {
    if (ratio === 0 || !isFinite(ratio)) return ratio.toString();
    return ratio.toPrecision(3);
  }

  // Add total traces, each at the top of its corresponding file's group in the legend
  const showTotalCheckbox = getElement('showTotal');
  if (showTotalCheckbox && showTotalCheckbox.checked) {
    // Compute total per file and collect total max values for ratio
    const totalMaxByFile = {}; // { fileKey: maxTotalValue }
    const totalTracesByFile = {}; // { fileKey: traceObject }
    for (const fileKey of Object.keys(totalDataByFile)) {
      const fileData = totalDataByFile[fileKey];
      if (fileData.dataArrays.length > 0) {
        const timeData = fileData.timeData;
        const totalY = new Array(timeData.length).fill(0);
        
        // Sum all data arrays
        for (const dataArray of fileData.dataArrays) {
          for (let i = 0; i < Math.min(dataArray.length, totalY.length); i++) {
            totalY[i] += dataArray[i];
          }
        }
        
        totalMaxByFile[fileKey] = Math.max(...totalY);

        let traceName = 'Total';
        let lineWidth = 2;
        
        if (enabledFiles.length > 1 && enabledFiles.indexOf(fileKey) > 0) {
          traceName = `Total (${filenameDiff(enabledFiles[0], fileKey)})`;
          lineWidth = 1;
        }
        
        totalTracesByFile[fileKey] = {
          x: timeData,
          y: totalY,
          mode: 'lines',
          name: traceName,
          line: {
            color: '#000000',
            dash: 'solid',
            width: lineWidth
          },
          type: 'scatter',
          _datasetKey: '__total__'
        };

        if (fileData.probabilisticSlices) {
          totalTracesByFile[fileKey]._isProbabilistic = true;
          totalTracesByFile[fileKey]._rawData = fileData.probabilisticSlices;
          totalTracesByFile[fileKey]._timeData = timeData;
        }
      }
    }

    // If Show Ratio is checked, append ratio to the primary Total trace name
    if (showRatioChecked && secondaryFile) {
      const t = totalTracesByFile[primaryFile];
      if (t && t.name === 'Total') {
        const maxPrimary = totalMaxByFile[primaryFile];
        const maxSecondary = totalMaxByFile[secondaryFile];
        if (maxSecondary != null && maxSecondary !== 0) {
          t.name = `Total (${formatRatio(maxPrimary / maxSecondary)})`;
        } else if (maxSecondary === 0 && maxPrimary > 0) {
          t.name = `Total (∞)`;
        }
      }
    }

    // Insert each total trace at the beginning of its file's group.
    // Process files in reverse order so earlier splice positions stay valid.
    const filesWithTotals = enabledFiles.filter(fk => totalTracesByFile[fk]);
    for (let i = filesWithTotals.length - 1; i >= 0; i--) {
      const fk = filesWithTotals[i];
      const insertIdx = fileTraceStartIndex[fk] != null ? fileTraceStartIndex[fk] : traces.length;
      traces.splice(insertIdx, 0, totalTracesByFile[fk]);
    }
  }

  // Update thick-line trace names with ratio of max values if "Show Ratio" is checked
  if (showRatioChecked) {
    for (const trace of traces) {
      // Thick-line traces are those from the primary file (no fileKey suffix, not Total)
      for (const datasetKey of Object.keys(maxByFileAndName)) {
        if (trace.name === datasetKey) {
          const maxPrimary = maxByFileAndName[datasetKey][primaryFile];
          const maxSecondary = maxByFileAndName[datasetKey][secondaryFile];
          if (maxSecondary != null && maxSecondary !== 0) {
            trace.name = `${datasetKey} (${formatRatio(maxPrimary / maxSecondary)})`;
          } else if (maxSecondary === 0 && maxPrimary > 0) {
            trace.name = `${datasetKey} (∞)`;
          }
          break;
        }
      }
    }
    
    // Hide thin-line (secondary file) traces from legend — keep them visible in chart.
    // Secondary file traces have halved line widths compared to primary ones.
    for (const trace of traces) {
      const w = trace.line && trace.line.width;
      // Thick (primary) traces have width >= 2, thin (secondary) have width < 2
      // Total traces: primary=2, secondary=1. Radionuclide traces: primary=original, secondary=original/2.
      // We keep ratio-annotated traces and primary Total in the legend.
      if (w != null && w < 2) {
        trace.showlegend = false;
        trace._hiddenFromLegend = true; // preserve across dynamic legend updates
      }
    }
  }
  
  // Render chart if we have traces
  if (traces.length > 0) {
    // Show CI checkbox if we have probabilistic data
    setShowCIVisible(hasProbabilistic);
    
    // Annotate legend with max values if "Show Max" is checked and ratio is not active
    if (!showRatioChecked) {
      const showMaxCb = getElement('showMax');
      if (showMaxCb && showMaxCb.checked) {
        annotateTracesWithMax(traces);
      }
    }

    // Get unit from group
    const firstFile = loadedFiles[enabledFiles[0]];
    try {
      const group = firstFile.get(path);
      if (group && group.attrs && typeof group.attrs === 'object') {
        for (const attrName in group.attrs) {
          if (attrName === 'unit') {
            const attrObj = group.attrs[attrName];
            if (attrObj && attrObj.value !== null && typeof attrObj.value !== 'undefined') {
              yAxisUnit = attrObj.value;
            }
          }
        }
      }
    } catch (e) {
      console.warn('Could not read unit from group:', e);
    }
    
    const { xScale, yScale } = getChartScales();
    const yAxisTitle = yAxisUnit ? `${yAxisName} (${yAxisUnit})` : yAxisName;
    
    const layout = ChartService.createBaseLayout({
      title: path,
      xAxisTitle: timeUnit ? `Time (${timeUnit})` : 'Time',
      yAxisTitle,
      xScale,
      yScale
    });
    
    // Preserve axis ranges when toggling controls (Show Total, Show Ratio)
    applyAxisState(layout, savedAxisState);
    _applyLockedAxes(layout);
    
    renderChart(traces, layout, path, () => {
      if (hasProbabilistic && wasCIChecked) {
        const ciCheckbox = getElement('showCI');
        if (ciCheckbox) {
          ciCheckbox.checked = true;
          toggleShowCI();
        }
      }
    });
  } else {
    hideChartLoading(chartContainer);
    hideChart();
  }
  } catch (err) {
    console.error('createRadionuclidesChart failed:', err);
    hideChartLoading(chartContainer);
    hideChart();
  }
}

/**
 * Get standard Plotly configuration with custom toolbar buttons.
 * Configures the mode bar with:
 * - Copy to clipboard button (PNG export)
 * - Download CSV button (data export)
 * - Download Excel button (xlsx export)
 * - Standard Plotly zoom/pan/reset tools
 * - SVG export configuration
 * 
 * @param {string} filename - Base filename for exported images/data
 * @returns {Object} Plotly config object
 */
function getPlotlyConfig(filename) {
  return {
    displayLogo: false,
    /* some versions of plotly check lowercase name */
    displaylogo: false,
    scrollZoom: true,
    showLink: false,
    plotlyServerURL: "https://chart-studio.plotly.com",
    modeBarButtonsToRemove: ['resetScale2d', 'toImage'],
    modeBarButtonsToAdd: [
      'v1hovermode',
      {
        name: 'Download plot as svg',
        icon: Plotly.Icons.camera,
        click: function(gd) {
          const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
          const origPaper = gd.layout.paper_bgcolor;
          const origPlot  = gd.layout.plot_bgcolor;
          const opts = { format: 'svg', filename: filename, height: 600, width: 800, scale: 1 };
          if (!isDark) {
            Plotly.relayout(gd, { paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)' }).then(function() {
              return Plotly.downloadImage(gd, opts);
            }).then(function() {
              return Plotly.relayout(gd, { paper_bgcolor: origPaper, plot_bgcolor: origPlot });
            });
          } else {
            Plotly.downloadImage(gd, opts);
          }
        }
      },
      {
        name: 'Copy chart to clipboard',
        icon: {
          width: 500,
          height: 600,
          path: 'M224 0c-35.3 0-64 28.7-64 64V288v64 64c0 35.3 28.7 64 64 64H448c35.3 0 64-28.7 64-64V288 160 64c0-35.3-28.7-64-64-64H224zm0 64H448V160H224V64zM160 448c0 17.7-14.3 32-32 32H64c-17.7 0-32-14.3-32-32V384H160v64zm0-96H32V288H160v64zM32 240V176H160v64H32zM160 128V64h32v64H160z'
        },
        click: function(gd) {
          EventBus.emit('toolbar:copy-chart');
        }
      },
      {
        name: 'Download data as CSV',
        icon: {
          width: 512,
          height: 512,
          path: 'M288 32c0-17.7-14.3-32-32-32s-32 14.3-32 32V274.7l-73.4-73.4c-12.5-12.5-32.8-12.5-45.3 0s-12.5 32.8 0 45.3l128 128c12.5 12.5 32.8 12.5 45.3 0l128-128c12.5-12.5 12.5-32.8 0-45.3s-32.8-12.5-45.3 0L288 274.7V32zM64 352c-35.3 0-64 28.7-64 64v32c0 35.3 28.7 64 64 64H448c35.3 0 64-28.7 64-64V416c0-35.3-28.7-64-64-64H346.5l-45.3 45.3c-25 25-65.5 25-90.5 0L165.5 352H64zm368 56a24 24 0 1 1 0 48 24 24 0 1 1 0-48z'
        },
        click: function(gd) {
          EventBus.emit('toolbar:download-csv');
        }
      },
      {
        name: 'Download data and chart in Excel',
        icon: {
          width: 384,
          height: 512,
          path: 'M64 0C28.7 0 0 28.7 0 64V448c0 35.3 28.7 64 64 64H320c35.3 0 64-28.7 64-64V160H256c-17.7 0-32-14.3-32-32V0H64zM256 0V128H384L256 0zM155.7 250.2L192 302.1l36.3-51.9c7.6-10.9 22.6-13.5 33.4-5.9s13.5 22.6 5.9 33.4L221.3 344l46.4 66.2c7.6 10.9 5 25.8-5.9 33.4s-25.8 5-33.4-5.9L192 385.8l-36.3 51.9c-7.6 10.9-22.6 13.5-33.4 5.9s-13.5-22.6-5.9-33.4L162.7 344l-46.4-66.2c-7.6-10.9-5-25.8 5.9-33.4s25.8-5 33.4 5.9z'
        },
        click: function(gd) {
          EventBus.emit('toolbar:download-excel');
        }
      }
    ],
    responsive: true
  };
}


