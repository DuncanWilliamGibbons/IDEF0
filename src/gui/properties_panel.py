from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QSpinBox, QGroupBox, 
                             QPushButton, QCheckBox, QScrollArea, QFontComboBox)
from PyQt6.QtCore import pyqtSignal, Qt

class PropertiesPanel(QWidget):
    layout_changed = pyqtSignal(int, int, int, int) # spacing_x, spacing_y, box_w, box_h
    
    # Hide Signals
    hide_arrow_ids_changed = pyqtSignal(bool)
    hide_box_ids_changed = pyqtSignal(bool)
    
    # Global Font Signals
    global_font_family_changed = pyqtSignal(str)
    global_font_size_changed = pyqtSignal(int)
    global_font_bold_changed = pyqtSignal(bool)
    global_font_italic_changed = pyqtSignal(bool)
    
    # Action Signals
    add_function_clicked = pyqtSignal()
    add_arrow_clicked = pyqtSignal()
    assign_arrow_clicked = pyqtSignal()
    
    # History Signals
    reset_clicked = pyqtSignal()
    undo_clicked = pyqtSignal()
    refresh_clicked = pyqtSignal()

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
            QPushButton, QSpinBox {
                min-height: 25px;
            }
        """)
        
        # --- UTILITIES (TOP) ---
        self.util_group = QGroupBox("Diagram Utilities")
        self.util_layout = QVBoxLayout()
        self.util_group.setLayout(self.util_layout)
        
        self.refresh_btn = QPushButton("Refresh View")
        self.refresh_btn.clicked.connect(self.refresh_clicked.emit)
        self.util_layout.addWidget(self.refresh_btn)
        
        self.reset_btn = QPushButton("Reset Diagram")
        self.reset_btn.clicked.connect(self.reset_clicked.emit)
        self.util_layout.addWidget(self.reset_btn)
        
        self.layout.addWidget(self.util_group)

        # --- DIAGRAM STRUCTURE ---
        self.structure_group = QGroupBox("Diagram Structure")
        self.structure_layout = QVBoxLayout()
        self.structure_group.setLayout(self.structure_layout)

        self.add_func_btn = QPushButton("Add Function")
        self.add_func_btn.clicked.connect(self.add_function_clicked.emit)
        self.structure_layout.addWidget(self.add_func_btn)

        self.add_arrow_btn = QPushButton("Add Arrow")
        self.add_arrow_btn.clicked.connect(self.add_arrow_clicked.emit)
        self.structure_layout.addWidget(self.add_arrow_btn)

        self.assign_arrow_btn = QPushButton("Assign Arrow")
        self.assign_arrow_btn.clicked.connect(self.assign_arrow_clicked.emit)
        self.structure_layout.addWidget(self.assign_arrow_btn)
        
        self.layout.addWidget(self.structure_group)

        # --- DIAGRAM SETTINGS ---
        self.settings_group = QGroupBox("Diagram Settings")
        self.settings_layout = QVBoxLayout()
        self.settings_group.setLayout(self.settings_layout)
        
        self.settings_layout.addWidget(QLabel("Box Width:"))
        self.box_width_spin = QSpinBox()
        self.box_width_spin.setRange(50, 500)
        self.box_width_spin.setValue(150)
        self.box_width_spin.setSingleStep(10)
        self.box_width_spin.valueChanged.connect(self.emit_layout_change)
        self.settings_layout.addWidget(self.box_width_spin)
        
        self.settings_layout.addWidget(QLabel("Box Height:"))
        self.box_height_spin = QSpinBox()
        self.box_height_spin.setRange(50, 500)
        self.box_height_spin.setValue(100)
        self.box_height_spin.setSingleStep(10)
        self.box_height_spin.valueChanged.connect(self.emit_layout_change)
        self.settings_layout.addWidget(self.box_height_spin)
        
        self.settings_layout.addWidget(QLabel("Horizontal Spacing:"))
        self.h_space_spin = QSpinBox()
        self.h_space_spin.setRange(100, 1000)
        self.h_space_spin.setValue(250)
        self.h_space_spin.setSingleStep(10)
        self.h_space_spin.valueChanged.connect(self.emit_layout_change)
        self.settings_layout.addWidget(self.h_space_spin)
        
        self.settings_layout.addWidget(QLabel("Vertical Spacing:"))
        self.v_space_spin = QSpinBox()
        self.v_space_spin.setRange(100, 1000)
        self.v_space_spin.setValue(200)
        self.v_space_spin.setSingleStep(10)
        self.v_space_spin.valueChanged.connect(self.emit_layout_change)
        self.settings_layout.addWidget(self.v_space_spin)
        
        self.hide_boxes_check = QCheckBox("Hide Function IDs")
        self.hide_boxes_check.toggled.connect(self.hide_box_ids_changed.emit)
        self.settings_layout.addWidget(self.hide_boxes_check)
        
        self.hide_arrows_check = QCheckBox("Hide Arrow IDs")
        self.hide_arrows_check.toggled.connect(self.hide_arrow_ids_changed.emit)
        self.settings_layout.addWidget(self.hide_arrows_check)
        
        self.layout.addWidget(self.settings_group)
        
        # --- GLOBAL FONT SETTINGS ---
        self.global_font_group = QGroupBox("Global Font Settings")
        self.global_font_layout = QVBoxLayout()
        self.global_font_group.setLayout(self.global_font_layout)
        
        self.global_font_layout.addWidget(QLabel("Font Family:"))
        self.global_font_combo = QFontComboBox()
        self.global_font_combo.currentFontChanged.connect(lambda f: self.global_font_family_changed.emit(f.family()))
        self.global_font_layout.addWidget(self.global_font_combo)
        
        self.global_font_size_label = QLabel("Font Size:")
        self.global_font_layout.addWidget(self.global_font_size_label)
        self.global_font_size_spin = QSpinBox()
        self.global_font_size_spin.setRange(6, 48)
        self.global_font_size_spin.setValue(10)
        self.global_font_size_spin.valueChanged.connect(self.global_font_size_changed.emit)
        self.global_font_layout.addWidget(self.global_font_size_spin)
        
        self.global_bold_check = QCheckBox("Bold")
        self.global_bold_check.toggled.connect(self.global_font_bold_changed.emit)
        self.global_font_layout.addWidget(self.global_bold_check)
        
        self.global_italic_check = QCheckBox("Italic")
        self.global_italic_check.toggled.connect(self.global_font_italic_changed.emit)
        self.global_font_layout.addWidget(self.global_italic_check)
        
        self.layout.addWidget(self.global_font_group)
        
        self.layout.addStretch()

    def emit_layout_change(self):
        self.layout_changed.emit(
            self.h_space_spin.value(), 
            self.v_space_spin.value(),
            self.box_width_spin.value(),
            self.box_height_spin.value()
        )
