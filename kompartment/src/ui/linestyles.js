/**
 * Lines that are known by name: a radionuclide, a repository, a pathway, an
 * exposed group.
 *
 * A chart of a block over its nuclides draws one line per nuclide, and which
 * nuclide a line is has to be readable without the legend once it has been
 * read once: I-129 is the same blue in every chart, whatever else is on it.
 * A colour taken from the line's place on the chart could not do that -- the
 * fifth line is a different nuclide on every chart -- so a line that stands
 * for a known index wears that index's own colour and pattern.
 *
 * The table is the HDF5 Browser's (`NAMED_LINE_STYLES` in
 * resources/js/rb-chart-axes.js at kvotab.se), copied as it is, so a nuclide
 * looks the same in both tools: a run handed from here to the browser draws
 * in the colours it was drawn in here. A test compares the two tables where
 * the browser's file is in reach.
 *
 * The patterns are named the way that table names them, which is Plotly's
 * way (`dash`, `dot`, `dashdot`...), and drawn at the lengths Plotly draws
 * them at for a line two pixels wide.
 *
 * The colours were chosen for a light page, and some of them are nearly the
 * page itself on one theme or the other: white and cream on a light chart,
 * navy and black on a dark one. `forSurface` keeps each hue and moves its
 * lightness until the line stands off the chart it is drawn on, so a colour
 * is changed only where it could not be seen as it was.
 */

export const NAMED_LINE_STYLES = {
	// Actinides
	'Ac-227': { color: 'rgb(128,0,0)', dash: 'solid' },
	'Am-241': { color: 'rgb(72,209,204)', dash: 'dashdot' },
	'Am-242m': { color: 'rgb(72,209,204)', dash: 'dash' },
	'Am-243': { color: 'rgb(72,209,204)', dash: 'solid' },
	'Cm-242': { color: 'rgb(175,238,238)', dash: 'dash' },
	'Cm-243': { color: 'rgb(175,238,238)', dash: 'solid' },
	'Cm-244': { color: 'rgb(175,238,238)', dash: 'dot' },
	'Cm-245': { color: 'rgb(175,238,238)', dash: 'dash' },
	'Cm-246': { color: 'rgb(175,238,238)', dash: 'dashdot' },
	'Np-237': { color: 'rgb(218,165,32)', dash: 'solid' },
	'Pa-231': { color: 'rgb(85,107,47)', dash: 'solid' },
	'Pu-238': { color: 'rgb(0,255,255)', dash: 'dot' },
	'Pu-239': { color: 'rgb(0,255,255)', dash: 'solid' },
	'Pu-240': { color: 'rgb(0,255,255)', dash: 'dash' },
	'Pu-241': { color: 'rgb(0,255,255)', dash: 'dashdot' },
	'Pu-242': { color: 'rgb(0,255,255)', dash: 'dash' },
	'Th-228': { color: 'rgb(75,0,130)', dash: 'dash' },
	'Th-229': { color: 'rgb(75,0,130)', dash: 'dot' },
	'Th-230': { color: 'rgb(75,0,130)', dash: 'solid' },
	'Th-232': { color: 'rgb(75,0,130)', dash: 'dash' },
	'U-232': { color: 'rgb(255,0,0)', dash: 'longdash' },
	'U-233': { color: 'rgb(255,0,0)', dash: 'dash' },
	'U-234': { color: 'rgb(255,0,0)', dash: 'dot' },
	'U-235': { color: 'rgb(255,0,0)', dash: 'dash' },
	'U-236': { color: 'rgb(255,0,0)', dash: 'dashdot' },
	'U-238': { color: 'rgb(255,0,0)', dash: 'solid' },

	// Fission products
	'Ag-108m': { color: 'rgb(128,128,0)', dash: 'solid' },
	'Cs-135': { color: 'rgb(0,128,0)', dash: 'solid' },
	'Cs-137': { color: 'rgb(0,128,0)', dash: 'dash' },
	'I-129': { color: 'rgb(30,144,255)', dash: 'solid' },
	'Pd-107': { color: 'rgb(216,191,216)', dash: 'solid' },
	'Se-79': { color: 'rgb(112,128,144)', dash: 'solid' },
	'Sm-151': { color: 'rgb(138,43,226)', dash: 'solid' },
	'Sn-126': { color: 'rgb(0,0,0)', dash: 'solid' },
	'Sr-90': { color: 'rgb(255,215,0)', dash: 'solid' },
	'Tc-99': { color: 'rgb(0,0,128)', dash: 'solid' },
	'Zr-93': { color: 'rgb(144,238,144)', dash: 'solid' },

	// Activation products
	'Be-10': { color: 'rgb(65,105,225)', dash: 'solid' },
	'C-14': { color: 'rgb(0,0,255)', dash: 'solid' },
	'C-14-org': { color: 'rgb(0,0,255)', dash: 'solid' },
	'C-14-ind': { color: 'rgb(0,0,255)', dash: 'dash' },
	'C-14-inorg': { color: 'rgb(0,0,255)', dash: 'dot' },
	'Cl-36': { color: 'rgb(210,105,30)', dash: 'solid' },
	'Co-60': { color: 'rgb(0,255,127)', dash: 'solid' },
	'H-3': { color: 'rgb(0,0,205)', dash: 'solid' },
	'Ni-59': { color: 'rgb(255,0,255)', dash: 'solid' },
	'Ni-63': { color: 'rgb(255,0,255)', dash: 'dash' },
	'Nb-93m': { color: 'rgb(210,180,140)', dash: 'solid' },
	'Nb-94': { color: 'rgb(210,180,140)', dash: 'dash' },
	'Mo-93': { color: 'rgb(0,255,0)', dash: 'solid' },

	// Other radionuclides
	'Ar-39': { color: 'rgb(152,251,152)', dash: 'solid' },
	'Ba-133': { color: 'rgb(70,130,180)', dash: 'solid' },
	'Ca-41': { color: 'rgb(128,0,128)', dash: 'solid' },
	'Cd-113m': { color: 'rgb(124,252,0)', dash: 'solid' },
	'Eu-150': { color: 'rgb(205,133,63)', dash: 'dash' },
	'Eu-152': { color: 'rgb(205,133,63)', dash: 'solid' },
	'Gd-148': { color: 'rgb(255,255,0)', dash: 'solid' },
	'Ho-166m': { color: 'rgb(100,149,237)', dash: 'solid' },
	'K-40': { color: 'rgb(139,69,19)', dash: 'solid' },
	'La-137': { color: 'rgb(255,248,220)', dash: 'solid' },
	'Pb-210': { color: 'rgb(148,0,211)', dash: 'dash' },
	'Po-210': { color: 'rgb(148,0,211)', dash: 'dot' },
	'Rn-222': { color: 'rgb(148,0,211)', dash: 'dashdot' },
	'Ra-226': { color: 'rgb(148,0,211)', dash: 'solid' },
	'Ra-228': { color: 'rgb(148,0,211)', dash: 'dash' },
	'Re-186m': { color: 'rgb(255,160,122)', dash: 'solid' },
	'Si-32': { color: 'rgb(255,228,181)', dash: 'solid' },
	'Tb-157': { color: 'rgb(221,160,221)', dash: 'solid' },
	'Tb-158': { color: 'rgb(221,160,221)', dash: 'dash' },
	'Ti-44': { color: 'rgb(218,112,214)', dash: 'solid' },

	// Repositories
	'Silo': { color: 'rgb(255,204,0)', dash: 'solid' },
	'BMA': { color: 'rgb(153,204,51)', dash: 'solid' },
	'1BMA': { color: 'rgb(153,204,51)', dash: 'solid' },
	'2BMA': { color: 'rgb(153,204,51)', dash: 'dash' },
	'BLA': { color: 'rgb(204,102,255)', dash: 'solid' },
	'1BLA': { color: 'rgb(204,102,255)', dash: 'solid' },
	'2-5BLA': { color: 'rgb(204,102,255)', dash: 'dash' },
	'2BLA': { color: 'rgb(204,102,255)', dash: 'dash' },
	'3BLA': { color: 'rgb(204,102,255)', dash: 'dot' },
	'4BLA': { color: 'rgb(204,102,255)', dash: 'dashdot' },
	'5BLA': { color: 'rgb(204,102,255)', dash: 'longdash' },
	'BTF': { color: 'rgb(102,153,204)', dash: 'solid' },
	'1BTF': { color: 'rgb(102,153,204)', dash: 'solid' },
	'2BTF': { color: 'rgb(102,153,204)', dash: 'dash' },
	'BRT': { color: 'rgb(192,80,77)', dash: 'solid' },

	// Pathways
	'ext': { color: 'rgb(255,211,158)', dash: 'solid' },
	'inh': { color: 'rgb(180,216,229)', dash: 'solid' },
	'ing_water': { color: 'rgb(0,169,212)', dash: 'solid' },
	'ing_meat': { color: 'rgb(224,48,46)', dash: 'solid' },
	'ing_milk': { color: 'rgb(154,154,154)', dash: 'solid' },
	'ing_tuber': { color: 'rgb(142,90,42)', dash: 'solid' },
	'ing_root': { color: 'rgb(142,90,42)', dash: 'dash' },
	'ing_cereal': { color: 'rgb(232,196,0)', dash: 'solid' },
	'ing_veg': { color: 'rgb(58,158,58)', dash: 'solid' },
	'ing_berry': { color: 'rgb(224,64,160)', dash: 'solid' },
	'ing_game': { color: 'rgb(255,140,26)', dash: 'solid' },
	'ing_mush': { color: 'rgb(140,132,36)', dash: 'solid' },
	'ing_cray': { color: 'rgb(138,92,240)', dash: 'solid' },
	'ing_fish': { color: 'rgb(42,112,216)', dash: 'solid' },

	// Exposed groups
	'drained_mire': { color: 'rgb(165,42,42)', dash: 'solid' },
	'forager': { color: 'rgb(147,197,114)', dash: 'solid' },
	'garden_plot': { color: 'rgb(0,191,255)', dash: 'solid' },
	'infield_outland': { color: 'rgb(255,204,0)', dash: 'solid' },
	'drilled_well': { color: 'rgb(0,191,255)', dash: 'solid', width: 3 },
	'drained_mire_irrig': { color: 'rgb(165,42,42)', dash: 'dash' },

	// No colour
	'none': { color: 'rgba(255,255,255,0)', dash: 'solid' },

	// Climate domains
	'submerged': { color: 'rgb(0,191,255)', dash: 'solid' },
	'temperate': { color: 'rgb(34,139,34)', dash: 'solid' },
	'permafrost': { color: 'rgb(70,130,180)', dash: 'solid' },
	'periglacial': { color: 'rgb(70,130,180)', dash: 'solid' },
	'glacial': { color: 'rgb(255,250,250)', dash: 'solid' },
	'glacial thawed': { color: 'rgb(224, 234, 239)', dash: 'solid' },

	// Chemical degradation states
	'State I': { color: 'rgb(79,99,39)', dash: 'solid' },
	'State II': { color: 'rgb(119,147,60)', dash: 'solid' },
	'State IIIa': { color: 'rgb(154,187,89)', dash: 'solid' },
	'State IIIb': { color: 'rgb(195,215,156)', dash: 'solid' },
	'State IV': { color: 'rgb(255,255,255)', dash: 'solid' },
	// Physical degradation states
	'Intact': { color: 'rgb(54,95,146)', dash: 'solid' },
	'Moderately degraded': { color: 'rgb(149,179,216)', dash: 'solid' },
	'Severely degraded': { color: 'rgb(185,205,229)', dash: 'solid' },
	'Completely degraded': { color: 'rgb(220,230,242)', dash: 'solid' },
	'No barrier': { color: 'rgb(255,255,255)', dash: 'solid' },

	// The total, which the chart draws in the text colour instead: black is
	// the page on a dark theme. Kept for the comparison with the browser's
	// table, and so that an index that is itself called Total is not given a
	// colour of its own.
	'Total': { color: 'rgb(0,0,0)', dash: 'solid' },
};

/**
 * The patterns by name, at the lengths Plotly draws them at for a line two
 * pixels wide: its unit is the line width, or three pixels for anything
 * thinner, and `dash` is three of those on and three off.
 */
export const NAMED_DASHES = {
	solid: [],
	dot: [3, 3],
	dash: [9, 9],
	longdash: [15, 15],
	dashdot: [9, 3, 3, 3],
	longdashdot: [15, 6, 3, 6],
};

/**
 * The style a line named `name` wears, or null for a name the table does not
 * know. The name as it is first, then in lower case, as the browser looks it
 * up -- a pathway may be written `Ing_water`.
 *
 * @returns {{color: string, dash: string, width?: number}|null}
 */
export function namedStyle(name) {
	if (name == null) return null;
	const key = String(name);
	if (Object.hasOwn(NAMED_LINE_STYLES, key)) return NAMED_LINE_STYLES[key];
	const lower = key.toLowerCase();
	if (Object.hasOwn(NAMED_LINE_STYLES, lower)) return NAMED_LINE_STYLES[lower];
	return null;
}

/** The canvas dash array for a named pattern; solid for one it does not know. */
export function dashOf(name) {
	return NAMED_DASHES[name] ?? NAMED_DASHES.solid;
}

/**
 * A CSS colour as `[r, g, b, a]` in 0..255 (alpha 0..1), or null for one this
 * cannot read without a page: a keyword, `var(--x)`, `color-mix(...)`.
 */
export function parseColor(text) {
	const s = String(text ?? '').trim();
	let m = /^#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i.exec(s);
	if (m) {
		let h = m[1];
		if (h.length <= 4) h = h.split('').map((c) => c + c).join('');
		const n = (k) => parseInt(h.slice(k, k + 2), 16);
		return [n(0), n(2), n(4), h.length === 8 ? n(6) / 255 : 1];
	}
	m = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+)(%?))?\s*\)$/i.exec(s);
	if (m) {
		const a = m[4] == null ? 1 : m[5] ? Number(m[4]) / 100 : Number(m[4]);
		return [Number(m[1]), Number(m[2]), Number(m[3]), a];
	}
	return null;
}

const toLinear = (c) => {
	const v = c / 255;
	return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
};
const fromLinear = (v) => {
	const c = v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055;
	return Math.round(Math.min(1, Math.max(0, c)) * 255);
};

/** WCAG relative luminance of `[r, g, b]`. */
export function luminance([r, g, b]) {
	return 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b);
}

/** WCAG contrast between two colours as `[r, g, b]`, 1 to 21. */
export function contrast(a, b) {
	const la = luminance(a);
	const lb = luminance(b);
	return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

// OKLab, for changing a colour's lightness without changing its hue.
const toOklab = ([r, g, b]) => {
	const R = toLinear(r); const G = toLinear(g); const B = toLinear(b);
	const l = Math.cbrt(0.4122214708 * R + 0.5363325363 * G + 0.0514459929 * B);
	const m = Math.cbrt(0.2119034982 * R + 0.6806995451 * G + 0.1073969566 * B);
	const s = Math.cbrt(0.0883024619 * R + 0.2817188376 * G + 0.6299787005 * B);
	return [
		0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
		1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
		0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
	];
};
const fromOklab = ([L, A, Bb]) => {
	const l = (L + 0.3963377774 * A + 0.2158037573 * Bb) ** 3;
	const m = (L - 0.1055613458 * A - 0.0638541728 * Bb) ** 3;
	const s = (L - 0.0894841775 * A - 1.2914855480 * Bb) ** 3;
	return [
		fromLinear(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
		fromLinear(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
		fromLinear(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s),
	];
};

/**
 * How far a line has to stand off the chart behind it: on a light chart, the
 * browser's own floor for its pale pathway colours; on a dark one, the 3:1
 * that graphics are asked for, since the table was made for light pages and
 * its dark colours go furthest wrong there.
 */
export const LINE_CONTRAST = { light: 1.7, dark: 3 };

/**
 * `color` as it is drawn over `surface`: unchanged where it already stands off
 * it by the contrast for that surface, and otherwise moved in lightness --
 * darker over a light chart, lighter over a dark one -- just far enough, its
 * hue and as much of its chroma as the screen can show kept.
 *
 * A colour this cannot read, or a surface it cannot, is returned as it is: the
 * one judgement it cannot make is the one it does not make. A transparent
 * colour stays transparent, since that is what it was asked to be.
 *
 * @returns {string} a CSS colour
 */
export function forSurface(color, surface) {
	const c = parseColor(color);
	const bg = parseColor(surface);
	if (!c || !bg || c[3] === 0) return color;
	const dark = luminance(bg) < 0.2;
	const want = dark ? LINE_CONTRAST.dark : LINE_CONTRAST.light;
	if (contrast(c, bg) >= want) return color;
	const lab = toOklab(c);
	// Bisect the lightness between where it is and the far end: contrast
	// grows monotonically as the lightness moves away from the surface's.
	let lo = lab[0];
	let hi = dark ? 1 : 0;
	let best = fromOklab([hi, lab[1], lab[2]]);
	for (let k = 0; k < 24; k++) {
		const mid = (lo + hi) / 2;
		const rgb = fromOklab([mid, lab[1], lab[2]]);
		if (contrast(rgb, bg) >= want) { best = rgb; hi = mid; } else lo = mid;
	}
	return `rgb(${best[0]},${best[1]},${best[2]})`;
}
