# PHREEQC, compiled to WebAssembly

These files are the U.S. Geological Survey's **IPhreeqc 3.8.6-17100**, compiled to WebAssembly for rtm.html. IPhreeqc is the library form of PHREEQC, by David L. Parkhurst and C.A.J. Appelo. Nothing in its source was changed.

| File | What it is |
|---|---|
| `phreeqc.js` | IPhreeqc compiled with Emscripten 7.0.0, the WebAssembly embedded in the script. It defines one factory, `createPhreeqc`. |
| `phreeqc.dat` | PHREEQC's standard database, as it comes in the same distribution. |
| `phreeqc-dat.js` | The same database as a script that sets `PHREEQC_DAT`, with non-ASCII characters escaped. A page opened from the disk cannot fetch a file, but it can load a script. |
| `NOTICE` | The USGS user rights notice, which goes with every copy. |

**The original distribution.** <https://water.usgs.gov/water-resources/software/PHREEQC/iphreeqc-3.8.6-17100.tar.gz>, SHA-256 `f5babcc9fb0c252e0c432786bbe9c265f02ca32791b096106f360cf1df1d9d94`. PHREEQC's own page is <https://www.usgs.gov/software/phreeqc-version-3>.

**How it was built.** `scripts/build-phreeqc-wasm.sh` downloads that archive, checks its SHA-256 and compiles the IPhreeqc library from it unchanged. The CMake build is used, with its tests off, and the module is linked to export IPhreeqc's C functions. Run it again to rebuild these files.

**Modifications.** None to PHREEQC or its database. The only additions are a comment at the top of `phreeqc.js` saying what it is, and the script form of the database.

**Acknowledgement.** PHREEQC is public domain under the USGS's notice. rtm.html credits it in its Help:

> Parkhurst, D.L., and Appelo, C.A.J., 2013, Description of input and examples for PHREEQC version 3—A computer program for speciation, batch-reaction, one-dimensional transport, and inverse geochemical calculations: U.S. Geological Survey Techniques and Methods, book 6, chap. A43, 497 p., <https://doi.org/10.3133/tm6A43>.
