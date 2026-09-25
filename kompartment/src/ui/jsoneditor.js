/**
 * The JSON tab's box: the project file, coloured as it is read and checked as
 * it is typed.
 *
 * THE COLOURING. A textarea cannot colour its own text, so the coloured copy is
 * a <pre> underneath it and the textarea's own text is made transparent over
 * it -- the way facsimile.html and rtm.html colour their model text, and for
 * their reason: native editing stays whole (undo, selection, the caret, paste)
 * where a contenteditable would not.
 *
 * Unlike theirs, only the lines in view are coloured. A model's file runs to
 * tens of thousands of lines, and a copy of all of them -- a span a line, laid
 * out a second time under the first -- doubled what the tab already costs to
 * open. The lines in view are a hundred at most, whatever the file, so the
 * copy is redrawn from scratch on every scroll and keystroke and costs the
 * same at any size. That puts one demand on the layout: line k of the text
 * has to be at k line-heights exactly, in both boxes, which a fractional line
 * height does not give -- the browser rounds each line box to its own
 * sub-pixel grid and the error adds up to tens of pixels by line ten
 * thousand. So both boxes use `LINE`, a whole number of pixels, and the same
 * padding (`PAD`), and css/app.css declares the two together.
 *
 * THE CHECK. After a pause in typing the text is parsed, and handed to
 * `validate` -- whatever Apply would refuse. What is wrong is said under the
 * toolbar with the line and column, and Apply waits until it is put right.
 * Browsers disagree on whether a JSON error says where it is (Safari's does
 * not, and V8's newer messages often do not), so where the text will not parse
 * its own scan (`jsonErrorAt`) finds the place and says what is wrong there in
 * words -- the same in every browser.
 */

import { el } from './parts.js';

/** The line height both boxes share, in whole pixels: see above. */
export const LINE = 18;
/** Their padding, in pixels. */
export const PAD = 10;

const SYNTAX_KEY = 'kompartment.jsonSyntax';

/** Whether the text is coloured: this browser's choice, on unless it said off. */
export function syntaxOn() {
	try { return localStorage.getItem(SYNTAX_KEY) !== 'off'; } catch { return true; }
}

function keepSyntax(on) {
	try { localStorage.setItem(SYNTAX_KEY, on ? 'on' : 'off'); } catch { /* a convenience */ }
}

// --- colouring ------------------------------------------------------------

// Whitespace, a string (closed or not: a line being typed is coloured as far
// as it goes), a number, a literal, punctuation, and anything else -- which
// in JSON is a mistake, and is left uncoloured for the check to name.
const TOKEN = /(\s+)|("(?:[^"\\]|\\.)*(?:"|\\?$))|(-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)|(true|false|null)(?![\w$])|([{}[\],:])|([^\s"{}[\],:]+)/g;

/** One line of the text as `[class, text]` pairs, the class null for text left as it is. */
export function tokenise(line) {
	const out = [];
	TOKEN.lastIndex = 0;
	let m;
	while ((m = TOKEN.exec(line)) !== null) {
		if (m[0] === '') { TOKEN.lastIndex += 1; continue; }
		if (m[1] !== undefined || m[6] !== undefined) { out.push([null, m[0]]); continue; }
		let cls = 'jh-punct';
		if (m[2] !== undefined) {
			// A string followed by a colon names a property.
			cls = /^\s*:/.test(line.slice(TOKEN.lastIndex)) ? 'jh-key' : 'jh-str';
		} else if (m[3] !== undefined) cls = 'jh-num';
		else if (m[4] !== undefined) cls = 'jh-lit';
		out.push([cls, m[0]]);
	}
	return out;
}

/** One line as coloured nodes, built rather than written as HTML: it came out of a file. */
function colourLine(line) {
	return tokenise(line).map(([cls, text]) => (cls
		? el('span', { className: cls }, text)
		: document.createTextNode(text)));
}

// --- the check --------------------------------------------------------------

/** A character, as the check's message names it. */
function describe(c) {
	if (c === undefined) return 'the end of the text';
	if (c === '\n' || c === '\r') return 'a line break';
	if (c === '\t') return 'a tab';
	return `‘${c}’`;
}

/**
 * Where the text stops being JSON, and what is wrong there: `{at, reason}`,
 * or null when it is JSON after all.
 *
 * A scan of the grammar that builds nothing, run only on text JSON.parse has
 * already refused -- so it is there to say where, and in words a person
 * editing a model reads: a comma after the last item, a property name without
 * its quotes, a string left open. Depth is bounded by the stack, which a model
 * file comes nowhere near; a text that does gets the browser's own message.
 */
export function jsonErrorAt(text) {
	const n = text.length;
	let i = 0;
	const fail = (reason, at = i) => { throw { at, reason }; };
	const ws = () => {
		while (i < n) {
			const c = text.charCodeAt(i);
			if (c === 32 || c === 9 || c === 10 || c === 13) i += 1;
			else break;
		}
	};
	const NUMBER = /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y;
	const string = () => {
		const start = i;
		i += 1;
		while (i < n) {
			const c = text[i];
			if (c === '"') { i += 1; return; }
			if (c === '\\') {
				const e = text[i + 1];
				if (e === 'u') {
					if (!/^[0-9a-fA-F]{4}$/.test(text.slice(i + 2, i + 6))) fail('\\u has to be followed by four hexadecimal digits');
					i += 6;
				} else if (e !== undefined && '"\\/bfnrt'.includes(e)) {
					i += 2;
				} else {
					fail(`${describe(e)} cannot follow a backslash in a string; write \\\\ for a backslash`);
				}
				continue;
			}
			if (text.charCodeAt(i) < 0x20) fail(c === '\n' ? 'a string runs past the end of its line: it is not closed with a double quote' : 'a control character inside a string; write it with a backslash');
			i += 1;
		}
		fail('a string is not closed with a double quote', start);
	};
	const value = () => {
		ws();
		const c = text[i];
		if (c === '{') return object();
		if (c === '[') return array();
		if (c === '"') return string();
		if (c === '-' || (c >= '0' && c <= '9')) {
			NUMBER.lastIndex = i;
			const m = NUMBER.exec(text);
			if (!m || !m[0] || m[0] === '-') fail('not a number: a number is digits, with an optional point and exponent');
			i += m[0].length;
			if (/[\d.eE]/.test(text[i] ?? '')) fail('not a number: a number is digits, with an optional point and exponent');
			return undefined;
		}
		for (const word of ['true', 'false', 'null']) {
			if (text.startsWith(word, i)) { i += word.length; return undefined; }
		}
		if (c === '\'') fail('strings are written in double quotes in JSON, not single');
		if (c === ']' || c === '}') fail(`${describe(c)} where a value was expected: a comma too many, or a value missing`);
		return fail(c === undefined ? 'the text ends where a value was expected' : `${describe(c)} where a value was expected`);
	};
	// Where the last comma was: a comma after the last item is the comma's
	// fault, and the caret belongs on it rather than on the bracket after it
	// -- which, in a file laid out a line an item, is a line further down.
	let comma = -1;
	const object = () => {
		i += 1;
		ws();
		if (text[i] === '}') { i += 1; return; }
		for (;;) {
			ws();
			const c = text[i];
			if (c === '}') fail('a comma after the last property: JSON allows none', comma);
			if (c !== '"') {
				fail(c === undefined ? 'the text ends inside an object: a closing brace is missing'
					: c === '\'' ? 'property names are written in double quotes in JSON, not single'
						: /[A-Za-z_$]/.test(c) ? 'a property name has to be in double quotes'
							: `${describe(c)} where a property name in double quotes was expected`);
			}
			string();
			ws();
			if (text[i] !== ':') fail(`${describe(text[i])} where a colon was expected, after the property name`);
			i += 1;
			value();
			ws();
			if (text[i] === ',') { comma = i; i += 1; continue; }
			if (text[i] === '}') { i += 1; return; }
			fail(text[i] === undefined ? 'the text ends inside an object: a closing brace is missing'
				: text[i] === '"' ? 'a comma is missing between two properties'
					: `${describe(text[i])} where a comma or a closing brace was expected`);
		}
	};
	const array = () => {
		i += 1;
		ws();
		if (text[i] === ']') { i += 1; return; }
		for (;;) {
			value();
			ws();
			if (text[i] === ',') {
				comma = i;
				i += 1;
				ws();
				if (text[i] === ']') fail('a comma after the last item: JSON allows none', comma);
				continue;
			}
			if (text[i] === ']') { i += 1; return; }
			fail(text[i] === undefined ? 'the text ends inside a list: a closing bracket is missing'
				: /["{[\d-]/.test(text[i]) ? 'a comma is missing between two items'
					: `${describe(text[i])} where a comma or a closing bracket was expected`);
		}
	};
	try {
		ws();
		if (i >= n) fail('the text is empty; a model is one JSON object');
		value();
		ws();
		if (i < n) fail(`${describe(text[i])} after the end of the model: the text should end with its closing brace`);
		return null;
	} catch (e) {
		if (e && typeof e.at === 'number') return e;
		return null;
	}
}

/** The line and column, both from 1, of an offset into `text`. */
export function lineColumn(text, at) {
	let line = 1;
	let from = 0;
	for (let k = text.indexOf('\n'); k >= 0 && k < at; k = text.indexOf('\n', k + 1)) {
		line += 1;
		from = k + 1;
	}
	return { line, column: at - from + 1 };
}

/**
 * What is wrong with `text` as a model, or null when nothing is.
 *
 * `{kind: 'syntax', line, column, at, reason}` where it is not JSON;
 * `{kind: 'model', reason, block}` where it is, and `validate` refuses it.
 */
export function checkText(text, validate) {
	let parsed;
	try {
		parsed = JSON.parse(text);
	} catch (e) {
		const where = jsonErrorAt(text);
		if (where) return { kind: 'syntax', ...lineColumn(text, where.at), at: where.at, reason: where.reason };
		return { kind: 'syntax', line: null, column: null, at: null, reason: e.message };
	}
	if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
		return { kind: 'model', reason: 'a model is one JSON object, in braces', block: null };
	}
	try {
		validate?.(parsed);
	} catch (e) {
		return { kind: 'model', reason: e.message, block: e.blockName ?? null };
	}
	return null;
}

// --- the box ------------------------------------------------------------------

/**
 * Wires the box: the colouring, the check, and Apply's state.
 *
 * @param {object} o
 * @param {HTMLTextAreaElement} o.ta
 * @param {HTMLElement} o.box        holds the two
 * @param {HTMLElement} o.hl         the coloured copy, a <pre> with a <code>
 * @param {HTMLInputElement} o.toggle the checkbox
 * @param {HTMLElement} o.status     the line under the toolbar
 * @param {HTMLButtonElement} o.apply
 * @param {() => string|null} o.baseline  the text of the model as it stands
 * @param {(parsed: object) => void} o.validate  throws what Apply would refuse
 * @returns {{reset: Function, dirty: () => boolean, problem: () => object|null}}
 */
export function wireJsonEditor({ ta, box, hl, toggle, status, apply, baseline, validate }) {
	const code = hl.querySelector('code') ?? hl.appendChild(document.createElement('code'));
	let on = syntaxOn();
	let lines = null;
	let problem = null;
	// An edit the check has not read yet: nothing is claimed about it until it has.
	let pending = false;
	let painting = 0;
	let checking = null;

	const paint = () => {
		painting = 0;
		if (!on || ta.hidden) { code.replaceChildren(); return; }
		lines ??= ta.value.split('\n');
		const top = ta.scrollTop;
		// From a couple of lines above the view to a few below it: enough that
		// a scroll step shows no gap before the next frame fills it.
		const first = Math.max(0, Math.floor((top - PAD) / LINE) - 2);
		const last = Math.min(lines.length, first + Math.ceil(ta.clientHeight / LINE) + 5);
		const bad = problem?.kind === 'syntax' && problem.line ? problem.line - 1 : -1;
		const frag = document.createDocumentFragment();
		for (let k = first; k < last; k++) {
			const row = el('span', { className: k === bad ? 'jh-line is-bad' : 'jh-line' }, ...colourLine(lines[k]), '\n');
			frag.append(row);
		}
		code.replaceChildren(frag);
		code.style.transform = `translate(${-ta.scrollLeft}px, ${first * LINE - top}px)`;
	};
	const repaint = () => { if (!painting) painting = requestAnimationFrame(paint); };

	const dirty = () => !ta.hidden && baseline() !== null && ta.value !== baseline();

	/** Apply, and the line under the toolbar, from what is known now. */
	const show = () => {
		const changed = dirty();
		apply.disabled = !changed || !!problem;
		apply.title = ta.hidden ? 'The project file is not shown, so there is nothing to apply'
			: !changed ? 'Nothing to apply: the text is the model as it stands. Edit it first.'
				: problem ? 'Put right what is said under the toolbar first'
					: 'Use the edited text as the model';
		status.replaceChildren();
		status.className = 'json-check';
		if (!changed) { status.hidden = true; return; }
		status.hidden = false;
		if (!problem) {
			status.classList.add('is-ok');
			status.append(pending ? 'Edited. ' : 'Edited, and it reads as a model. ', el('b', {}, 'Apply'), ' to use it.');
			return;
		}
		status.classList.add('is-bad');
		const p = problem;
		if (p.kind === 'syntax') {
			status.append(el('b', {}, p.line ? `Not JSON at line ${p.line}, column ${p.column}: ` : 'Not JSON: '),
				p.reason, '.');
			if (p.at != null) {
				const go = el('button', { type: 'button', className: 'ghost json-go' }, 'Show me');
				go.addEventListener('click', () => {
					ta.focus();
					// A caret, never a selection: a selected span is replaced by
					// the next key pressed, and this is somebody's model.
					ta.setSelectionRange(p.at, p.at);
					const want = (p.line - 1) * LINE;
					if (want < ta.scrollTop || want > ta.scrollTop + ta.clientHeight - 2 * LINE) {
						ta.scrollTop = Math.max(0, want - ta.clientHeight / 3);
					}
					repaint();
				});
				status.append(' ', go);
			}
		} else {
			// The block, where the message does not already name it.
			const block = p.block && !p.reason.includes(p.block) ? ` (${p.block})` : '';
			status.append(el('b', {}, 'Not a model this tool can read: '), p.reason + block,
				/[.!?]$/.test(p.reason + block) ? '' : '.');
		}
	};

	const check = () => {
		checking = null;
		pending = false;
		problem = dirty() ? checkText(ta.value, validate) : null;
		show();
		repaint();
	};
	// Longer for a larger file: the check reads the whole of it, and a model
	// of a few megabytes is a noticeable pause to spend between keystrokes.
	const soon = () => {
		clearTimeout(checking);
		checking = setTimeout(check, ta.value.length > 1e6 ? 900 : 300);
	};

	ta.addEventListener('input', () => {
		lines = null;
		// Apply is offered the moment the text differs; the check that may
		// take it back again comes after the pause.
		if (problem && !dirty()) problem = null;
		pending = dirty();
		show();
		repaint();
		soon();
	});
	ta.addEventListener('scroll', repaint, { passive: true });
	new ResizeObserver(repaint).observe(ta);

	const setOn = (next) => {
		on = next;
		toggle.checked = on;
		box.classList.toggle('is-coloured', on);
		repaint();
	};
	toggle.addEventListener('change', () => { setOn(toggle.checked); keepSyntax(on); });
	setOn(on);

	return {
		/** The text was just written from the model: nothing edited, nothing wrong. */
		reset() {
			clearTimeout(checking);
			checking = null;
			lines = null;
			problem = null;
			pending = false;
			show();
			repaint();
		},
		dirty,
		problem: () => problem,
	};
}
