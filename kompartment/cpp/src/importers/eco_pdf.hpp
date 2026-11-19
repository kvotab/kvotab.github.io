// A parameter's probability distribution as Ecolego writes it, read into the dictionary a model
// file stores: the Julia package's importers/eco_pdf.jl (`parse_pdf` of the Python package's
// stats/pdf.py, `parsePdf` in the application), as far as the importer needs it.

#pragma once

#include <optional>
#include <string>
#include <string_view>

#include "util/json.hpp"

namespace kompartment::eco {

/// `Number(s)` as pdf.py reads a number: a decimal literal (with `Infinity`), or `0x`, `0o`, `0b`
/// digits of that base only; anything else NaN; blank 0.
double pdf_number(std::string_view s);

/// Reads Ecolego's expression into a distribution, or none if it is not one. `expr` is the
/// `<pdf-value>` text, `logt(min=1,max=9,mode=3)`; `function_name` the `function=` attribute,
/// which names the kind (and tells the three log-normals apart). A list's values are separated
/// by `;`: `pg(values=1;2;3,inorder=true,pos=0)`.
std::optional<Json> parse_pdf(std::string_view expr, std::string_view function_name);

}  // namespace kompartment::eco
