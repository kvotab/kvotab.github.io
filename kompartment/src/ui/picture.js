/**
 * The diagram as a picture: SVG, PNG or JPEG.
 *
 * WHY IT IS NOT JUST `XMLSerializer`. What is on screen is an SVG whose
 * appearance is entirely in `css/app.css` -- a compartment is a `<path>` with
 * a class, and everything about how it looks is a rule and a custom property.
 * Serialised on its own it comes out as unstyled black shapes. So the styles
 * have to travel with it, and there are two ways to do that: embed the
 * stylesheet, or write the computed values onto the elements.
 *
 * This writes them onto the elements. The stylesheet is five thousand lines
 * about a whole application, its rules are keyed on ancestors the picture will
 * not have, and its colours are custom properties that resolve against
 * `:root`. A file that carries only what its own shapes need opens in
 * Inkscape, in Illustrator, in a browser and in Word, which is the point of
 * exporting one.
 *
 * WHAT IS IN THE PICTURE. The whole diagram at 1:1, not the part on screen:
 * the camera is dropped and the viewBox is the bounding box of what is drawn,
 * with a margin. The editing chrome is not -- selection rings, resize grips,
 * connection handles, the drop highlight and the marquee are all about the
 * editor rather than the model. The grid is not either: it is an editing aid,
 * and it is a CSS background rather than part of the SVG, so it would have had
 * to be invented for the picture rather than copied into it.
 */

/**
 * The properties written onto each element.
 *
 * Only what an SVG shape's appearance is made of. `display` and `visibility`
 * are deliberately absent: everything inside `<defs>` computes to `display:
 * none`, and copying that would take the arrowheads out of the picture.
 */
export const INLINE_PROPS = [
	'fill', 'fill-opacity', 'fill-rule',
	'stroke', 'stroke-width', 'stroke-opacity', 'stroke-dasharray',
	'stroke-dashoffset', 'stroke-linecap', 'stroke-linejoin', 'stroke-miterlimit',
	'opacity', 'marker-start', 'marker-mid', 'marker-end',
	'font-family', 'font-size', 'font-style', 'font-weight', 'letter-spacing',
	'text-anchor', 'dominant-baseline', 'paint-order', 'color',
];

/**
 * What each property already is, in an SVG that says nothing about it.
 *
 * A value equal to its own initial value is not worth a byte -- but which
 * value that is has to be right per property, not guessed at. Treating `none`
 * as "nothing to say" filled every `fill: none` shape solid black in the
 * picture, because black is what `fill` is when nobody says otherwise: the
 * outflow cloud came out as a blob and every connection as a filled wedge.
 */
export const INITIAL = {
	fill: 'rgb(0, 0, 0)',
	'fill-opacity': '1',
	'fill-rule': 'nonzero',
	stroke: 'none',
	'stroke-width': '1px',
	'stroke-opacity': '1',
	'stroke-dasharray': 'none',
	'stroke-dashoffset': '0px',
	'stroke-linecap': 'butt',
	'stroke-linejoin': 'miter',
	'stroke-miterlimit': '4',
	opacity: '1',
	'marker-start': 'none',
	'marker-mid': 'none',
	'marker-end': 'none',
	'font-style': 'normal',
	'font-weight': '400',
	'letter-spacing': 'normal',
	'text-anchor': 'start',
	'dominant-baseline': 'auto',
	'paint-order': 'normal',
};

/** Font properties belong on the elements that draw text, and nowhere else. */
const FONT_PROPS = new Set(['font-family', 'font-size', 'font-style',
	'font-weight', 'letter-spacing', 'text-anchor', 'dominant-baseline', 'color']);
const TEXTISH = new Set(['text', 'tspan', 'textPath']);

/**
 * The parts of the canvas that are about editing rather than about the model.
 *
 * A picture of a diagram should not carry the handle you drag to connect two
 * compartments, the ring around what happens to be selected, or the fat
 * invisible shapes that make thin lines easy to hit. They are all real
 * elements with real computed styles, so left in they come out *more* visible
 * than on screen -- a hit area is transparent by a rule that the picture would
 * be carrying, and a selection ring is a state nobody exports on purpose.
 */
const CHROME = new Set([
	'graph-overlay', 'gmarquee', 'gconnect-preview',
	// A shape's fat invisible outline and the handles round the one that is
	// selected: both are about editing it. The first would come out as a wide
	// smear in a picture, where there is no pointer to catch.
	'gdecor-hit', 'gdecor-handles',
	// And the ghost of a shape with no fill and no line: it is on screen so
	// the shape can be found and picked up again, and a picture of a shape
	// that paints nothing should paint nothing.
	'gdecor-ghost',
	'gport', 'gport-dot', 'gport-glyph', 'gport-hit',
	'gnode-halo', 'gnode-glow',
	'gedge-hit', 'gend-hit', 'ggrip-hit', 'gterm-hit', 'gresize',
]);

/** Whether an element is one of those. */
export function isChrome(el) {
	const cls = el.getAttribute?.('class');
	if (!cls) return false;
	for (const name of cls.split(/\s+/)) if (CHROME.has(name)) return true;
	return false;
}

/**
 * Copies the appearance of a live tree onto a clone of it.
 *
 * Walked in lockstep rather than by selector, because the clone is a deep copy
 * and the two trees therefore have the same shape: child `i` of a clone is the
 * copy of child `i` of the original, whatever either is.
 */
export function inlineStyles(live, clone) {
	const drop = [];
	walk(live, clone, drop);
	// After the walk, not during it: removing as it goes would take the two
	// trees out of step, and they are matched by position.
	for (const el of drop) el.remove();
	return clone;
}

function walk(live, clone, drop) {
	if (live.nodeType !== 1) return;
	if (isChrome(live)) { drop.push(clone); return; }
	const cs = getComputedStyle(live);
	const textish = TEXTISH.has(live.tagName);
	const parts = [];
	for (const prop of INLINE_PROPS) {
		if (FONT_PROPS.has(prop) && !textish) continue;
		const v = cs.getPropertyValue(prop).trim();
		if (!v || v === INITIAL[prop]) continue;
		parts.push(`${prop}:${v}`);
	}
	// Written whole, or taken off: an element's own `style` may carry custom
	// properties the stylesheet was reading -- a shape's colour tokens -- and
	// in the picture those name nothing. Everything they decided is already
	// inlined above as the value it resolved to.
	if (parts.length) clone.setAttribute('style', parts.join(';'));
	else clone.removeAttribute('style');
	// Classes are what the rules were keyed on; in the picture they are noise
	// that only invites a stylesheet to disagree with the inlined values.
	clone.removeAttribute('class');
	const a = live.children;
	const b = clone.children;
	for (let i = 0; i < a.length && i < b.length; i++) walk(a[i], b[i], drop);
}

/** The union of several `getBBox()`es, ignoring the empty ones. */
export function unionBox(boxes) {
	let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
	for (const b of boxes) {
		if (!b || (!b.width && !b.height)) continue;
		x0 = Math.min(x0, b.x);
		y0 = Math.min(y0, b.y);
		x1 = Math.max(x1, b.x + b.width);
		y1 = Math.max(y1, b.y + b.height);
	}
	if (!Number.isFinite(x0)) return null;
	return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
}

/**
 * The picture, as SVG text.
 *
 * @param {object} opts
 * @param {SVGSVGElement} opts.root      the live canvas
 * @param {SVGElement} opts.viewport     the group the camera transforms
 * @param {SVGElement[]} opts.drop       groups to leave out (the chrome)
 * @param {{x: number, y: number, width: number, height: number}} opts.box
 * @param {string} [opts.background]     a colour, or '' for transparent
 * @param {number} [opts.padding]
 * @param {string} [opts.title]          for the picture's own <title>
 */
export function diagramSvgText({
	root, viewport, drop = [], box, background = '', padding = 24, title = '',
}) {
	const clone = root.cloneNode(true);
	inlineStyles(root, clone);

	// The chrome, found by position rather than by class: `inlineStyles` has
	// just taken the classes off.
	const kidsOf = (el) => [...el.parentNode.children].indexOf(el);
	const viewportClone = clone.children[kidsOf(viewport)];
	for (const el of drop) {
		const at = kidsOf(el);
		const twin = viewportClone?.children?.[at];
		if (twin) twin.remove();
	}
	// The whole diagram at 1:1: the camera is where the *screen* is, and a
	// picture is not a screenshot.
	viewportClone?.removeAttribute('transform');

	const x = box.x - padding;
	const y = box.y - padding;
	const w = Math.max(1, box.width + padding * 2);
	const h = Math.max(1, box.height + padding * 2);
	clone.setAttribute('viewBox', `${round(x)} ${round(y)} ${round(w)} ${round(h)}`);
	clone.setAttribute('width', String(round(w)));
	clone.setAttribute('height', String(round(h)));
	clone.removeAttribute('style');
	clone.removeAttribute('tabindex');
	clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
	clone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink');

	if (background) {
		const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
		rect.setAttribute('x', String(round(x)));
		rect.setAttribute('y', String(round(y)));
		rect.setAttribute('width', String(round(w)));
		rect.setAttribute('height', String(round(h)));
		rect.setAttribute('fill', background);
		// Behind everything, and after the <defs> so the markers survive.
		clone.insertBefore(rect, clone.firstChild?.nextSibling ?? null);
	}
	if (title) {
		const t = document.createElementNS('http://www.w3.org/2000/svg', 'title');
		t.textContent = title;
		clone.insertBefore(t, clone.firstChild);
	}

	const text = new XMLSerializer().serializeToString(clone);
	return { text: `<?xml version="1.0" encoding="UTF-8"?>\n${text}`, width: w, height: h };
}

const round = (v) => Math.round(v * 100) / 100;

/**
 * The same picture rasterised.
 *
 * Through an `Image`, which is the only thing that can lay out SVG text with
 * the fonts the page is using. `scale` is there because a diagram in a report
 * is read at print resolution: at 1 the letters are the size they are on
 * screen and look it.
 *
 * JPEG has no transparency, so a picture asked for as one is given a white
 * ground when the caller wanted none -- better than the black that a
 * transparent PNG turns into.
 */
export function rasterise(svgText, { width, height, scale = 2, mime = 'image/png', quality = 0.92, background = '' } = {}) {
	return new Promise((resolve, reject) => {
		const url = URL.createObjectURL(new Blob([svgText], { type: 'image/svg+xml' }));
		const img = new Image();
		img.decoding = 'sync';
		img.onload = () => {
			try {
				const canvas = document.createElement('canvas');
				canvas.width = Math.max(1, Math.round(width * scale));
				canvas.height = Math.max(1, Math.round(height * scale));
				const ctx = canvas.getContext('2d');
				const ground = background || (mime === 'image/jpeg' ? '#ffffff' : '');
				if (ground) {
					ctx.fillStyle = ground;
					ctx.fillRect(0, 0, canvas.width, canvas.height);
				}
				ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
				canvas.toBlob(
					(blob) => (blob ? resolve(blob) : reject(new Error('The picture could not be encoded.'))),
					mime,
					quality,
				);
			} catch (e) {
				reject(e);
			} finally {
				URL.revokeObjectURL(url);
			}
		};
		img.onerror = () => {
			URL.revokeObjectURL(url);
			reject(new Error('The picture could not be drawn.'));
		};
		img.src = url;
	});
}

/** A name a file system will take, from whatever the model is called. */
export function fileName(parts, extension) {
	const stem = parts
		.filter(Boolean)
		.join(' - ')
		.replace(/[\\/:*?"<>|]+/g, '-')
		.replace(/\s+/g, ' ')
		.trim()
		.slice(0, 120) || 'diagram';
	return `${stem}.${extension}`;
}

/** Hands a blob to the browser as a download. */
export function saveBlob(name, blob) {
	const url = URL.createObjectURL(blob);
	const a = document.createElement('a');
	a.href = url;
	a.download = name;
	a.rel = 'noopener';
	document.body.append(a);
	a.click();
	a.remove();
	// Not immediately: Safari has not started reading the blob when the click
	// returns, and a revoked URL there is a download that never arrives.
	setTimeout(() => URL.revokeObjectURL(url), 10000);
}

/** What each format is called and how it is encoded. */
export const PICTURE_KINDS = {
	svg: { label: 'SVG', extension: 'svg', mime: 'image/svg+xml' },
	png: { label: 'PNG', extension: 'png', mime: 'image/png' },
	jpeg: { label: 'JPEG', extension: 'jpg', mime: 'image/jpeg' },
};
