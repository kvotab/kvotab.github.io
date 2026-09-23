/* ==========================================================================
   SKB REFERENCE CHECKER — zotero

   The Zotero client: settings, the library sources, matching a reference or
   a citation to a library item, and showing the result.

   Matching is zoterify.html's (zoterify-match.js), so both pages judge a
   reference the same way. A reference-list entry is read by zoterify's
   entry reader, so its whole author list, its year, its report number and
   its title words count; a citation is read by zoterify's citation reader.
   The result is one of matched, choose (ambiguous), year differs, possible
   and not found, with the items that led to it.

   The library is one of two kinds. zotero.sqlite, opened in the browser
   through sql.js (zoterify-zotero.js), gives the whole library at once, so
   an entry is matched against every item in milliseconds and a whole list
   can be checked in one go. A web source (a Zotero group or user library,
   Zotero desktop's local API, or a compatible endpoint) is searched with
   the queries below, and what comes back is matched the same way: there
   the result can only be as good as the search.

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

    /* ======================================================================
       Settings
       ====================================================================== */

    function updateZoteroSettingsVisibility() {
      const source = zoteroSourceType.value;
      document.querySelector('[data-setting="group-id"]').hidden = !['public-group', 'web-group'].includes(source);
      document.querySelector('[data-setting="user-id"]').hidden = source !== 'web-user';
      document.querySelector('[data-setting="custom-url"]').hidden = source !== 'custom';
      document.querySelector('[data-setting="local-url"]').hidden = source !== 'local';
      document.querySelectorAll('[data-setting^="sqlite"]').forEach(node => { node.hidden = source !== 'sqlite'; });
      document.querySelector('[data-setting="auth"]').hidden = source === 'sqlite';
      zoteroTestLocalAccess.hidden = source !== 'local';

      if (source === 'local' || source === 'sqlite') {
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
      if (settings.sourceType === 'sqlite' && !zoteroDatabase?.items) {
        throw new Error('Open zotero.sqlite first.');
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
        if (settings.sourceType === 'local' || settings.sourceType === 'sqlite') {
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
      updateZoteroBulkBars();
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
      zoteroMatchLevel.value = 'balanced';
      zoteroYearTolerance.value = '1';
      zoteroSearchCache.clear();
      updateZoteroSettingsVisibility();
      updateZoteroBulkBars();
      zoteroSettingsStatus.textContent = 'Default public group restored.';
      setTimeout(() => { zoteroSettingsStatus.textContent = ''; }, 2500);
    }

    /** What a fit must be, as zoterify-match.js takes it. */
    function zoteroMatchOptions() {
      const level = ['lenient', 'balanced', 'strict'].includes(zoteroMatchLevel.value) ? zoteroMatchLevel.value : 'balanced';
      const yearTolerance = Number(zoteroYearTolerance.value);
      return { level, yearTolerance: Number.isInteger(yearTolerance) ? yearTolerance : 1 };
    }

    /* ======================================================================
       zotero.sqlite, read in the browser

       The file Zotero desktop keeps in its data directory, with its -wal
       file when Zotero is running (the newest items are there until Zotero
       copies them into the database). It stays in this page: nothing is
       uploaded, and it is kept when another document is opened.
       ====================================================================== */

    let zoteroDatabase = null;   // { name, bytes, walName, walBytes, sqldb, info, items, byUri, byKey, walFrames, walNote, walMode, matcher, matcherKey, scopeItems }
    let zoteroPendingWal = null; // a -wal file chosen before its database

    function isZoteroDatabaseFile(file) {
      return /\.(?:sqlite|sqlite3|db)$|-wal$/i.test(String(file?.name || ''));
    }

    function usingLocalZoteroDatabase() {
      return activeZoteroSettings.sourceType === 'sqlite' && Boolean(zoteroDatabase?.items);
    }

    async function addZoteroDatabaseFiles(files) {
      const list = [...(files || [])];
      const database = list.find(file => /\.(?:sqlite|sqlite3|db)$/i.test(file.name));
      const wal = list.find(file => /-wal$/i.test(file.name));
      if (!database && !wal) {
        if (list.length) renderZoteroDatabaseInfo(`${list[0].name} is not an SQLite database. Choose zotero.sqlite from your Zotero data directory.`);
        return;
      }
      try {
        if (database) {
          const size = kvotFileTooLarge(database, KVOT_FILE_SIZE_LIMITS.dataset);
          if (size.tooLarge) throw new Error(size.reason);
          closeZoteroDatabase();
          zoteroDatabase = { name: database.name, bytes: new Uint8Array(await database.arrayBuffer()), walName: '', walBytes: null };
          if (zoteroPendingWal) {
            Object.assign(zoteroDatabase, zoteroPendingWal);
            zoteroPendingWal = null;
          }
        }
        if (wal) {
          const walPart = { walName: wal.name, walBytes: new Uint8Array(await wal.arrayBuffer()) };
          if (!zoteroDatabase) {
            zoteroPendingWal = walPart;
            renderZoteroDatabaseInfo(`${wal.name} will be read with the database; now choose zotero.sqlite.`);
            return;
          }
          Object.assign(zoteroDatabase, walPart);
        }
        await openZoteroDatabase();
      } catch (error) {
        renderZoteroDatabaseInfo(error.message);
      }
    }

    function closeZoteroDatabase() {
      if (zoteroDatabase?.sqldb) {
        try { zoteroDatabase.sqldb.close(); } catch (error) { /* already closed */ }
      }
      zoteroDatabase = null;
    }

    async function openZoteroDatabase() {
      const database = zoteroDatabase;
      renderZoteroDatabaseInfo(null, `Opening ${database.name}…`);
      try {
        const SQL = await ZFZotero.loadSqlJs();
        await yieldToBrowser();
        if (zoteroDatabase !== database) return;
        if (database.sqldb) { try { database.sqldb.close(); } catch (error) { /* already closed */ } }
        database.sqldb = null;
        database.walMode = database.bytes[18] === 2;
        const prepared = ZFZotero.prepareDatabase(database.bytes, database.walBytes);
        database.sqldb = new SQL.Database(prepared.bytes);
        database.walFrames = prepared.walFrames;
        database.walNote = prepared.walNote;
        database.info = ZFZotero.readInfo(database.sqldb);
        database.items = ZFZotero.readItems(database.sqldb, database.info);
        database.byUri = new Map(database.items.map(item => [item.uri, item]));
        database.byKey = new Map();
        for (const item of database.items) if (!database.byKey.has(item.key)) database.byKey.set(item.key, item);
        database.matcher = null;
        database.matcherKey = '';
        fillZoteroScope();
        useZoteroDatabaseSource();
        renderZoteroDatabaseInfo();
      } catch (error) {
        if (database.sqldb) { try { database.sqldb.close(); } catch (closeError) { /* already closed */ } }
        database.sqldb = null;
        database.items = null;
        renderZoteroDatabaseInfo(`${database.name}: ${error.message}`);
      }
      updateZoteroBulkBars();
    }

    /* Opening a database is choosing it: it becomes the source at once. */
    function useZoteroDatabaseSource() {
      zoteroSourceType.value = 'sqlite';
      activeZoteroSettings = { ...DEFAULT_ZOTERO_SETTINGS, sourceType: 'sqlite' };
      updateZoteroSettingsVisibility();
    }

    function renderZoteroDatabaseInfo(error = null, progress = '') {
      const database = zoteroDatabase;
      if (error) { zoteroDbInfo.innerHTML = `<div class="zotero-db-warn">${escHtml(error)}</div>`; return; }
      if (progress) { zoteroDbInfo.innerHTML = `<div class="zotero-db-meta">${escHtml(progress)}</div>`; return; }
      if (!database?.items) { zoteroDbInfo.innerHTML = ''; return; }
      const libraries = database.info.libraries.filter(library => library.type === 'user' || library.type === 'group');
      const lines = [
        `<div class="zotero-db-name">${escHtml(database.name)}${database.walName ? ` + ${escHtml(database.walName)}` : ''}</div>`,
        `<div class="zotero-db-meta">${database.items.length.toLocaleString('en')} items in ${libraries.length === 1 ? 'one library' : `${libraries.length} libraries`}. It is read here and nothing is uploaded.</div>`
      ];
      if (database.walName) {
        lines.push(`<div class="zotero-db-meta">${database.walFrames ? `${database.walFrames.toLocaleString('en')} pages of recent changes replayed from the WAL file.` : escHtml(`The WAL file: ${database.walNote || 'nothing to replay'}.`)}</div>`);
      } else if (database.walMode) {
        lines.push('<div class="zotero-db-warn">If Zotero is running, add zotero.sqlite-wal from the same folder: without it, items added since Zotero last saved to the database are not seen.</div>');
      }
      zoteroDbInfo.innerHTML = lines.join('');
    }

    function fillZoteroScope() {
      const { info, items } = zoteroDatabase;
      const count = libraryID => items.filter(item => item.libraryId === libraryID).length;
      const parts = [`<option value="">All libraries (${items.length.toLocaleString('en')})</option>`];
      const libraries = info.libraries.filter(library => library.type === 'user' || library.type === 'group');
      if (libraries.length > 1) {
        for (const library of libraries) parts.push(`<option value="lib:${library.libraryID}">${escHtml(library.name)} (${count(library.libraryID).toLocaleString('en')})</option>`);
      }
      if (info.collections.length) {
        parts.push('<optgroup label="Collections, with their subcollections">');
        for (const collection of info.collections) {
          const label = libraries.length > 1 ? `${collection.libraryName} / ${collection.path}` : collection.path;
          parts.push(`<option value="col:${collection.id}">${escHtml(label)} (${collection.itemCount})</option>`);
        }
        parts.push('</optgroup>');
      }
      zoteroDbScope.innerHTML = parts.join('');
      zoteroDbScope.disabled = false;
    }

    function zoteroScopeFromValue(value) {
      if (value.startsWith('lib:')) return { libraryID: Number(value.slice(4)) };
      if (value.startsWith('col:')) return { collectionId: Number(value.slice(4)) };
      return {};
    }

    /** The matcher over the chosen part of the library, rebuilt only when
        the part or the matching options change. */
    function localZoteroMatcher() {
      const database = zoteroDatabase;
      const scope = zoteroDbScope.value || '';
      const options = zoteroMatchOptions();
      const key = `${scope}|${options.level}|${options.yearTolerance}`;
      if (database.matcherKey !== key) {
        database.scopeItems = scope ? ZFZotero.readItems(database.sqldb, database.info, zoteroScopeFromValue(scope)) : database.items;
        database.matcher = ZFMatch.createMatcher(database.scopeItems, options);
        database.matcherKey = key;
      }
      return database.matcher;
    }

    /* ======================================================================
       Web sources
       ====================================================================== */

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

    /* ======================================================================
       What is matched

       The reference a row stands for, in the form zoterify-match.js reads.
       ====================================================================== */

    /*
      A reference-list entry. Its whole author list is known, so it is not
      "et al."; its title words settle between namesakes, and its report
      number, when it gives one after the title, settles "SKB, 2011." --
      but only for an item whose creators and year fit the entry too, as in
      zoterify, since an entry may name another report in passing. An entry
      entered under its number ("SKB TR-11-01. Title.", "SSMFS 2008:21.
      Title.") is the work that number names, as a citation of it would be.
      An entry with no readable author list is found by its title words, as
      an abbreviated name is.
    */
    function zoteroRefFromEntry(entry) {
      const text = String(entry.body || '').trim();
      // A numbered entry is read as one: its year may come last.
      const read = (entry.type === 'abbreviated-name' && ZFParse.readAbbreviatedEntry(text))
        || ZFParse.readEntry(entry.type === 'numbered' ? `1. ${text}` : text) || {};
      const listed = { authors: [], year: '', letter: '', yearKey: '', report: '', designation: '', abbrev: '', ...read, num: null, text };
      if (entry.type === 'abbreviated-name' && !listed.abbrev) listed.abbrev = entry.abbreviatedName || '';
      if (entry.type === 'skb-report' && !listed.report) listed.report = ZFParse.reportsIn(extractSkbReportKey(text, true) || '')[0] || '';
      if (entry.type === 'designation' && !listed.designation) listed.designation = extractDesignationKey(text, true) || '';
      const own = entry.type === 'skb-report' || entry.type === 'designation';
      return {
        authors: listed.authors, aliases: [], initials: [], etAl: false,
        year: listed.year, letter: listed.letter, yearKey: listed.yearKey, num: null,
        report: own ? listed.report : '', designation: own ? listed.designation : '',
        abbrev: listed.abbrev || (listed.authors.length ? '' : String(entry.key || text.slice(0, 40))),
        entry: listed
      };
    }

    /* A citation with no entry in the list, read the way zoterify reads one
       in running text: "Smith et al. 2020", "Vallery C 2001", "SKB
       TR-11-01", "SSMFS 2008:37". Null when it names nothing to look for. */
    function zoteroRefFromCitation(citation) {
      if (citation.type === 'numbered') return null;
      const key = String(citation.key || '').trim();
      if (!key) return null;
      const refs = ZFParse.findInParagraph(`(${key})`).flatMap(group => group.refs);
      return refs.length ? Object.assign(refs[0], { entry: null }) : null;
    }

    function zoteroCheckSources(kind) {
      return kind === 'reference' ? currentRefEntries : (currentReport?.orphanCites || []);
    }

    function zoteroRefFor(kind, source) {
      return kind === 'reference' ? zoteroRefFromEntry(source) : zoteroRefFromCitation(source);
    }

    function unreadableZoteroResult(source, note = '') {
      const why = source.type === 'numbered'
        ? 'A numbered citation with no entry in the reference list names no author or year to look for.'
        : 'The citation could not be read as authors and a year, a report number or a designation.';
      return { ref: null, status: 'none', item: null, confidence: 0, candidates: [], note: [note, why].filter(Boolean).join(' ') };
    }

    /*
      A Zotero field in the document names its items. When a field cites
      several, the ones that fit this citation are kept, and all of them on
      a tie; null when the field names none of the items given.
    */
    function zoteroFieldResult(ref, items) {
      if (!items.length) return null;
      let picked = items;
      if (items.length > 1 && ref) {
        const fit = ZFMatch.createMatcher(items, zoteroMatchOptions()).match(ref);
        if (fit.status === 'matched') picked = [fit.item];
        else if (fit.status === 'ambiguous') picked = fit.candidates.map(candidate => candidate.item);
      }
      return {
        ref, status: picked.length === 1 ? 'matched' : 'ambiguous', item: picked[0], confidence: 1, by: 'field', via: 'field',
        candidates: picked.map(item => ({ item, confidence: 1, entryConfirmed: false, by: 'field' }))
      };
    }

    /* The items of the database a Zotero field links to, by URI, else by key. */
    function zoteroLinkedItems(citation) {
      const found = [];
      for (const link of citation.zoteroFieldData?.linkedItems || []) {
        const item = (link.uri && zoteroDatabase.byUri.get(link.uri)) || zoteroDatabase.byKey.get(link.itemKey);
        if (item && !found.includes(item)) found.push(item);
      }
      return found;
    }

    function matchInLocalZotero(kind, source, matcher = localZoteroMatcher()) {
      const ref = zoteroRefFor(kind, source);
      let note = '';
      if (kind === 'citation' && source.citationSource === 'zotero') {
        const direct = zoteroFieldResult(ref, zoteroLinkedItems(source));
        if (direct) return direct;
        const keys = [...new Set(source.zoteroItemKeys || [])];
        if (keys.length) note = `The Zotero field links to ${keys.join(', ')}, which ${zoteroDatabase.name} does not hold.`;
      }
      if (!ref) return unreadableZoteroResult(source, note);
      const result = matcher.match(ref);
      return { ...result, via: 'database', searched: zoteroDatabase.scopeItems.length, note: [note, result.note].filter(Boolean).join(' ') };
    }

    /* An API item as a library item, keeping what the page shows of it. */
    function zoteroItemFromApi(apiItem, serial) {
      const item = ZFZotero.itemFromApi(apiItem, serial);
      item.zoteroData = apiItem.data || {};
      item.recordUrl = apiItem.links?.alternate?.href || '';
      return item;
    }

    async function matchByZoteroWebSearch(kind, source, signal) {
      const ref = zoteroRefFor(kind, source);
      let note = '';
      const keys = [...new Set(source.zoteroItemKeys || [])];
      if (kind === 'citation' && source.citationSource === 'zotero' && keys.length) {
        const fetched = [], failures = [];
        for (const itemKey of keys) {
          try {
            fetched.push(await fetchZoteroItemByKey(itemKey, signal));
          } catch (error) {
            if (error.name === 'AbortError') throw error;
            failures.push(`${itemKey}: ${error.message}`);
          }
        }
        const direct = zoteroFieldResult(ref, fetched.map((item, index) => zoteroItemFromApi(item, index + 1)));
        if (direct) return direct;
        note = `The item the Zotero field links to could not be retrieved (${failures.join('; ')}); a search followed.`;
      }
      if (!ref) return unreadableZoteroResult(source, note);

      const queries = kind === 'reference' ? buildZoteroQueriesForFullReference(source) : buildZoteroQueriesForCitation(source);
      const pool = new Map();
      let failed = 0, lastError = null;
      for (const search of queries) {
        if (signal.aborted) throw new DOMException('Search canceled', 'AbortError');
        try {
          const items = await searchZoteroItems(search.query, {
            qmode: search.qmode,
            limit: ZOTERO_CONFIG.searchResultLimit,
            timeoutMilliseconds: ZOTERO_CONFIG.searchTimeoutMilliseconds,
            signal
          });
          for (const item of items) if (item?.key && !pool.has(item.key)) pool.set(item.key, item);
        } catch (error) {
          if (error.name === 'AbortError') throw error;
          console.warn('Zotero query failed:', search.query, error);
          failed++;
          lastError = error;
        }
      }
      // Every query failing is a failure to report, not "not found".
      if (lastError && failed === queries.length) throw lastError;
      const items = [...pool.values()].map((item, index) => zoteroItemFromApi(item, index + 1));
      const result = ZFMatch.createMatcher(items, zoteroMatchOptions()).match(ref);
      return { ...result, via: 'web', searched: items.length, note: [note, result.note].filter(Boolean).join(' ') };
    }

    /* ======================================================================
       On the page

       Each row gets a verdict in its Zotero cell and, in a row of its own
       below it spanning the table, the items behind the verdict: the cell
       is too narrow for a title, let alone a formatted reference.
       ====================================================================== */

    const ZOTERO_VERDICTS = Object.freeze({
      matched:   { label: 'Matched',      tone: 'good',  about: 'one item fits clearly better than any other' },
      ambiguous: { label: 'Choose',       tone: 'warn',  about: 'several items fit equally well' },
      year:      { label: 'Year differs', tone: 'warn',  about: 'the authors fit an item from another year' },
      possible:  { label: 'Possible',     tone: 'muted', about: 'only looser fits, of any year' },
      none:      { label: 'Not found',    tone: 'bad',   about: 'nothing in the library comes near' }
    });

    function zoteroCellHtml(kind, index, title) {
      const id = `${kind}-${index}`;
      return `<td class="zotero-cell">
                  <button class="zotero-row-btn" type="button" data-kind="${kind}" data-index="${index}" data-search-id="${id}" data-result-id="zotero-${id}" title="${escHtml(title)}">Check Zotero</button>
                  <div class="zotero-verdict" id="zotero-verdict-${id}"></div>
                </td>`;
    }

    function zoteroDetailRowHtml(kind, index, columns) {
      const id = `${kind}-${index}`;
      return `<tr class="zotero-detail-row" id="zotero-detail-${id}" hidden><td colspan="${columns}"><div id="zotero-${id}" class="zotero-inline-results"></div></td></tr>`;
    }

    function zoteroBulkBarHtml(kind, count) {
      if (!count) return '';
      const what = kind === 'reference' ? 'entries' : 'citations';
      return `<div class="zotero-bulk">
          <button class="zotero-row-btn zotero-check-all" type="button" data-kind="${kind}">Check all ${count} ${what} in Zotero</button>
          <span class="zotero-bulk-hint" id="zotero-bulk-hint-${kind}"></span>
          <span class="zotero-bulk-status" id="zotero-bulk-status-${kind}"></span>
          <label class="zotero-bulk-filter" hidden><input type="checkbox" data-zotero-filter="${kind}"> Only those not matched</label>
        </div>`;
    }

    function updateZoteroBulkBars() {
      const ready = usingLocalZoteroDatabase();
      for (const button of document.querySelectorAll('.zotero-check-all')) {
        if (button.classList.contains('searching')) continue;
        button.disabled = !ready;
        const hint = $(`zotero-bulk-hint-${button.dataset.kind}`);
        if (hint) hint.textContent = ready ? '' : 'Open your zotero.sqlite under Zotero settings to check every row at once.';
      }
    }

    function handleInlineZoteroClick(event) {
      const copyButton = event.target.closest('.zotero-copy-reference');
      if (copyButton) {
        copyFormattedZoteroReference(copyButton);
        return;
      }
      const toggle = event.target.closest('.zotero-detail-toggle');
      if (toggle) {
        setZoteroDetailOpen(toggle.dataset.detail, Boolean($(`zotero-detail-${toggle.dataset.detail}`)?.hidden));
        return;
      }
      const checkAll = event.target.closest('.zotero-check-all');
      if (checkAll) {
        runAllZoteroChecks(checkAll.dataset.kind, checkAll);
        return;
      }
      const button = event.target.closest('.zotero-row-btn[data-search-id]');
      if (!button) return;
      const searchId = button.dataset.searchId;
      if (activeInlineZoteroSearches.has(searchId)) {
        activeInlineZoteroSearches.get(searchId).abort();
        return;
      }
      runZoteroCheck(button.dataset.kind, Number(button.dataset.index), button);
    }

    /* "Only those not matched": hides the matched rows and their details. */
    function handleZoteroFilterChange(event) {
      const kind = event.target?.dataset?.zoteroFilter;
      if (!kind) return;
      event.target.closest('.section-body')?.querySelector('.ref-table')?.classList.toggle('zotero-only-unmatched', event.target.checked);
    }

    async function runZoteroCheck(kind, index, button) {
      const source = zoteroCheckSources(kind)[index];
      if (!source) return;
      const id = `${kind}-${index}`;
      if (activeZoteroSettings.sourceType === 'sqlite') {
        if (!usingLocalZoteroDatabase()) {
          showZoteroMessage(kind, index, 'Open your zotero.sqlite under Zotero settings first.');
          return;
        }
        renderZoteroResult(kind, index, matchInLocalZotero(kind, source), { open: true });
        return;
      }

      const controller = new AbortController();
      activeInlineZoteroSearches.set(id, controller);
      button.classList.add('searching');
      button.textContent = 'Cancel search';
      const linked = kind === 'citation' && source.citationSource === 'zotero' && source.zoteroItemKeys?.length;
      showZoteroMessage(kind, index, linked ? 'Retrieving the item linked by the Zotero Word field…' : 'Searching Zotero…');
      try {
        renderZoteroResult(kind, index, await matchByZoteroWebSearch(kind, source, controller.signal), { open: true });
      } catch (error) {
        showZoteroMessage(kind, index, error.name === 'AbortError' ? 'Search canceled.' : `Search failed: ${error.message}`);
      } finally {
        activeInlineZoteroSearches.delete(id);
        button.classList.remove('searching');
        button.textContent = 'Check Zotero';
      }
    }

    async function runAllZoteroChecks(kind, button) {
      if (!usingLocalZoteroDatabase()) { updateZoteroBulkBars(); return; }
      const sources = zoteroCheckSources(kind);
      const status = $(`zotero-bulk-status-${kind}`);
      const say = html => { if (status) status.innerHTML = html; };
      button.disabled = true;
      button.classList.add('searching');
      try {
        say('Preparing the library…');
        await yieldToBrowser();
        const started = performance.now();
        const matcher = localZoteroMatcher();
        const counts = { matched: 0, ambiguous: 0, year: 0, possible: 0, none: 0 };
        for (let index = 0; index < sources.length; index++) {
          const result = matchInLocalZotero(kind, sources[index], matcher);
          counts[result.status] = (counts[result.status] || 0) + 1;
          renderZoteroResult(kind, index, result, { open: false });
          if (index % 40 === 39) {
            say(`Checked ${index + 1} of ${sources.length}…`);
            await yieldToBrowser();
          }
        }
        const seconds = ((performance.now() - started) / 1000).toFixed(1);
        const tally = Object.entries(counts).filter(([, count]) => count)
          .map(([verdict, count]) => `<span class="zotero-verdict-chip ${ZOTERO_VERDICTS[verdict].tone}">${count} ${escHtml(ZOTERO_VERDICTS[verdict].label.toLowerCase())}</span>`).join(' ');
        say(`${sources.length} checked against ${zoteroDatabase.scopeItems.length.toLocaleString('en')} items in ${seconds} s: ${tally}`);
        const filter = button.parentElement?.querySelector('.zotero-bulk-filter');
        if (filter) filter.hidden = counts.matched === sources.length;
      } finally {
        button.disabled = !usingLocalZoteroDatabase();
        button.classList.remove('searching');
      }
    }

    function setZoteroDetailOpen(id, open) {
      const row = $(`zotero-detail-${id}`);
      if (!row) return;
      row.hidden = !open;
      const toggle = document.querySelector(`.zotero-detail-toggle[data-detail="${id}"]`);
      if (toggle) {
        toggle.setAttribute('aria-expanded', String(open));
        toggle.textContent = open ? 'Hide details' : 'Details';
      }
    }

    function showZoteroMessage(kind, index, message) {
      const id = `${kind}-${index}`;
      const verdict = $(`zotero-verdict-${id}`), container = $(`zotero-${id}`);
      if (!container) return;
      if (verdict) verdict.innerHTML = '';
      verdict?.closest('tr')?.removeAttribute('data-zotero-status');
      container.innerHTML = `<div class="zotero-inline-status">${escHtml(message)}</div>`;
      setZoteroDetailOpen(id, true);
    }

    function renderZoteroResult(kind, index, result, { open }) {
      const id = `${kind}-${index}`;
      const verdict = $(`zotero-verdict-${id}`), container = $(`zotero-${id}`);
      if (!verdict || !container) return;
      const shown = ZOTERO_VERDICTS[result.status] || ZOTERO_VERDICTS.none;
      const item = result.status === 'matched' ? result.item : null;
      const about = item ? `${shown.about}: ${[item.authors[0] || item.editors[0], item.year].filter(Boolean).join(' ')}, ${item.title}` : shown.about;
      verdict.innerHTML = `<span class="zotero-verdict-chip ${shown.tone}" title="${escHtml(about)}">${escHtml(shown.label)}</span>`
        + `<button type="button" class="zotero-detail-toggle" data-detail="${id}" aria-controls="zotero-detail-${id}" aria-expanded="false">Details</button>`;
      verdict.closest('tr')?.setAttribute('data-zotero-status', result.status);
      container.innerHTML = buildZoteroResultDetail(result);
      setZoteroDetailOpen(id, open);
    }

    function buildZoteroResultDetail(result) {
      const shown = ZOTERO_VERDICTS[result.status] || ZOTERO_VERDICTS.none;
      let against = '';
      if (result.via === 'field') against = 'the item the Zotero field in the document links to';
      else if (result.via === 'web') against = `the ${result.searched} item${result.searched === 1 ? '' : 's'} the Zotero search returned`;
      else if (result.via === 'database') {
        const scope = zoteroDbScope.value ? ` (${zoteroDbScope.selectedOptions[0]?.textContent.replace(/\s*\(\d[\d,]*\)$/, '') || 'part of the library'})` : '';
        against = `${result.searched.toLocaleString('en')} items in ${zoteroDatabase?.name || 'zotero.sqlite'}${scope}`;
      }
      const head = `<div class="zotero-detail-head"><span class="zotero-verdict-chip ${shown.tone}">${escHtml(shown.label)}</span><span>${escHtml(shown.about)}${against ? ` · matched against ${escHtml(against)}` : ''}</span></div>`;
      const note = result.note ? `<div class="zotero-inline-status">${escHtml(result.note)}</div>` : '';
      const cards = result.candidates.length
        ? `<div class="zotero-candidates">${result.candidates.map(candidate => buildInlineZoteroCandidate(candidate, result)).join('')}</div>`
        : '';
      return head + note + cards;
    }

    /*
      The record links. For an item of the database, zotero://select opens
      it in Zotero desktop; the address is built from the item's URI, which
      the database reader writes, and its parts are checked rather than the
      whole trusted. For an item from a web source, the link its endpoint
      gives is used as a URL rather than as text, and escaping does not help
      there: "javascript:alert(1)" contains nothing escHtml would touch. The
      settings panel lets the endpoint be any http(s) address the user names,
      so the response is not trusted to that extent: the scheme is checked.
    */
    function zoteroRecordLinks(item) {
      const links = [];
      const parts = !item.zoteroData && /^http:\/\/zotero\.org\/(?:groups\/(\d+)|users\/[A-Za-z0-9/]+?)\/items\/([A-Z0-9]{8})$/.exec(item.uri || '');
      if (parts) links.push(`<a href="${escHtml(parts[1] ? `zotero://select/groups/${parts[1]}/items/${parts[2]}` : `zotero://select/library/items/${parts[2]}`)}">Show in Zotero</a>`);
      const web = kvotSafeHttpUrl(item.recordUrl);
      if (web) links.push(`<a href="${escHtml(web)}" target="_blank" rel="noopener noreferrer">Open Zotero record ↗</a>`);
      return links.length ? `<div class="zotero-candidate-links">${links.join(' · ')}</div>` : '';
    }

    function zoteroFitBadge(candidate) {
      const by = { report: 'report number', designation: 'designation', field: 'Zotero field' }[candidate.by];
      const share = `${Math.round(candidate.confidence * 100)}%`;
      // The share is mostly the fit of the names: say so, or a namesake
      // with another title reads as a "100%" match.
      const text = by || (candidate.entryConfirmed ? `title in entry · ${share}` : `names ${share}`);
      const title = by
        ? `Found by its ${by}.`
        : 'How well the cited names fit the item’s creators (first name, second name, number of names), adjusted by how much of the item’s title is in the reference-list entry. A ranking, not a probability.';
      return `<span class="zotero-probability" title="${escHtml(title)}">${escHtml(text)}</span>`;
    }

    function zoteroMatchBasis(candidate, result) {
      if (candidate.by === 'field') return 'the Zotero citation field in the document links to this item';
      if (candidate.by === 'report') return 'its Report Number is the SKB report number given';
      if (candidate.by === 'designation') return 'its number or title carries the designation given';
      const ref = result.ref || {};
      if (ref.abbrev && !ref.entry?.authors?.length) return 'its title words are in the reference-list entry';
      const parts = [result.status === 'possible' ? 'the names fit loosely' : 'the names fit'];
      const cited = Number(ref.yearKey), found = Number(candidate.item.year);
      if (/^\d{4}$/.test(ref.yearKey || '') && /^\d{4}$/.test(candidate.item.year || '')) {
        parts.push(cited === found ? 'the same year' : `the year differs by ${Math.abs(cited - found)}`);
      }
      if (candidate.entryConfirmed) parts.push('its title is in the reference-list entry');
      return parts.join(', ');
    }

    function buildInlineZoteroCandidate(candidate, result) {
      const item = candidate.item;
      const candidateId = 'zc-' + (item.key || 'item') + '-' + Math.random().toString(36).slice(2, 9);
      const data = zoteroItemData(item);
      const formatted = formatSkbReference(data);
      zoteroFormattedReferenceStore.set(candidateId, formatted);
      const names = item.authors.length ? item.authors : item.editors;
      const role = !item.authors.length && item.editors.length ? ' (editors)' : '';
      const number = item.csl?.number || '';
      const libraries = zoteroDatabase?.info?.libraries || [];
      const library = !item.zoteroData && new Set(zoteroDatabase?.items?.map(entry => entry.libraryId)).size > 1
        ? libraries.find(entry => entry.libraryID === item.libraryId)?.name || '' : '';
      return `
        <div class="zotero-candidate" data-zotero-candidate-id="${escHtml(candidateId)}">
          <div class="zotero-candidate-head">
            <div class="zotero-candidate-title">${escHtml(item.title || '(untitled Zotero item)')}</div>
            ${zoteroFitBadge(candidate)}
          </div>
          <div>${escHtml(names.join(', ') || 'No creator recorded')}${role} · ${escHtml(item.year || 'No year')}${library ? ` · ${escHtml(library)}` : ''}</div>
          ${number ? `<div>${item.itemTypeZotero === 'report' ? 'Report Number' : 'Number'}: ${escHtml(number)}</div>` : ''}
          ${data.language ? `<div>Language metadata: ${escHtml(data.language)}${formatted.languageNote ? ` → ${escHtml(formatted.languageNote)}` : ' → no language note required'}</div>` : '<div>Language metadata: not recorded</div>'}
          <div>Match basis: ${escHtml(zoteroMatchBasis(candidate, result))}</div>
          ${zoteroRecordLinks(item)}
          <div class="zotero-formatted-reference">${formatted.html}</div>
          <button class="zotero-row-btn zotero-copy-reference" type="button" data-candidate-id="${escHtml(candidateId)}">Copy formatted reference</button>
        </div>`;
    }

    /* ======================================================================
       The SKB reference formatter
       ====================================================================== */

    /*
      An item's fields under Zotero's names, which formatSkbReference reads:
      as the web API gave them, or, for an item of the database, from the
      CSL-JSON the database reader builds.
    */
    function zoteroItemData(item) {
      if (item.zoteroData) return item.zoteroData;
      const csl = item.csl || {};
      const creators = [];
      for (const creatorType of ['author', 'editor', 'translator']) {
        for (const person of csl[creatorType] || []) {
          creators.push(person.literal !== undefined
            ? { creatorType, name: person.literal }
            : { creatorType, lastName: person.family || '', firstName: person.given || '' });
        }
      }
      const container = csl['container-title'] || '';
      return {
        itemType: item.itemTypeZotero, title: item.title, date: item.year, creators,
        publicationTitle: container, bookTitle: container, volume: csl.volume || '', pages: csl.page || '',
        place: csl['publisher-place'] || '', publisher: csl.publisher || '', reportNumber: csl.number || '',
        archive: csl.archive || '', archiveLocation: csl.archive_location || '', DOI: csl.DOI || '',
        language: csl.language || '', shortTitle: csl['title-short'] || ''
      };
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

    /* ======================================================================
       Reading a reference-list entry for the web queries
       ====================================================================== */

    /* “(red)”, “(ed)”, “(eds)” mark the role, not part of the name: a Zotero
       editor is recorded as “Nyström”, the reference list writes
       “Nyström B (red)”, and the two have to compare equal. */
    function stripCreatorRoleSuffix(value) {
      return String(value || '')
        .replace(/\s*\((?:red|ed|eds|editor|editors|utg)\.?\)\s*$/i, '')
        .trim();
    }
    function normaliseTitle(value) {
      return normaliseDashes(value || '')
        .normalize('NFC')
        .toLowerCase()
        .replace(/&/g, ' and ')
        .replace(/[^a-zà-öø-ÿ0-9]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
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
