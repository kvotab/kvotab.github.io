#include "engine/errorinfo.hpp"

#include <new>
#include <stdexcept>

#include "engine/builder.hpp"
#include "engine/farfield.hpp"
#include "engine/farfield_laplace.hpp"
#include "engine/indexspace.hpp"
#include "engine/jacobian.hpp"
#include "engine/localsens.hpp"
#include "engine/lookup.hpp"
#include "engine/probabilistic.hpp"
#include "engine/project.hpp"
#include "engine/transport.hpp"
#include "engine/unitcheck.hpp"
#include "engine/userfunctions.hpp"
#include "lang/ast.hpp"
#include "lang/functions.hpp"
#include "solvers/matrix.hpp"
#include "solvers/types.hpp"
#include "util/errors.hpp"
#include "util/json.hpp"

namespace kompartment {

namespace {

/// An error that prints its message alone and carries it as `message`.
ErrorInfo plain(const char* name, const std::string& message) { return {name, message, message, std::nullopt, std::nullopt}; }

/// An error Julia shows with its name in front (`ArgumentError: ...`), carrying no `message`.
ErrorInfo named(const std::string& name, const std::string& text) { return {name, name + ": " + text, text, std::nullopt, std::nullopt}; }

/// An error whose shown text is `shown`; the service's message is that without the name in front.
ErrorInfo shown_as(const std::string& name, const std::string& shown) {
    std::string prefix = name + ": ";
    std::string message = shown.compare(0, prefix.size(), prefix) == 0 ? shown.substr(prefix.size()) : shown;
    return {name, shown, message, std::nullopt, std::nullopt};
}

}  // namespace

ErrorInfo error_info(const std::exception_ptr& e) {
    try {
        std::rethrow_exception(e);
    } catch (const SolverError& x) {
        return {"SolverError", x.message, x.message, x.block_name, x.hint};
    } catch (const BuildError& x) {
        return {"BuildError", x.what(), x.what(), x.block_name, std::nullopt};
    } catch (const ValidationError& x) {
        return plain("ValidationError", x.what());
    } catch (const NotSupported& x) {
        return plain("NotSupported", x.what());
    } catch (const SensitivityError& x) {
        return plain("SensitivityError", x.what());
    } catch (const JsonError& x) {
        // Shown with where it is (`(at byte n)`); its message is what is wrong.
        std::string shown = x.what();
        std::string where = " (at byte " + std::to_string(x.position) + ")";
        std::string message = shown.size() >= where.size() && shown.compare(shown.size() - where.size(), where.size(), where) == 0
                                  ? shown.substr(0, shown.size() - where.size())
                                  : shown;
        return {"JSONError", shown, message, std::nullopt, std::nullopt};
    } catch (const ArgumentError& x) {
        return named("ArgumentError", x.what());
    } catch (const JuliaError& x) {
        return shown_as(x.kind, x.what());
    } catch (const FarfError& x) {
        return plain("FarfError", x.what());
    } catch (const lp::LaplacePathError& x) {
        return plain("LaplacePathError", x.what());
    } catch (const lp::JlInexactError& x) {
        return shown_as("InexactError", x.what());
    } catch (const lp::PyLogDomainError& x) {
        // Julia's `DomainError(x, "math domain error")`.
        return shown_as("DomainError", "DomainError with " + julia_float(x.x) + ":\nmath domain error");
    } catch (const LookupError& x) {
        return plain("LookupError", x.what());
    } catch (const TransportError& x) {
        return plain("TransportError", x.what());
    } catch (const FunctionError& x) {
        return plain("FunctionError", x.what());
    } catch (const IndexSpaceError& x) {
        return plain("IndexSpaceError", x.what());
    } catch (const UnitClash& x) {
        return plain("UnitClash", x.what());
    } catch (const TransportRangeError& x) {
        return plain("TransportRangeError", x.what());
    } catch (const EquationSyntaxError& x) {
        return plain("EquationSyntaxError", x.what());
    } catch (const EquationParseError& x) {
        return plain("EquationParseError", x.what());
    } catch (const MatrixError& x) {
        // Julia's has no `message` (its `msg`): the shown text is the message.
        return shown_as("MatrixError", x.what());
    } catch (const NoDerivative& x) {
        return shown_as("NoDerivative", std::string("No derivative rule for ") + x.what());
    } catch (const std::bad_alloc&) {
        return shown_as("OutOfMemoryError", "OutOfMemoryError()");
    } catch (const std::invalid_argument& x) {
        // What this engine refuses as Julia's `ArgumentError` refuses it (an unknown solver).
        return named("ArgumentError", x.what());
    } catch (const std::domain_error& x) {
        return named("DomainError", x.what());
    } catch (const std::exception& x) {
        // Julia's `error(...)`: an `ErrorException`, shown as its message.
        return shown_as("ErrorException", x.what());
    } catch (...) {
        return shown_as("ErrorException", "an error that says nothing of itself");
    }
}

}  // namespace kompartment
