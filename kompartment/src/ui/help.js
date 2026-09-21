/**
 * The Help tab: this project's own documentation, read inside the application.
 *
 * The files on disk rather than a copy written into the interface. `GUIDE.md`
 * is the user guide -- what the thing does, and how to work it; `INTERNALS.md`
 * says how it does it. Both answer questions
 * that come up while a model is open -- what a lookup table's `cyclic` flag
 * does, which solver to reach for, why a transfer's unit cannot be typed in --
 * and answering them meant leaving for a text editor.
 *
 * Fetched, not bundled: a copy pasted in here would be a second description of
 * the same behaviour, and the two would drift within a week.
 *
 * **The measure is the reader's to set.** Prose wants about 70 characters a
 * line and a reference table wants the whole window, and the same document is
 * both. So the width is a control rather than a constant, remembered between
 * visits, with the widest setting standing the contents down to give its
 * column back.
 */

import { renderMarkdown, outline } from './markdown.js';
import { el } from './parts.js';

/** The documents on offer, in the order they are useful. */
export const DOCS = [
	{ id: 'guide', file: 'GUIDE.md', title: 'Guide', blurb: 'What it does, and how to work it' },
	{
		id: 'internals',
		file: 'INTERNALS.md',
		title: 'How it works',
		blurb: 'The machinery behind it, and why it is arranged this way',
	},
];

/**
 * How wide the text may run, in order.
 *
 * `ch` rather than pixels because the thing being measured is characters per
 * line; `none` is the one that means "use the window", and takes the contents
 * column with it so the gain is the full 230 pixels rather than half of it.
 */
export const WIDTHS = [
	{ id: 'narrow', label: 'Narrow', measure: '62ch', title: 'About 62 characters a line' },
	{ id: 'normal', label: 'Normal', measure: '78ch', title: 'About 78 characters a line' },
	{ id: 'wide', label: 'Wide', measure: '104ch', title: 'About 104 characters a line' },
	{ id: 'full', label: 'Full', measure: 'none', title: 'The whole window, contents hidden' },
];

const WIDTH_KEY = 'boxflow.help.width';

/** The remembered measure, or the middle one. Storage may be unavailable. */
function savedWidth() {
	try {
		const id = localStorage.getItem(WIDTH_KEY);
		return WIDTHS.find((w) => w.id === id) ?? WIDTHS[1];
	} catch { return WIDTHS[1]; }
}

function rememberWidth(id) {
	try { localStorage.setItem(WIDTH_KEY, id); } catch { /* private window */ }
}

/**
 * Puts the chosen measure on the panel.
 *
 * A custom property rather than a style on the article, so the stylesheet
 * keeps the rule and this keeps the number -- and so the `is-full` class can
 * fold the contents away in the same pass.
 */
function applyWidth(host, width) {
	host.style.setProperty('--help-measure', width.measure);
	host.classList.toggle('is-full', width.id === 'full');
}

/** Fetched once each; the files do not change while the page is open. */
const cache = new Map();

async function load(doc) {
	if (cache.has(doc.id)) return cache.get(doc.id);
	const text = await (await fetch(doc.file)).text();
	cache.set(doc.id, text);
	return text;
}

/** Which document is showing, how wide, and where in it, across visits. */
const state = { doc: DOCS[0].id, at: new Map(), width: null };

/**
 * @param {HTMLElement} host
 */
export function renderHelp(host) {
	const doc = DOCS.find((d) => d.id === state.doc) ?? DOCS[0];
	// Read from storage once per session, then kept in memory: the setting is
	// changed far more often than the tab is opened.
	if (!state.width) state.width = savedWidth();
	applyWidth(host, state.width);

	// Rebuilt only when the document changes: coming back to the tab should
	// find the page where it was left, not at the top again. The panel is
	// hidden with `display: none` between visits, which loses the scroll
	// offset, so it is put back from what the last scroll recorded.
	if (host.dataset.doc === doc.id) {
		const shown = host.querySelector('.help-doc');
		if (shown && state.at.has(doc.id)) shown.scrollTop = state.at.get(doc.id);
		return;
	}
	host.dataset.doc = doc.id;
	host.replaceChildren();

	const picker = el('div', { className: 'help-picker' });
	for (const d of DOCS) {
		const b = el('button', {
			className: `search-chip${d.id === doc.id ? ' is-on' : ''}`,
			type: 'button', title: d.blurb,
		}, d.title);
		b.addEventListener('click', () => { state.doc = d.id; renderHelp(host); });
		picker.append(b);
	}

	// The measure. A group rather than a menu because there are four of them
	// and the one in force has to be visible without opening anything.
	const widths = el('div', { className: 'help-widths', role: 'group', 'aria-label': 'Text width' });
	for (const w of WIDTHS) {
		const b = el('button', {
			className: `search-chip${w.id === state.width.id ? ' is-on' : ''}`,
			type: 'button', title: w.title, 'aria-pressed': String(w.id === state.width.id),
		}, w.label);
		b.addEventListener('click', () => {
			state.width = w;
			rememberWidth(w.id);
			applyWidth(host, w);
			for (const other of widths.children) {
				const on = other === b;
				other.classList.toggle('is-on', on);
				other.setAttribute('aria-pressed', String(on));
			}
		});
		widths.append(b);
	}

	const toc = el('nav', { className: 'help-toc', 'aria-label': `${doc.title} contents` });
	const body = el('article', { className: 'help-doc' });
	host.append(el('div', { className: 'help-head' }, picker,
		el('span', { className: 'hint help-blurb' }, doc.blurb),
		el('span', { className: 'help-spacer' }),
		el('span', { className: 'hint help-width-label' }, 'Width'), widths));
	host.append(el('div', { className: 'help-split' }, toc, body));

	body.append(el('p', { className: 'hint' }, `Reading ${doc.file}…`));

	load(doc).then((text) => {
		if (host.dataset.doc !== doc.id) return; // switched away while it loaded
		body.replaceChildren(renderMarkdown(text));

		// The heading elements are found once. Looking each of two dozen up by
		// id on every scroll event is a query storm for an answer that cannot
		// change while the document is on screen.
		const marks = [];
		for (const entry of outline(text)) {
			const heading = body.querySelector(`#${CSS.escape(entry.id)}`);
			const link = el('button', {
				className: `help-link help-level-${entry.level}`, type: 'button',
			}, entry.text);
			// Instant, not smooth: gliding through a thousand lines to reach a
			// heading is slower than arriving at it.
			link.addEventListener('click', () => heading?.scrollIntoView({ block: 'start' }));
			marks.push({ link, heading });
			toc.append(link);
		}

		// The heading you are reading is marked in the contents, which on a
		// document this long is the difference between a list and a map.
		const mark = () => {
			const top = body.getBoundingClientRect().top;
			let current = null;
			for (const { link, heading } of marks) {
				if (heading && heading.getBoundingClientRect().top - top <= 12) current = link;
			}
			for (const { link } of marks) link.classList.toggle('is-here', link === current);
			state.at.set(doc.id, body.scrollTop);
		};
		body.addEventListener('scroll', mark, { passive: true });
		body.scrollTop = state.at.get(doc.id) ?? 0;
		mark();
	}).catch((e) => {
		if (host.dataset.doc !== doc.id) return;
		body.replaceChildren(el('p', { className: 'hint' },
			`${doc.file} could not be read (${e.message}). `
			+ 'It is read from the folder this page is served from, so a page '
			+ 'opened straight off the disk cannot fetch it — serve the folder '
			+ 'instead: python3 serve.py'));
	});
}

/** Opens the tab at a particular heading, for a link from elsewhere. */
export function goToHelp(host, docId, headingId) {
	state.doc = DOCS.some((d) => d.id === docId) ? docId : DOCS[0].id;
	// A different document means a rebuild; the same one is already there.
	if (host.dataset.doc !== state.doc) renderHelp(host);
	if (!headingId) return;
	const find = () => host.querySelector(`.help-doc #${CSS.escape(headingId)}`);
	const jump = find();
	if (jump) jump.scrollIntoView({ block: 'start' });
	else setTimeout(() => find()?.scrollIntoView({ block: 'start' }), 300);
}
