# What a session's first edits would otherwise compile, compiled once into the
# package image: a small model made and edited through the API -- blocks of
# every common kind added, values set per index, a rename, a move and a
# delete followed through the references, an index list, the settings and
# the view, the model checked and written.

using PrecompileTools: @setup_workload, @compile_workload

@setup_workload begin
    @compile_workload begin
        m = new_model("Precompile")
        add_nuclides!(m, ["Cs-137", "Sr-90"])
        add_compartment!(m, "Soil"; initial="1e10")
        add_compartment!(m, "Well")
        add_parameter!(m, "k", 0.05; unit="1/year")
        t = add_transfer!(m, "Soil", "Well"; rate="k")
        add_expression!(m, "Conc", "Well / 10")
        add_index_reduction!(m, "Total", "Conc")
        add_lookup!(m, "Q", [[0, 1], [100, 2]]; argument="x")
        add_inflow!(m, "Soil", "1")
        add_min_max!(m, "Peak", "Conc")
        soil = m["Soil"]
        set_value!(soil, "5e9"; at="Cs-137")
        set_entry!(soil, "Sr-90"; initial="2", abstol=1e-3)
        value_at(soil, "Cs-137")
        soil.initial = "2e10"
        t.multiply_by_donor
        m["k"].distribution = distributions.log_triangular(0.01, 0.1, 0.05)
        add_index_list!(m, "Object", ["Lake", "Mire"])
        set_dimensions!(m, "Soil", ["Radionuclides", "Object"])
        rename_index!(m, "Object", "Lake", "Pond")
        add_system!(m, "Near")
        rename_block!(m, "Soil", "Topsoil")
        move_block!(m, "Topsoil", "Near")
        references_to(m, "Near.Topsoil")
        try
            delete_block!(m, "Well")
        catch e
            e isa EditError || rethrow()
        end
        delete_blocks!(m, ["Peak"])
        sim = m.simulation
        sim.end_time = 1e5
        update!(sim; rtol=1e-6)
        m.view.show_parameters = true
        check(m)
        to_json(m)
    end
end
