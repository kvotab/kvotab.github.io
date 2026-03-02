/* ==========================================================================
   15. EVENT LISTENERS & INITIALIZATION
   ========================================================================== */

/*
 * Application Initialization
 * 
 * The following code runs immediately when the script loads:
 * 1. Initialize DOM element cache for performance
 * 2. Register event handlers for file input, search, resize, etc.
 * 3. Set up keyboard shortcuts and accessibility features
 */

// Initialize cached DOM element references
initDOMReferences();

// EventBus listeners -------------------------------------------------
// Centralized selection handler — updates DOM classes and info/chart display
EventBus.on('selection:changed', (payload) => {
  try {
    const tree = document.getElementById('tree');

    if (!payload || !payload.mode) return; 

    // support explicit 'none' mode for clearing selection from other components

    if (payload.mode === 'none') {
      // clear UI selection and right panel
      document.querySelectorAll('.tree-item.dataset.selected').forEach(el => el.classList.remove('selected'));
      document.querySelectorAll('.tree-item.group.expanded').forEach(el => el.classList.remove('expanded'));
      resetInfoPanel();
      hideChart();
      selectedDatasetPath = null;
      selectedIsRadionuclidesGroup = false;
      selectedFileKey = null;
      return;
    }

    if (payload.mode === 'single') {
      // clear previous selection/expansions
      document.querySelectorAll('.tree-item.dataset.selected').forEach(el => el.classList.remove('selected'));
      document.querySelectorAll('.tree-item.group.expanded').forEach(el => el.classList.remove('expanded'));

      // mark the dataset element (if present)
      const items = Array.from(tree.querySelectorAll('.tree-item')).filter(el => el.getAttribute('data-path') === payload.path && (!payload.fileKey || el.getAttribute('data-file') === payload.fileKey));
      if (items.length > 0) {
        const el = items.find(n => n.classList.contains('dataset')) || items[0];
        if (el) el.classList.add('selected');
      }

      // show attributes / chart for single selection
      try { showNodeAttributes(payload.path, false); } catch (e) { console.warn('selection:changed handler showNodeAttributes failed', e); }
      return;
    }

    if (payload.mode === 'group') {
      // clear dataset selection, collapse groups, then expand/select the group
      document.querySelectorAll('.tree-item.dataset.selected').forEach(el => el.classList.remove('selected'));
      document.querySelectorAll('.tree-item.group.expanded').forEach(el => el.classList.remove('expanded'));

      const groupEl = Array.from(tree.querySelectorAll('.tree-item.group')).find(el => el.getAttribute('data-path') === payload.path && (!payload.fileKey || el.getAttribute('data-file') === payload.fileKey));
      if (groupEl) groupEl.classList.add('expanded');

      try { showNodeAttributes(payload.path, true); } catch (e) { console.warn('selection:changed handler showNodeAttributes(group) failed', e); }
      return;
    }

    if (payload.mode === 'multi') {
      // clear previous selection then mark provided items
      document.querySelectorAll('.tree-item.dataset.selected').forEach(el => el.classList.remove('selected'));
      const items = Array.isArray(payload.items) ? payload.items : [];
      for (const it of items) {
        const found = Array.from(tree.querySelectorAll('.tree-item.dataset')).find(el => el.getAttribute('data-path') === it.path && (!it.fileKey || el.getAttribute('data-file') === it.fileKey));
        if (found) found.classList.add('selected');
      }

      try { showMultipleDatasetAttributes(items); } catch (e) { console.warn('selection:changed handler showMultipleDatasetAttributes failed', e); }
      return;
    }
  } catch (e) {
    console.error('EventBus selection:changed handler error', e);
  }
});

// Theme-change handler (subscribed to EventBus by MutationObserver)
EventBus.on('theme:changed', ({ isDark }) => {
  try {
    const el = document.getElementById('plotlyChart');
    if (!el) return;

    if (currentPdfHistogram && currentPdfHistogramData) {
      // Re-render the whole histogram with correct theme colours
      createPdfHistogram(currentPdfHistogramData);
      return;
    }

    if (!currentChartData) return;
    Plotly.relayout(el, ChartService.relayoutForTheme(isDark));
  } catch (e) {
    console.warn('theme:changed handler failed', e);
  }
});

// Toolbar actions (decoupled via EventBus)
EventBus.on('toolbar:copy-chart', () => {
  try { copyChartToClipboard(); } catch (e) { console.warn('toolbar:copy-chart handler failed', e); }
});
EventBus.on('toolbar:download-csv', () => {
  try { downloadChartData(); } catch (e) { console.warn('toolbar:download-csv handler failed', e); }
});
EventBus.on('toolbar:download-excel', () => {
  try { downloadChartDataAsExcel(); } catch (e) { console.warn('toolbar:download-excel handler failed', e); }
});

// Background search-aware expansion (runs when `filterTree` emits `search:changed`)
EventBus.on('search:changed', ({ term }) => {
  if (!term || !term.trim()) return;
  if (window._searchExpansionState.inProgress) return;
  if (window._searchExpansionState.lastTerm === term) return;

  window._searchExpansionState.lastTerm = term;
  window._searchExpansionState.inProgress = true;

  showSearchTicker();

  (async () => {
    try {
      const isPathSearchLocal = isPathSearchTerm(term);
      const patternForSearch = isPathSearchLocal ? normalizePathSearchTerm(term) : term;
      const regexLocal = wildcardToRegex(patternForSearch);
      const enabled = getEnabledFiles();
      let expansions = 0;

      for (const fk of enabled) {
        const file = loadedFiles[fk];
        if (!file) continue;
        const matches = await asyncFindMatchingPaths(file, regexLocal, 50);
        for (const p of matches) {
          const exists = Array.from(document.querySelectorAll('.tree-item')).some(el => el.getAttribute('data-path') === p && (el.getAttribute('data-file') === fk || !el.getAttribute('data-file')));
          if (!exists) {
            const parentPath = p.substring(0, p.lastIndexOf('/')) || '/';
            await expandAndLoadPath(fk, parentPath);
            expansions++;
            await new Promise(r => setTimeout(r, 10));
          }
        }
      }

      if (expansions > 0) setTimeout(() => filterTree(term), 80);
    } catch (e) {
      console.error('search-aware expansion error', e);
    } finally {
      hideSearchTicker();
      window._searchExpansionState.inProgress = false;
    }
  })();
});

// debug: trace '+ Add Files' button clicks (helps diagnose file-input issues)
try {
  const _addBtn = document.querySelector('.add-file-btn');
  if (_addBtn) _addBtn.addEventListener('click', () => console.debug('[UI] add-file-btn clicked'));
} catch (e) { /* ignore */ }

// Pre-warm tree worker shortly after startup so first intersect is fast.
// Non-blocking: worker/h5wasm init happens in background and reduces
// likelihood of the quick-fallback being triggered on first use.
try {
  setTimeout(() => {
    try { ensureTreeWorker(); computeIntersectedPathsViaWorker([]).catch(() => {}); } catch (e) { /* ignore */ }
  }, 1200);
} catch (e) { /* ignore */ }

// File load ticker helpers (show per-file progress and tree-refresh state)
// search ticker state – reused file-load ticker element but separate control flag
let _searchTickerActive = false;
function showSearchTicker() {
  _searchTickerActive = true;
  try { showFileLoadTicker(0, 0, 'Searching…'); } catch (e) { /* ignore */ }
}
function hideSearchTicker() {
  if (!_searchTickerActive) return;
  _searchTickerActive = false;
  try { hideFileLoadTicker(); } catch (e) { /* ignore */ }
}

function showFileLoadTicker(current = 0, total = 0, text = '') {
  try {
    const el = document.getElementById('fileLoadTicker');
    if (!el) return;
    el.hidden = false;
    const spinner = el.querySelector('.spinner');
    const txt = el.querySelector('.ticker-text');
    const cancelBtn = el.querySelector('.ticker-cancel');
    if (spinner) spinner.style.display = 'inline-block';
    if (typeof current === 'number' && typeof total === 'number' && total > 0) {
      txt.textContent = `${current}/${total}${text ? ' — ' + text : ' Loading files…'}`;
      const bar = el.querySelector('.ticker-progress-bar');
      if (bar && total > 0 && current >= 0) bar.style.width = Math.min(100, Math.floor((current/total)*100)) + '%';
    } else {
      txt.textContent = text || 'Loading...';
    }
    // show cancel button only when a tree refresh is active
    if (cancelBtn) cancelBtn.style.display = (window._treeRefreshId ? 'inline-block' : 'none');
  } catch (e) { console.warn('showFileLoadTicker error', e); }
}

function updateFileLoadTicker(current = 0, total = 0, text = '') {
  try {
    const el = document.getElementById('fileLoadTicker');
    if (!el) return;
    el.hidden = false;
    const txt = el.querySelector('.ticker-text');
    txt.textContent = (typeof current === 'number' && total ? `${current}/${total}` : '') + (text ? (current && total ? ' — ' + text : ' ' + text) : '');
    const bar = el.querySelector('.ticker-progress-bar');
    if (bar && total > 0) bar.style.width = Math.min(100, Math.floor((current / total) * 100)) + '%';
    const cancelBtn = el.querySelector('.ticker-cancel');
    if (cancelBtn) cancelBtn.style.display = (window._treeRefreshId ? 'inline-block' : 'none');
  } catch (e) { console.warn('updateFileLoadTicker error', e); }
}

function hideFileLoadTicker() {
  try {
    const el = document.getElementById('fileLoadTicker');
    if (!el) return;
    el.hidden = true;
    const bar = el.querySelector('.ticker-progress-bar');
    if (bar) bar.style.width = '0%';
    const cancelBtn = el.querySelector('.ticker-cancel');
    if (cancelBtn) cancelBtn.style.display = 'none';
  } catch (e) { console.warn(e); }
}

function cancelTreeRefresh() {
  try {
    if (!window._treeRefreshId) return;
    window._treeRefreshCancelled = true;
    window._treeRefreshId = 0;
    // notify worker if active
    try { if (treeWorker) treeWorker.postMessage({ cmd: 'cancel' }); } catch (e) { /* ignore */ }
    const el = document.getElementById('fileLoadTicker');
    if (el) {
      el.querySelector('.ticker-text').textContent = 'Cancelling…';
      const spinner = el.querySelector('.spinner');
      if (spinner) spinner.style.display = 'none';
      const btn = el.querySelector('.ticker-cancel');
      if (btn) btn.style.display = 'none';
    }
    console.log('Tree refresh cancellation requested');
  } catch (e) { console.warn('cancelTreeRefresh failed', e); }
}



/**
 * File input change handler.
 * Processes selected HDF5 files, loads them via h5wasm,
 * and adds them to the file tabs for viewing.
 * 
 * @listens change
 */
document.getElementById('fileInput').addEventListener('change', async (e) => {
  const files = Array.from(e.target.files || []);
  console.debug('[fileInput.change] files selected=', files.length, files.map(f => f && f.name));
  if (files.length === 0) return;

  // show progress ticker (file count known)
  showFileLoadTicker(0, files.length, 'Starting…');

  try {
    console.debug('[fileInput.change] waiting for h5wasm...');
    await waitForH5Wasm();
    console.debug('[fileInput.change] h5wasm ready');

    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      // update ticker with current file being processed
      updateFileLoadTicker(i, files.length, file.name);
      try {
        const buffer = await file.arrayBuffer();
        // keep a copy of the raw buffer so we can send it to the worker later
        loadedFileBuffers[file.name] = buffer;
        console.debug('[fileInput.change] stored buffer for', file.name, 'bytes=', buffer && buffer.byteLength);

        const { FS, File } = window.h5wasm;
        if (!FS || !File) throw new Error('h5wasm not ready');
        
        const filename = `file_${Date.now()}_${Math.random().toString(36).substr(2, 9)}.h5`;
        const data = new Uint8Array(buffer);
        
        FS.writeFile('/' + filename, data);
        const hf = new File('/' + filename, 'r');
        
        // If replacing an existing file, close the old handle first
        if (loadedFiles[file.name]) {
          try { loadedFiles[file.name].close(); } catch (_) {}
        }

        loadedFiles[file.name] = hf;
        fileStates[file.name] = true;
        if (!fileOrder.includes(file.name)) {
          fileOrder.push(file.name);
        }
        // log per-file load (toasts removed)
        console.debug('[fileInput.change] Loaded', file.name);
      } catch (err) {
        console.error('[fileInput.change] Error loading', file.name, err);
        alert(`Failed to load ${file.name}`);
      }
    }
    
    // pre-warm tree worker (wait up to 5s) so first intersection is fast
    try {
      const _prewarmOk = await ensureTreeWorkerReady(5000);
      console.debug('[fileInput.change] worker pre-warm result =', _prewarmOk);
    } catch (e) {
      console.debug('[fileInput.change] worker pre-warm threw', e && e.message ? e.message : e);
    }

    // Update tabs (returns a promise that resolves when tree rebuild completes)
    updateFileLoadTicker(files.length, files.length, 'Refreshing tree...');
    console.debug('[fileInput.change] calling updateTabs(forceRefresh=true)');
    await updateTabs(true);
    console.debug('[fileInput.change] updateTabs() completed');
    hideFileLoadTicker();
  } catch (err) {
    hideFileLoadTicker();
    console.error('[fileInput.change] handler error', err);
    alert(`Error: ${err.message}`);
  }
  
  e.target.value = '';
});

/**
 * Search input handler with 200ms debouncing.
 * Filters the tree view to show only matching items.
 * Shows/hides the clear button based on input state.
 * 
 * @listens input
 */
document.getElementById('treeSearch').addEventListener('input', (e) => {
  const searchTerm = e.target.value;
  const clearBtn = document.getElementById('clearSearch');
  
  if (searchTerm) {
    clearBtn.classList.add('visible');
  } else {
    clearBtn.classList.remove('visible');
  }
  
  // Debounce the search
  if (searchTimeout) {
    clearTimeout(searchTimeout);
  }
  
  searchTimeout = setTimeout(() => {
    filterTree(searchTerm);
  }, 200);
});

/**
 * Clear search button handler.
 * Resets search input, removes filter, and refocuses the input.
 * 
 * @listens click
 */
document.getElementById('clearSearch').addEventListener('click', () => {
  const searchInput = document.getElementById('treeSearch');
  searchInput.value = '';
  document.getElementById('clearSearch').classList.remove('visible');
  filterTree('');
  searchInput.focus();
});

/**
 * Keyboard shortcut: Escape key clears the search input.
 * Provides quick way to reset the tree filter.
 * 
 * @listens keydown
 */
document.getElementById('treeSearch').addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    document.getElementById('clearSearch').click();
  }
});

/**
/**
 * Decorator: Re-apply search filter after tree structure refresh.
 * Ensures that if the user has an active search term, it persists
 * when the tree is rebuilt (e.g., after file reordering).
 */
const originalRefreshTreeStructure = refreshTreeStructure;
refreshTreeStructure = async function() {
  await originalRefreshTreeStructure();
  const searchTerm = document.getElementById('treeSearch').value;
  if (searchTerm) {
    setTimeout(() => filterTree(searchTerm), 50);
  }
};

/**
 * Responsive chart resizing using ResizeObserver.
 * Automatically resizes the Plotly chart when its container changes size.
 * Debounced to 100ms to prevent excessive resize operations.
 */
const plotlyChart = document.getElementById('plotlyChart');
let resizeTimeout;
const resizeObserver = new ResizeObserver(entries => {
  if (resizeTimeout) {
    clearTimeout(resizeTimeout);
  }
  resizeTimeout = setTimeout(() => {
    for (const entry of entries) {
      if (entry.target === plotlyChart && plotlyChart.data) {
        Plotly.Plots.resize(plotlyChart);
      }
    }
  }, 100);
});

if (plotlyChart) {
  resizeObserver.observe(plotlyChart);
}
