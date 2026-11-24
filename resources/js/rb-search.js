/* ==========================================================================
   12. SEARCH FUNCTIONALITY
   ========================================================================== */

'use strict';   // see the script manifest in rb.html for why
/**
 * Convert wildcard pattern to regular expression
 * @param {string} pattern - Wildcard pattern (supports *)
 * @returns {RegExp} Compiled regular expression
 */
function wildcardToRegex(pattern) {
  const escaped = pattern.replace(/[.+?^${}()|[\\\]\\]/g, '\\$&');
  const regexPattern = escaped.replace(/\*/g, '.*');
  return new RegExp(regexPattern, 'i');
}

/**
 * Detect whether the search term appears to be a full-path search.
 * A term containing '/' is one. A term containing '.', whitespace or '*' is
 * one when it matches no name in the tree as written.
 * @param {string} term
 * @returns {boolean}
 */
function isPathSearchTerm(term) {
  /*
    A slash is unambiguous. A dot or a space is not: nuclide and dataset names
    routinely contain dots (Am-241.total, Kd_Mo_2.5), and treating those as
    separators rewrote the term to 'Am-241/total', which then matched neither
    the label nor the full path. Only treat dots and spaces as separators when
    the term does not already match a name as written.
  */
  // A star stands for any characters, slashes among them, so 'Kd*Po' finds
  // .../Kd/soil/Po as the same term with a slash before Po does; tried on
  // names alone it found nothing. (Written as line comments: that term ends a
  // block comment.) It goes to the full path on the same terms as a dot, only
  // when no name holds the whole term: 'Pu*9' looks for Pu-239, and on full
  // paths it would also find every item below one, and every name with a 9
  // below a group whose name holds 'pu' (input_data) -- three times the items
  // in a results file.
  const value = String(term);
  if (value.includes('/')) return true;
  if (!/[.\s*]/.test(value)) return false;
  return !labelMatchesSomeTreeItem(value);
}

/**
 * True when the term, taken literally, already matches a visible tree label.
 * Used to decide that a dot, a space or a star belongs to a name rather than
 * standing for a slash in a path.
 *
 * @param {string} term
 * @returns {boolean}
 */
function labelMatchesSomeTreeItem(term) {
  const tree = document.getElementById('tree');
  if (!tree) return false;
  let regex;
  try { regex = wildcardToRegex(term); } catch (e) { return false; }
  for (const label of tree.querySelectorAll('.tree-label')) {
    if (regex.test(getLabelText(label))) return true;
  }
  return false;
}

/**
 * Normalize a path-style search term by treating dots and spaces as '/'
 * so users may write 'grp.sub dset' or 'grp.sub.dset' and it will match
 * '/grp/sub/dset' paths in the tree. Keeps '*' wildcards intact.
 * @param {string} term
 * @returns {string}
 */
function normalizePathSearchTerm(term) {
  return String(term).trim().replace(/[\.\s]+/g, '/');
}

/**
 * Return the last non-empty segment of a path-like search term for
 * highlighting the node label (final name) in the tree.
 *
 * Where that segment has a star and the name does not hold all of it, the
 * star stood for a slash ('Kd*Po' matching .../Kd/soil/Po), and what the
 * name holds is the part after the last star.
 *
 * @param {string} term
 * @param {string} [name] - The matching item's own name
 * @returns {string}
 */
function labelSegmentFromPathTerm(term, name) {
  const parts = normalizePathSearchTerm(term).split('/').filter(Boolean);
  const last = parts.length ? parts[parts.length - 1] : term;
  if (name == null || !last.includes('*') || wildcardToRegex(last).test(name)) return last;
  const pieces = last.split('*').filter(Boolean);
  return pieces.length ? pieces[pieces.length - 1] : last;
}

/**
 * Get only the node-name text from a .tree-label element,
 * excluding child elements like .tree-availability badges.
 * @param {Element} label
 * @returns {string}
 */
function getLabelText(label) {
  let text = '';
  for (const n of label.childNodes) {
    if (n.nodeType === Node.TEXT_NODE) {
      text += n.textContent;
    } else if (n.nodeType === Node.ELEMENT_NODE) {
      // Include text from highlight spans but skip badge elements
      if (n.classList.contains('search-highlight')) {
        text += n.textContent;
      } else if (n.classList.contains('tree-availability') || n.classList.contains('tree-link-badge')) {
        // skip badges
      }
    }
  }
  return text;
}

/**
 * Rewrite a .tree-label's text content while preserving child elements
 * such as .tree-availability badges. Sets the leading text node(s) to
 * the given HTML string without touching trailing element children.
 * @param {Element} label
 * @param {string} html - HTML for the name portion of the label
 */
function setLabelHtml(label, html) {
  // Collect non-text child elements (badges, etc.) to re-append
  const elements = [];
  for (const n of Array.from(label.childNodes)) {
    if (n.nodeType === Node.ELEMENT_NODE && !n.classList.contains('search-highlight')) {
      elements.push(n);
    }
  }
  label.innerHTML = html;
  for (const el of elements) label.appendChild(el);
}

/**
 * Highlight matching text in a string
 * @param {string} text - Original text
 * @param {string} searchTerm - Search term to highlight
 * @returns {string} HTML with highlighted matches
 */
function highlightText(text, searchTerm) {
  if (!searchTerm) return escapeHtml(text);
  
  const regex = wildcardToRegex(searchTerm);
  const match = text.match(regex);
  
  if (!match) return escapeHtml(text);
  
  const matchStart = match.index;
  const matchEnd = matchStart + match[0].length;
  
  const before = escapeHtml(text.substring(0, matchStart));
  const matched = escapeHtml(text.substring(matchStart, matchEnd));
  const after = escapeHtml(text.substring(matchEnd));
  
  return `${before}<span class="search-highlight">${matched}</span>${after}`;
}

// Saved expand state before search began, keyed by data-path of group items.
// null when no search is active.
let _preSearchExpandState = null;

/**
 * Snapshot the current expand/collapse state of every group in the tree.
 * Stores which groups have the `expanded` class and whether toggles are collapsed.
 * @returns {Map<Element, {expanded: boolean, collapsed: boolean}>}
 */
function _captureExpandState(tree) {
  const state = new Map();
  tree.querySelectorAll('.tree-item.group').forEach(groupItem => {
    const toggle = groupItem.querySelector('.tree-toggle');
    const childrenDiv = groupItem.nextElementSibling;
    state.set(groupItem, {
      groupExpanded: groupItem.classList.contains('expanded'),
      toggleCollapsed: toggle ? toggle.classList.contains('collapsed') : true,
      childrenExpanded: childrenDiv ? childrenDiv.classList.contains('expanded') : false,
    });
  });
  return state;
}

/**
 * Restore a previously captured expand/collapse state.
 * @param {Map<Element, Object>} state
 */
function _restoreExpandState(state) {
  state.forEach((saved, groupItem) => {
    const toggle = groupItem.querySelector('.tree-toggle');
    const childrenDiv = groupItem.nextElementSibling;

    if (saved.groupExpanded) {
      groupItem.classList.add('expanded');
    } else {
      groupItem.classList.remove('expanded');
    }

    if (toggle) {
      if (saved.toggleCollapsed) {
        toggle.classList.add('collapsed');
      } else {
        toggle.classList.remove('collapsed');
      }
    }

    if (childrenDiv && childrenDiv.classList.contains('tree-group-children')) {
      if (saved.childrenExpanded) {
        childrenDiv.classList.add('expanded');
      } else {
        childrenDiv.classList.remove('expanded');
      }
    }
  });
}

/**
 * Filter tree view based on search term
 * Shows matching items and their parents, hides non-matching items
 * @param {string} searchTerm - Search term (supports wildcards)
 */
function filterTree(searchTerm) {
  currentSearchTerm = searchTerm;
  // show/hide search ticker depending on term presence
  if (searchTerm && searchTerm.trim()) showSearchTicker();
  else hideSearchTicker();
  const tree = document.getElementById('tree');
  const allItems = tree.querySelectorAll('.tree-item');
  const allChildren = tree.querySelectorAll('.tree-group-children');
  
  // Clear search - restore pre-search state, remove highlights
  if (!searchTerm.trim()) {
    allItems.forEach(item => {
      item.classList.remove('search-hidden', 'search-match');
      const label = item.querySelector('.tree-label');
      if (label) {
        setLabelHtml(label, escapeHtml(getLabelText(label)));
      }
    });
    
    allChildren.forEach(child => {
      child.classList.remove('search-expanded');
    });

    // Restore the expand state that existed before the search started
    if (_preSearchExpandState) {
      _restoreExpandState(_preSearchExpandState);
      _preSearchExpandState = null;
    }
    
    return;
  }

  // Save expand state on first search invocation (transition from no-search to search)
  if (!_preSearchExpandState) {
    _preSearchExpandState = _captureExpandState(tree);
  }
  
  const regexLabel = wildcardToRegex(searchTerm);
  const isPathSearch = isPathSearchTerm(searchTerm);
  const pathRegex = isPathSearch ? wildcardToRegex(normalizePathSearchTerm(searchTerm)) : null;
  const matchingItems = new Set();
  const itemsToShow = new Set();
  
  // First pass: find all matching items (match label *or* full path when path-style search)
  allItems.forEach(item => {
    const label = item.querySelector('.tree-label');
    if (!label) return;

    const text = getLabelText(label);
    let matches = regexLabel.test(text);

    // If user typed a path-style query (contains /, or a ., space or * that no
    // name holds), also test the element's `data-path` attribute (full HDF5
    // path) using a normalized regex.
    if (!matches && isPathSearch) {
      const pathAttr = item.getAttribute('data-path') || '';
      if (pathRegex && pathRegex.test(pathAttr)) matches = true;
    }

    if (matches) {
      matchingItems.add(item);
      item.classList.add('search-match');
      // Highlight only the final name in the label when doing path searches
      const labelSearch = isPathSearch ? labelSegmentFromPathTerm(searchTerm, text) : searchTerm;
      setLabelHtml(label, highlightText(text, labelSearch));
    } else {
      const wasMatch = item.classList.contains('search-match');
      item.classList.remove('search-match');
      /* Only rewrite the label when it actually carries highlight markup. */
      if (wasMatch || label.querySelector('.search-highlight')) {
        setLabelHtml(label, escapeHtml(text));
      }
    }
  });
  
  // Second pass: build set of items to show (matches + their parents)
  matchingItems.forEach(item => {
    itemsToShow.add(item);
    
    let current = item;
    while (current) {
      const parentChildren = current.closest('.tree-group-children');
      if (parentChildren) {
        const parentGroup = parentChildren.previousElementSibling;
        if (parentGroup && parentGroup.classList.contains('tree-item')) {
          itemsToShow.add(parentGroup);
          current = parentGroup;
        } else {
          break;
        }
      } else {
        break;
      }
    }
  });
  
  // Third pass: hide non-matching items, show matching items and parents
  allItems.forEach(item => {
    if (itemsToShow.has(item)) {
      item.classList.remove('search-hidden');
    } else {
      item.classList.add('search-hidden');
    }
  });
  
  // Fourth pass: visually expand parent groups of matches using search-only classes.
  // The real expanded/collapsed state is NOT modified — it was captured above
  // and will be restored when the search is cleared.
  allChildren.forEach(child => {
    const parentGroup = child.previousElementSibling;
    if (parentGroup && itemsToShow.has(parentGroup)) {
      child.classList.add('search-expanded');
      // Make the toggle arrow, and with it the folder icon, show "open"
      // during search. The row's `expanded` class is the selected look and
      // is left alone: adding it here made every folder above a match look
      // selected.
      const toggle = parentGroup.querySelector('.tree-toggle');
      if (toggle) toggle.classList.remove('collapsed');
    } else if (!child.classList.contains('expanded')) {
      child.classList.remove('search-expanded');
    }
  });

  // notify subscribers (background expansion, telemetry, etc.)
  try { EventBus.emit('search:changed', { term: searchTerm }); } catch (e) { kvotWarn('filterTree emit failed', e); }
}

// ---- Search-aware lazy expansion helpers --------------------------------
if (!window._searchExpansionState) window._searchExpansionState = { lastTerm: null, inProgress: false };

/**
 * How many matches a search finds in each file, so as to load the folders
 * they are in (rb-init.js, on 'search:changed'). A match in a folder not yet
 * loaded costs that folder's load, so this bounds the work a broad term can
 * start; matches past it are shown once their folders are opened. 200 shows
 * all 94 of a results file's C-14*org items, where 50 showed half.
 */
const SEARCH_LOAD_LIMIT = 200;

/**
 * Async, non-blocking search for matching paths inside an HDF5 file.
 * Traverses groups with periodic yields to avoid freezing the UI.
 * Returns up to `limit` matching full paths.
 *
 * A path matches when its own name matches `regex`, as the tree's filter
 * matches a name search; given `pathRegex`, also when the whole path matches
 * that, as the filter matches a path search. A name search's term tried on
 * whole paths too spent the limit on items the filter then hid: everything
 * below a match, and every name under a group whose name held the letters.
 * 'Pu*9' took I-129 below input_data for one, and in a results file 46 of
 * the 50 paths the limit then allowed were of that kind, so 5 of 49 Pu-239
 * items were shown.
 *
 * @param {Object} fileNode - The file (or group) to search from
 * @param {RegExp} regex - Tried on each item's own name
 * @param {number} [limit=SEARCH_LOAD_LIMIT]
 * @param {RegExp|null} [pathRegex=null] - Tried on each item's full path
 * @returns {Promise<string[]>}
 */
async function asyncFindMatchingPaths(fileNode, regex, limit = SEARCH_LOAD_LIMIT, pathRegex = null) {
  const matches = [];
  const hit = (key, path) => regex.test(key) || (pathRegex !== null && pathRegex.test(path));
  // A lazy file has every path already, and its groups need not be fetched
  // to be searched (rb-lazy.js).
  const lazy = lazyStateOf(fileNode);
  if (lazy) {
    for (const path of lazy.paths) {
      const key = path.slice(path.lastIndexOf('/') + 1);
      if (hit(key, path)) {
        matches.push(path);
        if (matches.length >= limit) break;
      }
    }
    return matches;
  }
  const stack = [{ node: fileNode, prefix: '' }];
  let processed = 0;

  while (stack.length && matches.length < limit) {
    const { node, prefix } = stack.pop();
    let keys = [];
    try { keys = FileService.keys(node); } catch (e) { continue; }

    for (const key of keys) {
      const path = prefix ? `${prefix}/${key}` : `/${key}`;
      if (hit(key, path)) {
        matches.push(path);
        if (matches.length >= limit) break;
      }

      try {
        const child = node.get ? node.get(key) : null;
        if (child && String(child.type).toLowerCase() === 'group') {
          stack.push({ node: child, prefix: path });
        }
      } catch (e) { ignoreFailure('asyncFindMatchingPaths', e); }

      if (++processed % 200 === 0) await new Promise(r => setTimeout(r, 0));
    }
  }
  return matches;
}

/**
 * Ensure all ancestor groups for `targetPath` are expanded and loaded.
 * Loads lazy placeholders top-down using `loadGroupChildren()`.
 */
async function expandAndLoadPath(fileKey, targetPath) {
  const tree = document.getElementById('tree');
  const parts = targetPath.split('/').filter(Boolean);
  let cur = '';

  for (let i = 0; i < parts.length; i++) {
    cur += '/' + parts[i];
    const groupItem = findTreeItem(cur, { fileKey, allowMissingFile: true, extra: '.group', root: tree });
    if (!groupItem) break; // cannot proceed if ancestor DOM node missing

    const childrenDiv = groupItem.nextElementSibling;
    if (childrenDiv && childrenDiv.getAttribute && childrenDiv.getAttribute('data-lazy') === 'true' && childrenDiv.getAttribute('data-loaded') !== 'true') {
      await loadGroupChildren(groupItem, cur);
      await new Promise(r => setTimeout(r, 0));
    }
  }
}

// Search-aware expansion is now handled via EventBus ('search:changed')
// — the legacy IIFE wrapper was removed in favor of a decoupled handler.

