/* ==========================================================================
   SKB REFERENCE CHECKER — boot

   Everything the page does at load: rule metadata, the self-tests, the event
   wiring and the initial UI state, in the order they ran when this was one
   script.

   They are gathered here because a function declaration hoists only to the top
   of its own script. Several of these calls are to functions declared in
   modules loaded after the one they sat in, which worked while everything
   shared a single script and would not once it did not.

   This is the one module with no template literal in it, so unlike the rest
   it is not held at the indentation of the <script> block it came from.
   ========================================================================== */
'use strict';

/* Give every rule its id, name and legacy ids before anything reads them. */
ensureRuleMetadata(FORBIDDEN_WORD_RULES, 'review', { category: 'terminology', severity: 'review', flags: 'gu' });
ensureRuleMetadata(POTENTIAL_INVALID_CITATION_RULES, 'citation', { category: 'citation', severity: 'warning', flags: 'gu' });
ensureRuleMetadata(OFFICIAL_SKB_TEXT_RULES, 'official', { category: 'technical', severity: 'warning', flags: 'gu' });

/* Self-tests. They report through the console and block nothing. */
runReviewRuleRegressionTests();
runConsolidatedRegressionTests();
runReferenceHeadingSelectionRegressionTests();
runLanguageRegressionTests();

/* Event wiring, and the initial state of the Zotero settings panel. */
dropzone.addEventListener('dragover', event => { event.preventDefault(); dropzone.classList.add('drag-over'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag-over'));
/* zotero.sqlite (and its -wal) may be dropped with the document. */
dropzone.addEventListener('drop', event => {
  event.preventDefault();
  dropzone.classList.remove('drag-over');
  const files = [...event.dataTransfer.files];
  if (files.some(isZoteroDatabaseFile)) addZoteroDatabaseFiles(files.filter(isZoteroDatabaseFile));
  const report = files.find(file => !isZoteroDatabaseFile(file));
  if (report) handleFile(report);
});
dropzone.addEventListener('click', event => { if (!event.target.closest('button') && event.target !== fileInput) fileInput.click(); });
$('choose-file-btn').addEventListener('click', event => { event.stopPropagation(); fileInput.click(); });
fileInput.addEventListener('change', () => { if (fileInput.files[0]) handleFile(fileInput.files[0]); });
resetBtn.addEventListener('click', resetUI);
downloadResultsBtn.addEventListener('click', downloadAnalysisReport);
downloadRuleSummaryBtn.addEventListener('click', downloadRuleSummaryCsv);
results.addEventListener('click', handleInlineZoteroClick);
results.addEventListener('click', handleRuleLocationClick);
results.addEventListener('change', handleRuleSummaryFilter);
results.addEventListener('change', handleZoteroFilterChange);
zoteroSourceType.addEventListener('change', updateZoteroSettingsVisibility);
zoteroAuthType.addEventListener('change', updateZoteroSettingsVisibility);
$('zotero-save-settings').addEventListener('click', applyZoteroSettings);
zoteroTestLocalAccess.addEventListener('click', testLocalZoteroAccess);
$('zotero-reset-settings').addEventListener('click', restoreDefaultZoteroSettings);
$('zotero-db-open').addEventListener('click', () => zoteroDbFile.click());
zoteroDbFile.addEventListener('change', async () => { const files = [...zoteroDbFile.files]; zoteroDbFile.value = ''; await addZoteroDatabaseFiles(files); });
zoteroDbDrop.addEventListener('dragover', event => { event.preventDefault(); zoteroDbDrop.classList.add('drag-over'); });
zoteroDbDrop.addEventListener('dragleave', () => zoteroDbDrop.classList.remove('drag-over'));
zoteroDbDrop.addEventListener('drop', event => { event.preventDefault(); zoteroDbDrop.classList.remove('drag-over'); addZoteroDatabaseFiles(event.dataTransfer.files); });
updateZoteroSettingsVisibility();
runCitationDisplayRegressionTests();

/* Last: these read the DOM and localStorage the panels above set up. */
initialiseRulePackControls();
runGuideFixtureRegressionTests();
runReferenceGuideRegressionTests();
runDesignationRegressionTests();
runAbbreviatedNameRegressionTests();
runZoteroMatchingRegressionTests();
