# Kompartment

Compartment modelling in a browser tab. Draw the boxes, say what flows between
them, press Run: a system of ordinary differential equations is assembled from
what you drew, integrated by a stiff solver, and plotted.

No build step, no dependencies, no server-side code — `index.html` and the
files beside it are the whole of it.

```sh
python3 serve.py          # http://localhost:8080/
```

(Do not open `index.html` by double-clicking. Browsers refuse to load ES
modules from a `file://` page, so you get the toolbar and nothing behind it.)

Published, it answers at two addresses: `kompartment.html` one level up frames
it in the site's own header and footer, and this directory serves the same tool
on its own. Two query parameters are what the difference is made of --
`?brand=` picks up the site's palette and `?chrome=` tells the tool that a page
has a header and a footer of its own, so it insets itself between them and
hands over its light/dark switch. See `css/theme-kvotab.css` and
`src/ui/start.js`.

## What it is for

The kind of model a radiological safety assessment is made of: inventories in
becquerels moving between compartments over a hundred thousand years, indexed
by radionuclide and by landscape object, with decay chains, solubility limits,
discrete events and a far-field pathway. It reads the project files those
assessments are usually written in (`.eco` and `.eas`), so an existing model
can be opened, run and compared rather than retyped.

Ten worked examples ship with it — open one from the Help tab or with
`?model=biosphere.json` in the URL.

## What is in the box

- **A graphical editor.** Compartments, transfers, expressions, parameters,
  lookup tables, sub-systems and transports, on an SVG canvas with undo.
- **N-dimensional models.** Index lists turn one drawn block into a block per
  combination of indices; decay chains, landscape objects and scenarios are
  all just dimensions.
- **Thirteen solvers.** Numerical differentiation formulas as the default,
  plain BDF, a Rosenbrock (2,3) pair and Dormand-Prince (4,5) written here;
  six stiff methods ported from DifferentialEquations.jl; and three of
  SciPy's through Pyodide, as an independent check.
- **An analytic Jacobian**, differentiated from the model's own equations, with
  the sparsity pattern the model implies. It is what makes tens of thousands
  of states practical.
- **Probabilistic runs** over every core: Latin hypercube sampling, rank
  correlation, tornado plots, R²/SRC/PCC/S₁, and a replay of any single
  realisation.
- **Unit checking** on every equation, with SI prefixes and unit literals.
- **Results** as CSV, as HDF5 in the shape the assessment tools read, or as a
  project archive with the run beside it.
- **A Python package** that reads a model into objects, edits it by the same
  rules as the editor — a rename follows every reference, a delete is refused
  while something reads the block — writes it back, and runs it outside the
  browser with the same equations and solvers: deterministic, scenario,
  probabilistic and sensitivity runs, calibration, and the same result files.
  See [python/README.md](python/README.md).

## Documentation

| | |
|---|---|
| [GUIDE.md](GUIDE.md) | The user guide. Start at *Your first model*. |
| [INTERNALS.md](INTERNALS.md) | How it works. |
| [python/README.md](python/README.md) | Working on a model from Python. |

Both are readable inside the application, on the **Help** tab, with a width
control for the reference tables.

## Tests

```sh
node test/run.js
node test/lint.js
cd python/tests && python3 -m unittest
```

The numerical tests check against closed-form solutions and published
benchmarks — exponential decay, the Bateman equations, the Robertson problem,
harmonic-oscillator energy — never against a previous run of this code.

## Licence and provenance

Kompartment is released under the MIT licence; see [LICENSE](LICENSE).

The numerical methods are published ones, implemented here from their
descriptions and cited where they are implemented: Shampine & Reichelt (1997)
for the numerical differentiation formulas and the Rosenbrock pair, Dormand &
Prince (1980) for the explicit pair, Hairer & Wanner (1996) for the step-size
and order strategies, Gilbert–Peierls for the sparse LU. `src/ode/julia/` is a
port of six stiff solvers from [OrdinaryDiffEq.jl][sciml], which is MIT
licensed; its notice is in `src/ode/julia/LICENSE`. `src/domain/gsa.js` is a
port of the methods of [GlobalSensitivity.jl][gsa], with the parts of
KernelDensity.jl, Interpolations.jl and ComplexityMeasures.jl they use, all MIT
licensed; the notices are in `src/domain/gsa.LICENSE`. The far-field pathway
follows the formulation in *SKB TR-19-06* Appendix B, with Chapter 3 of
*TR-90-01* behind it.

The radionuclide data is ICRP Publication 107.

Kompartment reads the `.eco` and `.eas` project files of the Ecolego desktop
tool so that existing models can be opened here. It is an independent work,
and is not affiliated with or endorsed by that tool's publisher.

[sciml]: https://github.com/SciML/OrdinaryDiffEq.jl
[gsa]: https://github.com/SciML/GlobalSensitivity.jl
