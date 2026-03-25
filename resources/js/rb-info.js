/* ==========================================================================
   11. DATASET INFORMATION DISPLAY
   ========================================================================== */

/**
 * Display node attributes and information for a selected path
 * Shows data preview, attributes table, and triggers chart if time-dependent
 * @param {string} path - HDF5 path to the node
 * @param {boolean} isGroup - Whether the node is a group (vs dataset)
 */
async function showNodeAttributes(path, isGroup = false) {
  const infoDiv = document.getElementById('info');
  // Make panel visible and show loading immediately
  infoDiv.style.display = '';
  const heading = document.getElementById('datasetInfoHeading');
  if (heading) heading.style.display = '';
  while (infoDiv.firstChild) infoDiv.removeChild(infoDiv.firstChild);
  const loadingNode = document.createElement('div'); loadingNode.className = 'loading'; loadingNode.textContent = 'Loading...';
  infoDiv.appendChild(loadingNode);

  const jsonReplacer = PDFSampler.jsonReplacer;

  try {
    const enabledFiles = getEffectiveFiles();
    let hasTimeDependentData = false;
    let isRadionuclidesGroup = false;
    const pdfHistogramByFile = [];

    // Check if this is a radionuclides group
    if (isGroup && enabledFiles.length > 0) {
      const firstFile = loadedFiles[enabledFiles[0]];
      isRadionuclidesGroup = checkGroupForRadionuclides(firstFile, path);
      selectedIsRadionuclidesGroup = isRadionuclidesGroup;
    } else {
      selectedIsRadionuclidesGroup = false;
    }

    function createInfoSection(labelText, content, extraClass) {
      const section = document.createElement('div'); section.className = 'info-section' + (extraClass ? ' ' + extraClass : '');
      const lbl = document.createElement('div'); lbl.className = 'info-label'; lbl.textContent = labelText;
      const val = document.createElement('div'); val.className = 'info-content';
      if (content instanceof Node) val.appendChild(content); else val.textContent = (content === null || content === undefined) ? '' : String(content);
      section.appendChild(lbl); section.appendChild(val);
      return section;
    }

    const contentFrag = document.createDocumentFragment();

    for (const fileKey of enabledFiles) {
      const file = loadedFiles[fileKey];
      if (!checkDatasetExistsInFile(file, path)) continue;
      const node = FileService.get(file, path);
      if (!node) continue;

      const isFirstFile = fileKey === enabledFiles[0];
      const fileColor = isFirstFile ? '#0066cc' : '#10b981';
      const nodeType = String(node.type);
      const linkInfo = getLinkInfo(file, path, node);

      const fileSection = document.createElement('div');
      fileSection.className = 'file-data-section';
      fileSection.style.borderLeftColor = fileColor;

      const h = document.createElement('h4'); h.textContent = fileKey; fileSection.appendChild(h);

      if (nodeType === 'BrokenSoftLink') {
        fileSection.appendChild(createInfoSection('Path', path));
        fileSection.appendChild(createInfoSection('Type', 'Broken Soft Link'));
        const targetNode = document.createElement('span'); targetNode.textContent = (node.target || '?') + ' '; const accent = document.createElement('span'); accent.style.color = 'var(--color-kvot-accent)'; accent.textContent = '(target not found)';
        const linkContent = document.createElement('div'); linkContent.appendChild(targetNode); linkContent.appendChild(accent);
        fileSection.appendChild(createInfoSection('🔗 Link Target', linkContent, 'link-info broken'));
        contentFrag.appendChild(fileSection);
        continue;
      }

      if (nodeType === 'ExternalLink') {
        fileSection.appendChild(createInfoSection('Path', path));
        fileSection.appendChild(createInfoSection('Type', 'External Link'));
        fileSection.appendChild(createInfoSection('🔗 External File', node.filename || '?', 'link-info external'));
        fileSection.appendChild(createInfoSection('🔗 External Path', node.obj_path || '?', 'link-info external'));
        contentFrag.appendChild(fileSection);
        continue;
      }

      if (isFirstFile) {
        fileSection.appendChild(createInfoSection('Path', path));
        fileSection.appendChild(createInfoSection('Type', nodeType));
        if (linkInfo && linkInfo.type === 'soft') fileSection.appendChild(createInfoSection('🔗 Soft Link', `Target: ${linkInfo.target}`, 'link-info soft'));
        if (!isGroup && node.dtype) fileSection.appendChild(createInfoSection('Data Type', formatDataType(node.dtype)));
        if (node.shape && Array.isArray(node.shape)) fileSection.appendChild(createInfoSection('Shape', node.shape.join(', ')));
      }

      if (!isGroup) {
        if (isTimeDependent(node)) hasTimeDependentData = true;
        try {
          let data;
          if (typeof node.value !== 'undefined') data = node.value;
          else if (typeof node.toArray === 'function') data = node.toArray();

          if (typeof data !== 'undefined') {
            let preview, itemCount, fullData;
            if (Array.isArray(data)) { preview = data.slice(0, 100); itemCount = data.length; fullData = data; }
            else if (data && typeof data === 'object' && data.length !== undefined) { preview = Array.from(data).slice(0, 100); itemCount = data.length; fullData = Array.from(data); }
            else { preview = [data]; itemCount = 1; fullData = [data]; }

            const isScalar = itemCount === 1;
            const previewLabel = isScalar ? 'Data Preview' : `Data Preview (first ${preview.length}/${itemCount} items)`;
            let previewText;
            if (isScalar) { let val = preview[0]; val = PDFSampler.toNumber(val); previewText = String(val); }
            else previewText = JSON.stringify(preview, jsonReplacer, 2);

            const previewSection = document.createElement('div'); previewSection.className = 'info-section';
            const previewLbl = document.createElement('div'); previewLbl.className = 'info-label';
            previewLbl.style.display = 'flex'; previewLbl.style.alignItems = 'center'; previewLbl.style.justifyContent = 'space-between';
            previewLbl.textContent = previewLabel;

            if (!isScalar) {
              const dlBtn = document.createElement('button'); dlBtn.className = 'download-data-btn';
              dlBtn.style.cssText = 'padding:4px 8px;background:var(--color-kvot-background);color:var(--color-kvot-bright);border:none;border-radius:3px;cursor:pointer;font-size:11px;font-weight:500;transition:all 0.2s;';
              dlBtn.title = 'Download full dataset as CSV';
              dlBtn.textContent = '⬇ Download CSV';
              dlBtn.addEventListener('mouseover', () => dlBtn.style.background = 'var(--color-kvot-primary)');
              dlBtn.addEventListener('mouseout', () => dlBtn.style.background = 'var(--color-kvot-background)');
              dlBtn.addEventListener('click', () => downloadDatasetAsCSV(node, fullData, path, fileKey));
              previewLbl.appendChild(dlBtn);
            }

            const previewContent = document.createElement('div'); previewContent.className = 'info-content'; previewContent.textContent = previewText;
            previewSection.appendChild(previewLbl); previewSection.appendChild(previewContent);
            fileSection.appendChild(previewSection);
          }
        } catch (e) {
          console.warn('Could not read data:', e && e.message ? e.message : e);
        }
      }

      const attrs = {}; let hasAttributes = false;
      try {
        const allA = getAllAttrs(node);
        for (const [k, v] of Object.entries(allA)) {
          attrs[k] = v; hasAttributes = true;
        }
      } catch (e) { console.warn('Error reading attributes:', e && e.message ? e.message : e); }

      if (hasAttributes && Object.keys(attrs).length > 0) {
        const attrEl = buildAttributesTable(attrs, jsonReplacer);
        if (attrEl) fileSection.appendChild(attrEl);
      }

      if (!isGroup && attrs.pdf) {
        let filePdfData = null;
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
                  let rawData;
                  if (typeof node.value !== 'undefined') rawData = node.value;
                  else if (typeof node.toArray === 'function') rawData = node.toArray();

                  if (rawData !== undefined) {
                    const arr = Array.isArray(rawData) ? rawData : Array.from(rawData);
                    entries.push({ label: String(indexLabels[i] ?? i), samples: [arr[i]], spec: null });
                  }
                } catch (_) {
                  /* skip unreadable */
                }
                continue;
              }

              if (spec.type && spec.type.toLowerCase() === 'raw') {
                try {
                  let rawData;
                  if (typeof node.value !== 'undefined') rawData = node.value;
                  else if (typeof node.toArray === 'function') rawData = node.toArray();

                  if (rawData !== undefined) {
                    const flat = Array.isArray(rawData) ? rawData : Array.from(rawData);
                    const nCols = pdfRaw.length;
                    const nRows = Math.floor(flat.length / nCols);
                    const shift = spec.include_deterministic ? 1 : 0;
                    const detVal = (spec.include_deterministic && nRows > 0) ? flat[0 * nCols + i] : null;
                    const col = [];
                    for (let r = shift; r < nRows; r++) col.push(flat[r * nCols + i]);
                    entries.push({ label: String(indexLabels[i] ?? i), samples: col, spec: spec, deterministicValue: detVal });
                  }
                } catch (_) {
                  /* skip */
                }
              } else {
                // standard distribution spec for this index
                let detVal = null;
                try {
                  let rawData;
                  if (typeof node.value !== 'undefined') rawData = node.value;
                  else if (typeof node.toArray === 'function') rawData = node.toArray();

                  if (rawData !== undefined) {
                    const flat = Array.isArray(rawData) ? rawData : Array.from(rawData);
                    const nCols = pdfRaw.length;
                    if (flat.length >= nCols) detVal = Number(flat[i]);
                  }
                } catch (_) {
                  detVal = null;
                }

                const samples = generatePdfSamples(spec, 1000);
                if (samples) {
                  const norm = PDFSampler.normalizeDataArray(samples);
                  entries.push({ label: String(indexLabels[i] ?? i), samples: Array.from(norm), spec: spec, deterministicValue: isFinite(detVal) ? detVal : null });
                } else {
                  console.warn('generatePdfSamples returned null for spec (lookup index)', spec);
                }
              }
            }

            if (entries.length > 0) filePdfData = { type: 'lookup', entries, path };

          } else if (!isLookupTable && pdfRaw.type) {
            // single PDF spec
            if (pdfRaw.type.toLowerCase() === 'raw') {
              try {
                let rawData;
                if (typeof node.value !== 'undefined') rawData = node.value;
                else if (typeof node.toArray === 'function') rawData = node.toArray();

                if (rawData !== undefined) {
                  const flat = PDFSampler.normalizeDataArray(rawData);
                  const shift = pdfRaw.include_deterministic ? 1 : 0;
                  const detVal = (pdfRaw.include_deterministic && flat.length > 0) ? flat[0] : null;
                  filePdfData = { type: 'single', samples: flat.slice(shift), spec: pdfRaw, path, deterministicValue: detVal };
                }
              } catch (_) { /* skip */ }
            } else {
              let detVal = null;
              try {
                let rawData;
                if (typeof node.value !== 'undefined') rawData = node.value;
                else if (typeof node.toArray === 'function') rawData = node.toArray();

                if (rawData !== undefined) {
                  if (typeof rawData === 'number') detVal = rawData;
                  else if (rawData && rawData.length !== undefined && rawData.length > 0) detVal = Number(rawData[0]);
                }
              } catch (_) { /* ignore */ }

              const samples = generatePdfSamples(pdfRaw, 1000);
              if (samples) {
                const norm = PDFSampler.normalizeDataArray(samples);
                filePdfData = { type: 'single', samples: Array.from(norm), spec: pdfRaw, path, deterministicValue: isFinite(detVal) ? detVal : null };
              } else {
                console.warn('generatePdfSamples returned null for pdf spec', pdfRaw, 'at', path);
              }
            }
          }
        } catch (err) {
          console.warn('PDF collect error:', err);
        }
        if (filePdfData) pdfHistogramByFile.push({ fileKey, data: filePdfData });
      }

      // if still no histogram data for this file, and dataset was marked probabilistic without time-dependent
      if (!isGroup && !pdfHistogramByFile.some(e => e.fileKey === fileKey) && checkIsProbabilistic(node) && !hasTimeDependentData) {
        try {
          let rawData;
          if (typeof node.value !== 'undefined') rawData = node.value;
          else if (typeof node.toArray === 'function') rawData = node.toArray();

          if (rawData !== undefined) {
            const flat = PDFSampler.normalizeDataArray(rawData);
            pdfHistogramByFile.push({ fileKey, data: { type: 'single', samples: Array.from(flat), spec: null, path } });
          }
        } catch (err) {
          console.warn('Probabilistic histogram error:', err);
        }
      }

      if (!isGroup) {
        const excelWrap = document.createElement('div'); excelWrap.style.marginTop = '12px'; excelWrap.style.paddingTop = '12px'; excelWrap.style.borderTop = '1px solid var(--color-border)';
        const excelBtn = document.createElement('button'); excelBtn.style.cssText = 'padding:6px 12px;background:#217346;color:white;border:none;border-radius:4px;cursor:pointer;font-size:12px;font-weight:500;transition:all 0.2s;';
        excelBtn.title = 'Download this dataset to Excel';
        excelBtn.textContent = '📊 Download Excel';
        excelBtn.addEventListener('mouseover', () => excelBtn.style.background = '#1e6b3f');
        excelBtn.addEventListener('mouseout', () => excelBtn.style.background = '#217346');
        excelBtn.addEventListener('click', () => downloadDatasetAsExcel(path, fileKey));
        excelWrap.appendChild(excelBtn);
        fileSection.appendChild(excelWrap);
      }

      contentFrag.appendChild(fileSection);
    }

    while (infoDiv.firstChild) infoDiv.removeChild(infoDiv.firstChild);
    if (contentFrag.childNodes.length > 0) infoDiv.appendChild(contentFrag);
    else { const noData = document.createElement('div'); noData.style.color = '#999'; noData.textContent = 'No data available for this path'; infoDiv.appendChild(noData); }

    // Merge per-file PDF histogram data into a single structure
    let pdfHistogramData = null;
    if (pdfHistogramByFile.length === 1) {
      pdfHistogramData = pdfHistogramByFile[0].data;
    } else if (pdfHistogramByFile.length > 1) {
      // Multiple files — combine into a lookup-type structure with file-labelled entries
      // Use buildTraceName-consistent file diffing (each file diffs against a different peer)
      const allMergeFileKeys = pdfHistogramByFile.map(e => e.fileKey);
      const mergedEntries = [];
      for (const item of pdfHistogramByFile) {
        const fileSuffix = ' (' + filenameDiff(
          item.fileKey === allMergeFileKeys[0] ? allMergeFileKeys[1] : allMergeFileKeys[0],
          item.fileKey
        ) + ')';
        if (item.data.type === 'single') {
          const nodeName = item.data.path ? item.data.path.split('/').pop() : '';
          const specSuffix = item.data.spec ? ' (' + PDFSampler.pdfLabel(item.data.spec) + ')' : '';
          const label = (nodeName || 'raw') + specSuffix + fileSuffix;
          mergedEntries.push({ label, samples: item.data.samples, spec: item.data.spec, deterministicValue: item.data.deterministicValue });
        } else if (item.data.type === 'lookup') {
          for (const entry of item.data.entries) {
            mergedEntries.push({ ...entry, label: entry.label + fileSuffix });
          }
        }
      }
      if (mergedEntries.length > 0) pdfHistogramData = { type: 'lookup', entries: mergedEntries, path };
    }

    if (isRadionuclidesGroup) { currentPdfHistogram = false; await createRadionuclidesChart(path); }
    else if (hasTimeDependentData && !isGroup) { currentPdfHistogram = false; createPlotlyChart(path); }
    else if (pdfHistogramData) { createPdfHistogram(pdfHistogramData); }
    else { currentPdfHistogram = false; document.getElementById('plotlyChartContainer').classList.remove('visible'); currentChartData = null; }
  } catch (e) {
    while (infoDiv.firstChild) infoDiv.removeChild(infoDiv.firstChild);
    const errDiv = document.createElement('div'); errDiv.className = 'error'; errDiv.textContent = `Error: ${e && e.message ? e.message : 'unknown'}`;
    infoDiv.appendChild(errDiv);
    console.error(e);
  }
}

/**
 * Download dataset data as CSV file
 * @param {Object} node - HDF5 dataset node
 * @param {Array} fullData - Full data array
 * @param {string} path - Dataset path
 * @param {string} fileKey - File name
 */
function downloadDatasetAsCSV(node, fullData, path, fileKey) {
  // Get index attribute if it exists
  let headerRow = null;
  try {
    const indexValue = getAttr(node, 'index');
    if (indexValue !== undefined && indexValue !== null) {
      if (Array.isArray(indexValue)) {
        headerRow = indexValue;
      } else if (indexValue && indexValue.length !== undefined) {
        headerRow = Array.from(indexValue);
      }
    }
  } catch (e) {
    console.warn('Could not read index attribute:', e);
  }
  
  // Determine data shape and build CSV
  let csvContent = '';
  const shape = node.shape || [];
  
  if (shape.length === 1) {
    // 1D array - single column
    if (headerRow && headerRow.length === 1) {
      csvContent += escapeCSV(headerRow[0]) + '\n';
    }
    fullData.forEach(value => {
      csvContent += escapeCSV(value) + '\n';
    });
  } else if (shape.length === 2) {
    // 2D array - rows and columns
    const numRows = shape[0];
    const numCols = shape[1];
    
    if (headerRow && headerRow.length === numCols) {
      csvContent += headerRow.map(h => escapeCSV(h)).join(',') + '\n';
    }
    
    for (let i = 0; i < numRows; i++) {
      const row = [];
      for (let j = 0; j < numCols; j++) {
        row.push(escapeCSV(fullData[i * numCols + j]));
      }
      csvContent += row.join(',') + '\n';
    }
  } else if (shape.length === 0) {
    // Scalar or flat array
    if (headerRow && headerRow.length > 0) {
      csvContent += headerRow.map(h => escapeCSV(h)).join(',') + '\n';
    }
    
    if (headerRow && headerRow.length > 1) {
      const numCols = headerRow.length;
      const numRows = Math.floor(fullData.length / numCols);
      for (let i = 0; i < numRows; i++) {
        const row = [];
        for (let j = 0; j < numCols; j++) {
          row.push(escapeCSV(fullData[i * numCols + j]));
        }
        csvContent += row.join(',') + '\n';
      }
    } else {
      fullData.forEach(value => {
        csvContent += escapeCSV(value) + '\n';
      });
    }
  } else {
    // Higher dimensional - flatten to 2D
    console.warn('Multi-dimensional array, flattening to 2D');
    if (headerRow) {
      csvContent += headerRow.map(h => escapeCSV(h)).join(',') + '\n';
    }
    
    const lastDim = shape[shape.length - 1];
    const numRows = Math.floor(fullData.length / lastDim);
    
    for (let i = 0; i < numRows; i++) {
      const row = [];
      for (let j = 0; j < lastDim; j++) {
        row.push(escapeCSV(fullData[i * lastDim + j]));
      }
      csvContent += row.join(',') + '\n';
    }
  }
  
  // Create and download CSV
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  const safePath = path.replace(/[^a-zA-Z0-9]/g, '_');
  const safeFileName = fileKey.replace(/\.[^/.]+$/, '');
  a.download = `${safeFileName}${safePath}_data.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * Download selected dataset information, attributes, and data as Excel file
 * Uses xlsxwrite.js library
 */
async function downloadDatasetAsExcel(datasetPath, datasetFileKey) {
  // Use provided parameters or fall back to selected dataset
  const path = datasetPath || selectedDatasetPath;
  if (!path) {
    alert('No dataset selected');
    return;
  }
  
  const enabledFiles = getEffectiveFiles();
  if (enabledFiles.length === 0) {
    alert('No files enabled');
    return;
  }
  
  try {
    // Use specified file or first enabled file
    const fileKey = datasetFileKey || enabledFiles[0];
    const file = loadedFiles[fileKey];
    if (!file) {
      alert('File not found: ' + fileKey);
      return;
    }
    const node = FileService.get(file, path);
    
    if (!node) {
      alert('Could not access dataset');
      return;
    }
    
    const isGroup = node.type === 'Group';
    const safeFileName = fileKey.replace(/\.[^/.]+$/, '').replace(/[^a-zA-Z0-9]/g, '_');
    const safePath = path.replace(/[^a-zA-Z0-9]/g, '_');
    
    // Create workbook
    const xlsx = new XlsxWriter(`${safeFileName}${safePath}.xlsx`);
    
    // Create formats
    const headerFormat = xlsx.addFormat({
      bold: true,
      bg_color: '217346',
      font_color: 'FFFFFF',
      align: 'center',
      valign: 'vcenter',
      border: 1
    });
    
    const labelFormat = xlsx.addFormat({
      bold: true,
      bg_color: 'E2EFDA',
      border: 1
    });
    
    const valueFormat = xlsx.addFormat({
      border: 1
    });
    
    const titleFormat = xlsx.addFormat({
      bold: true,
      font_size: 14,
      font_color: '217346'
    });
    
    // ========== SHEET 1: Information ==========
    xlsx.write(0, 0, 'Dataset Information', titleFormat, 'Information');
    xlsx.write(2, 0, 'Property', headerFormat, 'Information');
    xlsx.write(2, 1, 'Value', headerFormat, 'Information');
    xlsx.setColumn(0, 0, 20, null, {}, 'Information');
    xlsx.setColumn(1, 1, 50, null, {}, 'Information');
    
    let row = 3;
    xlsx.write(row, 0, 'File', labelFormat, 'Information');
    xlsx.write(row, 1, fileKey, valueFormat, 'Information');
    row++;
    
    xlsx.write(row, 0, 'Path', labelFormat, 'Information');
    xlsx.write(row, 1, path, valueFormat, 'Information');
    row++;
    
    xlsx.write(row, 0, 'Type', labelFormat, 'Information');
    xlsx.write(row, 1, String(node.type), valueFormat, 'Information');
    row++;
    
    if (!isGroup && node.dtype) {
      xlsx.write(row, 0, 'Data Type', labelFormat, 'Information');
      xlsx.write(row, 1, formatDataType(node.dtype), valueFormat, 'Information');
      row++;
    }
    
    if (node.shape && Array.isArray(node.shape)) {
      xlsx.write(row, 0, 'Shape', labelFormat, 'Information');
      xlsx.write(row, 1, node.shape.join(' × '), valueFormat, 'Information');
      row++;
    }
    
    xlsx.write(row, 0, 'Export Date', labelFormat, 'Information');
    xlsx.write(row, 1, new Date().toISOString(), valueFormat, 'Information');
    
    // ========== SHEET 2: Attributes ==========
    const attrs = getAllAttrs(node);
    
    xlsx.write(0, 0, 'Attributes', titleFormat, 'Attributes');
    xlsx.write(2, 0, 'Name', headerFormat, 'Attributes');
    xlsx.write(2, 1, 'Value', headerFormat, 'Attributes');
    xlsx.setColumn(0, 0, 25, null, {}, 'Attributes');
    xlsx.setColumn(1, 1, 60, null, {}, 'Attributes');
    
    row = 3;
    for (const [key, value] of Object.entries(attrs)) {
      let displayValue;
      if (typeof value === 'string') {
        displayValue = value;
      } else if (Array.isArray(value)) {
        displayValue = `[${value.join(', ')}]`;
      } else if (value === null) {
        displayValue = 'null';
      } else if (value === undefined) {
        displayValue = 'undefined';
      } else if (typeof value === 'object') {
        if (value.length !== undefined) {
          displayValue = `[${Array.from(value).slice(0, 10).join(', ')}${value.length > 10 ? '...' : ''}]`;
        } else {
          displayValue = JSON.stringify(value);
        }
      } else if (typeof value === 'bigint') {
        displayValue = String(PDFSampler.toNumber(value));
      } else {
        displayValue = String(value);
      }
      
      xlsx.write(row, 0, key, labelFormat, 'Attributes');
      xlsx.write(row, 1, displayValue, valueFormat, 'Attributes');
      row++;
    }
    
    if (Object.keys(attrs).length === 0) {
      xlsx.write(3, 0, '(No attributes)', valueFormat, 'Attributes');
    }
    
    // ========== SHEET 3: Data ==========
    if (!isGroup) {
      let data;
      try {
        if (typeof node.value !== 'undefined') {
          data = node.value;
        } else if (typeof node.toArray === 'function') {
          data = node.toArray();
        }
      } catch (e) {
        console.warn('Could not read data:', e);
      }
      
      if (data !== undefined) {
        let fullData;
        if (Array.isArray(data)) {
          fullData = data;
        } else if (data && typeof data === 'object' && data.length !== undefined) {
          fullData = Array.from(data);
        } else {
          fullData = [data];
        }
        
        xlsx.write(0, 0, 'Data', titleFormat, 'Data');
        
        // Check for index attribute (column headers)
        let headerRow = null;
        try {
          const indexValue = getAttr(node, 'index');
          if (indexValue !== undefined && indexValue !== null) {
            if (Array.isArray(indexValue)) {
              headerRow = indexValue;
            } else if (indexValue && indexValue.length !== undefined) {
              headerRow = Array.from(indexValue);
            }
          }
        } catch (e) {
          console.warn('Could not read index attribute:', e);
        }
        
        // Try to get time data for time-series datasets
        let timeData = null;
        let timeUnit = '';
        try {
          timeData = getTimeData(file);
          timeUnit = getTimeUnit(file);
        } catch (e) {
          console.warn('Could not read time data:', e);
        }
        
        const shape = node.shape || [];
        
        if (shape.length <= 1) {
          // 1D array - single column (possibly with time column)
          const hasTimeColumn = timeData && timeData.length === fullData.length;
          const colOffset = hasTimeColumn ? 1 : 0;
          
          // Write time header if available
          if (hasTimeColumn) {
            const timeHeader = timeUnit ? `Time (${timeUnit})` : 'Time';
            xlsx.write(2, 0, timeHeader, headerFormat, 'Data');
            xlsx.setColumn(0, 0, 15, null, {}, 'Data');
          }
          
          // Write data header
          if (headerRow && headerRow.length === 1) {
            xlsx.write(2, colOffset, headerRow[0], headerFormat, 'Data');
          } else {
            xlsx.write(2, colOffset, 'Value', headerFormat, 'Data');
          }
          
          // Write data (with time if available)
          for (let i = 0; i < fullData.length; i++) {
            if (hasTimeColumn) {
              xlsx.write(3 + i, 0, timeData[i], null, 'Data');
            }
            const val = fullData[i];
            xlsx.write(3 + i, colOffset, typeof val === 'number' ? val : String(val), null, 'Data');
          }
          
          xlsx.setColumn(colOffset, colOffset, 15, null, {}, 'Data');
          
        } else if (shape.length === 2) {
          // 2D array (possibly with time column)
          const numRows = shape[0];
          const numCols = shape[1];
          const hasTimeColumn = timeData && timeData.length === numRows;
          const colOffset = hasTimeColumn ? 1 : 0;
          
          // Write time header if available
          if (hasTimeColumn) {
            const timeHeader = timeUnit ? `Time (${timeUnit})` : 'Time';
            xlsx.write(2, 0, timeHeader, headerFormat, 'Data');
          }
          
          // Write headers
          if (headerRow && headerRow.length === numCols) {
            for (let j = 0; j < numCols; j++) {
              xlsx.write(2, j + colOffset, String(headerRow[j]), headerFormat, 'Data');
            }
          } else {
            for (let j = 0; j < numCols; j++) {
              xlsx.write(2, j + colOffset, `Col ${j + 1}`, headerFormat, 'Data');
            }
          }
          
          // Write data (with time if available)
          for (let i = 0; i < numRows; i++) {
            if (hasTimeColumn) {
              xlsx.write(3 + i, 0, timeData[i], null, 'Data');
            }
            for (let j = 0; j < numCols; j++) {
              const val = fullData[i * numCols + j];
              xlsx.write(3 + i, j + colOffset, typeof val === 'number' ? val : String(val), null, 'Data');
            }
          }
          
          // Set column widths
          if (hasTimeColumn) {
            xlsx.setColumn(0, 0, 15, null, {}, 'Data');
          }
          for (let j = 0; j < numCols; j++) {
            xlsx.setColumn(j + colOffset, j + colOffset, 12, null, {}, 'Data');
          }
          
        } else {
          // Higher dimensional - flatten with index attribute hints (possibly with time column)
          const numCols = headerRow ? headerRow.length : (shape[shape.length - 1] || 1);
          const numRows = Math.floor(fullData.length / numCols);
          const hasTimeColumn = timeData && timeData.length === numRows;
          const colOffset = hasTimeColumn ? 1 : 0;
          
          // Write time header if available
          if (hasTimeColumn) {
            const timeHeader = timeUnit ? `Time (${timeUnit})` : 'Time';
            xlsx.write(2, 0, timeHeader, headerFormat, 'Data');
          }
          
          // Write headers
          if (headerRow) {
            for (let j = 0; j < headerRow.length; j++) {
              xlsx.write(2, j + colOffset, String(headerRow[j]), headerFormat, 'Data');
            }
          } else {
            for (let j = 0; j < numCols; j++) {
              xlsx.write(2, j + colOffset, `Col ${j + 1}`, headerFormat, 'Data');
            }
          }
          
          // Write data (with time if available)
          for (let i = 0; i < numRows; i++) {
            if (hasTimeColumn) {
              xlsx.write(3 + i, 0, timeData[i], null, 'Data');
            }
            for (let j = 0; j < numCols; j++) {
              const idx = i * numCols + j;
              if (idx < fullData.length) {
                const val = fullData[idx];
                xlsx.write(3 + i, j + colOffset, typeof val === 'number' ? val : String(val), null, 'Data');
              }
            }
          }
          
          // Set column widths
          if (hasTimeColumn) {
            xlsx.setColumn(0, 0, 15, null, {}, 'Data');
          }
          for (let j = 0; j < numCols; j++) {
            xlsx.setColumn(j + colOffset, j + colOffset, 12, null, {}, 'Data');
          }
        }
      }
    }
    
    // Save and download
    const content = await xlsx.save();
    
    // Browser download
    const url = URL.createObjectURL(content);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${safeFileName}${safePath}.xlsx`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    
  } catch (e) {
    console.error('Error creating Excel file:', e);
    alert('Error creating Excel file: ' + e.message);
  }
}

/**
 * Build HTML table for node attributes
 * @param {Object} attrs - Attributes object
 * @param {Function} jsonReplacer - JSON replacer for BigInt etc.
 * @returns {HTMLElement} Element containing the attributes table (DOM)
 */
function buildAttributesTable(attrs, jsonReplacer) {
  const wrapper = document.createElement('div'); wrapper.className = 'info-section';
  const label = document.createElement('div'); label.className = 'info-label'; label.textContent = `Attributes (${Object.keys(attrs).length})`;
  wrapper.appendChild(label);

  const content = document.createElement('div'); content.className = 'info-content'; content.style.padding = '0'; content.style.overflowX = 'auto';
  const table = document.createElement('table'); table.className = 'attrs-table';

  const thead = document.createElement('tr'); thead.className = 'attrs-header';
  const th1 = document.createElement('th'); th1.textContent = 'Name';
  const th2 = document.createElement('th'); th2.textContent = 'Value';
  thead.appendChild(th1); thead.appendChild(th2);
  table.appendChild(thead);

  for (const [key, value] of Object.entries(attrs)) {
    let displayValue;
    if (typeof value === 'string') displayValue = value;
    else if (Array.isArray(value)) displayValue = `[${value.join(', ')}]`;
    else if (value === null) displayValue = 'null';
    else if (value === undefined) displayValue = 'undefined';
    else if (typeof value === 'object') {
      if (value.length !== undefined) displayValue = `[${Array.from(value).slice(0, 10).join(', ')}${value.length > 10 ? '...' : ''}]`;
      else displayValue = JSON.stringify(value, jsonReplacer, 0);
    } else if (typeof value === 'bigint') displayValue = String(Number(value));
    else displayValue = String(value);

    const row = document.createElement('tr'); row.className = 'attrs-row';
    const nameTd = document.createElement('td'); const strong = document.createElement('strong'); strong.textContent = key; nameTd.appendChild(strong);
    const valTd = document.createElement('td'); valTd.className = 'attrs-value'; valTd.textContent = displayValue;
    row.appendChild(nameTd); row.appendChild(valTd);
    table.appendChild(row);
  }

  content.appendChild(table);
  wrapper.appendChild(content);
  return wrapper;
}

/**
 * Display information for multiple selected datasets.
 * Each item carries its own fileKey for cross-file comparisons.
 * @param {{path: string, fileKey: string|null}[]} items - Array of selected dataset items
 */
function showMultipleDatasetAttributes(items) {
  const infoDiv = document.getElementById('info');
  while (infoDiv.firstChild) infoDiv.removeChild(infoDiv.firstChild);
  const heading = document.getElementById('datasetInfoHeading');
  if (!items || items.length === 0) {
    resetInfoPanel();
    hideChart();
    return;
  }

  if (heading) heading.style.display = '';

  const loading = document.createElement('div'); loading.className = 'loading'; loading.textContent = `Loading ${items.length} datasets...`;
  infoDiv.appendChild(loading);

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
      for (const fk of getEnabledFiles()) {
        const key = item.path + '|' + fk;
        if (!seen.has(key)) {
          normalizedItems.push({ path: item.path, fileKey: fk });
          seen.add(key);
        }
      }
    }
  }

  const frag = document.createDocumentFragment();
  const header = document.createElement('div');
  header.style.cssText = 'background: var(--color-kvot-bright); padding: 12px; border-radius: 6px; margin-bottom: 16px; font-weight: 600; color: var(--color-kvot-background);';
  header.textContent = `📊 ${normalizedItems.length} datasets selected`;
  frag.appendChild(header);

  const makeLabelSection = (label, content, opts = {}) => {
    const section = document.createElement('div'); section.className = 'info-section';
    const lbl = document.createElement('div'); lbl.className = 'info-label'; lbl.textContent = label;
    const val = document.createElement('div'); val.className = 'info-content';
    if (opts.html) { val.innerHTML = opts.html; } else { val.textContent = (content === undefined || content === null) ? '' : String(content); }
    section.appendChild(lbl); section.appendChild(val);
    return section;
  };

  let allTimeDependent = true;
  const combinedHistogramEntries = [];

  // Pre-compute context arrays for buildTraceName
  const allPaths = normalizedItems.map(d => d.path);
  const allFileKeys = normalizedItems.map(d => d.fileKey);

  for (const item of normalizedItems) {
    const { path, fileKey } = item;
    const file = loadedFiles[fileKey];
    if (!file) continue;

    const fileSection = document.createElement('div'); fileSection.className = 'file-data-section';
    fileSection.style.borderLeftColor = 'var(--color-kvot-accent)';

    const h4 = document.createElement('h4');
    h4.textContent = path + ' ';
    const small = document.createElement('span'); small.style.fontWeight = '400'; small.style.fontSize = '11px'; small.style.color = '#888'; small.textContent = `(${fileKey})`;
    h4.appendChild(small);
    fileSection.appendChild(h4);

    try {
      const dataset = FileService.get(file, path);
      if (!dataset) { frag.appendChild(fileSection); continue; }

      const isTimeDep = isTimeDependent(dataset);
      if (!isTimeDep) allTimeDependent = false;

      fileSection.appendChild(makeLabelSection('Type', String(dataset.type) + (isTimeDep ? ' ⏱️ (time-dependent)' : '')));

      if (dataset.dtype) fileSection.appendChild(makeLabelSection('Data Type', formatDataType(dataset.dtype)));
      if (dataset.shape && Array.isArray(dataset.shape)) fileSection.appendChild(makeLabelSection('Shape', dataset.shape.join(', ')));

      const attrs = getAllAttrs(dataset);

      if (Object.keys(attrs).length > 0) {
        const sec = document.createElement('div'); sec.className = 'info-section';
        const lbl = document.createElement('div'); lbl.className = 'info-label'; lbl.textContent = 'Key Attributes';
        const val = document.createElement('div'); val.className = 'info-content'; val.style.fontSize = '11px';

        let count = 0;
        for (const [k, v] of Object.entries(attrs)) {
          if (count++ >= 5) break;
          const row = document.createElement('div');
          const strong = document.createElement('strong'); strong.textContent = k + ':'; row.appendChild(strong);
          //const txt = document.createTextNode(' ' + (v === undefined || v === null ? '' : String(v)).slice(0, 50) + ((v && String(v).length > 50) ? '...' : ''));
          const txt = document.createTextNode(' ' + (v === undefined || v === null ? '' : String(v)));
          row.appendChild(txt);
          val.appendChild(row);
        }

        sec.appendChild(lbl); sec.appendChild(val); fileSection.appendChild(sec);
      }

      try {
        if (attrs.pdf) {
          const datasetName = path.split('/').pop();
          const entryLabel = buildTraceName(datasetName, path, fileKey, allPaths, allFileKeys);
          const pdfEntries = collectPdfEntries(dataset, attrs, entryLabel);
          if (pdfEntries) combinedHistogramEntries.push(...pdfEntries);
        } else if (checkIsProbabilistic(dataset) && !isTimeDep) {
          // no PDF but probabilistic dataset – include raw values in combined entries
          try {
            let rawData = typeof dataset.value !== 'undefined' ? dataset.value : (typeof dataset.toArray === 'function' ? dataset.toArray() : undefined);
            if (rawData !== undefined) {
              const flat = Array.isArray(rawData) ? rawData : Array.from(rawData);
              const datasetName = path.split('/').pop();
              const entryLabel = buildTraceName(datasetName, path, fileKey, allPaths, allFileKeys);
              combinedHistogramEntries.push({ label: entryLabel, samples: flat.map(PDFSampler.toNumber), spec: null, deterministicValue: null });
            }
          } catch (err) {
            console.warn('probabilistic collect error:', err);
          }
        }
      } catch (err) { console.warn('PDF collect error:', err); }

      const excelWrap = document.createElement('div'); excelWrap.style.marginTop = '12px'; excelWrap.style.paddingTop = '12px'; excelWrap.style.borderTop = '1px solid var(--color-border)';
      const excelBtn = document.createElement('button');
      excelBtn.style.cssText = 'padding: 6px 12px; background: #217346; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: 500; transition: all 0.2s;';
      excelBtn.title = 'Download this dataset to Excel'; excelBtn.textContent = '📊 Download Excel';
      excelBtn.addEventListener('mouseover', () => excelBtn.style.background = '#1e6b3f');
      excelBtn.addEventListener('mouseout', () => excelBtn.style.background = '#217346');
      excelBtn.addEventListener('click', () => downloadDatasetAsExcel(path, fileKey));
      excelWrap.appendChild(excelBtn);
      fileSection.appendChild(excelWrap);

    } catch (e) {
      const errDiv = document.createElement('div'); errDiv.className = 'error'; errDiv.textContent = `Error loading dataset: ${e && e.message ? e.message : e}`;
      fileSection.appendChild(errDiv);
    }

    frag.appendChild(fileSection);
  }

  while (infoDiv.firstChild) infoDiv.removeChild(infoDiv.firstChild);
  infoDiv.appendChild(frag);

  if (allTimeDependent && normalizedItems.length > 0) {
    createMultiDatasetChart(normalizedItems);
  } else if (combinedHistogramEntries.length > 0) {
    createPdfHistogram({ type: 'lookup', entries: combinedHistogramEntries, path: 'Multi-selection' });
  } else {
    document.getElementById('plotlyChartContainer').classList.remove('visible');
    currentChartData = null;
  }
}


