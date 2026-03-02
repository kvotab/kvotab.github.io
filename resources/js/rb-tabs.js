/* ==========================================================================
   5. TAB MANAGEMENT
   ========================================================================== */

/**
 * Update the file tabs display and reinitialize drag-drop sorting.
 * Renders a tab for each loaded file, handles click-to-toggle and
 * drag-to-reorder functionality via SortableJS.
 * 
 * Tab states:
 * - enabled: File data included in charts (blue indicator)
 * - disabled: File loaded but hidden from charts (gray)
 * 
 * @returns {void}
 */
function updateTabs() {
  const tabsContainer = document.getElementById('fileTabs');
  const previousTreeFile = currentTreeFile;
  
  // Render tabs
  tabsContainer.innerHTML = fileOrder.map(key => {
    const isEnabled = fileStates[key];
    return `
      <div class="file-tab ${isEnabled ? 'enabled' : 'disabled'}" data-file="${escapeHtml(key)}">
        <div class="file-tab-name" title="${escapeHtml(key)}">${escapeHtml(key)}</div>
        <div class="file-tab-close" onclick="event.stopPropagation(); removeFile('${key.replace(/'/g, "\\'")}')">×</div>
      </div>
    `;
  }).join('');
  
  // Add click handlers for toggle
  document.querySelectorAll('.file-tab').forEach(tab => {
    const fileName = tab.getAttribute('data-file');
    tab.addEventListener('click', (e) => {
      if (!e.target.classList.contains('file-tab-close')) {
        toggleFileState(fileName);
      }
    });
  });
  
  // Initialize SortableJS for drag reordering
  if (window.Sortable && tabsContainer.children.length > 0) {
    Sortable.create(tabsContainer, {
      animation: 150,
      ghostClass: 'sortable-ghost',
      dragClass: 'sortable-drag',
      onEnd: function(evt) {
        const previousFirst = currentTreeFile;
        
        const newOrder = Array.from(tabsContainer.children).map(
          tab => tab.getAttribute('data-file')
        );
        fileOrder = newOrder;
        
        const newTreeFile = getTreeFile();
        currentTreeFile = newTreeFile;
        
        const treeFileChanged = previousFirst !== newTreeFile;
        
        console.log('Drag ended - Previous:', previousFirst, 'New:', newTreeFile, 'Changed:', treeFileChanged);
        
        if (treeFileChanged) {
          refreshTreeStructure();
        }
        
        refreshInfoAndChart();
      }
    });
  }
  
  // Check if tree file changed
  const newTreeFile = getTreeFile();
  const treeFileChanged = previousTreeFile !== newTreeFile;
  currentTreeFile = newTreeFile;
  
  // Show/hide tree mode selector based on number of enabled files
  const treeModeContainer = document.getElementById('treeModeContainer');
  const enabledCount = getEnabledFiles().length;
  if (treeModeContainer) {
    treeModeContainer.style.display = enabledCount > 1 ? 'inline-flex' : 'none';
    // Reset to separated if only one file left
    if (enabledCount <= 1) {
      treeModeContainer.querySelectorAll('button').forEach(b => b.classList.toggle('active', b.dataset.value === 'separated'));
    }
  }

  // If there are no enabled files, clear the right-hand panel and selection state
  if (enabledCount === 0) {
    try {
      resetInfoPanel();
      hideChart();
      selectedDatasetPath = null;
      selectedIsRadionuclidesGroup = false;
      selectedFileKey = null;

      document.querySelectorAll('.tree-item.dataset.selected').forEach(el => el.classList.remove('selected'));
      document.querySelectorAll('.tree-item.group.expanded').forEach(el => el.classList.remove('expanded'));
      document.querySelector('.search-container')?.classList.remove('visible');

      // notify listeners that selection was cleared
      try { EventBus.emit('selection:changed', { mode: 'none' }); } catch (e) {}
    } catch (e) { console.warn('updateTabs clear-selection-on-no-enabled-files failed', e); }
  }
  
  console.log('updateTabs - Previous:', previousTreeFile, 'New:', newTreeFile, 'Changed:', treeFileChanged);
  
  // Only refresh the tree when necessary (tree root changed or enabled set changed).
  // This prevents frequent/expensive refreshes and avoids triggering search-aware
  // background expansions on unrelated UI clicks.
  const prevEnabledCount = window._lastEnabledCount || 0;
  const needRefresh = treeFileChanged || (enabledCount !== prevEnabledCount);
  window._lastEnabledCount = enabledCount;

  let refreshPromise;
  if (needRefresh) {
    const treeMode = getTreeMode();
    const isMergedMode = treeMode === 'intersect' || treeMode === 'union';

    // If there's any in-flight worker intersection request, cancel it
    // now: the user changed enabled files so we'll start a fresh run.
    try {
      for (const wid of Object.keys(_treeWorkerPending)) {
        try { ensureTreeWorker().postMessage({ cmd: 'cancel', id: wid }); } catch (e) {}
        try { clearTimeout(_treeWorkerPending[wid]._timeout); } catch (e) {}
        delete _treeWorkerPending[wid];
        console.debug('[updateTabs] cancelled in-flight worker id=', wid);
      }
    } catch (e) { /* ignore */ }

    // Immediate visual feedback in the tree while recalculation runs.
    try {
      const tree = document.getElementById('tree');
      if (tree) {
        if (isMergedMode) {
          const modeLabel = treeMode === 'intersect' ? 'Intersection' : 'Union';
          tree.innerHTML = `
            <div class="tree-item group root-node" data-path="/">
              <div class="tree-toggle no-toggle"></div>
              <div class="tree-icon folder"></div>
              <div class="tree-label">/ (${modeLabel}) <span class="tree-inline-spinner" aria-hidden="true"></span></div>
            </div>
            <div class="tree-group-children expanded" style="margin-left:20px;">
              <div class="loading" style="padding:8px;font-size:12px;">Calculating ${modeLabel.toLowerCase()}…</div>
            </div>
          `;
        } else {
          tree.innerHTML = `<div class="loading">Refreshing tree… <span class="tree-inline-spinner" aria-hidden="true"></span></div>`;
        }
        // force layout so the spinner paints immediately (Safari-safe)
        void tree.offsetHeight;
        document.querySelector('.search-container')?.classList.remove('visible');
      }
    } catch (e) { /* ignore UI update errors */ }

    // mark a refresh token early so the header ticker can show a cancel button
    if (isMergedMode) {
      window._treeRefreshId = (window._treeRefreshId || 0) + 1;
      window._treeRefreshCancelled = false;
    }

    // Show header ticker for recalculation
    if (isMergedMode) {
      const tickerMsg = treeMode === 'intersect' ? 'Recalculating intersection...' : 'Calculating union...';
      try { showFileLoadTicker(0, 0, tickerMsg); } catch (e) {}
    }

    // Run the refresh asynchronously (yield so the spinner is visible first)
    refreshPromise = new Promise((resolve, reject) => {
      setTimeout(() => {
        refreshTreeStructure().then(resolve, reject);
      }, 50);
    }).finally(() => {
      if (isMergedMode) {
        try { hideFileLoadTicker(); } catch (e) {}
      }
    });
  } else {
    refreshPromise = Promise.resolve();
  }

  refreshInfoAndChart();

  // Validate multi-selection against the active intersection (if any).
  function validateSelectedDatasets() {
    try {
      if (selectedDatasets && selectedDatasets.length > 0) {
        const intersected = window._currentIntersectedPaths || getIntersectedPaths();
        if (isIntersectMode() && intersected && intersected.size > 0) {
          const before = selectedDatasets.length;
          selectedDatasets = selectedDatasets.filter(d => intersected.has(d.path));
          if (selectedDatasets.length === 0) {
            // clear UI selection
            resetInfoPanel();
            hideChart();
            document.querySelectorAll('.tree-item.dataset.selected').forEach(el => el.classList.remove('selected'));
          } else if (selectedDatasets.length < before) {
            // update shown attributes for the remaining selection
            showMultipleDatasetAttributes(selectedDatasets);
          }
        } else {
          // Non-intersect: remove any selected entries that no longer exist
          selectedDatasets = selectedDatasets.filter(d => checkIfPathExistsInFile(d.fileKey || getTreeFile(), d.path));
          if (selectedDatasets.length === 0) {
            resetInfoPanel();
            hideChart();
            document.querySelectorAll('.tree-item.dataset.selected').forEach(el => el.classList.remove('selected'));
          } else {
            showMultipleDatasetAttributes(selectedDatasets);
          }
        }
      }
    } catch (e) { console.warn('validate-selected-datasets error', e); }
  }

  validateSelectedDatasets();

  // Re-validate selection after async refresh completes (important for intersect changes)
  if (needRefresh && refreshPromise) {
    refreshPromise.then(() => {
      refreshInfoAndChart();
      validateSelectedDatasets();
    }).catch(e => console.warn('post-refresh validation failed', e));
  }

  return refreshPromise;
}

