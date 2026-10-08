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

/**
 * Populate the preset <select> dropdown, keeping whatever was selected.
 *
 * Every edit, capture, delete and import in the preset manager rebuilds the
 * list, and this used to drop the selection on the floor: the browser falls
 * back to the first option, so editing any preset quietly switched the chart's
 * preset to Auto range -- and closing the manager then applied it. A preset
 * that no longer exists falls back to Auto range; the caller decides whether
 * the view it left behind should read as Custom instead.
 */
function populatePresetDropdown() {
  const sel = document.getElementById('presetSelect');
  if (!sel) return;
  const previous = sel.value;
  const presets = loadPresets();
  sel.innerHTML = '';
  presets.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = p.name;
    sel.appendChild(opt);
  });
  if (previous === '__custom__') _markCustomPreset();
  else if (presets.some(p => p.id === previous)) sel.value = previous;
}

/** Apply the selected preset to the chart. */
function applySelectedPreset() {
  const sel = document.getElementById('presetSelect');
  if (!sel) return;
  if (sel.value === '__custom__') return;
  _removeCustomOption();
  applyPresetById(sel.value);
}

/** Apply a preset by its id string. Resolves once the chart has moved. */
function applyPresetById(id) {
  if (!currentChartData) return Promise.resolve();
  const presets = loadPresets();
  const preset = presets.find(p => p.id === id);
  if (!preset) return Promise.resolve();

  // Default preset → reset to autorange with current scale toggles
  if (preset.id === 'default') {
    const xScale = getScaleValue('x');
    const yScale = getScaleValue('y');
    _suppressPresetSync = true;
    return Plotly.relayout('plotlyChart', forEveryPanel(document.getElementById('plotlyChart'), {
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
    })).then(() => { _suppressPresetSync = false; refreshDynamicLegend(); return snapLogRangeToDecades(document.getElementById('plotlyChart')); });
  }

  const rangeOf = (lo, hi) => (lo != null && hi != null ? [lo, hi] : null);
  return _applyAxisSettings({
    x: { scale: preset.xScale || null, prefix: preset.xPrefix, range: rangeOf(preset.xMin, preset.xMax) },
    y: { scale: preset.yScale || null, prefix: preset.yPrefix, range: rangeOf(preset.yMin, preset.yMax) }
  });
}

/**
 * Move the chart's axes, for a preset or for the Current view editor.
 *
 * `settings.x` and `settings.y` are each optional -- an axis left out is not
 * touched at all, which is how the editor changes only what the reader
 * changed. Within an axis, `scale` null keeps the current scale; `prefix` is
 * the unit's prefix, '' for none, or null or undefined to keep the one it
 * has; and `range` is [min, max] in the file's units, null for auto range, or
 * undefined to keep the limits as they are (Plotly carries them across a
 * change of scale, the same as the lin/log buttons, and a change of prefix
 * keeps the stretch of data shown).
 *
 * The limits are converted for the scale the axis ENDS UP on. This used to go
 * by the preset's own scale only, so a preset with scale "auto" and limits,
 * applied to a log axis, handed Plotly years as if they were exponents. And
 * they are put in the prefix it ends up with: a preset's 1e4 Bq is 10 kBq.
 *
 * @returns {Promise}
 */
async function _applyAxisSettings(settings) {
  // A prefix first: it redraws the data, and the limits below are put in it.
  for (const axis of ['x', 'y']) {
    const s = settings[axis];
    if (!s || s.prefix === undefined || s.prefix === null) continue;
    setAxisPrefix(axis, s.prefix);
    await changeAxisPrefix(axis);
  }
  const exp = chartExponents();
  const plotDiv = document.getElementById('plotlyChart');
  const fullLayout = plotDiv && plotDiv._fullLayout;
  const update = {};
  for (const axis of ['x', 'y']) {
    const s = settings[axis];
    if (!s) continue;
    const key = axis + 'axis';
    // Plotly autoranges an axis that is given the type it has: only between
    // lin and log does it carry the range across. So the type goes in when it
    // changes or a range goes in with it, and not for a change of prefix alone.
    const typeChanges = !fullLayout || !fullLayout[key] || fullLayout[key].type !== s.scale;
    if (s.scale && (typeChanges || s.range !== undefined)) {
      setScaleValue(axis, s.scale);
      update[key + '.type'] = s.scale;
      if (s.scale === 'log') {
        update[key + '.dtick'] = 1;
        update[key + '.minor.ticks'] = 'outside';
        update[key + '.minor.ticklen'] = 3;
        update[key + '.minor.showgrid'] = true;
      } else {
        update[key + '.tickmode'] = 'auto';
        update[key + '.dtick'] = null;
        update[key + '.minor.ticks'] = 'outside';
        update[key + '.minor.showgrid'] = false;
      }
      if (axis === 'x' && typeChanges) {
        const bgShapes = backgroundShapesForXScale(plotDiv, s.scale);
        if (bgShapes) update.shapes = bgShapes;
      }
    }
    if (s.range === undefined) continue;
    if (s.range) {
      const onScale = s.scale || getScaleValue(axis);
      const [lo, hi] = s.range.map(v => shiftDecimal(v, -exp[axis]));
      update[key + '.range'] = onScale === 'log'
        ? [Math.log10(lo), Math.log10(hi)]
        : [lo, hi];
      update[key + '.autorange'] = false;
    } else {
      update[key + '.autorange'] = true;
    }
  }
  if (!Object.keys(update).length) return Promise.resolve();

  _suppressPresetSync = true;
  return Plotly.relayout('plotlyChart', forEveryPanel(plotDiv, update)).then(() => { _suppressPresetSync = false; refreshDynamicLegend(); return snapLogRangeToDecades(plotDiv); });
}

/**
 * Capture the current chart view state as a preset object (without id/name):
 * its limits in the file's units, whatever prefix the axes are shown in, and
 * the prefixes, null where there is none (a preset then keeps the one the
 * chart has).
 */
function _captureCurrentView() {
  const plotDiv = document.getElementById('plotlyChart');
  if (!plotDiv || !plotDiv.layout) return null;
  const xaxis = plotDiv.layout.xaxis || {};
  const yaxis = plotDiv.layout.yaxis || {};
  const xScale = getScaleValue('x');
  const yScale = getScaleValue('y');
  const exp = chartExponents();

  let xMin = null, xMax = null, yMin = null, yMax = null;
  if (xaxis.range && xaxis.autorange !== true) {
    xMin = shiftDecimal(xScale === 'log' ? Math.pow(10, xaxis.range[0]) : xaxis.range[0], exp.x);
    xMax = shiftDecimal(xScale === 'log' ? Math.pow(10, xaxis.range[1]) : xaxis.range[1], exp.x);
  }
  if (yaxis.range && yaxis.autorange !== true) {
    yMin = shiftDecimal(yScale === 'log' ? Math.pow(10, yaxis.range[0]) : yaxis.range[0], exp.y);
    yMax = shiftDecimal(yScale === 'log' ? Math.pow(10, yaxis.range[1]) : yaxis.range[1], exp.y);
  }
  return { xScale, yScale, xMin, xMax, yMin, yMax, xPrefix: prefixOf(exp.x) || null, yPrefix: prefixOf(exp.y) || null };
}

/** Save the current chart view as a new preset (asks for its name). */
async function saveCurrentAsPreset() {
  if (!currentChartData) { notifyUser('Draw a chart first — there is nothing to capture yet.'); return; }
  const name = await rbAskText({ title: 'Save preset', label: 'Preset name', okLabel: 'Save' });
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

/*
  The first row of the manager is the chart's current view, not a saved
  preset. Editing it moves the chart and saves nothing, and since the view then
  matches no preset, the dropdown changes to Custom. Editing a saved preset
  moves the chart only when that preset is the selected one: it stays selected
  and the chart follows the edit. Any other preset changes in storage only.
*/
const _CURRENT_VIEW_ROW = '__current__';

function openPresetManager() {
  const overlay = document.getElementById('presetManagerOverlay');
  if (!overlay) return;
  _renderPresetManagerList();
  overlay.style.display = 'flex';
}

/*
  Closing only closes. It used to re-apply the selected preset, which was how
  an edit to that preset reached the chart -- but it did so on every close,
  and since every change in here had already reset the dropdown to Auto range
  (see populatePresetDropdown), opening and closing the dialog threw a zoomed
  view away. Each change now reaches the chart when it is made.
*/
function closePresetManager() {
  const overlay = document.getElementById('presetManagerOverlay');
  if (overlay) overlay.style.display = 'none';
  _cancelPresetEdit();
}

function _refreshPresetManagerIfOpen() {
  const overlay = document.getElementById('presetManagerOverlay');
  if (overlay && overlay.style.display !== 'none') _renderPresetManagerList();
}

function _selectedPresetId() {
  const sel = document.getElementById('presetSelect');
  return sel ? sel.value : null;
}

/**
 * The chart's axes as the reader sees them, in the units on the axes: each
 * axis's scale, its prefix ('' for none) and its visible limits, whether those
 * were set or autoranged. The Current view editor starts from these, so the
 * numbers in it are the ones on screen.
 *
 * @returns {Object|null} {xScale, xPrefix, xMin, xMax, yScale, yPrefix, yMin, yMax}
 */
function _visibleAxisSettings() {
  const plotDiv = document.getElementById('plotlyChart');
  const fl = plotDiv && plotDiv._fullLayout;
  if (!fl || !fl.xaxis || !fl.yaxis) return null;
  const exp = chartExponents();
  const out = {};
  for (const axis of ['x', 'y']) {
    const ax = fl[axis + 'axis'];
    const scale = ax.type === 'log' ? 'log' : 'linear';
    const r = Array.isArray(ax.range) ? ax.range.map(Number) : [];
    // Six significant figures: 10 ** 5 is 100000, not 99999.99999999997.
    const toData = (v) => Number.isFinite(v)
      ? Number((scale === 'log' ? Math.pow(10, v) : v).toPrecision(6))
      : null;
    out[axis + 'Scale'] = scale;
    out[axis + 'Prefix'] = prefixOf(exp[axis]);
    out[axis + 'Min'] = toData(r[0]);
    out[axis + 'Max'] = toData(r[1]);
  }
  return out;
}

/**
 * A preset's limits in the units its prefix shows them in, which is how the
 * manager lists and edits them: they are kept in the file's units, and a
 * preset with no prefix of its own shows them so.
 *
 * @param {Object} p - A preset
 * @returns {Object} a copy
 */
function _inPresetUnits(p) {
  const shown = Object.assign({}, p);
  for (const axis of ['x', 'y']) {
    const e = prefixExponent(p[axis + 'Prefix']);
    if (!e) continue;
    for (const end of ['Min', 'Max']) {
      const v = p[axis + end];
      if (v != null && Number.isFinite(Number(v))) shown[axis + end] = shiftDecimal(Number(v), -e);
    }
  }
  return shown;
}

/**
 * One line for a set of axes: each one's scale, its prefix, and its limits in
 * the units of that prefix. The prefix is left out when there is none to say:
 * null keeps the chart's, and the chart's own '' is none.
 *
 * @param {Object} s - {xScale, xPrefix, xMin, xMax, ...}
 * @param {boolean} [view] - The chart's own axes, where '' is simply no prefix
 */
function _axisSummary(s, view = false) {
  const fmtR = (lo, hi) => (lo != null && hi != null) ? lo + ' – ' + hi : 'auto';
  const prefix = (p) => {
    if (p === '' && !view) return ', no prefix';
    return prefixExponent(p) ? ', prefix ' + p : '';
  };
  return 'X: ' + (s.xScale || 'auto') + prefix(s.xPrefix) + ' [' + fmtR(s.xMin, s.xMax) + ']   '
    + 'Y: ' + (s.yScale || 'auto') + prefix(s.yPrefix) + ' [' + fmtR(s.yMin, s.yMax) + ']';
}

/** A manager row: name, one-line summary, and an optional tag after the name. */
function _presetManagerRow(id, name, summaryText, tag) {
  const row = document.createElement('div');
  row.className = 'preset-manager-row';
  row.dataset.presetId = id;

  const nameSpan = document.createElement('span');
  nameSpan.className = 'preset-manager-name';
  nameSpan.textContent = name;
  if (tag) {
    const tagSpan = document.createElement('span');
    tagSpan.className = 'preset-manager-tag';
    tagSpan.textContent = tag;
    nameSpan.appendChild(tagSpan);
  }

  const summary = document.createElement('span');
  summary.className = 'preset-manager-summary';
  summary.textContent = summaryText;

  const nameBlock = document.createElement('div');
  nameBlock.className = 'preset-manager-name-block';
  nameBlock.appendChild(nameSpan);
  nameBlock.appendChild(summary);
  row.appendChild(nameBlock);
  return row;
}

function _presetManagerButton(label, title, onclick, className) {
  const btn = document.createElement('button');
  btn.textContent = label;
  btn.title = title;
  if (className) btn.className = className;
  btn.onclick = onclick;
  return btn;
}

function _renderPresetManagerList() {
  const list = document.getElementById('presetManagerList');
  if (!list) return;
  const presets = loadPresets();
  const selectedId = _selectedPresetId();
  list.innerHTML = '';

  // The chart as it is now. Tagged when the dropdown says Custom, since then
  // this row is the only one that describes what is on screen.
  const view = currentChartData ? _visibleAxisSettings() : null;
  const currentRow = _presetManagerRow(
    _CURRENT_VIEW_ROW, 'Current view',
    view ? _axisSummary(view, true) : 'No chart drawn yet',
    selectedId === '__custom__' ? 'Custom ✱' : '');
  currentRow.classList.add('preset-manager-current');
  if (selectedId === '__custom__') currentRow.classList.add('is-selected');
  const currentActions = document.createElement('span');
  currentActions.className = 'preset-manager-actions';
  const currentEdit = _presetManagerButton('Edit',
    'Change the chart’s axes without saving a preset', () => _editCurrentView());
  currentEdit.disabled = !view;
  currentActions.appendChild(currentEdit);
  currentRow.appendChild(currentActions);
  list.appendChild(currentRow);

  presets.forEach(p => {
    const isSelected = p.id === selectedId;
    const row = _presetManagerRow(p.id, p.name,
      p.id === 'default' ? 'auto' : _axisSummary(_inPresetUnits(p)),
      isSelected ? 'selected' : '');
    if (isSelected) row.classList.add('is-selected');
    if (p.id === 'default') row.querySelector('.preset-manager-name').style.fontStyle = 'italic';

    if (p.id !== 'default') {
      const btnGroup = document.createElement('span');
      btnGroup.className = 'preset-manager-actions';
      btnGroup.appendChild(_presetManagerButton('Edit', 'Edit preset settings', () => _editPreset(p.id)));
      btnGroup.appendChild(_presetManagerButton('Capture', 'Overwrite with current chart view', () => _updatePresetFromView(p.id)));
      btnGroup.appendChild(_presetManagerButton('Delete', 'Delete preset', () => _deletePreset(p.id), 'preset-delete-btn'));
      row.appendChild(btnGroup);
    }
    list.appendChild(row);
  });
}

/*
  The edit form's prefix select: "as is" ('', a preset only: it keeps the
  chart's), "none", or a prefix. The limits beside it are in its units, which
  for "as is" and "none" are the file's: prefixExponent of the value either way.
*/
const _FORM_NO_PREFIX = 'none';

/** What the form's prefix select stands for: null (as is), '' (none) or a prefix. */
function _formPrefix(value) {
  if (value === _FORM_NO_PREFIX) return '';
  return prefixExponent(value) ? value : null;
}

/**
 * Whether two limits typed in the form are the same number, each in the units
 * of its prefix: 10 in k is 0.01 in M. Text that is not a number is the same
 * only as itself.
 */
function _sameLimit(a, ea, b, eb) {
  if (a === b && ea === eb) return true;
  if (a.trim() === '' || b.trim() === '') return a.trim() === b.trim();
  const na = Number(a);
  const nb = Number(b);
  if (!Number.isFinite(na) || !Number.isFinite(nb)) return false;
  return shiftDecimal(na, ea) === shiftDecimal(nb, eb);
}

/**
 * Open the inline edit form under a manager row, filled from `v`.
 *
 * Each axis has a prefix select, and its limits are in the units of the
 * prefix chosen: choosing another moves the numbers typed to the same
 * stretch of data in the new units, 10 (k) to 0.01 (M).
 *
 * @param {string} rowId - the row's data-preset-id
 * @param {Object} v - {name?, xScale, xPrefix, xMin, xMax, yScale, yPrefix, yMin, yMax},
 *   the limits in the units of the prefixes
 * @param {Object} opts - withName: show the name field; autoScale: offer
 *   "auto" as a scale and "as is" as a prefix (a preset can leave either
 *   alone, a view cannot); saveLabel: the confirm button's text
 * @returns {HTMLElement|null} the form, or null if the row is not there
 */
function _openAxisForm(rowId, v, { withName, autoScale, saveLabel }) {
  _cancelPresetEdit();
  const list = document.getElementById('presetManagerList');
  if (!list) return null;
  const targetRow = Array.from(list.querySelectorAll('.preset-manager-row'))
    .find(r => r.dataset.presetId === rowId);
  if (!targetRow) return null;

  /*
    Escaped, not just stringified. These fields look numeric but nothing
    enforces that: importPresets stores whatever JSON it is handed after
    checking only that id and name exist, so xMin can be a string, and it is
    interpolated straight into value="…" below. A preset file with
    xMin: '" autofocus onfocus=… x="' broke out of the attribute.
  */
  const fmtVal = (val) => (val == null ? '' : kvotEscapeHtml(val));
  const scaleSelect = (id, value) =>
    '<select id="' + id + '">' +
      (autoScale ? '<option value=""' + (value == null ? ' selected' : '') + '>auto</option>' : '') +
      '<option value="linear"' + (value === 'linear' ? ' selected' : '') + '>linear</option>' +
      '<option value="log"' + (value === 'log' ? ' selected' : '') + '>log</option>' +
    '</select>';
  // A stored prefix is compared, never written: a preset's could be anything.
  const prefixSelect = (id, value) => {
    const none = value === '' || (!autoScale && !prefixExponent(value));
    return '<select id="' + id + '">' +
      (autoScale ? '<option value=""' + (value == null || (!none && !prefixExponent(value)) ? ' selected' : '') + '>as is</option>' : '') +
      '<option value="' + _FORM_NO_PREFIX + '"' + (none ? ' selected' : '') + '>none</option>' +
      Object.keys(AXIS_PREFIXES).map(p => '<option value="' + p + '"' + (value === p ? ' selected' : '') + '>' + p + '</option>').join('') +
    '</select>';
  };
  const axisRow = (axis) => {
    const A = axis.toUpperCase();
    return '<div class="preset-edit-row">' +
      '<label>' + A + ' scale ' + scaleSelect('pe_' + axis + 'Scale', v[axis + 'Scale']) + '</label>' +
      '<label title="The prefix to the axis\'s unit: k shows Bq as kBq. The limits are in its units.">' + A + ' prefix ' + prefixSelect('pe_' + axis + 'Prefix', v[axis + 'Prefix']) + '</label>' +
      '<label>' + A + ' min <input type="text" id="pe_' + axis + 'Min" value="' + fmtVal(v[axis + 'Min']) + '" placeholder="auto"></label>' +
      '<label>' + A + ' max <input type="text" id="pe_' + axis + 'Max" value="' + fmtVal(v[axis + 'Max']) + '" placeholder="auto"></label>' +
    '</div>';
  };

  const form = document.createElement('div');
  form.id = 'presetEditForm';
  form.className = 'preset-edit-form';
  form.innerHTML =
    (withName
      ? '<div class="preset-edit-row">' +
          '<label>Name <input type="text" id="pe_name" class="preset-name-input" value="' + _escAttr(v.name) + '"></label>' +
        '</div>'
      : '') +
    axisRow('x') + axisRow('y') +
    '<div class="preset-edit-btns">' +
      '<button id="pe_save" class="preset-edit-save">' + kvotEscapeHtml(saveLabel) + '</button>' +
      '<button id="pe_cancel">Cancel</button>' +
    '</div>';

  targetRow.insertAdjacentElement('afterend', form);
  document.getElementById('pe_cancel').onclick = () => _cancelPresetEdit();
  // Another prefix: the limits typed, in its units.
  for (const axis of ['x', 'y']) {
    const select = document.getElementById('pe_' + axis + 'Prefix');
    let was = prefixExponent(select.value);
    select.onchange = () => {
      const now = prefixExponent(select.value);
      for (const end of ['Min', 'Max']) {
        const input = document.getElementById('pe_' + axis + end);
        const n = input.value.trim() === '' ? NaN : Number(input.value);
        if (Number.isFinite(n)) input.value = String(shiftDecimal(n, was - now));
      }
      was = now;
    };
  }
  return form;
}

/** The edit form's axis fields, as typed. */
function _readAxisForm() {
  const val = (id) => {
    const el = document.getElementById(id);
    return el ? String(el.value).trim() : '';
  };
  const out = {};
  for (const axis of ['x', 'y']) {
    out[axis + 'Scale'] = val('pe_' + axis + 'Scale');
    out[axis + 'Prefix'] = val('pe_' + axis + 'Prefix');
    out[axis + 'Min'] = val('pe_' + axis + 'Min');
    out[axis + 'Max'] = val('pe_' + axis + 'Max');
  }
  return out;
}

/**
 * One axis's limits from the form: `range` is [min, max], or null for auto
 * range when both are empty; `message` says why they cannot be used.
 *
 * Stricter than the form used to be. It read a limit that was not a number as
 * empty and kept a range with one end missing, and either way the preset was
 * then applied as auto range with no word about it; and a log axis with a
 * limit of zero became Math.log10(0).
 */
function _formRange(axis, minText, maxText, scale) {
  const A = axis.toUpperCase();
  if (minText === '' && maxText === '') return { range: null };
  if (minText === '' || maxText === '') {
    return { message: 'Give both ' + A + ' limits, or leave both empty for auto range.' };
  }
  const lo = Number(minText);
  const hi = Number(maxText);
  const bad = [[minText, lo], [maxText, hi]].find(([, n]) => !Number.isFinite(n));
  if (bad) return { message: A + ' limit “' + bad[0] + '” is not a number.' };
  if (scale === 'log' && (lo <= 0 || hi <= 0)) {
    return { message: 'A log ' + A + ' axis needs limits above zero.' };
  }
  return { range: [lo, hi] };
}

/** Show inline edit form for a preset. */
function _editPreset(id) {
  const p = loadPresets().find(x => x.id === id);
  if (!p) return;
  if (!_openAxisForm(id, _inPresetUnits(p), { withName: true, autoScale: true, saveLabel: 'Save' })) return;
  document.getElementById('pe_save').onclick = () => _savePresetEdit(id);
}

/*
  Kept as a name the call sites already use, but delegating: this escaped &, "
  and < and left ' and > alone, which is safe only for as long as every
  attribute it feeds is written with double quotes. kvot-safe.js does all five.
*/
function _escAttr(s) {
  return kvotEscapeHtml(s);
}

function _savePresetEdit(id) {
  const presets = loadPresets();
  const p = presets.find(x => x.id === id);
  if (!p) return;

  const nameVal = (document.getElementById('pe_name').value || '').trim();
  if (!nameVal) { notifyUser('Give the preset a name before saving.'); return; }

  const f = _readAxisForm();
  const x = _formRange('x', f.xMin, f.xMax, f.xScale);
  const y = _formRange('y', f.yMin, f.yMax, f.yScale);
  const problem = [x, y].find(r => r.message);
  if (problem) { notifyUser(problem.message); return; }

  // Kept in the file's units: the form's are its prefix's.
  const inFile = (r, prefix) => (r.range ? r.range.map(v => shiftDecimal(v, prefixExponent(prefix))) : [null, null]);
  p.name    = nameVal;
  p.xScale  = f.xScale || null;
  p.yScale  = f.yScale || null;
  p.xPrefix = _formPrefix(f.xPrefix);
  p.yPrefix = _formPrefix(f.yPrefix);
  [p.xMin, p.xMax] = inFile(x, f.xPrefix);
  [p.yMin, p.yMax] = inFile(y, f.yPrefix);

  savePresetsToStorage(presets);
  populatePresetDropdown();
  _renderPresetManagerList();
  // The selected preset stays selected and the chart follows the edit.
  if (_selectedPresetId() === id) applyPresetById(id).then(_refreshPresetManagerIfOpen);
}

/** Show the inline edit form for the chart's current view. */
function _editCurrentView() {
  if (!currentChartData) { notifyUser('Draw a chart first — there is nothing to edit yet.'); return; }
  const view = _visibleAxisSettings();
  if (!view) return;
  if (!_openAxisForm(_CURRENT_VIEW_ROW, view, { withName: false, autoScale: false, saveLabel: 'Apply' })) return;
  const before = _readAxisForm();
  document.getElementById('pe_save').onclick = () => _applyCurrentViewEdit(before);
}

/**
 * Apply the Current view form to the chart, saving nothing.
 *
 * Only an axis whose fields were changed is touched, and within it a scale
 * change on its own keeps the limits, as the lin/log buttons do -- the form
 * starts from the limits on screen, so leaving them alone must not pin an
 * autoranged axis to them. A change of prefix on its own keeps them too:
 * the numbers the form moved into its units are the same limits. Applying
 * with nothing changed leaves the selection alone; any change makes it Custom.
 *
 * @param {Object} before - the form as it was opened, from _readAxisForm
 */
function _applyCurrentViewEdit(before) {
  const now = _readAxisForm();
  const settings = {};
  for (const axis of ['x', 'y']) {
    const ePrev = prefixExponent(before[axis + 'Prefix']);
    const eNow = prefixExponent(now[axis + 'Prefix']);
    const scaleChanged = now[axis + 'Scale'] !== before[axis + 'Scale'];
    const prefixChanged = now[axis + 'Prefix'] !== before[axis + 'Prefix'];
    const rangeChanged = !_sameLimit(before[axis + 'Min'], ePrev, now[axis + 'Min'], eNow)
      || !_sameLimit(before[axis + 'Max'], ePrev, now[axis + 'Max'], eNow);
    if (!scaleChanged && !prefixChanged && !rangeChanged) continue;
    const s = { scale: now[axis + 'Scale'] || null };
    if (prefixChanged) s.prefix = _formPrefix(now[axis + 'Prefix']);
    if (rangeChanged) {
      const r = _formRange(axis, now[axis + 'Min'], now[axis + 'Max'], s.scale);
      if (r.message) { notifyUser(r.message); return; }
      s.range = r.range ? r.range.map(v => shiftDecimal(v, eNow)) : null;   // in the file's units
    }
    settings[axis] = s;
  }
  if (!settings.x && !settings.y) { _cancelPresetEdit(); return; }

  _markCustomPreset();
  _renderPresetManagerList();
  _applyAxisSettings(settings).then(_refreshPresetManagerIfOpen);
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

async function _deletePreset(id) {
  const doomed = loadPresets().find(x => x.id === id);
  const asked = await rbAskConfirm({
    title: 'Delete preset',
    message: doomed ? `Delete the preset “${doomed.name}”?` : 'Delete this preset?',
    okLabel: 'Delete'
  });
  if (!asked) return;
  const wasSelected = _selectedPresetId() === id;
  let presets = loadPresets();
  presets = presets.filter(x => x.id !== id);
  savePresetsToStorage(presets);
  populatePresetDropdown();
  // The chart keeps the view the deleted preset gave it, which is now no
  // preset's; without a chart there is no view, and Auto range stands.
  if (wasSelected && currentChartData) _markCustomPreset();
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

/** How many decades a log y axis on auto range may span below its top. */
const LOG_Y_DECADES = 12;

/**
 * The decades a log y axis on auto range spans for these traces: the top is
 * the decade at or above the highest value drawn, the bottom the decade at or
 * below the lowest, and never more than LOG_Y_DECADES below the top. Null when
 * there is nothing to go by: no positive value, or a histogram, whose bars
 * Plotly counts itself.
 *
 * @param {Object[]} traces - The chart's traces (plotDiv.data)
 * @returns {number[]|null} [bottom, top] as powers of ten
 */
function logYRangeOfData(traces) {
  let lo = Infinity, hi = -Infinity;
  for (const t of traces || []) {
    if (t.type === 'histogram') return null;
    if (t.visible === false || t.visible === 'legendonly' || !t.y) continue;
    for (const v of t.y) {
      if (v > 0 && v < Infinity) {
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
    }
  }
  if (!(hi > 0)) return null;
  // The tolerance keeps a value that is a power of ten on its own decade.
  const top = Math.ceil(Math.log10(hi) - 1e-9);
  let bottom = Math.max(Math.floor(Math.log10(lo) + 1e-9), top - LOG_Y_DECADES);
  if (bottom >= top) bottom = top - 1;
  return [bottom, top];
}

/**
 * Whether a y axis still shows the auto range the last snap gave it. The
 * snap has to turn Plotly's autorange off to set its range, but until a zoom,
 * a preset or the axes lock sets another, the axis is still on auto range, and
 * should follow the traces when they change: a CI band, a realisation, a total.
 *
 * @param {HTMLElement} plotDiv
 * @param {string} [key] - Which y axis: 'yaxis', or a panel's 'yaxis2' and on
 * @returns {boolean}
 */
function isAutoLogY(plotDiv, key = 'yaxis') {
  const held = plotDiv && plotDiv.__autoLogY && plotDiv.__autoLogY[key];
  const ax = plotDiv && plotDiv._fullLayout && plotDiv._fullLayout[key];
  if (!held || !ax || ax.type !== 'log' || !ax.range || _axesLocked) return false;
  return Math.abs(ax.range[0] - held[0]) < 1e-9 && Math.abs(ax.range[1] - held[1]) < 1e-9;
}

/**
 * The y axes that keep a range of their own, 'yaxis' first. A panel's axis
 * that follows another (`matches`) is left to the one it follows.
 *
 * @param {Object} fullLayout
 * @returns {string[]}
 */
function ownYAxes(fullLayout) {
  return Object.keys(fullLayout)
    .filter(k => /^yaxis\d*$/.test(k) && !fullLayout[k].matches)
    .sort((a, b) => Number(a.slice(5) || 1) - Number(b.slice(5) || 1));
}

/**
 * The traces drawn against y axis `key`, or against a panel's axis that
 * follows it.
 *
 * @param {HTMLElement} plotDiv
 * @param {string} key - 'yaxis', 'yaxis2', ...
 * @returns {Object[]}
 */
function tracesOnYAxis(plotDiv, key) {
  const fl = plotDiv._fullLayout;
  const id = 'y' + key.slice(5);
  const ids = new Set([id]);
  for (const k of Object.keys(fl)) {
    if (/^yaxis\d*$/.test(k) && fl[k].matches === id) ids.add('y' + k.slice(5));
  }
  return (plotDiv.data || []).filter(t => ids.has(t.yaxis || 'y'));
}

/**
 * Snap log-scale axes to full-decade boundaries so the last major
 * gridline and its tick label are always visible.
 *
 * A y axis on auto range is set from the values drawn (logYRangeOfData)
 * rather than from Plotly's padded range. Snapping that outwards let the
 * padding add a decade above the data, and let one tiny value, a 1e-30 left
 * by round-off, stretch the axis over thirty decades. An x axis is still
 * snapped outwards from Plotly's range.
 */
let _snappingLog = false;
let _snapAgain = false;
function snapLogRangeToDecades(plotDiv) {
  if (!plotDiv) return Promise.resolve();
  // One at a time. A request made meanwhile runs once this one is done, since
  // what it was made for (a band just added, say) may change the range.
  if (_snappingLog) { _snapAgain = true; return Promise.resolve(); }
  var fl = plotDiv._fullLayout;
  if (!fl) return Promise.resolve();
  var update = {};
  // Every y axis with a range of its own: one, or a panel's each when the
  // groups drawn are in different units (renderRadionuclidePanels).
  ['xaxis'].concat(ownYAxes(fl)).forEach(function(axis) {
    var ax = fl[axis];
    if (!ax || ax.type !== 'log') return;
    var r = ax.range;
    if (!r || r.length < 2) return;
    var target = null;
    if (axis !== 'xaxis' && (ax.autorange || isAutoLogY(plotDiv, axis))) {
      target = logYRangeOfData(tracesOnYAxis(plotDiv, axis));
      if (target) plotDiv.__autoLogY = Object.assign({}, plotDiv.__autoLogY, { [axis]: target });
    }
    if (!target) {
      // Only snap auto-ranged axes; preserve explicit user/preset limits
      if (!ax.autorange) return;
      target = [Math.floor(r[0]), Math.ceil(r[1])];
    }
    if (Math.abs(r[0] - target[0]) > 0.001 || Math.abs(r[1] - target[1]) > 0.001) {
      update[axis + '.range'] = target;
      update[axis + '.autorange'] = false;
    }
  });
  if (Object.keys(update).length > 0) {
    _suppressPresetSync = true;
    _snappingLog = true;
    var done = function() {
      _suppressPresetSync = false;
      _snappingLog = false;
    };
    return Plotly.relayout(plotDiv, update).then(function() {
      done();
      if (_snapAgain) {
        _snapAgain = false;
        return snapLogRangeToDecades(plotDiv);
      }
    }, done);
  }
  return Promise.resolve();
}

/**
 * Listen for user-initiated axis changes and sync the preset dropdown.
 * - Manual zoom/pan → switch to "Custom *"
 * - Autoscale (double-click or button) → switch to "Auto range"
 * Programmatic relayouts are ignored via _suppressPresetSync flag.
 * One listener however often the chart is set up (see onPlotEvent).
 */
function setupPresetRelayoutSync(plotDiv) {
  onPlotEvent(plotDiv, 'plotly_relayout', 'presetSync', function(eventData) {
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
          // A prefix is one of the page's, '' for none, or null to keep the chart's.
          for (const key of ['xPrefix', 'yPrefix']) {
            const p = preset[key] === 'μ' || preset[key] === 'u' ? 'µ' : preset[key];
            preset[key] = p === '' || prefixExponent(p) ? p : null;
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
        // Replacing the selected preset is editing it: the chart follows.
        const selectedId = _selectedPresetId();
        if (selectedId !== 'default' && imported.some(p => p.id === selectedId)) {
          applyPresetById(selectedId).then(_refreshPresetManagerIfOpen);
        }
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
