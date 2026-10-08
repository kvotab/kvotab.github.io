/* ==========================================================================
   RB CHART - chart data export to CSV
   --------------------------------------------------------------------------
   Split out of rb-chart.js, which had grown past 3 600 lines. These are plain
   scripts sharing globals, not ES modules, so the load order in rb.html is the
   order this code was in before the split, and has to stay that way:

     rb-chart-axes.js  ->  rb-chart-presets.js  ->  rb-chart-export.js
     ->  rb-chart-excel.js  ->  rb-chart-toggles.js  ->  rb-chart.js

   The Excel export, which is a chart of its own, is in rb-chart-excel.js.

   Nothing here runs at load time; the files hold declarations only. Functions
   call across files freely, since every call happens after all six have
   loaded.
   ========================================================================== */

'use strict';   // see the script manifest in rb.html for why
/**
 * Export current chart data to a CSV file.
 * Creates a downloadable file with columns: Series, X, Y.
 * Each trace in the chart becomes a series in the CSV.
 *
 * The values are in the file's units, whatever prefix the axes show them
 * with (changeAxisPrefix): a CSV says nothing of units, so it holds the
 * numbers the file does.
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
    const name = trace._exportName || trace.name;
    const x = '_fileX' in trace ? trace._fileX : trace.x;
    const y = '_fileY' in trace ? trace._fileY : trace.y;
    for (let i = 0; i < x.length; i++) {
      csv += `"${name}",${x[i]},${y[i]}\n`;
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
