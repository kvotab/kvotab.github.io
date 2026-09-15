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
  try { resetInfoPanel(); } catch (e) { ignoreFailure('resetTreeModeToSeparated', e); }
  try { hideChart(); } catch (e) { ignoreFailure('resetTreeModeToSeparated', e); }

  // Remove visual selection in tree
  try {
    document.querySelectorAll('.tree-item.dataset.selected').forEach(el => el.classList.remove('selected'));
    document.querySelectorAll('.tree-item.group.expanded').forEach(el => el.classList.remove('expanded'));
  } catch (e) { ignoreFailure('resetTreeModeToSeparated', e); }

  // Hide multi-select hint
  try {
    const hint = document.getElementById('multiSelectHint');
    if (hint) hint.style.display = 'none';
  } catch (e) { ignoreFailure('resetTreeModeToSeparated', e); }

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
  } catch (e) { ignoreFailure('toggleFileState', e); }

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

  releaseLoadedFile(fileName);
  delete fileStates[fileName];
  delete loadedFileBuffers[fileName];
  fileOrder = fileOrder.filter(k => k !== fileName);
  
  if (!wasEnabled) {
    // Disabled file had no effect on the tree — just remove its tab element
    // without resetting tree mode, selections, or triggering a tree rebuild.
    try {
      const tab = document.querySelector(`.file-tab[data-file="${CSS.escape(fileName)}"]`);
      if (tab) tab.remove();
    } catch (e) { ignoreFailure('removeFile', e); }
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



/* ==========================================================================
   4b. BUFFER INGESTION

   Every way of getting a file into this page — the picker, a drop, the URL
   dialog, the sample-data list, a postMessage handoff — ends in the same four
   steps: validate the bytes, write them into the h5wasm filesystem, open a
   handle, and register the file. That sequence used to be copied at each call
   site; it lives here now so a new transport is a fetch plus one call.
   ========================================================================== */

/**
 * Mount an in-memory HDF5 file and register it under a display name.
 *
 * Does not refresh the tree — callers usually load several files and want a
 * single updateTabs(true) at the end.
 *
 * @param {string} fileName - Display name; an existing file of this name is replaced
 * @param {ArrayBuffer} buffer - Raw file bytes
 * @param {string} [context] - Label for failure reporting
 * @returns {Promise<string>} The display name the file was registered under
 * @throws {Error} If the bytes are empty, oversized, not HDF5, or h5wasm is unavailable
 */
async function ingestHdf5Buffer(fileName, buffer, context = 'ingestHdf5Buffer') {
  if (!buffer || typeof buffer.byteLength !== 'number' || buffer.byteLength === 0) {
    throw new Error(`${fileName} is empty.`);
  }

  /*
    The picker checks size before reading, which is better because it avoids
    the read entirely. This is the backstop for the transports that hand over
    bytes already in memory, where there is nothing to check beforehand.
  */
  if (buffer.byteLength > KVOT_FILE_SIZE_LIMITS.dataset) {
    throw new Error(kvotFileTooLarge({ name: fileName, size: buffer.byteLength },
                                     KVOT_FILE_SIZE_LIMITS.dataset).reason);
  }

  const h5Check = validateHdf5Buffer(buffer);
  if (!h5Check.ok) throw new Error(`${fileName}: ${h5Check.reason}`);

  await waitForH5Wasm();
  const { FS, File } = window.h5wasm;
  if (!FS || !File) throw new Error('h5wasm not ready');

  loadedFileBuffers[fileName] = buffer;

  const internalName = `file_${Date.now()}_${Math.random().toString(36).substr(2, 9)}.h5`;
  FS.writeFile('/' + internalName, new Uint8Array(buffer));
  const hf = new File('/' + internalName, 'r');

  if (loadedFiles[fileName]) {
    try { loadedFiles[fileName].close(); } catch (_) { ignoreFailure(context, _); }
  }

  loadedFiles[fileName] = hf;
  fileStates[fileName] = true;
  if (!fileOrder.includes(fileName)) fileOrder.push(fileName);

  return fileName;
}

/**
 * Derive a display name from a URL's last path segment.
 * blob: and data: URLs carry no meaningful name, so they get a generated one.
 *
 * @param {URL} parsed
 * @returns {string} A name ending in .h5 / .hdf5 / .he5
 */
function hdf5FileNameFromUrl(parsed) {
  const parts = (parsed.pathname || '').split('/').filter(Boolean);
  let name = parts.length > 0 ? decodeURIComponent(parts[parts.length - 1]) : '';
  if (parsed.protocol === 'blob:' || parsed.protocol === 'data:' || !name) {
    name = 'handoff.h5';
  }
  if (!/\.(h5|hdf5|he5)$/i.test(name)) name += '.h5';
  return name;
}

/**
 * Fetch an HDF5 file over http(s) or from a blob: URL and mount it.
 * Does not refresh the tree.
 *
 * @param {string} url
 * @param {string} [context] - Label for failure reporting
 * @returns {Promise<string>} The display name the file was registered under
 */
async function ingestHdf5FromUrl(url, context = 'ingestHdf5FromUrl') {
  let parsed;
  try {
    parsed = new URL(url, window.location.href);
  } catch (_) {
    throw new Error('Invalid URL format.');
  }

  if (!['https:', 'http:', 'blob:'].includes(parsed.protocol)) {
    throw new Error(`Unsupported URL scheme "${parsed.protocol}".`);
  }

  const fileName = hdf5FileNameFromUrl(parsed);
  const response = await fetch(parsed.href);
  if (!response.ok) throw new Error(`HTTP ${response.status} ${response.statusText}`);

  const buffer = await response.arrayBuffer();
  return ingestHdf5Buffer(fileName, buffer, context);
}
