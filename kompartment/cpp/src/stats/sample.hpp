// Drawing values from the distributions on a model, as Kompartment draws them: the
// Julia package's stats/sample.jl (the Python package's `kompartment/stats/sample.py`,
// the application's `src/domain/sample.js`).
//
// Everything is an inverse CDF rather than a sampler of its own, which buys
// reproducibility (a run is a seed and nothing else), truncation (the same inverse
// CDF fed a uniform confined to [F(lo), F(hi)]) and Latin hypercube sampling (a
// statement about the uniforms, not the shapes) at once.
//
// **The same numbers as the application.** The generator is mulberry32 and its
// output is bit for bit the application's for the same seed; so is every stream
// (`stream_for`, one per sampled input, seeded from the run's seed and the input's
// name) and every column of uniforms (`uniforms`).

#pragma once

#include <cmath>
#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

#include "engine/indexspace.hpp"
#include "util/json.hpp"

namespace kompartment {

class System;

/// A small, fast, seeded generator: mulberry32, the application's. Thirty-two bits of state
/// stepped by a constant; `next()` is the next number in [0, 1), exactly as the application's
/// `rng(seed)()` gives it. A seed of 0 is taken as 1.
class Mulberry32 {
public:
    explicit Mulberry32(std::uint32_t seed = 1) : a(seed == 0 ? 1u : seed) {}
    std::uint32_t a;

    double next() {
        std::uint32_t x = a + 0x6d2b79f5u;
        a = x;
        std::uint32_t t = (x ^ (x >> 15)) * (x | 1u);
        t ^= t + ((t ^ (t >> 7)) * (t | 0x3du));
        return static_cast<double>(t ^ (t >> 14)) / 4294967296.0;
    }
};

/// `v >>> 0`: JavaScript's ToUint32 of a seed, as `Number(v)` reads it.
std::uint32_t sm_to_uint32(const Json* v);
inline std::uint32_t sm_to_uint32(const Json& v) { return sm_to_uint32(&v); }

/// The next `n` numbers from `g`, as `n` calls would give them (none for `n` below 1).
std::vector<double> take_uniforms(Mulberry32& g, long long n);

/// FNV-1a over a name's UTF-16 code units, as the application hashes it.
std::uint32_t fnv_hash(std::string_view text);

/// A stream of its own for one named thing: the run's seed mixed with a hash of the name.
/// `name` is what is drawn for, as the application spells it: the sampled input's name
/// (`Kd[Tc-99]`), a correlation group's name for its members, `correlation:<name>` for a
/// correlation's scores, `<event>#occurrences#<i>` for a disruptive event's dice.
Mulberry32 stream_for(std::uint32_t seed_bits, std::string_view name);
/// The same from a seed and a name as a model file holds them (a name that is null or not
/// there is the empty name; anything else is read as `String()` reads it).
Mulberry32 stream_for(const Json& seed, const Json* name);
inline Mulberry32 stream_for(const Json& seed, std::string_view name) { return stream_for(sm_to_uint32(seed), name); }

/// `n` uniforms in (0, 1) from `g`, stratified or not. Latin hypercube (the default): one from
/// each of `n` equal slices, in an order shuffled by Fisher-Yates, so the draws cover the range
/// evenly. Otherwise `n` independent draws. The application's numbers, drawn in its order. A
/// negative `n` is refused in the Julia package's words.
std::vector<double> uniforms(long long n, Mulberry32& g, bool latin = true);

/// One value from `spec` for the uniform `u`; NaN where the distribution is not filled in. A
/// list (`pg`) is not drawn from: in order (`inorder`, the default) it hands out value
/// `(pos + at) % n` to realisation `at` (counted from 0); out of order it takes the value at
/// `u`. Every other kind is its quantile at `u` read between the two probabilities its
/// truncation leaves, never exactly 0 or 1, and clamped to a value truncation that the round
/// trip through the CDF misses by a billionth.
double value_at_probability(const Json& spec, double u, long long at = 0);

/// What `value_at_probability` reads from a distribution that is the same for every draw, so
/// that a design's thousands of draws do only the arithmetic that depends on the uniform, in
/// the same order: the same numbers (`draw_value`). A list, or a distribution that is not
/// filled in, is left to `value_at_probability`.
struct ValueDrawer {
    enum class Kind : unsigned char { None, List, Unif, Triang, Dtriang, Logu, Logt, Logdt, Norm, Logn, Other };
    Kind kind = Kind::None;
    Json spec;
    double lo = 0.0, span = 1.0;      // the probabilities the truncation reads between, and their span
    bool reversed = false;
    double trmin = NAN, trmax = NAN;  // NaN where there is none
    double a = NAN, b = NAN, c = NAN, d = NAN, e = NAN, f = NAN;   // the shape's numbers (see `draw_value`)

    explicit ValueDrawer(const Json& spec);
};

/// `value_at_probability(spec, u, at)` for the drawer of `spec`: the same number.
double draw_value(const ValueDrawer& dr, double u, long long at = 0);

/// A distributed value in a built model and where it lives in `P` (`distributed_slots`).
struct PlanEntry {
    int slot = 0;          // the offset in P, from 0
    std::string name;      // the parameter's name, or `<table>@<time>` for a lookup point
    Tup index;             // the index tuple, empty for none
    Json spec;             // the distribution

    /// `{"slot", "name", "index", "spec"}`, as the Julia package's plan entry is written.
    Json json() const;
};

/// Every distributed value in a built model and where it lives in `P`: the lookup-table points
/// that carry a distribution first, named `<table>@<time>`, then every parameter slot whose
/// distribution (its entry's own or the block's) is filled in, in the layout's order.
std::vector<PlanEntry> distributed_slots(const System& sys);

}  // namespace kompartment
