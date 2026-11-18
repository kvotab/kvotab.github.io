// A run that meets a value that is not a number, against the Julia engine's, with parity
// on (tools/nonfinite_fixtures.jl writes tests/fixtures/nonfinite.json): each model run
// on each solver, and what the error says -- its message, the block it names, the
// solver's own message and the hint -- word for word, or that the run went; the warnings
// at the start of a run; and equations written back as text.

#include <cstdlib>
#include <fstream>
#include <string>
#include <vector>

#include "check.hpp"
#include "engine/nonfinite.hpp"
#include "engine/runner.hpp"
#include "lang/parse.hpp"
#include "util/json.hpp"
#include "util/jsnum.hpp"
#include "util/parity.hpp"

using namespace kompartment;

namespace {

Json said(const std::optional<std::string>& s) { return s ? Json(*s) : Json(); }

std::string shown(const Json& v) { return v.is_null() ? "(none)" : js_text(v); }

void same(const std::string& what, const Json& here, const Json& there) {
    CHECK_MSG(here == there, what + "\n   here:  " + shown(here) + "\n   there: " + shown(there));
}

}  // namespace

int main() {
    Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/nonfinite.json"));
    const char* dumps = std::getenv("KOMPARTMENT_FIXTURE_DUMPS");
    std::string all;
    std::vector<std::string> skipped;
    set_parity(true);
    for (const Json& c : fx.get("cases").arr()) {
        const std::string& name = c.get("name").as_string();
        const Json& model = c.get("model");
        for (const char* solver : {"ndf", "ros23", "dp45"}) {
            if (!c.has(solver)) continue;
            const Json& want = c.get(solver);
            const std::string at = name + " (" + solver + ")";
            Json m = model.copy();
            m["simulation"].set("solver", Json(solver));
            try {
                auto project = std::make_shared<const Project>(m);
                auto system = std::make_shared<System>(project);
                Results res = run_project(project, system);
                all += at + ": ran\n";
                if (want.has("ran")) CHECK_MSG(static_cast<long long>(res.t.size()) == want.get("ran").as_int(), at + ": the output times");
                else CHECK_MSG(false, at + " runs here, not there: " + shown(want.get("message")) + shown(want.get("refused")));
            } catch (const NotSupported&) {
                skipped.push_back(at);
            } catch (const SolverError& e) {
                all += at + ": " + e.message + "\n   block " + shown(said(e.block_name)) + "\n   solver " + shown(said(e.solver_message)) + "\n   hint " +
                       shown(said(e.hint)) + "\n";
                if (!want.has("message")) {
                    CHECK_MSG(false, at + " fails here, not there: " + e.message);
                    continue;
                }
                same(at + ": the kind", Json(e.kind), want.get("kind"));
                same(at + ": the message", Json(e.message), want.get("message"));
                same(at + ": the block", said(e.block_name), want.get("block"));
                same(at + ": the solver's message", said(e.solver_message), want.get("solver_message"));
                same(at + ": the hint", said(e.hint), want.get("hint"));
            } catch (const std::exception& e) {
                all += at + ": refused: " + e.what() + "\n";
                if (want.has("refused")) same(at + ": refused", Json(e.what()), want.get("refused"));
                else CHECK_MSG(false, at + " is refused here, not there: " + e.what());
            }
        }
        // The warnings at the start of a run.
        const Json& warned = c.get("warnings");
        try {
            auto project = std::make_shared<const Project>(model);
            System sys(project, false);
            const double t0 = project->simulation.get("start_time").as_double();
            std::vector<double> y = sys.initial_state();
            sys.prime_recorders(t0, y);
            sys.evaluate_algebraic(t0, y.data());
            std::vector<Json> got = start_warnings(sys, t0, y);
            for (const Json& w : got) all += name + ": warns " + js_text(w.get("block")) + " " + js_text(w.get("stops")) + " " + w.get("message").as_string() + "\n";
            if (!warned.is_array()) {
                CHECK_MSG(false, name + ": warns here, refused there: " + shown(warned.get("refused")));
                continue;
            }
            CHECK_MSG(got.size() == warned.size(), name + ": " + std::to_string(got.size()) + " warnings, there " + std::to_string(warned.size()));
            for (std::size_t i = 0; i < got.size() && i < warned.size(); i++) {
                same(name + ": the warning's block", got[i].get("block"), warned[i].get("block"));
                same(name + ": the warning", got[i].get("message"), warned[i].get("message"));
                same(name + ": whether it stops a run", got[i].get("stops"), warned[i].get("stops"));
            }
        } catch (const NotSupported&) {
        } catch (const std::exception& e) {
            all += name + ": warnings refused: " + e.what() + "\n";
            if (warned.is_object()) same(name + ": the warnings refused", Json(e.what()), warned.get("refused"));
            else CHECK_MSG(false, name + ": the warnings are refused here: " + e.what());
        }
    }
    set_parity(false);

    // Equations written back.
    for (const Json& row : fx.get("equations").arr()) {
        const std::string& eq = row[0].as_string();
        try {
            std::string text = equation_text(*parse_equation(std::string_view(eq)));
            all += eq + " -> " + text + "\n";
            if (row[1].is_string()) same("'" + eq + "' written back", Json(text), row[1]);
            else CHECK_MSG(false, "'" + eq + "' is read here, refused there");
        } catch (const std::exception& e) {
            if (row[1].is_object()) same("'" + eq + "' refused", Json(e.what()), row[1].get("refused"));
            else CHECK_MSG(false, "'" + eq + "' is refused here: " + e.what());
        }
    }
    if (dumps && *dumps) std::ofstream(std::string(dumps) + "/nonfinite.cpp.txt") << all;
    if (!skipped.empty()) {
        std::string s;
        for (const auto& x : skipped) s += (s.empty() ? "" : ", ") + x;
        std::printf("not built here yet (%zu): %s\n", skipped.size(), s.c_str());
    }
    return check::summary("test_nonfinite");
}
