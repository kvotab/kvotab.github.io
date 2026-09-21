/**
 * A block's symbol: what it is called on screen, as opposed to what it is
 * called in an equation.
 *
 * A name has to be an identifier -- it is what equations refer to -- and that
 * rules out the notation this domain is actually written in: `<sup>14</sup>C`,
 * `k<sub>d</sub>`, plain text otherwise. So the symbol is written out as
 * markup rather than kept as a letter per corner of the block, which is the
 * other way to hold it and cannot say `K<sub>d,f</sub>`.
 *
 * The same four tags are understood in GUIDE.md and INTERNALS.md, so a
 * reference table there draws its symbols instead of printing their tags --
 * see `inlineRuns` in ../ui/markdown.js.
 *
 * Parsed into runs rather than handed to `innerHTML`. The text comes out of a
 * project file, which is a thing people send each other, and a label is not a
 * place to execute what arrives.
 */

/** The tags a symbol may use, and what each one means to a renderer. */
const TAGS = new Map(Object.entries({
	sup: 'sup', sub: 'sub', b: 'bold', strong: 'bold', i: 'italic', em: 'italic',
}));

/** So a caller can say what is allowed without repeating the list. */
export const SYMBOL_TAGS = ['sup', 'sub', 'b', 'i'];

/**
 * A symbol as a flat list of runs.
 *
 * Each run is a piece of text and the marks that apply to it, so a renderer
 * can build one element per run and nothing else. Unknown tags, and stray
 * angle brackets, are text: a symbol that will not parse is still shown, just
 * shown literally.
 *
 * @param {string} text
 * @returns {Array<{text: string, sup?: boolean, sub?: boolean, bold?: boolean,
 *   italic?: boolean}>}
 */
export function symbolRuns(text) {
	const src = String(text ?? '');
	// Every label on the diagram and in the tree is parsed on every render,
	// and re-parsing the same dozen strings sixty times a second is work for
	// nothing. The cache is bounded and holds only short strings, and the
	// array is copied out so a caller cannot edit the next caller's answer.
	const hit = CACHE.get(src);
	if (hit) return hit.slice();

	const runs = parseRuns(src);
	if (src.length <= CACHE_TEXT) {
		if (CACHE.size >= CACHE_MAX) CACHE.clear();
		CACHE.set(src, runs);
		return runs.slice();
	}
	return runs;
}

/** The cache behind `symbolRuns`: short strings only, cleared when it fills. */
const CACHE = new Map();
const CACHE_MAX = 2048;
const CACHE_TEXT = 256;

/**
 * How long a string is still treated as a symbol.
 *
 * Finding a tag's closing partner means scanning forward from it, so a string
 * that is nothing but opening tags costs one scan each and the whole parse
 * goes quadratic. A symbol is a label -- two or three characters with a corner
 * on them -- and nothing anybody writes comes near this. Past it the text is
 * shown literally, which is what an unparseable symbol does anyway.
 */
const MAX_SYMBOL = 2000;

/** One opening tag, matched in place rather than against a copy of the rest. */
const OPEN = /<([a-zA-Z]+)>/y;

/** `</sup>`, `</SUB >` -- one regex per tag name, built once. */
const CLOSERS = new Map();
const closerFor = (tag) => {
	let re = CLOSERS.get(tag);
	if (!re) {
		re = new RegExp(`</${tag}\\s*>`, 'gi');
		CLOSERS.set(tag, re);
	}
	return re;
};

/**
 * The parse itself, iterative and allocation-free.
 *
 * `marks` is the tags open at this point and `ends` where each one's content
 * stops, so a nested tag needs no recursion and no substring: the text is
 * walked once and a run is emitted whenever the set of marks changes. A tag
 * whose partner lies outside its parent's content is not a partner at all --
 * which is what the recursive version did too, by only ever searching inside
 * the piece it had been handed.
 */
function parseRuns(src) {
	const out = [];
	if (!src) return out;
	if (src.length > MAX_SYMBOL) return [{ text: src }];

	const marks = [];
	const ends = [];
	let plain = '';
	const flush = () => {
		if (!plain) return;
		const run = { text: plain };
		for (const mark of marks) run[mark] = true;
		out.push(run);
		plain = '';
	};

	let i = 0;
	while (i < src.length) {
		const open = ends.length ? ends[ends.length - 1] : null;
		if (open && i === open.at) {
			flush();
			i = open.after;
			ends.pop();
			marks.pop();
			continue;
		}
		if (src[i] === '<') {
			OPEN.lastIndex = i;
			const m = OPEN.exec(src);
			const mark = m && TAGS.get(m[1].toLowerCase());
			if (mark) {
				const from = OPEN.lastIndex;
				const close = closerFor(m[1].toLowerCase());
				close.lastIndex = from;
				const c = close.exec(src);
				const after = c ? c.index + c[0].length : -1;
				// Marks nest: `<sup><b>x</b></sup>` is both.
				if (c && after <= (open ? open.at : src.length)) {
					flush();
					marks.push(mark);
					ends.push({ at: c.index, after });
					i = from;
					continue;
				}
			}
		}
		plain += src[i];
		i++;
	}
	// Whatever is still open ran past the end of the text, so its opening tag
	// was never a tag. The runs already emitted inside it keep their marks --
	// the same thing the recursive version did with an unclosed tag deeper in.
	flush();
	return out;
}

/** The symbol with its markup taken off: what it reads as, for a title or a CSV. */
export function symbolText(text) {
	return symbolRuns(text).map((r) => r.text).join('');
}

/**
 * What to call a block on screen.
 *
 * Its symbol when it has one, and its name otherwise. Only ever a label:
 * equations, references, the tree's search and the project file all use the
 * name, because that is the block's identity.
 */
export function displayName(block) {
	const symbol = String(block?.symbol ?? '').trim();
	return symbol || String(block?.name ?? '');
}

/** True when a block is shown under something other than its own name. */
export function hasSymbol(block) {
	return !!String(block?.symbol ?? '').trim();
}
