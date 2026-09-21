/* ==========================================================================
   5. TAB MANAGEMENT
   ========================================================================== */

'use strict';   // see the script manifest in rb.html for why
let _fileTabTooltipEl = null;
// Where the pointer was when a tooltip was last dismissed by a click, or null.
// While this is set the tooltip stays away; see hideFileTabTooltip.
let _tooltipSuppressedAt = null;

/**
 * Ensure a shared tooltip element exists for file tabs.
 * @returns {HTMLElement}
 */
/**
 * Put the tab tooltip away.
 *
 * It is a div on the body rather than a title attribute, shown on a tab's
 * mouseenter and hidden on its mouseleave -- and a tab that is REMOVED never
 * gets a mouseleave, so closing a file left its tooltip on the screen.
 *
 * Hiding it is not enough on its own. Closing a tab shuffles the ones after it
 * leftwards, one slides under the stationary pointer, Chrome fires mouseenter
 * on it, and a tooltip appears again straight away -- for the next file along,
 * which nobody pointed at. What a title attribute does after a click is stay
 * away until the pointer actually moves, so `untilPointerMoves` does that:
 * the position is remembered here and shouldFileTabTooltipShow refuses until
 * the pointer has left it.
 *
 * @param {MouseEvent|null} [untilPointerMoves] the click that dismissed it
 */
function hideFileTabTooltip(untilPointerMoves) {
  if (_fileTabTooltipEl) _fileTabTooltipEl.style.display = 'none';
  // Only ever set here, never cleared: removing an enabled file goes on to
  // call updateTabs, which hides the tooltip again with no event, and an
  // `else` branch here would wipe the suppression the close had just asked
  // for -- which is precisely the case this was written for. It is cleared
  // when the pointer moves, in shouldFileTabTooltipShow.
  if (untilPointerMoves) {
    _tooltipSuppressedAt = { x: untilPointerMoves.clientX, y: untilPointerMoves.clientY };
  }
}

/**
 * Whether a tooltip may appear for a pointer at this event.
 *
 * A couple of pixels of slack, because a click can be followed by a mousemove
 * at the same place and that is not the pointer moving.
 */
function shouldFileTabTooltipShow(evt) {
  if (!_tooltipSuppressedAt) return true;
  const moved = Math.abs(evt.clientX - _tooltipSuppressedAt.x) > 2
    || Math.abs(evt.clientY - _tooltipSuppressedAt.y) > 2;
  if (moved) _tooltipSuppressedAt = null;
  return moved;
}

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
  // The tabs about to be replaced include whichever one the pointer is over,
  // and a removed element cannot report that the pointer has left it.
  hideFileTabTooltip();
  const previousTreeFile = currentTreeFile;
  const tooltipHtmlByFile = {};

  // Drop stale handles before any root/attribute reads.
  fileOrder = fileOrder.filter(key => !!getFileOrNull(key));

  for (const key of fileOrder) {
    const infoHtml = getRootInformationHtml(loadedFiles[key]);
    const safeInfoHtml = sanitizeTooltipHtml(infoHtml);
    tooltipHtmlByFile[key] = `<div class="file-tab-tooltip-title">${escapeHtml(key)}</div>${safeInfoHtml ? `<div class="file-tab-tooltip-info">${safeInfoHtml}</div>` : ''}`;
  }
  
  // Render tabs (no inline event handlers — listeners attached below)
  tabsContainer.innerHTML = fileOrder.map(key => {
    const isEnabled = fileStates[key];
    return `
      <div class="file-tab ${isEnabled ? 'enabled' : 'disabled'}" data-file="${escapeHtml(key)}">
        <div class="file-tab-name">${escapeHtml(key)}</div>
        <div class="file-tab-close" title="Remove file">×</div>
      </div>
    `;
  }).join('');

  // Attach event listeners to each tab
  document.querySelectorAll('.file-tab').forEach(tab => {
    const fileName = tab.getAttribute('data-file');
    tab.removeAttribute('title');

    // Tooltip
    tab.addEventListener('mouseenter', (evt) => {
      if (!shouldFileTabTooltipShow(evt)) return;
      const tooltip = ensureFileTabTooltip();
      tooltip.innerHTML = tooltipHtmlByFile[fileName] || `<div class="file-tab-tooltip-title">${escapeHtml(fileName || '')}</div>`;
      tooltip.style.display = 'block';
      positionFileTabTooltip(tooltip, evt);
    });
    tab.addEventListener('mousemove', (evt) => {
      const tooltip = ensureFileTabTooltip();
      // Moving within a tab is also how a suppressed tooltip comes back: the
      // tab it belongs to is already entered, so no mouseenter is coming.
      if (tooltip.style.display === 'none') {
        if (!shouldFileTabTooltipShow(evt)) return;
        tooltip.innerHTML = tooltipHtmlByFile[fileName]
          || `<div class="file-tab-tooltip-title">${escapeHtml(fileName || '')}</div>`;
        tooltip.style.display = 'block';
      }
      positionFileTabTooltip(tooltip, evt);
    });
    tab.addEventListener('mouseleave', () => {
      ensureFileTabTooltip().style.display = 'none';
    });

    // Close button — stopPropagation prevents the tab toggle from also firing
    const closeBtn = tab.querySelector('.file-tab-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        // Before the tab goes: this one stays away until the pointer moves,
        // rather than re-appearing for whichever tab slides into its place.
        hideFileTabTooltip(e);
        removeFile(fileName);
      });
    }

    // Tab body — toggle enabled/disabled state
    tab.addEventListener('click', () => toggleFileState(fileName));
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
    try { EventBus.emit('selection:changed', { mode: 'none' }); } catch (e) { ignoreFailure('onEnd', e); }
  }
  
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
        try { ensureTreeWorker().postMessage({ cmd: 'cancel', id: wid }); } catch (e) { ignoreFailure('onEnd', e); }
        try { clearTimeout(_treeWorkerPending[wid]._timeout); } catch (e) { ignoreFailure('onEnd', e); }
        delete _treeWorkerPending[wid];
        kvotTrace('[updateTabs] cancelled in-flight worker id=', wid);
      }
    } catch (e) { ignoreFailure('onEnd', e); }

    // Immediate visual feedback while tree rebuilds
    try {
      const tree = document.getElementById('tree');
      if (tree) {
        tree.innerHTML = `<div class="loading">Refreshing tree… <span class="tree-inline-spinner" aria-hidden="true"></span></div>`;
        void tree.offsetHeight;
        document.querySelector('.search-container')?.classList.remove('visible');
      }
    } catch (e) { ignoreFailure('onEnd', e); }

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

