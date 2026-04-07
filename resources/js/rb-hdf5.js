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


