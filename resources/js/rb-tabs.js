/* ==========================================================================
   5. TAB MANAGEMENT
   ========================================================================== */

let _fileTabTooltipEl = null;

/**
 * Ensure a shared tooltip element exists for file tabs.
 * @returns {HTMLElement}
 */
function ensureFileTabTooltip() {
  if (_fileTabTooltipEl && document.body.contains(_fileTabTooltipEl)) return _fileTabTooltipEl;
  const el = document.createElement('div');
  el.id = 'fileTabTooltip';
  el.className = 'file-tab-tooltip';
  el.style.display = 'none';
  document.body.appendChild(el);
  _fileTabTooltipEl = el;
  return el;
}

/**
 * Very small sanitizer for HTML shown in tooltips.
 * Removes script/style tags and inline event handlers.
 *
 * @param {string} html
 * @returns {string}
 */
function sanitizeTooltipHtml(html) {
  if (!html) return '';
  const container = document.createElement('div');
  container.innerHTML = String(html);
  container.querySelectorAll('script, style').forEach(n => n.remove());
  container.querySelectorAll('*').forEach(node => {
    for (const attr of Array.from(node.attributes || [])) {
      const attrName = (attr.name || '').toLowerCase();
      const attrVal = String(attr.value || '').trim().toLowerCase();
      if (attrName.startsWith('on')) node.removeAttribute(attr.name);
      if ((attrName === 'href' || attrName === 'src') && attrVal.startsWith('javascript:')) {
        node.removeAttribute(attr.name);
      }
    }
  });
  return container.innerHTML;
}

/**
 * Read root-level Information attribute HTML from a file, if present.
 * @param {Object} file
 * @returns {string}
 */
function getRootInformationHtml(file) {
  if (!file) return '';
  try {
    const root = FileService.get(file, '/');
    const attrCandidates = [
      getAttr(root, 'Information'),
      getAttr(root, 'information')
    ];
    const info = attrCandidates.find(v => v !== undefined && v !== null && String(v).trim() !== '');
    return info !== undefined && info !== null ? String(info) : '';
  } catch (e) {
    return '';
  }
}

/**
 * Position tooltip near mouse while keeping it inside viewport.
 * @param {HTMLElement} tooltip
 * @param {MouseEvent} evt
 */
function positionFileTabTooltip(tooltip, evt) {
  const margin = 12;
  const vw = window.innerWidth || document.documentElement.clientWidth;
  const vh = window.innerHeight || document.documentElement.clientHeight;
  const rect = tooltip.getBoundingClientRect();
  let left = evt.clientX + margin;
  let top = evt.clientY + margin;
  if (left + rect.width > vw - margin) left = vw - rect.width - margin;
  if (top + rect.height > vh - margin) top = vh - rect.height - margin;
  if (left < margin) left = margin;
  if (top < margin) top = margin;
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}

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
function updateTabs(forceRefresh) {
  const tabsContainer = document.getElementById('fileTabs');
  const previousTreeFile = currentTreeFile;
  const tooltipHtmlByFile = {};

  // Drop stale handles before any root/attribute reads.
  fileOrder = fileOrder.filter(key => !!getFileOrNull(key));

  for (const key of fileOrder) {
    const infoHtml = getRootInformationHtml(loadedFiles[key]);
    const safeInfoHtml = sanitizeTooltipHtml(infoHtml);
    tooltipHtmlByFile[key] = `<div class="file-tab-tooltip-title">${escapeHtml(key)}</div>${safeInfoHtml ? `<div class="file-tab-tooltip-info">${safeInfoHtml}</div>` : ''}`;
  }
  
  // Render tabs
  tabsContainer.innerHTML = fileOrder.map(key => {
    const isEnabled = fileStates[key];
    return `
      <div class="file-tab ${isEnabled ? 'enabled' : 'disabled'}" data-file="${escapeHtml(key)}">
        <div class="file-tab-name">${escapeHtml(key)}</div>
        <div class="file-tab-close" onclick="event.stopPropagation(); removeFile('${key.replace(/'/g, "\\'")}')">×</div>
      </div>
    `;
  }).join('');
  
  // Add click handlers for toggle
  document.querySelectorAll('.file-tab').forEach(tab => {
    const fileName = tab.getAttribute('data-file');
    tab.removeAttribute('title');
    tab.querySelectorAll('[title]').forEach(el => el.removeAttribute('title'));

    tab.addEventListener('mouseenter', (evt) => {
      const tooltip = ensureFileTabTooltip();
      tooltip.innerHTML = tooltipHtmlByFile[fileName] || `<div class="file-tab-tooltip-title">${escapeHtml(fileName || '')}</div>`;
      tooltip.style.display = 'block';
      positionFileTabTooltip(tooltip, evt);
    });

    tab.addEventListener('mousemove', (evt) => {
      const tooltip = ensureFileTabTooltip();
      if (tooltip.style.display !== 'none') {
        positionFileTabTooltip(tooltip, evt);
      }
    });

    tab.addEventListener('mouseleave', () => {
      const tooltip = ensureFileTabTooltip();
      tooltip.style.display = 'none';
    });

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
        
        // Reset tree mode and selections on reorder
        resetTreeModeToSeparated();

        if (treeFileChanged) {
          refreshTreeStructure();
        }
      }
    });
  }
  
  // Check if tree file changed
  const newTreeFile = getTreeFile();
  const treeFileChanged = previousTreeFile !== newTreeFile;
  currentTreeFile = newTreeFile;
  
  // Always reset tree mode to separated and clear selections on any tab change.
  // This avoids complex stale-state issues with intersect/union modes.
  const enabledCount = getEnabledFiles().length;
  resetTreeModeToSeparated();

  // Show/hide tree mode selector based on number of enabled files
  const treeModeContainer = document.getElementById('treeModeContainer');
  if (treeModeContainer) {
    treeModeContainer.style.display = enabledCount > 1 ? 'inline-flex' : 'none';
  }

  // Hide search when no files
  if (enabledCount === 0) {
    document.querySelector('.search-container')?.classList.remove('visible');
    try { EventBus.emit('selection:changed', { mode: 'none' }); } catch (e) {}
  }
  
  console.log('updateTabs - Previous:', previousTreeFile, 'New:', newTreeFile, 'Changed:', treeFileChanged);
  
  // Only refresh the tree when necessary (tree root changed or enabled set changed).
  // This prevents frequent/expensive refreshes and avoids triggering search-aware
  // background expansions on unrelated UI clicks.
  const prevEnabledCount = window._lastEnabledCount || 0;
  const needRefresh = forceRefresh || treeFileChanged || (enabledCount !== prevEnabledCount);
  window._lastEnabledCount = enabledCount;

  let refreshPromise;
  if (needRefresh) {
    // Cancel any in-flight worker intersection requests since enabled files changed.
    try {
      for (const wid of Object.keys(_treeWorkerPending)) {
        try { ensureTreeWorker().postMessage({ cmd: 'cancel', id: wid }); } catch (e) {}
        try { clearTimeout(_treeWorkerPending[wid]._timeout); } catch (e) {}
        delete _treeWorkerPending[wid];
        console.debug('[updateTabs] cancelled in-flight worker id=', wid);
      }
    } catch (e) { /* ignore */ }

    // Immediate visual feedback while tree rebuilds
    try {
      const tree = document.getElementById('tree');
      if (tree) {
        tree.innerHTML = `<div class="loading">Refreshing tree… <span class="tree-inline-spinner" aria-hidden="true"></span></div>`;
        void tree.offsetHeight;
        document.querySelector('.search-container')?.classList.remove('visible');
      }
    } catch (e) { /* ignore UI update errors */ }

    // Run the refresh asynchronously (yield so the spinner is visible first)
    refreshPromise = new Promise((resolve, reject) => {
      setTimeout(() => {
        refreshTreeStructure().then(resolve, reject);
      }, 50);
    });
  } else {
    refreshPromise = Promise.resolve();
  }

  // Selections were already cleared by resetTreeModeToSeparated(),
  // so no need to call refreshInfoAndChart() or validateSelectedDatasets().

  return refreshPromise;
}

