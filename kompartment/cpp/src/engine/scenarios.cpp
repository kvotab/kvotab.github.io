#include "engine/scenarios.hpp"

#include <algorithm>
#include <atomic>
#include <exception>
#include <memory>
#include <thread>

#include "engine/project.hpp"
#include "util/errors.hpp"

namespace kompartment {

std::vector<std::pair<std::string, Results>> run_scenarios(const Json& model, const std::optional<std::vector<std::string>>& wanted, int threads,
                                                           const Json& settings) {
    Json raw = model.copy();
    if (settings.is_object() && !settings.obj().empty()) {
        if (!raw.get("simulation").is_object()) raw.set("simulation", Json::object());
        for (const auto& [k, v] : settings.obj()) raw["simulation"].set(k, v);
    }
    const std::vector<std::string> names = wanted ? *wanted : Project(raw).scenarios;
    if (names.empty()) throw ArgumentError("This model has no scenarios: an index list marked as the scenario list, with indices.");
    // A Project copies what it is given: the model need not be copied for each. Runs side by
    // side are not split again.
    const bool side_by_side = threads > 1 && names.size() > 1;
    auto one = [&](const std::string& name) {
        Json r = raw.shallow();
        r.set("scenario", Json(name));
        RunOptions options;
        options.nest = !side_by_side;
        return run_project(std::make_shared<const Project>(r), nullptr, options);
    };
    std::vector<std::optional<Results>> done(names.size());
    if (!side_by_side) {
        for (std::size_t k = 0; k < names.size(); k++) done[k] = one(names[k]);
    } else {
        std::atomic<std::size_t> next{0};
        const std::size_t workers = std::min(static_cast<std::size_t>(threads), names.size());
        std::vector<std::exception_ptr> failed(workers);
        std::vector<std::thread> pool;
        for (std::size_t w = 0; w < workers; w++)
            pool.emplace_back([&, w] {
                try {
                    while (true) {
                        const std::size_t k = next.fetch_add(1);
                        if (k >= names.size()) break;
                        done[k] = one(names[k]);
                    }
                } catch (...) {
                    failed[w] = std::current_exception();
                }
            });
        for (std::thread& t : pool) t.join();
        for (const std::exception_ptr& e : failed)
            if (e) std::rethrow_exception(e);
    }
    std::vector<std::pair<std::string, Results>> out;
    out.reserve(names.size());
    for (std::size_t k = 0; k < names.size(); k++) out.emplace_back(names[k], std::move(*done[k]));
    return out;
}

}  // namespace kompartment
