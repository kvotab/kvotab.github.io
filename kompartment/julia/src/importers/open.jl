# Ecolego projects and assessments opened as models.

"""
    import_ecolego(source; file_name=nothing, version=nothing) -> Model

A model imported from an Ecolego project (`.eco`), assessment (`.eas`) or
bare `model.xml`, as the application's *Import* reads it: `source` is a path
or the file's bytes. What the import left out, renamed or switched off is in
`m.import_report` (`skipped`, `renamed`, `disabled`, `warnings`, `counts`);
read it before trusting the numbers. Throws `EcoImportError` for a file that
cannot be read.
"""
function import_ecolego(source; file_name=nothing, version=nothing)
    project, report = import_eco_file(source; file_name, version)
    m = Model(project; path=source isa AbstractString ? source : nothing)
    m.import_report = report
    return m
end
