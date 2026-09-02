/* ==========================================================================
   HDF5 BROWSER ACTIONS

   The names the page's controls declare in their data-action attributes, and
   the functions they reach. The dispatch mechanism itself is shared with the
   rest of the site; see kvot-actions.js.

   Each entry is a thunk rather than a direct reference: the target functions
   live in rb-chart.js, rb-init.js and rb-tree.js, which load after this file.
   Resolving them when the action fires removes any load-order dependency.
   ========================================================================== */

registerActions({
  /* ── Loading files ────────────────────────────────────────────────────── */
  openFilePicker:         () => document.getElementById('fileInput').click(),
  openUrlDialog:          () => openUrlDialog(),
  closeUrlDialog:         () => closeUrlDialog(),
  loadFromUrl:            () => loadFromUrl(),
  openSampleDataDialog:   () => openSampleDataDialog(),
  closeSampleDataDialog:  () => closeSampleDataDialog(),
  loadSelectedSampleData: () => loadSelectedSampleData(),
  cancelTreeRefresh:      () => cancelTreeRefresh(),

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
  toggleAxesLock:      () => toggleAxesLock(),
  applySelectedPreset: () => applySelectedPreset(),
  saveCurrentAsPreset: () => saveCurrentAsPreset(),
  openPresetManager:   () => openPresetManager(),
  closePresetManager:  () => closePresetManager(),
  importPresets:       () => importPresets(),
  exportPresets:       () => exportPresets(),

  /* ── Data preview histogram ──────────────────────────────────────────── */
  redrawHistogram: () => redrawHistogram(),
});
