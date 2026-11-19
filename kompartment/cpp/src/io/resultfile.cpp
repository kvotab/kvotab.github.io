#include "io/resultfile.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <fstream>
#include <limits>
#include <unordered_map>
#include <unordered_set>

#include "model/indexlists.hpp"
#include "stats/pdf.hpp"
#include "util/errors.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

constexpr double NaN = std::numeric_limits<double>::quiet_NaN();

// JavaScript's `undefined` -- a property that is not there, as distinct from `null` -- is a
// null pointer here, as in stats/pdf.

/// `obj[key]` for a dictionary, and `undefined` for anything else.
const Json* get(const Json& obj, std::string_view key) { return pd_prop(&obj, key); }

bool nullish(const Json* v) { return pd_nullish(v); }

/// JavaScript's ToBoolean: an object or a list is true however empty; 0, NaN and '' are not.
bool truthy(const Json* v) { return pd_truthy(v); }

/// Python's truthiness, for the places the Python package writes `x or []`.
bool pytruthy(const Json* v) {
    if (nullish(v)) return false;
    switch (v->type()) {
        case Json::Type::Bool: return v->as_bool();
        case Json::Type::Int: return v->as_int() != 0;
        case Json::Type::Float: return v->as_double() != 0;
        case Json::Type::String: return !v->as_string().empty();
        case Json::Type::Array: return !v->arr().empty();
        case Json::Type::Object: return !v->obj().empty();
        default: return true;
    }
}

/// `String(v)`, with `undefined` written as JavaScript writes it.
std::string text_of(const Json* v) { return pd_js_str(v); }

/// `String(v)` as a JSON value: a string as it is (shared), anything else written out.
Json text_json(const Json* v) { return v && v->is_string() ? *v : Json(text_of(v)); }

/// `v ?? fallback`.
Json nz(const Json* v, Json fallback) { return nullish(v) ? std::move(fallback) : *v; }

/// The name of the Julia type a model file's value is held as, for a refusal.
std::string julia_type(const Json& v) {
    switch (v.type()) {
        case Json::Type::Null: return "Nothing";
        case Json::Type::Bool: return "Bool";
        case Json::Type::Int: return "Int64";
        case Json::Type::Float: return "Float64";
        case Json::Type::String: return "String";
        case Json::Type::Array: return "Vector{Any}";
        case Json::Type::Object: return "OrderedCollections.OrderedDict{String, Any}";
    }
    return "Any";
}

/// What Python's `for x in v` walks: a list's items, a string's characters, a dictionary's keys.
std::vector<Json> iter(const Json& v) {
    std::vector<Json> out;
    if (v.is_array()) {
        out = v.arr();
    } else if (v.is_string()) {
        for (std::string& c : julia_chars(v.as_string())) out.emplace_back(std::move(c));
    } else if (v.is_object()) {
        for (const auto& item : v.obj()) out.emplace_back(item.first);
    } else {
        throw ArgumentError("'" + julia_type(v) + "' is not a list");
    }
    return out;
}

/// Python's `int(x)`: a whole number as it is, a float truncated, text read as an integer.
long long pyint(const Json& x) {
    switch (x.type()) {
        case Json::Type::Int: return x.as_int();
        case Json::Type::Bool: return x.as_bool() ? 1 : 0;
        case Json::Type::Float: return jl_to_int(std::trunc(x.as_double()));
        case Json::Type::String: {
            std::string_view s = jl_strip(x.as_string());   // Julia's `strip`: what its `isspace` calls white
            if (s.empty()) throw ArgumentError("input string is empty or only contains whitespace");
            std::size_t k = 0;
            bool negative = false;
            if (s[0] == '+' || s[0] == '-') negative = s[k++] == '-';
            if (k == s.size()) throw ArgumentError("premature end of integer: \"" + std::string(s) + "\"");
            unsigned long long v = 0;
            const unsigned long long most = negative ? 9223372036854775808ULL : 9223372036854775807ULL;
            for (; k < s.size(); k++) {
                if (!(s[k] >= '0' && s[k] <= '9'))
                    throw ArgumentError(std::string("invalid base 10 digit '") + s[k] + "' in \"" + std::string(s) + "\"");
                const unsigned d = static_cast<unsigned>(s[k] - '0');
                if (v > (most - d) / 10) throw JuliaError("OverflowError", "OverflowError: overflow parsing \"" + std::string(s) + "\"");
                v = 10 * v + d;
            }
            return negative ? static_cast<long long>(0ULL - v) : static_cast<long long>(v);
        }
        default: throw ArgumentError("'" + julia_string(x) + "' is not a whole number");
    }
}

/// What a name has to be before it can be a link (`linkName`): a slash is the one character
/// HDF5 keeps for itself, and is replaced by U+2044.
std::string link_name(const Json* s) {
    std::string out = (s && s->is_string()) ? s->as_string() : nullish(s) ? std::string() : pd_js_str(*s);
    if (out.find('/') != std::string::npos) {
        std::string r;
        for (char c : out) {
            if (c == '/') r += "\xe2\x81\x84";
            else r.push_back(c);
        }
        out = std::move(r);
    }
    std::string_view t = pd_js_trim(out);
    if (t.empty() || t == "." || t == "..") return "_";
    return std::string(t);
}
std::string link_name(std::string_view s) {
    const Json j(s);
    return link_name(&j);
}

/// Puts `node` at `path`, numbering the last name past one already taken. Only the last name is
/// numbered: a path that runs through a dataset (a block `NearField` written before a series
/// of `NearField.Flux`) is refused after 998 tries, the whole file with it, as in the Julia
/// package -- the other order is written, `NearField (2)` beside the group.
void place(H5Group& root, const std::vector<std::string>& path, const H5Ptr& node) {
    try {
        h5_put(root, path, node);
    } catch (const HDF5Error&) {
        std::vector<std::string> numbered = path;
        for (int n = 2; n <= 999; n++) {
            numbered.back() = path.back() + " (" + std::to_string(n) + ")";
            try {
                h5_put(root, numbered, node);
                return;
            } catch (const HDF5Error&) {
                // keep counting
            }
        }
        throw;
    }
}

/// Julia's `==` between an integer and a float: exact.
bool int_equals_float(long long i, double d) {
    if (!(d == d) || d != std::trunc(d) || d < -9223372036854775808.0 || d >= 9223372036854775808.0) return false;
    return static_cast<long long>(d) == i;
}

/// Julia's `==` of two numbers (a boolean is 0 or 1 there).
bool numbers_equal(const Json& a, const Json& b) {
    auto whole = [](const Json& v, long long& i) {
        if (v.is_bool()) return i = v.as_bool() ? 1 : 0, true;
        if (v.is_int()) return i = v.as_int(), true;
        return false;
    };
    long long ia = 0, ib = 0;
    const bool wa = whole(a, ia), wb = whole(b, ib);
    if (wa && wb) return ia == ib;
    if (wa) return int_equals_float(ia, b.as_double());
    if (wb) return int_equals_float(ib, a.as_double());
    return a.as_double() == b.as_double();
}

bool is_numeric(const Json& v) { return v.is_bool() || v.is_number(); }

/// Julia's `a == b` for the values a model file holds, true only where Julia's is `true`:
/// numbers by value (a boolean as 0 or 1, NaN never), text by its bytes, lists item by item,
/// dictionaries key by key whatever their order.
bool julia_equal(const Json& a, const Json& b) {
    if (a.is_null() || b.is_null()) return a.is_null() && b.is_null();
    if (is_numeric(a) || is_numeric(b)) return is_numeric(a) && is_numeric(b) && numbers_equal(a, b);
    if (a.is_string() || b.is_string()) return a.is_string() && b.is_string() && a.as_string() == b.as_string();
    if (a.is_array() && b.is_array()) {
        if (a.size() != b.size()) return false;
        for (std::size_t k = 0; k < a.size(); k++)
            if (!julia_equal(a[k], b[k])) return false;
        return true;
    }
    if (a.is_object() && b.is_object()) {
        if (a.same(b)) return true;
        if (a.obj().size() != b.obj().size()) return false;
        for (const auto& [k, v] : a.obj()) {
            const Json* w = b.obj().find(k);
            if (!w || !julia_equal(*w, v)) return false;
        }
        return true;
    }
    return false;
}

/// `a === b` for the values a descriptor holds.
bool strictly_equal(const Json& a, const Json& b) {
    if (a.is_string() || b.is_string()) return a.is_string() && b.is_string() && a.as_string() == b.as_string();
    if (a.is_bool() || b.is_bool()) return a.is_bool() && b.is_bool() && a.as_bool() == b.as_bool();
    if (a.is_number() && b.is_number()) return numbers_equal(a, b);
    return a.same(b);
}

/// A value as a key the way Julia's `Dict{Any}` tells keys apart (`isequal`): text by its
/// bytes, numbers by value (1, 1.0 and true one key; -0.0 not 0; NaN one key).
std::string label_key(const Json* v) {
    if (nullish(v)) return "n";
    switch (v->type()) {
        case Json::Type::String: return "s" + v->as_string();
        case Json::Type::Bool: return std::string("i") + (v->as_bool() ? "1" : "0");
        case Json::Type::Int: return "i" + std::to_string(v->as_int());
        case Json::Type::Float: {
            const double d = v->as_double();
            if (d == std::trunc(d) && !(d == 0 && std::signbit(d)) && d >= -9223372036854775808.0 && d < 9223372036854775808.0)
                return "i" + std::to_string(static_cast<long long>(d));
            if (d != d) return "dnan";
            std::uint64_t u;
            std::memcpy(&u, &d, 8);
            return "d" + std::to_string(u);
        }
        default: return "j" + json_text(*v, 0);
    }
}

/// Where one series goes, and which dimension its group carries (`pathOf`); a null dimension
/// for none.
struct PathOf {
    std::vector<std::string> parts;
    Json leaf_dim;
};

PathOf path_of(const Json& o) {
    static const Json value_word("value");
    const Json* block = get(o, "block");
    if (nullish(block)) block = get(o, "label");
    if (nullish(block)) block = &value_word;
    const std::string text = block->is_string() ? block->as_string() : pd_js_str(*block);
    PathOf out;
    if (text.find('.') != std::string::npos) {
        std::size_t start = 0;
        while (true) {
            const std::size_t dot = text.find('.', start);
            out.parts.push_back(link_name(std::string_view(text).substr(start, dot == std::string::npos ? std::string::npos : dot - start)));
            if (dot == std::string::npos) break;
            start = dot + 1;
        }
    } else {
        out.parts.push_back(link_name(std::string_view(text)));
    }
    const Json* dims = get(o, "dims");
    const Json* index = get(o, "index");
    if (nullish(dims) || nullish(index)) return out;
    const std::vector<Json> ds = iter(*dims);
    const std::vector<Json> ix = iter(*index);
    if (ds.empty() || ix.empty()) return out;
    // The nuclide is the leaf when there is one; otherwise the last dimension.
    std::size_t leaf = ix.size() - 1;
    const Json* nuclide = get(o, "nuclide");
    if (!nullish(nuclide))
        for (std::size_t i = 0; i < ix.size(); i++)
            if (strictly_equal(ix[i], *nuclide)) {
                leaf = i;
                break;
            }
    for (std::size_t i = 0; i < ix.size(); i++)
        if (i != leaf) out.parts.push_back(link_name(&ix[i]));
    out.parts.push_back(link_name(&ix[leaf]));
    out.leaf_dim = leaf < ds.size() ? ds[leaf] : Json();
    return out;
}

/// `column(i)[0]` as a double: NaN where there is none.
double first_of(const std::vector<double>& values) { return values.empty() ? NaN : values[0]; }

/// `sample.of === 'mean' ? 'mean' : Number(sample.of)`.
Json realisation_of(const std::optional<Json>& of) {
    if (!of) return Json(NaN);
    if (of->is_string() && of->as_string() == "mean") return Json("mean");
    return Json(pd_to_number(*of));
}

/// The model as a dictionary: the one given, or an empty one for anything else.
Json project_dict(const Json& model) { return model.is_object() ? model : Json::object(); }

void set_local(std::tm& tm, std::time_t when) {
#if defined(_WIN32)
    localtime_s(&tm, &when);
#else
    localtime_r(&when, &tm);
#endif
}

std::string stamp_of(int year, int month, int day, int hour, int minute, int second) {
    char buf[64];
    std::snprintf(buf, sizeof buf, "%d-%02d-%02d %02d:%02d:%02d", year, month, day, hour, minute, second);
    return buf;
}

std::string stamp_of(const std::tm& tm) { return stamp_of(tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday, tm.tm_hour, tm.tm_min, tm.tm_sec); }

// What a group of one block's series says about them, set on the group's own attributes in
// place: said once per group, the same way every time, so that two series of one block cannot
// disagree about what the group is.
void group_attrs(H5Attrs& a, const Json& leaf_dim, bool still, bool probabilistic, const Json& unit, const Json& block) {
    const Json* before = a.find("unit");
    Json group_unit = (before == nullptr || julia_equal(*before, unit)) ? unit : Json("");
    a.set("IndexLists", Json::array({leaf_dim}));
    a.set("time_dependent", Json(!still));
    a.set("probabilistic", Json(probabilistic));
    a.set("unit", std::move(group_unit));
    a.set("block", block);
}

std::shared_ptr<const std::vector<std::string>> names_of(std::initializer_list<const char*> names) {
    auto v = std::make_shared<std::vector<std::string>>();
    for (const char* n : names) v->emplace_back(n);
    return v;
}

[[noreturn]] void bounds_error(std::size_t length, long long at) {
    throw JuliaError("BoundsError", "BoundsError: attempt to access " + std::to_string(length) + "-element Vector at index [" + std::to_string(at) + "]");
}

/// numpy's pairwise sum of `a[lo, lo + n)` (`pairwise_sum` in its loops), which is what
/// `sum(axis=0)` does down a single column.
double pairwise_sum(const std::vector<double>& a, std::size_t lo, std::size_t n) {
    if (n < 8) {
        double res = 0.0;
        for (std::size_t i = 0; i < n; i++) res += a[lo + i];
        return res;
    }
    if (n <= 128) {
        double r1 = a[lo], r2 = a[lo + 1], r3 = a[lo + 2], r4 = a[lo + 3];
        double r5 = a[lo + 4], r6 = a[lo + 5], r7 = a[lo + 6], r8 = a[lo + 7];
        std::size_t i = 8;
        while (i < n - (n % 8)) {
            r1 += a[lo + i]; r2 += a[lo + i + 1]; r3 += a[lo + i + 2]; r4 += a[lo + i + 3];
            r5 += a[lo + i + 4]; r6 += a[lo + i + 5]; r7 += a[lo + i + 6]; r8 += a[lo + i + 7];
            i += 8;
        }
        double res = ((r1 + r2) + (r3 + r4)) + ((r5 + r6) + (r7 + r8));
        while (i < n) res += a[lo + i++];
        return res;
    }
    std::size_t n2 = n / 2;
    n2 -= n2 % 8;
    return pairwise_sum(a, lo, n2) + pairwise_sum(a, lo + n2, n - n2);
}

/// The mean of each column of an `n x cols` matrix over the rows that are finite there, NaN
/// where none is -- summed as numpy sums `np.where(finite, m, 0).sum(axis=0)`: down the rows
/// one at a time, or pairwise when there is one column.
template <class At>
std::vector<double> finite_mean(std::size_t n, std::size_t cols, At at) {
    std::vector<double> out(cols);
    if (cols == 1) {
        std::vector<double> xs(n);
        long long count = 0;
        for (std::size_t i = 0; i < n; i++) {
            const double v = at(i, 0);
            const bool finite = std::isfinite(v);
            xs[i] = finite ? v : 0.0;
            count += finite;
        }
        const double total = 0.0 + pairwise_sum(xs, 0, n);
        out[0] = count > 0 ? total / static_cast<double>(std::max<long long>(count, 1)) : NaN;
        return out;
    }
    for (std::size_t j = 0; j < cols; j++) {   // each column summed from its first row down
        double total = 0.0;
        long long count = 0;
        for (std::size_t i = 0; i < n; i++) {
            const double v = at(i, j);
            if (std::isfinite(v)) {
                total += v;
                count += 1;
            }
        }
        out[j] = count > 0 ? total / static_cast<double>(std::max<long long>(count, 1)) : NaN;
    }
    return out;
}

/// Python's `str(v)`, for the labels the Python package builds with an f-string.
std::string pystr(const Json& v) {
    switch (v.type()) {
        case Json::Type::String: return v.as_string();
        case Json::Type::Null: return "None";
        case Json::Type::Bool: return v.as_bool() ? "True" : "False";
        case Json::Type::Int: return std::to_string(v.as_int());
        case Json::Type::Float: {
            const double x = v.as_double();
            if (std::isnan(x)) return "nan";
            if (std::isinf(x)) return x > 0 ? "inf" : "-inf";
            if (x == 0) return std::signbit(x) ? "-0.0" : "0.0";
            const std::string sign = x < 0 ? "-" : "";
            auto [digits, decpt] = shortest_digits(std::fabs(x));
            const int k = static_cast<int>(digits.size());
            if (decpt <= -4 || decpt > 16) {
                const std::string mant = k == 1 ? digits : digits.substr(0, 1) + "." + digits.substr(1);
                const int e = decpt - 1;
                std::string exp = std::to_string(std::abs(e));
                if (exp.size() < 2) exp = "0" + exp;
                return sign + mant + "e" + (e < 0 ? "-" : "+") + exp;
            }
            if (decpt <= 0) return sign + "0." + std::string(static_cast<std::size_t>(-decpt), '0') + digits;
            if (decpt >= k) return sign + digits + std::string(static_cast<std::size_t>(decpt - k), '0') + ".0";
            return sign + digits.substr(0, static_cast<std::size_t>(decpt)) + "." + digits.substr(static_cast<std::size_t>(decpt));
        }
        default: return julia_string(v);
    }
}

/// A curve on one time axis, read onto another (the page's `ontoAxis`): linear between the
/// first axis's points, NaN outside its span, and the curve itself where the two are the same
/// times.
struct OntoAxis {
    bool same = false;
    std::vector<std::size_t> idx;
    std::vector<double> w;

    OntoAxis(const std::vector<double>& a_t, const std::vector<double>& b_t) {
        if (a_t == b_t) {
            same = true;
            return;
        }
        const std::size_t nb = b_t.size();
        idx.assign(nb, 0);
        w.assign(nb, 0.0);
        if (nb > 0 && a_t.empty()) bounds_error(0, 1);
        std::size_t k = 0;
        const std::size_t last = a_t.empty() ? 0 : a_t.size() - 1;
        for (std::size_t j = 0; j < nb; j++) {
            const double x = b_t[j];
            while (k + 1 < a_t.size() && a_t[k + 1] < x) k++;
            idx[j] = k;
            const double a = a_t[k], b = a_t[std::min(k + 1, last)];
            w[j] = (x < a_t[0] || x > a_t[last]) ? NaN : (b > a ? (x - a) / (b - a) : 0.0);
        }
    }

    std::vector<double> operator()(std::vector<double> v) const {
        if (same) return v;
        std::vector<double> out(idx.size());
        for (std::size_t j = 0; j < idx.size(); j++) {
            const std::size_t i = idx[j];
            if (i >= v.size()) bounds_error(v.size(), static_cast<long long>(i) + 1);
            const double a = v[i];
            const double b = v[std::min(i + 1, v.size() - 1)];
            out[j] = a + (b - a) * w[j];
        }
        return out;
    }
};

/// The scenario list's name, as the page finds it: the model's list marked as the scenario
/// list, `Scenarios` where there is none.
Json scenario_list_name(const Json& model, const Results& r) {
    auto marked = [](const Json* lists) -> std::optional<Json> {
        if (!pytruthy(lists)) return std::nullopt;
        for (const Json& lst : iter(*lists))
            if (lst.is_object() && truthy(get(lst, "for_scenarios"))) return nz(get(lst, "name"), Json());
        return std::nullopt;
    };
    if (auto found = marked(get(model, "index_lists"))) return *found;
    if (r.project)
        if (auto found = marked(&r.project->index_lists)) return *found;
    return Json("Scenarios");
}

void write_file(const std::string& path, const std::string& bytes) {
    std::ofstream out(path, std::ios::binary);
    if (!out) throw std::runtime_error("Cannot write " + path);
    out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    if (!out) throw std::runtime_error("Cannot write " + path);
}

/// `/time` less an origin, and nothing else.
void shift_time(H5Group& root, double origin) {
    if (origin == 0) return;
    auto* stamp = dynamic_cast<H5Dataset*>(root.child("time"));
    if (stamp == nullptr) return;
    if (auto* d = std::get_if<std::vector<double>>(&stamp->data)) {
        for (double& x : *d) x = x - origin;
    }
}

}  // namespace

// --- stamps and the description -----------------------------------------------------------------

Stamp Stamp::local(int year, int month, int day, int hour, int minute, int second) {
    Stamp s;
    s.kind = Kind::Local;
    s.year = year, s.month = month, s.day = day, s.hour = hour, s.minute = minute, s.second = second;
    return s;
}

Stamp Stamp::epoch(double seconds) {
    Stamp s;
    s.kind = Kind::Epoch;
    s.seconds = seconds;
    return s;
}

std::string stamp_text(const Stamp& when) {
    std::tm tm{};
    switch (when.kind) {
        case Stamp::Kind::Now: set_local(tm, std::time(nullptr)); return stamp_of(tm);
        case Stamp::Kind::Local: return stamp_of(when.year, when.month, when.day, when.hour, when.minute, when.second);
        case Stamp::Kind::Epoch: {
            // As Python's `datetime.fromtimestamp` splits it: whole seconds and microseconds
            // rounded half to even, a full second carried.
            const double x = when.seconds;
            if (!std::isfinite(x)) throw JuliaError("InexactError", "InexactError: Int64(" + js_text(x) + ")");
            double ip = std::trunc(x);
            const double fp = std::nearbyint((x - ip) * 1e6);
            if (fp >= 1e6) ip += 1;
            else if (fp < 0) ip -= 1;
            set_local(tm, static_cast<std::time_t>(std::floor(ip)));
            return stamp_of(tm);
        }
    }
    return "";
}

std::optional<Stamp> parse_stamp(const std::string& text) {
    int y, mo, d, h = 0, mi = 0, s = 0;
    char sep = 0;
    int used = 0;
    if (std::sscanf(text.c_str(), "%d-%d-%d%c%d:%d:%d%n", &y, &mo, &d, &sep, &h, &mi, &s, &used) == 7 && (sep == ' ' || sep == 'T') &&
        used == static_cast<int>(text.size()))
        return Stamp::local(y, mo, d, h, mi, s);
    used = 0;
    if (std::sscanf(text.c_str(), "%d-%d-%d%n", &y, &mo, &d, &used) == 3 && used == static_cast<int>(text.size())) return Stamp::local(y, mo, d);
    char* end = nullptr;
    const double seconds = std::strtod(text.c_str(), &end);
    if (!text.empty() && end == text.c_str() + text.size() && std::isfinite(seconds)) return Stamp::epoch(seconds);
    return std::nullopt;
}

std::optional<std::string> description_html(const Json& text) {
    const std::string s = text.is_null() ? std::string() : pd_js_str(text);
    std::string lines;
    lines.reserve(s.size());
    for (std::size_t i = 0; i < s.size(); i++) {
        if (s[i] == '\r') {
            lines.push_back('\n');
            if (i + 1 < s.size() && s[i + 1] == '\n') i++;
        } else {
            lines.push_back(s[i]);
        }
    }
    const std::string_view clean = pd_js_trim(lines);
    if (clean.empty()) return std::nullopt;
    std::string out;
    auto paragraph = [&](std::string_view p) {
        out += "<p>";
        for (char c : p) {
            switch (c) {
                case '&': out += "&amp;"; break;
                case '<': out += "&lt;"; break;
                case '>': out += "&gt;"; break;
                case '\n': out += "<br>"; break;
                default: out.push_back(c);
            }
        }
        out += "</p>";
    };
    // Paragraphs are parted by two newlines or more.
    std::size_t start = 0, i = 0;
    while (i < clean.size()) {
        if (clean[i] != '\n') {
            i++;
            continue;
        }
        std::size_t j = i;
        while (j < clean.size() && clean[j] == '\n') j++;
        if (j - i >= 2) {
            paragraph(clean.substr(start, i - start));
            start = j;
        }
        i = j;
    }
    paragraph(clean.substr(start));
    return out;
}

// --- a run's tree ----------------------------------------------------------------------------------

std::shared_ptr<H5Group> result_tree(const std::vector<double>& t, const std::vector<Json>& outputs, const ColumnFunction& column,
                                     const std::vector<std::size_t>& which, const Json& model, const Json& index_lists, const Stamp& now,
                                     const TreeRealisations* realisations, const TreeSample* sample) {
    const Json project = project_dict(model);
    const Json sim = nz(get(project, "simulation"), Json::object());
    const Json time_unit = nz(get(sim, "time_unit"), Json("year"));
    const Json created(stamp_text(now));
    std::optional<Json> iterations;   // undefined unless the realisations say
    if (realisations) iterations = realisations->iterations;
    const Json* name = get(project, "name");
    const bool probabilistic = realisations != nullptr;
    H5Attrs attrs{
        {"model", nullish(name) ? Json("model") : *name},
        {"created_time", created},
        {"source", Json("Kompartment")},
        {"time_unit", time_unit},
        {"start_time", Json(pd_to_number(nz(get(sim, "start_time"), Json(0))))},
        {"end_time", Json(pd_to_number(nz(get(sim, "end_time"), Json(0))))},
        {"solver", Json(pd_js_str(nz(get(sim, "solver"), Json(""))))},
        {"series", Json(static_cast<long long>(which.size()))},
        {"probabilistic", Json(probabilistic)},
    };
    if (probabilistic) attrs.set("n_iter", iterations ? *iterations : Json());
    const bool sampled = sample != nullptr;
    if (sampled) {
        attrs.set("n_iter", sample->iterations ? *sample->iterations : Json());
        attrs.set("realisation", realisation_of(sample->of));
    }
    const Json* description = get(project, "description");
    std::optional<std::string> information = description_html(nullish(description) ? Json() : *description);
    attrs.set("Information", information ? Json(*information) : Json());
    auto root = h5_group(std::move(attrs));

    // `probabilistic` on /time is whether the *time axis* is a matrix, which it never is:
    // every realisation is reported on the one output grid.
    h5_put(*root, {"time"},
           h5_dataset(t, H5Type::F64, H5Attrs{{"unit", time_unit}, {"created_time", created}, {"name", Json("time")}, {"probabilistic", Json(false)}}));

    // The index lists, whole: the members of a dimension and their order, and only the
    // members that are switched on. An index may be the bare string a file wrote it as, and
    // that string is its name.
    if (index_lists.is_array()) {
        for (const Json& lst : index_lists.arr()) {
            const Json* indices = get(lst, "indices");
            std::vector<Json> names;
            if (truthy(indices)) {
                for (const Json& i : iter(*indices)) {
                    if (i.is_null()) continue;
                    if (i.is_object() || i.is_array()) {
                        const Json* enabled = get(i, "enabled");
                        if (enabled && enabled->is_bool() && !enabled->as_bool()) continue;
                        const Json* nm = get(i, "name");
                        if (!nullish(nm)) names.push_back(*nm);
                    } else {
                        names.push_back(i);
                    }
                }
            } else {
                const Json* elements = get(lst, "elements");
                if (!nullish(elements))
                    for (const Json& e : iter(*elements))
                        if (!e.is_null()) names.push_back(e);
            }
            if (names.empty()) continue;
            Json members = Json::array();
            for (const Json& e : names) members.push(text_json(&e));
            const Json* list_name = get(lst, "name");
            const long long count = static_cast<long long>(members.size());
            place(*root, {"IndexLists", link_name(list_name)},
                  h5_dataset(std::move(members), H5Type::STR, H5Attrs{{"name", nz(list_name, Json())}, {"members", Json(count)}}));
        }
    }

    const Json n_iter = (iterations && !iterations->is_null()) ? *iterations : Json(0);
    static const auto keys_plain = names_of({"unit", "time_dependent", "probabilistic", "kind", "block", "name", "index", "created_time"});
    static const auto keys_matrix =
        names_of({"unit", "time_dependent", "probabilistic", "n_iter", "kind", "block", "name", "index", "created_time"});
    static const auto keys_sample =
        names_of({"unit", "time_dependent", "probabilistic", "n_iter", "realisation", "kind", "block", "name", "index", "created_time"});
    Json sample_n, sample_of;
    if (sampled) {
        sample_n = sample->iterations ? *sample->iterations : Json();
        sample_of = realisation_of(sample->of);
    }
    for (std::size_t i : which) {
        if (i >= outputs.size()) bounds_error(outputs.size(), static_cast<long long>(i) + 1);
        const Json& o = outputs[i];
        PathOf where = path_of(o);
        // Every run of it, where there is one, as float32: a Monte Carlo sample does not need
        // the digits, and Ecolego writes its own series so.
        std::optional<std::vector<float>> matrix;
        if (probabilistic && realisations->matrix_for) matrix = realisations->matrix_for(i);
        const Json* td = get(o, "timeDependent");
        const bool still = td && td->is_bool() && !td->as_bool();
        std::vector<double> values;
        if (matrix) {
            if (still && static_cast<double>(matrix->size()) > pd_to_number(n_iter)) {
                const long long k = pyint(n_iter);
                const long long keep = k >= 0 ? k : std::max(static_cast<long long>(matrix->size()) + k, 0LL);
                matrix->resize(static_cast<std::size_t>(keep));
            }
        } else {
            values = still ? std::vector<double>{first_of(column(i))} : column(i);
        }
        const Json* u = get(o, "unit");
        const Json unit = truthy(u) ? *u : Json("");
        const Json* label = get(o, "label");
        const Json block_given = nz(get(o, "block"), Json(""));
        const Json block = text_json(&block_given);
        // The names are the same for every series of a shape, so the series share one vector
        // of them (copied should one change) and each has only its values: unit,
        // time_dependent, probabilistic, [n_iter, [realisation]], kind, block, name, index,
        // created_time.
        std::vector<Json> vals;
        vals.reserve(10);
        vals.push_back(unit);
        vals.push_back(Json(!still));
        vals.push_back(Json(matrix.has_value()));
        if (matrix) {
            vals.push_back(iterations ? *iterations : Json());
        } else if (sampled) {
            vals.push_back(sample_n);
            vals.push_back(sample_of);
        }
        const Json* kind = get(o, "kind");
        vals.push_back(nullish(kind) ? Json("") : text_json(kind));
        vals.push_back(block);
        vals.push_back(label ? *label : Json());
        // What the browser writes as the column heading of this series.
        vals.push_back(Json::array({label ? *label : Json(NaN)}));
        vals.push_back(created);
        H5Attrs node_attrs(matrix ? keys_matrix : sampled ? keys_sample : keys_plain, std::move(vals));
        std::shared_ptr<H5Dataset> node;
        if (matrix) {
            std::optional<std::vector<Json>> dims;
            if (!still) {
                if (!iterations) {
                    // Julia's `undefined` multiplies out to NaN, which no count is.
                    throw HDF5Error("A " + js_number(static_cast<long long>(t.size())) + "\xc3\x97undefined dataset holds NaN values and was given " +
                                    std::to_string(matrix->size()));
                }
                dims = std::vector<Json>{Json(static_cast<long long>(t.size())), *iterations};
            }
            node = h5_dataset(std::move(*matrix), H5Type::F32, std::move(node_attrs), std::move(dims));
        } else {
            node = h5_dataset(std::move(values), H5Type::F64, std::move(node_attrs));
        }
        place(*root, where.parts, node);
        if (!truthy(&where.leaf_dim)) continue;
        H5Node* holder = root.get();
        for (std::size_t k = 0; k + 1 < where.parts.size() && holder != nullptr; k++)
            holder = holder->is_group() ? static_cast<H5Group*>(holder)->child(where.parts[k]) : nullptr;
        if (holder == nullptr || !holder->is_group()) continue;
        group_attrs(holder->attrs, where.leaf_dim, still, node->dt == H5Type::F32, unit, block);
    }
    return root;
}

std::vector<std::size_t> which_outputs(const std::vector<Json>& outputs, const std::optional<std::vector<Json>>& which) {
    std::vector<std::size_t> out;
    if (!which) {
        out.reserve(outputs.size());
        for (std::size_t k = 0; k < outputs.size(); k++) out.push_back(k);
        return out;
    }
    // Where each label is first: a large model reports hundreds of thousands of series. An
    // output given as itself is found by its label, which finds it or an earlier one of the
    // same label.
    std::unordered_map<std::string, std::size_t> first;
    bool indexed = false;
    auto index_labels = [&] {
        if (indexed) return;
        indexed = true;
        for (std::size_t j = 0; j < outputs.size(); j++) {
            const Json& o = outputs[j];
            first.emplace(label_key(o.is_object() ? get(o, "label") : nullptr), j);
        }
    };
    auto position = [&](long long k) {
        if (k < 1 || k > static_cast<long long>(outputs.size())) bounds_error(outputs.size(), k);
        out.push_back(static_cast<std::size_t>(k - 1));
    };
    for (const Json& w : *which) {
        if (w.is_string() || w.is_object()) {
            index_labels();
            const Json* label = w.is_string() ? &w : get(w, "label");
            auto it = first.find(label_key(label));
            std::optional<std::size_t> k;
            if (it != first.end()) k = it->second;
            if (!k && w.is_object())
                for (std::size_t j = 0; j < outputs.size(); j++)
                    if (outputs[j].same(w)) {
                        k = j;
                        break;
                    }
            if (!k) throw ArgumentError("No output labelled '" + (nullish(label) ? std::string("nothing") : julia_string(*label)) + "'");
            out.push_back(*k);
        } else if (w.is_int() || w.is_bool()) {
            position(w.is_bool() ? (w.as_bool() ? 1 : 0) : w.as_int());
        } else {
            position(pyint(w));
        }
    }
    return out;
}

std::shared_ptr<H5Group> results_tree(Results& res, const ResultsTreeOptions& options) {
    const std::vector<Json>& outs = res.outputs();
    const std::vector<std::size_t> chosen = which_outputs(outs, options.which);
    const Json model = options.model ? *options.model : options.project ? options.project->raw : res.project ? res.project->raw : Json();
    Json lists = Json::array();
    if (options.index_lists) lists = *options.index_lists;
    else if (res.project && pytruthy(&res.project->index_lists)) lists = res.project->index_lists;
    if (options.column) return result_tree(res.t, outs, options.column, chosen, model, lists, options.now, options.realisations, options.sample);
    // The run's own series, worked out in one pass; each handed over at the last time it is
    // asked for.
    std::vector<std::size_t> wanted;
    std::unordered_map<std::size_t, std::size_t> asked;
    for (std::size_t k : chosen)
        if (asked[k]++ == 0) wanted.push_back(k);
    std::unordered_map<std::size_t, std::vector<double>> cache;
    if (!wanted.empty()) {
        std::vector<Json> wo;
        wo.reserve(wanted.size());
        for (std::size_t k : wanted) wo.push_back(outs[k]);
        std::vector<std::vector<double>> cols = res.series_many(wo);
        for (std::size_t j = 0; j < wanted.size(); j++) cache.emplace(wanted[j], std::move(cols[j]));
    }
    ColumnFunction column = [&](std::size_t i) -> std::vector<double> {
        auto it = cache.find(i);
        if (it == cache.end()) return res.series(outs[i]);
        if (--asked[i] == 0) {
            std::vector<double> v = std::move(it->second);
            cache.erase(it);
            return v;
        }
        return it->second;
    };
    return result_tree(res.t, outs, column, chosen, model, lists, options.now, options.realisations, options.sample);
}

std::string write_results_hdf5(Results& res, const ResultsTreeOptions& options) { return write_hdf5(*results_tree(res, options)); }

// --- a probabilistic run ------------------------------------------------------------------------------

std::shared_ptr<H5Group> probabilistic_tree(const ProbabilisticResults& prob, const ProbabilisticTreeOptions& options) {
    const std::vector<double>& t = prob.t;
    const std::size_t times = t.size();
    std::vector<Json> described(prob.outputs.begin(), prob.outputs.end());
    // Where each series comes from: a kept series (its position) or a varied input (its row of
    // the samples, from 0).
    struct Source {
        bool input;
        std::size_t k;
    };
    std::vector<Source> source;
    for (std::size_t w = 0; w < prob.outputs.size(); w++) source.push_back({false, w});
    if (options.inputs) {
        std::unordered_set<std::string> taken;
        for (const Json& o : prob.outputs) taken.insert(label_key(get(o, "label")));
        for (const Json& inp : prob.inputs) {
            const Json o = nz(get(inp, "output"), Json());
            if (taken.count(label_key(get(o, "label")))) continue;
            const long long k = pyint(nz(get(inp, "k"), Json()));
            described.push_back(o);
            source.push_back({true, static_cast<std::size_t>(k - 1)});
        }
    }
    const std::vector<std::uint8_t>& ran = prob.ran;
    const long long n_rows = !prob.outputs.empty() ? prob.held() : static_cast<long long>(ran.size());
    const std::size_t n = static_cast<std::size_t>(std::max(0LL, n_rows));
    const std::vector<std::size_t> chosen = which_outputs(described, options.which);

    // An input's values: what was drawn for it in each realisation, NaN where one did not run.
    auto draws = [&](std::size_t j) {
        if (j >= prob.samples.inputs) bounds_error(prob.samples.inputs, static_cast<long long>(j) + 1);
        const std::size_t cols = static_cast<std::size_t>(std::max(0LL, prob.samples.realisations));
        std::vector<double> col(cols);
        for (std::size_t i = 0; i < cols; i++) col[i] = prob.samples(j, static_cast<long long>(i));
        if (ran.size() == col.size())
            for (std::size_t i = 0; i < col.size(); i++)
                if (ran[i] == 0) col[i] = NaN;
        return col;
    };
    auto still = [&](std::size_t k) {
        if (source[k].input) return true;
        const Json* td = get(described[k], "timeDependent");
        return td && td->is_bool() && !td->as_bool();
    };
    auto value = [&](std::size_t w, std::size_t i, std::size_t j) { return prob.value(w, static_cast<long long>(i), j); };

    std::optional<TreeRealisations> realisations;
    std::optional<TreeSample> sample;
    ColumnFunction column;
    const Json& want = options.want;
    if (want.is_string() && want.as_string() == "all") {
        realisations = TreeRealisations{};
        realisations->iterations = Json(static_cast<long long>(n));
        realisations->matrix_for = [&](std::size_t k) -> std::optional<std::vector<float>> {
            const Source& s = source[k];
            // An input is one value per realisation here, whatever its descriptor says, while
            // `result_tree` shapes a series by its descriptor's `timeDependent`: an input whose
            // descriptor does not say false is refused as a times x n matrix given n values. As
            // the Julia package does it; a run's inputs are parameters, which always say false.
            if (s.input) {
                std::vector<double> d = draws(s.k);
                std::vector<float> out(d.size());
                for (std::size_t i = 0; i < d.size(); i++) out[i] = static_cast<float>(d[i]);
                return out;
            }
            // Time-major: every realisation at the first time, then at the second.
            if (still(k)) {
                if (times == 0 && n > 0) bounds_error(0, 1);
                std::vector<float> out(n);
                for (std::size_t i = 0; i < n; i++) out[i] = static_cast<float>(value(s.k, i, 0));
                return out;
            }
            std::vector<float> out(n * times);
            for (std::size_t j = 0; j < times; j++)
                for (std::size_t i = 0; i < n; i++) out[j * n + i] = static_cast<float>(value(s.k, i, j));
            return out;
        };
        column = [&](std::size_t) { return std::vector<double>(times, NaN); };
    } else if (want.is_string() && want.as_string() == "mean") {
        column = [&](std::size_t k) {
            const Source& s = source[k];
            if (s.input) {
                const std::vector<double> d = draws(s.k);
                const std::vector<double> mean = finite_mean(d.size(), 1, [&](std::size_t i, std::size_t) { return d[i]; });
                return std::vector<double>(times, mean[0]);
            }
            std::vector<double> mean = finite_mean(n, times, [&](std::size_t i, std::size_t j) { return value(s.k, i, j); });
            return times == 1 ? std::vector<double>(times, mean[0]) : mean;
        };
        sample = TreeSample{Json(static_cast<long long>(n)), Json("mean")};
    } else {
        const double number = pd_to_number(want);
        const double r = std::isfinite(number) ? std::floor(number + 0.5) : 1.0;
        const long long rows = static_cast<long long>(n);
        long long one = r >= static_cast<double>(rows) ? rows : r <= 1 ? 1 : static_cast<long long>(r);
        one = std::min(rows, std::max(1LL, one));
        column = [&, one](std::size_t k) {
            const Source& s = source[k];
            if (one < 1) bounds_error(0, one);
            const std::size_t at = static_cast<std::size_t>(one - 1);
            if (s.input) {
                const std::vector<double> d = draws(s.k);
                if (at >= d.size()) bounds_error(d.size(), one);
                return std::vector<double>(times, d[at]);
            }
            std::vector<double> row(times);
            for (std::size_t j = 0; j < times; j++) row[j] = value(s.k, at, j);
            return row;
        };
        sample = TreeSample{Json(static_cast<long long>(n)), Json(one)};
    }
    // The run's own model where none is given: its name and index lists.
    Json model, lists;
    if (options.model) {
        model = *options.model;
        if (options.index_lists) {
            lists = *options.index_lists;
        } else {
            const Json* stored = get(model, "index_lists");
            lists = derive_block_lists(derive_elements(stored && stored->is_array() ? *stored : Json::array()), project_dict(model));
        }
    } else {
        const std::shared_ptr<const Project>& p = options.project ? options.project : prob.project;
        model = p ? p->raw : Json();
        lists = options.index_lists ? *options.index_lists : p ? p->index_lists : Json::array();
    }
    return result_tree(t, described, column, chosen, model, lists, options.now, realisations ? &*realisations : nullptr, sample ? &*sample : nullptr);
}

std::string write_probabilistic_hdf5(const ProbabilisticResults& prob, const ProbabilisticTreeOptions& options) {
    return write_hdf5(*probabilistic_tree(prob, options));
}

// --- scenarios side by side ------------------------------------------------------------------------------

std::shared_ptr<H5Group> scenarios_tree(std::vector<std::pair<std::string, Results>>& runs, const ScenariosTreeOptions& options) {
    if (runs.empty()) throw ArgumentError("There are no runs to write.");
    const std::string active = options.active ? *options.active : runs[0].first;
    std::size_t at = runs.size();
    for (std::size_t k = 0; k < runs.size(); k++)
        if (runs[k].first == active) {
            at = k;
            break;
        }
    if (at == runs.size()) throw ArgumentError("No run of the scenario '" + active + "'");
    Results& r = runs[at].second;
    std::vector<std::pair<std::string, Results*>> others;
    for (auto& [name, run] : runs)
        if (name != active) others.emplace_back(name, &run);
    const Json model = options.model ? *options.model : options.project ? options.project->raw : r.project ? r.project->raw : Json();
    Json lists = Json::array();
    if (options.index_lists) lists = *options.index_lists;
    else if (r.project && pytruthy(&r.project->index_lists)) lists = r.project->index_lists;
    if (others.empty()) {
        ResultsTreeOptions o;
        o.which = options.which;
        o.model = model;
        o.index_lists = lists;
        o.now = options.now;
        return results_tree(r, o);
    }
    const std::vector<Json>& outs = r.outputs();
    const std::vector<std::size_t> chosen = which_outputs(outs, options.which);
    auto label_of = [](const Json& o) -> const Json* { return o.is_object() ? get(o, "label") : nullptr; };
    std::unordered_map<std::size_t, std::vector<double>> own;
    {
        std::vector<Json> wo;
        for (std::size_t i : chosen) wo.push_back(outs[i]);
        std::vector<std::vector<double>> cols = wo.empty() ? std::vector<std::vector<double>>{} : r.series_many(wo);
        for (std::size_t j = 0; j < chosen.size(); j++) own[chosen[j]] = std::move(cols[j]);
    }
    struct Beside {
        std::string name;
        const std::vector<Json>* outs;
        std::unordered_map<std::string, std::size_t> by_label;
        std::unordered_map<std::size_t, std::vector<double>> cols;
        OntoAxis onto;
    };
    std::vector<Beside> beside;
    for (auto& [name, e] : others) {
        const std::vector<Json>& eo = e->outputs();
        std::unordered_map<std::string, std::size_t> by_label;
        for (std::size_t j = 0; j < eo.size(); j++) by_label[label_key(label_of(eo[j]))] = j;   // the last of a label
        std::vector<std::size_t> wanted;
        std::unordered_set<std::size_t> seen;
        for (std::size_t i : chosen) {
            auto it = by_label.find(label_key(label_of(outs[i])));
            if (it != by_label.end() && seen.insert(it->second).second) wanted.push_back(it->second);
        }
        std::unordered_map<std::size_t, std::vector<double>> cols;
        if (!wanted.empty()) {
            std::vector<Json> wo;
            for (std::size_t j : wanted) wo.push_back(eo[j]);
            std::vector<std::vector<double>> got = e->series_many(wo);
            for (std::size_t j = 0; j < wanted.size(); j++) cols[wanted[j]] = std::move(got[j]);
        }
        beside.push_back(Beside{name, &eo, std::move(by_label), std::move(cols), OntoAxis(e->t, r.t)});
    }
    struct Spec {
        const Json* out;
        std::string label;
        std::string scenario;
        std::vector<double> values;
    };
    std::vector<Spec> spec;
    const std::string dot = " \xc2\xb7 ";   // ·
    for (std::size_t i : chosen) {
        const Json& o = outs[i];
        const Json* lo = label_of(o);
        const std::string label = pystr(nz(lo, Json()));
        spec.push_back({&o, label + dot + pystr(Json(active)), active, own[i]});
        for (const Beside& b : beside) {
            auto it = b.by_label.find(label_key(lo));
            if (it == b.by_label.end()) continue;
            spec.push_back({&(*b.outs)[it->second], label + dot + pystr(Json(b.name)), b.name, b.onto(b.cols.at(it->second))});
        }
    }
    const Json list_name = scenario_list_name(model, r);
    std::vector<Json> souts;
    souts.reserve(spec.size());
    for (const Spec& s : spec) {
        Json d = s.out->shallow();
        const Json* dims = get(*s.out, "dims");
        const Json* index = get(*s.out, "index");
        Json nd = Json::array(), ni = Json::array();
        if (pytruthy(dims))
            for (Json& x : iter(*dims)) nd.push(std::move(x));
        nd.push(list_name);
        if (pytruthy(index))
            for (Json& x : iter(*index)) ni.push(std::move(x));
        ni.push(Json(s.scenario));
        d.set("dims", std::move(nd));
        d.set("index", std::move(ni));
        d.set("label", Json(s.label));
        souts.push_back(std::move(d));
    }
    std::vector<std::size_t> every(spec.size());
    for (std::size_t k = 0; k < spec.size(); k++) every[k] = k;
    ColumnFunction column = [&](std::size_t k) { return spec[k].values; };
    return result_tree(r.t, souts, column, every, model, lists, options.now);
}

std::string write_scenarios_hdf5(std::vector<std::pair<std::string, Results>>& runs, const ScenariosTreeOptions& options) {
    return write_hdf5(*scenarios_tree(runs, options));
}

// --- saving --------------------------------------------------------------------------------------------

bool is_hdf5_path(const std::string& path) {
    std::string low = path;
    for (char& c : low)
        if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
    for (const char* ending : {".h5", ".hdf5", ".hdf", ".he5"}) {
        const std::size_t n = std::strlen(ending);
        if (low.size() >= n && low.compare(low.size() - n, n, ending) == 0) return true;
    }
    return false;
}

std::string save_results(Results& res, const std::string& path, const SaveOptions& options) {
    std::optional<std::vector<Json>> outputs = options.which;
    if (options.blocks) {
        if (options.which) throw ArgumentError("give `blocks` or `outputs`, not both");
        outputs = std::vector<Json>{};
        for (const std::string& b : *options.blocks) {
            std::size_t found = 0;
            for (const Json& o : res.outputs())
                if (o.get("block") == b) {
                    outputs->push_back(o);
                    found++;
                }
            if (found == 0) throw ArgumentError("No series of a block '" + b + "' in this run");
        }
    }
    std::string low = path;
    for (char& c : low)
        if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
    auto ends = [&](const char* e) {
        const std::size_t n = std::strlen(e);
        return low.size() >= n && low.compare(low.size() - n, n, e) == 0;
    };
    if (is_hdf5_path(path)) {
        ResultsTreeOptions o = options;
        o.which = outputs;
        auto tree = results_tree(res, o);
        shift_time(*tree, options.time_origin);
        write_file(path, write_hdf5(*tree));
    } else if (ends(".zip")) {
        if (options.blocks || options.which || options.time_origin != 0)
            throw ArgumentError("an archive keeps the whole run: `blocks`, `outputs` and `time_origin` are for a result file or a table");
        write_file(path, dataset_archive(res, options.archive));
    } else if (ends(".csv")) {
        const bool more = options.project || options.model || options.index_lists || options.now.kind != Stamp::Kind::Now || options.column ||
                          options.realisations || options.sample;
        if (more) throw ArgumentError("a table takes only `outputs` and `time_origin`");
        std::vector<Json> chosen;
        if (outputs) {
            const std::vector<Json>& every = res.outputs();
            for (std::size_t k : which_outputs(every, outputs)) chosen.push_back(every[k]);
        }
        write_file(path, res.to_csv(outputs ? &chosen : nullptr, options.time_origin));
    } else {
        throw ArgumentError("'" + path + "': a result file ends .h5 (HDF5), .csv (the table) or .zip (the model and its run)");
    }
    return path;
}

std::string save_probabilistic(const ProbabilisticResults& prob, const std::string& path, const ProbabilisticSaveOptions& options) {
    auto tree = probabilistic_tree(prob, options);
    shift_time(*tree, options.time_origin);
    write_file(path, write_hdf5(*tree));
    return path;
}

std::string save_scenarios(std::vector<std::pair<std::string, Results>>& runs, const std::string& path, const ScenariosTreeOptions& options) {
    write_file(path, write_scenarios_hdf5(runs, options));
    return path;
}

}  // namespace kompartment
