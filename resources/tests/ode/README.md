# ode_core — tests

The solver core shared by facsimile.html, rtm.html and Kompartment
(`resources/js/ode_core/`), checked on its own:

```
node resources/tests/ode_core/test-core.mjs
```

It checks that the single-file build (`resources/js/ode-core.js`) gives the
same bits as the modules; that `facsimile-solver.js`'s `saveAt` comes out as it
always did; that the four iteration-matrix modes give the LU they name and that
`auto` follows each page's measurements; that every shape of Jacobian is
accepted; that each failure has its code; that an event switched off is not
reported; and that a floating absolute tolerance handed over as a
`Float64Array` keeps its high-water mark there.

That the modules, the build and Kompartment's copies are the same code is
`resources/tests/ode_julia/test-build.mjs`, which checks both packages. The
numbers against references are the pages' own suites:
`resources/tests/facsimile/`, `resources/tests/rtm/` and `kompartment/test/`.
