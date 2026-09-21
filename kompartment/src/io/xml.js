/**
 * A small XML parser.
 *
 * Browsers have DOMParser and Node does not, and this project has no
 * dependencies, so the importer brings its own. It handles the subset that
 * Ecolego's writers actually emit -- elements, attributes, text, CDATA,
 * comments, the XML declaration and the five predefined entities -- and
 * nothing else. No namespaces, no DTDs, no entity declarations.
 *
 * Nodes are plain objects:
 *   { name, attrs: {..}, children: [node..], text: '<concatenated text>' }
 */

export class XMLError extends Error {
	constructor(message, position) {
		super(position != null ? `${message} (at character ${position})` : message);
		this.name = 'XMLError';
		this.position = position ?? null;
	}
}

// Null prototype: the name between `&` and `;` comes out of the file, and on a
// plain object `ENTITIES.constructor` is a function -- so `&constructor;` in a
// block's comment would have been replaced by the source of `Object`.
const ENTITIES = Object.assign(Object.create(null), {
	amp: '&', lt: '<', gt: '>', quot: '"', apos: "'",
});

// What ends a tag or attribute name. Hoisted: `readName` used to build this
// literal afresh for every character it looked at, which is every character
// of every name in the document.
const NAME_END = /[\s/>=]/;

export function decodeEntities(s) {
	if (!s.includes('&')) return s;
	return s.replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z]+);/g, (whole, body) => {
		if (body[0] === '#') {
			const code = body[1] === 'x' || body[1] === 'X'
				? parseInt(body.slice(2), 16)
				: parseInt(body.slice(1), 10);
			// `String.fromCodePoint` throws a RangeError for anything that is
			// not a code point -- above U+10FFFF, or a surrogate half -- and a
			// file is entitled to contain nonsense. `&#1114112;` in one
			// comment killed the whole import with a message from deep inside
			// the string library; left as written, it is a comment that reads
			// oddly and nothing more.
			if (!Number.isInteger(code) || code < 0 || code > 0x10ffff) return whole;
			if (code >= 0xd800 && code <= 0xdfff) return whole;
			return String.fromCodePoint(code);
		}
		return ENTITIES[body] ?? whole;
	});
}

/**
 * @param {string} src
 * @returns {object} the root element node
 */
export function parseXML(src) {
	let i = 0;
	const n = src.length;

	const stack = [];
	let root = null;

	const fail = (msg) => { throw new XMLError(msg, i); };

	const skipSpace = () => {
		while (i < n && (src[i] === ' ' || src[i] === '\t' || src[i] === '\n' || src[i] === '\r')) i++;
	};

	const readName = () => {
		const start = i;
		while (i < n && !NAME_END.test(src[i])) i++;
		if (i === start) fail('Expected a name');
		return src.slice(start, i);
	};

	const addText = (raw) => {
		if (!stack.length) return;
		const parent = stack[stack.length - 1];
		parent.text += raw;
	};

	while (i < n) {
		const lt = src.indexOf('<', i);

		if (lt === -1) {
			addText(decodeEntities(src.slice(i)));
			break;
		}
		if (lt > i) addText(decodeEntities(src.slice(i, lt)));
		i = lt;

		// <!-- comment -->
		if (src.startsWith('<!--', i)) {
			const end = src.indexOf('-->', i + 4);
			if (end === -1) fail('Unterminated comment');
			i = end + 3;
			continue;
		}

		// <![CDATA[ ... ]]>  -- verbatim, no entity decoding
		if (src.startsWith('<![CDATA[', i)) {
			const end = src.indexOf(']]>', i + 9);
			if (end === -1) fail('Unterminated CDATA section');
			addText(src.slice(i + 9, end));
			i = end + 3;
			continue;
		}

		// <?xml ... ?>  and  <!DOCTYPE ...>
		if (src.startsWith('<?', i)) {
			const end = src.indexOf('?>', i + 2);
			if (end === -1) fail('Unterminated processing instruction');
			i = end + 2;
			continue;
		}
		if (src.startsWith('<!', i)) {
			const end = src.indexOf('>', i + 2);
			if (end === -1) fail('Unterminated declaration');
			i = end + 1;
			continue;
		}

		// </name>
		if (src.startsWith('</', i)) {
			i += 2;
			const name = readName();
			skipSpace();
			if (src[i] !== '>') fail(`Expected '>' closing </${name}`);
			i++;
			const open = stack.pop();
			if (!open) fail(`Unexpected closing tag </${name}>`);
			if (open.name !== name) {
				throw new XMLError(
					`Closing tag </${name}> does not match <${open.name}>`, i,
				);
			}
			continue;
		}

		// <name attr="value" ...>  or  <name .../>
		i++;
		const name = readName();
		// The attribute map has no prototype, for the same reason ENTITIES has
		// none: its keys are whatever the file wrote between `<name` and `>`,
		// and `attrs.constructor` on a plain object is a function.
		const node = { name, attrs: Object.create(null), children: [], text: '' };

		for (;;) {
			skipSpace();
			if (i >= n) fail('Unterminated tag');
			if (src[i] === '>') { i++; break; }
			if (src.startsWith('/>', i)) {
				i += 2;
				node.selfClosing = true;
				break;
			}
			const attrName = readName();
			skipSpace();
			if (src[i] !== '=') fail(`Expected '=' after attribute '${attrName}'`);
			i++;
			skipSpace();
			const quote = src[i];
			if (quote !== '"' && quote !== "'") {
				fail(`Expected a quoted value for attribute '${attrName}'`);
			}
			i++;
			const end = src.indexOf(quote, i);
			if (end === -1) fail(`Unterminated value for attribute '${attrName}'`);
			node.attrs[attrName] = decodeEntities(src.slice(i, end));
			i = end + 1;
		}

		if (stack.length) {
			stack[stack.length - 1].children.push(node);
		} else if (root) {
			fail('More than one root element');
		} else {
			root = node;
		}
		if (!node.selfClosing) stack.push(node);
	}

	if (stack.length) {
		throw new XMLError(`Unclosed element <${stack[stack.length - 1].name}>`);
	}
	if (!root) throw new XMLError('The document has no elements');
	return root;
}

// --- convenience accessors -------------------------------------------------

/** First direct child with the given name, or null. */
export function child(node, name) {
	if (!node) return null;
	return node.children.find((c) => c.name === name) ?? null;
}

/** All direct children with the given name. */
export function children(node, name) {
	if (!node) return [];
	return node.children.filter((c) => c.name === name);
}

/** Text of a direct child, trimmed, or a fallback. */
export function childText(node, name, fallback = null) {
	const c = child(node, name);
	if (!c) return fallback;
	const t = c.text.trim();
	return t === '' ? fallback : t;
}

export function childNumber(node, name, fallback = null) {
	const t = childText(node, name);
	if (t == null) return fallback;
	const v = Number(t);
	return Number.isFinite(v) ? v : fallback;
}

export function childBool(node, name, fallback = null) {
	const t = childText(node, name);
	if (t == null) return fallback;
	return t.toLowerCase() === 'true';
}

/**
 * Depth-first walk over every element.
 *
 * Iterative, with its own stack. `yield* walk(c)` recursed once per level of
 * nesting *and* once per level for every value yielded through it, so five
 * thousand nested elements -- a few tens of kilobytes of XML, well inside what
 * a file can carry -- overflowed the call stack. The parser itself has always
 * been iterative; this was the half that was not, and `find` below is what
 * `eco.js` reads a document with.
 */
export function* walk(node) {
	const stack = [node];
	while (stack.length) {
		const el = stack.pop();
		yield el;
		// Pushed in reverse so siblings come out in document order.
		const kids = el.children;
		for (let i = kids.length - 1; i >= 0; i--) stack.push(kids[i]);
	}
}

/** First element anywhere under `node` with the given name. */
export function find(node, name) {
	for (const el of walk(node)) {
		if (el.name === name) return el;
	}
	return null;
}
