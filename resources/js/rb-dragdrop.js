/* ==========================================================================
   13. DRAG & DROP FILE LOADING
   ========================================================================== */

/**
 * Prevent default browser behavior for drag events.
 * Required to enable custom drop handling for HDF5 files.
 * 
 * @param {Event} e - Drag event to prevent
 * @returns {void}
 */
function preventDefaults(e) {
  e.preventDefault();
  e.stopPropagation();
}

/*
 * Drag & Drop Event Registration
 * 
 * Uses a dragCounter to track nested drag enter/leave events,
 * ensuring the overlay is only hidden when the drag truly leaves
 * the document (not just moving between child elements).
 */
['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
  document.body.addEventListener(eventName, preventDefaults, false);
});

document.body.addEventListener('dragenter', (e) => {
  dragCounter++;
  document.getElementById('dropOverlay').classList.add('active');
});

document.body.addEventListener('dragleave', (e) => {
  dragCounter--;
  if (dragCounter === 0) {
    document.getElementById('dropOverlay').classList.remove('active');
  }
});

document.body.addEventListener('drop', (e) => {
  dragCounter = 0;
  document.getElementById('dropOverlay').classList.remove('active');
  
  const dt = e.dataTransfer;
  const files = dt.files;
  if (files.length > 0) {
    document.getElementById('fileInput').files = files;
    const event = new Event('change', { bubbles: true });
    document.getElementById('fileInput').dispatchEvent(event);
  }
});


