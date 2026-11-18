#include "engine/switchtimes.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

#include "engine/farfield_domain.hpp"
#include "lang/functions.hpp"
#include "lang/parse.hpp"
#include "model/indexlists.hpp"
#include "model/names.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

bool is_plain_number(std::string_view s) {
    std::size_t k = 0, n = s.size(), whole = 0, frac = 0;
    if (k < n && (s[k] == '+' || s[k] == '-')) k++;
    while (k < n && s[k] >= '0' && s[k] <= '9') { k++; whole++; }
    if (k < n && s[k] == '.') {
        k++;
        while (k < n && s[k] >= '0' && s[k] <= '9') { k++; frac++; }
    }
    if (whole == 0 && frac == 0) return false;
    if (k < n && (s[k] == 'e' || s[k] == 'E')) {
        k++;
        if (k < n && (s[k] == '+' || s[k] == '-')) k++;
        std::size_t ex = 0;
        while (k < n && s[k] >= '0' && s[k] <= '9') { k++; ex++; }
        if (ex == 0) return false;
    }
    return k == n;
}

bool finite_constant(const TNode& t) {
    if (t.kind != TNode::Kind::Leaf) return false;
    const TLeaf& l = as_leaf(t);
    if (l.leaf != LeafKind::K) return false;
    if (!l.values) return std::isfinite(l.value);
    for (double v : *l.values)
        if (!std::isfinite(v)) return false;
    return true;
}

std::vector<std::string> scenario_dims(const Project& project) {
    const JArray& lists = project.index_lists.arr();
    const Json* root = nullptr;
    for (const Json& l : lists)
        if (js_truthy(l.get("for_scenarios"))) { root = &l; break; }
    std::vector<std::string> out;
    if (!root) return out;
    for (const Json& l : lists) {
        Json at = l.get("name");
        std::size_t i = 0;
        while (js_truthy(at) && i <= lists.size()) {
            if (at == root->get("name")) {
                out.push_back(js_str(l.get("name")));
                break;
            }
            at = parent_list_name(find_list(project.index_lists, at));
            i++;
        }
    }
    return out;
}

std::optional<std::string> active_scenario(const Project& project) {
    const Json* lst = nullptr;
    for (const Json& l : project.index_lists.arr())
        if (js_truthy(l.get("for_scenarios"))) { lst = &l; break; }
    std::vector<std::string> names;
    if (lst && lst->get("indices").is_array())
        for (const Json& i : lst->get("indices").arr()) {
            if (i.is_string()) names.push_back(i.as_string());
            else if (js_truthy(i.get("name")) && !(i.get("enabled").is_bool() && !i.get("enabled").as_bool())) names.push_back(js_str(i.get("name")));
        }
    if (names.empty()) return std::nullopt;
    if (project.scenario && std::find(names.begin(), names.end(), *project.scenario) != names.end()) return project.scenario;
    return names[0];
}

Json constant_entry(const Project& project, const Json& block, const char* key, const std::vector<std::string>& dims) {
    if (dims.empty()) return block.get(key);
    std::vector<std::string> scen = scenario_dims(project);
    for (const auto& d : dims)
        if (std::find(scen.begin(), scen.end(), d) == scen.end()) return Json();
    std::optional<std::string> active = active_scenario(project);
    if (block.get("entries").is_array())
        for (const Json& e : block.get("entries").arr()) {
            if (!(e.is_object() && e.has(key))) continue;
            bool all = true;
            if (e.get("index").is_object())
                for (const auto& [k, v] : e.get("index").obj())
                    if (!(active && v == *active)) all = false;
            if (all) return e.get(key);
        }
    return block.get(key);
}

}  // namespace

double evaluate_tree(const TNode& t, double T, double T0, double T1) {
    switch (t.kind) {
        case TNode::Kind::Leaf: {
            const TLeaf& l = as_leaf(t);
            if (l.leaf == LeafKind::K) return l.value;
            if (l.leaf == LeafKind::T) return T;
            if (l.leaf == LeafKind::T0) return T0;
            if (l.leaf == LeafKind::T1) return T1;
            throw std::runtime_error("a leaf has no value here");
        }
        case TNode::Kind::Neg: return -evaluate_tree(*as_neg(t).a, T, T0, T1);
        case TNode::Kind::Bin: {
            const TBin& b = as_bin(t);
            double x = evaluate_tree(*b.a, T, T0, T1);
            double y = evaluate_tree(*b.b, T, T0, T1);
            if (b.op == BinOp::Pow) return finite_constant(*b.b) ? cpow(x, y) : kf_jspow(x, y);
            return apply_binary(b.op, x, y);
        }
        case TNode::Kind::Cond: {
            const TCond& c = as_tcond(t);
            return evaluate_tree(*c.test, T, T0, T1) != 0 ? evaluate_tree(*c.a, T, T0, T1) : evaluate_tree(*c.b, T, T0, T1);
        }
        case TNode::Kind::Call: {
            const TCall& c = as_tcall(t);
            std::vector<double> args;
            for (const auto& a : c.args) args.push_back(evaluate_tree(*a, T, T0, T1));
            if (c.fn == Fn::Power) return finite_constant(*c.args[1]) ? cpow(args[0], args[1]) : kf_jspow(args[0], args[1]);
            return call_value(c.fn, args.data(), args.size());
        }
        default: throw std::runtime_error("cannot evaluate this node");
    }
}

std::optional<double> constant_value(const Project& project, const Json& block, const std::string& kind, const std::set<std::string>& seen) {
    if (block.is_null()) return std::nullopt;
    std::vector<std::string> dims = strings_of(block.get("index_lists"));
    if (kind == "parameter") {
        Json raw = constant_entry(project, block, "value", dims);
        // `Number()` of a value that is there, its text by JavaScript's grammar; a value that is
        // not -- or an index other than the scenarios' -- is not known before the run.
        double v = raw.is_null() ? std::numeric_limits<double>::quiet_NaN() : js_number_of(raw);
        return std::isfinite(v) ? std::optional<double>(v) : std::nullopt;
    }
    if (kind != "expression") return std::nullopt;
    Json text = constant_entry(project, block, "equation", dims);
    if (text.is_null()) return std::nullopt;
    ENodePtr ast;
    try {
        ast = parse_equation(std::string_view(js_str(text)));
    } catch (const EquationParseError&) {
        return std::nullopt;
    }
    std::string system = js_truthy(block.get("system")) ? js_str(block.get("system")) : "";
    std::string own = qualified_name(block);
    auto find = [&](const std::string& q) -> std::pair<const Json*, const char*> {
        for (const Json& b : project.blocks_of("parameters"))
            if (qualified_name(b) == q) return {&b, "parameter"};
        for (const Json& b : project.blocks_of("expressions"))
            if (qualified_name(b) == q) return {&b, "expression"};
        return {nullptr, ""};
    };
    bool ok = true;
    RefResolver ref = [&](const ERef& r) -> TNodePtr {
        if (!ok) return k_leaf(0.0);
        if (!r.indices.empty() || r.by_list) {
            ok = false;
            return k_leaf(0.0);
        }
        auto q = resolve_reference(r.name, system, [&](const std::string& n) { return find(n).first != nullptr; });
        if (!q || *q == own || seen.count(*q)) {
            ok = false;
            return k_leaf(0.0);
        }
        auto target = find(*q);
        std::set<std::string> deeper = seen;
        deeper.insert(own);
        std::optional<double> v = constant_value(project, *target.first, target.second, deeper);
        if (!v) {
            ok = false;
            return k_leaf(0.0);
        }
        return k_leaf(*v);
    };
    TNodePtr tree;
    try {
        tree = resolve_tree(*ast, ref);
    } catch (const std::exception&) {
        return std::nullopt;
    }
    if (!ok) return std::nullopt;
    double start = project.start_time(), end = project.end_time();
    double v;
    try {
        v = evaluate_tree(*tree, start, start, end);
    } catch (const std::exception&) {
        return std::nullopt;
    }
    return std::isfinite(v) ? std::optional<double>(v) : std::nullopt;
}

std::optional<double> resolve_switch_time(const Project& project, const Json& entry) {
    if (entry.is_number()) {
        double v = entry.as_double();
        return std::isfinite(v) ? std::optional<double>(v) : std::nullopt;
    }
    std::string name(js_trim(entry.is_null() ? std::string() : js_str(entry)));
    if (name.empty()) return std::nullopt;
    if (is_plain_number(name)) return std::strtod(name.c_str(), nullptr);
    for (const auto& [collection, kind] : {std::pair<const char*, const char*>{"parameters", "parameter"}, {"expressions", "expression"}})
        for (const Json& b : project.blocks_of(collection))
            if (qualified_name(b) == name) {
                std::optional<double> v = constant_value(project, b, kind);
                return (v && std::isfinite(*v)) ? v : std::nullopt;
            }
    return std::nullopt;
}

std::vector<double> switch_times(const Project& project) {
    double start = project.start_time(), end = project.end_time();
    std::set<double> out;
    auto consider = [&](const std::optional<double>& v) {
        if (v && *v > start && *v < end) out.insert(*v);
    };
    const Json& declared = project.simulation.get("switch_times");
    if (declared.is_array())
        for (const Json& entry : declared.arr()) consider(resolve_switch_time(project, entry));
    for (const Json& w : project.blocks_of("waste_packages")) {
        const Json& failure = w.get("failure");
        std::vector<std::string> keys;
        if (failure == "at") keys = {"fail_at"};
        else if (failure == "uniform") keys = {"fail_from", "fail_to"};
        else if (failure == "exponential" || failure == "weibull") keys = {"fail_start"};
        for (const auto& key : keys) consider(resolve_switch_time(project, w.get(key)));
    }
    for (const Json& d : project.blocks_of("events")) {
        // One a trigger sets off has no corner known before the run.
        const Json& timing = d.get("timing");
        std::vector<std::string> keys;
        if (timing == "poisson") keys = {"from", "until"};
        else if (!(timing == "trigger")) keys = {"at"};
        for (const auto& key : keys) consider(resolve_switch_time(project, d.get(key)));
    }
    return std::vector<double>(out.begin(), out.end());
}

}  // namespace kompartment
