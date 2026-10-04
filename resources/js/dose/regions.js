/*
  Source regions of the ICRP 60 dosimetry (DCAL, SEECAL) and how a
  compartment of a biokinetic model is assigned to one.

  DCAL's rule (ORNL/TM-2001/190, section 3.5): a compartment's name is a
  standard source-region name, or one followed by an underscore and a
  subscript -- Liver_1, Other_0, T_Bone-V_e, AI_4, bbe-gel_t. Names are
  compared without regard to case, and a blank counts as an underscore (a few
  of DCAL's own files write "St wall_1" and "R marrow").
*/

export const SOURCES_60 = [
  'Adrenals', 'UB_Cont', 'UB_Wall', 'C_Bone-S', 'C_Bone-V', 'T_Bone-S', 'T_Bone-V', 'Brain', 'Breasts',
  'St_Cont', 'St_Wall', 'SI_Cont', 'SI_Wall', 'ULI_Cont', 'ULI_Wall', 'LLI_Cont', 'LLI_Wall', 'Kidneys', 'Liver',
  'ET1-sur', 'ET2-sur', 'ET2-bnd', 'ET2-seq', 'LN-ET', 'BBi-gel', 'BBi-sol', 'BBi-bnd', 'BBi-seq',
  'bbe-gel', 'bbe-sol', 'bbe-bnd', 'bbe-seq', 'AI', 'LN-Th', 'Lng_Cont', 'Lng_Tiss', 'NP_Cont', 'TB_Cont',
  'P_Cont', 'LN_Lung', 'Muscle', 'Ovaries', 'Pancreas', 'R_Marrow', 'Skin', 'Spleen', 'Testes', 'Thymus',
  'Thyroid', 'GB_Cont', 'GB_Wall', 'Ht_Cont', 'Ht_Wall', 'Uterus', 'Body_Tis', 'Blood', 'BT-Soft', 'Other',
];

/* Where activity leaves the body. */
export const SINKS = ['Urine', 'Feces', 'Excreta'];

/* Regions of the respiratory tract model (ICRP 66). */
export const LUNG_REGIONS = new Set(['ET1-sur', 'ET2-sur', 'ET2-bnd', 'ET2-seq', 'LN-ET', 'BBi-gel', 'BBi-sol', 'BBi-bnd',
  'BBi-seq', 'bbe-gel', 'bbe-sol', 'bbe-bnd', 'bbe-seq', 'AI', 'LN-Th']);

/* Contents: not part of Body Tissues, so never part of Other. */
export const CONTENTS = new Set(['UB_Cont', 'St_Cont', 'SI_Cont', 'ULI_Cont', 'LLI_Cont', 'GB_Cont', 'Ht_Cont', 'Lng_Cont', 'NP_Cont', 'TB_Cont', 'P_Cont']);

/* The wall each contents irradiates (SEECAL's walled organs). */
export const WALL_OF = { St_Cont: 'St_Wall', SI_Cont: 'SI_Wall', ULI_Cont: 'ULI_Wall', LLI_Cont: 'LLI_Wall', UB_Cont: 'UB_Wall', GB_Cont: 'GB_Wall', Ht_Cont: 'Ht_Wall' };

export const BONE_SOURCES = new Set(['C_Bone-S', 'C_Bone-V', 'T_Bone-S', 'T_Bone-V']);

export const key = (name) => String(name).trim().toUpperCase().replace(/\s+/g, '_');

const BY_KEY = new Map([...SOURCES_60, ...SINKS].map((r) => [key(r), r]));
/* DCAL's ICRP 30 translations use "Lungs" for lung tissue (mercury vapour). */
BY_KEY.set('LUNGS', 'Lng_Tiss');

/** The standard source region (or sink) a compartment belongs to, or null. */
export function regionOf(name) {
  const k = key(name);
  if (BY_KEY.has(k)) return BY_KEY.get(k);
  let best = null;
  for (const [rk, r] of BY_KEY) {
    if (k.startsWith(rk + '_') && (!best || rk.length > key(best).length)) best = r;
  }
  return best;
}

export const isSink = (name) => SINKS.includes(regionOf(name));
