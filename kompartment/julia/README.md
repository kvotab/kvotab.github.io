# Kompartment for Julia

Open a Kompartment model -- or an Ecolego project or assessment -- in Julia,
edit it, build it into equations, run it and save what it produced, as the
table or as the HDF5 result file the assessment tools read. The package is a
port of the Python package, made as fast as Julia can make it: the equations
are compiled to native code, the linear algebra is Julia's own, a model is
solved by the quickest of the solvers here, and probabilistic runs share the
threads. A run agrees with the Python package's to its tolerance; with parity
on (`Kompartment.set_parity!(true)`, or `KOMPARTMENT_PARITY=1`) it is that
package's run to the last bit on every bundled example -- the same equations
in the same order, the same steps -- which is how the two are checked.

```julia
using Kompartment

m = Kompartment.load("assessment.eas")          # or .eco, model.xml, .json, .json.gz, .zip
set_simulation!(m; non_negative=false)
res = run(m)
save(res, "assessment.h5"; blocks=["Well"], time_origin=2000)
```

## Installing

The package needs Julia 1.10 or later. From this directory:

```julia
using Pkg
Pkg.develop(path=".")        # or Pkg.activate(".") to work in its own environment
```

The first `using Kompartment` precompiles the package, which takes under a
minute; after that it loads in a fraction of a second, and a session's first
model runs without waiting for Julia to compile the package's own code.
Probabilistic runs, and a large model's derivative, use the threads Julia was
started with: `julia -t auto`, or `JULIA_NUM_THREADS`.

## Opening a model

```julia
m = Kompartment.load("examples/biosphere.json")   # .json, .json.gz or .zip
m = Kompartment.load("assessment.eas")            # an Ecolego assessment, project (.eco) or model.xml
m = from_json(text)
m = import_ecolego(bytes; file_name="model.eco")  # an Ecolego file's bytes

m.raw                       # the project, as the file holds it (an ordered dictionary)
simulation(m)               # its simulation settings, live
set_simulation!(m; end_time=1e6, solver="ros23")
save(m, "out.json")         # or .json.gz, or .zip
to_json(m)
```

Reading a file brings it into the shape Kompartment works on, as the
application does when it opens one: older key spellings renamed, the material
lists present, every block's dimensions written down, the units that follow
from the model filled in.

An Ecolego file is imported as the application's *Import* reads it. What could
not come across is in `m.import_report`: `skipped`, `renamed`, `disabled`,
`warnings` and `counts`, and `m.import_report.summary` says it in words. Read
it before trusting the numbers.

## Editing a model

```julia
m = new_model("Two boxes")
add_nuclides!(m, ["Cs-137", "Sr-90"])         # half-lives from ICRP 107; the decay chains follow
add_compartment!(m, "Soil"; initial="1e10")
add_compartment!(m, "Well")
add_parameter!(m, "k", 0.05; unit="1/year")
add_transfer!(m, "Soil", "Well", "k")

m["Soil"].initial = "2e10"                    # a block's settings, checked as the application checks them
set_value!(m["Soil"], "5e9"; at="Cs-137")     # a value at one index
set_distribution!(m["k"], "logt"; min=0.01, max=0.1, mode=0.05)
rename_block!(m, "Well", "Lake")              # every equation and transfer end follows
m.simulation.end_time = 1e5                   # the settings, checked too
check_model(m)                                # what is wrong, in words
save(m, "two-boxes.json")
```

This is the Python package's editing API, in Julia's spelling: a function that
changes the model ends in `!`, and a block is `m["name"]` (or `block(m,
name)`, `get_block(m, name)` for `nothing` when absent), its settings
properties. Everything the Python package's *Model* edits is here: every
`add_*!` block, values per index and distributions, edits that follow every
reference through the model (`rename_block!`, `move_block!`, `delete_block!`,
`set_dimensions!`, `set_connection_end!`), index lists and scenarios,
materials, half-lives and decay chains, sub-systems and transports, derived
outputs, review records and `check_model`. A value the application would
refuse throws an `EditError` in its words. The edits are checked against the
Python package's, the model's file after each one byte for byte
(`tools/edit_fixtures.py`, `test/model/edit.jl`).

## Running

```julia
res = run(m)                                   # the model's own settings
res = run(m; end_time=1e5, solver="ros23")     # any simulation setting, for this run only
res = run_file("examples/biosphere.json")

res.t                          # the output times
labels(res)                    # every series, named as the application's chart names them
res["Dose [I-129]"]            # one series
outputs(res, "Soil")           # the descriptors of one block's series (also kind=, nuclide=)
series_many(res, outs)         # several series at once: one pass over the run
total(res, "Soil")             # summed over its indices
maximum(res, "Dose [I-129]")   # (value, time)
to_dict(res); to_matrix(res)   # every series, by label or as a matrix
mass_balance(res)              # the audit, when simulation.mass_balance is on
summary(res)                   # solver, steps, time taken
print(run_log(res))            # the run log, as the application's Run log shows it
res.stats                      # the solver's counts
```

`on_progress=(fraction, t) -> ...` is told how far a run has come.

The solvers are ports of the application's: `ndf` (the default), `ros23` and
`dp45`. With `using OrdinaryDiffEq` loaded, the ids of the methods the
application took from DifferentialEquations.jl -- `fbdf`, `qndf`, `rodas5p`,
`radau5`, `kencarp4`, `trbdf2`, `rosenbrock23`, `tsit5`, `vern7`,
`auto_julia` and `fbdf_krylov` -- are solved by OrdinaryDiffEq itself, handed
the model's analytic Jacobian on its sparsity pattern; such a run agrees with
`ndf` to the tolerance, not to the bit. `auto` is DifferentialEquations.jl's
automatic choice here, as `auto_julia` is: an explicit method while the run
is not stiff and a stiff one once it is. (The application and the Python
package switch between methods of their own under that name.)

### Fast by default, or the Python package to the bit

By default the engine takes Julia's quickest way to an answer within a run's
tolerance:

- A model that asks for the Rosenbrock 2-3 (`ros23`) is solved by the NDF,
  which finished the bundled examples 3 to 24 times sooner, and closer to a
  tightly solved reference. Should the NDF not finish a run, the model's own
  solver runs it; `res.stats["solver"]`, `res.stats["asked"]` and the run log
  say which ran.
- A model whose Jacobian is constant -- a linear one -- takes one Newton
  iteration a step where ode15s's rule takes two (and one whose Jacobian
  moves with the clock alone keeps the rate it measured).
- The derivative's terms are merged into one entry per state and column read,
  each worked out from the values it reads with fused multiply-adds, so a call
  is one sparse product over far fewer entries than there are terms.
- A dense iteration matrix is factorised and solved by Julia's own LU, with
  vector instructions and fused multiply-adds.

`Kompartment.set_solver_policy!(:model)` (or `KOMPARTMENT_SOLVERS=model`)
keeps every model to its own solver. With parity on --
`Kompartment.set_parity!(true)`, or `KOMPARTMENT_PARITY=1` -- the engine does
exactly what the Python package does. Switch before building: a system takes
the setting when it is built, and a run when it starts.

## Solving in parts

A model whose radionuclides fall into groups with no path between them --
decay chains that never reach each other -- can be solved in those parts side
by side, each at the steps its own states need, as the application and the
Python package do it (`simulation.split`: `auto`, the default, `on` or `off`):

```julia
res = run(m; split="on")                 # one bin of parts per thread Julia has
res = run(m; split="on", threads=4)      # in four bins at most
res.stats["split"]                       # what was done, and why
```

The parts are tasks on Julia's threads (start Julia with `--threads=auto`),
not processes: a split starts in milliseconds and nothing is copied back. The
whole model is built first -- its Jacobian says where the parts are, and every
series is worked out on it afterwards -- then each bin of parts is built with
every other material switched off, solved on the output grid, and its states
filed back by name; the far-field paths keep the whole model's layers, and a
min/max or running mean comes back from the part it reads. With parity on, a
bin's run is the Python package's run of the same bin to the bit; a split run
agrees with the whole run to the tolerance.

`auto` splits when it expects that to be clearly quicker: a large model of
many parts before it has been timed, and afterwards by what a whole solve
took and what a split of it measured. A part's build costs here about as much
as the whole model's, whatever it holds, and builds side by side slow each
other down, so auto also weighs how many bins to pack the parts into, up to
one per thread. What it learns is kept by the model's layout in
`split-memory-julia.json`, in the package's scratch space in the Julia depot
(`KOMPARTMENT_CACHE` puts it elsewhere, `KOMPARTMENT_SPLIT_MEMORY=0` keeps
nothing).

A model is not split where that would be wrong or cannot work: a delay, a
snapshot or an event, which reach across parts without showing in the
Jacobian; a far-field path worked out semi-analytically; results at the
solver's own steps; a min/max of something read from more than one part; a
model with no materials to divide by, or one part; one thread.

## Saving results

```julia
save(res, "run.h5")                                   # every series, as the HDF5 result file
save(res, "two.h5"; blocks=["Soil", "Well"])         # the series of two blocks
save(res, "run.h5"; time_origin=2000)                 # /time counted from 2000
save(res, "run.csv")                                  # the application's table
save(res, "run.zip")                                  # the model and its run, as Save with results writes them
res = load_results("run.zip")                         # ... read back as a live run
to_csv(res)                                           # the table as text
```

The HDF5 file is the one the application's *Export to HDF5* writes, laid out
as Ecolego's result browser reads it (`/time`, `/IndexLists/...`, a group per
indexed block, a series per index); for the same numbers it is the Python
package's file to the byte. `blocks` names whole blocks; `outputs` picks
series one by one, as descriptors, labels or positions. `time_origin` moves
only `/time`: the series and the file's start and end times stay the run's.
For the tree itself, `results_tree(res, outputs)` and `write_hdf5(tree)`.

The archive is the application's *Save with results*: the model, the run
log, and the run's state vector at every output time with the recorders'
histories, so the application -- or `load_results`, here or in the Python
package -- opens it as a live run and works every series out from it. A
large model's run is much smaller this way than as every series.

With Tables.jl loaded -- as DataFrames, CSV.jl and the plotting packages load
it -- a run is a table, a `time` column and one per series:
`DataFrame(res)`, or `DataFrame(Kompartment.table(res, outputs(res, "Soil")))`
for some of them.

A probabilistic run goes into an archive beside its model as the application's
*Model with results* carries one (`results/sample/`), and opens there as the
sample it was: `write("run.zip", Kompartment.sample_archive(prob))`.

The application's `serve.py` can hand the page's runs to this package instead of
solving them in the browser. It starts
`julia --project=julia --threads=auto,1 -e 'using Kompartment; Kompartment.serve_stdio()'`
once and keeps it; the protocol is the Python package's (`kompartment.service`),
a run or a probabilistic run kept for the page and asked about included, and the
interactive thread is where a cancel is heard while every other thread solves.
It runs everything the page hands an engine: a run, a probabilistic run, a
tornado, a sensitivity design's runs, a replayed realisation, a calibration and
dy/dp.

## The built model

```julia
sys = build(m)                     # the equations, compiled
y0 = initial_state(sys)
dydt(sys, t, y)                    # the derivative
evaluate_algebraic!(sys, t, y)     # every algebraic value at (t, y)
values_at_start(m, "Soil")         # what a block and its settings come to at the first instant
```

## Scenarios

```julia
runs = run_scenarios(m)                         # one run per scenario: scenario => Results
runs = run_scenarios(m, ["Present", "Drier"]; threads=2, end_time=1e5)
write_scenarios_hdf5(runs, "scenarios.h5")      # side by side in one result file
```

## Probabilistic runs

```julia
prob = run_probabilistic(m, 1000; seed=1, keep=["Dose"])   # on every thread Julia was started with
prob["Dose [I-129]"]                         # every realisation: realisations × times
prob.samples, prob.names                     # what was drawn, input by input
quantiles(prob, "Dose [I-129]")              # the 5th, 50th and 95th percentiles over time
realisations_mean(prob, "Dose [I-129]")
bands(prob)                                  # per series: quantiles, mean, sd, the median's intervals
summary(prob, "Dose [I-129]"; at=:peak)      # one output at one time as a distribution
what_drove(prob, "Dose [I-129]"; at=:max)    # which inputs the spread came from
save(prob, "realisations.h5"; time_origin=2000)   # every realisation, as the application's Save -> Realisations

tor = run_tornado(m; keep=["Dose"])          # each input swung alone to its 5th and 95th percentiles
tornado_table(tor, "Dose [I-129]")

gsa = run_gsa(m, "sobol", Dict("samples" => 500); keep=["Dose"])   # a sensitivity design's runs
gsa.gsa_design["u"]                          # each input's probability at every run
```

The design is drawn whole before any realisation runs, from the named streams
the application draws from -- Latin hypercube or random, correlations put in
by Iman-Conover -- so the values drawn are the application's and the Python
package's to the bit, and the answer does not depend on how many threads
share the work. The model is built once -- built again, it takes the code
compiled the first time -- and every realisation, the first with the rest,
runs on the threads, each on a copy of the built system that shares the
compiled code, its kept series read straight into the results. `seed` and `latin` are the
sampling's (1 and Latin hypercube by default; the model's own are
`simulation(m)["seed"]` and `simulation(m)["sampling"]`). `keep` names the
blocks or series kept, every endpoint by default; `threads`, `range` (a slice
of the design), `varied` and `progress=true` (a progress line) are as in
Python. A realisation that fails is recorded (its row NaN, `prob.ran` 0) and
the run goes on.

Times are given in output-time positions from 1, or `:peak` (where the mean
peaks) and `:max` (each realisation's own peak).

A global sensitivity design (`run_gsa`, or `gsa=` to `run_probabilistic`) is
one of the application's methods -- `"morris"` (random walks, or SALib's
trajectories), `"radial"`, `"sobol"`, `"efast"`, `"rbdfast"`, `"ff"`,
`"dgsm"`, `"shapley"` -- laid out over the varied inputs, a correlation group
moving as one, each point read through the inputs' distributions; Shapley
draws through a Gaussian copula of the model's correlations.
`Kompartment.gsa_options` and `Kompartment.gsa_refusal` say what a method takes
and why it would refuse. The design is the Python package's to the bit
(`Kompartment.build_design`); the indices read off its runs are the page's, or
the Python package's `gsa_table`.

## Calibration and dy/dp

```julia
calibrate(m; targets=[Dict("output" => "Dose [I-129]", "when" => "peak", "value" => 1e-5, "scale" => "log")],
          variables=[Dict("key" => "Kd[I-129]", "lower" => 1e-4, "upper" => 1, "space" => "log")],
          method="lm")                       # or "nelder", "de"
r = run_sensitivity(m, ["Kd[I-129]", "geoTransit"])   # the states and dy/dp, integrated together
r.sens[1][3]                                 # d(state 3)/d(Kd[I-129]) at every output time
elasticity(r.y[3], r.sens[1][3], r.chosen[1]["value"])
```

`calibrate` searches the parameters (`variables_of(m)` lists them, by the
labels the page uses) for the values that put the endpoints at their targets:
Nelder-Mead, Levenberg-Marquardt or differential evolution, each step the
Python package's and the application's, `on_progress` hearing every
evaluation and `signal` stopping the search. `run_sensitivity` integrates the
forward sensitivity equations beside the model -- df/dp differentiated where
the model allows it, differenced otherwise -- and refuses, in words, what they
cannot carry: a jump in the state, a block that remembers the path of the run
where the rates read it, a semi-analytical far-field path, a parameter that
places a corner of the run.

## Speed

A model is built into Julia functions -- the values that never change, those
that follow the clock, those that read the state -- compiled once and called
through function wrappers, so the solvers themselves are compiled once for
every model. The derivative is one sparse product -- over the merged entries
by default, term by term in the application's order with parity on -- and
the Jacobian is the model's own, derived from its equations. The sparse
solves use KLU.

The Python package's timing model -- 16 decay chains of 12 made-up nuclides
through 150 compartments, 28,800 states (`tools/bench.jl`) -- and the bundled
biosphere example, run one after the other on one machine, both warm (the
Python package's compiled code cached, the Julia package precompiled):

| | Julia | Python (compiled) |
|---|---|---|
| Build (and compile) | 0.11 s | 0.51 s |
| Solve, whole model | 1.3 s | 6.0 s |
| Every series to HDF5 | 0.7 s | 13.6 s |
| Biosphere example, 1,000 realisations, one thread / process | 0.52 s | 5.1 s |
| The same on eight | 0.11 s | 1.9 s |
| The timing model split into its 16 chains, four threads / processes | 0.78 s | 5.1 s |
| The same on eight | 0.61 s | 5.4 s |

The Julia rows above the split rows are the engine's default, fast mode; a
model built again takes the code compiled for it the first time (compiling
the timing model's took 0.07 s). The split rows are the Python package's
timing test and this package's, with `KOMPARTMENT_SPLIT_TIMING=1`
(`python/tests/test_engine_split.py`, `test/engine/split.jl`): each run from
the model to its results -- the whole model's build, the parts' builds and
solves, the states filed back -- with every part taking the same steps in
both (parity mode).

The bundled examples build in tens of milliseconds and solve in milliseconds.
Julia compiles the package's own code once, when it is precompiled; a model's
generated code is compiled when the model is first built, a fraction of a
second even for a large assessment, and taken again whenever the same model
is built again in the process. Each solver is compiled once for every model,
whatever a run's settings, recorders, events or progress callback, so a fresh
process does not compile it again: there `using Kompartment` takes about half
a second, and a bundled example's first result, opened from its file and
saved as HDF5, about a third of a second more -- most of it compiling the
model's own equations.

Started with several threads, a large model's derivative is shared out between
them, row by row; the sums are the same, so the run is the same to the bit. It
is shared from 250,000 terms: below that, waking the threads costs more than
they save.

## A script from the file to the result file

```julia
# julia --project=path/to/kompartment/julia --threads=auto run_model.jl assessment.eas
using Kompartment, Printf

source = get(ARGS, 1, "assessment.eas")
blocks = ["Well", "Sea"]          # the blocks whose series go into the file; `nothing` for every series
time_origin = 2000.0              # the file's /time is the run's time less this
probabilistic = false

m = Kompartment.load(source)
m.import_report === nothing || println(m.import_report.summary)   # what an Ecolego import left out
set_simulation!(m; non_negative=false)     # the simulation's "Cannot go negative" switched off

if probabilistic
    sim = simulation(m)                    # the model's own sampling, where it says
    prob = run_probabilistic(m, 1000; seed=get(sim, "seed", 1), latin=get(sim, "sampling", "latin") == "latin",
                             keep=blocks, progress=true)
    save(prob, splitext(source)[1] * "_probabilistic.h5"; time_origin)
else
    res = run(m; on_progress=(f, t) -> @printf("\r  %5.1f%%  t = %.0f", 100f, t))
    println("\n", summary(res))
    save(res, splitext(source)[1] * ".h5"; blocks, time_origin)
end
```

## What the Python package has and this does not

- **Solvers**: SciPy's; `auto` is DifferentialEquations.jl's automatic choice
  here rather than the application's own switching solver.
- **Probabilistic analysis**: the indices read off a global sensitivity
  design's runs (`gsa_table`; the designs and their runs are here), the
  distribution-free measures of *What drove it* (`family="distribution"`) and
  screening realisations by categories.
- Writing an Ecolego project (`.eco`), validating through the application's
  own checks in Node, the App designer, and reading or writing data tables.

## How it agrees with the Python package

The engine is checked against the Python package's, with fixtures the
`tools/` scripts write from it (into a directory outside the repository):

| Check | Tool, then test |
|---|---|
| Layout, invariant values, initial state, derivative at five states | `tools/engine_fixtures.py DIR`, `KOMPARTMENT_ENGINE_FIXTURES=DIR julia --project=. test/engine/parity.jl` |
| Whole runs: steps, times, every series, the CSV | `tools/run_fixtures.py DIR`, `KOMPARTMENT_RUN_FIXTURES=DIR julia --project=. test/engine/runs.jl` |
| The solvers, step by step | `test/solvers/runtests.jl` (fixtures included) |
| The far-field pathway | `tools/farfield_fixtures.py DIR`, `KOMPARTMENT_FARFIELD_FIXTURES=DIR julia --project=. test/engine/farfield.jl` |
| A model opened and written: normalisation, units, stamps | `tools/model_fixtures.py DIR`, `KOMPARTMENT_MODEL_FIXTURES=DIR/text julia --project=. test/model/normalise.jl` |
| Transports and unit literals: expansion, derivative, runs | `tools/model_fixtures.py DIR` (and `engine_fixtures.py`, `run_fixtures.py` on its models), `KOMPARTMENT_TRANSPORT_FIXTURES=DIR julia --project=. test/engine/transport.jl` |
| Editing: the model's file after every edit, and every refusal | `tools/edit_fixtures.py DIR`, `KOMPARTMENT_EDIT_FIXTURES=DIR julia --project=. test/model/edit.jl` |
| Solving in parts: the partition, every plan and refusal, split runs to the bit | `tools/split_fixtures.py DIR`, `KOMPARTMENT_SPLIT_FIXTURES=DIR julia --project=. --threads=4 test/engine/split.jl` |
| Probabilistic runs: every draw, every realisation, the analysis, the result files | `tools/prob_fixtures.py DIR`, `KOMPARTMENT_PROB_FIXTURES=DIR julia --project=. --threads=auto test/engine/probabilistic.jl` |
| Sensitivity designs, every step of a calibration, dy/dp and the refusals | `tools/analysis_fixtures.py DIR`, `KOMPARTMENT_ANALYSIS_FIXTURES=DIR julia --project=. test/engine/analyses.jl` |
| The Ecolego importer | `tools/eco_fixtures.py DIR`, `KOMPARTMENT_ECO_FIXTURES=DIR julia --project=. test/importers/test_eco.jl` |
| The HDF5 files, byte for byte | `tools/hdf5_fixtures.py DIR`, `KOMPARTMENT_H5_FIXTURES=DIR julia --project=. test/io/test_hdf5.jl` |

Each tool runs on the Python package (`PYTHONPATH=../python`). `julia
--project=. test/runtests.jl` runs every test file, each parity test where its
variable is set and the rest of it regardless. These tests switch parity on.

With parity on, every bundled example runs to the same bits as the Python
package. A model whose iteration matrix is factorised sparse (from 64 states,
where its factor stays sparse) parts at round-off: the factorisations are KLU's
here and the application's sparse LUs in Python, so the runs agree to the
tolerance, as two machines do.

The default, fast mode is held to parity mode's accuracy instead
(`test/engine/fast.jl`): every bundled example is solved to a far tighter
tolerance, and its fast run must come within three times parity mode's error
of that, or ten times the run's own tolerance.

Some things needed care to come out the same. The model's arithmetic calls
the C library, as numpy does, rather than Julia's own `exp`, `log` and `^`,
which round differently for a few arguments in a hundred; numpy's shortcut for
a power of 2, 0.5 or -1 is taken where numpy takes it; the minimum and maximum
keep the first of equal values; the time grid and the solvers' step-size
formulas use the application's own JavaScript arithmetic.
