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
 * A collapsible panel section.
 *
 * The badge is what a closed section says about itself -- the time span and
 * solver, how many parameters, how many index combinations are set. A header
 * that says only "Simulation" makes you open it to learn anything. It is
 * hidden once the section is open, where the contents say more.
 *
 * @param {{id?: string, title: string, badge?: string, badgeTitle?: string,
 *          open?: boolean, onToggle?: (open: boolean) => void}} opts
 * @returns {HTMLDetailsElement} append the body to it
 */
export function section({
	id = '', title, badge = '', badgeTitle = '', open = true, onToggle = null, info = null,
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
		// see ./infopanel.js. Its click is its own and does not fold the
		// section.
		info));
	return box;
}
