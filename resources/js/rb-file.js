/* ==========================================================================
   4. FILE MANAGEMENT
   ========================================================================== */

/**
 * Get list of filenames for currently enabled (visible) files.
 * Maintains the order from fileOrder array.
 * 
 * @returns {string[]} Array of enabled filenames in display order
 */
function getEnabledFiles() {
  return fileOrder.filter(key => {
    if (!fileStates[key]) return false;
    if (typeof getFileOrNull === 'function') return !!getFileOrNull(key);
    return !!loadedFiles[key];
  });
}

/**
 * Get the filename of the first enabled file.
 * This file's structure is used to render the tree view.
 * 
 * @returns {string|null} Filename of first enabled file, or null if none enabled
 */
function getTreeFile() {
  const enabledFiles = getEnabledFiles();
  return enabledFiles.length > 0 ? enabledFiles[0] : null;
}

/**
 * Get the current tree display mode.
 * @returns {'separated'|'intersect'|'union'}
 */
function getTreeMode() {
  if (getEnabledFiles().length < 2) return 'separated';
  const active = document.querySelector('#treeModeContainer button.active');
  return (active && active.dataset.value) || 'separated';
}

/**
 * Check if intersect mode is active.
 * @returns {boolean}
 */
function isIntersectMode() {
  return getTreeMode() === 'intersect';
}

/**
 * Check if union mode is active.
 * @returns {boolean}
 */
function isUnionMode() {
  return getTreeMode() === 'union';
}

/**
 * Reset the tree mode toggle to "separated" and clear all selections.
 * Called whenever file tabs change (enable/disable, add/remove, reorder)
 * to avoid complex stale-state issues with intersect/union modes.
 */
function resetTreeModeToSeparated() {
  // Reset toggle button UI
  const treeModeContainer = document.getElementById('treeModeContainer');
  if (treeModeContainer) {
    treeModeContainer.querySelectorAll('button').forEach(b =>
      b.classList.toggle('active', b.dataset.value === 'separated')
    );
  }

  // Clear cached intersect/union data
  window._currentIntersectedPaths = null;
  window._unionPathOwnership = null;

  // Clear selection state
  selectedDatasetPath = null;
  selectedIsRadionuclidesGroup = false;
  selectedFileKey = null;
  selectedDatasets = [];
  multiSelectMode = false;

  // Reset right-hand panel
  try { resetInfoPanel(); } catch (e) { /* ignore */ }
  try { hideChart(); } catch (e) { /* ignore */ }

  // Remove visual selection in tree
  try {
    document.querySelectorAll('.tree-item.dataset.selected').forEach(el => el.classList.remove('selected'));
    document.querySelectorAll('.tree-item.group.expanded').forEach(el => el.classList.remove('expanded'));
  } catch (e) { /* ignore */ }

  // Hide multi-select hint
  try {
    const hint = document.getElementById('multiSelectHint');
    if (hint) hint.style.display = 'none';
  } catch (e) { /* ignore */ }

  console.debug('[resetTreeModeToSeparated] tree mode reset to separated, selections cleared');
}

/**
 * Get the list of files to use for info/charts.
 * In separated mode with a specific file selected, returns just that file.
 * In intersect/union modes, returns all enabled files.
 * @returns {string[]}
 */
function getEffectiveFiles() {
  if (isIntersectMode() || isUnionMode()) {
    return getEnabledFiles();
  }
  if (selectedFileKey && loadedFiles[selectedFileKey]) {
    return [selectedFileKey];
  }
  return getEnabledFiles();
}

/**
 * Toggle a file's enabled/disabled state and update the UI.
 * Enabled files contribute data to charts; disabled files are hidden.
 * 
 * @param {string} fileName - The filename to toggle
 */
function toggleFileState(fileName) {
  fileStates[fileName] = !fileStates[fileName];
  console.debug('[toggleFileState]', fileName, 'newState=', fileStates[fileName]);

  // Immediate visual update: change the tab element class so colour/state
  // responds instantly without waiting for the expensive tree recalculation.
  try {
    const tabs = document.querySelectorAll('.file-tab');
    for (const t of tabs) {
      if (t.getAttribute('data-file') === fileName) {
        t.classList.toggle('enabled', !!fileStates[fileName]);
        t.classList.toggle('disabled', !fileStates[fileName]);
        break;
      }
    }
  } catch (e) { /* ignore DOM update errors */ }

  // Always reset tree mode to separated and clear selections on any tab change.
  // updateTabs() will handle the full reset.
  scheduleUpdateTabs();
}

/**
 * Schedule an updateTabs call with debounce so rapid tab toggles are coalesced
 * into a single tree refresh. Useful when users rapidly enable/disable files.
 */
function scheduleUpdateTabs(delay = UPDATE_TABS_DEBOUNCE_MS) {
  if (_updateTabsDebounceTimer) clearTimeout(_updateTabsDebounceTimer);
  _updateTabsDebounceTimer = setTimeout(() => {
    _updateTabsDebounceTimer = null;
    updateTabs();
  }, delay);
}

/**
 * Remove a file completely from the viewer.
 * Cleans up all references and updates the UI. If this was the last
 * file, resets the viewer to its initial empty state.
 * 
 * @param {string} fileName - The filename to remove
 * @returns {Promise<void>}
 */
async function removeFile(fileName) {
  const wasEnabled = !!fileStates[fileName];

  delete loadedFiles[fileName];
  delete fileStates[fileName];
  delete loadedFileBuffers[fileName];
  fileOrder = fileOrder.filter(k => k !== fileName);
  
  if (!wasEnabled) {
    // Disabled file had no effect on the tree — just remove its tab element
    // without resetting tree mode, selections, or triggering a tree rebuild.
    try {
      const tab = document.querySelector(`.file-tab[data-file="${CSS.escape(fileName)}"]`);
      if (tab) tab.remove();
    } catch (e) { /* ignore */ }
    return;
  }

  // Enabled file removed — full reset via updateTabs()
  updateTabs();
  
  if (getEnabledFiles().length === 0) {
    // No enabled files - show initial placeholder
    currentTreeFile = null;
    const tree = document.getElementById('tree');
    tree.innerHTML = '<div class="loading">Drop HDF5 files or click "+ Add Files" to start...</div>';
    tree.classList.add('loading');
    
    document.querySelector('.search-container').classList.remove('visible');
  }
}

/**
 * Refresh the info panel and chart display after file selection changes.
 * Verifies the selected path still exists in the current tree file.
 * If the path no longer exists, clears the selection.
 * 
 * @returns {void}
 */
function refreshInfoAndChart() {
  if (!selectedDatasetPath) {
    return;
  }

  // Use selectedFileKey if available, otherwise first enabled file
  const checkFile = selectedFileKey || getTreeFile();
  
  // If the selected path no longer exists in the current file OR
  // is excluded by the active intersected-path set, clear selection.
  const intersected = window._currentIntersectedPaths || getIntersectedPaths();
  if (!checkFile || !checkIfPathExistsInFile(checkFile, selectedDatasetPath) || (isIntersectMode() && intersected && !intersected.has(selectedDatasetPath))) {
    // Clear selection if path doesn't exist or is outside the intersection
    resetInfoPanel();
    hideChart();
    selectedDatasetPath = null;
    selectedIsRadionuclidesGroup = false;
    selectedFileKey = null;
    
    document.querySelectorAll('.tree-item.dataset.selected').forEach(el => el.classList.remove('selected'));
    document.querySelectorAll('.tree-item.group.expanded').forEach(el => el.classList.remove('expanded'));
    return;
  }

  // Path exists, refresh display
  if (selectedIsRadionuclidesGroup) {
    showNodeAttributes(selectedDatasetPath, true);
    Promise.resolve().then(() => createRadionuclidesChart(selectedDatasetPath));
  } else {
    showNodeAttributes(selectedDatasetPath, false);
    
    try {
      const file = loadedFiles[checkFile];
      const dataset = FileService.get(file, selectedDatasetPath);
      if (dataset && dataset.type.toLowerCase() === 'dataset' && isTimeDependent(dataset)) {
        createPlotlyChart(selectedDatasetPath);
      }
    } catch (e) {
      console.warn('Error checking if dataset is time-dependent:', e);
    }
  }
}


