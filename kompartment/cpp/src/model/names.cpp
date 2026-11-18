#include "model/names.hpp"

#include <algorithm>

#include "lang/functions.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

bool is_name(std::string_view name) {
    if (name.empty()) return false;
    auto start = [](unsigned char c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_'; };
    if (!start(static_cast<unsigned char>(name[0]))) return false;
    for (unsigned char c : name)
        if (!(start(c) || (c >= '0' && c <= '9'))) return false;
    return true;
}
bool is_name(const Json& name) { return name.is_string() && is_name(std::string_view(name.as_string())); }

std::optional<std::string> name_problem(const Json& name) {
    if (!is_name(name))
        return "'" + js_text(name) + "' is not a valid name: use letters, digits and underscore, and do not start with a digit.";
    if (is_reserved_name(name.as_string())) return "'" + name.as_string() + "' is a reserved name.";
    return std::nullopt;
}

std::vector<std::string> split(std::string_view s, char sep) {
    std::vector<std::string> out;
    std::size_t from = 0;
    for (;;) {
        std::size_t at = s.find(sep, from);
        if (at == std::string_view::npos) {
            out.emplace_back(s.substr(from));
            return out;
        }
        out.emplace_back(s.substr(from, at - from));
        from = at + 1;
    }
}

std::string join(const std::vector<std::string>& parts, std::string_view sep) {
    std::string out;
    for (std::size_t i = 0; i < parts.size(); i++) {
        if (i) out += sep;
        out += parts[i];
    }
    return out;
}

std::vector<std::string> path_parts(std::string_view path) {
    std::vector<std::string> out;
    if (path.empty()) return out;
    for (auto& p : split(path, SEPARATOR))
        if (!p.empty()) out.push_back(std::move(p));
    return out;
}

std::string qualify(std::string_view system, std::string_view name) {
    if (system.empty()) return std::string(name);
    std::string out(system);
    out.push_back(SEPARATOR);
    out += name;
    return out;
}

std::string parent_of(std::string_view path) {
    std::vector<std::string> parts = path_parts(path);
    if (!parts.empty()) parts.pop_back();
    return join(parts, ".");
}

std::string base_name(std::string_view path) {
    // The last component that is not empty, as `path_parts` counts them.
    std::size_t hi = path.size();
    while (hi > 0 && path[hi - 1] == SEPARATOR) hi--;
    if (hi == 0) return "";
    std::size_t lo = path.rfind(SEPARATOR, hi - 1);
    return std::string(lo == std::string_view::npos ? path.substr(0, hi) : path.substr(lo + 1, hi - lo - 1));
}

bool is_within(std::string_view path, std::string_view ancestor) {
    if (ancestor.empty()) return true;
    if (path == ancestor) return true;
    return path.size() > ancestor.size() && path.substr(0, ancestor.size()) == ancestor && path[ancestor.size()] == SEPARATOR;
}

bool is_valid_path(std::string_view path) {
    if (path.empty()) return true;
    for (const auto& c : split(path, SEPARATOR))
        if (!is_name(std::string_view(c))) return false;
    return true;
}

std::string system_of(const Json& block) {
    const Json& s = block.get("system");
    if (s.is_null() || (s.is_bool() && !s.as_bool())) return "";
    return js_str(s);
}

std::string qualified_name(const Json& block) {
    const Json& n = block.get("name");
    return qualify(system_of(block), n.is_null() ? "" : js_str(n));
}

std::optional<std::string> resolve_reference(std::string_view reference, std::string_view system,
                                             const std::function<bool(const std::string&)>& known) {
    std::string ref(reference);
    if (ref.find(SEPARATOR) != std::string::npos) return known(ref) ? std::optional<std::string>(ref) : std::nullopt;
    std::string own = qualify(system, ref);
    if (known(own)) return own;
    return known(ref) ? std::optional<std::string>(ref) : std::nullopt;
}

std::string reference_from(std::string_view target, std::string_view system,
                           const std::function<bool(const std::string&)>& known) {
    std::string parent = parent_of(target);
    std::string local = base_name(target);
    if (parent.empty() || parent == system) {
        auto r = resolve_reference(local, system, known);
        if (r && *r == target) return local;
    }
    return std::string(target);
}

namespace {

// One character of UTF-8 text at `i`: its code point, and how many bytes it takes.
char32_t decode(std::string_view s, std::size_t i, std::size_t& len) {
    unsigned char c = static_cast<unsigned char>(s[i]);
    auto cont = [&](std::size_t k) { return i + k < s.size() ? static_cast<unsigned char>(s[i + k]) & 0x3f : 0; };
    if (c < 0x80) { len = 1; return c; }
    if ((c & 0xe0) == 0xc0) { len = 2; return ((c & 0x1f) << 6) | cont(1); }
    if ((c & 0xf0) == 0xe0) { len = 3; return ((c & 0x0f) << 12) | (cont(1) << 6) | cont(2); }
    len = 4;
    return ((c & 0x07) << 18) | (cont(1) << 12) | (cont(2) << 6) | cont(3);
}

void encode(std::string& out, char32_t u) {
    if (u < 0x80) out.push_back(static_cast<char>(u));
    else if (u < 0x800) {
        out.push_back(static_cast<char>(0xc0 | (u >> 6)));
        out.push_back(static_cast<char>(0x80 | (u & 0x3f)));
    } else if (u < 0x10000) {
        out.push_back(static_cast<char>(0xe0 | (u >> 12)));
        out.push_back(static_cast<char>(0x80 | ((u >> 6) & 0x3f)));
        out.push_back(static_cast<char>(0x80 | (u & 0x3f)));
    } else {
        out.push_back(static_cast<char>(0xf0 | (u >> 18)));
        out.push_back(static_cast<char>(0x80 | ((u >> 12) & 0x3f)));
        out.push_back(static_cast<char>(0x80 | ((u >> 6) & 0x3f)));
        out.push_back(static_cast<char>(0x80 | (u & 0x3f)));
    }
}

// The lower- and upper-case forms of the letters names are written with: ASCII, Latin-1,
// Latin Extended-A, Greek and Cyrillic. Anything else is left as it is.
char32_t lower_of(char32_t u) {
    if (u >= 'A' && u <= 'Z') return u + 32;
    if (u < 0x80) return u;
    if ((u >= 0xc0 && u <= 0xde && u != 0xd7)) return u + 32;
    if (u >= 0x100 && u <= 0x17f) {
        if (u == 0x130 || u == 0x131 || u == 0x138 || u == 0x149 || u == 0x17f) return u;
        if (u == 0x178) return 0xff;
        if ((u >= 0x139 && u <= 0x148) || (u >= 0x179 && u <= 0x17e)) return (u & 1) ? u + 1 : u;
        return (u & 1) ? u : u + 1;
    }
    if (u >= 0x391 && u <= 0x3a9 && u != 0x3a2) return u + 32;
    if (u >= 0x410 && u <= 0x42f) return u + 32;
    if (u >= 0x400 && u <= 0x40f) return u + 80;
    return u;
}
char32_t upper_of(char32_t u) {
    if (u >= 'a' && u <= 'z') return u - 32;
    if (u < 0x80) return u;
    if (u >= 0xe0 && u <= 0xfe && u != 0xf7) return u - 32;
    if (u == 0xff) return 0x178;
    if (u >= 0x100 && u <= 0x17f) {
        if (u == 0x130 || u == 0x131 || u == 0x138 || u == 0x149 || u == 0x17f || u == 0x178) return u;
        if ((u >= 0x139 && u <= 0x148) || (u >= 0x179 && u <= 0x17e)) return (u & 1) ? u : u - 1;
        return (u & 1) ? u - 1 : u;
    }
    if (u >= 0x3b1 && u <= 0x3c9 && u != 0x3c2) return u - 32;
    if (u >= 0x430 && u <= 0x44f) return u - 32;
    if (u >= 0x450 && u <= 0x45f) return u - 80;
    return u;
}

template <class F>
std::string mapped(std::string_view s, F f) {
    std::string out;
    out.reserve(s.size());
    for (std::size_t i = 0; i < s.size();) {
        std::size_t len;
        char32_t u = decode(s, i, len);
        encode(out, f(u));
        i += len;
    }
    return out;
}

}  // namespace

std::string lowercase(std::string_view s) { return mapped(s, lower_of); }
std::string uppercase(std::string_view s) { return mapped(s, upper_of); }

std::pair<std::string, std::string> locale_key(std::string_view s) {
    std::string swapped = mapped(s, [](char32_t u) {
        char32_t lo = lower_of(u), up = upper_of(u);
        return u != lo ? lo : (u != up ? up : u);
    });
    return {lowercase(s), std::move(swapped)};
}

bool locale_less(std::string_view a, std::string_view b) { return locale_key(a) < locale_key(b); }

std::vector<std::string> system_paths(const Json& declared, const Json& transports,
                                      const std::vector<std::string>& block_systems) {
    std::set<std::string> seen;
    auto add_prefixes = [&](std::string_view path) {
        std::vector<std::string> ps = path_parts(path);
        std::string prefix;
        for (std::size_t k = 0; k < ps.size(); k++) {
            if (k) prefix.push_back(SEPARATOR);
            prefix += ps[k];
            seen.insert(prefix);
        }
    };
    for (const Json* source : {&declared, &transports}) {
        if (!source->is_array()) continue;
        for (const Json& item : source->arr()) {
            const Json& path = item.is_object() ? item.get("name") : item;
            if (path.is_string()) add_prefixes(path.as_string());
        }
    }
    for (const auto& path : block_systems) add_prefixes(path);
    std::vector<std::string> out(seen.begin(), seen.end());
    std::stable_sort(out.begin(), out.end(), [](const std::string& a, const std::string& b) {
        std::size_t da = path_parts(a).size(), db = path_parts(b).size();
        if (da != db) return da < db;
        return locale_key(a) < locale_key(b);
    });
    return out;
}

}  // namespace kompartment
