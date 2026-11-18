// Units in equations: parsing them, the unit an equation comes out in, and a
// number written with a unit (`0.01[m]`) scaled to the unit of what it is
// added to (src/domain/unitcheck.js).
//
// A unit is a product of powers of symbols times a scale (`km` is m^1 x 1000,
// `g` is kg^1 x 0.001); two units are the same quantity when their powers
// agree, and the same unit when the scales agree too. A literal is converted
// to the unit of what it is added to, compared with or chosen against, when
// that unit is known: `p1 + 1000[mm]` with `p1` in metres is `p1 + 1`.

#pragma once

#include <functional>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

#include "lang/ast.hpp"
#include "util/json.hpp"

namespace kompartment {

/// A unit: powers of symbols (in the order the symbols came), and a scale.
struct UnitDim {
    std::vector<std::pair<std::string, long long>> powers;
    double scale = 1.0;

    UnitDim() = default;
    UnitDim(std::vector<std::pair<std::string, long long>> p, double s) : powers(std::move(p)), scale(s) {}

    /// The power of a symbol, or null when the unit has none of it.
    const long long* power(std::string_view symbol) const;
};

/// A unit, or null where it is not known.
using DimPtr = std::shared_ptr<const UnitDim>;

/// A power no whole number holds (Julia's `InexactError`, where it turns a power into an `Int`).
struct UnitPowerError : std::range_error {
    using std::range_error::range_error;
};

bool is_one(const UnitDim& d);
/// `a * b`, or `a / b` with `sign` -1.
UnitDim dim_times(const UnitDim& a, const UnitDim& b, int sign = 1);
UnitDim dim_over(const UnitDim& a, const UnitDim& b);
/// `d` to the power `n`, or nothing where a symbol would get a power that is not whole.
std::optional<UnitDim> dim_pow(const UnitDim& d, double n);
/// Whether two units measure the same quantity: the same powers, whatever the scales.
bool same_kind(const UnitDim& a, const UnitDim* b);
/// How many of `b` one of `a` is.
double dim_factor(const UnitDim& a, const UnitDim& b);
bool dim_equals(const UnitDim& a, const UnitDim* b);

/// `Number.prototype.toExponential()` with no argument.
std::string to_exponential(double v);
/// A unit's scale in a message: `1000`, `0.001`, `1e+6`.
std::string scale_text(double scale);
/// A unit in words: `unitless`, `kg/m^3`, `1000 m`, `1/(m*s)`.
std::string dim_text(const UnitDim& d);

/// A unit's text as a `UnitDim`, or null when it cannot be read: `kg/m3`, `m^2/year`,
/// `mol per kg`, `1/(m*s)`, `[Bq]`.
DimPtr parse_unit(std::string_view text);
/// The same for what a model file holds where a unit is expected (text, a number, null).
DimPtr parse_unit(const Json& text);

/// Whether two unit texts are the same unit.
bool same_unit(const Json& a, const Json& b);

/// Two units that cannot be put together, in words.
struct UnitClash : std::runtime_error {
    using std::runtime_error::runtime_error;
};

/// The unit of a block as it is written in an equation, or null.
using UnitOf = std::function<DimPtr(const std::string& name)>;

/// The unit an equation comes out in (null when it cannot be known), or the clash that
/// stops it having one.
struct EquationUnit {
    DimPtr dim;
    std::optional<std::string> clash;
};
EquationUnit equation_unit(const ENode& ast, const UnitOf& unit_of, const DimPtr& time_dim);

/// Whether an equation's tree holds a number written with a unit.
bool has_unit_literal(const ENode& node);

/// What `scale_literals` did: the literals it converted (each as written, the unit it was
/// in, the unit it is in now and its value there), and the ones written against
/// something whose unit is not known, left as they were.
struct ScaledLiterals {
    struct Converted {
        double value;
        std::string from, to;
        double now;
    };
    struct Unconverted {
        double value;
        std::string unit;
    };
    std::vector<Converted> converted;
    std::vector<Unconverted> unconverted;
};

/// Converts, in place, each literal written with a unit to the unit of what it is written
/// against: added to, subtracted from, compared with, or chosen against (`if`, `min`,
/// `max`, `?:`).
ScaledLiterals scale_literals(const ENodePtr& ast, const UnitOf& unit_of, const DimPtr& time_dim);

/// Scales, in place, every literal written with a unit to the unit it is written against
/// (the builder's `_scale_literals!`). `unit_blocks`: every block of the project by
/// qualified name; `simulation`: the project's simulation settings; `system`: the
/// sub-system the equation is written in.
void scale_model_literals(const ENodePtr& ast, const std::unordered_map<std::string, Json>& unit_blocks,
                          const Json& simulation, const std::string& system);

}  // namespace kompartment
