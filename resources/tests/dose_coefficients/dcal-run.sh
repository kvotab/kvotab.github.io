#!/bin/zsh
# DCAL itself, for checking the ICRP 60 engine against it: ACTACAL, SEECAL and
# EPACAL of your copy of DCAL (ORNL; the install's app folder, which holds bin,
# DAT, ini and wrk) run in DOSBox-X without a window, one case at a time.
#
#   DCAL=<app folder> resources/tests/dose_coefficients/dcal-run.sh WORK NUCLIDE ROUTE [TYPE] [KINETICS]
#
#   WORK      a folder for a working copy of DCAL (made on the first run; your
#             copy is never written to). Cases in different WORK folders can
#             run at the same time.
#   ROUTE     g ingestion, h inhalation, j injection; TYPE f, m or s (inhalation)
#   KINETICS  1 independent (the default), 2 shared -- what DCAL asks when a
#             chain has members; a chain that DCAL cuts to its parent asks nothing.
#
# The case runs from the FGR-13 work folder (WRK\FGR13, whose TIMIN.DAT is the
# time stepping of Federal Guidance Report 13) with the FGR-13 library
# (DAT\BIO\F13), members of the public, AMAD 1 um, DCAL's own chain cut. Its
# files (*.LOG, *.ACT, *.HRT, ...) stay in WORK/wrk/fgr13 until the next case;
# dcal-compare.mjs reads the *.HRT files. Needs: brew install dosbox-x.
#
# ACTACAL's prompts are answered from a file on standard input, padded with
# blank lines: its "Press <Enter> to continue" reads past what the Fortran
# runtime has buffered, and a file that ends there leaves it waiting forever.
set -e
[[ -n "$DCAL" && -d "$DCAL/bin" ]] || { echo "set DCAL to DCAL's app folder (with bin, DAT, ini, wrk)"; exit 2; }
WORK=${1:A}; nuc=$2; route=$3; type=${4:-f}; kin=${5:-1}
[[ -n "$WORK" && -n "$nuc" && -n "$route" ]] || { echo "usage: DCAL=... dcal-run.sh WORK NUCLIDE ROUTE [TYPE] [KINETICS]"; exit 2; }
if [[ ! -d "$WORK/bin" ]]; then
  mkdir -p "$WORK"
  rsync -a "$DCAL/" "$WORK/"
  # The FGR-13 library and work folder; the work folder's ACTACAL.INI predates
  # ACTACAL 8.3, which also wants the file of default ages at intake.
  printf 'Default Folders\r\n\\bio\\f13\r\n\\wrk\\fgr13\r\n' > "$WORK/ini/DCALMENU.INI"
  python3 - "$WORK/wrk/fgr13/ACTACAL.INI" <<'EOF'
import sys
p = sys.argv[1]
s = open(p, 'rb').read().decode('latin-1')
if 'intakexp.age' not in s:
    s = s.replace("'icrp56.age'", "'intakexp.age', '..\\..\\dat\\mis\\intakexp.age', 0   Default ages at intake\r\n'icrp56.age'", 1)
open(p, 'wb').write(s.encode('latin-1'))
EOF
fi
W="$WORK/wrk/fgr13"
find "$W" -maxdepth 1 -type f \( -iname '*.ACT' -o -iname '*.CPT' -o -iname '*.HRT' -o -iname '*.DRT' -o -iname '*.LOG' -o -iname '*.REQ' -o -iname '*.SEE' -o -iname 'FOR0*' -o -iname '$STEMNAM.DIR' -o -iname 'SCR?.TXT' \) -delete
python3 - "$W/IN.TXT" "$nuc" "$route" "$type" "$kin" <<'EOF'
import sys
out, nuc, route, typ, kin = sys.argv[1:]
# nuclide, default ages, equivalent dose, compartment file, route, [type, environmental, AMAD],
# no title lines, the chain cut ACTACAL offers, kinetics of the members
a = [nuc, 'y', 'e', 'y', route] + ([typ, 'e', '1'] if route == 'h' else []) + ['', '', kin]
open(out, 'wb').write(('\r\n'.join(a) + '\r\n').encode() + b'\r\n' * 3000)
EOF
printf 'cd \\wrk\\fgr13\r\n..\\..\\bin\\actacal.exe < IN.TXT > SCR1.TXT\r\n..\\..\\bin\\seecal.exe < IN.TXT > SCR2.TXT\r\n..\\..\\bin\\epacal.exe < IN.TXT > SCR3.TXT\r\n' > "$WORK/RUN.BAT"
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy dosbox-x -silent -nogui -nomenu -fastlaunch -time-limit ${DCAL_LIMIT:-900} \
  -set "cpu cycles=max" -set "cpu core=dynamic" -c "mount c \"$WORK\"" -c "c:" -c "RUN.BAT" > "$WORK/dosbox.log" 2>&1 || true
LC_ALL=C sed 's/\x1b\[[0-9;]*[A-Za-z]//g' "$W/SCR1.TXT" | LC_ALL=C tr -d '\r' | grep -E 'Truncate chain' || true
ls "$W" | grep -i -E '\.hrt$' | tr '\n' ' '; echo
