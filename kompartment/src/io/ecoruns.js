/**
 * The runs an Ecolego assessment carries beside its model.
 *
 * An `.eas` is a project archive with its results in it: `simulation.xml` at
 * the root describes every run kept -- what was run, when, and which outputs
 * were saved -- and `simulation/results/` holds each run's numbers, one file
 * per run, named by the run's GUID (`<GUID>.dta`). Ecolego 5 kept one run, in
 * `results.dta`; Ecolego 6 keeps the current run and any it was asked to
 * archive, each under its own name and date, and leaves an empty `results.dta`
 * beside them.
 *
 * ## The result file
 *
 * Ecolego's `MappedDiskRepository`, read off its source and checked against
 * every assessment here:
 *
 *     0     int32   how many simulations (1 for a single run)
 *     4     int32   how many output times
 *     1024  blocks, one per saved output, each
 *             0   int64  the GUID's low half
 *             8   int64  the GUID's high half
 *             16  int64  how many bytes of numbers follow the 64-byte header
 *             64  the numbers, big-endian doubles
 *
 * A block's numbers run simulation by simulation, then time by time, then
 * through the output's own indices -- the first index fastest in a file
 * Ecolego 6 wrote, the last fastest in one Ecolego 5 wrote (see `loadRun`).
 * A value that cannot change over the run is stored once per simulation
 * rather than once per time. The output times are themselves an output,
 * called `time`.
 *
 * ## What it becomes
 *
 * One series per output and index, labelled the way this tool labels its own
 * -- the block's name as the model has it, the index names in brackets -- so
 * the Chart and the Table can put a stored series beside the series of the
 * same name from a run here. An output this tool did not import (a block type
 * it skips, a sub-system, the interface blocks) has nothing to stand beside,
 * and is counted rather than kept.
 *
 * **Ecolego 6 stores a transfer as its flux** -- its rate times its donor,
 * where it multiplies by the donor -- and this tool reports a transfer's rate,
 * as Ecolego 5 stored it. So a flux from Ecolego 6 is divided by the stored
 * donor, at the same index, to put the two on the same footing; where the
 * donor holds nothing the solver resolved, the rate is not defined there and
 * is left out (NaN), and a transfer whose donor was not saved is counted with
 * the rest of what could not be matched. (33 of 33 such transfers in an
 * Ecolego 5 assessment hold the rate, and 35 of 35 in the Ecolego 6 one of the
 * same model the flux.)
 *
 * **Only single runs.** A probabilistic run keeps every realisation, and is
 * counted and left out.
 *
 * Nothing is decoded until a run is asked for: an assessment can hold a dozen
 * runs of a large model, and the archive inflates an entry only when it is
 * read.
 */

import { parseXML, child, children, childText, childNumber, XMLError } from './xml.js';

const HEADER = 1024;
const BLOCK_HEADER = 64;

/** The GUID text a block header's first sixteen bytes stand for. */
function guidAt(bytes, at) {
	// Ecolego writes the low half first and the high half second, and a GUID's
	// text reads from the high half.
	let s = '';
	for (const from of [at + 8, at]) {
		for (let i = from; i < from + 8; i++) s += bytes[i].toString(16).padStart(2, '0');
	}
	s = s.toUpperCase();
	return `${s.slice(0, 8)}-${s.slice(8, 12)}-${s.slice(12, 16)}-${s.slice(16, 20)}-${s.slice(20)}`;
}

/**
 * One result file: how many simulations and times it holds, and where each
 * output's numbers are. Nothing is decoded here.
 *
 * @param {Uint8Array} bytes
 * @returns {{simulations: number, times: number, blocks: Map<string, {start: number, size: number}>,
 *            view: DataView}}
 */
export function readResultFile(bytes) {
	if (!(bytes instanceof Uint8Array) || bytes.length < HEADER) {
		throw new Error('it is shorter than the header a result file starts with');
	}
	const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
	const simulations = view.getInt32(0, false);
	const times = view.getInt32(4, false);
	const blocks = new Map();
	let at = HEADER;
	while (at < bytes.length) {
		if (at + BLOCK_HEADER > bytes.length) throw new Error('it ends inside a block header');
		const size = Number(view.getBigInt64(at + 16, false));
		const start = at + BLOCK_HEADER;
		if (!(size >= 0) || start + size > bytes.length) {
			throw new Error('a block runs past the end of the file');
		}
		blocks.set(guidAt(bytes, at), { start, size });
		at = start + size;
	}
	return { simulations, times, blocks, view };
}

/** A block's numbers, as this machine holds doubles. */
function doublesOf(file, block) {
	const n = Math.floor(block.size / 8);
	const out = new Float64Array(n);
	for (let i = 0; i < n; i++) out[i] = file.view.getFloat64(block.start + i * 8, false);
	return out;
}

/** An entry's name with either separator, as these archives are written on Windows too. */
const slashed = (name) => name.replace(/\\/g, '/');

/**
 * The runs an assessment holds, ready to be read.
 *
 * @param {Map<string, Uint8Array>} entries the archive, as `unzip` gives it
 * @param {{project: object, blockIds?: Map<string, string>,
 *   timeUnitOf?: (text: string) => (string|null)}} model the project the
 *   archive's model.xml was imported into, the importer's map from Ecolego's
 *   ids to the names the blocks were given, and how it names a time unit
 *   Ecolego spells (`y`, `years`, `a` are all `year`)
 * @returns {{runs: Array<object>, probabilistic: number, shown: number}|null}
 *   null for an archive that keeps no run at all; each run has `name`, `date`,
 *   `archived`, `matched` (how many of the outputs it lists are blocks of the
 *   model) and `load()`, which decodes it (once) and returns
 *   `{t, timeUnit, series, left}`; `shown` is the one to show first (see
 *   `defaultRun`), or -1
 */
export function readStoredRuns(entries, { project, blockIds = new Map(), timeUnitOf = null }) {
	let xmlName = null;
	const files = new Map();
	for (const name of entries.keys()) {
		const n = slashed(name);
		if (n === 'simulation.xml') xmlName = name;
		const m = /^simulation\/results\/([^/]+)\.dta$/i.exec(n);
		if (m) files.set(m[1].toUpperCase(), name);
	}
	if (!xmlName || !files.size) return null;
	let root;
	try {
		root = parseXML(new TextDecoder('utf-8').decode(entries.get(xmlName)));
	} catch (e) {
		if (e instanceof XMLError) return null;
		throw e;
	}
	const top = root.name === 'simulation-model' ? root : null;
	if (!top) return null;

	const runs = [];
	let probabilistic = 0;
	const known = blocksByName(project);
	for (const ctx of children(top, 'simulation-context')) {
		const info = child(ctx, 'simulation-info');
		const kind = (childText(info, 'simulation-info-type') ?? '').toUpperCase();
		const key = (ctx.attrs.guid ?? '').trim().toUpperCase() || 'RESULTS';
		const entryName = files.get(key);
		if (!entryName) continue;
		if (kind && kind !== 'DETERMINISTIC') { probabilistic++; continue; }
		let loaded = null;
		// Counted off the list alone, so a run with nothing to stand beside
		// is not the one shown first: an assessment can keep runs of another
		// model, or runs that saved only what this tool does not import.
		const matched = children(child(ctx, 'simulation-outputs'), 'output-info')
			.filter((o) => o.attrs.id && o.attrs.id !== 'time' && known.has(blockIds.get(o.attrs.id) ?? o.attrs.id))
			.length;
		runs.push({
			name: childText(info, 'simulation-name') ?? '',
			date: childNumber(info, 'date'),
			archived: ctx.attrs.archive === 'true',
			matched,
			// Read once, and only when somebody asks for this run.
			load: () => (loaded ??= loadRun(entries.get(entryName), ctx, info, project, blockIds, timeUnitOf)),
		});
	}
	if (!runs.length && !probabilistic) return null;
	const stored = { runs, probabilistic };
	stored.shown = defaultRun(stored);
	return stored;
}

/**
 * The run shown first: one with something to stand beside, the current one
 * rather than an archived one, and the newest of those.
 */
export function defaultRun(stored) {
	const runs = stored?.runs ?? [];
	if (!runs.length) return -1;
	const order = runs.map((r, k) => k).sort((a, b) => {
		const ra = runs[a];
		const rb = runs[b];
		if ((ra.matched > 0) !== (rb.matched > 0)) return ra.matched > 0 ? -1 : 1;
		if (ra.archived !== rb.archived) return ra.archived ? 1 : -1;
		return (rb.date ?? -Infinity) - (ra.date ?? -Infinity) || b - a;
	});
	return order[0];
}

/** Every block of the model, by the name a series is labelled with. */
function blocksByName(project) {
	const out = new Map();
	for (const [collection, kind] of [
		['compartments', 'compartment'], ['expressions', 'expression'], ['parameters', 'parameter'],
		['transfers', 'transfer'], ['lookups', 'lookup'], ['index_reductions', 'index_reduction'],
		['block_reductions', 'block_reduction'], ['min_maxes', 'min_max'],
		['running_means', 'running_mean'], ['snapshots', 'snapshot'], ['delays', 'delay'],
		['triggers', 'trigger'],
	]) {
		for (const b of project?.[collection] ?? []) {
			out.set(b.system ? `${b.system}.${b.name}` : b.name, { kind, block: b });
		}
	}
	return out;
}

function loadRun(bytes, ctx, info, project, blockIds, timeUnitOf) {
	const file = readResultFile(bytes);
	// Ecolego 6 names each run by a GUID; Ecolego 5 kept one, unnamed. Two of
	// the file's conventions follow which it was -- see the two uses below,
	// each measured on assessments of one model saved by both.
	const six = !!(ctx.attrs.guid ?? '').trim();
	if (file.simulations !== 1) {
		throw new Error(`it holds ${file.simulations} simulations where a single run holds one`);
	}
	const nt = file.times;
	// The lists every output of this run is indexed by, by name -- Ecolego 6
	// writes them once for the run. Ecolego 5 writes each output's own.
	const lists = new Map();
	for (const l of children(child(ctx, 'index-lists'), 'index-list')) {
		if (l.attrs.name) lists.set(l.attrs.name, children(l, 'index').map((i) => i.text.trim()));
	}
	const outputs = children(child(ctx, 'simulation-outputs'), 'output-info');
	const timeInfo = outputs.find((o) => o.attrs.id === 'time');
	const timeBlock = timeInfo ? file.blocks.get((timeInfo.attrs.guid ?? '').trim().toUpperCase()) : null;
	if (!timeBlock) throw new Error('it has no output times');
	const t = doublesOf(file, timeBlock).subarray(0, nt);

	const known = blocksByName(project);
	const series = new Map();
	const left = { notInModel: 0, unreadable: 0, noDonor: 0 };
	const fluxes = [];
	for (const o of outputs) {
		const id = o.attrs.id;
		if (!id || id === 'time') continue;
		const block = file.blocks.get((o.attrs.guid ?? '').trim().toUpperCase());
		// A sub-system's row, or an output the run did not keep.
		if (!block) continue;
		const named = blockIds.get(id) ?? (known.has(id) ? id : null);
		const found = named ? known.get(named) : null;
		if (!found) { left.notInModel++; continue; }

		// Which index names each dimension holds, in the output's own order.
		const written = (o.attrs['index-lists'] ?? '').split(',').map((s) => s.trim()).filter(Boolean);
		const dims = written.length
			? written.map((n) => lists.get(n) ?? null)
			: children(child(o, 'index-lists'), 'index-list')
				.map((l) => children(l, 'index').map((i) => i.text.trim()));
		if (dims.some((d) => !d)) { left.unreadable++; continue; }
		const cells = dims.reduce((n, d) => n * d.length, 1);
		const timeDependent = childText(o, 'time-dependent') === 'true';
		if (block.size !== cells * (timeDependent ? nt : 1) * 8) { left.unreadable++; continue; }
		const values = doublesOf(file, block);
		const unit = childText(child(o, 'output-units'), 'output-unit') ?? '';
		// Which index runs fastest depends on which Ecolego wrote the file:
		// the first in Ecolego 6's, whose arrays run that way, and the last in
		// Ecolego 5's. Read the other way round, two assessments of one model,
		// one saved by each, put 203 of 255 inventory cells under the wrong
		// source.
		const lastFastest = !six;

		for (let c = 0; c < cells; c++) {
			const names = new Array(dims.length);
			let rest = c;
			for (let k = 0; k < dims.length; k++) {
				const j = lastFastest ? dims.length - 1 - k : k;
				names[j] = dims[j][rest % dims[j].length];
				rest = Math.floor(rest / dims[j].length);
			}
			const label = names.length ? `${named} [${names.join(', ')}]` : named;
			let v;
			if (timeDependent) {
				v = new Float64Array(nt);
				for (let ti = 0; ti < nt; ti++) v[ti] = values[ti * cells + c];
			}
			// What a series of a run here says about itself, so the chart's
			// picker can filter these as it filters those.
			const own = found.block.index_lists ?? [];
			const about = {
				unit, block: named, kind: found.kind,
				index: names.length ? names : null,
				dims: own.length === names.length ? [...own] : [],
			};
			const entry = timeDependent ? { values: v, ...about } : { constant: values[c], ...about };
			series.set(label, entry);
			const tr = found.kind === 'transfer' ? found.block : null;
			if (six && tr && tr.from && tr.multiply_by_donor !== false && timeDependent) {
				fluxes.push({ label, entry, donor: `${tr.from}${names.length ? ` [${names.join(', ')}]` : ''}` });
			}
		}
	}
	// Ecolego 6 says it for the run; Ecolego 5 only as the unit of `time`. As
	// the model's own is named, so the two can be compared: a model whose
	// unit was changed after the run is not one the run can stand beside.
	const said = childText(info, 'time-unit')
		?? childText(child(timeInfo, 'output-units'), 'output-unit') ?? null;
	const timeUnit = said == null ? null : (timeUnitOf?.(said) ?? said);
	// A stored flux over the stored donor is the rate this tool reports --
	// where the donor holds something the run resolved. Below the run's
	// absolute tolerance the solver does not control it, and twelve decades
	// below its own peak it is rounding: a backfill of 8e-10 Bq, under a
	// tolerance of 1 Bq, made a rate of 1e4 out of one of 1e-5, and one of
	// 5e-125 Bq a rate of 6e121. Left out there, as a log axis leaves out a
	// zero.
	const floor = childNumber(info, 'abs-error-tolerance') ?? Number(project?.simulation?.abstol ?? 0);
	for (const f of fluxes) {
		const donor = series.get(f.donor);
		const d = donor?.values ?? (donor && Number.isFinite(donor.constant)
			? new Float64Array(nt).fill(donor.constant) : null);
		if (!d) { series.delete(f.label); left.noDonor++; continue; }
		let peak = 0;
		for (let i = 0; i < nt; i++) if (Math.abs(d[i]) > peak) peak = Math.abs(d[i]);
		const below = Math.max(peak * 1e-12, Number.isFinite(floor) ? floor : 0);
		const rate = new Float64Array(nt);
		for (let i = 0; i < nt; i++) {
			const r = Math.abs(d[i]) > below ? f.entry.values[i] / d[i] : NaN;
			rate[i] = Number.isFinite(r) ? r : NaN;
		}
		f.entry.values = rate;
		// And in a rate's unit, per unit time whatever it moves: the flux's
		// was the donor's over time.
		f.entry.unit = `1/${timeUnit ?? 'year'}`;
	}
	return {
		t,
		timeUnit,
		start: childNumber(info, 'start-time'),
		end: childNumber(info, 'end-time'),
		series,
		left,
	};
}
