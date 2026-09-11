/* ==========================================================================
   SKB REFERENCE CHECKER — config

   Element handles, Zotero endpoint configuration and the settings defaults.

   Part of the page script that used to live inline in skbref.html. The
   modules share one global scope, as classic scripts do, and are loaded in
   the order they were written in; skbref-boot.js runs everything.

   The four-space indent is from the <script> block this came out of, and is
   kept deliberately: removing it would also remove four spaces from every
   line inside a multi-line template literal, changing the whitespace of the
   HTML this page generates.
   ========================================================================== */
'use strict';

    const $ = id => document.getElementById(id);
    const dropzone = $('dropzone');
    const fileInput = $('file-input');
    const statusBar = $('status-bar');
    const statusMsg = $('status-msg');
    const docInfo = $('doc-info');
    const summaryCards = $('summary-cards');
    const results = $('results');
    const resetBtn = $('reset-btn');
    const progressTrack = $('progress-track');
    const progressFill = $('progress-fill');
    const resultActions = $('result-actions');
    const downloadResultsBtn = $('download-results-btn');
    const downloadRuleSummaryBtn = $('download-rule-summary-btn');
    const zoteroFuzzyMatch = $('zotero-fuzzy-match');
    const zoteroSourceType = $('zotero-source-type');
    const zoteroGroupId = $('zotero-group-id');
    const zoteroUserId = $('zotero-user-id');
    const zoteroCustomUrl = $('zotero-custom-url');
    const zoteroLocalUrl = $('zotero-local-url');
    const zoteroAuthType = $('zotero-auth-type');
    const zoteroApiKey = $('zotero-api-key');
    const zoteroUsername = $('zotero-username');
    const zoteroPassword = $('zotero-password');
    const zoteroSettingsStatus = $('zotero-settings-status');
    const zoteroTestLocalAccess = $('zotero-test-local-access');

    const ZOTERO_CONFIG = Object.freeze({
      groupId: '6640399', apiVersion: '3', minimumScore: 45,
      maximumCandidates: 5, searchResultLimit: 15,
      searchTimeoutMilliseconds: 30000,
      maximumOrphanLookups: 5, maximumUncitedLookups: 5
    });

    const DEFAULT_ZOTERO_SETTINGS = Object.freeze({
      sourceType: 'public-group',
      groupId: ZOTERO_CONFIG.groupId,
      userId: '',
      customUrl: '',
      localUrl: 'http://localhost:23119/api/users/0/items/top',
      authType: 'none',
      apiKey: '',
      username: '',
      password: ''
    });

    let activeZoteroSettings = { ...DEFAULT_ZOTERO_SETTINGS };
    const zoteroFormattedReferenceStore = new Map();
