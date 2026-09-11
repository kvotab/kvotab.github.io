/* ==========================================================================
   SKB REFERENCE CHECKER — zotero

   The Zotero client: settings, endpoints, search, and scoring a candidate
   against a reference or a citation.

   Part of the page script that used to live inline in skbref.html. The
   modules share one global scope, as classic scripts do, and are loaded in
   the order they were written in; skbref-boot.js runs everything.

   The four-space indent is from the <script> block this came out of, and is
   kept deliberately: removing it would also remove four spaces from every
   line inside a multi-line template literal, changing the whitespace of the
   HTML this page generates.
   ========================================================================== */
'use strict';

    function initialiseRulePackControls() {
      loadedRulePacks = readStoredRulePacks()
        .map(pack => { try { return normaliseRulePack(pack, pack.name); } catch (error) { return null; } })
        .filter(Boolean);
      renderRulePackList();

      const input = document.getElementById('rule-pack-input');
      document.getElementById('rule-pack-load')?.addEventListener('click', () => input?.click());
      input?.addEventListener('change', async () => {
        await addRulePackFiles([...input.files]);
        input.value = '';
      });
      document.getElementById('rule-pack-export')?.addEventListener('click', exportRulePacks);
      document.getElementById('rule-pack-list')?.addEventListener('change', async event => {
        const index = event.target?.dataset?.packIndex;
        if (index === undefined) return;
        loadedRulePacks[Number(index)].enabled = event.target.checked;
        storeRulePacks();
        renderRulePackList();
        await reanalyseCurrentDocument();
      });
      document.getElementById('rule-pack-list')?.addEventListener('click', async event => {
        const index = event.target?.dataset?.removePack;
        if (index === undefined) return;
        loadedRulePacks.splice(Number(index), 1);
        storeRulePacks();
        renderRulePackList();
        await reanalyseCurrentDocument();
      });
    }

    function updateZoteroSettingsVisibility() {
      const source = zoteroSourceType.value;
      document.querySelector('[data-setting="group-id"]').hidden = !['public-group', 'web-group'].includes(source);
      document.querySelector('[data-setting="user-id"]').hidden = source !== 'web-user';
      document.querySelector('[data-setting="custom-url"]').hidden = source !== 'custom';
      document.querySelector('[data-setting="local-url"]').hidden = source !== 'local';
      zoteroTestLocalAccess.hidden = source !== 'local';

      if (source === 'local') {
        zoteroAuthType.value = 'none';
        zoteroAuthType.disabled = true;
      } else {
        zoteroAuthType.disabled = false;
      }

      const auth = zoteroAuthType.value;
      document.querySelector('[data-setting="api-key"]').hidden = auth !== 'api-key';
      document.querySelector('[data-setting="username"]').hidden = auth !== 'basic';
      document.querySelector('[data-setting="password"]').hidden = auth !== 'basic';
    }

    async function getLocalNetworkPermissionState() {
      if (!navigator.permissions?.query) return 'unknown';
      try {
        const result = await navigator.permissions.query({
          name: 'local-network-access'
        });
        return result.state;
      } catch {
        return 'unknown';
      }
    }

    async function testLocalZoteroAccess() {
      const endpoint = zoteroLocalUrl.value.trim();
      if (!/^https?:\/\//i.test(endpoint)) {
        zoteroSettingsStatus.textContent = 'Enter a complete local API URL first.';
        return;
      }

      zoteroTestLocalAccess.disabled = true;
      const permissionBefore = await getLocalNetworkPermissionState();
      zoteroSettingsStatus.textContent = permissionBefore === 'denied'
        ? 'Local network access is denied for this site. Change the permission in Edge site settings.'
        : 'Requesting access to Zotero on this computer…';

      try {
        const testUrl = new URL(endpoint);
        testUrl.searchParams.set('format', 'json');
        testUrl.searchParams.set('limit', '1');
        testUrl.searchParams.set('v', ZOTERO_CONFIG.apiVersion);

        const response = await fetch(testUrl, {
          method: 'GET',
          headers: { Accept: 'application/json' },
          targetAddressSpace: 'loopback'
        });

        if (!response.ok) {
          throw new Error(`Zotero local API returned HTTP ${response.status}.`);
        }

        zoteroSettingsStatus.textContent = 'Local Zotero access is working.';
      } catch (error) {
        const permissionAfter = await getLocalNetworkPermissionState();
        if (permissionAfter === 'denied') {
          zoteroSettingsStatus.textContent = 'Edge denied local network access for this site. Allow it in Site permissions → Local network access, then retry.';
        } else {
          zoteroSettingsStatus.textContent = 'Local Zotero access failed. Ensure Zotero is running, local API access is enabled, and Edge permits kvotab.se to access devices on the local network.';
        }
        console.warn('Local Zotero access test failed:', error);
      } finally {
        zoteroTestLocalAccess.disabled = false;
      }
    }

    function readZoteroSettingsForm() {
      return {
        sourceType: zoteroSourceType.value,
        groupId: zoteroGroupId.value.trim(),
        userId: zoteroUserId.value.trim(),
        customUrl: zoteroCustomUrl.value.trim(),
        localUrl: zoteroLocalUrl.value.trim(),
        authType: zoteroAuthType.value,
        apiKey: zoteroApiKey.value,
        username: zoteroUsername.value,
        password: zoteroPassword.value
      };
    }

    function validateZoteroSettings(settings) {
      if (['public-group', 'web-group'].includes(settings.sourceType) && !/^\d+$/.test(settings.groupId)) {
        throw new Error('Enter a numeric Zotero group ID.');
      }
      if (settings.sourceType === 'web-user' && !/^\d+$/.test(settings.userId)) {
        throw new Error('Enter a numeric Zotero user ID.');
      }
      if (settings.sourceType === 'custom' && !/^https?:\/\//i.test(settings.customUrl)) {
        throw new Error('Enter a complete HTTP or HTTPS custom endpoint URL.');
      }
      if (settings.sourceType === 'local' && !/^https?:\/\//i.test(settings.localUrl)) {
        throw new Error('Enter a complete local API URL.');
      }
      if (settings.authType === 'api-key' && !settings.apiKey) {
        throw new Error('Enter an API key or token.');
      }
      if (settings.authType === 'basic' && (!settings.username || !settings.password)) {
        throw new Error('Enter both username and password.');
      }
    }

    function applyZoteroSettings() {
      try {
        const settings = readZoteroSettingsForm();
        validateZoteroSettings(settings);
        if (settings.sourceType === 'local') {
          settings.authType = 'none';
          settings.apiKey = '';
          settings.username = '';
          settings.password = '';
        }
        activeZoteroSettings = settings;
        zoteroSearchCache.clear();
        zoteroSettingsStatus.textContent = settings.sourceType === 'local' && location.protocol === 'file:'
          ? 'Applied. Note: local API access may require serving this page from http://localhost.'
          : 'Settings applied.';
        setTimeout(() => { zoteroSettingsStatus.textContent = ''; }, 2500);
      } catch (error) {
        zoteroSettingsStatus.textContent = error.message;
      }
    }

    function restoreDefaultZoteroSettings() {
      activeZoteroSettings = { ...DEFAULT_ZOTERO_SETTINGS };
      zoteroSourceType.value = activeZoteroSettings.sourceType;
      zoteroGroupId.value = activeZoteroSettings.groupId;
      zoteroUserId.value = '';
      zoteroCustomUrl.value = '';
      zoteroLocalUrl.value = activeZoteroSettings.localUrl;
      zoteroAuthType.value = 'none';
      zoteroApiKey.value = '';
      zoteroUsername.value = '';
      zoteroPassword.value = '';
      zoteroSearchCache.clear();
      updateZoteroSettingsVisibility();
      zoteroSettingsStatus.textContent = 'Default public group restored.';
      setTimeout(() => { zoteroSettingsStatus.textContent = ''; }, 2500);
    }

    function getZoteroItemsEndpoint(settings) {
      switch (settings.sourceType) {
        case 'web-group':
        case 'public-group':
          return `https://api.zotero.org/groups/${encodeURIComponent(settings.groupId)}/items/top`;
        case 'web-user':
          return `https://api.zotero.org/users/${encodeURIComponent(settings.userId)}/items/top`;
        case 'local':
          return settings.localUrl;
        case 'custom':
          return settings.customUrl;
        default:
          throw new Error('Unsupported Zotero database source.');
      }
    }

    function getZoteroItemEndpoint(settings, itemKey) {
      const source = getZoteroItemsEndpoint(settings);
      const url = new URL(source);
      url.search = '';
      url.pathname = url.pathname.replace(/\/items\/top\/?$/i, '/items').replace(/\/$/, '');
      if (!/\/items$/i.test(url.pathname)) {
        if (/\/items\//i.test(url.pathname)) url.pathname = url.pathname.replace(/\/items\/.*$/i, '/items');
        else url.pathname += '/items';
      }
      url.pathname += `/${encodeURIComponent(itemKey)}`;
      return url;
    }

    async function fetchZoteroItemByKey(itemKey, signal) {
      const settings = activeZoteroSettings;
      const url = getZoteroItemEndpoint(settings, itemKey);
      url.searchParams.set('format', 'json');
      if (settings.sourceType === 'local') url.searchParams.set('v', ZOTERO_CONFIG.apiVersion);
      const response = await fetch(url, {
        headers: createZoteroRequestHeaders(settings),
        signal,
        ...(settings.sourceType === 'local' ? { targetAddressSpace: 'loopback' } : {})
      });
      if (!response.ok) throw new Error(`Zotero item ${itemKey} returned HTTP ${response.status}`);
      const item = await response.json();
      if (!item?.data) throw new Error(`Zotero item ${itemKey} returned incomplete metadata`);
      return item;
    }

    async function findCandidatesFromZoteroField(citation, scorer, signal) {
      const keys = [...new Set(citation.zoteroItemKeys || [])];
      if (!keys.length) return { candidates: [], failures: [] };
      const candidates = [], failures = [];
      for (const itemKey of keys) {
        try {
          const item = await fetchZoteroItemByKey(itemKey, signal);
          const candidate = prepareZoteroItems([item])[0];
          const scored = scorer(citation, candidate);
          candidates.push({
            ...candidate,
            ...scored,
            score: 100,
            reasons: ['linked Zotero citation field', ...(scored.reasons || [])],
            directFieldLink: true
          });
        } catch (error) {
          if (error.name === 'AbortError') throw error;
          failures.push(`${itemKey}: ${error.message}`);
        }
      }
      candidates.sort((a,b) => {
        const aScore = scorer(citation,a).score, bScore = scorer(citation,b).score;
        return bScore - aScore;
      });
      /* A grouped Zotero field can contain several items. Keep the item(s) that
         best fit the selected citation key, while retaining all on a tie. */
      if (candidates.length > 1) {
        const best = scorer(citation,candidates[0]).score;
        return { candidates: candidates.filter(item => scorer(citation,item).score === best), failures };
      }
      return { candidates, failures };
    }

    function createZoteroRequestHeaders(settings) {
      /*
        The local Zotero API is read-only and requires no authentication.
        Avoid custom headers for local reads: a Zotero-API-Version header
        triggers a browser CORS preflight that the localhost service may not
        answer for pages opened from file:// (origin null).
      */
      const headers = {
        Accept: 'application/json'
      };

      if (settings.sourceType !== 'local') {
        headers['Zotero-API-Version'] = ZOTERO_CONFIG.apiVersion;
      }

      if (settings.sourceType === 'local') {
        return headers;
      }

      if (settings.authType === 'api-key') {
        if (settings.sourceType === 'web-group' || settings.sourceType === 'web-user' || settings.sourceType === 'public-group') {
          headers['Zotero-API-Key'] = settings.apiKey;
        } else {
          headers.Authorization = `Bearer ${settings.apiKey}`;
        }
      } else if (settings.authType === 'basic') {
        headers.Authorization = `Basic ${btoa(unescape(encodeURIComponent(`${settings.username}:${settings.password}`)))}`;
      }

      return headers;
    }

    async function searchZoteroItems(
      query,
      { qmode = 'titleCreatorYear', limit = 15, timeoutMilliseconds = 30000, signal } = {}
    ) {
      const cleaned = String(query || '').replace(/\s+/g, ' ').trim();
      if (!cleaned) return [];

      const settings = activeZoteroSettings;
      const endpoint = getZoteroItemsEndpoint(settings);
      const cacheKey = `${settings.sourceType}|${endpoint}|${qmode}|${cleaned.toLowerCase()}`;
      if (zoteroSearchCache.has(cacheKey)) return zoteroSearchCache.get(cacheKey);

      const parameters = new URLSearchParams({
        format: 'json', include: 'data', q: cleaned, qmode,
        itemType: '-attachment', limit: String(limit)
      });

      if (settings.sourceType === 'local') {
        parameters.set('v', ZOTERO_CONFIG.apiVersion);
      }
      const timeoutController = new AbortController();
      const abortFromCaller = () => timeoutController.abort();
      signal?.addEventListener('abort', abortFromCaller, { once: true });
      const timer = setTimeout(() => timeoutController.abort(), timeoutMilliseconds);

      try {
        const response = await fetch(
          `${endpoint}${endpoint.includes('?') ? '&' : '?'}${parameters}`,
          {
            headers: createZoteroRequestHeaders(settings),
            signal: timeoutController.signal,
            ...(settings.sourceType === 'local'
              ? { targetAddressSpace: 'loopback' }
              : {})
          }
        );
        if (!response.ok) throw new Error(`Zotero API returned HTTP ${response.status}`);
        const returned = await response.json();
        if (!Array.isArray(returned)) throw new Error('Zotero returned an unexpected response.');
        const items = returned.filter(item => !['attachment', 'note', 'annotation'].includes(item?.data?.itemType));
        zoteroSearchCache.set(cacheKey, items);
        return items;
      } catch (error) {
        if (error.name === 'AbortError') throw error;

        if (settings.sourceType === 'local' && error instanceof TypeError) {
          const originAdvice = location.protocol === 'file:'
            ? ' This page is opened with file://. Serve the folder over http://localhost instead, then reload the page.'
            : ' Edge may have denied Local Network Access for this site. Open Zotero settings and use “Request/test local access”, or allow this site in Edge Site permissions → Local network access.';
          throw new Error(
            'The browser could not access the Zotero local API. Confirm that Zotero is running and that “Allow other applications on this computer to communicate with Zotero” is enabled.' +
            originAdvice
          );
        }

        throw error;
      } finally {
        clearTimeout(timer);
        signal?.removeEventListener('abort', abortFromCaller);
      }
    }

    function buildZoteroQueriesForCitation(citation){
      const key=String(citation.key||'').trim(); if(!key)return[];
      if(citation.type==='skb-report')return[{query:key.replace(/^SKB\s+/i,''),qmode:'everything'}];
      /* A designation is an identifier; searching it whole is the strongest query. */
      if(citation.type==='designation')return dedupeQueries([{query:key,qmode:'everything'},{query:key.replace(/^\S+\s+/,''),qmode:'everything'},{query:key,qmode:'titleCreatorYear'}]);
      const year=key.match(/\b(?:1[89]\d{2}|20\d{2})[a-z]?\b/i)?.[0]||'';
      const authorText=key.replace(/\s+(?:1[89]\d{2}|20\d{2})[a-z]?\s*$/i,'').replace(/\bet\s+al\.?|\bm\.fl\.?/gi,'').trim();
      const authors=authorText.split(/\s+(?:and|och|&)\s+/i).map(value=>value.trim()).filter(Boolean);
      const compact=[...authors,year].filter(Boolean).join(' ');
      const queries=[
        {query:key,qmode:'everything'},
        {query:compact,qmode:'titleCreatorYear'},
        ...authors.map(author=>({query:[author,year].filter(Boolean).join(' '),qmode:'titleCreatorYear'}))
      ];
      return dedupeQueries(queries);
    }
    function buildZoteroQueriesForReference(entry){ const title=getDocumentReferenceTitle(entry).split(/\s+/).filter(Boolean).slice(0,12).join(' '); const report=getDocumentReferenceReportKey(entry); const key=String(entry.key||'').replace(/\bet\s+al\.?|\bm\.fl\.?/gi,'').replace(/(?:\band\b|\boch\b|&)/gi,' ').replace(/\s+/g,' ').trim(); return dedupeQueries([{query:title,qmode:'titleCreatorYear'},{query:report?.replace(/^SKB\s+/i,''),qmode:'everything'},{query:key,qmode:'titleCreatorYear'}]); }
    function dedupeQueries(queries){ const seen=new Set(); return queries.filter(item=>{ if(!item.query)return false; const key=`${item.qmode}|${item.query.toLowerCase()}`; if(seen.has(key))return false; seen.add(key); return true; }); }
    function buildZoteroQueriesForFullReference(entry) {
      const queries = [];
      const reportKey = getDocumentReferenceReportKey(entry);
      const title = getDocumentReferenceTitle(entry);
      const authorYear = extractAuthorYearKey(entry.body) || entry.key || '';
      const year = getDocumentReferenceYear(entry) || '';
      const firstAuthor = extractFirstAuthorSurname(entry.body, authorYear);

      // Identifier query: strongest when Zotero quick search indexes the field.
      if (reportKey) {
        queries.push({
          query: reportKey.replace(/^SKB\s+/i, ''),
          qmode: 'everything'
        });
      }

      // Normalize punctuation and dash variants before title quick search.
      const normalizedTitle = normaliseTitle(title);
      if (normalizedTitle) {
        queries.push({ query: normalizedTitle, qmode: 'titleCreatorYear' });
      }

      // Short creator/year searches are more robust than one long combined query.
      if (firstAuthor && year) {
        queries.push({ query: `${firstAuthor} ${year}`, qmode: 'titleCreatorYear' });
      }
      if (firstAuthor) {
        queries.push({ query: firstAuthor, qmode: 'titleCreatorYear' });
      }
      if (authorYear) {
        queries.push({ query: authorYear, qmode: 'titleCreatorYear' });
      }

      return dedupeQueries(queries);
    }

    function extractFirstAuthorSurname(referenceText, authorYearKey = '') {
      const commaMatch = String(referenceText).match(/^\s*([^,]+),/);
      if (commaMatch) {
        const words = stripCreatorRoleSuffix(commaMatch[1]).split(/\s+/);
        while (words.length > 1 && isAuthorInitial(words.at(-1))) words.pop();
        if (words.length) return words.join(' ');
      }
      return String(authorYearKey)
        .replace(/\bet\s+al\.?/gi, '')
        .replace(/\bm\.fl\.?/gi, '')
        .replace(/\s+(?:1[89]\d{2}|20\d{2})[a-z]?.*$/i, '')
        .trim()
        .split(/\s+(?:and|och|&)\s+/i)[0]
        .trim();
    }

    async function findZoteroCandidates(queries, source, scoreFunction, signal) {
      const candidates = new Map();
      for (const search of queries) {
        if (signal.aborted) throw new DOMException('Search canceled', 'AbortError');
        let items = [];
        try {
          items = await searchZoteroItems(search.query, {
            qmode: search.qmode,
            limit: ZOTERO_CONFIG.searchResultLimit,
            timeoutMilliseconds: ZOTERO_CONFIG.searchTimeoutMilliseconds,
            signal
          });
        } catch (error) {
          if (error.name === 'AbortError') throw error;
          console.warn('Zotero query failed:', search.query, error);
          continue;
        }
        for (const candidate of prepareZoteroItems(items)) {
          const scored = scoreFunction(source, candidate);
          const existing = candidates.get(candidate.key);
          if (!existing || scored.score > existing.score) {
            candidates.set(candidate.key, { ...candidate, ...scored });
          }
        }
      }
      const minimumScore = zoteroFuzzyMatch.checked
        ? ZOTERO_CONFIG.minimumScore
        : 70;
      return [...candidates.values()]
        .filter(candidate => candidate.score >= minimumScore)
        .sort((a, b) => b.score - a.score)
        .slice(0, ZOTERO_CONFIG.maximumCandidates);
    }

    function handleInlineZoteroClick(event) {
      const copyButton = event.target.closest('.zotero-copy-reference');
      if (copyButton) {
        copyFormattedZoteroReference(copyButton);
        return;
      }
      const button = event.target.closest('.zotero-row-btn');
      if (!button) return;
      const searchId = button.dataset.searchId;
      if (activeInlineZoteroSearches.has(searchId)) {
        activeInlineZoteroSearches.get(searchId).abort();
        return;
      }
      if (button.dataset.kind === 'reference') {
        runReferenceZoteroSearch(Number(button.dataset.index), button);
      } else {
        runCitationZoteroSearch(Number(button.dataset.index), button);
      }
    }

    async function runReferenceZoteroSearch(index, button) {
      const entry = currentRefEntries[index];
      if (!entry) return;
      await runInlineZoteroSearch({
        source: entry,
        queries: buildZoteroQueriesForFullReference(entry),
        scorer: scoreDocumentReferenceAgainstZotero,
        button,
        emptyMessage: 'No probable Zotero match found for this reference.'
      });
    }

    async function runCitationZoteroSearch(index, button) {
      const citation = currentReport?.orphanCites?.[index];
      if (!citation) return;
      await runInlineZoteroSearch({
        source: citation,
        queries: buildZoteroQueriesForCitation(citation),
        scorer: scoreOrphanCitationAgainstZotero,
        button,
        directCitation: citation,
        emptyMessage: citation.citationSource === 'zotero'
          ? 'The Zotero field was detected, but its linked item could not be retrieved from the selected Zotero database and no search fallback matched.'
          : 'No probable Zotero match found for this citation key.'
      });
    }

    async function runInlineZoteroSearch({ source, queries, scorer, button, emptyMessage, directCitation = null }) {
      const searchId = button.dataset.searchId;
      const resultContainer = $(button.dataset.resultId);
      const controller = new AbortController();
      activeInlineZoteroSearches.set(searchId, controller);
      button.classList.add('searching');
      button.textContent = 'Cancel search';
      const modeLabel = zoteroFuzzyMatch.checked ? 'fuzzy matching enabled' : 'strict matching';
      const directKeys = directCitation?.zoteroItemKeys || [];
      resultContainer.innerHTML = `<div class="zotero-inline-status">${directKeys.length ? 'Retrieving item linked by the Zotero Word field' : `Searching Zotero (${modeLabel})`}…</div>`;

      try {
        let directResult = { candidates: [], failures: [] };
        if (directCitation?.citationSource === 'zotero' && directKeys.length) {
          directResult = await findCandidatesFromZoteroField(directCitation, scorer, controller.signal);
        }
        if (directResult.candidates.length) {
          resultContainer.innerHTML = `<div class="zotero-inline-status">Matched directly through ADDIN ZOTERO_ITEM CSL_CITATION.</div>${directResult.candidates.map(buildInlineZoteroCandidate).join('')}`;
        } else {
          const candidates = await findZoteroCandidates(queries, source, scorer, controller.signal);
          const directWarning = directResult.failures.length
            ? `<div class="zotero-inline-status">Direct Zotero field lookup failed (${escHtml(directResult.failures.join('; '))}). Search fallback was used.</div>` : '';
          resultContainer.innerHTML = directWarning + (candidates.length
            ? candidates.map(buildInlineZoteroCandidate).join('')
            : `<div class="zotero-inline-status">${escHtml(emptyMessage)}</div>`);
        }
      } catch (error) {
        resultContainer.innerHTML = error.name === 'AbortError'
          ? '<div class="zotero-inline-status">Search canceled.</div>'
          : `<div class="zotero-inline-status">Search failed: ${escHtml(error.message)}</div>`;
      } finally {
        activeInlineZoteroSearches.delete(searchId);
        button.classList.remove('searching');
        button.textContent = 'Check Zotero';
      }
    }

    /*
      The record link is the one place a value from the Zotero endpoint is used
      as a URL rather than as text, and escaping does not help there:
      "javascript:alert(1)" contains nothing escHtml would touch, so it would
      have been written into the href unchanged. The settings panel lets the
      endpoint be any http(s) address the user names, so the response is not
      trusted to that extent — the scheme is checked instead.
    */
    function zoteroRecordLink(url) {
      const safe = kvotSafeHttpUrl(url);
      if (!safe) return '';
      return `<a href="${escHtml(safe)}" target="_blank" rel="noopener noreferrer">Open Zotero record ↗</a>`;
    }

    function buildInlineZoteroCandidate(candidate) {
      const candidateId = 'zc-' + candidate.key + '-' + Math.random().toString(36).slice(2, 9);
      const formatted = formatSkbReference(candidate.data);
      zoteroFormattedReferenceStore.set(candidateId, formatted);
      return `
        <div class="zotero-candidate" data-zotero-candidate-id="${escHtml(candidateId)}">
          <div class="zotero-candidate-head">
            <div class="zotero-candidate-title">${escHtml(candidate.title || '(untitled Zotero item)')}</div>
            <span class="zotero-probability" title="Match confidence based on title, the complete creator list (author, or the editor when an item records no author), year, and Report Number">${candidate.score}% confidence</span>
          </div>
          <div>${escHtml(candidate.authors.join(', ') || 'No creator recorded')}${candidate.creatorRole && candidate.creatorRole !== 'author' ? ` (${escHtml(candidate.creatorRole)})` : ''} · ${escHtml(candidate.year || 'No year')}</div>
          ${candidate.reportKey ? `<div>Report Number: ${escHtml(candidate.reportKey)}</div>` : ''}
          ${candidate.data?.language ? `<div>Language metadata: ${escHtml(candidate.data.language)}${formatted.languageNote ? ` → ${escHtml(formatted.languageNote)}` : ' → no language note required'}</div>` : '<div>Language metadata: not recorded</div>'}
          <div>Match basis: ${escHtml(candidate.reasons.join(', ') || 'metadata similarity')}</div>
          ${zoteroRecordLink(candidate.url)}
          <div class="zotero-formatted-reference">${formatted.html}</div>
          <button class="zotero-row-btn zotero-copy-reference" type="button" data-candidate-id="${escHtml(candidateId)}">Copy formatted reference</button>
        </div>`;
    }

    function skbText(value) { return String(value || '').replace(/\s+/g, ' ').trim(); }
    function formatSkbName(creator) {
      if (creator.name) return skbText(creator.name);
      const family = skbText(creator.lastName);
      const given = skbText(creator.firstName);
      const initials = given.split(/[\s-]+/).filter(Boolean).map(part => part[0]?.toUpperCase() || '').join(' ');
      return [family, initials].filter(Boolean).join(' ');
    }
    function skbCreators(data, type) { return (data.creators || []).filter(c => c.creatorType === type); }
    function normalizeZoteroLanguage(value) {
      const raw=skbText(value);if(!raw)return{code:'',name:'',isEnglish:false};
      const normalized=raw.toLowerCase().replace(/_/g,'-').replace(/\s+/g,' ').trim(),base=normalized.split('-')[0];
      const aliases={sv:'Swedish',swe:'Swedish',swedish:'Swedish',svenska:'Swedish',en:'English',eng:'English',english:'English',engelska:'English',fi:'Finnish',fin:'Finnish',finnish:'Finnish',de:'German',deu:'German',ger:'German',german:'German',fr:'French',fra:'French',fre:'French',french:'French',da:'Danish',dan:'Danish',danish:'Danish',no:'Norwegian',nor:'Norwegian',norwegian:'Norwegian'};
      const name=aliases[normalized]||aliases[base]||'';return{code:normalized,name,isEnglish:name==='English'};
    }
    function zoteroLanguageNote(value){const language=normalizeZoteroLanguage(value);if(!language.code||language.isEnglish)return'';return `(In ${language.name||skbText(value)}.)`;}
    function formatSkbReference(data) {
      data = data || {};
      let creators = skbCreators(data, 'author');
      let role = '';
      if (!creators.length) { creators = skbCreators(data, 'editor'); role = creators.length ? ' (red)' : ''; }
      if (!creators.length) creators = skbCreators(data, 'translator');
      const author = creators.map(formatSkbName).filter(Boolean).join(', ') + role;
      const year = skbText(data.date).match(/\b(?:1[89]\d{2}|20\d{2})[a-z]?\b/i)?.[0] || 'u å';
      const headText = [author || skbText(data.title) || 'Untitled', year].join(', ') + '.';
      const title = skbText(data.title);
      const type = skbText(data.itemType);
      const parts = [];
      if (title && author) parts.push(title + '.');
      if (['journalArticle','magazineArticle','newspaperArticle'].includes(type)) {
        const journal = skbText(data.publicationTitle);
        const volume = skbText(data.volume);
        const pages = skbText(data.pages);
        const j = [journal, volume].filter(Boolean).join(' ');
        if (j || pages) parts.push([j, pages].filter(Boolean).join(', ') + '.');
        if (data.DOI) parts.push('https://doi.org/' + skbText(data.DOI).replace(/^https?:\/\/(?:dx\.)?doi\.org\//i,''));
      } else if (['book','bookSection','conferencePaper'].includes(type)) {
        const editors = skbCreators(data,'editor').map(formatSkbName).filter(Boolean);
        if (editors.length && type !== 'book') parts.push('I ' + editors.join(', ') + ' (red).');
        const container = skbText(data.bookTitle || data.proceedingsTitle || data.publicationTitle);
        const volume = skbText(data.volume);
        const placePublisher = [skbText(data.place), skbText(data.publisher)].filter(Boolean).join(': ');
        const pages = skbText(data.pages);
        const publication = [ [container,volume].filter(Boolean).join(' '), placePublisher, pages ].filter(Boolean).join(', ');
        if (publication) parts.push(publication + '.');
      } else {
        const number = skbText(data.reportNumber || data.number);
        const archive = [skbText(data.archive), skbText(data.archiveLocation)].filter(Boolean).join(' ');
        const publisher = skbText(data.publisher || data.institution || data.company);
        const tail = [number, archive, publisher].filter(Boolean).join(', ');
        if (tail) parts.push(tail + '.');
      }
      const languageNote=zoteroLanguageNote(data.language);if(languageNote)parts.push(languageNote);
      const plain = [headText, ...parts].join(' ').replace(/\s+/g,' ').trim();
      const html = '<strong>' + escHtml(headText) + '</strong>' + (parts.length ? ' ' + parts.map(escHtml).join(' ') : '');
      return { plain, html, languageNote };
    }

    async function copyFormattedZoteroReference(button) {
      const formatted = zoteroFormattedReferenceStore.get(button.dataset.candidateId);
      if (!formatted) return;
      try {
        if (navigator.clipboard && window.ClipboardItem) {
          await navigator.clipboard.write([new ClipboardItem({
            'text/plain': new Blob([formatted.plain], {type:'text/plain'}),
            'text/html': new Blob([formatted.html], {type:'text/html'})
          })]);
        } else {
          await navigator.clipboard.writeText(formatted.plain);
        }
        const old = button.textContent; button.textContent = 'Copied';
        setTimeout(() => button.textContent = old, 1400);
      } catch {
        const area=document.createElement('textarea'); area.value=formatted.plain; document.body.appendChild(area); area.select(); document.execCommand('copy'); area.remove();
        button.textContent='Copied as plain text'; setTimeout(()=>button.textContent='Copy formatted reference',1400);
      }
    }

    function getZoteroYear(item){return String(item?.data?.date||'').match(/\b(?:1[89]\d{2}|20\d{2})[a-z]?\b/i)?.[0]||null;}
    /*
      The creator roles a reference can be cited under, in the order the SKB
      reference guide falls through them: an item with no author is cited under
      its editor, and one with neither under its translator. formatSkbReference
      already does this when it writes the reference out; matching has to agree
      with it, or an edited volume gets no author-year alias, scores nothing on
      the name comparison, and shows as “No creator recorded” while the document
      cites it as “Nyström (red) 2005”.
    */
    const ZOTERO_CREATOR_TIERS = Object.freeze([
      { role: 'author',      types: ['author', 'bookAuthor', 'reporter', 'inventor', 'programmer'] },
      { role: 'editor',      types: ['editor', 'bookEditor', 'seriesEditor'] },
      { role: 'translator',  types: ['translator'] },
      { role: 'contributor', types: ['contributor'] }
    ]);

    /* An institutional creator is stored single-field, arriving as `name`
       rather than `lastName` — “Svensk Kärnbränslehantering AB” is one name. */
    function zoteroCreatorNames(item, types) {
      return (item?.data?.creators || [])
        .filter(creator => types.includes(creator.creatorType))
        .map(creator => String(creator.lastName || creator.name || '').trim())
        .filter(Boolean);
    }

    /**
     * The names an item would be cited under, plus the role that supplied them.
     *
     * @param {Object} item - A Zotero API item
     * @returns {{names: string[], role: string}} Empty names if no creator at all
     */
    function getZoteroCreators(item) {
      for (const tier of ZOTERO_CREATOR_TIERS) {
        const names = zoteroCreatorNames(item, tier.types);
        if (names.length) return { names, role: tier.role };
      }
      return { names: [], role: '' };
    }

    function getZoteroAuthors(item) { return getZoteroCreators(item).names; }

    /** The word to use about a candidate's creators in a match explanation. */
    function creatorNoun(candidate) {
      const role = candidate && candidate.creatorRole;
      return role && role !== 'author' ? role : 'author';
    }

    /* “(red)”, “(ed)”, “(eds)” mark the role, not part of the name: a Zotero
       editor is recorded as “Nyström”, the reference list writes
       “Nyström B (red)”, and the two have to compare equal. */
    function stripCreatorRoleSuffix(value) {
      return String(value || '')
        .replace(/\s*\((?:red|ed|eds|editor|editors|utg)\.?\)\s*$/i, '')
        .trim();
    }
    function getZoteroReportNumber(item){return String(item?.data?.reportNumber||'').trim();}
    /* Statutes and standards carry the designation in Number, and standards
       sometimes only in the title ("SS-EN 1936:1999. Natural stone ..."). */
    function getZoteroDesignationKey(item){
      const fields=[item?.data?.number,item?.data?.reportNumber,item?.data?.code].map(value=>String(value||'').trim());
      for(const value of fields){const found=extractDesignationKey(value);if(found)return found;}
      return extractDesignationKey(String(item?.data?.title||''),true);
    }
    function getZoteroSkbReportKey(item){return extractSkbReportKey(getZoteroReportNumber(item));}
    function getZoteroAuthorYearKey(item){const a=getZoteroAuthors(item),y=getZoteroYear(item);return !a.length||!y?null:a.length===1?`${a[0]} ${y}`:a.length===2?`${a[0]} and ${a[1]} ${y}`:`${a[0]} et al. ${y}`;}
    function prepareZoteroItems(items){return items.map(item=>{const creators=getZoteroCreators(item),aliases=[getZoteroAuthorYearKey(item),getZoteroSkbReportKey(item),getZoteroDesignationKey(item),item.data?.shortTitle].filter(Boolean);return{key:item.key,title:String(item.data?.title||''),year:getZoteroYear(item),authors:creators.names,creatorRole:creators.role,reportKey:getZoteroSkbReportKey(item),designationKey:getZoteroDesignationKey(item),aliases,normalizedAliases:aliases.map(normaliseKey),url:item.links?.alternate?.href||'',data:item.data||{}};});}
    function normaliseTitle(value) {
      return normaliseDashes(value || '')
        .normalize('NFC')
        .toLowerCase()
        .replace(/&/g, ' and ')
        .replace(/[^a-zà-öø-ÿ0-9]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
    }

    function titleSimilarity(firstValue, secondValue) {
      const first = new Set(normaliseTitle(firstValue).split(' ').filter(word => word.length >= 2));
      const second = new Set(normaliseTitle(secondValue).split(' ').filter(word => word.length >= 2));
      if (!first.size || !second.size) return 0;
      const common = [...first].filter(word => second.has(word)).length;
      return common / (first.size + second.size - common);
    }

    function stringSimilarity(firstValue, secondValue) {
      const first = normaliseTitle(firstValue).replace(/\s+/g, '');
      const second = normaliseTitle(secondValue).replace(/\s+/g, '');
      if (!first || !second) return 0;
      if (first === second) return 1;
      const bigrams = value => {
        const result = new Map();
        for (let index = 0; index < value.length - 1; index++) {
          const gram = value.slice(index, index + 2);
          result.set(gram, (result.get(gram) || 0) + 1);
        }
        return result;
      };
      const left = bigrams(first);
      const right = bigrams(second);
      let intersection = 0;
      for (const [gram, count] of left) {
        intersection += Math.min(count, right.get(gram) || 0);
      }
      return (2 * intersection) / Math.max(1, first.length + second.length - 2);
    }

    function getDocumentReferenceTitle(entry) {
      return String(entry.body || '')
        .replace(/^\s*SKB\s+(?:TR|R|P|IPR|RD|SR|TM|U|F)-\d{2,}-\d+\s*[.,]?\s*/i, '')
        .replace(/^.+?,\s*(?:1[89]\d{2}|20\d{2})[a-z]?\s*(?:[.]\s*|(?=[A-ZÅÄÖÀ-ÖØ-Þ]))/u, '')
        .replace(/^.+?\s+(?:1[89]\d{2}|20\d{2})[a-z]?\s*(?:[.]\s*|(?=[A-ZÅÄÖÀ-ÖØ-Þ]))/u, '')
        .split(/\.\s+/)[0]
        .trim();
    }

    function getDocumentReferenceYear(entry) {
      return String(entry.body || '').match(/\b(?:1[89]\d{2}|20\d{2})[a-z]?\b/i)?.[0] || null;
    }

    function getDocumentReferenceReportKey(entry) {
      return extractSkbReportKey(entry.body || '');
    }

    function scoreOrphanCitationAgainstZotero(citation, candidate) {
      let score = 0;
      const reasons = [];
      const citationKey = normaliseKey(citation.key);
      if (candidate.normalizedAliases.includes(citationKey)) {
        score += 90;
        reasons.push('exact citation alias');
      }
      if (citation.type === 'skb-report' && candidate.reportKey && normaliseKey(candidate.reportKey) === citationKey) {
        score = Math.max(score, 98);
        reasons.push('exact SKB report number');
      }
      /* A designation identifies the document as precisely as a report number. */
      if (citation.type === 'designation' && candidate.designationKey
          && normaliseKey(candidate.designationKey) === citationKey) {
        score = Math.max(score, 98);
        reasons.push('exact designation');
      }
      const year = citation.year || String(citation.key).match(/\b(?:1[89]\d{2}|20\d{2})[a-z]?\b/i)?.[0];
      if (year && candidate.year && year.toLowerCase() === candidate.year.toLowerCase()) {
        score += 10;
        reasons.push('same year');
      }
      if (citation.author && candidate.authors.length) {
        const citedAuthor = stripCreatorRoleSuffix(
          citation.author.replace(/\s+(?:et\s+al\.?|m\.fl\.?).*$/i, '').split(/\s+(?:and|och|&)\s+/i)[0]
        );
        const similarity = stringSimilarity(citedAuthor, candidate.authors[0]);
        const noun = creatorNoun(candidate);
        if (similarity >= .9) { score += 25; reasons.push(`same first ${noun}`); }
        else if (zoteroFuzzyMatch.checked && similarity >= .72) { score += 15; reasons.push(`similar first ${noun}`); }
      }
      return { score: Math.min(score, 100), reasons };
    }

    function getDocumentReferenceAuthors(entry) {
      const text = String(entry.body || '');
      const authorBlockMatch = text.match(
        /^(.+),\s*(?:1[89]\d{2}|20\d{2})[a-z]?(?=\s*[.]|\s+[A-ZÅÄÖÀ-ÖØ-Þ])/u
      );

      if (!authorBlockMatch) return [];

      return authorBlockMatch[1]
        .split(',')
        .map(author => {
          const words = stripCreatorRoleSuffix(author).split(/\s+/).filter(Boolean);
          while (words.length > 1 && isAuthorInitial(words.at(-1))) {
            words.pop();
          }
          return words.join(' ').trim();
        })
        .filter(Boolean);
    }

    function authorListSimilarity(documentAuthors, zoteroAuthors) {
      if (!documentAuthors.length || !zoteroAuthors.length) return 0;

      const usedZoteroIndexes = new Set();
      let matchedAuthors = 0;

      for (const documentAuthor of documentAuthors) {
        const comparableDocumentAuthor = documentAuthor
          .replace(/\s*\(ed\)\s*/gi, '')
          .trim();
        let bestIndex = -1;
        let bestSimilarity = 0;

        for (let index = 0; index < zoteroAuthors.length; index++) {
          if (usedZoteroIndexes.has(index)) continue;
          const similarity = stringSimilarity(
            comparableDocumentAuthor,
            zoteroAuthors[index].replace(/\s*\(ed\)\s*/gi, '').trim()
          );
          if (similarity > bestSimilarity) {
            bestSimilarity = similarity;
            bestIndex = index;
          }
        }

        if (bestIndex >= 0 && bestSimilarity >= .88) {
          usedZoteroIndexes.add(bestIndex);
          matchedAuthors++;
        }
      }

      const precision = matchedAuthors / zoteroAuthors.length;
      const recall = matchedAuthors / documentAuthors.length;
      return precision + recall > 0
        ? (2 * precision * recall) / (precision + recall)
        : 0;
    }

    function scoreDocumentReferenceAgainstZotero(entry, candidate) {
      const reasons = [];
      const documentReport = getDocumentReferenceReportKey(entry);

      /*
        An exact Report Number is a true identifier and may stand on its own.
      */
      if (
        documentReport &&
        candidate.reportKey &&
        normaliseKey(documentReport) === normaliseKey(candidate.reportKey)
      ) {
        return {
          score: 100,
          reasons: ['exact SKB report number']
        };
      }

      const documentTitle = getDocumentReferenceTitle(entry);
      const titleScore = titleSimilarity(documentTitle, candidate.title);
      const documentYear = getDocumentReferenceYear(entry);
      const sameYear = Boolean(
        documentYear &&
        candidate.year &&
        documentYear.toLowerCase() === candidate.year.toLowerCase()
      );
      const documentAuthors = getDocumentReferenceAuthors(entry);
      const authorsScore = authorListSimilarity(documentAuthors, candidate.authors);

      /*
        Title is the main identity check. An author-year alias such as
        "Abarca et al. 2016" is not unique and must never be treated as an
        exact reference match by itself.
      */
      if (titleScore >= .9) reasons.push('near-exact title');
      else if (titleScore >= .75) reasons.push('very similar title');
      else if (titleScore >= .55) reasons.push('similar title');
      else if (titleScore >= .35) reasons.push('partly similar title');
      else reasons.push('different title');

      const noun = creatorNoun(candidate);
      if (authorsScore >= .95) reasons.push(`same ${noun} list`);
      else if (authorsScore >= .7) reasons.push(`mostly same ${noun}s`);
      else if (authorsScore >= .4) reasons.push(`some shared ${noun}s`);
      else if (documentAuthors.length && candidate.authors.length) reasons.push(`different ${noun} list`);

      if (sameYear) reasons.push('same year');

      /*
        Weighted evidence: title 55%, complete author-list agreement 30%,
        and year 15%. This is a ranking confidence, not a statistical
        probability derived from a trained model.
      */
      let score = Math.round(
        titleScore * 55 +
        authorsScore * 30 +
        (sameYear ? 15 : 0)
      );

      /*
        A substantially different title cannot be a high-confidence match,
        even if the first author and year happen to agree.
      */
      if (titleScore < .2) score = Math.min(score, 35);
      else if (titleScore < .35) score = Math.min(score, 49);

      return {
        score: Math.min(score, 100),
        reasons
      };
    }
