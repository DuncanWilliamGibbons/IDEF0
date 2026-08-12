from PyQt6.QtWidgets import QGraphicsRectItem, QGraphicsItem, QGraphicsTextItem, QGraphicsPathItem
from PyQt6.QtCore import QRectF, Qt, QPointF
from PyQt6.QtGui import QPen, QBrush, QColor, QPainterPath, QPainter, QPainterPathStroker
import math
from src.core.model import Point, simplify_path, ArrowType

# How far back from the function box a branch/join label is anchored, so every
# one of them sits the same short distance off the box it belongs to.
BRANCH_LABEL_SETBACK = 60.0

# How far in from the diagram edge a BOUNDARY arrow's label is anchored. A
# border ICOM is read at the edge it crosses, so its label belongs in the
# headspace out there - the same run in for every one of them, rather than
# adrift halfway down whatever approach that particular arrow happens to have.
#
# Short on purpose. The callout leaves the arrow at 45 degrees over CALLOUT_LEG,
# so anchoring near the border is what lands the label OUTSIDE it, in the margin
# where nothing is drawn. Anchored deeper, the label sits down among the parallel
# drops of its neighbours - and a boundary label is wide enough to span several
# of them, so wherever it lands in there it lies across two or three lines.
BOUNDARY_LABEL_SETBACK = 18.0


def _runs_of(arrow):
    """The axis-aligned runs an arrow is drawn as, as (x1, y1, x2, y2)."""
    pts = arrow.segments or []
    return [(pts[i].x, pts[i].y, pts[i + 1].x, pts[i + 1].y)
            for i in range(len(pts) - 1)]


def _run_hits_rect(run, rect, pad=2.0):
    """Whether an axis-aligned run passes through a rectangle.

    Exact for a horizontal or vertical run, which is all an IDEF0 arrow is made
    of, so a bounding-box test is the real answer rather than an approximation.
    """
    x1, y1, x2, y2 = run
    return (min(x1, x2) <= rect.right() + pad and max(x1, x2) >= rect.left() - pad
            and min(y1, y2) <= rect.bottom() + pad and max(y1, y2) >= rect.top() - pad)


def _segments_cross(a, b, c, d):
    """Whether segment a-b properly crosses segment c-d. Points are (x, y)."""
    def side(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)

    return (side(a, b, c) != side(a, b, d)
            and side(c, d, a) != side(c, d, b))

# An automatically placed callout leaves the arrow at 45 degrees. Anything
# shallower runs alongside the line it came from and grazes the text it points
# at; a right angle buries the mount in the neighbouring lane. The leg is the
# run along each axis, so the callout itself spans CALLOUT_LEG * sqrt(2).
CALLOUT_LEG = 30.0

# How much of an arrow's identity a label carries. The View > ICOM IDs setting
# picks one of these for the whole model; the properties panel edits BOTH ids
# whichever is on show.
ICOM_ID_MODES = ("user", "auto", "both", "none")
DEFAULT_ICOM_ID_MODE = "both"


def compose_label_text(user_id, auto_id, label, mode=DEFAULT_ICOM_ID_MODE):
    """The text drawn beside an arrow, for one ICOM IDs setting.

    The modeller's own id leads and the standard's positional code trails, so a
    reader gets "P.2 AM Part [O1]" - the name they gave it, then the code
    ISO/IEC/IEEE 31320-1 requires for that position on the boundary. An id
    already spelled at the front of the label is not repeated.
    """
    user_id = (user_id or "").strip()
    auto_id = (auto_id or "").strip()
    body = (label or "").strip()

    lead = ""
    trail = ""
    if mode == "user":
        lead = user_id
    elif mode == "auto":
        lead = auto_id
    elif mode == "both":
        lead, trail = user_id, auto_id

    # A label typed as "D.4.1 CAD Model" already leads with its id; drop the
    # duplicate rather than printing it twice. Only codes that are about to be
    # printed are stripped, and the id has to end on a boundary to count -
    # otherwise an id of "D" eats the D of "Design Requirements".
    for code in (lead, trail):
        if not code or not body.lower().startswith(code.lower()):
            continue
        tail = body[len(code):]
        if tail and tail[0] not in " \t.-/:":
            continue
        # A label that is nothing but its own id leaves the id to say it.
        body = tail.lstrip(" \t.-/:").strip()

    parts = [p for p in (lead, body) if p]
    text = " ".join(parts)
    if trail:
        text = f"{text} [{trail}]" if text else f"[{trail}]"
    return text


def label_is_read_at_delivery(arrow_data):
    """True when this arrow's own label is drawn beside the box it feeds.

    Mirrors the anchor choice in `ArrowItem.update_label_display`. It decides
    whether an ancestor's label covers the legs that branch off it: a label
    printed where the arrow ENTERS the diagram (a boundary bus) or where it
    LEAVES a box (an output) sits upstream of every later split, so one printing
    names them all. A label printed beside the function the arrow delivers into
    sits at the far end of the run and names that delivery alone - the next leg
    off the same signal has to say what it carries for itself.
    """
    if not arrow_data:
        return False
    is_branch = bool(arrow_data.branch_parent_id or arrow_data.join_target_id)
    return is_branch and bool(arrow_data.target_box_id)


class ActivityBoxItem(QGraphicsRectItem):
    def __init__(self, x, y, width, height, name, node_number, has_decomposition=False, box_data=None):
        super().__init__(0, 0, width, height)
        self.setPos(x, y)
        self.has_decomposition = has_decomposition
        self.box_data = box_data  # Reference to the model data
        self.day_brush = QBrush(Qt.GlobalColor.white) # Default day brush
        self.setBrush(self.day_brush)
        self.setPen(QPen(Qt.GlobalColor.black, 2))
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable | QGraphicsItem.GraphicsItemFlag.ItemIsMovable | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Name Text
        self.name_text = QGraphicsTextItem(name, self)
        self.name_text.setTextWidth(width - 10) # Padding
        self.name_text.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Center Alignment
        doc = self.name_text.document()
        option = doc.defaultTextOption()
        option.setAlignment(Qt.AlignmentFlag.AlignCenter)
        doc.setDefaultTextOption(option)
        
        # Center the text item vertically in the box
        # We need to re-center whenever font changes, logic is mostly correct below but needs to respect height change due to wrapping
        text_rect = self.name_text.boundingRect()
        self.name_text.setPos((width - text_rect.width()) / 2, (height - text_rect.height()) / 2)
        
        # Node Number (bottom right)
        self.node_text = QGraphicsTextItem(node_number, self)
        # Make node number small font
        font = self.node_text.font()
        font.setPointSize(8)
        self.node_text.setFont(font)
        self.node_text.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_node_number_pos()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        # Capture offsets for attached arrows to enable rubber-banding
        scene = self.scene()
        if not scene or not hasattr(scene, 'diagram_data'): return
        
        self.attached_arrows = [] # List of {'arrow': ArrowData, 'item': ArrowItem, 'end': 'start'|'end', 'offset': QPointF}
        
        current_pos = self.pos()
        box_id = self.box_data.id if self.box_data else None
        if not box_id: return
        
        # Find all ArrowItems in the scene to link with data
        arrow_items_map = {}
        from src.gui.diagram_items import ArrowItem # localized import
        for item in scene.items():
            if isinstance(item, ArrowItem) and item.arrow_data:
                arrow_items_map[item.arrow_data.id] = item

        for arrow in scene.diagram_data.arrows:
            if not arrow.segments: continue
            
            arrow_item = arrow_items_map.get(arrow.id)
            if not arrow_item: continue

            if arrow.source_box_id == box_id:
                # Store offset of Start Point
                p = arrow.segments[0]
                offset = QPointF(p.x, p.y) - current_pos
                self.attached_arrows.append({'arrow': arrow, 'item': arrow_item, 'end': 'start', 'offset': offset})
                
            if arrow.target_box_id == box_id:
                # Store offset of End Point
                p = arrow.segments[-1]
                offset = QPointF(p.x, p.y) - current_pos
                self.attached_arrows.append({'arrow': arrow, 'item': arrow_item, 'end': 'end', 'offset': offset})

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            if self.box_data:
                self.box_data.x = self.x()
                self.box_data.y = self.y()
                self.update_attached_arrows()
                
        return super().itemChange(change, value)

    def update_attached_arrows(self):
        if not hasattr(self, 'attached_arrows'): return
        
        current_pos = self.pos()
        
        for data in self.attached_arrows:
            arrow = data['arrow']
            arrow_item = data['item']
            offset = data['offset']
            new_pt = current_pos + offset
            
            if data['end'] == 'start':
                arrow.segments[0].x = new_pt.x()
                arrow.segments[0].y = new_pt.y()
            else:
                arrow.segments[-1].x = new_pt.x()
                arrow.segments[-1].y = new_pt.y()
            
            # Update visual path
                arrow_item.update_path_from_model()

    def update_node_number_pos(self):
        """Positions node text and ensures its corner box is correctly sized."""
        if not self.node_text.isVisible():
            return
            
        # We determine size based on text + padding
        nr = self.node_text.boundingRect()
        bw = max(25, nr.width() + 6)
        bh = max(18, nr.height() + 4)
        
        right = self.rect().width()
        bottom = self.rect().height()
        
        # Center text within the corner box area
        self.node_text.setPos(right - bw + (bw - nr.width()) / 2, 
                              bottom - bh + (bh - nr.height()) / 2)
        self.update()

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        
        if not self.node_text.isVisible():
            return
            
        # Draw the small box around the node number (bottom right)
        # Size logic matches update_node_number_pos
        nr = self.node_text.boundingRect()
        bw = max(25, nr.width() + 6)
        bh = max(18, nr.height() + 4)
        
        right = self.rect().width()
        bottom = self.rect().height()
        
        painter.setPen(self.pen())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        
        # The rect for the corner number
        corner_rect = QRectF(right - bw, bottom - bh, bw, bh)
        painter.drawRect(corner_rect)
        
        if self.has_decomposition:
            # If decomposed, we can add a small indicator or just keep the box
            # Some IDEF0 styles use a thicker border for the corner box if decomposed
            # or a small triangle. For now, the existence of the box satisfies the request.
            # Let's add a subtle double-line or just keep it clean.
            pass

    def set_decomposition_status(self, status):
        if self.has_decomposition != status:
            self.has_decomposition = status
            self.update()

    def mouseDoubleClickEvent(self, event):
        scene = self.scene()
        if scene and hasattr(scene, 'on_item_double_clicked'):
            scene.on_item_double_clicked(self)
        super().mouseDoubleClickEvent(event)

    def set_box_color(self, color):
        self.day_brush = QBrush(color)
        if self.box_data:
            self.box_data.color = color.name()
        # Only apply immediately if NOT in night mode
        if not getattr(self, 'is_night_mode', False):
             self.setBrush(self.day_brush)
        
    def set_font_family(self, family):
        font = self.name_text.font()
        font.setFamily(family)
        self.name_text.setFont(font)
        self.center_text()
        if self.box_data:
            self.box_data.font_family = family
        
    def set_font_bold(self, is_bold):
        font = self.name_text.font()
        font.setBold(is_bold)
        self.name_text.setFont(font)
        self.center_text()
        if self.box_data:
            self.box_data.font_bold = is_bold
        
    def set_font_italic(self, is_italic):
        font = self.name_text.font()
        font.setItalic(is_italic)
        self.name_text.setFont(font)
        self.center_text()
        if self.box_data:
            self.box_data.font_italic = is_italic

    def get_box_color(self):
        return self.day_brush.color()
    
    def get_font_family(self):
        return self.name_text.font().family()
    
    def get_font_bold(self):
        return self.name_text.font().bold()
    
    def get_font_italic(self):
        return self.name_text.font().italic()
    
    def get_font_size(self):
        return self.name_text.font().pointSize()

    def center_text(self):
        # Helper to re-center text after font changes
        text_rect = self.name_text.boundingRect()
        self.name_text.setPos((self.rect().width() - text_rect.width()) / 2, (self.rect().height() - text_rect.height()) / 2)

    def set_font_size(self, size):
        font = self.name_text.font()
        font.setPointSize(size)
        self.name_text.setFont(font)
        self.center_text()
        if self.box_data:
            self.box_data.font_size = size

    def set_box_id(self, new_id):
        self.node_text.setPlainText(new_id)
        self.update_node_number_pos()
        if self.box_data:
            self.box_data.id = new_id

    def set_show_id(self, show):
        self.node_text.setVisible(show)
        self.update_node_number_pos()
        self.update()

    def update_theme(self, is_night):
        self.is_night_mode = is_night # Store state if needed
        color = Qt.GlobalColor.white if is_night else Qt.GlobalColor.black
        pen = QPen(color, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.setPen(pen)
        self.name_text.setDefaultTextColor(color)
        self.node_text.setDefaultTextColor(color)
        
        if is_night:
            # Use transparent fill so background shows through
            self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        else:
            self.setBrush(self.day_brush)

class ArrowItem(QGraphicsPathItem):
    def __init__(self, path: QPainterPath, tunnel_source=False, tunnel_target=False, branch_points=None, join_points=None, has_head=True, arrow_id="", arrow_data=None, radius=10):
        super().__init__(path)
        pen = QPen(Qt.GlobalColor.black, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.setPen(pen)
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self.tunnel_source = tunnel_source
        self.tunnel_target = tunnel_target
        self.branch_points = branch_points if branch_points else []
        self.join_points = join_points if join_points else []
        self.has_head = has_head
        self.arrow_id = arrow_id
        self.arrow_data = arrow_data  # Reference to the model data
        self.extended_segments = None # Preserved points including junction extensions
        self.skip_start = False
        self.skip_end = False
        self.label_text = ""
        self.show_id = True
        self.icom_id_mode = DEFAULT_ICOM_ID_MODE
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable | QGraphicsItem.GraphicsItemFlag.ItemSendsScenePositionChanges)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.label_percent = 0.5 # Default to middle
        self.label_is_vertical = None
        self._syncing_label = False
        self.is_updating_from_model = False
        self.label_item = None
        self.squiggle_item = None
        self.base_label_pos = QPointF(0, 0)
        self.handles = []
        self.is_dragging_split = False
        self.radius = radius # Rounding radius
        
        # Style properties
        self.arrow_color = QColor(Qt.GlobalColor.black)
        self.arrow_thickness = 2
        self.arrow_style = Qt.PenStyle.SolidLine
        
        # Use Hierarchy for Z-Order (handled in Scene)
        self.setZValue(10)
        
        # Label Font Properties
        self.label_font_family = "Arial"
        self.label_font_size = 9
        self.label_font_bold = False
        self.label_font_italic = False
        self.label_font_bold = False
        self.label_font_italic = False
        self._is_dragging = False
        
        # Arrowhead Style
        self.arrowhead_style = "Standard"
        self.icom_callout_style = "Jagged"
        if self.arrow_data:
            self.arrowhead_style = getattr(self.arrow_data, 'arrowhead_style', "Standard")
            self.icom_callout_style = getattr(self.arrow_data, 'icom_callout_style', "Jagged")

    def update_path_from_model(self):
        if self.arrow_data:
            # Sync extended_segments with arrow_data.segments if they already exist
            if self.extended_segments and len(self.extended_segments) > 0 and len(self.arrow_data.segments) > 0:
                skip_s = getattr(self, 'skip_start', bool(self.arrow_data.branch_parent_id))
                skip_e = getattr(self, 'skip_end', bool(self.arrow_data.join_target_id))
                new_ext = list(self.arrow_data.segments)
                if skip_s and len(self.extended_segments) > len(self.arrow_data.segments):
                    new_ext.insert(0, self.extended_segments[0])
                if skip_e and len(self.extended_segments) > len(self.arrow_data.segments):
                    new_ext.append(self.extended_segments[-1])
                self.extended_segments = new_ext

            # Use preserved radius and extended segments to prevent 'sharpening' or 'losing junctions' on click
            pts = self.extended_segments if self.extended_segments else self.arrow_data.segments
            if pts:
                from src.gui.diagram_items import make_rounded_path
                skip_s = getattr(self, 'skip_start', bool(self.arrow_data.branch_parent_id))
                skip_e = getattr(self, 'skip_end', bool(self.arrow_data.join_target_id))
                self.setPath(make_rounded_path(pts, radius=self.radius, skip_start=skip_s, skip_end=skip_e))
                
                self.update_label_display()
                if self.isSelected():
                    self.update_handles(True)


    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        # Set a wider stroke width for hit-testing to make it easier to click
        click_width = max(12, self.arrow_thickness + 8)
        stroker.setWidth(click_width)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return stroker.createStroke(self.path())

    def boundingRect(self):
        # Union of the path's bounding rect and all children's bounding rects
        rect = super().boundingRect()
        # Add padding for pen thickness and potential artifacts. Tunnel
        # notation is drawn beside the line, outside the path's own bounds,
        # so an end bracketed by it needs the room reserved or it gets clipped.
        pad = 10.0
        if self.tunnel_source or self.tunnel_target:
            pad += 20 + max(0.0, self.arrow_thickness - 2) * 2
        rect = rect.adjusted(-pad, -pad, pad, pad)
        # Include children (label, squiggle, handles)
        for child in self.childItems():
            if child.isVisible():
                child_rect = child.mapToParent(child.boundingRect()).boundingRect()
                rect = rect.united(child_rect)
        return rect

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self.prepareGeometryChange()
            self.update_handles(value)
        return super().itemChange(change, value)

    def update_handles(self, selected=None):
        if selected is None:
            selected = self.isSelected()
            
        # Clear existing handles
        self.prepareGeometryChange() # REQUIRED to prevent clipping bbox caches
        for h in self.handles:
            h.setParentItem(None)
            if self.scene():
                self.scene().removeItem(h)
        self.handles.clear()
        
        if not selected:
            return
            
        # Create handles for internal segments
        # Points are P0, P1, ..., Pn
        # Segments are S0(P0-P1), S1(P1-P2), ..., Sn-1(Pn-1-Pn)
        # We only allow moving segments that don't move the fixed endpoints P0 and Pn.
        # Moving Si (i>0 and i<n-1) is safe.
        
        scene = self.scene()
        if not scene: return
        
        # Get segments from model if possible, or use current path
        # ALWAYS simplify path before generating handles to ensure alternating H/V segments
        # We must clone before simplifying to not corrupt the model structure
        if hasattr(self, 'arrow_data') and self.arrow_data:
            # We must update arrow_data structure safely
            self.arrow_data.segments = simplify_path(self.arrow_data.segments)
            pts = self.arrow_data.segments
        else:
            return # Should have data
        
        n = len(pts) - 1
        
        # 1. Segment Handles (One in the middle of each arm)
        for i in range(n):
            p1 = pts[i]
            p2 = pts[i+1]
            
            # Double check orthogonality for handle naming
            is_horiz = abs(p1.y - p2.y) < 1
            is_vert = abs(p1.x - p2.x) < 1
            
            if not is_horiz and not is_vert:
                # Emergency fix for diagonal (shouldn't happen with simplify_path)
                p2.x = p1.x # Force vertical
                is_vert = True
            
            mid_x = (p1.x + p2.x) / 2
            mid_y = (p1.y + p2.y) / 2
            orient = 'H' if is_horiz else 'V'
            
            h_seg = ArrowHandleItem(self, i, orient, 'Segment')
            h_seg.setPos(mid_x, mid_y)
            h_seg.is_initializing = False
            self.handles.append(h_seg)

        # 2. Corner Handles (One in each corner to create new bends)
        # Corners are points P1 to Pn-1
        for i in range(1, n):
            h_corner = ArrowHandleItem(self, i, 'C', 'Corner')
            h_corner.setPos(pts[i].x, pts[i].y)
            h_corner.is_initializing = False
            self.handles.append(h_corner)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.is_dragging_split = False
        # No longer moving the whole arrow item, so no need to sync pos() here
        pass
        
    def paint(self, painter, option, widget=None):
        # Draw the path itself (shortened if we have an arrowhead)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Determine arrowhead scaling first to know how much to shorten the line
        # Suppress arrowhead if this is a joiner (it merges into another arrow)
        has_arrowhead = self.has_head and self.path().elementCount() > 1
        if self.arrow_data and self.arrow_data.join_target_id:
            has_arrowhead = False
        arrow_size = 14
        if has_arrowhead:
            # More aggressive scaling: start at 14, add 3px for every 1px of thickness
            arrow_size = 14 + (self.arrow_thickness - 2) * 3
            arrow_size = max(14, arrow_size)

        draw_path = self.path()
        if has_arrowhead:
            # Pull the line back so the thick stroke doesn't blunt the sharp tip.
            # This must operate on the path's OWN final straight run: the last
            # element is only safe to move when it is a LineTo. Trimming a curve's
            # end point deforms the rounded corner leading into it, and trimming
            # further than the run is long makes the line double back on itself.
            s_dist = arrow_size if self.arrowhead_style == "Open" else arrow_size * 0.7
            shortened = QPainterPath(self.path())
            last_idx = shortened.elementCount() - 1
            if last_idx > 0 and shortened.elementAt(last_idx).type == QPainterPath.ElementType.LineToElement:
                p_end = QPointF(shortened.elementAt(last_idx).x, shortened.elementAt(last_idx).y)
                p_prev = QPointF(shortened.elementAt(last_idx - 1).x, shortened.elementAt(last_idx - 1).y)
                vec = p_end - p_prev
                seg_len = (vec.x()**2 + vec.y()**2)**0.5
                if seg_len > s_dist + 0.5:
                    new_end = p_end - (vec / seg_len) * s_dist
                    shortened.setElementPositionAt(last_idx, new_end.x(), new_end.y())
                    draw_path = shortened

        # Use FlatCap to ensure thick line terminates flat, and MiterJoin to prevent rounded overshoots
        pen = QPen(self.pen())
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.drawPath(draw_path)
        
        if has_arrowhead:
            path = self.path()
            p_end = path.elementCount() - 1
            
            # Find the true points for orientation using mathematical segments
            geom_pts = self.arrow_data.segments if self.arrow_data and self.arrow_data.segments else self.extended_segments

            if geom_pts and len(geom_pts) >= 2:
                end_point = QPointF(geom_pts[-1].x, geom_pts[-1].y)
                prev_point = QPointF(geom_pts[-2].x, geom_pts[-2].y)
            else:
                p_prev = p_end - 1
                end_point = QPointF(path.elementAt(p_end).x, path.elementAt(p_end).y)
                prev_point = QPointF(path.elementAt(p_prev).x, path.elementAt(p_prev).y)
            
            line = end_point - prev_point
            if not line.isNull():
                angle = math.atan2(line.y(), line.x())
                head_angle = math.pi / 7 # Default angle
                
                if self.arrowhead_style == "Stealth":
                    arrow_size *= 1.15
                    head_angle = math.pi / 10
                elif self.arrowhead_style == "Open":
                    arrow_size *= 1.15
                    head_angle = math.pi / 6

                arrow_p1 = end_point - QPointF(math.cos(angle + head_angle) * arrow_size, math.sin(angle + head_angle) * arrow_size)
                arrow_p2 = end_point - QPointF(math.cos(angle - head_angle) * arrow_size, math.sin(angle - head_angle) * arrow_size)
                
                arrow_head = QPainterPath()
                arrow_head.moveTo(end_point)
                arrow_head.lineTo(arrow_p1)
                
                if self.arrowhead_style == "Stealth":
                     # Concave back
                     mid_back = end_point - QPointF(math.cos(angle) * (arrow_size * 0.7), math.sin(angle) * (arrow_size * 0.7))
                     arrow_head.lineTo(mid_back)
                     arrow_head.lineTo(arrow_p2)
                elif self.arrowhead_style != "Open":
                     # Standard Triangle
                     arrow_head.lineTo(arrow_p2)
                
                arrow_head.closeSubpath()
                
                head_color = pen.color()
                # Scale head thickness slightly so it doesn't look like a "hair" on a thick body
                # But keep it significantly thinner than the base to ensure the tip is sharp
                # For a 10px line, this will be around 4px
                head_pen_width = 1.5 + (self.arrow_thickness - 2) * 0.3
                sharp_pen = QPen(head_color, head_pen_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin)
                
                if self.arrowhead_style == "Open":
                    # For Open heads, we draw the V starting from the true end_point
                    
                    # 1. Draw a mask triangle in the background color to "sharpen" the end of the thick line
                    # This prevents the blunt end of the base line from showing through the V
                    mask_path = QPainterPath()
                    mask_path.moveTo(end_point)
                    mask_path.lineTo(arrow_p1)
                    mask_path.lineTo(arrow_p2)
                    mask_path.closeSubpath()
                    
                    # Determine current background color based on theme
                    bg_color = Qt.GlobalColor.black if getattr(self, 'is_night_mode', False) else Qt.GlobalColor.white
                    painter.fillPath(mask_path, QBrush(bg_color))

                    # 2. Draw the V lines
                    path_open = QPainterPath()
                    path_open.moveTo(arrow_p1)
                    path_open.lineTo(end_point)
                    path_open.lineTo(arrow_p2)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(sharp_pen)
                    painter.drawPath(path_open)
                else:
                    # For filled heads, draw the shape on top of the shortened line
                    painter.setBrush(QBrush(head_color))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawPath(arrow_head)
                    
                    # Draw outline with sharp pen to ensure the point is perfect
                    painter.setPen(sharp_pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPath(arrow_head)
                # Restore original pen for subsequent drawings
                painter.setPen(self.pen())

        # Tunnel notation, clause 9.4. Derived from the geometry here rather than
        # inside the arrowhead block above: a headless arrow (a joiner, a bus)
        # never enters that block, and a tunnelled end still has to be bracketed.
        for at_head in (True, False):
            if not (self.tunnel_target if at_head else self.tunnel_source):
                continue
            terminal = self._terminal_direction(at_head)
            if terminal:
                self.draw_tunnel_notation(painter, *terminal)

        # Draw branch/join points if present
        # (Removed per user request to clean up diagram)
        # painter.setBrush(QBrush(self.pen().color()))
        # painter.setPen(Qt.PenStyle.NoPen)
        # for pt in self.branch_points:
        #     painter.drawEllipse(QPointF(pt.x, pt.y), 3.5, 3.5)
        # for pt in self.join_points:
        #     # Only draw a dot for joins if they aren't forming a smooth rounded blend
        #     painter.drawEllipse(QPointF(pt.x, pt.y), 3.5, 3.5)
    
    def _terminal_direction(self, at_head: bool):
        """(end point, angle pointing away from whatever that end attaches to).

        The angle runs from the terminal back along the arrow, which is away
        from the box or frame it touches at either end: at the head that is
        against the flow, at the tail it is with it.
        """
        pts = (self.arrow_data.segments
               if self.arrow_data and self.arrow_data.segments else None)
        if pts and len(pts) >= 2:
            coords = [QPointF(p.x, p.y) for p in pts]
        else:
            path = self.path()
            if path.elementCount() < 2:
                return None
            coords = [QPointF(path.elementAt(i).x, path.elementAt(i).y)
                      for i in range(path.elementCount())]
        if at_head:
            coords.reverse()
        end = coords[0]
        inward = next((p for p in coords[1:] if p != end), None)
        if inward is None:
            return None
        line = inward - end
        return end, math.atan2(line.y(), line.x())

    def draw_tunnel_notation(self, painter, point, away_angle):
        """Bracket an arrow end in a pair of parentheses: clause 9.4 tunnelling.

        The standard asks for "a pair of short, shallow arcs drawn to resemble a
        pair of left and right parentheses characters", so both are drawn, and
        the bracketed end sits *between* them: the pair straddles the line, one
        arc each side of it, opening inwards. The pair turns with the arrow, so
        a vertical arrow is bracketed left and right and a horizontal one above
        and below - either way the line runs between the two arcs rather than
        through them.

        `away_angle` points from the end back along the arrow, away from the box
        or frame it attaches to, and the pair is set clear by its own extent in
        that direction so no arc is ever left drawn inside a box.
        """
        gap = 11 + max(0.0, self.arrow_thickness - 2) * 1.5  # line to each arc
        half_len = 13 + max(0.0, self.arrow_thickness - 2)   # half an arc's chord
        bulge = 5.0                                          # how round the arc is

        # Along the arrow, and across it. The chord of each arc runs along, the
        # offset that separates the two runs across.
        ax, ay = math.cos(away_angle), math.sin(away_angle)
        px, py = -ay, ax

        # The pair reaches half a chord back along the arrow, so that is what it
        # has to clear the box edge by.
        clearance = half_len + 4
        cx, cy = point.x() + ax * clearance, point.y() + ay * clearance

        # A dashed or hairline arrow still brackets solid and legibly: the
        # notation is a symbol, not part of the line's own styling.
        pen = QPen(self.pen())
        pen.setStyle(Qt.PenStyle.SolidLine)
        pen.setWidthF(max(1.5, self.arrow_thickness * 0.75))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        for side in (-1, 1):
            bx, by = cx + px * side * gap, cy + py * side * gap
            arc = QPainterPath()
            arc.moveTo(bx + ax * half_len, by + ay * half_len)
            # Control twice the bulge out, which puts the curve's own midpoint
            # exactly one bulge clear of the chord, bowing away from the line.
            arc.quadTo(bx + px * side * bulge * 2, by + py * side * bulge * 2,
                       bx - ax * half_len, by - ay * half_len)
            painter.strokePath(arc, pen)

    def update_theme(self, is_night):
        self.is_night_mode = is_night # Store state
        
        # Determine visual color (White in Night Mode, else User's Color)
        if is_night:
             visual_color = QColor(Qt.GlobalColor.white)
        else:
             visual_color = self.arrow_color
             
        pen = QPen(visual_color, self.arrow_thickness, self.arrow_style)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.setPen(pen)
        
        if self.label_item:
            lbl_col = getattr(self.arrow_data, 'label_color', self.arrow_color.name()) if hasattr(self, 'arrow_data') and self.arrow_data else self.arrow_color.name()
            lbl_visual_color = QColor(Qt.GlobalColor.white) if is_night else QColor(lbl_col)
            self.label_item.setDefaultTextColor(lbl_visual_color)
        if self.squiggle_item:
            self.squiggle_item.setPen(QPen(visual_color, 1))

    def set_style_properties(self, color=None, thickness=None, style_name=None):
        if color:
            self.arrow_color = color
            if self.arrow_data:
                self.arrow_data.color = color.name()
        if thickness:
            self.arrow_thickness = thickness
            if self.arrow_data:
                self.arrow_data.thickness = thickness
        if style_name:
            style_map = {
                "Solid": Qt.PenStyle.SolidLine,
                "Dashed": Qt.PenStyle.DashLine,
                "Dotted": Qt.PenStyle.DotLine,
                "DotDash": Qt.PenStyle.DashDotLine
            }
            self.arrow_style = style_map.get(style_name, Qt.PenStyle.SolidLine)
            if self.arrow_data:
                self.arrow_data.style = style_name
                
        pen = QPen(self.arrow_color, self.arrow_thickness, self.arrow_style)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.setPen(pen)
        
        self.prepareGeometryChange()
        self.update()
        scene = self.scene()
        is_night = False
        if scene and hasattr(scene, 'is_night_mode'):
             is_night = scene.is_night_mode
             
        self.update_theme(is_night)

    def set_arrowhead_style(self, style_name):
        self.arrowhead_style = style_name
        if self.arrow_data:
            self.arrow_data.arrowhead_style = style_name
        self.update()

    def set_icom_callout_style(self, style_name):
        self.icom_callout_style = style_name
        if self.arrow_data:
            self.arrow_data.icom_callout_style = style_name
        self.update_label_display()

    def set_label(self, text, percent=0.5):
        self.label_text = text
        self.label_percent = percent
        self.update_label_display(text_changed=True)

    def set_show_id(self, show):
        self.show_id = show
        self.update_label_display()

    def set_icom_id_mode(self, mode):
        """Which of the two ICOM ids the label prints - see ICOM_ID_MODES."""
        if mode not in ICOM_ID_MODES:
            mode = DEFAULT_ICOM_ID_MODE
        self.icom_id_mode = mode
        self.update_label_display()

    def effective_icom_id_mode(self):
        """The View menu setting, unless 'Hide Arrow IDs' overrides it to none."""
        return self.icom_id_mode if self.show_id else "none"

    def delivers_into_a_function(self):
        """True when this arrow physically touches a box at the end it is read at.

        An input, control or mechanism is read where it enters a function; an
        output where it leaves one. A leg that only feeds further legs touches no
        box and is not a delivery, so it stays unlabelled however specialised it
        is - repeating the name mid-corridor names nothing in particular.
        """
        ad = getattr(self, 'arrow_data', None)
        if not ad:
            return False
        if ad.type == ArrowType.OUTPUT:
            return bool(ad.source_box_id)
        return bool(ad.target_box_id)

    def update_label_display(self, text_changed=False):
        # Notify about geometry changes as label and squiggle move
        self.prepareGeometryChange()
        
        text = self.label_text
        
        # IDEF0 Convention: Suppress labels for branches/joins to prevent redundancy.
        # A branch label is redundant if it carries the same data as its parent trunk
        # that already displays it.
        is_redundant = False
        import re
        # Clean synthetic branch suffixes (e.g. D.4.2_1 -> D.4.2, D.5_A1.1 -> D.5.1)
        def clean_arrow_id(raw_id, arrow_data=None):
            val = (arrow_data.icom_code if (arrow_data and arrow_data.icom_code) else raw_id) or ""
            clean = re.sub(r'_[A-Za-z]\d+\.', '.', val)
            clean = re.sub(r'_(?:[A-Za-z]\d+|\d+)(?:_[A-Za-z0-9_]+)*$', '', clean)
            return clean

        clean_id = clean_arrow_id(self.arrow_id, getattr(self, 'arrow_data', None))

        diagram_arrows = []
        carries_decomposed_signal = False
        if hasattr(self, 'arrow_data') and self.arrow_data:
             scene = self.scene()
             diagram_arrows = (scene.diagram_data.arrows if (scene and hasattr(scene, 'diagram_data') and scene.diagram_data) else [])
             by_id = {a.id: a for a in diagram_arrows}

             # 1. Redundancy check (ISO/IEC/IEEE 31320-1): a branch or join that
             # carries the SAME signal as an ancestor must not repeat its label.
             # One label placed before the split covers every child; only a child
             # that decomposes into a genuinely different signal is labelled.
             ad = self.arrow_data
             p_id = ad.branch_parent_id or ad.join_target_id
             p_arr = by_id.get(p_id) if p_id else None

             if p_arr:
                 c_lbl = (ad.label or "").strip().lower()
                 c_clean = clean_arrow_id(self.arrow_id, ad).strip().lower()

                 # Climb while each ancestor carries the same signal; the topmost
                 # such arrow is the one that actually renders the label. The
                 # first ancestor carrying a DIFFERENT signal, if there is one,
                 # is the bus this signal was decomposed out of.
                 label_owner = None
                 decomposed_from = None
                 curr, seen = p_arr, set()
                 while curr and curr.id not in seen:
                     seen.add(curr.id)
                     curr_lbl = (curr.label or "").strip().lower()
                     curr_clean = clean_arrow_id(curr.id, curr).strip().lower()
                     same_signal = (c_clean == curr_clean) and ((not c_lbl) or curr_lbl == c_lbl)
                     if not same_signal:
                         decomposed_from = curr
                         break
                     label_owner = curr
                     nxt_id = curr.branch_parent_id or curr.join_target_id
                     curr = by_id.get(nxt_id) if nxt_id else None

                 # A decomposed signal - one its own bus does not carry, such as
                 # P.3.1 off the M1 mechanism bus - is named at EVERY function it
                 # reaches. Nothing upstream says which of M1's parts arrives
                 # here, so each delivery leg has to say it for itself. A signal
                 # merely fanned out to several functions is different: the one
                 # label before the split already covers all of them.
                 #
                 # Which of the two this is turns on WHERE the ancestor prints
                 # its label, not on whether a decomposition happened further up.
                 # D.4.1.1 Product Design leaves A11 labelled at the box, and the
                 # legs into A12 and A13 branch off downstream of that label - so
                 # they are fanned out and stay bare, even though D.4.1.1 is
                 # itself a decomposition of the D.4.1 CAD Model bus. D.5.1 CAD
                 # Software is labelled beside A11, the function it feeds; the leg
                 # on to A13 is not covered by that and names itself.
                 covered_by_ancestor = (
                     label_owner is not None
                     and not getattr(label_owner, 'hide_label', False)
                     and not label_is_read_at_delivery(label_owner))
                 carries_decomposed_signal = (decomposed_from is not None and
                                              not covered_by_ancestor and
                                              self.delivers_into_a_function())

                 if (label_owner is not None and not carries_decomposed_signal
                         and not getattr(label_owner, 'hide_label', False)):
                     # An ancestor already shows this exact signal before the split.
                     is_redundant = True
                     text = ""
                 else:
                     # A specialised child (e.g. D.4.6.1 off D.4.6) keeps its label,
                     # inheriting anything it did not define for itself.
                     is_redundant = False
                     if not text and p_arr.label:
                         text = p_arr.label
                         self.label_text = text
                     if not ad.icom_code and p_arr.icom_code:
                         ad.icom_code = p_arr.icom_code
                         clean_id = clean_arrow_id(self.arrow_id, ad)

        if (not is_redundant and not carries_decomposed_signal
                and hasattr(self, 'arrow_data') and self.arrow_data
                and (self.arrow_data.branch_parent_id or self.arrow_data.join_target_id)):
            c_lbl = (self.arrow_data.label or "").strip().lower()
            for sib in diagram_arrows:
                if sib.id != self.arrow_id and (sib.branch_parent_id or sib.join_target_id) == (self.arrow_data.branch_parent_id or self.arrow_data.join_target_id):
                    sib_lbl = (sib.label or "").strip().lower()
                    if sib_lbl == c_lbl and self.arrow_id.startswith(sib.id + '_'):
                        is_redundant = True
                        text = ""
                        break

        # Print whichever ICOM ids the View setting asks for (ISO 31320-1 gives
        # the positional code; the modeller owns the one at the front).
        if not is_redundant:
            auto_id = (getattr(self.arrow_data, 'auto_icom_code', "") or ""
                       if getattr(self, 'arrow_data', None) else "")
            text = compose_label_text(clean_id, auto_id, text,
                                      self.effective_icom_id_mode())

        if not text or is_redundant or getattr(self.arrow_data, 'hide_label', False): 
            if self.label_item:
                self.label_item.setPlainText("")
                self.label_item.hide()
            if self.squiggle_item:
                self.squiggle_item.hide()
            return

        if self.label_item:
             self.label_item.show()
        if self.squiggle_item:
             self.squiggle_item.show()
        
        path = self.path()
        if path.elementCount() < 2: return
        
        # 1. Setup Label Item
        if not self.label_item:
            self.label_item = ArrowLabelItem(text, self)
            font = self.label_item.font()
            font.setFamily(self.label_font_family)
            font.setPointSize(self.label_font_size)
            font.setBold(self.label_font_bold)
            font.setItalic(self.label_font_italic)
            self.label_item.setFont(font)
            self.label_item.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            # Force update text to reflect ID visibility change
            self.label_item.setPlainText(text)
            
        # 2. Find Anchor Point on Arrow — direction-aware placement
        # IDEF0 convention: labels go near the boundary edge of the arrow.
        #   - INPUT/CONTROL/MECHANISM trunks: label on FIRST segment (near boundary start)
        #   - OUTPUT trunks: label on LAST segment (near boundary end)
        # For trunks with branches, place between boundary and nearest branch point.
        # A branch that carries its own signal is named for what it hands the box
        # it connects to, so its label goes beside THAT box - the split it came
        # off may be at the far side of the diagram, and a label parked there
        # reads as belonging to the trunk instead of to the function.
        center_point = QPointF(0, 0)
        angle = 0.0
        # Which way the run travels, when we have real segments to read it from.
        # QPainterPath.angleAtPercent uses the opposite sign convention, so the
        # fallbacks below leave this unset rather than guess backwards.
        run_vec = None
        # Which way is out of the diagram, for a border ICOM; None for the rest.
        # Cleared on every pass, so a re-route that stops an arrow being one
        # cannot leave the last answer behind.
        self.boundary_outward = None

        if hasattr(self, 'arrow_data') and self.arrow_data and getattr(self, 'extended_segments', None):
            segments = self.extended_segments
            boundary = self.boundary_label_anchor(segments)
            if boundary is not None:
                # A border ICOM: anchored out in the headspace, after any merge.
                center_point, run_vec, self.boundary_outward = boundary
                angle = math.degrees(math.atan2(run_vec[1], run_vec[0]))
            elif len(segments) >= 2:
                arrow_type = self.arrow_data.type
                is_pure_branch = bool(self.arrow_data.branch_parent_id or self.arrow_data.join_target_id)
                has_children = bool(self.arrow_data.branch_points) or any(
                    hasattr(self.scene(), 'diagram_data') and a.branch_parent_id == self.arrow_id
                    for a in getattr(self.scene().diagram_data, 'arrows', [])
                )

                # How far along the chosen leg the anchor sits: 0.0 at its start,
                # 1.0 at its end, or None for the plain midpoint.
                target_seg_idx = 0
                anchor_at_end = False
                is_boundary_output = (arrow_type == ArrowType.OUTPUT and
                                      not self.arrow_data.target_box_id and
                                      not self.arrow_data.join_target_id)
                if is_pure_branch and self.arrow_data.target_box_id:
                    # Branch delivering into a box — label on the final leg, a
                    # short run back from the box it enters. This holds even when
                    # the branch goes on to feed further boxes: the label names
                    # what it hands THIS one. Joins *out of* a box keep the
                    # midpoint of their opening leg, because several of them leave
                    # one box a few pixels apart and pinning them all to the same
                    # setback would stack their labels on each other.
                    target_seg_idx = len(segments) - 2
                    anchor_at_end = True
                elif is_boundary_output and not has_children:
                    # An output that runs off the edge of the diagram is read at
                    # the edge, so its label belongs by the boundary it leaves
                    # through - not stranded halfway along the run.
                    target_seg_idx = len(segments) - 2
                    anchor_at_end = True
                elif is_pure_branch or has_children:
                    # Trunk with branches: place label near the source (box or boundary)
                    target_seg_idx = 0
                else:
                    # Simple arrow
                    if arrow_type == ArrowType.OUTPUT:
                        # Simple output to boundary goes at the end
                        target_seg_idx = len(segments) - 2
                    else:
                        target_seg_idx = 0

                # Ensure index is valid
                target_seg_idx = max(0, min(len(segments) - 2, target_seg_idx))

                p1 = segments[target_seg_idx]
                p2 = segments[target_seg_idx + 1]

                # Default position: middle of the target segment
                cx = (p1.x + p2.x) / 2.0
                cy = (p1.y + p2.y) / 2.0

                if anchor_at_end:
                    # Set back a consistent run from the box, so every branch
                    # label sits the same short distance off its function. Short
                    # legs fall back to a fraction of their own length rather
                    # than landing on the arrowhead.
                    seg_len = math.hypot(p2.x - p1.x, p2.y - p1.y)
                    if seg_len > 1e-6:
                        setback = min(max(seg_len * 0.25, 18.0),
                                      BRANCH_LABEL_SETBACK, seg_len * 0.5)
                        t = (seg_len - setback) / seg_len
                        cx = p1.x + (p2.x - p1.x) * t
                        cy = p1.y + (p2.y - p1.y) * t

                # For trunks with branches, place label BEFORE the first branch point on this segment
                if has_children and not anchor_at_end and self.arrow_data.branch_points:
                    bps_on_seg = []
                    for bp in self.arrow_data.branch_points:
                        tol = 2.0
                        in_x = min(p1.x, p2.x) - tol <= bp.x <= max(p1.x, p2.x) + tol
                        in_y = min(p1.y, p2.y) - tol <= bp.y <= max(p1.y, p2.y) + tol
                        if in_x and in_y:
                            # Verify collinearity (approx)
                            dx = p2.x - p1.x
                            dy = p2.y - p1.y
                            if abs(dx) < 1e-2 and abs(bp.x - p1.x) < tol:
                                bps_on_seg.append((abs(bp.y - p1.y), bp))
                            elif abs(dy) < 1e-2 and abs(bp.y - p1.y) < tol:
                                bps_on_seg.append((abs(bp.x - p1.x), bp))
                    
                    if bps_on_seg:
                        bps_on_seg.sort(key=lambda x: x[0])
                        first_bp = bps_on_seg[0][1]
                        cx = (p1.x + first_bp.x) / 2.0
                        cy = (p1.y + first_bp.y) / 2.0

                center_point = QPointF(cx, cy)
                angle = math.degrees(math.atan2(p2.y - p1.y, p2.x - p1.x))
                run_vec = (p2.x - p1.x, p2.y - p1.y)
            else:
                path = self.path()
                if not path.isEmpty():
                    center_point = path.pointAtPercent(0.5)
                    angle = path.angleAtPercent(0.5)
        else:
            path = self.path()
            if not path.isEmpty():
                center_point = path.pointAtPercent(0.5)
                angle = path.angleAtPercent(0.5)
                
        self.label_anchor_point = center_point
        
        # Add label offset from model if available
        scene = self.scene()
        offset_x = 0
        offset_y = 0
        if self.arrow_data:
            offset_x = self.arrow_data.label_offset_x
            offset_y = self.arrow_data.label_offset_y
        elif scene and hasattr(scene, 'diagram_data') and scene.diagram_data:
            for arrow in scene.diagram_data.arrows:
                if arrow.id == self.arrow_id:
                    offset_x = arrow.label_offset_x
                    offset_y = arrow.label_offset_y
                    break
        
        metrics = self.label_item.boundingRect()
        
        # Normalize angle to 0-180
        norm_angle = angle % 180
        
        # 3. Position Text based on Orientation + Base Offset
        is_vertical = 45 < norm_angle < 135
        base_offset_x, base_offset_y = self.auto_label_offset(
            metrics, is_vertical, run_vec)

        auto_is_vertical = is_vertical
        if abs(offset_x) > 0.1 or abs(offset_y) > 0.1:
            # Manual Mode: Position relative to Anchor Center
            self.base_label_pos = center_point
            text_pos = center_point + QPointF(offset_x, offset_y)
            is_vertical = None  # let the shared attachment rule decide from the offset
            if self.label_covers_a_box(text_pos, metrics):
                # A drag is stored relative to the anchor, so a re-route that
                # moves the anchor can carry the label onto a function box -
                # a placement nobody chose and nobody can read. Fall back to the
                # automatic side; the offset stays in the model for the next drag.
                self.base_label_pos = center_point + QPointF(base_offset_x, base_offset_y)
                text_pos = self.base_label_pos
                is_vertical = auto_is_vertical
        else:
            # Auto Mode: Position relative to Smart Base
            self.base_label_pos = center_point + QPointF(base_offset_x, base_offset_y)
            text_pos = self.base_label_pos

        # Remember the side the layout chose so a later drag repaint agrees with it.
        self.label_is_vertical = is_vertical

        # Moving the label fires ArrowLabelItem.itemChange, which repaints the
        # squiggle. Suppress that here: we are about to draw the authoritative
        # one, and letting the drag repaint run first makes the mount flicker.
        self._syncing_label = True
        try:
            self.label_item.setPos(text_pos)
        finally:
            self._syncing_label = False

        squig_path = self.build_squiggle_path(center_point, text_pos, metrics, is_vertical)
        if squig_path is None:
            return

        if not self.squiggle_item:
            self.squiggle_item = QGraphicsPathItem(squig_path, self)
            self.squiggle_item.setZValue(-1) # Behind label
            # Match theme
            scene = self.scene()
            is_night = False
            if scene and hasattr(scene, 'is_night_mode'):
                 is_night = scene.is_night_mode
            color = Qt.GlobalColor.white if is_night else self.arrow_color
            self.squiggle_item.setPen(QPen(color, 1))
        else:
            self.squiggle_item.setPath(squig_path)

        self.squiggle_item.show()
        self.update()

    def boundary_label_anchor(self, segments):
        """(point, run vector) for a border ICOM's label, or None.

        A boundary arrow is read at the edge it crosses, so its label sits out in
        the headspace there - the same run in from the border for every one of
        them, rather than adrift halfway down whatever approach that particular
        arrow happens to have. D.4.7 Equipment Controls used to be anchored at
        the midpoint of a 400px drop, which parked it down beside a function box
        with the other arrows' labels.

        Two junctions bound where along the approach that can be:

        * a **merge** must be BEHIND the label. Before a join the run does not
          yet carry the whole bundle, so a name printed there names the parts.
          P.4.8 Sensor Data sat 60 back from the edge with A44's output joining
          50 back - the wrong side of it.
        * a **split** must be AHEAD of it, so the one label covers every leg that
          peels off; that is what lets those legs stay bare.

        The label goes as near the border as those two allow.
        """
        ad = getattr(self, 'arrow_data', None)
        if not ad or len(segments) < 2:
            return None
        if ad.branch_parent_id or ad.join_target_id:
            return None  # a branch is named beside the function it feeds

        if ad.type == ArrowType.OUTPUT:
            if ad.target_box_id:
                return None  # runs into a box, not off the edge
            border, inward = segments[-1], segments[-2]
        else:
            if ad.source_box_id:
                return None
            border, inward = segments[0], segments[1]

        dx, dy = inward.x - border.x, inward.y - border.y
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return None
        ux, uy = dx / length, dy / length

        def on_leg(points):
            """How far from the border each junction sits, ignoring any that is
            not on this leg at all."""
            out = []
            for p in points:
                along = (p.x - border.x) * ux + (p.y - border.y) * uy
                across = abs(-(p.x - border.x) * uy + (p.y - border.y) * ux)
                if across <= 2.0 and 1e-6 < along < length:
                    out.append(along)
            return out

        splits, merges = on_leg(ad.branch_points), on_leg(ad.join_points)
        # An output travels TOWARDS the border, so distance-from-border counts
        # down along it and the two roles swap ends.
        if ad.type == ArrowType.OUTPUT:
            behind, ahead = splits, merges
        else:
            behind, ahead = merges, splits

        low = max(behind, default=0.0)
        high = min(ahead, default=length)
        if high <= low:
            low, high = 0.0, length  # nothing consistent to honour; use the leg
        reach = low + min(BOUNDARY_LABEL_SETBACK, (high - low) / 2)

        point = QPointF(border.x + ux * reach, border.y + uy * reach)
        run = (-dx, -dy) if ad.type == ArrowType.OUTPUT else (dx, dy)
        # Out past the border is the one direction with nothing in it: the drops
        # of the neighbouring boundary arrows all START at the border and run
        # inwards, so a label pushed outwards is pushed into clear space.
        outward = (-ux, -uy)
        return point, run, outward

    def other_runs(self):
        """Every run drawn in this diagram except this arrow's own."""
        scene = self.scene()
        data = getattr(scene, 'diagram_data', None) if scene else None
        if not data:
            return []
        return [run for a in data.arrows if a.id != self.arrow_id
                for run in _runs_of(a)]

    def label_mount(self, text_pos, metrics, is_vertical):
        """The point on the label rect a callout attaches to."""
        if is_vertical:
            if text_pos.x() > self.label_anchor_point.x():
                return text_pos + QPointF(0, metrics.height() / 2)
            return text_pos + QPointF(metrics.width(), metrics.height() / 2)
        if text_pos.y() > self.label_anchor_point.y():
            return text_pos + QPointF(metrics.width() / 2, 0)
        return text_pos + QPointF(metrics.width() / 2, metrics.height())

    def placement_is_clear(self, top_left, metrics, runs, is_vertical):
        """Whether a label here would sit clear of the boxes and every line.

        A callout drawn across another arrow reads as a connection between the
        two, and a label sitting on a run hides it. Both are checked, because
        either one on its own still leaves the picture crossed.
        """
        if self.label_covers_a_box(top_left, metrics):
            return False
        rect = QRectF(top_left.x(), top_left.y(), metrics.width(), metrics.height())
        if any(_run_hits_rect(run, rect) for run in runs):
            return False

        anchor = (self.label_anchor_point.x(), self.label_anchor_point.y())
        mount_point = self.label_mount(top_left, metrics, is_vertical)
        mount = (mount_point.x(), mount_point.y())
        return not any(_segments_cross(anchor, mount, (x1, y1), (x2, y2))
                       for x1, y1, x2, y2 in runs)

    def label_covers_a_box(self, top_left, metrics):
        """True when a label drawn at this position would sit over a function box."""
        scene = self.scene()
        data = getattr(scene, 'diagram_data', None) if scene else None
        if not data:
            return False
        left, top = top_left.x(), top_left.y()
        right, bottom = left + metrics.width(), top + metrics.height()
        return any(left < b.x + b.width and right > b.x and
                   top < b.y + b.height and bottom > b.y
                   for b in data.boxes)

    def auto_label_offset(self, metrics, is_vertical, run_vec=None):
        """Where to put a freshly generated label, relative to its anchor.

        The label goes one CALLOUT_LEG out along each axis, so the callout
        build_squiggle_path draws to it leaves the arrow at 45 degrees. Anything
        shallower creeps along beside the run and under the words it points at.

        Four diagonals satisfy that, so they are tried in order of how well they
        read and the first that leaves the label and its callout clear of the
        boxes AND of every other line wins: the customary side of the line first
        (left of a drop, above a run), and back the way the arrow came before
        forward, since forward on the leg that ends at a box points straight into
        it. In a corridor where no diagonal is clear of the lines, keeping off
        the function boxes is what still matters, so that is the fallback.
        """
        w, h = metrics.width(), metrics.height()

        # Backwards along the run, when we know which way it travels.
        back = 0
        if run_vec:
            along = run_vec[1] if is_vertical else run_vec[0]
            back = -1 if along > 0 else 1 if along < 0 else 0

        def offset(sx, sy):
            """Label position that puts the mount at (sx, sy) * CALLOUT_LEG."""
            mx, my = sx * CALLOUT_LEG, sy * CALLOUT_LEG
            if is_vertical:
                # Side by side: the mount is the edge facing the arrow, mid-height.
                return (mx - w if sx < 0 else mx), my - h / 2
            # Above or below: the mount is the edge facing the arrow, centred.
            return mx - w / 2, (my - h if sy < 0 else my)

        if is_vertical:
            # sx picks the side of the line, sy runs along it.
            order = [(-1, back or -1), (-1, -(back or -1)),
                     (1, back or -1), (1, -(back or -1))]
        else:
            # sy picks above or below, sx runs along.
            order = [(back or 1, -1), (-(back or 1), -1),
                     (back or 1, 1), (-(back or 1), 1)]

        candidates = [offset(sx, sy) for sx, sy in order]
        runs = self.other_runs()
        for dx, dy in candidates:
            if self.placement_is_clear(self.label_anchor_point + QPointF(dx, dy),
                                       metrics, runs, is_vertical):
                return dx, dy
        for dx, dy in candidates:
            if not self.label_covers_a_box(self.label_anchor_point + QPointF(dx, dy),
                                           metrics):
                return dx, dy
        return candidates[0]

    def callout_chord(self):
        """Anchor-to-mount vector of the drawn callout, or None if there is none.

        The mount is an edge of the label rect rather than its corner, so this
        is the only honest read of which way the callout actually leaves the
        arrow - for a wide label the rect can sit on the far side of the anchor
        from the point the callout attaches to.
        """
        if not self.squiggle_item:
            return None
        path = self.squiggle_item.path()
        if path.elementCount() < 2:
            return None
        start = path.elementAt(0)
        end = path.elementAt(path.elementCount() - 1)
        return QPointF(end.x - start.x, end.y - start.y)

    def label_scene_rect(self):
        """Where the label currently sits, in scene coordinates."""
        if not self.label_item:
            return None
        r = self.label_item.boundingRect()
        p = self.label_item.pos()
        return QRectF(p.x(), p.y(), r.width(), r.height())

    def move_label_to(self, pos):
        """Re-seat an automatically placed label and redraw its callout."""
        self._syncing_label = True
        try:
            self.label_item.setPos(pos)
        finally:
            self._syncing_label = False
        self.base_label_pos = pos
        path = self.build_squiggle_path(self.label_anchor_point, pos,
                                        self.label_item.boundingRect(),
                                        self.label_is_vertical)
        if path is not None and self.squiggle_item:
            self.squiggle_item.setPath(path)

    def build_squiggle_path(self, center_point, text_pos, metrics, is_vertical=None):
        """The one place an ICOM callout is drawn.

        `center_point` is always label_anchor_point - the spot on the arrow the
        callout belongs to. Layout and drag both come through here so the mount
        can never drift to a different part of the line.
        """
        if is_vertical is None:
            # Attach on whichever axis the label is furthest away along.
            dx = text_pos.x() - center_point.x()
            dy = text_pos.y() - center_point.y()
            is_vertical = abs(dx) > abs(dy)

        # The same mount `placement_is_clear` tested, so the callout it approved
        # is the callout that gets drawn.
        if is_vertical:
            start_squig = (text_pos + QPointF(0, metrics.height() / 2)
                           if text_pos.x() > center_point.x()
                           else text_pos + QPointF(metrics.width(), metrics.height() / 2))
        else:
            start_squig = (text_pos + QPointF(metrics.width() / 2, 0)
                           if text_pos.y() > center_point.y()
                           else text_pos + QPointF(metrics.width() / 2, metrics.height()))

        p0 = center_point  # At Arrow
        p3 = start_squig   # At Label

        vec = p3 - p0
        length = (vec.x()**2 + vec.y()**2)**0.5
        if length < 2:
            return None  # Too close

        # Perpendicular for jag offset
        perp_x = -vec.y() / length
        perp_y = vec.x() / length

        squig_path = QPainterPath()
        squig_path.moveTo(p0)

        if self.icom_callout_style == "Straight":
            # Simple direct vector
            squig_path.lineTo(p3)

        elif self.icom_callout_style == "Rounded":
            # Smooth Quadratic Squiggle (Cubic-ish)
            amp = 12
            # 2 Control points to form a soft S-curve
            cp1 = p0 + vec * 0.4 + QPointF(perp_x * amp, perp_y * amp)
            cp2 = p0 + vec * 0.7 - QPointF(perp_x * amp, perp_y * amp)
            squig_path.cubicTo(cp1, cp2, p3)

        else: # "Jagged" (Standard sharp zig-zag)
            amp = 10
            # p1: "Up" from arrow (go 60% of way)
            p1 = p0 + vec * 0.6 + QPointF(perp_x * amp, perp_y * amp)
            # p2: "Return" jog (go 40% of way)
            p2 = p0 + vec * 0.4 + QPointF(-perp_x * amp, -perp_y * amp)
            squig_path.lineTo(p1)
            squig_path.lineTo(p2)
            squig_path.lineTo(p3)

        return squig_path

    def set_label_font_size(self, size):
        self.label_font_size = size
        if self.arrow_data:
            self.arrow_data.label_font_size = size
        if self.label_item:
            font = self.label_item.font()
            font.setPointSize(size)
            self.label_item.setFont(font)
            self.update_label_position()

    def set_label_font_family(self, family):
        self.label_font_family = family
        if self.arrow_data:
            self.arrow_data.label_font_family = family
        if self.label_item:
            font = self.label_item.font()
            font.setFamily(family)
            self.label_item.setFont(font)
            self.update_label_position()

    def set_label_font_bold(self, is_bold):
        self.label_font_bold = is_bold
        if self.arrow_data:
            self.arrow_data.label_font_bold = is_bold
        if self.label_item:
            font = self.label_item.font()
            font.setBold(is_bold)
            self.label_item.setFont(font)
            self.update_label_position()

    def set_label_font_italic(self, is_italic):
        self.label_font_italic = is_italic
        if self.arrow_data:
            self.arrow_data.label_font_italic = is_italic
        if self.label_item:
            font = self.label_item.font()
            font.setItalic(is_italic)
            self.label_item.setFont(font)
            self.update_label_position()
            
    def get_label_font_family(self):
        return self.label_font_family
        
    def get_label_font_size(self):
        return self.label_font_size
        
    def get_label_font_bold(self):
        return self.label_font_bold
        
    def get_label_font_italic(self):
        return self.label_font_italic

    def update_label_position(self):
        # Re-run set_label logic to update position without forcing text refresh
        if self.label_item:
            self.update_label_display(text_changed=False)

    def update_squiggle_during_drag(self):
        """Repaint the callout while the user drags the label.

        It must anchor on label_anchor_point, exactly like update_label_display.
        Re-deriving the anchor from pointAtPercent() here used to make the mount
        jump to an unrelated part of the arrow the moment a label was touched.
        """
        if not self.label_item or not self.squiggle_item:
            return
        if not hasattr(self, 'label_anchor_point'):
            return

        squig_path = self.build_squiggle_path(
            self.label_anchor_point,
            self.label_item.pos(),
            self.label_item.boundingRect(),
        )
        if squig_path is not None:
            self.squiggle_item.setPath(squig_path)
        
def resolve_label_overlaps(items, boxes=(), arrows=(), step=13.0, limit=14):
    """Slide automatically placed labels off each other and off the lines.

    Every label is positioned from its own arrow alone, so two branches feeding
    one box - their lines only a lane apart - come out with their labels stacked,
    and a label placed beside its own run can land squarely on a neighbouring
    one. Nudging along the run the label belongs to keeps it beside its own arrow
    and lets the callout stretch to follow; labels the user has dragged are left
    exactly where they were put.

    Arrow runs are obstacles as well as boxes and other labels: a name printed
    over a line hides the line and is itself hard to read. The arrow's OWN runs
    are not - a label is meant to sit beside its own.
    """
    labelled = [i for i in items
                if i.label_item and i.label_item.isVisible()
                and i.label_item.toPlainText().strip()]
    # Settle top-left first so the result does not depend on scene item order.
    labelled.sort(key=lambda i: (round(i.label_item.pos().y()),
                                 round(i.label_item.pos().x()), i.arrow_id))

    owned_runs = [(a.id, run) for a in arrows for run in _runs_of(a)]

    def clear_of_lines(item, rect):
        return not any(_run_hits_rect(run, rect)
                       for aid, run in owned_runs if aid != item.arrow_id)

    taken = [QRectF(b.x, b.y, b.width, b.height) for b in boxes]
    moved = 0
    for item in labelled:
        rect = item.label_scene_rect()
        if rect is None:
            continue
        data = getattr(item, 'arrow_data', None)
        manual = data is not None and (abs(data.label_offset_x) > 0.1 or
                                       abs(data.label_offset_y) > 0.1)
        if manual or (not any(rect.intersects(t) for t in taken)
                      and clear_of_lines(item, rect)):
            taken.append(rect)
            continue

        origin = item.label_item.pos()

        # Backing straight out along the callout is the first thing to try: the
        # mount stays on the same ray from the anchor, so the 45 degree angle
        # automatic placement chose survives the move. Failing that, slide along
        # the run - that keeps the label reading against its own line - and only
        # then push sideways off it, which is often walled in by a box.
        # The ray is the callout's own chord, not the corner of the label: the
        # mount is an edge of the rect, so for a wide label the two can point to
        # opposite sides of the anchor.
        diagonal = ()
        chord = item.callout_chord()
        if chord is not None:
            diagonal = ((1 if chord.x() >= 0 else -1,
                         1 if chord.y() >= 0 else -1),)
        if item.label_is_vertical:
            moves = diagonal + ((0, 1), (0, -1), (-1, 0))   # label sits left of the line
        else:
            moves = diagonal + ((1, 0), (-1, 0), (0, -1))   # label sits above the line

        # A border ICOM has one direction with nothing in it - out past the
        # border, where the neighbouring drops have not started yet. Tried first,
        # it walks the label into the headspace instead of along a corridor where
        # every step lands on the next drop along.
        outward = getattr(item, 'boundary_outward', None)
        if outward:
            step_out = (round(outward[0]), round(outward[1]))
            moves = (step_out,) + tuple(m for m in moves if m != step_out)
        # The nearest clear spot wins, so a label never travels further from its
        # own arrow than it has to. A spot that is only free of the other labels
        # is kept as a fallback: in a packed corridor there may be nothing clear
        # of the lines as well, and sitting on a line still beats sitting on
        # another label.
        best = fallback = None
        for k in range(1, limit + 1):
            for dx, dy in moves:
                cand = QPointF(origin.x() + dx * k * step, origin.y() + dy * k * step)
                probe = QRectF(cand.x(), cand.y(), rect.width(), rect.height())
                if any(probe.intersects(t) for t in taken):
                    continue
                if clear_of_lines(item, probe):
                    best = (cand, probe)
                    break
                if fallback is None:
                    fallback = (cand, probe)
            if best:
                break
        best = best or fallback

        if best:
            item.move_label_to(best[0])
            taken.append(best[1])
            moved += 1
        else:
            taken.append(rect)
    return moved


def make_rounded_path(points, radius=10, skip_start=False, skip_end=False):
    """
    Creates a QPainterPath with rounded corners for Manhattan segments.
    Uses strict orthogonal vector snapping to prevent floating point 'spikes'.
    """
    if not points: return QPainterPath()
    
    path = QPainterPath()
    n = len(points)
    
    # 1. Handle short paths
    if n < 3:
        if not skip_start and not skip_end:
            path.moveTo(points[0].x, points[0].y)
            path.lineTo(points[-1].x, points[-1].y)
        elif skip_start and not skip_end:
            path.moveTo(points[-1].x, points[-1].y)
        elif not skip_start and skip_end:
            path.moveTo(points[0].x, points[0].y)
        else: # both skip_start and skip_end
            if n > 0:
                path.moveTo(points[0].x, points[0].y)
        return path

    started = False
    for i in range(1, n - 1):
        p_prev = points[i-1]
        p_curr = points[i]
        p_next = points[i+1]
        
        d1 = ((p_curr.x-p_prev.x)**2 + (p_curr.y-p_prev.y)**2)**0.5
        d2 = ((p_curr.x-p_next.x)**2 + (p_curr.y-p_next.y)**2)**0.5
        
        # Snap vectors to strict orthogonal values -1, 0, 1 to prevent micro-tilt spikes
        def snap_v(p1, p2, dist):
            if dist < 0.1: return 0, 0
            vx, vy = (p2.x-p1.x)/dist, (p2.y-p1.y)/dist
            if abs(vx) >= abs(vy):
                return (1 if vx > 0 else -1), 0
            else:
                return 0, (1 if vy > 0 else -1)

        v1_x, v1_y = snap_v(p_prev, p_curr, d1)
        v2_x, v2_y = snap_v(p_curr, p_next, d2)
        
        # The first segment (i=1) has no preceding corner, so it can use the full length d1.
        # The last segment (i=n-2) has no succeeding corner, so it can use the full length d2.
        # Intermediate segments share their length between two corners, so they get d/2.
        allowed_d1 = d1 if i == 1 else d1 / 2
        allowed_d2 = d2 if i == n - 2 else d2 / 2
        eff_radius = min(radius, allowed_d1, allowed_d2)
        cross_prod = v1_x*v2_y - v1_y*v2_x
        is_turn = cross_prod != 0 and eff_radius >= 3
        
        if is_turn:
            sc = QPointF(p_curr.x - v1_x*eff_radius, p_curr.y - v1_y*eff_radius)
            cx = p_curr.x - v1_x*eff_radius + v2_x*eff_radius
            cy = p_curr.y - v1_y*eff_radius + v2_y*eff_radius
            
            start_angle = math.degrees(math.atan2(-(sc.y() - cy), sc.x() - cx))
            sweep = -90 * cross_prod
            
            if not started:
                if i == 1 and skip_start:
                    # Start EXACLTY at the curve's start point to prevent backwards spikes
                    path.moveTo(sc)
                else:
                    path.moveTo(points[0].x, points[0].y)
                    if (sc.x() - path.currentPosition().x())**2 + (sc.y() - path.currentPosition().y())**2 > 0.5:
                        path.lineTo(sc)
                started = True
            else:
                # Avoid tiny segment spikes by suppression
                if (sc.x() - path.currentPosition().x())**2 + (sc.y() - path.currentPosition().y())**2 > 0.5:
                    path.lineTo(sc)
            
            path.arcTo(cx - eff_radius, cy - eff_radius, eff_radius*2, eff_radius*2, start_angle, sweep)
            
            # Reset sc to prevent accidental contamination of subsequent collinear iterations
            sc = None
        else:
            if not started:
                if i == 1 and skip_start:
                    # Move to the start of where the curve would be, to perfectly bridge the gap left by parent trunk curves
                    path.moveTo(p_curr.x - v1_x*eff_radius, p_curr.y - v1_y*eff_radius)
                else:
                    path.moveTo(points[0].x, points[0].y)
                    path.lineTo(p_curr.x, p_curr.y)
                started = True
            else:
                # A collinear line: route straight to p_curr unless sc leakage occurs
                if (p_curr.x - path.currentPosition().x())**2 + (p_curr.y - path.currentPosition().y())**2 > 0.5:
                    path.lineTo(p_curr.x, p_curr.y)
            
    if skip_end and n >= 2:
        # Stop exactly at the junction center or end of the rounded corner, skipping points[-1].
        pass
    else:
        # Standard termination
        path.lineTo(points[-1].x, points[-1].y)
        
    return path

class ArrowLabelItem(QGraphicsTextItem):
    """Subclass to handle manual dragging of labels"""
    def __init__(self, text, parent: ArrowItem):
        super().__init__(text, parent)
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable | 
                      QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.arrow_item = parent
        self._press_pos = None

    def mousePressEvent(self, event):
        # Remember where the drag started so a plain click can be told apart
        # from a real move. Without this, merely selecting a label wrote an
        # offset and flipped it from auto to manual placement.
        self._press_pos = self.pos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        # Calculate new offset relative to the GEOMETRIC ANCHOR (Center Point)
        # This decouples manual positioning from font metrics/smart display logic.

        if not hasattr(self.arrow_item, 'label_anchor_point'):
            self._press_pos = None
            return

        pos = self.pos()
        start = self._press_pos
        self._press_pos = None
        if start is not None and (pos - start).manhattanLength() < 2.0:
            # A click, not a drag: leave the stored placement exactly as it was.
            return

        center_point = self.arrow_item.label_anchor_point
        delta = pos - center_point

        scene = self.scene()
        if scene and hasattr(scene, 'diagram_data') and scene.diagram_data:
            for arrow in scene.diagram_data.arrows:
                if arrow.id == self.arrow_item.arrow_id:
                    arrow.label_offset_x = delta.x()
                    arrow.label_offset_y = delta.y()
                    break

        # Re-run the full layout; it draws the authoritative callout, so there is
        # no follow-up drag repaint to disagree with it.
        self.arrow_item.update_label_display()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            # Skip repositions that update_label_display() is driving - it draws
            # the callout itself once it has finished placing the text.
            if self.arrow_item and not getattr(self.arrow_item, '_syncing_label', False):
                 self.arrow_item.prepareGeometryChange()
                 self.arrow_item.update_squiggle_during_drag()
        return super().itemChange(change, value)

class ArrowHandleItem(QGraphicsRectItem):
    """Small handle for manipulating arrow segments"""
    def __init__(self, arrow_item, index, orientation='H', mode='Segment'):
        # Size/Shape based on mode
        size = 8 if mode != 'Corner' else 6
        super().__init__(-size/2, -size/2, size, size, arrow_item)
        self.arrow_item = arrow_item
        self.index = index 
        self.orientation = orientation
        self.mode = mode
        self.is_initializing = True
        
        if mode == 'Segment':
            self.setBrush(QBrush(QColor("#0078d4"))) # Blue
        elif mode == 'Anchor':
            self.setBrush(QBrush(QColor("#f7941d"))) # Orange
        else:
            self.setBrush(QBrush(QColor("#28a745"))) # Green (Corner)
            
        self.setPen(QPen(Qt.GlobalColor.white, 1))
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable | 
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        
        # Set cursor
        if mode == 'Anchor' or mode == 'Corner':
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        elif orientation == 'H':
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            
        self.setZValue(100)

    def paint(self, painter, option, widget):
        if self.mode == 'Corner':
            painter.setPen(self.pen())
            painter.setBrush(self.brush())
            painter.drawEllipse(self.rect())
        else:
            super().paint(painter, option, widget)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.on_drag(value)
        return super().itemChange(change, value)

    def on_drag(self, new_pos):
        if getattr(self, 'is_initializing', False):
            return
            
        scene = self.arrow_item.scene()
        if not scene or not hasattr(scene, 'diagram_data') or not scene.diagram_data:
            return
            
        arrow_id = self.arrow_item.arrow_id
        arrow_data = next((a for a in scene.diagram_data.arrows if a.id == arrow_id), None)
        if not arrow_data: return
        
        pts = arrow_data.segments
        idx = self.index

        if self.mode == 'Corner':
            # Create a jog at this corner to "pull it out"
            if self.arrow_item.is_dragging_split: return
            
            p_curr = pts[idx]
            dx = abs(new_pos.x() - p_curr.x)
            dy = abs(new_pos.y() - p_curr.y)
            
            # Only split if we moved significantly (avoid jitter)
            if dx > 10 or dy > 10:
                self.arrow_item.is_dragging_split = True
                
                p_prev = pts[idx-1]
                p_next = pts[idx+1]
                
                # We need to preserve the object p_curr to verify logic, but we modify list in place
                # If Prev-Curr was Horizontal (y is constant)
                is_horiz_entry = abs(p_prev.y - p_curr.y) < 1
                
                if is_horiz_entry:
                    # New path: H -> V -> H -> V (Total 3 new segments between Prev and Next?)
                    # Prev(x1, y1) -> New1(x2, y1) -> New2(x2, y2) -> New3(x3, y2) -> Next(x3, y3)
                    # New x2 is cursor X. New y2 is cursor Y.
                    # x3 matches p_next.x.
                    
                    # We are replacing P_curr with P_new1, P_new2, P_new3?
                    # Current: P_prev -> P_curr -> P_next
                    # New: P_prev -> (M.x, P_prev.y) -> (M.x, M.y) -> (P_next.x, M.y) -> P_next
                    
                    # 1. Update current point to be the first corner (M.x, Prev.y)
                    # No, we need 3 points to replace 1 point to keep Manhattan?
                    # Wait: Corner connects Seg1 and Seg2. 
                    # Seg1 H, Seg2 V. 
                    # If I pull corner to M:
                    # Seg1 extends to M.x. Seg2 extends to M.y.
                    # Middle segment connects them?
                    
                    # Let's use the Insert 2 points approach. 
                    # Replace P_curr with: A(M.x, Prev.y), B(M.x, M.y), C(Next.x, M.y)
                    # This is 3 points replacing 1.
                    
                    # P_curr is modified to A?
                    # Let's insert B and C after idx.
                    
                    pts[idx].x = new_pos.x() 
                    pts[idx].y = p_prev.y
                    
                    pts.insert(idx + 1, Point(new_pos.x(), new_pos.y()))
                    pts.insert(idx + 2, Point(p_next.x, new_pos.y()))
                    
                    # Wait, if p_next.x != old p_curr.x, then the last segment (C -> Next) is vertical?
                    # P_next is (x3, y3). C is (x3, y2). C->Next is Vertical. Correct.
                    
                else: # Prev segment was Vertical (x constant)
                    # Prev(x1, y1) -> P_curr(x1, y2) -> P_next(x2, y2)
                    # New: P_prev -> (P_prev.x, M.y) -> (M.x, M.y) -> (M.x, P_next.y) -> P_next
                    
                    pts[idx].x = p_prev.x
                    pts[idx].y = new_pos.y()
                    
                    pts.insert(idx + 1, Point(new_pos.x(), new_pos.y()))
                    pts.insert(idx + 2, Point(new_pos.x(), p_next.y))
                    
        elif self.mode == 'Segment':
            # Move the entire segment parallel to itself.
            # This segment connects pts[idx] and pts[idx+1].
            # If orientation is H, we move Y. If V, we move X.
            
            # IMPORTANT: Moving a segment affects its neighbors!
            # If we move segment i (Pi -> Pi+1), we must update Pi and Pi+1.
            # This changes the length of segment i-1 and segment i+1.
            # This maintains Manhattan routing perfectly.
            
            # Boundary checks:
            # If this is strict "slide arm" behavior, we just update the coordinate.
            # However, if this is a TERMINAL segment (idx=0 or idx=n-1), moving it 
            # implies moving the anchor point along the box edge.
            
            if self.orientation == 'H':
                new_y = new_pos.y()
                
                # If terminal, constrain to box edge if needed?
                # The user said "slide the arrow along the sides", but that was for the dots.
                # "The blue squares should slide the respective arm up/down or left/right linearly"
                # So yes, if it's the first arm, we slide the start point.
                
                # Constrain to box limits if terminal? 
                # Let's check.
                if idx == 0 and arrow_data.source_box_id:
                     box = next((b for b in scene.diagram_data.boxes if b.id == arrow_data.source_box_id), None)
                     if box: new_y = max(box.y, min(box.y + box.height, new_y))
                elif idx == len(pts)-2 and arrow_data.target_box_id: # Last segment
                     box = next((b for b in scene.diagram_data.boxes if b.id == arrow_data.target_box_id), None)
                     if box: new_y = max(box.y, min(box.y + box.height, new_y))

                pts[idx].y = new_y
                pts[idx+1].y = new_y
                
            else: # Vertical
                new_x = new_pos.x()
                
                if idx == 0 and arrow_data.source_box_id:
                     box = next((b for b in scene.diagram_data.boxes if b.id == arrow_data.source_box_id), None)
                     if box: new_x = max(box.x, min(box.x + box.width, new_x))
                elif idx == len(pts)-2 and arrow_data.target_box_id:
                     box = next((b for b in scene.diagram_data.boxes if b.id == arrow_data.target_box_id), None)
                     if box: new_x = max(box.x, min(box.x + box.width, new_x))
                
                pts[idx].x = new_x
                pts[idx+1].x = new_x

            # --- JUNCTION SYNCHRONIZATION ---
            # If any junction points (branch or join) were on this segment, move them too
            # and update the connected arrows.
            self.sync_connected_junctions(arrow_data, pts[idx], pts[idx+1], self.orientation)
            
        # Update path
        # Update path using the preserved radius and skipping flags
        from src.gui.diagram_items import make_rounded_path
        skip_s = getattr(self.arrow_item, 'skip_start', bool(self.arrow_item.arrow_data.branch_parent_id))
        skip_e = getattr(self.arrow_item, 'skip_end', bool(self.arrow_item.arrow_data.join_target_id))
        
        # Use preserved radius and extended segments to prevent 'sharpening' or 'losing junctions' on drag
        if self.arrow_item.extended_segments:
            new_ext = list(pts)
            if skip_s and len(self.arrow_item.extended_segments) > len(pts):
                new_ext.insert(0, self.arrow_item.extended_segments[0])
            if skip_e and len(self.arrow_item.extended_segments) > len(pts):
                new_ext.append(self.arrow_item.extended_segments[-1])
            self.arrow_item.extended_segments = new_ext
            pts_to_draw = new_ext
        else:
            pts_to_draw = pts
            
        self.arrow_item.setPath(make_rounded_path(pts_to_draw, radius=self.arrow_item.radius, skip_start=skip_s, skip_end=skip_e))
        self.arrow_item.update_label_display() 
        if self.arrow_item.scene():
            self.arrow_item.scene().update()
        
    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        # Simplify path only AFTER the drag is complete to keep it Manhattan-clean
        if self.arrow_item.arrow_data:
            self.arrow_item.arrow_data.segments = simplify_path(self.arrow_item.arrow_data.segments)
        self.arrow_item.update_handles(selected=True)

    def sync_connected_junctions(self, arrow_data, p1, p2, orientation):
        """Finds junction points on current segment and updates connected arrows"""
        scene = self.arrow_item.scene()
        if not scene: return
        
        # Determine the line segment bounds
        is_horiz = (orientation == 'H')
        coord = p1.y if is_horiz else p1.x
        min_v = min(p1.x, p2.x) if is_horiz else min(p1.y, p2.y)
        max_v = max(p1.x, p2.x) if is_horiz else max(p1.y, p2.y)
        
        # 1. Update our own model's dot lists (branch_points and join_points)
        # We need to find dots that were on the OLD segment coordinate.
        # Since on_drag is called continuously, we assume any dot very close to the segment's axis
        # and within its range should "stick" to it.
        
        def update_dots(dots):
            for dot in dots:
                if is_horiz:
                    if abs(dot.y - coord) < 10 and min_v <= dot.x <= max_v: # Loose tolerance for drag
                        dot.y = coord
                else:
                    if abs(dot.x - coord) < 10 and min_v <= dot.y <= max_v:
                        dot.x = coord
        
        update_dots(arrow_data.branch_points)
        update_dots(arrow_data.join_points)
        
        # 2. Find dependent arrows in the scene and update their segments
        for item in scene.items():
            if isinstance(item, ArrowItem) and item.arrow_data:
                dep_data = item.arrow_data
                changed = False
                
                # If this arrow branches FROM us
                if dep_data.branch_parent_id == arrow_data.id and dep_data.junction_point:
                    j = dep_data.junction_point
                    if (is_horiz and abs(j.y - coord) < 10 and min_v <= j.x <= max_v) or \
                       (not is_horiz and abs(j.x - coord) < 10 and min_v <= j.y <= max_v):
                        if is_horiz: j.y = coord
                        else: j.x = coord
                        # Update first segment of the branching arrow
                        if dep_data.segments:
                            dep_data.segments[0].x = j.x
                            dep_data.segments[0].y = j.y
                        changed = True
                
                # If this arrow joins INTO us
                if dep_data.join_target_id == arrow_data.id and dep_data.junction_point:
                    j = dep_data.junction_point
                    if (is_horiz and abs(j.y - coord) < 10 and min_v <= j.x <= max_v) or \
                       (not is_horiz and abs(j.x - coord) < 10 and min_v <= j.y <= max_v):
                        if is_horiz: j.y = coord
                        else: j.x = coord
                        # Update last segment of the joining arrow
                        if dep_data.segments:
                            dep_data.segments[-1].x = j.x
                            dep_data.segments[-1].y = j.y
                        changed = True
                
                if changed:
                    from src.gui.diagram_items import make_rounded_path
                    # Fix the sharpening corners bug: use the item's preserved radius and junction flags
                    s_s = getattr(item, 'skip_start', bool(item.arrow_data.branch_parent_id))
                    s_e = getattr(item, 'skip_end', bool(item.arrow_data.join_target_id))
                    
                    if item.extended_segments:
                        new_ext = list(dep_data.segments)
                        if s_s and len(item.extended_segments) > len(dep_data.segments):
                            ext_pt = item.extended_segments[0]
                            if is_horiz:
                                ext_pt.y = dep_data.segments[0].y
                            else:
                                ext_pt.x = dep_data.segments[0].x
                            new_ext.insert(0, ext_pt)
                        if s_e and len(item.extended_segments) > len(dep_data.segments):
                            ext_pt = item.extended_segments[-1]
                            if is_horiz:
                                ext_pt.y = dep_data.segments[-1].y
                            else:
                                ext_pt.x = dep_data.segments[-1].x
                            new_ext.append(ext_pt)
                        item.extended_segments = new_ext
                        pts_to_draw = new_ext
                    else:
                        pts_to_draw = dep_data.segments
                        
                    item.setPath(make_rounded_path(pts_to_draw, radius=item.radius, skip_start=s_s, skip_end=s_e))
                    item.update_label_position()
                    item.update()
