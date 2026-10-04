/*
  Loading the reference data of the two systems, in the page's worker (fetch)
  or in Node (the tests): `io` reads a path under resources/data/dose/ as JSON
  or as an ArrayBuffer.

    ICRP 60   icrp60/decay/  ICRP 38 decay data, as distributed with DCAL
              icrp60/saf.json, models.json, cases.json
    ICRP 103  icrp103/decay/ ICRP 107 decay data
              icrp103/saf/   ICRP 133/155 specific absorbed fractions
              icrp103/elements.json, progeny.json, hrtm.json, radon.json

  Decay data are per element; a calculation first loads the elements of the
  parent's whole chain, since the engines read emissions synchronously.
*/
import { SafPhantom } from './see103.js';
import { buildChain } from './chain.js';

const elementOf = (name) => /^([A-Z][a-z]?)-/.exec(name)[1];

export async function loadSystem(system, io) {
  const base = system === '60' ? 'icrp60' : 'icrp103';
  const decayIndex = await io.json(`${base}/decay/index.json`);
  const index = decayIndex.nuclides;
  const decay = {};
  const data = {
    system, index,
    emissions(name) {
      const el = decay[elementOf(name)];
      if (!el) throw new Error(`decay data of ${elementOf(name)} not loaded`);
      return el[name];
    },
    /** Load the decay data of every element in the chain of `nuclide`. */
    async prepare(nuclide) {
      const chain = buildChain(index, nuclide, { cutoff: 0 });
      const els = [...new Set(chain.members.map((m) => elementOf(m.name)))];
      await Promise.all(els.filter((el) => !decay[el]).map(async (el) => { decay[el] = await io.json(`${base}/decay/${el}.json`); }));
      if (system === '103') await loadNeutrons(chain.members.map((m) => m.name));
      return chain;
    },
  };
  if (system === '60') {
    const [models, saf, cases] = await Promise.all([io.json('icrp60/models.json'), io.json('icrp60/saf.json'), io.json('icrp60/cases.json')]);
    Object.assign(data, { models, saf, cases });
    return data;
  }
  const [elements, hrtm, safIndex, progeny, radon] = await Promise.all([io.json('icrp103/elements.json'), io.json('icrp103/hrtm.json'),
    io.json('icrp103/saf/index.json'), io.json('icrp103/progeny.json'), io.json('icrp103/radon.json')]);
  const phantoms = {};
  await Promise.all(safIndex.phantoms.map(async (p) => { phantoms[p.id] = new SafPhantom(safIndex, p.id, await io.bin(`icrp103/saf/${p.file}`)); }));
  // Neutron SAFs only when a chain has a spontaneously fissioning nuclide.
  async function loadNeutrons(names) {
    if (!names.some((n) => safIndex.neutron.nuclides.includes(n))) return;
    await Promise.all(safIndex.phantoms.map(async (p) => {
      if (!phantoms[p.id].neutron) phantoms[p.id].neutron = new Float32Array(await io.bin(`icrp103/saf/${p.neutronFile}`));
    }));
  }
  Object.assign(data, { elements, progeny, radon, deposition: hrtm.deposition, hrtm, saf: { index: safIndex, phantoms } });
  return data;
}

/** An io for fetch, relative to the data folder's URL. */
export function fetchIO(baseUrl) {
  const url = (p) => new URL(p, baseUrl).href;
  return {
    async json(p) { const r = await fetch(url(p)); if (!r.ok) throw new Error(`${p}: ${r.status}`); return r.json(); },
    async bin(p) { const r = await fetch(url(p)); if (!r.ok) throw new Error(`${p}: ${r.status}`); return r.arrayBuffer(); },
  };
}
