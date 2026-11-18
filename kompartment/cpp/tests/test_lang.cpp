// The equation language against the Julia engine's reading of it
// (tools/lang_fixtures.jl writes tests/fixtures/lang.json): every equation's
// tree or the message it is refused with, the built-in functions and V8's
// own exp, log, pow to the bit, numbers as JavaScript and Python write them.

#include <cstdint>
#include <cstring>
#include <functional>
#include <map>

#include "check.hpp"
#include "lang/functions.hpp"
#include "lang/jsmath.hpp"
#include "lang/parse.hpp"
#include "util/json.hpp"
#include "util/jsnum.hpp"

using namespace kompartment;

static std::string bits(double x) {
    std::uint64_t u;
    std::memcpy(&u, &x, 8);
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(u));
    return buf;
}
static double unbits(const std::string& h) {
    std::uint64_t u = std::strtoull(h.c_str(), nullptr, 16);
    double x;
    std::memcpy(&x, &u, 8);
    return x;
}
// A NaN is a NaN whatever its bits.
static bool same(const std::string& expected, double got) {
    double want = unbits(expected);
    if (want != want) return got != got;
    return expected == bits(got);
}

static std::string sexp(const ENode& n) {
    switch (n.kind) {
        case ENode::Kind::Num: {
            const ENum& x = as_num(n);
            return x.unit ? "(num " + bits(x.value) + " [" + *x.unit + "])" : "(num " + bits(x.value) + ")";
        }
        case ENode::Kind::Ref: {
            const ERef& r = as_ref(n);
            std::string out = "(ref " + r.name;
            for (const auto& i : r.indices) out += " [" + (i ? *i : std::string()) + "]";
            return out + ")";
        }
        case ENode::Kind::Call: {
            const ECall& c = as_call(n);
            std::string out = "(call " + c.name;
            for (const auto& a : c.args) out += " " + sexp(*a);
            return out + ")";
        }
        case ENode::Kind::Unary: return "(neg " + sexp(*as_unary(n).operand) + ")";
        case ENode::Kind::Binary: return "(" + as_binary(n).op + " " + sexp(*as_binary(n).left) + " " + sexp(*as_binary(n).right) + ")";
        case ENode::Kind::Cond:
            return "(? " + sexp(*as_cond(n).test) + " " + sexp(*as_cond(n).then) + " " + sexp(*as_cond(n).otherwise) + ")";
    }
    return "";
}

int main() {
    Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/lang.json"));

    CallsPredicate calls = [](const std::string& name) { return name == "Lookup" || name == "foo"; };
    for (const Json& row : fx.get("parse").arr()) {
        const std::string& src = row.get("src").as_string();
        std::string shown = src.size() > 60 ? src.substr(0, 60) + "..." : src;
        try {
            ENodePtr tree = parse_equation(std::string_view(src), calls);
            if (row.has("tree")) CHECK_MSG(sexp(*tree) == row.get("tree").as_string(), "the tree of '" + shown + "': " + sexp(*tree).substr(0, 200));
            else CHECK_MSG(false, "'" + shown + "' is refused there: " + row.get("error").as_string());
        } catch (const EquationParseError& e) {
            if (row.has("error")) {
                CHECK_MSG(row.get("error").as_string() == e.what(), "the refusal of '" + shown + "': " + e.what());
                CHECK_MSG(row.get("position").as_int() == e.position, "where '" + shown + "' is refused: " + std::to_string(e.position));
            } else {
                CHECK_MSG(false, "'" + shown + "' is read there, refused here: " + e.what());
            }
        }
        std::vector<std::string> names = names_in(std::string_view(src));
        const JArray& want = row.get("names").arr();
        bool ok = names.size() == want.size();
        for (std::size_t i = 0; ok && i < names.size(); i++) ok = want[i].as_string() == names[i];
        CHECK_MSG(ok, "the names in '" + shown + "'");
    }

    std::map<std::string, std::function<double(double)>> one = {
        {"round", kf_round}, {"sqrt", kf_sqrt}, {"sign", kf_sign}, {"ulp", kf_ulp}, {"not", kf_not},
        {"factorial", kf_factorial}, {"erf", kf_erf}, {"erfc", kf_erfc}, {"fix", kf_fix},
        {"js_exp", js_exp}, {"js_log", js_log}, {"js_log10", js_log10}, {"js_log1p", js_log1p}, {"js_expm1", js_expm1}};
    std::map<std::string, std::function<double(double, double)>> two = {
        {"np_pow", np_pow}, {"jspow", kf_jspow}, {"jspow1", kf_jspow1}, {"mod", kf_mod}, {"rem", kf_rem},
        {"min", kf_min}, {"max", kf_max}, {"binomial", kf_binomial}, {"bq2mole", kf_bq2mole}, {"mole2bq", kf_mole2bq},
        {"js_pow", js_pow}};
    std::map<std::string, std::function<double(double, double, double)>> three = {
        {"rampDown", kf_ramp_down}, {"rampUp", kf_ramp_up},
        {"smoothDown", [](double a, double b, double c) { return kf_smooth_down(a, b, c, true); }},
        {"smoothDownEach", [](double a, double b, double c) { return kf_smooth_down(a, b, c, false); }},
        {"smoothUp", [](double a, double b, double c) { return kf_smooth_up(a, b, c, true); }}};
    for (const Json& row : fx.get("calls").arr()) {
        const std::string& name = row[0].as_string();
        const JArray& args = row[1].arr();
        double got;
        if (args.size() == 1) got = one.at(name)(unbits(args[0].as_string()));
        else if (args.size() == 2) got = two.at(name)(unbits(args[0].as_string()), unbits(args[1].as_string()));
        else got = three.at(name)(unbits(args[0].as_string()), unbits(args[1].as_string()), unbits(args[2].as_string()));
        std::string said = name + "(";
        for (const Json& a : args) said += check::bits(unbits(a.as_string())) + " ";
        CHECK_MSG(same(row[2].as_string(), got), said + ") is " + check::bits(unbits(row[2].as_string())) + ", here " + check::bits(got));
    }

    for (const Json& row : fx.get("many").arr()) {
        const std::string& name = row[0].as_string();
        std::vector<double> args;
        for (const Json& a : row[1].arr()) args.push_back(unbits(a.as_string()));
        if (name == "sort") {
            std::vector<double> got = js_sort_numbers(args.data(), args.size());
            const JArray& want = row[2].arr();
            bool ok = got.size() == want.size();
            for (std::size_t i = 0; ok && i < got.size(); i++) ok = same(want[i].as_string(), got[i]);
            CHECK_MSG(ok, "a sort of " + std::to_string(args.size()) + " numbers");
            continue;
        }
        std::string got;
        try {
            double v = name == "percentile" ? kf_percentile(args[0], args.data() + 1, args.size() - 1)
                       : name == "transport_point" ? kf_transport_point(args.data(), args.size())
                       : kf_transport_range(args.data(), args.size(), name == "transport_mean");
            const std::string& want = row[2].as_string();
            CHECK_MSG(want.rfind("error", 0) != 0 && same(want, v), name + " of " + std::to_string(args.size()) + " arguments: " + check::bits(v) + ", there " + want);
        } catch (const TransportRangeError& e) {
            CHECK_MSG(row[2].as_string() == std::string("error: ") + e.what(), name + " refuses with: " + e.what());
        }
    }

    for (const Json& row : fx.get("numbers").arr()) {
        double x = unbits(row[0].as_string());
        CHECK_MSG(js_number(x) == row[1].as_string(), "js_number of " + check::bits(x) + ": " + js_number(x));
        CHECK_MSG(js_text(x) == row[2].as_string(), "js_text of " + check::bits(x) + ": " + js_text(x));
        CHECK_MSG(py_repr(x) == row[3].as_string(), "py_repr of " + check::bits(x) + ": " + py_repr(x));
    }
    return check::summary("test_lang");
}
