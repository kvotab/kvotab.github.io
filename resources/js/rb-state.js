/* ==========================================================================
   1. GLOBAL STATE & CONFIGURATION
   ========================================================================== */

/**
 * @typedef {Object} FileState
 * @property {boolean} enabled - Whether the file is currently enabled for display
 */

/**
 * @typedef {Object} ChartData
 * @property {Array} traces - Plotly trace data
 * @property {Object} layout - Plotly layout configuration
 * @property {string} path - Dataset path being charted
 */

/** @type {Object.<string, Object>} Map of filename to HDF5 file objects */
let loadedFiles = {};
/**
 * Raw ArrayBuffer copies for each loaded file. Used when passing the file
 * into a Web Worker for heavy traversal (keeps main-thread File objects intact).
 */
let loadedFileBuffers = {};
/** @type {Object.<string, boolean>} Map of filename to enabled/disabled state */
let fileStates = {};
/** @type {string[]} Ordered list of filenames (determines tab order) */
let fileOrder = [];

// Worker used for heavy tree traversal / intersection
let treeWorker = null;
let treeWorkerH5Ready = false; // whether h5wasm inside the worker finished initializing
const _treeWorkerPending = {};

// Selection state
/** @type {string|null} Currently selected HDF5 path in the tree view */
let selectedDatasetPath = null;
/** @type {boolean} True if the selected path is a radionuclides group (for special charting) */
let selectedIsRadionuclidesGroup = false;
/** @type {{path: string, fileKey: string|null}[]} Array of selected datasets in multi-select mode (Ctrl+click) */
let selectedDatasets = [];
/** @type {boolean} True when user is selecting multiple datasets with Ctrl/Cmd key */
let multiSelectMode = false;
/** @type {string|null} File key of the tree node that was clicked (null = use all enabled files) */
let selectedFileKey = null;

// Chart state
/** @type {ChartData|null} Current chart data (traces, layout, path) for export/clipboard */
let currentChartData = null;
/** @type {boolean} True when the chart area is showing a PDF histogram (not a time-series chart) */
let currentPdfHistogram = false;
/** @type {Object|null} Stored PDF histogram data for re-rendering on theme/log change */
let currentPdfHistogramData = null;
/** @type {string|null} Filename of the first enabled file (determines tree structure source) */
let currentTreeFile = null;

// Dynamic legend state
/** @type {boolean} When true, legend updates to show only traces visible in current viewport */
let dynamicLegendEnabled = true;
// whether to display the multi-select hint; persisted to localStorage
let _showMultiSelectHint = true;

// Search state
/** @type {number|null} Timeout ID for debounced search input */
let searchTimeout = null;
/** @type {string} Current search/filter term applied to tree view */
let currentSearchTerm = '';

// Debounce and cancellation helpers for tab refresh / tree build
let _updateTabsDebounceTimer = null;
const UPDATE_TABS_DEBOUNCE_MS = 250;
// Tree refresh cancellation token/flag (incremented per refresh)
window._treeRefreshId = window._treeRefreshId || 0;
window._treeRefreshCancelled = false;

// Drag & drop state
/** @type {number} Counter for drag enter/leave events to handle nested elements */
let dragCounter = 0;


/* ==========================================================================
   1.1 CONSTANTS
   ========================================================================== */

/**
 * Default placeholder message shown in the info panel when no dataset is selected.
 * @constant {string}
 */
const INFO_PANEL_DEFAULT_MESSAGE = `
<div class="welcome-panel">
  <h2>📂 HDF5 Browser</h2>
  <p>An interactive browser for exploring and visualising HDF5 data files.</p>

  <div class="welcome-section">
    <h4>Getting Started</h4>
    <ol>
      <li><strong>Load files</strong> — drag &amp; drop <code>.h5</code> / <code>.hdf5</code> files onto the page, click <em>+ Add Files</em>, or use <em>🔗 URL</em> to fetch from a remote server.</li>
      <li><strong>Browse</strong> — expand groups in the tree on the left to explore the file structure.</li>
      <li><strong>Select</strong> — click a dataset to view its attributes and chart.</li>
    </ol>
  </div>

  <div class="welcome-section">
    <h4>Tips</h4>
    <ul>
      <li><kbd>Ctrl</kbd>-click (<kbd>⌘</kbd> on Mac) datasets to <strong>compare multiple</strong> in one chart.</li>
      <li>Use the <strong>search bar</strong> to filter the tree — supports <code>*</code> wildcards and <code>/</code> full-path search.</li>
      <li>Load <strong>multiple files</strong> and use the ∩ (intersect) or ∪ (union) toggle to combine trees.</li>
      <li>Toggle <strong>Dynamic Legend</strong> to auto-hide traces outside the current view.</li>
      <li>Right-click the chart to <strong>copy</strong> or <strong>download</strong> data as CSV / Excel.</li>
    </ul>
  </div>

  <div class="welcome-section">
    <h4>Chart Controls</h4>
    <ul>
      <li><strong>Scale selectors</strong> — switch axes between linear and log scales.</li>
      <li><strong>Show Total</strong> — for radionuclide groups, overlay a summed trace.</li>
      <li><strong>Show Ratio</strong> — when two files are loaded, display max-value ratios per isotope.</li>
      <li><strong>Preset views</strong> — quickly zoom to common time ranges.</li>
    </ul>
  </div>
</div>
`;

/**
 * Standard legend positioning for Plotly charts.
 * Places legend to the right of the chart area.
 * @constant {Object}
 */
const CHART_LEGEND_CONFIG = {
  x: 1.02,      // Slightly right of chart area
  y: 1,         // Top aligned
  xanchor: 'left',
  yanchor: 'top'
};

/**
 * Y-axis exponent display settings for scientific notation.
 * Shows all exponents in power format (e.g., 10^6 instead of 1e6).
 * @constant {Object}
 */
const CHART_YAXIS_EXPONENT = {
  showexponent: 'all',
  exponentformat: 'power'
};

/**
 * Chart margins with extra right padding for legend.
 * @constant {Object}
 */
const CHART_MARGIN_WITH_LEGEND = { t: 25, r: 150,  b: 60 };


/* ==========================================================================
   1.2 DOM ELEMENT HELPERS
   ========================================================================== */

/**
 * Cached DOM element references (initialized on DOMContentLoaded)
 * @type {Object.<string, HTMLElement>}
 */
const DOM = {};

/**
 * Initialize cached DOM element references
 * Call once after DOM is ready
 */
function initDOMReferences() {
  DOM.plotlyChart = document.getElementById('plotlyChart');
  DOM.plotlyChartContainer = document.getElementById('plotlyChartContainer');
  DOM.info = document.getElementById('info');
  DOM.tree = document.getElementById('tree');
  DOM.searchInput = document.getElementById('searchInput');
  DOM.searchResults = document.getElementById('searchResults');
  DOM.tabs = document.getElementById('tabs');
  DOM.showTotal = document.getElementById('showTotal');
  DOM.showTotalContainer = document.getElementById('showTotalContainer');
  DOM.showTotalLabel = document.getElementById('showTotalLabel');
  DOM.showRatio = document.getElementById('showRatio');
  DOM.showRatioLabel = document.getElementById('showRatioLabel');
  DOM.dynamicLegendToggle = document.getElementById('dynamicLegendToggle');
  DOM.dropZone = document.getElementById('dropZone');
  DOM.fileTabs = document.getElementById('fileTabs');

  // load hint preference
  try {
    if (localStorage.getItem('rb_showMultiSelectHint') === '0') {
      _showMultiSelectHint = false;
    }
  } catch(_) {}
  updateMultiSelectHint();

  const closeBtn = document.getElementById('multiSelectHintClose');
  if (closeBtn) closeBtn.addEventListener('click', dismissMultiSelectHint);
  const showBtn = document.getElementById('showHintButton');
  if (showBtn) showBtn.addEventListener('click', showMultiSelectHint);
  updateHintToggleButton();

  // make the whole scale-toggle area clickable and simply invert current state
  ['xScaleToggle','yScaleToggle'].forEach(id => {
    const cont = document.getElementById(id);
    if (cont) cont.addEventListener('click', () => {
      const axis = id.startsWith('x') ? 'x' : 'y';
      const current = getScaleValue(axis);
      const newVal = current === 'linear' ? 'log' : 'linear';
      setScaleValue(axis, newVal);
      // If Auto range is selected, lin/log toggle should not leave Auto range
      const sel = document.getElementById('presetSelect');
      if (sel && sel.value === 'default') {
        _suppressPresetSync = true;
        updateChartScales();
        setTimeout(() => { _suppressPresetSync = false; }, 0);
      } else {
        updateChartScales();
      }
    });
  });

  // Wire tree-mode toggle buttons (separated / intersect / union)
  const tmContainer = document.getElementById('treeModeContainer');
  if (tmContainer) {
    tmContainer.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn || btn.disabled) return;
      if (btn.classList.contains('active')) return; // already selected
      tmContainer.querySelectorAll('button').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      toggleTreeMode();
    });
  }
}

/**
 * Get element by ID (with fallback if DOM cache not initialized)
 * @param {string} id - Element ID
 * @returns {HTMLElement|null}
 */
function getElement(id) {
  return DOM[id] || document.getElementById(id);
}

/**
 * Show or hide the "Show Total" checkbox based on context
 * @param {boolean} show - Whether to show the checkbox
 */
function setShowTotalVisible(show) {
  const label = getElement('showTotalLabel');
  if (label) {
    label.style.display = show ? '' : 'none';
  }
}

/**
 * Show or hide the "Show Ratio" checkbox based on context.
 * Only shown when there are exactly two enabled files (thick + thin lines).
 * @param {boolean} show - Whether to show the checkbox
 */
function setShowRatioVisible(show) {
  const label = getElement('showRatioLabel');
  if (label) {
    label.style.display = show ? '' : 'none';
  }
}

/**
 * Show or hide the "Show Max" checkbox based on context.
 * Visible whenever a time-series chart is displayed.
 * @param {boolean} show - Whether to show the checkbox
 */
function setShowMaxVisible(show) {
  const label = getElement('showMaxLabel');
  if (label) {
    label.style.display = show ? '' : 'none';
  }
}


