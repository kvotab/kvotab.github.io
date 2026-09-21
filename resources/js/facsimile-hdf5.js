/* ==========================================================================
   A CANISTER RUN AS AN HDF5 FILE

   Turns what facsimile.html has just solved into the tree the HDF5 Browser
   reads, so that a run can be looked at, compared with another file, and
   exported from there without ever being written to disk.

     /                        what was run, with what solver, and how it went
     /time                    the integration clock, in hours
     /Results/<OUTPUT>        one series per <OUTPUTS> line
     /Equations/<NAME>        one per <EQUATIONS> line: rate constants, the
                              Gibbs energies, the corrosion switches
     /Species/<NAME>          one per species, in mol/cm3
     /Settings                the case, as attributes
     /Constants               the constants the case works out to
     /Model/source            the model text, a line per string
     /Model/reactions         the reactions, as written
     /Events/...              when an event fired and what it changed
     /IndexLists/...          the members of the three groups above

   The conventions are Ecolego's, because they are what the browser reads:
   `/time` is the x-axis of everything, `time_dependent` is what makes a
   dataset plottable against it, and a group whose `IndexLists` names a list
   gets the chart that draws all of its children together.

   One global, FacsimileHDF5. Runs in a page, a Worker and Node.
   ========================================================================== */
(function (root, factory) {
  const hdf5 = root.KvotHDF5
    || (typeof require !== 'undefined' ? require('./kvot-hdf5-write.js') : null);
  const api = factory(hdf5);
  root.FacsimileHDF5 = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof self !== 'undefined' ? self : this, function (H) {
  'use strict';

  const { F64, STR, group, dataset, put, writeHDF5 } = H;

  /**
   * The unit out of a model comment.
   *
   * The model text has no field for a unit, but nearly every line says one in
   * its comment -- `# total gas pressure (atm)`, `# oxic iron loss (mol cm-3
   * s-1)`. The first parenthesis is taken when it looks like a unit and left
   * alone when it does not, so `# corrosion limited by RH (-)` contributes
   * nothing rather than a unit of "-". The whole comment goes in `description`
   * either way, so nothing is lost when the guess declines.
   */
  function unitFromComment(comment) {
    // 32 rather than 16: a real unit can be long ("100 eV cm-3 s-1 per mole"),
    // and widening it was measured over every comment in the model -- it wins
    // two units that were being dropped and pulls in nothing spurious.
    const m = /\(([^)]{1,32})\)/.exec(String(comment || ''));
    if (!m) return '';
    const text = m[1].trim();
    return /[A-Za-z]/.test(text) && /^[\w%°/·^ +*.,-]+$/.test(text) ? text : '';
  }

  /** Column `k` of a row-major matrix of `n` rows and `width` columns. */
  function column(flat, n, width, k) {
    const out = new Float64Array(n);
    for (let i = 0; i < n; i++) out[i] = flat[i * width + k];
    return out;
  }

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

  /**
   * What the browser shows when the file is selected: the case in a sentence
   * and a table, as markup. It is sanitised on the way in over there, so this
   * stays to the handful of tags that survive that.
   */
  function informationHTML(rows, scenario) {
    const cells = rows
      .map(([k, v]) => `<tr><td>${escapeHTML(k)}</td><td>${escapeHTML(v)}</td></tr>`)
      .join('');
    return `<p>Radiolysis and corrosion of the gas in an intact KBS-3 canister, `
      + `scenario <b>${escapeHTML(scenario)}</b>, solved in the browser at `
      + `kvotab.se/facsimile.html.</p><table>${cells}</table>`;
  }

  function escapeHTML(value) {
    return String(value ?? '').replace(/[&<>"']/g, (c) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  /**
   * Builds the tree.
   *
   * @param {object} run       the worker's result payload: t, states, observed,
   *                           n, nspecies, species, observeNames, events, stats
   * @param {object} model     the compiled summary: settings, equations,
   *                           outputs, reactions, warnings, nnz, colours
   * @param {object} [opts]
   * @param {string} [opts.scenario]  the preset the case came from
   * @param {string} [opts.reference]  where that case is defined, in one line
   * @param {object} [opts.solver]    the solver options the run used
   * @param {string} [opts.text]      the model text
   * @param {Date}   [opts.now]
   * @returns {object} the root group, for `writeHDF5`
   */
  function resultTree(run, model, opts = {}) {
    const { scenario = 'custom', reference = '', solver = {}, text = '', now = new Date() } = opts;
    const created = stamp(now);
    const n = run.n;
    const width = run.observeNames.length;
    const stats = run.stats || {};
    // The settings, by name, for the summary table and for `/Settings`.
    const settings = (model.settings || []).map((s) => [s.name, s.isTable ? s.value : s.value, s.comment]);
    // What the browser shows about the file as a whole: which case it is,
    // where that case comes from, and what solved it. NOT the settings --
    // every one of them is a dataset in /Settings, and repeating them here
    // was two places to read the same numbers and one of them to keep in step.
    const summary = [
      ['Scenario', scenario],
      ...(reference ? [['Defined in', reference]] : []),
      ['Solver', `${stats.solver || solver.method || ''}, rtol ${solver.rtol}, atol ${solver.atol}`],
    ].filter(([, v]) => v !== null && v !== undefined && v !== '');

    const root = group({
      model: 'SKB canister radiolysis (FACSIMILE)',
      scenario,
      // Where the case comes from, so a file that has left this page still
      // says which published case it is -- or that it is nobody's.
      scenario_reference: String(reference || ''),
      source: 'kvot ab — Canister Radiolysis (facsimile.html)',
      created_time: created,
      time_unit: 'h',
      // The run, in the terms the solver reports it in.
      solver: String(stats.solver || solver.method || ''),
      rtol: Number(solver.rtol),
      atol: Number(solver.atol),
      // The species held to something other than `atol`, as NAME=value pairs;
      // empty when the whole system was judged against the one number.
      atol_species: Object.keys(solver.atolSpecies || {})
        .map((k) => `${k}=${solver.atolSpecies[k]}`).join('; '),
      error_norm: String(solver.norm || 'max'),
      max_order: Number(solver.maxOrder || 5),
      jacobian: solver.jacobianMode === 'numeric' ? 'finite differences' : 'analytic, sparse',
      iteration_matrix: stats.sparse ? 'sparse LU' : 'dense LU',
      non_negative: !!solver.nonNegative,
      negative_clamped: !!solver.clamp,
      steps: Number(stats.nsteps || 0),
      failed_steps: Number(stats.nfailed || 0),
      function_evaluations: Number(stats.nfevals || 0),
      jacobians_formed: Number(stats.npds || 0),
      factorisations: Number(stats.ndecomps || 0),
      seconds: Number(run.seconds || stats.seconds || 0),
      species: Number(run.nspecies),
      reactions: Number(model.nreactions || (model.reactions || []).length),
      jacobian_nonzeros: Number(model.nnz || 0),
      points: n,
      probabilistic: false,
      Information: informationHTML(summary, scenario),
    });

    // The clock. In hours, which is what the page's own charts default to and
    // what the study's figures use; the model's own TIMH and TIMY are in
    // /Results as well, so nothing is lost by the choice.
    const hours = new Float64Array(n);
    for (let i = 0; i < n; i++) hours[i] = run.t[i] / 3600;
    put(root, ['time'], dataset(hours, F64, {
      unit: 'h', name: 'time', created_time: created, probabilistic: false,
    }));

    // Which of the observed names are equations and which are outputs: the
    // observe function reports the equations first, in order, then the
    // outputs, so the model's own lists say where the boundary is.
    const equationNames = new Set((model.equations || []).filter((e) => !e.substitution).map((e) => e.name));
    // A reaction that named its net rate is reported beside them, in a group
    // of its own: it is neither an equation nor a derived output but a flux,
    // and a reader looking for one wants the three kept apart.
    const rateNames = new Set(model.rateNames || []);
    const describe = (entry) => ({
      unit: unitFromComment(entry && entry.comment),
      description: String((entry && entry.comment) || ''),
      expression: String((entry && entry.expr) || ''),
    });
    const byName = new Map();
    (model.equations || []).forEach((e) => byName.set(e.name, e));
    (model.outputs || []).forEach((o) => byName.set(o.name, o));
    // A rate's expression is the reaction it belongs to, which is what a
    // reader opening the dataset needs to see.
    (model.rates || []).forEach((r) => byName.set(r.name, { comment: r.comment, expr: r.text }));

    const inResults = [];
    const inEquations = [];
    const inRates = [];
    run.observeNames.forEach((name, k) => {
      const where = equationNames.has(name) ? 'Equations' : rateNames.has(name) ? 'Rates' : 'Results';
      const info = describe(byName.get(name));
      put(root, [where, linkName(name)], dataset(column(run.observed, n, width, k), F64, {
        ...info,
        name,
        time_dependent: true,
        index: [name],
        created_time: created,
      }));
      (where === 'Results' ? inResults : where === 'Equations' ? inEquations : inRates).push(name);
    });

    // The state itself: every species, in the unit the model works in.
    run.species.forEach((name, k) => {
      put(root, ['Species', linkName(name)], dataset(column(run.states, n, run.nspecies, k), F64, {
        unit: 'mol/cm3',
        description: 'Concentration in the gas of the canister',
        name,
        time_dependent: true,
        index: [name],
        created_time: created,
      }));
    });

    // What makes the browser offer each of those groups as one chart.
    const lists = [['Outputs', inResults], ['Equations', inEquations], ['Rates', inRates], ['Species', Array.from(run.species)]];
    for (const [name, members] of lists) {
      if (!members.length) continue;
      put(root, ['IndexLists', name], dataset(members, STR, { name, members: members.length }));
    }
    for (const [path, list] of [['Results', 'Outputs'], ['Equations', 'Equations'], ['Rates', 'Rates'], ['Species', 'Species']]) {
      const node = root.children.get(path);
      if (node) Object.assign(node.attrs, { IndexLists: [list], time_dependent: true });
    }

    // The case, and what it works out to: a dataset each, carrying its own
    // unit and description. Not also as attributes on the group -- that was
    // the first shape, and a group of sixty name=value attributes is a wall
    // of text in a browser's info panel for something the tree already lists.
    // (Attributes *alone* was the shape before that, and read as an empty
    // group: the tree offered to expand it and there was nothing underneath.)
    const commentFor = new Map();
    for (const m of (model.Pmeta || [])) commentFor.set(m.name, m.comment || '');
    const constants = [];
    const settingNames = new Set(settings.map(([name]) => name));
    for (const [name, value] of Object.entries(run.constants || {})) {
      if (settingNames.has(name)) continue;
      constants.push([name, value, commentFor.get(name) || '']);
    }
    const oneEach = (path, pairs, description) => {
      if (!pairs.length) return;
      put(root, [path], group({ description, IndexLists: [path] }));
      for (const [name, value, comment] of pairs) {
        // The same two attributes every other dataset in this file carries,
        // read the same way: the unit is what the comment put in brackets.
        const attrs = { name, unit: unitFromComment(comment), description: String(comment || '') };
        // A string value is a table's name (TPROF = TEMP_PWR), not a number.
        put(root, [path, name], typeof value === 'number' && Number.isFinite(value)
          ? dataset([value], F64, attrs)
          : dataset([String(value)], STR, attrs));
      }
      put(root, ['IndexLists', path], dataset(pairs.map(([name]) => name), STR,
        { name: path, members: pairs.length }));
    };
    oneEach('Settings', settings, 'The case: every setting the model was compiled with');
    oneEach('Constants', constants,
      'What the case works out to, once the settings are applied');

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
    const reactions = (model.reactions || []).map((r) => String(r.text || ''));
    if (reactions.length) {
      put(root, ['Model', 'reactions'], dataset(reactions, STR, {
        name: 'reactions', count: reactions.length,
        description: 'The reactions as written, in the order they are applied',
      }));
    }
    if ((model.warnings || []).length) {
      put(root, ['Model', 'warnings'], dataset(model.warnings.map(String), STR, {
        name: 'warnings', count: model.warnings.length,
      }));
    }

    // When the run restarted, and what changed there.
    const events = run.events || [];
    if (events.length) {
      put(root, ['Events', 'time'], dataset(Float64Array.from(events, (e) => e.t / 3600), F64, {
        unit: 'h', name: 'time', description: 'When each event fired',
      }));
      put(root, ['Events', 'change'], dataset(events.map((e) => (e.changed || []).join(', ')), STR, {
        name: 'change', description: 'What the event changed',
      }));
      put(root, ['Events', 'expression'], dataset(events.map((e) => String(e.expr || '')), STR, {
        name: 'expression', description: 'The expression whose crossing fired it',
      }));
    }
    return root;
  }

  /** The tree, as the bytes of an HDF5 file. */
  function resultFile(run, model, opts = {}) {
    return writeHDF5(resultTree(run, model, opts));
  }

  return { resultTree, resultFile, unitFromComment };
});
