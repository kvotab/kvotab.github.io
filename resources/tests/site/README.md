# Characterisation tests for the whole site

These answer one question: **did a change alter the site's behaviour?** They do
not assert the behaviour is correct — they record what it currently is, so a
refactor can be shown not to have moved it.

## Running

    python3 -m http.server 8765 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      --headless=new --remote-debugging-port=9222 --no-first-run \
      --user-data-dir=/tmp/kvottest --disable-gpu about:blank

Then, from this directory:

    python3 characterise.py before      # before the change
    # ... make the change ...
    python3 characterise.py after
    python3 compare.py before.json after.json

`compare.py` prints `IDENTICAL` or lists every field that moved. One full run
takes roughly 100 seconds and compares 267 fields.

## What is covered

For **every page**: title, header element and tag, nav toggle and its ARIA
state, menu links, footer icon and button counts, theme (applied, stored,
toggled, restored), whether Leaflet is loaded eagerly, the office map's
lazy load and both toggles, and the exported `KVOT` API surface.

Per page, additionally:

| Page | Covered |
|---|---|
| index | project cards, contact icons and their titles, copy buttons, links, meta description |
| 404 | cards, `<base>` resolution, robots |
| logn | distribution tabs, metric tab set, input count, the computed result text before and after entering μ and σ |
| proj | a WGS 84 → RT 90 → SWEREF 99 conversion field by field, bulk conversion, zone tables, `fmt_dms`, point-in-zone |
| rdc | element tree, cytoscape/jQuery/Plotly readiness, decay data loaded, selecting an element |
| skbref | rule counts, the in-page guide fixture, SKB collation, chemical-formula detection, rule packs |
| skb_qa_summary | privacy note, filter ids (now including the two parameter switches), `normalize`/`esc`/`csvCell` |
| karaoke | language, control ids, player and lyric stage, page globals |
| arsredovisning | **Del A**: a small SIE 4 file written in the test itself is dropped on the page, and the fingerprint records what it said about itself, how many accounts came through, how many stayed unmapped, that the statements balance on their own, the computed resultatdisposition, and — the point of the whole thing — that the iXBRL the page writes passes the page's own checks with no errors. The Word and PDF exports are built from that same document and checked for shape — the title-page block among them, since it is neither heading, paragraph nor table and fell out of the exports until it was given a kind of its own — block counts by kind, the two media types, and the Times metrics that drive wrapping and right-aligned amounts. Every field carries where its value came from — the bookkeeping, a derivation, a calculation, a default, an earlier annual report, or the user's own hand — and the fingerprint records those, since a report that cannot say which of its figures were interpreted rather than read is worth less than one that can. A small .docx is built with the page's own zip writer and read back with its zip reader — the only place those two meet — and the fingerprint records what was recovered from it, where each value came from, and that nothing reached the form until it was asked for. The draft step records that a snapshot round-trips through storage and comes back complete, and — the one line there that is a promise rather than an observation — that no personal number reaches it. **Del B**: the scope block that says the page cannot file anything, the six-step count, every declared control, the three handlingstyper, and the reference headings that say what filing actually requires. A complete iXBRL filing is built in the test file itself and fed through the page: the findings and their levels, the SHA-256 and byte length of the fixture, and that a form organisationsnummer differing from the file's is reported. The page once built the three API request bodies and offered a local mTLS proxy to send them through; that was removed deliberately, since call objects that can never be sent look like a way forward without being one. Its absence is pinned — every id it used, and the module's export surface — so it cannot drift back in unnoticed |
| inkomstdeklaration | the declarations on offer and the blanketter in each, with the field counts that come from Skatteverket's own field-name tables; that the century digit is prepended correctly (16 for a company, 19/20 for a person), since without it the whole file is rejected; that account 8999 resolves to *both* halves of the profit/loss pair and that a profit and a loss each pick the right one, which was wrong on the first attempt and visible only as a different field code in the file; and, from a small SIE file, the filled räkenskapsschema with each row's source, the period derived from the financial year end by the statutory rule — it depends on which month the year ends in, not on the year, and getting that wrong produced a period that was not open, which Skatteverket reports only as an invalid form type — the warning the page now gives for a wrong period, both generated files, and that the bytes are ISO 8859-1 with CRLF rather than UTF-8. Also what the tax-adjustment sheet gets filled with — only what is mechanical: the year's result and the booked tax moved from the räkenskapsschema, and the closing over/under figure summed from the rows above using the form's own preprinted signs, which updates as you type. Also that two INK4DU blocks become two `#BLANKETT` records in the file — Skatteverket requires one per part-owner, which a map keyed by form name could not express — and that a BLANKETTER.SRU reads back into blocks. Also that the main form gets its two transferred figures — INK2S 4.15 says on its face that the surplus moves to point 1.1 — and that they follow the same keystroke as the sum; that the financial year's dates are filled on every form carrying the codes while a block holding nothing but those two dates stays out of the file; and what the *Lägg till blankett* picker offers, which follows the choice in step 1: its groups, the count, and that INK4DU is absent from an INK2 filing until *Visa alla blanketter* is ticked |
| uppsala, solna | the SL board module is present, its refresh interval and state table, the relation heading, the Trafiklab attribution link, the link to the other direction, the line diagram with its station count, its two direction lanes and legend, the stale-data threshold, and that nothing resembling an API key is in the page. The GPS layer is off unless `vehiclesUrl` (or the `kvot-sl-vehicles` storage key) points at the Worker in `workers/sl-vehicles.js`; without it the boards run on forecasts alone, which is what the fingerprint records |

`test-actions.py <page>` covers the control wiring: every element declaring a
`data-on-<event>` attribute is given that event, and its handler must fire
exactly once. Double-firing is the specific regression the design guards
against — a checkbox emits `click` then `change`. It also checks that an
unknown action name is reported, that a throwing handler is caught, and that
the failure banner appears.

    python3 test-actions.py rb.html      # expect 28/28
    python3 test-actions.py proj.html    # expect 39/39

## Determinism

A full run is byte-identical between runs. Two things had to be handled to get
there:

- the theme-toggle step persists a choice, so the stored theme is cleared at
  the start of each page;
- third-party console noise (the YouTube widget API, CDN and map-tile fetches
  the network happened to drop) varies run to run and is filtered out by
  origin. A failed request for one of *this site's own* files is not external
  and still shows up — that is how a mistyped script URL gets caught.

## test-chrome-buttons.py

Clicks the theme toggle and the office-map button on every page and checks
that the theme attribute, the page background, the button icon and the map's
visibility actually change.

    python3 -m http.server 8765          # from the repository root
    "$CHROME" --headless=new --remote-debugging-port=9222 --user-data-dir=/tmp/p
    python3 resources/tests/site/test-chrome-buttons.py

These two buttons exist only in markup that `site.js` generates at runtime, so
they are invisible to `test-actions.py`: that test enumerates the elements
carrying a `data-on-*` attribute and proves each reaches its handler, which
cannot detect a button that carries the wrong attribute name and therefore
never appears in the inventory. This test starts from the button instead, and
also fails if any element anywhere still uses the superseded `data-action`
name (karaoke.html's own row controls, which bind directly, are exempt).

## test-chrome-pdf.py

Analyses the same report as `.docx` and as `.pdf` and requires the same answer.
`../pdf/build-fixture-pair.py` writes one document in both formats; the `.docx`
states its own structure, so the checker's report on it is by construction the
right answer for that text, and any difference is a defect in the PDF
reconstruction.

    python3 resources/tests/pdf/build-fixture-pair.py resources/tests/pdf
    python3 -m http.server 8765          # from the repository root
    "$CHROME" --headless=new --remote-debugging-port=9222 --user-data-dir=/tmp/p
    python3 resources/tests/site/test-chrome-pdf.py

Beyond report equality it asserts that no rule fires on the PDF whose evidence
a PDF does not carry, that the PDF run invents no rule the `.docx` run did not
fire, and that italic and superscript survive — the one place `pdfFontResolver`
runs against real pdf.js font objects. See `../pdf/README.md` for why each of
those is a separate claim.

The target opens on `about:blank` so the cache can be disabled before anything
is fetched, and the loaded `skb-pdf.js` is identified before any measurement is
taken. Navigating first and disabling the cache afterwards leaves the page's
own scripts served from cache, which had this test reporting a stale
`resources/js/skb-pdf.js` as a code defect.

## test-chrome-presets.py

Importing chart presets on rb.html must merge, not replace.

    python3 resources/tests/site/test-chrome-presets.py

`importPresets()` used to pass the parsed file straight to
`savePresetsToStorage()`, which overwrites the storage key outright — so
importing a colleague's two presets destroyed every preset the user had built
up, silently, and then reported success. Nothing looked wrong: the imported
presets were all present. What was missing was everything else.

The test seeds a collection, drives the real `importPresets()` (stubbing the
file-input click so a file can be delivered to it), and asserts all four
properties that matter: a preset absent from the file survives, a colliding one
is replaced, a new one is added, and Default stays first.

## test-chrome-bulk-worker.py

proj.html's bulk conversion must run in its worker, and agree with the main
thread.

    python3 resources/tests/site/test-chrome-bulk-worker.py

The worker is assembled by serialising page functions into a blob, which drops
everything they closed over — the gausskruger module state, the zone tables,
and `point_in_ring`. It threw a `ReferenceError` on its first message every
time, and `worker.onerror` fell back to `convertMainThread()` without a word.
Every bulk conversion ran on the main thread, which is precisely what the
worker exists to avoid.

Both halves are asserted, because either alone would have passed while the bug
was present: the fallback is spied on and must not be taken, *and* the worker's
numbers must equal the main thread's. The `sweref_99_1200` pair is the
important one — a local zone with polygon bounds, so it exercises
`point_in_zone_bounds` → `point_in_ring` → `sweref99_zone_polygons`, the
dependencies that were missing.

The national pair, `wgs84_dd → sweref_99_tm`, is also checked for what it
*says* about each row, not only for agreement — agreement alone passed with the
old check. That check was a longitude band, 10.7–24.45°E: all of Norway east
of Oslo and most of Finnish Lapland were "in zone", and Sandhamn was in only
because a band knows nothing about the sea. "In zone" for a national system
now means inside Swedish territory out to the maritime median lines with
Denmark, Norway and Finland (`sweden_territory` in `sweref99-zones.js`, from
the Marine Regions land+EEZ union, generalised to 100 m), which the worker
reaches through `importScripts`. Six rows straddle the border on purpose:
Stockholm, Sandhamn and Ven inside; Halden, Tornio and Helsingør outside.
Sandhamn is an island Natural Earth does not draw, Ven sits in Öresund 4 km
from Denmark, and Tornio is across the river from Haparanda.

The local pair, `wgs84_dd → rt90_2.5_gon_o`, checks the other half of the
rule. A local RT 90 zone is a longitude band *and* Sweden — a band through
Sweden also runs through Norway and Finland, and these zones used to be bands
alone. Skibotn and Kilpisjärvi are inside the 2.5 gon O band (19.2–21.4°E) in
Norway and Finland; Luleå is in Sweden but east of the band. All three must be
flagged, for different reasons, and Kiruna and Gällivare must not be.

## test-chrome-file-origin.py

skbref.html opened from the filesystem rather than from a server.

    python3 resources/tests/pdf/build-fixture-pair.py resources/tests/pdf
    "$CHROME" --headless=new --remote-debugging-port=9222 --user-data-dir=/tmp/p
    python3 resources/tests/site/test-chrome-file-origin.py

No server: that is the point. Every other test here loads the page over http,
so none of them could see this. A page opened with `file://` has a null origin,
which makes every blob URL it creates `blob:null/...`. Given a worker URL it
considers cross-origin, pdf.js wraps it in a second blob that calls
`importScripts()` on the first — and a worker started from a blob cannot
`importScripts` a null-origin blob, so the worker died on every PDF:

    Failed to execute 'importScripts' on 'WorkerGlobalScope'
    The script at 'blob:null/...' failed to load

pdf.js then parsed on the main thread. The analysis was still correct, which is
why this went unreported for so long — what was lost was the speed, and what
was gained was an error telling the reader the page had stopped working.

Three things are asserted, because the first passed even while the bug was
present: that a report is produced, that no error reaches the page, and that the
worker actually receives the parsing rather than pdf.js quietly falling back.

## test-chrome-distributions.py

logn.html holding several distributions at once.

    python3 -m http.server 8765 --bind 127.0.0.1
    "$CHROME" --headless=new --remote-debugging-port=9222 --user-data-dir=/tmp/p
    python3 resources/tests/site/test-chrome-distributions.py

Only the selected distribution has panels in the DOM. Every other one is
computed from a store of what was typed into it, and the three ways that store
can go wrong are all silent:

**One distribution's values written into another's store.** The panels are
cleared and rebuilt when the selection changes, so what is on screen is kept
first. After a *distribution* switch the panels still hold the outgoing one's
values while the incoming one is already active — and the fields line up
exactly whenever the two were built from the same metrics. Selecting B after A
copied A's numbers into B and destroyed B's own. The panels are now stamped
with the distribution they were built for, and the store is written only while
that stamp matches. The test builds A and B on μ and σ and C on mean and GSD,
precisely so that A and B collide and C does not.

**A typed value rebuilt from its own result.** Filling each panel from the
distribution's μ and σ is what lets a metric swap carry the distribution
across, and applying it to a value the user typed turns 50 into the 50 that
comes back out of `exp(ln(50))`. A stored value now wins, and the derived value
fills only what has none.

**The distribution forgotten between two metrics.** Swapping σ for GSD passes
through a moment where only one metric is selected and the distribution is
undetermined. Treating that as "no result" threw away the μ and σ that GSD's
starting value is derived from, so it offered the template default of 1 instead
of e^σ. A half-filled form is no longer a reason to forget; a contradictory one
still is.

It also asserts that one distribution that does not resolve leaves the others
on the chart, and that with a single distribution the chart draws the exact
five traces it drew before there could be several — that being the case every
existing user of the page is in.

The chart opens on the log scale, so the linear branch is no longer reached by
simply loading the page. Unticking `ln(x) view` has to give the same
distribution over the same percentiles, which is the same axis range
exponentiated, and that is checked rather than assumed.

Data is fitted to a distribution of its own, so it shares one with nothing: it
is disabled while a metric is selected and every metric is disabled while it
is. Both directions are asserted, and so is the pair of clicks that should
change nothing. What deselecting must not throw away is the pasted values — the
store keeps what μ and σ cannot reconstruct, and losing a data set to a
mis-click would be worse than offering it again. The raw-data switch is checked
to take the histogram and the step CDF off the chart without taking the fit
with them.

The chart is open when the page loads, which is two claims rather than one:
`drawChart()` refuses to run against a closed `<details>` because it has no
dimensions to size to, so the test reads the trace list and the plot width
before touching anything.

Finally the two chart switches, because switching a thing off must also switch
off what validates it. The shade percentiles describe the band and nothing
else; leaving them validated meant a range left over from an earlier chart
blocked every redraw while the band it described was not being drawn at all.
The test puts a shade percentile outside the chart bounds, confirms it is
reported while the band is on, and confirms it stops blocking — and that the
fields grey out — once the band is off.

## test-chrome-rdc-mobile.py

Which selections put rdc.html's element list away on a phone.

    python3 -m http.server 8765 --bind 127.0.0.1
    "$CHROME" --headless=new --remote-debugging-port=9222 --user-data-dir=/tmp/p
    python3 resources/tests/site/test-chrome-rdc-mobile.py

Below 600px the list is laid over the graph rather than beside it, so it is
only up when it is wanted.

It starts out of the way: the page chooses U-238 for itself and draws its
chain, and opening on a list of every element with that chain behind it made
choosing one for you pointless. The list is one tap away on the control that
floats over the graph, and the test taps it.

Drawn is not the same as reachable, so the chain's bounding box is checked
against the viewport. How far out the graph could be zoomed was a fixed 0.5,
and U-238's chain — 933 by 1279 — needs **0.375** to fit a phone: `fit()` was
clamped to the floor and quietly did nothing, leaving the bottom of the chain
off the screen with no way to pull back to it. A desktop needs 0.614, which is
why the floor looked right for years. The floor now follows what is on screen
— recomputed rather than simply lowered, so a two-node chain still cannot be
zoomed away to a speck.

Choosing a nuclide moves the list out of the way, and everything turns on which
selections count as choosing. jstree reports all of them through one `changed`
event:

- the page picks U-238 for itself once the list has loaded. Putting the list
  away for that would mean it is never seen;
- re-sorting rebuilds the list, and jstree restores the selection afterwards.
  Nothing was chosen;
- a tap, a key press and a name typed into the search field are each a person
  asking to see a chain.

The first attempt asked whether anybody had touched the page yet, which
separates the startup choice from a tap and nothing else: the touch that
re-sorted the list also answered it, so sorting on a phone made the list
vanish. What separates them properly is the DOM event jstree passes on — it has
one for a tap or a key press and none for a selection it restored by itself.
The search field selects on the person's behalf and says so explicitly.

The test taps the real controls with touch events and hit-tests each one before
using it, because a control that has been covered or moved still reports its
old box. It also runs the same selections at desktop width, where the list is
beside the graph and nothing should ever move it.

## test-chrome-rdc-chart.py

Who decides whether rdc.html's chart window is up.

    python3 -m http.server 8765 --bind 127.0.0.1
    "$CHROME" --headless=new --remote-debugging-port=9222 --user-data-dir=/tmp/p
    python3 resources/tests/site/test-chrome-rdc-chart.py

It used to follow the inventory with no way to say otherwise: it appeared the
moment any nuclide had an initial inventory and vanished when the last one was
cleared. There was no toggle, and the title bar's close button was hidden by
the dialog's own `no-close` class, so a chart in the way could only be got rid
of by emptying the model.

It still follows the inventory until somebody says something — adding a first
becquerel shows what it does, which is how the page is discovered. From the
first use of the toggle or the ×, that choice holds, and the two states it has
to survive are exactly the ones the old code could not express:

- **dismissed, then the inventory changes.** The window stays down;
- **asked for, then the inventory is cleared to nothing.** The window stays up,
  and says why it is empty rather than showing bare axes with a modebar over
  them.

Closing because there is nothing left to show is not the user saying anything,
so that path must not be recorded as their choice — otherwise the first
automatic close would freeze the window down for the rest of the session. That
is what the `null` state is for, and the test walks through it in both
directions.

The placeholder is drawn with `Plotly.react` and a config of its own, which is
the part worth guarding: `react` applies a config, so the modebar disappears
with the data and the full one — including the CSV and lin/log buttons added by
hand — has to come back with it. The test counts the buttons on both sides.

Dragging the window to a different width was impossible for three reasons at
once, and the test drags the real handles and reads the width back:

- jQuery UI hangs its resize handles off the **outside** of the frame
  (`right: -5px`) and the frame is clipped so its rounded corners hold. The two
  met at a 2px sliver no pointer could find.
- `minWidth` was the same number as the width it opens at, so even a caught
  handle could not narrow it.
- jQuery's `.trigger()` walks a simulated bubble path that **ends at window**.
  The `resize` jQuery UI fires on the dialog for every frame of a drag arrived
  at the page's `$(window).on('resize')` handler as though the screen had
  changed; that handler set a dialog option, jQuery UI answered by re-applying
  `options.width`, and `options.width` stays the old width until the drag
  stops. Every frame was undone as it was drawn. A native `addEventListener`
  hears only real window resizes.

The settings row is checked with it: a window that can be narrowed is only
useful if what is in it follows. Its columns now answer to the window's own
width through container queries — the viewport queries they replaced could
never match a 510px window on a 1400px screen, which is also why the
"Interactive model" badge was sliced in half at the default size.

Two more things are checked because they are invisible until someone is holding
a phone. The window fills the screen there rather than floating in a 374px box,
and is neither draggable nor resizable, since either could only take it off the
screen. And the × has to be the thing under the thumb: the site's menu button
is fixed at z-index 1000000001 in the same top-right corner and took the taps
meant for it until it was hidden for the duration.

Finally, the window takes focus itself on opening. jQuery UI gives focus to the
first tabbable element inside, which is the quantity menu — a menu nobody asked
to open, in front of the chart they did.

## test-chrome-sl-idle.py

Whether the SL boards stop calling the network when nobody is looking.

    python3 -m http.server 8765 --bind 127.0.0.1
    "$CHROME" --headless=new --remote-debugging-port=9222 --user-data-dir=/tmp/p
    python3 resources/tests/site/test-chrome-sl-idle.py

### Where the positions come from

The boards first polled a Cloudflare Worker wrapping Trafiklab's GTFS-RT
`VehiclePositions`. That feed turned out not to name its lines: of 554 vehicles
carrying a position, **7** had a `route_id`, and one of those resolved. The
`trip_id` it does carry is a GTFS *static* id, so naming a line through it
needs the static dataset and somewhere to keep it.

They now use Trafikverket's `TrainPosition`, joined on the train number. SL's
`journey.id` is the date followed by the five-digit advertised train number -
`2026091302272` is train 2272 on 13 September - and Trafikverket keys positions
by exactly that number. Checked against both live APIs at once: **16 of 23**
journeys on these corridors matched a position, the other seven being services
that had not departed yet.

That replaced a nearest-fix-on-the-same-line-going-the-same-way match, whose
radius had to be sized against the corridor's median hop and could still pair a
fix with the train behind it. Identity beats proximity - and it removes what
made the old approach risky at all: the E4 runs beside the rail, so an unnamed
road vehicle inside the corridor would have been drawn as a train. Trafikverket
carries trains only, so an unmatched fix there is a real train - SJ, Malartag,
freight - which is the honest answer to whether the track is busy. Those are
labelled by train number and never given an invented destination.

`characterise.py` also checks that no page contains a 32-hex-character string,
which is the shape of a Trafikverket key. The key lives in the Worker's secret
store; these pages are world-readable.

### Direction, and the third departure

Three faults the live boards showed and the tests did not, all fixed together:

**Every unnamed train ran backwards.** `runsForward` decides which way along a
segment a fix is going by comparing the train's compass bearing with the
segment's. The inline version read `diff > 90` - the exact opposite of the
comment directly above it. It stayed hidden because a train matched to a
departure takes its direction from SL's `direction_code` instead, so only
trains the board could not name were reversed. Caught by checking the rule
against six live trains of known direction: `diff < 90` agreed six times,
`diff > 90` none. The logic is now a named, exported function with a truth
table in the test.

**Trains on the next track were drawn on this one.** `GPS_CORRIDOR_KM` was 3,
inherited from the GTFS-RT days when a fix could not be tied to a journey and
the allowance had to cover the bend of a rail the diagram draws straight. Ten
rounds of live sampling on both corridors: every train SL actually lists on the
stretch projected within **0.43 km** of the line, while trains on neighbouring
tracks sat at 1.96, 2.17, 2.34 and 3.40 km. A clean gap, with 3 km on the wrong
side of it. Now 1.2 km.

**The board showed two departures when there were three.** `FORECAST_MIN` was
180, so late at night the third train - often tomorrow's first - fell outside
the window. The API caps the answer at three per line and direction whatever
window is asked for, so widening to its 1200-minute maximum costs no extra
requests and simply stops hiding the third. Being on another date it is shown
as a clock time with a `tomorrow` label, because "04:26" seen at half past
eleven at night otherwise reads as four hours ago.

The stub honours `forecast` exactly as the real API does. Without that a
three-hour window would pass a test about showing a departure sixteen hours
out; with it, the old constant fails the check with "2 shown (1 hero + 1 rows)"
- the reported symptom, reproduced.

One counting trap: the first departure renders as a `.sl-hero`, not an
`.sl-row`. A probe that queries only rows reports one fewer departure than the
board is showing, which cost a round of chasing a bug that was not there.

### Only the pendeltåg

Trafikverket carries every train on the rails, so a fix matching no departure
is a real train - SJ, Mälartåg, Upptåget, freight - and these used to be drawn,
numbered rather than named. They are not any more. A chip reading `7856` beside
one reading `40` invites the reader to work out what it is, and the board has
no answer: the position feed carries no line and no headsign.

Which lines count is now named outright, `lines: ['40', '41']`, rather than
inferred from what calls at the home station. Both rules are needed for
opposite reasons, which is why neither alone worked:

- line **43** shares Stockholm City and Odenplan with 40 and then branches off,
  so it must not be drawn heading for Solna where it never arrives - the
  home-station rule handled that one;
- line **41** runs the Arlanda-to-Upplands-Väsby part of the Uppsala corridor
  without ever calling at Uppsala C, so the same rule threw it away. 41 is a
  pendeltåg that genuinely shares that track.

The stub feeds two positions between Uppsala C and Knivsta: `2269`, which the
departures stub says is already running, and `9999`, which matches nothing. One
must be drawn as line 40 and the other must not appear. Against the previous
code the second check fails with `1 unnamed chips`.

Line 41's chip is Trafiklab's `#862699` rather than the band lilac, because a
chip rides on its own band and a 41 in the band's own colour disappeared into
it.

### The diagram, in Trafiklab's idiom

The track diagram is drawn the way Trafiklab's own landing page draws a
network, taken from their stylesheet rather than guessed at: bands `#F4BFFF`
and `#FFF199` at stroke-width 20 in a 60-tall box, stops 48px white with a 12px
`#232323` ring, a stop serving two lines drawn as one tall marker across both,
flat colour chips for labels, and motion eased rather than linear. The single
rail became two bands - the lane a train runs in is now the line it rides on.

Their type is a *condensed* face, which this diagram gets for free: the SVG uses
`preserveAspectRatio="none"`, so the viewBox is stretched to the element and the
two axes end up scaled by very different amounts - about 0.37 across against
0.85 down on a phone. Text comes out condensed, which suits it.

Shapes do not get off so lightly. A circle comes out an egg and a chip comes
out a sliver, so **every horizontal measurement of a shape is divided by that
ratio before being drawn**. The test asserts the invariant this creates: a
chip's rendered width-to-height ratio must be the same at 390px as at 1280px.
It is 1.50 at both. Against the previous code it is **0.72 on a phone and 1.21
on a desktop** - the chips really were vertical slivers on a phone and lozenges
on a desktop, and nobody had noticed because both looked deliberate on their
own.

Two knock-on fixes, both from the same cause. Chips are now three times wider
in viewBox units on a phone, so the constant that decides when two of them
overprint had to become `42 * wide + 8` - a fixed 48 let them overlap exactly
where there was least room. And the "approaching" marker, parked beside its
station by a fixed 34 units, ran clean off the right-hand edge once the chip
width followed the screen; it is now offset by the chip's own half-width and
clamped to the drawing.

The stub that feeds this had to grow up too. It answered every corridor station
with identical times, so no journey could ever be placed *between* two stations
and the diagram drew no chips at all - the shape check came back `None` rather
than failing. It now advances each journey down the line and includes one
service that has already departed, so there is a train on the track and not
only trains yet to leave.

### Junctions, and trains that take them

A line that leaves this one, or joins it, is a straight stub running out from
under the stop marker - the stops are drawn after it, so the circle covers the
join and the branch reads as leaving the station rather than starting in
mid-air beside it. It is drawn at the same weight as the band it leaves.

The 45 degrees is not an equal rise and run: the two axes are stretched by
different amounts, so the run is multiplied by that ratio or the "diagonal"
comes out looking like nothing of the sort.

**Trains ride it.** A line 43 train past Odenplan is drawn a little way up the
Bålsta curve rather than ceasing to exist at the junction; a line 41 train due
at Upplands Väsby comes down the Märsta curve rather than appearing beside the
station out of nowhere. Both are the same sum - how far, in time, the train is
from the junction - and the position comes from `getPointAtLength` on the path
itself, so the chip follows whatever curve is drawn.

Two consequences the tests had to learn:

- a chip on a branch **changes height as it moves**, which is the feature. It
  is excluded from the "no chip changes height" check, which is about the band;
- it is off the band, so the sweep that spreads trains along the line must not
  shuffle it.

### A queue of trains that have not arrived

Several trains can be waiting for the same station. They were each placed at
that station's own position, so they all started on the same spot, and the
sweep then spread them out in whatever order they came out of the map - which
is why a train due in 8 minutes could sit further out than one due in 11. At
the first station on the board, where there is no room to the left at all, the
sweep spread them **rightwards across the platform**.

The queue is now built in arrival order, next train nearest the platform,
pinned so the sweep cannot shuffle it, and any train for which there is
genuinely no room is left off rather than drawn somewhere untrue. The full
order is in the departure list above the diagram.

The queue is flush with the **edge of the drawing**, not with the platform: one
waiting train sits at the far end of the space kept for it, and a second
appears beside it on the way in, rather than the first shuffling outward to
make room. The space then reads as a siding rather than a gap that opens and
closes. Order within it is still the order they arrive.

Room is only reserved at an end where a queue can actually form. Waiting trains
are drawn short of the first station in their direction of travel and never at
the board's own station - so at Uppsala C, which is both, nothing can ever park
to its left and the reserved space was simply empty.

How many fit is arithmetic, not taste: `clear + (n-1) * minGap + halfW + 2`.
Chips are 34 viewBox units wide (28px on screen - they hold a two-digit line
number and nothing else), and the end margin is that sum for three, capped at
235. The cap matters: uncapped, the same sum on a phone is 280 units and would
leave five stations 88 units apart with 72-unit chips between them. As it
stands a desktop fits three and a phone two.

### A train that has not arrived

A "not here yet" marker is parked short of the station it is due at, on the
side it is coming from, clear of the stop rather than drawn across the
platform. Two things had to change for that to hold:

- the sweep that spreads trains apart would push the marker over its own
  station, so those chips carry a bound the sweep respects. The bound is
  clamped to the drawing, not applied after it - the first version put a chip
  45px off the right of the panel;
- **the margin at each end of the drawing cannot be a constant.** Chips are
  drawn in stretched units, so on a 390px screen a chip is 88 viewBox units
  wide where on a desktop it is 52. A margin that was comfortable on one was
  45 units short on the other, and there was simply nowhere to put the marker
  beyond the last station. It now scales with the chip.

Getting the test to see this took a detour: a southbound train approaching the
*home* station is deliberately never drawn, so the stub's four southbound
services produced no marker at all and the check passed on an empty list. The
stub now runs one northbound service due at the far end.

### Trains stand one after another

Two trains too close together used to be stacked, one drawn further from the
rail than the other. Rows are gone: a train is nudged *along* the line until
the chips clear each other, which costs a little truth about where it is and
buys back the order they are in. The sweep only ever pushes a train away from
the one behind it, so they cannot swap places.

What the test asserts is therefore what was asked for - no chip overlaps
another, no chip changes height, and their order never changes - across a
14-step scene that alternates one gap across the old margin.

Two measurement traps, both of which produced failures that were not in the
code:

- a chip slides to its new place over a second, so a reading taken sooner
  catches trains mid-move and finds overlaps that are never on screen;
- `getBoundingClientRect` on a train's `<g>` includes its speed label and, at
  the time, its direction chevron. The chip body is 34.6px; the group was 42px.
  Measuring the group made neighbours look overlapped when only the arrow was
  crossing. The test now measures `.sl-train-body`.

### The rows that used to be here

Two trains too close together are drawn in different rows within their lane.
That row used to be `lift = (previous train's lift + 1) % 2` walked along the
lane - a chain, so one gap crossing the threshold flipped that train and every
train behind it, and the board redrawn every second had trains hopping with
nothing on the track having changed.

**The first replacement measured worse than the bug.** Placing each train in
the lowest row it fits in is local rather than chained, but a train sitting
near the margin still flips on the smallest drift: 5 row changes against the
chain's 3. The margins now differ by what they are for - a train moves only
when chips genuinely collide, and comes back down only when the lower row is
clear by 1.6x that. Between the two it stays put.

Getting a test that could tell the two apart took three tries, and the first
two were worthless:

- a steady drift sent the trains off the end of the corridor, so how many were
  left depended on when the test started;
- a wall-clock sine had every run sampling a different part of the cycle - the
  same code scored 5 one run and 0 the next;
- the phase is now stepped by the test itself, so every run walks the same
  path.

Even then, a scene that *sweeps* a gap through the threshold scores 3 against 3
- those changes are real, one train genuinely un-crowding and displacing the
two behind it. The symptom is a gap that **hovers**: alternating either side of
the old margin while staying inside the new hysteresis band. There the chain
rule scores **39 row changes in 14 samples** and the current one scores **0**.

### On a phone the panel is the page

Below 560px the introduction is hidden and the board runs edge to edge,
starting directly under the fixed header. Measured on a 390x844 screen, that
moved the panel's top from **226px to 43px** and cut 281px off the document,
which is the difference between the track diagram being below the fold and on
the first screen.

The site chrome goes with it, on request: header, footer, the hamburger, its
menu and the office map. `renderNav` inserts the toggle and the menu **after**
`<header>` rather than inside it, so hiding the header alone leaves a button
floating over the board - the rule names all five, and the test asserts none of
them is displayed rather than trusting the two obvious tags. `.content` is
positioned to sit between the two bars, so with neither there it is given
`top: 0` and the full `100dvh`. Panel top: **226px -> 0**.

What that costs, and it is deliberate: on a phone there is no way off these two
pages but the "other way" link at the bottom, and no theme toggle - the page
follows the phone's own light/dark setting. The desktop checks in the same
section exist to make sure the chrome was hidden *by the media query* and not
by accident everywhere.

That also set a trap for `test-chrome-buttons.py`, which clicks the theme
toggle on all eleven pages: the toggle lives in the footer, so at a narrow
ambient window size `.click()` would land on a `display: none` element and the
button would be reported dead when it is merely out of season. That test now
pins an explicit 1280px viewport.

Filling the screen is then a matter of letting the board have what is left
after the "other way" link - hence the flex column rather than a `100vh` guess
that would have had to know both bar heights.
`flex-shrink` is 0 on purpose: `.sl-board` clips its own overflow to keep its
corners, so a board allowed to shrink below its content would hide the bottom
of it rather than scroll.

The test resizes the viewport rather than reloading, since media queries
re-evaluate on their own, and checks both directions - that the phone layout
applies **and** that the desktop keeps its introduction, its inset and its
rounded corners. Against the previous CSS the four phone checks fail with
`still shown`, `x 12..378 of 390`, `top 226` and `14px`.

Overflow is measured element-by-element against `innerWidth`, never with
`scrollWidth`: a padded content-box widens the layout viewport itself, so
`scrollWidth` agrees while the element sticks out. This site has shipped that
bug twice.

### Gating

uppsala.html and solna.html ask the positions endpoint every three seconds, and
that endpoint is a Cloudflare Worker holding a paid-for key. A board nobody is
watching is that allowance being spent on nothing.

Three separate things are supposed to stop it, and because they are three
different mechanisms each is exercised on its own:

- **a backgrounded tab**, via `visibilitychange`;
- **the board scrolled out of the viewport**, via `IntersectionObserver` —
  a tab can be in front with the board a full page below the fold;
- **a visitor who has gone quiet**, via a 15-minute idle timer that any
  pointer, key, scroll or touch resets.

The first two are certainties; the third is a guess, and a departure board is
exactly the sort of page somebody watches without touching, which is why the
window is long, why the faintest movement ends it, and why `idleMs: 0` turns
it off for a screen meant to run unattended. The last section checks that
escape hatch actually works, because a wall display silently pausing after a
quarter of an hour would be the worst failure of the lot.

The test counts the fetches the page really makes, through a `fetch` stub
installed with `Page.addScriptToEvaluateOnNewDocument`. Installed after load it
would race the board's own first fetch and undercount. Asserting on call counts
rather than on internal state is what lets the same file run against an older
sl-board.js and report failures instead of crashing: against the previous
visibility-only code it reports 8/24, with **2 vehicle calls and 4 departure
calls in the 4 seconds the board sat out of view**. The hidden-tab checks pass
there too, which is right — that gate already worked.

Resuming has to refetch immediately rather than wait for the next tick, so
returning to a board does not present whatever it was showing when it stopped.
A paused board is greyed and says which of the three reasons stopped it: a
departure board quietly displaying minute counts it is no longer checking is
the one failure it must never have.

The last section measures something the rest of the file caused. `.sl-meta`
sized itself to its contents at the right-hand end of the head, so every time
the text beside the live dot changed - "Live" to "Updated 12s ago", and now
also "Paused - not in view", which is longer than any of the old strings - the
whole block grew leftwards and carried the dot with it. A status light that
jitters once a second. Against the previous CSS the test reports a **127.4px
swing**.

`.sl-meta` is now a grid filling the width the relation leaves. The dot sits
*after* the text (`#sl-live`'s `::after`), so what pins it is the text block
being aligned to the **end** of its column: the right edge stays put, the text
grows leftwards from it, and the clock holds the column beyond. Aligning to the
start instead would hand the jitter straight back, the dot riding on the end of
a string that changes every second - so the test measures `rect.right`, the
edge the dot is actually on.

A second check asserts the left edge *does* move, across 8 distinct positions.
Without it, a layout that froze everything by clipping the text to a fixed box
would pass the first check while quietly truncating "Last update 23:45 -
retrying".

**Two things move next to that dot, and the first version of this section only
tested one.** It stopped the board so the text would hold still - which stopped
the clock as well, so the clock never varied and the section passed while the
dot was visibly twitching once a second. The clock was the worse offender:
RawengulkSans has no tabular figures, so `1` measures 2.22px where `3` and `8`
measure 6.02px and `hh:mm:ss` swings **22.5px** between `11:11:11` and
`23:33:33`. `font-variant-numeric: tabular-nums` is set and computes, but the
font offers no `tnum` feature for it to switch on, so it does nothing.

Every character of the clock now gets a cell of its own, the width of the
widest digit - what tabular figures would have done, done in the layout. The
section samples the dot for twelve seconds with the board **running** and the
seconds really ticking, then checks the extremes a twelve-second sample cannot
reach by laying out the widest and narrowest possible times. A failure prints
which of `clockW`, `liveW`, `metaW` or `cells` also varied, so it says what
moved instead of needing a rerun to find out.

The section runs last, because the text part stops the board.

One harness note: this file disables the HTTP cache. The page URL is
cache-busted but its stylesheet and script are not, and Chrome will happily
serve the previous run's `sl-board.js` against the current `sl-board.css` -
which produced one genuinely confusing failure where the synthetic cell checks
passed and the live clock still jittered. New CSS, old JS.

## test-chrome-theme-default.py

Which theme a page starts in, given the system setting and what is stored.

    python3 -m http.server 8765 --bind 127.0.0.1
    "$CHROME" --headless=new --remote-debugging-port=9222 --user-data-dir=/tmp/p
    python3 resources/tests/site/test-chrome-theme-default.py

uppsala.html and solna.html fill the screen on a phone and hide the site
chrome, theme toggle included - so a visitor whose phone is set to dark got a
dark board and no way out of it. Below the layout's own 560px breakpoint those
two pages pin light as the **default**, by putting `data-theme-default` on
`<html>`; `site.js` falls back to that instead of the system when nothing is
stored.

A default is not an override, and that distinction is what the file is really
testing. Nine rows: the phone case in both pages, a light system (unchanged), a
desktop-width board (follows the system again), two other pages (untouched),
and a stored choice beating the pinned default in both directions. A change
that fixes the phone by breaking any of those cannot pass.

Two things it does deliberately rather than conveniently:

- the system setting is **emulated** with `Emulation.setEmulatedMedia`, not
  taken from whatever the machine running the test happens to be set to;
- `localStorage` is written with `Page.addScriptToEvaluateOnNewDocument`, since
  each page decides its theme in a `<head>` snippet and a value written after
  load would be read far too late to matter.

The inline snippet and `site.js` both have to agree, because both run: the
snippet sets the attribute before first paint to avoid a flash, and `site.js`
re-applies `storedTheme() || systemTheme()` afterwards. Getting one right and
not the other looks like it works until the page finishes loading.
