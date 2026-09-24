/**
 * Solving for the inputs, rather than running with them.
 *
 * Two lists and a method. The first says what the answer has to be -- one or
 * more endpoints with the value each is supposed to come out at; the second
 * says what may move to get there, and between which bounds. Everything else
 * is a consequence of those two, including which algorithm is worth using.
 *
 * **The bounds are the important half and the easy one to leave out.** A
 * search told only "vary the leach rate" will put it at 1e40 if that fits the
 * numbers, and a model is a set of assumptions about what is physical. So a
 * variable arrives with the value it has, a range around it, and -- for
 * anything known to within orders of magnitude, which is most rate constants
 * here -- a logarithmic search, because stepping 5% of a range that spans six
 * decades spends every evaluation in the top one.
 *
 * **Nothing is changed until it is asked for.** A solved problem is a set of
 * numbers on screen; the model still holds what it held. Two buttons then:
 * run it at those values, which shows what they do without keeping them, and
 * update the parameters, which is the edit.
 */

import { el } from './parts.js';
import { openModal } from './modal.js';
import { renderPicker, pickerState } from './pick.js';
import { METHODS, SCALES, SPACES } from '../domain/optimise.js';
import { WHENS } from '../sim/calibrate.js';
import { dialogInfo } from './dialoginfo.js';

const fmt = (v) => {
	if (v == null || !Number.isFinite(v)) return '—';
	if (v === 0) return '0';
	return Math.abs(v) >= 1e5 || Math.abs(v) < 1e-3 ? v.toExponential(4) : String(Number(v.toPrecision(6)));
};

/** A number box that reports what was typed and nothing else. */
function numberBox(value, onSet, { width = '7em', placeholder = '' } = {}) {
	const box = el('input', {
		type: 'text', value: value == null ? '' : String(value), placeholder,
		className: 'opt-num mono',
	});
	box.style.width = width;
	box.addEventListener('change', () => onSet(box.value.trim()));
	return box;
}

/** A sub-dialog of tick boxes, for adding rows to either list. */
function addFrom(items, { title, noun, chosen, onDone }) {
	const picked = new Set();
	const ui = pickerState();
	let handle = null;
	handle = openModal({
		info: dialogInfo('optimise-add'),
		title,
		wide: true,
		build(body) {
			body.replaceChildren();
			const box = el('div', {});
			const go = el('button', { type: 'button', className: 'primary' },
				picked.size ? `Add ${picked.size}` : 'Add');
			renderPicker(box, {
				items: items.filter((i) => !chosen.has(i.key)),
				chosen: picked,
				ui,
				onChange: () => handle.refresh(),
				// A tick has to reach the button, or the list says one is
				// chosen and the only way on stays greyed out.
				onTick: (n) => { go.disabled = !n; go.textContent = n ? `Add ${n}` : 'Add'; },
				noun,
			});
			body.append(box);
			go.disabled = !picked.size;
			go.addEventListener('click', () => { handle.close(); onDone([...picked]); });
			const cancel = el('button', { type: 'button', className: 'ghost' }, 'Cancel');
			cancel.addEventListener('click', () => handle.close());
			body.append(el('div', { className: 'pdf-foot' },
				el('span', { className: 'pdf-note' }, 'Ticked rows are added to the list.'),
				cancel, go));
		},
	});
}

/**
 * @param {object} opts
 * @param {Array} opts.outputs    pickable endpoints `{key, name, kind, unit}`
 * @param {Array} opts.variables  pickable parameters, with their values
 * @param {number[]} opts.times   the run's output times, for the *at* control
 * @param {object} opts.setup     what was set up last time, kept on the model
 * @param {(setup) => void} opts.onRun        start it
 * @param {() => void} opts.onStop
 * @param {(values) => void} opts.onApply     write the values into the model
 * @param {(values) => void} opts.onTry       run the model at them, no edit
 */
export function openOptimiseDialog({
	outputs = [], variables = [], times = [], setup = null,
	onRun, onStop, onApply, onTry, onChange = null,
}) {
	const byVar = new Map(variables.map((v) => [v.key, v]));
	const state = {
		targets: (setup?.targets ?? []).map((t) => ({ ...t })),
		variables: (setup?.variables ?? []).map((v) => ({ ...v })),
		method: setup?.method ?? 'lm',
		maxEvals: setup?.maxEvals ?? 300,
		// Set while it runs, and replaced by the answer.
		running: null,
		result: null,
		error: null,
		// The setup the answer on screen is an answer *to*. Changing a bound
		// or a target makes it an answer to a different question, and the one
		// thing worse than no answer is one that quietly belongs to the
		// problem before the one being looked at.
		ranWith: null,
	};

	let handle = null;
	const redraw = () => handle?.refresh();
	const changed = () => { onChange?.(snapshot()); redraw(); };
	const snapshot = () => ({
		targets: state.targets.map((t) => ({ ...t })),
		variables: state.variables.map((v) => ({ ...v })),
		method: state.method,
		maxEvals: state.maxEvals,
	});

	handle = openModal({
		info: dialogInfo('optimise'),
		title: 'Optimise',
		wide: true,
		build(body) {
			body.replaceChildren();

			// ---------------------------------------------------- the targets
			body.append(el('h3', { className: 'opt-head' }, 'What these should come to'));
			if (!state.targets.length) {
				body.append(el('p', { className: 'hint' },
					'Nothing yet. Add an endpoint and say what value it is supposed to have — '
					+ 'a measurement, a regulatory limit, a number from another assessment.'));
			}
			const tlist = el('div', { className: 'opt-list' });
			state.targets.forEach((t, i) => {
				const row = el('div', { className: 'opt-row' });
				row.append(el('span', { className: 'opt-name', title: t.output }, t.output));

				const when = el('select', { className: 'opt-when' });
				for (const [key, w] of Object.entries(WHENS)) {
					when.append(el('option', { value: key, selected: t.when === key }, w.label));
				}
				when.addEventListener('change', () => { t.when = when.value; changed(); });
				row.append(when);

				if (t.when === 'at') {
					// The run's own times, so a target cannot name an instant
					// the model never reports.
					const at = el('select', { className: 'opt-at' });
					for (const v of times) {
						at.append(el('option', { value: String(v), selected: Number(t.time) === v },
							fmt(v)));
					}
					at.addEventListener('change', () => { t.time = Number(at.value); changed(); });
					row.append(at);
				}

				row.append(el('span', { className: 'opt-eq' }, '='));
				row.append(numberBox(t.value, (v) => { t.value = v; changed(); }));

				const scale = el('select', { className: 'opt-scale' });
				for (const [key, s] of Object.entries(SCALES)) {
					scale.append(el('option', {
						value: key, selected: t.scale === key, title: s.blurb,
					}, s.label));
				}
				scale.addEventListener('change', () => { t.scale = scale.value; changed(); });
				row.append(scale);

				row.append(numberBox(t.weight ?? 1, (v) => { t.weight = Number(v) || 1; changed(); },
					{ width: '4em' }));

				const drop = el('button', { type: 'button', className: 'ghost icon', title: 'Remove' }, '×');
				drop.addEventListener('click', () => { state.targets.splice(i, 1); changed(); });
				row.append(drop);
				tlist.append(row);
			});
			body.append(tlist);
			const addT = el('button', { type: 'button', className: 'ghost' }, 'Add endpoints…');
			addT.addEventListener('click', () => addFrom(outputs, {
				title: 'Which endpoints',
				noun: 'endpoint',
				chosen: new Set(state.targets.map((t) => t.output)),
				onDone: (keys) => {
					for (const k of keys) {
						state.targets.push({
							output: k, when: 'end', time: times[times.length - 1] ?? 0,
							value: '', scale: 'relative', weight: 1,
						});
					}
					changed();
				},
			}));
			body.append(addT);

			// -------------------------------------------------- the variables
			body.append(el('h3', { className: 'opt-head' }, 'What may vary'));
			if (!state.variables.length) {
				body.append(el('p', { className: 'hint' },
					'Nothing yet. Add a parameter and give it bounds — a search with no '
					+ 'bounds will happily put a rate at 1e40 if that fits the numbers.'));
			}
			const vlist = el('div', { className: 'opt-list' });
			state.variables.forEach((v, i) => {
				const known = byVar.get(v.key);
				const row = el('div', { className: 'opt-row' });
				row.append(el('span', { className: 'opt-name', title: v.key }, v.key));
				row.append(el('span', { className: 'opt-now mono', title: 'What the model holds now' },
					fmt(known?.value)));
				row.append(numberBox(v.lower, (x) => { v.lower = x; changed(); }));
				row.append(el('span', { className: 'opt-eq' }, '…'));
				row.append(numberBox(v.upper, (x) => { v.upper = x; changed(); }));

				const space = el('select', { className: 'opt-space' });
				for (const [key, s] of Object.entries(SPACES)) {
					space.append(el('option', {
						value: key, selected: v.space === key, title: s.blurb ?? '',
					}, s.label));
				}
				space.addEventListener('change', () => { v.space = space.value; changed(); });
				row.append(space);

				const drop = el('button', { type: 'button', className: 'ghost icon', title: 'Remove' }, '×');
				drop.addEventListener('click', () => { state.variables.splice(i, 1); changed(); });
				row.append(drop);
				vlist.append(row);
			});
			body.append(vlist);
			const addV = el('button', { type: 'button', className: 'ghost' }, 'Add parameters…');
			addV.addEventListener('click', () => addFrom(variables, {
				title: 'Which parameters may vary',
				noun: 'parameter',
				chosen: new Set(state.variables.map((v) => v.key)),
				onDone: (keys) => {
					for (const k of keys) {
						const known = byVar.get(k);
						const at = Number(known?.value);
						// A decade either side of what it holds, in the
						// logarithm where that is possible -- which is the
						// range somebody would type, and the one they can then
						// argue with.
						const log = Number.isFinite(at) && at > 0;
						state.variables.push({
							key: k,
							lower: log ? at / 10 : (Number.isFinite(at) ? at - Math.abs(at) - 1 : 0),
							upper: log ? at * 10 : (Number.isFinite(at) ? at + Math.abs(at) + 1 : 1),
							space: log ? 'log' : 'linear',
						});
					}
					changed();
				},
			}));
			body.append(addV);

			// ----------------------------------------------------- the method
			body.append(el('h3', { className: 'opt-head' }, 'How'));
			const how = el('div', { className: 'field' }, el('label', {}, 'Method'));
			const sel = el('select');
			for (const [key, m] of Object.entries(METHODS)) {
				sel.append(el('option', { value: key, selected: state.method === key }, m.label));
			}
			sel.addEventListener('change', () => { state.method = sel.value; changed(); });
			how.append(sel);
			how.append(el('label', {}, 'At most'));
			how.append(numberBox(state.maxEvals, (v) => {
				state.maxEvals = Math.max(10, Math.round(Number(v) || 300));
				changed();
			}, { width: '5em' }));
			how.append(el('span', { className: 'hint' }, 'evaluations'));
			body.append(how);
			body.append(el('p', { className: 'hint' }, METHODS[state.method]?.blurb ?? ''));
			body.append(el('p', { className: 'hint' },
				'Each evaluation is a whole run of the model, so the count is the time this '
				+ 'takes. Stop is available while it goes.'));

			// ---------------------------------------------------- what it said
			//
			// An answer is about the setup it was asked of. Edit a bound and
			// it is still a real answer -- the values solved something -- but
			// not this problem, and saying so is the difference between a
			// stale number and a wrong one.
			const stale = !!state.result && state.ranWith !== JSON.stringify(snapshot());
			if (state.error) body.append(el('p', { className: 'prob-warn' }, state.error));
			if (state.running) {
				const p = state.running;
				body.append(el('p', { className: 'pdf-summary mono' },
					`${p.evals.toLocaleString()} evaluations · best ${fmt(p.best)}`
					+ (p.values ? ` · ${p.values.map(fmt).join(', ')}` : '')));
			}
			if (state.result) body.append(resultBox(state.result, stale));

			// ------------------------------------------------------ the buttons
			const foot = el('div', { className: 'pdf-foot' });
			const ready = state.targets.length && state.variables.length
				&& state.targets.every((t) => String(t.value).trim() !== '');
			foot.append(el('span', { className: 'pdf-note' },
				state.running ? 'Running…'
					: !ready ? 'Every endpoint needs a value, and something has to be allowed to vary.'
						: stale ? 'The setup has changed since that answer.'
							: 'Nothing is changed until you ask for it.'));
			if (state.running) {
				const stop = el('button', { type: 'button', className: 'ghost' }, 'Stop');
				stop.addEventListener('click', () => onStop());
				foot.append(stop);
			} else {
				// The answer, where there is one and it is worth using.
				if (state.result?.ok) {
					const tryIt = el('button', { type: 'button', className: 'ghost' },
						'Run at these values');
					tryIt.title = 'Runs the model with them without keeping them, so the whole '
						+ 'answer can be looked at before it is taken.';
					tryIt.addEventListener('click', () => { handle.close(); onTry(state.result.values); });
					const keep = el('button', {
						type: 'button', className: stale ? 'ghost' : 'primary',
					}, 'Update the parameters');
					keep.title = 'Writes them into the model as one edit, which one undo takes back.';
					keep.addEventListener('click', () => { handle.close(); onApply(state.result.values); });
					foot.append(tryIt, keep);
				}
				// **And always the way to ask again.** A setup is something
				// somebody argues with: widen a bound, add an endpoint, try
				// the global method because the local one sat down on a wall.
				// With the button gone after the first answer, every one of
				// those meant closing the dialog and building it all again.
				const go = el('button', {
					type: 'button',
					className: state.result?.ok && !stale ? 'ghost' : 'primary',
				}, state.result ? 'Optimise again' : 'Optimise');
				go.disabled = !ready;
				go.addEventListener('click', () => {
					state.result = null;
					state.error = null;
					state.running = { evals: 0, best: Infinity, values: null };
					state.ranWith = JSON.stringify(snapshot());
					redraw();
					onRun(snapshot());
				});
				foot.append(go);
			}
			const close = el('button', { type: 'button', className: 'ghost' }, 'Close');
			close.addEventListener('click', () => handle.close());
			foot.append(close);
			body.append(foot);
		},
	});

	return {
		handle,
		progress(p) { state.running = p; state.result = null; redraw(); },
		finished(result) { state.running = null; state.result = result; state.error = null; redraw(); },
		failed(message) { state.running = null; state.error = message; redraw(); },
	};
}

/** What the answer was, in the words a reader can check it in. */
function resultBox(r, stale = false) {
	const box = el('div', { className: `opt-result${stale ? ' is-stale' : ''}` });
	if (stale) {
		box.append(el('p', { className: 'prob-warn' },
			'This answer is to the setup as it was — something has changed since. '
			+ 'The values below still solved that problem; Optimise again for this one.'));
	}
	const pinned = r.values.filter((v) => v.pinned);
	box.append(el('p', {},
		el('b', {}, !r.ok ? 'Did not solve'
			: r.matched ? `Every endpoint matched, to within 1%`
				: 'The closest it could get'),
		` — ${r.evals.toLocaleString()} evaluations in ${(r.ms / 1000).toFixed(1)} s, `
		+ `${r.reason === 'budget' ? 'stopped at the evaluation limit'
			: r.reason === 'stopped' ? 'stopped' : 'nothing improved it further'}. `
		+ `Objective ${fmt(r.objective)}.`));
	if (r.ok && pinned.length) {
		// The first thing to check, and the one a number on its own does not
		// say: the search was still going when it ran out of room.
		box.append(el('p', { className: 'prob-warn' },
			`${pinned.map((v) => v.key).join(', ')} came out on `
			+ `${pinned.length === 1 ? 'a bound' : 'bounds'}, so the search wanted to go `
			+ 'further and was not allowed. Widen that range, or take it that the model '
			+ 'cannot reach the target from inside it.'));
	}

	const table = el('table', { className: 'opt-table' });
	table.append(el('thead', {}, el('tr', {},
		el('th', {}, 'Endpoint'), el('th', {}, 'Wanted'), el('th', {}, 'Got'), el('th', {}, 'Out by'))));
	const tb = el('tbody');
	for (const t of r.targets) {
		// In the terms the target was set in: a log-scaled endpoint is argued
		// about in factors, and `8301%` says less than `×84` does.
		const off = !Number.isFinite(t.got) || !Number.isFinite(t.want) || t.want === 0 ? '—'
			: t.scale === 'log' && t.got > 0 && t.want > 0
				? `×${(t.got / t.want).toPrecision(3)}`
				: `${(((t.got - t.want) / Math.abs(t.want)) * 100).toFixed(2)}%`;
		tb.append(el('tr', {},
			el('td', { title: t.output }, t.output),
			el('td', { className: 'mono' }, fmt(t.want)),
			el('td', { className: 'mono' }, fmt(t.got)),
			el('td', { className: 'mono' }, off)));
	}
	table.append(tb);
	box.append(table);

	const vt = el('table', { className: 'opt-table' });
	vt.append(el('thead', {}, el('tr', {},
		el('th', {}, 'Parameter'), el('th', {}, 'Was'), el('th', {}, 'Becomes'), el('th', {}, 'Factor'))));
	const vb = el('tbody');
	for (const v of r.values) {
		const factor = Number.isFinite(v.was) && v.was !== 0 && Number.isFinite(v.value)
			? `×${(v.value / v.was).toPrecision(3)}` : '—';
		// The bound is a mark rather than a sentence: the sentence is in the
		// warning above, which names the parameter, and a cell that carries
		// it is four times the width of every other cell in the column.
		const value = el('td', { className: 'mono' }, fmt(v.value));
		if (v.pinned) {
			value.append(el('span', {
				className: 'opt-bound',
				title: `On its ${v.pinned} bound — the search wanted to go further.`,
			}, v.pinned === 'upper' ? '\u2191' : '\u2193'));
		}
		vb.append(el('tr', { className: v.pinned ? 'is-pinned' : '' },
			el('td', { title: v.key }, v.key),
			el('td', { className: 'mono' }, fmt(v.was)),
			value,
			el('td', { className: 'mono' }, factor)));
	}
	vt.append(vb);
	box.append(vt);
	return box;
}
