#include "model/decay.hpp"

#include <algorithm>
#include <cmath>
#include <unordered_map>
#include <unordered_set>

#include "model/names.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

const std::unordered_map<std::string_view, int>& row_index() {
    static const std::unordered_map<std::string_view, int> index = [] {
        std::unordered_map<std::string_view, int> m;
        m.reserve(static_cast<std::size_t>(icrp107_data::ROW_COUNT) * 2);
        for (int i = 0; i < icrp107_data::ROW_COUNT; i++) m.emplace(icrp107_data::ROWS[i].name, i);
        return m;
    }();
    return index;
}

const icrp107_data::Row* row_of(std::string_view name) {
    auto it = row_index().find(name);
    return it == row_index().end() ? nullptr : &icrp107_data::ROWS[it->second];
}

// A nuclide's shares among the kept ones, in the order they are first reached.
using Shares = std::vector<std::pair<std::string, double>>;

void add_share(Shares& out, const std::string& target, double amount) {
    for (auto& [name, share] : out)
        if (name == target) {
            share += amount;
            return;
        }
    out.emplace_back(target, amount);
}

const Shares& distribution(const std::string& name, const std::unordered_set<std::string>& keep,
                           std::unordered_map<std::string, Shares>& memo, double ceiling) {
    auto hit = memo.find(name);
    if (hit != memo.end()) return hit->second;
    memo.emplace(name, Shares{});   // before the walk, so a cycle cannot recurse forever
    const icrp107_data::Row* row = row_of(name);
    if (!row) return memo[name];
    Shares out;
    for (int k = 0; k < row->count; k++) {
        const icrp107_data::Progeny& p = icrp107_data::PROGENY[row->first + k];
        std::string daughter = p.name;
        if (keep.count(daughter)) {
            add_share(out, daughter, p.branching);
            continue;
        }
        std::optional<double> half = half_life(daughter);
        if (!half || std::isinf(*half)) continue;   // the activity leaves the chain
        if (*half > ceiling) continue;               // a sink within any assessment's span
        // (A copy: the walk below may add to the memo, which moves what a reference points at.)
        Shares inner = distribution(daughter, keep, memo, ceiling);
        for (const auto& [target, share] : inner) add_share(out, target, p.branching * share);
    }
    // What a cycle read of this nuclide while it was being worked out was the empty list
    // set above; the entry is replaced with the whole of it now.
    return memo[name] = std::move(out);
}

}  // namespace

const std::vector<std::string>& known_nuclides() {
    static const std::vector<std::string> names = [] {
        std::vector<std::string> v;
        v.reserve(static_cast<std::size_t>(icrp107_data::ROW_COUNT));
        for (int i = 0; i < icrp107_data::ROW_COUNT; i++) v.emplace_back(icrp107_data::ROWS[i].name);
        return v;
    }();
    return names;
}

bool is_known_nuclide(std::string_view name) { return row_of(name) != nullptr; }

std::optional<double> half_life(std::string_view name) {
    const icrp107_data::Row* row = row_of(name);
    if (!row) return std::nullopt;
    return row->half_life < 0 ? std::numeric_limits<double>::infinity() : row->half_life;
}

bool means_stable(const Json& v) {
    if (v.is_float()) return std::isinf(v.as_double());
    if (v.is_string()) {
        std::string s = lowercase(js_trim(v.as_string()));
        return s == "stable" || s == "inf" || s == "infinity";
    }
    return false;
}

std::optional<std::string> element_of(std::string_view nuclide) {
    std::string_view s = js_trim(nuclide);
    auto letter = [](char c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); };
    // One to three letters, then the end, a hyphen, white space or a digit. As the pattern
    // is matched: the most letters first, fewer when what follows them does not fit.
    std::size_t most = 0;
    while (most < s.size() && most < 3 && letter(s[most])) most++;
    for (std::size_t k = most; k >= 1; k--) {
        bool fits = k == s.size();
        if (!fits) {
            unsigned char next = static_cast<unsigned char>(s[k]);
            fits = next == '-' || (next >= '0' && next <= '9') || next == ' ' || next == '\t' || next == '\n' ||
                   next == '\r' || next == '\f' || next == '\v';
        }
        if (fits) {
            std::string out(s.substr(0, k));
            out[0] = static_cast<char>(std::toupper(static_cast<unsigned char>(out[0])));
            for (std::size_t i = 1; i < out.size(); i++) out[i] = static_cast<char>(std::tolower(static_cast<unsigned char>(out[i])));
            return out;
        }
    }
    return std::nullopt;
}

std::vector<std::tuple<std::string, std::string, double>> default_chains(const std::vector<std::string>& nuclides,
                                                                         double ceiling, double min_branching) {
    std::unordered_set<std::string> keep;
    for (const auto& n : nuclides)
        if (is_known_nuclide(n)) keep.insert(n);
    std::unordered_map<std::string, Shares> memo;
    std::vector<std::tuple<std::string, std::string, double>> pairs;
    for (const std::string& name : known_nuclides()) {   // the table's order, whatever order was asked for
        if (!keep.count(name)) continue;
        Shares shares = distribution(name, keep, memo, ceiling);
        for (const auto& [daughter, branching] : shares) {
            if (branching < min_branching) continue;
            pairs.emplace_back(name, daughter, branching);
        }
    }
    std::stable_sort(pairs.begin(), pairs.end(), [](const auto& a, const auto& b) {   // stable, as the application's sort is
        auto ka = locale_key(std::get<0>(a)), kb = locale_key(std::get<0>(b));
        if (ka != kb) return ka < kb;
        return -std::get<2>(a) < -std::get<2>(b);
    });
    return pairs;
}

}  // namespace kompartment
