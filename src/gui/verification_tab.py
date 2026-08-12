from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
                             QTableWidgetItem, QPushButton, QLabel, QFileDialog, QMessageBox, QHeaderView)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from src.core.compliance import (get_compliance_data,
                                 generate_compliance_report, status_icon)
from src.gui.theme import status_colour

class VerificationReportTab(QWidget):
    def __init__(self, model, is_night=False, parent=None):
        super().__init__(parent)
        self.model = model
        self.is_night = is_night
        self.init_ui()
        self.refresh_report()

    def set_night_mode(self, is_night: bool):
        """Redraw the PASS/FAIL marks for the theme now in force.

        The stylesheet handles everything else in the table, but a foreground
        set on an individual item overrides it, so these have to be re-coloured
        rather than restyled.
        """
        if is_night == self.is_night:
            return
        self.is_night = is_night
        self.apply_legend_colour()
        self.refresh_report()

    def set_model(self, model):
        """Point the report at a model and re-run it.

        A report is a statement about a model at a moment; keeping the tab alive
        across an edit, or across opening a different project, left it asserting
        something that had stopped being true.
        """
        self.model = model
        self.title.setText(
            f"ISO/IEC/IEEE 31320-1 Verification: {model.name}")
        self.refresh_report()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Header
        header = QWidget()
        h_layout = QHBoxLayout(header)
        self.title = QLabel(f"ISO/IEC/IEEE 31320-1 Verification: {self.model.name}")
        self.title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        h_layout.addWidget(self.title)
        
        h_layout.addStretch()
        
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_report)
        h_layout.addWidget(refresh_btn)
        
        export_csv_btn = QPushButton("Export CSV")
        export_csv_btn.clicked.connect(self.export_csv)
        h_layout.addWidget(export_csv_btn)
        
        export_pdf_btn = QPushButton("Export PDF")
        export_pdf_btn.clicked.connect(self.export_pdf)
        h_layout.addWidget(export_pdf_btn)
        
        layout.addWidget(header)
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Status", "Rule ID", "Clause", "Requirement Description", "Findings"])

        # Allow user to adjust all columns
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)

        # Set initial widths to make the right-hand columns bigger
        self.table.setColumnWidth(0, 110)  # Status
        self.table.setColumnWidth(1, 110)  # Rule ID
        self.table.setColumnWidth(2, 70)   # Clause
        self.table.setColumnWidth(3, 350)  # Requirement Description
        self.table.setColumnWidth(4, 500)  # Findings (Bigger)

        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        # A rule the model was never inspected against must not read as a pass,
        # so those rules are not rows at all and every row here is an answer.
        self.legend = QLabel(
            "✅ PASS / ❌ FAIL - every row was checked against the model.   "
            "Criteria no tool can decide - clause 6 (SEM-*), and the drawing "
            "rules the editor can only obey (SYN-BOX-01, SYN-ARROW-02, "
            "SYN-ARROW-04) - are left to a reviewer and are not listed.")
        self.legend.setWordWrap(True)
        layout.addWidget(self.legend)
        self.apply_legend_colour()

    def apply_legend_colour(self):
        """Grey enough to recede, light enough to read on the current ground."""
        grey = "#a1a1aa" if self.is_night else "#71717A"
        self.legend.setStyleSheet(f"color: {grey}; font-size: 9pt;")

    def refresh_report(self):
        results = get_compliance_data(self.model)
        self.table.setRowCount(len(results))

        for i, r in enumerate(results):
            status_item = QTableWidgetItem(status_icon(r))
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            status_item.setForeground(QColor(status_colour(r.status, self.is_night)))
            self.table.setItem(i, 0, status_item)

            self.table.setItem(i, 1, QTableWidgetItem(r.rule_id))
            self.table.setItem(i, 2, QTableWidgetItem(r.clause))
            self.table.setItem(i, 3, QTableWidgetItem(r.description))

            findings_text = "; ".join(r.items) if r.items else ""
            findings_item = QTableWidgetItem(findings_text)
            if r.items:
                findings_item.setToolTip("\n".join(r.items))
            self.table.setItem(i, 4, findings_item)

    def export_csv(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Export CSV", "", "CSV Files (*.csv)")
        if not filename: return
        
        try:
            content = generate_compliance_report(self.model, format="csv")
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(content)
            QMessageBox.information(self, "Success", "Report exported to CSV successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export CSV:\n{str(e)}")

    def export_pdf(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Export PDF", "", "PDF Files (*.pdf)")
        if not filename: return
        
        try:
            from PyQt6.QtPrintSupport import QPrinter
            from PyQt6.QtGui import QTextDocument, QPageLayout
            
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setPageOrientation(QPageLayout.Orientation.Landscape)
            printer.setOutputFileName(filename)
            
            # Create HTML representation for high-quality table rendering in PDF
            html = f"""
            <html>
            <head>
                <style>
                    h1 {{ text-align: center; font-family: sans-serif; color: #333; }}
                    table {{ border-collapse: collapse; width: 100%; font-family: sans-serif; font-size: 10pt; }}
                    th {{ background-color: #f2f2f2; border: 1px solid #ddd; padding: 8px; text-align: left; }}
                    td {{ border: 1px solid #ddd; padding: 8px; }}
                    .pass {{ color: green; font-weight: bold; }}
                    .fail {{ color: red; font-weight: bold; }}
                </style>
            </head>
            <body>
                <h1>ISO/IEC/IEEE 31320-1 Verification Report</h1>
                <p><b>Model:</b> {self.model.name}</p>
                <table>
                    <tr>
                        <th>Status</th>
                        <th>Rule ID</th>
                        <th>Clause</th>
                        <th>Requirement Description</th>
                        <th>Findings</th>
                    </tr>
            """

            results = get_compliance_data(self.model)
            for r in results:
                status_class = "pass" if r.status else "fail"
                failing_items = ", ".join(r.items) if r.items else ""
                html += f"""
                    <tr>
                        <td class='{status_class}'>{r.status_text}</td>
                        <td>{r.rule_id}</td>
                        <td>{r.clause}</td>
                        <td>{r.description}</td>
                        <td>{failing_items}</td>
                    </tr>
                """
            
            html += """
                </table>
            </body>
            </html>
            """
            
            doc = QTextDocument()
            doc.setHtml(html)
            doc.print(printer)
            
            QMessageBox.information(self, "Success", "Report exported to PDF successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export PDF:\n{str(e)}")
