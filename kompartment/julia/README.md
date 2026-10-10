# Kompartment for Julia

Open a Kompartment model -- or an Ecolego project or assessment -- in Julia,
edit it, build it into equations, run it with the application's own solvers
and save what it produced, as the table or as the HDF5 result file the
assessment tools read. The package is a port of the Python package, and a run
here is that package's run to the last bit on every bundled example: the same
model loaded the same way, the same equations in the same order, the same
steps. What Julia adds is speed: the equations are compiled to native code,
probabilistic runs share the threads, and the whole path from file to result
file is several times quicker than Python's.

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
```

The design is drawn whole before any realisation runs, from the named streams
the application draws from -- Latin hypercube or random, correlations put in
by Iman-Conover -- so the values drawn are the application's and the Python
package's to the bit, and the answer does not depend on how many threads
share the work. The model is built once; each thread runs its share on a copy
of the built system that shares the compiled code. `seed` and `latin` are the
sampling's (1 and Latin hypercube by default; the model's own are
`simulation(m)["seed"]` and `simulation(m)["sampling"]`). `keep` names the
blocks or series kept, every endpoint by default; `threads`, `range` (a slice
of the design), `varied` and `progress=true` (a progress line) are as in
Python. A realisation that fails is recorded (its row NaN, `prob.ran` 0) and
the run goes on.

Times are given in output-time positions from 1, or `:peak` (where the mean
peaks) and `:max` (each realisation's own peak).

## Speed

A model is built into Julia functions -- the values that never change, those
that follow the clock, those that read the state -- compiled once and called
through function wrappers, so the solvers themselves are compiled once for
every model. The derivative is assembled as one sparse product in the
application's order, and the Jacobian is the model's own, derived from its
equations. The sparse solves use KLU.

The Python package's timing model -- 16 decay chains of 12 made-up nuclides
through 150 compartments, 28,800 states (`tools/bench.jl`) -- and the bundled
biosphere example, run one after the other on one machine, both warm (the
Python package's compiled code cached, the Julia package precompiled):

| | Julia | Python (compiled) |
|---|---|---|
| Build (and compile) | 0.11 s | 0.51 s |
| Solve, whole model | 2.3 s | 6.0 s |
| Every series to HDF5 | 0.7 s | 13.6 s |
| Biosphere example, 1,000 realisations, one thread / process | 3.0 s | 5.1 s |
| The same on eight | 0.6 s | 1.9 s |

The bundled examples build in tens of milliseconds and solve in milliseconds.
Julia compiles the package's own code once, when it is precompiled; a model's
generated code is compiled when the model is built, a fraction of a second
even for a large assessment.

Started with several threads, a large model's derivative is shared out between
them, row by row; the sums are the same, so the run is the same to the bit.

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

- **Solving in parts** (`simulation.split`): a model is always solved whole
  here, which on this engine is quicker than the Python package's split.
- **Solvers**: SciPy's; `auto` is DifferentialEquations.jl's automatic choice
  here rather than the application's own switching solver.
- **Probabilistic analysis**: the global sensitivity designs (`gsa=`), the
  distribution-free measures of *What drove it* (`family="distribution"`) and
  screening realisations by categories.
- Writing an Ecolego project (`.eco`), validating through the application's
  own checks in Node, the App designer, the local-sensitivity and calibration
  helpers, and reading or writing data tables.

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
| Probabilistic runs: every draw, every realisation, the analysis, the result files | `tools/prob_fixtures.py DIR`, `KOMPARTMENT_PROB_FIXTURES=DIR julia --project=. --threads=auto test/engine/probabilistic.jl` |
| The Ecolego importer | `tools/eco_fixtures.py DIR`, `KOMPARTMENT_ECO_FIXTURES=DIR julia --project=. test/importers/test_eco.jl` |
| The HDF5 files, byte for byte | `tools/hdf5_fixtures.py DIR`, `KOMPARTMENT_H5_FIXTURES=DIR julia --project=. test/io/test_hdf5.jl` |

Each tool runs on the Python package (`PYTHONPATH=../python`). `julia
--project=. test/runtests.jl` runs every test file, each parity test where its
variable is set and the rest of it regardless.

Every bundled example runs to the same bits as the Python package. A model
large enough for the sparse solver (above 200 states) parts at round-off:
the factorisations are KLU's here and SuperLU's in Python, so the runs agree to
the tolerance, as two machines do.

Some things needed care to come out the same. The model's arithmetic calls
the C library, as numpy does, rather than Julia's own `exp`, `log` and `^`,
which round differently for a few arguments in a hundred; numpy's shortcut for
a power of 2, 0.5 or -1 is taken where numpy takes it; the minimum and maximum
keep the first of equal values; the time grid and the solvers' step-size
formulas use the application's own JavaScript arithmetic.
