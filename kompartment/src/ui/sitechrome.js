/**
 * The site page's header and footer, seen from inside the frame.
 *
 * kompartment.html frames this tool under the site's own fixed header and
 * above its footer (`?chrome=kvotab`, see ./start.js). Framed, the tool's bar
 * carries one more button at its end: the full window, which has the page put
 * its header and footer away -- in place, so the model, its run and all the
 * rest in here stay just as they are. In the full window the bar also carries
 * what the header and the footer did:
 *
 *   - the kvot mark, first in the bar, which opens the site's home page. In a
 *     new tab, as the footer's kvotab.se does: a model in progress lives in
 *     this page and nowhere else until it is saved;
 *   - the site's light/dark switch, beside the full-window button. The page
 *     makes the choice and sends it back in as `kvot:theme` (see app.js).
 *
 * The page knows whether its chrome is shown, and says so: the button asks
 * (`kvot:full`), and the page's answer, the same message back, is what sets
 * `data-chrome-full` on the root. The stylesheet reads that attribute (see
 * ../../css/theme-kvotab.css), so the room kept for the header and footer
 * goes and these controls show. `?full=1` sets the attribute before the
 * first paint, for a page that starts in the full window.
 *
 * Messages go only to and from the window that framed this one, same-origin,
 * and the page's answer is taken only as a boolean.
 */

import { el } from './parts.js';

// (Read when asked, not when this loads: the suite loads every module
// without a document.)
const root = () => document.documentElement;

/** Whether this is the site page's frame. */
export const framed = () => root().getAttribute('data-chrome') === 'kvotab';

const isFull = () => root().hasAttribute('data-chrome-full');
const isDark = () => root().getAttribute('data-theme') === 'dark';

// A message to the page, if there is one to take it.
function ask(message) {
	if (window.parent === window) return;
	try { window.parent.postMessage(message, location.origin); } catch { /* no page to ask */ }
}

const SVG = 'http://www.w3.org/2000/svg';

// Four corners, out to the full window or back in.
function corners(full) {
	const s = document.createElementNS(SVG, 'svg');
	for (const [k, v] of Object.entries({ viewBox: '0 0 16 16', width: 15, height: 15, 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.6, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' })) s.setAttribute(k, String(v));
	const p = document.createElementNS(SVG, 'path');
	p.setAttribute('d', full ? 'M6 2v4H2M10 2v4h4M14 10h-4v4M2 10h4v4' : 'M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4');
	s.append(p);
	return s;
}

// Every copy of the two buttons says what is so now (the editor's bar and
// the running app's each have a pair).
function paint() {
	const full = isFull(), dark = isDark();
	for (const b of document.querySelectorAll('.kvot-full')) {
		b.setAttribute('aria-pressed', String(full));
		b.title = full ? 'Show the site’s header and footer again' : 'Full window: Kompartment without the site’s header and footer';
		b.replaceChildren(corners(full));
	}
	for (const b of document.querySelectorAll('.kvot-theme')) {
		b.textContent = dark ? '☀️' : '🌙';
		b.title = dark ? 'Switch to light mode' : 'Switch to dark mode';
	}
}

/** The kvot mark, for the start of a bar; null outside the site page. */
export function homeLink() {
	if (!framed()) return null;
	return el('a', {
		className: 'kvot-home', href: '../index.html', target: '_blank', rel: 'noopener',
		title: 'kvot ab: the home page (opens in a new tab)',
	}, el('img', { src: '../resources/images/kvot-logotype.svg', alt: 'kvot ab', width: 22, height: 22 }));
}

/** The light/dark switch and the full-window button, for the end of a bar;
    none outside the site page. */
export function endButtons() {
	if (!framed()) return [];
	const theme = el('button', { type: 'button', className: 'ghost kvot-theme' });
	theme.addEventListener('click', () => ask({ type: 'kvot:toggle-theme' }));
	const full = el('button', { type: 'button', className: 'ghost kvot-full', 'aria-label': 'Full window' });
	full.addEventListener('click', () => ask({ type: 'kvot:full', full: !isFull() }));
	queueMicrotask(paint);
	return [theme, full];
}

/** Listen to the page: once, at boot, when framed. */
export function listen() {
	if (!framed()) return;
	window.addEventListener('message', (ev) => {
		if (ev.origin !== location.origin || ev.source !== window.parent) return;
		if (ev.data?.type !== 'kvot:full' || typeof ev.data.full !== 'boolean') return;
		root().toggleAttribute('data-chrome-full', ev.data.full);
		paint();
	});
	// The theme is set by app.js's own `kvot:theme` handler; its switch follows.
	new MutationObserver(paint).observe(root(), { attributes: true, attributeFilter: ['data-theme'] });
}
