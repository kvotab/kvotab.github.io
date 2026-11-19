// The Ecolego importer against the Julia package's (tools/ecoimport_fixtures.jl writes
// tests/fixtures/ecoimport.json), byte for byte: the pieces on their own -- bytes decoded as
// CPython decodes them, `Number()` as JavaScript and pdf.py read it, `toPrecision`,
// `toExponential` and dates, trimming, UTF-16 lengths and positions, identifiers, Python's
// `lower()` and `upper()` on every code point, Julia's `strip`, `localeCompare`, entities, the XML
// reader on every element of every document, distributions, `.version` files, deflate streams
// inflated within limits, archives read entry by entry -- and whole imports: model.xml texts made
// up to reach every branch, bare files in every encoding, and archives stored, deflated and damaged
// in every way the reader names, two of them past the 256 MB allowance. An import's answer is the
// project and the report as JSON, or the refusal in its words.
//
// Archives are inflated by the engine's own inflater, as zlib 1.3.1 (the Julia package's) inflates;
// where the build has a zlib, that is run on every stream and archive too, and on some thousands of
// streams deflated here and damaged at random, and must come out the same -- but for Apple's zlib,
// which says "invalid literal/length/distance code" where zlib says "invalid literal/length code"
// or "invalid distance code".
//
// KOMPARTMENT_ECO_FIXTURES=DIR adds the synthetic directory julia/tools/eco_fixtures.py
// --synthetic writes (outside the repository): every case of it imported and compared with the
// Julia package's answer the fixture file keeps by its id (when the case's input is the one the
// fixture saw), and with the Python package's answer the directory itself holds. Without it that
// part is skipped, and says so. KOMPARTMENT_FIXTURE_DUMPS=DIR writes every answer
// (`ecoimport-<n>.cpp.txt`, numbered as the tool numbers them) and a table of the cases
// (`ecoimport.cpp.txt`) there.

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "check.hpp"
#include "importers/eco.hpp"
#include "importers/eco_maps.hpp"
#include "importers/eco_pdf.hpp"
#include "importers/eco_text.hpp"
#include "importers/eco_unicode.hpp"
#include "importers/eco_zip.hpp"
#include "importers/inflate.hpp"
#include "importers/xml.hpp"
#include "util/json.hpp"

#ifdef KOMPARTMENT_HAVE_ZLIB
#include <zlib.h>
#endif

using namespace kompartment;

namespace {

std::string fnv(const std::string& bytes) {
    std::uint64_t h = 0xcbf29ce484222325ULL;
    for (unsigned char b : bytes) h = (h ^ b) * 0x100000001b3ULL;
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(h));
    return buf;
}
std::string kept(const std::string& bytes) { return "#" + fnv(bytes) + ":" + std::to_string(bytes.size()); }

std::string hex(const std::string& bytes) {
    static const char* digits = "0123456789abcdef";
    std::string out;
    for (unsigned char b : bytes) {
        out.push_back(digits[b >> 4]);
        out.push_back(digits[b & 15]);
    }
    return out;
}
std::string unhex(const std::string& text) {
    std::string out;
    for (std::size_t i = 0; i + 1 < text.size(); i += 2) out.push_back(static_cast<char>(std::stoi(text.substr(i, 2), nullptr, 16)));
    return out;
}
std::string bits(double x) {
    std::uint64_t u;
    std::memcpy(&u, &x, 8);
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(u));
    return buf;
}
double from_bits(const std::string& h) {
    const std::uint64_t u = std::stoull(h, nullptr, 16);
    double x;
    std::memcpy(&x, &u, 8);
    return x;
}
std::optional<std::string> opt(const Json& v) { return v.is_string() ? std::optional<std::string>(v.as_string()) : std::nullopt; }

// --- answers as the fixture keeps them ---------------------------------------------------------

const char* dumps() {
    const char* d = std::getenv("KOMPARTMENT_FIXTURE_DUMPS");
    return (d && *d) ? d : nullptr;
}
int count = 0;
std::vector<std::string> table;

// A refusal as its words, anything else as a hash; numbered and dumped as the tool does when
// `numbered`.
std::string answer(const std::string& what, const std::string& text, bool numbered = true) {
    const std::string out = text.rfind("error:", 0) == 0 ? text : kept(text);
    if (!numbered) return out;
    count++;
    if (const char* d = dumps()) {
        std::FILE* f = std::fopen((std::string(d) + "/ecoimport-" + std::to_string(count) + ".cpp.txt").c_str(), "wb");
        if (f) {
            std::fwrite(text.data(), 1, text.size(), f);
            std::fclose(f);
        }
    }
    table.push_back(std::to_string(count) + " " + what + " " + out);
    return out;
}

std::string import_answer(const std::function<eco::EcoImport()>& f) {
    try {
        eco::EcoImport r = f();
        return json_text(r.project, 2) + "\n" + json_text(r.report.to_json(), 2);
    } catch (const eco::EcoImportError& e) {
        return "error:EcoImportError:" + e.message;
    } catch (const eco::EcoArgumentError& e) {
        return "error:ArgumentError:" + e.message;
    } catch (const eco::EcoUnsupportedError& e) {
        return "error:ErrorException:" + e.message;
    }
}

// --- a deflate stream of n zero bytes, as the tool writes it ----------------------------------------

std::string zeros_deflate(long long n) {
    static const int LBASE[29] = {3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258};
    static const int LEXT[29] = {0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0};
    std::string out;
    std::uint64_t acc = 0;
    int nbits = 0;
    auto put = [&](std::uint64_t value, int n_) {
        acc |= value << nbits;
        nbits += n_;
        while (nbits >= 8) {
            out.push_back(static_cast<char>(acc & 0xff));
            acc >>= 8;
            nbits -= 8;
        }
    };
    auto code = [&](unsigned value, int n_) {
        for (int k = n_ - 1; k >= 0; k--) put((value >> k) & 1, 1);
    };
    auto litlen = [&](int sym) {
        if (sym <= 143) code(static_cast<unsigned>(0x30 + sym), 8);
        else if (sym <= 255) code(static_cast<unsigned>(0x190 + sym - 144), 9);
        else if (sym <= 279) code(static_cast<unsigned>(sym - 256), 7);
        else code(static_cast<unsigned>(0xc0 + sym - 280), 8);
    };
    auto match = [&](int len) {
        int k = 28;
        while (LBASE[k] > len) k--;
        litlen(257 + k);
        if (LEXT[k] > 0) put(static_cast<std::uint64_t>(len - LBASE[k]), LEXT[k]);
        code(0, 5);   // distance 1
    };
    put(1, 1);   // the last block
    put(1, 2);   // fixed codes
    if (n > 0) {
        litlen(0);
        long long left = n - 1;
        while (left >= 258) {
            match(258);
            left -= 258;
        }
        if (left >= 3) match(static_cast<int>(left));
        else
            for (long long k = 0; k < left; k++) litlen(0);
    }
    litlen(256);
    if (nbits > 0) put(0, 8 - nbits);
    return out;
}

std::string segments_bytes(const Json& segs) {
    std::string out;
    for (const Json& s : segs.arr()) out += s.has("hex") ? unhex(s.get("hex").as_string()) : zeros_deflate(s.get("zeros").as_int());
    return out;
}

// --- the XML reader and the archive reader, dumped as the tool dumps them --------------------------

std::string xml_dump(const std::string& src) {
    std::unique_ptr<eco::XmlDoc> doc;
    try {
        doc = eco::parse_xml(src);
    } catch (const eco::EcoXMLError& e) {
        return "error:" + e.message + "|" + (e.position ? std::to_string(*e.position) : std::string("none"));
    }
    std::string out;
    std::function<void(const eco::XmlNode&, int)> walk = [&](const eco::XmlNode& n, int d) {
        out += "E " + std::to_string(d) + " " + std::to_string(n.name->size()) + ":" + *n.name + " " + (n.self_closing ? "1" : "0") + " " +
               std::to_string(n.attrs.size());
        for (const auto& [k, v] : n.attrs) out += " " + std::to_string(k.size()) + ":" + k + "=" + std::to_string(v.size()) + ":" + v;
        const std::string t = eco::text(n), r = eco::trimmed_text(n);
        out += " T" + std::to_string(t.size()) + ":" + t + " R" + std::to_string(r.size()) + ":" + r + "\n";
        for (const eco::XmlNode* c : n.children) walk(*c, d + 1);
    };
    walk(*doc->root, 0);
    return out;
}

std::string archive_dump(const std::string& bytes, bool builtin) {
    std::optional<eco::EcoArchive> a;
    try {
        a.emplace(eco::unzip(bytes, builtin));
    } catch (const eco::EcoImportError& e) {
        return "error:EcoImportError:" + e.message;
    } catch (const eco::EcoUnsupportedError& e) {
        return "error:ErrorException:" + e.message;
    }
    std::string out;
    for (const std::string& name : a->names()) {
        out += std::to_string(name.size()) + ":" + name + " ";
        try {
            out += kept(a->get(name));
        } catch (const eco::EcoImportError& e) {
            out += "error:" + e.message;
        }
        out += "\n";
    }
    return out;
}

// --- the inflaters against each other -------------------------------------------------------------

#ifdef KOMPARTMENT_HAVE_ZLIB
std::string deflate_with(const std::string& raw, int level, int strategy) {
    z_stream s{};
    deflateInit2(&s, level, Z_DEFLATED, -15, 8, strategy);
    std::string out(deflateBound(&s, static_cast<uLong>(raw.size())) + 16, '\0');
    s.next_in = reinterpret_cast<Bytef*>(const_cast<char*>(raw.data()));
    s.avail_in = static_cast<uInt>(raw.size());
    s.next_out = reinterpret_cast<Bytef*>(out.data());
    s.avail_out = static_cast<uInt>(out.size());
    deflate(&s, Z_FINISH);
    out.resize(s.total_out);
    deflateEnd(&s);
    return out;
}
#endif

// The same answer, but for the words Apple's zlib gives a bad code where zlib names which.
const char* APPLE = "invalid literal/length/distance code";
bool same_but_apple(std::string with_zlib, const std::string& own) {
    if (with_zlib == own) return true;
    const std::size_t at = with_zlib.find(APPLE);
    if (at == std::string::npos) return false;
    for (const char* standard : {"invalid literal/length code", "invalid distance code"}) {
        std::string t = with_zlib;
        t.replace(at, std::strlen(APPLE), standard);
        if (t == own) return true;
    }
    return false;
}

struct Mix {
    std::uint64_t s;
    std::uint64_t next() {
        s += 0x9e3779b97f4a7c15ULL;
        std::uint64_t z = s;
        z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
        z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
        return z ^ (z >> 31);
    }
    std::size_t below(std::size_t n) { return n == 0 ? 0 : static_cast<std::size_t>(next() % n); }
};

}  // namespace

int main() {
    const Json fixture = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/ecoimport.json"));
    const bool zlib = eco::have_zlib();
    std::printf("inflating with the engine's own inflater%s\n", zlib ? ", and with the build's zlib to check it" : " (no zlib in this build to check it with)");

    // --- bytes as text.
    for (const Json& c : fixture.get("decoders").arr()) {
        const std::string in = unhex(c.get("in").as_string());
        const std::string what = "bytes " + c.get("in").as_string();
        CHECK_MSG(eco::is_valid_utf8(in) == c.get("valid").as_bool(), "valid: " + what);
        CHECK_MSG(hex(eco::utf8_replace(in)) == c.get("replace").as_string(), "utf8 replace: " + what);
        std::string strict;
        try {
            strict = hex(eco::utf8_strict(in));
        } catch (const eco::EcoDecodeError& e) {
            strict = "error:" + e.message;
        }
        CHECK_MSG(strict == c.get("strict").as_string(), "utf8 strict: " + what + ": " + strict);
        CHECK_MSG(hex(eco::utf16_replace(in, 0, false)) == c.get("be").as_string(), "utf16 be: " + what);
        CHECK_MSG(hex(eco::utf16_replace(in, 0, true)) == c.get("le").as_string(), "utf16 le: " + what);
        CHECK_MSG(hex(eco::utf16_replace(in, 2, false)) == c.get("be3").as_string(), "utf16 be from 2: " + what);
        CHECK_MSG(hex(eco::decode_xml_bytes(in)) == c.get("xml").as_string(), "xml bytes: " + what);
    }

    // --- numbers.
    for (const Json& c : fixture.get("numbers").arr()) {
        const std::string& in = c.get("in").as_string();
        CHECK_MSG(bits(eco::to_number(std::string_view(in))) == c.get("number").as_string(), "Number('" + in + "')");
        CHECK_MSG(bits(eco::pdf_number(in)) == c.get("pdf").as_string(), "pdf number '" + in + "'");
    }
    for (const Json& c : fixture.get("rounding").arr()) {
        const double x = from_bits(c.get("x").as_string());
        CHECK_MSG(bits(eco::round_significant(x, static_cast<int>(c.get("digits").as_int()))) == c.get("out").as_string(),
                  "toPrecision of " + check::bits(x));
    }
    for (const Json& c : fixture.get("exponential").arr()) {
        const double x = from_bits(c.get("x").as_string());
        CHECK_MSG(eco::to_exponential(x) == c.get("out").as_string(), "toExponential of " + check::bits(x) + ": " + eco::to_exponential(x));
    }
    for (const Json& c : fixture.get("dates").arr()) {
        const double ms = from_bits(c.get("ms").as_string());
        std::string out;
        try {
            out = eco::iso_date(ms);
        } catch (const eco::EcoArgumentError& e) {
            out = "error:" + e.message;
        }
        CHECK_MSG(out == c.get("out").as_string(), "date of " + check::bits(ms) + ": " + out);
    }

    // --- strings.
    for (const Json& c : fixture.get("strings").arr()) {
        const std::string& in = c.get("in").as_string();
        CHECK_MSG(eco::js_trim(in) == c.get("trim").as_string(), "trim '" + in + "'");
        CHECK_MSG(static_cast<long long>(eco::js_len(in)) == c.get("len").as_int(), "length of '" + in + "'");
        CHECK_MSG(eco::js_identifier(in) == c.get("identifier").as_string(), "identifier of '" + in + "'");
        CHECK_MSG(eco::py_lower(in) == c.get("lower").as_string(), "lower '" + in + "': " + eco::py_lower(in));
        CHECK_MSG(eco::py_upper(in) == c.get("upper").as_string(), "upper '" + in + "': " + eco::py_upper(in));
        CHECK_MSG(eco::julia_strip(in) == c.get("strip").as_string(), "strip '" + in + "'");
        const JArray& pos = c.get("pos").arr();
        bool same = pos.size() == in.size() + 1;
        for (std::size_t i = 0; same && i < pos.size(); i++) same = static_cast<long long>(eco::utf16_pos(in, i)) == pos[i].as_int();
        CHECK_MSG(same, "UTF-16 positions in '" + in + "'");
    }
    {
        // Every code point on its own, through each mapping.
        std::string lower, upper, jl, ju, flags;
        for (char32_t c = 0; c <= 0x10ffff; c++) {
            if (c >= 0xd800 && c <= 0xdfff) continue;
            std::string s;
            eco::put_char(s, c);
            lower += eco::py_lower(s);
            lower.push_back('\0');
            upper += eco::py_upper(s);
            upper.push_back('\0');
            eco::put_char(jl, eco_unicode::lower(c));
            eco::put_char(ju, eco_unicode::upper(c));
            flags.push_back(static_cast<char>((eco_unicode::is_cased(c) ? 1 : 0) | (eco::is_case_ignorable(c) ? 2 : 0)));
        }
        const Json& want = fixture.get("case");
        CHECK_MSG(kept(lower) == want.get("lower").as_string(), "lower() of every code point");
        CHECK_MSG(kept(upper) == want.get("upper").as_string(), "upper() of every code point");
        CHECK_MSG(kept(jl) == want.get("julia_lower").as_string(), "lowercase of every code point");
        CHECK_MSG(kept(ju) == want.get("julia_upper").as_string(), "uppercase of every code point");
        CHECK_MSG(kept(flags) == want.get("flags").as_string(), "cased and case-ignorable code points");
    }
    {
        std::vector<std::string> words;
        for (const Json& w : fixture.get("collation").get("words").arr()) words.push_back(w.as_string());
        std::stable_sort(words.begin(), words.end(), [](const std::string& a, const std::string& b) { return eco::collation_less(a, b); });
        const JArray& want = fixture.get("collation").get("sorted").arr();
        bool same = words.size() == want.size();
        for (std::size_t k = 0; same && k < words.size(); k++) same = words[k] == want[k].as_string();
        CHECK_MSG(same, "localeCompare order");
    }
    for (const Json& c : fixture.get("entities").arr())
        CHECK_MSG(eco::decode_entities(c.get("in").as_string()) == c.get("out").as_string(), "entities in '" + c.get("in").as_string() + "'");

    // --- the XML reader: the import cases' texts, and some of its own.
    std::map<std::string, const Json*> import_by_name;
    for (const Json& c : fixture.get("imports").arr()) import_by_name[c.get("name").as_string()] = &c;
    int documents = 0, own = 0;
    for (const Json& c : fixture.get("xml").arr()) {
        const bool named = c.has("case");
        const std::string what = named ? "xml " + c.get("case").as_string() : "xml " + std::to_string(++own);
        const std::string src = named ? import_by_name.at(c.get("case").as_string())->get("payload").as_string() : c.get("in").as_string();
        const std::string got = answer(what, xml_dump(src));
        CHECK_MSG(got == c.get("out").as_string(), what + ": " + got.substr(0, 200));
        documents++;
    }

    // --- distributions and versions.
    for (const Json& c : fixture.get("pdf").arr()) {
        std::optional<Json> spec = eco::parse_pdf(c.get("expr").as_string(), c.get("function").as_string());
        const std::string got = spec ? json_text(*spec, 0) : "nothing";
        CHECK_MSG(got == c.get("out").as_string(), "distribution '" + c.get("expr").as_string() + "': " + got);
    }
    for (const Json& c : fixture.get("versions").arr()) {
        std::optional<std::string> v = eco::version_in(c.get("in").as_string());
        CHECK_MSG(c.get("out").is_null() ? !v : (v && *v == c.get("out").as_string()), "version in '" + c.get("in").as_string() + "'");
    }

    // --- deflate streams inflated within limits, by zlib and by the engine's own inflater.
    int inflations = 0;
    for (const Json& c : fixture.get("inflate").arr()) {
        const std::string in = unhex(c.get("in").as_string());
        for (const Json& r : c.get("runs").arr()) {
            const std::size_t max_length = static_cast<std::size_t>(r.get("max").as_int()), hint = static_cast<std::size_t>(r.get("hint").as_int());
            const eco::InflateResult got = eco::raw_inflate(in, max_length, hint);
            const bool same = kept(got.out) == r.get("out").as_string() && got.eof == r.get("eof").as_bool() &&
                              (r.get("damage").is_null() ? !got.damage : (got.damage && *got.damage == r.get("damage").as_string()));
            CHECK_MSG(same, "inflate of " + c.get("in").as_string().substr(0, 40) + " max " + std::to_string(max_length) + ": " + kept(got.out) + " " +
                                (got.damage ? *got.damage : ""));
            if (zlib) {
                const eco::InflateResult z = eco::raw_inflate(in, max_length, hint, true);
                CHECK_MSG(z.out == got.out && z.eof == got.eof && same_but_apple(z.damage.value_or(""), got.damage.value_or("")),
                          "zlib's inflate of " + c.get("in").as_string().substr(0, 40) + ": " + z.damage.value_or(""));
            }
            inflations++;
        }
    }

    // --- archives read entry by entry, with each inflater.
    std::map<std::string, std::string> file_bytes;
    for (const Json& c : fixture.get("imports").arr())
        if (c.get("kind") == "file") {
            const std::string bytes = segments_bytes(c.get("payload"));
            CHECK_MSG(kept(bytes) == c.get("bytes").as_string(), "the bytes of " + c.get("name").as_string());
            file_bytes[c.get("name").as_string()] = bytes;
        }
    for (const Json& c : fixture.get("archives").arr()) {
        const std::string& name = c.get("name").as_string();
        const std::string text = archive_dump(file_bytes.at(name), false);
        const std::string got = answer("archive " + name, text);
        CHECK_MSG(got == c.get("out").as_string(), "archive " + name + ": " + got.substr(0, 300));
        if (zlib) CHECK_MSG(same_but_apple(archive_dump(file_bytes.at(name), true), text), "archive " + name + ": with zlib");
    }

    // --- whole imports.
    int imports = 0;
    for (const Json& c : fixture.get("imports").arr()) {
        const std::string& name = c.get("name").as_string();
        const std::optional<std::string> file_name = opt(c.get("file_name")), version = opt(c.get("version"));
        if (c.get("kind") == "xml") {
            const std::string got = answer("import " + name, import_answer([&] { return eco::import_model_xml(c.get("payload").as_string(), file_name, version); }));
            CHECK_MSG(got == c.get("out").as_string(), "import " + name + ": " + got.substr(0, 300));
        } else {
            const std::string text = import_answer([&] { return eco::import_eco_file(file_bytes.at(name), file_name, version); });
            const std::string got = answer("import " + name, text);
            CHECK_MSG(got == c.get("out").as_string(), "import " + name + ": " + got.substr(0, 300));
            if (zlib)
                CHECK_MSG(same_but_apple(import_answer([&] { return eco::import_eco_file(file_bytes.at(name), file_name, version, true); }), text),
                          "import " + name + ": with zlib");
        }
        imports++;
    }
    {
        // A path's name is the file's.
        const std::filesystem::path dir =
            std::filesystem::temp_directory_path() /
            ("kompartment-ecoimport-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        std::filesystem::create_directories(dir);
        const std::string path = (dir / "Named project.EAS").string();
        {
            std::FILE* f = std::fopen(path.c_str(), "wb");
            const std::string& bytes = file_bytes.at("stored");
            std::fwrite(bytes.data(), 1, bytes.size(), f);
            std::fclose(f);
        }
        const std::string by_path = import_answer([&] { return eco::import_eco_path(path); });
        const std::string by_bytes = import_answer([&] { return eco::import_eco_file(file_bytes.at("stored"), std::string("Named project.EAS")); });
        CHECK(by_path == by_bytes);
        CHECK(by_path.find("Imported from Named project.EAS.") != std::string::npos);
        std::filesystem::remove_all(dir);
        CHECK(eco::is_ecolego_path("a/b.eco") && eco::is_ecolego_path("B.EAS") && eco::is_ecolego_path("model.Xml"));
        CHECK(!eco::is_ecolego_path("model.json") && !eco::is_ecolego_path("eco") && !eco::is_ecolego_path("x.ecox"));
    }

    // --- the synthetic directory.
    int directory = 0, matched = 0, python = 0;
    if (const char* dir_env = std::getenv("KOMPARTMENT_ECO_FIXTURES"); dir_env && *dir_env) {
        const std::string dir(dir_env);
        std::map<std::string, const Json*> by_id;
        for (const Json& d : fixture.get("directory").arr()) by_id[d.get("id").as_string()] = &d;
        const Json manifest = parse_json(check::read_file(dir + "/manifest.json"));
        int unknown = 0, other_input = 0;
        for (const Json& rec : manifest.arr()) {
            if (rec.get("source") != "synthetic") continue;
            const std::string id = rec.get("id").as_string();
            const std::string kind = rec.get("kind").as_string();
            const std::string base = dir + "/cases/" + id;
            // A file read by its path is looked for beside the cases, wherever the directory now is.
            const std::string path =
                kind == "path" ? dir + "/cases/" + std::filesystem::path(rec.get("path").as_string()).filename().string() : base + ".payload";
            const std::string payload = check::read_file(path);
            const std::optional<std::string> file_name = opt(rec.get("file_name")), version = opt(rec.get("version"));
            auto run = [&](bool with_zlib) {
                return import_answer([&] {
                    if (kind == "xml") return eco::import_model_xml(payload, file_name, version);
                    if (kind == "file") return eco::import_eco_file(payload, file_name, version, with_zlib);
                    return eco::import_eco_path(path, version);
                });
            };
            const std::string text = run(false);
            const std::string got = answer("directory " + id, text);
            directory++;
            auto it = by_id.find(id);
            if (it == by_id.end()) {
                unknown++;
            } else if (it->second->get("payload").as_string() != kept(payload)) {
                other_input++;
            } else {
                CHECK_MSG(got == it->second->get("out").as_string(), id + " (" + rec.get("label").as_string() + "): " + got.substr(0, 300));
                matched++;
            }
            if (zlib && kind == "file") CHECK_MSG(same_but_apple(run(true), text), id + ": with zlib");
            // And what the Python package made of it, which the directory holds.
            std::string want;
            if (std::filesystem::exists(base + ".error.json")) {
                const Json e = parse_json(check::read_file(base + ".error.json"));
                const std::string& t = e.get("type").as_string();
                want = "error:" + (t == "ValueError" ? std::string("ArgumentError") : t == "NotImplementedError" ? std::string("ErrorException") : t) + ":" +
                       e.get("message").as_string();
            } else {
                want = check::read_file(base + ".project.json") + "\n" + check::read_file(base + ".report.json");
            }
            CHECK_MSG(text == want, id + " (" + rec.get("label").as_string() + "): not the Python package's answer");
            python++;
        }
        if (unknown || other_input)
            std::printf("synthetic directory: %d cases the fixture file does not have and %d whose input differs from the one it saw were "
                        "compared with the Python package's answers only\n",
                        unknown, other_input);
    } else {
        std::printf("KOMPARTMENT_ECO_FIXTURES not set: the synthetic directory's cases skipped (the fixture file keeps %zu of them)\n",
                    fixture.get("directory").size());
    }

    // --- the two inflaters on streams deflated here and damaged at random.
    int stress = 0;
#ifdef KOMPARTMENT_HAVE_ZLIB
    {
        Mix m{0x1f1a7e};
        for (int k = 0; k < 3000; k++) {
            std::string raw;
            const std::size_t n = m.below(k % 10 == 0 ? 70000 : 3000);
            const int shape = static_cast<int>(m.below(4));
            for (std::size_t i = 0; i < n; i++) {
                const std::uint64_t r = m.next();
                const std::uint64_t byte = shape == 0 ? r : shape == 1 ? static_cast<std::uint64_t>("abcab"[r % 5]) : shape == 2 ? i / 300 : (r % 7 == 0 ? r : 0);
                raw.push_back(static_cast<char>(byte & 0xff));
            }
            const int strategy = m.below(5) == 0 ? Z_FIXED : m.below(4) == 0 ? Z_HUFFMAN_ONLY : Z_DEFAULT_STRATEGY;
            std::string s = deflate_with(raw, static_cast<int>(m.below(10)), strategy);
            const int damage = static_cast<int>(m.below(4));
            if (damage == 1 && !s.empty()) s.resize(m.below(s.size()));
            if (damage >= 2 && !s.empty()) {
                const std::size_t flips = 1 + m.below(4);
                for (std::size_t j = 0; j < flips; j++) {
                    const std::size_t i = m.below(std::min<std::size_t>(s.size(), damage == 2 ? 40 : s.size()));
                    s[i] = damage == 2 ? static_cast<char>(s[i] ^ (1 << m.below(8))) : static_cast<char>(m.next() & 0xff);
                }
            }
            const std::size_t limits[][2] = {{std::size_t{1} << 20, 0}, {raw.size() + 1, raw.size()}, {raw.size() / 2 + 1, 0}, {1, 0}, {1500, 1499}};
            for (const auto& l : limits) {
                const eco::InflateResult a = eco::raw_inflate(s, l[0], l[1], true), b = eco::raw_inflate(s, l[0], l[1]);
                CHECK_MSG(a.out == b.out && a.eof == b.eof && a.damage.has_value() == b.damage.has_value() &&
                              same_but_apple(a.damage.value_or(""), b.damage.value_or("")),
                          "stream " + std::to_string(k) + " max " + std::to_string(l[0]) + ": zlib " + kept(a.out) + (a.eof ? " eof " : " ") +
                              (a.damage ? *a.damage : "") + ", built-in " + kept(b.out) + (b.eof ? " eof " : " ") + (b.damage ? *b.damage : ""));
                stress++;
            }
        }
    }
#endif

    if (const char* d = dumps()) {
        std::FILE* f = std::fopen((std::string(d) + "/ecoimport.cpp.txt").c_str(), "wb");
        if (f) {
            std::string all;
            for (std::size_t k = 0; k < table.size(); k++) all += (k ? "\n" : "") + table[k];
            std::fwrite(all.data(), 1, all.size(), f);
            std::fclose(f);
        }
    }
    std::printf("%d imports, %d XML documents, %d inflations of the fixture's streams, %d of the synthetic directory (%d against the Julia "
                "package, %d against the Python package), %d streams against zlib\n",
                imports, documents, inflations, directory, matched, python, stress);
    return check::summary("test_ecoimport");
}
