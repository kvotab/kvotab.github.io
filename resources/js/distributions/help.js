/* ==========================================================================
   distributions.html: THE FAMILIES IN THE HELP

   One card per family, made from its own definition (families.js), so that
   the Help cannot disagree with what the page computes: its parameters,
   density and distribution function, mean and variance, its
   parameterisations, how it is fitted, and the same distribution in SciPy.
   The formulas are typeset by MathJax, which is fetched the first time the
   Help is opened.
   ========================================================================== */

import { FAMILIES, GROUPS, parameterisationsOf } from './families.js';
import { DOMAINS, symbolOf } from './kit.js';

const MATHJAX = {
  src: 'https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-mml-chtml.js',
  integrity: 'sha384-Wuix6BuhrWbjDBs24bXrjf4ZQ5aFeFWBuKkFekO2t8xFU0iNaLQfp2K6/1Nxveei',
};

let mathjax = null;

function loadMathJax() {
  if (mathjax) return mathjax;
  mathjax = new Promise((resolve, reject) => {
    if (window.MathJax && window.MathJax.typesetPromise) { resolve(window.MathJax); return; }
    window.MathJax = {
      tex: { inlineMath: [['\\(', '\\)']], displayMath: [] },
      options: { enableMenu: false },
      startup: { typeset: false },
    };
    const s = document.createElement('script');
    s.src = MATHJAX.src;
    s.integrity = MATHJAX.integrity;
    s.crossOrigin = 'anonymous';
    s.async = true;
    s.onload = () => window.MathJax.startup.promise.then(() => resolve(window.MathJax));
    s.onerror = () => reject(new Error('MathJax could not be loaded'));
    document.head.append(s);
  });
  return mathjax;
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

const tex = (t) => (t ? `\\(${t}\\)` : '');

function card(fam) {
  const box = el('div', 'ds-fam');
  box.id = `fam-${fam.id}`;
  box.append(el('h4', '', fam.label), el('p', '', fam.blurb));
  const dl = el('dl');
  const add = (label, value, isCode = false) => {
    if (!value) return;
    dl.append(el('dt', '', label));
    const dd = el('dd');
    if (isCode) dd.append(el('code', '', value)); else dd.textContent = value;
    dl.append(dd);
  };
  add('Parameters', fam.params.map((p) => {
    const sym = symbolOf(p);
    const words = p.label.replace(sym, '').replace(/[()]/g, '').replace(/\s+/g, ' ').trim();
    const note = DOMAINS[p.domain] ? DOMAINS[p.domain].note : 'any number';
    return `${sym}: ${words.toLowerCase()}, ${note}`;
  }).join('; '));
  if (fam.tex) {
    add(fam.kind === 'discrete' ? 'Probability' : 'Density', tex(fam.tex.pdf));
    add('Distribution function', tex(fam.tex.cdf));
    add('Mean', tex(fam.tex.mean));
    add('Variance', tex(fam.tex.variance));
  }
  add('Given by', parameterisationsOf(fam).map((p) => p.label.toLowerCase()).join('; '));
  let fitted = '';
  if (!fam.fit) fitted = 'not fitted';
  else {
    const why = fam.fit.applicable ? fam.fit.applicable({}) : '';
    if (/is not fitted/.test(why || '')) fitted = why.replace(/^is not fitted/, 'not fitted');
    else {
      fitted = `by maximum likelihood${fam.fit.mom || fam.free ? ' and by the method of moments' : ''}`;
      if (fam.fit.note) fitted += `, with ${fam.fit.note}`;
      if (fam.fit.regular === false) fitted += '; no standard errors (the support moves with a parameter)';
    }
  }
  add('Fitted', fitted);
  add('In SciPy', fam.scipy ? `scipy.stats.${fam.scipy}` : '', true);
  box.append(dl);
  return box;
}

/** The family cards, grouped, into a container; then typeset. */
export function buildHelp(container) {
  container.replaceChildren();
  const toc = el('ul', 'ds-toc');
  for (const [g, glabel] of GROUPS) {
    const fams = FAMILIES.filter((f) => f.group === g);
    if (!fams.length) continue;
    const h = el('h4', '', glabel);
    h.id = `fams-${g.toLowerCase().replace(/\s+/g, '-')}`;
    container.append(h);
    for (const fam of fams) {
      container.append(card(fam));
      const li = el('li');
      const a = el('a', '', fam.label);
      a.href = `#fam-${fam.id}`;
      a.dataset.onClick = 'ds:helpLink';
      li.append(a);
      toc.append(li);
    }
  }
  container.prepend(toc);
  loadMathJax().then((MJ) => MJ.typesetPromise([container])).catch(() => {
    container.prepend(el('p', 'ds-hint', 'The formulas are shown as TeX: MathJax, which draws them, could not be loaded.'));
  });
}
