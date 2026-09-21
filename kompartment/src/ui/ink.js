/**
 * Reading a colour, and picking text that stays legible on it.
 *
 * A block may be any colour -- the picker is a colour input and the value goes
 * straight into the project file -- so nothing downstream can assume a light
 * fill or a dark one. Anywhere a block's own colour is painted, the label on
 * top of it has to be chosen from that colour rather than from the theme.
 *
 * Its own module because the diagram and the transfer matrix both do it, and
 * two copies of a luminance formula are two copies that can disagree about
 * whether a fill is light.
 */

/**
 * Text colours that stay legible on an arbitrary fill.
 *
 * Uses the WCAG relative luminance of the fill, which is what actually
 * predicts readability, rather than a naive average of the channels.
 *
 * Null for a colour this cannot read -- a CSS keyword, an `rgb()`, anything a
 * hand-edited file might hold. The caller then leaves the theme's own ink
 * alone, which is the right answer for a fill whose lightness is unknown.
 */
export function inkFor(color) {
	const l = relativeLuminance(color);
	if (l == null) return null;
	return l > CROSSOVER
		? { strong: '#0b0b0b', dim: 'rgba(0,0,0,0.62)' }
		: { strong: '#ffffff', dim: 'rgba(255,255,255,0.72)' };
}

/**
 * The fill luminance at which the two inks are equally readable.
 *
 * Not a matter of taste: WCAG contrast is (L1 + 0.05)/(L2 + 0.05), so for the
 * two inks below -- white at 1, `#0b0b0b` at 0.0033 -- the crossover is where
 * (L + 0.05)^2 = 1.05 * 0.0533, which is L = 0.187. Above it black reads
 * better, below it white does.
 *
 * It used to say 0.42, which is the crossover of nothing: every fill between
 * 0.187 and 0.42 got the *less* readable of the two. That is the whole band of
 * mid-tones, and both colours in examples/four-compartment.json are in it --
 * its grey compartment took white text at 3.55:1 where black would have been
 * 5.54:1. Visible on the diagram, and much more so in the transfer matrix,
 * where the fill is a whole cell with the name on it.
 */
const CROSSOVER = 0.187;

export function relativeLuminance(color) {
	const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(color).trim());
	if (!m) return null;
	let hex = m[1];
	if (hex.length === 3) hex = hex.split('').map((c) => c + c).join('');
	const channel = (v) => {
		const c = parseInt(v, 16) / 255;
		return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
	};
	return 0.2126 * channel(hex.slice(0, 2))
		+ 0.7152 * channel(hex.slice(2, 4))
		+ 0.0722 * channel(hex.slice(4, 6));
}
