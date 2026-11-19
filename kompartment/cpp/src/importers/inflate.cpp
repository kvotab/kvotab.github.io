#include "importers/inflate.hpp"

#include <algorithm>
#include <climits>
#include <cstdint>
#include <cstdio>

#ifdef KOMPARTMENT_HAVE_ZLIB
#include <zlib.h>
#endif

namespace kompartment::eco {

namespace {

// --- this engine's own inflater: zlib's inflate.c, state for state ----------------------------

constexpr int MAXBITS = 15;

// A canonical Huffman code as zlib's inflate_table accepts it: the lengths counted, the symbols in
// code order. `max` 0 is a code with no symbols, which zlib takes and reads as one bit that is
// no symbol at all.
struct Code {
    unsigned short count[MAXBITS + 1] = {};
    unsigned short symbol[320] = {};
    int max = 0;
};

enum class CodeType { Codes, Lens, Dists };

// zlib's inflate_table: false for an over-subscribed set of lengths, or an incomplete one --
// except a lengths' or distances' code of one symbol of one bit.
bool build(Code& h, const unsigned short* lens, unsigned n, CodeType type) {
    for (int len = 0; len <= MAXBITS; len++) h.count[len] = 0;
    for (unsigned sym = 0; sym < n; sym++) h.count[lens[sym]]++;
    int max = MAXBITS;
    while (max >= 1 && h.count[max] == 0) max--;
    h.max = max;
    if (max == 0) return true;   // no symbols, but wait for decoding to report error
    int left = 1;
    for (int len = 1; len <= MAXBITS; len++) {
        left <<= 1;
        left -= h.count[len];
        if (left < 0) return false;   // over-subscribed
    }
    if (left > 0 && (type == CodeType::Codes || max != 1)) return false;   // incomplete
    unsigned short offs[MAXBITS + 2] = {};
    for (int len = 1; len < MAXBITS; len++) offs[len + 1] = static_cast<unsigned short>(offs[len] + h.count[len]);
    for (unsigned sym = 0; sym < n; sym++)
        if (lens[sym] != 0) h.symbol[offs[lens[sym]]++] = static_cast<unsigned short>(sym);
    return true;
}

const unsigned short LBASE[29] = {3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258};
const unsigned short LEXT[29] = {0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0};
const unsigned short DBASE[30] = {1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577};
const unsigned short DEXT[30] = {0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13};
const unsigned short ORDER[19] = {16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15};

struct Fixed {
    Code lens, dists;
    Fixed() {
        unsigned short l[288];
        unsigned sym = 0;
        while (sym < 144) l[sym++] = 8;
        while (sym < 256) l[sym++] = 9;
        while (sym < 280) l[sym++] = 7;
        while (sym < 288) l[sym++] = 8;
        build(lens, l, 288, CodeType::Lens);
        for (sym = 0; sym < 32; sym++) l[sym] = 5;
        build(dists, l, 32, CodeType::Dists);
    }
};

const Fixed& fixed_codes() {
    static const Fixed f;
    return f;
}

class Inflater {
public:
    enum class Status { Stopped, End, Error };   // Stopped: for want of output room or of input

    Inflater(const unsigned char* in, std::size_t n) : in_(in), n_(n) {}

    std::string msg;

    // Inflates into `out` until it holds `cap` bytes and more are to be written, the input runs
    // out, the stream ends or it is found damaged -- each as zlib's inflate() would stop.
    Status run(std::string& out, std::size_t cap) {
        for (;;) {
            switch (mode_) {
                case Mode::Type: {
                    if (last_) {
                        drop(bits_ & 7);
                        mode_ = Mode::Done;   // a raw stream has no check value
                        break;
                    }
                    if (!need(3)) return Status::Stopped;
                    last_ = peek(1) != 0;
                    drop(1);
                    switch (peek(2)) {
                        case 0: mode_ = Mode::Stored; break;
                        case 1:
                            lencode_ = &fixed_codes().lens;
                            distcode_ = &fixed_codes().dists;
                            mode_ = Mode::Len;
                            break;
                        case 2: mode_ = Mode::Table; break;
                        default: fail("invalid block type"); break;
                    }
                    drop(2);
                    break;
                }
                case Mode::Stored: {
                    drop(bits_ & 7);
                    if (!need(32)) return Status::Stopped;
                    if ((hold_ & 0xffff) != (((hold_ >> 16) ^ 0xffff) & 0xffff)) {
                        fail("invalid stored block lengths");
                        break;
                    }
                    length_ = static_cast<unsigned>(hold_ & 0xffff);
                    hold_ = 0;
                    bits_ = 0;
                    mode_ = Mode::Copy;
                    break;
                }
                case Mode::Copy: {
                    if (length_) {
                        std::size_t copy = length_;
                        copy = std::min(copy, n_ - pos_);
                        copy = std::min(copy, cap - out.size());
                        if (copy == 0) return Status::Stopped;
                        out.append(reinterpret_cast<const char*>(in_ + pos_), copy);
                        pos_ += copy;
                        length_ -= static_cast<unsigned>(copy);
                        break;
                    }
                    mode_ = Mode::Type;
                    break;
                }
                case Mode::Table: {
                    if (!need(14)) return Status::Stopped;
                    nlen_ = peek(5) + 257;
                    drop(5);
                    ndist_ = peek(5) + 1;
                    drop(5);
                    ncode_ = peek(4) + 4;
                    drop(4);
                    if (nlen_ > 286 || ndist_ > 30) {
                        fail("too many length or distance symbols");
                        break;
                    }
                    have_ = 0;
                    mode_ = Mode::LenLens;
                    break;
                }
                case Mode::LenLens: {
                    while (have_ < ncode_) {
                        if (!need(3)) return Status::Stopped;
                        lens_[ORDER[have_++]] = static_cast<unsigned short>(peek(3));
                        drop(3);
                    }
                    while (have_ < 19) lens_[ORDER[have_++]] = 0;
                    if (!build(codecode_, lens_, 19, CodeType::Codes)) {
                        fail("invalid code lengths set");
                        break;
                    }
                    have_ = 0;
                    mode_ = Mode::CodeLens;
                    break;
                }
                case Mode::CodeLens: {
                    bool bad = false;
                    while (have_ < nlen_ + ndist_) {
                        int sym = 0, len = 0;
                        const Decoded d = decode(codecode_, sym, len);
                        if (d == Decoded::Need) return Status::Stopped;
                        if (d == Decoded::Invalid) sym = 0;   // a code of no symbols reads as length 0
                        if (sym < 16) {
                            drop(static_cast<unsigned>(len));
                            lens_[have_++] = static_cast<unsigned short>(sym);
                            continue;
                        }
                        unsigned short value = 0;
                        unsigned copy = 0;
                        if (sym == 16) {
                            if (!need(static_cast<unsigned>(len) + 2)) return Status::Stopped;
                            drop(static_cast<unsigned>(len));
                            if (have_ == 0) {
                                fail("invalid bit length repeat");
                                bad = true;
                                break;
                            }
                            value = lens_[have_ - 1];
                            copy = 3 + peek(2);
                            drop(2);
                        } else if (sym == 17) {
                            if (!need(static_cast<unsigned>(len) + 3)) return Status::Stopped;
                            drop(static_cast<unsigned>(len));
                            copy = 3 + peek(3);
                            drop(3);
                        } else {
                            if (!need(static_cast<unsigned>(len) + 7)) return Status::Stopped;
                            drop(static_cast<unsigned>(len));
                            copy = 11 + peek(7);
                            drop(7);
                        }
                        if (have_ + copy > nlen_ + ndist_) {
                            fail("invalid bit length repeat");
                            bad = true;
                            break;
                        }
                        while (copy--) lens_[have_++] = value;
                    }
                    if (bad) break;
                    if (lens_[256] == 0) {
                        fail("invalid code -- missing end-of-block");
                        break;
                    }
                    if (!build(dynlens_, lens_, nlen_, CodeType::Lens)) {
                        fail("invalid literal/lengths set");
                        break;
                    }
                    if (!build(dyndists_, lens_ + nlen_, ndist_, CodeType::Dists)) {
                        fail("invalid distances set");
                        break;
                    }
                    lencode_ = &dynlens_;
                    distcode_ = &dyndists_;
                    mode_ = Mode::Len;
                    break;
                }
                case Mode::Len: {
                    int sym = 0, len = 0;
                    const Decoded d = decode(*lencode_, sym, len);
                    if (d == Decoded::Need) return Status::Stopped;
                    drop(static_cast<unsigned>(len));
                    if (d == Decoded::Invalid || sym > 285) {
                        fail("invalid literal/length code");
                        break;
                    }
                    if (sym < 256) {
                        length_ = static_cast<unsigned>(sym);
                        mode_ = Mode::Lit;
                        break;
                    }
                    if (sym == 256) {
                        mode_ = Mode::Type;
                        break;
                    }
                    length_ = LBASE[sym - 257];
                    extra_ = LEXT[sym - 257];
                    mode_ = Mode::LenExt;
                    break;
                }
                case Mode::LenExt: {
                    if (extra_) {
                        if (!need(extra_)) return Status::Stopped;
                        length_ += peek(extra_);
                        drop(extra_);
                    }
                    mode_ = Mode::Dist;
                    break;
                }
                case Mode::Dist: {
                    int sym = 0, len = 0;
                    const Decoded d = decode(*distcode_, sym, len);
                    if (d == Decoded::Need) return Status::Stopped;
                    drop(static_cast<unsigned>(len));
                    if (d == Decoded::Invalid || sym > 29) {
                        fail("invalid distance code");
                        break;
                    }
                    offset_ = DBASE[sym];
                    extra_ = DEXT[sym];
                    mode_ = Mode::DistExt;
                    break;
                }
                case Mode::DistExt: {
                    if (extra_) {
                        if (!need(extra_)) return Status::Stopped;
                        offset_ += peek(extra_);
                        drop(extra_);
                    }
                    mode_ = Mode::Match;
                    break;
                }
                case Mode::Match: {
                    if (out.size() >= cap) return Status::Stopped;
                    // Everything written so far is the window (a distance is at most 32768).
                    if (offset_ > out.size()) {
                        fail("invalid distance too far back");
                        break;
                    }
                    std::size_t copy = std::min<std::size_t>(length_, cap - out.size());
                    length_ -= static_cast<unsigned>(copy);
                    std::size_t from = out.size() - offset_;
                    while (copy--) out.push_back(out[from++]);
                    if (length_ == 0) mode_ = Mode::Len;
                    break;
                }
                case Mode::Lit: {
                    if (out.size() >= cap) return Status::Stopped;
                    out.push_back(static_cast<char>(length_));
                    mode_ = Mode::Len;
                    break;
                }
                case Mode::Done: return Status::End;
                case Mode::Bad: return Status::Error;
            }
        }
    }

private:
    enum class Mode { Type, Stored, Copy, Table, LenLens, CodeLens, Len, LenExt, Dist, DistExt, Match, Lit, Done, Bad };
    enum class Decoded { Ok, Need, Invalid };

    void fail(const char* message) {
        msg = message;
        mode_ = Mode::Bad;
    }

    // At least k bits in hand, a byte at a time; false when the input runs out first.
    bool need(unsigned k) {
        while (bits_ < k) {
            if (pos_ >= n_) return false;
            hold_ |= static_cast<std::uint64_t>(in_[pos_++]) << bits_;
            bits_ += 8;
        }
        return true;
    }
    unsigned peek(unsigned k) const { return static_cast<unsigned>(hold_ & ((std::uint64_t{1} << k) - 1)); }
    void drop(unsigned k) {
        hold_ >>= k;
        bits_ -= k;
    }

    // One symbol, nothing taken from the input until it is whole: `len` is its length. A pattern
    // no symbol has (an incomplete code of one one-bit symbol, or a code of none) is Invalid after
    // as many bits as zlib's table gives it.
    Decoded decode(const Code& h, int& sym, int& len) {
        if (h.max == 0) {
            if (!need(1)) return Decoded::Need;
            len = 1;
            return Decoded::Invalid;
        }
        int code = 0, first = 0, index = 0;
        for (int l = 1; l <= h.max; l++) {
            if (!need(static_cast<unsigned>(l))) return Decoded::Need;
            code |= static_cast<int>((hold_ >> (l - 1)) & 1);
            const int count = h.count[l];
            if (code - count < first) {
                sym = h.symbol[index + (code - first)];
                len = l;
                return Decoded::Ok;
            }
            index += count;
            first += count;
            first <<= 1;
            code <<= 1;
        }
        len = h.max;
        return Decoded::Invalid;
    }

    const unsigned char* in_;
    std::size_t n_, pos_ = 0;
    std::uint64_t hold_ = 0;
    unsigned bits_ = 0;
    Mode mode_ = Mode::Type;
    bool last_ = false;
    unsigned length_ = 0, offset_ = 0, extra_ = 0;
    unsigned nlen_ = 0, ndist_ = 0, ncode_ = 0, have_ = 0;
    unsigned short lens_[320] = {};
    Code codecode_, dynlens_, dyndists_;
    const Code* lencode_ = nullptr;
    const Code* distcode_ = nullptr;
};

// The first size of the output buffer, as `clamp(size_hint + 1, 1024, max(max_length, 1))` gives it.
std::size_t first_size(std::size_t size_hint, std::size_t max_length) {
    const std::size_t x = size_hint + 1, lo = 1024, hi = std::max<std::size_t>(max_length, 1);
    return x > hi ? hi : x < lo ? lo : x;
}

InflateResult builtin_inflate(std::string_view src, std::size_t max_length, std::size_t size_hint) {
    InflateResult r;
    Inflater inf(reinterpret_cast<const unsigned char*>(src.data()), src.size());
    std::size_t cap = first_size(size_hint, max_length);
    r.out.reserve(std::min<std::size_t>(cap, 1 << 26));
    while (true) {
        if (r.out.size() == cap) {
            if (r.out.size() >= max_length) break;
            cap = std::min(std::max<std::size_t>(2 * cap, 1024), max_length);
        }
        const Inflater::Status s = inf.run(r.out, cap);
        if (s == Inflater::Status::End) {
            r.eof = true;
            break;
        }
        if (s == Inflater::Status::Error) {
            r.damage = inf.msg;
            break;
        }
        // More room helps only when the output filled up.
        if (r.out.size() != cap) break;
    }
    return r;
}

#ifdef KOMPARTMENT_HAVE_ZLIB
InflateResult zlib_inflate(std::string_view src, std::size_t max_length, std::size_t size_hint) {
    InflateResult r;
    z_stream z{};
    if (inflateInit2(&z, -15) != Z_OK) {
        r.damage = "Error -2 while decompressing data";
        return r;
    }
    std::string& out = r.out;
    out.resize(first_size(size_hint, max_length));
    std::size_t produced = 0;
    z.next_in = reinterpret_cast<Bytef*>(const_cast<char*>(src.data()));
    z.avail_in = static_cast<uInt>(std::min<std::size_t>(src.size(), UINT_MAX));
    while (true) {
        if (produced == out.size()) {
            if (produced >= max_length) break;
            out.resize(std::min(std::max<std::size_t>(2 * out.size(), 1024), max_length));
        }
        z.next_out = reinterpret_cast<Bytef*>(out.data() + produced);
        z.avail_out = static_cast<uInt>(out.size() - produced);
        const uInt before = z.avail_out;
        const int rc = inflate(&z, Z_SYNC_FLUSH);
        produced += before - z.avail_out;
        if (rc == Z_STREAM_END) {
            r.eof = true;
            break;
        }
        if (rc == Z_OK || rc == Z_BUF_ERROR) {
            if (z.avail_out != 0) break;
            continue;
        }
        // CPython's `zlib_error`, after the importer's `split(': ', 1)[-1]`.
        if (z.msg) {
            std::string m(z.msg);
            if (m.size() > 200) m.resize(200);
            r.damage = m;
        } else if (rc == Z_STREAM_ERROR) {
            r.damage = "inconsistent stream state";
        } else if (rc == Z_DATA_ERROR) {
            r.damage = "invalid input data";
        } else {
            r.damage = "Error " + std::to_string(rc) + " while decompressing data";
        }
        break;
    }
    inflateEnd(&z);
    out.resize(produced);
    return r;
}
#endif

}  // namespace

bool have_zlib() {
#ifdef KOMPARTMENT_HAVE_ZLIB
    return true;
#else
    return false;
#endif
}

InflateResult raw_inflate(std::string_view src, std::size_t max_length, std::size_t size_hint, bool with_zlib) {
#ifdef KOMPARTMENT_HAVE_ZLIB
    if (with_zlib) return zlib_inflate(src, max_length, size_hint);
#endif
    (void)with_zlib;
    return builtin_inflate(src, max_length, size_hint);
}

}  // namespace kompartment::eco
