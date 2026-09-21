/**
 * Just enough Markdown to read this project's own documentation.
 *
 * The help panel shows `GUIDE.md` as it is on disk rather than a copy of it
 * written into the interface, so there is one description of how the thing
 * works instead of two that drift apart. That means reading Markdown, and
 * only the Markdown those files actually contain: headings, paragraphs,
 * fenced code, bullet and numbered lists, tables, and inline emphasis, code
 * and links. No images, no block quotes, no HTML.
 *
 * Split in two on purpose. `parseMarkdown` is a pure function from text to
 * blocks, so it can be tested without a browser; `renderMarkdown` turns those
 * blocks into elements. Elements, never `innerHTML`: the text comes from a
 * file fetched at runtime, and building nodes means nothing in it can become
 * markup by accident.
 */

import { el } from './parts.js';
import { renderFigure } from './helpfigures.js';

/** `The project format` -> `the-project-format`, for a link to jump to. */
export function slug(text) {
	return String(text).toLowerCase()
		.replace(/[^a-z0-9]+/g, '-')
		.replace(/^-+|-+$/g, '') || 'section';
}

/**
 * Text to blocks.
 *
 * @returns {Array<object>} one of
 *   `{type: 'heading', level, text, id}`
 *   `{type: 'paragraph', text}`
 *   `{type: 'code', text, language}`
 *   `{type: 'list', ordered, items: string[]}`
 *   `{type: 'table', head: string[], rows: string[][]}`
 *   `{type: 'quote', text}`
 */
export function parseMarkdown(source) {
	const lines = String(source ?? '').split('\n');
	const out = [];
	const seen = new Map();
	let at = 0;

	/** Headings share names across two documents, so ids are made unique. */
	const idFor = (text) => {
		const base = slug(text);
		const n = (seen.get(base) ?? 0) + 1;
		seen.set(base, n);
		return n === 1 ? base : `${base}-${n}`;
	};

	const cells = (row) => row
		.replace(/^\s*\|/, '')
		.replace(/\|\s*$/, '')
		.split('|')
		.map((c) => c.trim());

	/** A bar line is a table only when a rule follows it; otherwise it is text. */
	const startsTable = (i) => !!lines[i]?.trim().startsWith('|')
		&& /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1] ?? '');

	while (at < lines.length) {
		const line = lines[at];

		if (!line.trim()) { at++; continue; }

		const heading = /^(#{1,6})\s+(.*)$/.exec(line);
		if (heading) {
			const text = heading[2].trim();
			out.push({ type: 'heading', level: heading[1].length, text, id: idFor(text) });
			at++;
			continue;
		}

		if (line.startsWith('```')) {
			const language = line.slice(3).trim();
			const body = [];
			at++;
			while (at < lines.length && !lines[at].startsWith('```')) body.push(lines[at++]);
			at++; // the closing fence, or the end of the file
			out.push({ type: 'code', text: body.join('\n'), language });
			continue;
		}

		// A table is a header row, a rule, and its body. Without the rule it is
		// just text that happens to contain bars, and falls through to the
		// paragraph below rather than disappearing.
		if (startsTable(at)) {
			const head = cells(line);
			at += 2;
			const rows = [];
			while (at < lines.length && lines[at].trim().startsWith('|')) rows.push(cells(lines[at++]));
			out.push({ type: 'table', head, rows });
			continue;
		}

		const bullet = /^(\s*)([-*])\s+(.*)$/.exec(line);
		const number = /^(\s*)(\d+)\.\s+(.*)$/.exec(line);
		if (bullet || number) {
			const ordered = !!number;
			const items = [];
			while (at < lines.length) {
				const m = ordered
					? /^(\s*)(\d+)\.\s+(.*)$/.exec(lines[at])
					: /^(\s*)([-*])\s+(.*)$/.exec(lines[at]);
				if (m) {
					items.push(m[3].trim());
					at++;
					continue;
				}
				// An indented line under an item continues it; a blank line
				// followed by another item does not end the list.
				if (/^\s+\S/.test(lines[at]) && items.length) {
					items[items.length - 1] += ` ${lines[at].trim()}`;
					at++;
					continue;
				}
				if (!lines[at].trim() && /^\s*([-*]|\d+\.)\s/.test(lines[at + 1] ?? '')) {
					at++;
					continue;
				}
				break;
			}
			out.push({ type: 'list', ordered, items });
			continue;
		}

		// A quotation. These documents quote other texts,
		// and without this the marker is read out loud as an angle bracket at
		// the start of the paragraph. Hard-wrapped like a paragraph, and one
		// paragraph long -- a `>` line on its own ends it rather than starting
		// a second, which is all the quoting these two files do.
		if (/^\s*>/.test(line)) {
			const said = [];
			while (at < lines.length && /^\s*>\s?\S/.test(lines[at])) {
				said.push(lines[at++].replace(/^\s*>\s?/, '').trim());
			}
			if (said.length) { out.push({ type: 'quote', text: said.join(' ') }); continue; }
			at++;
			continue;
		}

		// A paragraph runs to the next blank line or block opener.
		const text = [];
		while (at < lines.length && lines[at].trim()
			&& !/^(#{1,6}\s|```)/.test(lines[at])
			&& !/^\s*>/.test(lines[at])
			&& !/^\s*([-*]|\d+\.)\s/.test(lines[at])
			&& !startsTable(at)) {
			text.push(lines[at++].trim());
		}
		// Hard-wrapped in the source, so the lines rejoin into one paragraph.
		if (text.length) out.push({ type: 'paragraph', text: text.join(' ') });
		else at++;
	}
	return out;
}

/** The headings, for a table of contents. */
export function outline(source) {
	return parseMarkdown(source)
		.filter((b) => b.type === 'heading' && b.level >= 2 && b.level <= 3)
		.map(({ level, text, id }) => ({ level, text, id }));
}

/**
 * Inline emphasis, code and links, as a flat list of runs.
 *
 * Scanned rather than matched with one alternation, because precedence here is
 * positional: a backtick opens a code span whatever is around it, so the `*`
 * in `` `donor * rate` `` is an asterisk and not the start of emphasis. With a
 * single pattern the bold in "**Transfer flux is `donor * rate`.**" failed --
 * its content held an asterisk -- and the italic alternative then matched
 * across it and mangled the rest of the line.
 *
 * Emphasis nests: its content is scanned again and the flag added to whatever
 * comes back, so `**bold with `code` in it**` is bold *and* code rather than a
 * bold run with backticks left in it.
 *
 * The four tags a block's symbol may use are understood here too, and for the
 * same reason: this domain is written in notation plain text cannot hold, and
 * `T<sub>w</sub>` in a reference table has to *draw* as T with a subscript
 * rather than print its own tags. Only those four, only with a partner that
 * closes them, and never inside a code span -- so the line of the guide that
 * documents the notation, which writes it in backticks, still shows it.
 *
 * @returns {Array<{text: string, code?: boolean, strong?: boolean,
 *   em?: boolean, sub?: boolean, sup?: boolean, href?: string}>}
 */
/** The symbol notation's tags, and the run flag each one sets. */
const TAG_FLAG = { sub: 'sub', sup: 'sup', b: 'strong', i: 'em' };

const OPEN_TAG = /^<(sub|sup|b|i)>/i;

/**
 * The content of an open tag, up to the partner that closes *it*.
 *
 * Depth-counted rather than taking the first closing tag of that name, so
 * `<sub>a<sub>b</sub>c</sub>` ends where it should. Null where there is no
 * partner at all, which leaves the opening tag as the literal text it is.
 */
function tagged(src, from, tag) {
	const scan = new RegExp(`<(/?)${tag}>`, 'gi');
	scan.lastIndex = from;
	let depth = 1;
	for (let m = scan.exec(src); m; m = scan.exec(src)) {
		depth += m[1] ? -1 : 1;
		if (!depth) return { text: src.slice(from, m.index), after: scan.lastIndex };
	}
	return null;
}

export function inlineRuns(text) {
	const src = String(text ?? '');
	const out = [];
	let plain = '';
	const flush = () => {
		if (plain) out.push({ text: plain });
		plain = '';
	};
	// The content of emphasis is a line in its own right.
	const nested = (inner, flag) => {
		flush();
		for (const run of inlineRuns(inner)) out.push({ ...run, [flag]: true });
	};

	let i = 0;
	while (i < src.length) {
		const rest = src.slice(i);

		if (src[i] === '`') {
			const end = src.indexOf('`', i + 1);
			if (end > i + 1) {
				flush();
				out.push({ text: src.slice(i + 1, end), code: true });
				i = end + 1;
				continue;
			}
		}
		if (src[i] === '<') {
			const m = OPEN_TAG.exec(rest);
			const inner = m ? tagged(src, i + m[0].length, m[1].toLowerCase()) : null;
			if (inner) {
				nested(inner.text, TAG_FLAG[m[1].toLowerCase()]);
				i = inner.after;
				continue;
			}
		}
		if (src[i] === '[') {
			const m = /^\[([^\]]+)\]\(([^)\s]+)\)/.exec(rest);
			if (m) {
				flush();
				out.push({ text: m[1], href: m[2] });
				i += m[0].length;
				continue;
			}
		}
		if (src[i] === '*' && src[i + 1] === '*') {
			const end = src.indexOf('**', i + 2);
			if (end > i + 1) {
				nested(src.slice(i + 2, end), 'strong');
				i = end + 2;
				continue;
			}
		}
		if (src[i] === '*') {
			const m = /^\*([^*\n]+)\*/.exec(rest);
			if (m) {
				nested(m[1], 'em');
				i += m[0].length;
				continue;
			}
		}
		plain += src[i];
		i++;
	}
	flush();
	return out;
}

function inline(text) {
	return inlineRuns(text).map((run) => {
		let node;
		if (run.code) node = el('code', {}, run.text);
		else if (run.href) {
			// Only a real URL becomes a link. A relative path in these files
			// points at the source tree, which is not somewhere this can go.
			node = /^https?:\/\//.test(run.href)
				? el('a', { href: run.href, target: '_blank', rel: 'noreferrer' }, run.text)
				: el('code', {}, run.text);
		} else node = document.createTextNode(run.text);
		// Innermost first: a subscript inside bold is bold, and the bold has to
		// be the outer element or the baseline shift applies to the wrong run.
		if (run.sub) node = el('sub', {}, node);
		if (run.sup) node = el('sup', {}, node);
		// Emphasis wraps whatever is inside it, so code can be bold.
		if (run.em) node = el('em', {}, node);
		if (run.strong) node = el('strong', {}, node);
		return node;
	});
}

/** @returns {DocumentFragment} */
export function renderMarkdown(source) {
	const frag = document.createDocumentFragment();
	for (const block of parseMarkdown(source)) {
		if (block.type === 'heading') {
			const h = el(`h${Math.min(block.level, 6)}`, { id: block.id }, ...inline(block.text));
			frag.append(h);
		} else if (block.type === 'paragraph') {
			frag.append(el('p', {}, ...inline(block.text)));
		} else if (block.type === 'quote') {
			frag.append(el('blockquote', { className: 'md-quote' }, ...inline(block.text)));
		} else if (block.type === 'code') {
			// ```figure <name> is a drawing, with the fence body as its sketch
			// for anything that cannot draw. An unknown name falls through to
			// the sketch rather than disappearing, so a typo is visible.
			const named = /^figure\s+(\S+)/.exec(block.language ?? '');
			const drawn = named ? renderFigure(named[1], block.text) : null;
			if (drawn) frag.append(drawn);
			else frag.append(el('pre', { className: 'md-code' }, el('code', {}, block.text)));
		} else if (block.type === 'list') {
			const list = el(block.ordered ? 'ol' : 'ul', { className: 'md-list' });
			for (const item of block.items) list.append(el('li', {}, ...inline(item)));
			frag.append(list);
		} else if (block.type === 'table') {
			const table = el('table', { className: 'md-table' });
			table.append(el('thead', {}, el('tr', {},
				...block.head.map((c) => el('th', {}, ...inline(c))))));
			const body = el('tbody');
			for (const row of block.rows) {
				body.append(el('tr', {}, ...row.map((c) => el('td', {}, ...inline(c)))));
			}
			table.append(body);
			// Wide tables scroll on their own rather than stretching the page.
			frag.append(el('div', { className: 'md-scroll' }, table));
		}
	}
	return frag;
}
