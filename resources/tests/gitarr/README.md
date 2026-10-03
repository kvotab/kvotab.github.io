# Tests for gitarr.html

Two files: the ear (resources/js/gitarr-pitch.js) on its own in Node, and
the page in headless Chrome. Both hear plucked strings made by `synth.js`:
the partials of a string plucked a fifth of the way along, the upper ones
dying faster, stretched by the string's stiffness `B`, with the click of the
pick, and if asked a phone microphone's high-pass, hiss, or an explicit list
of partial weights. No recordings are stored.

## test-pitch.js

    node resources/tests/gitarr/test-pitch.js

No page and no browser; about 15 s, and exits 0 when all 68 checks pass. It
reads every frame of each signal, 30 a second, the way the page does, and
checks that:

- **The right string, every frame.** Six strings at seven tunings from −45 to
  +45 cents, at 48 and 44.1 kHz, and at 16, 22.05, 32 and 96 kHz.
- **Accuracy.** Within 0.1 cent of the fundamental for clean plucks; within
  0.6 cent for a stiff string (B = 5·10⁻⁵, a guitar's) heard through a phone
  microphone, and 1.3 cent for one three times as stiff. YIN alone read these
  5–6 cents sharp while the upper partials rang; the second pass (the period
  measured again at the full rate on the three lowest partials) is what
  brought them under a cent.
- **The octave trap.** A low E with its fundamental gone, with no odd
  partials at all (which YIN reads as E3), or with the third partial loudest,
  is still a low E; a high E as a pure tone is not an A2 or E2 (three and
  four of its periods make those); a G two semitones flat is a G, not a sharp
  low E.
- **Noise and silence** are not strings; a pluck under −56 dBFS is not heard;
  the gate follows a loud room up and down, and a ringing string never lifts
  it.
- **A picked string** is read against itself however far out (a new A string
  400 cents flat), while the automatic choice would call the same note a
  sharp low E.
- **The tracker:** a stray reading of another string does not switch; one
  held 120 ms over three readings does; a silent string stays on screen,
  dimmed, then goes; the median throws out a wild reading; "in tune" after
  300 ms within 5 cents, announced once; the tick goes after 400 ms beyond
  12 cents. A low E still ringing under a fresh A gives way to it within
  350 ms.
- **Which way to turn,** all 48 cases of string, flat or sharp, left-handed
  or not, keys reversed or not, against the rules in `GT_PITCH.turn`.

## test-ui.py

The page in Chrome. Serve the repository and start Chrome first. The ports
are 8849 and 9349 unless `GT_HTTP_PORT` and `GT_CDP_PORT` say otherwise.
Check them with `lsof -nP -iTCP:<port> -sTCP:LISTEN` first, because other
sessions use ports too:

    python3 -m http.server 8849 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      --headless=new --remote-debugging-port=9349 --no-first-run \
      --user-data-dir=/tmp/gttest --disable-gpu \
      --autoplay-policy=no-user-gesture-required about:blank

    python3 resources/tests/gitarr/test-ui.py

About 15 seconds; exits 0 when all 106 checks pass. `GT_SHOTS=<folder>` saves
screenshots. Sound reaches the page three ways:

- `GT.test.feed(samples, rate, clock)` runs the page's own frame logic on a
  window of samples at a given clock time - for the many cases.
- `GT.test.play(samples, rate, loop)` plays them through the real audio
  path (an AudioBufferSource in place of the microphone, the high-pass, the
  analyser and the requestAnimationFrame loop).
- A trusted click on Starta with `getUserMedia` answering with a real
  MediaStream (a pluck played into a MediaStreamAudioDestinationNode). Chrome's
  own fake microphone is no use: in headless Chrome on macOS `getUserMedia`
  never settles, with `--use-fake-device-for-media-stream`, with or without a
  WAV file, the permission granted and the page focused.

It checks:

- **The drawing:** E A D on the left with the low E nearest the nut, G B E on
  the right with the high E nearest the nut, every string on the inside of
  its post. The site's own logo (`KVOT_ICONS.LOGO_SVG`) is cut small into the
  headstock: a cut per face of the mark, gold in what the header draws in its
  light colour (class `stTop`: the top face and the letters), centred, clear
  of the posts, and the right way round on a left-handed guitar.
- **Every string flat and sharp** (12 cases): its key lights, the loop round
  the key rolls the key's front up or down, the post's arrow turns the right
  way, and the message says "spänn" or "släpp efter" with the string's name.
  Near (within 15 cents), very far (over 50), in tune (green, ticked, no
  arrows), quiet (dimmed, then gone), all six ticked (the banner, and "Stäm
  igen").
- **Picking a string** with the mouse, Enter and Space; Auto; the settings
  (keys the other way, left-handed), kept in localStorage and validated on
  load; the help's table of strings; the dialogs open and close by clicks.
  (Not by Escape: CDP's Escape hangs headless Chrome while a dialog is open.)
- **The microphone:** the constraints asked for (no echo cancelling, noise
  suppression or gain control), the low E heard 20 cents flat with the right
  arrows, closed when the page is hidden and opened again when it is shown,
  Stoppa, the idle stop, sound suspended under it, a browser whose sound never
  starts (no hanging on "Startar mikrofonen …"), and the three
  `getUserMedia` errors.
- **Phones,** at the heights a page really gets after the browser's bars
  (iPhone 13 and SE both ways, a small Android, 320 × 520): no site header or
  footer, everything on one screen with nothing scrolling, keys at least
  30 px. A tablet upright keeps the chrome and stacks the guitar over the
  panel. Reduced motion stops every animation; the dark theme sets
  `color-scheme`.
