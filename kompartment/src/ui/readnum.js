/**
 * Numbers typed into a box, read the way they are typed here.
 *
 * `Number(text)` reads `6,21E12` as nothing, and `<input type=number>` reads it
 * by the browser's locale -- in an English Chrome the comma is a thousands
 * separator, and the value becomes 6.21E14 without a word. People who write a
 * comma for the decimal point write one here, so a box this tool reads takes a
 * single comma between digits as the decimal mark, spaces as nothing, and an
 * exponent with `e` or `E`.
 */

/**
 * One number, or null for text that is not one: `1e5`, `-2,5`, `1 000`,
 * `6,21E12`. A minus is allowed, since an axis may run below zero; hex,
 * `Infinity` and anything else `Number` would forgive are not.
 *
 * @param {string} text
 * @returns {number|null}
 */
export function readNumber(text) {
	let s = String(text ?? '').trim().replace(/[−‒–]/g, '-')
		.replace(/[\s   ]/g, '');
	if (!s) return null;
	if (!s.includes('.') && (s.match(/,/g) ?? []).length === 1) s = s.replace(',', '.');
	if (!/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(s)) return null;
	const v = Number(s);
	return Number.isFinite(v) ? v : null;
}

/**
 * A list of numbers: separated by semicolons, by spaces, or by a comma and a
 * space -- `1e3, 1e4, 1e5` and `1e3; 1e4` and `1000 10000` -- while a comma
 * between two digits is still a decimal mark: `1,5; 2,5` is 1.5 and 2.5.
 * What could not be read is returned as well, so a box can say so.
 *
 * @returns {{values: number[], bad: string[]}}
 */
export function readNumberList(text) {
	const parts = String(text ?? '').replace(/,(?=\s)/g, ';').split(/[;\s]+/).filter(Boolean);
	const values = [];
	const bad = [];
	for (const p of parts) {
		const v = readNumber(p);
		if (v == null) bad.push(p);
		else values.push(v);
	}
	return { values, bad };
}
