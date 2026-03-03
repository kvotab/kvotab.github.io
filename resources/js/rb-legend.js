/* ==========================================================================
   10. DYNAMIC LEGEND
   ========================================================================== */

/**
 * Toggle dynamic legend filtering on/off.
 * When enabled, only traces with data points visible in the current
 * viewport are shown in the legend. When disabled, all traces are shown.
 * 
 * @returns {void}
 */
function toggleDynamicLegend() {
  dynamicLegendEnabled = document.getElementById('dynamicLegend').checked;
  
  const plotDiv = document.getElementById('plotlyChart');
  if (!plotDiv || !plotDiv.data || !plotDiv.layout) {
    return;
  }
  
  if (!dynamicLegendEnabled) {
    // Show all legend items (except those explicitly hidden, e.g. by Show Ratio)
    const showlegendValues = plotDiv.data.map(trace => !trace._hiddenFromLegend);
    
    Plotly.restyle(plotDiv, { showlegend: showlegendValues }).then(() => {
      const statusEl = document.getElementById('legendStatus');
      if (statusEl) {
        statusEl.style.display = 'none';
      }
    });
  } else {
    refreshDynamicLegend();
  }
}

/**
 * Re-apply dynamic legend filtering based on the current viewport.
 * Reads axis ranges from the live Plotly layout and shows only traces
 * that have data points inside the visible area.
 *
 * Call this after any programmatic Plotly.relayout() that changes axes
 * (scale type, range, preset views, etc.).
 *
 * @returns {void}
 */
function refreshDynamicLegend() {
  if (!dynamicLegendEnabled) return;

  const plotDiv = document.getElementById('plotlyChart');
  if (!plotDiv || !plotDiv.data || !plotDiv.layout) return;

  const layout = plotDiv.layout;

  // Re-apply legend sorting by max Y value
  assignLegendRanks(plotDiv.data);

  let xRange = layout.xaxis?.range;
  let yRange = layout.yaxis?.range;

  if (!xRange || !yRange) return;

  const xIsLog = layout.xaxis?.type === 'log';
  const yIsLog = layout.yaxis?.type === 'log';

  const xMin = xIsLog ? Math.pow(10, xRange[0]) : xRange[0];
  const xMax = xIsLog ? Math.pow(10, xRange[1]) : xRange[1];
  const yMin = yIsLog ? Math.pow(10, yRange[0]) : yRange[0];
  const yMax = yIsLog ? Math.pow(10, yRange[1]) : yRange[1];

  let visibleCount = 0;

  // First pass: determine which traces have data in the viewport
  const traceInView = plotDiv.data.map((trace) => {
    for (let j = 0; j < trace.x.length; j++) {
      const x = trace.x[j];
      const y = trace.y[j];
      if (x == null || y == null) continue;
      if (x >= xMin && x <= xMax && y >= yMin && y <= yMax) return true;
    }
    return false;
  });

  // Build set of _datasetKey values that have any trace in view,
  // so hidden companion traces (secondary file) can contribute visibility.
  const visibleKeys = new Set();
  plotDiv.data.forEach((trace, i) => {
    if (traceInView[i] && trace._datasetKey) visibleKeys.add(trace._datasetKey);
  });

  const showlegendValues = plotDiv.data.map((trace, i) => {
    // A trace is visible if its own data is in view OR a companion trace
    // sharing the same _datasetKey has data in view.
    const isVisible = traceInView[i] ||
      !!(trace._datasetKey && visibleKeys.has(trace._datasetKey));

    const legendVisible = trace._hiddenFromLegend ? false : isVisible;
    if (legendVisible) visibleCount++;

    return legendVisible;
  });

  const legendrankValues = plotDiv.data.map(t => t.legendrank);
  window._dynamicLegendUpdating = true;
  Plotly.restyle(plotDiv, { showlegend: showlegendValues, legendrank: legendrankValues }).then(() => {
    window._dynamicLegendUpdating = false;
    const totalCount = plotDiv.data.length;
    const statusEl = document.getElementById('legendStatus');

    if (statusEl) {
      if (visibleCount < totalCount) {
        statusEl.textContent = `Showing ${visibleCount}/${totalCount} traces`;
        statusEl.style.display = 'block';
      } else {
        statusEl.style.display = 'none';
      }
    }
  }).catch(() => { window._dynamicLegendUpdating = false; });
}

/**
 * Set up dynamic legend filtering on zoom/pan events.
 * Attaches a plotly_relayout listener that updates legend visibility
 * based on which traces have data points in the current viewport.
 * 
 * This helps reduce legend clutter when zoomed in on charts with many traces.
 * A status indicator shows "Showing X/Y traces" when filtering is active.
 * 
 * @param {HTMLElement} plotDiv - The Plotly chart DOM element
 * @returns {void}
 */
function setupDynamicLegend(plotDiv) {
  plotDiv.on('plotly_relayout', function(eventData) {
    if (!dynamicLegendEnabled) return;
    if (window._dynamicLegendUpdating) return;
    
    if (!eventData || (!eventData['xaxis.range[0]'] && !eventData['xaxis.range'] && !eventData['xaxis.autorange'])) {
      return;
    }
    
    if (eventData['xaxis.autorange'] || eventData['yaxis.autorange']) {
      // Autorange - show all traces (except those explicitly hidden, e.g. by Show Ratio)
      const fullData = plotDiv.data;
      const visibility = fullData.map(trace => !trace._hiddenFromLegend);
      Plotly.restyle(plotDiv, { showlegend: visibility });
      
      const statusEl = document.getElementById('legendStatus');
      if (statusEl) {
        statusEl.style.display = 'none';
      }
      return;
    }
    
    // Delegate to refreshDynamicLegend which reads ranges from the live layout
    // and handles _datasetKey grouping for companion trace visibility.
    refreshDynamicLegend();
  });
}


