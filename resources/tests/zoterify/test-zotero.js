#!/usr/bin/env node
/* zoterify-zotero.js: reading zotero.sqlite, and replaying its -wal file.

   Runs the module under Node with sql.js, the same WebAssembly SQLite the
   page loads from cdnjs (the .wasm files are byte-identical). Install it
   beside this file once:

       cd resources/tests/zoterify && npm install --no-save sql.js@1.14.2
       node test-zotero.js

   Checks: the WAL replay against a database copied while a transaction
   was in its -wal file (and against a torn, a foreign and an empty -wal
   file); which items are citable; the URIs Zotero writes; the CSL-JSON;
   collections and scopes; an item from the web API read into the same
   form.

   Exit status is 0 when every check passes. */
'use strict';

const fs = require('fs');
const path = require('path');
const Z = require('../../js/zoterify-zotero.js');

let initSqlJs;
try {
  initSqlJs = require(path.join(__dirname, 'node_modules', 'sql.js'));
} catch (e) {
  console.log('sql.js is not installed here: cd resources/tests/zoterify && npm install --no-save sql.js@1.14.2');
  process.exit(2);
}

const F = (name) => fs.readFileSync(path.join(__dirname, 'fixtures', name));
let checks = 0;
const failures = [];
// Objects compare with their keys sorted: CSL-JSON has no key order.
const canon = (v) => JSON.stringify(v, (k, x) => (x && typeof x === 'object' && !Array.isArray(x)
  ? Object.fromEntries(Object.keys(x).sort().map((key) => [key, x[key]])) : x));
function check(label, got, want) {
  checks++;
  const a = canon(got);
  const b = canon(want);
  if (a !== b) failures.push(`${label}\n     got  ${a}\n     want ${b}`);
}

(async () => {
  const SQL = await initSqlJs();
  const open = (db, wal) => {
    const prep = Z.prepareDatabase(db, wal);
    const sqldb = new SQL.Database(prep.bytes);
    const info = Z.readInfo(sqldb);
    return { prep, sqldb, info, items: Z.readItems(sqldb, info) };
  };
  const keys = (items) => items.map((i) => i.key);

  /* ---- the WAL file ------------------------------------------------------ */
  const db = F('fixture-wal.sqlite');
  const wal = F('fixture-wal.sqlite-wal');
  const alone = open(db, null);
  check('the database alone has not seen Stone 2018', keys(alone.items).includes('STONE018'), false);
  check('its header says WAL mode', [db[18], db[19]], [2, 2]);
  check('which is switched to rollback for sql.js', [alone.prep.bytes[18], alone.prep.bytes[19]], [1, 1]);
  const withWal = open(db, wal);
  check('with its -wal file it has', keys(withWal.items).includes('STONE018'), true);
  check('eleven pages replayed', withWal.prep.walFrames, 11);
  check('and nothing else changed', keys(withWal.items).filter((k) => k !== 'STONE018'), keys(alone.items));
  check('the original bytes are not touched', [db[18], db[19]], [2, 2]);

  const pageSize = wal.readUInt32BE(8);
  const frame = 24 + pageSize;
  const torn = Buffer.concat([wal, wal.subarray(32, 32 + frame), wal.subarray(32, 32 + frame / 2)]);
  const tornRes = open(db, torn);
  check('a torn tail (a stale frame, half a frame) is ignored', [tornRes.prep.walFrames, keys(tornRes.items)], [11, keys(withWal.items)]);
  const foreign = Buffer.from(wal);
  foreign.writeUInt32BE((foreign.readUInt32BE(16) + 1) >>> 0, 16);
  const foreignRes = Z.applyWal(new Uint8Array(db), new Uint8Array(foreign));
  check('a -wal file whose header checksum fails is refused', foreignRes.note, 'the -wal header checksum is wrong; ignored');
  check('an empty -wal file, as Zotero leaves after a checkpoint', Z.applyWal(new Uint8Array(db), new Uint8Array(0)).note, 'the -wal file is empty');
  const flipped = Buffer.from(wal);
  flipped[32 + 24 + 100] ^= 0xff;
  check('a frame with a wrong checksum ends the replay before it', Z.applyWal(new Uint8Array(db), new Uint8Array(flipped)).frames, 0);
  let refused = '';
  try { Z.prepareDatabase(new Uint8Array(Buffer.from('not a database at all, sorry')), null); } catch (e) { refused = e.message; }
  check('a file that is not SQLite is refused with a reason', refused.startsWith('This is not an SQLite database.'), true);

  /* ---- the library -------------------------------------------------------- */
  const lib = open(F('fixture.sqlite'), null);
  check('libraries', lib.info.libraries.map((l) => [l.libraryID, l.type, l.name, l.groupID]),
    [[1, 'user', 'My Library', null], [2, 'group', 'Team references', 777], [3, 'feed', 'feed 3', null]]);
  check('citable items, newest first; no attachment, note, annotation, bin or feed', keys(lib.items),
    ['NILSS15B', 'NILSS15A', 'CASE2003', 'PROGR022', 'BILDT010', 'LANE0014', 'OHMAN014', 'GARCI021', 'BROWN019', 'JONES20B', 'JONES20A', 'SMITH020']);
  const item = (k) => lib.items.find((i) => i.key === k);
  check('a synced user library: users/<userID>', item('SMITH020').uri, 'http://zotero.org/users/4242/items/SMITH020');
  check('a group library: groups/<groupID>', item('OHMAN014').uri, 'http://zotero.org/groups/777/items/OHMAN014');
  check('an unsynced library: users/local/<localUserKey>',
    Z.uriBase({ userId: '', localUserKey: 'LOCALKEY', libraries: [{ libraryID: 1, type: 'user' }] }, 1), 'http://zotero.org/users/local/LOCALKEY/items/');
  check('the CSL-JSON of a journal article, with month', item('SMITH020').csl, {
    id: 10, type: 'article-journal', title: 'Buffer erosion in dilute groundwater', author: [{ family: 'Smith', given: 'John' }],
    issued: { 'date-parts': [['2020', '3']] }, 'container-title': 'Applied Clay Science', volume: '185', page: '105-117', DOI: '10.1000/aclay.2020.1',
  });
  check('a report, with an institutional series editor as a literal name', item('BROWN019').csl, {
    id: 13, type: 'report', title: 'Groundwater flow at Forsmark', author: [{ family: 'Brown', given: 'Peter' }],
    'collection-editor': [{ literal: 'Svensk Kärnbränslehantering AB' }], issued: { 'date-parts': [['2019']] },
    number: 'R-19-01', publisher: 'Svensk Kärnbränslehantering AB', 'publisher-place': 'Stockholm',
  });
  check('software: the programmer is the author', [item('PROGR022').authors, item('PROGR022').csl.author], [['Programmer'], [{ family: 'Programmer', given: 'Pat' }]]);
  check('a case: title from caseName, year from dateDecided', [item('CASE2003').title, item('CASE2003').year, item('CASE2003').csl.issued],
    ['Example v. Sample', '2003', { 'date-parts': [['2003', '5', '1']] }]);
  check('three authors, in order', item('OHMAN014').authors, ['Öhman', 'Odén', 'Vidstrand']);

  check('collections not in the bin, with paths and direct counts',
    lib.info.collections.map((c) => [c.path, c.itemCount, c.libraryName]),
    [['Thesis', 1, 'My Library'], ['Thesis / Chapter 2', 2, 'My Library'], ['Site data', 1, 'Team references']]);
  check('a collection with its subcollections, the binned item left out',
    keys(Z.readItems(lib.sqldb, lib.info, { collectionId: 1 })), ['JONES20B', 'JONES20A', 'SMITH020']);
  check('one library', keys(Z.readItems(lib.sqldb, lib.info, { libraryID: 2 })), ['LANE0014', 'OHMAN014']);

  /* ---- an item from the web API, as skbref.html matches it ---------------- */
  const api = Z.itemFromApi({
    key: 'BROWN019', library: { type: 'group', id: 777 },
    data: {
      key: 'BROWN019', itemType: 'report', title: 'Groundwater flow at Forsmark', date: '2019', reportNumber: 'R-19-01',
      institution: 'Svensk Kärnbränslehantering AB', place: 'Stockholm', relations: {}, tags: [],
      creators: [{ creatorType: 'author', firstName: 'Peter', lastName: 'Brown' }, { creatorType: 'seriesEditor', name: 'Svensk Kärnbränslehantering AB' }],
    },
  }, 13);
  check('an API item reads as the database item does', [api.key, api.itemId, api.title, api.year, api.authors, api.editors, api.csl],
    [item('BROWN019').key, item('BROWN019').itemId, item('BROWN019').title, item('BROWN019').year, item('BROWN019').authors,
      item('BROWN019').editors, item('BROWN019').csl]);
  check('its URI names its group', api.uri, 'http://zotero.org/groups/777/items/BROWN019');
  const film = Z.itemFromApi({ key: 'FILM0001', library: { type: 'user', id: 4242 }, data: { itemType: 'film', title: 'A film',
    creators: [{ creatorType: 'director', firstName: 'Ann', lastName: 'Director' }, { creatorType: 'contributor', lastName: 'Other' }] } }, 1);
  check('the primary creator of a type (a director) is its author; a contributor is not', [film.authors, film.uri],
    [['Director'], 'http://zotero.org/users/4242/items/FILM0001']);
  const dated = Z.itemFromApi({ key: 'DATED001', meta: { parsedDate: '2020-03' }, data: { itemType: 'journalArticle', title: 'T', date: 'March 2020' } }, 1);
  check('an API date is read through meta.parsedDate', [dated.year, dated.csl.issued], ['2020', { 'date-parts': [['2020', '3']] }]);

  console.log(`${checks} checks`);
  if (failures.length) {
    console.log(`${failures.length} FAILED:`);
    for (const f of failures) console.log(`  ${f}`);
    process.exit(1);
  }
  console.log('all passed');
})();
