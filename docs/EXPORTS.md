# Export Code Architecture — approach and verification

`File → Export Code Architecture` writes the functional architecture out in seven
notations. This note says how each mapping was chosen, and what was actually run
to check it.

## One reading of the model, seven renderers

Every exporter goes through `src/core/export_common.py`, which resolves the model
once into an **activity tree** and hands the same tree to all of them. Three
decisions live there rather than in any one exporter, because each of them used
to be made differently — and wrongly — in more than one place:

* **An activity's ICOMs are read off the box in its *parent* diagram**, not off
  the boundary arrows of its own decomposition. The parent diagram is the one
  place the signals are stated in the parent's own naming, so a child's internal
  re-labelling cannot change what the activity is declared to consume.
* **Signals are identified by label, not by ICOM code.** `I1`, `C2`, `M1` are
  *positional*: 31320-1 assigns them per diagram, so the same code names
  different things one level down. Keying on them wired an activity's second
  input to its parent's second input whatever the two carried. The label is what
  a decomposition restates verbatim, so the label is the cross-diagram identity.
* **Children come out producer-before-consumer.** IDEF0 states no execution order;
  what it does state is that A1's output is A2's input. Every generated artefact
  needs *some* order, and that is the only one the model supports. Feedback loops
  are broken for ordering purposes and kept in the model.

Names are sanitised and de-duplicated centrally, so no exporter can emit two
methods, actions or ids that clash. `A-0` and `A0` differ only by a hyphen and
used to collapse into one identifier, silently discarding the first definition.

## The mappings

| Target | Mapping | Why this shape |
| --- | --- | --- |
| **Python** | one class, one method per activity, dict of outputs | a decomposition is a call sequence; a dict keyed by signal keeps output names visible at the call site |
| **Java** | one class, `Map<String, Object>` per activity | same shape as Python, in a language with no dict literal |
| **C++** | one struct, `std::map<std::string, std::any>` | as above |
| **SysML v2** | `action def` per activity, `in`/`out item` per ICOM, `part def` per mechanism, `flow from … to …` | SysML v2 has direct counterparts for all four ICOM roles; nothing has to be approximated |
| **UML (XMI 2.1)** | `uml:Activity` per box, `CallBehaviorAction` per box on a diagram, `ObjectFlow` between pins, a `Signals` package of `uml:Class` pin types | an IDEF0 diagram *is* an activity model; exporting it as a class diagram would throw the flows away |
| **UML (PlantUML)** | one activity diagram per IDEF0 diagram — A-0 first, then each decomposition — with object nodes for boundary ICOMs and role-styled object flows between boxes | PlantUML is a text-to-picture renderer with **no XMI front end at all** — see below |
| **BPMN 2.0** | `process` + `callActivity` per decomposed box, `task` per leaf, `sequenceFlow` for output→input, `dataObjectReference` for controls and mechanisms, `startEvent`/`endEvent` for the boundary | BPMN sequences work; IDEF0 constrains it. Controls and mechanisms are data, not ordering, so they are not faked as flows |

### Why PlantUML is a separate writer

PlantUML cannot read XMI. It is not a UML tool that loads a model file; it renders
its own text syntax, and handing it an `.xmi` produces a syntax error rather than a
diagram. The XMI export is for tools that *do* read a model file — Papyrus,
Enterprise Architect, MagicDraw. `UML (PlantUML)` writes what PlantUML reads:
plain `@startuml` blocks, no includes and no themes, so the same file renders on
the online server, the CLI jar and every IDE plug-in.

### What it writes

An IDEF0 box is a **function**, which is a UML **activity** — not a component. The
export used to lead with a component diagram, so the first thing PlantUML drew from
a functional model was a wiring diagram of parts, and the nested
`component X as n { … }` it used for the decomposition is a later addition to that
syntax that older renderers refuse outright. There is no component view any more.

The file now follows IDEF0's own paging: **one activity diagram per diagram of the
model**, the A-0 context page first and each decomposition after it, parents before
children. Every page is a complete `@startuml … @enduml` block carrying its own
title and ICOM key, so it renders alone — pasted into the online server, which
takes one diagram at a time — or all together from the CLI.

### The mapping

This is the mapping `uml_export.py` already writes as XMI, drawn rather than
serialised, so the two exports say the same thing about the same model.

| IDEF0 | UML | Drawn as |
| --- | --- | --- |
| Box | `CallBehaviorAction` on the activity that details it | an action, **shaded** when a page of its own details it |
| Decomposition | the called `Activity` | a page of its own |
| Boundary arrow | `ActivityParameterNode` | an **object node** (UML's parallelogram), the group forked so stacking them implies no order IDEF0 never stated |
| Input | `ObjectFlow` into an `InputPin` | a solid labelled edge |
| Control | `ObjectFlow` into an `InputPin` «control» | a **blue dashed** edge |
| Mechanism | `ObjectFlow` into an `InputPin` «mechanism» | a **green dotted** edge |
| Output | `ObjectFlow` from an `OutputPin` | a labelled edge |
| Boxes with nothing between them | concurrent actions | a **fork** |
| A box's ICOMs | the pins of its call | a **note**, grouped by role, each entry naming where it came from |

Two of those are where a careless mapping goes wrong, and are worth saying out loud.

**IDEF0 states no sequence.** It states what feeds what. Drawing the boxes as one
chain of actions — which is what this export used to do, in node order — asserts a
control flow the model never claimed: that A2 begins when A1 ends. The boxes are
laid out in **dependency tiers** instead. Everything in a tier can run at once and
is drawn as a fork; only the edge *between* two tiers is an ordering, and it is one
the model does state. On A4 of the reference model the difference is plain: Monitor
AM Process and Recondition Powder both wait only on Fuse Powder Layer and neither
waits on the other, and A33's three boxes are wholly independent — all four used to
be drawn in a line. A feedback loop has no first tier by this rule, so it is broken
on the lowest node number and the edge that closed it is named on the box's own note
as feedback rather than silently dropped.

**An IDEF0 control is not a UML control flow.** It is data that *governs* the
function — an object flow into a pin, exactly like an input, distinguished by which
face of the box it enters rather than by being a different kind of edge. Mapping it
to a UML `ControlFlow` would be a pun on the word.

PlantUML gives two consecutive actions one arrow, so a run carrying more than one
role cannot be styled for all of them: the arrow stays neutral and each label takes
its own role's colour instead.

### What the notation cannot carry

None of these is worth a wrong picture to paper over:

- **Pins.** PlantUML draws none, so a box's ICOM signature is a note rather than
  ports on the action. The XMI export has the real pins.
- **Call arrows.** `export_common.py` folds a call arrow into the mechanisms before
  any exporter sees it, so it is not drawn as the separate `CallBehaviorAction` it
  is. Fixing that is a change to the shared reader and to all seven exports.
- **Tunnelling.** A statement about *which diagram* an arrow appears on. Every page
  here draws the arrows of its own diagram, so it needs no notation.
- **Mechanisms as swimlanes.** A UML partition holds one performer; an IDEF0 box may
  have several mechanisms at once, so forcing a lane would drop the rest.

## Faults found in this review, and what was done

| Export | Fault | Fix |
| --- | --- | --- |
| BPMN 2.0 | **No `bpmndi:BPMNDiagram` at all.** BPMN separates what a process *means* from where it is *drawn*, and every viewer built on bpmn-js (bpmn.io, Camunda Modeler) needs the second half. Without it the file loads and then reports that it contains no diagram — the error the export was opening with. | Each process now gets a `BPMNPlane`, a `BPMNShape` with `dc:Bounds` for every flow node and data object, and a `BPMNEdge` with waypoints for every sequence flow and association. IDEF0 geometry does not carry over (IDEF0 reads diagonally, BPMN left to right), so shapes are laid out afresh by sequence depth. |
| BPMN 2.0 | `calledElement="Process_A1"` — an `xsd:QName` with no prefix and no default namespace in scope, so it names a process in *no* namespace rather than the one in the target namespace. | The target namespace is bound to the `idef0` prefix and the attribute is written `idef0:Process_A1`. |
| BPMN 2.0 | `xmlns:bpmndi` was declared and never used; `dc` and `di` were absent. | All four declared, all four used. |
| SysML v2 | A `part def` for a mechanism emitted `perform action a31CreateBuildModel;`. A `part def` sits at package level and that action usage lives *inside* another `action def`, so the name resolved to nothing. | Each performed action is typed by its `action def`, which is declared at package level: `perform action a31CreateBuildModel : A31CreateBuildModel;`. |
| UML | Nothing wrong with the XMI; the complaint was that PlantUML could not open it. | New PlantUML export alongside it (above). XMI left as it was. |

Forward references in the SysML output — an `action def` used above the line that
declares it — are **not** a fault. Name resolution inside a SysML v2 namespace is
not order dependent, and the same is true of the XMI id references and of BPMN's
`calledElement`. The tests below resolve every one of them regardless of order.

## Verification

`tests/test_exports.py` checks the **artefact**, not the generator: what matters is
that something else can read the file.

| Target | How it is verified | Result |
| --- | --- | --- |
| Python | compiled *and executed*; the generated architecture is instantiated and run, and a traced subclass asserts that A1's output actually reaches A2 | pass |
| Java | braces balanced, no method declared twice, public class named for the file; handed to `javac` when a JDK is on PATH | pass, **javac compiled it** |
| C++ | braces balanced, no duplicate definitions; handed to `g++`/`clang++` when one is present | pass (compile step **skipped — no C++ compiler on PATH**) |
| SysML v2 | braces balanced, opens with its package, no duplicate `action def`, **every type referenced is defined somewhere in the file**, no performed action named out of scope, no `flow from self.x` | pass |
| UML (XMI) | parsed as XML; every `xmi:id` unique; every `type`, `behavior`, `source`, `target` and `parameter` reference resolves to an id in the file | pass |
| UML (PlantUML) | **handed to PlantUML itself** and every page rendered, when `PLANTUML_JAR` points at the jar or `plantuml` is on PATH; and without it: one page per IDEF0 diagram, each with a title, `start`/`stop` and balanced `split`s, every box drawn as an action, no `component` anywhere, each ICOM role drawn in its own notation, boxes that feed each other kept in order and boxes that do not forked, and a feedback edge named as feedback | pass, **PlantUML rendered every page** |
| BPMN 2.0 | parsed as XML; every id unique; `sourceRef`, `targetRef`, `calledElement`, `dataObjectRef` and `bpmnElement` all resolve; `incoming` before `outgoing` on every flow node (the XSD sequences them that way); every decomposed box is a callable process; **every process has a plane, every flow node a shape, every connection an edge with at least two waypoints** | pass |

Both a toy model and the full NIST AMS-100 reference model are run through every
one of these.

```
40 passed, 2 skipped        # the 2 skips are the C++ compile, no compiler on PATH
```

To close the two skips, put a C++ compiler on `PATH` and re-run
`pytest tests/test_exports.py`; the syntax-only compile then runs for real. The
Java compile already does — `javac` was on `PATH` for this run and accepted both
models.
