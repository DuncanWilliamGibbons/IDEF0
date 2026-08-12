"""Night mode for the application chrome.

Applied to the main window, from where Qt cascades it to every descendant, so a
table opened after the toggle is themed without anything having to remember it.

The tables are the reason this is a stylesheet rather than a palette. A
QTableWidget draws its every-other-row shading from the AlternateBase palette
role, which a `background-color` rule does not touch: the rows stayed the
default near-white while `color: #ffffff` cascaded into the item text, leaving
half of every table white on white. Any widget that draws text on a base of its
own - tables, trees, line edits, text edits - therefore needs its background
named here explicitly, not just inherited.
"""

# Text is white on all of these, so keep every one of them dark enough for it.
# Contrast against #ffffff: base 12.6:1, alternating row 9.7:1, header 8.9:1 -
# all comfortably past the 4.5:1 that WCAG AA asks for body text.
BASE = "#2b2b2b"
ALTERNATE_ROW = "#383838"
HEADER = "#3f3f3f"
FIELD = "#444444"
BORDER = "#555555"
GRID = "#4a4a4a"
SELECTION = "#0d5c8c"
TEXT = "#ffffff"

DARK_STYLESHEET = f"""
    QMainWindow, QWidget {{ background-color: {BASE}; color: {TEXT}; }}
    QGroupBox {{ color: {TEXT}; border: 1px solid {BORDER}; margin-top: 6px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 3px; }}
    QLabel {{ color: {TEXT}; }}
    QSpinBox, QComboBox, QCheckBox {{ color: {TEXT}; background-color: {FIELD}; }}
    QLineEdit, QTextEdit, QPlainTextEdit {{
        color: {TEXT}; background-color: {FIELD};
        border: 1px solid {BORDER}; selection-background-color: {SELECTION};
    }}
    QPushButton {{ background-color: {BORDER}; color: {TEXT}; }}
    QGraphicsView {{ background-color: #1e1e1e; border: none; }}
    QMenuBar {{ background-color: {BASE}; color: {TEXT}; }}
    QMenuBar::item:selected {{ background-color: {FIELD}; }}
    QMenu {{ background-color: {BASE}; color: {TEXT}; border: 1px solid {BORDER}; }}
    QMenu::item:selected {{ background-color: {FIELD}; }}
    QTabWidget::pane {{ border: 1px solid {GRID}; }}
    QTabBar::tab {{ background: #333333; color: {TEXT}; padding: 5px; }}
    QTabBar::tab:selected {{ background: {BORDER}; }}

    /* Tables and trees: the every-other-row shade has to be named, or it stays
       the default near-white and the white item text is unreadable on it. */
    QTableView, QTableWidget, QTreeView, QTreeWidget, QListView {{
        background-color: {BASE};
        alternate-background-color: {ALTERNATE_ROW};
        color: {TEXT};
        gridline-color: {GRID};
        border: 1px solid {BORDER};
        selection-background-color: {SELECTION};
        selection-color: {TEXT};
    }}
    QTableView::item, QTableWidget::item,
    QTreeView::item, QTreeWidget::item {{ color: {TEXT}; }}
    QTableView::item:selected, QTableWidget::item:selected,
    QTreeView::item:selected, QTreeWidget::item:selected {{
        background-color: {SELECTION}; color: {TEXT};
    }}
    QHeaderView {{ background-color: {HEADER}; }}
    QHeaderView::section {{
        background-color: {HEADER}; color: {TEXT};
        border: 1px solid {GRID}; padding: 4px;
    }}
    QTableCornerButton::section {{
        background-color: {HEADER}; border: 1px solid {GRID};
    }}
    QScrollBar:vertical, QScrollBar:horizontal {{ background: {BASE}; }}
    QScrollBar::handle {{ background: {BORDER}; border-radius: 3px; }}
    QToolTip {{
        background-color: {HEADER}; color: {TEXT}; border: 1px solid {BORDER};
    }}
"""

# Pass and fail marks. The dark-mode pair is not the light-mode pair dimmed:
# Qt's darkGreen (#008000) reads at 2.3:1 on #2b2b2b, well under legible.
PASS_COLOUR = {"light": "#1b7f3b", "dark": "#4ade80"}
FAIL_COLOUR = {"light": "#c62828", "dark": "#f87171"}


def status_colour(passed: bool, is_night: bool) -> str:
    """The colour a PASS/FAIL mark is drawn in, for the theme in force."""
    palette = PASS_COLOUR if passed else FAIL_COLOUR
    return palette["dark" if is_night else "light"]
