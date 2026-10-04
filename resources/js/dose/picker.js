/*
  dose_coefficients.html: the radionuclide picker of the Batch tab.

  A dialog with the radionuclides of a system to the left, narrowed by a
  search, an element, a half-life range, a decay mode and whether the route
  has forms for them, and the chosen ones to the right. They move with the
  buttons (those selected, or all the filters show), by double-clicking, or
  with Enter in a list; Shift and Ctrl (Cmd) select several, as in any list.
  "Use these" hands the chosen names back, in the catalogue's order; Cancel,
  the close button and Escape leave the batch as it was.

  Names come from the catalogue and go into the page as text nodes.
*/
const DAY_MIN = 1 / 1440;
const LOWER = [['0', 'any'], [String(10 * DAY_MIN), '10 min'], [String(1 / 24), '1 h'], ['1', '1 d'], ['30', '30 d'], ['365.25', '1 y'], ['36525', '100 y'], ['365250000', '1 million y']];
const UPPER = [['Infinity', 'any'], [String(1 / 24), '1 h'], ['1', '1 d'], ['30', '30 d'], ['365.25', '1 y'], ['36525', '100 y'], ['365250000', '1 million y']];
const MODES = [['', 'any'], ['A', 'alpha'], ['B-', 'beta minus'], ['B+ EC', 'beta plus or electron capture'], ['IT', 'isomeric transition'], ['SF', 'spontaneous fission']];
const modesOf = (m) => new Set(String(m || '').match(/B-|B\+|EC|IT|SF|A/g) || []);
const key = (s) => String(s).toLowerCase().replace(/[\s-]+/g, '');

/**
 * Open the picker.
 * @param {object} o  {h, halfLife, nuclides (the catalogue's, sorted), system, route, chosen (names),
 *   left (tokens of the field that are not radionuclides of the system), onUse(names)}
 */
export function openPicker(o) {
  const { h, halfLife } = o;
  const all = o.nuclides;
  const chosen = new Set(o.chosen);
  const elements = [];
  for (const n of all) {
    const el = n.name.split('-')[0];
    if (elements[elements.length - 1]?.[0] === el) elements[elements.length - 1][1]++;
    else elements.push([el, 1]);
  }
  const hasRoute = (n) => (n[o.route] || []).length > 0;
  const optionOf = (n) => h('option', { value: n.name }, `${n.name} · ${n.T ? halfLife(n.T) : n.t || ''}`);
  const select = (id, list, value) => h('select', { id }, ...list.map(([v, l]) => h('option', { value: v, selected: v === value }, l)));

  const dlg = h('dialog', { class: 'dc-picker', 'aria-labelledby': 'dcPickTitle' },
    h('div', { class: 'dc-picker-head' },
      h('h2', { id: 'dcPickTitle' }, 'Choose radionuclides'),
      h('span', { class: 'dc-muted' }, `ICRP ${o.system} system, ${o.route}`),
      h('button', { type: 'button', class: 'dc-picker-x', 'aria-label': 'Close without using them', 'data-pick': 'cancel' }, '×')),
    h('div', { class: 'dc-picker-filters' },
      h('label', { class: 'dc-picker-search' }, h('span', {}, 'Search'),
        h('input', { type: 'search', id: 'dcPickSearch', placeholder: 'Cs, 137, cs-13…', autocomplete: 'off', spellcheck: 'false' })),
      h('label', {}, h('span', {}, 'Element'),
        h('select', { id: 'dcPickElement' }, h('option', { value: '' }, 'all'), ...elements.map(([el, k]) => h('option', { value: el }, `${el} (${k})`)))),
      h('label', {}, h('span', {}, 'Half-life from'), select('dcPickFrom', LOWER, '0')),
      h('label', {}, h('span', {}, 'to'), select('dcPickTo', UPPER, 'Infinity')),
      h('label', {}, h('span', {}, 'Decay'), select('dcPickMode', MODES, '')),
      h('label', { class: 'dc-check dc-picker-route' }, h('input', { type: 'checkbox', id: 'dcPickRoute', checked: true }), h('span', {}, `only those with forms for ${o.route}`))),
    h('div', { class: 'dc-picker-lists' },
      h('div', { class: 'dc-picker-col' },
        h('label', { for: 'dcPickLeft' }, 'Available ', h('span', { class: 'dc-muted', id: 'dcPickLeftN' })),
        h('select', { id: 'dcPickLeft', multiple: true, size: 14 })),
      h('div', { class: 'dc-picker-moves', role: 'group', 'aria-label': 'Move' },
        h('button', { type: 'button', class: 'dc-btn secondary small', 'data-pick': 'add' }, 'Add →'),
        h('button', { type: 'button', class: 'dc-btn secondary small', 'data-pick': 'addAll' }, 'Add all shown ⇉'),
        h('button', { type: 'button', class: 'dc-btn secondary small', 'data-pick': 'remove' }, '← Remove'),
        h('button', { type: 'button', class: 'dc-btn secondary small', 'data-pick': 'removeAll' }, '⇇ Remove all')),
      h('div', { class: 'dc-picker-col' },
        h('label', { for: 'dcPickRight' }, 'Chosen ', h('span', { class: 'dc-muted', id: 'dcPickRightN' })),
        h('select', { id: 'dcPickRight', multiple: true, size: 14 }))),
    h('p', { class: 'dc-muted dc-picker-hint' },
      'Double-click, or press Enter, to move a radionuclide to the other list; Shift or Ctrl (⌘) and click select several; Enter in the search adds all it shows. ',
      o.left?.length ? `Not radionuclides of this system, left out: ${o.left.slice(0, 12).join(', ')}${o.left.length > 12 ? '…' : ''}.` : ''),
    h('div', { class: 'dc-picker-foot' },
      h('button', { type: 'button', class: 'dc-btn secondary', 'data-pick': 'cancel' }, 'Cancel'),
      h('button', { type: 'button', class: 'dc-btn', 'data-pick': 'use', id: 'dcPickUse' }, 'Use these')));
  document.body.append(dlg);
  const $ = (id) => dlg.querySelector(`#${id}`);
  const left = $('dcPickLeft'), right = $('dcPickRight');

  function shown() {
    const q = key($('dcPickSearch').value);
    const el = $('dcPickElement').value;
    const from = Number($('dcPickFrom').value), to = Number($('dcPickTo').value);
    const mode = $('dcPickMode').value;
    const route = $('dcPickRoute').checked;
    return all.filter((n) => {
      if (chosen.has(n.name)) return false;
      if (q && !key(n.name).includes(q)) return false;
      if (el && n.name.split('-')[0] !== el) return false;
      if (n.T != null && (n.T < from || n.T > to)) return false;
      if (mode) { const m = modesOf(n.m); if (!mode.split(' ').some((x) => m.has(x))) return false; }
      return !route || hasRoute(n);
    });
  }
  function render(keepLeft = new Set(), keepRight = new Set()) {
    const l = shown();
    left.replaceChildren(...l.map(optionOf));
    right.replaceChildren(...all.filter((n) => chosen.has(n.name)).map(optionOf));
    for (const opt of left.options) opt.selected = keepLeft.has(opt.value);
    for (const opt of right.options) opt.selected = keepRight.has(opt.value);
    $('dcPickLeftN').textContent = `${l.length.toLocaleString('en')} shown of ${all.length.toLocaleString('en')}`;
    $('dcPickRightN').textContent = `${chosen.size.toLocaleString('en')}`;
    $('dcPickUse').textContent = chosen.size ? `Use these ${chosen.size.toLocaleString('en')}` : 'Use none';
  }
  // Move what is selected in one list to the other, and select what now
  // stands where the first of them stood, so that Enter can go on.
  function move(from, names, add) {
    if (!names.length) return;
    const at = [...from.options].findIndex((x) => names.includes(x.value));
    for (const n of names) { if (add) chosen.add(n); else chosen.delete(n); }
    render();
    const next = from.options[Math.min(at, from.options.length - 1)];
    if (next) { next.selected = true; next.scrollIntoView?.({ block: 'nearest' }); }
  }
  const selectedIn = (sel) => [...sel.selectedOptions].map((x) => x.value);
  const act = {
    add: () => move(left, selectedIn(left), true),
    addAll: () => move(left, [...left.options].map((x) => x.value), true),
    remove: () => move(right, selectedIn(right), false),
    removeAll: () => move(right, [...right.options].map((x) => x.value), false),
    use: () => { close(); o.onUse(all.filter((n) => chosen.has(n.name)).map((n) => n.name)); },
    cancel: () => close(),
  };
  function close() {
    if (dlg.open) dlg.close();
    dlg.remove();
  }
  dlg.addEventListener('click', (e) => {
    const b = e.target.closest('[data-pick]');
    if (b) act[b.dataset.pick]();
  });
  left.addEventListener('dblclick', (e) => { if (e.target.tagName === 'OPTION') move(left, [e.target.value], true); });
  right.addEventListener('dblclick', (e) => { if (e.target.tagName === 'OPTION') move(right, [e.target.value], false); });
  left.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); act.add(); } });
  right.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); act.remove(); } });
  // The search narrows the list as it is typed; Enter in it adds all it shows.
  $('dcPickSearch').addEventListener('input', () => render(new Set(selectedIn(left))));
  $('dcPickSearch').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); act.addAll(); } });
  for (const id of ['dcPickElement', 'dcPickFrom', 'dcPickTo', 'dcPickMode', 'dcPickRoute']) $(id).addEventListener('change', () => render(new Set(selectedIn(left))));
  // Escape is the dialog's cancel.
  dlg.addEventListener('cancel', (e) => { e.preventDefault(); close(); });
  render();
  dlg.showModal();
  $('dcPickSearch').focus();
  return dlg;
}
