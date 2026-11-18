// The designs of the global sensitivity methods: the Julia package's
// stats/gsa_design.jl (the Python package's `build_design` and the builders behind
// it, in `kompartment/stats/gsa.py` and `salib.py`; the application's
// `src/domain/gsa.js` and `salib.js`).
//
// A design is the runs a method asks for, each a probability per input: Morris's
// walks or trajectories, the radial design, Saltelli's design for Sobol, eFAST's
// curves, RBD-FAST's random balance, a two-level fractional factorial, DGSM's base
// points and steps, Shapley's orders and conditional draws. A probabilistic run
// reads each probability through its input's distribution and runs the model at
// every point (`design_for`). What is read off the outputs -- the indices -- is the
// page's, or the Python package's.
//
// **The Julia package's numbers.** The streams and the columns of uniforms are the
// application's (stats/sample.hpp), every sum is added in the same order, and sin,
// cos, asin and log are the C library's (util/libm.hpp), as numpy calls them, so a
// design here is Julia's -- and Python's -- to the last bit.
//
// A design holds the method's layout under Julia's keys, in its order (`fields`),
// and `u`, K x runs: input k's probability at run i. Positions inside a design (a
// Shapley order, an RBD-FAST permutation) count from 0, as Julia's do there.
//
// The settings are what the Julia package reads them as: a whole number where a
// count is wanted (an `Int`), unless it is 9e15 or more, which stays a double -- and
// a design asked for with one of those fails as Julia's does (`JuliaError`).

#pragma once

#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <vector>

#include "stats/sample.hpp"
#include "util/json.hpp"

namespace kompartment {

/// A method's design (`build_design` and the builders).
struct GsaDesign {
    /// The design as Julia's dictionary holds it: `"method"`, `"K"`, the method's own keys,
    /// `"u"` (null here: the numbers are in `u`), `"runs"`, then `"options"` and `"seed"` when
    /// `build_design` made it. A matrix besides `u` is a list of its rows.
    Json fields;
    int K = 0;
    long long runs = 0;
    /// K x runs, a run after another: input k's probability at run i is `u[i * K + k]`.
    std::vector<double> u;

    double at(int k, long long i) const { return u[static_cast<std::size_t>(i * K + k)]; }
};

/// Julia's settings of each method, in the order the application lists them (`GSA_METHODS`).
std::vector<std::string> gsa_method_names();

/// A method's settings with every one filled in (`gsa_options`): what `given` says where it can
/// be read, the default elsewhere. A switch is read for its truth, a choice must be one of its
/// values, and a number is read as JavaScript's `Number()` reads it (a count rounded); anything
/// else takes the default. Empty for a method there is not.
Json gsa_options(const Json& method, long long K, const Json* given = nullptr);

/// How many runs a design of `method` over `K` inputs is, before any is made (0 for a method
/// there is not): a whole number, or a double where Julia's arithmetic makes one.
Json gsa_runs(const Json& method, long long K, const Json* options = nullptr);

/// Why a design cannot be made as asked, in a sentence, or none.
std::optional<std::string> gsa_refusal(const Json& method, long long K, const Json* options = nullptr);

/// A method's design, drawn from a run's seed, with its settings (`"options"`) and `"seed"`
/// recorded. `keys` names each input, for its streams: every column a method samples freely
/// comes from a stream named after the input it belongs to, Latin hypercube, as a probabilistic
/// run draws, so the same seed gives an input the same numbers whichever other inputs are in
/// the model. The walks, the orders and the conditional draws have one stream each
/// (`#gsa#morris`, `#gsa#shapley`). `corr` (K x K, row-major) reaches Shapley only. Raises the
/// refusal (`ArgumentError`) when the design cannot be made as asked.
GsaDesign build_design(const Json& method, const std::vector<std::string>& keys, const Json* options, const Json& seed,
                       const std::vector<double>* corr = nullptr);

// --- the pieces, as the Julia package has them ------------------------------------------------------

/// `ToInt32`, as a store into an `Int32Array` does it.
long long gsa_int32(double v);
/// `Math.round`: the nearest whole number, halves up.
double gsa_round(double x);
/// `sin(pi x)`, reduced exactly first.
double gsa_sinpi(double x);
/// A uniformly random permutation of 0..n-1, Fisher-Yates from the end.
std::vector<long long> gsa_random_permutation(long long n, Mulberry32& g);
/// Every permutation of 0..n-1, in lexicographic order.
std::vector<std::vector<long long>> gsa_permutations(long long n);
/// A Sylvester-Hadamard matrix of order `k` (a power of two from 2 up), as its rows.
std::vector<std::vector<int>> gsa_hadamard(long long k);
/// The lower Cholesky factor of a symmetric matrix (row-major, n * n), row-major; none if it is
/// not positive definite (a pivot not above 1e-14).
std::optional<std::vector<double>> gsa_cholesky(const std::vector<double>& A, long long n);
/// A Cholesky factor of a matrix that is positive semi-definite but not quite definite.
std::vector<double> gsa_jitter_cholesky(const std::vector<double>& A, long long n);

/// GlobalSensitivity.jl's Morris design: `trajectories` random walks of `points` runs.
GsaDesign morris_design(int K, long long trajectories, long long points, long long levels, Mulberry32& next);
/// One Morris trajectory, in levels (0 to `p - 1`): `K + 1` rows of `K`.
std::vector<std::vector<long long>> morris_trajectory(int K, long long p, Mulberry32& g);
/// SALib's distance between two trajectories, held in single precision as SALib holds it.
double trajectory_distance(const std::vector<std::vector<long long>>& a, const std::vector<std::vector<long long>>& b);
/// The `k` most spread-out of the candidate trajectories (SALib's `LocalOptimisation`): which,
/// from 0, ascending.
std::vector<long long> optimal_trajectories(const std::vector<std::vector<std::vector<long long>>>& candidates, long long k);
/// A design of Morris trajectories, `K + 1` runs each.
GsaDesign morris_trajectory_design(int K, long long trajectories, long long levels, long long candidates, Mulberry32& next);
/// The radial design: each of N base points, then once per input moved to its perturbation point.
GsaDesign radial_design(int K, const std::vector<std::vector<double>>& base, const std::vector<std::vector<double>>& step);
/// Saltelli's design; `draw(k, which, block)` gives the `n` probabilities of input k (from 0)
/// in sample "A" or "B" of a block (from 0).
GsaDesign sobol_design(int K, long long n, bool second, long long blocks,
                       const std::function<std::vector<double>(int, const std::string&, long long)>& draw);
/// The smallest number of points at or above `n` that eFAST can use with `M` harmonics (`n` a
/// whole number or a double, as the settings hold it; `M` must be a whole number).
long long efast_samples(const Json& n, const Json& M);
/// omega_1 and the complementary frequencies, as GlobalSensitivity.jl chooses them.
std::vector<double> efast_frequencies(long long K, long long N, long long M);
/// The eFAST design: N points along one curve per input; `phases` one per curve, in [0, 2).
GsaDesign efast_design(int K, long long N, long long harmonics, const std::vector<double>& phases);
/// The random balance design; `perms` one permutation of 0..N-1 per input.
GsaDesign rbd_fast_design(int K, long long N, const std::vector<std::vector<long long>>& perms);
/// The two-level fractional factorial of resolution IV.
GsaDesign ff_design(int K, double low = 0.05, double high = 0.95);
/// The DGSM design: each base point, then one step along each input (and each pair, `crossed`).
GsaDesign dgsm_design(int K, const std::vector<std::vector<double>>& base, double step = 1e-3, bool crossed = false);
/// Song, Nelson and Staum's design for Shapley effects; `perms` -1 for all K! orders; `corr`
/// a K x K correlation matrix of the normal scores, row-major, or none.
GsaDesign shapley_design(int K, long long perms, long long n_var, long long n_outer, long long n_inner,
                         const std::vector<double>* corr, Mulberry32& next);

}  // namespace kompartment
