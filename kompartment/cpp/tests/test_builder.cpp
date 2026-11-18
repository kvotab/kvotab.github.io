// The builder against the Julia engine's (tools/builder_fixtures.jl writes
// tests/fixtures/builder.json): each model built and written out section by
// section -- the layout, the parameters, the tables, each pass's statements
// as merged, the derivative's phases, the jumps, the events -- and each
// section compared by a hash of its text; or the message a model is refused
// with.

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>

#include "check.hpp"
#include "engine/builder.hpp"
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
template <class V>
static std::string ints(const V& v) {
    std::string s;
    for (auto x : v) {
        if (!s.empty()) s += ",";
        s += std::to_string(static_cast<long long>(x));
    }
    return s;
}
static std::string nums(const std::vector<double>& v) {
    std::string s;
    for (double x : v) {
        if (!s.empty()) s += ",";
        s += bits(x);
    }
    return s;
}
static std::string joined(const std::vector<std::string>& v, const char* sep) {
    std::string s;
    for (std::size_t i = 0; i < v.size(); i++) s += (i ? sep : "") + v[i];
    return s;
}
static const char* tf(bool b) { return b ? "true" : "false"; }

static std::string leaf_text(const TLeaf& l) {
    LeafKind k = l.leaf;
    if (k == LeafKind::T || k == LeafKind::T0 || k == LeafKind::T1) return leaf_kind_name(k);
    if (k == LeafKind::K) return l.values ? "K[" + nums(*l.values) + "]" : "K(" + bits(l.value) + ")";
    return std::string(leaf_kind_name(k)) + (l.indices ? "[" + ints(*l.indices) + "]" : "(" + std::to_string(l.index) + ")");
}
static std::string tree_text(const TNode& t) {
    switch (t.kind) {
        case TNode::Kind::Leaf: return leaf_text(as_leaf(t));
        case TNode::Kind::Neg: return "neg(" + tree_text(*as_neg(t).a) + ")";
        case TNode::Kind::Bin: return std::string("(") + bin_op_name(as_bin(t).op) + " " + tree_text(*as_bin(t).a) + " " + tree_text(*as_bin(t).b) + ")";
        case TNode::Kind::Cond: return "(? " + tree_text(*as_tcond(t).test) + " " + tree_text(*as_tcond(t).a) + " " + tree_text(*as_tcond(t).b) + ")";
        case TNode::Kind::Call: {
            std::string s = as_tcall(t).key + "(";
            for (std::size_t i = 0; i < as_tcall(t).args.size(); i++) s += (i ? "," : "") + tree_text(*as_tcall(t).args[i]);
            return s + ")";
        }
        case TNode::Kind::Tab: return "tab(" + leaf_text(*as_tab(t).leaf) + "," + tree_text(*as_tab(t).arg) + ")";
    }
    return "";
}
static std::string stmt_text(const Stmt& s) {
    if (s.special) {
        const Special& sp = *s.special;
        if (sp.kind == Special::Kind::FarfieldRelease) return "special farfield " + std::to_string(sp.index) + " " + tf(sp.laplace);
        const char* kind = sp.kind == Special::Kind::MinMax ? "min_max" : sp.kind == Special::Kind::RunningMean ? "running_mean"
                           : sp.kind == Special::Kind::Snapshot ? "snapshot" : "delay";
        return std::string("special ") + kind + " out=" + ints(sp.out) + " mem=" + ints(sp.mem) + " arg=" + ints(sp.arg) + " state=" + ints(sp.state);
    }
    return std::string(s.array == Stmt::Array::Y0 ? "y0" : "X") + " " + (s.multiply ? "*=" : "=") + " w=" + std::to_string(s.width) + " out=" +
           ints(s.out_indices()) + " :: " + tree_text(*s.tree);
}
static std::string stmts_text(const std::vector<std::shared_ptr<Stmt>>& v) {
    std::string out;
    for (std::size_t i = 0; i < v.size(); i++) out += (i ? "\n" : "") + stmt_text(*v[i]);
    return out;
}

static std::map<std::string, std::string> sections(const Builder& b) {
    std::map<std::string, std::string> out;
    std::string io = "nstate=" + std::to_string(b.nstate) + " nalg=" + std::to_string(b.nalg) + " nparam=" + std::to_string(b.nparam) + "\n";
    for (const auto& s : b.states)
        io += "state " + s->name + "|" + s->kind + "|" + std::to_string(s->base) + "|" + std::to_string(s->width) + "|" + joined(s->dims, ",") + "|" + tf(s->hidden) + "\n";
    for (const auto& s : b.param_layout)
        io += "param " + s->name + "|" + std::to_string(s->base) + "|" + std::to_string(s->width) + "|" + joined(s->dims, ",") + "\n";
    for (const auto& s : b.point_layout)
        io += "point " + s->name + "|" + std::to_string(s->off) + "|" + std::to_string(s->point) + "|" + std::to_string(s->slot) + "|" + std::to_string(s->tab) + "|" +
              std::to_string(s->row) + "\n";
    for (const auto& s : b.algebraic)
        io += "alg " + s->name + "|" + s->kind + "|" + std::to_string(s->base) + "|" + std::to_string(s->width) + "|" + std::to_string(s->level) + "|" +
              std::to_string(s->cls) + "|" + joined(s->dims, ",") + "|" + joined(s->reads_alg, ",") + "|" + tf(s->hidden) + "\n";
    out["layout"] = io;
    out["P"] = nums(b.P);
    {
        std::string t;
        static const char* rules[] = {"linear", "extrapolate", "below", "above", "nearest"};
        for (std::size_t i = 0; i < b.TAB.size(); i++) {
            const LookupTable& tab = *b.TAB[i];
            t += std::string(i ? "\n" : "") + nums(tab.x) + "|" + nums(tab.y) + "|" + rules[static_cast<int>(tab.interpolation)] + "|" + tf(tab.cyclic) + "|" + tf(tab.wraps);
        }
        out["tables"] = t;
    }
    out["invariant"] = stmts_text(merge_statements(b.pass_stmts[0]));
    out["clock"] = stmts_text(merge_statements(b.pass_stmts[1]));
    out["moving"] = stmts_text(merge_statements(b.pass_stmts[2]));
    if (!b.has_derivative_stmts) {
        out["derivative"] = "all";
    } else {
        std::vector<std::string> names(b.derivative_blocks.begin(), b.derivative_blocks.end());
        std::sort(names.begin(), names.end());
        out["derivative"] = joined(names, ",") + "\n" + stmts_text(merge_statements(b.derivative_stmts));
    }
    out["initial"] = stmts_text(merge_statements(b.initial_before)) + "\n--\n" + stmts_text(merge_statements(b.initial_stmts));
    out["classes"] = ints(b.slot_class);
    {
        static const char* kinds[] = {"transfers", "x", "waste", "move", "mean", "coef", "farf"};
        std::string t;
        for (std::size_t i = 0; i < b.phases.size(); i++) {
            const Phase& ph = b.phases[i];
            t += std::string(i ? "\n" : "") + kinds[static_cast<int>(ph.kind)] + " tgt=" + ints(ph.tgt) + " a=" + ints(ph.a) + " b=" + ints(ph.b) + " c=" + ints(ph.c) +
                 " f=" + nums(ph.f) + " s1=" + std::to_string(ph.s1) + " s2=" + std::to_string(ph.s2);
        }
        out["phases"] = t;
    }
    out["flux"] = "nflux=" + std::to_string(b.nflux) + " rate=" + ints(b.flux_rate) + " mbd=" + ints(b.flux_mbd) + " src=" + ints(b.flux_mbd_src);
    {
        std::string t;
        for (std::size_t i = 0; i < b.decay_lists.size(); i++) {
            const DecayTables& d = b.DEC_tables.at(b.decay_lists[i]);
            t += std::string(i ? "\n" : "") + b.decay_lists[i] + ": lam=" + nums(d.lam) + " ioff=" + ints(d.ioff) + " icnt=" + ints(d.icnt) + " ipar=" + ints(d.ipar) +
                 " icoef=" + nums(d.icoef);
        }
        out["decay"] = t;
    }
    {
        std::string t;
        for (std::size_t i = 0; i < b.jump_specs.size(); i++) {
            const JumpSpec& j = b.jump_specs[i];
            t += std::string(i ? "\n" : "") + j.name + " slot=" + (j.slot ? std::to_string(*j.slot) : "none") + " text=" + j.text + " index=" + std::to_string(j.index) +
                 " fired_by=" + ints(j.fired_by) + "\n";
            for (std::size_t k = 0; k < j.ops.size(); k++) {
                const JumpOp& op = j.ops[k];
                if (k) t += "\n";
                if (op.kind == JumpOp::Kind::Count) t += "count " + std::to_string(op.slot);
                else if (op.kind == JumpOp::Kind::Fail)
                    t += "fail share=" + std::to_string(op.share_slot) + " intact=" + ints(op.intact) + " exposed=" + ints(op.exposed) + " irf=" + ints(op.irf) +
                         " to=" + ints(op.to) + " budget=" + ints(op.budget);
                else t += "move share=" + std::to_string(op.share_slot) + " from=" + ints(op.from) + " to=" + ints(op.to) + " budget=" + ints(op.budget);
            }
        }
        out["jumps"] = t;
    }
    {
        static const char* actions[] = {"reset", "start", "stop", "snapshot"};
        std::string t;
        for (std::size_t i = 0; i < b.event_slots.size(); i++) {
            const EventSlot& e = b.event_slots[i];
            t += std::string(i ? "\n" : "") + std::to_string(e.slot) + " " + std::to_string(e.direction) + " " + e.name + " " + (e.index ? describe_tuple(*e.index) : "");
        }
        t += "\n--\n";
        bool first = true;
        for (const auto& [k, hs] : b.event_handlers) {
            t += std::string(first ? "" : "\n") + std::to_string(k) + ": ";
            first = false;
            for (std::size_t i = 0; i < hs.size(); i++)
                t += std::string(i ? " " : "") + hs[i].rec->name + "@" + std::to_string(hs[i].off) + ":" + actions[static_cast<int>(hs[i].action)];
        }
        out["events"] = t;
    }
    {
        static const char* kinds[] = {"min_max", "running_mean", "snapshot", "delay"};
        std::string t;
        for (std::size_t i = 0; i < b.MEM.size(); i++)
            t += std::string(i ? "\n" : "") + kinds[static_cast<int>(b.MEM[i].kind)] + " " + std::to_string(b.MEM[i].sign) + " " + tf(b.MEM[i].starts_recording);
        out["memory"] = t;
    }
    if (b.budget) {
        std::string t = "base=" + std::to_string(b.budget->base) + " nfam=" + std::to_string(b.budget->nfam) + " families=" + joined(b.budget->families, ",") + " ";
        for (std::size_t i = 0; i < b.budget->members.size(); i++) {
            const auto& m = b.budget->members[i];
            t += std::string(i ? " " : "") + m.name + ":" + std::to_string(m.base) + ":" + std::to_string(m.width) + ":" + ints(m.fam_of);
        }
        out["budget"] = t;
    }
    return out;
}

int main() {
    Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/builder.json"));
    const char* dumps = std::getenv("KOMPARTMENT_FIXTURE_DUMPS");
    std::vector<std::string> skipped;
    for (const Json& row : fx.get("cases").arr()) {
        const std::string& name = row.get("name").as_string();
        Json model = row.has("example")
                         ? parse_json(check::read_file(std::string(KOMPARTMENT_REPO) + "/examples/" + row.get("example").as_string() + ".json"))
                         : row.get("model");
        try {
            Builder b(std::make_shared<const Project>(model));
            std::map<std::string, std::string> secs = sections(b);
            if (dumps && *dumps) {
                std::ofstream out(std::string(dumps) + "/" + name + ".builder.cpp.txt");
                for (const auto& [k, v] : secs) out << "## " << k << "\n" << v << "\n";
            }
            if (!row.has("sections")) {
                CHECK_MSG(false, name + " is refused there: " + row.get("error").as_string());
                continue;
            }
            for (const auto& [key, hash] : row.get("sections").obj()) {
                auto it = secs.find(key);
                CHECK_MSG(it != secs.end() && fnv(it->second) == hash.as_string(), name + ": " + key + " differs");
            }
        } catch (const NotSupported& e) {
            skipped.push_back(name);
        } catch (const BuildError& e) {
            if (row.has("error")) CHECK_MSG(row.get("error").as_string() == e.what(), name + " is refused with: " + e.what() + "\n   there: " + row.get("error").as_string());
            else CHECK_MSG(false, name + " is built there, refused here: " + e.what());
        } catch (const ValidationError& e) {
            if (row.has("error")) CHECK_MSG(row.get("error").as_string() == e.what(), name + " is refused with: " + e.what() + "\n   there: " + row.get("error").as_string());
            else CHECK_MSG(false, name + " is built there, refused here: " + e.what());
        } catch (const std::exception& e) {
            CHECK_MSG(false, name + " threw: " + e.what());
        }
    }
    if (!skipped.empty()) std::printf("not built here yet (%zu): %s\n", skipped.size(), joined(skipped, ", ").c_str());
    return check::summary("test_builder");
}
