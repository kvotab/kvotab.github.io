/**
 * A prefix for an axis's unit: k shows Bq as kBq and its numbers divided by a
 * thousand, µ shows Sv/year as µSv/year and its numbers times a million.
 *
 * The rule is the HDF5 Browser's (the unit prefixes in
 * resources/js/rb-chart-axes.js at kvotab.se), here so that a chart of a run
 * reads the same in both tools; a test compares the two where the browser's
 * file is in reach. Which units take a prefix, and how one already there is
 * combined with it -- mSv with k is Sv -- are its decisions:
 *
 *   - only units a prefix is put in front of in use take one: Bq, Sv, Gy, g,
 *     mol, m, s, L, Pa, J, W, eV, V, Hz and the year;
 *   - a unit with an exponent on its first symbol (m3, m^3, m-1) is written
 *     with a power of ten instead, since km3 would be 10⁹ m3;
 *   - so is a unit the list does not have, where a letter in front could make
 *     something else of it, and no unit at all: `10³`.
 *
 * Numbers are moved by their decimal digits rather than multiplied, so 1.1e-7
 * in kilo is 1.1e-10 and not 1.1000000000000001e-10.
 */

/** The prefixes an axis can be given, largest first, with the power of ten of each. */
export const AXIS_PREFIXES = Object.freeze({ P: 15, T: 12, G: 9, M: 6, k: 3, m: -3, 'µ': -6, n: -9, p: -12, f: -15 });

/** A prefix by its power of ten, for a unit that has one already (mSv with k is Sv). */
const PREFIX_OF_EXPONENT = Object.freeze({
	18: 'E', 15: 'P', 12: 'T', 9: 'G', 6: 'M', 3: 'k', '-3': 'm', '-6': 'µ', '-9': 'n', '-12': 'p', '-15': 'f', '-18': 'a',
});

/** The prefixes recognised at the start of a unit: those above, and µ as Greek mu or as u. */
const PREFIX_IN_UNIT = Object.freeze({
	E: 18, P: 15, T: 12, G: 9, M: 6, k: 3, m: -3, 'µ': -6, 'μ': -6, u: -6, n: -9, p: -12, f: -15, a: -18,
});

/** The units a prefix is put in front of. */
const PREFIXABLE_UNITS = new Set(['Bq', 'Ci', 'Sv', 'Gy', 'rem', 'rad', 'g', 't', 'mol', 'm', 's', 'L', 'l',
	'Pa', 'bar', 'J', 'W', 'Wh', 'eV', 'V', 'Hz', 'a', 'yr', 'year', 'years']);

export function isPrefixableUnit(symbol) {
	return PREFIXABLE_UNITS.has(symbol) || /^years?$/i.test(symbol);
}

/**
 * v × 10^e, made by moving v's decimal digits e places: the double nearest the
 * shifted decimal, as v's shortest spelling has it. Anything that is not a
 * finite number is returned as it is.
 */
export function shiftDecimal(v, e) {
	if (!e || typeof v !== 'number' || !Number.isFinite(v) || v === 0) return v;
	const s = v.toExponential();
	const at = s.indexOf('e');
	return Number(`${s.slice(0, at)}e${Number(s.slice(at + 1)) + e}`);
}

/** The power of ten of a prefix: 3 for k; 0 for none, or for anything that is not one. */
export function prefixExponent(prefix) {
	return typeof prefix === 'string' && Object.prototype.hasOwnProperty.call(AXIS_PREFIXES, prefix)
		? AXIS_PREFIXES[prefix] : 0;
}

/** 10³, 10⁻⁶: a power of ten as text. */
export function powerOfTen(e) {
	return `10${String(e).replace('-', '⁻').replace(/\d/g, (d) => '⁰¹²³⁴⁵⁶⁷⁸⁹'[d])}`;
}

/**
 * A unit as an axis with a prefix of 10^e shows it: Bq as kBq, mSv/year as
 * µSv/year (e = -3), year as kyear; m3/year as 10³ m3/year; nothing as 10³.
 *
 * @param {*} unit
 * @param {number} e  the prefix's power of ten; 0 leaves the unit as it is
 * @returns {string}
 */
export function unitWithPrefix(unit, e) {
	const text = unit === undefined || unit === null ? '' : String(unit);
	if (!e) return text;
	const u = text.trim();
	const power = powerOfTen(e);
	if (u === '' || /^[-–—−1]$/.test(u)) return power;
	// The first symbol, and what follows it: an exponent there (m3, m^3, m²,
	// m-1, m<sup>3</sup>) would raise the prefix with it.
	const m = /^([A-Za-zµμ]+)([\s\S]*)$/.exec(u);
	if (!m || /^(?:[\d^²³¹⁰-⁻]|\*\*|[-−]\d|<sup)/i.test(m[2])) return `${power} ${u}`;
	const [, symbol, rest] = m;
	if (isPrefixableUnit(symbol)) return PREFIX_OF_EXPONENT[e] ? PREFIX_OF_EXPONENT[e] + u : `${power} ${u}`;
	// A unit with a prefix of its own: the two make one.
	const inner = PREFIX_IN_UNIT[symbol[0]];
	if (inner !== undefined && isPrefixableUnit(symbol.slice(1))) {
		const both = inner + e;
		if (both === 0) return symbol.slice(1) + rest;
		if (PREFIX_OF_EXPONENT[both]) return PREFIX_OF_EXPONENT[both] + symbol.slice(1) + rest;
	}
	return `${power} ${u}`;
}

/**
 * An axis's units with its prefix, several of them as a list: what a panel's
 * axis is lettered with. No unit and a prefix is the power of ten alone.
 */
export function unitsWithPrefix(units, e) {
	const list = (units ?? []).filter(Boolean);
	if (!list.length) return e ? powerOfTen(e) : '';
	return list.map((u) => unitWithPrefix(u, e)).join(', ');
}
