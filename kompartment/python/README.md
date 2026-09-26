# Kompartment for Python

Read a Kompartment model into Python, edit it through documented methods, write
it back as a project file the application opens -- and run it, deterministically
or probabilistically, without the browser. For the models you would rather
generate than draw: a chain of fifty compartments, a parameter table read from
a spreadsheet, the same edit made to twenty variants of an assessment, a
thousand realisations on every core of a server.

```python
import kompartment as kp

m = kp.Model.new('Two boxes')
m.add_nuclides(['Cs-137', 'Sr-90'])
m.add_compartment('Soil', initial='1e10')
m.add_compartment('Well')
m.add_parameter('k', 0.05, unit='1/year')
m.add_transfer('Soil', 'Well', rate='k')
m.save('two-boxes.json')
```

Reading, editing and writing need Python 3.9 or later and nothing else.
Running a model needs numpy and SciPy; numba, when installed, compiles the
model and the solver's loop, which makes a small model tens of times quicker.
Node.js is only needed for `Model.validate()`, which runs the application's
own checks on a model.

## Installing

From this directory:

```sh
pip install -e .            # read, edit, write
pip install -e ".[run]"     # ... and run (numpy, SciPy)
pip install -e ".[fast]"    # ... with numba
pip install -e ".[all]"     # ... and pandas, for Results.to_dataframe
```

or put this directory on `PYTHONPATH`. The package is `kompartment`.

## Reading and writing

```python
m = kp.Model.load('examples/biosphere.json')   # .json, .json.gz or .zip
m = kp.Model.from_json(text)
m = kp.Model.from_dict(data)                    # the dict is copied
m = kp.Model.new('Name', 'What it is')

m.save('out.json')                              # or .json.gz, or .zip -- or .eco, an Ecolego project
text = m.to_json()
data = m.to_dict()

m.author = 'A. Modeller'                        # who wrote it: 'author' in the file
m.created, m.saved                              # when it was made and last saved (UTC), or None
```

`save` stamps the model as the application's Save does: `saved` is now, and
`created` too for a model that has none; `Model.new` dates a model when it is
made. An `.eco` is an export and is not stamped.

Reading a file brings it into the shape Kompartment works on, as the application
does when it opens one: older key spellings renamed, the two built-in material
lists present, every block's dimensions written down, transfer ends written as
qualified names, and the units that follow from the model filled in. A file the
application saved comes back byte for byte. `normalise=False` leaves a
dictionary exactly as it is.

A `Model` holds the project exactly as the file does, as `m.raw`. Every block,
index list and setting is a view onto that dictionary, so nothing is copied and
what the objects show is what is saved.

## Blocks

| Add | Block |
|---|---|
| `add_compartment(name, initial, ...)` | A state variable holding an inventory |
| `add_transfer(source, target, rate, ...)` | A flux between compartments; either end may be `None` |
| `add_inflow(target, rate, ...)` | A source term from outside the model |
| `add_parameter(name, value, ...)` | A constant, and the distribution a probabilistic run draws it from |
| `add_expression(name, equation, ...)` | An algebraic quantity |
| `add_lookup(name, points, ...)` | A value following a series of points, at the clock or at an argument |
| `add_function(name, parameters, equation)` | Arithmetic called from any equation |
| `add_index_reduction(name, target, over=...)` | One block reduced along one of its index lists |
| `add_block_reduction(name, targets, ...)` | Several blocks combined element-wise |
| `add_min_max`, `add_running_mean`, `add_snapshot`, `add_delay`, `add_trigger` | The blocks that remember |
| `add_farfield(name, **settings)` | A far-field pathway (FARFCOMP) |
| `add_waste_package(name, failure=..., **settings)` | Waste packages that fail and release |
| `add_event(name, timing=..., ...)` | A disruptive event, with fail and move actions |
| `add_transport(name, number=...)` | A chain of N compartments drawn as two |

Every `add_` method takes `system=` for the sub-system the block goes in, and
most take `unit=`, `comment=`, `index_lists=` and `position=(x, y)`. Leave the
name out and the block is called what the application would call it (`C`,
`C1`, ...). A new compartment, transfer or expression is indexed by the
radionuclides when the model has any; a parameter or a lookup table is not.

Blocks are reached by qualified name, `system.name`:

```python
soil = m['Soil']                  # or m.block('Soil'), or m.get('Soil') for None
m['NearField.Water']
m.compartments, m.transfers, m.parameters, ...   # every block of a kind
m.blocks(kind='parameter', system='NearField')
```

A block's settings are properties, checked as the application checks them:

```python
soil.initial = '1e10'
soil.non_negative = False
m['Soil_Well'].multiply_by_donor = False
m['Q_gw'].interpolation = 'nearest'
m['Rock'].n_f = 40
soil['some_key']                  # any raw value
soil.raw                          # the block's own dictionary
```

A value the application would refuse raises `kp.EditError` on the spot.

### Values per index

A block indexed by one or more index lists holds one value per combination of
their indices. The block-level value is the default; a value set at an index
overrides it there, the most specific match winning.

```python
soil.set_value('5e9', at='Cs-137')                     # one dimension: the index alone
kd.set_value(0.03, at={'Radionuclides': 'Cs-137', 'Object': 'Lake'})
kd.set_value(0.01, at=('Sr-90', 'Mire'))               # one index per dimension, in order
soil.set_entry('Sr-90', initial='2', abstol=1e-3)      # several keys at once
soil.value_at('Cs-137')
soil.clear_value('Cs-137')
soil.combinations()                                    # every index combination, in solver order
```

### Distributions

```python
from kompartment import distributions as dist

m['k'].distribution = dist.log_triangular(0.01, 0.1, 0.05)
m['Kd'].set_distribution('norm', at='Cs-137', mean=0.05, sd=0.01, trmin=0)
m['Q'].set_point_distribution(1, 'unif', min=1.5, max=2.5)
```

The kinds are Kompartment's: `unif`, `triang`, `dtriang`, `norm`, `logu`,
`logt`, `logdt`, `Logn4`, `logn`, `logn5` and `pg` (a list of values), each
with truncation by value or by percentile and an optional correlation group.

## Edits that reach across the model

```python
m.rename_block('Soil', 'Topsoil')
m.move_block('Topsoil', 'NearField')
m.delete_block('Well')
m.delete_blocks(['A', 'B'])
m.set_connection_end('Soil_Well', 'to', 'Lake')
m.set_dimensions('Soil', ['Radionuclides', 'Object'])
```

These follow the change through every reference the way the application's
editor does: every equation (written from wherever it is written), transfer
ends, reduction targets, trigger names, event actions, values keyed by a
compartment's or a transfer's name, and the diagram. They refuse what it
refuses, and the error says why:

- a delete while something still reads the block (a compartment's transfers
  and inflows go with it);
- a rename or move whose new spelling would mean a different block from where
  an equation is written;
- a name that is taken, reserved, or not a name.

A move takes a compartment's outgoing transfers and inflows with it, since a
transfer lives in its donor's sub-system. Changing a compartment's dimensions
brings its transfers, the transport it is part of and the reductions that read
it along.

## Index lists, materials and decay

```python
m.add_index_list('Object', ['Lake', 'Mire', 'Forest'])
m.add_index_list('Wetland', ['Mire'], subset_of='Object')
m.add_index_list('Kind', ['Water', 'Land'], mapping_to='Object',
                 pairs={'Lake': 'Water', 'Mire': 'Land', 'Forest': 'Land'})
m.add_scenarios(['Present', 'Warmer'])
m.scenario = 'Warmer'

lst = m.index_list('Object')
lst.add_index('Bog')
lst.rename_index('Bog', 'Fen')     # values, sub-sets, mappings and K[Bog] in equations follow
lst.set_enabled('Fen', False)
lst.remove_index('Fen')

m.add_nuclides(['U-238', 'U-234', 'Th-230'])   # half-lives from ICRP 107
m.add_material('Water', unit='m3')             # a material that does not decay
m.set_half_life('Xx-1', 12.5)
m.decay_chains                                 # the pairs in force
m.add_decay_pair('U-238', 'U-234', 1)          # the first edit writes the chains down
m.reset_decay_chains()                         # follow the nuclides again
m.decay_unit = 'mol'
```

Two lists are built in and always present: the material catalogue
(`Contaminants`) and the radionuclides (`Radionuclides`), a sub-set of it.
Adding a radionuclide adds the material; removing one removes it. `Elements`,
`Compartments` and `Transfers` are worked out from the model and are never
stored.

## Sub-systems and transports

```python
m.add_system('NearField')
m.add_system('Buffer', parent='NearField')
m.rename_system('NearField', 'Near')
m.move_system('Near.Buffer', '')
m.delete_system('Near')                       # its contents move out
m.delete_system('Near', contents='delete')
m.set_system_enabled('Near', False)

tube = m.add_transport('Tube', number='20')
m.add_transfer('Soil', tube)                  # into its Begin
m.add_transfer(tube, 'Lake')                  # out of its End
m.add_transport_operation(tube, operation='mean')
```

## Settings, the diagram, reviews

```python
sim = m.simulation
sim.update(end_time=1e6, rtol=1e-6, abstol=1e-12, solver='radau5')
sim.spacing = 'series'
sim.add_output_series('times', times=[1e3, 1e4, 1e5])

m.view.show_parameters = True
m['Soil'].position = (120, 80)
m.add_shape('sticky', 40, 40, text='Check this')
m.add_derived('Peak dose', 'max', 'Dose [Cs-137]')

m.review_tracking = True
m.record_review('Kd', by='A. Author', reviewer='A. Reviewer')
m.review_status()                             # approved, stale, review or none, per block
```

## Checking a model

```python
m.check()       # what this package can see: names, ends, references, lists, values, settings
m.validate()    # Kompartment's own checks, through Node: raises kp.ValidationError
```

`validate()` loads the model as the application opens a file, checks every
equation with the editor's checker, and builds it as a run would. It needs
`node` on the path and the Kompartment sources: this package's own repository,
or the `src` directory named by `KOMPARTMENT_SRC`.

## What follows from the model

A transfer's unit follows from its donor and the time unit, a flux's dimensions
from its two ends, a transport's from what it is connected to. The application
brings these up to date after every edit. Here `m.settle()` does it, and it runs
by itself whenever the model is written out or checked.

## Running a model

```python
res = m.run()                                  # the model's own settings
res = m.run(end_time=1e5, solver='ros23')      # any simulation setting, for this run
res = kp.run('examples/biosphere.json')        # a path, a Model or a dict

res.labels                                     # every series, named as the Chart names them
res.t                                          # the output times
res['Dose [I-129]']                            # one series, a numpy array
res.select('Soil')                             # the descriptors of one block's series
res.total('Soil')                              # summed over its indices
res.max('Dose [I-129]')                        # {'t', 'value'}
res.to_csv('run.csv')                          # the Table tab's CSV
res.to_dataframe()                             # pandas, one column per series
res.mass_balance()                             # the audit, when simulation.mass_balance is on
print(res.summary())
```

A run is the application's run: the same model loaded the same way, built
into the same equations in the same order, and solved by ports of the same
solvers -- `ndf` (the default), `ros23`, `dp45`, the six Julia-derived methods
(`fbdf`, `qndf`, `rodas5p`, `radau5`, `kencarp4`, `trbdf2`) and SciPy's `BDF`,
`Radau` and `LSODA` (`scipy_bdf`, `scipy_radau`, `scipy_lsoda`), which here run
natively rather than in a browser's Python. The derivative is the
application's to the last bit on the bundled examples; a run agrees with the
application's to round-off, and usually takes the same number of steps. It
cannot always take exactly the same: each step size is chosen with a power,
and JavaScript's `Math.pow` rounds differently from the C library's in the
last place for about one argument in ten.

```python
m.values_at_start('Soil')                      # what the equations come to at the first instant
runs = m.run_scenarios(workers=3)              # {scenario: Results}, one run per scenario
system = m.build()                             # the built equations: system.dydt(t, y), system.layout
```

### Solving in parts

```python
res = m.run(split='on')                        # each independent part in a process of its own
from kompartment.engine.runner import run
res = run(m.project(split='on'), workers=4)    # at most four processes
res.stats['split']                             # whether it was split and why, each part's steps and times
```

A model that falls apart into parts that cannot reach each other -- each decay
chain a system of its own, joined to no other -- can be solved a part per
core, as the application's *Split into parts* does: `simulation.split` is
`auto` (the default), `on` or `off`. The parts are read off the model's
Jacobian. Each is the model with every other material switched off, solved on
the output grid at its own steps in a process of its own, and its states are
filed back into the whole model by name, so what comes back is the whole
model's `Results`. It agrees with a whole solve to within the tolerance, not
to the last digit, and does not depend on the number of processes. A model is
solved whole, whatever the setting, where the application would solve it
whole: a delay, a snapshot or a discrete event; output at the solver's own
steps; no materials to divide by; one part; one core. So is a split that does
not add up, and `stats['split']['why']` says so.

`auto` is the application's rule with numbers measured here, since a process
takes longer to start than a browser's worker. A model this process has not
timed is split from 10,000 states, when its parts promise at least 2x over
the cores there are. Once a whole solve has been timed, it is split when that
solve took 1.5 s or more and the parts are expected to be at least 1.2x
faster. Once it has been split, what the split was measured to gain decides.
A made-up model of 16 independent chains, 28,800 states, took 8.5 s whole and
2.9 s split on eight processes (2.1 s of solve against 7.5 s). A model of a
few thousand states is quicker whole.

The processes are started with `spawn` and load only this package, never the
calling script, so a script needs no `if __name__ == '__main__':` guard for a
run to be split. Each process keeps its numerical libraries to one thread.

### Probabilistic runs

```python
p = m.run_probabilistic(1000, seed=1, workers=8, keep=['Dose'])
p['Dose [I-129]']                              # (realisations, times)
p.quantiles('Dose [I-129]')                    # 5th, 50th and 95th percentiles over time
p.sample('Kd[I-129]')                          # the values one input took
p.what_drove('Dose [I-129]', at='max')         # which inputs the spread came from

m.run_probabilistic(tornado={'low': 0.05, 'high': 0.95})
m.run_probabilistic(gsa={'method': 'sobol', 'options': {'samples': 512}})
```

The design is drawn whole in every process, from the same named streams the
application draws from, so the samples are the application's and the answer
does not depend on `workers`. With `workers` above 1 the realisations are
shared between processes; a script that uses them needs the usual
`if __name__ == '__main__':` guard on macOS and Windows.

### Sensitivity and calibration

```python
s = m.local_sensitivity(['Kd[I-129]', 'geoTransit'])      # dy/dp integrated with the model, df/dp exact
cal = m.calibrate(
    targets=[{'output': 'Dose [I-129]', 'when': 'max', 'value': 1e-5}],
    variables=[{'key': 'Kd[I-129]', 'lower': 1e-3, 'upper': 10, 'space': 'log'}],
    method='nelder', apply=True)                           # apply=True writes the values found
m.put_values([{'key': 'Kd[I-129]', 'value': 0.5}])         # the same by hand
```

### Result files and data files

```python
res.to_hdf5('run.h5')                          # the result file the assessment tools read
res.save('run.zip')                            # the model with its run beside it
res = kp.load_results('run.zip')               # ... opened again, here or in the application
print(res.run_log())

m.export_data('data.xlsx')                     # every parameter and lookup table, as rows
m.export_data('data.h5', blocks=['Kd', 'Q'])   # or some of them, as HDF5
report = m.import_data('data.xlsx')            # edited values, distributions, tables read back
print(report)                                  # what it read, and what it could not match
m.data_rows()                                  # the rows themselves
```

Each is the file the application writes: an HDF5 result file from the
application's own numbers comes out the same byte for byte, an archive
written here opens in the application with the run in place and one written
there opens here, and the data files go both ways.

### Importing

```python
m = kp.Model.from_eco('project.eco')           # an Ecolego project, assessment or model.xml
m.import_report.skipped                        # what could not come across, and why
m.import_report.warnings
```

### Exporting to Ecolego

```python
m.save('project.eco')                          # an Ecolego 6 project
out = m.to_eco()                               # or in memory: out.bytes, out.xml, out.report
print(m.export_report.summary())               # what went out, and what could not
m.export_report.skipped                        # left out, with the reason: no Ecolego equivalent
m.export_report.rewritten                      # written as the Ecolego construct that says the same

from kompartment.io.ecoexport import export_eco
out = export_eco('model.json')                 # a path, a project dict or a Model
```

The application's *Save → Model → Ecolego project* and this give the same file
for the same model, byte for byte: `model.xml`, an empty `views.xml` and
`.version` in a ZIP whose entries are stored, dated 1980-01-01 unless
`modified=` gives a date. The file is written as the importer reads a
project, so `kp.Model.from_eco` gives back the model that went out, apart from
what the report lists; the Guide's *Exporting to Ecolego* says what maps to
what, what is written in another form (an inflow as a transfer from a source,
a narrowed transfer with zeros outside its sub-set, an availability folded
into the rate, a logarithmic output grid as its list of times, a far-field
path as a sub-system of its cells and the transfers between them) and what is
left out (waste packages, events, a far-field path that is switched off,
summed fluxes, blocks on the `Compartments` and `Transfers` lists, the
double-triangular distributions, correlations and the diagram). A far-field
path's layers are laid out by the package's engine, as a run lays them out
at its start, so exporting one needs numpy. The model's author goes out as
the project's.

### Speed

The equations are compiled to numpy, statements of the same shape merged into
one expression, and the derivative assembled as one sparse product in the
application's order. With numba installed a run goes further: the model's
derivative is compiled to machine code, and so is the solver's loop -- the
NDF, Rosenbrock (2,3) and Dormand-Prince, ported step for step
(`kompartment.engine.compiled`) -- so that a run returns to Python only when
it ends. A compiled run takes the same steps as the Python path to the last
bit: the same states, statistics and failures. So it is the default
(`compiled='auto'`); `m.run(compiled=False)` keeps to Python, and
`compiled=True` insists, saying why when it cannot.

```python
res = m.run()
res.stats['compiled']                          # True when the run was compiled
res.stats.get('compiled_why')                  # and why not, when it was not
```

A model's first run compiles it, in a second or two (the solvers compile once
per machine). After that, runs and other processes load it from the cache:
`KOMPARTMENT_CACHE`, or the user's cache directory. Measured on a laptop,
best of three runs:

| Run | Python | Compiled |
| --- | --- | --- |
| four-compartment, NDF | 15 ms | 0.7 ms |
| decay-chain, NDF | 105 ms | 1.6 ms |
| biosphere, NDF | 26 ms | 1.4 ms |
| landscape, NDF | 57 ms | 3.4 ms |
| waste-packages, Dormand-Prince | 0.98 s | 20 ms |
| farfield (1,581 states), NDF | 0.99 s | 0.71 s |
| made-up decay chains, 2,000 states | 0.25 s | 0.14 s |
| made-up decay chains, 16,000 states | 2.0 s | 1.4 s |
| biosphere, Sobol design of 272 runs, one process | 12.6 s | 1.3 s |

The application takes 2.5 s over the same Sobol design. On a large model the
gain shrinks: most of the time goes to SuperLU's factorisations and solves,
the same calls on both paths. The compiled loop calls back into Python for
these, as it does for an analytic Jacobian and for progress. Rosenbrock
gains two to three times on a model whose analytic Jacobian moves, since it
asks for a Jacobian at every step, and that Jacobian is worked out in Python.

Some runs stay on the Python path, and `compiled_why` says so:

- a model with discrete events, or with a running mean, snapshot, delay or
  trigger (a min/max is compiled);
- `min_change_time`;
- the SciPy and Julia-derived solvers;
- a system of equations standing in for the model's own, as local
  sensitivity integrates;
- a far-field path worked out semi-analytically (`method='semi-analytical'`):
  its release is the recorded history of what flowed into it convolved with
  the path's unit responses, which the compiled loop does not keep. The Python
  path runs it as the application does, to rounding (the history is summed
  with numpy); the example worked that way takes about 5 s, half of it working
  the responses out, which later runs with the same settings reuse.

Each worker process of a probabilistic run or a split run is compiled like
any other.

## Where this differs from the application

In editing, nowhere that the parity tests can find. In a run:

- The iteration matrix is factorised by the application's own dense LU
  (compiled with numba) or LAPACK up to 64 states and by SuperLU above,
  where the application tries its own sparse LUs from 24 states up. The run
  log's sparse flag and fill can differ; the solutions agree to round-off.
- The numbers of a run agree with the application's to round-off rather
  than to the last bit (see *Running a model*): step counts usually match
  and can differ by a few per cent where an error estimate sits at rounding
  level.
- The Julia-derived solvers factorise with SciPy's LUs; the solutions agree
  to round-off.
- *Split into parts* runs its parts in processes rather than workers, so
  `auto` decides with numbers of its own (see *Solving in parts*). A run
  with a SciPy solver is split here, where the application would have each
  worker download a Python runtime; a run that is itself in a worker
  process, such as a scenario of `run_scenarios(workers=3)`, is not. A
  min/max or a running mean is taken from the part that owns what it reads.
  One that reads more than one part (the peak of a total over nuclides) is
  solved whole, where the application splits the model and reports the
  total's value at each time as its peak.

## Tests

```sh
cd tests && python -m unittest
```

With Node available, `test_app_parity.py` runs the application's own code
beside this package — every bundled example opened, forty-odd edits, the decay
chains, the review stamps, 2,200 numbers formatted — and compares the results as
JSON text, key order included. The `test_engine_*` files do the same for runs:
through `tests/node/engine.mjs` the application builds and solves every
bundled example, and the layout of the equations, the derivative at random
states, the step counts and every series are compared with the engine's; the
other `test_*` files do it for the samplers, the sensitivity methods, the
optimisers, the importer and the file formats. `test_eco_export.py` exports
every bundled example and the made-up models of `test/eco-export-fixture.js`
through `tests/node/eco_export.mjs` and here, and compares the archives byte
for byte; then reads each export back with both importers, compares what
comes back with the model that went out, and runs the two. `test_engine_split.py` compares
the partition and the plan of a split run with the application's, and split
runs with whole ones; `KOMPARTMENT_SPLIT_TIMING=1` adds a timing of a large
made-up model, whole against split. `test_engine_compiled.py` runs the bundled
examples and made-up models on the compiled path and the Python path, and
asks for the same states, statistics and failures to the last bit, across the
solvers' settings, the non-negative constraint, a min/max, sparse matrices
and the solver's own steps as output. `tools/gen_data.mjs` writes the ICRP 107 table
and the reserved names from the application's sources; `--check` says whether
they are current.

## Licence

MIT, as Kompartment. See [LICENSE](LICENSE).
