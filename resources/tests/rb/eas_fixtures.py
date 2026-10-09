"""Ecolego assessments (.eas) written for the tests, in the shapes Ecolego 6
and Ecolego 5 wrote them: test-eas.py opens them in the page, and
rb-vscode/test/test-vscode.py in VS Code. Nothing in them is anyone's data.

    runs_e6()   Ecolego 6: a current run and an archived one ("Base case"),
                each in <GUID>.dta, the index lists named by the run, the first
                index fastest; outputs of every kind -- not indexed, indexed by
                one list and by two, a parameter, a transfer (its flux), a
                sub-system's row, one listed but not kept, one whose numbers do
                not fit, and one whose name is markup -- and a third run listed
                whose numbers were not kept
    old_e5()    Ecolego 5: one run in results.dta, written with backslashes,
                the index lists named only by model.xml, the last index fastest
    prob_e6()   a probabilistic run of four realisations
    bomb()      simulation.xml claims 64 bytes and unpacks to 200,000

Every value written encodes where it belongs (value()): the index of each list,
the time and the realisation, each in its own decimal place, so a value read
back from the wrong cell, time or realisation is a different number.
"""
import io
import struct
import zipfile


NUCLIDES = ['Cs-137', 'I-129', 'U-238']
CROPS = ['Cereals', 'Roots']
ELEMENTS = ['Cs', 'I']
ODD = ['A/B', '.']                  # a slash, and a name HDF5 cannot have
HOSTILE = '<img src=x onerror="__ran=1">'   # no dot: a dot separates a sub-system from its blocks


def value(k, pos, ti, sim=0):
    """What output k holds at cell `pos`, time ti, realisation sim: each part
    in its own decimal place, all exact in binary."""
    v = 1000 * k + ti / 8 + 10000 * sim
    for j, p in enumerate(pos):
        v += p * (100 if j == 0 else 10)
    return v


def cells_in_file_order(sizes, last_fastest):
    """The positions of an output's cells, in the order a result file holds them."""
    total = 1
    for n in sizes:
        total *= n
    out = []
    for c in range(total):
        pos = [0] * len(sizes)
        rest = c
        order = range(len(sizes) - 1, -1, -1) if last_fastest else range(len(sizes))
        for j in order:
            pos[j] = rest % sizes[j]
            rest //= sizes[j]
        out.append(pos)
    return out


def guid_bytes(guid):
    """The sixteen bytes a block header starts with: the low half first."""
    hexed = guid.replace('-', '')
    return bytes.fromhex(hexed[16:]) + bytes.fromhex(hexed[:16])


def result_file(S, nt, blocks):
    """A result file: the header, then a block per output (guid, doubles)."""
    out = [struct.pack('>ii', S, nt) + bytes(1024 - 8)]
    for guid, numbers in blocks:
        data = struct.pack('>%dd' % len(numbers), *numbers)
        out.append(guid_bytes(guid) + struct.pack('>q', len(data)) + bytes(40) + data)
    return b''.join(out)


def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


class Run:
    """One run's outputs: what simulation.xml says of each, and its numbers."""

    def __init__(self, S, times, last_fastest):
        self.S = S
        self.times = times
        self.last_fastest = last_fastest
        self.xml = []
        self.blocks = []
        self.n = 0

    def guid(self):
        self.n += 1
        return '%08X-0000-4000-8000-%012X' % (0x5EED0000 + self.n, self.n)

    def time(self, unit, every_row=True):
        g = self.guid()
        self.xml.append(f'<output-info id="time" guid="{g}" index-lists=""><time-dependent>true</time-dependent>'
                        f'<output-units><output-unit indices="">{unit}</output-unit></output-units></output-info>')
        rows = []
        for sim in range(self.S):
            rows += self.times if (every_row or sim == 0) else [0.0] * len(self.times)
        self.blocks.append((g, rows))

    def output(self, k, oid, kind, lists=(), sizes=(), unit='', timed=True, inline=None, units=None,
               kept=True, size_off=0):
        """`lists` names the index lists (Ecolego 6); `inline` writes their members
        instead (Ecolego 5), and `units` a unit per cell."""
        g = self.guid()
        parts = [f'<output-info id="{esc(oid)}" type="SIMULATION" guid="{g}"'
                 + (f' index-lists="{",".join(lists)}">' if inline is None else '>')]
        if kind:
            parts.append(f'<block-type>{kind}</block-type>')
        if timed:
            parts.append('<time-dependent>true</time-dependent>')
        if inline is not None:
            parts.append('<index-lists>' + ''.join(
                '<index-list>' + ''.join(f'<index>{esc(m)}</index>' for m in members) + '</index-list>'
                for members in inline) + '</index-lists>')
        if units:
            keyed = lambda pos: ' '.join('index-%d="%d"' % (j + 1, p) for j, p in enumerate(pos))
            parts.append('<output-units>' + ''.join(
                f'<output-unit {keyed(pos)}>{u}</output-unit>' for pos, u in units) + '</output-units>')
        else:
            parts.append(f'<output-units><output-unit indices="">{unit}</output-unit></output-units>')
        parts.append('</output-info>')
        self.xml.append(''.join(parts))
        if not kept:
            return
        per = len(self.times) if timed else 1
        order = cells_in_file_order(list(sizes), self.last_fastest)
        numbers = [value(k, pos, ti, sim) for sim in range(self.S) for ti in range(per) for pos in order]
        self.blocks.append((g, numbers[:len(numbers) - size_off] if size_off else numbers))

    def subsystem(self, oid):
        self.xml.append(f'<output-info id="{oid}" guid="{self.guid()}" index-lists="">'
                        '<block-type>Sub-system</block-type><sub-system>true</sub-system></output-info>')

    def dta(self):
        return result_file(self.S, len(self.times), self.blocks)


TIMES = [0.0, 1.0, 10.0, 100.0]


def context(guid, info, lists, run, archive=False):
    attrs = (f' guid="{guid}"' if guid else '') + (' archive="true"' if archive else '')
    index_lists = ''.join(f'<index-list name="{n}">' + ''.join(f'<index>{esc(m)}</index>' for m in members)
                          + '</index-list>' for n, members in lists)
    return (f'<simulation-context{attrs}><simulation-info>{info}</simulation-info>'
            + (f'<index-lists>{index_lists}</index-lists>' if lists else '')
            + '<simulation-outputs>' + ''.join(run.xml) + '</simulation-outputs></simulation-context>')


def simulation_xml(contexts):
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<simulation-model>'
            + ''.join(contexts) + '</simulation-model>').encode('utf-8')


def archive(entries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in entries:
            z.writestr(name, data)
    return out.getvalue()


E6_LISTS = [('Radionuclides', NUCLIDES), ('Crops', CROPS), ('Elements', ELEMENTS), ('Odd', ODD)]
CURRENT, ARCHIVED, UNKEPT = ('C0FFEE00-1111-4222-8333-444455556666', 'A5C4E7ED-1111-4222-8333-444455556666',
                             'DEADBEEF-1111-4222-8333-444455556666')


def runs_e6():
    current = Run(1, TIMES, last_fastest=False)
    current.time('Years')
    current.subsystem('Sys')
    current.output(1, 'Sys.Flow', 'Expression', unit='m^3/year')
    current.output(2, 'Sys.Inventory', 'Compartment', ['Radionuclides'], [3], unit='Bq')
    current.output(3, 'Bio.Dose_Crops', 'Expression', ['Radionuclides', 'Crops'], [3, 2], unit='Sv/year')
    current.output(4, 'Sys.Kd', 'Parameter', ['Elements'], [2], unit='m^3/kg', timed=False)
    current.output(5, 'Sys.Leach', 'Transfer', ['Radionuclides'], [3], unit='Bq year^-1')
    current.output(6, 'Sys.Odd', 'Expression', ['Odd'], [2], unit='-')
    current.output(7, 'Sys.NotKept', 'Expression', unit='Bq', kept=False)
    current.output(8, 'Sys.Broken', 'Expression', ['Radionuclides'], [3], unit='Bq', size_off=1)
    current.output(9, 'Sys.' + HOSTILE, 'Expression', unit='Bq')
    archived = Run(1, TIMES, last_fastest=False)
    archived.time('Years')
    archived.output(11, 'Sys.Flow', 'Expression', unit='m^3/year')
    archived.output(12, 'Sys.Inventory', 'Compartment', ['Radionuclides'], [3], unit='Bq')
    unkept = Run(1, TIMES, last_fastest=False)
    unkept.time('Years')
    info = ('<simulation-info-type>DETERMINISTIC</simulation-info-type><start-time>0.0</start-time>'
            '<end-time>100.0</end-time><time-unit><![CDATA[Years]]></time-unit><date>{date}</date>'
            '<java-solver>java-ode15s</java-solver><abs-error-tolerance>1.0E-6</abs-error-tolerance>'
            '<rel-error-tolerance>1.0E-4</rel-error-tolerance>{name}')
    xml = simulation_xml([
        context(CURRENT, info.format(date=1700000000000, name=''), E6_LISTS, current),
        context(ARCHIVED, info.format(date=1600000000000, name='<simulation-name>Base case</simulation-name>'),
                E6_LISTS, archived, archive=True),
        # A run listed whose numbers were not kept: not offered.
        context(UNKEPT, info.format(date=1500000000000, name='<simulation-name>Gone</simulation-name>'),
                E6_LISTS, unkept, archive=True),
    ])
    return archive([
        ('.version', b'version=6.0\r\ntrack-changes=false\r\n'),
        ('model.xml', b'<?xml version="1.0"?><data-model/>'),
        ('simulation.xml', xml),
        (f'simulation/results/{CURRENT}.dta', current.dta()),
        (f'simulation/results/{ARCHIVED}.dta', archived.dta()),
        ('simulation/results/results.dta', bytes(1024)),
    ])


def old_e5():
    run = Run(1, TIMES, last_fastest=True)
    run.time('y')
    units = [(pos, 'Sv/year' if pos[1] == 0 else 'mSv/year')
             for pos in cells_in_file_order([3, 2], last_fastest=True)]
    run.output(3, 'Bio.Dose_Crops', None, inline=[NUCLIDES, CROPS], sizes=[3, 2], units=units)
    run.output(2, 'Sys.Inventory', None, inline=[NUCLIDES], sizes=[3],
               units=[([p], 'Bq') for p in range(3)])
    run.output(4, 'Sys.Mystery', None, inline=[['p', 'q']], sizes=[2], units=[([0], 'kg'), ([1], 'kg')])
    run.output(5, 'Sys.CropOnly', None, inline=[CROPS], sizes=[2], units=[([0], 'kg'), ([1], 'kg')])
    info = ('<simulation-info-type>Deterministic</simulation-info-type><simulation-name></simulation-name>'
            '<simulation-use-dates>false</simulation-use-dates>')
    xml = simulation_xml([context(None, info, [], run)])
    lists = [('Materials', NUCLIDES), ('Radionuclides', NUCLIDES), ('Crops', CROPS)]
    model = ('<?xml version="1.0" encoding="UTF-8"?><data-model><index-list-model>'
             + ''.join(f'<index-list name="{n}">' + ''.join(f'<index name="{m}"><id>{m}</id></index>' for m in members)
                       + '</index-list>' for n, members in lists)
             + '</index-list-model>'
             '<component name="Inventory" type="compartment" index-lists="Radionuclides"><id>Sys.Inventory</id></component>'
             '<component name="Dose_Crops" type="expression" index-lists="Radionuclides,Crops"><id>Bio.Dose_Crops</id></component>'
             '</data-model>').encode('utf-8')
    return archive([
        ('.version', b'version=5.0\r\ntrack-changes=false\r\n'),
        ('model.xml', model),
        ('simulation.xml', xml),
        ('simulation\\results\\results.dta', run.dta()),
    ])


PROB = 'B0B0B0B0-1111-4222-8333-444455556666'


def prob_e6():
    run = Run(4, TIMES[:3], last_fastest=False)
    run.time('year')
    run.output(2, 'Sys.Inventory', 'Compartment', ['Radionuclides'], [3], unit='Bq')
    run.output(4, 'Sys.Kd', 'Parameter', unit='m^3/kg', timed=False)
    info = ('<simulation-info-type>PROBABILISTIC</simulation-info-type><start-time>0.0</start-time>'
            '<end-time>10.0</end-time><time-unit>year</time-unit><date>1700000000000</date>'
            '<simulation-inputs><simulation-input>Sys.Kd</simulation-input></simulation-inputs>')
    return archive([
        ('.version', b'version=6.0\r\n'),
        ('simulation.xml', simulation_xml([context(PROB, info, E6_LISTS, run)])),
        (f'simulation/results/{PROB}.dta', run.dta()),
    ])


def bomb():
    """simulation.xml claims 64 bytes and unpacks to 200,000."""
    data = bytearray(archive([('simulation.xml', b'<' + b' ' * 199999), ('simulation/results/x.dta', bytes(1100))]))
    at = data.find(b'PK\x03\x04')
    struct.pack_into('<I', data, at + 22, 64)
    at = data.find(b'PK\x01\x02')
    struct.pack_into('<I', data, at + 24, 64)
    return bytes(data)


def expected(k, sizes, pos_names, times, S=1):
    """The values a series should hold, as the page writes them: time by time,
    a column per realisation."""
    return [value(k, pos_names, ti, sim) for ti in range(len(times)) for sim in range(S)]
