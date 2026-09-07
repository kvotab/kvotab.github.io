const { render } = require('./render');
const CASES = [...require('./cases-guide-a'), ...require('./cases-guide-b')];

const styleKey = process.argv[2] || 'en';
const items = CASES.map(c => c.item);
const citations = CASES.map(c =>
  c.citationMode === 'author-only'
    ? [{ id: c.item.id, 'author-only': true }, { id: c.item.id, 'suppress-author': true }]
    : [{ id: c.item.id }]);

const { bibliography, citations: rendered, order } = render(styleKey, items, citations);

/* The guide is typeset with a straight apostrophe; citeproc curls it. That is
   a typographic detail, not one of the rules the instruction states. */
const norm = value => String(value == null ? '' : value).replace(/[’‘]/g, "'");

const limitations = [];
let bibPass = 0, citePass = 0;
const problems = [];
CASES.forEach((c) => {
  const got = bibliography[c.item.id];
  if (norm(got) === norm(c.expected)) { bibPass++; }
  else if (c.knownLimitation && norm(got) === norm(c.knownLimitation)) { limitations.push(c.section); }
  else problems.push({ kind: 'bibliography', section: c.section, expected: c.expected, got });

  if (c.citation) {
    const gotCite = String(rendered[c.item.id] || '').replace(/\u00a0/g, ' ').replace(/<[^>]+>/g, '').trim();
    // "author-only" renders as "Name (year)" in two parts joined by a space.
    if (norm(gotCite) === norm(c.citation)) citePass++;
    else problems.push({ kind: 'citation', section: c.section, expected: c.citation, got: gotCite });
  }
});

console.log(`bibliography: ${bibPass}/${CASES.length} match the guide`);
console.log(`in-text:      ${citePass}/${CASES.filter(c => c.citation).length} match the guide`);
if (limitations.length) {
  console.log(`known CSL limitations (documented in the style): ${limitations.length}`);
  limitations.forEach(section => console.log('  - ' + section));
}

if (problems.length) {
  console.log('\n' + '='.repeat(78));
  for (const p of problems) {
    console.log(`\n[${p.kind}] ${p.section}`);
    console.log('  guide : ' + p.expected);
    console.log('  style : ' + p.got);
    // point at the first difference
    let k = 0;
    while (k < p.expected.length && k < p.got.length && p.expected[k] === p.got[k]) k++;
    if (k < Math.max(p.expected.length, p.got.length)) {
      console.log('  diverges at ' + k + ': guide "' + p.expected.slice(k, k + 40)
        + '" vs style "' + p.got.slice(k, k + 40) + '"');
    }
  }
}
if (process.env.SHOW_ORDER) {
  console.log('\nbibliography order produced by the style:');
  order.forEach((id, i) => console.log('  ' + String(i + 1).padStart(2) + '. ' + bibliography[id].slice(0, 72)));
}
process.exit(problems.length ? 1 : 0);
