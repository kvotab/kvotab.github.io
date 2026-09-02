/* ==========================================================================
   UI ACTIONS

   rb.html used to wire its controls with 28 inline `onclick` / `onchange` /
   `oninput` attributes. That had three costs:

     - the set of entry points into the application was invisible: you could
       only find them by grepping the HTML for `on*=`;
     - every handler ran outside any error boundary, so a throwing toggle left
       the UI half-updated with nothing but a browser console entry;
     - the markup depended on each function being a global with exactly that
       name, which quietly blocked any move towards modules.

   Now every control declares what it does:

       <button data-action="openUrlDialog">
       <input type="checkbox" data-action="toggleShowTotal" data-action-on="change">

   and this file holds the only mapping from those names to behaviour. The
   handlers are looked up through the table below at dispatch time, so this
   file does not care in what order the other scripts loaded.

   Adding a control means adding one line here and one attribute there.
   ========================================================================== */

/*
  Each entry is a thunk rather than a direct function reference: the target
  functions live in rb-chart.js, rb-init.js and rb-tree.js, which may load
  after this file. Resolving them when the action fires removes any load-order
  dependency.
*/
const RB_ACTIONS = Object.freeze({
  /* ── Loading files ────────────────────────────────────────────────────── */
  openFilePicker:        () => document.getElementById('fileInput').click(),
  openUrlDialog:         () => openUrlDialog(),
  closeUrlDialog:        () => closeUrlDialog(),
  loadFromUrl:           () => loadFromUrl(),
  openSampleDataDialog:  () => openSampleDataDialog(),
  closeSampleDataDialog: () => closeSampleDataDialog(),
  loadSelectedSampleData: () => loadSelectedSampleData(),
  cancelTreeRefresh:     () => cancelTreeRefresh(),

  /* ── Chart series and overlays ────────────────────────────────────────── */
  toggleDynamicLegend:     () => toggleDynamicLegend(),
  toggleShowTotal:         () => toggleShowTotal(),
  toggleShowRatio:         () => toggleShowRatio(),
  toggleShowMax:           () => toggleShowMax(),
  toggleShowCI:            () => toggleShowCI(),
  toggleShowSDOM:          () => toggleShowSDOM(),
  toggleShowIteration:     () => toggleShowIteration(),
  toggleBackgroundOverlay: () => toggleBackgroundOverlay(),

  /* ── Axes and presets ────────────────────────────────────────────────── */
  toggleAxesLock:       () => toggleAxesLock(),
  applySelectedPreset:  () => applySelectedPreset(),
  saveCurrentAsPreset:  () => saveCurrentAsPreset(),
  openPresetManager:    () => openPresetManager(),
  closePresetManager:   () => closePresetManager(),
  importPresets:        () => importPresets(),
  exportPresets:        () => exportPresets(),

  /* ── Data preview histogram ──────────────────────────────────────────── */
  redrawHistogram: () => redrawHistogram(),
});

/*
  Which DOM event each control reacts to. A checkbox fires `click` and then
  `change`, so a single delegated listener matching on `[data-action]` alone
  would run its handler twice. `data-action-on` keeps the pairing explicit and
  identical to the attribute it replaced.
*/
const RB_ACTION_EVENTS = Object.freeze(['click', 'change', 'input']);
const RB_DEFAULT_ACTION_EVENT = 'click';

/**
 * Run one declared action, reporting rather than swallowing any failure.
 *
 * @param {string} name - Value of the element's data-action attribute
 * @param {Element} element - The element that declared the action
 * @returns {void}
 */
function runRbAction(name, element) {
  const handler = RB_ACTIONS[name];
  if (!handler) {
    reportFailure('runRbAction', new Error(`No handler registered for data-action="${name}"`));
    return;
  }
  try {
    const result = handler();
    /* Several handlers are async; an unhandled rejection is still a failure. */
    if (result && typeof result.catch === 'function') {
      result.catch(error => reportFailure(`action:${name}`, error, {
        userMessage: `“${describeControl(element)}” did not complete.`
      }));
    }
  } catch (error) {
    reportFailure(`action:${name}`, error, {
      userMessage: `“${describeControl(element)}” failed.`
    });
  }
}

/**
 * A human-readable name for a control, for use in failure messages.
 *
 * @param {Element} element
 * @returns {string}
 */
function describeControl(element) {
  if (!element) return 'This control';
  const label = element.getAttribute('aria-label')
    || element.getAttribute('title')
    || (element.textContent || '').trim()
    || (element.closest('label') ? (element.closest('label').textContent || '').trim() : '');
  const cleaned = label.replace(/\s+/g, ' ').trim();
  return cleaned ? cleaned.slice(0, 60) : (element.id || element.tagName.toLowerCase());
}

/**
 * Install one delegated listener per event type. Delegation also means
 * controls rendered later — the toolbar buttons that KVOT.renderHeader
 * injects, for one — need no separate wiring.
 *
 * @returns {void}
 */
function installRbActions() {
  for (const type of RB_ACTION_EVENTS) {
    document.addEventListener(type, event => {
      const element = event.target.closest ? event.target.closest('[data-action]') : null;
      if (!element) return;
      const wants = element.dataset.actionOn || RB_DEFAULT_ACTION_EVENT;
      if (wants !== type) return;
      runRbAction(element.dataset.action, element);
    });
  }
}

installRbActions();
