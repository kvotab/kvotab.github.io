# Kompartment — guide

Compartment modelling in a browser tab. Draw the boxes, say what flows between
them, press Run: a system of ordinary differential equations is assembled from
what you drew, integrated by a stiff solver, and plotted. No build step, no
dependencies, no server-side code — `index.html` and the files beside it are
the whole of it.

It is built for the kind of model a radiological safety assessment is made of:
inventories in becquerels moving between compartments over a hundred thousand
years, indexed by radionuclide and by landscape object, with decay chains,
solubility limits, discrete events and a far-field pathway. It reads the
project files those assessments are usually written in (`.eco` and `.eas`), so
an existing model can be opened, run and compared rather than retyped.

One deliberate, opt-in exception to "no server-side code": three of the
solvers are SciPy's, run through Pyodide, and fetching that runtime is the only
time this application talks to anything but its own origin. Nothing downloads
it unless you choose one of them, and every other part of the program works
offline. See [Solvers](#solvers).

**This guide is the whole of the user documentation.** It is long because the
application is, and it is meant to be read in pieces: the contents list on the
left of the Help tab is a map of it. If you are starting from nothing, read
[Running it](#running-it) and [Your first model](#your-first-model), then come
back for the rest. [INTERNALS.md](INTERNALS.md) is the other half — how the
machinery works.

**Reading this inside the application.** The **Width** control at the top right
of the Help tab sets how far the text runs before it wraps: *Narrow* for prose,
*Wide* for the reference tables, and *Full* to give the contents column back to
the page as well.

## Running it

**Do not open `index.html` by double-clicking it.** The app is built from ES
modules, and browsers refuse to load those from a `file://` page — you get the
toolbar and tabs but nothing behind them. Serve it instead:

```sh
cd kompartment
python3 serve.py          # http://localhost:8080/
```

(If you do open the file directly, the page says so and gives you this command.)

Use `serve.py` rather than `python3 -m http.server`. The stdlib server sends no
`Cache-Control` header, so browsers reuse JavaScript modules they already
hold — and a Worker keeps its own module cache on top of the page's. Edited code
then keeps running, and the app reports things the source no longer says.
`serve.py` sends `no-store`, so a plain refresh always picks up your edits.

The footer shows a **build** stamp. If it looks older than your last edit, you
are looking at a cached copy: hard-reload once (**Cmd+Shift+R**), and switch to
`serve.py` so it cannot happen again. (A test keeps the stamp honest — it fails
if a source file is newer than the stamp, so it cannot quietly start crying
wolf.)

Modules are cached **individually**, which is what makes this confusing rather
than merely annoying: an edited file can meet an old one, and the two disagree
about what the program is. The commonest symptom is a solver the list offers but
the engine will not run, and that one now says so in as many words rather than
reporting an unknown solver.

**Notices** — what just happened, why an edit was refused, that the block you
clicked is not drawn on this diagram — appear as a panel over the bottom of the
window, above the footer, and go after a few seconds (longer for a warning, and
at once if you click it). They are deliberately outside the layout: a notice
arrives because of something you clicked, and one that took a line of its own
pushed the panels, the diagram and the footer down as it appeared, so the
interface moved under the hand that caused it. Freed from the header a notice
can also wrap, which is worth more than it sounds: `'p12' is still used by T1.
Change those equations first.` fits, rather than being cut off at the ellipsis
with the half that says what to do. A notice raised inside the settings dialog
appears in the dialog, since the backdrop dims everything behind it.

**A problem with the model is never a notice.** Notices are for news; a model
that will not run is a state, and it takes the strip under the tab bar and
stays there until it is fixed. The strip lists what is wrong, one line each,
and every line names the block it is in as a button that goes there —
`C1 · initial · Unexpected 'q' (at character 2)` — so a broken equation is
reachable from whichever tab you were on when it broke. It does move the panels
below it, on purpose: it is the reason there are no results.

That covers three kinds. **Equations are re-scanned on every edit**, so typing
`0q` into a compartment reports itself immediately, and so does an equation
three blocks away that a rename has just broken — you do not have to be looking
at the field. Both halves of a block's value are checked, the default and every
per-index entry, since a model whose default is fine and whose Cs-137 entry is
`0q` is exactly as unrunnable.

**The simulation settings are checked too**, and each problem is keyed to its
setting, so the field that is wrong is the field that goes red — with the
reason in its tooltip. What is checked: the time span (the end after the
start), a non-negative start when the spacing is logarithmic, at least two
output points, and **both tolerances strictly greater than zero**. That last
one had no check anywhere: `rtol: 0` is a finite number, so the field accepted
it, `Project` had no opinion, and the solver then asked for `(0 / err) ** p` as
its step-size factor — which is zero, so it halved the step forever and failed
thousands of steps later with a stall naming neither the setting nor the value.
The engine refuses it now as well, so a hand-written file cannot slip one past.
A number out of range is *kept* in the field rather than reverted, marked, with
the reason above: reverting a mistake silently is how it becomes a mystery.

**A failed run** — a missing half-life, a solver that gave up — lands in the
same strip and is dropped when the next run is attempted. One mistake is one
line: a model the scan has already objected to is not handed to the solver at
all, since it would fail the same way and say so a second time in slightly
different words.

**And a block carries its own.** The Information view for a block shows what is
wrong with *that block* at the top, above what it is — the same fact the strip
carries for the whole model, where the reader is already looking. Red rather
than the amber of a unit mismatch, because a mismatch is a warning and the
model still runs, while this is the reason it does not.

**And the diagram says which block.** A broken block gets a red ring and a
small `!` in its corner, and a connection whose rate will not parse is drawn
red and dashed with its label to match. The ring is the same mechanism
selection uses — a wide stroke behind the body, so only its outer half shows
and the block's own outline survives, solid for a compartment and dashed for
everything algebraic — in the danger colour instead of the accent. The badge
is there as well because a red ring on a block whose *own* colour is red says
nothing, and it carries the message as its tooltip. A block that is both
selected and broken reads as broken: the selection is still legible from its
handles and its port dot, and of the two facts that is the one that stops the
model running.

**And the mark is carried up to where you are.** A fault in `foo.bar.Expr` is
found by browsing to it, and browsing starts at the top, where only `foo` is
drawn — so `foo` wears the ring and badge at the top level, `foo.bar` wears it
inside `foo`, and `Expr` wears it inside `foo.bar`, each badge saying how many
blocks inside have a problem and naming the first. The block tree puts the same
mark beside its rows, blocks and sub-systems alike, so a fault can be found by
walking the tree as well as by opening sub-systems one by one. Selecting a
sub-system lists what is wrong inside it on its Information page, block by
block and as links; selecting the block says the fault on its own page,
whether it is an equation's or something else the model will not build with.
Warnings — a unit that disagrees with its equation, a far-field release
delivered where it is counted twice — travel the same way in amber: the model
runs with them, which is why they are a different colour, and not a reason for
them to be harder to find. An error outranks a warning, so a sub-system with
one of each is marked red and says two.

**The strip lists the warnings too**, once nothing is broken — otherwise a
model with a dozen unit warnings wears amber badges on the diagram and in the
tree with nowhere to read them. The strip says *29 warnings — the model runs;
these are worth a look*, with each one named and clickable, and in amber rather
than red. A model that will not run
still says that first: the warnings wait until it does.

**A block can hold nothing.** A list with no enabled indices has width zero, so
a block indexed by it has no slots at all: it is not in the run, reports
nothing, and nothing can read it. That is a real thing to want — a calculation
case that leaves a waste type out empties the list rather than deleting every
block that mentions it — so the model runs, and the block is marked in amber
rather than the file being refused. Reaching *into* such a block is still an
error, caught where it is read.

**Not every warning is about a block.** A saved time outside the run is a
number written into the saved-times editor that the solver will never reach, so
it is dropped — quietly, until now: a series that saves three of its twelve
times and one that saves all twelve were the same object with the same count
beside it. All three ways that can happen are listed: a series entirely outside
the run, individual times outside it (named, so you can see which), and an end
past the run, which does not lengthen the run but moves the points, since the
spacing is worked out over the series' own ends. Such a row has no block name
to click, so it links to **saved times** — the editor that answers it — and
nothing on the diagram is marked, there being nothing to mark.

A badge on a sub-system counts **blocks** and the strip counts **faults**, and
both now say which. One block can carry several warnings — a unit that
disagrees with its equation at three indices is three — so *10 blocks with a
warning inside NearField* and *29 warnings* are the same model seen two ways.

**The strip shows six and opens out.** A model whose nuclide list has just been
renamed can have a hundred broken equations, and a strip a hundred rows tall is
one nobody reads — so it lists six, and the line under them is a button: *and
23 more — show all 29*, and *Show the first 6* to close it again. That button
is on the header as well as under the last row, and the header stays at the top
of the strip while the rows scroll under it — an opened list of thirty is
taller than the strip, and the control that closes it again should not be at
the far end of what it closes. The strip keeps its own height and scrolls
inside it, so an opened list never pushes the panels down the window.

**And the list can be switched off.** The warnings are worth reading once; they
are not worth reading on every edit for the rest of a model's life. **Hide** on
the warning strip puts the list away.

What stays is the **badge**: the amber circle with a `!` in it, on the block
and on its row in the tree, carrying the reason. What goes with the list is the
**halo** — the amber ring around the whole block, drawn in the colour selection
uses. The two are not the same size of statement: on a model where a third of
the blocks carry a unit warning the halo is most of the diagram, while the
badge is a mark in a corner. Somebody who has read the warnings and decided
about them wants a way to find one again, not a way to be told about it. A
*problem* is not affected either way: a model that will not run says so however
loudly it has to.

The way back is **⚠ 29** in the header, which is there only while the model has
warnings and their list is away — one button, in the place you were already
looking, rather than a menu on a canvas that three of the tabs do not show.
Right-click the canvas for **Show ▸ the warning list** does the same. The
switch is saved with the model, under `view`, because it is that model's
warnings that were read and decided about. Problems have no such button: a
model that will not run has to say so.

So a mistake now says the same thing in four places, each answering a
different question: the strip says *what and where*, the field says *which
input*, the Information view says *what about this block*, and the diagram says
*which block* — and the Run button's dot goes from accent to red, so even a
glance at the header distinguishes "not run yet" from "will not run".

**And results that are not this model's are not shown.** Every set of results
carries the model revision it was computed from, so the Chart and Table tabs
can tell. When they do not match, the plot and the table are replaced by a line
saying why, with a **Run** button when running is possible and a pointer to the
strip when it is not. The alternative — leaving the curves of the last model
that worked on screen — says nothing about which model they belong to, and the
only signs would be a dot on the Run button and a red border on one field in
one panel.

The exception is a run already on its way: with **auto-run** on, blanking the
chart for the third of a second before the new results arrive would be a
flicker on every keystroke, so the last results stay up while a run is in
flight. At rest, what is on screen is always this model's.

**A slow model says which slow thing it is doing.** Building a large model —
generating the derivative, the tangent function and the sparsity pattern — is
seconds before a single step is taken, and the first step can be seconds more.
The bar goes indeterminate and says *Building the model…*, then *Solving…*,
then starts counting. Before, it said nothing through both and looked like a
page that had stopped.

**The progress bar counts output points, not time.** A fraction of the span is
a poor account of how far a stiff run has got: the first per cent of the model
time can be a tenth of the work, so a silo model of 8,427 states sat at 0% for
its first ten seconds and read as a hang. What a run is actually producing is
its output points, and on a grid dense where the model is interesting — every
logarithmic grid, and every series a real file carries — the early ones tick
over quickly and the rest follow steadily. The model clock goes beside the
percentage, so something is moving even while the percentage rounds to nothing:
`24% · 2.6 year`. And building a large model is seconds of work before a single
step is taken, which the bar now says rather than sitting at zero:
*Building the model…*, with the bar indeterminate.

**That clock used to paint over the kvotab.se link.** The percentage sits in a
box sized for four characters — enough for `100%` and no more — and adding the
clock beside it made the text longer than the box without making the box
wider: the extra characters overflowed past its right edge and across whatever
sat next to it in the footer. The box now grows with its content, up to a cap,
with the overflow rule from the loading label as a backstop for anything still
longer than that.

**Auto-run starts off.** It is the switch that makes a keystroke start a solve,
and on an imported assessment of fifty thousand states that is a page that goes
away for half a minute every time a digit is typed — a cost paid by everyone
who opens one, to save a click for the people editing a small model. Tick it
beside **Run** and it behaves as it always did: a third of a second after the
typing stops, the solve starts. Everything below is about what happens when it
is on.

**Opening a model does not run it unless auto-run is on.** Running it whatever
the switch says is, on a large file, half a minute of a page doing something
nobody asked for. With the switch off, the chart says *no results for
this model yet, auto-run is off, so nothing will happen until you ask for it*
and puts a **Run** button in the space the curves would take. The JSON tab's
**Apply & run** is the exception, and says so on the button: it runs either
way, exactly as pressing Run does.

**An edit made while a run is going gets its turn when that run lands.**
Dropping it instead leaves the model dirty with nothing coming and only the Run
button to get out of it. For the solvers in this repository the window is
milliseconds and you would have to be quick; for the first SciPy run it is
*seconds*, spent downloading a Python runtime, and anything touched in that
window — including changing the solver again — would be lost. A **Run** pressed
during a run is remembered the same way, and honoured when that run lands even
with auto-run off. **Stop** is the one thing that clears it: an edit does not get to restart
what you have just stopped, and neither does the timer of an edit whose third
of a second has not elapsed yet.

**Stop also switches auto-run off**, and says so. Left on it is not an escape:
the next edit — or the one already typed a third of a second ago — starts the
very run you just stopped, and the only way out is to press Stop faster than
you can type. It is a control you set, so it changes visibly rather than behind
your back; tick it again, or press **Run**, when you want the model followed
once more.

**Auto-run stands down while a solve is slow, and says so.** Re-running on
every commit is only pleasant while a solve is quick, so past about a second
and a half it waits to be asked. What was missing was the *saying*: a chart
that stops following the model with the box still ticked reads as a program
that has stopped working. The out-of-date notice now gives the reason and the
number — *the last solve took 2.6 s under SciPy Radau IIA, which is long enough
that re-running on every edit would get in the way* — with the Run button
beside it. And the measurement is scoped to the solver that made it: SciPy's
solvers are there to be independent rather than fast, so one slow run under one
of them used to turn auto-run off for the rest of the session, including after
switching back to a solver that takes milliseconds.

The dot on the **Run** button has three states now rather than two — absent,
accent-coloured for *not run since you changed something*, red for *will not
run until you fix something* — and the button's own tooltip says which, since
the dot is decorative and a screen reader never reaches it.

## Your first model

```figure anatomy
 +---------------------------------------------------------------+
 |  New   Open   Import                Run               Theme    |
 +-------------+-------------------------------+-----------------+
 | Model tree  |  Build Matrix Chart Table ...  |  Inspector      |
 |  by         |                                |  what is        |
 |  sub-system |         the diagram            |  selected       |
 |             +-------------------------------+                 |
 |             |  problems | statistics | log   |                 |
 +-------------+-------------------------------+-----------------+
```

1. **New** — an empty canvas with the simulation settings filled in. It starts
   empty on purpose: a worked model is somebody else's, and the first thing to
   do with one is delete it. The picker beside the button has nine if you want
   one to read. The canvas says what to do next and has a button for it.
2. **Right-click empty canvas** and choose *Add compartment here*, and a box
   appears at that point. It is selected, and the
   right-hand rail shows its properties: name, initial inventory, unit,
   whether it may go negative, colour.
3. **Connect two boxes** — drag the round handle on a compartment's right edge
   onto another box. While you drag, legal targets are outlined and everything
   else dims, and a label at the pointer says what will happen on release.
   Dropping on empty space instead creates an outflow leaving the model.
4. **Give the rate a value.** A transfer's rate is multiplied by its source
   compartment, so `0.05` means 5% per year. To use a named parameter,
   right-click empty canvas for *Add parameter here*, rename it in the rail,
   then type that name as the rate.
   If the block is indexed, the field you edit here is the *default*; set
   individual index combinations under **Values per index** below it.
5. Press **Run**, or tick **auto-run** beside it to re-run as you edit;
   **Chart** shows the result.

```figure two-box
   [ Source ]  --- rate = k * Source --->  [ Sink ]
    1000 Bq                                   0

   A transfer carries rate x the amount in the compartment it leaves,
   so its unit follows from that and is never typed in.
```

**Right-click** is where the Build panel's controls live — there is no toolbar
above the diagram, so the diagram gets the room.

On **empty canvas**, four groups, in the order they are reached for — make
something, move something, go somewhere, then what is about the canvas rather
than about the model:

| | |
|---|---|
| **Add here** | *Compartment*, *Expression*, *Parameter*, *Inflow ▸* into any compartment, *Other blocks ▸*, *Sub-system* — and *Transport operation* when you are inside a transport. The block lands at the point you clicked, which is what the heading's *here* means and what a button on a toolbar can never do. |
| | *Other blocks ▸* holds the rest: lookup table, function, 1-D transport, 2-D far-field transport, index operation, aggregate, and *Recorder ▸* for the five that depend on what has already happened. |
| **Cut · Copy · Paste · Import…** | Cut and Copy act on the selection — right-clicking empty canvas does not clear it — and say nothing when nothing is selected. Paste names what it holds — where it will go is wherever the menu was opened, which is where the pointer already is, so that is in the tooltip rather than in the label. |

**Cut marks a move; it does not take anything away.** The blocks stay exactly
where they are, drawn dashed and faded to say they are going somewhere, until a
**Paste** names the place — and then they *move* there, rather than a copy
appearing and the original being destroyed. Cut a compartment, right-click
inside a sub-system, paste: it is now in that sub-system, at the point you
clicked, with its transfers. Cut and paste on the same canvas and it is simply
in its new position.

Nothing is deleted at any stage, so a cut you change your mind about costs
nothing and there is nothing to undo. **Any other edit calls it off** — an
undo, a value typed, another model loaded — and the blocks are left as they
were; a move whose source has been changed under it is a move nobody asked for.
Navigating is not editing, so going into a sub-system to paste there is exactly
what the mark is for. A **Copy** calls a pending cut off too, and a cut calls
off a copy: both answer the same Paste, so the last one asked for is the one
that is pending.
| **Leave X · Go to ▸** | Only when there is somewhere to go. |
| **Show ▸ · Add shape… · Save as picture ▸ · Canvas ▸** | The diagram's toggles, with *Transfer labels* among them since it answers the same question; then a shape to draw, a picture to take, and auto-layout, fit and zoom. |

The toggles are ticked in place and leave the menu open, since you rarely
change only one.

The grouping is deliberate. A context menu that has to scroll is one whose last
item you will not find, so the things reached for most stay at the top level
and everything else goes one step in — and the **Add here** heading says the
verb once instead of every item repeating it.

On a **block or a connection**, a menu of what can be done to it. **Its title
names what it is about** — `compartment Soil`, `parameter Kd`, `sub-system
NearField`, `3 blocks` — so the items under it say only what they do: *Copy*,
*Disable*, *Delete*, not *Copy Soil*, *Disable Soil*, *Delete Soil*. The name
once at the top reads better than the name on every row of a menu that is
entirely about it.
**Centre on the canvas** is first, above all of it. It brings the block to the
middle of the diagram at the zoom it is already at, going into its sub-system
first if that is not the one on screen. This is not *Fit to view*: fit answers
"show me everything", and on four hundred blocks that makes each one four pixels
across with the one you were looking for somewhere in it. The item is worth most
where the diagram is *not* what you are looking at — the same menu opens from
the block tree and from the Information view, so finding a block by name in a
tree of four thousand no longer means finding it a second time by eye. Picked
from either, it brings the Build tab forward with it. On a connection it centres
the two compartments it joins, which puts the arrow in the middle.

**The rest of every block's menu is in the same three parts**: what to make from
it, what to put on the clipboard, and what to do with the block itself — *Move
into*, *Disable*, *Delete* — in that order. A compartment is the one with anything to
make, under an **Add** heading: **Inflow**, an inflow from outside the
model, and **Transfer to** with every other compartment and *outside the model*
(one you are already joined to says how many transfers run there; picking it
adds another). A transfer offers **Starts at** and **Ends at** instead, each
listing the compartments and outside, which is the way to re-attach an end onto
a compartment that is currently off screen.

**A connection cannot be taken anywhere on its own.** *Cut*, *Copy* and *Move
into* are declined on a transfer or a source term selected by itself, and say
why: the arrow between two compartments is nothing without them — copied alone
it would paste pointing at blocks that are not in the copy, moved alone it
would sit in a sub-system its own ends are not in. Select the compartments at
its ends as well and it travels with them, which is the rule a copy has always
followed. Dragging one out of the tree by itself is refused for the same
reason. Escape or a
click anywhere else dismisses it. The arrow keys walk it, with ArrowRight to
enter a submenu and ArrowLeft to come back out.

**Escape abandons a gesture.** Whatever is being dragged — a block or a group
of them, a shape, either kind of resize, a bend point, a loose end, a selection
box, the canvas itself under a pan, or a connection being drawn or re-attached
— goes back to where it was. The key is listened for while the gesture is
running whatever holds the focus, since a press on a node takes the focus off
the canvas.

**The diagram takes the keyboard.** Tab reaches the diagram once — it lands on
the selected block, or the first when nothing is selected — rather than
stopping at every block on the way to the panel beside it; Enter or Space opens
that block's settings, and the arrow keys move the selection a grid step at a
time — one unit with Alt held, the same bargain a drag makes. The tab strip
along the top answers to the arrow keys too: Left and Right move between Build,
Chart, Table and the rest, Home and End go to the ends.

**Choosing what to chart.** The picker above the chart lists every output, and
a model of any size has more of them than one chart can hold. Narrow it with the
search box — the same rules as the block search, so `Water` matches anywhere
and `*I-129*` is a pattern over the whole label — with the kind chips, and with
one **selector per index list**, `Contaminants ▾`. **The box completes as you
type**: it lists the names the labels are made of — the blocks first, then the
indices, each with how many lines it reaches — so what there is to find can be
seen rather than remembered; Ctrl-Space or ↓ lists them all before anything is
typed, Enter or a click takes one, and Escape closes the list (a second Escape
clears the filter). A pattern with `*` or `?` in it is the box's own language
and is left alone. A selector says what it
filters and by how much in three words — `Contaminants · I-129`, `FlowPaths · 4 of
353` — and opens, on a click, into the indices that actually appear in the
results, as chips to switch on and off, with **All**, **None**, and a box to
find one by once there are more than a dozen. It closes on Escape or a click
elsewhere. Rows of chips in the open, one per list, do not scale: one model in
the corpus carries sixteen lists, one of them 353 flow paths long, and the rows
would run well below the fold before the picker or the chart was reached.
A sub-set shares its indices' names with the list it is cut from, so the two
are one selector — `Radionuclides` folds into `Contaminants`, and a nuclide chosen
there narrows a line indexed by either; the tooltip says which lists a selector
stands for. A mapped list, whose indices are its own, keeps a selector of its
own, and a list with one index in the results offers no choice and gets none.
The picker below draws three hundred chips at a time and says how many more
there are, with a button for them: a landscape model reports thousands of
outputs, and the filter is how a line is found in a list that long. A line
already on the chart keeps its chip wherever it falls in the list, since that
chip is the way to switch it off again.

**Thirty-two lines, in eight hues and four line styles.** The palette is the
validated categorical set, which is eight colours — assigned in fixed order,
because a filter that changes the series count must not repaint the survivors.
Past the eighth the hues begin again, and what tells one set from the next is
the *line style*: solid, dashed, dotted, then dash-dot. A series is a hue **and**
a pattern, so no two of the thirty-two look alike.

Cycling a palette on its own is the one thing a categorical palette must not do
— two lines the same colour are two lines you cannot tell apart — and the second
channel is what makes the repeat legible instead of a collision. It is carried
everywhere a series is shown and not only on the line: the label at the line's
end, the legend, the crosshair readout and the chip in the picker all draw a
short line in that series' own colour and pattern. A dashed line is drawn with a
butt cap rather than the round one the solid lines use, because a round cap adds
half a line width at each end of every dash and closes the gaps of the tightest
pattern.

A chart *opens* on one set — eight solid lines — rather than on all thirty-two;
the rest is there to be asked for. And the crosshair readout shows twelve rows
while every line fits in twelve, then switches to the largest values at that
time point and says how many it left out, because thirty-two rows is taller than
most charts.

**Zooming and panning.** **Drag a rectangle** over the part you want —
the conventional gesture, which is what a desktop chart does, and still the
quickest way to say "that peak, at that scale". A drag along one axis only
zooms that axis, which is what a chart is usually asked for: this decade of
time, at whatever the values do. **Scroll** to zoom about the pointer, the way
the diagram does. **Double-click** to show everything again.

**Panning** is a **shift-drag**, or a **middle-button drag**, or a plain drag
with **Drag to pan** ticked on the menu — which is also how anyone finds out
that panning is there. The modifier does the opposite of whatever a plain drag
does, either way round, so both gestures are always available and neither is
behind a mode you have to remember being in; the pointer shows which one it is
about to do. Panning works on an unzoomed chart too: moving a peak off the edge
to look at the shoulder of it is a fair thing to ask for, and refusing on the
grounds that everything was already on screen only made the gesture look
broken.

Zooming works in the space the axis is even in — the logarithm of the value on
a log axis — because halving the numbers of a four-decade axis would take it to
three and a half and look like nothing had happened. Lines are **clipped at the
plot's edge** rather than dropped at the last point inside it, so a line touches
the boundary it leaves through instead of stopping short of it; the direct
labels follow the window, and are spread apart *after* being clamped into the
plot, since a chart zoomed so that every line leaves through the top has four
labels wanting one height. A window that no longer overlaps the results — a
re-run whose answers moved somewhere else entirely — is dropped rather than
shown, because an empty chart reads as a model that produced nothing. Otherwise
the window **survives a re-run**: watching one decade of one peak while changing
a parameter is the reason to zoom in the first place.

**The chart's own menu.** Right-click the chart for what to do with it:
the two scales, the zoom, a picture of it, and the numbers as CSV. The scales
were two permanent checkboxes above the chart — two controls in the way of it
for a choice almost nobody changes, since log-log is how an
activity-versus-time result is read. They are ticks on the menu now, and the
Build tab keeps its settings the same way.

**Saving the chart as a picture.** **Save as picture ▸ SVG · PNG · JPEG**, on
that menu. Both routes *draw the chart again* rather than copy the pixels on
screen: PNG and JPEG onto a canvas at twice the size, because a bitmap scaled
up is a bitmap scaled up and a figure in a report is read at print resolution;
SVG through a Canvas2D-shaped surface that writes SVG instead of pixels
(`src/ui/svgcanvas.js`), so the lines stay lines and the figure can be zoomed,
re-lettered or dropped into a document at whatever size the page wants.

It is the same drawing code either way — `TimeChart._paint` takes a context and
does not care which it is. A second routine that emitted SVG would be a second
chart, and the two would disagree about a tick label or a dash pattern within a
month.

Two differences from the screen, both deliberate. **The legend is in the
picture** when the chart has more series than it labels at the ends of its own
lines: on screen that legend is HTML beside the canvas, and a picture has no
beside — a chart of sixteen lines with nothing naming them is the one thing a
chart must not be. And **the crosshair is not**: it says where the pointer was.
A picture of a zoomed chart is the window you are looking at, which is usually
the point of saving one.

**Every chip you press is a constraint.** To be listed, an output has to be
indexed by each list you have chosen from *and* carry one of the chosen indices
there — so a filter nothing satisfies lists nothing, which is the whole point of
being able to see what a filter did.

Two consequences worth knowing, because a looser rule reads as a bug in both
cases. A line with no dimension of a constrained list is out:
filtering `landscape.json` to `Radionuclides = I-129` no longer lists the three
`TotalWater [Object]` lines. They are a sum over nuclides, so they are *about*
I-129 in a sense — and 22 lines of which three did not mention I-129 was a
filter you could not read. And two lists that share a name are two different
constraints: `Wetland` is Lake and Mire out of `Object`'s Lake, Mire and
Forest, so choosing the sub-set's `Lake` lists the four `WetlandLoss [·, Lake]`
lines and nothing else — where before it listed 54 of the 79, every Forest line
among them. The case the old rule existed to prevent is still prevented:
`Object = Mire` does not list `WetlandLoss [Tc-99, Lake]`, because WetlandLoss
is indexed by `Wetland` and not by `Object`, so it fails the constraint outright.

**Show these** charts what the filter found, up to the maximum; **Show none**
clears the chart; **Clear filter** puts the list back. Filtering never changes
what is charted on its own — it changes what you can reach.

The whole filter is one wrapping row, so on a wide window it costs a single
line and the chart keeps the rest. The layout follows the window in both
directions: the chart redraws at whatever width it is given, and the side
panels and the header give way rather than pushing anything off the edge.

**Reshaping connections.** Select a connection and it grows three handles: one
at each end and one in the middle. Drag an **end** onto a different compartment
to re-attach it there, or onto empty space to leave it open to outside the
model. Drag the **middle** to bend the line around whatever is in the way, and
right-click the line for **Straighten** to drop the bend again. That item is in
the menu whether or not the line is bent, so a line bent by accident has a
visible way back rather than a gesture to remember.

Double-clicking a connection opens its **settings**, the same as
double-clicking a box does. Straightening is on the right-click menu instead:
one gesture meaning two things depending on what is under the pointer would
leave the rate — the thing a transfer mostly *is* — without the shortcut every
other block has.

**Appearance.** Any block drawn on the diagram — compartment, expression or
parameter — can be given a **colour**, a **shape** (rounded, box, ellipse,
hexagon, cylinder, diamond) and a **size**. Colour and shape are in the
inspector; size can also be dragged from the grips on the selected node, and
double-clicking a grip resets it. Label ink is chosen from the fill's
luminance, so a dark colour gets white text and a pale one black — a custom
colour never hides the label.

A **connection** has the three things a line can say with: a **colour**, a
**weight** (hairline, normal, thick, heavy) and a **style** (solid, dashed,
dotted). Its look used to follow its endpoints and nothing else, which is right
until a model has thirty transfers — then telling one route from another is
what the drawing is for. The keys are the canvas shapes' own, `line_width` and
`dash`, so the file format has one way of describing a line, and the arrowhead
takes the line's colour.

None of it overrides what the diagram is *saying*: selected, joined to the
selection, hovered and carrying-a-problem all still show, because the colour
arrives as a custom property that the state rules override rather than as an
inline `stroke` that would beat them — and the widths those rules use are
`calc()` on the line's own, so a line you made heavy stays heavy when it lights
up. A connection's colour also paints its cell in the transfer grid, with the
rate and name inked from that colour.

**Folding a sub-system on the transfer grid.** The grid is square — row *i*
and column *i* are the same thing — so a sub-system can only be drawn as a
group if its blocks are a *contiguous run* of slots. They are: the grid is
ordered by walking the sub-system tree, a system's own blocks and then each of
its children, depth first.

A **folded** sub-system is one row and one column. Every flux in or out of any
block inside it lands there, and the several that then share a cell stack in it
the way parallel transfers always have — across a folded boundary they are
summarised as a count, because each of them belongs to a block that is not on
the grid, and a dozen stacked in one cell made the row a screen tall. What is
left over is the fluxes *between* two blocks inside it: those have no row and
no column left to sit on, so they are **counted** on the cell rather than
dropped — `4 blocks, 1 sub-system, 2 flux inside`. A grid that quietly stops
showing part of the model is worse than one that says how much it is not
showing.

An **open** one gets a header slot of its own as well as its members, which is
what gives the group a corner for its name and the caret that folds it back up.
A frame runs from the header to the last member, and a sub-system inside a
sub-system frames strictly inside its parent's. The frames are drawn as
composed `box-shadow` insets rather than borders, because a cell can sit on two
of them — a sub-system whose last member is itself a sub-system shares its
bottom and right edge — and borders cannot stack.

Inside a frame a block shows its **local** name: `Water`, not
`NearField.Buffer.Water`, because the frame already says where it is. The full
path stays on the tooltip. Folding one folds what is inside it, and opening one
opens the way to it, so a sub-system reached from a fold several deep does not
vanish behind a closed parent. None of it is saved or changes a number — which
sub-systems are open is a fact about the view, and a new model starts folded.

**What the diagram shows.** The toggles under **Show**, and a label mode under
**Transfer labels**, both on the empty-canvas menu. The ones worth a word:

- **expressions** — expression blocks (on by default)
- **parameters** — parameter blocks (off by default; a large model has many)
- **influences** — dotted arrows from what a block reads to the block that
  reads it, coloured by the source. This covers **every equation a block
  holds**, so a parameter feeding a transfer rate shows up, not just
  expression-to-expression links — including a rate that only differs for one
  index, a compartment's initial inventory and its dy/dt term, and a far-field
  path's travel time. A **function** is read by being called, so it has an
  arrow out to every block that calls it, wherever the call is written, and
  arrows in from whatever its body reads. It also covers the blocks a
  **reduction** names: an index operation or an aggregate has no equation, so
  its arrows are the only thing on the diagram that says where a total comes
  from. Either end may be a connection rather than a block: a transfer's
  name in an equation is its flux, so an equation reading one gets an arrow
  *from* that transfer's line — `Outflow = TCOut*C3` in
  `examples/four-compartment.json` is exactly that. What is deliberately not
  drawn is the flow itself: a transfer moves material between its two
  compartments, and the transfer arrow already says so. An influence is only
  drawn when both ends are on the canvas, so turning parameters on is what
  makes their influences visible. A sub-system is a fold in the diagram rather
  than a wall: an expression inside `NearField` that reads `Kd` out here gets
  an arrow to the `NearField` node, the same substitution the transfers make,
  and several dependencies that fold onto the same pair are drawn as one arrow
  that says how many it stands for.
- **lookup tables** — lookup-table blocks (on by default; each draws its own
  curve, which is the thing worth seeing at a glance)
- **index operations & aggregates** — the reducing blocks (on by default; they
  are usually a model's outputs)
- **functions** — the user-defined functions (on by default; a model that has
  any has one or two, and the arrows to and from one say what its body reads
  and which equations call it)
- **recorders & events** — the five blocks that depend on what has already
  happened, and the discrete events that drive them (on by default; a peak dose
  is a result)
- **outflow clouds** — the cloud where a flow leaves the model (on by default)
- **the warning list** — not a kind of block, and not the amber marks either:
  those stay whatever this says. It is the list of warnings under the tabs (on
  by default). Off for a model whose warnings have been read and decided about;
  **Hide** on the warning strip is the same switch from the other end, and the
  **⚠** button in the header is the quicker way back
- **Transfer labels** — what is written along each transfer and source line:
  its `name` (the default), its `rate` (with the donor it multiplies, for a
  rate coefficient), or `none`

These are saved with the project, under `view`.

**More than one transfer between the same two compartments** is allowed, and
often what a model wants: the routes between two places — advection and
diffusion, drainage and overflow — are separate processes with separate rates,
and summing them into one number by hand costs you the ability to name, plot or
switch off each of them. The engine adds their fluxes, which is what parallel
paths mean. On the diagram they bow apart so each keeps its own label, and a
transfer and its counter-transfer separate the same way rather than retracing
one line. In the **Matrix** a cell holds all of them, stacked.

**Selecting a block** thickens every line joined to it — what flows in and
out, and every influence that reads it or that it reads. They keep their own
colours rather than taking the accent, which stays reserved for the one block
the inspector is showing.

**The line of prose under the diagram is off by default.** It is six lines of
the canvas's height, and the canvas is what the tab is for — so **Show ▸ the
help line under the diagram**, in the empty-canvas menu with the other view
toggles, is where it comes from when it is wanted, and the 74 pixels go to the
diagram the rest of the time. It is a view flag like `show_parameters`, kept in
the project, so the choice survives a save. Nothing is lost by having it off:
the Help tab covers the same material at length, and every gesture it describes
is in a tooltip on the thing that performs it.

The canvas is inset from the panel by the same twelve pixels on all four sides.

**Tidying the diagram.** Drag a box to move it; drag the background to pan and
scroll to zoom. **The grid is the thing blocks land on.** One pitch — ten model units —
serves three purposes that have to agree: what a drag snaps to, what the
automatic layout rounds to, and what the lattice behind the canvas is drawn at.
They did not agree before: the grid was a fixed 20-pixel *screen* lattice that
ignored the camera, while a drag snapped to 10 *model* units, so the lines a
block appeared to land on were not the ones it landed on. Now the grid follows
the pan and the zoom, and steps up when the pitch would fall below nine pixels,
because a 2.5-pixel lattice at quarter zoom is moiré rather than a grid.

Both halves can be turned off, and they are separate settings, side by side:
**Canvas ▸ Show grid** stops drawing it, **Canvas ▸ Snap to the grid** stops
landing on it, and either is remembered with the model as the other view flags
are. Holding **Alt**
during a drag inverts whichever way the setting is set — snapping when it is
off, placing freely when it is on — read off the pointer move rather than the
press, so it can be taken and released in the middle of a gesture.

What snapping means here is *where the block lands*, not how far it moves. The
block under the pointer goes onto the lattice and the rest of a selection moves
by the same delta, so the one you are dragging aligns and a group keeps its
shape. Snapping the delta alone — which is what this did — moved a block in
grid-sized steps without ever putting it on a line, which nobody could see
until the grid was drawn at the same pitch. With snapping off, coordinates are
still rounded to whole units: sub-pixel positions in a project file are noise.

**Saving the diagram as a picture.** **Save as picture ▸ SVG · PNG · JPEG**, on
the canvas menu. What it writes is the *whole* diagram of the sub-system you are
looking at, at 1:1 — the camera is dropped and the viewBox is the bounding box
of what is drawn, **shapes included**, with a margin. A group box reaches past
the blocks it is drawn round, and a box measured from the blocks alone cropped
its edges off, which took the annotation out of the picture it was the point
of. What does not go in is the editing chrome: the selection
rings, the resize grips, the connect handles and the fat invisible shapes that
make thin lines easy to hit are all about the editor rather than the model, and
left in they would come out *more* visible than on screen. The grid does not go
either; it is an editing aid, and a CSS background rather than part of the SVG.

The styles travel with it as inline values on the elements, not as an embedded
stylesheet. Everything about how this diagram looks is a rule in `app.css`
keyed on classes and resolved through custom properties, so a serialised SVG on
its own comes out as unstyled black shapes; and embedding five thousand lines
about a whole application, with its `:root` variables missing, is not a file
anyone can open. A file carrying only what its own shapes need opens in
Inkscape, in Illustrator, in a browser and in Word, which is the point of
exporting one. PNG and JPEG go through the same SVG, rasterised at 2× so the
type is still sharp in print; JPEG gets an opaque ground, since it has no
transparency and a transparent PNG turns black rather than white.

**Auto-layout**, under **Canvas** in the empty-canvas menu,
discards the bends and places everything again from what the diagram draws:
the transfers rank the compartments into columns left to right, ordered inside
each column to cut the number of lines that cross, and the influences hang
expressions, parameters, lookup tables and reductions underneath — each one
under whatever reads it, and a rate parameter under the middle of the transfer
it drives. A model in several unconnected pieces is packed into rows rather
than stacked in one column. Positions and bends live in the project file under
`layout`, and are ignored by the solver.

**Lining a selection up by hand** is the other half of that. Select two or
more — shift-click them, or shift-drag a box over them — and the selection's
menu grows **Align**: the six edges and two spreads every drawing program
offers, *left, centre, right, top, middle, bottom, distribute horizontally,
distribute vertically*. The lines are drawn through the selection itself — the
leftmost left edge, the middle of the whole — because there is no page here to
align them to; the canvas is unbounded. Distributing equalises the **gaps**,
not the centres: the outer edges of the selection stay where they are and
whatever space is left over is shared out evenly, so a compartment you have
made twice as wide does not end up with twice as much air around it. It needs
three to have anything to place between the two ends, and says so when there
are two. Sub-systems are nodes on the diagram, so they line up with the rest;
connections are lines rather than boxes, so they are left out. The same menu is
on a selection of shapes, where a line or an arrow moves by the box it occupies
and goes on pointing the way it did. The whole arrangement is one step of undo,
and an **Align** that finds everything already level says so rather than
recording a step that changes nothing.

The **Matrix** tab is often faster for wiring: rows give, columns receive, and
clicking an empty cell creates that transfer. A cell that already holds one
grows a `+` on hover for adding another alongside it. Each diagonal cell carries an
arrow coming in from the row and turning up into the column, which is the same
thing said in a picture.

Everything else is reachable from the rail: click any block in the list beneath
the inspector to select and edit it. **Del** removes the selection, and **⌘Z**
puts it back. **Save…** writes the model as JSON and asks where to put it; it
says **Save** after that and writes back to the same file, with **⌘S** for the
same thing and a dot on the button while there is anything to write; **Open…**
reads it back, or imports an Ecolego `.eco` project; **Import…** takes blocks *out of* one of those and into the model
already open.

Run the test suite with Node 18 or later:

```sh
node test/run.js
```

## What it does

Build a compartment model graphically — drag compartments, draw transfers,
edit equations — and it assembles the ODE system, compiles the equations,
integrates them, and charts the results.

```figure run-pipeline
  model  ->  build  ->  solve  ->  results
  blocks     one        in a      chart, table,
  and        derivative Worker    file
  equations  function
```

In more detail:

```
equations (text)
   -> parser        tokenize, AST, C-family precedence
   -> compile       AST -> JavaScript source -> new Function
   -> builder       index-list layout, dependency order, decay/ingrowth terms
   -> solver        ndf / bdf or ros23 (stiff) or dp45 (non-stiff)
   -> results       time series, peaks, CSV
```

The blocks a model is made of, and how the diagram draws them:

```figure block-kinds
  [ Compartment ]   solid  — the solver integrates it
  [ Expression  ]   dashed — worked out from the others every step
  ( Parameter   )   a number, or an equation of numbers
  ( Lookup      )   a value that changes with time
  < Source/sink >   where material enters or leaves the model
  { Sub-system  }   a model inside the model
  [ Min / max   ]   remembers what has happened
  < Event       >   an instant, not a value
```

Eight views over one model, all editing the same object:

| Tab | What it is |
|---|---|
| **Build** | The graph editor. Right-click for everything it can do — the empty-canvas menu adds blocks where you clicked and holds the view settings; a block's menu connects and deletes it. Drag from a compartment's right edge onto another to connect them; double-click anything to open its settings; right-click a connection for **Straighten**; drag to pan, Del to remove. The wheel zooms about wherever the pointer is — a mouse notch by about 7%, a trackpad smoothly, since the two report their scrolling in different units and the difference has to be read off `deltaMode` rather than taken at face value. Anywhere in the tab counts, not only over the canvas itself: there is a frame around it — the panel's padding, the breadcrumb above, the help line below — where a wheel doing nothing would read as a zoom that only works over blocks. Nothing in that tab scrolls, so there is nothing else a wheel there could mean, and a pointer outside the canvas zooms about the nearest point of it. Drag a sub-system onto another to move it in, contents and all. Shift-click, or shift-drag a box over them, to select several blocks — and sub-systems, which are nodes here like any other — at once; they then move together, drop into a sub-system together, and are deleted together, a selected sub-system taking everything inside it after a question. Ctrl/Cmd-A takes everything on the diagram. **Cut** (⌘X) and **Copy** (⌘C) are on every block's menu and on a selection's, and both wait for **Paste** (⌘V), which is on the canvas menu, on a sub-system, and on the block tree's rows — so a copy can be pasted into a different sub-system from the one it was taken from, or into a different model, and a cut moves the blocks there instead. A name already used where the copy lands gets a number, and **the connections come along**: a transfer is the arrow between two compartments, so it is copied when both of them are, and left behind when only one is. Every reference *inside* the copy follows the copy — a pasted expression reads the pasted parameter — and every reference *out* of it stays where it pointed. **A sub-system copies as a sub-system**: its own menu has Cut and Copy, and what they carry is its contents — every block in it at every depth, the sub-systems nested in it (empty ones included), and the arrows between them. Several of them, or sub-systems and blocks together, copy as one thing, and the connection rule is read across the whole of it: the arrow between two selected sub-systems comes along, and so does the one from a compartment on the canvas into a sub-system that is coming too. It pastes as a child of wherever you aim it, keeping every name it had, since what it lands in did not exist a moment ago; only its own name gets a number. What moves is the node on the parent's canvas — everything inside is drawn on the sub-system's own canvas and lands looking exactly as it did — and a paste onto a canvas the copy did not come from goes to a clear spot rather than on top of whatever was already there. An end that hangs outside the *view* is marked, and there are three different things it can be. A flow that crosses the model's own boundary gets a dashed cloud — the stock-and-flow convention for what lies beyond it — at whichever end is loose: past the arrowhead where the flow leaves, behind the start where a source term comes in, so the arrow always points the way the material moves. The exception is a source term that carries the **radionuclide dimension**, which wears the standard sign instead, a black trefoil on yellow: the cloud says where the material comes from and the sign says what it is. (The two are alternatives rather than one drawn on the other — a cloud is a wide, flat shape, and a trefoil inside one is a smudge at any size either of them can reasonably be.) **Show ▸ inflow icons** and **▸ outflow icons** turn each direction off separately, both on by default: a model of this kind has an outflow on nearly every compartment and two or three source terms, so the reason to hide the first — the same mark over and over — is not a reason to lose the few that say where the inventory enters. A cloud takes the colour its line was given, so a line styled on the **Appearance** rows is that colour to both its ends; the radiation sign does not, since it is recognised by its colours. And a flow whose far end is a real block in another sub-system gets a **pipe** instead: it has not left the model, it has gone *there*. Each of them is picked up and put down like a block: click to select the connection, drag to place the mark where you want it, right-click for **Straighten** to send it back to where it started. A pipe carries the name of the block at its far end and where that block lives (`Buffer · in NearField`, `Lake · top level`), points along the flow, and has the boundary it crosses drawn as a bar on the side facing the block on screen; double-click it to go there, with that block selected. **A flux that crosses the model's own boundary is drawn where its block is, and nowhere else**: a source term into a compartment inside `NearField` is on the `NearField` canvas, not on the top level as well pointing at the sub-system node. Such a connection has one end that means anything, so there is one canvas it belongs on — unlike a transfer between two real blocks, which still appears on each canvas that can say something about it. The grid is where they are gathered in one place instead. **Show ▸ Transfer labels** chooses what is written along each line — its `name`, its `rate`, or `none` — and sits beside **▸ influences**, the other thing drawn between blocks rather than as one. **Canvas ▸ Show grid** turns the lattice behind the canvas off, **▸ Snap to the grid** turns off landing on it — holding Alt during a drag does the opposite of whatever that setting says, for one placement without changing it — and **▸ Show help** turns off the line under the diagram, which costs the diagram the room. **Add shape…** and **Save as picture ▸** are the last section: the shapes drawn behind the model, and the diagram written out as SVG, PNG or JPEG. |
| **Matrix** | The transfer grid, laid out the way a Jacobian is drawn: **the blocks are on the diagonal and the flows between them are off it**. A cell is what leaves the name on the diagonal along its row and arrives at the name down its column — so the diagonal is a staircase of names and the grid needs no header band, in either direction. Each filled cell carries the elbow that traces its route: above the diagonal it turns down, below it turns up, which is also how a feedback loop shows itself at a glance. **Sub-systems fold**: see below. Everything in it that stands for a block behaves like one: a click selects it and a double-click opens its settings, on the diagonal and off it alike. Click an empty cell to add a transfer; a pair may hold several and their fluxes add. A block on the diagonal, and a transfer off it, wears the colour it was given on the diagram, with its label picked from that colour rather than from the theme — a model of any size is read by its colours as much as by its names, and two views showing it in different colours made this one a separate thing to learn. A far-field pathway sits on the diagonal like any other block. **The world outside the model gets a row and a column of its own**, at the end and outside the hierarchy — its row is what comes in, its column what leaves — and only when something actually crosses that boundary, since an empty pair in every closed model is furniture. It is the one view that puts every source term and every outflow together, the diagram having drawn each of them beside its own block. Built when this tab is opened rather than on every edit, and a selection that moves within one model moves the highlight rather than rebuilding the grid: it is (compartments + paths + 1) squared. |
| **Index lists** | The model's dimensions. One pane lists them, the other is the one you are editing: its name, what it is defined from, its indices, and — for the radionuclide list — half-lives and decay chains. Everything about a list is made and unmade here. |
| **Chart** | Results over time, log-log by default. A search box, kind chips and one selector per index list narrow the line picker above it, which matters as soon as a model is two-dimensional — `landscape.json` has 63 lines to choose eight from. Drag a rectangle over the chart to zoom, scroll to zoom about the pointer, shift-drag or middle-drag to pan, double-click to show everything. Right-click it for the two scales, the zoom, the drag mode, **Save as picture ▸ SVG · PNG · JPEG**, and the numbers as CSV. |
| **Table** | The same numbers, for reading and copying. Built when this tab is opened rather than on every run, and two thousand rows at a time with a button for the next two thousand: a run may hold a hundred thousand output times, and a row of the table is a DOM element per column. The CSV export is not bounded by that — it streams the whole run. Right-click it to export **as CSV** or **as HDF5**: the table as it stands, every output the run produced, or the endpoints you pick. See [Saving the results](#saving-the-results). |
| **JSON** | The project file itself. |
| **Generated code** | Two views of what the builder made. *Derivative code* is the function compiled from the equations — in the three passes it runs as: what reads neither the clock nor the state, worked out once when the model is built; what reads only the clock, once per instant; and the rest, on every call. *Jacobian* is the matrix of its partial derivatives, drawn as its sparsity pattern and checked against finite differences — see [Looking at the Jacobian](#looking-at-the-jacobian). |
| **Help** | This file, and `INTERNALS.md`, read here — with a table of contents down the side. Set apart from the others because it is not a view of the model. |

The left panel is the only panel, and it holds three things in a column:
**Model** (the name and description, which are what the header shows),
**Simulation**, and below them the **tree of the model** with the
**Information** view of whatever is selected.

It is one panel, not two. Splitting the blocks across a list on the left and a
tree on the right puts them in two places at once, in two orders, in two columns
competing for the width of the window, and the middle of the window gets what is
left. One column, and the diagram, the chart and the table each keep those three
hundred pixels.

**Model and Simulation start folded, and the room goes to the tree.** They are
two short forms read once and changed rarely; the tree is the model. Open they
are capped at a share of the panel's height however much is in them, and a rule
under them marks where the settings end and the model begins. The divider below
splits what is left between the tree and the Information view.

**A value is edited where the block is opened** — the settings dialog, from
**Edit…** in the Information title bar or by double-clicking the block on the
diagram, in the tree, or on its name in the Information view. That was always
one of the two ways; it is the way now.

**The tree and the Information view divide the height between them.** Drag the
line between them to give one more room and the other less — the handle is the
only control needed, since the two share all the space and there is no third
arrangement where one is shorter without the other being taller. Double-click
it to even them up, or use the arrow keys with it focused. The share is a
proportion rather than a height, so it survives the window being resized.

Each pane scrolls inside its own share, and the panel as a whole does not. That
is the point of the arrangement: with a model of any size the tree is hundreds
of rows long, and a panel that scrolled meant reading a block's equation and
then losing it to reach the next block in the tree.

**The panel is resizable, and folds away.** A grip runs down its inside edge:
drag it to take width from the middle or give it back,
double-click it for the panel's usual width, or focus it and use the arrow keys
(a step of 16 pixels, 72 with Page Up and Page Down, *Home* and *End* for the
extremes). The small chevron at the top of the grip folds the panel away
altogether — for a wide diagram, a wide table, or a chart with a long legend —
and it stays where it is when the panel goes, so it is also the way back.

Its width is in pixels rather than a proportion, unlike the divider inside it:
a panel sized to fit the names in it should stay that wide when the window
changes and let the middle take the difference. What the middle never loses is
360 pixels — the panel cannot squeeze it out — and a window that
becomes too narrow for the widths you chose squeezes the panels instead,
giving them back when it widens again. None of it is remembered across a
reload, which is true of the theme, the tab and the rail's divider too.

**There is no property form in the rail** — no third editing surface above the
two panes. In a 310-pixel column that is a third editor of the same block, the
left panel and the settings dialog being the other two, and it leaves the two
halves anyone actually navigates by sharing whatever is underneath it. Editing
is the dialog's job: **Edit…** in the Information title bar opens it, and so does
double-clicking the block — on the diagram, in the tree, or on the name at the
top of the Information view itself, so the gesture means the same thing
wherever the block is in front of you. A sub-system has no settings — it is a
place, not a quantity — so **Open** takes its place, and double-clicking its
name goes inside. With nothing selected there is no button at all: the model
has no dialog — its fields *are* the left panel, which is on screen the whole
time — and a door to a room you are already standing in is worse than no door.

**The filter is behind a disclosure.** The kind filter is thirteen chips, which
in this column wraps to four rows; above a tree that is now the main thing in
the panel, that cost more room than the first screenful of what it searches.
Closed it is one line saying what is filtered and how much it leaves —
`Compartments · 4 of 20` — and opened it is the same cloud of chips it always
was.

**Writing an equation.** Every field that holds one completes what you are
typing: the blocks you can name from where you are standing, and the function
library with its signatures. It opens on its own once a word is started;
Ctrl-Space opens it against whatever is under the caret, including nothing, for
when the question is *what is available* rather than *finish this*. Up and
down move, Enter or Tab takes one, Escape dismisses it. A function arrives with
its parentheses and the caret inside them, and one that takes no arguments —
`time`, `pi` — arrives bare, since that is how the parser accepts it. A lookup
table that is read at an argument arrives as the call it has to be, `Q_gw()`,
because such a table has no value of its own to refer to.

The list is scoped the way the equation is. Inside a sub-system its own `Kd`
is offered as `Kd` and every other one as a full path, and what is inserted is
guaranteed to resolve back to the block that was shown — over the four real
`.eco` models this tool is checked against, all 16,291 references those files
actually contain can be produced this way. The one case that is *not* offered is a root block
shadowed by a local one of the same name: the format writes both as `Kd`, the
nearer wins on the way back in, and offering it would quietly bind the wrong
one. The line under the list says what the highlighted row is — a block's kind,
dimensions, unit and comment; a function's signature, category and what it
does, taken from the function metadata a project file carries.

Inside `[ ]` it completes **index names** instead, which is the half nobody
can type from memory: `[F.18:00_51_FORSMARK]`, `[_Ra-226]`. The bracket alone
is enough to open it. It offers every index of every dimension the block has,
not only the one this bracket sits in, because a bracket is resolved by name
rather than by position — and 200 of the 506 two-bracket references in these
files are written in the order the *other* dimension would suggest. Each row
says which list its index belongs to.

The gesture is the conventional one: the space bar opens the list and Enter
replaces the word under the caret. What it shows is every name in the model,
unfiltered, and it refuses to open inside brackets.

**The tree.** Its spine is the sub-systems, nested the way their names are:
that is how a model of any size is actually organised, and in one of the real
ones a bare name settles nothing — one assessment model has 1,298 blocks in 55
sub-systems, and several of them are called `Kd`. Each sub-system says how many
blocks are inside it in all; clicking one shows it on the diagram (the
disclosure arrow opens it without going there), and the one the canvas is
currently showing is marked. A block carries a small icon of the shape the
diagram draws it with, in the same colour, so its kind is legible without a
heading over it — and clicking a block on the canvas opens the tree down to it.
Arrow keys walk it: down and up between rows, right to open a sub-system or
step into it, left to close it or step back out. **Group by type** — beside
**All kinds** above the tree, since the two are a pair, one saying what is in
the list and the other how it is arranged — files each sub-system's blocks
under a heading per kind, which is worth having when one holds hundreds;
**Expand all** and **Collapse**, over the tree itself, do what they say.

**The three Add tabs**, on the top edge of the tree at its right, add a
compartment, an expression or a parameter to whichever sub-system the diagram is
showing, and select it, so its settings are one click away. Each is the block's
own symbol and nothing else — the rounded box a compartment is drawn as, that
box with an equals sign for an expression, the hexagon for a parameter — which
is the same glyph on the row it will appear as, and the same shape the diagram
draws.

**A block that looks like a compartment and is not says so.** Five kinds wear
the rounded box — a compartment, an expression, the two reductions and a
function — and on the canvas each carries a name and a dimension line and
nothing else, so what tells them apart is the fill colour and only that. The
four that are not compartments therefore carry their own mark in the corner:
an equals sign, a funnel, a plus, a pair of brackets. The compartment stays
bare, and that is the rule rather than an omission — the shape's plain reading
is *a compartment*, so a mark means *this looks like one and is not*, and
marking all five would leave the mark saying nothing. The same marks appear on
a far-field path, a waste package, the three blocks that remember and a
transport, each of which shares its shape with something else. **Add** at the head of the row says what the three of them do, so none of
them has to say it again. Three, not thirteen: those are what a model is
mostly made of, and the rest are a right-click on the canvas away, where they
can be put somewhere on purpose. The canvas menu is still the way to add one
*at a point*; this is for when the panel is what you are looking at — reading
the tree, or working on the chart with the diagram behind it — and the
alternative is to go to the Build tab, find empty canvas, and right-click it.
A block added inside a sub-system says so, since the tree lists every
sub-system's blocks together.

**Ungrouped, the blocks are in name order**, ignoring case, so `Well` and
`wellVolume` sort together rather than a capital letter putting them in
different halves of the list. With the headings on they go kind by kind
instead — that is what the headings are cut from — and by name inside each. A
block's kind is on it either way, as the icon of the shape the diagram draws
it with.

**With the Chart or the Table tab in view, a row's menu opens with it.** *Add
to chart* puts the block's series beside what is already drawn; *Show in chart*
shows them and nothing else — and on the Table tab the same pair reads *Add to
table* and *Show in table*, since the two views draw the same choice of series. A block is not a series — an indexed one is a line
per index, so `Dose` on a four-nuclide model is four lines and all four go — and
a sub-system stands for everything inside it at any depth. This is the way to
reach one block you are looking at in the tree: the line picker above the chart
lists every series in the model, which is the wrong instrument for that. The
two items are there only while one of those two tabs is in view, since on the
Build tab there is neither to add to.

**Clicking the empty space below the rows selects the model**, which is what
pointing at no block means. The Information view then describes the whole model
— what it holds, at every depth, by kind — rather than going on describing a
block the pointer has just been moved away from. Right-clicking that space
offers to paste into the top level, for the same reason.

Adding keeps the lines already drawn, and keeps their order, so a block joining
the chart does not restyle what was on it. A chart holds so many lines before
the colours and dashes run out; past that it says how many would not fit rather
than dropping them quietly.

**It is not a read-only list.** A right-click on a row opens the diagram's own
menu — the whole of it, not a smaller version: connect this compartment to
that one, move an end of a transfer, add a source term, move into a
sub-system, open or rename or dissolve one, delete. There is one menu for a
block and it lives with the diagram, so what a right-click does does not
depend on which panel you found the block in. The same menu is on every
reference in the Information view, since a name in an equation is a block like
any other.

Several rows can be selected at once, with the conventions a list has rather
than the diagram's: click replaces, **shift**-click takes everything between
the last row clicked and this one, and **Ctrl/Cmd**-click adds or removes one.
Shift with an arrow key extends as it goes. The selection is the same
selection the diagram holds, so it is marked in both places at once, and
**Del** and Escape do here what they do there. Right-clicking a member of a
group gives the group's menu — move all of them, delete all of them — and
right-clicking anything else selects that one first, so the menu's title
always names what the menu is about. A sub-system's row joins in under either
modifier, and a range that runs across one takes it: the rows between two rows
are what "between" means here, and what a range has caught is highlighted
before anything acts on it.

**Rows can be dragged.** Drop a block on a sub-system to move it in, on the
top-level row to move it back out. That second half is the one a diagram
cannot offer: on the canvas you can drop a block onto a container, but there
is nothing to drop it on to take it out again. A drop takes the whole
selection when what you dragged was part of it. Where the blocks were drawn is
forgotten, as with a drop on the canvas — coordinates on the diagram they left
mean nothing on the one they arrive at — so they are laid out among their new
neighbours. A sub-system can be dragged too, onto another
sub-system or onto the top-level row. That the format has no place for a
sub-system to *be* is what makes it work rather than what stops it: a
sub-system is the dotted path its blocks wear, so moving one is renaming that
path, and every block inside it, every sub-system nested in it and every
reference to any of them follow the same way they follow a rename. The one drop
it refuses is into itself or into something inside it — nothing can end up
inside itself, and the row does not light up.

**Shown as.** A block's name is an identifier — equations refer to it — and
this domain is written in notation identifiers cannot hold. So a block may
carry a **symbol**, set under *Appearance* in *All settings*, which is what it
is called on screen while the name goes on being what it is called in an
equation:
`<sup>14</sup>C` draws as <sup>14</sup>C and `k<sub>d</sub>` as k<sub>d</sub>.
`<sup> <sub> <b> <i>` are understood and nest; everything else is literal text,
and a symbol that will not parse is shown as written rather than swallowed. It
is parsed into runs and built as elements — never `innerHTML` — because a
project file is a thing people send each other. On the diagram the same runs
become one `<tspan>` each, which is what a superscript is in SVG.

This guide is written in the same notation, which is why the reference tables
below say T<sub>w</sub> and K<sub>d,f</sub> rather than spelling their tags out.

Where the symbol goes depends on how the block is being read. A box on the
diagram is read at a glance, so it carries the symbol alone. A list is read by
name — the block tree, the matrix's diagonal, the Information view's title —
and there the **name comes first with the symbol in brackets after it**:
`Water (H₂O)`. The name is what an equation, the search box and the problem
strip call the block, so it is the thing you look a row up by; the symbol says
what the diagram will show.

**Constant, or something that moves.** The Information view answers it on a row
of its own: *Over time — Constant*, or *Varies — it reads Water, which the
solver integrates*, with the block that moves as a link. It is not a question
you can answer by looking — except of a parameter, which is a constant by
definition and says so at the top of the card, so that row is not drawn for
one. Nor is *At the start*: a parameter's value is printed two lines above, and
it is the same number at every instant. `Kd * rho / porosity` is three
parameters and never changes; `Kd * Water` is the same shape and changes at
every step; and a block four references away from a compartment looks like
arithmetic all the way down. The reason names the *nearest* thing that moves
rather than the whole chain — `A reads B, which reads C, which the solver
integrates` is a sentence nobody finishes, and B's own row says the rest.

The rule is the engine's: a compartment is the state being integrated, a
far-field pathway's release comes out of that state, a table is read at the clock,
and the blocks that remember are functions of history. Everything else is
constant when it reads no clock and everything it reads is constant too — which
is exactly the rule deciding what an [initial condition may
read](#what-an-initial-condition-may-read), and the two are run side by side
over every bundled example and required to agree.

**Which indices differ.** For an indexed block the Information view says what
it is indexed by and how many combinations that is — and, when any of them hold
something of their own, **which ones and what**: `I-129 · Mire — initial 1e12`,
`Cs-137 — abs. tol. 1e-6`, `I-129 · Lake — floor may go negative`. Across every
per-index key, not only the block's own value, so an index that differs solely
in its tolerance or its floor is not an index that looks the same as the rest.
It is the thing you go looking for in the settings dialog, and finding it by
opening the grid and reading down it means — on a model whose nuclide list is
fifty long — passing forty-nine rows that say nothing.

**What the equation comes to.** Under every equation box in the settings dialog
is a line saying what that equation works out to **at the start of the run** —
`= 3000 Bq` under `Conc * Volume`, `= 0.1 1/year` under a rate, `= 0.0017 to
0.05 over 3 indices` under a sorption coefficient that is a table of its own.
The blocks with no equation box — a table, the two reductions, a far-field pathway,
a parameter, and the flux of a release, which the path works out rather than
anyone typing it — get a row of their own saying the same thing. The
Information view carries the number for the block itself, on a row between what
defines it and what it is measured in, so the three read in order: *this is the
equation, this is what it comes to, this is what that number is*. **The left
panel's rows carry it too**, as a third column after the box — `= 1e10` on a
compartment, `= 1e-5` on a transfer, `= 0–7e14` on an expression that spreads
over its indices — cut to the number, with the full line and the values by
index on hover. A parameter's row has none, since a parameter is its own value.
The column fills in when the numbers are known, which on a large model is a
moment after an edit rather than during it.

It is the answer to the question the box itself raises. An initial inventory
written as `Total_inventory * Leaching_fraction` is two names and an operator
until something says it is 3.2e9 Bq; a rate that reads `k_out * (1 - Retention)`
could be anything until it says `0` and you find the parameter nobody filled in.

**A block in a real model is rarely one number** — the median imported block
carries 39, one per nuclide or per region — so there are three ways to read
them, each for a different question. The line under the box gives the range and
how many indices it covers. **Values per index** in the same dialog gains a
column, *at the start*, so each row reads *this is what I wrote here, this is
what it comes to* — and a table, whose row is a whole list of points rather
than a value, gets it on the line that summarises the table instead. Two kinds
of row do without: a far-field pathway's, which already carries a column per
chemistry term, and any block indexed by the scenarios, where one scenario is
live and every row would show that one's value. And
the Information view lists them: up to eight are simply there, more are behind
**show all 53**, and a block with hundreds arrives fifty at a time with **load
50 more of 1134** at the end of the list.

Nothing is hidden for being strange: `infinite at all 3 indices` is what a model
that divides by a compartment starting at zero *says*, `not a number` is what
dividing nothing by it says, and half the imported projects say one or the other
somewhere. What has no answer is a model that will not build, and there the
line goes quiet rather than repeating what the problem strip already says.

**What it costs.** One evaluation of the whole model, which is the same first
step a run takes: a tenth of a millisecond. *Building* the model to do it is the
expensive half — measured in the browser, the whole thing takes a millisecond or
two on the bundled examples, about 100 ms on a model of 1,141 blocks and 2.4 s
on a landscape model of 4,278 — so it happens a moment after the edit
rather than during it, and a model that turns out to cost more than 400 ms is
measured once, said so, and then left alone. Nothing is worked out until
something asks: a model nobody opens a block of costs nothing at all, and the
code that does the work is not even loaded. On one of those the line shows what it worked out and goes quiet at your
next edit rather than showing a number that is no longer true; the table's first
row after a run is the same number.

**Selecting a sub-system.** A sub-system is a block like any other, and
clicking one on the diagram says so: the rail gives its name, how much it
holds, and *Show on the diagram* / *Dissolve*, while the Information view
lists what is inside it by kind, the sub-systems within it, and — the question
you actually have about a part of a model — **what crosses its edge**, as the
connections flowing in and out.

**Selecting several.** Shift-click blocks on the diagram to add them to the
selection, or hold shift and drag a box over them — touching one is enough to
catch it, since a box that has to enclose a block turns picking six out of a
crowded diagram into an exercise in aim. Ctrl/Cmd-A takes everything on the
current diagram, Escape drops it. The rail says how many are selected and
which of them the inspector is describing; the tree and the diagram both mark
every member and give that one a full-strength ring while the rest are
softened, so the question "which of these am I editing" is answered wherever
you happen to be looking. Dragging any member moves the whole group. Deleting a
selection is one edit, which is what lets two blocks that read each other go
together though neither could go alone; anything still used from *outside* the
selection stops the whole delete rather than half of it.

**Sub-systems are part of a selection.** A sub-system is a node on the canvas
and a row in the tree, so it is one of the things a selection holds: shift-click
one, sweep the box across it, Ctrl/Cmd-A on a diagram made of them. Without
that, the top level of a nested model — which is mostly sub-systems — could not
be multi-selected at all, and the clicks that tried it were silently ignored. In
the tree a plain click on a sub-system still *opens* it, since that is what a
click on a row in a tree means; Ctrl/Cmd- or shift-click is what picks it out.

What a group is then asked to do says which part of the group it is about, since
a selection holding both kinds cannot honestly be called blocks. **Cut** and
**Copy** take blocks and sub-systems together. **Move ▸** takes both, and moving a
sub-system is renaming the path its blocks wear: everything inside follows,
and so does every reference to it. The targets it offers leave out the ones a
sub-system in the selection cannot go into — itself, and anything inside it —
and when that leaves nowhere the item says so instead of opening onto a
submenu of greyed lines. **Delete** takes
each sub-system with everything inside it, as one edit with the blocks beside
them, and it is the one delete here that asks first: a container stands for
more than you can see, even with **Undo** behind it. Its own menu has the same
thing as **Delete, and everything in it**, next to the **Dissolve** that keeps
them.

**A selection can reach further than the canvas.** The diagram shows one
sub-system at a time, and a selection built in the tree can hold blocks from
several of them. So *adding* to a selection no longer brings the canvas along —
jumping to whichever row was clicked last would take the view away from the rest
of the group — and the foot of the left panel says how many are somewhere else:
*3 blocks and 1 sub-system selected · 3 elsewhere*. It is under the Information
card rather than over the tree, where it would push both down the moment a
second block was picked; at the foot it is a status line, which is what it is,
and it is not there at all while nothing is selected. Cut, Copy and Delete act
on all of them, wherever they happen to be drawn.

**What a selected block looks like.** A ring outside it, in the accent colour,
rather than its own outline repainted. That outline is part of what a block is
— solid for a compartment, dashed for everything algebraic — and a thick accent
stroke through it meant a selected block stopped saying what kind of block it
was. The ring is two strokes of the block's own path drawn *behind* it: since
the fill is opaque, only their outer halves survive, so a wide faint one
becomes a soft aura and a narrow solid one a crisp edge. It costs no geometry
and it is exact for every shape there is — the hexagon and the diamond get a
concentric echo, not a bounding box.

Tab walks the blocks and gives the one it reaches the same ring, dashed — here,
but not chosen, since tabbing does not select. Nothing else marks focus: a
Chromium browser focuses an element carrying a `tabindex` when you *click* it
and then draws its own ring around the bounding box, a hard-cornered rectangle
outside the shape, so that is suppressed. Safari never drew it, because macOS
does not focus non-form elements on a click — which is why the same diagram
looked right there and wrong in Edge and Brave.

The resize grips sit on the shape's own corner rather than on the corner of its
box, which on a diamond are a quarter of the block apart. A compartment gets
two of them, at the bottom and the bottom-right corner: the middle of its right
edge belongs to the connect port, and a grip there was drawn over that port and
took its clicks, so the one control for drawing a transfer was unreachable at
its own centre whenever the block was selected. The corner grip changes the
width, so nothing is lost but the collision.

**Finding a block.** Type in the search box and the tree below narrows to what
matches, opening whatever still holds a match; the diagram dims everything else and rings the matches in amber. A
plain query matches anywhere in the name and ignores case, so `soil` finds
`Soil`, `Soil_Water` and `kSoil`. Add `*` (any run) or `?` (one character) and
it becomes a pattern over the *whole* name, so `*_out` finds names ending that
way and nothing else. Everything else is a literal — `S.il` matches a name
with a dot in it, not `Soil`. The chips under the box limit the search to
particular kinds of block, and several add up; a kind the model has none of is
greyed out. **Clear** or Escape resets both. The filter is a way of looking at
the model rather than part of it, so it is not saved with the project — and
neither is which sub-systems are open. A search that matches thousands of
blocks draws the first 600 and says how many more there are, because on a model
the size of the largest assessment model a single letter matches 2,875 of them.

**Information.** Under the inspector, a reading view of the selected block — a
reading view that writes each reference as a link moving the selection: the
block's name and kind, the sub-system it is in, its comment, and **its
equation with every block it names rendered as a link you can click to go
there**. Double-clicking the name at the top opens the block's settings, the
same as double-clicking it anywhere else. Under that, *Uses* and *Used by*:
what it reads and what reads it, each one named, typed, given its unit and
summarised — `Kd` on its own says nothing, `Kd · parameter · 0.01` says
whether it is the one you meant. Following a link changes the selection
everywhere, so the diagram, the inspector and the tree all move with you, and
**←** / **→** in its title bar walk back and forward through where you have
been. The tree scrolls to a selection made *elsewhere* — a click on the
diagram, a link followed here — and stays where it was for one made in the
tree itself, so a row far down the list can be clicked and then double-clicked
without the list jumping back to its head between the two.

Every reference here is labelled with the block's **symbol** where it has one,
inside the equation as well as in the lists: `1 + Kd * rho / theta` reads as
`1 + k_d * ρ / theta`, and a block with no symbol keeps the identifier exactly
as the equation spells it — a path written as a path stays one. The name it
answers to is in the tooltip, and on its own page as *Named*. This is the
reading view; the equation **field** in the rail still shows the text you
typed, because that is the text you are editing.

It is drawn as a card — its own outline, its own surface, a titled bar with its
own controls — because everything else in that column *edits* the model and
this one reads it: nothing in it should be mistaken for a field to type in. The
card collapses to its bar if you would rather not have it.

**With nothing selected it describes the model.** The panel is not idle then —
it is the only view that can say what the *whole* file is, which is the first
thing anyone wants from one they have just opened: its name and description,
how many blocks it holds and how they split across sub-systems, how many
**states** the solver will integrate (one per compartment per index
combination, plus one per running mean), the **index lists** with the size of
each, and the run settings — time span, output points and spacing, solver, and
the two tolerances. All of it is on one card, rather than split across a
properties dialog for the name and description and a settings dialog for the
run: the reading half sits with the rest of the reading, and the editing stays
where the editing is — the left panel, which never
leaves the screen, so this card has no *Edit…* of its own. Double-clicking the
model's name puts the caret in the field that spells it, the same as clicking
the name in the window header and exactly as double-clicking a block's name
opens the block. Each index list is a link to it on the *Index lists* tab,
each sub-system a link to it on the diagram, and a model whose units do not
add up says so with a link to the first block at fault. Everything on it is
worked out from the model rather than from the last run, so it says the same
thing before the first simulation as after it.

**Unit checking.** An equation is worked out in units and compared with the
unit its block claims, and a mismatch is a **warning** on the field and in the
Information view — never an error. The engine treats units as labels, so a
model with a mismatch still runs and still gives the numbers it always gave;
what it may not be is the quantity the label says. The rules are the ordinary
ones: `*` and `/` combine, `+` and `-` must agree
except that a dimensionless side is absorbed, an exponent must be constant, a
comparison is dimensionless, `min`/`max`/`if` need their arguments to agree,
`sqrt` halves, `time` is the simulation's time unit — and the two odd targets,
a flux checked against `1/<time>` or `<donor>/<time>` and a delay time against
the time unit.

It stays quiet unless it is sure. A bare number never complains (a number has
no unit), an equation naming one block without a unit produces no verdict at
all, and a power it cannot follow — `D^k` — is left alone rather than called
wrong. On the 12,205 blocks in the real files here that comes to 178 warnings,
about 1.5%, and reading them they are the sort of thing worth knowing:
`Expected_dose_core_drilling_*` works out as `Sv*year` against a declared `Sv`.
The unit reader handles what modellers actually type — `year^-1`, `m year^-1`,
`kg/(m^2*year)`, `Sv/year per Bq/m3`, `m2`, `Sv/y`, `[-]` — and refuses rather
than guesses at the one thing it cannot represent (`m^(1/3)`). It never
converts: `m` and `cm` are different units here, because nothing in this tool
multiplies by a conversion factor and quietly accepting one for the other would
be worse than saying nothing.

Writing this found four hidden constants in the bundled examples — a bulk
density and a porosity written as `1500` and `0.3` inside a retardation factor,
a lake depth as `2.0`, a lake volume as `1e4` — each now a named parameter with
a unit. The numbers are identical; the models say what they mean.

**The inspector, and the settings dialog.** The rail shows what a block *is*:
its name, the equation or value that defines it, its unit, and — where the
block has a dimension — how much of its per-index grid has been filled in. That
is three or four rows. Everything else a block can carry is real and editable
and does not belong in a 300-pixel column all at once, so **All settings…**
opens it in a dialog: which sub-system holds it, what it is indexed by, the
grid itself, colour, shape, size, comment, and the per-kind options (a
compartment's non-negativity and decay flags, a lookup's interpolation and
whether it repeats, a recorder's reset and stop events). Double-clicking a
block on the diagram opens the same dialog, as does **Settings…** in its
right-click menu; Escape or the backdrop closes it. It is the same form as the
rail with nothing left out rather than a second description of the same
fields, and it edits the model live — the diagram and the run behind it follow
each keystroke, and a rename retitles the dialog rather than orphaning it.

**The title carries both names.** A block shown as something else is titled
`Water (H₂O)` — the name the model is written in, and in brackets after it what
the diagram calls it. A dialog titled only with the symbol would be one you
could not find the block from.

**What sits where.** The dialog is two columns, so the first two cells are the
best real estate in it, and they hold **Name** and **Unit** — what the block is
called and what it is measured in, which is the pair you read a block by. Below
those comes what defines it, then the per-kind options. A compartment's
defaults — the **initial inventory**, the **absolute tolerance** the solver
is allowed on it, and the **dy/dt term** if it has one — share one cell, one
under the other, because they are one answer about one compartment and the
per-index grid below sets them in adjacent columns. Five rows further down
among the flags, nothing would connect the two. **Enabled** is last,
just above *Appearance*: it is the one answer that is about the whole block
rather than about any field of it, and in the middle of the form it read as a
property of whatever it happened to sit beside. *Shown as* is inside
*Appearance* with colour, shape and size, because what a block is called on
screen is one of the things that panel is for; the cell beside the name is a
lot of room for a field most models never set.

Two kinds of block have a value too big to show in a column, and the rail shows
what it is instead of a box to retype it in. A lookup table gets its own curve
and `12 points, 0 to 1e4`; an aggregate gets the names of what it reduces. The
editors — one x, y pair per line, one block name per line — are in the dialog,
where there is room for the 4,000-point tables and 40-block aggregates the real
files contain.

The equation language is the one those project files use: `+ - * / ^`, the
array-language `~=`, `.*`, `./`, `.^`, a ternary `? :`, and ~50 functions
(`if`, `min`, `max`, `sum`, `mean`, `erf`, `log`, `mod`, `rem`, the trig
family, `time`). Precedence follows the C family, with `^` left-associative —
`2^3^2` is 64.

## Settings windows

They open where the browser puts them and stay there. A `<dialog>` is centred
by the browser and *re*-centred whenever its contents change, so a validation
line appearing under a field used to move the field being typed into — pinned
on opening, it grows downwards like anything else, and the body is held at the
height it had across a rebuild so nothing flickers between one keystroke and
the next.

**Drag the title bar to move one**, and the corner at the bottom right to size
it. Both are useful for the same reason: a settings window covers the thing it
is about, and a long form in a short window is a lot of scrolling. Neither is
remembered — each window opens centred at its own size — and a window cannot be
dragged somewhere it cannot be dragged back from.

### The Table, after a sample

**Show** above the Table chooses between the run over time — one row per output
time — and **the realisations at one time**: one row per realisation, one column
per selected series, with the mean, median, 5% and 95% above them so the number
you want is read rather than counted to. The time is beside the control, and it
is the same time the Chart's distribution is of: asking the same question in two
tabs is a way of getting two answers. That one is the Chart's distribution as
numbers, which is what pasting into a report needs.

Over time, a second control says **which run** the rows are. A column of numbers
cannot say that by looking, and after a thousand realisations there are several
honest answers:

| | |
|---|---|
| **the median of the realisations** | the middle of them at each time. The default, and the Chart's own default line. |
| **their mean** | their average at each time, which for a skewed output is well above the median. |
| **one realisation** | one of them as it was integrated, chosen by number beside the control. |
| **this model's own run** | the deterministic run — the model at its own values. |
| **every realisation** | the whole matrix: time down the side, realisation across the top. |

**Every realisation** is offered one series at a time, because every column is
already a realisation and a second series would want a second table rather than
more columns. Both directions are capped on screen — a thousand realisations
over four hundred times is four hundred thousand cells — with a button for more
of each, and the line underneath says what is being held back. The whole of it,
for every series the run kept, goes out through **Save → Model with results**.

A sample is always reported on the model's grid, and a run may not be — see
*The solver's own points*. So the times down the side are the sample's for the
first three and the run's for *this model's own run*, and each is labelled with
its own.

## Solving for the inputs

A run asks *what does this model give*. **Optimise…**, under **Calibration** in
the left panel, asks the other one: *what would the inputs have to be for it to
give this*. A measured concentration, a dose an assessment has to match, a
release rate calibrated against a field study — each is one or more endpoints
with the value they are supposed to come out at, and a handful of parameters
allowed to move until they do.

### Saying what the answer is

**What these should come to** takes endpoints — *Add endpoints…* opens the same
searchable list the exports use — and for each one: **where** it is read (at a
time, at its highest, at the end of the run), the **value** it should have, how
the miss is **measured**, and a **weight**.

How the miss is measured matters more than it looks:

| | |
|---|---|
| **absolute** | `got − want`. For a quantity whose own scale is the point. |
| **relative** | divided by the target. The default, because two endpoints in different units are otherwise not comparable and the larger one simply wins. |
| **logarithmic** | the ratio. For a dose or a concentration, argued about in orders of magnitude: being out by a factor of two is the same error at 10⁻⁹ as at 10³, and neither of the other two says so. |

### Saying what may move

**What may vary** takes parameters, each with a **range** and whether it is
searched **linearly or logarithmically**. A parameter arrives with a decade
either side of the value it has, logarithmically where that is possible — which
is the range somebody would type, and the one they can then argue with.

The bounds are the important half and the easy one to leave out. A search told
only *vary the leach rate* will put it at 10⁴⁰ if that fits the numbers; a model
is a set of assumptions about what is physical, and the bounds are where those
get written down.

### Which method

Every evaluation is a whole run of the model, so the count is the time this
takes.

| | |
|---|---|
| **Nelder–Mead** | A simplex walking downhill. Few evaluations, no derivatives, and the right first thing to try on a handful of parameters. Finds the bottom of the valley it starts in. |
| **Levenberg–Marquardt** | The classic for least squares, and this is one. Costs one extra evaluation per variable each iteration to build a Jacobian, and is much the fastest once it is near — on the standard test problem, 97 evaluations against Nelder–Mead's 265. Wants a decent starting guess. |
| **Differential evolution** | A population crossed with its own differences. Much the slowest, and the only one that climbs out of a local minimum — what to reach for when the parameters range over decades and nobody knows the answer to within a factor of ten. |

Stop is available while it runs, and it stops.

### What it says, and what you do with it

The report is graded on whether it actually solved the problem rather than on
whether numbers came back: *Every endpoint matched, to within 1%*, or *The
closest it could get*. Each target shows what was wanted, what came out and how
far off — as a factor where the target was set logarithmically, because ×84
says more than 8301% does.

**A parameter that came out on one of its bounds is called out**, because that
is the search saying it wanted to go further and was not allowed. Widen the
range, or take it that the model cannot reach the target from inside it.

Then two buttons, which do two different things:

- **Run at these values** runs the model against a *copy* with them in it and
  changes nothing. The corner of the Chart says the run is a preview and the
  model still holds its own values; pressing Run goes back to it.
- **Update the parameters** writes them into the model, as one edit, so one
  undo takes the whole answer back rather than a parameter at a time.

## Handing the data over

An assessment's data — every parameter's value and unit, every lookup table's
points, and whatever distribution each carries — travels separately from the
model that consumes it. **Save → Data** writes it as a spreadsheet or as an
HDF5 tree, and **Import…** reads either back.

Both carry the same thing, spelled two ways.

**The spreadsheet** is one row per value. A parameter is a row; a lookup table
is one row per point with the point's time in the `Time` column, so the table
is the rows sharing an `ID`. The columns are `ID`, `Unit`, `Time`, `Value`,
`Type`, `Group`, `Min`, `Max`, `Mean`, `Std`, `GM`, `GSD`, `Pmin`, `Pmax` and
`Reference` — plus `Subsystem`, `Name`, `Media`, `Position` and `Species`,
which are **helpers rather than data**: in a hand-made sheet they are what the
ID is pasted together from, so they are filled in on the way out and read on
the way in only when `ID` itself is empty.

`Min` and `Max` mean what the shape says they mean. For a uniform they are its
two ends; for a normal or a log-normal they are a truncation of it. `Pmin` and
`Pmax` are always the percentile truncation. A triangular's most likely value
is the `Value` column where `Mean` is empty — the number the model runs at *is*
the mode — for the double triangulars (`dtriang`, `logdt`) as for the
triangulars. The `Type` words are `unif`, `triang`, `dtriang`, `norm`, `logu`,
`logt`, `logdt` and `logn`, spelled as skbrnt spells them, and in HDF5 the
numbers carry skbrnt's names: `{"type": "dtriang", "a": …, "b": …, "m": …}`.

**A row with both a `Time` and a `Type`** gives that point of the lookup table
its own distribution. In HDF5 the same thing is a *list* of specs on the
dataset, one per value, in the order the values are in.

A `Value` that is not a number is carried as the text it is — `GROUP1` names a
speciation class — but it cannot be written into a parameter, and an import
says which rows it left alone for that reason.

Datasets may be **chunked and compressed** — gzip, shuffle, or both, which is
what most writers produce the moment anything is squeezed — and are read as
they are.

**The HDF5 tree** puts the ID in the path: `/model/Atmosphere/height/L1` is the
id `Atmosphere.height.L1`. A parameter is a scalar dataset, a lookup table is a
dataset of its values with the times beside it in an `index` attribute, and the
rest rides as attributes — `unit`, `reference`, and `pdf`, a JSON object using
the same words the spreadsheet's columns use.

### What an ID means

The dotted path is the sub-systems it lives in, then the block, then one
segment per index it is given at. Nothing in `CR.food.herbiv.Ac` says where the
name stops and the index begins — so the import asks the model: **the longest
prefix that is a block is the block**, and what is left over are its indices in
the order of its own index lists. A segment written `_` is the block's own
value rather than an index of that name, which is how a data set gives one
number for every element and then overrides four of them.

### Importing

The dialog says what the file would do **before it does it**: how many rows it
holds, how many are lookup tables, how many carry a distribution, and then —
from a trial run against a copy of the model — how many values, tables and
distributions would land, which ids matched nothing, and which rows could not
be used. Nothing is changed until *Import* is pressed, and what it then does is
one undo step.

**Create what is missing** decides what an unmatched id does. Off, it is listed
and left alone. On, it becomes a new block — but with no block to ask, there is
no way to tell a name from an index, so the last segment is the name and the
rest are sub-systems, which are made on the way.

A segment a model cannot hold as a name is given one it can: `1BMA` starts with
a digit and becomes `_1BMA`. The report says so once rather than per row, and
the file's own id still finds it afterwards — so importing the same file a
second time matches what the first one made.

## Asking the model about itself

The box at the top of the left panel finds a block by name. The **?** beside it
answers the questions that come up on a model somebody else built, years ago,
with four thousand blocks in it:

| Question | What it is for |
|---|---|
| **That use…** | Everything whose equations name a block — directly, or through others. What to look at before changing a rate constant. |
| **That are used by…** | Everything a block needs to have a value. What has to travel with it into another model. |
| **That nothing reads** | Redundancy, or a mistake — or an output meant for a person rather than for the model. |
| **That are only data** / **That use an expression** | Transcribed numbers against worked-out ones, which is the line a review is drawn along. |
| **Indexed over…**, **In the sub-system…** | Structure. |
| **With the unit…**, **With a unit mentioning…**, **With no unit** | `Bq/m3` and `Bq m-3` are one quantity spelled two ways; finding both is how they come to be spelled one. |
| **That carry a distribution**, **That are switched off** | What a probabilistic run would sample; what the model carries and the run does not. |
| **With a comment containing…** | Where a "check this" was left. |

The answer is **pinned over the block list** rather than shown in a list of its
own, so it composes: ask what reads `leachRate`, then narrow to the transfers
with the kind chips, then find one by name. The line under the search says which
question is pinned, and × takes it off. Matches are marked on the diagram too.

## Recording that a definition has been reviewed

Switch **Track review** on under MODEL and every block gains three states —
approved, needs review, or nothing yet — with a record of who approved it, when
and why. The tally in the panel says how far a review has got; clicking it lists
what is left.

**An approval stops counting when it should.** A parameter approved last month
is not approved now if somebody has changed it since — and, the part nobody
tracks by hand, it is not approved now if somebody has changed something it is
*worked out from*. Approve `Dose = WellConc × intake × doseCoeff`, halve
`intake`, and the dose has been reviewed only in the sense that a number nobody
checked used to be right. The panel says so, and names what changed:

> Approved, but something changed — `doseCoeff` is no longer approved

That works because the editor already knows what reads what. Nothing has to be
told about an edit: the status is worked out from the model each time it is
asked, so no code path can forget to invalidate it.

**Locking** holds an approved block: any change to it is put back, and the
editor says which. It is enforced where every edit passes through, so there is
no way round it. Unlock it under All settings to edit it again.

None of this stops a model running. An unapproved block runs exactly as an
approved one does — the record is about whether a person has read it, not about
whether the solver will.

## Version report

**Compare with ▾** under MODEL says what differs between the model in front of
you and another version of it — either **the model as it was opened**, which
answers "what have I changed this session", or **another file**, picked the way
Open picks one (`.json`, `.zip`, `.eco`, `.eas`), which answers "what did they
change between the January and the March assessment". There is no version
history kept inside the file — the two files a reviewer actually has are these,
and the report is between them.

The comparison is by name, block for block, field for field:

```
Version report: this model against well-jan.json
Blocks: 6 before, 6 after — 1 added, 1 removed, 3 changed, 1 renamed, 2 settings
Name: Well → Well, revised

+ compartment Lake
- compartment Well
↔ parameter k_old → k (renamed)
~ parameter Kd
    entries[Cs-137].value: 100 → 200
    entries[Ra-226]: (absent) → {"index":"Ra-226","value":500}
~ transfer Leach
    rate: k_old → k

Index lists
~ RN: + Ra-226

Simulation settings
end_time: 1000 → 10000
```

Where a block sits on the canvas is not a difference; a changed comment is,
because to a reviewer it is. Indexed entries are matched by their index, so a
value changed at `Cs-137` is reported at `Cs-137` rather than as every entry
after it having moved. A block gone under one name and back under another with
nothing else different is a rename, and is said to be. Key order in the file is
nothing. The report can be copied or saved as text; a model that is identical
gets one line saying so.

## Disabling a block

Every block has an **Enabled** switch — under its name in the settings dialog,
and as *Disable* / *Enable* on its right-click menu. Off, the block stays in the
model with everything it has: its equations, its per-index values, its place on
the diagram, where it is drawn faded and dashed. What changes is that it takes
no part in the run. This is Ecolego's own switch, read from a project file's
`<enabled>false</enabled>` and written as `"enabled": false`; a block that says
nothing is on.

**It is how a model with a broken block in it still runs.** A block whose
equation names something that no longer exists, or that was left half-written,
is disabled rather than deleted — and the model builds and runs as long as
nothing that is *still on* reads it. One assessment model arrives with
29 blocks switched off, one of them reading a block that is not in the file at
all; honouring the switch is the difference between that model building and
not.

**It is not in the left panel.** That panel is for the values you are working
on, and a switched-off block has none that change an answer, so the sections
list what is on and say how many are not: *2 more are switched off and not
shown*. They are still in the block tree and on the diagram, greyed, which is
where switching one back on is one click away. A block inside a switched-off
sub-system is left out for the same reason.

The rule is said by name wherever it bites. A disabled block's own equations
are not checked — being broken is very often why it was switched off — but an
enabled block that reads one is told *`Gas_flow` is disabled, so it has no value
here. Enable it, or disable this block as well*, in the problem strip, under the
box as you type, and from the build. Nothing is worked out for a disabled block
at the start of the run, so its lines there go quiet; and it is still a name —
deleting a block it reads is refused the way it would be for any other reader,
since switching it back on would break it.

**A disabled compartment takes its outflows with it.** A transfer whose donor
is disabled has no
inventory to move and is left out of the run too, drawn faded on the diagram
though its own switch is on, with the Information view saying why. A source term
into a disabled compartment has nothing to feed and goes the same way. A
transfer *into* a disabled compartment stays on — its flux still leaves the
donor, and with nothing integrating the receiving end it leaves the model, as a
flux to *outside* does; the Information view says that too, because a flux that
quietly leaves the model is the sort of thing you otherwise learn from a mass
balance.

**A whole sub-system can be switched off.** A sub-system is a block too —
A sub-system carries a block's switch — so *Disable* is on its
right-click menu, on the diagram and in the tree, and off, everything in it and
every sub-system inside it is left out of the run. The node fades, and so does
every block inside; the Information view of a block in it says *Disabled with
`NF`, the sub-system it is in*, with a link, since that is the switch to find.
The blocks keep their own switches untouched, so turning the sub-system back on
returns it to exactly what it was, including any block that was off on its own
account. A sub-system switched off inside another that is off cannot be
switched on from its own menu — the item says which outer one to enable. A
disabled sub-system arriving in an Ecolego file is carried as exactly that, in
`"disabled_systems": ["NF"]`, rather than as its blocks switched off one by one,
which is what this tool did before it had a switch to carry.

**A transfer into a switched-off compartment is warned about.** Only a
transfer's *donor* decides whether it runs — so one whose target is off keeps
draining its
donor and what it moves leaves the model, exactly as a flux to *outside* does.
That is the right rule and it is quiet: the donor's curve does not change,
nothing fails to build, and the inventory that used to arrive somewhere now
arrives nowhere. So the warning list says it, on the transfer, and clicking the
row selects it.

The other direction says nothing. A transfer whose *donor* is off goes off with
it — there is no inventory for it to move — which is what switching off a donor
is for, and nothing is lost by it.

## Undo and redo

**⌘Z takes back the last edit; ⇧⌘Z puts it back** (Ctrl on Windows and Linux,
where Ctrl+Y also redoes). The two arrows beside **Save…** do the same, and each
says what it would do: *Undo Delete 3 blocks*, *Redo Move 2 blocks*. A button
with nothing to take back is disabled, so the pair also says how far back the
model can be walked.

**Everything is undoable**, because nothing had to be made so one edit at a
time. Every edit in the application goes through one function, and what is kept
is the model itself before and after — so drawing a transfer, renaming a block,
retyping a rate, moving a node, pasting from another model, editing an index
list, changing the solver, changing what the diagram shows, and **Apply** on the
JSON tab are all steps, and a kind of edit added later is a step without being
told to be. What is *not* a step is what is not in the model: which tab is open,
which sub-systems are folded on the grid, what the block filter says. What the step *is called* is worked out by comparing the two: a block that
appeared is an *Add*, one that vanished is a *Delete*, one that changed its name
is a *Rename*, one that changed its sub-system is a *Move*. Where nothing
structural changed, the step is named after whatever the editor was pointed at:
*Edit Buffer*.

A few things behave the way they should rather than the way they are:

- **The selection travels with the step.** Undo a deletion and the block comes
  back *selected*, on the diagram it was deleted from — even if you have since
  walked out of that sub-system, in which case the view goes back in. Deleting
  clears the selection on its way out, so honouring what was selected when the
  edit was recorded would have brought three blocks back and left them lost.
- **A colour sweep is one step.** A colour picker reports every colour the
  pointer crosses on the way to the one you meant; the whole sweep folds into a
  single step rather than two hundred.
- **An edit that changed nothing is not a step** — a field committed at the
  value it already held, a menu re-asserting a setting. An undo that does
  nothing visible looks exactly like an undo that is broken.
- **Moving a block does not re-run the model.** Nor does undoing the move: a
  step knows whether it could change a number, and only those mark the results
  stale and start a run.
- **⌘Z inside a text field is the field's own undo.** The model has not heard
  about a half-typed value yet, and the browser's undo is the one meant there.

Opening a model starts its history over. Undo does not reach back across a
file: the thing it would put back is not on the screen to be looked at first.

The stack holds **200 steps**, and holds them as *differences*. The models this
is for are big — one landscape model in the corpus is 8 MB of JSON — and two consecutive
snapshots of an 8 MB model differ in a few dozen characters, so what is stored
is the characters between the longest common prefix and the longest common
suffix: thirty block moves on that model cost **31 characters** between them.
Taking a step costs one `JSON.stringify` of the model, 19 ms on those 8 MB and
0.05 ms on an ordinary one — against the 265 ms that model already spends
re-scanning its equations after every edit.

## A shape that paints nothing

A shape's **Fill** and **Line** can both be *none*, which is a real thing to
want: a group box that only carries a label, or a shape kept for its text.
What that used to mean in practice was a shape you could never get back —
invisible, and selectable only by clicking within a few pixels of an edge you
could not see and had to remember the position of.

An invisible shape now shows a faint dashed outline while you are editing.
It is not part of the picture: **Save as picture** drops it, along with
everything else that is about editing rather than about the model, so what you
export is the shape as the model has it — nothing.

## Compressed model files

A model is repetitive text, so it compresses well — `examples/biosphere.json`
to a sixth of itself, a large assessment from 36 MB to 16 — and the file is
usually on its way somewhere: into a repository, attached to a mail, onto a
memory stick.

**Saving.** The **Save** button opens a dialog: *what* to write down the left,
*how* and *which of it* on the right.

| | |
|---|---|
| **Model** | the model on its own — JSON, ZIP or gzip |
| **Model with results** | the model *and the run it produced*, so it opens again without the solve |
| **Results** | the series themselves — HDF5 or CSV |
| **Every realisation** | a probabilistic run in full: one row per output time, one column per realisation |
| **Data** | parameters and lookup tables — Excel or HDF5 |
| **Run log** | what the solver did, as text |

Everything but the model and the archive is a list of named things, so the
right-hand side is that list with a **search** over it, a filter by kind and by
sub-system, and *All shown* / *None* acting on whatever the search matched —
which is what makes "every far-field path" one gesture. A block brings every
index of it: tick `Dose` and all four nuclides come. The line underneath says
how many blocks are ticked and how many series that comes to.

A row that cannot be written stays where it is and says why — *Nothing has run
yet*, *This needs a probabilistic run*, *The model has changed since this run* —
because "why is this greyed out" is the question a disabled control always asks
and almost never answers.

**The keyboard still just saves.** **⌘S** writes straight back to the file this
model came from with no dialog in between, and the button carries a dot
whenever there is something to write — so *have I saved this?* is answered by
looking. **⇧⌘S** asks where to put it. The dialog is for choosing; the key is
for repeating yesterday's choice.

Opening a model, or starting a new one, forgets the file: a model opened from
disk arrives as a `File` and a page is given nothing it can write back through,
so the first Save after opening asks once and every one after that writes.
Nothing is remembered across a reload, because a button pressed once should not
silently overwrite a file chosen last week.

The model's own formats:

| | what it is | when |
|---|---|---|
| `.json` | the model as readable text | the default; what every other tool takes, and what a diff can show you |
| `.zip` | the same JSON, compressed | sending it to somebody — it double-clicks open on every desktop |
| `.json.gz` | the same, gzipped | keeping it under version control, or anywhere a command line will meet it |
| `.zip` **with results** | the model *and the run it produced* | sending somebody a result, or keeping one — see below |

Pick the format in the dialog, or just type the extension you want — the file
is written as whatever it ends up called, so typing `.zip` gives a ZIP whichever
entry was highlighted. The notice afterwards says how much smaller it came out.

Firefox and Safari have no such dialog and no page can conjure one, so there
the file goes wherever downloads go and every Save is a fresh download — there
is no file to write back to. The format is chosen in this tool's own dialog
either way, which is why it is there rather than only in the system's.

**Importing.** **Import…** reads the file first and then asks what to take out
of it — because the extension cannot answer that. A `.zip` from this tool is a
model *and* a run; a `.h5` is a table of parameter values, or a thousand
realisations of somebody else's near-field. So the dialog lists what the file
holds, one row each:

- **Model** — *Import blocks…* brings some of them into the model that is open,
  with a survey of what each one drags along; *Open it* replaces what is open.
- **A saved run** — opens the model with its results, no solve needed.
- **Data** — parameters and lookup tables, with the same searchable list and a
  dry run saying what would land before anything does.

A row the file does not have stays and says so. Nothing is changed until one of
those buttons is pressed, and each of them asks again.

**Opening.** **Open…** replaces the model. All three formats open, and so does a
compressed Ecolego `.eco`. The format is read from the file's first four bytes rather than its
name, so a model somebody compressed and never renamed still opens, and so does
a `.zip` that a mail system decided to call something else. A ZIP is looked
*into*: one holding a `model.xml` is an Ecolego project, one holding a `.json`
is a model, and one holding neither says so rather than failing with a parse
error about a byte nobody wrote.

Nothing is lost either way — the JSON inside a `.zip` is the same JSON, and the
model that comes back out is identical to the one that went in.

## The solver's own settings

Under **SIMULATION**, below the tolerances, is a fold called **Advanced
settings**, as in facsimile.html and rtm.html, holding the settings **that the
chosen solver actually reads**, and nothing else. Leave one empty and the solver
chooses for itself, which is almost always right. Every setting in the panel —
these and the ones above them — explains itself when you point at its name.

The same settings go by the same names in all three pages, where the name fits
the sidebar's column:

| | what it does | read by |
|---|---|---|
| **Maximum step** | the longest step the solver may take | all |
| **First step** | the first step to try | all |
| **Step budget** | how many steps before it gives up and says so | all |
| **Maximum order** / **Minimum order** | cap and floor the variable-order formulas; set both equal for a fixed order | the NDF/BDF solvers (maximum only) and FBDF/QNDF |
| **Norm control** | judge the error against the norm of the whole solution rather than component by component (MATLAB's NormControl) | `ndf`, `bdf` |
| **Error norm** | the largest of the components' errors, or their root mean square | the vendored methods except Radau, which uses its own |
| **Stall tolerance** | how large a Newton correction may be and still be taken once it has stopped shrinking | `ndf`, `bdf` |
| **Newton tolerance** | how tightly each stage's iteration must converge | the vendored methods with a Newton iteration |
| **Jacobian reuse** | how many steps a Jacobian may be reused | as above, except Rodas5P |
| **Steps at the floor** | how many steps that failed the error test at the smallest representable size may be accepted in a row | the vendored methods |
| **Iteration matrix** | factorise I − hJ with a sparse or a dense LU | the vendored methods |
| **Jacobian** | generated from the equations, or differenced through the same pattern (*finite differences*): the check to run when the generated one is in doubt | every stiff solver |
| **Absolute tolerance follows the solution** | see below | `ndf`, `bdf`, the vendored methods |

**What the chosen solver does not read is named rather than hidden.** Under the
fold there is a line — *"stiff, Rosenbrock 5 does not read the maximum order,
the minimum order, norm control, the stall tolerance, the Newton tolerance and
how long a Jacobian is reused, so they are not shown"* — because a knob that
silently does nothing is worse than a missing one: nothing on screen would tell
you which it was. A Rosenbrock method is linearly implicit, so there is no Newton
iteration to give a tolerance to, and it re-forms its Jacobian every step by
definition, so there is no age to set.

Which solver reads what lives in `SOLVER_OPTIONS` in `src/ode/solvers.js`,
beside the code that passes them on, because that is the only place the answer
stays honest.

## Letting the tolerance follow the solution

**Absolute tolerance follows the solution**, under Advanced settings, is a trade, and worth
understanding before switching it on. Normally a component is judged against an
absolute tolerance fixed before the run — so a nuclide that grew in to 10¹² and
decayed back to 10⁻⁴⁰ is still being resolved to `abstol`, orders below anything
it ever was, and most of the solver's work goes into a number nobody reads. With
this on, after every accepted step a component's absolute tolerance is raised to
the relative tolerance times what it now holds, where that is larger: each
component is judged against the largest it has ever been.

On a decay chain that is most of the work:

| | fixed | floating |
|---|---|---|
| `decay-chain.json`, variable-order | 1,973 steps | **512** |
| the same, FBDF | 3,399 | **886** |
| the same, Rodas5P | 762 | **193** |

**It only ever loosens, which is the point and the risk.** A quantity that
peaked high and then decayed is no longer controlled in its tail: on
`biosphere.json` one nuclide comes out as 94 Bq where it should be 41. So it is
off by default, and a result that leaned on it is worth checking against a run
without it — the run log records that it was on.

It is an idea from the NDF error test, and only the solvers that have one can
do it: the variable-order solver and the six vendored methods beside it. Choose
`ros23` or `dp45` and the switch greys out and says so, rather than doing
nothing quietly.

## The mass-balance audit

**Mass balance** under SIMULATION is a check to run, not a way to run. Switch it
on and the run carries a budget for every radionuclide (and one for the
compartments that are not indexed by one): what came **in** from outside, went
**out**, was lost to **decay**, gained by **ingrowth**, moved by an **explicit**
dy/dt term, or moved **between** families — a per-nuclide compartment draining
into one that is not indexed. At every output time the inventories are checked
against it:

```
Σ inventory(t) − Σ inventory(0) = in − out − decay + ingrowth + explicit + between
```

and the status line says how it went — `mass balance closes (9e-11)` — with a
line per radionuclide in the tooltip and in the run log:

```
Sr-90: holds 345.8 at the end = start 1000 + in 2000 − out 925 − decay 2129
       + ingrowth 0 + explicit 400; residual -1.4e-8 (6.7e-12 relative, worst at t = 76.9 year)
```

The budgets are integrated by the solver with everything else, and every solver
here is linear in the state, so this closes to within the solver's tolerance —
round-off with an explicit solver, about the relative tolerance with an
implicit one, whose Newton iteration stops there — unless something outside
the equations moved mass. The one thing that does is **cannot go
negative**: a compartment held at zero while its equations pushed it below has
had mass put back that the equations took away, and the audit shows it as an
open balance where the held-at-zero count only says it happened. That is what
it is for.

It is a check of the bookkeeping, not a conservation law: in becquerels the
total is not conserved, since decay changes activity by the ratio of the
half-lives, and the audit does not pretend otherwise. It costs `6 × (nuclides +
1)` extra states and the analytic Jacobian — the run works out df/dy by
differencing while it is on — and because the budgets take part in the
solver's step-size control the curves are the plain run's to within the
tolerance rather than to the bit. That is why it is off by default, and saved
with the model as `simulation.mass_balance`.

## The run log

Every run keeps a log — **log** at the right of the status line opens it — of
what the run was, in words that survive it: the program build and the time,
the model's name, every simulation setting (solver, tolerances, output grid,
decay unit, the decay-chain ceiling if one is set), the solver's account of the
run (states, steps, rejections, function evaluations, how df/dy was obtained,
events and restarts), what was held at zero and for how long, the mass-balance
audit when it is on, and — when a probabilistic run or a tornado stands — its
seed, sampling, correlations, failures and categories. A replayed realisation says which it is and lists the
value every input took. **Copy** and **Save as text…** do what they say.

It is the audit trail: six months on, somebody asks which tolerance, and the
status line that knew was replaced by the next run's.
**Save with results…** writes the log into the archive (`results/meta.json`),
and a saved result opened later shows the log it was saved with first, under
*as saved with the results*, before the account of the opening.

## Saving a run, and opening it again

**Save with results (.zip)…** writes the model *and the run it produced*. Open
that file and the curves are there — the chart, the table, the CSV and the HDF5
export, all of it — with nothing solved. On the largest assessment here a run is
sixteen minutes in the solver and forty-three end to end, which is the whole
argument for it.

**What is in the file is the state vector, not the series.** Every other series
this editor shows is worked out from the states when something asks for it, so
the file holds what the solver produced and not the hundreds of thousands of
lines that follow from it — the difference between about 80 MB and about 2.8 GB
for the same information. It is also the difference between a picture of a run
and the run itself: what opens is a *live* result, and a series nobody has
looked at yet is worked out the moment you ask for it, exactly as after a solve.

It is an ordinary model file as well. The model sits at the root of the archive
where a plain compressed save puts it, with the run beside it under `results/`,
so anything that reads a `.zip` model — including an older build of this editor
— opens the model and ignores the rest.

```
four-compartment.json      the model
results/meta.json          the run report, and what the numbers mean
results/t.f64              the output times
results/y.f64              the state vector at each of them
results/held.i32           what the zero-floor held, and for how long
results/mem.f64            the histories of the blocks that remember
```

**The blocks that remember are in there too** — a peak, a running mean, a
snapshot, a delay. Their values are accumulated *during* the integration rather
than worked out from the states, so a file without them would reopen with a
model that has never run and report a peak dose of nothing much. (Re-running
after an edit refuses to reuse states for exactly this reason; here the model
travels in the same file as the run, so there is nothing to prove and the
histories simply come along.)

**What it refuses.** The archive records what its numbers mean — every entry of
the state vector and every recorder slot, by the name and offset the model gave
it. Opening checks that against the model in the same file, and a mismatch drops
the results and says so rather than drawing plausible numbers under the wrong
labels. Saving refuses too, if the model has changed since the run: that is the
same dot the **Run** button is already showing, and a file pairing this model
with last model's results would be a lie the layout check could not catch.

## The tab remembers what you were working on

Nothing here used to be written down anywhere. A model lived in the page and
nowhere else, so a refresh, a crash or a stray Cmd-W took it — including the
tidying that opening a file does, which you never chose to keep and could not
get back.

The tab now keeps a **draft**: the model as it stands, written a couple of
seconds after you stop typing. Open the page again and a line above the tabs
says what it was working on and how long ago, with **Restore** and **Discard**.
Neither appears if the draft is what is already on screen.

It is a draft and not a save, and the difference matters:

- it lives in this browser, on this machine, for this address — nobody else can
  open it, and it does not travel;
- **Save…** is still the way to keep a model. That writes a file you can put
  somewhere, send to somebody, and open next year;
- a browser holds a few megabytes per site, and a large assessment is tens.
  A model too big to keep is **not** kept, and the editor says so once rather
  than letting you believe there is a draft when there is not. On those models,
  save early;
- a private window, or a browser with site data switched off, keeps nothing.
  Everything still works; there is simply no offer next time.

## Edits that do not need solving again

A run produces one thing: the inventory of every compartment over time. Every
other line — a concentration, a dose, a flux, a parameter drawn flat beside
them — is worked out from that afterwards, when something asks for it.

So an edit that cannot move the inventories does not start the solver. Change
the dose coefficient, rewrite the dose equation, add an expression that divides
one dose by another: none of that reaches a compartment, the states are still
the states, and what comes back is the same trajectory with the algebra over it
worked out again. On a model that takes a minute to build and sixteen to solve,
that is the difference between an edit you can make and one you plan around.

**It is decided by what the integration reads, not by what kind of block you
edited.** A parameter feeding a transfer rate is part of the integration and a
parameter feeding only a dose is not — the same kind of block, opposite
answers. The chain is followed the whole way: a rate reading an expression
reading a parameter puts all three inside. The footer says which happened —
**solve** carries a time when the model was solved, and reads *not repeated —
the states were already right* when it was not.

**Two things always solve again.** Anything reaching a compartment's initial
value, a transfer or source rate, or a far-field pathway; and anything at all in a
model with a **block that remembers**. A peak, a mean from a given year, a value
a century ago — each is accumulated *during* the integration, so a model that
carries one is always solved in full.

**And a transport counts as a rate.** How long a chain is, whether a sub-system
*is* a chain, which sub-systems are switched off: none of those is an equation
anything reads, so none of them was noticed. Turning a transport off and back
on used to leave the old curve on screen looking like the new one — the states
even laid out identically, so nothing downstream could tell. All three are part
of what the integration depends on now.

**How much of a model is free depends on what the model is for.** A chain that
ends in a dose has a whole tail of post-processing outside the integration:
`examples/biosphere.json` has five of its twenty blocks there. A near-field
transport model has almost none — across eleven assessment models, 412 of
24,877 blocks can be edited without solving again, because in a model whose
subject *is* the transport nearly everything feeds a rate.

**Adding is always free, whatever the model.** A new expression, a new
parameter, an expression over that parameter: nothing integrating reads them, so
nothing needs solving. On model A — 22,842 states, 15.3 seconds in the
solver — adding an expression costs the half-second rebuild instead, and working
out which it is takes 30 milliseconds.

The scan that decides all this — every equation re-read, every unit checked,
every transport looked over — runs after each edit, and used to be 1.4 seconds
on the largest assessment here. It is **64 milliseconds** now: the two passes
that dominated it were each resolving a name by walking every block in the
model, once per reference.

## Telling the solver where the model changes

A solver chooses its steps by fitting a polynomial to what it has just seen,
which works because what it has just seen is smooth. A source that switches on
at year 1,000, a cap that fails at 300, a well drilled at 50 — each is a corner,
and an adaptive stepper meets one in one of two ways: it steps across it and
fits a polynomial through a discontinuity, or it rejects that step and bisects
its way over at considerable cost.

Neither is necessary, because the model knows where its corners are.

```json
"simulation": { "switch_times": ["t_cap_fails", 1000, "t_well"] }
```

Numbers, or the names of parameters and expressions that come to a number
before the run starts — a name because a switch time is usually *also* a
parameter, and writing the year in two places is how the two come to disagree.
The solver restarts at each of them, exactly as it restarts at a discrete event.

**This is not a nicety.** A source that is on for five years out of a thousand,
with the corners undeclared, is stepped clean over: the run reports that nothing
was ever released. Declare them and the same model gives the right answer to
four figures. A lookup table needs no declaration — its points are already
places the value may turn, and the builder knows them.

## Working the rates out less often

Every rate, source and decay term that varies with time and nothing else is
recomputed at every step the solver takes. On a long-running model those change
over centuries while the solver steps in years, so nearly all of that work
produces a number indistinguishable from the last one.

```json
"simulation": { "min_change_time": 500 }
```

says how often they are really worth recomputing; between two such instants they
are interpolated linearly. It is off unless a model asks for it, an interval
never spans a declared switch time, and it is an approximation the model chooses
knowingly — set it larger than the time over which rates actually change and it
will smooth away a change that mattered. On a model whose algebra dominates,
a coarse interval is worth two or three times the speed for a part in a million
of accuracy.

## Solvers

Each solver has two names. The interface calls it by what it is *for*, since
that is the choice a modeller is actually making; the project file and every
error message use the method's own id, so a run can still be compared against
desktop output. `src/ode/solvers.js` is the one place both are defined.

```figure solver-choice
                    is it stiff?
                   /            \
                 no              yes
                 |                |
      Dormand-Prince 4-5    NDF (the default)
      smooth, well-scaled,        |
      few states           will not converge?
                                  |
                           Rosenbrock 5 — no Newton iteration,
                           so there is nothing to fail
```

| In the interface | id | Method | Notes |
|---|---|---|---|
| **stiff, NDF** | `ndf` | Variable-order numerical differentiation formulas | **The default.** The standard variable-order choice for a stiff problem, and usually the cheapest here: on the bundled `landscape.json` it takes a quarter of `ros23`'s steps for the same answer to seven figures, and it re-forms its iteration matrix only when the step size or order changes, where a Rosenbrock method re-forms it at every step. |
| **stiff, BDF** | `bdf` | The same, with the NDF terms off | Plain variable-order backward differentiation formulas. One integrator under two names: `bdf: true` zeroes the κ terms, which is exactly what makes an NDF a BDF. A few more steps than the NDFs for the same answer (480 against 477 on `biosphere.json`), so run both to see what those terms buy, or to match a result someone else worked out with BDF. |
| **stiff, low order, Rosenbrock 2-3** | `ros23` | Rosenbrock (2,3) | Robust, lower order, and it re-forms its iteration matrix every step, which makes it steady through a discontinuity. Holds a compartment on zero once it reaches the bound — see below. |
| **non-stiff, Dormand-Prince 4-5** | `dp45` | Dormand–Prince (4,5) | Cheaper per step on a smooth problem, but stalls when rates differ by orders of magnitude — which most decay chains do. |
| **stiff, Rosenbrock 5** | `rodas5p` | Rodas5P | Order 5, L-stable, and **no Newton iteration at all**, so there is nothing to fail to converge — the one to reach for when a model will not run. On `biosphere.json` it is both the most accurate solver here and a third of `ndf`'s steps. |
| **stiff, Radau IIA 5** | `radau5` | RadauIIA5 | Fully implicit Runge–Kutta of order 5 — a different family from every BDF solver here, and the least order reduction on a stiff problem. The one to believe when two others disagree. It factorises densely, so prefer `fbdf` above a few thousand states. |
| **stiff, fixed-leading-coefficient BDF** | `fbdf` | FBDF | SciML's recommendation for the largest stiff systems: it reuses one matrix factorisation across many steps, which on hundreds of states is most of the cost. |
| **stiff, quasi-constant-step NDF** | `qndf` | QNDF | Shampine and Reichelt's NDFs — the same method `ndf` implements, written independently from the Julia sources. The closest thing here to a line-by-line check of the default solver. |
| **stiff, ESDIRK 4** | `kencarp4` | KenCarp4 | Order 4, L-stable. A reasonable middle: cheaper per step than Radau, higher order than the low-order Rosenbrock. |
| **stiff, ESDIRK 2 (loose tolerances)** | `trbdf2` | TRBDF2 | Order 2, L-stable, forgiving — and second order is the catch: on sharp transients it loses phase accuracy long before local accuracy, and reports success either way. Use it loose, or use the ESDIRK 4. |
| **SciPy BDF, stiff** ↓ | `scipy_bdf` | `solve_ivp(method="BDF")` | The same family as `ndf`, written independently of it. A second opinion rather than a faster route to the same one. |
| **SciPy Radau IIA, stiff** ↓ | `scipy_radau` | `solve_ivp(method="Radau")` | Implicit Runge–Kutta of order 5 — a different family altogether, so it agrees with the BDF solvers for different reasons. The strongest check of the three. |
| **SciPy LSODA, auto-switching** ↓ | `scipy_lsoda` | `solve_ivp(method="LSODA")` | The ODEPACK routine that detects stiffness and switches between Adams and BDF itself, so it needs no choice from you. Usually the quickest of the three. |

The three marked ↓ need a download the first time they are used; the rest
never touch the network. See [A second opinion: the SciPy
solvers](#a-second-opinion-the-scipy-solvers).

**Six of them come from [DifferentialEquations.jl][sciml]**, vendored whole in
`src/ode/julia/` and adapted in `src/ode/julia-solvers.js`. They matter for two
reasons. Two are families this tool had nothing of — a Rosenbrock–Wanner method
with no nonlinear iteration, and a fully implicit Runge–Kutta — so a model that
will not converge under the BDF solvers now has somewhere to go. And unlike the
SciPy solvers they are a second opinion that works **offline**: the three
marked ↓ download a Python runtime, these are just there.

They take the same analytic Jacobian the built-in solvers take, stop at the
same discrete events, and report the same statistics, so nothing else in the
program knows the difference.

[sciml]: https://docs.sciml.ai/DiffEqDocs/stable/

The formulas live in `src/ode/ndf.js`, and `src/ode/variable-order.js` adapts
them to the interface the other two use. Both stiff solvers are handed an
analytic Jacobian — see below — which is what makes the larger models
practical.

Pick one under **Solver** in the left panel; hovering an option describes it.
The default is the variable-order stiff solver, because compartment models with
decay almost always are stiff. If a run stops with a step-size or progress
error on the non-stiff solver, that is what it is telling you.

## Looking at the Jacobian

`df/dy` — how each equation moves with each state — is the one thing a stiff
run depends on that nobody ever looks at. It is generated from the model's own
equations, it decides how many steps the solve takes, and **when it is wrong
the symptom is a slow run or a subtly different answer rather than an error**.
The *Jacobian* view of the **Generated code** tab draws it, and checks it.

```figure jacobian-pattern
   columns: the state differentiated with respect to
   rows: the equation
      +-------------------------+
      | #                       |   # the diagonal
      | * #                     |   * an entry
      |   * #                   |
      |     * #                 |   a decay chain is a band
      |       * #               |   just off the diagonal
      +-------------------------+
```

**The picture is the sparsity pattern.** A compartment model's matrix is nearly
all zeros, and the shape of what is left says a great deal at a glance: a decay
chain is a band just under the diagonal, a landscape model is a block per
object, a transport is a tridiagonal stripe. A dense row is something that
reads everything; a dense column is something everything reads. Hover a cell to
name the two states. Above one cell per pixel — past about five hundred states
— each pixel stands for a block of the matrix and is drawn if anything in that
block is non-zero, which over-states the density and is the safe direction for
a picture whose job is to show where the structure is.

**Beside it, what the pattern is worth.** How many entries it has, how dense it
is, whether the matrix is the same at every point (then it is formed and
factorised once for the whole run), and how many evaluations of the model a
*differenced* Jacobian would cost through this pattern — one per group of
columns that share no row, typically five or ten against one per state. That
number is the whole reason the pattern is worked out.

### What the check does

**The picture is drawn as soon as you open the view** — it is structural, and
costs nothing beyond building the model. **Checking the values is a separate
button**, because that is the slow half: it compares the matrix against finite
differences of the derivative it is supposed to be the derivative of. Neither
is the truth — one is exact arithmetic on a possibly wrong expression, the
other inexact arithmetic on the right one — but they come from different code,
so agreement is worth something and a disagreement is always worth reading.

Three things are looked at, and they are reported worst-first because they want
different fixes:

| | What it means |
|---|---|
| **The colouring is wrong** | Two columns in one colour group share a row, so the values read back through it are sums. Nothing about the matrix itself is wrong; the scheme for filling it is. |
| **An entry is missing** | Differencing finds a value where the pattern has no entry. This is the one that matters most: **the solver never evaluates an entry the pattern does not have**, so no tolerance recovers it, and the run converges to something else. |
| **An entry differs** | The pattern is right and a value is out by more than 0.1%. |
| **Agrees** | Every entry that a difference can resolve matches. |

**Where it is checked.** Not at one point, and not only at the start. The
*pattern* does not depend on the time or the state at all, but the *values* do
— so the comparison is made at the model's own initial state and then at
states with every compartment given something, spread across the run. An empty
compartment contributes nothing to any column, so a model that starts with one
nuclide in one box would otherwise report a clean bill on a matrix it had
barely touched. A very large model checks at two of those rather than four,
and says so.

**"Below what a difference can resolve" is counted, not judged.** A difference
quotient subtracts two nearly equal numbers, so an entry whose effect on the
derivative is smaller than that derivative's own rounding says nothing either
way. Calling those a disagreement would bury the real ones; calling them
agreement would be a lie. Most of a decay chain is unresolvable at the starting
state, which is exactly why several states are used.

**The colouring is what makes it affordable.** A group of columns shares no
row, so perturbing all of them at once moves each row by the one entry of that
group which owns it — which means one evaluation of the model covers every
entry of every column in the group, rather than one evaluation per column.
That is the same trick a differenced Jacobian uses, and it is why the check
reads the whole matrix rather than a sample of it. Finding an entry the
pattern does *not* have is the one question the colouring cannot answer, and
that pass does cost an evaluation per column, so it is sampled — spread across
the matrix, because a model's states are laid out block by block.

The check runs off the page, so a large model does not freeze the tab, and the
report is thrown away as soon as you edit the model: the matrix is generated
from the equations, and a stale *agrees* would be worse than no answer.

## What a run keeps

A run stores its **states** — the compartment inventories at each output time —
and nothing else. Every other series you can chart or tabulate — an expression,
a transfer's rate, a table read at the clock, a reduction, what a min/max or a
running mean holds — is worked out from those states when you ask for it, one
pass over the rows for however many lines the chart is showing. The numbers are
the same ones the solver saw: everything algebraic is a function of the clock
and the state, and the blocks that remember keep their histories against time,
so asking about an earlier row afterwards answers as of that row.

This is why a large model no longer needs the memory it did. Storing every
series of a landscape model of 200,000 values over 500 times was 800 MB before
a line was drawn; the states alone are a twelfth of that. The one thing that
still costs what it always did is *Export every output*, CSV or HDF5, which
asks for every column at once — and says so while it works. See
[Saving the results](#saving-the-results) for what each of them writes.

## Saving the results

Right-click the **Table**. Three ways to choose what goes in the file — the
table as it stands, every output the run produced, or **Choose endpoints to
save…** — and two formats for each.

### Choosing endpoints

An **endpoint** is a block whose result is kept, and a project file carries
the list:

```xml
<outputs>
  <output id="NearField&#46;waste_domain_length"/>
  ...
</outputs>
```

the run writes a series for those and for nothing else, which is why an
Ecolego result file of a three-thousand-block model holds two groups: somebody
decided what was worth keeping. This tool keeps everything — every series is
worked out from the states when asked for, so holding them costs nothing — and
that is right for *looking* at a model and wrong for *saving* one. A run of
model G has 831,314 series, which is 2.8 GB of HDF5 and more than
a tab can build.

So the third export is a list of the blocks the run produced, ticked. **The
model's own endpoint list is what it opens on** when the file came with one, so
the common case is one click; otherwise it opens on whatever the table is
showing. Search by name or by kind (`parameter` narrows to parameters), and
**All shown** and **None** act on every match rather than only the rows drawn.
The line under the toolbar says what it comes to — *100 of 1485 blocks — 1,835
series over 356 times, about 5 MB* — and moves as you tick.

**An endpoint is a block**: tick `Dose` and every nuclide of it goes. Picking
831,314 series one at a time is not something a dialog can offer.

What you choose is **saved back to the model**, under `simulation.endpoints`,
because an endpoint list is a property of the model rather than of one export,
and because picking the same forty blocks every time is not a thing to ask of
anybody. It is an ordinary edit: undoable, and written into the project file.
It changes no number, so it does not re-run anything.

An export of more than half a gigabyte of numbers asks before it starts,
whichever of the three it is: the file is built in memory before the browser is
handed it, so the question is not patience but whether the tab can hold it.

**CSV** is one row per output time and one column per series, with the time
first. The header quotes any label that holds a comma or a quote, which every
indexed output's does (`Soil[Cs-137, Lake]`), so a spreadsheet reads one column
per series rather than splitting the label in two.

**HDF5** is what Ecolego itself writes, and what the tools around it read — the
result browser at [kvotab.se/rb.html](https://kvotab.se/rb.html) opens a `.h5`,
walks its tree and draws every radionuclide of a block as one chart. A CSV
cannot say any of that: a column called `Soil [Cs-137, North]` is a name
somebody has to take apart again, and nothing in the file says what the units
are, which index list those nuclides came from, or what the time column is
measured in.

The shape is the one the assessment tools read, taken from real files:

```
/time                        the output grid, once, with its unit
/IndexLists/Radionuclides    the members of each index list, in order
/Lake/                       an indexed block, as a group
     @IndexLists = ['Radionuclides']
     @time_dependent = 'TRUE'
     @unit = 'Bq'
     Cs-137                  one dataset per member
     H-3
/NearField/Flux              a block with no indices, as a dataset
```

A sub-system is a group, so `bio.Soil` is at `/bio/Soil`; a block indexed by
two lists nests, `/Dose/<area>/<nuclide>`, with the nuclide as the leaf — which
is where Ecolego puts it, a dose in one of its own files sitting at
`/biosphere/1BLA/drained_mire/total/Cs-137`. Each series carries its unit, its
kind, the block it came from and its full label; the root carries the model's
name, when it was written, the time unit, the run's ends and which solver ran
it. Between them there is enough in the file to read it a year later without
the model beside it.

**The model's description goes in as `Information`**, which is the attribute
the result browser renders as markup rather than prints. So the four lines an
imported model carries — where it came from, what is in it, what it is indexed
by, what it runs — read as four lines there. The description is plain text in
this application, so it is escaped on the way out and only its structure is
turned into tags: a blank line becomes a paragraph and a single newline a
break. A model with nothing to say gets no attribute rather than an empty one.

The writer is this tool's own — `src/io/hdf5.js` — because the alternative is a
4.7 MB WebAssembly build of the HDF5 library fetched from a CDN, and this
program is files in a folder. See [INTERNALS.md](INTERNALS.md) for what it does and
does not write.

## When results are saved

A safety assessment starts at zero and runs for a hundred thousand years, and
**a single series cannot describe both ends of that**. Logarithmic spacing from
a start of zero has to begin somewhere above zero — this tool begins at a
millionth of the end time, Ecolego at 1 — so a release that is over in the
first year happens *between the first two saved points*, and the chart shows a
vertical line and nothing else.

**Time spacing**, in the Simulation panel, is therefore five things:

| | What is saved |
|---|---|
| **Logarithmic** | one geometric series over the run, from `output_points`. The shorthand every file of this tool's own uses, and what a result spanning decades is read in |
| **Linear** | one even series over the run |
| **Several series…** | a list of series, combined: a geometric one for the run, an even one for its first year, and any times written out by hand. Ecolego's `TimeSeriesList` |
| **The solver's own points** | no grid at all — the result is reported at every step the solver took |
| **Series and the solver's points** | both of those, merged |

The last three are Ecolego's own three output modes, which its files carry in
`<output-options>`: *Produce specified output only*, *Produce no additional
output* (its **default**), and *Produce additional output*. `EOutputMode` in
`JavaSimulatorNextGeneration` is where they are decided; `src/domain/timeseries.js`
has the same generators.

### A list of series

Each series has its own two ends and its own number of points, and contributes
whatever falls inside the run:

```json
"simulation": {
  "start_time": 0, "end_time": 1e6, "spacing": "series",
  "output_times": [
    { "kind": "log",    "points": 400, "from": 1, "to": null },
    { "kind": "linear", "points": 21,  "from": 0, "to": 1 },
    { "kind": "times",  "times": [0.001, 0.01, 0.05] }
  ]
}
```

That is 423 saved times, 22 of them inside the first year, against **none** for
the logarithmic shorthand over the same run. `from` or `to` left out means the
simulation's own start or end — the format's own “not set”.

**A time outside the run is skipped, not refused.** The solver never reaches
it, so it cannot report it, and that is all there is to say: a `times` list
written for a longer run, or a series whose `from` lies past the end, simply
contributes less — or nothing. A series that contributes nothing is worth
knowing about, since it looks exactly like one that is working, so the editor
marks it *nothing in the run* and the sidebar's **Saved times** count says how
many series are entirely outside. The run's own start and end are always saved,
so there is always something in the grid.

The result is a **set**: every series is combined, sorted, and duplicates are
removed, with the run's own start and end always in it. Two series that overlap
therefore cost nothing, and a linear series ending at 1 beside a geometric one
starting there produce one point at 1 rather than 1 and 0.9999999999999998.
Anything outside the run is left out — a time the solver never reaches is not a
time it can report.

Edit them from **Saved times** in the panel, which says how many times the list
comes to and opens an editor for the series. The preview at the bottom of that
dialog is the *engine's* answer, from the same `combineSeries` a run uses: a
preview that agreed with the editor and disagreed with the run would be worse
than none.

### The solver's own points

The other way round: ask for no times at all and report every step the solver
took. It already takes small steps where the answer is moving and large ones
where it is not, which is the distribution a result wants — so nothing has to
be chosen in advance, and the first year of a run is as well resolved as the
model needs it to be.

Every solver here already announces each accepted step, because the blocks that
remember have to see them, so this needs nothing from the solvers: the span
becomes the two ends of the run and what comes back is the steps collected on
the way. **The step is the output**, not an interpolation onto a grid.

Two things worth knowing. **How the steps are spread is the solver's own
business**: the variable-order stiff solver opens at a fraction of a year and
grows geometrically, which is what makes this mode useful, while an explicit
method is held to a nearly fixed step by its own stability limit — `h·λ` of
about 4 for a decay of `λ = 1` — and gives an almost even spread however small
the inventory becomes. And there are **a great many of them**: a stiff run over
a million years may take a quarter of a million steps, so they are thinned
while being collected, keeping every k-th, and the footer says which: `points
4713 of 301486 steps, every 64`.

A model with nothing to integrate has no steps to report, so it falls back to
the grid — the algebraic-only models are evaluated on `output_points` as they
always were.

**A probabilistic run cannot use them**, and says so before it starts. The
steps are a per-run answer: a thousand realisations take a thousand different
sets of them, and with no time that every realisation was reported at there is
no column to take a percentile down. So the realisations are reported on the
grid — `output_points` times, logarithmically spaced — and the solver is asked
for exactly those, answering out of its own interpolant. They are as accurate as
any other run, the run is a little faster for not collecting a quarter of a
million steps it would discard, and single runs are unaffected. The corner of
the Chart says when this has happened, and the band is drawn against the run's
own times underneath it.

### An explicit dy/dt term

A compartment's rate of change is normally what its transfers and its decay
say it is: what flows in, minus what flows out, plus ingrowth, minus decay.
A term of your own can be added to that sum — the **dy/dt** column of a
compartment's grid, which a project file carries per entry — and
so does this tool. In the settings dialog it is the **dy/dt term** box under
the initial inventory; in a `.json` file it is `dydt`:

```json
{ "name": "Rabbits", "initial": "10", "unit": "Rabbit",
  "dydt": "a*Rabbits - b*Rabbits*Foxes" }
```

The term is added to the compartment's own equation beside whatever its
transfers give, so `dC/dt = term + inflows − outflows − λC`; a compartment with
no transfers at all and `-k*C` for a term decays exponentially, and one with
`S` for a term and nothing else fills at S per year. It is in the compartment's
unit per unit of time — `Bq/year` for a compartment in `Bq` — and the unit
check says so if the equation works out as something else.

Unlike the initial inventory, which is worked out once before the run, the
term is evaluated with the state at every step, so it may read anything at all:
parameters, expressions, other compartments, the clock — and **the compartment
itself**, which is the one place an equation may name its own block. That is
what makes the predator–prey pair above writable in one indexed compartment:

```json
{ "name": "Eco", "index_lists": ["Animals"], "initial": "10",
  "entries": [
    { "index": { "Animals": "Rabbit" }, "dydt": "a*Eco - b*Eco*Eco[Fox]" },
    { "index": { "Animals": "Fox" },    "dydt": "e*b*Eco*Eco[Rabbit] - c*Eco" }
  ] }
```

A bare `Eco` inside the term is this index; `Eco[Fox]` is the other. A term
set for one index alone is zero at the rest, and the **dy/dt** column of the
per-index grid is where those are typed. The Information view shows the term
under the initial inventory and counts what it reads among the compartment's
*Uses*; renaming a block rewrites it; the analytic Jacobian carries it, so the
stiff solvers see `-k*C` as the diagonal entry it is.

Two things it is not for. A flux between two compartments is still a transfer:
a term takes from nowhere and gives to nowhere, so mass written into one
compartment's term does not leave another's. And a term is not the place for a
cap or a floor — the *cannot go negative* switch is the only constraint the
solvers apply, and a term that fights it produces the same hold-at-zero
behaviour any other rate does.

It comes across from a `.eco` file: `<differential-equation>` on an entry is
read into `dydt`, at the block level or per index, and an empty one — which is
what Ecolego writes on every entry that has none — is nothing. In a transport,
Begin's term is every slice's except End's, and End keeps its own; see
*Transports*.

### A tolerance for one compartment

The simulation's **absolute tolerance** is the error the solver is allowed on
every state. One number rarely fits a model whose inventories span decades: at
`1e-9` Bq a compartment holding `1e12` Bq is being controlled to twenty-one
significant figures it does not have, while a trace daughter really sitting at
`1e-8` Bq needs that tolerance to be integrated at all.

So a compartment may set its own, in the inspector under **Absolute
tolerance** — and, for a compartment that is indexed, one nuclide of it may
differ from the rest, in the `abs. tol.` column of the per-index grid. Blank
means the simulation's, which is what every model says until it says otherwise.

```json
{ "name": "Waste", "initial": "1e12", "unit": "Bq", "abstol": 1e-3,
  "entries": [{ "index": { "Radionuclides": "Pu-239" }, "abstol": 1e-12 }] }
```

It is per index because the entry is: the run fills the tolerance vector with
the setting and then overrides each state that says something of its own. It
comes across from a `.eco` file too — the field is written on every entry such
a file saves, and is empty in all 9,695 of them across the 87 projects here,
so nothing changes for a model that says nothing.

Every solver takes it, the SciPy ones included. Zero, negative and infinite are
refused: the first asks for a relative-only error test none of these solvers
implements, and the last has nowhere to go in a JSON file.

### Keeping a compartment non-negative

An inventory cannot be negative, so every compartment carries **cannot go
negative** and it is on unless you turn it off. It is the one constraint any solver here applies
option, and the only constraint any solver here applies.

It is worth being able to turn off. A compartment held at zero by the
constraint looks like a result, and it is usually a modelling error being
hidden — a rate with the wrong sign, a transfer draining something that was
never filled. Turning the flag off shows the negative inventory the equations
actually produce, which is the thing you need to see.

**And there is one switch over all of them.** *Cannot go negative enabled*
under **Simulation** is the model's master switch: on, every compartment decides for
itself, which is the default and what a model does unless somebody changed it;
off, nothing is held at zero anywhere and the equations are integrated as
written. The per-compartment settings are left exactly as they are and simply
not consulted, so turning it back on restores what the model said rather than
whatever was last edited.

Use it when you want to see what a model really does before deciding which
compartments should be held — unticking one box is a question you can ask of a
three-thousand-block assessment in a second, where clearing three thousand
flags is not a question at all. It is also how you find out whether a flat line
at zero is the constraint or the chemistry: run it once with the switch off,
and the ones that dive were being held.

A project file carries this setting too, under the name *Enable saturation*.
It is read before the first compartment is looked at — off, the solver is
handed no constraint at all. An imported file defaults it *off* and this tool
defaults it *on*, because in a file it also gates an upper and lower saturation
band that this tool does not carry, and here the floor is all there is. An
imported model arrives with whatever it was saved with, and is told so when that turns
the floor off: of the twelve real assessments tested against, eleven have it on
and one assessment model has it off.

Only compartments get it. The blocks that remember carry integrals that may
legitimately be negative — a running mean of a negative quantity is negative —
so holding those at zero would change the number they report.

**A constraint that binds makes the derivative discontinuous at zero**, and the
three solvers do not cope with that equally:

| | behaviour when the constraint actually binds |
|---|---|
| `ndf` | Carries it. Where a compartment sits on zero and its equations push it below, its derivative is held at zero and its row of the iteration matrix becomes a row of the identity, so it stays exactly on the bound while the rest of the model integrates against it — the *projected system*, which is what the option means. A compartment within its absolute tolerance of zero and pushed past it is put onto the bound rather than chased towards it, and the release is found by the error test as it finds any other change in a rate. |
| `ros23` | Carries it once the compartment is on the bound: a compartment within its tolerance of zero and pushed past it is put there, and the derivative of a compartment on the bound is held. The approach to the bound from above is where a one-step method struggles — its stages straddle the kink and disagree, so the step is cut and cut again — and where that never resolves the run stops and says so, naming the cause and the solver to use. |
| `dp45` | Stalls. It folds the violation into the error estimate and rejects the step, which no step size can fix, so it reports that it has stopped making progress. |

A violation inside a step — a compartment carried a little below zero by a
step that was otherwise fine — is bounded by the tolerance and projected back
onto zero, in all three. That is not a hold, and is not reported as one.

**A hold is reported.** When *cannot go negative* holds a compartment at zero
while its equations push it below by more than the tolerance, the footer says
so — `held at zero B 100%` — with the compartments and the share of the
solver's steps they were held for, and the explanation in the row's tooltip.
The flat line at zero is then known for what it is: the constraint's, not the
equations'. A run with nothing held shows nothing, which is most runs.

Every solver here carries a step budget and a no-progress check, since in a
Worker there is nobody to press Ctrl-C. The `ndf` check needs two signals before it gives up — no ground covered *and* a step
size that has stopped growing — because a violent initial transient
legitimately crawls: a model whose derivative starts at 1e150 reaches only
t=1e-42 after two thousand accepted steps, and then recovers.

The two failures carry a hint naming `ndf` and the flag, because on the face
of it they read like stiffness.

If a cap is part of the model rather than a guard against nonsense, express it
as a rate term — a transfer whose rate falls to zero as the compartment fills —
rather than as a hard bound. That is what Ecolego's own models do, and it is a
model the solver can integrate instead of one it has to fight.

#### What happened to the saturation band

Ecolego's Compartment carries `lower-saturation` and `upper-saturation`, and
this tool used to carry them too. They are gone, because only `ros23` could
honour them: `ndf` refused a model that set one and `dp45` would stall on
it, so a band meant three different things depending on the solver — which is
not a feature, it is a trap.

Importing an `.eco` file maps what it can. A floor of zero with no ceiling says
exactly what **cannot go negative** says, so it crosses silently; a negative
floor is the file saying that compartment may go below zero, and crosses just
as cleanly the other way. A real band — a positive floor, or a finite ceiling —
has no equivalent here, so it is dropped and the import report says so, naming
the block. An import that quietly relaxed a cap would give you a model that
runs and is not the one in the file.

### A second opinion: the SciPy solvers

The three solvers above are **this project's own**: this code integrating
equations this code generated, checked against closed-form solutions and
published benchmarks. That catches a great deal, but it cannot catch a mistake
shared between the code and its tests. The thing that catches those is a second implementation of
the same mathematics written by other people, and for this class of problem the
best-tested one in existence is SciPy's.

So `scipy_bdf`, `scipy_radau` and `scipy_lsoda` run the model through
[Pyodide](https://pyodide.org) — CPython compiled to WebAssembly, with real
NumPy and SciPy wheels — and hand it to `scipy.integrate.solve_ivp`. When a
result looks wrong, running it again under SciPy says whether the *model* is
wrong or the *solver* is.

**They are not here to be fast.** They are here to be independent.

#### What it costs

About **22 MB over the wire** on first use (the Python runtime, NumPy and
SciPy), then roughly two and a half seconds to start. The browser caches it, so
the second run in a session starts immediately. Nothing is downloaded unless
one of these solvers is actually chosen — the module that loads Pyodide has no
static import of it, so the rest of the application never sees it.

Speed depends almost entirely on the size of the model, because the fixed cost
is per derivative evaluation rather than per state:

| states | `ndf` | `scipy_bdf` | `scipy_lsoda` |
|---|---|---|---|
| 10 | 5 ms | 18 ms | 4 ms |
| 50 | 4 ms | 8 ms | 3 ms |
| 200 | 10 ms | 17 ms | 5 ms |
| 600 | 18 ms | 17 ms | 8 ms |

On a small model SciPy is a few times slower; by six hundred states it has
caught up, because that is where the analytic Jacobian is handed over as a
sparse matrix and the per-call overhead is spread across a longer vector.

#### How the model gets into Python

The derivative **stays in JavaScript**. `buildSystem` compiles a model's
equations into a JavaScript function, and re-emitting them as Python would mean
a second code generator to keep in step with the first — the surest way to make
the "independent check" agree with the thing it is checking.

Instead Python calls back into the generated function through a pair of buffers
that live in the WebAssembly heap and are seen from both sides with no copying:
NumPy writes the state in, JavaScript writes the derivative back. What SciPy
integrates is therefore *exactly* the function the other solvers integrate, and
a disagreement is a disagreement about integration and nothing else.

Growing the WebAssembly heap replaces its backing store, which detaches every
typed array pointing into it — and a detached one reads as empty rather than
throwing, so a solver that did not check would quietly integrate zeros. It was
observed happening on the smallest of the bundled models, so the buffers are
re-acquired whenever that happens.

The analytic Jacobian goes across too. It is already stored column-compressed
(`colPtr`, `rowIdx`, `values`), which is precisely `scipy.sparse.csc_matrix`'s
own layout, so it crosses with no conversion at all.

#### What they will not do

`solve_ivp` has no callback for accepted steps, which this codebase needs for
the blocks that remember and for progress and cancellation. Rather than
reimplement SciPy's driver — and with it the chance of a bug SciPy does not
have — each solver *class* is subclassed and its `_step_impl` wrapped, so
SciPy's own `solve_ivp` runs its own numerics and this code is merely told when
a step is accepted. Progress, cancellation and the min/max, running-mean and
delay blocks all work as they do under the built-in solvers.

One thing is refused outright rather than quietly ignored:

- **Triggers.** Every trigger is terminal, and they are located by the
  bracketing search in `src/ode/events.js`, including the rule that a crossing at the instant a previous event
  fired is not a new one. SciPy has event support and it works, but reproducing
  *that* rule on top of it would risk a subtly different model rather than an
  independent check of this one. Use `ndf`, `ros23` or `dp45`.

**Non-negativity** is honoured as far as it can be. The usual treatment splits the option in
two: the derivative is wrapped so a state that has gone negative cannot be
carried further down, and an accepted step is projected back onto zero with the
violation folded into the error estimate. The first half lives in the
derivative, so it is applied to the function SciPy calls — which makes the
comparison closer, not looser, since it is then the same ODE the built-in
solvers integrate. The second half belongs to the step controller, which is
SciPy's. Whatever is left over is counted and reported in `stats.negative`,
which is zero on every model tested here.

#### How closely they agree

Against `ndf` on the bundled models, at each model's own tolerances, over
every output whose magnitude is within eight orders of the largest:

| model | `scipy_bdf` | `scipy_radau` | `scipy_lsoda` |
|---|---|---|---|
| `four-compartment.json` | 2.0e-5 | 5.2e-5 | 5.0e-5 |
| `landscape.json` | 6.4e-5 | 5.5e-5 | 3.2e-5 |
| `decay-chain.json` | 6.7e-7 | 1.2e-6 | 1.1e-6 |
| `biosphere.json` | 2.1e-5 | 5.1e-5 | 2.1e-6 |
| `lookup-driver.json` | 1.1e-5 | 6.0e-6 | 9.9e-6 |
| `post-processing.json` | 0 | 0 | 0 |

On the **Robertson problem** at `rtol=1e-10` the two agree to 2.5e-9 while both
conserve mass to 1e-15, and tightening SciPy to `rtol=1e-9` moves its answer to
within 3e-7 of a `rtol=1e-11` reference — textbook convergence, from two
implementations that share no code.

A **running extremum is the one output that will visibly differ**, because
min/max is sampled at accepted steps and no two solvers step alike. Early in a
run, where a peak has only a handful of steps behind it, `scipy_bdf` differs
from `ndf` by 4%: the built-in `ros23` and `dp45` differ from it by 21%
and 23% on the same series. By the end of the run all five agree to 1e-4. This
is the recorder reporting what it saw, not a solver disagreeing about the
model — the compartment underneath it agrees to 2.9e-8.

#### Pinning

`PYODIDE_VERSION` in `src/ode/scipy.js` is an exact version, never `latest`: an
independent check that changed under a model without the model changing would be
worse than no check at all. Bumping it is a deliberate act with a
re-run of the comparison above behind it.

#### Offline

With no network the three SciPy solvers fail on the first run with a message
naming the URL they could not reach and telling you to choose a built-in
solver; nothing else is affected, and the built-in solvers keep working in the
same session. A model *saved* with one of them will open anywhere but will not
run without a network — which is why they are marked ↓ in the solver list, and
why the default is still `ndf`.

### The Jacobian

A stiff solver has to know how each compartment's rate of change responds to
every other compartment — the matrix df/dy — and it needs it repeatedly.
Approximating it costs one evaluation of the whole model per state, which for a
thousand-state model is a thousand evaluations for a single matrix, and
`ros23` needs a fresh one at **every step**.

The model already says what that matrix is, so it is generated from the
equations instead. Three things fall out of the model's own structure:

| | |
|---|---|
| **which entries can be non-zero** | read off the equations, so the matrix is stored and factorised sparsely. A compartment couples only to what it exchanges with and to its own decay chain, so a row holds a handful of entries however large the model is. |
| **the entries themselves** | by differentiating the generated code, so they are exact. No perturbation size to choose, no cancellation, and a step function contributes 0 rather than the 1e8 artefact a difference across its jump invents. |
| **how few passes it takes** | columns that share no row are seeded together, so the whole matrix comes out of a handful of passes — five for `landscape.json`, nine for a thousand-state landscape — rather than one per state. |

If nothing in the model depends on the state or the clock, df/dy is *constant*:
it is then built once for the entire run, which is what the variable-order solver calls
a constant Jacobian.

The footer says which of these happened — `df/dy analytic, sparse` — and the
tooltip gives the details. The **Code** tab shows the generated tangent
function beside the derivative function.

What it is worth, on a chain of compartments with four nuclides, solved to the
same tolerance and the same answer:

| states | `ndf` before | after | `ros23` before | after |
|---|---|---|---|---|
| 160 | 0.6 s | 0.14 s | 85 s | 0.36 s |
| 640 | 32 s | 0.8 s | 2 h 35 min | 7.8 s |
| 1280 | — | 2.0 s | — | 19 s |

A model using a function with no derivative rule — `factorial` of a state, say —
declines the whole thing and falls back to differencing, rather than shipping a
Jacobian that is right in most columns. The tooltip says so, and why, and it
names the block, since one equation in four thousand can be what declines it.

**Nothing that cannot move is differentiated.** A quantity the model shows can
never follow a compartment — a lookup table read at the clock, an expression
built only on parameters — contributes no tangent at all rather than one that
happens to be zero. That keeps the generated function small, and it is what
lets a table read at the clock sit inside a function whose rule refuses a
*moving* table: a staircase in time like
`interpolationUseEndValues(time(), 0, Marine, 6, q*2)`, which is how a
landscape model's water balance is usually written, is differentiated where a
staircase over a compartment is still declined.

An entry that is not a number at one state — `sqrt` or `log` of a compartment
that has reached exactly zero, an infinite slope — declines the matrix for
that evaluation only: the solver differences it there and asks the generated
one again at the next step, in `ros23` and `ndf` alike. Before this the
stiff solvers failed on such a model and blamed it, while `dp45` solved it.
While *cannot go negative* holds a compartment at zero, `ndf` replaces that
compartment's row of the matrix with a row of the identity, for the reason
given under [Keeping a compartment non-negative](#keeping-a-compartment-non-negative).

## Index lists

Every block is indexed by an ordered list of *index lists* — its dimension —
and holds one value per combination. It is what makes a model more than a
handful of boxes: a compartment indexed by `[Radionuclides, Object]` with 4
nuclides and 3 landscape objects is 12 state variables, drawn as one box.

```figure indexing
  [ Soil ]  x  ( Radionuclides )  =  [Soil[I-129]] [Soil[Cs-137]] [Soil[U-238]]
  one block     I-129, Cs-137,       three states, one equation,
  drawn         U-238                one drawn box
```

```json
"index_lists": [
  { "name": "Contaminants", "for_materials": true,
    "indices": ["I-129", "Tc-99", "Ra-226"] },
  { "name": "Radionuclides", "for_nuclides": true, "sub_set_of": "Contaminants",
    "indices": ["I-129", "Tc-99", "Ra-226"] },
  { "name": "Object",
    "indices": [{ "name": "Lake", "enabled": true },
                { "name": "Mire", "enabled": true },
                { "name": "Forest", "enabled": false }] },
  { "name": "Wetland", "sub_set_of": "Object", "indices": ["Lake", "Mire"] }
]
```

Three kinds:

- **root** — an independent list.
- **sub-set** (`sub_set_of`) — a selection from a root list. A block indexed by
  the sub-set can read and write blocks indexed by the root.
- **mapped** (`mapping`) — an explicit index-to-index relation onto another
  list, many of its indices to one of yours:

  ```json
  { "name": "Elements",
    "mapping": { "to": "Contaminants", "pairs": [
      { "from": "Cs", "to": "Cs-137" },
      { "from": "Cs", "to": "Cs-135" },
      { "from": "Sr", "to": "Sr-90" } ] },
    "indices": ["Cs", "Sr"] }
  ```

**Scenarios in a new model** are one button: **+ Scenarios** on the **Index
lists** tab, beside *+ Index list*. It makes a list marked as the scenarios with two to
choose between, picks the first as live, and the choice appears at the top of
**Simulation**. Double-click either index to rename it — everything keyed on
the old name follows, including per-index values, sub-sets, groupings and the
scenario chosen for the run, which is why renaming is not delete-and-add-again.
The button is only there while the model has no scenarios: one list at a time
can be them.

### A transfer does not choose its dimensions

A flux is indexed by **the indices its two ends have in common**, and that is
not a setting. A transfer moves inventory out of one cell and into another, so
it exists exactly where there are two such cells — and Ecolego says the same,
keeping every transfer's dimension in step with both ends and offering no
picker for it.

So there is nothing to tick. A transfer between two compartments on the same
list takes that list; between a compartment on `Contaminants` and one on
`Radionuclides` it takes `Radionuclides`, the indices both of them have; from a
compartment to outside the model it takes that compartment's whole dimension.
Change what either end is indexed by and the flux follows. Its settings say
what it inherited — and when the two ends were on different lists, which two
were intersected — rather than asking you to work it out:

> `Radionuclides` — the indices Waste and Fracture have in common
> (Contaminants ∩ Radionuclides).

The boxes are still there, because **a narrower flux is a real thing to want**
and one this tool can express where Ecolego cannot: a loss that only applies to
the wetland objects is the same dimensions with one of them taken to a sub-set,
and `examples/landscape.json` does exactly that. A narrowing you state is kept;
a dimension that no longer follows from either end is replaced, since that is
what a stale one is.

#### Ends of different dimension, and *sum extra indices*

Two ends that do not correspond — a flux from `[Radionuclides, Object]` into
`[Radionuclides]` — Ecolego refuses outright: the connection cannot be drawn.
The reason is worth knowing, because the shape is not nonsense. There is no
intersection to take, so the flux keeps the **union**, which is the only
dimensions that can reach both ends at all; and reaching the narrower end then
means every index of the extra dimension arriving in its one cell. Into a
target that is a **sum** — three landscape objects discharging into one
downstream compartment. Out of a donor it is the mirror image: the one cell
pays out once per object, three times the flux.

Mass is conserved either way. What is lost is that the model ever said so — a
number that is a total reads exactly like a number that is not.

So this tool allows it and asks first. A flux whose dimensions an end has not
got carries **sum extra indices**, and until that is ticked the model does not
run:

> `T` is indexed by `Obj`, which `Dst` is not: the flux would be added up over
> all 3 of them and delivered into the one `Dst` cell. Give both ends the same
> dimensions, or tick "sum extra indices" on `T` to ask for that total on
> purpose.

The tick is on the transfer's own settings, and appears only where there is
something to add up. Both ways out are real: the message leads with matching
the dimensions because that is the answer nine times in ten — the shape usually
arrives by changing one compartment and forgetting the other — and a deliberate
aggregation only has to be said once. `examples/landscape.json` says it on its
`Discharge`.

The Information view names the end and the dimension, so a flux that sums says
so wherever you meet it:

> **Summed into** `Dst` has no `Obj`, so every `Obj` arrives in the one cell.

Measured across the real projects on this machine, **no flux in any of them has
the shape**: 48,016 fluxes in 134 models, none summing. That is what you would
expect of files written by a program that refuses to draw one.

All three kinds of list are made on the **Index lists** tab. The left pane
lists what the model has — name, size, and what each one is in three words —
and the right pane is the one you are editing.

It opens with *Defined as* — an axis of its own, a sub-set of, or a grouping of
— then the indices themselves as chips: click one to disable it, double-click
to rename it, **×** to remove it. A disabled index stays in the file and keeps
its values but takes no part in a simulation. Past 60 indices the card grows a
filter and shows a windowful at a time, because real lists get large: one assessment model's
`Transfers` list has 1,624, and drawn all at once that is one card twenty
thousand pixels tall.

What comes below depends on what the list is. A **sub-set** gets the indices of
its parent it has not taken, as dashed chips to click (and *Add all*); there is
no free-text box, because a name the parent does not have is accepted and then
fails the build. A **grouping** gets its pairs written the way they are read:
**one cell per index of the parent, saying which of these it belongs to**,
flowing into as many columns as the window is wide. That is the direction a
modeller thinks in — which element is this nuclide — and the only one that is
total; how many are still unassigned is on the card's title, since a
half-written mapping is a model that will not build. The **radionuclide** list
gets its half-lives and its decay chains, described below.

The header also carries **Delete**, which refuses while anything is still
indexed by the list and says what; the line under it names those blocks, so
the answer is on screen before the question is asked.

*these are the model's scenarios* is on the *Defined as* card. One list at a
time can be them, so ticking a second demotes the first, and the live one is
then chosen at the top of **Simulation** — where an *edit* link comes back
here, since that is the one place the two meet.

**Two lists are related whenever they share a root**, however many steps apart
they are. An element list mapped onto the materials is readable from a block
indexed by a *sub-set* of those materials, because both resolve to the same
root and the two translations compose. Reading one way is exact — each nuclide
has one element — and the other way has to pick a representative, since an
element has many isotopes; the first the mapping names is taken. Lists with no
root in common are simply unrelated, and a build that needs to carry a
dimension between them says so rather than guessing.

### The element dimension

Chemistry is a property of the element, not of the isotope: a sorption
coefficient, a concentration ratio and a partition factor are all per element,
while inventory and decay are per nuclide. An element list beside the nuclides
is what carries that, and real models lean on it heavily.

So this tool **derives one**. A model with materials automatically gets an
`Elements` list, one index per element, mapped onto the materials:

```json
"parameters": [
  { "name": "Kd", "index_lists": ["Elements"],
    "entries": [{ "index": { "Elements": "Cs" }, "value": 10 }] }
],
"expressions": [{ "name": "Retardation", "equation": "1 + Kd" }]
```

`Retardation` is per nuclide, `Kd` is per element, and every isotope of caesium
gets the same one. It compiles to a table lookup, not a branch.

The list is **derived, not stored**: its indices and its mapping follow the
materials, so adding one brings its element with it, nothing can fall out of
step, and it is left out of the saved file. It shows in the **Index lists**
panel marked *derived*, and nothing there can edit it — change the materials
and it changes with them.

**Every material has an element**, not only the ones that decay, because a
grouping has to cover what it groups: at a material no element stands for,
anything indexed by `Elements` has no cell to be read — and the build refuses
the model rather than guessing. The element symbol is everything up to the
first digit, which covers every spelling the corpus uses (`Cs-137`, `Nb-93m`,
`C-14 organic`, `C-14-inorg`), so stable C-12 joins C-14 under `C`: one
element, one sorption coefficient, right for both. A name that is not a
nuclide's — `water`, `Rabbit` — is its own element, since there is nothing else
it could belong to.

A model that declares its own `Elements` list — an imported one, or one that
needs organic and inorganic carbon apart — keeps it, and nothing is derived
beside it. That one is kept in step by hand instead: adding a material adds its
element and the pair, and removing the last material of an element removes the
element. A grouping of your own making — `Species`, say — is not guessed at:
a new material is left out of it, and the build tells you which index is
missing from which list if anything reads it.

**Decay and ingrowth act on a compartment only where it has a nuclide
dimension.** There is nothing for −λC to act along otherwise, and the engine
has always skipped such a compartment — so the **Handle decay and ingrowth**
checkbox is offered only where it would do something, and says which list it
acts along. A *sub-set* of the nuclides counts (real models keep a catalogue
and the subset of it that decays, and index compartments by either); a
*grouping* of them does not, since one of its indices stands for several
nuclides at once and there is no single decay constant for that.

### Contaminants and radionuclides

Every model has **two** contaminant dimensions, and both are built in: they
are always there, they keep their names, and neither can be deleted.

| | |
|---|---|
| **`Contaminants`** (`for_contaminants`) | every material the model knows |
| **`Radionuclides`** (`for_nuclides`) | a sub-set of it: the ones that have a half-life |

They are one list of materials looked at two ways, and the **Index lists** tab
divides accordingly. On **Radionuclides** you type a name, browse *ICRP 107*,
and edit the half-lives and the decay chains; a radionuclide added there is a
material, so it appears in **Contaminants** as well. On **Contaminants** you type
anything else — a material that does not decay. That is not a theoretical case:
real assessment models carry stable carbon beside C-14, water, and one carries
a population of rabbits and foxes.

Removing a radionuclide removes the *material*: there is one material, and
taking it out of one list takes it out of both. To keep something in the model
without decay, add it to **Contaminants** instead.

**A compartment may be indexed by either**, and one indexed by `Contaminants`
decays the materials that decay and carries the rest unchanged — a pool of
C-14 and stable carbon in one box, with the right physics on each column.
Disabling an index removes it from the simulation but keeps its data, so
re-enabling restores it; switching one off in either list switches off the
material.

**A material that does not decay carries its own unit** — `kgC`, `m^3`,
`Rabbit` — set on the **Units** card of the Contaminants list. A radionuclide's is
not a separate fact: an inventory of one is an activity or an amount, chosen
once for the whole model under **Inventory unit**, and every nuclide follows
it. A compartment that states no unit is labelled per index from the material
it holds, so one on the catalogue reads `kgC` at the stable carbon and `Bq` at
the C-14 — and the chart says so, since it will not put two units on one axis
without warning. A compartment that *does* state a unit means it at every
index.

A file written before this tool had the two — where one list did both jobs — is
split as it is read. Every block keeps the dimension it was indexed by and the
model computes exactly what it computed.

### The compartment and transfer dimensions

Two more lists come free, and they are made of the model itself: **`Compartments`**
has one index per compartment and **`Transfers`** one per transfer, each named
by the block's qualified name — `Water`, or `NearField.Water` for one inside a
sub-system.

They exist because so much of a model is *per compartment* or *per transfer*: a
sorption coefficient, a depth, a volume, a rate coefficient. Without them that
is written as one parameter per compartment — forty blocks whose only
difference is which compartment they belong to — or as a column somebody keeps
in step with the model by hand.

```json
"parameters": [
  { "name": "k", "index_lists": ["Transfers"], "value": 0,
    "entries": [{ "index": { "Transfers": "A_B" }, "value": 0.1 },
                { "index": { "Transfers": "B_C" }, "value": 0.25 }] },
  { "name": "Kd", "index_lists": ["Compartments"], "value": 1,
    "entries": [{ "index": { "Compartments": "A" }, "value": 2 }] }
],
"transfers": [
  { "name": "A_B", "from": "A", "to": "B", "rate": "k / Kd[_source_]" }
]
```

**The block being evaluated supplies the index.** A transfer *is* one of the
transfers, so `k` written in the rate of `A_B` means `k[A_B]`, with nothing to
say. A compartment is one of the compartments, so a parameter indexed by
`Compartments` written in its initial condition means that compartment's value.
That is the whole point: one equation, written once, that means something
different in each block because each block is somewhere different.

**A list made from either is answered for the same way.** A sub-set of
`Transfers` — the advective ones, say — or of `Compartments` — the barriers —
and a list *mapped onto* `Compartments` — the media the compartments are made
of — all inherit it: a per-advective-transfer flow written in an advective
transfer's rate is that transfer's, and a per-medium porosity written in a
compartment's initial condition, or as `porosity[_source_]` in its outflow, is
the porosity of that compartment's medium. That is how a vault model of that
kind writes its flows, one value per advective transfer, and it is how a file of
that shape is read (index-name resolution looks the block's own index up in a
sub-set by name and through a mapping by its element). A block *outside* the
list is the one thing that cannot be answered for, and the error says so and
names the list.

### What an initial condition may read

Anything whose value **cannot change over the run**. It is worked out before
any compartment has a value, so that is the only honest limit — and within it,
an initial inventory can be written the way it is actually derived:

```json
"parameters": [
  { "name": "Conc",   "value": 3 },
  { "name": "Volume", "value": 4 }
],
"expressions": [{ "name": "Amount", "equation": "Conc * Volume" }],
"compartments": [{ "name": "Pool", "initial": "Amount" }]
```

`Amount` is an expression, and an indexed one lands per index: an inventory per
nuclide per object, written once and read in the compartment that holds it.
Chains are followed — an expression built on an expression built on parameters
is still constant — and only the ones an initial condition actually reads are
worked out, before anything else runs.

What it cannot read is what has no value yet, or a different one at every
moment, and the error says which:

| | |
|---|---|
| a **compartment** | it *is* the state being initialised |
| a **lookup table** | read from a table at the clock |
| a **far-field pathway** | its release comes out of the state |
| a **min/max, running mean, snapshot, delay** | all functions of history |
| anything reading `time` | including at one remove |

`start_time` and `end_time` are constants of the run, so they are fine; only
`time` moves.

**A transfer reaches its two ends by name.** A value per *compartment* used in a
transfer is ambiguous — the transfer touches two of them — so it is pinned:

| Written | Means |
|---|---|
| `Kd[_source_]` | the compartment the transfer flows **out of** |
| `Kd[_target_]` | the compartment it flows **into** |

Both are offered while you type, in a transfer's equations and nowhere else.
Anywhere they cannot mean anything — in an expression, or on a transfer with
that end open — they are refused with a message that says why.

Where nothing can supply the index, the model is refused rather than guessed
at, and the message names the fix:

```
A_B: 'Kd' has a value per compartment, and 'A_B' does not say which.
     Write 'Kd[_source_]' for the compartment it flows out of, or
     'Kd[_target_]' for the one it flows into.
```

**Only some blocks can be indexed by them:** an expression, a parameter, a
lookup table, an aggregate or an index operation — the blocks that hold a value
for others to read. A compartment *is* one of the compartments already, which
is exactly what lets a per-compartment value be read inside one with no index;
being indexed by them as well would mean one state per pair of compartments,
and a transfer indexed by the transfers is the same nonsense one step along.
The dimension picker shows them greyed for the blocks that cannot carry them,
with the reason on them, and the engine refuses a file that says otherwise.

Like the element dimension these are **derived, not stored**: the model already
says what its compartments are, so writing them down again would only create
something that could fall out of step. Rename a compartment and its column
follows — in the values *and* in an index written into an equation by hand;
delete one and its column goes with it. A value keyed by an index that another
list also holds is left alone on a rename, because a bracket says which *index*
is meant and not which list, and an ambiguity is not something a rename should
settle on its own.

**These two lists are this tool's, not Ecolego's.** Ecolego has no such
dimension: a model that uses one is a model this tool can run and Ecolego
cannot read back. See INTERNALS.md.

### One dimension twice

A block cannot be indexed by two lists that are **the same dimension**: a list
and a sub-set of it (`Contaminants` and `Radionuclides`), a list and a grouping of
it (`Radionuclides` and `Elements`), or two sub-sets of one list. Any of those
would index the block by one dimension twice, with nothing in an equation to
say which cell of which is meant. Tick one and the others in its family grey
out, with the reason on them; a file that carries such a pair is refused with
the same words. Choose the longer list or the shorter — one value per material,
or one per radionuclide — not both.

This is the rule a project file states: no block may carry two index lists that
come from the same root — two sub-sets of the contaminant catalogue, say. An
earlier version of this tool allowed a list beside a sub-set of it, in the
belief that real models did that; a scan of the 87 readable projects on this
machine found none that does, and this tool now applies the rule. The same rule
keeps a block from being indexed by the compartments *and* the transfers at
once — a value per compartment per transfer is not a quantity anything here has
a meaning for.

**Only the lists a block can carry are offered.** A compartment is one of the
compartments and a transfer one of the transfers, so those two lists — the ones
made of the model's own blocks — are not dimensions such a block can have, and
they are not shown in its *Indexed by* box rather than shown greyed. What is
greyed is what could be ticked but not now: a list in the same family as one
already ticked.

### Pinning an index in an equation

An equation normally reads an indexed block *at its own position*: inside a
block indexed by `[Radionuclides, Object]`, the name `Soil` means this nuclide in
this object. Square brackets pin one dimension to a particular index instead,
one bracket per dimension:

```
Soil[Cs-137]                  this nuclide fixed, the object still follows
M[_Ra-226][Pb-210]            both dimensions fixed — a cell of a matrix
M[][Pb-210]                   the column fixed, the row follows
```

**The brackets are read by name, not by position.** Each one is matched against
whichever of the target's index lists actually contains it, which is what
the format does, and not a convenience: of the 506
two-bracket references in the `.eco` files tested here, **200 are written in an
order that a positional reading would resolve to the wrong cell**, including
this one, whose block is declared `Ecosystem × Objects`:

```
Ecosystem_area_objects[11][Lake]
```

An empty bracket pins nothing, and fewer brackets than dimensions is fine — the
rest follow the equation's own position. One index may pin two dimensions, so
`M[Cs-137]` on a list and a copy of it is the diagonal. What is refused is
anything genuinely ambiguous or impossible: more brackets than the block has
dimensions, two brackets that want the same dimension, an index that belongs to
none of them, and — separately, because the fix is different — an index that
exists but is disabled.

An index name is raw text up to the closing bracket, as in
index parsing, not an identifier: real models use `_Ra-226`, `01`,
`F.18:00_51_FORSMARK` and `B.04:00_205_BARSEBÄCK`.

### Radionuclides, half-lives and decay chains

The radionuclide dimension is **built in**. Decay and ingrowth act along one
index list, and in this domain that list is not an optional extra, so it is
always the first entry on the **Index lists** tab: it cannot be deleted and it
keeps its name. What decays and how fast is on the same page, under its
indices.

**A compartment holds an activity or an amount, and you say which.**
`decay_unit` is `Bq` or `mol` for the whole model — *Inventory unit*, on the
same page as the half-lives, which is where a project file keeps it too — as a
unit on every nuclide rather than one on the model, which is how
an .eco file carries the choice). `Bq` when a file does not say, which is
Ecolego's default and what every nuclide in the corpus is in.

The one number it changes is the ingrowth coefficient, and it is the whole of
the difference between the two quantities:

| | ingrowth into a daughter |
|---|---|
| `Bq` | `lambda_daughter * A_parent * ratio` |
| `mol` | `lambda_parent * n_parent * ratio` |

Self-decay is `-lambda_daughter` either way. Both are exact for their own
quantity rather than one being an approximation of the other — they are the same
physics written in `A = lambda*n`, and multiplying the amount equation through
by `lambda_daughter` turns it into the activity one. A test runs the same chain
both ways from matched initial conditions and checks that identity at every
output point.

What must not happen is the two disagreeing: the coefficients differ by
`T½(parent) / T½(daughter)`, which for U-238 into U-234 is a factor of 18,200.
So changing the setting relabels the compartments that carried the other unit,
and says which ones it left alone. Nothing is *converted* — the numbers in the
model are read as being in whatever unit is chosen, as in Ecolego — and
`bq2mole(bq, half_life_years)` and `mole2bq(mole, half_life_years)` are there
for an equation that has to cross over.

Add nuclides to it like any other index list, then tick that list under
**Indexed by** on the blocks that should be per-nuclide — or take them from the
published database, which is the next section.

**An empty radionuclide list is not a dimension.** A model with no nuclides in
it is a plain compartment model: blocks get no nuclide dimension by default,
and nothing is indexed by a list with nothing in it. Add the first nuclide and
new blocks pick the dimension up.

A file that flags a differently named list — an imported `.eco` may — keeps
that list as the radionuclide one, name and all. Renaming index lists inside
someone's model is not something loading a file should do.

**The field completes as you type**, over the database rather than over the
model: `cs` offers the caesiums, `137` everything with that mass number,
`caesium` the element by name, and `cs137` or `cs-137` go straight to it. Each
row carries the half-life and what the nuclide decays into, because choosing
between Cs-134 and Cs-137 is not a choice the name alone settles. Ctrl-Space
lists all 1,252 of them. It is the same popup, the same keys and the same
behaviour as an equation field — Tab or Enter takes the highlighted one, and
the next Enter adds it — because typing `Cs-137` into a nuclide list is the
same act as typing `Kd_ter` into an equation. Stable nuclides are not offered:
a compartment model does not integrate something that does not decay.

A name the database has never heard of is still accepted and starts
**stable** — a model may carry a tracer that is not a nuclide at all — and you
are told that is what happened, because the one thing that must not be done for
you is to assume a decay rate.

Creating a list never changes what existing blocks are indexed by — they stay
as they were until you tick them. Blocks you add *afterwards* do pick the
radionuclide dimension up, since that is nearly always what a nuclide model
wants; parameters are the exception and default to a single value. Everything
is one tick either way.

### Half-lives, and the decay constant beside them

The radionuclide list carries a table of half-lives — from ICRP 107 unless this
model says otherwise, with `stable` for anything that does not decay, and the
source of each value named in its own column.

**Either column can be typed into.** The half-life is in years, because that is
what the file stores and what ICRP 107 is a table of. The decay constant beside
it is in the model's own time unit, because that is the number that actually
appears in the model — it is what the solver multiplies an inventory by, and
what a report, a review note or another code's input file quotes. Setting one
sets the other, and the table shows the result immediately, so the two are one
value seen two ways rather than two values that can fall out of step.

- `0` in the decay-constant column means **stable** — the same statement as a
  half-life of forever.
- An empty field in *either* column clears the override and falls back to
  ICRP 107.
- A negative decay constant is refused: that would be a nuclide growing rather
  than decaying.
- Changing the model's time unit re-labels the column and re-states every value
  in it. The stored half-lives do not move.

The conversion is exact in both directions to the last bit a double will carry,
in every time unit — a half-life typed as a decay constant comes back as the
half-life it was.

### Choosing nuclides from ICRP 107

**Browse ICRP 107…**, beside the box that adds an index by hand, opens the
1,252 radionuclides of ICRP Publication 107 — every half-life, and every decay
pair with its branching ratio. `src/domain/icrp107.js` is that database,
extracted from the decay-chain page at
[kvotab.se/rdc.html](https://kvotab.se/rdc.html), which publishes the ICRP 107
tables, and it is the only radionuclide data in this tool. It replaced what
`src/domain/nuclides.js` used to hold: fifty half-lives and twenty-four decay
pairs typed by hand, whose own note said the table was not Ecolego's database
and that "any assessment work should import the real one". That table now
lives in the test suite instead, where an independent hand-typed source is
worth having — it is what the computed chains are checked against.

The dialog is arranged the way that page is — elements down the left, their
radioisotopes beside them, each with the half-life as ICRP writes it (`3.1 m`,
`0.1643 ms`, `4.468 By`) and its decay modes — because by element is how anyone
who knows the nuclide they want navigates twelve hundred of them. A search box
takes a name, an element symbol or an element's name in words.

**The interesting half is underneath.** Tick U-238 and the band below says what
the model would actually contain — U-238, U-234, Th-230, Ra-226, Pb-210 — and
what it collapsed to get there: fifteen members that live for days or minutes
and are assumed to sit in secular equilibrium with their parents. Change *Model
explicitly above* from a year to a month and Po-210 appears. That is the
modelling decision being made, made where it can be seen rather than in a table
typed afterwards.

Why it needs computing rather than typing. Leaving Pa-234m out means U-238's
daughter is U-234, and the branching that reaches it is the product of the
ratios along the way — 0.9984 through Pa-234m, not 1 — while the other 0.0016
ends up somewhere else. The rule is one sentence: *the effective branching from
A to B is the total probability that a decay of A reaches B through nuclides
that are not being modelled*, and `collapse` in `src/domain/decaydb.js` is that
sentence memoised over the database's decay graph. A test computes the collapse
at a one-year threshold and checks it against the chains that were typed by
hand — all twenty-two agree, and it finds three the hand table missed: the small
α branch of Pu-241 straight to Np-237, and the fission losses on Cm-246 and
Pu-241 that made their branching 0.9997 rather than 1.

**The chain has an upper bound as well as a lower one.** *Treat as stable above*
stops the walk at a daughter longer-lived than the figure — never, by default;
100 My, 10 Gy or 1 Ty on offer. U-236 decays to Th-232, at fourteen billion
years, and on into the thorium series; walked to its stable end that is four
members and a pair `U-236 → Ra-228` that hands U-236's activity *through*
Th-232 at U-236's own rate — a thing that does not happen within any
assessment. With the ceiling at 10 Gy, Th-232 is a **sink**: the chain is U-236
alone, the band says *1 stopped at: Th-232 (14.05 Gy)*, and the setting is saved
with the model as `simulation.decay_ceiling` (in years) so the run collapses
its decay pairs the same way the panel showed them.

Each pair in the band now says what it passes through, in parentheses after
the daughter — `→ U-234 (Th-234, Pa-234m)`, `→ Pb-210 (Rn-222, Po-218, Pb-214,
Bi-214, Po-214)` — so a pair the model asked for wears its assumption where it
is read. *Hide shorter-lived* leaves the nuclides below the threshold out of the
lists, since they would be collapsed into their parents anyway; anything ticked
or in the chain stays.

Each chain member can be dropped from the band itself — truncating a chain is a
real modelling choice, not a mistake — and clicking a member's name shows that
element's isotopes. **Add** writes the nuclides into the radionuclide list with
ICRP 107's half-lives *as explicit values in the project file*, so a chain
worked out from a published database carries that database's numbers where they
can be read and cited, and replaces every decay pair out of those nuclides with
the computed ones. Pairs out of nuclides the selection said nothing about are
left alone.

The half-lives are not always the ones in `nuclides.js`: 44 of that table's 50
agree with ICRP 107 to within half a percent, and six differ because the
evaluated data moved after 2008 — Se-79 by 10% (re-measured in 2010), Th-229 by
7%, Ag-108m by 5%, Ca-41, Ni-63 and Cm-245 by less. A test names those six, so
that a *new* disagreement is a failure rather than a shrug.

**Transfers follow their endpoints.** A connection is indexed by the union of
the compartments it joins, maintained for you: it has to be, or it could not
say which cell of a per-nuclide compartment it moves. So making a compartment
per-nuclide also indexes the transfers attached to it, and you are told when
that happens.

A per-nuclide compartment draining into a scalar one is fine and means what it
looks like: the scalar compartment receives the **sum over nuclides**.

Selecting the radionuclide list then also gives you the two things behind
decay:

**Half-lives**, in years, with the resulting decay constant beside each. These
are *overrides* on ICRP 107, so a nuclide with no entry still decays at the
published rate — the Source column says `ICRP 107` or `this model`, and **×**
drops an override. Type `stable` for a nuclide that does not decay; that is
also what a name the database does not know starts as. A nuclide with no
half-life anywhere is flagged, and the model will not run until it has one,
which only a hand-written file can now manage.

Stable is stored as the word `"stable"` rather than as a number, because JSON
has no `Infinity`: `JSON.stringify` turns it into `null`, which reads back as
"no half-life at all". A stable nuclide used to survive only until the file was
saved.

**Decay chains**, as parent → daughter with a branching ratio. Ingrowth is
applied only where both members are in the model and enabled, which the Applies
column shows.

Beside the table, **the chains drawn**: a box per nuclide with its half-life in
the unit that suits it, a solid arrow carrying the decay mode (`α`, `β−`) where
ICRP 107 states that pair itself, and a dashed one saying `via 5` where the pair
only exists because the model leaves the members between out. Separate series
pack side by side; a fork is labelled with its branching and puts the main line
down the left; a pair whose ends are more than one layer apart is routed round
the boxes between them; a nuclide in no chain at all gets a captioned row of its
own rather than being left out. A disabled index goes pale, matching its Applies
row. The drawing is laid out to the width the column actually has and redrawn
when that changes, and wraps under the table when there is no room for both.

**A model does not normally have any chains in it.** They are worked out from
ICRP 107 for exactly the nuclides it carries, so a list of `U-238, U-234,
Th-230, Ra-226, Pb-210` produces the four pairs between them with no `chains`
key at all — and the branching on each is the total probability of reaching
that nuclide *through the eleven short-lived members left out*, not the 1 a
hand-typed table would say. Add or remove a nuclide and the pairs follow. Keep
only `U-238` and `Pb-210` and you get the single pair between them, at the same
total probability: that is the same rule applied to a shorter list, not a
special case.

Which makes editing one a real decision. `half_lives` *adds to* the database,
but `chains` *replaces* the computed set — so the first chain edit writes the
whole set into the file, and from that moment the model's chains stop following
its nuclide list. The panel says which of the two states it is in, and the
editor materialises the computed set on that first edit so nothing is lost.

### Editing values per index

Select an indexed block and the inspector shows two things:

- the block-level value, labelled **(default)** — it applies wherever nothing
  overrides it;
- **Values per index**, a row per index combination.

A row you have set is highlighted and its **×** is active; the rest show the
inherited default in grey. Type into any row to set that combination; press **×**
to clear it back to the default. The header counts both (`12 combinations, 3 set`).

**A row is more than one value.** A compartment's carries its **dy/dt** term,
its **absolute tolerance** and its **floor** — `cannot go negative` — beside
the inventory. The term is an equation like the inventory, checked and
completed as one, and the one box in the grid that may name the compartment it
belongs to; the other two are applied per *state*, and one nuclide of one
compartment is one state. The floor is a three-way picker rather than a box: blank follows the
compartment's own setting and says which way that is, and the two other options
set it here. A daughter that dips below zero while its parent is being
integrated hard is exactly the cell to let go of while the rest of the model
keeps the floor — pinning it hides what the model is doing, and pinning the
whole compartment hides more than that. A far-field pathway's row carries its
chemistry, and its geometry too once it is indexed by something other than the
nuclides; see *Far-field pathways*.

Above 240 combinations the grid would be unreadable, so the inspector instead
lists only what is set, plus a dimension picker to reach any one cell.

In the project file, the same thing looks like this:

```json
{ "name": "Kd", "index_lists": ["Radionuclides"], "value": 0.01,
  "entries": [ { "index": { "Radionuclides": "I-129" }, "value": 0.001 } ] }
```

```json
{ "name": "Soil", "index_lists": ["Radionuclides"], "initial": "0",
  "entries": [ { "index": { "Radionuclides": "I-129" },
                 "initial": "1e12", "abstol": 1e-6, "non_negative": false } ] }
```

The block-level value is the default; entries override it, and the entry
naming the most index components wins — so an entry keyed by `Radionuclides` alone
covers that nuclide in every object, while one keyed by both wins over it. Referencing a block of *different*
dimension carries the shared components across and drops the rest; where that
is ambiguous you get an error naming the list, not a guess. `C[Cs-137]` pins
one dimension explicitly.

**The three built-in lists are `Contaminants`, `Radionuclides` and
`Elements`.** `Contaminants` is the catalogue — everything the model transports;
`Radionuclides` is a sub-set of it, and `Elements` a mapping onto it. *Contaminant*
is what a modeller expects the transported things to be called, and it is not
*Species*, which is no use in a biosphere model: real projects already have a
list called `Species` for biota. A model whose contaminants are not radioactive
— stable carbon, water, a Lotka-Volterra rabbit — works exactly the same; read
the list as "what is being transported".

An `.eco` import, whose catalogue is spelled `Materials`, is renamed as it is
read — the list, the lists defined from it, the
dimensions each block declares and the keys of the values they hold per index,
all together, so the file means exactly what it meant. A list of your own that
happens to be called `Nuclide` is left alone, and so is either of them in a
model that already has a list under the new name.

The older `nuclides: ["Cs-137", ...]` shorthand still works — it is sugar for a
`Radionuclides` list flagged `for_nuclides`, and the `Contaminants` catalogue it is
a sub-set of, which blocks pick up unless they set `"per_nuclide": false`. So do the per-nuclide value maps —
`"values_by_nuclide": { "I-129": 1e-5 }` on a parameter, an object `initial` on a
compartment — and `default` as an older name for a block's value.
`examples/biosphere.json` is written that way. All of them are folded into
`entries` when the file is opened, so the editor and the engine read one
representation; the saved file comes back in the current form.

## Importing Ecolego projects

**Open…** accepts four things, and so does **dropping a file anywhere on the
page**:

- `.json` — this tool's own format
- `.eco` — an Ecolego project archive (a ZIP of the project folder)
- `.eas` — an Ecolego **assessment**: the same archive with a run stored in it
- `.xml` — a bare `model.xml`, if you have unzipped the folder yourself

An assessment file reads exactly like a project, because it *is* one: the same
`model.xml`, `views.xml` and `simulation.xml`, plus a `simulation/` folder of
`.dta` result files and whatever raw data a lookup table was linked to. The
model comes across; the stored results do not, since the point of this tool is
to get that answer here rather than to read it.

Anything else is named rather than guessed at: reading an unknown file as JSON
gives a parse error that says nothing about what went wrong.

A file past 200 MB asks before it is read: the largest real project here is
11 MB, and one twenty times that will take a while and may run the tab out of
memory. The archive is read lazily — only the XML files the importer looks at
are decompressed, so a damaged result file in an assessment's `simulation/`
folder no longer fails the import of the model beside it — and the reader
stops at 256 MB of decompressed output for the whole archive, not per entry.

A compartment's `<differential-equation>` — Ecolego's dy/dt column — comes
across as its `dydt` term, at the block level and per index; see *An explicit
dy/dt term*. It used to be dropped with a warning.

**An imported model arrives knowing what it is.** It used to arrive with an
empty description and a name of `model`, and a safety assessment of fifteen
thousand blocks is not something anybody reconstructs by browsing it. Two
different sorts of fact go into the description now, and neither survives the
import otherwise:

```
Imported from Vault_assessment.eas, written by Ecolego 6.5, by a.modeller, created Tue May 25 17:41:51 UTC 2021.
Holds 108 compartments, 103 expressions, 67 parameters, 19 lookup tables, 3 index operations and 565 transfers, in 81 sub-systems; 5724 states to integrate.
Indexed by Contaminants (53), Media (10), Species (35), SRFGroup (6), FlowPaths (353), Parts (91) and 12 more.
Runs 2000 to 102000 years with ndf.
```

The first line is the half that cannot be worked out again later — the file,
the Ecolego that wrote it, the author and the date, all read out of the
archive. The rest *is* derivable, which is exactly why it is worth writing
down: it is the reading somebody would otherwise do by hand before they could
say anything at all about the file. The counts are taken after the import has
finished renaming blocks, flattening groups and connecting interfaces, so they
describe the model rather than the file; the dimensions are the ones blocks
actually carry, most used first, because a real project declares one index list
per collection it has and naming all sixteen says less than naming six.

Ecolego writes `Created at <date>` into the comment field by default, so that
one is read as the date it is rather than repeated as a remark; a comment
somebody actually wrote leads the description instead. **The name comes from
the file**, because every project in the corpus calls itself `model` — that is
Ecolego's default, and an exported result file that called a whole assessment
`model` was the visible half of it.

The description is plain text — the sidebar edits it in a textarea — and the
HDF5 export turns it into markup on the way out, where the result browser
renders it. See [Saving the results](#saving-the-results).

Names come out of the file tidied, and the import report says what changed. A
block or index list with no name is called by its id. A block named after a
function — `min`, `if` — is numbered `min_1`, since the model could not be
loaded with it. A name with an operator in it, `A-B`, is written `A_B` in every
equation and flagged separately, because the same characters spell `A - B` and
the rewrite is textual; a nuclide, material or index called `__proto__` is
refused outright, since those names cannot be tidied without changing what
they mean.

An imported model keeps its **scenarios**: the index list Ecolego marks as its
scenario dimension arrives as this model's, so one index of it is live at a
time and every block indexed by it is read at that one. Three ways a file says
which list that is — the marker in upper case, the marker in title case, and,
in the oldest files, nothing at all but the name `Scenarios` — and all three are
read. The same three settle the `Elements` dimension.

**Sub-system inputs and outputs are joined up rather than kept.** Ecolego
routes a value across a sub-system boundary through a *model output* block, a
*model input* block and a connector between them — a device for lifting a
ready-made sub-system out of a library and wiring it into a project. There is
no such library here, so the blocks are not kept; but what they *connected* is
carried across, because an unconnected input is a placeholder and every one in
the corpus reads `0.0`. So the block that was fed simply reads the block that
fed it, across the boundary, and several feeding one are added — or combined
with whatever operation the input named. Dropping that wiring would not break a
model; it would leave one that runs and reports zero, which is worse. An input
connected to nothing is left exactly as it is, which is what the file says.

An import always shows a report: what came across, what was renamed (Ecolego
names may contain spaces, which this tool's identifiers cannot), and above all
**what was skipped**. This tool implements five block types out of roughly
thirty, so a real project will lose blocks. The report says which, because an
import that quietly dropped them would look like a working model that gives
the wrong answer.

The importer has been run against every Ecolego file on this machine — 211 of
them, 162 `.eco` projects and 49 `.eas` assessments. **136 import**; the other
75 are the older Ecolego 4/5 `<sheet>` format and are refused with an
explanation. Of the 136, **59 build and run** as they stand. See
[INTERNALS.md](INTERNALS.md) for the full breakdown of what stops the rest.

## Copying blocks between two windows

Copy in one tab, paste in another. The two can have different models open, and
neither has to know about the other: a copy is shared with every tab of this
site, and the tab you paste into says where it came from — *Paste Geosphere ·
Into the top level, from Repository to well, copied in another tab*. An open tab
is told the moment a copy is taken somewhere else, so a Paste that has just
become possible does not have to be guessed at.

**The last thing copied anywhere is the thing that pastes**, which is what a
clipboard means. Copy in the left window, then in the right, and the right
window's copy is what both of them paste.

Everything about it is the ordinary paste: a name already in use gets a number,
the connections between copied blocks come along, an index list the receiving
model has never heard of is dropped with the values under it, and the whole
thing is one undo. Bringing *most* of another model across is
[Import…](#importing-blocks-from-another-model) instead, which asks about the
dimensions rather than dropping them.

Two limits worth knowing. It is the same browser and the same site — two tabs,
not two machines, and not a different browser. And a very large copy (a
sub-system of a landscape model, say) is kept in the tab that took it but not
shared, because the space a browser gives a site is a few megabytes and the
model's own recovery draft has first call on it; the message after the copy says
so when it happens.

## Importing blocks from another model

**Open…** replaces the model. **Import…** — beside it, and on the diagram's
right-click menu next to **Paste** — brings blocks *out of* another file *into*
the one that is open, which stays open. It accepts the same four kinds of file,
so the thing you are taking a near-field from can be an `.eco` archive.

The dialog is two panes. On the left, the file: its sub-systems as a tree, a
search box, a chip per kind of block, and a checkbox on every row. On the right,
**what taking it would mean**, which is the half that matters and the reason
this is a dialog rather than a file picker. Ticking a block in a 3,000-block
model is easy; knowing what it drags with it is not.

**Taking a hundred of them is four clicks, not a hundred.** Anywhere on a row
is its checkbox, and:

- **Shift-click** takes everything between the last row you clicked and this
  one — the run you can see on the screen, in the order it is drawn, either way
  round. Shift-click while *un*ticking and the run goes back the same way.
- **A kind chip, or the search box, narrows the tree — and then `All` means
  those.** Click `parameter 64` and the button reads **All 64**; one click takes
  every parameter in the file and nothing else. `None` follows the same rule.
- **A sub-system's own tick** takes it whole — it arrives as a sub-system, with
  everything in it at every depth. While the tree is filtered it cannot honestly
  mean that, so it takes what is *shown* under it instead, and the count beside
  it changes to match.
- A block that is already coming inside a sub-system you took whole is shown
  ticked and inert: nothing can take it back out from under the sub-system
  carrying it.

**What comes along without being asked for.** Two things, marked in the tree as
they become relevant so you can see them arrive:

- **what the chosen blocks read** — an expression is half a block without the
  parameter its equation names, and that parameter may name another. The whole
  chain is followed, through every equation a block holds: a compartment whose
  initial inventory is `Conc * Volume` brings both, and one that calls a
  function brings the function and whatever its body reads. (`Bring what they
  need`, on by default; turn it off and the equations arrive reading names this
  model may not have.)
- **the connections between them** — a transfer is the arrow between two
  compartments, so it comes when both of them do, and stays behind when only
  one does. One that has to stay behind is said so, by name.

**And what has to be decided: the dimensions.** This is where a clipboard
cannot help you. A copy carries no index lists of its own, so pasting a
per-nuclide block into a model with no nuclide list drops the dimension and
every value under it. Here each index list the incoming blocks are written in
terms of gets a row, and the row is a choice:

| the list | what you are offered |
|---|---|
| **not in this model** | **Add it** (the default — with its indices, and the list it is a sub-set of, and the list that one is a sub-set of) · Use one of this model's instead · Drop the dimension |
| **here already** | **Use it** (the default) · Use a different one · Drop the dimension |
| **here but narrower** | the same, plus **Add the 3 indices to Radionuclides** — off by default |
| **worked out from the model** (`Compartments`, `Transfers`, `Elements`) | nothing to decide: the blocks will be indexed by this model's own |

Two defaults, and both are conservative about the model you are importing
*into*. A dimension it does not have is **added**, because dropping one
collapses the block's whole grid onto a single value. A dimension it does have
is **used as it stands**, because widening one is not a change to the blocks
arriving — it is a change to every block already indexed by it, and to the size
of the state vector. The row says exactly what that costs (*Ra-226 — not in
Radionuclides, so 11 values will be dropped*) and the tick beside it is how you buy
them back. Nothing is guessed at silently in either direction.

The same select handles the case that has no other answer: **the same dimension
under a different name**. Point a file's `Nuclide` at this model's `Radionuclides` and
every incoming block, every per-index value and every list defined from it
follows — it is the editor's own rename, run on a scratch copy of the file.

The rest of the right-hand pane is what you would otherwise find out afterwards:
the names that are already taken and what they will become (`Water` → `Water1`,
the same numbering a paste uses), the radionuclides being added and any whose
half-life the two models disagree about, and — when this model writes its own
decay chains — that a nuclide arriving has no ingrowth until you say what it
decays into.

**And, last, whether it would build.** Everything above is a reason the answer
might be no, so the answer itself is worth having before you commit: once the
clicking stops, the import is carried out on a *copy* and that copy is built.
*The model still builds*, or the builder's own complaint about it —
`PartsVolume is indexed by Parts, which does not cover every index of
Compartments`. It is asked by doing it rather than by a rule written to predict
it, because a rule would be a second implementation of the builder's dimension
algebra and it would be the wrong one. On the models this is for it costs about
85 ms; on one where it costs more than a second it stops asking and says so.

That check is what makes the hard case honest. A model like one small vault model
holds index lists made of its *own blocks* — `AdvectiveTransfers` is a sub-set
of the transfer dimension, `Parts` is a mapping onto the compartment one — and
those cannot mean the same thing in a model with different blocks. What can be
done automatically is done: such a list arrives holding only the blocks that
arrived with it, under the names they arrived under, and one left holding
nothing is not added at all. What cannot is *said*: *Parts names blocks rather
than indices, and will not name the 4 already in this model*. Which of your
compartments belong in `Parts` is a modelling decision, so it is left to you —
on the Index lists tab, or by dropping that dimension in the same row.

**Into** chooses where they land: wherever they were (their own sub-systems,
made here if this model has none of that name), the top level, or any
sub-system. They always land on a clear part of the canvas.

Nothing is written until **Import**, and then all of it is written at once — so
the whole import, blocks and index lists and nuclides together, is a single
**Cmd+Z**. Afterwards the strip under the tabs says what was actually done,
including anything that could not be kept.

## Sub-systems

A real model is not a flat list of two hundred boxes. It is organised into
**sub-systems**, which nest, and which scope the names inside them: two
compartments called `Water` in different sub-systems are different
compartments, and an equation inside one of them that says `Water` means its
own.

```json
{
  "systems": ["NearField", "NearField.Bentonite"],
  "compartments": [
    { "name": "Waste", "system": "NearField", "initial": "1e6" },
    { "name": "Pore",  "system": "NearField.Bentonite", "initial": "0" }
  ],
  "transfers": [
    { "name": "Leach", "system": "NearField",
      "from": "NearField.Waste", "to": "NearField.Bentonite.Pore", "rate": "k" }
  ]
}
```

A block keeps its own `name` and gains a `system` — the dotted path of the
sub-system holding it. Its **qualified name**, `NearField.Bentonite.Pore`, is
what everything else addresses it by. A model with no `system` anywhere is
exactly the model it always was.

**How a name is read.** A bare name is looked for in the block's own
sub-system, and failing that at the top level. A name with a dot in it is a
full path from the top. There is nothing in between: to reach a block in a
*neighbouring* sub-system, write the whole path. That is not a simplification
— it is the rule an imported file's own references are written by, so a model
round-trips unchanged. Names have to be unique only within a sub-system.

**One namespace for blocks and sub-systems.** A sub-system and a block in the
same place cannot share a name: `Geo` the sub-system and `Geo` the parameter
would both be written `Geo`, and the tree, the diagram and the Delete command
would have to guess which was meant — deleting the block used to empty the
sub-system instead. The editor refuses it in either direction; the one
exception is naming a new sub-system after the block that is about to move into
it, which is how *Move into new sub-system* names it. A file that carries the
clash is refused when it is opened, and the message names it.

**A rename or a move that cannot be spelled is refused.** From inside `A`, a
block at the top level called `Lake` is out of reach while `A` has a `Lake` of
its own: the bare name means the nearer one, and there is no longer form to
fall back on. So renaming the top-level `Water` to `Lake` while something in
`A` reads it, or moving a block in beside a same-named one it reads, used to
rewrite the reference to a name that quietly meant a different block, and the
model ran on with a different number in it. The edit now stops before anything
has changed and says which block, which reference, and what to rename first.

**Where a connection lives.** With its donor. `Sub.C1 → C2` is a transfer
*out of* `Sub`, so it belongs to `Sub` and its rate is read from inside `Sub` —
which is the rule every real model here keeps, in all 4,648 of their transfers.
It is an invariant rather than a default: a compartment that moves takes its
outgoing transfers and its source terms with it (the status line says how many
went along), and re-attaching a transfer's donor end moves the transfer to
where it now starts. The inspector shows a connection's sub-system but does not
offer to change it — that choice belongs to the compartment it flows out of.

**Selecting brings the diagram with it.** Picking a block anywhere else — a row
in the tree, a search result, a reference followed in the Information view, a
cell in the Matrix — shows that block's sub-system on the canvas. Otherwise the
selection is real and invisible: the inspector fills in while the canvas goes
on showing somewhere the block is not. Only selections made *elsewhere* do
this; a click on the canvas, or the refresh after an edit, leaves the view
exactly where it was, so dragging a block into a sub-system does not dive into
that sub-system after it. If the block is of a kind the diagram is not drawing
— parameters are hidden unless asked for — it says so and where the switch is,
rather than highlighting nothing.

Double-clicking a block in the tree opens its full settings, as
double-clicking it on the diagram does; double-clicking a sub-system there
opens and closes it.

**Getting around.** The diagram shows one sub-system at a time. A sub-system
inside it is drawn as a container with the number of blocks it holds;
double-click to go in, and the breadcrumb above the canvas leads back out. A
connection whose far end is elsewhere in the model is still drawn, running to
the edge of the view. Right-click the canvas for **Sub-system** or
**Go to**, a block for **Move into**, and a sub-system for **Open**,
**Rename**, **Disable**, **Dissolve** or **Delete, and everything in it** —
the last two being the pair: dissolving moves its blocks out into the
sub-system around it, deleting takes them with it. A transport has no
Dissolve, since its parts are not blocks on their own; it is deleted whole. A block can also be **dragged onto a sub-system**: hold it over the container
and it lights up with *Release to move Kd into NearField* at the pointer, and
letting go puts it inside. A whole selection goes at once — the hint counts
them — and the menu on a selection of several offers **Move into ▸**
and **Delete**. The position is left behind — the coordinates it
was dropped at belong to the diagram it just left — so it is laid out with its
new neighbours the first time that sub-system is drawn. Dropping anywhere else
is the ordinary move it has always been. **A sub-system is dragged the same
way**, into another sub-system or out to the top level, and so is a selection
holding one; what it cannot be dropped into is itself or anything inside it,
which is simply not offered — the container does not light up and the release
is an ordinary move. The node being dragged is drawn on top of what is under
the pointer, so the hit test has to look past what it is carrying: with one
test it found the sub-system in your hand instead of the one you were aiming
at, and every drop was a silent no-op.

**Move into ▸ a new sub-system…** makes one where the block
already is and puts it straight in, which is how a model that arrived flat
gets organised: doing it as two steps leaves an empty sub-system behind the
moment you stop halfway. The new one takes the block's place on the diagram,
and everything that referred to the block follows it down. A name already used
by a sub-system there is used rather than side-stepped into `Sand1`, and you
are told that is what happened; a name already used by a *block* is refused,
since the two cannot share an id. The tree on the right is the same hierarchy, and the inspector
says which sub-system a block is in.

Importing an `.eco` file brings its hierarchy with it: 66 of the 71 real models
tested use sub-systems, up to five deep. A *group* is Ecolego's purely visual
grouping and does not scope names, so its blocks are read as belonging to the
sub-system around it, which is what the file's own ids say.

## Transports

A soil column, a sediment, a stretch of river: transport through a homogeneous
material is modelled by cutting it into N slices and letting each exchange
with the next. Drawing fifty compartments and forty-nine transfers is not how
anyone wants to spend an afternoon, and you do not have to. A **transport** is
a block that is also a sub-system — one node standing for the whole chain,
drawn as its two ends. It has its own icon and colour in the tree and on the
diagram, its own menu, and a connect handle like a compartment's.

Right-click the canvas for **New transport here**. What arrives is a
sub-system holding four blocks, under the names a project file uses for them:

| Block | What it is |
|---|---|
| **Begin** | a compartment; the first slice. Its initial inventory, its decay setting and its dy/dt term are every slice's. |
| **End** | a compartment; the last slice. What leaves the chain leaves from here. Its own dy/dt term, if it has one, applies to it alone. |
| **N** | an expression, unitless: how many slices. Worked out before the run starts, so numbers, parameters and expressions made of those; a fraction is rounded down. |
| **i** | the element counter: inside a transfer between Begin and End, the number of the slice the transfer leaves, 1 at Begin. It is the chain's own count, not an expression of the model's — it has a value only inside the transport, is offered nowhere else, and does not appear among the Expressions in the left panel. |

Draw the transfers a slice exchanges with the next **between Begin and End** —
downwards, and upwards too if there is dispersion to model — and connect the
outside world to the transport itself: **a line dropped on the transport feeds
its Begin, and a line dragged from its handle leaves from its End**, so the
chain connects from outside like the one block it stands for. (Going inside
and connecting to Begin or End by name does the same thing.) When the model
runs, Begin and End stand at the two ends of a chain of N compartments, every
transfer drawn between them is repeated N−1 times, once per pair of
neighbours, and everything from outside arrives at the first slice or leaves
from the last. Begin, End and the rest of the model report as usual; the
slices in between take part in the run and stay out of the results. The node
on the diagram says `chain of N`, and the panel says how long the chain is and
between which two blocks.

```json
{
  "transports": ["Column"],
  "compartments": [
    { "name": "Begin", "system": "Column", "transport": "begin",
      "initial": "if(i == 1, 1000, 0)" },
    { "name": "End",   "system": "Column", "transport": "end" }
  ],
  "expressions": [
    { "name": "N", "system": "Column", "transport": "number", "equation": "20" },
    { "name": "i", "system": "Column", "transport": "counter" }
  ],
  "transfers": [
    { "name": "Down", "system": "Column",
      "from": "Column.Begin", "to": "Column.End", "rate": "v / dx" }
  ]
}
```

**Every slice starts as Begin says.** Begin's initial inventory is the initial
inventory of the whole chain, slice by slice — End's box is shown for what it
is, and not read. To start the first slice alone, use the counter: `if(i == 1,
1000, 0)`. The counter is what makes a slice differ from its neighbours
anywhere else too: a rate written `k * i`, or an expression inside the
transport that reads `i`, `Begin`, `End` or one of the transfers between them,
is evaluated once per pair of neighbours with that pair's values. Seen from
outside the transport, such an expression is what it comes to for the first
pair with the counter at 1, and a transfer drawn between Begin and End is the
one joining the first pair. It stays one transfer in every other respect: a
value held *per transfer* — a flow, in the silo model — is read by every pair
as the drawn transfer's, and `_source_` and `_target_` in its rate are Begin
and End for every pair.

**Its dimensions are inherited.** Begin, End and the operations are one shape,
and the shape is not a choice once the chain is connected: as a transfer takes
the indices its two ends have in common, the transport takes the indices of
what feeds it and what it delivers to have in common — paired by root,
narrowed to a sub-set where one end is one, and left out where only one end
has a dimension of that root. A column between soil per nuclide and object and
a sea per nuclide is a column per nuclide, and the inflow is then the one flux
that sums over objects, which its own row says and its **sum extra indices**
tick allows. Connected at one end only, the chain takes that end's dimensions
whole; unconnected, it keeps what it was given. Change what is connected and
the chain follows; a narrowing you state on Begin is kept. This is more than a
project file asks for: there, Begin's choice is pushed to End and the
operations, leaving the ends to you.

**Operations over the chain.** Right-click the transport for **Add operation
over the chain**, or right-click the canvas *inside* it for **Add transport
operation here**. It is the **sum** or the **mean** of the slices, and it is
read one of three ways, chosen in its settings: over **the whole chain**, by
name, as any expression is; at **one position**, called as `Depth(0.5)`, where
a position is a fraction of the chain's length, 0 at Begin and 1 at End, and
the value is the slice that fraction falls in; or over **a stretch**, called
as `Depth(0.2, 0.6)`, the sum or the mean of the slices between, the two at
the ends counting by the fraction of each that lies inside. The last two have
no value of their own — they are functions of where you ask — so they are not
in the results and cannot be referred to by name; the checker says so if you
try. A position outside 0 to 1 stops the run with a message.

**What it costs.** N states per index the chain is on, and N−1 copies of each
transfer between the ends: the model is built with the chain written out, so a
column of fifty slices over twenty radionuclides is a thousand states, exactly
as if drawn by hand. Which is the point — nothing runs differently, it is only
drawn differently. One consequence: a model that calls an operation at a
position has no analytic derivative for that call, so its Jacobian is
differenced; the status line says so.

**What is checked.** A transport needs exactly one Begin and one End, indexed
alike — change one's index lists and the other's follow, and the operations'
with them — and an N the run can know before it starts, one or more. The
problem strip says which is missing, naming the block. **A transport is kept
whole or deleted whole.** None of its parts — Begin, End, N, the counter or an
operation — can leave it or be deleted on its own, and it cannot be dissolved
into ordinary blocks: let loose, Begin is a compartment with a misleading name,
the counter an expression that says 1, and an operation a block that comes to
nothing, and the model would build and mean something else with no line saying
so. The same rule refuses those moves in any tool that has transports.
Nothing nests inside a transport, and switching off Begin or End switches off
the chain, its other parts with it. A copy of the transport is a transport; a
Begin copied on its own is a compartment.

**Importing** an `.eco` project brings its transport sub-systems across with
their parts — `transport-begin`, `transport-end`, `transport-number`,
`transport-element-counter` and `transport-operation`, an operation with one
`<argument>` read at a point and one with two over a stretch. None of the 87
real projects here has one, so this was verified against real files and
against chains drawn by hand rather than against a file: see INTERNALS.md.

## Shapes on the canvas

A compartment model says what flows where and at what rate. It has no way to
say that *these four compartments are the near field*, or to draw the lake that
two of them stand for. So the canvas carries shapes of its own — right-click
the background and choose **Add shape…**

They are annotation. They sit behind every block, take no part in the
equations, and belong to one sub-system's canvas the way a block does. They are
saved with the model, because a drawing that vanished on reload would not be
worth making.

**The dictionary** is 45 figures in six groups: the ordinary boxes and circles,
a group box whose label sits on its top bar, lines and arrows, and the things
these models are usually *about* — a tree, a conifer, grass, a mire, a lake, a
river, soil layers, bedrock, a well, a borehole, a house, a barn, a factory, a
canister, a repository, a drum, a cow, a fish, a crop, a person. The picker
shows each one drawn rather than named: `mire`, `bedrock` and `soil` are three
words for three pictures, and the pictures tell them apart in a glance.

**Adding one** is the last section of the canvas menu, with the other things
that are about the canvas rather than about the model — a picture of it, and
its settings. It goes where the menu was opened.

**Editing one** is the right-click menu on the shape itself: fill and line
colour from a palette of ten, a line style and width, a label and its size,
flips, the order among the shapes, duplicate and delete. Drag it to move it,
its grips to resize it — eight for an area, two for a line, since a line's ends
*are* the corners of its box. **Del** removes what is selected. Shapes and
blocks are selected apart from each other, so nothing has to guess which a
menu or a keystroke is about.

The colours are ten named tokens rather than a colour wheel, each with a step
chosen for the light theme and another for the dark one, and each fill is the
same token mixed down. That is what keeps a diagram legible in both themes and
in an exported picture — where the shapes come along, with the editing chrome
left behind.

Figures are written in the unit square and scaled to the shape's own box, so a
wide, short box has the same line weight on its uprights as on its rails; a
`scale()` transform would have thinned one and fattened the other.

## Lookup tables

A parameter is a constant. A **lookup table** is a value that changes as the
simulation runs: a list of `(x, y)` points and a rule for reading between and
beyond them. It is how a model says *the flow follows this measured series*,
or *the glaciation rescales the groundwater from year 10 000*.

```json
{
  "lookups": [
    { "name": "Q_gw", "unit": "m3/year", "interpolation": "linear",
      "points": [[0, 1.2], [5000, 2.1], [9000, 0.06], [12000, 1.4]] }
  ],
  "transfers": [
    { "name": "Advection", "from": "Regolith", "to": "Lake", "rate": "Q_gw / V" }
  ]
}
```

The table is read at the simulation clock, so `Q_gw` in an equation is its
value *now*. Everything else about it behaves like any other block: it can be
indexed, it appears in the block list and on the chart, and it is drawn on the
diagram — as a box with the shape of its own data in it, which is the fastest
way to tell four drivers apart.

**Every picture of a table is drawn the way the table is read.** The thumbnail
on the diagram, the one in the left panel and the larger preview in the points
editor all follow the rule the table carries, so a table read with *use input
below* is a staircase and not a sloping line. They used to be straight lines
whatever the rule, which for a table of four points showed a quantity ramping
where the model holds it flat — the opposite of what the picture is for.

Five rules, with the counts they carry across the `.eco` files on this
machine:

| `interpolation` | What it does | In the corpus |
|---|---|---|
| `linear` | straight lines between the points, held flat beyond the ends (the default; Ecolego's *Interpolation-Use End Values*) | 3261 |
| `below` | the value at or before the lookup point | 90 |
| `extrapolate` | as `linear`, but the end segments are continued outwards | 31 |
| `above` | the value at or after the lookup point | 0 |
| `nearest` | the value of whichever point is closer | 0 |

`"cyclic": true` wraps the lookup point into the table's own span first, so a
year of data can drive a century of simulation.

Two points at the same `x` are how a table expresses a step: the later one
wins. A table with a single point is that value everywhere; a table with no
points reads as zero.

**Editing.** The inspector shows the curve, then a text box with one `x, y`
pair per line — separators are comma, tab, semicolon or space, so a pair of
spreadsheet columns pastes straight in. The preview redraws as you type, and a
line that is not a pair of numbers is reported by line number and not
committed. Real tables are long: the ones here average 70 points and the
largest has 181.

**A table with an argument.** A table may be read at something other than the
clock. Give it an `"argument"` and it stops being a value and becomes a
function other equations call:

```json
{ "name": "Kd", "argument": "X", "points": [[0, 0], [1, 2], [10, 20]] }
```

```
Sorbed = Kd(Conc_water)
```

Such a table has no value of its own, so it cannot be referred to by name
alone. Its derivative is the slope of the segment the argument lands in, which
the analytic Jacobian uses — exactly, where a finite difference taken across
one of the table's corners would not be.

**In an equation.** Two functions take a table inline, for one too small to be
worth a block: `interpolationUseEndValues(x, x1, y1, x2, y2, ...)` and
`interpolationExtrapolation(...)`. They are the same arithmetic as `linear` and
`extrapolate`. The corpus uses them 343 times.

**The Jacobian.** A table read at the clock contributes nothing to `df/dy` —
its value does not depend on the state — but it does make the matrix
*time-dependent*, so the solver stops treating it as constant and refreshes it.
An argument-keyed table contributes its slope. Either way the analytic path
stays available; see [The Jacobian](#the-jacobian).

## Functions

When the same arithmetic turns up in fifteen equations, write it once. A
**function** is a block with named parameters and a body, called from any
equation in the model:

```json
"functions": [
  { "name": "TR_adv", "parameters": ["LAI", "leaf_width"],
    "equation": "C_adv * vel_wind * leaf_width^0.2 / sqrt(LAI * area_obj)",
    "unit": "1/year" }
]
```

and then `TR_adv(LAI_ter, 0.02)` wherever it is needed — in an expression, a
rate, an initial inventory, a dy/dt term, anything that holds an equation.

**Making one.** Either the **+** beside *Functions* in the left panel, or
right-click the canvas and choose *Add other block ▸ Function*, which puts it
where you clicked. What arrives is called `Func`, takes one parameter `x`, and
has an empty body — the problem strip says so by name until you write it, since
a body this could invent would be a guess. The settings dialog has the two
boxes that matter: the parameters, written as a comma-separated list, and the
body.

**On the diagram.** A function is drawn where it lives, labelled with its
signature — `ADV(u, d)` — with a longer dash round it than an expression, since
nothing flows through one and it has no connect handle. What joins it to the
rest of the model are the influence arrows: in from whatever its body reads,
out to every equation that calls it. Turn those on with *Show ▸ influences*,
and the functions themselves off again with *Show ▸ functions*.

**The body reads the model.** Its parameters are extra names beside everything
it could already see: `C_adv` and `area_obj` above are blocks. A name in the
body means what it means *where the function is written* — a function inside a
sub-system reads that sub-system's names, however far away it is called from —
so moving a call never changes what the body means.

**A parameter may shadow a block.** `ADV(position, kd)` in a model full of
`Kd` values is the case to have in mind. Inside the body the parameter wins;
everywhere else the block is untouched, and renaming that block leaves the
parameter alone.

**A call is worked out where it is written**, at the index of whatever calls
it. So a function is not indexed and has no values per index: the caller is the
one standing at an index, and the body reads the model there. This also means
an argument is evaluated once per place it appears in the body, and that the
analytic Jacobian differentiates through a call like any other arithmetic.

What is refused, and said plainly: the wrong number of arguments, a function
that calls itself directly or round a ring, an index on a parameter
(`x[Cs-137]` — put the index at the call instead), and a body that is still
empty. An empty body is a real state to be in — it is what an import makes of
a function whose definition could not come across — so the model loads, the
problem strip asks for the equation, and only running is refused.

A function has no **Enabled** switch: it has no value to leave out of a run,
and every equation that calls it would stop meaning anything. Delete it
instead, which the editor refuses while an equation still calls it.

## When only part of an inventory can move

A transfer's flux is `rate × amount`, which is linear in the inventory. That is
right for advection and diffusion, and wrong for the two things a near field is
mostly about: past a solubility limit the excess is precipitate and does not
travel in the water, and under a sorption isotherm the fraction in solution
*rises* with the inventory rather than staying fixed.

Both are the same correction — a fraction between 0 and 1 on the flux.

```figure availability
  flux = rate x availability x amount in the donor

  [ no limit ]        availability = 1
  [ solubility ]      min(limit / amount, 1)
  [ Langmuir ]        (amount + alpha) / (amount + beta)

  The availability belongs to the transfer, not to the compartment:
  a limit holds back what leaches and not what erodes.
```

Set it in the transfer's own settings: **Availability**, under the rate. It is
offered on a transfer that has a donor compartment and multiplies by it, because
those are the two things an availability is a fraction *of* — on a transfer
carrying an absolute flux there is no inventory to take a fraction of, and the
box is not shown rather than shown and then refused. Choosing a scheme reveals
the fields that scheme needs and no others: a limit, or the two Langmuir
coefficients, plus the list a shared scheme sums over.

In the model file it is one object on the transfer:

```json
{ "name": "Leaching", "from": "Waste", "to": "Water", "rate": "k",
  "availability": { "scheme": "shared_limit", "limit": "Sol * V", "over": "Elements", "basis": "moles" } }
```

| `scheme` | What it does |
|---|---|
| `limit` | `min(limit ÷ amount, 1)` — only as much as the limit can travel |
| `shared_limit` | the same with one limit over a group, the amount summed across it |
| `langmuir` | `(amount + α) ÷ (amount + β)` — a sorption isotherm, rising towards 1 |
| `shared_langmuir` | the same over a group |

**Carry what is held back instead** (`"unavailable": true`) is one minus the
scheme — the transfer that carries precisely what the other one leaves behind,
erosion beside leaching.

**It belongs to the transfer, not to the compartment**, and that is the point: a
solubility limit holds back what leaches and does not hold back what erodes, and
a flag on the compartment cannot say that.

**The shared scheme is the one a near field wants.** An elemental solubility
limits the element, and the isotopes leave in the proportions they are present
in. Three nuclides at 100, 50 and 25 under a shared limit stay at 0.571, 0.286
and 0.143 of the total as they drain; under an individual limit they do not,
because each is being held to the same cap regardless of how much of it there is.

**What the group is comes from Shared over** (`over`), read against the donor's
own dimensions:

| `over` | The group |
|---|---|
| a list the donor is indexed by — `Radionuclides` | the whole of it: one limit shared by every nuclide the donor holds |
| a grouping of one of those — `Elements` | one group per index: the isotopes of each element share that element's limit |

The second is an elemental solubility: `Sol` per element, `over: "Elements"`, and
uranium's isotopes share uranium's limit while caesium's share caesium's —
the caesium is not held back by the uranium. The first adds everything the
donor holds into one amount, so every atom in the compartment counts against
the limit read at the index; it is the right choice for one element's
isotopes on their own list, and it is what `over` naming the nuclide list has
always done. An element that should not be limited at all is given a limit
larger than anything the compartment can hold — `1e300`, say. A list that is
neither — nothing along it for the donor to share — leaves the individual
scheme, reading the donor in the model's own unit as that scheme does.

**Sum the group in moles, not becquerels.** A solubility is a limit on atoms
in solution, and becquerels do not count atoms: at equal activity U-238 is
18,200 times the atoms of U-234, so a limit shared by activity holds the U-234
back as hard as the U-238 and is a different limit for each isotope. **Summed
as → moles** (or `"basis": "moles"` in the file) converts each isotope's
inventory through its half-life first — `A/λ` atoms with λ in 1/s, over
Avogadro's number — and the `limit` is then a molar amount in mol, so the share
each isotope takes is its share of the atoms. A model whose decay unit is already `mol` gains nothing from it, and the
dialog says so; a stable isotope has no activity to convert and is left out of
the sum. The proportions of what moves are those of what is there either way —
the basis decides *how much* moves, not *what*. To write a limit from a
solubility, the expression is yours to type: `Sol * (V + Kd * M)` if the
compartment's inventory includes what is sorbed.

**With an availability, the transfer's own value is rate × availability.**
That is what its name means in an equation and what the chart draws for it, so
`Leaching * Waste` is still the flux through `Leaching` — the idiom every
assessment model uses to read a flux keeps working — and the rate as typed is
in the transfer's settings, where it is edited.

This makes the equations non-linear, and the **analytic Jacobian** follows: the
tangent generator differentiates the scheme as the code is written, branch by
branch — nothing past a limit's corner, `(dL·a − L·da)/a²` beyond it, the
quotient rule for Langmuir — and the sparsity pattern takes every member of a
shared group, since each flux reads all of them. The test suite checks the
matrix against differences on both sides of every scheme's limit. On
`examples/biosphere.json` with a solubility limit on the release, ros23 takes
the same 734 steps it took when the matrix was differenced, with 2,204
evaluations of the derivative rather than 13,948 — and on a model of tens of
thousands of states, which could not be differenced at all, it is the
difference between running and not.

## Reducing a dimension

Two blocks collapse many values into one. They reduce along different axes,
which is why they are two blocks and not one:

```json
{
  "index_operations": [
    { "name": "TotalWater", "target": "Water", "operation": "sum",
      "index_lists": ["Object"] }
  ],
  "aggregates": [
    { "name": "Inventory", "targets": ["Regolith", "Water"], "operation": "sum",
      "index_lists": ["Radionuclides", "Object"] }
  ]
}
```

**An index operation** takes one block and reduces it along one of its index
lists. Which list is not written down — it follows from the dimensions, and is
the one the operation does *not* keep. `Water` is indexed by `Radionuclides × Object`
and `TotalWater` keeps `Object`, so it sums over the nuclides. A block with no
dimensions of its own reduces the target's first list. That is the rule a
project file states, and it is why an index
operation always has exactly one dimension fewer than its target — the
inspector shows which list is being reduced so a mismatch is visible rather
than mysterious.

**An aggregate** takes several blocks and combines them index by index.
Targets may be of lower dimension than the aggregate — a scalar or a
per-nuclide block is read at every combination of the rest — and one whose
dimensions cannot be reached from the aggregate's position is left out rather
than failing the block, as in the aggregate code generator.

| `operation` | | index operation | aggregate |
|---|---|:-:|:-:|
| `sum` | adds them up (the default) | ✓ | ✓ |
| `product` | multiplies them together | ✓ | ✓ |
| `min` / `max` | the smallest / largest | ✓ | ✓ |
| `mean` | the arithmetic mean | ✓ | ✓ |
| `percentile` | with a `percentile` from 0 to 100 | ✓ | |

Both compile to a call in the ordinary equation language — `sum(...)`,
`max(...)` — which means they get the analytic Jacobian, the dependency ordering and the per-index
values for nothing. A `max` over four objects differentiates to the derivative
of whichever object is currently largest, not to a finite-difference smear.

Renaming or deleting a block a reduction reduces behaves like any other
reference: the rename follows through, and the delete is refused while
something still reduces it.

**Scenarios.** A block may be indexed by a *scenario* list — alternative runs
rather than a real axis — and that list is left out when counting dimensions.
So a target indexed by `Scenarios × A × B`, reduced to `A`, is reduced over
`B`. See below.

## Scenarios

An index list marked `for_scenarios` is not an axis of the model but a set of
alternative futures. The usual arrangement is one simulation per scenario;
**this tool runs one at a time** — pick it under **Simulation** in the left
panel, and every block indexed by that list is read at the index you picked.

That is exactly what one run of a per-scenario sweep does: with a scenario
selected, a scenario-dependent block is treated *as if
it were not*, with the scenario's index inserted automatically. So the
dimension disappears from the simulation — from the state vector, from the
widths and strides, from the result labels — while staying a dimension you can
edit, so a parameter still holds a value per scenario.

```json
{
  "scenario": "Warmer and wetter",
  "index_lists": [
    { "name": "Climate", "for_scenarios": true,
      "indices": ["Present", "Warmer and wetter", "Drier"] }
  ],
  "parameters": [
    { "name": "Runoff", "index_lists": ["Climate"], "value": 0.02,
      "entries": [
        { "index": { "Climate": "Warmer and wetter" }, "value": 0.05 },
        { "index": { "Climate": "Drier" }, "value": 0.005 }
      ] }
  ]
}
```

`Runoff` holds three values and the simulation sees one of them, so an
expression that reads it needs no scenario dimension of its own — which is the
whole point, and the reference that had nowhere to go before. The choice is
saved with the project under `scenario`; a saved choice that no longer names a
scenario falls back to the first rather than leaving the model with none.

A block may reach the scenario dimension through a **sub-set** of the scenario
list or through a list **mapped** onto it, and both are the same dimension:
setting the active scenario walks a block's lists for one whose root is the
all-scenarios list and takes the matching index by name or through the
mapping. If the active scenario is not in a sub-set a block is indexed by,
that block has no value for it and falls back to its default.

What is *not* here is running them all: no scenario sweep, no per-scenario
simulation settings, and no comparison chart. One at a time, chosen in the
panel. `examples/scenarios.json` is the same model under three futures.

## Numbers read off a finished curve

The peak dose. The year it peaked. How much arrived altogether. These are the
numbers an assessment quotes, and they are all reductions of a curve the run has
already produced — so they cost the solve nothing:

```json
"derived": [
  { "name": "Peak_dose",   "kind": "max",         "of": "Dose [I-129]" },
  { "name": "Peak_year",   "kind": "time_of_max", "of": "Dose [I-129]" },
  { "name": "At_10k",      "kind": "at_time",     "of": "Dose [I-129]", "at": 10000 },
  { "name": "Total",       "kind": "integral",    "of": "Dose [I-129]" },
  { "name": "Annual_mean", "kind": "period_mean", "of": "Dose [I-129]", "period": 1 },
  { "name": "Peak_annual", "kind": "max",         "of": "Annual_mean" }
]
```

| `kind` | What it is |
|---|---|
| `max`, `min` | the largest or smallest value over the run |
| `time_of_max` | when it got there — a time, so it carries the run's time unit |
| `at_time` | the value at one moment, interpolated between the output points and held flat outside the run |
| `integral` | the running total, by the trapezium rule — a curve rather than a number, and it carries `unit × time` |
| `period_mean` | the series averaged over each period of `period` (in the run's time unit): the **annual mean** with a period of 1 |
| `period_sum` | the series integrated over each period — the release in each year; carries `unit × time` |
| `period_change` | the value at the end of each period less its value at the end of the one before |
| `period_rate` | that change over the period's length; carries `unit / time` |

`of` names the series as the chart spells it — **or another derived output**, in
any order, so `Peak_annual` above is the peak annual mean dose, the number
several regulators write their limit against and one that a logarithmic output
grid has nowhere in it. Each becomes an ordinary output: one more line on the
chart, one more column in an export. The three that are a single number draw
as a flat line, which is deliberate — a flat line at the peak drawn across the
series it came from is how a peak is read.

**The period kinds read a curve one period at a time**, and are drawn as a
stair-step: every time in a period carries that period's number. They are worked
out from the curve *between* the period boundaries, interpolating the curve at
the boundaries themselves, so they do not depend on whether the output grid
happens to have a point at each year — a dose that peaks between two output
times still counts for as long as it lasted. The mean is the integral over the
period divided by its length; a last period the run does not fill is worked out
over the part it covers.

**These are not the blocks that remember.** A min/max block, a running mean, a
snapshot and a delay accumulate *during* the integration, because a delay has
to — it feeds its own value back into the derivative. The cost is that a model
carrying one can never have its trajectory re-used, so every edit re-solves
it. A derived parameter costs none of that. Reach for a recorder when the
model *reads* the number while it runs, and one of these when a person reads
it afterwards. Almost every peak dose is the second.

## Blocks that remember

Everything above is a function of the state as it stands: hand it `(t, y)` and
it can be worked out again from scratch, which is why the runner solves first
and fills in the algebraic blocks afterwards. Five block types are not, and
they are the ones that answer the questions a safety assessment actually asks —
*how bad did it get, and when?*

| Block | What it holds |
|---|---|
| **Min/max** | the largest (or smallest) value its target has taken |
| **Running mean** | the mean of its target over the time it has been recording |
| **Snapshot** | its target as it was when an event last fired |
| **Delay** | its target as it was a given time ago |
| **Trigger** | not a value so much as an instant: the moment one expression crosses another |

Each keeps a **history** — the (time, value) pairs written as the solver
accepts steps — and reads it back at each output time, which always lies at or
before the last step taken. That is what lets them work in the two-phase
arrangement: the solver fills the history as it goes, and the algebraic pass
afterwards reads it. Between two accepted steps a min/max or a running mean
reports the value at the earlier one, a staircase — there is no value in
between, only the two the solver stopped at.

A **running mean** is the exception that also carries a state: `dS/dt = target`
while it is recording, and the block's value is `S` divided by the time it
covers. That makes it a state block, for exactly this
reason, and here its integral sits in the state vector after the compartments —
hidden from the results, since the block's own value is what you want.

**Triggers** are event functions in the usual sense: `first - second`, with a
direction, and every one of them is *terminal*. The solver locates the
crossing inside the step with regula falsi over its own dense output, stops
there, applies whatever the event drives, and starts again from the event. So
a snapshot taken "when the dose falls back below the limit" is taken at that
instant, not at whichever step the solver happened to land on next — which for
a step spanning a century is a different model. A crossing at the very instant
a restart begins is ignored, or an event whose two expressions stay equal
would fire again forever.

A min/max or a running mean can be **driven by events** as well: `reset_event`
starts the extreme or the mean again, `start_event` holds it until the event
fires, and `stop_event` freezes it. Left unset, it records from the beginning.

All five differentiate exactly, so a model using them keeps its analytic
Jacobian: a min/max is `max(so far, target)`, whose derivative is the target's
wherever one exists; a running mean's is its integral's over the same elapsed
time; a snapshot and a delay report the past, which no present state can move.
The matrix is no longer constant, though — a mean divides by a time that grows
— so it is refreshed rather than factorised once.

`examples/recorders.json` is a release pulse through a lake with all five on it.

## Far-field pathways (FARFCOMP)

Transport through fractured rock is not a compartment model, and drawing it as
one is a hundred boxes of numerics that say nothing about the model. One
**far-field pathway** block is that whole calculation: a dual-porosity model of a
single migration path, in the formulation set out in Appendix B of *SKB
TR-19-06* with Chapter 3 of *TR-90-01* behind it.

```
   FRACTURE          ROCK MATRIX
   <2·TW/F>    <────── PENDEP ──────>       (m)
NF │████████│ ↔ │ ↔ │███│ ↔ ··· ↔ │████████│
   ⋮   ↑ advection along the fracture
 2 │████████│ ↔ │ ↔ │███│ ↔ ··· ↔ │████████│
 1 │████████│ ↔ │ ↔ │███│ ↔ ··· ↔ │████████│
       ↑ in                ↔ diffusion sideways
```

Solute travels along the fracture by advection and dispersion. Three things
hold it back: sorption on the fracture coating, diffusion into the stagnant
pore water of the rock matrix beside it, and sorption on the matrix's own
micro-surfaces. The diffusion is one-dimensional and perpendicular to the flow,
so the path is N_F fracture cells in series, each with its own chain of N_M
matrix layers behind it — and every one of those cells decays and grows in
along the model's chain, like any other inventory in the model.

**What makes it one block rather than a sub-system full of compartments** is
that the equations are written in terms of the water **travel time** TW and the
**Peclet number** Pe instead of a pore velocity and a dispersion coefficient —
effectively `v = 1`, `z = TW`, `D = TW/Pe`. The whole path is then described by
two numbers a hydrogeological model can supply, TW and the flow-related
transport resistance F, plus sorption and diffusion data per nuclide. The cell
counts are not a modelling choice at all; they are numerics, and the block owns
them.

### Wiring one up

A path is a block with a connection at each end, drawn like any other.

**In.** Anything delivered to a path lands in its first fracture cell — the
inlet end of the fracture, where the water enters. Three ways to send it there:

- **drag a transfer onto it** — from a compartment's right edge, as for any
  other connection. The path lights up as a target like a compartment does;
- **a source term**, for an input from outside the model: right-click the
  canvas, **Add source term ▸**, and the path is in the list beside the
  compartments;
- **the Matrix tab**, where a path is a row and a column both: click the cell
  where a compartment's row crosses its column.

**Out.** Drag from the path's own right edge onto a compartment and you get a
**release**: an ordinary-looking transfer whose rate is **not editable**,
because it *is* the flux out of the far end of the path, which the block has
already worked out. The panel shows it rather than offering it — a rate you
could type would be a second answer to a question the path has answered. There
is no donor multiplication either: the mass has already left the path, taken
off the last cell by the outflow condition, so a release delivers and takes
nothing.

A path may have several releases, or none. The flux is also the block's own
value, so `Rock` in any equation is that same number — `Rock / well_flow` is a
concentration — whether or not it is delivered anywhere.

What a release cannot do is end at another path. A path's inlet takes an
inventory per unit time and a release is exactly that, but chaining two of them
with nothing in between hides where the mass is; put a compartment between.

What you cannot do is draw a transfer *out* of one. The release has already
left the path — the outflow boundary condition takes it off the last cell — so
a transfer taking from it would be taking the same mass twice, and the model
says so rather than letting you.

### What it may be indexed by

**Whatever a compartment may be indexed by**, including nothing.

Indexed by the radionuclides it is one path per nuclide, with the decay chain
running between them inside every cell: the ordinary case. Indexed by nothing
it transports one quantity with **no decay and no ingrowth** — a tracer, a
stable species, or a mass.

**Indexed by anything else as well, it is that many paths side by side.** One
block per landscape object, per climate, per waste type — the same geometry
read at each index, its own cells, its own states. The only dimension that
cannot be doubled is the radionuclides: the decay chain runs along exactly one
of them, and a block indexed by the nuclide list *and* a sub-set of it is
refused by name.

What that costs is real, and is said where it can be seen rather than refused:
the line under the dimension boxes counts the states, and a second dimension
multiplies several hundred of them by its width. `5 × 20` cells over four
nuclides is 420 states; over four nuclides and ten objects it is 4,200.

**The settings follow the same split as the chemistry.** `Kd,f`, `εm`, `Kd,m`
and `De,m` are properties of the nuclide and hold a value per index, as they
always did. `Tw`, `F`, `Pe`, `ρm` and the penetration depths describe the
*path*, so they hold one value per index of everything **except** the
radionuclides — one travel time per object, not one per (nuclide, object) and
not one for the block. They appear as their own columns in **Values per index**
as soon as the path has a dimension other than the nuclides, and editing one on
any row writes it for that object: the other nuclides' rows show the change,
because it was never theirs to differ on. The same water takes the same time
whatever is dissolved in it.

This was measured rather than assumed. A path indexed by `[Radionuclides, Object]`
with a travel time per object was run against two ordinary one-dimensional
paths carrying those travel times, and the release curves agree to **three
parts in 10⁸ of the peak** — the solver's own noise. The engine had been
written for it all along; what was missing was the layout that says where each
combination's values live.

### What the settings mean

Every quantity is an **equation**, so it may be a number, a parameter, a lookup
table of travel times against time, or an expression over the rest of the
model. Units are the model's own time unit throughout.

They divide in two, and the panel is organised by the division — ten settings
in two columns of five, read in pairs:

| | |
|---|---|
| **Release** | **Flow-wetted surface area** |
| **T<sub>w</sub>** | **F** |
| **K<sub>d,f</sub>** | **P<sub>e</sub>** |
| **ε<sub>m</sub>** | **ρ<sub>m</sub>** |
| **K<sub>d,m</sub>** | **D<sub>e,m</sub>** |

Each retention term sits beside the number it is read against, and the two
derived readings are at the top. The names are the symbols they are on paper —
subscripts and Greek — not a transliteration of them.

**The chemistry belongs to the nuclide**, so each may hold its own value — set
under *Values per index*, the same grid every indexed block has, one
radionuclide per row:

| | |
|---|---|
| **K<sub>d,f</sub>** | sorption on the fracture coating, in m³/m² (0 for none) |
| **ε<sub>m</sub>** | the matrix porosity. Per nuclide, because the porosity a species can reach depends on the size of the species |
| **K<sub>d,m</sub>** | the partition coefficient in the rock matrix, in m³/kg |
| **D<sub>e,m</sub>** | the effective diffusivity in the matrix, in m²/[time] — the diffusivity in the pores times the transport porosity |

**The path holds one value each**, however many nuclides travel along it:

| | |
|---|---|
| **T<sub>w</sub>** | the water travel time along the path |
| **F** | the flow-related transport resistance, in [time]·m²/m³ |
| **ρ<sub>m</sub>** | the dry bulk density of the rock |
| **P<sub>e</sub>** | the Peclet number; the dispersion is T<sub>w</sub>/P<sub>e</sub> |
| **PENDEP**, **PENDEP0** | the depths, under *Discretisation* below |

The water does not travel at one speed for caesium and another for iodine, so
there is no per-nuclide box for T<sub>w</sub> to be filled in by accident. They
are still equations, and still read at every step.

A path may be indexed by the radionuclide list or by nothing at all — one block
is one migration path, and every other dimension multiplies several hundred
states by its width — so that is the only list the panel offers.

F/T<sub>w</sub> is the flow-wetted surface per unit volume of water, which
is what turns a resistance into a geometry — the panel shows it, and the
fracture aperture that goes with it, beside the two fields it comes from.

**The release goes to one place.** It is the flux out of the far end of the
fracture: a single quantity the block works out for itself, so two lines
carrying it would each deliver the whole of it and the model would release
twice what the path let through. Pick the compartment in the panel, or drag
from the dot on the block's right edge; pointing it somewhere new moves the
line that is there. *Read only* takes the line away and leaves the flux
readable as the path's own name in any equation.

The **Discretisation** section is the numerics. Its fields are labelled by
what they choose rather than by the input names the formulation uses —
`PENDEP`, `NF`, `OB` are not symbols anybody reads a report against, and a
panel headed by them reads as a listing of variables. Each name is on its
field's tooltip for anyone cross-checking against SKB's own reports.

| | |
|---|---|
| **Depth into the matrix modelled** | `PENDEP` |
| **First layer's thickness** | `PENDEP0`. Left empty it is worked out: the thickness that makes the layers grow by a factor of e, which for a 12.5 m depth in 20 layers is 44 nanometres |
| **Fracture cells**, **Matrix layers** | `NF` (at least 1) and `NM` (at least 2) |
| **Water downstream of the path** | `OB`: infinite dilution, the same concentration as the last cell, linear extrapolation, or quadratic. The stored value is the number the reference uses; the choice is made by what it means |
| **Cells past the release point** | `NB` — extra fracture cells *past* the point the release is read at, so the reading stops depending on the outflow condition |

### The grid disperses on its own

First-order upwinding spreads a front whether or not it is asked to: each cell
adds `v·Δx/2`, which over `NF` cells is the same as a Peclet number of
**2·NF**. So the dispersion the model *adds* is the difference between what was
asked for and what the grid already does — `d_f = adv_f·(NF/Pe − ½)` in
`coefficients`, zero exactly where 2·NF = P<sub>e</sub>. **Five fracture cells
are P<sub>e</sub> = 10.**

Three cases, and the panel warns about the third:

| | |
|---|---|
| 2·NF > P<sub>e</sub> | the grid is finer than needed; the difference is added explicitly and the total is the P<sub>e</sub> asked for, at more states |
| 2·NF = P<sub>e</sub> | the grid's own dispersion *is* the answer. Nothing is added — the cheapest grid that gets it right |
| 2·NF < P<sub>e</sub> | the correction would have to be negative to sharpen the front back up, and `max(0, …)` clamps it away. The path disperses as if P<sub>e</sub> were `2·NF`, more spread than the setting says, and no number in the model reads it off — so the panel says so |

Measured rather than asserted, by pushing a pulse through a non-sorbing,
non-diffusing path and reading the Peclet number back off the spread of the
breakthrough (σ²/t̄² = 2/P<sub>e</sub>), with P<sub>e</sub> set to 10:

| NF | measured P<sub>e</sub> | |
|---|---|---|
| 3 | 6.09 | clamped — `2·NF` |
| 4 | 8.03 | clamped — `2·NF` |
| **5** | **10.01** | the boundary: the grid alone gives the P<sub>e</sub> asked for |
| 20 | 11.08 | corrected, the residue being the outflow boundary's own 8/P<sub>e</sub>² |

The layers are a geometric series adding up to exactly PENDEP, because the
concentration gradient is steepest at the fracture wall and all but flat at
depth. A first layer thicker than PENDEP/NM cannot add up to it — the layers
grow with depth — and the block says so rather than modelling a shallower rock
than you asked for.

### What it reports

- **`<name>`** — the release out of the far end, per unit time. This is the
  block's value, so equations read it and the chart draws it.
- **`<name> held`** — the total inventory the path is holding, per nuclide. The
  other half of a mass balance, since the release is only what is leaving.
- **`<name>.F3`, `<name>.M3_1`** — every cell, when **Report every cell** is
  on: the third fracture cell, and the first matrix layer behind it. A 20 × 20
  path over ten nuclides is 4,200 series, which is not a list anyone can read,
  so it is off until it is wanted. It is how you see the profile down the
  fracture and into the rock.

A path starts empty. There is no way to write an initial inventory for one —
it would need a value per cell per nuclide, and a cell is numerics rather than
a place in the model. A path is a route, not a store: what travels it arrives
through its inlet.

### Two things worth knowing

**Extra outflow cells read inside the path.** With NB > 0 the reading is taken
between cell NF and the first extra one, so the mass it reports is still in the
model. Delivering it to a compartment as well counts it twice, and the panel
says so. Use them when you want a reading that does not depend on the outflow
condition, and read it rather than drawing a release.

**A quadratic outflow can read backwards.** `C_out = 3C_n − 3C_{n−1} + C_{n−2}`
extrapolates past the last cell, and before the front arrives that is negative:
for a moment the flux it reads runs the wrong way. Charted, that is a known
artefact of the extrapolation. Delivered into a compartment that *cannot go
negative* it is a deadlock — the constraint holds the compartment at zero while the
equation pushes it below — and the solver stops rather than integrating
something untrue. The panel warns about that combination; use a linear outflow,
or turn the constraint off on that compartment.

### Cost

A 20 × 20 path is 420 states per nuclide, so three nuclides is 1,260 — usually
most of the state vector, and one path with no nuclide dimension is 420. It is solved *with* the rest of the model, in one
system, which is the point: the release feeds a biosphere model that feeds back
into nothing, and the solver sees all of it at once. `examples/farfield.json`
is 1,266 states and takes about a second.

The automatic first layer makes the path very stiff — a 44-nanometre layer
beside a 7-metre one is a rate ratio of 10¹⁶ — so use ndf or the SciPy BDF,
and expect a few thousand steps. df/dy is generated analytically and factorised
sparsely, which is what makes that affordable: 4,630 non-zeros out of 1.6
million, in six colours.

## Waste packages: the source term with its barriers

A repository's inventory does not start in the water. It starts inside
packages — canisters, drums, concrete moulds — and reaches the near field only
as those fail and the waste form inside them dissolves. **Waste packages** is
that as one block: add it from the canvas menu (or `waste_packages` in the file), give it the inventory, say how
the packages fail, and draw its release into a compartment.

| Setting | What it is |
|---|---|
| **Inventory** (per nuclide) | What the packages hold at the start — the total over all of them, in the model's inventory unit |
| **Instant release fraction** (per nuclide) | The share of a failed package's inventory that is in the water at once — the gap and grain-boundary inventory of spent fuel, the part that is not bound in the matrix. The rest waits for the matrix |
| **Packages fail** | *never* · *all at one time* · *evenly over a window* · *at a constant rate* · *Weibull* — with only the settings that way reads shown: a time, a window, a start and a rate, or a start, a scale and a shape |
| **Matrix degradation rate** | The fraction of the exposed waste form dissolving per unit time, which carries everything bound in it out **congruently** — every nuclide in proportion to what the matrix holds |
| **Packages** | How many the block stands for; for the reader |
| **Handle decay and ingrowth** | On by default: the chain runs inside the packages too, so a daughter grown in inside an intact canister is there to be released when it fails |

**When the packages fail is usually uncertain**, and each of these settings
carries a **±** button that gives it a distribution — see
[A spread on something that is not a parameter](#a-spread-on-something-that-is-not-a-parameter).
*Packages fail* itself does not: Weibull and the constant rate are already
distributions, over the packages.

Behind the block are two inventories per nuclide, *intact* and *exposed*,
which the solver integrates with everything else and which appear as series
(`Canisters intact [Cs-137]`, `Canisters exposed [Cs-137]`); the block's own
value is the **release** — `Canisters [Cs-137]` in the picker and in any
equation — which is what the line drawn out of it carries:

```
intact   dP/dt = −h(t)·P              + decay and ingrowth
exposed  dM/dt = +h(t)·P·(1 − irf) − d(t)·M   + decay and ingrowth
release  R(t)  =  h(t)·P·irf       + d(t)·M
```

`h(t)` is the failure *hazard* — the fraction of the still-intact packages
failing per unit time — which is how a failure distribution multiplies an
inventory that is also decaying. Each way of failing has a closed form for it:
1/(t_to − t) for the window (so the fraction failed rises in a straight line),
a constant for the constant rate, `(k/η)((t − t₀)/η)^(k−1)` for the Weibull
(rising with age above a shape of 1, the corrosion form). **All at one time**
is not a rate at all: at that time the intact inventory moves to the exposed
waste form and the instant-release part goes straight into the release target,
as a jump between two segments of the integration. The times a block names are
corners the solver lands on exactly, without being written into the switch
times as well.

What is not in the block is solubility. The release goes into an ordinary
near-field compartment and the limit sits on the transfer out of it,
as an [availability](#availability-solubility-limits-and-sorption-isotherms) —
with the molar sharing an element's isotopes need — where it can be seen and
where erosion can ignore it. With the mass-balance audit on, the inventories
inside the packages are counted with the compartments, so a release into the
near field is a move and a release drawn to nowhere is counted as *out*. The
analytic Jacobian covers the block: the release is differentiated through both
inventories, and through the instant-release fraction and the degradation rate
when those follow the state. Only a *failure* setting that follows the state —
a window that closes when a compartment fills — makes it decline, and then the
run says so and differences instead.

`examples/waste-packages.json` is 4,500 canisters failing by a Weibull after
year 1,000 into a near field, a geosphere and a biosphere; switch the audit on
under SIMULATION to watch the bookkeeping close.

## Events

An assessment is not only slow processes. An earthquake breaches canisters; a
glacier scrapes the soil off a landscape object; a well is drilled through the
repository. **Event** (canvas menu → *Other blocks*; `events`
in the file) is something that happens to the model at an instant:

| | |
|---|---|
| **Happens** | *at a time* — an equation that comes to a number before the run, so a parameter with a distribution draws it per realisation — or *at random, at a rate*, a Poisson process between **From** and **Until** (the whole run when blank) |
| **Does** | any number of actions, each a share of something: **fail a share of the packages in** a waste-package block (their inventory moves to the exposed waste form, the instant-release part goes wherever the block's release goes), or **move a share of** a compartment to another compartment or out of the model |
| **Draw the occurrences** | on by default: each probabilistic realisation draws its own occurrence times. Off, every realisation keeps the expected-value form below |

Its own value is the **number of occurrences so far**, charted under the
block's name — and there are two readings of a random event, both right. **A
deterministic run has no dice**: a Poisson event at rate λ that fails a share *f*
is read in its *expected-value* form, a hazard *f·λ* added to the waste block's
own, a first-order transfer *f·λ* for a move, and the count is ∫λ dt over the
window. **A probabilistic realisation samples**: its occurrence times come from
a stream keyed by the run's seed, the block's name and the realisation's
number — so a replay reproduces them and two events are independent — and the
actions are applied as jumps at those times with the expected-value terms
switched off, so nothing is counted twice; the count is then a staircase. A
timed event is a jump in both. A model whose only randomness is such an event
can still be run probabilistically; a tornado swings parameters and never
draws events.

Each occurrence is a corner the solver lands on, and the jump is applied to the
state between two segments, so the row *at* the corner is the state before it.
With the mass-balance audit on, a move into another compartment is a move and a
move out of the model is counted *out*. The analytic Jacobian covers the block;
a rate or a window that follows the state declines it.

`examples/waste-packages.json` has an earthquake that fails 5 % of the canisters
at 2 × 10⁻⁵ a year and a glaciation at 100,000 years that strips 80 % of the
biosphere: run it, then run it probabilistically and compare the staircase of
`Quake` with its expected line.

## Models with no compartments

Not every model integrates anything. A great many Ecolego projects — 15 of the
71 real ones tested here — have **no compartments at all**: they take a release
computed elsewhere, or a measured series, and work out a concentration and a
dose from it. There is nothing to solve, so nothing is solved: the blocks are
evaluated over the output grid, in dependency order, with the same clock a
solved model would see.

```json
{
  "simulation": { "start_time": 0, "end_time": 12000, "output_points": 300 },
  "lookups":     [{ "name": "Release", "points": [[0, 0], [6000, 4e6]] }],
  "parameters":  [{ "name": "Dilution", "value": 5e5 }],
  "expressions": [{ "name": "Conc", "equation": "Release / Dilution" }]
}
```

Everything the algebraic side can do still works — index lists, lookup tables,
reductions, sub-systems, `time()` — because it is the same generated function,
called on a grid instead of by a solver. What is absent is absent honestly: the
footer says **evaluated · no compartments — algebraic blocks only** rather than
naming a solver, and reports no step count and no Jacobian, since none of the
three exists. `Results.stats.integrated` is `false`.

**A model with neither compartments nor expressions runs too**, and so does one
with nothing in it at all. It used to be refused, on the grounds that an empty
chart looks like a fault in the program — but that made emptying a model, or
starting one from nothing, report a fault in the *file*, which is worse. So the
run produces the time grid and whatever constants the model carries, the footer
says **evaluated · nothing to work out — the output grid only**, and the Chart
and Table tabs say what is missing and offer the Build view. An empty diagram
says it too, with a button that adds the first compartment.

## A distribution on a parameter

A parameter in a real assessment is rarely just a number. It is a number *and*
the distribution it was drawn from, and Ecolego keeps both — per index, because
a sorption coefficient has one distribution per nuclide per material, not one
for the block. model B carries 644 of them; of the 302 model files
tested against, 112 have at least one.

**Every parameter has one**, whether or not it is indexed, and there are two
ways to it. In the left panel each parameter's row ends in a small curve — faint
where there is no distribution, coloured where there is, with the whole thing in
its tooltip — and clicking it opens the editor. In the block's settings the same
thing is a **Distribution** row under the value. Either is the whole story for a
parameter with no index list.

An indexed parameter has the same row — labelled **Distribution (default)** —
*and* a **distribution** column in its per-index grid. The two work the way the
values above them do: the row is what every index uses, and a cell overrides it
for that index alone. A cell showing the default in grey is inheriting it; one
in ordinary ink has its own. Clicking either opens the editor, and the `×` at
the end of a row clears the override and puts the index back on the default.

A cell says what is there — *"Log-triangular: min 0.7, max 20, mode 3"* — and
the full text is in its tooltip when the column is too narrow for it.

**The chart is the point of the editor.** Three numbers are not a shape until
they are drawn, and the mistakes they invite are invisible on a form and
obvious on a curve: a most-likely value outside the range, a truncation that
removes nearly all the probability, a geometric standard deviation of 1.05
where 5 was meant. The curve is redrawn as you type. A log-scaled kind gets a
logarithmic axis with a tick per decade, because a log-triangular over five
decades drawn on a linear axis is a spike beside a flat line and tells you
nothing.

Eleven shapes: the nine the corpus uses, and skbrnt's two double triangulars:

| | |
|---|---|
| **Uniform** | every value between the ends equally likely |
| **Triangular** | a rise to the most likely value and a fall away from it |
| **Double-triangular** | two triangles meeting at the most likely value, each holding half the probability — so that value is the median too. skbrnt's `dtriang`, which SKB's SFK data uses for release fractions; its density steps at the mode unless the mode is the middle of the range |
| **Normal** | the bell curve |
| **Log-uniform** | uniform in the logarithm — every decade equally likely |
| **Log-triangular** | a triangle in the logarithm, and the commonest here by far |
| **Log-double-triangular** | the same in the logarithm: skbrnt's `logdt`, which SKB's SFK data uses for diffusivities |
| **Log-normal (geometric)** | a geometric mean and a geometric SD: "a factor of three either way" |
| **Log-normal (mean, SD)** | the same curve from the ordinary mean and standard deviation |
| **Log-normal (two quantiles)** | fitted through two points you know — "5% below this, 95% below that" |
| **List of values** | not a curve but values sampled elsewhere, one per realisation |

Any of them can be **truncated** above, below or both. Truncation cuts the
drawing as well as the density and what is left is scaled back up, so the chart
shows the distribution you would actually sample rather than the one you
started from.

Two things the editor will tell you that nothing else would. A shape that
cannot exist — *"The most likely value is above the maximum"* — and, more
usefully, a parameter whose own value sits outside its own distribution: a
deterministic run uses that value and a probabilistic one would never draw it,
which is the sort of disagreement that survives a long time unnoticed.

Distributions are read from imported files, kept on the model, shown, editable
and written back in the same spelling — `logt(min=0.7,max=20,mode=3)` — so a
model that arrives with 644 of them leaves with 644 of them. A deterministic run
ignores them and uses the value beside each; the next section is what they are
for.

### A spread on something that is not a parameter

Plenty of the numbers that matter are not parameters. When the packages fail,
how fast the waste form dissolves, how often an event happens, how long the
water takes to travel a far-field path, what a compartment starts with — each of
those is a setting on its own block, and a setting is an equation with nowhere
to keep a distribution.

So every one of those settings has a **±** button beside its box. Press it and
you get the same distribution editor; save a distribution and the setting
becomes a parameter of its own, carrying the value it had, with the setting
pointing at it by name:

```
Weibull scale   [ 20000            ] ±        →    Weibull scale   [ Canisters_fail_scale ] ±
                                                   Uniform: min 5000, max 40000,
                                                   sampled as Canisters_fail_scale.
```

That is the whole mechanism, and it is deliberate: afterwards there is nothing
unusual about the model. The spread is on an ordinary parameter, so it appears
in the **Probabilistic…** dialog, in *What drove the spread*, in the tornado
and in `dy/dp` immediately — and the bar in the tornado plot has a name on it,
which is what makes the plot readable.

The button is filled in when a spread is set, and opening it again edits that
distribution rather than making a second one. Clearing the distribution puts the
value back in the box and removes the parameter, unless something else has come
to read it — a parameter you wired up yourself is yours.

**A setting has to be a number, or a reference to one parameter.** `2 *
canister_life` is arithmetic over something that may already be uncertain, and
replacing it with a parameter would throw the arithmetic away; the button says
so rather than doing it. Give the quantity a parameter of its own first and put
the spread on that.

**The mode selectors have no ±**, and that is not an oversight. *Packages fail:
Weibull* and *Happens: at random, at a rate* are already distributions — over
the packages, and over the occurrences within one run. They are choices rather
than numbers, and a second distribution on top of one would be a different
quantity than anyone means. The settings underneath them — the scale, the shape,
the rate, the start — are numbers, and they all take one.

## A probabilistic run

Give the parameters distributions and the model can be integrated once per
**realisation**, drawing a value for each of them every time. What comes back
is not a curve but a band: at every output time, where the outcomes were.

**Uncertainty → Probabilistic…** under Simulation opens it. The button is there
only when something in the model has a distribution, because a thousand runs of
a model with none is a thousand identical answers.

**To see it work, open `examples/biosphere.json`.** Fifteen of its parameters
carry distributions: the four leach rates and the four sorption coefficients
log-triangular a factor of ten either way, the geosphere and soil rates the
same, the well and intake figures triangular, the soil density normal. The
ICRP dose coefficients are deliberately left fixed, because that is how an
assessment treats them — a model where *everything* is distributed would
misrepresent the method. Run it once, then **Probabilistic…**, and at a million
years the leach rate turns out to explain almost the whole spread with a rank
correlation of −1.00: a faster release emptied the repository earlier, so less
of it is left to arrive now.

**It uses the machine's cores.** A thousand realisations are a thousand
independent integrations, and they are shared over as many workers as there are
cores, less one — that one is left for the interface, so the page keeps
answering while it runs. The notice at the end says how many were used, and the
estimate before it starts is divided by them.

The answer does not depend on how many cores there are: the same model with the
same seed gives *identical* numbers on one core and on sixteen, to the last
bit. That is not a happy accident. Latin hypercube sampling is a statement
about the whole set of realisations, so every worker draws the entire design
from the seed and integrates only the ones that are its own, and the results are
put back in realisation order rather than in the order they arrive. There is a
test.

Two cases run on one thread instead, and both are deliberate: a browser that
will not let a worker start workers (Safari before 16.4), and a model whose
*build* dwarfs its solve — every worker builds the model for itself, so a
handful of realisations of a model that takes a minute to build is slower on
eight cores than on one. `?workers=1` in the address forces the single-threaded
path, and `?workers=4` caps it, which is the way to measure what it is worth on
your own machine and to leave room for other work.

**It says what it will cost before it starts.** How many values will be drawn
and from what, how many realisations of how many series, how much memory the
result takes, and — measured from the run you have already done, not guessed —
roughly how long it will take. An imported assessment says 1,000 realisations
and takes 50 seconds for one integration, which is fourteen hours; that is
worth knowing before pressing anything rather than after. A result that will
not fit is refused rather than attempted.

**The numbers come from the model.** Ecolego keeps its own `no-simulations`,
`sampling` and `seed`, and an imported model arrives with all three — 1,000
realisations, Latin hypercube and a seed, in every assessment model tested
against. Reading them does *not* make **Run** probabilistic: Run stays the
deterministic run it has always been, and a probabilistic one is started from
its own dialog.

**Keep only the endpoints, and where those are decided.** Holding every series
of every realisation is what makes a probabilistic run expensive — an imported
assessment can be 831,314 series — and an assessment already knows which forty
blocks it is about. That list is the model's **endpoints**, and the tick box in
this dialog is whether to keep those and nothing else.

**Choose blocks…** beside it is where the list itself is set: one row per block
the run produced, ticked, with a search box. A block brings every index of it —
tick `Dose` and all four nuclides of it are kept — because picking series one at
a time is not a thing a dialog can offer. What you tick is saved with the model,
so it travels with the project file and the next run starts where the last one
left off. An imported `.eco` arrives with its own list, which is what the dialog
opens on.

The same picker is reached from **Save → Model with results**, and on the Table tab's
right-click menu where it also writes the chosen blocks out as CSV or HDF5.

**It needs no run.** The blocks it offers come from the model — what a run
*would* report is a function of the layout, and the layout exists as soon as
the model builds. That is the point: deciding what a run should keep is
something to do before it has kept 831,314 series, not after. The cost line in
the probabilistic dialog follows from the same list, so it prices the run
before the run.

**A run is a function of its seed.** The same seed and the same model give the
same realisations, on any machine — which is what makes a probabilistic result
something you can quote and somebody else can check. Change the seed to see
whether an answer was luck.

**Latin hypercube** is the default. Each distribution is cut into as many
equal slices as there are realisations and one value is drawn from each,
shuffled — so the range is covered evenly instead of leaving the clumps and
gaps that independent draws leave. Over 200 realisations it reaches every
slice where independent draws reach about 60% of them, which is why a tail
turns up in hundreds of runs rather than thousands.

**The Chart and the Table say what they are showing.** A line in the corner of
each: *Nothing has run yet*, *One deterministic run · 59 series over 400 times*,
*150 realisations · as a median with its spread behind it*, or *Realisation 734
of the probabilistic run, integrated again on its own values*. A chart of five
curves and a chart of five medians with their spread behind them look alike
from across a desk, and which of them it is changes what every line on it
means. Where a model carries distributions but has only been run
deterministically, the line says so too — a probabilistic run is the thing
nobody knows is available until it is offered.

**The Chart has two pictures of one selection.** *Show* beside the picker
chooses between them, and it is there only once there are realisations to
choose about:

- **over time** — the bands described below, with two controls beside them for
  what the line is and what is drawn behind it.
- **distribution** — each selected series as a histogram of its realisations at
  one time, with the time beside the control. This is the picture for a
  quantity that does not move: a sampled parameter is one number per
  realisation, and a band across the page says only that it is flat.
- **scatter** — the selection plotted against one of its own members, one point
  per realisation. This is the picture for how two quantities move *together*,
  which neither of the others can show.

**Draw** above them chooses the arrangement, once there is more than one
series to arrange. *All in one* is the default: the series ticked together are
usually the same quantity, and comparing them is why they were ticked together.
They are drawn as outlines over a shared axis in the chart's own colours, and
the picture takes the space the time chart would have had. The shared axis is
built on the *bodies* of the samples (1st to 99th percentile), because one
series' smallest realisation can be forty decades below another's and an axis
that reaches it puts everything in the last bin.

*One panel each* gives every series its own scale, which is the honest picture
when they are different quantities — and the only one when the units differ,
which the overlay says out loud. Under each panel: the median, the 5–95% range
and how many realisations it is drawn from.

**Bins** beside the picture is how many, and how they are spaced. Both change
what shape a sample appears to have, which is why neither is decided for you:

- **how many** — leave it empty for the rule. A panel of its own gets Sturges'
  (about eleven bins for a thousand realisations); the shared axis gets a finer
  count, because outlines over one another read as curves and a curve wants
  more than eleven steps. Type a number between 2 and 200 for your own.
- **auto / linear / logarithmic** — what the bin *edges* are spaced by.
  *Auto* uses the logarithm where the sample is positive and spans more than
  two decades, judged on the body of it rather than its extremes: a dose over a
  thousand realisations on an even spacing is one tall bin and a tail nobody can
  see. *Linear* and *logarithmic* overrule that. A sample that reaches zero has
  no logarithm to bin by, so that request falls back to even spacing and the
  line under the picture says it did.

The line under the picture always says what it was binned into, so a histogram
copied into a report can be described.

### Scatter

**Show ▸ scatter** plots the selection against one of its own members: the
series beside the mode control goes across the bottom, the rest go up the side,
and every point is one realisation at the chosen time. It is the only one of
the three pictures where the *shape* of a relationship is visible rather than a
number standing for it — *What drove the spread* reports a rank correlation of
0.91, and this says whether the 0.91 is a line, a curve, a fan, or two clusters
with nothing between them.

**regression** draws a least-squares line through each set of points, with its
equation and R² underneath. The fit is on what is *drawn*: with both axes
logarithmic — which they are by default when the samples span decades — it is
the fit to the logarithms, so a power law comes out straight and the equation
reads `y = 3.2·x^1.4`; on linear axes it is the ordinary fit and reads
`y = 3.2 + 1.4·x`. The two are different claims, which is why the equation says
which one it is. R² is of the line as drawn, so a curve fitted straight reports
the poor number it deserves.

Pairs that cannot be drawn — a zero or a negative under a logarithm — are left
out of the fit and counted beside it. *All in one* and *one panel each* work
here as they do for the distributions: one set of axes for everything, or a
panel each so a small series is not flattened against a large one.

**A run of nothing but parameters opens as a distribution.** When everything
selected is a quantity that does not vary over time, the second picture is the
only one that says anything, so it is the one the tab opens on. Choose *over
time* and it stays chosen.

### What the lines are, and what is behind them

Beside *over time*, three tick boxes and a select:

| the lines | |
|---|---|
| **median** | the middle of the realisations. On by default, and what an assessment quotes. |
| **mean** | their average. For a skewed output — a dose is one — the two are far apart. |
| **own run** | the deterministic run: the model at its own values, with no band. |

Any combination. They are not alternatives — how far a skewed output's mean sits
above its median, and where the one run the model's own values give falls among
the thousand, are questions about two lines at once. The last one on cannot be
turned off.

All three wear the **output's** colour and are told apart by their pattern —
solid, dashed, dotted. Colour is which series a line is of; the pattern is which
line of it.

| behind it | |
|---|---|
| **percentile bands** | the pairs the run was asked for, outermost faintest. |
| **standard error** | how well the *line itself* is known, which narrows as the sample grows. |
| **standard deviation** | where the *realisations* are, which does not narrow however many are run. |
| **no spread** | a bare line. |

The last two are about whichever line you chose, and they are not the same
numbers for both — so the select renames them as you switch.

For the **mean** they are the textbook pair: ± 1.96 standard errors, and ± one
standard deviation.

For the **median** neither exists in that form. A standard error is the
deviation over the root of the count because the mean of a sample is a sum; the
median is not, and its error is `1 / (2·f(m)·√n)`, which wants the density of
the output at its own median. So both are read off the sorted realisations
instead: *standard error of the median* is the interval between the ranks
`n/2 ∓ 0.98√n`, which is the distribution-free 95% interval for a median, and
*middle 68% of realisations* is the pair of ranks at 16% and 84% — what ± one
standard deviation would be if the output were normal.

Both of the median's come out **lopsided**, and that is the point: a dose whose
logarithm is normal has far more room above its median than below it, and the
same number either side would say otherwise. The corner of the Chart says which
of the six you are looking at.

**Pressing Run once with a sample on screen** shows that one run: the tab goes
back to the curves and *own run* is ticked. The other lines are left as they
were, so the single run appears among them rather than in place of them. The
sample is kept — a thousand integrations is not something to discard because you
wanted to see one.

### Truncating a distribution

Any shape can be cut, and there are two ways to say where. **Truncate below /
above** are the values: *nothing below 0.005 came out of this*. **Truncate
below / above percentile** are the fractions of this curve's own probability:
*the bottom and top 5% did not*. The second cuts wherever the numbers above it
put it, which is how a data set that fixes the same tail fraction for a
thousand element-specific distributions writes it — the values differ in every
one of them and the rule does not.

Both may be set, and then the part inside all four is what is drawn from. A
percentile is a probability, so it is `0.05`, not `5`; the dialog says so if
you type the other one. Truncation is done by reading the same curve between
two probabilities rather than by drawing until something lands inside, which is
why a distribution truncated to its own tail still starts a run.

### Inputs that move together

A distribution may name a **group**. Every input in one group shares a single
underlying sample: they are not two draws that happen to agree, they are one
draw used in several places — one element's concentration ratio quoted for four
ecosystems, say. Members with the *same* shape get the identical number in
every realisation; members with different shapes share the rank, which is what
full correlation means when the curves differ.

A group is a correlation of one, so it beats an ordinary correlation: a pair
naming a grouped input is ignored and the run says so.

### A distribution at one point of a lookup table

A lookup table is a curve, not a number, and a data set that knows how
uncertain a quantity is usually knows it at the years it was measured. So a
**point** may carry its own distribution: a release fraction triangular on
62–1911 at year 0 and on 1–23 at year 8700 is two spreads of one quantity, not
one spread of two.

Each such point is a sampled input of its own, named for the time it sits at —
`SRF@0`, `SRF@8700` — and appears that way in *What drove it* and in the
Probabilistic dialog's plan. Between them the curve is interpolated as always,
so a realisation is a whole table drawn from the point spreads. Put them in the
same **group** and the curve keeps its shape while scaling as one; leave them
ungrouped and each point moves on its own.

The deterministic run is untouched: a point starts at the value the model holds.
In a project file a point with a spread is `[time, value, pdf]` rather than
`[time, value]`.

### Using somebody else's sample

Some data is not a distribution at all. A near-field release rate is the output
of a thousand runs of another model, and what this model wants is those
thousand curves — not a shape fitted to them. **Import…** reads them.

A **parameter** takes a column of numbers, one per realisation, used in the
order they are written. Realisation 1 gets the first, realisation 2 the second,
and a run therefore reproduces the one the numbers came from rather than
resembling it. In HDF5 such a dataset says so:
`pdf: {"type": "raw", "include_deterministic": true}` — and with that flag the
*first* value is the deterministic one, the one the model runs at, with the
sample beginning after it.

A **lookup table** takes a matrix: one row per time and one column per
realisation, beside a `/time` dataset saying what the rows are. Each point of
the table gets that row as its own sample, and because every point is read at
the same realisation number, realisation 17 is column 17 all the way along —
the curve stays whole. With no deterministic column, the middle of the sample
stands in for the deterministic run.

These files are large — a thousand realisations over four hundred times is four
hundred thousand numbers for one series — so the import says how many values it
would bring before it brings them, and only the rows that match a block in your
model land.

Such a sample shows up like any other uncertainty: each point is a sampled
input named for its time in *What drove it*, and the chart draws the spread the
way it draws any other.

### Being rid of a sample

A sample lasts until the model changes. Any edit that the model's numbers depend
on — widening a distribution, changing a shape, adding a block — makes every
realisation a realisation of a model that no longer exists, and the bands, the
histograms and *What drove it…* go with it. Run it again to get them back.

To be rid of one before that, **Discard sample** — beside the line that says
what ran, on both the Chart and the Table, and in the Probabilistic dialog. It
throws away the realisations and the megabytes they are held in without touching
the model.

**On the chart**, a series that was part of the run is drawn as its median with
two bands behind it: 25–75 and 5–95 unless the model says otherwise. **Analyse ▾
→ Bands…** sets the pairs — `1–99, 10–90`, or a set of six — and can draw the
**mean** as a dashed line beside the median. The line is the median of the
realisations, not the deterministic run — a band around one curve with a line
from another would be two pictures overlaid; and for a skewed output the mean
sits well above the median, which is exactly why it is worth seeing both. The
choice is saved with the model and redrawn at once from the realisations the
worker still holds.

**Saving a probabilistic result.** *Choose endpoints to save…* has a **HDF5
holds** row once a probabilistic run stands behind the series, with four things
the file can be:

| | What is written |
|---|---|
| **The deterministic run** | The values the model holds, with no sampling. What this button has always written, and still the default. |
| **The mean of N realisations** | One curve: the average of the runs at each time. |
| **All N realisations** | The sample itself — one row per output time, one column per realisation. |
| **One realisation** | One curve: that run, exactly as it was integrated. Give its number. |

It is asked rather than assumed because the answers are not close to one
another. On `examples/biosphere.json` the mean of a thousand doses ends up **81
times** the deterministic run: a dose is a skewed quantity, so its average sits
far above the curve at the central parameter values, and a file that did not say
which of the two it held would be quietly unusable. Every file says — the mean
and single-realisation files carry `realisation` and `n_iter` attributes, and
the deterministic one carries neither. CSV always writes the deterministic
values, and says so.

Right-click the table for the quick version: **Export table to HDF5** for the
curve, **Export realisations to HDF5** for the sample — and **Open in the HDF5
browser** or **Open every output in the HDF5 browser** to send either straight
to the reader without saving a file. The whole run is the usual thing to want
there: a reader is opened to look around in, which is exactly when you want
more than the four lines you happened to chart.

**Or open it in the reader without saving it at all.** *Open in browser* in the
endpoints picker — and **Open in the HDF5 browser** on the table's menu — opens
the result browser at kvotab.se in a new tab and hands it the file directly. No
download, nothing to find in a downloads folder afterwards, and nothing left
behind when the tab is closed. It writes whatever **HDF5 holds** is set to, so
the realisations can go across the same way.

A pop-up blocker will stop the tab opening; allow pop-ups for this page and try
again. The reader also has to be told to accept files from wherever this page is
served — it only accepts its own origin until it is told otherwise — so if the
tab opens and nothing arrives, that is what to check. Use `?rb=<address>` to
point it at a different copy of the reader.

The realisation file is the shape Ecolego writes, and the result browser at
kvotab.se opens it as one: it draws the mean of the runs, will put a confidence
band around it, and can pick out a single realisation — none of which would be
possible from a file holding only quantiles, which is why the runs themselves
are what is stored. Series that were not part of the probabilistic run keep
their single curve in the same file and say so.

**Only the sample is a large file, and it says so before it writes one.** A
realisation matrix is as many times the size of a series as there were
realisations: four dose series over four hundred times, a thousand times over,
is 6.4 MB — and fifty series is 80. The values are written as float32, which
halves that and is still far finer than a Monte Carlo sample of a thousand draws
can justify. A mean or a single realisation is one curve, so those files are the
size of an ordinary export — 26 kB against 1.2 MB for the same four series.

What a model can say and this cannot yet do: **correlated sampling**. An
assessment often ties two parameters together — model B correlates
210 pairs — and this tool draws each one independently, so its spread is wider
than Ecolego's. The import says so when a model carries a correlation matrix.

## Partial sampling: what one input is worth

A correlation ranks what the sample happens to show. It cannot answer *how much
of this spread is that one parameter* — for that you need the same run twice,
once with the input varying and once with it held.

**Vary only some** in the Probabilistic dialog does that. Tick the inputs that
should vary; the rest stay at the value the model holds. The difference between
the two bands is the input.

It works because **a parameter's draws do not depend on what else is sampled**.
Each sampled input has a stream of its own, seeded from the run's seed and the
input's name, so:

- a partial run gives every varying input *exactly* the numbers it took in the
  full run — the two are comparable, not two experiments;
- adding a distribution to one parameter leaves every other parameter's sample
  untouched. The same seed on a model that has gained an input answers the same
  for every input it already had, which is what lets a run be repeated after a
  review;
- two indices of one parameter — `Kd[Tc-99]` and `Kd[I-129]` — draw
  independently, because they are two quantities that share a spelling.

The realisation count, the seed and the choice of what varies are all saved with
the model, so a comparison can be repeated next year.

## Correlated inputs

Two sampled inputs are independent unless the model says otherwise, and in an
assessment they often are not: the sorption coefficient of one element in three
compartments was fitted from the same experiments, and a run that draws the
three independently produces realisations — high in the backfill, low in the
rock — that nobody believes. **Correlate inputs** in the Probabilistic dialog is
where the model says so.

Two forms. A **pair** names two sampled inputs and a coefficient: `Kd[Tc-99]`
with `Kd[I-129]` at 0.8. A **group** names a parameter and correlates every one
of its sampled indices with every other — the Kd of one element across every
compartment it is in, which as pairs would be 1,176 lines for a list of 49.
Both are saved with the model:

```json
"correlations": [
  { "a": "Kd[Tc-99]", "b": "Kd[I-129]", "r": 0.8 },
  { "group": "Kd", "r": 0.9 }
]
```

The coefficients are **rank** correlations — Spearman's — and they are imposed
by the method every risk tool uses for a Latin hypercube sample, Iman and
Conover's: the values each input was going to take are *reordered* so that the
inputs' ranks correlate as asked. Nothing about any one input changes — the same
strata, the same values, the same distribution — only which realisation gets
which. Two things follow, and both are tested. Every input outside a pair takes
*exactly* the draws it takes with no correlation in the model at all, so adding
one does not move the rest of the sample; and the design comes out the same on
one core and on sixteen, as it always did.

A set of coefficients no real inputs could have — A with B at 0.9, B with C at
0.9, A with C at −0.9 — is not refused: it is moved to the nearest set that is
achievable, and the notice after the run says how far it had to move. An input
held by *Vary only some* takes no part, since a column of one value has no
ranks to arrange.

## What drove the spread

A probabilistic run says how uncertain an answer is. **What drove it…**, beside
the probabilistic button once a run has finished, says *because of what*.

It correlates every sampled input against one output, at every output time,
using the realisations already drawn — no further runs. This is the standard
method, and the one an assessment usually reports.

**Two pickers decide which answer you are looking at.** *Of* is the series —
it opens on the first line charted, which is the one in front of you, and the
list offers every series the run kept. *At* is the output time the table is
for. Either one asks the sample again and answers in place: the coefficients
are a pass over realisations that are already in memory, so changing them costs
nothing and no dialog stacks up behind.

*Of* can only offer what the run **kept**. If *Keep only the N endpoints* was
ticked when it ran, that is the endpoint list and nothing else — ask about a
line outside it and this opens on the first endpoint instead and says so. To
widen the choice, run again with the box clear, or add the line to the endpoint
list (**Choose endpoints to save…**, in the table's right-click menu). On a
model with more series than the list will hold, chart the one you want and open
this again.

**Two coefficients, and the difference between them means something.**
*Spearman* is a rank correlation and finds any relationship where more of the
input reliably gives more (or less) of the output. *Pearson* finds only a
straight-line one. The table is ranked by Spearman, because the normal case
here is monotone and bent — a log-triangular sorption coefficient driving a
dose through four compartments is nothing like a straight line, and ranking by
Pearson would put a genuinely important input below a coincidentally straight
one. Where the two disagree, the relationship is curved; that is information,
not a warning.

A coefficient near **+1** means the output rises with the input, near **−1**
that it falls, and near **0** that this input does not reach the output at all
— which is worth knowing too: a parameter with a carefully chosen distribution
that turns out to correlate with nothing is either irrelevant or not connected
the way you thought.

**The chart above the table is the part a single number cannot say.** Which
input matters changes with time: a release rate governs the first century and a
sorption coefficient the next ten thousand years. The curves show each of the
top few against time, always on the full −1 to +1 scale so a weak correlation
cannot be made to look strong by rescaling.

**The other five statistics an assessment usually quotes are in the table
too**, for the time the table is showing. **SRC**, the standardized regression
coefficient, is this input's own share of the output's movement *given the
others*, from one regression of the output on every input at once; **PCC**,
the partial correlation, is what is left of the relationship once the other
inputs' linear effects are removed from both. Where the inputs are independent
the two say much what the correlations say; where inputs are correlated — the
case the section above exists for — they are the ones that mean anything,
because a correlation cannot tell an input that drives the output from one
that merely moves with another that does.

**b** beside them is the same coefficient without the standardising: how much
the output moves per unit of this input, with the others held. SRC is the one
to compare *between* inputs — which is why the table is ranked by it — and `b`
is the one to read against what the input actually is, since it is in the
model's own units.

**Translate** is what the regression is fitted to, and it is the control that
decides whether any of these numbers mean anything:

| | |
|---|---|
| **nothing — the values** | As the run drew them. `b` is in units; the fit is a straight line through the model's own arithmetic. |
| **ranks** | Each input and the output replaced by their ranks, giving **SRRC** and **PRCC**. The reading for a relationship that is monotone and bent — which a log-triangular sorption coefficient driving a dose through four compartments is. |
| **logarithms** | The logarithm of each input and of the output. A power law `y = a·xᵇ` is a straight line in logs, so the fit finds it and `b` becomes an **elasticity**: a percentage in the output per percentage in the input. |

On the bundled biosphere example at its peak, the three answers to the same
question are R² = 0.85 on the values, 0.96 on ranks and 0.98 on logarithms,
where `b` for the leach rate reads −1.5e+9 Bq per unit on the values and 0.87
on logarithms. The second number is the one anybody can use.

A logarithm needs a positive number, so realisations where an input or the
output is zero or negative are left out and the line underneath says how many.
Spearman is a rank correlation already and does not move whatever is chosen
here.

The **R²** line says what share of the spread a linear fit to every input
explains at all — a low R² with high rank coefficients is a model that is
monotone and far from linear, and a low R² with low everything is a model whose
spread comes from interactions no one-input statistic can see.

**At** picks the time the table is about, and its first entry is **where it
peaks on average** — the output time at which this series is largest averaged
over the realisations, which is the time a reader means by "at the peak" and
cannot pick out of a list of four hundred. It is the mean over the
realisations, not the largest single one, and it follows the output: change
*Of* and it finds the new series' peak rather than staying at the old one's
time. Screened-out realisations do not count toward it.

**S₁**, the first-order index, is the share of the output's variance that
knowing this one input alone would remove, and it finds a relationship of *any*
shape — an output that peaks in the middle of an input's range has a
correlation of nothing and an S₁ of a lot. It is estimated by binning the
input, with the noise that binning adds subtracted, so an input that does
nothing reads near zero rather than as a small number that looks like
something.

None of this costs a run. The regression is one inverse of a matrix as wide as
the number of inputs plus one; on the largest assessment here, 617 of them,
that is under a second, and it is done for the time on screen rather than for
all four hundred.

## Categories of realisation

A band says how uncertain the dose is. The question after it is *what do the
bad realisations have in common*, and a band has already averaged that away.
**Analyse ▾ → Categories of realisation…** sorts them: a category is a label and
a condition over one series the run kept — its **peak**, its **lowest value**,
its **value at the end** or **at a time**, compared with a number — and every
realisation belongs to the first category in the list whose condition it
meets. What meets none is **Other**. The count and share beside each row is
live while a run stands.

Untick a category's **Include** box and it is screened out of everything: the
bands, the mean, *What drove it*, the distribution summary. The legend says so
— *412 of 1,000 realisations shown (categories)* — so a band over a chosen
subset cannot be mistaken for the run. Screening is the way to ask "among the
realisations where the canister failed early, what drove the dose", which is a
different question from "what drove the dose" and often has a different
answer.

The categories are saved with the model, as the seed is; the membership is
worked out from whichever run stands. A category that names a series the run
did not keep is empty and says so.

## The distribution of one output

**Analyse ▾ → Distribution summary…** is one series at one time as a
distribution: a histogram, the cumulative curve, and the numbers a band cannot
give — the mean with its 95% bounds, standard deviation, skewness, excess
kurtosis, the count, a percentile table from the 1st to the 99th, and a
calculator that turns a value into the probability of exceeding it and a
percentile into a value, answered from the realisations already on the page.
The **tail expectation** is the mean of the realisations above a chosen
percentile — not where the tail starts but how heavy it is, which is the number
a regulator asks for after the 95th percentile.

The shaded band on the cumulative curve is the Dvoretzky–Kiefer–Wolfowitz 95%
band: with N realisations no probability read off the curve is closer than
±√(ln 40 / 2N) to the truth, *whatever the shape*. At a thousand realisations
that is ±4.3%, which is worth knowing before quoting a 99th percentile. The
bounds on the mean are the usual normal-approximation ones and are honest only
when N is large; the band is honest always.

## Tornado

**Analyse ▾ → Tornado…** asks the model what a sample asks a sample: hold every
input at the model's own value, move one to its 5th and then its 95th
percentile, and see what the output does; then the next input. That is 2K+1
runs for K sampled inputs — one central run shared — through the same pool of
cores as a probabilistic run, priced the same way before it starts. The result
is a bar per input from the low-input output to the high-input output, ranked
by the swing, with the central value marked; a red bar is an input whose high
end *lowers* the output. **Of**, the reading (peak, end, lowest, at a time)
and the time can be changed without running anything again.

It needs no sample, finds no interactions, and is the chart to draw when the
distributions are not yet trusted enough to sample from — or when the question
is which of six hundred inputs to bother giving a distribution at all. The
percentiles swung to are saved with the model.

## Replaying one realisation

**Analyse ▾ → Replay a realisation…** runs one realisation of the probabilistic
run again as an ordinary run — every series of it, not only the ones the band
kept — and puts it on the chart and in the table in place of the deterministic
run. The status line says which it is, *realisation 734 of 1,000, seed 7*, and
its tooltip lists the value every sampled input took. Realisation 734 is not
read back from the run: the draws are a function of the seed and each input's
name, so the same settings rebuild it to the last digit, and the run need not
still be held.

This is how an outlier gets looked at. A category picks out the realisations
where the dose peaked; the summary says which percentile they are; this shows
one of them in full. A tornado's points replay the same way — double-click a
row of the tornado for the high point of that input.

## Sensitivity to one parameter

**dy/dp → Sensitivity…** asks a sharper question than the probabilistic one:
at the values the model actually holds, how much does each block move when one
parameter moves? It is a derivative rather than a correlation — exact, and it
needs no distributions at all.

Tick a few parameters and it integrates the model *and* its sensitivities in
one solve. That is why it is a few and not six hundred: each parameter adds a
whole copy of the state vector to the solve, and the dialog says what the total
will be before you start.

**The answer is given as an elasticity**, not as dy/dp. The raw derivative
carries the units of both the block and the parameter, so a sensitivity to a
rate in 1/year and one to a coefficient in m³/kg cannot be put side by side.
The elasticity `(p/y)·(dy/dp)` is a relative change for a relative change: an
elasticity of 0.4 means *1% more of this parameter gives 0.4% more of that
block*, which is comparable across a whole model. dy/dp is in the table beside
it for when the units are what you want.

**Against time, because the answer moves.** A parameter that governs the first
century and nothing after it is the normal case, and the chart shows each
chosen parameter's elasticity across the run with zero always in view — the
sign is half of what an elasticity says.

**Each sensitivity is integrated to its own tolerance.** `dy/dp` is not an
inventory — it carries the units of the block over the units of the parameter,
and on a model with small rates and large inventories it can be twenty orders
of magnitude away from what the block holds. The run's absolute tolerance is
therefore divided by the size of the parameter for each sensitivity, which is
what makes this finish at all: on `four-compartment.json` it is the difference
between 190 steps and hitting the step ceiling with a solver error.

**Nothing in it is approximated.** The sensitivities satisfy
`S' = J·S + df/dp`, and both terms are differentiated from the model's own
equations rather than probed with finite differences — `J·S` by the same
generated tangent the stiff solvers use, and `df/dp` by that generator seeded
on the parameters instead of on the state. Three block types are the exception:
a far-field pathway, a waste package and a disruptive event each fall back to
one forward difference for `df/dp`, which is what every model used to do.

A model can still be too stiff for it — `farfield.json` is, since each
parameter adds another 1,266 states to a system whose first rock layer is 44
nanometres thick. The dialog says what the solve will cost before it starts.

This is exact where the probabilistic sensitivity is sampled, and local where
that one is global: it says how the answer responds to a small change *here*,
not which input explains the spread over a whole distribution. The two answer
different questions and it is worth having both.

## Parameters on the chart

A parameter is a constant, and it is a series like any other: `Results.outputs()`
lists one per parameter per index tuple, after the compartments and the algebraic
blocks, and `series()` gives it as a flat line at its own value. That is what
makes it useful — a rate constant drawn beside the flux it scales says whether
the flux is following the constant or the inventory, and a dose limit drawn
beside a dose says whether the dose crosses it.

They come last and are never what a chart opens on. A real model carries
hundreds of them, so `pickDefaultSeries` reaches for the compartments first and
falls back to parameters only when they are all a model has — which is the case
of a model still being built.

A constant does not travel as a column. `Results.constantOf(output)` gives the
one value behind it and the worker sends that instead, because a Kd indexed by
nuclide and object is several hundred slots and several hundred columns of two
thousand identical numbers is megabytes of nothing to carry across the worker
boundary; the page fills a column from it if and when it charts one. And since
`log value` is on by default, a parameter that is zero or negative throughout —
an ordinary thing for a model to carry — draws nothing on a log axis, so the
chart says so rather than leaving a lit chip beside a line that is not there.

## The project format

A model is one JSON object. The smallest useful one:

```json
{
  "name": "Two boxes",
  "simulation": {
    "start_time": 0, "end_time": 100, "output_points": 200,
    "spacing": "log", "solver": "ndf", "rtol": 1e-6, "abstol": 1e-9
  },
  "parameters":   [{ "name": "k", "value": 0.03, "unit": "1/year" }],
  "compartments": [{ "name": "A", "initial": "1e10" },
                   { "name": "B", "initial": "0" }],
  "transfers":    [{ "name": "T", "from": "A", "to": "B", "rate": "k" }]
}
```

Blocks:

| Key | Meaning |
|---|---|
| `compartments` | State variables. `initial` is a number or an equation. `dydt` is an optional extra term in the rate of change, added to what the transfers and decay give; it may read the compartment itself — see [An explicit dy/dt term](#an-explicit-dydt-term). `handle_decay` (default true) adds decay and ingrowth. `non_negative` (default true) stops the solver carrying the inventory below zero. |
| `transfers` | `from` -> `to`, either of which may be `null` for a source or sink. `rate` is multiplied by the donor compartment unless `"multiply_by_donor": false`, in which case it is an absolute flux. Several transfers may join the same two compartments; their fluxes add. A flux indexed by a dimension one of its ends has not got needs `"sum_extra_indices": true` to say that the total is meant — see [Ends of different dimension](#ends-of-different-dimension-and-sum-extra-indices). |
| `parameters` | Constants. |
| `expressions` | Algebraic quantities evaluated from the state each step. They may reference each other; circular references are rejected. |
| `functions` | Arithmetic written once and called from any equation: `parameters` names the values passed in, `equation` is the body. See [Functions](#functions). |
| `inflows` | An input flux into a compartment. |
| `waste_packages` | The source term with its barriers: an inventory inside packages that fail (`failure`: `never`, `at`, `uniform`, `exponential`, `weibull`, with `fail_at`, `fail_from`/`fail_to`, `fail_start`/`fail_rate`, `fail_start`/`fail_scale`/`fail_shape`), an instant release fraction `irf`, a `degradation_rate` of the matrix, `packages`, `handle_decay`. Per nuclide `inventory` and `irf` through `entries`. Its release leaves through a transfer drawn out of it. See [Waste packages](#waste-packages-the-source-term-with-its-barriers). |
| `events` | Something that happens at an instant: `timing` `at` (with `at`) or `poisson` (with `rate`, `from`, `until`), `sampled`, and `actions`: `{kind: 'fail', block, fraction}` or `{kind: 'move', from, to, fraction}`. Its value is the count of occurrences. See [Events](#disruptive-events). |
| `lookups` | Time-dependent values: a list of `points` and a rule for reading between them (see below). |
| `index_reductions` | One block, reduced along one of its index lists. |
| `block_reductions` | Several blocks, reduced element-wise at each index. |
| `min_maxes` | The largest or smallest value `target` has taken. `operation` is `max` or `min`. |
| `running_means` | The mean of `target` over the time it has been recording. |
| `snapshots` | `target` as it was when `event` last fired; `initial` until then. |
| `delays` | `target` as it was `delay` ago. |
| `triggers` | The instant `first` crosses `second`, `rising`, `falling` or `both`. The solver stops there. |
| `index_lists` | The dimensions available to blocks (see above). A list marked `for_scenarios` is not an axis: one of its indices runs at a time. |
| `scenario` | Which scenario is live, when the model has a scenario list. |
| `decay_unit` | What a radionuclide inventory is measured in: `Bq` (the default) or `mol`. It decides the ingrowth coefficient — see above — and nothing else. |
| `layout` | Diagram geometry per block. Ignored by the solver. |
| `systems` | The sub-systems the model is organised into, as dotted paths. A block's `system` says which one holds it. |
| `transports` | Which of those sub-systems are transports — chains of N compartments drawn as two. The parts inside carry `transport`: `begin` or `end` on a compartment, `number`, `counter` or `operation` on an expression. See *Transports*. |

Every block also takes `index_lists` (its dimensions) and `entries` (values per
index combination).

`simulation` also takes **`endpoints`**: the names of the blocks an export
offers first, which is Ecolego's endpoint list and is read out of an imported
model. It decides nothing about the run — every series is kept — only what the
endpoint export opens on. See [Choosing endpoints](#choosing-endpoints).

### Key names

Keys are `snake_case` — `start_time`, `multiply_by_donor`, `index_lists`. They
were camelCase until recently, and a file written then still opens: the keys
the format defines are renamed on load and the model is saved in the new
spelling. Nothing else is touched, because a model's own names are keys too —
`layout` is keyed by block name, `half_lives` and an object `initial` by
nuclide — and any of those may legitimately be camelCase. The rename matters
rather than being cosmetic: an unknown key is ignored rather than reported, so
a stale `multiplyByDonor: false` would quietly revert to the default `true`
and turn an absolute flux into a rate coefficient. `src/domain/keys.js` is the
list, and is the one place to add to if a key is ever renamed again.

### Units

Units are labels: they reach the chart, the table and the CSV, and take no part
in the arithmetic. Type them where they are a fact about the model — a
compartment's inventory, a parameter, an expression.

A **transfer's** unit is not a fact of that kind. It follows from what its rate
equation means, and so it is derived rather than typed:

| | The rate is | Unit |
|---|---|---|
| `multiply_by_donor` (the default) | a rate coefficient | `1/<time unit>` |
| `"multiply_by_donor": false` | an absolute flux | `<donor unit>/<time unit>` |

The donor is the `from` compartment; for an inflow from outside there is none,
so the recipient sets the scale. `inflows` are that same case and derive the
same way. A donor unit that itself contains a `/` is bracketed —
`(Bq/m3)/year`. If the donor carries no unit, neither does the flux.

The inspector shows the result as a readout rather than a field, and it is
re-derived after every edit that could change it — the flag, the endpoints, the
donor's unit, the simulation's time unit — including a hand-edit in the JSON
tab, which is rewritten on **Apply**. `src/domain/units.js` is the derivation;
`Project` falls back to it for a file that never passed through the editor.

Referencing a transfer by name yields its rate, so `TCOut*C3` is the flux
through `TCOut` — a common idiom in assessment models. A transfer with an
availability yields its rate times the availability, so the idiom still reads
the flux; see [When only part of an inventory can move](#when-only-part-of-an-inventory-can-move).

**A compartment's unit follows the model too, when it holds a radionuclide.** A
compartment on the radionuclide dimension holds an inventory, and there are
exactly two things an inventory is measured in — `Bq` or `mol`, the model's own
choice. So a per-nuclide compartment with no unit is labelled with it, and one
that says the *other* one is reported: that is a state the model cannot be in,
since the numbers in it are read as being in whichever unit was chosen. A
compartment that says something else — `Bq/m3` — means it, and is left alone.

**Where the equation settles the unit, the unit is offered.** A block with an
empty unit whose equation works out to something — an expression over a
transfer in `1/year` and a compartment in `Bq` is in `Bq/year` — shows that
answer beside the box, as a button that fills it in. Offered, never applied: a
unit is a claim about what a number means, and the equation only settles the
ones it can reach. Taking the offer always leaves the unit checker with nothing
to say, which is the property that makes it worth offering.

**A number in an equation can carry its unit.** `0.01[m]` is a length, `2[year]`
a time, `1e3[Bq/m3]` a concentration — the unit in square brackets after the
number. The arithmetic does not change: the
compiler reads the value and nothing else, so `Depth * 0.01[m]` runs exactly as
`Depth * 0.01` does. What changes is what the checker knows. A bare `0.01` is
absorbed into whatever it multiplies; `0.01[m]` makes the product an area, and
`Depth + 2[year]` is reported. Write the unit where a number *is* a quantity
and a parameter would be ceremony.

**SI prefixes are read.** `kBq`, `mSv`, `MBq`, `µg`, `cm`, `mL` — a prefix from
tera to pico on `Bq`, `Sv`, `Gy`, `g`, `m`, `mol`, `L`, `s`, `J`, `W`, `Pa` or
`Ci` is the base unit at a scale, so `cm3` is 10⁻⁶ m³ and `kBq/m3` is 1000 Bq/m³.
Nothing is converted — this tool applies no factors, and a kilobecquerel is still
not a becquerel — but a mismatch that is only a prefix now says so:

> `C: equation works out as Bq/m^3, but this block says 1000 Bq/m^3 — the same
> quantity, 1000 times smaller; nothing here converts, so the factor is yours to
> write in`

rather than treating the two as strangers. The kilogram is the base of mass, as
in SI and in every model here, so `g` reads as 0.001 kg and messages keep saying
`kg`. A symbol whose remainder is not one of those bases is never split: `mol`
is a mole, `min` a minute, `Gy` a gray, `Pa` a pascal, `Ma` a million years.

**A literal is converted to the unit of what it is written against.**
`p1 + 1000[mm]` with `p1` in metres is **2**, not 1001: the literal is scaled by
the factor between the two units and means a metre from there on. This happens
wherever the checker requires two units to *agree* — `+` and `−`, a comparison,
and the arguments of `min`, `max` and `if` — because that is exactly where
there is a unit to convert *to*:

```
p1 + 1000[mm]        ->  2       p1 in m
q  + 500[mm]         ->  150     q in cm — scaled to cm, not to metres
min(p1, 1000[mm])    ->  1
p1 * 5[cm]           ->  5       a product has no target: as written
```

**The target is always the sibling, never a canonical unit.** That is what
makes it safe in a model whose lengths are in centimetres: `q + 500[mm]` is
150 cm, where a tool that scaled to SI would hand you 1.5 and no warning, since
both sides would still agree on the dimension. Two *blocks* whose units differ
are never converted — a number typed into a block is in that block's unit and
only the modeller can restate it — so `Depth + Width` with one in m and one in
mm is still reported, with the factor.

Two things are reported rather than converted, and both are the cases where
there is no single unit to scale to:

> `E: equation — m and 0.001 m cannot be added — the same quantity, a factor of
> 1000 apart; only a literal written directly against the other side is
> converted, so the factor is yours to write in here` — for `p1 + (2 * 1000[mm])`
>
> `E: equation — 1000[mm] is not converted: nothing it is written against says
> what unit it is in` — where the other side is a block with no unit, so that
> typing one on it later cannot quietly change what the equation computes

## Bundled examples

| File | What it shows |
|---|---|
| `examples/four-compartment.json` | A four-compartment test model: one source draining two ways, rejoining, and discharging |
| `examples/decay-chain.json` | Ingrowth down the 4n+1 chain, Pu-241 to Th-229 |
| `examples/biosphere.json` | Repository to geosphere to soil to well, with a dose calculation — and the one to open for a probabilistic run: 15 of its parameters carry distributions |
| `examples/landscape.json` | Two dimensions: 4 nuclides × 3 landscape objects, a sub-set list, and three reductions; solved with ndf |
| `examples/lookup-driver.json` | Two lookup tables driving the model: groundwater flow over a glacial cycle, and a lake silting up |
| `examples/post-processing.json` | No compartments at all: a released inventory, a dilution and a dose, evaluated over the time span |
| `examples/recorders.json` | All five blocks that remember: a peak dose, the year the limit was crossed, a mean from that year on, and the dose a century earlier |
| `examples/scenarios.json` | The same model under three climates, one live at a time |
| `examples/farfield.json` | A FARFCOMP far-field pathway: a vault leaking into a fracture, 20 × 20 cells of rock per nuclide, and a well at the other end |

The picker in the header lists them, and it names **where the model in front of
you came from**: one of these, the file that was opened or dropped, or a blank
start. Not what the model now contains — editing an example does not stop it
being the example you loaded — and not the model's name either, which is the
title beside it. Choosing an entry loads it, over whatever is there.

## URL parameters

`?model=decay-chain.json` open a bundled example ·
`?tab=chart` open on a tab (`build`, `chart`, `table`, `code`, `matrix`,
`indexlists`, `model`, `help`; an unknown name opens Build) ·
`?theme=light` / `?theme=dark` force a colour scheme ·
`?brand=kvotab` use the site palette ·
`?chrome=kvotab` leave room for the site's own header and footer ·
`?mainthread=1` solve without a Worker

### Embedding it in a page

The interface is one grid that fills its box, and the whole of its colour is
custom properties — so putting it inside another site is two parameters rather
than a fork.

**`?brand=kvotab`** swaps the palette. The greys go warm, the ink becomes the
site's dark brown, and the accent — filled buttons, focus rings, the tick in a
checkbox, links — becomes the brand's terracotta, so a Kompartment button
looks like a kvotab button.

One exception, and it is the only one: the ring around a **selected** block
stays green. That ring is read against the ring around a **broken** one, on the
same canvas at the same moment, and the brand's terracotta against the danger
red is eight degrees of hue and a contrast of 1.4:1 between them — two states,
one colour, and the one that matters is *this model will not run*. So the
selection colour is a token of its own (`--select`, which every other palette
leaves equal to the accent).

What does not change at all is every colour that carries meaning: the red of a
broken model, the amber of a warning, and the eight series colours of the
chart, which were chosen to be told apart and not to match anything.

**`?chrome=kvotab`** makes room above and below for the page's own fixed header
and footer, and drops the three things the page is already carrying — whose
site this is, the build, and the light/dark switch. The run statistics stay,
because nothing on the page can say those. Leave it off and the tool fills the
window, which is what it does on its own.

The switch goes because two switches for one setting is two of them to find
disagreeing. The page keeps its own and sends the choice in, as a message —

```js
frame.contentWindow.postMessage({ type: 'kvot:theme', theme: 'dark' }, location.origin);
```

— which is taken only from the window that framed this one, only same-origin,
and only as the two words `light` and `dark`. A message rather than a reload:
what is in the frame is somebody's unsaved model. A page that embeds this and
has no switch of its own can leave `?theme=` to say it once at the start.

The two are separate on purpose: a page may want the palette while the reader
has hidden its navigation, or the navigation with the tool's own colours.

Both are read before the first paint, so there is no flash of the other
palette on the way in.
