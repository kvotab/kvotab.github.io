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
		const raw = enc.encode(f.text);
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

const YEAR_S = 365.25 * 24 * 3600;

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
			<half-life>${2.552 / 60 / 60 / 24 / 365.25 * YEAR_S}</half-life>
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
		<java-solver>ODE15S</java-solver>
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
		<java-solver>ODE45</java-solver>
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
		<java-solver>ODE45</java-solver>
		<rel-error-tolerance>1.0E-8</rel-error-tolerance>
		<abs-error-tolerance>1.0E-12</abs-error-tolerance>
	</simulation-settings>
</data-model>`;
