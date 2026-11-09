#!/usr/bin/env bash
# =============================================================================
# PHREEQC FOR RTM.HTML: IPHREEQC COMPILED TO WEBASSEMBLY
#
# Writes vendors/phreeqc/ from the USGS's own IPhreeqc source distribution,
# compiled unchanged with Emscripten:
#
#   phreeqc.js      the module, its WebAssembly inside it: one file, so that a
#                   page opened from the disk, which may not fetch, loads it too
#   phreeqc.dat     PHREEQC's standard database, from the same distribution
#   phreeqc-dat.js  the same database as a script (PHREEQC_DAT), for the same
#                   reason; non-ASCII characters are escaped
#   NOTICE          the USGS's user rights notice, which goes with every copy
#
#       scripts/build-phreeqc-wasm.sh
#
# Needs git, curl, cmake and node. Emscripten is installed into EMSDK_DIR
# (~/emsdk unless set), never into a shell profile; the source is unpacked and
# built in PHREEQC_BUILD_DIR (~/.cache/kvotab-phreeqc unless set).
#
# Pinned: IPhreeqc 3.8.6-17100, checked by its SHA-256, and Emscripten 7.0.0.
# What the module exports is what resources/js/rtm-phreeqc-engine.js calls.
# =============================================================================
set -euo pipefail

VERSION=3.8.6-17100
URL="https://water.usgs.gov/water-resources/software/PHREEQC/iphreeqc-${VERSION}.tar.gz"
SHA256=f5babcc9fb0c252e0c432786bbe9c265f02ca32791b096106f360cf1df1d9d94
EMSDK_VERSION=7.0.0
EMSDK_DIR="${EMSDK_DIR:-$HOME/emsdk}"
BUILD="${PHREEQC_BUILD_DIR:-$HOME/.cache/kvotab-phreeqc}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$REPO/vendors/phreeqc"

EXPORTS=_CreateIPhreeqc,_DestroyIPhreeqc,_LoadDatabaseString,_RunString,_GetErrorString
EXPORTS+=,_GetWarningString,_SetErrorStringOn,_SetCurrentSelectedOutputUserNumber
EXPORTS+=,_GetSelectedOutputRowCount,_GetSelectedOutputColumnCount,_GetSelectedOutputValue
EXPORTS+=,_VarInit,_VarClear,_GetVersionString,_malloc,_free
# PHREEQC's printed output, for what it prints alone: its inverse models.
EXPORTS+=,_SetOutputStringOn,_GetOutputString

# --- Emscripten ---------------------------------------------------------------
if [ ! -x "$EMSDK_DIR/emsdk" ]; then
  git clone --depth 1 https://github.com/emscripten-core/emsdk.git "$EMSDK_DIR"
fi
"$EMSDK_DIR/emsdk" install "$EMSDK_VERSION" >/dev/null
"$EMSDK_DIR/emsdk" activate "$EMSDK_VERSION" >/dev/null
# shellcheck disable=SC1091
source "$EMSDK_DIR/emsdk_env.sh" >/dev/null 2>&1

# --- the source, as the USGS distributes it --------------------------------------
mkdir -p "$BUILD"
cd "$BUILD"
TARBALL="iphreeqc-${VERSION}.tar.gz"
[ -f "$TARBALL" ] || curl -fsSL -o "$TARBALL" "$URL"
echo "$SHA256  $TARBALL" | shasum -a 256 -c - >/dev/null
rm -rf src obj out
mkdir src out
tar -xzf "$TARBALL" -C src --strip-components=1

# --- compiled unchanged: the static library, then one module ------------------------
# Tests off: they would fetch googletest. Native WebAssembly exceptions, in the
# form every current browser and Node 17 on take (PHREEQC throws on bad input).
# The WebAssembly is embedded as base64, which is plain ASCII: Emscripten's newer
# binary embedding puts raw bytes in the script and depends on its being read
# as UTF-8, which Emscripten itself says a browser on Windows may not do.
emcmake cmake -S src -B obj -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DBUILD_SHARED_LIBS=OFF \
  -DCMAKE_CXX_FLAGS=-fwasm-exceptions -DCMAKE_C_FLAGS=-fwasm-exceptions >/dev/null
cmake --build obj -j8 --target IPhreeqc >/dev/null
em++ -O2 -fwasm-exceptions -sWASM_LEGACY_EXCEPTIONS=1 obj/libIPhreeqc.a -o out/phreeqc.js \
  -sMODULARIZE=1 -sEXPORT_NAME=createPhreeqc \
  -sEXPORTED_FUNCTIONS="$EXPORTS" \
  -sEXPORTED_RUNTIME_METHODS=UTF8ToString,stringToUTF8,lengthBytesUTF8,getValue \
  -sALLOW_MEMORY_GROWTH=1 -sINITIAL_MEMORY=33554432 -sSTACK_SIZE=8388608 \
  -sENVIRONMENT=web,worker,node -sSINGLE_FILE=1 -sSINGLE_FILE_BINARY_ENCODE=0

# --- into the repository -----------------------------------------------------------
mkdir -p "$OUT"
{
  printf '/* IPhreeqc %s, the USGS'"'"'s PHREEQC (Parkhurst and Appelo), compiled unchanged to\n' "$VERSION"
  printf '   WebAssembly with Emscripten %s by scripts/build-phreeqc-wasm.sh. Public domain under\n' "$EMSDK_VERSION"
  printf '   the USGS user rights notice in NOTICE beside this file; see README.md there. */\n'
  cat out/phreeqc.js
} > "$OUT/phreeqc.js"
cp src/database/phreeqc.dat "$OUT/phreeqc.dat"
cp src/doc/NOTICE "$OUT/NOTICE"
node -e '
  const fs = require("fs");
  const [dat, js, version] = process.argv.slice(1);
  const text = fs.readFileSync(dat, "latin1");
  const lit = JSON.stringify(text).replace(/[\u0080-￿]/g,
    (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
  fs.writeFileSync(js, "/* phreeqc.dat from IPhreeqc " + version + " (USGS), as a script: a page opened from\n"
    + "   the disk cannot fetch the file beside it, but it can load this. */\n"
    + "(typeof self !== \"undefined\" ? self : globalThis).PHREEQC_DAT = " + lit + ";\n");
' "$OUT/phreeqc.dat" "$OUT/phreeqc-dat.js" "$VERSION"

printf 'vendors/phreeqc: IPhreeqc %s with Emscripten %s\n' "$VERSION" "$EMSDK_VERSION"
ls -l "$OUT"
