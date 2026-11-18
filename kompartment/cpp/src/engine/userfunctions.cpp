#include "engine/userfunctions.hpp"

#include <algorithm>

#include "lang/parse.hpp"
#include "model/names.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

ENodePtr scoped(const ENodePtr& ast, const std::unordered_set<std::string>& params, const std::string& system) {
    switch (ast->kind) {
        case ENode::Kind::Ref: {
            const ERef& r = as_ref(*ast);
            if (params.count(r.name)) return ast;
            auto out = std::make_shared<ERef>(r.name, r.indices, system);
            out->by_list = r.by_list;
            out->named = r.named;
            return out;
        }
        case ENode::Kind::Unary: return std::make_shared<EUnary>(as_unary(*ast).op, scoped(as_unary(*ast).operand, params, system));
        case ENode::Kind::Binary: {
            const EBinary& b = as_binary(*ast);
            return std::make_shared<EBinary>(b.op, scoped(b.left, params, system), scoped(b.right, params, system));
        }
        case ENode::Kind::Cond: {
            const ECond& c = as_cond(*ast);
            return std::make_shared<ECond>(scoped(c.test, params, system), scoped(c.then, params, system), scoped(c.otherwise, params, system));
        }
        case ENode::Kind::Call: {
            const ECall& c = as_call(*ast);
            std::vector<ENodePtr> args;
            for (const auto& a : c.args) args.push_back(scoped(a, params, system));
            return std::make_shared<ECall>(c.name, std::move(args), c.scope);
        }
        default: return ast;
    }
}

ENodePtr substitute(const ENodePtr& ast, const std::unordered_map<std::string, ENodePtr>& bound, const std::string& fn_name) {
    switch (ast->kind) {
        case ENode::Kind::Ref: {
            const ERef& r = as_ref(*ast);
            auto arg = bound.find(r.name);
            if (arg == bound.end()) return ast;
            if (!r.indices.empty() || (r.by_list && !r.named.empty()))
                throw FunctionError("'" + r.name + "[\xe2\x80\xa6]' asks for an index of a parameter of '" + fn_name +
                                    "'. An argument is a single value, already worked out where the function is called: put the index there instead.",
                                    fn_name);
            return arg->second;
        }
        case ENode::Kind::Unary: return std::make_shared<EUnary>(as_unary(*ast).op, substitute(as_unary(*ast).operand, bound, fn_name));
        case ENode::Kind::Binary: {
            const EBinary& b = as_binary(*ast);
            return std::make_shared<EBinary>(b.op, substitute(b.left, bound, fn_name), substitute(b.right, bound, fn_name));
        }
        case ENode::Kind::Cond: {
            const ECond& c = as_cond(*ast);
            return std::make_shared<ECond>(substitute(c.test, bound, fn_name), substitute(c.then, bound, fn_name), substitute(c.otherwise, bound, fn_name));
        }
        case ENode::Kind::Call: {
            const ECall& c = as_call(*ast);
            std::vector<ENodePtr> args;
            for (const auto& a : c.args) args.push_back(substitute(a, bound, fn_name));
            return std::make_shared<ECall>(c.name, std::move(args), c.scope);
        }
        default: return ast;
    }
}

}  // namespace

UserFunctions::UserFunctions(const JArray& functions, const std::function<bool(const std::string&, const std::string&)>& callable) {
    for (const Json& f : functions)
        if (js_truthy(f.get("name"))) declared_.insert(qualified_name(f));
    for (const Json& f : functions) {
        if (!js_truthy(f.get("name"))) continue;
        std::string name = qualified_name(f);
        std::vector<std::string> parameters;
        if (f.get("parameters").is_array())
            for (const Json& p : f.get("parameters").arr()) parameters.push_back(js_str(p));
        const Json& eq = f.get("equation");
        std::string text(js_trim(eq.is_null() ? std::string() : js_str(eq)));
        if (text.empty()) {
            std::string what = parameters.empty() ? "numbers and the built-in functions" : "its parameters (" + join(parameters, ", ") + ")";
            throw FunctionError("'" + name + "' has no body yet. Write what it works out to in terms of " + what +
                                ", or delete it and the equations that call it.", name);
        }
        std::string system = js_truthy(f.get("system")) ? js_str(f.get("system")) : "";
        ENodePtr ast;
        try {
            ast = parse_equation(std::string_view(text), [&](const std::string& n) {
                return resolve(n, system).has_value() || (callable && callable(n, system));
            });
        } catch (const EquationParseError& e) {
            throw FunctionError(std::string(e.what()) + " in the body of '" + name + "' (at character " + std::to_string(e.position + 1) + ")", name);
        }
        std::unordered_set<std::string> params(parameters.begin(), parameters.end());
        defs_[name] = Def{name, parameters, f, scoped(ast, params, system)};
    }
}

std::optional<std::string> UserFunctions::resolve(const std::string& written, const std::string& system) const {
    auto q = resolve_reference(written, system, [&](const std::string& n) { return declared_.count(n) != 0; });
    return (q && declared_.count(*q)) ? q : std::nullopt;
}

ENodePtr UserFunctions::inline_functions(const ENodePtr& ast, const std::optional<std::string>& owner, const std::string& system) const {
    return expand(ast, owner, system, {}, 0);
}

ENodePtr UserFunctions::expand(const ENodePtr& ast, const std::optional<std::string>& owner, const std::string& system,
                               const std::vector<std::string>& stack, int depth) const {
    if (depth > MAX_FUNCTION_DEPTH) {
        std::string who = stack.empty() ? owner.value_or("nothing") : stack.back();
        throw FunctionError("'" + who + "' nests function calls more than " + std::to_string(MAX_FUNCTION_DEPTH) + " deep.", owner);
    }
    auto go = [&](const ENodePtr& node) { return expand(node, owner, system, stack, depth); };
    switch (ast->kind) {
        case ENode::Kind::Ref:
        case ENode::Kind::Num: return ast;
        case ENode::Kind::Unary: return std::make_shared<EUnary>(as_unary(*ast).op, go(as_unary(*ast).operand));
        case ENode::Kind::Binary: {
            const EBinary& b = as_binary(*ast);
            ENodePtr left = go(b.left);
            return std::make_shared<EBinary>(b.op, left, go(b.right));
        }
        case ENode::Kind::Cond: {
            const ECond& c = as_cond(*ast);
            ENodePtr test = go(c.test);
            ENodePtr then = go(c.then);
            return std::make_shared<ECond>(test, then, go(c.otherwise));
        }
        case ENode::Kind::Call: {
            const ECall& c = as_call(*ast);
            std::vector<ENodePtr> args;
            for (const auto& a : c.args) args.push_back(go(a));
            const std::string& scope = c.scope ? *c.scope : system;
            std::optional<std::string> q = resolve(c.name, scope);
            auto fn = q ? defs_.find(*q) : defs_.end();
            if (fn == defs_.end()) return std::make_shared<ECall>(c.name, std::move(args), c.scope);
            const Def& def = fn->second;
            if (std::find(stack.begin(), stack.end(), def.name) != stack.end()) {
                std::vector<std::string> chain = stack;
                chain.push_back(def.name);
                throw FunctionError("'" + def.name + "' calls itself (" + join(chain, " \xe2\x86\x92 ") +
                                    "). A function is worked out where it is called, so there would be nothing to stop at.",
                                    stack.empty() ? owner : std::optional<std::string>(stack[0]));
            }
            const std::vector<std::string>& params = def.parameters;
            if (args.size() != params.size()) {
                std::string named = params.empty() ? "" : " (" + join(params, ", ") + ")";
                throw FunctionError("'" + def.name + "' takes " + std::to_string(params.size()) + " argument" + (params.size() == 1 ? "" : "s") + named +
                                    ", but is called with " + std::to_string(args.size()) + ".", owner);
            }
            std::unordered_map<std::string, ENodePtr> bound;
            // (A parameter named twice is refused when the model is read; the last would win here, as there.)
            for (std::size_t i = 0; i < params.size(); i++) bound[params[i]] = args[i];
            ENodePtr body = substitute(def.ast, bound, def.name);
            std::string fsys = js_truthy(def.block.get("system")) ? js_str(def.block.get("system")) : "";
            std::vector<std::string> deeper = stack;
            deeper.push_back(def.name);
            return expand(body, owner, fsys, deeper, depth + 1);
        }
    }
    return ast;
}

}  // namespace kompartment
