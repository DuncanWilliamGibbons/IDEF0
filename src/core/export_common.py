"""Shared reading of an IDEF0 model for every code / notation exporter.

Each exporter used to walk `model.diagrams` on its own, and each got the same
things wrong: two diagrams whose node numbers differ only by the hyphen (A-0 and
A0) collided into one method name, boundary arrows were read from the child
diagram instead of the box in the parent, and boxes were emitted in id order so a
generated variable could be used a line before it was assigned.

This module resolves the model once into an activity tree, so an exporter only
has to render it:

    * an activity's ICOMs come from the arrows touching ITS box in ITS parent
      diagram - the one place they are stated with the parent's own naming;
    * signals are identified by label, which is what stays stable across a
      decomposition boundary (the I1/C2/M1 codes are positional and do not);
    * children are ordered so that a producer is emitted before its consumers,
      with feedback edges dropped from the ordering rather than the model.

Names are sanitised and de-duplicated centrally, so no exporter can emit two
methods, actions or ids that clash.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
import re

from src.core.model import IDEF0Model, Diagram, ActivityBox, Arrow, ArrowType

# Identifiers we must not hand to a generated language as a name.
RESERVED = {
    # python
    "False", "None", "True", "and", "as", "assert", "async", "await", "break",
    "class", "continue", "def", "del", "elif", "else", "except", "finally",
    "for", "from", "global", "if", "import", "in", "is", "lambda", "nonlocal",
    "not", "or", "pass", "raise", "return", "try", "while", "with", "yield",
    # java / c++ additions that are not already above
    "abstract", "auto", "bool", "boolean", "byte", "case", "catch", "char",
    "const", "default", "delete", "do", "double", "enum", "explicit", "export",
    "extends", "extern", "final", "float", "goto", "implements", "inline",
    "instanceof", "int", "interface", "long", "namespace", "native", "new",
    "operator", "package", "private", "protected", "public", "register",
    "short", "signed", "sizeof", "static", "struct", "super", "switch",
    "synchronized", "template", "this", "throw", "throws", "transient",
    "typedef", "typename", "union", "unsigned", "using", "virtual", "void",
    "volatile",
}

_KIND_OF_TYPE = {
    ArrowType.INPUT: "input",
    ArrowType.CONTROL: "control",
    ArrowType.OUTPUT: "output",
    ArrowType.MECHANISM: "mechanism",
    ArrowType.CALL: "mechanism",
}


def sanitize(name: str) -> str:
    """A bare identifier: alphanumerics and underscores, never leading a digit."""
    cleaned = re.sub(r'[^0-9A-Za-z]+', '_', (name or "")).strip('_')
    if not cleaned:
        return "unnamed"
    if cleaned[0].isdigit():
        cleaned = "v_" + cleaned
    if cleaned in RESERVED:
        cleaned += "_"
    return cleaned


def snake(name: str) -> str:
    """lower_snake_case, splitting runs of capitals the way a reader would."""
    text = sanitize(name)
    text = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', text)
    text = re.sub(r'_+', '_', text).strip('_').lower()
    if not text:
        return "unnamed"
    if text[0].isdigit():
        text = "v_" + text
    if text in RESERVED:
        text += "_"
    return text


def camel(name: str) -> str:
    parts = [p for p in snake(name).split('_') if p]
    if not parts:
        return "unnamed"
    head = parts[0]
    out = head + "".join(p[:1].upper() + p[1:] for p in parts[1:])
    if out in RESERVED:
        out += "_"
    return out


def pascal(name: str) -> str:
    parts = [p for p in snake(name).split('_') if p]
    out = "".join(p[:1].upper() + p[1:] for p in parts) or "Unnamed"
    if out[0].isdigit():
        out = "N" + out
    return out


def unique(name: str, used: Set[str]) -> str:
    """`name` if it is free, else name_2, name_3 ... Records what it hands out."""
    candidate = name
    n = 2
    while candidate in used:
        candidate = f"{name}_{n}"
        n += 1
    used.add(candidate)
    return candidate


def signal_key(arrow: Arrow) -> str:
    """What identifies a signal ACROSS diagrams.

    The label: a decomposition restates it verbatim, while the ICOM letter-codes
    (I1, C2, M1) are positional and are reassigned per diagram, so keying on
    those would wire an activity's second input to its parent's second input
    whatever the two actually carry.
    """
    label = (arrow.label or "").strip()
    if label:
        return re.sub(r'\s+', ' ', label).lower()
    code = (arrow.icom_code or "").strip()
    if code:
        return code.lower()
    return (arrow.id or "unnamed").strip().lower()


@dataclass
class Flow:
    """One ICOM of one activity."""
    key: str                 # cross-diagram identity
    display: str             # human label, e.g. "Feedstock Material"
    code: str                # ICOM code, e.g. "I1" or "P.2.1"
    kind: str                # input | control | output | mechanism
    name: str = ""           # sanitised identifier, assigned by the exporter

    @property
    def qualified(self) -> str:
        return f"[{self.code}] {self.display}" if self.code else self.display


@dataclass
class Activity:
    """An IDEF0 box, resolved together with its ICOMs and its decomposition."""
    node_id: str                       # "A31"
    title: str                         # "Create Build Model"
    description: str = ""
    box: Optional[ActivityBox] = None
    diagram: Optional[Diagram] = None          # decomposition, if any
    parent: Optional["Activity"] = None
    children: List["Activity"] = field(default_factory=list)

    inputs: List[Flow] = field(default_factory=list)
    controls: List[Flow] = field(default_factory=list)
    outputs: List[Flow] = field(default_factory=list)
    mechanisms: List[Flow] = field(default_factory=list)

    # names claimed by the exporter, filled in by assign_names()
    name: str = ""

    @property
    def is_decomposed(self) -> bool:
        return bool(self.children)

    @property
    def parameters(self) -> List[Flow]:
        """Everything flowing IN, in IDEF0 reading order."""
        return self.inputs + self.controls + self.mechanisms

    def all_flows(self) -> List[Flow]:
        return self.inputs + self.controls + self.outputs + self.mechanisms

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


def _collect_flows(diagram: Optional[Diagram], box_id: str) -> Dict[str, List[Flow]]:
    """The ICOMs of one box, read off the diagram that box is drawn on.

    Every leg is read, branches included: a branch that carries a decomposed
    signal (P.3.1 off the M1 bus) is a distinct ICOM of the box it enters, and
    dropping it would leave that activity missing a parameter it is fed.
    """
    buckets = {"input": [], "control": [], "output": [], "mechanism": []}
    if not diagram:
        return buckets

    seen = set()
    for arrow in diagram.arrows:
        incoming = (arrow.target_box_id == box_id)
        outgoing = (arrow.source_box_id == box_id)
        if not (incoming or outgoing):
            continue
        kind = _KIND_OF_TYPE.get(arrow.type, "input")
        # Direction wins over the declared type: an arrow leaving the box is an
        # output of it whatever the type says, and one arriving is not.
        if outgoing and not incoming:
            kind = "output"
        elif incoming and kind == "output":
            kind = "input"

        key = signal_key(arrow)
        if (kind, key) in seen:
            continue
        seen.add((kind, key))
        buckets[kind].append(Flow(
            key=key,
            display=(arrow.label or arrow.icom_code or arrow.id or "unnamed").strip(),
            code=(arrow.icom_code or "").strip(),
            kind=kind,
        ))

    for bucket in buckets.values():
        bucket.sort(key=lambda f: (f.code or "~", f.display))
    return buckets


def _order_children(activity: Activity) -> List[Activity]:
    """Producers before consumers, with feedback edges left out of the ordering.

    A generated body assigns a signal where it is produced and reads it where it
    is consumed, so emitting boxes in id order let a read run ahead of its write.
    IDEF0 models legitimately contain feedback, so a cycle is broken rather than
    reported: the remaining boxes still come out in an order a reader can follow.
    """
    children = list(activity.children)
    produced: Dict[str, List[str]] = {}
    for child in children:
        for flow in child.outputs:
            produced.setdefault(flow.key, []).append(child.node_id)

    deps = {c.node_id: set() for c in children}
    for child in children:
        for flow in child.inputs + child.controls:
            for producer in produced.get(flow.key, ()):
                if producer != child.node_id:
                    deps[child.node_id].add(producer)

    by_id = {c.node_id: c for c in children}
    ordered: List[Activity] = []
    done: Set[str] = set()
    remaining = sorted(by_id, key=_natural_key)

    while remaining:
        ready = [nid for nid in remaining if deps[nid] <= done]
        if not ready:
            # A feedback loop: take the lowest-numbered box in it and carry on.
            ready = [remaining[0]]
        for nid in ready:
            ordered.append(by_id[nid])
            done.add(nid)
        remaining = [nid for nid in remaining if nid not in done]

    return ordered


def _natural_key(text: str):
    return [int(p) if p.isdigit() else p.lower()
            for p in re.split(r'(\d+)', text or "")]


def build_activity_tree(model: IDEF0Model) -> List[Activity]:
    """Resolve the model into activity roots, ICOMs and decomposition attached.

    Follows the IDEF0 hierarchy rather than the diagram list: the box drawn on
    A-0 is the root, and a box decomposes into the diagram whose node number
    matches its id.
    """
    by_node = {d.node_number: d for d in model.diagrams}

    def build(box: ActivityBox, parent_diagram: Diagram,
              parent: Optional[Activity], guard: Set[str]) -> Activity:
        flows = _collect_flows(parent_diagram, box.id)
        activity = Activity(
            node_id=box.id,
            title=(box.name or box.id).strip(),
            description=(box.description or "").strip(),
            box=box,
            parent=parent,
            inputs=flows["input"],
            controls=flows["control"],
            outputs=flows["output"],
            mechanisms=flows["mechanism"],
        )
        decomposition = by_node.get(box.id)
        # A model that decomposes a box into an ancestor of itself would recurse
        # for ever; the guard drops that edge and leaves the box a leaf.
        if decomposition and box.id not in guard:
            activity.diagram = decomposition
            inner = guard | {box.id}
            for child_box in sorted(decomposition.boxes, key=lambda b: _natural_key(b.id)):
                activity.children.append(build(child_box, decomposition, activity, inner))
            activity.children = _order_children(activity)
        return activity

    roots: List[Activity] = []
    context = by_node.get("A-0")
    if context and context.boxes:
        for box in context.boxes:
            roots.append(build(box, context, None, set()))
        return roots

    # No context diagram: fall back to the highest diagram that has boxes, and
    # treat every box on it as a root so nothing is silently dropped.
    for node in sorted(by_node, key=_natural_key):
        diagram = by_node[node]
        if diagram.boxes:
            for box in diagram.boxes:
                roots.append(build(box, diagram, None, set()))
            break
    return roots


def all_activities(model: IDEF0Model) -> List[Activity]:
    out: List[Activity] = []
    for root in build_activity_tree(model):
        out.extend(root.walk())
    return out


def distinct_signals(roots: List[Activity]) -> Dict[str, Flow]:
    """Every signal in the model once, keyed by cross-diagram identity."""
    signals: Dict[str, Flow] = {}
    for root in roots:
        for activity in root.walk():
            for flow in activity.all_flows():
                current = signals.get(flow.key)
                if current is None:
                    signals[flow.key] = Flow(key=flow.key, display=flow.display,
                                             code=flow.code, kind=flow.kind)
                elif not current.code and flow.code:
                    current.code = flow.code
    return signals


def wiring(activity: Activity) -> Dict[str, Optional[str]]:
    """For a decomposed activity: which child produces each signal read inside.

    Maps signal key -> node id of the producing child, or None when the signal
    arrives from the activity's own boundary.
    """
    produced: Dict[str, Optional[str]] = {}
    boundary = {f.key for f in activity.parameters}
    for child in activity.children:
        for flow in child.outputs:
            produced.setdefault(flow.key, child.node_id)
    for key in boundary:
        produced.setdefault(key, None)
    return produced


def model_title(model: IDEF0Model) -> str:
    return (getattr(model, "name", "") or "IDEF0 Model").strip() or "IDEF0 Model"
