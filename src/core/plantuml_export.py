"""PlantUML export of an IDEF0 functional architecture, as activity diagrams.

The XMI 2.1 export writes UML for a UML *tool* - Papyrus, EA, MagicDraw - which
reads a model file and draws it for you. PlantUML reads nothing of the sort: it
is a text-to-picture renderer with its own syntax and no XMI front end at all, so
handing it an .xmi gets a syntax error rather than a diagram. This writes what it
does read, and writes it as the diagram kind an IDEF0 model actually is.

An IDEF0 box is a *function*, which is a UML activity - not a component. The
export used to lead with a component diagram, nesting `component X as n { ... }`
to show the decomposition, so the first thing PlantUML drew from a functional
model was a wiring diagram of parts; that nesting form is also a later addition
to the component syntax and is refused outright by older renderers, which is one
way the file came back as an error rather than a picture. There is no component
view any more.

What is written instead follows IDEF0's own paging: one activity diagram per
diagram of the model, the A-0 context page first, each decomposition after it,
parents before children. Every page is a complete `@startuml ... @enduml` block
carrying its own title and key, so it renders alone - pasted into the web
server, which takes one diagram at a time - or all together from the CLI.

The mapping is the one `uml_export.py` writes as XMI, drawn rather than
serialised, so the two exports say the same thing about the same model:

    IDEF0                     UML                          drawn as
    ------------------------- ---------------------------- --------------------
    box                       CallBehaviorAction on the     an action, shaded
                              Activity that details it      when a page details it
    decomposition             the called Activity           a page of its own
    boundary arrow            ActivityParameterNode         an object node
    input                     ObjectFlow into an InputPin   solid labelled edge
    control                   ObjectFlow into an InputPin   blue dashed edge
                              <<control>>
    mechanism                 ObjectFlow into an InputPin   green dotted edge
                              <<mechanism>>
    output                    ObjectFlow from an OutputPin  labelled edge
    boxes with nothing         concurrent actions           a fork
    between them
    a box's ICOMs             the pins of its call          a note, by role

Two of those need saying out loud, because they are where a careless mapping
goes wrong.

**IDEF0 states no sequence.** It states what feeds what. Drawing the boxes as
one chain of actions - which is what this export used to do, in node order -
asserts a control flow the model never claimed: that A2 begins when A1 ends. So
the boxes are laid out in DEPENDENCY TIERS instead. Everything in a tier can
run at once and is drawn as a fork; only the edge between two tiers is an
ordering, and it is one the model does state. See `_dependency_tiers`.

**An IDEF0 control is not a UML control flow.** It is data that governs the
function - an object flow into a pin, exactly like an input, and distinguished
by which face of the box it enters rather than by being a different kind of
edge. Mapping it to a UML ControlFlow would be a pun on the word.

Known limits, none of them worth a wrong picture to paper over. PlantUML draws
no pins, so a box's ICOM signature is a note rather than ports on the action. A
call arrow reaches this writer already folded into the mechanisms by the shared
reader, so it is not drawn as the separate CallBehaviorAction it is. Tunnelling
is a statement about which diagram an arrow appears on, and every page here
draws the arrows of its own diagram, so it needs no notation. Mechanisms are
not made into swimlanes: a partition holds one performer and an IDEF0 box may
have several at once.

Everything is plain PlantUML with no includes or themes, so it renders the same
in the online server, the CLI jar and every IDE plug-in.
"""
import re
from typing import Dict, List

from src.core.export_common import (
    Activity, Flow, build_activity_tree, model_title, pascal,
)
from src.core.model import IDEF0Model

# Object nodes and shaded actions. Kept pale: PlantUML renders label text in
# black over them and a saturated fill makes an ICOM code hard to read.
_OBJECT_FILL = "#E8F1FA"
_DECOMPOSED_FILL = "#DDEBF7"

# How an object flow is drawn for the role it plays where it ARRIVES. IDEF0
# reads the role off the side of the box the arrow enters, so one box's output
# is drawn as a control when the next box takes it on its control face.
_FLOW_STYLE = {
    "input": "->",
    "control": "-[#0055aa,dashed]->",
    "mechanism": "-[#2f7f2f,dotted]->",
}

# The same colours on the label, so a run carrying more than one role - which
# can only be drawn as one arrow - still says which of them each signal is.
_ROLE_COLOUR = {"control": "#0055aa", "mechanism": "#2f7f2f"}

_ROLE_HEADING = {"input": "Inputs", "control": "Controls",
                 "mechanism": "Mechanisms"}

# `;` ends an action and a newline ends a line, so neither can reach a label.
_UNSAFE = str.maketrans({";": ",", "\n": " ", "\r": " ", "\t": " "})


def _text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").translate(_UNSAFE)).strip()


def _node_key(node_id: str):
    """Sorts A1, A2, A10 the way a modeller numbered them."""
    return [int(p) if p.isdigit() else p.lower()
            for p in re.split(r"(\d+)", node_id or "")]


def _reading_order(activities: List[Activity]) -> List[Activity]:
    """Boxes in the order the model numbers them.

    The shared tree orders children producer-before-consumer, which is what a
    generated *program* needs so a variable is assigned before it is read. A
    diagram needs the reading order the modeller chose instead: 9.1 lays the
    boxes out in node-number order down the staircase, and a page that shows
    A4 first because nothing feeds it does not match the diagram it details.
    """
    return sorted(activities, key=lambda a: _node_key(a.node_id))


def export_to_plantuml(model: IDEF0Model) -> str:
    roots = build_activity_tree(model)

    pages = [_context_page(model, roots)]
    for root in roots:
        for activity in _top_down(root):
            if activity.children:
                pages.append(_decomposition_page(activity))

    return "\n\n".join("\n".join(page) for page in pages) + "\n"


def _top_down(root: Activity) -> List[Activity]:
    """Every activity, a parent before its children, siblings in reading order."""
    out: List[Activity] = []
    queue = [root]
    while queue:
        activity = queue.pop(0)
        out.append(activity)
        queue.extend(_reading_order(activity.children))
    return out


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------
def _context_page(model: IDEF0Model, roots: List[Activity]) -> List[str]:
    """A-0: the one box the whole model details, with its boundary ICOMs."""
    title = model_title(model)

    # 7.2 wants the purpose and viewpoint stated on the context page. They go in
    # the legend: a note has to attach to an element, and before `start` there
    # is no element for one to attach to - which is what made the page a syntax
    # error rather than a diagram.
    stated = []
    for field in ("purpose", "viewpoint"):
        value = _text(getattr(model, field, "") or "")
        if value:
            stated.append(f"  <b>{field.title()}</b> {value}")

    lines = _open(pascal(f"A-0 {title}"), f"A-0 Context - {_text(title)}",
                  preamble=stated)
    lines.append("start")

    for root in _reading_order(roots):
        lines.extend(_object_nodes(root.inputs))
        lines.append(_action(root))
        lines.extend(_icom_note(root, {}))
        lines.extend(_object_nodes(root.outputs))

    lines.extend(("stop", "@enduml"))
    return lines


def _decomposition_page(activity: Activity) -> List[str]:
    """One IDEF0 diagram: the boxes that detail `activity`.

    The page opens on the ICOMs arriving at the parent box - which is exactly
    what the boundary arrows of the diagram carry - works down the boxes in
    dependency tiers, and closes on what leaves.
    """
    children = _reading_order(activity.children)
    producer = _producers(children)
    tiers = _dependency_tiers(children, producer)
    tier_of = {child.node_id: i for i, tier in enumerate(tiers) for child in tier}

    lines = _open(pascal(f"{activity.node_id} {activity.title}"),
                  f"{_text(activity.node_id)} - {_text(activity.title)}")
    lines.append("start")
    lines.extend(_object_nodes(activity.inputs))

    previous: List[Activity] = []
    for tier in tiers:
        if previous:
            lines.extend(_object_flow(previous, tier, producer))
        lines.extend(_tier(tier, producer, tier_of))
        previous = tier

    lines.extend(_object_nodes(activity.outputs))
    lines.extend(("stop", "@enduml"))
    return lines


def _dependency_tiers(children: List[Activity],
                      producer: Dict[str, str]) -> List[List[Activity]]:
    """The boxes grouped by how deep their dependencies run.

    This is the whole of the ordering an IDEF0 diagram states, and no more of
    it. IDEF0 says what feeds what; it does not say what happens first. Boxes
    that need nothing from a sibling can all run at once, and one that needs
    another's output cannot start before it - so the tiers become a fork of
    concurrent actions each, and only the edge BETWEEN two tiers is a claim
    the model actually makes.

    Drawing the boxes in a line instead, which is what a single chain of
    actions does, reads as a control flow: A2 begins when A1 ends. Nothing in
    IDEF0 says that, and on A4 of the reference model it is plainly false -
    Monitor AM Process and Recondition Powder both wait only on Fuse Powder
    Layer, and neither waits on the other.

    A feedback loop has no first tier by this rule, so it is broken on the
    lowest node number and the edge that closed it is reported on the box's
    own note instead of being silently dropped.
    """
    by_id = {child.node_id: child for child in children}
    needs = {
        child.node_id: {producer[flow.key] for flow in child.parameters
                        if producer.get(flow.key) not in (None, child.node_id)}
        for child in children
    }

    tiers: List[List[Activity]] = []
    placed: set = set()
    remaining = [child.node_id for child in children]
    while remaining:
        ready = [node for node in remaining if needs[node] <= placed]
        if not ready:
            ready = [remaining[0]]  # feedback: break it on the lowest number
        tiers.append([by_id[node] for node in ready])
        placed.update(ready)
        remaining = [node for node in remaining if node not in placed]
    return tiers


def _tier(tier: List[Activity], producer: Dict[str, str],
          tier_of: Dict[str, int]) -> List[str]:
    """One tier: a single action, or a fork of the boxes that can run at once."""
    if len(tier) == 1:
        return _box(tier[0], producer, tier_of)

    lines = ["split"]
    for i, child in enumerate(tier):
        if i:
            lines.append("split again")
        lines.extend(f"  {line}" for line in _box(child, producer, tier_of))
    lines.append("end split")
    return lines


def _box(child: Activity, producer: Dict[str, str],
         tier_of: Dict[str, int]) -> List[str]:
    return [_action(child)] + _icom_note(child, producer, tier_of)


def _open(name: str, title: str, preamble: List[str] = ()) -> List[str]:
    """The head of one page: its own title, styling and ICOM key.

    Repeated on every page rather than shared, because each block is a diagram
    in its own right - the online server renders one at a time - and a page
    that arrives without its key cannot be read.
    """
    return [
        f"@startuml {name}",
        f"title {title}",
        "",
        "skinparam shadowing false",
        "skinparam ArrowFontSize 10",
        "skinparam NoteBackgroundColor #FEFBE6",
        "skinparam ActivityBackgroundColor #F5F5F5",
        "",
        "legend right",
        *preamble,
        *(["  ----"] if preamble else []),
        "  <b>Reading this diagram</b>",
        "  Parallelogram = ICOM crossing the diagram boundary",
        "  Solid arrow = one box's output read as the next box's input",
        "  <color:#0055aa>Blue dashed</color> = read as a control",
        "  <color:#2f7f2f>Green dotted</color> = read as a mechanism",
        "  Fork = boxes that wait on nothing from each other",
        "  Shaded box = decomposed on its own page",
        "  IDEF0 states what feeds what, never what happens first:",
        "  only an edge between two forks is an ordering.",
        "endlegend",
        "",
    ]


# --------------------------------------------------------------------------
# elements
# --------------------------------------------------------------------------
def _producers(children: List[Activity]) -> Dict[str, str]:
    """Signal key -> the node id of the child that produces it."""
    produced: Dict[str, str] = {}
    for child in children:
        for flow in child.outputs:
            produced.setdefault(flow.key, child.node_id)
    return produced


def _action(activity: Activity) -> str:
    """One IDEF0 box as one action, shaded when a page details it further."""
    fill = _DECOMPOSED_FILL if activity.children else ""
    return f"{fill}:<b>{_text(activity.node_id)}</b> {_text(activity.title)};"


def _object_nodes(flows: List[Flow]) -> List[str]:
    """Boundary ICOMs as object nodes - the parallelogram UML gives an object.

    Split into parallel branches rather than stacked in a line. A diagram's
    boundary arrows arrive together and go to different boxes; one under
    another would read as a sequence, and claim an order IDEF0 never states.
    """
    if not flows:
        return []

    nodes = []
    for flow in flows:
        # A label ending in the shape character would swallow it.
        label = _bold_code(_text(flow.qualified).rstrip("/\\|]})"))
        nodes.append(f"{_OBJECT_FILL}:{label}/")

    if len(nodes) == 1:
        return nodes

    lines = ["split"]
    for i, node in enumerate(nodes):
        if i:
            lines.append("split again")
        lines.append(f"  {node}")
    lines.append("end split")
    return lines


def _bold_code(label: str) -> str:
    """Sets a leading [ICOM code] in bold so it reads apart from the name."""
    return re.sub(r"^(\[[^\]]+\])", r"<b>\1</b>", label)


def _object_flow(previous: List[Activity], tier: List[Activity],
                 producer: Dict[str, str]) -> List[str]:
    """Label the edge into a tier with what actually passes along it.

    Only what the tier above produces and this one reads: two tiers with no
    signal between them get the bare arrow PlantUML draws anyway, rather than
    an arrow claiming a flow the model does not state.
    """
    sources = {activity.node_id for activity in previous}
    carried, seen = [], set()
    for child in tier:
        for flow in child.parameters:
            if producer.get(flow.key) in sources and flow.key not in seen:
                seen.add(flow.key)
                carried.append(flow)
    if not carried:
        return []

    # PlantUML allows one arrow between two actions, so a run carrying signals
    # in different roles cannot be styled for all of them. The line keeps the
    # style when they agree, and each label is coloured for its own role either
    # way, so a control riding alongside an input is still legible as one.
    roles = {flow.kind for flow in carried}
    style = _FLOW_STYLE[carried[0].kind] if len(roles) == 1 else "->"
    label = "\\n".join(_role_colour(_bold_code(_text(flow.qualified)), flow.kind)
                       for flow in carried)
    return [f"{style} {label};"]


def _role_colour(label: str, role: str) -> str:
    """Controls and mechanisms in the colour their arrow style uses."""
    colour = _ROLE_COLOUR.get(role)
    return f"<color:{colour}>{label}</color>" if colour else label


def _icom_note(activity: Activity, producer: Dict[str, str],
               tier_of: Dict[str, int] = None) -> List[str]:
    """Everything the box is given, by role, and where each one comes from.

    This is the box's ICOM signature - in UML terms the pins of its call, which
    PlantUML has no way to draw. The edges carry the tier-to-tier flows; this
    carries the rest, which is most of any control or mechanism, since those
    usually arrive from the diagram boundary and have no edge to hang a label
    on. A signal fed back from a box further down is marked as feedback, so a
    source that appears below its consumer reads as the loop it is.
    """
    tier_of = tier_of or {}
    sections = []
    for role in ("input", "control", "mechanism"):
        flows = getattr(activity, {"input": "inputs", "control": "controls",
                                   "mechanism": "mechanisms"}[role])
        if not flows:
            continue
        entries = [f"  <b>{_ROLE_HEADING[role]}</b>"]
        for flow in flows:
            source = producer.get(flow.key)
            if not source or source == activity.node_id:
                origin = "boundary"
            elif tier_of.get(source, -1) >= tier_of.get(activity.node_id, 0):
                origin = f"{source}, feedback"
            else:
                origin = source
            entries.append(f"  {_text(flow.qualified)} <i>from {origin}</i>")
        sections.append(entries)

    if not sections:
        return []

    lines = ["note right"]
    for i, section in enumerate(sections):
        if i:
            lines.append("  ----")
        lines.extend(section)
    lines.append("end note")
    return lines
