/**
 * The house rules, checked.
 *
 * This project has no build step and no dependencies, so it has no ESLint
 * either. What it has instead is a handful of rules that are specific to it,
 * that have each been broken at least once, and that are cheap to check by
 * reading the source as text:
 *
 *   1. No markup from strings.      Every element is built with `el()`.
 *   2. No swallowed errors.         A `catch` with nothing in it says nothing.
 *   3. No stray `console`.          Except behind a debug flag.
 *   4. No undeclared editor state.  Every `state.x = ...` in app.js names a
 *                                   field the `state` literal declares.
 *   5. No unused imports.           An import list that describes the module.
 *
 * Rule 4 is the one with a scar. `state.prob` was created by assignment and
 * never appeared in the literal, so the reset list in `setModel` -- which was
 * written by reading that literal -- never learned about it, and a
 * probabilistic run outlived the model it was a run of: its bands were drawn
 * under the next model's lines, and its realisations were written into the
 * next model's export. A rule that a field must be declared before it is
 * assigned is the cheapest thing that would have caught it.
 *
 *     node test/lint.js          # on its own
 *     npm run lint
 *
 * and `test/run.js` runs the text rules too, so they cannot rot.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, relative } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

/** Every `.js` under a directory, depth first. */
export function sources(dir = join(ROOT, 'src')) {
	const out = [];
	for (const name of readdirSync(dir).sort()) {
		const full = join(dir, name);
		if (statSync(full).isDirectory()) out.push(...sources(full));
		else if (name.endsWith('.js')) out.push(full);
	}
	return out;
}

/** The line a character offset falls on, counting from 1. */
function lineAt(text, at) {
	let line = 1;
	for (let i = 0; i < at && i < text.length; i++) if (text[i] === '\n') line++;
	return line;
}

/**
 * Comments and string literals, blanked out.
 *
 * Every rule here is about *code*, and this file is written by people who
 * explain themselves at length -- so `innerHTML` in a comment saying why there
 * is no `innerHTML` must not be a finding. Blanked rather than removed, so
 * offsets still point at the right line.
 */
export function code(text) {
	const out = text.split('');
	let i = 0;
	const blank = (from, to) => {
		for (let k = from; k < to && k < out.length; k++) if (out[k] !== '\n') out[k] = ' ';
	};
	while (i < text.length) {
		const c = text[i];
		const next = text[i + 1];
		if (c === '/' && next === '/') {
			const end = text.indexOf('\n', i);
			blank(i, end < 0 ? text.length : end);
			i = end < 0 ? text.length : end;
			continue;
		}
		if (c === '/' && next === '*') {
			const end = text.indexOf('*/', i + 2);
			blank(i, end < 0 ? text.length : end + 2);
			i = end < 0 ? text.length : end + 2;
			continue;
		}
		if (c === '"' || c === "'" || c === '`') {
			let k = i + 1;
			while (k < text.length) {
				if (text[k] === '\\') { k += 2; continue; }
				if (text[k] === c) break;
				k++;
			}
			blank(i + 1, k);
			i = k + 1;
			continue;
		}
		i++;
	}
	return out.join('');
}

const RULES = [
	{
		name: 'no-markup-from-strings',
		why: 'Every element is built with `el()`; a model file must have no way '
			+ 'to become markup.',
		find: /\.(innerHTML|outerHTML)\s*=|\.insertAdjacentHTML\(|document\.write\(/g,
	},
	{
		name: 'no-empty-catch',
		why: 'A `catch` with nothing in it swallows the reason. Say why it is '
			+ 'safe to ignore, even if the body stays empty.',
		// `catch {}` and `catch (e) {}` with nothing but space between braces.
		// Read from the *raw* text, not the blanked copy: a comment in the body
		// is exactly what this rule is asking for, and blanking it out would
		// turn every well-explained one into a finding.
		raw: true,
		find: /catch\s*(\([^)]*\))?\s*\{\s*\}/g,
	},
	{
		name: 'no-stray-console',
		why: 'Left-over logging. Put it behind a flag, or take it out.',
		find: /\bconsole\.(log|debug)\(/g,
		// The flag-guarded one in runner.js is the exception this allows: a
		// `globalThis.__SEG` a few lines above means somebody turned it on.
		allow: (file, text, at) => {
			const before = text.slice(Math.max(0, at - 400), at);
			return /globalThis\.__[A-Z_]+/.test(before);
		},
	},
];

/**
 * Rule 4: every `state.x = ...` in app.js names a field the literal declares.
 *
 * Reads the `const state = { ... }` literal, takes the keys at its top level,
 * and compares them with every `state.<name> =` and `state.<name> +=` in the
 * file. Text, not a parser -- but the literal has one shape, it is at the top
 * of the file, and the alternative is no check at all.
 */
export function undeclaredState(text) {
	const start = text.indexOf('\nconst state = {');
	if (start < 0) return [];
	// The matching close brace: depth counting from the opening one.
	let depth = 0;
	let end = -1;
	const from = text.indexOf('{', start);
	const src = code(text);
	for (let i = from; i < src.length; i++) {
		if (src[i] === '{') depth++;
		else if (src[i] === '}') {
			depth--;
			if (depth === 0) { end = i; break; }
		}
	}
	if (end < 0) return [];
	const body = src.slice(from + 1, end);
	// Top-level keys only: anything nested belongs to a field, not to `state`.
	const declared = new Set();
	depth = 0;
	let key = '';
	for (let i = 0; i < body.length; i++) {
		const c = body[i];
		if (c === '{' || c === '[' || c === '(') { depth++; continue; }
		if (c === '}' || c === ']' || c === ')') { depth--; continue; }
		if (depth !== 0) continue;
		if (/[A-Za-z0-9_$]/.test(c)) { key += c; continue; }
		if (c === ':' && key) declared.add(key);
		if (!/\s/.test(c) || c === '\n') key = '';
		if (/\s/.test(c) && c !== ' ' && c !== '\t') key = '';
		if (c !== ' ' && c !== '\t' && c !== ':') key = '';
	}
	const out = [];
	const seen = new Set();
	for (const m of src.matchAll(/\bstate\.([A-Za-z_$][A-Za-z0-9_$]*)\s*(?:=[^=]|\+=|-=|\?\?=)/g)) {
		const name = m[1];
		if (declared.has(name) || seen.has(name)) continue;
		seen.add(name);
		out.push({ name, at: m.index });
	}
	return out;
}

/**
 * Rule 5: a named import that nothing in the file uses.
 *
 * Cheap to leave behind and easy to miss -- moving `integratingBlocks` out of
 * edit.js left `COLLECTIONS` and `REMEMBERING_KINDS` imported by a file that
 * no longer mentions either. Harmless, and exactly the kind of harmless thing
 * that accumulates until an import list stops describing what a module needs.
 *
 * **Counted in the raw text, with only the import statements taken out.**
 * The blanked copy the other rules read is not safe here, and finding that out
 * cost three deletions: it blanks the whole inside of a template literal,
 * substitutions included, so `${solverName(sim.solver)}` and
 * `${describeTuple(...)}` looked like no use at all and the imports that fed
 * them were removed. A rule whose finding is "delete this line" has to be
 * wrong in the harmless direction, so this one counts everywhere -- and misses
 * a name that appears only in a comment, which is a finding not made rather
 * than a line wrongly deleted.
 */
export function unusedImports(text) {
	// Every import statement blanked out, so a name is not its own use.
	const src = text.replace(/import\s*\{[^}]*\}\s*from\s*['"][^'"]*['"]\s*;?/g,
		(m) => m.replace(/[^\n]/g, ' '));
	const out = [];
	// Every `import { a, b as c } from '...'` -- the braced form only, since a
	// default or namespace import is nearly always used for its side effect or
	// as `ns.thing`, which this cannot count.
	for (const m of text.matchAll(/import\s*\{([^}]*)\}\s*from\s*['"][^'"]*['"]\s*;?/g)) {
		const names = m[1].split(',').map((n) => n.trim()).filter(Boolean)
			.map((n) => (n.includes(' as ') ? n.split(' as ')[1].trim() : n));
		for (const name of names) {
			if (!/^[A-Za-z_$][\w$]*$/.test(name)) continue;
			// Nowhere at all, now that the import lines themselves are gone.
			if (!new RegExp(`\\b${name}\\b`).test(src)) out.push({ name, at: m.index });
		}
	}
	return out;
}

/** Runs the text rules over `src/`. @returns {Array<{file,line,rule,message}>} */
export function lint(files = sources()) {
	const found = [];
	for (const file of files) {
		const text = readFileSync(file, 'utf8');
		const src = code(text);
		const where = relative(ROOT, file);
		for (const rule of RULES) {
			rule.find.lastIndex = 0;
			for (const m of (rule.raw ? text : src).matchAll(rule.find)) {
				if (rule.allow?.(file, text, m.index)) continue;
				found.push({
					file: where,
					line: lineAt(text, m.index),
					rule: rule.name,
					message: `${m[0].trim()} — ${rule.why}`,
				});
			}
		}
		for (const u of unusedImports(text)) {
			found.push({
				file: where,
				line: lineAt(text, u.at),
				rule: 'no-unused-import',
				message: `${u.name} is imported and never used.`,
			});
		}
		if (where.endsWith('ui/app.js')) {
			for (const u of undeclaredState(text)) {
				found.push({
					file: where,
					line: lineAt(text, u.at),
					rule: 'no-undeclared-state',
					message: `state.${u.name} is assigned but not declared in the `
						+ '`state` literal. Declare it there, so that the list `setModel` '
						+ 'resets can be read and checked — see the note beside `prob`.',
				});
			}
		}
	}
	return found;
}

// --- run it ------------------------------------------------------------------

if (process.argv[1] && import.meta.url.endsWith(process.argv[1].split('/').pop())) {
	const found = lint();
	for (const f of found) {
		process.stdout.write(`${f.file}:${f.line}  ${f.rule}\n    ${f.message}\n`);
	}
	const files = sources().length;
	process.stdout.write(found.length
		? `\n${found.length} problem${found.length === 1 ? '' : 's'} in ${files} files\n`
		: `\nclean — ${files} files, ${RULES.length + 2} rules\n`);
	process.exit(found.length ? 1 : 0);
}
