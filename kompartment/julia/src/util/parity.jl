# Speed first, or the Python package's arithmetic to the bit.
#
# By default the engine takes Julia's quickest way to an answer within the
# run's tolerance: Julia's own math functions, its own dense LU with fused
# multiply-adds, the derivative's terms merged into one matrix per instant,
# and the quickest of its solvers where a model asks for a slower one. With
# parity on, it does exactly what the Python package does -- the C library's
# math, the application's dense LU, every term summed in the application's
# order, the model's own solver -- so a run gives the Python package's
# numbers to the last bit (on a dense problem; KLU and SuperLU part at
# round-off on a sparse one). That is how the package is checked against the
# Python one.
#
# A system takes the setting when it is built (its generated code and its
# derivative's layout) and a run when it starts (its solver and its linear
# algebra): build again after changing it.

const _PARITY = Ref(false)

"""
    parity() -> Bool

Whether the engine reproduces the Python package's arithmetic to the bit,
rather than taking Julia's quickest way to the same answer within the
tolerance (the default). Set with `set_parity!` or `KOMPARTMENT_PARITY=1`.
"""
parity() = _PARITY[]

"""
    set_parity!(on=true) -> Bool

Has the engine reproduce the Python package's arithmetic to the bit (`true`)
or take Julia's quickest way to an answer within the tolerance (`false`, the
default). Systems built before keep the setting they were built with.
"""
set_parity!(on::Bool=true) = (_PARITY[] = on)

_parity_from_env() = lowercase(strip(get(ENV, "KOMPARTMENT_PARITY", ""))) in ("1", "true", "yes", "on")

# --- which solver runs ------------------------------------------------------------------------------

const _SOLVER_POLICY = Ref(:fastest)

"""
    solver_policy() -> Symbol

`:fastest` (the default): a model that asks for the Rosenbrock 2-3 is run with
the NDF, which finishes the bundled examples three to forty times sooner at
a tighter error, falling back on the model's own solver if the NDF cannot
finish. `:model`: always the model's own solver (parity implies it). Set
with `set_solver_policy!` or `KOMPARTMENT_SOLVERS=model`.
"""
solver_policy() = parity() ? :model : _SOLVER_POLICY[]

"""
    set_solver_policy!(policy) -> Symbol

`:fastest` or `:model`; see `solver_policy`.
"""
function set_solver_policy!(policy::Symbol)
    policy in (:fastest, :model) || throw(ArgumentError("a solver policy is :fastest or :model, not :$policy"))
    return _SOLVER_POLICY[] = policy
end

_solver_policy_from_env() = lowercase(strip(get(ENV, "KOMPARTMENT_SOLVERS", ""))) == "model" ? :model : :fastest

"""The solver a run takes for the one its model asks for, under the policy."""
quicker_solver(asked::String) = (solver_policy() === :fastest && asked == "ros23") ? "ndf" : asked
