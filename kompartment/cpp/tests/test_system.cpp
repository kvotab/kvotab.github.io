// A built system against the Julia engine's, with parity on
// (tools/system_fixtures.jl writes tests/fixtures/system.json): the initial
// state, the slots that never move, and at a few instants and states the
// derivative and every algebraic slot, to the bit. Then, with parity off, the
// derivative from the merged matrix against the one summed term by term.

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>

#include "check.hpp"
#include "engine/system.hpp"
#include "util/json.hpp"
#include "util/parity.hpp"

using namespace kompartment;

static std::string bits(double x) {
    if (std::isnan(x)) return "nan";
    std::uint64_t u;
    std::memcpy(&u, &x, 8);
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(u));
    return buf;
}
static std::string fnv(const std::string& text) {
    std::uint64_t h = 0xcbf29ce484222325ULL;
    for (unsigned char b : text) h = (h ^ b) * 0x100000001b3ULL;
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(h));
    return buf;
}
static std::string nums(const std::vector<double>& v) {
    std::string s;
    for (double x : v) {
        if (!s.empty()) s += ",";
        s += bits(x);
    }
    return s;
}

// The states the derivative is asked at: the initial one, and two made from it.
static std::vector<std::vector<double>> states(const std::vector<double>& y0) {
    std::size_t n = y0.size();
    std::vector<std::vector<double>> out(3, y0);
    for (std::size_t i = 1; i <= n; i++) {
        out[1][i - 1] = y0[i - 1] * (1.0 + 0.25 * static_cast<double>((i * 7) % 5)) + 0.5 * static_cast<double>((i * 3) % 4);
        out[2][i - 1] = std::fabs(y0[i - 1]) * 0.3 + 1e-3 * static_cast<double>(i);
    }
    return out;
}

int main() {
    Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/system.json"));
    const char* dumps = std::getenv("KOMPARTMENT_FIXTURE_DUMPS");
    std::vector<std::string> skipped;
    for (const Json& row : fx.get("cases").arr()) {
        const std::string& name = row.get("name").as_string();
        Json model = row.has("example")
                         ? parse_json(check::read_file(std::string(KOMPARTMENT_REPO) + "/examples/" + row.get("example").as_string() + ".json"))
                         : row.get("model");
        try {
            auto project = std::make_shared<const Project>(model);
            set_parity(true);
            System sys(project);
            std::map<std::string, std::string> out;
            std::vector<double> y0 = sys.initial_state();
            out["y0"] = nums(y0);
            {
                // (Only the slots that never move: the others hold whatever was last worked out.)
                std::vector<double> still;
                for (int i = 0; i < sys.nalg; i++)
                    if (sys.builder->slot_class[static_cast<std::size_t>(i)] == 0) still.push_back(sys.X[static_cast<std::size_t>(i)]);
                out["invariant"] = nums(still);
            }
            sys.prime_recorders(sys.start_time, y0);
            double t0 = sys.start_time, t1 = sys.end_time;
            double times[3] = {t0, t0 + 0.37 * (t1 - t0), t1};
            std::vector<std::vector<double>> ys = states(y0);
            std::vector<std::vector<double>> exact;
            for (int k = 0; k < 3; k++) {
                std::vector<double> X = sys.evaluate_algebraic(times[k], ys[static_cast<std::size_t>(k)].data());
                std::vector<double> dy = sys.dydt(times[k], ys[static_cast<std::size_t>(k)]);
                out["X" + std::to_string(k + 1)] = nums(X);
                out["dy" + std::to_string(k + 1)] = nums(dy);
                exact.push_back(dy);
            }
            if (dumps && *dumps) {
                std::ofstream f(std::string(dumps) + "/" + name + ".system.cpp.txt");
                for (auto [k, v] : out) {
                    for (char& ch : v)
                        if (ch == ',') ch = '\n';
                    f << "## " << k << "\n" << v << "\n";
                }
            }
            for (const auto& [key, hash] : row.get("values").obj()) CHECK_MSG(fnv(out[key]) == hash.as_string(), name + ": " + key + " differs");

            // The quickest way to the same derivative: the terms merged, the products fused.
            set_parity(false);
            System fast(project);
            fast.prime_recorders(fast.start_time, y0);
            System copy = fast.clone();
            for (int k = 0; k < 3; k++) {
                std::vector<double> dy = fast.dydt(times[k], ys[static_cast<std::size_t>(k)]);
                std::vector<double> again = copy.dydt(times[k], ys[static_cast<std::size_t>(k)]);
                bool close = true, same = true;
                double scale = 0;
                for (double v : exact[static_cast<std::size_t>(k)])
                    if (std::isfinite(v)) scale = std::max(scale, std::fabs(v));
                for (std::size_t i = 0; i < dy.size(); i++) {
                    double want = exact[static_cast<std::size_t>(k)][i];
                    if (std::isnan(want) || std::isinf(want)) continue;
                    if (!(std::fabs(dy[i] - want) <= 1e-9 * std::max(scale, 1e-300))) close = false;
                    if (!check::same_bits(dy[i], again[i])) same = false;
                }
                CHECK_MSG(close, name + ": the merged derivative " + std::to_string(k + 1) + " is not the summed one");
                CHECK_MSG(same, name + ": a copy's derivative " + std::to_string(k + 1) + " differs from its system's");
            }
        } catch (const NotSupported&) {
            skipped.push_back(name);
        } catch (const std::exception& e) {
            CHECK_MSG(false, name + " threw: " + e.what());
        }
    }
    set_parity(false);
    if (!skipped.empty()) {
        std::string names;
        for (const auto& s : skipped) names += (names.empty() ? "" : ", ") + s;
        std::printf("not built here yet (%zu): %s\n", skipped.size(), names.c_str());
    }
    return check::summary("test_system");
}
