/*
  A front view of the body for the Model tab: where the organs and tissues
  that a model's compartments stand for are. Schematic, not to scale: the
  shapes sit roughly where they are in the reference phantoms, and each part
  lists the source regions it stands for, in the names of the ICRP 133/155
  SAF files (ICRP 103 system) and of DCAL's dosimetry (ICRP 60 system).

    partsOf(region)            -> [part id], none for a sink
    drawBody(used, labelOf)    -> SVGSVGElement
    badge(n)                   -> the numbered disc of a part
        used     Map(part id -> number shown on the part)
        labelOf  part id -> its tooltip text

  Every part is a <g class="bp" data-part="id" data-tip="label">, so the
  page can light a part and the compartments it stands for together, and
  show the label in its own tooltip.
*/
const NS = 'http://www.w3.org/2000/svg';
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) e.setAttribute(k, String(v));
  for (const k of kids) if (k != null) e.append(k);
  return e;
};
const ell = (cx, cy, rx, ry, rot = 0) => el('ellipse', { cx, cy, rx, ry, transform: rot ? `rotate(${rot} ${cx} ${cy})` : null });
const circ = (cx, cy, r) => el('circle', { cx, cy, r });
const path = (d, cls) => el('path', { d, class: cls });
const line = (x1, y1, x2, y2, cls) => el('line', { x1, y1, x2, y2, class: cls });

/* The outline: the right half (the viewer's right) from the top of the neck
   to the crotch, and its mirror image back. */
const HALF = [
  ['M', 100, 54], ['L', 109, 54], ['L', 109, 68],
  ['C', 120, 72, 136, 74, 144, 80], ['C', 152, 86, 155, 96, 155, 108],
  ['L', 158, 168], ['L', 163, 236],
  ['C', 166, 246, 166, 258, 160, 264], ['C', 155, 268, 151, 262, 151, 254],
  ['L', 148, 240], ['L', 144, 172], ['L', 138, 112],
  ['C', 138, 140, 132, 170, 131, 192], ['C', 132, 212, 138, 228, 138, 246],
  ['C', 138, 280, 134, 310, 132, 340], ['C', 131, 370, 128, 396, 126, 418],
  ['C', 127, 424, 132, 428, 132, 432], ['L', 108, 432], ['L', 108, 424],
  ['C', 108, 410, 108, 380, 109, 350], ['C', 110, 320, 106, 290, 102, 266],
  ['C', 101, 263, 100, 262, 100, 262],
];
function outline() {
  const end = (s) => s.slice(-2);
  const m = (x, y) => `${200 - x},${y}`;
  const out = HALF.map(([c, ...p]) => c + p.join(','));
  for (let i = HALF.length - 1; i >= 1; i--) {
    const s = HALF[i], to = end(HALF[i - 1]);
    out.push(s[0] === 'L' ? `L${m(...to)}` : `C${m(s[3], s[4])} ${m(s[1], s[2])} ${m(...to)}`);
  }
  return out.join(' ') + ' Z';
}
const BODY = outline();
/* A number in a disc, or a pill for two or more digits. */
export function badge(n) {
  const t = String(n), w = 12.8 + (t.length - 1) * 5;
  return el('g', {}, el('rect', { x: -w / 2, y: -6.4, width: w, height: 12.8, rx: 6.4, class: 'disc' }),
    el('text', { y: 3, 'text-anchor': 'middle' }, document.createTextNode(t)));
}
const silhouette = (cls) => [path(BODY, cls), el('ellipse', { cx: 100, cy: 30, rx: 20, ry: 25, class: cls })];

/* The parts, in the order they are numbered (head to feet), with the regions
   they stand for (lower case, '_' and blanks as '-'), where their number goes,
   and their shapes. */
export const PARTS = [
  { id: 'brain', label: 'Brain', regions: ['brain'], at: [100, 21], draw: () => [ell(100, 23, 15, 11)] },
  { id: 'eyes', minor: true, label: 'Eye lenses', regions: ['eye-lens'], at: [86, 35], draw: () => [circ(93, 34, 2.2), circ(107, 34, 2.2)] },
  { id: 'pituitary', minor: true, label: 'Pituitary gland', regions: ['p-gland'], at: [114, 30], draw: () => [circ(100, 31, 1.8)] },
  { id: 'et', label: 'Nose and throat (extrathoracic airways)', regions: ['et1-sur', 'et2-sur', 'et2-bnd', 'et2-seq', 'et1-wall', 'et2-wall', 'np-cont', 'et'],
    at: [100, 40], draw: () => [path('M97,37h6v7h-6z M98.6,51h2.8v9h-2.8z')] },
  { id: 'mouth', label: 'Mouth, teeth and tongue', regions: ['o-cavity', 'o-mucosa', 'teeth-s', 'teeth-v', 'tongue', 'tonsils'], at: [100, 49], draw: () => [ell(100, 48, 6.5, 3)] },
  { id: 'saliva', label: 'Salivary glands', regions: ['s-glands'], at: [84, 52], draw: () => [ell(87, 50, 3.5, 2.5), ell(113, 50, 3.5, 2.5)] },
  { id: 'ln-et', minor: true, label: 'Lymph nodes of the neck', regions: ['ln-et'], at: [117, 61], draw: () => [circ(91, 61, 1.8), circ(109, 61, 1.8)] },
  { id: 'thyroid', label: 'Thyroid', regions: ['thyroid'], at: [100, 67], draw: () => [ell(96.6, 67, 3, 2.3), ell(103.4, 67, 3, 2.3)] },
  { id: 'oesophagus', label: 'Oesophagus', regions: ['oesophag-s', 'oesophag-f', 'oesophag-w', 'oesophagus'], at: [104, 146], draw: () => [el('rect', { x: 101.5, y: 60, width: 3, height: 90, rx: 1.5 })] },
  { id: 'airways', label: 'Bronchi and bronchioles', regions: ['bronchi', 'bronchi-b', 'bronchi-q', 'brchiole', 'brchiole-b', 'brchiole-q', 'bbi-gel', 'bbi-sol', 'bbi-bnd', 'bbi-seq', 'bbe-gel', 'bbe-sol', 'bbe-bnd', 'bbe-seq', 'tb-cont', 'rt-air'],
    at: [96, 78], draw: () => [path('M98,62V92 M98,92L86,104 M98,92L111,104 M86,104l-6,10 M86,104l2,12 M111,104l6,10 M111,104l-2,12', 'tube')] },
  { id: 'lungs', label: 'Lungs (alveolar region)', regions: ['alv', 'ai', 'lungs', 'lung-tis', 'lng-tiss', 'lng-cont', 'p-cont'], at: [77, 120],
    draw: () => [path('M95,88C86,86 74,92 70,110C66,130 66,146 70,152C78,150 88,152 95,148Z'), path('M105,88C114,86 126,92 130,110C134,130 134,146 130,152C124,150 114,154 108,150C112,138 106,128 104,120Z')] },
  { id: 'ln-th', minor: true, label: 'Lymph nodes of the chest', regions: ['ln-th', 'ln-lung'], at: [92, 102], draw: () => [circ(94, 97, 1.8), circ(103, 97, 1.8)] },
  { id: 'thymus', label: 'Thymus', regions: ['thymus'], at: [100, 84], draw: () => [ell(100, 84, 4.5, 5)] },
  { id: 'heart', label: 'Heart wall', regions: ['ht-wall', 'ht-cont'], at: [108, 131], draw: () => [path('M100,118C108,112 120,116 118,128C116,138 106,144 102,146C96,140 92,132 94,124C95,120 97,118 100,118Z')] },
  { id: 'blood', label: 'Blood', regions: ['blood', 'ht-cont'], at: [52, 150],
    draw: () => [path('M104,118C104,108 98,104 94,108 M100,108V236 M100,236L88,262L84,336L82,410 M100,236L112,262L116,336L118,410 M100,108L66,88L54,128L46,200L42,236 M100,108L134,88L146,128L154,200L158,236', 'vessel')] },
  { id: 'breast', minor: true, label: 'Breasts', regions: ['breast', 'breasts'], at: [124, 112], draw: () => [circ(84, 124, 8), circ(116, 124, 8)] },
  { id: 'liver', label: 'Liver', regions: ['liver'], at: [80, 163], draw: () => [path('M68,152C80,148 100,150 112,154C110,162 100,170 88,176C80,180 72,178 68,170Z')] },
  { id: 'gallbladder', label: 'Gallbladder', regions: ['gb-wall', 'gb-cont'], at: [91, 182], draw: () => [ell(87, 176, 3.5, 2.6)] },
  { id: 'stomach', label: 'Stomach', regions: ['st-cont', 'st-mucosa', 'st-wall'], at: [119, 169], draw: () => [path('M108,156C118,152 128,156 128,166C128,178 120,186 110,184C104,183 102,178 106,174C112,172 116,168 112,162Z')] },
  { id: 'spleen', label: 'Spleen', regions: ['spleen'], at: [136, 152], draw: () => [ell(131, 160, 3.6, 7.5, 20)] },
  { id: 'adrenals', label: 'Adrenal glands', regions: ['adrenals'], at: [131, 179], draw: () => [path('M77,184L80.5,178L84,184Z M116,184L119.5,178L123,184Z')] },
  { id: 'pancreas', label: 'Pancreas', regions: ['pancreas'], at: [104, 192], draw: () => [ell(104, 188, 12, 2.8, -8)] },
  { id: 'kidneys', label: 'Kidneys', regions: ['kidneys'], at: [70, 192], draw: () => [ell(80, 192, 5, 8), ell(120, 192, 5, 8)] },
  { id: 'ureters', label: 'Ureters', regions: ['ureters'], at: [86, 236], draw: () => [path('M82,199L95,248 M118,199L105,248', 'tube thin')] },
  { id: 'colon-r', label: 'Right colon', regions: ['rc-cont', 'rc-mucosa', 'rc-wall', 'uli-cont', 'uli-wall'], at: [76, 220], draw: () => [path('M76,240V206Q76,202 80,202H100', 'gut')] },
  { id: 'colon-l', label: 'Left colon', regions: ['lc-cont', 'lc-mucosa', 'lc-wall', 'lli-cont', 'lli-wall'], at: [124, 220], draw: () => [path('M100,202H120Q124,202 124,206V236', 'gut')] },
  { id: 'small-int', label: 'Small intestine', regions: ['si-cont', 'si-mucosa', 'si-wall', 'si-villi'], at: [100, 222],
    draw: () => [path('M85,212C92,206 108,206 115,212C120,220 118,232 111,236C104,240 95,240 89,236C82,231 80,219 85,212Z'), path('M88,216q6,-4 12,0t12,0 M87,224q6,-4 13,0t12,0 M90,232q5,-3 10,0t10,0', 'texture')] },
  { id: 'colon-rs', label: 'Rectosigmoid colon', regions: ['rs-cont', 'rs-mucosa', 'rs-wall', 'lli-cont', 'lli-wall'], at: [113, 247], draw: () => [path('M124,236C124,248 112,247 106,250L104,262', 'gut')] },
  { id: 'uterus', minor: true, label: 'Uterus', regions: ['uterus'], at: [100, 241], draw: () => [ell(100, 242, 5, 3.5)] },
  { id: 'ovaries', label: 'Ovaries', regions: ['ovaries'], at: [85, 246], draw: () => [circ(90, 243, 2.3), circ(110, 243, 2.3)] },
  { id: 'bladder', label: 'Urinary bladder', regions: ['ub-wall', 'ub-cont'], at: [100, 252], draw: () => [ell(100, 252, 7.5, 5.5)] },
  { id: 'prostate', minor: true, label: 'Prostate', regions: ['prostate'], at: [113, 262], draw: () => [ell(100, 260, 3, 2.3)] },
  { id: 'testes', label: 'Testes', regions: ['testes'], at: [87, 271], draw: () => [ell(96, 268, 2.4, 3), ell(104, 268, 2.4, 3)] },
  { id: 'bone-t', label: 'Trabecular bone (spine, pelvis, ribs, ends of long bones)', regions: ['t-bone-s', 't-bone-v', 'trab-bone-s', 'trab-bone-v'], at: [69, 236],
    draw: () => [path('M100,62V242', 'bone spine'), path('M70,236C70,226 80,226 90,236C95,242 105,242 110,236C120,226 130,226 130,236C130,250 116,258 100,258C84,258 70,250 70,236Z', 'bone'),
      path('M100,100C90,100 76,104 72,112 M100,100C110,100 124,104 128,112 M100,114C90,114 76,118 72,126 M100,114C110,114 124,118 128,126 M100,128C90,128 78,132 74,140 M100,128C110,128 122,132 126,140', 'bone rib'),
      circ(62, 86, 4), circ(138, 86, 4), circ(84, 264, 4), circ(116, 264, 4), circ(82, 342, 3.5), circ(118, 342, 3.5)] },
  { id: 'marrow-r', label: 'Marrow of trabecular bone (most of the red marrow)', regions: ['r-marrow', 't-marrow'], at: [131, 236], draw: () => [path('M100,66V238', 'marrow spine'), path('M76,238C80,233 86,234 90,240 M124,238C120,233 114,234 110,240', 'marrow')] },
  { id: 'bone-c', label: 'Cortical bone (shafts of the long bones)', regions: ['c-bone-s', 'c-bone-v', 'cort-bone-s', 'cort-bone-v'], at: [83, 300],
    draw: () => [path('M62,90L51,166 M138,90L149,166 M50,172L43,234 M150,172L157,234 M84,268L82,336 M116,268L118,336 M82,348L80,412 M118,348L120,412', 'bone long')] },
  { id: 'marrow-y', label: 'Marrow of the long bones (yellow marrow)', regions: ['y-marrow', 'c-marrow'], at: [117, 300], draw: () => [path('M61,100L52,160 M139,100L148,160 M84,276L82,330 M116,276L118,330', 'marrow')] },
  { id: 'cartilage', minor: true, label: 'Cartilage', regions: ['cartilage'], at: [129, 344], draw: () => [circ(82, 342, 1.6), circ(118, 342, 1.6)] },
  { id: 'ln-sys', minor: true, label: 'Lymph nodes', regions: ['ln-sys'], at: [66, 102], draw: () => [circ(66, 106, 1.8), circ(134, 106, 1.8), circ(80, 256, 1.8), circ(120, 256, 1.8)] },
  { id: 'muscle', minor: true, label: 'Muscle', regions: ['muscle'], at: [80, 384],
    draw: () => [ell(52, 128, 5, 26, 10), ell(148, 128, 5, 26, -10), ell(46, 204, 3.6, 24, 6), ell(154, 204, 3.6, 24, -6), ell(82, 302, 9, 30), ell(118, 302, 9, 30), ell(81, 382, 6, 24), ell(119, 382, 6, 24)] },
  // A band just inside the outline (drawn clipped to the body).
  { id: 'adipose', label: 'Adipose tissue', regions: ['adipose'], at: [66, 204], draw: () => silhouette('band') },
  { id: 'skin', label: 'Skin', regions: ['skin'], at: [160, 204], draw: () => silhouette('skin') },
  // The whole body, under everything else.
  { id: 'other', label: 'Other tissues (those the model does not name)', regions: ['other', 'body-tis', 'bt-soft'], at: [120, 384], draw: () => silhouette('fill') },
];
const BY_REGION = new Map();
for (const p of PARTS) for (const r of p.regions) BY_REGION.set(r, [...(BY_REGION.get(r) || []), p.id]);
const norm = (r) => String(r || '').trim().toLowerCase().replace(/[_\s]+/g, '-');

/** The parts a source region stands for ([] for sinks and unknown names). */
export function partsOf(region) {
  return BY_REGION.get(norm(region)) || [];
}

/**
 * @param {Map<string, number>} used  part id -> its number
 * @param {(id: string) => string} labelOf  the tooltip of a part
 */
export function drawBody(used, labelOf) {
  const svg = el('svg', { viewBox: '0 0 200 440', class: 'dc-body-svg', role: 'img', 'aria-label': 'Where the compartments are in the body' });
  svg.append(el('defs', {},
    el('clipPath', { id: 'dcBodyClip' }, ...silhouette()),
    el('pattern', { id: 'dcBodyHatch', width: 5, height: 5, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' },
      el('line', { x1: 0, y1: 0, x2: 0, y2: 5, class: 'hatch' }))));
  const part = (p) => el('g', { class: `bp ${p.id}${used.has(p.id) ? ' used' : ''}`, 'data-part': p.id, 'data-tip': labelOf(p.id) }, ...p.draw());
  const byId = (id) => PARTS.find((p) => p.id === id);
  // The body (other tissues), the fat just inside its outline, the organs
  // (the small or superficial ones only when the model has them), the skin
  // over them, and the numbers over everything.
  svg.append(part(byId('other')), el('g', { 'clip-path': 'url(#dcBodyClip)' }, part(byId('adipose'))));
  for (const p of PARTS) if (!['other', 'adipose', 'skin'].includes(p.id) && (!p.minor || used.has(p.id))) svg.append(part(p));
  svg.append(part(byId('skin')));
  for (const p of PARTS) {
    if (!used.has(p.id)) continue;
    svg.append(el('g', { class: 'bp-num', 'data-part': p.id, 'data-tip': labelOf(p.id), transform: `translate(${p.at[0]},${p.at[1]})` },
      badge(used.get(p.id))));
  }
  return svg;
}
