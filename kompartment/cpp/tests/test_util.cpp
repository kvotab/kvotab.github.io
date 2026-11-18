// JSON as the model files hold it, and numbers as JavaScript and Python write them.

#include <cmath>
#include <limits>

#include "check.hpp"
#include "util/json.hpp"
#include "util/jsnum.hpp"

using namespace kompartment;

int main() {
    // Numbers as JavaScript's String(x) writes them (values checked in Node).
    CHECK_EQ(js_number(100000.0), "100000");
    CHECK_EQ(js_number(0.000015), "0.000015");
    CHECK_EQ(js_number(1e-7), "1e-7");
    CHECK_EQ(js_number(1.5e21), "1.5e+21");
    CHECK_EQ(js_number(1e21), "1e+21");
    CHECK_EQ(js_number(123456789012345680000.0), "123456789012345680000");
    CHECK_EQ(js_number(-0.1), "-0.1");
    CHECK_EQ(js_number(0.1 + 0.2), "0.30000000000000004");
    CHECK_EQ(js_number(5e-324), "5e-324");
    CHECK_EQ(js_number(1.7976931348623157e308), "1.7976931348623157e+308");
    CHECK_EQ(js_number(-0.0), "0");
    CHECK_EQ(js_number(std::nan("")), "null");
    CHECK_EQ(js_number(123.456), "123.456");
    CHECK_EQ(js_number(0.000001), "0.000001");
    CHECK_EQ(js_number(1.2345e-7), "1.2345e-7");
    CHECK_EQ(js_text(std::numeric_limits<double>::infinity()), "Infinity");

    // Floats as Python's repr writes them.
    CHECK_EQ(py_repr(1.0), "1.0");
    CHECK_EQ(py_repr(1e-5), "1e-05");
    CHECK_EQ(py_repr(0.0001), "0.0001");
    CHECK_EQ(py_repr(1e16), "1e+16");
    CHECK_EQ(py_repr(1e15), "1000000000000000.0");
    CHECK_EQ(py_repr(1.5e16), "1.5e+16");
    CHECK_EQ(py_repr(-2.5), "-2.5");
    CHECK_EQ(py_repr(0.1 + 0.2), "0.30000000000000004");
    CHECK_EQ(py_repr(123456.789), "123456.789");
    CHECK_EQ(py_repr(-0.0), "-0.0");
    CHECK_EQ(py_repr(1e22), "1e+22");
    CHECK_EQ(py_repr(1.2345e-10), "1.2345e-10");

    // Number(v).
    CHECK_EQ(js_number_of(std::string_view("")), 0.0);
    CHECK_EQ(js_number_of(std::string_view("  12.5e1 ")), 125.0);
    CHECK_EQ(js_number_of(std::string_view(".5")), 0.5);
    CHECK_EQ(js_number_of(std::string_view("5.")), 5.0);
    CHECK_EQ(js_number_of(std::string_view("0x1F")), 31.0);
    CHECK(std::isnan(js_number_of(std::string_view("1_000"))));
    CHECK(std::isnan(js_number_of(std::string_view("abc"))));
    CHECK(std::isnan(js_number_of(std::string_view("1e"))));
    CHECK_EQ(js_number_of(Json()), 0.0);
    CHECK_EQ(js_number_of(Json(true)), 1.0);
    CHECK(std::isinf(js_number_of(std::string_view("-Infinity"))));

    // Reading: key order kept, integers apart from floats, escapes, sharing.
    Json v = parse_json("\xef\xbb\xbf {\"b\": 1, \"a\": [1.0, 2e3, -0, \"x\\u00e5\\n\\ud83d\\ude00\"], \"c\": {\"k\": null, \"t\": true}}");
    CHECK(v.is_object());
    CHECK_EQ(v.obj().keys()[0], "b");
    CHECK_EQ(v.obj().keys()[1], "a");
    CHECK(v.get("b").is_int());
    CHECK(v.get("a")[0].is_float());
    CHECK_EQ(v.get("a")[1].as_double(), 2000.0);
    CHECK(v.get("a")[2].is_int());
    CHECK_EQ(v.get("a")[3].as_string(), "x\xc3\xa5\n\xf0\x9f\x98\x80");
    CHECK(v.get("c").get("k").is_null());
    CHECK(v.get("missing").is_null());
    CHECK(v.get("c").get("t").as_bool());
    CHECK_EQ(json_text(v, 0), "{\"b\":1,\"a\":[1,2000,0,\"x\xc3\xa5\\n\xf0\x9f\x98\x80\"],\"c\":{\"k\":null,\"t\":true}}");
    CHECK_EQ(json_text(parse_json("{\"a\":[1,{\"b\":[]}],\"c\":{}}"), 2), "{\n  \"a\": [\n    1,\n    {\n      \"b\": []\n    }\n  ],\n  \"c\": {}\n}");
    CHECK_EQ(parse_json("1e400").as_double(), std::numeric_limits<double>::infinity());
    CHECK_EQ(parse_json("123456789012345678901234567890").as_double(), 1.2345678901234568e29);

    Json shared = v.get("a");
    shared.push(Json(7));
    CHECK_EQ(v.get("a").size(), std::size_t{5});          // a list is shared when its value is copied
    Json own = v.copy();
    own["a"].push(Json(8));
    CHECK_EQ(v.get("a").size(), std::size_t{5});          // and a copy is a tree of its own
    CHECK(v.get("a").same(shared));
    CHECK(!own.get("a").same(shared));

    // A dictionary keeps its order through sets and removals, however many keys it has.
    Json d = Json::object();
    for (int i = 0; i < 40; i++) d.set("k" + std::to_string(i), Json(i));
    d.erase("k3");
    d.set("k3", Json(-3));
    d.set("k5", Json(-5));
    CHECK_EQ(d.size(), std::size_t{40});
    CHECK_EQ(d.obj().keys().back(), "k3");
    CHECK_EQ(d.get("k5").as_int(), -5);
    CHECK_EQ(d.obj().keys()[4], "k5");
    CHECK(Json(1) == Json(1.0));
    CHECK(parse_json("{\"a\":1,\"b\":[2]}") == parse_json("{\"b\":[2.0],\"a\":1}"));

    bool threw = false;
    try { parse_json("{\"a\": }"); } catch (const JsonError& e) { threw = e.position == 7; }
    CHECK(threw);
    CHECK(js_truthy_switch(Json(), true));
    CHECK(!js_truthy_switch(Json("false"), true));
    CHECK(!js_truthy_switch(Json(), false));
    CHECK(js_truthy_switch(Json(1), false));
    return check::summary("test_util");
}
