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

/*
  A single delegated listener for the whole tree. buildTree used to attach seven
  closures per rendered node, so a large tree allocated thousands of listeners
  that all had to be torn down on every refresh. Row identity comes from the
  data-path attribute the nodes already carry.
*/
(function installTreeClickDelegation() {
  const tree = document.getElementById('tree');
  if (!tree) return;
  tree.addEventListener('click', (event) => {
    const toggle = event.target.closest('.tree-toggle');
    if (toggle && !toggle.classList.contains('no-toggle')) {
      const owner = toggle.closest('.tree-item');
      if (owner) {
        event.stopPropagation();
        toggleGroupExpansion(event, owner.getAttribute('data-path'), toggle);
        return;
      }
    }

    const item = event.target.closest('.tree-item');
    if (!item || !tree.contains(item)) return;

    if (item.classList.contains('group')) {
      toggleGroup(event, item);
      return;
    }

    const path = item.getAttribute('data-path');
    if (path) selectDataset(path, event);
  });
})();


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
      const el = findTreeItem(payload.path, { fileKey: payload.fileKey, extra: '.dataset', root: tree })
        || findTreeItem(payload.path, { fileKey: payload.fileKey, root: tree });
      if (el) el.classList.add('selected');

      // show attributes / chart for single selection
      try { showNodeAttributes(payload.path, false); } catch (e) { console.warn('selection:changed handler showNodeAttributes failed', e); }
      return;
    }

    if (payload.mode === 'group') {
      // clear dataset selection, collapse groups, then expand/select the group
      document.querySelectorAll('.tree-item.dataset.selected').forEach(el => el.classList.remove('selected'));
      document.querySelectorAll('.tree-item.group.expanded').forEach(el => el.classList.remove('expanded'));

      const groupEl = findTreeItem(payload.path, { fileKey: payload.fileKey, extra: '.group', root: tree });
      if (groupEl) groupEl.classList.add('expanded');

      try { showNodeAttributes(payload.path, true); } catch (e) { console.warn('selection:changed handler showNodeAttributes(group) failed', e); }
      return;
    }

    if (payload.mode === 'multi') {
      // clear previous selection then mark provided items
      document.querySelectorAll('.tree-item.dataset.selected').forEach(el => el.classList.remove('selected'));
      const items = Array.isArray(payload.items) ? payload.items : [];

      // If all items were deselected, treat as 'none'
      if (items.length === 0) {
        resetInfoPanel();
        hideChart();
        selectedDatasetPath = null;
        selectedIsRadionuclidesGroup = false;
        selectedFileKey = null;
        return;
      }

      for (const it of items) {
        const found = findTreeItem(it.path, { fileKey: it.fileKey, extra: '.dataset', root: tree });
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
    _suppressPresetSync = true;
    Plotly.relayout(el, ChartService.relayoutForTheme(isDark));
    setTimeout(() => { _suppressPresetSync = false; }, 0);
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
          const exists = hasTreeItemForPath(p, fk);
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

// Pre-warm tree worker shortly after startup so first intersect is fast.
// Non-blocking: worker/h5wasm init happens in background and reduces
// likelihood of the quick-fallback being triggered on first use.
try {
  setTimeout(() => {
    try { ensureTreeWorker(); computeIntersectedPathsViaWorker([]).catch(() => {}); } catch (e) { ignoreFailure('init@209', e); }
  }, 1200);
} catch (e) { ignoreFailure('init@211', e); }

// File load ticker helpers (show per-file progress and tree-refresh state)
// search ticker state – reused file-load ticker element but separate control flag
let _searchTickerActive = false;
function showSearchTicker() {
  _searchTickerActive = true;
  try { showFileLoadTicker(0, 0, 'Searching…'); } catch (e) { ignoreFailure('showSearchTicker', e); }
}
function hideSearchTicker() {
  if (!_searchTickerActive) return;
  _searchTickerActive = false;
  try { hideFileLoadTicker(); } catch (e) { ignoreFailure('hideSearchTicker', e); }
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

/**
 * Drive the ticker from a fraction rather than a file count.
 *
 * The count form reads "2/5 — name.h5", which is wrong for one long transfer
 * where the interesting number is how much of it has arrived. This sets the
 * text verbatim and the bar from 0..1; pass null for an indeterminate step
 * that has no measurable progress.
 *
 * @param {number|null} fraction - 0..1, or null to leave the bar alone
 * @param {string} text - Ticker text, shown as written
 * @returns {void}
 */
function setFileLoadProgress(fraction, text) {
  try {
    const el = document.getElementById('fileLoadTicker');
    if (!el) return;
    el.hidden = false;
    const spinner = el.querySelector('.spinner');
    if (spinner) spinner.style.display = 'inline-block';
    const txt = el.querySelector('.ticker-text');
    if (txt) txt.textContent = text || '';
    const bar = el.querySelector('.ticker-progress-bar');
    if (bar && typeof fraction === 'number' && isFinite(fraction)) {
      bar.style.width = Math.max(0, Math.min(100, Math.round(fraction * 100))) + '%';
    }
    const cancelBtn = el.querySelector('.ticker-cancel');
    if (cancelBtn) cancelBtn.style.display = (window._treeRefreshId ? 'inline-block' : 'none');
  } catch (e) { console.warn('setFileLoadProgress error', e); }
}

/**
 * Let the browser paint before a step that blocks the main thread.
 *
 * Writing a large buffer into the h5wasm filesystem holds the thread long
 * enough that a ticker shown immediately beforehand never appeared — the DOM
 * was updated but no frame was produced. Two yields: one for the frame, one
 * for the task queue behind it.
 *
 * @returns {Promise<void>}
 */
async function yieldForPaint() {
  await new Promise(requestAnimationFrame);
  await new Promise(resolve => setTimeout(resolve, 0));
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
    try { if (treeWorker) treeWorker.postMessage({ cmd: 'cancel' }); } catch (e) { ignoreFailure('cancelTreeRefresh', e); }
    const el = document.getElementById('fileLoadTicker');
    if (el) {
      el.querySelector('.ticker-text').textContent = 'Cancelling…';
      const spinner = el.querySelector('.spinner');
      if (spinner) spinner.style.display = 'none';
      const btn = el.querySelector('.ticker-cancel');
      if (btn) btn.style.display = 'none';
    }
    console.debug('[tree] Refresh cancellation requested');
  } catch (e) { console.warn('cancelTreeRefresh failed', e); }
}


/**
 * Validate that an ArrayBuffer looks like a real HDF5 file before opening it.
 * Supports userblock offsets (0, 512, 1024, 2048, ...).
 *
 * @param {ArrayBuffer} buffer
 * @returns {{ok:boolean, reason:string}}
 */
function validateHdf5Buffer(buffer) {
  if (!buffer || typeof buffer.byteLength !== 'number' || buffer.byteLength < 8) {
    return { ok: false, reason: 'File is too small to be a valid HDF5 file.' };
  }

  const bytes = new Uint8Array(buffer);
  const sig = [0x89, 0x48, 0x44, 0x46, 0x0d, 0x0a, 0x1a, 0x0a];
  const maxOffset = Math.min(bytes.length - sig.length, 1024 * 1024);

  let offset = 0;
  while (offset <= maxOffset) {
    let matches = true;
    for (let i = 0; i < sig.length; i++) {
      if (bytes[offset + i] !== sig[i]) {
        matches = false;
        break;
      }
    }
    if (matches) return { ok: true, reason: '' };
    offset = offset === 0 ? 512 : offset * 2;
  }

  let headText = '';
  try {
    headText = new TextDecoder('utf-8').decode(bytes.slice(0, Math.min(256, bytes.length)));
  } catch (_) {
    headText = '';
  }

  if (/version https:\/\/git-lfs\.github\.com\/spec\/v1/i.test(headText)) {
    return {
      ok: false,
      reason: 'This file looks like a Git LFS pointer, not actual HDF5 binary data.'
    };
  }
  if (/^\s*<!doctype html|^\s*<html/i.test(headText)) {
    return {
      ok: false,
      reason: 'Downloaded content is HTML, not an HDF5 file. The address of a page '
        + 'that shows a file is not the address of the file: look for a "raw" or '
        + '"download" link on that page and use the address it points at.'
    };
  }

  return {
    ok: false,
    reason: 'Missing HDF5 signature. The file is not a valid HDF5 payload.'
  };
}


/* ==========================================================================
   URL FILE LOADING
   ========================================================================== */

/**
 * A URL that serves the file, from one that only shows a page about it.
 *
 * Pasting what the address bar says while looking at a file on GitHub is the
 * obvious thing to do and cannot work twice over:
 * github.com/<owner>/<repo>/blob/<ref>/<path> is an HTML page about the file,
 * and github.com sends no `access-control-allow-origin`, so a browser would
 * refuse the read even if that address did return the bytes.
 * raw.githubusercontent.com serves the file itself and does send it.
 *
 * @param {URL} parsed
 * @returns {string|null} the address to fetch instead, or null if this one is fine
 */
function rawUrlFor(parsed) {
  const host = parsed.hostname.toLowerCase();
  if (host === 'github.com' || host === 'www.github.com') {
    // /<owner>/<repo>/blob/<ref>/<path...>, and the /raw/ spelling of the same,
    // which only redirects to raw.githubusercontent.com anyway.
    const m = /^\/([^/]+)\/([^/]+)\/(?:blob|raw)\/(.+)$/.exec(parsed.pathname);
    if (m) {
      return `https://raw.githubusercontent.com/${m[1]}/${m[2]}/${m[3]}${parsed.search}`;
    }
  }
  return null;
}

/** Open the URL input dialog */
function openUrlDialog() {
  const dialog = document.getElementById('urlDialog');
  const input = document.getElementById('urlInput');
  const error = document.getElementById('urlError');
  if (!dialog) return;
  error.style.display = 'none';
  error.textContent = '';
  input.value = '';
  dialog.style.display = '';
  input.focus();
}

/** Close the URL input dialog */
function closeUrlDialog() {
  const dialog = document.getElementById('urlDialog');
  if (dialog) dialog.style.display = 'none';
}

/**
 * Fetch an HDF5 file from the URL entered in the dialog,
 * load it via h5wasm, and add it to the file tabs.
 */
async function loadFromUrl() {
  const input = document.getElementById('urlInput');
  const errorEl = document.getElementById('urlError');
  const loadBtn = document.getElementById('urlLoadBtn');
  const url = (input.value || '').trim();

  errorEl.style.display = 'none';
  errorEl.textContent = '';

  if (!url) {
    errorEl.textContent = 'Please enter a URL.';
    errorEl.style.display = '';
    return;
  }

  // Basic URL validation
  let parsed;
  try {
    parsed = new URL(url);
  } catch (_) {
    errorEl.textContent = 'Invalid URL format.';
    errorEl.style.display = '';
    return;
  }

  // An address that shows the file rather than serving it is corrected here,
  // and written back into the box so that the one that worked is the one the
  // reader is left looking at.
  const raw = rawUrlFor(parsed);
  const target = raw || url;
  if (raw) {
    parsed = new URL(raw);
    input.value = raw;
  }

  const fileName = hdf5FileNameFromUrl(parsed);

  loadBtn.disabled = true;
  loadBtn.textContent = 'Loading…';

  try {
    showFileLoadTicker(0, 1, fileName);

    await ingestHdf5FromUrl(target, 'loadFromUrl', (read, total) => {
      setFileLoadProgress(total ? read / total : null,
                          total
                            ? `${fileName} — ${kvotFormatBytes(read)} of ${kvotFormatBytes(total)}`
                            : `${fileName} — ${kvotFormatBytes(read)}`);
    });

    // Pre-warm tree worker
    try { await ensureTreeWorkerReady(5000); } catch (_) { ignoreFailure('loadFromUrl', _); }

    setFileLoadProgress(1, 'Refreshing tree…');
    await updateTabs(true);
    hideFileLoadTicker();
    closeUrlDialog();
    console.debug('[loadFromUrl] Loaded', fileName, 'from', target);
  } catch (err) {
    hideFileLoadTicker();
    console.error('[loadFromUrl] Error loading from URL', target, err);
    errorEl.textContent = `Failed to load: ${err.message}`;
    errorEl.style.display = '';
  } finally {
    loadBtn.disabled = false;
    loadBtn.textContent = 'Load';
  }
}

// ── Sample Data dialog ──────────────────────────────────────────────

/** Open the sample-data picker dialog, fetching the manifest. */
async function openSampleDataDialog() {
  const dialog  = document.getElementById('sampleDataDialog');
  const listEl  = document.getElementById('sampleDataList');
  const errorEl = document.getElementById('sampleDataError');
  if (!dialog) return;

  errorEl.style.display = 'none';
  errorEl.textContent = '';
  listEl.innerHTML = '';
  dialog.style.display = '';

  try {
    const resp = await fetch('./resources/data/files.json');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const files = await resp.json();

    if (!Array.isArray(files) || files.length === 0) {
      listEl.innerHTML = '<div class="sample-data-empty">No sample files available.</div>';
      return;
    }

    files.forEach(name => {
      const alreadyLoaded = !!loadedFiles[name];
      const item = document.createElement('div');
      item.className = 'sample-data-item';

      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.id = 'sd_' + name;
      cb.value = name;
      if (alreadyLoaded) cb.disabled = true;

      const lbl = document.createElement('label');
      lbl.htmlFor = cb.id;
      lbl.textContent = name + (alreadyLoaded ? ' (loaded)' : '');

      item.appendChild(cb);
      item.appendChild(lbl);
      listEl.appendChild(item);
    });
  } catch (err) {
    errorEl.textContent = 'Could not load sample file list: ' + err.message;
    errorEl.style.display = '';
  }
}

/** Close the sample-data dialog. */
function closeSampleDataDialog() {
  const dialog = document.getElementById('sampleDataDialog');
  if (dialog) dialog.style.display = 'none';
}

/** Load the files the user checked in the sample-data dialog. */
async function loadSelectedSampleData() {
  const listEl  = document.getElementById('sampleDataList');
  const errorEl = document.getElementById('sampleDataError');
  const loadBtn = document.getElementById('sampleDataLoadBtn');

  const checked = Array.from(listEl.querySelectorAll('input[type="checkbox"]:checked'))
                       .map(cb => cb.value);

  if (checked.length === 0) {
    errorEl.textContent = 'Select at least one file.';
    errorEl.style.display = '';
    return;
  }

  errorEl.style.display = 'none';
  loadBtn.disabled = true;
  loadBtn.textContent = 'Loading…';

  try {
    showFileLoadTicker(0, checked.length, 'Starting…');
    await waitForH5Wasm();

    for (let i = 0; i < checked.length; i++) {
      const fileName = checked[i];
      updateFileLoadTicker(i, checked.length, fileName);

      const resp = await fetch('./resources/data/' + encodeURIComponent(fileName));
      if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${fileName}`);
      const buffer = await resp.arrayBuffer();

      await ingestHdf5Buffer(fileName, buffer, 'loadSelectedSampleData');
    }

    try { await ensureTreeWorkerReady(5000); } catch (_) { ignoreFailure('loadSelectedSampleData', _); }

    updateFileLoadTicker(checked.length, checked.length, 'Refreshing tree…');
    await updateTabs(true);
    hideFileLoadTicker();
    closeSampleDataDialog();
  } catch (err) {
    hideFileLoadTicker();
    errorEl.textContent = 'Failed to load: ' + err.message;
    errorEl.style.display = '';
  } finally {
    loadBtn.disabled = false;
    loadBtn.textContent = 'Load Selected';
  }
}

// Allow Enter key to submit the URL dialog
document.addEventListener('DOMContentLoaded', () => {
  const urlInput = document.getElementById('urlInput');
  if (urlInput) {
    urlInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); loadFromUrl(); }
      if (e.key === 'Escape') { e.preventDefault(); closeUrlDialog(); }
    });
  }
  // Close dialog on overlay click
  const urlDialog = document.getElementById('urlDialog');
  if (urlDialog) {
    urlDialog.addEventListener('click', (e) => {
      if (e.target === urlDialog) closeUrlDialog();
    });
  }

  // Close sample-data dialog on Escape or overlay click
  const sdDialog = document.getElementById('sampleDataDialog');
  if (sdDialog) {
    sdDialog.addEventListener('click', (e) => {
      if (e.target === sdDialog) closeSampleDataDialog();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && sdDialog.style.display !== 'none') {
        e.preventDefault();
        closeSampleDataDialog();
      }
    });
  }

  // Populate chart preset dropdown from localStorage / defaults
  populatePresetDropdown();

  /* Close preset manager on overlay click or Escape. The other two dialogs
     have both; this one had only the click, so a keyboard user could open it
     and not get out the same way they got out of the others. */
  const presetOverlay = document.getElementById('presetManagerOverlay');
  if (presetOverlay) {
    presetOverlay.addEventListener('click', (e) => {
      if (e.target === presetOverlay) closePresetManager();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && presetOverlay.style.display !== 'none') {
        e.preventDefault();
        closePresetManager();
      }
    });
  }
});


/**
 * File input change handler.
 * Processes selected HDF5 files, loads them via h5wasm,
 * and adds them to the file tabs for viewing.
 * 
 * @listens change
 */
document.getElementById('fileInput').addEventListener('change', async (e) => {
  const files = Array.from(e.target.files || []);
  if (files.length === 0) return;

  showFileLoadTicker(0, files.length, 'Starting…');

  try {
    await waitForH5Wasm();

    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      updateFileLoadTicker(i, files.length, file.name);
      try {
        /*
          Checked before the read, not after. An HDF5 result set is read into
          memory whole and then copied into the h5wasm filesystem, so an
          oversized file costs twice its own size and gave no signal at all
          beyond a tab that stopped responding.
        */
        const size = kvotFileTooLarge(file, KVOT_FILE_SIZE_LIMITS.dataset);
        if (size.tooLarge) throw new Error(size.reason);

        const buffer = await file.arrayBuffer();
        await ingestHdf5Buffer(file.name, buffer, 'fileInput:load');
      } catch (err) {
        /*
          Report and carry on to the next file. This used to raise a modal,
          which halted a multi-file drop until the user dismissed it — once per
          bad file — and then continued regardless of what they clicked.
        */
        reportFailure('fileInput:load', err, { userMessage: `Could not load ${file.name}.` });
      }
    }

    // Pre-warm tree worker
    try { await ensureTreeWorkerReady(5000); } catch (_) { ignoreFailure('init@682', _); }

    updateFileLoadTicker(files.length, files.length, 'Refreshing tree...');
    await updateTabs(true);
    hideFileLoadTicker();
  } catch (err) {
    hideFileLoadTicker();
    reportFailure('fileInput:handler', err, { userMessage: 'Adding files failed.' });
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
