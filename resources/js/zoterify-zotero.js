/* ==========================================================================
   ZOTERIFY.HTML: READING A ZOTERO DATABASE

   Reads zotero.sqlite, the file Zotero desktop keeps in its data directory
   (~/Zotero/zotero.sqlite on macOS and Linux, C:\Users\<you>\Zotero on
   Windows), through sql.js, the SQLite library compiled to WebAssembly.
   Nothing leaves the browser.

   Two things about that file shape this module.

   Zotero runs SQLite in WAL mode. While Zotero is open, recent changes live
   in zotero.sqlite-wal beside the database and are copied into it only now
   and then. applyWal() replays the committed transactions of a -wal file
   onto the database bytes, verifying SQLite's checksums frame by frame, so
   that the library read here is the library Zotero shows, even with Zotero
   still running. Without the -wal file the read is of the last checkpoint.

   A library item carries what the matcher needs (creators' names, year,
   title) and what a Zotero field code needs: the numeric itemID, the item
   URI and CSL-JSON item data. The URI is the one Zotero itself writes:
       http://zotero.org/users/<userID>/items/<key>          synced library
       http://zotero.org/users/local/<localKey>/items/<key>  never synced
       http://zotero.org/groups/<groupID>/items/<key>        group library
   The whole library is read in a handful of queries: libraries of tens of
   thousands of items are common, and a query per item would take minutes.

   Left out: attachments, notes, annotations, items in the bin and feed
   items. An item type's primary creator (the director of a film, the
   programmer of software) counts as its author.
   ========================================================================== */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ZFZotero = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /* ---------------------------------------------------------------------
     Zotero's data model in CSL terms

     The CSL-JSON a citation carries is what lets it format for someone
     without the item in their library; Zotero rebuilds it from the database
     on every refresh. Written from the CSL 1.0 variable list and Zotero's
     item types and fields: for each CSL variable, the Zotero fields that
     feed it, in order of preference -- the type-specific field names
     included, since the database stores those and not their base field.
     --------------------------------------------------------------------- */
  const CSL_TYPE = {
    journalArticle: 'article-journal', magazineArticle: 'article-magazine', newspaperArticle: 'article-newspaper',
    preprint: 'article', book: 'book', bookSection: 'chapter', thesis: 'thesis', report: 'report', manuscript: 'manuscript',
    document: 'document', conferencePaper: 'paper-conference', presentation: 'speech', letter: 'personal_communication',
    email: 'personal_communication', instantMessage: 'personal_communication', interview: 'interview',
    webpage: 'webpage', blogPost: 'post-weblog', forumPost: 'post', encyclopediaArticle: 'entry-encyclopedia',
    dictionaryEntry: 'entry-dictionary', dataset: 'dataset', computerProgram: 'software', standard: 'standard',
    patent: 'patent', statute: 'legislation', bill: 'bill', case: 'legal_case', hearing: 'hearing', map: 'map',
    artwork: 'graphic', film: 'motion_picture', videoRecording: 'motion_picture', audioRecording: 'song',
    podcast: 'broadcast', radioBroadcast: 'broadcast', tvBroadcast: 'broadcast',
  };

  const CSL_TEXT = {
    'container-title': ['publicationTitle', 'bookTitle', 'proceedingsTitle', 'encyclopediaTitle', 'dictionaryTitle',
      'websiteTitle', 'blogTitle', 'forumTitle', 'programTitle', 'reporter', 'code'],
    'container-title-short': ['journalAbbreviation'],
    'collection-title': ['series', 'seriesTitle'],
    'collection-number': ['seriesNumber'],
    publisher: ['publisher', 'institution', 'university', 'company', 'label', 'distributor', 'network', 'studio',
      'repository', 'organization'],
    'publisher-place': ['place'],
    event: ['conferenceName', 'meetingName'],
    number: ['number', 'reportNumber', 'billNumber', 'docketNumber', 'patentNumber', 'publicLawNumber',
      'episodeNumber', 'applicationNumber'],
    volume: ['volume', 'codeVolume', 'reporterVolume'],
    issue: ['issue'],
    page: ['pages', 'firstPage', 'codePages'],
    'number-of-pages': ['numPages'],
    'number-of-volumes': ['numberOfVolumes'],
    edition: ['edition'],
    genre: ['reportType', 'thesisType', 'letterType', 'manuscriptType', 'mapType', 'presentationType', 'postType',
      'websiteType', 'genre', 'type'],
    medium: ['medium', 'artworkMedium', 'audioRecordingFormat', 'videoRecordingFormat', 'interviewMedium', 'format'],
    authority: ['court', 'legislativeBody', 'issuingAuthority'],
    section: ['section', 'committee'],
    'chapter-number': ['session'],
    dimensions: ['artworkSize', 'runningTime'],
    scale: ['scale'],
    version: ['versionNumber'],
    archive: ['archive'],
    archive_location: ['archiveLocation'],
    'call-number': ['callNumber'],
    abstract: ['abstractNote'],
    language: ['language'],
    'title-short': ['shortTitle'],
    references: ['history'],
    note: ['extra'],
    URL: ['url'],
    DOI: ['DOI'],
    ISBN: ['ISBN'],
    ISSN: ['ISSN'],
  };

  // Creator roles and their CSL name variables. A primary role not listed
  // here (programmer, artist, performer ...) is the item's author.
  const CSL_NAMES = {
    author: 'author', editor: 'editor', seriesEditor: 'collection-editor', bookAuthor: 'container-author',
    translator: 'translator', contributor: 'contributor', director: 'director', composer: 'composer',
    interviewer: 'interviewer', recipient: 'recipient', reviewedAuthor: 'reviewed-author',
  };

  const TITLE_FIELDS = ['title', 'caseName', 'nameOfAct', 'subject'];
  const DATE_FIELDS = ['date', 'dateDecided', 'dateEnacted', 'issueDate'];

  /* ---------------------------------------------------------------------
     The WAL file
     --------------------------------------------------------------------- */

  const WAL_MAGIC_LE = 0x377f0682;
  const WAL_MAGIC_BE = 0x377f0683;

  function walChecksum(view, offset, length, bigEndian, s0, s1) {
    for (let i = offset; i < offset + length; i += 8) {
      s0 = (s0 + view.getUint32(i, !bigEndian) + s1) >>> 0;
      s1 = (s1 + view.getUint32(i + 4, !bigEndian) + s0) >>> 0;
    }
    return [s0, s1];
  }

  /**
   * The database as it stands after the committed transactions in a WAL
   * file. Frames after the last valid commit (a transaction still being
   * written when the file was copied) are ignored, as SQLite would.
   *
   * @param {Uint8Array} db
   * @param {Uint8Array|null} wal
   * @returns {{bytes: Uint8Array, frames: number, note: string}}
   */
  function applyWal(db, wal) {
    if (!wal || wal.length < 32) return { bytes: db, frames: 0, note: wal ? 'the -wal file is empty' : '' };
    const wv = new DataView(wal.buffer, wal.byteOffset, wal.byteLength);
    const magic = wv.getUint32(0, false);
    if (magic !== WAL_MAGIC_LE && magic !== WAL_MAGIC_BE) return { bytes: db, frames: 0, note: 'not a SQLite WAL file; ignored' };
    const bigEndian = magic === WAL_MAGIC_BE;
    const pageSize = wv.getUint32(8, false) || 65536;
    const salt1 = wv.getUint32(16, false);
    const salt2 = wv.getUint32(20, false);
    let [s0, s1] = walChecksum(wv, 0, 24, bigEndian, 0, 0);
    if (s0 !== wv.getUint32(24, false) || s1 !== wv.getUint32(28, false)) {
      return { bytes: db, frames: 0, note: 'the -wal header checksum is wrong; ignored' };
    }
    const dbPageSize = dbPageSizeOf(db);
    if (dbPageSize && dbPageSize !== pageSize) return { bytes: db, frames: 0, note: 'the -wal file belongs to another database; ignored' };

    const frameSize = 24 + pageSize;
    const committed = new Map();   // page number -> offset of its frame in wal
    let pending = new Map();
    let dbPages = Math.floor(db.length / pageSize);
    let frames = 0;
    for (let off = 32; off + frameSize <= wal.length; off += frameSize) {
      if (wv.getUint32(off + 8, false) !== salt1 || wv.getUint32(off + 12, false) !== salt2) break;
      [s0, s1] = walChecksum(wv, off, 8, bigEndian, s0, s1);
      [s0, s1] = walChecksum(wv, off + 24, pageSize, bigEndian, s0, s1);
      if (s0 !== wv.getUint32(off + 16, false) || s1 !== wv.getUint32(off + 20, false)) break;
      pending.set(wv.getUint32(off, false), off + 24);
      const commitSize = wv.getUint32(off + 4, false);
      if (commitSize) {
        for (const [pg, at] of pending) committed.set(pg, at);
        frames += pending.size;
        pending = new Map();
        dbPages = commitSize;
      }
    }
    if (!committed.size) return { bytes: db, frames: 0, note: 'the -wal file holds no committed changes' };
    const out = new Uint8Array(dbPages * pageSize);
    out.set(db.subarray(0, Math.min(db.length, out.length)));
    for (const [pg, at] of committed) {
      if (pg >= 1 && pg <= dbPages) out.set(wal.subarray(at, at + pageSize), (pg - 1) * pageSize);
    }
    return { bytes: out, frames, note: '' };
  }

  function dbPageSizeOf(db) {
    if (db.length < 100) return 0;
    const v = (db[16] << 8) | db[17];
    return v === 1 ? 65536 : v;
  }

  const SQLITE_HEADER = 'SQLite format 3\u0000';

  /**
   * Bytes sql.js can open: the WAL replayed, and the header switched from
   * WAL to rollback journalling, which an in-memory database needs.
   */
  function prepareDatabase(dbBytes, walBytes) {
    const db = dbBytes instanceof Uint8Array ? dbBytes : new Uint8Array(dbBytes);
    for (let i = 0; i < 16; i++) {
      if (db[i] !== SQLITE_HEADER.charCodeAt(i)) throw new Error('This is not an SQLite database. Choose zotero.sqlite from your Zotero data directory.');
    }
    const wal = walBytes ? (walBytes instanceof Uint8Array ? walBytes : new Uint8Array(walBytes)) : null;
    const applied = applyWal(db, wal);
    // A copy, whatever came in: Node's Buffer.slice() is a view, and the
    // header is about to be rewritten.
    const bytes = applied.bytes === db ? new Uint8Array(db) : applied.bytes;
    if (bytes[18] === 2) bytes[18] = 1;
    if (bytes[19] === 2) bytes[19] = 1;
    return { bytes, walFrames: applied.frames, walNote: applied.note };
  }

  /* ---------------------------------------------------------------------
     sql.js, loaded on first use

     From cdnjs, pinned and checked against its integrity hashes. Shared by
     zoterify.html and skbref.html, which both read zotero.sqlite.
     --------------------------------------------------------------------- */

  const SQLJS = {
    js: 'https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.14.2/sql-wasm.min.js',
    jsIntegrity: 'sha384-ua6rbgEfbwIWlrG1MxSagm4g3MI0VYpCkQQCjt6CtFL345h8/3ttwVWpyKiRzt/9',
    wasm: 'https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.14.2/sql-wasm.wasm',
    wasmIntegrity: 'sha384-x0YkuPkDHnKTZcB1JO4eb6j5+eU36aka+jBA6tOKTFaTz98b9V7fPT0QgZ9qyQW2',
  };

  function loadScript(src, integrity) {
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = src;
      s.integrity = integrity;
      s.crossOrigin = 'anonymous';
      s.onload = resolve;
      s.onerror = () => reject(new Error(`${src} could not be loaded`));
      document.head.appendChild(s);
    });
  }

  let sqlPromise = null;
  /** The sql.js module, loaded once per page. A failed load is not cached. */
  function loadSqlJs() {
    if (!sqlPromise) {
      sqlPromise = (async () => {
        if (typeof initSqlJs !== 'function') await loadScript(SQLJS.js, SQLJS.jsIntegrity);
        const res = await fetch(SQLJS.wasm, { integrity: SQLJS.wasmIntegrity, mode: 'cors', credentials: 'omit' });
        if (!res.ok) throw new Error(`the SQLite library could not be fetched (HTTP ${res.status})`);
        return initSqlJs({ wasmBinary: await res.arrayBuffer() }); // eslint-disable-line no-undef
      })().catch((e) => { sqlPromise = null; throw e; });
    }
    return sqlPromise;
  }

  /* ---------------------------------------------------------------------
     Queries
     --------------------------------------------------------------------- */

  function rows(db, sql, params) {
    const stmt = db.prepare(sql);
    try {
      if (params) stmt.bind(params);
      const out = [];
      while (stmt.step()) out.push(stmt.get());
      return out;
    } finally {
      stmt.free();
    }
  }

  function tryRows(db, sql, params) {
    try { return rows(db, sql, params); } catch (e) { return null; }
  }

  function hasTable(db, name) {
    return rows(db, "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?", [name]).length > 0;
  }

  /** Libraries, their names, the account and the collections. */
  function readInfo(db) {
    if (!hasTable(db, 'items') || !hasTable(db, 'itemData')) {
      throw new Error('This SQLite file is not a Zotero database: it has no items table.');
    }
    const setting = (key) => {
      const r = tryRows(db, "SELECT value FROM settings WHERE setting = 'account' AND key = ?", [key]);
      return r && r.length && r[0][0] !== null ? String(r[0][0]) : '';
    };
    const userId = setting('userID');
    const localUserKey = setting('localUserKey');
    const groups = new Map((tryRows(db, 'SELECT libraryID, groupID, name FROM groups') || []).map(([lib, gid, name]) => [lib, { groupID: gid, name }]));
    const libraries = (tryRows(db, 'SELECT libraryID, type FROM libraries') || [[1, 'user']]).map(([libraryID, type]) => {
      const g = groups.get(libraryID);
      return {
        libraryID, type,
        name: type === 'user' ? 'My Library' : (g ? g.name : `${type} ${libraryID}`),
        groupID: g ? g.groupID : null,
      };
    });
    return { userId, localUserKey, libraries, collections: listCollections(db, libraries) };
  }

  /** The item URI Zotero writes into a citation, per library. */
  function uriBase(info, libraryID) {
    const lib = info.libraries.find((l) => l.libraryID === libraryID);
    if (lib && lib.type === 'group' && lib.groupID !== null) return `http://zotero.org/groups/${lib.groupID}/items/`;
    if (info.userId) return `http://zotero.org/users/${info.userId}/items/`;
    if (info.localUserKey) return `http://zotero.org/users/local/${info.localUserKey}/items/`;
    return `http://zotero.org/users/local/${libraryID}/items/`;
  }

  /** Every collection not in the bin, with its path from the top. */
  function listCollections(db, libraries) {
    const deleted = hasTable(db, 'deletedCollections') ? 'WHERE collectionID NOT IN (SELECT collectionID FROM deletedCollections)' : '';
    const list = rows(db, `SELECT collectionID, collectionName, parentCollectionID, libraryID FROM collections ${deleted}`)
      .map(([id, name, parentId, libraryID]) => ({ id, name, parentId, libraryID }));
    const deletedItems = hasTable(db, 'deletedItems') ? 'WHERE ci.itemID NOT IN (SELECT itemID FROM deletedItems)' : '';
    const counts = new Map(rows(db, `SELECT ci.collectionID, COUNT(*) FROM collectionItems ci ${deletedItems} GROUP BY ci.collectionID`));
    const byId = new Map(list.map((c) => [c.id, c]));
    const libName = new Map((libraries || []).map((l) => [l.libraryID, l.name]));
    for (const c of list) {
      const names = [];
      const seen = new Set();
      let cur = c;
      while (cur && !seen.has(cur.id)) {
        seen.add(cur.id);
        names.push(cur.name);
        cur = byId.get(cur.parentId);
      }
      c.path = names.reverse().join(' / ');
      c.itemCount = counts.get(c.id) || 0;
      c.libraryName = libName.get(c.libraryID) || '';
    }
    return list.sort((a, b) => (a.libraryID - b.libraryID) || a.path.toLowerCase().localeCompare(b.path.toLowerCase()));
  }

  function descendantIds(collections, rootId) {
    const children = new Map();
    for (const c of collections) {
      if (c.parentId === null || c.parentId === undefined) continue;
      if (!children.has(c.parentId)) children.set(c.parentId, []);
      children.get(c.parentId).push(c.id);
    }
    const out = [rootId];
    const stack = [rootId];
    while (stack.length) {
      for (const child of children.get(stack.pop()) || []) {
        out.push(child);
        stack.push(child);
      }
    }
    return out;
  }

  /* ---------------------------------------------------------------------
     Items
     --------------------------------------------------------------------- */

  function extractYear(dateStr) {
    const m = /(?<![\p{L}\p{N}_])(\d{4})(?![\p{L}\p{N}_])/u.exec(dateStr || '');
    return m ? m[1] : '';
  }

  /** A Zotero date ("2020-03-00 March 2020") as CSL. */
  function cslDate(value) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || '');
    if (!m) return value ? { raw: value } : null;
    const parts = [m[1]];
    if (m[2] !== '00') {
      parts.push(String(Number(m[2])));
      if (m[3] !== '00') parts.push(String(Number(m[3])));
    }
    if (m[1] === '0000') return { raw: value.slice(11) || value };
    return { 'date-parts': [parts] };
  }

  /**
   * The citable items of the library, newest first.
   *
   * @param {Object} db       an open sql.js Database
   * @param {Object} info     from readInfo()
   * @param {{libraryID?: number, collectionId?: number}} [scope]
   * @param {function(number, number)} [progress]
   * @returns {Array<Object>}
   */
  function readItems(db, info, scope = {}, progress) {
    const typeName = new Map(rows(db, 'SELECT itemTypeID, typeName FROM itemTypes'));
    const skipTypes = [...typeName].filter(([, n]) => n === 'attachment' || n === 'note' || n === 'annotation').map(([id]) => id);
    const citableLibs = info.libraries.filter((l) => l.type === 'user' || l.type === 'group').map((l) => l.libraryID);

    let where = `i.itemTypeID NOT IN (${skipTypes.join(',') || -1}) AND i.libraryID IN (${citableLibs.join(',') || -1})`;
    if (hasTable(db, 'deletedItems')) where += ' AND i.itemID NOT IN (SELECT itemID FROM deletedItems)';
    const params = [];
    if (scope.collectionId !== undefined && scope.collectionId !== null) {
      const ids = descendantIds(info.collections, scope.collectionId);
      where += ` AND i.itemID IN (SELECT itemID FROM collectionItems WHERE collectionID IN (${ids.map(() => '?').join(',')}))`;
      params.push(...ids);
    } else if (scope.libraryID !== undefined && scope.libraryID !== null) {
      where += ' AND i.libraryID = ?';
      params.push(scope.libraryID);
    }
    const base = rows(db, `SELECT i.itemID, i.key, i.libraryID, i.itemTypeID FROM items i WHERE ${where} ORDER BY i.dateAdded DESC, i.itemID DESC`, params);
    if (progress) progress(1, 4);

    const byId = new Map();
    for (const [itemID, key, libraryID, itemTypeID] of base) {
      byId.set(itemID, { itemID, key, libraryID, type: typeName.get(itemTypeID) || 'document', itemTypeID, fields: {}, creators: [] });
    }

    for (const [itemID, fieldName, value] of rows(db, 'SELECT d.itemID, f.fieldName, v.value FROM itemData d JOIN itemDataValues v ON v.valueID = d.valueID JOIN fields f ON f.fieldID = d.fieldID')) {
      const rec = byId.get(itemID);
      if (rec && fieldName) rec.fields[fieldName] = value === null ? '' : String(value);
    }
    if (progress) progress(2, 4);

    const primary = new Map();
    for (const [itemTypeID, creatorTypeID] of tryRows(db, 'SELECT itemTypeID, creatorTypeID FROM itemTypeCreatorTypes WHERE primaryField = 1') || []) {
      primary.set(itemTypeID, creatorTypeID);
    }
    const creatorSql = 'SELECT ic.itemID, c.firstName, c.lastName, %MODE%, ic.creatorTypeID, ct.creatorType FROM itemCreators ic JOIN creators c ON c.creatorID = ic.creatorID LEFT JOIN creatorTypes ct ON ct.creatorTypeID = ic.creatorTypeID ORDER BY ic.itemID, ic.orderIndex';
    const creatorRows = tryRows(db, creatorSql.replace('%MODE%', 'c.fieldMode')) || rows(db, creatorSql.replace('%MODE%', '0'));
    for (const [itemID, firstName, lastName, fieldMode, creatorTypeID, creatorType] of creatorRows) {
      const rec = byId.get(itemID);
      if (!rec) continue;
      const isPrimary = primary.get(rec.itemTypeID) === creatorTypeID;
      rec.creators.push({ firstName: firstName || '', lastName: lastName || '', fieldMode: Number(fieldMode) || 0, type: creatorType || 'author', isPrimary });
    }
    if (progress) progress(3, 4);

    const items = [];
    for (const rec of byId.values()) items.push(buildItem(rec, info));
    if (progress) progress(4, 4);
    return items;
  }

  function buildItem(rec, info) {
    const f = rec.fields;
    const title = TITLE_FIELDS.map((k) => f[k]).find(Boolean) || '';
    const dateRaw = DATE_FIELDS.map((k) => f[k]).find(Boolean) || '';
    const year = extractYear(dateRaw);
    const cslType = CSL_TYPE[rec.type] || 'document';

    const authors = [];
    const editors = [];
    const csl = { id: rec.itemID, type: cslType };
    if (title) csl.title = title;
    for (const c of rec.creators) {
      if (!c.lastName && !c.firstName) continue;
      let person;
      if (c.fieldMode === 1) {
        person = { literal: c.lastName || c.firstName };
      } else {
        person = {};
        if (c.lastName) person.family = c.lastName;
        if (c.firstName) person.given = c.firstName;
      }
      const surname = c.lastName || c.firstName;
      if (c.type === 'author' || c.isPrimary) authors.push(surname);
      else if (c.type === 'editor') editors.push(surname);
      const variable = CSL_NAMES[c.type] || (c.isPrimary ? 'author' : null);
      if (variable) (csl[variable] = csl[variable] || []).push(person);
    }
    const issued = cslDate(dateRaw);
    if (issued) csl.issued = issued;
    if (f.accessDate) {
      const a = /^(\d{4})-(\d{2})-(\d{2})/.exec(f.accessDate);
      if (a) csl.accessed = { 'date-parts': [[a[1], String(Number(a[2])), String(Number(a[3]))]] };
    }
    for (const [variable, fields] of Object.entries(CSL_TEXT)) {
      const value = fields.map((k) => f[k]).find(Boolean);
      if (value) csl[variable] = value;
    }

    return {
      key: rec.key,
      itemId: rec.itemID,
      libraryId: rec.libraryID,
      itemTypeZotero: rec.type,
      itemTypeCsl: cslType,
      title,
      year,
      authors,
      editors,
      uri: uriBase(info, rec.libraryID) + rec.key,
      csl,
    };
  }

  /* The creator roles that are an item type's primary one somewhere in
     Zotero's schema. The database says which is primary for each type; an
     item from the web API does not, so these count as its author. */
  const PRIMARY_CREATORS = new Set(['author', 'artist', 'cartographer', 'director', 'interviewee', 'inventor',
    'performer', 'podcaster', 'presenter', 'programmer', 'sponsor']);

  /**
   * An item as the Zotero web API returns it ({key, library, data}), in the
   * form readItems() gives, so that one matcher serves both. The API names
   * fields as the database does ("reportNumber", "institution").
   *
   * @param {Object} apiItem
   * @param {number} itemID  any number unique among the items matched together
   */
  function itemFromApi(apiItem, itemID) {
    const data = (apiItem && apiItem.data) || {};
    const key = String((apiItem && apiItem.key) || data.key || '');
    const fields = {};
    for (const [name, value] of Object.entries(data)) if (typeof value === 'string' && value) fields[name] = value;
    // The database keeps a date as "2019-03-00 March 2019"; the API gives
    // "March 2019", and the parsed part in meta.parsedDate ("2019-03").
    const dateField = DATE_FIELDS.find((name) => fields[name]);
    if (dateField) {
      const parsed = /^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$/.exec((apiItem.meta && apiItem.meta.parsedDate) || '')
        || /^(\d{4})$/.exec(fields[dateField]);
      if (parsed) fields[dateField] = `${parsed[1]}-${parsed[2] || '00'}-${parsed[3] || '00'} ${fields[dateField]}`;
    }
    const creators = (Array.isArray(data.creators) ? data.creators : []).map((c) => ({
      firstName: c.name !== undefined ? '' : String(c.firstName || ''),
      lastName: String(c.name !== undefined ? c.name : c.lastName || ''),
      fieldMode: c.name !== undefined ? 1 : 0,
      type: c.creatorType || 'author',
      isPrimary: PRIMARY_CREATORS.has(c.creatorType),
    }));
    const lib = (apiItem && apiItem.library) || {};
    const item = buildItem({ itemID, key, libraryID: lib.id || 0, type: data.itemType || 'document', fields, creators },
      { libraries: [], userId: '', localUserKey: '' });
    item.uri = lib.type === 'group' ? `http://zotero.org/groups/${lib.id}/items/${key}`
      : lib.type === 'user' ? `http://zotero.org/users/${lib.id}/items/${key}` : '';
    return item;
  }

  return {
    applyWal, prepareDatabase, readInfo, readItems, listCollections, descendantIds, uriBase,
    extractYear, cslDate, CSL_TYPE, loadSqlJs, itemFromApi,
  };
}));
