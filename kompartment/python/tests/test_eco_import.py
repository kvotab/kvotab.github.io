"""The Ecolego importer against the application's: the same file, the same model,
the same report.

Every test here imports a file with the application's own importer
(``src/io/eco.js``, run by ``tests/node/eco_import.mjs``) and with
:mod:`kompartment.importers.eco`, and compares the two as JSON text, key order
included: the project, the report's lists and counts, its summary, and -- for a
file neither can read -- the error and its message.

The files are the application's hand-written synthetic fixture
(``test/eco-fixture.js``, no real project data) and variants of it: every
variant the application's own tests use, and more made up here to reach the
corners -- missing attributes, sub-systems, index lists, distributions, lookups,
recorders, events, archives, and the places where JavaScript itself decides the
answer.
"""

from __future__ import annotations

import base64
import json
import random
import re
import struct
import subprocess
import unittest
import zlib
from functools import lru_cache
from typing import Any, Dict, List, NamedTuple, Optional
from xml.sax.saxutils import escape, quoteattr

from helpers import HERE, NODE, SRC, differences, needs_app

import kompartment as kp
from kompartment.importers import _eco_maps as maps
from kompartment.importers._xml import XMLError, parse_xml
from kompartment.importers.eco import (
    EcoImportError, decode_xml_bytes, import_eco_file, import_model_xml,
)
from kompartment.jsonio import dumps


def _node(requests: List[Dict[str, Any]]) -> List[Any]:
    """Asks the application's importer (see tests/node/eco_import.mjs)."""
    assert NODE is not None
    proc = subprocess.run([NODE, str(HERE / 'node' / 'eco_import.mjs'), str(SRC)],
                          input=json.dumps({'task': 'batch', 'requests': requests}),
                          capture_output=True, text=True, timeout=600, encoding='utf-8')
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return json.loads(proc.stdout)


@lru_cache(maxsize=1)
def fixtures() -> Dict[str, str]:
    """The texts test/eco-fixture.js exports."""
    return _node([{'task': 'fixtures'}])[0]


def fx(name: str) -> str:
    return fixtures()[name]


def replace(text: str, old: str, new: str) -> str:
    """``text.replace(old, new)`` as JavaScript does it with a string: the first
    occurrence only. Refuses a replacement that would change nothing, so a
    variant cannot quietly be the fixture itself."""
    assert old in text, f'{old!r} is not in the text'
    return text.replace(old, new, 1)


class Case(NamedTuple):
    label: str
    kind: str  # 'xml' (text) or 'file' (bytes)
    payload: Any
    file_name: Optional[str] = None
    version: Optional[str] = None


def xml(label: str, text: str, file_name: Optional[str] = None, version: Optional[str] = None) -> Case:
    return Case(label, 'xml', text, file_name, version)


def file(label: str, data: bytes, file_name: Optional[str] = None, version: Optional[str] = None) -> Case:
    return Case(label, 'file', data, file_name, version)


def request(case: Case) -> Dict[str, Any]:
    out: Dict[str, Any] = {'task': case.kind}
    if case.kind == 'xml':
        out['text'] = case.payload
    else:
        out['base64'] = base64.b64encode(case.payload).decode('ascii')
    if case.file_name is not None:
        out['fileName'] = case.file_name
    if case.version is not None:
        out['version'] = case.version
    return out


def python(case: Case) -> Dict[str, Any]:
    """The Python import, in the shape the harness writes the JavaScript one."""
    try:
        if case.kind == 'xml':
            result = import_model_xml(case.payload, file_name=case.file_name, version=case.version)
        else:
            result = import_eco_file(case.payload, file_name=case.file_name, version=case.version)
    except EcoImportError as e:
        return {'error': {'name': 'ImportError', 'message': str(e)}}
    except ValueError as e:
        # `new Date(...).toISOString()` out of range: a RangeError there.
        return {'error': {'name': 'RangeError', 'message': str(e)}}
    return {'project': json.loads(dumps(result.project)), 'report': result.report.to_dict()}


class ParityCase(unittest.TestCase):
    """Imports each case both ways and compares."""

    maxDiff = None

    def assertSameImports(self, cases: List[Case]) -> List[Dict[str, Any]]:
        labels = [c.label for c in cases]
        self.assertEqual(len(labels), len(set(labels)), 'two cases share a label')
        answers = _node([request(c) for c in cases])
        for case, js in zip(cases, answers):
            with self.subTest(case=case.label):
                py = python(case)
                self.assertEqual(differences(py, js), [])
                self.assertEqual(dumps(py), dumps(js))
        return answers


# --- the variants the application's own tests use (test/run.js) ----------------------------

def with_saturation(value: Optional[str]) -> str:
    if value is None:
        return fx('MODEL_XML')
    return replace(fx('MODEL_XML'), '<simulation-settings>',
                   f'<simulation-settings>\n\t\t<saturation-enabled>{value}</saturation-enabled>')


def settings(inner: str) -> str:
    return replace(fx('MODEL_XML'), '<simulation-type>DETERMINISTIC</simulation-type>',
                   f'<simulation-type>DETERMINISTIC</simulation-type>{inner}')


AUTO = '&#45;7&#46;92842341234234E11'

ENDPOINTS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<data-model>
	<project-properties name="ep"/>
	<block-model>
		<component name="Lake" type="compartment"><id>NearField&#46;Lake</id>
			<sub-system>NearField</sub-system>
			<entry type="compartment"><initial-condition><![CDATA[1]]></initial-condition></entry>
		</component>
		<component name="k leach" type="parameter"><id>k&#32;id</id>
			<entry type="parameter"><value>0.5</value></entry>
		</component>
	</block-model>
	<simulation-settings>
		<start-time>0</start-time><end-time>10</end-time>
		<time-unit>year</time-unit><solver>ODE15S</solver>
		<outputs>
			<output id="NearField&#46;Lake"/>
			<output id="NearField&#46;Lake"/>
			<output id="k&#32;id"/>
			<output id="gone&#46;Ghost"/>
		</outputs>
	</simulation-settings>
</data-model>"""


def described(props: str, extra: str = '') -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<data-model>
	{props}
	<index-list-model>
		<index-list name="Radionuclides"><id>il</id>
			<index name="Cs-137" enabled="true"><id>i1</id></index>
			<index name="H-3" enabled="true"><id>i2</id></index>
			<index name="Sr-90" enabled="false"><id>i3</id></index>
		</index-list>
	</index-list-model>
	<block-model>
		<component name="Lake" type="compartment" index-lists="il">
			<id>b1</id><unit>Bq</unit>
			<entry type="compartment"><initial-condition><![CDATA[1]]></initial-condition></entry>
		</component>
		<component name="Mire" type="compartment">
			<id>b2</id><unit>Bq</unit>
			<entry type="compartment"><initial-condition><![CDATA[0]]></initial-condition></entry>
		</component>
		<component name="k" type="parameter">
			<id>b3</id><entry type="parameter"><value>0.1</value></entry>
		</component>
	</block-model>
	<simulation-settings>
		<start-time>0</start-time><end-time>1000</end-time>
		<time-unit>year</time-unit><solver>ODE15S</solver>
	</simulation-settings>
	{extra}
</data-model>"""


REAL_PROPS = """<project-properties name="model">
		<guid><![CDATA[7CE02604]]></guid>
		<modification-date>1621966224401</modification-date>
		<property name="author" type="string"><![CDATA[a.modeller]]></property>
		<property name="comment" type="string"><![CDATA[Created at Tue May 25 17:41:51 UTC 2021]]></property>
	</project-properties>"""

SAID_PROPS = """<project-properties name="Landscape 2075">
		<property name="comment" type="string"><![CDATA[Base case, revision 12]]></property>
		<modification-date>1621966224401</modification-date>
	</project-properties>"""


def wide_description() -> str:
    many = ''.join(f'<index-list name="L{i}"><id>x{i}</id><index name="a" enabled="true"><id>xi{i}</id>'
                   '</index></index-list>' for i in range(9))
    text = described('<project-properties name="w"/>')
    text = replace(text, '</index-list-model>', f'{many}</index-list-model>')
    return replace(text, 'index-lists="il"', 'index-lists="il,' + ','.join(f'x{i}' for i in range(9)) + '"')


def intersection(dim: str = '1', lists: str = '', source_list: str = 'il-mat', target_list: str = 'il-rn') -> str:
    return f"""
		<data-model>
		<project-properties name="Intersection"/>
		<index-list-model>
			<index-list name="Contaminants"><id>il-mat</id>
				<property name="predefined-type" type="class se.facilia.ecolego.domain.EcolegoIndexList$PredefinedType">MATERIALS</property>
				<index name="C-14" enabled="true"><id>ix-c</id></index>
				<index name="I-129" enabled="true"><id>ix-i</id></index>
			</index-list>
			<index-list name="Radionuclides"><id>il-rn</id>
				<property name="predefined-type" type="class se.facilia.ecolego.domain.EcolegoIndexList$PredefinedType">RADIONUCLIDES</property>
				<index name="C-14" enabled="true"><id>ix-rn-c</id></index>
				<index name="I-129" enabled="true"><id>ix-rn-i</id></index>
				<sub-set of="il-mat"/>
			</index-list>
			<index-list name="Objects"><id>il-obj</id>
				<index name="Lake" enabled="true"><id>ix-lake</id></index>
			</index-list>
		</index-list-model>
		<material-model>
			<nuclide name="C-14"><id>C-14</id><unit>Bq</unit><half-life>1.8e11</half-life></nuclide>
			<nuclide name="I-129"><id>I-129</id><unit>Bq</unit><half-life>4.955e14</half-life></nuclide>
		</material-model>
		<simulation-settings>
			<start-time>0</start-time><end-time>1</end-time>
			<number-of-output-points>2</number-of-output-points><time-unit>year</time-unit>
		</simulation-settings>
		<block-model>
			<component name="A" type="compartment" dimension="1" index-lists="{source_list}">
				<id>blk-a</id><unit>Bq</unit>
				<entry type="compartment"><initial-condition><![CDATA[1]]></initial-condition></entry>
			</component>
			<component name="B" type="compartment" dimension="1" index-lists="{target_list}">
				<id>blk-b</id><unit>Bq</unit>
				<entry type="compartment"><initial-condition><![CDATA[0]]></initial-condition></entry>
			</component>
			<connection name="flow" type="transfer" source="blk-a" target="blk-b"
			            dimension="{dim}" index-lists="{lists}">
				<id>blk-flow</id>
				<entry type="transfer">
					<transfer-equation><![CDATA[0.25]]></transfer-equation>
					<multiply-with-donor><![CDATA[true]]></multiply-with-donor>
				</entry>
			</connection>
		</block-model>
		</data-model>"""


def interface(wired: bool = True, sources: Optional[List[str]] = None, op: Optional[str] = None,
              target: str = 'blk-in', kind: str = 'expression', off: bool = False) -> str:
    sources = sources or ['blk-out']
    if kind == 'transfer':
        fed = """<connection name="taken" type="transfer" source="blk-a" target="blk-b" index-lists="il-mat">
				<id>blk-in</id><guid><![CDATA[G-IN]]></guid>
				<sub-system>ss-bio</sub-system>
				<entry type="transfer"><transfer-equation><![CDATA[0.0]]></transfer-equation></entry>
				<entry type="transfer" index="ix-i"><transfer-equation><![CDATA[42]]></transfer-equation></entry>
			</connection>"""
    else:
        zero = '<value><![CDATA[0.0]]></value>' if kind == 'parameter' else '<equation><![CDATA[0.0]]></equation>'
        many = '<value><![CDATA[42]]></value>' if kind == 'parameter' else '<equation><![CDATA[42]]></equation>'
        fed = f"""<component name="taken" type="{kind}" index-lists="il-mat">
				<id>blk-in</id><guid><![CDATA[G-IN]]></guid>
				<sub-system>ss-bio</sub-system>
				<entry type="{kind}">{zero}</entry>
				<entry type="{kind}" index="ix-i">{many}</entry>
			</component>"""
    operation = f' operation="{op}"' if op else ''
    connections = ''.join(
        f'<model-connection source="{"G-OUT" if s == "blk-out" else "G-OUT2"}" '
        f'target="{"G-IN" if target == "blk-in" else target}"/>' for s in sources)
    wire = (f"""<connection name="wire" type="connector" source="blk-mo" target="blk-mi">
				<id>blk-conn</id><guid><![CDATA[G-CONN]]></guid>{'<enabled>false</enabled>' if off else ''}
				<sub-system>ss-near</sub-system>
				{connections}
			</connection>""" if wired else '')
    return f"""
		<data-model>
		<project-properties name="Interface test"/>
		<index-list-model>
			<index-list name="Contaminants"><id>il-mat</id>
				<index name="I-129" enabled="true"><id>ix-i</id></index>
			</index-list>
		</index-list-model>
		<material-model>
			<nuclide name="I-129"><id>I-129</id><unit>Bq</unit>
				<half-life>4.955e14</half-life></nuclide>
		</material-model>
		<hierarchy-model>
			<sub-system-block name="Near"><id>ss-near</id></sub-system-block>
			<sub-system-block name="Bio"><id>ss-bio</id></sub-system-block>
		</hierarchy-model>
		<block-model>
			<component name="release" type="expression">
				<id>blk-out</id><guid><![CDATA[G-OUT]]></guid>
				<sub-system>ss-near</sub-system>
				<entry type="expression"><equation><![CDATA[7]]></equation></entry>
			</component>
			<component name="other" type="expression">
				<id>blk-out2</id><guid><![CDATA[G-OUT2]]></guid>
				<sub-system>ss-near</sub-system>
				<entry type="expression"><equation><![CDATA[5]]></equation></entry>
			</component>
			<component name="Output" type="model-output">
				<id>blk-mo</id><guid><![CDATA[G-MO]]></guid>
				<sub-system>ss-near</sub-system>
				<interface-object guid="G-OUT" allow-auto-connection="true"/>
				<interface-object guid="G-OUT2" allow-auto-connection="true"/>
			</component>
			<component name="A" type="compartment"><id>blk-a</id>
				<sub-system>ss-bio</sub-system><unit>Bq</unit>
				<entry type="compartment"><initial-condition><![CDATA[1]]></initial-condition></entry>
			</component>
			<component name="B" type="compartment"><id>blk-b</id>
				<sub-system>ss-bio</sub-system><unit>Bq</unit>
				<entry type="compartment"><initial-condition><![CDATA[0]]></initial-condition></entry>
			</component>
			{fed}
			<component name="Input" type="model-input">
				<id>blk-mi</id><guid><![CDATA[G-MI]]></guid>
				<sub-system>ss-bio</sub-system>
				<interface-object guid="G-IN" allow-auto-connection="true"{operation}/>
			</component>
			{wire}
		</block-model>
		</data-model>"""


REACHES_XML = """
		<data-model>
		<project-properties name="Reaches"/>
		<index-list-model>
			<index-list name="Contaminants"><id>il-mat</id>
				<index name="I-129" enabled="true"><id>ix-i</id></index>
			</index-list>
		</index-list-model>
		<material-model>
			<nuclide name="I-129"><id>I-129</id><unit>Bq</unit>
				<half-life>4.955e14</half-life></nuclide>
		</material-model>
		<hierarchy-model>
			<sub-system-block name="Near"><id>ss-near</id></sub-system-block>
			<sub-system-block name="Bio"><id>ss-bio</id></sub-system-block>
		</hierarchy-model>
		<simulation-settings>
			<start-time>0</start-time><end-time>10</end-time>
			<number-of-output-points>11</number-of-output-points>
			<time-unit>year</time-unit>
		</simulation-settings>
		<block-model>
			<component name="release" type="expression">
				<id>blk-out</id><guid><![CDATA[G-OUT]]></guid>
				<sub-system>ss-near</sub-system>
				<entry type="expression"><equation><![CDATA[3]]></equation></entry>
			</component>
			<component name="Output" type="model-output">
				<id>blk-mo</id><guid><![CDATA[G-MO]]></guid>
				<sub-system>ss-near</sub-system>
				<interface-object guid="G-OUT"/>
			</component>
			<component name="inflow" type="expression">
				<id>blk-in</id><guid><![CDATA[G-IN]]></guid>
				<sub-system>ss-bio</sub-system>
				<entry type="expression"><equation><![CDATA[0.0]]></equation></entry>
			</component>
			<component name="Input" type="model-input">
				<id>blk-mi</id><guid><![CDATA[G-MI]]></guid>
				<sub-system>ss-bio</sub-system>
				<interface-object guid="G-IN" operation="ADD"/>
			</component>
			<component name="Pool" type="compartment">
				<id>blk-pool</id><guid><![CDATA[G-POOL]]></guid>
				<sub-system>ss-bio</sub-system>
				<unit>Bq</unit>
				<entry type="compartment"><initial-condition><![CDATA[0]]></initial-condition></entry>
			</component>
			<component name="Outside" type="inflow"><id>blk-bnd</id>
				<sub-system>ss-bio</sub-system>
			</component>
			<connection name="feed" type="transfer" source="blk-bnd" target="blk-pool">
				<id>blk-src</id><guid><![CDATA[G-SRC]]></guid>
				<sub-system>ss-bio</sub-system>
				<entry type="transfer"><transfer-equation><![CDATA[inflow]]></transfer-equation></entry>
			</connection>
			<connection name="wire" type="connector" source="blk-mo" target="blk-mi">
				<id>blk-conn</id><guid><![CDATA[G-CONN]]></guid>
				<sub-system>ss-near</sub-system>
				<model-connection source="G-OUT" target="G-IN"/>
			</connection>
		</block-model>
		</data-model>"""

PREDEFINED = ('<property name="predefined-type" '
              'type="class se.facilia.ecolego.domain.EcolegoIndexList$PredefinedType">{}</property>')


def material_lists(props: bool = True, radionuclides: Optional[List[str]] = None) -> str:
    radionuclides = ['Cs-137'] if radionuclides is None else radionuclides
    members = ''.join(f'<index name="{n}" enabled="true"><id>i-rn-{n}</id></index>' for n in radionuclides)
    return f"""
		<data-model>
		<project-properties name="Material test"/>
		<material-model>
			<nuclide name="Cs-137"><id>Cs-137</id><unit>Bq</unit>
				<half-life>9.5e8</half-life></nuclide>
			<material name="Carbon_12"><id>Carbon_12</id><unit>kgC</unit></material>
		</material-model>
		<index-list-model>
			<index-list name="Contaminants">
				<id>il-mat</id>
				{PREDEFINED.format('MATERIALS') if props else ''}
				<index name="Cs-137" enabled="true"><id>i-cs</id></index>
				<index name="Carbon_12" enabled="true"><id>i-c12</id></index>
			</index-list>
			<index-list name="Radionuclides">
				<id>il-rn</id>
				{PREDEFINED.format('RADIONUCLIDES') if props else ''}
				{members}
				<sub-set of="il-mat"/>
			</index-list>
		</index-list-model>
		<compartment-model/>
		</data-model>"""


def scenario_lists(props: str, name: str = 'Scenarios') -> str:
    return f"""
		<data-model>
		<project-properties name="Scenario test"/>
		<index-list-model>
			<index-list name="Contaminants">
				<id>il-mat</id>
				<index name="Cs-137" enabled="true"><id>ix-cs</id></index>
			</index-list>
			<index-list name="{name}">
				<id>il-sc</id>
				{props}
				<index name="Base" enabled="true"><id>ix-base</id></index>
				<index name="Wet" enabled="true"><id>ix-wet</id></index>
			</index-list>
			<index-list name="Elements">
				<id>il-el</id>
				<index name="Cs" enabled="true"><id>ix-el-cs</id></index>
			</index-list>
		</index-list-model>
		<compartment-model/>
		</data-model>"""


DECLARED_SCENARIOS = f"""
		<data-model>
		<project-properties name="Declared"/>
		<index-list-model>
			<index-list name="Cases">
				<id>il-c</id>
				{PREDEFINED.format('SCENARIOS')}
				<index name="A" enabled="true"><id>ix-a</id></index>
			</index-list>
			<index-list name="Scenarios">
				<id>il-s</id>
				<index name="B" enabled="true"><id>ix-b</id></index>
			</index-list>
		</index-list-model>
		<compartment-model/>
		</data-model>"""


def io_model(blocks: str, extra: str = '') -> str:
    return f'<data-model>{extra}<block-model>{blocks}</block-model></data-model>'


def io_expr(name: str, bid: str, eq: str) -> str:
    return (f'<component type="expression" name="{name}" dimension="0" index-lists="">'
            f'<id>{bid}</id><entry type="expression"><equation>{eq}</equation></entry></component>')


def io_list(name: str, *indices: str) -> str:
    return (f'<index-list-model><index-list name="{name}"><id>L1</id>'
            + ''.join(f'<index name="{n}"><id>i{k + 1}</id></index>' for k, n in enumerate(indices))
            + '</index-list></index-list-model>')


def nuclides(name: str) -> str:
    return ('<material-model><nuclide name="Cs-137"><id>n1</id><half-life>9.49e8</half-life></nuclide>'
            f'<nuclide name="{name}"><id>n2</id><half-life>3.15e7</half-life></nuclide></material-model>')


EMPTY_TIMES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<data-model>
	<project-properties name="t"/>
	<block-model><component name="A" type="compartment"><id>a</id>
		<entry type="compartment"><initial-condition><![CDATA[1]]></initial-condition></entry>
	</component></block-model>
	<simulation-settings>
		<start-time>2000</start-time><end-time>102000</end-time>
		<output-options>Produce specified output only</output-options>
		<time-series-list><time-series type="custom">
			<values>&#91;2000&#46;0&#44;&#32;3000&#46;0&#93;</values>
		</time-series></time-series-list>
		<discrete-times><time-series type="custom"><values>&#91;&#93;</values></time-series></discrete-times>
	</simulation-settings>
</data-model>"""


def run_js_cases() -> List[Case]:
    """Every variant of the synthetic model the application's tests import."""
    model = fx('MODEL_XML')
    cases = [
        xml('fixture', model),
        xml('fixture, named by a file', model, file_name='projects/Test import.eco'),
        xml('fixture, with a version', model, file_name='C:\\work\\x.eas', version='6.5'),
        xml('real shapes', fx('REAL_SHAPES_XML')),
        xml('transport', fx('TRANSPORT_XML')),
        # an imported model brings its saturation switch with it
        xml('saturation false', with_saturation('false')),
        xml('saturation true', with_saturation('true')),
        xml('saturation in CDATA', replace(model, '<simulation-settings>',
                                           '<simulation-settings>\n\t\t<saturation-enabled><![CDATA[false]]>'
                                           '</saturation-enabled>')),
        # a model brings its own probabilistic settings
        xml('probabilistic settings', replace(
            model, '</data-model>',
            '<probabilistic-settings><no-simulations>250</no-simulations>'
            '<sampling><![CDATA[Latin Hypercube]]></sampling><seed>-99</seed>'
            '</probabilistic-settings></data-model>')),
        # endpoints
        xml('endpoints', ENDPOINTS_XML, file_name='ep.eco'),
        # an imported model arrives knowing what it is
        xml('described', described(REAL_PROPS), file_name='Vault_assessment.eas', version='6.5'),
        xml('described by its author', described(SAID_PROPS), file_name='lobj.eas'),
        xml('described with nothing', described('<project-properties name="model"/>')),
        xml('described wide', wide_description()),
        # the unit its nuclides were in
        xml('nuclides in moles', replace(replace(model, '<z>55</z>', '<unit><![CDATA[mol]]></unit><z>55</z>'),
                                         '<z>56</z>', '<unit><![CDATA[Mole]]></unit><z>56</z>')),
        xml('nuclides that disagree', replace(replace(model, '<z>55</z>', '<unit><![CDATA[Bq]]></unit><z>55</z>'),
                                              '<z>56</z>', '<unit><![CDATA[mol]]></unit><z>56</z>')),
        # a transfer written over the indices its two ends share
        xml('intersection materials to nuclides', intersection()),
        xml('intersection nuclides to materials', intersection(source_list='il-rn', target_list='il-mat')),
        xml('intersection named', intersection(lists='il-rn')),
        xml('intersection scalar', intersection(dim='0')),
        xml('intersection overlapping', intersection(target_list='il-obj')),
        # sub-system interfaces
        xml('interface switched off', interface(off=True)),
        xml('interface one source', interface()),
        xml('interface ADD', interface(sources=['blk-out', 'blk-out2'], op='ADD')),
        xml('interface MAX', interface(sources=['blk-out', 'blk-out2'], op='MAX')),
        xml('interface no operation', interface(sources=['blk-out', 'blk-out2'])),
        xml('interface into a transfer', interface(kind='transfer')),
        xml('interface into a parameter', interface(kind='parameter')),
        xml('interface unwired', interface(wired=False)),
        xml('interface to nowhere', interface(target='G-NOWHERE')),
        xml('interface end to end', REACHES_XML),
        # Ecolego's three material lists
        xml('material lists marked', material_lists(True)),
        xml('material lists unmarked', material_lists(False)),
        xml('material lists, radionuclides empty', material_lists(True, [])),
        # how the file says results should be saved
        xml('output solver', settings('<output-options>Produce no additional output</output-options>')),
        xml('output 0', settings('<output-options>0</output-options>')),
        xml('output 2', settings('<output-options>2</output-options>')),
        xml('output listed', settings("""
		<output-options>Produce specified output only</output-options>
		<time-series-list>
			<time-series type="geometric">
				<time-series-start-time>1.0</time-series-start-time>
				<time-series-end-time>1000.0</time-series-end-time>
				<n>7</n>
			</time-series>
			<time-series type="linear">
				<time-series-start-time>0.0</time-series-start-time>
				<time-series-end-time>1.0</time-series-end-time>
				<n>11</n>
			</time-series>
		</time-series-list>
		<discrete-times>
			<time-series type="custom">
				<values>[0.25, 0.75, 500.0]</values>
			</time-series>
		</discrete-times>""")),
        xml('output stepped', settings("""
		<output-options>Produce specified output only</output-options>
		<time-series-list>
			<time-series type="linear-increment">
				<time-series-start-time>0.0</time-series-start-time>
				<time-series-end-time>100.0</time-series-end-time>
				<increment>25.0</increment>
			</time-series>
		</time-series-list>""")),
        xml('output ragged', settings("""
		<output-options>Produce specified output only</output-options>
		<time-series-list>
			<time-series type="linear-increment">
				<time-series-start-time>0.0</time-series-start-time>
				<time-series-end-time>100.0</time-series-end-time>
				<increment>30.0</increment>
			</time-series>
		</time-series-list>""")),
        xml('output both', settings("""
		<output-options>Produce additional output</output-options>
		<time-series-list>
			<time-series type="linear">
				<time-series-start-time>0.0</time-series-start-time>
				<time-series-end-time>1000.0</time-series-end-time>
				<n>11</n>
			</time-series>
		</time-series-list>""")),
        xml('output batched', settings("""
		<output-options>Produce no additional output</output-options>
		<batch-mode>true</batch-mode>
		<time-series-list>
			<time-series type="linear">
				<time-series-start-time>0.0</time-series-start-time>
				<time-series-end-time>1000.0</time-series-end-time>
				<n>11</n>
			</time-series>
		</time-series-list>""")),
        xml('output specified, none listed', settings(
            '<output-options>Produce specified output only</output-options>')),
        # a series whose ends are Ecolego's AUTO
        xml('AUTO both ends', settings(f"""
		<output-options>Produce specified output only</output-options>
		<time-series-list>
			<time-series type="linear">
				<time-series-start-time>{AUTO}</time-series-start-time>
				<time-series-end-time>{AUTO}</time-series-end-time>
				<n>11</n>
			</time-series>
		</time-series-list>""")),
        xml('AUTO one end', settings(f"""
		<output-options>Produce specified output only</output-options>
		<time-series-list>
			<time-series type="geometric">
				<time-series-start-time>1.0</time-series-start-time>
				<time-series-end-time>{AUTO}</time-series-end-time>
				<n>4</n>
			</time-series>
		</time-series-list>""")),
        xml('AUTO stepped', settings(f"""
		<output-options>Produce specified output only</output-options>
		<time-series-list>
			<time-series type="linear-increment">
				<time-series-start-time>{AUTO}</time-series-start-time>
				<time-series-end-time>{AUTO}</time-series-end-time>
				<increment>100.0</increment>
			</time-series>
		</time-series-list>""")),
        # a compartment's own absolute tolerance
        xml('abs-tol', replace(replace(
            model, '<lower-saturation>0</lower-saturation>',
            '<abs-tol><![CDATA[1e-4]]></abs-tol><lower-saturation>0</lower-saturation>'),
            '<initial-condition><![CDATA[1.0e10]]></initial-condition>',
            '<initial-condition><![CDATA[1.0e10]]></initial-condition><abs-tol><![CDATA[1e-11]]></abs-tol>')),
        xml('abs-tol infinite', replace(model, '<lower-saturation>0</lower-saturation>',
                                        '<abs-tol><![CDATA[Infinity]]></abs-tol><lower-saturation>0</lower-saturation>')),
        xml('RADAU5', replace(model, '<java-solver>ODE15S</java-solver>', '<java-solver>RADAU5</java-solver>')),
        # a compartment's saturation band
        xml('negative floor', replace(model, '<lower-saturation>0</lower-saturation>',
                                      '<lower-saturation>-1e30</lower-saturation>')),
        xml('ceiling', replace(model, '<upper-saturation></upper-saturation>',
                               '<upper-saturation>500</upper-saturation>')),
        xml('positive floor', replace(model, '<lower-saturation>0</lower-saturation>',
                                      '<lower-saturation>10</lower-saturation>')),
        # an imported Scenarios list
        xml('scenarios marked', scenario_lists(PREDEFINED.format('SCENARIOS'))),
        xml('scenarios title case', scenario_lists(PREDEFINED.format('Scenarios'))),
        xml('scenarios as Cases', scenario_lists(PREDEFINED.format('Scenarios'), 'Cases')),
        xml('elements as Cases', scenario_lists(PREDEFINED.format('Elements'), 'Cases')),
        xml('scenarios by name', scenario_lists('')),
        xml('scenarios declared', DECLARED_SCENARIOS),
        # switched off
        xml('a block switched off', replace(
            model, '<component name="Total" type="expression" index-lists="il-obj">',
            '<component name="Total" type="expression" index-lists="il-obj"><enabled>false</enabled>')),
        xml('a sub-system switched off', replace(replace(replace(
            model, '<block-model>',
            '<hierarchy-model>'
            '<sub-system-block name="NF" type="subsystem"><id>NF</id><enabled>false</enabled></sub-system-block>'
            '<sub-system-block name="FF" type="subsystem"><id>FF</id></sub-system-block>'
            '</hierarchy-model><block-model>'),
            '<component name="Total" type="expression" index-lists="il-obj">',
            '<component name="Total" type="expression" index-lists="il-obj"><sub-system>NF</sub-system>'),
            '<component name="k leach" type="parameter" index-lists="il-obj">',
            '<component name="k leach" type="parameter" index-lists="il-obj"><sub-system>FF</sub-system>')),
        # a saved time outside the run
        xml('empty discrete times', EMPTY_TIMES_XML),
        # the explicit dy/dt term
        xml('dydt', replace(replace(
            model, '<upper-saturation></upper-saturation>',
            '<upper-saturation></upper-saturation><differential-equation><![CDATA[-0.01*Soil]]>'
            '</differential-equation>'),
            '<initial-condition><![CDATA[1.0e10]]></initial-condition>',
            '<initial-condition><![CDATA[1.0e10]]></initial-condition>'
            '<differential-equation><![CDATA[-0.02*Soil]]></differential-equation>')),
        xml('dydt empty', replace(model, '<upper-saturation></upper-saturation>',
                                  '<upper-saturation></upper-saturation><differential-equation><![CDATA[]]>'
                                  '</differential-equation>')),
        # functions
        xml('expression with arguments', replace(
            model, '\t\t<component name="Total" type="expression" index-lists="il-obj">\n',
            '\t\t<component name="Total" type="expression" index-lists="il-obj">\n'
            '<argument><argument-key>x</argument-key><argument-name>x</argument-name></argument>'
            '<argument><argument-key>y</argument-key><argument-name>y</argument-name></argument>')),
        xml('compiled function', replace(
            model, '\t<index-list-model>',
            '\t<function-model>'
            '<function name="TR_adv" source-file-name="TR_adv.java" source-type="JAVA">'
            '<function-metadata key="TR_adv" name="TR_adv">'
            '<function-description><![CDATA[advective transfer]]></function-description>'
            '<parameter-metadata key="LAI" name="LAI"></parameter-metadata>'
            '<parameter-metadata key="leaf width" name="leaf width"></parameter-metadata>'
            '</function-metadata></function></function-model>\n\t<index-list-model>')),
    ]
    return cases


def run_js_name_cases() -> List[Case]:
    """The application's tests of names out of the file."""
    return [
        xml('an empty name', io_model(io_expr('', 'E1', '1') + io_expr('Other', 'E2', '(a) + (b)'))),
        xml('a blank list name', io_model(io_expr('x', 'X', '1'), io_list('  ', 'a'))),
        xml('a name of one space', io_model(io_expr(' ', 'E1', '1') + io_expr('a', 'A', '1') + io_expr('b', 'B', '2')
                                            + io_expr('Other', 'E2', '(a) + (b)'))),
        xml('an operator in a name', io_model(io_expr('A-B', 'E1', '1') + io_expr('A', 'A', '1')
                                              + io_expr('B', 'B', '2') + io_expr('Deep soil', 'D', '3')
                                              + io_expr('Diff', 'E2', 'A-B + Deep soil'))),
        xml('a function name', io_model(io_expr('min', 'E1', '1') + io_expr('Other', 'E2', 'min * 2'))),
        xml('a block called __proto__', io_model(io_expr('__proto__', 'E1', '1'))),
        xml('a block called constructor', io_model(io_expr('constructor', 'E1', '1'))),
        xml('a block called prototype', io_model(io_expr('prototype', 'E1', '1'))),
        xml('a nuclide called __proto__', io_model(io_expr('x', 'X', '1'), nuclides('__proto__'))),
        xml('a material called constructor', io_model(
            io_expr('x', 'X', '1'), '<material-model><material name="constructor"><id>m1</id></material></material-model>')),
        xml('an index called prototype', io_model(io_expr('x', 'X', '1'), io_list('L', 'a', 'prototype'))),
        xml('a blank index', io_model(io_expr('x', 'X', '1'), io_list('L', 'a', '  '))),
        xml('a nuclide with spaces around it', io_model(io_expr('x', 'X', '1'), nuclides(' Sr-90 '))),
        xml('the fixed tables', io_model(
            io_expr('x', 'X', '1'),
            '<simulation-settings><start-time>0</start-time><end-time>10</end-time>'
            '<time-unit>constructor</time-unit><output-options>__proto__</output-options></simulation-settings>')),
        xml('an entry index map', io_model(
            '<component type="parameter" name="p" dimension="1" index-lists="L1"><id>P</id>'
            '<entry type="parameter" index="i1"><value>2</value></entry></component>', io_list('L', 'a'))),
    ]


# --- variants made up here ------------------------------------------------------------------

def made_up_cases() -> List[Case]:
    """Corners the application's tests do not reach."""
    model = fx('MODEL_XML')
    shapes = fx('REAL_SHAPES_XML')
    out = []

    # Missing attributes and elements.
    out.append(xml('no name, no type, no id', io_model(
        '<component><entry type="expression"><equation>1</equation></entry></component>'
        '<component type="expression"><entry type="expression"><equation>2</equation></entry></component>'
        '<component name="Named"><id>N</id></component>'
        '<component type="expression" name="twice"><entry type="expression"><equation>3</equation></entry></component>'
        '<component type="expression" name="twice"><entry type="expression"><equation>4</equation></entry></component>'
        '<connection type="transfer" name="nowhere"><id>T</id></connection>')))
    out.append(xml('a transfer to blocks that were not imported', replace(
        model, '</block-model>',
        '<connection name="Lost" type="transfer" source="blk-transport" target="blk-deep"><id>blk-lost</id>'
        '<entry type="transfer"><transfer-equation><![CDATA[1]]></transfer-equation>'
        '<transfer-event><![CDATA[blk-event]]></transfer-event><entry-unit>Bq/y</entry-unit></entry></connection>'
        '<connection name="Void" type="transfer" source="blk-nothing" target="blk-transport"><id>blk-void</id>'
        '</connection>'
        '<connection name="Coeff" type="transfer&#45;coefficient" source="blk-soil" target="blk-deep"'
        ' index-lists="il-nuc,il-obj"><id>blk-coeff</id>'
        '<entry type="transfer"><transfer-equation><![CDATA[0.1]]></transfer-equation>'
        '<multiply-with-donor>FALSE</multiply-with-donor></entry></connection>'
        '</block-model>')))
    out.append(xml('entries keyed badly', replace(
        model, '<entry type="parameter" index="ix-mire">',
        '<entry type="parameter" index="ix-nowhere"><value>7</value></entry>'
        '<entry type="parameter" index="ix-lake,ix-mire"><value>8</value></entry>'
        '<entry type="parameter" index=" ix-forest , "><value>9</value></entry>'
        '<entry type="parameter" index="ix-mire">')))
    out.append(xml('entries keyed out of order', replace(
        model, '<entry type="compartment" index="ix-cs,ix-lake">',
        '<entry type="compartment" index="ix-mire,ix-ba"><initial-condition>5</initial-condition></entry>'
        '<entry type="compartment" index="ix-cs,ix-lake">')))

    # Sub-systems: nested, grouped, external, transports, and parents only the
    # blocks name.
    hierarchy = ('<hierarchy-model>'
                 '<sub-system-block name="Model"><id>root</id></sub-system-block>'
                 '<sub-system-block name="Near field"><id>ss-nf</id><sub-system>root</sub-system></sub-system-block>'
                 '<sub-system-block name="Buffer" type="group"><id>ss-grp</id><sub-system>ss-nf</sub-system>'
                 '</sub-system-block>'
                 '<sub-system-block name="Deep" type="subsystem"><id>ss-deep</id><sub-system>ss-grp</sub-system>'
                 '</sub-system-block>'
                 '<sub-system-block name="Library" type="external"><id>ss-ext</id></sub-system-block>'
                 '<sub-system-block name="Near field"><id>ss-nf2</id><sub-system>root</sub-system>'
                 '</sub-system-block>'
                 '<sub-system-block name="  "><id>ss-blank</id></sub-system-block>'
                 '<sub-system-block name="min"><id>ss-min</id><enabled>FALSE</enabled></sub-system-block>'
                 '</hierarchy-model>')
    text = replace(model, '<block-model>', hierarchy + '<block-model>')
    text = replace(text, '<component name="Soil" type="compartment" index-lists="il-nuc,il-obj">',
                   '<component name="Soil" type="compartment" index-lists="il-nuc,il-obj"><sub-system>ss-grp'
                   '</sub-system>')
    text = replace(text, '<component name="Deep soil" type="compartment" index-lists="il-nuc,il-obj">',
                   '<component name="Deep soil" type="compartment" index-lists="il-nuc,il-obj"><sub-system>ss-deep'
                   '</sub-system>')
    text = replace(text, '<component name="Total" type="expression" index-lists="il-obj">',
                   '<component name="Total" type="expression" index-lists="il-obj"><sub-system>ss-nf2</sub-system>')
    text = replace(text, '<component name="k leach" type="parameter" index-lists="il-obj">',
                   '<component name="k leach" type="parameter" index-lists="il-obj"><sub-system>Far away.Rock bed'
                   '</sub-system>')
    text = replace(text, '<component name="Held up" type="delay" index-lists="il-obj">',
                   '<component name="Held up" type="delay" index-lists="il-obj"><sub-system>ss-min</sub-system>')
    out.append(xml('sub-systems nested, grouped and undeclared', text))

    out.append(xml('the same bad name in two sub-systems', io_model(
        '<component type="parameter" name="k-1"><id>A.k</id><sub-system>A</sub-system>'
        '<entry type="parameter"><value>1</value></entry></component>'
        '<component type="parameter" name="k_1"><id>A.k2</id><sub-system>A</sub-system>'
        '<entry type="parameter"><value>2</value></entry></component>'
        '<component type="parameter" name="k-1"><id>B.k</id><sub-system>B</sub-system>'
        '<entry type="parameter"><value>3</value></entry></component>'
        '<component type="expression" name="use"><id>use</id>'
        '<entry type="expression"><equation>k-1 + A.k + B.k</equation></entry></component>')))

    # Index lists: sub-sets and mappings by id, and what they point at.
    out.append(xml('index lists that point at nothing', replace(
        model, '</index-list-model>',
        '<index-list name="Orphan"><id>il-orphan</id><index name="X"><id>ix-x</id></index>'
        '<sub-set of="il-gone"/></index-list>'
        '<index-list name="Mapped away"><id>il-away</id><index name="Y" enabled="FALSE"><id>ix-y</id></index>'
        '<mapping to="il-gone"><map from="ix-y" to="ix-north"/></mapping></index-list>'
        '<index-list name="Mapped globally"><id>il-glob</id><index name="Z"><id>ix-z</id></index>'
        '<mapping to="il-reg"><map from="ix-lake" to="ix-south"/><map from="ix-z" to="ix-none"/>'
        '<map to="ix-north"/></mapping></index-list>'
        '<index-list><index name="Nameless"/></index-list>'
        '<index-list name="Nuclides"><id>il-dup</id><index name="Cs-137"><id>ix-dup</id></index></index-list>'
        '</index-list-model>')))
    out.append(xml('material lists by name', io_model(
        io_expr('x', 'X', '1'),
        '<material-model>'
        '<nuclide name="Cs-137"><id>n1</id><half-life>9.49e8</half-life><unit>becquerel</unit></nuclide>'
        '<nuclide name="Stable-1"><id>n2</id><half-life>Infinity</half-life></nuclide>'
        '<nuclide name="Odd-1"><id>n3</id><half-life>soon</half-life></nuclide>'
        '<nuclide name="  "><id>n4</id></nuclide>'
        '<material name="Water"><id>w</id><unit> m3 </unit></material>'
        '</material-model>'
        '<index-list-model>'
        '<index-list name="Materials"><id>il-m</id><index name="Cs-137"><id>a</id></index>'
        '<index name="Stable-1"><id>b</id></index><index name="Odd-1"><id>c</id></index>'
        '<index name="Water"><id>d</id></index></index-list>'
        '<index-list name="Radionuclides"><id>il-r</id></index-list>'
        '<index-list name="Scenarios"><id>il-s</id><index name="One"><id>s1</id></index>'
        '<index name="Two"><id>s2</id></index><index name="Three" enabled="false"><id>s3</id></index>'
        '</index-list>'
        '<index-list name="elements"><id>il-e</id><index name="Cs"><id>e1</id></index></index-list>'
        '</index-list-model>')))
    out.append(xml('material lists by shape', io_model(
        io_expr('x', 'X', '1'),
        '<material-model><nuclide name="A-1"><id>n1</id><half-life>1e9</half-life></nuclide>'
        '<nuclide name="B-2"><id>n2</id><half-life>2e9</half-life></nuclide></material-model>'
        '<index-list-model>'
        '<index-list name="Big"><id>l1</id><index name="A-1"><id>a</id></index><index name="B-2"><id>b</id></index>'
        '<mapping to="l3"/></index-list>'
        '<index-list name="Small"><id>l2</id><index name="A-1"><id>c</id></index><sub-set of="l1"/></index-list>'
        '<index-list name="Other"><id>l3</id><index name="Q"><id>q</id></index></index-list>'
        '</index-list-model>')))
    out.append(xml('integer-like nuclide names', io_model(
        io_expr('x', 'X', '1'),
        '<material-model><nuclide name="Zz-9"><id>n1</id><half-life>1e9</half-life></nuclide>'
        '<nuclide name="42"><id>n2</id><half-life>2e9</half-life></nuclide>'
        '<nuclide name="7"><id>n3</id></nuclide>'
        '<nuclide name="007"><id>n4</id><half-life>3e9</half-life></nuclide></material-model>'
        '<nuclide-decay-model><decay-pair parent="42" daughter="7" rate="0x10"/>'
        '<decay-pair parent="Zz-9" daughter="42"/><decay-pair parent=" " daughter="42" rate="1"/>'
        '<decay-pair parent="7" daughter="Zz-9" rate=" 0.5 "/></nuclide-decay-model>')))

    # Lookup tables.
    out.append(xml('lookup tables of every sort', replace(
        model, '</block-model>',
        '<component name="Ragged" type="lookup-table"><id>lk1</id>'
        '<lookup-option>Use Input Nearest</lookup-option><lookup-cyclic>TRUE</lookup-cyclic>'
        '<entry type="lookup-table"><lookup-table-time-points>[0.0, 1.0, 2.0, 3.0]</lookup-table-time-points>'
        '<lookup-table-values>[5.0, , 7.0,]</lookup-table-values><link/></entry></component>'
        '<component name="Unknown rule" type="lookup-table"><id>lk2</id>'
        '<lookup-option>Spline</lookup-option><argument><argument-name>depth</argument-name></argument>'
        '<entry type="lookup-table"><lookup-table-time-points>[]</lookup-table-time-points>'
        '<lookup-table-values>[1.0]</lookup-table-values></entry></component>'
        '<component name="Inherited rule" type="lookup-table"><id>lk3</id>'
        '<lookup-option>constructor</lookup-option>'
        '<entry type="lookup-table"><lookup-table-time-points>[0, 1]</lookup-table-time-points>'
        '<lookup-table-values>[0x10, 1e400]</lookup-table-values></entry></component>'
        '<component name="Prototype rule" type="lookup-table"><id>lk4</id>'
        '<lookup-option>__proto__</lookup-option><argument/></component>'
        '<component name="Plain" type="lookup-table"><id>lk5</id>'
        '<lookup-option>  Interpolation-Extrapolation </lookup-option>'
        '<entry type="lookup-table"><lookup-table-time-points> 0, 1 </lookup-table-time-points>'
        '<lookup-table-values>[2 ;3]</lookup-table-values></entry></component>'
        '</block-model>')))

    # The blocks that remember, and events.
    out.append(xml('recorders of every sort', replace(
        model, '</block-model>',
        '<component name="Low" type="min-max" index-lists="il-obj"><id>r1</id><operation>min</operation>'
        '<entry type="min-max"><target-expression>blk-total</target-expression>'
        '<reset-event>blk-event</reset-event><stop-recording-event>blk-ev2</stop-recording-event></entry>'
        '<entry type="min-max" index="ix-lake"><target-expression>blk-k * 2</target-expression></entry>'
        '</component>'
        '<component name="Median" type="min-max"><id>r2</id><operation>MEDIAN</operation></component>'
        '<component name="Mean2" type="running-mean"><id>r3</id>'
        '<entry type="running-mean"><reset-event>blk-ev2</reset-event></entry></component>'
        '<component name="Snap" type="snapshot" index-lists="il-obj"><id>r4</id>'
        '<entry type="snapshot" index="ix-mire"><snapshot-target>blk-total</snapshot-target></entry></component>'
        '<component name="Lag" type="delay" index-lists="il-obj"><id>r5</id>'
        '<entry type="delay"><delay-target>blk-soil</delay-target></entry>'
        '<entry type="delay" index="ix-lake"><delay-time>blk-k</delay-time></entry></component>'
        '<component name="Down" type="discrete-event"><id>blk-ev2</id>'
        '<entry type="discrete-event"><first-expression>blk-total</first-expression>'
        '<direction> left </direction></entry></component>'
        '<component name="Arrow" type="discrete-event"><id>ev3</id>'
        '<entry type="discrete-event"><direction>&lt;-</direction></entry></component>'
        '<component name="Either" type="discrete-event"><id>ev4</id>'
        '<entry type="discrete-event"><direction>&gt;-&lt;</direction></entry></component>'
        '<component name="Odd" type="discrete-event"><id>ev5</id>'
        '<entry type="discrete-event"><direction>constructor</direction></entry></component>'
        '<component name="Odder" type="discrete-event"><id>ev6</id>'
        '<entry type="discrete-event"><direction>__proto__</direction></entry></component>'
        '<component name="Unknown" type="discrete-event"><id>ev7</id>'
        '<entry type="discrete-event"><direction>UP</direction><second-expression>1</second-expression></entry>'
        '</component>'
        '</block-model>')))

    # Expressions with an evaluation mode, transports out of place, reductions.
    out.append(xml('expressions with modes and reductions', replace(
        model, '</block-model>',
        '<component name="Post" type="post-processing"><id>e1</id>'
        '<entry type="expression"><equation>blk-total * 2</equation></entry></component>'
        '<component name="Const" type="constant" index-lists="il-obj"><id>e2</id>'
        '<entry type="expression"><equation>3</equation></entry>'
        '<entry type="expression" index="ix-lake"><equation>4</equation></entry></component>'
        '<component name="Fn" type="expression"><id>e3</id>'
        '<argument><argument-name>1st value</argument-name></argument><argument/>'
        '<argument><argument-key>min</argument-key></argument><argument><argument-key>x y</argument-key></argument>'
        '<argument><argument-key>x_y</argument-key></argument>'
        '<entry type="expression" index="ix-lake"><equation>5</equation></entry></component>'
        '<component name="N" type="transport&#45;number"><id>e4</id></component>'
        '<component name="Pct" type="index-operation" index-lists="il-nuc"><id>io1</id>'
        '<property name="percentile" type="double">95</property><operation>Percentile</operation>'
        '<entry type="expression"><equation>blk-soil</equation></entry>'
        '<entry type="expression" index="ix-cs"><equation> blk-deep </equation></entry></component>'
        '<component name="Pct2" type="index-operation"><id>io2</id><percentile>50.5</percentile>'
        '<operation>Median</operation><entry type="expression"><equation>blk-soil</equation></entry></component>'
        '<component name="Pct3" type="index-operation"><id>io3</id><property name="percentile">abc</property>'
        '<entry type="expression"><equation>blk-pct</equation></entry></component>'
        '<component name="Chain" type="index-operation"><id>io4</id>'
        '<entry type="expression"><equation>io3</equation></entry></component>'
        '<component name="Partly" type="aggregate"><id>ag1</id><operation>Product</operation>'
        '<entry type="expression"><equation>blk-soil + blk-transport + blk-gone1 + blk-gone2 + blk-gone3</equation>'
        '</entry><entry type="expression" index="ix-cs"><equation>blk-deep+</equation></entry></component>'
        '<component name="Nothing" type="aggregate"><id>ag2</id>'
        '<entry type="expression"><equation>blk-gone</equation></entry></component>'
        '<component name="Empty" type="aggregate"><id>ag3</id></component>'
        '</block-model>')))

    # Simulation settings.
    out.append(xml('simulation settings, odd', replace(
        replace(model, '<start-time>0.0</start-time>', '<start-time>-10</start-time>'),
        '<simulation-type>DETERMINISTIC</simulation-type>',
        '<simulation-type>probabilistic</simulation-type><time-unit>days</time-unit>'
        '<output-options>0x2</output-options>'
        '<time-series-list><time-series type="custom"><values>[5; 3, x, 1e400, 4]</values></time-series>'
        '<time-series type="linear"><n>1</n></time-series>'
        '<time-series type="linear"><increment>-1</increment></time-series></time-series-list>'
        '<outputs><output id="nowhere"/><output/></outputs>')))
    out.append(xml('simulation span unusable', replace(
        replace(replace(model, '<end-time>1000.0</end-time>', '<end-time>-5</end-time>'),
                '<time-unit>year</time-unit>', '<time-unit>Fortnight</time-unit>'),
        '<java-solver>ODE15S</java-solver>', '<java-solver>ode-23.tb</java-solver>')))
    out.append(xml('simulation settings missing', io_model(io_expr('x', 'X', '1'))))
    out.append(xml('probabilistic settings, the rest', replace(
        model, '</data-model>',
        '<probabilistic-settings><no-simulations>1e400</no-simulations><sampling>Random</sampling>'
        '<probabilistic-parameters><selected-parameter> blk-k </selected-parameter>'
        '<selected-parameter/></probabilistic-parameters>'
        '<correlation-matrix><correlation-pair/><correlation-pair/></correlation-matrix>'
        '</probabilistic-settings></data-model>')))
    out.append(xml('probabilistic settings, correlation off', replace(
        model, '</data-model>',
        '<probabilistic-settings><no-simulations>2.5</no-simulations><seed>0x1F</seed>'
        '<correlation-enabled>false</correlation-enabled>'
        '<correlation-matrix><correlation-pair/></correlation-matrix></probabilistic-settings></data-model>')))
    for label, start, end in [('tie', '0', '1000500'), ('tiny', '0.0001234565', '1e21'),
                              ('huge', '0', '1.7976931348623157e308'), ('six figures', '1.5', '123456.75'),
                              ('negative', '-5e-4', '1e-3')]:
        out.append(xml(f'run span, {label}', replace(
            replace(model, '<start-time>0.0</start-time>', f'<start-time>{start}</start-time>'),
            '<end-time>1000.0</end-time>', f'<end-time>{end}</end-time>')))

    # Where it came from: dates, comments, names.
    for label, stamp in [('year 10000', '253402300800000'), ('the last day', '8.64e15'),
                         ('past the last day', '8640000000000001'), ('a fraction', '1.9'), ('hex', '0x10'),
                         ('not a date', 'yesterday')]:
        out.append(xml(f'modified, {label}', described(
            f'<project-properties><modification-date>{stamp}</modification-date>'
            '<property name="comment">  Line one\nCreated at noon  </property>'
            '<name>From the element</name></project-properties>')))
    out.append(xml('comment in an element', described(
        '<project-properties><full-name>Full</full-name><comment>Created at\u2028noon</comment>'
        '<property name="author"></property></project-properties>'), file_name='dir/'))
    out.append(xml('no project properties', described(''), file_name='dir\\Some model.XML'))
    out.append(xml('named model, no file', described('<project-properties name=""/>'), file_name='  .eco'))

    # What it is indexed by: ties broken as localeCompare breaks them.
    names = ['L_1', 'L1', 'L10', 'l1', 'L2', 'aB', 'Ab', 'ab', 'AB', '_x', 'x0']
    lists = ''.join(f'<index-list name="{n}"><id>d{k}</id><index name="i"><id>i</id></index></index-list>'
                    for k, n in enumerate(names))
    for start in range(0, len(names), 5):
        chosen = ','.join(f'd{k}' for k in range(start, min(start + 6, len(names))))
        out.append(xml(f'collation from {names[start]}', io_model(
            f'<component type="parameter" name="p"><id>p</id>'
            f'<entry type="parameter"><value>1</value></entry></component>'
            f'<component type="parameter" name="q" index-lists="{chosen}"><id>q</id></component>',
            f'<index-list-model>{lists}</index-list-model>')))

    # Endpoints that all name nothing.
    out.append(xml('endpoints all gone', replace(
        model, '<simulation-type>DETERMINISTIC</simulation-type>',
        '<simulation-type>DETERMINISTIC</simulation-type><outputs><output id="gone"/></outputs>')))

    # Compiled functions with awkward parameter names.
    out.append(xml('compiled functions, awkward', replace(
        model, '\t<index-list-model>',
        '<extra><function-model>'
        '<function source-file-name="sum.java"><function-metadata>'
        '<parameter-metadata key="min"/><parameter-metadata name="2nd"/><parameter-metadata/>'
        '<parameter-metadata key="a b"/><parameter-metadata key="a_b"/><parameter-metadata key="a b"/>'
        '</function-metadata></function>'
        '<function><function-description>Nameless</function-description></function>'
        '<function name="  "/>'
        '</function-model></extra>\n\t<index-list-model>')))

    # Interfaces: several targets, a kind that cannot be fed, a fed block
    # whose source was dropped.
    text = interface(sources=['blk-out', 'blk-out2'], op='PRODUCT')
    text = replace(text, '</block-model>',
                   '<component name="Table" type="lookup-table"><id>blk-lk</id><guid>G-LK</guid>'
                   '<sub-system>ss-bio</sub-system></component>'
                   '<component name="Input2" type="model-input"><id>blk-mi2</id><sub-system>ss-bio</sub-system>'
                   '<interface-object guid="G-LK"/><interface-object guid=" "/>'
                   '<interface-object guid="G-B" operation=" mean "/></component>'
                   '<connection name="wire2" type="connector"><id>blk-conn2</id>'
                   '<model-connection source="G-OUT" target="G-LK"/>'
                   '<model-connection source="G-A" target="G-B"/>'
                   '<model-connection source="G-OUT2" target="G-B"/>'
                   '<model-connection source="G-GONE" target="G-B"/>'
                   '<model-connection source=" " target="G-B"/></connection>'
                   '</block-model>')
    text = replace(text, '<component name="A" type="compartment"><id>blk-a</id>',
                   '<component name="A" type="compartment"><id>blk-a</id><guid>G-A</guid>')
    text = replace(text, '<component name="B" type="compartment"><id>blk-b</id>',
                   '<component name="B" type="compartment"><id>blk-b</id><guid>G-B</guid>')
    out.append(xml('interfaces, awkward', text))
    out.append(xml('interfaces declared twice over', interface(wired=False).replace(
        '<interface-object guid="G-IN"', '<interface-object guid="G-X"/><interface-object guid="G-IN"', 1)))

    # Blocks switched off, by id, inside and outside switched-off sub-systems.
    text = replace(shapes, '<component name="Water" type="compartment" index-lists="Elements">\n\t\t\t<id>NF',
                   '<component name="Water" type="compartment" index-lists="Elements"><enabled>false</enabled>'
                   '\n\t\t\t<id>NF')
    text = replace(text, '<block-model>',
                   '<hierarchy-model><sub-system-block name="NF"><id>NF</id><enabled>false</enabled>'
                   '</sub-system-block><sub-system-block name="Inner"><id>NF.In</id><sub-system>NF</sub-system>'
                   '</sub-system-block></hierarchy-model><block-model>')
    text = replace(text, '<component name="k" type="parameter" index-lists="Elements">',
                   '<component name="k" type="parameter" index-lists="Elements"><sub-system>NF.In</sub-system>'
                   '<enabled>false</enabled>')
    out.append(xml('switched off in and out of sub-systems', text))

    # XML the reader must refuse, and XML it must read as the application does.
    out.append(xml('xml: mismatched', '<data-model><a></b></data-model>'))
    out.append(xml('xml: unclosed', '<data-model><block-model>'))
    out.append(xml('xml: no elements', '<?xml version="1.0"?><!-- nothing -->'))
    out.append(xml('xml: two roots', '<data-model/><data-model/>'))
    out.append(xml('xml: unquoted', '<data-model a=1/>'))
    out.append(xml('xml: an astral character first', '<data-model><c>\U0001F600\U0001F600</c><d a="1"b/></data-model>'))
    out.append(xml('xml: space that is not XML space', '<data-model\u00a0/>'))
    out.append(xml('xml: unterminated comment', '<data-model><!-- </data-model>'))
    out.append(xml('xml: unterminated CDATA', '<data-model><![CDATA[ </data-model>'))
    out.append(xml('xml: unterminated declaration', '<!DOCTYPE x'))
    out.append(xml('xml: stray close', '</data-model>'))
    out.append(xml('xml: no data-model', '<project><thing/></project>'))
    out.append(xml('xml: data-model inside', '<?xml version="1.0"?>\n<!DOCTYPE p>\n<p><x><data-model>'
                                             '<project-properties name="Inside"/></data-model></x></p>'))
    out.append(xml('xml: entities', io_model(
        io_expr('e&#12a;x', 'E1', 'a &lt; b &amp;&amp; &#1114112; &#xD800; &constructor; &#X41; &nbsp;')
        + io_expr('\U0001F600z', 'E2', '1'))))
    out.append(xml('xml: an empty data model', '<data-model/>'))
    return out


# --- archives -----------------------------------------------------------------------------------

def raw_zip(entries: List[Dict[str, Any]]) -> bytes:
    """A ZIP archive written byte by byte, so every field is the test's to set.

    Each entry: ``name`` (text or bytes), ``data`` (the bytes it holds),
    ``method`` (0 stored, 8 deflate, or anything), ``payload`` (what is written
    in place of the compressed data), ``flags`` (default: UTF-8 names) and
    ``size`` (the uncompressed size the directory claims).
    """
    local = bytearray()
    central = bytearray()
    for e in entries:
        name = e['name'].encode('utf-8') if isinstance(e['name'], str) else e['name']
        data = e.get('data', b'')
        method = e.get('method', 8)
        if 'payload' in e:
            payload = e['payload']
        elif method == 8:
            c = zlib.compressobj(9, zlib.DEFLATED, -15)
            payload = c.compress(data) + c.flush()
        else:
            payload = data
        flags = e.get('flags', 0x800)
        size = e.get('size', len(data))
        crc = zlib.crc32(data)
        offset = len(local)
        local += struct.pack('<IHHHHHIIIHH', 0x04034B50, 20, flags, method, 0, 0, crc, len(payload), size,
                             len(name), 0) + name + payload
        central += struct.pack('<IHHHHHHIIIHHHHHII', 0x02014B50, 20, 20, flags, method, 0, 0, crc, len(payload),
                               size, len(name), 0, 0, 0, 0, 0, offset) + name
    eocd = struct.pack('<IHHHHIIH', 0x06054B50, 0, 0, len(entries), len(entries), len(central), len(local), 0)
    return bytes(local + central + eocd)


def lie_about_directory(data: bytes) -> bytes:
    """The archive with its first central directory record's signature broken."""
    at = data.index(b'PK\x01\x02')
    return data[:at] + b'PK\x09\x09' + data[at + 4:]


MINIMAL = ('<data-model><block-model><component type="expression" name="x" dimension="0" '
           'index-lists=""><id>X</id><entry type="expression"><equation>1</equation></entry></component>'
           '</block-model></data-model>')


def archive_cases() -> List[Case]:
    """Archives and bare files, some built by the fixture's own ZIP writer."""
    model = fx('MODEL_XML')
    built = _node([
        {'task': 'zip', 'files': [{'name': 'Test import/model/model.xml', 'text': model, 'deflate': True},
                                  {'name': 'Test import/views.xml', 'text': fx('VIEWS_XML')}]},
        {'task': 'zip', 'files': [{'name': 'p/views.xml', 'text': fx('VIEWS_XML')}]},
        {'task': 'zip', 'files': [{'name': 'deeply/nested/path/model.xml', 'text': model}]},
        {'task': 'utf16', 'text': fx('SHEET_XML')},
        {'task': 'utf16', 'text': fx('REAL_SHAPES_XML')},
        {'task': 'utf16', 'text': model.replace('Top soil layer', 'Top soil \U0001F30D layer')},
        {'task': 'zip', 'files': [{'name': '.version', 'text': 'version=6.5 track-changes=false', 'deflate': True},
                                  {'name': 'proj\\model\\model.xml', 'text': model, 'deflate': True}]},
    ])
    data = [base64.b64decode(b['base64']) for b in built]
    utf8 = model.encode('utf-8')
    return [
        file('whole archive', data[0]),
        file('whole archive, named', data[0], file_name='C:\\Users\\x\\Test import.eco'),
        file('archive with no model', data[1]),
        file('model nested deep', data[2]),
        file('sheet in UTF-16', data[3]),
        file('bare UTF-16', data[4]),
        file('bare UTF-16 with an astral character', data[5]),
        file('archive with a version and backslashes', data[6], file_name='x.eco'),
        file('bare UTF-8 with a BOM', b'\xef\xbb\xbf' + utf8),
        file('bare UTF-8 with two BOMs', b'\xef\xbb\xbf\xef\xbb\xbf' + utf8),
        file('bare UTF-16LE', b'\xff\xfe' + model.encode('utf-16-le')),
        file('bare UTF-16BE with two BOMs', b'\xfe\xff\xfe\xff' + model.encode('utf-16-be')),
        file('bare, with a version', utf8, file_name='m.xml', version='5.1'),
        file('bare UTF-8, broken bytes', utf8.replace(b'Top soil layer', b'Top \xc3\x28 soil \xed\xa0\x80 layer')),
        file('neither ZIP nor model', b'hello'),
        file('empty', b''),
        file('PK and nothing else', b'PK\x03\x04 not really'),
        file('an empty archive', raw_zip([])),
        file('a damaged result beside the model', raw_zip([
            {'name': 'simulation/result.dta', 'payload': b'\xff\xff\xff\xff', 'size': 100},
            {'name': 'model.xml', 'data': MINIMAL.encode('utf-8')},
        ])),
        file('an encrypted result', raw_zip([
            {'name': 'model.xml', 'data': MINIMAL.encode('utf-8')},
            {'name': 'simulation/r.dta', 'data': b'x', 'flags': 0x801},
        ])),
        file('a method nobody supports', raw_zip([
            {'name': 'model.xml', 'data': MINIMAL.encode('utf-8'), 'method': 12},
        ])),
        file('a damaged XML beside the model', raw_zip([
            {'name': 'views.xml', 'payload': b'\x07\x00garbage', 'size': 5},
            {'name': 'model.xml', 'data': MINIMAL.encode('utf-8')},
        ])),
        file('an XML shorter than it says', raw_zip([
            {'name': 'model.xml', 'data': MINIMAL.encode('utf-8'), 'size': len(MINIMAL) + 3},
        ])),
        file('an XML cut short', raw_zip([
            {'name': 'model.xml', 'payload': zlib.compress(MINIMAL.encode('utf-8'))[2:20], 'size': len(MINIMAL)},
        ])),
        file('model under another name', raw_zip([
            {'name': 'dir/', 'data': b'', 'method': 0},
            {'name': 'notes.XML', 'data': b'<notes/>', 'method': 0},
            {'name': 'Project.XML', 'data': MINIMAL.encode('utf-8')},
        ])),
        file('a name twice', raw_zip([
            {'name': 'model.xml', 'data': b'<nothing/>', 'method': 0},
            {'name': 'a.bin', 'data': b'x' * 50},
            {'name': 'model.xml', 'data': MINIMAL.encode('utf-8')},
            {'name': '.version', 'data': b'\xff\xfeversion=7', 'method': 0},
        ])),
        file('names that are not UTF-8', raw_zip([
            {'name': b'caf\xe9/notes.txt', 'data': b'x', 'flags': 0},
            {'name': b'd\xc3\xa9j\xc3\xa0/notes.txt', 'data': b'y', 'flags': 0},
            {'name': '\ufeffbom.txt', 'data': b'z'},
        ])),
        file('a central directory that lies', lie_about_directory(raw_zip([
            {'name': 'model.xml', 'data': MINIMAL.encode('utf-8')},
        ]))),
        file('a version that says nothing', raw_zip([
            {'name': 'x/.version', 'data': b'track-changes=false\nversionx=1'},
            {'name': 'model.xml', 'data': MINIMAL.encode('utf-8')},
        ])),
    ]

# --- random models ------------------------------------------------------------------------------

#: Names chosen to collide: spaces, operators, dots, reserved words, a name that
#: is another's tidied form (`k-1`, `k_1`, `k_1_1`), blanks, non-ASCII.
POOL = ['Soil', 'Deep soil', 'soil', 'k-1', 'k_1', 'k 1', 'k_1_1', 'A-B', 'A', 'B', 'A_B', 'min', 'sum', 'x.y',
        'Water', ' ', '', '__proto__', 'constructor', '1st', 'a(b)', 'Café', '\U0001F600x', 'time', 'Total',
        'blk-1', 'q', 'Near field', 'Near_field', 'NF', 'Q[1]', 'r,s', 'e^x', 'Deep  soil', ' Soil ', 'Sub', 'if',
        'rate', 'Rate']
RANDOM_TYPES = ['compartment', 'compartment', 'expression', 'expression', 'parameter', 'parameter', 'lookup-table',
                'post-processing', 'constant', 'index-operation', 'aggregate', 'min-max', 'running-mean', 'snapshot',
                'delay', 'discrete-event', 'transport-begin', 'transport-number', 'source', 'sink', 'weird',
                'model-output', 'model-input']
ENTRY_TYPE = {'compartment': 'compartment', 'transport-begin': 'compartment', 'parameter': 'parameter',
              'lookup-table': 'lookup-table', 'min-max': 'min-max', 'running-mean': 'running-mean',
              'snapshot': 'snapshot', 'delay': 'delay', 'discrete-event': 'discrete-event'}


def random_model(seed: int) -> str:
    """A small, messy model.xml, the same for the same seed: names from
    :data:`POOL`, index lists with and without predefined types, a hierarchy
    with groups, transports and external sub-systems, blocks of every type
    (some with no name, no id or an undeclared sub-system), per-index entries
    keyed rightly and wrongly, equations mixing names, ids and qualified names,
    interfaces, transfers to anything, and simulation settings."""
    rnd = random.Random(seed)

    def name() -> str:
        return rnd.choice(POOL)

    out = ['<data-model>']
    if rnd.random() < 0.7:
        out.append(f'<project-properties name={quoteattr(rnd.choice(["model", "Random", ""]))}/>')

    lists = []
    out.append('<index-list-model>')
    for li in range(rnd.randint(0, 3)):
        lid = f'il{li}'
        members = [(f'{lid}-{k}', rnd.choice(['Cs-137', 'Sr-90', 'I-129', 'Lake', 'Mire', ' x ', 'Nb']))
                   for k in range(rnd.randint(1, 4))]
        lists.append((lid, members))
        predefined = rnd.choice(['', '', 'MATERIALS', 'RADIONUCLIDES', 'SCENARIOS', 'Elements'])
        prop = f'<property name="predefined-type">{predefined}</property>' if predefined else ''
        sub = f'<sub-set of="il{rnd.randint(0, 3)}"/>' if rnd.random() < 0.3 else ''
        list_name = rnd.choice(['Contaminants', 'Radionuclides', 'Objects', 'Scenarios', 'Elements', f'L {li}', name()])
        indices = ''.join(f'<index name={quoteattr(n)} enabled="{rnd.choice(["true", "true", "false"])}">'
                          f'<id>{i}</id></index>' for i, n in members)
        out.append(f'<index-list name={quoteattr(list_name)}><id>{lid}</id>{prop}{indices}{sub}</index-list>')
    out.append('</index-list-model>')
    if rnd.random() < 0.6:
        out.append('<material-model>' + ''.join(
            f'<nuclide name="{n}"><id>{n}</id><half-life>{rnd.choice(["1e9", "Infinity", "", "x"])}</half-life>'
            f'<unit>{rnd.choice(["Bq", "mol", "", "kg"])}</unit></nuclide>'
            for n in rnd.sample(['Cs-137', 'Sr-90', 'I-129', 'Nb'], rnd.randint(1, 3))) + '</material-model>')

    systems = []
    out.append('<hierarchy-model><sub-system-block name="Model"><id>root</id></sub-system-block>')
    for k in range(rnd.randint(0, 5)):
        sid = f'ss{k}'
        parent = rnd.choice(['root'] + [x for x, _ in systems]) if rnd.random() < 0.8 else ''
        kind = rnd.choice(['', '', 'group', 'transport', 'external', 'subsystem'])
        systems.append((sid, kind))
        out.append(f'<sub-system-block name={quoteattr(name() or "S")}'
                   + (f' type={quoteattr(kind)}' if kind else '') + f'><id>{sid}</id>'
                   + (f'<sub-system>{parent}</sub-system>' if parent else '')
                   + ('<enabled>false</enabled>' if rnd.random() < 0.15 else '') + '</sub-system-block>')
    out.append('</hierarchy-model>')

    blocks = []
    for b in range(rnd.randint(1, 14)):
        t = rnd.choice(RANDOM_TYPES)
        nm = name()
        r = rnd.random()
        bid = (f'blk-{b}' if r < 0.4 else nm.replace(' ', '_') + str(b) if r < 0.7 else f'Sub.{nm}' if r < 0.9 else '')
        blocks.append((t, nm, bid))
    all_ids = [bid for _, _, bid in blocks if bid] + ['nowhere', '']

    def equation() -> str:
        parts = [rnd.choice([name(), rnd.choice(all_ids), 'Sub.' + name(), str(rnd.randint(0, 9)), 'time'])
                 for _ in range(rnd.randint(1, 4))]
        return rnd.choice([' + ', '-', ' * ', '*', ', ', ' ']).join(parts)

    out.append('<block-model>')
    for t, nm, bid in blocks:
        dims = rnd.sample(lists, rnd.randint(0, min(2, len(lists)))) if lists else []
        attrs = (f' name={quoteattr(nm)}' if rnd.random() < 0.95 else '') + f' type={quoteattr(t)}'
        if dims:
            attrs += f' index-lists="{",".join(l for l, _ in dims)}"'
        body = f'<id>{escape(bid)}</id>' if bid else ''
        if systems and rnd.random() < 0.6:
            body += f'<sub-system>{rnd.choice([x for x, _ in systems] + ["Undeclared.Path", "ss9"])}</sub-system>'
        if rnd.random() < 0.1:
            body += '<enabled>false</enabled>'
        if rnd.random() < 0.3:
            body += f'<guid>G{rnd.randint(0, 5)}</guid>'
        et = ENTRY_TYPE.get(t, 'expression')

        def entry(index: str = '') -> str:
            if et == 'compartment':
                inner = (f'<initial-condition>{escape(equation())}</initial-condition>'
                         f'<lower-saturation>{rnd.choice(["0", "", "-1", "5"])}</lower-saturation>')
            elif et == 'parameter':
                inner = f'<value>{rnd.choice(["1", "0.5", "x", "Infinity", ""])}</value>'
            elif et == 'lookup-table':
                inner = ('<lookup-table-time-points>[0, 1, 2]</lookup-table-time-points>'
                         '<lookup-table-values>[1, 2]</lookup-table-values>')
            elif et in ('min-max', 'running-mean'):
                inner = (f'<target-expression>{escape(equation())}</target-expression>'
                         f'<reset-event>{escape(rnd.choice(all_ids))}</reset-event>')
            elif et == 'snapshot':
                inner = (f'<snapshot-target>{escape(equation())}</snapshot-target>'
                         f'<snapshot-event>{escape(rnd.choice(all_ids))}</snapshot-event>')
            elif et == 'delay':
                inner = (f'<delay-target>{escape(equation())}</delay-target>'
                         f'<delay-time>{escape(equation())}</delay-time>')
            elif et == 'discrete-event':
                inner = (f'<first-expression>{escape(equation())}</first-expression>'
                         f'<direction>{rnd.choice(["RIGHT", "left", "x"])}</direction>')
            else:
                text = equation() if t != 'aggregate' else '+'.join(rnd.sample(all_ids, 2))
                inner = f'<equation>{escape(text)}</equation>'
            return f'<entry type="{et}"' + (f' index="{index}"' if index else '') + f'>{inner}</entry>'

        body += entry()
        for _ in range(rnd.randint(0, 2)):
            if dims:
                body += entry(','.join(rnd.choice(m)[0] for _, m in dims))
        if t in ('model-output', 'model-input'):
            for _ in range(rnd.randint(1, 3)):
                op = f' operation={quoteattr(rnd.choice(["ADD", "MAX", "PRODUCT"]))}' if rnd.random() < 0.5 else ''
                body += f'<interface-object guid="G{rnd.randint(0, 5)}"{op}/>'
        if rnd.random() < 0.2 and t in ('expression', 'lookup-table'):
            body += '<argument><argument-key>x</argument-key></argument>'
        out.append(f'<component{attrs}>{body}</component>')
    for c in range(rnd.randint(0, 6)):
        src = rnd.choice(all_ids)
        dst = rnd.choice(all_ids)
        t = rnd.choice(['transfer', 'transfer-coefficient', 'influence', 'connector'])
        dims = rnd.sample(lists, rnd.randint(0, min(2, len(lists)))) if lists else []
        extra = f' index-lists="{",".join(l for l, _ in dims)}"' if dims else ''
        if rnd.random() < 0.3:
            extra += f' dimension="{rnd.randint(0, 2)}"'
        donor = f'<multiply-with-donor>{rnd.choice(["true", "false"])}</multiply-with-donor>' if rnd.random() < 0.5 else ''
        body = (f'<id>c{c}</id><entry type="transfer"><transfer-equation>{escape(equation())}</transfer-equation>'
                f'{donor}</entry>')
        if systems and rnd.random() < 0.5:
            body += f'<sub-system>{rnd.choice([x for x, _ in systems])}</sub-system>'
        if t == 'connector':
            body += ''.join(f'<model-connection source="G{rnd.randint(0, 5)}" target="G{rnd.randint(0, 5)}"/>'
                            for _ in range(rnd.randint(1, 3)))
        out.append(f'<connection name={quoteattr(name() or "c")} type="{t}" source={quoteattr(src)} '
                   f'target={quoteattr(dst)}{extra}>{body}</connection>')
    out.append('</block-model>')
    if rnd.random() < 0.8:
        outputs = ('<outputs>' + ''.join(f'<output id={quoteattr(rnd.choice(all_ids))}/>' for _ in range(3))
                   + '</outputs>') if rnd.random() < 0.5 else ''
        out.append(f'<simulation-settings><start-time>{rnd.choice(["0", "-1", "10"])}</start-time>'
                   f'<end-time>{rnd.choice(["100", "1e6", "5"])}</end-time>'
                   f'<time-unit>{rnd.choice(["year", "d", "x"])}</time-unit>'
                   f'<java-solver>{rnd.choice(["ODE15S", "ODE45", "RADAU5", ""])}</java-solver>'
                   f'{outputs}</simulation-settings>')
    out.append('</data-model>')
    return ''.join(out)


# --- the tests ------------------------------------------------------------------------------------

@needs_app
class TheApplicationsOwnVariants(ParityCase):
    def test_every_variant_the_application_tests(self):
        self.assertSameImports(run_js_cases())

    def test_names_out_of_the_file(self):
        self.assertSameImports(run_js_name_cases())

    def test_the_variants_are_what_they_say(self):
        # A few of the application's own assertions, so that a variant that
        # stopped exercising its rule would be noticed here too.
        by = {c.label: python(c) for c in run_js_cases() + run_js_name_cases()}
        self.assertEqual(by['fixture']['project']['name'], 'Test import')
        self.assertEqual(by['saturation false']['project']['simulation']['non_negative'], False)
        self.assertEqual(by['described']['project']['description'].split('\n')[0],
                         'Imported from Vault_assessment.eas, written by Ecolego 6.5, by a.modeller, '
                         'created Tue May 25 17:41:51 UTC 2021.')
        self.assertEqual(by['interface ADD']['project']['expressions'][-1]['equation'],
                         'sum(Near.release, Near.other)')
        self.assertEqual(by['a function name']['project']['expressions'][1]['equation'], 'min_1 * 2')
        self.assertIn("'__proto__'", by['a nuclide called __proto__']['error']['message'])
        self.assertEqual(by['AUTO both ends']['project']['simulation']['output_times'][0]['from'], None)
        self.assertEqual(by['endpoints']['project']['simulation']['endpoints'], ['NearField.Lake', 'k_leach'])


@needs_app
class VariantsMadeUpHere(ParityCase):
    def test_made_up_variants(self):
        self.assertSameImports(made_up_cases())

    def test_what_javascript_decides(self):
        by = {c.label: python(c) for c in made_up_cases()}
        # `<output-options>` read through Number(): 0x2 is 2, specified times.
        self.assertEqual(by['simulation settings, odd']['project']['simulation']['spacing'], 'series')
        # A nuclide called 42 is listed first, as an object lists it.
        self.assertEqual(list(by['integer-like nuclide names']['project']['half_lives']),
                         ['7', '42', 'Zz-9', '007'])
        # toPrecision rounds a tie up; Python's formatting would not.
        self.assertIn('Runs 0 to 1.001e6 years', by['run span, tie']['project']['description'])
        # A plain object answers `constructor`: no warning, and nothing JSON can hold.
        lookups = {l['name']: l for l in by['lookup tables of every sort']['project']['lookups']}
        self.assertNotIn('interpolation', lookups['Inherited_rule'])
        self.assertEqual(lookups['Prototype_rule']['interpolation'], {})
        # A year past 9999 and a time past what a Date holds.
        self.assertIn('last changed +010000-01', by['modified, year 10000']['project']['description'])
        self.assertEqual(by['modified, past the last day']['error'],
                         {'name': 'RangeError', 'message': 'Invalid time value'})


@needs_app
class Archives(ParityCase):
    def test_archives_and_bare_files(self):
        self.assertSameImports(archive_cases())

    def test_a_path_is_read_with_its_name(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'Some project.eco'
            path.write_bytes(raw_zip([{'name': 'model.xml', 'data': MINIMAL.encode('utf-8')}]))
            project, report = import_eco_file(path)
            same = import_eco_file(path.read_bytes(), file_name='Some project.eco')
        self.assertEqual(project['name'], 'Some project')
        self.assertEqual(dumps(project), dumps(same.project))
        self.assertEqual(report.summary(), same.report.summary())


@needs_app
class Distributions(ParityCase):
    def test_distributions_per_index_and_by_default(self):
        model = fx('MODEL_XML')

        def with_one(expr: str, fn: str) -> str:
            text, n = re.subn(r'(<entry type="parameter" index="ix-lake">\s*<value>[^<]*</value>)',
                              lambda m: f'{m.group(1)}<pdf function="{fn}"><pdf-value><![CDATA[{expr}]]>'
                                        '</pdf-value></pdf>', model, count=1)
            assert n == 1
            return text

        default = replace(model, '<value>0.001</value>',
                          '<value>0.001</value><pdf function="logn"><pdf-value>logn(gm=1,gsd=2, trmin=0.1)'
                          '</pdf-value></pdf>')
        cases = [
            xml('logt per index', with_one('logt(min=0.7,max=20,mode=3)', 'logt')),
            xml('weibull, unread', with_one('weibull(a=1,b=2)', 'weibull')),
            xml('by default and per index', replace(
                default, '<entry type="parameter" index="ix-mire">\n\t\t\t\t<value>0.02</value>',
                '<entry type="parameter" index="ix-mire"><value>0.02</value>'
                '<pdf><pdf-value>pg(values=1;2;x;3,inorder=false,pos=2)</pdf-value></pdf>'
                '<pdf><pdf-value>unif(min=1,max=2)</pdf-value></pdf>')),
            xml('empty and unknown', replace(
                with_one('', 'unif'), '<entry type="parameter" index="ix-mire">\n\t\t\t\t<value>0.02</value>',
                '<entry type="parameter" index="ix-mire"><value>0.02</value>'
                '<pdf function="nonsense"><pdf-value>nonsense(1)</pdf-value></pdf>')),
            xml('a distribution in an unindexed entry only', replace(
                model, '<value>0.001</value>',
                '<value>abc</value><pdf function="norm"><pdf-value>norm(mean=1,sd=0.1,group=g1)</pdf-value></pdf>')),
        ]
        self.assertSameImports(cases)


@needs_app
class RandomModels(ParityCase):
    def test_random_models(self):
        self.assertSameImports([xml(f'random model {seed}', random_model(seed)) for seed in range(200)])


@needs_app
class LoadsAsAModel(unittest.TestCase):
    """An imported model is one this package opens, and its own checks pass
    on the ones the application's tests build and run."""

    def test_imported_models_load_and_pass_check(self):
        wanted = {
            'fixture', 'real shapes', 'transport', 'saturation false', 'probabilistic settings',
            'described', 'nuclides in moles', 'intersection materials to nuclides',
            'intersection nuclides to materials', 'intersection named', 'interface one source',
            'interface ADD', 'interface into a transfer', 'interface into a parameter',
            'interface end to end', 'material lists marked', 'output listed', 'AUTO both ends', 'abs-tol',
            'dydt', 'expression with arguments', 'empty discrete times', 'scenarios marked',
        }
        cases = [c for c in run_js_cases() if c.label in wanted]
        self.assertEqual(len(cases), len(wanted))
        for case in cases:
            with self.subTest(case=case.label):
                result = import_model_xml(case.payload, file_name=case.file_name, version=case.version)
                m = kp.Model(result.project)
                self.assertEqual(m.check(), [])
                # And saved and read again, it is the same model.
                self.assertEqual(kp.Model.from_json(m.to_json()).to_json(), m.to_json())

    def test_model_from_eco_is_the_import_opened(self):
        case = next(c for c in run_js_cases() if c.label == 'fixture')
        m = kp.Model.from_eco(case.payload.encode('utf-8'), file_name=case.file_name, version=case.version)
        opened = kp.Model(import_model_xml(case.payload, file_name=case.file_name, version=case.version).project)
        self.assertEqual(m.to_json(), opened.to_json())
        self.assertEqual(m.import_report.counts['compartments'], len(m.compartments))
        self.assertIsNone(kp.Model.new().import_report)
        try:
            import numpy  # noqa: F401 - running needs the engine's dependencies
            import scipy  # noqa: F401
        except ImportError:
            return
        res = m.run()
        self.assertGreater(res.t.size, 1)


class Pieces(unittest.TestCase):
    """The parts that need no application to check."""

    def test_decode_xml_bytes(self):
        self.assertEqual(decode_xml_bytes(b'\xfe\xff\x00A'), 'A')
        self.assertEqual(decode_xml_bytes(b'\xff\xfeA\x00'), 'A')
        self.assertEqual(decode_xml_bytes(b'\xef\xbb\xbfA'), 'A')
        self.assertEqual(decode_xml_bytes(b'\xef\xbb\xbf\xef\xbb\xbfA'), 'A')
        self.assertEqual(decode_xml_bytes(b'A\xc3'), 'A\ufffd')

    def test_xml_errors_count_utf16(self):
        with self.assertRaises(XMLError) as caught:
            parse_xml('<a>\U0001F600</b>')
        self.assertEqual(caught.exception.position, 9)
        self.assertEqual(parse_xml('<a x="1" x="2"><![CDATA[&amp;]]>&amp;</a>').text, '&amp;&')

    def test_number(self):
        for text, want in [('', 0.0), (' 12 ', 12.0), ('0x1A', 26.0), ('.5', 0.5), ('5.', 5.0),
                           ('-Infinity', float('-inf')), ('\xa012\xa0', 12.0)]:
            self.assertEqual(maps.to_number(text), want, text)
        for text in ['-0x1A', '1e', '.', 'infinity', '1_000', '\x1c12', 'NaN', '0x']:
            self.assertNotEqual(maps.to_number(text), maps.to_number(text), text)

    def test_rounding(self):
        self.assertEqual(maps.round_significant(1000500, 4), 1001000)
        self.assertEqual(maps.round_significant(1.25, 2), 1.3)
        self.assertEqual(maps.to_exponential(1001000.0), '1.001e+6')
        self.assertEqual(maps.js_round(-2.5), -2)
        self.assertEqual(maps.js_round(0.49999999999999994), 0)
        self.assertEqual(maps.iso_date(1621966224401), '2021-05-25')

    def test_the_rewrite_skips_only_pairs_that_cannot_match(self):
        # The application searches every text for every pair; the port leaves
        # out the pairs that cannot match (see `_Candidates`). The same
        # answer, cascades included (`k-1` -> `k_1` -> `k_1_1`), on random
        # names built to collide.
        from kompartment.importers.eco import IDENT_CHAR, _NAME_PART, _Candidates

        def scan(pairs, text, order):
            out = text
            for j in order:
                frm, to = pairs[j]
                at = 0
                while True:
                    i = out.find(frm, at)
                    if i == -1:
                        break
                    end = i + len(frm)
                    if all(c is None or not _NAME_PART.fullmatch(c)
                           for c in (out[i - 1] if i else None, out[end] if end < len(out) else None)):
                        out = out[:i] + to + out[end:]
                        at = i + len(to)
                    else:
                        at = end
            return out

        rnd = random.Random(7)
        atoms = ['k', '1', 'k_1', 'a', 'b', 'x.y', 'A', '_', 'soil', 'Deep']
        seps = ['-', ' ', '.', '_', '+', '(', ')', ',', '']

        def name():
            return ''.join(rnd.choice(atoms) + rnd.choice(seps) for _ in range(rnd.randint(1, 3))).strip()

        def ident():
            return (''.join(rnd.choice('k1_abxyA') for _ in range(rnd.randint(1, 5)))
                    + rnd.choice(['', '.k_1', '_1', '.a']))

        cascades = 0
        for _ in range(3000):
            pairs = []
            for _ in range(rnd.randint(1, 8)):
                frm = name()
                to = rnd.choice([ident(), re.sub('[- ]', '_', frm), 'k_1', 'k_1_1', 'x.y'])
                if frm and frm != to and IDENT_CHAR.search(frm) and re.fullmatch('[A-Za-z0-9_.]+', to) \
                        and (frm, to) not in pairs:
                    pairs.append((frm, to))
            pairs.sort(key=lambda p: -maps.js_len(p[0]))
            if not pairs:
                continue
            candidates = _Candidates(pairs)
            for _ in range(5):
                text = rnd.choice(['', ' ', '(']).join(
                    rnd.choice([p[0] for p in pairs] + [name(), ident(), '+', ' ', '*'])
                    for _ in range(rnd.randint(1, 6)))
                whole = scan(pairs, text, range(len(pairs)))
                self.assertEqual(scan(pairs, text, candidates.of(text)), whole, (pairs, text))
                cascades += whole != scan(pairs, text, [j for j in range(len(pairs)) if pairs[j][0] in text])
        self.assertGreater(cascades, 10, 'the random names made no cascades to test')

    def test_collation(self):
        words = ['a_', 'a0', 'aA', 'aa', 'a', 'A', '_a', 'B', 'b', 'Ab', 'aB', 'AB', 'ab', 'L_1', 'L1', 'L10',
                 'L2', 'Z9', 'z_', '__', '_', '_0', '0', 'Nuclides', 'Landscape_objects', 'nuclides']
        # What Node's localeCompare gave for these, en-US.
        node = ['_', '__', '_0', '_a', '0', 'a', 'A', 'a_', 'a0', 'aa', 'aA', 'ab', 'aB', 'Ab', 'AB', 'b', 'B',
                'L_1', 'L1', 'L10', 'L2', 'Landscape_objects', 'nuclides', 'Nuclides', 'z_', 'Z9']
        self.assertEqual(sorted(words, key=maps.collation_key), node)


if __name__ == '__main__':
    unittest.main()
