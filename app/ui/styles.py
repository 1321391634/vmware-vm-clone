from __future__ import annotations


APP_STYLE = """
* { outline: 0; }
QMainWindow, QWidget {
    background: #f3f6f4;
    color: #192a24;
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 13px;
}
QFrame#TopBar { background: #fffefa; border-bottom: 1px solid #d8e2dc; }
QFrame#ActionsBar { background: transparent; }
QFrame#BrandMark { background: #173b34; border-radius: 8px; }
QLabel#BrandGlyph { color: #d7f1df; font-size: 16px; font-weight: 800; }
QLabel#AppTitle { color: #173b34; font-size: 19px; font-weight: 800; }
QLabel#AppSubtitle { color: #728279; font-size: 12px; }
QLabel#Eyebrow { color: #75867c; font-size: 10px; font-weight: 800; letter-spacing: 1px; }
QLabel#Muted { color: #748279; }
QLabel#SectionTitle { color: #1b342b; font-size: 15px; font-weight: 800; }
QLabel#SectionCaption { color: #819088; font-size: 11px; }
QLabel#ConnectionStatus {
    color: #a36525; background: #fff3e5; border: 1px solid #f0d2ae;
    border-radius: 12px; padding: 5px 10px; font-size: 11px; font-weight: 700;
}
QLabel#ConnectionStatus[connected="true"] { color: #147c69; background: #e7f7f0; border-color: #b9e1d3; }
QFrame#InventoryPanel, QFrame#WorkspacePanel { background: #fbfcfa; border-right: 1px solid #dce5df; }
QFrame#WorkspacePanel { border-right: 0; }
QFrame#FilterSurface, QFrame#SelectionSurface, QFrame#FormSurface, QFrame#PreviewBar, QFrame#MetricTile {
    background: #fffefa; border: 1px solid #dce5df; border-radius: 9px;
}
QFrame#MetricTile { background: #f7faf7; border-color: #e1e9e3; }
QLabel#MetricValue { color: #183c33; font-size: 17px; font-weight: 800; }
QLabel#MetricLabel { color: #819088; font-size: 10px; font-weight: 700; }
QLabel#SelectionName { color: #173b34; font-size: 14px; font-weight: 800; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {
    background: #fffefa; border: 1px solid #cad8cf; border-radius: 6px;
    padding: 7px 9px; color: #20342b; selection-background-color: #cdebdc; selection-color: #173b34;
}
QComboBox[resourceSelector="true"] { padding-right: 32px; }
QComboBox::drop-down { background: #f0f8f3; border-left: 1px solid #d7e6dc; border-radius: 0 6px 6px 0; width: 28px; }
QComboBox::down-arrow { width: 0; height: 0; border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid #168c78; }
QComboBox QAbstractItemView { background: #fffefa; border: 1px solid #b8cfc0; padding: 4px; selection-background-color: #d9eee3; selection-color: #173b34; outline: 0; }
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QTextEdit:hover { border-color: #9eb9aa; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus { border: 1px solid #168c78; background: #ffffff; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QTextEdit:disabled { color: #a1aea6; background: #f0f4f1; }
QPushButton { background: #fffefa; border: 1px solid #cbd8d0; border-radius: 6px; padding: 7px 12px; color: #315047; font-weight: 600; }
QPushButton:hover { background: #eef8f2; border-color: #84b7a0; }
QPushButton:pressed { background: #dcefe5; }
QPushButton:disabled { color: #a6b2ab; background: #f1f4f1; border-color: #e0e7e1; }
QPushButton#PrimaryButton { background: #168c78; border-color: #168c78; color: #ffffff; font-weight: 800; }
QPushButton#PrimaryButton:hover { background: #0f7564; border-color: #0f7564; }
QPushButton#QuietButton { border-color: transparent; background: transparent; color: #587267; }
QPushButton#QuietButton:hover { background: #eaf4ed; border-color: transparent; }
QPushButton#DangerButton { color: #b34b3a; }
QListWidget#StepList { background: #f5f8f5; border: 1px solid #dce5df; border-radius: 9px; padding: 7px; }
QListWidget#StepList::item { padding: 12px 10px; margin: 2px 0; border-radius: 7px; color: #73827a; }
QListWidget#StepList::item:hover { background: #eaf3ed; color: #315047; }
QListWidget#StepList::item:selected { background: #dcefe5; color: #166956; font-weight: 800; }
QTableWidget { background: #fffefa; border: 1px solid #dce5df; border-radius: 8px; gridline-color: #edf2ee; alternate-background-color: #f8faf8; selection-background-color: #d9eee3; selection-color: #173b34; }
QTableWidget::item { padding: 7px 5px; }
QHeaderView::section { background: #f1f6f2; color: #6c7e73; padding: 8px 7px; border: 0; border-bottom: 1px solid #dce5df; font-size: 11px; font-weight: 800; }
QGroupBox { background: #fffefa; border: 1px solid #dce5df; border-radius: 9px; margin-top: 14px; padding: 18px 13px 13px; font-weight: 800; color: #29463a; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; background: #fffefa; color: #315047; }
QProgressBar { border: 0; border-radius: 3px; background: #e4eee7; height: 6px; text-align: center; }
QProgressBar::chunk { background: #168c78; border-radius: 3px; }
QCheckBox, QRadioButton { spacing: 7px; color: #476057; }
QCheckBox::indicator, QRadioButton::indicator { width: 15px; height: 15px; }
QStatusBar { background: #fffefa; border-top: 1px solid #dce5df; color: #6f8177; }
QScrollArea { background: transparent; border: 0; }
QScrollArea#PreviewCardsArea { background: transparent; border: 0; }
QWidget#PreviewCardsContent { background: transparent; }
QFrame#PreviewItemCard { background: #fffefa; border: 1px solid #dce5df; border-radius: 8px; }
QLabel#PreviewSequence { color: #ffffff; background: #168c78; border-radius: 10px; padding: 3px 8px; font-weight: 800; }
QLabel#PreviewCardTitle { color: #1b342b; font-weight: 800; }
QLabel#PreviewPower { color: #587267; background: #f1f6f2; border-radius: 5px; padding: 4px 8px; }
QLabel#PreviewFieldLabel { color: #75867c; font-size: 10px; font-weight: 800; }
QLabel#PreviewReadonly { color: #315047; background: #f5f8f5; border: 1px solid #e1e9e3; border-radius: 6px; padding: 7px 9px; }
QToolTip { background: #173b34; color: #ffffff; border: 0; padding: 5px 7px; }
"""
