/**
 * Choosing when results are saved.
 *
 * A list of series -- Ecolego's `TimeSeriesList` -- needs more room than the
 * left panel has, and it is not a setting anyone changes twice a minute, so it
 * is a dialog reached from the panel. What the panel shows is the answer: how
 * many times will be saved and where they run from.
 *
 * The editor is deliberately arithmetic-free. Every number typed into it goes
 * through the domain, and the preview at the bottom is the *engine's* answer --
 * `combineSeries` over the series as they now stand -- rather than this file's
 * idea of what those series mean. A preview that agreed with the editor and
 * disagreed with the run would be worse than none.
 */

import { openModal, refreshModal } from './modal.js';
import * as ed from '../domain/edit.js';
import { el } from './parts.js';

const KIND_LABEL = {
	log: 'Logarithmic',
	linear: 'Even',
	times: 'Written out',
};

/** A time, short enough for a narrow field. */
const fmt = (v) => {
	const n = Number(v);
	if (!Number.isFinite(n)) return '';
	if (n !== 0 && (Math.abs(n) >= 1e5 || Math.abs(n) < 1e-3)) {
		return Number(n.toPrecision(6)).toExponential().replace('e+', 'e');
	}
	return String(Number(n.toPrecision(10)));
};

/**
 * @param {object} project the raw model
 * @param {{onChange: Function, onStatus?: Function}} hooks
 */
export function openOutputTimes(project, hooks) {
	const changed = () => { hooks.onChange?.(); refreshModal(); };

	openModal({
		title: 'Saved time points',
		subtitle: (project.simulation?.spacing === 'both'
			? 'Every series is combined into one set of times — sorted, without '
				+ 'duplicates, the start and the end always in it — and every step '
				+ 'the solver takes is added to them.'
			: 'Every series is combined into one set of times, sorted, without '
				+ 'duplicates — and the start and the end are always in it.'),
		build: (body) => {
			const sim = project.simulation ?? {};
			const t0 = Number(sim.start_time ?? 0);
			const t1 = Number(sim.end_time ?? 0);
			const series = ed.outputSeries(project);

			const list = el('div', { className: 'ot-list' });
			series.forEach((spec, i) => list.append(row(project, spec, i, {
				t0, t1, changed, onStatus: hooks.onStatus,
			})));
			if (!series.length) {
				list.append(el('p', { className: 'insp-hint' },
					'No series yet. Add one below.'));
			}
			body.append(el('div', { className: 'ot-box' }, list));

			// Adding one of each kind rather than one "add" and a kind to
			// choose afterwards: the three are different enough that the
			// choice *is* the action.
			const add = el('div', { className: 'ot-add' });
			for (const kind of ed.SERIES_KINDS) {
				const b = el('button', { type: 'button', className: 'ghost' },
					`+ ${KIND_LABEL[kind].toLowerCase()}`);
				b.title = kind === 'log'
					? 'Equal ratios: 1, 10, 100 — how a result spanning decades is read'
					: kind === 'linear'
						? 'Equal steps: for the first year of a run that starts at zero, '
							+ 'which a logarithmic series cannot describe'
						: 'Times written out by hand, for the few that matter';
				b.addEventListener('click', () => {
					try {
						ed.addOutputSeries(project, kind);
						changed();
					} catch (e) { hooks.onStatus?.(e.message, 'warn'); }
				});
				add.append(b);
			}
			body.append(add);

			// What the engine will actually save, from the engine's own
			// combiner.
			const times = ed.outputTimes(project);
			const shown = [...times].slice(0, 6).map(fmt);
			const tail = times.length > 8 ? [...times].slice(-2).map(fmt) : [];
			body.append(el('p', { className: 'ot-sum' },
				el('b', {}, `${times.length} saved time${times.length === 1 ? '' : 's'}`),
				': ',
				[...shown, ...(tail.length ? ['…', ...tail] : [])].join(', ')));
			body.append(el('p', { className: 'insp-hint' },
				`Anything outside ${fmt(t0)} to ${fmt(t1)} is left out — a time the `
				+ `solver never reaches is not a time it can report. Leave `
				+ `“from” or “to” empty for the run's own start and end.`));
		},
	});
}

/** One series: what kind it is, and the two or three numbers it needs. */
function row(project, spec, i, { t0, t1, changed, onStatus }) {
	const kind = ed.seriesKind(spec);
	const box = el('div', { className: 'ot-row' });

	const kindSel = el('select', { className: 'ot-kind' });
	for (const k of ed.SERIES_KINDS) {
		kindSel.append(el('option', { value: k, selected: k === kind }, KIND_LABEL[k]));
	}
	kindSel.addEventListener('change', () => {
		try {
			ed.updateOutputSeries(project, i, { kind: kindSel.value });
			changed();
		} catch (e) { onStatus?.(e.message, 'warn'); }
	});
	box.append(kindSel);

	const commit = (patch, input, back) => {
		try {
			ed.updateOutputSeries(project, i, patch);
			changed();
		} catch (e) {
			onStatus?.(e.message, 'warn');
			if (input) input.value = back;
		}
	};

	if (kind === 'times') {
		const written = (spec.times ?? []).map(fmt).join(', ');
		const input = el('input', {
			type: 'text', className: 'mono ot-times', value: written,
			placeholder: '0.1, 0.25, 0.5',
			title: 'Times, separated by commas or spaces',
		});
		input.addEventListener('change', () => {
			const parts = input.value.split(/[\s,;]+/).filter(Boolean);
			const bad = parts.find((p) => !Number.isFinite(Number(p)));
			if (bad !== undefined) {
				onStatus?.(`'${bad}' is not a time`, 'warn');
				input.value = written;
				return;
			}
			commit({ times: parts.map(Number) }, input, written);
		});
		box.append(input);
	} else {
		const num = (key, placeholder, title) => {
			const value = spec[key] == null ? '' : fmt(spec[key]);
			const input = el('input', {
				type: 'text', className: 'mono ot-num', value, placeholder, title,
			});
			input.addEventListener('change', () => commit({ [key]: input.value }, input, value));
			return el('label', { className: 'ot-field' },
				el('span', {}, key === 'from' ? 'from' : 'to'), input);
		};
		box.append(num('from', fmt(t0), 'The first time of this series; empty for the run’s start'));
		box.append(num('to', fmt(t1), 'The last; empty for the run’s end'));
		const points = String(spec.points ?? '');
		const n = el('input', {
			type: 'text', className: 'mono ot-num', value: points,
			title: 'How many points this series has between its own two ends',
		});
		n.addEventListener('change', () => commit({ points: n.value }, n, points));
		box.append(el('label', { className: 'ot-field' }, el('span', {}, 'points'), n));
	}

	// What this one contributes, which is not the same as what it asks for: a
	// series is clipped to the run, and to its own ends. One with nothing
	// inside the run is not a mistake the model refuses -- the times are
	// simply never reached -- but it is worth a warning, since a series that
	// quietly saves nothing looks exactly like one that is working.
	const mine = ed.seriesTimes(spec, t0, t1);
	box.append(el('span', {
		className: `ot-count${mine.length ? '' : ' is-empty'}`,
		title: mine.length
			? ''
			: `Every time in this series is outside ${fmt(t0)} to ${fmt(t1)}, so it `
				+ 'saves nothing. Change its ends, or the run\u2019s, or remove it.',
	}, mine.length ? `${mine.length} in the run` : 'nothing in the run'));

	const kill = el('button', {
		type: 'button', className: 'insp-entry-reset', title: 'Remove this series',
	}, '×');
	kill.addEventListener('click', () => {
		try {
			ed.deleteOutputSeries(project, i);
			changed();
		} catch (e) { onStatus?.(e.message, 'warn'); }
	});
	box.append(kill);
	return box;
}
