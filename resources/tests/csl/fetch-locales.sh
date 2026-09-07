#!/bin/sh
# CSL locale files are not part of this repository. citeproc needs them to
# resolve terms and month names; the styles override the terms they care about,
# but the processor still refuses to start without a locale.
set -e
cd "$(dirname "$0")"
mkdir -p locales
for lang in en-GB en-US sv-SE; do
  curl -fsSL -o "locales/locales-$lang.xml" \
    "https://raw.githubusercontent.com/citation-style-language/locales/master/locales-$lang.xml"
  echo "locales/locales-$lang.xml"
done
