from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QComboBox, QCompleter, QFrame, QLineEdit, QVBoxLayout


class SearchableComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ResourceSelector")
        self.setProperty("resourceSelector", True)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(16)
        self.setMaxVisibleItems(12)
        self.setMinimumHeight(36)
        completer = QCompleter(self.model(), self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.setMaxVisibleItems(12)
        self.setCompleter(completer)
        self.view().setMinimumWidth(280)
        self.view().setMinimumHeight(34)
        self.lineEdit().setClearButtonEnabled(True)

    def set_items(self, items: list[tuple[str, object]]) -> None:
        self.blockSignals(True)
        self.clear()
        for label, data in items:
            self.addItem(label, data)
        self.setCurrentIndex(0 if items else -1)
        self.blockSignals(False)

    def selected_data(self):
        index = self.findText(self.currentText(), Qt.MatchExactly)
        return self.itemData(index) if index >= 0 else None


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(18, 16, 18, 16)
        self.layout.setSpacing(12)


class HostnameLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setValidator(QRegularExpressionValidator(r"[A-Za-z0-9][A-Za-z0-9-]{0,61}[A-Za-z0-9]?", self))
        self.setPlaceholderText("仅英文字母、数字和连字符")
