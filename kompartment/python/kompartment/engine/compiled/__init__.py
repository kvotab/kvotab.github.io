"""The compiled path: a model's derivative and the solver's loop compiled
with numba, so that a run returns to Python only when it ends.

* :mod:`.model` compiles a built model's derivative (and its min/max
  bookkeeping) into functions of fixed signature, cached on disk by content;
* :mod:`.solvers` holds the NDF, Rosenbrock (2,3) and Dormand-Prince loops,
  ports of ``engine/solvers`` with the same arithmetic, compiled once for
  every model;
* :mod:`.run` decides whether a run can take the path and drives it.

A compiled run takes the same steps as the Python path, to the last bit. A
run the path does not take -- see :func:`.run.prepare` and
:func:`.model.compile_model` for why one would not -- keeps to the Python
path, which can run everything. numba is optional; without it there is only
the Python path.
"""


class NotCompiled(Exception):
    """This model, or this run of it, is not one the compiled path takes.

    Here rather than beside the compiler so that the runner can catch it on
    a Python without numba, where the rest of this package cannot be imported.
    """
