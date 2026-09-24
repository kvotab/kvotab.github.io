/* ==========================================================================
   RB CHART - the chart checkboxes and the background overlay
   --------------------------------------------------------------------------
   Split out of rb-chart.js, which had grown past 3 600 lines. These are plain
   scripts sharing globals, not ES modules, so the load order in rb.html is the
   order this code was in before the split, and has to stay that way:

     rb-chart-axes.js  ->  rb-chart-presets.js  ->  rb-chart-export.js
     ->  rb-chart-toggles.js  ->  rb-chart.js

   Nothing here runs at load time; the files hold declarations only. Functions
   call across files freely, since every call happens after all five have
   loaded.
   ========================================================================== */

'use strict';   // see the script manifest in rb.html for why
/**
 * Handle "Show Total" checkbox toggle for radionuclides charts.
 * When checked, adds a trace showing the sum of all radionuclide activities.
 * Only applicable when viewing a radionuclides group.
 * 
 * @returns {void}
 */
function toggleShowTotal() {
  if (selectedIsRadionuclidesGroup && selectedDatasetPath) {
    const savedAxis = captureAxisState();
    Promise.resolve().then(() => createRadionuclidesChart(selectedDatasetPath, savedAxis));
  }
}

/**
 * Handle "Show Ratio" checkbox toggle for radionuclides charts.
 * When checked, appends the ratio of max values (thick/thin) to the legend
 * name of thick-line traces.
 * 
 * @returns {void}
 */
function toggleShowRatio() {
  const ratioChecked = getElement('showRatio')?.checked;
  setShowMaxVisible(!ratioChecked);
  if (selectedIsRadionuclidesGroup && selectedDatasetPath) {
    const savedAxis = captureAxisState();
    Promise.resolve().then(() => createRadionuclidesChart(selectedDatasetPath, savedAxis));
  }
}

/**
 * Handle background overlay source change for special group charts.
 * @returns {void}
 */
function toggleBackgroundOverlay() {
  const select = getElement('backgroundSourceSelect');
  selectedBackgroundOverlaySource = select && select.value ? select.value : '__none__';
  if (selectedIsRadionuclidesGroup && selectedDatasetPath) {
    const savedAxis = captureAxisState();
    Promise.resolve().then(() => createRadionuclidesChart(selectedDatasetPath, savedAxis));
  } else if (!selectedIsRadionuclidesGroup && selectedDatasetPath) {
    const savedAxis = captureAxisState();
    Promise.resolve().then(() => createPlotlyChart(selectedDatasetPath, savedAxis));
  }
}

function ensureBackgroundOverlayTooltip() {
  let tip = document.getElementById('backgroundOverlayTooltip');
  if (!tip) {
    tip = document.createElement('div');
    tip.id = 'backgroundOverlayTooltip';
    tip.className = 'chart-bg-tooltip';
    tip.style.display = 'none';
    document.body.appendChild(tip);
  }
  return tip;
}

function toComparableAxisValue(v) {
  const n = Number(v);
  if (isFinite(n)) return n;
  const t = Date.parse(v);
  if (isFinite(t)) return t;
  return null;
}

function removeBackgroundOverlayTooltipHandlers(plotDiv) {
  if (!plotDiv || !plotDiv.__bgTooltipHandlers) return;
  const h = plotDiv.__bgTooltipHandlers;
  plotDiv.removeEventListener('mousemove', h.mousemove);
  plotDiv.removeEventListener('mouseleave', h.mouseleave);
  delete plotDiv.__bgTooltipHandlers;
}

/** Whether the chart now in plotDiv is showing a background overlay. */
function chartHasBackgroundShapes(plotDiv) {
  const shapes = plotDiv && plotDiv._fullLayout && plotDiv._fullLayout.shapes;
  return Array.isArray(shapes) && shapes.some(s => s && s.name === BACKGROUND_SHAPE_NAME);
}

/**
 * The layout.shapes a relayout must carry when it switches the x-axis to
 * `xScale`, or null when the chart has no background overlay. A relayout that
 * changes only xaxis.type leaves the rectangles clamped for the old scale; see
 * backgroundRectShapes for what that did to a log axis.
 *
 * @param {HTMLElement} plotDiv
 * @param {string} xScale - 'log' or 'linear'
 * @returns {Array|null}
 */
function backgroundShapesForXScale(plotDiv, xScale) {
  if (!chartHasBackgroundShapes(plotDiv)) return null;
  const segments = plotDiv.__bgSegments;
  if (!Array.isArray(segments) || !segments.length) return null;
  return backgroundRectShapes(segments, plotDiv.data || [], xScale);
}

function setupBackgroundOverlayTooltip(plotDiv, segments) {
  if (!plotDiv) return;
  removeBackgroundOverlayTooltipHandlers(plotDiv);

  const tip = ensureBackgroundOverlayTooltip();
  tip.style.display = 'none';

  if (!Array.isArray(segments) || segments.length === 0) {
    delete plotDiv.__bgSegments;
    return;
  }
  plotDiv.__bgSegments = segments;

  /*
    The segment bounds in the axis's own linear units, for the axis as it is
    NOW. This used to be worked out once, when the chart was drawn, and kept:
    clicking "log" then compared the pointer's log10(x), a number between
    about -9 and 5, with bounds still in years, so the whole chart read as the
    first segment -- and clicking back to "lin" on a chart drawn on log did the
    reverse, so nothing past x = 5 had a tooltip at all. The scale can change without a redraw
    (the scale buttons, a preset), so it is redone whenever the type differs.
  */
  let cachedFor = null;
  let cachedSegments = [];
  const segmentsOnAxis = (xAxis) => {
    if (cachedFor === xAxis.type) return cachedSegments;
    const toAxisLinearValue = (v) => {
      try {
        if (typeof xAxis.d2l === 'function') {
          const n = Number(xAxis.d2l(v));
          if (isFinite(n)) return n;
        }
      } catch (_) { ignoreFailure('toAxisLinearValue', _); }
      return toComparableAxisValue(v);
    };
    cachedFor = xAxis.type;
    cachedSegments = backgroundSegmentsOnScale(segments, plotDiv.data || [], xAxis.type)
      .map(seg => {
        const x0 = toAxisLinearValue(seg.x0);
        const x1 = toAxisLinearValue(seg.x1);
        if (x0 === null || x1 === null) return null;
        return { ...seg, _x0: Math.min(x0, x1), _x1: Math.max(x0, x1) };
      })
      .filter(Boolean);
    return cachedSegments;
  };

  const mousemove = (evt) => {
    const fullLayout = plotDiv._fullLayout;
    const xAxis = fullLayout && fullLayout.xaxis;
    const yAxis = fullLayout && fullLayout.yaxis;
    // The listener is on the div, which the next chart reuses; a chart
    // without the overlay must not answer with the last one's segments.
    if (!xAxis || !yAxis || !chartHasBackgroundShapes(plotDiv)) {
      tip.style.display = 'none';
      return;
    }

    const rect = plotDiv.getBoundingClientRect();
    const px = evt.clientX - rect.left;
    const py = evt.clientY - rect.top;

    const inX = px >= xAxis._offset && px <= (xAxis._offset + xAxis._length);
    const inY = py >= yAxis._offset && py <= (yAxis._offset + yAxis._length);
    if (!inX || !inY) {
      tip.style.display = 'none';
      return;
    }

    const axisX = xAxis.p2l(px - xAxis._offset);
    const xVal = Number(axisX);
    if (!isFinite(xVal)) {
      tip.style.display = 'none';
      return;
    }

    const match = segmentsOnAxis(xAxis).find(seg => xVal >= seg._x0 && xVal <= seg._x1);
    if (!match) {
      tip.style.display = 'none';
      return;
    }

    tip.textContent = match.category || 'Section';
    tip.style.display = 'block';
    tip.style.left = `${evt.clientX + 12}px`;
    tip.style.top = `${evt.clientY + 12}px`;
  };

  const mouseleave = () => {
    tip.style.display = 'none';
  };

  plotDiv.addEventListener('mousemove', mousemove);
  plotDiv.addEventListener('mouseleave', mouseleave);
  plotDiv.__bgTooltipHandlers = { mousemove, mouseleave };
}

/**
 * Handle "Show Max" checkbox toggle.
 * When checked, appends the maximum value to each trace's legend name.
 * Re-renders the current chart (single, multi-select, or radionuclides).
 * 
 * @returns {void}
 */
function toggleShowMax() {
  const plotDiv = getElement('plotlyChart');
  if (!plotDiv || !plotDiv.data) {
    return;
  }
  const showMax = getElement('showMax')?.checked;
  const newNames = plotDiv.data.map(trace => {
    if (trace._hiddenFromLegend) return trace.name;
    // Strip any existing " (…)" max suffix added by us.
    // Keep suffixes added by other features (ratio, file-diff) by only
    // removing a trailing parenthesised numeric value we appended.
    let baseName = trace._baseName || trace.name;
    if (showMax && trace.y && trace.y.length > 0) {
      const maxVal = trace.y.reduce((m, v) => v > m ? v : m, -Infinity);
      const formatted = maxVal === 0 || !isFinite(maxVal) ? String(maxVal) : maxVal.toPrecision(3);
      trace._baseName = baseName;
      return `${baseName} (${formatted})`;
    }
    // Unchecked — restore base name
    trace._baseName = baseName;
    return baseName;
  });
  Plotly.restyle(plotDiv, { name: newNames });
}

/**
 * Toggle the confidence interval band display.
 * Adds or removes CI band traces from the current chart.
 * CI band colors match the corresponding mean trace line colors.
 */
async function toggleShowCI() {
  const plotDiv = getElement('plotlyChart');
  if (!plotDiv || !plotDiv.data) {
    return;
  }
  const chartContainer = getElement('plotlyChartContainer');
  
  const showCI = getElement('showCI')?.checked;
  const shouldShowLoader = !!showCI;
  if (shouldShowLoader) {
    showChartLoading(chartContainer, 'Calculating confidence interval...');
    await new Promise(requestAnimationFrame);
    await new Promise(resolve => setTimeout(resolve, 0));
  }
  try {
    // Find existing CI band traces and remove them
    const existingCIIndices = [];
    plotDiv.data.forEach((trace, idx) => {
      if (trace._isCIBand) {
        existingCIIndices.push(idx);
      }
    });
    
    if (existingCIIndices.length > 0) {
      await Plotly.deleteTraces(plotDiv, existingCIIndices);
    }
    
    // If checkbox is now checked, add CI bands for all probabilistic traces
    if (showCI) {
      const ciTraces = [];
      plotDiv.data.forEach((trace) => {
        const hasColumnCI = Array.isArray(trace._ciP5) && Array.isArray(trace._ciP95) && trace._timeData;
        const hasProbCI = trace._isProbabilistic && trace._rawData && trace._timeData;
        if (hasColumnCI || hasProbCI) {
          const p5 = hasColumnCI ? trace._ciP5 : computeProbabilisticPercentile(trace._rawData, trace._timeData, 5, trace._numRealizations);
          const p95 = hasColumnCI ? trace._ciP95 : computeProbabilisticPercentile(trace._rawData, trace._timeData, 95, trace._numRealizations);
          const minLength = Math.min(trace._timeData.length, p5.length, p95.length);
          const timeSlice = trace._timeData.slice(0, minLength);
          const p5Slice = p5.slice(0, minLength);
          const p95Slice = p95.slice(0, minLength);
          
          // Get the trace's line color and convert to semi-transparent fill
          let traceColor = 'rgba(100, 150, 200, 0.2)';
          if (trace.line && trace.line.color) {
            const color = trace.line.color;
            if (color.startsWith('rgba')) {
              traceColor = color.replace(/,[\s]*[\d.]+\s*\)$/, ', 0.2)');
            } else if (color.startsWith('rgb')) {
              traceColor = color.replace(/^rgb\(/, 'rgba(').replace(/\)$/, ', 0.2)');
            } else if (color.startsWith('#')) {
              const hex = color.slice(1);
              const r = parseInt(hex.substr(0, 2), 16);
              const g = parseInt(hex.substr(2, 2), 16);
              const b = parseInt(hex.substr(4, 2), 16);
              traceColor = `rgba(${r}, ${g}, ${b}, 0.2)`;
            }
          }
          
          const ciBandTrace = {
            x: [...timeSlice, ...timeSlice.slice().reverse()],
            y: [...p95Slice, ...p5Slice.slice().reverse()],
            fill: 'tozeroy',
            fillcolor: traceColor,
            line: { color: 'rgba(255, 255, 255, 0)' },
            showlegend: false,
            hoverinfo: 'skip',
            _hiddenFromLegend: true,
            _isCIBand: true,
            mode: 'lines',
            name: 'CI Band'
          };
          ciTraces.push(ciBandTrace);
        }
      });
      
      if (ciTraces.length > 0) {
        await Plotly.addTraces(plotDiv, ciTraces);
      }
    }
    // A band can reach past a log axis on auto range, or leave it too tall.
    await snapLogRangeToDecades(plotDiv);
  } finally {
    if (shouldShowLoader) {
      hideChartLoading(chartContainer);
    }
  }
}

/**
 * Toggle SDOM band display.
 * SDOM band is mean +/- (sigma / sqrt(n_iter)).
 */
async function toggleShowSDOM() {
  const plotDiv = getElement('plotlyChart');
  if (!plotDiv || !plotDiv.data) {
    return;
  }
  const chartContainer = getElement('plotlyChartContainer');

  const showSDOM = getElement('showSDOM')?.checked;
  const shouldShowLoader = !!showSDOM;
  if (shouldShowLoader) {
    showChartLoading(chartContainer, 'Calculating SEM band...');
    await new Promise(requestAnimationFrame);
    await new Promise(resolve => setTimeout(resolve, 0));
  }

  try {
    const existingIndices = [];
    plotDiv.data.forEach((trace, idx) => {
      if (trace._isSDOMBand) {
        existingIndices.push(idx);
      }
    });
    if (existingIndices.length > 0) {
      await Plotly.deleteTraces(plotDiv, existingIndices);
    }

    if (showSDOM) {
      const sdomTraces = [];
      plotDiv.data.forEach((trace) => {
        const hasAttrSDOM = Array.isArray(trace._sdomLower) && Array.isArray(trace._sdomUpper) && trace._timeData;
        const hasProbSDOM = !!trace._nIter && trace._nIter > 1 && trace._rawData && trace._timeData;
        if (!hasAttrSDOM && !hasProbSDOM) return;

        /* One computation for both edges; this used to run the whole
           per-timestep pass twice, once for each side of the band. */
        const sdomBand = hasAttrSDOM ? null
          : computeProbabilisticSDOMBand(trace._rawData, trace._timeData, trace._nIter, trace._numRealizations);
        const lower = hasAttrSDOM ? trace._sdomLower : (sdomBand?.lower || []);
        const upper = hasAttrSDOM ? trace._sdomUpper : (sdomBand?.upper || []);
        const minLength = Math.min(trace._timeData.length, lower.length, upper.length);
        if (minLength <= 0) return;

        const timeSlice = trace._timeData.slice(0, minLength);
        const lowerSlice = lower.slice(0, minLength);
        const upperSlice = upper.slice(0, minLength);

        let traceColor = 'rgba(120, 120, 120, 0.18)';
        let hatchColor = 'rgba(90, 90, 90, 0.22)';
        if (trace.line && trace.line.color) {
          const color = trace.line.color;
          if (color.startsWith('rgba')) {
            traceColor = color.replace(/,[\s]*[\d.]+\s*\)$/, ', 0.18)');
            hatchColor = color.replace(/,[\s]*[\d.]+\s*\)$/, ', 0.28)');
          } else if (color.startsWith('rgb')) {
            traceColor = color.replace(/^rgb\(/, 'rgba(').replace(/\)$/, ', 0.18)');
            hatchColor = color.replace(/^rgb\(/, 'rgba(').replace(/\)$/, ', 0.28)');
          } else if (color.startsWith('#')) {
            const hex = color.slice(1);
            const r = parseInt(hex.substr(0, 2), 16);
            const g = parseInt(hex.substr(2, 2), 16);
            const b = parseInt(hex.substr(4, 2), 16);
            traceColor = `rgba(${r}, ${g}, ${b}, 0.18)`;
            hatchColor = `rgba(${r}, ${g}, ${b}, 0.28)`;
          }
        }

        sdomTraces.push({
          x: [...timeSlice, ...timeSlice.slice().reverse()],
          y: [...upperSlice, ...lowerSlice.slice().reverse()],
          fill: 'tozeroy',
          fillcolor: traceColor,
          line: { color: 'rgba(255, 255, 255, 0)' },
          showlegend: false,
          hoverinfo: 'skip',
          _hiddenFromLegend: true,
          _isSDOMBand: true,
          mode: 'lines',
          name: 'SDOM Band'
        });

        // Add a hatch-like overlay using sparse vertical stripe segments.
        // Use null separators so Plotly renders disjoint line pieces.
        const stripeX = [];
        const stripeY = [];
        const stripeStep = Math.max(1, Math.floor(minLength / 36));
        for (let i = 0; i < minLength; i += stripeStep) {
          const low = lowerSlice[i];
          const up = upperSlice[i];
          if (low === null || up === null || !isFinite(low) || !isFinite(up)) continue;
          stripeX.push(timeSlice[i], timeSlice[i], null);
          stripeY.push(up, low, null);
        }
        if (stripeX.length > 0) {
          sdomTraces.push({
            x: stripeX,
            y: stripeY,
            mode: 'lines',
            line: { color: hatchColor, width: 1, dash: 'dot' },
            showlegend: false,
            hoverinfo: 'skip',
            _hiddenFromLegend: true,
            _isSDOMBand: true,
            _isSDOMHatch: true,
            name: 'SDOM Hatch'
          });
        }
      });

      if (sdomTraces.length > 0) {
        await Plotly.addTraces(plotDiv, sdomTraces);
      }
    }
    await snapLogRangeToDecades(plotDiv);
  } finally {
    if (shouldShowLoader) {
      hideChartLoading(chartContainer);
    }
  }
}

/**
 * Toggle a specific iteration's time-series as a dotted line on the current chart.
 * Reads the iteration number (1-based) from #showIterNum and adds one dotted trace
 * per probabilistic base trace, using the same line color.
 */
function toggleShowIteration() {
  const plotDiv = getElement('plotlyChart');
  if (!plotDiv || !plotDiv.data) return;

  // Read and validate the requested iteration number
  const iterInput = getElement('showIterNum');
  const iterNumRaw = iterInput ? parseInt(iterInput.value, 10) : NaN;
  if (!isFinite(iterNumRaw) || iterNumRaw < 1) return;

  // ── Probabilistic-time mode ──────────────────────────────────────────────
  // The /time dataset is a matrix; each iteration has its own time axis.
  // Instead of adding a dotted overlay we replace the base trace data.
  if (currentChartData && currentChartData._isProbTimeChart) {
    const sourceTraces = Array.isArray(currentChartData.traces) ? currentChartData.traces : [];
    const hasSingleDatasetProbTimeTraces = sourceTraces.some(t => t._isProbTime);

    if (hasSingleDatasetProbTimeTraces) {
      // ── createPlotlyChart variant: restyle x/y on individual traces ──
      const xUpdates = [];
      const yUpdates = [];
      const indices  = [];

      // Find the index of each prob-time trace in the plotDiv (excluding any
      // legacy overlay traces that may be present).
      const plotTraces = plotDiv.data || [];
      sourceTraces.forEach(trace => {
        if (!trace._isProbTime) return;
        const plotIdx = plotTraces.findIndex(pt => pt === trace || (pt.name === trace.name && !pt._isIterTrace));
        if (plotIdx < 0) return;

        const iterIdx = Math.min(iterNumRaw - 1, trace._nIter - 1);
        const timeRow = trace._probTimeMatrix.matrix[iterIdx];
        const iterLen = trace._probTimeMatrix.iterLengths[iterIdx];

        const x = timeRow.slice(0, iterLen);
        const y = [];
        for (let t = 0; t < iterLen; t++) {
          y.push(PDFSampler.toNumber(trace._probYFlat[t * trace._probMaxLen + iterIdx]));
        }

        // Keep the trace object in sync so subsequent calls stay correct
        trace.x = x;
        trace.y = y;

        xUpdates.push(x);
        yUpdates.push(y);
        indices.push(plotIdx);
      });

      if (indices.length > 0) {
        Promise.resolve(Plotly.restyle(plotDiv, { x: xUpdates, y: yUpdates }, indices))
          .then(() => snapLogRangeToDecades(plotDiv));
      }
    } else {
      // ── createRadionuclidesChart variant: full redraw with new iteration ──
      const savedAxis = captureAxisState();
      Promise.resolve().then(() => createRadionuclidesChart(selectedDatasetPath, savedAxis));
    }
    return;
  }
  // ─────────────────────────────────────────────────────────────────────────

  // Remove any existing iteration overlay traces first
  const existingIndices = plotDiv.data
    .map((trace, idx) => trace._isIterTrace ? idx : -1)
    .filter(idx => idx >= 0);
  if (existingIndices.length > 0) {
    Plotly.deleteTraces(plotDiv, existingIndices);
  }

  const iterTraces = [];
  // Use currentChartData.traces for reliable _rawData access (Plotly may not preserve custom props)
  const sourceTraces = (currentChartData && Array.isArray(currentChartData.traces))
    ? currentChartData.traces : (plotDiv.data || []);
  sourceTraces.forEach(trace => {
    // A value that does not vary over time has one number per realisation.
    const constant = trace._constantSamples;
    if ((!trace._rawData && !constant) || !trace._timeData) return;
    const numRealizations = trace._numRealizations;
    if (!numRealizations || iterNumRaw > numRealizations) return;
    const r = iterNumRaw - 1;
    const y = [];
    for (let t = 0; t < trace._timeData.length; t++) {
      y.push(constant ? constant[r] : PDFSampler.toNumber(trace._rawData[t * numRealizations + r]));
    }
    const color = (trace.line && trace.line.color) ? trace.line.color : '#888888';
    iterTraces.push({
      x: trace._timeData.slice(),
      y,
      type: 'scatter',
      mode: 'lines',
      name: `Iter.\u00a0${iterNumRaw} \u2013 ${trace.name}`,
      line: { color, width: 1, dash: 'dot' },
      showlegend: true,
      _isIterTrace: true,
    });
  });

  // A realisation can reach past a log axis on auto range.
  Promise.resolve(iterTraces.length > 0 ? Plotly.addTraces(plotDiv, iterTraces) : null)
    .then(() => snapLogRangeToDecades(plotDiv));
}

/**
 * Append the maximum y-value to each trace's legend name.
 * Formats as "name (max)" using 3 significant digits.
 * Skips traces that are hidden from the legend.
 * @param {Object[]} traces - Plotly trace objects (modified in-place)
 */
function annotateTracesWithMax(traces) {
  for (const trace of traces) {
    if (trace._hiddenFromLegend) continue;
    if (!trace.y || trace.y.length === 0) continue;
    trace._baseName = trace.name;
    const maxVal = trace.y.reduce((m, v) => v > m ? v : m, -Infinity);
    const formatted = maxVal === 0 || !isFinite(maxVal) ? String(maxVal) : maxVal.toPrecision(3);
    trace.name = `${trace.name} (${formatted})`;
  }
}
