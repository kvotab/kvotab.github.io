/**
 * Check the run: the run on show solved again a hundred times more carefully,
 * and what moved.
 *
 * One window, three states: while the careful run goes (with Stop), what it
 * found, or why it could not. What it found is a sentence first -- the run
 * holds, nearly holds or does not -- then the states that moved most, each with
 * how far as a share of its size, when, and what each run has there, then what
 * each run was solved at; and *Run with the careful setting*, which writes the
 * tighter tolerances into the model as one edit and runs it. See
 * ../sim/checkrun.js for what is compared and why.
 */

import { el } from './parts.js';
import { openModal } from './modal.js';
import { dialogInfo } from './dialoginfo.js';
import { HOLDS, NEARLY, CAREFUL } from '../sim/checkrun.js';

const fmt = (v) => {
	if (v == null || !Number.isFinite(v)) return '—';
	if (v === 0) return '0';
	return Math.abs(v) >= 1e5 || Math.abs(v) < 1e-3 ? v.toExponential(3) : String(Number(v.toPrecision(5)));
};

/** A share as a per cent, to the digits that matter. */
const pct = (share) => {
	if (!Number.isFinite(share)) return 'all of it';
	const p = share * 100;
	if (p === 0) return '0 %';
	return `${p >= 10 ? p.toFixed(1) : p >= 0.01 ? p.toPrecision(2) : p.toExponential(1)} %`;
};

/**
 * @param {object} opts
 * @param {string} opts.timeUnit
 * @param {() => void} opts.onStop
 * @param {() => void} opts.onCareful   write the careful tolerances in and run
 * @param {() => boolean} [opts.isAboutShownRun]  whether the report is still
 *   about the run on show
 */
export function openCheckRunDialog({ timeUnit = '', onStop, onCareful, isAboutShownRun = () => true }) {
	const state = { running: { stage: 'building', fraction: 0 }, report: null, error: null };
	let handle = null;
	const redraw = () => handle?.refresh();

	handle = openModal({
		info: dialogInfo('check-run'),
		title: 'Check the run',
		subtitle: `Solved again with both tolerances ${CAREFUL} times tighter, and set against itself`,
		wide: true,
		className: 'check-run-modal',
		build(body) {
			body.replaceChildren();
			if (state.running) {
				const p = state.running;
				const word = p.stage === 'solving'
					? `Solving it again a hundred times more carefully… ${Math.round((p.fraction ?? 0) * 100)} %`
					: 'Building the model for the careful run…';
				body.append(el('p', { className: 'check-run-busy' }, word));
				const bar = el('div', { className: 'jac-bar' }, el('div', { className: 'jac-bar-fill' }));
				bar.firstChild.style.width = `${Math.round(Math.min(1, p.fraction ?? 0) * 100)}%`;
				body.append(bar);
				body.append(el('p', { className: 'hint' },
					'A careful run takes more steps than the run itself, usually a few times as many.'));
			}
			if (state.error) body.append(el('p', { className: 'prob-warn' }, state.error));
			if (state.report) body.append(reportBox(state.report, timeUnit, !isAboutShownRun()));

			const foot = el('div', { className: 'pdf-foot' });
			foot.append(el('span', { className: 'pdf-note' },
				state.running ? 'The run on show is not changed by this.'
					: state.report ? 'Nothing in the model has changed.' : ''));
			if (state.running) {
				const stop = el('button', { type: 'button', className: 'ghost' }, 'Stop');
				stop.addEventListener('click', () => onStop?.());
				foot.append(stop);
			} else if (state.report) {
				const careful = el('button', {
					type: 'button',
					className: state.report.verdict === 'holds' ? 'ghost' : 'primary',
				}, 'Run with the careful setting');
				careful.title = 'Writes the tighter tolerances into the model, as one edit that one undo '
					+ 'takes back, and runs it.';
				careful.addEventListener('click', () => { handle.close(); onCareful?.(state.report); });
				foot.append(careful);
			}
			const close = el('button', { type: 'button', className: 'ghost' }, 'Close');
			close.addEventListener('click', () => handle.close());
			foot.append(close);
			body.append(foot);
		},
	});

	return {
		handle,
		progress(p) { state.running = { stage: p.stage, fraction: p.fraction ?? 0 }; redraw(); },
		finished(report) { state.running = null; state.report = report; state.error = null; redraw(); },
		failed(message) { state.running = null; state.error = message; redraw(); },
		/** Whether the window is still open, for a reply that arrives after it was closed. */
		get open() { return !!handle?.dialog?.open; },
	};
}

/** What the careful run found: the verdict, the states that moved most, and what each run took. */
export function reportBox(r, timeUnit, earlier = false) {
	const box = el('div', { className: 'check-run-report' });
	if (earlier) {
		box.append(el('p', { className: 'prob-warn' },
			'This is about an earlier run than the one on show. Check the run again for this one.'));
	}
	const first = r.moved[0];
	const named = first
		? ` The most, ${first.label}, by ${pct(first.share)} of its size at ${fmt(first.at)} ${timeUnit}.`
		: '';
	const [cls, said] = r.verdict === 'holds'
		? ['is-ok', `The run holds: no state moved by ${HOLDS * 100} % of its size.${named}`]
		: r.verdict === 'nearly'
			? ['is-warn', `The run nearly holds: no state moved by ${NEARLY * 100} % of its size, though some by more than ${HOLDS * 100} %.${named}`]
			: ['is-bad', `The run does not hold: a state moved by ${pct(r.worst)} of its size.${named} `
				+ 'What is read off its curves is out by about that much.'];
	box.append(el('p', { className: `jac-verdict check-run-verdict ${cls}` }, said));

	if (r.moved.length) {
		const table = el('table', { className: 'opt-table check-run-table' });
		table.append(el('thead', {}, el('tr', {},
			el('th', {}, 'State'), el('th', {}, 'Moved by'), el('th', {}, `When (${timeUnit})`),
			el('th', {}, 'This run'), el('th', {}, 'Careful run'))));
		const tb = el('tbody');
		for (const m of r.moved) {
			tb.append(el('tr', { className: m.share >= HOLDS ? 'is-moved' : '' },
				el('td', { title: m.label }, m.label),
				el('td', { className: 'mono' }, pct(m.share)),
				el('td', { className: 'mono' }, fmt(m.at)),
				el('td', { className: 'mono' }, fmt(m.held)),
				el('td', { className: 'mono' }, fmt(m.careful))));
		}
		table.append(tb);
		box.append(table);
	}

	const steps = (n) => (Number.isFinite(n) ? `${n.toLocaleString()} steps` : 'its steps');
	box.append(el('p', { className: 'hint' },
		`This run: relative tolerance ${fmt(r.run.rtol)}, absolute ${fmt(r.run.abstol)}, ${steps(r.run.steps)}. `
		+ `The careful run: ${fmt(r.careful.rtol)} and ${fmt(r.careful.abstol)}, ${steps(r.careful.steps)} `
		+ `in ${r.careful.ms < 1000 ? `${Math.round(r.careful.ms)} ms` : `${(r.careful.ms / 1000).toFixed(1)} s`}, `
		+ `at this run’s ${r.times.toLocaleString()} output times. `
		+ 'A state’s size is the most it reaches in either run, or the absolute tolerance over the '
		+ 'relative where that is more: a state smaller than the run was asked to resolve is not judged '
		+ 'on its last digits.'
		+ (r.careful.floor ? ` The careful run’s relative tolerance is ${fmt(r.careful.rtol)}, as tight `
			+ 'as the formulas gain from, so it is less than a hundred times tighter than this run’s.' : '')));
	return box;
}
