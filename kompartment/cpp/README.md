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

The arithmetic is never the compiler's to rearrange: nothing is contracted into
a fused multiply-add unless the code asks for one, and no flag lets a sum be
reordered. That is what makes a run reproducible to the bit across compilers
and across the engines.

## Running a model

```
kompartment-cpp model.json [--csv out.csv] [--repeat n] [--parity]
kompartment-cpp --serve
kompartment-cpp --version
```

The model is a Kompartment model file (`.json`). The program says what it ran
-- the states, the time to read, build and solve, the solver and its steps --
and with `--csv` writes every output as the application's results table has
them. `--repeat` runs it again, for timing. `--parity` (or `KOMPARTMENT_PARITY=1`)
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
letting go asked for afterwards. What it does not do it refuses before anything
runs, by a name the page knows, and the page then does that piece itself, in
the browser, and says so.

## What it does, and what it leaves to the other engines

It runs a model: every block the builder knows -- compartments, transfers,
inflows, expressions, lookup tables and their interpolations, functions,
reductions over indices and blocks, recorders, events and their jumps,
snapshots, waste packages, disruptive events, decay and ingrowth, scenarios
pinned, numbers written with a unit, transport sub-systems written out as their
chains, far-field paths on cells -- with the `ndf`, `ros23` and `dp45` solvers, the exact Jacobian or the
differenced one, the dense, sparse, kept-pivot and block-at-a-time LUs, the
zero floor, the mass-balance audit, the derived outputs, and the archive *Save
with results* writes.

It does not do: far-field paths worked out semi-analytically (paths on cells,
the default, it does); probabilistic runs, replays, calibrations and
sensitivities (the page does these itself when the engine is chosen); the other
solvers (`auto`, the DifferentialEquations.jl ports, SciPy's); HDF5 result
files; Ecolego files; editing a model. A model that needs one of these is
refused with a sentence saying which, and no number is made up for it.

## How it is laid out

| | |
|---|---|
| `src/util/` | An ordered JSON value, numbers written and read as JavaScript writes and reads them, the parity switch |
| `src/lang/` | The equation language: tokens, the parser, the functions, V8's `exp`, `log` and `pow` to the bit |
| `src/model/` | Names, the decay data (ICRP 107 as the application carries it, compiled in by `tools/embed_data.py`), index lists, the simulation's settings |
| `src/engine/project.*` | A model file read and checked, refusals word for word |
| `src/engine/builder*` | The layout of states, parameters and algebraic slots; statements as trees; phases, jumps, events |
| `src/engine/vm.*` | The statements compiled to vector programs, and run |
| `src/engine/system.*` | The passes (never changing, following the clock, following the state), the assembly `dy/dt = A(X)·[y; 1]`, recorders, events |
| `src/engine/jacobian*` | The Jacobian's structure, the differenced one, the exact one |
| `src/engine/farfield*` | A far-field path on cells: its geometry, its layers, its release |
| `src/engine/runner.*` | A run: segments between switch times, events, the outputs, the audit |
| `src/solvers/` | NDF/BDF, Rosenbrock 2-3, Dormand-Prince 4-5, event location, the LUs |
| `src/io/` | ZIP, the dataset archive |
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
| `test_solvers`, `test_sparselu` | The solvers and the LUs on problems of their own | fixtures within; `KOMPARTMENT_SPARSE_FIXTURES` for the application's own matrices (see `../julia/README.md`) |
| `test_service` | The messages `serve.py` and the engine exchange | |
| `test_util` | JSON and the number formats | |

To write the fixtures again, after a change to the Julia package or to a tool
(from `../julia`, in this order -- each reads the one before):

```sh
for t in lang project transport unit builder system jacobian run farfield; do
  julia --project=. ../cpp/tools/${t}_fixtures.jl
done
```

With `KOMPARTMENT_FIXTURE_DUMPS=DIR` set, the tools and the tests both write
the full text they hash into `DIR`, one file a case, so that a difference can
be read with `diff`.
