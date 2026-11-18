#include "engine/transport.hpp"

#include <algorithm>
#include <cmath>
#include <functional>
#include <limits>
#include <map>
#include <unordered_map>
#include <unordered_set>
#include <utility>

#include "engine/builder.hpp"
#include "engine/farfield_domain.hpp"
#include "engine/recorders.hpp"
#include "engine/switchtimes.hpp"
#include "lang/functions.hpp"
#include "lang/parse.hpp"
#include "model/names.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

using StringSet = std::unordered_set<std::string>;
using Known = std::function<bool(const std::string&)>;

const JArray NO_ITEMS;

/// A list's items; nothing for what is not a list (a project's collections, a block's
/// entries and its dimensions are lists once the project has read them).
const JArray& items(const Json& v) { return v.is_array() ? v.arr() : NO_ITEMS; }

/// Python's truthiness of what a model file holds: null, false, zero and what is empty are not.
bool py_truthy(const Json& v) {
    switch (v.type()) {
        case Json::Type::Null: return false;
        case Json::Type::Bool: return v.as_bool();
        case Json::Type::Int: return v.as_int() != 0;
        case Json::Type::Float: return v.as_double() != 0;
        default: return !v.empty();
    }
}

/// `v`, or `fallback` where Python reads `v` as false (`v or fallback`).
const Json& py_or(const Json& v, const Json& fallback) { return py_truthy(v) ? v : fallback; }

/// Python's `str(v)` of what stands where an equation does; nothing at all is the empty text.
std::string norm_text(const Json& v) {
    if (v.is_null()) return std::string();
    return v.is_string() ? v.as_string() : py_text(v);
}

bool is_text(const Json& v, const std::string& s) { return v.is_string() && v.as_string() == s; }

/// The equations of each collection a transport expansion reads and rewrites, in the Python engine's order.
const std::vector<std::pair<std::string, std::vector<std::string>>>& transport_equation_keys() {
    static const std::vector<std::pair<std::string, std::vector<std::string>>> keys = [] {
        std::vector<std::pair<std::string, std::vector<std::string>>> d = {
            {"compartments", {"initial", "dydt"}},
            {"transfers", {"rate"}},
            {"inflows", {"rate"}},
            {"expressions", {"equation"}},
            {"farfields", farf_equation_keys()},
        };
        for (const char* kind : {"min_max", "running_mean", "snapshot", "delay", "trigger"}) {
            std::vector<std::string> fields = equation_fields(kind);
            for (const auto& f : event_fields(kind)) fields.push_back(f);
            d.emplace_back(recorder_collection(kind), std::move(fields));
        }
        return d;
    }();
    return keys;
}

/// A key a patch removes rather than sets (JavaScript's `undefined`).
const std::optional<Json> UNDEFINED = std::nullopt;
using Patch = std::vector<std::pair<std::string, std::optional<Json>>>;

const Json& transport_role(const Json& block) { return py_truthy(block) ? block.get("transport") : Json::null_value; }

const JArray& project_blocks(const Project& project, const std::string& key) { return project.blocks_of(key); }

// --- what an expansion looks blocks up by ---------------------------------------------------------------

/// A block's texts under some keys, and the last component of every name they hold.
struct Texts {
    std::vector<std::string> texts;
    StringSet last;
};

using TokenList = std::shared_ptr<const std::vector<Token>>;
using TokenCache = std::unordered_map<std::string, TokenList>;
using ReadCache = std::map<std::pair<const JObject*, std::string>, Texts>;

/// What an expansion looks blocks up by, worked out once: the project's blocks do not
/// change while it runs, and a model of many transports would otherwise read every block
/// of the model again for each one. Every lookup gives what the scan it stands for gives,
/// in the same order.
///
/// - `own`: collection => sub-system => its blocks, in the project's order;
/// - `pairs`: a transfer's `(from, to)` => its positions among the project's transfers;
/// - `names`: a block (by identity, and kept so that it stays the one) => its qualified
///   name, worked out once;
/// - `reading`: a base name => where it is read, `(group, position)` in the order the
///   counter check scans the groups, made when a counter is first checked.
struct TransportIndex {
    std::unordered_map<std::string, std::unordered_map<std::string, JArray>> own;
    std::map<std::pair<std::string, std::string>, std::vector<std::size_t>> pairs;
    std::unordered_map<const JObject*, std::pair<Json, std::string>> names;
    std::optional<std::unordered_map<std::string, std::vector<std::pair<std::size_t, std::size_t>>>> reading;
};

TransportIndex transport_index(const Project& project) {
    TransportIndex ix;
    for (const char* key : {"compartments", "expressions", "transfers", "inflows"}) {
        auto& by = ix.own[key];
        for (const Json& b : project_blocks(project, key)) by[system_of(b)].push_back(b);
    }
    const JArray& transfers = project_blocks(project, "transfers");
    for (std::size_t k = 0; k < transfers.size(); k++) {
        const Json& from = transfers[k].get("from");
        const Json& to = transfers[k].get("to");
        // Only a transfer between two named blocks can be one of a chain's.
        if (from.is_string() && to.is_string()) ix.pairs[{from.as_string(), to.as_string()}].push_back(k);
    }
    return ix;
}

/// A block's qualified name, worked out once per block.
const std::string& qname(TransportIndex& ix, const Json& b) {
    static const std::string none;
    if (!b.is_object()) return none;
    const JObject* id = &b.obj();
    auto it = ix.names.find(id);
    if (it == ix.names.end()) it = ix.names.emplace(id, std::make_pair(b, qualified_name(b))).first;
    return it->second.second;
}

/// The groups the counter check reads, in its order: the blocks and the keys of each.
struct CounterGroup {
    const JArray* blocks;
    std::vector<std::string> keys;
};
std::vector<CounterGroup> counter_groups(const Project& project) {
    return {{&project_blocks(project, "expressions"), {"equation"}},
            {&project_blocks(project, "transfers"), {"rate"}},
            {&project_blocks(project, "inflows"), {"rate"}},
            {&project_blocks(project, "compartments"), {"initial", "dydt"}}};
}

/// `tokenize(src)`, or null where it fails -- kept in `cache` when one is given.
TokenList transport_tokens(const std::string& src, TokenCache* cache) {
    if (cache) {
        auto hit = cache->find(src);
        if (hit != cache->end()) return hit->second;
    }
    TokenList tokens;
    try {
        tokens = std::make_shared<const std::vector<Token>>(tokenize(src));
    } catch (const EquationSyntaxError&) {
        tokens = nullptr;
    }
    if (cache) (*cache)[src] = tokens;
    return tokens;
}

/// A block's texts under `keys`, and the last component of every name they hold -- worked
/// out once for each block in an expansion (the project's blocks do not change while it runs).
const Texts& texts_of(ReadCache& read, TokenCache& tokens, const Json& block, const std::vector<std::string>& keys) {
    std::pair<const JObject*, std::string> at{block.is_object() ? &block.obj() : nullptr, join(keys, " ")};
    auto got = read.find(at);
    if (got != read.end()) return got->second;
    Texts t;
    for (const auto& key : keys) {
        const Json& v = block.get(key);
        if (v.is_string()) t.texts.push_back(v.as_string());
        for (const Json& e : items(block.get("entries"))) {
            const Json& x = e.get(key);
            if (x.is_string()) t.texts.push_back(x.as_string());
        }
    }
    for (const auto& text : t.texts) {
        TokenList toks = transport_tokens(text, &tokens);
        if (!toks) continue;
        for (const Token& tok : *toks)
            if (tok.type == Token::Type::Ident) t.last.insert(base_name(tok.text));
    }
    return read.emplace(std::move(at), std::move(t)).first->second;
}

/// Where each base name is read among the counter check's groups: `(group, position)`, in its scan order.
const std::unordered_map<std::string, std::vector<std::pair<std::size_t, std::size_t>>>& reading_index(
    TransportIndex& ix, const Project& project, ReadCache& read, TokenCache& tokens) {
    if (ix.reading) return *ix.reading;
    std::unordered_map<std::string, std::vector<std::pair<std::size_t, std::size_t>>> out;
    std::vector<CounterGroup> groups = counter_groups(project);
    for (std::size_t g = 0; g < groups.size(); g++) {
        const JArray& blocks = *groups[g].blocks;
        for (std::size_t pos = 0; pos < blocks.size(); pos++) {
            // Group by group and block by block: every list comes out in the scan's order.
            for (const auto& name : texts_of(read, tokens, blocks[pos], groups[g].keys).last) out[name].emplace_back(g, pos);
        }
    }
    ix.reading = std::move(out);
    return *ix.reading;
}

// --- a transport's parts -----------------------------------------------------------------------------------

/// A transport's parts: its Begin and End compartments, its number and counter, and its
/// operations (every one of each; the first is the one that counts).
struct Parts {
    std::string path;
    JArray begins, ends, numbers, counters, operations;
};

Parts transport_parts(const std::string& path, const TransportIndex& ix) {
    auto with_role = [&](const char* key, const char* role) {
        JArray out;
        auto by = ix.own.find(key);
        if (by == ix.own.end()) return out;
        auto own = by->second.find(path);
        if (own == by->second.end()) return out;
        for (const Json& b : own->second)
            if (transport_role(b) == role) out.push_back(b);
        return out;
    };
    Parts p;
    p.path = path;
    p.begins = with_role("compartments", "begin");
    p.ends = with_role("compartments", "end");
    p.numbers = with_role("expressions", "number");
    p.counters = with_role("expressions", "counter");
    p.operations = with_role("expressions", "operation");
    return p;
}

/// The transfers drawn between a transport's Begin and End, either way.
JArray internal_transfers(const Project& project, const Parts& parts, const TransportIndex& ix) {
    JArray out;
    if (parts.begins.empty() || parts.ends.empty()) return out;
    std::string b = qualified_name(parts.begins[0]);
    std::string e = qualified_name(parts.ends[0]);
    if (b.empty() || e.empty()) return out;
    std::vector<std::size_t> at;
    for (const auto& key : {std::make_pair(b, e), std::make_pair(e, b)}) {
        auto hit = ix.pairs.find(key);
        if (hit != ix.pairs.end()) at.insert(at.end(), hit->second.begin(), hit->second.end());
    }
    std::sort(at.begin(), at.end());
    at.erase(std::unique(at.begin(), at.end()), at.end());
    const JArray& every = project_blocks(project, "transfers");
    for (std::size_t k : at) out.push_back(every[k]);
    return out;
}

/// How many compartments a transport's chain has; `why` says why not when it cannot be known.
struct ChainLength {
    long long n = 0;
    std::optional<std::string> why;
};

ChainLength transport_number(const Project& project, const Parts& parts) {
    if (parts.numbers.empty()) {
        return {0, "'" + parts.path + "' has no transport number, so the length of its chain is not known. Add one "
                   "(an expression with the part \"number\")."};
    }
    const Json& N = parts.numbers[0];
    std::string name = qualified_name(N);
    std::optional<double> value = constant_value(project, N, "expression");
    if (!value) {
        return {0, "'" + name + "' cannot be worked out before the run starts. The number of compartments in a transport "
                   "may use numbers, parameters and expressions made of those, and nothing that changes over the run."};
    }
    long long n = std::fabs(*value) < 9.0e18 ? static_cast<long long>(std::trunc(*value))
                                             : (*value > 0 ? std::numeric_limits<long long>::max() : std::numeric_limits<long long>::min());
    if (n < 1) return {0, "'" + name + "' comes to " + js_number(*value) + ", and a transport needs at least one compartment."};
    return {n, std::nullopt};
}

/// A block's copy without its transport part, its qualified name and its kind, with `patch` applied in its order.
Json plain_block(const Json& block, const Patch& patch = {}) {
    Json out = Json::object();
    if (block.is_object()) {
        for (const auto& [k, v] : block.obj()) {
            if (k == "transport" || k == "qname" || k == "kind") continue;
            out.set(k, v);
        }
    }
    for (const auto& [key, value] : patch) {
        if (!value) out.erase(key);
        else out.set(key, *value);
    }
    return out;
}

// --- equations rewritten ------------------------------------------------------------------------------------

/// Where the characters of a text are: tokens count characters, text is cut by bytes.
struct CharSlices {
    const std::string& src;
    std::vector<std::size_t> starts;   // of each character and of the end; empty when every character is one byte

    explicit CharSlices(const std::string& s) : src(s) {
        bool ascii = std::all_of(s.begin(), s.end(), [](char c) { return (static_cast<unsigned char>(c) & 0x80) == 0; });
        if (ascii) return;
        for (std::size_t k = 0; k < s.size(); k++)
            if ((static_cast<unsigned char>(s[k]) & 0xc0) != 0x80) starts.push_back(k);
        starts.push_back(s.size());
    }
    std::size_t count() const { return starts.empty() ? src.size() : starts.size() - 1; }
    /// The characters `a .. b-1` (character offsets from 0, as the tokenizer counts).
    std::string_view slice(std::size_t a, std::size_t b) const {
        if (starts.empty()) return std::string_view(src).substr(a, b - a);
        return std::string_view(src).substr(starts[a], starts[b] - starts[a]);
    }
};

/// `src` with every name that refers to a block replaced by `replace(qname)` where that
/// gives something else; everything between is kept as written.
std::string rewrite_refs(const std::string& src, const std::string& system, const Known& known,
                         const std::function<std::optional<std::string>(const std::string&)>& replace, TokenCache* cache) {
    if (src.empty()) return src;
    TokenList tokens = transport_tokens(src, cache);
    if (!tokens) return src;
    CharSlices chars(src);
    std::string out;
    std::size_t cursor = 0;
    for (std::size_t i = 0; i < tokens->size(); i++) {
        const Token& tok = (*tokens)[i];
        if (tok.type != Token::Type::Ident) continue;
        if (i + 1 < tokens->size() && (*tokens)[i + 1].type == Token::Type::LParen && lookup_function(tok.text)) continue;
        std::optional<std::string> q = resolve_reference(tok.text, system, known);
        if (!q) continue;
        std::optional<std::string> to = replace(*q);
        if (!to || *to == tok.text) continue;
        out += chars.slice(cursor, static_cast<std::size_t>(tok.pos));
        out += *to;
        cursor = static_cast<std::size_t>(tok.pos) + tok.text.size();
    }
    if (cursor == 0) return src;
    out += chars.slice(cursor, chars.count());
    return out;
}

/// `src` with every call of the operation `target` written as a call of `fn_name` over the chain's elements.
std::string rewrite_calls(const std::string& src, const std::string& system, const std::string& target, const std::string& fn_name,
                          const std::vector<std::string>& elements, int arity, const Known& known, const std::string& owner) {
    if (src.empty() || src.find(base_name(target)) == std::string::npos) return src;
    std::vector<Token> tokens;
    try {
        tokens = tokenize(src);
    } catch (const EquationSyntaxError&) {
        return src;
    }
    CharSlices chars(src);
    std::string out;
    std::size_t cursor = 0;
    for (std::size_t i = 0; i < tokens.size(); i++) {
        const Token& tok = tokens[i];
        if (tok.type != Token::Type::Ident || i + 1 >= tokens.size() || tokens[i + 1].type != Token::Type::LParen) continue;
        if (lookup_function(tok.text)) continue;
        std::optional<std::string> q = resolve_reference(tok.text, system, known);
        if (!q || *q != target) continue;
        int depth = 0, commas = 0;
        bool empty = true;
        for (std::size_t j = i + 1; j < tokens.size(); j++) {
            const Token& t = tokens[j];
            if (t.type == Token::Type::LParen) {
                depth++;
            } else if (t.type == Token::Type::RParen) {
                depth--;
                if (depth == 0) break;
            } else if (t.type == Token::Type::Comma && depth == 1) {
                commas++;
            }
            if (depth == 1 && j > i + 1) empty = false;
        }
        int given = empty ? 0 : commas + 1;
        if (given != arity) {
            std::string wants = arity == 1 ? "one position along the chain, between 0 and 1"
                                           : "two positions along the chain, each between 0 and 1";
            std::string was = given == 1 ? " was" : "s were";
            throw TransportError("'" + tok.text + "' is a transport operation that takes " + wants + "; " + std::to_string(given) +
                                     " argument" + was + " given.",
                                 owner);
        }
        std::vector<std::string> spelled;
        spelled.reserve(elements.size());
        for (const auto& e : elements) spelled.push_back(reference_from(e, system, known));
        const Token& opening = tokens[i + 1];
        out += chars.slice(cursor, static_cast<std::size_t>(tok.pos));
        out += fn_name + "(" + join(spelled, ", ") + ", ";
        cursor = static_cast<std::size_t>(opening.pos) + 1;
    }
    if (cursor == 0) return src;
    out += chars.slice(cursor, chars.count());
    return out;
}

// --- one transport written out -------------------------------------------------------------------------------

struct Expansion {
    const Project& project;
    Json& raw;
    StringSet& known;
    StringSet& taken;
    StringSet& off;
    TokenCache& tokens;
    ReadCache& read;
    TransportIndex& ix;

    /// The blocks of a list that are none of `names`.
    Json without(const Json& list, const StringSet& names) {
        Json out = Json::array();
        for (const Json& b : items(list))
            if (!names.count(qname(ix, b))) out.push(b);
        return out;
    }

    void expand_one(const std::string& path);
};

void Expansion::expand_one(const std::string& path) {
    Parts parts = transport_parts(path, ix);
    bool switched_off = std::any_of(project.disabled.begin(), project.disabled.end(), [&](const std::string& n) { return parent_of(n) == path; });
    if ((parts.begins.empty() || parts.ends.empty()) && switched_off) {
        StringSet going;
        for (const JArray* part : {&parts.begins, &parts.ends, &parts.numbers, &parts.counters, &parts.operations})
            for (const Json& b : *part) going.insert(js_str(b.get("qname")));
        raw.set("compartments", without(raw.get("compartments"), going));
        raw.set("expressions", without(raw.get("expressions"), going));
        off.insert(going.begin(), going.end());
        return;
    }
    if (parts.begins.size() != 1 || parts.ends.size() != 1) {
        auto count = [](const JArray& lst, const std::string& what) {
            std::size_t n = lst.size();
            return (n == 0 ? std::string("no") : std::to_string(n)) + " " + what + (n == 1 ? "" : (n != 0 ? "s" : ""));
        };
        std::vector<std::string> what;
        if (parts.begins.size() != 1) what.push_back(count(parts.begins, "Begin compartment"));
        if (parts.ends.size() != 1) what.push_back(count(parts.ends, "End compartment"));
        throw TransportError("'" + path + "' is a transport with " + join(what, " and ") + ". A transport is a chain from one Begin "
                             "to one End.", path);
    }
    const Json B = parts.begins[0], E = parts.ends[0];
    const std::string bq = js_str(B.get("qname")), eq = js_str(E.get("qname"));
    auto dims_text = [](const Json& b) {
        std::vector<std::string> dims;
        for (const Json& d : items(b.get("index_lists"))) dims.push_back(js_str(d));
        std::sort(dims.begin(), dims.end());
        return join(dims, " ");
    };
    if (dims_text(B) != dims_text(E)) {
        throw TransportError("'" + eq + "' is not indexed by the same lists as '" + bq + "'. Every compartment of the chain is one "
                             "compartment repeated, so Begin and End must match.", eq);
    }
    ChainLength number = transport_number(project, parts);
    if (number.why) throw TransportError(*number.why, !parts.numbers.empty() ? js_str(parts.numbers[0].get("qname")) : path);
    const long long n = number.n;
    const bool counted = !parts.counters.empty();
    const Json C = counted ? parts.counters[0] : Json();
    const std::string cq = counted ? js_str(C.get("qname")) : std::string();
    JArray internal = internal_transfers(project, parts, ix);
    StringSet internal_names;
    for (const Json& t : internal) internal_names.insert(js_str(t.get("qname")));
    JArray dependent;
    StringSet dependent_names;
    const Known is_known = [&](const std::string& name) { return known.count(name) != 0; };

    auto pair_names = [&] {
        StringSet s = {bq, eq};
        if (counted) s.insert(cq);
        s.insert(internal_names.begin(), internal_names.end());
        s.insert(dependent_names.begin(), dependent_names.end());
        return s;
    };

    // A reference keeps its last component whatever it resolves to, so a block none of
    // whose names ends as one of `bases` refers to none of `names`.
    auto refs_any = [&](const Json& block, const std::vector<std::string>& keys, const StringSet& names, const StringSet& bases) {
        const Texts& t = texts_of(read, tokens, block, keys);
        if (std::none_of(bases.begin(), bases.end(), [&](const std::string& b) { return t.last.count(b) != 0; })) return false;
        for (const auto& text : t.texts) {
            if (std::none_of(bases.begin(), bases.end(), [&](const std::string& b) { return text.find(b) != std::string::npos; })) continue;
            bool found = false;
            // Resolved where the block that writes it sits: from inside this chain, a bare
            // `i` in a second transport was this one's counter.
            rewrite_refs(text, system_of(block), is_known, [&](const std::string& q) -> std::optional<std::string> {
                if (names.count(q)) found = true;
                return std::nullopt;
            }, &tokens);
            if (found) return true;
        }
        return false;
    };

    bool grew = true;
    static const JArray nothing_inside;
    auto own_expressions = ix.own["expressions"].find(path);
    const JArray& inside = own_expressions == ix.own["expressions"].end() ? nothing_inside : own_expressions->second;
    const std::vector<std::string> equation_key = {"equation"};
    while (grew) {
        grew = false;
        StringSet names = pair_names();
        StringSet bases;
        for (const auto& q : names) bases.insert(base_name(q));
        for (const Json& x : inside) {
            std::string xq = js_str(x.get("qname"));
            if (py_truthy(transport_role(x)) || dependent_names.count(xq)) continue;
            if (refs_any(x, equation_key, names, bases)) {
                dependent.push_back(x);
                dependent_names.insert(xq);
                grew = true;
            }
        }
    }
    if (counted) {
        StringSet only = {cq};
        StringSet bases = {base_name(cq)};
        const Json* outside = nullptr;
        // Only a block that reads a name ending as the counter's can refer to it: those,
        // in the order the groups are scanned.
        std::vector<CounterGroup> groups = counter_groups(project);
        const auto& reading = reading_index(ix, project, read, tokens);
        auto readers = reading.find(base_name(cq));
        if (readers != reading.end()) {
            for (const auto& [g, pos] : readers->second) {
                const Json& b = (*groups[g].blocks)[pos];
                if (system_of(b) != path && refs_any(b, groups[g].keys, only, bases)) {
                    outside = &b;
                    break;
                }
            }
        }
        if (outside) {
            std::string oq = js_str(outside->get("qname"));
            throw TransportError("'" + oq + "' reads '" + cq + "', the element counter of '" + path + "', from outside the "
                                 "transport. The counter counts the compartments of the chain and has a value only "
                                 "inside it.", oq);
        }
    }

    auto fresh = [&](const std::string& base) {
        std::string name = base;
        long long i = 1;
        while (taken.count(qualify(path, name))) {
            name = base + "_" + std::to_string(i);
            i++;
        }
        taken.insert(qualify(path, name));
        return name;
    };

    // The chain's elements, counted from 1 as the equations count them.
    const std::string bname = js_str(B.get("name"));
    std::vector<std::string> elem_local(static_cast<std::size_t>(n));
    auto local = [&](long long e) -> std::string& { return elem_local[static_cast<std::size_t>(e - 1)]; };
    local(1) = bname;
    if (n > 1) local(n) = js_str(E.get("name"));
    for (long long e = 2; e <= n - 1; e++) local(e) = fresh(bname + "_" + std::to_string(e));
    auto elem_q = [&](long long e) { return qualify(path, local(e)); };
    std::vector<std::string> elements;
    elements.reserve(elem_local.size());
    for (long long e = 1; e <= n; e++) elements.push_back(elem_q(e));
    std::unordered_map<std::string, std::string> copy_name;
    auto copy_key = [](const Json& block, long long e) { return js_str(block.get("qname")) + " " + std::to_string(e); };
    for (long long e = 1; e <= n - 1; e++) {
        for (const Json& x : dependent) copy_name[copy_key(x, e)] = fresh(js_str(x.get("name")) + "_" + std::to_string(e));
        for (const Json& t : internal)
            copy_name[copy_key(t, e)] = e == 1 ? js_str(t.get("name")) : fresh(js_str(t.get("name")) + "_" + std::to_string(e));
    }

    auto replace_for = [&](long long e) {
        return [&, e](const std::string& q) -> std::optional<std::string> {
            if (q == bq) return local(e);
            // End read from End's own equations (e == n) has no element after it: the name
            // stays, as in the application (Python's list index fails there).
            if (q == eq) return e < n ? std::optional<std::string>(local(e + 1)) : std::nullopt;
            if (counted && q == cq) return std::to_string(e);
            auto hit = copy_name.find(q + " " + std::to_string(e));
            return hit == copy_name.end() ? std::nullopt : std::optional<std::string>(hit->second);
        };
    };
    auto rewrite = [&](const Json& text, long long e) { return rewrite_refs(norm_text(text), path, is_known, replace_for(e), &tokens); };
    auto rewrite_entries = [&](const Json& entries, const std::string& key, long long e) {
        Json out = Json::array();
        for (const Json& en : items(entries)) {
            Json c = en.shallow();
            if (en.get(key).is_string()) c.set(key, Json(rewrite(en.get(key), e)));
            out.push(c);
        }
        return out;
    };
    auto rewrite_initial = [&](const Json& text, long long e) {
        return rewrite_refs(norm_text(text), path, is_known, [&](const std::string& q) -> std::optional<std::string> {
            return (counted && q == cq) ? std::optional<std::string>(std::to_string(e)) : std::nullopt;
        }, &tokens);
    };
    auto b_dims = [&] { return Json(JArray(items(B.get("index_lists")))); };
    auto either_unit = [&](const Json& x) { return py_or(x.get("unit"), B.get("unit")); };

    if (n == 1) {
        raw.set("compartments", without(raw.get("compartments"), {eq}));
        raw["expressions"].push(plain_block(E, {
            {"equation", B.get("name")}, {"unit", either_unit(E)}, {"index_lists", b_dims()}, {"entries", Json::array()},
            {"initial", UNDEFINED}, {"abstol", UNDEFINED}, {"non_negative", UNDEFINED},
            {"handle_decay", UNDEFINED}, {"dydt", UNDEFINED}}));
        auto rewired = [&](const Json& list) {
            Json out = Json::array();
            for (const Json& conn : items(list)) {
                if (internal_names.count(qname(ix, conn))) continue;
                const Json& from = conn.get("from");
                const Json& to = conn.get("to");
                if (!is_text(from, eq) && !is_text(to, eq)) {
                    out.push(conn);
                    continue;
                }
                Json c = conn.shallow();
                c.set("from", is_text(from, eq) ? Json(bq) : from);
                c.set("to", is_text(to, eq) ? Json(bq) : to);
                out.push(c);
            }
            return out;
        };
        raw.set("transfers", rewired(raw.get("transfers")));
        raw.set("inflows", rewired(raw.get("inflows")));
    } else {
        for (long long e = 2; e <= n - 1; e++) {
            raw["compartments"].push(plain_block(B, {
                {"name", Json(local(e))}, {"system", Json(path)}, {"hidden", Json(true)},
                {"alias", Json::object({{"compartment", Json(bq)}})},
                {"initial", Json(rewrite_initial(B.get("initial"), e))},
                {"dydt", B.get("dydt").is_string() ? std::optional<Json>(Json(rewrite(B.get("dydt"), e))) : UNDEFINED},
                {"entries", rewrite_entries(rewrite_entries(B.get("entries"), "initial", e), "dydt", e)},
                {"color", UNDEFINED}, {"symbol", UNDEFINED}, {"comment", Json("")}}));
        }
        auto end_block = [&](const Json& c) -> Json {
            if (qname(ix, c) != eq) return c;
            Json entries = Json::array();
            Json initial_entries = rewrite_entries(B.get("entries"), "initial", n);
            for (const Json& en : items(initial_entries)) {
                Json rest = Json::object();
                bool any = false;
                if (en.is_object()) {
                    for (const auto& [k, v] : en.obj()) {
                        if (k == "dydt") continue;
                        rest.set(k, v);
                        any = any || k != "index";
                    }
                }
                if (any) entries.push(rest);
            }
            for (const Json& en : items(E.get("entries"))) {
                if (!en.get("dydt").is_string()) continue;
                entries.push(Json::object({{"index", en.get("index")}, {"dydt", Json(rewrite(en.get("dydt"), n))}}));
            }
            return plain_block(B, {
                {"name", E.get("name")}, {"system", Json(path)}, {"unit", either_unit(E)},
                {"comment", E.get("comment")}, {"color", E.get("color")}, {"symbol", E.get("symbol")},
                {"initial", Json(rewrite_initial(B.get("initial"), n))},
                {"dydt", E.get("dydt").is_string() ? std::optional<Json>(Json(rewrite(E.get("dydt"), n))) : UNDEFINED},
                {"entries", entries}});
        };
        {
            Json compartments = Json::array();
            for (const Json& c : items(raw.get("compartments"))) compartments.push(end_block(c));
            raw.set("compartments", compartments);
        }
        raw.set("transfers", without(raw.get("transfers"), internal_names));
        for (long long e = 1; e <= n - 1; e++) {
            for (const Json& x : dependent) {
                raw["expressions"].push(plain_block(x, {
                    {"name", Json(copy_name.at(copy_key(x, e)))}, {"system", Json(path)}, {"hidden", Json(true)},
                    {"equation", Json(rewrite(x.get("equation"), e))},
                    {"entries", rewrite_entries(x.get("entries"), "equation", e)},
                    {"color", UNDEFINED}, {"symbol", UNDEFINED}, {"comment", Json("")}}));
            }
            for (const Json& t : internal) {
                bool forward = is_text(t.get("from"), bq);
                Patch patch = {
                    {"name", Json(copy_name.at(copy_key(t, e)))}, {"system", Json(path)},
                    {"alias", Json::object({{"transfer", t.get("qname")}, {"from", t.get("from")}, {"to", t.get("to")}})},
                    {"from", Json(forward ? elem_q(e) : elem_q(e + 1))},
                    {"to", Json(forward ? elem_q(e + 1) : elem_q(e))},
                    {"rate", Json(rewrite(t.get("rate"), e))},
                    {"entries", rewrite_entries(t.get("entries"), "rate", e)}};
                if (e != 1) {
                    patch.emplace_back("hidden", Json(true));
                    patch.emplace_back("color", UNDEFINED);
                    patch.emplace_back("comment", Json(""));
                }
                raw["transfers"].push(plain_block(t, patch));
            }
        }
    }
    if (n == 1) {
        for (const Json& t : internal) {
            Json entries = Json::array();
            for (const Json& en : items(t.get("entries"))) {
                Json rest = Json::object();
                if (en.is_object()) {
                    for (const auto& [k, v] : en.obj())
                        if (k != "rate") rest.set(k, v);
                }
                if (en.get("rate").is_string()) rest.set("equation", en.get("rate"));
                entries.push(rest);
            }
            raw["expressions"].push(plain_block(t, {
                {"equation", t.get("rate")}, {"entries", entries}, {"from", UNDEFINED}, {"to", UNDEFINED},
                {"multiply_by_donor", UNDEFINED}, {"index_lists", b_dims()}}));
        }
    }
    auto replaced = [&](const std::string& which, const std::function<Json(const Json&)>& with) {
        Json out = Json::array();
        for (const Json& x : items(raw.get("expressions"))) out.push(qname(ix, x) != which ? x : with(x));
        raw.set("expressions", out);
    };
    if (counted) replaced(cq, [&](const Json&) { return plain_block(C, {{"equation", Json("1")}, {"hidden", Json(true)}}); });
    replaced(js_str(parts.numbers[0].get("qname")), [&](const Json& x) { return plain_block(x); });
    std::vector<std::string> locals;
    locals.reserve(elements.size());
    for (const auto& q : elements) locals.push_back(base_name(q));
    const Known is_taken = [&](const std::string& name) { return taken.count(name) != 0; };
    for (const Json& op : parts.operations) {
        std::string oq = js_str(op.get("qname"));
        bool mean = py_or(op.get("operation"), Json("mean")) == "mean";
        if (py_or(op.get("argument"), Json("all")) == "all") {
            std::string total = join(locals, " + ");
            replaced(oq, [&](const Json&) {
                return plain_block(op, {
                    {"equation", Json(mean ? "(" + total + ") / " + std::to_string(n) : total)}, {"index_lists", b_dims()},
                    {"unit", py_or(op.get("unit"), B.get("unit"))}, {"entries", Json::array()},
                    {"operation", UNDEFINED}, {"argument", UNDEFINED}});
            });
            continue;
        }
        raw.set("expressions", without(raw.get("expressions"), {oq}));
        bool point = op.get("argument") == "point";
        std::string fn_name = point ? "transport_point" : (mean ? "transport_mean" : "transport_sum");
        int arity = point ? 1 : 2;
        for (const auto& [collection, keys] : transport_equation_keys()) {
            Json new_list = Json::array();
            for (const Json& b : items(raw.get(collection))) {
                std::string system = system_of(b);
                const std::string& owner = qname(ix, b);
                Json changed;   // null until something in the block changes
                const Json& entries = b.get("entries");
                for (const auto& key : keys) {
                    const Json& v = b.get(key);
                    if (v.is_string()) {
                        std::string next = rewrite_calls(v.as_string(), system, oq, fn_name, elements, arity, is_taken, owner);
                        if (next != v.as_string()) {
                            if (changed.is_null()) changed = b.shallow();
                            changed.set(key, Json(next));
                        }
                    }
                    const JArray& own_entries = items(entries);
                    for (std::size_t i = 0; i < own_entries.size(); i++) {
                        const Json& x = own_entries[i].get(key);
                        if (!x.is_string()) continue;
                        std::string next = rewrite_calls(x.as_string(), system, oq, fn_name, elements, arity, is_taken, owner);
                        if (next == x.as_string()) continue;
                        if (changed.is_null()) changed = b.shallow();
                        if (changed.get("entries").same(entries)) {
                            Json copies = Json::array();
                            for (const Json& y : own_entries) copies.push(y.shallow());
                            changed.set("entries", copies);
                        }
                        changed["entries"][i].set(key, Json(next));
                    }
                }
                new_list.push(changed.is_null() ? b : changed);
            }
            if (raw.has(collection) || !new_list.empty()) raw.set(collection, new_list);
        }
    }
}

}  // namespace

// --- what the rest of the engine reads ---------------------------------------------------------------------------

std::vector<std::string> transport_paths(const Project& project) {
    std::vector<std::string> out;
    for (const auto& p : project.transports)
        if (!p.empty()) out.push_back(p);
    return out;
}

Json project_to_json(const Project& p) {
    auto every = [&](const std::string& key) {
        JArray out = p.blocks_of(key);
        auto off = p.switched_off.find(key);
        if (off != p.switched_off.end()) out.insert(out.end(), off->second.begin(), off->second.end());
        return Json(std::move(out));
    };
    Json out = Json::object({{"name", p.name}, {"description", p.description}, {"simulation", p.simulation},
                             {"nuclides", p.nuclides}, {"half_lives", p.half_lives_override}, {"decay_unit", Json(p.decay_unit)}});
    if (p.chains_stated) out.set("chains", p.chains_override);
    Json lists = Json::array();
    for (const Json& l : items(p.index_lists))
        if (!(l.get("name").is_string() && p.derived_lists.count(l.get("name").as_string()))) lists.push(l);
    out.set("index_lists", lists);
    if (p.scenario && !p.scenario->empty()) out.set("scenario", Json(*p.scenario));
    for (const char* key : {"parameters", "compartments", "expressions", "transfers", "inflows"}) out.set(key, every(key));
    for (const char* key : {"lookups", "index_reductions", "block_reductions", "functions", "min_maxes", "running_means",
                            "snapshots", "delays", "triggers", "farfields", "waste_packages", "events"}) {
        std::string_view k(key);
        bool present = (k == "index_reductions" || k == "triggers") ? !p.blocks_of(key).empty() : !every(key).empty();
        if (present) out.set(key, every(key));
    }
    if (!p.transports.empty()) out.set("transports", Json::array(p.transports));
    if (!p.disabled_systems.empty()) {
        std::vector<std::string> unique;
        for (const auto& q : p.disabled_systems)
            if (std::find(unique.begin(), unique.end(), q) == unique.end()) unique.push_back(q);
        out.set("disabled_systems", Json::array(unique));
    }
    if (!p.systems.empty()) out.set("systems", Json::array(p.systems));
    out.set("layout", p.layout);
    if (!p.shapes.empty()) out.set("shapes", p.shapes);
    if (!p.derived.empty()) out.set("derived", p.derived);
    if (p.view.is_object() && !p.view.empty()) out.set("view", p.view);
    return out;
}

std::shared_ptr<const Project> expand_transports(const Project& project) {
    std::vector<std::string> paths;
    for (const auto& q : transport_paths(project))
        if (std::find(project.systems.begin(), project.systems.end(), q) != project.systems.end()) paths.push_back(q);
    if (paths.empty()) return std::make_shared<const Project>(project);
    try {
        // The four collections an expansion adds to are lists of its own here.
        Json raw = project_to_json(project);
        raw.erase("transports");
        StringSet known;
        auto note = [&](const std::string& key) {
            for (const Json& b : items(raw.get(key))) known.insert(qualified_name(b));
        };
        for (const auto& [collection, keys] : transport_equation_keys()) note(collection);
        for (const char* key : {"parameters", "lookups", "index_reductions", "block_reductions"}) note(key);
        StringSet taken = known;
        StringSet off;
        TokenCache tokens;
        ReadCache read;
        TransportIndex ix = transport_index(project);
        Expansion expansion{project, raw, known, taken, off, tokens, read, ix};
        for (const auto& path : paths) expansion.expand_one(path);
        // A Project copies what it is given, so raw needs no copy of its own.
        auto derived = std::make_shared<Project>(raw);
        derived->disabled.insert(project.disabled.begin(), project.disabled.end());
        derived->disabled.insert(off.begin(), off.end());
        for (const auto& [name, why] : project.implicitly_disabled) derived->implicitly_disabled.emplace(name, why);
        return derived;
    } catch (const TransportError& e) {
        throw BuildError(e.what(), e.block_name);
    }
}

}  // namespace kompartment
