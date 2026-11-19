// Calibration against the Julia package's (tools/calibrate_fixtures.jl writes
// tests/fixtures/calibrate.json), with parity on: the three optimisers on functions made up
// for the purpose -- smooth, flat, not a number in a region, infinite everywhere, at the
// bounds and past them, raising, giving up -- from starts inside the box, on its bounds and
// outside it, with budgets that run out, searches stopped by their signal and every
// refusal, every step each reports and what each gives, to the bit; the pieces (the
// objective on readings and targets of every kind, the elimination, the keys a point is
// known by, the scales, spaces and methods looked up by odd keys); `reading_of` on runs of
// every bundled example and of made-up models, `variables_of` on each; and calibrations of
// bundled examples and made-up models -- each method, several seeds and budgets, variables
// in the value and in its logarithm, a corner of the box that will not solve, targets that
// are not there or cannot be met, stopped searches and every refusal -- every step said and
// the answer, to the bit.
//
// KOMPARTMENT_CALIBRATE_ONLY=text runs only the cases whose name holds it (for a sanitizer build).

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <functional>
#include <limits>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include "check.hpp"
#include "engine/calibrate.hpp"
#include "engine/errorinfo.hpp"
#include "engine/project.hpp"
#include "engine/runner.hpp"
#include "engine/system.hpp"
#include "lang/jsmath.hpp"
#include "model/names.hpp"
#include "stats/optimise.hpp"
#include "util/json.hpp"
#include "util/jsnum.hpp"
#include "util/parity.hpp"

using namespace kompartment;

namespace {

constexpr double NaN = std::numeric_limits<double>::quiet_NaN();
constexpr double Inf = std::numeric_limits<double>::infinity();

std::string bits(double x) {
    if (std::isnan(x)) return "nan";
    std::uint64_t u;
    std::memcpy(&u, &x, 8);
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(u));
    return buf;
}
double unbits(const std::string& s) {
    if (s == "nan") return NaN;
    std::uint64_t u = std::strtoull(s.c_str(), nullptr, 16);
    double x;
    std::memcpy(&x, &u, 8);
    return x;
}
std::vector<double> unnums(const std::string& s) {
    std::vector<double> out;
    if (s.empty()) return out;
    for (const std::string& part : split(s, ',')) out.push_back(unbits(part));
    return out;
}
std::string fnv(const std::string& text) {
    std::uint64_t h = 0xcbf29ce484222325ULL;
    for (unsigned char b : text) h = (h ^ b) * 0x100000001b3ULL;
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(h));
    return buf;
}
std::string kept(const std::string& text) { return text.size() <= 300 ? "=" + text : "#" + fnv(text); }
std::string nums(const std::vector<double>& v) {
    std::string s;
    for (std::size_t i = 0; i < v.size(); i++) s += (i ? "," : "") + bits(v[i]);
    return s;
}
std::string joined(const std::vector<std::string>& parts, const std::string& by) {
    std::string s;
    for (std::size_t i = 0; i < parts.size(); i++) s += (i ? by : "") + parts[i];
    return s;
}

std::string tdump(const Json& v) {
    switch (v.type()) {
        case Json::Type::Null: return "null";
        case Json::Type::Bool: return v.as_bool() ? "true" : "false";
        case Json::Type::Int: return "i" + std::to_string(v.as_int());
        case Json::Type::Float: return "f" + bits(v.as_double());
        case Json::Type::String: return "s(" + v.as_string() + ")";
        case Json::Type::Array: {
            std::string s = "[";
            for (std::size_t i = 0; i < v.size(); i++) s += (i ? "," : "") + tdump(v[i]);
            return s + "]";
        }
        case Json::Type::Object: {
            std::string s = "{";
            bool first = true;
            for (const auto& [k, x] : v.obj()) {
                s += (first ? "" : ";") + k + "=" + tdump(x);
                first = false;
            }
            return s + "}";
        }
    }
    return "";
}
Json array_of(const std::vector<Json>& items) {
    Json a = Json::array();
    for (const Json& x : items) a.push(x);
    return a;
}

/// What a call gives, or the error it raises as the service names it: its type and its message.
std::string said(const std::function<std::string()>& f) {
    try {
        return f();
    } catch (...) {
        ErrorInfo info = error_info(std::current_exception());
        return "error:" + info.name + ":" + info.message;
    }
}

// --- the functions the optimisers are run on (tools/calibrate_fixtures.jl has each, in the same arithmetic) ---------

using X = std::vector<double>;
constexpr double CENTRE[4] = {0.3, -0.2, 0.7, 0.05};

double sphere(const X& x) {
    double s = 0.0;
    for (std::size_t i = 0; i < x.size(); i++) {
        const double d = x[i] - CENTRE[i % 4];
        s += d * d;
    }
    return s;
}

std::map<std::string, OptimiseFunction> functions() {
    std::map<std::string, OptimiseFunction> f;
    f["sphere"] = sphere;
    f["rosenbrock"] = [](const X& x) {
        const double a = 1 - x[0], b = x[1] - x[0] * x[0];
        return a * a + 100 * b * b;
    };
    f["flat"] = [](const X&) { return 5.0; };
    f["nan right"] = [](const X& x) { return x[0] > 0.5 ? NaN : sphere(x); };
    f["inf left"] = [](const X& x) { return x[0] < 0.1 ? Inf : sphere(x); };
    f["corner"] = [](const X& x) {
        const double a = x[0] - 2, b = x[1] + 3;
        return a * a + b * b;
    };
    f["abs"] = [](const X& x) { return std::fabs(x[0] - 0.25) + std::fabs(x[1] + 0.5); };
    f["explog"] = [](const X& x) { return js_exp(x[0]) - 2 * x[0] + js_log(1 + x[1] * x[1]); };
    f["plateaus"] = [](const X& x) { return std::floor(x[0] * 4) + 0.5 * std::floor(x[1] * 3); };
    f["never"] = [](const X&) { return Inf; };
    f["huge"] = [](const X& x) { return 1e200 * (1 + x[0] * x[0]) * 1e200; };
    f["throws"] = [](const X& x) {
        if (x[0] > 0.6) throw std::runtime_error("boom");
        return sphere(x);
    };
    f["gives up"] = [](const X& x) {
        if (x[0] > 0.6) throw OptimiseError("gave up");
        return sphere(x);
    };
    f["negative zero"] = [](const X& x) { return -0.0 * x[0]; };
    f["one"] = [](const X& x) {
        const double d = x[0] * x[0] - 2;
        return d * d;
    };
    return f;
}

std::map<std::string, ResidualFunction> residual_functions() {
    std::map<std::string, ResidualFunction> f;
    f["line"] = [](const X& x) { return X{x[0] + x[1] - 1, x[0] - x[1] - 0.5, 2 * x[0] + 0.25 * x[1] - 3}; };
    f["rosen"] = [](const X& x) { return X{1 - x[0], 10 * (x[1] - x[0] * x[0])}; };
    f["expfit"] = [](const X& x) {
        const double data[5][2] = {{0.0, 2.0}, {1.0, 1.2}, {2.0, 0.75}, {4.0, 0.3}, {7.0, 0.07}};
        X out;
        for (const auto& td : data) out.push_back(x[1] * js_exp(-x[0] * td[0]) - td[1]);
        return out;
    };
    f["nan right"] = [](const X& x) { return x[0] > 0.5 ? X{NaN, x[1]} : X{x[0] - 0.2, x[1] - 0.1}; };
    f["inf jacobian"] = [](const X& x) { return X{x[0] > 0.3 ? Inf : x[0] - 0.5, x[1] - 0.25}; };
    f["empty"] = [](const X&) { return X{}; };
    f["one"] = [](const X& x) { return X{x[0] * x[0] - 2}; };
    f["flat"] = [](const X&) { return X{1.0, 2.0}; };
    f["throws"] = [](const X& x) {
        if (x[0] > 0.6) throw std::runtime_error("boom");
        return X{x[0] - 0.7, x[1]};
    };
    f["far out"] = [](const X& x) { return X{(x[0] - 1000000.005) * 3, x[1] - 2}; };
    f["sawtooth"] = [](const X& x) { return X{std::floor(10 * x[0]) / 10 - 0.05 * x[0] + 1}; };
    f["mixed"] = [](const X& x) { return X{x[0] - 1, x[0] * x[0] - 4, 0.5 * x[0] - 0.3}; };
    f["far apart"] = [](const X& x) { return X{x[0] - 3, x[0] * x[0] - 1, x[0] + 2}; };
    f["two"] = [](const X& x) { return X{x[0] - 1, x[1] - 2, x[0] * x[1] - 4, x[0] * x[0] - x[1]}; };
    return f;
}

/// A signal that answers true from its `after + 1`-th call on, or none.
std::function<bool()> signal_of(const Json& o) {
    const Json& after = o.get("abort");
    if (after.is_null()) return nullptr;
    auto calls = std::make_shared<long long>(0);
    const long long limit = after.as_int();
    return [calls, limit] { return ++*calls > limit; };
}

std::optional<double> number_or_none(const Json& v) { return v.is_null() ? std::nullopt : std::optional<double>(v.as_double()); }

std::string step_line(const OptimiseStep& p) {
    return std::to_string(p.evals) + " " + bits(p.fx) + " " + bits(p.best) + " " + nums(*p.x) + " " + (p.best_x ? nums(*p.best_x) : std::string("none"));
}

std::string result_line(const OptimiseResult& out) {
    return "x=" + (out.x ? nums(*out.x) : std::string("none")) + " fx=" + bits(out.fx) + " evals=" + std::to_string(out.evals) + " reason=" + out.reason;
}

std::string optimise_text(const Json& c) {
    static const auto fs = functions();
    static const auto rs = residual_functions();
    const Json& o = c.get("options");
    std::vector<std::string> steps;
    OptimiseOptions opts;
    opts.lower = o.get("lower");
    opts.upper = o.get("upper");
    opts.max_evals = o.get("max_evals");
    opts.tol = number_or_none(o.get("tol"));
    opts.start = o.get("start");
    opts.pop_size = o.has("pop_size") ? o.get("pop_size") : Json(0);
    opts.seed = o.has("seed") ? o.get("seed") : Json(1);
    opts.F = number_or_none(o.get("F"));
    opts.CR = number_or_none(o.get("CR"));
    opts.on_step = [&](const OptimiseStep& p) { steps.push_back(step_line(p)); };
    opts.signal = signal_of(o);
    const std::string& method = c.get("method").as_string();
    const std::string& fn = c.get("fn").as_string();
    std::string out = said([&] {
        if (method == "nelder") return result_line(nelder_mead(fs.at(fn), c.get("start"), opts));
        if (method == "lm") return result_line(levenberg_marquardt(rs.at(fn), c.get("start"), opts));
        return result_line(differential_evolution(fs.at(fn), opts));
    });
    steps.push_back(out);
    return joined(steps, "\n");
}

std::string calibrate_text(const Json& model, const Json& o) {
    std::vector<std::string> steps;
    std::string out = said([&] {
        Json m = model;
        if (o.get("break") == Json(true)) {
            m = model.copy();
            m["transfers"][std::size_t{0}].set("rate", Json("k *"));
        }
        CalibrateOptions co;
        co.targets = o.get("targets");
        co.variables = o.get("variables");
        co.method = o.get("method");
        co.max_evals = o.get("maxEvals");
        co.seed = o.get("seed");
        co.signal = signal_of(o);
        co.on_progress = [&](const CalibrateStep& p) {
            steps.push_back(std::to_string(p.evals) + " " + bits(p.fx) + " " + bits(p.best) + " " + (p.values ? nums(*p.values) : std::string("none")));
        };
        Json r = calibrate(std::make_shared<const Project>(m), co);
        r.erase("ms");
        return tdump(r);
    });
    steps.push_back(out);
    return joined(steps, "\n");
}

std::string scale_name(const std::optional<OptimiseScale>& s) {
    if (!s) return "none";
    return *s == OptimiseScale::Absolute ? "absolute" : *s == OptimiseScale::Relative ? "relative" : "log";
}
std::string space_name(const std::optional<OptimiseSpace>& s) {
    if (!s) return "none";
    return *s == OptimiseSpace::Linear ? "linear" : "log";
}
std::string method_name(const std::optional<OptimiseMethod>& m) {
    if (!m) return "none";
    return *m == OptimiseMethod::Nelder ? "nelder" : *m == OptimiseMethod::Lm ? "lm" : "de";
}

}  // namespace

int main() {
    Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/calibrate.json"));
    const char* dumps = std::getenv("KOMPARTMENT_FIXTURE_DUMPS");
    const char* only_env = std::getenv("KOMPARTMENT_CALIBRATE_ONLY");
    const std::string only = only_env ? only_env : "";
    auto wanted = [&](const std::string& name) { return only.empty() || name.find(only) != std::string::npos; };
    set_parity(true);
    std::map<std::string, Json> examples;
    auto model_named = [&](const std::string& name) -> Json {
        if (fx.get("models").has(name)) return fx.get("models").get(name);
        const std::string ex = name.rfind("example ", 0) == 0 ? name.substr(8) : name;
        if (!examples.count(ex)) examples[ex] = parse_json(check::read_file(std::string(KOMPARTMENT_REPO) + "/examples/" + ex + ".json"));
        return examples[ex];
    };
    std::string all;
    int n = 0;
    auto record = [&](const std::string& head, const std::string& text, const Json& want) {
        all += (n++ ? "\n\n" : "") + std::string("## ") + head + "\n" + text;
        CHECK_MSG(kept(text) == want.as_string(), head + "\n   here:  " + kept(text).substr(0, 300) + "\n   there: " + want.as_string().substr(0, 300));
    };

    // The optimisers on made-up functions: every step, and what each gives.
    int optimisations = 0;
    for (const Json& c : fx.get("optimise").arr()) {
        const std::string head = "optimise " + c.get("method").as_string() + " " + c.get("fn").as_string() + " " + json_text(c.get("start"), 0) + " " +
                                 json_text(c.get("options"), 0);
        if (!wanted(head)) continue;
        std::string text;
        try {
            text = optimise_text(c);
        } catch (const std::exception& e) {
            text = std::string("raised here: ") + e.what();
        }
        record(head, text, c.get("out"));
        optimisations++;
    }

    // One endpoint's value out of a finished run, and the variables a model offers.
    int read = 0;
    for (const Json& c : fx.get("readings").arr()) {
        const std::string name = c.get("name").as_string();
        if (!wanted("readings " + name)) continue;
        std::string text = said([&] {
            auto project = std::make_shared<const Project>(model_named(name));
            RunOptions options;
            options.on_grid = true;
            Results res = run_project(project, std::make_shared<System>(project), options);
            std::vector<double> got;
            for (const Json& t : c.get("targets").arr()) got.push_back(reading_of(res, t));
            return nums(got);
        });
        record("readings " + name, text, c.get("out"));
        read++;
    }
    for (const Json& c : fx.get("variables").arr()) {
        const std::string name = c.get("name").as_string();
        if (!wanted("variables " + name)) continue;
        record("variables " + name, said([&] { return tdump(array_of(variables_of(std::make_shared<const Project>(model_named(name))))); }),
               c.get("out"));
    }

    // Calibrations: every step said, and the answer.
    int calibrations = 0, refused = 0;
    for (const Json& c : fx.get("calibrations").arr()) {
        const std::string head = "calibrate " + c.get("name").as_string() + " " + json_text(c.get("options"), 0);
        if (!wanted(head)) continue;
        const Json model = c.has("example") ? model_named(c.get("example").as_string()) : fx.get("models").get(c.get("model").as_string());
        std::string text;
        try {
            text = calibrate_text(model, c.get("options"));
        } catch (const std::exception& e) {
            text = std::string("raised here: ") + e.what();
        }
        record(head, text, c.get("out"));
        calibrations++;
        if (text.rfind("error:", 0) == 0) refused++;
    }
    if (dumps && *dumps) std::ofstream(std::string(dumps) + "/calibrate.cpp.txt", std::ios::binary) << all;

    if (only.empty()) {
        // The objective on readings and targets of every kind.
        for (const Json& c : fx.get("objective").arr()) {
            const Objective o = objective_of(optimise_readings(c.get("readings")), c.get("targets").arr());
            const std::string got = bits(o.objective) + "|" + nums(o.residuals);
            CHECK_MSG(got == c.get("out").as_string(), "objective_of " + json_text(c.get("readings"), 0) + " " + json_text(c.get("targets"), 0) +
                                                           "\n   here:  " + got + "\n   there: " + c.get("out").as_string());
        }
        // Gauss elimination.
        for (const Json& c : fx.get("solve").arr()) {
            std::vector<std::vector<double>> A;
            for (const Json& row : c.get("A").arr()) A.push_back(unnums(row.as_string()));
            const std::optional<std::vector<double>> x = optimise_solve(A, unnums(c.get("b").as_string()));
            const std::string got = x ? nums(*x) : "none";
            CHECK_MSG(got == c.get("out").as_string(), "_op_solve " + json_text(c.get("A"), 0) + ": " + got + ", Julia's " + c.get("out").as_string());
        }
        // The keys a point is known by.
        {
            std::vector<std::string> keys;
            for (double v : unnums(fx.get("keys").get("values").as_string())) keys.push_back(js_to_precision(v, 12));
            CHECK_MSG(joined(keys, "|") == fx.get("keys").get("out").as_string(), "toPrecision(12): " + joined(keys, "|"));
        }
        // The scales, spaces and methods, looked up by odd keys.
        for (const Json& c : fx.get("lookups").arr()) {
            const Json* key = c.get("missing") == Json(true) ? nullptr : &c.get("key");
            const std::string what = key ? json_text(*key, 0) : "undefined";
            CHECK_MSG(scale_name(optimise_scale(key)) == c.get("scale").as_string(), "the scale of " + what);
            CHECK_MSG(space_name(optimise_space(key)) == c.get("space").as_string(), "the space of " + what);
            CHECK_MSG(method_name(optimise_method(key)) == c.get("method").as_string(), "the method of " + what);
        }
        {
            const Json& scales = fx.get("scales");
            std::vector<std::pair<double, double>> pairs;
            for (const std::string& p : split(scales.get("pairs").as_string(), ',')) {
                const std::vector<std::string> gw = split(p, ':');
                pairs.emplace_back(unbits(gw[0]), unbits(gw[1]));
            }
            for (const auto& [name, scale] : std::vector<std::pair<std::string, OptimiseScale>>{
                     {"absolute", OptimiseScale::Absolute}, {"relative", OptimiseScale::Relative}, {"log", OptimiseScale::Log}}) {
                std::vector<double> got;
                for (const auto& [g, w] : pairs) got.push_back(optimise_residual(scale, g, w));
                CHECK_MSG(nums(got) == scales.get(name).as_string(), "the " + name + " scale");
            }
            const Json& spaces = fx.get("spaces");
            const std::vector<double> values = unnums(spaces.get("values").as_string());
            for (const auto& [name, space] : std::vector<std::pair<std::string, OptimiseSpace>>{{"linear", OptimiseSpace::Linear}, {"log", OptimiseSpace::Log}}) {
                std::vector<std::string> got;
                for (double v : values)
                    got.push_back(bits(space_to(space, v)) + ":" + bits(space_from(space, v)) + ":" + (space_ok(space, v, 2 * v) ? "true" : "false"));
                CHECK_MSG(joined(got, ",") == spaces.get(name).as_string(), "the " + name + " space");
            }
        }
    }

    set_parity(false);
    std::printf("%d optimisations, %d models read, %d calibrations (%d refused)\n", optimisations, read, calibrations, refused);
    return check::summary("test_calibrate");
}
