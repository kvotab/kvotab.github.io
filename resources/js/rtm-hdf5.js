/* ==========================================================================
   A REACTIVE-TRANSPORT RUN AS AN HDF5 FILE

   Turns what rtm.html has just solved into the tree the HDF5 Browser reads,
   so that a run can be looked at, compared with another file and exported
   from there without ever being written to disk.

     /                        what was run, with what solver, and how it went
     /time                    the integration clock, in the model's time unit
     /Species/<NAME>          every species where the page was looking: the
                              batch, or the cell the Model tab had open
     /Cells/<cell>/<NAME>     the same, for every cell of the column and every
                              layer of rock behind it (transport only)
     /Grid/...                what each cell is: where its centre sits, how
                              deep into the rock it is, how wide it is
     /Settings/<NAME>         the settings the model compiled with
     /Model/source            the model text, a line per string
     /IndexLists/...          the members of the groups above

   The conventions are Ecolego's, because they are what the browser reads:
   `/time` is the x-axis of everything, `time_dependent` is what makes a
   dataset plottable against it, and a group whose `IndexLists` names a list
   gets the chart that draws all of its children together.

   EVERY SERIES IS ONE-DIMENSIONAL, one value per stored time. A transport run
   holds a concentration for every species in every cell, which would be a
   tidier file as one matrix per species -- and unreadable in the browser it
   is written for: a dataset with a trailing dimension is a set of realisations
   there, and one that is not probabilistic is drawn against a clock as long as
   its first column alone. So a cell is a group and a species in it is a
   series, and the price is the number of datasets. Past MAX_DATASETS of them
   the layers of rock are left out rather than the file becoming something no
   browser will open; the root then says `matrix_written` is false, and the
   water -- which is what a breakthrough is read from -- is all there.

   One global, RtmHDF5. Runs in a page, a Worker and Node.
   ========================================================================== */
(function (root, factory) {
  const hdf5 = root.KvotHDF5
    || (typeof require !== 'undefined' ? require('./kvot-hdf5-write.js') : null);
  const api = factory(hdf5);
  root.RtmHDF5 = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof self !== 'undefined' ? self : this, function (H) {
  'use strict';

  const { F64, STR, group, dataset, put, writeHDF5 } = H;

  /** ISO-ish, to the second: what Ecolego's own `created_time` looks like. */
  function stamp(date) {
    const p = (v) => String(v).padStart(2, '0');
    return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())} `
      + `${p(date.getHours())}:${p(date.getMinutes())}:${p(date.getSeconds())}`;
  }

  /** A name HDF5 can use as a link. */
  function linkName(s) {
    const out = String(s ?? '').replace(/\//g, '_').trim();
    return out === '' || out === '.' || out === '..' ? '_' : out;
  }

  function escapeHTML(value) {
    return String(value ?? '').replace(/[&<>"']/g, (c) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  /**
   * What the browser shows when the file is selected: the run in a sentence
   * and a table, as markup. It is sanitised on the way in over there, so this
   * stays to the handful of tags that survive that.
   */
  function informationHTML(rows, lead) {
    const cells = rows
      .map(([k, v]) => `<tr><td>${escapeHTML(k)}</td><td>${escapeHTML(v)}</td></tr>`)
      .join('');
    return `<p>${escapeHTML(lead)} Solved in the browser at kvotab.se/rtm.html.</p>`
      + `<table>${cells}</table>`;
  }

  /** The series of species `si` in column `c`, out of the flat state. */
  function columnSeries(run, ns, si, c) {
    const out = new Float64Array(run.n);
    const at = c * ns + si;
    for (let i = 0; i < run.n; i++) out[i] = run.states[i * run.width + at];
    return out;
  }

  /*
    How many series a file may hold before the rock behind the column is left
    out of it. A dual-porosity model is forty layers deep on every one of a
    hundred cells, and a species in each of those is four thousand datasets
    for one species -- a file that takes longer to open than the run took to
    solve. The water is always written whatever this says.
  */
  const MAX_DATASETS = 4000;

  /** What to call the group of a column: which cell, and how deep in the rock. */
  function cellName(i, j) {
    return `cell_${String(i).padStart(3, '0')}${j > 0 ? `_rock_${String(j).padStart(2, '0')}` : ''}`;
  }

  /**
   * Builds the tree.
   *
   * @param {object} run       the worker's result payload: t, states, n,
   *                           width, model, stats, seconds
   * @param {object} [opts]
   * @param {object} [opts.solver]  the solver options the run used
   * @param {string} [opts.text]    the model text
   * @param {number} [opts.cell]    the fracture cell the page is showing
   * @param {number} [opts.layer]   which layer of rock behind it, 0 for none
   * @param {string} [opts.title]   what to call the model
   * @param {Date}   [opts.now]
   * @returns {object} the root group, for `writeHDF5`
   */
  function resultTree(run, opts = {}) {
    const { solver = {}, text = '', cell = 0, layer = 0, title = '', now = new Date() } = opts;
    const created = stamp(now);
    const m = run.model || {};
    const stats = run.stats || {};
    const species = m.species || [];
    const ns = species.length;
    const cells = m.cells || 1;               // every column: layers included
    const fracture = m.fracture || 1;         // the cells along the column
    const stride = m.stride || 1;             // columns per fracture cell
    const unit = (m.timeUnit && m.timeUnit.symbol) || 's';
    const unitName = (m.timeUnit && m.timeUnit.name) || 'second';
    const settings = m.settings || {};
    const transport = !!m.transport;

    const summary = [
      ['What was solved', transport
        ? `${fracture} cells over ${m.length} m`
          + (m.matrix ? `, each with ${m.matrix.n} layers of rock ${m.matrix.total} m deep` : '')
        : 'a batch: one cell, no transport'],
      ['Species', `${ns}`],
      ['Reactions', `${m.nreactions || 0}`],
      ...(m.nequilibria ? [['Equilibria', `${m.nequilibria}`]] : []),
      ['Solver', `${stats.solver || solver.method || ''}, rtol ${solver.rtol}, atol ${solver.atol}`],
      ['Time', `${run.t && run.n ? run.t[run.n - 1] : 0} ${unitName}s, ${run.n} points kept`],
    ].filter(([, v]) => v !== null && v !== undefined && v !== '');

    const root = group({
      model: title || 'Reactive transport',
      source: 'kvot ab — Reactive Transport (rtm.html)',
      created_time: created,
      time_unit: unit,
      time_unit_name: unitName,
      mode: transport ? 'transport' : 'batch',
      cells: Number(cells),
      fracture_cells: Number(fracture),
      matrix_layers: Number(stride - 1),
      length: Number(m.length || 0),
      species: Number(ns),
      reactions: Number(m.nreactions || 0),
      equilibria: Number(m.nequilibria || 0),
      // The run, in the terms the solver reports it in.
      solver: String(stats.solver || solver.method || ''),
      rtol: Number(solver.rtol),
      atol: Number(solver.atol),
      error_norm: String(solver.norm || 'max'),
      iteration_matrix: stats.sparse ? 'sparse LU' : 'dense LU',
      jacobian: 'analytic, sparse',
      jacobian_nonzeros: Number(m.nnz || 0),
      non_negative: !!solver.nonNegative,
      steps: Number(stats.nsteps || 0),
      failed_steps: Number(stats.nfailed || 0),
      function_evaluations: Number(stats.nfevals || 0),
      jacobians_formed: Number(stats.npds || 0),
      factorisations: Number(stats.ndecomps || 0),
      seconds: Number(run.seconds || stats.seconds || 0),
      points: Number(run.n || 0),
      probabilistic: false,
      Information: informationHTML(summary, transport
        ? 'A reactive-transport run: reactions in a column of water, with diffusion and advection.'
        : 'A reactive-transport run: reactions in one stirred batch.'),
    });

    // The clock, in the unit the model is written in. It converts nothing --
    // neither does the page -- so the number here is the model's own.
    put(root, ['time'], dataset(Float64Array.from(run.t.slice(0, run.n)), F64, {
      unit, name: 'time', description: `The integration clock, in ${unitName}s`,
      created_time: created, probabilistic: false,
    }));

    /*
      /Species: where the page was looking.

      A file wants one place a reader can open and see the run, and on a
      column that is the cell the page itself had in front of it -- the same
      curves, in the same order, under the name the species has. Every other
      cell is under /Cells below.
    */
    const shown = Math.min(cells - 1, Math.max(0, cell) * stride + Math.min(layer, stride - 1));
    const where = cells === 1 ? 'the batch'
      : (layer > 0 ? `cell ${cell}, rock layer ${layer}` : `cell ${cell}`);
    species.forEach((name, si) => {
      put(root, ['Species', linkName(name)], dataset(columnSeries(run, ns, si, shown), F64, {
        unit: 'concentration', name, time_dependent: true, index: [name],
        description: `${name} in ${where}`, created_time: created,
        cell: Number(cells === 1 ? 0 : cell), layer: Number(cells === 1 ? 0 : layer),
      }));
    });
    if (ns) {
      put(root, ['IndexLists', 'Species'], dataset(species.map(String), STR,
        { name: 'Species', members: ns }));
      const node = root.children.get('Species');
      if (node) Object.assign(node.attrs, {
        IndexLists: ['Species'], time_dependent: true,
        description: `Every species in ${where}, the view the page had open`,
      });
    }

    /*
      /Cells: the same for every cell there is.

      One group per cell, so that the browser draws a cell as a chart of its
      species, and a search for a species name draws that species in every
      cell -- the two ways anyone reads a column.
    */
    const withMatrix = cells * ns <= MAX_DATASETS;
    root.attrs.matrix_written = stride > 1 ? withMatrix : true;
    if (cells > 1) {
      put(root, ['Cells'], group({
        description: stride > 1 && !withMatrix
          ? `Every species in every cell of the column. The ${stride - 1} layers of rock `
            + 'behind each cell are left out: there are too many of them for one file.'
          : 'Every species in every cell of the column',
      }));
      for (let c = 0; c < cells; c++) {
        const i = Math.floor(c / stride);
        const j = c % stride;
        if (j > 0 && !withMatrix) continue;
        const path = cellName(i, j);
        put(root, ['Cells', path], group({
          description: j > 0
            ? `Every species in layer ${j} of the rock behind cell ${i}`
            : `Every species in cell ${i}`,
          IndexLists: ['Species'], time_dependent: true,
          cell: Number(i), layer: Number(j),
        }));
        species.forEach((name, si) => {
          put(root, ['Cells', path, linkName(name)], dataset(columnSeries(run, ns, si, c), F64, {
            unit: 'concentration', name, time_dependent: true, index: [name],
            description: `${name} in ${j > 0 ? `layer ${j} of the rock behind cell ${i}` : `cell ${i}`}`,
            created_time: created, cell: Number(i), layer: Number(j),
          }));
        });
      }
    }

    /*
      What each cell is. Written as datasets rather than as attributes for the
      same reason the settings are: a wall of numbers in an info panel is not
      something anyone reads, and these are what a profile is plotted against.
      One row for every cell the model has, water and rock alike, in the order
      the solver holds them -- which is the order /Cells lists them in, and is
      longer than /Cells when the rock was left out.
    */
    if (cells > 1) {
      const x = new Float64Array(cells);
      const depth = new Float64Array(cells);
      const cellOf = new Float64Array(cells);
      const layerOf = new Float64Array(cells);
      const centres = m.centres || [];
      const layers = (m.matrix && m.matrix.depth) || [];
      for (let c = 0; c < cells; c++) {
        const i = Math.floor(c / stride);
        const j = c % stride;
        x[c] = centres[i] !== undefined ? centres[i] : i;
        depth[c] = j === 0 ? 0 : (layers[j - 1] !== undefined ? layers[j - 1] : 0);
        cellOf[c] = i;
        layerOf[c] = j;
      }
      put(root, ['Grid'], group({
        description: 'What each cell of the model is: one row per cell, water and '
          + 'rock alike, in the order /Cells lists them',
        IndexLists: ['Grid'], rows: Number(cells),
      }));
      const columns = [
        ['x', x, 'm', 'Distance along the column to the centre of the cell'],
        ['depth', depth, 'm', 'Depth into the rock to the centre of the layer, 0 in the water'],
        ['cell', cellOf, '', 'Which cell of the column'],
        ['layer', layerOf, '', 'Which layer of rock behind it, 0 for the water itself'],
        ['width', Float64Array.from(m.width || []), 'm', 'How wide each cell of the column is'],
      ].filter(([, values]) => values.length);
      for (const [name, values, u, description] of columns) {
        put(root, ['Grid', name], dataset(values, F64, { name, unit: u, description }));
      }
      put(root, ['IndexLists', 'Grid'], dataset(columns.map(([name]) => name), STR,
        { name: 'Grid', members: columns.length }));
    }

    // The case: every setting the model compiled with, a dataset each.
    const names = Object.keys(settings);
    if (names.length) {
      put(root, ['Settings'], group({
        description: 'The settings the model was compiled with', IndexLists: ['Settings'],
      }));
      for (const name of names) {
        const value = settings[name];
        put(root, ['Settings', linkName(name)], typeof value === 'number' && Number.isFinite(value)
          ? dataset([value], F64, { name })
          : dataset([String(value)], STR, { name }));
      }
      put(root, ['IndexLists', 'Settings'], dataset(names, STR,
        { name: 'Settings', members: names.length }));
    }

    // The model itself, so the file says what produced it. A line per string:
    // one string of thirty kilobytes is not something a reader can look at.
    const modelGroup = group({ description: 'The model text this run was solved from' });
    root.children.set('Model', modelGroup);
    if (text) {
      const lines = String(text).split('\n');
      put(root, ['Model', 'source'], dataset(lines, STR, {
        name: 'source', lines: lines.length, description: 'The model text, a line per value',
      }));
    }
    if ((m.warnings || []).length) {
      put(root, ['Model', 'warnings'], dataset(m.warnings.map(String), STR, {
        name: 'warnings', count: m.warnings.length,
      }));
    }
    return root;
  }

  /** The tree, as the bytes of an HDF5 file. */
  function resultFile(run, opts = {}) {
    return writeHDF5(resultTree(run, opts));
  }

  return { resultTree, resultFile };
});
