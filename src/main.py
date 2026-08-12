import sys
import os
import re

# Add the project root directory to sys.path to allow running this script directly
# and still support imports starting with 'src'
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QGraphicsView, QMessageBox, QTabWidget, QFileDialog,
                             QTreeWidget, QTreeWidgetItem, QHeaderView,
                             QGraphicsScene, QGraphicsTextItem, QFrame, QPushButton, QGridLayout)
from PyQt6.QtGui import QPainter, QImage, QPen, QBrush, QColor, QActionGroup, QPainterPath, QIcon
from src.core.model import Diagram, ActivityBox, IDEF0Model, Arrow, ArrowType
from src.core.xml_io import model_to_xml, xml_to_model
import pickle
from PyQt6.QtCore import Qt, QRectF, QTimer
from src.gui.diagram_scene import DiagramScene
from src.gui.properties_panel import PropertiesPanel
from src.gui.item_panel import ItemPanel
from src.gui.diagram_items import (ActivityBoxItem, ArrowItem, ArrowLabelItem,
                                   DEFAULT_ICOM_ID_MODE, ICOM_ID_MODES)
from src.gui.management_views import (ICOMsManagerWidget, FunctionsManagerWidget,
                                      FlowReportWidget)
from src.gui.theme import DARK_STYLESHEET
from src.gui.verification_tab import VerificationReportTab

class NavigationOverlay(QFrame):
    def __init__(self, view, parent=None):
        super().__init__(parent or view)
        self.view = view
        self.is_night = False
        
        self.setObjectName("NavOverlay")
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(4)
        
        # Pan D-Pad Layout (3x3 grid)
        pan_grid = QGridLayout()
        pan_grid.setSpacing(2)
        
        self.btn_up = QPushButton("▲")
        self.btn_down = QPushButton("▼")
        self.btn_left = QPushButton("◄")
        self.btn_right = QPushButton("►")
        
        for btn in (self.btn_up, self.btn_down, self.btn_left, self.btn_right):
            btn.setFixedSize(28, 28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            
        self.btn_up.setToolTip("Move Diagram Up")
        self.btn_down.setToolTip("Move Diagram Down")
        self.btn_left.setToolTip("Move Diagram Left")
        self.btn_right.setToolTip("Move Diagram Right")

        # The arrow points the way the DIAGRAM travels, not the way the camera
        # does. Wiring them to the camera meant pressing "right" walked the
        # drawing off to the left, which is the opposite of what the glyph says.
        self.btn_up.clicked.connect(lambda: self.view.pan(0, 100))
        self.btn_down.clicked.connect(lambda: self.view.pan(0, -100))
        self.btn_left.clicked.connect(lambda: self.view.pan(100, 0))
        self.btn_right.clicked.connect(lambda: self.view.pan(-100, 0))
        
        pan_grid.addWidget(self.btn_up, 0, 1)
        pan_grid.addWidget(self.btn_left, 1, 0)
        pan_grid.addWidget(self.btn_right, 1, 2)
        pan_grid.addWidget(self.btn_down, 2, 1)
        
        main_layout.addLayout(pan_grid)
        
        # Zoom Controls Layout
        zoom_layout = QHBoxLayout()
        zoom_layout.setSpacing(4)
        
        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_out = QPushButton("−")
        
        for btn in (self.btn_zoom_in, self.btn_zoom_out):
            btn.setFixedSize(28, 28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            
        self.btn_zoom_in.setToolTip("Zoom In (Ctrl++)")
        self.btn_zoom_out.setToolTip("Zoom Out (Ctrl+-)")
        
        self.btn_zoom_in.clicked.connect(self.view.zoom_in)
        self.btn_zoom_out.clicked.connect(self.view.zoom_out)
        
        zoom_layout.addWidget(self.btn_zoom_in)
        zoom_layout.addWidget(self.btn_zoom_out)
        main_layout.addLayout(zoom_layout)
        
        # Reset View Button
        self.btn_reset = QPushButton("Reset View")
        self.btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset.setToolTip("Center & Fit Diagram Contents to Window Pane Size")
        self.btn_reset.clicked.connect(self.view.reset_view)
        main_layout.addWidget(self.btn_reset)
        
        self.update_theme(False)

    def update_theme(self, is_night=False):
        self.is_night = is_night
        if is_night:
            self.setStyleSheet("""
                QFrame#NavOverlay {
                    background-color: rgba(35, 35, 35, 220);
                    border: 1px solid #555555;
                    border-radius: 8px;
                }
                QPushButton {
                    background-color: #333333;
                    color: #ffffff;
                    border: 1px solid #555555;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #444444;
                    border-color: #777777;
                }
                QPushButton:pressed {
                    background-color: #222222;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame#NavOverlay {
                    background-color: rgba(255, 255, 255, 230);
                    border: 1px solid #cccccc;
                    border-radius: 8px;
                }
                QPushButton {
                    background-color: #f5f5f5;
                    color: #333333;
                    border: 1px solid #cccccc;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #e8e8e8;
                    border-color: #aaaaaa;
                }
                QPushButton:pressed {
                    background-color: #d0d0d0;
                }
            """)


class ZoomableView(QGraphicsView):
    def __init__(self, scene=None, parent=None):
        super().__init__(scene, parent)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.zoom_factor = 1.15
        
        # Ensure scrollbars are useful
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Floating navigation controls overlay
        self.nav_overlay = NavigationOverlay(view=self, parent=self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'nav_overlay') and self.nav_overlay:
            margin = 15
            ov_size = self.nav_overlay.sizeHint()
            v_scroll = self.verticalScrollBar()
            sb_w = v_scroll.width() if (v_scroll and v_scroll.isVisible()) else 0
            x = self.width() - ov_size.width() - margin - sb_w
            y = margin
            self.nav_overlay.move(max(margin, x), y)
            self.nav_overlay.raise_()

    def zoom_in(self):
        self.scale(self.zoom_factor, self.zoom_factor)

    def zoom_out(self):
        self.scale(1 / self.zoom_factor, 1 / self.zoom_factor)

    def pan(self, dx, dy):
        """Shift the view by dx/dy viewport pixels, at any zoom level.

        Driving the scroll bars alone left the D-pad dead whenever the diagram
        fitted inside the pane: a scroll bar has range only while the scene
        overflows the viewport, so every click was a no-op. Move the centre
        instead, and grow the scene rect to cover wherever it lands - which is
        also what gives the bars the range to follow it.
        """
        if not self.scene():
            return

        # Viewport pixels to scene units, via the live transform, so a step is
        # the same distance on screen however far in or out the view is zoomed.
        origin = self.mapToScene(0, 0)
        delta = self.mapToScene(int(dx), int(dy)) - origin

        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        target = QRectF(visible)
        target.translate(delta)

        self.setSceneRect(self.sceneRect().united(target))
        self.centerOn(target.center())

    def reset_view(self):
        self.resetTransform()
        if not self.scene():
            return
        items_rect = self.scene().itemsBoundingRect()
        if items_rect.isEmpty() or not items_rect.isValid():
            items_rect = self.scene().sceneRect()
        if items_rect.isEmpty() or not items_rect.isValid():
            items_rect = QRectF(0, 0, 1000, 800)
            
        padded_rect = items_rect.adjusted(-60, -60, 60, 60)
        self.scene().setSceneRect(padded_rect)
        self.fitInView(padded_rect, Qt.AspectRatioMode.KeepAspectRatio)
        self.centerOn(padded_rect.center())

    def wheelEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
        else:
            super().wheelEvent(event)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IDEF0 Modeler")
        self.resize(1200, 800)
        # Start Maximized
        self.setWindowState(Qt.WindowState.WindowMaximized)
        
        # Application Branding (Favicon)
        icon_path = os.path.join(root_dir, "figures", "logo.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        self.is_night = False
        self.current_box_color = "#ffffff"
        
        # Data Model
        self.project_model = IDEF0Model("New Project")
        
        # State Management
        self.open_diagrams = {} # Map node_id -> widget
        self.tree_routing_style = 'straight' # Default
        self.icom_id_mode = DEFAULT_ICOM_ID_MODE  # View > ICOM IDs
        self.undo_stack = []
        
        # Menu Bar
        self.create_menu_bar()
        
        # Central widget setup
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        # Main Layout (Vertical to hold content + status)
        main_v_layout = QVBoxLayout(self.central_widget)
        
        # Content Layout (Horizontal to hold Panel + View)
        self.main_layout = QHBoxLayout()
        main_v_layout.addLayout(self.main_layout)
        
        # Properties Panel (Left)
        self.properties_panel = PropertiesPanel()
        self.main_layout.addWidget(self.properties_panel)
        
        # Tabs (Center)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.main_layout.addWidget(self.tabs)
        
        # Item Panel (Right)
        self.item_panel = ItemPanel()
        self.main_layout.addWidget(self.item_panel)
        
        # Status Log (Bottom)
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("padding: 5px; font-size: 9pt; color: #666;")
        self.status_label.setMaximumHeight(25)
        main_v_layout.addWidget(self.status_label)
        
        # Connect Signals for Properties
        # Connect Signals for Properties (Left Panel)
        self.properties_panel.layout_changed.connect(self.update_layout_settings)
        self.properties_panel.hide_arrow_ids_changed.connect(self.toggle_arrow_ids)
        self.properties_panel.hide_box_ids_changed.connect(self.toggle_box_ids)
        self.properties_panel.refresh_clicked.connect(self.force_refresh)
        self.properties_panel.reset_clicked.connect(self.handle_reset)
        self.properties_panel.add_function_clicked.connect(self.add_function_box)
        self.properties_panel.add_arrow_clicked.connect(self.add_arrow)
        self.properties_panel.assign_arrow_clicked.connect(self.assign_boundary_arrows)

        # Connect Global Font Signals for Left Pane
        self.properties_panel.global_font_family_changed.connect(self.update_global_font_family)
        self.properties_panel.global_font_size_changed.connect(self.update_global_font_size)
        self.properties_panel.global_font_bold_changed.connect(self.update_global_font_bold)
        self.properties_panel.global_font_italic_changed.connect(self.update_global_font_italic)

        # Connect Signals for Item Panel (Right Panel)
        self.item_panel.font_size_changed.connect(self.update_font_size)
        self.item_panel.box_color_changed.connect(self.update_box_color)
        self.item_panel.font_family_changed.connect(self.update_font_family)
        self.item_panel.font_bold_changed.connect(self.update_font_bold)
        self.item_panel.font_italic_changed.connect(self.update_font_italic)
        self.item_panel.arrow_color_changed.connect(self.update_arrow_color)
        self.item_panel.label_color_changed.connect(self.update_arrow_label_color)
        self.item_panel.arrow_thickness_changed.connect(self.update_arrow_thickness)
        self.item_panel.arrow_style_changed.connect(self.update_arrow_style)
        self.item_panel.selection_id_changed.connect(self.update_selected_id)
        self.item_panel.selection_auto_id_changed.connect(self.update_selected_auto_id)
        self.item_panel.selection_name_changed.connect(self.update_selected_name)
        self.item_panel.description_changed.connect(self.update_selected_description)
        self.item_panel.icom_font_size_changed.connect(self.update_icom_font_size)
        self.item_panel.icom_callout_style_changed.connect(self.update_icom_callout_style)
        self.item_panel.hide_label_toggled.connect(self.update_selected_hide_label)
        self.item_panel.tunnel_source_toggled.connect(
            lambda on: self.update_selected_tunnel('source', on))
        self.item_panel.tunnel_target_toggled.connect(
            lambda on: self.update_selected_tunnel('target', on))
        
        # Apply initial theme
        self.toggle_theme()

        # Create initial A-0 diagram
        self.ensure_diagram_open("A-0", f"Context - {self.project_model.name}")

    @property
    def current_scene(self):
        current_widget = self.tabs.currentWidget()
        if isinstance(current_widget, QGraphicsView):
            return current_widget.scene()
        return None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
             self.delete_selected()
        else:
             super().keyPressEvent(event)

    def delete_selected(self):
        if not self.current_scene: return
        selected = self.current_scene.selectedItems()
        if not selected: return
        
        target_items = []
        for item in selected:
            if isinstance(item, (ActivityBoxItem, ArrowItem)):
                if item not in target_items:
                    target_items.append(item)
            elif isinstance(item, ArrowLabelItem):
                if item.arrow_item not in target_items:
                    target_items.append(item.arrow_item)
        
        if not target_items: return
        
        reply = QMessageBox.question(self, "Confirm Delete", 
                                   f"Are you sure you want to delete {len(target_items)} selected item(s)?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            self.save_snapshot()
            diag = self.current_scene.diagram_data
            if not diag: return
            
            global_refresh_needed = False
            
            for item in target_items:
                if isinstance(item, ActivityBoxItem):
                    box_id = item.box_data.id
                    # Delete arrows connected to this box
                    diag.arrows = [a for a in diag.arrows if a.source_box_id != box_id and a.target_box_id != box_id]
                    # Delete the box itself
                    diag.boxes = [b for b in diag.boxes if b.id != box_id]
                elif isinstance(item, ArrowItem):
                    arrow = item.arrow_data
                    # Two-Stage Deletion for Boundary Signals
                    # If it's a boundary arrow (one end free) AND it's currently connected to a box...
                    if arrow.is_boundary() and (arrow.source_box_id or arrow.target_box_id):
                        # STAGE 1: Unassign (Disconnect from Box, keep as floating stub locally)
                        if arrow.target_box_id is None: # Output
                            arrow.source_box_id = None
                        else: # Input/Control/Mech
                            arrow.target_box_id = None
                        arrow.segments = None 
                    else:
                        # STAGE 2 or Internal Arrow: Global Delete from model
                        self.project_model.delete_arrow_globally(arrow.id)
                        global_refresh_needed = True
                
            # Clear all arrow segments to force full redistributive re-route
            for a in diag.arrows:
                a.segments = None
                
            if global_refresh_needed:
                self.refresh_all_diagrams()
            else:
                self.refresh_current_diagram(diag)

    def create_diagram_tab(self, diagram):
        scene = DiagramScene()
        scene.load_diagram(diagram, project_model=self.project_model)
        scene.set_frame_visible(self.show_border_frame) # Apply persistent frame setting

        
        # Connect Scene Signals
        scene.selectionChanged.connect(self.on_selection_changed)
        scene.node_double_clicked.connect(self.open_child_diagram)
        scene.diagram_properties_changed.connect(self.on_diagram_properties_changed)
        
        view = ZoomableView(scene)
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Apply current theme to new view/scene
        if hasattr(scene, 'setBackgroundBrush'):
             if self.is_night:
                 dark_bg = QColor(30, 30, 30)
                 scene.setBackgroundBrush(QBrush(dark_bg))
                 view.setStyleSheet("background-color: #1e1e1e; border: none;")
             else:
                 scene.setBackgroundBrush(QBrush(Qt.GlobalColor.white))
        
        # Apply theme to all items in the scene
        self.apply_visual_settings_to_scene(scene)
        if hasattr(view, 'nav_overlay'):
             view.nav_overlay.update_theme(self.is_night)
             
        # Center view
        items_rect = scene.itemsBoundingRect()
        scene.setSceneRect(items_rect.adjusted(-100, -100, 100, 100))
        view.centerOn(items_rect.center())
        
        return view

    def ensure_diagram_open(self, node_id, title="Diagram"):
        if node_id in self.open_diagrams:
            # Switch to it
            widget = self.open_diagrams[node_id]
            self.tabs.setCurrentWidget(widget)
            return

        # Check in project model
        diagram = self.project_model.get_diagram(node_id)
        
        if not diagram:
            # Generate new if not exists
            diagram = self.generate_diagram(node_id, title)
            self.project_model.add_diagram(diagram)
        
        # Ensure boundary arrow consistency (ISO 31320-1)
        self.project_model.synchronize_boundaries(node_id)
        
        # Create View
        view = self.create_diagram_tab(diagram)
        # Add tab
        index = self.tabs.addTab(view, f"[{node_id}] {diagram.title}")
        self.tabs.setCurrentIndex(index)
        self.open_diagrams[node_id] = view
        
        QTimer.singleShot(50, lambda: view.reset_view() if isinstance(view, ZoomableView) and view.scene() else None)

    def open_child_diagram(self, parent_node_id):
        # Create decomposition diagram
        self.ensure_diagram_open(parent_node_id, f"Decomposition of {parent_node_id}")

    def on_diagram_properties_changed(self):
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            for nid, w in list(self.open_diagrams.items()):
                if w == widget:
                    diag = self.project_model.get_diagram(nid)
                    if diag:
                        self.tabs.setTabText(i, f"[{nid}] {diag.title}")
                        break
        # Defer refresh to prevent deletion of the editing widget during focusOutEvent
        QTimer.singleShot(0, self.refresh_all_diagrams)

    def generate_diagram(self, node_id, title):
        # Create a blank diagram
        diagram = Diagram(node_number=node_id, title=title)
        
        if node_id == "A-0":
             # Context Diagram: Start empty per user request
             pass
        
        # Initial Layout
        from src.core.layout import calculate_diagonal_layout
        calculate_diagonal_layout(diagram)
        return diagram

    def apply_visual_settings_to_scene(self, scene, hide_arrows_override=None, hide_boxes_override=None):
        hide_arrows = hide_arrows_override if hide_arrows_override is not None else self.properties_panel.hide_arrows_check.isChecked()
        hide_boxes = hide_boxes_override if hide_boxes_override is not None else self.properties_panel.hide_boxes_check.isChecked()
        
        for item in scene.items():
            if isinstance(item, ActivityBoxItem):
                item.set_show_id(not hide_boxes)
                item.update_theme(self.is_night)
            elif isinstance(item, ArrowItem):
                item.icom_id_mode = self.icom_id_mode
                item.set_show_id(not hide_arrows)
                item.update_theme(self.is_night)
        
        # Also update frame if present
        from src.gui.frame_item import DiagramFrameItem
        for item in scene.items():
            if isinstance(item, DiagramFrameItem):
                item.update_theme(self.is_night)

    def save_model(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Export Functional Model", "", "IDEF0 Model (*.idef0)")
        if not filename: return
        # A name typed without one is written with no extension at all, and the
        # file then does not show up under its own filter when reopening.
        if not os.path.splitext(filename)[1]:
            filename += ".idef0"

        try:
            # Export functional only: strip visual locations and colors
            xml_content = model_to_xml(self.project_model, functional_only=True)
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(xml_content)
            self.log_message("Functional model exported successfully")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export model:\n{str(e)}")
            self.log_message("Error: Failed to export model")

    def export_architecture(self, target: str):
        """Write the functional architecture out in one of the supported notations.

        One handler for all of them: they differ only in the dialog caption, the
        file filter and which renderer runs, and every one of them used to repeat
        the same open-write-log-catch block with its own chance of drifting out
        of step with the others.
        """
        from src.core import (bpmn_export, code_export, plantuml_export,
                              sysml_export, uml_export)

        targets = {
            "python": ("Export Python Code", "Python Script (*.py)", ".py",
                       code_export.export_to_python),
            "java": ("Export Java Code", "Java Source (*.java)", ".java",
                     code_export.export_to_java),
            "cpp": ("Export C++ Code", "C++ Source (*.cpp)", ".cpp",
                    code_export.export_to_cpp),
            "sysml": ("Export SysML v2", "SysML v2 (*.sysml)", ".sysml",
                      sysml_export.export_to_sysml),
            "uml": ("Export UML (XMI)", "UML XMI (*.xmi *.uml)", ".xmi",
                    uml_export.export_to_uml),
            "plantuml": ("Export PlantUML", "PlantUML (*.puml *.plantuml)",
                         ".puml", plantuml_export.export_to_plantuml),
            "bpmn": ("Export BPMN 2.0", "BPMN 2.0 (*.bpmn *.xml)", ".bpmn",
                     bpmn_export.export_to_bpmn),
        }
        if target not in targets:
            return
        caption, file_filter, suffix, render = targets[target]

        filename, _ = QFileDialog.getSaveFileName(self, caption, "", file_filter)
        if not filename:
            return
        if not os.path.splitext(filename)[1]:
            filename += suffix

        try:
            # Java requires the public class to match the file name; the other
            # renderers ignore the extra argument.
            if target == "java":
                content = render(self.project_model,
                                 os.path.splitext(os.path.basename(filename))[0])
            else:
                content = render(self.project_model)
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(content)
            self.log_message(f"{caption.replace('Export ', '')} written to "
                             f"{os.path.basename(filename)}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"{caption} failed:\n{str(e)}")
            self.log_message(f"Error: {caption} failed - {e}")

    def export_to_sysml_file(self):
        self.export_architecture("sysml")

    def export_to_python_file(self):
        self.export_architecture("python")

    def export_to_java_file(self):
        self.export_architecture("java")

    def export_to_cpp_file(self):
        self.export_architecture("cpp")

    def export_to_uml_file(self):
        self.export_architecture("uml")

    def export_to_bpmn_file(self):
        self.export_architecture("bpmn")

    def open_model(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Import Functional Model", "", "IDEF0 Model (*.idef0)")
        if not filename: return
        
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                xml_content = f.read()
            model = xml_to_model(xml_content)
            
            if isinstance(model, IDEF0Model):
                # Check if this is a functional import (no coordinates)
                # If all boxes in all diagrams are at (0,0), it's likely functional only
                functional_only = True
                for diag in model.diagrams:
                    for box in diag.boxes:
                        if box.x != 0 or box.y != 0:
                            functional_only = False
                            break
                    if not functional_only: break
                
                if functional_only:
                    from src.core.layout import calculate_diagonal_layout
                    for diag in model.diagrams:
                        calculate_diagonal_layout(diag)
                        # Clear arrow segments to force standard re-routing based on new layout
                        for arrow in diag.arrows:
                            arrow.segments = []
                    
                    # Reset properties panel to standard defaults for functional imports
                    self.properties_panel.h_space_spin.setValue(250)
                    self.properties_panel.v_space_spin.setValue(200)
                    self.properties_panel.box_width_spin.setValue(150)
                    self.properties_panel.box_height_spin.setValue(100)
                    
                    self.log_message("Functional model imported and auto-laid out")
                
                self.project_model = model
                self.reset_ui_and_open_root()
            else:
                QMessageBox.warning(self, "Invalid File", "This is not a valid IDEF0 model file.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open model:\n{str(e)}")
            self.log_message("Error: Failed to open model")

    def new_project(self):
        # Ask to save current project
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText("Do you want to save your current project before starting a new one?")
        msg.setWindowTitle("New Project")
        msg.setStandardButtons(QMessageBox.StandardButton.Save | 
                               QMessageBox.StandardButton.No | 
                               QMessageBox.StandardButton.Cancel)
        
        ret = msg.exec()
        
        if ret == QMessageBox.StandardButton.Save:
            self.save_project()
        elif ret == QMessageBox.StandardButton.No:
            pass
        else: # Cancel
            return
            
        # Create fresh model
        self.project_model = IDEF0Model("New Project")
        self.reset_ui_and_open_root()
        self.log_message("New project created")

    def save_project(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Save Project", "", "IDEF Project (*.idefproj)")
        if not filename: return
        if not os.path.splitext(filename)[1]:
            filename += ".idefproj"

        try:
            # Full save (XML format as original, but with .idefproj extension)
            xml_content = model_to_xml(self.project_model, functional_only=False)
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(xml_content)
            self.log_message("Project saved successfully")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save project:\n{str(e)}")
            self.log_message("Error: Failed to save project")

    def open_project(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Open Project", "", "IDEF Project (*.idefproj);;IDEF0 Model (*.idef0)")
        if not filename: return
        
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                xml_content = f.read()
            model = xml_to_model(xml_content)
            
            if isinstance(model, IDEF0Model):
                # Check for functional import
                functional_only = True
                for diag in model.diagrams:
                    for box in diag.boxes:
                        if box.x != 0 or box.y != 0:
                            functional_only = False
                            break
                    if not functional_only: break
                
                if functional_only:
                    from src.core.layout import calculate_diagonal_layout
                    for diag in model.diagrams:
                        calculate_diagonal_layout(diag)
                        for arrow in diag.arrows:
                            arrow.segments = []
                    
                    # Reset properties panel to standard defaults for functional imports
                    self.properties_panel.h_space_spin.setValue(250)
                    self.properties_panel.v_space_spin.setValue(200)
                    self.properties_panel.box_width_spin.setValue(150)
                    self.properties_panel.box_height_spin.setValue(100)

                self.project_model = model
                # Note: Night mode/global spacing are currently not in the XML schema, 
                # but fonts and locations are handled within the model objects.
                self.reset_ui_and_open_root()
            else:
                QMessageBox.warning(self, "Invalid File", "This is not a valid IDEF0 model/project file.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open project:\n{str(e)}")

    def apply_metadata(self, metadata):
        self.is_night = metadata.get("is_night", False)
        self.night_mode_action.setChecked(self.is_night)
        self.current_box_color = metadata.get("box_color", "#ffffff")
        
        # Layout Spacing
        self.properties_panel.h_space_spin.setValue(metadata.get("h_spacing", 250))
        self.properties_panel.v_space_spin.setValue(metadata.get("v_spacing", 200))
        self.properties_panel.box_width_spin.setValue(metadata.get("box_width", 150))
        self.properties_panel.box_height_spin.setValue(metadata.get("box_height", 100))
        
        self.toggle_theme() # Apply night mode and colors

    def reset_ui_and_open_root(self):
        # The history belongs to the project that was loaded. Carried across an
        # Open or New, one press of Undo replaces the project just opened with
        # the previous one - which is not an undo of anything the user did.
        self.undo_stack.clear()

        self.tabs.clear()
        self.open_diagrams.clear()

        if self.project_model.diagrams:
            root = self.project_model.get_diagram("A-0")
            if root:
                self.ensure_diagram_open("A-0", root.title)
            else:
                first = self.project_model.diagrams[0]
                self.ensure_diagram_open(first.node_number, first.title)
        else:
            # Empty model?
            self.ensure_diagram_open("A-0", "Context Diagram")
            
        self.log_message("Project loaded successfully")

    def close_tab(self, index):
        widget = self.tabs.widget(index)
        # Find node_id
        for nid, w in list(self.open_diagrams.items()):
            if w == widget:
                del self.open_diagrams[nid]
                break
        self.tabs.removeTab(index)

    def run_verification_report(self):
        try:
            # An open report is re-run against the model as it stands now.
            # Switching to it untouched showed whatever the model looked like
            # when the tab was first opened - and after opening a different
            # project, a report on a model no longer loaded.
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i) == "Verification Report":
                    self.tabs.widget(i).set_model(self.project_model)
                    self.tabs.setCurrentIndex(i)
                    self.log_message("Verification Report refreshed")
                    return

            report_tab = VerificationReportTab(self.project_model,
                                               is_night=self.is_night)
            index = self.tabs.addTab(report_tab, "Verification Report")
            self.tabs.setCurrentIndex(index)
            self.log_message("Verification Report generated")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to generate verification report:\n{str(e)}")

    def on_tab_changed(self, index):
        if index == -1:
            self.item_panel.setVisible(False)
            return
            
        tab_text = self.tabs.tabText(index)
        if tab_text.startswith("["):
            self.item_panel.setVisible(True)
        else:
            self.item_panel.setVisible(False)
            
        # Refresh selection state
        self.on_selection_changed()

    def on_selection_changed(self):
        if not self.current_scene: return
        
        selected = self.current_scene.selectedItems()
        if not selected:
            self.item_panel.clear_panel()
            return
            
        # Prioritize ActivityBoxItem for properties, but also check Arrows
        # Filter for boxes
        boxes = [item for item in selected if isinstance(item, ActivityBoxItem)]
        
        # Filter for arrows (directly selected or via label)
        arrows = []
        is_arrow_label_clicked = False
        for item in selected:
            if isinstance(item, ArrowItem):
                arrows.append(item)
            elif isinstance(item, ArrowLabelItem):
                is_arrow_label_clicked = True
                # ArrowLabelItem stores reference to parent ArrowItem in .arrow_item
                if hasattr(item, 'arrow_item'):
                    arrows.append(item.arrow_item)
        
        if boxes:
            box = boxes[0]
            self.item_panel.update_panel(
                item_type="box",
                item_id=box.box_data.id,
                item_name=box.box_data.name,
                description=box.box_data.description,
                font_family=box.get_font_family(),
                font_size=box.get_font_size(),
                is_bold=box.get_font_bold(),
                is_italic=box.get_font_italic()
            )
        elif arrows:
            arrow = arrows[0]
            f_family = arrow.get_label_font_family()
            f_bold = arrow.get_label_font_bold()
            f_italic = arrow.get_label_font_italic()
            f_size = arrow.get_label_font_size()
            
            style = getattr(arrow.arrow_data, 'style', "Solid") if getattr(arrow, 'arrow_data', None) else "Solid"
            thickness = getattr(arrow.arrow_data, 'thickness', 2) if getattr(arrow, 'arrow_data', None) else 2
            icom_style = getattr(arrow, 'icom_callout_style', "Jagged")
            
            description = getattr(arrow.arrow_data, 'description', "") if getattr(arrow, 'arrow_data', None) else ""
            
            # Use icom_code if it exists, otherwise fall back to internal arrow_id
            item_id = arrow.arrow_id
            if arrow.arrow_data and arrow.arrow_data.icom_code:
                item_id = arrow.arrow_data.icom_code

            auto_id = (getattr(arrow.arrow_data, 'auto_icom_code', "") or ""
                       if getattr(arrow, 'arrow_data', None) else "")


            hide_label = getattr(arrow.arrow_data, 'hide_label', False) if getattr(arrow, 'arrow_data', None) else False
            
            self.item_panel.update_panel(
                item_type="arrow_label" if is_arrow_label_clicked else "arrow",
                item_id=item_id,
                item_name=arrow.label_text,
                description=description,
                font_family=f_family,
                font_size=f_size,
                is_bold=f_bold,
                is_italic=f_italic,
                extra_props={
                    "style": style,
                    "thickness": thickness,
                    "icom_style": icom_style,
                    "hide_label": hide_label,
                    "auto_id": auto_id,
                    "tunnel_source": getattr(arrow.arrow_data, 'tunnel_source', False)
                                     if getattr(arrow, 'arrow_data', None) else False,
                    "tunnel_target": getattr(arrow.arrow_data, 'tunnel_target', False)
                                     if getattr(arrow, 'arrow_data', None) else False,
                }
            )

    def update_selected_auto_id(self, new_code):
        """Edit the standard ICOM code of the selected arrow.

        Left blank the diagram regenerates it from the arrow's position, which
        is what ISO/IEC/IEEE 31320-1 asks for; typed in, the entry stands until
        it is cleared again.
        """
        if not self.current_scene:
            return
        selected = self.current_scene.selectedItems()
        if not selected:
            return

        self.save_snapshot()
        code = (new_code or "").strip()
        for item in selected:
            arrow_item = None
            if isinstance(item, ArrowItem):
                arrow_item = item
            elif isinstance(item, ArrowLabelItem) and hasattr(item, 'arrow_item'):
                arrow_item = item.arrow_item
            if arrow_item and getattr(arrow_item, 'arrow_data', None):
                arrow_item.arrow_data.auto_icom_code = code or None
                arrow_item.arrow_data.auto_icom_code_manual = bool(code)
                arrow_item.update_label_display()
        self.current_scene.update()
        self.log_message(f"Standard ICOM code set to '{code or 'auto'}'")

    def update_selected_hide_label(self, hide):
        if not self.current_scene: return
        selected = self.current_scene.selectedItems()
        for item in selected:
            arrow_item = None
            if isinstance(item, ArrowItem):
                arrow_item = item
            elif isinstance(item, ArrowLabelItem) and hasattr(item, 'arrow_item'):
                arrow_item = item.arrow_item
                
            if arrow_item and hasattr(arrow_item, 'arrow_data'):
                arrow_item.arrow_data.hide_label = hide
                if hasattr(arrow_item, 'update_label_display'):
                    arrow_item.update_label_display()
        self.current_scene.update()
        self.log_message(f"Label visibility toggled to {'hidden' if hide else 'visible'}")

    def update_selected_tunnel(self, end, on):
        """Bracket or unbracket one end of the selected arrows (clause 9.4).

        The notation is drawn from the arrow's own flags, so the item only has
        to be repainted - `prepareGeometryChange` because the brackets sit
        outside the line's own bounds and the cached rect has to grow with them.
        """
        if not self.current_scene:
            return
        selected = self.current_scene.selectedItems()
        if not selected:
            return

        self.save_snapshot()
        for item in selected:
            arrow_item = None
            if isinstance(item, ArrowItem):
                arrow_item = item
            elif isinstance(item, ArrowLabelItem) and hasattr(item, 'arrow_item'):
                arrow_item = item.arrow_item
            if not (arrow_item and getattr(arrow_item, 'arrow_data', None)):
                continue
            setattr(arrow_item.arrow_data, f"tunnel_{end}", on)
            setattr(arrow_item, f"tunnel_{end}", on)
            arrow_item.prepareGeometryChange()
            arrow_item.update()
        self.current_scene.update()
        self.log_message(
            f"Tunnel notation {'added to' if on else 'removed from'} the arrow "
            f"{'tail' if end == 'source' else 'head'}")

    def check_id_sequence(self, diagram, new_id):
        """Warns the user if the new ID skips a number in the sequence."""
        if not new_id or not diagram: return
        
        node_num = getattr(diagram, 'node_number', '')
        if node_num in ["A-0", "A0"]:
            expected_prefix = "A"
        elif node_num:
            expected_prefix = node_num
        else:
            expected_prefix = ""
            
        def parse_id(id_str):
            if expected_prefix and id_str.startswith(expected_prefix):
                suffix = id_str[len(expected_prefix):]
                if suffix.isdigit():
                    return expected_prefix, int(suffix)
            
            match = re.search(r'([A-Za-z\-]+)(\d+)$', id_str)
            if match:
                prefix, num_str = match.groups()
                return prefix, int(num_str)
            return None, None

        prefix, num = parse_id(new_id)
        if prefix is None: return
        
        # Get existing numeric suffixes for the same prefix
        existing_nums = []
        for box in diagram.boxes:
            if box.id == new_id: continue # Skip if already in (during rename)
            box_prefix, box_num = parse_id(box.id)
            if box_prefix == prefix:
                existing_nums.append(box_num)
        
        if not existing_nums:
            if num > 1:
                QMessageBox.warning(self, "Non-sequential ID", f"ID '{new_id}' starts at {num}, but usually should start at 1.")
            return
            
        max_num = max(existing_nums)
        if num > max_num + 1:
            QMessageBox.warning(self, "Non-sequential ID", 
                                f"The ID '{new_id}' is non-sequential within this diagram. "
                                f"Expected next ID is '{prefix}{max_num + 1}'.")

    def update_selected_id(self, new_id):
        if not self.current_scene: return
        selected = self.current_scene.selectedItems()
        if not selected: return
        
        self.save_snapshot()
        from src.gui.diagram_items import ActivityBoxItem, ArrowItem, ArrowLabelItem
        
        has_boundary_change = False
        for item in selected:
            if isinstance(item, ActivityBoxItem):
                # Check sequence if renamed
                if self.current_scene and hasattr(self.current_scene, 'diagram_data'):
                    self.check_id_sequence(self.current_scene.diagram_data, new_id)
                item.set_box_id(new_id)
            elif isinstance(item, ArrowItem):
                if item.arrow_data:
                    if item.arrow_data.is_boundary() or item.arrow_data.branch_parent_id or item.arrow_data.join_target_id or item.arrow_data.icom_code:
                        item.arrow_data.icom_code = new_id
                        has_boundary_change = True
                    else:
                        item.arrow_id = new_id
                        item.arrow_data.id = new_id
                else:
                    item.arrow_id = new_id
                item.update_label_display()
            elif isinstance(item, ArrowLabelItem) and hasattr(item, 'arrow_item'):
                arrow_item = item.arrow_item
                if arrow_item.arrow_data:
                    if arrow_item.arrow_data.is_boundary() or arrow_item.arrow_data.branch_parent_id or arrow_item.arrow_data.join_target_id or arrow_item.arrow_data.icom_code:
                        arrow_item.arrow_data.icom_code = new_id
                        has_boundary_change = True
                    else:
                        arrow_item.arrow_id = new_id
                        arrow_item.arrow_data.id = new_id
                else:
                    arrow_item.arrow_id = new_id
                arrow_item.update_label_display()
        
        if has_boundary_change:
            # Propagate ID change (e.g. P.2) to all diagrams
            for diag in self.project_model.diagrams:
                self.project_model.synchronize_boundaries(diag.node_number)
            self.log_message(f"Global ID synchronized: {new_id}")
        
        if self.current_scene and hasattr(self.current_scene, 'diagram_data'):
            self.refresh_all_diagrams()

    def update_selected_name(self, new_name):
        if not self.current_scene: return
        selected = self.current_scene.selectedItems()
        if not selected: return
        
        self.save_snapshot()
        from src.gui.diagram_items import ActivityBoxItem, ArrowItem, ArrowLabelItem
        
        for item in selected:
            if isinstance(item, ActivityBoxItem):
                item.box_data.name = new_name
                item.name_text.setPlainText(new_name)
                item.center_text()
            elif isinstance(item, ArrowItem):
                item.label_text = new_name
                if item.arrow_data:
                    item.arrow_data.label = new_name
                    # Rename globally for all arrows with this ID across all diagrams
                    target_id = item.arrow_id
                    for d in self.project_model.diagrams:
                        for a in d.arrows:
                            if a.id == target_id:
                                a.label = new_name
                item.update_label_display()
            elif isinstance(item, ArrowLabelItem) and hasattr(item, 'arrow_item'):
                item.arrow_item.label_text = new_name
                if item.arrow_item.arrow_data:
                    item.arrow_item.arrow_data.label = new_name
                    # Rename globally for all arrows with this ID across all diagrams
                    target_id = item.arrow_item.arrow_id
                    for d in self.project_model.diagrams:
                        for a in d.arrows:
                            if a.id == target_id:
                                a.label = new_name
                item.arrow_item.update_label_display()
        
        # Log and refresh
        self.log_message(f"Selected item(s) renamed to: {new_name}")
        self.refresh_all_diagrams()

    def update_selected_description(self, new_desc):
        if not self.current_scene: return
        selected = self.current_scene.selectedItems()
        if not selected: return
        
        self.save_snapshot()
        from src.gui.diagram_items import ActivityBoxItem, ArrowItem, ArrowLabelItem
        
        for item in selected:
            if isinstance(item, ActivityBoxItem):
                item.box_data.description = new_desc
            elif isinstance(item, ArrowItem):
                if item.arrow_data:
                    item.arrow_data.description = new_desc
            elif isinstance(item, ArrowLabelItem) and hasattr(item, 'arrow_item'):
                if item.arrow_item.arrow_data:
                    item.arrow_item.arrow_data.description = new_desc
        
    def force_refresh(self):
        """Manually triggered refresh for all diagrams"""
        self.refresh_all_diagrams()
        self.log_message("Diagram layout refreshed")

    def get_target_items(self, item_type=None):
        if not self.current_scene: return []
        selected = self.current_scene.selectedItems()
        target = []
        if selected:
            if item_type:
                target = [item for item in selected if isinstance(item, item_type)]
            else:
                target = selected
        else:
            if item_type:
                target = [item for item in self.current_scene.items() if isinstance(item, item_type)]
            else:
                target = self.current_scene.items()
        return target

    def update_layout_settings(self, spacing_x, spacing_y, box_w, box_h):
        self.save_snapshot()
        # 1. Update active diagram if applicable
        if self.current_scene and hasattr(self.current_scene, 'diagram_data'):
            diag = self.current_scene.diagram_data
            if diag:
                from src.core.layout import calculate_diagonal_layout
                for box in diag.boxes:
                    box.width = box_w
                    box.height = box_h
                calculate_diagonal_layout(diag, spacing_x=spacing_x, spacing_y=spacing_y)
                
                # Clear arrow segments and junction data to force a perfectly clean re-route
                for arrow in diag.arrows:
                    arrow.segments = []
                    arrow.junction_point = None
                    arrow.branch_points = []
                    arrow.join_points = []
                
                # Preserve frame visibility
                was_frame_enabled = self.current_scene.frame_enabled
                
                self.current_scene.load_diagram(diag, project_model=self.project_model)
                
                # Restore frame
                self.current_scene.set_frame_visible(was_frame_enabled)
                
                for item in self.current_scene.items():
                    if hasattr(item, 'update_theme'):
                         item.update_theme(self.is_night)
                self.center_view()
        
        # 2. Refresh Node Tree if open (regardless of which tab is active)
        # We find the tab index first
        tree_idx = -1
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == "Node Tree":
                tree_idx = i
                break
        
        if tree_idx != -1:
            # Remember focus
            prev_active_idx = self.tabs.currentIndex()
            # If the tree IS the active tab, we must be careful
            is_tree_active = (prev_active_idx == tree_idx)
            
            # Remove and re-generate
            # We must block signals to prevent recursive layout_changed if we were to trigger tab changes
            self.tabs.blockSignals(True)
            self.tabs.removeTab(tree_idx)
            self.generate_node_tree(fit_to_view=False) # Keep zoom constant
            
            # Restore previous focus if tree wasn't active
            if not is_tree_active:
                # The index might have shifted if the tree was before current
                new_idx = prev_active_idx
                if tree_idx < prev_active_idx:
                    new_idx -= 1
                # But generate_node_tree adds at the end, so index is tabs.count() - 1
                self.tabs.setCurrentIndex(new_idx)
            
            self.tabs.blockSignals(False)
            
    def update_font_size(self, size):
        self.save_snapshot()
        if not self.current_scene: return
        from src.gui.diagram_items import ActivityBoxItem
        
        # Check what is selected to determine what to update
        selected = self.current_scene.selectedItems()
        
        # If Selection: Update Selected Only
        if selected:
            for item in selected:
                if isinstance(item, ActivityBoxItem):
                    item.set_font_size(size)
        else:
            # Global: Update ALL boxes in the project
            for diag in self.project_model.diagrams:
                for box in diag.boxes:
                    box.font_size = size
            self.refresh_all_diagrams()

    def update_icom_font_size(self, size):
        self.save_snapshot()
        if not self.current_scene: return
        from src.gui.diagram_items import ArrowItem, ArrowLabelItem
        
        # Check what is selected to determine what to update
        selected = self.current_scene.selectedItems()
        
        # If Selection: Update Selected Only
        if selected:
            for item in selected:
                if isinstance(item, ArrowItem):
                    item.set_label_font_size(size)
                elif isinstance(item, ArrowLabelItem) and hasattr(item, 'arrow_item'):
                    item.arrow_item.set_label_font_size(size)
        else:
            # Global: Update ALL arrows in the project
            for diag in self.project_model.diagrams:
                for arrow in diag.arrows:
                    arrow.label_font_size = size
            self.refresh_all_diagrams()

    def update_box_color(self, color):
        self.save_snapshot()
        self.current_box_color = color.name()
        # Apply to selection or global
        selected = self.current_scene.selectedItems() if self.current_scene else []
        if selected:
            from src.gui.diagram_items import ActivityBoxItem
            for item in selected:
                if isinstance(item, ActivityBoxItem):
                    item.set_box_color(color)
        else:
            # Global color change: update ALL boxes in the project model
            for diag in self.project_model.diagrams:
                for box in diag.boxes:
                    box.color = color.name()
            self.refresh_all_diagrams()

    def update_global_font_family(self, family):
        self.save_snapshot()
        for diag in self.project_model.diagrams:
            for box in diag.boxes: box.font_family = family
            for arrow in diag.arrows: arrow.label_font_family = family
        self.refresh_all_diagrams()

    def update_global_font_size(self, size):
        self.save_snapshot()
        for diag in self.project_model.diagrams:
            for box in diag.boxes: box.font_size = size
            for arrow in diag.arrows: arrow.label_font_size = size
        self.refresh_all_diagrams()

    def update_global_font_bold(self, bold):
        self.save_snapshot()
        for diag in self.project_model.diagrams:
            for box in diag.boxes: box.font_bold = bold
            for arrow in diag.arrows: arrow.label_font_bold = bold
        self.refresh_all_diagrams()

    def update_global_font_italic(self, italic):
        self.save_snapshot()
        for diag in self.project_model.diagrams:
            for box in diag.boxes: box.font_italic = italic
            for arrow in diag.arrows: arrow.label_font_italic = italic
        self.refresh_all_diagrams()

    def update_font_family(self, family):
        self.save_snapshot()
        selected = self.current_scene.selectedItems() if self.current_scene else []
        if selected:
            # Each setter below repaints its item directly, so refreshing here
            # would rebuild every item from the model and drop the selection -
            # closing the item panel on whatever was just being edited.
            from src.gui.diagram_items import ActivityBoxItem, ArrowItem, ArrowLabelItem
            for item in selected:
                if isinstance(item, ActivityBoxItem): item.set_font_family(family)
                elif isinstance(item, ArrowItem): item.set_label_font_family(family)
                elif isinstance(item, ArrowLabelItem) and hasattr(item, 'arrow_item'):
                    item.arrow_item.set_label_font_family(family)
        else:
            for diag in self.project_model.diagrams:
                for box in diag.boxes: box.font_family = family
                for arrow in diag.arrows: arrow.label_font_family = family
            self.refresh_all_diagrams()

    def update_font_bold(self, is_bold):
        self.save_snapshot()
        selected = self.current_scene.selectedItems() if self.current_scene else []
        if selected:
            from src.gui.diagram_items import ActivityBoxItem, ArrowItem, ArrowLabelItem
            for item in selected:
                if isinstance(item, ActivityBoxItem): item.set_font_bold(is_bold)
                elif isinstance(item, ArrowItem): item.set_label_font_bold(is_bold)
                elif isinstance(item, ArrowLabelItem) and hasattr(item, 'arrow_item'):
                    item.arrow_item.set_label_font_bold(is_bold)
        else:
            for diag in self.project_model.diagrams:
                for box in diag.boxes: box.font_bold = is_bold
                for arrow in diag.arrows: arrow.label_font_bold = is_bold
            self.refresh_all_diagrams()

    def update_font_italic(self, is_italic):
        self.save_snapshot()
        selected = self.current_scene.selectedItems() if self.current_scene else []
        if selected:
            from src.gui.diagram_items import ActivityBoxItem, ArrowItem, ArrowLabelItem
            for item in selected:
                if isinstance(item, ActivityBoxItem): item.set_font_italic(is_italic)
                elif isinstance(item, ArrowItem): item.set_label_font_italic(is_italic)
                elif isinstance(item, ArrowLabelItem) and hasattr(item, 'arrow_item'):
                    item.arrow_item.set_label_font_italic(is_italic)
        else:
            for diag in self.project_model.diagrams:
                for box in diag.boxes: box.font_italic = is_italic
                for arrow in diag.arrows: arrow.label_font_italic = is_italic
            self.refresh_all_diagrams()

    def zoom_in(self):
        view = self.tabs.currentWidget()
        if isinstance(view, ZoomableView):
            view.scale(1.15, 1.15)
            
    def zoom_out(self):
        view = self.tabs.currentWidget()
        if isinstance(view, ZoomableView):
            view.scale(1/1.15, 1/1.15)
            
    def reset_zoom(self):
        view = self.tabs.currentWidget()
        if isinstance(view, ZoomableView):
            view.resetTransform()
            self.center_view()

    def center_view(self):
        if not self.current_scene: return
        items_rect = self.current_scene.itemsBoundingRect()
        self.current_scene.setSceneRect(items_rect.adjusted(-100, -100, 100, 100))
        # Need to center the view associated with this scene
        # We can't easily get View from Scene unless we store it.
        # But we found scene via self.tabs.currentWidget() which IS the view.
        view = self.tabs.currentWidget()
        if isinstance(view, QGraphicsView) and view.scene() == self.current_scene:
            view.centerOn(items_rect.center())
        
    def create_menu_bar(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        
        # Project Actions
        new_proj_action = file_menu.addAction("New Project")
        new_proj_action.setShortcut("Ctrl+N")
        new_proj_action.triggered.connect(self.new_project)
        
        file_menu.addSeparator()

        save_proj_action = file_menu.addAction("Save Project")
        save_proj_action.setShortcut("Ctrl+S")
        save_proj_action.triggered.connect(self.save_project)
        
        open_proj_action = file_menu.addAction("Open Project")
        open_proj_action.setShortcut("Ctrl+O")
        open_proj_action.triggered.connect(self.open_project)
        
        file_menu.addSeparator()
        
        # Export/Import Actions
        import_action = file_menu.addAction("Import IDEF0 Model")
        import_action.triggered.connect(self.open_model)
        
        export_model_action = file_menu.addAction("Export IDEF0 Model")
        export_model_action.triggered.connect(self.save_model)
        
        file_menu.addSeparator()
        
        # Code Export Submenu
        code_export_menu = file_menu.addMenu("Export Code Architecture")
        for label, target in (("Python", "python"), ("Java", "java"), ("C++", "cpp")):
            action = code_export_menu.addAction(label)
            action.triggered.connect(lambda checked, t=target: self.export_architecture(t))

        code_export_menu.addSeparator()
        # XMI is for a UML tool that reads a model file; PlantUML renders its own
        # text syntax and cannot read XMI at all, so it needs its own writer.
        for label, target in (("SysML v2", "sysml"), ("UML (XMI 2.1)", "uml"),
                              ("UML (PlantUML)", "plantuml"),
                              ("BPMN 2.0", "bpmn")):
            action = code_export_menu.addAction(label)
            action.triggered.connect(lambda checked, t=target: self.export_architecture(t))
        
        # View Menu
        view_menu = menubar.addMenu("View")
        
        context_view_act = view_menu.addAction("View Context Diagram")
        context_view_act.triggered.connect(lambda: self.ensure_diagram_open("A-0", f"Context - {self.project_model.name}"))
        
        view_menu.addSeparator()
        
        zoom_in_act = view_menu.addAction("Zoom In")
        zoom_in_act.setShortcut("Ctrl++")
        zoom_in_act.triggered.connect(self.zoom_in)
        
        zoom_out_act = view_menu.addAction("Zoom Out")
        zoom_out_act.setShortcut("Ctrl+-")
        zoom_out_act.triggered.connect(self.zoom_out)
        
        reset_zoom_act = view_menu.addAction("Reset Zoom")
        reset_zoom_act.setShortcut("Ctrl+0")
        reset_zoom_act.triggered.connect(self.reset_zoom)
        
        view_menu.addSeparator()

        # ICOM IDs: which of an arrow's two identities its label prints. Both
        # are always editable in the properties panel, whatever is on show here.
        icom_id_menu = view_menu.addMenu("ICOM IDs")
        self.icom_id_group = QActionGroup(self)
        self.icom_id_actions = {}
        for label, mode in (("User Defined", "user"), ("Auto", "auto"),
                            ("Both", "both"), ("None", "none")):
            action = icom_id_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(mode == self.icom_id_mode)
            action.triggered.connect(lambda checked, m=mode: self.set_icom_id_mode(m))
            self.icom_id_group.addAction(action)
            self.icom_id_actions[mode] = action

        view_menu.addSeparator()
        view_icoms_act = view_menu.addAction("View ICOMs")
        view_icoms_act.setShortcut("Ctrl+Shift+I")
        view_icoms_act.triggered.connect(self.open_view_icoms_tab)

        view_funcs_act = view_menu.addAction("View Functions")
        view_funcs_act.setShortcut("Ctrl+Shift+F")
        view_funcs_act.triggered.connect(self.open_view_functions_tab)

        # The two display toggles sit last: they are persistent settings rather
        # than actions, and everything above them does something once.
        view_menu.addSeparator()

        night_mode_action = view_menu.addAction("Night Mode")
        night_mode_action.setCheckable(True)
        night_mode_action.triggered.connect(self.toggle_theme)
        self.night_mode_action = night_mode_action

        self.border_frame_action = view_menu.addAction("Show Border Frame")
        self.border_frame_action.setCheckable(True)
        self.border_frame_action.setChecked(False) # Default off
        self.border_frame_action.triggered.connect(self.toggle_frame)
        self.show_border_frame = False # Persistent state




        
        # Move Export/Exit to File menu
        export_action = file_menu.addAction("Export Diagram")
        export_action.triggered.connect(self.export_diagram)

        file_menu.addSeparator()

        about_action = file_menu.addAction("About")
        about_action.triggered.connect(self.show_about_dialog)

        file_menu.addSeparator()

        exit_action = file_menu.addAction("Exit")
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        
        # Model Menu
        model_menu = menubar.addMenu("Model")
        
        undo_action = model_menu.addAction("Undo")
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(self.handle_undo)
        
        reset_action = model_menu.addAction("Reset Diagram")
        reset_action.triggered.connect(self.handle_reset)
        
        model_menu.addSeparator()
        
        add_box_action = model_menu.addAction("Add Function Box")
        add_box_action.setShortcut("Ctrl+B")
        add_box_action.triggered.connect(self.add_function_box)
        
        add_arrow_action = model_menu.addAction("Add Arrow")
        add_arrow_action.setShortcut("Ctrl+A")
        add_arrow_action.triggered.connect(self.add_arrow)

        assign_arrow_action = model_menu.addAction("Assign Arrow")
        assign_arrow_action.triggered.connect(self.assign_boundary_arrows)

        model_menu.addSeparator()

        # Arrowhead Style Submenu
        arrow_style_menu = model_menu.addMenu("Arrowhead Style")
        self.arrowhead_group = QActionGroup(self)
        for name, style in [("Filled", "Standard"), ("Open", "Open"), ("Sharp", "Stealth")]:
            action = arrow_style_menu.addAction(name)
            action.setCheckable(True)
            if style == "Standard": action.setChecked(True) # Default
            action.triggered.connect(lambda checked, s=style: self.update_arrowhead_style(s))
            self.arrowhead_group.addAction(action)

        # ICOM Callout Style Submenu
        icom_menu = model_menu.addMenu("Label Callout Style")
        self.icom_style_group = QActionGroup(self)
        for sname in ["Jagged", "Straight", "Rounded"]:
            action = icom_menu.addAction(sname)
            action.setCheckable(True)
            if sname == "Jagged": action.setChecked(True)
            action.triggered.connect(lambda checked, s=sname: self.update_icom_callout_style(s))
            self.icom_style_group.addAction(action)

        model_menu.addSeparator()
        
        auto_route_action = model_menu.addAction("Automatically Route Arrows")
        auto_route_action.triggered.connect(self.auto_route_current_diagram)

        # Report Menu (Moved here, before Help)
        report_menu = menubar.addMenu("Report")
        node_tree_action = report_menu.addAction("Generate Node Tree")
        node_tree_action.triggered.connect(self.generate_node_tree)

        # Routing Style for Tree - sits with the tree it styles
        routing_menu = report_menu.addMenu("Tree Routing Style")
        self.routing_group = QActionGroup(self)
        for rs in ["Straight", "Squared", "Rounded"]:
            action = routing_menu.addAction(rs)
            action.setCheckable(True)
            if rs.lower() == self.tree_routing_style:
                action.setChecked(True)
            action.triggered.connect(lambda checked, s=rs.lower(): self.set_tree_routing(s))
            self.routing_group.addAction(action)

        node_index_action = report_menu.addAction("Generate Node Index")
        node_index_action.triggered.connect(self.generate_node_index)

        report_menu.addSeparator()

        verification_action = report_menu.addAction("Verification Report (ISO 31320-1)")
        verification_action.triggered.connect(self.run_verification_report)

        # Specialized Reports
        flows_menu = report_menu.addMenu("Flow Reports")
        for ft in ["Input", "Control", "Output", "Mechanism"]:
            action = flows_menu.addAction(f"{ft} Index")
            action.triggered.connect(lambda checked, t=ft: self.generate_flow_index(t))

    def set_icom_id_mode(self, mode):
        """View > ICOM IDs: which ICOM identity every arrow label prints.

        'user' is the id the modeller assigned, 'auto' the positional code
        ISO/IEC/IEEE 31320-1 defines, 'both' shows "P.2 AM Part [O1]", 'none'
        leaves only the label text. It changes what is drawn and nothing else -
        both ids stay editable in the properties panel under every setting.
        """
        if mode not in ICOM_ID_MODES:
            return
        self.icom_id_mode = mode
        action = getattr(self, 'icom_id_actions', {}).get(mode)
        if action and not action.isChecked():
            action.setChecked(True)

        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            scene = widget.scene() if isinstance(widget, QGraphicsView) else None
            if not scene:
                continue
            for item in scene.items():
                if isinstance(item, ArrowItem):
                    item.set_icom_id_mode(mode)
        self.log_message(f"ICOM ID display: {mode}")

    def update_arrow_color(self, color):
        self.save_snapshot()
        selected = [i for i in self.current_scene.selectedItems() if isinstance(i, ArrowItem)] if self.current_scene else []
        if selected:
            # set_style_properties() already repaints the item in place, so a
            # full refresh here would only rebuild every item from the model -
            # dropping the selection and, with it, the item panel showing it.
            for item in selected:
                item.set_style_properties(color=color)
                if item.arrow_data:
                    item.arrow_data.color = color.name()
        else:
            # Global project update
            for diag in self.project_model.diagrams:
                for arrow in diag.arrows:
                    arrow.color = color.name()
            self.refresh_all_diagrams()

    def update_arrow_label_color(self, color):
        self.save_snapshot()
        selected = self.current_scene.selectedItems() if self.current_scene else []
        did_update = False
        for item in selected:
            if isinstance(item, ArrowLabelItem) and hasattr(item, 'arrow_item'):
                if item.arrow_item.arrow_data:
                    item.arrow_item.arrow_data.label_color = color.name()
                    did_update = True
        
        if not did_update:
            # Global project update
            for diag in self.project_model.diagrams:
                for arrow in diag.arrows:
                    arrow.label_color = color.name()
        self.refresh_all_diagrams()

    def update_arrow_thickness(self, width):
        self.save_snapshot()
        selected = [i for i in self.current_scene.selectedItems() if isinstance(i, ArrowItem)] if self.current_scene else []
        if selected:
            # Applied and repainted in place - see update_arrow_color for why
            # a refresh here would just close the item panel on the arrow the
            # user is still adjusting.
            for item in selected:
                item.set_style_properties(thickness=width)
                if item.arrow_data:
                    item.arrow_data.thickness = width
        else:
            # Global project update
            for diag in self.project_model.diagrams:
                for arrow in diag.arrows:
                    arrow.thickness = width
            self.refresh_all_diagrams()

    def update_arrow_style(self, style_name):
        self.save_snapshot()
        selected = [i for i in self.current_scene.selectedItems() if isinstance(i, ArrowItem)] if self.current_scene else []
        if selected:
            for item in selected:
                item.set_style_properties(style_name=style_name)
                if item.arrow_data:
                    item.arrow_data.style = style_name
        else:
            # Global project update
            for diag in self.project_model.diagrams:
                for arrow in diag.arrows:
                    arrow.style = style_name
            self.refresh_all_diagrams()

    def update_arrowhead_style(self, style_name):
        self.save_snapshot()
        selected = [i for i in self.current_scene.selectedItems() if isinstance(i, ArrowItem)] if self.current_scene else []
        if selected:
            for item in selected:
                item.set_arrowhead_style(style_name)
                if item.arrow_data:
                    item.arrow_data.arrowhead_style = style_name
        else:
            # Global project update
            for diag in self.project_model.diagrams:
                for arrow in diag.arrows:
                    arrow.arrowhead_style = style_name
            self.refresh_all_diagrams()

    UNDO_DEPTH = 5

    def save_snapshot(self):
        """Save the current project state to undo history.

        A snapshot is of the model, not of the view, so it must be taken
        whichever tab is in front. Requiring an active diagram scene meant an
        edit made in the ICOMs or Functions database recorded nothing - and the
        next Undo then reverted some earlier, unrelated change instead.
        """
        if not self.project_model:
            return

        if len(self.undo_stack) >= self.UNDO_DEPTH:
            self.undo_stack.pop(0)

        # Deep copy the entire project model using pickle
        state = pickle.dumps(self.project_model)
        self.undo_stack.append(state)

    def handle_reset(self):
        if not self.current_scene or not self.current_scene.initial_state: return
        
        data = pickle.loads(self.current_scene.initial_state)
        
        self.save_snapshot()
        
        # Update project model ref
        for i, d in enumerate(self.project_model.diagrams):
             if d.node_number == data.node_number:
                 self.project_model.diagrams[i] = data
                 break
        
        self.refresh_all_diagrams()
        self.log_message("Diagram reset to initial state")

    def log_message(self, message):
        """Display a status message in the bottom log panel"""
        self.status_label.setText(message)
        # Auto-clear after 5 seconds
        QTimer.singleShot(5000, lambda: self.status_label.setText("Ready"))

    def handle_undo(self):
        if not self.undo_stack:
             self.log_message("Nothing to undo")
             return
             
        state = self.undo_stack.pop()
        self.project_model = pickle.loads(state)
        
        self.refresh_all_diagrams()
        remaining = len(self.undo_stack)
        self.log_message(f"Undo successful ({remaining} changes remaining)")

    def add_function_box(self):
        self.save_snapshot()
        from src.gui.dialogs import AddActivityBoxDialog
        
        # Suggested ID logic
        current_diag = self.current_scene.diagram_data if self.current_scene else None
        
        prefix = current_diag.node_number if current_diag else "A"
        if prefix in ["A-0", "A0"]:
            prefix = "A"
            
        suggested_id = f"{prefix}1"
        
        # Special case override: If Context Diagram is empty, suggest A0
        if current_diag and current_diag.node_number == "A-0" and not current_diag.boxes:
             suggested_id = "A0"
        elif current_diag:
            existing_ids = [b.id for b in current_diag.boxes]
            i = 1
            while f"{prefix}{i}" in existing_ids:
                i += 1
            suggested_id = f"{prefix}{i}"

        dialog = AddActivityBoxDialog(suggested_id=suggested_id, parent=self)
        if dialog.exec():
            data = dialog.get_data()
            cid = data['id']
            name = data['name']
            
            # Helper to get parent ID
            def get_parent_id(child_id):
                if child_id == "A0": return "A-0"
                if child_id == "A-0": return None
                if child_id.startswith("A") and len(child_id) == 2: return "A0"
                if len(child_id) > 2: return child_id[:-1]
                return "A0"

            pid = get_parent_id(cid)
            if not pid:
                QMessageBox.warning(self, "Invalid ID", "Cannot add root node A-0.")
                return

            # Find or create target diagram
            diag = self.project_model.get_diagram(pid)
            if not diag:
                diag = self.generate_diagram(pid, f"Decomposition of {pid}")
                self.project_model.add_diagram(diag)
            
            # Check ID Sequence Consistency
            self.check_id_sequence(diag, cid)

            # Prevent duplicates
            if any(b.id == cid for b in diag.boxes):
                QMessageBox.warning(self, "Duplicate ID", f"Node {cid} already exists.")
                return

            # Enforce 2-9 Box Limit (Validation)
            # A-0 is exempt or handled differently (it has 1 box usually).
            # Constraint applies to decomposition diagrams.
            if len(diag.boxes) >= 9:
                QMessageBox.warning(self, "Limit Reached", "Maximum of 9 boxes allowed per diagram (ISO 31320-1).")
                return
                
            # Add to model
            diag.boxes.append(ActivityBox(id=cid, name=name))
            
            # Auto-layout to ensure the new box doesn't overlap at (0,0)
            from src.core.layout import calculate_diagonal_layout
            h_spacing = self.properties_panel.h_space_spin.value()
            v_spacing = self.properties_panel.v_space_spin.value()
            
            # Update all boxes to the current global dimensions from properties panel
            box_w = self.properties_panel.box_width_spin.value()
            box_h = self.properties_panel.box_height_spin.value()
            for box in diag.boxes:
                box.width = box_w
                box.height = box_h
                
            calculate_diagonal_layout(diag, spacing_x=h_spacing, spacing_y=v_spacing)
            
            # Sync GUI
            self.ensure_diagram_open(pid, diag.title)
            # Find the view for pid and refresh it
            if pid in self.open_diagrams:
                view = self.open_diagrams[pid]
                # Force refresh
                from src.gui.diagram_scene import DiagramScene
                if isinstance(view.scene(), DiagramScene):
                    view.scene().load_diagram(diag, project_model=self.project_model)
                    self.apply_visual_settings_to_scene(view.scene())
        
    def add_arrow(self):
        self.save_snapshot()
        if not self.current_scene or not self.current_scene.diagram_data:
            QMessageBox.warning(self, "Warning", "No diagram open.")
            return
            
        diagram = self.current_scene.diagram_data
        from src.gui.dialogs import AddArrowDialog
        
        dialog = AddArrowDialog(diagram, self)
        if dialog.exec():
            data = dialog.get_data()
            
            # Use User-defined Arrow ID
            arrow_id = data['id']
            
            # Junction Calculation
            junction_point = None
            
            # If branching, find a default branch point
            if data['branch_parent_id']:
                parent = next((a for a in diagram.arrows if a.id == data['branch_parent_id']), None)
                if parent and parent.segments:
                    # Pick a point in the middle of segments
                    mid = len(parent.segments) // 2
                    junction_point = parent.segments[mid]
                    # Also set the parent's branch point so it renders the dot
                    parent.branch_points.append(junction_point)
            
            # If joining, find a default join point
            if data['join_target_id']:
                target_arrow = next((a for a in diagram.arrows if a.id == data['join_target_id']), None)
                if target_arrow and target_arrow.segments:
                    # Pick a point in the middle of segments (maybe 2/3 down?)
                    mid = int(len(target_arrow.segments) * 0.7)
                    junction_point = target_arrow.segments[mid]
                    # Also set the target's join point so it renders the dot
                    target_arrow.join_points.append(junction_point)

            new_arrow = Arrow(
                id=arrow_id,
                source_box_id=data['source_id'],
                target_box_id=data['target_id'],
                type=data['arrow_type'],
                label=data['label'],
                branch_parent_id=data['branch_parent_id'],
                join_target_id=data['join_target_id'],
                is_manual_connection=bool(data['branch_parent_id'] or data['join_target_id']),
                junction_point=junction_point,
                tunnel_source=data['tunnel_source'],
                tunnel_target=data['tunnel_target']
            )
            
            diagram.arrows.append(new_arrow)
            
            # Clear all arrow segments to force full redistributive re-route
            for a in diagram.arrows:
                a.segments = None
            
            # Check for boundary consistency if this is a boundary arrow
            if new_arrow.source_box_id is None or new_arrow.target_box_id is None:
                self.project_model.synchronize_boundaries(diagram.node_number)
            
            self.refresh_current_diagram(diagram)

    def _generate_sequential_child_id(self, parent_id: str, diagram) -> str:
        import re
        prefix = f"{parent_id}."
        existing_indices = []
        for a in diagram.arrows:
            if a.id.startswith(prefix):
                suffix = a.id[len(prefix):]
                m = re.match(r'^(\d+)', suffix)
                if m:
                    existing_indices.append(int(m.group(1)))
                    
        next_index = max(existing_indices) + 1 if existing_indices else 1
        new_id = f"{prefix}{next_index}"
        
        while any(a.id == new_id for a in diagram.arrows):
            next_index += 1
            new_id = f"{prefix}{next_index}"
            
        return new_id

    def assign_boundary_arrows(self):
        if not self.current_scene or not self.current_scene.diagram_data:
            return
            
        diagram = self.current_scene.diagram_data
        from src.gui.dialogs import AssignArrowDialog
        
        # First, ensure we have the latest from parent
        self.project_model.synchronize_boundaries(diagram.node_number)
        
        dialog = AssignArrowDialog(diagram, self)
        if dialog.exec():
            data = dialog.get_data()
            arrow_id = data['arrow_id']
            box_id = data['box_id']
            
            arrow = next((a for a in diagram.arrows if a.id == arrow_id), None)
            if not arrow:
                # Find the arrow in the project model to copy/import it
                other_arrow = None
                for other_diag in self.project_model.diagrams:
                    other_arrow = next((a for a in other_diag.arrows if a.id == arrow_id), None)
                    if other_arrow:
                        break
                if other_arrow:
                    from src.core.model import Arrow
                    arrow = Arrow(
                        id=other_arrow.id,
                        source_box_id=None,
                        target_box_id=None,
                        type=other_arrow.type,
                        label=other_arrow.label,
                        icom_code=other_arrow.icom_code,
                        description=other_arrow.description
                    )
                    diagram.arrows.append(arrow)
                    self.log_message(f"Imported boundary arrow {arrow.id} into current diagram")
            
            if arrow:
                self.save_snapshot()
                
                # Check if this arrow is already assigned to this specific box (avoid duplicates)
                is_duplicate = False
                if arrow.type in [ArrowType.INPUT, ArrowType.CONTROL, ArrowType.MECHANISM]:
                    if arrow.target_box_id == box_id: is_duplicate = True
                elif arrow.type == ArrowType.OUTPUT:
                    if arrow.source_box_id == box_id: is_duplicate = True
                
                # Check for existing branches/joins to this box
                for a in diagram.arrows:
                    if a.branch_parent_id == arrow.id and a.target_box_id == box_id: is_duplicate = True
                    if a.join_target_id == arrow.id and a.source_box_id == box_id: is_duplicate = True
                
                if is_duplicate:
                    self.log_message(f"Arrow {arrow_id} is already assigned to box {box_id}")
                    return

                # Determine if we should update the original or create a branch/join
                # Get requested role
                requested_type = data.get('connection_type', arrow.type)
                
                # Default "already assigned" check (basic connectivity)
                is_connected = False
                if arrow.type in [ArrowType.INPUT, ArrowType.CONTROL, ArrowType.MECHANISM]:
                    if arrow.target_box_id is not None: is_connected = True
                elif arrow.type == ArrowType.OUTPUT:
                    if arrow.source_box_id is not None: is_connected = True

                # Decision Logic: Always prefer branching/joining for boundary arrows to support "Bus Rendering"
                
                # If the trunk is COMPLETELY unassigned and the user is assigning it as a different type,
                # update the trunk's type so it correctly moves to the appropriate boundary side (e.g. Input->Mech).
                if not is_connected and not any(a.branch_parent_id == arrow.id for a in diagram.arrows):
                    if arrow.type != requested_type:
                        arrow.type = requested_type
                        self.log_message(f"Updated boundary arrow {arrow.id} type to {requested_type.value}")

                # Check if the trunk itself is completely unattached to any box or branch
                has_existing_branches = any(a.branch_parent_id == arrow.id or a.join_target_id == arrow.id for a in diagram.arrows)
                is_unattached_trunk = (arrow.source_box_id is None and arrow.target_box_id is None and not has_existing_branches)

                if is_unattached_trunk:
                    # Directly attach the trunk itself to the box
                    if requested_type == ArrowType.OUTPUT:
                        arrow.source_box_id = box_id
                        arrow.target_box_id = None
                    else:
                        arrow.target_box_id = box_id
                        arrow.source_box_id = None
                    arrow.type = requested_type
                    self.log_message(f"Assigned boundary arrow {arrow.id} to box {box_id} ({requested_type.value})")
                
                # Case 1: Existing Output Trunk -> New Input/Control/Mech connection (Cross-type Branch)
                elif arrow.type == ArrowType.OUTPUT and requested_type != ArrowType.OUTPUT:
                    # Create a Branch from the Output trunk
                    new_id = f"{arrow.id}_{box_id}"
                    idx = 1
                    while any(a.id == new_id for a in diagram.arrows):
                        new_id = f"{arrow.id}_{box_id}_{idx}"
                        idx += 1
                    
                    from src.core.model import Arrow
                    new_arrow = Arrow(
                        id=new_id,
                        label=arrow.label, # Inherit label
                        type=requested_type, # Use requested type
                        source_box_id=None,
                        target_box_id=box_id,
                        branch_parent_id=arrow.id, # Branch from Output Arrow
                        join_target_id=None,
                        is_manual_connection=True,
                        icom_code=arrow.icom_code or arrow.id
                    )
                    diagram.arrows.append(new_arrow)
                    self.log_message(f"Created branch from Output {arrow.id} to {box_id} ({requested_type.value})")
                
                # Case 2: Input/Control/Mechanism Trunk -> Box connection (Direct Branch or Feedback Join)
                elif arrow.type in [ArrowType.INPUT, ArrowType.CONTROL, ArrowType.MECHANISM]:
                    new_id = f"{arrow.id}_{box_id}"
                    idx = 1
                    while any(a.id == new_id for a in diagram.arrows):
                        new_id = f"{arrow.id}_{box_id}_{idx}"
                        idx += 1
                        
                    from src.core.model import Arrow
                    if requested_type == ArrowType.OUTPUT:
                        # User wants a box OUTPUT to feed into this Boundary Input/Control/Mech trunk!
                        new_arrow = Arrow(
                            id=new_id,
                            label=arrow.label,
                            type=requested_type,
                            source_box_id=box_id,
                            target_box_id=None,
                            branch_parent_id=None,
                            join_target_id=arrow.id,
                            is_manual_connection=True,
                            icom_code=arrow.icom_code or arrow.id
                        )
                        diagram.arrows.append(new_arrow)
                        self.log_message(f"Created branch from {box_id} output to boundary trunk {arrow.id}")
                    else:
                        # Normal branch from the boundary trunk to the target box
                        new_arrow = Arrow(
                            id=new_id,
                            label=arrow.label,
                            type=requested_type,
                            source_box_id=None,
                            target_box_id=box_id,
                            branch_parent_id=arrow.id,
                            join_target_id=None,
                            is_manual_connection=True,
                            icom_code=arrow.icom_code or arrow.id
                        )
                        diagram.arrows.append(new_arrow)
                        self.log_message(f"Created branch from boundary trunk {arrow.id} to {box_id}")

                # Case 3: Output -> Output connection (Direct Join to boundary trunk)
                elif arrow.type == ArrowType.OUTPUT and requested_type == ArrowType.OUTPUT:
                    # Always create a Join for boundary outputs to maintain the "Bus" trunk
                    new_id = f"{arrow.id}_{box_id}"
                    idx = 1
                    while any(a.id == new_id for a in diagram.arrows):
                        new_id = f"{arrow.id}_{box_id}_{idx}"
                        idx += 1
                    
                    from src.core.model import Arrow
                    new_arrow = Arrow(
                        id=new_id,
                        label=arrow.label,
                        type=ArrowType.OUTPUT,
                        source_box_id=box_id,
                        target_box_id=None,
                        branch_parent_id=None,
                        join_target_id=arrow.id,
                        is_manual_connection=True,
                        icom_code=arrow.icom_code or arrow.id
                    )
                    diagram.arrows.append(new_arrow)
                    self.log_message(f"Created join from {box_id} to boundary {arrow.id}")
                
                # Clear all arrow segments to force full redistributive re-route
                for a in diagram.arrows:
                    a.segments = None
                
                self.refresh_current_diagram(diagram)

    def refresh_current_diagram(self, diagram):
        """Refreshes only the specified active diagram tab."""
        if not diagram: return
        node_id = diagram.node_number
        if node_id in self.open_diagrams:
            view = self.open_diagrams[node_id]
            scene = view.scene()
            was_frame = getattr(scene, 'frame_enabled', True)
            scene.load_diagram(diagram, project_model=self.project_model)
            # load_diagram() clears the scene, which drops the old frame item -
            # set_frame_visible() must run first to rebuild it, so the theming
            # pass right after has a frame to find and actually reaches it.
            scene.set_frame_visible(was_frame)
            self.apply_visual_settings_to_scene(scene)


    def refresh_all_diagrams(self):
        """Refreshes all open diagram tabs to reflect model changes."""
        for node_id, view in list(self.open_diagrams.items()):
            scene = view.scene()
            diag = self.project_model.get_diagram(node_id)
            if diag:
                # from src.core.layout import calculate_diagonal_layout
                # calculate_diagonal_layout(diag)
                
                # Capture current frame state
                was_frame = scene.frame_enabled

                scene.load_diagram(diag, project_model=self.project_model)
                # Restore the frame before theming the scene: load_diagram()
                # dropped the old frame item, and set_frame_visible() rebuilds
                # it as a fresh, untheme'd, black-on-white DiagramFrameItem -
                # the theming pass has to run after it exists, not before.
                scene.set_frame_visible(was_frame)
                self.apply_visual_settings_to_scene(scene)
        
        # Refresh any open management tabs. Undo and Open Project rebind
        # self.project_model to a different object, so hand each widget the
        # model that is current - otherwise it repopulates from the one it was
        # built with and shows the state that was just undone.
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if isinstance(widget, (ICOMsManagerWidget, FunctionsManagerWidget,
                                   FlowReportWidget)):
                widget.project_model = self.project_model
                widget.populate_data()

        # Also refresh node tree if it exists
        self.refresh_node_tree_if_open()

    def open_view_icoms_tab(self):
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if isinstance(widget, ICOMsManagerWidget):
                self.tabs.setCurrentIndex(index)
                widget.populate_data()
                return
                
        icoms_widget = ICOMsManagerWidget(self.project_model, main_window=self)
        idx = self.tabs.addTab(icoms_widget, "ICOMs Manager")
        self.tabs.setCurrentIndex(idx)
        self.log_message("Opened ICOMs Manager tab.")

    def open_view_functions_tab(self):
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if isinstance(widget, FunctionsManagerWidget):
                self.tabs.setCurrentIndex(index)
                widget.populate_data()
                return
                
        funcs_widget = FunctionsManagerWidget(self.project_model, main_window=self)
        idx = self.tabs.addTab(funcs_widget, "Functions Manager")
        self.tabs.setCurrentIndex(idx)
        self.log_message("Opened Functions Manager tab.")

    def refresh_node_tree_if_open(self):
        """Refreshes the Node Tree tab if it is currently open."""
        tree_idx = -1
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == "Node Tree":
                tree_idx = i
                break
        
        if tree_idx != -1:
            prev_active_idx = self.tabs.currentIndex()
            is_tree_active = (prev_active_idx == tree_idx)
            
            self.tabs.blockSignals(True)
            self.tabs.removeTab(tree_idx)
            self.generate_node_tree(fit_to_view=False)
            
            if not is_tree_active:
                new_idx = prev_active_idx
                if tree_idx < prev_active_idx:
                    new_idx -= 1
                self.tabs.setCurrentIndex(new_idx)
            self.tabs.blockSignals(False)

    def auto_route_current_diagram(self):
        """Automatically recalculates and re-routes all arrows in the active diagram."""
        if not self.current_scene or not self.current_scene.diagram_data:
            self.log_message("No active diagram to route")
            return

        diagram = self.current_scene.diagram_data
        # Re-routing discards every manual adjustment, so make it undoable
        self.save_snapshot()

        # Clear specific manual segment positions, junction data and label offsets to force a clean re-routing
        for arrow in diagram.arrows:
            arrow.segments = []
            arrow.junction_point = None
            arrow.branch_points = []
            arrow.join_points = []
            arrow.label_offset_x = 0.0
            arrow.label_offset_y = 0.0
            
        self.refresh_current_diagram(diagram)
        self.log_message("Automatically routed all arrows in current diagram")

    def toggle_theme(self):
        self.is_night = self.night_mode_action.isChecked()
        
        # Apply to all open tabs
        count = self.tabs.count()
        for i in range(count):
            view = self.tabs.widget(i)
            if not isinstance(view, QGraphicsView): continue
            scene = view.scene()
            
            if self.is_night:
                dark_bg = QColor(30, 30, 30)
                scene.setBackgroundBrush(QBrush(dark_bg))
                view.setStyleSheet("background-color: #1e1e1e; border: none;")
            else:
                scene.setBackgroundBrush(QBrush(Qt.GlobalColor.white))
                view.setStyleSheet("") # Reset
                
            self.apply_visual_settings_to_scene(scene)
            if hasattr(view, 'nav_overlay'):
                view.nav_overlay.update_theme(self.is_night)
            scene.update()  # Force immediate redraw
        
        # Set on the window, from where Qt cascades it to every descendant -
        # including tabs opened later, which is why nothing has to re-apply it.
        self.setStyleSheet(DARK_STYLESHEET if self.is_night else "")

        # The one thing a stylesheet cannot reach: marks coloured per item.
        self.apply_theme_to_report_tabs()

    def apply_theme_to_report_tabs(self):
        """Hand the current theme to tabs that colour their own cell contents."""
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if isinstance(widget, VerificationReportTab):
                widget.set_night_mode(self.is_night)



    def toggle_arrow_ids(self, checked):
        # Sync all open diagrams to the current panel state
        count = self.tabs.count()
        for i in range(count):
            view = self.tabs.widget(i)
            if not isinstance(view, QGraphicsView): continue
            scene = view.scene()
            if scene:
                self.apply_visual_settings_to_scene(scene, hide_arrows_override=checked)
        self.log_message(f"Arrow IDs {'hidden' if checked else 'shown'}")

    def toggle_box_ids(self, checked):
        # Sync all open diagrams to the current panel state
        count = self.tabs.count()
        for i in range(count):
            view = self.tabs.widget(i)
            if not isinstance(view, QGraphicsView): continue
            scene = view.scene()
            if scene:
                self.apply_visual_settings_to_scene(scene, hide_boxes_override=checked)
        # Also refresh node tree and index if open as they are static-ish
        self.refresh_node_tree_if_open()
        self.log_message(f"Function IDs {'hidden' if checked else 'shown'}")

    def show_about_dialog(self):
        from src.gui.dialogs import AboutDialog
        dialog = AboutDialog(parent=self)
        dialog.exec()

    def export_diagram(self):
        if not self.current_scene: return
        from PyQt6.QtWidgets import QFileDialog
        
        filename, selected_filter = QFileDialog.getSaveFileName(
            self, "Export Diagram", "", "PNG (*.png);;JPEG (*.jpg *.jpeg);;SVG (*.svg);;PDF (*.pdf)"
        )
        
        if not filename:
            return
            
        _, ext = os.path.splitext(filename)
        ext = ext.lower()
        
        # If no extension in filename, append from filter
        if not ext:
             if "PNG" in selected_filter: ext = ".png"
             elif "JPEG" in selected_filter: ext = ".jpg"
             elif "SVG" in selected_filter: ext = ".svg"
             elif "PDF" in selected_filter: ext = ".pdf"
             filename += ext

        # Render the scene to the file
        rect = self.current_scene.itemsBoundingRect()
        # Add some margin
        rect.adjust(-50, -50, 50, 50)
        
        if ext == '.svg':
            from PyQt6.QtSvg import QSvgGenerator
            generator = QSvgGenerator()
            generator.setFileName(filename)
            generator.setSize(rect.size().toSize())
            generator.setViewBox(rect)
            generator.setTitle("IDEF0 Diagram")
            
            painter = QPainter()
            painter.begin(generator)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self.current_scene.render(painter, target=QRectF(generator.viewBox()), source=rect)
            painter.end()
            
        elif ext == '.pdf':
            from PyQt6.QtGui import QPdfWriter, QPageSize
            
            writer = QPdfWriter(filename)
            writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            writer.setResolution(300) # High quality
            
            painter = QPainter()
            painter.begin(writer)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            # Map scene rect to PDF page rect maintaining aspect ratio
            page_rect = painter.viewport()
            scene_to_page_ratio = min(page_rect.width() / rect.width(), page_rect.height() / rect.height())
            
            target_w = rect.width() * scene_to_page_ratio
            target_h = rect.height() * scene_to_page_ratio
            
            target_rect = QRectF((page_rect.width() - target_w)/2, (page_rect.height() - target_h)/2, target_w, target_h)
            
            self.current_scene.render(painter, target=target_rect, source=rect)
            painter.end()
            
        elif ext in ['.jpg', '.jpeg']:
            image = QImage(rect.size().toSize(), QImage.Format.Format_RGB32)
            image.fill(Qt.GlobalColor.white)
            
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self.current_scene.render(painter, target=QRectF(image.rect()), source=rect)
            painter.end()
            image.save(filename, "JPG", 95) # 95 quality
            
        else: # PNG
            image = QImage(rect.size().toSize(), QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.white) # Ensure background is clean if not transparent
            
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self.current_scene.render(painter, target=QRectF(image.rect()), source=rect)
            painter.end()
            image.save(filename, "PNG")

    def set_tree_routing(self, style):
        self.tree_routing_style = style
        # Refresh any open Node Tree tab
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == "Node Tree":
                # Re-generate it
                current_idx = self.tabs.currentIndex()
                self.tabs.removeTab(i)
                self.generate_node_tree(fit_to_view=False)
                self.tabs.setCurrentIndex(current_idx)
                break

    def generate_node_tree(self, fit_to_view=True):
        tree_data = self.project_model.get_node_tree()
        if not tree_data: return
        
        scene = QGraphicsScene()
        scene.setBackgroundBrush(Qt.GlobalColor.white)
        
        # Mapping: V-Slider for Width, H-Slider for Depth (per user requirement)
        font_family = self.properties_panel.global_font_combo.currentFont().family()
        font_size = self.properties_panel.global_font_size_spin.value()
        font_bold = self.properties_panel.global_bold_check.isChecked()
        font_italic = self.properties_panel.global_italic_check.isChecked()
        
        hide_boxes = self.properties_panel.hide_boxes_check.isChecked()
        
        node_width = 80
        h_spacing = self.properties_panel.v_space_spin.value() * 0.3
        v_spacing = self.properties_panel.h_space_spin.value() * 0.5
        
        arrow_color = Qt.GlobalColor.black # standard for reports
        # Better: get from current_box_color logic or just standard black for tree
        arrow_pen = QPen(arrow_color)
        arrow_pen.setWidth(2) # Default thickness for tree
        arrow_pen.setStyle(Qt.PenStyle.SolidLine)
        
        def calc_width(node):
            if not node["children"]:
                return node_width
            total = sum(calc_width(c) for c in node["children"])
            total += h_spacing * (len(node["children"]) - 1)
            return max(node_width, total)
            
        def draw_node(node, x_center, y_top):
            if hide_boxes:
                name_parts = node['text'].replace(node['id'], "").strip().split()
                text_str = "\n".join(name_parts)
            else:
                name_parts = node['text'].replace(node['id'], "").strip().split()
                text_str = f"[{node['id']}]\n" + "\n".join(name_parts)
            
            text = QGraphicsTextItem()
            # Use current Font settings
            style_str = f"text-align: center; color: black; font-family: {font_family}; font-size: {font_size}pt;"
            if font_bold: style_str += " font-weight: bold;"
            if font_italic: style_str += " font-style: italic;"
            html_text = text_str.replace('\n', '<br/>')
            text.setHtml(f"<div style='{style_str}'>{html_text}</div>")
            
            # Center the text
            tr = text.boundingRect()
            text.setPos(x_center - tr.width()/2, y_top)
            scene.addItem(text)
            
            bh = tr.height()
            
            if node["children"]:
                total_children_width = calc_width(node)
                current_x = x_center - total_children_width / 2
                
                style = self.tree_routing_style
                tick_len = 25
                mid_y = y_top + bh + tick_len
                child_y = y_top + bh + v_spacing
                
                # Draw Squared/Fork specific helper lines
                if style == 'squared':
                    # Vertical tick down from parent
                    scene.addLine(x_center, y_top + bh, x_center, mid_y, arrow_pen)
                    
                    # Calculate extreme points for the horizontal part
                    first_child_x = current_x + calc_width(node["children"][0]) / 2
                    last_child_x = current_x
                    temp_x = current_x
                    for c in node["children"]:
                        last_child_x = temp_x + calc_width(c) / 2
                        temp_x += calc_width(c) + h_spacing
                    
                    if len(node["children"]) > 1:
                        scene.addLine(first_child_x, mid_y, last_child_x, mid_y, arrow_pen)

                for child in node["children"]:
                    child_subtree_width = calc_width(child)
                    child_x_center = current_x + child_subtree_width / 2
                    
                    if style == 'straight':
                        # Direct diagonal line
                        scene.addLine(x_center, y_top + bh, child_x_center, child_y, arrow_pen)
                    elif style == 'squared':
                        # Vertical line from bridge to child
                        scene.addLine(child_x_center, mid_y, child_x_center, child_y, arrow_pen)
                    elif style == 'rounded':
                        # Squared path with rounded corners
                        radius = 20
                        path = QPainterPath()
                        
                        # From mid point of parent bottom tick to bridge mid_y
                        # We start from parent bottom + tick? 
                        # Actually use the bridge mid_y logic
                        
                        # Path from parent to child via mid_y
                        # 1. Start at parent bottom (x_center, y_top + bh)
                        path.moveTo(x_center, y_top + bh)
                        
                        # Only round if not a straight vertical drop
                        if abs(x_center - child_x_center) < 1:
                            path.lineTo(child_x_center, child_y)
                        else:
                            # Vertical to corner
                            corner1_y = mid_y - radius
                            path.lineTo(x_center, corner1_y)
                            
                            # Curve to horizontal
                            path.quadTo(x_center, mid_y, x_center + (radius if child_x_center > x_center else -radius), mid_y)
                            
                            # Horizontal to second corner
                            corner2_x = child_x_center - (radius if child_x_center > x_center else -radius)
                            path.lineTo(corner2_x, mid_y)
                            
                            # Curve to vertical
                            path.quadTo(child_x_center, mid_y, child_x_center, mid_y + radius)
                            
                            # Vertical to child
                            path.lineTo(child_x_center, child_y)
                            
                        scene.addPath(path, arrow_pen)
                    
                    draw_node(child, child_x_center, child_y)
                    current_x += child_subtree_width + h_spacing

        if tree_data:
            draw_node(tree_data[0], 0, 0)
            
        view = ZoomableView(scene)
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        index = self.tabs.addTab(view, "Node Tree")
        self.tabs.setCurrentIndex(index)
        if fit_to_view:
            view.fitInView(scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def generate_node_index(self):
        tree_data = self.project_model.get_node_tree()
        if not tree_data: return
        
        tree_widget = QTreeWidget()
        tree_widget.setHeaderLabels(["IDEF0 Node Index"])
        tree_widget.header().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        
        def add_items(parent_item, data_list):
            for data in data_list:
                if not data: continue
                item = QTreeWidgetItem(parent_item)
                # Bracketized text: [A1] Plan Manufacturing
                hide_boxes = self.properties_panel.hide_boxes_check.isChecked()
                if hide_boxes:
                    bracket_text = data['text'].replace(data['id'], "").strip()
                else:
                    bracket_text = f"[{data['id']}] " + data['text'].replace(data['id'], "").strip()
                item.setText(0, bracket_text)
                item.setData(0, Qt.ItemDataRole.UserRole, data["id"])
                if data["children"]:
                    add_items(item, data["children"])
                item.setExpanded(True)

        add_items(tree_widget, tree_data)
        index = self.tabs.addTab(tree_widget, "Node Index")
        self.tabs.setCurrentIndex(index)

    def generate_flow_index(self, flow_type):
        """Report > Flow Reports: which diagrams carry arrows of one ICOM role.

        Re-populated rather than rebuilt when the tab is already open, so the
        report answers for the model as it stands now - the same reason the
        verification report is re-run every time it is asked for.
        """
        title = f"{flow_type} Index"
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if isinstance(widget, FlowReportWidget) and widget.flow_type == flow_type:
                widget.project_model = self.project_model
                widget.bracket_nodes = not self.properties_panel.hide_boxes_check.isChecked()
                widget.populate_data()
                self.tabs.setCurrentIndex(index)
                return

        report = FlowReportWidget(
            self.project_model, flow_type, main_window=self,
            bracket_nodes=not self.properties_panel.hide_boxes_check.isChecked())
        index = self.tabs.addTab(report, title)
        self.tabs.setCurrentIndex(index)
        self.log_message(f"Opened {title}")

    def update_icom_callout_style(self, style):
        self.save_snapshot()
        selected = self.current_scene.selectedItems() if self.current_scene else []
        did_update = False
        
        # Apply to selection
        for item in selected:
            if isinstance(item, ArrowItem):
                item.set_icom_callout_style(style)
                did_update = True
            elif isinstance(item, ArrowLabelItem):
                item.arrow_item.set_icom_callout_style(style)
                did_update = True
        
        # If no selection, apply to the entire model
        if not did_update:
            for diag in self.project_model.diagrams:
                for arrow in diag.arrows:
                    arrow.icom_callout_style = style
            self.refresh_all_diagrams()
        elif self.current_scene:
            self.current_scene.update()

    def toggle_frame(self, checked):
        self.show_border_frame = checked
        # Update all open diagrams
        # Iterate all tabs
        for i in range(self.tabs.count()):
            view = self.tabs.widget(i)
            # Check if it is a view
            if hasattr(view, 'scene'):
                scene = view.scene()
                if hasattr(scene, 'set_frame_visible'):
                    scene.set_frame_visible(checked)
                    # A frame just switched on is a brand-new DiagramFrameItem,
                    # constructed with no theme of its own - it draws its border
                    # and field labels in black until told otherwise.
                    self.apply_visual_settings_to_scene(scene)

        # Ensure frame is centered in the viewer
        self.center_view()

def main():
    try:
        app = QApplication(sys.argv)
        # Use Fusion style as requested
        from PyQt6.QtWidgets import QStyleFactory
        if 'Fusion' in QStyleFactory.keys():
            app.setStyle('Fusion')
        
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
