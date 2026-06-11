/* ==========================================================================
   3. HDF5 DATA ACCESS
   ========================================================================== */

/**
 * Check if a dataset or group exists at the given path in an HDF5 file.
 * Safely handles exceptions from invalid paths.
 * 
 * @param {Object} file - h5wasm File object
 * @param {string} path - HDF5 path to check (e.g., '/group/dataset')
 * @returns {boolean} True if the path exists and is accessible
 */
function checkDatasetExistsInFile(file, path) {
  try {
    const dataset = FileService.get(file, path);
    return dataset !== null && dataset !== undefined;
  } catch (e) {
    return false;
  }
}

/**
 * Check if a path exists in a file referenced by filename.
 * Looks up the file in loadedFiles by name before checking.
 * 
 * @param {string} fileName - Key in loadedFiles object
 * @param {string} path - HDF5 path to check
 * @returns {boolean} True if file exists in loadedFiles and path is valid
 */
function checkIfPathExistsInFile(fileName, path) {
  try {
    const file = loadedFiles[fileName];
    if (!file) return false;
    const node = FileService.get(file, path);
    return node !== null && node !== undefined;
  } catch (e) {
    return false;
  }
}

/**
 * Retrieve time axis data from the standard '/time' dataset.
 * This is the x-axis data for time-dependent plots.
 * 
 * @param {Object} file - h5wasm File object
 * @returns {number[]|null} Array of time values, or null if not found
 */
function getTimeData(file) {
  try {
    const timeDataset = FileService.get(file, '/time');
    if (timeDataset && typeof timeDataset.value !== 'undefined') {
      let timeData = timeDataset.value;
      if (timeData && typeof timeData === 'object' && timeData.length !== undefined) {
        return Array.from(timeData);
      }
      return [timeData];
    }
  } catch (e) {
    console.warn('Could not read /time dataset:', e.message);
  }
  return null;
}

/**
 * Check if the '/time' dataset has the 'probabilistic' attribute set to true.
 * When true the time axis is a matrix – one row per iteration.
 *
 * @param {Object} file - h5wasm File object
 * @returns {boolean}
 */
function checkTimeProbabilistic(file) {
  try {
    const timeDataset = FileService.get(file, '/time');
    return isTruthyAttribute(getAttr(timeDataset, 'probabilistic'));
  } catch (e) {
    return false;
  }
}

/**
 * Read the probabilistic time matrix from '/time'.
 *
 * Storage layout (confirmed from data files):
 *   shape = (nTimeSteps, nIterPad) where
 *     nTimeSteps = max number of time steps across all iterations (row count)
 *     nIterPad   = padded column count (≥ actual number of iterations)
 *   flat[t_i * nIterPad + k] = time value at time step t_i for iteration k
 *   n_times[k]               = number of valid time steps for iteration k
 *   nIter                    = len(n_times) = actual number of iterations
 *
 * Returns an object with:
 *   matrix      – array [nIter] where matrix[k] is iteration k's time series
 *                 (only the valid time steps, length = iterLengths[k])
 *   nIter       – number of valid iterations
 *   maxLen      – nIterPad = shape[1], used as stride for flat y-array access:
 *                 y_flat[t_i * maxLen + k] = y value at time step t_i for iter k
 *   iterLengths – array [nIter]: number of valid time steps per iteration
 *
 * Returns null when the dataset is absent, not probabilistic, or not 2-D.
 *
 * @param {Object} file - h5wasm File object
 * @returns {{ matrix: number[][], nIter: number, maxLen: number, iterLengths: number[] }|null}
 */
function getProbabilisticTimeMatrix(file) {
  try {
    const timeDataset = FileService.get(file, '/time');
    if (!timeDataset || !isTruthyAttribute(getAttr(timeDataset, 'probabilistic'))) return null;
    const shape = timeDataset.shape;
    if (!shape || shape.length < 2) return null;
    const nTimeSteps = shape[0];  // rows  = max time steps
    const nIterPad   = shape[1];  // cols  = padded iteration count (stride)
    const flat = Array.from(timeDataset.value, v => PDFSampler.toNumber(v));

    // Determine per-iteration lengths from 'n_times' attribute (indexed by iteration k).
    // Fallback: scan each column for the last monotonically-increasing value.
    const nTimesAttr = getAttr(timeDataset, 'n_times');
    let nIter, iterLengths;
    if (nTimesAttr != null) {
      const nTimesArr = Array.from(nTimesAttr);
      nIter       = nTimesArr.length;
      iterLengths = nTimesArr.map(v => {
        const n = Math.round(PDFSampler.toNumber(v));
        return (isFinite(n) && n > 0) ? Math.min(n, nTimeSteps) : 0;
      });
    } else {
      // Without n_times, use the number of padded columns as nIter and scan each column.
      nIter       = nIterPad;
      iterLengths = [];
      for (let k = 0; k < nIter; k++) {
        let len = 0, prev = -Infinity;
        for (let t_i = 0; t_i < nTimeSteps; t_i++) {
          const v = flat[t_i * nIterPad + k];
          if (v > prev) { len = t_i + 1; prev = v; } else { break; }
        }
        iterLengths.push(len || 1);
      }
    }

    // Build matrix[k] = iteration k's time series (column k, first iterLengths[k] rows).
    const matrix = [];
    for (let k = 0; k < nIter; k++) {
      const iterLen = iterLengths[k];
      const col = new Array(iterLen);
      for (let t_i = 0; t_i < iterLen; t_i++) {
        col[t_i] = flat[t_i * nIterPad + k];
      }
      matrix.push(col);
    }

    return { matrix, nIter, maxLen: nIterPad, iterLengths };
  } catch (e) {
    console.warn('Could not read probabilistic time matrix:', e);
    return null;
  }
}

/**
 * Return the effective (monotonically-increasing) length of a single iteration
 * row from the probabilistic time matrix.
 * The series ends at the last position where each value is strictly larger than
 * the previous one; padding values (equal or smaller) are excluded.
 *
 * @param {number[]} timeRow - One row from the time matrix
 * @returns {number} Number of valid time points (≥ 1)
 */
function getProbTimeIterLength(timeRow) {
  if (!Array.isArray(timeRow) || timeRow.length === 0) return 0;
  let len = 1;
  for (let i = 1; i < timeRow.length; i++) {
    if (timeRow[i] >= timeRow[i - 1]) {
      len = i + 1;
    } else {
      break;
    }
  }
  return len;
}

/**
 * Get the unit string from the '/time' dataset's 'unit' attribute.
 * Used for labeling the x-axis on time-dependent charts.
 * 
 * @param {Object} file - h5wasm File object
 * @returns {string} Time unit string (e.g., 'years', 's'), or empty string if not found
 */
function getTimeUnit(file) {
  try {
    const timeDataset = FileService.get(file, '/time');
    const unit = getAttr(timeDataset, 'unit');
    return unit !== undefined && unit !== null ? unit : '';
  } catch (e) {
    console.warn('Could not read time unit:', e);
  }
  return '';
}

/**
 * Check if a dataset has the 'time_dependent' attribute set to a truthy value.
 * Datasets marked as time-dependent are eligible for time-series plotting.
 * 
 * @param {Object} dataset - h5wasm Dataset object with attrs property
 * @returns {boolean} True if the dataset has time_dependent=true/1/'TRUE'/'True'
 */
function isTimeDependent(dataset) {
  try {
    const val = getAttr(dataset, 'time_dependent');
    return isTruthyAttribute(val);
  } catch (e) {
    console.warn('Error checking time_dependent attribute:', e);
  }
  return false;
}

/**
 * Check if a group contains data suitable for special time-chart plotting.
 * A qualifying group must have:
 * - IndexLists attribute containing 'Radionuclides', 'Repositories', 'NHB', or 'exposed_groups'
 * - time_dependent attribute set to true
 * 
 * These groups get special treatment: all child datasets are plotted together
 * with colored line styles.
 * 
 * @param {Object} file - h5wasm File object
 * @param {string} path - HDF5 path to the group
 * @returns {boolean} True if the group is a radionuclides data container
 */
function checkGroupForRadionuclides(file, path) {
  try {
    const group = FileService.get(file, path);
    if (!group || group.type.toLowerCase() !== 'group') {
      return false;
    }
    
    const chartIndexNames = ['Radionuclides', 'Repositories', 'NHB', 'exposed_groups'];
    let hasRadionuclidesIndex = false;
    let isTimeDependentGroup = false;
    
    if (group.attrs && typeof group.attrs === 'object') {
      for (const attrName in group.attrs) {
        if (attrName === 'IndexLists') {
          const attrObj = group.attrs[attrName];
          if (attrObj && attrObj.value !== null && typeof attrObj.value !== 'undefined') {
            const value = attrObj.value;
            if (Array.isArray(value) && value.some(v => chartIndexNames.includes(v))) {
              hasRadionuclidesIndex = true;
            } else if (typeof value === 'string' && chartIndexNames.includes(value)) {
              hasRadionuclidesIndex = true;
            }
          }
        }
        
        if (attrName === 'time_dependent') {
          const attrObj = group.attrs[attrName];
          if (attrObj && typeof attrObj.value !== 'undefined') {
            const value = attrObj.value;
            isTimeDependentGroup = value === true || value === 1 || value === 'TRUE' || value === 'True';
          }
        }
      }
    }
    
    return hasRadionuclidesIndex && isTimeDependentGroup;
  } catch (e) {
    console.warn('Error checking group for radionuclides:', e);
    return false;
  }
}


