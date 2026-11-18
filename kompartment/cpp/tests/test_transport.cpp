// Transport sub-systems written out as the chains they stand for, against the
// Julia engine's (tools/transport_fixtures.jl writes
// tests/fixtures/transport.json): every bundled example and models made to
// reach each branch and each refusal of the expansion, each as the project it
// is expanded into -- by a hash of its text -- or the message it is refused
// with, the kind of error and the block it names; and the project as a file
// holds it, before and after.

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>

#include "check.hpp"
#include "engine/builder.hpp"
#include "engine/project.hpp"
#include "engine/transport.hpp"
#include "util/json.hpp"

using namespace kompartment;

static std::string bits(double x) {
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

static Json strings(const std::vector<std::string>& v) { return Json::array(v); }
static Json opt(const std::optional<std::string>& s) { return s ? Json(*s) : Json(); }
static Json sorted(const std::unordered_map<std::string, std::string>& map) {
    std::vector<std::string> keys;
    for (const auto& [k, v] : map) keys.push_back(k);
    std::sort(keys.begin(), keys.end());
    Json out = Json::object();
    for (const auto& k : keys) out.set(k, Json(map.at(k)));
    return out;
}

static Json dump(const Project& p) {
    Json blocks = Json::object(), off = Json::object();
    for (const auto& c : block_collections()) {
        blocks.set(c, Json(JArray(p.blocks_of(c))));
        auto it = p.switched_off.find(c);
        if (it != p.switched_off.end()) {
            Json names = Json::array();
            for (const Json& b : it->second) names.push(b.get("qname"));
            off.set(c, names);
        }
    }
    std::vector<std::string> disabled(p.disabled.begin(), p.disabled.end());
    std::sort(disabled.begin(), disabled.end());
    DecayModel dm = p.decay_model();
    Json lambdas = Json::array(), parents = Json::array(), grid = Json::array();
    for (double x : dm.lambdas) lambdas.push(Json(bits(x)));
    for (const auto& ps : dm.parents) {
        Json row = Json::array();
        for (const auto& q : ps) row.push(Json::array({Json(q.index), Json(bits(q.lambda)), Json(bits(q.ratio))}));
        parents.push(row);
    }
    for (double t : p.time_grid()) grid.push(Json(bits(t)));
    return Json::object({
        {"name", p.name}, {"description", p.description}, {"simulation", p.simulation},
        {"output_mode", Json(p.output_mode)}, {"decay_unit", Json(p.decay_unit)},
        {"index_lists", p.index_lists}, {"chains", p.chains},
        {"material_list", opt(p.material_list_name)}, {"nuclide_list", opt(p.nuclide_list_name)},
        {"scenario", opt(p.scenario)}, {"scenarios", strings(p.scenarios)},
        {"blocks", blocks}, {"switched_off", off}, {"disabled", strings(disabled)},
        {"implicitly_disabled", sorted(p.implicitly_disabled)}, {"off_reasons", sorted(p.off_reasons)},
        {"disabled_systems", strings(p.disabled_systems)},
        {"systems", strings(p.systems)}, {"transports", strings(p.transports)},
        {"derived_lists", strings(std::vector<std::string>(p.derived_lists.begin(), p.derived_lists.end()))},
        {"decay", Json::object({{"names", strings(dm.names)}, {"lambdas", lambdas}, {"parents", parents}})},
        {"grid", grid},
        {"layout", p.layout}, {"shapes", p.shapes}, {"derived", p.derived}, {"view", p.view},
    });
}

int main() {
    Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/transport.json"));
    const char* dumps = std::getenv("KOMPARTMENT_FIXTURE_DUMPS");
    for (const Json& row : fx.get("cases").arr()) {
        const std::string& name = row.get("name").as_string();
        Json model = row.has("example")
                         ? parse_json(check::read_file(std::string(KOMPARTMENT_REPO) + "/examples/" + row.get("example").as_string() + ".json"))
                         : row.get("model");
        std::string there = row.has("error") ? row.get("kind").as_string() + ": " + row.get("error").as_string() : "expanded";
        try {
            Project p(model);
            std::string before = json_text(dump(p), 0);
            CHECK_MSG(fnv(json_text(project_to_json(p), 0)) == row.get("json").as_string(), name + ": the project as a file holds it differs");
            try {
                std::shared_ptr<const Project> x = expand_transports(p);
                CHECK_MSG(json_text(dump(p), 0) == before, name + ": the project handed in is left as it was");
                Json d = dump(*x);
                if (dumps && *dumps) std::ofstream(std::string(dumps) + "/" + name + ".cpp.json") << json_text(d, 1);
                if (row.has("hash")) {
                    CHECK_MSG(fnv(json_text(d, 0)) == row.get("hash").as_string(), name + ": the expanded project differs");
                    CHECK_MSG(fnv(json_text(project_to_json(*x), 0)) == row.get("expanded_json").as_string(),
                              name + ": the expanded project as a file holds it differs");
                } else {
                    CHECK_MSG(false, name + " is refused there: " + there);
                }
            } catch (const BuildError& e) {
                CHECK_MSG(there == std::string("BuildError: ") + e.what(), name + " is refused with: BuildError: " + e.what() + "\n   there: " + there);
                if (row.has("error") && row.get("kind") == "BuildError")
                    CHECK_MSG(opt(e.block_name) == row.get("block"), name + ": the refusal names " + e.block_name.value_or("no block"));
            } catch (const ValidationError& e) {
                CHECK_MSG(there == std::string("ValidationError: ") + e.what(),
                          name + " is refused with: ValidationError: " + e.what() + "\n   there: " + there);
            }
        } catch (const std::exception& e) {
            CHECK_MSG(false, name + " threw: " + e.what());
        }
    }
    return check::summary("test_transport");
}
