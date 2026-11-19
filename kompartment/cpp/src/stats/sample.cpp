#include "stats/sample.hpp"

#include <cmath>
#include <limits>
#include <utility>

#include "engine/builder.hpp"
#include "engine/project.hpp"
#include "engine/system.hpp"
#include "lang/jsmath.hpp"
#include "stats/normal.hpp"
#include "stats/pdf.hpp"
#include "util/errors.hpp"

namespace kompartment {

namespace {

constexpr double NaN = std::numeric_limits<double>::quiet_NaN();

/// Two 32-bit values into one, well enough that neighbours do not collide.
std::uint32_t sm_mix(std::uint32_t a, std::uint32_t b) {
    std::uint32_t h = a ^ ((b ^ (b >> 16)) * 0x85ebca6bu);
    h = (h ^ (h >> 13)) * 0xc2b2ae35u;
    return h ^ (h >> 16);
}

/// Julia's `transcode(UInt16, s)` (base/strings/cstring.jl), byte for byte: well-formed UTF-8
/// as its UTF-16 code units, and what is not -- a byte out of place, a sequence cut short -- as
/// Julia carries it across, a code unit a byte.
std::vector<std::uint16_t> utf16_units(std::string_view s) {
    std::vector<std::uint16_t> dst;
    std::size_t n = s.size();
    if (n == 0) return dst;
    dst.reserve(2 * n);
    auto at = [&](std::size_t i) { return static_cast<std::uint8_t>(s[i - 1]); };   // from 1, as Julia's
    auto signed8 = [](std::uint8_t x) { return static_cast<int>(static_cast<std::int8_t>(x)); };
    auto u16 = [](unsigned v) { return static_cast<std::uint16_t>(v & 0xffffu); };
    std::size_t i = 1;
    std::uint8_t a = at(1);
    while (true) {
        if (i < n && -64 <= signed8(a) && signed8(a) <= -12) {   // a multi-byte character
            std::uint8_t b = at(++i);
            if (-64 <= signed8(b) || (a == 0xf4 && 0x8f < b)) {
                // not UTF-8 (no continuation, or a code point too high)
                dst.push_back(a);
                a = b;
                continue;
            } else if (a < 0xe0) {   // two bytes
                dst.push_back(u16(0x3080u ^ (static_cast<unsigned>(u16(static_cast<unsigned>(a) << 6))) ^ b));
            } else if (i < n) {   // three or four bytes
                std::uint8_t c = at(++i);
                if (-64 <= signed8(c)) {
                    dst.push_back(a);
                    dst.push_back(b);
                    a = c;
                    continue;
                } else if (a < 0xf0) {   // three bytes
                    dst.push_back(u16(0x2080u ^ u16(static_cast<unsigned>(a) << 12) ^ u16(static_cast<unsigned>(b) << 6) ^ c));
                } else if (i < n) {
                    std::uint8_t d = at(++i);
                    if (-64 <= signed8(d)) {
                        dst.push_back(a);
                        dst.push_back(b);
                        dst.push_back(c);
                        a = d;
                        continue;
                    } else if (a == 0xf0 && b < 0x90) {   // an overlong form
                        dst.push_back(u16(0x2080u ^ u16(static_cast<unsigned>(b) << 12) ^ u16(static_cast<unsigned>(c) << 6) ^ d));
                    } else {   // four bytes
                        dst.push_back(u16(0xe5b8u + u16(static_cast<unsigned>(a) << 8) + u16(static_cast<unsigned>(b) << 2) +
                                          (static_cast<unsigned>(c) >> 4)));
                        dst.push_back(u16(0xdc80u ^ u16(static_cast<unsigned>(c & 0xf) << 6) ^ d));
                    }
                } else {   // cut short
                    dst.push_back(a);
                    dst.push_back(b);
                    dst.push_back(c);
                    break;
                }
            } else {   // cut short
                dst.push_back(a);
                dst.push_back(b);
                break;
            }
        } else {   // ASCII, or a byte that is not UTF-8
            dst.push_back(a);
        }
        if (!(i < n)) break;
        a = at(++i);
    }
    return dst;
}

/// `values[index]` as JavaScript reads it: NaN unless a whole index in range; a number as a
/// double. (A Boolean, a word or a gap is no number to set into a run: NaN, held over.)
double sm_element(const Json& values, double index) {
    if (std::isnan(index) || std::isinf(index) || index != std::floor(index)) return NaN;
    // Julia's `Int(index)`: an index below -2^63 is its InexactError, where JavaScript reads
    // no value there -- reproduced as it stands.
    long long i = jl_to_int(index);
    if (i < 0 || i >= static_cast<long long>(values.size())) return NaN;
    const Json& v = values[static_cast<std::size_t>(i)];
    return v.is_number() ? v.as_double() : NaN;
}

/// `((spec.pos ?? 0) + at) % length`, with JavaScript's `+` and `%`.
double sm_list_index(const Json* pos, long long at, std::size_t len) {
    static const Json zero(0);
    if (pd_nullish(pos)) pos = &zero;
    double total = pos->is_string() ? pd_string_to_number(pos->as_string() + pd_js_number_str(static_cast<double>(at)))
                                    : pd_to_number(pos) + static_cast<double>(at);
    if (!std::isfinite(total)) return NaN;
    return std::fmod(total, static_cast<double>(len));
}

}  // namespace

std::uint32_t sm_to_uint32(const Json* v) {
    double x = pd_to_number(v);
    if (!std::isfinite(x)) return 0;
    double r = std::fmod(std::trunc(x), 4294967296.0);
    if (r < 0) r += 4294967296.0;
    return static_cast<std::uint32_t>(r);
}

std::vector<double> take_uniforms(Mulberry32& g, long long n) {
    std::vector<double> out = jl_zeros(jl_vector_count(n > 0 ? n : 0));
    for (double& x : out) x = g.next();
    return out;
}

std::uint32_t fnv_hash(std::string_view text) {
    std::uint32_t h = 0x811c9dc5u;
    for (std::uint16_t u : utf16_units(text)) h = (h ^ static_cast<std::uint32_t>(u)) * 0x01000193u;
    return h;
}

Mulberry32 stream_for(std::uint32_t seed_bits, std::string_view name) { return Mulberry32(sm_mix(seed_bits, fnv_hash(name))); }

Mulberry32 stream_for(const Json& seed, const Json* name) {
    return stream_for(sm_to_uint32(seed), pd_nullish(name) ? std::string() : pd_js_str(name));
}

std::vector<double> uniforms(long long n, Mulberry32& g, bool latin) {
    if (n < 0) throw ArgumentError("Invalid typed array length: a column cannot hold fewer than no uniforms");
    if (!latin) return take_uniforms(g, n);
    std::vector<double> first = take_uniforms(g, n);
    std::vector<double> out = jl_zeros(jl_vector_count(n));
    double dn = static_cast<double>(n);
    for (long long i = 0; i < n; i++) out[static_cast<std::size_t>(i)] = (static_cast<double>(i) + first[static_cast<std::size_t>(i)]) / dn;
    // Fisher-Yates: otherwise every parameter would rise together through the run and the
    // sample would lie on a diagonal. Every step's pick is drawn first, then the swaps made.
    if (n > 1) {
        std::vector<long long> picks(static_cast<std::size_t>(n - 1));
        for (long long s = 0; s < n - 1; s++)
            picks[static_cast<std::size_t>(s)] = static_cast<long long>(std::floor(g.next() * static_cast<double>(n - s)));
        for (long long s = 0; s < n - 1; s++) {
            std::size_t i = static_cast<std::size_t>(n - 1 - s);
            std::size_t j = static_cast<std::size_t>(picks[static_cast<std::size_t>(s)]);
            std::swap(out[i], out[j]);
        }
    }
    return out;
}

double value_at_probability(const Json& spec, double u, long long at) {
    if (!pd_truthy(&spec) || pd_meta(pd_prop(spec, "kind")) == nullptr || !pdf_complete(spec)) return NaN;
    if (spec.get("kind") == "pg") {
        const Json* v = pd_prop(spec, "values");
        if (pd_nullish(v) || !v->is_array() || v->empty()) return NaN;
        std::size_t len = v->size();
        const Json* inorder = pd_prop(spec, "inorder");
        if (inorder != nullptr && inorder->is_bool() && !inorder->as_bool()) {
            double x = u * static_cast<double>(len);
            return sm_element(*v, pd_jmin(static_cast<double>(len - 1), std::isfinite(x) ? std::floor(x) : x));
        }
        return sm_element(*v, sm_list_index(pd_prop(spec, "pos"), at, len));
    }
    // Truncation is the same curve read between two probabilities rather than between 0 and
    // 1 -- never by rejection.
    ProbabilityCuts cuts = probability_cuts(spec);
    double q = pd_jmin(1 - 1e-12, pd_jmax(1e-12, cuts.lo + u * (cuts.hi - cuts.lo)));
    double v = pdf_quantile(spec, q);
    if (cuts.reversed) return v;
    const Json* trmin = pd_prop(spec, "trmin");
    const Json* trmax = pd_prop(spec, "trmax");
    if (!pd_nullish(trmin) && v < pd_to_number(trmin)) return pd_to_number(trmin);
    if (!pd_nullish(trmax) && v > pd_to_number(trmax)) return pd_to_number(trmax);
    return v;
}

ValueDrawer::ValueDrawer(const Json& spec_) : spec(spec_) {
    if (!pd_truthy(&spec) || pd_meta(pd_prop(spec, "kind")) == nullptr || !pdf_complete(spec)) {
        kind = Kind::None;
        return;
    }
    const Json& k = spec.get("kind");
    if (k == "pg") {
        kind = Kind::List;
        return;
    }
    ProbabilityCuts cuts = probability_cuts(spec);
    auto bound = [&](const char* key) {
        const Json* v = pd_prop(spec, key);
        return pd_nullish(v) ? NaN : pd_to_number(v);
    };
    const Json* p = pd_prop(spec, "params");
    static const Json empty = Json::object();
    if (pd_nullish(p)) p = &empty;
    kind = Kind::Other;
    if (k == "unif") {
        kind = Kind::Unif;
        a = pd_param(p, "min");
        b = pd_param(p, "max") - a;
    } else if (k == "triang" || k == "dtriang") {
        kind = k == "triang" ? Kind::Triang : Kind::Dtriang;
        a = pd_param(p, "min");
        b = pd_param(p, "max");
        c = pd_param(p, "mode");
        d = b - a;
        e = c - a;
        f = b - c;
    } else if (k == "logu") {
        kind = Kind::Logu;
        a = js_log(pd_param(p, "min"));
        b = js_log(pd_param(p, "max")) - a;
    } else if (k == "logt" || k == "logdt") {
        kind = k == "logt" ? Kind::Logt : Kind::Logdt;
        a = js_log(pd_param(p, "min"));
        b = js_log(pd_param(p, "max"));
        c = js_log(pd_param(p, "mode"));
        d = b - a;
        e = c - a;
        f = b - c;
    } else if (k == "norm") {
        kind = Kind::Norm;
        a = pd_param(p, "mean");
        b = pd_param(p, "sd");
    } else if (k == "Logn4" || k == "logn" || k == "logn5") {
        auto ls = pd_log_space(spec);
        if (ls) {
            kind = Kind::Logn;
            a = ls->first;
            b = ls->second;
        }
    }
    lo = cuts.lo;
    span = cuts.hi - cuts.lo;
    reversed = cuts.reversed;
    trmin = bound("trmin");
    trmax = bound("trmax");
}

double draw_value(const ValueDrawer& dr, double u, long long at) {
    using K = ValueDrawer::Kind;
    K k = dr.kind;
    if (k == K::None) return NaN;
    if (k == K::List) return value_at_probability(dr.spec, u, at);
    double q = pd_jmin(1 - 1e-12, pd_jmax(1e-12, dr.lo + u * dr.span));
    // `pdf_quantile` at q, each shape's arithmetic as it is there
    double a = dr.a, b = dr.b, c = dr.c, d = dr.d, e = dr.e, f = dr.f;
    (void)c;
    double v;
    switch (k) {
        case K::Unif: v = a + q * b; break;
        case K::Triang: v = q <= e / d ? a + pd_sqrt((q * d) * e) : b - pd_sqrt(((1 - q) * d) * f); break;
        case K::Dtriang: v = q <= 0.5 ? a + pd_sqrt(2 * q) * e : b - f * pd_sqrt(2 * (1 - q)); break;
        case K::Logu: v = js_exp(a + q * b); break;
        case K::Logt: v = js_exp(q <= e / d ? a + pd_sqrt((q * d) * e) : b - pd_sqrt(((1 - q) * d) * f)); break;
        case K::Logdt: v = js_exp(q <= 0.5 ? a + pd_sqrt(2 * q) * e : b - f * pd_sqrt(2 * (1 - q))); break;
        case K::Norm: {
            std::optional<double> z = normal_probit(q);
            v = a + b * (z ? *z : 0.0);
            break;
        }
        case K::Logn: {
            std::optional<double> z = normal_probit(q);
            v = js_exp(a + b * (z ? *z : 0.0));
            break;
        }
        default: v = NaN; break;
    }
    if (dr.reversed) return v;
    if (!std::isnan(dr.trmin) && v < dr.trmin) return dr.trmin;
    if (!std::isnan(dr.trmax) && v > dr.trmax) return dr.trmax;
    return v;
}

Json PlanEntry::json() const {
    Json idx = Json::object();
    for (const auto& [list, name_] : index) idx.set(list, Json(name_));
    return Json::object({{"slot", Json(slot)}, {"name", Json(name)}, {"index", idx}, {"spec", spec}});
}

std::vector<PlanEntry> distributed_slots(const System& sys) {
    const Builder& b = *sys.builder;
    std::vector<PlanEntry> out;
    for (const auto& pt : b.point_layout) {
        const Json& spec = pt->spec;
        if (!(pd_truthy(&spec) && pdf_complete(spec))) continue;
        out.push_back(PlanEntry{pt->slot, pd_js_str(Json(pt->name)) + "@" + pd_js_number_str(pt->at), pt->index, spec});
    }
    const IndexSpace& space = *b.space;
    for (const auto& entry : b.param_layout) {
        const std::vector<std::string>& dims = entry->dims;
        for (int off = 0; off < entry->width; off++) {
            Tup tup = dims.empty() ? Tup() : tuple_by_list(space, dims, off);
            // Read where the value is read: with the active scenario put back in, so that a
            // parameter given a distribution per scenario draws from the one of the scenario
            // that runs. Named without it, as the slot is.
            Tup at = space.pin_scenario(strings_of(entry->block.get("index_lists")), tup);
            Json spec = value_at(entry->block, "pdf", at);
            if (!(pd_truthy(&spec) && pdf_complete(spec))) continue;
            out.push_back(PlanEntry{entry->base + off, entry->name, tup, spec});
        }
    }
    return out;
}

}  // namespace kompartment
