from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import re

class ArrowType(Enum):
    INPUT = "Input"
    CONTROL = "Control"
    OUTPUT = "Output"
    MECHANISM = "Mechanism"
    CALL = "Call"

@dataclass
class Point:
    x: float
    y: float

def simplify_path(points: List[Point]) -> List[Point]:
    """Removes collinear, duplicate, extremely short segments, overshoots, and U-turn jogs from a Manhattan path."""
    if len(points) < 2:
        return points
    
    # 1. Remove duplicate and extremely nearby points (strict 1px epsilon)
    deduped = [Point(round(points[0].x), round(points[0].y))]
    for i in range(1, len(points)):
        rx, ry = round(points[i].x), round(points[i].y)
        p1 = deduped[-1]
        if abs(p1.x - rx) > 0.5 or abs(p1.y - ry) > 0.5:
             deduped.append(Point(rx, ry))
    
    if len(deduped) < 3:
        return deduped
        
    # 2. Remove collinear points and 180-degree back-and-forth overshoots
    simplified = [deduped[0]]
    for i in range(1, len(deduped) - 1):
        p_prev = simplified[-1]
        p_curr = deduped[i]
        p_next = deduped[i+1]
        
        # Collinear check
        is_collinear_h = abs(p_prev.y - p_curr.y) < 0.5 and abs(p_curr.y - p_next.y) < 0.5
        is_collinear_v = abs(p_prev.x - p_curr.x) < 0.5 and abs(p_curr.x - p_next.x) < 0.5
        
        # Backtracking overshoot check: p_curr extends past p_next along the same axis and then returns
        is_overshoot_h = abs(p_prev.y - p_curr.y) < 0.5 and abs(p_curr.y - p_next.y) < 0.5 and ((p_prev.x <= p_next.x <= p_curr.x) or (p_prev.x >= p_next.x >= p_curr.x))
        is_overshoot_v = abs(p_prev.x - p_curr.x) < 0.5 and abs(p_curr.x - p_next.x) < 0.5 and ((p_prev.y <= p_next.y <= p_curr.y) or (p_prev.y >= p_next.y >= p_curr.y))
        
        if not (is_collinear_h or is_collinear_v or is_overshoot_h or is_overshoot_v):
            simplified.append(p_curr)
            
    simplified.append(deduped[-1])
    
    # 3. Remove very short U-turn jogs and spike overshoots
    MIN_SEGMENT_LEN = 5.0
    changed = True
    while changed and len(simplified) >= 3:
        changed = False
        cleaned = [simplified[0]]
        i = 1
        while i < len(simplified) - 1:
            p_prev = cleaned[-1]
            p_curr = simplified[i]
            p_next = simplified[i+1]
            
            seg_len = abs(p_curr.x - p_prev.x) + abs(p_curr.y - p_prev.y)
            seg_len_next = abs(p_next.x - p_curr.x) + abs(p_next.y - p_curr.y)
            
            is_short_jog = False
            if seg_len < MIN_SEGMENT_LEN:
                if abs(p_prev.y - p_next.y) < 1.0 or abs(p_prev.x - p_next.x) < 1.0:
                    is_short_jog = True
            if seg_len_next < MIN_SEGMENT_LEN:
                if abs(p_prev.y - p_next.y) < 1.0 or abs(p_prev.x - p_next.x) < 1.0:
                    is_short_jog = True
                    
            if is_short_jog:
                changed = True
                i += 1
            else:
                cleaned.append(p_curr)
                i += 1
        cleaned.append(simplified[-1])
        simplified = cleaned
    
    return simplified

@dataclass
class ActivityBox:
    id: str  # e.g., "A1"
    name: str
    description: str = ""
    # Position will be calculated by the layout engine, but stored here
    x: float = 0.0
    y: float = 0.0
    width: float = 150.0
    height: float = 100.0
    
    # Font Properties
    font_family: str = "Arial"
    font_size: int = 10
    font_bold: bool = False
    font_italic: bool = False
    
    # Visual Properties
    color: str = "#ffffff"

@dataclass
class Arrow:
    id: str
    source_box_id: Optional[str]  # None means external source
    target_box_id: Optional[str]  # None means external target
    type: ArrowType
    label: str
    description: str = ""
    segments: List[Point] = field(default_factory=list) # For Manhattan routing points
    
    # Branching/Forking
    branch_parent_id: Optional[str] = None  # If this arrow branches from another arrow
    join_target_id: Optional[str] = None    # If this arrow joins into another arrow
    is_manual_connection: bool = False      # If this connection was manually assigned
    junction_point: Optional[Point] = None  # The point on the parent/target arrow where this arrow connects
    
    # Junction dots for other arrows connecting TO this one
    branch_points: List[Point] = field(default_factory=list) # Dots for arrows branching FROM this one
    join_points: List[Point] = field(default_factory=list)   # Dots for arrows joining INTO this one
    
    # Tunneling: Arrows can be hidden in decomposition
    tunnel_source: bool = False  # True = arrow tail has parentheses (hidden source, now appearing)
    tunnel_target: bool = False  # True = arrow head has parentheses (will be hidden in child diagram)
    
    # Manual UI adjustments
    label_offset_x: float = 0.0
    label_offset_y: float = 0.0
    
    # Visual Properties
    color: str = "#000000"
    thickness: int = 2
    style: str = "Solid" # Solid, Dashed, Dotted, DotDash
    arrowhead_style: str = "Standard" # Standard, Open, Stealth
    
    # ICOM Reference Notation (ISO/IEC/IEEE 31320-1)
    # Two identities, kept apart on purpose:
    #   icom_code       - the ID the MODELLER assigns, e.g. "P.2" or "D.4.1".
    #                     Never generated, never overwritten by the tool.
    #   auto_icom_code  - the positional code the STANDARD defines, e.g. "O1".
    #                     Always regenerated from the diagram, never edited into
    #                     something the standard would not produce.
    # Holding both in one field meant assigning "P.2" silently destroyed the
    # "O1" the standard requires, and the two can now be shown together.
    icom_code: Optional[str] = None       # user-defined, e.g. "P.2"
    auto_icom_code: Optional[str] = None  # standard code, e.g. "O1"
    # Set when the modeller typed the standard code by hand, so the generator
    # leaves it alone. Clearing the field clears this too and hands the arrow
    # back to the generator.
    auto_icom_code_manual: bool = False
    
    # Label Font Properties
    label_font_family: str = "Arial"
    label_font_size: int = 9
    label_font_bold: bool = False
    label_font_italic: bool = False
    label_color: str = "#000000"
    icom_callout_style: str = "Jagged"
    hide_label: bool = False
    
    def is_boundary(self):
        """Returns True if this arrow is a boundary signal (one end disconnected and not a branch/join)."""
        # A true boundary "Trunk" has one end fundamentally disconnected 
        # AND it is not itself a branch or join of another boundary signal.
        is_in = (self.source_box_id is None and self.branch_parent_id is None)
        is_out = (self.target_box_id is None and self.join_target_id is None)
        return is_in or is_out

@dataclass
class Diagram:
    node_number: str # e.g., "A0"
    title: str
    boxes: List[ActivityBox] = field(default_factory=list)
    arrows: List[Arrow] = field(default_factory=list)
    parent_diagram_id: Optional[str] = None
    c_number: str = ""

class IDEF0Model:
    def __init__(self, name: str):
        self.name = name
        self.purpose: str = "<Enter purpose>"
        self.viewpoint: str = "<Enter viewpoint>"
        
        # Frame Context Info
        self.author: str = "Author Name"
        self.date_created: str = "2025-01-20" # Default, should ideally be dynamic
        self.version: str = "1.0"
        
        self.diagrams: List[Diagram] = []
        # All models must have a Context Diagram A-0
        self.add_diagram(Diagram(node_number="A-0", title=f"Context - {name}"))
        
    def add_diagram(self, diagram: Diagram):
        self.diagrams.append(diagram)
        
    def get_diagram(self, node_number: str) -> Optional[Diagram]:
        for d in self.diagrams:
            if d.node_number == node_number:
                return d
        return None

    def _clean_arrow_ids(self):
        """Removes administrative prefixes from all arrow IDs across all diagrams."""
        for d in self.diagrams:
            for arrow in d.arrows:
                old_id = arrow.id
                new_id = old_id
                
                # Strip prefixes case-insensitively and with/without underscores
                prefixes_to_strip = ["Bound_", "Bound", "FromChild_", "FromChild"]
                for pref in prefixes_to_strip:
                    if new_id.lower().startswith(pref.lower()):
                        new_id = new_id[len(pref):]
                
                # Clean up any leading underscores or junk
                new_id = new_id.lstrip("_")
                
                if not new_id:
                     new_id = arrow.label[:5] if arrow.label else f"{arrow.type.value}_1"
                
                # Ensure local uniqueness in this diagram
                temp_id = new_id
                idx = 1
                while any(a.id == temp_id and a is not arrow for a in d.arrows):
                    temp_id = f"{new_id}_{idx}"
                    idx += 1
                
                arrow.id = temp_id

    def delete_arrow_globally(self, arrow_id: str):
        """Removes the specified arrow from all diagrams in the project model."""
        for diag in self.diagrams:
            diag.arrows = [a for a in diag.arrows if a.id != arrow_id]
            # Drop dangling references to the deleted arrow held by its neighbours
            for a in diag.arrows:
                if a.branch_parent_id == arrow_id:
                    a.branch_parent_id = None
                if a.join_target_id == arrow_id:
                    a.join_target_id = None

    def get_parent_box_and_diagram(self, diagram_id: str) -> Tuple[Optional[ActivityBox], Optional[Diagram]]:
        """
        Returns the parent box and diagram that decomposes into diagram_id.
        """
        for d in self.diagrams:
            for box in d.boxes:
                # 1. Match by ID
                if box.id == diagram_id:
                    return box, d
                # 2. Try to find if this box is the "root" of the decomposition
                # In IDEF0, Box A1 in parent decomposes to Diagram A1.
                # Box A0 (context) decomposes to Diagram A0.
                pass
        return None, None

    def synchronize_boundaries(self, diagram_id: str):
        """
        Ensures consistency between a child diagram's boundary arrows 
        and the parent box's arrow segments.
        """
        self._clean_arrow_ids() # Ensure all IDs are universal and prefix-free
        
        diagram = self.get_diagram(diagram_id)
        if not diagram: return
        
        parent_box, parent_diag = self.get_parent_box_and_diagram(diagram_id)
        if not parent_box or not parent_diag: return
        
        # 1. Parent -> Child: Every arrow on parent_box in parent_diag
        # must have a corresponding boundary arrow in child diagram.
        parent_arrows = [a for a in parent_diag.arrows if a.source_box_id == parent_box.id or a.target_box_id == parent_box.id]
        
        for pa in parent_arrows:
            # Check if this parent arrow already has a corresponding child boundary arrow
            is_parent_input = (pa.target_box_id == parent_box.id)
            is_parent_output = (pa.source_box_id == parent_box.id)
            
            match = None
            for ca in diagram.arrows:
                # A boundary arrow in child is one with one side free
                ca_is_in = (ca.source_box_id is None and ca.branch_parent_id is None)
                ca_is_out = (ca.target_box_id is None and ca.join_target_id is None)
                
                if is_parent_input and not ca_is_in: continue
                if is_parent_output and not ca_is_out: continue
                if pa.type != ca.type: continue

                # Match by label (case-insensitive) OR by ID
                pa_label = (pa.label or "").strip().lower()
                ca_label = (ca.label or "").strip().lower()
                
                if (pa_label and pa_label == ca_label) or (ca.id == pa.id):
                    match = ca
                    break
            
            if not match:
                # Create a new boundary arrow in child (Trunk stub)
                # Use the Parent's ID directly to ensure "P.2" consistency across diagrams
                new_arrow = Arrow(
                    id=pa.id, 
                    source_box_id=None,
                    target_box_id=None,
                    type=pa.type,
                    label=pa.label,
                    icom_code=pa.icom_code # Shared ICOM code (e.g. P.2)
                )
                diagram.arrows.append(new_arrow)
            else:
                # Synchronize labels and ICOM codes bidirectionally
                icom_pattern = re.compile(r'^[OICM]\d+$')
                
                # Sync label
                if ca.label and not pa.label:
                    pa.label = ca.label
                elif pa.label and not ca.label:
                    ca.label = pa.label
                elif pa.label != ca.label:
                    if ca.label: pa.label = ca.label
                    else: ca.label = pa.label
                
                # Sync icom_code
                ca_custom = ca.icom_code and not icom_pattern.match(ca.icom_code)
                pa_custom = pa.icom_code and not icom_pattern.match(pa.icom_code)
                
                if ca_custom and not pa_custom:
                    pa.icom_code = ca.icom_code
                elif pa_custom and not ca_custom:
                    ca.icom_code = pa.icom_code
                elif ca.icom_code != pa.icom_code:
                    if ca.icom_code: pa.icom_code = ca.icom_code
                    else: ca.icom_code = pa.icom_code
        
        # 3. Consolidation: Group matching boundary stubs into buses
        consolidate_boundary_arrows(diagram)
        
        # 4. Child -> Parent: True boundary arrows in child diagram
        # must appear as arrows on parent_box in parent_diag.
        # Build a set of arrow IDs that are branch parents or join targets
        # (i.e., trunks that only exist to fan out to child branches).
        child_arrow_map = {a.id: a for a in diagram.arrows}
        trunk_only_ids = set()
        for a in diagram.arrows:
            if a.branch_parent_id and a.branch_parent_id in child_arrow_map:
                trunk_only_ids.add(a.branch_parent_id)
            if a.join_target_id and a.join_target_id in child_arrow_map:
                trunk_only_ids.add(a.join_target_id)
        
        # Refresh parent_arrows list (may have been modified above)
        parent_arrows = [a for a in parent_diag.arrows if a.source_box_id == parent_box.id or a.target_box_id == parent_box.id]
        
        for ca in diagram.arrows:
            # Skip arrows that are branches/joins of another arrow —
            # they are internal decomposition details, not true boundaries.
            if ca.branch_parent_id is not None:
                continue
            if ca.join_target_id is not None:
                continue
            
            # A true boundary arrow in the child is one that has no box on one side
            # AND no branch/join on that same side.
            is_true_boundary_input = (ca.source_box_id is None)
            is_true_boundary_output = (ca.target_box_id is None)
            
            if not (is_true_boundary_input or is_true_boundary_output):
                continue
            
            # Skip trunk-only arrows: arrows that exist solely as parents for
            # branches within this diagram. They don't represent a real boundary
            # signal at the parent level — only their children do.
            if ca.id in trunk_only_ids:
                # Check if this trunk also connects to a box itself
                has_own_box = (ca.source_box_id is not None or ca.target_box_id is not None)
                if not has_own_box:
                    continue
                
            # Look for match in parent
            match = None
            for pa in parent_arrows:
                is_parent_input = (pa.target_box_id == parent_box.id)
                is_parent_output = (pa.source_box_id == parent_box.id)
                
                orientation_match = (is_true_boundary_input and is_parent_input) or \
                                   (is_true_boundary_output and is_parent_output)
                
                if (pa.id == ca.id) or (pa.label == ca.label and pa.type == ca.type and orientation_match and ca.label):
                    match = pa
                    break
            
            if not match:
                # Create in parent using the SAME ID as child
                new_pa_id = ca.id
                idx = 1
                while any(a.id == new_pa_id for a in parent_diag.arrows):
                    new_pa_id = f"{ca.id}_{idx}"
                    idx += 1
                
                new_pa = Arrow(
                    id=new_pa_id,
                    source_box_id=None if is_true_boundary_input else parent_box.id,
                    target_box_id=parent_box.id if is_true_boundary_input else None,
                    type=ca.type,
                    label=ca.label,
                    icom_code=ca.icom_code
                )
                parent_diag.arrows.append(new_pa)
            else:
                # Sync labels and ICOM codes bidirectionally
                icom_pattern = re.compile(r'^[OICM]\d+$')
                
                if ca.label and not match.label:
                    match.label = ca.label
                elif match.label and not ca.label:
                    ca.label = match.label
                elif match.label != ca.label:
                    if ca.label: match.label = ca.label
                    else: ca.label = match.label
                
                ca_custom = ca.icom_code and not icom_pattern.match(ca.icom_code)
                ma_custom = match.icom_code and not icom_pattern.match(match.icom_code)
                
                if ca_custom and not ma_custom:
                    match.icom_code = ca.icom_code
                elif ma_custom and not ca_custom:
                    ca.icom_code = match.icom_code
                elif ca.icom_code != match.icom_code:
                    if ca.icom_code: match.icom_code = ca.icom_code
                    else: ca.icom_code = match.icom_code

    def get_node_tree(self) -> List[dict]:
        """Returns a nested structure representing the function decomposition hierarchy."""
        def build_node(box_id, box_name):
            node = {
                "id": box_id,
                "text": f"{box_id} {box_name}",
                "children": []
            }
            # Find decomposition diagram for this box
            decomp = self.get_diagram(box_id)
            if decomp:
                # Add all boxes from this decomposition as children
                for box in sorted(decomp.boxes, key=lambda x: x.id):
                    node["children"].append(build_node(box.id, box.name))
            return node

        # Start from A-0 Context Diagram
        context_diag = self.get_diagram("A-0")
        if context_diag and context_diag.boxes:
            # Context diagram has exactly one box: A0
            root_box = context_diag.boxes[0]
            return [build_node(root_box.id, root_box.name)]
        
        # Fallback: if A-0 is empty or missing, try A0 diagram directly
        a0_diag = self.get_diagram("A0")
        if a0_diag:
            # Root "virtual" node for A0 diagram title or something similar
            root = {
                "id": "A0",
                "text": f"A0 {a0_diag.title}",
                "children": []
            }
            for box in sorted(a0_diag.boxes, key=lambda x: x.id):
                root["children"].append(build_node(box.id, box.name))
            return [root]
            
        return []
@dataclass
class IDEF0Project:
    model: IDEF0Model
    metadata: dict = field(default_factory=dict)

def get_default_icom_code(arrow_id: str, current_icom: str = None) -> Optional[str]:
    import re
    if current_icom:
        # Check if it has any digits or separators (. or -)
        if any(c.isdigit() for c in current_icom) or '.' in current_icom or '-' in current_icom:
            return current_icom.strip()
            
    if arrow_id and not arrow_id.startswith("Arrow_") and not arrow_id.startswith("Trunk_"):
        # Strip diagram suffix like _A21 or _A2, replacing underscore box suffix with dot for branches
        clean_id = arrow_id.strip()
        clean_id = re.sub(r'_(?:A?\d+|\d+)(?:_[A-Za-z0-9_]+)*$', '', clean_id)
        # Check if it has digits or separators
        if any(c.isdigit() for c in clean_id) or '.' in clean_id or '-' in clean_id:
            return clean_id
    return None

STANDARD_ICOM_PATTERN = re.compile(r'^[OICM]\d+$')


def split_legacy_icom_code(arrow: "Arrow"):
    """Move a standard code out of the user field it used to share.

    Before the two identities were separated, `icom_code` held whichever of them
    had been written last, so a model saved earlier can carry "C2" in the field
    the modeller now owns. A value the generator would itself produce belongs to
    the generator, so it is moved across rather than shown as a user's choice.
    """
    code = (arrow.icom_code or "").strip()
    if code and STANDARD_ICOM_PATTERN.match(code):
        if not arrow.auto_icom_code:
            arrow.auto_icom_code = code
        arrow.icom_code = None


def generate_icom_codes(diagram: Diagram):
    """
    Consolidates boundary signals and assigns ICOM codes (C1, I2, etc.)
    based on their position and type.
    """
    # Clean and initialize default ICOM codes
    for a in diagram.arrows:
        a.icom_code = get_default_icom_code(a.id, a.icom_code)
        split_legacy_icom_code(a)

    # 1. First, consolidate related boundary arrows into buses (Trunks + Branches/Joins)
    consolidate_boundary_arrows(diagram)
    
    inputs = []
    controls = []
    mechanisms = []
    outputs = []
    
    def get_arrow_pos(a):
        # Prefer actual segment start/end if available
        if a.segments:
            if a.source_box_id is None and a.branch_parent_id is None: 
                return a.segments[0].x if a.type in [ArrowType.CONTROL, ArrowType.MECHANISM] else a.segments[0].y
            return a.segments[-1].y # Output
            
        # Fallback to connected box coordinates
        found_box = None
        for b in diagram.boxes:
            if b.id == a.source_box_id or b.id == a.target_box_id:
                found_box = b
                break
        
        if not found_box: return 0
        return found_box.x if a.type in [ArrowType.CONTROL, ArrowType.MECHANISM] else found_box.y

    for arrow in diagram.arrows:
        # A true boundary "Trunk" has one end fundamentally disconnected 
        # AND it is not itself a branch or join of another boundary signal.
        is_boundary_in = (arrow.source_box_id is None and arrow.branch_parent_id is None)
        is_boundary_out = (arrow.target_box_id is None and arrow.join_target_id is None)
        
        if is_boundary_in or is_boundary_out:
            if arrow.type == ArrowType.CONTROL: controls.append(arrow)
            elif arrow.type == ArrowType.MECHANISM: mechanisms.append(arrow)
            elif arrow.type == ArrowType.INPUT: inputs.append(arrow)
            elif arrow.type == ArrowType.OUTPUT: outputs.append(arrow)

    # Sort and assign the standard positional codes. These go in their own field,
    # so a modeller's "P.2" is neither overwritten by nor able to overwrite the
    # "O1" the standard requires for the same arrow.
    import re

    for group, letter in ((controls, "C"), (inputs, "I"),
                          (mechanisms, "M"), (outputs, "O")):
        group.sort(key=get_arrow_pos)
        for i, arrow in enumerate(group, 1):
            if not arrow.auto_icom_code_manual:
                arrow.auto_icom_code = f"{letter}{i}"

    # Propagate codes to child branch/join arrows that are NOT specialized/decomposed
    arrow_map = {a.id: a for a in diagram.arrows}
    for a in diagram.arrows:
        p_id = a.branch_parent_id or a.join_target_id
        if p_id:
            parent = arrow_map.get(p_id)
            if parent:
                is_specialized = False
                child_clean = re.sub(r'_(?:A?\d+|\d+)(?:_[A-Za-z0-9_]+)*$', '', a.id)
                parent_clean = re.sub(r'_(?:A?\d+|\d+)(?:_[A-Za-z0-9_]+)*$', '', parent.id)
                if child_clean.startswith(f"{parent_clean}."):
                    is_specialized = True
                c_lbl = (a.label or "").strip().lower()
                p_lbl = (parent.label or "").strip().lower()
                if c_lbl and p_lbl and c_lbl != p_lbl:
                    is_specialized = True
                if a.icom_code and parent.icom_code:
                    c_ic = a.icom_code.strip().lower()
                    p_ic = parent.icom_code.strip().lower()
                    if c_ic.startswith(p_ic + "."):
                        is_specialized = True

                if not is_specialized:
                    a.icom_code = parent.icom_code
                    if not a.auto_icom_code_manual:
                        a.auto_icom_code = parent.auto_icom_code

def consolidate_boundary_arrows(diagram: Diagram):
    """
    Identifies related boundary arrows and links them into buses (Trunks + Joins/Branches)
    based on label/ICOM hierarchy first, then label similarity.
    """
    # Clean and initialize default ICOM codes
    for a in diagram.arrows:
        a.icom_code = get_default_icom_code(a.id, a.icom_code)
        split_legacy_icom_code(a)

    import re

    arrow_map = {a.id: a for a in diagram.arrows}
    box_map = {b.id: b for b in diagram.boxes}
    
    def get_arrow_signatures(arrow):
        sigs = []
        if arrow.icom_code:
            sigs.append(arrow.icom_code.strip().lower())
        if arrow.label:
            cleaned_label = arrow.label.strip().replace("[", "").replace("]", "")
            m = re.match(r'^([a-zA-Z0-9\.\-_]+)', cleaned_label)
            if m:
                sigs.append(m.group(1).lower())
        if arrow.id and not arrow.id.startswith("Arrow_") and not arrow.id.startswith("Trunk_"):
            cleaned_id = re.sub(r'_[a-zA-Z]\d+.*$', '', arrow.id.strip())
            if cleaned_id:
                sigs.append(cleaned_id.lower())
        return list(set(sigs))

    def has_hierarchical_prefix_match(child, parent):
        child_sigs = get_arrow_signatures(child)
        parent_sigs = get_arrow_signatures(parent)
        for c_sig in child_sigs:
            for p_sig in parent_sigs:
                if len(p_sig) >= len(c_sig):
                    continue
                is_match = False
                for delim in ['.', '-', '/']:
                    if c_sig.startswith(p_sig + delim):
                        is_match = True
                        break
                if not is_match and p_sig.isalnum() and c_sig.startswith(p_sig + "."):
                    is_match = True
                if is_match:
                    return True
        return False

    def get_stem(arrow):
        text = (arrow.label or "").strip().replace("[", "").replace("]", "")
        stem_match = re.match(r'^([a-zA-Z]+)', text)
        if stem_match:
            stem = stem_match.group(1).lower()
            num_match = re.match(r'^([a-zA-Z]+\d+)', text)
            if num_match:
                stem = num_match.group(1).lower()
        else:
            stem = "unlabeled_boundary" if not text else text.lower()
        return stem

    def share_stem(a, b):
        return get_stem(a) == get_stem(b)

    # Auto-detect manual connections for backwards compatibility/unsaved state
    for a in diagram.arrows:
        if not a.is_manual_connection:
            if a.branch_parent_id:
                parent = arrow_map.get(a.branch_parent_id)
                if parent:
                    if parent.type != a.type or (not has_hierarchical_prefix_match(a, parent) and not share_stem(a, parent)):
                        a.is_manual_connection = True
            if a.join_target_id:
                target = arrow_map.get(a.join_target_id)
                if target:
                    if target.type != a.type or (not has_hierarchical_prefix_match(a, target) and not share_stem(a, target)):
                        a.is_manual_connection = True

    # 0. Reset existing branch/join links for all arrows in this diagram
    # to allow clean re-consolidation when labels or codes change.
    # Preserve manual cross-type links (where parent/target type differs from child type)
    # and manually assigned same-type links.
    for a in diagram.arrows:
        preserve_branch = False
        if a.branch_parent_id:
            parent = arrow_map.get(a.branch_parent_id)
            if parent and (parent.type != a.type or a.is_manual_connection):
                preserve_branch = True
                
        preserve_join = False
        if a.join_target_id:
            target = arrow_map.get(a.join_target_id)
            if target and (target.type != a.type or a.is_manual_connection):
                preserve_join = True
                
        if not preserve_branch:
            a.branch_parent_id = None
            a.branch_points = []
            
        if not preserve_join:
            a.join_target_id = None
            a.join_points = []
            
        a.junction_point = None
    
    # --- PHASE 1: Hierarchical ICOM/Label Decomposition Consolidation ---
    # Find all boundary arrows (where source_box_id is None or target_box_id is None)
    boundary_arrows = [a for a in diagram.arrows if a.source_box_id is None or a.target_box_id is None]
    
    # Calculate signatures for all boundary arrows
    arrow_sigs = {}
    for a in boundary_arrows:
        arrow_sigs[a.id] = get_arrow_signatures(a)
        
    for child in boundary_arrows:
        if child.is_manual_connection:
            continue
        child_sigs = arrow_sigs[child.id]
        if not child_sigs:
            continue
            
        best_parent_id = None
        best_parent_sig_len = 0
        best_orig_sig = None
        
        for parent in boundary_arrows:
            if parent.id == child.id or parent.type != child.type:
                continue
                

                
            parent_sigs = arrow_sigs[parent.id]
            for c_sig in child_sigs:
                for p_sig in parent_sigs:
                    # Parent signature must be strictly shorter to be a hierarchical parent
                    if len(p_sig) >= len(c_sig):
                        continue
                        
                    is_match = False
                    # Check prefix with delimiters
                    for delim in ['.', '-', '/']:
                        if c_sig.startswith(p_sig + delim):
                            is_match = True
                            break
                    # Support alpha-numeric prefix without dot, e.g. D3 -> D3.1
                    if not is_match and p_sig.isalnum() and c_sig.startswith(p_sig + "."):
                        is_match = True
                        
                    if is_match:
                        # We found a parent candidate! Keep the one with the longest matching parent signature
                        if len(p_sig) > best_parent_sig_len:
                            best_parent_sig_len = len(p_sig)
                            best_parent_id = parent.id
                            # Extract matching child signature case from original to set as icom_code
                            if child.icom_code:
                                best_orig_sig = child.icom_code.strip()
                            elif child.id and not child.id.startswith("Arrow_") and not child.id.startswith("Trunk_"):
                                best_orig_sig = re.sub(r'_A\d+', '', child.id.strip())
                            elif child.label:
                                cleaned = child.label.strip().replace("[", "").replace("]", "")
                                m = re.match(r'^([a-zA-Z0-9\.\-_]+)', cleaned)
                                if m:
                                    candidate = m.group(1)
                                    if re.match(r'^[a-zA-Z]+\d+', candidate) or '.' in candidate or '-' in candidate:
                                        best_orig_sig = candidate
                            
        if best_parent_id:
            if child.type == ArrowType.OUTPUT:
                child.join_target_id = best_parent_id
            else:
                child.branch_parent_id = best_parent_id
                
            if best_orig_sig:
                child.icom_code = best_orig_sig

    # --- PHASE 2: Traditional Stem-Based Consolidation (fallback for unnamed/similar stubs) ---
    # groups[type][preamble] -> [arrow_ids]
    signal_groups = {t: {} for t in ArrowType}
    
    for a in diagram.arrows:
        # A boundary arrow is anything touching the margin (one end has no box AND no link)
        # INTERNAL ARROWS (both boxes present) should NEVER be consolidated as boundary trunks.
        if a.source_box_id and a.target_box_id:
            continue

        # Skip arrows already consolidated by Phase 1 hierarchical matching
        if a.branch_parent_id is not None or a.join_target_id is not None:
            continue

        is_boundary_in = (a.source_box_id is None)
        is_boundary_out = (a.target_box_id is None)
        
        if not (is_boundary_in or is_boundary_out):
            continue
            
        # Extract "Signal Stem" (first alphabetic run)
        text = (a.label or "").strip().replace("[", "").replace("]", "")
        stem_match = re.match(r'^([a-zA-Z]+)', text)
        if stem_match:
            stem = stem_match.group(1).lower()
            # If followed by digit, include it (e.g. O1 vs O2)
            num_match = re.match(r'^([a-zA-Z]+\d+)', text)
            if num_match: stem = num_match.group(1).lower()
        else:
            stem = "unlabeled_boundary" if not text else text.lower()
            
        if stem not in signal_groups[a.type]:
            signal_groups[a.type][stem] = []
        signal_groups[a.type][stem].append(a.id)

    for a_type in signal_groups:
        for stem in signal_groups[a_type]:
            ids = signal_groups[a_type][stem]
            if len(ids) <= 1:
                continue
                
            # Sort: Prioritize "Trunk_" arrows from sync as the primary trunk (id[0])
            # Then sort by Y position.
            def sort_key(aid):
                a = arrow_map[aid]
                pref = 0 if a.id.startswith("Trunk_") else 1
                box_id = a.source_box_id or a.target_box_id
                pos = box_map[box_id].y if (box_id and box_id in box_map) else 0
                return (pref, pos)
                
            sorted_ids = sorted(ids, key=sort_key)
            
            if a_type in [ArrowType.INPUT, ArrowType.CONTROL, ArrowType.MECHANISM]:
                trunk = arrow_map[sorted_ids[0]]
                for i in range(1, len(sorted_ids)):
                    child = arrow_map[sorted_ids[i]]
                    if child.is_manual_connection:
                        continue
                        

                            
                    child.branch_parent_id = trunk.id
                    # Propagate label to trunk if needed
                    if not trunk.label and child.label: trunk.label = child.label
            
            elif a_type == ArrowType.OUTPUT:
                trunk = arrow_map[sorted_ids[0]]
                for i in range(1, len(sorted_ids)):
                    child = arrow_map[sorted_ids[i]]
                    if child.is_manual_connection:
                        continue
                    child.join_target_id = trunk.id
                    # Propagate label to trunk if needed
                    if not trunk.label and child.label: trunk.label = child.label

