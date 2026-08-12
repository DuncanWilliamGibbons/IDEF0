# Design notes

Why the layout, labelling, notation and export code decides what it decides.
These are the rules the tests in `tests/` hold the renderer to, and the reasoning
behind each one — usually a case where the obvious rule was tried first and
measurably lost. For what the program is and how to run it, see the
[README](../README.md).

## Arrow routing rules

Each box edge is ordered by whichever rule keeps its arrows from crossing, which
is not the same rule on every edge:

- **Head edge (controls)** — by where the arrow arrives *from*, which is two
  different things for two kinds of control. One that comes down the head
  corridor arrives at an X, and arrival order is already crossing-free there. One
  that arrives from *inside* the diagram — off another box's output, or off an
  input bus crossing from the left — never arrives at an X at all: it runs along
  a lane under the corridor and turns up into the edge, so every corridor drop
  landing to its left has to cross that run. Those take the left of the edge,
  lowest lane first, and the corridor drops queue by X to their right.
- **Boundary stubs** — by the standard's positional code (C1, C2, C3 …), which is
  the reading order 31320-1 lays down for an edge. Ordering them by the
  modeller's own id instead cost 4 crossings on A0 alone.
- **Side edge (inputs)** — by the Y the arrow arrives at, for the same reason:
  an input crosses the diagram at the height it left its source.
- **Foot edge (mechanisms)** — by run length, shortest first. Mechanisms come
  from below and around, where arrival position says little; length is the
  better guide and measurably wins here.
- **Corridor tiers** — by how far each bus has to run, shortest held in nearest
  the boxes.
- **Feedback loops off one box** — nested by reach, shortest on the inside. All
  the loops leaving a box the same way share one channel: the drop lane beside
  the box, then the run under (or over) the diagram. A short loop staggered
  *outside* a long one has to turn back across the long one's descent to get
  home, which is the crossing under A3 that used to show; inside, it turns back
  before it ever reaches that lane. The drop lane and the run underneath are
  ordered together, since disagreeing about which is inner crosses them anyway.

Ordering the head or side edge by length instead cost 21 crossings and swapped
ports on arrows that had no reason to trade them; both are ordered by arrival.

All of this is computed from the diagram every time it is laid out, so adding or
reassigning an arrow re-runs it for every arrow in that diagram. The tests in
`test_arrow_labels_and_spacing.py` check the rules over every diagram in the
reference model rather than any one of them.

## Arrow labelling rules

A signal is named once, where a reader tracing the line meets it first, and
nowhere else. Which leg that is turns on **where the label above it is printed**,
not on whether a decomposition happened somewhere further up:

- **Covered by an upstream label** — an ancestor named where the signal *enters*
  the diagram (a boundary bus) or where it *leaves a box* (an output) sits
  upstream of every later split, so one printing names them all. D.4.1.1 Product
  Design leaves A11 named; the legs branching off it into A12 and A13 stay bare.
- **Not covered** — an ancestor named beside the function it *delivers into* has
  its label at the far end of its own run and names that delivery alone. D.5.1
  CAD Software is named at A11, so the leg on to A13 names itself; A13 has
  nothing else to read.
- A leg that only feeds further legs, touching no box, stays unlabelled either
  way: naming a signal mid-corridor names it to nobody.

The rule is universal — `test_arrow_labels_and_spacing.py` checks it against
every diagram in the reference model, not against the cases it was written for.

### Where a border ICOM's label goes

A boundary arrow is read at the edge it crosses, so its label sits out in the
headspace there — the same short run in from the border for every one of them,
which puts them all in the margin where nothing else is drawn. Two junctions
bound how far along the approach that can be:

- a **merge** must be behind it. Before a join the run does not yet carry the
  whole bundle, so a name printed there names the parts: P.4.8 Sensor Data was
  anchored 60 back from the edge with A44's output joining 50 back.
- a **split** must be ahead of it, so the one label covers every leg peeling off
  — which is what lets those legs stay bare.

Anchored at the midpoint of its own approach instead, a label ended up wherever
that arrow happened to be long: D.4.7 Equipment Controls sat 200px down a 400px
drop, in among the parallel drops of its neighbours. A boundary label is wide
enough to span several of those, so anywhere in there it lay across two or three
lines. Over the reference model that cost 42 labels drawn over a line and 13
callouts drawn across one; it is now 6 and 1.

Placement also treats arrow runs as obstacles, not just boxes and other labels,
and a border ICOM that has to move is walked *outwards* first — past the border
is the one direction with nothing in it.

## ICOM identifiers

An arrow carries two, kept in separate fields:

- `icom_code` — the id the **modeller** assigns (`P.2`, `D.4.1`). Never
  generated, never overwritten.
- `auto_icom_code` — the positional code **31320-1** defines (`O1`, `C2`),
  regenerated from the diagram unless it has been typed in by hand.

Holding both in one field meant assigning `P.2` silently destroyed the `O1` the
standard requires. **View → ICOM IDs** picks which is drawn: `User Defined`
("P.2 AM Part"), `Auto` ("O1 AM Part"), `Both` ("P.2 AM Part [O1]") or `None`
("AM Part"). Both stay editable in the properties panel under every setting.

## Tunnel notation

Clause 9.4 asks for "a pair of short, shallow arcs drawn to resemble a pair of
left and right parentheses characters" bracketing the end of the arrow. Both
arcs are drawn, and the bracketed end sits **between** them — the pair straddles
the line, one arc each side of it, opening inwards. It turns with the arrow, so
a vertical segment is bracketed left and right and a horizontal one above and
below; either way the line runs between the two arcs rather than through them.
One arc across the line is not the notation, and offsetting it *forward* from a
head put it inside the box the arrow was tunnelling into.

The pair is set clear of whatever the end attaches to by its own extent in that
direction, so a box edge never cuts an arc, and it is derived from the arrow's
geometry rather than from the arrowhead — an arrow that merges into another one
draws no head and still has to be bracketed.

Which end is bracketed is the modeller's, and is now editable: **Tunnel Tail
(Source)** and **Tunnel Head (Target)** sit in the properties panel for a
selected arrow, not only on the dialog that created it. **FEAT-TUN-01** reports
a notation that claims a hop the model does not make — an arrow tunnelled into a
box and drawn on that box's child diagram anyway.

## Exports

`File -> Export Code Architecture` writes the functional architecture as Python,
Java, C++, SysML v2, UML (XMI 2.1), UML (PlantUML) or BPMN 2.0. All seven read
the model through `src/core/export_common.py`, which resolves it once into an
activity tree, so they cannot disagree about what the model says.

**PlantUML** writes what an IDEF0 model *is*: an activity diagram per diagram of
the model, A-0 first and each decomposition after it. It draws the same mapping
`uml_export.py` serialises as XMI — box → `CallBehaviorAction`, boundary arrow →
`ActivityParameterNode`, ICOM → `ObjectFlow` into a pin — so the two exports say
the same thing about the same model.

Two points decide whether that mapping is honest:

- **IDEF0 states no sequence**, only what feeds what. Boxes are laid out in
  **dependency tiers**: everything in a tier can run at once and is drawn as a
  fork, and only the edge *between* tiers is an ordering the model actually
  states. Drawn as one chain instead — which is what this export used to do —
  the diagram asserts that A2 begins when A1 ends, which IDEF0 never said and
  which is plainly false on A4 and A33 of the reference model. A feedback loop
  has no first tier, so it is broken on the lowest node number and the edge that
  closed it is named as feedback on the box's own note.
- **An IDEF0 control is not a UML control flow.** It is data that governs the
  function — an object flow into a pin, like an input, told apart by which face
  of the box it enters. Mapping it to a `ControlFlow` would be a pun on the word.

The roles are drawn rather than described: boundary ICOMs as object nodes, forked
so stacking them implies no order; box-to-box flows as the object flow's label,
blue dashed arriving as a control and green dotted as a mechanism; each box's
ICOM signature — its pins, which PlantUML cannot draw — in a note grouped by
role; and a decomposed box shaded, because a page of its own details it. Every
page is a self-contained `@startuml` block with its own title and key, so one
pasted into the online server — which takes a single diagram at a time — renders.

A box is a function, which is an activity: the export used to lead with a
**component** diagram, so the first thing PlantUML drew from a functional model
was a wiring diagram of parts, and the nested `component X as n { … }` it used
for the decomposition is a later addition to that syntax which older renderers
refuse outright.

`tests/test_exports.py` checks the artefact rather than the generator: the Python
is compiled and run, the Java is handed to `javac` when a JDK is on PATH, the C++
to `g++`/`clang++` when one is, the PlantUML is **rendered by PlantUML** when
`PLANTUML_JAR` points at the jar (or `plantuml` is on PATH), and the XMI and BPMN
are parsed with every cross-reference resolved.

`docs/EXPORTS.md` says why each mapping was chosen and what was run to check it.

The ICOMs and Functions database views each carry an **Export** button writing
whatever the table currently shows — filter included — as CSV, JSON, XML or TXT.

## Done

- Labels are generated with their squiggle at 45 degrees to the arrow line, so the
  callout leaves the run instead of creeping along under the text.
- A branch whose drop lane ends up behind its tap no longer hooks back along its
  trunk before turning.
- The four pan buttons move the view at any zoom. They drove the scroll bars,
  which have range only while the diagram overflows the pane, so on a diagram
  that fitted — the state straight after Reset View — every click did nothing.
- Each pan arrow points the way the *diagram* travels. They were wired to the
  camera, so pressing "right" walked the drawing off to the left.

## Verification report

`Report -> Verification Report (ISO 31320-1)` covers every criterion in
`docs/IDEF0_Validation_Criteria.md` that a tool can decide at all — eleven
of them used to be absent from the report entirely and four more were hard-coded
to PASS. Each result says how it was decided, so a clause nobody could check no
longer reads as one that passed: **every row is a criterion the model was
inspected against, and the answer is PASS or FAIL.** There is no third, softer
verdict, because a rule nothing tested has no business carrying one.

Seven criteria are therefore **not rows at all**, in two groups:

- **Clause 6** — **SEM-TRANS-01** (input is transformed into output),
  **SEM-TRANS-02** (output accounts for all input), **SEM-JUNCT-01** (a trunk
  means the union of its legs) and **SEM-AMBIG-01** (an ambiguous attachment is
  labelled). Each asks whether two things carry the same meaning, and nothing
  here reads meaning; what stood under those clause numbers inspected labelling
  and connectivity instead and reported the answer as though the rule itself had
  been tested.
- **The drawing rules** — **SYN-BOX-01** (square-cornered rectangle),
  **SYN-ARROW-02** (90-degree arcs) and **SYN-ARROW-04** (a squiggle to the
  label). Each constrains how the editor draws, and it can only draw one way, so
  the model holds nothing to inspect and the row only restated what the renderer
  does.

All seven stay in the criteria document, marked for a human reviewer.

An output takes **type and direction, both**: an arrow has to leave the box and
say it is an output. P.2.1 Powder Layer leaves A41 typed Input, so the model as
recorded says A41 produces nothing — which is exactly what 5.4 forbids, and
**SYN-ATTACH-01** reports it. The finding names the arrow behind it rather than
leaving "A41 has no output" as a true statement nobody can act on:

> `A4:A41 has no output; 'Powder Layer' leaves it but is typed Input (see SYN-ATTACH-03)`

The mis-typing itself is a separate fault, and **SYN-ATTACH-03** is where it is
reported.
Clause 5.4 gives an arrow its role from the side of the box it attaches to, so
the type is a second statement of something the drawing already says, and the two
have to agree. Three ways they can fall out of step, all checked:

- it **leaves a box**, which is that box's output side, so it is an output;
- it **enters a box**, which is never that box's output side;
- it **merges into another arrow**, and a merge carries one signal, so the leg
  and the bundle are the same kind of thing.

A branch is deliberately free: a leg splitting off an output bus is typed for
where it lands, which is how D.4.4 Build Model reaches A32 as a Control.

The finding names the redraw that settles it — an output from A41, branched into
A42 where it arrives as an Input, which is how the rest of the model is already
drawn. Reporting it under SYN-ATTACH-01 instead said "A41 has no output", which
is both untrue and no help in fixing it.

The report itself is re-run every time it is asked for. The tab was built once
and afterwards only switched to, so it went on asserting whatever the model
looked like when it first opened: fix a finding, ask for the report again, and
the finding was still there. After opening a different project it reported on a
model no longer loaded.
