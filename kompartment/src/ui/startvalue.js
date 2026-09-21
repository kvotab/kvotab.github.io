/**
 * An equation's value at the start of the run, said in one line.
 *
 * The line goes under the box the equation was typed into, which is the only
 * place it answers the question people actually have: you have written
 * `Total_inventory * Leaching_fraction` and you want to know what that *is*.
 *
 * Two things decide the wording. A block in a real model is rarely one number
 * -- across the imported corpus the median block carries 39 of them, one per
 * nuclide or per region, and the largest carries 1,134 -- so the line has to
 * say what a column of numbers would say without being one. And a model that
 * divides by a compartment starting at zero legitimately *has* an infinity in
 * it at the start; half the corpus does somewhere. Saying so is the point, so
 * nothing here hides one.
 */

import { fmtTime as fmtNumber } from './summary.js';

/** How many index values a tooltip lists before it starts counting instead. */
const LISTED = 12;

const word = (v) => {
	// Only a real infinity is called one. Anything else that is not a finite
	// number -- undefined from a short array, a null out of a half-written
	// file -- is not a number, and saying "minus infinity" about it would be
	// the most confident wrong answer available.
	if (v === Infinity) return 'infinite';
	if (v === -Infinity) return 'minus infinity';
	return 'not a number';
};

/** `53 indices`, which is what a block of that shape has one value for. */
const count = (n) => `${n} ${n === 1 ? 'index' : 'indices'}`;

/** One value, with its unit when it has one. */
const one = (v, unit) => (Number.isFinite(v)
	? `${fmtNumber(v)}${unit ? ` ${unit}` : ''}`
	: word(v));

/**
 * The line for one equation's values.
 *
 * @param {{label: string, unit: string, value: number}[]} values one per index
 * @returns {{text: string, title: string}|null} null when there is nothing to
 *   say -- no values at all, which is not the same as a value of nothing
 */
export function startValueLine(values) {
	if (!values?.length) return null;
	const finite = values.filter((v) => Number.isFinite(v.value));
	const odd = values.length - finite.length;
	const unit = values[0].unit ?? '';
	const sameUnit = values.every((v) => (v.unit ?? '') === unit);
	const suffix = sameUnit ? unit : '';

	let text;
	if (values.length === 1) {
		text = one(values[0].value, suffix);
	} else if (!finite.length) {
		// Every one of them is strange, and how strange is the whole story.
		const kinds = new Set(values.map((v) => word(v.value)));
		// Which kinds of strange, not just that they are strange: a column of
		// infinities and a column of NaNs are two different mistakes.
		text = `${[...kinds].join(' or ')} at all ${count(values.length)}`;
	} else {
		// Not `Math.min(...)`: one argument per index, and a block indexed by
		// two lists of four hundred has 160,000 of them, which is past the
		// point where V8 throws `RangeError: Maximum call stack size
		// exceeded` -- from inside a render, where nothing catches it.
		let lo = Infinity;
		let hi = -Infinity;
		for (const v of finite) {
			if (v.value < lo) lo = v.value;
			if (v.value > hi) hi = v.value;
		}
		text = lo === hi
			? `${one(lo, suffix)} at all ${count(values.length)}`
			: `${one(lo, suffix)} to ${one(hi, suffix)} over ${count(values.length)}`;
		// Counted, not buried: one infinity among sixty numbers is the one
		// worth knowing about, and a range would say nothing about it.
		if (odd) {
			const kinds = new Set(values.filter((v) => !Number.isFinite(v.value))
				.map((v) => word(v.value)));
			text += ` — ${odd} ${kinds.size === 1 ? [...kinds][0] : 'not numbers'}`;
		}
	}

	const listed = values.slice(0, LISTED)
		.map((v) => `${v.label} = ${one(v.value, v.unit ?? '')}`);
	if (values.length > LISTED) listed.push(`… and ${values.length - LISTED} more`);
	// No leading `=`: in the settings dialog the line reads as an answer to the
	// box above it and the stylesheet writes one, while in the Information
	// view it sits beside a label that has already said what it is.
	return { text, title: listed.join('\n') };
}

/**
 * The same values in the fewest characters: for a column that has to share a
 * row with a name and an equation box, as the left panel's rows do.
 *
 * One value is the number; several that agree are the number; a spread is
 * `lo–hi`; and what is not a number is named, since one infinity is the one
 * value worth a glance. No unit and no count -- both are a hover away, in the
 * title, which carries the full line and the values by index.
 *
 * @returns {{text: string, title: string}|null}
 */
export function startValueBrief(values) {
	const line = startValueLine(values);
	if (!line) return null;
	const finite = values.filter((v) => Number.isFinite(v.value));
	let text;
	if (!finite.length) {
		text = values.length === 1 ? word(values[0].value) : `${word(values[0].value)}…`;
	} else {
		let lo = Infinity;
		let hi = -Infinity;
		for (const v of finite) {
			if (v.value < lo) lo = v.value;
			if (v.value > hi) hi = v.value;
		}
		text = lo === hi ? fmtNumber(lo) : `${fmtNumber(lo)}–${fmtNumber(hi)}`;
		if (finite.length < values.length) text += ' !';
	}
	return { text, title: `${line.text}\n${line.title}` };
}

/**
 * Marks an element as showing one equation's value, so that it can be filled
 * in later without rebuilding the panel around it.
 *
 * Working the values out means building the whole model, which is twenty
 * milliseconds on an ordinary one and over a second on a landscape model, so
 * it happens after the edit rather than during it. Re-rendering the settings
 * dialog when the answer arrives would take the focus out of whatever box was
 * being typed into; writing the one line in place does not.
 */
export function markStartValue(node, name, key = null, index = null) {
	// A space separates the two because neither a qualified name nor a property
	// name can contain one; `-` stands for the block's own value, which is not
	// a property of it.
	node.dataset.startvalue = `${name} ${key ?? '-'}`;
	// One index of it, for a cell in a grid or a row in a list. Joined on a
	// unit separator rather than on anything readable, because an index name
	// is whatever the model calls it and two of them joined by a space would
	// be one name that happened to have a space in it.
	if (index) node.dataset.startvalueAt = index.join(AT_SEP);
	return node;
}

const AT_SEP = '\u001f';

/**
 * Writes one marked node from the values it is about.
 *
 * Separate from `fillStartValues` because a list that is built while the
 * values are already known should not wait for the next round of filling to
 * say anything -- the rows a `load more` button adds, most of all.
 */
export function refreshStartValue(node, values) {
	const at = node.dataset.startvalueAt;
	// `data-startvalue-brief` asks for the short form: a row's worth, not a
	// line's.
	const say = node.dataset.startvalueBrief === undefined ? startValueLine : startValueBrief;
	const line = say(at === undefined
		? values
		: (values ?? []).filter((v) => (v.index ?? []).join(AT_SEP) === at));
	node.textContent = line ? line.text : '';
	node.title = line ? line.title : '';
	// A line under an equation box hides itself; a row that is nothing but
	// this value has to take its label with it, and says so by carrying
	// `data-startvalue-row` on the row.
	(node.closest('[data-startvalue-row]') ?? node).hidden = !line;
	return node;
}

/**
 * Fills in every marked line under `root` from `lookup(name, key)`.
 *
 * @param {(name: string, key: string) => object|null} lookup values for one
 *   equation, in `startValueLine`'s shape
 */
export function fillStartValues(root, lookup) {
	// Asked once per block and field rather than once per node: a grid of
	// fifty-three nuclides is fifty-three cells about one equation.
	const got = new Map();
	for (const node of root.querySelectorAll('[data-startvalue]')) {
		const mark = node.dataset.startvalue;
		if (!got.has(mark)) {
			const [name, key] = mark.split(' ');
			got.set(mark, lookup(name, key === '-' ? null : key));
		}
		refreshStartValue(node, got.get(mark));
	}
}
