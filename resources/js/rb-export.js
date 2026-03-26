/* ==========================================================================
   14. CLIPBOARD & EXPORT
   ========================================================================== */

/**
 * Copy the current chart to clipboard as a PNG image.
 * Uses the Clipboard API with ClipboardItem for image data.
 * Falls back to file download if clipboard access is denied or unavailable.
 * 
 * The exported image is rendered at 2x scale (1200x800 at scale 2)
 * for high-quality output suitable for documents and presentations.
 * 
 * @returns {Promise<void>}
 */
async function copyChartToClipboard() {
  if (!currentChartData) {
    alert('No chart available to copy');
    return;
  }
  
  const plotDiv = document.getElementById('plotlyChart');
  const btn = event.target;
  const originalText = btn.textContent;
  
  try {
    // Check clipboard API availability
    if (!navigator.clipboard || !navigator.clipboard.write) {
      throw new Error('Clipboard API not supported');
    }
    
    // Try to request permission if needed
    try {
      const permissionStatus = await navigator.permissions.query({ name: 'clipboard-write' });
      if (permissionStatus.state === 'denied') {
        throw new Error('Clipboard permission denied');
      }
    } catch (permErr) {
      console.log('Permission query not supported, attempting clipboard write anyway');
    }
    
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const origPaper = plotDiv.layout.paper_bgcolor;
    const origPlot  = plotDiv.layout.plot_bgcolor;

    if (!isDark) {
      await Plotly.relayout(plotDiv, { paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)' });
    }

    // Convert chart to PNG
    const dataUrl = await Plotly.toImage(plotDiv, {
      format: 'png',
      width: 1200,
      height: 800,
      scale: 2
    });

    if (!isDark) {
      await Plotly.relayout(plotDiv, { paper_bgcolor: origPaper, plot_bgcolor: origPlot });
    }
    
    const blob = await fetch(dataUrl).then(r => r.blob());
    
    // Write to clipboard
    await navigator.clipboard.write([
      new ClipboardItem({
        'image/png': blob
      })
    ]);
    
    // Show success feedback
    btn.textContent = '✓ Copied!';
    btn.style.background = 'var(--color-kvot-accent)';
    
    setTimeout(() => {
      btn.textContent = originalText;
      btn.style.background = '';
    }, 2000);
    
  } catch (err) {
    console.error('Clipboard copy failed:', err);
    
    // Fallback to download
    try {
      const dataUrl = await Plotly.toImage(plotDiv, {
        format: 'png',
        width: 1200,
        height: 800,
        scale: 2
      });
      
      const link = document.createElement('a');
      link.href = dataUrl;
      link.download = `chart_${Date.now()}.png`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      
      // Show download feedback
      btn.textContent = '⬇ Downloaded';
      btn.style.background = 'var(--color-kvot-accent)';
      
      setTimeout(() => {
        btn.textContent = originalText;
        btn.style.background = '';
      }, 2000);
      
      if (err.message.includes('denied') || err.message.includes('permission')) {
        alert('Clipboard access was denied. The chart has been downloaded instead.');
      }
    } catch (downloadErr) {
      console.error('Download also failed:', downloadErr);
      alert('Failed to copy or download chart: ' + downloadErr.message);
    }
  }
}


