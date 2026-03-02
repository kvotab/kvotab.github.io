/* ==========================================================================
   6. TREE VIEW
   ========================================================================== */

/**
 * Toggle the expand/collapse state of a group node in the tree.
 * Called when clicking the triangle toggle icon.
 * Does NOT select the group or trigger chart updates.
 * 
 * @param {Event} event - Click event on the toggle icon
 * @param {string} path - HDF5 path of the group
 * @returns {void}
 */
function toggleGroupExpansion(event, path) {
  event.stopPropagation();
  
  const toggle = event.currentTarget;
  const groupItem = toggle.closest('.tree-item.group');
  const childrenDiv = groupItem.nextElementSibling;
  
  if (childrenDiv && childrenDiv.classList.contains('tree-group-children')) {
    const isExpanded = childrenDiv.classList.contains('expanded');
    
    if (isExpanded) {
      childrenDiv.classList.remove('expanded');
      toggle.classList.add('collapsed');
      groupItem.classList.remove('expanded');
    } else {
      // If children were rendered as lazy placeholders, load them on first expand
      if (childrenDiv && childrenDiv.getAttribute && childrenDiv.getAttribute('data-lazy') === 'true') {
        // If intersect/union mode is active and this path has no allowed descendants,
        // mark it as loaded-empty and avoid the load to save work.
        const pathFilter = window._currentIntersectedPaths || null;
        if (pathFilter && !Array.from(pathFilter).some(p => p === path || p.startsWith(path + '/'))) {
          childrenDiv.innerHTML = '<div style="color:#999;padding:8px;font-size:12px;">(empty)</div>';
          childrenDiv.setAttribute('data-loaded', 'true');
        } else {
          // fire-and-forget loader; it will set data-loaded when complete
          loadGroupChildren(groupItem, path).catch(e => console.error('Lazy load failed', e));
        }
      }
      childrenDiv.classList.add('expanded');
      toggle.classList.remove('collapsed');
    }
  }
}

/**
 * Lazy-load children for a group node the first time it is expanded.
 * Inserts the group's subtree DOM nodes into the adjacent `.tree-group-children`. (expects a DocumentFragment from `buildTree`)
 */
async function loadGroupChildren(groupItem, path) {
  try {
    const childrenDiv = groupItem.nextElementSibling;
    if (!childrenDiv || childrenDiv.getAttribute('data-loaded') === 'true' || childrenDiv.getAttribute('data-loading') === 'true') return;
    childrenDiv.setAttribute('data-loading', 'true');
    childrenDiv.innerHTML = '<div class="loading" style="padding:8px;font-size:12px;">Loading…</div>';
    const rawFileAttr = groupItem.getAttribute('data-file');
    // In intersect/union mode, preserve null fileKey so child nodes remain file-agnostic
    // (they will be expanded to all enabled files when selected).
    const mergedMode = isIntersectMode() || isUnionMode();
    const fileKey = rawFileAttr || (mergedMode ? null : getTreeFile());
    const readFileKey = rawFileAttr || getTreeFile();
    let file = loadedFiles[readFileKey];

    // In union mode, the primary file may not have this group.
    // Try to find any enabled file that does.
    let node = null;
    if (file) {
      try { node = FileService.get(file, path); } catch (e) { /* skip */ }
    }
    if (!node && isUnionMode()) {
      for (const fk of getEnabledFiles()) {
        if (fk === readFileKey) continue;
        const altFile = loadedFiles[fk];
        if (!altFile) continue;
        try {
          node = FileService.get(altFile, path);
          if (node) { file = altFile; break; }
        } catch (e) { /* skip */ }
      }
    }

    if (!file) {
      childrenDiv.innerHTML = '<div style="color:#999;padding:8px;font-size:12px;">(unavailable)</div>';
      childrenDiv.setAttribute('data-loaded', 'true');
      childrenDiv.removeAttribute('data-loading');
      return;
    }
    if (!node) {
      childrenDiv.innerHTML = '<div style="color:#999;padding:8px;font-size:12px;">(unreadable)</div>';
      childrenDiv.setAttribute('data-loaded', 'true');
      childrenDiv.removeAttribute('data-loading');
      return;
    }
    // Build the subtree for this group.
    // Pass the path filter (intersect or union path set) so children are
    // correctly filtered or expanded.
    const pathFilter = window._currentIntersectedPaths || null;
    const pathOwnership = window._unionPathOwnership || null;
    // render only one level when expanding lazily to keep UI responsive
    const subFrag = await buildTree(node, path, true, '', pathFilter, fileKey, null, false, 1, pathOwnership);
    childrenDiv.replaceChildren();
    if (subFrag && subFrag.childNodes.length > 0) {
      childrenDiv.appendChild(subFrag);
    } else {
      const empty = document.createElement('div');
      empty.style.color = '#999'; empty.style.padding = '8px'; empty.style.fontSize = '12px';
      empty.textContent = '(empty)';
      childrenDiv.appendChild(empty);
    }
    childrenDiv.setAttribute('data-loaded', 'true');
    childrenDiv.removeAttribute('data-loading');
  } catch (e) {
    console.error('loadGroupChildren error', e);
    const childrenDiv = groupItem.nextElementSibling;
    if (childrenDiv) childrenDiv.innerHTML = `<div style="color:red;padding:8px;font-size:12px;">(error: ${escapeHtml(e.message)})</div>`;
  }
}

/**
 * Handle dataset selection in single or multi-select mode.
 * 
 * Single-click: Selects one dataset, shows its info and chart.
 * Ctrl/Cmd+click: Adds/removes dataset from multi-selection,
 *                 shows combined info and comparison chart.
 * 
 * @param {string} path - HDF5 path to the dataset
 * @param {Event} [evt] - Click event (used to detect Ctrl/Cmd key)
 * @returns {void}
 */
function selectDataset(path, evt) {
  evt?.stopPropagation();

  const isCtrlKey = evt?.ctrlKey || evt?.metaKey;
  const datasetElement = evt?.target?.closest('.tree-item.dataset');
  const nodeFileKey = datasetElement?.getAttribute('data-file') || null;

  if (isCtrlKey) {
    // Update selection state for multi-select and emit centralized event
    multiSelectMode = true;
    selectedFileKey = null; // clear single-file scope

    const exists = selectedDatasets.find(d => d.path === path && d.fileKey === nodeFileKey);
    if (exists) {
      selectedDatasets = selectedDatasets.filter(d => !(d.path === path && d.fileKey === nodeFileKey));
    } else {
      selectedDatasets.push({ path, fileKey: nodeFileKey });
    }

    selectedIsRadionuclidesGroup = false;
    EventBus.emit('selection:changed', {
      mode: 'multi',
      items: selectedDatasets.slice()
    });
  } else {
    // Single select mode — set state and emit centralized event
    multiSelectMode = false;
    selectedFileKey = nodeFileKey;
    selectedDatasets = [{ path, fileKey: nodeFileKey }];
    selectedDatasetPath = path;
    selectedIsRadionuclidesGroup = false;

    EventBus.emit('selection:changed', {
      mode: 'single',
      path,
      fileKey: nodeFileKey,
      isGroup: false
    });
  }
}

/**
 * Handle group selection to show group info and radionuclides chart.
 * Clicking on a group (not its toggle icon) selects it for display.
 * If the group contains radionuclides data, triggers special charting.
 * 
 * @param {Event} event - Click event on the group element
 * @returns {void}
 */
function toggleGroup(event) {
  event.stopPropagation();
  const groupItem = event.currentTarget;

  if (event.target.classList.contains('tree-toggle')) {
    return;
  }

  const path = groupItem.getAttribute('data-path');
  if (path) {
    multiSelectMode = false;
    selectedDatasets = [];

    const nodeFileKey = groupItem.getAttribute('data-file') || null;
    selectedFileKey = nodeFileKey;

    selectedDatasetPath = path;
    selectedIsRadionuclidesGroup = true;

    EventBus.emit('selection:changed', {
      mode: 'group',
      path,
      fileKey: nodeFileKey,
      isGroup: true
    });
  }
}

/**
 * Toggle the Intersect checkbox and rebuild the tree.
 */
async function toggleTreeMode() {
  // Clear per-file selection when switching modes
  selectedFileKey = null;
  selectedDatasetPath = null;
  selectedIsRadionuclidesGroup = false;
  selectedDatasets = [];
  multiSelectMode = false;
  resetInfoPanel();
  hideChart();

  // mark a refresh token early so the header ticker cancel button can appear
  window._treeRefreshId = (window._treeRefreshId || 0) + 1;
  window._treeRefreshCancelled = false;

  const treeMode = getTreeMode();
  const isMerged = treeMode === 'intersect' || treeMode === 'union';
  const modeLabel = treeMode === 'intersect' ? 'Intersection' : (treeMode === 'union' ? 'Union' : 'Separated');

  // Show header ticker for long-running recalculations
  if (isMerged) {
    try { showFileLoadTicker(0, 0, `Calculating ${modeLabel.toLowerCase()}...`); } catch (e) {}
  }

  // Immediately show the root + inline spinner so the UI responds instantly
  try {
    const tree = document.getElementById('tree');
    if (tree) {
      if (isMerged) {
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
      // force layout so browsers (Safari) paint the inserted spinner immediately
      void tree.offsetHeight;
      tree.classList.remove('loading');
      document.querySelector('.search-container')?.classList.remove('visible');
    }
  } catch (e) { /* ignore UI update errors */ }

  // Let the browser paint the inline spinner before starting the expensive work.
  // Use setTimeout to yield to the event loop (more reliable on Safari).
  await new Promise(r => setTimeout(r, 0));

  // Start refresh asynchronously so the UI paint is never blocked in Safari.
  const tmBtns = document.querySelectorAll('#treeModeContainer button');
  tmBtns.forEach(b => b.disabled = true);
  setTimeout(() => {
    refreshTreeStructure().finally(() => { tmBtns.forEach(b => b.disabled = false); });
  }, 50);

  // return immediately so the inline spinner remains visible while work runs
  return;
}

/**
 * (sync) Recursively collect all paths (groups and datasets) from an HDF5 file.
 * NOTE: kept for backward-compatibility and lightweight files; heavy scans
 * should use `collectAllPathsAsync` to avoid blocking the UI.
 *
 * @param {Object} group - h5wasm Group object
 * @param {string} prefix - Current path prefix
 * @returns {Set<string>} Set of all paths in the group
 */
function collectAllPaths(group, prefix = '') {
  const paths = new Set();
  try {
    let keys = [];
    if (typeof group.keys === 'function') {
      keys = Array.from(group.keys());
    }
    for (const key of keys) {
      const path = prefix ? `${prefix}/${key}` : `/${key}`;
      paths.add(path);
      try {
        const obj = group.get(key);
        if (obj && String(obj.type).toLowerCase() === 'group') {
          for (const subPath of collectAllPaths(obj, path)) {
            paths.add(subPath);
          }
        }
      } catch (e) { /* skip */ }
    }
  } catch (e) { /* skip */ }
  return paths;
}

/**
 * Asynchronously collect all paths (groups and datasets) from an HDF5 file
 * without blocking the main thread. Yields to the event loop periodically
 * and honors the global cancellation flag `window._treeRefreshCancelled`.
 *
 * @param {Object} group - h5wasm Group object
 * @param {string} prefix - Current path prefix
 * @param {Object} [opts] - Options: { yieldEvery: number }
 * @returns {Promise<Set<string>>}
 */
async function collectAllPathsAsync(group, prefix = '', opts = {}) {
  const paths = new Set();
  const yieldEvery = (opts && opts.yieldEvery) || 200;
  let counter = 0;

  async function _traverse(g, p) {
    if (!g || typeof g.keys !== 'function') return;
    let keys = [];
    try { keys = Array.from(g.keys()).sort(); } catch (e) { return; }

    for (const k of keys) {
      if (window._treeRefreshCancelled) throw new Error('cancelled');

      const path = p ? `${p}/${k}` : `/${k}`;
      paths.add(path);

      let obj = null;
      try { obj = g.get(k); } catch (e) { /* unreadable — skip */ }

      if (obj && String(obj.type).toLowerCase() === 'group') {
        await _traverse(obj, path);
      }

      if (++counter % yieldEvery === 0) {
        // yield so the browser can process user input (clicks, cancel)
        await new Promise(r => setTimeout(r, 0));
        if (window._treeRefreshCancelled) throw new Error('cancelled');
      }
    }
  }

  await _traverse(group, prefix);
  return paths;
}

/**
 * Get the set of paths that exist in ALL enabled files (full-path intersection).
 * Synchronous version for quick checks; for large files use the
 * `getIntersectedPathsAsync` worker-friendly implementation below.
 *
 * @returns {Set<string>|null} Intersected paths, or null if intersect is off
 */
function getIntersectedPaths() {
  if (getTreeMode() !== 'intersect') return null;
  
  const enabledFiles = getEnabledFiles();
  if (enabledFiles.length < 2) return null;
  
  let intersection = null;
  for (const fileKey of enabledFiles) {
    const file = loadedFiles[fileKey];
    if (!file) continue;
    const filePaths = collectAllPaths(file);
    if (intersection === null) {
      intersection = filePaths;
    } else {
      // Keep only paths present in both sets
      for (const p of intersection) {
        if (!filePaths.has(p)) intersection.delete(p);
      }
    }
  }
  return intersection || new Set();
}

/**
 * Async, cooperative version of getIntersectedPaths(). Use this when the
 * enabled files are large — it yields to the event loop and honors
 * cancellation so the UI stays responsive and the cancel button works.
 *
 * @returns {Promise<Set<string>|null>}
 */
async function getIntersectedPathsAsync() {
  if (getTreeMode() !== 'intersect') return null;

  const enabledFiles = getEnabledFiles();
  if (enabledFiles.length < 2) return null;

  // Prefer using a worker when available and when we have stored file buffers
  try {
    const buffersAvailable = enabledFiles.every(k => loadedFileBuffers[k] instanceof ArrayBuffer);
    if (buffersAvailable) {
        // If worker exists but h5wasm inside it hasn't finished, wait a
        // *short* time for readiness before launching a compute. This
        // prevents immediate fallback when the worker is still warming up.
        const WORKER_STARTUP_WAIT_MS = 1500;
        let tryWorker = true;
        try {
          ensureTreeWorker();
          if (!treeWorkerH5Ready) {
            tryWorker = await ensureTreeWorkerReady(WORKER_STARTUP_WAIT_MS);
            console.debug('[getIntersectedPathsAsync] worker readiness after wait=', tryWorker);
          }
        } catch (e) {
          tryWorker = false;
        }

        if (!tryWorker) {
          console.debug('[getIntersectedPathsAsync] skipping worker path (worker not ready)');
        } else {
          // keep worker as the preferred path but *quickly* fallback to the
          // main-thread collector if the worker doesn't respond fast (eg.
          // slow h5wasm init inside worker). This prevents the UI spinner
          // from appearing to hang for long-running worker startups.
          const WORKER_QUICK_FALLBACK_MS = 5000;
          const workerP = computeIntersectedPathsViaWorker(enabledFiles);
          let paths;
          try {
            paths = await Promise.race([
              workerP,
              new Promise((_, rej) => setTimeout(() => rej(new Error('worker quick-fallback')), WORKER_QUICK_FALLBACK_MS))
            ]);
            console.debug('[getIntersectedPathsAsync] worker returned', (paths && paths.length) || 0);
            return new Set(paths || []);
          } catch (workerErr) {
            // quick fallback — try to cancel the in-flight worker request so
            // it doesn't remain pending and interfere with later runs.
            console.warn('[getIntersectedPathsAsync] worker slow/failed, falling back to main-thread:', workerErr);
            try {
              const wid = workerP && workerP._workerId;
              if (wid && _treeWorkerPending[wid]) {
                try { clearTimeout(_treeWorkerPending[wid]._timeout); } catch (e) {}
                try { ensureTreeWorker().postMessage({ cmd: 'cancel', id: wid }); } catch (e) {}
                delete _treeWorkerPending[wid];
                console.debug('[getIntersectedPathsAsync] cancelled in-flight worker id=', wid);
              }
            } catch (e) { /* ignore */ }

            // schedule a background retry if/when the worker becomes fully
            // initialized (h5wasm ready). This mirrors the manual uncheck/
            // recheck behavior users observed and avoids requiring manual
            // intervention.
            try {
              ensureTreeWorkerReady(10000).then((ok) => {
                if (ok && isIntersectMode()) {
                  console.debug('[getIntersectedPathsAsync] worker became ready after fallback — scheduling tree refresh');
                  scheduleUpdateTabs(100);
                }
              }).catch(() => {});
            } catch (e) { /* ignore */ }
          }
        }
    }
  } catch (e) {
    // ignore and fall back
  }

  let intersection = null;
  for (const fileKey of enabledFiles) {
    if (window._treeRefreshCancelled) throw new Error('cancelled');
    const file = loadedFiles[fileKey];
    if (!file) {
      console.debug('[getIntersectedPathsAsync] skipping not-yet-loaded file=', fileKey);
      continue;
    }
    // use async collector so we don't block the UI
    console.debug('[getIntersectedPathsAsync] collecting paths for', fileKey);
    const filePaths = await collectAllPathsAsync(file, '');
    console.debug('[getIntersectedPathsAsync] collected', filePaths.size, 'paths for', fileKey);
    if (window._treeRefreshCancelled) throw new Error('cancelled');
    if (intersection === null) {
      intersection = filePaths;
    } else {
      for (const p of Array.from(intersection)) {
        if (!filePaths.has(p)) intersection.delete(p);
      }
    }
  }
  return intersection || new Set();
}

/**
 * Async, cooperative computation of the UNION of all paths across enabled
 * files. Also builds a path-ownership map so the tree can show which files
 * contain each node.
 *
 * @returns {Promise<{paths: Set<string>, ownership: Map<string, Set<string>>}|null>}
 *   null if union mode is not active.
 */
async function getUnionPathsAsync() {
  if (getTreeMode() !== 'union') return null;

  const enabledFiles = getEnabledFiles();
  if (enabledFiles.length < 2) return null;

  /** @type {Set<string>} */
  const unionPaths = new Set();
  /** @type {Map<string, Set<string>>} path → Set<fileKey> */
  const ownership = new Map();

  for (const fileKey of enabledFiles) {
    if (window._treeRefreshCancelled) throw new Error('cancelled');
    const file = loadedFiles[fileKey];
    if (!file) continue;

    console.debug('[getUnionPathsAsync] collecting paths for', fileKey);
    const filePaths = await collectAllPathsAsync(file, '');
    console.debug('[getUnionPathsAsync] collected', filePaths.size, 'paths for', fileKey);
    if (window._treeRefreshCancelled) throw new Error('cancelled');

    for (const p of filePaths) {
      unionPaths.add(p);
      let owners = ownership.get(p);
      if (!owners) { owners = new Set(); ownership.set(p, owners); }
      owners.add(fileKey);
    }
  }

  return { paths: unionPaths, ownership };
}


// Worker helpers ---------------------------------------------------------
function ensureTreeWorker() {
  if (treeWorker) return treeWorker;
  try {
    treeWorkerH5Ready = false;
    treeWorker = new Worker('resources/js/tree-worker.js');
    treeWorker.onmessage = (ev) => {
      const d = ev.data || {};
      // handle generic notifications (no id) such as worker lifecycle messages
      if (!d || !d.id) {
        if (d && d.cmd === 'h5ready') {
          treeWorkerH5Ready = true;
          console.debug('[ensureTreeWorker] worker reported h5ready');
          return;
        }
        if (d && d.cmd === 'started') {
          console.debug('[ensureTreeWorker] worker thread started');
          return;
        }
        // route other generic notifications (ignore by default)
        if (d && d.cmd === 'progress') {
          // ignore if not matching a pending request
        }
        return;
      }

      const p = _treeWorkerPending[d.id];
      if (!p) {
        console.debug('[ensureTreeWorker] message for unknown id=', d.id, d.cmd);
        return;
      }
      if (d.cmd === 'result') {
        console.debug('[ensureTreeWorker] worker result id=', d.id, 'paths=', (d.intersectedPaths || []).length);
        clearTimeout(p._timeout);
        p.resolve(d.intersectedPaths || []);
        delete _treeWorkerPending[d.id];
      } else if (d.cmd === 'progress') {
        // forward progress to ticker if needed
        try { updateFileLoadTicker(d.fileIndex, d.totalFiles, 'Calculating intersection...'); } catch (e) {}
        // extend/reset the worker timeout whenever we get progress so
        // long-running but active workers aren't prematurely rejected.
        try {
          clearTimeout(p._timeout);
          p._timeout = setTimeout(() => {
            clearTimeout(p._timeout);
            delete _treeWorkerPending[d.id];
            try { treeWorker.postMessage({ cmd: 'cancel', id: d.id }); } catch (e) { /* ignore */ }
            p.reject(new Error('worker timeout'));
          }, 30000);
        } catch (e) { /* ignore */ }
      } else if (d.cmd === 'error') {
        console.warn('[ensureTreeWorker] worker error id=', d.id, d.message || '');
        clearTimeout(p._timeout);
        p.reject(new Error(d.message || 'worker error'));
        delete _treeWorkerPending[d.id];
      } else if (d.cmd === 'cancelled') {
        console.debug('[ensureTreeWorker] worker cancelled id=', d.id);
        clearTimeout(p._timeout);
        p.reject(new Error('cancelled'));
        delete _treeWorkerPending[d.id];
      }
    };
    treeWorker.onerror = (err) => { console.warn('treeWorker error', err); };
    return treeWorker;
  } catch (e) {
    console.warn('could not create tree worker', e);
    treeWorker = null;
    return null;
  }
}

function computeIntersectedPathsViaWorker(enabledFiles) {
  // return a Promise that includes the worker request id (if created)
  let _workerId = null;
  const p = new Promise((resolve, reject) => {
    const worker = ensureTreeWorker();
    if (!worker) return reject(new Error('no worker'));
    _workerId = `${Date.now()}-${Math.random().toString(36).slice(2,9)}`;
    const id = _workerId;

    console.debug('[computeIntersectedPathsViaWorker] starting id=', id, 'files=', enabledFiles.length);
    const files = [];
    const transfers = [];
    for (const k of enabledFiles) {
      const buf = loadedFileBuffers[k];
      if (!(buf instanceof ArrayBuffer)) {
        // fallback — abort
        console.warn('[computeIntersectedPathsViaWorker] missing buffer for', k);
        return reject(new Error('missing file buffer for ' + k));
      }
      const copy = buf.slice(0);
      files.push({ name: k, buffer: copy });
      transfers.push(copy);
    }

    _treeWorkerPending[id] = {
      resolve,
      reject,
      _timeout: setTimeout(() => {
        // timeout expired — proactively cancel worker and reject
        try { worker.postMessage({ cmd: 'cancel', id }); } catch (e) { /* ignore */ }
        try { clearTimeout(_treeWorkerPending[id]._timeout); } catch (e) {}
        delete _treeWorkerPending[id];
        console.warn('[computeIntersectedPathsViaWorker] request timed out id=', id);
        reject(new Error('worker timeout'));
      }, 30000)
    };
    try {
      worker.postMessage({ cmd: 'computeIntersect', id, files }, transfers);
    } catch (e) {
      try { clearTimeout(_treeWorkerPending[id]._timeout); } catch (err) {}
      delete _treeWorkerPending[id];
      return reject(e);
    }
  });

  // attach the worker id so callers can cancel the in-flight request
  p._workerId = _workerId;
  return p;
}

/**
 * Ensure the tree worker is initialized and h5wasm in-worker is ready.
 * Returns a Promise<boolean> that resolves true when ready, false on timeout.
 */
function ensureTreeWorkerReady(timeoutMs = 5000) {
  try {
    // fast-path if worker already reported h5wasm readiness
    if (treeWorkerH5Ready) return Promise.resolve(true);

    ensureTreeWorker();
    // race a pre-warm compute (which forces h5wasm init in the worker)
    // against a timeout so we don't block file loading indefinitely.
    return Promise.race([
      computeIntersectedPathsViaWorker([]).then(() => true).catch((e) => {
        console.debug('[ensureTreeWorkerReady] pre-warm failed', e && e.message ? e.message : e);
        return false;
      }),
      new Promise(resolve => setTimeout(() => resolve(false), timeoutMs))
    ]);
  } catch (e) {
    console.warn('[ensureTreeWorkerReady] error', e && e.message ? e.message : e);
    return Promise.resolve(false);
  }
}

/**
 * Walk the HDF5 group and count items (datasets + groups) so we can show
 * determinate progress while building the tree. Honors the optional
 * intersectedPaths filter.
 *
 * @param {Object} group - h5wasm Group or File
 * @param {Set|null} intersectedPaths - optional filter set
 * @returns {Promise<number>} total items
 */
async function countTreeItems(group, intersectedPaths = null) {
  let cnt = 0;
  try {
    const keys = (typeof group.keys === 'function') ? Array.from(group.keys()).sort() : [];
    let _yieldCounter = 0;
    for (const key of keys) {
      // allow cooperative cancellation/yielding
      if (window._treeRefreshCancelled) throw new Error('cancelled');
      try {
        const obj = group.get(key);
        if (!obj) continue;
        const path = group === loadedFiles[Object.keys(loadedFiles)[0]] ? `/${key}` : `${group.name || ''}/${key}`;
        if (intersectedPaths && !intersectedPaths.has(path)) continue;
        // count this node
        cnt += 1;
        if (String(obj.type).toLowerCase() === 'group') {
          cnt += await countTreeItems(obj, intersectedPaths);
        }
      } catch (e) {
        // ignore individual errors while counting
      }
      if (++_yieldCounter % 200 === 0) await new Promise(r => setTimeout(r, 0));
    }
  } catch (e) {
    // best-effort counting; return what we've got
    if (String(e && e.message).toLowerCase().includes('cancel')) throw e;
  }
  return cnt;
}

/**
 * Refresh the tree view from the first enabled file's structure.
 * Rebuilds the entire tree DOM and applies any active search filter.
 * Shows loading state during refresh and handles errors gracefully.
 * 
 * @returns {Promise<void>}
 */
async function refreshTreeStructure() {
  const tree = document.getElementById('tree');
  const searchContainer = document.querySelector('.search-container');
  const enabledFiles = getEnabledFiles();

  // indicate busy for accessibility and automated tests
  try { tree && tree.setAttribute('aria-busy', 'true'); } catch(e) {}
  // start cancellable refresh token (used by buildTree to abort)
  window._treeRefreshId = (window._treeRefreshId || 0) + 1;
  const _myTreeRefreshId = window._treeRefreshId;
  window._treeRefreshCancelled = false;
  
  if (enabledFiles.length === 0) {
    tree.innerHTML = '<div class="loading">Drop HDF5 files or click "+ Add Files" to start...</div>';
    tree.classList.add('loading');
    resetInfoPanel();
    hideChart();
    searchContainer.classList.remove('visible');
    try { tree && tree.removeAttribute('aria-busy'); } catch(e) {}
    // reset token if nothing to do
    window._treeRefreshId = 0;
    window._treeRefreshCancelled = false;
    return;
  }
  
  try {
    let intersectedPaths = null;
    let unionResult = null;
    const treeMode = getTreeMode();

    // Clear previous union ownership data
    window._unionPathOwnership = null;

    if (treeMode === 'intersect') {
      try {
        intersectedPaths = await getIntersectedPathsAsync();
      } catch (err) {
        if (String(err && err.message).toLowerCase().includes('cancel')) {
          tree.innerHTML = '<div class="loading">(cancelled)</div>';
          hideFileLoadTicker();
          try { tree && tree.removeAttribute('aria-busy'); } catch (e) {}
          return;
        }
        throw err;
      }
      try { window._currentIntersectedPaths = intersectedPaths; console.debug('[refreshTreeStructure] intersectedPaths size=', intersectedPaths ? intersectedPaths.size : 'null', 'enabledFiles=', enabledFiles); } catch(e) {}

      // If intersect produced an empty set unexpectedly, allow one short retry
      if (intersectedPaths && intersectedPaths.size === 0 && enabledFiles.length > 1) {
        try {
          console.debug('[refreshTreeStructure] intersectedPaths empty — retrying once after 150ms');
          await new Promise(r => setTimeout(r, 150));
          const retry = await getIntersectedPathsAsync();
          intersectedPaths = retry || intersectedPaths;
          try { window._currentIntersectedPaths = intersectedPaths; } catch(e) {}
          console.debug('[refreshTreeStructure] retry intersectedPaths size=', intersectedPaths ? intersectedPaths.size : 'null');
        } catch (e) {
          console.debug('[refreshTreeStructure] retry failed or cancelled', e && e.message);
        }
      }
    } else if (treeMode === 'union') {
      try {
        unionResult = await getUnionPathsAsync();
      } catch (err) {
        if (String(err && err.message).toLowerCase().includes('cancel')) {
          tree.innerHTML = '<div class="loading">(cancelled)</div>';
          hideFileLoadTicker();
          try { tree && tree.removeAttribute('aria-busy'); } catch (e) {}
          return;
        }
        throw err;
      }
      if (unionResult) {
        // Store the union path set as the current path filter (used by lazy loading etc.)
        intersectedPaths = unionResult.paths;
        window._currentIntersectedPaths = intersectedPaths;
        window._unionPathOwnership = unionResult.ownership;
        console.debug('[refreshTreeStructure] unionPaths size=', intersectedPaths.size);
      }
    } else {
      // Separated mode
      window._currentIntersectedPaths = null;
    }

    // abort quickly if a cancellation was requested before we started
    if (window._treeRefreshCancelled || window._treeRefreshId !== _myTreeRefreshId) {
      hideFileLoadTicker();
      try { tree && tree.removeAttribute('aria-busy'); } catch (e) {}
      updateMultiSelectHint();
      updateHintToggleButton();
      return;
    }
    let treeHtml = ''; 

    // Shallow estimate to avoid a full pre-traversal (fast, best-effort).
    // Use top-level key counts as a cheap heuristic; fall back to
    // indeterminate mode when the estimate is small/uncertain.
    let totalItems = 0;
    try {
      for (const fk of enabledFiles) {
        const f = loadedFiles[fk];
        if (!f || typeof f.keys !== 'function') continue;
        totalItems += Array.from(f.keys()).length || 0;
      }
      // treat small estimates as unknown so UI stays indeterminate
      if (totalItems < 20) totalItems = 0;
    } catch (e) {
      totalItems = 0;
    }

    // use a single progress callback shared across builds (throttled)
    let progressSeen = 0;
    const progressCb = (() => {
      let lastPct = -1;
      let lastTs = 0;
      return (inc = 1, label = '') => {
        progressSeen += (typeof inc === 'number' ? inc : 1);
        const now = Date.now();
        if (totalItems > 0) {
          const pct = Math.floor((progressSeen / totalItems) * 100);
          if (pct !== lastPct) {
            lastPct = pct;
            updateFileLoadTicker(progressSeen, totalItems, label || 'Building tree...');
          }
        } else {
          // indeterminate — update at most every 500ms or on coarse increments
          if (now - lastTs > 500 || progressSeen % 100 === 0) {
            lastTs = now;
            updateFileLoadTicker(progressSeen, 0, label || 'Building tree...');
          }
        }
      };
    })();

    if (totalItems > 0) {
      showFileLoadTicker(0, totalItems, 'Building tree...');
    } else {
      // no reliable total — show indeterminate spinner
      showFileLoadTicker(0, 0, 'Building tree...');
    }

    // Clear tree and render incrementally so users see content immediately.
    tree.replaceChildren();
    if (intersectedPaths) {
      // Intersect or Union mode: single tree from first file, filtered/expanded
      const modeLabel = treeMode === 'union' ? 'Union' : 'Intersection';
      const pathOwnership = window._unionPathOwnership || null;
      const file = loadedFiles[enabledFiles[0]];
      const fileFrag = await buildTree(file, '', false, modeLabel, intersectedPaths, null, progressCb, true, Infinity, pathOwnership);
      if (fileFrag && fileFrag.childNodes.length > 0) {
        tree.appendChild(fileFrag);
      } else {
        const noItems = document.createElement('div');
        noItems.style.color = '#999';
        noItems.textContent = 'No items found';
        tree.appendChild(noItems);
      }
      if (window._treeRefreshCancelled || window._treeRefreshId !== _myTreeRefreshId) {
        const cancelled = document.createElement('div'); cancelled.className = 'loading'; cancelled.textContent = '(cancelled)';
        tree.appendChild(cancelled);
        hideFileLoadTicker();
        try { tree && tree.removeAttribute('aria-busy'); } catch(e) {}
        return;
      }
    } else {
      // Non-intersect: append each file as it finishes so UI is responsive
      for (const fileKey of enabledFiles) {
        const file = loadedFiles[fileKey];
        const fileFrag = await buildTree(file, '', false, fileKey, null, fileKey, progressCb, true);
        if (fileFrag && fileFrag.childNodes.length > 0) {
          tree.appendChild(fileFrag);
        } else {
          const empty = document.createElement('div');
          empty.style.color = '#999'; empty.style.padding = '8px'; empty.style.fontSize = '12px';
          empty.textContent = '(empty)';
          tree.appendChild(empty);
        }
        // yield to allow the browser to paint between files
        await new Promise(r => setTimeout(r, 0));
        // Stop early if the user cancelled the refresh
        if (window._treeRefreshCancelled || window._treeRefreshId !== _myTreeRefreshId) {
          const cancelled = document.createElement('div'); cancelled.className = 'loading'; cancelled.textContent = '(cancelled)';
          tree.appendChild(cancelled);
          hideFileLoadTicker();
          try { tree && tree.removeAttribute('aria-busy'); } catch(e) {}
          return;
        }
      }
    }

    // finalize progress and UI
    if (totalItems > 0) updateFileLoadTicker(totalItems, totalItems, 'Done');
    hideFileLoadTicker();

    if (!tree.innerHTML || tree.innerHTML.trim() === '') {
      tree.innerHTML = '<div style="color:#999;">No items found</div>';
    }
    tree.classList.remove('loading');
    searchContainer.classList.add('visible');
    try { tree && tree.removeAttribute('aria-busy'); } catch(e) {}

    // Post-refresh validation: ensure the right-panel selection/chart
    // reflect the newly-built tree / intersected set.
    try { refreshInfoAndChart(); } catch (e) { console.warn('refreshInfoAndChart after refreshTreeStructure failed', e); }
  } catch (err) {
    tree.innerHTML = `<div class="error">Error loading tree: ${escapeHtml(err.message)}</div>`;
    console.error(err);
    searchContainer.classList.remove('visible');
    try { tree && tree.removeAttribute('aria-busy'); } catch(e) {}
  } finally {
    // Ensure active refresh token is cleared so UI (cancel button) is hidden
    window._treeRefreshId = 0;
    window._treeRefreshCancelled = false;
  }
}

// Decorator: Show multi-select hint after tree refresh
const originalRefreshTreeStructure2 = refreshTreeStructure;
refreshTreeStructure = async function() {
  await originalRefreshTreeStructure2();
  const hint = document.getElementById('multiSelectHint');
  const tree = document.getElementById('tree');
  
  if (hint) {
    const hasEnabledFiles = getEnabledFiles().length > 0;
    const isNotLoading = !tree.classList.contains('loading');
    const hasTreeContent = tree.querySelector('.tree-item') !== null;
    
    if (hasEnabledFiles && isNotLoading && hasTreeContent) {
      hint.style.display = 'flex';
      // Notify user that tree refresh completed
    } else {
      hint.style.display = 'none';
    }
  }
};

/**
 * Recursively build HTML tree structure from an HDF5 group.
 * Creates collapsible group nodes and selectable dataset nodes.
 * Preserves selection state when rebuilding.
 * 
 * @param {Object} group - h5wasm Group object to traverse
 * @param {string} [prefix=''] - Path prefix for nested items
 * @param {boolean} [isNested=false] - Whether this is a nested call (not root)
 * @returns {Promise<DocumentFragment>} DocumentFragment containing tree nodes
 */
async function buildTree(group, prefix = '', isNested = false, fileName = '', intersectedPaths = null, fileKey = null, progressCb = null, lazyLoad = false, maxDepth = Infinity, pathOwnership = null) {
  // Return a DocumentFragment containing tree node elements (not HTML string).
  const frag = document.createDocumentFragment();
  // depth guard for incremental rendering (maxDepth=0 => render nothing)
  if (typeof maxDepth === 'number' && maxDepth <= 0) return frag;

  // Helper to attach common attributes and listeners to a .tree-item
  const makeTreeItem = (classes = '') => {
    const el = document.createElement('div');
    el.className = `tree-item ${classes}`.trim();
    return el;
  };

  // Add root group item only at top level
  let rootChildren = null;
  if (prefix === '') {
    const isRootSelected = selectedDatasetPath === '/' && selectedIsRadionuclidesGroup;
    const rootLabel = fileName ? fileName : 'root';
    let rootExpandable = true;
    if (intersectedPaths) {
      rootExpandable = Array.from(intersectedPaths).some(p => p !== '/' && p.startsWith('/'));
    }

    const rootItem = makeTreeItem('group root-node' + (isRootSelected ? ' expanded' : ''));
    rootItem.setAttribute('data-path', '/');
    if (fileKey) rootItem.setAttribute('data-file', fileKey);
    rootItem.addEventListener('click', toggleGroup);

    const toggleDiv = document.createElement('div');
    if (rootExpandable) {
      toggleDiv.className = 'tree-toggle' + (isRootSelected ? '' : ' collapsed');
      toggleDiv.textContent = '▶';
      toggleDiv.addEventListener('click', (e) => { e.stopPropagation(); toggleGroupExpansion(e, '/'); });
    } else {
      toggleDiv.className = 'tree-toggle no-toggle';
    }
    rootItem.appendChild(toggleDiv);

    const icon = document.createElement('div');
    icon.className = 'tree-icon folder';
    rootItem.appendChild(icon);

    const label = document.createElement('div');
    label.className = 'tree-label';
    label.appendChild(document.createTextNode(`/ (${rootLabel})`));
    rootItem.appendChild(label);

    frag.appendChild(rootItem);

    rootChildren = document.createElement('div');
    rootChildren.className = 'tree-group-children' + (isRootSelected ? ' expanded' : '');
    rootChildren.style.marginLeft = '20px';
    frag.appendChild(rootChildren);
  }

  // container for child nodes: rootChildren when at top level, otherwise the fragment
  const container = rootChildren || frag;

  try {
    let keys = [];
    try {
      if (typeof group.keys === 'function') keys = Array.from(group.keys());
      keys.sort();

      if (intersectedPaths && intersectedPaths.size > 0) {
        const allowed = new Set();
        const prefixWithSlash = prefix === '' ? '/' : (prefix + '/');
        for (const p of intersectedPaths) {
          if (!p.startsWith(prefixWithSlash)) continue;
          const rest = p.substring(prefixWithSlash.length);
          const child = rest.split('/')[0];
          if (child) allowed.add(child);
        }
        if (pathOwnership) {
          // Union mode: add keys from other files that this file doesn't have
          const keySet = new Set(keys);
          for (const k of allowed) {
            if (!keySet.has(k)) keys.push(k);
          }
          keys.sort();
        } else if (allowed.size > 0 && keys.length > 0) {
          // Intersect mode: filter to common keys
          keys = keys.filter(k => allowed.has(k));
        }
      }
    } catch (e) {
      console.error('Error getting keys:', e.message);
      return frag;
    }

    const topLevelLazy = !!lazyLoad && prefix === '';
    if (keys.length === 0) return frag;

    let _yieldCounter = 0;
    for (const key of keys) {
      if (window._treeRefreshCancelled) {
        console.log('buildTree: aborting early due to cancellation');
        break;
      }

      try {
        let obj = null;
        try { obj = group.get(key); } catch (e) { /* may not exist in this file */ }
        const path = prefix ? `${prefix}/${key}` : `/${key}`;

        // Union mode: if this file doesn't have the key, try an alternative file
        let altFileUsed = false;
        if (!obj && pathOwnership) {
          const owners = pathOwnership.get(path);
          if (owners) {
            for (const fk of owners) {
              const altFile = loadedFiles[fk];
              if (!altFile) continue;
              try {
                obj = FileService.get(altFile, path);
                if (obj) { altFileUsed = true; break; }
              } catch (e) { /* skip */ }
            }
          }
        }
        if (!obj) continue;
        const objType = String(obj.type).toLowerCase();

        if (intersectedPaths && !pathOwnership && !intersectedPaths.has(path)) continue;

        const linkInfo = getLinkInfo(group, path, obj);
        const linkBadgeEl = buildLinkBadge(linkInfo);

        // Union mode: build availability badge when not all files have this path
        let availBadgeEl = null;
        if (pathOwnership) {
          const owners = pathOwnership.get(path);
          const totalFiles = getEnabledFiles().length;
          if (owners && owners.size < totalFiles) {
            availBadgeEl = document.createElement('span');
            availBadgeEl.className = 'tree-availability';
            availBadgeEl.textContent = `${owners.size}/${totalFiles}`;
            const ownerNames = Array.from(owners).map(f => {
              const parts = f.split('/');
              return parts[parts.length - 1];
            });
            availBadgeEl.title = `Present in ${owners.size} of ${totalFiles} files: ${ownerNames.join(', ')}`;
          }
        }

        if (objType === 'brokensoftlink') {
          const isSelected = selectedDatasetPath === path && !selectedIsRadionuclidesGroup;
          const broken = makeTreeItem('broken-link' + (isSelected ? ' selected' : ''));
          broken.setAttribute('data-path', path);
          if (fileKey) broken.setAttribute('data-file', fileKey);
          broken.addEventListener('click', (e) => selectDataset(path, e));

          const icon = document.createElement('div'); icon.className = 'tree-icon broken-link';
          const label = document.createElement('div'); label.className = 'tree-label';
          label.appendChild(document.createTextNode(key));
          if (linkBadgeEl) label.appendChild(linkBadgeEl);
          if (availBadgeEl) label.appendChild(availBadgeEl);
          const meta = document.createElement('div'); meta.className = 'tree-meta'; meta.style.color = 'var(--color-kvot-accent)'; meta.textContent = 'broken link';

          broken.appendChild(icon); broken.appendChild(label); broken.appendChild(meta);
          container.appendChild(broken);
          if (typeof progressCb === 'function') progressCb(1, path);
          continue;
        }

        if (objType === 'externallink') {
          const isSelected = selectedDatasetPath === path && !selectedIsRadionuclidesGroup;
          const external = makeTreeItem('external-link' + (isSelected ? ' selected' : ''));
          external.setAttribute('data-path', path);
          if (fileKey) external.setAttribute('data-file', fileKey);
          external.addEventListener('click', (e) => selectDataset(path, e));

          const icon = document.createElement('div'); icon.className = 'tree-icon external-link';
          const label = document.createElement('div'); label.className = 'tree-label';
          label.appendChild(document.createTextNode(key));
          if (linkBadgeEl) label.appendChild(linkBadgeEl);
          if (availBadgeEl) label.appendChild(availBadgeEl);
          const meta = document.createElement('div'); meta.className = 'tree-meta'; meta.textContent = `→ ${linkInfo ? linkInfo.filename : '?'}`;

          external.appendChild(icon); external.appendChild(label); external.appendChild(meta);
          container.appendChild(external);
          if (typeof progressCb === 'function') progressCb(1, path);
          continue;
        }

        if (objType === 'group') {
          const isSelected = selectedDatasetPath === path && selectedIsRadionuclidesGroup;

          let groupExpandable = true;
          if (intersectedPaths) {
            groupExpandable = Array.from(intersectedPaths).some(p => p === path || p.startsWith(path + '/'));
          }

          const groupItem = makeTreeItem('group' + (isSelected ? ' expanded' : ''));
          groupItem.setAttribute('data-path', path);
          if (fileKey) groupItem.setAttribute('data-file', fileKey);
          groupItem.addEventListener('click', toggleGroup);

          const toggleDiv = document.createElement('div');
          if (groupExpandable) {
            toggleDiv.className = 'tree-toggle' + (isSelected ? '' : ' collapsed');
            toggleDiv.textContent = '▶';
            toggleDiv.addEventListener('click', (e) => { e.stopPropagation(); toggleGroupExpansion(e, path); });
          } else {
            toggleDiv.className = 'tree-toggle no-toggle';
          }

          const icon = document.createElement('div'); icon.className = 'tree-icon folder';
          const label = document.createElement('div'); label.className = 'tree-label';
          label.appendChild(document.createTextNode(key));
          if (linkBadgeEl) label.appendChild(linkBadgeEl);
          if (availBadgeEl) label.appendChild(availBadgeEl);

          groupItem.appendChild(toggleDiv); groupItem.appendChild(icon); groupItem.appendChild(label);
          container.appendChild(groupItem);
          if (typeof progressCb === 'function') progressCb(1, path);

          try {
            if (topLevelLazy && prefix === '') {
              const placeholder = document.createElement('div');
              placeholder.className = 'tree-group-children' + (isSelected ? ' expanded' : '');
              placeholder.setAttribute('data-lazy', 'true');
              placeholder.setAttribute('data-loaded', 'false');
              container.appendChild(placeholder);
            } else {
              const subFrag = await buildTree(obj, path, true, '', intersectedPaths, fileKey, progressCb, false, (typeof maxDepth === 'number' ? maxDepth - 1 : Infinity), pathOwnership);
              const childrenWrapper = document.createElement('div');
              childrenWrapper.className = 'tree-group-children' + (isSelected ? ' expanded' : '');

              if (subFrag && subFrag.childNodes.length > 0) {
                childrenWrapper.appendChild(subFrag);
              } else {
                const hasChildren = (FileService.keys(obj) || []).length > 0;
                if (hasChildren) {
                  childrenWrapper.setAttribute('data-lazy', 'true');
                  childrenWrapper.setAttribute('data-loaded', 'false');
                } else {
                  const empty = document.createElement('div');
                  empty.style.color = '#999'; empty.style.padding = '8px'; empty.style.fontSize = '12px';
                  empty.textContent = '(empty)';
                  childrenWrapper.appendChild(empty);
                }
              }
              container.appendChild(childrenWrapper);
            }
          } catch (subErr) {
            console.error('Error getting sub-items for', key, subErr);
            const errorWrapper = document.createElement('div');
            errorWrapper.className = 'tree-group-children';
            const msg = document.createElement('div');
            msg.style.color = 'red'; msg.style.padding = '8px'; msg.style.fontSize = '12px';
            msg.textContent = `(error: ${subErr?.message || subErr})`;
            errorWrapper.appendChild(msg);
            container.appendChild(errorWrapper);
            if (typeof progressCb === 'function') progressCb(1, path);
          }
        } else if (objType === 'dataset') {
          const shape = obj.shape?.length ? `${obj.shape.join('×')}` : 'scalar';
          const formattedDtype = formatDataType(obj.dtype);
          const isSelected = selectedDatasetPath === path && !selectedIsRadionuclidesGroup;

          const ds = makeTreeItem('dataset' + (isSelected ? ' selected' : ''));
          ds.setAttribute('data-path', path);
          if (fileKey) ds.setAttribute('data-file', fileKey);
          ds.addEventListener('click', (e) => selectDataset(path, e));

          const icon = document.createElement('div'); icon.className = 'tree-icon dataset';
          const label = document.createElement('div'); label.className = 'tree-label';
          label.appendChild(document.createTextNode(key));
          if (linkBadgeEl) label.appendChild(linkBadgeEl);
          if (availBadgeEl) label.appendChild(availBadgeEl);
          const meta = document.createElement('div'); meta.className = 'tree-meta'; meta.textContent = `${formattedDtype} [${shape}]`;

          ds.appendChild(icon); ds.appendChild(label); ds.appendChild(meta);
          container.appendChild(ds);
          if (typeof progressCb === 'function') progressCb(1, path);
        }
      } catch (e) {
        console.error('Error with key', key, ':', e.message || e);
        const errEl = document.createElement('div');
        errEl.className = 'tree-item';
        errEl.style.color = 'red'; errEl.style.fontSize = '12px';
        errEl.textContent = `⚠️ ${key}`;
        container.appendChild(errEl);
      }

      if (++_yieldCounter % 50 === 0) await new Promise(r => setTimeout(r, 0));
    }
  } catch (e) {
    console.error('buildTree error:', e);
  }

  return frag;
}



