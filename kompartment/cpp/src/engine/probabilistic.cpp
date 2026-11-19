// The design of a probabilistic run (see probabilistic.hpp): a port of the first part of the
// Julia package's engine/probabilistic.jl, operation for operation.

#include "engine/probabilistic.hpp"

#include <cmath>
#include <cstdio>
#include <limits>
#include <map>
#include <new>
#include <set>
#include <unordered_map>

#include "engine/builder.hpp"
#include "engine/project.hpp"
#include "engine/system.hpp"
#include "lang/jsmath.hpp"
#include "stats/correlate.hpp"
#include "stats/pdf.hpp"
#include "util/errors.hpp"
#include "util/jsnum.hpp"
#include "util/libm.hpp"

namespace kompartment {

namespace {

constexpr double NaN = std::numeric_limits<double>::quiet_NaN();
constexpr double PB_MIN_VALUE = 5e-324;
constexpr double PB_PI = 3.141592653589793;

/// Whether Julia prints a character beyond ASCII as itself (`isprint`): see below.
bool julia_printable(std::uint32_t cp);

}  // namespace

// --- Julia's `string()` of what a model file holds, for a group given as a list or a dictionary ---------

std::string julia_float(double x) {
    if (std::isnan(x)) return "NaN";
    if (std::isinf(x)) return x > 0 ? "Inf" : "-Inf";
    if (x == 0) return std::signbit(x) ? "-0.0" : "0.0";
    std::string sign = x < 0 ? "-" : "";
    auto [digits, n] = shortest_digits(std::fabs(x));
    long long olength = static_cast<long long>(digits.size());
    long long pt = n;                    // x = 0.digits * 10^n
    long long nexp = pt - olength;       // x = digits * 10^nexp
    bool fixed = false;
    if (-4 < pt && pt <= 6) {
        bool odd = false;
        if (pt >= olength) {
            double m = std::pow(10.0, static_cast<double>(pt - olength));
            double r = std::fmod(x + 0.05, m);
            if (r != 0 && std::signbit(r) != std::signbit(m)) r += m;   // Julia's `mod`
            odd = std::fabs(r - 0.05) > 0.05;
        }
        fixed = !odd;
    }
    if (fixed) {
        if (pt <= 0) return sign + "0." + std::string(static_cast<std::size_t>(-pt), '0') + digits;
        if (pt >= olength) return sign + digits + std::string(static_cast<std::size_t>(nexp), '0') + ".0";
        return sign + digits.substr(0, static_cast<std::size_t>(pt)) + "." + digits.substr(static_cast<std::size_t>(pt));
    }
    std::string mant = digits.substr(0, 1) + "." + (olength > 1 ? digits.substr(1) : "0");
    return sign + mant + "e" + std::to_string(pt - 1);
}

namespace {

/// Whether Julia prints a character beyond ASCII as itself (`isprint`: the letters, marks,
/// numbers, punctuation, symbols and space separators). The other categories as far as a model's
/// text meets them: the C1 controls, the line and paragraph separators, the formatting
/// characters, the private use areas, the noncharacters. (An unassigned code point Julia also
/// escapes is printed here as itself.)
bool julia_printable(std::uint32_t cp) {
    if (cp >= 0x80 && cp <= 0x9f) return false;
    if (cp == 0xad || (cp >= 0x600 && cp <= 0x605) || cp == 0x61c || cp == 0x6dd || cp == 0x70f || cp == 0x8e2 || cp == 0x180e)
        return false;
    if ((cp >= 0x200b && cp <= 0x200f) || (cp >= 0x2028 && cp <= 0x202e) || (cp >= 0x2060 && cp <= 0x2064) || (cp >= 0x2066 && cp <= 0x206f))
        return false;
    if (cp == 0xfeff || (cp >= 0xfff9 && cp <= 0xfffb) || (cp >= 0xfdd0 && cp <= 0xfdef) || (cp & 0xfffe) == 0xfffe) return false;
    if ((cp >= 0xe000 && cp <= 0xf8ff) || cp >= 0xf0000) return false;
    if (cp == 0x110bd || cp == 0x110cd || (cp >= 0x13430 && cp <= 0x1343f) || (cp >= 0x1bca0 && cp <= 0x1bca3) ||
        (cp >= 0x1d173 && cp <= 0x1d17a) || cp == 0xe0001 || (cp >= 0xe0020 && cp <= 0xe007f))
        return false;
    return true;
}

}  // namespace

std::string julia_quote(const std::string& s) {
    struct Char {
        bool ok;
        std::uint32_t cp;
        std::size_t len;
    };
    auto char_at = [&](std::size_t i) -> Char {
        unsigned char c = static_cast<unsigned char>(s[i]);
        if (c < 0x80) return {true, c, 1};
        std::size_t len = (c & 0xe0) == 0xc0 ? 2 : (c & 0xf0) == 0xe0 ? 3 : (c & 0xf8) == 0xf0 ? 4 : 0;
        if (len == 0 || i + len > s.size()) return {false, c, 1};
        std::uint32_t cp = c & (len == 2 ? 0x1f : len == 3 ? 0x0f : 0x07);
        for (std::size_t k = 1; k < len; k++) {
            unsigned char d = static_cast<unsigned char>(s[i + k]);
            if ((d & 0xc0) != 0x80) return {false, c, 1};
            cp = (cp << 6) | (d & 0x3f);
        }
        std::uint32_t least = len == 2 ? 0x80 : len == 3 ? 0x800 : 0x10000;
        if (cp < least || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff)) return {false, c, 1};
        return {true, cp, len};
    };
    auto hex = [](std::uint32_t v, int pad) {
        char buf[16];
        std::snprintf(buf, sizeof buf, "%0*x", pad, static_cast<unsigned>(v));
        return std::string(buf);
    };
    std::string out = "\"";
    for (std::size_t i = 0; i < s.size();) {
        Char c = char_at(i);
        std::size_t next = i + c.len;
        auto next_is = [&](auto pred) {
            if (next >= s.size()) return false;
            Char d = char_at(next);
            return d.ok && pred(d.cp);
        };
        if (!c.ok) {
            out += "\\x" + hex(c.cp, 2);
        } else if (c.cp == '"' || c.cp == '$') {
            out.push_back('\\');
            out.push_back(static_cast<char>(c.cp));
        } else if (c.cp < 0x80) {
            if (c.cp == 0) out += next_is([](std::uint32_t d) { return d >= '0' && d <= '7'; }) ? "\\x00" : "\\0";
            else if (c.cp == 0x1b) out += "\\e";
            else if (c.cp == '\\') out += "\\\\";
            else if (c.cp >= 0x07 && c.cp <= 0x0d) out += std::string("\\") + "abtnvfr"[c.cp - 7];
            else if (c.cp >= 0x20 && c.cp < 0x7f) out.push_back(static_cast<char>(c.cp));
            else out += "\\x" + hex(c.cp, 2);
        } else if (julia_printable(c.cp)) {
            out.append(s, i, c.len);
        } else {
            bool full = next_is([](std::uint32_t d) { return (d >= '0' && d <= '9') || (d >= 'a' && d <= 'f') || (d >= 'A' && d <= 'F'); });
            out += c.cp <= 0xffff ? "\\u" + hex(c.cp, full ? 4 : 2) : "\\U" + hex(c.cp, full ? 8 : 4);
        }
        i = next;
    }
    return out + "\"";
}

std::string julia_show(const Json& v) {
    switch (v.type()) {
        case Json::Type::Null: return "nothing";
        case Json::Type::Bool: return v.as_bool() ? "true" : "false";
        case Json::Type::Int: return std::to_string(v.as_int());
        case Json::Type::Float: return julia_float(v.as_double());
        case Json::Type::String: return julia_quote(v.as_string());
        case Json::Type::Array: {
            std::string out = "Any[";
            for (std::size_t k = 0; k < v.size(); k++) out += (k ? ", " : "") + julia_show(v[k]);
            return out + "]";
        }
        case Json::Type::Object: {
            std::string out = "OrderedCollections.OrderedDict{String, Any}(";
            bool first = true;
            for (const auto& [k, x] : v.obj()) {
                out += (first ? "" : ", ") + julia_quote(k) + " => " + julia_show(x);
                first = false;
            }
            return out + ")";
        }
    }
    return "";
}

std::string julia_string(const Json& v) { return v.is_string() ? v.as_string() : julia_show(v); }

namespace {

/// Python's `max(a, b)` and `min(a, b)`: the first unless the second is strictly beyond it.
double pb_pymax(double a, double b) { return b > a ? b : a; }
double pb_pymin(double a, double b) { return b < a ? b : a; }

/// A tornado's two probabilities, from `true` or a dictionary, read as the application reads
/// them (`Number(tornado.low ?? 0.05)`): an end that is not there, or null, is the default;
/// any other is a number as JavaScript's `Number()` makes one -- text read as a number where
/// it is one, NaN where it is not.
std::pair<double, double> tornado_ends(const Json& tornado) {
    if (tornado.is_bool() && tornado.as_bool()) return {0.05, 0.95};
    auto get = [&](const char* key, double fallback) {
        if (!tornado.is_object()) return fallback;
        const Json* v = tornado.obj().find(key);
        return v == nullptr || v->is_null() ? fallback : pd_to_number(v);
    };
    double low = get("low", 0.05);
    double high = get("high", 0.95);
    return {low, high};
}

/// Input `k`'s value in every realisation, from its uniforms (`value_at_probability`, the
/// reading of its distribution worked out once).
void pb_draw(ValueTable& values, std::size_t k, const ValueDrawer& drawer, const std::vector<double>& u) {
    for (std::size_t i = 0; i < u.size(); i++) values(k, static_cast<long long>(i)) = draw_value(drawer, u[i], static_cast<long long>(i));
}

/// A sensitivity design's points (`gsaDesignFor`): one factor per varied input, or per
/// correlation group (its members move together), a design of the method over the factors,
/// and each point's probabilities read through the inputs' distributions. Shapley honours the
/// correlations between factors through a Gaussian copula, weakened towards none until they
/// are consistent; the other methods sample the factors independently, which the statistics
/// say. A list read in order hands out its values by realisation number, which a design point
/// is not; here it is read by probability, as an unordered list is.
SampleDesign pb_gsa_design(const Project& project, SampleDesign d, const Json& gsa) {
    // `_pb_gsa_spec`: the method and its settings, from a dictionary.
    Json method = gsa.is_object() ? gsa.get("method") : Json();
    Json options = gsa.is_object() ? gsa.get("options") : Json();
    const Json* opts = pd_truthy(&options) ? &options : nullptr;

    const std::vector<PlanEntry>& plan = d.plan;
    std::vector<std::string> keys;
    std::vector<std::optional<std::string>> groups;
    std::vector<std::vector<long long>> members;
    std::unordered_map<std::string, std::size_t> by_key;
    std::vector<std::size_t> factor_of(plan.size(), 0);   // 0: held; else the factor, from 1
    for (std::size_t k = 0; k < plan.size(); k++) {
        if (!d.varies[k]) continue;
        std::optional<std::string> g = sample_group(plan[k]);
        std::string key = g ? *g : d.names[k];
        auto it = by_key.find(key);
        if (it == by_key.end()) {
            keys.push_back(key);
            groups.push_back(g);
            members.emplace_back();
            it = by_key.emplace(key, keys.size()).first;
        }
        members[it->second - 1].push_back(static_cast<long long>(k));
        factor_of[k] = it->second;
    }
    if (keys.empty()) throw ArgumentError("Every sampled input is held, so a sensitivity design has nothing to vary.");
    CorrelationPairs cp = correlation_pairs(project, d.names);
    std::vector<CorrelationPair> between;
    for (const auto& pr : cp.pairs) {
        std::size_t fa = factor_of[static_cast<std::size_t>(pr.a)], fb = factor_of[static_cast<std::size_t>(pr.b)];
        if (fa > 0 && fb > 0 && fa != fb) between.push_back(pr);
    }
    std::optional<std::vector<double>> corr;
    double shrunk = 0.0;
    if (method == "shapley" && !between.empty()) {
        std::size_t K = keys.size();
        std::vector<double> R(K * K, 0.0);
        for (std::size_t j = 0; j < K; j++) R[j * K + j] = 1.0;
        for (const auto& pr : between) {
            std::size_t a = factor_of[static_cast<std::size_t>(pr.a)] - 1, b = factor_of[static_cast<std::size_t>(pr.b)] - 1;
            double r = 2 * lm_sin((PB_PI * pr.r) / 6);
            R[a * K + b] = r;
            R[b * K + a] = r;
        }
        // Correlations given pair by pair need not be consistent with each other. Shrunk
        // towards independence until they are, and said.
        double lam = 0.0;
        while (lam < 1) {
            std::vector<double> S(K * K);
            for (std::size_t i = 0; i < K * K; i++) S[i] = i % (K + 1) == 0 ? 1.0 : (1 - lam) * R[i];
            if (gsa_cholesky(S, static_cast<long long>(K))) {
                corr = S;
                shrunk = lam;
                break;
            }
            lam += 0.05;
        }
    }
    auto design = std::make_shared<GsaDesign>(build_design(method, keys, opts, d.seed, corr ? &*corr : nullptr));
    long long n = design->runs;
    ValueTable values(plan.size(), n);
    for (std::size_t k = 0; k < plan.size(); k++) {
        std::size_t f = factor_of[k];
        if (f == 0) {
            for (long long i = 0; i < n; i++) values(k, i) = d.best[k];
            continue;
        }
        Json spec = plan[k].spec;
        if (spec.is_object() && spec.get("kind") == "pg" && !(spec.get("inorder").is_bool() && !spec.get("inorder").as_bool())) {
            spec = spec.shallow();
            spec.set("inorder", Json(false));
        }
        ValueDrawer drawer(spec);
        for (long long i = 0; i < n; i++) values(k, i) = draw_value(drawer, design->at(static_cast<int>(f - 1), i), i);
    }
    Json factors = Json::array();
    for (std::size_t j = 0; j < keys.size(); j++) {
        Json m = Json::array();
        for (long long k : members[j]) m.push(Json(k + 1));
        factors.push(Json::object({{"key", Json(keys[j])}, {"group", groups[j] ? Json(*groups[j]) : Json()}, {"members", m}}));
    }
    d.stats = Json::object({{"seed", d.seed}, {"latin", Json(false)}, {"sampled", Json(static_cast<long long>(plan.size()))},
                            {"gsa", Json::object({{"method", method}, {"options", design->fields.get("options")}, {"factors", factors},
                                                  {"correlated", Json(static_cast<long long>(between.size()))},
                                                  {"correlationsUsed", Json(corr.has_value())}, {"correlationShrunk", Json(shrunk)},
                                                  {"correlationProblems", Json::array(cp.problems)}})}});
    d.iterations = n;
    d.values = std::move(values);
    d.gsa_design = design;
    return d;
}

}  // namespace

bool can_be_endpoint(const Json& kind) { return !(kind == "parameter" || kind == "lookup"); }

bool pb_truthy_opt(const Json& x) {
    return !(x.is_null() || (x.is_bool() && !x.as_bool()) || (x.is_object() && x.empty()));
}

std::string pb_py_str(const Json& v) {
    switch (v.type()) {
        case Json::Type::String: return v.as_string();
        case Json::Type::Bool: return v.as_bool() ? "True" : "False";
        case Json::Type::Int: return std::to_string(v.as_int());
        case Json::Type::Float: return py_repr(v.as_double());
        case Json::Type::Null: return "None";
        default: return julia_show(v);
    }
}

std::optional<std::string> sample_group(const PlanEntry& entry) {
    const Json& spec = entry.spec;
    const Json& g = spec.is_object() ? spec.get("group") : Json::null_value;
    if (g.is_null()) return std::nullopt;
    std::string text = pb_py_str(g);
    std::string_view t = jl_strip(text);
    if (t.empty()) return std::nullopt;
    return std::string(t);
}

std::string sample_slot_name(const PlanEntry& entry) {
    if (entry.index.empty()) return entry.name;
    std::string out = entry.name + "[";
    bool first = true;
    for (const auto& [list, index] : entry.index) {
        out += (first ? "" : "][") + index;
        first = false;
    }
    return out + "]";
}

ShapeEstimate estimate(long long series, long long times, long long iterations, std::string_view precision) {
    auto wrap = [](long long a, long long b) {
        return static_cast<long long>(static_cast<unsigned long long>(a) * static_cast<unsigned long long>(b));
    };
    long long b = wrap(wrap(wrap(series, times), iterations), precision == "float32" ? 4 : 8);
    std::string text;
    char buf[64];
    if (b >= 1073741824) {
        std::snprintf(buf, sizeof buf, "%.1f GB", static_cast<double>(b) / 1073741824);
        text = buf;
    } else if (b >= 1048576) {
        // Julia's `round(Int, x)`: the nearest, a tie to the even one.
        text = std::to_string(static_cast<long long>(std::nearbyint(static_cast<double>(b) / 1048576))) + " MB";
    } else {
        text = std::to_string(std::max(1LL, static_cast<long long>(std::nearbyint(static_cast<double>(b) / 1024)))) + " kB";
    }
    return {b, text};
}

std::string hold_precision(long long series, long long times, long long iterations, long long most) {
    return estimate(series, times, iterations).bytes > most ? "float32" : "double";
}

std::vector<double> sample_occurrences(double rate, double frm, double until, Mulberry32& stream, long long most) {
    std::vector<double> out;
    if (!(rate > 0 && until > frm)) return out;
    double t = frm;
    while (true) {
        double u = stream.next();
        t += (-js_log(u > 0 ? u : PB_MIN_VALUE)) / rate;
        if (t >= until) break;
        out.push_back(t);
        if (static_cast<long long>(out.size()) >= most) break;
    }
    return out;
}

std::vector<PlanEntry> sampling_plan(const Project& project, const System& sys) {
    std::vector<PlanEntry> every = distributed_slots(sys);
    const Json& chosen = project.simulation.get("varied");
    if (!(chosen.is_array() && !chosen.empty())) return every;
    // `Set{Any}(chosen)`: a name is in it as the same text, and only so.
    std::set<std::string> want;
    for (const Json& v : chosen.arr())
        if (v.is_string()) want.insert(v.as_string());
    std::vector<PlanEntry> kept;
    for (const auto& e : every)
        if (want.count(sample_slot_name(e)) || want.count(e.name)) kept.push_back(e);
    return kept.empty() ? every : kept;
}

std::vector<PlanEntry> sampling_plan(const std::shared_ptr<const Project>& project) {
    System sys(project, false);
    return sampling_plan(*project, sys);
}

ValueTable::ValueTable(std::size_t inputs_, long long realisations_) : inputs(inputs_), realisations(realisations_) {
    data = jl_zeros(jl_array_count(static_cast<long long>(inputs_), realisations_));
}

Json SampleDesign::plan_json() const {
    Json out = Json::array();
    for (const auto& e : plan) out.push(e.json());
    return out;
}

SampleDesign design_for(const Project& project, const System& sys, const DesignOptions& options) {
    Json tornado = pb_truthy_opt(options.tornado) ? options.tornado : Json();
    Json gsa = pb_truthy_opt(options.gsa) ? options.gsa : Json();
    bool has_tornado = !tornado.is_null(), has_gsa = !gsa.is_null();
    SampleDesign d;
    d.seed = options.seed;
    d.plan = sampling_plan(project, sys);
    bool dice = false;
    for (const auto& D : sys.builder->disruption_layout) {
        const Json& sampled = D->block.get("sampled");
        if (D->timing == "poisson" && !(sampled.is_bool() && !sampled.as_bool())) dice = true;
    }
    if (d.plan.empty() && !(dice && !has_tornado && !has_gsa)) {
        std::string what = has_tornado ? "tornado swings" : "sensitivity design varies";
        std::string tail = dice ? ", and a " + what +
                                      " parameters; the disruptive events are what varies here, and they need a probabilistic run."
                                : std::string(", so every realisation would be the same run. Give a parameter one first \xe2\x80\x94"
                                              " the curve at the end of its row in the left panel \xe2\x80\x94"
                                              " or add a disruptive event that draws its occurrences.");
        throw ArgumentError("No parameter in this model has a distribution" + tail);
    }
    const std::vector<PlanEntry>& plan = d.plan;
    for (const auto& e : plan) {
        d.names.push_back(sample_slot_name(e));
        d.best.push_back(sys.P[static_cast<std::size_t>(e.slot)]);
    }
    std::set<std::string> wanted;
    if (options.varied) wanted.insert(options.varied->begin(), options.varied->end());
    for (std::size_t k = 0; k < plan.size(); k++) d.varies.push_back(!options.varied || wanted.count(d.names[k]) > 0);

    if (has_tornado) {
        auto [low, high] = tornado_ends(tornado);
        std::vector<std::size_t> swung;
        for (std::size_t k = 0; k < plan.size(); k++)
            if (d.varies[k]) swung.push_back(k);
        long long n = 2 * static_cast<long long>(swung.size()) + 1;
        ValueTable values(plan.size(), n);
        for (long long i = 0; i < n; i++)
            for (std::size_t k = 0; k < plan.size(); k++) {
                if (i == 0 || swung[static_cast<std::size_t>((i - 1) / 2)] != k) values(k, i) = d.best[k];
                else values(k, i) = value_at_probability(plan[k].spec, (i - 1) % 2 == 0 ? low : high, i);
            }
        Json swung_json = Json::array();
        for (std::size_t k : swung) swung_json.push(Json(static_cast<long long>(k + 1)));
        d.stats = Json::object({{"seed", d.seed}, {"latin", Json(false)}, {"sampled", Json(static_cast<long long>(plan.size()))},
                                {"tornado", Json::object({{"low", Json(low)}, {"high", Json(high)}, {"swung", swung_json}})}});
        d.iterations = n;
        d.values = std::move(values);
        return d;
    }
    if (has_gsa) return pb_gsa_design(project, std::move(d), gsa);

    double count = options.iterations ? *options.iterations : 100.0;
    long long n = std::max(1LL, jl_to_int(std::floor(count + 0.5)));
    std::vector<std::vector<double>> draws;
    for (std::size_t k = 0; k < plan.size(); k++) {
        std::optional<std::string> g = sample_group(plan[k]);
        Mulberry32 stream = stream_for(d.seed, g ? *g : d.names[k]);
        draws.push_back(uniforms(n, stream, options.latin));
    }
    CorrelationPairs cp = correlation_pairs(project, d.names);
    std::vector<std::string> problems = cp.problems;
    std::vector<bool> grouped(plan.size(), false);
    for (std::size_t k = 0; k < plan.size(); k++) grouped[k] = sample_group(plan[k]).has_value();
    for (const auto& pr : cp.pairs) {
        std::size_t a = static_cast<std::size_t>(pr.a), b = static_cast<std::size_t>(pr.b);
        if (!(grouped[a] || grouped[b])) continue;
        const std::string& who = grouped[a] ? d.names[a] : d.names[b];
        problems.push_back(d.names[a] + " and " + d.names[b] + ": " + who +
                           " is in a correlation group, which already fixes its sample. The correlation was ignored.");
    }
    std::vector<CorrelationPair> usable;
    for (const auto& pr : cp.pairs) {
        std::size_t a = static_cast<std::size_t>(pr.a), b = static_cast<std::size_t>(pr.b);
        if (d.varies[a] && d.varies[b] && !grouped[a] && !grouped[b]) usable.push_back(pr);
    }
    // (The seed is read only where a stream is drawn: none is with no pairs or under three
    // realisations, and every draw above has read it already.)
    ImanConover corr = usable.empty() || n < 3 ? ImanConover{} : iman_conover(draws, usable, d.names, sm_to_uint32(d.seed));
    ValueTable values(plan.size(), n);
    for (std::size_t k = 0; k < plan.size(); k++) {
        if (d.varies[k]) {
            pb_draw(values, k, ValueDrawer(plan[k].spec), draws[k]);
        } else {
            for (long long i = 0; i < n; i++) values(k, i) = d.best[k];
        }
    }
    std::vector<std::pair<std::string, std::vector<std::string>>> groups;
    for (std::size_t k = 0; k < plan.size(); k++) {
        std::optional<std::string> g = sample_group(plan[k]);
        if (!g) continue;
        auto it = std::find_if(groups.begin(), groups.end(), [&](const auto& x) { return x.first == *g; });
        if (it == groups.end()) {
            groups.emplace_back(*g, std::vector<std::string>{});
            it = groups.end() - 1;
        }
        it->second.push_back(d.names[k]);
    }
    Json groups_json = Json::array();
    for (const auto& [g, m] : groups) groups_json.push(Json::object({{"name", Json(g)}, {"members", Json::array(m)}}));
    d.stats = Json::object({{"seed", d.seed}, {"latin", Json(options.latin)}, {"sampled", Json(static_cast<long long>(plan.size()))},
                            {"correlated", Json(static_cast<long long>(corr.columns.size()))}, {"correlationAdjusted", Json(corr.adjusted)},
                            {"correlationProblems", Json::array(problems)}, {"groups", groups_json}});
    d.iterations = n;
    d.values = std::move(values);
    return d;
}

ValueTable effective_values(const SampleDesign& design, long long frm, long long to) {
    std::size_t nplan = design.plan.size();
    ValueTable eff(nplan, to - frm);
    // A realisation the design does not have is Julia's BoundsError, where it reads one.
    auto value = [&](std::size_t k, long long j) {
        if (j < 0 || j >= design.iterations)
            throw JuliaError("BoundsError", "BoundsError: realisation " + std::to_string(j + 1) + " of " + std::to_string(design.iterations));
        return design.values(k, j);
    };
    for (std::size_t k = 0; k < nplan; k++) {
        double prev = design.best[k];
        if (design.varies[k]) {
            // What the realisations before `frm` left it at.
            for (long long j = frm - 1; j >= 0; j--) {
                double v = value(k, j);
                if (std::isfinite(v)) {
                    prev = v;
                    break;
                }
            }
        }
        for (long long c = 0; c < to - frm; c++) {
            double v = value(k, frm + c);
            if (std::isfinite(v)) prev = v;
            else if (!design.varies[k]) prev = design.best[k];
            eff(k, c) = prev;
        }
    }
    return eff;
}

void apply_realisation(System& sys, const SampleDesign& design, const ValueTable& eff, long long column, long long i) {
    for (std::size_t k = 0; k < design.plan.size(); k++) {
        if (column < 0 || column >= eff.realisations || k >= eff.inputs)
            throw JuliaError("BoundsError", "BoundsError: column " + std::to_string(column + 1) + " of " + std::to_string(eff.realisations));
        sys.P[static_cast<std::size_t>(design.plan[k].slot)] = eff(k, column);
    }
    sys.evaluate_invariant();
    draw_disruptions(sys, design.seed, i, !design.is_designed());
}

void draw_disruptions(System& sys, const Json& seed, long long i, bool sample) {
    const Builder& b = *sys.builder;
    for (const auto& D : b.disruption_layout) {
        int index = D->number;
        const Json& sampled = D->block.get("sampled");
        if (D->timing != "poisson" || (sampled.is_bool() && !sampled.as_bool()) || !sample) {
            sys.set_disruption(index, false);
            continue;
        }
        auto slot_of = [&](const char* key) -> std::optional<int> {
            const EntryPtr* s = D->setting_at(key);
            return s ? std::optional<int>((*s)->base) : std::nullopt;
        };
        std::optional<int> rate_slot = slot_of("rate"), from_slot = slot_of("from"), until_slot = slot_of("until");
        auto fixed = [&](const std::optional<int>& slot) { return !slot || b.slot_class[static_cast<std::size_t>(*slot)] == 0; };
        if (!fixed(rate_slot) || !fixed(from_slot) || !fixed(until_slot)) {
            sys.set_disruption(index, false);
            continue;
        }
        double rate = rate_slot ? sys.X[static_cast<std::size_t>(*rate_slot)] : NaN;
        double frm = from_slot ? sys.X[static_cast<std::size_t>(*from_slot)] : sys.start_time;
        double until = until_slot ? sys.X[static_cast<std::size_t>(*until_slot)] : sys.end_time;
        Mulberry32 stream = stream_for(seed, D->q + "#occurrences#" + std::to_string(i));
        std::vector<double> times = sample_occurrences(rate, pb_pymax(frm, sys.start_time), pb_pymin(until, sys.end_time), stream);
        sys.set_disruption(index, true, std::move(times));
    }
}

}  // namespace kompartment
