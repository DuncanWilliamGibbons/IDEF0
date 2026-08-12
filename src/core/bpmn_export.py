"""BPMN 2.0 XML export of an IDEF0 functional architecture.

IDEF0 says what each activity consumes and produces; BPMN says what happens
after what. The mapping reads the IDEF0 output-to-input arrows as the ordering
they imply, and keeps controls and mechanisms as data rather than pretending
they sequence anything:

    IDEF0 activity with a decomposition -> bpmn:process + bpmn:callActivity
    IDEF0 leaf activity                 -> bpmn:task
    output feeding another box's input  -> bpmn:sequenceFlow
    control / mechanism                 -> bpmn:dataObjectReference + association
    boundary input / output             -> bpmn:startEvent / bpmn:endEvent

Element order follows the BPMN 2.0 XSD - every flowElement before any artifact,
every process before any diagram - so the file opens in a BPMN tool instead of
failing schema validation.

Two things a reader needs that the semantic model alone does not carry:

  * a `bpmndi:BPMNDiagram` per process. BPMN separates what a process MEANS from
    where it is DRAWN, and a viewer built on bpmn-js (bpmn.io, Camunda Modeler)
    has nothing to put on the canvas without the DI half - it reports the file
    as containing no diagram. IDEF0 geometry does not carry over, so the shapes
    are laid out afresh, left to right by sequence depth.
  * a prefix on `calledElement`. It is an xsd:QName, and an unprefixed one with
    no default namespace in scope resolves to no namespace at all - not to the
    process it names in the target namespace.
"""
from typing import Dict, List, Set, Tuple
import xml.etree.ElementTree as ET

from src.core.export_common import (
    Activity, Flow, build_activity_tree, model_title, pascal,
)
from src.core.model import IDEF0Model

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"
TARGET_NS = "http://idef0.modeler/bpmn"
TARGET_PREFIX = "idef0"

ET.register_namespace("bpmn", BPMN_NS)
ET.register_namespace("bpmndi", BPMNDI_NS)
ET.register_namespace("dc", DC_NS)
ET.register_namespace("di", DI_NS)
ET.register_namespace(TARGET_PREFIX, TARGET_NS)

# Shape sizes a BPMN reader expects; anything else renders as an oddity.
TASK_W, TASK_H = 130.0, 80.0
EVENT_SIZE = 36.0
DATA_W, DATA_H = 36.0, 50.0
COLUMN, ROW = 220.0, 130.0
MARGIN = 60.0


def _q(tag: str) -> str:
    return f"{{{BPMN_NS}}}{tag}"


class _Plan:
    """Where one process's shapes and connections go on its own canvas."""

    def __init__(self, process_id: str, name: str):
        self.process_id = process_id
        self.name = name
        self.shapes: List[Tuple[str, float, float, float, float]] = []
        self.edges: List[Tuple[str, List[Tuple[float, float]]]] = []

    def shape(self, element_id, x, y, w, h):
        self.shapes.append((element_id, x, y, w, h))

    def edge(self, element_id, waypoints):
        self.edges.append((element_id, waypoints))


class _Ids:
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


def export_to_bpmn(model: IDEF0Model) -> str:
    roots = build_activity_tree(model)
    activities = [a for root in roots for a in root.walk()]
    ids = _Ids()

    definitions = ET.Element(_q("definitions"), {
        "id": ids.make("Definitions"),
        "targetNamespace": TARGET_NS,
        "exporter": "IDEF0 Modeler",
        "name": model_title(model),
    })

    process_id: Dict[str, str] = {}
    for activity in activities:
        if activity.children:
            process_id[activity.node_id] = ids.make("Process", activity.node_id)

    plans: List[_Plan] = []
    for activity in activities:
        if activity.children:
            plans.append(_write_process(definitions, activity, process_id, ids))

    if not process_id:
        # A model with no decomposition at all still exports one process, so the
        # file is never an empty shell.
        plans.append(_write_flat_process(definitions, activities, ids, model))

    # Every rootElement first, then the diagrams - the order the XSD sequences
    # them in, and the order a strict reader insists on.
    for plan in plans:
        _write_diagram(definitions, plan, ids)

    ET.indent(definitions, space="  ")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            + ET.tostring(definitions, encoding="unicode") + "\n")


def _write_diagram(definitions: ET.Element, plan: _Plan, ids: _Ids) -> None:
    diagram = ET.SubElement(definitions, f"{{{BPMNDI_NS}}}BPMNDiagram", {
        "id": ids.make("Diagram", plan.process_id),
        "name": plan.name,
    })
    plane = ET.SubElement(diagram, f"{{{BPMNDI_NS}}}BPMNPlane", {
        "id": ids.make("Plane", plan.process_id),
        "bpmnElement": plan.process_id,
    })
    for element_id, x, y, w, h in plan.shapes:
        shape = ET.SubElement(plane, f"{{{BPMNDI_NS}}}BPMNShape", {
            "id": ids.make("Shape", element_id),
            "bpmnElement": element_id,
        })
        ET.SubElement(shape, f"{{{DC_NS}}}Bounds", {
            "x": f"{x:.0f}", "y": f"{y:.0f}",
            "width": f"{w:.0f}", "height": f"{h:.0f}",
        })
    for element_id, waypoints in plan.edges:
        edge = ET.SubElement(plane, f"{{{BPMNDI_NS}}}BPMNEdge", {
            "id": ids.make("Edge", element_id),
            "bpmnElement": element_id,
        })
        for x, y in waypoints:
            ET.SubElement(edge, f"{{{DI_NS}}}waypoint",
                          {"x": f"{x:.0f}", "y": f"{y:.0f}"})


def _columns(node_ids: List[str], edges: Dict[str, Set[str]]) -> Dict[str, int]:
    """How far along the sequence each node sits, as a column number.

    Longest path from a node with nothing before it, so a task never lands left
    of something it waits on. A feedback loop cannot lengthen a path for ever -
    each node is settled once - so a cyclic model still lays out.
    """
    column = {nid: 0 for nid in node_ids}
    for _ in range(len(node_ids)):
        changed = False
        for source, targets in edges.items():
            for target in targets:
                if column.get(target, 0) < column.get(source, 0) + 1:
                    column[target] = column[source] + 1
                    changed = True
        if not changed:
            break
    return column


def _successors(activity: Activity) -> Dict[str, Set[str]]:
    """node id -> the child node ids it must run before, from the arrows."""
    producers: Dict[str, List[str]] = {}
    for child in activity.children:
        for flow in child.outputs:
            producers.setdefault(flow.key, []).append(child.node_id)

    edges = {c.node_id: set() for c in activity.children}
    for child in activity.children:
        for flow in child.inputs + child.controls:
            for producer in producers.get(flow.key, ()):
                if producer != child.node_id:
                    edges[producer].add(child.node_id)
    return edges


def _write_process(definitions: ET.Element, activity: Activity,
                   process_id: Dict[str, str], ids: _Ids) -> _Plan:
    process = ET.SubElement(definitions, _q("process"), {
        "id": process_id[activity.node_id],
        "name": f"{activity.node_id} {activity.title}",
        "isExecutable": "false",
    })
    ET.SubElement(process, _q("documentation")).text = (
        f"IDEF0 node {activity.node_id}"
        + (f" - {activity.description}" if activity.description else ""))

    edges = _successors(activity)
    predecessors = {c.node_id: set() for c in activity.children}
    for source, targets in edges.items():
        for target in targets:
            predecessors[target].add(source)

    # Tasks first, then the events that bracket them, then the flows.
    task_id: Dict[str, str] = {}
    elements: Dict[str, ET.Element] = {}
    for child in activity.children:
        tag = "callActivity" if child.children else "task"
        attrs = {
            "id": ids.make("Activity", child.node_id),
            "name": f"{child.node_id} {child.title}",
        }
        if child.children:
            # A QName, so it carries the prefix bound to the target namespace;
            # bare, it names a process in no namespace and resolves to nothing.
            attrs["calledElement"] = f"{TARGET_PREFIX}:{process_id[child.node_id]}"
        node = ET.SubElement(process, _q(tag), attrs)
        task_id[child.node_id] = attrs["id"]
        elements[child.node_id] = node

    start_id = ids.make("Start", activity.node_id)
    start = ET.SubElement(process, _q("startEvent"), {
        "id": start_id,
        "name": ", ".join(f.display for f in activity.inputs) or "Begin",
    })
    end_id = ids.make("End", activity.node_id)
    end = ET.SubElement(process, _q("endEvent"), {
        "id": end_id,
        "name": ", ".join(f.display for f in activity.outputs) or "Done",
    })

    # The XSD orders a flow node's children incoming* then outgoing*, so they are
    # collected here and written once every sequence flow exists.
    incoming: Dict[str, List[str]] = {}
    outgoing: Dict[str, List[str]] = {}

    def sequence(source_id: str, target_id: str, name: str = "") -> str:
        flow_id = ids.make("Flow", source_id, target_id)
        attrs = {"id": flow_id, "sourceRef": source_id, "targetRef": target_id}
        if name:
            attrs["name"] = name
        ET.SubElement(process, _q("sequenceFlow"), attrs)
        outgoing.setdefault(source_id, []).append(flow_id)
        incoming.setdefault(target_id, []).append(flow_id)
        return flow_id

    signal_name = {f.key: f.display
                   for child in activity.children for f in child.outputs}

    for child in activity.children:
        if not predecessors[child.node_id]:
            sequence(start_id, task_id[child.node_id])
        if not edges[child.node_id]:
            sequence(task_id[child.node_id], end_id)

    for source, targets in edges.items():
        for target in sorted(targets):
            carried = sorted({signal_name.get(f.key, "")
                              for f in _shared_signals(activity, source, target)})
            sequence(task_id[source], task_id[target],
                     ", ".join(n for n in carried if n))

    for node_id, node in elements.items():
        _write_connections(node, incoming.get(task_id[node_id], []),
                           outgoing.get(task_id[node_id], []))
    _write_connections(start, incoming.get(start_id, []), outgoing.get(start_id, []))
    _write_connections(end, incoming.get(end_id, []), outgoing.get(end_id, []))

    # Data: controls and mechanisms are not sequencing, so they are data objects
    # associated with the tasks that read them.
    data_ref: Dict[str, str] = {}
    for child in activity.children:
        for flow in child.controls + child.mechanisms:
            if flow.key in data_ref:
                continue
            object_id = ids.make("DataObject", flow.display)
            ET.SubElement(process, _q("dataObject"), {"id": object_id})
            reference_id = ids.make("DataObjectReference", flow.display)
            ET.SubElement(process, _q("dataObjectReference"), {
                "id": reference_id,
                "name": flow.qualified,
                "dataObjectRef": object_id,
            })
            data_ref[flow.key] = reference_id

    # Artifacts must follow every flowElement, per the BPMN 2.0 XSD.
    association_ends: List[Tuple[str, str, str]] = []
    for child in activity.children:
        for flow in child.controls + child.mechanisms:
            reference_id = data_ref.get(flow.key)
            if not reference_id:
                continue
            association_id = ids.make("Association", reference_id, child.node_id)
            ET.SubElement(process, _q("association"), {
                "id": association_id,
                "sourceRef": reference_id,
                "targetRef": task_id[child.node_id],
                "associationDirection": "One",
            })
            association_ends.append((association_id, reference_id,
                                     task_id[child.node_id]))

    return _lay_out(process_id[activity.node_id],
                    f"{activity.node_id} {activity.title}",
                    start_id, end_id, [task_id[c.node_id] for c in activity.children],
                    {task_id[s]: {task_id[t] for t in ts} for s, ts in edges.items()},
                    incoming, outgoing, list(data_ref.values()), association_ends)


def _lay_out(process_id: str, name: str, start_id: str, end_id: str,
             task_ids: List[str], task_edges: Dict[str, Set[str]],
             incoming: Dict[str, List[str]], outgoing: Dict[str, List[str]],
             data_ids: List[str],
             associations: List[Tuple[str, str, str]]) -> _Plan:
    """Place a process's shapes left to right and route its connections.

    IDEF0 lays a diagram out diagonally and BPMN reads left to right, so none of
    the modeller's geometry transfers. Columns come from how deep each task sits
    in the sequence, which is the only ordering the export actually asserts.
    """
    plan = _Plan(process_id, name)

    edges = dict(task_edges)
    edges.setdefault(start_id, set()).update(
        t for t in task_ids if not any(t in ts for ts in task_edges.values()))
    for task in task_ids:
        if not task_edges.get(task):
            edges.setdefault(task, set()).add(end_id)

    column = _columns([start_id] + task_ids + [end_id], edges)
    column[start_id] = 0
    column[end_id] = max(column.values(), default=0) + 1

    rows: Dict[int, int] = {}
    box: Dict[str, Tuple[float, float, float, float]] = {}
    for element_id in [start_id] + task_ids + [end_id]:
        col = column.get(element_id, 0)
        row = rows.get(col, 0)
        rows[col] = row + 1
        is_event = element_id in (start_id, end_id)
        w, h = (EVENT_SIZE, EVENT_SIZE) if is_event else (TASK_W, TASK_H)
        x = MARGIN + col * COLUMN
        y = MARGIN + row * ROW + (TASK_H - h) / 2
        box[element_id] = (x, y, w, h)
        plan.shape(element_id, x, y, w, h)

    def right(element_id):
        x, y, w, h = box[element_id]
        return (x + w, y + h / 2)

    def left(element_id):
        x, y, w, h = box[element_id]
        return (x, y + h / 2)

    seen_flows = set()
    for source, targets in edges.items():
        for target in targets:
            for flow_id in outgoing.get(source, []):
                if flow_id in incoming.get(target, []) and flow_id not in seen_flows:
                    seen_flows.add(flow_id)
                    plan.edge(flow_id, [right(source), left(target)])

    # Data objects sit under the band of tasks they govern.
    base_y = MARGIN + max(rows.values(), default=1) * ROW + 60
    data_box: Dict[str, Tuple[float, float, float, float]] = {}
    for i, reference_id in enumerate(data_ids):
        x, y = MARGIN + i * (DATA_W + 60), base_y
        data_box[reference_id] = (x, y, DATA_W, DATA_H)
        plan.shape(reference_id, x, y, DATA_W, DATA_H)

    for association_id, reference_id, target_id in associations:
        if reference_id not in data_box or target_id not in box:
            continue
        dx, dy, dw, dh = data_box[reference_id]
        tx, ty, tw, th = box[target_id]
        plan.edge(association_id,
                  [(dx + dw / 2, dy), (tx + tw / 2, ty + th)])
    return plan


def _write_connections(node: ET.Element, incoming: List[str],
                       outgoing: List[str]) -> None:
    for flow_id in incoming:
        ET.SubElement(node, _q("incoming")).text = flow_id
    for flow_id in outgoing:
        ET.SubElement(node, _q("outgoing")).text = flow_id


def _shared_signals(activity: Activity, source_id: str, target_id: str) -> List[Flow]:
    source = next(c for c in activity.children if c.node_id == source_id)
    target = next(c for c in activity.children if c.node_id == target_id)
    consumed = {f.key for f in target.inputs + target.controls}
    return [f for f in source.outputs if f.key in consumed]


def _write_flat_process(definitions: ET.Element, activities: List[Activity],
                        ids: _Ids, model: IDEF0Model) -> _Plan:
    process_id = ids.make("Process", "Model")
    process = ET.SubElement(definitions, _q("process"), {
        "id": process_id,
        "name": model_title(model),
        "isExecutable": "false",
    })
    start_id = ids.make("Start")
    start = ET.SubElement(process, _q("startEvent"), {"id": start_id, "name": "Begin"})
    end_id = ids.make("End")
    end = ET.SubElement(process, _q("endEvent"), {"id": end_id, "name": "Done"})
    incoming, outgoing = {}, {}
    previous, elements = start_id, {start_id: start, end_id: end}
    task_ids, chain = [], {}
    for activity in activities:
        task_id = ids.make("Activity", activity.node_id)
        task_ids.append(task_id)
        elements[task_id] = ET.SubElement(process, _q("task"), {
            "id": task_id, "name": f"{activity.node_id} {activity.title}"})
        flow_id = ids.make("Flow", previous, task_id)
        ET.SubElement(process, _q("sequenceFlow"), {
            "id": flow_id, "sourceRef": previous, "targetRef": task_id})
        outgoing.setdefault(previous, []).append(flow_id)
        incoming.setdefault(task_id, []).append(flow_id)
        chain.setdefault(previous, set()).add(task_id)
        previous = task_id
    flow_id = ids.make("Flow", previous, end_id)
    ET.SubElement(process, _q("sequenceFlow"), {
        "id": flow_id, "sourceRef": previous, "targetRef": end_id})
    outgoing.setdefault(previous, []).append(flow_id)
    incoming.setdefault(end_id, []).append(flow_id)
    chain.setdefault(previous, set()).add(end_id)
    for element_id, element in elements.items():
        _write_connections(element, incoming.get(element_id, []),
                           outgoing.get(element_id, []))

    return _lay_out(process_id, model_title(model), start_id, end_id, task_ids,
                    {s: {t for t in ts if t in task_ids}
                     for s, ts in chain.items() if s in task_ids},
                    incoming, outgoing, [], [])
