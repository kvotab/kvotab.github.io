/*
  The names of ICRP Publication 72's tables, where they differ from the page's.

  In the ICRP 60 system the page names a radionuclide as ICRP Publication
  119 does. Its Table 2.3 gives the states of a nuclide the names of
  Publication 107: the ground state plain, the excited states with m and n.
  Publication 72 has the names of its decay data, Publication 38, and they
  differ in three ways:

    - two pairs are the other way round: its Rh-102 (2.9 y) and Ta-180
      (1.0E13 y) are the excited states, its Rh-102m (207 d) and Ta-180m
      (8.1 h) the ground states;
    - the two states of a pair stand under one name, told apart by their
      half-lives: Nb-89, In-110, Sb-120, Sb-128, Eu-150, Re-182, Ir-186 and
      Np-236, and Tb-156m and Ir-190m for the two excited states of each;
    - a state stands under a name that here is another state's (Sb-124m,
      Ta-178) or no state's (Nb-98, Ir-192m, Es-250).

  The ICRP's database of dose coefficients has Publication 72's names, with
  s or l (the short or the long half-life) after one that stands for two
  states.
*/

/** The page's name -> the name Publication 72 prints, where they differ. */
export const NAME_72 = {
  'Nb-89m': 'Nb-89', 'Nb-98m': 'Nb-98', 'Rh-102': 'Rh-102m', 'Rh-102m': 'Rh-102', 'In-110m': 'In-110',
  'Sb-120m': 'Sb-120', 'Sb-124n': 'Sb-124m', 'Sb-128m': 'Sb-128', 'Eu-150m': 'Eu-150', 'Tb-156n': 'Tb-156m',
  'Ta-178m': 'Ta-178', 'Ta-180': 'Ta-180m', 'Ta-180m': 'Ta-180', 'Re-182m': 'Re-182', 'Ir-186m': 'Ir-186',
  'Ir-190n': 'Ir-190m', 'Ir-192n': 'Ir-192m', 'Np-236m': 'Np-236', 'Es-250m': 'Es-250',
};

/**
 * What to say beside a nuclide of the ICRP 60 system about its name in
 * Publication 72: a sentence, or '' where the names agree.
 * @param {string} name     the name typed, written as the page writes names
 * @param {boolean} found   the page has a nuclide of that name
 * @param {boolean} listed  Publication 72 has coefficients for it (of a nuclide found)
 */
export function note72(name, found, listed) {
  const own = found ? NAME_72[name] : undefined;
  const other = Object.keys(NAME_72).find((n) => n !== name && NAME_72[n] === name);
  if (own && other) return `Publication 72 and the ICRP’s database of dose coefficients have the two names the other way round: this is their ${own}, and their ${name} is ${other} here.`;
  if (own) return `Publication 72 prints it as ${own}.`;
  if (!other) return '';
  return found && listed ? `Publication 72 prints ${other} under this name too.` : `The ${name} of Publication 72 is ${other} here.`;
}
