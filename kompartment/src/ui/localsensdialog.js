/**
 * Choosing parameters to take the derivative to, and reading the answer.
 *
 * Two halves. Before the run: which parameters, with the cost said plainly --
 * each one adds a whole copy of the state vector to the solve and an extra
 * evaluation of the derivative to every step, so this is a question about a
 * handful and the dialog says so rather than letting somebody tick six hundred.
 *
 * After it: the elasticity of the chosen output against time. Not `dy/dp`,
 * which carries the units of both and cannot be compared between a parameter in
 * years and one in m^3/kg -- the elasticity `(p/y)·(dy/dp)` is a relative change
 * for a relative change, so "1% more of this gives 0.4% more of that", and two
 * parameters can be put side by side.
 */

import { el } from './parts.js';
import { openModal } from './modal.js';

const COLOURS = ['--series-1', '--series-2', '--series-3', '--series-4', '--series-5', '--series-6'];
const FALLBACK = ['#4a9eff', '#f08c3a', '#54c08a', '#d96c8a', '#9b7fe0', '#d8c15a'];

/** The elasticities against time, on a scale that keeps zero in view. */
function paint(canvas, t, curves) {
	const ctx = canvas.getContext('2d');
	if (!ctx) return;
	const dpr = window.devicePixelRatio || 1;
	const w = canvas.clientWidth || 420;
	const h = canvas.clientHeight || 170;
	canvas.width = Math.round(w * dpr);
	canvas.height = Math.round(h * dpr);
	ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
	ctx.clearRect(0, 0, w, h);
	if (!curves.length || !t.length) return;

	const style = getComputedStyle(canvas);
	const ink = style.getPropertyValue('--text-muted').trim() || '#888';
	const faint = style.getPropertyValue('--border').trim() || '#333';
	const pad = { l: 38, r: 8, t: 8, b: 17 };
	const pw = w - pad.l - pad.r;
	const ph = h - pad.t - pad.b;

	let lo = 0;
	let hi = 0;
	for (const c of curves) {
		for (const v of c.y) {
			if (!Number.isFinite(v)) continue;
			if (v < lo) lo = v;
			if (v > hi) hi = v;
		}
	}
	// Zero is always on the chart: the sign of an elasticity is half of what it
	// says, and a scale that cropped zero would hide which side a curve is on.
	if (lo === hi) { lo -= 1; hi += 1; }
	const t0 = t[0];
	const tN = t[t.length - 1];
	const useLog = t0 > 0 && tN / t0 > 100;
	const sx = (x) => pad.l + (useLog
		? (Math.log(x) - Math.log(t0)) / (Math.log(tN) - Math.log(t0))
		: (x - t0) / (tN - t0)) * pw;
	const sy = (v) => pad.t + (1 - (v - lo) / (hi - lo)) * ph;

	ctx.font = '9px system-ui, sans-serif';
	ctx.textAlign = 'right';
	ctx.textBaseline = 'middle';
	for (let k = 0; k <= 4; k++) {
		const v = lo + ((hi - lo) * k) / 4;
		const y = sy(v);
		ctx.strokeStyle = faint;
		ctx.globalAlpha = Math.abs(v) < (hi - lo) * 1e-9 ? 0.9 : 0.3;
		ctx.beginPath();
		ctx.moveTo(pad.l, y + 0.5);
		ctx.lineTo(pad.l + pw, y + 0.5);
		ctx.stroke();
		ctx.globalAlpha = 1;
		ctx.fillStyle = ink;
		ctx.fillText(v.toPrecision(2), pad.l - 4, y);
	}

	curves.forEach((c, i) => {
		ctx.strokeStyle = style.getPropertyValue(COLOURS[i % COLOURS.length]).trim()
			|| FALLBACK[i % FALLBACK.length];
		ctx.lineWidth = 1.8;
		ctx.lineJoin = 'round';
		ctx.beginPath();
		let pen = false;
		for (let j = 0; j < t.length; j++) {
			const v = c.y[j];
			if (!Number.isFinite(v) || (useLog && !(t[j] > 0))) { pen = false; continue; }
			const px = sx(t[j]);
			const py = sy(v);
			if (!pen) { ctx.moveTo(px, py); pen = true; } else ctx.lineTo(px, py);
		}
		ctx.stroke();
	});
}

/**
 * Which parameters to differentiate against.
 *
 * @param {object} opts
 * @param {Array} opts.slots   every parameter, from `parameterSlots`
 * @param {number} opts.states how many states the model has, for the cost
 * @param {boolean} [opts.exact] whether `df/dp` is generated for this model
 *   rather than differenced, which is what each parameter costs per step
 * @param {number} opts.most
 * @param {(names: string[]) => void} opts.onRun
 */
export function openLocalSensitivityPicker({
	slots, states, exact = true, most = 12, onRun,
}) {
	const chosen = new Set();
	let query = '';

	const modal = openModal({
		wide: true,
		title: 'Sensitivity to a parameter',
		subtitle: 'dy/dp, integrated alongside the model rather than differenced from two runs',
		// The subtitle is the claim; `exact` below says whether the driving
		// term of the sensitivity equations lives up to it on this model.
		build: (body) => {
			// The two pieces of the cost line that a tick moves, held so they
			// can be rewritten in place.
			const count = el('b', {}, `${chosen.size} chosen`);
			const cost = el('span', {}, '.');
			const q = query.trim().toLowerCase();
			const found = q
				? slots.filter((s) => s.label.toLowerCase().includes(q))
				: slots;

			body.append(el('p', { className: 'prob-summary' },
				el('p', {},
					'Each parameter adds a copy of the whole state vector to the solve — ',
					el('b', {}, `${states.toLocaleString()} states`),
					' apiece — and ',
					// What a parameter costs per step, which is not the same
					// on every model: df/dp is generated where it can be, and
					// differenced where a far-field path, a waste package or a
					// disruptive event makes that impossible.
					exact
						? 'one more pass over the equations to every step. '
						: 'an extra evaluation of the whole derivative to every step. ',
					count,
					cost),
				exact ? null : el('p', { className: 'hint' },
					'This model has a far-field pathway, a waste package or a disruptive '
					+ 'event, so df/dp is differenced rather than differentiated — an '
					+ 'approximation, and the slower of the two.')));

			const search = el('input', {
				type: 'search', className: 'ep-search', value: query,
				placeholder: `Search ${slots.length.toLocaleString()} parameters`,
				'aria-label': 'Search parameters',
			});
			search.addEventListener('input', () => { query = search.value; modal.refresh(); });
			body.append(el('div', { className: 'pdf-row pdf-row-wide' },
				el('label', {}, 'Find'), search));

			const list = el('div', { className: 'prob-list' });
			// The boxes, so a tick can put the others right without the dialog
			// being rebuilt around them. `.prob-list` is a scroller, and a
			// rebuild sends it back to the top -- which on a search that found
			// the parameter forty rows down means finding it again for every
			// one that is ticked.
			const boxes = [];
			for (const s of found.slice(0, 200)) {
				const box = el('input', {
					type: 'checkbox', checked: chosen.has(s.label),
					disabled: !chosen.has(s.label) && chosen.size >= most,
				});
				boxes.push({ box, label: s.label });
				box.addEventListener('change', () => {
					if (box.checked) chosen.add(s.label);
					else chosen.delete(s.label);
					retally();
				});
				list.append(el('label', { className: 'prob-item is-pick' },
					box,
					el('code', {}, s.label),
					el('span', { className: 'mono' }, String(s.value))));
			}
			if (found.length > 200) {
				list.append(el('div', { className: 'prob-more' },
					`Showing 200 of ${found.length.toLocaleString()} — narrow the search.`));
			}
			body.append(list);

			// Said whenever the limit is reached, which is a thing a tick can
			// do -- so it is drawn once and hidden, rather than appearing and
			// disappearing with a rebuild.
			const full = el('p', { className: 'prob-warn' },
				`${most} at a time is the limit: past that the augmented solve is `
				+ `larger than the model by an order of magnitude, and the answer for `
				+ `one parameter does not depend on which others were asked for — so `
				+ `two runs of six say exactly what one run of twelve would.`);
			body.append(full);

			const go = el('button', {
				type: 'button', className: 'primary', disabled: !chosen.size,
			}, 'Run');

			/**
			 * What a tick changes, without rebuilding what it does not.
			 *
			 * Three things depend on how many are chosen: the cost line, which
			 * boxes may still be ticked, and whether there is anything to run.
			 * Everything else on the dialog is the same as it was, and
			 * redrawing it would cost the scroll position and the caret.
			 */
			function retally() {
				count.textContent = `${chosen.size} chosen`;
				cost.textContent = chosen.size
					? `, so the solve is ${((1 + chosen.size) * states).toLocaleString()} states.`
					: '.';
				for (const b2 of boxes) {
					b2.box.disabled = !chosen.has(b2.label) && chosen.size >= most;
				}
				full.hidden = chosen.size < most;
				go.disabled = !chosen.size;
			}
			retally();
			go.addEventListener('click', () => { modal.close(); onRun([...chosen]); });
			const cancel = el('button', { type: 'button', className: 'ghost' }, 'Cancel');
			cancel.addEventListener('click', () => modal.close());
			body.append(el('div', { className: 'pdf-foot' },
				el('span', { className: 'pdf-note' },
					'Exact to the solver’s own tolerance, and needs no distributions.'),
				cancel, go));
		},
	});
	return modal;
}

/**
 * The answer: elasticity against time, per parameter, for one state.
 *
 * @param {object} opts
 * @param {Float64Array} opts.t
 * @param {Array} opts.chosen   the parameters, with their values
 * @param {Array} opts.states   name, y, sens, elasticity
 * @param {string} opts.timeUnit
 * @param {object} opts.stats
 */
export function openLocalSensitivityResult({ t, chosen, states, timeUnit = 'year', stats }) {
	let which = 0;
	const modal = openModal({
		wide: true,
		title: 'Sensitivity to a parameter',
		subtitle: `${stats.states.toLocaleString()} states solved in `
			+ `${(stats.ms / 1000).toFixed(1)} s — elasticity, a relative change for a `
			+ 'relative change',
		build: (body) => {
			const pick = el('select', {});
			states.forEach((s, i) => {
				pick.append(el('option', { value: String(i), selected: i === which }, s.name));
			});
			pick.addEventListener('change', () => { which = Number(pick.value); modal.refresh(); });
			body.append(el('div', { className: 'pdf-row pdf-row-wide' },
				el('label', {}, 'Of'), pick));

			const s = states[which];
			const curves = chosen.map((p, j) => ({ label: p.label, y: s.elasticity[j] }));
			const canvas = el('canvas', { className: 'sens-canvas' });
			body.append(el('div', { className: 'sens-chart' }, canvas));
			const key = el('div', { className: 'sens-key' });
			curves.forEach((c, i) => {
				key.append(el('span', { className: `sens-key-item c${i % 6}` }, c.label));
			});
			body.append(key);
			requestAnimationFrame(() => paint(canvas, t, curves));

			// The numbers at the end of the run, which is the one time anybody
			// quotes -- and the raw derivative beside the elasticity, since the
			// elasticity is the comparable one and the derivative is the one
			// with the units.
			const last = t.length - 1;
			const table = el('div', { className: 'sens-table' },
				el('div', { className: 'sens-head' },
					el('span', {}, 'Parameter'),
					el('span', {}, `Elasticity at ${t[last]} ${timeUnit}`),
					el('span', {}, 'dy/dp')));
			chosen.forEach((p, j) => {
				const e = s.elasticity[j][last];
				table.append(el('div', { className: 'sens-row' },
					el('code', { title: `${p.label} = ${p.value}` }, p.label),
					el('span', { className: 'mono' }, Number.isFinite(e) ? e.toFixed(4) : '—'),
					el('span', { className: 'mono' }, s.sens[j][last].toExponential(3))));
			});
			body.append(table);

			body.append(el('p', { className: 'sens-note' },
				'An elasticity of 0.4 means a 1% change in the parameter gives a 0.4% '
				+ 'change in this block. It is dimensionless, so two parameters measured '
				+ 'in different things can be compared; dy/dp beside it cannot.'));

			const done = el('button', { type: 'button', className: 'primary' }, 'Close');
			done.addEventListener('click', () => modal.close());
			body.append(el('div', { className: 'pdf-foot' },
				el('span', { className: 'pdf-note' },
					'Integrated with the model, to the same tolerance.'),
				done));
		},
	});
	return modal;
}
