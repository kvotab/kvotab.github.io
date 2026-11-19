// HDF5 files against the Julia package's, byte for byte (tools/hdf5_fixtures.jl writes
// tests/fixtures/hdf5.json): the writer on trees made up step by step -- every datatype and
// the values each is given as, empty and large datasets, many children, attribute orders with
// array-index keys, text that is not ASCII or not UTF-8, pooled strings past a global heap
// collection, int32 wrapping, NaN and the infinities, dimensions, the refusals -- lookup3 on
// its own, text as `TextEncoder` writes it and a string's characters as Julia cuts them; and
// the result files: trees of made-up descriptors (every realisation, a mean, one
// realisation), the runs of every bundled example and of made-up models, probabilistic runs
// and results made up by hand, scenarios side by side, and `save`. Each file's bytes are
// hashed and compared, or the refusal's words.
//
// Besides: the attributes' order and shared names, a probabilistic run's file the same on four
// threads as on one, and files a reader of HDF5 would open (the superblock and every object
// header's checksum read back).
//
// KOMPARTMENT_FIXTURE_DUMPS=DIR writes every file (`hdf5-<n>.cpp.h5`) and a table of the
// cases (`hdf5.cpp.txt`) there; KOMPARTMENT_HDF5_ONLY=text runs only the cases whose name
// holds it. Files `save` writes go in a folder of the system's temporary one, removed at the
// end; a time in seconds since the epoch is read in UTC, as the fixtures were.

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <functional>
#include <limits>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include "check.hpp"
#include "engine/builder.hpp"
#include "engine/probabilistic.hpp"
#include "engine/project.hpp"
#include "engine/runner.hpp"
#include "engine/scenarios.hpp"
#include "engine/system.hpp"
#include "io/hdf5.hpp"
#include "io/resultfile.hpp"
#include "solvers/types.hpp"
#include "util/errors.hpp"
#include "util/json.hpp"
#include "util/jsnum.hpp"
#include "util/parity.hpp"

using namespace kompartment;

namespace {

constexpr double NaN = std::numeric_limits<double>::quiet_NaN();
constexpr double Inf = std::numeric_limits<double>::infinity();

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

/// What a case gives: a file's bytes (kept as their hash), or a refusal in the package's words.
std::string said(const std::function<std::string()>& f) {
    try {
        return kept(f());
    } catch (const HDF5Error& e) {
        return std::string("error:HDF5Error:") + e.what();
    } catch (const ArgumentError& e) {
        return std::string("error:ArgumentError:") + e.what();
    } catch (const SolverError& e) {
        return "error:SolverError:" + e.message;
    } catch (const BuildError& e) {
        return std::string("error:BuildError:") + e.what();
    } catch (const ValidationError& e) {
        return std::string("error:ValidationError:") + e.what();
    } catch (const JuliaError& e) {
        if (e.kind == "ErrorException") return std::string("error:ErrorException:") + e.what();
        return "error:" + e.kind;
    }
}

const char* dumps_dir() {
    const char* d = std::getenv("KOMPARTMENT_FIXTURE_DUMPS");
    return (d && *d) ? d : nullptr;
}

std::string table;
int count = 0;

/// Compares a case's answer with the fixture's, the file dumped where asked.
void record(const std::string& what, const std::string& want, const std::string& got, const std::string& bytes) {
    count++;
    if (const char* d = dumps_dir()) {
        if (got.rfind("error:", 0) != 0) std::ofstream(std::string(d) + "/hdf5-" + std::to_string(count) + ".cpp.h5", std::ios::binary) << bytes;
    }
    table += (table.empty() ? "" : "\n") + std::to_string(count) + " " + what + " " + got;
    CHECK_MSG(got == want, what + "\n   here:  " + got.substr(0, 300) + "\n   there: " + want.substr(0, 300));
}

/// Makes a case's file, or its refusal (tidied where asked), and compares it.
void answer(const std::string& what, const std::string& want, const std::function<std::string()>& make,
            const std::function<std::string(std::string)>& tidy = nullptr) {
    std::string bytes;
    std::string got = said([&] {
        bytes = make();
        return bytes;
    });
    if (tidy && got.rfind("error:", 0) == 0) got = tidy(got);
    record(what, want, got, bytes);
}

// --- values as the fixture writes them ---------------------------------------------------------------

double special(const std::string& s) {
    if (s == "NaN") return NaN;
    if (s == "Infinity") return Inf;
    if (s == "-Infinity") return -Inf;
    return -0.0;
}

std::uint64_t splitmix(std::uint64_t& s) {
    s += 0x9e3779b97f4a7c15ULL;
    std::uint64_t z = s;
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
    return z ^ (z >> 31);
}

/// The numbers a `$gen` makes (as the tool's `generated`).
std::vector<double> generated(const Json& g) {
    const long long n = g.get("n").as_int();
    std::uint64_t s = static_cast<std::uint64_t>(g.get("seed").as_int());
    const bool specials = g.get("specials") == Json(true);
    std::vector<double> out(static_cast<std::size_t>(n));
    for (long long k = 0; k < n; k++) {
        const double m = static_cast<double>(splitmix(s) >> 11) * 0x1p-53;
        const int e = static_cast<int>(splitmix(s) % 81) - 40;
        double x = std::ldexp(2.0 * m - 1.0, e);
        if (specials) {
            if (k % 101 == 7) x = NaN;
            if (k % 103 == 11) x = Inf;
            if (k % 107 == 13) x = -Inf;
            if (k % 109 == 17) x = -0.0;
            if (k % 113 == 19) x = 5e-324;
        }
        out[static_cast<std::size_t>(k)] = x;
    }
    return out;
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

const Json* escape(const Json& v, const char* key) {
    if (!v.is_object() || v.obj().size() != 1) return nullptr;
    return v.obj().find(key);
}

Json dec(const Json& v);

double num(const Json& v) { return v.is_object() ? dec(v).as_double() : v.as_double(); }

/// A value with its escapes read (the tool's `dec`); numbers made by a generator, or given as
/// doubles or singles, as a list of doubles.
Json dec(const Json& v) {
    if (v.is_object()) {
        if (v.obj().size() == 1 && !v.obj().begin()->first.empty() && v.obj().begin()->first[0] == '$') {
            const std::string& k = v.obj().begin()->first;
            const Json& x = v.obj().begin()->second;
            if (k == "$float") return Json(special(x.as_string()));
            if (k == "$f64" || k == "$f32") {
                Json out = Json::array();
                for (const Json& y : x.arr()) out.push(Json(k == "$f32" ? static_cast<double>(static_cast<float>(num(y))) : num(y)));
                return out;
            }
            if (k == "$cp") {
                std::string s;
                for (const Json& c : x.arr()) put_utf8(s, static_cast<std::uint32_t>(c.as_int()));
                return Json(s);
            }
            if (k == "$bytes") return Json(unhex(x.as_string()));
            if (k == "$gen") {
                const std::vector<double> g = generated(x);
                Json out = Json::array();
                for (double d : g) out.push(Json(x.get("kind") == "f32" ? static_cast<double>(static_cast<float>(d)) : d));
                return out;
            }
            if (k == "$strings") {
                const long long n = x.get("n").as_int();
                const long long m = x.has("mod") ? x.get("mod").as_int() : 0;
                Json out = Json::array();
                for (long long j = 0; j < n; j++) out.push(Json(x.get("prefix").as_string() + std::to_string(m > 0 ? j % m : j)));
                return out;
            }
        }
        Json out = Json::object();
        for (const auto& [k, x] : v.obj()) out.set(k, dec(x));
        return out;
    }
    if (v.is_array()) {
        Json out = Json::array();
        for (const Json& x : v.arr()) out.push(dec(x));
        return out;
    }
    return v;
}

std::vector<double> doubles(const Json& v) {
    if (const Json* g = escape(v, "$gen")) return generated(*g);
    std::vector<double> out;
    const Json values = dec(v);
    for (const Json& x : values.arr()) out.push_back(x.as_double());
    return out;
}

std::vector<float> singles(const Json& v) {
    std::vector<float> out;
    for (double x : doubles(v)) out.push_back(static_cast<float>(x));
    return out;
}

/// A dataset's values as the tool gives them: doubles, singles, or JSON values.
H5Dataset::Data data_of(const Json& v) {
    if (escape(v, "$f64")) return doubles(v);
    if (escape(v, "$f32")) return singles(v);
    if (const Json* g = escape(v, "$gen")) {
        if (g->get("kind") == "f32") return singles(v);
        if (g->get("kind") == "any") return dec(v);
        return doubles(v);
    }
    return dec(v);
}

H5Attrs attrs_of(const Json& v) {
    H5Attrs a;
    if (v.is_object())
        for (const auto& [k, x] : v.obj()) a.set(k, dec(x));
    return a;
}

H5Type type_of(const std::string& name) {
    if (name == "F32") return H5Type::F32;
    if (name == "I32") return H5Type::I32;
    if (name == "STR") return H5Type::STR;
    return H5Type::F64;
}

std::string text_of(const Json& v) { return dec(v).as_string(); }

Stamp stamp_of(const Json& s) {
    if (s.has("epoch")) return Stamp::epoch(s.get("epoch").as_double());
    const Json& l = s.get("local");
    return Stamp::local(static_cast<int>(l[0].as_int()), static_cast<int>(l[1].as_int()), static_cast<int>(l[2].as_int()),
                        static_cast<int>(l[3].as_int()), static_cast<int>(l[4].as_int()), static_cast<int>(l[5].as_int()));
}

// --- the cases -------------------------------------------------------------------------------------------

std::string build_tree(const Json& c) {
    std::map<long long, H5Ptr> nodes;
    for (const Json& op : c.get("ops").arr()) {
        const std::string& kind = op.get("op").as_string();
        if (kind == "group") {
            nodes[op.get("id").as_int()] = h5_group(attrs_of(op.get("attrs")));
        } else if (kind == "dataset") {
            std::optional<std::vector<Json>> dims;
            if (!op.get("dims").is_null()) dims = dec(op.get("dims")).arr();
            const H5Type dt = type_of(op.get("dt").as_string());
            H5Attrs attrs = attrs_of(op.get("attrs"));
            H5Dataset::Data data = data_of(op.get("data"));
            nodes[op.get("id").as_int()] = std::visit([&](auto&& d) -> H5Ptr { return h5_dataset(std::move(d), dt, std::move(attrs), dims); }, std::move(data));
        } else if (kind == "put") {
            std::vector<std::string> path;
            for (const Json& p : op.get("path").arr()) path.push_back(text_of(p));
            h5_put(static_cast<H5Group&>(*nodes.at(op.get("root").as_int())), path, nodes.at(op.get("node").as_int()));
        } else if (kind == "at") {
            H5Ptr node = nodes.at(op.get("root").as_int());
            for (const Json& p : op.get("path").arr()) {
                const std::string name = text_of(p);
                H5Ptr next;
                for (const auto& [k, child] : static_cast<H5Group&>(*node).children())
                    if (k == name) next = child;
                node = next;
            }
            nodes[op.get("id").as_int()] = node;
        } else if (kind == "set_attr") {
            nodes.at(op.get("node").as_int())->attrs.set(text_of(op.get("key")), dec(op.get("value")));
        } else if (kind == "delete_attr") {
            nodes.at(op.get("node").as_int())->attrs.erase(text_of(op.get("key")));
        }
    }
    return write_hdf5(*nodes.at(c.get("root").as_int()));
}

std::string pattern(long long n, long long seed) {
    std::string out;
    for (long long k = 0; k < n; k++) out.push_back(static_cast<char>((k * 131 + seed * 7 + (k >> 3) * 17) % 256));
    return out;
}

std::string build_result_tree(const Json& c) {
    const std::vector<double> t = doubles(c.get("t"));
    std::vector<Json> outputs = dec(c.get("outputs")).arr();
    std::vector<std::vector<double>> cols;
    for (const Json& col : c.get("columns").arr()) cols.push_back(doubles(col));
    std::vector<std::size_t> which;
    for (const Json& w : c.get("which").arr()) which.push_back(static_cast<std::size_t>(w.as_int() - 1));
    std::optional<TreeRealisations> realisations;
    std::map<long long, std::vector<float>> mats;
    if (!c.get("realisations").is_null()) {
        const Json& r = c.get("realisations");
        for (const Json& p : r.get("matrices").arr()) mats[p[0].as_int()] = singles(p[1]);
        realisations = TreeRealisations{};
        if (r.has("iterations")) realisations->iterations = dec(r.get("iterations"));
        realisations->matrix_for = [&](std::size_t i) -> std::optional<std::vector<float>> {
            auto it = mats.find(static_cast<long long>(i) + 1);
            if (it == mats.end()) return std::nullopt;
            return it->second;
        };
    }
    std::optional<TreeSample> sample;
    if (!c.get("sample").is_null()) {
        const Json s = dec(c.get("sample"));
        sample = TreeSample{};
        if (s.has("iterations")) sample->iterations = s.get("iterations");
        if (s.has("of")) sample->of = s.get("of");
    }
    auto tree = result_tree(t, outputs, [&](std::size_t i) { return cols.at(i); }, which, dec(c.get("project")), dec(c.get("index_lists")),
                            stamp_of(c.get("now")), realisations ? &*realisations : nullptr, sample ? &*sample : nullptr);
    return write_hdf5(*tree);
}

std::map<std::string, Json> examples;
Json fixture;

const Json& model_of(const Json& c) {
    if (c.has("example")) {
        const std::string& ex = c.get("example").as_string();
        if (!examples.count(ex)) examples[ex] = parse_json(check::read_file(std::string(KOMPARTMENT_REPO) + "/examples/" + ex + ".json"));
        return examples[ex];
    }
    return fixture.get("models").get(c.get("model").as_string());
}

Results run_res(const Json& model) {
    auto project = std::make_shared<const Project>(model);
    auto sys = std::make_shared<System>(project);
    return run_project(project, sys);
}

/// The series asked for: labels, positions from 1, and `{"$output": k}` for the k-th descriptor itself.
std::optional<std::vector<Json>> which_of(const Json& w, const std::vector<Json>& outs) {
    if (w.is_null()) return std::nullopt;
    std::vector<Json> out;
    for (const Json& x : w.arr()) {
        if (const Json* k = escape(x, "$output")) out.push_back(outs.at(static_cast<std::size_t>(k->as_int() - 1)));
        else out.push_back(dec(x));
    }
    return out;
}

std::string build_results(const Json& c) {
    Results res = run_res(model_of(c));
    const std::vector<Json>& outs = res.outputs();
    ResultsTreeOptions o;
    o.which = which_of(c.get("which"), outs);
    o.now = stamp_of(c.has("now") ? c.get("now") : fixture.get("now"));
    if (c.has("project")) o.model = dec(c.get("project"));
    if (c.has("index_lists")) o.index_lists = dec(c.get("index_lists"));
    if (c.get("double") == Json(true))
        o.column = [&](std::size_t i) {
            std::vector<double> v = res.series(outs[i]);
            for (double& x : v) x = 2 * x;
            return v;
        };
    return write_results_hdf5(res, o);
}

ProbabilisticResults run_prob(const Json& model, const Json& o, int threads) {
    ProbabilisticOptions p;
    if (o.has("iterations")) p.iterations = o.get("iterations").as_double();
    p.seed = o.has("seed") ? o.get("seed") : Json(1);
    if (o.has("latin")) p.latin = o.get("latin").as_bool();
    if (o.has("keep")) {
        std::vector<std::string> keep;
        for (const Json& k : o.get("keep").arr()) keep.push_back(k.as_string());
        p.keep = keep;
    }
    if (o.has("range")) p.range = std::make_pair(o.get("range")[0].as_double(), o.get("range")[1].as_double());
    if (o.has("tornado")) p.tornado = o.get("tornado");
    if (o.has("gsa")) p.gsa = o.get("gsa");
    if (o.has("most_bytes")) p.most_bytes = o.get("most_bytes").as_int();
    if (o.has("asked_bytes")) p.asked_bytes = o.get("asked_bytes").as_int();
    if (o.has("large")) p.large = o.get("large").as_bool();
    p.threads = threads;
    return run_probabilistic(std::make_shared<const Project>(model), p);
}

/// Every series a file of a probabilistic run can hold, as `$output` counts them: the kept
/// ones, then the inputs of a label not kept.
std::vector<Json> described(const ProbabilisticResults& prob) {
    std::vector<Json> out = prob.outputs;
    for (const Json& inp : prob.inputs) {
        bool taken = false;
        for (const Json& o : prob.outputs) taken = taken || o.get("label") == inp.get("output").get("label");
        if (!taken) out.push_back(inp.get("output"));
    }
    return out;
}

std::string prob_tree(const ProbabilisticResults& prob, const Json& t) {
    ProbabilisticTreeOptions o;
    o.want = dec(t.get("want"));
    o.which = which_of(t.get("which"), described(prob));
    if (t.has("project_model")) o.project = std::make_shared<const Project>(fixture.get("models").get(t.get("project_model").as_string()));
    else if (t.has("project")) o.model = dec(t.get("project"));
    if (t.has("index_lists")) o.index_lists = dec(t.get("index_lists"));
    o.now = stamp_of(t.has("now") ? t.get("now") : fixture.get("now"));
    if (t.has("inputs")) o.inputs = t.get("inputs").as_bool();
    return write_probabilistic_hdf5(prob, o);
}

/// A probabilistic result made up by hand, as the tool makes one.
ProbabilisticResults made_prob(const Json& spec) {
    ProbabilisticResults p;
    p.t = doubles(spec.get("t"));
    p.outputs = spec.get("outputs").arr();
    p.precision = spec.get("precision").as_string();
    for (const Json& r : spec.get("ran").arr()) p.ran.push_back(static_cast<std::uint8_t>(r.as_int()));
    const long long n = static_cast<long long>(p.ran.size());
    for (const Json& v : spec.get("values").arr()) {
        if (p.single()) p.values32.push_back(singles(v));
        else p.values.push_back(doubles(v));
    }
    const std::vector<double> flat = doubles(spec.get("samples"));
    const std::size_t rows = flat.empty() ? 0 : flat.size() / static_cast<std::size_t>(n);
    p.samples = ValueTable(rows, n);
    p.samples.data = flat;
    p.inputs = spec.get("inputs").arr();
    p.iterations = n;
    p.first = 1;
    p.last = n;
    p.stats = Json::object();
    p.project = std::make_shared<const Project>(fixture.get("models").get(spec.get("model").as_string()));
    return p;
}

std::string build_scenarios(const Json& c) {
    std::optional<std::vector<std::string>> names;
    if (c.has("names")) {
        names = std::vector<std::string>{};
        for (const Json& n : c.get("names").arr()) names->push_back(n.as_string());
    }
    const int threads = c.has("threads") ? static_cast<int>(c.get("threads").as_int()) : 1;
    // Each whole, whatever auto has learnt of the runs before it.
    auto runs = run_scenarios(model_of(c), names, threads, Json::object({{"split", Json("off")}}));
    ScenariosTreeOptions o;
    o.which = which_of(c.get("which"), runs.front().second.outputs());
    if (c.has("active")) o.active = c.get("active").as_string();
    if (c.has("project")) o.model = dec(c.get("project"));
    if (c.has("index_lists")) o.index_lists = dec(c.get("index_lists"));
    o.now = stamp_of(fixture.get("now"));
    return write_scenarios_hdf5(runs, o);
}

/// A tree's request as the tool names it: without its answer.
std::string named(const Json& t) {
    Json bare = t.shallow();
    bare.erase("out");
    return json_text(bare, 0);
}

std::string lower(std::string s) {
    for (char& c : s)
        if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
    return s;
}

bool ends_with(const std::string& s, const std::string& e) { return s.size() >= e.size() && s.compare(s.size() - e.size(), e.size(), e) == 0; }

std::string build_save(const Json& c, const std::string& path) {
    if (c.has("probabilistic")) {
        ProbabilisticResults prob = run_prob(model_of(c), c.get("probabilistic"), 1);
        ProbabilisticSaveOptions o;
        o.want = c.get("want");
        if (c.has("time_origin")) o.time_origin = c.get("time_origin").as_double();
        o.now = stamp_of(fixture.get("now"));
        save_probabilistic(prob, path, o);
    } else {
        Results res = run_res(model_of(c));
        SaveOptions o;
        if (c.has("blocks")) {
            std::vector<std::string> blocks;
            for (const Json& b : c.get("blocks").arr()) blocks.push_back(b.as_string());
            o.blocks = blocks;
        }
        if (c.has("which")) o.which = which_of(c.get("which"), res.outputs());
        if (c.has("time_origin")) o.time_origin = c.get("time_origin").as_double();
        if (c.has("project")) o.model = dec(c.get("project"));
        const std::string low = lower(c.get("path").as_string());
        if (!ends_with(low, ".csv") && !ends_with(low, ".zip")) o.now = stamp_of(fixture.get("now"));
        save_results(res, path, o);
    }
    return check::read_file(path);
}

/// Reads a file back as libhdf5 would begin to: the superblock's checksum, and every object
/// header the root group reaches, each with its checksum, its messages walked to the end.
bool reads_back(const std::string& f, std::string& why) {
    auto u = [&](std::size_t at, int n) {
        std::uint64_t v = 0;
        for (int i = n - 1; i >= 0; i--) v = (v << 8) | static_cast<unsigned char>(f[at + static_cast<std::size_t>(i)]);
        return v;
    };
    if (f.size() < 48 || f.compare(0, 8, "\x89HDF\r\n\x1a\n") != 0) return why = "no signature", false;
    if (lookup3(std::string_view(f).substr(0, 44)) != u(44, 4)) return why = "the superblock's checksum", false;
    // The signature, versions and sizes (12 bytes), the base address, the extension's, the end of
    // the file, the root group's header.
    if (u(28, 8) != f.size()) return why = "the end of the file", false;
    std::vector<std::uint64_t> todo = {u(36, 8)};
    std::size_t headers = 0;
    while (!todo.empty()) {
        const std::uint64_t at = todo.back();
        todo.pop_back();
        if (at + 14 > f.size() || f.compare(at, 4, "OHDR") != 0) return why = "no header at " + std::to_string(at), false;
        const std::uint64_t size = u(at + 6, 4);
        const std::uint64_t end = at + 10 + size;
        if (end + 4 > f.size() || lookup3(std::string_view(f).substr(at, 10 + size)) != u(end, 4)) return why = "a header's checksum at " + std::to_string(at), false;
        std::uint64_t p = at + 10;
        while (p < end) {
            const unsigned kind = static_cast<unsigned char>(f[p]);
            const std::uint64_t len = u(p + 1, 2);
            if (kind == 0x06) {   // a link: its name, then the address of what it links to
                const bool longer = (static_cast<unsigned char>(f[p + 5]) & 1) != 0;
                const std::uint64_t nb = longer ? u(p + 6, 2) : u(p + 6, 1);
                todo.push_back(u(p + 6 + (longer ? 2 : 1) + nb, 8));
            }
            p += 4 + len;
        }
        if (p != end) return why = "messages past a header's end at " + std::to_string(at), false;
        headers++;
    }
    return headers > 0;
}

}  // namespace

int main() {
#if !defined(_WIN32)
    setenv("TZ", "UTC", 1);
    tzset();
#endif
    fixture = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/hdf5.json"));
    const char* only_env = std::getenv("KOMPARTMENT_HDF5_ONLY");
    const std::string only = only_env ? only_env : "";
    auto wanted = [&](const Json& c) { return only.empty() || c.get("name").as_string().find(only) != std::string::npos; };
    set_parity(true);

    // --- lookup3 and text as it is written.
    int lookups = 0, strings = 0;
    for (const Json& c : fixture.get("lookup3").arr()) {
        const std::string data = pattern(c.get("n").as_int(), c.get("seed").as_int());
        const std::uint32_t got = c.has("start") ? lookup3(data, static_cast<std::size_t>(c.get("start").as_int()), static_cast<std::size_t>(c.get("len").as_int()))
                                                 : lookup3(data);
        CHECK_MSG(got == static_cast<std::uint32_t>(c.get("out").as_int()), "lookup3 of " + std::to_string(c.get("n").as_int()) + " bytes");
        lookups++;
    }
    CHECK(lookup3(std::string()) == 0xdeadbeefu);
    CHECK(lookup3(std::string("Four score and seven years ago")) == 0x17770551u);
    CHECK(lookup3(std::string("Four score and seven years ago, and then some"), 0, 30) == 0x17770551u);
    for (const Json& c : fixture.get("utf8").arr()) {
        const std::string in = unhex(c.get("in").as_string());
        std::string out;
        try {
            out = hex(h5_utf8(in));
        } catch (const JuliaError& e) {
            out = std::string("error:") + e.what();
        }
        std::string chars;
        const std::vector<std::string> cs = julia_chars(in);
        for (std::size_t k = 0; k < cs.size(); k++) chars += (k ? "," : "") + hex(cs[k]);
        CHECK_MSG(out == c.get("out").as_string(), "text " + c.get("in").as_string() + ": " + out + " there " + c.get("out").as_string());
        CHECK_MSG(chars == c.get("chars").as_string(), "characters of " + c.get("in").as_string());
        CHECK_MSG(static_cast<long long>(cs.size()) == c.get("count").as_int(), "how many characters " + c.get("in").as_string());
        strings++;
    }

    // --- trees made up step by step.
    for (const Json& c : fixture.get("trees").arr())
        if (wanted(c)) answer("tree " + c.get("name").as_string(), c.get("out").as_string(), [&] { return build_tree(c); });
    for (const Json& c : fixture.get("result_trees").arr())
        if (wanted(c)) answer("result tree " + c.get("name").as_string(), c.get("out").as_string(), [&] { return build_result_tree(c); });
    for (const Json& c : fixture.get("results").arr())
        if (wanted(c)) answer("results " + c.get("name").as_string(), c.get("out").as_string(), [&] { return build_results(c); });

    // --- probabilistic runs: each file again from the run on four threads, the same bytes.
    int again = 0;
    for (const Json& c : fixture.get("probabilistic").arr()) {
        if (!wanted(c)) continue;
        std::optional<ProbabilisticResults> prob, prob4;
        std::string refused;
        try {
            prob = run_prob(model_of(c), c.get("run"), 1);
            prob4 = run_prob(model_of(c), c.get("run"), 4);
        } catch (...) {
            refused = said([] () -> std::string { throw; });
        }
        for (const Json& t : c.get("trees").arr()) {
            const std::string what = "probabilistic " + c.get("name").as_string() + " " + named(t);
            if (!refused.empty()) {
                record(what, t.get("out").as_string(), refused, std::string());
                continue;
            }
            answer(what, t.get("out").as_string(), [&] { return prob_tree(*prob, t); });
            const std::string one = said([&] { return prob_tree(*prob, t); });
            const std::string four = said([&] { return prob_tree(*prob4, t); });
            CHECK_MSG(one == four, what + ": on four threads the file differs");
            again++;
        }
    }
    for (const Json& c : fixture.get("made").arr()) {
        if (!wanted(c)) continue;
        const ProbabilisticResults prob = made_prob(c.get("prob"));
        for (const Json& t : c.get("trees").arr())
            answer("made " + c.get("name").as_string() + " " + named(t), t.get("out").as_string(), [&] { return prob_tree(prob, t); });
    }
    for (const Json& c : fixture.get("scenarios").arr())
        if (wanted(c)) answer("scenarios " + c.get("name").as_string(), c.get("out").as_string(), [&] { return build_scenarios(c); });

    // --- saved.
    namespace fs = std::filesystem;
    const fs::path dir = fs::temp_directory_path() / ("kompartment-test-hdf5-" + std::to_string(static_cast<long long>(std::time(nullptr))) + "-" +
                                                      std::to_string(reinterpret_cast<std::uintptr_t>(&count) & 0xffff));
    fs::create_directories(dir);
    int k = 0;
    for (const Json& c : fixture.get("saves").arr()) {
        k++;
        if (!wanted(c)) continue;
        const std::string prefix = (dir / (std::to_string(k) + "-")).string();
        const std::string path = prefix + c.get("path").as_string();
        answer("save " + c.get("name").as_string(), c.get("out").as_string(), [&] { return build_save(c, path); },
               [&](std::string got) {
                   // The folder the files went to is not part of a refusal's words.
                   for (std::size_t at; (at = got.find(prefix)) != std::string::npos;) got.erase(at, prefix.size());
                   return got;
               });
    }
    fs::remove_all(dir);
    if (const char* d = dumps_dir()) std::ofstream(std::string(d) + "/hdf5.cpp.txt", std::ios::binary) << table;

    // --- what a reader of HDF5 checks first, on files of every kind.
    if (only.empty()) {
        std::vector<std::pair<std::string, std::string>> files;
        for (const Json& c : fixture.get("trees").arr()) {
            try {
                files.emplace_back(c.get("name").as_string(), build_tree(c));
            } catch (const std::exception&) {
            }
        }
        files.emplace_back("biosphere", build_results(Json::object({{"example", Json("biosphere")}})));
        for (const auto& [name, bytes] : files) {
            std::string why;
            CHECK_MSG(reads_back(bytes, why), name + " does not read back: " + why);
        }
    }

    // --- attributes: their order, and names shared between them.
    {
        H5Attrs a{{"b", Json(1)}, {"a", Json(2)}};
        a.set("c", Json(3));
        a.set("b", Json(10));   // keeps its place
        CHECK(a.size() == 3 && a.name(0) == "b" && a.name(1) == "a" && a.name(2) == "c" && a.find("b")->as_int() == 10);
        CHECK(a.erase("a") && !a.erase("zz") && a.size() == 2 && a.name(1) == "c");
        auto shared = std::make_shared<const std::vector<std::string>>(std::vector<std::string>{"x", "y"});
        H5Attrs p(shared, {Json(1), Json(2)}), q(shared, {Json(3), Json(4)});
        p.set("x", Json(5));    // a value: the names stay shared
        p.set("z", Json(6));    // a name: copied first
        CHECK(shared->size() == 2 && p.size() == 3 && q.size() == 2 && q.name(1) == "y" && p.find("x")->as_int() == 5);
        H5Attrs copy = p;
        copy.set("w", Json(7));
        CHECK(p.size() == 3 && copy.size() == 4);
        // What the file says follows JavaScript's key order, whatever order the keys were set in.
        auto t1 = h5_group(H5Attrs{{"u", Json("Bq")}, {"17", Json(1.5)}, {"0", Json(true)}});
        auto t2 = h5_group(H5Attrs{{"0", Json(true)}, {"u", Json("Bq")}, {"17", Json(1.5)}});
        auto t3 = h5_group(H5Attrs{{"u", Json("Bq")}, {"0", Json(true)}, {"17", Json(1.5)}});
        CHECK(write_hdf5(*t1) == write_hdf5(*t2) && write_hdf5(*t1) == write_hdf5(*t3));
        auto t4 = h5_group(H5Attrs{{"v", Json("Bq")}, {"0", Json(true)}, {"u", Json(1.5)}});
        auto t5 = h5_group(H5Attrs{{"u", Json(1.5)}, {"0", Json(true)}, {"v", Json("Bq")}});
        CHECK(write_hdf5(*t4) != write_hdf5(*t5));
        auto g = h5_group();
        auto d = h5_dataset(std::vector<double>{1.0});
        CHECK(h5_put(*g, {"a", "", "b"}, d) == d);
        CHECK(static_cast<H5Group*>(g->child("a"))->child("b") == d.get());
    }

    set_parity(false);
    std::printf("%d files and refusals, %d made again on four threads, %d lookup3 checks, %d strings\n", count, again, lookups, strings);
    return check::summary("test_hdf5");
}
