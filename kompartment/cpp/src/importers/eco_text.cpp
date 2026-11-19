#include "importers/eco_text.hpp"

#include <cstdint>
#include <cstdio>

#include "importers/eco_maps.hpp"

namespace kompartment::eco {

namespace {

enum class Step { Ok, End, Start, Cont };

// One step of CPython's UTF-8 decoder at byte i of b[0, n): the kind, and how many bytes the
// character (or the error's range) takes. An error is `End` for a sequence cut short by the end
// (the rest of the bytes are its range), `Start` for a byte that cannot begin one and `Cont`
// for a sequence broken after its first k bytes.
Step utf8_step(std::string_view b, std::size_t i, std::size_t n, std::size_t& k) {
    auto byte = [&](std::size_t j) { return static_cast<unsigned char>(b[j]); };
    auto iscont = [](unsigned char x) { return (x & 0xc0) == 0x80; };
    const unsigned char c = byte(i);
    if (c < 0x80) {
        k = 1;
        return Step::Ok;
    }
    const std::size_t left = n - i;
    if (c < 0xe0) {
        if (c < 0xc2) {
            k = 1;
            return Step::Start;
        }
        if (left < 2) {
            k = left;
            return Step::End;
        }
        if (!iscont(byte(i + 1))) {
            k = 1;
            return Step::Cont;
        }
        k = 2;
        return Step::Ok;
    }
    if (c < 0xf0) {
        if (left < 3) {
            if (left < 2) {
                k = left;
                return Step::End;
            }
            const unsigned char c2 = byte(i + 1);
            if (!iscont(c2) || (c2 < 0xa0 ? c == 0xe0 : c == 0xed)) {
                k = 1;
                return Step::Cont;
            }
            k = left;
            return Step::End;
        }
        const unsigned char c2 = byte(i + 1), c3 = byte(i + 2);
        k = 1;
        if (!iscont(c2)) return Step::Cont;
        if (c == 0xe0 && c2 < 0xa0) return Step::Cont;
        if (c == 0xed && c2 >= 0xa0) return Step::Cont;
        k = 2;
        if (!iscont(c3)) return Step::Cont;
        k = 3;
        return Step::Ok;
    }
    if (c < 0xf5) {
        if (left < 4) {
            if (left < 2) {
                k = left;
                return Step::End;
            }
            const unsigned char c2 = byte(i + 1);
            if (!iscont(c2) || (c2 < 0x90 ? c == 0xf0 : c == 0xf4)) {
                k = 1;
                return Step::Cont;
            }
            if (left < 3) {
                k = left;
                return Step::End;
            }
            if (!iscont(byte(i + 2))) {
                k = 2;
                return Step::Cont;
            }
            k = left;
            return Step::End;
        }
        const unsigned char c2 = byte(i + 1), c3 = byte(i + 2), c4 = byte(i + 3);
        k = 1;
        if (!iscont(c2)) return Step::Cont;
        if (c == 0xf0 && c2 < 0x90) return Step::Cont;
        if (c == 0xf4 && c2 >= 0x90) return Step::Cont;
        k = 2;
        if (!iscont(c3)) return Step::Cont;
        k = 3;
        if (!iscont(c4)) return Step::Cont;
        k = 4;
        return Step::Ok;
    }
    k = 1;
    return Step::Start;
}

const char* REPLACEMENT = "\xef\xbf\xbd";

}  // namespace

bool is_valid_utf8(std::string_view b) {
    const std::size_t n = b.size();
    for (std::size_t i = 0; i < n;) {
        std::size_t k = 1;
        if (utf8_step(b, i, n, k) != Step::Ok) return false;
        i += k;
    }
    return true;
}

std::string utf8_replace(std::string_view b) {
    if (is_valid_utf8(b)) return std::string(b);
    const std::size_t n = b.size();
    std::string out;
    out.reserve(n + 16);
    for (std::size_t i = 0; i < n;) {
        std::size_t k = 1;
        if (utf8_step(b, i, n, k) == Step::Ok) out.append(b.substr(i, k));
        else out += REPLACEMENT;
        i += k;
    }
    return out;
}

std::string utf8_strict(std::string_view b) {
    const std::size_t n = b.size();
    for (std::size_t i = 0; i < n;) {
        std::size_t k = 1;
        const Step kind = utf8_step(b, i, n, k);
        if (kind != Step::Ok) {
            const char* reason = kind == Step::End ? "unexpected end of data" : kind == Step::Start ? "invalid start byte" : "invalid continuation byte";
            char buf[160];
            if (k == 1)
                std::snprintf(buf, sizeof buf, "'utf-8' codec can't decode byte 0x%02x in position %zu: %s",
                              static_cast<unsigned>(static_cast<unsigned char>(b[i])), i, reason);
            else
                std::snprintf(buf, sizeof buf, "'utf-8' codec can't decode bytes in position %zu-%zu: %s", i, i + k - 1, reason);
            throw EcoDecodeError(buf);
        }
        i += k;
    }
    return std::string(b);
}

std::string utf16_replace(std::string_view b, std::size_t start, bool little_endian) {
    const std::size_t n = b.size();
    std::string out;
    out.reserve(n > start ? (n - start) * 3 / 2 : 0);
    auto unit = [&](std::size_t i) -> std::uint32_t {
        const std::uint32_t x = static_cast<unsigned char>(b[i]), y = static_cast<unsigned char>(b[i + 1]);
        return little_endian ? (y << 8) | x : (x << 8) | y;
    };
    std::size_t q = start;
    while (true) {
        if (q >= n || n - q < 2) {
            if (q < n) out += REPLACEMENT;   // "truncated data": the odd byte
            break;
        }
        const std::uint32_t ch = unit(q);
        q += 2;
        if (ch < 0xd800 || ch > 0xdfff) {
            put_char(out, ch);
            continue;
        }
        if (ch >= 0xdc00) {   // a low surrogate on its own: "illegal encoding"
            out += REPLACEMENT;
            continue;
        }
        if (q >= n || n - q < 2) {   // "unexpected end of data": the rest is one error
            out += REPLACEMENT;
            break;
        }
        const std::uint32_t ch2 = unit(q);
        if (ch2 >= 0xdc00 && ch2 <= 0xdfff) {
            q += 2;
            put_char(out, 0x10000 + ((ch - 0xd800) << 10) + (ch2 - 0xdc00));
        } else {   // "illegal UTF-16 surrogate": the high one alone
            out += REPLACEMENT;
        }
    }
    return out;
}

std::string without_bom(std::string text) {
    if (text.size() >= 3 && text.compare(0, 3, "\xef\xbb\xbf") == 0) text.erase(0, 3);
    return text;
}

std::string decode_xml_bytes(std::string_view b) {
    const std::size_t n = b.size();
    auto byte = [&](std::size_t j) { return static_cast<unsigned char>(b[j]); };
    if (n >= 2) {
        if (byte(0) == 0xfe && byte(1) == 0xff) return without_bom(utf16_replace(b, 2, false));
        if (byte(0) == 0xff && byte(1) == 0xfe) return without_bom(utf16_replace(b, 2, true));
    }
    if (n >= 3 && byte(0) == 0xef && byte(1) == 0xbb && byte(2) == 0xbf) return without_bom(utf8_replace(b.substr(3)));
    return without_bom(utf8_replace(b));
}

}  // namespace kompartment::eco
