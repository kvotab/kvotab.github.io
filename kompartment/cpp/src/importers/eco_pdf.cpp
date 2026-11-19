#include "importers/eco_pdf.hpp"

#include <cmath>
#include <limits>
#include <map>
#include <vector>

#include "importers/eco_maps.hpp"

namespace kompartment::eco {

namespace {

struct Kind {
    const char* id;
    const char* name;
    std::vector<const char*> params;
};

// The kinds a distribution can be, in the order the application lists them: each with the
// name its expression is written with and its parameters.
const std::vector<Kind>& kinds() {
    static const std::vector<Kind> k = {
        {"unif", "unif", {"min", "max"}},
        {"triang", "triang", {"min", "max", "mode"}},
        {"dtriang", "dtriang", {"min", "max", "mode"}},
        {"norm", "norm", {"mean", "sd"}},
        {"logu", "logu", {"min", "max"}},
        {"logt", "logt", {"min", "max", "mode"}},
        {"logdt", "logdt", {"min", "max", "mode"}},
        {"Logn4", "logn", {"gm", "gsd"}},
        {"logn", "logn", {"mean", "sd"}},
        {"logn5", "logn", {"p1", "x1", "p2", "x2"}},
        {"pg", "pg", {}},
    };
    return k;
}

const Kind* meta(std::string_view id) {
    for (const Kind& k : kinds())
        if (id == k.id) return &k;
    return nullptr;
}

// The bytes [a, b) of `s` trimmed, as a view.
std::string_view trim_view(std::string_view s, std::size_t a, std::size_t b) {
    if (b < a) return std::string_view();
    auto [x, y] = js_trim_range(s, a, b);
    return s.substr(x, y - x);
}

// A number, or none for nothing, an empty string or what is not a finite number.
std::optional<double> pdf_num(const std::optional<std::string_view>& v) {
    if (!v || v->empty()) return std::nullopt;
    const double n = pdf_number(*v);
    if (!std::isfinite(n)) return std::nullopt;
    return n;
}

Json num_json(const std::optional<double>& v) { return v ? Json(*v) : Json(); }

}  // namespace

double pdf_number(std::string_view s) {
    auto [a, b] = js_trim_range(s, 0, s.size());
    if (b <= a) return 0.0;
    const std::string_view t = s.substr(a, b - a);
    if (t.size() >= 3 && t[0] == '0') {
        const char p = t[1];
        const int base = (p == 'x' || p == 'X') ? 16 : (p == 'o' || p == 'O') ? 8 : (p == 'b' || p == 'B') ? 2 : 0;
        if (base != 0) {
            bool ok = true;
            for (std::size_t k = 2; k < t.size(); k++) {
                const unsigned char c = static_cast<unsigned char>(t[k]);
                const int v = is_ascii_digit(c) ? c - '0' : (c >= 'a' && c <= 'f') ? c - 'a' + 10 : (c >= 'A' && c <= 'F') ? c - 'A' + 10 : 99;
                if (v >= base) {
                    ok = false;
                    break;
                }
            }
            if (ok) return radix_to_double(t.substr(2), base);
        }
    }
    if (!is_js_decimal(t)) return std::numeric_limits<double>::quiet_NaN();
    return parse_decimal(t);
}

std::optional<Json> parse_pdf(std::string_view expr, std::string_view function_name) {
    const std::string text = js_trim(expr);
    if (text.empty()) return std::nullopt;
    // `name<spaces>(body)<spaces>` to the end: the text is trimmed, so it ends with the closing
    // bracket.
    const std::size_t n = text.size();
    auto byte = [&](std::size_t i) { return static_cast<unsigned char>(text[i]); };
    if (!(is_alpha(byte(0)) || byte(0) == '_')) return std::nullopt;
    std::size_t k = 1;
    while (k < n && is_ident_char(byte(k))) k++;
    const std::string name = text.substr(0, k);
    while (k < n) {
        const std::size_t sp = js_space_bytes(text, k, n);
        if (sp == 0) break;
        k += sp;
    }
    if (!(k < n && text[k] == '(')) return std::nullopt;
    if (!(n >= k + 2 && text[n - 1] == ')')) return std::nullopt;

    // Commas separate arguments; a list's own values are separated by `;`.
    std::map<std::string, std::string_view> args;
    std::vector<std::string> bare;
    const std::string_view tv(text);
    std::size_t p = k + 1;        // the body is bytes [k + 1, n - 1)
    const std::size_t stop = n - 1;
    while (true) {
        const std::size_t q = tv.find(',', p);
        const bool last = q == std::string_view::npos || q >= stop;
        const std::size_t e = last ? stop : q;   // this piece is [p, e)
        const std::size_t at = tv.substr(0, e).find('=', p);
        if (at == std::string_view::npos) {
            const std::string_view word = trim_view(tv, p, e);
            if (!word.empty()) bare.emplace_back(word);
        } else {
            args[std::string(trim_view(tv, p, at))] = trim_view(tv, at + 1, e);
        }
        if (last) break;
        p = q + 1;
    }
    auto get = [&](const char* key) -> std::optional<std::string_view> {
        auto it = args.find(key);
        if (it == args.end()) return std::nullopt;
        return it->second;
    };
    auto has = [&](const char* key) {
        if (args.count(key)) return true;
        for (const auto& w : bare)
            if (w == key) return true;
        return false;
    };

    std::string kind;
    if (meta(function_name)) {
        kind = std::string(function_name);
    } else if (name == "logn") {
        kind = (has("gm") || has("gsd")) ? "Logn4" : (has("p1") || has("x1")) ? "logn5" : "logn";
    } else {
        for (const Kind& m : kinds())
            if (name == m.name) {
                kind = m.id;
                break;
            }
    }
    if (kind.empty()) return std::nullopt;

    const std::optional<double> pos = pdf_num(get("pos"));
    Json params = Json::object();
    Json spec = Json::object();
    spec.set("kind", Json(kind));
    spec.set("params", params);
    spec.set("values", Json());
    spec.set("trmin", num_json(pdf_num(get("trmin"))));
    spec.set("trmax", num_json(pdf_num(get("trmax"))));
    spec.set("pmin", num_json(pdf_num(get("pmin"))));
    spec.set("pmax", num_json(pdf_num(get("pmax"))));
    {
        std::optional<std::string_view> g = get("group");
        Json group;
        if (g) {
            auto [a, b] = js_trim_range(*g, 0, g->size());
            if (b > a) group = Json(std::string(g->substr(a, b - a)));
        }
        spec.set("group", group);
    }
    {
        std::optional<std::string_view> inorder = get("inorder");
        spec.set("inorder", Json(!(inorder && *inorder == "false")));
    }
    spec.set("pos", pos ? Json(*pos) : Json(0));
    for (const char* name_ : meta(kind)->params) params.set(name_, num_json(pdf_num(get(name_))));
    if (kind == "pg") {
        std::vector<double> values;
        std::optional<std::string_view> raw = get("values");
        if (raw && !raw->empty()) {
            std::size_t a = 0;
            const std::size_t b = raw->size();
            while (true) {
                const std::size_t q = raw->find(';', a);
                const std::size_t end = q == std::string_view::npos ? b : q;
                const double v = pdf_number(raw->substr(a, end - a));
                if (std::isfinite(v)) values.push_back(v);
                if (q == std::string_view::npos) break;
                a = q + 1;
            }
        }
        spec.set("values", Json::array(values));
    }
    return spec;
}

}  // namespace kompartment::eco
