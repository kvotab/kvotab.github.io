#include "io/hdf5.hpp"

#include <algorithm>
#include <bit>
#include <cmath>
#include <cstring>
#include <limits>

#include "stats/pdf.hpp"
#include "util/errors.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

// --- Julia's characters ------------------------------------------------------------------------
//
// A string's characters as Julia iterates a `String`, each as Julia's `Char` holds it: the
// bytes it is made of at the top of 32 bits. UTF-8 decodes as it should; bytes that are not
// UTF-8 come out in pieces -- a lead byte with the continuation bytes that follow it, up to
// the length it announces, or a byte alone -- and such a piece is "malformed". Julia's
// `_h5_utf8` writes these as U+FFFD, and an overlong form too, which is not malformed but has
// no code point (`codepoint` would throw).

/// One character from `i`, and where the next one starts (`iterate` and `iterate_continued`).
std::uint32_t next_char(std::string_view s, std::size_t& i) {
    const std::size_t n = s.size();
    auto byte = [&](std::size_t k) { return static_cast<std::uint32_t>(static_cast<unsigned char>(s[k])); };
    std::uint32_t b = byte(i);
    std::uint32_t u = b << 24;
    if (!(b >= 0x80 && b <= 0xf7) || u < 0xc0000000u) {
        i += 1;
        return u;
    }
    if (++i >= n) return u;
    b = byte(i);
    if ((b & 0xc0) != 0x80) return u;
    u |= b << 16;
    if (++i >= n || u < 0xe0000000u) return u;
    b = byte(i);
    if ((b & 0xc0) != 0x80) return u;
    u |= b << 8;
    if (++i >= n || u < 0xf0000000u) return u;
    b = byte(i);
    if ((b & 0xc0) != 0x80) return u;
    u |= b;
    ++i;
    return u;
}

int leading_ones(std::uint32_t u) { return std::countl_one(u); }
int trailing_zeros(std::uint32_t u) { return std::countr_zero(u); }
/// Julia's `>>` on a UInt32: past its width, zero.
std::uint32_t shr(std::uint32_t u, int k) { return k >= 32 ? 0u : u >> k; }

bool char_malformed(std::uint32_t u) {
    const int l1 = leading_ones(u) << 3;
    const int t0 = trailing_zeros(u) & 56;
    return (l1 == 8) || (l1 + t0 > 32) || (shr((u & 0x00c0c0c0u) ^ 0x00808080u, t0) != 0);
}

bool char_overlong(std::uint32_t u) {
    return (u >> 24 == 0xc0) || (u >> 24 == 0xc1) || (u >> 21 == 0x0704) || (u >> 20 == 0x0f08);
}

/// Julia's `show` of a character that is not one: its bytes, each `\xhh`.
std::string show_bytes_char(std::uint32_t u) {
    std::string s = "'";
    for (int k = 3; k >= 0; k--) {
        unsigned b = (u >> (8 * k)) & 0xff;
        if (k < 3 && b == 0) break;
        char buf[8];
        std::snprintf(buf, sizeof buf, "\\x%02x", b);
        s += buf;
    }
    return s + "'";
}

/// `codepoint(c)` (`UInt32(c)`): an overlong form has none, and Julia throws.
std::uint32_t char_codepoint(std::uint32_t u) {
    if (u < 0x80000000u) return u >> 24;
    const int l1 = leading_ones(u);
    const int t0 = trailing_zeros(u) & 56;
    if ((l1 == 1) || (8 * l1 + t0 > 32) || (shr((u & 0x00c0c0c0u) ^ 0x00808080u, t0) != 0) || char_overlong(u))
        throw JuliaError("InvalidCharError", "Base.InvalidCharError{Char}(" + show_bytes_char(u) + ")");
    u &= 0xffffffffu >> l1;
    u = shr(u, t0);
    return (u & 0x0000007fu) | ((u & 0x00007f00u) >> 2) | ((u & 0x007f0000u) >> 4) | ((u & 0x7f000000u) >> 6);
}

/// `isvalid(c)`, which compares characters as Julia holds them.
bool char_valid(std::uint32_t u) {
    return !char_malformed(u) && !char_overlong(u) && ((u <= 0xed9fbf00u) || (0xee808000u <= u && u <= 0xf48fbfbfu));
}

/// The bytes of a character as Julia holds it (`write(io, c)`).
void put_char(std::string& out, std::uint32_t u) {
    std::uint32_t v = (u >> 24) | ((u >> 8) & 0xff00u) | ((u << 8) & 0xff0000u) | (u << 24);   // bswap
    while (true) {
        out.push_back(static_cast<char>(v & 0xff));
        if ((v >>= 8) == 0) return;
    }
}

void put_utf8(std::string& out, std::uint32_t cp) {
    if (cp < 0x80) {
        out.push_back(static_cast<char>(cp));
    } else if (cp < 0x800) {
        out.push_back(static_cast<char>(0xc0 | (cp >> 6)));
        out.push_back(static_cast<char>(0x80 | (cp & 0x3f)));
    } else if (cp < 0x10000) {
        out.push_back(static_cast<char>(0xe0 | (cp >> 12)));
        out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3f)));
        out.push_back(static_cast<char>(0x80 | (cp & 0x3f)));
    } else {
        out.push_back(static_cast<char>(0xf0 | (cp >> 18)));
        out.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3f)));
        out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3f)));
        out.push_back(static_cast<char>(0x80 | (cp & 0x3f)));
    }
}

/// `isvalid(String, s)`: UTF-8 with no overlong form, no surrogate, nothing past U+10FFFF.
bool valid_utf8(std::string_view s) {
    std::size_t i = 0;
    const std::size_t n = s.size();
    while (i < n) {
        unsigned char c = static_cast<unsigned char>(s[i]);
        if (c < 0x80) {
            i++;
            continue;
        }
        std::size_t len;
        std::uint32_t cp, least;
        if (c >= 0xc2 && c <= 0xdf) len = 2, cp = c & 0x1f, least = 0x80;
        else if (c >= 0xe0 && c <= 0xef) len = 3, cp = c & 0x0f, least = 0x800;
        else if (c >= 0xf0 && c <= 0xf4) len = 4, cp = c & 0x07, least = 0x10000;
        else return false;
        if (i + len > n) return false;
        for (std::size_t k = 1; k < len; k++) {
            unsigned char d = static_cast<unsigned char>(s[i + k]);
            if ((d & 0xc0) != 0x80) return false;
            cp = (cp << 6) | (d & 0x3f);
        }
        if (cp < least || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff)) return false;
        i += len;
    }
    return true;
}

// --- JavaScript's view of the values ------------------------------------------------------------

/// Whether a key is a JavaScript array index: `0` or digits without a leading zero, below 2^32 - 1.
bool is_array_index(std::string_view k) {
    const std::size_t n = k.size();
    if (n == 0 || n > 10) return false;
    if (!(k[0] >= '0' && k[0] <= '9')) return false;
    if (k[0] == '0') return n == 1;
    long long v = 0;
    for (char c : k) {
        if (!(c >= '0' && c <= '9')) return false;
        v = 10 * v + (c - '0');
    }
    return v < 0xFFFFFFFFLL;
}

long long array_index_value(std::string_view k) {
    long long v = 0;
    for (char c : k) v = 10 * v + (c - '0');
    return v;
}

/// `ToInt32`: truncated towards zero and wrapped modulo 2^32; NaN and the infinities are 0.
std::int32_t to_int32(double x) {
    if (!std::isfinite(x)) return 0;
    double r = std::fmod(std::trunc(x), 4294967296.0);   // exact
    if (r < 0) r += 4294967296.0;
    return static_cast<std::int32_t>(static_cast<std::uint32_t>(r));
}

/// A value of a dataset as a number, as the writer reads one (`Number(v)`; a number as it is).
double number_of(const Json& v) { return v.is_number() ? v.as_double() : pd_to_number(v); }

// --- the global heap -----------------------------------------------------------------------------

// A global heap collection has to be at least this big, and every variable-length string in
// the file lives in one of them.
constexpr std::size_t HEAP_MINIMUM = 4096;
// Past this many objects the two-byte index in a heap ID runs out.
constexpr std::size_t HEAP_MAX_OBJECTS = 60000;

const std::string TRUE_TEXT = "TRUE";
const std::string FALSE_TEXT = "FALSE";

// Strings numbered (from 0) in the order they are first seen, by what they were given as;
// `texts` holds each as it is written (valid UTF-8). For the global heap: every
// variable-length string in the file, pooled, and the k-th is object k % 60000 + 1 of
// collection k / 60000. (Attribute names are numbered the same way.) In front of the table is
// a small cache by address: a result file says TRUE, its unit and its time hundreds of
// thousands of times, each time the same string a JSON value shares, and finding the address
// again is cheaper than hashing the characters. Every string in it outlives the plan (the tree
// holds them, or they are the constants above), so an address in it cannot come to be
// another string's.
struct Interner {
    struct Hash {
        using is_transparent = void;
        std::size_t operator()(std::string_view s) const noexcept { return std::hash<std::string_view>{}(s); }
    };
    std::unordered_map<std::string, std::uint32_t, Hash, std::equal_to<>> index;
    std::vector<std::string> texts;
    std::vector<const std::string*> cache_ptr;
    std::vector<std::uint32_t> cache_id;

    explicit Interner(std::size_t slots = 256) : cache_ptr(slots, nullptr), cache_id(slots, 0) {}

    std::uint32_t text(std::string_view s) {
        auto it = index.find(s);
        if (it != index.end()) return it->second;
        std::string key(s);
        texts.push_back(h5_utf8(key));
        const auto k = static_cast<std::uint32_t>(texts.size() - 1);
        index.emplace(std::move(key), k);
        return k;
    }
    /// A string that lives as long as the plan.
    std::uint32_t held(const std::string& s) {
        const std::size_t slot = (reinterpret_cast<std::uintptr_t>(&s) >> 4) & (cache_ptr.size() - 1);
        if (cache_ptr[slot] == &s) return cache_id[slot];
        const std::uint32_t k = text(s);
        cache_ptr[slot] = &s;
        cache_id[slot] = k;
        return k;
    }
};

// --- laying the file out ---------------------------------------------------------------------------

// One attribute, normalised: its name by number, and its values in the plan's `ids` (strings,
// as heap object numbers) or `nums` (doubles) from `first` on.
struct AttrRec {
    std::uint32_t name;
    bool str;
    bool scalar;
    std::size_t n;
    std::size_t first;
};

// One object's numbers. A group's children are `plan.children[group]`.
struct ObjRec {
    std::size_t attr_first = 0, attr_count = 0;
    std::size_t header_size = 0;
    std::size_t data_size = 0;
    std::size_t count = 0;        // how many values a dataset holds
    std::size_t ids_first = 0;    // a string dataset's heap ids, in the plan's `ids`
    std::ptrdiff_t group = -1;    // -1 for a dataset
};

struct Plan {
    Interner pool;
    Interner names{64};
    std::vector<AttrRec> attrs;
    std::vector<std::uint32_t> ids;
    std::vector<double> nums;
    std::vector<const H5Node*> nodes;     // every object, depth first
    std::vector<std::string> links;       // the name each is linked by, as written ("" for the root)
    std::vector<ObjRec> objs;
    std::vector<std::uint64_t> addr;
    std::vector<std::int64_t> data_addr;  // -1: none
    std::vector<std::vector<std::size_t>> children;
    std::vector<std::uint64_t> heap_at, heap_size;
    std::uint64_t size = 0;
};

std::size_t datatype_size(H5Type t) { return t == H5Type::I32 ? 12 : 20; }

std::size_t attr_size(const AttrRec& a, const Interner& names) {
    return 9 + names.texts[a.name].size() + 1 + 20 + (a.scalar ? 4 : 12) + a.n * (a.str ? 16 : 8);
}

std::size_t link_size(std::size_t nb) { return 2 + (nb > 255 ? 2 : 1) + nb + 8; }

std::size_t cld(std::size_t a, std::size_t b) { return (a + b - 1) / b; }

// An attribute's text: a boolean is TRUE or FALSE, which is what Ecolego's files say and what
// every reader of them tests for; anything else as `String()` writes it.
std::uint32_t text_id(Interner& pool, const Json& v) {
    if (v.is_string()) return pool.held(v.as_string());
    if (v.is_bool()) return pool.held(v.as_bool() ? TRUE_TEXT : FALSE_TEXT);
    return pool.text(pd_js_str(v));
}

// A string dataset's values are written as `String()` writes them, so a boolean there is `true`.
std::uint32_t data_id(Interner& pool, const Json& v) {
    if (v.is_string()) return pool.held(v.as_string());
    return pool.text(pd_js_str(v));
}

// The values of one attribute, normalised; the bytes its message takes.
std::size_t plan_attribute(Plan& plan, const std::string& name, const Json& value) {
    const std::uint32_t nm = plan.names.held(name);
    AttrRec a{nm, false, true, 1, 0};
    switch (value.type()) {
        case Json::Type::String:
        case Json::Type::Bool:
            plan.ids.push_back(text_id(plan.pool, value));
            a.str = true;
            a.first = plan.ids.size() - 1;
            break;
        case Json::Type::Array: {
            const JArray& vals = value.arr();
            bool text = false;
            for (const Json& v : vals)
                if (v.is_string() || v.is_bool()) {
                    text = true;
                    break;
                }
            a.str = text;
            a.scalar = false;
            a.n = vals.size();
            if (text) {
                a.first = plan.ids.size();
                for (const Json& v : vals) plan.ids.push_back(text_id(plan.pool, v));
            } else {
                a.first = plan.nums.size();
                for (const Json& v : vals) plan.nums.push_back(pd_to_number(v));
            }
            break;
        }
        default:   // a number; a dictionary is NaN
            plan.nums.push_back(pd_to_number(value));
            a.first = plan.nums.size() - 1;
            break;
    }
    plan.attrs.push_back(a);
    return 4 + attr_size(a, plan.names);
}

// The attributes of one object, in JavaScript's key order, normalised; the bytes their messages take.
std::size_t plan_attrs(Plan& plan, const H5Attrs& attrs) {
    std::size_t msgs = 0;
    const std::size_t n = attrs.size();
    bool indexed = false;
    for (std::size_t i = 0; i < n && !indexed; i++) indexed = is_array_index(attrs.name(i));
    if (!indexed) {
        for (std::size_t i = 0; i < n; i++)
            if (!attrs.value(i).is_null()) msgs += plan_attribute(plan, attrs.name(i), attrs.value(i));
        return msgs;
    }
    std::vector<std::size_t> first, rest;
    for (std::size_t i = 0; i < n; i++) (is_array_index(attrs.name(i)) ? first : rest).push_back(i);
    std::sort(first.begin(), first.end(), [&](std::size_t a, std::size_t b) { return array_index_value(attrs.name(a)) < array_index_value(attrs.name(b)); });
    for (const auto* order : {&first, &rest})
        for (std::size_t i : *order)
            if (!attrs.value(i).is_null()) msgs += plan_attribute(plan, attrs.name(i), attrs.value(i));
    return msgs;
}

// A dataset's string values, as the writer reads them, into the pool.
void plan_strings(Plan& plan, const H5Dataset& ds) {
    if (const auto* d = std::get_if<std::vector<double>>(&ds.data)) {
        for (double x : *d) plan.ids.push_back(plan.pool.text(pd_js_number_str(x)));
    } else if (const auto* f = std::get_if<std::vector<float>>(&ds.data)) {
        for (float x : *f) plan.ids.push_back(plan.pool.text(pd_js_number_str(static_cast<double>(x))));
    } else {
        const Json& v = std::get<Json>(ds.data);
        if (v.is_array()) {
            for (const Json& x : v.arr()) plan.ids.push_back(data_id(plan.pool, x));
        } else if (v.is_string()) {
            for (const std::string& c : julia_chars(v.as_string())) plan.ids.push_back(plan.pool.text(c));
        } else if (v.is_object()) {
            for (const auto& item : v.obj()) plan.ids.push_back(plan.pool.held(item.first));
        }
    }
}

// Walks the tree once: normalises the attributes, pools the strings, and works out how big
// every object header and data block will be, and where everything goes. Depth first, each
// object before its children -- which fixes both the order of the headers and the order the
// strings enter the heap. Walked with a stack of its own rather than by recursion, so a deep
// tree is not refused.
void make_plan(Plan& plan, const H5Group& root) {
    struct Item {
        const H5Node* node;
        std::string link;
        std::ptrdiff_t parent;   // -1: none
    };
    std::vector<Item> stack;
    stack.push_back({&root, std::string(), -1});
    while (!stack.empty()) {
        Item item = std::move(stack.back());
        stack.pop_back();
        if (item.parent >= 0 && item.link.empty()) throw HDF5Error("A link cannot have an empty name");
        const H5Node& node = *item.node;
        const std::size_t attr_first = plan.attrs.size();
        std::size_t msgs = plan_attrs(plan, node.attrs);
        const std::size_t attr_count = plan.attrs.size() - attr_first;
        // Every object with attributes says so: without it a reader looks for them in a
        // fractal heap that is not there.
        if (attr_count > 0) msgs += 4 + 18;
        plan.nodes.push_back(&node);
        plan.links.push_back(std::move(item.link));
        const std::size_t me = plan.nodes.size() - 1;
        if (item.parent >= 0) plan.children[static_cast<std::size_t>(plan.objs[static_cast<std::size_t>(item.parent)].group)].push_back(me);
        ObjRec o;
        o.attr_first = attr_first;
        o.attr_count = attr_count;
        if (node.is_group()) {
            const auto& g = static_cast<const H5Group&>(node);
            plan.children.emplace_back();
            o.group = static_cast<std::ptrdiff_t>(plan.children.size() - 1);
            msgs += 4 + 18 + 4 + 2;   // link info, group info
            const auto& kids = g.children();
            std::vector<std::string> kid_names;
            kid_names.reserve(kids.size());
            for (const auto& [name, child] : kids) {
                kid_names.push_back(h5_utf8(name));
                msgs += 4 + link_size(kid_names.back().size());
            }
            for (std::size_t j = kids.size(); j-- > 0;)
                stack.push_back({kids[j].second.get(), std::move(kid_names[j]), static_cast<std::ptrdiff_t>(me)});
            o.header_size = 14 + msgs;
        } else {
            const auto& ds = static_cast<const H5Dataset&>(node);
            const std::size_t n = ds.count();
            if (ds.dt == H5Type::STR) {
                o.ids_first = plan.ids.size();
                plan_strings(plan, ds);
            }
            const std::size_t rank = ds.dims ? ds.dims->size() : 1;
            msgs += (4 + 4 + 8 * rank) + (4 + datatype_size(ds.dt)) + (4 + 2) + (4 + 18);
            o.header_size = 14 + msgs;
            o.data_size = n * h5_type_size(ds.dt);
            o.count = n;
        }
        plan.objs.push_back(o);
    }

    // Where everything goes: the superblock first, then the strings -- they have to be placed
    // before any header is written, because an attribute's data is the address of the
    // collection holding it -- then the headers, then the numbers, each block on an eight-byte
    // boundary.
    const std::vector<std::string>& texts = plan.pool.texts;
    const std::size_t ncoll = std::max<std::size_t>(1, cld(texts.size(), HEAP_MAX_OBJECTS));
    plan.heap_at.resize(ncoll);
    plan.heap_size.resize(ncoll);
    std::uint64_t at = 48;
    for (std::size_t c = 0; c < ncoll; c++) {
        std::uint64_t n = 16;
        const std::size_t lo = c * HEAP_MAX_OBJECTS, hi = std::min((c + 1) * HEAP_MAX_OBJECTS, texts.size());
        for (std::size_t k = lo; k < hi; k++) n += 16 + 8 * cld(texts[k].size(), 8);
        // The specification's minimum. Anything left over is described by a free-space
        // object, which is what index 0 means.
        plan.heap_at[c] = at;
        plan.heap_size[c] = std::max<std::uint64_t>(HEAP_MINIMUM, n + 16);
        at += plan.heap_size[c];
    }
    const std::size_t nobj = plan.objs.size();
    plan.addr.resize(nobj);
    plan.data_addr.resize(nobj);
    for (std::size_t i = 0; i < nobj; i++) {
        plan.addr[i] = at;
        at += plan.objs[i].header_size;
    }
    for (std::size_t i = 0; i < nobj; i++) {
        // Nothing to point at, and address zero is the superblock: a dataset with no values
        // says so with the undefined address.
        plan.data_addr[i] = -1;
        const std::size_t size = plan.objs[i].data_size;
        if (size == 0) continue;
        at = 8 * cld(at, 8);
        plan.data_addr[i] = static_cast<std::int64_t>(at);
        at += size;
    }
    plan.size = at;
}

// --- writing -------------------------------------------------------------------------------------
//
// Into a buffer of exactly the file's size: each helper writes at `p` and moves it on.

struct Out {
    unsigned char* b;
    std::size_t p;

    void u8(std::uint64_t v) { b[p++] = static_cast<unsigned char>(v & 0xff); }
    void u16(std::uint64_t v) {
        u8(v);
        u8(v >> 8);
    }
    void u32(std::uint64_t v) {
        for (int i = 0; i < 4; i++) u8(v >> (8 * i));
    }
    void u64(std::uint64_t v) {
        for (int i = 0; i < 8; i++) u8(v >> (8 * i));
    }
    /// An address: -1 is the undefined one, all ones.
    void addr(std::int64_t v) { u64(v < 0 ? ~std::uint64_t{0} : static_cast<std::uint64_t>(v)); }
    void f64(double x) { u64(std::bit_cast<std::uint64_t>(x)); }
    void fill(std::size_t n, unsigned char v) {
        if (n) std::memset(b + p, v, n);
        p += n;
    }
    void text(const std::string& s) {
        if (!s.empty()) std::memcpy(b + p, s.data(), s.size());
        p += s.size();
    }
    void msg(unsigned kind, std::size_t size) {
        u8(kind);
        u16(size);
        u8(0);
    }
};

// A number as eight little-endian bytes the way the JavaScript spells it out
// (`Math.floor(n / 2 ** (8 * i)) & 0xff` for each byte): NaN and the infinities are zeros, a
// negative integer all ones above its bits.
void put_le(Out& o, const Json& x) {
    auto put_int = [&](std::uint64_t u) {
        for (int i = 0; i < 8; i++) o.u8(u >> (8 * i));
    };
    if (x.is_int()) {
        put_int(static_cast<std::uint64_t>(x.as_int()));
        return;
    }
    const double f = pd_to_number(x);
    if (!std::isfinite(f)) {
        o.fill(8, 0x00);
    } else if (f != std::trunc(f)) {
        for (int i = 0; i < 8; i++) {
            const double q = std::floor(f / std::ldexp(1.0, 8 * i));   // |f| < 2^52: it fits
            o.u8(static_cast<std::uint64_t>(static_cast<std::int64_t>(q)) & 0xff);
        }
    } else if (std::fabs(f) < 9223372036854775808.0) {
        put_int(static_cast<std::uint64_t>(static_cast<std::int64_t>(f)));
    } else {
        // The whole number's low 64 bits, in two's complement, as a BigInt has them.
        int e = 0;
        const double fr = std::frexp(std::fabs(f), &e);
        const auto m = static_cast<std::uint64_t>(std::ldexp(fr, 53));
        const int shift = e - 53;
        std::uint64_t low = shift >= 64 ? 0 : m << shift;
        if (f < 0) low = ~low + 1;
        put_int(low);
    }
}

// The datatype message's body. Version 1, which every reader understands: a class-and-version
// byte, three bytes of class-specific flags, a four-byte size, and then properties whose shape
// depends on the class.
void put_datatype(Out& o, H5Type t) {
    if (t == H5Type::F64 || t == H5Type::F32) {
        const bool d = t == H5Type::F64;
        const unsigned size = d ? 8 : 4;
        // Bit 0 clear is little-endian; bits 4-5 = 2 is the usual "the leading mantissa bit is
        // implied"; bits 8-15 say where the sign sits, which for these is the top bit.
        const unsigned bits = 0x20 | ((size * 8 - 1) << 8);
        o.u8((1 << 4) | 1);
        o.u8(bits);
        o.u8(bits >> 8);
        o.u8(bits >> 16);
        o.u32(size);
        o.u16(0);          // bit offset
        o.u16(size * 8);   // bit precision
        o.u8(d ? 52 : 23);
        o.u8(d ? 11 : 8);
        o.u8(0);
        o.u8(d ? 52 : 23);
        o.u32(d ? 1023 : 127);
    } else if (t == H5Type::I32) {
        o.u8((1 << 4) | 0);
        o.u8(0x08);   // signed
        o.u8(0);
        o.u8(0);
        o.u32(4);
        o.u16(0);
        o.u16(32);
    } else {
        // Class 9, variable-length. Bits 0-3 = 1 says the sequence is a string; bits 4-7 are
        // its padding rule and bits 8-11 its character set (UTF-8).
        o.u8((1 << 4) | 9);
        o.u8(0x01);
        o.u8(0x01);
        o.u8(0x00);
        o.u32(16);
        // The parent type is one character, which libhdf5 writes as an eight-bit unsigned
        // integer rather than as a one-byte string.
        o.u8((1 << 4) | 0);
        o.u8(0);
        o.u8(0);
        o.u8(0);
        o.u32(1);
        o.u16(0);
        o.u16(8);
    }
}

// The dataspace message's body, version 2, whose "type" byte tells a scalar (no dimensions)
// from a one-element array.
void put_dataspace(Out& o, const std::optional<std::vector<Json>>& dims, std::size_t n) {
    if (!dims) {   // one dimension of `n`
        o.u8(2);
        o.u8(1);
        o.u8(0);
        o.u8(1);
        o.u64(n);
        return;
    }
    o.u8(2);
    o.u8(dims->size());
    o.u8(0);
    o.u8(dims->empty() ? 0 : 1);
    for (const Json& d : *dims) put_le(o, d);
}

// The 16 bytes that stand for one variable-length string: its length, the address of its
// collection, its index in it.
void put_heap_id(Out& o, const Plan& plan, std::uint32_t k) {
    o.u32(plan.pool.texts[k].size());
    o.u64(plan.heap_at[k / HEAP_MAX_OBJECTS]);
    o.u32(k % HEAP_MAX_OBJECTS + 1);
}

void put_header(Out& o, const Plan& plan, std::size_t i) {
    const ObjRec& rec = plan.objs[i];
    const std::size_t start = plan.addr[i];
    o.p = start;
    o.u8('O');
    o.u8('H');
    o.u8('D');
    o.u8('R');
    o.u8(2);   // version
    o.u8(2);   // the chunk's size takes four bytes
    o.u32(rec.header_size - 14);
    const H5Node& node = *plan.nodes[i];
    if (node.is_group()) {
        // Undefined addresses for both indexes: the links are here, in this header, rather
        // than in a fractal heap.
        o.msg(0x02, 18);
        o.u8(0);
        o.u8(0);
        o.fill(16, 0xff);
        o.msg(0x0a, 2);
        o.u8(0);
        o.u8(0);
        for (std::size_t j : plan.children[static_cast<std::size_t>(rec.group)]) {
            const std::string& name = plan.links[j];
            const std::size_t nb = name.size();
            const bool longer = nb > 255;
            o.msg(0x06, link_size(nb));
            o.u8(1);
            o.u8(longer ? 1 : 0);
            if (longer) o.u16(nb);
            else o.u8(nb);
            o.text(name);
            o.u64(plan.addr[j]);
        }
    } else {
        const auto& ds = static_cast<const H5Dataset&>(node);
        const std::size_t rank = ds.dims ? ds.dims->size() : 1;
        o.msg(0x01, 4 + 8 * rank);
        put_dataspace(o, ds.dims, rec.count);
        o.msg(0x03, datatype_size(ds.dt));
        put_datatype(o, ds.dt);
        // Version 3, allocated late, with no fill value of its own: every byte of this dataset
        // is written, so there is nothing to fill.
        o.msg(0x05, 2);
        o.u8(3);
        o.u8(2);
        o.msg(0x08, 18);
        o.u8(3);
        o.u8(1);
        o.addr(plan.data_addr[i]);
        o.u64(rec.data_size);
    }
    if (rec.attr_count > 0) {
        o.msg(0x15, 18);
        o.u8(0);
        o.u8(0);
        o.fill(16, 0xff);
        for (std::size_t ai = rec.attr_first; ai < rec.attr_first + rec.attr_count; ai++) {
            const AttrRec& a = plan.attrs[ai];
            const std::string& name = plan.names.texts[a.name];
            const std::size_t nb = name.size();
            o.msg(0x0c, attr_size(a, plan.names));
            o.u8(3);
            o.u8(0);
            o.u16(nb + 1);
            o.u16(20);
            o.u16(a.scalar ? 4 : 12);
            o.u8(0);
            o.text(name);
            o.u8(0);
            put_datatype(o, a.str ? H5Type::STR : H5Type::F64);
            if (a.scalar) {
                o.u8(2);
                o.u8(0);
                o.u8(0);
                o.u8(0);
            } else {
                o.u8(2);
                o.u8(1);
                o.u8(0);
                o.u8(1);
                o.u64(a.n);
            }
            if (a.str)
                for (std::size_t k = a.first; k < a.first + a.n; k++) put_heap_id(o, plan, plan.ids[k]);
            else
                for (std::size_t k = a.first; k < a.first + a.n; k++) o.f64(plan.nums[k]);
        }
    }
    o.u32(lookup3(std::string_view(reinterpret_cast<const char*>(o.b) + start, o.p - start)));
    if (o.p != start + rec.header_size)
        throw std::logic_error("an object header came out " + std::to_string(o.p - start) + " bytes, not " + std::to_string(rec.header_size));
}

// Every value of a dataset, as a number, in order.
template <class F>
void each_number(const H5Dataset& ds, F&& f) {
    if (const auto* d = std::get_if<std::vector<double>>(&ds.data)) {
        for (double x : *d) f(x);
    } else if (const auto* s = std::get_if<std::vector<float>>(&ds.data)) {
        for (float x : *s) f(static_cast<double>(x));
    } else {
        const Json& v = std::get<Json>(ds.data);
        if (v.is_array()) {
            for (const Json& x : v.arr()) f(number_of(x));
        } else if (v.is_string()) {
            for (const std::string& c : julia_chars(v.as_string())) f(pd_string_to_number(c));
        } else if (v.is_object()) {
            for (const auto& item : v.obj()) f(pd_string_to_number(item.first));
        }
    }
}

// One dataset's values, at its address, as the application's typed arrays hold them.
void put_data(Out& o, const Plan& plan, std::size_t i, const H5Dataset& ds) {
    const ObjRec& rec = plan.objs[i];
    const std::size_t start = static_cast<std::size_t>(plan.data_addr[i]);
    o.p = start;
    constexpr bool little = std::endian::native == std::endian::little;
    switch (ds.dt) {
        case H5Type::STR:
            for (std::size_t k = rec.ids_first; k < rec.ids_first + rec.count; k++) put_heap_id(o, plan, plan.ids[k]);
            break;
        case H5Type::F64:
            if (const auto* d = std::get_if<std::vector<double>>(&ds.data); d && little) {
                std::memcpy(o.b + o.p, d->data(), 8 * d->size());
                o.p += 8 * d->size();
            } else {
                each_number(ds, [&](double x) { o.f64(x); });
            }
            break;
        case H5Type::F32:
            if (const auto* f = std::get_if<std::vector<float>>(&ds.data); f && little) {
                std::memcpy(o.b + o.p, f->data(), 4 * f->size());
                o.p += 4 * f->size();
            } else {
                // Doubles first, as every JavaScript number is, then rounded to the nearest
                // float32, overflowing to infinity, as a Float32Array stores them.
                each_number(ds, [&](double x) { o.u32(std::bit_cast<std::uint32_t>(static_cast<float>(x))); });
            }
            break;
        case H5Type::I32:
            each_number(ds, [&](double x) { o.u32(static_cast<std::uint32_t>(to_int32(x))); });
            break;
    }
    if (o.p != start + rec.data_size)
        throw std::logic_error("a dataset's data came out " + std::to_string(o.p - start) + " bytes, not " + std::to_string(rec.data_size));
}

// --- lookup3 ---------------------------------------------------------------------------------------

inline std::uint32_t rot(std::uint32_t x, int k) { return (x << k) | (x >> (32 - k)); }

inline std::uint32_t word(const unsigned char* b) {
    return static_cast<std::uint32_t>(b[0]) | (static_cast<std::uint32_t>(b[1]) << 8) | (static_cast<std::uint32_t>(b[2]) << 16) |
           (static_cast<std::uint32_t>(b[3]) << 24);
}

inline std::uint32_t partial(const unsigned char* b, std::size_t m) {
    std::uint32_t w = 0;
    for (std::size_t t = 0; t < m; t++) w |= static_cast<std::uint32_t>(b[t]) << (8 * t);
    return w;
}

std::uint32_t lookup3_bytes(const unsigned char* b, std::size_t n) {
    std::uint32_t a, bb, c;
    a = bb = c = 0xdeadbeefu + static_cast<std::uint32_t>(n);
    std::size_t i = 0, left = n;
    // Twelve bytes at a time while more than twelve are left: the last one to twelve go
    // through the tail below.
    while (left > 12) {
        a += word(b + i);
        bb += word(b + i + 4);
        c += word(b + i + 8);
        a -= c; a ^= rot(c, 4); c += bb;
        bb -= a; bb ^= rot(a, 6); a += c;
        c -= bb; c ^= rot(bb, 8); bb += a;
        a -= c; a ^= rot(c, 16); c += bb;
        bb -= a; bb ^= rot(a, 19); a += c;
        c -= bb; c ^= rot(bb, 4); bb += a;
        left -= 12;
        i += 12;
    }
    if (left == 0) return c;
    // The tail, as the C's fall-through switch adds it.
    if (left >= 9) c += partial(b + i + 8, left - 8);
    if (left >= 5) bb += partial(b + i + 4, std::min<std::size_t>(left - 4, 4));
    a += partial(b + i, std::min<std::size_t>(left, 4));
    c ^= bb; c -= rot(bb, 14);
    a ^= c; a -= rot(c, 11);
    bb ^= a; bb -= rot(a, 25);
    c ^= bb; c -= rot(bb, 16);
    a ^= c; a -= rot(c, 4);
    bb ^= a; bb -= rot(a, 14);
    c ^= bb; c -= rot(bb, 24);
    return c;
}

}  // namespace

// --- the public pieces -------------------------------------------------------------------------------

std::size_t h5_type_size(H5Type t) noexcept {
    switch (t) {
        case H5Type::F64: return 8;
        case H5Type::F32: return 4;
        case H5Type::I32: return 4;
        case H5Type::STR: return 16;
    }
    return 0;
}

std::vector<std::string> julia_chars(std::string_view s) {
    std::vector<std::string> out;
    std::size_t i = 0;
    while (i < s.size()) {
        const std::size_t at = i;
        next_char(s, i);
        out.emplace_back(s.substr(at, i - at));
    }
    return out;
}

std::string h5_utf8(const std::string& s) {
    if (valid_utf8(s)) return s;
    std::string out;
    out.reserve(s.size() + 8);
    std::uint32_t pending = 0;   // a high surrogate waiting for its low half
    std::size_t i = 0;
    while (i < s.size()) {
        const std::uint32_t c = next_char(s, i);
        // An overlong form (C0 80, E0 80 80, ...) is not malformed to Julia, but it has no code
        // point: U+FFFD, as any other piece that is not UTF-8.
        const std::uint32_t u = char_malformed(c) || char_overlong(c) ? 0xffffffffu : char_codepoint(c);
        if (pending != 0) {
            if (u >= 0xdc00 && u <= 0xdfff) {
                put_utf8(out, 0x10000 + ((pending - 0xd800) << 10) + (u - 0xdc00));
                pending = 0;
                continue;
            }
            put_utf8(out, 0xfffd);
            pending = 0;
        }
        if (u >= 0xd800 && u <= 0xdbff) pending = u;
        else if (char_valid(c)) put_char(out, c);
        else put_utf8(out, 0xfffd);
    }
    if (pending != 0) put_utf8(out, 0xfffd);
    return out;
}

// --- attributes and nodes ------------------------------------------------------------------------------

H5Attrs::H5Attrs(std::initializer_list<std::pair<std::string, Json>> items) {
    for (const auto& [k, v] : items) set(k, v);
}

H5Attrs::H5Attrs(std::shared_ptr<const std::vector<std::string>> names, std::vector<Json> values) : names_(std::move(names)), values_(std::move(values)) {
    if (!names_ || names_->size() != values_.size()) throw std::invalid_argument("attributes need a name for every value");
}

std::ptrdiff_t H5Attrs::slot(std::string_view name) const noexcept {
    if (!names_) return -1;
    const auto& ks = *names_;
    for (std::size_t i = 0; i < ks.size(); i++)
        if (ks[i] == name) return static_cast<std::ptrdiff_t>(i);
    return -1;
}

std::vector<std::string>& H5Attrs::own_names() {
    // Names given (shared with other attributes), or held by a copy of these, are copied first.
    if (!own_ || names_.use_count() > 1) {
        names_ = names_ ? std::make_shared<std::vector<std::string>>(*names_) : std::make_shared<std::vector<std::string>>();
        own_ = true;
    }
    // Made here, by `make_shared` of a vector that is not const: it may be changed.
    return const_cast<std::vector<std::string>&>(*names_);
}

const Json* H5Attrs::find(std::string_view name) const noexcept {
    const std::ptrdiff_t i = slot(name);
    return i < 0 ? nullptr : &values_[static_cast<std::size_t>(i)];
}

void H5Attrs::set(std::string_view name, Json value) {
    const std::ptrdiff_t i = slot(name);
    if (i >= 0) {
        values_[static_cast<std::size_t>(i)] = std::move(value);
        return;
    }
    own_names().emplace_back(name);
    values_.push_back(std::move(value));
}

bool H5Attrs::erase(std::string_view name) {
    const std::ptrdiff_t i = slot(name);
    if (i < 0) return false;
    auto& ks = own_names();
    ks.erase(ks.begin() + i);
    values_.erase(values_.begin() + i);
    return true;
}

H5Node* H5Group::child(std::string_view name) const noexcept {
    auto it = index_.find(name);
    return it == index_.end() ? nullptr : children_[it->second].second.get();
}

bool H5Group::add(std::string name, H5Ptr node) {
    if (index_.count(std::string_view(name))) return false;
    index_.emplace(name, children_.size());
    children_.emplace_back(std::move(name), std::move(node));
    return true;
}

std::size_t H5Dataset::count() const {
    if (const auto* d = std::get_if<std::vector<double>>(&data)) return d->size();
    if (const auto* f = std::get_if<std::vector<float>>(&data)) return f->size();
    const Json& v = std::get<Json>(data);
    if (v.is_array()) return v.size();
    if (v.is_object()) return v.obj().size();
    if (v.is_string()) {
        std::size_t n = 0, i = 0;
        const std::string& s = v.as_string();
        while (i < s.size()) {
            next_char(s, i);
            n++;
        }
        return n;
    }
    return 0;   // a bare number is not a list, and gives an empty dataset, as in the application
}

std::shared_ptr<H5Group> h5_group(H5Attrs attrs) { return std::make_shared<H5Group>(std::move(attrs)); }

namespace {

std::shared_ptr<H5Dataset> checked(std::shared_ptr<H5Dataset> ds) {
    if (!ds->dims) return ds;
    double want = 1.0;
    for (const Json& d : *ds->dims) want *= pd_to_number(d);
    const std::size_t got = ds->count();
    if (want != static_cast<double>(got)) {
        std::string shape;
        for (std::size_t k = 0; k < ds->dims->size(); k++) {
            if (k) shape += "\xc3\x97";   // ×
            const Json& d = (*ds->dims)[k];
            if (!d.is_null()) shape += pd_js_str(d);
        }
        throw HDF5Error("A " + shape + " dataset holds " + pd_js_number_str(want) + " values and was given " + std::to_string(got));
    }
    return ds;
}

}  // namespace

std::shared_ptr<H5Dataset> h5_dataset(std::vector<double> data, H5Type dt, H5Attrs attrs, std::optional<std::vector<Json>> dims) {
    return checked(std::make_shared<H5Dataset>(std::move(data), dt, std::move(attrs), std::move(dims)));
}

std::shared_ptr<H5Dataset> h5_dataset(std::vector<float> data, H5Type dt, H5Attrs attrs, std::optional<std::vector<Json>> dims) {
    return checked(std::make_shared<H5Dataset>(std::move(data), dt, std::move(attrs), std::move(dims)));
}

std::shared_ptr<H5Dataset> h5_dataset(Json data, H5Type dt, H5Attrs attrs, std::optional<std::vector<Json>> dims) {
    return checked(std::make_shared<H5Dataset>(std::move(data), dt, std::move(attrs), std::move(dims)));
}

H5Ptr h5_put(H5Group& root, const std::vector<std::string>& path, H5Ptr node) {
    std::vector<const std::string*> parts;
    for (const std::string& p : path)
        if (!p.empty()) parts.push_back(&p);
    if (parts.empty()) throw HDF5Error("Nothing can be put at the root itself");
    H5Group* at = &root;
    for (std::size_t k = 0; k + 1 < parts.size(); k++) {
        const std::string& part = *parts[k];
        if (part.find('/') != std::string::npos) throw HDF5Error("'" + part + "' cannot be a name: it has a slash in it");
        H5Node* next = at->child(part);
        if (next == nullptr) {
            auto g = h5_group();
            at->add(part, g);
            at = g.get();
        } else if (!next->is_group()) {
            throw HDF5Error("'" + part + "' is a dataset, so nothing can be put inside it");
        } else {
            at = static_cast<H5Group*>(next);
        }
    }
    const std::string& last = *parts.back();
    if (last.find('/') != std::string::npos) throw HDF5Error("'" + last + "' cannot be a name: it has a slash in it");
    if (!at->add(last, node)) {
        std::string where;
        for (std::size_t k = 0; k < parts.size(); k++) where += (k ? "/" : "") + *parts[k];
        throw HDF5Error("There is already something at " + where);
    }
    return node;
}

std::uint32_t lookup3(std::string_view data) noexcept { return lookup3_bytes(reinterpret_cast<const unsigned char*>(data.data()), data.size()); }

std::uint32_t lookup3(std::string_view data, std::size_t start, std::size_t len) {
    if (start <= data.size() && len <= data.size() - start) return lookup3(data.substr(start, len));
    std::string chunk(len, '\0');
    if (start < data.size()) {
        const std::size_t have = std::min(len, data.size() - start);
        std::memcpy(chunk.data(), data.data() + start, have);
    }
    return lookup3(chunk);
}

std::string write_hdf5(const H5Node& root) {
    if (!root.is_group()) throw HDF5Error("The root of a file is a group");
    Plan plan;
    make_plan(plan, static_cast<const H5Group&>(root));
    std::string file(plan.size, '\0');
    Out o{reinterpret_cast<unsigned char*>(file.data()), 0};

    // --- the superblock, version 2.
    for (unsigned c : {0x89u, unsigned('H'), unsigned('D'), unsigned('F'), unsigned('\r'), unsigned('\n'), 0x1au, unsigned('\n')}) o.u8(c);
    o.u8(2);
    o.u8(8);
    o.u8(8);
    o.u8(0);
    o.u64(0);                 // base address
    o.addr(-1);               // no superblock extension
    o.u64(plan.size);         // end of file
    o.u64(plan.addr[0]);      // the root group
    o.u32(lookup3(std::string_view(file.data(), o.p)));

    // --- the strings.
    const std::vector<std::string>& texts = plan.pool.texts;
    for (std::size_t c = 0; c < plan.heap_at.size(); c++) {
        const std::size_t start = plan.heap_at[c];
        const std::size_t total = plan.heap_size[c];
        o.p = start;
        o.u8('G');
        o.u8('C');
        o.u8('O');
        o.u8('L');
        o.u8(1);
        o.fill(3, 0x00);
        o.u64(total);
        const std::size_t lo = c * HEAP_MAX_OBJECTS, hi = std::min((c + 1) * HEAP_MAX_OBJECTS, texts.size());
        for (std::size_t k = lo; k < hi; k++) {
            const std::string& s = texts[k];
            // The reference count is what libhdf5 writes for a string the file itself points
            // at, which is nothing: it counts *references*, the HDF5 kind, and there are none.
            o.u16(k - lo + 1);
            o.u16(0);
            o.u32(0);
            o.u64(s.size());
            o.text(s);
            o.fill(8 * cld(o.p, 8) - o.p, 0x00);
        }
        // What is left is one object with index zero, which is how a collection says "free
        // space" -- and there always is some.
        std::size_t left = start + total - o.p;
        if (left >= 16) {
            o.u16(0);
            o.u16(0);
            o.u32(0);
            o.u64(left);
            left -= 16;
        }
        o.fill(left, 0x00);
    }

    // --- the objects.
    for (std::size_t i = 0; i < plan.objs.size(); i++) put_header(o, plan, i);

    // --- the numbers, each block on an eight-byte boundary (the buffer starts zeroed).
    for (std::size_t i = 0; i < plan.objs.size(); i++) {
        if (plan.data_addr[i] < 0) continue;
        put_data(o, plan, i, static_cast<const H5Dataset&>(*plan.nodes[i]));
    }
    return file;
}

}  // namespace kompartment
