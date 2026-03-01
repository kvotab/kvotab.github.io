/* ==========================================================================
   12. SEARCH FUNCTIONALITY
   ========================================================================== */

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
 * We treat terms containing '/', '.' or whitespace as path searches.
 * @param {string} term
 * @returns {boolean}
 */
function isPathSearchTerm(term) {
  return /[\/\.\s]/.test(String(term));
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
 */
function labelSegmentFromPathTerm(term) {
  const parts = normalizePathSearchTerm(term).split('/').filter(Boolean);
  return parts.length ? parts[parts.length - 1] : term;
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
  
  // Clear search - show everything, remove highlights
  if (!searchTerm.trim()) {
    allItems.forEach(item => {
      item.classList.remove('search-hidden', 'search-match');
      const label = item.querySelector('.tree-label');
      if (label) {
        const originalText = label.textContent;
        label.innerHTML = escapeHtml(originalText);
      }
    });
    
    allChildren.forEach(child => {
      child.classList.remove('search-expanded');
      const parentGroup = child.previousElementSibling;
      if (parentGroup && parentGroup.classList.contains('expanded')) {
        child.classList.add('expanded');
      } else {
        child.classList.remove('expanded');
      }
    });
    
    return;
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

    const text = label.textContent || '';
    let matches = regexLabel.test(text);

    // If user typed a path-style query (contains /, . or space), also test the
    // element's `data-path` attribute (full HDF5 path) using a normalized regex.
    if (!matches && isPathSearch) {
      const pathAttr = item.getAttribute('data-path') || '';
      if (pathRegex && pathRegex.test(pathAttr)) matches = true;
    }

    if (matches) {
      matchingItems.add(item);
      item.classList.add('search-match');
      // Highlight only the final name in the label when doing path searches
      const labelSearch = isPathSearch ? labelSegmentFromPathTerm(searchTerm) : searchTerm;
      label.innerHTML = highlightText(text, labelSearch);
    } else {
      item.classList.remove('search-match');
      label.innerHTML = escapeHtml(text);
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
  
  // Fourth pass: expand parent groups of matches
  allChildren.forEach(child => {
    const parentGroup = child.previousElementSibling;
    if (parentGroup && itemsToShow.has(parentGroup)) {
      child.classList.add('search-expanded');
      if (parentGroup) {
        const toggle = parentGroup.querySelector('.tree-toggle');
        if (toggle) {
          toggle.classList.remove('collapsed');
        }
        parentGroup.classList.add('expanded');
      }
    } else if (!child.classList.contains('expanded')) {
      child.classList.remove('search-expanded');
    }
  });

  // notify subscribers (background expansion, telemetry, etc.)
  try { EventBus.emit('search:changed', { term: searchTerm }); } catch (e) { console.warn('filterTree emit failed', e); }
}

// ---- Search-aware lazy expansion helpers --------------------------------
if (!window._searchExpansionState) window._searchExpansionState = { lastTerm: null, inProgress: false };

/**
 * Async, non-blocking search for matching paths inside an HDF5 file.
 * Traverses groups with periodic yields to avoid freezing the UI.
 * Returns up to `limit` matching full paths.
 */
async function asyncFindMatchingPaths(fileNode, regex, limit = 50) {
  const matches = [];
  const stack = [{ node: fileNode, prefix: '' }];
  let processed = 0;

  while (stack.length && matches.length < limit) {
    const { node, prefix } = stack.pop();
    let keys = [];
    try { keys = FileService.keys(node); } catch (e) { continue; }

    for (const key of keys) {
      const path = prefix ? `${prefix}/${key}` : `/${key}`;
      if (regex.test(key) || regex.test(path)) {
        matches.push(path);
        if (matches.length >= limit) break;
      }

      try {
        const child = node.get ? node.get(key) : null;
        if (child && String(child.type).toLowerCase() === 'group') {
          stack.push({ node: child, prefix: path });
        }
      } catch (e) { /* ignore unreadable nodes */ }

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
    const groupItems = Array.from(tree.querySelectorAll('.tree-item.group'));
    const groupItem = groupItems.find(el => el.getAttribute('data-path') === cur && (el.getAttribute('data-file') === fileKey || !el.getAttribute('data-file')));
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

