/*
  The calculation cases of skb_qa_summary.html: what the TOML files say, and
  how a case reaches the workbooks its data come from.

  A configuration is the TOML files of one folder. Two of them are special.
  link.toml defines the input sets, each the parameter file <set>.h5 built
  from data files: listed under 'files', or taken from the set named in
  'init_file', then without those in 'skip' and with those in 'add'. A name
  ending in '_det' is the deterministic copy of a data file. data.toml
  defines the data files: the workbook of one is <path>/<name>.xlsx under the
  Excel folder, and 'sheet_names' narrows it to those sheets. One with a
  'raw_path' also has raw data, which may stand in for the workbook. Every
  other TOML file is a calculation case, named by its file. Its
  'parameter_files' (and a domain's own) are parameter files of input sets.

  These are the rules the calculation-case code applies when it builds the
  parameter files and runs a case. Nothing here touches the page, so the
  tests run it in Node.
*/

/* The sections of a case that hold a domain's settings. */
export const DOMAINS = ['nearfield', 'farfield', 'biosphere'];

/* A TOML value as a list: one string is a list of one. */
export function asList(value) {
  if (value == null) return [];
  return Array.isArray(value) ? value.slice() : [value];
}

const isTable = (value) => value != null && typeof value === 'object' && !Array.isArray(value) && !(value instanceof Date);

/*
  The tables of link.toml or data.toml; top-level values such as 'info' are
  not definitions. Kept without a prototype, as the parser keeps every table:
  a set or data file a TOML file calls 'constructor' or '__proto__' is then
  just a name, found only when defined.
*/
export function definitions(parsed) {
  const defs = Object.create(null);
  for (const [name, value] of Object.entries(parsed || {})) if (isTable(value)) defs[name] = value;
  return defs;
}

export function kindOf(fileName) {
  const name = fileName.toLowerCase();
  if (name === 'link.toml') return 'link';
  if (name === 'data.toml') return 'data';
  return 'case';
}

const folderOf = (path) => path.split('/').slice(0, -1).join('/');
const stem = (fileName) => fileName.replace(/\.toml$/i, '');

/*
  The configurations among the TOML files read: one per folder. A folder with
  cases but no link.toml or data.toml uses the one that was read elsewhere,
  when only one was: cases chosen one by one beside the two files picked from
  another folder still resolve.
*/
export function buildConfigs(files) {
  const byFolder = new Map();
  const configOf = (folder) => {
    if (!byFolder.has(folder)) byFolder.set(folder, { folder, link: null, data: null, cases: [], errors: [] });
    return byFolder.get(folder);
  };
  for (const file of files) {
    const config = configOf(folderOf(file.path));
    if (file.error) { config.errors.push(file); continue; }
    const kind = kindOf(file.name);
    if (kind === 'case') config.cases.push({ name: stem(file.name), path: file.path, toml: file.data || {} });
    else config[kind] = { path: file.path, defs: definitions(file.data), info: file.data?.info ?? '' };
  }
  const configs = [...byFolder.values()];
  for (const kind of ['link', 'data']) {
    const found = configs.filter((c) => c[kind]);
    if (found.length !== 1) continue;
    for (const config of configs) if (!config[kind]) config[kind] = { ...found[0][kind], borrowed: true };
  }
  for (const config of configs) config.cases.sort((a, b) => a.name.localeCompare(b.name, 'en', { numeric: true }));
  return configs.filter((c) => c.cases.length || c.link || c.data || c.errors.length);
}

/*
  The data files of an input set, and how they came about: each step is a set
  with what it started from, what it skipped and what it added. Errors are a
  set that is not defined, and a set that comes back round to itself.
*/
export function setSources(linkDefs, setName) {
  const steps = [];
  const errors = [];
  const resolve = (name, seen) => {
    const definition = linkDefs?.[name];
    if (!definition) {
      errors.push(seen.length ? `${seen[seen.length - 1]} is built on ${name}, which link.toml does not define`
        : `link.toml does not define ${name}`);
      return [];
    }
    if (seen.includes(name)) {
      errors.push(`${[...seen, name].join(' → ')} comes back round to itself`);
      return [];
    }
    let sources;
    let base = null;
    if (definition.init_file != null) {
      base = String(definition.init_file);
      sources = resolve(base, [...seen, name]);
    } else {
      sources = asList(definition.files).map(String);
    }
    const skip = asList(definition.skip).map(String);
    const add = asList(definition.add).map(String);
    const kept = sources.filter((source) => !skip.includes(source));
    steps.push({
      set: name, base, files: base ? [] : sources.slice(), skip, add,
      skipAbsent: base ? skip.filter((s) => !sources.includes(s)) : [],
      addPresent: add.filter((a) => kept.includes(a)),
      groups: asList(definition.groups).map(String)
    });
    return kept.concat(add);
  };
  const sources = resolve(setName, []);
  return { sources, steps, errors };
}

/* A '_det' name is the deterministic copy of a data file, built from the same workbook. */
export const dataName = (source, dataDefs) => (dataDefs && source in dataDefs ? source : source.replace(/_det$/, ''));

/*
  Where a data file's data come from: the workbook <path>/<name>.xlsx under
  the Excel folder, and with a 'raw_path' its raw data too. Some raw data
  come beside the workbook and some in its place, so the workbook is looked
  for either way: found, its QC rows count; not found, a data file with raw
  data has them only, and one without lacks its workbook.
*/
export function dataSource(dataDefs, source) {
  const name = dataName(source, dataDefs);
  const entry = dataDefs?.[name];
  if (!entry) return { source, name, entry: null, workbook: null, raw: null, sheets: null };
  const folder = entry.path ? String(entry.path).replace(/^\/+|\/+$/g, '') : '';
  const workbook = `${folder ? `${folder}/` : ''}${name}.xlsx`;
  const rawPath = entry.raw_path != null ? String(entry.raw_path) : null;
  /* The raw data's folder, and the file in it when data.toml names one. */
  const raw = rawPath == null ? null : entry.file_name != null ? `${rawPath}/${entry.file_name}` : rawPath;
  const sheets = entry.sheet_names != null ? asList(entry.sheet_names).map(String) : null;
  return { source, name, entry, workbook, raw, sheets };
}

/*
  The workbook read for a data file, among the paths of those read. The Excel
  folder can arrive on its own (excel/base_case/decay.xlsx), inside the data
  folder (data/excel/...), or as one of its subfolders
  (base_case/decay.xlsx), so a path matches when it ends with the expected
  one. Of several, the one in the Excel folder beside the configuration's
  folder is taken, then one in any folder called excel.
*/
export function findWorkbook(expected, loadedPaths, configFolder) {
  if (!expected) return { path: null, others: [] };
  const lower = expected.toLowerCase();
  const ends = (path, caseless) => {
    const p = caseless ? path.toLowerCase() : path;
    const e = caseless ? lower : expected;
    return p === e || p.endsWith(`/${e}`);
  };
  let found = loadedPaths.filter((path) => ends(path, false));
  if (!found.length) found = loadedPaths.filter((path) => ends(path, true));
  if (!found.length) return { path: null, others: [] };
  const root = folderOf(configFolder || '');
  const beside = `${root ? `${root}/` : ''}excel/${expected}`.toLowerCase();
  const rank = (path) => (path.toLowerCase() === beside ? 0 : path.toLowerCase().endsWith(`excel/${lower}`) ? 1 : 2);
  found.sort((a, b) => rank(a) - rank(b) || a.length - b.length);
  return { path: found[0], others: found.slice(1) };
}

/* The parameter files of a case: its own, then each domain's. */
export function parameterFiles(caseToml) {
  const out = asList(caseToml.parameter_files).map((file) => ({ file: String(file), domain: null }));
  for (const domain of DOMAINS) {
    if (isTable(caseToml[domain])) {
      for (const file of asList(caseToml[domain].parameter_files)) out.push({ file: String(file), domain });
    }
  }
  return out;
}

const setOfFile = (file) => file.replace(/\.h5$/i, '');

/*
  Everything a case uses: its parameter files, the set each comes from, and
  the data files of them all, each once, in the order first met.
*/
export function caseInputs(config, caseFile) {
  const linkDefs = config.link?.defs || Object.create(null);
  const dataDefs = config.data?.defs || Object.create(null);
  const files = parameterFiles(caseFile.toml).map((pf) => {
    const set = setOfFile(pf.file);
    const known = Object.prototype.hasOwnProperty.call(linkDefs, set);
    return { ...pf, set: known ? set : null, ...(known ? setSources(linkDefs, set) : { sources: [], steps: [], errors: [] }) };
  });
  const seen = new Set();
  const data = [];
  for (const pf of files) {
    for (const source of pf.sources) {
      if (seen.has(source)) continue;
      seen.add(source);
      data.push(dataSource(dataDefs, source));
    }
  }
  return { files, data };
}

/* The cases a case names: the base case and the cases a domain takes its source from. */
export function caseReferences(caseToml) {
  const refs = [];
  if (caseToml.base_cc != null) refs.push({ key: 'base_cc', domain: null, name: String(caseToml.base_cc) });
  for (const domain of DOMAINS) {
    const section = caseToml[domain];
    if (isTable(section) && section.source_cc != null) refs.push({ key: 'source_cc', domain, name: String(section.source_cc) });
  }
  return refs;
}

/*
  What deserves a look in a configuration, most serious first: files that
  could not be read, parameter files no set builds, sets that cannot be
  resolved, data files with no definition or no workbook, and references to
  cases that are not there. `loadedPaths` are the workbooks read, or null
  when none were, in which case nothing is said about missing workbooks.
*/
export function configChecks(config, loadedPaths) {
  const out = [];
  const add = (level, text, cases = []) => out.push({ level, text, cases });
  const linkDefs = config.link?.defs || null;
  const dataDefs = config.data?.defs || null;
  for (const file of config.errors) add('error', `${file.path} could not be read: ${file.error}`);
  if (config.cases.length && !linkDefs) add('error', 'No link.toml was read, so no parameter file can be traced to its data files.');
  if (config.cases.length && !dataDefs) add('error', 'No data.toml was read, so no data file can be traced to its workbook.');

  const unbuilt = new Map();
  const caseNames = new Set(config.cases.map((c) => c.name));
  for (const caseFile of config.cases) {
    if (!asList(caseFile.toml.parameter_files).length) add('warning', `${caseFile.name} names no parameter file.`, [caseFile.name]);
    for (const pf of parameterFiles(caseFile.toml)) {
      if (linkDefs && !Object.prototype.hasOwnProperty.call(linkDefs, setOfFile(pf.file))) {
        if (!unbuilt.has(pf.file)) unbuilt.set(pf.file, []);
        unbuilt.get(pf.file).push(caseFile.name);
      }
    }
    for (const ref of caseReferences(caseFile.toml)) {
      if (!caseNames.has(ref.name)) {
        add('warning', `${caseFile.name}: ${ref.domain ? `[${ref.domain}] ` : ''}${ref.key} = ${ref.name}, which is not among the cases read.`, [caseFile.name]);
      }
    }
  }
  for (const [file, cases] of unbuilt) add('warning', `${file} is not built by link.toml: no set is called ${setOfFile(file)}.`, cases);

  if (linkDefs) {
    const usedData = new Set();
    for (const set of Object.keys(linkDefs)) {
      const { sources, steps, errors } = setSources(linkDefs, set);
      for (const error of errors) add('error', `Input set ${set}: ${error}.`);
      const own = steps[steps.length - 1];
      if (own && own.set === set) {
        if (own.skipAbsent.length) add('warning', `Input set ${set} skips ${own.skipAbsent.join(', ')}, which ${own.base} does not have.`);
        if (own.addPresent.length) add('warning', `Input set ${set} adds ${own.addPresent.join(', ')}, which it has already.`);
      }
      for (const source of sources) {
        usedData.add(dataName(source, dataDefs));
        if (dataDefs && !(dataName(source, dataDefs) in dataDefs)) add('error', `Input set ${set} uses ${source}, which data.toml does not define.`);
      }
    }
    if (dataDefs) {
      const unused = Object.keys(dataDefs).filter((name) => !usedData.has(name));
      if (unused.length) add('info', `${unused.length} data file(s) are in no input set: ${unused.join(', ')}.`);
    }
  }

  if (dataDefs && loadedPaths && loadedPaths.length) {
    const missing = [];
    for (const name of Object.keys(dataDefs)) {
      const src = dataSource(dataDefs, name);
      if (!src.raw && !findWorkbook(src.workbook, loadedPaths, config.folder).path) missing.push(src.workbook);
    }
    if (missing.length) add('warning', `${missing.length} workbook(s) in data.toml were not among those read: ${missing.join(', ')}.`);
  }
  const rank = { error: 0, warning: 1, info: 2 };
  return out.sort((a, b) => rank[a.level] - rank[b.level]);
}

/* A value as a short line: long lists are counted, with their ends. */
export function shortValue(value) {
  if (Array.isArray(value)) {
    if (value.length > 8) return `${value.length} values, ${shortValue(value[0])} … ${shortValue(value[value.length - 1])}`;
    return value.map(shortValue).join(', ');
  }
  if (value instanceof Date) return value.toISOString();
  if (isTable(value)) return Object.entries(value).map(([k, v]) => `${k} ${shortValue(v)}`).join(' · ');
  return String(value);
}
