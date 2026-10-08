/**
 * Test fixtures for the .eco importer.
 *
 * The model.xml below is written by hand to match what
 * real project files carry: the same element names,
 * attribute names, id references and CDATA usage. It is small on purpose: the
 * real project files the importer was measured against (see INTERNALS.md,
 * "Importing .eco projects") are megabytes each and not part of this
 * repository, and a fixture is for exercising one rule at a time.
 *
 * Also here: a minimal ZIP writer, so the reader can be exercised end to end
 * on both stored and deflated entries.
 */

const CRC_TABLE = (() => {
	const t = new Uint32Array(256);
	for (let i = 0; i < 256; i++) {
		let c = i;
		for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
		t[i] = c >>> 0;
	}
	return t;
})();

function crc32(bytes) {
	let c = 0xffffffff;
	for (let i = 0; i < bytes.length; i++) {
		c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
	}
	return (c ^ 0xffffffff) >>> 0;
}

/**
 * Compresses with whatever the host provides: CompressionStream where it
 * supports raw deflate, otherwise Node's zlib. Test-only, so reaching for a
 * Node builtin here is fine -- src/ stays dependency-free.
 */
async function deflateRaw(raw) {
	try {
		if (typeof CompressionStream !== 'undefined') {
			const s = new Blob([raw]).stream()
				.pipeThrough(new CompressionStream('deflate-raw'));
			return new Uint8Array(await new Response(s).arrayBuffer());
		}
	} catch {
		// fall through to zlib
	}
	const { deflateRawSync } = await import('node:zlib');
	return new Uint8Array(deflateRawSync(raw));
}

/**
 * @param {Array<{name: string, text: string, deflate?: boolean}>} files
 * @returns {Promise<Uint8Array>}
 */
export async function makeZip(files) {
	const enc = new TextEncoder();
	const locals = [];
	const centrals = [];
	let offset = 0;

	for (const f of files) {
		const nameBytes = enc.encode(f.name);
		// A result file is bytes rather than text.
		const raw = f.bytes ?? enc.encode(f.text);
		const crc = crc32(raw);

		let stored = raw;
		let method = 0;
		if (f.deflate) {
			stored = await deflateRaw(raw);
			method = 8;
		}

		const lfh = new Uint8Array(30 + nameBytes.length);
		const lv = new DataView(lfh.buffer);
		lv.setUint32(0, 0x04034b50, true);
		lv.setUint16(4, 20, true);        // version needed
		lv.setUint16(6, 0x800, true);     // UTF-8 names
		lv.setUint16(8, method, true);
		lv.setUint16(10, 0, true);        // time
		lv.setUint16(12, 0, true);        // date
		lv.setUint32(14, crc, true);
		lv.setUint32(18, stored.length, true);
		lv.setUint32(22, raw.length, true);
		lv.setUint16(26, nameBytes.length, true);
		lv.setUint16(28, 0, true);
		lfh.set(nameBytes, 30);

		locals.push(lfh, stored);

		const cdh = new Uint8Array(46 + nameBytes.length);
		const cv = new DataView(cdh.buffer);
		cv.setUint32(0, 0x02014b50, true);
		cv.setUint16(4, 20, true);
		cv.setUint16(6, 20, true);
		cv.setUint16(8, 0x800, true);
		cv.setUint16(10, method, true);
		cv.setUint32(16, crc, true);
		cv.setUint32(20, stored.length, true);
		cv.setUint32(24, raw.length, true);
		cv.setUint16(28, nameBytes.length, true);
		cv.setUint32(42, offset, true);
		cdh.set(nameBytes, 46);
		centrals.push(cdh);

		offset += lfh.length + stored.length;
	}

	const cdSize = centrals.reduce((n, c) => n + c.length, 0);
	const eocd = new Uint8Array(22);
	const ev = new DataView(eocd.buffer);
	ev.setUint32(0, 0x06054b50, true);
	ev.setUint16(8, files.length, true);
	ev.setUint16(10, files.length, true);
	ev.setUint32(12, cdSize, true);
	ev.setUint32(16, offset, true);

	const parts = [...locals, ...centrals, eocd];
	const total = parts.reduce((n, p) => n + p.length, 0);
	const out = new Uint8Array(total);
	let p = 0;
	for (const part of parts) { out.set(part, p); p += part.length; }
	return out;
}

/** Seconds per year as Ecolego's files hold a half-life: its `year`, 365.2425 days. */
const YEAR_S = 31556952;

/**
 * A model.xml exercising: nuclides with half-lives, a decay pair, a root index
 * list, a sub-set and a mapped list, compartments with default and indexed
 * entries, a transfer with an open end, a per-index parameter, an expression,
 * and an unsupported block type.
 */
export const MODEL_XML = `<?xml version="1.0" encoding="UTF-8"?>
<data-model>
	<project-properties name="Test import">
		<comment><![CDATA[A synthetic project for the importer tests]]></comment>
	</project-properties>

	<material-model>
		<nuclide name="Cs-137">
			<id>nuc-cs</id>
			<half-life>${30.08 * YEAR_S}</half-life>
			<z>55</z><a>137</a>
		</nuclide>
		<nuclide name="Ba-137m">
			<id>nuc-ba</id>
			<half-life>${2.552 * 60}</half-life>
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
</data-model>`;

export const VIEWS_XML = '<?xml version="1.0"?><presentation-model></presentation-model>';

/**
 * A second fixture built from what real .eco files turned out to contain:
 *
 *  - index ids are scoped to their list, so two lists both hold an index
 *    with id "H" (this is why entry keys must resolve per block dimension)
 *  - `transfer` defaults to multiply-with-donor FALSE, `transfer-coefficient`
 *    to TRUE (BlockXMLHandler)
 *  - source and sink are components that transfers attach to
 *  - two blocks in different sub-systems may share a name
 *  - hyphens in type attributes are written as &#45;
 */
export const REAL_SHAPES_XML = `<?xml version="1.0" encoding="UTF-8"?>
<data-model>
	<project-properties name="Real shapes"/>
	<index-list-model>
		<index-list name="Elements">
			<id>Elements</id>
			<index name="H" enabled="true"><id>H</id></index>
			<index name="Nb" enabled="true"><id>Nb</id></index>
		</index-list>
		<index-list name="Species">
			<id>Species</id>
			<index name="H" enabled="true"><id>H</id></index>
			<index name="Nb-ind" enabled="true"><id>Nb</id></index>
		</index-list>
	</index-list-model>
	<block-model>
		<component name="Boundary" type="source"><id>Src</id></component>
		<component name="Drain" type="sink"><id>Snk</id></component>

		<component name="Water" type="compartment" index-lists="Elements">
			<id>NF&#46;Water</id>
			<sub-system>NF</sub-system>
			<entry type="compartment"><initial-condition><![CDATA[1]]></initial-condition></entry>
		</component>

		<component name="Water" type="compartment" index-lists="Elements">
			<id>FF&#46;Water</id>
			<sub-system>FF</sub-system>
			<!-- Enough inventory that the constant outflow below stays physical. -->
			<entry type="compartment"><initial-condition><![CDATA[1000]]></initial-condition></entry>
		</component>

		<component name="k" type="parameter" index-lists="Elements">
			<id>k</id>
			<entry type="parameter"><value>0.1</value></entry>
			<entry type="parameter" index="Nb"><value>0.25</value></entry>
		</component>

		<component name="Inflow" type="parameter"><id>Inflow</id>
			<entry type="parameter"><value>3</value></entry>
		</component>

		<connection name="Feed" type="transfer" source="Src" target="NF&#46;Water"
		            index-lists="Elements">
			<id>Feed</id>
			<entry type="transfer"><transfer-equation><![CDATA[Inflow]]></transfer-equation></entry>
		</connection>

		<connection name="Move" type="transfer&#45;coefficient" source="NF&#46;Water"
		            target="FF&#46;Water" index-lists="Elements">
			<id>Move</id>
			<entry type="transfer"><transfer-equation><![CDATA[k]]></transfer-equation></entry>
		</connection>

		<connection name="Leak" type="transfer" source="FF&#46;Water" target="Snk"
		            index-lists="Elements">
			<id>Leak</id>
			<entry type="transfer"><transfer-equation><![CDATA[Inflow]]></transfer-equation></entry>
		</connection>

		<connection name="Watches" type="influence" source="k" target="FF&#46;Water">
			<id>Watches</id>
		</connection>
	</block-model>
	<simulation-settings>
		<start-time>0.0</start-time>
		<end-time>10.0</end-time>
		<time-unit>year</time-unit>
		<java-solver>java-ode45</java-solver>
	</simulation-settings>
</data-model>`;

/** The same document as UTF-16BE with a BOM, as Ecolego 5 wrote XML. */
export function toUtf16BE(text) {
	const out = new Uint8Array(2 + text.length * 2);
	out[0] = 0xfe; out[1] = 0xff;
	for (let i = 0; i < text.length; i++) {
		const c = text.charCodeAt(i);
		out[2 + i * 2] = c >> 8;
		out[3 + i * 2] = c & 0xff;
	}
	return out;
}

/** An Ecolego 4/5 <sheet> document, which the importer must recognise and refuse. */
export const SHEET_XML = `<?xml version="1.0" encoding="UTF-16" standalone="yes"?>
<sheet><cell-size><width>96</width></cell-size>
<simulation-model><simulation-model-name>Sheet</simulation-model-name></simulation-model>
</sheet>`;

/**
 * A transport sub-system as `HierarchyModelXMLPersistence` and
 * `BlockModelXMLPersistence` write one: `type="transport"` on the sub-system,
 * and the five block types -- `transport-begin`, `transport-end`,
 * `transport-number`, `transport-element-counter`, `transport-operation` --
 * for its parts. An operation with one `<argument>` is read at a point.
 */
export const TRANSPORT_XML = `<?xml version="1.0" encoding="UTF-8"?>
<data-model>
	<project-properties name="Transport import"/>
	<material-model/>
	<index-list-model/>
	<hierarchy-model>
		<sub-system-block name="Model"><id>root</id></sub-system-block>
		<sub-system-block name="Soil column" type="transport">
			<id>ss-col</id><sub-system>root</sub-system>
		</sub-system-block>
	</hierarchy-model>
	<block-model>
		<component name="Lake" type="compartment">
			<id>blk-lake</id><unit>Bq</unit>
			<entry type="compartment"><initial-condition><![CDATA[100]]></initial-condition></entry>
		</component>
		<component name="Begin" type="transport-begin">
			<id>blk-begin</id><sub-system>ss-col</sub-system><unit>Bq</unit>
			<entry type="compartment"><initial-condition><![CDATA[0]]></initial-condition></entry>
		</component>
		<component name="End" type="transport-end">
			<id>blk-end</id><sub-system>ss-col</sub-system><unit>Bq</unit>
			<entry type="compartment"><initial-condition><![CDATA[0]]></initial-condition></entry>
		</component>
		<component name="N" type="transport-number">
			<id>blk-n</id><sub-system>ss-col</sub-system>
			<evaluation-mode>SIMULATION</evaluation-mode>
			<entry type="expression"><equation><![CDATA[3]]></equation></entry>
		</component>
		<component name="i" type="transport-element-counter">
			<id>blk-i</id><sub-system>ss-col</sub-system>
		</component>
		<component name="Total" type="transport-operation">
			<id>blk-tot</id><sub-system>ss-col</sub-system>
			<operation><![CDATA[SUM]]></operation>
		</component>
		<component name="At" type="transport-operation">
			<id>blk-at</id><sub-system>ss-col</sub-system>
			<operation><![CDATA[MEAN]]></operation>
			<argument><argument-key>point</argument-key><argument-name>Point</argument-name></argument>
		</component>
		<component name="Halfway" type="expression">
			<id>blk-half</id>
			<entry type="expression"><equation><![CDATA[blk-at(0.5)]]></equation></entry>
		</component>
		<connection name="Feed" type="transfer" source="blk-lake" target="blk-begin">
			<id>blk-feed</id>
			<entry type="transfer">
				<transfer-equation><![CDATA[0.1]]></transfer-equation>
				<multiply-with-donor>true</multiply-with-donor>
			</entry>
		</connection>
		<connection name="Down" type="transfer" source="blk-begin" target="blk-end">
			<id>blk-down</id><sub-system>ss-col</sub-system>
			<entry type="transfer">
				<transfer-equation><![CDATA[0.2 * blk-i]]></transfer-equation>
				<multiply-with-donor>true</multiply-with-donor>
			</entry>
		</connection>
	</block-model>
	<simulation-settings>
		<start-time>0.0</start-time><end-time>10.0</end-time><time-unit>year</time-unit>
		<java-solver>java&#45;ode45</java-solver>
		<rel-error-tolerance>1.0E-8</rel-error-tolerance>
		<abs-error-tolerance>1.0E-12</abs-error-tolerance>
	</simulation-settings>
</data-model>`;

/**
 * General variables as the real files carry them: a block that stands in for
 * another, its pick written as the entry's equation -- the chosen block's id --
 * and the blocks it may stand for listed by id. The chosen block's unit is
 * copied onto the entry (Ecolego 5) or the block (Ecolego 6, which also names
 * a block in its own sub-system by its bare name). Then the oldest spelling,
 * `select`, which gives the pick and the list by GUID; a pick of its own at
 * one index; and a general variable with nothing picked.
 */
export const GENERAL_VARIABLE_XML = `<?xml version="1.0" encoding="UTF-8"?>
<data-model>
	<project-properties name="General variables"/>
	<index-list-model>
		<index-list name="Crops">
			<id>Crops</id>
			<index name="Grass" enabled="true"><id>Grass</id></index>
			<index name="Wheat" enabled="true"><id>Wheat</id></index>
		</index-list>
	</index-list-model>
	<hierarchy-model>
		<sub-system-block name="Bio"><id>Bio</id></sub-system-block>
	</hierarchy-model>
	<block-model>
		<component name="Conc&#95;par" type="parameter" dimension="1" index-lists="Crops">
			<id>Bio&#46;Conc&#95;par</id><sub-system>Bio</sub-system>
			<unit><![CDATA[Bq/m^3]]></unit>
			<guid><![CDATA[G-PAR]]></guid>
			<entry type="parameter"><value><![CDATA[2.0]]></value></entry>
			<entry type="parameter" index="Grass"><value><![CDATA[5.0]]></value></entry>
		</component>
		<component name="Conc&#95;calc" type="expression" dimension="1" index-lists="Crops">
			<id>Bio&#46;Conc&#95;calc</id><sub-system>Bio</sub-system>
			<unit><![CDATA[Bq/m^3]]></unit>
			<guid><![CDATA[G-CALC]]></guid>
			<evaluation-mode>AUTO</evaluation-mode>
			<entry type="expression"><equation><![CDATA[3]]></equation></entry>
		</component>
		<component name="Conc" type="general&#45;variable" dimension="1" index-lists="Crops">
			<id>Bio&#46;Conc</id><sub-system>Bio</sub-system>
			<available-objects>
				<available-object id="Bio&#46;Conc&#95;calc"/>
				<available-object id="Bio&#46;Conc&#95;par"/>
			</available-objects>
			<entry type="expression">
				<entry-unit><![CDATA[kg]]></entry-unit>
				<equation><![CDATA[Bio.Conc_par]]></equation>
			</entry>
		</component>
		<component name="Dose" type="expression" dimension="1" index-lists="Crops">
			<id>Bio&#46;Dose</id><sub-system>Bio</sub-system>
			<evaluation-mode>AUTO</evaluation-mode>
			<entry type="expression"><equation><![CDATA[Conc * 2]]></equation></entry>
		</component>
		<component name="Picked" type="general&#45;variable" dimension="1" index-lists="Crops">
			<id>Bio&#46;Picked</id><sub-system>Bio</sub-system>
			<unit><![CDATA[Bq/m^3]]></unit>
			<available-objects>
				<available-object id="Bio&#46;Conc&#95;calc"/>
			</available-objects>
			<entry type="expression">
				<entry-unit><![CDATA[Bq/m^3]]></entry-unit>
				<equation><![CDATA[Conc_calc]]></equation>
			</entry>
		</component>
		<component name="Deep soil" type="parameter" dimension="0">
			<id>Deep soil</id><unit><![CDATA[m]]></unit>
			<entry type="parameter"><value><![CDATA[4.0]]></value></entry>
		</component>
		<component name="Depth" type="general&#45;variable" dimension="0">
			<id>Depth</id>
			<available-objects><available-object id="Deep soil"/></available-objects>
			<entry type="expression"><equation><![CDATA[Deep soil]]></equation></entry>
		</component>
		<component name="Old" type="select" dimension="1" index-lists="Crops">
			<id>Old</id>
			<selected-object-guid guid="G-PAR"/>
			<available-object-guid guid="G-PAR"/>
			<available-object-guid guid="G-CALC"/>
		</component>
		<component name="Each" type="general&#45;variable" dimension="1" index-lists="Crops">
			<id>Bio&#46;Each</id><sub-system>Bio</sub-system>
			<available-objects>
				<available-object id="Bio&#46;Conc&#95;calc"/>
				<available-object id="Bio&#46;Conc&#95;par"/>
			</available-objects>
			<entry type="expression"><equation><![CDATA[Bio.Conc_calc]]></equation></entry>
			<entry type="expression" index="Wheat"><equation><![CDATA[Bio.Conc_par]]></equation></entry>
		</component>
		<component name="Unset" type="general&#45;variable" dimension="0">
			<id>Unset</id>
		</component>
	</block-model>
	<simulation-settings>
		<start-time>0.0</start-time><end-time>1.0</end-time><time-unit>year</time-unit>
		<java-solver>java&#45;ode45</java-solver>
	</simulation-settings>
</data-model>`;

// ---------------------------------------------------------------------------
// An assessment's stored runs (../src/io/ecoruns.js)

/**
 * A result file as Ecolego writes one: how many simulations and times, then a
 * block per output -- its GUID's low half, its high half, how many bytes
 * follow the 64-byte header -- and the numbers, all big-endian.
 *
 * @param {{simulations?: number, times: number, blocks: Array<{guid: string, values: number[]}>}} spec
 */
export function makeResultFile({ simulations = 1, times, blocks }) {
	const size = 1024 + blocks.reduce((n, b) => n + 64 + b.values.length * 8, 0);
	const bytes = new Uint8Array(size);
	const view = new DataView(bytes.buffer);
	view.setInt32(0, simulations, false);
	view.setInt32(4, times, false);
	let at = 1024;
	for (const b of blocks) {
		const hex = b.guid.replace(/-/g, '');
		for (let i = 0; i < 8; i++) {
			bytes[at + i] = parseInt(hex.slice(16 + 2 * i, 18 + 2 * i), 16);
			bytes[at + 8 + i] = parseInt(hex.slice(2 * i, 2 + 2 * i), 16);
		}
		view.setBigInt64(at + 16, BigInt(b.values.length * 8), false);
		at += 64;
		b.values.forEach((v, i) => view.setFloat64(at + i * 8, v, false));
		at += b.values.length * 8;
	}
	return bytes;
}

/**
 * The model the stored runs below are of: two lists, a compartment on both
 * draining into a second whose name has a space in it, the parameter that is
 * the rate, and an expression.
 */
export const STORED_MODEL_XML = `<?xml version="1.0" encoding="UTF-8"?>
<data-model>
	<project-properties name="Stored runs"/>
	<index-list-model>
		<index-list name="Nuclides"><id>Nuclides</id>
			<index name="Cs&#45;137" enabled="true"><id>Cs&#45;137</id></index>
			<index name="I&#45;129" enabled="true"><id>I&#45;129</id></index>
			<index name="Sr&#45;90" enabled="true"><id>Sr&#45;90</id></index>
		</index-list>
		<index-list name="Objects"><id>Objects</id>
			<index name="Lake" enabled="true"><id>Lake</id></index>
			<index name="Mire" enabled="true"><id>Mire</id></index>
		</index-list>
	</index-list-model>
	<block-model>
		<component name="Soil" type="compartment" dimension="2" index-lists="Nuclides,Objects">
			<id>Soil</id><unit>Bq</unit>
			<entry type="compartment"><initial-condition><![CDATA[1000]]></initial-condition></entry>
		</component>
		<component name="Deep layer" type="compartment" dimension="2" index-lists="Nuclides,Objects">
			<id>Deep layer</id><unit>Bq</unit>
			<entry type="compartment"><initial-condition><![CDATA[0]]></initial-condition></entry>
		</component>
		<connection name="Down" type="transfer&#45;coefficient" source="Soil" target="Deep layer"
		            dimension="2" index-lists="Nuclides,Objects">
			<id>Down</id>
			<entry type="transfer"><transfer-equation><![CDATA[k]]></transfer-equation></entry>
		</connection>
		<component name="k" type="parameter" dimension="0"><id>k</id><unit>1/year</unit>
			<entry type="parameter"><value>0.1</value></entry>
		</component>
		<component name="Dose" type="expression" dimension="0"><id>Dose</id><unit>Sv</unit>
			<entry type="expression"><equation><![CDATA[2*time]]></equation></entry>
		</component>
	</block-model>
	<simulation-settings>
		<start-time>0.0</start-time><end-time>10.0</end-time><time-unit>year</time-unit>
		<java-solver>java&#45;ode45</java-solver>
		<abs-error-tolerance>1.0E-6</abs-error-tolerance>
	</simulation-settings>
</data-model>`;

/** What the stored runs hold, worked out from the names so a test can say what it expects. */
export const STORED = {
	times: [0, 1, 10],
	nuclides: ['Cs-137', 'I-129', 'Sr-90'],
	objects: ['Lake', 'Mire'],
	soil: (n, o, ti) => (n === 2 && o === 1 && ti === 2 ? 1e-9 : 1000 + 100 * n + 10 * o + ti),
	deep: (n, o, ti) => 5 + n + o + ti,
	rate: 0.1,
	dose: (ti) => [0, 2, 20][ti],
};

const guidOf = (k) => `8BAF1D9C-F29F-11E6-9877-${k.toString(16).toUpperCase().padStart(12, '0')}`;
const xmlText = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/-/g, '&#45;');

/**
 * An assessment's files beside its model.xml: simulation.xml and the result
 * files of the runs, written as Ecolego `version` 6 or 5 writes them. Ecolego
 * 6: one file per run named by its GUID, the lists named once for the run, the
 * first index fastest, and a transfer stored as its flux. Ecolego 5: one run,
 * in results.dta, each output's own lists, the last index fastest, and a
 * transfer stored as its rate. Version 6 carries three runs: an archived one
 * dated later, the current one, and a probabilistic one -- and with
 * `stranger`, a fourth, current and newest, that saved only an output the
 * model does not have.
 *
 * The probabilistic run is `sims` realisations, realisation s being the single
 * run with every amount times s + 1 and the rate times s + 1 too -- so a
 * stored flux is `rate × amount` with both moving, and its rate is only got
 * back by dividing realisation by realisation. Ecolego 5 writes it as its one
 * run, `Probabilistic`, with the times in the first realisation's row only, as
 * Ecolego 5 does (`sampledFive`).
 */
export function storedRunFiles({ version = 6, stranger = false, sims = 2, sampledFive = false } = {}) {
	const S = STORED;
	const nt = S.times.length;
	const dims2 = [S.nuclides, S.objects];
	// Every cell of the two lists in the order the file stores them.
	const cells = [];
	if (version === 6) {
		for (let o = 0; o < S.objects.length; o++) for (let n = 0; n < S.nuclides.length; n++) cells.push([n, o]);
	} else {
		for (let n = 0; n < S.nuclides.length; n++) for (let o = 0; o < S.objects.length; o++) cells.push([n, o]);
	}
	const series2 = (f) => {
		const out = [];
		for (let ti = 0; ti < nt; ti++) for (const [n, o] of cells) out.push(f(n, o, ti));
		return out;
	};
	// Realisation `sim` of the run: the single run when it is 0 and there is
	// one, scaled as the doc above says otherwise.
	const rate = (sim) => S.rate * (sim + 1);
	const soil = (sim) => (n, o, ti) => S.soil(n, o, ti) * (sim + 1);
	const outputs = [
		// Spelt as the files spell it, which is not always as this tool does.
		{
			id: 'time', dims: [], td: true, unit: version === 6 ? 'year' : 'y', values: S.times,
			at: (sim) => (version === 5 && sim > 0 ? S.times.map(() => 0) : S.times),
		},
		{ id: 'Soil', dims: dims2, td: true, unit: 'Bq', values: series2(S.soil), at: (sim) => series2(soil(sim)) },
		{
			id: 'Deep layer', dims: dims2, td: true, unit: 'Bq', values: series2(S.deep),
			at: (sim) => series2((n, o, ti) => S.deep(n, o, ti) * (sim + 1)),
		},
		{
			id: 'Down', dims: dims2, td: true, unit: version === 6 ? 'Bq/year' : '1/year',
			values: series2((n, o, ti) => (version === 6 ? S.rate * S.soil(n, o, ti) : S.rate)),
			at: (sim) => series2((n, o, ti) => (version === 6 ? rate(sim) * soil(sim)(n, o, ti) : rate(sim))),
		},
		{ id: 'k', dims: [], td: false, unit: '1/year', values: [S.rate], at: (sim) => [rate(sim)] },
		{
			id: 'Dose', dims: [], td: true, unit: 'Sv', values: S.times.map((t, ti) => S.dose(ti)),
			at: (sim) => S.times.map((t, ti) => S.dose(ti) * (sim + 1)),
		},
		{ id: 'Gone', dims: [], td: true, unit: '', values: [1, 2, 3] },
	].map((o, k) => ({ ...o, guid: guidOf(k + 1) }));
	// What a run of some other model saved: the clock, and a block this one
	// has never had.
	const elsewhere = [
		outputs[0],
		{ id: 'Nowhere', dims: [], td: true, unit: 'Bq', values: S.times.map(() => 1), guid: guidOf(99) },
	];
	const listNames = (dims) => dims.map((d) => (d === S.nuclides ? 'Nuclides' : 'Objects'));
	const outputXml = (o) => {
		const lists = version === 6
			? ` index-lists="${listNames(o.dims).join('&#44;')}"`
			: '';
		const own = version === 6 ? ''
			: `<index-lists>${o.dims.map((d) => `<index-list>${d.map((i) => `<index>${xmlText(i)}</index>`).join('')}</index-list>`).join('')}</index-lists>`;
		return `<output-info id="${xmlText(o.id)}" type="SIMULATION" guid="${xmlText(o.guid)}"${lists}>`
			+ `<time-dependent>${o.td}</time-dependent>${own}`
			+ `<output-units><output-unit indices=""><![CDATA[${o.unit}]]></output-unit></output-units></output-info>`;
	};
	const listsXml = '<index-lists>'
		+ [['Nuclides', S.nuclides], ['Objects', S.objects]]
			.map(([name, idx]) => `<index-list name="${name}">${idx.map((i) => `<index>${xmlText(i)}</index>`).join('')}</index-list>`)
			.join('')
		+ '</index-lists>';
	const context = ({ guid, name, date, archived, type = 'DETERMINISTIC', saved = outputs }) => (version === 6
		? `<simulation-context guid="${xmlText(guid)}"${archived ? ' archive="true"' : ''}><simulation-info>`
			+ `<simulation-info-type>${type}</simulation-info-type><simulation-name>${xmlText(name)}</simulation-name>`
			+ `<date>${date}</date><start-time>0&#46;0</start-time><end-time>10&#46;0</end-time>`
			+ '<time-unit><![CDATA[Years]]></time-unit><abs-error-tolerance>1&#46;0E&#45;6</abs-error-tolerance>'
			+ `</simulation-info>${listsXml}<simulation-outputs>${saved.map(outputXml).join('')}</simulation-outputs>`
			+ '</simulation-context>'
		: `<simulation-context><simulation-info><simulation-info-type>${sampledFive ? 'Probabilistic' : 'Deterministic'}`
			+ `</simulation-info-type><simulation-name></simulation-name></simulation-info>`
			+ `<simulation-outputs>${outputs.map(outputXml).join('')}</simulation-outputs></simulation-context>`);
	// A single run is its values; a probabilistic one each realisation's after
	// the one before.
	const file = (simulations = 1, saved = outputs) => makeResultFile({
		simulations,
		times: nt,
		blocks: saved.map((o) => ({
			guid: o.guid,
			values: simulations === 1 ? o.values
				: Array.from({ length: simulations }, (_, sim) => (o.at ? o.at(sim) : o.values)).flat(),
		})),
	});
	const runs = version === 6
		? [
			{ guid: 'A0000000-0000-0000-0000-000000000001', name: 'Older', date: 2000, archived: true },
			{ guid: 'A0000000-0000-0000-0000-000000000002', name: 'Now', date: 1000, archived: false },
			{ guid: 'A0000000-0000-0000-0000-000000000003', name: 'Sampled', date: 3000, type: 'PROBABILISTIC', sims },
			...(stranger
				? [{ guid: 'A0000000-0000-0000-0000-000000000004', name: 'Elsewhere', date: 4000, archived: false, saved: elsewhere }]
				: []),
		]
		: [{}];
	const xml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><simulation-model>`
		+ `${runs.map(context).join('')}</simulation-model>`;
	return [
		{ name: 'simulation.xml', text: xml },
		...(version === 6
			? [
				...runs.map((r) => ({ name: `simulation/results/${r.guid}.dta`, bytes: file(r.sims ?? 1, r.saved) })),
				// The empty file Ecolego 6 leaves beside them.
				{ name: 'simulation/results/results.dta', bytes: new Uint8Array(1024) },
			]
			: [{ name: 'simulation\\results\\results.dta', bytes: file(sampledFive ? sims : 1) }]),
	];
}
