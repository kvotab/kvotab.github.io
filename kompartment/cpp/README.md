# Kompartment's engine in C++

Build a Kompartment model into equations and run it, from the command line or
behind the application's local server, as fast as the machine allows. The
engine is a port of the Julia package (`../julia`), which is a port of the
Python package and the application: the same model file, the same equations in
the same order, the same solvers taking the same steps. With parity on it gives
the Julia package's run in parity mode -- which is the Python package's -- to
the last bit; that is how it is checked. (The application's own run differs in
the last digits, as the Python package's does: V8's `Math.pow`, which chooses
each step size, rounds differently from the C library's.) Without parity (the
default) the same run is taken the quickest way, and agrees to the run's
tolerance.

Nothing waits for a compiler when a model is opened. Where the other engines
write a model's equations out as source code and have it compiled -- a fraction
of a second in the browser, seconds in Julia, a minute the first time in Python
-- this one compiles each statement into a short program of vector
instructions, in microseconds, and runs those a block of elements at a time. A
bundled example is read, built and solved in a few milliseconds, the process's
start included.

```sh
cmake -S . -B ~/.kompartment/cpp -DCMAKE_BUILD_TYPE=Release
cmake --build ~/.kompartment/cpp -j
~/.kompartment/cpp/kompartment-cpp ../examples/biosphere.json --csv biosphere.csv
```

## Building

A C++20 compiler and CMake 3.20. There is nothing else to install: the engine
has no dependencies. Where zlib is found, the archives it writes are compressed
with it; without it they are stored. It is written in standard C++ and has
been built and tested with Apple Clang 21 on an Apple-silicon Mac; the build
file has the settings for GCC and for Visual C++, which have not been tried.

Build somewhere outside this folder -- the line above uses the place
`serve.py` looks in and builds into. Options:

| Option | Default | |
|---|---|---|
| `KOMPARTMENT_NATIVE` | `ON` | Compile for this machine's processor. Turn it off for a program that is to run on other machines. |
| `KOMPARTMENT_SANITIZE` | `OFF` | The address and undefined-behaviour sanitizers, for the tests. |
| `KOMPARTMENT_EXCLUDE` | | A regular expression: sources and tests whose paths match are left out. |

The build writes a stamp of the engine's sources and of how they were compiled
(`tools/build_stamp.cmake`): what auto learns about splitting a model is kept
by it, so that what one build measured is not taken to hold for another.

The arithmetic is never the compiler's to rearrange: nothing is contracted into
a fused multiply-add unless the code asks for one, and no flag lets a sum be
reordered. That is what makes a run reproducible to the bit across compilers
and across the engines.

## Running a model

```
kompartment-cpp model.json [--csv out.csv] [--h5 out.h5] [--repeat n] [--split auto|on|off] [--threads n] [--parity]
kompartment-cpp model.json --probabilistic n [--seed s] [--h5 out.h5 [--want all|mean|k]] [--threads n] [--parity]
kompartment-cpp model.json --scenarios [--h5 out.h5] [--threads n] [--parity]
kompartment-cpp project.eco --import out.json
kompartment-cpp --serve
kompartment-cpp --version
```

The model is a Kompartment model file (`.json`), or an Ecolego project
(`.eco`), assessment (`.eas`) or model XML (`.xml`), imported as the Julia
package's `load` imports one: what the import left out, renamed or switched off
is said before the run. `--import out.json` writes the imported model instead
-- the importer's project, byte for byte the Julia package's -- says what the
import did, and runs nothing. The program says what it ran
-- the states, the time to read, build and solve, the solver and its steps, and
what a split did -- and with `--csv` writes every output as the application's
results table has them. `--repeat` runs it again, for timing. `--split` sets
the model's *Split into parts* for the run, and `--threads` the most threads a
split, a probabilistic run or scenarios use (the machine's cores by default).
`--h5` writes the HDF5 result file the application's *Export to HDF5* writes,
byte for byte the other engines' for the same run. `--probabilistic n` runs n
realisations over the model's distributions and says how it went; its file is
*Save → Realisations*: every realisation as float32, their mean, or one by
number (`--want`). `--scenarios` runs the model once for each of its scenarios,
side by side, and `--h5` writes them all. `--stamp` fixes the file's
`created_time`, so that the same run gives the same bytes. `--parity` (or `KOMPARTMENT_PARITY=1`)
gives the other engines' numbers to the bit. Without it a model that asks for
the Rosenbrock 2-3 is run with the NDF where that finishes, as the Julia
package runs it; `KOMPARTMENT_SOLVERS=model` keeps every model to its own
solver.

## Behind the application

`python3 serve.py` in the application's folder finds the engine built in
`~/.kompartment/cpp`, offers to build it where it is missing or older than its
source (`python3 serve.py --setup` builds it without asking), and the page then
offers *on C++* beside **Run**. `--cpp PATH` names a program built elsewhere,
`--no-cpp` leaves the engine out, `--engine cpp` starts the page on it.

The engine speaks the Python and Julia engines' protocol (`src/service.cpp`): a
run, a run kept on the engine with its series, its whole archive and its
letting go asked for afterwards; a probabilistic run, a tornado or a
sensitivity design's runs, a sample kept on the engine and asked for its bands,
its realisations, a time across them or one of them; one realisation replayed;
dy/dp for the parameters a job names; a calibration, each step's best said as
it goes and its answer written as JSON; a job cancelled. Errors are named as the Julia engine names them. What it does
not do it refuses before anything runs, by a name the page knows, and the page
then does that piece itself, in the browser, and says so.

## What it does, and what it leaves to the other engines

It runs a model: every block the builder knows -- compartments, transfers,
inflows, expressions, lookup tables and their interpolations, functions,
reductions over indices and blocks, recorders, events and their jumps,
snapshots, waste packages, disruptive events, decay and ingrowth, scenarios
pinned, numbers written with a unit, transport sub-systems written out as their
chains, far-field paths on cells and worked out semi-analytically -- with the
`ndf`, `ros23` and `dp45` solvers, the exact Jacobian or the differenced one,
the dense, sparse, kept-pivot and block-at-a-time LUs, the zero floor, the
mass-balance audit, the derived outputs, and the archive *Save with results*
writes, with the run log the page shows under *Run log* (the Julia package's,
word for word, its build line saying *C++ engine*). A run that stops on a value
that is not a number says, as the page does, where that value started: the
compartment it reached, the transfer that carried it, the one operation that
made it and the values that operation read.

It runs a model probabilistically: a sample (Latin hypercube or independent
draws, correlations put in by Iman-Conover, any inputs held), a tornado, or the
runs of a global sensitivity design (Morris, radial, Sobol, eFAST, RBD-FAST,
fractional factorial, DGSM, Shapley), the realisations shared out between
threads, each on a copy of the built system of its own, with the same bits on
any number of them as on one. Every realisation of the series kept is held, as
float32 past what the page says the machine can hold as doubles; the run is
written as the application's sample archive (`results/sample/`), or kept on the
engine and asked for its bands, its realisations, a time across them or one of
them. One realisation is replayed as a run of its own, and a probabilistic run
has its log.

It integrates dy/dp for the parameters asked for (up to twelve): the forward
sensitivity equations `[y, S_1 ... S_m]` in one NDF solve, run by the runner's
own machinery -- switch times, discrete events, the blocks that remember, each
compartment's floor (each sensitivity held with its state: zero while the floor
holds it), the clock's interpolation --, J·S from the exact
Jacobian, df/dp differentiated where the model allows it (far-field paths'
rates included) and differenced otherwise, the iteration matrix solved a block
at a time. What the equations cannot carry -- a jump in the state, a history
the rates read, a semi-analytical path, a parameter that places a corner of the
run -- is refused in the Julia package's words, and a differenced solve that
gives up says why.

It calibrates: Nelder-Mead, Levenberg-Marquardt or differential evolution
search the parameter slots a job names, in their values or their logarithms,
between their bounds, for the values that put the endpoints where the targets
say -- at the peak, at the end, or at the output time nearest. Each evaluation
is a run of the system built once, and a corner that will not solve counts as
a miss of 1e6 per target. Each step is said as it goes; the steps and the
answer are the Julia package's to the bit.

It solves a model in its independent parts, side by side, as *Split into
parts* says (`simulation.split`: auto, on, off). The parts are read off the
Jacobian's pattern; the jobs -- sets of materials whose states reach no
other's -- are packed into a bin per thread, and each bin, the model with every
other material switched off, is built and solved on the output grid at its own
steps on a thread of its own, holding the whole model's far-field layers. Its
states and its recorders' histories are filed back by name, and a split that
does not add up is solved whole. The plan, its refusals and its words are the
Julia package's, and the bins are its runs of them to the bit, on any number of
threads. Auto weighs a split by this engine's own measured numbers and learns
what runs of a model cost: `split-memory-cpp.json` in `KOMPARTMENT_CACHE`, else
in `~/.kompartment/cpp/`, kept by the model's layout and this build's stamp
(`KOMPARTMENT_SPLIT_MEMORY=0` keeps it in the process only).

It writes the application's HDF5 result files, byte for byte the other
engines': a run's, a probabilistic run's (every realisation, their mean or one
of them), several scenarios' side by side; and saves a run by the name's ending
(`.h5`, `.csv`, `.zip`).

It imports Ecolego projects, assessments and Ecolego 4/5 model XML as the Julia
package does: the same project, key order included, the same report of what
was skipped, noted, renamed, switched off and warned about, and every refusal
in the same words. The archive is read as Python's zipfile reads it, the text
decoded as CPython decodes it, the XML by the same small reader; archives are
inflated by the engine's own inflater, written to zlib's 1.3.1, whatever zlib
the build has (Apple's words its errors otherwise).

It does not do: the other solvers (`auto`, the DifferentialEquations.jl ports,
SciPy's); editing a model; the normalisation the other engines put a model
through as they open it. A model that needs a solver it lacks is refused with a
sentence saying which, and no number is made up for it. Without the
normalisation, an Ecolego import runs as the importer gives it, where the Julia
package's `load` normalises it first: a few models the normalisation mends are
refused here, and a refusal may name a list it would have renamed; and the
model an archive carries is the file as it was given, where the other engines
write it as they normalised it.

## How it is laid out

| | |
|---|---|
| `src/util/` | An ordered JSON value, numbers written and read as JavaScript writes and reads them (`toFixed`, `toExponential` and `toPrecision` too, to the exact digit), the parity switch, the Julia package's errors, the C library's `sin`, `cos` and `asin`, the lock for caches threads share |
| `src/lang/` | The equation language: tokens, the parser, the functions, V8's `exp`, `log` and `pow` to the bit |
| `src/model/` | Names, the decay data (ICRP 107 as the application carries it, compiled in by `tools/embed_data.py`), index lists, the simulation's settings |
| `src/engine/project.*` | A model file read and checked, refusals word for word |
| `src/engine/builder*` | The layout of states, parameters and algebraic slots; statements as trees; phases, jumps, events |
| `src/engine/vm.*` | The statements compiled to vector programs, and run |
| `src/engine/system.*` | The passes (never changing, following the clock, following the state), the assembly `dy/dt = A(X)·[y; 1]`, recorders, events |
| `src/engine/jacobian*` | The Jacobian's structure, the differenced one, the exact one |
| `src/engine/farfield*` | A far-field path: on cells (its geometry, layers and release), or worked out semi-analytically (unit responses inverted from the Laplace domain, and their convolution with what flows in) |
| `src/engine/runner.*` | A run: segments between switch times, events, the outputs, the audit; equations standing over the model's own (dy/dp's) |
| `src/engine/calibrate.*` | A calibration: an endpoint read off a run, the variables a model offers, the search against the system built once |
| `src/engine/split.*` | A model solved in its independent parts: the partition, the jobs, the plan and what auto learns, a bin's model, the bins run on threads and filed back into one run |
| `src/engine/localsens.*` | dy/dp: the parameter slots and states as the page names them, what the forward equations cannot carry, the augmented system with its Jacobian and block iteration matrix, the run, its failures said again, elasticities |
| `src/engine/paramtangent.*` | df/dp differentiated: the statements' tangents seeded on the parameters, through the blocks that remember and far-field rates, and why it is refused where it is |
| `src/engine/runlog.*` | The run log, in the application's words |
| `src/engine/nonfinite.*` | Where a value that is not a number came from, followed back through the equations at the state the solver held |
| `src/engine/probabilistic*` | A probabilistic run: the sampling plan, every realisation's values (a sample, a tornado or a sensitivity design), what a realisation sets into a system, the realisations run on threads and kept, one replayed |
| `src/engine/analysis.*` | A probabilistic run's bands: the quantiles, mean, standard deviation and the median's intervals of every series at every time, over the realisations a mask keeps |
| `src/engine/errorinfo.*` | An error as the Julia package names and shows it |
| `src/stats/` | The statistics a probabilistic run draws with: the normal distribution, the distributions and their draws under JavaScript's rules, named streams and Latin hypercube columns, correlations put in by Iman-Conover, every sensitivity method's design, and the optimisers a calibration searches with |
| `src/solvers/` | NDF/BDF, Rosenbrock 2-3, Dormand-Prince 4-5, event location, the LUs |
| `src/io/` | ZIP, the dataset archive, the sample archive (`results/sample/`), HDF5 written byte for byte (groups, datasets, attributes, the global heap, lookup3) and the result files on it |
| `src/engine/scenarios.*` | A model run once per scenario, side by side on threads |
| `src/importers/` | The Ecolego importer: the project and its report (`eco.*`), the archive as Python's zipfile reads it (`eco_zip.*`) and its inflater (`inflate.*`), the XML reader (`xml.*`), text as CPython decodes it (`eco_text.*`), distributions as Ecolego writes them (`eco_pdf.*`), JavaScript's and Python's rules and the small maps (`eco_maps.*`), Python's case tables (`eco_unicode.*`, written by `tools/eco_unicode.jl`) |
| `src/service.*`, `src/main.cpp` | The engine behind `serve.py`, and the command line |

In fast mode a model whose derivative is linear in the state is assembled once
into one matrix with the constant column beside it and applied with fused
multiply-adds, and a run of single-state blocks in the block LU is solved with
reciprocal pivots. In both modes, as in the other engines, a step of a linear
model takes one Newton iteration, the rate of the iteration being known.

## Speed

Measured on an Apple M1 Max, one thread, on a model made up for the purpose --
16 decay chains of 12 nuclides through 150 compartments in a row, 28,800
states, solved with the NDF to a relative tolerance of 1e-8 in 1,626 steps --
the time to solve, the model already built:

| Engine | Seconds |
|---|---|
| The application, in Node | 3.9 |
| Python, compiled | 1.7 |
| Julia, parity | 1.04 |
| Julia | 1.0 |
| C++, parity | 0.92 |
| C++ | 0.83 |

Building that model takes 0.1 s here. The bundled examples are each read, built
and solved in 1 to 11 ms.

A probabilistic run of the bundled biosphere example, 1,000 realisations of 40
series at 400 times, takes 0.40 s on one thread and 0.07 s on eight (Julia:
0.50 and 0.11 s); 40 realisations of the far-field example given a spread, 5.2
and 0.70 s (Julia: 5.7 and 0.82 s).

dy/dp of the biosphere example to five parameters takes 7 ms (Julia 51 ms); of
the far-field example to two, 3,832 steps of 4,743 equations, 0.96 s (Julia
9.3 s), in the same steps. A calibration of the biosphere example takes 21 ms
by Nelder-Mead (59 runs), and 0.10-0.12 s by Levenberg-Marquardt or
differential evolution (300 runs each); Julia takes 27, 134 and 149 ms.

The benchmark model above falls apart into its 16 chains, and split into parts
(the whole run, build and solve, in seconds):

| Engine | Whole | 2 threads | 4 threads | 8 threads |
|---|---|---|---|---|
| C++ | 0.83 | 0.47 | 0.27 | 0.15 |
| C++, parity | 0.93 | 0.52 | 0.29 | 0.16 |
| Julia | 1.23 | 0.87 | 0.63 | 0.50 |

A split run agrees with the whole one to within 7e-9 of the peak. Auto splits
it on eight threads from its first run here.

A result file of 300,000 series of 250 values (799 MB) is built and written in
0.88 s (Julia 0.97 s).

## Tests

```sh
ctest --test-dir ~/.kompartment/cpp --output-on-failure
```

Each `tests/test_*.cpp` is a program of its own. Most compare this engine with
the Julia package through fixtures in `tests/fixtures/`, written by the Julia
tools in `tools/`: a tool builds or runs every bundled example and a set of
models made up to reach each branch, writes what came out as text, and keeps a
hash of it; the test makes the same text here and compares. Nothing is compared
to a tolerance where the two are meant to agree to the bit.

| Test | Against | Written by |
|---|---|---|
| `test_lang` | The parser, the functions and the number formats on some 13,000 inputs | `tools/lang_fixtures.jl` |
| `test_project` | Every model read, and every refusal word for word | `tools/project_fixtures.jl` |
| `test_transport`, `test_unitcheck` | Transports written out; units read, compared and converted | `tools/transport_fixtures.jl`, `tools/unit_fixtures.jl` |
| `test_builder` | The layout, the statements, the phases and the jumps of every model | `tools/builder_fixtures.jl` |
| `test_system` | The initial state, the slots and the derivative at three points, to the bit; the fast assembly to 1e-9 | `tools/system_fixtures.jl` |
| `test_jacobian` | The exact Jacobian's plan and values | `tools/jacobian_fixtures.jl` |
| `test_runs` | Every series of every run, and the step counts, to the bit, with the exact Jacobian and the differenced one | `tools/run_fixtures.jl` |
| `test_farfield` | Far-field paths on cells: the helpers, 113 models laid out, differentiated and run, the refusals | `tools/farfield_fixtures.jl` |
| `test_laplace` | A semi-analytical path's Laplace-domain transfer functions and their inversion: 73 paths, their unit responses and evaluation counts, the complex arithmetic, 38 refusals | `tools/laplace_fixtures.jl` |
| `test_farfield_semi` | Semi-analytical paths in a run: 53 models laid out, differentiated and run, their histories, restarts and balance warnings, the refusals | `tools/farfield_semi_fixtures.jl` |
| `test_solvers`, `test_sparselu` | The solvers and the LUs on problems of their own, and on the problems the Python package's solvers were run on | `../julia/test/solvers/fixtures.json` (the Julia package's); `KOMPARTMENT_SPARSE_FIXTURES` for the application's own matrices (see `../julia/README.md`) |
| `test_runlog` | The run log: 780 numbers written as the page writes them, and the logs of 370 runs, word for word | `tools/runlog_fixtures.jl` |
| `test_nonfinite` | 56 models that make a value that is not a number, run on each solver: where it is said to start, the warnings before a run, equations written back out | `tools/nonfinite_fixtures.jl` |
| `test_stats` | The statistics: JavaScript's reading of values, named streams and columns of uniforms, the normal functions, 105 distributions at 42 probabilities and 61 values, correlations and Iman-Conover, every sensitivity method's settings, runs, refusals and design, settings past what a double counts among them; 1,960 cases | `tools/stats_fixtures.jl` |
| `test_design` | Designs on 15 made-up models and every bundled example under many settings (a tornado's ends given as numbers, text, null and the rest), every value drawn, ranges of realisations, 1,706 realisations set into systems (parameters, invariant slots, tables, events and their occurrence times), 156 refusals word for word | `tools/design_fixtures.jl` |
| `test_probabilistic` | Probabilistic runs of 22 made-up models (7 of them bundled examples given a spread) and every bundled example: every realisation of every series kept, to the bit (float32 too), the samples, inputs, statistics and log, the sample archive's entries, bands under 5 lists of percentiles and 6 masks, the service's answers and refusals; 12 replays; every run again on 2 and 8 threads, the same bits | `tools/probabilistic_fixtures.jl` |
| `test_calibrate` | The three optimisers on 114 made-up problems (every step, budgets, stopped searches, refusals), the objective, the elimination, the keys and lookups; endpoints read off 32 models' runs, the variables they offer; 103 calibrations of bundled examples and made-up models (each method, seeds, budgets, log space, a corner that will not solve, 27 refusals word for word), every step and answer to the bit | `tools/calibrate_fixtures.jl` |
| `test_ecoimport` | The Ecolego importer: 185 byte strings decoded, numbers, roundings and dates as JavaScript and Python read them, every code point through Python's case mappings, 146 XML documents element by element, 28 distributions, 87 deflate streams under 7 limits, 99 archives entry by entry, 225 imports (126 model texts reaching every branch, 99 files -- every encoding, every damage the reader names, two past the 256 MB allowance); the build's zlib against the engine's inflater on them and on 3,000 damaged streams; with `KOMPARTMENT_ECO_FIXTURES`, 1,329 synthetic cases against the Julia and the Python package | `tools/ecoimport_fixtures.jl`; `KOMPARTMENT_ECO_FIXTURES` for the synthetic cases |
| `test_hdf5` | HDF5 files byte for byte: 23 trees built step by step, lookup3 on 107 byte strings, 1,253 strings as `TextEncoder` writes them (overlong forms among them); 26 made-up result trees, every bundled example's run and 7 made-up models, 57 files of 13 probabilistic runs (each again on four threads) and 17 of results made by hand, 12 scenario files, 13 saves; 27 refusals word for word; the files read back as libhdf5 begins to | `tools/hdf5_fixtures.jl` |
| `test_split` | The partition, the states' names and materials, the jobs, 4,950 plans and the layers of every bundled example and 27 made-up models; 33 split runs at 2 and 4 threads and on bins fixed by hand (every state, series, count, account and run log to the bit), again on 1, 2, 3 and 8 threads with the same bits; a split solved whole; the formulas; parts assembled and refused; measurements close or not; progress, a stop, what auto learns and its file, a file written by hand with what is not a number in it | `tools/split_fixtures.jl` |
| `test_localsens` | dy/dp of every builder model, the bundled examples and 57 made-up models (among them the zero floor holding a state -- alone, feeding another, held and released, by index, through an event), differentiated and differenced: the problem, the run to the bit, the refusals word for word; 189 models' parameter slots, what cannot be carried per slot and df/dp at three points; 108 failures said again; 396 cases | `tools/localsens_fixtures.jl` |
| `test_service` | The messages `serve.py` and the engine exchange: a run's log in its archive, a run that stops on a value that is not a number, a probabilistic run kept and asked every question, a tornado, which is never kept as a sample is (a tornado of 0 is one, as the design takes it; of `{}`, none), a sensitivity design, a replay, dy/dp answered, refused and stopped (the answer byte for byte the Julia engine's), a calibration answered (every progress detail and its answer the Julia engine's), refused and stopped, a model refused where the Julia engine's job refuses it, a cancel, errors named as the Julia engine names them | |
| `test_util` | JSON and the number formats | |

To write the fixtures again, after a change to the Julia package or to a tool
(from `../julia`, in this order -- each reads the one before):

```sh
for t in lang project transport unit builder system jacobian run farfield laplace farfield_semi runlog nonfinite stats design probabilistic localsens calibrate split hdf5 ecoimport; do
  julia --project=. ../cpp/tools/${t}_fixtures.jl
done
```

The importer's synthetic cases come from the Python package's tool --
`python3 tools/eco_fixtures.py DIR --synthetic --more 400` from `../julia`
(Python and Node; `DIR` outside the repository) -- and `ecoimport` keeps the
cases already in its file unless `KOMPARTMENT_ECO_FIXTURES=DIR` names them
again; the same variable lets `test_ecoimport` read them.

With `KOMPARTMENT_FIXTURE_DUMPS=DIR` set, the tools and the tests both write
the full text they hash into `DIR`, one file a case, so that a difference can
be read with `diff`.

A test's runs are not this machine's runs of a model: every test program keeps
what auto learns about splitting to itself (`KOMPARTMENT_SPLIT_MEMORY=0`, set
by CTest and by the tests' own helpers when a test is run on its own), and
`test_split` points it at a folder of its own where it tests it.
