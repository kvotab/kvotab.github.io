// Units and numbers written with one, against the Julia engine's reading of
// them (tools/unit_fixtures.jl writes tests/fixtures/unitcheck.json): unit
// texts as powers and a scale, scales as a message writes them, the unit an
// equation comes out in or the clash that stops it, and every literal written
// with a unit after it has been scaled to what it is written against -- its
// value to the bit, the unit it was converted to, what was and was not
// converted -- by `scale_literals` and as the builder does it.

#include <cstdint>
#include <cstring>

#include "check.hpp"
#include "engine/unitcheck.hpp"
#include "lang/parse.hpp"
#include "util/json.hpp"

using namespace kompartment;

static std::string bits(double x) {
    std::uint64_t u;
    std::memcpy(&u, &x, 8);
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(u));
    return buf;
}
static double unbits(const std::string& h) {
    std::uint64_t u = std::strtoull(h.c_str(), nullptr, 16);
    double x;
    std::memcpy(&x, &u, 8);
    return x;
}

/// A unit as one line: its text, its powers in the order they came, its scale.
static std::string dim_line(const DimPtr& d) {
    if (!d) return "?";
    std::string out = dim_text(*d) + " |";
    bool first = true;
    for (const auto& [sym, n] : d->powers) {
        if (!first) out += " ";
        first = false;
        out += sym + "^" + std::to_string(n);
    }
    return out + "| " + bits(d->scale);
}

static std::string sexp(const ENode& n) {
    switch (n.kind) {
        case ENode::Kind::Num: {
            const ENum& x = as_num(n);
            return "(num " + bits(x.value) + (x.unit ? " [" + *x.unit + "]" : "") + (x.dim ? " {" + dim_line(x.dim) + "}" : "") + ")";
        }
        case ENode::Kind::Ref: {
            const ERef& r = as_ref(n);
            std::string out = "(ref " + r.name;
            for (const auto& i : r.indices) out += " [" + (i ? *i : std::string()) + "]";
            return out + ")";
        }
        case ENode::Kind::Call: {
            const ECall& c = as_call(n);
            std::string out = "(call " + c.name;
            for (const auto& a : c.args) out += " " + sexp(*a);
            return out + ")";
        }
        case ENode::Kind::Unary: return "(neg " + sexp(*as_unary(n).operand) + ")";
        case ENode::Kind::Binary: return "(" + as_binary(n).op + " " + sexp(*as_binary(n).left) + " " + sexp(*as_binary(n).right) + ")";
        case ENode::Kind::Cond:
            return "(? " + sexp(*as_cond(n).test) + " " + sexp(*as_cond(n).then) + " " + sexp(*as_cond(n).otherwise) + ")";
    }
    return "";
}

static std::string unit_now(const ENode& ast, const UnitOf& unit_of, const DimPtr& time_dim) {
    try {
        EquationUnit u = equation_unit(ast, unit_of, time_dim);
        return u.clash ? "clash: " + *u.clash : "unit: " + dim_line(u.dim);
    } catch (const UnitPowerError&) {
        return "throws";
    }
}

int main() {
    Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/unitcheck.json"));

    for (const Json& row : fx.get("units").arr()) {
        const Json& text = row.get("text");
        std::string got;
        try {
            got = dim_line(parse_unit(text));
        } catch (const UnitPowerError&) {
            got = "throws";
        }
        CHECK_MSG(got == row.get("dim").as_string(), "the unit '" + json_text(text, 0) + "': " + got + "\n   there: " + row.get("dim").as_string());
        // Text is read the same way whichever door it comes in by.
        if (text.is_string()) {
            std::string direct;
            try {
                direct = dim_line(parse_unit(std::string_view(text.as_string())));
            } catch (const UnitPowerError&) {
                direct = "throws";
            }
            CHECK_MSG(direct == got, "the unit '" + text.as_string() + "' read as text");
        }
    }

    for (const Json& row : fx.get("scales").arr()) {
        double v = unbits(row.get("value").as_string());
        CHECK_MSG(scale_text(v) == row.get("text").as_string(), "the scale " + check::bits(v) + ": " + scale_text(v) + " vs " + row.get("text").as_string());
        CHECK_MSG(to_exponential(v) == row.get("exponential").as_string(),
                  "toExponential of " + check::bits(v) + ": " + to_exponential(v) + " vs " + row.get("exponential").as_string());
    }

    for (const Json& row : fx.get("same").arr())
        CHECK_MSG(same_unit(row.get("a"), row.get("b")) == row.get("same").as_bool(),
                  "whether " + json_text(row.get("a"), 0) + " and " + json_text(row.get("b"), 0) + " are one unit");

    CallsPredicate calls = [](const std::string&) { return true; };
    for (const Json& row : fx.get("equations").arr()) {
        const std::string& src = row.get("src").as_string();
        const Json& table = fx.get("tables").get(row.get("table").as_string());
        const Json& units = table.get("units");
        DimPtr time_dim = parse_unit(table.get("time"));
        UnitOf unit_of = [&](const std::string& name) -> DimPtr {
            const Json& u = units.get(name);
            return u.is_null() ? nullptr : parse_unit(u);
        };
        try {
            ENodePtr ast = parse_equation(std::string_view(src), calls);
            CHECK_MSG(has_unit_literal(*ast) == row.get("literal").as_bool(), "whether '" + src + "' holds a literal with a unit");
            std::string before = unit_now(*ast, unit_of, time_dim);
            CHECK_MSG(before == row.get("unit").as_string(), "the unit of '" + src + "': " + before + "\n   there: " + row.get("unit").as_string());
            ScaledLiterals done = scale_literals(ast, unit_of, time_dim);
            CHECK_MSG(sexp(*ast) == row.get("scaled").as_string(), "'" + src + "' scaled: " + sexp(*ast) + "\n   there: " + row.get("scaled").as_string());
            Json converted = Json::array(), unconverted = Json::array();
            for (const auto& c : done.converted) converted.push(Json::array({Json(bits(c.value)), Json(c.from), Json(c.to), Json(bits(c.now))}));
            for (const auto& c : done.unconverted) unconverted.push(Json::array({Json(bits(c.value)), Json(c.unit)}));
            CHECK_MSG(json_text(converted, 0) == json_text(row.get("converted"), 0),
                      "what was converted in '" + src + "': " + json_text(converted, 0) + "\n   there: " + json_text(row.get("converted"), 0));
            CHECK_MSG(json_text(unconverted, 0) == json_text(row.get("unconverted"), 0),
                      "what was left in '" + src + "': " + json_text(unconverted, 0) + "\n   there: " + json_text(row.get("unconverted"), 0));
            std::string after = unit_now(*ast, unit_of, time_dim);
            const std::string& want_after = row.has("unit_after") ? row.get("unit_after").as_string() : row.get("unit").as_string();
            CHECK_MSG(after == want_after, "the unit of '" + src + "' once scaled: " + after + "\n   there: " + want_after);
            ScaledLiterals again = scale_literals(ast, unit_of, time_dim);
            const std::string& want_again = row.has("again") ? row.get("again").as_string() : row.get("scaled").as_string();
            CHECK_MSG(sexp(*ast) == want_again, "'" + src + "' scaled twice: " + sexp(*ast));
            CHECK_MSG(static_cast<std::int64_t>(again.converted.size()) == row.get("again_converted").as_int(), "'" + src + "' converted twice");
        } catch (const std::exception& e) {
            CHECK_MSG(false, "'" + src + "' threw: " + e.what());
        }
    }

    std::unordered_map<std::string, Json> blocks;
    for (const auto& [name, block] : fx.get("blocks").obj()) blocks.emplace(name, block);
    for (const Json& row : fx.get("model").arr()) {
        const std::string& src = row.get("src").as_string();
        const std::string& system = row.get("system").as_string();
        const std::string& sim = row.get("simulation").as_string();
        try {
            ENodePtr ast = parse_equation(std::string_view(src), calls);
            scale_model_literals(ast, blocks, fx.get("simulations").get(sim), system);
            CHECK_MSG(sexp(*ast) == row.get("scaled").as_string(),
                      "'" + src + "' in '" + system + "' (" + sim + "): " + sexp(*ast) + "\n   there: " + row.get("scaled").as_string());
        } catch (const std::exception& e) {
            CHECK_MSG(false, "'" + src + "' in '" + system + "' threw: " + e.what());
        }
    }

    return check::summary("test_unitcheck");
}
