"""SysML v2 textual-notation export of an IDEF0 functional architecture.

IDEF0 and SysML v2 line up closely once the mapping is stated:

    IDEF0 activity  -> action def, and an action usage inside its parent
    input / control -> in item feature on the action def
    output          -> out item feature
    mechanism       -> part def that `perform`s the actions it enables
    arrow between   -> flow from <producer>.<feature> to <consumer>.<feature>
    two boxes

Every IDEF0 identifier the model carries - a box's node number, an arrow's ICOM
code - is written as an **attribute of the element it belongs to**:

    action def CreateBuildModel { attribute nodeId : String = "A31"; ... }
    item def BuildModel        { attribute icomCode : String = "D.4.4"; }

They used to be `// D.4.4` comments beside the declaration, and the node number
was also glued onto the front of the name (`A31CreateBuildModel`). Neither is
data: a comment is dropped by every parser that reads the file, and a name that
encodes a second field cannot be read back out of one without a convention no
tool knows. As attributes they survive the round trip and can be queried.

Which face of a box an arrow enters is IDEF0's whole point and does not belong
to the signal - the same item is an input at one action and a control at
another - so it is recorded on the feature rather than on the item def:

    in item designGuidelines : DesignGuidelines { attribute isControl = true; }

`isControl` is written only where it is true, the way UML writes `isAbstract`;
an `in item` without it is an input. A mechanism needs no such marker because it
is already a `ref part` rather than an `in item`.
"""
from typing import Dict, List, Set

from src.core.export_common import (
    Activity, Flow, build_activity_tree, camel, distinct_signals, model_title,
    pascal, unique,
)
from src.core.model import IDEF0Model

INDENT = "    "


def _escape(text: str) -> str:
    return (text or "").replace("*/", "* /").replace("\\", "/")


def _quote(text: str) -> str:
    """A SysML v2 string literal; nothing in an ICOM code has to be escaped."""
    return '"' + (text or "").replace("\\", "/").replace('"', "'") + '"'


def _readable(preferred: str, fallback: str, used: Set[str], case) -> str:
    """A name a reader recognises, made unique without a counter if it can be.

    The node number is no longer part of the name, so two boxes titled the same
    on different diagrams now collide. The tie is broken with the thing that
    actually distinguishes them - their node numbers - rather than a `_2` that
    tells a reader nothing.
    """
    first = case(preferred)
    if first not in used:
        used.add(first)
        return first
    second = case(f"{preferred} {fallback}")
    if second not in used:
        used.add(second)
        return second
    return unique(second, used)


def _assign_names(roots: List[Activity], signals: Dict[str, Flow]) -> Dict[str, str]:
    """Unique action def / usage names, and one feature name per signal."""
    used_defs: Set[str] = set()
    used_usages: Set[str] = set()
    used_types: Set[str] = set()
    used_features: Set[str] = set()
    feature_of: Dict[str, str] = {}

    for key, flow in signals.items():
        feature_of[key] = unique(camel(flow.display or flow.code or key), used_features)
        flow.name = unique(pascal(flow.display or flow.code or key), used_types)

    for root in roots:
        for activity in root.walk():
            activity.name = _readable(activity.title, activity.node_id,
                                      used_defs, pascal)
            activity.usage_name = _readable(activity.title, activity.node_id,
                                            used_usages, camel)
            for flow in activity.all_flows():
                flow.name = feature_of[flow.key]
    return feature_of


def export_to_sysml(model: IDEF0Model) -> str:
    roots = build_activity_tree(model)
    signals = distinct_signals(roots)
    feature_of = _assign_names(roots, signals)
    activities = [a for root in roots for a in root.walk()]

    lines: List[str] = [
        f"package {pascal(model_title(model))} {{",
        f"{INDENT}doc /* {_escape(model_title(model))}",
        f"{INDENT} *  Purpose:   {_escape(getattr(model, 'purpose', '') or '-')}",
        f"{INDENT} *  Viewpoint: {_escape(getattr(model, 'viewpoint', '') or '-')}",
        f"{INDENT} *  Generated from an IDEF0 functional model.",
        f"{INDENT} */",
        "",
        # String and Boolean live in the standard library, and the attributes
        # below are typed by them.
        f"{INDENT}import ScalarValues::*;",
        "",
    ]

    # 1. Items - everything that flows, except mechanisms, which are parts.
    mechanism_keys = {f.key for a in activities for f in a.mechanisms}
    item_keys = [k for k in signals if k not in mechanism_keys]
    if item_keys:
        lines.append(f"{INDENT}// Items: every signal that flows between actions")
        for key in sorted(item_keys):
            lines.extend(_signal_def("item def", signals[key], depth=1))
        lines.append("")

    # 2. Parts - the mechanisms that carry actions out.
    if mechanism_keys:
        lines.append(f"{INDENT}// Parts: the mechanisms that perform the actions")
        for key in sorted(mechanism_keys):
            performers = [a for a in activities
                          if any(m.key == key for m in a.mechanisms)]
            body = [
                # Typed by the action def, not a bare reference to the usage of
                # the same name: that usage lives inside another action def and
                # is not in scope from a part def at package level, so the plain
                # `perform action createBuildModel;` resolved to nothing.
                f"{INDENT * 2}perform action {a.usage_name} : {a.name};"
                for a in performers
            ]
            lines.extend(_signal_def("part def", signals[key], depth=1, body=body))
        lines.append("")

    # 3. Action definitions - features first, then the decomposition.
    lines.append(f"{INDENT}// Actions: one per IDEF0 activity")
    for activity in activities:
        lines.extend(_action_def(activity, signals, feature_of, depth=1))
        lines.append("")

    # 4. The model's root as a usage, so the package has an entry point.
    for root in roots:
        lines.append(f"{INDENT}action {root.usage_name} : {root.name};")

    lines.append("}")
    return "\n".join(lines) + "\n"


def _signal_def(keyword: str, flow: Flow, depth: int,
                body: List[str] = ()) -> List[str]:
    """`item def X;`, or with a body when it carries a code or holds anything."""
    tab = INDENT * depth
    name = pascal(flow.display or flow.key)
    inner = list(body)
    if flow.code:
        inner.insert(0, f"{tab}{INDENT}attribute icomCode : String = "
                        f"{_quote(flow.code)};")
    if not inner:
        return [f"{tab}{keyword} {name};"]
    return [f"{tab}{keyword} {name} {{", *inner, f"{tab}}}"]


def _type_name(flow: Flow, signals: Dict[str, Flow]) -> str:
    known = signals.get(flow.key)
    return pascal((known.display if known else flow.display) or flow.key)


def _feature(keyword: str, flow: Flow, signals: Dict[str, Flow], indent: str,
             is_control: bool = False) -> List[str]:
    """One ICOM as a feature, carrying whatever the model states about it."""
    declaration = f"{indent}{keyword} {flow.name} : {_type_name(flow, signals)}"
    attributes = []
    if is_control:
        attributes.append(f"{indent}{INDENT}attribute isControl : Boolean = true;")
    if not attributes:
        return [f"{declaration};"]
    return [f"{declaration} {{", *attributes, f"{indent}}}"]


def _action_def(activity: Activity, signals: Dict[str, Flow],
                feature_of: Dict[str, str], depth: int) -> List[str]:
    tab = INDENT * depth
    inner = INDENT * (depth + 1)
    lines = [f"{tab}action def {activity.name} {{",
             f"{inner}attribute nodeId : String = {_quote(activity.node_id)};",
             f"{inner}doc /* {_escape(activity.title)} */"]
    if activity.description:
        lines.append(f"{inner}doc /* {_escape(activity.description)} */")

    for flow in activity.inputs:
        lines.extend(_feature("in item", flow, signals, inner))
    for flow in activity.controls:
        lines.extend(_feature("in item", flow, signals, inner, is_control=True))
    for flow in activity.outputs:
        lines.extend(_feature("out item", flow, signals, inner))
    for flow in activity.mechanisms:
        lines.extend(_feature("ref part", flow, signals, inner))

    if activity.children:
        lines.append("")
        lines.append(f"{inner}// Decomposition ({activity.diagram.node_number})"
                     if activity.diagram else f"{inner}// Decomposition")
        for child in activity.children:
            lines.append(f"{inner}action {child.usage_name} : {child.name};")

        flows = _internal_flows(activity)
        if flows:
            lines.append("")
            lines.append(f"{inner}// Flows")
            for text in flows:
                lines.append(f"{inner}{text}")

    lines.append(f"{tab}}}")
    return lines


def _internal_flows(activity: Activity) -> List[str]:
    """`flow from producer.feature to consumer.feature`, boundaries included."""
    produced: Dict[str, str] = {}
    for child in activity.children:
        for flow in child.outputs:
            produced.setdefault(flow.key, child.usage_name)
    boundary_in = {f.key: f for f in activity.parameters}
    boundary_out = {f.key: f for f in activity.outputs}

    out: List[str] = []
    for child in activity.children:
        for flow in child.inputs + child.controls + child.mechanisms:
            source = produced.get(flow.key)
            if source and source != child.usage_name:
                out.append(f"flow from {source}.{flow.name} "
                           f"to {child.usage_name}.{flow.name};")
            elif flow.key in boundary_in:
                out.append(f"flow from {flow.name} "
                           f"to {child.usage_name}.{flow.name};")
    for key, flow in boundary_out.items():
        source = produced.get(key)
        if source:
            out.append(f"flow from {source}.{flow.name} to {flow.name};")

    seen, unique_flows = set(), []
    for text in out:
        if text not in seen:
            seen.add(text)
            unique_flows.append(text)
    return unique_flows
