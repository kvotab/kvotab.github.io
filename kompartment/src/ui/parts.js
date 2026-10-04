/**
 * Pieces both side panels are built from.
 *
 * The left panel and the inspector rail are different views over the same
 * model, and a control that looks and behaves differently in each is a small
 * tax on everyone who uses both. So the collapsible section lives here, once,
 * and each panel supplies only what it cannot share: the open state, which the
 * left panel keeps in the application state and the rail keeps per section
 * across selections.
 */

/**
 * One DOM element, with properties and children: the helper every panel is
 * built from. Here, once -- it used to be pasted into fifteen files, byte for
 * byte, and a fix to it would have been fifteen fixes.
 */
export const el = (tag, props = {}, ...kids) => {
	// A hyphenated name is an *attribute*, not a property: `aria-label` and
	// `aria-hidden` assigned through `Object.assign` land as plain JS fields
	// on the element and reach neither the accessibility tree nor the
	// stylesheet. Nineteen of them across the panels said nothing at all --
	// including the accessible name of every value box in the left panel,
	// which is the one place a screen reader has to be told what a field is,
	// since the name beside it is a label that deliberately labels nothing.
	const attrs = {};
	for (const k of Object.keys(props)) {
		if (k.includes('-')) attrs[k] = props[k];
	}
	const n = Object.assign(document.createElement(tag), props);
	for (const [k, v] of Object.entries(attrs)) {
		delete n[k];
		if (v == null || v === false) n.removeAttribute(k);
		else n.setAttribute(k, v === true ? '' : String(v));
	}
	for (const k of kids.flat()) {
		if (k == null || k === false) continue;
		n.append(k.nodeType ? k : document.createTextNode(String(k)));
	}
	return n;
};

/**
 * Controls on a heading's line -- a section's (i), the Information card's
 * buttons -- that are not in its <summary>. A button inside one is a control
 * inside a control, which keyboards and screen readers do not all reach, and
 * Chrome reports each one in the console ("An interactive element was found
 * within a <summary> element"). Nor can they go after the <summary> inside
 * the <details>, which shows nothing else while it is shut. So they go in a
 * bar before the <details>, in a frame holding the two, and the summary keeps
 * a room where they stood (`toolsRoom`): the bar is drawn over it and the
 * room is kept as big as the bar, so the summary lays out as it did and the
 * controls are where they were. The frame is what goes into the panel
 * (`frameOf`); the body still goes into the <details>.
 */
const frames = new WeakMap();		// the <details> -> { frame, bar, room }
const followed = new Map();			// the frame -> its parts, while it is in the page
const resized = typeof ResizeObserver === 'function'
	? new ResizeObserver((entries) => {
		for (const e of entries) fitTools(e.target.closest('.panel-frame'));
	})
	: null;

/** The room a summary keeps for its controls, laid out where they were. */
export const toolsRoom = () => el('span', { className: 'panel-tools-room', 'aria-hidden': 'true' });

/** The <details>, its summary holding a `toolsRoom`, in a frame with a bar of `controls` before it. */
export function framed(box, ...controls) {
	const bar = el('span', { className: 'panel-tools' }, ...controls);
	const frame = el('div', { className: 'panel-frame' }, bar, box);
	const summary = box.querySelector(':scope > summary');
	const room = summary?.querySelector('.panel-tools-room') ?? null;
	frames.set(box, { frame, bar, room });
	if (room) {
		followed.set(frame, { bar, summary, room, seen: false });
		if (resized) {
			resized.observe(bar);
			resized.observe(summary);
		}
	}
	return frame;
}

/** What goes into the panel for a section: its frame, or the section itself. */
export const frameOf = (box) => frames.get(box)?.frame ?? box;
/** The bar a section's heading controls go in, or null. */
export const toolsOf = (box) => frames.get(box)?.bar ?? null;
/** The room its summary keeps for them, or null. */
export const roomOf = (box) => frames.get(box)?.room ?? null;

/* The room as big as the bar, and the bar where the room is. Fitted again
   whenever either changes size; hidden while the summary is. */
function fitTools(frame) {
	const f = frame && followed.get(frame);
	if (!f) return;
	if (!frame.isConnected) {
		// Out of the page after being in it -- the panels are rebuilt on every
		// edit -- or not yet in it, when the observer calls again on its layout.
		if (f.seen) {
			resized?.unobserve(f.bar);
			resized?.unobserve(f.summary);
			followed.delete(frame);
		}
		return;
	}
	f.seen = true;
	const shown = f.summary.getClientRects().length > 0;
	f.bar.hidden = !shown;
	if (!shown) return;
	// To the fraction of a pixel: offsetWidth rounds, and a room pushed to
	// the right-hand end would start half a pixel away from the controls.
	const size = f.bar.getBoundingClientRect();
	f.room.style.width = `${size.width}px`;
	f.room.style.height = `${size.height}px`;
	const b = frame.getBoundingClientRect();
	const r = f.room.getBoundingClientRect();
	f.bar.style.left = `${r.left - b.left - frame.clientLeft}px`;
	f.bar.style.top = `${r.top - b.top - frame.clientTop}px`;
}

/**
 * A collapsible panel section.
 *
 * The badge is what a closed section says about itself -- the time span and
 * solver, how many parameters, how many index combinations are set. A header
 * that says only "Simulation" makes you open it to learn anything. It is
 * hidden once the section is open, where the contents say more.
 *
 * With an (i), or `tools` for the Information card's buttons, the section is
 * framed (see `framed`): the panel takes `frameOf(box)`.
 *
 * @param {{id?: string, title: string, badge?: string, badgeTitle?: string,
 *          open?: boolean, onToggle?: (open: boolean) => void,
 *          info?: HTMLElement, tools?: boolean}} opts
 * @returns {HTMLDetailsElement} append the body to it
 */
export function section({
	id = '', title, badge = '', badgeTitle = '', open = true, onToggle = null, info = null, tools = false,
}) {
	const box = el('details', { className: 'panel-section', open: !!open });
	if (id) box.dataset.section = id;
	// Setting `open` at construction queues a toggle event of its own, and
	// reporting that as a choice would overwrite the caller's rule with
	// whatever it happened to render first -- a section that opens only when
	// it has something in it would stay open for every block after the first.
	// Only a change away from the state we set is a real toggle.
	let known = !!open;
	if (onToggle) {
		box.addEventListener('toggle', () => {
			if (box.open === known) return;
			known = box.open;
			onToggle(box.open);
		});
	}
	box.append(el('summary', {},
		el('span', { className: 'panel-section-title' }, title),
		badge
			? el('span', { className: 'panel-section-badge', title: badgeTitle }, badge)
			: null,
		// What the section holds, behind an (i) at the end of the heading:
		// see ./infopanel.js. Drawn over the room kept for it here rather
		// than in the summary (see `framed`), so its click is its own and
		// does not fold the section.
		info || tools ? toolsRoom() : null));
	if (info || tools) framed(box, info);
	return box;
}
