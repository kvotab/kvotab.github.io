/* ==========================================================================
   RB CHART - saved axis presets and the axis presets window
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
  _presetPanelSync();
}

/** Apply the selected preset to the chart. */
function applySelectedPreset() {
  const sel = document.getElementById('presetSelect');
  if (!sel) return;
  if (sel.value === '__custom__') return;
  _removeCustomOption();
  applyPresetById(sel.value);
}

/**
 * Apply a preset by its id string. Resolves once the chart has moved. Only to
 * a time chart: a data preview's histogram has axes of another kind.
 */
function applyPresetById(id) {
  if (!_timeChartOnScreen()) return Promise.resolve();
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

/**
 * Save the current chart view as a preset, asking for its name. A name a
 * preset already has replaces that preset, once the reader says so: two of
 * one name could not be told apart in the dropdown. The preset saved is then
 * the one selected, since it is the view on screen.
 */
async function saveCurrentAsPreset() {
  if (!_timeChartOnScreen()) { notifyUser('Draw a chart first — there is no view to save yet.'); return; }
  const name = String(await rbAskText({ title: 'Save preset', label: 'Preset name', okLabel: 'Save' }) || '').trim();
  if (!name) return;

  const view = _captureCurrentView();
  if (!view) return;

  const presets = loadPresets();
  const same = presets.find(p => String(p.name).trim().toLowerCase() === name.toLowerCase());
  if (same && same.id === 'default') {
    notifyUser(`“${same.name}” is the page's own preset: choose another name.`);
    return;
  }
  let id;
  if (same) {
    const replace = await rbAskConfirm({
      title: 'Replace preset',
      message: `There is a preset called “${same.name}” already. Replace its axes with the chart's?`,
      okLabel: 'Replace'
    });
    if (!replace) return;
    Object.assign(same, view);
    id = same.id;
  } else {
    id = 'user_' + Date.now();
    presets.push(Object.assign({ id, name, builtIn: false }, view));
  }
  savePresetsToStorage(presets);
  populatePresetDropdown();

  // Select the preset saved: it is the view on screen.
  const sel = document.getElementById('presetSelect');
  if (sel) sel.value = id;
  _removeCustomOption();
}

/* ---------- The axis presets window ---------- */

/*
  What the gear opens: the chart's axes as they are now, and the saved
  presets. It floats over the page rather than blocking it -- the chart stays
  in view, and can be zoomed while it is open with the numbers following it --
  and it is moved by its title bar, staying where it is put.

  The rules it keeps (the user's):
    - its first part is the chart's axes as they are now: changing them and
      applying moves the chart and saves nothing, and since the view then
      matches no preset the dropdown says Custom; applying with nothing
      changed leaves the selection alone;
    - a click on a preset uses it, as choosing it in the dropdown does;
    - editing the SELECTED preset keeps it selected and moves the chart with
      it; editing any other preset moves nothing;
    - closing only closes. It used to re-apply the selected preset, which was
      how an edit to that preset reached the chart -- but it did so on every
      close, and since every change in here had reset the dropdown to Auto
      range (see populatePresetDropdown), opening and closing threw a zoomed
      view away. Each change reaches the chart when it is made.

  It is built of elements and text, never of markup: a preset's name and
  numbers can come from an imported file.
*/

/** Where the reader put the window, kept in this browser only. */
const _PRESET_PANEL_PLACE_KEY = 'kvot-rb-preset-panel';

/**
 * The chart's-axes part: its fields as filled from the chart (`before`),
 * whether the reader has changed them since, and the chart they were filled
 * from, so that another chart fills them afresh.
 */
const _presetNow = { before: null, dirty: false, chart: null };

function _presetPanel() {
  return document.getElementById('presetPanel');
}

function _presetPanelOpen() {
  const panel = _presetPanel();
  return !!panel && !panel.hidden;
}

/** Whether a time chart is on screen, whose axes the window sets: not a data preview's histogram. */
function _timeChartOnScreen() {
  const plotDiv = document.getElementById('plotlyChart');
  return !!(currentChartData && currentChartData.axisUnits && plotDiv && plotDiv._fullLayout);
}

function openPresetManager() {
  const panel = _presetPanel();
  if (!panel) return;
  _wirePresetPanel(panel);
  if (panel.hidden) {
    panel.hidden = false;
    _presetNow.chart = null;   // filled afresh from the chart
    _syncPresetPanel();
    _placePresetPanel(_savedPresetPanelPlace() || _defaultPresetPanelPlace(panel));
    _setPresetGearOpen(true);
  }
  panel.focus({ preventScroll: true });
}

function closePresetManager() {
  const panel = _presetPanel();
  if (!panel || panel.hidden) return;
  _cancelPresetEdit();
  const hadFocus = panel.contains(document.activeElement);
  panel.hidden = true;
  _setPresetGearOpen(false);
  // Focus goes back to where the window was opened from.
  const gear = document.getElementById('presetGear');
  if (hadFocus && gear && !gear.disabled) gear.focus();
}

/** The gear: opens the window, or closes it when it is open. */
function togglePresetManager() {
  if (_presetPanelOpen()) closePresetManager();
  else openPresetManager();
}

function _setPresetGearOpen(open) {
  const gear = document.getElementById('presetGear');
  if (!gear) return;
  gear.classList.toggle('active', open);
  gear.setAttribute('aria-expanded', open ? 'true' : 'false');
}

function _selectedPresetId() {
  const sel = document.getElementById('presetSelect');
  return sel ? sel.value : null;
}

/*
  The window follows the chart and the presets: whatever moves the axes,
  draws another chart, or changes the presets or the one selected asks for
  this, and the window catches up a moment later, once for a burst of them
  (a scroll zoom is many).
*/
let _presetSyncTimer = null;
function _presetPanelSync() {
  if (_presetSyncTimer !== null || !_presetPanelOpen()) return;
  _presetSyncTimer = setTimeout(() => {
    _presetSyncTimer = null;
    _syncPresetPanel();
  }, 30);
}

function _syncPresetPanel() {
  const panel = _presetPanel();
  if (!panel || panel.hidden) return;
  // The axes lock holds the axes as they are: nothing in here may move them.
  const locked = !!_axesLocked;
  panel.classList.toggle('is-locked', locked);
  panel.querySelector('.preset-panel-fields').disabled = locked;
  const importButton = panel.querySelector('[data-on-click="importPresets"]');
  if (importButton) importButton.disabled = locked;
  _syncChartNow();
  _syncPresetList();
  _keepPresetPanelInView();
}

/** An element, with a class and its text when given. */
function _el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function _presetButton(label, title, onClick, className = 'preset-btn') {
  const button = _el('button', className, label);
  button.type = 'button';
  if (title) button.title = title;
  button.addEventListener('click', onClick);
  return button;
}

/**
 * The chart's axes as the reader sees them, in the units on the axes: each
 * axis's scale, its prefix ('' for none) and its visible limits, whether those
 * were set or autoranged. The window's fields start from these, so the
 * numbers in them are the ones on screen.
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
 * window lists and edits them: they are kept in the file's units, and a
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

/** The units of the chart's axes, without a prefix, from what their titles are made of: {x: [...], y: [...]}. */
function _chartUnits() {
  const titles = (currentChartData && currentChartData.axisUnits && currentChartData.axisUnits.titles) || {};
  const of = (letter) => [...new Set(Object.keys(titles).sort()
    .filter(k => k[0] === letter && titles[k]).flatMap(k => titles[k].units.map(String)))];
  return { x: of('x'), y: of('y') };
}

/** A preset's limits as its line shows them: 100 – 10⁵, 10⁴ – 10⁹, 0 – 50000, 10⁻⁷ – 2×10⁻⁵. */
function _fmtRange(lo, hi) {
  return `${_fmtLimit(lo)} – ${_fmtLimit(hi)}`;
}

/**
 * A limit as it is from 0.001 to 99999, and as a power of ten beyond that,
 * 10⁹ or 2×10⁻⁵, rather than its nine zeros; a power of ten from 10⁴ up is
 * one too, so 10⁴ – 10⁹ reads as one kind of number.
 */
function _fmtLimit(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  const a = Math.abs(n);
  const [m, e] = n.toExponential().split('e');
  const mantissa = Number(Number(m).toPrecision(6));
  const plain = a === 0 || (a >= 1e-3 && a < 1e5 && !(a >= 1e4 && Math.abs(mantissa) === 1));
  if (plain) return String(Number(n.toPrecision(6))).replace('-', '−');
  const power = powerOfTen(Number(e));
  if (mantissa === 1) return power;
  if (mantissa === -1) return '−' + power;
  return `${mantissa}×${power}`;
}

/*
  The prefix select of a form: "keep" ('', a preset only: the chart's stays),
  "none", or a prefix; likewise its scale select's "keep". The limits beside
  a prefix are in its units, which for "keep" and "none" are the file's:
  prefixExponent of the value either way.
*/
const _FORM_NO_PREFIX = 'none';

/** What a form's prefix select stands for: null (keep), '' (none) or a prefix. */
function _formPrefix(value) {
  if (value === _FORM_NO_PREFIX) return '';
  return prefixExponent(value) ? value : null;
}

/**
 * Whether two limits typed in a form are the same number, each in the units
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
 * Both axes' settings as a table: Scale, Prefix, Min and Max, a row an axis,
 * the unit at the end. Its fields are `${prefix}xScale` and so on. Choosing
 * another prefix moves the numbers typed to the same stretch of data in its
 * units, 10 (k) to 0.01 (M), and the unit with them.
 *
 * @param {string} prefix - 'cv_' for the chart's axes, 'pe_' for a preset being edited
 * @param {Object} v - {xScale, xPrefix, xMin, xMax, ...}, the limits in the units of the prefixes
 * @param {Object} opts - keep: offer "keep" as a scale and as a prefix (a preset can
 *   leave either as the chart has it, the chart cannot); units: the axes' units
 *   without a prefix, {x, y}, to show with the prefix chosen
 * @returns {HTMLElement}
 */
function _axisGrid(prefix, v, { keep, units = null }) {
  const grid = _el('div', 'preset-grid');
  grid.append(_el('span'), _el('span', 'preset-grid-head', 'Scale'), _el('span', 'preset-grid-head', 'Prefix'),
    _el('span', 'preset-grid-head', 'Min'), _el('span', 'preset-grid-head', 'Max'), _el('span'));
  const select = (id, label, options, value) => {
    const s = _el('select');
    s.id = id;
    s.setAttribute('aria-label', label);
    for (const [val, text] of options) {
      const o = _el('option', null, text);
      o.value = val;
      s.appendChild(o);
    }
    s.value = options.some(([val]) => val === value) ? value : options[0][0];
    return s;
  };
  const field = (id, label, value) => {
    const f = _el('input');
    f.type = 'text';
    f.id = id;
    f.inputMode = 'decimal';
    f.autocomplete = 'off';
    f.spellcheck = false;
    f.placeholder = 'auto';
    f.title = 'Leave Min and Max empty and the axis fits the data';
    f.setAttribute('aria-label', label);
    f.value = value === undefined || value === null ? '' : String(value);
    return f;
  };
  for (const axis of ['x', 'y']) {
    const A = axis.toUpperCase();
    const scaleValue = v[axis + 'Scale'] === 'linear' || v[axis + 'Scale'] === 'log' ? v[axis + 'Scale'] : '';
    // A stored prefix is compared, never written: a preset's could be anything.
    const stored = v[axis + 'Prefix'];
    const prefixValue = prefixExponent(stored) ? stored : (stored === '' || !keep ? _FORM_NO_PREFIX : '');
    const scale = select(prefix + axis + 'Scale', `${A} scale`,
      [...(keep ? [['', 'keep']] : []), ['linear', 'linear'], ['log', 'log']], scaleValue);
    const pre = select(prefix + axis + 'Prefix', `${A} prefix`,
      [...(keep ? [['', 'keep']] : []), [_FORM_NO_PREFIX, 'none'], ...Object.keys(AXIS_PREFIXES).map(p => [p, p])],
      prefixValue);
    pre.title = 'A prefix to the unit: k shows Bq as kBq. The limits are in its units.';
    const min = field(prefix + axis + 'Min', `${A} min`, v[axis + 'Min']);
    const max = field(prefix + axis + 'Max', `${A} max`, v[axis + 'Max']);
    const unit = _el('span', 'preset-grid-unit');
    unit.id = prefix + axis + 'Unit';
    const showUnit = () => {
      unit.textContent = units ? unitsWithPrefix(units[axis] || [], prefixExponent(pre.value)) : '';
      unit.title = unit.textContent;   // it may be cut short
    };
    showUnit();
    let was = prefixExponent(pre.value);
    pre.addEventListener('change', () => {
      const now = prefixExponent(pre.value);
      for (const input of [min, max]) {
        const n = input.value.trim() === '' ? NaN : Number(input.value);
        if (Number.isFinite(n)) input.value = String(shiftDecimal(n, was - now));
      }
      was = now;
      showUnit();
    });
    grid.append(_el('span', 'preset-grid-axis', A), scale, pre, min, max, unit);
  }
  return grid;
}

/** A form's axis fields, as typed. */
function _readAxisForm(prefix) {
  const val = (id) => {
    const el = document.getElementById(id);
    return el ? String(el.value).trim() : '';
  };
  const out = {};
  for (const axis of ['x', 'y']) {
    out[axis + 'Scale'] = val(prefix + axis + 'Scale');
    out[axis + 'Prefix'] = val(prefix + axis + 'Prefix');
    out[axis + 'Min'] = val(prefix + axis + 'Min');
    out[axis + 'Max'] = val(prefix + axis + 'Max');
  }
  return out;
}

/**
 * One axis's limits from a form: `range` is [min, max], or null for auto
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

/**
 * What differs between two readings of an axis form, axis by axis: its scale,
 * its prefix, and its limits as numbers in the units of each reading's prefix
 * -- so a prefix changed on its own, which moves the numbers into its units,
 * leaves the limits the same.
 */
function _axisFormChanges(before, now) {
  const out = {};
  for (const axis of ['x', 'y']) {
    const ePrev = prefixExponent(before[axis + 'Prefix']);
    const eNow = prefixExponent(now[axis + 'Prefix']);
    out[axis] = {
      scale: now[axis + 'Scale'] !== before[axis + 'Scale'],
      prefix: now[axis + 'Prefix'] !== before[axis + 'Prefix'],
      range: !_sameLimit(before[axis + 'Min'], ePrev, now[axis + 'Min'], eNow)
        || !_sameLimit(before[axis + 'Max'], ePrev, now[axis + 'Max'], eNow)
    };
  }
  return out;
}

/** The chart's axes as the window's fields would read them. */
function _viewAsForm(view) {
  const out = {};
  for (const axis of ['x', 'y']) {
    out[axis + 'Scale'] = view[axis + 'Scale'];
    out[axis + 'Prefix'] = view[axis + 'Prefix'] || _FORM_NO_PREFIX;
    out[axis + 'Min'] = view[axis + 'Min'] === null ? '' : String(view[axis + 'Min']);
    out[axis + 'Max'] = view[axis + 'Max'] === null ? '' : String(view[axis + 'Max']);
  }
  return out;
}

/* ---------- The chart's axes, at the top of the window ---------- */

/**
 * The chart's axes, as fields that follow the chart until the reader changes
 * one: from then on Apply (or Enter) moves the chart to them and Revert puts
 * them back, and the chart moving meanwhile leaves them as typed.
 */
function _syncChartNow() {
  const box = document.getElementById('presetNow');
  if (!box) return;
  const chart = _timeChartOnScreen() ? currentChartData : null;
  if (_presetNow.chart !== chart || box.dataset.drawn !== '1') {
    // Another chart, or none: what was typed for the last one goes.
    _presetNow.chart = chart;
    _renderChartNow(box);
  } else if (chart && !_presetNow.dirty) {
    const view = _visibleAxisSettings();
    const shown = _presetNow.before;
    const fresh = view ? _viewAsForm(view) : null;
    if (fresh && shown && Object.keys(fresh).some(k => fresh[k] !== shown[k])) _renderChartNow(box);
  }
  _syncChartNowState();
}

function _renderChartNow(box) {
  const focused = box.contains(document.activeElement) ? document.activeElement.id : '';
  box.textContent = '';
  box.dataset.drawn = '1';
  _presetNow.dirty = false;
  _presetNow.before = null;
  const head = _el('div', 'preset-section-head');
  const state = _el('span', 'preset-state');
  state.id = 'presetNowState';
  head.append(_el('span', 'preset-section-title', 'The chart’s axes'), state);
  box.append(head);
  if (!_timeChartOnScreen()) {
    box.append(_el('p', 'preset-empty', 'No chart is drawn. Choose a dataset or a group, and its axes are shown here.'));
    return;
  }
  const grid = _axisGrid('cv_', _visibleAxisSettings(), { keep: false, units: _chartUnits() });
  grid.addEventListener('input', _chartNowEdited);
  grid.addEventListener('change', _chartNowEdited);
  box.append(grid);
  const buttons = _el('div', 'preset-buttons');
  const revert = _presetButton('Revert', 'Put the fields back as the chart has them (Esc)', _revertChartNow);
  revert.id = 'cv_revert';
  const apply = _presetButton('Apply', 'Set the chart’s axes to these (Enter)', _applyChartNow, 'preset-btn primary');
  apply.id = 'cv_apply';
  const save = _presetButton('Save as new preset…', 'Keep the chart’s axes as a preset of their own',
    _saveChartNowAsPreset);
  save.id = 'cv_save';
  buttons.append(revert, apply, _el('span', 'preset-spacer'), save);
  box.append(buttons);
  _presetNow.before = _readAxisForm('cv_');
  const again = focused && document.getElementById(focused);
  if (again && box.contains(again)) again.focus();
}

/** A field changed: the fields are the reader's until applied or reverted, if they differ from the chart. */
function _chartNowEdited() {
  if (!_presetNow.before) return;
  const changes = _axisFormChanges(_presetNow.before, _readAxisForm('cv_'));
  _presetNow.dirty = Object.values(changes).some(c => c.scale || c.prefix || c.range);
  _syncChartNowState();
}

/** The buttons, and the line saying what the chart's axes are: Auto range, a preset, or a view of the reader's own. */
function _syncChartNowState() {
  const on = _timeChartOnScreen();
  const apply = document.getElementById('cv_apply');
  const revert = document.getElementById('cv_revert');
  const save = document.getElementById('cv_save');
  if (apply) apply.disabled = !_presetNow.dirty;
  if (revert) revert.disabled = !_presetNow.dirty;
  if (save) save.disabled = !on;
  const state = document.getElementById('presetNowState');
  if (!state) return;
  let text = '';
  let kind = '';
  if (on) {
    const selected = _selectedPresetId();
    const preset = loadPresets().find(p => p.id === selected);
    if (_presetNow.dirty) { text = 'Changed: Apply to use'; kind = 'changed'; }
    else if (!preset) { text = 'Custom view, not saved'; kind = 'custom'; }
    else if (preset.id === 'default') { text = 'Auto range'; kind = 'auto'; }
    else { text = `Preset: ${preset.name}`; kind = 'preset'; }
  }
  state.textContent = text;
  state.dataset.kind = kind;
  state.hidden = !text;
}

/**
 * Apply the chart's-axes fields to the chart, if the reader changed them.
 *
 * @returns {Promise|null} the chart moving, or null when a field cannot be used (and it said why)
 */
function _applyChartNow() {
  if (!_presetNow.dirty || !_presetNow.before) return Promise.resolve();
  const moving = _applyCurrentViewEdit(_presetNow.before, _readAxisForm('cv_'));
  if (!moving) return null;
  return moving.then(() => {
    _presetNow.chart = null;   // filled afresh from the chart as it now is
    _syncPresetPanel();
  });
}

function _revertChartNow() {
  _presetNow.chart = null;
  _syncPresetPanel();
}

/** Save as new preset, from the window: what the fields say, applied first if they were changed. */
async function _saveChartNowAsPreset() {
  if (_presetNow.dirty) {
    const applied = _applyChartNow();
    if (!applied) return;
    await applied;
  }
  await saveCurrentAsPreset();
}

/**
 * Apply the chart's-axes fields to the chart, saving nothing.
 *
 * Only an axis whose fields were changed is touched, and within it a scale
 * change on its own keeps the limits, as the lin/log buttons do -- the fields
 * start from the limits on screen, so leaving them alone must not pin an
 * autoranged axis to them. A change of prefix on its own keeps them too:
 * the numbers the form moved into its units are the same limits. Applying
 * with nothing changed leaves the selection alone; any change makes it Custom.
 *
 * @param {Object} before - the fields as filled from the chart, from _readAxisForm
 * @param {Object} now - the fields as they are
 * @returns {Promise|null} null when a field cannot be used, and it said why
 */
function _applyCurrentViewEdit(before, now) {
  const changes = _axisFormChanges(before, now);
  const settings = {};
  for (const axis of ['x', 'y']) {
    const c = changes[axis];
    if (!c.scale && !c.prefix && !c.range) continue;
    const s = { scale: now[axis + 'Scale'] || null };
    if (c.prefix) s.prefix = _formPrefix(now[axis + 'Prefix']);
    if (c.range) {
      const r = _formRange(axis, now[axis + 'Min'], now[axis + 'Max'], s.scale);
      if (r.message) { notifyUser(r.message); return null; }
      const e = prefixExponent(now[axis + 'Prefix']);
      s.range = r.range ? r.range.map(v => shiftDecimal(v, e)) : null;   // in the file's units
    }
    settings[axis] = s;
  }
  if (!settings.x && !settings.y) return Promise.resolve();
  _markCustomPreset();
  return _applyAxisSettings(settings);
}

/* ---------- The saved presets ---------- */

/**
 * The saved presets, a row each: built again when they change, while no
 * preset is being edited; the one in use marked whenever the selection moves.
 */
function _syncPresetList() {
  const list = document.getElementById('presetManagerList');
  if (!list) return;
  const presets = loadPresets();
  const sig = JSON.stringify(presets);
  if (list.dataset.sig !== sig && !document.getElementById('presetEditForm')) {
    _renderPresetList(list, presets);
    list.dataset.sig = sig;
  }
  const selected = _selectedPresetId();
  // Using a preset, or updating one from the chart, needs a chart.
  const usable = _timeChartOnScreen();
  for (const row of list.querySelectorAll('.preset-row')) {
    const on = row.dataset.presetId === selected;
    row.classList.toggle('is-selected', on);
    const use = row.querySelector('.preset-use');
    use.setAttribute('aria-checked', on ? 'true' : 'false');
    use.disabled = !usable;
    const update = [...row.querySelectorAll('button')].find(b => b.dataset.act === 'update');
    if (update) update.disabled = !usable;
  }
}

function _renderPresetList(list, presets) {
  // A button that had the focus keeps it, in the row built anew.
  const focused = list.contains(document.activeElement) ? document.activeElement : null;
  const keep = focused && focused.closest('.preset-row')
    ? { id: focused.closest('.preset-row').dataset.presetId, act: focused.dataset.act } : null;
  list.textContent = '';
  for (const p of presets) list.appendChild(_presetRow(p));
  if (!presets.some(p => p.id !== 'default')) {
    list.appendChild(_el('p', 'preset-empty', 'No presets saved yet. Set the chart’s axes above, then Save as new preset.'));
  }
  if (keep) {
    const row = _presetRowEl(keep.id);
    const button = row && [...row.querySelectorAll('button')].find(b => b.dataset.act === keep.act);
    if (button) button.focus();
  }
}

/** A preset's row, found by its id (which can come from a file, so is never put in a selector). */
function _presetRowEl(id) {
  return [...document.querySelectorAll('#presetManagerList .preset-row')].find(r => r.dataset.presetId === id) || null;
}

/** One saved preset: the row uses it, and its buttons edit, update or delete it. */
function _presetRow(p) {
  const row = _el('div', 'preset-row');
  row.dataset.presetId = p.id;
  const use = _el('button', 'preset-use');
  use.type = 'button';
  use.dataset.act = 'use';
  use.setAttribute('role', 'radio');
  use.title = p.id === 'default' ? 'Fit both axes to the data' : 'Use this preset on the chart';
  const axes = _el('span', 'preset-axes');
  if (p.id === 'default') {
    axes.append(_el('span', 'preset-axis', 'Both axes fit the data'));
  } else {
    const shown = _inPresetUnits(p);
    axes.append(_presetAxisCell(shown, 'x'), _presetAxisCell(shown, 'y'));
  }
  use.append(_el('span', 'preset-radio'), _el('span', 'preset-name', p.name), axes);
  use.addEventListener('click', () => _usePreset(p.id));
  row.append(use);
  if (p.id !== 'default') {
    const act = (label, title, onClick, className = 'preset-act') => {
      const button = _presetButton(label, title, onClick, className);
      button.dataset.act = label.toLowerCase();
      return button;
    };
    const actions = _el('span', 'preset-actions');
    actions.append(
      act('Edit', 'Change its name, scales, prefixes and limits', () => _editPreset(p.id)),
      act('Update', 'Replace its axes with the chart’s as they are now', () => _updatePresetFromView(p.id)),
      act('Delete', 'Delete this preset', () => _deletePreset(p.id), 'preset-act preset-act-delete'));
    row.append(actions);
  }
  return row;
}

/**
 * One axis of a preset, as its row shows it: X log · 100 – 10⁵, its prefix
 * in a pill, and the same in words for a pointer resting on it.
 *
 * @param {Object} p - The preset, its limits in its prefix's units (_inPresetUnits)
 * @param {string} axis - 'x' or 'y'
 */
function _presetAxisCell(p, axis) {
  const A = axis.toUpperCase();
  const scale = p[axis + 'Scale'];
  const lo = p[axis + 'Min'];
  const hi = p[axis + 'Max'];
  const ranged = lo != null && hi != null;
  const prefix = p[axis + 'Prefix'];
  const cell = _el('span', 'preset-axis');
  const parts = [];
  if (scale === 'linear' || scale === 'log') parts.push(scale === 'log' ? 'log' : 'lin');
  parts.push(ranged ? _fmtRange(lo, hi) : 'auto');
  cell.append(_el('b', null, A), document.createTextNode(' ' + parts.join(' · ')));
  if (prefixExponent(prefix) || prefix === '') cell.append(_el('span', 'preset-pfx', prefix || 'no prefix'));
  cell.title = `${A} axis: ` + [
    scale === 'linear' || scale === 'log' ? `${scale} scale` : 'the chart’s own scale',
    ranged ? `${lo} to ${hi}` : 'fitted to the data',
    prefixExponent(prefix) ? `with the prefix ${prefix}` : (prefix === '' ? 'with no prefix' : '')
  ].filter(Boolean).join(', ');
  return cell;
}

/** A click on a preset: it is used, as choosing it in the dropdown uses it. */
function _usePreset(id) {
  if (!_timeChartOnScreen() || _axesLocked) return Promise.resolve();
  const sel = document.getElementById('presetSelect');
  if (sel) sel.value = id;
  _removeCustomOption();
  return applyPresetById(id);
}

/** Edit a preset, in a form under its row. */
function _editPreset(id) {
  _cancelPresetEdit();
  const p = loadPresets().find(x => x.id === id);
  const row = _presetRowEl(id);
  if (!p || !row) return;
  const form = _el('div', 'preset-edit');
  form.id = 'presetEditForm';
  form.dataset.presetId = id;
  const label = _el('label', 'preset-edit-name', 'Name');
  const name = _el('input');
  name.type = 'text';
  name.id = 'pe_name';
  name.autocomplete = 'off';
  name.value = p.name;
  label.append(name);
  const buttons = _el('div', 'preset-buttons');
  const cancel = _presetButton('Cancel', 'Leave the preset as it was (Esc)', () => _cancelPresetEdit());
  cancel.id = 'pe_cancel';
  const save = _presetButton('Save', 'Save the preset (Enter)', () => _savePresetEdit(id), 'preset-btn primary');
  save.id = 'pe_save';
  buttons.append(_el('span', 'preset-spacer'), cancel, save);
  form.append(label, _axisGrid('pe_', _inPresetUnits(p), { keep: true }),
    _el('p', 'preset-help', 'Min and Max empty: the axis fits the data. Keep: the chart’s own scale or prefix stays as it is.'),
    buttons);
  row.classList.add('is-editing');
  row.after(form);
  _keepPresetPanelInView();
  name.focus();
  name.select();
}

function _cancelPresetEdit() {
  const form = document.getElementById('presetEditForm');
  if (!form) return;
  const row = _presetRowEl(form.dataset.presetId);
  const hadFocus = form.contains(document.activeElement);
  form.remove();
  if (row) {
    row.classList.remove('is-editing');
    const edit = [...row.querySelectorAll('button')].find(b => b.dataset.act === 'edit');
    if (hadFocus && edit) edit.focus();
  }
  _presetPanelSync();   // the list may have waited for the form to close
}

function _savePresetEdit(id) {
  const presets = loadPresets();
  const p = presets.find(x => x.id === id);
  if (!p) return;

  const nameVal = (document.getElementById('pe_name').value || '').trim();
  if (!nameVal) { notifyUser('Give the preset a name before saving.'); return; }
  const same = presets.find(x => x.id !== id && String(x.name).trim().toLowerCase() === nameVal.toLowerCase());
  if (same) { notifyUser(`There is a preset called “${same.name}” already: choose another name.`); return; }

  const f = _readAxisForm('pe_');
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
  _cancelPresetEdit();
  populatePresetDropdown();
  // The selected preset stays selected and the chart follows the edit.
  if (_selectedPresetId() === id) applyPresetById(id);
}

/** Update: a preset's axes replaced with the chart's, once the reader says so. */
async function _updatePresetFromView(id) {
  if (!_timeChartOnScreen()) { notifyUser('Draw a chart first — there is no view to save yet.'); return; }
  const target = loadPresets().find(x => x.id === id);
  if (!target) return;
  const asked = await rbAskConfirm({
    title: 'Update preset',
    message: `Replace the axes of “${target.name}” with the chart’s as they are now?`,
    okLabel: 'Update'
  });
  if (!asked) return;
  const presets = loadPresets();
  const p = presets.find(x => x.id === id);
  const view = _captureCurrentView();
  if (!p || !view) return;
  Object.assign(p, view);
  savePresetsToStorage(presets);
  populatePresetDropdown();
  // The view on screen is this preset's now.
  const sel = document.getElementById('presetSelect');
  if (sel) sel.value = id;
  _removeCustomOption();
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
  const form = document.getElementById('presetEditForm');
  if (form && form.dataset.presetId === id) _cancelPresetEdit();
  let presets = loadPresets();
  presets = presets.filter(x => x.id !== id);
  savePresetsToStorage(presets);
  populatePresetDropdown();
  // The chart keeps the view the deleted preset gave it, which is now no
  // preset's; without a chart there is no view, and Auto range stands.
  if (wasSelected && _timeChartOnScreen()) _markCustomPreset();
}

/* ---------- Moving the window ---------- */

function _wirePresetPanel(panel) {
  if (panel.dataset.wired) return;
  panel.dataset.wired = '1';
  panel.addEventListener('keydown', _presetPanelKey);
  _makePresetPanelMovable(panel);
}

/**
 * Keys in the window: Escape cancels what is being edited, else reverts the
 * chart's-axes fields if they were changed, else closes the window. Enter in
 * a field saves a preset's form, or applies the chart's axes. The window
 * listens only to keys typed in it: it does not block the page, and an
 * Escape meant for anything else is not its own.
 */
function _presetPanelKey(e) {
  if (e.key === 'Escape') {
    e.preventDefault();
    e.stopPropagation();
    if (e.target.closest('#presetEditForm')) _cancelPresetEdit();
    else if (_presetNow.dirty && e.target.closest('#presetNow')) _revertChartNow();
    else closePresetManager();
    return;
  }
  if (e.key !== 'Enter' || !e.target.matches('input, select')) return;
  const form = e.target.closest('#presetEditForm');
  if (form) {
    e.preventDefault();
    _savePresetEdit(form.dataset.presetId);
  } else if (e.target.closest('#presetNow')) {
    e.preventDefault();
    _chartNowEdited();
    _applyChartNow();
  }
}

/**
 * The window moves by its title bar, kept inside the window of the browser
 * and below the page's header; a double click on the bar puts it back where
 * it first opens. Its grip moves it from the keyboard too, by 10 px an arrow
 * (50 with Shift). Where it is put is kept for the next time it opens.
 */
function _makePresetPanelMovable(panel) {
  const bar = panel.querySelector('.preset-panel-header');
  const grip = panel.querySelector('.preset-panel-grip');
  const handle = (e) => !e.target.closest('button') || e.target.closest('.preset-panel-grip');
  /*
    The pointer is followed on the window, not only through pointer capture:
    Chrome sometimes grants no capture -- a press where the last drag ended,
    a moment later -- and the moves then went to whatever was under the
    pointer, leaving the window behind. Stopping the pointerdown's default
    keeps the page (the chart's hover among it) from seeing the drag's moves.
  */
  bar.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 || !handle(e)) return;
    const r = panel.getBoundingClientRect();
    const id = e.pointerId;
    const dx = e.clientX - r.left;
    const dy = e.clientY - r.top;
    const move = (ev) => {
      if (ev.pointerId === id) _placePresetPanel({ left: ev.clientX - dx, top: ev.clientY - dy });
    };
    const stop = (ev) => {
      if (ev.pointerId !== id) return;
      window.removeEventListener('pointermove', move, true);
      window.removeEventListener('pointerup', stop, true);
      window.removeEventListener('pointercancel', stop, true);
      panel.classList.remove('is-moving');
      _rememberPresetPanelPlace();
    };
    window.addEventListener('pointermove', move, true);
    window.addEventListener('pointerup', stop, true);
    window.addEventListener('pointercancel', stop, true);
    try { bar.setPointerCapture(id); } catch (err) { ignoreFailure('presetPanelDrag', err); }
    panel.classList.add('is-moving');
    e.preventDefault();
  });
  bar.addEventListener('dblclick', (e) => {
    if (!handle(e)) return;
    _forgetPresetPanelPlace();
    _placePresetPanel(_defaultPresetPanelPlace(panel));
  });
  grip.addEventListener('keydown', (e) => {
    const step = e.shiftKey ? 50 : 10;
    const by = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
    if (!by) return;
    e.preventDefault();
    const r = panel.getBoundingClientRect();
    _placePresetPanel({ left: r.left + by[0], top: r.top + by[1] });
    _rememberPresetPanelPlace();
  });
  // A smaller browser window keeps it in view.
  window.addEventListener('resize', () => {
    if (panel.hidden) return;
    const r = panel.getBoundingClientRect();
    _placePresetPanel({ left: r.left, top: r.top });
  });
  /*
    Until the reader puts it somewhere, it keeps below the chart's controls,
    which wrap onto another line as they fill: "Showing 2/9 traces" appears
    beside them after a zoom, and covered by the window, the gear and the
    preset dropdown were out of reach.
  */
  const controls = document.querySelector('#plotlyChartContainer .chart-controls');
  if (controls && typeof ResizeObserver === 'function') {
    new ResizeObserver(() => {
      if (!panel.hidden && !_savedPresetPanelPlace()) _placePresetPanel(_defaultPresetPanelPlace(panel));
    }).observe(controls);
  }
}

/**
 * Put the window at `left`, `top` (px), or as near as keeps it all in view
 * below the page's header. It is never taller than that room: what it holds
 * scrolls in it instead.
 */
function _placePresetPanel({ left, top }) {
  const panel = _presetPanel();
  if (!panel) return;
  const header = document.querySelector('body > header');
  const minTop = header ? Math.max(0, header.getBoundingClientRect().bottom) : 0;
  panel.style.maxHeight = `${Math.max(160, window.innerHeight - minTop - 8)}px`;
  const maxLeft = Math.max(0, window.innerWidth - panel.offsetWidth);
  const maxTop = Math.max(minTop, window.innerHeight - panel.offsetHeight);
  panel.style.left = `${Math.round(Math.min(Math.max(0, Number(left) || 0), maxLeft))}px`;
  panel.style.top = `${Math.round(Math.min(Math.max(minTop, Number(top) || 0), maxTop))}px`;
}

/** The window, kept in view after what it holds has grown: a preset's form opening near the bottom. */
function _keepPresetPanelInView() {
  const panel = _presetPanel();
  if (!panel || panel.hidden) return;
  const r = panel.getBoundingClientRect();
  _placePresetPanel({ left: r.left, top: r.top });
}

/**
 * Where it opens the first time: by the chart's right edge, below its
 * controls, so the gear and the preset list stay in reach and the plot's
 * left part in view; in the middle when no chart is drawn.
 */
function _defaultPresetPanelPlace(panel) {
  const chart = document.getElementById('plotlyChartContainer');
  const r = chart && chart.classList.contains('visible') ? chart.getBoundingClientRect() : null;
  if (r && r.width > panel.offsetWidth) {
    const controls = chart.querySelector('.chart-controls');
    const below = controls ? controls.getBoundingClientRect().bottom + 8 : r.top + 12;
    return { left: r.right - panel.offsetWidth - 16, top: below };
  }
  return { left: (window.innerWidth - panel.offsetWidth) / 2, top: 96 };
}

function _savedPresetPanelPlace() {
  try {
    const place = JSON.parse(localStorage.getItem(_PRESET_PANEL_PLACE_KEY) || 'null');
    return place && Number.isFinite(place.left) && Number.isFinite(place.top) ? place : null;
  } catch (_) {
    return null;
  }
}

function _rememberPresetPanelPlace() {
  const panel = _presetPanel();
  if (!panel) return;
  try {
    localStorage.setItem(_PRESET_PANEL_PLACE_KEY,
      JSON.stringify({ left: parseFloat(panel.style.left) || 0, top: parseFloat(panel.style.top) || 0 }));
  } catch (_) { ignoreFailure('_rememberPresetPanelPlace', _); }
}

function _forgetPresetPanelPlace() {
  try { localStorage.removeItem(_PRESET_PANEL_PLACE_KEY); } catch (_) { ignoreFailure('_forgetPresetPanelPlace', _); }
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
  _presetPanelSync();
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
  _presetPanelSync();
}

/** Remove the temporary "Custom *" option from the preset dropdown. */
function _removeCustomOption() {
  const sel = document.getElementById('presetSelect');
  if (!sel) return;
  const opt = sel.querySelector('option[value="__custom__"]');
  if (opt) opt.remove();
  _presetPanelSync();
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
  // The presets window follows the axes, whoever moves them: a zoom, a
  // preset, a prefix (Plotly.update), and this chart, just drawn.
  onPlotEvent(plotDiv, 'plotly_relayout', 'presetPanel', _presetPanelSync);
  onPlotEvent(plotDiv, 'plotly_update', 'presetPanelUpdate', _presetPanelSync);
  _presetPanelSync();
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
        // Replacing the selected preset is editing it: the chart follows,
        // unless the axes are locked.
        const selectedId = _selectedPresetId();
        if (!_axesLocked && selectedId !== 'default' && imported.some(p => p.id === selectedId)) {
          applyPresetById(selectedId);
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
