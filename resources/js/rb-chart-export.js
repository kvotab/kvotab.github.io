/* ==========================================================================
   RB CHART - chart data export to CSV and to Excel
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
 * Export current chart data to a CSV file.
 * Creates a downloadable file with columns: Series, X, Y.
 * Each trace in the chart becomes a series in the CSV.
 * 
 * @returns {void}
 */
function downloadChartData() {
  if (!currentChartData) {
    notifyUser('There is no chart data to download yet.');
    return;
  }
  
  let csv = 'Series,X,Y\n';
  
  for (const trace of currentChartData.traces) {
    const name = trace.name;
    for (let i = 0; i < trace.x.length; i++) {
      csv += `"${name}",${trace.x[i]},${trace.y[i]}\n`;
    }
  }
  
  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `chart_data_${Date.now()}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * Export current chart data to an Excel file (.xlsx).
 * Creates a workbook with two sheets:
 * - "Chart": Contains a native Excel scatter chart with the same look as Plotly
 * - "Data": Contains the chart data with time column and one column per trace
 * 
 * Uses xlsxwrite.js for native Excel chart creation with full feature support.
 * Creates a chart that matches the Plotly chart styling:
 * - Same axis type (log/linear) with proper logarithmic scale support
 * - Same line colors from traces
 * - Same dash patterns (solid, dash, dot, dashdot, longdash)
 * - Gridlines matching the Plotly style
 * - Lines without markers
 * 
 * @returns {Promise<void>}
 */
/**
 * Which traces the Excel export should contain.
 *
 * With Dynamic Legend on, the export follows what the chart is showing: a
 * trace is kept only if at least one of its points falls inside the current
 * axis ranges. With it off, everything not explicitly hidden is exported.
 *
 * Log axes carry their ranges as exponents, hence the Math.pow.
 *
 * @param {Array} plotlyTraces - traces as the chart element currently holds them
 * @param {Object} plotlyLayout - the live layout, for ranges and axis types
 * @param {boolean} isDynamicLegendEnabled
 * @returns {Array}
 */
function tracesForExcelExport(plotlyTraces, plotlyLayout, isDynamicLegendEnabled) {
  if (!isDynamicLegendEnabled || !plotlyLayout.xaxis || !plotlyLayout.yaxis) {
    // Dynamic Legend off - export all traces (or filter by visible property)
    return plotlyTraces.filter(trace => {
      const visible = trace.visible;
      return visible === undefined || visible === true;
    });
  }
  const xRange = plotlyLayout.xaxis.range;
  const yRange = plotlyLayout.yaxis.range;
  if (!xRange || !yRange) return plotlyTraces;

  const xIsLog = plotlyLayout.xaxis.type === 'log';
  const yIsLog = plotlyLayout.yaxis.type === 'log';
  const xMin = xIsLog ? Math.pow(10, xRange[0]) : xRange[0];
  const xMax = xIsLog ? Math.pow(10, xRange[1]) : xRange[1];
  const yMin = yIsLog ? Math.pow(10, yRange[0]) : yRange[0];
  const yMax = yIsLog ? Math.pow(10, yRange[1]) : yRange[1];

  return plotlyTraces.filter(trace => {
    // Check if trace has any data points in the current viewport
    for (let j = 0; j < trace.x.length; j++) {
      const x = trace.x[j];
      const y = trace.y[j];
      if (x !== null && x !== undefined && y !== null && y !== undefined) {
        if (x >= xMin && x <= xMax && y >= yMin && y <= yMax) {
          return true;
        }
      }
    }
    return false;
  });
}

// Helper function to parse rgb color string to [R, G, B] array
function parseRgbColor(colorStr) {
  if (!colorStr) return null;
  // Handle rgb(r,g,b) format
  const rgbMatch = colorStr.match(/rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)/i);
  if (rgbMatch) {
    return [parseInt(rgbMatch[1]), parseInt(rgbMatch[2]), parseInt(rgbMatch[3])];
  }
  // Handle hex format #RRGGBB or RRGGBB
  const hexMatch = colorStr.match(/#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i);
  if (hexMatch) {
    return [parseInt(hexMatch[1], 16), parseInt(hexMatch[2], 16), parseInt(hexMatch[3], 16)];
  }
  // Handle short hex format #RGB
  const shortHexMatch = colorStr.match(/^#?([a-f\d])([a-f\d])([a-f\d])$/i);
  if (shortHexMatch) {
    return [
      parseInt(shortHexMatch[1] + shortHexMatch[1], 16),
      parseInt(shortHexMatch[2] + shortHexMatch[2], 16),
      parseInt(shortHexMatch[3] + shortHexMatch[3], 16)
    ];
  }
  return null;
}

// Map Plotly dash type to Excel dash type (using sys variants for standard Excel look)
function mapDashType(plotlyDash) {
  if (!plotlyDash || plotlyDash === 'solid') return 'solid';
  switch (plotlyDash) {
    case 'dash': return 'sysDash';
    case 'dot': return 'sysDot';
    case 'dashdot': return 'sysDashDot';
    case 'longdash': return 'lgDash';
    case 'longdashdot': return 'lgDashDot';
    default: return 'solid';
  }
}

async function downloadChartDataAsExcel() {
  if (!currentChartData) {
    notifyUser('There is no chart data to export yet.');
    return;
  }
  
  // Check if xlsxwrite.js is ready
  if (!window.xlsxReady || !window.XlsxWriter) {
    reportFailure('downloadChartDataAsExcel', new Error('xlsxwrite.js did not load'),
      { userMessage: 'The Excel export library is not loaded. Reload the page and try again' });
    return;
  }
  
  try {
    const allTraces = currentChartData.traces;
    const layout = currentChartData.layout;
    
    // Get current state from the actual Plotly chart element
    const chartDiv = document.getElementById('plotlyChart');
    const plotlyTraces = chartDiv && chartDiv.data ? chartDiv.data : allTraces;
    const plotlyLayout = chartDiv && chartDiv.layout ? chartDiv.layout : layout;
    
    // Check if Dynamic Legend is enabled and we should filter by viewport
    const dynamicLegendCheckbox = document.getElementById('dynamicLegend');
    const isDynamicLegendEnabled = dynamicLegendCheckbox && dynamicLegendCheckbox.checked;
    
    const traces = tracesForExcelExport(plotlyTraces, plotlyLayout, isDynamicLegendEnabled);
    
    if (traces.length === 0) {
      notifyUser('Every trace is hidden. Show at least one before exporting.');
      return;
    }
    
    // Find the longest x array to determine row count
    const maxLength = Math.max(...traces.map(t => t.x ? t.x.length : 0));
    
    // Extract chart metadata
    const chartTitle = layout && layout.title && layout.title.text 
      ? layout.title.text 
      : 'Chart Data';
    const xAxisTitle = layout && layout.xaxis && layout.xaxis.title && layout.xaxis.title.text
      ? layout.xaxis.title.text
      : 'Time';
    const yAxisTitle = layout && layout.yaxis && layout.yaxis.title && layout.yaxis.title.text
      ? layout.yaxis.title.text
      : 'Value';
    
    // Detect axis types from Plotly layout
    const xAxisType = plotlyLayout && plotlyLayout.xaxis && plotlyLayout.xaxis.type ? plotlyLayout.xaxis.type : 'linear';
    const yAxisType = plotlyLayout && plotlyLayout.yaxis && plotlyLayout.yaxis.type ? plotlyLayout.yaxis.type : 'linear';
    
    // Fallback Plotly-like color palette (brighter colors)
    const plotlyColors = [
      [0x1F, 0x77, 0xB4], // blue
      [0xFF, 0x7F, 0x0E], // orange
      [0x2C, 0xA0, 0x2C], // green
      [0xD6, 0x27, 0x28], // red
      [0x94, 0x67, 0xBD], // purple
      [0x8C, 0x56, 0x4B], // brown
      [0xE3, 0x77, 0xC2], // pink
      [0x7F, 0x7F, 0x7F], // gray
      [0xBC, 0xBD, 0x22], // olive
      [0x17, 0xBE, 0xCF]  // cyan
    ];
    
    // Create workbook using xlsxwrite.js
    const xlsx = new XlsxWriter();
    
    // Plotly-like gridline color (light gray)
    const gridColor = 'E5ECF6';
    const minorGridColor = 'EEF2F8';
    
    // ============ CREATE CHART ============
    // Configure chart with axis settings
    const chartConfig = {
      width: 800,
      height: 500,
      scatterStyle: 'line',  // Line without markers
      showBorder: false,     // Remove chart border
      xAxis: {
        title: { text: xAxisTitle },
        numberFormat: '[>1000]### ### ### ##0;General',
        fontSize: 9,
        majorGridlines: { color: gridColor, width: 0.75 }
      },
      yAxis: {
        title: { text: yAxisTitle, customAngle: -90 },
        numberFormat: '0E+0',
        fontSize: 9,
        majorGridlines: { color: gridColor, width: 0.75 }
      },
      legend: { position: 'r', fontSize: 8 }
    };
    
    // Set logarithmic scale if Plotly uses it, and add minor gridlines/ticks
    if (xAxisType === 'log') {
      chartConfig.xAxis.logBase = 10;
      chartConfig.xAxis.minorGridlines = { color: minorGridColor, width: 0.5 };
      chartConfig.xAxis.minorTickMark = 'out';
    }
    if (yAxisType === 'log') {
      chartConfig.yAxis.logBase = 10;
      chartConfig.yAxis.minorGridlines = { color: minorGridColor, width: 0.5 };
      chartConfig.yAxis.minorTickMark = 'out';
    }
    
    // Set axis min/max to match current Plotly view
    // For log scale: always set limits (needed for proper scaling)
    // For linear scale: only set limits if user has zoomed (autorange is false)
    if (plotlyLayout.xaxis && plotlyLayout.xaxis.range) {
      const xRange = plotlyLayout.xaxis.range;
      const xIsLog = xAxisType === 'log';
      const xIsZoomed = plotlyLayout.xaxis.autorange === false;
      if (xIsLog || xIsZoomed) {
        chartConfig.xAxis.minimum = xIsLog ? Math.pow(10, xRange[0]) : xRange[0];
        chartConfig.xAxis.maximum = xIsLog ? Math.pow(10, xRange[1]) : xRange[1];
      }
    }
    if (plotlyLayout.yaxis && plotlyLayout.yaxis.range) {
      const yRange = plotlyLayout.yaxis.range;
      const yIsLog = yAxisType === 'log';
      const yIsZoomed = plotlyLayout.yaxis.autorange === false;
      if (yIsLog || yIsZoomed) {
        chartConfig.yAxis.minimum = yIsLog ? Math.pow(10, yRange[0]) : yRange[0];
        chartConfig.yAxis.maximum = yIsLog ? Math.pow(10, yRange[1]) : yRange[1];
      }
    }
    
    const chart = xlsx.newChart(chartConfig);
    
    // Get x values from the first trace
    const xValues = traces.length > 0 && traces[0].x ? traces[0].x : [];
    
    // Add series to chart
    traces.forEach((trace, idx) => {
      // Get color from trace or use fallback
      let color = plotlyColors[idx % plotlyColors.length];
      const traceColor = trace.line?.color || trace.marker?.color || null;
      if (traceColor) {
        const parsedColor = parseRgbColor(traceColor);
        if (parsedColor) {
          color = parsedColor;
        }
      }
      
      // Get dash type from trace
      const dashType = mapDashType(trace.line?.dash);
      
      // Get line width from trace (default to 2 if not specified)
      const lineWidth = trace.line?.width || 2;
      
      // Filter out null/undefined values
      const yVals = trace.y || [];
      const xVals = trace.x || xValues;
      
      // Create series with xlsxwrite.js
      const series = xlsx.newSeries({
        name: { text: trace.name || `Series ${idx + 1}` },
        x: { values: xVals.map(v => v === null || v === undefined ? NaN : v) },
        y: { values: yVals.map(v => v === null || v === undefined ? NaN : v) },
        length: Math.max(xVals.length, yVals.length),
        line: {
          color: { option: 'Solid', value: color },
          width: lineWidth,
          dashType: dashType,
          capType: 'rnd',
          compoundType: 'sng',
          joinType: 'round',
          beginType: 'none',
          endType: 'none'
        },
        marker: { option: 'NoMarker' }
      });
      
      chart.series.push(series);
    });
    
    // ============ PREPARE DATA ============
    // Build data array with headers
    const headers = ['Time', ...traces.map((t, i) => t.name || `Series ${i + 1}`)];
    const dataRows = [];
    
    for (let i = 0; i < maxLength; i++) {
      const row = [xValues[i] !== undefined ? xValues[i] : null];
      traces.forEach(trace => {
        row.push(trace.y && trace.y[i] !== undefined ? trace.y[i] : null);
      });
      dataRows.push(row);
    }
    
    // Position chart to the right of the data (after all data columns)
    chart.x = (traces.length + 2) * 64;  // Offset by number of columns + margin
    chart.y = 0;
    
    // Write Data sheet with both data AND chart
    xlsx.writeData([headers, ...dataRows], 'Data', { chart: chart });
    
    // Generate filename
    const safeTitle = chartTitle.replace(/[^a-z0-9]/gi, '_').substring(0, 50);
    const filename = `${safeTitle}_${Date.now()}.xlsx`;
    
    // Save and download the file
    await xlsx.saveAs(filename);
    
  } catch (err) {
    reportFailure('downloadChartDataAsExcel', err, { userMessage: 'The Excel export failed' });
  }
}
