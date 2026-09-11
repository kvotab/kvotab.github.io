/* ==========================================================================
   SKB REFERENCE CHECKER — shell

   Analysis state, and the status line, progress bar and reset that frame
   every run.

   Part of the page script that used to live inline in skbref.html. The
   modules share one global scope, as classic scripts do, and are loaded in
   the order they were written in; skbref-boot.js runs everything.

   The four-space indent is from the <script> block this came out of, and is
   kept deliberately: removing it would also remove four spaces from every
   line inside a multi-line template literal, changing the whitespace of the
   HTML this page generates.
   ========================================================================== */
'use strict';

    let currentReport = null;
    let currentRuleFindings = { official: [], citation: [], review: [] };
    let currentRefEntries = [];
    let currentFilename = '';
    const activeInlineZoteroSearches = new Map();
    const zoteroSearchCache = new Map();


    function showStatus(message) { statusMsg.textContent = message; statusBar.classList.add('show'); }
    function hideStatus() { statusBar.classList.remove('show'); }
    function setProgress(value, indeterminate = false) {
      progressTrack.classList.add('show');
      progressTrack.classList.toggle('indeterminate', indeterminate);
      const safeValue = Math.max(0, Math.min(100, Number(value) || 0));
      progressFill.style.width = indeterminate ? '' : `${safeValue}%`;
      progressTrack.setAttribute('aria-valuenow', String(Math.round(safeValue)));
    }
    function hideProgress() {
      progressTrack.classList.remove('show', 'indeterminate');
      progressFill.style.width = '0%';
      progressTrack.setAttribute('aria-valuenow', '0');
    }
    function yieldToBrowser() { return new Promise(resolve => setTimeout(resolve, 0)); }
    function withTimeout(promise, milliseconds, message) {
      let timer;
      const timeout = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), milliseconds); });
      return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
    }

    function resetUI() {
      for (const controller of activeInlineZoteroSearches.values()) controller.abort();
      activeInlineZoteroSearches.clear();
      dropzone.style.display = '';
      statusBar.classList.remove('show');
      docInfo.classList.remove('show');
      renderFormatNotice(null);
      summaryCards.classList.remove('show');
      results.innerHTML = '';
      hideProgress();
      resultActions.classList.remove('show');
      resetBtn.classList.remove('show');
      fileInput.value = '';
      currentReport = null;
      currentRuleFindings = { official: [], citation: [], review: [] };
      currentRefEntries = [];
      currentFilename = '';
    }
