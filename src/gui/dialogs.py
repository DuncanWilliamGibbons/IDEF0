import os
import re

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                             QLineEdit, QDialogButtonBox, QMessageBox, QCheckBox)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt
from src import APP_NAME, __version__, __date__
from src.core.model import Diagram, ArrowType

# src/gui/dialogs.py -> src/gui -> src -> project root
_root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class AddActivityBoxDialog(QDialog):
    def __init__(self, suggested_id="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Function Box")
        
        layout = QVBoxLayout(self)
        
        # ID
        layout.addWidget(QLabel("ID (e.g., A1):"))
        self.id_input = QLineEdit()
        self.id_input.setText(suggested_id)
        layout.addWidget(self.id_input)
        
        # Name
        layout.addWidget(QLabel("Name:"))
        self.name_input = QLineEdit()
        layout.addWidget(self.name_input)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
    def validate_and_accept(self):
        if not self.id_input.text().strip():
            QMessageBox.warning(self, "Invalid Input", "ID is required.")
            return
        if not self.name_input.text().strip():
            QMessageBox.warning(self, "Invalid Input", "Name is required.")
            return
        self.accept()
        
    def get_data(self):
        return {
            "id": self.id_input.text().strip(),
            "name": self.name_input.text().strip()
        }

class AddArrowDialog(QDialog):
    def __init__(self, diagram: Diagram, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Arrow")
        self.diagram = diagram
        
        layout = QVBoxLayout(self)
        
        # ID
        layout.addWidget(QLabel("Arrow ID:"))
        self.id_input = QLineEdit()
        # Suggest a default ID
        self.id_input.setText(f"Arr_{len(diagram.arrows) + 1}")
        layout.addWidget(self.id_input)

        # Label
        layout.addWidget(QLabel("Label:"))
        self.label_input = QLineEdit()
        layout.addWidget(self.label_input)

        # Source
        layout.addWidget(QLabel("Source Box:"))
        self.source_combo = QComboBox()
        self.source_combo.addItem("(Boundary)", None)
        for box in diagram.boxes:
            self.source_combo.addItem(f"[{box.id}] {box.name}", box.id)
        layout.addWidget(self.source_combo)
        
        # Branch from another arrow
        layout.addWidget(QLabel("OR Branch from Arrow:"))
        self.branch_combo = QComboBox()
        self.branch_combo.addItem("(None)", None)
        for arrow in diagram.arrows:
            self.branch_combo.addItem(f"[{arrow.id}] {arrow.label}", arrow.id)
        layout.addWidget(self.branch_combo)
        
        # Target
        layout.addWidget(QLabel("Target Box:"))
        self.target_combo = QComboBox()
        self.target_combo.addItem("(Boundary)", None)
        for box in diagram.boxes:
            self.target_combo.addItem(f"[{box.id}] {box.name}", box.id)
        layout.addWidget(self.target_combo)

        # Join into another arrow
        layout.addWidget(QLabel("OR Join into Arrow:"))
        self.join_combo = QComboBox()
        self.join_combo.addItem("(None)", None)
        for arrow in diagram.arrows:
            self.join_combo.addItem(f"[{arrow.id}] {arrow.label}", arrow.id)
        layout.addWidget(self.join_combo)
        
        # Type
        layout.addWidget(QLabel("Arrow Type:"))
        self.type_combo = QComboBox()
        for t in ArrowType:
            self.type_combo.addItem(t.value, t)
        layout.addWidget(self.type_combo)
        
        # Tunneling
        tunnel_layout = QHBoxLayout()
        self.tunnel_source_cb = QCheckBox("Tunnel Source (Tail)")
        self.tunnel_target_cb = QCheckBox("Tunnel Target (Head)")
        tunnel_layout.addWidget(self.tunnel_source_cb)
        tunnel_layout.addWidget(self.tunnel_target_cb)
        layout.addLayout(tunnel_layout)
        
        # Connect combo boxes to dynamic suggested ID updater
        self.branch_combo.currentIndexChanged.connect(self.update_suggested_id)
        self.join_combo.currentIndexChanged.connect(self.update_suggested_id)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
    def update_suggested_id(self):
        branch_id = self.branch_combo.currentData()
        join_id = self.join_combo.currentData()
        
        parent_id = branch_id or join_id
        if parent_id:
            prefix = f"{parent_id}."
            existing_indices = []
            for a in self.diagram.arrows:
                if a.id.startswith(prefix):
                    suffix = a.id[len(prefix):]
                    m = re.match(r'^(\d+)', suffix)
                    if m:
                        existing_indices.append(int(m.group(1)))
            next_index = max(existing_indices) + 1 if existing_indices else 1
            self.id_input.setText(f"{prefix}{next_index}")
        else:
            self.id_input.setText(f"Arr_{len(self.diagram.arrows) + 1}")
        
    def validate_and_accept(self):
        source_id = self.source_combo.currentData()
        target_id = self.target_combo.currentData()
        branch_id = self.branch_combo.currentData()
        join_id = self.join_combo.currentData()
        arrow_id = self.id_input.text().strip()

        if not arrow_id:
            QMessageBox.warning(self, "Invalid Arrow", "Arrow ID is required.")
            return

        # Check for duplicate ID
        if any(a.id == arrow_id for a in self.diagram.arrows):
            QMessageBox.warning(self, "Invalid Arrow", f"Arrow with ID '{arrow_id}' already exists.")
            return

        if source_id is None and branch_id is None and target_id is None and join_id is None:
             QMessageBox.warning(self, "Invalid Arrow", "Arrow must have at least one connection.")
             return
             
        self.accept()
        
    def get_data(self):
        return {
            "id": self.id_input.text().strip(),
            "source_id": self.source_combo.currentData(),
            "target_id": self.target_combo.currentData(),
            "branch_parent_id": self.branch_combo.currentData(),
            "join_target_id": self.join_combo.currentData(),
            "arrow_type": self.type_combo.currentData(),
            "label": self.label_input.text(),
            "tunnel_source": self.tunnel_source_cb.isChecked(),
            "tunnel_target": self.tunnel_target_cb.isChecked()
        }
class AssignArrowDialog(QDialog):
    def __init__(self, diagram: Diagram, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Assign Arrow")
        self.diagram = diagram
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("Select an Arrow to Assign:"))
        self.arrow_combo = QComboBox()
        
        # Populate with all arrows in the diagram to preserve original matching logic
        self.boundary_arrows = list(diagram.arrows)
        
        # Add project-wide decomposed descendants of current boundary arrows
        if parent and hasattr(parent, 'project_model') and parent.project_model:
            
            def get_arrow_signatures(arrow):
                sigs = []
                # Match standard ICOM codes like D.4.6, P.3.1, D.4.6.3, M1, I1, C1, O1
                for text in [arrow.icom_code, arrow.id, arrow.label]:
                    if not text:
                        continue
                    # Match pattern like D.4.6.3 or D.4.6 or P.3.1 or D.4 or M1
                    matches = re.findall(r'[A-Za-z]\.?(?:\d+\.)*\d+|[A-Za-z]\d+', str(text))
                    for m in matches:
                        sigs.append(m.lower().strip())
                    # Also strip brackets/punctuation
                    cleaned = re.sub(r'[\[\]\(\)]', '', str(text)).strip()
                    m_start = re.match(r'^([a-zA-Z0-9\.\-_]+)', cleaned)
                    if m_start:
                        sigs.append(m_start.group(1).lower().strip())
                return list(set(sigs))

            def is_descendant(child, parent_arrow):
                child_sigs = get_arrow_signatures(child)
                parent_sigs = get_arrow_signatures(parent_arrow)
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

            current_boundary = [a for a in diagram.arrows if a.source_box_id is None or a.target_box_id is None]
            existing_ids = {a.id for a in diagram.arrows}
            
            # Also include parent box arrows from parent diagram
            parent_box, parent_diag = parent.project_model.get_parent_box_and_diagram(diagram.node_number)
            if parent_box and parent_diag:
                parent_arrows = [a for a in parent_diag.arrows if a.source_box_id == parent_box.id or a.target_box_id == parent_box.id]
                current_boundary.extend(parent_arrows)
            
            for other_diag in parent.project_model.diagrams:
                if other_diag.node_number == diagram.node_number:
                    continue
                for other_arrow in other_diag.arrows:
                    if other_arrow.id in existing_ids:
                        continue
                    
                    # Check if this other arrow is a descendant of any current boundary or parent arrow
                    for ba in current_boundary:
                        if is_descendant(other_arrow, ba) or other_arrow.id == ba.id or (other_arrow.icom_code and other_arrow.icom_code == ba.icom_code):
                            self.boundary_arrows.append(other_arrow)
                            existing_ids.add(other_arrow.id)
                            break
                    
        # Group and deduplicate by user-visible display ID to avoid duplicate entries in the list
        def get_display_id(a):
            if a.icom_code:
                return re.sub(r'_[A-Za-z]\d+.*$', '', a.icom_code.strip())
            return re.sub(r'_[A-Za-z]\d+.*$', '', a.id.strip())
            
        grouped_arrows = {}
        for arrow in self.boundary_arrows:
            disp_id = get_display_id(arrow)
            # Group by unique (display_id, label) pair so distinct decomposed signals are preserved
            key = (disp_id, (arrow.label or "").strip())
            if key not in grouped_arrows:
                grouped_arrows[key] = []
            grouped_arrows[key].append(arrow)
            
        # Select the best representative arrow for each display_id/label pair
        repr_arrows = []
        for key in sorted(grouped_arrows.keys(), key=lambda k: k[0]):
            arrows_group = grouped_arrows[key]
            # Prefer trunks (no parent/target branch/join)
            trunks = [a for a in arrows_group if a.branch_parent_id is None and a.join_target_id is None]
            if trunks:
                repr_arrows.append(trunks[0])
            else:
                repr_arrows.append(arrows_group[0])

        for arrow in repr_arrows:
            side = arrow.type.value
            display_id = get_display_id(arrow)
            desc = f"[{display_id}] {arrow.label} ({side})"
            if (arrow.type != ArrowType.OUTPUT and arrow.target_box_id) or (arrow.type == ArrowType.OUTPUT and arrow.source_box_id):
                desc += " - Add Branch"
            if arrow not in diagram.arrows:
                desc += " (Decomposed)"
            self.arrow_combo.addItem(desc, arrow.id)
        
        layout.addWidget(self.arrow_combo)
        
        layout.addWidget(QLabel("Assign to Function Box:"))
        self.box_combo = QComboBox()
        for box in diagram.boxes:
            self.box_combo.addItem(f"[{box.id}] {box.name}", box.id)
        layout.addWidget(self.box_combo)
        
        layout.addWidget(QLabel("Connection Type (Role at Box):"))
        self.type_combo = QComboBox()
        # Will be populated when arrow is selected
        self.type_combo.addItems(["Input", "Control", "Output", "Mechanism"])
        layout.addWidget(self.type_combo)
        
        # Connect signal to update type combo based on arrow selection
        self.arrow_combo.currentIndexChanged.connect(self.update_type_options)
        self.update_type_options()
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
    def update_type_options(self):
        arrow_id = self.arrow_combo.currentData()
        if not arrow_id: return
        
        # Find arrow
        arrow = next((a for a in self.diagram.arrows if a.id == arrow_id), None)
        if not arrow: return
        
        # Set default type to match arrow type by default
        current_type = arrow.type.value
        
        # Determine available/logical options?
        # A boundary arrow can serve any role if branched appropriately.
        # But usually output->input is the main cross-connection.
        
        # Set combo to current arrow type
        index = self.type_combo.findText(current_type)
        if index >= 0:
            self.type_combo.setCurrentIndex(index)

    def get_data(self):
        from src.core.model import ArrowType
        type_str = self.type_combo.currentText()
        if type_str == "Input": atype = ArrowType.INPUT
        elif type_str == "Output": atype = ArrowType.OUTPUT
        elif type_str == "Control": atype = ArrowType.CONTROL
        else: atype = ArrowType.MECHANISM # Mechanism
        
        return {
            "arrow_id": self.arrow_combo.currentData(),
            "box_id": self.box_combo.currentData(),
            "connection_type": atype
        }

class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setFixedWidth(420)

        layout = QVBoxLayout(self)

        logo_path = os.path.join(_root_dir, "figures", "logo_full.png")
        if os.path.exists(logo_path):
            logo_label = QLabel()
            pixmap = QPixmap(logo_path).scaledToWidth(360, Qt.TransformationMode.SmoothTransformation)
            logo_label.setPixmap(pixmap)
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(logo_label)

        description = QLabel(
            "A desktop editor for IDEF0 function models that draws, checks and "
            "exports them to the conformance rules of ISO/IEC/IEEE 31320-1:2012."
        )
        description.setWordWrap(True)
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(description)

        link_label = QLabel(
            '<a href="https://github.com/DuncanWilliamGibbons/IDEF0">'
            'github.com/DuncanWilliamGibbons/IDEF0</a>'
        )
        link_label.setOpenExternalLinks(True)
        link_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(link_label)

        info_label = QLabel(
            f"Author: Duncan W. Gibbons, Ph.D.\nVersion {__version__} — {__date__}"
        )
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
