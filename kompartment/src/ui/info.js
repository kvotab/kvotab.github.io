/**
 * The Information view: what the selected block is, and what it is joined to.
 *
 * Ecolego's own (`ui.workbench.views.info.InformationTextGenerator`) writes a
 * small HTML page about whatever is selected -- its description, its unit, its
 * equation, the blocks that equation names, the blocks that name it -- and
 * every one of those references is a link (`<a href="ref://ecolego/<id>">`)
 * that moves the selection. `NavigationHistory` beside it gives the back and
 * forward that following links needs.
 *
 * This is that, as elements rather than generated markup. The one thing it is
 * not is an editor: the settings dialog edits, and this reads. Reading is a
 * different job -- when you click `Kd` in an equation you want to *go there*,
 * not to type in it -- and since the rail's property form went away in favour
 * of the tree and this, the title bar carries the door to the dialog.
 */

import * as ed from '../domain/edit.js';
import { systemOf } from '../domain/systems.js';
import { blockIcon } from './icons.js';
import {
	summarise,
	summariseIndexList,
	summariseTable,
	fmtTime,
	describeSharedDims,
} from './summary.js';
import { DEFAULT_SIMULATION, hasDydt } from '../domain/project.js';
import { SOLVER_INFO, solverLabel } from '../ode/solvers.js';
import { symbolNodes } from './symbol.js';
import { hasSymbol, symbolText } from '../domain/symbol.js';
import { section as part } from './parts.js';
import { startValueLine, markStartValue, refreshStartValue } from './startvalue.js';
import { el } from './parts.js';

/**
 * How many references are listed before the list says how many more.
 *
 * This pane has a height of its own and scrolls inside it, so a block read by
 * ninety others is a scroll rather than a wall -- but a list that long is
 * still not a thing anyone reads. The count is always exact; only the naming
 * stops.
 */
const MOST = 12;

/**
 * How many values at the start are printed without being asked for, and how
 * many a request adds.
 *
 * A block is rarely one number -- the median imported block carries 39, one per
 * nuclide or per region -- so the row says the range and this says which index
 * is which. Up to a handful the list is shorter than the sentence explaining
 * that it is hidden, so it is simply there. Past that it is asked for, and past
 * a page of them it arrives a page at a time: the largest block in the corpus
 * carries 1,134 values, and a panel that pours all of them into the rail is a
 * panel you have to scroll past every time you select that block.
 */
const START_ALWAYS = 8;
const START_PAGE = 50;

/** Which block's values are unfolded, and how many of them are on screen. */
let startShown = { name: null, count: 0 };

/** A labelled row: `Unit    Bq`. The label column is fixed, so rows line up. */
const line = (label, ...content) => el('div', { className: 'info-line' },
	el('span', { className: 'info-label' }, label),
	el('span', { className: 'info-value' }, ...content));

/** Whether the section is showing. Remembered across selections. */
let open = true;

/**
 * The diagram's own menu, on a reference.
 *
 * A name in an equation is a block, and the things you want to do to a block
 * are the same wherever you found it -- so a right-click here offers what a
 * right-click on the diagram offers rather than nothing at all. It selects
 * first, as the diagram does, so the panels agree with the menu's title; the
 * one exception is a reference that is already part of a multiple selection,
 * which the graph's own menu keeps whole.
 */
function menuOn(node, name, kind, hooks) {
	if (!hooks.onContextMenu) return;
	node.addEventListener('contextmenu', (ev) => {
		ev.preventDefault();
		ev.stopPropagation();
		hooks.onContextMenu(name, ev, { kind });
	});
}

/** The equation-ish field that says what each kind of block *is*. */
const DEFINING = {
	compartment: ['initial', 'Initial inventory'],
	expression: ['equation', 'Equation'],
	transfer: ['rate', 'Rate'],
	inflow: ['rate', 'Input rate'],
	min_max: ['target', 'Watching'],
	running_mean: ['target', 'Watching'],
	snapshot: ['target', 'Watching'],
	delay: ['target', 'Watching'],
	trigger: ['first', 'First'],
	function: ['equation', 'Body'],
	// A path has no single defining value; its own is the release, which is
	// read off the cells rather than written down. `farfieldInfo` below says
	// what it is instead.
};

/**
 * @param {HTMLElement} host
 * @param {object} project
 * @param {{kind: string, name: string}|null} selection
 * @param {{onSelect?: Function, onOpenSystem?: Function, onBack?: Function,
 *          onForward?: Function, canBack?: boolean, canForward?: boolean}} hooks
 */
export function renderInfo(host, project, selection, hooks = {}) {
	// The pane, kept separately because `host` is reassigned to the card's
	// body further down and the closures up here mean the pane -- a class
	// meant for the rail landed on the body instead, so closing the card left
	// it holding its share of the panel.
	const pane = host;
	pane.replaceChildren();

	// Collapsible and remembered for the session, like the rail's other
	// sections: this is a view you show when you want it, which is how Ecolego
	// treats it too. The class lets the rail give the space back to the tree
	// when it is closed, since a card that is only a title bar should not go
	// on holding half the panel.
	const box = part({
		id: 'information',
		title: 'Information',
		open,
		// Rendered again rather than just hidden, so that opening a card that
		// was closed when the view was built fills it: it used to come back
		// empty, since the body is only written when the card is open.
		onToggle: (on) => { open = on; renderInfo(pane, project, selection, hooks); },
	});
	pane.classList.toggle('is-closed', !open);
	pane.append(box);

	// Back and forward live in the title bar, not in the body: they are the
	// panel's own controls rather than something about the block, and a card
	// with its name and its buttons along the top reads as a view of its own.
	const nav = el('div', { className: 'info-nav' });
	const arrow = (label, title, on, go) => {
		const b = el('button', {
			className: 'ghost info-arrow', type: 'button', disabled: !on, title,
		}, label);
		// A summary swallows clicks to open and close itself.
		b.addEventListener('click', (ev) => { ev.preventDefault(); ev.stopPropagation(); go?.(); });
		return b;
	};
	const action = (label, title, go) => {
		const b = el('button', { className: 'ghost info-act', type: 'button', title }, label);
		b.addEventListener('click', (ev) => { ev.preventDefault(); ev.stopPropagation(); go?.(); });
		return b;
	};
	nav.append(
		arrow('←', 'Back to the block you were reading', hooks.canBack, hooks.onBack),
		arrow('→', 'Forward again', hooks.canForward, hooks.onForward),
	);

	// The way through to the editor. This panel reads a block; everything a
	// block can be given is in the dialog, and with no property form in the
	// rail any more there has to be a door to it from here. A sub-system has
	// no settings to open -- it is a place, not a quantity -- so it offers the
	// other thing you want from one, which is to go inside.
	// Looked up once, and before the title bar rather than after it: what the
	// bar offers and what the body shows are the same decision, and a
	// selection naming a block that has since been deleted has to fall to the
	// same branch in both.
	const found = selection?.name ? ed.findBlock(project, selection.name) : null;
	if (selection?.kind === 'system' && selection.implied) {
		// The diagram is already inside it, so the door offered is the one
		// out: the sub-system around it, or the top level.
		const up = ed.parentOf(selection.name);
		nav.append(action('Up', `Show ${up || 'the top level'} on the diagram`,
			() => hooks.onOpenSystem?.(up)));
	} else if (selection?.kind === 'system' && selection.name) {
		nav.append(action('Open', `Show ${selection.name} on the diagram`,
			() => hooks.onOpenSystem?.(selection.name)));
	} else if (selection?.kind === 'system') {
		// The top level, which is not somewhere to be taken: the same rule the
		// bar follows with nothing selected. A door to a room you are already
		// standing in is worse than no door.
		
	} else if (found) {
		nav.append(action('Edit…',
			'Unit, dimensions, per-index values, appearance and comment. '
			+ 'Double-clicking the block, on the diagram or in the tree, opens the same thing.',
			() => hooks.onOpenSettings?.(selection.name)));
	}
	// With nothing selected there is no `Edit...`. The bar's other two labels
	// each open something that is not already in front of you -- a dialog, a
	// sub-system -- and the model has no dialog: its fields are the left
	// panel, which is on screen the whole time. A button whose only effect is
	// to expand a section that is open by default does nothing at all, and a
	// door to a room you are standing in is worse than no door.
	box.querySelector('summary')?.append(nav);
	// What this view is, behind an (i) at the end of its title bar, where the
	// other sections of the panel keep theirs. See ./infopanel.js.
	if (hooks.info) box.querySelector('summary')?.append(hooks.info());

	// A sibling of the disclosure, not a child of it.
	//
	// This pane has a height and the body is what scrolls inside it, which
	// means the body has to be a flex item of the pane. Inside a `<details>`
	// it is not one: a browser may put a box of its own between the element
	// and its content (Chromium's `::details-content`), and that box does not
	// shrink -- so the body kept its full content height, hung 30 pixels out
	// of the bottom of the card, and scrolled the rail instead of itself.
	// Whether the card is open is a class and a `hidden` here rather than
	// something the element does for us.
	const body = el('div', { className: 'info-body', hidden: !open });
	pane.append(body);
	if (!open) return;
	host = body;

	// A sub-system is not a block, so there is nothing to look up -- but it is
	// the thing selected, and what it holds is exactly what a reader wants.
	if (selection?.kind === 'system') {
		renderSystemInfo(host, project, selection.name, hooks);
		if (selection.implied) {
			host.append(el('p', { className: 'info-none' },
				'The sub-system the diagram is showing. Click a block for its own page, '
				+ 'or Up for the model around it.'));
		}
		return;
	}

	if (!found) {
		renderModelInfo(host, project, hooks);
		return;
	}
	const { block, kind } = found;
	const qname = ed.qualifiedName(block);
	const system = systemOf(block);

	/**
	 * A block, as something you can click to go there.
	 *
	 * Labelled with its symbol wherever it has one -- this is the view for
	 * reading a model, and `¹⁴C` is what the modeller calls that block. The
	 * name it answers to in an equation is in the tooltip, and on the block's
	 * own page as `Named`, so nothing is lost.
	 *
	 * `text` overrides the label with the identifier exactly as an equation
	 * spells it, which is what a reference *without* a symbol should read as:
	 * `S.k` written as a path stays a path.
	 */
	const link = (name, { text = null, icon = true } = {}) => {
		const target = ed.findBlock(project, name);
		if (!target) {
			return el('span', {
				className: 'info-gone', title: `${name} is not in this model`,
			}, text ?? name);
		}
		const b = el('button', {
			className: 'info-link', type: 'button',
			title: hasSymbol(target.block)
				? `${name} — ${target.kind.replace(/_/g, ' ')}, shown as `
					+ `${symbolText(target.block.symbol)}`
				: `${name} — ${target.kind.replace(/_/g, ' ')}`,
		});
		if (icon) b.append(blockIcon(target.kind));
		b.append(el('span', {}, hasSymbol(target.block)
			? symbolNodes(target.block.symbol)
			: [document.createTextNode(text ?? target.block.name)]));
		b.addEventListener('click', () => hooks.onSelect?.({ kind: target.kind, name }));
		menuOn(b, name, target.kind, hooks);
		return b;
	};

	// --- who it is ---------------------------------------------------------
	const shown = el('b', { className: 'info-name' });
	// The name, and what it is shown as after it in brackets: the name is
	// what an equation, the search and the strip call the block, so it leads
	// everywhere the block is listed rather than drawn.
	shown.textContent = block.name;
	if (hasSymbol(block)) {
		shown.append(' (', el('span', { className: 'info-symbol' }, ...symbolNodes(block.symbol)), ')');
	}
	// A part of a transport is called by its part.
	const home = ed.transportOf(project, block);
	const roleKey = home ? ed.transportRole(block) : null;
	const head = el('div', { className: 'info-head' },
		blockIcon(kind), shown,
		el('span', { className: 'info-kind' },
			roleKey ? ed.TRANSPORT_ROLE_LABEL[roleKey].toLowerCase() : kind.replace(/_/g, ' ')));
	// Double-clicking a block opens its settings on the diagram and in the
	// tree, so it does the same here. The name is the block, so the line that
	// carries it is the thing to double-click; the qualified name is still on
	// the `Named` line below for copying.
	if (hooks.onOpenSettings) {
		head.classList.add('is-openable');
		head.title = `Double-click to open ${block.name}'s settings`;
		head.addEventListener('dblclick', (ev) => {
			ev.preventDefault();
			hooks.onOpenSettings(qname);
		});
	}
	host.append(head);

	// Ecolego's `enabled`, off. Said first, because it changes how everything
	// below reads: the equation is there and is not evaluated, the value at
	// the start is not worked out, and a block that reads this one is broken
	// until one of the two changes.
	if (!ed.isEnabled(block)) {
		host.append(el('p', { className: 'info-note info-disabled' },
			'Disabled — kept in the model and left out of the run. Nothing that '
			+ 'is enabled may read it.'));
	} else if (ed.disablingSystem(project, block)) {
		// Off with the sub-system around it, not by its own switch: the switch
		// to find is the sub-system's, so it is named and is a link.
		const by = ed.disablingSystem(project, block);
		const go = el('button', { className: 'info-link', type: 'button', title: `Show ${by}` },
			blockIcon(ed.isTransport(project, by) ? 'transport' : 'system'), el('span', {}, by));
		go.addEventListener('click', () => hooks.onSelect?.({ kind: 'system', name: by }));
		host.append(el('p', { className: 'info-note info-disabled' },
			'Disabled with ', go, ', the sub-system it is in — its own switch is on, '
			+ 'and it comes back when that one does.'));
	} else {
		// Switched off with its compartment, or aimed at one that is: the
		// connection's own switch is on, so the diagram alone would not say.
		const implied = ed.implicitlyDisabled(project);
		const why = implied.get(qname);
		const toOff = implied.get(`${qname}#to`);
		if (why) {
			host.append(el('p', { className: 'info-note info-disabled' },
				`Left out of the run: ${why}.`));
		} else if (toOff) {
			host.append(el('p', { className: 'info-note info-disabled' },
				`Still runs, but ${toOff}.`));
		}
	}

	if (system) {
		const path = el('button', {
			className: 'info-link info-system', type: 'button',
			title: `Show ${system} on the diagram`,
		}, blockIcon('system'), el('span', {}, system));
		path.addEventListener('click', () => hooks.onOpenSystem?.(system));
		host.append(el('div', { className: 'info-line' },
			el('span', { className: 'info-label' }, 'In'),
			el('span', { className: 'info-value' }, path)));
	}

	// The name is already in the title, before the symbol; what this row adds
	// is the qualified spelling, which is what an equation outside the block's
	// own sub-system has to write.
	if (hasSymbol(block) && qname !== block.name) {
		host.append(line('Named', el('code', {}, qname),
			el('span', { className: 'info-dim' }, ' — what equations refer to it by')));
	}

	if (block.comment) host.append(el('p', { className: 'info-comment' }, block.comment));

	// What is wrong with *this* block, before anything about what it is.
	//
	// The problems strip above the tabs lists these for the whole model, and
	// this is the same fact where the reader is already looking: they clicked
	// the block to find out about it, and "this equation will not parse" is
	// the first thing about it. A unit mismatch is a warning further down --
	// the model still runs -- and this is not: nothing runs until it is fixed.
	const broken = ed.allEquationProblems(project, { only: qname });
	for (const p of broken) {
		host.append(el('p', { className: 'info-error' },
			el('b', {}, `${p.field}${p.index
				? ` at ${Object.values(p.index).join(' \u00b7 ')}` : ''}: `),
			p.message));
	}
	// A fault that is not an equation's -- a transport with no End, a flux
	// the loader refuses, a setting the file gate will not take -- reaches
	// the diagram as a mark and reaches here the same way, so the block's
	// page says what its badge says.
	const mark = hooks.marks?.get(qname);
	if (mark?.level === 'error' && !broken.length) {
		host.append(el('p', { className: 'info-error' }, mark.message));
	}

	// --- what it is --------------------------------------------------------
	if (home) {
		const go = el('button', { className: 'info-link', type: 'button', title: home },
			blockIcon('system'), el('span', {}, home));
		go.addEventListener('click', () => hooks.onOpenSystem?.(home));
		host.append(line('Part of', go,
			el('span', { className: 'info-ref-what' }, ed.TRANSPORT_ROLE_BLURB[roleKey])));
		if (roleKey === 'operation') {
			const over = {
				all: 'the whole chain, read by name',
				point: `one position along the chain, called as ${block.name}(0.5)`,
				range: `a stretch of the chain, called as ${block.name}(0, 0.5)`,
			}[block.argument ?? 'all'];
			host.append(line('Works out', `the ${block.operation ?? 'mean'} over ${over}`));
		}
		if (roleKey === 'number') {
			const { n, why } = ed.transportNumber(project, ed.transportParts(project, home));
			host.append(line('Chain', why ? 'length not yet known' : `${n} compartment${n === 1 ? '' : 's'}`));
		}
	}
	const [key, label] = DEFINING[kind] ?? [];
	if (roleKey === 'counter' || roleKey === 'operation') {
		// No equation of its own: the run writes it.
	} else if (kind === 'lookup') {
		host.append(line('Table', summariseTable(block)));
		if (block.argument) {
			host.append(line('Read at', el('code', {}, block.argument)));
		}
	} else if (kind === 'parameter') {
		host.append(line('Value', el('code', {}, String(block.value ?? 0))));
	} else if (key) {
		host.append(el('div', { className: 'info-equation' },
			el('span', { className: 'info-label' }, label),
			el('code', { className: 'info-code' },
				...equationNodes(project, block[key], system, link))));
		for (const w of ed.unitProblems(project, block, kind)) {
			// The field by the name the dialog gives it, where that differs
			// from the key: `dydt` is the "dy/dt term" box.
			const field = w.field === 'dydt' ? 'dy/dt term' : w.field;
			host.append(el('p', { className: 'info-warn' },
				`Units: ${w.field === key ? '' : `${field} `}${w.detail}.`));
		}
		// A discrete event is a comparison, so the other side belongs with it.
		if (kind === 'trigger') {
			host.append(el('div', { className: 'info-equation' },
				el('span', { className: 'info-label' }, 'Second'),
				el('code', { className: 'info-code' },
					...equationNodes(project, block.second, system, link))));
		}
		// A compartment's explicit dy/dt term, when it has one: the part of
		// its rate of change that is neither a transfer nor decay, and the
		// one equation of a compartment that may read the compartment.
		if (kind === 'compartment' && hasDydt(block)) {
			const text = typeof block.dydt === 'string' && block.dydt.trim() ? block.dydt : null;
			host.append(el('div', { className: 'info-equation' },
				el('span', { className: 'info-label' }, 'dy/dt term'),
				text
					? el('code', { className: 'info-code' },
						...equationNodes(project, text, system, link))
					: el('span', { className: 'info-dim' }, 'set per index only')));
		}
	}

	if (kind === 'function') {
		// What it is called with, and what the body may use: a function is
		// handed its arguments and nothing else, so the two are the same list.
		host.append(line('Called as', el('code', {},
			`${block.name}(${(block.parameters ?? []).join(', ')})`)));
		host.append(el('p', { className: 'info-note' },
			`The body may use ${(block.parameters ?? []).length
				? 'those names beside everything else it can see'
				: 'anything it can see'}`
			+ `${systemOf(block) ? ` in '${systemOf(block)}'` : ' in this model'}`
			+ ', and is worked out wherever it is called, at that caller’s index.'));
	}

	if (kind === 'index_reduction' || kind === 'block_reduction') {
		host.append(line('Reduces',
			kind === 'block_reduction'
				? joinLinks((block.targets ?? []), link)
				: (block.target ? link(block.target) : '—'),
			el('span', { className: 'info-dim' }, ` by ${block.operation ?? 'sum'}`)));
	}

	if (kind === 'farfield') {
		// The physics first, then the discretisation: a reader who has clicked
		// on a path wants to know what it transports and how fast, and only
		// then how finely it was divided.
		const states = ed.farfieldStates(project, block);
		host.append(line('Path', el('span', {},
			`${block.n_f} fracture cells, ${block.n_m} matrix layers, `
			+ `${states.states} states`)));
		for (const key of ed.FARF_EQUATION_KEYS) {
			const v = String(block[key] ?? '').trim();
			if (!v) continue;
			const perNuclide = ed.FARF_NUCLIDE_KEYS.includes(key);
			host.append(el('div', { className: 'info-equation' },
				// Written in symbol markup, so rendered rather than printed.
				el('span', { className: 'info-label' },
					...symbolNodes(ed.FARF_LABEL[key])),
				el('code', { className: 'info-code' },
					...equationNodes(project, v, system, link)),
				// Which of them may differ from one nuclide to the next, since
				// that is the thing a reader cannot tell from the value.
				perNuclide && (block.entries ?? []).some((e) => key in e)
					? el('span', { className: 'info-dim' }, ' · and per index below')
					: null));
		}
		host.append(line('Outflow', ed.OUTFLOW_LABEL[block.o_b ?? 1] ?? String(block.o_b)));
		if (Number(block.n_b) > 0) {
			host.append(line('Read', `${block.n_b} cell`
				+ `${Number(block.n_b) === 1 ? '' : 's'} before the far end`));
		}
		const releases = ed.releaseTransfers(project, qname);
		host.append(line('Release',
			releases.length
				? joinLinks(releases.map((t) => t.to).filter(Boolean), link)
				: 'read only — nothing is drawn out of it'));
		const warning = ed.farfieldWarning(project, block);
		if (warning) host.append(el('p', { className: 'info-warn' }, `${warning}.`));
	}

	if (kind === 'waste_package') {
		// What is inside, how it gets out, and where it goes: the three
		// questions a reader clicking on the source term has.
		const states = ed.wasteStates(project, block);
		host.append(line('Packages', el('span', {},
			`${Number(block.packages) > 1 ? `${Number(block.packages).toLocaleString()} packages, ` : ''}`
			+ `${ed.describeWaste({ ...block, packages: 1 })} — ${states.states} states`)));
		const shown = ['inventory', 'irf', 'degradation_rate', ...ed.FAILURE_KEYS[block.failure] ?? []];
		for (const key of shown) {
			const v = String(block[key] ?? '').trim();
			if (!v) continue;
			const perNuclide = ed.WASTE_NUCLIDE_KEYS.includes(key);
			host.append(el('div', { className: 'info-equation' },
				el('span', { className: 'info-label' }, ed.WASTE_LABEL[key]),
				el('code', { className: 'info-code' },
					...equationNodes(project, v, system, link)),
				perNuclide && (block.entries ?? []).some((e) => key in e)
					? el('span', { className: 'info-dim' }, ' · and per nuclide below')
					: null));
		}
		host.append(line('Decay', block.handle_decay === false
			? 'not applied inside the packages' : 'inside the packages too, along the chain'));
		const releases = ed.releaseTransfers(project, qname);
		host.append(line('Release',
			releases.length
				? joinLinks(releases.map((t) => t.to).filter(Boolean), link)
				: 'read only — nothing is drawn out of it, so what leaves has left the model'));
	}

	if (kind === 'event') {
		// When, then what: the two things an event is.
		const timing = ed.timingOf(block);
		host.append(line('Happens', ed.TIMING_LABEL[timing]
			+ (block.sampled === false && timing === 'poisson' ? ' — expected-value form in every realisation' : '')));
		for (const key of ed.TIMING_KEYS[timing]) {
			const v = String(block[key] ?? '').trim();
			if (!v) continue;
			host.append(el('div', { className: 'info-equation' },
				el('span', { className: 'info-label' }, ed.DIS_LABEL[key]),
				el('code', { className: 'info-code' }, ...equationNodes(project, v, system, link))));
		}
		const actions = ed.normaliseActions(block.actions);
		host.append(line('Does', actions.length
			? el('span', {}, ...actions.flatMap((a, k) => [
				k ? el('br') : null,
				a.kind === 'fail'
					? el('span', {}, `fails ${ed.shareText(a.fraction)} of the packages in `, ...(a.block ? [link(a.block)] : ['?']))
					: el('span', {}, `moves ${ed.shareText(a.fraction)} of `, ...(a.from ? [link(a.from)] : ['?']),
						' ', ...(a.to ? ['to ', link(a.to)] : ['out of the model'])),
			]).filter(Boolean))
			: 'nothing but count its occurrences'));
	}

	if (kind === 'transfer' || kind === 'inflow') {
		if (kind === 'transfer') {
			host.append(line('From', block.from ? link(block.from) : 'outside the model'));
		}
		host.append(line('To', block.to ? link(block.to) : 'outside the model'));
		// A flux that does not reach its ends one cell at a time says so here,
		// where the two ends are named: which dimension, and at which end. It
		// is the difference between a number and a total, and reading it off
		// the two endpoint rows means noticing that one of them is missing a
		// dimension, which nobody does.
		const summed = ed.summedFluxDims(project, block);
		if (summed.length) {
			for (const { end, name, dims } of summed) {
				const what = dims.join(' and ');
				host.append(line(end === 'to' ? 'Summed into' : 'Drawn from',
					link(name),
					` has no ${dims.join(' or ')}, so `
					+ (end === 'to'
						? `every ${what} arrives in the one cell`
						: `the one cell pays out once per ${what}`)
					+ (block.sum_extra_indices
						? '.'
						: ' — which this flux has not asked to do, so the model '
							+ 'will not build.')));
			}
		}
	}

	// What the block is worth at the first instant of a run, between what
	// defines it and what it is measured in -- which is the order the three
	// read in: this is the equation, this is what it comes to, this is what
	// that number is. Derived from the project like everything else here: the
	// model is built and evaluated once at `start_time`, never read out of the
	// last run. It arrives a moment after the edit that changed it, because
	// building the model is the expensive half, and writes itself into the row
	// rather than waiting for the next render.
	//
	// Not for a function: it has no value of its own at any instant. What it
	// works out to depends on what it is called with, and the callers are
	// listed further down with the calls they make.
	//
	// Not for a parameter either, for the opposite reason: a parameter *is* a
	// value, it is printed two lines above, and it is the same number at the
	// start as at every other instant. `Value 0.001` followed by `At the start
	// 0.001` is the row read twice.
	if (hooks.atStart && kind !== 'function' && kind !== 'parameter') {
		const values = hooks.atStart(qname);
		const shown = markStartValue(el('span', {}), qname);
		const at = startValueLine(values);
		if (at) { shown.textContent = at.text; shown.title = at.title; }
		// An event's own value is the crossing function rather than a
		// quantity: `First` and `Second` are above, and what the solver
		// watches is the gap between them, which is what its sign says about
		// whether the event is about to fire. Labelled as the difference it
		// is, because "at the start" beside 998 when `First` reads 1000 is a
		// puzzle rather than an answer.
		const row = line(kind === 'trigger' ? 'First − Second' : 'At the start', shown);
		// `1 year`, `0 years` -- the same rule the Runs row uses above.
		const t0 = Number(project.simulation?.start_time ?? 0);
		const tu = project.simulation?.time_unit ?? '';
		row.title = `At t = ${fmtTime(t0)}`
			+ (tu ? ` ${tu}${t0 === 1 ? '' : 's'}` : '')
			+ ', before anything has moved';
		// The row and the values behind it go together: when the model will
		// not build there is nothing to say, and the whole block goes rather
		// than leaving a label with nothing after it.
		const box = el('div', { className: 'info-start' }, row);
		box.dataset.startvalueRow = '';
		box.hidden = !at;
		if (values?.length > 1) {
			box.append(...startValueList(qname, values,
				() => renderInfo(pane, project, selection, hooks)));
		}
		host.append(box);
	}

	const unit = ['transfer', 'inflow'].includes(kind)
		? ed.derivedUnit(project, block, kind)
		: block.unit;
	if (unit) host.append(line('Unit', el('code', {}, unit)));

	// Whether this is a number or something that moves, which is the question
	// a reader of somebody else's model has about every box in it and cannot
	// answer by looking: `Kd * rho / porosity` is three parameters and never
	// changes, and `Kd * Water` is the same shape and changes at every step.
	// The reason names the nearest thing that moves, and links it, so the
	// answer is one click from the block that is really responsible.
	// Not asked of a parameter: a parameter is a constant by definition, so the
	// answer is `Constant` for every one of them and the row says nothing that
	// the word `PARAMETER` at the top has not said already. The question is
	// worth a line exactly where it cannot be answered by looking -- an
	// expression whose shape gives away nothing about whether it moves.
	if (kind !== 'parameter') {
		const how = ed.constancy(project, qname);
		const [before, after] = how.because ? how.why.split('{}') : [how.why, null];
		host.append(line('Over time',
			el('span', {}, how.constant ? 'Constant' : 'Varies'),
			el('span', { className: 'info-dim' }, ' — ', before,
				...(how.because ? [link(how.because), after] : []))));
	}

	const dims = ed.effectiveDims(project, block);
	if (dims.length) {
		const total = ed.combinationCount(project, dims);
		// Every per-index key, not only the block's value: an index with a
		// tolerance of its own, or one that is allowed to go negative when the
		// rest are not, is an index that differs -- and a count that said
		// "none set" about it would be answering a narrower question than the
		// one being asked.
		const set = ed.setIndexes(block, kind);
		host.append(line('Indexed by',
			el('span', {}, dims.join(' × ')),
			el('span', { className: 'info-dim' },
				` — ${total} combination${total === 1 ? '' : 's'}`
				+ `${set.length ? `, ${set.length} set` : ''}`)));
		// A flux does not choose its dimensions -- they are the indices its two
		// ends have in common -- so where they came from is worth a line, and
		// an intersection between two different lists is worth naming.
		const inherited = ['transfer', 'inflow'].includes(kind)
			? describeSharedDims(ed.transferDims(project, block), dims,
				{ from: block.from, to: block.to })
			: '';
		if (inherited) host.append(el('p', { className: 'info-note' }, inherited));
		if (set.length) host.append(overrideList(project, block, kind, dims));
	}

	// --- what it is joined to ----------------------------------------------
	const links = ed.influences(project);
	const reads = [...new Set(links.filter((i) => i.to === qname).map((i) => i.from))];
	const usedBy = ed.referencesTo(project, qname);

	if (reads.length) host.append(refList('Uses', reads, project, link));
	if (usedBy.length) host.append(refList('Used by', usedBy, project, link));
	if (!reads.length && !usedBy.length) {
		host.append(el('p', { className: 'info-none' },
			'Nothing reads this block, and it reads nothing.'));
	}
}

/**
 * The model itself: how big it is, what it is indexed by, and how it will run.
 *
 * This is the view with nothing selected, and it used to be one sentence
 * telling you to select something. But the panel is not idle then -- it is the
 * only place that can describe the *whole* model, which is what anyone wants
 * first from a file they have just opened: how many blocks it has, what
 * dimensions they are indexed by, how long the run is and what solves it.
 * Ecolego splits that across two dialogs you have to open to read --
 * `ProjectPropertiesEditor` for the name and description,
 * `SimulationSettingsEditor` for the run -- and shows neither anywhere else.
 * Here the reading half lives with the rest of the reading, and the editing
 * stays where the editing is: the left panel, which is on screen already.
 *
 * Everything here is derived from the project, never from the last run, so it
 * says the same thing before the first simulation as after it.
 */
function renderModelInfo(host, project, hooks) {
	// The defaults Project itself applies, so this says what would actually
	// run rather than what the file happens to spell out.
	const sim = { ...DEFAULT_SIMULATION, ...(project.simulation ?? {}) };
	const unit = sim.time_unit ?? DEFAULT_SIMULATION.time_unit;

	const head = el('div', { className: 'info-head' },
		blockIcon('system'),
		el('b', { className: 'info-name' }, project.name || 'Untitled project'),
		el('span', { className: 'info-kind' }, 'model'));
	// The gesture a block's head answers to, on the thing this head names --
	// and the one route to editing the model that this card can offer, since
	// what it lands on is a field with the caret in it rather than a section
	// that was already open. Clicking the model's name in the window header
	// does the same thing.
	if (hooks.onEditName) {
		head.classList.add('is-openable');
		head.title = 'Double-click to edit the name and description';
		head.addEventListener('dblclick', (ev) => {
			ev.preventDefault();
			hooks.onEditName();
		});
	}
	host.append(head);

	if (project.description) {
		host.append(el('p', { className: 'info-comment' }, project.description));
	}

	// --- how big it is -----------------------------------------------------
	const all = ed.blocksIn(project, '', { deep: true });
	if (!all.length) {
		host.append(el('p', { className: 'info-none' },
			'Empty. Right-click the diagram to add the first block.'));
	} else {
		// `in all` and the split only where there is a split to report: on a
		// flat model -- most of them -- `13 blocks` is the whole story.
		const top = ed.blocksIn(project, '').length;
		const nested = top !== all.length;
		host.append(line('Holds',
			el('span', {}, `${all.length} block${all.length === 1 ? '' : 's'}`
				+ (nested ? ' in all' : '')),
			nested
				? el('span', { className: 'info-dim' }, ` — ${top} at the top level`)
				: null));

		// What a run costs. Worked out from the model rather than read off the
		// last results, because this view has to be able to say it before
		// anything has run; a test holds it to what the builder lays out.
		const states = ed.stateCount(project);
		host.append(line('States', el('span', {}, String(states)),
			el('span', { className: 'info-dim' }, states
				? ' — what the solver integrates'
				: ' — nothing to integrate, so the blocks are evaluated '
					+ 'straight onto the output grid')));
	}

	// --- how it will run ---------------------------------------------------
	// Before the lists below and grouped under a heading of its own: the pane
	// is short, so the handful of settings anyone opens a strange file to
	// check should be in the first screenful of it, and a card of eight
	// unbroken rows reads as one list of unrelated numbers.
	const scenarios = ed.scenarioNames(project);
	host.append(el('div', { className: 'info-refs' },
		el('div', { className: 'info-label' }, 'Simulation'),
		// Which scenario runs is one of these settings, not a fact about the
		// model: Ecolego runs one simulation per scenario and this tool runs
		// the selected one, reading every scenario-indexed block at that index.
		scenarios.length
			? line('Scenario', el('code', {}, ed.activeScenario(project) ?? '—'),
				el('span', { className: 'info-dim' },
					` — the 1 of ${scenarios.length} a run uses`))
			: null,
		line('Runs',
			el('span', {}, `${fmtTime(sim.start_time)} to ${fmtTime(sim.end_time)} `
				+ `${unit}${sim.end_time === 1 ? '' : 's'}`),
			el('span', { className: 'info-dim' },
				` — ${sim.output_points} points, `
				+ `${sim.spacing === 'linear' ? 'evenly spaced' : 'logarithmic'}`)),
		line('Solver',
			el('span', { title: SOLVER_INFO[sim.solver]?.blurb ?? '' },
				solverLabel(sim.solver)),
			el('span', { className: 'info-dim' }, ` (${sim.solver})`)),
		line('Tolerance',
			el('span', {}, `${fmtTime(sim.rtol)} relative`),
			el('span', { className: 'info-dim' },
				` · ${fmtTime(sim.abstol)} absolute`))));

	// --- what it is indexed by ---------------------------------------------
	const lists = ed.indexLists(project);
	if (lists.length) {
		const box = el('div', { className: 'info-refs' },
			el('div', { className: 'info-label' }, `Index lists (${lists.length})`));
		for (const list of lists) {
			// Enabled indices only, which is what a block indexed by the list
			// actually holds a value for -- and what multiplies into the state
			// count above.
			const size = ed.combinationCount(project, [list.name]);
			const what = `${list.name} — ${summariseIndexList(list)}, `
				+ `${size} ${size === 1 ? 'index' : 'indices'}`;
			let name;
			if (hooks.onOpenIndexList) {
				name = el('button', {
					className: 'info-link', type: 'button',
					title: `${what}. Click to show it on the Index lists tab.`,
				}, el('span', {}, list.name));
				name.addEventListener('click', () => hooks.onOpenIndexList(list.name));
			} else {
				name = el('span', { title: what }, list.name);
			}
			box.append(el('div', { className: 'info-ref' }, name,
				el('span', { className: 'info-ref-what' }, String(size))));
		}
		host.append(box);
	}

	const kinds = kindBreakdown('By kind', all);
	if (kinds) host.append(kinds);
	const inside = childSystemList(project, '', hooks, 'Sub-systems');
	if (inside) host.append(inside);

	// Where the units do not add up. Otherwise a mismatch is only ever found
	// by landing on the block that has it.
	// Handed in by the editor, which has just scanned the model for the
	// problems strip; worked out here only when nothing has.
	const bad = hooks.unitProblems ?? ed.allUnitProblems(project);
	if (bad.length) {
		const go = el('button', { className: 'info-link', type: 'button' });
		go.append(el('span', {}, bad.length === 1
			? '1 block has units that do not add up'
			: `${bad.length} blocks have units that do not add up`));
		go.addEventListener('click', () => {
			const first = ed.findBlock(project, bad[0].name);
			if (first) hooks.onSelect?.({ kind: first.kind, name: bad[0].name });
		});
		host.append(el('p', { className: 'info-warn' }, go));
	}

	host.append(el('p', { className: 'hint' },
		'Select a block to read what it is, what it uses and what uses it. '
		+ 'Every name here is a link.'));
}

/**
 * What a container holds, by kind: `Compartments 12`, `Transfers 30`.
 *
 * In `KIND_LABEL` order rather than in the order the blocks happen to come in,
 * so the same model always reads the same way and the two kinds anyone counts
 * first -- compartments and transfers -- are at the top.
 *
 * @returns {HTMLElement|null} null when there is nothing to count
 */
function kindBreakdown(label, blocks) {
	const byKind = new Map();
	for (const b of blocks) byKind.set(b.kind, (byKind.get(b.kind) ?? 0) + 1);
	if (!byKind.size) return null;
	const box = el('div', { className: 'info-refs' },
		el('div', { className: 'info-label' }, label));
	for (const kind of Object.keys(ed.KIND_LABEL)) {
		const n = byKind.get(kind);
		if (!n) continue;
		box.append(el('div', { className: 'info-ref' },
			blockIcon(kind),
			el('span', {}, ed.KIND_LABEL[kind]),
			el('span', { className: 'info-ref-what' }, String(n))));
	}
	return box;
}

/**
 * The sub-systems directly inside a system, each with what it holds.
 *
 * Shared by the sub-system view and the model view, because the model is the
 * outermost system: `Inside` there and `Sub-systems` here is the same list of
 * the same thing one level down.
 *
 * @returns {HTMLElement|null} null when it has none
 */
function childSystemList(project, path, hooks, label) {
	const children = ed.childSystems(project, path);
	if (!children.length) return null;
	const box = el('div', { className: 'info-refs' },
		el('div', { className: 'info-label' }, `${label} (${children.length})`));
	for (const child of children) {
		const b = el('button', {
			className: 'info-link', type: 'button',
			title: `Show ${child} on the diagram`,
		}, blockIcon('system'), el('span', {}, ed.baseName(child)));
		b.addEventListener('click', () => hooks.onOpenSystem?.(child));
		box.append(el('div', { className: 'info-ref' }, b,
			el('span', { className: 'info-ref-what' },
				String(ed.blocksIn(project, child, { deep: true }).length))));
	}
	return box;
}

/**
 * A sub-system: what is in it, and what crosses its edge.
 *
 * Ecolego treats a sub-system as a block -- it is one -- and
 * its information view lists the contents. The connections in and out are
 * added here because on a model of any size that is the question you actually
 * have about a part: not what is inside it, but what it is joined to.
 */
function renderSystemInfo(host, project, path, hooks) {
	const link = (name) => {
		const target = ed.findBlock(project, name);
		if (!target) return el('span', { className: 'info-gone' }, name);
		const b = el('button', { className: 'info-link', type: 'button', title: name });
		b.append(blockIcon(target.kind));
		// Its symbol where it has one, as everywhere else in this view.
		b.append(el('span', {}, hasSymbol(target.block)
			? symbolNodes(target.block.symbol)
			: [document.createTextNode(target.block.name)]));
		b.addEventListener('click', () => hooks.onSelect?.({ kind: target.kind, name }));
		menuOn(b, name, target.kind, hooks);
		return b;
	};
	// A sub-system has no settings to open -- it is a place, not a quantity --
	// so the same gesture does the thing you do want from one: go inside.
	const transport = ed.isTransport(project, path);
	// The top level is a sub-system with no name: the model itself, which is
	// what clicking the tree's root row or the empty space below its rows
	// selects. `baseName('')` is empty, so it wears the model's own name and
	// is called what it is -- a blank line above the word `sub-system` reads
	// as a sub-system whose name failed to load.
	const root = !path;
	const shead = el('div', { className: `info-head${root ? '' : ' is-openable'}` },
		blockIcon(transport ? 'transport' : 'system'),
		el('b', { className: 'info-name' }, root ? ed.modelName(project) : ed.baseName(path)),
		el('span', { className: 'info-kind' },
			root ? 'the whole model' : transport ? 'transport' : 'sub-system'));
	shead.title = root
		? 'Everything in the model, at every depth'
		: `Double-click to open ${path}`;
	shead.addEventListener('dblclick', (ev) => {
		ev.preventDefault();
		hooks.onOpenSystem?.(path);
	});
	host.append(shead);

	const parent = ed.parentOf(path);
	if (parent) {
		const up = el('button', { className: 'info-link', type: 'button' },
			blockIcon('system'), el('span', {}, parent));
		up.addEventListener('click', () => hooks.onOpenSystem?.(parent));
		host.append(line('In', up));
	}
	// Off, and said first, as it is for a block: it changes how everything
	// below reads. A sub-system is a block too and has a block's switch;
	// one switched off by a sub-system further out names that one.
	if (!ed.isSystemEnabled(project, path)) {
		const own = ed.disabledSystems(project).includes(path);
		const by = own ? null : ed.disablingSystem(project, { system: path });
		host.append(el('p', { className: 'info-note info-disabled' },
			own
				? `Disabled — everything in ${ed.baseName(path)} is kept in the model and `
					+ 'left out of the run. Its blocks keep their own switches, and come back '
					+ 'with it.'
				: `Disabled with ${by}, the sub-system around it.`));
	}
	// A transport runs as a chain: how long, and between which two, and what
	// it is connected to -- which is where its dimensions come from.
	if (transport) {
		const parts = ed.transportParts(project, path);
		const { n, why } = ed.transportNumber(project, parts);
		host.append(line('Chain', why
			? 'length not yet known'
			: `${n} compartment${n === 1 ? '' : 's'}, from `,
		...(why ? [] : [
			parts.begin ? link(ed.qualifiedName(parts.begin)) : 'Begin', ' to ',
			parts.end ? link(ed.qualifiedName(parts.end)) : 'End',
		])));
		if (parts.number) {
			host.append(line('N', link(ed.qualifiedName(parts.number)),
				el('span', { className: 'info-dim' }, ' — how many compartments the chain runs as')));
		}
		const ends = ed.transportEnds(project, path);
		if (ends.from.length || ends.to.length) {
			host.append(line('Fed by', ends.from.length ? joinLinks(ends.from, link) : 'nothing yet'));
			host.append(line('Delivers to', ends.to.length ? joinLinks(ends.to, link) : 'nothing yet'));
			const dims = ed.transportDims(project, path);
			if (dims) {
				host.append(line('Indexed by',
					el('span', {}, dims.dims.length ? dims.dims.join(' × ') : 'nothing'),
					el('span', { className: 'info-dim' }, ' — inherited from what it is connected to, '
						+ 'as a transfer’s are')));
			}
		}
		if (parts.operations.length) {
			host.append(line('Operations', joinLinks(parts.operations.map((o) => ed.qualifiedName(o)), link)));
		}
	}
	// Going inside is in the title bar, beside the history arrows, where a
	// block's way through to its settings is. A row labelled `Open` whose
	// value was a button saying the sub-system's own name said nothing about
	// the sub-system, which is what the rest of this view is for.

	// What is in it, by kind, counting everything beneath it as well as its own.
	const own = ed.blocksIn(project, path);
	const deep = ed.blocksIn(project, path, { deep: true });
	host.append(line('Holds',
		el('span', {}, `${own.length} here, ${deep.length} in all`)));
	const kinds = kindBreakdown('By kind', deep);
	if (kinds) host.append(kinds);
	const inside = childSystemList(project, path, hooks, 'Inside');
	if (inside) host.append(inside);

	// What crosses the edge. A transfer lives with its donor, so one leaving
	// is one held here whose receiver is not, and one arriving is held outside
	// with a receiver in here.
	const within = (name) => name != null && ed.isWithin(ed.parentOf(name), path);
	const out = [];
	const into = [];
	for (const conn of [...(project.transfers ?? []), ...(project.inflows ?? [])]) {
		const name = ed.qualifiedName(conn);
		const from = conn.from ?? null;
		const to = conn.to ?? null;
		if (within(from) && !within(to)) out.push(name);
		else if (!within(from) && within(to)) into.push(name);
	}
	const crossing = (title, names) => {
		if (!names.length) return;
		const box = el('div', { className: 'info-refs' },
			el('div', { className: 'info-label' }, `${title} (${names.length})`));
		for (const name of names.slice(0, MOST)) {
			const found = ed.findBlock(project, name);
			box.append(el('div', { className: 'info-ref' }, link(name),
				el('span', { className: 'info-ref-what' },
					found ? summarise(found.collection, found.block) : '')));
		}
		if (names.length > MOST) {
			box.append(el('div', { className: 'info-ref-more' },
				`and ${names.length - MOST} more`));
		}
		host.append(box);
	};
	// What is wrong inside it, block by block and as links: this is the page
	// you reach on the way down to a fault, and it should say where to go
	// next rather than leave you to open the sub-systems one by one.
	const mark = hooks.marks?.get(path);
	if (mark?.inside?.length) {
		const box = el('div', { className: 'info-crossing' });
		const errors = mark.inside.filter((x) => x.level === 'error').length;
		box.append(el('div', { className: `info-label ${errors ? 'info-error-label' : 'info-warn-label'}` },
			errors
				? `${errors} problem${errors === 1 ? '' : 's'} inside${mark.inside.length > errors
					? `, ${mark.inside.length - errors} warning${mark.inside.length - errors === 1 ? '' : 's'}` : ''}`
				: `${mark.inside.length} warning${mark.inside.length === 1 ? '' : 's'} inside`));
		for (const x of mark.inside.slice(0, 12)) {
			box.append(el('div', { className: `info-fault is-${x.level}` },
				link(x.name), el('span', { className: 'info-dim' }, ` — ${x.message}`)));
		}
		if (mark.inside.length > 12) {
			box.append(el('div', { className: 'info-dim' }, `and ${mark.inside.length - 12} more`));
		}
		host.append(box);
	}
	crossing('Flows out', out);
	crossing('Flows in', into);
	if (!out.length && !into.length && deep.length) {
		host.append(el('p', { className: 'info-none' },
			'Nothing flows across its edge.'));
	}
	if (!deep.length) {
		host.append(el('p', { className: 'info-none' },
			'Empty. Drop a block on it, or add one inside.'));
	}
}

/** The equation, with every block it names turned into a link. */
function equationNodes(project, text, system, link) {
	const segments = ed.equationSegments(project, text, system);
	if (!segments.length) return ['—'];
	return segments.map((seg) => (seg.name
		? link(seg.name, { text: seg.text, icon: false })
		: document.createTextNode(seg.text)));
}

function joinLinks(names, link) {
	const out = [];
	names.forEach((n, i) => {
		if (i) out.push(document.createTextNode(', '));
		out.push(link(n));
	});
	return out.length ? out : ['—'];
}

/**
 * The blocks on the other end of a reference, each with what it is.
 *
 * Ecolego writes the equation and then a table explaining each name in it,
 * which is the half that saves the trip: `Kd` on its own says nothing, `Kd
 * — parameter, 0.01` says whether it is the one you meant.
 */
/**
 * Which indices hold something of their own, and what.
 *
 * The count above says how many; this says which, and in what. An index that
 * differs from the block is the thing you go looking for in the settings
 * dialog, and until now the only way to find it was to open the grid and read
 * down it -- on a model whose nuclide list is fifty long, past forty-nine rows
 * that say nothing.
 */
/**
 * The values behind the one on the row: which index holds which.
 *
 * A page at a time, because the blocks this is worth asking about are the wide
 * ones. `more` re-renders the panel, which is how the card's own fold works.
 *
 * Each row carries its own `data-startvalue-row`, so a row with nothing to say
 * hides itself rather than taking the whole block with it -- and each value is
 * marked, so the rows a `load more` adds keep up with the next edit.
 */
function startValueList(qname, values, more) {
	const total = values.length;
	const all = total <= START_ALWAYS;
	const open = all || startShown.name === qname;
	const count = all ? total
		: Math.min(total, open ? startShown.count || START_PAGE : 0);

	const out = [];
	if (count) {
		const box = el('div', { className: 'info-refs info-start-list' });
		for (const v of values.slice(0, count)) {
			const cell = markStartValue(
				el('span', { className: 'info-ref-what' }), qname, null, v.index,
			);
			const where = (v.index ?? []).join(' \u00b7 ') || 'every index';
			const rowEl = el('div', { className: 'info-ref', title: where },
				el('code', {}, where),
				refreshStartValue(cell, values));
			rowEl.dataset.startvalueRow = '';
			box.append(rowEl);
		}
		out.push(box);
	}
	if (all) return out;

	const buttons = el('div', { className: 'info-start-more' });
	const button = (text, onClick) => {
		const b = el('button', { className: 'info-more', type: 'button' }, text);
		b.addEventListener('click', onClick);
		return b;
	};
	if (!open) {
		buttons.append(button(`show all ${total}`, () => {
			startShown = { name: qname, count: START_PAGE };
			more();
		}));
	} else {
		if (count < total) {
			const next = Math.min(total - count, START_PAGE);
			buttons.append(button(`load ${next} more of ${total}`, () => {
				startShown = { name: qname, count: count + START_PAGE };
				more();
			}));
		}
		buttons.append(button('hide', () => {
			startShown = { name: null, count: 0 };
			more();
		}));
	}
	out.push(buttons);
	return out;
}

function overrideList(project, block, kind, dims) {
	const extras = ed.ENTRY_EXTRA[kind] ?? [];
	const label = (key) => symbolText(
		extras.find((x) => x.key === key)?.label ?? String(key).replace(/_/g, ' '),
	);
	const show = (key, v) => {
		const x = extras.find((e) => e.key === key);
		if (typeof v === 'boolean') return v ? (x?.on ?? 'yes') : (x?.off ?? 'no');
		// A column that is neither a number nor a flag says how it reads: a
		// distribution is an object, and `String(spec)` is `[object Object]`.
		const text = x?.describe ? x.describe(v)
			: (Array.isArray(v) ? v.join(' + ') : String(v));
		return text.length > 34 ? `${text.slice(0, 33)}\u2026` : text;
	};
	const keys = ed.entryKeys(kind);
	const box = el('div', { className: 'info-refs' },
		el('div', { className: 'info-label' }, 'Set per index'));
	const rows = (block.entries ?? [])
		.filter((e) => keys.some((k) => Object.prototype.hasOwnProperty.call(e, k)));
	for (const e of rows.slice(0, MOST)) {
		const where = dims.map((d) => e.index?.[d]).filter(Boolean).join(' \u00b7 ');
		const what = keys
			.filter((k) => Object.prototype.hasOwnProperty.call(e, k))
			.map((k) => `${label(k)} ${show(k, e[k])}`)
			.join(', ');
		box.append(el('div', { className: 'info-ref' },
			el('code', {}, where || 'every index'),
			el('span', { className: 'info-ref-what' }, what)));
	}
	if (rows.length > MOST) {
		box.append(el('div', { className: 'info-ref-more' }, `and ${rows.length - MOST} more`));
	}
	return box;
}

function refList(title, names, project, link) {
	const box = el('div', { className: 'info-refs' },
		el('div', { className: 'info-label' }, `${title} (${names.length})`));
	for (const name of names.slice(0, MOST)) {
		const found = ed.findBlock(project, name);
		const row = el('div', { className: 'info-ref' }, link(name));
		if (found) {
			// Its unit, beside the name: an equation is arithmetic on
			// quantities, and what each one is measured in is the first thing
			// to check when the result's unit looks wrong. A flux's is derived
			// from its ends, as on its own page.
			const kind = ed.SINGULAR[found.collection] ?? found.kind;
			const unit = ['transfer', 'inflow'].includes(kind)
				? ed.derivedUnit(project, found.block, kind)
				: found.block.unit;
			if (unit) row.append(el('code', { className: 'info-ref-unit', title: 'unit' }, unit));
			row.append(el('span', { className: 'info-ref-what' },
				summarise(found.collection, found.block)));
		}
		box.append(row);
	}
	if (names.length > MOST) {
		box.append(el('div', { className: 'info-ref-more' },
			`and ${names.length - MOST} more`));
	}
	return box;
}
