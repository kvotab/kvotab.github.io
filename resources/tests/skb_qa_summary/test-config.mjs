/*
  The rules of resources/js/skb-qa-config.mjs, run in Node on small TOML
  texts read with the page's own copy of smol-toml:

      node resources/tests/skb_qa_summary/test-config.mjs

  Exit status is 0 when every check passes.
*/
import { parse } from '../../../vendors/js/smol-toml-1.9.0/index.js';
import * as C from '../../js/skb-qa-config.mjs';

let failed = 0;
function check(ok, what, detail) {
  console.log(`${ok ? 'ok   ' : 'FAIL '} ${what}${ok ? '' : `\n      ${JSON.stringify(detail)}`}`);
  if (!ok) failed++;
}
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

const LINK = `
info = 'linked files'
[base]
    files = ['alpha', 'beta', 'gamma']
[variant]
    init_file = 'base'
    skip = ['beta']
    add = ['delta']
[deeper]
    init_file = 'variant'
    skip = 'gamma'
    add = 'alpha_det'
[skipper]
    init_file = 'base'
    skip = ['zeta']
    add = ['alpha']
[orphan]
    init_file = 'nowhere'
[loop_a]
    init_file = 'loop_b'
[loop_b]
    init_file = 'loop_a'
[odd]
    init_file = 'constructor'
`;
const DATA = `
info = 'data files'
[alpha]
    path = 'base_case'
[beta]
    path = 'base_case'
    sheet_names = 'nearfield'
[gamma]
    path = 'other'
    raw_path = 'HYDRO'
    flows = ['Inflow', 'Outflow']
[delta]
    path = 'other/report'
    sheet_names = ['a', 'b']
[inventory]
    path = 'base_case'
    raw_path = 'INVENTORY'
[well]
    path = 'base_case'
    raw_path = 'DRILLED_WELL'
    file_name = 'Well.xlsx'
[unused]
    path = 'other'
`;
const link = C.definitions(parse(LINK));
const data = C.definitions(parse(DATA));

// Input sets
check(!('info' in link) && Object.keys(link).length === 8, 'link.toml: the tables are the sets, info is not one', Object.keys(link));
check(same(C.setSources(link, 'base').sources, ['alpha', 'beta', 'gamma']), 'a set lists its files');
check(same(C.setSources(link, 'variant').sources, ['alpha', 'gamma', 'delta']), 'init_file, then skip, then add');
const deeper = C.setSources(link, 'deeper');
check(same(deeper.sources, ['alpha', 'delta', 'alpha_det']) && same(deeper.steps.map((s) => s.set), ['base', 'variant', 'deeper']),
  'a chain is followed to its start, a single string is a list of one', deeper);
const skipper = C.setSources(link, 'skipper');
const own = skipper.steps[skipper.steps.length - 1];
check(same(own.skipAbsent, ['zeta']) && same(own.addPresent, ['alpha']), 'a skip of what is not there, an add of what is', own);
check(same(C.setSources(link, 'orphan').errors, ['orphan is built on nowhere, which link.toml does not define']), 'an unknown init_file is an error');
check(C.setSources(link, 'loop_a').errors[0] === 'loop_a → loop_b → loop_a comes back round to itself', 'a loop of init_files is an error, not a hang');
check(same(C.setSources(link, 'odd').errors, ['odd is built on constructor, which link.toml does not define']),
  'a set called "constructor" is a name, not the object\'s constructor');

// Data files
const alpha = C.dataSource(data, 'alpha');
check(alpha.workbook === 'base_case/alpha.xlsx' && alpha.sheets === null && alpha.raw === null, 'a data file is <path>/<name>.xlsx, all sheets', alpha);
check(same(C.dataSource(data, 'beta').sheets, ['nearfield']) && same(C.dataSource(data, 'delta').sheets, ['a', 'b']), 'sheet_names, one or several');
const gamma = C.dataSource(data, 'gamma');
check(gamma.workbook === 'other/gamma.xlsx' && gamma.raw === 'HYDRO', 'a data file with raw data still has its workbook looked for', gamma);
check(C.dataSource(data, 'well').raw === 'DRILLED_WELL/Well.xlsx', 'a file_name is the raw data file');
const det = C.dataSource(data, 'alpha_det');
check(det.name === 'alpha' && det.workbook === 'base_case/alpha.xlsx', 'a _det data file is read from its own workbook', det);
check(C.dataSource(data, 'nope').entry === null && C.dataSource(data, 'constructor').entry === null, 'an undefined data file has no entry');

// Finding the workbook among those read
const loaded = ['sfr/excel/base_case/alpha.xlsx', 'copy/base_case/alpha.xlsx', 'excel/other/report/delta.xlsx', 'excel/BASE_CASE/Beta.xlsx'];
check(C.findWorkbook('base_case/alpha.xlsx', loaded, 'sfr/config').path === 'sfr/excel/base_case/alpha.xlsx', 'the Excel folder beside the config folder first');
check(same(C.findWorkbook('base_case/alpha.xlsx', loaded, 'sfr/config').others, ['copy/base_case/alpha.xlsx']), 'and the other copies are named');
check(C.findWorkbook('base_case/beta.xlsx', loaded, 'config').path === 'excel/BASE_CASE/Beta.xlsx', 'case is ignored when nothing matches exactly');
check(C.findWorkbook('base_case/zeta.xlsx', loaded, 'config').path === null, 'none, when none was read');
check(C.findWorkbook('case/alpha.xlsx', loaded, '').path === null, 'a match is whole folder names, not the end of one');

// Configurations
const files = [
  { path: 'cfg/link.toml', name: 'link.toml', data: parse(LINK) },
  { path: 'cfg/data.toml', name: 'data.toml', data: parse(DATA) },
  { path: 'cfg/CC010.toml', name: 'CC010.toml', data: parse(`info = 'ten'\nparameter_files = 'variant.h5'\nbase_cc = 'CC002'\n[biosphere]\nparameter_files = ['base.h5']\nsource_cc = 'CC099'`) },
  { path: 'cfg/CC002.toml', name: 'CC002.toml', data: parse(`info = 'two'\nparameter_files = ['Legacy.h5', 'base.h5']`) },
  { path: 'cfg/CC003.toml', name: 'CC003.toml', data: parse(`info = 'three'`) },
  { path: 'cfg/bad.toml', name: 'bad.toml', error: 'Invalid TOML' },
  { path: 'loose/CC900.toml', name: 'CC900.toml', data: parse(`parameter_files = 'base.h5'`) }
];
const configs = C.buildConfigs(files);
const cfg = configs.find((c) => c.folder === 'cfg');
const loose = configs.find((c) => c.folder === 'loose');
check(same(cfg.cases.map((c) => c.name), ['CC002', 'CC003', 'CC010']) && cfg.errors.length === 1, 'cases in numeric order, a broken file kept as an error');
check(loose.link?.borrowed && loose.data?.borrowed, 'a folder with cases alone uses the only link.toml and data.toml read');
const ten = C.caseInputs(cfg, cfg.cases[2]);
check(same(ten.files.map((f) => [f.file, f.domain, f.set]), [['variant.h5', null, 'variant'], ['base.h5', 'biosphere', 'base']]),
  'a case\'s parameter files, its own and its domains\'', ten.files);
check(same(ten.data.map((d) => d.source), ['alpha', 'gamma', 'delta', 'beta']), 'its data files, each once, in the order first met');
const two = C.caseInputs(cfg, cfg.cases[0]);
check(two.files[0].set === null && two.files[1].set === 'base', 'a parameter file no set builds has no set');
check(same(C.caseReferences(cfg.cases[2].toml), [{ key: 'base_cc', domain: null, name: 'CC002' }, { key: 'source_cc', domain: 'biosphere', name: 'CC099' }]),
  'base_cc and a domain\'s source_cc are the cases it takes results from');

// Checks
const checks = C.configChecks(cfg, ['excel/base_case/alpha.xlsx', 'excel/base_case/beta.xlsx']);
const texts = checks.map((c) => c.text);
const has = (part) => texts.some((t) => t.includes(part));
check(checks[0].level === 'error' && texts[0].startsWith('cfg/bad.toml could not be read'), 'errors first, a broken file among them');
check(has('Legacy.h5 is not built by link.toml') && checks.find((c) => c.text.includes('Legacy.h5')).cases[0] === 'CC002', 'a parameter file no set builds, with its cases');
check(has('CC003 names no parameter file.'), 'a case with no parameter file');
check(has('source_cc = CC099, which is not among the cases read'), 'a case named that was not read');
check(has('Input set orphan: orphan is built on nowhere'), 'an unknown init_file');
check(has('Input set skipper skips zeta, which base does not have.') && has('Input set skipper adds alpha, which it has already.'), 'skip and add that do nothing');
check(has('3 data file(s) are in no input set: inventory, well, unused.'), 'data files in no input set', texts);
check(has('2 workbook(s) in data.toml were not among those read: other/report/delta.xlsx, other/unused.xlsx.'),
  'workbooks not read are named; those read, and those of data files with raw data, are not', texts);
check(!C.configChecks(cfg, null).some((c) => c.text.includes('were not among those read')), 'nothing is said about workbooks when none were read');
check(C.configChecks({ folder: '', link: null, data: null, cases: cfg.cases, errors: [] }, null).filter((c) => c.level === 'error').length === 2,
  'cases without link.toml and data.toml say so');

// Values in a line
check(C.shortValue(Array.from({ length: 20 }, (_, i) => i * 5)) === '20 values, 0 … 95', 'a long list is counted');
check(C.shortValue(['Silo', '1BTF']) === 'Silo, 1BTF' && C.shortValue({ flow: 'old_net', endpoints: ['release'] }) === 'flow old_net · endpoints release', 'short lists and tables');

console.log(failed ? `\n${failed} failed` : '\nall passed');
process.exit(failed ? 1 : 0);
