// The parts of a workbook written by resources/js/xlsxwrite.js, for
// test-xlsxwrite.py, which zips them and reads them back.
//
//     node resources/tests/site/xlsxwrite-parts.mjs formats|names|sheets
//
// prints { "xl/styles.xml": "...", ... } as JSON. JSZip is stood in for by a
// map of the parts: putting them in a zip is JSZip's work, and what is being
// checked is the XML the writer puts in it.
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = readFileSync(path.join(here, '..', '..', 'js', 'xlsxwrite.js'), 'utf8');

class Parts {
  constructor() { this.parts = {}; }
  file(name, content) { this.parts[name] = String(content); return this; }
  async generateAsync() { return this.parts; }
}

// As in a page: the writer finds JSZip on window and leaves XlsxWriter there.
const window = { JSZip: Parts };
vm.runInContext(source, vm.createContext({ window, console }), { filename: 'xlsxwrite.js' });
const { XlsxWriter } = window;

const CASES = {
  // One cell a format, the default format among them, in the order a page
  // makes them: each format's cell has to come out in that format, not in
  // the one made before it.
  formats() {
    const w = new XlsxWriter('formats.xlsx');
    const S = 'Formats';
    const f = {
      bold: w.addFormat({ bold: true }),
      sci: w.addFormat({ numFormat: '0.000E+00' }),
      fixed: w.addFormat({ numFormat: '0.00' }),
      muted: w.addFormat({ italic: true, fontSize: 9, fontColor: '7A6E62', align: 'center' }),
      struck: w.addFormat({ fontStrikeout: true }),
      header: w.addFormat({ bold: true, bg_color: '217346', font_color: 'FFFFFF', border: 1 }),
      plain: w.addFormat({})
    };
    w.write(0, 0, 'bold', f.bold, S);
    w.write(1, 0, 1.5e-12, f.sci, S);
    w.write(2, 0, 3.14159, f.fixed, S);
    w.write(3, 0, 'muted', f.muted, S);
    w.write(4, 0, 'struck', f.struck, S);
    w.write(5, 0, 'header', f.header, S);
    w.write(6, 0, 'plain', f.plain, S);
    w.write(7, 0, 'none', undefined, S);
    w.setColumn(1, 1, 30, f.bold, {}, S);
    return w;
  },
  // XlsxWriter's names and numbers for what OOXML spells otherwise. A Format
  // takes them (rb's dataset export asks for valign 'vcenter'), and written
  // as they are they make styles.xml invalid.
  names() {
    const w = new XlsxWriter('names.xlsx');
    const S = 'Names';
    w.write(0, 0, 'centred', w.addFormat({ align: 'center_across', valign: 'vcenter' }), S);
    w.write(1, 0, 'patterned', w.addFormat({ bg_color: 'E2EFDA', pattern: 1 }), S);
    return w;
  },
  // A sheet made by writeData, and then named by the calls that take a
  // sheet: they have to reach that sheet, not start a second of its name.
  sheets() {
    const w = new XlsxWriter('sheets.xlsx');
    w.writeData([['a', 'b'], [1, 2]], 'Settings');
    w.setColumn(0, 0, 22, undefined, {}, 'Settings');
    w.write(3, 0, 'after', undefined, 'Settings');
    w.freezePanes('Settings', 1);
    w.writeData([[3]], 'Second');
    return w;
  }
};

const make = CASES[process.argv[2]];
if (!make) {
  console.error(`usage: node xlsxwrite-parts.mjs ${Object.keys(CASES).join('|')}`);
  process.exit(2);
}
process.stdout.write(JSON.stringify(await make().save()));
