/* ==========================================================================
   RB CHART - the three chart builders
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
/* ==========================================================================
   9. CHART CREATION
   ========================================================================== */

/**
 * Create a Plotly chart for a single time-dependent dataset.
 * Plots the dataset from all enabled files as separate traces,
 * allowing comparison across files.
 * 
 * @param {string} path - HDF5 path to the dataset
 * @returns {void}
 */
/**
 * Background overlay rectangles for a Plotly layout.
 *
 * On a log x-axis a segment starting at or below zero cannot be drawn, so it
 * is clamped to the smallest positive x in the data and dropped if that leaves
 * it empty. Left at zero, Plotly still draws it -- from far past the left edge
 * -- and autorange follows it there: clicking "log" on a chart drawn linear
 * put the axis at 1e-9 to 1e5. So a change of x scale has to redraw these as
 * well (backgroundShapesForXScale), not just flip the axis type.
 *
 * The minimum is accumulated directly rather than collected into an array and
 * spread into Math.min, which throws RangeError once the trace set exceeds
 * roughly 125 000 points - one radionuclide group with a long time series
 * already does.
 *
 * This was the same forty lines in createPlotlyChart and in the radionuclides
 * renderer, differing only in line breaks.
 *
 * @param {Array} segments - {x0, x1, color} in data coordinates
 * @param {Array} traces - the traces being plotted, for the log-axis minimum
 * @param {string} xScale - 'log' or 'linear'
 * @returns {Array} Plotly shape objects, ready to concat onto layout.shapes
 */
function backgroundRectShapes(segments, traces, xScale) {
  return backgroundSegmentsOnScale(segments, traces, xScale).map(seg => ({
    type: 'rect', xref: 'x', yref: 'paper', name: BACKGROUND_SHAPE_NAME,
    x0: seg.x0, x1: seg.x1, y0: 0, y1: 1,
    line: { width: 0 }, fillcolor: seg.color, layer: 'below'
  }));
}

/*
  How the overlay's rectangles are told apart from any other shape, by the
  tooltip and by a change of x scale -- the plot div outlives the chart drawn
  in it, so "this div once had an overlay" says nothing about the chart now.
*/
const BACKGROUND_SHAPE_NAME = 'kvot-background-overlay';

/**
 * Where the overlay segments sit on an x-axis of this scale: the clamping
 * described above, and nothing else. Both the rectangles and the tooltip over
 * them come from here, so what is coloured and what is named always agree.
 *
 * @param {Array} segments - {x0, x1, ...} in data coordinates
 * @param {Array} traces - the traces being plotted, for the log-axis minimum
 * @param {string} xScale - 'log' or 'linear'
 * @returns {Array} the segments, clamped and filtered for that scale
 */
function backgroundSegmentsOnScale(segments, traces, xScale) {
  let shapeSegments = segments.slice();
  if (xScale === 'log') {
    let minPositiveX = null;
    for (const trace of traces) {
      const xVals = Array.isArray(trace.x) ? trace.x : [];
      for (const xv of xVals) {
        const n = Number(xv);
        if (isFinite(n) && n > 0 && (minPositiveX === null || n < minPositiveX)) minPositiveX = n;
      }
    }
    if (minPositiveX !== null) {
      shapeSegments = shapeSegments
        .map(seg => {
          const rawX0 = Number(seg.x0);
          const rawX1 = Number(seg.x1);
          if (!isFinite(rawX0) || !isFinite(rawX1)) return null;
          let x0 = rawX0;
          let x1 = rawX1;
          if (x0 <= 0 && x1 <= 0) return null;
          if (x0 <= 0) x0 = minPositiveX;
          if (x1 <= 0) x1 = minPositiveX;
          if (x1 < x0) { const tmp = x0; x0 = x1; x1 = tmp; }
          if (x1 === x0) return null;
          return { ...seg, x0, x1 };
        })
        .filter(Boolean);
    }
  }
  return shapeSegments;
}


function createPlotlyChart(path, savedAxisState) {
  if (!_axesLocked) resetPresetDropdown();
  const chartContainer = getElement('plotlyChartContainer');
  showChartLoading(chartContainer);
  const plotDiv = getElement('plotlyChart');

  let wasCIChecked = false;
  let wasSDOMChecked = false;
  let backgroundSourceValue = selectedBackgroundOverlaySource || '__none__';
  try {
    const ciCheckbox = getElement('showCI');
    if (ciCheckbox) {
      wasCIChecked = !!ciCheckbox.checked;
    }
    const sdomCheckbox = getElement('showSDOM');
    if (sdomCheckbox) {
      wasSDOMChecked = !!sdomCheckbox.checked;
    }
    const backgroundSelect = getElement('backgroundSourceSelect');
    if (backgroundSelect && backgroundSelect.value) {
      backgroundSourceValue = backgroundSelect.value;
    }
  } catch (e) { ignoreFailure('createPlotlyChart', e); }

  plotDiv.innerHTML = '';

  // Hide "Show Total" and "Show Ratio" checkboxes (only for radionuclides groups)
  setShowTotalVisible(false);
  setShowRatioVisible(false);
  setShowMaxVisible(true);
  setShowCIVisible(false);  // Will be enabled if we have probabilistic data
  setShowSDOMVisible(false); // Will be enabled if SDOM is available
  setBackgroundSelectorVisible(false);
  setIterationSelectorVisible(false);

  const traces = [];
  const enabledFiles = getEffectiveFiles();
  const probDataInfo = [];  // Track raw data for probabilistic datasets
  let hasProbabilistic = false;
  let hasSDOM = false;
  let hasProbTime = false;          // Any file has a probabilistic /time matrix
  let probTimeIterMax = 0;          // Maximum nIter across all prob-time files
  const nIterByFile = {};

  // Determine the currently-selected iteration index (0-based, default 0)
  const _iterInputEarly = getElement('showIterNum');
  const _selectedIterNum  = (_iterInputEarly && _iterInputEarly.value) ? parseInt(_iterInputEarly.value, 10) : 1;
  const _selectedIterIdx  = (isFinite(_selectedIterNum) && _selectedIterNum >= 1) ? _selectedIterNum - 1 : 0;

  let timeUnit = '';
  let yAxisUnit = '';
  let yAxisName = path.split('/').pop();
  let backgroundSourceOptions = [{ value: '__none__', label: 'No background' }];
  let indexBackgroundSegments = [];

  if (enabledFiles.length > 0) {
    const firstFile = loadedFiles[enabledFiles[0]];
    timeUnit = getTimeUnit(firstFile);

    // Get y-axis unit from the first file's dataset (best-effort)
    try {
      const dataset = FileService.get(firstFile, path);
      const unit = getAttr(dataset, 'unit');
      if (unit !== undefined && unit !== null) yAxisUnit = unit;
    } catch (e) {
      kvotWarn('Could not read unit from dataset:', e);
    }

    // Collect background source options from parent group or root IndexLists
    try {
      const parentPath = path.substring(0, path.lastIndexOf('/')) || '/';
      backgroundSourceOptions = collectBackgroundSourceOptions(firstFile, null, parentPath);
      if (!backgroundSourceOptions.some(o => o.value === backgroundSourceValue)) {
        backgroundSourceValue = '__none__';
      }
      selectedBackgroundOverlaySource = backgroundSourceValue;
      populateBackgroundSelector(backgroundSourceOptions, backgroundSourceValue);
      setBackgroundSelectorVisible(backgroundSourceOptions.length > 1);
      if (backgroundSourceValue !== '__none__') {
        const timeData = getTimeData(firstFile);
        if (timeData) {
          indexBackgroundSegments = collectIndexBackgroundSegments(firstFile, backgroundSourceValue, timeData);
        }
      }
    } catch (e) { ignoreFailure('createPlotlyChart', e); }
  }

  // Build traces for each enabled file
  for (const fileKey of enabledFiles) {
    const file = loadedFiles[fileKey];
    if (nIterByFile[fileKey] === undefined) {
      nIterByFile[fileKey] = getRootNIter(file);
    }
    const nIter = nIterByFile[fileKey];

    if (!checkDatasetExistsInFile(file, path)) {
      continue;
    }

    try {
      const dataset = FileService.get(file, path);

      if (!isTimeDependent(dataset)) {
        continue;
      }

      const timeData = getTimeData(file);
      if (!timeData) {
        kvotWarn(`No /time dataset found in ${fileKey}`);
        continue;
      }

      let yData;
      if (typeof dataset.value !== 'undefined') {
        yData = dataset.value;
      } else if (typeof dataset.toArray === 'function') {
        yData = dataset.toArray();
      }

      if (yData) {
        /*
          The boxed copy is only needed by the statistics paths further down.
          The probabilistic branch reads one strided column — a few hundred of
          several hundred thousand values — so converting the whole array there
          cost about 16 ms and 4 MB per dataset for nothing.
        */
        const isProbTimeFile = checkTimeProbabilistic(file);
        const normalizedRawData = isProbTimeFile ? null : PDFSampler.normalizeDataArray(yData);

        // ── Probabilistic time matrix ────────────────────────────────────────
        // When /time carries a 'probabilistic' attribute the time axis is a
        // matrix [nIter × maxLen].  Each iteration has its own time series
        // that ends when values stop being strictly increasing.  Statistics
        // (mean, CI, SDOM) cannot be computed; only a single iteration is shown.
        if (isProbTimeFile) {
          const timeMatrix = getProbabilisticTimeMatrix(file);
          if (!timeMatrix) continue;  // Malformed – skip

          hasProbTime = true;
          if (timeMatrix.nIter > probTimeIterMax) probTimeIterMax = timeMatrix.nIter;

          const iterIdx  = Math.min(_selectedIterIdx, timeMatrix.nIter - 1);
          const timeRow  = timeMatrix.matrix[iterIdx];
          const iterLen  = timeMatrix.iterLengths[iterIdx];
          const iterTimeData = timeRow.slice(0, iterLen);

          // Extract y values for this iteration.
          // Y-data layout matches time matrix: flat[t_i * maxLen + k] = y at time step t_i for iter k.
          const iterYData = [];
          for (let t = 0; t < iterLen; t++) {
            iterYData.push(PDFSampler.toNumber(yData[t * timeMatrix.maxLen + iterIdx]));
          }

          const traceObj = ChartService.timeSeriesTrace({
            x: iterTimeData,
            y: iterYData,
            name: buildTraceName(yAxisName, path, fileKey, [path], enabledFiles)
          });
          traceObj._isProbTime     = true;
          traceObj._probTimeMatrix = timeMatrix;
          traceObj._probYFlat      = yData;
          traceObj._probMaxLen     = timeMatrix.maxLen;
          traceObj._nIter          = timeMatrix.nIter;
          traces.push(traceObj);
          continue;  // Skip the regular probabilistic / column-stats path
        }
        // ─────────────────────────────────────────────────────────────────────
        let yArray = normalizedRawData;
        let isProbabilistic = false;
        let ciFromColumns = null;
        let sdomInfo = null;

        const colStats = getColumnStatisticsSeries(dataset, normalizedRawData, timeData);
        if (colStats && Array.isArray(colStats.meanSeries)) {
          yArray = colStats.meanSeries;
          if (Array.isArray(colStats.p5Series) && Array.isArray(colStats.p95Series)) {
            hasProbabilistic = true;
            ciFromColumns = { p5: colStats.p5Series, p95: colStats.p95Series };
          }
          if (nIter && nIter > 1 && Array.isArray(colStats.sigmaSeries)) {
            const sqrtN = Math.sqrt(nIter);
            sdomInfo = {
              meanSeries: colStats.meanSeries,
              lower: colStats.meanSeries.map((mean, idx) => {
                const sigma = colStats.sigmaSeries[idx];
                if (mean === null || sigma === null) return null;
                const sdom = PDFSampler.toNumber(sigma) / sqrtN;
                return isFinite(sdom) ? mean - sdom : null;
              }),
              upper: colStats.meanSeries.map((mean, idx) => {
                const sigma = colStats.sigmaSeries[idx];
                if (mean === null || sigma === null) return null;
                const sdom = PDFSampler.toNumber(sigma) / sqrtN;
                return isFinite(sdom) ? mean + sdom : null;
              })
            };
            hasSDOM = true;
          }
        }

        // Handle probabilistic data (take mean)
        if (!colStats && checkIsProbabilistic(dataset)) {
          isProbabilistic = true;
          hasProbabilistic = true;
          // Store raw data for CI band computation later
          probDataInfo.push({ yArray, timeData: timeData.slice() });
          yArray = computeProbabilisticMean(yArray, timeData, getRealizationStride(dataset, normalizedRawData.length, timeData.length, path));
        }

        if (!isProbabilistic) {
          sdomInfo = sdomInfo || getDatasetAttributeSDOM(dataset, timeData, nIter);
          if (sdomInfo && Array.isArray(sdomInfo.meanSeries)) {
            yArray = sdomInfo.meanSeries;
            hasSDOM = true;
          }
        } else if (nIter && nIter > 1) {
          hasSDOM = true;
        }

        // Handle length mismatch
        const minLength = Math.min(timeData.length, yArray.length);
        if (timeData.length !== yArray.length) {
          kvotWarn(`Time data length (${timeData.length}) doesn't match data length (${yArray.length}) for ${fileKey}`);
        }

        const traceObj = ChartService.timeSeriesTrace({ x: timeData.slice(0, minLength), y: yArray.slice(0, minLength), name: buildTraceName(yAxisName, path, fileKey, [path], enabledFiles) });
        traceObj._isProbabilistic = isProbabilistic || !!ciFromColumns;
        if (isProbabilistic) {
          // Store raw data and time data on the trace for CI computation
          traceObj._rawData = normalizedRawData;
          traceObj._timeData = timeData.slice(0, minLength);
          traceObj._numRealizations = getRealizationStride(dataset, normalizedRawData.length, timeData.length, path);
          if (nIter && nIter > 1) {
            traceObj._nIter = nIter;
          }
        } else if (ciFromColumns) {
          traceObj._ciP5 = ciFromColumns.p5.slice(0, minLength);
          traceObj._ciP95 = ciFromColumns.p95.slice(0, minLength);
          traceObj._timeData = timeData.slice(0, minLength);
        }
        if (sdomInfo) {
          traceObj._sdomLower = sdomInfo.lower.slice(0, minLength);
          traceObj._sdomUpper = sdomInfo.upper.slice(0, minLength);
          traceObj._timeData = timeData.slice(0, minLength);
        }
        traces.push(traceObj);
      }
    } catch (e) {
      console.error(`Error creating trace for ${fileKey}:`, e);
    }
  }

  renderPlotlyChart({
    traces, path, chartContainer, savedAxisState, hasProbabilistic, hasProbTime,
    hasSDOM, probTimeIterMax, indexBackgroundSegments, timeUnit, yAxisUnit,
    backgroundSourceOptions, backgroundSourceValue, wasCIChecked, wasSDOMChecked
  });
}

/**
 * Draw the single-dataset chart once its traces exist.
 *
 * Split out of createPlotlyChart. Everything here is presentation: which
 * controls the data warrants, the axis titles, the Plotly call and the state
 * restored once it resolves. Nothing in it decides what the traces are.
 *
 * It takes a context object rather than fifteen arguments, which is what the
 * split costs - the block reads that many values from the function it used to
 * sit inside.
 *
 * @param {Object} ctx - see the destructuring below for the fields used
 */
function renderPlotlyChart(ctx) {
  const {
    traces, path, chartContainer, savedAxisState, hasProbabilistic, hasProbTime,
    hasSDOM, probTimeIterMax, indexBackgroundSegments, timeUnit, yAxisUnit,
    backgroundSourceOptions, backgroundSourceValue, wasCIChecked, wasSDOMChecked
  } = ctx;

  // Render chart if we have data
  if (traces.length > 0) {
    // Show CI checkbox if we have probabilistic data
    if (hasProbabilistic) {
      setShowCIVisible(true);
    }

    // Annotate legend with max values if "Show Max" is checked
    const showMaxCb = getElement('showMax');
    if (showMaxCb && showMaxCb.checked) {
      annotateTracesWithMax(traces);
    }

    const { xScale, yScale } = getChartScales();

    let yAxisTitle = 'Value';
    if (yAxisUnit) {
      yAxisTitle = `Value (${yAxisUnit})`;
    }

    const paths = [path];
    const layout = ChartService.createBaseLayout({
      title: path,
      xAxisTitle: timeUnit ? `Time (${timeUnit})` : 'Time',
      yAxisTitle,
      xScale,
      yScale
    });
    layout.margin.r = 200; // Extra room for longer legend names

    if (indexBackgroundSegments.length) {
      layout.shapes = (layout.shapes || [])
        .concat(backgroundRectShapes(indexBackgroundSegments, traces, xScale));
    }

    applyAxisState(layout, savedAxisState);
    _applyLockedAxes(layout);

    // Show CI / SDOM controls only for regular (non prob-time) probabilistic data
    setShowCIVisible(hasProbabilistic && !hasProbTime);
    setShowSDOMVisible(hasSDOM && !hasProbTime);

    // Iteration selector: prob-time charts always show it; regular prob charts
    // show it only when there are realizations stored on the traces.
    const _regularIterMax = traces.filter(t => t._numRealizations).reduce((m, t) => Math.max(m, t._numRealizations), 0);
    const _iterMax = hasProbTime ? probTimeIterMax : _regularIterMax;
    setIterationSelectorVisible(_iterMax > 0);
    if (_iterMax > 0) setIterationSelectorMax(_iterMax);

    const config = getPlotlyConfig('multi_dataset_chart');

    currentChartData = { traces, layout, paths, _isProbTimeChart: hasProbTime };
    if (chartContainer) chartContainer.classList.add('visible');
    if (dynamicLegendEnabled) {
      assignLegendRanks(traces);
    }
    Plotly.newPlot('plotlyChart', traces, layout, config).then(() => {
      const pDiv = getElement('plotlyChart');
      setupDynamicLegend(pDiv);
      setupPresetRelayoutSync(pDiv);
      refreshDynamicLegend();
      snapLogRangeToDecades(pDiv);
      // Restore CI state if we have probabilistic data and it was previously checked
      if (hasProbabilistic && !hasProbTime && wasCIChecked) {
        const ciCheckboxNew = getElement('showCI');
        if (ciCheckboxNew) {
          ciCheckboxNew.checked = true;
          toggleShowCI();
        }
      }
      if (hasSDOM && !hasProbTime && wasSDOMChecked) {
        const sdomCheckboxNew = getElement('showSDOM');
        if (sdomCheckboxNew) {
          sdomCheckboxNew.checked = true;
          toggleShowSDOM();
        }
      }
      // For regular probabilistic data, add dotted iteration overlay if one is selected.
      // For prob-time charts the correct iteration is already baked into the traces.
      if (!hasProbTime) {
        const _iterInput = getElement('showIterNum');
        if (_iterInput && _iterInput.value && parseInt(_iterInput.value, 10) >= 1) {
          toggleShowIteration();
        }
      }
      populateBackgroundSelector(backgroundSourceOptions, backgroundSourceValue);
      setBackgroundSelectorVisible(backgroundSourceOptions.length > 1);
      setupBackgroundOverlayTooltip(getElement('plotlyChart'), indexBackgroundSegments);
      hideChartLoading(chartContainer);
    });
  } else {
    hideChart();
  }
}


/**
 * A flat line across `span` for a value that does not vary over time (see
 * constantValuesOf). Given realisations it is their mean, and it carries what
 * the CI, SEM and Show iteration toggles read, all of it flat as well: the
 * 5-95 % band, mean ± σ/√n_iter and each realisation's own value.
 *
 * @param {{values: number[], name: string, line: Object, nIter: number|null}} constant
 * @param {number[]} span - The times to draw it at
 * @returns {Object} Plotly trace
 */
function constantTrace({ values, name, line, nIter }, span) {
  const flat = (v) => span.map(() => v);
  const finite = values.filter(Number.isFinite);
  const mean = finite.reduce((a, b) => a + b, 0) / finite.length;
  const many = values.length > 1;
  const trace = ChartService.timeSeriesTrace({ x: span, y: flat(mean), name, line,
    hovertemplate: `<b>${name}</b><br>Value: %{y}<br>${many ? `Mean of ${values.length} realisations, not` : 'Not'} time-dependent<extra></extra>` });
  if (!many) return trace;
  trace._isProbabilistic = true;
  trace._timeData = span;
  trace._ciP5 = flat(computeProbabilisticPercentile(values, [0], 5, values.length)[0]);
  trace._ciP95 = flat(computeProbabilisticPercentile(values, [0], 95, values.length)[0]);
  trace._constantSamples = values;
  trace._numRealizations = values.length;
  const sdom = nIter > 1 ? computeProbabilisticSDOMBand(values, [0], nIter, values.length) : null;
  if (sdom) {
    trace._sdomLower = flat(sdom.lower[0]);
    trace._sdomUpper = flat(sdom.upper[0]);
  }
  return trace;
}

/**
 * Create a Plotly chart comparing multiple selected datasets.
 * Each selection item carries its own fileKey so cross-file comparisons work.
 *
 * Used in multi-select mode (Ctrl+click on datasets, possibly from different files).
 * A selected value that does not vary over time is drawn as a flat line across
 * the time series, as long as there is at least one of those to draw.
 *
 * @param {{path: string, fileKey: string|null}[]} items - Array of selected dataset items
 * @returns {void}
 */
function createMultiDatasetChart(items) {
  if (!_axesLocked) resetPresetDropdown();
  const plotDiv = getElement('plotlyChart');
  const chartContainer = getElement('plotlyChartContainer');
  showChartLoading(chartContainer);
  
    // Save CI state and checkbox reference before clearing
    let wasCIChecked = false;
    let wasSDOMChecked = false;
    try {
      const ciCheckbox = getElement('showCI');
      if (ciCheckbox) {
        wasCIChecked = ciCheckbox.checked || false;
      }
      const sdomCheckbox = getElement('showSDOM');
      if (sdomCheckbox) {
        wasSDOMChecked = sdomCheckbox.checked || false;
      }
    } catch (e) { ignoreFailure('createMultiDatasetChart', e); }
  
  if (plotDiv) plotDiv.innerHTML = '';
  
  // Hide "Show Total" and "Show Ratio" checkboxes (only for radionuclides groups)
  setShowTotalVisible(false);
  setShowRatioVisible(false);
  setShowMaxVisible(true);
  setShowCIVisible(false);  // Will be enabled if we have probabilistic data
  setShowSDOMVisible(false); // Will be enabled if SDOM is available
  setBackgroundSelectorVisible(false);
  setIterationSelectorVisible(false);
  
  const traces = [];
  const yAxisUnits = new Set();
  const probDataInfo = [];  // Track raw data for probabilistic datasets
  let hasProbabilistic = false;
  let hasSDOM = false;
  const nIterByFile = {};
  let timeUnit = '';
  const meanTracesByIndex = {};  // Map CI trace back to mean trace for color matching
  
  // Normalize items: if fileKey is null (intersect mode), expand to all enabled files
  // Deduplicate so each (path, fileKey) pair is unique
  const normalizedItems = [];
  const seen = new Set();
  for (const item of items) {
    if (item.fileKey && loadedFiles[item.fileKey]) {
      const key = item.path + '|' + item.fileKey;
      if (!seen.has(key)) {
        normalizedItems.push(item);
        seen.add(key);
      }
    } else {
      // Intersect mode — expand to all enabled files
      for (const fk of getEnabledFiles()) {
        const key = item.path + '|' + fk;
        if (!seen.has(key)) {
          normalizedItems.push({ path: item.path, fileKey: fk });
          seen.add(key);
        }
      }
    }
  }
  
  // Collect unique file keys from items
  const uniqueFileKeys = [...new Set(normalizedItems.map(d => d.fileKey).filter(Boolean))];
  if (uniqueFileKeys.length === 0) return hideChart();
  
  // Use first file for time unit
  const firstFile = loadedFiles[uniqueFileKeys[0]];
  if (firstFile) timeUnit = getTimeUnit(firstFile);
  
  // Color palette for different datasets
  const colors = [
    '#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6',
    '#1abc9c', '#e67e22', '#34495e', '#c0392b', '#2980b9',
    '#27ae60', '#f1c40f', '#8e44ad', '#16a085', '#d35400'
  ];
  
  // Unique paths for color assignment
  const uniquePaths = [...new Set(normalizedItems.map(d => d.path))];
  const multiFile = uniqueFileKeys.length > 1;
  const multiPath = uniquePaths.length > 1;
  
  // Pre-compute context arrays for buildTraceName
  const allPaths = normalizedItems.map(d => d.path);
  const allFileKeys = normalizedItems.map(d => d.fileKey);

  // One line style per file when several are compared, thinner than a single file's.
  const dashStyles = ['solid', 'dash', 'dot', 'dashdot'];
  const lineFor = (fileKey, color) => multiFile
    ? { color, dash: dashStyles[uniqueFileKeys.indexOf(fileKey) % dashStyles.length], width: 1.5 }
    : { color, dash: 'solid', width: 2 };

  // Values that do not vary over time, drawn once the time series have set the span.
  const constants = [];

  for (const [itemIndex, item] of normalizedItems.entries()) {
    const { path, fileKey } = item;
    const datasetName = path.split('/').pop();
    const pathIdx = uniquePaths.indexOf(path);
    const baseColor = colors[pathIdx % colors.length];
    
    const file = loadedFiles[fileKey];
    if (!file || !checkDatasetExistsInFile(file, path)) continue;
    if (nIterByFile[fileKey] === undefined) {
      nIterByFile[fileKey] = getRootNIter(file);
    }
    const nIter = nIterByFile[fileKey];
    
    try {
      const dataset = FileService.get(file, path);
      if (!isTimeDependent(dataset)) {
        const values = constantValuesOf(dataset, nIter);
        if (values) {
          constants.push({ at: traces.length, values, nIter, unit: getAttr(dataset, 'unit'),
            name: buildTraceName(datasetName, path, fileKey, allPaths, allFileKeys),
            line: lineFor(fileKey, baseColor) });
        }
        continue;
      }

      // Get unit
      let yAxisUnit = '';
      const unitVal = getAttr(dataset, 'unit');
      if (unitVal !== undefined && unitVal !== null) {
        yAxisUnit = unitVal;
        yAxisUnits.add(yAxisUnit);
      }
      
      const timeData = getTimeData(file);
      if (!timeData) {
        kvotWarn(`No /time dataset found in ${fileKey}`);
        continue;
      }
      
      let yData;
      if (typeof dataset.value !== 'undefined') {
        yData = dataset.value;
      } else if (typeof dataset.toArray === 'function') {
        yData = dataset.toArray();
      }
      
      if (yData) {
        const normalizedRawData = PDFSampler.normalizeDataArray(yData);
        let yArray = normalizedRawData;
        let isProbabilistic = false;
        let ciFromColumns = null;
        let sdomInfo = null;

        const colStats = getColumnStatisticsSeries(dataset, normalizedRawData, timeData);
        if (colStats && Array.isArray(colStats.meanSeries)) {
          yArray = colStats.meanSeries;
          if (Array.isArray(colStats.p5Series) && Array.isArray(colStats.p95Series)) {
            hasProbabilistic = true;
            ciFromColumns = { p5: colStats.p5Series, p95: colStats.p95Series };
          }
          if (nIter && nIter > 1 && Array.isArray(colStats.sigmaSeries)) {
            const sqrtN = Math.sqrt(nIter);
            sdomInfo = {
              meanSeries: colStats.meanSeries,
              lower: colStats.meanSeries.map((mean, idx) => {
                const sigma = colStats.sigmaSeries[idx];
                if (mean === null || sigma === null) return null;
                const sdom = PDFSampler.toNumber(sigma) / sqrtN;
                return isFinite(sdom) ? mean - sdom : null;
              }),
              upper: colStats.meanSeries.map((mean, idx) => {
                const sigma = colStats.sigmaSeries[idx];
                if (mean === null || sigma === null) return null;
                const sdom = PDFSampler.toNumber(sigma) / sqrtN;
                return isFinite(sdom) ? mean + sdom : null;
              })
            };
            hasSDOM = true;
          }
        }
        
        // Handle probabilistic data (take mean)
        if (!colStats && checkIsProbabilistic(dataset)) {
          isProbabilistic = true;
          hasProbabilistic = true;
          // Store raw data for CI band computation later
          probDataInfo.push({ yArray, timeData: timeData.slice() });
          yArray = computeProbabilisticMean(yArray, timeData, getRealizationStride(dataset, normalizedRawData.length, timeData.length, path));
        }

        if (!isProbabilistic) {
          sdomInfo = sdomInfo || getDatasetAttributeSDOM(dataset, timeData, nIter);
          if (sdomInfo && Array.isArray(sdomInfo.meanSeries)) {
            yArray = sdomInfo.meanSeries;
            hasSDOM = true;
          }
        } else if (nIter && nIter > 1) {
          hasSDOM = true;
        }

        const minLength = Math.min(timeData.length, yArray.length);
        const trimmedTimeData = timeData.slice(0, minLength);
        const trimmedYData = yArray.slice(0, minLength);
        
        // Build trace name — harmonized via buildTraceName
        const traceName = buildTraceName(datasetName, path, fileKey, allPaths, allFileKeys);
        const traceObj = ChartService.timeSeriesTrace({ x: trimmedTimeData, y: trimmedYData, name: traceName, line: lineFor(fileKey, baseColor), hovertemplate: `<b>${traceName}</b><br>Time: %{x}<br>Value: %{y}<extra></extra>` });
        traceObj._isProbabilistic = isProbabilistic || !!ciFromColumns;
        if (isProbabilistic) {
          // Store raw data and time data on the trace for CI computation
          traceObj._rawData = normalizedRawData;
          traceObj._timeData = trimmedTimeData;
          traceObj._numRealizations = getRealizationStride(dataset, normalizedRawData.length, timeData.length, path);
          if (nIter && nIter > 1) {
            traceObj._nIter = nIter;
          }
        } else if (ciFromColumns) {
          traceObj._ciP5 = ciFromColumns.p5.slice(0, minLength);
          traceObj._ciP95 = ciFromColumns.p95.slice(0, minLength);
          traceObj._timeData = trimmedTimeData;
        }
        if (sdomInfo) {
          traceObj._sdomLower = sdomInfo.lower.slice(0, minLength);
          traceObj._sdomUpper = sdomInfo.upper.slice(0, minLength);
          traceObj._timeData = trimmedTimeData;
        }
        traces.push(traceObj);
      }
    } catch (e) {
      console.error(`Error creating trace for ${path} in ${fileKey}:`, e);
    }
  }

  // A constant runs flat across the time series, through every time any of
  // them reports: it then answers a hover wherever they do, and it survives a
  // log axis, which drops t = 0. It keeps its place in the selection's order.
  if (traces.length > 0 && constants.length > 0) {
    const span = [...new Set(traces.flatMap(t => t.x))].filter(Number.isFinite).sort((a, b) => a - b);
    for (const c of constants.reverse()) {
      const trace = constantTrace(c, span);
      if (c.unit !== undefined && c.unit !== null) yAxisUnits.add(c.unit);
      if (trace._isProbabilistic) hasProbabilistic = true;
      if (trace._sdomLower) hasSDOM = true;
      traces.splice(c.at, 0, trace);
    }
  }

  if (traces.length > 0) {
    // Show CI checkbox if we have probabilistic data
    if (hasProbabilistic) {
      setShowCIVisible(true);
    }
    if (hasSDOM) {
      setShowSDOMVisible(true);
    }
    const _iterMax = traces.filter(t => t._numRealizations).reduce((m, t) => Math.max(m, t._numRealizations), 0);
    setIterationSelectorVisible(_iterMax > 0);
    if (_iterMax > 0) setIterationSelectorMax(_iterMax);

    // Annotate legend with max values if "Show Max" is checked
    const showMaxCb = getElement('showMax');
    if (showMaxCb && showMaxCb.checked) {
      annotateTracesWithMax(traces);
    }

    const { xScale, yScale } = getChartScales();
    
    let yAxisTitle = 'Value';
    if (yAxisUnits.size === 1) {
      yAxisTitle = `Value (${Array.from(yAxisUnits)[0]})`;
    } else if (yAxisUnits.size > 1) {
      yAxisTitle = `Value (${Array.from(yAxisUnits).join(', ')})`;
    }
    
    const paths = normalizedItems.map(d => d.path);
    const layout = ChartService.createBaseLayout({
      title: `Comparing ${normalizedItems.length} dataset${normalizedItems.length > 1 ? 's' : ''}`,
      xAxisTitle: timeUnit ? `Time (${timeUnit})` : 'Time',
      yAxisTitle,
      xScale,
      yScale
    });
    layout.margin.r = 200; // Extra room for longer legend names
    _applyLockedAxes(layout);
    
    const config = getPlotlyConfig('multi_dataset_chart');

    currentChartData = { traces, layout, paths };
    const container = getElement('plotlyChartContainer');
    if (container) container.classList.add('visible');
    if (dynamicLegendEnabled) {
      assignLegendRanks(traces);
    }
      Plotly.newPlot('plotlyChart', traces, layout, config).then(() => {
        const pDiv = getElement('plotlyChart');
        setupDynamicLegend(pDiv);
        setupPresetRelayoutSync(pDiv);
        refreshDynamicLegend();
        snapLogRangeToDecades(pDiv);
        // Restore CI state if we have probabilistic data and it was previously checked
        if (hasProbabilistic && wasCIChecked) {
          const ciCheckboxNew = getElement('showCI');
          if (ciCheckboxNew) {
            ciCheckboxNew.checked = true;
            toggleShowCI();
          }
        }
        if (hasSDOM && wasSDOMChecked) {
          const sdomCheckboxNew = getElement('showSDOM');
          if (sdomCheckboxNew) {
            sdomCheckboxNew.checked = true;
            toggleShowSDOM();
          }
        }
        const _iterInput = getElement('showIterNum');
        if (_iterInput && _iterInput.value && parseInt(_iterInput.value, 10) >= 1) {
          toggleShowIteration();
        }
        hideChartLoading(container);
      });
  } else {
    hideChart();
  }
}

/**
 * Create a Plotly chart for a radionuclides data group.
 * Plots all child datasets (isotopes) with predefined line styles.
 * 
 * Features:
 * - Each isotope uses its characteristic color and dash pattern
 * - "Show Total" checkbox adds a summed trace
 * - Supports multi-file comparison with thinner lines for secondary files
 * 
 * @param {string} path - HDF5 path to the radionuclides group
 * @returns {void}
 */
function isVisibleGroupEndpoint(name) {
  return !(typeof name === 'string' && name.startsWith('_'));
}

function normalizeBackgroundLabel(name) {
  return String(name || '').replace(/^_+|_+$/g, '') || String(name || '');
}

function getBackgroundSourceLabel(dataset, datasetKey) {
  const attrName = getAttr(dataset, 'name') ?? getAttr(dataset, 'Name');
  if (attrName !== undefined && attrName !== null && String(attrName).trim() !== '') {
    return String(attrName).trim();
  }
  return normalizeBackgroundLabel(datasetKey);
}

function parseIndexNames(indexAttr) {
  if (indexAttr === undefined || indexAttr === null) return [];
  if (Array.isArray(indexAttr) || ArrayBuffer.isView(indexAttr)) {
    return Array.from(indexAttr).map(v => String(v).trim()).filter(Boolean);
  }
  if (typeof indexAttr === 'object' && typeof indexAttr.length === 'number') {
    try {
      return Array.from(indexAttr).map(v => String(v).trim()).filter(Boolean);
    } catch (_) { ignoreFailure('parseIndexNames', _); }
  }
  if (typeof indexAttr === 'string') {
    const s = indexAttr.trim();
    if (!s) return [];
    try {
      const parsed = JSON.parse(s);
      if (Array.isArray(parsed)) {
        return parsed.map(v => String(v).trim()).filter(Boolean);
      }
    } catch (_) { ignoreFailure('parseIndexNames', _); }
    return s.split(/[;,]/).map(v => v.trim()).filter(Boolean);
  }
  return [String(indexAttr).trim()].filter(Boolean);
}

function resolveIndexCategoryName(rawValue, indexNames) {
  const strVal = String(rawValue).trim();
  if (!strVal) return null;
  if (indexNames.includes(strVal)) return strVal;
  const asNumber = Number(strVal);
  if (isFinite(asNumber)) {
    const idx0 = Math.floor(asNumber);
    if (idx0 >= 0 && idx0 < indexNames.length) return indexNames[idx0];
    if (idx0 >= 1 && idx0 <= indexNames.length) return indexNames[idx0 - 1];
  }
  return null;
}

function rgbaFromRgbString(rgb, alpha) {
  if (!rgb || typeof rgb !== 'string') return null;
  const m = rgb.match(/rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)/i);
  if (!m) return null;
  return `rgba(${m[1]},${m[2]},${m[3]},${alpha})`;
}

function getCategoryFillColor(name) {
  const named = getNamedColor(name);
  if (named) {
    return rgbaFromRgbString(named, 0.24) || 'rgba(120,120,120,0.24)';
  }
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = ((hash << 5) - hash) + name.charCodeAt(i);
    hash |= 0;
  }
  const hue = Math.abs(hash) % 360;
  return `hsla(${hue}, 60%, 55%, 0.24)`;
}

function readDatasetNumericVector(dataset) {
  let raw;
  if (typeof dataset.value !== 'undefined') raw = dataset.value;
  else if (typeof dataset.toArray === 'function') raw = dataset.toArray();
  if (raw == null) return null;
  const normalized = PDFSampler.normalizeDataArray(raw);
  const arr = Array.isArray(normalized)
    ? normalized
    : (ArrayBuffer.isView(normalized) ? Array.from(normalized) : null);
  if (!arr || !arr.length) return null;
  const flat = arr.map(pt => Array.isArray(pt) ? pt[0] : (ArrayBuffer.isView(pt) ? pt[0] : pt));
  const nums = flat.map(Number);
  return nums.every(isFinite) ? nums : null;
}

function hasDataTimeBackground(dataset) {
  const indexArr = parseIndexNames(getAttr(dataset, 'Index'));
  if (!indexArr.length) return false;
  const dataArr = readDatasetNumericVector(dataset);
  return dataArr !== null && dataArr.length === indexArr.length;
}

function collectDataTimeSegments(dataset, sourcePath) {
  const timeArr = readDatasetNumericVector(dataset);
  const categoryNames = parseIndexNames(getAttr(dataset, 'Index'));
  if (!timeArr || !categoryNames.length || timeArr.length !== categoryNames.length) return [];
  const segments = [];
  for (let i = 0; i < timeArr.length; i++) {
    const x0 = i === 0 ? 0 : timeArr[i - 1];
    const x1 = timeArr[i];
    if (!isFinite(x0) || !isFinite(x1) || x1 < x0) continue;
    const category = categoryNames[i];
    if (!category) continue;
    segments.push({ x0, x1, category, color: getCategoryFillColor(category), source: sourcePath });
  }
  return segments;
}

function addBackgroundSourcesFromGroup(file, groupPath, list, seenValues) {
  const sourceGroup = FileService.get(file, groupPath);
  if (!sourceGroup || String(sourceGroup.type).toLowerCase() !== 'group' || typeof sourceGroup.keys !== 'function') {
    return;
  }
  let keys = [];
  try {
    keys = Array.from(sourceGroup.keys()).filter(k => typeof k === 'string' && k.startsWith('_'));
  } catch (_) {
    return;
  }
  for (const key of keys) {
    const sourcePath = `${groupPath}/${key}`.replace(/\/+/g, '/');
    if (seenValues.has(sourcePath)) continue;
    const dataset = FileService.get(file, sourcePath);
    if (!dataset || String(dataset.type).toLowerCase() !== 'dataset') continue;
    const isTimeDep = isTimeDependent(dataset);
    const hasDataTime = !isTimeDep && hasDataTimeBackground(dataset);
    if (!isTimeDep && !hasDataTime) continue;
    if (!parseIndexNames(getAttr(dataset, 'Index')).length) continue;
    let label = getBackgroundSourceLabel(dataset, key);
    if (list.some(item => item.label === label)) {
      label = groupPath.endsWith('/IndexLists') ? `${label} (IndexLists)` : `${label} (${normalizeBackgroundLabel(key)})`;
    }
    list.push({ value: sourcePath, label });
    seenValues.add(sourcePath);
  }
}

function collectBackgroundSourceOptions(file, group, groupPath) {
  const options = [{ value: '__none__', label: 'No background' }];
  const seenValues = new Set(['__none__']);
  addBackgroundSourcesFromGroup(file, groupPath, options, seenValues);
  addBackgroundSourcesFromGroup(file, `${groupPath}/IndexLists`, options, seenValues);
  addBackgroundSourcesFromGroup(file, '/IndexLists', options, seenValues);
  return options;
}

function collectIndexBackgroundSegments(file, sourcePath, timeData) {
  if (!file || !sourcePath || sourcePath === '__none__' || !Array.isArray(timeData) || timeData.length < 2) {
    return [];
  }
  const dataset = FileService.get(file, sourcePath);
  if (!dataset || String(dataset.type).toLowerCase() !== 'dataset') {
    return [];
  }
  if (!isTimeDependent(dataset)) {
    if (!hasDataTimeBackground(dataset)) return [];
    return collectDataTimeSegments(dataset, sourcePath);
  }
  const indexNames = parseIndexNames(getAttr(dataset, 'Index'));
  if (!indexNames.length) return [];
  let raw;
  if (typeof dataset.value !== 'undefined') raw = dataset.value;
  else if (typeof dataset.toArray === 'function') raw = dataset.toArray();
  if (!raw) return [];
  const normalized = PDFSampler.normalizeDataArray(raw);
  const series = Array.isArray(normalized)
    ? normalized
    : (ArrayBuffer.isView(normalized) ? Array.from(normalized) : null);
  if (!series || !series.length) return [];
  const n = Math.min(timeData.length, series.length);
  if (n < 2) return [];
  const labels = [];
  for (let i = 0; i < n; i++) {
    const point = series[i];
    const v = Array.isArray(point) ? point[0] : (ArrayBuffer.isView(point) ? point[0] : point);
    labels.push(resolveIndexCategoryName(v, indexNames));
  }
  const segments = [];
  let start = 0;
  for (let i = 1; i <= n; i++) {
    const changed = i === n || labels[i] !== labels[start];
    if (!changed) continue;
    const category = labels[start];
    if (category) {
      const x0 = timeData[start];
      const x1 = timeData[Math.min(i, n - 1)];
      if (x0 !== undefined && x1 !== undefined && x1 >= x0) {
        segments.push({ x0, x1, category, color: getCategoryFillColor(category), source: sourcePath });
      }
    }
    start = i;
  }
  return segments;
}

/**
 * Convert probabilistic raw data into per-timestep realization arrays.
 * Returns null when the shape is not probabilistic.
 *
 * Hoisted out of createRadionuclidesChart, where it was a nested function. It
 * closes over nothing, so nesting it only kept it out of reach.
 *
 * @param {Array} rawData
 * @param {Array} timeData
 * @param {number} stride
 * @returns {Array<Array<number>>|null}
 */
function toProbabilisticTimeSlices(rawData, timeData, stride) {
  if (!Array.isArray(rawData) || !timeData || timeData.length === 0) {
    return null;
  }
  if (Array.isArray(rawData[0])) {
    return rawData.slice(0, timeData.length).map(timeSlice => {
      if (!Array.isArray(timeSlice)) return [PDFSampler.toNumber(timeSlice)];
      return timeSlice.map(PDFSampler.toNumber);
    });
  }
  const flatStride = resolveStride(rawData.length, timeData.length, stride);
  if (flatStride) {
    const numRealizations = flatStride;
    const timeSlices = [];
    for (let t = 0; t < timeData.length; t++) {
      const values = [];
      for (let r = 0; r < numRealizations; r++) {
        values.push(PDFSampler.toNumber(rawData[t * numRealizations + r]));
      }
      timeSlices.push(values);
    }
    return timeSlices;
  }
  return null;
}

/**
 * Build one radionuclide's y-series for one file.
 *
 * Split out of createRadionuclidesChart's per-dataset loop. This is the half
 * that decides what the numbers are: which of the probabilistic-time, column-
 * statistics, probabilistic and SDOM paths applies, and what the series looks
 * like once trimmed to the shorter of time and value.
 *
 * sawProbabilistic and sawSDOM report what this dataset turned out to be, for
 * the caller to fold into the flags that decide which controls to show.
 *
 * @returns {Object|null} null when the dataset holds no readable values
 */
function computeRadionuclideSeries({ dataset, datasetKey, path, probTimeForFile, effectiveTimeData, nIter }) {
  let yData;
  if (typeof dataset.value !== 'undefined') {
    yData = dataset.value;
  } else if (typeof dataset.toArray === 'function') {
    yData = dataset.toArray();
  }
  if (!yData) return null;

  /* Boxed copy only for the statistics paths; see createPlotlyChart. */
  const normalizedRawData = probTimeForFile ? null : PDFSampler.normalizeDataArray(yData);
  let yArray = normalizedRawData;
  let isProbabilistic = false;
  let ciFromColumns = null;
  let sdomInfo = null;
  let sawProbabilistic = false;
  let sawSDOM = false;

  // ── Probabilistic time: extract the selected iteration's y values ──
  // Y-data layout: flat[t_i * maxLen + k] = y at time step t_i for iteration k.
  if (probTimeForFile) {
    const { iterIdx, maxLen, effectiveTimeData: ptTimeData } = probTimeForFile;
    const iterLen = ptTimeData.length;
    yArray = [];
    for (let t = 0; t < iterLen; t++) {
      yArray.push(PDFSampler.toNumber(yData[t * maxLen + iterIdx]));
    }
  } else {
    // ── Regular (non prob-time) path ─────────────────────────────────
    const colStats = getColumnStatisticsSeries(dataset, normalizedRawData, effectiveTimeData);
    if (colStats && Array.isArray(colStats.meanSeries)) {
      yArray = colStats.meanSeries;
      if (Array.isArray(colStats.p5Series) && Array.isArray(colStats.p95Series)) {
        sawProbabilistic = true;
        ciFromColumns = { p5: colStats.p5Series, p95: colStats.p95Series };
      }
      if (nIter && nIter > 1 && Array.isArray(colStats.sigmaSeries)) {
        const sqrtN = Math.sqrt(nIter);
        sdomInfo = {
          meanSeries: colStats.meanSeries,
          lower: colStats.meanSeries.map((mean, idx) => {
            const sigma = colStats.sigmaSeries[idx];
            if (mean === null || sigma === null) return null;
            const sdom = PDFSampler.toNumber(sigma) / sqrtN;
            return isFinite(sdom) ? mean - sdom : null;
          }),
          upper: colStats.meanSeries.map((mean, idx) => {
            const sigma = colStats.sigmaSeries[idx];
            if (mean === null || sigma === null) return null;
            const sdom = PDFSampler.toNumber(sigma) / sqrtN;
            return isFinite(sdom) ? mean + sdom : null;
          })
        };
        sawSDOM = true;
      }
    }
    // Handle probabilistic data
    if (!colStats && checkIsProbabilistic(dataset)) {
      isProbabilistic = true;
      sawProbabilistic = true;
      yArray = computeProbabilisticMean(yArray, effectiveTimeData, getRealizationStride(dataset, normalizedRawData.length, effectiveTimeData.length, `${path}/${datasetKey}`));
    }
    if (!isProbabilistic) {
      sdomInfo = sdomInfo || getDatasetAttributeSDOM(dataset, effectiveTimeData, nIter);
      if (sdomInfo && Array.isArray(sdomInfo.meanSeries)) {
        yArray = sdomInfo.meanSeries;
        sawSDOM = true;
      }
    } else if (nIter && nIter > 1) {
      sawSDOM = true;
    }
  }

  const minLength = Math.min(effectiveTimeData.length, yArray.length);
  return {
    normalizedRawData,
    minLength,
    trimmedTimeData: effectiveTimeData.slice(0, minLength),
    trimmedYData: yArray.slice(0, minLength),
    isProbabilistic,
    ciFromColumns,
    sdomInfo,
    sawProbabilistic,
    sawSDOM
  };
}

/**
 * Fold one dataset's series into the running per-file total.
 *
 * Mutates totalDataByFile, which is how the original loop worked: the total is
 * accumulated dataset by dataset rather than summed at the end, and the
 * probabilistic branch depends on this dataset's array already having been
 * pushed. Call it before building the trace, as the loop always did.
 */
function accumulateRadionuclideTotal({ totalDataByFile, fileKey, nIter, series, dataset, datasetKey, path, effectiveTimeData }) {
  const { trimmedTimeData, trimmedYData, normalizedRawData, isProbabilistic } = series;
  if (!totalDataByFile[fileKey]) {
    totalDataByFile[fileKey] = {
      timeData: trimmedTimeData,
      dataArrays: [],
      probabilisticSlices: null,
      nIter
    };
  }
  totalDataByFile[fileKey].dataArrays.push(trimmedYData);
  if (isProbabilistic) {
    const datasetSlices = toProbabilisticTimeSlices(normalizedRawData, trimmedTimeData,
      getRealizationStride(dataset, normalizedRawData.length, effectiveTimeData.length, `${path}/${datasetKey}`));
    if (datasetSlices) {
      if (!totalDataByFile[fileKey].probabilisticSlices) {
        totalDataByFile[fileKey].probabilisticSlices = datasetSlices.map((values, idx) => {
          const deterministicBase = totalDataByFile[fileKey].dataArrays.length > 1
            ? totalDataByFile[fileKey].dataArrays
                .slice(0, totalDataByFile[fileKey].dataArrays.length - 1)
                .reduce((sum, arr) => sum + (arr[idx] || 0), 0)
            : 0;
          return values.map(v => v + deterministicBase);
        });
      } else {
        const totalSlices = totalDataByFile[fileKey].probabilisticSlices;
        const compatible = totalSlices.length === datasetSlices.length
          && totalSlices.every((values, idx) => values.length === datasetSlices[idx].length);
        if (compatible) {
          for (let t = 0; t < totalSlices.length; t++) {
            for (let r = 0; r < totalSlices[t].length; r++) {
              totalSlices[t][r] += datasetSlices[t][r];
            }
          }
        } else {
          totalDataByFile[fileKey].probabilisticSlices = null;
        }
      }
    }
  } else if (totalDataByFile[fileKey].probabilisticSlices) {
    const totalSlices = totalDataByFile[fileKey].probabilisticSlices;
    for (let t = 0; t < Math.min(totalSlices.length, trimmedYData.length); t++) {
      for (let r = 0; r < totalSlices[t].length; r++) {
        totalSlices[t][r] += trimmedYData[t];
      }
    }
  }
}

/**
 * Turn a computed series into the Plotly trace.
 *
 * The underscore-prefixed fields are read back later by the CI, SDOM and
 * iteration toggles, which recompute bands from the raw data rather than
 * asking the file again.
 */
function buildRadionuclideTrace({ series, dataset, datasetKey, path, fileKey, enabledFiles, nIter, effectiveTimeData }) {
  const { trimmedTimeData, trimmedYData, normalizedRawData, minLength,
          isProbabilistic, ciFromColumns, sdomInfo } = series;

  // Get line style for this radionuclide
  const lineStyle = getLineStyle(datasetKey);
  let traceName = datasetKey;
  let lineWidth = lineStyle.width;
  if (enabledFiles.length > 1 && enabledFiles.indexOf(fileKey) > 0) {
    traceName = `${datasetKey} (${filenameDiff(enabledFiles[0], fileKey)})`;
    lineWidth = lineWidth / 2;
  }
  const traceObj = ChartService.timeSeriesTrace({ x: trimmedTimeData, y: trimmedYData, name: traceName, line: { color: lineStyle.color, dash: lineStyle.dash, width: lineWidth }, _datasetKey: datasetKey });
  traceObj._isProbabilistic = isProbabilistic || !!ciFromColumns;
  if (isProbabilistic) {
    // Store raw data and time data on the trace for CI computation
    traceObj._rawData = normalizedRawData;
    traceObj._timeData = trimmedTimeData;
    traceObj._numRealizations = getRealizationStride(dataset, normalizedRawData.length, effectiveTimeData.length, `${path}/${datasetKey}`);
    if (nIter && nIter > 1) {
      traceObj._nIter = nIter;
    }
  } else if (ciFromColumns) {
    traceObj._ciP5 = ciFromColumns.p5.slice(0, minLength);
    traceObj._ciP95 = ciFromColumns.p95.slice(0, minLength);
    traceObj._timeData = trimmedTimeData;
  }
  if (sdomInfo) {
    traceObj._sdomLower = sdomInfo.lower.slice(0, minLength);
    traceObj._sdomUpper = sdomInfo.upper.slice(0, minLength);
    traceObj._timeData = trimmedTimeData;
  }
  return traceObj;
}

/**
 * Format a ratio value to a display string (3 significant digits).
 * @param {number} ratio
 * @returns {string}
 */
function formatRatio(ratio) {
  if (ratio === 0 || !isFinite(ratio)) return ratio.toString();
  return ratio.toPrecision(3);
}


/**
 * Add one "Total" trace per file, at the top of that file's legend group.
 *
 * Split out of createRadionuclidesChart. The total is the sum of every
 * radionuclide already collected for the file, and it is spliced in rather
 * than appended so it sits above the traces it sums. The splices run in
 * reverse file order, so the recorded start index of each earlier group is
 * still valid when its turn comes.
 *
 * Mutates ctx.traces, as the original block did.
 *
 * @param {Object} ctx - see the destructuring below
 * @returns {boolean} whether any total carried enough realizations for SDOM,
 *   for the caller to fold into its own flag
 */
function insertTotalTraces(ctx) {
  const { traces, totalDataByFile, enabledFiles, fileTraceStartIndex, hasTotalSubNode,
          showRatioChecked, primaryFile, secondaryFile } = ctx;
  let sawSDOM = false;
  const showTotalCheckbox = getElement('showTotal');
  if (!hasTotalSubNode && showTotalCheckbox && showTotalCheckbox.checked) {
    // Compute total per file and collect total max values for ratio
    const totalMaxByFile = {}; // { fileKey: maxTotalValue }
    const totalTracesByFile = {}; // { fileKey: traceObject }
    for (const fileKey of Object.keys(totalDataByFile)) {
      const fileData = totalDataByFile[fileKey];
      if (fileData.dataArrays.length > 0) {
        const timeData = fileData.timeData;
        const totalY = new Array(timeData.length).fill(0);
        
        // Sum all data arrays
        for (const dataArray of fileData.dataArrays) {
          for (let i = 0; i < Math.min(dataArray.length, totalY.length); i++) {
            totalY[i] += dataArray[i];
          }
        }
        
        totalMaxByFile[fileKey] = totalY.reduce((m, v) => v > m ? v : m, -Infinity);

        let traceName = 'Total';
        let lineWidth = 2;
        
        if (enabledFiles.length > 1 && enabledFiles.indexOf(fileKey) > 0) {
          traceName = `Total (${filenameDiff(enabledFiles[0], fileKey)})`;
          lineWidth = 1;
        }
        
        totalTracesByFile[fileKey] = {
          x: timeData,
          y: totalY,
          mode: 'lines',
          name: traceName,
          line: {
            color: '#000000',
            dash: 'solid',
            width: lineWidth
          },
          type: 'scatter',
          _datasetKey: '__total__'
        };

        if (fileData.probabilisticSlices) {
          totalTracesByFile[fileKey]._isProbabilistic = true;
          totalTracesByFile[fileKey]._rawData = fileData.probabilisticSlices;
          totalTracesByFile[fileKey]._timeData = timeData;
          if (fileData.nIter && fileData.nIter > 1) {
            totalTracesByFile[fileKey]._nIter = fileData.nIter;
            sawSDOM = true;
          }
        }
      }
    }

    // If Show Ratio is checked, append ratio to the primary Total trace name
    if (showRatioChecked && secondaryFile) {
      const t = totalTracesByFile[primaryFile];
      if (t && t.name === 'Total') {
        const maxPrimary = totalMaxByFile[primaryFile];
        const maxSecondary = totalMaxByFile[secondaryFile];
        if (maxSecondary != null && maxSecondary !== 0) {
          t.name = `Total (${formatRatio(maxPrimary / maxSecondary)})`;
        } else if (maxSecondary === 0 && maxPrimary > 0) {
          t.name = `Total (∞)`;
        }
      }
    }

    // Insert each total trace at the beginning of its file's group.
    // Process files in reverse order so earlier splice positions stay valid.
    const filesWithTotals = enabledFiles.filter(fk => totalTracesByFile[fk]);
    for (let i = filesWithTotals.length - 1; i >= 0; i--) {
      const fk = filesWithTotals[i];
      const insertIdx = fileTraceStartIndex[fk] != null ? fileTraceStartIndex[fk] : traces.length;
      traces.splice(insertIdx, 0, totalTracesByFile[fk]);
    }
  }
  return sawSDOM;
}

async function createRadionuclidesChart(path, savedAxisState) {
  if (!_axesLocked) resetPresetDropdown();
  const plotDiv = getElement('plotlyChart');
  const chartContainer = getElement('plotlyChartContainer');
  showChartLoading(chartContainer);
  let wasCIChecked = false;
  let wasSDOMChecked = false;
  let backgroundSourceValue = selectedBackgroundOverlaySource || '__none__';
  try {
    const ciCheckbox = getElement('showCI');
    if (ciCheckbox) {
      wasCIChecked = !!ciCheckbox.checked;
    }
    const sdomCheckbox = getElement('showSDOM');
    if (sdomCheckbox) {
      wasSDOMChecked = !!sdomCheckbox.checked;
    }
    const backgroundSelect = getElement('backgroundSourceSelect');
    if (backgroundSelect && backgroundSelect.value) {
      backgroundSourceValue = backgroundSelect.value;
    }
  } catch (e) { ignoreFailure('createRadionuclidesChart', e); }
  try {
  if (plotDiv) plotDiv.innerHTML = '';
  // Yield to browser for immediate UI update before heavy processing (cross-browser)
  await new Promise(requestAnimationFrame);
  await new Promise(resolve => setTimeout(resolve, 0));
  // Show "Show Total" checkbox for radionuclides groups (suppressed if a "Total" sub-node already exists)
  setShowTotalVisible(true);
  let hasTotalSubNode = false;
  setShowMaxVisible(true);
  setShowCIVisible(false);
  setShowSDOMVisible(false);
  setBackgroundSelectorVisible(false);
  setIterationSelectorVisible(false);
  populateBackgroundSelector([{ value: '__none__', label: 'No background' }], '__none__');
  
  const traces = [];
  const enabledFiles = getEffectiveFiles();

  // Determine the currently-selected iteration index (0-based, default 0)
  const _iterInputEarly = getElement('showIterNum');
  const _selectedIterNum = (_iterInputEarly && _iterInputEarly.value) ? parseInt(_iterInputEarly.value, 10) : 1;
  const _selectedIterIdx = (isFinite(_selectedIterNum) && _selectedIterNum >= 1) ? _selectedIterNum - 1 : 0;

  // Show "Show Ratio" checkbox only when exactly 2 files are enabled (thick + thin lines)
  // and secondary file has data for this path — will be set after building traces
  const hasTwoFiles = enabledFiles.length === 2;
  setShowRatioVisible(false);

  // Store data for computing total
  const totalDataByFile = {};
  const nIterByFile = {};
  let hasProbTime = false;          // any file has probabilistic /time
  let probTimeIterMax = 0;

  // Track the starting index of each file's traces in the traces array
  const fileTraceStartIndex = {};
  
  // Track if any probabilistic data exists
  let hasProbabilistic = false;
  let hasSDOM = false;

  let timeUnit = '';
  let yAxisName = path.split('/').pop();
  let indexBackgroundSegments = [];
  let backgroundSourceOptions = [{ value: '__none__', label: 'No background' }];
  
  if (enabledFiles.length > 0) {
    const firstFile = loadedFiles[enabledFiles[0]];
    timeUnit = getTimeUnit(firstFile);
  }
  
  // Build traces for each file and each radionuclide
  for (const fileKey of enabledFiles) {
    const file = loadedFiles[fileKey];
    if (nIterByFile[fileKey] === undefined) {
      nIterByFile[fileKey] = getRootNIter(file);
    }
    const nIter = nIterByFile[fileKey];
    
    // Record where this file's traces begin
    fileTraceStartIndex[fileKey] = traces.length;
    
    if (!checkDatasetExistsInFile(file, path)) {
      continue;
    }
    
    try {
      const group = FileService.get(file, path);
      if (!group || group.type.toLowerCase() !== 'group') {
        continue;
      }
      
      const timeData = getTimeData(file);
      if (!timeData) {
        kvotWarn(`No /time dataset found in ${fileKey}`);
        continue;
      }

      // Resolve probabilistic time matrix: if /time is a [nIter × maxLen] matrix,
      // extract the selected iteration's time series so all downstream code works
      // with a plain 1-D time array of the correct length.
      let probTimeForFile = null;
      if (checkTimeProbabilistic(file)) {
        const timeMatrix = getProbabilisticTimeMatrix(file);
        if (!timeMatrix) {
          kvotWarn(`Could not read probabilistic time matrix in ${fileKey}`);
          continue;
        }
        hasProbTime = true;
        if (timeMatrix.nIter > probTimeIterMax) probTimeIterMax = timeMatrix.nIter;
        const iterIdx  = Math.min(_selectedIterIdx, timeMatrix.nIter - 1);
        const timeRow  = timeMatrix.matrix[iterIdx];
        const iterLen  = timeMatrix.iterLengths[iterIdx];
        probTimeForFile = {
          effectiveTimeData: timeRow.slice(0, iterLen),
          iterIdx,
          maxLen: timeMatrix.maxLen,
          nIter:  timeMatrix.nIter,
        };
      }
      const effectiveTimeData = probTimeForFile ? probTimeForFile.effectiveTimeData : timeData;

      if (backgroundSourceOptions.length === 1) {
        backgroundSourceOptions = collectBackgroundSourceOptions(file, group, path);
        if (!backgroundSourceOptions.some(option => option.value === backgroundSourceValue)) {
          backgroundSourceValue = '__none__';
        }
        selectedBackgroundOverlaySource = backgroundSourceValue;
        populateBackgroundSelector(backgroundSourceOptions, backgroundSourceValue);
        setBackgroundSelectorVisible(backgroundSourceOptions.length > 1);
      }

      if (!indexBackgroundSegments.length && backgroundSourceValue !== '__none__') {
        indexBackgroundSegments = collectIndexBackgroundSegments(file, backgroundSourceValue, timeData);
      }
      
      let datasetKeys = [];
      try {
        if (typeof group.keys === 'function') {
          datasetKeys = Array.from(group.keys()).filter(isVisibleGroupEndpoint);
        }
      } catch (e) {
        console.error('Error getting dataset keys:', e);
        continue;
      }
      if (datasetKeys.includes('Total')) hasTotalSubNode = true;
      
      for (const datasetKey of datasetKeys) {
        try {
          const dataset = group.get(datasetKey);
          if (!dataset || dataset.type.toLowerCase() !== 'dataset') {
            continue;
          }
          const series = computeRadionuclideSeries({
            dataset, datasetKey, path, probTimeForFile, effectiveTimeData, nIter
          });
          if (series) {
            // Both flags are only ever raised, never cleared, so folding the
            // per-dataset answer in with || matches the original assignments.
            hasProbabilistic = hasProbabilistic || series.sawProbabilistic;
            hasSDOM = hasSDOM || series.sawSDOM;
            accumulateRadionuclideTotal({
              totalDataByFile, fileKey, nIter, series,
              dataset, datasetKey, path, effectiveTimeData
            });
            traces.push(buildRadionuclideTrace({
              series, dataset, datasetKey, path, fileKey, enabledFiles, nIter, effectiveTimeData
            }));
          }
          // Yield to browser for UI update after each dataset
          await Promise.resolve();
        } catch (e) {
          console.error(`Error creating trace for ${datasetKey} in ${fileKey}:`, e);
        }
      }
    } catch (e) {
      console.error(`Error processing group for ${fileKey}:`, e);
    }
  }

  // Hide "Show Total" if a "Total" sub-node already exists in the group
  if (hasTotalSubNode) setShowTotalVisible(false);
  
  // Now that traces are built, show "Show Ratio" only if both files contributed data
  if (hasTwoFiles) {
    const secondaryFile = enabledFiles[1];
    const secondaryStart = fileTraceStartIndex[secondaryFile] != null ? fileTraceStartIndex[secondaryFile] : traces.length;
    const secondaryHasTraces = secondaryStart < traces.length;
    setShowRatioVisible(secondaryHasTraces);
  }

  // Collect max values per radionuclide per file (needed for ratio display)
  const showRatioCheckbox = getElement('showRatio');
  const showRatioChecked = hasTwoFiles && showRatioCheckbox && showRatioCheckbox.checked;

  // Hide "Show Max" when ratio is active
  setShowMaxVisible(!showRatioChecked);
  const maxByFileAndName = {}; // { datasetKey: { fileKey: maxVal } }
  if (showRatioChecked) {
    for (const fileKey of enabledFiles) {
      const fileData = totalDataByFile[fileKey];
      if (!fileData) continue;
      const file = loadedFiles[fileKey];
      const group = FileService.get(file, path);
      let datasetKeys = [];
      try {
        if (typeof group.keys === 'function') {
          datasetKeys = Array.from(group.keys()).filter(isVisibleGroupEndpoint);
        }
      } catch (e) { ignoreFailure('toProbabilisticTimeSlices', e); }
      // Match datasetKeys to dataArrays by index
      for (let i = 0; i < datasetKeys.length && i < fileData.dataArrays.length; i++) {
        const key = datasetKeys[i];
        const arr = fileData.dataArrays[i];
        const maxVal = arr.reduce((m, v) => v > m ? v : m, -Infinity);
        if (!maxByFileAndName[key]) maxByFileAndName[key] = {};
        maxByFileAndName[key][fileKey] = maxVal;
      }
    }
  }

  const primaryFile = enabledFiles[0];
  const secondaryFile = hasTwoFiles ? enabledFiles[1] : null;


  // Add total traces, each at the top of its corresponding file's group in the legend
  if (insertTotalTraces({
    traces, totalDataByFile, enabledFiles, fileTraceStartIndex, hasTotalSubNode,
    showRatioChecked, primaryFile, secondaryFile
  })) hasSDOM = true;

  // Update thick-line trace names with ratio of max values if "Show Ratio" is checked
  if (showRatioChecked) {
    for (const trace of traces) {
      // Thick-line traces are those from the primary file (no fileKey suffix, not Total)
      for (const datasetKey of Object.keys(maxByFileAndName)) {
        if (trace.name === datasetKey) {
          const maxPrimary = maxByFileAndName[datasetKey][primaryFile];
          const maxSecondary = maxByFileAndName[datasetKey][secondaryFile];
          if (maxSecondary != null && maxSecondary !== 0) {
            trace.name = `${datasetKey} (${formatRatio(maxPrimary / maxSecondary)})`;
          } else if (maxSecondary === 0 && maxPrimary > 0) {
            trace.name = `${datasetKey} (∞)`;
          }
          break;
        }
      }
    }
    
    // Hide thin-line (secondary file) traces from legend — keep them visible in chart.
    // Secondary file traces have halved line widths compared to primary ones.
    for (const trace of traces) {
      const w = trace.line && trace.line.width;
      // Thick (primary) traces have width >= 2, thin (secondary) have width < 2
      // Total traces: primary=2, secondary=1. Radionuclide traces: primary=original, secondary=original/2.
      // We keep ratio-annotated traces and primary Total in the legend.
      if (w != null && w < 2) {
        trace.showlegend = false;
        trace._hiddenFromLegend = true; // preserve across dynamic legend updates
      }
    }
  }
  
  renderRadionuclidesChart({
    traces, path, enabledFiles, chartContainer, savedAxisState, hasProbabilistic,
    hasProbTime, hasSDOM, probTimeIterMax, showRatioChecked, backgroundSourceOptions,
    backgroundSourceValue, indexBackgroundSegments, timeUnit, yAxisName,
    wasCIChecked, wasSDOMChecked
  });
  } catch (err) {
    console.error('createRadionuclidesChart failed:', err);
    hideChartLoading(chartContainer);
    setupBackgroundOverlayTooltip(getElement('plotlyChart'), []);
    hideChart();
  }
}

/**
 * Draw the radionuclides chart once its traces exist.
 *
 * Split out of createRadionuclidesChart, which ran to 660 lines. Everything
 * here is presentation: which controls to show for the data that was found,
 * the axis titles, the Plotly call and what to do when there is nothing to
 * draw. Nothing in it decides what the traces are.
 *
 * It takes a context object rather than twenty arguments, which is what the
 * split actually costs - the block reads that many values from the function
 * it used to sit inside.
 *
 * @param {Object} ctx - see the destructuring below for the fields used
 */
function renderRadionuclidesChart(ctx) {
  const {
    traces, path, enabledFiles, chartContainer, savedAxisState, hasProbabilistic,
    hasProbTime, hasSDOM, probTimeIterMax, showRatioChecked, backgroundSourceOptions,
    backgroundSourceValue, indexBackgroundSegments, timeUnit, yAxisName,
    wasCIChecked, wasSDOMChecked
  } = ctx;

  // Written and read only below, from the group's 'unit' attribute. It was a
  // let in the calling function, which never reads it back.
  let yAxisUnit = '';

  // Render chart if we have traces
  if (traces.length > 0) {
    // Show CI / SDOM controls only for regular (non prob-time) probabilistic data
    setShowCIVisible(hasProbabilistic && !hasProbTime);
    setShowSDOMVisible(hasSDOM && !hasProbTime);
    // Iteration selector: prob-time charts always show it
    const _regularIterMax = traces.filter(t => t._numRealizations).reduce((m, t) => Math.max(m, t._numRealizations), 0);
    const _iterMax = hasProbTime ? probTimeIterMax : _regularIterMax;
    setIterationSelectorVisible(_iterMax > 0);
    if (_iterMax > 0) setIterationSelectorMax(_iterMax);
    populateBackgroundSelector(backgroundSourceOptions, backgroundSourceValue);
    setBackgroundSelectorVisible(backgroundSourceOptions.length > 1);
    
    // Annotate legend with max values if "Show Max" is checked and ratio is not active
    if (!showRatioChecked) {
      const showMaxCb = getElement('showMax');
      if (showMaxCb && showMaxCb.checked) {
        annotateTracesWithMax(traces);
      }
    }

    // Get unit from group
    const firstFile = loadedFiles[enabledFiles[0]];
    try {
      const group = firstFile.get(path);
      if (group && group.attrs && typeof group.attrs === 'object') {
        for (const attrName in group.attrs) {
          if (attrName === 'unit') {
            const attrObj = group.attrs[attrName];
            if (attrObj && attrObj.value !== null && typeof attrObj.value !== 'undefined') {
              yAxisUnit = attrObj.value;
            }
          }
        }
      }
    } catch (e) {
      kvotWarn('Could not read unit from group:', e);
    }
    
    const { xScale, yScale } = getChartScales();
    const yAxisTitle = yAxisUnit ? `${yAxisName} (${yAxisUnit})` : yAxisName;
    
    const layout = ChartService.createBaseLayout({
      title: path,
      xAxisTitle: timeUnit ? `Time (${timeUnit})` : 'Time',
      yAxisTitle,
      xScale,
      yScale
    });

    if (indexBackgroundSegments.length) {
      layout.shapes = (layout.shapes || [])
        .concat(backgroundRectShapes(indexBackgroundSegments, traces, xScale));
    }
    
    // Preserve axis ranges when toggling controls (Show Total, Show Ratio)
    applyAxisState(layout, savedAxisState);
    _applyLockedAxes(layout);
    
    renderChart(traces, layout, path, () => {
      // Mark the chart so toggleShowIteration knows this is a prob-time chart
      if (hasProbTime && currentChartData) {
        currentChartData._isProbTimeChart = true;
      }
      if (hasProbabilistic && !hasProbTime && wasCIChecked) {
        const ciCheckbox = getElement('showCI');
        if (ciCheckbox) {
          ciCheckbox.checked = true;
          toggleShowCI();
        }
      }
      if (hasSDOM && !hasProbTime && wasSDOMChecked) {
        const sdomCheckbox = getElement('showSDOM');
        if (sdomCheckbox) {
          sdomCheckbox.checked = true;
          toggleShowSDOM();
        }
      }
      populateBackgroundSelector(backgroundSourceOptions, backgroundSourceValue);
      setBackgroundSelectorVisible(backgroundSourceOptions.length > 1);
      if (!hasProbTime) {
        const _iterInput = getElement('showIterNum');
        if (_iterInput && _iterInput.value && parseInt(_iterInput.value, 10) >= 1) {
          toggleShowIteration();
        }
      }
      setupBackgroundOverlayTooltip(getElement('plotlyChart'), indexBackgroundSegments);
    });
  } else {
    hideChartLoading(chartContainer);
    setupBackgroundOverlayTooltip(getElement('plotlyChart'), []);
    hideChart();
  }
}


/**
 * Get standard Plotly configuration with custom toolbar buttons.
 * Configures the mode bar with:
 * - Copy to clipboard button (PNG export)
 * - Download CSV button (data export)
 * - Download Excel button (xlsx export)
 * - Standard Plotly zoom/pan/reset tools
 * - SVG export configuration
 * 
 * @param {string} filename - Base filename for exported images/data
 * @returns {Object} Plotly config object
 */
function getPlotlyConfig(filename) {
  return {
    displayLogo: false,
    /* some versions of plotly check lowercase name */
    displaylogo: false,
    scrollZoom: true,
    showLink: false,
    plotlyServerURL: "https://chart-studio.plotly.com",
    modeBarButtonsToRemove: ['resetScale2d', 'toImage'],
    modeBarButtonsToAdd: [
      'v1hovermode',
      {
        name: 'Download plot as svg',
        icon: Plotly.Icons.camera,
        click: function(gd) {
          const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
          const origPaper = gd.layout.paper_bgcolor;
          const origPlot  = gd.layout.plot_bgcolor;
          const opts = { format: 'svg', filename: filename, height: 600, width: 800, scale: 1 };
          if (!isDark) {
            Plotly.relayout(gd, { paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)' }).then(function() {
              return Plotly.downloadImage(gd, opts);
            }).then(function() {
              return Plotly.relayout(gd, { paper_bgcolor: origPaper, plot_bgcolor: origPlot });
            });
          } else {
            Plotly.downloadImage(gd, opts);
          }
        }
      },
      {
        name: 'Copy chart to clipboard',
        icon: {
          width: 500,
          height: 600,
          path: 'M224 0c-35.3 0-64 28.7-64 64V288v64 64c0 35.3 28.7 64 64 64H448c35.3 0 64-28.7 64-64V288 160 64c0-35.3-28.7-64-64-64H224zm0 64H448V160H224V64zM160 448c0 17.7-14.3 32-32 32H64c-17.7 0-32-14.3-32-32V384H160v64zm0-96H32V288H160v64zM32 240V176H160v64H32zM160 128V64h32v64H160z'
        },
        click: function(gd) {
          EventBus.emit('toolbar:copy-chart');
        }
      },
      {
        name: 'Download data as CSV',
        icon: {
          width: 512,
          height: 512,
          path: 'M288 32c0-17.7-14.3-32-32-32s-32 14.3-32 32V274.7l-73.4-73.4c-12.5-12.5-32.8-12.5-45.3 0s-12.5 32.8 0 45.3l128 128c12.5 12.5 32.8 12.5 45.3 0l128-128c12.5-12.5 12.5-32.8 0-45.3s-32.8-12.5-45.3 0L288 274.7V32zM64 352c-35.3 0-64 28.7-64 64v32c0 35.3 28.7 64 64 64H448c35.3 0 64-28.7 64-64V416c0-35.3-28.7-64-64-64H346.5l-45.3 45.3c-25 25-65.5 25-90.5 0L165.5 352H64zm368 56a24 24 0 1 1 0 48 24 24 0 1 1 0-48z'
        },
        click: function(gd) {
          EventBus.emit('toolbar:download-csv');
        }
      },
      {
        name: 'Download data and chart in Excel',
        icon: {
          width: 384,
          height: 512,
          path: 'M64 0C28.7 0 0 28.7 0 64V448c0 35.3 28.7 64 64 64H320c35.3 0 64-28.7 64-64V160H256c-17.7 0-32-14.3-32-32V0H64zM256 0V128H384L256 0zM155.7 250.2L192 302.1l36.3-51.9c7.6-10.9 22.6-13.5 33.4-5.9s13.5 22.6 5.9 33.4L221.3 344l46.4 66.2c7.6 10.9 5 25.8-5.9 33.4s-25.8 5-33.4-5.9L192 385.8l-36.3 51.9c-7.6 10.9-22.6 13.5-33.4 5.9s-13.5-22.6-5.9-33.4L162.7 344l-46.4-66.2c-7.6-10.9-5-25.8 5.9-33.4s25.8-5 33.4 5.9z'
        },
        click: function(gd) {
          EventBus.emit('toolbar:download-excel');
        }
      }
    ],
    responsive: true
  };
}
