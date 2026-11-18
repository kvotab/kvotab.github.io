// The application's sparse LUs (src/solvers/sparselu.cpp): against the Python
// package's port of them, which is the application's to the bit
// (julia/tools/sparse_fixtures.py), where the fixtures have been written; and
// always against a dense solve, in every mode and kind. A port of
// julia/test/solvers/sparselu.jl.
//
//     PYTHONPATH=kompartment/python python3 kompartment/julia/tools/sparse_fixtures.py <scratch>/sparse
//     KOMPARTMENT_SPARSE_FIXTURES=<scratch>/sparse ./test_sparselu

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include "util/parity.hpp"
#include "check.hpp"
#include "solvers/solvers.hpp"
#include "util/json.hpp"

using namespace kompartment;

namespace {

int hex_digit(char c) { return c <= '9' ? c - '0' : (c | 0x20) - 'a' + 10; }

/// Doubles from little-endian hex, to the bit.
Vec unhx(const Json& h) {
    const std::string& s = h.as_string();
    Vec out(s.size() / 16);
    for (std::size_t i = 0; i < out.size(); i++) {
        unsigned char bytes[8];
        for (int b = 0; b < 8; b++) {
            bytes[b] = static_cast<unsigned char>(hex_digit(s[16 * i + 2 * static_cast<std::size_t>(b)]) * 16 +
                                                  hex_digit(s[16 * i + 2 * static_cast<std::size_t>(b) + 1]));
        }
        std::memcpy(&out[i], bytes, 8);
    }
    return out;
}

/// Whether a solve's answer is the fixture's to the bit. A NaN is a NaN whatever its sign: which
/// one a subtraction of a NaN product gives is the compiler's choice (Apple clang gives the
/// fixture's own; g++ negates the product and adds).
bool same_answer(const Vec& x, const Json& h) {
    const Vec want = unhx(h);
    if (want.size() != x.size()) return false;
    for (std::size_t i = 0; i < x.size(); i++)
        if (!check::same_bits(x[i], want[i])) return false;
    return true;
}

std::vector<I32> ivec(const Json& list) {
    std::vector<I32> out;
    out.reserve(list.size());
    for (const Json& v : list.arr()) out.push_back(static_cast<I32>(v.as_int()));
    return out;
}

/// A fill as the fixtures hold one: null where there is none.
Json fill_or_nothing(I64 f) { return f < 0 ? Json() : Json(static_cast<long long>(f)); }

int mode_of(const std::string& mode) {
    return mode == "auto" ? slu::AUTO : mode == "refactor" ? slu::REFACTOR : slu::SPARSE_MODE;
}

/// A matrix case through the port as the Python package took it: what differs, or nothing.
std::optional<std::string> replay_matrix(const Json& c, const Json& ex) {
    const int n = static_cast<int>(c.get("n").as_int());
    const bool too_big = static_cast<double>(n) * n * 8 > c.get("denseMaxBytes").as_double();
    const Json& made = ex.get("made");
    if (c.get("mode") == "auto" && n < c.get("denseBelow").as_int() && !too_big) {
        return made.get("kind").as_int() == slu::DENSE ? std::nullopt : std::optional<std::string>("dense by size");
    }
    const bool has_mass = !c.get("mass").is_null();
    const Vec mass = has_mass ? unhx(c.get("mass")) : Vec(static_cast<std::size_t>(n), 1.0);
    SparseLUMatrix sw(n, ivec(c.get("colPtr")), ivec(c.get("rowIdx")), unhx(c.get("values")), mass, has_mass,
                      mode_of(c.get("mode").as_string()), c.get("denseFill").as_double(), too_big,
                      c.get("blocks").as_bool());
    if (!(sw.kind == made.get("kind").as_int() && made.get("ordering") == slu::ORDERINGS[sw.ordering] &&
          made.get("fill") == fill_or_nothing(sw.fill))) {
        return "chose kind " + std::to_string(sw.kind) + ", " + slu::ORDERINGS[sw.ordering] + ", fill " +
               std::to_string(sw.fill) + "; Python " + json_text(made, 0);
    }
    if (sw.kind == slu::DENSE) return std::nullopt;
    const JArray& ops = c.get("ops").arr();
    const JArray& steps = ex.get("steps").arr();
    Vec x(static_cast<std::size_t>(n), 0.0);
    for (std::size_t k = 0; k < ops.size() && k < steps.size(); k++) {
        const Json& op = ops[k];
        const Json& step = steps[k];
        if (op.has("form")) {
            const Json& f = op.get("form");
            std::vector<std::uint8_t> held;
            const bool has_held = !f.get("held").is_null();
            if (has_held) {
                for (const Json& v : f.get("held").arr()) {
                    held.push_back(static_cast<std::uint8_t>(v.is_bool() ? (v.as_bool() ? 1 : 0) : v.as_int()));
                }
            }
            const int st = slu::form(sw, f.get("a").as_double(), unhx(f.get("values")), has_held ? held.data() : nullptr);
            if (!(st == step.get("status").as_int() && step.get("fill") == fill_or_nothing(sw.fill) &&
                  sw.repivots == step.get("repivots").as_int() && sw.fallbacks == step.get("fallbacks").as_int())) {
                return "form " + std::to_string(k + 1) + ": status " + std::to_string(st) + ", fill " +
                       std::to_string(sw.fill) + ", repivots " + std::to_string(sw.repivots) + ", fallbacks " +
                       std::to_string(sw.fallbacks) + "; Python " + json_text(step, 0);
            }
            if (st != slu::OK) {
                if (!(sw.fail_column == step.get("column").as_int() &&
                      sw.fail_nonfinite == step.get("nonfinite").as_bool())) {
                    return "form " + std::to_string(k + 1) + " failed at " + std::to_string(sw.fail_column) +
                           ", Python at " + std::to_string(step.get("column").as_int());
                }
            }
        } else {
            std::fill(x.begin(), x.end(), 0.0);
            slu::solve(sw, unhx(op.get("solve")), x);
            if (!same_answer(x, step.get("x"))) return "solve " + std::to_string(k + 1);
        }
    }
    return std::nullopt;
}

/// A single-LU case through the port as the Python package took it: what differs, or nothing.
std::optional<std::string> replay_part(const Json& c, const Json& ex) {
    const int n = static_cast<int>(c.get("n").as_int());
    const std::vector<I32> colptr = ivec(c.get("colPtr"));
    const std::vector<I32> rowidx = ivec(c.get("rowIdx"));
    const bool has_mass = !c.get("mass").is_null();
    const Vec mass = has_mass ? unhx(c.get("mass")) : Vec(static_cast<std::size_t>(n), 1.0);
    const JArray& ops = c.get("ops").arr();
    const JArray& steps = ex.get("steps").arr();
    Vec x(static_cast<std::size_t>(n), 0.0);
    const std::string lu_kind = c.get("lu").as_string();
    if (lu_kind == "gp") {
        const slu::MiterStructure m = slu::miter_structure(n, colptr, rowidx);
        Vec mx(m.mi.size(), 0.0);
        slu::GP g(n);
        const bool rcm = c.get("order") == "rcm";
        std::vector<I32> q(static_cast<std::size_t>(n));
        for (int i = 0; i < n; i++) q[i] = i;
        if (rcm) {
            slu::miter_update(mx, 1e-3, unhx(c.get("values")), mass, has_mass, m.jtom, m.diag);
            q = slu::rcm_order(n, m.mp, m.mi);
            if (q != ivec(ex.get("order"))) return "reverse Cuthill-McKee's order";
        }
        for (std::size_t k = 0; k < ops.size() && k < steps.size(); k++) {
            const Json& op = ops[k];
            const Json& step = steps[k];
            if (op.has("form")) {
                slu::miter_update(mx, op.get("form").get("a").as_double(), unhx(op.get("form").get("values")), mass,
                                  has_mass, m.jtom, m.diag);
                slu::gp_factorize(g, m.mp, m.mi, mx, q, rcm, sv::INF);
                if (step.get("singular").as_bool()) {
                    if (!(g.singular && g.nonfinite == step.get("nonfinite").as_bool() &&
                          g.fail_original == step.get("column").as_int())) {
                        return "factorisation " + std::to_string(k + 1);
                    }
                } else if (!(!g.singular && g.lnz == step.get("lnz").as_int() && g.unz == step.get("unz").as_int() &&
                             g.flops == step.get("flops").as_int())) {
                    return "factorisation " + std::to_string(k + 1);
                }
            } else if (step.has("x")) {
                std::fill(x.begin(), x.end(), 0.0);
                slu::gp_solve(g, unhx(op.get("solve")), x);
                if (!same_answer(x, step.get("x"))) return "solve " + std::to_string(k + 1);
            }
        }
        return std::nullopt;
    }
    const bool by_blocks = lu_kind == "blocks";
    slu::BK bk;
    slu::RF rf;
    if (by_blocks) {
        auto [nblocks, block] = slu::block_triangular(n, colptr, rowidx);
        if (!(nblocks == ex.get("blocks").get("nblocks").as_int() && block == ivec(ex.get("blocks").get("block")))) {
            return "the blocks";
        }
        bk = slu::bk_new(n, colptr, rowidx, nblocks, block);
    } else {
        const Json& given = c.get("columns");
        const std::vector<I32> columns = given.is_null() ? std::vector<I32>() : ivec(given);
        rf = slu::rf_new(n, colptr, rowidx, columns, !given.is_null());
    }
    for (std::size_t k = 0; k < ops.size() && k < steps.size(); k++) {
        const Json& op = ops[k];
        const Json& step = steps[k];
        if (op.has("form")) {
            const double a = op.get("form").get("a").as_double();
            const Vec values = unhx(op.get("form").get("values"));
            const bool ok = by_blocks ? slu::bk_factor(bk, a, values, mass, has_mass)
                                      : slu::rf_factor(rf, a, values, mass, has_mass);
            const I64 work = by_blocks ? bk.ops : rf.ops;
            const I64 nnz = by_blocks ? bk.nnz : rf.nnz;
            const I64 repivots = by_blocks ? slu::bk_repivots(bk) : rf.repivots;
            const bool valid = by_blocks ? bk.valid : rf.valid;
            if (!(ok == step.get("ok").as_bool() && work == step.get("ops").as_int() &&
                  nnz == step.get("nnz").as_int() && repivots == step.get("repivots").as_int() &&
                  valid == step.get("valid").as_bool())) {
                return "factorisation " + std::to_string(k + 1) + ": ok " + std::to_string(ok) + ", ops " +
                       std::to_string(work) + ", nnz " + std::to_string(nnz) + ", repivots " +
                       std::to_string(repivots) + ", valid " + std::to_string(valid) + "; Python " +
                       json_text(step, 0);
            }
        } else if (step.has("x")) {
            std::fill(x.begin(), x.end(), 0.0);
            if (by_blocks) {
                slu::bk_solve(bk, unhx(op.get("solve")), x);
            } else {
                slu::rf_solve(rf, unhx(op.get("solve")), x);
            }
            if (!same_answer(x, step.get("x"))) return "solve " + std::to_string(k + 1);
        }
    }
    return std::nullopt;
}

void against_python(const std::string& dir) {
    const Json fx = parse_json(check::read_file(dir + "/sparselu.json"));
    std::map<long long, int> kinds;
    std::size_t k = 0;
    for (const Json& c : fx.get("matrices").arr()) {
        k += 1;
        const std::optional<std::string> why = replay_matrix(c, c.get("expect"));
        CHECK_MSG(!why, "matrix case " + std::to_string(k) + ": " + why.value_or(""));
        kinds[c.get("expect").get("made").get("kind").as_int()] += 1;
    }
    // Every choice was made.
    CHECK(kinds[slu::DENSE] > 0 && kinds[slu::SPARSE] > 0 && kinds[slu::WHOLE] > 0 && kinds[slu::BLOCKS] > 0);
    k = 0;
    for (const Json& c : fx.get("parts").arr()) {
        k += 1;
        const std::optional<std::string> why = replay_part(c, c.get("expect"));
        CHECK_MSG(!why, "single-LU case " + std::to_string(k) + " (" + c.get("lu").as_string() + "): " +
                            why.value_or(""));
    }
    std::printf("the sparse LUs against the Python package: %zu matrices, %zu single LUs\n",
                fx.get("matrices").size(), fx.get("parts").size());
}

// --- against a dense solve ----------------------------------------------------------------------------

/// Numbers made up the same on every machine (splitmix64).
struct Random {
    std::uint64_t state;
    std::uint64_t next() {
        std::uint64_t z = (state += 0x9e3779b97f4a7c15ull);
        z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ull;
        z = (z ^ (z >> 27)) * 0x94d049bb133111ebull;
        return z ^ (z >> 31);
    }
    /// In [0, 1).
    double uniform() { return static_cast<double>(next() >> 11) * 0x1p-53; }
    /// A whole number from lo to hi.
    int between(int lo, int hi) { return lo + static_cast<int>(next() % static_cast<std::uint64_t>(hi - lo + 1)); }
    double normal() {
        const double u = 1.0 - uniform();
        const double v = uniform();
        return std::sqrt(-2.0 * std::log(u)) * std::cos(6.283185307179586 * v);
    }
};

double norm2(const Vec& v) {
    double s = 0.0;
    for (double x : v) s += x * x;
    return std::sqrt(s);
}

void against_dense() {
    Random rng{4};
    int solved = 0;
    for (int trial = 1; trial <= 80; trial++) {
        const int n = rng.between(2, 80);
        const int kind = trial % 4;
        std::vector<I32> rows, cols;
        auto entry = [&](int r, int c) {
            rows.push_back(r);
            cols.push_back(c);
        };
        for (int j = 0; j < n; j++) {
            entry(j, j);
            if (kind == 0) {                        // random entries
                const int more = rng.between(0, 3);
                for (int e = 0; e < more; e++) entry(rng.between(0, n - 1), j);
            } else if (kind == 1) {                 // a chain feeding down, with a little back flow
                if (j + 1 < n) entry(j + 1, j);
                if (j > 0 && rng.uniform() < 0.3) entry(j - 1, j);
            } else if (kind == 3) {                 // chains side by side feeding each other, no way back:
                                                    // one long run of blocks of one state, many levels deep
                if (j + 4 < n) entry(j + 4, j);
                const int more = rng.between(0, 2);
                for (int e = 0; e < more && j + 1 < n; e++) entry(rng.between(j + 1, n - 1), j);
            } else {                                // blocks of cells one way round
                if (j % 5 != 4 && j + 1 < n) entry(j + 1, j);
                if (j % 5 != 0) entry(j - 1, j);
                if (j + 5 < n) entry(j + 5, j);
            }
        }
        const Pattern p(n, rows, cols);
        const std::size_t nnz = p.nnz();
        const std::size_t N = static_cast<std::size_t>(n);
        for (int mode : {slu::AUTO, slu::REFACTOR, slu::SPARSE_MODE}) {
            Vec J0(nnz);
            for (double& v : J0) v = rng.normal();
            SparseLUMatrix sw(n, p.colptr, p.rowval, J0, Vec(N, 1.0), false, mode, 0.15, false, true);
            if (sw.kind == slu::DENSE) continue;
            for (double a : {1e-3, 0.5, 30.0}) {
                Vec J(nnz);
                for (std::size_t q = 0; q < nnz; q++) J[q] = J0[q] * (1 + 0.5 * rng.normal());
                if (slu::form(sw, a, J, nullptr) != slu::OK) continue;
                Vec A(N * N, 0.0);
                for (std::size_t i = 0; i < N; i++) A[i * N + i] = 1.0;
                for (int jj = 0; jj < n; jj++)
                    for (I32 q = p.colptr[jj]; q < p.colptr[jj + 1]; q++)
                        A[static_cast<std::size_t>(p.rowval[q]) * N + static_cast<std::size_t>(jj)] -= a * J[q];
                Vec b(N);
                for (double& v : b) v = rng.normal();
                Vec x(N, 0.0);
                slu::solve(sw, b, x);
                Vec residual(N, 0.0);
                for (std::size_t i = 0; i < N; i++) {
                    double s = 0.0;
                    for (std::size_t j = 0; j < N; j++) s += A[i * N + j] * x[j];
                    residual[i] = s - b[i];
                }
                CHECK(norm2(residual) <= 1e-9 * (norm2(A) * norm2(x) + norm2(b)));
                solved += 1;
            }
        }
    }
    CHECK(solved > 200);
    std::printf("the sparse LUs against a dense solve: %d systems\n", solved);
}

}  // namespace

int main() {
    const char* dir = std::getenv("KOMPARTMENT_SPARSE_FIXTURES");
    if (dir == nullptr || *dir == 0 || !std::ifstream(std::string(dir) + "/sparselu.json")) {
        std::printf("KOMPARTMENT_SPARSE_FIXTURES not set: the sparse LUs' parity tests skipped\n");
    } else {
        // The fixtures are the other engines' numbers: compared with parity on.
        const bool was = kompartment::parity();
        kompartment::set_parity(true);
        against_python(dir);
        kompartment::set_parity(was);
    }
    // Against a dense solve both ways: as the other engines order the solve, and
    // the quicker order taken with parity off.
    for (bool exact : {true, false}) {
        const bool was = kompartment::parity();
        kompartment::set_parity(exact);
        against_dense();
        kompartment::set_parity(was);
    }
    return check::summary("test_sparselu");
}
