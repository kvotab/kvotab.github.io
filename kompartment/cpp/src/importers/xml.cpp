#include "importers/xml.hpp"

#include <cmath>
#include <cstring>

#include "importers/eco_maps.hpp"

namespace kompartment::eco {

EcoXMLError::EcoXMLError(std::string message_, std::optional<std::size_t> position_)
    : std::runtime_error(position_ ? message_ + " (at character " + std::to_string(*position_) + ")" : message_),
      message(std::move(message_)),
      position(position_) {}

std::string EcoXMLError::full() const {
    return position ? message + " (at character " + std::to_string(*position) + ")" : message;
}

// --- entities --------------------------------------------------------------------------------

namespace {

// What one matched reference stands for, or none to leave it as written.
std::optional<std::string> entity(std::string_view body) {
    if (body[0] == '#') {
        const bool hex = body.size() >= 2 && (body[1] == 'x' || body[1] == 'X');
        const std::string_view digits = hex ? body.substr(2) : body.substr(1);
        const int base = hex ? 16 : 10;
        long long code = 0;
        std::size_t count = 0;
        bool big = false;
        for (char ch : digits) {
            const unsigned char b = static_cast<unsigned char>(ch);
            const int v = (b >= '0' && b <= '9') ? b - '0'
                          : (base == 16 && b >= 'a' && b <= 'f') ? b - 'a' + 10
                          : (base == 16 && b >= 'A' && b <= 'F') ? b - 'A' + 10
                                                                  : -1;
            if (v < 0) break;
            count++;
            if (!big) code = code * base + v;
            if (code > 0x10ffff) big = true;
        }
        if (count == 0) return std::nullopt;
        if (big || code > 0x10ffff) return std::nullopt;
        if (code >= 0xd800 && code <= 0xdfff) return std::nullopt;
        std::string out;
        put_char(out, static_cast<char32_t>(code));
        return out;
    }
    if (body == "amp") return std::string("&");
    if (body == "lt") return std::string("<");
    if (body == "gt") return std::string(">");
    if (body == "quot") return std::string("\"");
    if (body == "apos") return std::string("'");
    return std::nullopt;
}

}  // namespace

std::string decode_entities(std::string_view text) {
    const std::size_t n = text.size();
    std::size_t j = text.find('&');
    if (j == std::string_view::npos) return std::string(text);
    std::string out;
    out.reserve(n);
    std::size_t i = 0;   // what has been copied up to
    while (j != std::string_view::npos && j < n) {
        // Try to match `&(#x?[0-9a-fA-F]+|[a-zA-Z]+);` at j.
        std::size_t k = j + 1;
        std::size_t stop = std::string_view::npos;
        if (k < n && text[k] == '#') {
            k++;
            if (k < n && text[k] == 'x') {
                std::size_t m = k + 1;
                while (m < n && is_hex(static_cast<unsigned char>(text[m]))) m++;
                if (m > k + 1 && m < n && text[m] == ';') stop = m;
            } else {
                std::size_t m = k;
                while (m < n && is_hex(static_cast<unsigned char>(text[m]))) m++;
                if (m > k && m < n && text[m] == ';') stop = m;
            }
        } else {
            std::size_t m = k;
            while (m < n && is_alpha(static_cast<unsigned char>(text[m]))) m++;
            if (m > k && m < n && text[m] == ';') stop = m;
        }
        if (stop == std::string_view::npos) {
            j = text.find('&', j + 1);
            continue;
        }
        std::optional<std::string> replacement = entity(text.substr(j + 1, stop - j - 1));
        out.append(text.substr(i, j - i));
        if (replacement) out += *replacement;
        else out.append(text.substr(j, stop - j + 1));
        i = stop + 1;
        j = text.find('&', i);
    }
    out.append(text.substr(i));
    return out;
}

// --- the scanner -----------------------------------------------------------------------------

namespace {

struct Parser {
    XmlDoc& doc;
    const std::string& src;
    std::size_t n;
    std::vector<XmlNode*> stack;

    [[noreturn]] void fail(const std::string& message, std::size_t at) const {
        throw EcoXMLError(message, utf16_pos(src, at));
    }

    bool starts(std::size_t i, std::string_view lit) const {
        return i + lit.size() <= n && std::memcmp(src.data() + i, lit.data(), lit.size()) == 0;
    }

    bool has_amp(std::size_t a, std::size_t b) const {
        return b > a && std::memchr(src.data() + a, '&', b - a) != nullptr;
    }

    // One piece of text for the innermost open element; outside every element, text is not
    // anyone's.
    void add_piece(std::size_t a, std::size_t b, std::uint8_t kind) {
        if (stack.empty() || a >= b) return;
        XmlNode* node = stack.back();
        doc.pstart.push_back(a);
        doc.pstop.push_back(b);
        doc.pkind.push_back(kind);
        doc.pnext.push_back(0);
        const std::uint32_t k = static_cast<std::uint32_t>(doc.pstart.size());
        if (node->tfirst == 0) node->tfirst = k;
        else doc.pnext[node->tlast - 1] = k;
        node->tlast = k;
    }

    // A name, from byte i: everything up to JavaScript's white space, `/`, `>` or `=`.
    const std::string* read_name(std::size_t& i) {
        const std::size_t start = i;
        while (i < n) {
            const unsigned char b = static_cast<unsigned char>(src[i]);
            if (b < 0x80) {
                if (b == 0x2f || b == 0x3e || b == 0x3d || b == 0x20 || (b >= 0x09 && b <= 0x0d)) break;
            } else if (js_space_bytes(src, i, n) > 0) {
                break;
            }
            i++;
        }
        if (i == start) fail("Expected a name", i);
        return &*doc.names.emplace(src.substr(start, i - start)).first;
    }

    // XML's own white space, skipped between attributes.
    std::size_t skip_space(std::size_t i) const {
        while (i < n) {
            const char b = src[i];
            if (!(b == ' ' || b == '\t' || b == '\n' || b == '\r')) break;
            i++;
        }
        return i;
    }

    void run() {
        XmlNode* root = nullptr;
        std::size_t i = 0;
        while (i < n) {
            const std::size_t lt = src.find('<', i);
            if (lt == std::string::npos) {
                if (!stack.empty()) add_piece(i, n, has_amp(i, n) ? 1 : 0);
                break;
            }
            if (lt > i && !stack.empty()) add_piece(i, lt, has_amp(i, lt) ? 1 : 0);
            i = lt;

            if (starts(i, "<!--")) {
                const std::size_t e = src.find("-->", i + 4);
                if (e == std::string::npos) fail("Unterminated comment", i);
                i = e + 3;
                continue;
            }
            if (starts(i, "<![CDATA[")) {
                const std::size_t e = src.find("]]>", i + 9);
                if (e == std::string::npos) fail("Unterminated CDATA section", i);
                add_piece(i + 9, e, 2);
                i = e + 3;
                continue;
            }
            if (starts(i, "<?")) {
                const std::size_t e = src.find("?>", i + 2);
                if (e == std::string::npos) fail("Unterminated processing instruction", i);
                i = e + 2;
                continue;
            }
            if (starts(i, "<!")) {
                const std::size_t e = src.find('>', i + 2);
                if (e == std::string::npos) fail("Unterminated declaration", i);
                i = e + 1;
                continue;
            }

            if (starts(i, "</")) {
                i += 2;
                const std::string* name = read_name(i);
                i = skip_space(i);
                if (i >= n || src[i] != '>') fail("Expected '>' closing </" + *name, i);
                i += 1;
                if (stack.empty()) fail("Unexpected closing tag </" + *name + ">", i);
                XmlNode* open = stack.back();
                stack.pop_back();
                if (*open->name != *name) fail("Closing tag </" + *name + "> does not match <" + *open->name + ">", i);
                continue;
            }

            i += 1;
            const std::string* name = read_name(i);
            std::vector<std::pair<std::string, std::string>> attrs;
            bool self_closing = false;
            while (true) {
                i = skip_space(i);
                if (i >= n) fail("Unterminated tag", i);
                const char b = src[i];
                if (b == '>') {
                    i += 1;
                    break;
                }
                if (b == '/' && i + 1 < n && src[i + 1] == '>') {
                    i += 2;
                    self_closing = true;
                    break;
                }
                const std::string* attr_name = read_name(i);
                i = skip_space(i);
                if (i >= n || src[i] != '=') fail("Expected '=' after attribute '" + *attr_name + "'", i);
                i = skip_space(i + 1);
                const char quote = i < n ? src[i] : '\0';
                if (quote != '"' && quote != '\'') fail("Expected a quoted value for attribute '" + *attr_name + "'", i);
                i += 1;
                const std::size_t e = i < n ? src.find(quote, i) : std::string::npos;
                if (e == std::string::npos) fail("Unterminated value for attribute '" + *attr_name + "'", i);
                std::string value = has_amp(i, e) ? decode_entities(std::string_view(src).substr(i, e - i)) : src.substr(i, e - i);
                bool replaced = false;
                for (auto& [k, v] : attrs)
                    if (k == *attr_name) {
                        v = std::move(value);
                        replaced = true;
                        break;
                    }
                if (!replaced) attrs.emplace_back(*attr_name, std::move(value));
                i = e + 1;
            }
            XmlNode& node = doc.nodes.emplace_back();
            node.name = name;
            node.attrs = std::move(attrs);
            node.doc = &doc;
            node.self_closing = self_closing;

            if (!stack.empty()) stack.back()->children.push_back(&node);
            else if (root) fail("More than one root element", i);
            else root = &node;
            if (!self_closing) stack.push_back(&node);
        }

        if (!stack.empty()) throw EcoXMLError("Unclosed element <" + *stack.back()->name + ">", std::nullopt);
        if (!root) throw EcoXMLError("The document has no elements", std::nullopt);
        doc.root = root;
    }
};

std::string piece(const XmlDoc& d, std::uint32_t k) {
    const std::string_view s = std::string_view(d.src).substr(d.pstart[k - 1], d.pstop[k - 1] - d.pstart[k - 1]);
    return d.pkind[k - 1] == 1 ? decode_entities(s) : std::string(s);
}

}  // namespace

std::unique_ptr<XmlDoc> parse_xml(std::string src) {
    auto doc = std::make_unique<XmlDoc>();
    doc->src = std::move(src);
    Parser p{*doc, doc->src, doc->src.size(), {}};
    p.run();
    return doc;
}

// --- reading what was read -------------------------------------------------------------------

std::string text(const XmlNode& n) {
    std::uint32_t k = n.tfirst;
    if (k == 0) return "";
    const XmlDoc& d = *n.doc;
    if (k == n.tlast) return piece(d, k);
    std::string out;
    while (k != 0) {
        out += piece(d, k);
        k = d.pnext[k - 1];
    }
    return out;
}

std::string trimmed_text(const XmlNode& n) {
    const std::uint32_t k = n.tfirst;
    if (k == 0) return "";
    const XmlDoc& d = *n.doc;
    if (k == n.tlast && d.pkind[k - 1] != 1) {
        auto [a, b] = js_trim_range(d.src, d.pstart[k - 1], d.pstop[k - 1]);
        return d.src.substr(a, b - a);
    }
    return js_trim(text(n));
}

std::optional<std::string> attr(const XmlNode& n, std::string_view key) {
    for (const auto& [k, v] : n.attrs)
        if (k == key) return v;
    return std::nullopt;
}

std::string attr_or(const XmlNode& n, std::string_view key, std::string_view fallback) {
    for (const auto& [k, v] : n.attrs)
        if (k == key) return v;
    return std::string(fallback);
}

bool has_attr(const XmlNode& n, std::string_view key) {
    for (const auto& [k, v] : n.attrs)
        if (k == key) return true;
    return false;
}

const XmlNode* child(const XmlNode* node, std::string_view name) {
    if (!node) return nullptr;
    for (const XmlNode* c : node->children)
        if (*c->name == name) return c;
    return nullptr;
}

std::vector<const XmlNode*> children(const XmlNode* node, std::string_view name) {
    std::vector<const XmlNode*> out;
    if (!node) return out;
    for (const XmlNode* c : node->children)
        if (*c->name == name) out.push_back(c);
    return out;
}

std::optional<std::string> child_text(const XmlNode* node, std::string_view name) {
    const XmlNode* c = child(node, name);
    if (!c) return std::nullopt;
    std::string t = trimmed_text(*c);
    if (t.empty()) return std::nullopt;
    return t;
}

std::optional<double> child_number(const XmlNode* node, std::string_view name) {
    std::optional<std::string> t = child_text(node, name);
    if (!t) return std::nullopt;
    const double v = to_number(std::string_view(*t));
    if (!std::isfinite(v)) return std::nullopt;
    return v;
}

std::optional<bool> child_bool(const XmlNode* node, std::string_view name) {
    std::optional<std::string> t = child_text(node, name);
    if (!t) return std::nullopt;
    return py_lower(*t) == "true";
}

void walk(const XmlNode& node, const std::function<bool(const XmlNode&)>& f) {
    std::vector<const XmlNode*> stack{&node};
    while (!stack.empty()) {
        const XmlNode* el = stack.back();
        stack.pop_back();
        if (f(*el)) return;
        for (std::size_t k = el->children.size(); k > 0; k--) stack.push_back(el->children[k - 1]);
    }
}

const XmlNode* find(const XmlNode& node, std::string_view name) {
    const XmlNode* found = nullptr;
    walk(node, [&](const XmlNode& el) {
        if (*el.name == name) {
            found = &el;
            return true;
        }
        return false;
    });
    return found;
}

}  // namespace kompartment::eco
