/*
  The rules of 1215757 that its example references do not exercise: page
  locators, multiple sources in one parenthesis, year disambiguation, the
  reference-list order of chapter 5, and the Swedish forms of chapter 6.
*/
const fs = require('fs');
const path = require('path');
const CSL = require('citeproc');

/* CSL locale files, fetched by ./fetch-locales.sh */
const LOCALES = path.join(__dirname, 'locales');

const STYLES = {
  en: path.join(__dirname, '..', '..', 'csl', 'skb_reference_template_en.csl'),
  sv: path.join(__dirname, '..', '..', 'csl', 'skb_reference_template_sv.csl'),
};
const localeFor = lang => fs.readFileSync(
  path.join(LOCALES, fs.existsSync(path.join(LOCALES, `locales-${lang}.xml`)) ? `locales-${lang}.xml` : 'locales-en-US.xml'), 'utf8');

function engineFor(styleKey, items) {
  const byId = Object.fromEntries(items.map(i => [i.id, i]));
  const engine = new CSL.Engine(
    { retrieveLocale: localeFor, retrieveItem: id => byId[id] },
    fs.readFileSync(STYLES[styleKey], 'utf8'));
  engine.updateItems(items.map(i => i.id));
  return engine;
}
const clean = v => String(v == null ? '' : v)
  .replace(/<[^>]+>/g, '').replace(/ /g, ' ').replace(/[’‘]/g, "'").trim();

let pass = 0; const failures = [];
function is(label, actual, expected) {
  if (clean(actual) === clean(expected)) { pass++; console.log('  ok    ' + label); }
  else {
    failures.push(label);
    console.log('  FAIL  ' + label);
    console.log('        guide : ' + clean(expected));
    console.log('        style : ' + clean(actual));
  }
}

// ── Items reused across the checks ────────────────────────────────────────
const book = (id, family, year, title) => ({
  id, type: 'book', author: [{ family, given: 'A' }],
  issued: { 'date-parts': [[year]] }, title, publisher: 'P', 'publisher-place': 'X',
});

/* ═══════════════════════════ Section 3.2.1 ═══════════════════════════ */
console.log('3.2.1 page locators (English: p and pp, no full stop)');
{
  const items = [book('fridman', 'Fridman', 2002, 'A'), book('murray', 'Murray', 1998, 'B')];
  const e = engineFor('en', items);
  is('single page',  e.makeCitationCluster([{ id: 'fridman', locator: '69', label: 'page' }]), '(Fridman 2002, p 69)');
  is('page range',   e.makeCitationCluster([{ id: 'murray', locator: '120-132', label: 'page' }]), '(Murray 1998, pp 120–132)');
}

console.log('\n3.2.1 several sources in one parenthesis, separated by commas');
{
  const items = [
    book('wiley', 'Wiley', 1995, 'A'),
    { ...book('lee', 'Lee', 2001, 'B'), author: [{ family: 'Lee', given: 'A' }, { family: 'Wen', given: 'B' }] },
    { ...book('oconnor', "O'Connor", 2008, 'C') },
  ];
  const e = engineFor('en', items);
  is('two sources', e.makeCitationCluster([{ id: 'lee' }, { id: 'oconnor' }]), "(Lee and Wen 2001, O'Connor 2008)");
}

console.log('\n3.2.1 several works by the same author, different years');
{
  const items = [book('b02', 'Brown', 2002, 'A'), book('b04', 'Brown', 2004, 'B')];
  const e = engineFor('en', items);
  is('collapsed years', e.makeCitationCluster([{ id: 'b02' }, { id: 'b04' }]), '(Brown 2002, 2004)');
}

console.log('\n3.2.1 several works by the same author in the same year');
{
  const items = [
    { ...book('l93a', 'Lindroos', 1993, 'Climate modelling') },
    { ...book('l93b', 'Lindroos', 1993, 'Understanding our Earth') },
  ];
  const e = engineFor('en', items);
  is('a and b suffixes', e.makeCitationCluster([{ id: 'l93a' }, { id: 'l93b' }]), '(Lindroos 1993a, b)');
  const [params, entries] = e.makeBibliography();
  is('suffix in the list too', clean(entries[0]).slice(0, 22), 'Lindroos A, 1993a. Cli');
}

console.log('\n3.2.1 three or more authors are shortened to et al. in the text');
{
  const items = [{
    id: 'fisher', type: 'book',
    author: [{ family: 'Fisher', given: 'N I' }, { family: 'Lewis', given: 'T' }, { family: 'Embleton', given: 'B J J' }],
    issued: { 'date-parts': [[1987]] }, title: 'Statistical analysis of spherical data',
    publisher: 'Cambridge University Press', 'publisher-place': 'Cambridge',
  }];
  const e = engineFor('en', items);
  is('in text', e.makeCitationCluster([{ id: 'fisher' }]), '(Fisher et al. 1987)');
  is('all names in the list', e.makeBibliography()[1][0],
     'Fisher N I, Lewis T, Embleton B J J, 1987. Statistical analysis of spherical data. Cambridge: Cambridge University Press.');
}

/* ═══════════════════════════ Chapter 5 order ═══════════════════════════ */
console.log('\n5 reference-list order: one author, then one co-author, then et al.');
{
  const bentz = (id, coauthors, year, title) => ({
    id, type: 'report',
    author: [{ family: 'Bentz', given: 'A' }, ...coauthors],
    issued: { 'date-parts': [[year]] }, title,
    number: 'SKB TR-00-00', publisher: 'Svensk Kärnbränslehantering AB',
  });
  const n = (family, given) => ({ family, given });
  const items = [
    bentz('i1994', [n('Garboczi', 'M'), n('Haecker', 'P'), n('Jensen', 'J')], 1994, 'F'),
    bentz('i2001b', [n('Williams', 'J'), n('MacKenzie', 'P')], 2001, 'I'),
    bentz('i1997', [], 1997, 'A'),
    bentz('i2005', [n('Haecker', 'P')], 2005, 'D'),
    bentz('i1999a', [n('Coveney', 'A'), n('Garboczi', 'M'), n('Kleyn', 'E'), n('Stutzman', 'T')], 1999, 'G'),
    bentz('i2007', [], 2007, 'B'),
    bentz('i1999c', [n('Stutzman', 'T')], 1999, 'E'),
    bentz('i1999b', [n('Jensen', 'J'), n('Hansen', 'J'), n('Olesen', 'I'), n('Stang', 'E'), n('Haecker', 'P')], 1999, 'H'),
    bentz('i2001a', [n('Conway', 'M')], 2001, 'C'),
  ];
  const e = engineFor('en', items);
  const [params] = e.makeBibliography();
  const order = params.entry_ids.map(ids => ids[0]);
  is('order', order.join(' '), 'i1997 i2007 i2001a i2005 i1999c i1994 i1999a i1999b i2001b');
}

/* ═══════════════════════════ Chapter 6, Swedish ═══════════════════════════ */
console.log('\n6 Swedish publication: och, s, red, I, u å, Tillgänglig, uppl');
{
  const items = [
    { id: 'mill', type: 'book', author: [{ family: 'Mill', given: 'A' }], issued: { 'date-parts': [[2005]] },
      title: 'En titel', publisher: 'Förlag', 'publisher-place': 'Stockholm' },
    { id: 'wyllie', type: 'book', author: [{ family: 'Wyllie', given: 'D C' }, { family: 'Mah', given: 'C W' }],
      issued: { 'date-parts': [[2004]] }, title: 'Rock slope engineering: civil and mining', edition: '4',
      publisher: 'Spon Press', 'publisher-place': 'New York', language: 'en' },
    { id: 'jenne', type: 'book', editor: [{ family: 'Jenne', given: 'E A' }], issued: { 'date-parts': [[1998]] },
      title: 'Adsorption of metals by geomedia', publisher: 'Academic Press', 'publisher-place': 'San Diego, CA', language: 'en' },
    { id: 'saugier', type: 'chapter',
      author: [{ family: 'Saugier', given: 'B' }, { family: 'Roy', given: 'R' }, { family: 'Mooney', given: 'H A' }],
      editor: [{ family: 'Roy', given: 'J' }, { family: 'Saugier', given: 'B' }, { family: 'Mooney', given: 'H A' }],
      issued: { 'date-parts': [[2001]] }, title: 'Estimations of global terrestrial productivity',
      'container-title': 'Terrestrial global productivity', publisher: 'Academic Press',
      'publisher-place': 'London', page: '543-557', language: 'en' },
    { id: 'smhi', type: 'webpage', author: [{ literal: 'SMHI' }], title: 'Klimatdata',
      URL: 'https://www.smhi.se/', accessed: { 'date-parts': [[2011, 8, 15]] } },
  ];
  const e = engineFor('sv', items);
  const bib = Object.fromEntries(e.makeBibliography()[0].entry_ids.map((ids, i) => [ids[0], e.makeBibliography()[1][i]]));

  is('och between two authors', e.makeCitationCluster([{ id: 'wyllie' }]), '(Wyllie och Mah 2004)');
  is('s for pages',            e.makeCitationCluster([{ id: 'mill', locator: '65-67', label: 'page' }]), '(Mill 2005, s 65–67)');
  is('u å for no date',        e.makeCitationCluster([{ id: 'smhi' }]), '(SMHI, u å)');
  is('(red) after an editor',  bib['jenne'], 'Jenne E A (red), 1998. Adsorption of metals by geomedia. San Diego, CA: Academic Press. (På engelska.)');
  is('uppl for edition',       bib['wyllie'], 'Wyllie D C, Mah C W, 2004. Rock slope engineering: civil and mining. 4. uppl. New York: Spon Press. (På engelska.)');
  is('I before the editors',   bib['saugier'], 'Saugier B, Roy R, Mooney H A, 2001. Estimations of global terrestrial productivity. I Roy J, Saugier B, Mooney H A (red). Terrestrial global productivity. London: Academic Press, 543–557. (På engelska.)');
  is('Tillgänglig and a Swedish month', bib['smhi'], 'SMHI, u å. Klimatdata. Tillgänglig: https://www.smhi.se/ [15 augusti 2011].');
}

console.log('\n' + pass + ' passed, ' + failures.length + ' failed');
process.exit(failures.length ? 1 : 0);
