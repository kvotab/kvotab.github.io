// The Laplace-domain far field (src/engine/farfield_laplace.*) against the Julia
// engine's, with parity on (tools/laplace_fixtures.jl writes
// tests/fixtures/laplace.json).
//
// The helpers first: the complex arithmetic a path is written in, Python's log
// and the quintic Hermite step, each called on the fixture's numbers and
// compared to the bit. Then paths made up to reach every branch, each worked
// through the same calls in the same order as the tool makes them -- the path
// as prepared or its refusal word for word, its unit responses with the
// evaluation counters, T(0), the transfer function, the scalar functions and
// their series, each pair's transforms, singularities, axes, saddles, support,
// inversions and shared cells -- and every text compared with Julia's.

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <optional>

#include "check.hpp"
#include "engine/farfield_laplace.hpp"
#include "util/json.hpp"
#include "util/parity.hpp"

using namespace kompartment;
using namespace kompartment::lp;

static std::string bits(double x) {
    std::uint64_t u;
    std::memcpy(&u, &x, 8);
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(u));
    return buf;
}
static double unbits(const std::string& s) {
    std::uint64_t u = std::strtoull(s.c_str(), nullptr, 16);
    double x;
    std::memcpy(&x, &u, 8);
    return x;
}
static std::string fnv(const std::string& text) {
    std::uint64_t h = 0xcbf29ce484222325ULL;
    for (unsigned char b : text) h = (h ^ b) * 0x100000001b3ULL;
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(h));
    return buf;
}
// A NaN is a NaN whatever its bits.
template <class V>
static std::string nums(const V& v) {
    std::string s;
    bool first = true;
    for (double x : v) {
        if (!first) s += ",";
        first = false;
        s += std::isnan(x) ? std::string("nan") : bits(x);
    }
    return s;
}
static std::string nums(std::initializer_list<double> v) { return nums(std::vector<double>(v)); }
template <class V>
static std::string ints(const V& v) {
    std::string s;
    bool first = true;
    for (auto x : v) {
        if (!first) s += ",";
        first = false;
        s += std::to_string(static_cast<long long>(x));
    }
    return s;
}
static std::string cx(Cx z) { return nums({z.re, z.im}); }
static std::string cxs(const std::vector<Cx>& v) {
    std::string s;
    for (std::size_t k = 0; k < v.size(); k++) s += (k ? ";" : "") + cx(v[k]);
    return s;
}
static std::string tf(bool b) { return b ? "true" : "false"; }
static std::string kept(const std::string& text) {
    std::size_t characters = 0;
    for (unsigned char c : text)
        if ((c & 0xC0) != 0x80) characters++;
    return characters <= 400 ? "=" + text : "#" + fnv(text);
}
static std::string joined(const std::vector<std::string>& parts, const std::string& sep) {
    std::string s;
    for (std::size_t i = 0; i < parts.size(); i++) s += (i ? sep : "") + parts[i];
    return s;
}
// What a call gave, or the kind of error Julia's would have thrown.
template <class F>
static std::string said(F&& f) {
    try {
        return f();
    } catch (const LaplacePathError& e) {
        return std::string("refused: ") + e.what();
    } catch (const std::domain_error&) {
        return "throws";
    } catch (const JlInexactError&) {
        return "inexact";
    }
}

// --- the helpers -------------------------------------------------------------------------------------------

static std::string helper(const std::string& fn, const std::vector<double>& x) {
    if (fn == "csqrt") return cx(c_sqrt({x[0], x[1]}));
    if (fn == "cexp") return cx(c_exp({x[0], x[1]}));
    if (fn == "ctanh") return cx(c_tanh({x[0], x[1]}));
    if (fn == "csech2") return cx(c_sech2({x[0], x[1]}));
    if (fn == "rmul") return cx(r_mul(x[0], {x[1], x[0]}));
    if (fn == "radd") return cx(r_add(x[0], {x[1], x[0]}));
    if (fn == "cdiv") return cx(c_div({x[0], x[1]}, {x[2], x[3]}));
    if (fn == "cmul") return cx(c_mul({x[0], x[1]}, {x[2], x[3]}));
    if (fn == "py_log") return said([&] { return nums({py_log(x[0])}); });
    if (fn == "lp_ln") return nums({lp_ln(x[0])});
    if (fn == "hermite5") return nums({hermite5(x[0], x[1], x[2], x[3], x[4], x[5], x[6], x[7], x[8])});
    return "no such helper";
}

// --- the paths -----------------------------------------------------------------------------------------------

struct Case {
    std::string name;
    LPSettings settings;
    std::optional<LPDecay> decay;
    int n = 1;
    std::optional<std::vector<std::string>> names;
    double tmax = 1e12;
    std::optional<std::vector<std::pair<int, int>>> pairs;
    bool inner = true;
    bool wanted(int i, int j) const {
        return !pairs || std::find(pairs->begin(), pairs->end(), std::make_pair(i, j)) != pairs->end();
    }
};

static Case case_of(const Json& row) {
    Case c;
    c.name = row.get("name").as_string();
    c.settings.surface = row.get("surface").as_string();
    for (const auto& [k, v] : row.get("single").obj()) c.settings.single[k] = unbits(v.as_string());
    for (const auto& [k, v] : row.get("each").obj()) {
        std::vector<double> xs;
        for (const Json& x : v.arr()) xs.push_back(unbits(x.as_string()));
        c.settings.each[k] = xs;
    }
    const Json& d = row.get("decay");
    if (!d.is_null()) {
        LPDecay D;
        for (const Json& x : d.get("lam").arr()) D.lam.push_back(unbits(x.as_string()));
        for (const Json& x : d.get("ioff").arr()) D.ioff.push_back(static_cast<int>(x.as_int()));
        for (const Json& x : d.get("icnt").arr()) D.icnt.push_back(static_cast<int>(x.as_int()));
        for (const Json& x : d.get("ipar").arr()) D.ipar.push_back(static_cast<int>(x.as_int()));
        for (const Json& x : d.get("icoef").arr()) D.icoef.push_back(unbits(x.as_string()));
        c.decay = D;
    }
    c.n = static_cast<int>(row.get("n").as_int());
    if (!row.get("names").is_null()) {
        std::vector<std::string> nm;
        for (const Json& x : row.get("names").arr()) nm.push_back(x.as_string());
        c.names = nm;
    }
    c.tmax = unbits(row.get("tmax").as_string());
    if (!row.get("pairs").is_null()) {
        std::vector<std::pair<int, int>> ps;
        for (const Json& p : row.get("pairs").arr()) ps.push_back({static_cast<int>(p.arr()[0].as_int()), static_cast<int>(p.arr()[1].as_int())});
        c.pairs = ps;
    }
    c.inner = row.get("inner").as_bool();
    return c;
}

static const std::pair<double, double> SVALS[] = {{0.0, 0.0},    {1e-300, 0.0}, {1.0, 0.0},    {1.0, 3.0},
                                                  {10.0, -1.0},  {1e-6, 1e3},   {-1e-3, 0.5},  {1e-2, 1e-2}};

// Julia's isless on numbers: NaN after everything, -0 before 0.
static bool jl_isless(double a, double b) {
    if (std::isnan(b)) return !std::isnan(a);
    if (std::isnan(a)) return false;
    if (a == b) return std::signbit(a) && !std::signbit(b);
    return a < b;
}

using Sections = std::vector<std::pair<std::string, std::string>>;

static Sections sections(const Case& c) {
    Sections S;
    std::unique_ptr<LaplacePath> owned;
    try {
        owned = prepare_path(c.settings, c.decay ? &*c.decay : nullptr, c.n, c.names ? &*c.names : nullptr);
    } catch (const LaplacePathError& e) {
        S.push_back({"refused", e.what()});
        return S;
    }
    LaplacePath& path = *owned;
    int n = path.n;
    LPWorkspace& ws = *path.ws;
    {
        std::vector<std::string> parts;
        parts.push_back(ints(path.order));
        parts.push_back(ints(path.pos));
        parts.push_back(std::to_string(path.max_block));
        parts.push_back(nums(path.lam));
        parts.push_back(nums(path.Rf));
        parts.push_back(nums(path.Rm));
        parts.push_back(nums(path.De));
        parts.push_back(ints(path.matrix));
        std::vector<std::string> ps;
        for (int i = 0; i < n; i++) {
            std::vector<std::string> one;
            for (const auto& [p, q] : path.parents[i]) one.push_back(std::to_string(p) + ":" + bits(q));
            ps.push_back(joined(one, " "));
        }
        parts.push_back(joined(ps, "/"));
        parts.push_back(nums({path.tw, path.f, path.Pe, path.aw, path.x0, path.rho}));
        parts.push_back(tf(path.inf_pe) + " " + tf(path.inf_x0));
        parts.push_back(ints(path.reach));
        parts.push_back(joined(path.names, " "));
        S.push_back({"path", joined(parts, "|")});
    }
    // The unit responses first, as the runtime asks for them of a path just prepared.
    for (int j = 0; j < n; j++)
        for (int i = 0; i < n; i++) {
            if (!c.wanted(i, j)) continue;
            std::string text = said([&] {
                LPResponse r = unit_response(path, i, j, c.tmax);
                return joined({nums(r.t), nums(r.h), nums(r.dh), nums(r.d2h),
                               nums({r.peak, r.tPeak, r.integral, r.maxCond, r.maxErr, r.m0, r.T0, r.expected, r.rel}),
                               tf(r.balanced) + " " + tf(r.checked) + " " + std::to_string(ws.evaluations) + " " + std::to_string(ws.clustered)},
                              "\n");
            });
            S.push_back({"response " + std::to_string(i) + " " + std::to_string(j), text});
        }
    {
        std::string t0 = nums(transfer_at_zero(path));
        S.push_back({"T0", t0 + " " + std::to_string(ws.evaluations)});
    }
    if (!c.inner) return S;
    std::vector<std::string> lines;
    for (int i = 0; i < n; i++)
        for (int j = 0; j < n; j++)
            for (const auto& [sr, si] : SVALS) lines.push_back(cx(lp_transfer(path, sr / path.tw, si / path.tw, i, j)));
    lines.push_back("evaluations " + std::to_string(ws.evaluations) + " clustered " + std::to_string(ws.clustered));
    S.push_back({"transfer", joined(lines, "\n")});
    lines.clear();
    const Cx zs[] = {{1e-3 / path.tw, 0.0}, {1 / path.tw, 2 / path.tw}, {-0.5 / path.tw, 0.1 / path.tw}, {5.0, -7.0},
                     {-30.0, 0.0},          {-30.0, 1e-3},              {1e-9, 1e4},                      {-1e3, -1e2}};
    for (Cx z : zs) {
        lines.push_back(said([&] {
            std::string a = cx(tau_at(path, z));
            double s1 = tau_scale(path, z);
            double s2 = h_scale(path, z);
            return a + " " + nums({s1, s2}) + " " + cx(phi_at(path, z));
        }));
        for (int k : {0, 1, 4, 17}) {
            lines.push_back(said([&] { return cxs(sqrt_series(z, {0.5, -0.25}, k)); }));
            lines.push_back(said([&] { return cxs(tau_series(path, z, k)); }));
            lines.push_back(said([&] { return cxs(h_series(path, z, 0.75, k)); }));
            lines.push_back(said([&] { return cxs(exp_series(2.5, z, k)); }));
        }
    }
    S.push_back({"series", joined(lines, "\n")});
    for (int j = 0; j < n; j++)
        for (int i = 0; i < n; i++) {
            if (!c.wanted(i, j)) continue;
            LPBlock* blk = block_of(path, i, j);
            if (!blk) continue;
            std::string pair = std::to_string(i) + " " + std::to_string(j);
            lines.clear();
            lines.push_back(ints(blk->S) + " " + nums(blk->A) + " " + nums({blk->Rmin}) + " " + tf(blk->matrix));
            for (int kind : {LP_RELEASE, LP_INVENTORY, LP_DECAYED})
                for (int q = 2; q < 8; q++) {
                    auto [sr, si] = SVALS[q];
                    lines.push_back(said([&] {
                        Cx v = eval_block(path, ws, *blk, {sr / path.tw, si / path.tw}, kind);
                        return cx(v) + " " + nums({ws.E});
                    }));
                }
            {
                double a = singularity(path, *blk);
                double b = singularity(path, *blk, LP_DECAYED);
                lines.push_back(nums({a, b}) + " " + std::to_string(ws.evaluations) + " " + std::to_string(ws.clustered));
            }
            S.push_back({"block " + pair, joined(lines, "\n")});
            double shift = path.inf_pe ? path.tw * blk->Rmin : 0.0;
            LPAxis& ax = *axis_of(path, *blk, LP_RELEASE, shift);
            lines.clear();
            lines.push_back(nums({ax.s0, ax.tLo, ax.shift}));
            lines.push_back(nums(ax.s));
            lines.push_back(nums(ax.psi));
            lines.push_back(nums(ax.sm));
            lines.push_back(nums(ax.D));
            std::optional<LPSupport> sup = response_support(ax, ax.tLo, LP_T_CAP);
            lines.push_back(!sup ? std::string("no support") : nums({sup->tLo, sup->tHi, sup->tPeak, sup->logPeak, sup->tTail}));
            double tp = !sup ? shift + path.tw : sup->tPeak;
            std::vector<double> times;
            for (double f : {1e-3, 0.03, 0.3, 1.0, 3.0, 30.0, 1e3}) times.push_back(shift + (tp - shift) * f);
            for (double t : times) {
                lines.push_back(said([&] {
                    std::optional<LPSaddle> sad = saddle_at(ax, t - shift);
                    return !sad ? std::string("none") : nums({sad->s, sad->psi2, sad->w}) + " " + tf(sad->edge) + " " + tf(sad->beyond);
                }));
                lines.push_back(said([&] {
                    double le = log_estimate(ax, t);
                    return nums({le}) + " " + std::to_string(de_hoog_terms(path, &ax, t));
                }));
            }
            lines.push_back(std::to_string(de_hoog_terms(path)) + " " + std::to_string(ws.evaluations));
            S.push_back({"axis " + pair, joined(lines, "\n")});
            lines.clear();
            for (int kind : {LP_INVENTORY, LP_DECAYED})
                lines.push_back(said([&] {
                    LPAxis& a2 = *axis_of(path, *blk, kind, 0.0);
                    return joined({nums({a2.s0, a2.tLo}), nums(a2.s), nums(a2.psi), nums(a2.D)}, "\n");
                }));
            S.push_back({"axes " + pair, joined(lines, "\n")});
            lines.clear();
            int M = de_hoog_terms(path);
            for (int q = 1; q <= 5; q++) {
                double t = times[q];
                for (double atol : {0.0, 1e-20})
                    lines.push_back(said([&] {
                        LPInv r = invert_parabola(path, ws, ax, t, atol);
                        return nums({r.h, r.dh, r.d2, r.err, r.cond}) + " " + tf(r.regrow) + " " + tf(r.bad) + " " + std::to_string(ws.evaluations);
                    }));
                for (int deriv : {-1, 0, 1, 2})
                    lines.push_back(said([&] { return nums({invert_de_hoog(path, ws, *blk, LP_RELEASE, shift, t, M, deriv)}); }));
                lines.push_back(said([&] {
                    double v = invert_de_hoog(path, ws, *blk, LP_RELEASE, shift, t, de_hoog_terms(path, &ax, t));
                    return nums({v}) + " " + std::to_string(ws.evaluations);
                }));
            }
            S.push_back({"invert " + pair, joined(lines, "\n")});
            lines.clear();
            LPCells C = make_cells(path, ax, 0.0, 0.0);
            lines.push_back(nums(C.tb));
            lines.push_back(nums(C.U));
            lines.push_back(nums(C.sig));
            lines.push_back(nums({C.peak}));
            for (double t : times) {
                lines.push_back(said([&] {
                    double u = cell_u(C, t - shift);
                    return nums({u, cell_t(C, u)});
                }));
                lines.push_back(said([&] {
                    std::optional<LPInv> r = invert_shared(path, ws, C, t);
                    return !r ? std::string("nothing") : nums({r->h, r->dh, r->d2, r->err, r->cond});
                }));
            }
            lines.push_back("shared=" + std::to_string(C.st_shared) + " fallback=" + std::to_string(C.st_fallback) + " negligible=" +
                            std::to_string(C.st_negligible) + " cells=" + std::to_string(C.st_cells) + " failed=" + std::to_string(C.st_failed) +
                            " dehoog=" + std::to_string(C.st_dehoog) + " " + std::to_string(ws.evaluations));
            std::vector<std::pair<double, const LPCell*>> built;
            for (const auto& [key, cell] : C.map) built.push_back({cell.k, &cell});
            std::sort(built.begin(), built.end(), [](const auto& a, const auto& b) { return jl_isless(a.first, b.first); });
            for (const auto& [k, cell] : built)
                lines.push_back(nums({k}) + " " + tf(cell->ok) + " " + cell->why + " " + std::to_string(cell->levels) + " " + std::to_string(cell->n) +
                                " " + nums({cell->tLo, cell->tA, cell->tHi, cell->v, cell->step, cell->strip, cell->c}) + " " +
                                fnv(joined({nums(cell->sr), nums(cell->si), nums(cell->gr), nums(cell->gi), nums(cell->ag), nums(cell->la),
                                            nums(cell->mE), ints(cell->lev)},
                                           "|")));
            S.push_back({"cells " + pair, joined(lines, "\n")});
        }
    return S;
}

int main() {
    set_parity(true);
    Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/laplace.json"));
    const char* dumps = std::getenv("KOMPARTMENT_FIXTURE_DUMPS");
    const bool trace = std::getenv("KOMPARTMENT_TEST_TRACE") != nullptr;

    long calls = 0;
    for (const Json& row : fx.get("helpers").arr()) {
        std::vector<double> x;
        for (const Json& v : row.get("x").arr()) x.push_back(unbits(v.as_string()));
        const std::string& fn = row.get("fn").as_string();
        std::string got = helper(fn, x);
        const std::string& want = row.get("out").as_string();
        if (got != want) {
            std::string args;
            for (double v : x) args += (args.empty() ? "" : ", ") + check::bits(v);
            CHECK_MSG(false, fn + "(" + args + ") is\n    " + got + "\n  and Julia's\n    " + want);
        } else {
            CHECK(true);
        }
        calls++;
    }

    long worked = 0, refused = 0;
    for (const Json& row : fx.get("paths").arr()) {
        Case c = case_of(row);
        if (trace) std::fprintf(stderr, "%s\n", c.name.c_str());
        const JObject& want = row.get("values").obj();
        Sections S;
        try {
            S = sections(c);
        } catch (const std::exception& e) {
            CHECK_MSG(false, c.name + " threw: " + e.what());
            continue;
        }
        if (dumps && *dumps) {
            std::ofstream f(std::string(dumps) + "/" + c.name + ".laplace.cpp.txt");
            bool first = true;
            for (auto [k, v] : S) {
                for (char& ch : v)
                    if (ch == ',') ch = '\n';
                f << (first ? "" : "\n") << "## " << k << "\n" << v;
                first = false;
            }
        }
        std::map<std::string, std::string> got;
        for (const auto& [k, v] : S) got[k] = v;
        for (const auto& [key, value] : want) {
            auto it = got.find(key);
            if (it == got.end()) {
                CHECK_MSG(false, c.name + ": " + key + " is not worked out here; Julia's is " + value.as_string().substr(0, 300));
                continue;
            }
            std::string mine = kept(it->second);
            if (mine == value.as_string())
                CHECK(true);
            else if (mine[0] == '=' || value.as_string()[0] == '=')
                CHECK_MSG(false, c.name + ": " + key + " is\n    " + it->second.substr(0, 600) + "\n  and Julia's\n    " + value.as_string().substr(0, 600));
            else
                CHECK_MSG(false, c.name + ": " + key + " differs");
        }
        for (const auto& [key, value] : got) CHECK_MSG(want.has(key), c.name + ": " + key + " is worked out here and not by Julia");
        (got.count("refused") ? refused : worked)++;
    }
    set_parity(false);
    std::printf("%ld helper calls, %ld paths worked through, %ld refused as Julia refuses them\n", calls, worked, refused);
    return check::summary("test_laplace");
}
