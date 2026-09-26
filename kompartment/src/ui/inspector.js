/**
 * Property panel for the selected block.
 *
 * Stands in for the workbench's properties window. Every field writes straight
 * into the plain project object through src/domain/edit.js, so the graph, the
 * matrix, the JSON tab and this panel are all editing one thing.
 *
 * Equations are checked as they are typed -- parsed, then every name resolved
 * against the model -- because a typo in a rate is otherwise only discovered
 * when the run fails.
 */

import * as ed from '../domain/edit.js';
import {
	qualifiedName,
	systemOf,
	parentOf,
	resolveReference,
} from '../domain/systems.js';
import { shapeNames, shapeLabel } from './shapes.js';
import { section as part } from './parts.js';
import { INTERPOLATIONS, INTERPOLATION_BLURB } from '../domain/lookup.js';
import {
	FARF_HELP,
	FARF_LABEL,
	FARF_TERM,
	OUTFLOW_LABEL,
	OUTFLOW_ORDER,
	CONTINUES,
	SURFACES,
	SURFACE_KEY,
	SURFACE_LABEL,
	FARF_SURFACE_DEFAULTS,
	GRIDS,
	GRID_LABEL,
	FARF_METHODS,
	METHOD_LABEL,
	autoExtraCells,
	isSemiAnalytic,
	surfaceOf,
} from '../domain/farfield.js';
import { pointsBox, sparkPath } from './lookup-editor.js';
import * as qa from '../domain/qa.js';
import { symbolNodes } from './symbol.js';
import { attachCompletion, equationLook } from './complete.js';
import {
	OPERATIONS,
	AGGREGATE_OPERATIONS,
	OPERATION_BLURB,
	operatedList,
} from '../domain/reduce.js';
import { summariseTable, describeSharedDims } from './summary.js';
import { openPDFEditor } from './pdfeditor.js';
import { describePDF } from '../domain/pdf.js';
import {
	uncertaintyOf, makeUncertain, clearUncertainty,
} from '../domain/uncertainty.js';
import * as avail from '../domain/availability.js';
import {
	RECORDER_KINDS,
	RECORDER_BLURB,
	EXTREMES,
	DIRECTIONS,
	DIRECTION_BLURB,
} from '../domain/recorders.js';

/**
 * What the first column of a per-index grid is called, where "value" would be
 * wrong. Only the far-field block: everything else has one value, and that is
 * what "value" means.
 */
// Read off `ENTRY_KEY`, not written out again: the first column *is* whatever
// that says, and naming it separately is how it came to be headed T_w over a
// column of K_d,f values.
const PRIMARY_LABEL = { farfield: FARF_LABEL[ed.ENTRY_KEY.farfield] };
const PRIMARY_TITLE = { farfield: FARF_HELP[ed.ENTRY_KEY.farfield] };

/**
 * Which of the rail's sections start open.
 *
 * Appearance is closed: colour and shape matter when laying a diagram out and
 * never again, so it should not sit between the equation and its values. The
 * choice is remembered for the session and across selections -- someone who
 * opens Appearance is doing a pass of appearance work on several blocks.
 */
const SECTION_OPEN = { entries: true, appearance: false, comment: false };
const sectionState = new Map();

/**
 * At most one call per `ms`, with the last one always made.
 *
 * For a colour picker, which reports every colour the pointer crosses on the
 * way to the one chosen -- hundreds per sweep -- and each report used to run
 * the whole edit pipeline: undo, the scan for problems, every panel redrawn.
 * On a large model that was a diagram that could not keep up with the hand.
 * The picker still previews live; it does so a few times a second.
 */
function throttled(fn, ms) {
	let timer = null;
	let pending = false;
	return () => {
		if (timer) { pending = true; return; }
		fn();
		timer = setTimeout(() => {
			timer = null;
			if (pending) { pending = false; fn(); }
		}, ms);
	};
}

function railSection(id, title, badge = '', badgeTitle = '', fallbackOpen = null) {
	return part({
		id,
		title,
		badge,
		badgeTitle,
		open: sectionState.get(id) ?? fallbackOpen ?? SECTION_OPEN[id] ?? true,
		onToggle: (open) => sectionState.set(id, open),
	});
}

// `validateEquation` moved to ../domain/edit.js, which is where the model-wide
// scan that reports the same problems in the workspace strip has to live.
//
// Imported *and* re-exported, and both halves matter: the re-export is for
// this module's callers, who have always asked for it through the inspector,
// and the import is because this module calls it too. A bare
// `export { x } from '...'` gives the name to importers and not to the module
// itself, so every settings dialog with an equation field in it -- which is
// nine of the twelve block kinds -- threw `validateEquation is not defined`
// halfway through being built and never opened.
import { validateEquation } from '../domain/edit.js';
import { hasDydt } from '../domain/project.js';
import { startValueLine, markStartValue, refreshStartValue } from './startvalue.js';
import { el } from './parts.js';

/**
 * The kinds that need a row of their own to say what they are worth.
 *
 * Most blocks do not. A compartment's value at the start is what its initial
 * inventory works out to, and that line is already under the box it was typed
 * into; so is an expression's, a transfer's and a source's.
 *
 * Nor do the blocks that remember, though it is less obvious: at the first
 * instant a min/max, a running mean and a delay all read their target, and a
 * snapshot reads its own `initial` -- which are the boxes above, so a row here
 * would print the same string twice. A discrete event is the odd one: its own
 * value is `first - second`, which is neither of the two boxes and is not a
 * quantity anybody typed, so it is left to the Information view, where it can
 * be labelled as the difference it is.
 *
 * What is left is the four kinds with no equation of their own -- a table, the
 * two reductions and a far-field path, whose value is a consequence of what
 * they watch -- and a parameter, whose box holds one number while an indexed
 * one has a value per index and the box cannot show them.
 */
const NO_EQUATION_OF_THEIR_OWN = [
	'lookup', 'index_reduction', 'block_reduction', 'farfield', 'waste_package', 'event', 'parameter',
];

export { validateEquation };

/**
 * @param {HTMLElement} host
 * @param {object} project
 * @param {{kind: string, name: string}|null} selection
 * @param {{onChange, onSelect, onStatus}} hooks
 */
/**
 * The block editor, in two sizes.
 *
 * `brief` is the right-hand rail: the block's name, the one or two fields that
 * say what it *is*, and a way through to the rest. Everything a block can
 * carry -- its unit, its dimensions, a value per index, colour, shape, size, a
 * comment -- came to twenty-odd controls in a 300-pixel column, which is a lot
 * to scroll past when all you wanted was to read an equation.
 *
 * The full form is the same function with `brief` off, rendered into a dialog
 * (see ./modal.js), so there is one description of every field rather than two
 * that drift.
 */
export function renderInspector(host, project, selection, hooks = {}, opts = {}) {
	const { brief = true } = opts;
	host.replaceChildren();

	if (!selection) {
		host.append(el('p', { className: 'hint' },
			'Select a block to edit it. Right-click the canvas to add a compartment, '
			+ 'or drag from the dot on a compartment’s right edge to connect it to another.'));
		return;
	}

	// A sub-system is a block in Ecolego's sense, and selecting one on the
	// diagram used to say it no longer existed. It has a name to change and
	// two things you can do to it; what is inside is in the Information view.
	if (selection.kind === 'system') {
		renderSystemPanel(host, project, selection.name, hooks);
		return;
	}

	const found = ed.findBlock(project, selection.name);
	if (!found) {
		host.append(el('p', { className: 'hint' }, 'That block no longer exists.'));
		return;
	}
	const { block, kind } = found;

	/**
	 * A control that belongs to the detailed form.
	 *
	 * In the rail it is simply not built: `brief` is about what is on screen,
	 * not about hiding things behind a disclosure that still takes up a line.
	 */
	const unitProblems = ed.unitProblems(project, block, kind);

	const more = (node) => { if (!brief) host.append(node); };
	/** The same, for a field whose per-index grid goes with it. */
	const moreEntries = (node) => { if (!brief) withEntries(node); };

	const commit = (fn) => {
		try {
			fn();
			hooks.onChange?.();
		} catch (e) {
			hooks.onStatus?.(e.message, 'warn');
			// `opts`, not nothing: the fifth argument defaults to the short
			// rail form, so a refused edit inside the settings dialog redrew
			// the dialog as the rail -- half its fields gone, and the per-index
			// grid with them -- and the only way back was to close and reopen
			// it. The refusal is the ordinary case here: every field that
			// validates goes through this.
			renderInspector(host, project, selection, hooks, opts);
		}
	};

	// --- a labelled row with inline validation --------------------------
	const row = (label, control, { hint, error, warning } = {}) => el('div', { className: 'insp-row' },
		el('label', { className: 'insp-label' }, label),
		control,
		error ? el('p', { className: 'insp-error' }, error) : null,
		!error && warning ? el('p', { className: 'insp-warn' }, warning) : null,
		hint && !error && !warning ? el('p', { className: 'insp-hint' }, hint) : null);

	/**
	 * A value the model derives, shown but not editable.
	 *
	 * An input the user can type into but whose text is overwritten on the
	 * next edit is worse than no field at all, so this says where the value
	 * comes from instead.
	 */
	const derivedField = (label, value, hint) => {
		const shown = el('output', { className: 'insp-derived mono' },
			value || '—');
		return el('div', { className: 'insp-row' },
			el('label', { className: 'insp-label' }, label),
			shown,
			el('p', { className: 'insp-hint' }, hint));
	};

	/**
	 * The unit box, with the model's own opinion of it beside it.
	 *
	 * A unit is a label here: it reaches the chart, the table and the CSV and
	 * takes no part in the arithmetic. What makes it worth helping with is
	 * that the model often knows it while the box is empty -- an expression
	 * over a transfer in 1/year and a compartment in Bq is in Bq/year, and
	 * nothing but the equation knows that -- or the box holds the one thing it
	 * cannot be, which is the other inventory unit.
	 *
	 * Offered as a button, never written in. A unit is the modeller's claim
	 * about what a number means, and the equation only settles the ones it can
	 * reach; filling it in silently would put words in their mouth.
	 */
	const unitRow = () => {
		const input = textField(block.unit ?? '', (v) => {
			block.unit = v.trim();
			hooks.onChange?.();
		});
		const clash = unitProblems.find((w) => w.field === 'unit');
		const suggestion = clash ? null : ed.suggestedUnit(project, block, kind);
		const offer = clash?.expected ?? suggestion?.unit ?? null;
		const box = el('div', { className: 'insp-unit' }, input);
		if (offer) {
			const take = el('button', {
				className: 'insp-link insp-unit-take',
				type: 'button',
				title: clash
					? `Label it ${offer}, the unit this model\u2019s inventories are in`
					: `Label it ${offer}, which is what ${suggestion.from} works out as`,
			}, `use ${offer}`);
			take.addEventListener('click', () => {
				block.unit = offer;
				hooks.onChange?.();
			});
			box.append(take);
		}
		return row('Unit', box, {
			warning: clash ? `Units: ${clash.detail}.` : null,
			// Not in the rail: one line of explanation is worth more than the
			// column it costs only where there is room for it.
			hint: !brief && !clash && suggestion
				? `${suggestion.field === 'equation' ? 'The equation' : `Its ${suggestion.field}`}`
					+ ` works out as ${offer}.`
				: undefined,
		});
	};

	const textField = (value, onCommit, { mono = false, placeholder = '' } = {}) => {
		const input = el('input', {
			type: 'text', value: value ?? '', spellcheck: false, placeholder,
			className: mono ? 'mono' : '',
		});
		input.addEventListener('change', () => onCommit(input.value, input));
		return input;
	};

	// --- name (shared by every kind) -------------------------------------
	// The qualified name is the block's identity everywhere outside this panel;
	// `block.name` is only what is typed in the Name box.
	const qname = qualifiedName(block);
	const system = systemOf(block);

	const nameInput = textField(block.name, (v, input) => {
		const problem = ed.validateName(project, v.trim(), { allow: qname, system });
		if (problem) {
			hooks.onStatus?.(problem, 'warn');
			input.value = block.name;
			return;
		}
		commit(() => ed.renameBlock(project, qname, v.trim()));
		hooks.onSelect?.({ kind, name: system ? `${system}.${v.trim()}` : v.trim() });
	});

	if (brief) {
		// A part of a transport is called by its part: `transport begin`
		// says more about the box than `compartment` does.
		const role = ed.roleLabel(project, block);
		host.append(el('div', { className: 'insp-head' },
			el('span', {
				className: `insp-kind insp-kind-${kind}${role ? ' insp-kind-transport' : ''}`,
			}, role ? role.toLowerCase() : kind)));
	}
	const nameRow = row('Name', nameInput);
	host.append(nameRow);

	// The unit goes in the cell beside the name, whichever kind this is and
	// whether it is typed or worked out. Which of those it is, and what it says
	// about itself, is decided in the kind's own branch far below -- a
	// compartment's is a box with the model's opinion beside it, a transfer's
	// is derived from its donor and the time unit and cannot be typed at all --
	// so the branches put the row here instead of appending it where they
	// build it, and it is moved up once they have all run. The alternative was
	// ten copies of the same decision at the top of the function.
	let unitNode = null;

	// What it is called on screen, when that cannot be its name. A name has to
	// be an identifier -- equations refer to it -- and this domain is written
	// in notation identifiers cannot hold. The row itself is built here, where
	// the field helpers are, and shown under Appearance, which is where the
	// rest of "how this block looks" lives.
	const symbolInput = textField(block.symbol ?? '', (v) => {
		const next = v.trim();
		if (next) block.symbol = next;
		else delete block.symbol;
		hooks.onChange?.();
	});
	const preview = el('span', { className: 'insp-symbol-preview' });
	if (ed.hasSymbol(block)) preview.append(...symbolNodes(block.symbol));
	/**
	 * `Shown as`, in the shape the Appearance panel's own rows take: a label,
	 * a control, and a button that puts the default back.
	 */
	const symbolRows = () => {
		const clear = el('button', {
			className: 'insp-appearance-reset', type: 'button',
			title: ed.hasSymbol(block) ? 'Show it under its name again' : 'Shown under its name',
			disabled: !ed.hasSymbol(block),
		}, '×');
		clear.addEventListener('click', () => {
			delete block.symbol;
			hooks.onChange?.();
		});
		return [
			el('div', { className: 'insp-appearance-row' },
				el('span', {}, 'shown as'),
				el('div', { className: 'insp-symbol' }, symbolInput, preview),
				clear),
			el('p', { className: 'insp-hint' },
				'Left empty it is shown under its name. '
				+ `${ed.SYMBOL_TAGS.map((t) => `<${t}>`).join(' ')} are understood, so `
				+ '<sup>14</sup>C draws as ¹⁴C. Everything else is literal text.'),
		];
	};

	// Which sub-system holds it. Shown only when the model has any, since for
	// most models there is nothing to choose.
	const paths = ed.systems(project);
	const connection = kind === 'transfer' || kind === 'inflow';
	if (paths.length && connection) {
		// A connection is not free to live anywhere: it belongs with its
		// donor, and follows it about. Saying where it is without offering to
		// change it is the honest control -- the choice belongs to the
		// compartment it flows out of.
		const anchor = block.from ?? block.to ?? null;
		more(row('Sub-system', el('div', { className: 'insp-static' },
			system || 'the top level'), {
			hint: block.from
				? `A transfer lives where its donor lives. Move ${block.from} and this `
					+ 'follows.'
				: `This has no donor, so it lives with ${anchor ?? 'what it feeds'}.`,
		}));
	} else if (paths.length) {
		const sel = el('select', {});
		for (const [value, label] of [['', 'the top level'], ...paths.map((x) => [x, x])]) {
			sel.append(el('option', { value, selected: value === system }, label));
		}
		sel.addEventListener('change', () => {
			try {
				const to = ed.moveBlock(project, qname, sel.value);
				hooks.onChange?.();
				hooks.onSelect?.({ kind, name: to });
			} catch (e) {
				hooks.onStatus?.(e.message, 'warn');
				sel.value = system;
			}
		});
		more(row('Sub-system', sel, {
			hint: 'Names are unique inside a sub-system, not across the model.',
		}));
	}

	// --- equation-ish field with live checking ---------------------------
	/**
	 * What this equation works out to at the start of the run, under its box.
	 *
	 * The answer to the question the box itself raises: you have written
	 * `Total_inventory * Leaching_fraction` and what you want to know is what
	 * that *is*. Empty until the values arrive -- working them out means
	 * building the whole model, which happens after the edit rather than
	 * during it -- and it fills itself in without this panel being rebuilt,
	 * which is what keeps the focus in the box you are typing into.
	 */
	const startLine = (key) => {
		if (!hooks.atStart) return null;
		const line = startValueLine(hooks.atStart(qname, key));
		const node = el('p', { className: 'insp-atstart mono' }, line ? line.text : '');
		node.hidden = !line;
		if (line) node.title = line.title;
		return markStartValue(node, qname, key);
	};

	/**
	 * Puts that line into a row, directly under the control.
	 *
	 * `key` is the property the equation was written in, or null for the
	 * block's own value -- which is what a release transfer needs, since its
	 * flux is worked out by the path rather than typed anywhere.
	 */
	const withStartLine = (built, key) => {
		const line = key === undefined ? null : startLine(key);
		if (line) built.insertBefore(line, built.children[2] ?? null);
		return built;
	};

	/**
	 * The parameter carrying a setting's spread, if it has one.
	 *
	 * Reading it fresh each time rather than caching: the panel is rebuilt on
	 * every edit, and the setting may have been pointed somewhere else since.
	 */
	const spreadOf = (key) => {
		const st = uncertaintyOf(project, block, key);
		return st.parameter?.pdf ? st.parameter : null;
	};

	/**
	 * What a setting with a spread says about itself, under its box.
	 *
	 * The parameter's name is in it because that is the name the spread will
	 * be listed under everywhere else -- the probabilistic dialog, the tornado,
	 * *what drove the spread* -- and a reader who meets `Canisters_fail_scale`
	 * in a tornado plot should be able to find its way back here.
	 */
	const spreadNote = (key) => {
		const p = spreadOf(key);
		if (!p) return null;
		return el('b', { className: 'insp-spread-note' },
			`${describePDF(p.pdf)}, sampled as ${p.name}.`);
	};

	/**
	 * The button that puts a spread on a setting.
	 *
	 * A distribution belongs to a parameter -- the sampler, the sensitivity
	 * measures and dy/dp all read `layout.parameters` -- so this makes one.
	 * See ../domain/uncertainty.js for why, and for what it refuses.
	 *
	 * The parameter is made only once a distribution has been chosen. Opening
	 * the editor and pressing Escape leaves the model exactly as it was, which
	 * a reader looking at what a setting could be is entitled to.
	 */
	const spreadButton = (key, label, get) => {
		const p = spreadOf(key);
		const state = uncertaintyOf(project, block, key);
		// A label is usually a string, but a far-field path's is symbol markup
		// already turned into nodes -- `K`, `<sub>d,f</sub>`. Read back as text
		// it is still the name a reader knows the setting by.
		const text = typeof label === 'string'
			? label
			: [].concat(label ?? []).map((x) => x?.textContent ?? String(x ?? '')).join('')
				|| String(key);
		const b = el('button', {
			type: 'button',
			className: `insp-spread${p ? ' is-set' : ''}${state.can ? '' : ' is-off'}`,
			title: p
				? `${describePDF(p.pdf)}\n\nSampled as ${p.name}. Click to edit it or `
					+ 'take it off.'
				: state.can
					? 'Give this a spread for a probabilistic run. It becomes a parameter '
						+ 'of its own, so it can be sampled, ranked in a tornado and '
						+ 'differentiated against.'
					: state.why,
			'aria-label': `Uncertainty of ${text}`,
			'aria-pressed': String(!!p),
		}, '\u00b1');
		b.addEventListener('click', () => {
			const now = uncertaintyOf(project, block, key);
			if (!now.can) {
				hooks.onStatus?.(now.why, 'warn');
				return;
			}
			const shown = String(get?.() ?? block[key] ?? '').trim();
			openPDFEditor({
				spec: now.parameter?.pdf ?? null,
				title: `${block.name} — ${text}`,
				unit: block.unit ?? '',
				value: Number.isFinite(Number(shown)) && shown !== '' ? Number(shown) : null,
				onSave: (next) => commit(() => {
					if (next) {
						const made = makeUncertain(project, block, key, { unit: block.unit });
						made.pdf = next;
					} else {
						clearUncertainty(project, block, key, { referencesTo: ed.referencesTo });
					}
				}),
			});
		});
		return b;
	};

	// `self` lets the equation name the block it belongs to, which only a
	// compartment's dy/dt term may: see SELF_READING_FIELDS in edit.js.
	/**
	 * A box holding an equation.
	 *
	 * `check` and `complete` override how it is read and what it offers, for
	 * the one field whose scope is not the model: a function's body, where the
	 * names are its parameters. Everything else takes the defaults.
	 */
	const equationField = (label, get, set, {
		hint, field = null, title, self = false, check = null, complete = null,
		uncertain = false, placeholder = '',
	} = {}) => {
		const read = check ?? ((text) => validateEquation(project, text, qname, { self }));
		const error = read(get());
		const input = textField(get(), (v) => {
			const problem = read(v);
			set(v);
			hooks.onChange?.({ soft: !!problem });
			if (problem) hooks.onStatus?.(`${block.name}: ${problem}`, 'warn');
		}, { mono: true, placeholder });
		// Names are what an equation is mostly made of, and this model's are
		// neither short nor guessable -- `NearField.Bentoniteinlet.Comp_5`.
		attachCompletion(input, complete ?? equationLook(project, qname, system));
		if (error) input.classList.add('is-invalid');
		// The units the equation works out to, against the unit the block
		// claims. A warning and not an error: it still runs, and it still
		// gives the numbers it always gave -- they may just not be the
		// quantity the label says.
		const clash = field && !error
			? unitProblems.find((w) => w.field === field && !w.index)
			: null;
		if (clash) input.classList.add('is-suspect');
		if (title) input.title = title;
		// A setting that may carry a spread gets the box and the button side by
		// side, because they are two halves of one answer: what it is, and how
		// well it is known.
		const control = uncertain && field
			? el('div', { className: 'insp-eq' }, input, spreadButton(field, label, get))
			: input;
		// Directly under the box rather than after the hint: it is about what
		// is in the box, and the hint is about what may go in it.
		const spreadHint = uncertain && field ? spreadNote(field) : null;
		return withStartLine(row(label, control, {
			error,
			warning: clash ? `Units: ${clash.detail}.` : null,
			hint: spreadHint ? [spreadHint, hint ? ' ' : null, hint] : hint,
		}), field ?? undefined);
	};

	/**
	 * A number that may be left blank, which means "inherit".
	 *
	 * `numberField` insists on a number, which is right for a property the
	 * block always has. A tolerance is not one of those: blank is the normal
	 * state and means the simulation's own setting, so the box shows that
	 * value greyed as its placeholder and clearing it puts the property back
	 * to absent rather than to zero.
	 */
	const optionalNumberField = (label, get, set, { hint, placeholder, refuse } = {}) => {
		const shown = () => (get() == null ? '' : String(get()));
		const input = textField(shown(), (v, node) => {
			const text = v.trim();
			if (!text) {
				set(null);
				hooks.onChange?.();
				return;
			}
			const n = Number(text);
			if (!(n > 0) || !Number.isFinite(n)) {
				hooks.onStatus?.(refuse ? refuse(v) : `'${v}' is not a number`, 'warn');
				node.value = shown();
				return;
			}
			set(n);
			hooks.onChange?.();
		}, { mono: true, placeholder: placeholder == null ? '' : String(placeholder) });
		return row(label, input, { hint });
	};

	// `title` is for the name a setting goes by somewhere else -- the
	// reference implementation's own input name, where the label is a
	// description of the choice instead. On the control rather than the label,
	// so it is there for the asking and nowhere in the way.
	const numberField = (label, get, set, { hint, unit, title } = {}) => {
		const input = textField(String(get()), (v, node) => {
			const n = Number(v);
			if (!Number.isFinite(n) && v.trim() !== 'Infinity') {
				hooks.onStatus?.(`'${v}' is not a number`, 'warn');
				node.value = String(get());
				return;
			}
			set(v.trim() === 'Infinity' ? Infinity : n);
			hooks.onChange?.();
		}, { mono: true });
		if (title) input.title = title;
		return row(unit ? `${label} (${unit})` : label, input, { hint });
	};

	/**
	 * A lookup table's points. The box carries its own preview and its own
	 * error line, because a table is checked as a whole -- one bad line is not
	 * one bad character -- and the panel's single-line error row cannot say
	 * which line it was.
	 */
	const pointsField = (label, get, set, { hint } = {}) => {
		// In the rail a table is its own shape and a count: the box that holds
		// one point per line is the right editor and the wrong size for a
		// 300-millimetre column, and the .eco files here have tables of 4,000
		// points.
		if (brief) {
			const pts = get();
			const line = el('div', { className: 'insp-spark' });
			// With the block's own rule, so the shape in the rail is the shape
			// the model reads -- a step table drawn as a sloping line is a
			// picture of a different table.
			const d = sparkPath(pts, 1, 3, 114, 24, block.interpolation ?? 'linear');
			if (d) {
				const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
				svg.setAttribute('viewBox', '0 0 116 30');
				svg.setAttribute('class', 'insp-spark-line');
				const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
				path.setAttribute('d', d);
				svg.append(path);
				line.append(svg);
			}
			const open = el('button', { className: 'insp-link', type: 'button' },
				summariseTable({ points: pts }));
			open.addEventListener('click', () => hooks.onOpenSettings?.(qname));
			line.append(open);
			return row(label, line, { hint: 'Edit the points under All settings.' });
		}
		const box = pointsBox({
			points: get(),
			onCommit: (pts) => { set(pts); hooks.onChange?.(); },
			onStatus: hooks.onStatus,
			interpolation: block.interpolation ?? 'linear',
		});
		return row(label, box, { hint });
	};

	/**
	 * An aggregate's targets: one block name per line.
	 *
	 * A list rather than a picker because real aggregates are long -- the
	 * largest in the .eco files here reduces 40 blocks -- and because that
	 * makes them pasteable. Each line is checked against the model as it is
	 * typed, so a name that resolves to nothing is visible before the run.
	 */
	const targetsField = (label, get, set, { hint } = {}) => {
		// In the rail, what it reduces rather than a box to retype it in: the
		// largest aggregate in the .eco files here names 40 blocks.
		if (brief) {
			const list = get() ?? [];
			const open = el('button', { className: 'insp-link', type: 'button' },
				`${list.length} block${list.length === 1 ? '' : 's'}`);
			open.addEventListener('click', () => hooks.onOpenSettings?.(qname));
			return row(label, el('div', { className: 'insp-spark' },
				el('span', { className: 'insp-targets mono' },
					list.join(', ') || 'none yet'),
				open));
		}
		const known = new Set(ed.blockNames(project));
		const area = el('textarea', {
			className: 'lk-text mono', rows: 6, spellcheck: false,
			value: (get() ?? []).join('\n'),
			placeholder: 'One block name per line',
		});
		const status = el('p', { className: 'lk-status' });
		const lines = () => area.value.split(/\r?\n/).map((t) => t.trim()).filter(Boolean);
		const describe = () => {
			const list = lines();
			const bad = list.filter(
				(t) => !resolveReference(t, system, (n) => known.has(n)) && t !== qname,
			);
			const self = list.filter((t) => t === qname);
			status.classList.toggle('is-error', !!bad.length || !!self.length);
			status.textContent = self.length
				? `'${qname}' cannot reduce itself`
				: bad.length
					? `not in this model: ${bad.slice(0, 4).join(', ')}`
					+ `${bad.length > 4 ? ` and ${bad.length - 4} more` : ''}`
					: `${list.length} block${list.length === 1 ? '' : 's'}`;
			return !bad.length && !self.length;
		};
		describe();
		area.addEventListener('input', describe);
		area.addEventListener('change', () => {
			if (!describe()) return;
			set(lines());
			hooks.onChange?.();
		});
		return row(label, el('div', { className: 'lk-points' }, area, status), { hint });
	};

	const checkField = (label, get, set, hint) => {
		const input = el('input', { type: 'checkbox', checked: !!get() });
		input.addEventListener('change', () => { set(input.checked); hooks.onChange?.(); });
		return el('div', { className: 'insp-row' },
			el('label', { className: 'insp-check' }, input, label),
			hint ? el('p', { className: 'insp-hint' }, hint) : null);
	};

	/**
	 * Ecolego's own switch, and the one setting every kind of block shares with
	 * every other.
	 *
	 * Off, the block keeps everything it has and is left out of the run. Built
	 * here, where the tick-box helper is, and appended last -- it is the one
	 * answer that is about the whole block rather than about any field of it,
	 * so it belongs at the end of the fields rather than in the middle of
	 * them, where it used to sit between the name and the first thing worth
	 * reading.
	 */
	/**
	 * Where a block's review stands, and the two buttons that move it.
	 *
	 * The status is *computed* rather than stored -- see ../domain/qa.js -- so
	 * this is a reading of the model rather than a field, and it can say
	 * "approved, but `intake` has changed since" without anybody having had to
	 * notice that and write it down.
	 */
	const reviewSection = () => {
		const found = qa.statuses(project);
		const at = found.get(qname) ?? { state: 'none', why: '' };
		const rec = block.qa ?? null;
		const box = railSection('review', 'Review', qa.QA_LABEL[at.state] ?? at.state);

		const line = el('div', { className: `qa-state is-${at.state}` },
			el('b', {}, qa.QA_LABEL[at.state] ?? at.state),
			at.why ? el('span', { className: 'qa-why' }, ` — ${at.why}` ) : null);
		box.append(line);

		if (rec?.history?.length) {
			const last = rec.history[rec.history.length - 1];
			box.append(el('p', { className: 'pdf-note' },
				`${last.status === 'approved' ? 'Approved' : 'Marked for review'}`
				+ `${last.reviewer ? ` by ${last.reviewer}` : ''}`
				+ `${last.at ? ` on ${String(last.at).slice(0, 10)}` : ''}`
				+ `${last.comment ? ` — ${last.comment}` : ''}`));
		}

		const row = el('div', { className: 'qa-buttons' });
		const act = (status) => {
			const who = window.prompt(status === 'approved'
				? 'Approved by — your name, for the record. A comment after a semicolon.'
				: 'Marked for review by — your name. A comment after a semicolon.', '');
			// Cancelling is an answer: nothing is recorded and nothing is said.
			if (who == null) return;
			const [reviewer, ...rest] = String(who).split(';');
			qa.record(block, {
				status,
				reviewer: reviewer.trim(),
				comment: rest.join(';').trim(),
			});
			hooks.onChange?.();
		};
		const approve = el('button', {
			type: 'button', className: 'ghost', disabled: at.state === 'approved',
			title: 'Records that this definition has been read and is right. It '
				+ 'stops counting the moment the block changes, or anything it is '
				+ 'worked out from does.',
		}, 'Approve');
		approve.addEventListener('click', () => act('approved'));
		const unapprove = el('button', {
			type: 'button', className: 'ghost',
			title: 'Marks it as waiting for a review.',
		}, 'Needs review');
		unapprove.addEventListener('click', () => act('review'));
		row.append(approve, unapprove);

		if (rec?.status === 'approved') {
			const lock = el('input', { type: 'checkbox', checked: !!rec.locked });
			lock.addEventListener('change', () => {
				qa.setLocked(block, lock.checked);
				hooks.onChange?.();
			});
			row.append(el('label', { className: 'qa-lock',
				title: 'While it is locked, any change to this block is put back. '
					+ 'The editor says so when it happens.' }, lock, 'Locked'));
		}
		box.append(row);
		return box;
	};

	const enabledRow = () => {
		// Off with the sub-system around it: this switch is on and does
		// nothing on its own, and the hint has to say where the one that
		// matters is.
		const by = ed.disablingSystem(project, block);
		return checkField('Enabled',
			() => ed.isEnabled(block),
			(v) => ed.setBlockEnabled(project, qname, v),
			by
				? `${by}, the sub-system this block is in, is disabled, so the block is out `
					+ 'of the run whatever this says. Enable the sub-system to bring it back.'
				: ed.isEnabled(block)
					? 'Untick to leave this block out of the run. It keeps its equations '
						+ 'and values, and anything still enabled that reads it will say so.'
					: 'Disabled: this block takes no part in the run, and nothing that is '
						+ 'enabled may read it. Its equations are not checked until it is '
						+ 'switched back on.');
	};

	const selectField = (label, value, options, onCommit, { hint, title } = {}) => {
		const sel = el('select', {});
		for (const [v, t] of options) {
			sel.append(el('option', { value: v ?? '', selected: (value ?? '') === (v ?? '') }, t));
		}
		sel.addEventListener('change', () => onCommit(sel.value === '' ? null : sel.value));
		if (title) sel.title = title;
		return row(label, sel, { hint });
	};

	// A link out to the Index lists tab, which is where a list is created,
	// renamed and given its indices. Absent when the host has nowhere to go --
	// the same inspector renders inside the sidebar's entry editor.
	const openLists = (label) => {
		if (!hooks.onOpenIndexList) return null;
		const b = el('button', { type: 'button', className: 'link-btn' }, label);
		b.addEventListener('click', () => hooks.onOpenIndexList());
		return b;
	};

	const compartmentNames = (project.compartments ?? []).map((c) => qualifiedName(c));
	// Both ends of a connection accept a far-field path: a flux goes into its
	// first fracture cell, a release comes out of its last.
	const pathNames = (project.farfields ?? []).map((f) => qualifiedName(f));
	const endpointNames = [...compartmentNames, ...pathNames];
	// Waste packages are a donor and never a target: what leaves them is drawn
	// out as a line, and nothing is delivered into them.
	const wasteNames = (project.waste_packages ?? []).map((w) => qualifiedName(w));
	const fromNames = [...endpointNames, ...wasteNames];
	const hasNuclides = (project.nuclides ?? []).length > 0;
	const dims = block.index_lists ?? [];

	// Dimensions: which index lists this block is indexed by. Changing them
	// changes how many values the block holds, so the count is shown.
	//
	// A far-field path is offered the same lists as a compartment. It used to
	// be offered the radionuclides and nothing else, on the grounds that one
	// block is one migration path -- but a path per landscape object, or per
	// climate, or per waste type, is what these models are made of, and the
	// engine was written for it all along. What it costs is real and is said
	// where it can be seen: the line under these boxes counts the states, and
	// adding a dimension multiplies several hundred of them by its width.
	const allLists = ed.indexLists(project);
	// Only the lists this kind of block can carry at all. A compartment is one
	// of the compartments, so a value per compartment is not a dimension it can
	// have -- and a box for it, greyed with the reason, was a line of the panel
	// spent on something that could never be ticked. Ecolego does not offer
	// them either (the rule for which lists are on offer). What *can* be
	// ticked but not now -- the same dimension as one already ticked -- stays,
	// greyed, with the reason on it: that one changes as the ticks do.
	const offered = allLists.filter((list) => ed.listApplies(list, kind) || dims.includes(list.name));
	// A function is never indexed: it is called, and the index it is worked
	// out at is the caller's. See ../sim/functions.js. Nor is a disruptive
	// event: it acts on whole blocks.
	if (offered.length && kind !== 'function' && kind !== 'event') {
		const box = el('div', { className: 'insp-dims' });
		for (const list of offered) {
			const on = dims.includes(list.name);
			const clash = on ? null : ed.dimensionsClash(project, [...dims, list.name]);
			const why = ed.listAppliesWhy(list, kind) || ed.dimensionsClashWhy(clash);
			const cb = el('input', {
				type: 'checkbox', checked: on, disabled: !!why, title: why,
			});
			cb.addEventListener('change', () => {
				const next = cb.checked
					? [...dims, list.name]
					: dims.filter((d) => d !== list.name);
				try {
					// Attached connections follow their endpoints, and a
					// reduction follows what it reduces; say so rather than
					// let it look like the change did more than asked. Asking
					// `setBlockDimensions` for the list rather than running
					// the same sync again, which had already been done there
					// and so always came back empty.
					const moved = [];
					ed.setBlockDimensions(project, qname, next, { followed: moved });
					hooks.onChange?.();
					if (moved.length) {
						hooks.onStatus?.(
							`${moved.join(', ')} now ${moved.length === 1 ? 'follows' : 'follow'} `
							+ `${block.name}'s dimensions.`, 'info',
						);
					}
				} catch (e) {
					hooks.onStatus?.(e.message, 'warn');
					cb.checked = on;
				}
			});
			const size = list.indices.filter((i) => i.enabled !== false).length;
			box.append(el('label', {
				className: `insp-check insp-dim${why ? ' is-off' : ''}`,
				title: why,
			},
			cb, list.name,
			el('span', { className: 'insp-dim-size' }, `${size}`)));
		}
		const total = dims.reduce((n, d) => {
			const l = offered.find((x) => x.name === d);
			return n * (l ? l.indices.filter((i) => i.enabled !== false).length : 1);
		}, 1);
		// A flux does not choose its dimensions: it is indexed by the indices
		// its two ends have in common, which is what Ecolego's
		// the dimension rule keeps in step and offers no picker for.
		// So the boxes stay -- this tool can narrow a flux onto a sub-set of
		// what its ends share, which Ecolego cannot -- but what it inherits is
		// said above them, so there is nothing to work out and nothing to tick.
		// A part of a transport inherits too: the chain takes its dimensions
		// from what feeds it and what it delivers to, as a transfer does from
		// its two ends, and Begin, End and the operations are the chain's.
		const chain = ed.transportOf(project, block);
		const chainEnds = chain ? ed.transportEnds(project, chain) : null;
		const inherited = ['transfer', 'inflow'].includes(kind)
			? describeSharedDims(ed.transferDims(project, block), dims,
				{ from: block.from, to: block.to })
			: chain && ed.transportDims(project, chain)
				? describeSharedDims(ed.transportDims(project, chain), dims, {
					from: chainEnds.from.join(', ') || null,
					to: chainEnds.to.join(', ') || null,
				})
				: '';
		more(el('div', { className: 'insp-row' },
			el('label', { className: 'insp-label' }, 'Indexed by'),
			box,
			...(inherited ? [el('p', { className: 'insp-hint insp-inherited' }, inherited)] : []),
			el('p', { className: 'insp-hint' },
				// A release out of a far-field path is per nuclide and has no
				// grid: every one of its values is the path's own release, so
				// there is nothing to set individually. A path itself has both
				// kinds -- the chemistry per nuclide, the path once -- so it
				// says which is which rather than counting.
				kind === 'transfer' && ed.isReleaseTransfer(project, block)
					? `One per combination, each of them ${block.from}'s own release. `
						+ `There is nothing to set.`
					: kind === 'farfield'
						? `${total} value(s) for the chemistry -- sorption, diffusion, `
							+ `porosity -- set individually under "Values per index" `
							+ `below. The path's own settings hold one value each.`
						: kind === 'waste_package'
							? `${total} inventor${total === 1 ? 'y' : 'ies'} and instant-release `
								+ `fraction(s), one per index, set under "Values per index" below. `
								+ `How the packages fail and how the waste form degrades hold one `
								+ `value each.`
						: dims.length
							? `${total} value(s): one per combination. Set them `
								+ `individually under "Values per index" below.`
							: 'A single value, shared across every index.'),
			// What the lists *are* is edited on their own tab; here you only
			// choose which of them this block is indexed by.
			openLists('Edit the lists themselves')));
	} else if (kind === 'event') {
		// An event acts on whole blocks: there is no dimension to offer, and
		// nothing to say about the lists.
	} else if (kind === 'farfield') {
		// Nothing to offer: a path may be indexed by any list a compartment
		// may -- the radionuclides, chemical species, objects -- or by
		// nothing, and this model has no list it can carry.
		more(el('p', { className: 'insp-hint insp-noindex' },
			'A far-field path may be indexed by any of the model\u2019s index lists '
			+ '-- the radionuclides, chemical species, landscape objects -- or by nothing, '
			+ 'which is one quantity that does not decay. This model has none to offer. ',
			openLists('Add one on the Index lists tab'),
			' to give the path a dimension.'));
	} else if (allLists.length) {
		// The model has lists, and none of them is one this kind can carry:
		// a compartment in a model whose only lists are made of its blocks.
		more(el('p', { className: 'insp-hint insp-noindex' },
			`None of this model's index lists can index a ${String(kind).replace(/_/g, ' ')}, `
			+ 'so it holds a single value. ',
			openLists('Add one on the Index lists tab'),
			' to give it a nuclide or landscape-object dimension.'));
	} else {
		// No index lists in the model at all. Say so, or the per-index editor
		// looks like it is missing rather than inapplicable.
		more(el('p', { className: 'insp-hint insp-noindex' },
			'This model has no index lists, so every block holds a single value. ',
			openLists('Add one on the Index lists tab'),
			' to give blocks a nuclide or landscape-object dimension.'));
	}

	/**
	 * A block's own value, with its per-index values immediately below.
	 *
	 * The two belong together: the block-level value is the default those
	 * indices inherit, and reading one without the other tells you nothing.
	 * The grid used to sit at the foot of the panel, past the unit, the
	 * the non-negativity flag and the whole appearance section.
	 */
	let entriesPlaced = false;
	const withEntries = (valueRow) => {
		host.append(valueRow);
		if (!dims.length || entriesPlaced) return;
		entriesPlaced = true;
		const total = ed.combinationCount(project, dims);
		if (brief) {
			// A grid of 53 nuclides does not belong in a 300-pixel column. The
			// rail says how much of it has been filled in and opens it.
			const set = ed.setIndexes(block, kind).length;
			// One combination with nothing set is the default itself, and
			// saying so is a row that tells you nothing.
			if (total <= 1 && !set) return;
			const open = el('button', { className: 'insp-link', type: 'button' },
				set ? `${set} of ${total} set` : `${total}, all default`);
			open.addEventListener('click', () => hooks.onOpenSettings?.(qname));
			host.append(el('div', { className: 'insp-row' },
				el('label', { className: 'insp-label' }, 'Values per index'), open));
			return;
		}
		const set = ed.setIndexes(block, kind).length;
		const box = railSection('entries', 'Values per index',
			set ? `${set}/${total} set` : `${total}`,
			set
				? `${set} of ${total} combinations set; the rest use the default above`
				: `${total} combinations, all using the default above`);
		box.append(renderEntryEditor(project, block, kind, dims, hooks,
			{ heading: false }));
		host.append(box);
	};

	// --- per kind ---------------------------------------------------------
	if (kind === 'compartment') {
		// The two ends of a transport chain. Every compartment of the chain
		// starts as Begin says -- `writeGetInitialConditionMethod` reads only
		// Begin's initial condition -- so End's box is shown as what it is.
		const home = ed.transportOf(project, block);
		const role = home ? ed.transportRole(block) : null;
		const chainParts = home ? ed.transportParts(project, home) : null;
		// The two defaults the per-index grid below overrides, in one cell so
		// that they are read as the pair they are: what this compartment
		// starts at, and how closely the solver is asked to follow it. The
		// grid has them in adjacent columns -- VALUE and ABS. TOL. -- and the
		// tolerance used to sit five rows further down, among the flags, where
		// nothing connected the two.
		const defaults = el('div', { className: 'insp-defaults' });
		if (role === 'end') {
			const begin = chainParts.begin;
			defaults.append(derivedField('Initial inventory',
				begin ? String(begin.initial ?? '0') : '—',
				`${begin ? begin.name : 'Begin'}’s. Every compartment of the chain starts `
				+ 'as Begin says; a value written here is not read.'));
		} else {
			defaults.append(equationField(
				dims.length ? 'Initial inventory (default)' : 'Initial inventory',
				() => block.initial,
				(v) => { block.initial = v; },
				{
					field: 'initial',
					// One value however the block is indexed, so a spread on it is
					// one number too. With a nuclide list the box is a default
					// under a grid of per-nuclide values, and a single draw
					// standing for all of them would be a different quantity.
					uncertain: !dims.length,
					// Anything whose value cannot change over the run: it is
					// worked out before any compartment has a value, so it can
					// read parameters and expressions built on them, but not the
					// state, the clock or a table read at it.
					hint: role === 'begin'
						? `Every compartment of the chain starts with this. The counter `
							+ `${chainParts.counter?.name ?? 'i'} numbers them, so `
							+ `if(${chainParts.counter?.name ?? 'i'} == 1, 1, 0) starts the `
							+ 'first alone.'
						: dims.length
							? 'Applies wherever no index has a value of its own. May read '
								+ 'parameters and any expression that does not change over the run.'
							: 'A number, or anything that does not change over the run — a '
								+ 'parameter, or an expression built on parameters.',
				},
			));
		}
		// One tolerance cannot fit a model
		// whose inventories span decades: at 1e-9 Bq a compartment holding
		// 1e12 Bq is being controlled to twenty-one figures it does not have,
		// while a trace daughter really at 1e-8 Bq needs that tolerance to be
		// integrated at all.
		if (!brief) {
			defaults.append(optionalNumberField('Absolute tolerance'
				+ (dims.length ? ' (default)' : ''),
				() => block.abstol ?? null,
				(v) => { if (v == null) delete block.abstol; else block.abstol = v; },
				{
					placeholder: project.simulation?.abstol,
					refuse: (v) => `'${v}' is not a tolerance: a number greater than zero`,
					hint: `Blank uses the simulation’s ${project.simulation?.abstol}. This `
						+ `is the error the solver is allowed on this compartment`
						+ (dims.length ? ', and each index can have its own below.' : '.'),
				}));
		}
		// The compartment's own "dy/dt": a
		// term of the modeller's own, added to the rate of change beside what
		// the transfers and the decay give, and the one field of a
		// compartment that may read the compartment itself. Rare enough that
		// the rail shows it only once it is set; the dialog always offers it.
		if (!brief || hasDydt(block)) {
			const per = project.simulation?.time_unit ?? 'year';
			defaults.append(equationField(
				`dy/dt term${dims.length ? ' (default)' : ''}`,
				() => block.dydt ?? '',
				(v) => {
					const text = String(v ?? '').trim();
					if (text) block.dydt = text;
					else delete block.dydt;
				},
				{
					field: 'dydt',
					self: true,
					hint: `Added to this compartment’s rate of change beside its transfers `
						+ `and decay, in ${block.unit || 'its unit'}/${per}. Blank means none. `
						+ `May read anything, ${block.name} itself included`
						+ (role === 'begin'
							? '; every slice of the chain gets it except End, which has its own.'
							: role === 'end' ? '; End’s own, not Begin’s.' : '.'),
				},
			));
		}
		// The pair goes in together, and the per-index grid follows it -- for
		// an End, which has no default of its own to set, the grid is placed
		// by the fallback further down.
		if (role === 'end') host.append(defaults);
		else withEntries(defaults);
		unitNode = unitRow();
		if (role) {
			more(derivedField('Part of', home, ed.TRANSPORT_ROLE_BLURB[role]));
		}
		// Only where it does something. Decay and ingrowth couple a
		// compartment's states along the radionuclide dimension, so a
		// compartment that is not indexed by one has nothing for them to act
		// on -- and the engine skips it. A checkbox offering to switch on
		// something that would not happen is a promise the model does not keep.
		const decaysAlong = ed.decayDimensionOf(project, block);
		if (decaysAlong) {
			more(checkField('Handle decay and ingrowth',
				() => block.handle_decay !== false,
				(v) => { block.handle_decay = v; },
				`Adds −λC and ingrowth from parents in the chain, along `
				+ `${decaysAlong}.`));
		}
		// The only constraint any solver here applies.
		// On by default because an inventory cannot be negative;
		// worth being able to turn off because a compartment held at zero by
		// the constraint looks like a result and is usually a modelling error
		// being hidden.
		more(checkField('Cannot go negative',
			() => block.non_negative !== false,
			(v) => { block.non_negative = v; },
			'Stops the solver carrying this compartment below zero. Turn it '
			+ 'off to see a negative inventory rather than have it clipped away.'));
	}

	/**
	 * The availability scheme, and whichever fields the chosen one needs.
	 *
	 * One group rather than four loose fields, because three of the five only
	 * mean anything once a scheme is picked and a panel that showed a limit
	 * box on every transfer would be asking a question about all of them.
	 * Picking a scheme redraws the dialog -- `hooks.onChange` runs
	 * `refreshModal` -- so the fields below follow the choice.
	 *
	 * What it costs is said here rather than found out later: an availability
	 * reads the inventory it scales, which makes the equations non-linear, and
	 * ../sim/jacobian.js declines the analytic Jacobian for the whole model
	 * when any transfer carries one.
	 */
	const availabilityFields = () => {
		const box = el('div', { className: 'insp-group' });
		const a = avail.schemeOf(block);
		const scheme = a?.scheme ?? '';
		// Written into the block only when there is something to write: a
		// transfer with `availability: {}` on it would be a scheme nobody
		// chose, saved into the model file and read back as a problem.
		const into = () => (block.availability ??= {});

		box.append(selectField('Availability', scheme,
			[
				['', 'All of it \u2014 the flux is rate \u00d7 inventory (default)'],
				...avail.SCHEMES.map((v) => [v, avail.SCHEME_LABEL[v]]),
			],
			(v) => {
				if (!v) delete block.availability;
				else into().scheme = v;
				hooks.onChange?.();
			},
			{
				hint: `The fraction of what is in ${block.from} this transfer can `
					+ 'move. On the transfer rather than on the compartment, because '
					+ 'a solubility limit holds back what leaches and not what erodes.',
			}));
		if (!a) return box;

		box.append(el('p', { className: 'insp-hint' }, avail.SCHEME_BLURB[scheme]));

		if (scheme === 'limit' || scheme === 'shared_limit') {
			box.append(equationField('Limit',
				() => a.limit ?? '',
				(v) => { into().limit = v; },
				{
					hint: 'How much may travel, as a number or an equation, in the '
						+ `same unit as ${block.from}. Availability is `
						+ 'min(limit \u00f7 amount, 1), so a limit above what is '
						+ 'there scales nothing.',
				}));
		} else {
			box.append(equationField('\u03b1 (top)',
				() => a.top ?? '',
				(v) => { into().top = v; },
				{ hint: 'The top of (amount + \u03b1) \u00f7 (amount + \u03b2).' }));
			box.append(equationField('\u03b2 (bottom)',
				() => a.bottom ?? '',
				(v) => { into().bottom = v; },
				{
					hint: 'The bottom of it. Larger than \u03b1 is the sorption case: '
						+ 'the fraction free to move rises towards 1 as the inventory '
						+ 'grows.',
				}));
		}

		if (avail.isShared(scheme)) {
			const lists = ed.indexLists(project).map((l) => l.name);
			box.append(selectField('Shared over', a.over ?? '',
				[['', 'choose a list\u2026'], ...lists.map((n) => [n, n])],
				(v) => { into().over = v ?? ''; hooks.onChange?.(); },
				{
					hint: 'The amount is summed over a group before the scheme is '
						+ 'applied, so one limit covers the whole group and what moves '
						+ 'keeps the proportions of what is there. A list the donor is '
						+ 'indexed by is one group: '
						+ (dims[0] ?? 'the radionuclide list') + ' shares one limit '
						+ 'among every nuclide. A grouping of it is one group per index: '
						+ 'Elements shares each element’s limit among its isotopes, '
						+ 'which is what an elemental solubility is.',
				}));
			// What is summed. An elemental solubility is about atoms, and in
			// becquerels the isotopes are not counted in atoms.
			const inMol = (project.decay_unit ?? 'Bq') === 'mol';
			box.append(selectField('Summed as', avail.basisOf(a),
				avail.BASES.map((b) => [b, avail.BASIS_LABEL[b]]),
				(v) => {
					if (v === 'moles') into().basis = 'moles'; else delete into().basis;
					hooks.onChange?.();
				},
				{
					hint: inMol
						? 'This model holds its inventories in moles already, so the two '
							+ 'are the same sum.'
						: 'A solubility is a limit on atoms in solution. Summed as '
							+ 'becquerels, a long-lived isotope counts for almost nothing '
							+ 'beside a short-lived one \u2014 at equal activity U-238 is 18,000 '
							+ 'times the atoms of U-234 \u2014 so a limit shared by activity is '
							+ 'a different limit for each isotope. In moles the limit is a '
							+ 'molar amount (mol) and each isotope is converted through its '
							+ 'half-life; a stable isotope has no activity to convert and is '
							+ 'left out.',
				}));
		}

		box.append(checkField('Carry what is held back instead',
			() => !!a.unavailable,
			(v) => { into().unavailable = v; },
			'One minus the availability, for the transfer that moves precisely '
			+ 'what the other one leaves behind \u2014 erosion carrying the '
			+ 'precipitate that leaching cannot.'));

		box.append(el('p', { className: 'insp-hint' },
			'This reads the inventory it scales, so the equations stop being '
			+ 'linear: the run falls back to a numeric Jacobian for the whole '
			+ 'model, which is slower on a large one.'));
		return box;
	};

	if (kind === 'transfer') {
		// A release out of a far-field path: its rate is not a number anybody
		// types, it *is* the flux out of the far end of the path, which the
		// block already works out. Shown rather than offered.
		const release = ed.isReleaseTransfer(project, block);
		// Both ends go through `setConnectionEnd`, which is the same edit the
		// diagram makes when an arrow is dragged onto another block. Setting
		// `block.from` here directly -- which this panel used to do -- looked
		// equivalent and was not: it skipped the endpoint check, so a transfer
		// could be pointed at a block that cannot be one; it skipped the
		// conversion that makes a transfer *out of a far-field path* a release
		// rather than a rate; and it skipped `rehome`, so the transfer stayed
		// in a sub-system its donor had left. Two ways to make the same change
		// is one too many, and the second one was wrong.
		const moveEnd = (end) => (v) => commit(() => {
			const conn = ed.setConnectionEnd(project, qualifiedName(block), end, v);
			// Re-attaching the donor moves the transfer into that donor's
			// sub-system, so the selection has to follow it there.
			const now = qualifiedName(conn);
			if (now !== qname) hooks.onSelect?.({ kind, name: now });
		});
		host.append(selectField('From', block.from,
			[['', 'outside the model'], ...fromNames.map((n) => [n, n])],
			moveEnd('from')));
		host.append(selectField('To', block.to,
			[
				['', 'outside the model'],
				// A release goes to a compartment: one path straight into
				// another would hide where the mass is.
				...(release ? compartmentNames : endpointNames).map((n) => [n, n]),
			],
			moveEnd('to')));
		// An absent flag means donor multiplication is on -- that is what the
		// checkbox below, the engine's defaults and the derived unit all say,
		// so the label for the equation has to agree. Testing `multiply_by_donor`
		// for truth instead read an unset flag as off.
		const byDonor = block.multiply_by_donor !== false;
		if (release) {
			// The one flux nobody typed, and so the one the reader cannot work
			// out from the box: what is in it is the path's name.
			host.append(withStartLine(derivedField('Flux', block.rate,
				`The release out of the far end of ${block.from}, which the path `
				+ `works out from its own cells. There is nothing to set here: a `
				+ `rate that could be edited would be a second answer to a question `
				+ `${block.from} has already answered.`), null));
		} else {
			withEntries(equationField(
				(byDonor ? 'Rate coefficient' : 'Flux')
					+ (dims.length ? ' (default)' : ''),
				() => block.rate,
				(v) => { block.rate = v; },
				{
					field: 'rate',
					hint: byDonor
						? 'Multiplied by the source compartment to give the flux.'
						: 'Used directly as the flux.',
				}));
			// What the box above *means*, as a choice rather than a modifier.
			// It was a tick called "Multiply by donor compartment", which is
			// the mechanism and not the question: a reader deciding between a
			// rate constant and a flux has to know that ticking it changes the
			// unit of the field they have just filled in, and nothing on
			// screen said so. Both readings are named, and each says what it
			// is measured in -- which is the difference the tick was hiding.
			// Each reading's unit is the one the model would derive for it --
			// `derivedUnit` asked of the block with the flag either way, so the
			// two lines cannot drift from what the flux is actually labelled.
			const unitOf = (byDonorThen) => ed.derivedUnit(
				project, { ...block, multiply_by_donor: byDonorThen }, kind,
			);
			const perTime = unitOf(true) || `1/${ed.timeUnit(project)}`;
			const fluxUnit = unitOf(false) || `the donor's unit over ${ed.timeUnit(project)}`;
			host.append(selectField('The rate is',
				byDonor ? 'coefficient' : 'absolute',
				[
					['coefficient', `a rate coefficient, in ${perTime}`],
					['absolute', `an absolute flux, in ${fluxUnit}`],
				],
				(v) => commit(() => {
					if (v === 'coefficient' && block.from == null) {
						hooks.onStatus?.('There is no donor compartment to multiply by, so this '
							+ 'flux can only be absolute.', 'warn');
						return;
					}
					block.multiply_by_donor = v === 'coefficient';
				}),
				{
					hint: byDonor
						? `The flux is this times what ${block.from ?? 'the donor'} holds, so the `
							+ `box above is in ${perTime}.`
						: `The flux is the box above as written, so it is in ${fluxUnit} — nothing `
							+ 'is multiplied by it.',
				}));

			// How much of the donor is actually free to move. Offered only
			// where it means something: it scales an inventory, so there has
			// to be an inventory and the flux has to be a rate against it --
			// the same two conditions `availabilityProblems` refuses on, asked
			// here as *not showing the control* rather than as an error after
			// the fact. See ../domain/availability.js for the four schemes.
			if (!brief && byDonor && block.from) more(availabilityFields());
		}
		if (!brief) {
			unitNode = derivedField('Unit', ed.derivedUnit(project, block, 'transfer'),
				byDonor
					? `A rate coefficient, so 1/${ed.timeUnit(project)}.`
					: release
						? `The path's own value is already an inventory per unit time, so `
							+ `this is ${block.from}'s unit unchanged.`
						: `An absolute flux, so ${block.from ?? block.to ?? 'the compartment'}'s `
							+ `unit over ${ed.timeUnit(project)}. Change it on that compartment.`);
		}
	}

	if (kind === 'expression') {
		// The parts of a transport that are expressions: N is an equation
		// with a job, the counter has none of its own, and an operation is
		// two choices rather than an equation.
		const home = ed.transportOf(project, block);
		const role = home ? ed.transportRole(block) : null;
		if (role === 'number') {
			withEntries(equationField('Number of compartments',
				() => block.equation, (v) => { block.equation = v; }, {
					field: 'equation',
					hint: 'How long the chain is. Worked out before the run starts, so '
						+ 'numbers, parameters and expressions made of those; a fraction '
						+ 'is rounded down.',
				}));
			const { n, why } = ed.transportNumber(project, ed.transportParts(project, home));
			host.append(derivedField('Chain',
				why ? '—' : `${n} compartment${n === 1 ? '' : 's'}`,
				why ?? `The run has ${n} compartment${n === 1 ? '' : 's'} from Begin to End.`));
		} else if (role === 'counter') {
			host.append(derivedField('Value', 'the element number',
				ed.TRANSPORT_ROLE_BLURB.counter));
		} else if (role === 'operation') {
			host.append(selectField('Works out', block.operation ?? 'mean', [
				['mean', 'mean — the average over the compartments'],
				['sum', 'sum — the total over the compartments'],
			], (v) => { block.operation = v ?? 'mean'; hooks.onChange?.(); }));
			host.append(selectField('Over', block.argument ?? 'all', [
				['all', 'the whole chain — read by name'],
				['point', `one position — called, as ${block.name}(0.5)`],
				['range', `a stretch — called, as ${block.name}(0, 0.5)`],
			], (v) => { block.argument = v ?? 'all'; hooks.onChange?.(); }, {
				hint: (block.argument ?? 'all') === 'all'
					? `Other equations refer to it by name, as ${block.name}.`
					: `A position is a fraction of the chain’s length, 0 at Begin and 1 `
						+ `at End. Called, it has no value of its own to refer to by name.`,
			}));
			const begin = ed.transportParts(project, home).begin;
			unitNode = derivedField('Unit', begin?.unit || '—',
				`${begin?.name ?? 'Begin'}’s: an operation over the chain is in the `
				+ 'chain’s unit.');
		} else {
			withEntries(equationField(dims.length ? 'Equation (default)' : 'Equation',
				() => block.equation, (v) => { block.equation = v; }, { field: 'equation' }));
			unitNode = unitRow();
			if (hasNuclides) {
				more(checkField('One value per nuclide',
					() => block.per_nuclide !== false,
					(v) => { block.per_nuclide = v; }));
			}
		}
		if (role) more(derivedField('Part of', home, ed.TRANSPORT_ROLE_BLURB[role]));
	}

	if (kind === 'parameter') {
		withEntries(numberField(
			dims.length ? 'Value (default)' : 'Value',
			() => block.value, (v) => { block.value = v; },
			dims.length
				? { hint: 'Applies wherever no index has a value of its own.' }
				: {},
		));
		// The distribution the value was drawn from. On the block, so that a
		// parameter with no index list has somewhere to keep one at all, and so
		// that an indexed one has a default under its per-index grid -- which
		// is where Ecolego keeps it too: the entry with no index is the
		// parameter's own. See ../domain/pdf.js.
		{
			const spec = block.pdf ?? null;
			const button = el('button', {
				type: 'button',
				className: `insp-pdf${spec ? ' is-set' : ''}`,
				title: spec ? `${describePDF(spec)}\n\nClick to edit or remove it.`
					: 'Click to choose one.',
			}, spec ? describePDF(spec) : 'None — choose\u2026');
			button.addEventListener('click', () => {
				openPDFEditor({
					spec,
					title: block.name,
					unit: block.unit ?? '',
					value: Number.isFinite(Number(block.value)) ? Number(block.value) : null,
					onSave: (next) => {
						if (next) block.pdf = next;
						else delete block.pdf;
						hooks.onChange?.();
					},
				});
			});
			more(row(dims.length ? 'Distribution (default)' : 'Distribution', button, {
				hint: dims.length
					? 'Applies wherever no index has one of its own. A run here is '
						+ 'deterministic and uses the value above; this is what a '
						+ 'probabilistic one would sample.'
					: 'What a probabilistic run would sample. A run here is '
						+ 'deterministic and uses the value above.',
			}));
		}
		unitNode = unitRow();
	}

	if (kind === 'lookup') {
		more(selectField('Interpolation', block.interpolation ?? 'linear',
			INTERPOLATIONS.map((v) => [v, `${v} \u2014 ${INTERPOLATION_BLURB[v]}`]),
			(v) => { block.interpolation = v ?? 'linear'; hooks.onChange?.(); },
			{ hint: 'How the table is read between and beyond its points.' }));

		more(checkField('Repeat the table',
			() => !!block.cyclic,
			(v) => { block.cyclic = v; },
			'Wraps the lookup point back into the table\u2019s own span, so a year '
			+ 'of data can drive a century of simulation.'));

		// Time or an argument. Ecolego's LookupTable.OptionArgument: with an
		// argument the block is no longer a value at all, it is a function
		// other equations call, so the two are one choice rather than two.
		more(selectField('Read at', block.argument ? 'argument' : 'time',
			[['time', 'the simulation clock'], ['argument', 'an argument passed to it']],
			(v) => {
				block.argument = v === 'argument' ? (block.argument || 'X') : null;
				hooks.onChange?.();
			},
			{
				hint: block.argument
					? `Other equations call it: ${block.name}(\u2026). It has no value `
						+ `of its own, so it cannot be referred to by name alone.`
					: `Other equations refer to it by name, as ${block.name}.`,
			}));

		withEntries(pointsField(
			dims.length ? 'Points (default)' : 'Points',
			() => block.points ?? [],
			(pts) => { block.points = pts; },
			{
				hint: dims.length
					? 'One x, y pair per line. Applies wherever no index has a table '
						+ 'of its own.'
					: 'One x, y pair per line \u2014 paste a pair of spreadsheet '
						+ 'columns straight in.',
			},
		));
		unitNode = unitRow();
	}

	if (kind === 'index_reduction' || kind === 'block_reduction') {
		const ops = kind === 'block_reduction' ? AGGREGATE_OPERATIONS : OPERATIONS;
		host.append(selectField('Reduce by', block.operation ?? 'sum',
			ops.map((o) => [o, `${o} \u2014 ${OPERATION_BLURB[o]}`]),
			(v) => { block.operation = v ?? 'sum'; hooks.onChange?.(); }));
		if (kind === 'index_reduction' && block.operation === 'percentile') {
			host.append(numberField('Percentile',
				() => block.percentile ?? 50, (v) => { block.percentile = v; },
				{ hint: 'Between 0 and 100. 50 is the median.' }));
		}
	}

	if (kind === 'index_reduction') {
		// Every block that holds values, since any of them can be reduced.
		const targets = ed.reducibleBlocks(project, { indexed: true })
			.filter((n) => n !== qname);
		host.append(selectField('Reduce', block.target,
			[['', 'nothing yet'], ...targets.map((n) => [n, n])],
			// The dimensions follow the target, as they do in Ecolego: an
			// index operation is its target with one dimension collapsed, and
			// a mismatch is a block that cannot be built.
			(v) => commit(() => ed.setReductionTarget(project, qname, v)),
			{ hint: 'The block whose values are combined. Its dimensions set this block\u2019s.' }));

		// Which of the target's index lists is reduced away follows from the
		// dimensions, so it is shown rather than chosen -- the same rule the
		// engine uses, and the fastest way to see a mismatch.
		const found = block.target ? ed.findBlock(project, block.target) : null;
		const targetDims = found ? ed.effectiveDims(project, found.block) : [];
		const scenarioList = (d) => !!ed.indexLists(project).find(
			(l) => l.name === d)?.for_scenarios;
		const over = operatedList(dims, targetDims, scenarioList);
		more(derivedField('Reduced over', over ?? '—',
			!block.target
				? 'Choose a block above.'
				: over
					? `'${block.target}' is indexed by ${targetDims.join(' \u00d7 ')}; `
						+ `this block keeps ${dims.join(' \u00d7 ') || 'none of them'} and `
						+ `combines over '${over}'.`
					: targetDims.length
						? `This block is indexed by everything '${block.target}' is, so `
							+ `there is nothing left to combine over. Untick one above.`
						: `'${block.target}' holds a single value, so there is nothing `
							+ `to combine.`));
	}

	if (kind === 'block_reduction') {
		withEntries(targetsField(
			dims.length ? 'Blocks (default)' : 'Blocks',
			() => block.targets ?? [],
			(list) => { block.targets = list; },
		));
	}

	if (kind === 'index_reduction' || kind === 'block_reduction') {
		unitNode = unitRow();
	}

	// --- a user-defined function ------------------------------------------
	// Two boxes: what it is called with, and what it works out to. The body
	// is an equation in the parameters alone -- a function is handed its
	// arguments and no model, as a compiled function of loose arguments is --
	// so the completion offers those names and the functions, and nothing
	// from the model that the checker would then refuse.
	if (kind === 'function') {
		const params = () => (block.parameters ?? []).map(String);
		const paramInput = textField(params().join(', '), (v, input) => {
			try {
				ed.setFunctionParameters(project, qname, String(v).split(','));
				hooks.onChange?.();
			} catch (e) {
				hooks.onStatus?.(e.message, 'warn');
				input.value = params().join(', ');
			}
		}, { mono: true, placeholder: 'none' });
		host.append(row('Parameters', paramInput, {
			hint: 'The names the body uses for the values passed in, separated by commas. '
				+ 'Their order is the order the arguments are written in at a call.',
		}));
		const called = `${block.name}(${params().join(', ')})`;
		const body = equationField('Body', () => block.equation ?? '', (v) => {
			block.equation = v;
		}, {
			field: 'equation',
			check: (text) => ed.validateEquation(project, text, qname, {
				locals: new Set(params()),
			}),
			complete: equationLook(project, qname, '', { locals: new Set(params()) }),
			hint: `What ${called} works out to. It may use `
				+ (params().length
					? `${params().join(', ')}, the built-in functions and the model’s other `
						+ 'functions'
					: 'numbers, the built-in functions and the model’s other functions')
				+ ' — not the model’s blocks: pass what it needs in as an argument.',
		});
		host.append(body);
		unitNode = unitRow();
	}

	// --- the blocks that remember -----------------------------------------
	if (RECORDER_KINDS.includes(kind)) {
		const events = ed.discreteEvents(project).filter((n) => n !== qname);
		const eventField = (label, key, hint, always = false) => (always ? host.append.bind(host) : more)(selectField(
			label, block[key] ?? '',
			[['', 'never'], ...events.map((n) => [n, n])],
			(v) => commit(() => { block[key] = v || null; }),
			{ hint: events.length ? hint : 'Add a discrete event first.' },
		));

		if (kind === 'trigger') {
			withEntries(equationField(dims.length ? 'First (default)' : 'First',
				() => block.first, (v) => { block.first = v; }, { field: 'first' }));
			withEntries(equationField(dims.length ? 'Second (default)' : 'Second',
				() => block.second, (v) => { block.second = v; }, { field: 'second' }));
			host.append(selectField('Fires', block.direction ?? 'rising',
				DIRECTIONS.map((d) => [d, `${d} \u2014 ${DIRECTION_BLURB[d]}`]),
				(v) => { block.direction = v ?? 'rising'; hooks.onChange?.(); },
				{
					hint: 'The solver stops at the crossing and starts again from it, '
						+ 'so whatever the event drives happens when it happens.',
				}));
		} else {
			withEntries(equationField(dims.length ? 'Watching (default)' : 'Watching',
				() => block.target, (v) => { block.target = v; },
				{ field: 'target', hint: RECORDER_BLURB[kind] }));
		}

		if (kind === 'min_max') {
			host.append(selectField('Keep the', block.operation ?? 'max',
				EXTREMES.map((o) => [o, o === 'max' ? 'largest value' : 'smallest value']),
				(v) => { block.operation = v ?? 'max'; hooks.onChange?.(); }));
		}
		if (kind === 'delay') {
			withEntries(equationField(dims.length ? 'Delayed by (default)' : 'Delayed by',
				() => block.delay, (v) => { block.delay = v; },
				{
					field: 'delay',
					hint: `In ${ed.timeUnit(project)}. The block reports what it is `
						+ `watching as it was that long ago.`,
				}));
		}
		if (kind === 'snapshot') {
			eventField('Taken at', 'trigger', 'The event that takes the snapshot.', true);
			moreEntries(equationField(dims.length ? 'Before then (default)' : 'Before then',
				() => block.initial, (v) => { block.initial = v; },
				{ field: 'initial', hint: 'What it reads until the event first fires.' }));
		}
		if (kind === 'min_max' || kind === 'running_mean') {
			eventField('Reset at', 'reset_trigger',
				kind === 'min_max'
					? 'Starts the extreme again from whatever is being watched.'
					: 'Starts the mean again from whatever is being watched.');
			eventField('Start at', 'start_trigger',
				'Until this fires, nothing is recorded. Left at "never" it records '
				+ 'from the start of the simulation.');
			eventField('Stop at', 'stop_trigger', 'After this fires, nothing more is recorded.');
		}
		unitNode = unitRow();
	}

	if (kind === 'event') {
		// When, then what. The actions are rows the reader adds, each a kind, a
		// target and a share; the block's own value is its count of occurrences.
		const timing = ed.timingOf(block);
		host.append(derivedField('Value', 'occurrences so far',
			'The block’s own value: the expected number of occurrences in a deterministic '
			+ 'run, the number a realisation drew in a probabilistic one. It is charted under '
			+ 'the block’s name.'));
		host.append(selectField('Happens', timing,
			ed.TIMINGS.map((t) => [t, ed.TIMING_LABEL[t]]),
			(v) => commit(() => { block.timing = v; }),
			{ hint: ed.TIMING_BLURB[timing] }));
		// The settings the timing reads may each carry a spread. The timing
		// itself may not: a Poisson process is already a distribution, over the
		// occurrences within one run, and a second one on top of it would be a
		// different quantity than anyone means. See UNCERTAIN_EXCLUDES.
		for (const key of ed.TIMING_KEYS[timing]) {
			host.append(equationField(ed.DIS_LABEL[key],
				() => block[key], (v) => { block[key] = v; },
				{ field: key, hint: ed.DIS_HELP[key], uncertain: true }));
		}
		if (timing === 'poisson') {
			host.append(checkField('Draw the occurrences in a probabilistic run',
				() => block.sampled !== false,
				(v) => { block.sampled = v; },
				'On, each realisation draws its own occurrence times from the rate, and the '
				+ 'actions happen at those. Off, every realisation keeps the expected-value form '
				+ '— the choice when the question is about the parameters rather than the dice.'));
		}

		// The actions.
		const actions = ed.normaliseActions(block.actions);
		const wastes = (project.waste_packages ?? []).map((w) => qualifiedName(w));
		const list = el('div', { className: 'dis-actions' });
		const write = (rows) => commit(() => { block.actions = rows; });
		actions.forEach((a, k) => {
			const rowEl = el('div', { className: 'dis-action' });
			const kindSel = el('select', { className: 'dis-kind' });
			for (const kd of ed.ACTIONS) kindSel.append(el('option', { value: kd, selected: kd === a.kind }, ed.ACTION_LABEL[kd]));
			kindSel.addEventListener('change', () => {
				const next = actions.map((x, i) => (i === k
					? (kindSel.value === 'fail' ? { kind: 'fail', block: wastes[0] ?? null, fraction: x.fraction }
						: { kind: 'move', from: compartmentNames[0] ?? null, to: null, fraction: x.fraction })
					: x));
				write(next);
			});
			rowEl.append(kindSel);
			if (a.kind === 'fail') {
				const target = el('select', { className: 'dis-target' });
				for (const w of wastes) target.append(el('option', { value: w, selected: w === a.block }, w));
				if (!wastes.length) target.append(el('option', { value: '', selected: true }, 'no waste packages in the model'));
				target.addEventListener('change', () => write(actions.map((x, i) => (i === k ? { ...x, block: target.value || null } : x))));
				rowEl.append(target);
			} else {
				const from = el('select', { className: 'dis-target' });
				for (const c of compartmentNames) from.append(el('option', { value: c, selected: c === a.from }, c));
				from.addEventListener('change', () => write(actions.map((x, i) => (i === k ? { ...x, from: from.value } : x))));
				const to = el('select', { className: 'dis-target' });
				to.append(el('option', { value: '', selected: !a.to }, 'out of the model'));
				for (const c of compartmentNames) to.append(el('option', { value: c, selected: c === a.to }, c));
				to.addEventListener('change', () => write(actions.map((x, i) => (i === k ? { ...x, to: to.value || null } : x))));
				rowEl.append(from, el('span', { className: 'dis-arrow' }, '\u2192'), to);
			}
			const share = el('input', { type: 'text', className: 'dis-share', value: a.fraction, title: ed.ACTION_BLURB[a.kind] });
			share.addEventListener('change', () => write(actions.map((x, i) => (i === k ? { ...x, fraction: share.value } : x))));
			rowEl.append(el('span', { className: 'dis-label' }, 'share'), share);
			const remove = el('button', { type: 'button', className: 'ghost dis-remove', title: 'Remove this action' }, '\u00d7');
			remove.addEventListener('click', () => write(actions.filter((x, i) => i !== k)));
			rowEl.append(remove);
			list.append(rowEl);
		});
		const add = el('button', { type: 'button', className: 'ghost dis-add' }, '+ Action');
		add.title = 'Add something for the event to do: fail a share of some packages, or move a share of a compartment.';
		add.addEventListener('click', () => write([...actions, wastes.length
			? { kind: 'fail', block: wastes[0], fraction: '0.1' }
			: { kind: 'move', from: compartmentNames[0] ?? null, to: null, fraction: '0.1' }]));
		list.append(add);
		host.append(row('Does', list, {
			hint: actions.length ? 'Each row is one thing that happens at every occurrence. A share is a fraction '
				+ 'between 0 and 1, a number or an equation.' : 'Nothing yet: the event only counts its occurrences.',
		}));
	}

	if (kind === 'waste_package') {
		// The source term with its barriers: what is inside, how the packages
		// fail, how the waste form lets go, and where it goes. In that order,
		// because that is the order the mass moves. See ../domain/wastepackage.js.
		const states = ed.wasteStates(project, block);
		host.append(derivedField('States',
			`${states.states} (intact and exposed, ${states.width} per index)`,
			'Two inventories per index -- what is still inside intact packages, and '
			+ 'what the failed ones have exposed -- solved with the rest of the model.'));

		// Where the release goes: a line drawn out of the block, the same edit
		// said in a field, as for a far-field path.
		const releases = ed.releaseTransfers(project, qname);
		host.append(selectField('Release',
			releases[0]?.to ?? '',
			[['', 'read only \u2014 not delivered'], ...endpointNames.map((n) => [n, n])],
			(v) => commit(() => {
				const moved = ed.setRelease(project, qname, v);
				hooks.onStatus?.(moved
					? `What leaves ${block.name} now goes to ${moved.to}.`
					: `${block.name}\u2019s release is read only.`, 'info');
			}),
			{
				hint: `What leaves the packages: the instant release as they fail and the `
					+ `congruent release as the waste form degrades. It is also ${block.name} in `
					+ `any equation, so it can be read whether or not it is delivered; undelivered, `
					+ `it has left the model.`,
			}));

		host.append(numberField('Packages',
			() => block.packages ?? 1,
			(v) => { block.packages = Math.max(1, Math.round(v)); },
			{ hint: 'How many packages the block stands for. The inventory is the total over '
				+ 'all of them; the number is for the reader, and for a realisation that fails '
				+ 'them one by one.' }));

		withEntries(equationField(dims.length ? `${ed.WASTE_LABEL.inventory} (default)` : ed.WASTE_LABEL.inventory,
			() => block.inventory, (v) => { block.inventory = v; },
			{ field: 'inventory', hint: ed.WASTE_HELP.inventory, uncertain: !dims.length }));
		host.append(equationField(dims.length ? `${ed.WASTE_LABEL.irf} (default)` : ed.WASTE_LABEL.irf,
			() => block.irf, (v) => { block.irf = v; },
			{ field: 'irf', hint: ed.WASTE_HELP.irf + (dims.length ? ' A property of the nuclide, so each can have its own below.' : ''), uncertain: !dims.length }));

		// How they fail: the way, then only the settings that way reads.
		const failure = ed.failureOf(block);
		host.append(selectField('Packages fail', failure,
			ed.FAILURES.map((f) => [f, ed.FAILURE_LABEL[f]]),
			(v) => commit(() => { block.failure = v; }),
			{ hint: ed.FAILURE_BLURB[failure] }));
		// When the packages fail is the commonest uncertain thing in the model,
		// so each setting the way of failing reads may carry a spread. The way
		// itself may not: Weibull and the constant rate are already
		// distributions, over the packages. See UNCERTAIN_EXCLUDES.
		for (const key of ed.FAILURE_KEYS[failure]) {
			host.append(equationField(ed.WASTE_LABEL[key],
				() => block[key], (v) => { block[key] = v; },
				{ field: key, hint: ed.WASTE_HELP[key], uncertain: true }));
		}
		// Per index, like the fraction, so the value here is the default --
		// and still one that may carry a spread: a dissolution rate is the
		// commonest uncertain number in a source term, and a distribution on
		// the default applies wherever no index has a value of its own.
		host.append(equationField(dims.length ? `${ed.WASTE_LABEL.degradation_rate} (default)` : ed.WASTE_LABEL.degradation_rate,
			() => block.degradation_rate, (v) => { block.degradation_rate = v; },
			{
				field: 'degradation_rate',
				hint: ed.WASTE_HELP.degradation_rate + (dims.length
					? ' Each index can have its own below — per waste type, say — or read an indexed parameter.'
					: ''),
				uncertain: true,
			}));

		const decaysAlong = ed.decayDimensionOf(project, block);
		if (decaysAlong) {
			host.append(checkField('Handle decay and ingrowth',
				() => block.handle_decay !== false,
				(v) => { block.handle_decay = v; },
				`Decay and ingrowth run inside the packages too, along ${decaysAlong}: a `
				+ 'daughter grown in inside an intact canister is there to be released when it fails.'));
		}
	}

	if (kind === 'farfield') {
		// A whole transport model behind one block, so the panel is organised
		// the way the physics is: what carries the nuclide, what retains it,
		// how far into the rock is modelled, and how finely -- rather than as
		// fourteen fields in the order they happen to be stored.
		const states = ed.farfieldStates(project, block);
		// Per nuclide where the path runs a decay chain; a path of chemical
		// species, or of nothing, has cells per index or just cells.
		const per = ed.decayDimensionOf(project, block) ? ' per nuclide'
			: (block.index_lists ?? []).length ? ' per index' : '';
		// Worked out exactly, the path has no cells: one state for what it
		// holds, and a release that is a convolution rather than a flux out
		// of a last cell.
		const exact = isSemiAnalytic(block);
		host.append(derivedField('States',
			exact ? `${states.states} (what the path holds${per})`
				: `${states.states} (${states.cells} cells${per})`,
			exact
				? 'The path is solved once for the whole run, in the Laplace domain, and '
					+ 'its release is what has flowed in convolved with its response: all '
					+ 'that is left in the state vector is what it holds.'
				: 'The path is solved with the rest of the model, so these are part of '
					+ 'the state vector. A finer grid costs more of them.'));
		// How: on cells with everything else, or exactly. Beside the states,
		// which are what the choice changes.
		host.append(selectField(FARF_TERM.method, exact ? 'semi-analytical' : 'discretized',
			FARF_METHODS.map((m) => [m, METHOD_LABEL[m]]),
			(v) => commit(() => { block.method = v; }),
			{
				hint: exact
					? 'Exact for the path as given, with no cells to refine: the settings '
						+ 'have to stay the same through a run, and the rock goes on past the '
						+ 'release point.'
					: FARF_HELP.method,
			}));

		// Where the release goes is a line drawn out of the block, not a field
		// on it: one mechanism for "this flux goes there", visible on the
		// diagram and in the transfer grid like every other flux.
		// A path has one release, so where it goes is a choice and not a list:
		// pick a compartment, or "read only" to leave the flux to be read by
		// equations and delivered nowhere. Drawing the line on the diagram
		// does the same edit; this is the same thing said in a field, for the
		// case where the compartment is off screen.
		const releases = ed.releaseTransfers(project, qname);
		const releaseRow = selectField('Release',
			releases[0]?.to ?? '',
			[['', 'read only — not delivered'], ...compartmentNames.map((n) => [n, n])],
			(v) => commit(() => {
				const moved = ed.setRelease(project, qname, v);
				hooks.onStatus?.(moved
					? `${block.name}\u2019s release now goes to ${moved.to}.`
					: `${block.name}\u2019s release is read only.`, 'info');
			}),
			{
				hint: `The flux out of the far end. It is also ${block.name} in any `
					+ `equation, so it can be read whether or not it is delivered.`,
			});

		// The flow-wetted surface, given one of three ways -- F, the wetted
		// surface per volume of water, or the fracture aperture -- and the other
		// two worked out beside the choice: the one reading that says what the
		// numbers mean together. Switching keeps the path the same where the
		// numbers allow it: the new setting starts at what the old one said.
		const surface = surfaceOf(block);
		const surfaceRow = selectField(FARF_TERM.surface, surface,
			SURFACES.map((k) => [k, SURFACE_LABEL[k]]),
			(v) => commit(() => {
				const key = SURFACE_KEY[v];
				if (block[key] == null || block[key] === '') {
					block[key] = sameSurface(block, v) ?? FARF_SURFACE_DEFAULTS[key];
				}
				block.surface = v;
			}),
			{ hint: surfaceReading(block) });

		// The labels are written in symbol markup -- `K<sub>d,f</sub>` -- so
		// they are rendered rather than printed. See FARF_LABEL.
		const label = (key, suffix = '') => symbolNodes(FARF_LABEL[key] + suffix);

		// The path: one value each, however many nuclides travel along it.
		const single = (key) => equationField(label(key),
			() => block[key], (v) => { block[key] = v; },
			{ field: key, hint: FARF_HELP[key], uncertain: true });
		// The chemistry: a property of the nuclide, so one value per nuclide.
		const perNuclide = (key) => equationField(
			label(key, dims.length ? ' (default)' : ''),
			() => block[key], (v) => { block[key] = v; },
			{
				field: key,
				uncertain: !dims.length,
				hint: `${FARF_HELP[key]}${dims.length
					? ' — a property of what travels, the nuclide or the species, so each '
						+ 'can have its own below.'
					: ''}`,
			},
		);
		// Whichever of the three the path gives.
		const surfaceValue = single(SURFACE_KEY[surface]);

		// Ten settings in one narrow column is a scroll; in two it is a block
		// of five rows that can be read at a glance. Paired by what they are
		// about rather than by storage order: the release and how the wetted
		// surface is given at the top, then the water's travel beside the
		// surface it travels over, then each retention term beside the number
		// it is read against.
		//
		//   Release                 Flow-wetted surface given as
		//   T_w                     F (or a_w, or δ)
		//   K_d,f (default)         P_e
		//   ε_m   (default)         ρ_m
		//   K_d,m (default)         D_e,m (default)
		//
		// Laid out by the dialog's own two-column grid rather than by a grid
		// of its own: the rows are appended in reading order and the browser
		// pairs them. A nested grid inside one column of that one gets half
		// the width and lays five rows out in a single file, which is what a
		// first attempt at this did.
		//
		// The first row is pinned to column one -- see `insp-farf-start` --
		// because where the pairing begins would otherwise depend on how many
		// fields happen to precede it, and one more field above would shift
		// every pair by one.
		releaseRow.classList.add('insp-farf-start');
		const rows = [
			releaseRow, surfaceRow,
			single('tw'), surfaceValue,
			perNuclide('kd_f'), single('pe'),
			perNuclide('eps_m'), single('rho_m'),
			perNuclide('kd_m'),
		];
		for (const r of rows) host.append(r);
		// The per-index grid goes under the whole block: the four nuclide
		// settings are spread across both columns, so it hangs off the last of
		// them rather than the first, and the section spans the full width.
		withEntries(perNuclide('de_m'));

		// Worked out exactly there is nothing to discretise: how far the rock
		// goes is physics, and the outlet is the one the solution has.
		if (exact) {
			const depth = equationField(FARF_TERM.pen_dep,
				() => block.pen_dep, (v) => { block.pen_dep = v; },
				{ field: 'pen_dep', uncertain: true, hint: FARF_HELP.pen_dep });
			depth.classList.add('insp-farf-start');
			host.append(depth);
			host.append(derivedField(FARF_TERM.o_b, 'The rock goes on past the release point',
				'The outlet the exact solution has: dispersion carries on past the point '
				+ 'where the release is measured. Worked out on cells, the block offers the '
				+ 'others.'));
		}

		// The discretisation, which is numerics rather than physics.
		const grid = exact ? null : railSection('farf-grid', 'Discretisation',
			`${block.n_f} × ${block.n_m}`,
			'How finely the path is divided. Numerics rather than physics: a '
			+ 'finer grid is a better answer and a slower one.');
		const intoGrid = (node) => grid?.append(node);
		if (!exact) {
			// Labelled by what each one is, not by what the reference
			// implementation calls it: `PENDEP`, `NF`, `OB` are input names, and a
			// panel headed by them reads as a listing of variables rather than as
			// a set of choices. The reference name is on the field's tooltip, for
			// anyone cross-checking against the SKB reports. See FARF_TERM.
			const asks = (key) => ({
				hint: FARF_HELP[key],
				title: `${ed.symbolText(FARF_LABEL[key])} in the reference implementation`,
			});
			// How the layers are laid out: matched to diffusion into the rock, or
			// the reference implementation's own, kept for the models built on it.
			const layout = block.grid === 'matched' ? 'matched' : 'reference';
			intoGrid(selectField(FARF_TERM.grid, layout,
				GRIDS.map((g) => [g, GRID_LABEL[g]]),
				(v) => commit(() => { block.grid = v; }),
				{
					hint: layout === 'matched'
						? 'A geometric series from a first layer worked out from the path’s '
							+ 'own time scales, every nuclide on it at once, with each node placed '
							+ 'so that the rock takes up what exact diffusion would. Laid out at '
							+ 'the start of each run and held to its end.'
						: 'Layers growing by e from the first, nodes at their centres: the '
							+ 'reference implementation’s, which takes up about 6 % too little '
							+ 'where its layers are coarse. Kept so that models built on it run '
							+ 'as they did.',
				}));
			for (const key of ['pen_dep', 'pen_dep_0']) {
				intoGrid(equationField(FARF_TERM[key],
					() => block[key], (v) => { block[key] = v; },
					{
						field: key,
						uncertain: true,
						...asks(key),
						...(key === 'pen_dep_0' ? { placeholder: 'auto' } : {}),
					}));
			}
			for (const key of ['n_f', 'n_m']) {
				intoGrid(numberField(FARF_TERM[key],
					() => block[key], (v) => commit(() => { block[key] = Math.round(Number(v)); }),
					asks(key)));
			}
			// The numbers are what the model stores and what a report cites; they
			// are not a choice anybody makes by number, so the choice is the words.
			intoGrid(selectField(FARF_TERM.o_b, String(block.o_b ?? 1),
				OUTFLOW_ORDER.map((o) => [String(o), OUTFLOW_LABEL[o]]),
				(v) => commit(() => { block.o_b = Number(v); }),
				{
					...asks('o_b'),
					...(Number(block.o_b) === CONTINUES ? {
						hint: 'The rock does not stop where the release is measured: a few of its '
							+ 'cells past that point say how the water beyond pushes back, and the '
							+ 'release is the flux across the plane between them.',
					} : {}),
				}));
			// Extra cells past the release point: a count, or empty to have it
			// worked out -- which, for the rock that goes on, is as many as the
			// push back upstream needs, and otherwise none.
			{
				const continues = Number(block.o_b) === CONTINUES;
				const auto = continues ? autoExtraCells(block.n_f, block.pe) : 0;
				const peNumber = Number.isFinite(Number(block.pe)) && Number(block.pe) > 0;
				const shown = () => (block.n_b === '' || block.n_b == null ? '' : String(block.n_b));
				const input = textField(shown(), (v, node) => {
					const text = v.trim();
					if (!text) {
						commit(() => { block.n_b = ''; });
						return;
					}
					const n = Number(text);
					if (!Number.isInteger(n) || n < 0) {
						hooks.onStatus?.(`'${v}' is not a whole number of cells`, 'warn');
						node.value = shown();
						return;
					}
					commit(() => { block.n_b = n; });
				}, { mono: true, placeholder: `auto: ${auto}` });
				input.title = `${ed.symbolText(FARF_LABEL.n_b)} in the reference implementation`;
				intoGrid(row(FARF_TERM.n_b, input, {
					hint: continues
						? `${FARF_HELP.n_b}. Empty works it out from the fracture cells and the `
							+ `Peclet number${peNumber ? '' : ', taken as 10 while it is an equation'}.`
						: FARF_HELP.n_b,
				}));
			}
			intoGrid(checkField('Report every cell',
				() => !!block.report_cells,
				(v) => { block.report_cells = v; },
				`${FARF_HELP.report_cells} — ${states.states} more series for this block, `
				+ 'so it is off until it is wanted. The total it holds is always reported.'));
			more(grid);
		}

		// Decay runs in every cell of the path, as it does in a compartment,
		// and can be turned off for the same reason.
		more(checkField('Handle decay and ingrowth',
			() => block.handle_decay !== false,
			(v) => { block.handle_decay = v; },
			FARF_HELP.handle_decay));

		const problem = ed.structureProblem(block) ?? ed.geometryProblem(block);
		if (problem) host.append(el('p', { className: 'insp-error' }, `${problem}.`));
		if (!problem) {
			// Two independent things can be worth saying: where the release
			// goes, and whether the grid disperses more than the Peclet number
			// asks for. Neither is an error -- the model runs, and gives the
			// numbers it gives.
			for (const warning of [
				ed.farfieldWarning(project, block),
				ed.dispersionWarning(block),
			]) {
				if (!warning) continue;
				host.append(el('p', { className: 'insp-warn' },
					`${warning[0].toUpperCase()}${warning.slice(1)}.`));
			}
		}

		if (!brief) {
			unitNode = derivedField('Unit', block.unit,
				'The release is an inventory per unit time, like a source term.');
		}
	}

	if (kind === 'inflow') {
		// The same route as a transfer's ends, and for the same reasons: the
		// endpoint check, and the move into the target's sub-system.
		host.append(selectField('Into', block.to,
			compartmentNames.map((n) => [n, n]),
			(v) => commit(() => {
				const conn = ed.setConnectionEnd(project, qualifiedName(block), 'to', v);
				const now = qualifiedName(conn);
				if (now !== qname) hooks.onSelect?.({ kind, name: now });
			})));
		withEntries(equationField(dims.length ? 'Input rate (default)' : 'Input rate',
			() => block.rate, (v) => { block.rate = v; },
			{ field: 'rate', hint: 'Added directly to the target compartment.' }));
		if (!brief) {
			unitNode = derivedField('Unit', ed.derivedUnit(project, block, 'inflow'),
				`An absolute flux, so ${block.to ?? 'the target'}'s unit over `
				+ `${ed.timeUnit(project)}. Change it on that compartment.`);
		}
	}

	// Whether this flux may reach an end of fewer dimensions than it has, by
	// adding its cells up on the way in. Offered only where it arises -- the
	// ends already disagree, or the flux has said yes and might want to say no
	// again -- because on a flux whose ends correspond there is nothing for it
	// to do and a tick box that does nothing is a question about a problem the
	// reader has not got.
	if (connection) {
		const summed = ed.summedFluxDims(project, block);
		if (summed.length || block.sum_extra_indices) {
			const say = ({ end, name, dims }) => `${dims.map((d) => `'${d}'`).join(' and ')} `
				+ `${dims.length > 1 ? 'are' : 'is'} on this ${kind} and not on '${name}', so `
				+ (end === 'to'
					? `the flux is added up over ${dims.length > 1 ? 'them' : 'it'} and `
						+ `delivered into the one '${name}' cell`
					: `the one '${name}' cell has the flux taken out of it once per index`);
			more(checkField('Sum extra indices',
				() => !!block.sum_extra_indices,
				(v) => {
					if (v) block.sum_extra_indices = true;
					else delete block.sum_extra_indices;
				},
				summed.length
					? `${summed.map(say).join('; ')}. Off, the model is refused: a flux `
						+ `whose ends do not correspond is more often a slip than a `
						+ `decision.`
					: 'Nothing to add up: both ends carry every dimension this '
						+ `${kind} has. Untick it and nothing changes.`));
		}
	}

	// A block with a dimension but no grid yet -- nothing above claimed it --
	// still needs one. Except a release out of a far-field path: it is per
	// nuclide, but every one of its values is the path's own release, and a
	// grid of boxes that must all hold the same thing is an invitation to
	// break it.
	if (dims.length && !entriesPlaced
		&& !(kind === 'transfer' && ed.isReleaseTransfer(project, block))) {
		withEntries(el('span', { hidden: true }));
	}

	// --- what the block itself comes to at the start ----------------------
	// Only for the kinds with no equation box of their own: where there is
	// one, the line under it has already said it. What a reduction sums to
	// before anything has moved, or what a delay reads before there is any
	// history to read, is exactly the number that says whether the block is
	// wired up the way it was meant to be.
	if (hooks.atStart && NO_EQUATION_OF_THEIR_OWN.includes(kind)) {
		const shown = markStartValue(el('output', { className: 'insp-derived mono' }), qname);
		const at = startValueLine(hooks.atStart(qname));
		if (at) { shown.textContent = at.text; shown.title = at.title; }
		const row = el('div', { className: 'insp-row' },
			el('label', { className: 'insp-label' }, 'At the start'),
			shown,
			el('p', { className: 'insp-hint' },
				'What this block reads at the first instant of the run.'));
		row.dataset.startvalueRow = '';
		row.hidden = !at;
		host.append(row);
	}

	// The unit, in the cell beside the name: the branches above decided what
	// it says, and this is where it goes. See `unitNode`.
	if (unitNode) nameRow.after(unitNode);

	// Last of the fields, and the only one that is about the block rather than
	// about a value in it.
	//
	// Not for a function: it has no value to leave out of the run, and every
	// equation that calls one would stop meaning anything. Deleting it is the
	// honest way to get rid of one, and the editor refuses that while an
	// equation still calls it.
	if (kind !== 'function') host.append(enabledRow());

	// --- review ------------------------------------------------------------
	// Only where the model has asked for it. A review is a process somebody
	// has decided to run, not something to put in front of everybody editing
	// a model on a Tuesday afternoon.
	if (qa.enabled(project)) host.append(reviewSection());

	// --- appearance -------------------------------------------------------
	// A block drawn as a node has a colour, a shape and a size; a connection
	// is a line and has a colour, a weight and a dash. Its look used to
	// follow its endpoints and nothing else, which is right until a model has
	// thirty transfers -- then telling one route from another is what the
	// drawing is for. `Shown as` is here too: what a block is called on screen
	// is one of the things this panel is for, and it was taking the best cell
	// in the dialog -- the one beside the name -- for a field most models
	// never set.
	if (ed.NODE_KINDS.includes(kind)) {
		const box = railSection('appearance', 'Appearance',
			ed.blockShape(project, qname, kind) === ed.defaultShapeFor(kind)
				&& !block.color && !block.w && !ed.hasSymbol(block)
				? 'default'
				: 'custom');
		const look = renderAppearance(project, block, kind, hooks);
		look.prepend(...symbolRows());
		box.append(look);
		more(box);
	} else if (kind === 'transfer' || kind === 'inflow') {
		const look = ed.connectionLook(block);
		const box = railSection('appearance', 'Appearance',
			look.color || look.width || look.dash || ed.hasSymbol(block)
				? 'custom' : 'default');
		const drawn = renderLineAppearance(project, block, hooks);
		drawn.prepend(...symbolRows());
		box.append(drawn);
		more(box);
	}

	// --- comment and delete -----------------------------------------------
	const comment = el('textarea', {
		className: 'insp-comment', rows: 3, value: block.comment ?? '',
		placeholder: 'Notes about this block', spellcheck: true,
	});
	comment.addEventListener('change', () => { block.comment = comment.value; hooks.onChange?.(); });
	// Open when there is something to read, closed when it is an empty box.
	const commentBox = railSection('comment', 'Comment',
		block.comment ? 'written' : '', '', !!block.comment);
	commentBox.append(comment);
	more(commentBox);

	const refs = ed.referencesTo(project, qname);
	if (refs.length) {
		more(el('p', { className: 'insp-hint' },
			`Referenced by ${refs.join(', ')}.`));
	}

	// The way through to everything the rail left out.
	if (brief) {
		const open = el('button', {
			className: 'insp-settings', type: 'button',
			title: 'Unit, dimensions, per-index values, appearance and comment. '
				+ 'Double-clicking the block on the diagram opens the same thing.',
		}, 'All settings…');
		open.addEventListener('click', () => hooks.onOpenSettings?.(qname));
		host.append(open);
		if (block.comment) {
			host.append(el('p', { className: 'insp-hint insp-note' }, block.comment));
		}
	}

	const del = el('button', { className: 'insp-delete', type: 'button' }, 'Delete block');
	del.addEventListener('click', () => {
		try {
			const removed = ed.deleteBlock(project, qname);
			hooks.onSelect?.(null);
			hooks.onChange?.();
			hooks.onStatus?.(
				removed.length > 1
					? `Deleted ${removed[0]} and ${removed.length - 1} attached connection(s).`
					: `Deleted ${removed[0]}.`, 'info');
		} catch (e) {
			hooks.onStatus?.(e.message, 'warn');
		}
	});
	host.append(del);
}

/**
 * The sub-system panel: its name, and the two things that can happen to it.
 *
 * Deliberately small. A sub-system has no value, no unit and no dimensions --
 * it is a place, not a quantity -- so what is left is what it is called, and
 * whether it should go on being one.
 */
/**
 * The wetted surface per volume of water a path's settings come to, when they
 * are numbers: F/T_w, a_w itself, or 2/δ. Null when any of them is an
 * equation -- a read-out that guessed would be worse than one that says
 * nothing.
 */
function numericAw(block) {
	const how = surfaceOf(block);
	const tw = Number(block.tw);
	let aw = NaN;
	if (how === 'aw') aw = Number(block.aw);
	else if (how === 'aperture') aw = 2 / Number(block.aperture);
	else if (tw > 0) aw = Number(block.f) / tw;
	return Number.isFinite(aw) && aw > 0 ? aw : null;
}

const shortNumber = (x, digits = 4) => String(Number(x.toPrecision(digits)));

/**
 * The other two ways of saying what a path's wetted surface is, for the line
 * under the choice: given F, the wetted surface and the aperture; given the
 * surface, F and the aperture; given the aperture, the other two.
 */
function surfaceReading(block) {
	const aw = numericAw(block);
	const tw = Number(block.tw);
	if (aw == null) return 'The other two follow the equations: a_w = F/T_w, and the aperture is 2/a_w.';
	const aperture = `aperture ${shortNumber(2 / aw, 3)} m`;
	const f = tw > 0 ? `F = a_w·T_w = ${shortNumber(aw * tw)}` : 'F follows T_w';
	const how = surfaceOf(block);
	if (how === 'aw') return `${f}; ${aperture}.`;
	if (how === 'aperture') return `a_w = 2/\u03b4 = ${shortNumber(aw)} m²/m³; ${f}.`;
	return `a_w = F/T_w = ${shortNumber(aw)} m²/m³; ${aperture}.`;
}

/**
 * What a path's wetted surface is when given the other way, as an equation, so
 * that switching how it is given does not change the path. Null when the
 * settings are equations and there is no number to carry across.
 */
function sameSurface(block, how) {
	const aw = numericAw(block);
	if (aw == null) return null;
	const tw = Number(block.tw);
	if (how === 'aw') return shortNumber(aw, 12);
	if (how === 'aperture') return shortNumber(2 / aw, 12);
	return tw > 0 ? shortNumber(aw * tw, 12) : null;
}

function renderSystemPanel(host, project, path, hooks) {
	const transport = ed.isTransport(project, path);
	host.append(el('div', { className: 'insp-head' },
		el('span', {
			className: `insp-kind insp-kind-system${transport ? ' insp-kind-transport' : ''}`,
		}, transport ? 'transport' : 'sub-system')));

	const row = (label, control, hint) => el('div', { className: 'insp-row' },
		el('label', { className: 'insp-label' }, label),
		control,
		hint ? el('p', { className: 'insp-hint' }, hint) : null);

	const name = el('input', {
		type: 'text', value: ed.baseName(path), className: 'insp-input', spellcheck: false,
	});
	name.addEventListener('change', () => {
		try {
			const to = ed.renameSystem(project, path, name.value.trim());
			hooks.onChange?.();
			hooks.onSelect?.({ kind: 'system', name: to });
		} catch (e) {
			hooks.onStatus?.(e.message, 'warn');
			name.value = ed.baseName(path);
		}
	});
	host.append(row('Name', name,
		'Every block inside keeps its own name; the path they are reached by changes.'));

	const inside = ed.blocksIn(project, path, { deep: true }).length;
	host.append(row('Holds', el('div', { className: 'insp-static' },
		`${inside} block${inside === 1 ? '' : 's'}`)));

	// A transport says how long its chain is, and offers the one block only
	// it can hold.
	if (transport) {
		const parts = ed.transportParts(project, path);
		const { n, why } = ed.transportNumber(project, parts);
		host.append(row('Chain', el('div', { className: 'insp-static' },
			why ? 'length not yet known'
				: `${n} compartment${n === 1 ? '' : 's'}, from ${parts.begin?.name ?? 'Begin'} `
					+ `to ${parts.end?.name ?? 'End'}`),
		why ?? `Set by ${parts.number?.name ?? 'N'} inside. Every transfer drawn between `
			+ `${parts.begin?.name ?? 'Begin'} and ${parts.end?.name ?? 'End'} joins each `
			+ 'compartment of the chain to the next.'));
		const add = el('button', { className: 'insp-settings', type: 'button' },
			'Add operation over the chain');
		add.addEventListener('click', () => {
			try {
				const block = ed.addTransportOperation(project, {
					system: path, at: ed.freeSpotIn(project, path),
				});
				hooks.onChange?.();
				hooks.onSelect?.({ kind: 'expression', name: qualifiedName(block) });
			} catch (e) { hooks.onStatus?.(e.message, 'warn'); }
		});
		host.append(add);
	}

	const open = el('button', { className: 'insp-settings', type: 'button' },
		'Show on the diagram');
	open.addEventListener('click', () => hooks.onOpenSystem?.(path));
	host.append(open);

	const dissolve = el('button', {
		className: 'insp-delete', type: 'button',
		title: transport
			? 'Removes the transport; Begin and End become ordinary compartments, and its '
				+ 'blocks move out into the one around it'
			: 'Removes the sub-system; its blocks move out into the one around it',
	}, 'Dissolve');
	dissolve.addEventListener('click', () => {
		try {
			ed.deleteSystem(project, path, { contents: 'move' });
			hooks.onSelect?.(null);
			hooks.onChange?.();
			hooks.onStatus?.(
				`Dissolved ${ed.baseName(path)}; its ${inside} block`
				+ `${inside === 1 ? '' : 's'} moved out.`, 'info');
		} catch (e) { hooks.onStatus?.(e.message, 'warn'); }
	});
	host.append(dissolve);
}

/**
 * Colour, shape and size.
 *
 * Every block drawn on the diagram gets these, not just compartments: on a
 * model of any size the quickest way to make a diagram readable is to group
 * things by how they look.
 */
/**
 * A connection's look: a colour, a weight and a dash.
 *
 * The three things a line can say with. Built like `renderAppearance` and in
 * the same rows, because it is the same section of the same panel -- what
 * differs is that a line has no shape and no size.
 *
 * Every edit is `layoutOnly`: how a line is drawn changes no number, so it
 * must not mark the results stale or start a run.
 */
function renderLineAppearance(project, block, hooks) {
	const qname = qualifiedName(block);
	const look = ed.connectionLook(block);
	const section = el('div', { className: 'insp-appearance' });

	const set = (patch, opts = {}) => {
		try {
			ed.setConnectionLook(project, qname, patch);
			// `layoutOnly` last: what a caller may add here is how the edit is
			// recorded, never whether drawing a line changes a number.
			hooks.onChange?.({ ...opts, layoutOnly: true });
		} catch (e) { hooks.onStatus?.(e.message, 'warn'); }
	};
	const row = (label, control, reset) => section.append(
		el('div', { className: 'insp-appearance-row' },
			el('span', {}, label), control, reset ?? el('span', {})),
	);
	const clear = (what, patch, on) => {
		const b = el('button', {
			className: 'insp-appearance-reset', type: 'button',
			title: on ? `Use the default ${what}` : 'Default',
			disabled: !on,
		}, '\u00d7');
		b.addEventListener('click', () => set(patch));
		return b;
	};

	// --- colour ---
	// The theme's own edge colour as the starting point, so opening the picker
	// on a line that has never been coloured does not suggest it is red.
	const swatch = el('input', { type: 'color', value: look.color ?? '#8a8880' });
	const clearColour = clear('colour', { color: null }, !!look.color);
	// A colour picker reports every colour the pointer passes over on its way
	// to the one that is chosen. `coalesce` makes the whole sweep one step to
	// undo rather than two hundred; see undo.js. `keepModal` keeps the dialog
	// from being rebuilt under the picker, which would close it -- see
	// `republish` -- and `pickedColour` puts right in place the two things in
	// the dialog a colour changes.
	const pick = () => {
		set({ color: swatch.value }, { coalesce: `colour:${qname}`, keepModal: true });
		pickedColour(swatch, clearColour, 'Use the default colour');
	};
	swatch.addEventListener('input', throttled(pick, 120));
	// And `change` the same way: where the picker is a panel that stays open,
	// Chrome may send it for every colour chosen rather than once at the end.
	swatch.addEventListener('change', pick);
	row('colour', swatch, clearColour);

	// --- weight ---
	const width = el('select', {});
	for (const w of ed.EDGE_WIDTHS) {
		width.append(el('option', {
			value: String(w), selected: (look.width ?? 1.8) === w,
		}, w === 1 ? 'hairline' : w === 1.8 ? 'normal' : w === 2.6 ? 'thick' : 'heavy'));
	}
	width.addEventListener('change', () => set({ line_width: Number(width.value) }));
	row('weight', width, clear('weight', { line_width: null }, !!look.width));

	// --- dash ---
	const dash = el('select', {});
	for (const d of ed.SHAPE_DASHES) {
		dash.append(el('option', {
			value: d, selected: (look.dash ?? 'solid') === d,
		}, d));
	}
	dash.addEventListener('change', () => set({ dash: dash.value }));
	row('style', dash, clear('style', { dash: null }, !!look.dash));

	section.append(el('p', { className: 'insp-hint' },
		'How the line is drawn, and nothing about what it carries. A colour '
		+ 'here also colours the cell in the transfer grid.'));
	return section;
}

/**
 * What choosing a colour changes in the dialog around the picker, put right
 * in place because the dialog is not rebuilt while a picker is open: the x
 * beside it, which now has a colour to clear, and the section's badge, which
 * now says the block is not as its kind draws it.
 */
function pickedColour(swatch, clearButton, title = null) {
	clearButton.disabled = false;
	if (title) clearButton.title = title;
	const badge = swatch.closest('.panel-section')?.querySelector(':scope > summary > .panel-section-badge');
	if (badge) badge.textContent = 'custom';
}

function renderAppearance(project, block, kind, hooks) {
	// Its own, because this is a separate function: the block's identity is
	// its qualified name, not the name in the box.
	const qname = qualifiedName(block);
	// No heading of its own: the section around it carries the title.
	const section = el('div', { className: 'insp-appearance' });

	// --- colour ---
	const swatch = el('input', {
		type: 'color',
		value: block.color ?? DEFAULT_COLOR[kind] ?? '#dff0e0',
	});
	const clearColour = el('button', {
		className: 'insp-appearance-reset', type: 'button',
		title: block.color ? 'Use the default colour for this kind of block' : 'Default',
		disabled: !block.color,
	}, '×');
	const paint = () => {
		try {
			ed.setBlockColor(project, qname, swatch.value);
			// One step for the whole sweep of the picker, not one per colour
			// it passes through on the way. And the dialog left standing,
			// since rebuilding it under the picker closes the picker (see
			// `republish`): what the colour changes in it is put right here.
			hooks.onChange?.({ layoutOnly: true, coalesce: `colour:${qname}`, keepModal: true });
			pickedColour(swatch, clearColour, 'Use the default colour for this kind of block');
		} catch (e) { hooks.onStatus?.(e.message, 'warn'); }
	};
	swatch.addEventListener('input', throttled(paint, 120));
	// Where the picker is a panel that stays open, Chrome may send `change`
	// for every colour chosen rather than once at the end, so it is no
	// different from `input`.
	swatch.addEventListener('change', paint);
	clearColour.addEventListener('click', () => {
		ed.setBlockColor(project, qname, null);
		hooks.onChange?.({ layoutOnly: true });
	});
	section.append(el('div', { className: 'insp-appearance-row' },
		el('span', {}, 'colour'), swatch, clearColour));

	// --- shape ---
	// The current value is the shape actually drawn, which for a block with no
	// override is its kind's default -- not a blanket 'rounded'.
	const shapeSel = el('select', {});
	const defaultShape = ed.defaultShapeFor(kind);
	const current = block.shape ?? defaultShape;
	for (const name of shapeNames()) {
		shapeSel.append(el('option', {
			value: name, selected: name === current,
		}, name === defaultShape ? `${shapeLabel(name)} (default)` : shapeLabel(name)));
	}
	shapeSel.addEventListener('change', () => {
		try {
			ed.setBlockShape(project, qname, shapeSel.value);
			hooks.onChange?.({ layoutOnly: true });
		} catch (e) {
			hooks.onStatus?.(e.message, 'warn');
			shapeSel.value = current;
		}
	});
	section.append(el('div', { className: 'insp-appearance-row' },
		el('span', {}, 'shape'), shapeSel, el('span', {})));

	// --- size ---
	const size = ed.blockSize(project, qname, kind);
	const dim = (axis, value) => {
		const input = el('input', {
			type: 'text', className: 'mono', value: String(value), spellcheck: false,
		});
		input.addEventListener('change', () => {
			const v = Number(input.value);
			if (!Number.isFinite(v)) { input.value = String(value); return; }
			try {
				ed.setBlockSize(project, qname, { [axis]: v });
				hooks.onChange?.({ layoutOnly: true });
			} catch (e) { hooks.onStatus?.(e.message, 'warn'); }
		});
		return input;
	};
	const explicit = project.layout?.[qname]?.w != null
		|| project.layout?.[qname]?.h != null;
	const clearSize = el('button', {
		className: 'insp-appearance-reset', type: 'button',
		title: explicit ? 'Return to the default size' : 'Default size',
		disabled: !explicit,
	}, '×');
	clearSize.addEventListener('click', () => {
		ed.clearBlockSize(project, block.name);
		hooks.onChange?.({ layoutOnly: true });
	});
	section.append(el('div', { className: 'insp-appearance-row insp-size' },
		el('span', {}, 'size'),
		el('span', { className: 'insp-size-pair' },
			dim('w', size.w), el('span', { className: 'insp-times' }, '×'), dim('h', size.h)),
		clearSize));

	section.append(el('p', { className: 'insp-hint' },
		'Or drag the grips on the selected node; double-click a grip to reset.'));
	return section;
}

/** Fallbacks matching the CSS, so the picker opens on the colour in use. */
const DEFAULT_COLOR = {
	compartment: '#dff0e0',
	expression: '#eceaf7',
	parameter: '#f3ead9',
};

/**
 * The per-index value editor.
 *
 * An indexed block holds one value per index combination: the block-level
 * value is the default, and entries override it. This is Ecolego's
 * the per-index entry store arrangement, and without a way to see and edit those
 * overrides an indexed block looks like it has a single value.
 *
 * Two modes, because the combination count varies by orders of magnitude:
 * a full grid while it stays readable, and an overrides-only list with an
 * explicit picker once it does not.
 *
 * Exported because the left panel edits parameters and expressions in place,
 * and an indexed one needs exactly this. One implementation of per-index
 * editing, used from both sides. Pass `heading: false` where the caller's own
 * header already names it and counts the overrides.
 */
export function renderEntryEditor(project, block, kind, dims, hooks, opts = {}) {
	const key = ed.ENTRY_KEY[kind];
	// Per-index properties beside the block's value: a compartment's own
	// absolute tolerance is one, and it gets a column of its own rather than
	// a second grid, because it is read against the initial inventory sitting
	// next to it. See ENTRY_EXTRA.
	let extras = ed.ENTRY_EXTRA[kind] ?? [];
	// A path indexed by something other than the nuclides is that many paths
	// side by side, and what differs between them is the geometry: the travel
	// time through this object, the flow-wetted surface of that one. Those
	// settings are not per nuclide, so they are held over the *other*
	// dimensions alone -- which is where the column writes them, however many
	// rows of the grid show the same value. Without this the dimension could
	// be chosen and the numbers that make it worth choosing could not be set.
	if (kind === 'farfield') {
		const decay = ed.decayDimensionOf(project, block);
		const over = dims.filter((d) => d !== decay);
		if (over.length) {
			// Of F, the wetted surface and the aperture, only the one the path
			// gives: the other two are not worked out, and a column for them
			// would be numbers that change nothing.
			const used = new Set(ed.activeEquationKeys(block));
			extras = [...extras, ...ed.FARF_SINGLE_KEYS
				.filter((k) => ed.FARF_EQUATION_KEYS.includes(k) && used.has(k))
				.map((k) => ({
					key: k,
					label: ed.FARF_LABEL[k],
					title: `${ed.symbolText(ed.FARF_HELP[k] ?? '')} `
						+ `Held per ${over.join(' \u00d7 ')} rather than per index: the `
						+ 'same water takes the same time whatever is dissolved in it.',
					over,
				}))];
		}
	}
	const keys = [...new Set([...ed.entryKeys(kind), ...extras.map((x) => x.key)])];
	const numeric = kind === 'parameter';
	const total = ed.combinationCount(project, dims);
	const GRID_LIMIT = 240;

	const heading = opts.heading !== false;
	const section = el('div', {
		className: `insp-entries${heading ? '' : ' is-bare'}`,
	});
	const overrides = ed.setIndexes(block, kind).map((index) => ({ index }));

	if (heading) {
		section.append(el('div', { className: 'insp-entries-head' },
			el('span', { className: 'insp-label' }, 'Values per index'),
			el('span', { className: 'insp-entries-count' },
				`${total} combination${total === 1 ? '' : 's'}`
				+ (overrides.length ? `, ${overrides.length} set` : ''))));
	}

	if (total === 0) {
		section.append(el('p', { className: 'insp-hint' },
			'Every index of at least one of this block\u2019s dimensions is disabled, '
			+ 'so it holds no values.'));
		return section;
	}

	// The block's identity, not the name in the Name box: a block inside a
	// sub-system is `NearField.Kd`, and asking for `Kd` finds nothing.
	const qname = qualifiedName(block);

	/**
	 * Whether the grid carries a column of what each index comes to at the
	 * start of the run.
	 *
	 * Two reasons it might not. There has to be room: a far-field path already
	 * has a column for every chemistry term, and a sixth would leave the
	 * equation a sliver. And the scenario dimension is not a dimension of the
	 * simulation -- one scenario is live and the model is evaluated at that one
	 * -- so a block carrying it has a row per scenario and one value behind
	 * them all, and a column repeating that value against each would say the
	 * scenarios differ when nothing here can tell.
	 */
	// The floor is a narrow three-way picker rather than a column of boxes,
	// so it is not counted: a compartment's grid keeps its answer column with
	// the dy/dt term, the tolerance and the floor beside the inventory.
	const showStart = !!hooks.atStart && extras.filter((x) => !x.flag).length <= 2
		&& !dims.some((d) => ed.isScenarioDim(project, d));
	// A table's rows are not rows of the grid -- each is a disclosure holding
	// a whole list of points -- so there is no column to put anything in, and
	// what the table reads at the start goes on the line that summarises it.
	const startColumn = showStart && kind !== 'lookup';

	const commitValue = (index, raw, input, previous) => {
		let value = raw;
		if (kind === 'lookup') {
			// Already parsed and checked by the points box.
			value = raw;
		} else if (kind === 'block_reduction') {
			// The blocks an aggregate reduces, joined the way the .eco format
			// joins them. Splitting on a comma instead would quietly turn one
			// name into two on any model that uses one.
			value = String(raw).split('+').map((t) => t.trim()).filter(Boolean);
		} else if (numeric) {
			const n = Number(raw);
			if (!Number.isFinite(n)) {
				hooks.onStatus?.(`'${raw}' is not a number`, 'warn');
				input.value = String(previous ?? '');
				return;
			}
			value = n;
		} else {
			// Checked against the block's identity, not the name in its Name
			// box: an override inside a sub-system reads that sub-system's
			// names, and `block.name` would resolve it at the root.
			const problem = validateEquation(project, raw, qname);
			if (problem) hooks.onStatus?.(`${block.name}: ${problem}`, 'warn');
		}
		try {
			ed.setEntryValue(project, qname, index, key, value);
			hooks.onChange?.();
		} catch (e) {
			hooks.onStatus?.(e.message, 'warn');
		}
	};

	const clear = (index) => {
		try {
			for (const k of keys) ed.clearEntryValue(project, qname, index, k);
			hooks.onChange?.();
		} catch (e) {
			hooks.onStatus?.(e.message, 'warn');
		}
	};

	/**
	 * A table per index, as a disclosure: the points are far too tall to sit in
	 * a grid row, and a model that sets them per index sets a handful, not all
	 * of them.
	 */
	const tableRow = (index, { showLabels = true } = {}) => {
		const set = ed.isOverridden(block, key, index);
		const pts = ed.effectiveValue(block, key, index) ?? [];
		const det = el('details', {
			className: `insp-entry insp-entry-table${set ? ' is-set' : ''}`
				+ `${showStart ? ' has-start' : ''}`,
		});
		det.append(el('summary', {},
			showLabels
				? el('span', { className: 'insp-entry-idx' },
					dims.map((d) => index[d]).join(' \u00b7 '))
				: null,
			el('span', { className: 'insp-entry-sum' },
				`${summariseTable({ points: pts })}${set ? '' : ' (default)'}`),
			// What the table reads at the start, which is the one point of it
			// the rest of the model sees first.
			showStart
				? refreshStartValue(markStartValue(
					el('span', { className: 'insp-entry-start mono' }),
					qname, key, dims.map((d) => index[d]),
				), hooks.atStart(qname, key))
				: null));
		const body = el('div', { className: 'insp-entry-body' });
		body.append(pointsBox({
			points: pts,
			onCommit: (next) => commitValue(index, next),
			onStatus: hooks.onStatus,
			rows: 6,
			// Per index, but the rule belongs to the block: a table is read one
			// way whichever of its indexed sets of points is being looked at.
			interpolation: block.interpolation ?? 'linear',
		}));
		const reset = el('button', {
			className: 'insp-entry-reset',
			type: 'button',
			title: set ? 'Clear, and use the block default again' : 'Not set here',
			disabled: !set,
		}, 'Use the default');
		reset.addEventListener('click', () => clear(index));
		body.append(reset);
		det.append(body);
		return det;
	};

	/**
	 * One of the extra per-index properties, as a box in its own column.
	 *
	 * Blank is the resting state and means "inherited", so the box shows what
	 * it would inherit as its placeholder -- the block's own value if it has
	 * one, otherwise where the value really comes from, which for a tolerance
	 * is the simulation. Emptying it clears the override rather than writing a
	 * zero, which is the only reading that matches what blank means.
	 */
	const extraBox = (x, full) => {
		// A column held over fewer dimensions than the grid's rows writes at
		// those: every row for the same object edits that object's value, and
		// shows it.
		const index = x.over
			? Object.fromEntries(x.over.map((d) => [d, full[d]]))
			: full;
		const own = ed.isOverridden(block, x.key, index);
		const value = ed.effectiveValue(block, x.key, index);
		// A flag, not a number: three states rather than a box that would
		// have to be typed `false` into. Blank is what the block says, and
		// what the block says is spelled out in the option so that the row
		// answers the question without looking anywhere else.
		// A distribution rather than a number: the cell says what it is and
		// opens the editor, which is where the shape is drawn. A column of
		// `logt(min=7.0E-12,max=5.0E-11,mode=1.0E-11)` would be unreadable and
		// untypable, and the thing anyone wants from it is the picture.
		if (x.pdf) {
			// `value` is the effective one: this index's own, or the block's.
			// An inherited one is shown greyed rather than as a dash, the way
			// the tolerance column shows the value that would be used -- a cell
			// that says nothing where the parameter has a default is a cell
			// saying the wrong thing.
			const has = !!value;
			const button = el('button', {
				type: 'button',
				className: `insp-entry-extra insp-entry-pdf${own && value ? ' is-own' : ''}`,
				title: has
					? `${describePDF(value)}${own ? '' : " \u2014 the parameter's own"}`
						+ '\n\nClick to edit or remove it.'
					: ed.symbolText(x.title),
			}, has ? describePDF(value) : '—');
			button.addEventListener('click', () => {
				openPDFEditor({
					spec: has ? value : null,
					title: `${block.name}${Object.keys(index).length
						? ` [${Object.values(index).join(' \u00b7 ')}]` : ''}`,
					unit: block.unit ?? '',
					value: ed.effectiveValue(block, ed.ENTRY_KEY[kind], index) ?? null,
					onSave: (next) => {
						try {
							if (next) ed.setEntryValue(project, qname, index, x.key, next);
							else ed.clearEntryValue(project, qname, index, x.key);
							hooks.onChange?.();
						} catch (e) { hooks.onStatus?.(e.message, 'warn'); }
					},
				});
			});
			return button;
		}
		if (x.flag) {
			const sel = el('select', {
				className: `insp-entry-extra insp-entry-flag${own ? ' is-own' : ''}`,
				title: ed.symbolText(x.title),
			});
			const asBlock = block[x.key] !== false ? x.on : x.off;
			for (const [v, text] of [
				['', `— ${asBlock}`], ['yes', x.on], ['no', x.off],
			]) {
				sel.append(el('option', {
					value: v, selected: !own ? v === '' : v === (value !== false ? 'yes' : 'no'),
				}, text));
			}
			sel.addEventListener('change', () => {
				try {
					if (!sel.value) ed.clearEntryValue(project, qname, index, x.key);
					else ed.setEntryValue(project, qname, index, x.key, sel.value === 'yes');
					hooks.onChange?.();
				} catch (e) { hooks.onStatus?.(e.message, 'warn'); }
			});
			return sel;
		}
		// An equation rather than a number: checked as one, completed as
		// one, and allowed to name the block it belongs to, as a dy/dt term
		// does. Blank is the compartment's own, shown greyed as the placeholder.
		if (x.equation) {
			const shownEq = own ? String(value ?? '') : '';
			const input = el('input', {
				type: 'text',
				className: `mono insp-entry-extra is-eq${own ? ' is-own' : ''}`,
				value: shownEq,
				placeholder: value != null ? String(value) : '',
				spellcheck: false,
				title: ed.symbolText(x.title),
			});
			attachCompletion(input, equationLook(project, qname, parentOf(qname)));
			input.addEventListener('change', () => {
				const text = input.value.trim();
				try {
					if (!text) {
						ed.clearEntryValue(project, qname, index, x.key);
					} else {
						const problem = validateEquation(project, text, qname, { self: true });
						if (problem) hooks.onStatus?.(`${block.name}: ${problem}`, 'warn');
						ed.setEntryValue(project, qname, index, x.key, text);
					}
					hooks.onChange?.();
				} catch (e) {
					hooks.onStatus?.(e.message, 'warn');
				}
			});
			return input;
		}
		const fallback = x.fallback?.(project);
		const shown = own ? String(value ?? '') : '';
		const input = el('input', {
			type: 'text',
			className: `mono insp-entry-extra${own ? ' is-own' : ''}`,
			value: shown,
			placeholder: value != null ? String(value)
				: fallback == null ? '' : String(fallback),
			spellcheck: false,
			// Plain text: a title attribute is text, and a label may be
			// written in symbol markup.
			title: ed.symbolText(x.title),
		});
		input.addEventListener('change', () => {
			const text = input.value.trim();
			try {
				if (!text) {
					ed.clearEntryValue(project, qname, index, x.key);
				} else {
					const n = Number(text);
					if (!(n > 0) || !Number.isFinite(n)) {
						hooks.onStatus?.(
							`'${input.value}' is not a ${ed.symbolText(x.label)}: `
							+ 'a number greater than zero',
							'warn',
						);
						input.value = shown;
						return;
					}
					ed.setEntryValue(project, qname, index, x.key, n);
				}
				hooks.onChange?.();
			} catch (e) {
				hooks.onStatus?.(e.message, 'warn');
			}
		});
		return input;
	};

	/** One editable row: the index labels, the value, and a reset button. */
	const valueRow = (index, { showLabels = true } = {}) => {
		if (kind === 'lookup') return tableRow(index, { showLabels });
		// Highlighted when anything on the row is this index's own, not only
		// the block's value: a tolerance set here is a value set here.
		const set = keys.some((k) => ed.isOverridden(block, k, index));
		const value = ed.effectiveValue(block, key, index);
		const rowEl = el('div', {
			className: `insp-entry${set ? ' is-set' : ''}`
				+ `${extras.length ? ' has-extra' : ''}${startColumn ? ' has-start' : ''}`,
		});
		if (showLabels) {
			rowEl.append(el('span', { className: 'insp-entry-idx' },
				dims.map((d) => index[d]).join(' \u00b7 ')));
		}
		const input = el('input', {
			type: 'text',
			className: 'mono',
			value: value == null ? ''
				: Array.isArray(value) ? value.join(' + ') : String(value),
			spellcheck: false,
			title: set ? 'Set for this index' : 'Inherited from the block default',
		});
		input.addEventListener('change', () => commitValue(index, input.value, input, value));
		// The same completion the block-level field has: a per-index override
		// is an equation like any other. An aggregate's row is a list of block
		// names joined with `+` rather than an expression, so the function
		// library stays out of it.
		if (!numeric) {
			attachCompletion(input, equationLook(project, qname, parentOf(qname),
				{ functions: kind !== 'block_reduction' }));
		}
		rowEl.append(input);
		// What that equation comes to at the start, beside it rather than
		// under it: in a grid the answer belongs in the row it is about.
		// Marked so that it fills itself in when the values arrive, and filled
		// now if they are already known -- which is what the rows a `load
		// more` adds, and the picker's single row, depend on.
		if (startColumn) {
			const cell = markStartValue(
				el('output', { className: 'insp-entry-start mono' }),
				qname, key, dims.map((d) => index[d]),
			);
			rowEl.append(refreshStartValue(cell, hooks.atStart(qname, key)));
		}
		for (const x of extras) rowEl.append(extraBox(x, index));

		const reset = el('button', {
			className: 'insp-entry-reset',
			type: 'button',
			title: set ? 'Clear, and use the block default again' : 'Not set here',
			disabled: !set,
		}, '\u00d7');
		// The row, not the first column: with two boxes on it, a button that
		// cleared one of them and left the other would be the sort of thing
		// you discover from a result.
		reset.addEventListener('click', () => clear(index));
		rowEl.append(reset);
		return rowEl;
	};

	/**
	 * One column heading.
	 *
	 * A label written in symbol markup is set as a symbol: rendered rather
	 * than printed, and *not* put through the heading's uppercase transform,
	 * which turns `ε` into a capital epsilon -- indistinguishable from an E --
	 * and `K<sub>d,f</sub>` into `K<sub>D,F</sub>`. That transform is why
	 * these labels used to be spelled `EPSM` and `RHOM` in the first place.
	 */
	const colHead = (label, title) => {
		const symbol = ed.symbolText(label) !== label;
		return el('span', {
			className: symbol ? 'insp-entry-sym' : '',
			title: ed.symbolText(title ?? ''),
		}, ...symbolNodes(label));
	};

	const head = () => el('div', {
		className: `insp-entry-head${extras.length ? ' has-extra' : ''}`
			+ `${startColumn ? ' has-start' : ''}`,
	},
	el('span', {}, dims.join(' \u00b7 ')),
	// "value" for a block that has one. A far-field path has ten settings and
	// no single value, so the first column is named like the rest of them --
	// a column headed "value" beside nine headed by what they are says the
	// wrong thing about which one matters.
	colHead(PRIMARY_LABEL[kind] ?? 'value', PRIMARY_TITLE[kind]),
	...(startColumn ? [colHead('at the start',
		'What this index works out to at the first instant of the run')] : []),
	...extras.map((x) => colHead(x.label, x.title)),
	el('span', {}));

	/**
	 * The list the rows go in.
	 *
	 * How many value columns there are beside the block's own is not something
	 * CSS can know, so it is handed over as a custom property and the template
	 * in the stylesheet repeats on it. A far-field path has three extras --
	 * the porosity and the two other retention terms -- and a template fixed
	 * at one wrapped every nuclide onto two lines.
	 */
	const newList = () => {
		const el2 = el('div', { className: 'insp-entry-list' });
		if (extras.length) el2.style.setProperty('--entry-extras', String(extras.length));
		return el2;
	};

	if (total <= GRID_LIMIT) {
		const list = newList();
		list.append(head());
		for (const index of ed.indexCombinations(project, dims)) {
			list.append(valueRow(index));
		}
		section.append(list);
		section.append(el('p', { className: 'insp-hint' },
			'A highlighted row is set for that index; the rest inherit the default '
			+ 'above. \u00d7 clears the row back to the default.'));
		return section;
	}

	// Too many to list. Show what is set, and a picker to reach any one cell.
	if (overrides.length) {
		const list = newList();
		list.append(head());
		for (const o of overrides) list.append(valueRow(o.index));
		section.append(list);
	} else {
		section.append(el('p', { className: 'insp-hint' },
			'Nothing is set per index yet; every combination uses the default above.'));
	}

	// The picker: one select per dimension, then edit that combination.
	const picker = el('div', { className: 'insp-picker' });
	const chosen = {};
	const per = ed.dimensionIndices(project, dims);
	dims.forEach((d, i) => {
		const sel = el('select', {});
		for (const name of per[i]) sel.append(el('option', { value: name }, name));
		chosen[d] = per[i][0];
		sel.addEventListener('change', () => {
			chosen[d] = sel.value;
			refreshPicked();
		});
		picker.append(el('label', { className: 'insp-picker-dim' },
			el('span', {}, d), sel));
	});

	const picked = el('div', { className: 'insp-picker-value' });
	const refreshPicked = () => {
		picked.replaceChildren(valueRow({ ...chosen }, { showLabels: false }));
	};
	refreshPicked();

	section.append(
		el('p', { className: 'insp-hint' },
			`${total} combinations is too many to list. Pick one to set:`),
		picker,
		picked,
	);
	return section;
}

