/**
 * The entry point: one line of it, in a file rather than inline in the page.
 *
 * The page carries a Content Security Policy, and an inline `<script>` is the
 * thing a policy exists to refuse -- allowing this one would have meant
 * allowing every other, which is most of what a policy is for. So the two
 * scripts index.html used to carry are files now: this, and ./boot-problem.js,
 * which runs before it and reports the case where this never gets to run.
 */

import { boot } from './app.js';

/**
 * The skin, and whether a page's own header and footer are above and below.
 *
 * Read here rather than in `boot`, because both are attributes the stylesheet
 * matches on: set after the first paint they would be a visible flash of the
 * default palette, and this file runs before anything is drawn.
 *
 * Both are deliberately separate from `?theme=`, which is light against dark.
 * A brand has both of those, and a page embedding this may want the palette
 * without giving up its own chrome or the other way round.
 */
const BRANDS = new Set(['kvotab']);
{
	const params = new URLSearchParams(location.search);
	const brand = params.get('brand');
	if (BRANDS.has(brand)) document.documentElement.setAttribute('data-brand', brand);
	const chrome = params.get('chrome');
	if (BRANDS.has(chrome)) document.documentElement.setAttribute('data-chrome', chrome);
}

// Never on a `file://` page: modules do not load there, and ./boot-problem.js
// has already put an explanation on the screen.
if (location.protocol !== 'file:') {
	boot();
	if (window.__ecolegoStarted) window.__ecolegoStarted();
}
