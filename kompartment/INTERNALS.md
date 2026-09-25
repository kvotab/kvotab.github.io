# How it works

The machinery behind the guide: where each piece lives, what was measured
rather than assumed, and why each thing is arranged as it is.

Kompartment covers the part of compartment modelling that determines the
numbers — a domain model with index lists, an equation language, a code
generator and a set of solvers — plus a graphical editor to build models with
and an importer for the project files these assessments are usually written in.

**Nothing here is needed to use the tool.** [GUIDE.md](GUIDE.md) is that. This
is for the person who has to change it.

## Where things live

`src/` splits three ways and nothing crosses the lines the wrong way round:
`domain/` is pure — no DOM, no solver — `ui/` touches the DOM and never the
numerics, and `sim/` and `ode/` do the numerics and never the DOM. The tests
exercise `domain/` and `sim/` directly, which is why they can be plain Node.

| File | What it is |
|---|---|
| `src/parser/parser.js` | Tokenizer and recursive-descent parser for the equation language |
| `src/parser/functions.js` | The ~70 built-in functions, their arities and their arithmetic |
| `src/parser/function-help.js` | A signature and a one-line summary for each, for the completion list |
| `src/parser/compile.js` | An AST to a JavaScript expression string |
| `src/parser/../domain/complete.js`, `src/ui/complete.js` | The word under the caret, replaced by a choice |
| `src/sim/builder.js` | The state-vector layout, the block ordering and the generated derivative |
| `src/sim/jacobian.js` | The analytic df/dy, differentiated from the same ASTs |
| `src/sim/runner.js` | Drives a solve and back-fills the algebraic outputs |
| `src/sim/history.js` | The buffers a delay, a min/max, a running mean and a snapshot need |
| `src/sim/partition.js` | Cutting a model into parts that cannot see each other |
| `src/sim/split.js` | Whether to solve those parts on several cores, and putting the parts back together |
| `src/sim/localsens.js` | dy/dp for a chosen parameter, by forward sensitivities |
| `src/sim/probabilistic.js` | Latin hypercube sampling and the statistics over realisations |
| `src/ode/solvers/ndf.js` | The NDF/BDF formulas (Shampine & Reichelt 1997; Hairer & Wanner 1996, ch. V). One of the five shared-core files: see *One solver core for three pages* |
| `src/ode/variable-order.js` | The adapter that gives those formulas this project's solver shape |
| `src/ode/solvers/rosenbrock23.js` | The modified Rosenbrock (2,3) pair (Shampine & Reichelt 1997, §4) |
| `src/ode/solvers/dormand-prince.js` | The explicit (4,5) pair (Dormand & Prince 1980) |
| `src/ode/core/onestep.js` | The driver the two one-step pairs share: step control, events, output, the constraint |
| `src/ode/julia/`, `src/ode/julia-solvers.js` | Six stiff methods from SciML's DifferentialEquations.jl, vendored whole, and the adapter. See *The DifferentialEquations.jl solvers* |
| `src/ode/scipy.js` | `scipy.integrate.solve_ivp` through Pyodide, as an independent check on the rest |
| `src/ode/core/events.js` | Locating the instant an event function crosses zero (shared core) |
| `src/ode/core/linalg.js` | Dense LU with partial pivoting (shared core) |
| `src/ode/core/sparse.js` | CSC, Gilbert-Peierls left-looking LU, reverse Cuthill-McKee, colouring, differencing, and the choice of iteration matrix (shared core) |
| `src/ode/core/refactor.js` | The sparse LU that keeps its pivots (shared core) |
| `src/ode/solvers.js` | The catalogue: names, blurbs, and which settings each method reads |
| `src/domain/project.js` | The block types and the normalised project |
| `src/domain/edit.js` | Every editing operation, as pure functions over the project |
| `src/domain/keys.js` | Migration: old key spellings and old solver ids, so a saved file still opens |
| `src/domain/indexlists.js` | Index lists, sub-sets, mappings and index resolution |
| `src/domain/systems.js` | Sub-systems and qualified names |
| `src/domain/nuclides.js`, `src/domain/decaydb.js` | Half-lives, decay chains and chain collapsing |
| `src/domain/icrp107.js` | The ICRP 107 radionuclide tables, extracted from kvotab.se/rdc.html |
| `src/domain/lookup.js` | A value that changes with time, and the five ways of reading between points |
| `src/domain/reduce.js` | The two blocks that reduce many values to one |
| `src/domain/recorders.js` | The five blocks that depend on what has already happened |
| `src/domain/transport.js` | A chain of N cells written as one block |
| `src/domain/farfield.js`, `src/sim/farfield.js` | The dual-porosity far-field pathway (SKB TR-19-06 App. B; TR-90-01 ch. 3) |
| `src/domain/availability.js` | Solubility limits and Langmuir sorption |
| `src/domain/wastepackage.js` | Packages that fail, a waste form that degrades, an instant release |
| `src/domain/disruption.js` | Timed and Poisson events with consequences |
| `src/domain/derived.js` | Quantities worked out from a finished curve, and reporting periods |
| `src/domain/switchtimes.js` | Parameters that change value at a stated time |
| `src/domain/queries.js`, `src/ui/querydialog.js` | Searching the model's parameters |
| `src/domain/qa.js` | Parameter approvals, computed from the dependency graph |
| `src/domain/correlate.js` | Correlated sampling, by Iman and Conover's permutation |
| `src/domain/gsa.js`, `src/domain/salib.js`, `src/domain/fft.js`, `src/ui/gsadialog.js` | Global sensitivity analysis, ported from GlobalSensitivity.jl and SALib, and the FFT its spectral methods read |
| `src/domain/categories.js` | Classifying and screening realisations |
| `src/domain/distribution.js` | A distribution summary with a DKW band |
| `src/domain/fit.js` | The parameter shapes fitted to a sample, by likelihood and by moments, and ranked |
| `src/domain/massbalance.js` | The mass-balance audit, done with budget states the solver integrates |
| `src/domain/versions.js` | Two models in, the differences out |
| `src/domain/runlog.js` | What a run was, written into its results archive |
| `src/domain/pdf.js`, `src/domain/sample.js` | The distributions and the sampler |
| `src/domain/unitcheck.js` | The unit algebra, the literal conversion and the clash messages |
| `src/domain/symbol.js` | Sub- and superscripts in a block's display name |
| `src/domain/layout.js` | Laying an imported diagram out, since a file's positions are not read |
| `src/ui/app.js` | The shell: tabs, toolbar, settings, notices |
| `src/ui/scenarios.js` | Which scenarios run beside the selected one, and how their lines share a chart |
| `src/ui/infopanel.js` | The (i) beside a setting and the panel it opens: what a setting is, on demand |
| `src/ui/siminfo.js` | What each simulation setting is, for that panel |
| `src/ui/panelinfo.js`, `src/ui/blockinfo.js`, `src/ui/dialoginfo.js` | The same for the left panel's parts and the Index lists and JSON tabs, each kind of block's settings window, and every dialog |
| `src/ui/graph.js` | The diagram, in SVG |
| `src/ui/matrix.js` | The transfer grid |
| `src/ui/chart.js`, `src/ui/svgcanvas.js` | The chart on a canvas, and the same paint routine writing SVG |
| `src/ui/tree.js`, `src/ui/icons.js` | The block tree, and the glyph beside each name |
| `src/ui/inspector.js` | The settings panel for whatever is selected |
| `src/ui/indexlists.js` | Index lists, contaminants and decay data, in one panel |
| `src/ui/jsoneditor.js` | The JSON tab's box: the coloured copy of the lines in view under the textarea, the check as you type (`jsonErrorAt` says where text stops being JSON, in words and the same in every browser), and whether Apply is offered |
| `src/ui/endpoints.js` | Which blocks a probabilistic run keeps |
| `src/ui/savedialog.js`, `src/ui/dualtree.js` | Everything that can be written, in one dialog, and the two trees its lists are chosen in |
| `src/ui/cores.js` | How many cores a sampled run is shared over, when the reader says |
| `src/ui/help.js`, `src/ui/markdown.js`, `src/ui/helpfigures.js` | This documentation, read inside the application |
| `css/app.css`, `css/theme-kvotab.css` | Every colour, as tokens, and a second palette for embedding |
| `src/ui/undo.js` | Undo and redo, from snapshots |
| `src/ui/histview.js`, `src/ui/scatterview.js` | The Chart tab's other two pictures of a sample |
| `src/ui/clipboard.js` | The block clipboard, shared between tabs of one browser |
| `src/io/eco.js` | The importer for `.eco` projects and `.eas` assessments |
| `src/io/zip.js`, `src/io/gzip.js`, `src/io/inflate.js` | Reading and writing the archives those come in |
| `src/io/hdf5.js` | An HDF5 writer, in the shape the assessment tools read |
| `src/io/resultfile.js`, `src/io/dataset.js` | Results files, and a project archive with its run beside it |
| `src/worker/sim-worker.js`, `src/worker/prob-pool.js` | The solve, off the UI thread, and a pool over the cores |
| `python/` | The Python package: a model file read into objects, edited by the same rules as `src/domain/edit.js`, and written back. Its tests run the editor beside it through Node and compare the files. See `python/README.md` |

## Behaviours measured, not guessed

Four things determine what a model *means*, and getting any of them wrong
produces a plausible model that is not the one in the file. Each was settled by
reading a corpus of real project files rather than by assumption. The large
assessment models measured against below are referred to as models A to G and
L, with their sizes given where they matter.

1. **Operator precedence is the C family's, and `^` is left-associative.**
   An equation in one of these files is rewritten so that `a^b` becomes a call
   to a power function and the rest is evaluated as an ordinary C-family
   expression. The rewrite takes one operand per side scanning left to right,
   so `2^3^2` is `(2^3)^2` = 64, and `2^-1` is legal because a signed exponent
   is explicitly allowed.

2. **Transfer flux is `donor × rate`, conditionally.**
   A plain transfer prepends the donor compartment and a multiply; a transfer
   marked otherwise *is* the flux, absolutely. Both are supported, through
   `multiply_by_donor`.

3. **Decay and ingrowth, in either unit.**
   The decay term is

       -lambda·C + sum over parents ( ingrowthLambda · C_parent · ratio )

   and it is written only for parents that are themselves enabled in the run.
   A daughter whose parent is not part of the simulation gets no ingrowth term,
   which is reproduced here.

   What `ingrowthLambda` is depends on the **decay unit**:

   | decay unit | ingrowth coefficient | what it is the equation for |
   |---|---|---|
   | `Bq` (the default) | the **daughter's** lambda | activity: `A_D' = lambda_D · (ratio · A_P − A_D)` |
   | `mol` | the **parent's** lambda | amounts: the classical Bateman equation for numbers of nuclei |

   Both are here, behind `decay_unit` on the model, defaulting to `Bq`. That
   setting is the *only* thing the decay term reads the unit for; nothing else
   scales anything by it. The two coefficients differ by
   `T½(parent) / T½(daughter)` — a factor of 18,200 for U-238 into U-234 — so
   the setting has to agree with what the numbers in the model mean, which is
   why changing it relabels the compartments that carried the other unit.

   **Where a file keeps it: nowhere, as a model-level property.** The unit is
   written onto *every nuclide* instead, and read back off any one of them. So
   an `.eco` file carries the choice as
   `<nuclide><unit>Bq</unit></nuclide>`, and that is what the importer reads.
   Every nuclide in every corpus file here says `Bq`.

   `bq2mole` and `mole2bq` are the conversion between the two and are exposed
   to equations under those names. They are exact inverses here. That is worth
   saying because the obvious implementation is not: dividing a half-life in
   years by the seconds in a year, where it must be multiplied, leaves the two
   out by that factor squared — about 1e15. Neither name is reachable from an
   equation in any corpus file, so there is no behaviour in the field to match,
   and the honest inverse is what this implements. Both have tangent rules —
   `bq2mole(a, T)` is bilinear and `mole2bq(n, T)` linear in `n` and `1/T` —
   written through the functions themselves, so a rate that reads a
   compartment through one keeps the analytic Jacobian and can never use a
   different Avogadro's number or year from the value it differentiates.

4. **`lambda = ln(2) / halfLife`, with the half-life converted into the
   simulation's time unit**, not into seconds.

## Verification

`test/run.js` — 789 tests. The numerical ones check against closed-form
solutions or published benchmarks, never against a previous run of this code:

- exponential decay against `exp(-lambda t)`
- a three-member chain against the **Bateman equations** (worst relative error
  4e-7 through the full parser → codegen → decay model → solver stack)
- the **Robertson problem** against its published reference values, with mass
  conserved to 1e-9
- harmonic-oscillator energy conservation
- two-compartment transfer against `A0(1-exp(-kt))`
- mass conservation around a closed transfer loop
- the dense-output interpolant checked on a grid far finer than the step size

And, since code can be wrong in the same way its own tests are, every bundled
model is also run through **SciPy** — a second implementation sharing no code
with this one, reached through Pyodide. See
[Solvers](GUIDE.md#a-second-opinion-the-scipy-solvers): the two agree to 1e-5
or better on every bundled model at its own tolerances, and to 2.5e-9 on the
Robertson problem. That comparison is run by hand rather than in
`test/run.js`, because it needs a browser and a 22 MB download; the suite
instead asserts that the SciPy solvers are dispatchable and that they refuse,
with a reason, when their runtime is absent.

Bugs caught this way and fixed, none of which showed up by hand:

- models with exactly one nuclide silently got no decay term at all (the guard
  tested array width instead of the per-nuclide flag)
- custom half-lives were dropped crossing into the Worker (`toJSON()` did not
  serialise the overrides)
- disabling an index invalidated every entry keyed by it, so switching one off
  broke the model instead of shrinking it
- an absent upper saturation round-tripped through JSON as `null` and landed in
  a `Float64Array` as `0`, clamping the compartment to nothing (the band has
  since been removed altogether -- see below)
- `ndf` threw rather than integrating any model with a discrete event and
  fewer states than the BDF order -- the scratch array that rebuilds the
  interpolation data at an event holds `k+1-m` columns of `neq` rows and was
  allocated by `neq`, so with `k` at 5 and `neq` at 2 the later columns were
  undefined. Found by running every bundled example under every solver rather
  than under the one it declares
- generated flux variables collided when transfers were not loop-wrapped
- creating a radionuclide index list retroactively indexed *every* block,
  because Project infers a missing `index_lists` as "the material list" for
  backwards compatibility with the `nuclides: [...]` shorthand. The editor
  showed a block as un-indexed while the engine treated it as per-nuclide, and
  results carried a dimension the user never asked for. Dimensions are now
  written down explicitly whenever the index-list model changes, and on load,
  so the two cannot disagree

- the pop-up menu closed itself on `scroll` and `wheel` in the capture phase,
  which is right for the page scrolling underneath and wrong for the menu's
  own panel: once the canvas menu grew long enough to need a scrollbar, the
  wheel dismissed it and dragging the scrollbar dismissed it before the drag
  could move. Both listeners now ignore events from inside the menu -- and the
  menu was grouped so that it does not scroll in the first place
- `_influences` built a `Set` and then called `.map` on it, which does not
  exist, so the influence layer threw and drew nothing whenever it was switched
  on
- the same layer read only *equations*, so an index operation and an aggregate
  -- which name the blocks they reduce instead of writing an equation about
  them -- got no arrow at all. Who reads whom is now `edit.influences`, a fact
  about the model rather than about the view, which is testable without a
  browser and is where the third kind of reader stopped being forgettable
- and it still left out the blocks that read the model through settings of
  their own: a waste package's inventory, failure settings and degradation
  rate, an event's time, rate and action shares -- and the blocks its actions
  name -- and a transfer's availability limit. `referencesTo` counted all of
  them for the delete gate and the Used-by lists; `influences` now does too.
  *Show ▸ Influences* is `none`, `all` or `selected` (`influenceMode`, which
  reads the old `true` and `false` as all and none): with `selected` every
  influence is drawn, and `_applySelection` marks with `is-chosen` those
  touching any block picked, so a click changes which are seen without a
  redraw; the canvas class `shows-chosen-influences` hides the rest
- the per-index value grid addressed its block by local name, so editing one
  cell of a block inside a sub-system reported "no block named ..."
- the explicit dark theme never defined `--node-fill-parameter`, so a parameter
  node kept its light fill on a dark canvas (the media-query dark block had it
  twice instead)
- `isConstant` followed the *written* name when propagating clock dependence,
  so a rate that read a time-dependent quantity by its local name inside a
  sub-system was reported as constant — and a constant Jacobian is one the
  solver stops refreshing

The index-list work is covered by tests checking a 2-D model against
closed-form solutions cell by cell, a decay chain replicated across three
landscape objects, sub-set and mapped lists routing values correctly, and
partial sums over named dimensions.

**Differential testing.** Where an answer has to match another implementation
of the same published method rather than merely look reasonable, it is checked
against one:

| Module | Checked against | Result |
|---|---|---|
| `src/ode/solvers/ndf.js` | the six ported stiff solvers, and SciPy's BDF and Radau | agree to tolerance on the bundled models |
| `src/ode/core/sparse.js` | the dense LU in `linalg.js` | agrees to round-off |
| `src/domain/lookup.js` | an independent table reader | 68 520 comparisons, 0 mismatches |
| `src/domain/reduce.js` | an independent quantile routine | 52 035 comparisons, 0 mismatches |

The lookup comparison is worth spelling out, because a table reader is commonly
*stateful*: it walks a cursor from wherever the last call left it, so the answer
can depend on the order the questions are asked in. This tool looks the point up
by bisection instead, which cannot. Both were run over every interpolation rule,
cyclic and not, on tables with duplicate x values and single points, at points
inside, on and beyond the ends — 68 520 fresh-instance comparisons and 36 000
sequential ones, with no difference. One deliberate divergence: for a table with
a single point a cursor-based reader returns its uninitialised cache, which is
zero; this tool returns the point's value.

## Index lists

Every block is indexed over an arbitrary number of index lists.
`src/domain/indexlists.js` implements the three kinds (root, sub-set, mapped);
the builder lays the state vector out over every index combination, resolves
references between blocks of different dimension, and applies decay along
whichever list is flagged as the material dimension.

The part that took care is `IndexSpace.projection`: when a block indexed by
`[Radionuclides, Object]` mentions one indexed by `[Radionuclides]`, the nuclide component
has to be carried across and the object component dropped; when it mentions one
indexed by a *sub-set* of `Object`, the carry goes through a lookup table. The
code generator turns those into offset arithmetic, with the tables passed in as
`Int32Array`s. Where a dimension genuinely cannot be resolved the build fails
with a message naming the list and both ways out, rather than guessing.

**Two lists are related through whatever root they share**, not only when one
is defined directly against the other. Each list gets a translation to and from
its root once, and `relate` is then the same two lookups whatever the lists
are. That is what makes an element list mapped onto the materials readable from
a block indexed by a *sub-set* of those materials -- the shape every biosphere
model in the corpus has, and the largest single blocker in the corpus until it was done. Index-name resolution composes the same two steps by hand, one
`if` at a time.

**The element dimension is derived rather than required.** Ecolego keeps an
`ELEMENTS` list beside the materials because chemistry belongs to the element
and not to the isotope; this tool builds one from the catalogue and leaves it
out of the saved file, so the two cannot drift apart. A model that declares its
own -- an imported one, or one that keeps organic and inorganic carbon apart --
keeps it, and nothing is derived beside it.

**Every material has an element, not only the ones that decay.** A mapping has
to cover the list it groups: read from a block indexed by the materials, a
parameter indexed by the elements has no cell to be read at a material no
element stands for, and the build refuses the model rather than guessing --
*"'Elements' does not cover every index of 'Materials'"*. Ecolego never meets
this, because its `materialAdded` only ever adds a material through the
Contaminants view and its index lists are read-only shadows; here the catalogue
takes typed indices, so the gesture needs an answer of its own. The element of
a name that is a nuclide's is its symbol, so stable C-12 joins C-14 under `C` --
one element, and one sorption coefficient right for both. A name that is not a
nuclide's is its own element, because there is nothing else it could belong to.

A *stored* element list -- which is what every imported model has -- follows
nothing by itself, so the editor keeps it in step: adding a material adds its
element and the pair, and removing the last material of an element removes the
element, which is the dance `materialRenamed` does around
`allElements.remove(oldElementIndex)`. Only the element list. A model's own
grouping of its materials -- `Species`, in 32 of the corpus files -- is a
classification this cannot guess at, so a new material is left out of it and
the build says so if anything reads it, naming the list and the missing index.

### One dimension twice

`clashingDimensions` refused a list beside a *grouping* of it and allowed a
list beside a *sub-set* of it, on the stated belief that real models index a
block by a list and a sub-set. That belief was wrong: a scan of every block in
the 87 readable projects finds no block indexed by a list and any ancestor of
it, sub-set or grouping. The rule a project file states is the plain one: no
block may carry two index lists that come from the same root -- two sub-sets
of the contaminant catalogue, say -- and none may be indexed by both the
compartments and the transfers. This tool now applies both, in the editor and
when a file is read, and `getAvailableIndexLists` is followed too: a
compartment or a transfer is not offered the two lists made of the model's
blocks at all, where the panel used to show them greyed.

### Lists derived from the two block dimensions

model C holds one flow per *advective* transfer -- `Q`, indexed by
`AdvectiveTransfers`, a sub-set of `Transfers` -- and every advective
transfer's rate reads `Q` with no index. The builder refused it: a transfer
answered implicitly for `Transfers` itself and for nothing derived from it. Index-name resolution walks the available indices -- the current
transfer's own, the current compartment's, the source and target -- and for
each dimension asks `indexListToSearch.contains(availableIndex)`, then

```
for each dimension of the block being searched:
    mapped list   -> follow the mapping to the index it names
    sub-set       -> look the index up by name
    root list     -> the index itself
```

so a sub-set is searched by name and a mapped list by the element that maps
onto the block. `derivedIndex` in `src/sim/builder.js` does the same through
`IndexSpace.relate`, for the implicit index and for a written `_source_` or
`_target_` alike; a block the list does not reach is refused, naming the list.
The model builds and runs after this (and after the transport work above,
which it also needs: seventeen of its sub-systems are transports).

### The two material dimensions

Ecolego has three material lists, not one, and the index-list model creates
all three in its constructor, marks each with a `predefined-type` and maintains
them from one flat list of materials:

| list | what it holds | how |
|---|---|---|
| `Contaminants` | every material the model knows | one index per a contaminant |
| `Radionuclides` | the ones that have a half-life | a **sub-set** of it, one index per a radionuclide |
| `Elements` | the element of each | a **mapping** onto it, one index per element |

`materialAdded` is where they are kept in step: every material goes into the
catalogue, and one that is a nuclide goes into the sub-set and brings its
element with it. All 87 readable projects here carry all three.

This tool had **one** list doing both jobs, flagged `for_contaminants`, and that
turned out to be a difference that costs a user real work. In an imported model
`Radionuclides` carried the flag *and* its `sub_set_of: Contaminants`, so the Index
lists panel took the sub-set branch -- "taken from Contaminants, so they are picked
rather than typed" -- and returned before the add field and the ICRP 107 button.
The only way to add a radionuclide was to type the name into `Contaminants`, come
back, tick it in `Radionuclides`, and type a half-life by hand.

So the role is split in two: `for_contaminants` marks the catalogue -- which is
what the word says -- and `for_nuclides` the sub-set. What each is for:

- - **The catalogue** takes typed indices of its own, and those are materials
  that do not decay. It is not a theoretical case: the corpus carries stable
  carbon beside C-14 (`Carbon_12`, in kgC), `C-12`, `water`, and a
  Lotka-Volterra model whose two materials are `Rabbit` and `Fox`. Blocks are
  indexed by it heavily -- 3,565 transfers, 1,482 compartments, 1,786
  expressions, 491 parameters across the corpus. - **The radionuclides** own
  their indices: this is where a name is typed, where the ICRP 107 browser
  adds, and where the half-lives and the decay chains are edited. Adding one
  adds the material to the catalogue as well; removing one removes the
  material, which is what deleting it in Ecolego's Materials view does. A
  material that should stay in the model without decaying is added to the
  catalogue instead. - **A compartment may be indexed by either**, and one on
  the catalogue decays the materials that decay and carries the rest
  unchanged. That needed no engine change: the decay table is already built
  per list over that list's own indices, and `lambda` reads a name it has
  never heard of as not decaying. It is also what the generated code does --
  it looks each index up in the contaminant catalogue and decays the ones that
  are nuclides, rather than consulting the `Radionuclides` list.

That last point matters for two real files. one far-field model
writes `Radionuclides` **empty** while its material model holds ten nuclides
with half-lives, and Ecolego runs it and decays them. So membership of the
sub-set drives the editor -- where you add, what the half-life table lists --
and never the engine, and the importer repopulates an empty list from the
material model, which is what `materialAdded` would have done.

**A sub-set of the radionuclides becomes a sub-set of the catalogue.** Making
`Radionuclides` a sub-set makes a model's own selection of nuclides a sub-set of
a sub-set, which neither this tool nor Ecolego has -- the index-list panel greys
"create sub-set" out on a list that is already one. It is re-pointed rather than
refused: the catalogue holds every name the radionuclide list holds, so the
selection is the same selection and everything indexed by it is untouched.

A file written before the split says so in one of three shapes, and
`splitMaterialRoles` reads all three (`src/domain/indexlists.js`): the flag on
`Radionuclides` with `Contaminants` above it, the flag on `Contaminants` with the
sub-set unnamed, or the flag on a lone list with no catalogue at all -- where
one is made holding the same materials. Every block keeps the dimension it was
indexed by, the catalogue starts out holding exactly what the radionuclide list
holds, and the corpus is identical file for file.

### Units per material

Ecolego holds a unit per material (a contaminant’s unit) and a compartment
reads it off the material at the index rather than carrying one of its own:
`Compartment.getUnit(indices)` looks each index up in the material model and
returns that material's unit when it is auto-managing. `autoUnit` is `ON` for
1,588 blocks in the corpus.

A radionuclide's unit is **not** stored. The contaminant catalogue keeps one decay unit
for the whole model and holds every nuclide's own equal to it, so it follows
`decay_unit` and cannot drift from the decay term it labels -- an inventory of a
radionuclide is an activity or an amount and there is no third thing it could
be. Only a material that is not a radionuclide carries one, and the importer
reads `<unit>` off `<material>` elements only. That rule also disposes of the
oldest file here, which
writes a *half-life* unit in that field -- `<unit>d</unit>` on a Cs-134 whose
inventory is Bq.

Units are labels in this tool, never arithmetic, so per-material units are a
labelling rule and nothing more:

- a block that states a unit means it at every index -- that is Ecolego's unit
  auto-management switched off, and a concentration in `Bq/m3` must not be
  relabelled `kgC` at one column;
- a block that states none takes each index from its material;
- a compartment with no unit is filled in from its material dimension only when
  that dimension has one unit to give. On the radionuclides it always does; on
  a catalogue holding both kinds it does not, and the block is left unlabelled
  so the per-index units can speak.

Measured across the corpus: three projects change a label, and both changes are
corrections. one lake model has one compartment the file left
blank which now reads `kgC` instead of `Bq` -- it is a carbon model --  and
one small test model has four that now read as nothing rather than claiming `Bq`, since
its three materials carry no unit at all.

`IndexOperation` and `Aggregate` reduce a dimension *inside* the model, and
both are here — see `src/domain/reduce.js`. Neither needed new machinery in
the code generator: an index operation is a call to the language's own `sum`
over the target's indices, and an aggregate is the same call over several
blocks, which is literally what an aggregate assembles before handing
the tokens to the ordinary equation compiler. They therefore get the analytic
Jacobian, the dependency ordering and the per-index values without a line of
new codegen — a `max` over four objects differentiates to the derivative of
whichever object is currently largest.

The one thing built directly rather than through the parser is the reference
node: a reduction pins the dimension *by the list's name* rather than by an
index name, because a target indexed by a list and a copy of it carries the
same index names twice and asking by name would pin the wrong one.

Not carried over from the index machinery:

- an intersection list as a list of its own, and mappings spanning more
  than two lists. A transfer written over one is still read: where the
  intersection is a list the model already names -- which every one in the
  corpus is, a sub-set against its own root -- the transfer takes that list.
  See *What the real files contain*.
- Scenarios as separate runs. A scenario list is read and marked, and left out
  of a reduction's dimension count as the reference does, but this tool solves every
  scenario at once as an ordinary dimension.

## Importing .eco projects

`src/io/eco.js` reads an Ecolego project. Three dependency-free supports: a ZIP
reader (`zip.js`), a raw-DEFLATE decompressor (`inflate.js`, for platforms
without `DecompressionStream('deflate-raw')` — Node before 20.12, older Safari),
and a small XML parser (`xml.js`, because Node has no DOMParser).

Two container formats are accepted: a ZIP with `model.xml` at its root
(Ecolego 6), and a bare XML file, usually UTF-16BE with a BOM.

### An empty list of times

`<discrete-times>` holds a custom time series, and in every one of the eleven
assessment models of one series it holds an empty one:

```xml
<discrete-times><time-series type="custom"><values>[]</values></time-series></discrete-times>
```

Read as `[]` -> `''` -> `split` -> `['']` -> `Number('')` -> **0**, and
`Number.isFinite(0)` is true, so each of those models arrived with a second
output series holding the single time zero -- before the start of a run that
begins at 2000. Harmless, since the solver never reaches it, and invisible:
the times it contributes are clipped away and the count beside the series said
nothing.

What found it was the saved-times warning added for exactly this shape of
silence -- *Series 2 (1 times) is entirely outside the run (2000 to 1.02e5), so
it saves nothing* -- appearing on all eleven models at once, which is not what
eleven independently-written assessments look like. The fix is to drop empty
tokens before they are read as numbers rather than after.

### Endpoints

`<simulation-settings>` carries the blocks Ecolego keeps results for:

```xml
<outputs>
  <output id="NearField&#46;waste_domain_length"/>
  ...
</outputs>
```

the run writes a result series for those and for nothing else. This
tool keeps every series a run produces -- they are worked out from the states
on request, so holding them costs nothing until they are asked for -- so the
list decides nothing about a deterministic run. It is still the modeller's own
answer to "which of these three thousand blocks did I want?", which is exactly
what a probabilistic run should keep, so it is read into `simulation.endpoints`
and the endpoint picker opens on it.

Two things about the file are worth knowing. **The ids repeat**: Ecolego writes
one `<output>` per index of an endpoint, so model B lists 746 of
them for 102 blocks. A repeat is not a fault and is not counted as one. And
**an id is a qualified name** here (`NearField.waste_domain_length`), which is
what it is matched by first; `blockNameById` answers for the blocks this tool
had to rename, and it is consulted second because it is older than the model --
it was built before groups were flattened, so a block that moved out of a group
is under a name the map no longer knows.

### What the file says about itself

`<project-properties>` carries the author and the comment as
`<property name="...">` elements, not as elements of their own:

```xml
<project-properties name="model">
  <guid><![CDATA[7CE02604-BD80-11EB-ACD7-005056AE12AF]]></guid>
  <modification-date>1621966224401</modification-date>
  <property name="author" type="string"><![CDATA[a.modeller]]></property>
  <property name="comment" type="string"><![CDATA[Created at Tue May 25 17:41:51 UTC 2021]]></property>
</project-properties>
```

Read as `<comment>`, which is what this did, the comment was never found and
every imported model arrived with an empty description. `propertyText` — which
the importer already used for the awkward properties elsewhere — is where it
actually is.

`name="model"` is Ecolego's default and is what **every** file in the corpus
says, so the file's own name is used instead when there is one; the declared
name is kept when it is anything else, and when there is no file behind the
XML. This was visible before it was understood: an exported HDF5 file called a
whole safety assessment `model`.

`.version` at the archive root is a properties file —
`version=6.5 track-changes=false ode-required=true nuclidedb-required=true` —
and is the only thing in a project that says which Ecolego wrote it.

All of it goes into the model's description, together with a count of what came
across, what the model is indexed by and what a run of it does
(`describeModel`). The counts are taken at the end of the import rather than
while reading, so they are of the model as it ended up — after blocks are
renamed, groups flattened, sub-system interfaces connected and unreachable
targets dropped — rather than of the file as it was spelled.

### Measured against 199 real project files

The importer was **validated against the `.eco` files on this machine**, not
only against synthetic fixtures. Current state:

| | count |
|---|---|
| `.eco` files found | 200 |
| Ecolego 6 format — imported without error | **71** |
| of those, validated and code-generated | **35** |
| Ecolego 4/5 `<sheet>` format — refused with an explanation | 106 |
| other containers — not recognised | 23 |

Why the 36 that import but do not yet build:

| | count | |
|---|---|---|
| unresolved name | 18 | a block type this tool skips, read by an equation |
| index projection | 6 | index-list relations this tool cannot resolve |
| missing function | 5 | user-defined functions and PDFs — the functions are supported now; see below |
| other | 7 | one each; see the list in the run log |

**Models with no compartments now run.** They were 15 of the failures and are
the commonest shape in the corpus after the transport models: they read a
release computed elsewhere and work out a dose, so there is nothing to
integrate. The algebraic blocks are evaluated over the output grid instead --
the same generated function, called on a grid rather than by a solver. Ten of
the fifteen build and run; the rest stop on a skipped block type like everything
else. A model with neither compartments nor equations runs as well: refusing
one meant that emptying a model, or starting one from nothing, reported a fault
in the file, and an empty chart with a note in it beats an error message.

**Sub-systems used to be the biggest blocker, and are supported.** 26 files failed
on a qualified name; none do. 66 of the 71 importable models use sub-systems —
1325 of them across the corpus, nested up to five deep — so this was not an
optional feature but the shape real models are written in.

**`lookup-table` was the next biggest, and is supported.** It took the count that
builds from 7 to 21. 3382 tables come across, in 28 files, carrying 238 469
points; 148 of them are argument-keyed. None is skipped.

**Two-dimensional index references work too**, and no file now fails to
parse: `M[_Ra-226][Pb-210]`, `Ecosystem_area_objects[11][Lake]`. That was 7
files, which turn out to be three distinct models copied about; each has now
moved on to its own next gap — an element/nuclide relation, an index
aggregation, and user-defined functions — so the build count did not move. The
gain is real but not yet visible in that column, which is worth saying plainly
rather than quoting the parse count as progress. (The third of those, the
functions, is supported now — see "User-defined functions".)

**Index operations and aggregates are supported too.** 185 index operations and
11 aggregates come across, in 18 distinct models. None of those models builds
yet — every one is held up by something else, mostly the element dimension
below — so the count in the table above did not move. What can be checked
without a working build is the semantics, and that is checked: **all 185 index
operations and all 11 aggregates (76 targets) satisfy Ecolego's own dimension
rule**, which is what the index-operation rule and the aggregate rule
enforce. Twelve reductions of block types this tool does not have are skipped
and listed in the import report rather than left dangling.

Two smaller fixes found while testing the lookup feature account for part of
the same jump, and are worth naming because both were silent:

- **A block with no index lists was being made per-nuclide.** An `.eco` file
  states every block's dimension, and an empty one means *scalar*. The importer
  dropped the empty list, and `Project`'s "one value per nuclide unless told
  otherwise" default then took over — which gave every scalar parameter a
  nuclide dimension and made each equation that read one from a non-nuclide
  block unresolvable.
- **A reference inside a sub-system was classified by its written name.**
  `makeLocator` resolved `Water` to `NearField.Water` correctly and then asked
  `stateByName.has('Water')`, which is false, so a compartment reference was
  treated as algebraic and read out of the wrong array. The generated code was
  wrong rather than broken: it compiled and ran.

### What the real files contain

Several things the format's own documentation does not settle, each read off the
corpus and covered by a test:

- **Index ids are scoped to their list, not global.** Two lists may each hold an index with id `H`. The file format resolves an entry's ids against the
  *block's own* index lists, positionally; a global id map silently attaches
  entries to the wrong dimension.
- **`transfer` and `transfer-coefficient` have opposite donor defaults.** The file format creates a plain `transfer` with `TransferEntry(null, false)`
  — an absolute flux — and the legacy `transfer-coefficient` with `true`.
  Defaulting every transfer to multiply-by-donor silently multiplies fluxes by
  their donor compartment.
- **`source` and `sink` are components, not connections.** Transfers attach to
  them; they are Ecolego's model boundary, which this tool writes as a null
  endpoint. Treating them as unsupported blocks left transfers dangling.
- **Names are not unique.** Two blocks in different sub-systems may share a
  name, so name mapping has to be keyed by block id.
- **Hyphens are escaped** as `&#45;` inside attribute values, so `type` reads
  `lookup&#45;table` — the XML parser must decode entities in attributes.
- **A transfer's dimension is not a choice.** It is the intersection of its two
  ends' index lists, kept in step as either end changes, and no file format in
  this family offers a picker for it. What makes the rule total is the check on
  adding a transfer,
  which refuses the connection outright unless the two ends correspond position
  for position: the same list, or one a sub-set of the other with a shared
  root. Positions are matched by **root**, not by order, and the scenario
  dimension is left out of the whole computation, as the desktop tool leaves
  it out.

  So a flux here takes what its ends share, and takes it again whenever either
  end changes — the same arrangement the derived units already have, one pass
  after each edit rather than a listener per transfer. Measured against the
  corpus first: of **8,879 imported transfers, 8,875 already had exactly that
  dimension**, and the other four are scenario-only fluxes that the files
  themselves write as scalar, which is what excluding scenarios produces.

  **What this tool keeps that Ecolego has not.** Two of `landscape.json`'s three
  transfers are shapes the desktop tool would refuse: one runs from
  `[Radionuclides, Object]` into `[Radionuclides]`, summing over the objects,
  and one is narrowed onto `Wetland`, a sub-set of what its ends share, so a
  loss applies only to the wetland objects. Both are worth having. So the
  derived dimension is what a flux gets and what it follows, and a *narrowing*
  the model states — the same dimensions, some of them taken to a sub-set — is
  left alone. Dropping a dimension is not a narrowing but a reduction, and
  neither is an empty one: reading `[]` as "a narrowing of everything" left
  every scalar flux scalar whatever happened at its ends.

  The two are not kept on the same terms, and the difference took a second
  pass to get right. A narrowing is unambiguous: every cell of the flux still
  names one cell at each end. Ends of *different* dimension are not, and the
  first version of this tool let them through in silence. The desktop tool
  refuses a transfer whose two ends do not agree on their scenario dimension
  count, and its dimension rule then assumes as much. A flux that carries a
  dimension one end has not got reaches
  that end's one cell from every index of it: the engine emits one loop over
  the flux's own index space, and the end's offset does not move as the extra
  dimension is walked, so `out[target] += f` accumulates. A total delivered
  into a target, or a donor drawn down once per index. Mass is conserved; what
  is lost is that the model ever said so, and a number that is a total reads
  exactly like a number that is not.

  So the shape is still allowed — a discharge from every landscape object into
  one downstream compartment is a real model, and writing it as twenty
  transfers is not better — but only where the flux says `sum_extra_indices`,
  and the default is Ecolego's refusal. `summedDims` in `src/domain/indexlists.js`
  is the rule, `Project.validate` is the gate a file passes, and the settings
  dialog offers the tick exactly where there is something to add up. The cost
  of the change is measurable and was measured before it was made: **0 of
  48,016 fluxes across 134 real models on this machine** have the shape, which
  is what a corpus written by a program that refuses the shape should look
  like. The one model here that did was `examples/landscape.json`, which now
  carries the flag and a comment saying why.
- **`index-lists=""` with `dimension="1"` is a dimension, not the lack of
  one.** Ecolego has a fourth kind of index list this tool does not:
  an intersection list, *"used by Transfers. When the Transfer is connecting
  two Compartments, and these Compartments have different sets of indices, this
  index list will make sure to contain only indices that are present in both"*.
  It is built with `super("")`, so it has no name and no id, and `createIds`
  writes it out as nothing at all. Read as written, that transfer is a scalar
  between two compartments of 49 indices, and the build refuses it — *"'A' is
  indexed by 'Contaminants', which 'flow' is not indexed by and cannot reach"*.
  94 transfers in three projects here are that shape. Since the intersection is
  by index **name**, a sub-set *is* the intersection of itself and its root,
  and all 94 are exactly that pair — `Contaminants` against `Radionuclides`,
  either way round — so the transfer takes the sub-set. Two lists that merely
  overlap have an intersection no list of the model names; there is nowhere to
  put that, so it is reported rather than guessed at.
- **Stable isotopes** appear in material lists with an infinite half-life.
- **An index name is raw text, not an identifier.** index parsing
  reads to the closing bracket and no further, which is the only way
  `A[F.18:00_51_FORSMARK]` and `A[B.04:00_205_BARSEBÄCK]` can be read at all.
  Tokenizing the contents also left `Cs` inside `A[Cs-137]` looking like a
  block reference to anything walking the token stream, so renaming a block
  called `Cs` corrupted the nuclide name.
- **A reduction's dimension count excludes the scenario list.** Ecolego counts
  with `getDimensionForScenario`, so a block indexed by `Scenarios × A × B` and
  reduced to `A` is reduced over `B`. Eight blocks in the corpus are shaped
  that way, and reading them without the exclusion reduces the scenarios. The
  list is marked in the file by a `predefined-type` property of `SCENARIOS`.
- **A model keeps two nuclide lists, and indexes compartments by either.**
  `Contaminants` is the catalogue and `Radionuclides` the sub-set of it that
  decays; different models use different ones, and one uses both. Decay is
  therefore computed per list, over that list's own indices — treating one as
  *the* material dimension left every compartment indexed by the other with no
  decay term at all, which is a wrong answer that looks like a right one.
- **`nuclides:` must not add a list beside one the file already states.** The
  shorthand synthesised a second `Radionuclides` list, no block was indexed by it,
  and it was the one `materialList()` returned — so every imported model ran
  without decay. Two bugs, one symptom, both silent.
- **Index brackets are matched by name, not by position.** Index-name resolution gives each of the target's dimensions
  whichever written index its own list contains. 200 of the 506 two-bracket
  references in the corpus are written in an order a positional reading would
  get wrong.
- **A lookup table's points are one array per entry**, written by
  the array syntax — `[0.0, 10.0, ...]` — in two parallel elements,
  `<lookup-table-time-points>` and `<lookup-table-values>`. The two are walked to the shorter of them, so a truncated
  file loses the tail rather than the table.

Where a file's own writer and its reader disagree, the reader wins: block type
names and their defaults are taken as the file spells them.

### Sub-systems

Ecolego organises a model into sub-systems, which nest, and **scopes names
inside them**: two compartments called `Water` in different sub-systems are
different compartments, and an equation inside one of them that writes `Water`
means its own.

This tool keeps a block's own `name` and adds a `system` — the dotted path of
the sub-system holding it. Its **qualified name** (`NearField.Water`) is the
one string the rest of the application addresses it by, so a model with no
sub-systems is spelled exactly as it always was, and nothing outside
`src/domain/systems.js` had to learn about the hierarchy.

Four rules, all taken from the source material rather than invented:

1. **An id is `namespace + "." + name`.** The id rule builds it against the nearest *namespace* sub-system.
2. **A group sub-system is not a namespace.** A plain grouping declares no namespace, so the id rule skips it, so its blocks belong to the
   sub-system around it. The importer flattens groups away, which is what the
   ids in the file already say.
3. **How a reference resolves is the mirror of how it is written.**
   The desktop tool writes a target's *local name* when it shares the writer's namespace or sits at the root, and its
   *full id* otherwise. So a bare name is mine, or failing that the model's; a
   dotted name is a path from the root. An intermediate ancestor is deliberately
   **not** searched — Ecolego never writes such a reference, and an outward walk
   would resolve names it never meant, possibly to the wrong block.

4. **A connection belongs to its donor's sub-system.** `Sub.C1 -> C2` is a
   transfer *out of* `Sub`, and it lives in `Sub` — so its rate equation is
   written and resolved from inside `Sub`. Counted over the real files here:
   of the 1,333 transfers whose two ends are in different sub-systems, 1,333
   sit with the donor and **none** at the top level; all 358 outflows sit with
   their donor too, and every one of the 4,648 transfers in the corpus keeps
   the rule. A connection with no donor — a source, or an inflow from outside —
   has only its receiver to follow.

   This is an invariant and not just a default for new connections, so a
   compartment that moves takes its outgoing transfers and its source terms
   with it, and re-attaching a transfer's donor end moves the transfer.

The format has one genuine ambiguity, which Ecolego shares: with a `Volume`
inside `A` and another at the root, both are written `Volume`. The nearer one
wins, which is the only reading under which a sub-system's own block is its own.
Connection endpoints avoid the ambiguity by being ids: a name that already names
a compartment is that compartment, and only otherwise is it read relatively --
without which a connection inside a sub-system could never reach a top-level
compartment whose name the sub-system also uses.

### Output times

`<simulation-settings>` carries how Ecolego reports results, and this tool used
to ignore all of it and default to 250 logarithmic points. It is read now:

- `<output-options>` chooses between the three `EOutputMode`s — the solver's
  accepted steps (*Produce no additional output*, Ecolego's default), those
  plus the specified times (*Produce additional output*), or the specified
  times alone (*Produce specified output only*). Older files write the index
  into the setting's allowed values, `0`/`1`/`2`, rather than the words; both
  are read. `<batch-mode>` overrides the option, because
  the output mode tests it first.
- `<time-series-list>` and `<discrete-times>` hold the series: `geometric`,
  `linear`, `linear-increment` and `custom`. The first two map straight onto
  this tool's own; an incrementing one says how far apart its points are rather
  than how many there are, and is converted, with a warning when the step does
  not divide the span evenly. The date-based variant is not read.

- - A series' own first and last time may be the “not set” sentinel,
  `-792842341234.234` — the one magic double a project file writes wherever a
  number was left alone, and which appears somewhere in 86 of the 87 projects
  here (mostly as a step size, which this tool does not read). All three
  generators open by replacing it with the simulation's own start and end, so
  it is read as absent, which is what this tool's series mean by an empty
  *from* or *to*. Read as a number instead it is a time 800 billion years
  before the run, and the series that says it produces nothing at all: 28 of
  the 145 series here have it as a start and 23 as an end.

Across the 87 readable projects here: 43 ask for specified times, 44 for the
solver's own steps, four carry five series each, and one carries a list of
discrete times. None of that used to come across.

### Sub-system inputs and outputs

Ecolego routes a value across a sub-system boundary through three blocks: a
`model-output` lists blocks inside its sub-system that may be read from
outside, a `model-input` lists blocks inside its own that may be fed from
outside, and a `connector` between them carries `<model-connection
source target/>` pairs naming one of each by GUID. They exist so that a
sub-system can be lifted out as a black box, put in a library, and dropped into
another project with its wiring left loose, ready to be connected.

There is nothing to build on there — this application has no such library — but
*not* carrying the wiring is not neutral, and this is the trap. What a
connection means is written into the generated code: the fed block's
whole calculation is replaced by a reference to the block feeding it. An
unconnected input is a **placeholder**, and every one in the corpus reads `0.0`
or a constant. Read without the connections, a model does not fail — it runs,
and reports zero. one comparison model had **117 of its 324
series identically zero** that way: a whole biosphere object receiving nothing
from the near field.

So the three blocks are read for their wiring and then thrown away, and the
wiring is written straight into the blocks at each end:

    fed block's equation  :=  feeding block          (one source)
                              sum(a, b, ...)         (several)

Where several outputs feed one input they are combined with the operation the
input names — a model input’s operation is `ADD`/`MAX`/`MIN`/`MEAN`/`PRODUCT` and
this tool's own functions happen to be spelled the same way. A file that names
no operation for a multi-source input adds them, which is the format's default.

Three details the corpus forced:

- **Either end can be a transfer.** 25 of the 41 sources and 11 of the targets
  are, and what is read and written is the transfer's rate — `getReference`
  with no prefix calls the default `calculate` method, not `flux_`. (It makes
  no difference to any real file: every transfer involved is an absolute flux,
  so rate and flux are the same number.)
- **A fed parameter becomes an expression.** It no longer holds a number of its
  own, and a parameter here is a number. one base-case model's two fed blocks are
  parameters carrying 52 per-nuclide values each.
- **The fed block's per-index values go.** The generated code reads none of
  them — the connection replaces the calculation at every index — so leaving
  them would override the connection at exactly the indices the model wrote
  down.

An input connected to nothing is left exactly as the file has it: it is a
socket, and an empty socket says nothing about the block behind it. Three of
the 13 projects that carry an interface are in that state, with 11 interface
objects between them; the other 10 carry 41 connections.

### Not mapped

The other ~20 block types, presentation state, scenarios, probabilistic
settings and results. Sub-systems are read, transports included -- see
"Transport sub-systems" -- and the *external* flavour is read as an ordinary
one, with a warning. Skipped blocks are listed in the import
report rather than dropped silently; `influence` connections are noted
separately, since they carry no mass and declare only an evaluation order this
tool derives from the equations themselves.

Two wrinkles worth knowing:

- Ecolego block names may contain spaces and punctuation; this tool's
  identifiers may not. Such blocks are renamed and every equation is rewritten
  textually. That rewrite cannot be token-based, precisely because the original
  names do not tokenise — so check the rewritten equations.
- Ecolego can obfuscate a project on save (the archive writer
  encrypts entries with PBE). Encrypted archives are detected and refused.


## Scenarios

An Ecolego index list may be marked `predefined-type = SCENARIOS`. It is not an
axis of the model: it is a set of alternative futures, and Ecolego runs one
simulation per scenario.

**Three ways a file says which list that is, and this tool used to read one.**
Of the 87 readable projects here, 26 carry a scenario list. one small vault model
writes the marker as `SCENARIOS`; the older an older file writes `Scenarios`, and
compared as written that one lost its scenario dimension *and* its element
dimension -- the marker was there, spelled the other way. (The material
dimension survived only because it has two fallbacks behind the marker: the
sub-set shape, then the widest candidate.) The oldest files here,
one carbon-14 model among them, write no `predefined-type` on any
list at all, and then the name is the only thing left -- `Scenarios` and
`Elements` are what Ecolego calls its own. So the type is read case-
insensitively, and a list of that name claims the role when nothing else does.
A file that says which list it means is believed: a list *called* `Scenarios`
beside one *marked* as the scenarios is an ordinary axis. With all three, every
one of the 26 is read. Every scenario list that was previously missed is empty,
so no model's state vector changes -- the corpus is identical file for file.

This tool runs **one at a time**, chosen in the panel, which is exactly what one of those runs does. Put plainly: with a
scenario selected, a scenario-dependent block is treated *as if it were not
scenario-dependent*, with that scenario's index inserted automatically. So the
implementation is two operations on the index space and nothing else:

- `withoutScenarios(dims)` — what the simulation sees. This is
  the scenario rule: the dimension count the generated code is actually
  written with, so the scenario never reaches the state
  vector, the widths, the strides or the result labels.
- `pinScenario(dims, tuple)` — the tuple a stored value is read at, which is
  wrapping a value for a scenario.

The dimension stays a dimension for *editing*: a parameter still holds a value
per scenario and the entry grid still shows one row each. Only the simulation
drops it.

A block reaches the dimension through the scenario list itself, through a
**sub-set** of it, or through a list **mapped** onto it. `setObject` walks a
block's lists for one whose root is the all-scenarios list, and takes the index
by name for a sub-set or through the mapping for a mapped list; this tool's
root/`up`/`down` tables already answer both, so `scenarioIndexIn` is four lines.
When the active scenario is not in a sub-set, there is no index for it and the
block falls back to its default — which is what a null index
amounts to.

This is what the two remaining "cannot be reached from" failures in the corpus
were: a block *not* indexed by `Scenarios` reading one that is. There is now a
scenario to read it at. Builds went **43 to 46** of the 241 files on this
machine, and two models that use scenarios in earnest now run —
one comparison model with ten of them and one running-water model
with two, whose two scenarios give visibly different answers (`q_s` 7.5 against
7.6, and everything downstream with it).

**Several at once, since.** The page runs the scenarios ticked beside the
selected one (`src/ui/scenarios.js` holds the rules, `app.js` the running) as
runs of their own: the model with another scenario selected, each posted to a
page-level simulation worker of its own. Not children of the selected
scenario's worker -- a worker's children cannot be reached by the page, their
progress would wait on the parent's synchronous solve, and a browser that will
not nest workers would lose the feature. As page workers they report straight
back, are stopped by terminating them, and each keeps its own `last`: a
scenario's results live where they were computed, exactly as the selected one's
do, and a chart asks each scenario's worker for its columns (`r.worker` on the
result set routes `sendColumnAsk`). The same messages the selected one is sent
-- `run`, `re-evaluate`, `columns` -- so a scenario whose integrating part has
not changed is only re-evaluated, with its own integration key.

Three rules keep them honest. A scenario's lines are drawn only beside results
of the same model revision (`shownScenarioRuns`), so a run in flight never mixes
two models on one chart. They are not drawn through a probabilistic sample,
whose line is a median; the table and the exports, which are of the runs, still
carry them. And the whole of what Run started is one run to the interface:
`running` stays set until the last scenario is in (`primaryBusy` is the
selected scenario's share), Stop terminates them all, and how many go at once
follows the Cores setting, `runsAtOnce` of it. What remains deliberately absent
is per-scenario *settings* -- every scenario runs with the model's.

## Disabled blocks

The enabled flag is written on every block in a project file as
`<enabled>true|false</enabled>`, and a disabled block is drawn greyed. What it
*means* is that the block is kept and takes no part in the run, and a model with a broken block in
it runs as long as nothing that is enabled reads the broken one.

Reading every block as enabled is wrong in practice. Nine of the 87 real projects
switch something off -- 139 blocks between them, and four whole sub-systems --
and model L switches off 29 blocks and two connectors,
among them an expression reading a block that is not in the file at all. Read
as enabled, that one expression failed the build of 3,845 blocks. Read as
Ecolego reads it, the model builds, and so does one landscape-object model, whose
`Screening` sub-system is off as a whole: over the corpus the build failures
went from 37 to 31 and the models that run from 44 to 46, with nothing moving
the other way. (model L itself builds and then wants more than the two
gigabytes Node gives a run by default -- 16,244 states and 201,004 algebraic
values at 498 output times is 800 MB of results before anything else -- which
is a size question, not a switch question.)

How it is carried: `enabled: false` on the raw block, and the absence of the key
is on. `Project` drops disabled blocks from every collection it builds and keeps
their names in `project.disabled`, so the builder can say *`X` is disabled* for a
reference to one rather than *unknown name*. `edit.allEquationProblems` skips a
disabled block's own equations and `equationChecker` reports a reference to one
from an enabled block, so the problem strip and the box being typed into agree
with the build. A disabled connector or sub-system interface in an `.eco` file
routes nothing, which is the other half of what model L needed.

What a connection does when its compartment is off is Ecolego's rule, read off
the source rather than chosen:

```
a transfer is enabled  <=>  its own flag and its sub-system's are on
                            AND it has no source, or the source is enabled
```

The inherited half is the block's own flag and its sub-system's, and only the
*source* is added. So a transfer out of a disabled compartment is off with it,
and a transfer into one stays on: its flux leaves the donor, and with no
compartment class written for the receiving end, leaves the model. The tool
does exactly that (`Project._followDisabledEnds`, aiming the transfer at the
boundary), and says so in the Information view. Model C has
a disabled compartment with an enabled transfer out of it; refusing that
combination -- the first thing this tool did -- would have refused a real
model. An influence or a connector requires both ends, which is
why a disabled connector routes nothing.

**A sub-system has a switch of its own**, and honouring one on import by
switching off every block inside it instead would be equivalent for the run and
weaker for editing -- the blocks could not be brought back as they were. Four
real projects use one, all to keep a screening version of a landscape beside the
live one. A sub-system is a path its blocks wear and has nowhere to carry a flag,
so the switch is a list of paths beside
`transports`, `disabled_systems`, because a sub-system is a path its blocks
wear and has nowhere else to carry a flag. What it means is the
implicitly-enabled rule -- a block's own flag *and* its sub-system's -- read
off the raw model by `isEffectivelyEnabled` and at the file gate by `Project`,
which sets every block inside aside with the reason *it is in 'NF', which is
disabled*. The blocks keep their own switches, as Ecolego's do, so the
sub-system comes back as it was; a copy of a disabled sub-system is disabled;
the flag follows a rename, a move and a delete as `transports` does; and a
stale path in a file is refused rather than switching nothing off.

## Transport sub-systems

A transport sub-system is how a model discretises transport through a
homogeneous material without drawing every slice: two compartments,
`TransportBegin` and `TransportEnd`, the transfers between them, a a
`transport-number` N, a `transport-element-counter`, and any number of
`transport-operation`s. The first four are made with the sub-system, under the
names a project file gives them -- `Begin`, `End`, `N`, `i` -- and this tool's
**New transport here** does the same.

The run-time semantics are in the generated transport code, which generates
one class for the whole chain. N states are laid out side by side per index
tuple, and two static ints say which pair of neighbours is being worked on
while the derivative is assembled:

```
a chain of one:   dydt = the single-compartment equation
otherwise:        Begin = 0, End = 1     -> the Begin equation
                  for i in 1 .. last-1:
                      Begin = i-1, End = i    -> the internal equation
                  Begin = last-1, End = last  -> the End equation
```

Two static indices say which pair of neighbours is being assembled while the
loop runs, which is what lets one equation stand for every slice.

`writeGetStatesMethod` turns a reference to Begin into `getStateAt(pos +
BEGIN)` and one to End into `getStateAt(pos + END)`, so the transfer equations
drawn between the two read whichever pair is current; `getCurrentElement`
answers `BEGIN + 1`, which is what the counter is; and
`writeGetInitialConditionMethod` sets `BEGIN = i` and reads **Begin's**
initial condition for every element -- End's is never read. With N = 1
(the single-compartment equation) there is one state, every
transfer drawn into or out of either end applies to it, and
The connections between them are dropped, End's value is the last cell, and
the generated code produces the sum, the mean, the element at a
fraction of the length (`(int)(arg0*n)`, or `n-1` for exactly 1) and the
weighted sum over a stretch, with a `SolverException` for a position outside
0..1.

**How this tool does it.** The same chain, unrolled before the model is built
rather than looped over inside it. `src/sim/transport.js` rewrites every
transport into ordinary blocks: N compartments, the first keeping Begin's name
and the last End's, the ones between named `Begin_2 … Begin_{N-1}` and marked
`hidden`; N-1 copies of every transfer drawn between the two, one per pair of
neighbours, with Begin, End and the counter substituted (`Begin_2`, `Begin_3`,
`2`); and the same copies of any expression inside the transport that reads
the pair -- which is left uncached inside a transport for exactly this reason. Begin, End and the
counter are substituted token by token and by resolved name, the way every
other rewrite in this tool is done. The builder, the solvers, the Jacobian and
the results then see a model with nothing unusual in it, and the hidden mark
is all that keeps the middle of the chain out of the lists of results -- as
Ecolego's anonymous states are.

An operation read by name becomes an expression over the elements
(`Begin + Begin_2 + End`, divided by N for a mean). One that is called --
`Op(x)`, `Op(a, b)` -- is not a block at all after the rewrite: every call of
it, anywhere in the model, becomes `transport_point(Begin, Begin_2, End, x)`
or `transport_sum`/`transport_mean(…, a, b)`, three functions added to the
expression language for the purpose and transcribed line for line from
the transport operation, integer truncation and the refusal of a
position outside 0..1 included. They have no derivative rule, so a model that
calls one gets a differenced Jacobian and says so.

### A tangent only for what can move

Two rules in the tangent generator will not differentiate what they are given
rather than guess at it: `interpolationUseEndValues` and
`interpolationExtrapolation` refuse a table whose own *points* move with the
state, since the value is then a function of the table as well as of the point
read in it. They decide that by asking whether an argument has a tangent at
all -- and every reference to an algebraic block answered yes, because the
generated tangent of a slot is the symbolic `dX[i]` whether or not anything
ever writes something non-zero into it.

A table read at the clock is exactly that case. `interpolationUseEndValues(
time, threshold_start, WF_out_marine, threshold_isolation, q*area, ...)` --
one landscape object's flow of water out, and a shape half the real models use
-- has a time series among its values, whose `dX` the generator itself writes
as `0` two hundred lines earlier. The refusal fired anyway, and a 2,757-state
model declined its analytic Jacobian over one equation: a dense
finite-difference matrix at 2,757 evaluations of f to form, and a dense
factorisation of 2,757 x 2,757 to use, thirty-two times in one run.

The pattern pass already knows better. `SX` holds the state columns every
algebraic slot depends on, it is computed before the tangent function is
generated, and an empty set there means the slot cannot move with the state at
all. So the tangent resolver now answers `null` -- no tangent -- for a
reference to a block whose every slot has an empty set, and a live tangent
otherwise. The refusals stay exactly as sharp for a table whose points really
do follow a compartment; what goes is the false positive.

Nothing is taken on trust that was not already: the pattern decides which
entries the matrix has, so a dependency it misses is an entry that was being
dropped before this change too.

Measured on one 2,757-state landscape model, 2,757 states, the model
that prompted it:

| | before | after |
|---|---|---|
| analytic Jacobian | declined | 12,484 non-zeros of 7,601,049, 16 colours |
| evaluations of f | 2,956 | 199 |
| factorisation | dense | sparse |
| run | 261 s | 1.6 s |

The two runs agree exactly -- every one of the 2,757 compartment series, at
every one of the 356 output times, to the last bit. The model is nearly linear,
so Newton converges to the same root whichever matrix is iterated with.

Across the 114 files in the `.eco`/`.eas` corpus here that import and build,
seven models gain an analytic Jacobian and none lose one:

| model | states | now |
|---|---|---|
| two transport models | 1,675 | 5,423 non-zeros, 8 colours |
| three files of one landscape model | 2,757 | 12,484 non-zeros, 16 colours |
| model C | 8,427 | 30,316 non-zeros, 15 colours |
| model D | 10,229 | 40,763 non-zeros, 46 colours |

The last two were not refusals of the staircase at all: they were over the
statement ceiling on the tangent function, 60,000 at the time. A tangent for
every quantity that cannot move is a great deal of code that multiplies by
zero, and dropping it brought the two largest models in the corpus back under
the limit.

The block that declines a model is now named in the reason as well, which is
what turned a message about a function into a model that runs.

A declined model keeps its pattern. The values are refused, not the structure:
the pattern and its colouring are worked out before the tangent code is
generated, `buildJacobian` returns them with the refusal
(`b.differencingPattern`), and the runner hands them over with an `evaluate`
that answers null -- the numeric-Jacobian path -- so the solvers difference
the matrix through the pattern rather than densely. Before, a declined model of
nine thousand states needed a dense matrix of 0.7 GB, and the solver refused it.

### The tangent function's temporaries, and a worker's stack

A generated tangent function hoists its common subexpressions, and those used
to be `const` locals. V8 gives every local in a function a register in the
interpreter frame, so a large enough function cannot be *called*: it compiles,
`new Function` returns it happily, and the RangeError arrives on the first
call, from inside the solver.

How large "large enough" is depends on how much stack there is when the call
is made -- and **a worker has far less than the page**. Measured in this
browser, with the call two hundred frames down:

| locals | page | worker |
|---|---|---|
| 60,000 | callable | callable |
| 62,000 | callable | **RangeError** |
| 100,000 | callable | RangeError |

Runs happen in the worker. So the ceiling was a worker's stack, and every
number measured in Node or on the page was measuring the wrong thing.
model C -- 8,427 states, 67,578 statements -- compiled its tangent
function, failed the smoke test in the worker, fell back to a dense
finite-difference Jacobian, and sat on "Building the model…" for as long as
anyone was willing to wait.

The fix is not a number. The temporaries are slots in an array now (`T[12] =`
rather than `const v12 =`), carried on the runtime context that every
generated function already takes, allocated once with the system. The frame
holds a handful of registers whatever the model's size. Measured in a worker:

| | compile | one call |
|---|---|---|
| 68,000 locals | fine | **RangeError** |
| 68,000 slots | 36 ms | 2.3 ms |
| 300,000 slots | 176 ms | 10 ms |

So the limit is about work rather than frames now, and sits at 250,000
statements. The same model builds and runs in the browser in twenty seconds,
to numbers identical to the old path's. Two more corpus models gain an
analytic Jacobian, bringing it to 81 of the 120 that build; of the rest, 21 are
held by the 300,000-line ceiling rather than by this one, which is where to
look next.

### The statement ceiling, re-measured

The 60,000 was a safe distance rather than a measurement, and it cost a real
model its Jacobian by 13%. model C — 8,427 states — generates
67,578 tangent statements; its near-twin model C generates
56,335 and was fine. What the difference buys, on that model:

| | differenced | analytic |
|---|---|---|
| one Jacobian | 8,427 evaluations of f, ~85 s | 143 ms |
| one factorisation | dense 8,427², ~126 s | sparse, 30,316 non-zeros |
| the run (546 Jacobians, 288 factorisations) | ~a day | 120 s |

Measured rather than extrapolated at the ends: a 600-year slice of that model
takes 12.3 s with the analytic Jacobian and had not finished after 21 minutes
without it.

So the limit is now measured, at the depth that matters. Whether a generated
function can be *entered* depends on how much stack is left when it is:

|  locals | callable |
|---|---|
|  92,000 | a thousand frames down |
|  95,000–102,000 | two hundred frames down, not a thousand |
| 105,000 | not two hundred frames down |
| 110,000 | not at all |

The solver enters the tangent function a couple of dozen frames deep, so the
ceiling is 90,000: above the deepest model in the corpus, below the most
conservative measured row. And `smokeTest` now calls the compiled function
from two hundred frames down rather than from the top level, since another
engine's stack is not this one's and the number is only a first filter.

Six more files gain an analytic Jacobian at the new ceiling, four distinct
models and the largest in the corpus among them: model C (8,427
states), model D (10,229) and model E (in two versions)
(10,865, 43,147 non-zeros, 46 colours). 79 of the 120 models that build now
have one; of the rest, 23 are still over the ceiling and 17 have no
compartments to differentiate at all.

**Where that stands now.** The count above was taken before the tangent stopped
emitting one body per index tuple (*One body per equation, not per index*,
below). Swept again over the 302 `.eco` and `.eas` files on this machine:

| | then | now |
|---|---|---|
| built a system | 120 | 133 |
| analytic Jacobian | 81 | **112** |
| over the tangent ceiling | 23 | **3** |
| nothing to differentiate | 17 | 17 |

Three files and two distinct models: one landscape model (9,462
states) and another (8,662, present twice). One model
declines for an unrelated and correct reason -- one small file has a
non-finite Jacobian entry at its starting state, which is `refuseNonFinite`
doing its job. The largest models in the corpus all have one now, up to
model F at 55,728 states.

**Why those two resist.** `LandscapeAllChain_CC23` has 56,649 unrolled bodies
holding 1,446 distinct equations, and looping the dimensions its equations do
not vary along only reaches 38,819 of them: its worst blocks vary along *every*
dimension. one release-rate block is 741 values and twelve
distinct equations, **702 of them the literal `0.0`**.

Grouping by equation alone does not finish the job, and it is worth being
precise about why: where the tuples sharing an equation do not form a regular
sub-lattice, the same text still resolves to a different offset at each of
them, so the loop would need a table of offsets per reference, shipped as data
beside the code. **But 19% of those bodies hold no references at all.** A
constant needs no offset resolution however scattered its tuples are, so that
share can be grouped by equation with nothing more than a list of slots to
write -- which is the cheap next step, and a materially smaller job than the
general case.

### One body per equation, not per index

The ceiling above is about how much code is generated, and most of what was
generated did not need to be. A block whose indices all share one equation was
emitted as a loop (`entry.uniform`); a block whose equations differ was
**unrolled**, one copy of the generated code per index tuple. That is where a
large model's code came from:

| model L | entries | values |
|---|---|---|
| emitted as loops | 2,908 | 118,880 |
| unrolled, one body per tuple | **30** | **82,124** |

Thirty blocks, 41% of the model's algebraic values, and much more than 41% of
its lines. Its tangent came to 587,780 lines and 374,915 hoisted slots against
ceilings of 300,000 and 250,000, so a 16,244-state model was refused an
analytic Jacobian and differenced a **dense** matrix instead -- the pattern is
built by the same generator, so losing the tangent loses the sparsity with it.

Those thirty are not arbitrary. `Biosphere_models.Biosphere.C_do_soil_objects`
holds 686 values and fourteen distinct equations -- one per landscape object,
each naming `Object_01`, `Object_02` and so on -- repeated for all 49
radionuclides. The equation varies along one dimension and is identical along
the other. Across the thirty: 82,124 values, **321 distinct equations**.

So `emitByEquation` finds the dimensions an equation does *not* vary along,
loops those, and unrolls only the rest. `C_do_soil_objects` becomes fourteen
bodies each looping 49 nuclides instead of 686 bodies.

What makes this cheap is that the offset machinery already does the work.
`space.projection` reports each component of a reference as either fixed or
carried from a source dimension, and the locator multiplies whatever it is
handed by a stride -- so a *pinned* dimension is a loop variable whose name
happens to be a number, and `MAPS[k][3]` and `3 * 49` are as valid as
`MAPS[k][n0]` and `n0 * 49`. Nothing in `makeLocator`, `stateOffsetExpr` or
`farfInletExpr` changed. The loop variables are indexed **by position in the
entry's own dimensions**, which is what `projection` reports and what the
locator indexes with; keying them by name instead was the one real mistake
while writing this, and it compiled.

| model L | before | after | ceiling |
|---|---|---|---|
| tangent lines | 587,780 | **170,462** | 300,000 |
| hoisted slots | 374,915 | **111,777** | 250,000 |

It now has an analytic Jacobian: 77,812 non-zeros of 263,867,536, 54 colours,
formed in 54 tangent sweeps where the dense difference would have taken 16,244
columns. Five hundred years of it solve in 4m34 over 1,851 steps.

Across the assessment models of one series, which all had an analytic Jacobian already,
the same change is worth between nothing and a great deal -- it depends
entirely on whether a block's equations vary along one of its dimensions or
along all of them:

| unrolled bodies | before | after |
|---|---|---|
| model A | 1,341 | 1,341 |
| model E | 5,944 | 2,324 |
| model F | 13,770 | 5,488 |
| model C | 35,201 | **2,228** |

model A gains nothing: its five non-uniform blocks vary along every dimension they
have, so there is nothing to loop and it is unrolled exactly as before. model C's
generated code is a sixteenth of the size. What that buys, for a model that
already had its Jacobian, is build time -- model C builds in 15.3 s where it took
18.8 s.

**The numbers do not move.** Both emitters were run against each other over
every bundled example and three of the assessment models -- model A (90,290
series), model B (98,826) and model C (155,322) -- comparing every value at every
output time: the worst relative difference is zero, and the Jacobian
availability and colour count are identical. Building is slightly faster
(model C 18.8 s to 15.3 s), since there is less code to generate and compile.

One safeguard: looping a dimension resolves references through
`space.projection`, which is more particular than reading them off a known
tuple. If it cannot express one as a stride, the block is wound back and
unrolled exactly as before. Nothing in the corpus takes that path -- every
uniform block already goes through `projection` -- but the generated program
is the model, and a fallback is cheaper than a surprise.

**N.** The cell count is fixed before the run
when it is a literal or a reference to a non-probabilistic, non-scenario
parameter, and otherwise evaluates it as the run starts
(`noDiscretizationsForTransport`), which lets a Monte Carlo realisation have
its own N. This tool has no probabilistic runs, and lays the state vector out
before anything is evaluated, so N is settled before the build by a small
evaluator (`constantValue` in `src/domain/transport.js`) over numbers,
functions, parameters and expressions made of those -- read at the active
scenario where the scenario list is involved -- and refused otherwise, with a
message that says what N may use. Truncated towards zero as an integer cast
is; below one refused.

**Where this tool decides by rule what the generated code decides by order.**
Two places. A transfer drawn from outside into Begin, or out of End, reads
Begin and End as the first and last elements here; in the generated code
Begin's external transfers are assembled while the statics say (0, 1) and
End's while they say (last, last), so a rate out of End that mentions Begin
would read End itself. And an expression inside the transport that reads the
pair is, seen from outside, what it comes to for the first pair with the
counter at 1 -- which is the state the statics are left in after the loop, so
the two agree there. The counter itself is not readable from outside at all:
it is an ordinary entry block rather than an expression, and it answers a
question -- which pair is being assembled -- that has no answer outside the
chain. A read of it from outside used to come to that same 1; the equation
checker, the problem strip and the build now refuse it, the completion does
not offer it beyond the transport, and the left panel does not list it among
the expressions. A transfer drawn between Begin and End becomes the transfer
joining the first pair, under its own name; the copies for the other pairs are
hidden and carry an `alias` that `implicitIndices` in the builder reads, so
that for the `Transfers` list and the lists derived from it every copy *is*
the drawn transfer -- index resolution holds the drawn transfer's index for
every pair -- and `_source_`/`_target_` in its rate are Begin and End
throughout, as `currentSourceCompartmentIndex` is. A slice in the middle of
the chain answers for the `Compartments` list as Begin, whose initial
condition it took; and the hidden slices and copies are left out of the two
derived lists, which in Ecolego hold Begin and End and nothing between.
Neither reading is something a model can sensibly rely on, and both are
documented in the README.

There is a faster path, chosen when the counter is unused and the decay is
simplified) generates the same arithmetic with local variables and a running
`above` term; the numbers are the same, so this tool follows the classic
writer and has no second path.

**Editing.** The sub-system is a path in `transports`; the parts carry
`transport: 'begin' | 'end' | 'number' | 'counter' | 'operation'` on the
compartment or expression they are, since `TransportBegin extends Compartment`
and `TransportNumber extends Expression`, and everything that treats a
compartment as a compartment goes on doing so. The rule for what may be moved where refuses to move a part out or a sub-system in:

```
a Begin, an End, an N or a counter      -> may not be moved out
a sub-system into a transport            -> may not be moved in
```

The editor refuses the same moves, and an operation's as well -- a sum over
*this* chain means nothing beside another -- and refuses to delete Begin, End
or N on their own, since deleting one leaves a transport with no chain. **A
transport is not dissolved either.** Dissolving one would make its parts
ordinary blocks -- a compartment with a misleading name, an expression that says
1, and an operation that comes to nothing -- a model that builds and means
something other than it did, with no line saying so. A transport is deleted
whole or kept whole, which is the reading `isValidMove`
already implies for its parts.

`TransportSubSystem extends SubSystemBlock`, a block that is a sub-system, and
this tool draws it as one: its own icon and colour in the tree and on the
diagram, its own menu, and a connect handle. A line dropped on the node feeds
its Begin and a line dragged from its handle leaves from its End
(`transportEndpoint`, which `addTransfer`, `addSource` and `setConnectionEnd`
all ask); Ecolego has no such gesture, since it draws the sub-system as a box
you open and connect inside. Where this tool goes further is the chain's dimensions. Setting Begin's dimensions gives End and the operations Begin's
lists and stops there:

```
setting Begin's index lists also sets End's,
and every operation's in the same sub-system -- and stops there
```

-- and the modeller keeps Begin in step with what feeds it by hand. Here a
transport takes its dimensions from what it is connected to, as a transfer
does from its two ends (`transportDims`, run by `syncTransferDimensions` before
the fluxes): paired by root across every outside end, narrowed to a sub-set
where one end is one, and dropped where an end has no dimension of that root
-- which is where the chain's rule parts from `sharedDims`, since a chain is
not a flux and the fluxes to it say what they sum over. A chain between a
compartment per nuclide and object and one per nuclide is a chain per nuclide,
and the inflow is then the flux that sums, refused until it says so. One end
connected takes that end whole; none keeps what it was given; a narrowing
Begin states is kept, on the rule a flux's is. The equation checker accepts a
call to an operation with an argument, as it accepts a call to a lookup table
with one, and refuses a bare reference to it with the call to write instead.

**Verified** against closed forms and against chains drawn by hand, not
against a file: none of the 87 real projects here has a transport. A chain of
four with rate k, started in its first element, matches the Erlang
distribution `(kt)^(j-1) e^{-kt} / (j-1)!` element by element to 1e-9; a
column of three with the counter in its rate, a flow back up, an inflow, an
outflow and a pair-reading expression matches the same column drawn as three
compartments and five transfers to 1e-9 at every end, and so do the point and
stretch operations on it and a chain with decay and ingrowth per element; N =
1 matches one compartment. The three chain functions are checked against the
arithmetic on a fixed vector, partial cells and reversed ends included.
The `.eco` reader is checked on a hand-written `type="transport"` sub-system
with all five block types, which imports, builds and conserves mass.

## Deleting a large sub-system

`referencesTo` answers "what still reads this block" by tokenising every
equation in the model, which is the only honest way to do it: whether a bare
`Water` means this sub-system's or the top level's depends on what exists. That
is fine for one name and quadratic for a selection. `deleteBlocks` asked it
once per block going, so deleting `Biosphere_models` out of model L —
2,147 blocks of 3,789 — tokenised the whole model 2,147 times and took **29
seconds**.

None of that work depends on which name is being asked about, so it is done
once. `referencesToAny` walks the model a single time, tokenises each equation
once, resolves each identifier once and files the answer under whichever of the
wanted names it landed on. The same delete now takes **0.5 s**, and the
remainder is the splice itself rather than the search.

Checked rather than assumed: for every one of the 3,789 blocks in that model
the batched walk returns exactly what the one-at-a-time walk returned, in the
same order — 12,376 references, none different — and the same on a second
project.

## What an initial condition may read

A project file puts no restriction on it: an initial condition is compiled by
the ordinary equation compiler, the same one every other equation goes
through. This tool accepted parameters and numbers and nothing else, which is
narrower than the model: an initial inventory is very often *derived* — a
concentration times a volume, an inventory per square metre times an area —
and writing that as one expression and reading it in the compartment is the
natural way to say it.

The limit that is actually there is that the initial state is worked out before
any compartment has a value, so an initial condition can only read what does
not depend on the state. That is now the rule, and it is computed rather than
assumed. `timeInvariantAlgebraic` walks the algebraic blocks — already in
dependency order, so one forward pass settles it — and admits an expression, an
index operation or an aggregate when everything it reads is invariant too and
it does not read the clock. A compartment, a lookup table, a far-field release
and the four blocks that remember are never invariant, and neither is anything
built on them.

Two details worth keeping:

- **`time` is a call, not an identifier.** It parses as `{type: 'call', name:
  'time', args: []}` and `collectReferences` does not report it, so the check
  for it is a separate walk — and one over plain values rather than by node
  type, since `time` can appear anywhere an expression can, an index included.
  A walk that knew the shapes would have to be right about all of them; missing
  one would call something invariant that is not, which is a wrong initial
  inventory and no error at all. `start_time` and `end_time` are constants of
  the run and are left alone.
- **The state is kept out one step back.** `invariant` only ever holds
  algebraic blocks, so a compartment can never be in it — but the states have
  to be in the resolver all the same, or a bare `Pool` would resolve to nothing
  and be read as "a parameter, which is a number".

Only the blocks an initial condition actually reads are evaluated, and they are
emitted ahead of it in the order the algebraic pass settled. A model whose
initial conditions read only parameters generates exactly the code it generated
before.

Measured on the corpus: one vault model moves from BUILDFAIL to running. Its
`Waste_forms.uniform_dissoultion` starts at `Total_Inventory * Leaching_Fraction`,
and `Leaching_Fraction` is an expression.

## The explicit dy/dt term

a compartment entry carries one more equation than the initial condition: a
term added to the differential equation that is not defined through transfers
or radionuclide decay.

It is the `dy/dt` column of the compartment grid (the compartment settings:
IC, DIFF_EQ, NON_NEGATIVE, ABS_TOL), the `<differential-equation>` element of
an entry in `model.xml`, and this tool's `dydt` -- block-level default and
per-entry override, like everything else a compartment entry holds. Three
things decide how it is read: **Where it goes.** The standard assembly builds
the compartment's equation by putting the term's tokens first and appending
the fluxes after it -- `+ transfer` for each inflow, `- transfer` for each
outflow, each multiplied by the donor where `multiplyByDonor` says so -- and
the class and that is combined with the decay term. So the term is additive
and unconditional: `dC/dt = dydt + in - out - λC`. The tool compiles it as one
more algebraic slot per compartment that has one -- `C#dydt`, hidden, of the
compartment's own dimensions, exactly as a source's rate is compiled -- and
the derivative assembly adds `X[slot]` into the compartment's row. A term set
for one index alone reads as `0` at the others, because `valueAt` falls back
to a block-level value that is not there.

**What it may read.** Nothing is forbidden: the compartment rule runs the
ordinary the equation rule over it and no more, and unlike the initial
condition it is evaluated with the state, so it may read compartments, the
clock and everything built on them -- including its own compartment, which is
the point of `Ecosystem*a - Ecosystem*b*Ecosystem[Fox]`. This tool's equation
checker refuses a block that names itself everywhere else (`E = E + 1` is a
one-step cycle); `SELF_READING_FIELDS` in edit.js exempts this one field, and
the builder's own cycle test is unaffected because the reference resolves to a
state, not to the slot.

**Its unit.** The unit rule special-cases it:

> The unit for the differential equation property of the compartment do not
> have the same unit as the compartment, (it has the unit of a transfer)

and builds `targetUnit + "/" + timeUnit`. `UNIT_TARGET` gained a fourth rule,
`rate`, which is the block's own unit over the simulation's time unit, and the
start-value panel labels the term the same way.

**In a transport.** The faster path has three fetchers:
the internal equation builds every slice's row from
`getDifferentialEquation(begin, indices)`, the external-end equation builds
End's row from End's own, and with one slice
the single-compartment equation generates from Begin alone.
The unrolling does the same: Begin's term is copied to each slice, rewritten
for the pair as the internal transfers are (`Begin` in it is the slice, `End`
the next), End keeps its own, and with N = 1 End's is not read.

The Jacobian generator treats the slot as it treats a source: its dependency
set lands in the compartment's row, its tangent in the same row, and a term
that follows the state or the clock makes the matrix non-constant.

Measured: 242 real `.eco` files on this machine carry 3 non-empty
`<differential-equation>` elements in 2 of them -- the two halves of a
predator-prey pair in one indexed compartment, and one
carbon balance (`Burial_C*area_RegoUp-RegoPeat_SOC*minRate_RegoPeat`). Every
other entry in those files has the element empty or absent. It is read rather
than dropped with a warning, which is what makes the Lotka-Volterra file run.

## User-defined functions

Ecolego has two of these, and they are not the same thing.

**The one in the file format.** `UserDefinedFunction` is metadata -- a name, a
source type, a file name -- pointing at a source file in the archive:

```
a class with one method, `double function(double... params)`,
compiled from a source file in the archive when a run starts
```

The generated code instantiates one per function and compiles every call site to
`Model._function1.function(a, b)`. That cannot come across -- the browser has
no way to run it, and a tool that ran code out of a project file would be a security
hole rather than a feature. It is read for its *signature*: the block arrives
with its name and its parameters (`<parameter-metadata>` under
`<function-metadata>`), an empty body, and a line in the import report. All
`<function-model>` elements in the 291 files here are empty, so nothing in the
corpus exercises it.

**The one real models use.** An `Expression` implements an argumented expression:

> Interface for objects that can receive arguments, like functions

and carries `<argument>` elements naming values its equation may use beside
everything it can already see. It compiles to a method of `n` index dimensions
and `d` arguments (`writeMethodOpen(methodName, n, d)`), and a call passes the
caller's indices along with the arguments. one small test model has

```
ADV(position, kd) = interpolationUseEndValues(
    DegradedFcn, position, Q1, position + z_barrier/N, Q2) * kd
```

called from four transfer rates as `ADV(index[_source_]/N, Kd)`.

This tool has one block type for both, `functions`, and the importer reads an
argumented expression into it. Four decisions:

- **A call is inlined** where it is written, rather than emitted as a JS
  function. That is what keeps the rest of this tool unchanged: the dependency
  order, the index machinery, the unit check and the analytic Jacobian all see
  ordinary arithmetic, because by the time they look, that is what it is. A
  tangent rule for a call would otherwise have been real work.
- **The body reads the model**, since Ecolego's is an expression and its body
  does: `TR_adv` reads `C_adv`, `vel_wind_height_ref_ter` and `area_obj_ter`.
  A version that could not would make every caller pass those in.
- **A name in the body is resolved where the body was written.** The inliner
  stamps every non-parameter reference with the function's own sub-system and
  `makeLocator` reads the stamp, so `Water` in a body written at the top level
  does not become `NF.Water` when it is called from inside `NF`. This is the
  one place in this tool where an AST node carries scope.
- **A parameter may shadow a block** -- `ADV(position, kd)` is exactly that,
  in a model full of Kd values -- so every walk over equations asks
  `functionLocals` and leaves the parameters alone. Without it, renaming `kd`
  would rewrite the parameter and the diagram would draw an influence nobody
  wrote.

**What it is not.** A function is not indexed: Ecolego declares a dimension on
these expressions (`RegoLow_eq` says Radionuclides) but the generated method
takes the *caller's* indices, so the declaration says only what the values it
reads are per. Inlining gives the same answer and there is nothing to declare.
Nor is it disable-able: it has no value to leave out of a run.

Measured: four models in the corpus carry argumented expressions -- `ADV`,
`TR_adv` and `TR_turb`, `RegoLow_eq` -- and all four failed to build before
this, stopping at `Unknown function` with no way forward. They now build and
run. The count of files that import and build goes from 114 to 120 of 291.

## Blocks that remember

Five block types are not functions of the state vector. Everything else in this
tool is recomputed from `(t, y)` whenever it is wanted — which is what lets the
runner solve first and fill in the algebraic blocks afterwards — and none of
these can be:

| Block | What it is | Where it comes from |
|---|---|---|
| min/max | the extreme its target has taken |
| running mean | the mean of its target over the recorded time | `RunningMean`, and it `implements IStateBlock` |
| snapshot | its target when an event last fired |
| delay | its target as it was a given time ago | `Delay`, the scalar recorder |
| discrete event | the instant one expression crosses another | `DiscreteEvent`, the event locator |

Each keeps a history as the solver accepts steps and reads it back afterwards
(`src/sim/history.js`), which is the usual arrangement:
`acceptedFcn` calls each block's `store`, and each block's `calculate` reads
the hold-below rule over what it stored whenever it is asked about a time at
or before the last step. So the two-phase runner needed no change of shape,
only somewhere to put the memory.

Four things had to be got right, and each is a decision the format makes
explicitly rather than something to invent:

- **A min/max stores its own value, not its target.** `writeMinMaxStoreMethod`
  records `getName()(indices)` — the extreme so far — so the history reads back
  as the block's own past. A delay is the exception, and stores what it is
  watching, because its target's past is the whole point of it.
- **A running mean is a state.** `dS/dt = target`, seeded at zero, and the
  block's value is `S` over the time it covers. Its integral goes in the state
  vector after the compartments, does not decay however it is indexed, and is
  not clamped non-negative — the mean of something negative is negative.
- **Events are terminal.** Every one of them fills the array
  with `true`, so the solver stops at the crossing, `performEvents` runs, and
  the integration starts again. This tool does the same by running the solve in
  segments: each stops at the first crossing it locates and the next begins
  from the event. Restarting is not a cost worth avoiding — an event is a
  discontinuity, and a solver carrying its step size and difference table
  through one would be extrapolating a model that has changed.
- **`first - second`, with a direction.** The generated code assembles
  the event function from the two expressions and `getValue(Direction)` maps
  the file's LEFT/RIGHT/BOTH onto -1/+1/0. So a `RIGHT` event on
  `0 - V` fires when the volume falls to nothing, which is what model L
  model's "lake disappearing" event says.

**Event location** is the bracketing search in `src/ode/core/events.js`. All three
solvers share it: a safeguarded regula falsi over the solver's own dense
output, returning the first crossing, which is all a terminal event needs. One
guard matters -- a component exactly on zero where a segment starts is the
event that stopped the previous segment, not a new crossing. Without it an
event sitting on zero at the instant a segment restarts fires again, and
again, for ever.

Two deliberate departures, both places where following the format exactly would
be wrong here:

- **A stopped running mean stops dividing by a growing time.** The usual
  `t = totalTime + time - lastTime` keeps growing after the recording stops and
  relies on `!Model._solving` to read the history instead once the run is over.
  This tool has no equivalent of that flag at the point the value is computed --
  the algebraic pass runs the same code during and after the solve -- so the
  elapsed time is frozen while stopped instead. During a solve the two agree to
  within a step; afterwards the usual one reports a mean stopped at year 8 and
  read at year 9 as half as large again.
- **A delay's history is seeded at the start time.** The usual code clears it in
  `init` and adds nothing until the first accepted step, and a recorder read
  on an empty recorder reads `values[0]` of an untouched array — zero. The
  commented-out code beside it shows the intent was to seed it with the target's
  initial condition, which is what this does.

**All five differentiate exactly**, so a model using them keeps its analytic
Jacobian rather than falling back to differences: a min/max is `max(so far,
target)`, whose derivative is the target's wherever one exists; a running mean's
is its integral's over the same elapsed time; a snapshot and a delay report the
past, which no present state can move; a discrete event is an ordinary
difference of two expressions. What does change is that the Jacobian is no
longer treated as constant whenever a model has one -- a mean divides by a time
that grows -- so the iteration matrix is refreshed rather than factorised once.

**Verified** against closed forms rather than against a previous run: over
`0..10` the mean of `time` is 5, the largest `time*(10-time)` is 25, `time`
delayed by 2 is `t - 2`, and an event on `time = 5` puts the snapshot at
exactly 5 — checked on all three solvers, together with resets and
start/stop events (a mean recorded from year 5 to year 8 is 6.5), the
`useInputBelow` and a recorder read readers on their own, event
location on a known root, and the analytic Jacobian of a running mean against
finite differences.

In the corpus the two models of the L series carry all five — 14 min/max blocks, 14
discrete events, 4 running means, 4 snapshots and a delay — and import whole.
They also carried the `model-input` and `model-output` blocks that were the
last thing stopping them; those are connected directly now (see *Sub-system
inputs and outputs*), and all three model L files build: 16,244 states, no
problems, 27 unit warnings. The analytic Jacobian declines on them — more than
300,000 lines of tangent code — so they run on finite differences.

## Laying the diagram out

Ecolego keeps node positions in `views.xml`, which this tool does not read —
presentation state is one of the things the importer leaves behind. So an
imported model arrives with no geometry at all, and what its diagram looks like
is entirely the automatic layout's doing. That makes it worth more than a
heuristic.

Two graphs decide where a block goes, and deliberately not the same one:

- **Transfers** rank the compartments into columns, left to right: a layered
  (Sugiyama) layout in `src/domain/layout.js` — break cycles by depth-first
  search, rank by longest path, order inside each column by the weighted-median
  heuristic with a transposition pass, then place the rows by pulling each node
  towards the middle of what it joins.
- **Influences** — `edit.influences`, the same fact about the model that draws
  the dotted arrows — hang everything else underneath, each block under
  whatever reads it. A rate parameter lands under the *middle of the transfer*
  it drives, because that is where the diagram draws the end of its arrow, and
  most parameters in a real model feed a rate rather than a block.

Keeping the two apart is what makes the result stable: expressions, parameters,
lookup tables and reductions can each be hidden, and hiding them must not move
the compartments.

Three things the textbook version leaves out and a real model needs:

- **Models come apart.** Each connected flow is laid out on its own and the
  pieces packed into rows, so a model whose top level is a dozen unconnected
  sub-systems reads as a grid rather than one tall column.
- **Blocks that want the same place stack, rather than spreading.** Forty
  parameters feeding one transfer, laid along a row, would be ten thousand units
  across with each one further from its reader than the last; they queue in
  lanes underneath it instead. Blocks whose wanted positions collide form a
  group, and a group gets the run of space up to where the next group starts —
  so evenly spread blocks still land exactly where they want, and a hundred
  blocks wanting one place share the width between them.
- **A budget for placeholder nodes.** Splitting an edge that skips a column into
  a chain through invisible nodes is what stops the ordering from routing a line
  through a box. But the root of a landscape model is 150 sub-systems joined by
  hundreds of transfers, and splitting every long edge made thousands of them:
  the layout took 28 seconds and stood 72,000 units tall. Past the budget the
  long edges are left whole, which costs a diagram that size nothing — it is
  read by drilling into a sub-system anyway. Counting crossings by Barth, Jünger
  and Mutzel's accumulator tree, and deciding a transposition from the two
  nodes' own edges rather than by recounting the column, brought the same model
  to 280 ms.

**Measured over 78 imported models**, against the layout this replaced — a
longest-path rank, each rank centred, and everything that is not a compartment
in a row at the bottom by kind:

| | before | after | median per model |
|---|---|---|---|
| crossings, as the diagram is drawn by default | 10,225 | 3,119 | **0.09×** |
| line length, the same view | 3.4M | 2.6M | 0.80× |
| line length, every block and influence shown | 6,655M | 159M | **0.23×** |
| boxes overlapping another box | 59 | **0** | — |
| width ÷ height, median (the pane is 1.78) | 26.75 | 1.02 | — |

Two of the 78 get worse in the default view, by four crossings each; 75 of 78
shorten their lines. With every influence shown the total crossings rise 8%
while the median falls to 0.82× — the sum is carried by three landscape models
of several thousand blocks, where a dependency graph that dense crosses itself
whatever you do. Transfers that end up pointing right to left are unchanged
either way (2373 against 2415), which is the cycle-breaking choosing a
direction rather than either layout being better at it.

Two measurement traps, both of which made the first numbers a lie and are now
handled in the harness:

- **Parallel connections are drawn as one bundled path**, so counting each
  transfer as its own line counts lines nobody sees. One pair of sub-systems in
  model L is joined by forty transfers.
- **Collinear lines never "cross".** The old layout put every sub-system node in
  a single row, so 543 connections between them scored a perfect zero while
  being completely unreadable.

### Lining a selection up by hand

Align and distribute are here because an imported model arrives with no geometry, so every
diagram in this tool is either the automatic layout's or arranged by hand, and
arranging by hand without it means nudging boxes until they are nearly level.

The geometry is in `layout.js` beside the automatic layout, for the same reason
the rest of that module is: boxes in, positions out, no project object, so it
can be tested on its own. `edit.js` has the two that know what a project is —
`alignBlocks` and `alignShapes`.

Three decisions worth writing down:

- **The lines are drawn through the selection**, not through a page. PowerPoint
  offers both; there is no page here, since the canvas is unbounded.
- **Distributing equalises the gaps, not the centres.** The two agree when the
  boxes are one size, which is the ordinary case, and part company as soon as a
  compartment has been widened — and then it is the space between boxes that the
  eye reads as even. The span is preserved exactly: what is divided is what is
  left of it once the boxes themselves are taken out, which can be negative, and
  boxes that cannot fit are spread to overlap evenly rather than refusing to
  move.
- **Only what the diagram draws.** A selection can hold more than the canvas
  shows — a connection, which is a line between two boxes rather than a box; a
  block picked in the tree that lives in another sub-system; one of a kind the
  view is hiding. The diagram narrows the selection to its own nodes before
  asking, and `alignBlocks` refuses anything that is not drawn as a node rather
  than inventing a box at the origin for it.

A shape is *moved* to its new box rather than placed there, because a line or
an arrow is drawn corner to corner: its width and height carry its direction
and either may be negative, and setting `x` directly would have turned an arrow
round. Nothing moved means nothing recorded — the diagram says so instead, so
an Align on an already-level row does not leave an undo step that changes
nothing.

## Mass-balance audit

A compartment model can lose mass in a dozen quiet ways, and a curve that looks
plausible says nothing about whether it did. The audit
(`simulation.mass_balance: true`, off by default) answers it with *budget
states*: `src/sim/builder.js` appends, after the far-field
paths, one state per family per kind of movement — `in`, `out`, `decay`,
`ingrowth`, `explicit`, `between`, in that order, a family being a position in
the material list plus one for compartments not indexed by nuclide — and at
every emission site adds the same term it adds to the compartment to the
matching budget: a transfer with no `to` (or into a far-field pathway) to `out`,
one with no `from` to `in`, a source to `in`, the decay loss to `decay`, each
ingrowth term to `ingrowth`, an explicit dy/dt slot to `explicit`, and a
transfer whose endpoints are in different families (a per-nuclide compartment
draining into one that is not indexed) to `between` on both sides. A loop over
a sub-set of the material list reaches its family through a table (`BMAP<j>`)
spliced in after `out.fill(0)` once every emission has said which lists it
needs. Budgets start at zero, are hidden, answer to no name, and get the
fallback tolerance.

The closure is checked in `src/domain/massbalance.js` (`audit`), which is pure:
for each family and each output time, `Σ inventory(t) − Σ inventory(0)` against
`in − out − decay + ingrowth + explicit + between`, the residual judged against
the largest amount the family ever held or moved. Because every solver here is
linear in the state, the numerical solution of the sum *is* the sum of the
numerical solutions — exactly, for the solvers without a Newton iteration
(2×10⁻¹⁶ relative under dp45, 3×10⁻¹⁴ under ros23, whose Rosenbrock stages
are linear solves), and to the tolerance the Newton iteration stops at for
ndf (10⁻⁷ at rtol 10⁻⁶; 10⁻¹¹ when the tolerances happen to land well) — unless something outside the equations moved mass: the
non-negative projection, above all, which is precisely what the audit is for,
and which shows as a residual of order one (0.98 relative on a compartment
drained by an absolute flux while held at zero — the mass the projection
created). `closed` is therefore judged against `20 × rtol`, not round-off. It is not a conservation law and is not presented as one:
in becquerels the total is not conserved, and the check is of the bookkeeping,
not of physics.

Two prices, both on purpose and said in the switch's (i): the vector grows by
`6 × (nuclides + 1)` states, and the budgets take part in the step-size
control, so the trajectory is the plain run's to within the tolerance rather
than to the bit (1.3 × 10⁻⁸ relative on the test model under dp45). An audit
run is a check, not a way to run.

It used to have a third: `buildJacobian` declined, since the budget rows were
not in the pattern. On a model of 9,392 states that was no price but a refusal.
With no pattern, the solver needed the iteration matrix dense (0.7 GB) and
would not start. It keeps the Jacobian now, and how much of the budgets it
carries depends on the solver (`DIAGONAL_BUDGET_IDS` in
`src/sim/jacobian.js`; `jacobian.budgetRows` says which).

- **`'diagonal'`**: ndf, dp45 and the SciPy methods. Nothing reads a budget,
  so a budget's column is empty and the rest of the matrix is exact without its
  row. A Newton iteration with the row left at the diagonal still converges to
  the same solution, because the budgets are set from the state each iteration
  and settle one behind it. The diagonal has to be the exact zero it is,
  though, including when the matrix is differenced (on request, or at a point
  where the generated one is not finite). A budget column shares no row with
  anything, so the colouring would put it in any group. Differenced there, its
  diagonal reads the fluxes of the states beside it, and a Newton iteration
  with that on the diagonal settles slowly or not at all. So `budgetsApart`
  takes the budgets into one group of their own, which differences to exactly
  zero, and `evaluate` skips it.
- **`'exact'`**: everything else. A Rosenbrock puts J into the formula, so a
  missing row is a lower-order budget. The ported methods colour the pattern
  themselves when they difference, and their colouring cannot be told to keep
  the budgets apart. `patternSource` and `jvpSourceFor` then emit the budget
  rows (`budgetRowsOfTransfer`, and the in/explicit/waste/event/decay/ingrowth
  sites), each row reaching every state of its family, so the colouring widens
  to about the largest family.

`checkJacobian` skips `'diagonal'` budget rows, where differences see entries the
pattern leaves out on purpose.

Turning the audit on also exposed a bug in the ported package's
`reverseCuthillMcKee` (`src/ode/julia/core/linalg.js`, the same bytes as
`resources/js/ode/julia/`). It started each component at the least degree from
the scan position and moved on by one whether or not the component reached
that position, so two isolated vertices after a connected block were enough for
it to return zeros in place of the vertices it had walked past. The sparse LU
through that order reported the matrix singular, and every ported method
stalled at t = 0. It now orders what the loop left. Where the loop left nothing,
which is every case it got right, the order is bit-identical (4,000 random
patterns: 3,065 unchanged, 935 formerly broken). `mass_balance` is in the fingerprint's solve settings, since a run
without it is not a run with it.

A family is judged against the largest amount it held or moved, and one that
never exceeds the largest absolute tolerance among its states is not judged at
all (`unresolved`, reported as such). It used to be idle only at exactly zero,
and round-off from the rest of the model -- 1e-28, leaked into an empty
family's budget under a differenced Jacobian -- was then a residual as large
as the family: kencarp4 reported an audit that did not close on a model that
did. The result travels as `payload.massBalance`
from `Results.massBalance()`, is a status-line item (`mass balance: closes
(9e-11)` / `open by 3.2e-4`, with every family in the tooltip) and is written
into the run log, so it goes into a results archive with the rest.

## Version report

What changed between two models is a question a reviewer asks constantly and a
diff of two JSON files answers badly: the order of the keys, the tidying an
open does, and the layout coordinates all show up as differences that are not
changes. So `src/domain/versions.js` compares the models rather than the text: `compareModels(before, after)`
and `reportLines(diff, labels)`, with the two models being the one open and
either the file as opened — one JSON string kept by `setModel`, taken *after*
the tidying opening does (`migrateKeys`, `materialiseShorthand`,
`syncDerivedUnits`, `autoLayout`) so that the tidying is not a difference — or
another file read through `readModelFile` and given the same tidying.

Blocks are matched by qualified name within each of `COLLECTIONS`; fields by
key, on a canonical (key-sorted) JSON of each value, with the layout keys
(`x y w h shape colour collapsed label`) left out and `comment` kept in. Indexed
`entries` are matched by `index`/`indices` rather than position. A block
removed under one name and added under another whose body (everything but name
and layout) is byte-identical is reported as a rename — a deliberate reading:
two blocks that merely look alike will be paired too, and the report says
"(renamed)" so the reader can disagree. Index lists compare by member name and
per-member fields, nuclides by name and fields, `simulation` key by key, and any
other top-level key whole. The text puts a `+ - ↔ ~` in front of each line and
cuts long values to 72 characters in the text only; the structured result keeps
them whole.

## Unit checking

the unit rule works an equation out in units and compares it
with the unit the block declares. The rules are read off that method and
`resolveUnit` beside it, not invented:

* `*` and `/` combine the units; `+` and `-` require them to agree, **except
  that a dimensionless side is absorbed** — which is why `1 - k*t` is not
  reported, and why the sum then takes the unit of the side that has one.
* `^` needs a constant exponent. Ecolego raises the base to it through
  `pow(n).root(d)`; this tool refuses a power it cannot name rather than
  reporting the model wrong for something it cannot follow.
* A comparison is dimensionless whatever it compares — though the two sides
  still have to be comparable.
* `min`, `max` and `if` require their arguments to agree, with the same
  absorption; `sqrt` halves the exponents; `time` is the simulation's time unit.
* Two targets are not the block's own unit: a compartment's **derivative** is
  checked against `<compartment>/<time>` — in this tool that is the transfer,
  whose unit is derived already — and a **delay time** against the time unit.

Three differences, all deliberate. Ecolego makes it opt-in per block
(`isUnitChecking`, off by default) with a severity preference; here it is
always on, because the checker is silent unless it is sure — no unit, an
unknown in the equation, or a power it cannot follow all produce no verdict
rather than a guess. It never converts between units, since nothing in this
tool applies a conversion factor. And it is never an error: units reach the
chart, the table and the CSV and nothing else, so a mismatch cannot make a run
wrong, only mislabelled.

The unit reader takes what the files actually contain — of 138 distinct
spellings across 12,205 blocks it reads all but one (`m^(1/3)*s`), including
`year^-1`, `m year^-1` and `m year-1`, `kg/(m^2*year)`, `Sv/year per Bq/m3`,
`m2` for `m^2`, `Sv/y` for `Sv/year`, and `[-]` for none. The result is 178
warnings, 1.5% of blocks.

**Unit literals and prefixes.** A number
may carry its unit in the equation — `0.01[m]` — which the parser turns into
`{type: 'num', value, unit}`; the compiler, the tangent generator and the
function evaluator read `value` and ignore `unit`, so the run is bit-identical
to the bare number. `equationUnit` reads `parseUnit(unit)` for the literal in
place of the dimensionless one, which is the whole feature: a length in an
equation stops being absorbed. The syntax reuses the index brackets, which the
tokenizer already hands over as one raw string, so `1e3[Bq/m3]` needs no new
token.

`Dim` gained a `scale`. An SI prefix (T G M k d c m u/µ n p; hecto, deca, peta
and exa left out since `h`, `da` and `Pa` are other units) on one of twelve base
symbols is read as that base at the prefix's factor, and `times`, `over` and
`pow` carry the factor along, so `cm3` is {m: 3} at 10⁻⁶. `equals` compares the
scale too — `kBq` ≠ `Bq`, as before — and `sameKind` / `factor` are the looser
question the warning uses to say "the same quantity, 1000 times smaller". No
conversion happens anywhere, which keeps the header's promise; the reader is
handed the factor instead. Two choices worth recording: the kilogram is the
canonical mass (`g` is {kg: 1} at 10⁻³) so that the unit every file writes
prints as itself, and the packed length form `m3`/`cm3` is recognised through
the same prefix reader rather than a list of length spellings. The base list is
deliberately short so that `mol`, `min`, `Gy`, `Pa`, `ha`, `Ma`, `kgC` stay
whole; the corpus sweep found no symbol that the split misreads.

**A literal is converted against its sibling** (`scaleLiterals` in
`unitcheck.js`): `p1 + 1000[mm]` compiles as `p1 + 1`. The rewrite runs
wherever the checker demands agreement -- `+`, `-`, the comparisons, and the
arguments of `min`/`max`/`if` -- and nowhere else, because nowhere else names
a unit to convert to.

**Why the sibling and not a canonical unit.** Scaling `5[cm]` to metres because
centimetres are not SI is the obvious rule and is *unsound*: in a model whose
lengths are in cm it evaluates as 0.05 where 5 was meant, and the checker
compares 0.01 m against 0.01 m, agrees, and reports nothing -- a silent factor
of 100 that the one mechanism meant to catch it cannot see. Scaling to whatever
the literal is written against is right whatever the model's units are, and is
the whole of the rule. Two *blocks* are never converted: a number typed into a
block is in that block's unit, and restating it is the modeller's to do.

**One rule, two readers.** `scaleLiterals` rewrites the AST in place -- the
literal's value is multiplied by `here.factor(want)` and the node gains a `dim`
that `equationUnit` honours in place of its written unit -- and both the
checker (`unitProblems`, before `equationUnit`) and the run (`parseEquation` in
`builder.js`, which every equation and initial condition goes through, so the
tangent generator compiles the converted tree too) call it. The checker is
therefore silent about exactly the equations the run converted, which is the
property that keeps the two from drifting; a test runs one model both ways and
checks the numbers and the silence together. It walks bottom-up, so an inner
sum settles its unit before an outer one reads it, and it asks `equationUnit`
for a sibling's dimension rather than writing the dimension walk out a second
time. `hasUnitLiteral` short-circuits the whole pass, so a model with no
literals -- every model in the corpus -- pays one AST walk per equation and
nothing else (an 11 ms build stays an 11 ms build).

Two cases stay reported, both where no single unit is in reach: a literal
buried in a product (`p1 + (2 * 1000[mm])`), and one written against a block
with no unit -- the second so that typing a unit on that block later cannot
quietly change what the equation computes. `clashNote` hands over the factor
for the first; `unconverted` carries the second.

## The far-field block

`FARFCOMP` is not a block type any of these file formats has. It is SKB's own
dual-porosity far-field model, and here it is a block in the model rather than
a script beside it.

**The formulation** is Appendix B of *SKB TR-19-06* (SE-SFL) for the
derivation, and Chapter 3 of *TR-90-01* for the form in travel time and Peclet
number. Where each part of it lives:

| | |
|---|---|
| the layer grid | `layerDepths` in `src/domain/farfield.js`, over `zeroin` |
| the fracture and matrix rates | `coefficients` |
| the transport matrix | `cellStructure` + `cellValues` |
| the release out of the path | `releaseCells` + `releaseWeights` |
| decay and ingrowth inside a cell | `buildDecayModel`, the model's own, in both unit conventions |
| the inlet | a flux delivered to the block lands in cell 0 |
| the derivative and its Jacobian | `FarfPath` in `src/sim/farfield.js` |

**What it may be indexed by** is the radionuclide list or nothing at all. That
is narrower than this tool's other blocks on purpose: one block is one migration
path, and the numbers that describe a path -- a travel time and a flow
resistance out of a hydrogeological model -- arrive per path. Indexed by
nothing it transports one quantity with no decay and no ingrowth.

**Which settings may differ per nuclide** is the four that are chemistry:
`Kd,f`, `Kd,m`, `De,m` and the matrix porosity -- the last because the porosity
a species can reach depends on the size of the species. The rest describe the
path and hold one value: the
water does not travel at one speed for caesium and another for iodine. They are
separate algebraic slots for that reason, one apiece rather than one per
nuclide, so the model cannot express the difference by accident.

**Where the release goes is a transfer**, drawn from the block to a
compartment, whose rate is the path's own name -- which *is* the release -- and
which multiplies by no donor, because the mass has already left the path. That
makes it an ordinary block: it appears on the diagram, in the transfer grid,
in the block tree and on the chart, and the engine needed no new case for it
(`stateByName` holds no paths, so the flux is added to the target and
subtracted from nothing). The editor holds its rate where it is and shows it
rather than offering it.

The one Jacobian nicety it needs is in `isConstant`: a release reads the state
and *still* has a constant derivative, since it is a fixed weighted sum of the
path's cells. Proved narrowly, by shape -- the rate has to be a bare reference
to the path -- because the wrong answer there is a solver reusing a stale
matrix.

**The state layout** is nuclide-innermost:

```
base + other*(cells*nuclides) + cell*nuclides + m
```

so the decay chain — which couples nuclides inside one cell and nothing else —
is a stride-1 walk, and the transport, which couples cells within one nuclide,
strides by the nuclide count. Cell `k*(N_M+1)` is fracture cell k and the N_M
behind it are its matrix layers, so an inventory can be read cell by cell.

**Why it is a runtime object rather than generated code**, which is how every
other block in this tool works: a 20 × 20 path has 420 cells per nuclide and
about 1,250 non-zero rates, so a ten-nuclide model would emit 12,500 lines for
one block and the same again for the Jacobian's pattern and its tangent. The
structure is identical for every nuclide and every index of the block, so it is
built once as index arrays and walked in a flat loop. The generated derivative
holds one line per path: `FARF[0].apply(y, out, X, DEC[0])`.

**Time-dependent settings come for free.** Every setting is an ordinary
equation in an algebraic slot, so it can follow the clock, a lookup table or a
compartment, and the rates are recomputed when — and only when — their inputs
move. Nothing is precomputed on a time grid and interpolated between. That
also means df/dy has to carry the *rates'* own tangents when a setting depends
on the state, which is `coefficientsTangent` and, because the layer
thicknesses come out of two root-finds, `layerDepthsTangent` by the implicit
function theorem.

### Two places where care is needed

Both are cases where the obvious reading of the published formulation gives a
wrong answer. Everything else is its arithmetic, and the tests hold published
numbers to prove it.

**The release with extra outflow cells.** With `n_b > 0` the flux out of the
last fracture cell is written in some presentations as
`(adv_f − d_f)·I[N_F] − d_f·I[N_F+1]`. The flux the matrix itself implies is
advection forward plus dispersion both ways, so the sign on the dispersive
self-term has to be positive: `(adv_f + d_f)·I[N_F] − d_f·I[N_F+1]`. Measured —
a unit release through five cells at Pe 8, integrated to a steady state with
the inventory upstream of the face gone to zero — the first form comes to 0.750
and this one to 1.000, and the deficit is exactly `2·d_f/adv_f`. Every other
case (no extra cells, any outflow condition) conserves mass to 1e-6.

**The ratio of the layer thicknesses.** The geometric ratio between successive
matrix layers is found by a root search, and bracketing that search in `[1, 100]`
is not enough: a ratio above 100 is ordinary when there are few layers — two
layers starting at a millimetre reach 10 m at a ratio of 9,999. Bracketed at
100 and asked for that, a search returns a grid whose layers add up to 0.101 m
— a rock matrix a hundred times shallower than the one it was given, with no
complaint. Here the upper bound is found rather than assumed, by doubling until
the series overshoots. Two guards go with it: a first layer thicker than
`PENDEP/N_M` cannot add up to the depth at all, and one matrix layer has no
layer to diffuse into. Both are refused with a message rather than integrated.

### How it was verified

Against an independent implementation of the same formulation, and against the
properties the model has to have.

- **The transport matrix, entry for entry.** Ten cases as (row, column, value)
  triplets — one nuclide and three, both decay conventions, all four outflow
  conditions, extra cells, a 20-layer path of 252 states — against the same
  matrix assembled here from `cellStructure`, `cellValues` and this tool's own
  decay model. Worst disagreement **7e-16**, which is summation order. They are
  in `test/farfield-fixture.js` and checked on every run.
- **Complete release curves.** Five cases at a relative tolerance of 1e-9, with
  a constant unit input into every nuclide, read at 41 times over five or six
  decades: a single nuclide, a sorbing one on the automatic layer grid, a
  three-member chain, and outflow conditions 0 and 3. This tool agrees to
  **1.4e-8**, which is two solvers agreeing rather than two models differing.
- **Mass balance.** A stable nuclide and a unit input: everything that goes in
  is either still in the path or in the compartment its release was handed to,
  for every outflow condition, to 1e-6.
- **The analytic Jacobian against central differences**, on a deliberately
  well-scaled path — every rate of order one, because a realistic path spans
  nine orders of magnitude and a difference cannot see a term worth 1e-18 of
  what it is differencing. Each of the ten settings in turn made to follow a
  compartment, plus the two that move through a root-find, plus a chain: every
  entry within the noise floor of the difference itself.

## Waste packages

A waste package block holds an inventory inside barriers -- containers that
fail over time, a waste form that degrades once they have -- and releases what
escapes. Written out by hand it is several compartments, a transfer per
release path and a hazard function typed into each of them, all of which have
to be kept in step; as one block it is a handful of settings.
`src/domain/wastepackage.js` is the block, and the builder gives it:

* **two hidden states per index** -- `Canisters intact` and `Canisters
  exposed` -- registered after the far-field pathways, with `role`, an `unit` of
  their own (the inventory unit; the block's is its release's) and `block`
  pointing at the package block, so `absoluteTolerance`, the non-negative
  mask, the decay loop and the mass-balance members all take them with a
  one-line widening of `kind === 'compartment'`;
* **a slot per setting**, named `Canisters#irf` etc., the inventory and IRF per
  index and the rest single-valued (`over = []`), exactly as a path's settings
  are; a setting the way of failing does not read gets no slot, so an empty
  Weibull scale on packages failing at a constant rate is not an equation to
  compile;
* **a hazard slot** (`#hazard`) emitted from `hazardCode(kind, …)` over
  `ctx.t` and the setting slots, and **the release slot** under the block's own
  name, `h·P·irf + d·M`, both with `needs` so `orderAlgebraic` puts them after
  what they read -- the same hook a recorder uses;
* **the derivative**: `out[P] -= fail; out[M] += fail − rel` with `fail = h·P`
  and `rel` read back off the release slot, which is exactly `fail(1 − irf) −
  d·M` and keeps the two in step by construction; the release itself is
  delivered by the transfer drawn out of the block (`rate` the block's name,
  `multiply_by_donor: false`, as for a path), or by nothing, in which case the
  audit counts it as `out`;
* **a jump** for *all at one time*: generated code, with `stateOffsetExpr` /
  `farfInletExpr` finding the target's cell, closed over `X`, and exposed as
  `system.jumps = [{name, slot, apply}]`. The runner reads the time off the
  slot (`system.slotValue`) after the build -- not baked, because a
  probabilistic run moves the parameter behind it -- refuses one whose
  `slotClass` is not "once for the run" (`fail_at: time() + 1`), adds it to
  the breaks and applies it in `solveAcrossBreaks` to a copy of the state
  between segments, so the row *at* the corner is the state before the change
  as the segment semantics already say. The other failure times go into
  `switchTimes` from the block, resolved as declared switch times are;
* **its analytic Jacobian**, in `src/sim/jacobian.js` beside the far-field
  hooks: the hazard slot's columns are its failure settings' (empty for
  constants) and its tangent zero -- a failure setting that follows the state
  is *refused*, since the hazard's derivative in each closed form is not a
  thing to approximate; the release slot's columns are the two inventories
  plus the hazard's, the IRF's and the degradation rate's (the last two per
  index, like the release), and its tangent is
  `h(v_P·irf + P·dirf) + d·v_M + dd·M` with the setting tangents present only
  when the pattern says they move; the two rows are `PAT(P,P)`, `PAT(M,P)`,
  the hazard's columns on both and the release's on M, with jvp
  `dout[P] -= h v_P; dout[M] += h v_P − dX[release]`. The matrix is not
  constant over the run whenever the hazard reads the clock, which
  `isConstant` learns from the slot's own code. `solveAcrossBreaks` also
  gained the statistics it used to drop between segments -- `solver`, `held`,
  `npds` -- which is why a model with a switch time said "solver undefined".

Against closed forms (`test/run.js`): with no decay, an exponential failure
from t₀ gives `P = P₀e^{−λτ}` and `M = λ(1−irf)P₀(e^{−λτ} − e^{−dτ})/(d − λ)`,
matched to 10⁻⁸ and 10⁻⁷ under dp45; the Weibull's fraction failed matched to
10⁻⁷; the jump conserves mass to 10⁻⁹ and lands the IRF in the target; the
audit closes to round-off in every mode, including a read-only release
counted as `out`. The bundled example (4,500 canisters, Weibull, four
nuclides, a million years) is 50 states and 75 ms.

Two choices worth recording. The uniform window's hazard `1/(t_to − t)` is
capped at a thousandth of the window (`WINDOW_TAIL`) so the solver does not
chase it to infinity; the last packages go within a few thousandths more,
which is the same answer at any resolution a model has. And solubility stays
out of the block: it is on a transfer, as an availability, which is where the
molar sharing lives, and a second copy inside the package block would be a
second place for the same physics. `packages` is a count for the reader, and
for a realisation that fails them one by one under an event.

## Events

The disruptive-event scenarios of a safety assessment -- an earthquake that
fails a share of the canisters, a glaciation that flushes a compartment -- are
written in prose as something that happens at a time or at random and then has
consequences. The `events` block (`src/domain/disruption.js`) is that: a timing,
and two kinds of action -- fail a share of a waste block's packages, move a
share of a compartment. Its own value is a *state*: the count of occurrences.

It is distinct from a **trigger**, which watches two quantities cross and fires:
a trigger detects and moves no mass, an event acts.

**Two readings, and the switch between them.** The builder emits, per event,
a `#lambda` slot holding the expected-value rate -- the rate inside its window,
multiplied by `ctx.dis[k]`, a per-event runtime switch that is 1 by default --
and uses it as a hazard: `+ lambda·share` inside the waste block's hazard slot
for a fail action (the waste slot's `needs` gains the event's slots, so the
order holds), a first-order term `lambda·share·y[A]` between the two
compartments for a move, and `d(count)/dt = lambda`. A probabilistic
realisation that samples calls `system.setDisruption(k, {sampled: true,
times})`, which sets `ctx.dis[k] = 0` and hands the runner the occurrence
times as jumps; the same generated jump code (`failLines`, shared with the
waste block's own *all at one time*) fails the share, moves the share and adds
one to the count. So a deterministic run is the expected-value model and a
realisation is a sample path, with no term counted twice and nothing in the
model file saying which is which.

**The draw** is `sampleOccurrences(rate, from, until, streamFor(seed,
`${name}#occurrences#${i}`))`: exponential gaps, capped at 10,000, from a
stream keyed by the seed, the block and the realisation -- independent across
events and realisations, reproducible for a replay (`runRealization` goes
through the same `applyPoint`, which draws after the parameters are set, so a
rate that is itself a sampled parameter is drawn at that realisation's value).
A rate or window slot that is not "once for the run" cannot be a homogeneous
process and keeps the expected-value form. A tornado draws nothing. `designFor`
no longer refuses a model with no distributed parameter when an event samples:
the dice are the events, and `hasDistributions` offers the button for them.

One consequence for the probabilistic matrix: a run's own time axis carries
its corners as output points, and a sampled event puts corners where each
realisation's dice fell, so realisations no longer share an axis. They used
to be copied row for row onto the first run's -- which silently misaligned
every realisation with a different number of corners -- and are now read at
the requested output times, which every run's axis contains exactly; the
result's `t` is that grid.

**Corners and the Jacobian.** A timed event's time and a window's ends go into
`switchTimes` from the block, the sampled times through the jump list, and
`solveAcrossBreaks` applies every jump due at a corner to a copy of the state
between segments, counting them into `stats.jumps` for the log. In
`src/sim/jacobian.js` the `#lambda` slot's columns are its rate and window
slots' (empty for constants) with tangent zero -- a rate that follows the
state is refused, as a moving failure setting is -- the hazard slot's columns
and value gain the events' terms, the count's row takes the lambda's columns,
and a move's two rows are `PAT(·, A)` plus the lambda's and share's columns
with jvp `lambda·(share·v_A + dshare·A)`. `isConstant` treats a windowed rate
as clock-dependent and a rate over the whole run as constant, and adds the
lambda and share slots to the rate blocks it inspects.

Against closed forms (`test/run.js`): a fail share of 0.1 at 10⁻³ a year over
2,000 years leaves `e^{−0.2}` of the inventory intact and a count of 2.000, to
10⁻⁷; a timed event's jump moves exactly half and fails exactly a fifth and
conserves mass to 10⁻⁹; six sampled realisations give integer counts with the
intact inventory exactly `0.9^count`, and realisation 2 replays to the same
count. The Jacobian agrees with differences and is constant for an unwindowed
rate.

## The solver's own settings

Two tables in `src/ode/solvers.js`: `SOLVER_OPTION_INFO` is what a setting *is*
(label, shape, what it does) and `SOLVER_OPTIONS` is which solvers read it. The
interface builds its rows from the second, so a setting appears exactly where
it does something -- and the ones left out are *named* underneath, which is the
half that matters: a knob that silently does nothing is worse than a missing
one, because nothing on screen says which it is. The pattern, and that
sentence, come from `facsimile.html`, which does the same for the same reason.

Each is normalised in `Project` whatever the solver, so changing the solver
never silently changes what a setting means, and out of range is *refused*
rather than clamped -- a step budget of -1 or an order of 9 is a mistake, and a
run that quietly used something else would be a number nobody could account
for. All of them are in the fingerprint, since each changes how the run is
stepped.

**Two of them need care to reach the solver at all.** `max_step` and
`initial_step` have been settings of the model, editable in the file, and in
the fingerprint's solve-settings list -- so setting one forced a re-solve and
then produced an identical run. Only `scipy.js` ever read `opts.hmax`, and
nothing set it. They are wired now, and `ndf` also forwards the step budget
`ndf.js` has always had.

## The DifferentialEquations.jl solvers

`src/ode/julia/` is a package of stiff solvers ported from SciML's
DifferentialEquations.jl -- FBDF, QNDF, Rodas5P, RadauIIA5, KenCarp4, TRBDF2 --
written for the browser, with no dependencies, and vendored here whole. It is
not this project's code and is not written in this project's voice; its own
README, which travelled with it, says how it was written and how it is checked
(observed order of convergence at fixed steps, then the Hairer and Wanner stiff
set against `scipy.integrate` Radau at rtol 1e-12).

`src/ode/julia-solvers.js` is the adapter, and it exists because five things do
not line up:

* **the Jacobian.** This tool hands over an *evaluator* that fills a values
  array against a CSC pattern; the package wants a callback that fills its own
  matrix. Same pattern shape, so sparse is a `set` and dense is a scatter.
* **the output.** This tool asks for a row per point of `tspan`; the package
  calls that `saveat`.
* **the recorders.** The blocks that remember are handed every accepted step
  (`onAccepted`) and every requested time (`onOutput`), as with this tool's own
  solvers. The second was not passed on at first, so with these six a step
  across an output interval hid the extreme at that time from a min/max.
* **events.** Both are "a vector of functions whose sign change stops the run",
  with a direction for each, and every one of this tool's is terminal.
* **failure.** This tool throws a `SolverError`; the package returns a retcode.
  A run stopped at an event is not a failure.

Three changes were made to the vendored package, all recorded at the end of its
own README and all worth taking back upstream. Two are adaptations: a `jac` may
answer `false` to decline a point (this tool's analytic matrix refuses one where
an entry would be non-finite and differences for it), and the differencing
machinery is therefore built even when a `jac` was given. The third is a bug
fix: **a root at the instant the solve began is not a crossing**. A caller that
stops at a terminal event and restarts from it hands back the state at the root,
where `g` is zero to rounding; on the unlucky side of that rounding the first
step crosses it again, the event fires twice, and a duplicate row lands in the
output. KenCarp4 did exactly that on `examples/recorders.json` where the other
five landed on the lucky side.

Eight faults were then fixed in the package on 2026-09-25, each listed at the
end of its README with the check that failed before it: with two or more event
functions none was ever located (the per-function direction array was compared
with 0 as a whole); FBDF's and QNDF's rows between steps came from a Hermite
whose far-end slope stayed zero, off by about h·f -- they now read their own
polynomials; rows inside a step an event cut short were read at the wrong
place; there was no hook for the saved rows; QNDF rolled its differences
forward before the error test and from the unclamped state; RadauIIA5 took its
starting guess from a failed attempt and, after a Newton that diverged, fell to
the floor for good, while a step that failed at the floor was retried until the
step budget ran out; RadauIIA5 kept a complex factorisation from a Jacobian
renewed for age; and a NaN error estimate was accepted while the maximum norms
skipped NaNs.

Four more the same day, all about what happens at a restart. FBDF could not go
on from packages that all fail late in a run: its first step predicted no
change, so its error estimate was h·f and no step the clock could represent
passed (the waste packages of a made-up model failing at t = 5000 were refused
at 1.5e-11), and its history's times were the clock's rounded readings, 3 %
out on the shortest steps there -- it now predicts by an Euler step and keeps
its history as the steps themselves. FBDF moved a component at rest by
rounding, its Lagrange weights reaching thousands once the step had grown, and
an event on such a component fired at every upward pass; the sums are now
differences from the newest point, which are zero for a constant. The state
handed back at an event was read at the middle of the root's bracket, a hair
short of the crossing now and then, and a run restarted there could meet the
same crossing again a few ulps in, past the guard above -- it is now the
bracket's far end, where the function has crossed, as `events.js` reports it.
And RadauIIA5 carried its starting guess below zero from a component clamped
there, where rates that read max(0, y) are flat; it now keeps the guess at or
above zero where non-negativity was asked for.

One trap in the adapter: the package merges what it is
handed over its own defaults, so passing a key with the value `undefined`
*replaces* the default rather than leaving it. `dtmax: undefined` made every
step size a NaN and the run never left `t0` -- with all six methods reporting
"more than 10,000,000 steps at t = 0", which reads like the solvers being
broken rather than the adapter. The adapter now sets only the keys it was given.

Measured against `ndf` on the bundled models (steps, and the worst relative
error against the same solver at rtol 1e-11):

```
biosphere.json     ndf 442 / 6.2e-5    rodas5p 151 / 1.6e-7    radau5 211 / 1.0e-6
                   fbdf   637 / 1.3e-5    qndf    775 / 1.2e-6    kencarp4 180 / 6.6e-5
```

Rodas5P is both the most accurate and the cheapest of them there, which is not
a general claim -- it is one model -- but it is why the catalogue points at it
first among the six.

## Importing blocks from another model

Several of the features below have no counterpart in the `.eco` format, so a
model that uses one cannot be written back out as one. That is the only thing
they have in common.

The mechanics of carrying blocks between two models are `copySelection` and
`pasteBlocks`: the clipboard is not cleared by loading a
model, so a block can be copied in one and pasted in the next. What that route
cannot do is the part that makes cross-model work hard, which is the
*dimensions*. A copy carries no index lists of its own, so pasting a per-nuclide
block into a model with no nuclide list drops the dimension and every value
under it, and pasting one whose list has nuclides the receiving model has never
heard of drops those values. Both are right for a clipboard, which has to do
something sensible in one step and cannot ask.

So `src/domain/import.js` is the asking half: `surveyImport` works out
everything that would have to be decided -- which lists are missing, which
indices are, what leaving them out costs, which names collide -- without
touching either model, and `applyImport` carries the answers out and then hands
the ordinary paste the job it is already good at. The dialog is one row per thing
that has to be matched, with the target choosable on each.

Three things are worth recording about how it works.

*The rename is the editor's own.* A dimension that is going to become one of the
receiving model's is renamed in a scratch copy of the source with
`renameIndexList`, which already follows a list name through every block's
`index_lists`, every entry key, and every list defined from it. A second rewrite
written here would be a second chance to get it slightly differently wrong. The
one guard lifted is the refusal to rename the radionuclide dimension -- that
guard is about a model being edited, and this is a copy whose only purpose is to
be read from.

*The defaults are conservative about the receiving model, not about the blocks
arriving.* A dimension the receiving model does not have is added; one it does
have is used as it stands. Widening an existing list is not a change to the
blocks arriving -- it is a change to every block already indexed by it and to
the size of the state vector -- so it is offered, counted (*11 values will be
dropped*) and never taken silently.

*The dialog answers the question by doing it.* Whether the result would build
is asked once the clicking stops, by carrying the import out on a copy of the
receiving model and running `buildSystem` on that -- not by a rule written to
predict the answer, which would be a second implementation of the builder's
dimension algebra and would be the wrong one. It costs about 85 ms for 94
blocks out of `one small vault model` into the biosphere example; past a second it
stops asking. This is what makes the hard case honest, and the hard case is the
real one: an assessment model's index lists are partly made of its own blocks --
`AdvectiveTransfers` is a sub-set of the transfer dimension, `Parts` a mapping
onto the compartment one -- and those cannot mean the same thing in a model
with different blocks. Such a list arrives holding only the blocks that arrived
with it, under the names they arrived under; one left holding nothing is not
added at all; and the coverage that cannot be repaired automatically is named
on the row before the import rather than found in a build error after it.

*Two rules the paste has to keep*, both about the derived block dimensions and
both silent when broken. An index of `Compartments` **is** a compartment's
qualified name, and a name is exactly what a paste changes -- so a
per-compartment value has to be re-keyed, or it means a different compartment in
the receiving model. And the check that drops values keyed by unknown indices
has to run against the model as it will be *after* the paste, or a value keyed
by a compartment arriving in the same paste is dropped for naming something the
model does not have yet. Both live in the paste, so the in-model clone gets
them too.

## A clipboard two tabs share

`state.clipboard` in `app.js` is the clipboard: what `copySelection` took,
waiting for `pasteBlocks`. It lives in one page, which carries blocks from one
model to the next *in that tab* -- load another model and paste -- and is no
help when the two models are open side by side, which is how anybody compares
them.

So `src/ui/clipboard.js` writes the same payload to `localStorage` as well. Two
tabs of this application are two pages of one origin, and that is the one thing
they both see.

- **The in-page copy is still the real one.** This is a second place the same
  object is written, not a replacement, so a paste in the tab that copied works
  with storage switched off. Everything about the sharing degrades to nothing.
- **Whichever copy is newer wins**, which is what a clipboard means. Each record
  carries when it was taken; `clipboardNow` compares that against this tab's
  own, and a tie goes to this tab -- that copy is certainly intact, where the
  shared one is a round-trip through JSON and could have been written by a
  different version of this application.
- **`clipboardInfo` reads the same thing**, so a copy taken next door enables
  Paste and the item's tooltip names the model it came from. A paste that
  silently produced another window's blocks would be the wrong kind of surprise.
- **The `storage` event fires in every tab but the one that wrote**, which is
  exactly "somebody else copied" and needs no filtering. It is what turns a
  greyed-out Paste live without a reload.
- **It can decline.** The quota is a few megabytes over the whole origin and the
  autosave draft is sharing it, so `MOST` is 1 MB and a copy past it is kept in
  the tab that took it and not shared -- said in the message, because a copy
  that is silently not shared shows up later as a paste that produced the wrong
  blocks. A refusal also clears what was shared before, so a stale copy is never
  offered as though it were this one.
- **Anything unreadable is nothing.** A half-written value, a record from an
  older version, a key another script wrote: `get` checks the shape it needs and
  returns null otherwise, because a clipboard that throws on paste is worse than
  an empty one.

## Undo and redo

`src/ui/undo.js` is written as *snapshots*
rather than as the usual stack of inverse commands. An edit here is one of
about a hundred functions in `edit.js` writing straight into the model, and an
inverse for each would be a hundred chances to write one that is subtly wrong,
plus a hundred and first whenever an edit is added. A snapshot cannot miss
anything, because nothing has to be enumerated: the model is a plain JSON
object -- the JSON tab shows it and Save writes it -- so a snapshot is
`JSON.stringify` and restoring one is `JSON.parse`. Every edit in the
application already funnels through `modelChanged`, so that is the only place
that had to learn about it.

What makes that affordable on the real files is that the stack holds
*differences*: the characters between the longest common prefix and the longest
common suffix of two consecutive snapshots, stored backwards -- newest state in
full, each older step as the patch that reaches it from the step after it. On
one landscape model, 8 MB of JSON, a block move changes 18 characters and
thirty of them cost 31 characters between them. The scan compares 64 KB at a
time with `===`, which is one memcmp inside the engine, before falling back to
a character loop inside the single chunk that differs: 1 ms on those 8 MB,
against 28 for the character loop alone. Taking a step costs the stringify --
19 ms on that model, 0.05 ms on an ordinary one -- next to the 265 ms it
already spends rebuilding its `Project` and re-scanning its equations after
every edit.

The one thing that is not automatic is the *name* of a step. A full diff would
say exactly what changed but would cost a parse of the older snapshot on every
edit -- 21 ms on that model, to write a label nobody may read. So a cheap
summary is taken alongside each snapshot by walking the blocks rather than the
text (404 of them on the biggest file in the corpus), and the label comes from
comparing two summaries: a block that appeared is an *Add*, one that vanished a
*Delete*, one whose name changed a *Rename*, one whose sub-system changed a
*Move*. Where nothing structural changed, the step is named after whatever the
editor was pointed at -- *Edit Buffer*.

## The compartment and transfer dimensions

A value per compartment is otherwise written as one parameter per compartment,
or as a column somebody keeps in step by hand. `Compartments` and `Transfers`
are index lists derived from the model itself -- one index per block, named
by its qualified name -- and the block being evaluated supplies the index, so a
per-transfer rate coefficient written in a transfer's own rate needs no index
at all. `[_source_]` and `[_target_]` reach a transfer's two ends, which is the
one case the block itself cannot settle. See `deriveBlockLists` in
`src/domain/indexlists.js` and `implicitIndices` in `src/sim/builder.js`.

## Shapes on the canvas

A list of annotation shapes -- a group box, an arrow, a tree, a well -- kept in
`project.shapes`, drawn behind the blocks, and read by nothing in the engine.
`src/ui/figures.js` is the dictionary.

## A recommended unit

Where a block has no unit and its equation settles one, the editor offers it as
a button. Units are labels here and nothing converts one into another, so the
best the editor can do is say what the equation works out to and let the
modeller decide. The check behind it is the same `equationUnit` the warnings
use, which is why taking the offer always silences them.

## What an equation comes to at the start

Under every equation box in the settings dialog, and on a row of its own in the
Information view, the value that equation takes at `start_time`. Showing the
equation *text* and nothing else is the easy thing to do, and it leaves the
reader to work out in their head what `inv0 * exp(-lambda * t_delay)` actually
is at the moment the run begins.

The number itself is free: `initialState`, `primeRecorders`, one
`evaluateAlgebraic` at `start_time`, which is the first thing a run does anyway.
Three decisions carry it:

- **It is read back through `Results`.** `describeEntry` was lifted out of
  `Results.outputs` so that the dialog and the table label and unit a value the
  same way. What the line says for a block is the first row of the Table tab for
  that block, down to the unit -- checked over every bundled example and over
  the 44 imported projects that run, 116,070 series in all, none of which
  differs.
- **The build is the expensive half, so it is measured rather than guessed.**
  One evaluation is a tenth of a millisecond; building the model to do it is 21
  ms on the median imported project in Node, and in Chrome 2.4 s on a landscape
  model of 4,278 blocks. Size is no guide -- ERICA's 30 blocks over a thousand
  nuclides each take 330 ms, more than the 1,141-block mire model's 100 -- so
  the first attempt is timed and a model that costs more than 400 ms stops being
  asked, which is what `importblocks.js` does with its own build check
  (`CHECK_BUDGET`). Nothing is worked out at all until something asks: a model
  nobody inspects costs nothing, and the module that does the work is not even
  loaded until something does.
- **The line fills itself in rather than being re-rendered.** The settings
  dialog is rebuilt on every committed edit; a rebuild 400 ms *after* one, when
  the answer arrives, would take the focus out of the box being typed into. So
  each line is marked with the block and field it is for -- and, for a cell in
  the per-index grid, the index too -- and the values are written into the
  marked nodes in place. The Information view is the one exception: what rows
  there are to write into depends on the answer, so that card alone is built
  again, which is safe because nothing in it can be typed into.

Nothing is refused for being strange. Half the corpus divides by something that
starts at zero somewhere, and a line reading `not a number at all 3 indices`, or
`0 Bq to 5 Bq over 61 indices — 1 infinite`, is the feature working rather than
failing. Only a model that will not build has no answer, and that is already the
problem strip's business.

## The variable-order solver

`src/ode/solvers/ndf.js` implements the numerical differentiation formulas of orders
1–5 -- the standard variable-order choice for a stiff problem, and the default
here -- with the backward differentiation formulas as the special case of
every κ set to zero. `src/ode/variable-order.js` is adaptation around it: the
derivative convention, the progress report, the abort, and the translation of
the integrator's named failures into advice a modeller can act on. The
integrator and its linear algebra are the same code facsimile.html and
rtm.html run; see *One solver core for three pages*.

The method is written from its published descriptions -- Shampine and
Reichelt's paper for the κ values and the error estimate, Hairer and Wanner's
chapter V for the backward-difference formulation and the order and step-size
strategy -- and the file is arranged as four parts a reader can take one at a
time:

- **The difference table**: the columns ∇ʲy, the predictor read off them, the
  corrector's history term Σ γⱼ∇ʲy, and one linear map that re-expresses the
  table on another grid. That map serves three purposes -- a change of step
  size, an event inside the step (the table has to end at the event), and,
  read at a single point, the interpolant that output and event location use.
  It is derived from the Newton backward-difference basis and written so that
  the entries that are analytically zero are exactly zero.
- **The weighting**: every size is measured per state against
  max(|y|, |y_new|, abstol/rtol) and compared with rtol, or over the whole
  vector under norm control. With a floating absolute tolerance there are two
  weightings: the error test follows the floor as it moves, the Newton test
  keeps the floor the run began with.
- **The Jacobian**: the four shapes it may be handed over in -- a constant
  matrix, a function, dense rows filled in place, or the pattern's values in
  CSC with an optional column colouring -- and a differencer for when it is
  not handed over, or declines a point. Differencing through the pattern costs
  one evaluation of the model per colour and stores the pattern's entries
  rather than the square; without a pattern it is one evaluation per column.
- **The iteration matrix** I − (h/l_k)·J, held and factorised densely through
  `linalg.js` or in CSC through `sparse.js` and `refactor.js`, whichever one
  real factorisation of each ordering says is cheapest. *Iteration matrix*
  under Advanced settings overrides the choice: `refactor` is the sparse LU
  that keeps its pivots, `sparse` the Gilbert-Peierls LU that chooses them
  every time, `dense` the dense LU. Past a quarter of a gigabyte the dense
  form is not offered at all and the solver says why.

**The corrector** is a simplified Newton iteration on the correction to the
predictor, at most four iterations, with the contraction rate measured between
corrections and remembered across steps at the same matrix, so that a step is
usually taken on one iteration. A correction that has stopped shrinking ends
the attempt: the matrix is re-formed if the Jacobian is from an earlier point,
else the step is cut to a quarter. `stagnation_tol` lets a correction that has
stopped shrinking be taken on its size alone, at a Jacobian for the current
point, for the models whose right-hand side cancels so heavily that the
residual cannot be evaluated any finer.

**Step and order** are chosen only after k+1 steps at constant step and order,
from the error estimates at orders k−1, k and k+1, with a safety factor that
leans towards staying at the current order and a growth of at most ten in one
change. A rejected step is cut from its own estimate and may drop an order; a
second rejection halves.

**The constraint** -- *cannot go negative* -- is integrated as the projected
system. Where a constrained state is on zero and its equations push it below,
its derivative is held at zero and its row of the iteration matrix becomes a
row of the identity, so the state stays exactly on the bound while the rest of
the model integrates against it. Which rows are held is read once per step,
from the derivative at the point the step starts from; a matrix that followed
every flicker of a state hovering on zero was re-formed for ever and never
took a step. Inside a step the mask changes only when a held state is found to
have been released -- the equations at the point the iteration settled on no
longer push it below -- and then the step is taken again with the row
restored. A state within its absolute tolerance of zero that the step pushes
past it, or that the Newton iteration keeps flipping across the kink with, is
put onto the bound and held there: the move is smaller than the error test
could tell, and no shorter step mends either symptom. The dip `y' = 2t − 4`
from `y(0) = 1` comes out as zero until `t = 2` and `(t − 2)²` after it, to
the tolerance. The file counts every projection and, per state, the steps it
was held through where the derivative held back would have moved it by more
than its tolerance -- which is what the footer's *held at zero* is made of.

**A Jacobian that declines a point** -- an entry that is not finite there --
is differenced for that one evaluation and asked again next time.

**A run that cannot advance says so.** The published method leans on a step
floor and a person at a prompt; here there is a step budget, and a stall guard
that needs two signals before it gives up -- no ground covered over two
thousand accepted steps *and* a step size that has stopped growing -- because
a violent initial transient legitimately crawls and then recovers. A step that
cannot be cut any further is taken as it is and counted (`nbelowtol`, in the
run log); twenty in a row is a run that will never meet its tolerances, and is
refused.

Why it is the default: the corpus survey found the variable-order NDF is the
solver real `.eco` files ask for more than any other, so imports run the
method they were built around. It is also dramatically cheaper -- on
`landscape.json`, about a quarter of `ros23`'s steps for answers agreeing to
seven significant figures. It is the default for new models and for anything
imported without a recognised solver (`DEFAULT_SOLVER` in
`src/ode/solvers.js`).

## Checking the Jacobian

`src/sim/jaccheck.js` compares the generated `df/dy` against finite differences
of the generated `dydt`, and `src/ui/jacobianview.js` draws the pattern beside
the result. It exists because of the shape of the bug it looks for: a wrong
Jacobian does not raise an error. The solver takes more steps, or converges to
something slightly different, and a run that looks fine is not evidence.

**Three faults, and they are not equally bad.**

1. **A value out.** The pattern is right and an entry disagrees. The solver's
   Newton iteration converges more slowly, or to a different point.
2. **An entry missing from the pattern.** Worse, and it is the failure a
   sparsity pattern makes possible where a dense Jacobian cannot: an entry the
   pattern does not declare is *never evaluated*, so it is silently absent from
   the iteration matrix and no tolerance recovers it.
3. **A colouring that is not a colouring.** Worst. Two columns of one group
   sharing a row means their seeds collide and every value read back through
   the colouring is a sum. It is checked structurally rather than numerically,
   because the values are read column by column here and would look right.

The verdict reports them in that order.

**Resolvability is the whole of the difficulty.** A difference quotient
subtracts two nearly equal numbers. An entry whose effect on row `i` over the
perturbation is below the rounding of `f[i]` cannot be judged by one, and there
are a great many of those: on `biosphere.json` the unresolvable entries
outnumber the judged ones several times over. Counting them separately is what
keeps the report honest — treating them as disagreements would bury the real
ones, and treating them as agreement would be a claim the arithmetic does not
support.

**Several states, because an empty compartment tests nothing.** The model's own
initial state first, then three states with every compartment filled at 1e-3,
1e-6 and 1e-9 of the largest, across the run. A model that starts with one
nuclide in one box would otherwise report a clean bill on a matrix it had
barely touched.

**Two passes, because only one of them can use the colouring.** The values are
swept group by group: a group's columns share no row, so one perturbation of
all of them moves each row by the one entry of that group which owns it, and
one evaluation of the derivative yields every entry of every column in the
group. Entries the pattern does *not* declare cannot be found that way — the
group pass reads each row through the pattern, so a missing entry is
attributed to whichever column does own that row — and finding one means
differencing a single column and scanning every row of the result. That pass
costs an evaluation per column and is therefore sampled. Measured on
model F (55,728 states, 220,998 entries, 60 colour groups): 94.5 s
before, 11.9 s after, still judging 251,720 entries. The whole matrix is never
formed — `evaluate` cost four seconds a state and was read by nothing.

**Drawing and checking are separate messages**, because the picture is the
half somebody opening the view wants immediately and it costs nothing beyond
the build. Both run in the worker, which keeps the built system against the
page's edit counter — building one is eight seconds on that assessment, and a
run of the same model has already paid for it. The page throws both away on
any edit: the matrix is generated from the equations, so a stale *agrees* is
worse than no answer.

**What the picture is for.** One cell per (row, column), the diagonal in the
accent colour, drawn on a canvas because a 1,266-state model is 1.6 million
cells and that many elements never finish laying out. Above one cell per pixel
each pixel is drawn if anything in its block is non-zero, which over-states the
density — the safe direction for a picture of where the structure is. The shape
is worth the screen space: a decay chain is a band, a landscape model is a
block per object, a transport is a tridiagonal stripe, and a row that is
unexpectedly dense is usually a modelling mistake you can see before you can
describe.

**Not done.** The values are not drawn, only the structure — a magnitude
colouring would show the stiff corner of the matrix at a glance. The check
compares against differences of `dydt` rather than against a second,
independently written Jacobian, so a fault shared between the derivative and
its tangent would pass; that is what the SciPy solvers are for. And the states
it checks at are chosen rather than asked for: checking at the state a run
actually reached at a particular time would be a better question on a model
whose stiffness arrives late.

## What a run keeps

The obvious answer to "what does a run keep" is *everything*: every endpoint,
evaluated, at every output time. This tool used to do exactly that in memory —
`finish()` walked the stored rows, evaluated the whole algebraic
vector at each and kept a copy -- a dense table of every value at every output
time. On model L that is 201,004 algebraic values over
498 times, 800 MB before the states or a single chart, and more than Node
hands a run by default.

Now a run keeps its states and nothing else. `Results.seriesMany` works any set
of series out from `(t, y)` on request, one algebraic evaluation per row with
every requested value read from it -- a tenth of a millisecond a row, so a
chart of twelve lines is one pass, not twelve, and a request that reads only
compartments and parameters evaluates nothing. It is exact because every
algebraic value is a function of the clock and the state except what the
remembering blocks hold, and their histories are kept against the time they were
recorded at: `extreme(t, ...)` asked about a row long after the run answers as
of that row.

The worker follows suit. `done` carries the list of outputs and none of their
series; the page asks for the columns it is drawing (`columns`, batched per
render), the worker answers in one pass, and the page caches what it has been
given. An export of every output asks for every column at once, which is the
one request that costs what the old design always cost.

**Asking together is not a nicety.** One evaluation covers the whole algebraic
vector however many values are read out of it, so the cost of a request is the
number of *passes*, not the number of series. On the landscape model, whose
algebraic vector is 200,000 values over 356 rows, one algebraic series asked
for on its own takes 988 ms and all 49,125 of them asked for together take
1,224 ms. The worker batched from the start; `ensureColumns` did not, for a run
on the main thread -- which is what the SciPy solvers are -- so exporting that
model from one of them was an afternoon's work for the page rather than a
second. It batches now.

## Saving what a run kept

Ecolego's `.eas` is its `.eco` with the run inside it: `model.xml`, `views.xml`
and `simulation.xml` at the root, and a `simulation/` folder of `.dta` files
holding every endpoint's series: everything, evaluated.

This tool's answer follows from the section above. A run *is* `(t, y)`, so that
is what the file holds -- `src/io/dataset.js`, written into the same ZIP that a
compressed save produces, with the model at the root where it always was and the
run beside it under `results/`. On model G that is 50,490 states over a few hundred
output times, about 80 MB of doubles before deflate, against the 2.8 GB its
HDF5 export runs to. And what opens is a `Results`, not a table of one: the
chart asks for its columns through the same `columns` message, and a series
nobody has looked at yet is worked out the moment somebody does.

**The model at the root is not a convenience; it is the compatibility story.**
`readModelFile` already looked into a ZIP for a `.json`, so a results archive
opened by a build of this tool that predates the format opens the model and
ignores `results/`. Nothing had to be versioned to make that true, and the
`format` field in `meta.json` is there for the other direction -- a file from a
newer build says so and leaves the model openable.

**The writer keeps to the reader's allowance.** `unzip` refuses an archive
whose deflated entries would expand past `MAX_ARCHIVE_INFLATED` (256 MB) in
total, and a run of a large model is more than that, so Save used to write
archives Open refused. `zip` now stores any entry that would take the deflated
total past the same constant -- stored data is outside the reader's budget,
being already in the file -- so what it writes is always what it reads.

**Two things had to be carried that the reuse path refuses.** `integrationFingerprint`
returns null for any model with a remembering block, and its comment records
why: a system built fresh has empty histories, and on `examples/recorders.json`
it reported the peak dose as 6.35 where the run recorded 0.00057. Across an
edit, carrying histories over would mean proving the new memory layout matches
the old one. In one archive there is nothing to prove -- the model that built
the layout is the model in the file -- so the histories travel (`results/mem.f64`,
every `Recorder`'s `(t, v)` pairs end to end, with the four scalars a running
mean needs beside them in the meta) and are put back onto the freshly built
system's `memory` before the `Results` is made. Verified the only way that
means anything: every one of the fourteen outputs of that model, compared
element by element between the run and the file, `Object.is`-equal. The peak
comes back as 5.732e-4, the year it fell below the limit as 214.41, the value a
century ago as 4.672e-11 -- against a dose at the last row of 6.353e-13, which is
what a fresh system would have called the peak.

**The signature is the whole safety argument, so it is written down.**
`layoutSignature(system)` is one string naming every state entry and every
recorder slot by kind, name, base and width. It is saved into `meta.json` and
compared against the system built from the model *in the same file*; a mismatch
drops the results with the reason and opens the model alone. The worker's
`stateSignature` -- the re-evaluate path's check -- is now this function, since
it asks the same question of a smaller set.

What the signature cannot catch is the one case the page refuses instead: a rate
changed since the run moves no layout, so a saved pair of "model as edited" and
"results of the model before the edit" would pass every check and be a lie.
`saveFile('data')` refuses while `state.dirty`, which is the same test the dot
on Run draws from, so the refusal is in words the reader has already seen.

**Auto-run now starts off**, which is the other half of the same thought. It is
the switch that makes a keystroke start a solve, and on an imported assessment
that is half a minute of a page gone away every time a digit is typed -- paid
by everyone who opens one, to save a click for the people editing a small
model. With the run savable, the cost of *not* re-solving on every edit is a
click on Run; the cost of doing so was never recoverable.

## Writing HDF5

The assessment tools around these models read HDF5 and nothing else. So this
tool has to write it, and the question was how.

**Not by linking the library.** The browser build of libhdf5 is h5wasm: 4.7 MB
of WebAssembly from a CDN. This tool has no build step, no dependencies and no
network — `index.html` and the files beside it are the whole of it — and a
feature that only works online, in a program whose point is that it is a folder
you can copy, is a feature that will not be there when it is wanted. So
`src/io/hdf5.js` writes the bytes. It is a writer only, and a narrow one:
groups, one-dimensional arrays of doubles, floats, ints and strings, and
attributes on both. That is what a result file is.

**Which flavour.** There are two ways to store a group and this writes the
newer: version 2 object headers with the links as messages in the header
itself. The older way — a symbol table, a local heap and a version 1 B-tree,
which is what `h5py` writes by default — means building and balancing a B-tree
for every group in the file, and the number of entries one node may hold is a
constant in the superblock, so a group of 53 radionuclides is a tree rather
than a list. Compact groups need no tree at all: a link is a message, and a
group of six hundred children is six hundred messages. The price is that every
version 2 structure ends in a Jenkins lookup3 checksum, which is forty lines
(`H5_checksum_lookup3` from `H5checksum.c`, byte for byte); the saving is the
whole of the tree code. libhdf5 has written version 2 headers since 1.8 and
reads them everywhere.

Strings are variable-length, in a global heap, because that is what Ecolego
writes — `h5py` reports its `unit` attributes and its `/IndexLists/*` datasets
as `dtype=object` — and because a fixed-width string reads back padded. The
writer pools them: `TRUE` is in the file once however many datasets say it,
where libhdf5 inserts each one again. Booleans are the string `TRUE` or
`FALSE`, which is what Ecolego's own files hold (an enumerated type there) and
what every reader of them tests for; an enumeration would be two more datatype
classes for one bit.

**What is written once.** A series whose value cannot change over the run is
one value in the file and says `time_dependent = FALSE`. In a file of
realisations it is one value per realisation, a column of *n*. Which series
these are is decided from the model by `timeDependentOf` in
`src/sim/runner.js`, never from the numbers:

- a slot of `P`, which is a parameter or a point of a lookup table;
- an algebraic slot the builder works out once for the run (`slotClass` 0),
  except the kinds whose value is a history: the recorders, triggers and
  events;
- a derived value that is one number for the run (`isSeries` false in
  `src/domain/derived.js`).

A state is always time-dependent, even one that stays at zero. Judged by its
numbers, a dose that has not arrived yet would be written as one zero, and
drop out of its nuclides' chart. The descriptor carries `timeDependent: false`.
`prob-matrix` with `compact` returns such a series as one row of realisations,
so a file of a thousand varied parameters is not first built at every time.

**How it was checked.** Every structure was decoded out of a file libhdf5 had
written before it was written here, which is how the awkward details were
settled rather than guessed — that a variable-length string's parent type is an
eight-bit unsigned integer rather than a one-byte string, that the reference
count on a heap object is zero, that `Link Info` and `Attribute Info` with both
addresses undefined is how a header says "they are in here". The checksum was
verified against the superblock of an `h5py` file before anything used it. Then
the other way round: files this writes are opened with `h5py`, `h5ls` and
`h5dump`, and with the browser's h5wasm, which draws them. The suite has no
libhdf5, so `test/hdf5-read.js` reads them back — verifying both checksums and
refusing anything outside the subset the writer produces.

**What is not written**: chunking, compression, references, enumerations,
compound types and external links. A file of realisations has one
two-dimensional dataset per series, times by realisations. `/time` carries a
`probabilistic` attribute saying `FALSE`, because the browser reads that to
decide whether the time axis is a matrix with one row per iteration. Every
realisation here is reported on the one output grid, so it never is.

## Solver naming

`src/ode/solvers.js` is the catalogue: for each solver an **id** and a **label**.

The id (`ndf`) names the method. It is what the project file
stores, what `Results.stats.solver` reports and what error messages quote, so
it must not drift — it is the term to search for when checking a run against
desktop output.

The label (`stiff, NDF`) is what the interface shows, because at the
moment of choosing, what matters is whether the problem is stiff, not which
formulas are underneath. The full blurb is the option's tooltip.

The catalogue imports none of the integrators, so the interface can list and
name them, and `domain/project.js` can name a default, without dragging the
builder, the parser and three integrators onto the main thread — runs happen in
a Worker.

**The plain BDFs are a switch on the NDF, not a second solver.** Kappa is
precisely the difference between the two families of formulas — zeroing it
turns the NDFs into the plain BDFs — and it is the same integrator either way.
So the list has one entry, `ndf`, and the NDF has a setting, `simulation.bdf`
(*BDF formulas*, off), as QNDF has the same one for QBDF. They used to be two
entries, `ndf` and `bdf`, on the argument that offering both says what those
terms are worth; the switch says the same with one list entry fewer, in all
three pages alike. Running with and without it still shows what the terms buy,
and an answer worked out against plain BDF is still reproduced exactly. A file
that names the solver `bdf` (or its older name, `ode15s_bdf`) opens as `ndf`
with the switch on, in `domain/keys.js`, and runs the same code bit for bit.
The statistics report the formulas that ran, so a run log never says `ndf`
for a BDF run, nor `qndf` for a QBDF one.

## What the file gate enforces

A model can arrive as a file. A file does not come through the editor, so every
rule the editor enforces has to hold again at the gate — `Project`, and the
importers that feed it — because nothing downstream re-checks it.

**Names are tidied before anything else sees them.** An empty name becomes the
block's id; a reserved word (`min`, `if`) is numbered past; a name with an
operator in it (`A-B`) is rewritten to `A_B` in every equation and flagged in
the import report, since those same characters also spell `A - B`. `names.js`
is the one place `NAME_RE` and `RESERVED` live, and every rename in the editor
goes through the same gate, so the two cannot drift apart.

**`__proto__` and its two relatives are refused outright** as a block, nuclide,
index or list name, and every map keyed by a string out of a file is
prototype-free — so `<time-unit>constructor</time-unit>` is an unrecognised
unit rather than `Object`. A block named `__proto__` otherwise merges its
diagram coordinates into `Object.prototype`, and `layoutOf(project)` is the one
way a position is written for the same reason.

**A name never reaches generated source unescaped.** The derivative is compiled
with `new Function`, so a block name carried into a `//` comment is a way for a
newline in a file to end the comment and have the rest compiled and run. Index
names are validated for the same reason: with auto-run on, opening a file is
the whole of it.

**Index lists are checked for what the builder assumes**: no duplicate indices,
no empty dimension, no list named twice.

**An archive is read lazily, under one budget.** Every entry inflated eagerly
put the size bound on each entry rather than on the archive, and an `.eas`
assessment carries a `simulation/` folder of results the importer never reads —
so a damaged result file could fail the import of the model beside it. Entries
are inflated when asked for, under a single budget for the whole archive, and
every offset a ZIP64 record supplies is checked against the file before it is
believed. A file past 200 MB asks before it is read.

## The content policy

`index.html` carries a Content-Security-Policy in its head, with
`frame-ancestors` and `nosniff` as headers from `serve.py`, because a `<meta>`
tag cannot carry the first.

It needs `'unsafe-eval'`: the derivative is `new Function`, in the Worker and on
the `?mainthread` fallback alike. That is why a policy looks pointless at first
— model text does not reach the generated source, so there is nothing for it to
catch there. But a policy also decides where the page may *send* things, and the
result-browser handoff posts an entire result file to an address a query
parameter would otherwise choose freely.

Having one took the last two inline `<script>` blocks out of `index.html` —
they are `src/ui/start.js` and `src/ui/boot-problem.js` — which also removed
the last `innerHTML` in the project.

## Three choices in the parser

**`a^-b` is accepted, and `^` stays left-associative.** `2^-3^2` is `(2^-3)^2`.
A single signed operand after `^` is allowed because `year^-1` is how a unit is
written and refusing it would help nobody; anything longer has to be bracketed.

**NaN is false.** The inline `&&` and `if` used to treat it as true where the
function table's `and` and `if` treated it as false. Both read `!== 0` now, as
the equation rewriter does, so a condition over a value that is not a number
takes the same branch wherever it is written.

**`factorial` is capped at 170**, past which the double is infinite anyway.

## One stream per sampled parameter

Realisations used to be drawn from one stream split across the sampling plan in
order, so adding a distribution to one parameter shifted every parameter after
it: adding an unrelated input moved `k` from 0.18703, 0.16908, 0.12687 to
0.05209, 0.14484, 0.18309 — same seed, same distribution.

Each parameter's stream is now seeded from the run's seed and the parameter's
*indexed* name. That is what makes a re-run after a review comparable at all,
and **partial sampling** follows from it and only from it: hold some inputs at
their values and everything that still varies takes exactly the numbers it took
in the full run, so the difference between the two bands is the input.

## Availability

A solubility limit or a Langmuir isotherm makes the flux
`rate × availability × amount`, which is non-linear in the inventory. All four
schemes are here, individual and shared, with the unavailable form of each;
`src/domain/availability.js` holds them.

The trap is the Jacobian. Emitting the availability into the derivative and
leaving the Jacobian generator alone gives a right flux and a matrix that is
still the linear one: above a solubility limit Newton is told the flux moves
with the inventory when it no longer does, and `examples/biosphere.json` runs
to a million steps and stops at the moment the inventory crosses the limit,
whatever the limit is.

The analytic Jacobian used to be **declined** for such a transfer, which is
safe and made availabilities unusable on large models: a 16,720-state
repository model with one solubility limit would have needed its matrix
differenced densely, 2.1 GB of it. Now the availability is folded into the
transfer's own algebraic slot, so the transfer's value is rate × availability:

- **its operands have slots of their own.** The limit, or the two Langmuir
  coefficients, are `<transfer>#limit` (`#top`, `#bottom`), hidden, of the
  transfer's dimensions, parsed and ordered like any equation and answering
  `_source_`, `_target_` and a per-transfer value as the rate does. The
  transfer's slot `needs` them.
- **the product is one pass after the rate.** Whichever way the rate was
  written out — one scalar line, a loop, per-entry bodies — `emitAvailability`
  then loops the transfer's dimensions and multiplies each slot by the
  scheme's expression (`expressionOf`) in the donor's amount. The slot now
  reads `y`, so the classification puts it with the slots worked out on every
  call, and the derivative assembly is `donor × value` for every transfer.
- **the amount is a list of terms.** `availabilityTerms` gives the offsets it
  sums, each with its molar weight and, for a group, its condition: shared
  over a *grouping* of the donor's list (`Elements`), the group is read at run
  time from the grouping's table, `MAPS[g][peer] === k`, against each
  member's group worked out at build time. The value (`y`), its tangent (`v`)
  and the pattern's columns are all written from that one list.
- **the tangent is the scheme's own** (`tangentOf`): zero before a limit's
  corner, `(dL·a − L·da)/a²` past it, the quotient rule for Langmuir, the sign
  turned over for what is held back — differentiated as the code is written,
  branch by branch. `d(r·A) = dr·A + r·dA` is emitted after the rate's own
  tangent. Along a parameter the amount's tangent is null.

`test/run.js` compares the matrix with central differences on both sides of
every scheme's limit, individual and shared, and with a grouped limit whose
groups must not couple.

## Switch times

A source that is on for five years out of a thousand, undeclared, is stepped
clean over by `dp45`: the run reports that nothing was released. Declared, the
same model is right to four figures. `src/domain/switchtimes.js` collects the
times a parameter changes value and the solver is made to land on each of them.

## A coarser clock for the clock-only algebra

`min_change_time` works the algebra that depends on nothing but the clock out
on a coarser clock and interpolates between — linearly, because holding it flat
would make a ramping rate lag by half an interval. Two to three times faster on
a clock-heavy model, for a part in a million.

## Derived parameters

`src/domain/derived.js` works a quantity out from the finished curve —
a peak, a mean, a time of arrival — rather than accumulating it during the
integration. That is the whole point of doing it this way: post-processing
costs the solve nothing, where a min/max block accumulates as the solver steps
and stops the trajectory ever being re-used.

## Parameter QA

A block's approval status is *computed* from the model each time it is asked —
the block's own stamp, and whether everything it reads is itself approved —
rather than recorded and invalidated by hand. So no edit path can forget to
invalidate anything, and the panel can say *which* upstream change lapsed an
approval. The dependency walk it needs is the one the delete guard and the
re-solve fingerprint already use.

Locking is enforced at the single funnel every edit passes through, rather than
in the fifty functions that can change a block.

## A probabilistic run over the cores

Realisations are independent, so running them one after another on a single
Worker leaves every other core idle. There is a pool: the Worker that receives a
probabilistic run starts one Worker per core, less one for the page, and hands
each a range of realisations. It is its own child — `sim-worker.js` answers
`prob-slice` as well as `probabilistic` — so there is one build of the
simulator's code and no second file to keep in step.

**The constraint that shaped it: the answer may not depend on the machine.** An
assessment is checked against desktop output and re-run years later; "the same
seed gave a different 95th percentile on a different laptop" is not a defect
anyone should have to chase. Two things follow.

*The design is drawn whole, by everyone.* Latin hypercube sampling is a
statement about the entire column of realisations — the i-th realisation takes
the i-th entry of each parameter's own shuffled stratification — so a slice
cannot draw its own. Each Worker runs `rng(seed)` over all `n` realisations and
integrates only its range. It costs `plan.length × n` random numbers per Worker,
which is nothing, and it is what makes the result identical.

*Slices are placed, not appended.* The fourth Worker often answers first, and a
matrix assembled in arrival order is a run whose realisations are shuffled.
Every statistic over it would accept that without complaint — a quantile does
not care what order it reads — so the bands would be right and the sensitivity,
which pairs the i-th sample with the i-th output, quietly wrong. `stitch` writes
by realisation number.

There is a test that runs `examples/biosphere.json` serially and then in 2, 3, 5
and 24 slices and compares every cell of every matrix and every drawn sample.

**When it declines.** Every Worker builds the model for itself — a built system
is compiled functions and typed arrays and cannot cross a `postMessage` — so
fanning out costs `w` builds instead of one, plus about 60 ms per Worker to
start and compile the module graph (measured in Chrome on a warm cache: 55 ms
each, 406 ms for nine started together). `workersFor` does that arithmetic
against the build and solve times the last deterministic run measured, and
returns 1 where it does not pay: a model that takes a minute to build and five
milliseconds to solve is slower on eight cores than on one. It also returns 1
where the browser will not nest Workers, which it finds out by trying.

**A number the reader chose** (*Cores* in the Probabilistic and Tornado
dialogs, `src/ui/cores.js`) goes to the worker as `cores` and to `workersFor`
as `exact`: used as it stands, bounded by the cores the machine reports
(`hardwareConcurrency`, which is also where the dialog's list ends; `MOST_WORKERS`
where the browser does not say) and the number of realisations, and not
second-guessed by the build arithmetic. It is kept in
`localStorage` (`kompartment.cores`), not in the model: it changes no number. The
coordinator posts `{type: 'pool', workers, asked, why}` once it has sized the
pool and before anything is built, and the footer shows the count beside the
bar for the rest of the run, with `why` in its tooltip.

**Stopping.** Terminating the coordinator would leave its children holding a
core and a matrix each with nothing able to talk to them. A `cancel` message
*does* reach the coordinator during a pool run — it is awaiting messages, not
solving, which is the one time a message gets through — so it kills the pool and
answers `cancelled`, and the page waits 250 ms for that before terminating it.
A deterministic run never answers, because it is one long synchronous call,
which is why terminating exists at all.

**Not done.** The pool is sized per run and torn down after it; a long session
pays the start-up each time. Ecolego's own `<max-n-processors>` setting is not
read from the file; *Cores* sets the number by hand, and `?workers=` caps it.

## Global sensitivity, from GlobalSensitivity.jl

`src/domain/gsa.js` is a port of GlobalSensitivity.jl 2.12.8's methods: the
designed ones (Morris, Sobol, eFAST, RBD-FAST, fractional factorial, DGSM,
Shapley) and the ones that read a sample (EASI, δ, RSA, mutual information).
Its regression method is not ported: it fits without an intercept and ranks by
`sortperm`, and `src/domain/sensitivity.js` already does SRC, PCC and their
rank forms properly.

**How it was checked.** `scripts/gen-gsa-ref.jl` runs GlobalSensitivity.jl on
fixed designs and data -- Ishigami, linear and product test functions, so
nothing in it is anybody's data -- and writes what it gets, with every random
draw the methods make of their own replayed from the same RNG (eFAST's phases,
RBD-FAST's permutations, δ's bootstrap indices, the MI shuffles), to
`test/fixtures/gsa-reference.json`, arrays as base64 of their Float64 bytes.
The test rebuilds each design here, requires the outputs over it to be Julia's
to 1e-12, and each estimator to agree to 1e-9 (1e-7 for the intervals, whose
normal quantile is computed differently). The worst difference on the day it
was written was 8e-13. Designs that Julia draws from its own generator (Morris's
walks, Shapley's samples) are compared through their recorded points; the
methods are also held to known answers -- Ishigami's closed-form indices,
exact effects on linear functions, Shapley effects of a correlated Gaussian
model -- because a design here is drawn from the tool's streams, not Julia's.
To regenerate: a Julia environment with GlobalSensitivity 2.12.8, StableRNGs,
JSON3, Distributions and Copulas, then `julia --project=… scripts/gen-gsa-ref.jl`.

**Probability space.** Every design is in the unit hypercube; `gsaDesignFor` in
`src/sim/probabilistic.js` maps a point through each input's
`valueAtProbability`, as a Latin hypercube sample is mapped. A correlation
group is one factor, its members sharing the column; a partial run's held
inputs are not factors; a `pg` list read in order is read by probability; no
disruptive event draws dice (a design point is its factors' and nothing
else's). The correlations reach Shapley only, as a Gaussian copula of the
normal scores with ρ = 2 sin(πρₛ/6), shrunk towards independence by the least
that makes the pairs a valid matrix.

**The deliberate differences** are listed at the top of `gsa.js`: seeded
streams instead of Julia's RNG and Sobol sequences; Morris's levels at the
middles of the probability slices and no candidate trajectories (all spreads
are equal in probability space); eFAST's points per curve raised to where the
harmonics fit (Julia indexes past its spectrum for, e.g., 65 or 1001); DGSM by
finite differences in probability; a one-input factorial; RSA's dummy spread
over all dummies; and δ's density of a tied class at the whole output's
bandwidth. Two things GlobalSensitivity.jl does not guard against are handled
by the caller rather than the port: *What drove it* reads δ on the output's
normal scores and mutual information on ranks, which leaves both unchanged and
keeps their estimators working on an output spanning thirty decades (on the
values, δ was 449,816). And its fractional factorial writes the levels into an
integer matrix, so a level of 0.2 is an `InexactError` there; the reference
case uses integer levels.

**Where it runs.** The worker's `gsa` message is `runDesign` with a design: the
coordinator builds the model once, as for a tornado, to learn the plan, sizes
the pool from the design's run count, and keeps the design for the analysis;
each slice draws the same design from the same seed. `gsa-table` reads the
runs for another output or reading. The page asks with `wantLabel` so the
answer arrives for the line on the chart.

## An empty dimension

A block indexed by a list with nothing enabled in it has **width zero**: no
slots, no values, nothing in the state vector. The first review made that a
`ValidationError` at the file gate, because the code generator walked an empty
array and threw `Cannot read properties of undefined` from inside itself,
naming nothing anybody could act on. Refusing it by name was better than
crashing.

It was still wrong, and the assessment models said so. model B has
five empty lists, four blocks carrying them -- `NearField.WPVolumeWaste`,
`NearField.WPVolumeMould` (parameters) and `NearField.PartsVolume`,
`NearField.WasteVolume` (expressions) -- and **not one of them is read by
anything**. They are waste types this calculation case does not have. Ecolego
runs that model; this tool refused it outright, over four blocks that hold
nothing and that nothing reads.

The fix is one line, in the one place per-index code is generated:

```js
function emitLoop(lines, space, dims, baseIndent, body) {
	if (!dims.length) { body([], '0', baseIndent); return; }
	if (dims.some((d) => space.size(d) === 0)) return;
	...
```

A loop over an empty dimension runs no iterations, so there is no code for it
to be. Generating the body anyway was the actual bug: a block of width zero has
no equations parsed for it either, so `a.asts[0]` was undefined.

What makes leaving it to the run safe is that **reaching into a block that
holds nothing is still refused**, by the rule that already governs reaching an
index you do not carry:

```
t: 'B' is indexed by 'L', which 't' is not indexed by and cannot reach.
```

A transfer into such a block, and an equation reading one, both stop there.
Only a flux wholly inside the empty dimension is silent, and that is a loop of
no iterations at both ends. `modelWarnings` says it in amber, on the block
rather than on the list, because a block that quietly holds nothing looks
exactly like one that is working.

## Differencing a Jacobian that has a pattern

A differenced Jacobian costs one evaluation of the model per column and, held
densely, `neq` squared numbers. At a few hundred states that is unremarkable.
At 16,244 it is fatal: three matrices of 264 million numbers each, and 16,244
evaluations of a 201,004-slot model, per Jacobian -- which is what model L
asked for the moment it first needed a differenced matrix, ten thousand years
into a hundred-thousand-year run, and the process died there every time,
inside a call that does not return.

The model already carries what is needed to avoid all of it. The analytic
Jacobian brings a **pattern**, so only `nnz` numbers are worth storing, and a
**colouring** of the columns -- groups within which no two columns share a
row -- so a whole group can be perturbed at once and separated afterwards by
which rows each column owns. The differencer in `ndf.js` uses both: for model
L that is 77,812 numbers and 54 evaluations in place of 792 million and
16,244. Checked against the dense routine on every bundled example that has an
analytic Jacobian, the two agree on every pattern entry.

Two guards sit beside it. A dense iteration matrix costs `8 · neq²` -- 2.1 GB
at 16,244 states -- so past a 256 MB budget it is not offered at all and the
solver says why instead of allocating until the tab dies. And a *singular
trial* factorisation does not condemn the sparse path for the whole run: the
trial is `I − 1e-3·J` at one instant, and a matrix that is singular there may
factorise perfectly well at every step the solver actually takes.

## The whole model, once per block

Unticking a checkbox in the Simulation panel took **321 ms** on a
600-compartment model, and the interface visibly rebuilt itself. The checkbox
was not the cause. Every edit cost that; a tick simply feels different from a
number field, because a tick should be instant.

A CPU profile of the click named it in one line:

```
  356 ms   45%  (idle)
  178 ms   23%  deriveBlockLists   indexlists.js:1001
   86 ms   11%  (program)
```

and the call path said why:

```
deriveBlockLists <- materialList <- materialDimensionName <- unitProblems
                 <- allUnitProblems <- modelWarnings <- rescanProblems
                 <- republish <- modelChanged
```

`allUnitProblems` calls `unitProblems` once per block. `unitProblems` asked for
the model's material dimension, which walks every index list -- and two of
those are *derived*, built fresh from every compartment and every transfer in
the model. So each of 1,350 blocks rebuilt a 1,200-entry list, and the whole
thing ran twice per edit: once for the warnings, once for the rail's info card.

**This is the second time.** The note on the parameter beside it says so:

> `known` is the set of every block's name, which the model-wide scan builds
> once and hands in: built here per block, it was the whole model walked once
> per block, and a second of every keystroke on a large one.

The same shape, through a different property. The fix is the same shape too --
`allUnitProblems` works the material dimension out once and hands it down.

| | scan of 300 blocks | of 1,200 |
|---|---|---|
| before | 18.0 ms | 100.5 ms |
| after | 4.0 ms | 13.8 ms |

and in the interface, on the 600-compartment model:

| | before | after |
|---|---|---|
| untick *Cannot go negative* | 321 ms | 120 ms |
| change *Rel. tolerance* | 261 ms | 110 ms |
| change a compartment's value | 190 ms | 96 ms |

**The test counts rather than times.** A ratio between two model sizes cannot
tell the two versions apart -- 3.5x against 5.6x over the same span, with too
much linear cost mixed in -- and a stopwatch measures the machine. But each
`indexLists()` reads `project.index_lists` exactly once, so a proxy over that
one key counts the rebuilds: **2 whatever the model's size** after the fix,
`2n + 2` before it, which on 400 compartments is 802 against 2. Nothing about
that depends on how fast anything runs.

**What was left was not the diagram.** Timed on the *Build* tab -- the earlier
figures were taken on the JSON tab, where the rail is not rendered at all
(`RAIL_TABS`), which hid the larger half -- an edit cost 206 ms, and a profile
attributed it:

```
  106 ms  renderRail        (of which 66 ms in draw, tree.js:78)
   80 ms  rescanProblems    (29 ms of it also in draw)
   24 ms  setProject        -- the diagram, the thing that looked expensive
```

The diagram was never the problem. The tree of every block in the model was,
and it was being built **twice for one edit**: `rescanProblems` ended with
`renderRail()`, and `republish` then called `renderEditorViews`, which calls it
again. Two changes, in that order:

- `rescanProblems({ rail: false })` from the edit path, since the render two
  lines below does it. The other two callers -- the JSON tab's Apply and
  opening a file -- scan *after* they render, because a model can arrive with
  something already wrong in it, and they keep the refresh. 206 ms to 125.
- `SOLVE_ONLY_SETTINGS`: `solver`, `rtol`, `abstol`, `non_negative`. An edit to
  one of those cannot move a block, a name, a value, a unit or a dimension, so
  the diagram, the matrix and the tree are already right and are not built
  again. The rail still is, because its info card shows the span and the
  solver. 125 ms to **31**.

| on a model of 1,350 blocks | before | after |
|---|---|---|
| untick *Cannot go negative* | 206 ms | **31 ms** |
| change *Rel. tolerance* | 217 ms | 25 ms |
| change a compartment's value | 207 ms | 115 ms |

The last row is the control: a value edit really can change what is drawn, so
it takes the whole path and gains only what the double render gave back.

**The list is deliberately four names long.** `time_unit` is a simulation
setting that re-derives every flux unit in the model; `scenario` changes which
value each indexed block reads; the span moves the saved-times warnings. Those
are edits to what is shown, whatever panel they are typed into. The test pins
both halves -- the four that are in, and five that must stay out.

What makes the skip safe rather than merely fast is that a simulation problem
is never about a block: `simulationProblems` returns `{key, message}` and
`marksByName` only marks what has a `where`. So a solver setting cannot change
a mark that the skipped views are the ones showing, and the test checks that
against the domain rather than asserting it.

Checked in a browser as well as timed: after a solver setting the tree still
holds its 240 rows and the diagram its 120 nodes, and after adding a
compartment both follow it -- 241 and 121, with the new block found in the
tree.


## Three passes, not one

The generated derivative used to be one straight line: work out every algebraic
block in dependency order, then assemble `out` from them. It is called two or
three times per step -- once for the predictor, once per Newton iteration --
and on the assessment models of one series almost none of what it recomputed had moved.

Counting what each block actually reaches, through its own emitted code and
then transitively through `readsAlg`:

| model | algebraic slots | constant | clock only | state |
|---|---|---|---|---|
| model A | 65,751 | 17,864 (27%) | 47,671 (73%) | **216** |
| model C | 128,479 | 5,359 (4%) | 122,904 (96%) | **216** |
| model L | 201,004 | 13,354 (7%) | 10,261 (5%) | 177,389 (88%) |

Two hundred and sixteen slots of sixty-five thousand depend on the state. The
rest is a function of time, and a stiff solver asks for the derivative
*repeatedly at one instant*: every Newton iteration of a step sits at the same
`t` with a different vector, and so does every colour of a differenced
Jacobian. All of it was being worked out again each time.

So the pass is emitted three times over instead of once:

- **once**, at the end of the build, for what reads neither the clock nor the
  state -- a transfer rate that is a parameter, an expression over parameters;
- **once per instant**, for what reads the clock (`ctx`, which covers `ctx.t`
  and `F.time.fn(ctx)` alike) or a lookup (`TAB[`, read at the clock), and
  nothing else;
- **every call**, for what reads the state (`y[`), a history (`MEM[`) or a
  far-field pathway (`FARF`) -- or anything that does.

The order matters and is free: a clock-only block can only read constant or
clock-only blocks, since reading a state-dependent one would make it
state-dependent, so running the three in that order keeps every block after the
ones it reads.

Measured, same machine, same process, the split switched off and on:

| model | steps | rejected | before | after | |
|---|---|---|---|---|---|
| model A | 838 | 43 | 28.0 s | 21.5 s | **1.30x** |
| model B | 1,375 | 167 | 52.3 s | 45.6 s | 1.15x |
| model C | 1,502 | 209 | 104.3 s | 87.8 s | 1.19x |
| model D | 1,466 | 148 | 160.6 s | 145.1 s | 1.11x |

**Every one takes the same steps and rejects the same steps**, and model A's
checksum over 8,131,752 state values is identical to the digit with the split
on and off. It is the same arithmetic in a different order of evaluation, not
an approximation.

**The first version of this was worth nothing, and the reason is worth
recording.** Sampling said 92% of model A's slots never move -- evaluated at three
times across the span and two perturbed states, they did not. But that is
"did not move at the five points tried", not "cannot move": a handful of
time-dependent switches (`switch_permafrost_pd`, `switch_transport`,
`Geosphere.travel_time`) are constant over much of the span and genuinely
time-dependent. The provable share is 27%, hoisting it measured 0.99x, and only
splitting the *moving* remainder by what it moves with found the 73%.

**A hazard that had to be found by asking what else writes `X`.** The tangent
shares it. `jvpSourceFor` works out each algebraic value and its derivative
together and writes the value into the same slot the derivative reads, so a
Jacobian evaluated at one instant leaves *its* numbers in the clock-only slots
while the cache goes on believing they hold the instant it filled them for.
Nothing about that is visible -- no error, no NaN, a wrong rate. With the
invalidation removed, `lookup-driver.json` gives -1,715,614 where it should
give -4,066,414. `jacobian.evaluate` is wrapped to invalidate, and a test fails
without it.

Three tests hold the whole thing up, because every part of it is the kind of
mistake that returns a plausible number rather than an error: that the constant
slots do not move under any clock or state, that the clock-only slots do not
move when only the state changes, and that a Jacobian at one instant does not
poison the derivative at another.

**What is left, and it is the larger half.** The Jacobian is the expensive call
-- 157.94 ms against 9.87 ms for a derivative, on model A -- and its tangent
recomputes the same algebra with the same structure, which is why model C gains
2.2x per derivative call and only 1.19x over a run. The same three-way split
applies to `jvpSourceFor` and has not been done.


## Solving a large model in sections

There is a second answer to a model too large to integrate in one piece, and it
is worth writing down what it is, because it is the obvious thing to reach for
next and it is not the right thing to build here.

**Batch solving.** Preparing a scenario cuts the states into
batches -- independently, or merging compartments, contaminants or decay
chains -- and the solve then runs the solver once per batch rather than once
for the model:

```
for each batch:
    map the batch's states onto the model's
    set up the solver
    solve
    mark the batch complete
```

There are two cuts, and the flag chooses between them. `independent` walks the
dependency graph a walk in both directions and merges anything mutually dependent, giving
batches that cannot see each other at all. With it off the walk is
a backward walk, the batches are sorted, and `backwardsReferences` is set: a
batch may read one solved before it, never one after. That second arrangement
is the downstream-only case, and the reading back is a recorder read, which
is a linear interpolation with a moving cursor:

```
between the two stored points either side of the time asked for,
take the straight line:   v0 + (t - t0)/(t1 - t0) * (v1 - v0)
```

Every batch therefore has its own solver times, which is why batch mode forces
the output grid -- the run sets `outputOption = OutputOption.SpecifiedOutput`
whenever it is on, and the validator says so out loud: in batch mode the
output option has to be *produce specified output only*. The documentation
names the rest of the price too -- batch simulation can cost accuracy.

**And what it costs.** The setting next to it, *Minimum time between stored
data points*, exists because of the interpolation:

> This setting is only used when one batch depends upon the data of a previous
> batch. In this case, data for all (by the solver) accepted time points is
> stored during the simulation until no longer required. For very stiff
> problems the memory footprint can become very large.

That is the same failure this tool had just spent a day removing, arriving by a
different road: a stiff model in downstream mode holds every accepted step of
every batch anything still needs.

**Whether it would help here.** Two things have to be true. The system has to
come apart, and the pieces have to want different step sizes -- if every piece
is as stiff as the whole, solving them one at a time is the same work in more
calls, plus the interpolation error.

The first is true, comfortably. Taking the analytic Jacobian's own pattern and
running Tarjan over it:

| model | states | independent parts (largest) | SCCs (largest) |
|---|---|---|---|
| model L | 16,244 | 68 (89.7%) | 3,990 (0.7%) |
| model A | 22,842 | 32 (18.5%) | 108 (1.8%) |
| model B | 23,436 | 32 (18.5%) | 486 (1.8%) |
| model C | 31,212 | 32 (18.5%) | 108 (1.3%) |
| model G | 50,490 | 2,624 (16.9%) | 4,482 (0.9%) |
| model F | 55,728 | 32 (18.5%) | 108 (1.1%) |

No strongly connected component is more than 2% of any model. In block
triangular form these are thousands of small blocks in a long chain, which is
exactly the shape the technique wants -- in its *downstream* form, which is the
one the corpus uses. The fully independent split is weaker: model L's largest
disconnected part is 89.7% of it, so cutting that model into pieces that cannot
see each other leaves one piece that is almost the whole model.

The second looked false, and the first measurement of it was the wrong
measurement. Scoring each state by the Jacobian's own diagonal -- `1/|J_jj|` is
its time constant -- says stiffness is spread right through these models: 77%
of model L's states and 100% of model C's sit in a component holding a state
faster than ten years against a hundred-thousand-year span. But a stiff solver
is built to swallow stiffness. What decides this is not which states are stiff,
it is **which states set the step size**, and the NDF solver picks it from an infinity
norm over states, so at every step exactly one state chose it. Instrumenting
that norm on model B:

- **262 states of 23,436 -- 1.1% -- ever set the step.** Half the steps were set
  by 26 of them.
- 424 of the 486 blocks never set it once, and they hold 72% of the model.

Those 17,000 states are being carried at a step chosen for somebody else. To
put a number on it, each block's share of the same error norm says what step
*it* would have needed, through the solver's own growth formula, and covering the run at that step costs it `1/ratio` of a step
each time:

| model | states | coupled | in SCC blocks | in independent parts |
|---|---|---|---|---|
| model A | 22,842 | 19.4M state-steps | 7.4M — **2.6×** | 10.1M — **1.9×** |
| model D | 33,048 | 51.2M | 12.3M — **4.2×** | 23.7M — **2.2×** |
| model B | 23,436 | 33.7M | 5.6M — **6.0×** | 9.8M — **3.4×** |
| model C | 31,212 | 49.6M | 6.0M — **8.3×** | 17.4M — **2.8×** |

Two to eight times less arithmetic, on a cost model where a step costs what its
states cost -- charging neither the restart per block, which favours the whole,
nor the superlinear factorisation, which favours the split. And it is an
extrapolation rather than a simulation: each block's error is read off the
*coupled* trajectory, and a block solved alone would wander somewhere slightly
different.

The last two columns are the two modes, and the gap between them is what the
interpolation buys. The independent split is exact -- the parts cannot see each
other, so there is nothing to interpolate -- and it still carries a third to
three quarters of the win.

**Reading the coupling.** A stored trace is read by drawing a straight line
between two stored points, and that is the weakest part of the arrangement
rather than a necessary cost of splitting. The solver chose the gap between
those points to keep a *fifth-order* local error near the tolerance, so the
gap is long wherever the solution is smooth, and a chord across it answers to
`h^2 y''` and to nothing the tolerance controls. Measured against the difference-table
interpolant the NDF solver already uses for its own output and for locating
events:

| model | worst chord error | values off by more than `rtol` |
|---|---|---|
| model A | 2.1% | 10.4% |
| model B | 2.2% | 6.4% |
| model C | 2.0% | 6.4% |

One value in ten to one in sixteen is wrong by more than the tolerance the run
is working to, and the worst is twenty times it -- in all three models within a
hundred years of a start that runs to 102,000, which is where the transient is
and where blocks would be handing each other their fastest-moving values. So
the coupling must be read through the solver's continuous extension, not off
stored points. Every solver here already has one and already hands it around:
the difference-table interpolant in `ndf.js`, the free interpolant in
`dormand-prince.js` and the quadratic in `rosenbrock23.js`, all three passed
to `locateCrossing` as `denseAt`.

That also retires the constraint the whole technique is usually sold with. A
stored trace can only be read where it was stored, which is why Ecolego forces
the specified-times output option and asks the user to pin the output times; an
interpolant can be evaluated anywhere, so a downstream block queries its inputs
at whatever times its own stepping lands on and nobody has to pin anything.
What it costs instead is memory: a chord keeps one vector per step, the
interpolant needs `ynew`, `h`, `k` and `dif[0..k-1]` -- six at order five. The
answer to that is not to store the trajectory at all but to pull the upstream
solve forward on demand, which the per-step `onAccepted` hook already makes
possible.

**What the corpus asks for.** All eleven assessments of one series and both L-series models
files ship with `<batch-mode>true</batch-mode>`, and every one of them has
`<batch-independent-only>false</batch-independent-only>`; only model L sets
`<batch-decay-chains>true</batch-decay-chains>`. So the models do use this --
in its downstream-with-interpolation form, on the machine Ecolego runs on,
against a native UMFPACK solver.

**And then the cost model turned out to be measuring the wrong half.**

Everything above charges a step by the states it carries. That is wrong here,
and timing one step says so:

| | states | algebraic slots | `dydt` | Jacobian | sparse LU |
|---|---|---|---|---|---|
| model A, whole | 22,842 | 65,751 | **9.87 ms** | 157.94 ms | 3.86 ms |
| its largest part | 4,230 | 26,767 | 2.80 ms | 41.98 ms | 1.22 ms |
| its smallest part | 423 | 18,793 | 1.06 ms | 10.40 ms | 0.04 ms |

The factorisation is not the expensive thing -- the derivative is, by 2.6 to
one -- and the derivative barely shrinks with the part. The smallest part holds
**1.9% of the states and costs 10.7% of a full derivative call**, because every
part contains all 423 compartments and needs all 881 transfer rates; only the
nuclide dimension narrows. Built all 32 ways, the states divide perfectly and
the algebra does not:

```
states:          22,842 over the parts against 22,842 whole   (1.00x)
algebraic slots: 620,868 over the parts against 65,751 whole  (9.44x)
```

Against 848 coupled steps and 12,177 summed over the parts, splitting model A as
it stands would run it **between 1.2x and 2.7x slower**, not 1.9x faster. The
state-steps were real; they were not what a step costs.

**What is actually worth doing is underneath both of them.** The algebra is
51% of a derivative call on model A and 59% on model C -- and most of it never
changes. Evaluating it at three times across the span and at two perturbed
states, and counting the slots that never moved:

| model | states | algebraic slots | never move |
|---|---|---|---|
| model A | 22,842 | 65,751 | **60,606 (92%)** |
| model C | 31,212 | 128,479 | 74,885 (58%) |
| model L | 16,244 | 201,004 | 133,563 (66%) |

Sixty thousand numbers worked out afresh on every one of two or three calls a
step, for eight hundred steps, each time giving what they gave before. That
observation went somewhere -- see *Three passes, not one*, which is built -- but
it did not rescue this. Most of that algebra turned out to be clock-dependent
rather than constant, and a part solved on its own steps at its own instants
recomputes its share at every one of them. The 9.44x duplication is a duplication
of work that has to happen somewhere; splitting the model multiplies the number
of instants it happens at.

**So this is not built, and on these models it should not be.** The partition
itself is -- `src/sim/partition.js`, which declines a model whose couplings it
cannot see rather than splitting one it should not. A part also builds as a
project in its own right with no new code generator: switch off the materials
that are not its, and `buildSystem` returns a system whose derivative matches
the whole model's on that part's states to **zero** relative difference, checked
on all 4,230 states of model A's ten-nuclide chain. Both are kept because they were
measured to be right and because the question will be asked again. What is
missing is a model where the sums come out the other way -- one whose cost sits
in the factorisation rather than the derivative, which is what the state-step
saving is a saving of.

## Solving the parts at once

The section above measured splitting as a way to do *less arithmetic*, and it
does not: a part's derivative costs far more than its share of the states,
because the algebra is not per material. That was the question for one core.
On several, what a run costs is the time until its **slowest** part is in, and
the parts' extra arithmetic is spent on cores that were idle. Model A's
largest part is 18.5% of its states and 28% of a derivative call: with a core
per part the run waits on about a quarter of the whole model's work per step,
plus a build per part. So the split is built after all -- `src/sim/split.js`,
decided per run by a setting, `simulation.split` (auto, always, never).

**The coordinator builds the whole model**, as it must: the parts are read off
its Jacobian, and its system is what every series is worked out from after the
solve. `splitJobs` turns the partition into *jobs*, sets of materials, because
a part is built by switching every other material off: parts that share a
material are merged, and a part with no material at all rides with the smallest
job, since switching materials off does not remove it -- it is in every job's
build and is taken from one. Each job goes to a worker as the model's text and
a list of materials; the worker switches the others off (`partModel`), builds,
solves on the output grid, and sends its states back named (`stateKeys`: block,
index, and for a far field the cell). `assembleParts` files every state from
the job that owns it into the whole model's vector, and the result is a
`Results` of the whole model's own system -- nothing downstream knows it was
split. The check above, that a part's derivative is the whole model's on its
states to zero difference, is now a test, on every job of the bundled
four-nuclide model.

**Two things the real models taught it.** An equation may pin a material by
name -- a coefficient read at carbon-14 for every nuclide, `k[C-14]` -- and a
job with carbon-14 switched off does not build. The pin is safe to honour -- what it reads cannot
depend on a state, or the two jobs would be one part -- so `buildPart` switches
the pinned material back on in that job's build and tries again; its states are
integrated there for nothing and not kept. And switching off the only isotope
of an element dropped the element from the derived list, so an entry keyed by
it named an index the list did not have and the model refused to load -- which
switching that isotope off in the Index lists tab did too, before any of this.
`deriveElements` now keeps such an element, switched off, and its entries lie
dormant like any other switched-off index's.

**Refused, whatever the setting**, where the partition cannot be trusted (a
delay, a snapshot or an event, as above), where the output is the solver's own
steps (every part's differ), for the SciPy solvers, for one core, and where
nested workers are not available. **Refused after the fact** -- solved whole
instead, and the log says why -- when the parts come back on different times
(a part whose blocks carry a switch time the others do not) or a state is not
carried by any part. A disruptive event's jumps are not in the Jacobian, and
need not be: a jump moves a share of a state into the same index of another
block, or a package failure into the block the release is already transferred
to, so it joins nothing the derivative does not.

**Auto** predicts with the measured shape of the cost: a job pays `0.12 +
0.88 × its share of the states` of a whole derivative call and of a whole build,
jobs are packed onto the cores largest first, and each worker costs a start.
What it assumes -- that the largest part needs every step the whole model takes
-- is the pessimistic end: a part answers to its own states, and on the
assessments it has been measured on it needed markedly fewer, so splits ran
well ahead of the prediction. The thresholds reflect that: from 2,000 states and
a 1.6× promise before a model has been timed, 1.2× and a 1.5 s solve after, and
once a model has been split what the split measured decides (`splitMemory` in
the worker, per layout signature). The parts agree with a whole solve to
within the tolerance, not to the last digit, so the setting is in the
integration fingerprint.

## A global switch over the floor

Every compartment carries *cannot go negative*, and until now that was the
only say anybody had over it: three thousand blocks, three thousand flags. A
project file carries a switch above them, read before any compartment is
looked at:

```
if the model-level saturation setting is off:
    no compartment gets a floor at all
```

Null, and the solver is handed nothing: no state is held however each one is
set. That is `simulation.non_negative` here, and `runner.js` reads it in the
same place and to the same effect.

**Two deliberate differences.** A file calls it *Enable saturation* and
defaults it to false, because there it gates a whole upper-and-lower band that
clips the value to either bound. This tool carries only the floor of that (see
*No saturation band, only a floor* under *Known limitations*), so the switch is
named for the thing it switches, and it defaults to **on**, which is what every
model here already did. Defaulting it
off would silently unclamp every existing model.

**What it is not is a bulk edit.** The per-compartment flags are left exactly
as they are and simply not consulted while the switch is off, so turning it
back on restores what the model said rather than whatever was last edited. A
test checks that on the model rather than on the result, since a rewrite is
precisely what would not show up in a number.

**It changes how one corpus model runs, and that is the point.** Reading
`<saturation-enabled>` on import, eleven of the twelve real assessments have it
true and model L has it false -- so Ecolego runs model L with
no floor at all, while this tool clamped it. That clamp is not a detail: it is
what `ndf.js` bypasses the analytic Jacobian for, and the reason that model
spent a day out of memory (see *Differencing a Jacobian that has a pattern*).
Running it as its author saved it was always the right behaviour; it took
reading the setting to notice. The import says so out loud, because turning a
constraint off for a whole model is not something to do quietly.


## A spread on something that is not a parameter

**A distribution belongs to a parameter**, and not by accident. A probabilistic
run varies inputs, reports which of them drove the spread, ranks them in a
tornado and differentiates against them, and every one of those wants the same
thing: a named quantity with one value per realisation. `layout.parameters` is
that list, and `distributedSlots`, the sensitivity measures and `dy/dp` all read
it.

But most of a model's numbers are not parameters. A waste package's
characteristic life, an event's rate, a far-field path's travel time, a
compartment's initial inventory — each is an *equation* on its own block, and an
equation has nowhere to keep a distribution and no slot for the sampler to write
into.

So `src/domain/uncertainty.js` makes one. Asking for a spread on a setting
creates a parameter holding the value the setting had, points the setting at it
by name, and hands the parameter back for the distribution to go on:

```
makeUncertain(project, block, 'fail_scale')
    fail_scale: "20000"      ->   fail_scale: "Canisters_fail_scale"
                                  parameters += { name, value: "20000", index_lists: [] }
```

Nothing downstream changes, because afterwards there is nothing to handle: it is
a parameter like any other, and it reaches the probabilistic dialog, *what drove
the spread*, the tornado and `dy/dp` with no new case anywhere. It also makes
the model say what it means — a canister life that varies *is* a parameter of
the assessment, and giving it a name is what lets a tornado bar carry a label.

Four things the module settles:

- **The parameter carries no index list.** `addParameter` gives a new parameter
  the model's default dimensions, which in a nuclide-indexed model is the
  radionuclide list — and a canister life is one number however many nuclides
  are in the packages. So `index_lists` is set empty. The control is therefore
  offered on a setting that holds one value, and on a per-nuclide setting only
  when the model has no nuclide dimension at all.
- **A reference is found, not wrapped.** `parameterBehind` resolves a bare name
  the way an equation would — through `resolveReference`, so a name inside a
  sub-system means the nearer block of that name — and returns it only if it is
  a parameter. That is what makes the control reversible: opening it again edits
  the distribution that is there rather than making a second parameter.
- **An expression is refused.** A setting has to be a plain number, a blank, or
  a reference to one parameter. `2 * canister_life` would have to be thrown away
  to be replaced, so the caller is told why instead.
- **Clearing leaves the model as it found it.** The distribution goes; the
  parameter goes only if this setting is the one thing that reads it, checked
  through `referencesTo`. A parameter somebody wired up themselves is theirs.

**The mode selectors are excluded by name.** `UNCERTAIN_EXCLUDES` holds
`failure` and `timing`: a Weibull failure and a Poisson process are already
distributions, over the packages and over the occurrences within one run. They
are choices rather than numbers, and a second distribution over one would be a
different quantity. Naming them in one place is what keeps the panels agreeing
about it.

The interface half is `uncertain: true` on `equationField` in
`src/ui/inspector.js`, which puts the box and a **±** button in one cell and
writes the distribution and the parameter's name under it. The parameter is made
only when a distribution is saved, so opening the editor and pressing Escape
leaves the model untouched.

## Reading a distribution

Every parameter entry in Ecolego may carry the distribution its value was
drawn from, and this tool used to count them and throw them away:

```
'TIA' has a probability distribution; this tool is deterministic and uses
its constant value.
```

Thirty-one to forty-seven of those per assessment model, and the information was in
the file all along. They are now read, kept per index, shown, edited against a
chart and written back as Ecolego spells them. Nothing samples them: a run here
is still deterministic and still uses the value beside the distribution. What
has changed is that a model no longer loses them by passing through.

**The file says it twice, and only one of them is enough.**

```xml
<entry type="parameter" index="Construction&#95;concrete">
  <value><![CDATA[1.0E-11]]></value>
  <pdf function="logt">
    <pdf-value><![CDATA[logt(min=7.0E-12,max=5.0E-11,mode=1.0E-11)]]></pdf-value>
  </pdf>
</entry>
```

The expression names the *family* and the attribute names the *class*, and
three parameterisations of the log-normal share one spelling:

| `function=` | expression | what the numbers are |
|---|---|---|
| `Logn4` | `logn(gm=, gsd=)` | geometric mean and geometric SD |
| `logn` | `logn(mean=, sd=)` | arithmetic mean and SD |
| `logn5` | `logn(p1=, x1=, p2=, x2=)` | two quantiles to fit through |

Read off the expression alone a `Logn4` is taken for a `logn` and drawn with
the wrong shape, so the attribute is the kind and the argument names are the
fallback for a file that has none. Over the corpus the two agree in all 17,746
distributions -- but they agree because the attribute is right, not because the
expression is sufficient.

**Every density matches what a file means by it.** `Logt` is the one worth spelling out, since
"log-triangular" could mean two things and this is which:

```
a < x <= c :   (1/x) * 2*(ln x - ln a) / ((ln c - ln a)(ln b - ln a))
c < x <= b :   (1/x) * 2*(ln b - ln x) / ((ln b - ln c)(ln b - ln a))
```

-- a triangle in `ln x` carried back by the `1/x`. `Logn4` is the geometric
parameterisation written out, `Logu` is `1/(x*(ln b - ln a))`, and `Triang`
guards its degenerate ends rather than dividing by zero at them, which is why
a mode outside the range draws a ramp cut at the maximum instead of nothing.
The tests check each at a point against these formulas rather than against a
textbook that might differ, and check that every curve encloses one unit of
probability -- the property that catches a density written with the wrong
constant.

`dtriang` and `logdt` are not a file format's but skbrnt's (`samp_util.Dtriang`
and `Logdt`, the second being the first in `ln x`), which is where SKB's SFK
data sets take them from. They are spelled as skbrnt spells them,
`dtriang(min=, max=, mode=)` with skbrnt's `a`, `b` and `m`:

```
a < x <= c :   (x - a) / (c - a)^2
c < x <= b :   (b - x) / (b - c)^2
```

-- two right triangles, each holding half the probability however wide it is,
and `logdt` is the same in `ln x` carried back by the `1/x`. So the mode is
always the median, the quantile splits at 1/2, and the density steps at the
mode unless the mode is the middle of the range (the geometric middle for
`logdt`). A mode at an end is allowed, as in skbrnt, and puts half of every
sample on that end; `pdfProblems` says so, since a release fraction whose best
estimate is its maximum is written exactly that way. The tests pin the CDF, the
quantile and the truncated draws of both to skbrnt's own numbers.

**A distribution may be declared and not filled in.** `logn(gm,gsd)` -- the
argument names with no values -- appears 11 times in the corpus, and 994 more
carry a truncation and no shape. Ecolego writes those when the kind has been
chosen and the numbers have not. They are not errors, they are not discarded,
`complete()` is false for them, and `formatPDF` writes them back exactly as
they came. Nor are they reported as problems while one is being edited: a
distribution passes through every half-finished state on the way to a finished
one, and a field that complains at each of them cannot be typed into.

**Checked against all of it.** 17,746 distributions across 25 archives: every
one parses, every one returns from `formatPDF` byte-identical to what the file
held, and every drawable curve integrates to 1. On model B that is
29 on parameters and 615 per index, in five kinds, surviving a save and a
re-read.

**Where it stops.** `pg` -- a list of pre-sampled values, and 14,306 of the
17,746 -- is stored and drawn as a histogram, and the position cursor Ecolego
keeps with it (`inorder`, `pos`) is round-tripped and otherwise unused. What
would use all of this is probabilistic simulation, which is item 4 on the order
of work and is not built. This is the half of it that a deterministic run can
honestly do: the model keeps what it was given.


## Sampling a model

With the distributions read, running over them is mostly arithmetic and one
structural decision.

**Build once, integrate many times.** The expensive half of a run is the build
-- a minute on model G -- and none of it depends on a parameter's
*value*: the layout, the generated derivative, the sparsity pattern and its
colouring are all structure. So `runProbabilistic` builds once and each
realisation rewrites `P`, which the generated code holds and reads live. Two
things are not live and are redone per realisation:

- `system.evaluateInvariant()`. The algebra that reads neither the clock nor
  the state is worked out at build time *from the parameters* and left in `X`
  -- see *Three passes, not one*. Rewriting `P` without re-running it leaves
  the previous realisation's transfer rates in place, which is a wrong answer
  that looks entirely plausible. `run()` grew a `system` option for this, and
  that option is the only way the two files meet.
- `system.initialState()`, since an initial inventory may be an equation over
  parameters.

**A slot per index, which is a trap worth naming.** `distributedSlots` walks the
layout rather than the block list, so a parameter indexed by four nuclides
becomes four slots and each is drawn independently. That is right for a leach
rate and wrong for the bulk density of the soil -- and in this tool every
parameter in a model with a nuclide list is per nuclide *unless it says
otherwise*, which is the rule a file's contaminant catalogue follows too.

The consequence only shows up once you sample. `examples/biosphere.json` leaches
its soil at `soilLeach / (1 + Kd*rho/porosity)`, the textbook retardation
factor, in which `Kd` is per nuclide and `rho` and `porosity` are properties of
one soil. Left implicit, a realisation drew `rho` four times and handed the four
nuclides four different soils inside the same formula -- physically impossible,
and it dilutes every correlation the sensitivity then reports. Marking the seven
genuinely scalar parameters `per_nuclide: false` took the model from 40
parameter slots to 19 and the sample from 36 draws to 15, with the deterministic
checksum unchanged to the last digit, since all four slots had held the same
number anyway. The test asserts the widths, because nothing else would notice.

**One run id, two meanings.** The page keeps a single `state.runId`, bumped by
every run it starts, and the worker's replies were matched against it with one
comparison at the top of `onmessage`. That is right for everything a run
reports -- progress, results, an error from an abandoned run is noise -- and
wrong for exactly one message.

A `columns` reply is not part of the run in flight. Series are left in the
worker until something asks for them, and they are asked for under the id of
the run *that produced the results on screen*. A probabilistic run takes the
next id, so from that moment the two ids differ, and the reply was dropped on
arrival:

```
to worker:    columns  id 1  (36 indices)
from worker:  columns  id 1  (36 indices)     <- answered
page:         1 !== 2, dropped
```

The indices stay in `r.asked`, which is what stops a column being requested
twice, so nothing asked again either. `downloadHDF5` printed *Working out 59
series…* and then waited on a promise that could no longer be resolved. From
the outside: the export did nothing, for ever, in silence. The same held for
CSV, and for any export after a `dy/dp` run, which takes an id the same way.

`messageIsCurrent` names the rule instead of repeating the comparison, and
`acceptColumns` does the matching that is actually right -- against the results
the columns belong to. The second half of the fix is that a batch dropped
before it is sent now unmarks its indices, so this class of failure cannot
strand a column permanently by any other route.

**What an export leaves out, and the one that does not.** The ordinary export
writes `state.results`, the deterministic run, while the chart draws the median
of the realisations over it -- the file and the picture disagree, and nothing
said so, which is the quiet version of the same disappointment. So that notice
now ends *"These are the deterministic values, not the realisations."*, and
beside it there is now an export that writes the sample itself.

## Writing the sample

**The format is Ecolego's, and it is not a set of quantiles.** The tempting
shape -- `q05`, `q50`, `q95` datasets beside each series -- would have been
this tool inventing a convention. The result browser at kvotab.se already reads
probabilistic files, and what it reads is the runs: a series becomes a matrix of
one row per output time and one column per realisation, marked
`probabilistic=TRUE`, with `n_iter` at the root. It derives the mean and the
confidence band from that itself, and can overlay a single iteration -- none of
which is possible from stored quantiles. So the file holds the sample and
nothing derived from it.

Three details, each of which would produce a file that opens and is wrong.

**The matrix is transposed on the way out.** A run holds its values one
realisation at a time, `values[i * times + j]`, which is the order they are
produced in and the order every statistic reads them in. The file stores the
same numbers one *time* at a time with the realisations varying fastest,
`flat[j * iterations + i]` -- `getRealizationStride` in the browser's
`rb-utils.js` is explicit that "realizations are the fastest-varying index".
Written the other way round the file still opens and still draws, with every
realisation a slice across time and every time a slice across realisations, and
no amount of looking at the chart would reveal it. Hence `timeMajor`, which is a
named function in `probabilistic.js` rather than a loop in the worker, and has a
test that reads it back both ways.

**`/time` stays one-dimensional and `probabilistic=FALSE` even here.** That
attribute on `/time` answers a different question -- whether each realisation
had its *own* time grid, which is what an adaptive-output run produces and what
`getProbabilisticTimeMatrix` unpacks. Every realisation in this tool is reported
on the one output grid, so one row of times serves all of them. Two attributes,
two questions, answered separately.

**The matrix is float32.** It is `iterations` times the size of the series --
a thousand runs over four hundred times is 1.6 MB per series in single precision
and 3.2 in double -- and the values are a Monte Carlo sample whose own error
after a thousand draws is a few percent. Seven significant figures is already
far more than the sample means. Ecolego writes its own series as float32 for the
same reason. The narrowing and the transpose both happen in the worker, before
the copy crosses to the page, because doing either afterwards means holding both.

**Three things a file can hold, and the file says which.** The picker asks --
the deterministic run, the mean of the realisations, all of them, or one by
number -- rather than assuming, because for a skewed quantity the answers are
nowhere near each other. On `biosphere.json` the mean of a thousand doses ends
the run at 3.67e-7 Sv/year against the deterministic 4.54e-9, a factor of 81:
the average of a lognormal-ish sample sits far above the curve at the central
parameter values. Two files that looked identical and disagreed by two orders of
magnitude would be worse than no export at all, so a derived file carries
`realisation` (`'mean'`, or the number) and `n_iter`, and a deterministic one
carries neither.

The mean and the single realisation are computed **in the worker**, not on the
page. The mean of fifty series over a thousand realisations is fifty columns of
four hundred numbers; the matrix behind it is fifty thousand. Sending the matrix
so the page could average it would move a thousand times what the answer weighs.
A single realisation is a slice of the values the run already holds, which is
why the test asserts that column `k` of the transposed matrix and the slice for
realisation `k` are the same numbers -- a file labelled *realisation 7* holding
some other run is a mistake no inspection of the file could find, since every
column is a plausible run.

The writer grew two-dimensional datasets for this: `dataset(data, dt, attrs,
dims)`, with the values still flat -- which is how HDF5 stores them anyway -- and
`dims` saying how to read them. It refuses a shape whose product is not the
number of values given, since that is a mistake with no safe reading.

## One panel, not two

The left panel listed every compartment, transfer, parameter and expression
with an editable value beside each; a second panel on the right -- beside the
diagram and the matrix only -- held the tree of the model and the reading view
of what was selected. A model of any size therefore had its blocks in two
places at once, in two orders, in two columns, and the middle of the window got
what was left of 1,500 pixels after 290 and 310 were taken off it.

They are one column now: `Model`, `Simulation`, then the tree and the
Information view. The middle is 1,164 pixels where it was about 850 on the two
tabs that had both.

**The move itself was markup.** Everything in the old rail is addressed by id --
`#picked`, `#search`, `#blocklist`, `#info` -- so `renderRail`, the tree and the
Information card needed no change at all: the elements were cut out of
`<aside id="rail">` and pasted into `<aside id="sidebar">`. Three things did
need care.

`renderSidebar` replaced the children of `#sidebar`, which would have destroyed
the tree on every keystroke. The panel has two parts now: `#sb-top`, which that
function rebuilds, and the tree and reading view below it, which it does not
touch. Rebuilding three thousand tree rows on every keystroke is the thing that
division exists to avoid.

The tree/Information divider writes its shares as custom properties on the
element those two are children of, so `applySplit` had to move from `#rail` to
`#sidebar`.

And the height had to be shared. `#sidebar` is a flex column: `#sb-top` takes
the height it needs, capped at 42% so a model with every section open cannot
leave the tree two rows tall, and the tree and the Information view divide what
is left. Folding `Simulation` gives its 228 pixels straight to them.

**What went with the lists.** The panel's own search, the per-index disclosure,
the start-value column, the distribution button on a parameter row, `BULK_ROWS`,
`ROW_CAP` and about 22,000 characters of `app.js`. Nothing is lost that had only
one route: a distribution is still reached from the settings dialog (twice --
the block's default and one index's), and a block is still added by right-
clicking the canvas, which `graph.js` has always offered for all four kinds.
What *is* lost is editing a value without opening the block, which is what the
lists were for; that is the trade the arrangement makes.

## Not solving again

`Results` keeps the trajectory and nothing else: every expression, flux and
parameter series is computed from `(t, y)` when something asks for it. That was
done for memory -- a run of 831,314 series is not a thing to hold -- and it
turns out to buy something else. An edit that cannot move `y(t)` needs the
system rebuilt, because the generated code has changed, and needs no step taken.

**The test is over what the integration reads.** `integratingBlocks` walks
forward from the roots -- every compartment's initial value and `dy/dt`, every
transfer and source rate, every far-field setting -- and closes over the
references, which is `referencesToAny` read the other way. On
`examples/biosphere.json` that puts the four compartments, the four transfers
and the seven parameters feeding the rates inside, and leaves `Dose`,
`WellConc`, `doseCoeff`, `intake` and `wellVolume` out. The kind of block
decides nothing: `intake` and `soilLeach` are both parameters and only one of
them is in.

`integrationFingerprint` is that set's contents plus the settings a trajectory
is a function of. Conservative in the one direction that matters -- anything it
cannot rule out is included, so an edit that changes nothing may still cost a
solve, which is what every edit costs today. The other error would leave a
wrong curve on the screen looking like a right one.

**A model that remembers is never reusable**, and this is the part that had to
be measured rather than reasoned about. A peak dose, a mean from a given year, a
value a century ago: each is accumulated *during* the integration into a history
the system carries, and `Results` reads those back when asked. A system built
fresh and handed somebody else's trajectory has never run and remembers nothing.
On `examples/recorders.json`:

```
output                        solved         reused   agree?
Peak_dose [Cs-137]      0.000573159   6.3532011330    NO
Mean_dose_after         6.034404303   6.3532011330    NO
Dose_a_century_ago      4.671663325              0    NO
```

Every one of those is a plausible number and nothing downstream would have
caught it. Refused rather than worked around: carrying the histories across
would mean proving the new system's memory layout matches the old one's, which
is the same proof as the state layout and a good deal less obvious.

**What it is worth, measured.** On model A the build is 537 ms and the
solve 15,296 ms, so skipping the solve is 97% of the wall clock -- and deciding
whether it can be skipped takes 30 ms over 1,413 blocks. What it reaches is
another question, and the corpus answers it honestly:

```
model     blocks   integrating   free
model A        1413          1401     12
model F     5294          5127    167
model E     2619          2584     35
...
across the eleven: 412 of 24,877 blocks
```

A near-field transport model is nearly all integration: 1.7% of its blocks sit
outside. `examples/biosphere.json`, which runs a repository through to a dose,
has five of twenty outside -- the post-processing tail is where the free blocks
are, and a model whose subject *is* the transport has hardly any. Adding is the
case that is free whatever the model, since a new expression or parameter is by
construction read by nothing.

**Refused twice, from both sides.** The page's test is over the model text; the
worker's is over what the model actually *built into* -- `stateSignature`, and
the memory array. They can disagree: an edit that changes no equation the
integration reads can still change how many states there are, through an index
list a sub-system turns on. The worker's answer decides, and a refusal costs one
build, thrown away, and then the run that was going to happen anyway.

## Warnings under a problem

The strip lists the model's problems, and its warnings under them. It did not:
warnings were dropped whenever `state.problems.length`, while the comment three
lines above said they were listed *"under the problems when there are any"* --
and the test pinned the code rather than the comment.

What that cost was the ⚠ button. A model with both showed it, since warnings
existed and were put away; clicking it set the switch, listed no warnings, and
then hid the button too, because the warnings were no longer put away. Two of
the three things on screen changed and the one that was asked for did not.

`Hide` moved with them: keyed to `!all.length`, a list showing both offered no
way to put the warnings away again until the error was fixed. It is keyed to
the warnings now, which is all it has ever hidden. The heading says what else is
in the list, since its own count is of problems -- nine rows under a heading
that says three owes the other six.

## Handing the file over

The reader already had a protocol for this -- `resources/js/rb-handoff.js` in
the kvotab repository -- so `src/ui/handoff.js` is the other half of it and not
a new invention. A tab is opened at `rb.html#handoff=<our origin>`, it announces
itself with `rb-ready` once its listener is installed, the bytes cross as a
transferred `ArrayBuffer`, and it answers `rb-opened` or `rb-error`. Nothing
touches the disk.

**The window is opened before the file exists**, which is the only order that
works. A pop-up is allowed out of a user gesture and not out of a promise that
settles after one, and building a result -- fetching realisation matrices from
the worker, writing the tree -- takes seconds. So the click opens the tab and
returns something to send *to*, and `send` waits for `rb-ready` itself. Every
path that gives up afterwards calls `cancel`, or the tab would sit waiting for a
file that is not coming.

**The bytes are transferred, not cloned.** `writeHDF5` returns a `Uint8Array`
over an exactly-sized buffer, so it goes in the transfer list; a structured
clone of a realisation matrix would be a second copy of hundreds of megabytes on
a page already holding the first. The test asserts the transfer list holds the
same buffer that is in the message, because a copy would work and would only
show up as memory.

**What the reader still needs**: its allow-list, `RB_HANDOFF_ALLOWED_ORIGINS`,
is same-origin by default, so the producing page's origin has to be added there.
Nothing on this side can change that, and the refusal is deliberately quiet --
the reader logs to its own console and ignores the message -- so `send` gives up
after a timeout and says what is likely wrong rather than waiting for a reply
that will never arrive. `?rb=<address>` points this at another copy of the
reader, which is how it was tested.

Checked by writing a real file from the browser and opening it in the browser it
is for: the tree opens, `/Dose` expands to its four nuclides, the confidence-band
control appears -- it only appears when the browser recognises probabilistic data
-- and the line it draws is the mean of the realisations, matching what `h5py`
computes from the same file to float32 precision:

```
mean of the last row  : 3.5926859709e-07
browser drew (last)   : 3.592686072742252e-07
```

**The feature was complete and unreachable.** The panel offers *Probabilistic…*
only where `hasDistributions` is true, and not one bundled example carried a
distribution -- so every part of this worked and nobody could get to it from a
fresh start. Giving `biosphere.json` a realistic set is what closed that, and a
test now asserts an example exists that can be run probabilistically at all.


**Every draw is an inverse CDF**, never a sampler of its own. That one decision
buys three things: a run is a function of its seed alone, so a result is
reproducible and therefore quotable; truncation is the same curve read between
`F(lo)` and `F(hi)`, where rejection sampling would have no bound on how long
it takes and real files truncate a distribution into its own tail; and Latin
hypercube becomes a statement about the uniforms rather than about the shapes.

Checked against an exact answer rather than against itself. One compartment
decaying at a log-uniform rate has `A(t) = exp(-k t)`, and the transformation
is monotone, so the q-th quantile of `A` is `exp(-t * the (1-q)-th quantile of
k)`:

```
   t      5%        50%       95%      exact 5%   exact 50%  exact 95%
  50  0.011889  0.205757  0.569088   0.011606   0.205741   0.570633
```

400 realisations, median agreeing to five figures and the tails inside sampling
error. The sampler is also checked against the *density* in `pdf.js` -- two
formulas written from different sources, agreeing to 0.7% over 40,000 draws.

**What is kept, and what is refused.** A thousand realisations of `model G` would
be 831,314 series by 356 times by 1,000, which is 2.4 terabytes. So a run keeps
the series it is asked for -- the model's endpoints by default, where it has
them -- and for those keeps every realisation, because quantiles need them.
What that costs is said before it is spent and refused past a gigabyte rather
than attempted.

**What the model says, and what it is not allowed to do.** Ecolego's
`<probabilistic-settings>` carries `no-simulations`, `sampling` and `seed`, and
all three corpus models that have them say 1000, Latin hypercube and a seed.
Those are read. They deliberately do **not** make Run probabilistic: a file
saying 1000 must not turn one press into a thousand integrations of a
23,436-state model, so a probabilistic run is started from its own dialog and
the file's numbers are that dialog's defaults. model L also
names 427 `<selected-parameter>`s, and those are honoured -- 426 of its 626
distributed values are sampled and the rest keep their numbers.

**Not supported: correlated sampling.** An assessment often ties parameters
together -- model B correlates 210 pairs and model G more -- and
this draws each independently, so its spread is wider than Ecolego's. The
import says so rather than letting the difference pass unremarked. Doing it
properly means a Cholesky factor of the correlation matrix over the normal
scores, which is a day's work and a different one.


## Which inputs the answer depends on

"Sensitivity" names two different things, and it was worth finding out which
one Ecolego means before building either. Its default method is not a
derivative at all:

> **Probabilistic.** A Monte Carlo sample is generated using the linear
> congruent method. This common method is used to estimate a number of
> statistics: 1. Pearson product moment correlation 2. Spearman coefficient
> 3. Standardized Regression Coefficient (SRC) 4. Partial Correlation
> Coefficient (PCC) 5. Standardized Rank Regression Coefficient (SRRC)
> 6. Partial Rank Correlation Coefficient (PRCC) 7. First Order Sensitivity
> Index

-- computed from the sample a probabilistic run has already drawn, and shown as
a ranked table and as *correlation rank coefficients over time*. So this is
built on the run rather than beside it: `runProbabilistic` keeps the values it
drew, and the analysis is a pass over them.

**Pearson and Spearman are here; the other five are not.** The reason is cost
rather than difficulty. A correlation is a dot product. SRC, PCC, SRRC and PRCC
are all one multiple regression of the output on *every* input at once, and
model B samples 617 values -- a 617-wide least squares at each of
356 output times, for each series. A first-order index from a plain random
sample needs binning or a second sample designed for it. Those are a separate
piece of work.

The two that are here answer the question the others refine. **Spearman finds
any monotone relationship, Pearson only a straight one**, and the table ranks by
Spearman because monotone-and-bent is the normal case: a log-triangular sorption
coefficient driving a dose is nothing like linear, and ranking by Pearson would
put a genuinely important input below a coincidentally straight one. Where they
disagree the relationship is curved, which is worth a column of its own.

**Checked against a model whose sensitivities are known by construction.**
`A(t) = f·exp(-k·t)`: at t = 0 the output *is* `f`, so `f` must explain it
completely and `k` not at all; late on `k` must dominate and be negative; and a
third parameter, sampled and never read, must correlate with nothing anywhere.

```
t=  0  f 1.000   idle 0.031   k -0.022
t= 10  f 0.746   k -0.650     idle 0.043
t= 60  k -0.975  f  0.223     idle 0.016
k over time: -0.02  -0.65  -0.85  -0.92  -0.95  -0.97  -0.97
```

That last row is the shape a single number cannot report, and is why the chart
is above the table rather than instead of it.

**Where it runs.** In the worker, because the sample lives there -- a thousand
realisations of every kept series is the thing that was deliberately not sent to
the page. The page asks about one output at a time and gets back a ranked table
and the over-time curves for the few that matter.

**Two small decisions that are load-bearing.** The *values* drawn are kept
beside the uniforms that chose them, because a log-uniform's uniform is its
logarithm -- it would rank identically and correlate differently. And a constant
input returns NaN rather than zero: a parameter the model never reads, or a
distribution whose whole range is one value, has no correlation with anything,
and answering 0 would claim it had been measured.

**The other kind is built too**, and is `src/sim/localsens.js`. Differentiating
`y' = f(t, y, p)` with respect to a parameter gives

```
S' = J·S + df/dp,      S(0) = dy0/dp
```

-- a linear system driven by `df/dp`, integrated alongside the states, so one
solve gives the states and every sensitivity at once, each to the solver's own
tolerance rather than to whatever differencing two whole runs would leave.

Three decisions made it affordable, and the second of them was the last
approximation in it.

**`J·S` is one tangent call, not a Jacobian.** The generated tangent already
computes `J·v` for any direction in a single pass -- forming the whole matrix is
that same call repeated once per colour group. `jacobian.jvp` exposes it, which
is 3 ms against 158 on model A, and agrees with forming `J` and
multiplying to 2e-16.

**`df/dp` is differentiated too, by the same generator seeded on the
parameters.** It used to be a one-sided difference — an extra evaluation of the
whole derivative per parameter per step, plus two invariant passes to carry the
perturbed parameter into algebra that had been worked out from the old one —
and it was the only approximation left in the calculation. `buildParamTangent`
in `src/sim/jacobian.js` generates it instead: one pattern pass over parameter
columns, one more tangent function, and `(df/dp)·w` in a single call.

It is one generator, not two. The state tangent and the parameter tangent
differ in exactly three places — which reference carries the seed, which column
set says a quantity is structurally still, and which terms of the assembly
survive — so `jvpSourceFor` takes a `seed` option rather than being copied.
Along a parameter the donor of a transfer is held fixed, so `d(donor × rate)`
loses its first term; decay and ingrowth have coefficients from the half-lives
and drop out altogether.

It is built on first ask and kept, so an ordinary run pays nothing for it.

Three block types are refused rather than approximated, because each carries a
runtime piece that knows how to differentiate along the state and not along a
parameter: a far-field path's transport matrix, a waste package's hazard, and a
disruptive event's rate. A model with any of them differences `df/dp` exactly
as before, which is what `differenced: true` also forces — the option exists so
the two routes can be run against each other on a model with no closed form.

What it is worth, measured on the bundled examples: the two routes agree to
between 1e-13 and 1e-5 of the state they are a sensitivity of, and the
generated one takes fewer steps because the difference noise is gone from the
term the step-size controller reads. On `four-compartment.json` — rates of
1e-5 against inventories of 1e10, where a forward difference of `f` loses
everything below the rounding of a number of order 1e9 — it is 366 steps
against 1,981 with all four rates (347 against 1,889 for `p12` alone; the
other three are within two steps of each other either way). On `recorders.json`, 529 against 698 for
`k_out[Cs-137]`. (Measured again when the sensitivity solve moved into the
runner; the counts it replaced were older than that.)

**The iteration matrix leaves out the second derivatives.** The true Jacobian of
the augmented system carries `d(J·S)/dy` in the sensitivity blocks. Left out,
exactly as CVODES leaves them out: they change how fast Newton converges and not
what it converges *to*, so the matrix is the original `J` repeated down the
diagonal and the answer is the same. That is also why it is always the NDF: a
Rosenbrock method puts the Jacobian inside its formula, and an incomplete one
changes its order rather than its speed.

**It is solved as a run.** The augmented system used to go straight to
`variableOrder` with its tolerances and nothing else -- no switch-time restarts,
no discrete events, no recorders primed or fed, none of the model's solver
settings, every compartment floored whatever its own switch said, and the
dialog's progress and Stop handed over under names the solver does not read.
A pulse a thousandth of a year wide between two switch times was stepped over
entirely (A = 0 where the run has 0.61), a `max_step` of 10 over 1,000 years
gave 20 steps where the run takes 106, and a compartment allowed below zero
came out floored. Now `run` takes `equations` -- `{ dydt, y0, abstol,
jacobian, solver, onSegment }`, a system standing over the model's own whose
first `nstate` entries are the states -- and integrates it with everything a run
does. The floor is sized by the vector, so it covers the states and nothing
after them. `onSegment` tells the equations where each segment starts, because
under `min_change_time` the clock slots are interpolated between two ends
anchored there, and those ends were worked out from the parameter as it was:
they are dropped around each difference. The tangents write the clock slots
exactly at their instant, so after the generated `df/dp` the cache is told to
work them out again. What that leaves is an approximation, and a known one:
the states read the clock-only slots interpolated, while `J·S + df/dp` reads
them at the exact instant -- a difference second order in the interval.
Interpolating the tangents between the same two ends, as the values are, would
close it; that has not been done.

**What cannot be carried is refused** (`uncarried`), since each puts a term in
`dy/dp` that `J·S + df/dp` does not have: a jump inside the run (`jumpsOf`); a
min/max, snapshot or delay -- or a running mean an event switches -- that the
derivative reads, found by walking `readsAlg` back from every transfer, source,
dy/dt term, running-mean target and waste, event and far-field setting; and a
chosen parameter that places a corner, found by moving the parameter's block a
little and asking `switchTimes` again. A recorder no rate reads is a report and
is run.

**The dialog's series are per state.** `r.y` and each block of `r.sens` are one
row per state; the worker used to walk `r.states`, which is one entry per
*block*, so on a model indexed by nuclide the labels landed on the wrong rows
and most states were never offered. `runSensitivity` returns `series`, a label
per state as the chart gives it (`stateSeries`), and the worker reads that.

Checked against exact derivatives rather than against itself. `A(t) = f·e^{-kt}`
has `dA/dk = -t·f·e^{-kt}` and `dA/df = e^{-kt}`, and a two-compartment chain
has `dB/dk = A0·t·e^{-kt}` -- which is the case that has to travel through `J`
rather than arriving straight from `df/dp`:

```
   t        A          dA/dk      exact       dA/df     exact
   30  0.4613825  -13.8414764  -13.8414764  0.3295590  0.3295590
   60  0.1520528   -9.1231651   -9.1231651  0.1086091  0.1086091
```

**The sensitivity block gets its own absolute tolerance**, `atol/|p|`, and that
is not a refinement -- without it the feature failed outright on models it
should have been easy on. `abstol` is an *absolute* floor, and `dy/dp` carries
the units of `y` over the units of `p`, so the tolerance that suits an
inventory is wrong for its derivative by a factor of the parameter. On
`four-compartment.json` -- rates of 1e-5, an inventory of 1e10, so `dy/dp`
reaches 1e13 against an `abstol` of 1e-9 -- the solver was being asked to
resolve a quantity of order 1e13 to a part in 1e22 as it passed through zero.
It rejected 79% of its steps (654,238 failures in 830,031 steps) and hit the
million-step ceiling, so *Sensitivity…* on the simplest bundled example
reported a `SolverError` rather than an answer. Scaled, the same run takes 190
steps and agrees with an independent `dp45` integration to nine significant
figures. This is CVODES's rule for the same problem
(`CVodeSensSStolerances` sets the sensitivity tolerances from the state's over
the parameter scale); a parameter that is zero has no scale to read and keeps
the state's tolerance. The state block now takes the run's own per-compartment
tolerances (`absoluteTolerance`) rather than the bare setting, so the states
are integrated to what the plain run integrates them to. The regression test
is a single compartment `dy/dt = -k·y` with `k = 1e-5` and `y₀ = 1e10`, checked
against `dy/dk = -t·y` at every output time.

Not every model is reachable even so: `examples/farfield.json` still stops
early, and for its own reason -- its first matrix layer is 44 nanometres, which
the example's own comment calls out as making the path very stiff, and the
augmented system inherits that with a copy of 1,266 states per parameter.

Reported as an **elasticity**, `(p/y)·(dy/dp)`, because `dy/dp` carries the units
of both and two parameters measured in different things cannot be compared. The
elasticity is dimensionless -- and on that model it is exactly `-k·t`, which the
test checks.

**Where a parameter cannot reach, the answer is exactly zero** -- and that is the
clearest argument for integrating the sensitivity rather than differencing two
runs. On `biosphere.json`, `leachRate[I-129]` moves the four I-129 states and no
others, since each nuclide has its own rate. Running the model twice and
subtracting gives the other twelve states a change of about `1e-11` of
themselves, which is the solver's own noise, and dividing that by a small `h`
turns it into a large and entirely fictional derivative:

```
state                       y(end)      predicted Δ       observed Δ   as % of y
Repository[I-129]         1.303e+8       -1.3032e+7       -1.2401e+7   4.84e-1
Repository[Cl-36]         4.122e+1        0.0000e+0       3.7623e-11   9.13e-11
Repository[Tc-99]        5.494e+10        0.0000e+0        8.5907e-3   1.56e-11
```

The `4.84e-1%` on the top row is not error either. `k·t = 10` at the end of that
run, so a 1% larger rate really gives `e^{-0.1} - 1 = -9.516%` where the
derivative, being linear, says `-10%` -- the gap is second-order curvature, to
three figures. The test checks against *that* rather than against the raw
difference, which is what makes it a test of the derivative instead of a test of
the step size.

The elasticity of `-10` the first browser run reported was likewise real: an
exponential's elasticity is `-k·t`, and the `-1.3e+14` beside it is only
`-10·y/p` with a parameter of `1e-5`. A raw derivative that large next to one of
`4e-2` on the same screen is precisely why the table leads with the elasticity.


## A shared solubility in moles

A shared availability sums the group's inventories, and the obvious way to do
that is in whatever the model holds them in -- becquerels, for every model here.
That is wrong for the thing a shared scheme exists for. An elemental solubility
is a limit on atoms in solution, so it has to be shared in the isotopic molar
ratios; in becquerels the ratio between U-238 and
U-234 at equal activity is 1:1 and in atoms it is 18,200:1, so a limit shared by
activity holds the short-lived isotope back as hard as the long-lived one and
is a different elemental limit for each. `basis: 'moles'` on the scheme makes
the builder weight each member of the sum by `1/(λ[1/s]·N_A)` -- a build-time
constant per isotope from its half-life, written into the generated line where
the tangent generator treats it as the constant it is -- and the limit becomes
a molar amount. The default stays `amount`, because a model in `mol` is already
right and a model in becquerels with a becquerel limit is at least the model its
author wrote; the dialog explains the difference where the basis is chosen.
Tested with two uranium isotopes at equal activity: a limit of half the atoms
gives the shared ½; a limit of exactly U-234's atoms gives 1/18,201 of the
inventory, where by activity it would have been read as half.

## A run log

A status line is replaced by the next run and is the wrong place to keep an
account of one. The run log is that account -- version, date, settings,
warnings -- and `runlog.js` assembles it from what the worker already reports, so the log and the footer cannot disagree; the page shows it
from a `log` button in the footer, and Save → Model with results writes it into
`results/meta.json` as lines, where a reopened archive shows it first under
"as saved with the results" -- the run's own account, from the page that made
it, ahead of anything the opening page can say.

Two browser rules decide how the text leaves the page. `showSaveFilePicker` is
only allowed inside a user gesture, so *Save as text…* and Save → Run log call
`saveText` from the click itself, before anything awaits; a download is the
fallback only where there is no such dialog, and the notice then says where the
file went. And a modal `<dialog>` makes the rest of the document inert, so
`copyText`'s fallback for a refused Clipboard API -- a hidden textarea,
selected and copied -- puts the textarea inside the open dialog: appended to
`body` it cannot be selected, and the copy silently takes nothing. Save → Run
log makes the log once and hands the same string to the preview and to the
file, since the log's second line is the time it was made.

## A ceiling on the decay chain

The nuclide picker includes a parent's daughters automatically, between a lower
and an upper half-life bound, and names the intermediates it skipped. The upper
bound is not a display filter: `collapse` treats an un-modelled daughter above `ceiling` as a
sink -- the activity ends there, as at a stable nuclide -- rather than walking
through it, because walking through a fourteen-billion-year nuclide hands its
parent's activity on at the *parent's* rate, and `collapse(['U-236', 'Ra-228',
'Th-228'])` did exactly that: `U-236 → Ra-228` at branching 1. So the ceiling
lives on the model (`simulation.decay_ceiling`, years; `Project.decayCeiling`)
and `decayModelFor` collapses with it, so the pairs the picker shows are the
pairs the run integrates. Default never, since every existing model was
collapsed to the stable ends and is not wrong for it; roots are exempt, since
choosing one is deliberate.

## Reading a series period by period

A curve read as an *average*, a *total*, a *change* or a *rate of change* over
each month or year is four more derived kinds (`period_mean`, `period_sum`,
`period_change`, `period_rate`), because a derived output is already "a number read off a finished curve, worked out
when asked" and a period statistic is exactly that with a length attached. Two
decisions. The boundaries are laid over the run as `t0 + kP` and each period's
number comes from the curve *between* them, interpolated at the boundaries, so
the answer does not depend on the output grid -- a logarithmic grid has no
point at year 7,000 and the annual mean there has to exist anyway. And the
answer is a stair-step on the run's own grid rather than one value per period,
so it draws on the same axis as its source and, more to the point, so `max`
of it is the peak annual mean: a derived output may now be *of* another
derived output, admitted in passes until nothing more can be, with a cycle
left out rather than looped on. What is integrated is the *output* curve, by
the trapezium rule, so the accuracy is the grid's: against `100·e^{−t/2}` every
annual mean is within 0.1% on a 200-point grid and up to 7% high late on a
sixty-point logarithmic one, where the points are most of a year apart and the
rule overshoots a convex curve. Both are in the test, because the second is the
grid a long assessment actually uses -- a period statistic wanted to better
than a few percent needs output times dense enough to carry it.

## Asking more of the sample

Each piece below is a question a real assessment asks of a sample it has
already drawn, and the matrix to answer it is already in the worker.

**Correlated inputs are a permutation, not a sampler.** Iman and Conover (1982)
is the standard for a Latin hypercube sample because of what it preserves: it
reorders the values a column was going to take so the columns' *ranks*
correlate as a target matrix says, and touches nothing else. So every marginal
is exactly what it was, value for value; every input outside a pair keeps
exactly the draws it had -- the guarantee `streamFor` makes, that an input's
sample does not depend on what else is sampled, survives; and because it is a
permutation of the whole column before the run is sliced, the pool still gives
the same design on one core and sixteen. The scores are van der Waerden's,
shuffled on a stream named for the input, so the permutation is as reproducible
as the draws. A target that is not a correlation matrix -- pairwise coefficients
typed one at a time need not be -- is moved to the nearest one that is, by
clipping its eigenvalues and putting the diagonal back, and the size of the
move is reported; the alternative, refusing, would have meant a modeller with
600 inputs could not say "these three are alike" without first proving a
matrix positive definite. Coefficients are Spearman's, which is what a
permutation can promise; Pearson's follows as closely as the marginals allow.
Held inputs take no part. `correlations` on the simulation carries pairs and
groups, a group being every sampled index of one parameter pairwise, which is
the Kd-across-compartments case that comes up.

**The regression family is one inverse.** SRC, PCC and their rank forms had been
left out on cost: a 617-wide least squares at every one of 356 output times.
They are in now for *one* time, the one on screen, and computed from the
correlation matrix `R` of `[inputs, output]` -- with `R⁻¹` its inverse,
`PCC_k = −R⁻¹[k,y] / √(R⁻¹[k,k]·R⁻¹[y,y])`, `SRC = R_xx⁻¹·r_xy` and
`R² = r_xy·SRC` -- so the whole family is one (K+1)-wide Cholesky rather than K
regressions. Constant columns are dropped rather than allowed to make the
matrix singular; a singular matrix anyway (more inputs than realisations, two
inputs that are the same numbers) is reported as "cannot" and not as a large
number. The first-order index is the binning estimator, `√n` bins of equal
count, with the `B/n` the bin means add by noise subtracted and the result
clamped at zero; on `y = 2x₁ + x₂` the two indices come out 4:1, and on
`y = (x − ½)²` -- Spearman 0.000 -- it reads 0.96.

**A category is a definition, membership is computed.** The classification
conditions are kept with the model and evaluated over the run rather than
written down as a list of realisation numbers: `simulation.categories` is a
list of {series, statistic,
comparison, value, include}, the worker sorts the matrix as the run lands and
again on every edit, and *screening* is a `Uint8Array` mask threaded through
`quantiles`, `meanOf`, `atTime`, `ranked`, `overTime`, `regressionMeasures`,
`firstOrderIndex` and `sortedColumn` -- a masked realisation is treated exactly
as a failed one, as if it were not there. `null` when nothing is screened, so
the common case pays nothing. Other is always included. First-true-wins in
list order, so the order is part of the definition and the editor lets it be
changed.

**The distribution summary is the sorted column.** One output at one time,
sorted once in the worker and sent as a `Float64Array`, so the calculator on
the page answers value↔probability by binary search and never asks again. The
statistics are the plain sample ones; the two intervals are the ones a finite
sample honestly supports -- normal bounds on the mean, and the
Dvoretzky–Kiefer–Wolfowitz band on the whole CDF, `ε = √(ln(2/α)/2n)`, which
holds for any shape and says at a glance what a 99th percentile from a thousand
draws is worth (±4.3%). DKW is the
shape-free version of the same idea and needs no assumption a dose would break.

**A fit is a shape the model can take.** `fit.js` fits only the kinds in
`pdf.js`, so every result is an expression a parameter accepts, and the curve a
fit is drawn and scored with is `densityAt` -- the one the specified
distribution is drawn with. That function cuts a truncated curve exactly where
the sampler does, because both ask `probabilityCuts`. Maximum likelihood is a
closed form for the normal, the log-normal and the two uniforms. For the four
triangles the likelihood is convex in the mode between two neighbouring
realisations, so the best mode is always an order statistic, which leaves the
two ends to search: a profile over the order statistics inside a Nelder–Mead
over the ends' log distance past the extremes, on the sample standardised to
[0, 1]. The double triangle's density jumps at its mode, so its profile also
tries the mode a hair *below* each realisation. Without that candidate its
"maximum" was less likely than the true parameters on a quantile sample, which
is what the test checks. Moments are the values' own, not their logarithms'. A
log shape's are Z's moment generating function at kL, carried as
E[e^(−kL(1−Z))] so a spread of hundreds of decades neither overflows nor
underflows; the peak comes from the skewness by bisection and the spread from
the CV. The uniforms' likelihood ends are the sample's extremes, where A² is
infinite by construction, so K–S and A² are taken over the realisations
between them -- the conditional test, since given its ends the rest is a sample
of the same curve. A curve over the histogram is n·f(x)·Δx, or n·f(x)·x·Δln x
on a log axis, so it is in the bars' units either way. All eight shapes by
likelihood take about 0.2 s for 10,000 realisations, run off the click.

**A tornado is a design, and goes through the pool.** Three runs per
variable, with the central one shared: `designFor(…, {tornado})` produces
`2K+1` design points -- point 0 everything at the model's values, point `2s+1`
input `s` at its low percentile, `2s+2` at its high -- and `runProbabilistic`
runs them exactly as it runs realisations, so slicing, stitching, progress and
Stop come for nothing and the result is a matrix a table is read out of. The
central point is bit-identical to the deterministic run, which is the test.
The price is one extra build in the coordinator to learn how many points there
are before the pool can be sized.

**A replay needs no matrix.** Because every input's draws are a function of the
seed and its name, realisation 734 is rebuilt from the settings alone, set into
the system, and run as an ordinary run: `last` in the worker becomes that
`Results`, so the chart, the table, the CSV and the HDF5 export all work on it
with no new code, and the page marks it `replayed` so the status line can say
what is on screen. The inputs it used travel with the payload. A tornado point
replays the same way, which is how "what did the run at Kd-high look like" is
answered in full.

**Bands** are the same `quantiles` at a list the model may carry
(`simulation.percentiles`); the chart draws whatever symmetric pairs arrive,
outermost faintest, and the mean when asked, as a dashed series -- the chart
needed one new idea, `dashed`, and no other.

## A varied parameter is kept as its draws

`runProbabilistic` leaves every parameter out of the matrix (`source === 'P'`)
and returns `inputs`: the output each varied parameter is, and the column of
`samples` that holds it. A parameter is a slot of `P` that the design writes
once per realisation, so in realisation *i* it is `samples[k][i]` exactly. Held
as a curve it would be that number at every output time, which is `times` times
the memory for nothing: gigabytes against megabytes on an assessment with a
thousand varied values. A tornado or a sensitivity design has no `inputs`,
since its points are not realisations. `ran` says which realisations
integrated, and the pool stitches both like `samples`.

The worker's `withInputs` appends them after the kept series. Each is a series
whose values are one number per realisation, marked in `result.flat` and as
`varied` in the descriptors the page gets. Appending leaves every kept index
where it was, so *What drove it* and the tables number what they always did.
A realisation that did not integrate is NaN in them, as in a kept series.

Everything that reads a series goes through `strideOf` and `timeIn`: the bands,
the summaries and histograms, the scatter's points, the categories and the
sensitivity reply. A flat band is sent as one number per statistic
(`flat: true`), and the page's `bandOf` spreads it over the times when a line
of it is drawn. `prob-matrix` spreads the draws back over the times too
(`acrossTimes`), so a result file has the shape every other series has.

A lookup table is an input the same way. Each of its points that carries a
spread is a slot of `P`, and `lookupPointOutputs` in ../sim/runner.js makes
that slot a series of its own, `SRF [@8700]`, the time as one more index along
the pseudo-list `POINT_LIST`. It is a constant in an ordinary run and reaches
`inputs` like a parameter's series. The table's curve is not in the matrix
either: `wanted` leaves out every kind `canBeEndpoint` refuses.

An endpoint is never an input (`canBeEndpoint` in ../domain/edit.js): not a
parameter, not a lookup table. `endpoints()` skips any in the stored list and
leaves the list as the file had it. The picker and Save's endpoint tree do not
offer them. The page compares a Done against the effective list, so dropping
the file's inputs is never an edit on its own.

`implicitInputs` in ../domain/uncertainty.js lists what else varies, for the
probabilistic dialog's *What will be sampled*: the disruptive events that draw
their occurrences, and the waste packages' failure laws, which are not drawn.
Each realisation follows the expected failure curve. That was the reader's
choice when asked, against drawing each package's failure time, which would be
a solver restart per package.

`sampleContents` on the page says what a sample holds, by block and by label.
The tree's marks and its Probabilistic chip read it, and so do the chart's
chips, their filter (`among` in `filterOutputs`) and the Table's heads.

## What SALib adds

../domain/salib.js ports what SALib 1.6.0 has that GlobalSensitivity.jl does
not:

- PAWN and discrepancy, which read any sample and sit in *What drove it*'s
  distribution family.
- The radial one-at-a-time design, with its elementary effects and Jansen's
  total index.
- Morris's trajectories with Ruano's local search for the optimal ones.
- SALib's bootstrap intervals on μ*, the Sobol indices and ν.
- The fractional factorial's interactions, and RBD-FAST's bias correction.

The designed ones go through the same registry in ../domain/gsa.js
(`GSA_METHODS`, `buildDesign`, `gsaTable`) as the GlobalSensitivity.jl ports.
The intervals are drawn from a stream of the run's seed, so a table read again
gives the same interval, and never for the curves over time, which read only
the rank.

`test/fixtures/salib-reference.json`, from `scripts/gen-salib-ref.py`, gives
each case SALib's own sample or design, outputs and numpy's resample indices,
so the test compares the arithmetic. To regenerate it: a virtualenv with
`pip install SALib==1.6.0`, then `python scripts/gen-salib-ref.py`.

The deviations are listed at the top of the module. The two that matter:

- Numpy's `arange` gives PAWN one slice edge too many for some slice counts, at
  a quantile above one, and SALib then stops. The port's edges are `i/S`.
- SALib's interval on Jansen's Sₜ indexes the differences with a (resamples ×
  inputs) array, which is not a bootstrap. The port resamples the base points
  and checks that against the same computation in the script.

Morris's optimal selection holds its distances in single precision, as SALib
does, so ties break where SALib breaks them. Four candidate sets agree.

Not ported: SALib's HDMR, which SALib is retiring for enhanced HDMR. That one
needs D-MORPH regression, an SVD and an F-test, which the tool does not yet
have.

## Known limitations

Each of these is a decision rather than an oversight, and each says what it
costs and what it would take to lift.

**The analytic Jacobian is optional, and the fallback is dense.** Two things
decline it: a function with no derivative rule, or one reached with a live
argument; and a model large enough to pass the tangent generator's ceiling of
250,000 statements. (An availability and the mass-balance audit used to be two
more; see *Availability* and *Mass-balance audit*.) Without the pattern there is nothing for `src/ode/core/sparse.js`
to factorise either, so those runs difference `df/dy` and factorise it densely —
comfortable to a few hundred states and slow past a thousand. Each refusal
names itself in the run's statistics rather than happening quietly.

**`df/dp` is generated for most models, differenced for three block types.** A
far-field path, a waste package and a disruptive event each carry a runtime
piece that differentiates along the state and not along a parameter. A model
with any of them falls back to a one-sided difference. Lifting it means writing
the parameter half of each of those three, which is a piece of work rather than
a line.

**`∂f/∂t` is still differenced in the Rosenbrock path.** `ros23` takes one
extra evaluation of `f` per step for it. The same generator would give it
exactly — seeded on the clock rather than on the state or the parameters — but
unlike those two it needs the clock to carry a tangent through
`src/parser/compile.js`, which is a change to the rule that decides whether a
call is live. The cost is one evaluation per step on one solver, and the
vendored `rodas5p` takes an exact `tgrad` already.

**A non-negativity constraint that binds is only safe under `ndf`**, with or without its BDF switch.
Holding a compartment at zero while its equations push it below makes the
derivative discontinuous there. A multistep method's Newton iteration lands on
the kink and carries it; a one-step method's stages straddle it and disagree by
the whole jump, so no step size passes the error test. `ros23` therefore stops
and names the cause rather than creeping towards zero a tolerance at a time,
and `dp45` rejects the step forever. Both failures are reported with a hint
naming `ndf`, because on the face of it they read like stiffness.

**`ros23` is also the wrong solver for a very tight absolute tolerance.** It
crawls at the start of the far-field example at its 1e-16 floor and gives up on
its no-progress check; `ndf` runs the same model in milliseconds, which is one
of the reasons it is the default.

**The solvers written here have a step budget, which the published methods do
not.** Those rely on `hmin`, and the recovery at `hmin` is designed to carry on
rather than to stop — right at an interactive prompt, where there is a person
and a Ctrl-C, and wrong in a browser Worker, where a run that cannot finish has
to say so rather than hold the tab until it is closed. So `maxSteps` and
`stallWindow` are settings of the model like the rest. The no-progress check
requires two signals — no ground covered over the window *and* a step size that
has stopped growing — because a violent initial transient crawls legitimately
before it recovers.

**No saturation band, only a floor.** A compartment in a project file may carry
a lower and an upper saturation. This tool had both and removed them: only
`ros23` could honour a band, `ndf` refused a model that set one and `dp45`
stalled on it, so the same file meant three different things depending on which
solver was chosen. What is left is one flag per compartment — *cannot go
negative* — which every solver here implements. The importer maps a floor of
zero onto it silently, maps a negative floor onto "may go negative", and
reports any real band it had to drop. A cap that is part of the model belongs
in a rate term, or in a min/max block.

**The radionuclide data is ICRP Publication 107.** 1,512 nuclides in
`src/domain/icrp107.js`, with every half-life and every decay pair, and the
chains collapsed from the published ones onto whatever nuclides a model carries
rather than typed by hand. It is the only radionuclide data here. Half-lives
are ICRP 107's, so a handful differ from later evaluations — Se-79 by 10%,
Th-229 by 7% — which is what a citable 2008 source means.

**Charts cap at 32 series**: the validated categorical palette's eight hues,
each in four line styles. The palette is never extended and never cycled on its
own — past the eighth line the hue repeats and the style changes with it, so a
series is a hue and a pattern together. A thirty-third is refused rather than
given an invented hue or a fifth style nobody could tell from the fourth.

**An index reference reaches an index list directly, not through a relation.**
`M[Lake]` finds `Lake` in one of `M`'s own lists; a file may also name an index
of a list that `M`'s is a sub-set of, or mapped to. No file in the corpus needs
it, and the fall-back path — an unpinned dimension carried from the referring
block's position — already goes through the full projection machinery,
relations included.

**A user-defined function's body does not come across.** It is a source file
inside the archive, in a language that is compiled when a run starts and that a
browser cannot run at all. The block arrives with its signature, the
import report says so, and the problem strip asks for the equation before the
model will run.

**An imported file's correlations are counted, not carried.** This tool
correlates sampled parameters by Iman and Conover's permutation — see
`src/domain/correlate.js` — but the `<correlation-matrix>` of an imported
project is not read into it. The importer counts the pairs and warns that a
probabilistic run here will spread wider than the file's own would; setting the
correlations up again in the model is what makes it agree.

## Generated functions in parts

V8 will not hand a function of more than 60 KB of bytecode to its optimising
compiler (`--max-optimized-bytecode-size`, 61,440 bytes). A longer one stays in
the baseline tier for the whole run, however hot it is. The generated functions
here pass that as soon as a model is large. On LandscapeAllChain (the SR-PSU
biosphere model, 9,462 states), the derivative is 3.0 MB of source in 39,710
lines and the Jacobian tangent 7.3 MB in 246,892 lines. Raising the limit is no
way out: at these sizes the optimising compiler crashes, as it did in Node when
the flag was tried.

So `buildFunction` (`src/parser/compile.js`) cuts a body of more than about
30,000 characters into parts of about 24,000, which is 17 to 24 KB of bytecode.
Each part is compiled as a function of the same arguments, and the result is a
function that calls them in order and returns what the last one returns. A part
is a slice of the body and nothing else. Everything the generated code carries
from one statement to a later one is in the arrays it is handed (`X`, `T`,
`out`, `dX` and so on), which every part sees. `splitBody` cuts only where that
is the whole story:

- between top-level statements, never inside a loop, a block or a bracket;
- past the last use of every top-level local declared so far. A transfer's
  `const f12` or a conditional's `let v3` lives for a few lines, and the cut
  waits for it;
- the tape line (`tapePrelude`) is the one exception: it is idempotent and read
  throughout, so every part begins with it.

A body the scan does not fully understand (a string, a template, a block
comment, a nested function, a `return` before the end, or an unfamiliar
declaration) is compiled whole, as before. So is one whose parts fail to
compile. `fn.source` is still the whole body, which is what the code view
shows, and `fn.parts` says how many parts there are. The jump functions
(`builder.js`, compiled with `new Function` directly) are not cut, because they
run once per jump.

Measured in Node 20, per call, at steady state:

| model | states | derivative | clock-only pass | Jacobian |
|---|---|---|---|---|
| LandscapeAllChain | 9,462 | 19.4 → 0.76 ms | 1.32 → 0.05 ms | 151 → 7.7 ms |
| Loviisa AoRD model-2 | 16,244 | 19.7 → 1.0 ms | 0.70 → 0.07 ms | 2,675 → 229 ms |

A whole run of the Loviisa model took 1,361 s before and takes 186 s now, in
the same 5,741 steps. Build times did not change (4.3 s; Loviisa 5.7 s before,
4.9 s now).

**The results are the same to the last bit.**

- Every one of the 66 files in the `.eco` corpus here that builds gives
  identical derivative and Jacobian values at six (t, y) points.
- The ten bundled examples, and full runs of four corpus models (SimpleSilo,
  BHASimplePA, BHKSimplePA and Loviisa), give identical output series.

`test/run.js` has a test that builds a long body in the generators' shapes and
compares it with the same body compiled whole. It fails if the cut ignores
either the brackets or the liveness of a local.

**Not yet revisited.** The tangent's statement ceiling (`MAX_STATEMENTS` and
`MAX_LINES` in `src/sim/jacobian.js`) was set for the compile time and the cost
per call of one whole function. With parts, the cost per call is an order of
magnitude lower, so the ceiling may now be set too low. It has not been
re-measured.

## An LU that keeps its pivots

A stiff run factorises I - h*J hundreds or thousands of times. The pattern
never changes and the values change slowly, yet the Gilbert-Peierls LU in
`src/ode/core/sparse.js` redoes all of it every time: a depth-first reach for every
column, and a search for every pivot. On a 16,244-state assessment model the
factorisations were 28 % of the run, and the solves another 5 %.

`src/ode/core/refactor.js` chooses the pivots once, from the values, and records
every elimination. Each later matrix is factorised by replaying the record,
with nothing searched. The canister and reactive-transport pages use the
same module; see *One solver core for three pages*.

**Choosing.** At each step it takes the entry with the least (row count - 1) x
(column count - 1), among those at least 0.1 times the largest in their column
(threshold Markowitz; 0.1 is UMFPACK's and MA48's default). The search looks at
the sixteen sparsest columns that have a candidate. It can also keep the column
order `sparseIterationMatrix` already found (natural or reverse Cuthill-McKee)
and choose only each pivot's row, by the same test, preferring short rows.
`sparseIterationMatrix` runs both on the trial matrix and keeps the cheaper.
Markowitz wins where the bandwidth order fills in, and the fixed order wins on
banded blocks that order keeps together: a decay chain in a column of cells
took 22,800 multiply-adds against Markowitz's 44,000.

**Checking.** Every replayed step is checked. The pivot must be nonzero and
finite, and no entry below it may exceed it by more than 100, a threshold of
0.01 (MA57's default). That bounds the growth of each step. A pivot chosen at
0.1 can drift a long way before it fails 0.01. On a reactive-transport model,
re-checking at 0.1 meant choosing again at half of all factorisations; at 0.01
it was one in twenty. A failing step is chosen again from the matrix as it
stands, and so is every later step. Choosing from the middle keeps pivots
chosen for an earlier matrix, and the order drifts: re-choosing from the
failing step every time took one model's work per factorisation from 190,000
multiply-adds to 820,000. So past 1.2 times the work of the last choice made
from the start, it starts again.

**Declining.** A matrix it cannot factor this way, because nothing acceptable
is left to pivot on or a value is not finite, goes to Gilbert-Peierls. That LU
either factors it or reports it singular with the message it always gave, so
a declined matrix never needs a dense one.

**When it is used.** `sparseIterationMatrix` uses it when a trial on the same
matrix costs no more than the alternative: Gilbert-Peierls's own count where
the factor stays sparse, a quarter of n^3/3 where it would have gone dense.
Both counts are structural. Gilbert-Peierls skips exact zeros as it goes, and
a trial taken at the initial state is full of them, so its runtime count
flattered it by a factor of two on one model. It is also kept under 4 million
multiply-adds. The record holds one index per multiply-add, and past that it is
16 MB; a synthetic chemistry of dense 120 x 120 blocks needed 32 million, and
stays on Gilbert-Peierls. The stats say which LU ran (`lu`), and the UI reports
it as sparse, with its fill.

**Measured.** In Node, with the same steps:
- the 16,244-state assessment model: 176 s to 128 s;
- the mid-size corpus models (1,100 to 1,500 states), where the LU was about
  a tenth of the run: 3 to 6 % faster;
- the farfield example: 0.68 s to 0.64 s.

It does not give the same bits, since the pivots differ. On the farfield and
decay-chain examples and two corpus models, the output series agree to within
a fifth of rtol x |y| + atol. On a third they differ by up to 19 times that.
Nudging rtol by one part in 10^10 moves that model's own answer by 12 to 20
times, so this is the model's sensitivity at its tolerance, not the LU.
`test/run.js` checks the backward error on the farfield model's matrices over
nine orders of magnitude of h, the choosing-again of a collapsed pivot, the
declining of singular and NaN matrices, and the singular message.

## One solver core for three pages

facsimile.html and rtm.html used to carry an NDF of their own, written from the
same papers as this one and in the same shape, and the two had drifted: each
page had tuned its copy on its own models, fixed its own faults, and grown
settings the other lacked. They are now one. The integrator and its linear
algebra live in the site at `resources/js/ode/`, and five files here are
copies of it, the same bytes:

    src/ode/core/linalg.js   src/ode/core/refactor.js   src/ode/core/sparse.js
    src/ode/core/events.js   src/ode/solvers/ndf.js

Do not edit them here. Edit the modules in `resources/js/ode/` and run
`node scripts/build-solvers.mjs` from the site's root, which rewrites these
copies and the single-file build the other pages load; `--check` fails when
either is stale. This folder stays self-contained: nothing here reaches up
into the site, and `src/ode/julia/` is the same arrangement for the ported
solvers. The site's `resources/js/ode/README.md` says what every option does.

**The same tree in both places.** `src/ode/` here and `resources/js/ode/` in
the site have one layout: `core/` for the linear algebra and event location,
`solvers/` for the integrators, and `julia/` with its own `core/` and
`solvers/` for the ported package. So a shared module imports its neighbours by
the same relative path in both, and a file is found at the same place in
either. This tool's own files sit in the same folders -- its one-step driver in
`core/onestep.js`, its Dormand-Prince and Rosenbrock solvers in `solvers/` --
and the modules that give each family this tool's shape (`variable-order.js`,
`julia-solvers.js`, `scipy.js`) and the catalogue that names them
(`solvers.js`) at the top of `src/ode/`.

**What differs between the pages is settings, not code.** The defaults of the
shared `ndf` are this tool's, so `variable-order.js` passes only what the
model sets. facsimile.html and rtm.html pass their own: the Newton system
scaled by each species' weight (their species span forty orders of
magnitude), two Newton iterations a step at least, five failing steps at the
floor in a row where this tool allows twenty failed error tests and no failed
iteration, a stall window of 4,000 steps, and their own measurements of when
a dense LU is cheaper (no minimum size, and a third of n² rather than 15 %).
Each of those was measured where it was set, and making them one set of
numbers would move one page's answers or the other's at round-off level. That
is a separate decision, not part of this merge.

**Checked by the bits.** Before the switch, every bundled example ran under
fifteen settings -- the NDF, the BDF, each LU, the differenced Jacobian, a
floating tolerance, both norms and norm control, the floor rule, the stall
tolerance, tight tolerances, a lower top order, and `ros23`, which uses the
shared LU and `sparseIterationMatrix` -- and the SFK FSAR model of 9,120
states with both Jacobians. Each run was recorded as a hash of every output
value at full precision. After the switch 144 of the 152 are bit-identical.
The eight that are not are all *Iteration matrix: sparse LU*, and four of them
differ only in the fill they report. It used to mean
whichever sparse LU was cheaper, which is what `auto` does, and facsimile.html
and rtm.html have always used it for the Gilbert-Peierls LU alone; it now
means that here too, and *sparse LU, pivots kept* (`refactor`) is offered as
it is there. The same hashes over the other two pages found the only other
difference in the floating absolute tolerance, which facsimile.html raised
from the corrector's value before the step was folded in. It now does what
this tool always did.

The ported solvers of `src/ode/julia/` keep their own linear algebra:
column-major storage, a complex LU for Radau's stages, and a sparse LU written
against their own Jacobian cache. They read `refactor` as their sparse LU,
since they have none that keeps its pivots.

## An (i) instead of a tooltip

The rows of the Simulation section explained themselves on hover, which is the
one way an explanation cannot be read while acting on it: the tooltip goes the
moment the pointer moves to the box, holds a sentence, cannot be reached from
the keyboard and does not exist on a touch screen. They have an **(i)** after
the name instead, opening one panel over the right-hand side of the window
(`src/ui/infopanel.js`). Built to be used anywhere, so adding one to another
panel is two calls:

```js
row.append(infoButton('insp:half_life', () => ({ kicker, title, lead, facts, sections })));
// ...and, where that panel rebuilds itself, after it has:
refreshInfo();
```

A topic is data -- a lead paragraph, a table of facts, sections of paragraphs,
bullets or choices with the one in force marked -- and the panel decides how it
looks. The strings may carry `code` in backticks and **emphasis** in double
stars and nothing else: the panel is built from elements and text nodes, as the
rest of the interface is, because a topic will quote block names and a name
comes out of a file. A topic given as a function is worked out when the panel is
drawn, and drawn again by `refreshInfo`, so what it says is the model as it
stands: the simulation topics (`src/ui/siminfo.js`) read the solver chosen and
quote its defaults, which come from `solverDefault` in `src/ode/solvers.js`
beside the table of who reads what -- the numbers the solvers' own code uses,
which a test holds them to.

One panel at a time: another (i) replaces it, the same one closes it, as do the
× and Escape. Escape only from the panel, an (i) or nowhere in particular --
it puts a text box's value back and clears the tree's selection, and taking it
from those would close a panel nobody was looking at -- and never past an open
dialog. It sits between the header and the footer, read off them rather than
written into the stylesheet, since the header wraps on a narrow window.

**Where the (i)s are.** A row's is after its control, in a third grid column
(`.field.has-info`, built by `infoRow` in `renderSidebar`), so every (i) down the
panel is on one right-hand edge; a section heading's is the last thing in its
summary (`section({info})` in `parts.js`), pushed right in the flex heading of
`#sb-top` unless a count has already taken the push. The tree's is beside its
search box, the Information view's is handed in through `hooks.info`, and a
dialog's is `openModal({ info })`, beside the close button. Their topics are in
`src/ui/panelinfo.js` (the sections and the tree, which says what is above it
only when it is there), `src/ui/blockinfo.js` (one per kind of block, read from
whichever block the window shows when the (i) is pressed) and
`src/ui/dialoginfo.js` (`dialogInfo('save')` and the rest). By convention `info`
is a dialog's first option, which is where the test that every dialog has one
looks for it; the one exception is the one-box prompt for a shape's text.

**Inside a dialog.** A modal dialog makes everything outside it inert, so an (i)
in a dialog opens the panel *inside* the dialog -- still `position: fixed`, so
still laid over the window rather than clipped by the dialog's own
`overflow: hidden`. `place` puts it beside the dialog when there are 300 pixels
to spare, and otherwise over the dialog's right-hand edge, starting below its
title bar so that the (i) and the dialog's × stay in reach. The dialog's
`cancel` handler closes the panel first when one is inside it and refuses the
close, so Escape anywhere in the window closes what is in front; Chrome lets a
page refuse a close request only once per user activation, and Escape is not
one, so the next press closes the window even with nothing clicked between.

**Read more in Help.** A topic's `more` is the heading of the Guide section that
says the rest; `setInfoLinks` in `boot` makes the link close any dialog, switch
to Help and go to `slug(more)`, and `goToHelp` asks again every tenth of a
second, for five seconds, while the Guide is still loading. A test checks every
topic's `more` against the Guide's headings, so renaming a heading there names
the topics it strands.

**Testing it in headless Chrome.** Chrome 153 headless on macOS, with the page
focused (a tab made by `Target.createTarget`, or focus emulation on), hangs the
browser within a few modal dialogs closed with a CDP Escape key -- on the third,
on a twelve-line page with a bare `<dialog>` -- and closing with a click never
does. Close dialogs with their × in a CDP script. A tab made by
`/json/new` is not focused and does not hang, but it also never gets focus
events, so what focus does is not tested there.

## Block settings as floating windows

A block's settings open with `openModal({ floating: true })` (src/ui/modal.js):
`dialog.show()` rather than `showModal()`, so the page is not made inert and a
second block's settings can be opened beside the first. What a modal dialog
gets from the browser, a floating one is given by hand:

* **placing** -- `.modal.is-floating` is `position: fixed; inset: 0; margin:
  auto`, which centres it as the top layer centres a modal one, and `pin` then
  fixes it there; each new one is moved a step down and right of the last
  (`28 * (open % 8)`), so none lands exactly on another;
* **stacking** -- not in the top layer, so `raise` keeps the floating windows
  in a band of their own (z-index 30 and up) under the pickers (40), the info
  panel (45), the drop zone (50), menus and notices (60) and completion (90),
  and brings one to the front on `pointerdown` (capture) and `focusin`;
* **Escape** -- no close request reaches a dialog that is not modal, so a
  `keydown` on the dialog closes it, after a panel an (i) in it opened, unless
  a field has already taken the key (`defaultPrevented`).

It has no backdrop, so `dismissOnBackdrop` is not attached. `refreshModal`
refreshes the modal dialog on top when there is one (everything under it is
inert), and otherwise every floating window, since each is an editor over the
same model. Code that wanted "the open dialog" in order to escape a modal's
inertness now asks for `dialog:modal`: the notice, the copy fallback's
textarea, the info panel's document-level Escape.

`openBlockSettings` keeps `settingsWindows`, block name to window: asked for a
block whose window is open, it calls the handle's `focus()` instead of
opening another. Each window holds its own block name, moved on by a rename
made in it; `state.settingsFor` is only the window last used, for the undo
history's labels. Each window's (i) is keyed by the window
(`dialog:block:<id>`), since two windows can be about two kinds of block.

The Information view uses the same machinery for a window of its own (`popInfo`
in src/ui/app.js), opened by the **⧉** in its title bar. `renderInfoCard`
renders into the window's body while `infoWin` is set, and into `#info`
otherwise. With `hooks.bar`, `renderInfo` (src/ui/info.js) skips the fold and
puts its buttons in a slot in the window's head, ahead of its (i).
`#sidebar.is-info-out` hides `#info` and the divider, so the tree takes the
rail. Two options were added to `openModal` for it. `className` is applied
before the first layout. `keep` has `closeAllModals` leave the window open, so a
newly opened model is shown in it rather than closing it. The scroll position
is kept across a rebuild while the same thing is shown. The place, the size and
whether it was out are stored in `localStorage` under `kompartment.infoWindow`
(read and written in try/catch, and saved on every `pointerup` on the window),
and the first model on screen reopens the window if it was out.

## A pipe's place, per canvas

A connection's bend is `layout['edge:<name>']`. A connection is drawn whole on
the one canvas that sees both its ends, as themselves or as the sub-system
nodes holding them, and on each deeper canvas as a line ending in a pipe
(`_elsewhere` in `_renderEdges`). The pipe used to be placed by the same
point, so dragging it inside a sub-system bent the line above, and the other
way round. Now a pipe is `edge:<name>@<canvas>` (`waypointKey`,
`parseEdgeKey` in src/domain/edit.js). `_renderEdges` notes which connections
are pipes on the canvas it draws (`_pipesHere`), and `_wayView` gives the drags
and Straighten the point that canvas owns. The keys follow a renamed block
(`retargetLayout`) and a renamed or moved sub-system (`retargetLayoutAll`'s
`canvasOf`); `pruneLayout` drops a pipe whose canvas has gone; and a moved end
drops every canvas's point (`clearWaypoints`). A file written before this has
only the one key, which is now the whole drawing's; its pipes start from their
default places.

## Faults found by building

The problem scan builds a `Project`, not the system, so a fault only the
builder can find -- an equation indexed by a list its slot cannot reach --
used to surface only as a failed run: the strip had it, no block did, and it
named the setting by its slot, `Canisters#degradation_rate`. Three changes:

* `BuildError` files a `Block#setting` owner under the block (with `.setting`
  kept) and says slot names in words (`inWords`, `SLOT_WORDS`): *Canisters's
  matrix degradation rate*, and "add 'WT' to the lists Canisters is indexed
  by";
* the build behind the values at the start (`computeStartValues`), which is
  the builder without df/dy and so fails where a run would, hands what it
  caught to `noteBuildProblem`: a `buildProblem`, shown in the strip ("the
  model will not build as it stands") but not refusing Run. `recheckBuild`
  runs it again after every edit, or forgets the fault for a model whose build
  is over `START_BUDGET`, where the run will say it;
* `marksByName` marks the block that the run's problem or the build's names,
  and `fillSettingsProblems` puts every problem naming a block at the top of
  that block's settings -- filled in place, since a fault can arrive after the
  window was drawn.
