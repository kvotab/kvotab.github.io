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
  return fileOrder.filter(key => fileStates[key]);
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
 * Check if intersect mode is active.
 * @returns {boolean}
 */
function isIntersectMode() {
  const cb = document.getElementById('intersectCheckbox');
  return cb && cb.checked && getEnabledFiles().length > 1;
}

/**
 * Get the list of files to use for info/charts.
 * In non-intersect mode with a specific file selected, returns just that file.
 * In intersect mode, returns all enabled files.
 * @returns {string[]}
 */
function getEffectiveFiles() {
  if (isIntersectMode()) {
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

  // If Intersect mode is active, trigger the same UI + full recompute
  // as toggling the Intersect checkbox (preserves previous fix behavior).
  if (isIntersectMode()) {
    try {
      toggleIntersect();
      return;
    } catch (e) {
      console.warn('[toggleFileState] toggleIntersect fallback', e);
    }
  }

  // coalesce rapid toggles to avoid repeated expensive tree rebuilds
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
  delete loadedFiles[fileName];
  delete fileStates[fileName];
  delete loadedFileBuffers[fileName];
  fileOrder = fileOrder.filter(k => k !== fileName);
  
  const enabledFiles = getEnabledFiles();
  
  updateTabs();
  
  if (enabledFiles.length === 0) {
    // No enabled files - clear UI
    currentTreeFile = null;
    const tree = document.getElementById('tree');
    tree.innerHTML = '<div class="loading">Drop HDF5 files or click "+ Add Files" to start...</div>';
    tree.classList.add('loading');
    resetInfoPanel();
    hideChart();
    selectedDatasetPath = null;
    selectedIsRadionuclidesGroup = false;
    
    document.querySelector('.search-container').classList.remove('visible');
    
    const hint = document.getElementById('multiSelectHint');
    if (hint) {
      hint.style.display = 'none';
    }
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


