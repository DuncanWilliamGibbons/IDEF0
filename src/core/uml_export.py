"""UML 2.5 export of an IDEF0 functional architecture, as XMI 2.1.

An IDEF0 diagram is an activity model, so that is what this writes - not a class
diagram that would throw the flows away:

    IDEF0 activity      -> uml:Activity (one per box, nested by decomposition)
    ICOM signal         -> uml:Class in a Signals package, used as a pin type
    input / control     -> in ownedParameter + ActivityParameterNode
    mechanism           -> in ownedParameter, commented as a mechanism
    output              -> out ownedParameter + ActivityParameterNode
    box on a diagram    -> uml:CallBehaviorAction calling that box's Activity
    arrow between boxes -> uml:ObjectFlow between the two pins

XMI ids are generated and every reference is written as an id, so the file loads
into a UML tool rather than needing one to interpret names.
"""
from typing import Dict
import xml.etree.ElementTree as ET

from src.core.export_common import (
    Activity, Flow, build_activity_tree, camel, distinct_signals, model_title,
    pascal,
)
from src.core.model import IDEF0Model

XMI_NS = "http://www.omg.org/spec/XMI/20131001"
UML_NS = "http://www.omg.org/spec/UML/20131001"

ET.register_namespace("xmi", XMI_NS)
ET.register_namespace("uml", UML_NS)

XMI_ID = f"{{{XMI_NS}}}id"
XMI_TYPE = f"{{{XMI_NS}}}type"
XMI_VERSION = f"{{{XMI_NS}}}version"


class _Ids:
    """Unique, readable, XML-safe ids."""

    def __init__(self):
        self.used = set()

    def make(self, *parts) -> str:
        base = "_".join(pascal(str(p)) for p in parts if str(p).strip()) or "Element"
        candidate, n = base, 2
        while candidate in self.used:
            candidate = f"{base}_{n}"
            n += 1
        self.used.add(candidate)
        return candidate


def export_to_uml(model: IDEF0Model) -> str:
    roots = build_activity_tree(model)
    signals = distinct_signals(roots)
    activities = [a for root in roots for a in root.walk()]
    ids = _Ids()

    xmi = ET.Element(f"{{{XMI_NS}}}XMI", {XMI_VERSION: "20131001"})
    uml_model = ET.SubElement(xmi, f"{{{UML_NS}}}Model", {
        XMI_ID: ids.make("Model"),
        "name": model_title(model),
    })
    _comment(uml_model, ids,
             f"Purpose: {getattr(model, 'purpose', '') or '-'} | "
             f"Viewpoint: {getattr(model, 'viewpoint', '') or '-'} | "
             f"Generated from an IDEF0 functional model.")

    # 1. Signals package - one Class per ICOM, used as the type of every pin.
    signals_pkg = ET.SubElement(uml_model, "packagedElement", {
        XMI_TYPE: "uml:Package",
        XMI_ID: ids.make("Signals"),
        "name": "Signals",
    })
    signal_ids: Dict[str, str] = {}
    for key in sorted(signals):
        flow = signals[key]
        signal_ids[key] = ids.make("Signal", flow.display or key)
        element = ET.SubElement(signals_pkg, "packagedElement", {
            XMI_TYPE: "uml:Class",
            XMI_ID: signal_ids[key],
            "name": pascal(flow.display or key),
        })
        if flow.code:
            _comment(element, ids, f"IDEF0 ICOM code {flow.code}")

    # 2. One Activity per IDEF0 box, so a CallBehaviorAction has something to call.
    activity_ids: Dict[str, str] = {}
    for activity in activities:
        activity_ids[activity.node_id] = ids.make("Activity", activity.node_id,
                                                  activity.title)

    behaviours_pkg = ET.SubElement(uml_model, "packagedElement", {
        XMI_TYPE: "uml:Package",
        XMI_ID: ids.make("Activities"),
        "name": "Activities",
    })
    for activity in activities:
        _write_activity(behaviours_pkg, activity, activity_ids, signal_ids, ids)

    ET.indent(xmi, space="  ")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            + ET.tostring(xmi, encoding="unicode") + "\n")


def _comment(parent: ET.Element, ids: _Ids, body: str) -> None:
    ET.SubElement(parent, "ownedComment", {
        XMI_TYPE: "uml:Comment",
        XMI_ID: ids.make("Comment"),
        "body": body,
    })


def _kind_label(flow: Flow) -> str:
    return f"IDEF0 {flow.kind}" + (f" {flow.code}" if flow.code else "")


def _write_activity(parent: ET.Element, activity: Activity,
                    activity_ids: Dict[str, str], signal_ids: Dict[str, str],
                    ids: _Ids) -> None:
    element = ET.SubElement(parent, "packagedElement", {
        XMI_TYPE: "uml:Activity",
        XMI_ID: activity_ids[activity.node_id],
        "name": f"{activity.node_id} {activity.title}",
    })
    body = f"IDEF0 node {activity.node_id}"
    if activity.description:
        body += f" - {activity.description}"
    _comment(element, ids, body)

    # Parameters, and the parameter nodes that let flows reach the boundary.
    param_node: Dict[str, str] = {}
    for flow in activity.parameters + activity.outputs:
        direction = "out" if flow.kind == "output" else "in"
        parameter_id = ids.make("Param", activity.node_id, flow.display)
        attrs = {
            XMI_TYPE: "uml:Parameter",
            XMI_ID: parameter_id,
            "name": camel(flow.display or flow.key),
            "direction": direction,
        }
        if flow.key in signal_ids:
            attrs["type"] = signal_ids[flow.key]
        parameter = ET.SubElement(element, "ownedParameter", attrs)
        _comment(parameter, ids, _kind_label(flow))

        node_attrs = {
            XMI_TYPE: "uml:ActivityParameterNode",
            XMI_ID: ids.make("ParamNode", activity.node_id, flow.display),
            "name": camel(flow.display or flow.key),
            "parameter": parameter_id,
        }
        if flow.key in signal_ids:
            node_attrs["type"] = signal_ids[flow.key]
        ET.SubElement(element, "node", node_attrs)
        param_node[flow.key] = node_attrs[XMI_ID]

    if not activity.children:
        return

    # One call per child box, with a pin per ICOM of that box.
    input_pin: Dict[str, Dict[str, str]] = {}
    output_pin: Dict[str, str] = {}
    for child in activity.children:
        call = ET.SubElement(element, "node", {
            XMI_TYPE: "uml:CallBehaviorAction",
            XMI_ID: ids.make("Call", activity.node_id, child.node_id),
            "name": f"{child.node_id} {child.title}",
            "behavior": activity_ids[child.node_id],
        })
        pins = {}
        for flow in child.parameters:
            attrs = {
                XMI_TYPE: "uml:InputPin",
                XMI_ID: ids.make("In", child.node_id, flow.display),
                "name": camel(flow.display or flow.key),
            }
            if flow.key in signal_ids:
                attrs["type"] = signal_ids[flow.key]
            pin = ET.SubElement(call, "argument", attrs)
            _comment(pin, ids, _kind_label(flow))
            pins[flow.key] = attrs[XMI_ID]
        input_pin[child.node_id] = pins

        for flow in child.outputs:
            attrs = {
                XMI_TYPE: "uml:OutputPin",
                XMI_ID: ids.make("Out", child.node_id, flow.display),
                "name": camel(flow.display or flow.key),
            }
            if flow.key in signal_ids:
                attrs["type"] = signal_ids[flow.key]
            pin = ET.SubElement(call, "result", attrs)
            _comment(pin, ids, _kind_label(flow))
            output_pin.setdefault(flow.key, attrs[XMI_ID])

    # Object flows: producer pin -> consumer pin, boundary node -> consumer pin,
    # and producer pin -> boundary node.
    for child in activity.children:
        for flow in child.parameters:
            target = input_pin[child.node_id].get(flow.key)
            if not target:
                continue
            source = output_pin.get(flow.key) or param_node.get(flow.key)
            if source and source != target:
                _object_flow(element, ids, source, target, flow)

    for flow in activity.outputs:
        source = output_pin.get(flow.key)
        target = param_node.get(flow.key)
        if source and target:
            _object_flow(element, ids, source, target, flow)


def _object_flow(parent: ET.Element, ids: _Ids, source: str, target: str,
                 flow: Flow) -> None:
    ET.SubElement(parent, "edge", {
        XMI_TYPE: "uml:ObjectFlow",
        XMI_ID: ids.make("Flow", source, target),
        "name": flow.qualified,
        "source": source,
        "target": target,
    })
