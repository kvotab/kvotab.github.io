/* ==========================================================================
   5. THE FILES BAR

   The files open, a box each in the bar above the panels (rb.html #rbBar).
   They were tabs in the site's header once, and the names here (updateTabs,
   .file-tab, the tab's tooltip) are theirs still.
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
 * Fill the tab tooltip: the file's name, and its root's Information, which a
 * file writes as markup, through kvotSanitizeHtml -- the page's one sanitiser
 * for markup from a file (kvot-safe.js), whose fragment is appended, never
 * parsed again.
 *
 * It had a denylist of its own, which handed back a string for innerHTML: the
 * Information of a hostile file sent the page to another address the moment
 * its tab was hovered (<meta http-equiv="refresh">), loaded a stylesheet of
 * its choosing, and kept javascript: links, by a tab inside the scheme or an
 * SVG's xlink:href.
 *
 * @param {HTMLElement} tooltip
 * @param {string} fileName
 * @param {string} infoHtml - The root's Information as the file has it, or ''
 */
function fillFileTabTooltip(tooltip, fileName, infoHtml) {
  tooltip.textContent = '';
  const title = document.createElement('div');
  title.className = 'file-tab-tooltip-title';
  title.textContent = fileName || '';
  tooltip.appendChild(title);
  if (infoHtml) {
    const info = document.createElement('div');
    info.className = 'file-tab-tooltip-info';
    info.appendChild(kvotSanitizeHtml(infoHtml));
    tooltip.appendChild(info);
  }
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
  const infoHtmlByFile = {};

  // Drop stale handles before any root/attribute reads.
  fileOrder = fileOrder.filter(key => !!getFileOrNull(key));

  for (const key of fileOrder) {
    infoHtmlByFile[key] = getRootInformationHtml(loadedFiles[key]);
  }
  
  // What had the keyboard among the boxes, which are about to be drawn anew.
  const focus = focusedFileBox(tabsContainer);

  // Render the boxes (no inline event handlers — listeners attached below).
  // A ticked file is numbered by its place among the ticked ones: 1 is the
  // one the others are drawn against (rb-chart.js gives it the full lines).
  let ticked = 0;
  tabsContainer.innerHTML = fileOrder.map(key => {
    const isEnabled = !!fileStates[key];
    const name = escapeHtml(key);
    return `<div class="file-tab ${isEnabled ? 'enabled' : 'disabled'}" role="listitem" data-file="${name}">`
      + '<label class="file-tab-main">'
      + `<input type="checkbox" class="file-tab-check"${isEnabled ? ' checked' : ''} aria-label="Show ${name} in the tree and the charts">`
      + `<span class="file-tab-order" aria-hidden="true">${isEnabled ? ++ticked : ''}</span>`
      + `<span class="file-tab-name">${name}</span>`
      + '</label>'
      + `<button type="button" class="file-tab-close" aria-label="Close ${name}" title="Close the file">×</button>`
      + '</div>';
  }).join('');

  // Attach event listeners to each box
  tabsContainer.querySelectorAll('.file-tab').forEach(tab => {
    const fileName = tab.getAttribute('data-file');
    tab.removeAttribute('title');

    // Tooltip
    tab.addEventListener('mouseenter', (evt) => {
      if (!shouldFileTabTooltipShow(evt)) return;
      const tooltip = ensureFileTabTooltip();
      fillFileTabTooltip(tooltip, fileName, infoHtmlByFile[fileName]);
      tooltip.style.display = 'block';
      positionFileTabTooltip(tooltip, evt);
    });
    tab.addEventListener('mousemove', (evt) => {
      const tooltip = ensureFileTabTooltip();
      // Moving within a tab is also how a suppressed tooltip comes back: the
      // tab it belongs to is already entered, so no mouseenter is coming.
      if (tooltip.style.display === 'none') {
        if (!shouldFileTabTooltipShow(evt)) return;
        fillFileTabTooltip(tooltip, fileName, infoHtmlByFile[fileName]);
        tooltip.style.display = 'block';
      }
      positionFileTabTooltip(tooltip, evt);
    });
    tab.addEventListener('mouseleave', () => {
      ensureFileTabTooltip().style.display = 'none';
    });

    // × closes the file — stopPropagation keeps the click from the box itself
    tab.querySelector('.file-tab-close').addEventListener('click', (e) => {
      e.stopPropagation();
      // Before the box goes: its tooltip stays away until the pointer moves,
      // rather than re-appearing for whichever box slides into its place.
      hideFileTabTooltip(e);
      closeFileBox(fileName, tab.contains(document.activeElement));
    });

    // The tick: the file in the tree and the charts, or not. A click on the
    // box's edge, beside its label, ticks it as the label does.
    tab.querySelector('.file-tab-check').addEventListener('change', () => toggleFileState(fileName));
    tab.addEventListener('click', (e) => { if (e.target === tab) toggleFileState(fileName); });

    // Delete closes the file; Alt with an arrow moves it.
    tab.addEventListener('keydown', (e) => fileBoxKey(e, fileName));
  });

  restoreFileBoxFocus(tabsContainer, focus);

  // Drag to reorder (SortableJS), set up once: the boxes are drawn anew in
  // the same list, and an instance made at every drawing answered each drag
  // once for every drawing there had been.
  if (window.Sortable && !Sortable.get(tabsContainer)) {
    Sortable.create(tabsContainer, {
      animation: 150,
      draggable: '.file-tab',
      ghostClass: 'sortable-ghost',
      dragClass: 'sortable-drag',
      // A press on × is a click on it, never the start of a drag.
      filter: '.file-tab-close',
      preventOnFilter: false,
      // On a touch screen a box moves after a short press, so a tap ticks it.
      delay: 150,
      delayOnTouchOnly: true,
      onEnd: () => reorderFiles([...tabsContainer.querySelectorAll('.file-tab')].map(b => b.getAttribute('data-file')))
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


/* ==========================================================================
   THE FILES BAR: what the boxes do besides being drawn, the Open menu, and
   the full window
   ========================================================================== */

/**
 * Which box has the keyboard, and on which of its two controls, if any.
 *
 * @param {HTMLElement} list - #fileTabs
 * @returns {{file: string, close: boolean}|null}
 */
function focusedFileBox(list) {
  const el = document.activeElement;
  const box = el && list && list.contains(el) ? el.closest('.file-tab') : null;
  if (!box) return null;
  return { file: box.getAttribute('data-file'), close: el.classList.contains('file-tab-close') };
}

/**
 * Give the keyboard back to the box it was on, after the boxes were drawn
 * anew: a tick, a move or a close with the keyboard keeps its place.
 *
 * @param {HTMLElement} list - #fileTabs
 * @param {{file: string, close: boolean}|null} focus
 */
function restoreFileBoxFocus(list, focus) {
  if (!focus) return;
  const box = [...list.querySelectorAll('.file-tab')].find(b => b.getAttribute('data-file') === focus.file);
  const target = box && box.querySelector(focus.close ? '.file-tab-close' : '.file-tab-check');
  if (target) target.focus({ preventScroll: true });
}

/**
 * Close a file from its box. With the keyboard on the box, it goes to the
 * next box (the one before, at the end), or to Open when none is left.
 *
 * @param {string} fileName
 * @param {boolean} keepFocus - Whether the keyboard was on the box
 * @returns {Promise<void>}
 */
async function closeFileBox(fileName, keepFocus) {
  const at = fileOrder.indexOf(fileName);
  const next = at < 0 ? null : (fileOrder[at + 1] ?? fileOrder[at - 1] ?? null);
  await removeFile(fileName);
  if (!keepFocus) return;
  const list = document.getElementById('fileTabs');
  if (next && fileOrder.includes(next)) restoreFileBoxFocus(list, { file: next, close: false });
  else document.getElementById('rbOpen')?.focus({ preventScroll: true });
}

/**
 * Put the files in a new order: the boxes are drawn with their new numbers,
 * and the tree is drawn again when its first file changed (updateTabs).
 * The same order again does nothing, as when a box is pressed and let go
 * where it was.
 *
 * @param {string[]} order - Every file open, in the new order
 */
function reorderFiles(order) {
  if (order.length !== fileOrder.length || order.every((key, i) => key === fileOrder[i])) return;
  fileOrder = order;
  updateTabs();
}

/**
 * The keys on a box, besides Tab, and Space on its tick: Delete (or
 * Backspace) closes the file; Alt with an arrow moves it one place, as a
 * drag would.
 *
 * @param {KeyboardEvent} e
 * @param {string} fileName
 */
function fileBoxKey(e, fileName) {
  if (e.ctrlKey || e.metaKey) return;
  if ((e.key === 'Delete' || e.key === 'Backspace') && !e.altKey) {
    e.preventDefault();
    hideFileTabTooltip();
    closeFileBox(fileName, true);
    return;
  }
  const step = e.altKey ? { ArrowLeft: -1, ArrowUp: -1, ArrowRight: 1, ArrowDown: 1 }[e.key] : undefined;
  if (!step) return;
  e.preventDefault();
  const at = fileOrder.indexOf(fileName);
  const to = at + step;
  if (at < 0 || to < 0 || to >= fileOrder.length) return;
  const order = fileOrder.slice();
  order.splice(at, 1);
  order.splice(to, 0, fileName);
  reorderFiles(order);
}

/*
  Open: a menu that is a popover (rb.html), opened and shut by the browser --
  its button, a click elsewhere, Escape. Here it is put under its button, left
  edges together, or where the window has room; the first way takes the focus
  and the arrow keys move through the rest; a way chosen shuts it, and so does
  the page scrolling under it. A browser without popovers (Safari before 17,
  Firefox before 125) opens the file picker from the button, the way most
  used.
*/
function setupOpenMenu() {
  const menu = document.getElementById('rbOpenMenu');
  const button = document.getElementById('rbOpen');
  if (!menu || !button) return;
  if (typeof HTMLElement.prototype.showPopover !== 'function') {
    button.addEventListener('click', () => document.getElementById('fileInput').click());
    return;
  }
  const items = () => [...menu.querySelectorAll('.rb-menu-item')].filter(b => !b.hidden && !b.disabled);
  button.setAttribute('aria-expanded', 'false');
  menu.addEventListener('beforetoggle', (ev) => {
    if (ev.newState !== 'open') return;
    const r = button.getBoundingClientRect();
    menu.style.top = `${Math.round(r.bottom + 4)}px`;
    menu.style.left = `${Math.max(4, Math.round(r.left))}px`;
  });
  menu.addEventListener('toggle', (ev) => {
    button.setAttribute('aria-expanded', String(ev.newState === 'open'));
    if (ev.newState !== 'open') return;
    const m = menu.getBoundingClientRect();
    const width = document.documentElement.clientWidth;
    if (m.right > width - 4) menu.style.left = `${Math.max(4, Math.round(width - 4 - m.width))}px`;
    if (m.bottom > window.innerHeight - 4) {
      menu.style.top = `${Math.max(4, Math.round(button.getBoundingClientRect().top - 4 - m.height))}px`;
    }
    const first = items()[0];
    if (first) first.focus({ preventScroll: true });
  });
  // A way chosen shuts the menu; its action runs all the same (kvot-actions,
  // on the document, hears the click after the menu does).
  menu.addEventListener('click', (ev) => {
    if (ev.target.closest('.rb-menu-item') && menu.matches(':popover-open')) menu.hidePopover();
  });
  menu.addEventListener('keydown', (ev) => {
    const list = items();
    const at = list.indexOf(document.activeElement);
    const to = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: list.length - 1 }[ev.key];
    if (to === undefined || !list.length) return;
    ev.preventDefault();
    list[(to + list.length) % list.length].focus();
  });
  document.addEventListener('scroll', (ev) => {
    if (menu.matches(':popover-open') && !menu.contains(ev.target)) menu.hidePopover();
  }, true);
  // A press anywhere but on the menu or its button shuts it. The browser does
  // that itself, except over a chart: Plotly lays a cover over the page on
  // the press, the release lands on the cover, and the menu stayed open.
  document.addEventListener('pointerdown', (ev) => {
    if (menu.matches(':popover-open') && !menu.contains(ev.target) && !button.contains(ev.target)) menu.hidePopover();
  }, true);
}

/*
  The full window (rb.css :root.rb-full): the page without the site's header
  and footer, by the button at the files bar's right end; kept for the next
  visit, which the page's head puts in it before the first paint. The chart
  follows its box (rb-init.js watches it), so nothing is redrawn here.
*/
const RB_FULL_KEY = 'kvot.rb.full';

function toggleFullWindow() {
  setFullWindow(!document.documentElement.classList.contains('rb-full'));
}

/**
 * @param {boolean} on - Whether the page is to be the full window
 */
function setFullWindow(on) {
  document.documentElement.classList.toggle('rb-full', !!on);
  try { localStorage.setItem(RB_FULL_KEY, on ? '1' : '0'); } catch (e) { /* storage unavailable: for this visit only */ }
  fullWindowState();
  placeUnderFilesBar();
}

/** The button says what it does from here: out to the full window, or back. */
function fullWindowState() {
  const on = document.documentElement.classList.contains('rb-full');
  const button = document.getElementById('rbFull');
  if (!button) return;
  button.setAttribute('aria-pressed', String(on));
  button.setAttribute('aria-label', on ? 'Leave the full window' : 'Full window');
  button.title = on ? 'Show the site\'s header and footer again' : 'Full window: the page without the site\'s header and footer';
}

/*
  The site's message banner (kvot-errors.js) is fixed 52px from the top of
  the window, which is where the files bar is: while it showed it covered the
  boxes and Open. rb.css puts it under the bar instead, from --rb-bar-bottom,
  kept here as the bar grows a row of boxes or the full window moves it up.
*/
function placeUnderFilesBar() {
  const bar = document.getElementById('rbBar');
  if (bar) document.documentElement.style.setProperty('--rb-bar-bottom', `${Math.round(bar.getBoundingClientRect().bottom)}px`);
}

/** The bar's start, from rb-init.js: the Open menu, the full window's button, and the banner's place. */
function setupFilesBar() {
  setupOpenMenu();
  fullWindowState();
  const bar = document.getElementById('rbBar');
  if (bar && window.ResizeObserver) new ResizeObserver(placeUnderFilesBar).observe(bar);
  placeUnderFilesBar();
}
