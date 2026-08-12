from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QSpinBox, QGroupBox, 
                             QPushButton, QColorDialog, QFontComboBox, QCheckBox, QComboBox, QLineEdit, QScrollArea, QPlainTextEdit, QSizePolicy)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor, QFont

class ItemPanel(QWidget):
    # Signals for Selection Editing
    selection_id_changed = pyqtSignal(str)
    selection_auto_id_changed = pyqtSignal(str)
    selection_name_changed = pyqtSignal(str)
    description_changed = pyqtSignal(str)
    
    # Appearance Signals
    box_color_changed = pyqtSignal(QColor)
    font_family_changed = pyqtSignal(str)
    font_size_changed = pyqtSignal(int)
    icom_font_size_changed = pyqtSignal(int)
    font_bold_changed = pyqtSignal(bool)
    font_italic_changed = pyqtSignal(bool)
    icom_callout_style_changed = pyqtSignal(str) 
    
    # Arrow Settings Signals
    arrow_color_changed = pyqtSignal(QColor)
    label_color_changed = pyqtSignal(QColor)
    arrow_thickness_changed = pyqtSignal(int)
    arrow_style_changed = pyqtSignal(str)
    hide_label_toggled = pyqtSignal(bool)
    tunnel_source_toggled = pyqtSignal(bool)
    tunnel_target_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        
        content_widget = QWidget()
        self.layout = QVBoxLayout(content_widget)
        
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)
        
        self.setFixedWidth(270)
        
        self.setStyleSheet("""
            QPushButton, QSpinBox, QComboBox, QLineEdit {
                min-height: 25px;
            }
        """)
        
        # --- SELECTION EDITING SECTION ---
        self.selection_group = QGroupBox("Edit Details")
        self.selection_layout = QVBoxLayout()
        self.selection_group.setLayout(self.selection_layout)
        
        self.selection_layout.addWidget(QLabel("Assigned ID:"))
        self.selection_id_edit = QLineEdit()
        self.selection_id_edit.setToolTip("The ID you assign, shown at the front of the label (e.g. P.2)")
        self.selection_id_edit.editingFinished.connect(lambda: self.on_id_edited(self.selection_id_edit.text()))
        self.selection_layout.addWidget(self.selection_id_edit)

        # Both ICOM ids are editable here whatever View > ICOM IDs is showing,
        # so a setting that hides one never puts it out of reach.
        self.auto_id_label = QLabel("Standard ICOM Code:")
        self.selection_layout.addWidget(self.auto_id_label)
        self.selection_auto_id_edit = QLineEdit()
        self.selection_auto_id_edit.setPlaceholderText("Auto (e.g. O1)")
        self.selection_auto_id_edit.setToolTip(
            "The positional code from ISO/IEC/IEEE 31320-1, shown at the back of "
            "the label. Clear it to let the diagram regenerate it.")
        self.selection_auto_id_edit.editingFinished.connect(
            lambda: self.selection_auto_id_changed.emit(self.selection_auto_id_edit.text()))
        self.selection_layout.addWidget(self.selection_auto_id_edit)

        self.selection_layout.addWidget(QLabel("Name / Label:"))
        self.selection_name_edit = QLineEdit()
        self.selection_name_edit.editingFinished.connect(lambda: self.on_name_edited(self.selection_name_edit.text()))
        self.selection_layout.addWidget(self.selection_name_edit)
        
        self.hide_label_check = QCheckBox("Hide Label on Diagram")
        self.hide_label_check.toggled.connect(self.hide_label_toggled.emit)
        self.selection_layout.addWidget(self.hide_label_check)

        # Tunnelling is a modelling decision that gets revisited as the
        # decomposition grows, so it is editable here and not only on the
        # dialog that created the arrow.
        self.tunnel_tail_check = QCheckBox("Tunnel Tail (Source)")
        self.tunnel_tail_check.setToolTip(
            "Bracket the tail: the arrow enters this diagram without appearing "
            "on the parent box, or leaves a box without appearing in its "
            "decomposition (ISO/IEC/IEEE 31320-1 clause 9.4)")
        self.tunnel_tail_check.toggled.connect(self.tunnel_source_toggled.emit)
        self.selection_layout.addWidget(self.tunnel_tail_check)

        self.tunnel_head_check = QCheckBox("Tunnel Head (Target)")
        self.tunnel_head_check.setToolTip(
            "Bracket the head: the arrow enters a box without appearing in its "
            "decomposition, or leaves this diagram without appearing on the "
            "parent box (ISO/IEC/IEEE 31320-1 clause 9.4)")
        self.tunnel_head_check.toggled.connect(self.tunnel_target_toggled.emit)
        self.selection_layout.addWidget(self.tunnel_head_check)

        self.selection_layout.addWidget(QLabel("Description:"))
        self.description_edit = QPlainTextEdit()
        self.description_edit.textChanged.connect(self.on_description_edited)
        self.description_edit.setMaximumHeight(80)
        self.description_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.selection_layout.addWidget(self.description_edit)
        
        self.selection_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.layout.addWidget(self.selection_group)

        # --- APPEARANCE SECTION ---
        self.appearance_group = QGroupBox("Appearance")
        self.appearance_layout = QVBoxLayout()
        self.appearance_group.setLayout(self.appearance_layout)
        
        self.box_color_btn = QPushButton("Function Box Color")
        self.box_color_btn.clicked.connect(self.open_box_color_dialog)
        self.appearance_layout.addWidget(self.box_color_btn)
        
        self.arrow_color_btn = QPushButton("Arrow Line Color")
        self.arrow_color_btn.clicked.connect(self.open_arrow_color_dialog)
        self.appearance_layout.addWidget(self.arrow_color_btn)
        
        self.label_color_btn = QPushButton("Label Color")
        self.label_color_btn.clicked.connect(self.open_label_color_dialog)
        self.appearance_layout.addWidget(self.label_color_btn)
        
        self.style_label = QLabel("Line Style:")
        self.appearance_layout.addWidget(self.style_label)
        self.style_combo = QComboBox()
        self.style_combo.addItems(["Solid", "Dashed", "Dotted", "DotDash"])
        self.style_combo.currentTextChanged.connect(self.arrow_style_changed.emit)
        self.appearance_layout.addWidget(self.style_combo)
        
        self.thickness_label = QLabel("Line Thickness:")
        self.appearance_layout.addWidget(self.thickness_label)
        self.thickness_spin = QSpinBox()
        self.thickness_spin.setRange(1, 10)
        self.thickness_spin.setValue(2)
        self.thickness_spin.valueChanged.connect(self.arrow_thickness_changed.emit)
        self.appearance_layout.addWidget(self.thickness_spin)
        
        self.appearance_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.layout.addWidget(self.appearance_group)

        # --- FONT SECTION ---
        self.font_group = QGroupBox("Font Settings")
        self.font_layout = QVBoxLayout()
        self.font_group.setLayout(self.font_layout)
        
        self.font_layout.addWidget(QLabel("Font Family:"))
        self.font_combo = QFontComboBox()
        self.font_combo.currentFontChanged.connect(lambda f: self.font_family_changed.emit(f.family()))
        self.font_layout.addWidget(self.font_combo)
        
        self.font_size_label = QLabel("Font Size:")
        self.font_layout.addWidget(self.font_size_label)
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(6, 48)
        self.font_size_spin.setValue(10)
        self.font_size_spin.valueChanged.connect(self.handle_font_size_changed)
        self.font_layout.addWidget(self.font_size_spin)

        self.icom_style_label = QLabel("ICOM Callout Style:")
        self.font_layout.addWidget(self.icom_style_label)
        self.icom_style_combo = QComboBox()
        self.icom_style_combo.addItems(["Jagged", "Straight", "Rounded"])
        self.icom_style_combo.currentTextChanged.connect(self.icom_callout_style_changed.emit)
        self.font_layout.addWidget(self.icom_style_combo)
        
        self.bold_check = QCheckBox("Bold")
        self.bold_check.toggled.connect(self.font_bold_changed.emit)
        self.font_layout.addWidget(self.bold_check)
        
        self.italic_check = QCheckBox("Italic")
        self.italic_check.toggled.connect(self.font_italic_changed.emit)
        self.font_layout.addWidget(self.italic_check)
        
        self.font_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.layout.addWidget(self.font_group)
        self.layout.addStretch()
        
        self.placeholder_label = QLabel("Select an element to edit.")
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder_label.setStyleSheet("color: #71717A; font-style: italic;")
        self.layout.addWidget(self.placeholder_label)
        
        self.current_item_type = None
        self.clear_panel()

    def clear_panel(self):
        self.current_item_type = None
        self.selection_group.setVisible(False)
        self.appearance_group.setVisible(False)
        self.font_group.setVisible(False)
        self.placeholder_label.setVisible(True)

    def on_id_edited(self, text):
        self.selection_id_changed.emit(text)

    def on_name_edited(self, text):
        self.selection_name_changed.emit(text)
        
    def on_description_edited(self):
        self.description_changed.emit(self.description_edit.toPlainText())
        
    def handle_font_size_changed(self, size):
        if self.current_item_type == "box":
            self.font_size_changed.emit(size)
        elif self.current_item_type in ("arrow", "arrow_label"):
            # Clicking an ICOM label selects an ArrowLabelItem, whose type is
            # "arrow_label" - its font size is still the arrow's label font size.
            self.icom_font_size_changed.emit(size)

    def update_panel(self, item_type, item_id, item_name, description, font_family, font_size, is_bold, is_italic, extra_props=None):
        self.current_item_type = item_type
        
        self.selection_group.setVisible(True)
        self.appearance_group.setVisible(True)
        self.font_group.setVisible(item_type != "arrow")
        self.placeholder_label.setVisible(False)
        
        self.selection_id_edit.blockSignals(True)
        self.selection_auto_id_edit.blockSignals(True)
        self.selection_name_edit.blockSignals(True)
        self.hide_label_check.blockSignals(True)
        self.tunnel_tail_check.blockSignals(True)
        self.tunnel_head_check.blockSignals(True)
        self.description_edit.blockSignals(True)
        self.font_combo.blockSignals(True)
        self.font_size_spin.blockSignals(True)
        self.bold_check.blockSignals(True)
        self.italic_check.blockSignals(True)

        self.selection_id_edit.setText(item_id)
        self.selection_name_edit.setText(item_name)
        self.description_edit.setPlainText(description)
        if font_family:
            self.font_combo.setCurrentFont(QFont(font_family))
        self.font_size_spin.setValue(font_size)
        self.bold_check.setChecked(is_bold)
        self.italic_check.setChecked(is_italic)

        is_arrow_or_label = item_type in ["arrow", "arrow_label"]
        self.hide_label_check.setVisible(is_arrow_or_label)
        self.tunnel_tail_check.setVisible(is_arrow_or_label)
        self.tunnel_head_check.setVisible(is_arrow_or_label)
        self.auto_id_label.setVisible(is_arrow_or_label)
        self.selection_auto_id_edit.setVisible(is_arrow_or_label)
        self.selection_auto_id_edit.setText((extra_props or {}).get("auto_id", ""))
        if extra_props:
            self.hide_label_check.setChecked(extra_props.get("hide_label", False))
            self.tunnel_tail_check.setChecked(extra_props.get("tunnel_source", False))
            self.tunnel_head_check.setChecked(extra_props.get("tunnel_target", False))

        if item_type == "box":
            self.box_color_btn.setVisible(True)
            self.arrow_color_btn.setVisible(False)
            self.label_color_btn.setVisible(False)
            self.style_label.setVisible(False)
            self.style_combo.setVisible(False)
            self.thickness_label.setVisible(False)
            self.thickness_spin.setVisible(False)
            self.icom_style_label.setVisible(False)
            self.icom_style_combo.setVisible(False)
            
        elif item_type == "arrow":
            self.box_color_btn.setVisible(False)
            self.arrow_color_btn.setVisible(True)
            self.label_color_btn.setVisible(False)
            self.style_label.setVisible(True)
            self.style_combo.setVisible(True)
            self.thickness_label.setVisible(True)
            self.thickness_spin.setVisible(True)
            self.icom_style_label.setVisible(True)
            self.icom_style_combo.setVisible(True)
            
            if extra_props:
                self.style_combo.blockSignals(True)
                self.thickness_spin.blockSignals(True)
                self.icom_style_combo.blockSignals(True)
                
                self.style_combo.setCurrentText(extra_props.get("style", "Solid"))
                self.thickness_spin.setValue(extra_props.get("thickness", 2))
                self.icom_style_combo.setCurrentText(extra_props.get("icom_style", "Jagged"))
                
                self.style_combo.blockSignals(False)
                self.thickness_spin.blockSignals(False)
                self.icom_style_combo.blockSignals(False)
                
        elif item_type == "arrow_label":
            self.box_color_btn.setVisible(False)
            self.arrow_color_btn.setVisible(False)
            self.label_color_btn.setVisible(True)
            self.style_label.setVisible(False)
            self.style_combo.setVisible(False)
            self.thickness_label.setVisible(False)
            self.thickness_spin.setVisible(False)
            self.icom_style_label.setVisible(False)
            self.icom_style_combo.setVisible(False)

        self.selection_id_edit.blockSignals(False)
        self.selection_auto_id_edit.blockSignals(False)
        self.selection_name_edit.blockSignals(False)
        self.hide_label_check.blockSignals(False)
        self.tunnel_tail_check.blockSignals(False)
        self.tunnel_head_check.blockSignals(False)
        self.description_edit.blockSignals(False)
        self.font_combo.blockSignals(False)
        self.font_size_spin.blockSignals(False)
        self.bold_check.blockSignals(False)
        self.italic_check.blockSignals(False)

    def open_box_color_dialog(self):
        color = QColorDialog.getColor(Qt.GlobalColor.white, self, "Select Box Color")
        if color.isValid():
            self.box_color_changed.emit(color)

    def open_arrow_color_dialog(self):
        color = QColorDialog.getColor(Qt.GlobalColor.black, self, "Select Arrow Color")
        if color.isValid():
            self.arrow_color_changed.emit(color)

    def open_label_color_dialog(self):
        color = QColorDialog.getColor(Qt.GlobalColor.black, self, "Select Label Color")
        if color.isValid():
            self.label_color_changed.emit(color)
