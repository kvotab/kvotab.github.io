/* ==========================================================================
   RB CHART - saved axis presets and the preset manager dialog
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
  } catch (_) { ignoreFailure('loadPresets', _); }
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
  if (!currentChartData) { notifyUser('Draw a chart first — there is nothing to capture yet.'); return; }
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

  /*
    Escaped, not just stringified. These fields look numeric but nothing
    enforces that: importPresets stores whatever JSON it is handed after
    checking only that id and name exist, so xMin can be a string, and it is
    interpolated straight into value="…" below. A preset file with
    xMin: '" autofocus onfocus=… x="' broke out of the attribute.
  */
  const fmtVal = (v) => (v == null ? '' : kvotEscapeHtml(v));

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

/*
  Kept as a name the call sites already use, but delegating: this escaped &, "
  and < and left ' and > alone, which is safe only for as long as every
  attribute it feeds is written with double quotes. kvot-safe.js does all five.
*/
function _escAttr(s) {
  return kvotEscapeHtml(s);
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
  if (!nameVal) { notifyUser('Give the preset a name before saving.'); return; }

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
  if (!currentChartData) { notifyUser('Draw a chart first — there is nothing to capture yet.'); return; }
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
    /* A preset file is a few kilobytes of JSON; anything large is a mistake. */
    const size = kvotFileTooLarge(file, 4 * 1024 * 1024);
    if (size.tooLarge) { notifyUser(size.reason); return; }
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const imported = JSON.parse(reader.result);
        if (!Array.isArray(imported)) {
          notifyUser('That file does not contain a list of presets.');
          return;
        }
        for (const p of imported) {
          if (!p.id || !p.name) {
            notifyUser('That file has an entry with no id or name, so it was not imported.');
            return;
          }
        }

        /*
          Coerce before storing. Escaping where these are drawn is what stops
          them being markup, but a preset whose xMin is an object or a hostile
          string is still wrong everywhere else it is used - and it would be
          written back to localStorage to be met again on the next visit. A
          field that is meant to be a number becomes a number or nothing.
        */
        for (const preset of imported) {
          for (const key of ['xMin', 'xMax', 'yMin', 'yMax']) {
            if (preset[key] == null || preset[key] === '') { preset[key] = null; continue; }
            const asNumber = Number(preset[key]);
            preset[key] = Number.isFinite(asNumber) ? asNumber : null;
          }
          for (const key of ['xScale', 'yScale']) {
            if (preset[key] !== 'linear' && preset[key] !== 'log') preset[key] = null;
          }
          preset.id = String(preset.id).slice(0, 120);
          preset.name = String(preset.name).slice(0, 120);
        }

        /*
          Merge rather than replace. This used to hand the parsed array straight
          to savePresetsToStorage, which overwrites the key outright — so
          importing a colleague's two presets silently destroyed every preset
          the user had built up themselves, with a success message on top.

          An imported preset replaces one of the same id in place, keeping its
          position so the Default preset stays first; anything not in the file
          is left alone.
        */
        const merged = new Map(loadPresets().map(preset => [preset.id, preset]));
        let replaced = 0;
        for (const preset of imported) {
          if (merged.has(preset.id)) replaced++;
          merged.set(preset.id, preset);
        }
        const addedCount = imported.length - replaced;
        savePresetsToStorage([...merged.values()]);
        populatePresetDropdown();
        _renderPresetManagerList();
        notifyUser(
          `Imported ${imported.length} preset(s): ${addedCount} added, ${replaced} replaced. `
          + 'Presets not in the file were kept.',
          { tone: 'success' });
      } catch (e) {
        reportFailure('importPresets', e, { userMessage: 'That preset file could not be read' });
      }
    };
    reader.readAsText(file);
  };
  input.click();
}
