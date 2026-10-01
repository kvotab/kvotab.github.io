/* ==========================================================================
   UTSEENDEN - THE LOOKS OF WINNETKAKORT AND GLOSOR

   The list of looks card-looks.css defines, and the picker that chooses
   one. Both pages keep the chosen look per person and set it on <html> as
   data-look; the head of each page does the same from storage before the
   first paint, so a page never flashes its standard look first.

   The motif is also in each look's CSS (--wk-motif); the test checks that
   the two agree.
   ========================================================================== */

const CARD_LOOKS = (() => {
  'use strict';

  const LOOKS = Object.freeze([
    { id: 'kvot', name: 'Kvot', motif: '', group: 'lugn' },
    { id: 'minimal', name: 'Minimal', motif: '', group: 'lugn' },
    { id: 'natt', name: 'Natt', motif: '🌙', group: 'lugn' },
    { id: 'skogen', name: 'Skogen', motif: '🌲', group: 'lugn' },
    { id: 'papper', name: 'Skrivbok', motif: '✏️', group: 'lugn' },
    { id: 'kontrast', name: 'Hög kontrast', motif: '', group: 'lugn' },
    { id: 'rymden', name: 'Rymden', motif: '🚀', group: 'rolig' },
    { id: 'havet', name: 'Havet', motif: '🐠', group: 'rolig' },
    { id: 'djungeln', name: 'Djungeln', motif: '🦜', group: 'rolig' },
    { id: 'godis', name: 'Godisbutiken', motif: '🍭', group: 'rolig' },
    { id: 'regnbage', name: 'Regnbåge', motif: '🌈', group: 'rolig' },
    { id: 'enhorning', name: 'Enhörning', motif: '🦄', group: 'rolig' },
    { id: 'dino', name: 'Dinosaurier', motif: '🦖', group: 'rolig' },
    { id: 'hjalte', name: 'Superhjälte', motif: '💥', group: 'rolig' },
    { id: 'pirat', name: 'Piratskatten', motif: '🏴‍☠️', group: 'rolig' },
    { id: 'vinter', name: 'Vinterland', motif: '⛄', group: 'rolig' },
    { id: 'robot', name: 'Robotlabbet', motif: '🤖', group: 'rolig' },
    { id: 'pixel', name: 'Pixelspel', motif: '👾', group: 'rolig' },
    { id: 'tavla', name: 'Svarta tavlan', motif: '🍎', group: 'rolig' },
    { id: 'solnedgang', name: 'Solnedgång', motif: '🌅', group: 'rolig' },
  ]);

  const ids = LOOKS.map(l => l.id);
  const DEFAULT = 'kvot';
  const valid = id => ids.includes(id);

  /** The look on the page: set on <html>, where card-looks.css reads it. */
  function apply(id) {
    document.documentElement.dataset.look = valid(id) ? id : DEFAULT;
  }

  const byId = id => LOOKS.find(l => l.id === id) || LOOKS[0];
  const label = id => { const l = byId(id); return l.motif ? `${l.name} ${l.motif}` : l.name; };

  /**
   * The picker: every look as a tile that carries the look itself, so it
   * shows its own colours, fonts and card, with its motif stuck on like a
   * sticker. Calm looks first, then the fun ones.
   *
   * @param {string} current - the chosen look
   * @param {string} action - the data-on-click action a tile runs
   * @param {string} sample - what the little card on each tile says
   */
  function pickerHtml(current, action, sample) {
    const esc = kvotEscapeHtml;
    const tile = l => `<button type="button" class="wk-look" data-look="${esc(l.id)}" aria-pressed="${l.id === current}" data-on-click="${esc(action)}">
        <span class="wk-look-scene" aria-hidden="true"><span class="wk-look-card"><span class="wk-look-band"></span><span class="wk-look-sample">${esc(sample)}</span></span>${l.motif ? `<span class="wk-look-motif">${esc(l.motif)}</span>` : ''}</span>
        <span class="wk-look-name">${esc(l.name)}</span>
      </button>`;
    const group = (g, title) => `<p class="wk-looks-head">${title}</p><div class="wk-looks">${LOOKS.filter(l => l.group === g).map(tile).join('')}</div>`;
    return group('lugn', 'Lugna och tydliga') + group('rolig', 'Roliga');
  }

  /** Mark the chosen tile. */
  function markPicked(root, current) {
    for (const b of root.querySelectorAll('.wk-look')) b.setAttribute('aria-pressed', String(b.dataset.look === current));
  }

  return { LOOKS, ids, DEFAULT, valid, apply, label, pickerHtml, markPicked };
})();
