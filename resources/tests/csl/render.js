/*
  Render a set of items through one of the SKB CSL styles and print the
  bibliography entry and the in-text citation for each, so they can be diffed
  against the examples printed in 1215757.
*/
const fs = require('fs');
const path = require('path');
const CSL = require('citeproc');

/* CSL locale files, fetched by ./fetch-locales.sh */
const LOCALES = path.join(__dirname, 'locales');

const HERE = __dirname;
const STYLES = {
  en: path.join(__dirname, '..', '..', 'csl', 'skb_reference_template_en.csl'),
  sv: path.join(__dirname, '..', '..', 'csl', 'skb_reference_template_sv.csl'),
};

const localeCache = {};
function retrieveLocale(lang) {
  if (localeCache[lang]) return localeCache[lang];
  for (const candidate of [lang, lang.split('-')[0] === 'en' ? 'en-GB' : lang, 'en-US']) {
    const file = path.join(LOCALES, `locales-${candidate}.xml`);
    if (fs.existsSync(file)) return (localeCache[lang] = fs.readFileSync(file, 'utf8'));
  }
  return fs.readFileSync(path.join(LOCALES, 'locales-en-US.xml'), 'utf8');
}

function stripTags(html) {
  return html
    .replace(/<[^>]+>/g, '')
    .replace(/&#38;/g, '&').replace(/&amp;/g, '&')
    .replace(/&#60;/g, '<').replace(/&lt;/g, '<')
    .replace(/&#62;/g, '>').replace(/&gt;/g, '>')
    .replace(/&#160;/g, ' ').replace(/&nbsp;/g, ' ')
    .replace(/\s+$/g, '')
    .trim();
}

/**
 * @param {string} styleKey - 'en' or 'sv'
 * @param {Array} items - CSL-JSON items
 * @param {Array} [citations] - [{id, locator, label, "author-only"/"suppress-author"}]
 * @returns {{bibliography: string[], citations: string[]}}
 */
function render(styleKey, items, citations) {
  const byId = Object.fromEntries(items.map(item => [item.id, item]));
  const engine = new CSL.Engine({
    retrieveLocale,
    retrieveItem: id => byId[id],
  }, fs.readFileSync(STYLES[styleKey], 'utf8'));

  engine.updateItems(items.map(item => item.id));
  /* The bibliography comes back in the style's own sort order, so pair each
     entry with its item through entry_ids rather than by position. */
  const [params, entries] = engine.makeBibliography();
  const byEntryId = {};
  params.entry_ids.forEach((ids, index) => { byEntryId[ids[0]] = stripTags(entries[index]); });

  /*
    citeproc-js renders the two halves of a narrative citation separately;
    Zotero joins them. A well-known Harvard style behaves the same way, so
    this is how the application composes "Geschwind (2001)", not a style
    property.
  */
  const rendered = {};
  for (const group of (citations || [])) {
    if (group.length === 2 && group[0]['author-only']) {
      rendered[group[0].id] = engine.makeCitationCluster([group[0]])
        + ' ' + engine.makeCitationCluster([group[1]]);
    } else {
      rendered[group[0].id] = engine.makeCitationCluster(group);
    }
  }
  return { bibliography: byEntryId, citations: rendered, order: params.entry_ids.map(ids => ids[0]) };
}

module.exports = { render, stripTags };
