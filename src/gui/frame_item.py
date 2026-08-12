from PyQt6.QtWidgets import QGraphicsItem, QGraphicsTextItem
from PyQt6.QtCore import Qt, QLineF
from PyQt6.QtGui import QPen, QFont, QFontMetrics

class DiagramFrameItem(QGraphicsItem):
    """
    Renders a standard IDEF0 diagram frame (Reader Kit).
    
    Top Panel: Author, Model, Date, Rev
    Bottom Panel: Model Page (Node Number), Name (Title), Number (C-Number/Page)
    """
    def __init__(self, rect, project_model, diagram, parent=None, show_context_info=True):
        super().__init__(parent)
        self.rect = rect
        self.project_model = project_model
        self.diagram = diagram
        self.padding = 40
        self.header_height = 50
        self.footer_height = 50
        self.show_context_info = show_context_info
        
        self.text_items = []
        self.is_night_mode = False
        
    def boundingRect(self):
        return self.rect

    def get_author_col_width(self):
        w = self.rect.width()
        v_font = QFont()
        v_font.setPointSize(10)
        v_font.setBold(True)
        fm = QFontMetrics(v_font)
        author_text = self.project_model.author if self.project_model and self.project_model.author else ""
        author_text_width = fm.horizontalAdvance(author_text)
        # Margin buffer of 40px, bounded between 15% and 50% of the total width
        return max(w * 0.15, min(author_text_width + 40, w * 0.50))

    def paint(self, painter, option, widget=None):
        # Determine Color
        color = Qt.GlobalColor.white if self.is_night_mode else Qt.GlobalColor.black
        
        # Draw Main Border
        pen = QPen(color, 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect)
        
        # Geometry
        x, y, w, h = self.rect.x(), self.rect.y(), self.rect.width(), self.rect.height()
        
        # Header Line
        painter.drawLine(QLineF(x, y + self.header_height, x + w, y + self.header_height))
        
        # Footer Line
        painter.drawLine(QLineF(x, y + h - self.footer_height, x + w, y + h - self.footer_height))
        
        # Header Divisions (Author | Model | Date | Rev)
        author_w = self.get_author_col_width()
        col1 = x + author_w
        col2 = x + w * 0.70
        col3 = x + w * 0.85
        
        painter.drawLine(QLineF(col1, y, col1, y + self.header_height))
        painter.drawLine(QLineF(col2, y, col2, y + self.header_height))
        painter.drawLine(QLineF(col3, y, col3, y + self.header_height))
        
        # Footer Divisions (Model Page | Name | Number)
        # Allocate width: 20% | 60% | 20%
        f_col1 = x + w * 0.20
        f_col2 = x + w * 0.80
        
        painter.drawLine(QLineF(f_col1, y + h - self.footer_height, f_col1, y + h))
        painter.drawLine(QLineF(f_col2, y + h - self.footer_height, f_col2, y + h))
        
        # Labels are drawn by child QGraphicsTextItems to allow editing interaction if needed
        # But for simpler implementation, we can draw static labels here and values as items.

    def update_theme(self, is_night):
        self.is_night_mode = is_night
        color = Qt.GlobalColor.white if is_night else Qt.GlobalColor.black
        
        # Update text children
        for item in self.childItems():
            if isinstance(item, QGraphicsTextItem):
                item.setDefaultTextColor(color)
        
        self.update()

    def create_text_items(self):
        """Creates the text items for the frame fields."""
        # Cleanup old items if any (though usually we recreate the frame)
        for item in self.childItems():
            if isinstance(item, QGraphicsTextItem) or isinstance(item, EditableTextItem):
                item.setParentItem(None)
                
        x, y, w, h = self.rect.x(), self.rect.y(), self.rect.width(), self.rect.height()
        
        # -- Helpers --
        def add_label_value(label_text, value_text, pos_x, pos_y, width, key=None):
            # Label (small)
            lbl = QGraphicsTextItem(label_text, self)
            font = lbl.font()
            font.setPointSize(8)
            lbl.setFont(font)
            lbl.setPos(pos_x + 2, pos_y + 2)
            
            # Value (User Editable if key provided)
            # Center alignment logic is tricky with QGraphicsTextItem without fixed width container.
            # We'll just position it below label.
            val = EditableTextItem(value_text, self, key=key, model=self.project_model, diagram=self.diagram) if key else QGraphicsTextItem(value_text, self)
            v_font = val.font()
            v_font.setPointSize(10)
            v_font.setBold(True)
            val.setFont(v_font)
            val.setPos(pos_x + 5, pos_y + 18)
            val.setTextWidth(width - 10) # Enforce wrapping/width
            
        # -- Header --
        author_w = self.get_author_col_width()
        model_w = w * 0.70 - author_w
        
        # Author
        add_label_value("Author:", self.project_model.author, x, y, author_w, key="author")
        
        # Model
        add_label_value("Model:", self.project_model.name, x + author_w, y, model_w, key="name") # Project Name
        
        # Date
        add_label_value("Date:", self.project_model.date_created, x + w * 0.70, y, w * 0.15, key="date")
        
        # Rev
        add_label_value("Rev:", self.project_model.version, x + w * 0.85, y, w * 0.15, key="version")

        # -- Footer --
        # Model Page (Node Number)
        add_label_value("Model Page:", self.diagram.node_number, x, y + h - self.footer_height, w * 0.20, key="node_number")
        
        # Name (Diagram Title)
        add_label_value("Name:", self.diagram.title, x + w * 0.20, y + h - self.footer_height, w * 0.60, key="title")
        
        # Number (C-Number / Page Number)
        c_num = self.diagram.c_number if getattr(self.diagram, 'c_number', "") else self.diagram.node_number
        add_label_value("Number:", c_num, x + w * 0.80, y + h - self.footer_height, w * 0.20, key="c_number")
        
        # -- Context Info (Top Right, for A-0 diagrams only) --
        if self.diagram.node_number == "A-0" and self.show_context_info:
            self.create_context_info()
    
    def create_context_info(self):
        """Creates Model Name, Viewpoint, and Purpose text in top right for context diagrams."""
        x, y, w = self.rect.x(), self.rect.y(), self.rect.width()
        
        # Position in top right, below the header
        info_x = x + w * 0.65  # Start at 65% width
        info_y = y + self.header_height + 20  # Below header with padding
        info_width = w * 0.33  # Use 33% of width
        
        line_height = 20
        
        # Determine text color based on current theme
        text_color = Qt.GlobalColor.white if self.is_night_mode else Qt.GlobalColor.black
        
        # Viewpoint
        vp_label = QGraphicsTextItem("Viewpoint:", self)
        font = vp_label.font()
        font.setPointSize(9)
        font.setBold(True)
        vp_label.setFont(font)
        vp_label.setPos(info_x, info_y)
        vp_label.setDefaultTextColor(text_color)
        
        v_font = QFont(font)
        v_font.setBold(False)
        
        vp_value = EditableTextItem(self.project_model.viewpoint, self, key="viewpoint", model=self.project_model)
        vp_value.setFont(v_font)
        vp_value.setPos(info_x, info_y + line_height)
        vp_value.setTextWidth(info_width)
        vp_value.setDefaultTextColor(text_color)
        
        # Purpose
        purpose_label = QGraphicsTextItem("Purpose:", self)
        purpose_label.setFont(font)
        purpose_label.setPos(info_x, info_y + line_height * 3)
        purpose_label.setDefaultTextColor(text_color)
        
        purpose_value = EditableTextItem(self.project_model.purpose, self, key="purpose", model=self.project_model)
        purpose_value.setFont(v_font)
        purpose_value.setPos(info_x, info_y + line_height * 4)
        purpose_value.setTextWidth(info_width)
        purpose_value.setDefaultTextColor(text_color)

class EditableTextItem(QGraphicsTextItem):
    """A text item that updates the model when changed."""
    def __init__(self, text, parent, key, model, diagram=None):
        super().__init__(text, parent)
        self.key = key
        self.model = model
        self.diagram = diagram
        
        # Make editable
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        
    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        # Clear selection
        cursor = self.textCursor()
        cursor.clearSelection()
        self.setTextCursor(cursor)
        self.on_changed()
        
    def keyPressEvent(self, event):
        # Commit on Enter/Return (optional, but good UX)
        if event.key() == Qt.Key.Key_Return and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.clearFocus() # Triggers focusOut
            return
        super().keyPressEvent(event)
        
    def on_changed(self):
        new_text = self.toPlainText()
        if self.key == "author":
            self.model.author = new_text
        elif self.key == "date":
            self.model.date_created = new_text
        elif self.key == "version":
            self.model.version = new_text
        elif self.key == "name":
            self.model.name = new_text
        elif self.key == "purpose":
            self.model.purpose = new_text
        elif self.key == "viewpoint":
            self.model.viewpoint = new_text
        elif self.key == "node_number":
            if self.diagram:
                self.diagram.node_number = new_text
        elif self.key == "title":
            if self.diagram:
                self.diagram.title = new_text
        elif self.key == "c_number":
            if self.diagram:
                self.diagram.c_number = new_text
                
        # Emit signal to notify scene of diagram property changes
        scene = self.scene()
        if scene and hasattr(scene, 'diagram_properties_changed'):
            scene.diagram_properties_changed.emit()
