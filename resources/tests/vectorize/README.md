# Tests for vectorize.html

Three files: the tracing engine (resources/js/vectorize-trace.js) and the
poster PDF (resources/js/vectorize-poster.js) on their own in Node, and the
page in headless Chrome. None needs a file: every image is drawn by the test,
or is the page's own sample.

## test-trace.js

    node resources/tests/vectorize/test-trace.js

No page and no browser; a few seconds, and exits 0 when all 47 checks pass.
It checks that:

- **Outlines are right:** a ring is two outlines wound opposite ways, on its
  true radii within 0.3 px, in a handful of curves; smoothing takes the
  pixel steps out of a hard-edged circle without changing its size; specks
  go by area; light lines on a dark ground; a checkerboard's every outline
  closes.
- **Faint lines** on grainy grey paper come out unbroken and as wide as a
  black line of the same width, and the paper stays paper.
- **Corners** are kept when asked for.
- **Black lines only**, on a drawn cartoon with flat fills of every kind
  (red, navy, dark brown, grey, dark grey) outlined in black, clean and with
  a JPEG's colour smeared over 2 × 2 pixels: every fill is paper (traced by
  darkness, the navy and brown are solid ink); the black lines are traced
  (overlap with the true lines over 0.8); a dark blue line on white is let
  go; a 1.2 px black fold line across the red is unbroken; a solid black
  disc keeps its area within 5 %; transparency is paper.
- **Pieces:** an outline and its holes are one piece, a disc inside a hole
  another; each seed is ink of its own piece; on a checkerboard every piece
  has one outer outline, and below half, joined at the corners, it is one
  piece.
- **The runner** (the worker's own code): each piece has its slice of the
  path, its box and its seed; removing by the seed takes a ring out, hole
  and all, and leaves the disc inside it; a point at the ink's edge finds
  the piece too, a point on paper nothing; only the drawing is put together
  again (no retrace); the removal holds with thinner lines; an erased
  stroke cuts a bar in two where it ran, leaves the outlines it did not
  touch exactly as they were, and is undone by leaving it out; a looser
  curve fit refits; a slanted cut follows the stroke's edge within 0.3 px.
- **Speed:** a 1080 × 810 doodle at 3× detail in under 15 s, its fill
  matching the drawing (overlap over 0.84).

Each check of black lines only and of the edits was seen to fail with the
part it is about taken out of the engine (the colour gate, the floor, the
edge measure, the closing, the lift, the saddle joins, removal, erasing, the
fit cache's key, the soft edge of a stroke).

## test-poster.js

    node resources/tests/vectorize/test-poster.js

Exits 0 when all 56 checks pass: reading path data (arcs, Q and T, flags
written together, malformed data refused), the poster's layout, its sheets
and the PDF it writes, and an SVG file printed as it is.

## test-ui.py

    python3 -u resources/tests/vectorize/test-ui.py

The page in headless Chrome, 36 checks: the Trace choice and the preset for
a cartoon, the offer of black lines only for a picture in colour, the
coloured sample traced both ways, and the edit tools (Remove by hover,
click, box and tap; Erase; Undo, Redo, Restore all; the space bar; Escape;
the Black & white view and the downloaded SVG with the edits). Its
docstring says how to serve the repository and start Chrome (muted), on
ports 8861 and 9361 unless VZ_HTTP_PORT and VZ_CDP_PORT say otherwise.
