/**
 * A run's results as an HDF5 tree.
 *
 * The shape is Ecolego's, read off the files it writes and the ones the
 * result browser at kvotab.se ships as samples. Nothing in the format says any
 * of this: an HDF5 file is a tree of arrays, and the *convention* below is
 * what makes a particular tree a result file rather than a bag of numbers.
 *
 *     /time                        the output grid, once, with its unit
 *     /IndexLists/Radionuclides    the members of each index list, by name
 *     /Soil/                       a block, as a group, when it is indexed
 *          @IndexLists = ['Radionuclides']
 *          @time_dependent = 'TRUE'
 *          Cs-137                  one series per member
 *          H-3
 *     /NearField/Flux              a block that is not indexed, as a dataset
 *
 * The browser reads exactly these: `/time` is the x-axis of everything;
 * `time_dependent` is what makes a dataset plottable against it; and a group
 * with an `IndexLists` naming `Radionuclides` gets the chart that draws all of
 * its children together, which is the chart a safety assessment is read in.
 *
 * Two dimensions nest, as they do in Ecolego's own files, where a dose is at
 * `/biosphere/1BLA/drained_mire/total/Cs-137`: the nuclide is the leaf and
 * everything else is a group on the way down. A block indexed by areas and
 * nuclides is therefore `/Dose/<area>/<nuclide>`, and each `<area>` is a group
 * carrying the `IndexLists` that gets the nuclides drawn together.
 *
 * Attributes carry everything a reader of the file might otherwise have to
 * guess: what a series is measured in, which block it came from, what kind of
 * block that was, and -- on the root -- which model, which solver and when.
 *
 * **A value that cannot change over the run is one value**, not the same
 * number at every output time: a parameter, a table's point, an expression of
 * parameters alone, the peak of a series. Its dataset holds that number -- and
 * in a file of realisations one number per realisation -- and says
 * `time_dependent = 'FALSE'`, so a reader does not take it for a series over
 * `/time` -- the result browser draws it flat across a time chart only when
 * it is selected beside a series -- and nobody stores it four hundred times
 * over. Which values those are is the model's to say, not the numbers': a
 * compartment that stays at nothing is still a quantity that moves, and is
 * still drawn with its nuclides. See `timeDependentOf` in ../sim/runner.js.
 */

import { F64, F32, STR, group, dataset, put } from './hdf5.js';

/** What a name has to be before it can be a link. */
function linkName(s) {
	// A slash is the one character HDF5 keeps for itself. A dot is fine in a
	// name and is left alone: `Cs-137` and `C-14-org` read as themselves, and
	// a block called `k.eff` should too.
	const out = String(s ?? '').replace(/\//g, '⁄').trim();
	return out === '' || out === '.' || out === '..' ? '_' : out;
}

/** Puts `node` at `path`, working around a name that is already taken. */
function place(root, path, node) {
	try {
		return put(root, path, node);
	} catch (e) {
		// Two different things that want one path: a block and a sub-system
		// with the same name, or two index values that differ only by a
		// slash. Numbered rather than dropped -- a result that is not in the
		// file is worse than one with an awkward name.
		const head = path.slice(0, -1);
		const last = path[path.length - 1];
		for (let n = 2; n < 1000; n++) {
			try {
				return put(root, [...head, `${last} (${n})`], node);
			} catch (again) { /* keep counting */ }
		}
		throw e;
	}
}

/**
 * Where one series goes, and which group carries its index list.
 *
 * @returns {{path: string[], leafDim: string|null}}
 */
function pathOf(o) {
	const block = String(o.block ?? o.label ?? 'value').split('.').map(linkName);
	const dims = o.dims ?? [];
	const index = o.index ?? [];
	if (!dims.length || !index.length) return { path: block, leafDim: null };
	// The nuclide is the leaf when there is one, because that is the axis a
	// result is read along and the one the browser draws together. Otherwise
	// the last dimension is, which keeps the order the model wrote them in.
	let leaf = index.length - 1;
	if (o.nuclide != null) {
		const at = index.indexOf(o.nuclide);
		if (at >= 0) leaf = at;
	}
	const rest = index.filter((_, i) => i !== leaf).map(linkName);
	return { path: [...block, ...rest, linkName(index[leaf])], leafDim: dims[leaf] ?? null };
}

/** Values as doubles, without a copy when they already are. */
const asDoubles = (v) => (v instanceof Float64Array ? v : Float64Array.from(v));

/**
 * The model's description, as the markup the result browser will render.
 *
 * `Information` is the attribute that browser shows as HTML: any string
 * attribute holding a tag is put into the page rather than printed, so the
 * description -- which after an import is four lines saying where the model
 * came from, what is in it and what it runs -- reads as four lines there
 * instead of as one run-on paragraph.
 *
 * The text is escaped first. The description field in this application is
 * plain text: the sidebar edits it in a textarea and the Information view puts
 * it in a paragraph, so a `<` somebody typed is a `<` they meant, and passing
 * it through unescaped would let the file's own content decide what the page
 * does. Blank lines become paragraphs and single newlines become breaks, which
 * is the whole of the structure a plain-text field can carry.
 */
export function descriptionHTML(text) {
	const clean = String(text ?? '').replace(/\r\n?/g, '\n').trim();
	if (!clean) return null;
	const escape = (s) => s
		.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
	return clean.split(/\n{2,}/)
		.map((para) => `<p>${escape(para).replace(/\n/g, '<br>')}</p>`)
		.join('');
}

/** A time, an hour and a minute, in the shape Ecolego's own files use. */
function stamp(when) {
	const two = (n) => String(n).padStart(2, '0');
	return `${when.getFullYear()}-${two(when.getMonth() + 1)}-${two(when.getDate())} `
		+ `${two(when.getHours())}:${two(when.getMinutes())}:${two(when.getSeconds())}`;
}

/**
 * The tree for a run.
 *
 * @param {object} options
 * @param {Float64Array} options.t          the output times
 * @param {Array} options.outputs           the series descriptors, in order
 * @param {(i: number) => Float64Array} options.column  one series' values
 * @param {number[]} options.which          which outputs to write, by index
 * @param {object} options.project          the model, for its name and settings
 * @param {Array<{name: string, elements: string[]}>} options.indexLists
 * @param {Date} options.now
 * @param {{iterations: number, matrixFor: (i: number) => (Float32Array|null)}}
 *   [options.realisations]  every run of a probabilistic result, rather than
 *   one curve: `matrixFor` returns `times × iterations` values for a series,
 *   flat and time-major -- or just `iterations` of them for one that cannot
 *   change over the run -- or null for a series that was not part of the run
 * @param {{iterations: number, of: 'mean'|number}} [options.sample]  where one
 *   curve came from, when it is not the deterministic run but the mean of a
 *   probabilistic one or a single named realisation out of it. The values
 *   themselves arrive through `column` like any other; this only says what they
 *   are, so a file cannot be mistaken for a deterministic run of the same model
 * @returns the root group, ready for `writeHDF5`
 */
export function resultTree({
	t, outputs, column, which, project = {}, indexLists = [], now = new Date(),
	realisations = null, sample = null,
}) {
	const sim = project.simulation ?? {};
	const timeUnit = sim.time_unit ?? 'year';
	const created = stamp(now);
	const root = group({
		// What was run, and what ran it. `created_time` is the name Ecolego's
		// files use, so a browser showing both side by side shows one column.
		model: project.name ?? 'model',
		created_time: created,
		source: 'Kompartment',
		time_unit: timeUnit,
		start_time: Number(sim.start_time ?? 0),
		end_time: Number(sim.end_time ?? 0),
		solver: String(sim.solver ?? ''),
		series: which.length,
		probabilistic: !!realisations,
		// `n_iter` is what the result browser reads to know how many runs are
		// behind a series -- it is asked for at the root, once, rather than
		// counted from a dataset's shape. Written only when there are runs to
		// count, since an `n_iter` of 1 is what a deterministic file means by
		// saying nothing.
		...(realisations ? { n_iter: realisations.iterations } : {}),
		// A single curve that came out of a probabilistic run says so, and says
		// which curve it is. Without this the mean of a thousand runs and the
		// deterministic run are two files that look identical and are not the
		// same number anywhere -- and for a skewed quantity, which a dose is,
		// the mean is not even close to the one run at the central values.
		...(sample ? {
			n_iter: sample.iterations,
			realisation: sample.of === 'mean' ? 'mean' : Number(sample.of),
		} : {}),
		// What this model is, in the model's own words -- as markup, because
		// that is what the reader on the other end makes of it. Left out when
		// there is nothing to say rather than written empty.
		Information: descriptionHTML(project.description),
	});

	// `probabilistic` on /time says whether the *time axis* is a matrix with one
	// row per iteration, which the browser asks before it reads it. It is not,
	// even for a probabilistic run: every realisation here is reported on the
	// same output grid, so one row of times serves all of them. That is a
	// different question from whether the series are probabilistic, and the two
	// attributes are answered separately for that reason. Said rather than left
	// out, because an absent attribute and a false one only read alike by
	// accident.
	put(root, ['time'], dataset(asDoubles(t), F64, {
		unit: timeUnit, created_time: created, name: 'time', probabilistic: false,
	}));

	// The index lists, whole, in the place the browser looks for them: what
	// the members of a dimension are and what order they are in, which no
	// amount of reading the series names will tell you.
	for (const list of indexLists) {
		// A list reaches here in either of the two shapes the model uses: the
		// derived one, whose indices can be switched off one at a time, or the
		// shorthand a hand-written file may still be in. A member that is
		// turned off is not in the run, so it is not in the file. An index may
		// also be the bare string a file wrote it as -- the scenario list of
		// examples/scenarios.json is -- and that string is its name: read as an
		// object it was `undefined`, and the file named every scenario so.
		const members = (list.indices
			? list.indices
				.filter((i) => i != null && (typeof i !== 'object' || i.enabled !== false))
				.map((i) => (typeof i === 'object' ? i.name : i))
			: list.elements ?? [])
			.filter((e) => e != null)
			.map((e) => String(e));
		if (!members.length) continue;
		place(root, ['IndexLists', linkName(list.name)],
			dataset(members, STR, { name: list.name, members: members.length }));
	}

	// One dataset per series, and a group for each level above it. The groups
	// are made on the way down by `put`, so what is left here is to say what
	// each one holds -- which is the same for every child of it.
	for (const i of which) {
		const o = outputs[i];
		const { path, leafDim } = pathOf(o);
		// Every run of it, where there is one. A realisation matrix is written
		// as float32: it is `iterations` times the size of the series -- a
		// thousand of them over four hundred times is 1.6 MB per series in
		// single precision and 3.2 in double -- and the values are a Monte
		// Carlo sample, whose own error after a thousand draws is a few percent.
		// Seven significant figures is already far more than the sample means.
		// Ecolego writes its own series as float32 for the same reason.
		const matrix = realisations ? realisations.matrixFor(i) : null;
		// A value that cannot change over the run is written once: one number,
		// or one per realisation -- the first row of a matrix a caller may
		// still hand over whole.
		const still = o.timeDependent === false;
		const n = realisations?.iterations ?? 0;
		let values;
		if (matrix) values = still && matrix.length > n ? matrix.subarray(0, n) : matrix;
		// Not copied when it is already what the writer wants: a run of fifty
		// thousand series is a hundred and forty megabytes, and copying each
		// one to find out it was already a Float64Array doubles that.
		else values = still ? Float64Array.of(column(i)[0]) : asDoubles(column(i));
		const node = dataset(values, matrix ? F32 : F64, {
			unit: o.unit || '',
			time_dependent: !still,
			probabilistic: !!matrix,
			...(matrix ? { n_iter: realisations.iterations } : {}),
			...(sample && !matrix ? {
				n_iter: sample.iterations,
				realisation: sample.of === 'mean' ? 'mean' : Number(sample.of),
			} : {}),
			kind: String(o.kind ?? ''),
			block: String(o.block ?? ''),
			name: o.label,
			// What the browser writes as the column heading when it exports
			// this series to CSV or to a spreadsheet.
			index: [o.label],
			created_time: created,
		}, matrix && !still ? [t.length, realisations.iterations] : null);
		place(root, path, node);
		if (!leafDim) continue;
		const holder = path.slice(0, -1).reduce((at, part) => at?.children?.get(part), root);
		if (holder?.kind !== 'group') continue;
		// Said once per group rather than once per series, and said the same
		// way every time, so two series of one block cannot disagree about
		// what the group is.
		holder.attrs = {
			...holder.attrs,
			IndexLists: [leafDim],
			time_dependent: !still,
			probabilistic: !!matrix,
			unit: holder.attrs?.unit === undefined || holder.attrs.unit === (o.unit || '')
				? (o.unit || '')
				: '',
			block: String(o.block ?? ''),
		};
	}
	return root;
}
