/**
 * Choosing radionuclides from the ICRP 107 database, and taking their chains
 * with them.
 *
 * Two things this is modelled on. The decay-chain page at kvotab.se/rdc.html
 * browses the same database as a tree of elements, each holding its own
 * radioisotopes, which is how anyone who knows what they are looking for
 * navigates 1,512 nuclides -- by element first. And Ecolego's own nuclide
 * selection is graphical for a reason: what you are choosing is not a list of
 * names but a set of chains, and whether you have the right set is a question
 * about the chains, not about the names.
 *
 * So the interesting half is not the list, it is the line under it. Pick U-238
 * and the panel says what the model will actually contain -- U-238, U-234,
 * Th-230, Ra-226, Pb-210 -- and what it has collapsed out on the way: the
 * fourteen members that live for days or minutes and are assumed to sit in
 * secular equilibrium with their parents. Change the threshold from a year to
 * a month and Po-210 appears. That is the decision being made, and it is made
 * where it can be seen rather than in a table typed afterwards.
 *
 * The arithmetic is all in ../domain/decaydb.js; this file is the room it
 * happens in.
 */

import * as ed from '../domain/edit.js';
import * as db from '../domain/decaydb.js';
import { openModal, closeModal } from './modal.js';
import { el } from './parts.js';
import { dialogInfo } from './dialoginfo.js';

/**
 * What the dialog is showing and what has been chosen.
 *
 * Module state, not DOM state: the modal rebuilds its body on every refresh --
 * including the ones an edit elsewhere causes -- so anything kept in the
 * markup would be lost.
 */
let ui = null;

/** How many search hits are listed before the list says how many more. */
const MOST_HITS = 60;

/** The default threshold: what a long-term safety assessment models. */
const DEFAULT_THRESHOLD = 1;

/**
 * Opens the picker.
 *
 * @param {object} project the raw project
 * @param {{onChange?: Function, onStatus?: Function}} hooks
 */
export function openNuclidePicker(project, hooks = {}) {
	const inModel = new Set(
		(ed.nuclideList(project)?.indices ?? []).map((i) => i.name),
	);
	ui = {
		project,
		hooks,
		// Explicitly chosen. The chain members follow from these.
		picked: new Set(),
		// Chain members the reader has decided not to model after all: a
		// truncated chain is a real modelling choice, not a mistake.
		dropped: new Set(),
		threshold: DEFAULT_THRESHOLD,
		// The other bound: above this half-life a daughter is a sink. The
		// model's own setting, since the run reads the same one.
		ceiling: Number(project.simulation?.decay_ceiling) > 0
			? Number(project.simulation.decay_ceiling) : Infinity,
		// Whether the isotope lists leave out what the threshold would
		// collapse anyway.
		hideShort: false,
		element: 'U',
		query: '',
		inModel,
	};
	const modal = openModal({
		info: dialogInfo('nuclides'),
		title: () => 'Radionuclides from ICRP 107',
		subtitle: () => `${db.allUnstable().length} radionuclides, `
			+ 'their half-lives and their decay pairs — ICRP Publication 107. '
			+ 'Choose what to model explicitly; the chain follows.',
		build: render,
		onClose: () => { ui = null; },
	});
	// Two scrolling lists and a chain under them need more room than a form of
	// short fields, and they need one column rather than two.
	modal.dialog.classList.add('modal-wide');
	return modal;
}

/** The nuclides the current selection implies, and what it collapses out. */
function selection() {
	const roots = [...ui.picked].filter((n) => !ui.dropped.has(n));
	if (!roots.length) return { members: [], skipped: [], sinks: [], pairs: [], through: [] };
	const { members, skipped, sinks } = db.chainFrom(roots, { threshold: ui.threshold, ceiling: ui.ceiling });
	const kept = members.filter((n) => !ui.dropped.has(n));
	const { pairs, through } = db.collapse(kept, { ceiling: ui.ceiling });
	return { members: kept, skipped, sinks, pairs, through };
}

function render(host) {
	if (!ui) return;
	const { members, pairs, through } = selection();

	host.append(renderTools());
	host.append(el('div', { className: 'np-cols' },
		renderElements(), renderIsotopes(members)));
	host.append(renderChain(members, pairs, through));
	host.append(renderActions(members));
}

/** The search box and the threshold: the two things that change what is offered. */
function renderTools() {
	const box = el('div', { className: 'np-tools' });

	const search = el('input', {
		type: 'search', className: 'np-search', value: ui.query,
		placeholder: 'Find a nuclide — Cs-137, or Cs, or caesium',
		spellcheck: false,
	});
	// Rebuilt on every keystroke, so the caret has to be put back.
	search.addEventListener('input', () => {
		// A `<dialog>` fires its `close` event asynchronously, so the dialog is
		// gone and `ui` with it before the last event off this field arrives:
		// adding a nuclide and watching the picker close threw
		// "Cannot set properties of null" out of here every time.
		if (!ui) return;
		ui.query = search.value;
		const at = search.selectionStart;
		redraw();
		const again = document.querySelector('.np-search');
		if (again) { again.focus(); again.setSelectionRange(at, at); }
	});

	const sel = el('select', { className: 'np-threshold' });
	for (const t of db.THRESHOLDS) {
		sel.append(el('option', {
			value: String(t.years), selected: t.years === ui.threshold,
			title: t.what,
		}, `${t.label} — ${t.what}`));
	}
	sel.addEventListener('change', () => {
		ui.threshold = Number(sel.value);
		redraw();
	});

	// The ceiling: what the walk stops at from above. Th-232 at fourteen
	// billion years is the case -- a daughter no assessment sees decay, and
	// one that passed *through* would hand its parent's activity on at the
	// parent's rate.
	const top = el('select', { className: 'np-threshold np-ceiling' });
	for (const c of db.CEILINGS) {
		top.append(el('option', {
			value: String(c.years), selected: c.years === ui.ceiling, title: c.what,
		}, `${c.label} — ${c.what}`));
	}
	top.addEventListener('change', () => {
		ui.ceiling = Number(top.value);
		redraw();
	});
	const hide = el('input', { type: 'checkbox', checked: ui.hideShort });
	hide.addEventListener('change', () => { ui.hideShort = hide.checked; redraw(); });

	box.append(
		search,
		el('label', { className: 'np-threshold-label' },
			el('span', {}, 'Model explicitly above'), sel),
		el('label', { className: 'np-threshold-label',
			title: 'A daughter longer-lived than this is treated as stable: the chain stops '
				+ 'there and nothing below it is brought in. Saved with the model, and the '
				+ 'run collapses its decay pairs the same way.' },
		el('span', {}, 'treat as stable above'), top),
		el('label', { className: 'np-threshold-label np-hide',
			title: 'Leave out of the lists the nuclides that live less than the threshold: '
				+ 'they would be collapsed into their parents anyway.' },
		hide, el('span', {}, 'hide shorter-lived')),
	);
	return box;
}

/**
 * The elements, as the source page lists them: by atomic number, with how many
 * radioisotopes each has. This is how anyone who knows the nuclide they want
 * finds it -- Caesium, then 137.
 */
function renderElements() {
	const box = el('div', { className: 'np-side' });
	const chosen = new Set([...ui.picked, ...selection().members].map(db.elementOf));
	for (const e of db.elements()) {
		if (!e.unstable) continue;
		const row = el('button', {
			className: 'np-el' + (e.symbol === ui.element ? ' is-current' : '')
				+ (chosen.has(e.symbol) ? ' is-chosen' : ''),
			type: 'button',
			title: `${e.name} — ${e.category.replace(/_/g, ' ')}, Z = ${e.z}`,
		},
		el('span', { className: 'np-el-z' }, String(e.z)),
		el('b', { className: 'np-el-sym' }, e.symbol),
		el('span', { className: 'np-el-name' }, e.name),
		el('span', { className: 'np-el-count' }, String(e.unstable)));
		row.addEventListener('click', () => { ui.element = e.symbol; ui.query = ''; redraw(); });
		box.append(row);
	}
	return box;
}

/** One nuclide, as a row that can be ticked. */
function isotopeRow(name, members) {
	const n = db.nuclide(name);
	const chainOnly = !ui.picked.has(name) && members.includes(name);
	const has = ui.inModel.has(name);
	const on = members.includes(name);

	const box = el('input', { type: 'checkbox', checked: on || has, disabled: has });
	box.addEventListener('change', () => {
		if (box.checked) { ui.picked.add(name); ui.dropped.delete(name); }
		else if (ui.picked.has(name)) ui.picked.delete(name);
		// Unticking something the chain brought in is a decision to truncate
		// there, which has to be remembered or the chain would put it back.
		else ui.dropped.add(name);
		redraw();
	});

	const row = el('label', {
		className: 'np-nuc' + (on ? ' is-on' : '') + (chainOnly ? ' is-chain' : '')
			+ (has ? ' is-have' : ''),
		title: has ? `${name} is already in the model`
			: `${n.text}${n.progeny.length
				? ` — ${n.progeny.map((p) => `${p.mode} to ${p.name}`
					+ (p.branching < 0.999 ? ` (${(p.branching * 100).toPrecision(3)}%)` : '')).join(', ')}`
				: ''}`,
	},
	box,
	el('span', { className: 'np-nuc-name' }, name),
	el('span', { className: 'np-nuc-hl' }, n.text),
	el('span', { className: 'np-nuc-mode' },
		n.progeny.map((p) => p.mode).filter((m, i, a) => a.indexOf(m) === i).join(' ')));
	if (chainOnly) row.append(el('span', { className: 'np-nuc-tag' }, 'chain'));
	if (has) row.append(el('span', { className: 'np-nuc-tag' }, 'in model'));
	return row;
}

/**
 * Whether a nuclide is listed at all under *hide shorter-lived*: anything at
 * or above the threshold, and anything already chosen or in the chain, since
 * a row that is ticked must stay where it can be unticked.
 */
function shown(name, members) {
	if (!ui.hideShort) return true;
	return db.halfLife(name) >= ui.threshold || ui.picked.has(name)
		|| members.includes(name) || ui.inModel.has(name);
}

/** The nuclides on offer: one element's, or whatever the search matches. */
function renderIsotopes(members) {
	const box = el('div', { className: 'np-main' });
	const q = ui.query.trim().toLowerCase();

	if (q) {
		// A name, an element symbol, or an element's name in words -- the page
		// this is modelled on lets you get at a nuclide all three ways.
		const bySymbol = db.elements()
			.filter((e) => e.name.toLowerCase().startsWith(q) || e.symbol.toLowerCase() === q)
			.map((e) => e.symbol);
		const hits = db.allUnstable().filter((n) => (n.toLowerCase().includes(q)
			|| bySymbol.includes(db.elementOf(n))) && shown(n, members));
		box.append(el('div', { className: 'np-head' },
			el('b', {}, hits.length
				? `${hits.length} nuclide${hits.length === 1 ? '' : 's'} match “${ui.query}”`
				: `Nothing matches “${ui.query}”`)));
		for (const name of hits.slice(0, MOST_HITS)) box.append(isotopeRow(name, members));
		if (hits.length > MOST_HITS) {
			box.append(el('p', { className: 'hint' },
				`and ${hits.length - MOST_HITS} more — narrow the search, or pick the `
				+ 'element on the left.'));
		}
		return box;
	}

	const e = db.element(ui.element);
	const isotopes = db.isotopesOf(ui.element).filter((n) => !db.isStable(n) && shown(n, members));
	box.append(el('div', { className: 'np-head' },
		el('b', {}, e ? e.name : ui.element),
		el('span', { className: 'np-head-what' },
			`${isotopes.length} radioisotope${isotopes.length === 1 ? '' : 's'}`
			+ (e ? ` · ${e.category.replace(/_/g, ' ')} · Z = ${e.z}` : ''))));
	for (const name of isotopes) box.append(isotopeRow(name, members));
	if (!isotopes.length) {
		box.append(el('p', { className: 'hint' },
			`ICRP 107 has no radioisotopes for ${e ? e.name : ui.element}.`));
	}
	return box;
}

/**
 * What the selection actually means: the chain, and what was collapsed.
 *
 * The point of the whole dialog. A list of ticked names says nothing about
 * whether the right set has been chosen; the pairs and the pass-throughs do.
 */
function renderChain(members, pairs, through) {
	const box = el('div', { className: 'np-chain' });
	if (!members.length) {
		box.append(el('p', { className: 'hint' },
			'Tick a nuclide and its chain is worked out here — which members are '
			+ 'worth a state variable at the threshold above, which are assumed '
			+ 'to sit in equilibrium with their parents, and the branching that '
			+ 'reaches each one.'));
		return box;
	}

	box.append(el('div', { className: 'np-chain-head' },
		el('b', {}, `${members.length} nuclide${members.length === 1 ? '' : 's'}`),
		el('span', {}, pairs.length
			? `${pairs.length} decay pair${pairs.length === 1 ? '' : 's'}`
			: 'no decay between them')));

	// The pairs, grouped by parent, so a chain reads as a chain.
	const byParent = new Map();
	for (const [p, d, br] of pairs) {
		if (!byParent.has(p)) byParent.set(p, []);
		byParent.get(p).push([d, br]);
	}
	const grid = el('div', { className: 'np-pairs' });
	for (const name of members) {
		const kids = byParent.get(name) ?? [];
		// The name goes to its element, because a chain of six nuclides is six
		// elements and hunting for lead in order to look at Pb-210 is not
		// navigation.
		const to = el('button', {
			className: 'np-pair-from', type: 'button',
			title: `Show the ${db.element(db.elementOf(name))?.name ?? db.elementOf(name)} isotopes`,
		}, name);
		to.addEventListener('click', () => {
			ui.element = db.elementOf(name);
			ui.query = '';
			redraw();
		});
		const row = el('div', { className: 'np-pair' },
			to,
			el('span', { className: 'np-pair-hl' }, db.halfLifeText(name)));
		if (!kids.length) {
			row.append(el('span', { className: 'np-pair-to np-pair-end' },
				'end of the chain here'));
		} else {
			row.append(el('span', { className: 'np-pair-to' },
				kids.flatMap(([d, br], i) => {
					// What the decay passes through on the way, in parentheses
					// -- GoldSim's "skipped intermediates" -- so a pair the
					// model asked for wears its assumption where it is read.
					const via = db.pathBetween(name, d, members) ?? [];
					return [
						i ? el('span', { className: 'np-pair-sep' }, ' · ') : null,
						el('span', {}, `→ ${d}`),
						via.length
							? el('span', { className: 'np-pair-via',
								title: `${via.length === 1 ? 'Passes' : 'Pass'} through ${via.join(', ')}, `
									+ 'assumed in equilibrium with the parent' },
							` (${via.join(', ')})`)
							: null,
						br < 0.999
							? el('span', { className: 'np-pair-br' },
								` ${(br * 100).toPrecision(3)}%`)
							: null,
					].filter(Boolean);
				})));
		}
		// Truncating the chain is done here, where the members are, rather than
		// by finding each one's element in the list on the left.
		if (!ui.inModel.has(name)) {
			const drop = el('button', {
				className: 'ghost np-pair-drop', type: 'button',
				title: `Leave ${name} out \u2014 its parent then decays straight `
					+ 'through it, as if it were in equilibrium with it',
				'aria-label': `Leave ${name} out`,
			}, '\u00d7');
			drop.addEventListener('click', () => {
				ui.dropped.add(name);
				ui.picked.delete(name);
				redraw();
			});
			row.append(drop);
		}
		grid.append(row);
	}
	box.append(grid);

	// What has been left out on purpose, and the way back: a chain truncated by
	// accident would otherwise have no visible undo.
	if (ui.dropped.size) {
		const line = el('p', { className: 'np-dropped' },
			el('b', {}, `${ui.dropped.size} left out: `),
			[...ui.dropped].join(', '), ' ');
		const back = el('button', { className: 'link-btn', type: 'button' }, 'put back');
		back.addEventListener('click', () => { ui.dropped.clear(); redraw(); });
		line.append(back);
		box.append(line);
	}

	if (through.length) {
		box.append(el('p', { className: 'np-through' },
			el('b', {}, `${through.length} collapsed out: `),
			through.join(', '),
			el('span', { className: 'np-through-why' },
				' — short-lived, so assumed to be in secular equilibrium with '
				+ 'its parent. The branching that reaches each modelled nuclide '
				+ 'is the product of the ratios along the way.')));
	}
	const { sinks } = selection();
	if (sinks.length) {
		box.append(el('p', { className: 'np-through' },
			el('b', {}, `${sinks.length} stopped at: `),
			sinks.map((n) => `${n} (${db.halfLifeText(n)})`).join(', '),
			el('span', { className: 'np-through-why' },
				' — longer-lived than the ceiling, so treated as stable: the chain '
				+ 'ends there and nothing below is brought in.')));
	}
	return box;
}

/** What the dialog does when it is done. */
function renderActions(members) {
	const box = el('div', { className: 'np-actions' });
	const fresh = members.filter((n) => !ui.inModel.has(n));

	const add = el('button', {
		className: 'primary', type: 'button', disabled: !fresh.length,
		title: fresh.length
			? 'Adds them to the radionuclide list with their ICRP 107 half-lives, '
				+ 'and replaces the decay pairs between them with the ones worked '
				+ 'out above'
			: 'Nothing new to add',
	}, fresh.length
		? `Add ${fresh.length} nuclide${fresh.length === 1 ? '' : 's'}`
		: 'Add');
	add.addEventListener('click', () => {
		// Held rather than read through `ui`, which the close below clears: what
		// this reports is about the model as it was when Add was pressed.
		const state = ui;
		const list = ed.nuclideList(state.project)?.name ?? ed.NUCLIDE_LIST_NAME;
		try {
			// Names only. The half-lives are the database's already -- it is
			// the model's default now -- and so are the pairs, worked out from
			// whatever the nuclide list ends up holding. Writing either of
			// them down would put a copy in the file that says the same thing
			// and then stops following it.
			const r = ed.applyNuclides(state.project, { names: members });
			// The ceiling goes with the choice: the run collapses the decay
			// pairs with the same one, so what the panel showed is what runs.
			const sim = state.project.simulation ?? (state.project.simulation = {});
			if (Number.isFinite(state.ceiling)) sim.decay_ceiling = state.ceiling;
			else delete sim.decay_ceiling;
			const hooks = state.hooks;
			// A compartment that existed before the radionuclide list did keeps
			// the dimensions it had -- `ensureMaterialList` writes them down
			// first, so that adding a nuclide cannot silently multiply every
			// block in the model by six. Worth saying, because the reader's
			// next question is why their boxes are not per-nuclide.
			const flat = (state.project.compartments ?? [])
				.filter((b) => !(b.index_lists ?? []).includes(list))
				.map((b) => b.name);
			closeModal();
			hooks.onChange?.();
			const pairs = selection().pairs.length;
			hooks.onStatus?.(`Added ${r.added.join(', ')}`
				+ (pairs ? ` — ${pairs} decay pair${pairs === 1 ? '' : 's'} between them` : '')
				+ (r.already.length ? `; ${r.already.length} already in the model` : '')
				+ '.'
				+ (flat.length
					? ` ${flat.length === 1 ? flat[0] : `${flat.length} compartments`} `
						+ `${flat.length === 1 ? 'is' : 'are'} not indexed by ${list} — `
						+ `open ${flat.length === 1 ? 'its' : 'their'} settings to make `
						+ `${flat.length === 1 ? 'it' : 'them'} per-nuclide.`
					: ''), 'info');
		} catch (e) {
			state.hooks.onStatus?.(e.message, 'warn');
		}
	});

	const cancel = el('button', { className: 'ghost', type: 'button' }, 'Cancel');
	cancel.addEventListener('click', () => closeModal());

	const clear = el('button', {
		className: 'ghost', type: 'button', disabled: !ui.picked.size,
		title: 'Untick everything',
	}, 'Clear');
	clear.addEventListener('click', () => {
		ui.picked.clear();
		ui.dropped.clear();
		redraw();
	});

	box.append(el('span', { className: 'np-actions-what' },
		members.length
			? `${fresh.length} to add, ${members.length - fresh.length} already there`
			: ''),
	clear, cancel, add);
	return box;
}

/** Rebuilds the dialog's body in place. */
function redraw() {
	const body = document.querySelector('.modal-body');
	if (!body) return;
	const top = body.scrollTop;
	body.replaceChildren();
	render(body);
	body.scrollTop = top;
}
