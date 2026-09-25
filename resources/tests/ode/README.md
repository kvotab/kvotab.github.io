# ode — tests

The tests of the ODE solvers in `resources/js/ode/`, laid out as that tree is:

```
node resources/tests/ode/test-core.mjs            # core/ and solvers/: the NDF, its LUs, events
node resources/tests/ode/test-build.mjs           # the bundles and Kompartment's copies are up to date
node resources/tests/ode/julia/test-linalg.mjs    # julia/: see julia/README.md
node resources/tests/ode/julia/test-order.mjs
node resources/tests/ode/julia/test-stiff.mjs [--verbose]
node resources/tests/ode/julia/test-behaviour.mjs
```

`test-core` checks that the single-file build (`resources/js/ode-core.js`)
gives the same bits as the modules; that `facsimile-solver.js`'s `saveAt` comes
out as it always did; that the four iteration-matrix modes give the LU they
name and that `auto` follows each page's measurements; that every shape of
Jacobian is accepted; that each failure has its code; that an event switched
off is not reported; and that a floating absolute tolerance handed over as a
`Float64Array` keeps its high-water mark there.

`test-build` runs `node scripts/build-solvers.mjs --check`: the modules, the two
single-file builds and Kompartment's copies are the same code. The numbers
against references are the pages' own suites: `resources/tests/facsimile/`,
`resources/tests/rtm/` and `kompartment/test/`.
