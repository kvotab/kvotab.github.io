/* ==========================================================================
   2. UTILITY FUNCTIONS
   ========================================================================== */

/**
 * Wait for h5wasm library to be loaded and ready
 */
async function waitForH5Wasm() {
  let attempts = 0;
  while (!window.h5wasm && attempts < 50) {
    await new Promise(r => setTimeout(r, 100));
    attempts++;
  }
  if (!window.h5wasm) throw new Error('h5wasm failed to load');
  if (window.h5wasm.ready instanceof Promise) await window.h5wasm.ready;
  return window.h5wasm;
}

// Install a lightweight console filter to reduce noisy h5wasm/HDF5 diagnostic
// messages that are benign (e.g. "HDF5-DIAG", "Object not found").
// Disable by setting `window.SUPPRESS_H5WASM_DIAGNOSTICS = false` in the console.
(function installH5WasmDiagFilter(){
  if (window.SUPPRESS_H5WASM_DIAGNOSTICS === false) return;
  // default to enabled
  window.SUPPRESS_H5WASM_DIAGNOSTICS = true;
  const origError = console.error.bind(console);
  const origWarn = console.warn.bind(console);

  function looksLikeH5Diag(args) {
    try {
      const txt = args.map(a => (typeof a === 'string' ? a : (a && a.message) ? a.message : String(a))).join(' ');
      if (!txt) return false;
      // match the common HDF5 diagnostic signatures we saw in the console
      if (!/HDF5-DIAG|Object not found|minor:\s*Object not found/i.test(txt)) return false;
      // also prefer messages originating from h5wasm (best-effort check)
      return /h5wasm(\.min)?\.js|h5wasm/i.test(txt);
    } catch (e) {
      return false;
    }
  }

  console.error = function(...args) {
    if (looksLikeH5Diag(args)) return;
    origError(...args);
  };
  console.warn = function(...args) {
    if (looksLikeH5Diag(args)) return;
    origWarn(...args);
  };

  try { console.debug('H5Wasm diagnostic filter enabled — SUPPRESS_H5WASM_DIAGNOSTICS = true'); } catch(e){}
})();

// Small FileService wrapper for h5wasm File objects. Use FileService.get(file, path),
// FileService.keys(file) and FileService.attrs(node) to access HDF5 content safely.
window.FileService = {
  get(file, path) {
    try { if (!file) return null; return file.get(path); } catch (e) { if (window.SUPPRESS_H5WASM_DIAGNOSTICS) return null; console.warn('FileService.get error:', e && e.message ? e.message : e, path); return null; }
  },
  keys(file) {
    try { if (!file || typeof file.keys !== 'function') return []; return Array.from(file.keys()).sort(); } catch (e) { return []; }
  },
  attrs(node) {
    const out = {};
    try {
      if (!node || !node.attrs) return out;
      for (const name in node.attrs) {
        try { const a = node.attrs[name]; out[name] = (a && typeof a === 'object' && 'value' in a) ? a.value : a; } catch (err) { out[name] = `(unreadable: ${err.message})`; }
      }
    } catch (e) {}
    return out;
  }
};

/* ==========================================================================
   2.0a CHART LOADING OVERLAY HELPERS
   ========================================================================== */

/**
 * Show or create the loading overlay on the chart container.
 * Centralises the duplicated loading-div creation that was previously
 * inlined in createPlotlyChart, createMultiDatasetChart,
 * createRadionuclidesChart, and createPdfHistogram.
 *
 * @param {HTMLElement} container - The #plotlyChartContainer element
 */
function showChartLoading(container) {
  if (!container) return;
  container.style.display = '';
  container.classList.add('visible');
  let loadingDiv = container.querySelector('.plotly-loading');
  if (!loadingDiv) {
    loadingDiv = document.createElement('div');
    loadingDiv.className = 'plotly-loading';
    loadingDiv.innerHTML = '<span class="spinner"></span> Loading...';
    // Position is determined by the CSS class; add fallback inline
    // styles only for the properties that the CSS already covers so
    // older cached CSS still works.
    loadingDiv.style.position = 'absolute';
    loadingDiv.style.top = '50%';
    loadingDiv.style.left = '50%';
    loadingDiv.style.transform = 'translate(-50%, -50%)';
    loadingDiv.style.zIndex = '10';
    loadingDiv.style.background = 'rgba(255,255,255,0.8)';
    loadingDiv.style.padding = '16px 32px';
    loadingDiv.style.borderRadius = '8px';
    loadingDiv.style.fontSize = '1.2em';
    loadingDiv.style.boxShadow = '0 2px 8px rgba(0,0,0,0.15)';
    container.appendChild(loadingDiv);
  } else {
    loadingDiv.style.display = '';
  }
}

/**
 * Hide the loading overlay on the chart container.
 * @param {HTMLElement} container - The #plotlyChartContainer element
 */
function hideChartLoading(container) {
  if (!container) return;
  const loadingDiv = container.querySelector('.plotly-loading');
  if (loadingDiv) loadingDiv.style.display = 'none';
}

/* ==========================================================================
   2.0b ATTRIBUTE READ HELPER
   ========================================================================== */

/**
 * Read a single attribute value from an h5wasm node by name.
 * Handles the quirk where node.attrs[name] may be either a raw value
 * or an object with a `.value` property.
 *
 * @param {Object} node - h5wasm node (Dataset/Group) with attrs
 * @param {string} name - Attribute name
 * @returns {*} Attribute value, or undefined if not found / unreadable
 */
function getAttr(node, name) {
  try {
    if (!node || !node.attrs) return undefined;
    const attrObj = node.attrs[name];
    if (attrObj === undefined || attrObj === null) return undefined;
    return (attrObj && typeof attrObj === 'object' && 'value' in attrObj) ? attrObj.value : attrObj;
  } catch (e) {
    return undefined;
  }
}

/**
 * Read all non-internal attributes from a node into a plain object.
 * Filters out attribute names starting with '_'.
 *
 * @param {Object} node - h5wasm node (Dataset/Group) with attrs
 * @returns {Object.<string, *>} Map of attribute name to value
 */
function getAllAttrs(node) {
  const out = {};
  try {
    if (!node || !node.attrs || typeof node.attrs !== 'object') return out;
    for (const attrName in node.attrs) {
      if (attrName.startsWith('_')) continue;
      try {
        const attrObj = node.attrs[attrName];
        out[attrName] = (attrObj && typeof attrObj === 'object' && 'value' in attrObj) ? attrObj.value : attrObj;
      } catch (err) {
        out[attrName] = `(unreadable: ${err && err.message ? err.message : 'error'})`;
      }
    }
  } catch (e) {}
  return out;
}

/* ==========================================================================
   2.0c STALE FILE REFERENCE GUARD
   ========================================================================== */

/**
 * Get a loaded file object, or null if the reference is stale / missing.
 * Automatically cleans up stale entries from the global maps.
 *
 * @param {string} fileKey - Filename key in loadedFiles
 * @returns {Object|null} The h5wasm File object, or null
 */
function getFileOrNull(fileKey) {
  const file = loadedFiles[fileKey];
  if (!file) return null;
  try {
    // Quick sanity check — attempt to access root keys
    if (typeof file.keys === 'function') file.keys();
    return file;
  } catch (e) {
    console.warn(`Stale file reference for ${fileKey}, removing`);
    delete loadedFiles[fileKey];
    delete fileStates[fileKey];
    delete loadedFileBuffers[fileKey];
    fileOrder = fileOrder.filter(k => k !== fileKey);
    return null;
  }
}

/**
 * Simple EventBus (pub/sub) for decoupling UI actions.
 * - synchronous delivery to preserve existing behavior expectations
 * - API: EventBus.on(name, fn), .off(name, fn), .emit(name, payload), .once(name, fn)
 */
window.EventBus = (function() {
  const _handlers = Object.create(null);
  return {
    on(name, fn) {
      if (!name || typeof fn !== 'function') return;
      (_handlers[name] = _handlers[name] || []).push(fn);
    },
    off(name, fn) {
      if (!name) return;
      if (!fn) { delete _handlers[name]; return; }
      const arr = _handlers[name];
      if (!arr) return;
      const idx = arr.indexOf(fn);
      if (idx !== -1) arr.splice(idx, 1);
    },
    once(name, fn) {
      const wrapper = function(payload) { fn(payload); EventBus.off(name, wrapper); };
      EventBus.on(name, wrapper);
    },
    emit(name, payload) {
      const arr = _handlers[name];
      if (!arr || !arr.length) return;
      // synchronous delivery
      for (let i = 0; i < arr.length; i++) {
        try { arr[i](payload); } catch (e) { console.error('EventBus handler error for', name, e); }
      }
    }
  };
})();



/**
 * Escape HTML special characters for safe rendering
 */
function escapeHtml(text) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return String(text).replace(/[&<>"']/g, m => map[m]);
}

/**
 * Detect if an HDF5 path is a soft link, external link, or broken soft link.
 * @param {Object} group - h5wasm Group or File object
 * @param {string} path - Absolute HDF5 path
 * @param {Object} [obj] - The object returned by group.get(key), if already fetched
 * @returns {Object|null} Link info or null if not a link
 */
function getLinkInfo(group, path, obj) {
  try {
    // don't treat the root "/" as a link
    if (!path || path === '/') return null;

    // explicit link object types first
    if (obj && String(obj.type) === 'BrokenSoftLink') {
      // normalize target to string when possible
      const t = obj.target;
      const targetStr = (typeof t === 'string') ? t
                        : (t instanceof Uint8Array ? new TextDecoder().decode(t) : (t?.toString?.() ?? '?'));
      return { type: 'broken', target: targetStr };
    }
    if (obj && String(obj.type) === 'ExternalLink') {
      return { type: 'external', filename: obj.filename || '?', obj_path: obj.obj_path || '?' };
    }

    // If the caller already provided `obj` (group.get(name)), avoid calling
    // the potentially noisy `group.get_link()` lookup — h5wasm may log
    // "Object not found" for non-link names. Only attempt get_link when
    // `obj` is not available.
    if (!obj && typeof group.get_link === 'function') {
      const localName = String(path).split('/').pop();
      try {
        const softTarget = group.get_link(localName);
        if (softTarget) {
          if (typeof softTarget === 'string') return { type: 'soft', target: softTarget };
          if (softTarget && typeof softTarget === 'object') {
            if (typeof softTarget.target === 'string') return { type: 'soft', target: softTarget.target };
            if (softTarget instanceof Uint8Array) {
              try { return { type: 'soft', target: new TextDecoder().decode(softTarget) }; } catch (e) {}
            }
          }
        }
      } catch (e) {
        // Swallow internal errors from get_link to avoid noisy console output
      }
    }
  } catch (e) { /* not a link / ignore noisy return values */ }
  return null;
}

/**
 * Build a small link badge element for the tree view.
 * @param {Object} linkInfo - Link info from getLinkInfo()
 * @returns {HTMLElement|null} span element or null when no badge
 */
function buildLinkBadge(linkInfo) {
  if (!linkInfo) return null;
  let tooltip, cls;
  if (linkInfo.type === 'broken') {
    tooltip = 'Broken link → ' + linkInfo.target;
    cls = 'broken';
  } else if (linkInfo.type === 'external') {
    tooltip = 'External → ' + linkInfo.filename + ':' + linkInfo.obj_path;
    cls = 'external';
  } else {
    tooltip = 'Link → ' + linkInfo.target;
    cls = 'soft';
  }

  const span = document.createElement('span');
  span.className = 'link-badge ' + cls;
  span.title = tooltip;
  // static SVG icon (safe, not user-provided)
  span.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>';
  return span;
}

/* ==========================================================================
   PDF SAMPLING ENGINE
   Mirrors the Python Distribution class from samp_util.py.
   Supports: uniform, triangular, dtriangular, normal, exponential,
   loguniform, logtriangular, logdtriangular, lognormal, raw/empirical.
   ========================================================================== */




/* DIST_INV moved to resources/js/pdf-sampler.js (use PDFSampler internally) */

/**
 * Generate n random samples from a PDF specification object.
 * Mirrors Python's Distribution(pdf).rnd() from samp_util.py.
 *
 * @param {Object} pdf - PDF spec, e.g. {type:'normal', mean:5, std:1}
 * @param {number} [n=1000] - Number of samples
 * @returns {Float64Array|null} Array of samples, or null if type unknown
 */
/* Generate PDF samples (delegates to PDFSampler) */
function generatePdfSamples(pdf, n = 1000) { return window.PDFSampler.generatePdfSamples(pdf, n); }

/**
 * Build a human-readable label for a PDF spec.
 * @param {Object} pdf
 * @returns {string}
 */

/**
 * Extract histogram entries from a dataset node that has a 'pdf' attribute.
 * Ensures all returned sample arrays and deterministic values are plain Numbers
 * (converts BigInt -> Number) so Plotly / math ops won't throw.
 *
 * @param {Object} node  - HDF5 dataset node
 * @param {Object} attrs - Already-extracted attribute dict (must contain attrs.pdf)
 * @param {string} label - Human-readable label prefix for this dataset
 * @returns {Array|null}
 */
function collectPdfEntries(node, attrs, label) {
  if (!attrs.pdf) return null;
  try {
    let pdfRaw = attrs.pdf;
    if (typeof pdfRaw === 'string') pdfRaw = JSON.parse(pdfRaw);



    const isLookupTable = Array.isArray(pdfRaw);
    const indexAttr = attrs.index;

    if (isLookupTable && indexAttr) {
      const indexLabels = Array.isArray(indexAttr) ? indexAttr : Array.from(indexAttr);
      const entries = [];
      for (let i = 0; i < pdfRaw.length; i++) {
        const spec = pdfRaw[i];
        if (!spec) {
          try {
            let rawData = typeof node.value !== 'undefined' ? node.value : (typeof node.toArray === 'function' ? node.toArray() : undefined);
            if (rawData !== undefined) {
              const arr = Array.isArray(rawData) ? rawData : Array.from(rawData);
              entries.push({ label: label + ' – ' + String(indexLabels[i] ?? i), samples: [PDFSampler.toNumber(arr[i])], spec: null, deterministicValue: null });
            }
          } catch (_) {}
          continue;
        }

        if (spec.type && spec.type.toLowerCase() === 'raw') {
          try {
            let rawData = typeof node.value !== 'undefined' ? node.value : (typeof node.toArray === 'function' ? node.toArray() : undefined);
            if (rawData !== undefined) {
              const flat = Array.isArray(rawData) ? rawData : Array.from(rawData);
              const nCols = pdfRaw.length, nRows = Math.floor(flat.length / nCols);
              const shift = spec.include_deterministic ? 1 : 0;
              const detVal = spec.include_deterministic && nRows > 0 ? PDFSampler.toNumber(flat[0 * nCols + i]) : null;
              const col = [];
              for (let r = shift; r < nRows; r++) col.push(PDFSampler.toNumber(flat[r * nCols + i]));
              entries.push({ label: label + ' – ' + String(indexLabels[i] ?? i), samples: col, spec, deterministicValue: detVal });
            }
          } catch (_) {}
        } else {
          let detVal = null;
          try {
            let rawData = typeof node.value !== 'undefined' ? node.value : (typeof node.toArray === 'function' ? node.toArray() : undefined);
            if (rawData !== undefined) {
              const flat = Array.isArray(rawData) ? rawData : Array.from(rawData);
              if (flat.length >= pdfRaw.length) detVal = PDFSampler.toNumber(flat[i]);
            }
          } catch (_) {}
          const samples = generatePdfSamples(spec, 1000);
          if (samples) {
            entries.push({ label: label + ' – ' + String(indexLabels[i] ?? i), samples: PDFSampler.normalizeDataArray(samples), spec, deterministicValue: isFinite(detVal) ? detVal : null });
          }
        }
      }
      return entries.length > 0 ? entries : null;
    } else if (!isLookupTable && pdfRaw.type) {
      if (pdfRaw.type.toLowerCase() === 'raw') {
        try {
          let rawData = typeof node.value !== 'undefined' ? node.value : (typeof node.toArray === 'function' ? node.toArray() : undefined);
          if (rawData !== undefined) {
            const flat = Array.isArray(rawData) ? rawData : Array.from(rawData);
            const shift = pdfRaw.include_deterministic ? 1 : 0;
            const detVal = pdfRaw.include_deterministic && flat.length > 0 ? PDFSampler.toNumber(flat[0]) : null;
            return [{ label, samples: flat.slice(shift).map(PDFSampler.toNumber), spec: pdfRaw, deterministicValue: detVal }];
          }
        } catch (_) {}
      } else {
        let detVal = null;
        try {
          let rawData = typeof node.value !== 'undefined' ? node.value : (typeof node.toArray === 'function' ? node.toArray() : undefined);
          if (rawData !== undefined) {
            if (typeof rawData === 'number') detVal = rawData;
            else if (rawData && rawData.length !== undefined && rawData.length > 0) detVal = PDFSampler.toNumber(rawData[0]);
          }
        } catch (_) {}
        const samples = generatePdfSamples(pdfRaw, 1000);
        if (samples) {
          return [{ label, samples: Array.from(samples).map(PDFSampler.toNumber), spec: pdfRaw, deterministicValue: isFinite(detVal) ? detVal : null }];
        }
      }
    }
  } catch (e) {
    console.warn('collectPdfEntries error:', e.message);
  }
  return null;
}

/**
 * Compute analytical PDF curve points for a given distribution spec.
 * Accounts for truncation (trmin/trmax/pmin/pmax) and shift.
 * @param {Object} spec - PDF specification object
 * @param {number} [nPoints=200] - Number of points to evaluate
 * @returns {{x:number[], y:number[]}|null} Points for the line overlay
 */
/* Compute PDF overlay (delegates to PDFSampler) */
function computePdfOverlay(spec, nPoints = 200) { return window.PDFSampler.computePdfOverlay(spec, nPoints); }

/**
 * Escape value for CSV export (handle commas, quotes, newlines)
 */
function escapeCSV(value) {
  if (value === null || value === undefined) {
    return '';
  }
  
  const str = String(value);
  
  if (str.includes(',') || str.includes('"') || str.includes('\n') || str.includes('\r')) {
    return '"' + str.replace(/"/g, '""') + '"';
  }
  
  return str;
}

/**
 * Format HDF5 data type into human-readable string
 */
function formatDataType(dtype) {
  if (!dtype) return 'unknown';
  
  let name = '';
  
  if (typeof dtype === 'object' && dtype.name) {
    name = dtype.name;
  } else if (typeof dtype === 'string') {
    name = dtype;
  } else {
    return String(dtype);
  }
  
  const typeMap = {
    'i': 'Integer', 'u': 'Unsigned Integer', 'f': 'Float', 'c': 'Complex',
    'q': 'Integer', 'Q': 'Unsigned Integer',
    'S': 'String (fixed)', 'U': 'Unicode String', 'V': 'Void/Compound',
    'O': 'Object Reference', 'b': 'Boolean', 't': 'Time', 'm': 'Timedelta',
    'M': 'Datetime', 'a': 'Bytes', 'A': 'Any', 'd': 'Float'
  };
  
  name = name.replace(/^[<>|=]/, '');
  
  const match = name.match(/^([a-zA-Z])(\d+)$/);
  if (match) {
    const [, type, bytes] = match;
    const baseType = typeMap[type] || type;
    const bitSize = parseInt(bytes) * 8;
    return `${baseType} (${bitSize}-bit)`;
  }
  
  const singleTypeMatch = name.match(/^([a-zA-Z])$/);
  if (singleTypeMatch) {
    const type = singleTypeMatch[1];
    return typeMap[type] || name;
  }
  
  return name;
}

/**
 * Check if a value represents a truthy attribute (handles various formats)
 * @param {*} value - The value to check
 * @returns {boolean} True if the value is truthy
 */
function isTruthyAttribute(value) {
  return value === true || value === 1 || value === 'TRUE' || value === 'True' || value === 'true';
}

/**
 * Check if a dataset has the 'probabilistic' attribute set to true
 * @param {Object} dataset - HDF5 dataset with attrs
 * @returns {boolean} True if probabilistic
 */
function checkIsProbabilistic(dataset) {
  const val = getAttr(dataset, 'probabilistic');
  return val !== undefined && isTruthyAttribute(val);
}

/**
 * Compute mean values from probabilistic data array
 * @param {Array} yArray - Raw data array (may contain realizations)
 * @param {Array} timeData - Time data for reference length
 * @returns {Array} Array of mean values per timestep
 */
function computeProbabilisticMean(yArray, timeData) {
  if (Array.isArray(yArray[0])) {
    // Array of arrays: each timeSlice has multiple realizations
    return yArray.map(timeSlice => {
      if (Array.isArray(timeSlice)) {
        const sum = timeSlice.reduce((a, b) => a + PDFSampler.toNumber(b), 0);
        return sum / timeSlice.length;
      }
      return PDFSampler.toNumber(timeSlice);
    });
  } else if (yArray.length > timeData.length && yArray.length % timeData.length === 0) {
    // Flat array: realizations interleaved or sequential
    const numRealizations = Math.floor(yArray.length / timeData.length);
    const means = [];
    for (let t = 0; t < timeData.length; t++) {
      let sum = 0;
      for (let r = 0; r < numRealizations; r++) {
        sum += PDFSampler.toNumber(yArray[t * numRealizations + r]);
      }
      means.push(sum / numRealizations);
    }
    return means;
  }
  return yArray.map(PDFSampler.toNumber);
}

/**
 * Compute a compact diff label showing only the parts of secondName
 * that differ from firstName, with '...' replacing matching segments
 * longer than 3 characters. Short matching runs (1-3 chars) are kept.
 * Example: firstName='SFR_FSAR_CCP1.h5', secondName='SFR_PSAR_CCP33.h5'
 *          returns '...P...33...'
 *
 * @param {string} firstName - The primary/reference filename
 * @param {string} secondName - The secondary filename to diff
 * @returns {string} Compact diff string
 */
function filenameDiff(firstName, secondName) {
  // Strip .h5/.hdf5/.he5 extension for comparison
  const stripExt = s => s.replace(/\.(h5|hdf5|he5)$/i, '');
  const a = stripExt(firstName);
  const b = stripExt(secondName);
  
  // Build runs of same/diff segments
  const runs = []; // { same: bool, text: string (from b) }
  let i = 0;
  const len = Math.max(a.length, b.length);
  while (i < len) {
    const ca = i < a.length ? a[i] : '';
    const cb = i < b.length ? b[i] : '';
    const same = (ca === cb);
    let text = cb;
    let j = i + 1;
    while (j < len) {
      const na = j < a.length ? a[j] : '';
      const nb = j < b.length ? b[j] : '';
      if ((na === nb) !== same) break;
      text += nb;
      j++;
    }
    runs.push({ same, text });
    i = j;
  }
  
  // Build result: replace matching runs > 3 chars with '...'
  let result = '';
  for (const run of runs) {
    if (run.same) {
      result += run.text.length > 3 ? '...' : run.text;
    } else {
      result += run.text;
    }
  }
  
  // If result equals the stripped second name, files are identical
  if (result === b) return secondName;
  
  return result;
}

/**
 * Build a harmonized legend label for a dataset trace.
 *
 * Disambiguation rules:
 * 1. Start with the dataset leaf name.
 * 2. If other items in the selection share the same leaf name from a
 *    different HDF5 path, walk up the hierarchy and include the minimum
 *    number of trailing path segments needed to make each name unique.
 * 3. If multiple files are involved, append a compact file-diff suffix
 *    (via filenameDiff) so every file gets a short, distinguishing tag.
 *
 * @param {string} datasetName - Leaf name (path.split('/').pop())
 * @param {string} path        - Full HDF5 path to the dataset
 * @param {string} fileKey     - File key for this trace
 * @param {string[]} allPaths    - All HDF5 paths in the current selection
 * @param {string[]} allFileKeys - All file keys in the current selection
 * @returns {string} Harmonized legend label
 */
function buildTraceName(datasetName, path, fileKey, allPaths, allFileKeys) {
  let name = datasetName;

  // Path disambiguation – walk up the hierarchy until this path's trailing
  // segments are unique among all selected paths sharing the same leaf name.
  const uniquePaths = [...new Set(allPaths)];
  const sameLeaf = uniquePaths.filter(p => p !== path && p.split('/').pop() === datasetName);

  if (sameLeaf.length > 0) {
    const allSameLeaf = [path, ...sameLeaf];
    const allSegments = allSameLeaf.map(p => p.split('/').filter(Boolean));
    const thisSegments = path.split('/').filter(Boolean);
    const maxDepth = Math.max(...allSegments.map(s => s.length));

    let depth = 2; // start with parent + leaf
    while (depth <= maxDepth) {
      const thisSuffix = thisSegments.slice(-depth).join('/');
      const duplicates = allSegments.filter(segs => segs.slice(-depth).join('/') === thisSuffix);
      if (duplicates.length <= 1) break;
      depth++;
    }

    // Clamp to available depth
    depth = Math.min(depth, thisSegments.length);
    name = thisSegments.slice(-depth).join('/');
  }

  // File disambiguation – append compact diff when multiple files are shown
  const uniqueFiles = [...new Set(allFileKeys)];
  if (uniqueFiles.length > 1) {
    // Pick a reference that is *different* from the current file so the
    // diff highlights what is unique about this file.
    const ref = (fileKey === uniqueFiles[0]) ? uniqueFiles[1] : uniqueFiles[0];
    name += ' (' + filenameDiff(ref, fileKey) + ')';
  }

  return name;
}

/**
 * Get current axis scale values from UI
 * @returns {{xScale: string, yScale: string}}
 */
function getChartScales() {
  return {
    xScale: getScaleValue('x'),
    yScale: getScaleValue('y')
  };
}

/**
 * Capture the current Plotly axis state (ranges and autorange flags)
 * so it can be restored after a chart rebuild.
 * @returns {Object|null} Saved axis state, or null if no chart exists
 */
function captureAxisState() {
  const plotDiv = getElement('plotlyChart');
  if (!plotDiv || !plotDiv.layout) return null;
  const xaxis = plotDiv.layout.xaxis || {};
  const yaxis = plotDiv.layout.yaxis || {};
  return {
    xRange: xaxis.range ? [...xaxis.range] : null,
    yRange: yaxis.range ? [...yaxis.range] : null,
    xAutorange: xaxis.autorange,
    yAutorange: yaxis.autorange
  };
}

/**
 * Apply a previously captured axis state to a Plotly layout object.
 * Only overrides ranges when the user had manually zoomed/panned (autorange=false).
 * @param {Object} layout - Plotly layout to modify in-place
 * @param {Object} savedState - State from captureAxisState()
 */
function applyAxisState(layout, savedState) {
  if (!savedState) return;
  if (savedState.xRange && savedState.xAutorange === false) {
    layout.xaxis.range = savedState.xRange;
    layout.xaxis.autorange = false;
  }
  if (savedState.yRange && savedState.yAutorange === false) {
    layout.yaxis.range = savedState.yRange;
    layout.yaxis.autorange = false;
  }
}

/**
 * Create base layout configuration for Plotly charts
 * @param {Object} options - Layout options
 * @param {string} options.title - Chart title
 * @param {string} options.xAxisTitle - X axis title
 * @param {string} options.yAxisTitle - Y axis title
 * @param {string} [options.xScale='linear'] - X axis scale type
 * @param {string} [options.yScale='linear'] - Y axis scale type
 * @returns {Object} Plotly layout configuration
 */
function createBaseLayout({ title, xAxisTitle, yAxisTitle, xScale = 'linear', yScale = 'linear' }) {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  const textColor = isDark ? '#e8ddd0' : '#2d2416';
  const gridColor = isDark ? '#4a3f35' : '#e5ddd5';
  const bgColor = isDark ? '#2a221b' : '#ffffff';
  // use panel background for the page around the axes
  let panelBg = ''; 
  try {
    panelBg = getComputedStyle(document.documentElement).getPropertyValue('--color-panel-bg').trim();
  } catch (e) { panelBg = isDark ? '#2a221b' : '#faf8f6'; }
  if (!panelBg) panelBg = isDark ? '#2a221b' : '#faf8f6';

  return {
    title: {
      text: '',
      font: { size: 14, color: textColor },
      xanchor: 'left',
      x: 0
    },
    paper_bgcolor: panelBg,
    plot_bgcolor: bgColor,
    font: { color: textColor },
    xaxis: { 
      title: xAxisTitle,
      type: xScale,
      gridcolor: gridColor,
      zerolinecolor: gridColor,
      color: textColor
    },
    yaxis: { 
      title: yAxisTitle,
      type: yScale,
      gridcolor: gridColor,
      zerolinecolor: gridColor,
      color: textColor,
      rangemode: yScale === 'linear' ? 'tozero' : undefined,
      ...CHART_YAXIS_EXPONENT
    },
    hovermode: 'closest',
    showlegend: true,
    legend: { ...CHART_LEGEND_CONFIG, font: { color: textColor } },
    margin: CHART_MARGIN_WITH_LEGEND
  };
}

// ChartService: factories for traces and theme relayout helpers
window.ChartService = {
  createBaseLayout: function(opts) { return createBaseLayout(opts); },

  timeSeriesTrace({ x, y, name, line = {}, hovertemplate = undefined, showlegend = true, ...extra }) {
    const trace = { x, y, mode: 'lines', type: 'scatter', name, line, showlegend, ...extra };
    if (hovertemplate) trace.hovertemplate = hovertemplate;
    return trace;
  },

  histogramTrace({ samples, name = 'Samples', color, lineColor, opacity = 0.85, histnorm = 'probability density' }) {
    return {
      x: samples,
      type: 'histogram',
      histnorm,
      marker: { color, line: { color: lineColor, width: 1 } },
      opacity,
      name
    };
  },

  pdfOverlayTrace({ x, y, color, width = 2.5, name = 'PDF', showlegend = true }) {
    return { x, y, type: 'scatter', mode: 'lines', line: { color, width }, name, showlegend };
  },

  relayoutForTheme(isDark) {
    const textColor = isDark ? '#e8ddd0' : '#2d2416';
    const gridColor = isDark ? '#4a3f35' : '#e5ddd5';
    const bgColor  = isDark ? '#2a221b' : '#ffffff';
    let panelBg = '';
    try {
      panelBg = getComputedStyle(document.documentElement).getPropertyValue('--color-panel-bg').trim();
    } catch (e) { panelBg = isDark ? '#2a221b' : '#faf8f6'; }
    if (!panelBg) panelBg = isDark ? '#2a221b' : '#faf8f6';
    return {
      paper_bgcolor: panelBg,
      plot_bgcolor: bgColor,
      'font.color': textColor,
      'xaxis.gridcolor': gridColor,
      'xaxis.zerolinecolor': gridColor,
      'xaxis.color': textColor,
      'yaxis.gridcolor': gridColor,
      'yaxis.zerolinecolor': gridColor,
      'yaxis.color': textColor,
      'legend.font.color': textColor
    };
  }
};

// Update Plotly chart colours when theme changes
// Notify interested components when theme changes (decoupled via EventBus)
new MutationObserver((mutations) => {
  for (const m of mutations) {
    if (m.type === 'attributes' && m.attributeName === 'data-theme') {
      const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
      EventBus.emit('theme:changed', { isDark });
    }
  }
}).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

/**
 * Hide the chart container and clear chart data
 */
function hideChart() {
  const container = getElement('plotlyChartContainer');
  if (container) {
    container.classList.remove('visible');
    // Restore chart controls visibility (may have been hidden for PDF histograms)
    const controls = container.querySelector('.chart-controls');
    if (controls) controls.style.display = '';
  }
  currentChartData = null;
  currentPdfHistogram = false;
  currentPdfHistogramData = null;
  const histControls = document.getElementById('histControls');
  if (histControls) histControls.style.display = 'none';
}

/**
 * Hide or show the multi-select hint element depending on state.
 */
function updateMultiSelectHint() {
  const hint = document.getElementById('multiSelectHint');
  if (!hint) return;
  let hasData = false;
  const tree = document.getElementById('tree');
  if (tree) {
    // treat any tree-item as evidence of data; loading state will clear hint
    if (tree.querySelector('.tree-item')) hasData = true;
  }
  hint.style.display = (_showMultiSelectHint && hasData) ? '' : 'none';
}

/**
 * Permanently dismiss the multi-select hint (stored in localStorage).
 */
function dismissMultiSelectHint() {
  _showMultiSelectHint = false;
  try { localStorage.setItem('rb_showMultiSelectHint','0'); } catch(_) {}
  updateMultiSelectHint();
  updateHintToggleButton();
}

/**
 * Update visibility of the lamp button that can restore the tip.
 */
function updateHintToggleButton() {
  const btn = document.getElementById('showHintButton');
  if (!btn) return;
  // show when hint is dismissed but tree has data
  const tree = document.getElementById('tree');
  const hasData = tree && tree.querySelector('.tree-item');
  btn.style.display = (!_showMultiSelectHint && hasData) ? '' : 'none';
}

/**
 * Restore the multi-select hint and hide the lamp.
 */
function showMultiSelectHint() {
  _showMultiSelectHint = true;
  try { localStorage.removeItem('rb_showMultiSelectHint'); } catch(_) {}
  updateMultiSelectHint();
  updateHintToggleButton();
}

/**
 * Reset info panel to default message
 */
function resetInfoPanel() {
  const info = getElement('info');
  if (info) {
    info.innerHTML = INFO_PANEL_DEFAULT_MESSAGE;
  }
  const heading = getElement('datasetInfoHeading');
  if (heading) heading.style.display = 'none';
}

/**
 * Assign legendrank to traces so that in the legend they are grouped by
 * line width (thick first, thin second) and within each group sorted by
 * the maximum Y value in descending order.
 * @param {Array} traces - Array of Plotly trace objects
 */
function assignLegendRanks(traces) {
  // Classify traces into groups by line width (thick = first file, thin = secondary files)
  const thick = [];
  const thin = [];
  for (let i = 0; i < traces.length; i++) {
    const w = traces[i].line?.width || 2;
    const maxY = Math.max(...(traces[i].y || []).filter(v => v != null && isFinite(v)));
    const entry = { index: i, maxY: isFinite(maxY) ? maxY : 0 };
    if (w >= 2) {
      thick.push(entry);
    } else {
      thin.push(entry);
    }
  }
  // Sort each group by maxY descending
  thick.sort((a, b) => b.maxY - a.maxY);
  thin.sort((a, b) => b.maxY - a.maxY);
  // Assign legendrank: thick group first, then thin group
  let rank = 0;
  for (const entry of thick) {
    traces[entry.index].legendrank = rank++;
  }
  for (const entry of thin) {
    traces[entry.index].legendrank = rank++;
  }
}

/**
 * Render a Plotly chart with standard configuration
 * @param {Array} traces - Plotly trace data
 * @param {Object} layout - Plotly layout configuration
 * @param {string} path - Dataset path (for storing in currentChartData)
 */
function renderChart(traces, layout, path) {
  const container = getElement('plotlyChartContainer');
  const config = getPlotlyConfig('chart');
  
  // Restore chart controls (may have been hidden for PDF histograms)
  if (container) {
    const controls = container.querySelector('.chart-controls');
    if (controls) controls.style.display = '';
  }
  const histControls = document.getElementById('histControls');
  if (histControls) histControls.style.display = 'none';

  if (dynamicLegendEnabled) {
    assignLegendRanks(traces);
  }

  currentChartData = { traces, layout, path };
  if (container) {
    container.classList.add('visible');
  }
  
  Plotly.newPlot('plotlyChart', traces, layout, config).then(() => {
    setupDynamicLegend(getElement('plotlyChart'));
    refreshDynamicLegend();
    hideChartLoading(container);
  });
}

/**
 * Render a PDF histogram in the main chart area (#plotlyChart).
 * Handles both single-distribution and lookup-table (multi-index) cases.
 * @param {Object} data - pdfHistogramData object
 */
function createPdfHistogram(data) {
  // Ensure panelBg is defined for histogram layout
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  let panelBg = '';
  try {
    panelBg = getComputedStyle(document.documentElement).getPropertyValue('--color-panel-bg').trim();
  } catch (e) { panelBg = isDark ? '#2a221b' : '#faf8f6'; }
  if (!panelBg) panelBg = isDark ? '#2a221b' : '#faf8f6';
  const container = getElement('plotlyChartContainer');
  if (!container) return;

  // Store data globally for re-rendering on theme / log toggle
  currentPdfHistogramData = data;

  // Hide time-series controls, show histogram controls when applicable
  const controls = container.querySelector('.chart-controls');
  if (controls) controls.style.display = 'none';
  const histControls = document.getElementById('histControls');

  // Determine if all sample values are strictly positive (log10 is only meaningful then)
  let allPositive = true;
  if (data.type === 'single') {
    allPositive = data.samples.every(v => v > 0);
  } else if (data.type === 'lookup') {
    allPositive = data.entries.every(e => e.samples.every(v => v > 0));
  }

  // Always show the Data preview header when a histogram is rendered.
  // Show/hide only the Log10 checkbox based on positivity and clear it when hidden.
  if (histControls) {
    histControls.style.display = ''; // show Data preview area for any histogram
    const logLabel = document.getElementById('histLogLabel');
    const logCheckbox = document.getElementById('histLogScale');
    if (logLabel) logLabel.style.display = allPositive ? '' : 'none';
    if (!allPositive && logCheckbox) logCheckbox.checked = false;
  }
  

  const useLog = allPositive && document.getElementById('histLogScale') && document.getElementById('histLogScale').checked;

  // ...existing code...
  const textColor = isDark ? '#e8ddd0' : '#2d2416';
  const gridColor = isDark ? '#4a3f35' : '#e5ddd5';
  const bgColor  = isDark ? '#2a221b' : '#ffffff';
  const barColor  = isDark ? 'rgba(243,184,123,0.45)' : 'rgba(187,108,93,0.45)';
  const barLine   = isDark ? 'rgba(243,184,123,0.8)'  : 'rgba(187,108,93,0.8)';
  const pdfLineColor = isDark ? 'rgba(255,220,160,1)' : 'rgba(140,60,45,1)';
  const detColor  = isDark ? '#ff6b6b' : '#d63031';

  const palette = [
    { bar: isDark ? 'rgba(243,184,123,0.35)' : 'rgba(187,108,93,0.35)', line: isDark ? 'rgba(243,184,123,0.8)' : 'rgba(187,108,93,0.8)', pdf: isDark ? 'rgba(255,220,160,1)' : 'rgba(140,60,45,1)' },
    { bar: isDark ? 'rgba(123,198,243,0.35)' : 'rgba(65,131,196,0.35)',  line: isDark ? 'rgba(123,198,243,0.8)' : 'rgba(65,131,196,0.8)',  pdf: isDark ? 'rgba(160,220,255,1)' : 'rgba(30,90,160,1)' },
    { bar: isDark ? 'rgba(168,230,160,0.35)' : 'rgba(80,160,72,0.35)',   line: isDark ? 'rgba(168,230,160,0.8)' : 'rgba(80,160,72,0.8)',   pdf: isDark ? 'rgba(190,255,185,1)' : 'rgba(40,120,35,1)' },
    { bar: isDark ? 'rgba(230,168,230,0.35)' : 'rgba(170,80,170,0.35)',  line: isDark ? 'rgba(230,168,230,0.8)' : 'rgba(170,80,170,0.8)',  pdf: isDark ? 'rgba(250,200,250,1)' : 'rgba(130,40,130,1)' },
    { bar: isDark ? 'rgba(243,210,123,0.35)' : 'rgba(200,150,50,0.35)',  line: isDark ? 'rgba(243,210,123,0.8)' : 'rgba(200,150,50,0.8)',  pdf: isDark ? 'rgba(255,230,160,1)' : 'rgba(160,110,20,1)' },
    { bar: isDark ? 'rgba(243,150,150,0.35)' : 'rgba(200,80,80,0.35)',   line: isDark ? 'rgba(243,150,150,0.8)' : 'rgba(200,80,80,0.8)',   pdf: isDark ? 'rgba(255,185,185,1)' : 'rgba(160,40,40,1)' },
  ];

  /** Transform value into display-space (identity or log10) */
  const xform = useLog ? v => Math.log10(v) : v => v;

  let traces = [];
  let shapes = [];

  if (data.type === 'single') {
    const label = data.spec ? PDFSampler.pdfLabel(data.spec) : 'raw';

    // Histogram trace (probability density)
    traces.push(ChartService.histogramTrace({ samples: data.samples.map(xform), name: 'Samples', color: barColor, lineColor: barLine, opacity: 0.85 }));

    // Analytical PDF overlay line
    const overlay = data.spec ? computePdfOverlay(data.spec) : null;
    if (overlay) {
      if (useLog) {
        // Change of variable: f_log10(log10(x)) = f(x) · x · ln(10)
        const xLog = [], yLog = [];
        for (let k = 0; k < overlay.x.length; k++) {
          const xv = overlay.x[k];
          if (xv > 0) {
            xLog.push(Math.log10(xv));
            yLog.push(overlay.y[k] * xv * Math.LN10);
          }
        }
        traces.push(ChartService.pdfOverlayTrace({ x: xLog, y: yLog, color: pdfLineColor, width: 2.5, name: `PDF (${label})` }));
      } else {
        traces.push(ChartService.pdfOverlayTrace({ x: overlay.x, y: overlay.y, color: pdfLineColor, width: 2.5, name: `PDF (${label})` }));
      }
    }

    // Deterministic value vertical line
    if (data.deterministicValue !== null && data.deterministicValue !== undefined && isFinite(data.deterministicValue)) {
      const detX = xform(data.deterministicValue);
      shapes.push({
        type: 'line', x0: detX, x1: detX, y0: 0, y1: 1, yref: 'paper',
        line: { color: detColor, width: 2, dash: 'dashdot' },
      });
      traces.push({
        x: [detX], y: [0], type: 'scatter', mode: 'markers',
        marker: { color: detColor, size: 10, symbol: 'line-ns-open', line: { width: 2, color: detColor } },
        name: 'Deterministic (' + Number(data.deterministicValue.toPrecision(4)) + ')',
        showlegend: true,
      });
    }
  } else if (data.type === 'lookup') {
    data.entries.forEach((entry, i) => {
      const c = palette[i % palette.length];
      const pdfSuffix = entry.spec ? ' (' + PDFSampler.pdfLabel(entry.spec) + ')' : '';
      const label = (pdfSuffix && entry.label.includes(pdfSuffix)) ? entry.label : entry.label + pdfSuffix;

      traces.push(ChartService.histogramTrace({ samples: entry.samples.map(xform), name: label, color: c.bar, lineColor: c.line, opacity: 0.7 }));

      const overlay = entry.spec ? computePdfOverlay(entry.spec) : null;
      if (overlay) {
        if (useLog) {
          const xLog = [], yLog = [];
          for (let k = 0; k < overlay.x.length; k++) {
            const xv = overlay.x[k];
            if (xv > 0) { xLog.push(Math.log10(xv)); yLog.push(overlay.y[k] * xv * Math.LN10); }
          }
          traces.push(ChartService.pdfOverlayTrace({ x: xLog, y: yLog, color: c.pdf, width: 2, name: 'PDF ' + entry.label, showlegend: false }));
        } else {
          traces.push(ChartService.pdfOverlayTrace({ x: overlay.x, y: overlay.y, color: c.pdf, width: 2, name: 'PDF ' + entry.label, showlegend: false }));
        }
      }

      if (entry.deterministicValue !== null && entry.deterministicValue !== undefined && isFinite(entry.deterministicValue)) {
        const detX = xform(entry.deterministicValue);
        shapes.push({
          type: 'line', x0: detX, x1: detX, y0: 0, y1: 1, yref: 'paper',
          line: { color: c.line, width: 1.5, dash: 'dashdot' },
        });
      }
    });
  }


  const layout = {
    barmode: data.type === 'lookup' ? 'overlay' : undefined,
    paper_bgcolor: panelBg,
    plot_bgcolor: bgColor,
    font: { color: textColor },
    xaxis: {
      title: useLog ? 'log\u2081\u2080(Value)' : 'Value',
      gridcolor: gridColor,
      zerolinecolor: gridColor,
      color: textColor,
    },
    yaxis: {
      title: 'Probability Density',
      gridcolor: gridColor,
      zerolinecolor: gridColor,
      color: textColor,
      rangemode: 'tozero',
    },
    margin: { t: 20, r: 30, b: 60, l: 60 },
    showlegend: true,
    legend: { font: { color: textColor } },
    shapes: shapes,
  };

  const config = getPlotlyConfig('pdf_histogram');

  currentPdfHistogram = true;
  currentChartData = null;
  container.classList.add('visible');

  showChartLoading(container);
  Plotly.newPlot('plotlyChart', traces, layout, config).then(() => {
    hideChartLoading(container);
  });
}

/**
 * Toggle log\u2081\u2080 scale on the PDF histogram x-axis.
 * Re-renders the histogram from stored data.
 */
function toggleHistLog() {
  if (currentPdfHistogramData) {
    createPdfHistogram(currentPdfHistogramData);
  }
}


