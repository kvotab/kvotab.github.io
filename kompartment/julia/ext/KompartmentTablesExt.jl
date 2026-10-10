# A run's results as a Tables.jl table: `DataFrame(res)`, `CSV.write(path, res)`,
# and whatever else reads tables, with a `time` column and one per series.

module KompartmentTablesExt

using Kompartment
using Tables

import Kompartment: Results, ResultTable

Tables.istable(::Type{ResultTable}) = true
Tables.columnaccess(::Type{ResultTable}) = true
Tables.columns(t::ResultTable) = t
Tables.columnnames(t::ResultTable) = Symbol.(t.names)
Tables.getcolumn(t::ResultTable, i::Int) = t.columns[i]
function Tables.getcolumn(t::ResultTable, name::Symbol)
    i = findfirst(==(String(name)), t.names)
    i === nothing && throw(ArgumentError("No column named $name"))
    return t.columns[i]
end
Tables.schema(t::ResultTable) = Tables.Schema(Symbol.(t.names), fill(Float64, length(t.names)))

# A Results is the table of every series it has.
Tables.istable(::Type{Results}) = true
Tables.columnaccess(::Type{Results}) = true
Tables.columns(res::Results) = Kompartment.table(res)

end # module
