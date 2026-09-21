/**
 * Drawing a block's symbol, in the two places a label can live.
 *
 * The parse is in ../domain/symbol.js; this turns runs into elements. Two
 * renderers because the diagram is SVG, where `<sup>` does not exist: a
 * superscript there is a `<tspan>` lifted off the baseline and set smaller.
 */

import { symbolRuns, symbolText, displayName } from '../domain/symbol.js';

const NS = 'http://www.w3.org/2000/svg';

/** The symbol as HTML nodes, for a panel or a list. */
export function symbolNodes(text) {
	return symbolRuns(text).map((run) => {
		let node = document.createTextNode(run.text);
		const wrap = (tag) => {
			const e = document.createElement(tag);
			e.append(node);
			node = e;
		};
		if (run.italic) wrap('i');
		if (run.bold) wrap('b');
		if (run.sup) wrap('sup');
		if (run.sub) wrap('sub');
		return node;
	});
}

/** Fills an element with a block's on-screen name. */
export function setSymbol(host, block) {
	host.replaceChildren(...symbolNodes(displayName(block)));
	return host;
}

/**
 * The same, as tspans inside an SVG `<text>`.
 *
 * `dy` is cumulative in SVG, so a run that goes back to the baseline has to
 * undo the shift the one before it made -- without that, two superscripts in a
 * row climb off the top of the box.
 */
export function symbolTspans(text, { size = 1 } = {}) {
	const runs = symbolRuns(text);
	const out = [];
	let shift = 0;
	for (const run of runs) {
		const want = run.sup ? -0.36 : run.sub ? 0.22 : 0;
		const t = document.createElementNS(NS, 'tspan');
		t.textContent = run.text;
		if (want !== shift) t.setAttribute('dy', `${(want - shift) * size}em`);
		if (want !== 0) t.setAttribute('font-size', '0.72em');
		if (run.bold) t.setAttribute('font-weight', '700');
		if (run.italic) t.setAttribute('font-style', 'italic');
		out.push(t);
		shift = want;
	}
	// Back to the baseline at the end, so anything following this text -- a
	// second line, another label -- starts where it should.
	if (shift !== 0 && out.length) {
		const t = document.createElementNS(NS, 'tspan');
		t.textContent = '';
		t.setAttribute('dy', `${-shift * size}em`);
		out.push(t);
	}
	return out;
}

export { symbolText, displayName };
