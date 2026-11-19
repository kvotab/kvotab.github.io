// The statistics against the Julia package's (tools/stats_fixtures.jl writes
// tests/fixtures/stats.json): JavaScript's rules for what a model file holds, the
// named streams and the columns of uniforms, the normal distribution, every kind of
// distribution read at a grid of probabilities, the correlation pairs and
// Iman-Conover, and every sensitivity method's settings, runs, refusals and design,
// each to the bit. A case is a function and its arguments; what it gives is written
// as text, as the tool writes it, and compared (a short text as it is, a long one by
// its hash).

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <functional>
#include <string>
#include <vector>

#include "check.hpp"
#include "engine/probabilistic.hpp"
#include "engine/project.hpp"
#include "stats/correlate.hpp"
#include "stats/gsa_design.hpp"
#include "stats/normal.hpp"
#include "stats/pdf.hpp"
#include "stats/sample.hpp"
#include "util/errors.hpp"
#include "util/json.hpp"
#include "util/parity.hpp"

using namespace kompartment;

namespace {

std::string bits(double x) {
    if (std::isnan(x)) return "nan";
    std::uint64_t u;
    std::memcpy(&u, &x, 8);
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(u));
    return buf;
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
std::string join(const std::vector<std::string>& v, const std::string& sep) {
    std::string s;
    for (std::size_t i = 0; i < v.size(); i++) s += (i ? sep : "") + v[i];
    return s;
}

double unF(const Json& s) {
    std::uint64_t u = std::strtoull(s.as_string().c_str() + 2, nullptr, 16);
    double x;
    std::memcpy(&x, &u, 8);
    return x;
}
std::vector<double> unF_list(const Json& v) {
    std::vector<double> out;
    for (const Json& s : v.arr()) out.push_back(unF(s));
    return out;
}
std::vector<std::vector<double>> unF_columns(const Json& v) {
    std::vector<std::vector<double>> out;
    for (const Json& c : v.arr()) out.push_back(unF_list(c));
    return out;
}
/// `{"$undefined": true}` is JavaScript's `undefined`: none.
const Json* val(const Json& v) { return v.is_object() && v.has("$undefined") ? nullptr : &v; }
std::vector<std::string> strings(const Json& v) {
    std::vector<std::string> out;
    for (const Json& s : v.arr()) out.push_back(s.as_string());
    return out;
}

/// What a case gives, or the error it raises as the tool writes one.
std::string said(const std::function<std::string()>& f) {
    try {
        return f();
    } catch (const ArgumentError& e) {
        return std::string("error:ArgumentError:") + e.what();
    } catch (const JuliaError& e) {
        return "error:" + e.kind;
    }
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

/// A design as the tool dumps Julia's dictionary: `u` K rows of `runs` numbers.
std::string tdump(const GsaDesign& d) {
    std::string s = "{";
    bool first = true;
    for (const auto& [k, x] : d.fields.obj()) {
        s += (first ? "" : ";") + k + "=";
        first = false;
        if (k == "u") {
            s += "[";
            for (int r = 0; r < d.K; r++) {
                s += (r ? ",[" : "[");
                for (long long c = 0; c < d.runs; c++) s += (c ? "," : "") + ("f" + bits(d.at(r, c)));
                s += "]";
            }
            s += "]";
        } else {
            s += tdump(x);
        }
    }
    return s + "}";
}

template <class T>
std::string tdump_rows(const std::vector<std::vector<T>>& rows) {
    std::string s = "[";
    for (std::size_t r = 0; r < rows.size(); r++) {
        s += (r ? ",[" : "[");
        for (std::size_t c = 0; c < rows[r].size(); c++) s += (c ? "," : "") + ("i" + std::to_string(rows[r][c]));
        s += "]";
    }
    return s + "]";
}
std::string tdump_list(const std::vector<long long>& v) {
    std::string s = "[";
    for (std::size_t i = 0; i < v.size(); i++) s += (i ? "," : "") + ("i" + std::to_string(v[i]));
    return s + "]";
}

std::vector<std::vector<long long>> int_rows(const Json& v) {
    std::vector<std::vector<long long>> out;
    for (const Json& r : v.arr()) {
        std::vector<long long> row;
        for (const Json& x : r.arr()) row.push_back(x.as_int());
        out.push_back(row);
    }
    return out;
}

struct Grids {
    std::vector<double> us, xs;
    Json xj;
};

std::string run_case(const std::string& fn, const Json& args, const Grids& grids) {
    if (fn == "jsrules") {
        const Json* v = val(args[0]);
        std::vector<std::string> parts = {pd_truthy(v) ? "true" : "false", pd_js_str(v), said([&] { return bits(pd_to_number(v)); }),
                                          said([&] { return std::to_string(sm_to_uint32(v)); })};
        if (v != nullptr) {
            parts.push_back(said([&] {
                auto z = normal_probit(*v);
                return z ? bits(*z) : std::string("none");
            }));
        }
        if (v != nullptr && v->is_string()) {
            parts.emplace_back(pd_js_trim(v->as_string()));
            parts.emplace_back(jl_strip(v->as_string()));
        }
        return join(parts, "|");
    }
    if (fn == "stream") {
        return said([&] {
            Mulberry32 g = stream_for(args[0], val(args[1]));
            std::string s = std::to_string(g.a) + "|";
            std::vector<double> d;
            for (int k = 0; k < 8; k++) d.push_back(g.next());
            return s + nums(d);
        });
    }
    if (fn == "fnv") return std::to_string(fnv_hash(args[0].as_string()));
    if (fn == "uniforms") {
        return said([&] {
            Mulberry32 g = stream_for(args[0], &args[1]);
            return nums(uniforms(args[2].as_int(), g, args[3].as_bool()));
        });
    }
    if (fn == "take") {
        return said([&] {
            Mulberry32 g = stream_for(args[0], &args[1]);
            return nums(take_uniforms(g, args[2].as_int()));
        });
    }
    if (fn == "normal") {
        double x = unF(args[0]);
        auto z = normal_probit(x);
        return bits(normal_phi(x)) + "|" + (z ? bits(*z) : "none") + "|" + bits(normal_quantile(x));
    }
    if (fn == "spec") {
        const Json& s = args[0];
        std::vector<std::string> lines = {std::string("complete=") + (pdf_complete(s) ? "true" : "false")};
        lines.push_back("cuts=" + said([&] {
                            ProbabilityCuts c = probability_cuts(s);
                            return bits(c.lo) + "," + bits(c.hi) + "," + (c.cut ? "true" : "false") + "," + (c.reversed ? "true" : "false");
                        }));
        std::optional<ValueDrawer> dr;
        try {
            dr.emplace(s);
        } catch (const ArgumentError& e) {
            lines.push_back(std::string("drawer=error:ArgumentError:") + e.what());
        }
        for (std::size_t k = 0; k < grids.us.size(); k++) {
            double u = grids.us[k];
            long long at = static_cast<long long>(k % 11);
            lines.push_back(said([&] { return bits(value_at_probability(s, u, at)); }) + ";" +
                            (dr ? said([&] { return bits(draw_value(*dr, u, at)); }) : std::string("-")) + ";" +
                            said([&] { return bits(pdf_quantile(s, u)); }));
        }
        std::vector<std::string> cdfs;
        for (double x : grids.xs) cdfs.push_back(said([&] { return bits(pdf_cdf(s, x)); }));
        lines.push_back(join(cdfs, ";"));
        std::vector<std::string> js;
        for (const Json& x : grids.xj.arr())
            js.push_back(said([&] { return bits(pdf_cdf(s, val(x))); }) + "/" + said([&] { return bits(pdf_quantile(s, val(x))); }));
        lines.push_back(join(js, ";"));
        return join(lines, "\n");
    }
    if (fn == "vap") return said([&] { return bits(value_at_probability(args[0], unF(args[1]), args[2].as_int())); });
    if (fn == "pairs") {
        std::vector<std::string> names = strings(args[1]);
        CorrelationPairs cp;
        if (args[0].is_object() && args[0].has("$project")) cp = correlation_pairs(Project(args[0].get("$project")), names);
        else cp = correlation_pairs_of_model(args[0], names);
        std::vector<std::string> pairs;
        for (const auto& p : cp.pairs) pairs.push_back(std::to_string(p.a) + "," + std::to_string(p.b) + "," + bits(p.r));
        return join(pairs, ";") + "\n" + join(cp.problems, "\n");
    }
    if (fn == "iman") {
        auto cols = unF_columns(args[0]);
        std::vector<CorrelationPair> pairs;
        for (const Json& p : args[1].arr())
            pairs.push_back(CorrelationPair{static_cast<int>(p[0].as_int()), static_cast<int>(p[1].as_int()), unF(p[2])});
        std::vector<std::string> names = strings(args[2]);
        return said([&] {
            ImanConover res = iman_conover(cols, pairs, names, sm_to_uint32(args[3]));
            std::vector<std::string> moved;
            for (int c : res.columns) moved.push_back(std::to_string(c));
            std::string s = "moved=" + join(moved, ",") + ";adjusted=" + bits(res.adjusted);
            for (const auto& c : cols) s += "\n" + nums(c);
            return s;
        });
    }
    if (fn == "gsa") {
        const Json& m = args[0];
        long long Kn = args[1].as_int();
        const Json* g = val(args[2]);
        std::string o = said([&] { return tdump(gsa_options(m, Kn, g)); });
        std::string r = said([&] { return tdump(gsa_runs(m, Kn, g)); });
        std::string f = said([&] {
            auto x = gsa_refusal(m, Kn, g);
            return x ? *x : std::string("none");
        });
        return o + "\n" + r + "\n" + f;
    }
    if (fn == "design") {
        return said([&] {
            std::vector<double> corr;
            if (!args[4].is_null()) corr = unF_list(args[4]);
            const Json* options = args[2].is_null() ? nullptr : &args[2];
            return tdump(build_design(args[0], strings(args[1]), options, args[3], args[4].is_null() ? nullptr : &corr));
        });
    }
    if (fn == "morris_design") {
        return said([&] {
            Mulberry32 g = stream_for(args[4], &args[5]);
            return tdump(morris_design(static_cast<int>(args[0].as_int()), args[1].as_int(), args[2].as_int(), args[3].as_int(), g));
        });
    }
    if (fn == "morris_trajectory") {
        Mulberry32 g = stream_for(args[2], &args[3]);
        std::vector<std::string> out;
        for (long long t = 0; t < args[4].as_int(); t++)
            out.push_back(tdump_rows(morris_trajectory(static_cast<int>(args[0].as_int()), args[1].as_int(), g)));
        return join(out, "\n");
    }
    if (fn == "trajectory_distance") return bits(trajectory_distance(int_rows(args[0]), int_rows(args[1])));
    if (fn == "optimal_trajectories") {
        Mulberry32 g = stream_for(args[2], &args[3]);
        std::vector<std::vector<std::vector<long long>>> cands;
        for (long long t = 0; t < args[4].as_int(); t++) cands.push_back(morris_trajectory(static_cast<int>(args[0].as_int()), args[1].as_int(), g));
        return said([&] {
            std::vector<std::string> out;
            for (long long i : optimal_trajectories(cands, args[5].as_int())) out.push_back(std::to_string(i));
            return join(out, ",");
        });
    }
    if (fn == "morris_trajectory_design") {
        return said([&] {
            Mulberry32 g = stream_for(args[4], &args[5]);
            return tdump(morris_trajectory_design(static_cast<int>(args[0].as_int()), args[1].as_int(), args[2].as_int(), args[3].as_int(), g));
        });
    }
    if (fn == "radial_design") return tdump(radial_design(static_cast<int>(args[0].as_int()), unF_columns(args[1]), unF_columns(args[2])));
    if (fn == "sobol_design") {
        long long n = args[1].as_int();
        const Json& seed = args[4];
        return said([&] {
            return tdump(sobol_design(static_cast<int>(args[0].as_int()), n, args[2].as_bool(), args[3].as_int(),
                                      [&](int k, const std::string& which, long long b) {
                                          Mulberry32 g = stream_for(seed, std::to_string(k + 1) + "#" + which + "#" + std::to_string(b));
                                          return uniforms(n, g, true);
                                      }));
        });
    }
    if (fn == "efast_samples")
        return said([&] {
            // Julia's `string()`: a whole number, or past the counts a double, as Julia shows one.
            const Json N = efast_samples(args[0], args[1]);
            return N.is_int() ? std::to_string(N.as_int()) : julia_float(N.as_double());
        });
    if (fn == "efast_frequencies") return said([&] { return nums(efast_frequencies(args[0].as_int(), args[1].as_int(), args[2].as_int())); });
    if (fn == "efast_design") {
        return said([&] {
            return tdump(efast_design(static_cast<int>(args[0].as_int()), args[1].as_int(), args[2].as_int(), unF_list(args[3])));
        });
    }
    if (fn == "rbd_fast_design") {
        int Kn = static_cast<int>(args[0].as_int());
        long long N = args[1].as_int();
        std::vector<std::vector<long long>> perms;
        for (int k = 1; k <= Kn; k++) {
            Mulberry32 g = stream_for(args[2], std::to_string(k) + "#rbd");
            perms.push_back(gsa_random_permutation(N, g));
        }
        return said([&] { return tdump(rbd_fast_design(Kn, N, perms)); });
    }
    if (fn == "ff_design") return tdump(ff_design(static_cast<int>(args[0].as_int()), unF(args[1]), unF(args[2])));
    if (fn == "dgsm_design")
        return tdump(dgsm_design(static_cast<int>(args[0].as_int()), unF_columns(args[1]), unF(args[2]), args[3].as_bool()));
    if (fn == "shapley_design") {
        return said([&] {
            std::vector<double> corr;
            if (!args[5].is_null()) corr = unF_list(args[5]);
            Mulberry32 g = stream_for(args[6], &args[7]);
            return tdump(shapley_design(static_cast<int>(args[0].as_int()), args[1].as_int(), args[2].as_int(), args[3].as_int(),
                                        args[4].as_int(), args[5].is_null() ? nullptr : &corr, g));
        });
    }
    if (fn == "hadamard") return said([&] { return tdump_rows(gsa_hadamard(args[0].as_int())); });
    if (fn == "permutations") return tdump_rows(gsa_permutations(args[0].as_int()));
    if (fn == "random_permutation") {
        Mulberry32 g = stream_for(args[1], &args[2]);
        return tdump_list(gsa_random_permutation(args[0].as_int(), g));
    }
    if (fn == "cholesky") {
        std::vector<double> A = unF_list(args[0]);
        long long n = args[1].as_int();
        auto L = gsa_cholesky(A, n);
        return (L ? nums(*L) : std::string("none")) + "|" + said([&] { return nums(gsa_jitter_cholesky(A, n)); });
    }
    if (fn == "small") {
        double x = unF(args[0]);
        return bits(gsa_sinpi(x)) + "|" + bits(gsa_round(x)) + "|" + std::to_string(gsa_int32(x));
    }
    if (fn == "estimate") {
        long long s = args[0].as_int(), t = args[1].as_int(), it = args[2].as_int();
        ShapeEstimate e = estimate(s, t, it), f = estimate(s, t, it, "float32");
        return std::to_string(e.bytes) + "|" + e.text + "|" + std::to_string(f.bytes) + "|" + f.text + "|" + hold_precision(s, t, it);
    }
    if (fn == "occurrences") {
        Mulberry32 g = stream_for(args[3], &args[4]);
        return nums(sample_occurrences(unF(args[0]), unF(args[1]), unF(args[2]), g, args[5].as_int()));
    }
    if (fn == "py_str") return pb_py_str(args[0]);
    throw std::runtime_error("no such case: " + fn);
}

}  // namespace

int main() {
    Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/stats.json"));
    const char* dumps = std::getenv("KOMPARTMENT_FIXTURE_DUMPS");
    set_parity(true);
    Grids grids;
    grids.us = unF_list(fx.get("grids").get("us"));
    grids.xs = unF_list(fx.get("grids").get("xs"));
    grids.xj = fx.get("grids").get("xj");
    std::string all;
    int n = 0;
    for (const Json& c : fx.get("cases").arr()) {
        const std::string& fn = c.get("fn").as_string();
        std::string head = fn + " " + json_text(c.get("args"), 0);
        std::string text;
        try {
            text = run_case(fn, c.get("args"), grids);
        } catch (const std::exception& e) {
            text = std::string("raised here: ") + e.what();
        }
        all += (n++ ? "\n\n" : "") + head + "\n" + text;
        CHECK_MSG(kept(text) == c.get("out").as_string(), head + "\n   here:  " + kept(text) + "\n   there: " + c.get("out").as_string());
    }
    if (dumps && *dumps) std::ofstream(std::string(dumps) + "/stats.cpp.txt", std::ios::binary) << all;
    set_parity(false);
    std::printf("%d cases\n", n);
    return check::summary("test_stats");
}
