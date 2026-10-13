/*
  The ICRP's figures of its systemic models, as the Model tab lays them out
  (diagram.js): each box at [x, y, w, h], x and w in 26 px, y and h in rows
  (one box high and the gap below it), the ways out with [x, y] and a width;
  `in` the side an arrow from outside comes in from where the figure draws
  it. A name may list its other spellings (a|b). What a figure does not
  have -- the gut's contents beyond those it shows, a progeny's compartments
  for where it is formed in its parent's model -- goes beside it and below.

  models: the systemic models of elements.json (element/key) a figure is
  of. A progeny's model, from its parent element's section of the OIR
  series, takes the figure of its own element when that holds most of it.
*/
/* The gut's contents down a column on a figure's right, where the figure
   has its colon contents and faeces: the small intestine (absorbed to the
   blood on its left), right colon, left colon, rectosigmoid, faeces; the
   stomach beside the small intestine and the oesophagus above it. */
const TRACT_RIGHT = (x, y) => ({
  'SI contents|SI content|SI cont': [x, y, 6.5, 1], 'RC contents|RC content|RC cont|RC-cont|Right colon contents': [x, y + 1.1, 6.5, 1],
  'LC contents|LC content|Left colon contents': [x, y + 2.2, 6.5, 1], 'RS contents|RS content|Rectosigmoid contents': [x, y + 3.3, 6.5, 1],
  'Faeces': [x + 0.5, y + 4.5],
  'Stomach contents|St contents|ST contents|St content|Stomach content': [x + 8, y, 6, 1], 'Oesophagus (slow)|Oesophagus (fast)': [x + 8, y - 1.2, 6, 1],
});

/* Boxes one under another down a column. */
const stack = (x, y, names, { dy = 1.1, w = 6.5, h = 1 } = {}) => Object.fromEntries(names.map((n, i) => [n, [x, y + i * dy, w, h]]));
/* Bone as the figures draw it: each surface next to the blood, its volume
   further out (vol false: the surfaces alone). */
const BONE = (x, y, { vol = true } = {}) => ({
  ...(vol ? { 'Cort bone vol|Cort volume': [x, y, 6.5, 1.2], 'Trab bone vol|Trab volume': [x, y + 1.8, 6.5, 1.2] } : {}),
  'Cort bone surf|Cort surface': [x + (vol ? 7.5 : 0), y, 6.5, 1.2], 'Trab bone surf|Trab surface': [x + (vol ? 7.5 : 0), y + 1.8, 6.5, 1.2],
});
/* The urinary bladder's contents, and urine on their left. */
const BLADDER = (x, y) => ({ 'UB contents|UB content|UB cont|UB-cont': [x, y, 5.5, 1.2], 'Urine': [x - 4.5, y + 0.3] });
/* The figure most models of Publication 151 and the EIR Part 3 draft share:
   a tall blood down the middle; soft tissue across the top (one box each
   over the left column, the blood and the right column) or stacked on its
   left; bone below that, a row each, the surface next to the blood and its
   volume or marrow further out; kidneys over the bladder at the bottom left;
   other organs, the liver and the gut down its right. inner: a box drawn
   inside the blood at its foot (red cells, a second pool), or with innerTop
   a second pool filling its upper part. */
function column({ blood, inner, innerTop = false, top = [], left = [], bone = [], kidneys = [], right = [], liver = [] }) {
  const BX = 17, LX = 9, RX = 24.5, boxes = {};
  const T = top.length ? 1.5 : 0;
  top.forEach((n, i) => { boxes[n] = [[LX, BX - 1, RX][i] ?? RX + 7.5 * (i - 2), 0, 6.5, 1]; });
  let y = T;
  for (const n of left) { boxes[n] = [LX, y, 6.5, 1]; y += 1.1; }
  if (left.length) y += 0.4;
  for (const row of bone) { row.forEach((n, i) => { boxes[n] = [LX - 7.5 * i, y, 6.5, 1.2]; }); y += 1.8; }
  y += 0.2;
  kidneys.forEach((n, i) => { boxes[n] = [LX, y + i * 1.2, 6.5, 1.2]; });
  const ubY = y + Math.max(0, kidneys.length - 1) * 1.2;
  Object.assign(boxes, BLADDER(LX - 7.5, ubY));
  let ry = T;
  for (const n of right) { boxes[n] = [RX, ry, 6.5, 1]; ry += 1.15; }
  if (liver.length) { ry += 0.2; for (const n of liver) { boxes[n] = [RX, ry, 6.5, 1]; ry += 1.1; } }
  Object.assign(boxes, TRACT_RIGHT(RX, ry + 0.3));
  const bottom = Math.max(ubY + 1.7, ry + 2.5);
  boxes[blood] = [BX, T, 4.5, bottom - T];
  if (inner) boxes[inner] = innerTop ? [BX + 0.7, T + 0.9, 3.1, bottom - T - 2.8] : [BX + 0.7, bottom - 2.1, 3.1, 1.4];
  return boxes;
}
const BONE4 = [['Cort surface', 'Cort volume'], ['Trab surface', 'Trab volume']];
const SURFACES = [['Cort surface'], ['Trab surface']];

export const FIGURES = [
  {
    id: 'tritium', figure: 'Publication 158, Figs. 5.1 and 5.2', models: ['H/hto', 'H/obt'],
    boxes: {
      'OBT-1': [7, 0, 6, 1.2], 'OBT-2': [14, 0, 6, 1.2],
      'Extravascular HTO': [7, 2, 13, 1],
      'Blood': [7, 3.6, 13, 1],
      'UB contents': [7, 5.4, 4.6, 1], 'Excreta': [12.2, 5.65], 'RC contents': [15.4, 5.4, 4.6, 1],
      'Urine': [7.4, 6.7],
      // The alimentary tract, which the figure leaves out.
      'Oesophagus (slow)|Oesophagus (fast)': [0, 0.6, 5, 1], 'Stomach contents': [0, 2, 5, 1], 'SI contents': [0, 3.6, 5, 1],
      'Left colon contents': [15.4, 6.6, 4.6, 1], 'Rectosigmoid contents': [15.4, 7.7, 4.6, 1], 'Faeces': [21, 7.95],
    },
    in: { 'Blood': 'left', 'OBT-1': 'left' },
  },
  {
    id: 'carbon-dioxide', figure: 'Publication 158, Fig. 6.2', models: ['C/co2'],
    boxes: {
      'Environment': [11.6, 0.1],
      'Trab bone surf': [1, 1.4, 5.7, 1], 'Trab bone vol': [1, 2.4, 5.7, 1],
      'Cort bone surf': [1, 3.8, 5.7, 1], 'Cort bone vol': [1, 4.8, 5.7, 1],
      'Blood 1': [8.8, 1.2, 5.4, 5.2],
      'Blood 2': [9.6, 2.6, 3.8, 2],
      'ST0': [16.2, 1.2, 6, 1], 'ST1': [16.2, 2.2, 6, 1], 'ST2': [16.2, 3.2, 6, 1], 'ST3': [16.2, 4.2, 6, 1],
      'RC contents': [16.2, 5.4, 6, 1], 'LC contents|Left colon contents': [23.5, 5.4, 6, 1], 'RS contents|Rectosigmoid contents': [23.5, 6.7, 6, 1],
      'Faeces': [18.5, 6.9],
      'Urine': [1, 6.9], 'UB contents': [6.2, 6.7, 4.6, 1],
      // The alimentary tract above the colon, which the figure leaves out.
      'SI contents': [23.5, 4.2, 6, 1], 'Stomach contents': [23.5, 3.1, 6, 1], 'Oesophagus (slow)|Oesophagus (fast)': [23.5, 2.0, 6, 1],
    },
  },
  {
    id: 'phosphorus', figure: 'Publication 158, Fig. 7.1', models: ['P/default'],
    boxes: {
      'ST1': [14, 0, 6.5, 1], 'ST0': [23, 0, 6.5, 1], 'ST2': [31.5, 0, 6.5, 1],
      'Plasma': [24, 1.5, 4.5, 9.4], 'RBC': [24.7, 8.6, 3.1, 1.2],
      'Nonexch cort bone vol': [0, 2.4, 6.5, 1.2], 'Exch cort bone vol': [7.5, 2.4, 6.5, 1.2], 'Cort bone surf': [15, 2.4, 6.5, 1.2],
      'Nonexch trab bone vol': [0, 4.4, 6.5, 1.2], 'Exch trab bone vol': [7.5, 4.4, 6.5, 1.2], 'Trab bone surf': [15, 4.4, 6.5, 1.2],
      'Liver 2': [31.5, 2.4, 6.5, 1], 'Liver 1': [31.5, 3.5, 6.5, 1],
      ...TRACT_RIGHT(31.5, 4.9),
      'Other kidney tissue': [15, 7.4, 6.5, 1], 'Urinary path': [15, 8.6, 6.5, 1],
      'UB contents': [7.5, 8.6, 6.5, 1], 'Urine': [1.5, 8.85],
    },
  },
  {
    id: 'alkaline-earth', figure: 'Publication 158, Figs. 9.1, 15.4 and 27.1', models: ['Ca/default', 'Sr/default', 'Ba/default'],
    boxes: {
      'Nonexch cort bone vol': [0, 1.4, 6.5, 1.2], 'Exch cort bone vol': [7.5, 1.4, 6.5, 1.2], 'Cort bone surf': [15, 1.4, 6, 1.2],
      'Nonexch trab bone vol': [0, 3.2, 6.5, 1.2], 'Exch trab bone vol': [7.5, 3.2, 6.5, 1.2], 'Trab bone surf': [15, 3.2, 6, 1.2],
      'Blood': [23.5, 0, 4.5, 7.4],
      'ST2': [31, 0.2, 6.5, 1], 'ST1': [31, 1.3, 6.5, 1], 'ST0': [31, 2.4, 6.5, 1],
      ...TRACT_RIGHT(31, 3.9),
      'UB contents': [7.5, 5.6, 6.5, 1.2], 'Urine': [1.5, 5.85],
    },
  },
  {
    id: 'radium', figure: 'Publication 158, Fig. 33.2', models: ['Ra/default'],
    boxes: {
      'ST1': [14, 0, 6.5, 1], 'ST0': [23, 0, 6.5, 1], 'ST2': [31.5, 0, 6.5, 1],
      'Blood': [24, 1.5, 4.5, 9.4],
      'Nonexch cort bone vol': [0, 2.4, 6.5, 1.2], 'Exch cort bone vol': [7.5, 2.4, 6.5, 1.2], 'Cort bone surf': [15, 2.4, 6.5, 1.2],
      'Nonexch trab bone vol': [0, 4.4, 6.5, 1.2], 'Exch trab bone vol': [7.5, 4.4, 6.5, 1.2], 'Trab bone surf': [15, 4.4, 6.5, 1.2],
      'Liver 2': [31.5, 2.4, 6.5, 1], 'Liver 1': [31.5, 3.5, 6.5, 1],
      ...TRACT_RIGHT(31.5, 4.9),
      'Kidneys 2': [15, 7.4, 6.5, 1], 'Kidneys 1': [15, 8.6, 6.5, 1],
      'UB contents': [7.5, 8.6, 6.5, 1], 'Urine': [1.5, 8.85],
    },
  },
  {
    id: 'carbon', figure: 'Publication 158, Figs. 6.1 and 6.2', models: ['C/generic', 'C/methane'],
    boxes: {
      // Fig. 6.1: the systemic tissues beside the blood, the carbon dioxide model (Fig. 6.2) below them.
      'Blood (methane)': [4.5, -1.4, 5.5, 1], 'Expired air': [11.5, -1.15],
      'SI contents': [-2.5, 0.2, 5, 1], 'Stomach contents': [-2.5, -1, 5, 1], 'Oesophagus (slow)|Oesophagus (fast)': [-2.5, -2.2, 5, 1],
      'RC contents': [-2.5, 1.6, 5, 1.4], 'Short-term tissue': [4.5, 1.6, 5.5, 1.4], 'Long-term tissue': [11, 1.6, 5.5, 1.4],
      'Blood': [18, 0, 4.5, 3.6], 'UB contents': [18, 4.2, 5, 1.2], 'Urine': [24, 4.45],
      'Environment': [1.5, 5.4],
      'Trab bone surf': [0, 6.6, 5.7, 1], 'Trab bone vol': [0, 7.6, 5.7, 1], 'Cort bone surf': [0, 9.0, 5.7, 1], 'Cort bone vol': [0, 10.0, 5.7, 1],
      'Blood 1': [7.8, 6.4, 5.4, 5.2], 'Blood 2': [8.6, 7.8, 3.8, 2],
      'ST0': [15.2, 6.4, 6, 1], 'ST1': [15.2, 7.4, 6, 1], 'ST2': [15.2, 8.4, 6, 1], 'ST3': [15.2, 9.4, 6, 1],
      'LC contents|Left colon contents': [-2.5, 3.1, 5, 1], 'RS contents|Rectosigmoid contents': [-2.5, 4.2, 5, 1], 'Faeces': [-2, 5.4],
    },
  },
  {
    id: 'sulphur-inorganic', figure: 'Publication 158, Fig. 8.1', models: ['S/inorganic'],
    boxes: {
      'Other': [7.5, 0, 5, 1], 'Blood': [8, 1.5, 4, 5],
      'Red marrow': [0, 2, 5.5, 1.2], 'Cartilage': [15, 2, 5.5, 1.2],
      'UB contents': [0, 4.2, 5.5, 1.3], 'Urine': [0.5, 5.9],
      'RC contents': [15, 4.2, 5.5, 1.2], 'Left colon contents': [15, 5.5, 5.5, 1], 'Rectosigmoid contents': [15, 6.6, 5.5, 1], 'Faeces': [15.5, 7.8],
      'SI contents': [22, 3.1, 5.5, 1], 'Stomach contents': [22, 1.9, 5.5, 1], 'Oesophagus (slow)|Oesophagus (fast)': [22, 0.7, 5.5, 1],
    },
  },
  {
    id: 'sulphur-organic', figure: 'Publication 158, Fig. 8.2', models: ['S/organic'],
    boxes: {
      'SI contents': [0, 0.4, 5, 2.4], 'Blood 1': [7.5, 0, 5, 2], 'Blood 2': [7.5, 2, 5, 2.4],
      'UB contents': [15, 1.2, 5, 1.4], 'All tissues': [15, 3, 5, 1.2], 'Urine': [21.5, 3.25], 'Excreta': [8, 4.8],
      'Right colon contents': [0, 3.2, 5, 1], 'Left colon contents': [0, 4.3, 5, 1], 'Rectosigmoid contents': [0, 5.4, 5, 1], 'Faeces': [0.5, 6.6],
      'Stomach contents': [0, -0.9, 5, 1], 'Oesophagus (slow)|Oesophagus (fast)': [0, -2.1, 5, 1],
    },
  },
  {
    id: 'iron', figure: 'Publication 158, Fig. 10.1', models: ['Fe/default'],
    boxes: {
      'Other RE': [0, 0, 6.5, 1.2], 'RM storage': [8.5, 0, 6.5, 1.2], 'Spleen': [17, 0, 6.5, 1.2],
      'RM synthesis': [0, 1.7, 6.5, 1.2], 'RM transit': [8.5, 1.7, 6.5, 1.2], 'Liver 2': [17, 1.7, 6.5, 1.2],
      'EV transferrin': [0, 3.4, 6.5, 1.3], 'Plasma transferrin': [8.5, 3.4, 6.5, 1.2], 'Liver 1': [17, 3.4, 6.5, 1.2],
      'Other parenchyma': [0, 5.1, 6.5, 1.2], 'Other plasma': [8.5, 5.1, 6.5, 1.2], 'SI contents': [17, 5.1, 6.5, 1],
      'Excreta': [0.5, 6.85], 'RBC': [8.5, 6.6, 6.5, 1.2], 'RC contents': [17, 6.6, 6.5, 1],
      'UB contents': [0, 7.9, 6.5, 1], 'Urine': [9, 8.15],
      'Left colon contents': [17, 7.7, 6.5, 1], 'Rectosigmoid contents': [17, 8.8, 6.5, 1], 'Faeces': [17.5, 10],
      'Stomach contents': [25, 5.1, 6, 1], 'Oesophagus (slow)|Oesophagus (fast)': [25, 3.9, 6, 1],
    },
  },
  {
    id: 'cobalt', figure: 'Publication 158, Figs. 11.1, 21.1 and 28.1', models: ['Co/default', 'Ru/default', 'Ir/default'],
    boxes: {
      'ST1': [9, 0, 6.5, 1], 'ST0': [17.5, 0, 6.5, 1], 'ST2': [26, 0, 6.5, 1],
      'Blood 1': [18.5, 1.5, 4.5, 9.4], 'Blood 2': [19.2, 8.4, 3.1, 1.3],
      ...BONE(1.5, 2.4),
      'Liver 2': [26, 2.4, 6.5, 1], 'Liver 1': [26, 3.5, 6.5, 1], ...TRACT_RIGHT(26, 4.9),
      'Other kidney tissue': [9, 7.4, 6.5, 1], 'Urinary path': [9, 8.6, 6.5, 1], ...BLADDER(2, 8.6),
    },
  },
  {
    id: 'nickel', figure: 'Publication 158, Fig. 12.1', models: ['Ni/default'],
    boxes: {
      ...stack(9, 0, ['ST1', 'ST0']), ...BONE(1.5, 2.6),
      'Plasma': [17.5, 0, 4.5, 9.4], 'RBC': [18.2, 6.6, 3.1, 1.4],
      'Excreta': [25, 0.25], 'Liver 2': [25, 1.4, 6.5, 1], 'Liver 1': [25, 2.6, 6.5, 1], ...TRACT_RIGHT(25, 4),
      'Kidneys 1': [9, 6.8, 6.5, 1], 'Kidneys 2': [9, 8.2, 6.5, 1], 'UB contents': [1.5, 6.8, 6, 1], 'Urine': [2, 8.3],
    },
  },
  {
    id: 'zinc', figure: 'Publication 158, Fig. 13.1', models: ['Zn/default'],
    boxes: {
      ...stack(9, 0, ['ST2', 'ST1', 'ST0']), ...BONE(1.5, 3.7),
      'Plasma': [17.5, 0, 4.5, 10.4], 'RBC': [18.2, 7.2, 3.1, 1.4],
      ...stack(25, 0, ['Muscle', 'Pancreas'], { dy: 1.2 }), 'Liver 2': [25, 2.6, 6.5, 1], 'Liver 1': [25, 3.7, 6.5, 1], ...TRACT_RIGHT(25, 5.1),
      'Kidneys': [9, 7.6, 6.5, 1.4], ...BLADDER(2, 8.9), 'Excreta': [23.5, 10.8],
    },
  },
  {
    id: 'selenium', figure: 'Publication 158, Fig. 14.1', models: ['Se/default'],
    boxes: {
      ...stack(9, 0, ['ST2', 'ST1']), ...BONE(9, 2.6, { vol: false }),
      'Plasma': [17.5, 0, 4.5, 9.8], 'RBC': [18.2, 6.6, 3.1, 1.4],
      ...stack(25, 0, ['Pancreas', 'Spleen', 'Testes', 'Ovaries'], { dy: 1.15 }), 'Liver': [25, 4.8, 6.5, 1], ...TRACT_RIGHT(25, 6.1),
      'Kidneys': [9, 7.2, 6.5, 1.4], ...BLADDER(2, 8.4),
    },
  },
  {
    id: 'yttrium', figure: 'Publication 158, Figs. 16.1, 17.1 and 18.1', models: ['Y/default', 'Zr/default', 'Nb/default'],
    boxes: {
      ...stack(9, 0, ['ST1', 'ST0']), ...BONE(1.5, 2.6),
      'Blood 1': [17.5, 0, 4.5, 9.4], 'Blood 2': [18.2, 6.8, 3.1, 1.4],
      'Liver 1': [25, 1.2, 6.5, 1], 'Liver 0': [25, 2.4, 6.5, 1], ...TRACT_RIGHT(25, 3.9),
      'Kidneys': [9, 7, 6.5, 1.4], ...BLADDER(2, 8.2),
    },
  },
  {
    id: 'molybdenum', figure: 'Publication 158, Fig. 19.1', models: ['Mo/default'],
    boxes: {
      'Other': [4.5, 0.1, 6.5, 1], 'Kidneys 2': [7.5, 1.4, 5, 1], 'Kidneys 1': [7.5, 2.6, 5, 1],
      'UB contents': [1.5, 4.4, 5, 1.2], 'Urine': [-3, 4.65],
      'Blood 2': [15, 0, 4.5, 3.6], 'Blood 1': [15, 3.8, 4.5, 2.2],
      'Liver': [22, 1.4, 4.5, 3.4],
      // The gut, which the figure has as colon contents and faeces: under the blood and the liver.
      'SI contents': [15, 6.4, 4.5, 1], 'Stomach contents': [8, 6.4, 5, 1], 'Oesophagus (slow)|Oesophagus (fast)': [8, 7.6, 5, 1],
      'RC contents': [22, 6.4, 5.5, 1], 'Left colon contents': [29, 6.4, 5.5, 1], 'Rectosigmoid contents': [29, 7.5, 5.5, 1], 'Faeces': [29.5, 8.7],
    },
  },
  {
    id: 'technetium', figure: 'Publication 158, Fig. 20.1', models: ['Tc/default'],
    boxes: {
      ...stack(9, 0, ['ST0', 'ST1', 'ST2'], { w: 5.5 }), ...BONE(1, 3.7),
      'Blood': [17.5, 0, 4.5, 11],
      'Other kidney tissue': [8.5, 7.6, 6, 1], 'Urinary path': [8.5, 8.8, 6, 1], ...BLADDER(2, 8.8),
      'Thyroid 1': [24.5, 0, 6, 1], 'Thyroid 2': [24.5, 1.2, 6, 1], 'Salivary glands': [24.5, 2.6, 6.5, 1],
      'Liver 2': [24.5, 4, 5, 1], 'Liver 1': [24.5, 5.3, 5, 1], 'Oral cavity': [31, 4, 5, 1], 'Oesophagus (slow)': [31, 5.3, 5, 1], 'Oesophagus (fast)': [37, 5.3, 5.5, 1],
      'St wall': [24.5, 6.7, 5, 1], 'St contents': [31, 6.7, 6, 1], 'SI contents': [31, 8, 6, 1],
      'RC wall': [24.5, 9.2, 5, 1], 'RC contents': [31, 9.2, 6, 1], 'Left colon contents': [31, 10.3, 6, 1], 'Rectosigmoid contents': [31, 11.4, 6, 1], 'Faeces': [31.5, 12.6],
    },
  },
  {
    id: 'silver', figure: 'Publication 158, Fig. 22.1', models: ['Ag/default'],
    boxes: {
      ...stack(9, 0, ['ST1', 'ST0']), ...BONE(9, 2.6, { vol: false }),
      'Blood 1': [17.5, 0, 4.5, 8.4], 'Blood 2': [18.2, 5.8, 3.1, 1.4],
      'Liver 1': [25, 1.2, 6.5, 1], 'Liver 2': [25, 2.4, 6.5, 1], ...TRACT_RIGHT(25, 3.8),
      'Kidneys': [9, 6.4, 6.5, 1.2], ...BLADDER(2, 7),
    },
  },
  {
    id: 'antimony', figure: 'Publication 158, Fig. 23.1', models: ['Sb/default'],
    boxes: {
      'ST1': [9, 0, 6.5, 1], 'ST0': [17.5, 0, 6.5, 1], 'ST2': [26, 0, 6.5, 1],
      'Plasma': [18.5, 1.5, 4.5, 9.4], 'RBC': [19.2, 8.4, 3.1, 1.3], ...BONE(1.5, 2.4),
      'Thyroid': [26, 1.6, 6.5, 1], 'Liver 2': [26, 2.9, 6.5, 1], 'Liver 1': [26, 4, 6.5, 1], ...TRACT_RIGHT(26, 5.4),
      'Kidneys': [9, 8.2, 6.5, 1.4], ...BLADDER(2, 9),
    },
  },
  {
    id: 'tellurium', figure: 'Publication 158, Fig. 24.1', models: ['Te/default'],
    boxes: {
      ...BONE(0, 0.2), 'Blood 1': [16, 0, 4.5, 7.4], 'Blood 2': [16.7, 4.9, 3.1, 1.4],
      'Thyroid': [23, 0.2, 6, 1], 'Liver': [23, 2.4, 6, 1.2], 'Other': [23, 4.8, 6, 1.2],
      'SI contents': [30.5, 2.4, 6, 1.2], 'Right colon contents': [30.5, 3.8, 6, 1], 'Left colon contents': [30.5, 4.9, 6, 1], 'Rectosigmoid contents': [30.5, 6, 6, 1], 'Faeces': [31, 7.2],
      'Stomach contents': [38, 2.4, 6, 1], 'Oesophagus (slow)|Oesophagus (fast)': [38, 1.2, 6, 1],
      'Kidneys': [8, 4, 6, 1.4], ...BLADDER(2.5, 5.8),
    },
  },
  {
    id: 'iodine', figure: 'Publication 158, Fig. 25.4', models: ['I/default'],
    boxes: {
      'Oral cavity': [0, 0, 5, 1], 'Oesophagus (slow)': [0, 1.2, 5, 1], 'Oesophagus (fast)': [-6.5, 1.2, 5.5, 1], 'St contents': [0, 2.4, 5, 1],
      'SI contents': [0, 3.5, 5, 1.2], 'RC contents': [0, 5.4, 5, 1.2], 'Left colon contents': [0, 6.8, 5, 1], 'Rectosigmoid contents': [0, 7.9, 5, 1], 'Faeces': [0.5, 9.1],
      'Salivary glands': [7, 0, 5.5, 1], 'St wall': [7, 2.4, 5.5, 1], 'Liver 2': [7, 3.8, 5.5, 1], 'Liver 1': [7, 4.9, 5.5, 1], 'Other 3': [7, 6.6, 5.5, 1], 'Other 4': [7, 7.7, 5.5, 1],
      'Blood iodide': [15, 0, 5, 3.95], 'Blood organic': [15, 3.95, 5, 5.65],
      'Thyroid 1': [22.5, 0.3, 5.5, 1], 'Thyroid 2': [22.5, 1.4, 5.5, 1], 'Other 1': [22.5, 2.4, 5.5, 1], 'Other 2': [22.5, 3.5, 5.5, 1],
      'Kidneys 1': [22.5, 6.4, 5.5, 1], 'Kidneys 2': [22.5, 7.5, 5.5, 1], 'UB contents': [30, 6.4, 5.5, 1.2], 'Urine': [30.5, 8.1],
    },
  },
  {
    id: 'caesium', figure: 'Publication 158, Fig. 26.2', models: ['Cs/default'],
    boxes: {
      'Blood': [9.5, 0, 4.5, 14], 'RBC': [10.2, 10.6, 3.1, 1.4],
      ...stack(1.5, 0, ['Skin', 'Other 1', 'Other 2', 'Lung tissue', 'Adipose tissue', 'Red marrow', 'Trab bone surf', 'Cort bone surf', 'Cartilage', 'Kidneys']),
      'UB contents': [1.5, 11, 6.5, 1], 'Urine': [2, 12.2], 'Muscle': [1.5, 13, 6.5, 1], 'Excreta': [-4.5, 0.25],
      ...stack(16.5, 0, ['Brain', 'Heart wall', 'Pancreas', 'Spleen', 'Liver']),
      ...stack(16.5, 5.7, ['St wall', 'SI wall', 'RC wall', 'LC wall', 'RS wall'], { dy: 1.4 }),
      ...stack(24, 6.2, ['St contents', 'SI contents', 'RC contents', 'LC contents', 'RS contents'], { dy: 1.4 }), 'Faeces': [24.5, 13.2],
      'Oesophagus (slow)|Oesophagus (fast)': [24, 5, 6.5, 1],
    },
  },
  {
    id: 'lead', figure: 'Publication 158, Fig. 29.1', models: ['Pb/default'],
    boxes: {
      'Excreta': [0, 0.25], 'ST1': [9, 0, 6.5, 1], 'ST0': [17.5, 0, 6.5, 1], 'ST2': [26, 0, 6.5, 1],
      'Blood': [18.5, 1.5, 4.5, 9.4], 'Blood 1': [19.2, 8.4, 3.1, 1.3],
      'Cort bone vol 2': [-6, 2.4, 6.5, 1.2], 'Cort bone vol 1': [1.5, 2.4, 6.5, 1.2], 'Cort bone surf': [9, 2.4, 6.5, 1.2],
      'Trab bone vol 2': [-6, 4.2, 6.5, 1.2], 'Trab bone vol 1': [1.5, 4.2, 6.5, 1.2], 'Trab bone surf': [9, 4.2, 6.5, 1.2],
      'Liver 2': [26, 2.4, 6.5, 1], 'Liver 1': [26, 3.5, 6.5, 1], ...TRACT_RIGHT(26, 4.9),
      'Kidneys 2': [9, 7.4, 6.5, 1], 'Kidneys 1': [9, 8.6, 6.5, 1], ...BLADDER(2, 8.6),
    },
  },
  {
    id: 'bismuth', figure: 'Publication 158, Fig. 30.1', models: ['Bi/default'],
    boxes: {
      'ST1': [9, 0, 6.5, 1], 'ST0': [17.5, 0, 6.5, 1], 'ST2': [26, 0, 6.5, 1],
      'Blood': [18.5, 1.5, 4.5, 9.4], 'Blood 1': [19.2, 7.6, 3.1, 1.3],
      'Trab bone surf': [5, 2.6, 8.5, 1.2], 'Cort bone surf': [5, 4.4, 8.5, 1.2],
      'Liver 2': [26, 2.4, 6.5, 1], 'Liver 1': [26, 3.5, 6.5, 1], ...TRACT_RIGHT(26, 4.9),
      'Kidneys 2': [9, 7.4, 6.5, 1], 'Kidneys 1': [9, 8.6, 6.5, 1], ...BLADDER(2, 8.6),
    },
  },
  {
    id: 'actinide', figure: 'EIR Part 2 (draft), Figs. 3.1, 17.1-19.1, 21.1 and 23.1-28.1',
    models: ['La/default', 'Ce/default', 'Pr/default', 'Nd/default', 'Pm/default', 'Sm/default', 'Eu/default', 'Gd/default', 'Tb/default', 'Dy/default', 'Ho/default', 'Er/default', 'Tm/default', 'Yb/default', 'Lu/default',
      'Ac/default', 'Th/default', 'Pa/default', 'Np/default', 'Am/default', 'Cm/default', 'Bk/default', 'Cf/default', 'Es/default', 'Fm/default'],
    boxes: {
      'ST1': [12, 0, 6.5, 1], 'ST0': [21.5, 0, 6.5, 1], 'ST2': [31, 0, 6.5, 1],
      'Blood': [22.5, 1.5, 4.5, 10],
      'Cort bone vol': [0, 2.6, 6, 1.2], 'Cort bone surf': [7.5, 2.6, 6, 1.2], 'Cort marrow': [15, 2.6, 6, 1.2],
      'Trab bone vol': [0, 4.6, 6, 1.2], 'Trab bone surf': [7.5, 4.6, 6, 1.2], 'Trab marrow': [15, 4.6, 6, 1.2],
      'Liver 2': [30, 2.4, 6.5, 1], 'Liver 1': [30, 3.5, 6.5, 1],
      'SI content|SI cont|SI contents': [30, 4.9, 6.5, 1], 'RC content|RC cont|Right colon contents': [30, 6, 6.5, 1],
      'LC contents|Left colon contents': [30, 7.1, 6.5, 1], 'RS contents|Rectosigmoid contents': [30, 8.2, 6.5, 1], 'Faeces': [37.5, 8.45],
      'Stomach contents': [38, 4.9, 6, 1], 'Oesophagus (slow)|Oesophagus (fast)': [38, 3.7, 6, 1],
      'Testes': [30, 9.5, 6.5, 1], 'Ovaries': [30, 10.6, 6.5, 1],
      'Kidneys 2': [15, 8.4, 6, 1], 'Kidneys 1': [15, 9.6, 6, 1], 'UB content|UB cont|UB contents': [7.5, 9.6, 6, 1.2], 'Urine': [3, 9.9],
    },
  },
  {
    id: 'uranium', figure: 'EIR Part 2 (draft), Fig. 20.1', models: ['U/default'],
    boxes: {
      'ST1': [14, 0, 6.5, 1], 'ST0': [23, 0, 6.5, 1], 'ST2': [31.5, 0, 6.5, 1],
      'Plasma': [24, 1.5, 4.5, 9.4], 'RBC': [24.7, 8.4, 3.1, 1.3],
      'Nonexch cort vol': [0, 2.4, 6.5, 1.2], 'Exch cort vol': [7.5, 2.4, 6.5, 1.2], 'Cort bone surf': [15, 2.4, 6.5, 1.2],
      'Nonexch trab vol': [0, 4.4, 6.5, 1.2], 'Exch trab vol': [7.5, 4.4, 6.5, 1.2], 'Trab bone surf': [15, 4.4, 6.5, 1.2],
      'Liver 2': [31.5, 2.4, 6.5, 1], 'Liver 1': [31.5, 3.5, 6.5, 1], ...TRACT_RIGHT(31.5, 4.9),
      'Kidneys 2': [15, 7.4, 6.5, 1], 'Kidneys 1': [15, 8.6, 6.5, 1], ...BLADDER(7.5, 8.6),
    },
  },
  {
    id: 'plutonium', figure: 'EIR Part 2 (draft), Fig. 22.1', models: ['Pu/default'],
    boxes: {
      // The figure's blood column, Blood 0 above Blood 2 and Blood 1: Blood 1, which sends to every tissue,
      // round Blood 2, to which they return.
      'Blood 0': [22.5, 0, 6, 1.1], 'Blood 1': [22, 1.4, 7, 11.8], 'Blood 2': [23.5, 2.7, 4, 9.9],
      'ST0': [12, 0.2, 6.5, 1], 'ST1': [12, 2.8, 6.5, 1], 'ST2': [12, 3.9, 6.5, 1],
      'Cort bone vol': [0, 5.4, 6, 1.2], 'Cort bone surf': [7.5, 5.4, 6, 1.2], 'Cort marrow': [15, 5.4, 6, 1.2],
      'Trab bone vol': [0, 7.2, 6, 1.2], 'Trab bone surf': [7.5, 7.2, 6, 1.2], 'Trab marrow': [15, 7.2, 6, 1.2],
      'Liver 3': [31.5, 2.7, 6.5, 1], 'Liver 2': [31.5, 3.8, 6.5, 1], 'Liver 1': [31.5, 4.9, 6.5, 1],
      'SI cont|SI content|SI contents': [31.5, 6.3, 6.5, 1], 'RC cont|RC content|Right colon contents': [31.5, 7.4, 6.5, 1],
      'LC contents|Left colon contents': [31.5, 8.5, 6.5, 1], 'RS contents|Rectosigmoid contents': [31.5, 9.6, 6.5, 1], 'Faeces': [39, 9.85],
      'Stomach contents': [39.5, 6.3, 6, 1], 'Oesophagus (slow)|Oesophagus (fast)': [39.5, 5.1, 6, 1],
      'Testes': [31.5, 10.8, 6.5, 1], 'Ovaries': [31.5, 11.9, 6.5, 1],
      'Kidneys 2': [15, 9.2, 6, 1], 'Kidneys 1': [15, 10.4, 6, 1], 'UB cont|UB content|UB contents': [7.5, 10.4, 6, 1.2], 'Urine': [3, 10.7],
    },
  },
  { id: 'beryllium', figure: 'EIR Part 3 (draft), Fig. 2.1', models: ['Be/default'],
    boxes: column({ blood: 'Blood 1', inner: 'Blood 2', innerTop: true, left: ['Other 1', 'Other 2'], bone: SURFACES, kidneys: ['Kidneys'], liver: ['Liver 2', 'Liver 1'] }) },
  { id: 'fluorine', figure: 'EIR Part 3 (draft), Fig. 3.2', models: ['F/default'],
    boxes: {
      'Other': [0, 0, 5, 1], 'Blood': [0, 1.5, 5, 2.6],
      'Trab surface 1': [8, 1.5, 5.5, 1], 'Trab surface 2': [15, 1.5, 5.5, 1], 'Cort surface 1': [8, 2.9, 5.5, 1], 'Cort surface 2': [15, 2.9, 5.5, 1],
      'Kidneys': [0, 4.6, 5, 1], 'UB content|UB contents': [0, 6, 5, 1.2], 'Urine': [6, 6.3],
      // The alimentary tract, which the figure leaves out, down its left.
      'Oesophagus (slow)|Oesophagus (fast)': [-7.5, 0.4, 6, 1], 'Stomach contents': [-7.5, 1.5, 6, 1], 'SI contents': [-7.5, 2.6, 6, 1],
      'Right colon contents': [-7.5, 3.7, 6, 1], 'Left colon contents': [-7.5, 4.8, 6, 1], 'Rectosigmoid contents': [-7.5, 5.9, 6, 1], 'Faeces': [-7, 7.1],
    } },
  { id: 'sodium', figure: 'EIR Part 3 (draft), Fig. 4.1', models: ['Na/default'],
    boxes: column({ blood: 'Blood', left: ['Other'], bone: BONE4, right: ['Excreta'] }) },
  { id: 'magnesium', figure: 'EIR Part 3 (draft), Fig. 5.1', models: ['Mg/default'],
    boxes: column({ blood: 'Plasma', inner: 'RBC', bone: BONE4, right: ['Other 1', 'Other 2', 'Other 3'] }) },
  { id: 'aluminium', figure: 'EIR Part 3 (draft), Fig. 6.1', models: ['Al/default'],
    boxes: column({ blood: 'Blood 1', inner: 'Blood 2', innerTop: true, bone: BONE4, right: ['Other 2', 'Other 1'] }) },
  { id: 'silicon', figure: 'EIR Part 3 (draft), Figs. 7.1 and 17.1', models: ['Si/default', 'Ge/default'],
    boxes: column({ blood: 'Blood', bone: [['Trab surface', 'Trab volume'], ['Cort surface', 'Cort volume']], kidneys: ['Kidneys'], right: ['Other', 'Liver'] }) },
  { id: 'potassium', figure: 'EIR Part 3 (draft), Figs. 9.1 and 20.3', models: ['K/default', 'Rb/default'],
    boxes: column({ blood: 'Blood', inner: 'RBC', left: ['Excreta', 'Other'], bone: SURFACES, kidneys: ['Kidneys'], right: ['Muscle', 'Red marrow', 'Liver'] }) },
  { id: 'scandium', figure: 'EIR Part 3 (draft), Fig. 10.1', models: ['Sc/default'],
    boxes: column({ blood: 'Blood 1', inner: 'Blood 2', left: ['Other 1', 'Other 2'], bone: [['Cort marrow', 'Cort surface', 'Cort volume'], ['Trab marrow', 'Trab surface', 'Trab volume']], kidneys: ['Kidneys'], right: ['Spleen'], liver: ['Liver 2', 'Liver 1'] }) },
  { id: 'titanium', figure: 'EIR Part 3 (draft), Figs. 11.1, 26.1 and 27.1', models: ['Ti/default', 'Hf/default', 'Ta/default'],
    boxes: column({ blood: 'Blood 1', inner: 'Blood 2', left: ['Other 1', 'Other 2'], bone: BONE4, kidneys: ['Kidneys'], liver: ['Liver 2', 'Liver 1'] }) },
  { id: 'vanadium', figure: 'EIR Part 3 (draft), Fig. 12.1', models: ['V/default'],
    boxes: column({ blood: 'Blood 1', inner: 'Blood 2', left: ['Other 2', 'Other 1'], bone: SURFACES, kidneys: ['Kidneys'], liver: ['Liver 2', 'Liver 1'] }) },
  { id: 'chromium', figure: 'EIR Part 3 (draft), Fig. 13.1', models: ['Cr/default'],
    boxes: column({ blood: 'Plasma 1', inner: 'Plasma 2', innerTop: true, left: ['Other 1', 'Other 2'], bone: SURFACES, kidneys: ['Kidneys'], right: ['Liver'] }) },
  { id: 'manganese', figure: 'EIR Part 3 (draft), Fig. 14.1', models: ['Mn/default'],
    boxes: column({ blood: 'Plasma', inner: 'RBC', left: ['Other 1', 'Other 2', 'Other 3'], bone: BONE4, kidneys: ['Kidneys'], right: ['Brain', 'Pancreas'], liver: ['Liver 2', 'Liver 1'] }) },
  { id: 'copper', figure: 'EIR Part 3 (draft), Fig. 15.1', models: ['Cu/default'],
    boxes: {
      'SI content': [0, 0.6, 5, 1.6], 'Liver 1': [7, 0.6, 4.5, 1.6], 'Plasma 1': [14, 0.6, 4.5, 1.6], 'UB content': [21, 0.6, 5, 1.6], 'Urine': [21.5, -0.7],
      'Liver 2': [7, 3.4, 4.5, 1.6], 'Plasma 2': [14, 3.4, 4.5, 1.6], 'Other': [21, 3.4, 5, 1.6],
      'Right colon contents': [0, 2.8, 5, 1], 'Left colon contents': [0, 3.9, 5, 1], 'Rectosigmoid contents': [0, 5, 5, 1], 'Faeces': [0.5, 6.2],
      'Stomach contents': [0, -0.7, 5, 1], 'Oesophagus (slow)|Oesophagus (fast)': [0, -1.9, 5, 1],
    },
    in: { 'Plasma 1': 'top' } },
  { id: 'gallium', figure: 'EIR Part 3 (draft), Fig. 16.1', models: ['Ga/default'],
    boxes: column({ blood: 'Blood', left: ['Other 1', 'Other 2'], bone: [['Cort surface'], ['Trab surface'], ['Red marrow']], kidneys: ['Kidneys'], right: ['Muscle', 'Pancreas', 'Spleen', 'Liver'] }) },
  { id: 'arsenic', figure: 'EIR Part 3 (draft), Fig. 18.1', models: ['As/default'],
    boxes: column({ blood: 'Plasma', inner: 'RBC', top: ['Other 1', 'Other 2', 'Other 3'], bone: BONE4, kidneys: ['Kidneys 2', 'Kidneys 1'], liver: ['Liver 2', 'Liver 1'] }) },
  { id: 'platinum-group', figure: 'EIR Part 3 (draft), Figs. 21.1, 22.1, 30.1 and 31.1', models: ['Rh/default', 'Pd/default', 'Os/default', 'Pt/default'],
    boxes: column({ blood: 'Blood 1|Blood', inner: 'Blood 2', top: ['Other 2', 'Other 1', 'Other 3'], bone: BONE4, kidneys: ['Kidneys 2', 'Kidneys 1'], liver: ['Liver 2', 'Liver 1'] }) },
  { id: 'cadmium', figure: 'EIR Part 3 (draft), Fig. 23.1', models: ['Cd/default'],
    boxes: column({ blood: 'Plasma', inner: 'RBC', left: ['Other 1', 'Other 2'], bone: BONE4, kidneys: ['Kidneys'], right: ['Muscle', 'Pancreas', 'Liver'] }) },
  { id: 'indium', figure: 'EIR Part 3 (draft), Fig. 24.1', models: ['In/default'],
    boxes: {
      ...stack(9, 0, ['Other 1', 'Other 2']), ...stack(9, 2.6, ['Red marrow 1', 'Red marrow 2'], { dy: 1.3 }),
      'Plasma': [17, 0, 4.5, 8.4], 'TF': [17.7, 0.9, 3.1, 4.2], 'RBC': [17.7, 6, 3.1, 1.4],
      'Liver 2': [24.5, 1.2, 6.5, 1], 'Liver 1': [24.5, 2.3, 6.5, 1], ...TRACT_RIGHT(24.5, 3.7),
      'Kidneys': [9, 6.4, 6.5, 1.2], ...BLADDER(1.5, 6.4),
    } },
  { id: 'tin', figure: 'EIR Part 3 (draft), Fig. 25.1', models: ['Sn/default'],
    boxes: column({ blood: 'Blood', left: ['Other 1', 'Other 2'], bone: BONE4, kidneys: ['Kidneys 2', 'Kidneys 1'], liver: ['Liver 2', 'Liver 1'] }) },
  { id: 'tungsten', figure: 'EIR Part 3 (draft), Fig. 28.1', models: ['W/default'],
    boxes: { ...column({ blood: 'Plasma', inner: 'RBC', top: ['Other 3', 'Other 1', 'Other 2'], bone: [['Cort surface', 'Cort volume 1', 'Cort volume 2'], ['Trab surface', 'Trab volume 1', 'Trab volume 2']], kidneys: ['Kidneys 2', 'Kidneys 1'], right: ['Spleen'], liver: ['Liver 2', 'Liver 1'] }),
      'Excreta': [0, 0.25] } },
  { id: 'rhenium', figure: 'EIR Part 3 (draft), Fig. 29.1', models: ['Re/default'],
    boxes: {
      ...stack(9, 0, ['Other 1', 'Other 2', 'Other 3'], { w: 5.5 }), ...BONE(1, 3.7),
      'Blood': [17.5, 0, 4.5, 11],
      'Kidneys 2': [8.5, 7.6, 6, 1], 'Kidneys 1': [8.5, 8.8, 6, 1], ...BLADDER(2, 8.8),
      'Thyroid 1': [24.5, 0, 6, 1], 'Thyroid 2': [24.5, 1.2, 6, 1], 'S-glands': [24.5, 2.6, 6.5, 1],
      'Liver 2': [24.5, 4, 5, 1], 'Liver 1': [24.5, 5.3, 5, 1], 'Oral cavity': [31, 4, 5, 1], 'Oesophagus (slow)': [31, 5.3, 5, 1], 'Oesophagus (fast)': [37, 5.3, 5.5, 1],
      'Stomach wall': [24.5, 6.7, 5, 1], 'St content': [31, 6.7, 6, 1], 'SI content|SI contents': [31, 8, 6, 1],
      'RC wall': [24.5, 9.2, 5, 1], 'RC content': [31, 9.2, 6, 1], 'Left colon contents': [31, 10.3, 6, 1], 'Rectosigmoid contents': [31, 11.4, 6, 1], 'Faeces': [31.5, 12.6],
    } },
  { id: 'gold', figure: 'EIR Part 3 (draft), Fig. 32.1', models: ['Au/default'],
    boxes: column({ blood: 'Blood 1', inner: 'Blood 2', left: ['Other 1'], bone: SURFACES, kidneys: ['Kidneys'], right: ['Other 2', 'Liver'] }) },
  { id: 'thallium', figure: 'EIR Part 3 (draft), Fig. 37.1', models: ['Tl/default'],
    boxes: column({ blood: 'Plasma', inner: 'RBC', left: ['Other'], bone: SURFACES, kidneys: ['Kidneys'], right: ['Liver'] }) },
  { id: 'astatine', figure: 'EIR Part 3 (draft), Fig. 35.1', models: ['At/default'],
    boxes: {
      'Oral cavity': [0, 0.6, 5, 1], 'Oesophagus (slow)': [0, 1.7, 5, 1], 'Oesophagus (fast)': [-6.5, 1.7, 5.5, 1], 'Stomach content': [0, 2.8, 5, 1], 'SI contents|SI content': [0, 3.9, 5, 1],
      'Right colon contents': [0, 5, 5, 1], 'Left colon contents': [0, 6.1, 5, 1], 'Rectosigmoid contents': [0, 7.2, 5, 1], 'Faeces': [0.5, 8.4],
      'Salivary glands': [7, 0.6, 5, 1.2], 'Stomach wall': [7, 2.8, 5, 1.2], 'Lung tissue': [7, 4.4, 5, 1.2], 'Spleen': [7, 5.8, 5, 1.2], 'Other': [7, 7.2, 5, 1.2],
      'Blood': [14, 0, 5, 9],
      'Thyroid 1': [21.5, 0.6, 5, 1], 'Thyroid 2': [21.5, 1.8, 5, 1], 'Liver': [21.5, 3.4, 5, 1], 'Kidneys': [21.5, 4.8, 5, 1], 'UB content': [21.5, 6.2, 5, 1.2], 'Urine': [22, 7.8],
    } },
  { id: 'mercury-inorganic', figure: 'EIR Part 3 (draft), Fig. 33.1', models: ['Hg/inorganic'],
    boxes: {
      'Brain 1': [0, 0.2, 5, 1], 'Brain 2': [0, 1.2, 5, 1], 'Other 1': [0, 2.8, 5, 1], 'Other 2': [0, 3.8, 5, 1], 'Kidneys': [0, 5.3, 5, 1.2], 'UB content': [0, 6.9, 5, 1], 'Urine': [0.5, 8.1],
      'Plasma 1': [8, 0, 6, 7.4], 'Plasma 2': [9, 0.9, 4, 1.2], 'RBC': [9, 4.9, 4, 1.2],
      'Excreta': [17, 0.25], 'Liver': [17, 1.6, 5, 1.2], ...TRACT_RIGHT(17, 3.4),
    } },
  { id: 'mercury-vapour', figure: 'EIR Part 3 (draft), Fig. 33.2', models: ['Hg/vapour'],
    boxes: {
      'Excreta': [8, -0.3], 'Plasma 0': [0, 0.6, 5, 7.9],
      ...stack(7, 0.8, ['Brain 1', 'Brain 2', 'RBC', 'Other 1', 'Other 2', 'Liver', 'Kidneys'], { w: 5.5 }),
      'Plasma 1': [15, 0.6, 5, 7.9], 'Plasma 2': [22, 0.8, 5, 1.2],
      'UB content': [7, 8.9, 5.5, 1], 'Urine': [1.5, 9.15],
      'SI content': [15, 9.1, 5, 1], 'Right colon contents': [22, 9.1, 5, 1], 'Left colon contents': [29, 9.1, 5.5, 1], 'Rectosigmoid contents': [29, 10.2, 5.5, 1], 'Faeces': [29.5, 11.4],
      'Stomach contents': [15, 10.3, 5, 1], 'Oesophagus (slow)|Oesophagus (fast)': [15, 11.5, 5, 1],
    } },
  { id: 'mercury-methyl', figure: 'EIR Part 3 (draft), Fig. 33.3', models: ['Hg/methyl'],
    boxes: {
      'Excreta': [14.5, -1], 'Plasma 3': [0, 0.4, 5, 8.4],
      ...stack(7, 0.6, ['Brain 3', 'RBC 2', 'Plasma 4', 'Other 3', 'Liver 3', 'Liver 2', 'Kidneys 2'], { dy: 1.2, w: 5.5 }),
      ...stack(14, 0, ['Skin', 'Brain 1', 'Brain 2', 'RBC', 'Other 1', 'Other 2', 'Liver', 'Kidneys'], { dy: 1.15, w: 5.5 }),
      'Plasma 4': [7, 2.85, 5.5, 1], // level with the gap between Brain 2 and RBC, through which it sends to Plasma 1
      'Plasma 1': [21.5, 0.4, 5, 8.4], 'Plasma 2': [28.5, 1.2, 5, 1.2],
      'UB content': [7, 9.4, 5.5, 1], 'Urine': [1.5, 9.65],
      'SI content': [14, 9.4, 5.5, 1], 'Right colon contents': [21.5, 9.4, 5, 1], 'Left colon contents': [28.5, 9.4, 5.5, 1], 'Rectosigmoid contents': [28.5, 10.5, 5.5, 1], 'Faeces': [29, 11.7],
      'Stomach contents': [14, 10.6, 5.5, 1], 'Oesophagus (slow)|Oesophagus (fast)': [14, 11.8, 5.5, 1],
    } },
  {
    id: 'radon', figure: 'Publication 158, Fig. 32.1', models: ['Rn/male', 'Rn/female'],
    boxes: {
      'RT-air': [7, 0, 8, 1],
      'Environment': [18, 0, 4],
      'Blood-V': [0, 0.5, 4, 11.5],
      'Blood-A': [18, 0.5, 4, 11.5],
      'Fat 1': [7, 1, 8, 1], 'Fat 2': [7, 2, 8, 1],
      'Y-marrow 1': [7, 3, 8, 1], 'Y-marrow 2': [7, 4, 8, 1],
      'Red marrow': [7, 5, 8, 1],
      'TB volume': [7, 6, 8, 1], 'CB volume': [7, 7, 8, 1],
      'Breast-a': [7, 8, 8, 1], 'Breast-g': [7, 9, 8, 1],
      'Kidneys': [7, 10, 8, 1],
      'Other': [7, 11, 8, 1],
      'Liver': [0, 12.8, 5, 1], 'SI contents': [7, 12.8, 5, 1], 'ST contents': [13.5, 12.8, 6, 1],
    },
    in: { 'RT-air': 'left', 'ST contents': 'right' },
  },
  {
    id: 'polonium', figure: 'Publication 158, Fig. 31.1', models: ['Po/default'],
    boxes: {
      'Plasma 2': [15.5, 0, 6, 1.5],
      'Plasma 1': [15.5, 1.5, 6, 8],
      'Plasma 3': [16.5, 4, 4, 1],
      'RBC': [16.5, 6.5, 4, 1],
      'UB contents': [0, 2, 5, 1], 'Urine': [0, 3.3, 5], 'Excreta': [0, 4.6, 5],
      'Kidneys 1': [7.5, 2, 5.5, 1], 'Kidneys 2': [7.5, 3, 5.5, 1],
      'Skin': [7.5, 4.5, 5.5, 1], 'Spleen': [7.5, 5.5, 5.5, 1], 'Red marrow': [7.5, 6.5, 5.5, 1],
      'Trab bone surf': [7.5, 7.5, 5.5, 1], 'Cort bone surf': [7.5, 8.5, 5.5, 1],
      'SI contents': [24.5, 1.5, 7, 1],
      'Liver 1': [24.5, 3, 5, 1], 'Liver 2': [24.5, 4, 5, 1],
      'Testes': [24.5, 5.3, 5, 1], 'Ovaries': [24.5, 6.3, 5, 1],
      'Other': [24.5, 7.6, 5, 1.4],
      // The rest of the alimentary tract, which the figure has as one box with the small intestine's.
      'Oesophagus (slow)|Oesophagus (fast)': [33, 0.2, 6, 1], 'Stomach contents': [33, 1.5, 6, 1],
      'Right colon contents': [33, 3, 6, 1], 'Left colon contents': [33, 4, 6, 1], 'Rectosigmoid contents': [33, 5, 6, 1],
      'Faeces': [33, 6.2, 5],
    },
    in: { 'Plasma 2': 'right' },
  },
];

/* The figure of a model of the Model tab (worker.js models103): the one of
   its own model, or null. */
export function figureFor(model) {
  return (model.modelId && FIGURES.find((f) => f.models.includes(model.modelId))) || null;
}

/* Figures a model without one of its own might stand as (diagram.js
   chooseFigure keeps the one whose arrows cross the fewest boxes, or makes
   one): those that place all its blood compartments, three in five of all
   its boxes, and fill half the figure's own boxes, so that no large part of
   it stands empty; the best first, its own element's on a tie. */
const ADDED = /contents?$|cont$|^Oesophagus|^Oral cavity$|^(Urine|Faeces|Excreta)$/;
export function similarFigures(model) {
  // Only within the ICRP 103 system, whose figures these are (an ICRP 60 model has no element here).
  if (figureFor(model) || !model.el) return [];
  const names = new Set(model.compartments.map((c) => c.name));
  const blood = model.compartments.filter((c) => c.region === 'Blood').map((c) => c.name);
  const out = [];
  for (const f of FIGURES) {
    const keys = Object.keys(f.boxes).map((k) => k.split('|'));
    const has = (n) => keys.some((alts) => alts.includes(n));
    if (!blood.every(has)) continue;
    const cover = [...names].filter(has).length / names.size;
    const core = keys.filter((alts) => !alts.some((a) => ADDED.test(a)));
    const fill = core.length ? core.filter((alts) => alts.some((a) => names.has(a))).length / core.length : 0;
    if (cover < 0.6 || fill < 0.5) continue;
    const mine = !!model.el && f.models.some((id) => id.startsWith(`${model.el}/`));
    out.push([cover + fill + (mine ? 0.05 : 0), f]);
  }
  return out.sort((a, b) => b[0] - a[0]).map(([, f]) => f);
}
