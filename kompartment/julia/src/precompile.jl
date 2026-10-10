# What a session's first run would otherwise compile, compiled once into the
# package image: a small model opened, built, run by each of the solvers here,
# and its results read and written. A model's own generated code is compiled
# when it is built, as every model's is; everything around it is here already.

using PrecompileTools: @setup_workload, @compile_workload

@setup_workload begin
    text = """
    {"name": "Precompile", "nuclides": ["Cs-137", "Sr-90"],
     "simulation": {"start_time": 0, "end_time": 1000, "output_points": 20, "rtol": 1e-6, "abstol": 1e-12},
     "parameters": [{"name": "k", "value": 0.05, "index_lists": [],
                     "pdf": {"kind": "logt", "params": {"min": 0.01, "max": 0.1, "mode": 0.05}}},
                    {"name": "q", "value": 1.0, "index_lists": [],
                     "pdf": {"kind": "norm", "params": {"mean": 1.0, "sd": 0.1}, "trmin": 0}}],
     "lookups": [{"name": "Q", "points": [[0, 1], [500, 2], [1000, 1]], "index_lists": []}],
     "compartments": [{"name": "Soil", "initial": "1e10"}, {"name": "Well"}],
     "expressions": [{"name": "Conc", "equation": "Well / 2", "unit": "Bq/m3"}],
     "transfers": [{"name": "Soil_Well", "from": "Soil", "to": "Well", "rate": "k * Q"},
                   {"name": "Well_out", "from": "Well", "rate": "0.1 * min(1, Well / (1 + Well))"}],
     "min_maxes": [{"name": "Peak", "target": "Conc", "operation": "max"}]}
    """
    # An Ecolego model.xml, made up: two nuclides that decay one into the
    # other, a root list, a sub-set and a mapped list, per-index entries, a
    # lookup table, an expression and transfers.
    eco = """<?xml version="1.0" encoding="UTF-8"?>
    <data-model>
      <project-properties name="Precompile"><comment><![CDATA[made up]]></comment></project-properties>
      <material-model>
        <nuclide name="Cs-137"><id>nuc-cs</id><half-life>949233116.16</half-life><z>55</z><a>137</a></nuclide>
        <nuclide name="Ba-137m"><id>nuc-ba</id><half-life>153.12</half-life><z>56</z><a>137</a></nuclide>
      </material-model>
      <index-list-model>
        <index-list name="Nuclides"><id>il-nuc</id>
          <index name="Cs-137" enabled="true"><id>ix-cs</id></index>
          <index name="Ba-137m" enabled="true"><id>ix-ba</id></index>
        </index-list>
        <index-list name="Objects"><id>il-obj</id>
          <index name="Lake" enabled="true"><id>ix-lake</id></index>
          <index name="Mire" enabled="true"><id>ix-mire</id></index>
        </index-list>
        <index-list name="Wet"><id>il-wet</id>
          <index name="Lake" enabled="true"><id>ix-wlake</id></index>
          <sub-set of="il-obj"/>
        </index-list>
      </index-list-model>
      <nuclide-decay-model><decay-pair parent="Cs-137" daughter="Ba-137m" rate="0.944"/></nuclide-decay-model>
      <block-model>
        <component name="Soil" type="compartment" index-lists="il-nuc,il-obj"><id>blk-soil</id><unit>Bq</unit>
          <handle-decay>true</handle-decay>
          <entry type="compartment"><initial-condition><![CDATA[0]]></initial-condition></entry>
          <entry type="compartment" index="ix-cs,ix-lake"><initial-condition><![CDATA[1.0e10]]></initial-condition></entry>
        </component>
        <component name="Deep" type="compartment" index-lists="il-nuc,il-obj"><id>blk-deep</id><unit>Bq</unit>
          <entry type="compartment"><initial-condition><![CDATA[0]]></initial-condition></entry>
        </component>
        <component name="k" type="parameter" index-lists="il-obj"><id>blk-k</id><unit>1/year</unit>
          <entry type="parameter"><value>0.001</value></entry>
          <entry type="parameter" index="ix-lake"><value>0.05</value></entry>
        </component>
        <component name="Q" type="lookup-table"><id>blk-q</id>
          <lookup-option><![CDATA[Use Input Below]]></lookup-option>
          <entry type="lookup-table">
            <lookup-table-time-points><![CDATA[[0.0, 500.0, 1000.0]]]></lookup-table-time-points>
            <lookup-table-values><![CDATA[[1.0, 2.0, 1.0]]]></lookup-table-values>
          </entry>
        </component>
        <component name="Total" type="expression" index-lists="il-obj"><id>blk-total</id><unit>Bq</unit>
          <entry type="expression"><equation><![CDATA[Soil[Cs-137] + Deep[Cs-137]]]></equation></entry>
        </component>
        <connection name="Leach" type="transfer" source="blk-soil" target="blk-deep" index-lists="il-nuc,il-obj">
          <id>blk-leach</id><unit>1/year</unit>
          <entry type="transfer"><transfer-equation><![CDATA[k * Q]]></transfer-equation>
            <multiply-with-donor>true</multiply-with-donor></entry>
        </connection>
        <connection name="Out" type="transfer" source="blk-deep" index-lists="il-nuc,il-obj"><id>blk-out</id>
          <entry type="transfer"><transfer-equation><![CDATA[0.001]]></transfer-equation>
            <multiply-with-donor>true</multiply-with-donor></entry>
        </connection>
      </block-model>
      <simulation-settings>
        <start-time>0.0</start-time><end-time>1000.0</end-time><time-unit>year</time-unit>
        <java-solver>java&#45;ode15s</java-solver>
        <rel-error-tolerance>1.0E-7</rel-error-tolerance><abs-error-tolerance>1.0E-12</abs-error-tolerance>
      </simulation-settings>
    </data-model>"""
    # And a transport: a chain of N compartments in a sub-system of its own,
    # with its counter, a number and the operations along it.
    chain = """<?xml version="1.0" encoding="UTF-8"?>
    <data-model>
      <project-properties name="Chain"/>
      <material-model/>
      <index-list-model/>
      <hierarchy-model>
        <sub-system-block name="Model"><id>root</id></sub-system-block>
        <sub-system-block name="Column" type="transport"><id>ss-col</id><sub-system>root</sub-system></sub-system-block>
      </hierarchy-model>
      <block-model>
        <component name="Pond" type="compartment"><id>blk-pond</id><unit>Bq</unit>
          <entry type="compartment"><initial-condition><![CDATA[100]]></initial-condition></entry></component>
        <component name="Top" type="transport-begin"><id>blk-top</id><sub-system>ss-col</sub-system><unit>Bq</unit>
          <entry type="compartment"><initial-condition><![CDATA[0]]></initial-condition></entry></component>
        <component name="Bottom" type="transport-end"><id>blk-bottom</id><sub-system>ss-col</sub-system><unit>Bq</unit>
          <entry type="compartment"><initial-condition><![CDATA[0]]></initial-condition></entry></component>
        <component name="N" type="transport-number"><id>blk-n</id><sub-system>ss-col</sub-system>
          <evaluation-mode>SIMULATION</evaluation-mode>
          <entry type="expression"><equation><![CDATA[4]]></equation></entry></component>
        <component name="i" type="transport-element-counter"><id>blk-i</id><sub-system>ss-col</sub-system></component>
        <component name="Held" type="transport-operation"><id>blk-held</id><sub-system>ss-col</sub-system>
          <operation><![CDATA[SUM]]></operation></component>
        <component name="Mid" type="transport-operation"><id>blk-mid</id><sub-system>ss-col</sub-system>
          <operation><![CDATA[MEAN]]></operation>
          <argument><argument-key>point</argument-key><argument-name>Point</argument-name></argument></component>
        <component name="Halfway" type="expression"><id>blk-half</id>
          <entry type="expression"><equation><![CDATA[blk-mid(0.5)]]></equation></entry></component>
        <connection name="Feed" type="transfer" source="blk-pond" target="blk-top"><id>blk-feed</id>
          <entry type="transfer"><transfer-equation><![CDATA[0.1]]></transfer-equation>
            <multiply-with-donor>true</multiply-with-donor></entry></connection>
        <connection name="Down" type="transfer" source="blk-top" target="blk-bottom"><id>blk-down</id>
          <sub-system>ss-col</sub-system>
          <entry type="transfer"><transfer-equation><![CDATA[0.2 * blk-i]]></transfer-equation>
            <multiply-with-donor>true</multiply-with-donor></entry></connection>
      </block-model>
      <simulation-settings>
        <start-time>0.0</start-time><end-time>10.0</end-time><time-unit>year</time-unit>
        <java-solver>java&#45;ode15s</java-solver>
        <rel-error-tolerance>1.0E-8</rel-error-tolerance><abs-error-tolerance>1.0E-12</abs-error-tolerance>
      </simulation-settings>
    </data-model>"""
    # The application's own synthetic Ecolego model (its importer tests'):
    # index reductions and aggregates, the blocks that remember, a discrete
    # event, a delay, lookups read at the clock and at an argument.
    recorders = """
    <?xml version="1.0" encoding="UTF-8"?>
    <data-model>
    	<project-properties name="Test import">
    		<comment><![CDATA[A synthetic project for the importer tests]]></comment>
    	</project-properties>

    	<material-model>
    		<nuclide name="Cs-137">
    			<id>nuc-cs</id>
    			<half-life>949233116.16</half-life>
    			<z>55</z><a>137</a>
    		</nuclide>
    		<nuclide name="Ba-137m">
    			<id>nuc-ba</id>
    			<half-life>153.12</half-life>
    			<z>56</z><a>137</a>
    		</nuclide>
    	</material-model>

    	<index-list-model>
    		<index-list name="Nuclides">
    			<id>il-nuc</id>
    			<index name="Cs-137" enabled="true"><id>ix-cs</id></index>
    			<index name="Ba-137m" enabled="true"><id>ix-ba</id></index>
    		</index-list>
    		<index-list name="Landscape objects">
    			<id>il-obj</id>
    			<index name="Lake" enabled="true"><id>ix-lake</id></index>
    			<index name="Mire" enabled="true"><id>ix-mire</id></index>
    			<index name="Forest" enabled="false"><id>ix-forest</id></index>
    		</index-list>
    		<index-list name="Region">
    			<id>il-reg</id>
    			<index name="North" enabled="true"><id>ix-north</id></index>
    			<index name="South" enabled="true"><id>ix-south</id></index>
    		</index-list>
    		<index-list name="Wetlands">
    			<id>il-wet</id>
    			<index name="Lake" enabled="true"><id>ix-wlake</id></index>
    			<index name="Mire" enabled="true"><id>ix-wmire</id></index>
    			<sub-set of="il-obj"/>
    		</index-list>
    		<index-list name="ObjRegion">
    			<id>il-objreg</id>
    			<index name="Lake" enabled="true"><id>ix-mlake</id></index>
    			<index name="Mire" enabled="true"><id>ix-mmire</id></index>
    			<mapping to="il-reg">
    				<map from="ix-mlake" to="ix-north"/>
    				<map from="ix-mmire" to="ix-south"/>
    			</mapping>
    		</index-list>
    	</index-list-model>

    	<nuclide-decay-model>
    		<decay-pair parent="Cs-137" daughter="Ba-137m" rate="0.944"/>
    	</nuclide-decay-model>

    	<block-model>
    		<component name="Soil" type="compartment" index-lists="il-nuc,il-obj">
    			<id>blk-soil</id>
    			<unit>Bq</unit>
    			<comment><![CDATA[Top soil layer]]></comment>
    			<handle-decay>true</handle-decay>
    			<entry type="compartment">
    				<initial-condition><![CDATA[0]]></initial-condition>
    				<lower-saturation>0</lower-saturation>
    				<upper-saturation></upper-saturation>
    			</entry>
    			<entry type="compartment" index="ix-cs,ix-lake">
    				<initial-condition><![CDATA[1.0e10]]></initial-condition>
    			</entry>
    		</component>

    		<component name="Deep soil" type="compartment" index-lists="il-nuc,il-obj">
    			<id>blk-deep</id>
    			<unit>Bq</unit>
    			<entry type="compartment">
    				<initial-condition><![CDATA[0]]></initial-condition>
    			</entry>
    		</component>

    		<component name="k leach" type="parameter" index-lists="il-obj">
    			<id>blk-k</id>
    			<unit>1/year</unit>
    			<entry type="parameter">
    				<value>0.001</value>
    			</entry>
    			<entry type="parameter" index="ix-lake">
    				<value>0.05</value>
    			</entry>
    			<entry type="parameter" index="ix-mire">
    				<value>0.02</value>
    			</entry>
    		</component>

    		<component name="Total" type="expression" index-lists="il-obj">
    			<id>blk-total</id>
    			<unit>Bq</unit>
    			<entry type="expression">
    				<equation><![CDATA[Soil[Cs-137] + Deep_soil[Cs-137]]]></equation>
    			</entry>
    		</component>

    		<component name="Sorption" type="lookup-table" index-lists="il-obj">
    			<id>blk-lookup</id>
    			<unit>m3/kg</unit>
    			<lookup-option><![CDATA[Use Input Below]]></lookup-option>
    			<lookup-cyclic>false</lookup-cyclic>
    			<entry type="lookup-table">
    				<lookup-table-time-points><![CDATA[[0.0, 500.0]]]></lookup-table-time-points>
    				<lookup-table-values><![CDATA[[1.0, 4.0]]]></lookup-table-values>
    			</entry>
    			<entry type="lookup-table" index="ix-lake">
    				<lookup-table-time-points><![CDATA[[0.0, 500.0]]]></lookup-table-time-points>
    				<lookup-table-values><![CDATA[[2.0, 8.0]]]></lookup-table-values>
    			</entry>
    		</component>

    		<component name="Retardation" type="lookup-table">
    			<id>blk-lookup-arg</id>
    			<argument>
    				<argument-key>X</argument-key>
    				<argument-name>X</argument-name>
    			</argument>
    			<lookup-option><![CDATA[Interpolation-Use End Values]]></lookup-option>
    			<entry type="lookup-table">
    				<lookup-table-time-points><![CDATA[[0.0, 10.0]]]></lookup-table-time-points>
    				<lookup-table-values><![CDATA[[0.0, 20.0]]]></lookup-table-values>
    			</entry>
    		</component>

    		<component name="Held up" type="delay" index-lists="il-obj">
    			<id>blk-delay</id>
    			<entry type="delay">
    				<delay-target><![CDATA[blk-total]]></delay-target>
    				<delay-time><![CDATA[50.0]]></delay-time>
    			</entry>
    		</component>

    		<component name="Half way" type="discrete&#45;event">
    			<id>blk-event</id>
    			<entry type="discrete&#45;event">
    				<first-expression><![CDATA[time]]></first-expression>
    				<second-expression><![CDATA[100.0]]></second-expression>
    				<direction><![CDATA[RIGHT]]></direction>
    			</entry>
    		</component>

    		<component name="Peak total" type="min&#45;max" index-lists="il-obj">
    			<id>blk-minmax</id>
    			<operation><![CDATA[MAX]]></operation>
    			<entry type="min&#45;max">
    				<target-expression><![CDATA[blk-total]]></target-expression>
    			</entry>
    		</component>

    		<component name="Mean total" type="running&#45;mean" index-lists="il-obj">
    			<id>blk-mean</id>
    			<entry type="running&#45;mean">
    				<target-expression><![CDATA[blk-total]]></target-expression>
    				<start-recording-event><![CDATA[blk-event]]></start-recording-event>
    			</entry>
    		</component>

    		<component name="Time of crossing" type="snapshot">
    			<id>blk-snap</id>
    			<entry type="snapshot">
    				<snapshot-target><![CDATA[time]]></snapshot-target>
    				<snapshot-event><![CDATA[blk-event]]></snapshot-event>
    				<snapshot-initial-value><![CDATA[-1.0]]></snapshot-initial-value>
    			</entry>
    		</component>

    		<component name="Depth" type="transport&#45;begin">
    			<id>blk-transport</id>
    		</component>

    		<component name="Soil total" type="index-operation" index-lists="il-nuc">
    			<id>blk-iop</id>
    			<unit>Bq</unit>
    			<operation><![CDATA[Sum]]></operation>
    			<entry type="expression">
    				<equation><![CDATA[blk-soil]]></equation>
    			</entry>
    		</component>

    		<component name="Everywhere" type="aggregate" index-lists="il-nuc,il-obj">
    			<id>blk-agg</id>
    			<operation><![CDATA[MAX]]></operation>
    			<entry type="expression">
    				<equation><![CDATA[blk-soil+blk-deep]]></equation>
    			</entry>
    		</component>

    		<component name="Orphan sum" type="index-operation" index-lists="il-nuc">
    			<id>blk-iop-orphan</id>
    			<operation><![CDATA[SUM]]></operation>
    			<entry type="expression">
    				<equation><![CDATA[blk-transport]]></equation>
    			</entry>
    		</component>

    		<connection name="Leaching" type="transfer" source="blk-soil" target="blk-deep"
    		            index-lists="il-nuc,il-obj">
    			<id>blk-leach</id>
    			<unit>1/year</unit>
    			<entry type="transfer">
    				<transfer-equation><![CDATA[k_leach]]></transfer-equation>
    				<multiply-with-donor>true</multiply-with-donor>
    			</entry>
    		</connection>

    		<connection name="Outflow" type="transfer" source="blk-deep"
    		            index-lists="il-nuc,il-obj">
    			<id>blk-out</id>
    			<entry type="transfer">
    				<transfer-equation><![CDATA[0.001]]></transfer-equation>
    				<multiply-with-donor>true</multiply-with-donor>
    			</entry>
    		</connection>
    	</block-model>

    	<simulation-settings>
    		<start-time>0.0</start-time>
    		<end-time>1000.0</end-time>
    		<time-unit>year</time-unit>
    		<java-solver>java&#45;ode15s</java-solver>
    		<rel-error-tolerance>1.0E-7</rel-error-tolerance>
    		<abs-error-tolerance>1.0E-12</abs-error-tolerance>
    		<simulation-type>DETERMINISTIC</simulation-type>
    	</simulation-settings>
    </data-model>"""
    @compile_workload begin
        m = from_json(text)
        for solver in ("ndf", "ros23", "dp45")
            res = run(m; solver=solver)
            to_csv(res)
            series_many(res, outputs(res))
            summary(res)
        end
        to_json(m)
        # A probabilistic run of a few realisations, and what it says.
        prob = run_probabilistic(m, 4; seed=1, threads=1)
        bands(prob)
        what_drove(prob, labels(prob)[1])
        summary(prob, labels(prob)[1]; at=:peak)
        write_hdf5(probabilistic_tree(prob, "all"))
        e = import_ecolego(Vector{UInt8}(codeunits(eco)); file_name="precompile.eco")
        res = run(e)
        run(import_ecolego(Vector{UInt8}(codeunits(chain)); file_name="chain.eco"))
        rec = run(import_ecolego(Vector{UInt8}(codeunits(recorders)); file_name="recorders.eco"))
        run_log(rec)
        mktempdir() do dir
            save(res, joinpath(dir, "all.h5"))
            save(res, joinpath(dir, "soil.h5"); blocks=["Soil"], time_origin=100)
            save(res, joinpath(dir, "soil.csv"); outputs=outputs(res, "Soil"))
        end
    end
end
