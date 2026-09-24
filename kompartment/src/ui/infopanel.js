/**
 * What a setting is, on demand, beside the setting.
 *
 * A small (i) beside a setting's name opens a panel over the right-hand side
 * of the window that says what the setting does, what to write in it, what an
 * empty box means and what number that comes to, and where it is kept. It is
 * meant to replace the tooltip, which could not do any of that well: a tooltip
 * appears only while the pointer rests, vanishes the moment the reader moves to
 * the box to act on what it said, has no room for more than a sentence, cannot
 * be reached from the keyboard, and does not exist on a touch screen.
 *
 * One panel at a time. Another (i) replaces what it shows; the same (i), the
 * x in its corner, or Escape closes it. It stays open while the reader works,
 * because reading about a setting while changing it is the point -- and when
 * the panel that drew the (i) is rebuilt, as the sidebar is on every edit, the
 * panel is rebuilt with it, so what it says follows the model: pick another
 * solver and the defaults it lists are that solver's.
 *
 * A topic is plain data, so a caller writes what it knows and this file
 * decides how it looks:
 *
 *   {
 *     kicker:   'Simulation setting',          the line above the title
 *     title:    'Relative tolerance',
 *     lead:     'The error a step may make…',  a string, or several paragraphs
 *     facts:    [['Default', '1e-3'], ...],    a short table, label and value
 *     sections: [{ heading, text, list, choices }],
 *   }
 *
 * `text` is a paragraph or several; `list` is bullet points; `choices` is
 * `[[name, what it does], ...]`, for a setting that is a choice. Any of the
 * strings may carry `code` in backticks and **emphasis** in double stars;
 * nothing else is read as markup. The panel is built from elements and text
 * nodes, never from markup, like the rest of the interface -- a topic may one
 * day quote a block name, and a name comes out of a model file.
 *
 * `more` is the heading of the section of the Guide that says the rest, and
 * becomes a link at the foot of the panel; what following it does is the
 * page's to say (`setInfoLinks`), since only the page knows where the Guide is.
 *
 * **Inside a dialog.** A modal dialog makes everything outside it inert, a
 * panel over the page included, so an (i) inside a dialog opens the panel
 * inside that dialog: it is laid over the window all the same, and is part of
 * what the dialog lets you reach. It sits beside the dialog where there is room
 * and over its edge, under its title bar, where there is not, and goes when
 * the dialog does.
 */

import { el } from './parts.js';

/** What each key shows, as last handed over: the latest drawing of an (i) wins. */
const topics = new Map();

/** The open panel, and what it is showing. */
let panel = null;
let shown = null;

/** What following a `more` link does: the page's, set once. See `setInfoLinks`. */
let follow = null;

/**
 * Says what a topic's `more` link does: `go(heading)` is handed the heading of
 * the Guide section the topic names.
 */
export function setInfoLinks(go) {
	follow = go;
}

/**
 * The (i) for a setting.
 *
 * @param {string} key  what the topic is, unique on the page (`sim:rtol`)
 * @param {object|(() => object)} topic  the topic, or a function that makes it
 *   when the panel is opened -- for one that depends on the model as it is
 *   then, such as the defaults of the solver chosen
 * @returns {HTMLButtonElement}
 */
export function infoButton(key, topic) {
	topics.set(key, topic);
	const title = resolve(topic)?.title ?? 'this setting';
	const b = el('button', {
		type: 'button',
		className: `info-btn${shown?.key === key ? ' is-open' : ''}`,
		'aria-label': `About ${title}`,
		'aria-expanded': String(shown?.key === key),
		'aria-controls': 'info-panel',
	});
	b.dataset.info = key;
	b.append(glyph());
	b.addEventListener('click', (ev) => {
		// Inside a row that may have a click of its own -- a summary that
		// folds, a label -- and this click is only the panel's.
		ev.preventDefault();
		ev.stopPropagation();
		if (shown?.key === key) closeInfo();
		else openInfo(key, b);
	});
	return b;
}

/**
 * Opens the panel on topic `key`, or shows it there if it is open already.
 *
 * @param {string} key
 * @param {HTMLElement} [from]  the (i) it was opened from, which says whether
 *   it opens over the page or inside a dialog
 */
export function openInfo(key, from = null) {
	if (!topics.has(key)) return;
	installClosers();
	shown = { key };
	// The panel belongs where the (i) is: inside the dialog that holds it, or
	// over the page. One left behind by a dialog that has closed is gone.
	const host = from?.closest?.('dialog[open]') ?? document.body;
	if (panel && (!panel.isConnected || panel.parentElement !== host)) {
		panel.remove();
		panel = null;
	}
	paint(host);
	markButtons();
	// To the panel, so a screen reader starts reading it and Escape reaches
	// it; the (i) gets the focus back when it closes.
	panel.querySelector('.info-panel-body')?.focus({ preventScroll: true });
}

/** Closes the panel, and puts the keyboard back on the (i) that opened it. */
export function closeInfo() {
	if (!shown) return;
	const key = shown.key;
	shown = null;
	panel?.remove();
	panel = null;
	markButtons();
	const back = [...document.querySelectorAll('[data-info]')].find((b) => b.dataset.info === key);
	back?.focus({ preventScroll: true });
}

/** Whether the panel is open, and on what. */
export function infoShowing() {
	return shown?.key ?? null;
}

/**
 * Draws the open panel again from what its topic says now. Called by whoever
 * rebuilds the (i) buttons, after rebuilding them: the topic may have changed
 * with the model.
 */
export function refreshInfo() {
	if (!shown) return;
	paint();
	markButtons();
}

/** A topic, from itself or from the function that makes it. */
function resolve(topic) {
	try {
		return typeof topic === 'function' ? topic() : topic;
	} catch {
		return null;
	}
}

/** The (i) itself: a ring and a letter, in the button's own colour. */
function glyph() {
	const ns = 'http://www.w3.org/2000/svg';
	const svg = document.createElementNS(ns, 'svg');
	svg.setAttribute('viewBox', '0 0 16 16');
	svg.setAttribute('width', '13');
	svg.setAttribute('height', '13');
	svg.setAttribute('aria-hidden', 'true');
	const ring = document.createElementNS(ns, 'circle');
	ring.setAttribute('cx', '8');
	ring.setAttribute('cy', '8');
	ring.setAttribute('r', '6.9');
	ring.setAttribute('fill', 'none');
	ring.setAttribute('stroke', 'currentColor');
	ring.setAttribute('stroke-width', '1.3');
	const dot = document.createElementNS(ns, 'circle');
	dot.setAttribute('cx', '8');
	dot.setAttribute('cy', '4.7');
	dot.setAttribute('r', '1');
	dot.setAttribute('fill', 'currentColor');
	const stem = document.createElementNS(ns, 'rect');
	stem.setAttribute('x', '7.25');
	stem.setAttribute('y', '6.8');
	stem.setAttribute('width', '1.5');
	stem.setAttribute('height', '5.2');
	stem.setAttribute('rx', '0.75');
	stem.setAttribute('fill', 'currentColor');
	svg.append(ring, dot, stem);
	return svg;
}

/** Every (i) on the page says whether it is the one open. */
function markButtons() {
	for (const b of document.querySelectorAll('[data-info]')) {
		const on = shown?.key === b.dataset.info;
		b.classList.toggle('is-open', on);
		b.setAttribute('aria-expanded', String(on));
	}
}

/** Builds the panel, or refills the one that is open. */
function paint(host = document.body) {
	const topic = resolve(topics.get(shown.key));
	if (!topic) return;
	if (panel && !panel.isConnected) panel = null;
	if (!panel) {
		const close = el('button', {
			type: 'button', className: 'ghost info-panel-close', 'aria-label': 'Close',
		}, '×');
		close.addEventListener('click', closeInfo);
		panel = el('aside', {
			id: 'info-panel', className: 'info-panel', role: 'complementary',
			'aria-labelledby': 'info-panel-title',
		},
		el('div', { className: 'info-panel-head' },
			el('div', { className: 'info-panel-heading' },
				el('div', { className: 'info-panel-kicker' }),
				el('h2', { className: 'info-panel-title', id: 'info-panel-title' })),
			close),
		el('div', { className: 'info-panel-body', tabIndex: -1 }));
		// Escape from inside the panel closes the panel and nothing else: in a
		// dialog, the key would otherwise close the dialog around it.
		panel.addEventListener('keydown', (ev) => {
			if (ev.key !== 'Escape') return;
			ev.preventDefault();
			ev.stopPropagation();
			closeInfo();
		});
		host.append(panel);
		if (host.tagName === 'DIALOG') {
			panel.classList.add('in-dialog');
			// Gone with the dialog, and said to be gone.
			host.addEventListener('close', () => {
				if (panel && host.contains(panel)) {
					panel = null;
					shown = null;
					markButtons();
				}
			}, { once: true });
		}
		place();
	}
	panel.querySelector('.info-panel-kicker').textContent = topic.kicker ?? '';
	panel.querySelector('.info-panel-title').textContent = topic.title ?? '';
	const body = panel.querySelector('.info-panel-body');
	const top = body.scrollTop;
	const same = body.dataset.key === shown.key;
	body.replaceChildren(...contents(topic));
	body.dataset.key = shown.key;
	// Kept where it was when the same topic is drawn again after an edit;
	// back to the top for a new one.
	body.scrollTop = same ? top : 0;
}

/** The panel's contents, from the topic's data. */
function contents(topic) {
	const out = [];
	const more = () => {
		if (!topic.more || !follow) return null;
		const b = el('button', { type: 'button', className: 'info-panel-more' },
			'Read more in Help: ', el('b', {}, topic.more), ' \u2192');
		b.addEventListener('click', () => { const heading = topic.more; closeInfo(); follow(heading); });
		return el('p', { className: 'info-panel-more-line' }, b);
	};
	for (const p of paragraphs(topic.lead)) out.push(el('p', { className: 'info-lead' }, ...inline(p)));
	if (topic.facts?.length) {
		const dl = el('dl', { className: 'info-facts' });
		for (const [label, value] of topic.facts) {
			if (value == null || value === '') continue;
			dl.append(el('dt', {}, label), el('dd', {}, ...inline(String(value))));
		}
		out.push(dl);
	}
	for (const s of topic.sections ?? []) {
		if (s.heading) out.push(el('h3', {}, s.heading));
		for (const p of paragraphs(s.text)) out.push(el('p', {}, ...inline(p)));
		if (s.list?.length) out.push(el('ul', {}, ...s.list.map((item) => el('li', {}, ...inline(item)))));
		if (s.choices?.length) {
			out.push(el('dl', { className: 'info-choices' }, ...s.choices.flatMap(([name, what, on]) => [
				el('dt', { className: on ? 'is-current' : '' }, ...inline(name),
					on ? el('span', { className: 'info-current' }, 'chosen') : null),
				el('dd', {}, ...inline(what ?? '')),
			])));
		}
	}
	const link = more();
	if (link) out.push(link);
	return out;
}

const paragraphs = (text) => (Array.isArray(text) ? text : text ? [text] : []);

/**
 * A string with `code` and **emphasis** in it, as nodes. Nothing else is
 * markup: a `<` in a topic is a `<`.
 */
export function inline(text) {
	const nodes = [];
	const re = /`([^`]+)`|\*\*([^*]+)\*\*/g;
	let at = 0;
	for (let m = re.exec(text); m; m = re.exec(text)) {
		if (m.index > at) nodes.push(document.createTextNode(text.slice(at, m.index)));
		nodes.push(m[1] != null ? el('code', {}, m[1]) : el('b', {}, m[2]));
		at = re.lastIndex;
	}
	if (at < text.length) nodes.push(document.createTextNode(text.slice(at)));
	return nodes;
}

/**
 * Between the header and the footer, whatever height those are: read from
 * them rather than written into the stylesheet, since the header wraps on a
 * narrow window.
 */
function place() {
	if (!panel) return;
	const dialog = panel.parentElement?.tagName === 'DIALOG' ? panel.parentElement : null;
	if (dialog) {
		// Over the window, with a margin all round: the page's header and
		// footer are under the dialog's backdrop and mean nothing here. Beside
		// the dialog when there is room for a readable panel, so neither
		// covers the other; over its right-hand edge when there is not.
		// The room is what lies right of the dialog less the panel's own 12px
		// margin to the window's edge and a 12px gap to the dialog. Over the
		// dialog, the panel starts under its title bar, so that the (i) that
		// opened it and the x that closes the dialog are not buried under it
		// -- but never so far down that the panel is a sliver.
		const r = dialog.getBoundingClientRect();
		const room = window.innerWidth - r.right - 24;
		const beside = room >= 300;
		const head = dialog.querySelector('.modal-head')?.getBoundingClientRect();
		const top = beside || !head ? 12 : Math.round(Math.min(head.bottom + 6, window.innerHeight * 0.4));
		panel.style.top = `${Math.max(12, top)}px`;
		panel.style.bottom = '12px';
		panel.style.width = beside ? `${Math.round(Math.min(400, room))}px` : '';
		return;
	}
	const top = document.querySelector('header')?.getBoundingClientRect().bottom ?? 0;
	const foot = document.querySelector('footer')?.getBoundingClientRect().top ?? window.innerHeight;
	panel.style.top = `${Math.max(0, Math.round(top))}px`;
	panel.style.bottom = `${Math.max(0, Math.round(window.innerHeight - foot))}px`;
}

/** Escape and resizing, installed once for the page. */
let installed = false;
function installClosers() {
	if (installed) return;
	installed = true;
	document.addEventListener('keydown', (ev) => {
		if (ev.key !== 'Escape' || !shown || ev.defaultPrevented) return;
		// A dialog on top has the key: Escape closes the thing in front.
		if (document.querySelector('dialog[open]')) return;
		// Only from the panel, its (i), or nowhere in particular: Escape in a
		// text box puts its value back and in the tree clears the selection,
		// and taking the key from them would close a panel nobody was
		// looking at.
		const at = document.activeElement;
		if (at && at !== document.body && !panel?.contains(at) && !at.closest?.('[data-info]')) return;
		ev.preventDefault();
		closeInfo();
	});
	window.addEventListener('resize', place);
}
