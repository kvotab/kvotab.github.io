# Kompartment for Python

Read a Kompartment model into Python, edit it through documented methods, and
write it back as a project file the application opens. For the models you would
rather generate than draw: a chain of fifty compartments, a parameter table read
from a spreadsheet, the same edit made to twenty variants of an assessment.

```python
import kompartment as kp

m = kp.Model.new('Two boxes')
m.add_nuclides(['Cs-137', 'Sr-90'])
m.add_compartment('Soil', initial='1e10')
m.add_compartment('Well')
m.add_parameter('k', 0.05, unit='1/year')
m.add_transfer('Soil', 'Well', rate='k')
m.save('two-boxes.json')
```

Python 3.9 or later, and nothing else. Node.js is only needed for
`Model.validate()`, which runs the application's own checks on a model.

## Installing

From this directory:

```sh
pip install -e .
```

or put this directory on `PYTHONPATH`. The package is `kompartment`.

## Reading and writing

```python
m = kp.Model.load('examples/biosphere.json')   # .json, .json.gz or .zip
m = kp.Model.from_json(text)
m = kp.Model.from_dict(data)                    # the dict is copied
m = kp.Model.new('Name', 'What it is')

m.save('out.json')                              # or .json.gz, or .zip
text = m.to_json()
data = m.to_dict()
```

Reading a file brings it into the shape Kompartment works on, as the application
does when it opens one: older key spellings renamed, the two built-in material
lists present, every block's dimensions written down, transfer ends written as
qualified names, and the units that follow from the model filled in. A file the
application saved comes back byte for byte. `normalise=False` leaves a
dictionary exactly as it is.

A `Model` holds the project exactly as the file does, as `m.raw`. Every block,
index list and setting is a view onto that dictionary, so nothing is copied and
what the objects show is what is saved.

## Blocks

| Add | Block |
|---|---|
| `add_compartment(name, initial, ...)` | A state variable holding an inventory |
| `add_transfer(source, target, rate, ...)` | A flux between compartments; either end may be `None` |
| `add_inflow(target, rate, ...)` | A source term from outside the model |
| `add_parameter(name, value, ...)` | A constant, and the distribution a probabilistic run draws it from |
| `add_expression(name, equation, ...)` | An algebraic quantity |
| `add_lookup(name, points, ...)` | A value following a series of points, at the clock or at an argument |
| `add_function(name, parameters, equation)` | Arithmetic called from any equation |
| `add_index_reduction(name, target, over=...)` | One block reduced along one of its index lists |
| `add_block_reduction(name, targets, ...)` | Several blocks combined element-wise |
| `add_min_max`, `add_running_mean`, `add_snapshot`, `add_delay`, `add_trigger` | The blocks that remember |
| `add_farfield(name, **settings)` | A far-field pathway (FARFCOMP) |
| `add_waste_package(name, failure=..., **settings)` | Waste packages that fail and release |
| `add_event(name, timing=..., ...)` | A disruptive event, with fail and move actions |
| `add_transport(name, number=...)` | A chain of N compartments drawn as two |

Every `add_` method takes `system=` for the sub-system the block goes in, and
most take `unit=`, `comment=`, `index_lists=` and `position=(x, y)`. Leave the
name out and the block is called what the application would call it (`C`,
`C1`, ...). A new compartment, transfer or expression is indexed by the
radionuclides when the model has any; a parameter or a lookup table is not.

Blocks are reached by qualified name, `system.name`:

```python
soil = m['Soil']                  # or m.block('Soil'), or m.get('Soil') for None
m['NearField.Water']
m.compartments, m.transfers, m.parameters, ...   # every block of a kind
m.blocks(kind='parameter', system='NearField')
```

A block's settings are properties, checked as the application checks them:

```python
soil.initial = '1e10'
soil.non_negative = False
m['Soil_Well'].multiply_by_donor = False
m['Q_gw'].interpolation = 'nearest'
m['Rock'].n_f = 40
soil['some_key']                  # any raw value
soil.raw                          # the block's own dictionary
```

A value the application would refuse raises `kp.EditError` on the spot.

### Values per index

A block indexed by one or more index lists holds one value per combination of
their indices. The block-level value is the default; a value set at an index
overrides it there, the most specific match winning.

```python
soil.set_value('5e9', at='Cs-137')                     # one dimension: the index alone
kd.set_value(0.03, at={'Radionuclides': 'Cs-137', 'Object': 'Lake'})
kd.set_value(0.01, at=('Sr-90', 'Mire'))               # one index per dimension, in order
soil.set_entry('Sr-90', initial='2', abstol=1e-3)      # several keys at once
soil.value_at('Cs-137')
soil.clear_value('Cs-137')
soil.combinations()                                    # every index combination, in solver order
```

### Distributions

```python
from kompartment import distributions as dist

m['k'].distribution = dist.log_triangular(0.01, 0.1, 0.05)
m['Kd'].set_distribution('norm', at='Cs-137', mean=0.05, sd=0.01, trmin=0)
m['Q'].set_point_distribution(1, 'unif', min=1.5, max=2.5)
```

The kinds are Kompartment's: `unif`, `triang`, `dtriang`, `norm`, `logu`,
`logt`, `logdt`, `Logn4`, `logn`, `logn5` and `pg` (a list of values), each
with truncation by value or by percentile and an optional correlation group.

## Edits that reach across the model

```python
m.rename_block('Soil', 'Topsoil')
m.move_block('Topsoil', 'NearField')
m.delete_block('Well')
m.delete_blocks(['A', 'B'])
m.set_connection_end('Soil_Well', 'to', 'Lake')
m.set_dimensions('Soil', ['Radionuclides', 'Object'])
```

These follow the change through every reference the way the application's
editor does: every equation (written from wherever it is written), transfer
ends, reduction targets, trigger names, event actions, values keyed by a
compartment's or a transfer's name, and the diagram. They refuse what it
refuses, and the error says why:

- a delete while something still reads the block (a compartment's transfers
  and inflows go with it);
- a rename or move whose new spelling would mean a different block from where
  an equation is written;
- a name that is taken, reserved, or not a name.

A move takes a compartment's outgoing transfers and inflows with it, since a
transfer lives in its donor's sub-system. Changing a compartment's dimensions
brings its transfers, the transport it is part of and the reductions that read
it along.

## Index lists, materials and decay

```python
m.add_index_list('Object', ['Lake', 'Mire', 'Forest'])
m.add_index_list('Wetland', ['Mire'], subset_of='Object')
m.add_index_list('Kind', ['Water', 'Land'], mapping_to='Object',
                 pairs={'Lake': 'Water', 'Mire': 'Land', 'Forest': 'Land'})
m.add_scenarios(['Present', 'Warmer'])
m.scenario = 'Warmer'

lst = m.index_list('Object')
lst.add_index('Bog')
lst.rename_index('Bog', 'Fen')     # values, sub-sets, mappings and K[Bog] in equations follow
lst.set_enabled('Fen', False)
lst.remove_index('Fen')

m.add_nuclides(['U-238', 'U-234', 'Th-230'])   # half-lives from ICRP 107
m.add_material('Water', unit='m3')             # a material that does not decay
m.set_half_life('Xx-1', 12.5)
m.decay_chains                                 # the pairs in force
m.add_decay_pair('U-238', 'U-234', 1)          # the first edit writes the chains down
m.reset_decay_chains()                         # follow the nuclides again
m.decay_unit = 'mol'
```

Two lists are built in and always present: the material catalogue
(`Contaminants`) and the radionuclides (`Radionuclides`), a sub-set of it.
Adding a radionuclide adds the material; removing one removes it. `Elements`,
`Compartments` and `Transfers` are worked out from the model and are never
stored.

## Sub-systems and transports

```python
m.add_system('NearField')
m.add_system('Buffer', parent='NearField')
m.rename_system('NearField', 'Near')
m.move_system('Near.Buffer', '')
m.delete_system('Near')                       # its contents move out
m.delete_system('Near', contents='delete')
m.set_system_enabled('Near', False)

tube = m.add_transport('Tube', number='20')
m.add_transfer('Soil', tube)                  # into its Begin
m.add_transfer(tube, 'Lake')                  # out of its End
m.add_transport_operation(tube, operation='mean')
```

## Settings, the diagram, reviews

```python
sim = m.simulation
sim.update(end_time=1e6, rtol=1e-6, abstol=1e-12, solver='radau5')
sim.spacing = 'series'
sim.add_output_series('times', times=[1e3, 1e4, 1e5])

m.view.show_parameters = True
m['Soil'].position = (120, 80)
m.add_shape('sticky', 40, 40, text='Check this')
m.add_derived('Peak dose', 'max', 'Dose [Cs-137]')

m.review_tracking = True
m.record_review('Kd', by='A. Author', reviewer='A. Reviewer')
m.review_status()                             # approved, stale, review or none, per block
```

## Checking a model

```python
m.check()       # what this package can see: names, ends, references, lists, values, settings
m.validate()    # Kompartment's own checks, through Node: raises kp.ValidationError
```

`validate()` loads the model as the application opens a file, checks every
equation with the editor's checker, and builds it as a run would. It needs
`node` on the path and the Kompartment sources: this package's own repository,
or the `src` directory named by `KOMPARTMENT_SRC`.

## What follows from the model

A transfer's unit follows from its donor and the time unit, a flux's dimensions
from its two ends, a transport's from what it is connected to. The application
brings these up to date after every edit. Here `m.settle()` does it, and it runs
by itself whenever the model is written out or checked.

## Where this differs from the application

- A transfer's availability operands (`limit`, `top`, `bottom`) are followed
  by a rename and counted as references by a delete. The application's editor
  does not follow them yet.
- A sub-system path is written once in `systems`. The application can write
  one twice after a sub-system is renamed; both read the same.

## Tests

```sh
cd tests && python -m unittest
```

With Node available, `test_app_parity.py` runs the application's own code
beside this package — every bundled example opened, forty-odd edits, the decay
chains, the review stamps, 2,200 numbers formatted — and compares the results as
JSON text, key order included. `tools/gen_data.mjs` writes the ICRP 107 table
and the reserved names from the application's sources; `--check` says whether
they are current.

## Licence

MIT, as Kompartment. See [LICENSE](LICENSE).
