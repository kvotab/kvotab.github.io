// df/dp, differentiated rather than differenced (the Julia package's
// engine/paramtangent.jl; the Python package's `kompartment/engine/paramtangent.py`,
// `buildParamTangent` in the application's src/sim/jacobian.js). The driving term of
// the forward sensitivity equations `S' = J·S + df/dp`, taken by the same
// forward-mode rules the analytic Jacobian uses (engine/jacobian_analytic), seeded
// on the parameters instead of on the state. engine/localsens uses it where it is
// available, as the application does, and differences df/dp otherwise.
//
// `param_pvp(plan, t, y, w)` is `(df/dp)·w` at `(t, y)` with the state held fixed:
// the directional derivative along `w`, a vector over the parameter slots. Every
// algebraic slot's tangent is carried through all three passes -- the slots worked
// out once for the run, those that move with the clock and those that read the
// state -- in the builder's dependency order, and the derivative's assembly is
// differentiated along it:
//
// - a transfer's flux `donor × rate` loses its first term (the donor is held
//   fixed), so it contributes `donor × d(rate)`, or `d(rate)` where it does not
//   multiply by the donor;
// - a source, a compartment's dy/dt term and a running mean's integral contribute
//   their slot's tangent;
// - decay and ingrowth have coefficients from the half-lives and drop out;
// - the mass-balance budget's rows get nothing, as in the application, whose
//   parameter tangent writes them only along the state.
//
// The blocks that remember: a min/max follows its target's tangent where the target
// is the extreme, a running mean its target's only before any time has passed, a
// snapshot and a delay nothing (a delay whose lag moves with a parameter is
// refused). A lookup table read at the clock has no tangent.
//
// A far-field path on cells is differentiated through its own rates: its cells are
// states, held, so what moves along a parameter is its rates -- nothing along a
// leach rate into it, and along a diffusivity or a Kd its settings are worked out
// from, the transport matrix's and the release weights' own tangents
// (`farfield_tangent`), over the matched layers the run laid out.
//
// Refused, with the application's reasons, where it refuses: a model with no
// parameters, a semi-analytical far-field path, a waste package or a disruptive
// event (each has runtime pieces that differentiate along the state and not along a
// parameter), a function with no derivative rule applied to something a parameter
// reaches, and a derivative that is not a number at the start of the run.

#pragma once

#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include "engine/system.hpp"

namespace kompartment {

/// What makes df/dp not one to generate, in the application's words (Julia's `_PTRefused`).
struct ParamTangentRefused : std::runtime_error {
    using std::runtime_error::runtime_error;
};

/// What `param_pvp` walks: the statements in dependency order, and the assembly's terms. It
/// holds its system by address, as the analytic Jacobian's plan does.
struct ParamTangentPlan;

/// The plan of df/dp for a built model; throws `NoDerivative` or `ParamTangentRefused` where
/// there is none (Julia's `ParamTangentPlan(sys)`).
std::shared_ptr<ParamTangentPlan> make_param_tangent_plan(System& sys);

/// `(df/dp)·w` at `(t, y)`, the state held fixed: `w` is a weight per parameter slot.
std::vector<double> param_pvp(ParamTangentPlan& plan, double t, const std::vector<double>& y, const std::vector<double>& w);

/// df/dp for a built model, or why there is none (`param_tangent`): no analytic Jacobian, no
/// parameters, a semi-analytical far-field path, a waste package or a disruptive event, a
/// function with no derivative rule, or a derivative that is not a number at the start of
/// the run.
struct ParamTangent {
    bool available = false;
    std::optional<std::string> reason;
    std::shared_ptr<ParamTangentPlan> plan;
};
ParamTangent param_tangent(System& sys);

}  // namespace kompartment
