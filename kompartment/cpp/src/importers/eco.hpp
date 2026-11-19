// Importing Ecolego projects (.eco), assessments (.eas) and Ecolego 4/5 model XML into
// Kompartment's own model format: a port of the Julia package's importers/eco.jl and open.jl,
// themselves ports of the Python package's importer and the application's src/io/eco.js. The
// same file gives the same model -- a project dictionary in Kompartment's own format, key order
// included -- and the same report of what was renamed, skipped, switched off or could not come
// across, to the byte.
//
// A .eco file is a ZIP of the Ecolego project folder, and the model is its model.xml. An .eas
// assessment is the same archive with a run stored in it, and is read exactly as a project is:
// the model comes across, the results do not. The older Ecolego 4/5 format, a bare XML file
// (usually UTF-16), is accepted too when it holds a `<data-model>`, and refused with an
// explanation when it is a `<sheet>`.
//
// The mapping is deliberately lossy and says so: what has no equivalent here is skipped and
// listed in the report, so the result is usable or explicitly incomplete -- never silently wrong.
// The project returned is the importer's own output; the other engines' normalisation of a model
// they open (key migration, defaults, derived units) is not applied here.

#pragma once

#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "importers/eco_maps.hpp"
#include "util/json.hpp"

namespace kompartment::eco {

/// What an import did: what came across, what was renamed, and above all what could not come
/// across (`EcoImportReport` in the Julia package, `ImportReport` in the Python package).
struct EcoImportReport {
    Json skipped = Json::array();    // {type, name, why} per block that has no equivalent here
    Json notes = Json::array();      // {type, name} per block present but numerically inert
    Json renamed = Json::array();    // {from, to} per name tidied into an identifier
    std::vector<std::string> disabled;   // blocks imported switched off, as in Ecolego
    /// Sub-system path => blocks inside it, for each sub-system the file switches off whole.
    std::optional<std::vector<std::pair<std::string, long long>>> disabled_systems;
    std::vector<std::string> warnings;   // what else is worth reading, each said once
    std::vector<std::pair<std::string, long long>> counts;   // how many of each kind came across
    std::set<std::string> said;

    /// Whether every block came across.
    bool ok() const { return skipped.empty(); }
    /// A short account in words, one line per kind of thing to say.
    std::string summary() const;
    /// The report as plain data, in the order and shape of the Julia package's `to_dict`.
    Json to_json() const;
};

struct EcoImport {
    Json project;
    EcoImportReport report;
};

/// Reads an Ecolego project (`.eco`), assessment (`.eas`) or bare `model.xml` from its bytes.
/// `file_name` is which file this is (it goes into the model's name and description);
/// `version` the Ecolego version, for a bare XML file (an archive's `.version` is used instead).
/// Throws EcoImportError for a file it cannot read, EcoArgumentError("Invalid time value") for a
/// modification date past what a JavaScript `Date` holds, EcoUnsupportedError for an archive
/// entry of a later ZIP version. An archive is inflated by the engine's own inflater, as zlib 1.3.1
/// inflates (importers/inflate.hpp); `with_zlib` inflates by the build's zlib instead, where it has
/// one -- for the tests, which check the two against each other.
EcoImport import_eco_file(std::string bytes, const std::optional<std::string>& file_name = std::nullopt,
                          const std::optional<std::string>& version = std::nullopt, bool with_zlib = false);

/// The same, read from a path: its name is the file's.
EcoImport import_eco_path(const std::string& path, const std::optional<std::string>& version = std::nullopt);

/// Reads a bare `model.xml`'s text.
EcoImport import_model_xml(std::string text, const std::optional<std::string>& file_name = std::nullopt,
                           const std::optional<std::string>& version = std::nullopt);

/// Whether a path names an Ecolego file the engine opens by importing it (`.eco`, `.eas` or
/// `.xml`, in any case), as the Julia package's `load` decides.
bool is_ecolego_path(std::string_view path);

/// Which Ecolego wrote an archive, as its `.version` properties say: `version=6.5 ...`.
std::optional<std::string> version_in(std::string_view text);

}  // namespace kompartment::eco
