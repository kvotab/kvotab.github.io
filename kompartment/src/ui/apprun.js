/**
 * The app, running: its title, its pages, and its parts -- and nothing else
 * of the editor.
 *
 * Laid out on the same grid the designer places parts on (./appdesigner.js),
 * across the whole window, and in one column, in reading order, where the
 * window is too narrow for twelve: see `.app-run` in css/app.css. The parts
 * are live here. Moving a control is the page's to act on (`set` in the
 * context, see ./appwidgets.js); when the run it asks for comes back, the
 * page calls `refreshAppRun` and the results are drawn again in place, so a
 * chart that has been zoomed into stays zoomed.
 */

import { el } from './parts.js';
import { buildComponent, gridItem } from './appwidgets.js';
import { wearTheme } from './appdesigner.js';
import * as apps from '../domain/apps.js';
import { usesSpread } from '../domain/appinputs.js';
import { homeLink, endButtons } from './sitechrome.js';

let root = null;
let hooks = null;
/** The parts on screen: `{id, c, widget}`. */
let drawn = [];
/** Which page is up. The page's, not the model's. */
let page = 0;

/** Back to the first page: a different model, or a fresh start of the app. */
export function resetAppRun(at = 0) {
	page = Math.max(0, at | 0);
}

/**
 * Draws the running app into `host`.
 *
 * @param {HTMLElement} host
 * @param {object} h  what the page provides: `raw()`, `context()` (see
 *   ./appwidgets.js), `status()` -- `{running, sampling, fraction, owed,
 *   spreadOwed, problem}` --, `run()`, `sample()`, `stop()`, `canEdit()` and
 *   `leave()`
 */
export function renderAppRun(host, h) {
	root = host;
	hooks = h;
	for (const d of drawn) d.widget.destroy?.();
	drawn = [];
	const app = apps.readApp(hooks.raw());
	if (!app) { host.replaceChildren(); return; }
	page = Math.min(page, app.pages.length - 1);
	wearTheme(host, app);

	const title = app.title || String(hooks.raw()?.name ?? '') || 'App';
	const run = el('button', { type: 'button', className: 'primary app-run-go', title: 'Run the model at the values the controls hold (⌘↵)' }, 'Run');
	run.addEventListener('click', () => hooks.run());
	run.hidden = app.run !== 'button';
	// The spread, where anything on the app reads it and it is sampled when
	// asked: the one button that says so, whatever page is showing.
	const spread = el('button', {
		type: 'button', className: 'app-run-spread',
		title: `Run the model ${app.realisations.toLocaleString()} times at the controls, drawing every input that carries a distribution`,
	}, 'Run the spread');
	spread.addEventListener('click', () => hooks.sample());
	spread.hidden = !usesSpread(app) || app.spread_when !== 'button';
	const stop = el('button', { type: 'button', className: 'app-run-stop', title: 'Stop the run', hidden: true }, 'Stop');
	stop.addEventListener('click', () => hooks.stop());
	const edit = el('button', { type: 'button', className: 'ghost app-run-edit', title: 'Back to the editor (Esc)' }, 'Edit');
	edit.addEventListener('click', () => hooks.leave());
	edit.hidden = !hooks.canEdit();
	// Framed in the site's page, the bar has the page's full window too (and
	// in it the site's mark and light/dark switch), as the editor's does: an
	// app is the whole of what its user sees. See ./sitechrome.js.
	const bar = el('header', { className: 'app-run-bar' },
		homeLink(),
		el('div', { className: 'app-run-titles' },
			el('h1', { className: 'app-run-title' }, title),
			app.description ? el('p', { className: 'app-run-sub' }, app.description) : null),
		el('span', { className: 'spacer' }),
		el('span', { className: 'app-run-status', role: 'status', 'aria-live': 'polite' }),
		el('progress', { className: 'app-run-progress', max: 1, value: 0, hidden: true }),
		stop, spread, run, edit, ...endButtons());

	const tabs = app.pages.length > 1
		? el('nav', { className: 'app-run-pages', role: 'tablist', 'aria-label': 'Pages' },
			...app.pages.map((p, i) => {
				const b = el('button', {
					type: 'button', role: 'tab', className: `app-run-page${i === page ? ' is-on' : ''}`,
					'aria-selected': String(i === page),
				}, p.name);
				b.addEventListener('click', () => {
					if (page === i) return;
					page = i;
					renderAppRun(root, hooks);
				});
				return b;
			}))
		: null;

	const grid = el('div', { className: 'app-grid app-run-grid' });
	const shown = app.pages[page].components;
	grid.style.setProperty('--rows', String(Math.max(1, apps.rowsOf(shown))));
	const ctx = hooks.context();
	// In the order the page is read in, which is the order it is tabbed
	// through and stacked in on a narrow window: see `stackOrder`.
	for (const c of apps.stackOrder(shown)) {
		const widget = buildComponent(c, ctx);
		grid.append(gridItem(c, widget.node));
		drawn.push({ id: c.id, c, widget });
	}
	const empty = shown.length ? null : el('p', { className: 'app-run-empty' }, 'This page has nothing on it.');
	host.replaceChildren(...[bar, tabs,
		el('div', { className: 'app-run-banner', role: 'alert', hidden: true }),
		el('div', { className: 'app-run-body', tabIndex: -1 }, grid, empty)].filter(Boolean));
	paintAppRunStatus();
}

/**
 * The parts again, where they are: the results after a run, and the inputs
 * after one of them moved -- all but `except`, the one being moved, which
 * already shows where it is and would fight the pointer if set from here.
 * A control moving changes no result until its run is in, so `outputs` is
 * false then: redrawing every chart per pointer move was redrawing the same
 * numbers.
 */
export function refreshAppRun({ inputs = true, outputs = true, except = null } = {}) {
	if (!root || !hooks || root.hidden) return;
	const ctx = hooks.context();
	for (const d of drawn) {
		const isInput = apps.INPUT_TYPES.has(d.c.type);
		if (isInput ? (!inputs || d.id === except) : !outputs) continue;
		d.widget.update?.(ctx);
	}
	paintAppRunStatus();
}

/** Takes the app off the page, and lets its charts go: each watches its box for a resize. */
export function closeAppRun() {
	for (const d of drawn) d.widget.destroy?.();
	drawn = [];
	root?.replaceChildren();
}

/** Every chart drawn again: the theme changed, and a canvas does not follow on its own. */
export function redrawAppRun() {
	for (const d of drawn) d.widget.redraw?.();
}

/**
 * What the app is doing, in the title bar, and what stops it, under it.
 *
 * A run in flight is a word and a bar; a change still to be run, in an app
 * that runs when asked, says so beside the button that runs it; a model that
 * cannot run says why, since somebody using the app has no other place to
 * find out.
 */
export function paintAppRunStatus() {
	if (!root || !hooks) return;
	const s = hooks.status();
	const status = root.querySelector('.app-run-status');
	const bar = root.querySelector('.app-run-progress');
	const banner = root.querySelector('.app-run-banner');
	if (status) {
		status.textContent = s.sampling ? 'Sampling the spread…'
			: s.running ? 'Running…'
				: s.owed ? 'Changed — press Run'
					: s.spreadOwed ? 'The spread is of the controls as they were' : '';
		status.classList.toggle('is-owed', !s.running && (!!s.owed || !!s.spreadOwed));
	}
	if (bar) {
		bar.hidden = !s.running;
		bar.value = Math.max(0, Math.min(1, s.fraction ?? 0));
	}
	const stop = root.querySelector('.app-run-stop');
	if (stop) stop.hidden = !s.running;
	root.querySelector('.app-run-body')?.classList.toggle('is-running', !!s.running);
	if (banner) {
		banner.hidden = !s.problem;
		banner.textContent = s.problem ?? '';
	}
}
