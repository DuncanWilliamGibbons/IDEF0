"""
Management View Widgets for IDEF0 Modeler.
Provides interactive tables to view, search, edit, and delete ICOMs and Functions database items across the project model.
"""

import csv
import io
import json
import os
import re
import xml.etree.ElementTree as ET

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QLineEdit, QPushButton, QLabel, QHeaderView, QDialog, QFormLayout,
    QMessageBox, QComboBox, QTextEdit, QAbstractItemView, QFileDialog
)
from PyQt6.QtCore import Qt
from src.core.model import IDEF0Model, ArrowType, ActivityBox
from src.core.layout import natural_sort_key


# --------------------------------------------------------------------------
# Table export
# --------------------------------------------------------------------------
EXPORT_FILTERS = [
    ("CSV (*.csv)", "csv", ".csv"),
    ("JSON (*.json)", "json", ".json"),
    ("XML (*.xml)", "xml", ".xml"),
    ("Text (*.txt)", "txt", ".txt"),
]


def _xml_tag(header: str) -> str:
    """A column heading such as 'ICOM Code / ID' as a legal XML element name."""
    tag = re.sub(r'[^0-9A-Za-z]+', '_', header or "").strip('_').lower()
    if not tag or tag[0].isdigit():
        tag = f"field_{tag}" if tag else "field"
    return tag


def render_table(headers, rows, fmt, record="row", collection="rows"):
    """One table, in whichever of the four formats was asked for.

    Kept as a plain function of (headers, rows) so both database views share it
    and neither can drift into exporting a different shape from the other.
    """
    fmt = (fmt or "csv").lower()

    if fmt == "csv":
        buffer = io.StringIO()
        # Excel reads a bare \n as a line break inside a cell, so use \r\n and
        # let csv quote anything containing one.
        writer = csv.writer(buffer, lineterminator="\r\n")
        writer.writerow(headers)
        writer.writerows(rows)
        return buffer.getvalue()

    if fmt == "json":
        payload = [dict(zip(headers, row)) for row in rows]
        return json.dumps({collection: payload, "count": len(payload)},
                          indent=2, ensure_ascii=False) + "\n"

    if fmt == "xml":
        root = ET.Element(collection, {"count": str(len(rows))})
        tags = [_xml_tag(h) for h in headers]
        for row in rows:
            element = ET.SubElement(root, record)
            for tag, value in zip(tags, row):
                ET.SubElement(element, tag).text = "" if value is None else str(value)
        ET.indent(root, space="  ")
        return ('<?xml version="1.0" encoding="UTF-8"?>\n'
                + ET.tostring(root, encoding="unicode") + "\n")

    # txt: a fixed-width table, sized from the widest cell in each column
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], len(str(value)))
    lines = ["  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers)),
             "  ".join("-" * w for w in widths)]
    for row in rows:
        lines.append("  ".join(str(v).ljust(widths[i]) for i, v in enumerate(row)))
    lines.append("")
    lines.append(f"{len(rows)} rows")
    return "\n".join(lines) + "\n"


class TableViewMixin:
    """Filtering and export, shared by every table view in the application.

    The filter is a deliberate act, so what is on screen is what is written -
    exporting the whole database from a filtered view would quietly hand back
    rows the user had just excluded.
    """

    export_record = "row"
    export_collection = "rows"
    export_default_name = "export"

    def filter_data(self, text: str):
        """Hide every row that does not contain `text` in any of its cells."""
        query = text.strip().lower()
        for i in range(self.table.rowCount()):
            match = not query
            if query:
                for col in range(self.table.columnCount()):
                    item = self.table.item(i, col)
                    if item and query in item.text().lower():
                        match = True
                        break
            self.table.setRowHidden(i, not match)

    def fit_columns(self, stretch_column=None):
        """Size every column to its widest cell, then let the user drag them.

        A report is unreadable when a long diagram title is elided into an
        ellipsis, so the width comes from the text. `stretch_column` takes
        whatever room is left over.
        """
        self.table.resizeColumnsToContents()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        if stretch_column is not None and stretch_column < self.table.columnCount():
            header.setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)

    def visible_rows(self):
        headers = [self.table.horizontalHeaderItem(c).text()
                   for c in range(self.table.columnCount())]
        rows = []
        for r in range(self.table.rowCount()):
            if self.table.isRowHidden(r):
                continue
            rows.append([(self.table.item(r, c).text() if self.table.item(r, c) else "")
                         for c in range(self.table.columnCount())])
        return headers, rows

    def build_export_button(self):
        button = QPushButton("Export")
        button.setToolTip("Export the rows shown to CSV, JSON, XML or TXT")
        button.clicked.connect(self.on_export_clicked)
        return button

    def on_export_clicked(self):
        headers, rows = self.visible_rows()
        if not rows:
            QMessageBox.information(self, "Nothing to Export",
                                    "There are no rows to export.")
            return

        filename, chosen = QFileDialog.getSaveFileName(
            self, "Export Table", self.export_default_name,
            ";;".join(f[0] for f in EXPORT_FILTERS))
        if not filename:
            return

        fmt, suffix = "csv", ".csv"
        for label, key, ext in EXPORT_FILTERS:
            if label == chosen:
                fmt, suffix = key, ext
                break
        # An extension typed into the dialog wins over the filter drop-down.
        typed = os.path.splitext(filename)[1].lower()
        for _label, key, ext in EXPORT_FILTERS:
            if typed == ext:
                fmt, suffix = key, ext
                break
        if not typed:
            filename += suffix

        try:
            text = render_table(headers, rows, fmt,
                                record=self.export_record,
                                collection=self.export_collection)
            with open(filename, 'w', encoding='utf-8', newline='') as handle:
                handle.write(text)
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed",
                                 f"Could not write {filename}:\n{exc}")
            return

        if self.main_window and hasattr(self.main_window, 'log_message'):
            self.main_window.log_message(
                f"Exported {len(rows)} {self.export_collection} to "
                f"{os.path.basename(filename)}")


class EditICOMDialog(QDialog):
    """Dialog for editing an ICOM / Arrow item's metadata and parent/ancestor relationship."""
    def __init__(self, icom_code: str, label: str, arrow_type: ArrowType, description: str = "",
                 available_parents=None, current_parent_key: str = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit ICOM: {icom_code or label or 'Arrow'}")
        self.resize(480, 340)
        
        layout = QVBoxLayout(self)
        form = QFormLayout()
        
        self.icom_edit = QLineEdit(icom_code or "")
        self.label_edit = QLineEdit(label or "")
        
        self.type_combo = QComboBox()
        for at in [ArrowType.INPUT, ArrowType.CONTROL, ArrowType.OUTPUT, ArrowType.MECHANISM]:
            self.type_combo.addItem(at.value, at)
        idx = self.type_combo.findData(arrow_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
            
        self.parent_combo = QComboBox()
        self.parent_combo.addItem("None (Top Level / Boundary)", None)
        if available_parents:
            for p_info in available_parents:
                self.parent_combo.addItem(p_info['display'], p_info['key'])
                
        if current_parent_key:
            p_idx = self.parent_combo.findData(current_parent_key)
            if p_idx >= 0:
                self.parent_combo.setCurrentIndex(p_idx)
            
        self.desc_edit = QTextEdit(description or "")
        self.desc_edit.setMaximumHeight(80)
        
        form.addRow("ICOM Code / ID:", self.icom_edit)
        form.addRow("Label / Name:", self.label_edit)
        form.addRow("Arrow Type:", self.type_combo)
        form.addRow("Parent / Ancestor ICOM:", self.parent_combo)
        form.addRow("Description:", self.desc_edit)
        
        layout.addLayout(form)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QPushButton("Save Changes")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)

    def get_data(self):
        return {
            'icom_code': self.icom_edit.text().strip(),
            'label': self.label_edit.text().strip(),
            'type': self.type_combo.currentData(),
            'parent_key': self.parent_combo.currentData(),
            'description': self.desc_edit.toPlainText().strip()
        }


class EditFunctionDialog(QDialog):
    """Dialog for editing an Activity Box / Function metadata."""
    def __init__(self, box: ActivityBox, current_parent_id: str = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit Function: {box.id} - {box.name}")
        self.resize(480, 320)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.id_label = QLabel(box.id)
        self.name_edit = QLineEdit(box.name)

        # A function's parent follows from where its box sits in the decomposition,
        # so it is reported here but reassigned on the diagram, not in this dialog.
        self.parent_label = QLabel(current_parent_id or "None (Top Level / Context)")

        self.desc_edit = QTextEdit(box.description or "")
        self.desc_edit.setMaximumHeight(80)

        form.addRow("Function ID:", self.id_label)
        form.addRow("Function Name:", self.name_edit)
        form.addRow("Parent Function:", self.parent_label)
        form.addRow("Description:", self.desc_edit)
        
        layout.addLayout(form)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QPushButton("Save Changes")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)

    def get_data(self):
        return {
            'name': self.name_edit.text().strip(),
            'description': self.desc_edit.toPlainText().strip()
        }


class ICOMsManagerWidget(TableViewMixin, QWidget):
    """Tab widget for viewing, filtering, editing, and deleting all ICOMs in the project."""

    export_record = "icom"
    export_collection = "icoms"
    export_default_name = "project_icoms"

    def __init__(self, project_model: IDEF0Model, main_window=None, parent=None):
        super().__init__(parent)
        self.project_model = project_model
        self.main_window = main_window
        
        self.init_ui()
        self.populate_data()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # Header / Search bar
        top_layout = QHBoxLayout()
        title_label = QLabel("<b>Project ICOMs Database</b>")
        title_label.setStyleSheet("font-size: 14px;")
        top_layout.addWidget(title_label)
        top_layout.addStretch()
        
        search_lbl = QLabel("Filter:")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by code, label, type, or diagram...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.filter_data)
        self.search_edit.setMinimumWidth(250)
        top_layout.addWidget(search_lbl)
        top_layout.addWidget(self.search_edit)
        
        layout.addLayout(top_layout)
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "ICOM Code / ID", "Label / Name", "Type", "Parent / Ancestor", "Diagram(s)", "Source", "Target", "Description"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(self.on_edit_clicked)
        
        layout.addWidget(self.table)
        
        # Action Bar
        action_layout = QHBoxLayout()
        self.stats_label = QLabel("Total ICOMs: 0")
        action_layout.addWidget(self.stats_label)
        action_layout.addStretch()
        
        refresh_btn = QPushButton("Refresh List")
        refresh_btn.clicked.connect(self.populate_data)
        action_layout.addWidget(refresh_btn)

        edit_btn = QPushButton("Edit Selected")
        edit_btn.clicked.connect(self.on_edit_clicked)
        action_layout.addWidget(edit_btn)

        delete_btn = QPushButton("Delete Selected")
        delete_btn.setStyleSheet("QPushButton { color: #cc0000; }")
        delete_btn.clicked.connect(self.on_delete_clicked)
        action_layout.addWidget(delete_btn)

        self.export_btn = self.build_export_button()
        action_layout.addWidget(self.export_btn)

        layout.addLayout(action_layout)

    def populate_data(self):
        """Build distinct ICOM / Arrow list from all diagrams in the project model."""
        self.table.setRowCount(0)
        if not self.project_model:
            return
            
        icom_map = {} # key -> info dict
        
        for diag in self.project_model.diagrams:
            box_map = {b.id: b.name for b in diag.boxes}
            arrow_dict = {a.id: a for a in diag.arrows}
            
            for arrow in diag.arrows:
                key = (arrow.icom_code or arrow.id or "").strip()
                if not key:
                    key = (arrow.label or "Unlabeled").strip()
                    
                if key not in icom_map:
                    icom_map[key] = {
                        'key': key,
                        'icom_code': arrow.icom_code or arrow.id,
                        'label': arrow.label or "",
                        'type': arrow.type.value,
                        'arrow_type_enum': arrow.type,
                        'parent_key': None,
                        'diagrams': set(),
                        'sources': set(),
                        'targets': set(),
                        'description': arrow.description or "",
                        'sample_arrow': arrow
                    }
                
                info = icom_map[key]
                
                # Check for parent arrow
                if not info['parent_key'] and (arrow.branch_parent_id or arrow.join_target_id):
                    p_id = arrow.branch_parent_id or arrow.join_target_id
                    p_arr = arrow_dict.get(p_id)
                    if p_arr:
                        pk = (p_arr.icom_code or p_arr.id or p_arr.label or "").strip()
                        if pk and pk != key:
                            info['parent_key'] = pk
                
                info['diagrams'].add(diag.node_number)
                if arrow.source_box_id and arrow.source_box_id in box_map:
                    info['sources'].add(f"{arrow.source_box_id} ({box_map[arrow.source_box_id]})")
                elif arrow.source_box_id:
                    info['sources'].add(arrow.source_box_id)
                else:
                    info['sources'].add("Boundary")
                    
                if arrow.target_box_id and arrow.target_box_id in box_map:
                    info['targets'].add(f"{arrow.target_box_id} ({box_map[arrow.target_box_id]})")
                elif arrow.target_box_id:
                    info['targets'].add(arrow.target_box_id)
                else:
                    info['targets'].add("Boundary")
                    
                if arrow.description and not info['description']:
                    info['description'] = arrow.description

        sorted_keys = sorted(icom_map.keys())
        self.icom_map_cached = icom_map
        self.table.setRowCount(len(sorted_keys))
        
        for i, key in enumerate(sorted_keys):
            info = icom_map[key]
            
            item_code = QTableWidgetItem(info['icom_code'])
            item_code.setFlags(item_code.flags() ^ Qt.ItemFlag.ItemIsEditable)
            item_code.setData(Qt.ItemDataRole.UserRole, info)
            
            item_label = QTableWidgetItem(info['label'])
            item_label.setFlags(item_label.flags() ^ Qt.ItemFlag.ItemIsEditable)
            
            item_type = QTableWidgetItem(info['type'])
            item_type.setFlags(item_type.flags() ^ Qt.ItemFlag.ItemIsEditable)
            
            parent_disp = "None"
            if info['parent_key'] and info['parent_key'] in icom_map:
                p_info = icom_map[info['parent_key']]
                p_code = p_info['icom_code'] or p_info['key']
                p_lbl = p_info['label'] or ""
                parent_disp = f"[{p_code}] {p_lbl}".strip()
            elif info['parent_key']:
                parent_disp = info['parent_key']
                
            item_parent = QTableWidgetItem(parent_disp)
            item_parent.setFlags(item_parent.flags() ^ Qt.ItemFlag.ItemIsEditable)
            
            item_diags = QTableWidgetItem(", ".join(sorted(info['diagrams'])))
            item_diags.setFlags(item_diags.flags() ^ Qt.ItemFlag.ItemIsEditable)
            
            item_src = QTableWidgetItem(", ".join(sorted(info['sources'])))
            item_src.setFlags(item_src.flags() ^ Qt.ItemFlag.ItemIsEditable)
            
            item_tgt = QTableWidgetItem(", ".join(sorted(info['targets'])))
            item_tgt.setFlags(item_tgt.flags() ^ Qt.ItemFlag.ItemIsEditable)
            
            item_desc = QTableWidgetItem(info['description'])
            item_desc.setFlags(item_desc.flags() ^ Qt.ItemFlag.ItemIsEditable)
            
            self.table.setItem(i, 0, item_code)
            self.table.setItem(i, 1, item_label)
            self.table.setItem(i, 2, item_type)
            self.table.setItem(i, 3, item_parent)
            self.table.setItem(i, 4, item_diags)
            self.table.setItem(i, 5, item_src)
            self.table.setItem(i, 6, item_tgt)
            self.table.setItem(i, 7, item_desc)
            
        self.stats_label.setText(f"Total ICOMs: {len(sorted_keys)}")
        self.fit_columns(stretch_column=1)

    def get_selected_info(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item0 = self.table.item(row, 0)
        if not item0:
            return None
        return item0.data(Qt.ItemDataRole.UserRole)

    def on_edit_clicked(self):
        info = self.get_selected_info()
        if not info:
            QMessageBox.information(self, "No Selection", "Please select an ICOM row to edit.")
            return
            
        # Build available parents list (excluding self)
        available_parents = []
        if hasattr(self, 'icom_map_cached'):
            for k, v in self.icom_map_cached.items():
                if k != info['key']:
                    code_str = v['icom_code'] or k
                    lbl_str = v['label'] or ""
                    disp = f"[{code_str}] {lbl_str}".strip()
                    available_parents.append({'key': k, 'display': disp})
            available_parents.sort(key=lambda x: x['display'])
            
        dialog = EditICOMDialog(
            icom_code=info['icom_code'],
            label=info['label'],
            arrow_type=info['arrow_type_enum'],
            description=info['description'],
            available_parents=available_parents,
            current_parent_key=info['parent_key'],
            parent=self
        )
        
        if dialog.exec():
            data = dialog.get_data()
            new_code = data['icom_code']
            new_label = data['label']
            new_type = data['type']
            new_parent_key = data['parent_key']
            new_desc = data['description']
            
            if self.main_window and hasattr(self.main_window, 'save_snapshot'):
                self.main_window.save_snapshot()
                
            target_key = info['key']
            
            for diag in self.project_model.diagrams:
                # Find parent candidate arrow in this diagram if new_parent_key is specified
                parent_candidate = None
                if new_parent_key:
                    parent_candidate = next(
                        (a for a in diag.arrows if (a.icom_code or a.id or a.label or "").strip() == new_parent_key or a.icom_code == new_parent_key or a.id == new_parent_key),
                        None
                    )
                    
                for arrow in diag.arrows:
                    k = (arrow.icom_code or arrow.id or arrow.label or "").strip()
                    if k == target_key or arrow.icom_code == info['icom_code'] or arrow.id == info['icom_code']:
                        if new_code:
                            arrow.icom_code = new_code
                        if new_label:
                            arrow.label = new_label
                        arrow.type = new_type
                        arrow.description = new_desc
                        
                        # Apply parent/ancestor link propagation
                        if new_parent_key and parent_candidate and parent_candidate.id != arrow.id:
                            arrow.branch_parent_id = parent_candidate.id
                        elif new_parent_key is None:
                            arrow.branch_parent_id = None

            self.populate_data()
            if self.main_window and hasattr(self.main_window, 'refresh_all_diagrams'):
                self.main_window.refresh_all_diagrams()
                self.main_window.log_message(f"Updated ICOM '{new_code or new_label}' across project model.")

    def on_delete_clicked(self):
        info = self.get_selected_info()
        if not info:
            QMessageBox.information(self, "No Selection", "Please select an ICOM row to delete.")
            return
            
        code_str = info['icom_code'] or info['label']
        reply = QMessageBox.question(
            self,
            "Confirm Delete ICOM",
            f"Are you sure you want to completely delete ICOM '{code_str}' from the model?\n\n"
            "This will remove the arrow and any associated branches across all diagrams in the project.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            if self.main_window and hasattr(self.main_window, 'save_snapshot'):
                self.main_window.save_snapshot()
                
            target_key = info['key']
            
            for diag in self.project_model.diagrams:
                to_remove = []
                for arrow in diag.arrows:
                    k = (arrow.icom_code or arrow.id or arrow.label or "").strip()
                    if k == target_key or arrow.icom_code == info['icom_code'] or arrow.id == info['icom_code']:
                        to_remove.append(arrow)
                for a in to_remove:
                    if a in diag.arrows:
                        diag.arrows.remove(a)
                        
            self.populate_data()
            if self.main_window and hasattr(self.main_window, 'refresh_all_diagrams'):
                self.main_window.refresh_all_diagrams()
                self.main_window.log_message(f"Deleted ICOM '{code_str}' from project model.")


class FunctionsManagerWidget(TableViewMixin, QWidget):
    """Tab widget for viewing, filtering, editing, and deleting all Functions (Activity Boxes) in the project."""

    export_record = "function"
    export_collection = "functions"
    export_default_name = "project_functions"

    def __init__(self, project_model: IDEF0Model, main_window=None, parent=None):
        super().__init__(parent)
        self.project_model = project_model
        self.main_window = main_window
        
        self.init_ui()
        self.populate_data()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # Header / Search bar
        top_layout = QHBoxLayout()
        title_label = QLabel("<b>Project Functions Database</b>")
        title_label.setStyleSheet("font-size: 14px;")
        top_layout.addWidget(title_label)
        top_layout.addStretch()
        
        search_lbl = QLabel("Filter:")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by function ID, name, or diagram...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.filter_data)
        self.search_edit.setMinimumWidth(250)
        top_layout.addWidget(search_lbl)
        top_layout.addWidget(self.search_edit)
        
        layout.addLayout(top_layout)
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Function ID", "Name", "Parent Function", "Diagram", "Decomposed?", "Color", "Description"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(self.on_edit_clicked)
        
        layout.addWidget(self.table)
        
        # Action Bar
        action_layout = QHBoxLayout()
        self.stats_label = QLabel("Total Functions: 0")
        action_layout.addWidget(self.stats_label)
        action_layout.addStretch()
        
        refresh_btn = QPushButton("Refresh List")
        refresh_btn.clicked.connect(self.populate_data)
        action_layout.addWidget(refresh_btn)
        
        edit_btn = QPushButton("Edit Selected")
        edit_btn.clicked.connect(self.on_edit_clicked)
        action_layout.addWidget(edit_btn)
        
        delete_btn = QPushButton("Delete Selected")
        delete_btn.setStyleSheet("QPushButton { color: #cc0000; }")
        delete_btn.clicked.connect(self.on_delete_clicked)
        action_layout.addWidget(delete_btn)

        self.export_btn = self.build_export_button()
        action_layout.addWidget(self.export_btn)

        layout.addLayout(action_layout)

    def populate_data(self):
        """Build list of all Activity Boxes across all diagrams in the project model."""
        self.table.setRowCount(0)
        if not self.project_model:
            return
            
        decomposed_ids = {d.node_number for d in self.project_model.diagrams}
        boxes_info = []
        
        for diag in self.project_model.diagrams:
            for box in diag.boxes:
                # Resolve Parent Function (e.g. Diagram node number or parent activity box)
                parent_fn = diag.node_number if diag.node_number != "A0" else "A-0 Context"
                boxes_info.append({
                    'box': box,
                    'diagram_node': diag.node_number,
                    'parent_function': parent_fn,
                    'is_decomposed': box.id in decomposed_ids
                })
                
        boxes_info.sort(key=lambda info: natural_sort_key(info['box'].id))
        self.boxes_info_cached = boxes_info
        
        self.table.setRowCount(len(boxes_info))
        
        for i, info in enumerate(boxes_info):
            box = info['box']
            
            item_id = QTableWidgetItem(box.id)
            item_id.setFlags(item_id.flags() ^ Qt.ItemFlag.ItemIsEditable)
            item_id.setData(Qt.ItemDataRole.UserRole, info)
            
            item_name = QTableWidgetItem(box.name)
            item_name.setFlags(item_name.flags() ^ Qt.ItemFlag.ItemIsEditable)
            
            item_parent = QTableWidgetItem(info['parent_function'])
            item_parent.setFlags(item_parent.flags() ^ Qt.ItemFlag.ItemIsEditable)
            
            item_diag = QTableWidgetItem(info['diagram_node'])
            item_diag.setFlags(item_diag.flags() ^ Qt.ItemFlag.ItemIsEditable)
            
            item_decomp = QTableWidgetItem("Yes" if info['is_decomposed'] else "No")
            item_decomp.setFlags(item_decomp.flags() ^ Qt.ItemFlag.ItemIsEditable)
            
            item_color = QTableWidgetItem(box.color or "#ffffff")
            item_color.setFlags(item_color.flags() ^ Qt.ItemFlag.ItemIsEditable)
            
            item_desc = QTableWidgetItem(box.description or "")
            item_desc.setFlags(item_desc.flags() ^ Qt.ItemFlag.ItemIsEditable)
            
            self.table.setItem(i, 0, item_id)
            self.table.setItem(i, 1, item_name)
            self.table.setItem(i, 2, item_parent)
            self.table.setItem(i, 3, item_diag)
            self.table.setItem(i, 4, item_decomp)
            self.table.setItem(i, 5, item_color)
            self.table.setItem(i, 6, item_desc)
            
        self.stats_label.setText(f"Total Functions: {len(boxes_info)}")
        self.fit_columns(stretch_column=1)

    def get_selected_info(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item0 = self.table.item(row, 0)
        if not item0:
            return None
        return item0.data(Qt.ItemDataRole.UserRole)

    def on_edit_clicked(self):
        info = self.get_selected_info()
        if not info:
            QMessageBox.information(self, "No Selection", "Please select a Function row to edit.")
            return
            
        box = info['box']
        dialog = EditFunctionDialog(
            box=box,
            current_parent_id=info['parent_function'],
            parent=self
        )

        if dialog.exec():
            data = dialog.get_data()
            new_name = data['name']
            new_desc = data['description']

            if self.main_window and hasattr(self.main_window, 'save_snapshot'):
                self.main_window.save_snapshot()

            if new_name:
                box.name = new_name
            box.description = new_desc

            self.populate_data()
            if self.main_window and hasattr(self.main_window, 'refresh_all_diagrams'):
                self.main_window.refresh_all_diagrams()
                self.main_window.log_message(f"Updated Function '{box.id} - {box.name}' in project model.")

    def on_delete_clicked(self):
        info = self.get_selected_info()
        if not info:
            QMessageBox.information(self, "No Selection", "Please select a Function row to delete.")
            return
            
        box = info['box']
        diag_node = info['diagram_node']
        
        reply = QMessageBox.question(
            self,
            "Confirm Delete Function",
            f"Are you sure you want to completely delete Function '{box.id} - {box.name}'?\n\n"
            f"This will remove the function box and disconnect attached arrows from diagram {diag_node}.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            if self.main_window and hasattr(self.main_window, 'save_snapshot'):
                self.main_window.save_snapshot()
                
            diag = self.project_model.get_diagram(diag_node)
            if diag:
                if box in diag.boxes:
                    diag.boxes.remove(box)
                # Disconnect arrows attached to this box
                for arrow in diag.arrows:
                    if arrow.source_box_id == box.id:
                        arrow.source_box_id = None
                    if arrow.target_box_id == box.id:
                        arrow.target_box_id = None
                        
            self.populate_data()
            if self.main_window and hasattr(self.main_window, 'refresh_all_diagrams'):
                self.main_window.refresh_all_diagrams()
                self.main_window.log_message(f"Deleted Function '{box.id}' from project model.")


class FlowReportWidget(TableViewMixin, QWidget):
    """Report > Flow Reports: every diagram carrying arrows of one ICOM role.

    A report of the same shape as the two database views, so it filters, sizes
    and exports the same way. One row per diagram that carries an arrow of the
    role, because that is the question the report answers - where in the model
    does this kind of signal appear.
    """

    export_record = "diagram"
    export_collection = "diagrams"

    HEADERS = ["Node", "Diagram Title", "Arrows Found", "Count"]

    def __init__(self, project_model: IDEF0Model, flow_type: str,
                 main_window=None, bracket_nodes=True, parent=None):
        super().__init__(parent)
        self.project_model = project_model
        self.flow_type = flow_type
        self.main_window = main_window
        # Report > ... follows the same "hide function IDs" setting the
        # diagrams do, so the two never disagree about how a node is written.
        self.bracket_nodes = bracket_nodes
        self.export_default_name = f"{flow_type.lower()}_flow_report"

        self.init_ui()
        self.populate_data()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        top_layout = QHBoxLayout()
        title_label = QLabel(f"<b>{self.flow_type} Flow Report</b>")
        title_label.setStyleSheet("font-size: 14px;")
        top_layout.addWidget(title_label)
        top_layout.addStretch()

        search_lbl = QLabel("Filter:")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by node, title, or arrow label...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.filter_data)
        self.search_edit.setMinimumWidth(250)
        top_layout.addWidget(search_lbl)
        top_layout.addWidget(self.search_edit)

        layout.addLayout(top_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.doubleClicked.connect(self.on_open_diagram)

        layout.addWidget(self.table)

        action_layout = QHBoxLayout()
        self.stats_label = QLabel("Total Diagrams: 0")
        action_layout.addWidget(self.stats_label)
        action_layout.addStretch()

        refresh_btn = QPushButton("Refresh List")
        refresh_btn.clicked.connect(self.populate_data)
        action_layout.addWidget(refresh_btn)

        open_btn = QPushButton("Open Diagram")
        open_btn.clicked.connect(self.on_open_diagram)
        action_layout.addWidget(open_btn)

        self.export_btn = self.build_export_button()
        action_layout.addWidget(self.export_btn)

        layout.addLayout(action_layout)

    def populate_data(self):
        self.table.setRowCount(0)
        if not self.project_model:
            return

        rows = []
        for diag in self.project_model.diagrams:
            arrows = [a for a in diag.arrows if a.type.value == self.flow_type]
            if not arrows:
                continue
            labels = ", ".join(a.label for a in arrows if a.label)
            rows.append({
                'node': diag.node_number,
                'title': diag.title,
                'labels': labels or "(Unnamed)",
                'count': len(arrows),
            })

        rows.sort(key=lambda r: natural_sort_key(r['node']))
        self.table.setRowCount(len(rows))

        for i, row in enumerate(rows):
            node = f"[{row['node']}]" if self.bracket_nodes else row['node']
            node_item = QTableWidgetItem(node)
            # The unbracketed node number, so double-click can open the diagram
            # whichever way the ID is being written.
            node_item.setData(Qt.ItemDataRole.UserRole, row['node'])
            self.table.setItem(i, 0, node_item)
            self.table.setItem(i, 1, QTableWidgetItem(row['title']))
            self.table.setItem(i, 2, QTableWidgetItem(row['labels']))

            count_item = QTableWidgetItem(str(row['count']))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                        | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 3, count_item)

        total = sum(row['count'] for row in rows)
        self.stats_label.setText(
            f"Total Diagrams: {len(rows)}   |   {self.flow_type} Arrows: {total}")
        self.fit_columns(stretch_column=2)

    def on_open_diagram(self):
        """Open the diagram named on the selected row."""
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if not item:
            return
        node = item.data(Qt.ItemDataRole.UserRole) or item.text().strip("[]")
        if self.main_window and hasattr(self.main_window, 'open_child_diagram'):
            self.main_window.open_child_diagram(node)
