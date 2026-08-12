"""Verification of a model against ISO/IEC/IEEE 31320-1:2012 (IDEF0).

Every row is a criterion the model was actually inspected against, and PASS or
FAIL is the answer. There is no third verdict, because a rule nothing tested has
no business carrying one.

Seven criteria are therefore not reported at all, in two groups:

    clause 6 - SEM-TRANS-01, SEM-TRANS-02, SEM-JUNCT-01, SEM-AMBIG-01. Each asks
               whether two things carry the same meaning: is this input really
               transformed into that output, does the output account for the
               input, does a trunk mean the union of its legs, is an attachment
               ambiguous. Nothing here reads meaning.
    drawing  - SYN-BOX-01, SYN-ARROW-02, SYN-ARROW-04. Each constrains how the
               editor DRAWS - square corners, 90-degree arcs, a squiggle to the
               label - and it can only draw one way, so the model holds nothing
               to inspect and the row only restated what the renderer does.

All seven stay in `docs/IDEF0_Validation_Criteria.md`, marked as belonging
to a human reviewer. Eleven clauses used to be missing from the report entirely
and four more were hard-coded to PASS, which read as though they had been
tested; what is left is what can be answered.
"""
import re
from typing import Dict, List, Optional, Set

from src.core.model import IDEF0Model, Diagram, ActivityBox, Arrow, ArrowType


# Characters an identifier may contain: 5.3 says alphanumerics, spaces and
# hyphens; periods and apostrophes are admitted because reference codes (D.4.1)
# and proper names (Roberts' Rules) need them.
ID_CHARS = re.compile(r"^[A-Za-z0-9 \-\.\'’]+$")

PLACEHOLDERS = {"", "-", "<enter purpose>", "<enter viewpoint>", "n/a", "tbd",
                "todo", "none"}


class ComplianceResult:
    def __init__(self, rule_id: str, description: str, status: bool,
                 items: List[str] = None, clause: str = ""):
        self.rule_id = rule_id
        self.description = description
        self.status = status  # True = All items passed, False = some failed
        self.items = items or []  # List of failing elements (empty if passed)
        self.clause = clause

    @property
    def status_text(self) -> str:
        return "PASS" if self.status else "FAIL"


def _is_placeholder(text: Optional[str]) -> bool:
    return (text or "").strip().lower() in PLACEHOLDERS


def _parent_box_of(model: IDEF0Model, diagram: Diagram):
    """(box, diagram it is drawn on) that this diagram details, or (None, None)."""
    for other in model.diagrams:
        if other is diagram:
            continue
        for box in other.boxes:
            if box.id == diagram.node_number:
                return box, other
    return None, None


def _attached(diagram: Diagram, box_id: str) -> List[Arrow]:
    return [a for a in diagram.arrows
            if a.source_box_id == box_id or a.target_box_id == box_id]


def _outputs_of(arrows: List[Arrow], box_id: str) -> List[Arrow]:
    """The arrows drawn as this box's output: type AND direction, both.

    An arrow has to leave the box and say it is an output. One that leaves while
    calling itself an Input gives the box no output at all - P.2.1 Powder Layer
    leaves A41 typed Input, so the model as recorded says A41 produces nothing,
    which is what 5.4 forbids. SYN-ATTACH-03 names the mis-typing behind it, and
    SYN-ATTACH-01 reports what it costs the box.
    """
    return [a for a in arrows
            if a.source_box_id == box_id and a.type == ArrowType.OUTPUT]


def _mistyped_exits(arrows: List[Arrow], box_id: str) -> List[Arrow]:
    """Arrows leaving this box that do not say they are its output."""
    return [a for a in arrows if a.source_box_id == box_id
            and a.type not in (ArrowType.OUTPUT, ArrowType.CALL)]


def get_compliance_data(model: IDEF0Model) -> List[ComplianceResult]:
    """Every criterion in IDEF0_Validation_Criteria.md, in clause order."""
    results: List[ComplianceResult] = []

    def add(rule_id, clause, description, failures):
        failures = list(failures)
        results.append(ComplianceResult(rule_id, description, not failures,
                                        failures, clause))

    all_boxes = [(d, b) for d in model.diagrams for b in d.boxes]
    context = model.get_diagram("A-0")

    # ---------------------------------------------------------------- 5.1 boxes
    # SYN-BOX-01 (a box is a square-cornered rectangle), SYN-ARROW-02 (segments
    # meet at 90-degree arcs) and SYN-ARROW-04 (a squiggle links a label to its
    # segment) are not reported. All three constrain how the editor DRAWS, and
    # it can only draw them one way, so the model holds nothing to inspect: the
    # rows only ever restated what the renderer does.
    add("SYN-BOX-02", "5.1",
        "A box name shall be an active verb or verb phrase",
        [f"{d.node_number}:{b.id} ('{b.name}')" for d, b in all_boxes
         if not _is_verb_phrase(b.name)])

    # 5.1 / 10.1 - the box number in the lower right corner. It is the last
    # character of the node id here, so an id that does not end in a digit has
    # no box number to draw, and two boxes on one diagram may not share one.
    numbering = []
    for diagram in model.diagrams:
        seen: Dict[str, str] = {}
        for box in diagram.boxes:
            bid = (box.id or "").strip()
            if not bid or not bid[-1].isdigit():
                numbering.append(f"{diagram.node_number}:{bid or '<blank>'} "
                                 f"has no box number")
            elif bid in seen:
                numbering.append(f"{diagram.node_number}: box number '{bid}' "
                                 f"used twice")
            else:
                seen[bid] = box.name
    add("SYN-BOX-03", "5.1, 10.1",
        "A box shall carry a unique box number in its lower right corner",
        numbering)

    # 5.1 - the detail reference is framed when a child diagram details the box.
    # The frame is drawn from that relationship, so what is worth checking is
    # the relationship: a decomposition nobody detailed can never show one.
    orphans = [f"Diagram {d.node_number} details no box"
               for d in model.diagrams
               if d.node_number != "A-0" and _parent_box_of(model, d)[0] is None]
    add("SYN-BOX-04", "5.1",
        "A box detailed by a child diagram shall show a framed detail reference",
        orphans)

    unconnected = [f"{d.node_number}:{b.id} ('{b.name}')" for d, b in all_boxes
                   if not _attached(d, b.id)]
    add("SYN-BOX-05", "5.4", "An unconnected box may not appear in a diagram",
        unconnected)

    # --------------------------------------------------------------- 5.2 arrows
    # The router only ever emits axis-aligned runs, but a hand-dragged segment or
    # an imported model can still hold a diagonal, so this is measured.
    diagonals = []
    for diagram in model.diagrams:
        for arrow in diagram.arrows:
            for i in range(len(arrow.segments) - 1):
                p, q = arrow.segments[i], arrow.segments[i + 1]
                if abs(p.x - q.x) > 0.5 and abs(p.y - q.y) > 0.5:
                    diagonals.append(
                        f"{diagram.node_number}:{arrow.id} segment {i} runs "
                        f"({p.x:.0f},{p.y:.0f})-({q.x:.0f},{q.y:.0f})")
                    break
    add("SYN-ARROW-01", "5.2",
        "Arrows shall be horizontal and vertical lines, never diagonal",
        diagonals)

    add("SYN-ARROW-03", "5.2, 5.3",
        "An arrow label shall be a noun or noun phrase",
        [f"'{a.label}' in {d.node_number}" for d in model.diagrams
         for a in d.arrows if a.label and not _is_noun_phrase(a.label)])

    # ---------------------------------------------------------- 5.3 identifiers
    bad_chars = []
    for diagram in model.diagrams:
        if diagram.node_number and not ID_CHARS.match(diagram.node_number):
            bad_chars.append(f"Diagram node number '{diagram.node_number}'")
        if diagram.title and not ID_CHARS.match(diagram.title):
            bad_chars.append(f"Diagram '{diagram.node_number}' title "
                             f"'{diagram.title}'")
        for box in diagram.boxes:
            if box.name and not ID_CHARS.match(box.name):
                bad_chars.append(f"Box '{box.id}' name '{box.name}' in "
                                 f"'{diagram.node_number}'")
        for arrow in diagram.arrows:
            if arrow.label and not ID_CHARS.match(arrow.label):
                bad_chars.append(f"Arrow '{arrow.id}' label '{arrow.label}' in "
                                 f"'{diagram.node_number}'")
    add("SYN-ID-01", "5.3",
        "Identifiers shall be alphanumeric, spaces and hyphens", bad_chars)

    banned_box_words = ("function", "activity", "process")
    add("SYN-ID-02", "5.3",
        "A box name shall not contain 'function', 'activity' or 'process'",
        [f"{d.node_number}:{b.id} ('{b.name}')" for d, b in all_boxes
         if any(re.search(rf"\b{w}\b", (b.name or "").lower())
                for w in banned_box_words)])

    banned_labels = {"input", "control", "output", "mechanism", "call",
                     "object", "data"}
    add("SYN-ID-03", "5.3",
        "An arrow label shall not be a bare ICOM category name",
        [f"'{a.label}' in {d.node_number}" for d in model.diagrams
         for a in d.arrows
         if (a.label or "").strip().lower() in banned_labels])

    add("SYN-ID-04", "5.3",
        "No two different arrows or boxes shall share an identifier",
        _duplicate_identifiers(model))

    # -------------------------------------------------------- 5.4 attachment
    missing_attach = []
    too_many_calls = []
    for diagram in model.diagrams:
        for box in diagram.boxes:
            attached = _attached(diagram, box.id)
            wants = []
            if not any(a.target_box_id == box.id and a.type == ArrowType.CONTROL
                       for a in attached):
                wants.append("control")
            if not _outputs_of(attached, box.id):
                wants.append("output")
            if wants:
                # Say why, when the reason is an arrow that leaves the box
                # without claiming to be its output - otherwise "A41 has no
                # output" is true but gives nobody anything to go and fix.
                mistyped = _mistyped_exits(attached, box.id)
                because = ""
                if "output" in wants and mistyped:
                    because = "; " + ", ".join(
                        f"'{a.label or a.id}' leaves it but is typed {a.type.value}"
                        for a in mistyped) + " (see SYN-ATTACH-03)"
                missing_attach.append(f"{diagram.node_number}:{box.id} has no "
                                      f"{' and no '.join(wants)}{because}")
            calls = [a for a in attached if a.type == ArrowType.CALL]
            if len(calls) > 1:
                too_many_calls.append(f"{diagram.node_number}:{box.id} has "
                                      f"{len(calls)} Call arrows")
    add("SYN-ATTACH-01", "5.4",
        "At least one control and one output shall be attached to every box",
        missing_attach)
    add("SYN-ATTACH-02", "5.4", "Only one call arrow may be attached to a box",
        too_many_calls)

    add("SYN-ATTACH-03", "5.4",
        "An arrow's type shall be the role it is drawn in",
        _type_contradicts_drawing(model))

    # ----------------------------------------------------------- 6 semantics
    # Clause 6 is not reported at all. All four of its criteria - SEM-TRANS-01,
    # SEM-TRANS-02, SEM-JUNCT-01 and SEM-AMBIG-01 - ask whether two things carry
    # the same meaning: is this input really transformed into that output, does
    # the output account for the input, does a trunk mean the union of its legs,
    # is this attachment ambiguous. Nothing here reads meaning. What stood here
    # inspected labelling and connectivity instead and printed the answer under
    # a clause 6 number, which put a verdict on a rule that had not been tested.
    # A reviewer applies clause 6 by hand.

    # ------------------------------------------------------- 7-9 diagrams
    if context is None:
        add("DIA-COMP-01", "7.2",
            "The model shall have an A-0 context diagram with exactly one box",
            ["No A-0 context diagram"])
    else:
        add("DIA-COMP-01", "7.2",
            "The model shall have an A-0 context diagram with exactly one box",
            [] if len(context.boxes) == 1 else
            [f"A-0 holds {len(context.boxes)} boxes, not 1"])

    missing_context = [f"Model {name} is not stated" for name, value in (
        ("name", getattr(model, "name", "")),
        ("purpose", getattr(model, "purpose", "")),
        ("viewpoint", getattr(model, "viewpoint", ""))) if _is_placeholder(value)]
    if context is not None and _is_placeholder(context.title):
        missing_context.append("A-0 has no title")
    add("DIA-COMP-02", "7.2",
        "A-0 shall present the model name, viewpoint and purpose",
        missing_context)

    add("DIA-COMP-03", "9.1",
        "A diagram other than A-0 shall hold between 2 and 9 boxes",
        [f"{d.node_number}: {len(d.boxes)} boxes" for d in model.diagrams
         if d.node_number != "A-0" and not 2 <= len(d.boxes) <= 9])

    # 8.1/8.2 - the text accompanying a diagram is held as the description of the
    # box it details, which is the only prose the model carries for it.
    no_text = []
    for diagram in model.diagrams:
        if _is_placeholder(diagram.title):
            no_text.append(f"{diagram.node_number} has no title")
        box, _ = _parent_box_of(model, diagram)
        if box is not None and _is_placeholder(box.description):
            no_text.append(f"{diagram.node_number} has no accompanying text "
                           f"(describe box {box.id})")
    add("DIA-PAGE-01", "8.1, 8.2",
        "Each diagram shall be accompanied by at least one text page", no_text)

    add("DIA-GLOS-01", "8.3",
        "Every arrow label and leaf box name shall be defined in the glossary",
        _glossary_gaps(model))

    add("FEAT-CONN-01", "9.2",
        "Every box shall connect to a control and an output that reach the "
        "diagram boundary", _boundary_connectivity(model))

    consistency = []
    for diagram in model.diagrams:
        for box in diagram.boxes:
            child = model.get_diagram(box.id)
            if child:
                for issue in _check_consistency(box, diagram, child):
                    consistency.append(f"{box.id}->{child.node_number}: {issue}")
    add("FEAT-BND-01", "9.3",
        "Boundary arrows in a child diagram shall correspond one-to-one with "
        "the arrows on the parent box", consistency)

    add("FEAT-TUN-01", "9.4",
        "A tunnelled arrow shall traverse at least one diagram before "
        "reappearing", _tunnel_faults(model))

    add("REF-NODE-01", "10.2",
        "Node numbers shall be unique and follow the decomposition hierarchy",
        _node_number_faults(model))

    return results


# --------------------------------------------------------------------------
# individual checks
# --------------------------------------------------------------------------
def _root_arrow_id(arrow: Arrow, by_id: Dict[str, Arrow]) -> str:
    """The trunk an arrow ultimately hangs off, following either link."""
    curr, seen = arrow, {arrow.id}
    while True:
        nxt_id = curr.branch_parent_id or curr.join_target_id
        if not nxt_id or nxt_id in seen or nxt_id not in by_id:
            return curr.id
        curr = by_id[nxt_id]
        seen.add(curr.id)


def _article(word: str) -> str:
    return "an" if word[:1].upper() in "AEIOU" else "a"


def _type_contradicts_drawing(model: IDEF0Model) -> List[str]:
    """Every arrow whose declared type disagrees with how it is actually drawn.

    Clause 5.4 gives an arrow its role from the side of the box it attaches to,
    so the type is not a free annotation: it is a second statement of something
    the drawing already says, and the two have to agree. Three ways they can
    fall out of step, checked wherever they can arise rather than only on the
    case that raised it:

    * it **leaves a box**, which is that box's output side, so it is an output.
      P.2.1 Powder Layer leaves A41 and calls itself an Input, which says A41
      emits one.
    * it **enters a box**, which is never that box's output side, so it is an
      input, control or mechanism there.
    * it **merges into another arrow**, and a merge carries one signal, so the
      leg and the bundle it joins are the same kind of thing.

    A branch is deliberately not constrained: a leg splitting off an output bus
    is typed by the role it plays where it lands, which is how D.4.4 Build Model
    reaches A32 as a Control.

    Direction, not type, is what the rest of the report goes by - A41 does have
    an output - and this is where the contradiction itself is reported, with the
    redraw that settles it. A call arrow is exempt: 5.5 attaches it to the
    bottom of the calling box by design.
    """
    faults = []
    for diagram in model.diagrams:
        by_id = {a.id: a for a in diagram.arrows}
        for arrow in diagram.arrows:
            if arrow.type == ArrowType.CALL:
                continue
            named = arrow.label or arrow.icom_code or arrow.id
            where = f"{diagram.node_number}:{arrow.id} ('{named}')"
            kind = arrow.type.value

            if arrow.source_box_id and arrow.type != ArrowType.OUTPUT:
                fix = ""
                if arrow.target_box_id:
                    fix = (f"; draw it as {arrow.source_box_id}'s output and "
                           f"branch that into {arrow.target_box_id}, where it "
                           f"arrives as {_article(kind)} {kind}")
                faults.append(f"{where} leaves {arrow.source_box_id} but is "
                              f"typed {kind}{fix}")

            if arrow.target_box_id and arrow.type == ArrowType.OUTPUT:
                faults.append(
                    f"{where} enters {arrow.target_box_id} but is typed Output; "
                    f"an arrow arriving at a box is its input, control or "
                    f"mechanism")

            trunk = by_id.get(arrow.join_target_id or "")
            if trunk is not None and trunk.type != arrow.type:
                trunk_named = trunk.label or trunk.icom_code or trunk.id
                faults.append(
                    f"{where} is typed {kind} but merges into "
                    f"'{trunk_named}', which is {_article(trunk.type.value)} "
                    f"{trunk.type.value}")
    return faults


def _duplicate_identifiers(model: IDEF0Model) -> List[str]:
    faults = []

    names: Dict[str, List] = {}
    for diagram in model.diagrams:
        for box in diagram.boxes:
            key = (box.name or "").strip().lower()
            if key:
                names.setdefault(key, []).append((box.id, diagram.node_number,
                                                  box.name))
    for boxes in names.values():
        if len({b[0] for b in boxes}) > 1:
            where = ", ".join(f"{b[0]} in {b[1]}" for b in boxes)
            faults.append(f"Box name '{boxes[0][2]}' is duplicate across "
                          f"boxes: {where}")

    for diagram in model.diagrams:
        by_id = {a.id: a for a in diagram.arrows}
        roots: Dict[str, Set[str]] = {}
        for arrow in diagram.arrows:
            if (arrow.label or "").strip():
                roots.setdefault(_root_arrow_id(arrow, by_id), set()).add(
                    arrow.label.strip())
        label_to_roots: Dict[str, List[str]] = {}
        for root_id, labels in roots.items():
            for label in labels:
                label_to_roots.setdefault(label.lower(), []).append(root_id)
        for label, root_ids in label_to_roots.items():
            if len(root_ids) > 1:
                where = ", ".join(f"'{by_id[r].label or r}' ({r})" for r in root_ids)
                faults.append(f"In diagram {diagram.node_number}, label "
                              f"'{label}' used by multiple independent "
                              f"arrows: {where}")
    return faults


def _glossary_gaps(model: IDEF0Model) -> List[str]:
    """Arrow labels and leaf box names with no description anywhere."""
    described: Set[str] = set()
    for diagram in model.diagrams:
        for arrow in diagram.arrows:
            if (arrow.description or "").strip() and (arrow.label or "").strip():
                described.add(arrow.label.strip().lower())

    faults, reported = [], set()
    for diagram in model.diagrams:
        for arrow in diagram.arrows:
            label = (arrow.label or "").strip()
            if label and label.lower() not in described and label.lower() not in reported:
                reported.add(label.lower())
                faults.append(f"Arrow '{label}' has no glossary entry")
        for box in diagram.boxes:
            if model.get_diagram(box.id):
                continue  # not a leaf; its child diagram carries the detail
            if _is_placeholder(box.description):
                faults.append(f"Leaf box {diagram.node_number}:{box.id} "
                              f"('{box.name}') has no glossary entry")
    return faults


def _boundary_connectivity(model: IDEF0Model) -> List[str]:
    """A box whose control or output does not trace out to the diagram edge.

    Section 9.2 asks for the connection to the boundary, not merely for an arrow
    to exist - a control that comes from nowhere inside the diagram governs the
    box with something the diagram never received.
    """
    faults = []
    for diagram in model.diagrams:
        by_id = {a.id: a for a in diagram.arrows}

        def to_boundary(arrow, upstream):
            curr, seen = arrow, {arrow.id}
            while True:
                if upstream:
                    if curr.source_box_id:
                        return True          # produced by another box: still fed
                    if not curr.branch_parent_id:
                        return True          # its tail is the diagram edge
                    nxt = by_id.get(curr.branch_parent_id)
                else:
                    if curr.target_box_id:
                        return True
                    if not curr.join_target_id:
                        return True
                    nxt = by_id.get(curr.join_target_id)
                if nxt is None or nxt.id in seen:
                    return False
                seen.add(nxt.id)
                curr = nxt

        for box in diagram.boxes:
            attached = _attached(diagram, box.id)
            controls = [a for a in attached
                        if a.target_box_id == box.id and a.type == ArrowType.CONTROL]
            outputs = _outputs_of(attached, box.id)
            if controls and not any(to_boundary(a, True) for a in controls):
                faults.append(f"{diagram.node_number}:{box.id} has no control "
                              f"reaching the diagram boundary")
            if outputs and not any(to_boundary(a, False) for a in outputs):
                faults.append(f"{diagram.node_number}:{box.id} has no output "
                              f"reaching the diagram boundary")
    return faults


def _tunnel_faults(model: IDEF0Model) -> List[str]:
    """A tunnel that hides nothing, or that hides an arrow still drawn.

    An arrow tunnelled at the box end is not to appear on the child diagram; one
    tunnelled at the boundary end did not appear on the parent. Either notation
    used where the arrow IS drawn on the neighbouring diagram states a hop the
    model does not make.
    """
    faults = []
    for diagram in model.diagrams:
        for box in diagram.boxes:
            child = model.get_diagram(box.id)
            if not child:
                continue
            child_boundary = [a for a in child.arrows
                              if a.source_box_id is None or a.target_box_id is None]
            for arrow in _attached(diagram, box.id):
                tunnelled = ((arrow.target_box_id == box.id and arrow.tunnel_target)
                             or (arrow.source_box_id == box.id and arrow.tunnel_source))
                if not tunnelled:
                    continue
                shown = [c for c in child_boundary if _is_boundary_match(c, arrow)]
                if shown:
                    faults.append(
                        f"{diagram.node_number}:{arrow.id} "
                        f"('{arrow.label or arrow.icom_code or arrow.id}') is "
                        f"tunnelled into {child.node_number} but drawn there as "
                        f"'{shown[0].id}'")
    return faults


def _node_number_faults(model: IDEF0Model) -> List[str]:
    faults = []
    seen: Dict[str, int] = {}
    for diagram in model.diagrams:
        seen[diagram.node_number] = seen.get(diagram.node_number, 0) + 1
    for node, count in seen.items():
        if count > 1:
            faults.append(f"Node number '{node}' is used by {count} diagrams")

    for diagram in model.diagrams:
        if diagram.node_number in ("A-0", "A0"):
            continue
        parent = diagram.node_number[:-1]
        for box in diagram.boxes:
            if not box.id.startswith(diagram.node_number):
                faults.append(
                    f"Box '{box.id}' sits on {diagram.node_number} but its node "
                    f"number does not continue it")
        if parent and parent != "A" and not model.get_diagram(parent):
            faults.append(f"Diagram {diagram.node_number} has no parent "
                          f"diagram {parent}")
    return faults


def generate_compliance_report(model: IDEF0Model, format="markdown") -> str:
    results = get_compliance_data(model)
    if format == "csv":
        return _format_csv_report(model.name, results)
    return _format_markdown_report(model.name, results)


# --------------------------------------------------------------------------
# name heuristics
# --------------------------------------------------------------------------
# Words that are verbs and nothing else. A box name may start with one; an arrow
# label may not, because the label would then read as an instruction.
STRONG_VERBS = {
    "manage", "create", "operate", "handle", "transform", "execute", "perform",
    "conduct", "analyze", "analyse", "define", "maintain", "provide", "produce",
    "manufacture", "post-process", "evaluate", "develop", "inspect", "verify",
    "validate", "coordinate", "optimize", "optimise", "configure", "implement",
    "establish", "improve", "generate", "deliver", "acquire", "procure",
    "purchase", "distribute", "assemble", "install", "prepare", "determine",
    "select", "receive", "use",
    # Verbs an engineering model reaches for. Without these the report failed
    # perfectly good box names - Format Model, Fuse Powder Layer, Slice Build -
    # and buried the names that really are nouns.
    "choose", "fuse", "recondition", "assign", "allocate", "apply", "deposit",
    "cure", "clean", "melt", "sinter", "remove", "send", "convert", "compile",
    "simulate", "calibrate", "assess", "specify", "refine", "sieve", "capture",
    "collect", "compare", "adjust", "correct", "extract", "derive", "compute",
    "gather", "identify", "classify", "resolve", "reject", "dispatch",
    "publish", "archive", "retrieve", "authorise", "authorize",
}

# Words that are equally a noun. "Design Requirements", "Build Model" and
# "Process Specification" are noun phrases, and flagging every label that opens
# with one of these buried the report in false failures.
NOUN_VERBS = {
    "plan", "design", "control", "process", "support", "report", "test",
    "monitor", "review", "store", "log", "track", "transfer", "build", "model",
    "order", "record", "package", "ship", "market", "schedule", "sell",
    "scan", "print", "cut", "format", "place", "slice", "blend", "repair",
    "sample", "release", "issue", "check", "change", "measure", "update",
}

VERB_SUFFIXES = ("ing", "ize", "ate", "ed", "ify", "ise")


def _words(text: str) -> List[str]:
    return re.findall(r"[A-Za-z][A-Za-z\-]*", text or "")


def _looks_like_a_verb(word: str) -> bool:
    lowered = word.lower()
    return lowered in STRONG_VERBS or lowered.endswith(VERB_SUFFIXES)


def _is_verb_phrase(text: str) -> bool:
    words = _words(text)
    if not words:
        return False
    first = words[0].lower()
    return (first in STRONG_VERBS or first in NOUN_VERBS
            or first.endswith(VERB_SUFFIXES))


def _is_noun_phrase(text: str) -> bool:
    """A label reads as a noun phrase unless it opens as an instruction.

    A word that is only ever a verb rules it out on its own. A word that is
    equally a noun does not: "Design Requirements" names a thing. It only reads
    as a command when something later in the phrase is the verb's object -
    "Plan Manufacturing" - which is what the second test looks for.
    """
    words = _words(text)
    if not words:
        return True
    first = words[0].lower()
    if first in STRONG_VERBS:
        return False
    if first in NOUN_VERBS and any(_looks_like_a_verb(w) for w in words[1:]):
        return False
    return True


# --------------------------------------------------------------------------
# boundary consistency (9.3)
# --------------------------------------------------------------------------
def _get_ref_codes(arrow: Arrow) -> List[str]:
    codes = []
    if arrow.label:
        for m in re.findall(r'\[([^\]]+)\]', arrow.label):
            codes.append(m.strip().lower())

    cleaned = (arrow.label or "").strip().replace("[", "").replace("]", "")
    m = re.match(r'^([a-zA-Z0-9\.\-_]+)', cleaned)
    if m:
        codes.append(m.group(1).lower())

    for code in (arrow.icom_code, getattr(arrow, "auto_icom_code", None)):
        if code:
            codes.append(code.strip().lower())

    return list(set(codes))


def _is_boundary_match(ca: Arrow, pa: Arrow) -> bool:
    if ca.type != pa.type:
        return False

    def clean(s):
        return (s or "").strip().lower()

    ca_lbl, ca_ic = clean(ca.label), clean(ca.icom_code)
    pa_lbl, pa_ic = clean(pa.label), clean(pa.icom_code)

    # 1. Exact matches for raw labels/ICOM codes
    if ca_lbl and pa_lbl and ca_lbl == pa_lbl:
        return True
    if ca_lbl and pa_ic and ca_lbl == pa_ic:
        return True
    if ca_ic and pa_lbl and ca_ic == pa_lbl:
        return True
    if ca_ic and pa_ic and ca_ic == pa_ic:
        return True

    # 2. Extract reference codes and do hierarchical checks
    delims = ['.', '-', '_', '/']
    for c_code in _get_ref_codes(ca):
        for p_code in _get_ref_codes(pa):
            if c_code == p_code:
                return True
            if len(c_code) > len(p_code) and c_code.startswith(p_code):
                if c_code[len(p_code)] in delims:
                    return True

    # 3. Clean text exact matches (ignoring brackets)
    def clean_text_only(s):
        if not s:
            return ""
        return re.sub(r'\[[^\]]+\]', '', s).strip().lower()

    ca_text, pa_text = clean_text_only(ca.label), clean_text_only(pa.label)
    return bool(ca_text and pa_text and ca_text == pa_text)


def _check_consistency(parent_box: ActivityBox, parent_diag: Diagram,
                       child_diag: Diagram) -> List[str]:
    issues = []
    parent_arrows = [a for a in parent_diag.arrows
                     if a.source_box_id == parent_box.id
                     or a.target_box_id == parent_box.id]

    # Only TRUE boundary arrows of the child: a leg that branches off a bus, or
    # joins one, is internal decomposition and has no segment of its own on the
    # parent box. Counting those made every branch of D.3 Standards - Material
    # Specification, three times over - report as unmatched, which is exactly
    # the correspondence 9.3 says holds.
    child_boundary_arrows = [a for a in child_diag.arrows
                             if a.is_boundary() and a.type != ArrowType.CALL]

    def tunnelled(pa):
        return ((pa.target_box_id == parent_box.id and pa.tunnel_target)
                or (pa.source_box_id == parent_box.id and pa.tunnel_source))

    # 1. Parent to Child: non-tunnelled parent arrows must exist in the child
    for pa in parent_arrows:
        if tunnelled(pa):
            continue
        if not any(_is_boundary_match(ca, pa) for ca in child_boundary_arrows):
            issues.append(f"Parent arrow '{pa.label or pa.icom_code or pa.id}' "
                          f"({pa.type.value}) missing in child")

    # 2. Child to Parent (9.3): each child boundary arrow matches exactly one
    for ca in child_boundary_arrows:
        if not (ca.label or "").strip() and not (ca.icom_code or "").strip():
            issues.append(f"Child boundary arrow with ID '{ca.id}' "
                          f"({ca.type.value}) has no label or ICOM code")
            continue

        matching = [pa for pa in parent_arrows
                    if not tunnelled(pa) and _is_boundary_match(ca, pa)]

        if len(matching) > 1:
            ca_codes = _get_ref_codes(ca)
            lengths = []
            for p in matching:
                best = 0
                for c_code in ca_codes:
                    for p_code in _get_ref_codes(p):
                        if c_code == p_code:
                            best = max(best, len(p_code))
                        elif (c_code.startswith(p_code)
                              and len(c_code) > len(p_code)
                              and c_code[len(p_code)] in ['.', '-', '_', '/']):
                            best = max(best, len(p_code))
                lengths.append(best)
            longest = max(lengths) if lengths else 0
            if longest > 0:
                best_parents = [p for p, l in zip(matching, lengths) if l == longest]
                if len(best_parents) == 1:
                    matching = best_parents

        if not matching:
            issues.append(f"Child boundary arrow '{ca.label or ca.icom_code}' "
                          f"({ca.type.value}) has no matching parent arrow segment")
        elif len(matching) > 1:
            names = ", ".join(f"'{p.label or p.icom_code or p.id}'" for p in matching)
            issues.append(f"Child boundary arrow '{ca.label or ca.icom_code}' "
                          f"({ca.type.value}) matches multiple parent arrow "
                          f"segments: {names}")

    return issues


# --------------------------------------------------------------------------
# report formatting
# --------------------------------------------------------------------------
_ICONS = {"PASS": "✅", "FAIL": "❌"}


def status_icon(result: ComplianceResult) -> str:
    text = result.status_text
    return f"{_ICONS.get(text, '')} {text}".strip()


def _format_markdown_report(model_name: str, results: List[ComplianceResult]) -> str:
    passed = sum(1 for r in results if r.status)
    failed = sum(1 for r in results if not r.status)
    report = [f"# Verification Report: {model_name}\n",
              "## ISO/IEC/IEEE 31320-1 Compliance Summary\n",
              f"{len(results)} criteria evaluated - {passed} passed, "
              f"{failed} failed.\n",
              "| Status | Rule ID | Clause | Requirement Description | Findings |",
              "| :--- | :--- | :--- | :--- | :--- |"]
    for r in results:
        findings = "; ".join(r.items) if r.items else "None"
        report.append(f"| {status_icon(r)} | {r.rule_id} | {r.clause} | "
                      f"{r.description} | {findings} |")
    return "\n".join(report)


def _format_csv_report(model_name: str, results: List[ComplianceResult]) -> str:
    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Rule ID", "Clause", "Requirement Description", "Status",
                     "Findings"])
    for r in results:
        writer.writerow([r.rule_id, r.clause, r.description, r.status_text,
                         "; ".join(r.items)])
    return output.getvalue()
