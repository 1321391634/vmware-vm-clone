from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QObject, QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import CloneItem, ClonePlan, DiskRequest, InventorySnapshot
from .widgets import HostnameLineEdit, SearchableComboBox


class DiskEditorDialog(QDialog):
    def __init__(self, disks: tuple[DiskRequest, ...], parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑新增硬盘")
        self.setMinimumWidth(360)
        self._rows: list[tuple[QDoubleSpinBox, QComboBox, QWidget]] = []

        layout = QVBoxLayout(self)
        self._form_widget = QWidget()
        self._form = QFormLayout(self._form_widget)
        layout.addWidget(self._form_widget)

        controls = QHBoxLayout()
        add_button = QPushButton("添加硬盘")
        remove_button = QPushButton("移除最后一块")
        add_button.clicked.connect(lambda: self._add_row())
        remove_button.clicked.connect(self._remove_row)
        controls.addWidget(add_button)
        controls.addWidget(remove_button)
        controls.addStretch()
        layout.addLayout(controls)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for disk in disks:
            self._add_row(disk.size, disk.unit)

    def _add_row(self, size: float = 100, unit: str = "GB") -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        size_box = QDoubleSpinBox()
        size_box.setRange(0.01, 1048576)
        size_box.setDecimals(2)
        size_box.setValue(size)
        unit_box = QComboBox()
        unit_box.addItems(["GB", "TB"])
        unit_box.setCurrentText(unit)
        row_layout.addWidget(size_box)
        row_layout.addWidget(unit_box)
        row_layout.addStretch()
        self._rows.append((size_box, unit_box, row))
        self._form.addRow(f"磁盘 {len(self._rows)}", row)

    def _remove_row(self) -> None:
        if not self._rows:
            return
        _, _, row = self._rows.pop()
        self._form.removeRow(row)
        row.deleteLater()

    def disks(self) -> tuple[DiskRequest, ...]:
        return tuple(
            DiskRequest(size=size.value(), unit=unit.currentText())
            for size, unit, _ in self._rows
        )


class PreviewEditor(QObject):
    """Keeps per-row drafts and renders the editable batch preview."""

    items_changed = Signal(object)

    COLUMNS = ("名称", "Hostname", "IP", "计算资源", "存储", "端口组", "CPU", "内存", "新增磁盘", "电源")
    DIRTY_FIELDS = (
        "vm_name",
        "hostname",
        "ip_address",
        "datastore_name",
        "portgroup_name",
        "cpu_count",
        "memory_gb",
        "disk_requests",
    )

    def __init__(self, table: QTableWidget, parent=None, *, card_layout=None):
        super().__init__(parent or table)
        self.table = table
        self.card_layout = card_layout
        self.snapshot = InventorySnapshot()
        self.plan: ClonePlan | None = None
        self._drafts: dict[int, CloneItem] = {}
        self._dirty_fields: dict[int, set[str]] = {}
        self._sequence_order: tuple[int, ...] = ()
        self._cards: dict[int, QFrame] = {}
        self._card_widgets: dict[int, dict[str, QWidget]] = {}

    def clear(self) -> None:
        self.plan = None
        self._drafts.clear()
        self._dirty_fields.clear()
        self._sequence_order = ()
        self.table.setRowCount(0)
        self._clear_cards()

    def items(self) -> tuple[CloneItem, ...]:
        return tuple(self._drafts[sequence] for sequence in self._sequence_order if sequence in self._drafts)

    def items_for_plan(self, plan: ClonePlan) -> tuple[CloneItem, ...]:
        """Merge dirty row fields onto a freshly rebuilt batch plan."""
        base_items = tuple(self._coerce_item(plan, item) for item in plan.items)
        if tuple(item.sequence for item in base_items) != self._sequence_order:
            return ()
        merged = []
        for base_item in base_items:
            draft = base_item
            previous = self._drafts.get(base_item.sequence)
            for field in self._dirty_fields.get(base_item.sequence, set()):
                if previous is not None:
                    draft = replace(draft, **{field: getattr(previous, field)})
            merged.append(draft)
        return tuple(merged)

    def set_plan(
        self,
        plan: ClonePlan,
        snapshot: InventorySnapshot,
        *,
        preserve_drafts: bool = True,
    ) -> None:
        old_drafts = self._drafts
        old_dirty = self._dirty_fields
        self.plan = plan
        self.snapshot = snapshot
        normalized_items = tuple(self._coerce_item(plan, item) for item in plan.items)
        self._sequence_order = tuple(item.sequence for item in normalized_items)
        self._drafts = {}
        self._dirty_fields = {}
        for item in normalized_items:
            draft = item
            dirty = set()
            if preserve_drafts and item.sequence in old_drafts:
                previous = old_drafts[item.sequence]
                dirty = set(old_dirty.get(item.sequence, set()))
                for field in dirty:
                    draft = replace(draft, **{field: getattr(previous, field)})
            self._drafts[item.sequence] = draft
            self._dirty_fields[item.sequence] = dirty
        self._render()

    @staticmethod
    def _coerce_item(plan: ClonePlan, item) -> CloneItem:
        if isinstance(item, CloneItem):
            return item
        return CloneItem(
            sequence=int(getattr(item, "sequence", 1)),
            vm_name=str(getattr(item, "vm_name", "")),
            hostname=str(getattr(item, "hostname", "")),
            ip_address=getattr(item, "ip_address", None),
            datastore_name=str(getattr(item, "datastore_name", getattr(plan, "datastore_name", ""))),
            portgroup_name=getattr(item, "portgroup_name", getattr(plan, "portgroup_name", None)),
            cpu_count=int(getattr(item, "cpu_count", getattr(plan, "cpu_count", 1))),
            memory_gb=int(getattr(item, "memory_gb", getattr(plan, "memory_gb", 1))),
            disk_requests=tuple(getattr(item, "disk_requests", getattr(plan, "disk_requests", ()))),
        )

    def _render(self) -> None:
        plan = self.plan
        if plan is None:
            self.clear()
            return
        self.table.setRowCount(0)
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(list(self.COLUMNS))
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideNone)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)

        for row, sequence in enumerate(self._sequence_order):
            self.table.insertRow(row)
            item = self._drafts[sequence]
            self._render_row(row, sequence, item)

        self.table.resizeColumnsToContents()
        minimum_widths = (150, 150, 150, 140, 220, 220, 130, 130, 170, 120)
        for column, minimum_width in enumerate(minimum_widths):
            self.table.setColumnWidth(column, max(minimum_width, self.table.columnWidth(column)))
        self._render_cards()

    def card_for_sequence(self, sequence: int) -> QFrame | None:
        return self._cards.get(sequence)

    def _clear_cards(self) -> None:
        self._cards.clear()
        self._card_widgets.clear()
        if self.card_layout is None:
            return
        while self.card_layout.count():
            layout_item = self.card_layout.takeAt(0)
            widget = layout_item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render_cards(self) -> None:
        if self.card_layout is None or self.plan is None:
            return
        self._clear_cards()
        for sequence in self._sequence_order:
            card = self._build_card(sequence, self._drafts[sequence])
            self._cards[sequence] = card
            self.card_layout.addWidget(card)
        self.card_layout.addStretch(1)

    def _build_card(self, sequence: int, item: CloneItem) -> QFrame:
        plan = self.plan
        card = QFrame()
        card.setObjectName("PreviewItemCard")
        card.setMinimumHeight(220)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        outer = QVBoxLayout(card)
        outer.setContentsMargins(12, 9, 12, 10)
        outer.setSpacing(7)

        header = QHBoxLayout()
        sequence_label = QLabel(f"{sequence:02d}")
        sequence_label.setObjectName("PreviewSequence")
        title = QLabel(f"克隆任务 {sequence}")
        title.setObjectName("PreviewCardTitle")
        power_label = QLabel("完成后开机" if plan.power_on_after else "完成后关机")
        power_label.setObjectName("PreviewPower")
        header.addWidget(sequence_label)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(power_label)
        outer.addLayout(header)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(9)
        grid.setVerticalSpacing(5)
        widgets: dict[str, QWidget] = {"power": power_label}

        name_editor = self._line_editor(sequence, "vm_name", item.vm_name)
        hostname_editor = self._hostname_editor(sequence, item.hostname)
        ip_editor = self._line_editor(sequence, "ip_address", item.ip_address or "")
        compute_label = QLabel(plan.compute_resource.name)
        compute_label.setObjectName("PreviewReadonly")
        compute_label.setWordWrap(True)
        compute_label.setMinimumHeight(34)
        storage_editor = self._datastore_editor(sequence, item.datastore_name)
        portgroup_editor = self._portgroup_editor(sequence, item.portgroup_name)
        cpu_editor = self._spin_editor(sequence, "cpu_count", item.cpu_count, 512, " vCPU")
        memory_editor = self._spin_editor(sequence, "memory_gb", item.memory_gb, 65536, " GB")
        disk_button = self._disk_button(sequence, item.disk_requests)

        widgets.update(
            {
                "vm_name": name_editor,
                "hostname": hostname_editor,
                "ip_address": ip_editor,
                "compute_resource": compute_label,
                "datastore_name": storage_editor,
                "portgroup_name": portgroup_editor,
                "cpu_count": cpu_editor,
                "memory_gb": memory_editor,
                "disk_requests": disk_button,
            }
        )
        fields = (
            ("名称", name_editor),
            ("Hostname", hostname_editor),
            ("IP", ip_editor),
            ("计算资源", compute_label),
            ("存储", storage_editor),
            ("端口组", portgroup_editor),
            ("CPU", cpu_editor),
            ("内存", memory_editor),
            ("新增硬盘", disk_button),
        )
        for index, (label_text, widget) in enumerate(fields):
            row, column = divmod(index, 3)
            label = QLabel(label_text)
            label.setObjectName("PreviewFieldLabel")
            grid.addWidget(label, row * 2, column)
            grid.addWidget(widget, row * 2 + 1, column)
        for column in range(3):
            grid.setColumnStretch(column, 1)
        outer.addLayout(grid)
        self._card_widgets[sequence] = widgets
        return card

    def _render_row(self, row: int, sequence: int, item: CloneItem) -> None:
        plan = self.plan
        if plan is None:
            return
        source_vm = getattr(plan, "source_vm", None)
        source_datastores = getattr(source_vm, "datastores", ()) or ()
        source_cpu = getattr(source_vm, "cpu_count", 0)
        source_memory_gb = max(1, round(getattr(source_vm, "memory_mb", 0) / 1024))
        datastore_origin = "继承模板" if (
            plan.inheritance.get("datastore") == "source"
            and source_datastores
            and item.datastore_name == source_datastores[0]
        ) else "已指定"
        cpu_origin = "继承模板" if (
            plan.inheritance.get("cpu") == "source"
            and (not source_cpu or item.cpu_count == source_cpu)
        ) else "已覆盖"
        memory_origin = "继承模板" if (
            plan.inheritance.get("memory") == "source"
            and (not source_memory_gb or item.memory_gb == source_memory_gb)
        ) else "已覆盖"
        disk_text = self._disk_text(item.disk_requests)
        values = (
            item.vm_name,
            item.hostname,
            item.ip_address or "DHCP",
            plan.compute_resource.name,
            f"{item.datastore_name}（{datastore_origin}）",
            item.portgroup_name or "继承源网卡（保留源网卡）",
            f"{item.cpu_count} vCPU（{cpu_origin}）",
            f"{item.memory_gb} GB（{memory_origin}）",
            disk_text,
            "完成后开机" if plan.power_on_after else "完成后关机",
        )
        for column, value in enumerate(values):
            cell = QTableWidgetItem(str(value))
            cell.setToolTip(str(value))
            self.table.setItem(row, column, cell)

        self._set_line_editor(row, 0, sequence, "vm_name", item.vm_name)
        self._set_hostname_editor(row, 1, sequence, item.hostname)
        self._set_line_editor(row, 2, sequence, "ip_address", item.ip_address or "")
        self._set_datastore_editor(row, 4, sequence, item.datastore_name)
        self._set_portgroup_editor(row, 5, sequence, item.portgroup_name)
        self._set_spin_editor(row, 6, sequence, "cpu_count", item.cpu_count, 512, " vCPU")
        self._set_spin_editor(row, 7, sequence, "memory_gb", item.memory_gb, 65536, " GB")
        self.table.setCellWidget(row, 8, self._disk_button(sequence, item.disk_requests))

    @staticmethod
    def _disk_text(disks: tuple[DiskRequest, ...]) -> str:
        return ", ".join(f"{disk.size:g} {disk.unit}" for disk in disks) or "无新增"

    def _set_line_editor(self, row, column, sequence, field, value) -> None:
        self.table.setCellWidget(row, column, self._line_editor(sequence, field, value))

    def _set_hostname_editor(self, row, column, sequence, value) -> None:
        self.table.setCellWidget(row, column, self._hostname_editor(sequence, value))

    def _set_datastore_editor(self, row, column, sequence, value) -> None:
        self.table.setCellWidget(row, column, self._datastore_editor(sequence, value))

    def _set_portgroup_editor(self, row, column, sequence, value) -> None:
        self.table.setCellWidget(row, column, self._portgroup_editor(sequence, value))

    def _set_spin_editor(self, row, column, sequence, field, value, maximum, suffix) -> None:
        self.table.setCellWidget(
            row,
            column,
            self._spin_editor(sequence, field, value, maximum, suffix),
        )

    def _line_editor(self, sequence: int, field: str, value) -> QLineEdit:
        editor = QLineEdit(str(value or ""))
        editor.setToolTip("编辑后按回车或离开输入框完成校验")
        editor.textChanged.connect(
            lambda text, seq=sequence, key=field: self._commit(seq, key, text)
        )
        return editor

    def _hostname_editor(self, sequence: int, value) -> HostnameLineEdit:
        editor = HostnameLineEdit()
        editor.setText(str(value or ""))
        editor.textChanged.connect(
            lambda text, seq=sequence: self._commit(seq, "hostname", text)
        )
        return editor

    def _datastore_editor(self, sequence: int, value) -> SearchableComboBox:
        names = list(self.snapshot.datastores)
        if value and value not in names:
            names.insert(0, value)
        editor = SearchableComboBox()
        editor.set_items([(name, name) for name in names])
        self._select_data(editor, value)
        editor.currentTextChanged.connect(
            lambda _text, combo=editor, seq=sequence: self._commit(
                seq, "datastore_name", combo.selected_data() or combo.currentText().strip()
            )
        )
        return editor

    def _portgroup_editor(self, sequence: int, value) -> SearchableComboBox:
        names = [("继承源网卡", None), *((name, name) for name in self.snapshot.portgroups)]
        editor = SearchableComboBox()
        editor.set_items(names)
        self._select_data(editor, value)
        editor.currentTextChanged.connect(
            lambda _text, combo=editor, seq=sequence: self._commit(
                seq, "portgroup_name", combo.selected_data()
            )
        )
        return editor

    @staticmethod
    def _select_data(combo: SearchableComboBox, value) -> None:
        index = combo.findData(value, Qt.UserRole)
        if index >= 0:
            with QSignalBlocker(combo):
                combo.setCurrentIndex(index)

    def _spin_editor(
        self,
        sequence: int,
        field: str,
        value,
        maximum: int,
        suffix: str,
    ) -> QSpinBox:
        editor = QSpinBox()
        editor.setRange(1, maximum)
        editor.setValue(max(1, int(value)))
        editor.setSuffix(suffix)
        editor.valueChanged.connect(
            lambda number, seq=sequence, key=field: self._commit(seq, key, number)
        )
        return editor

    def _disk_button(self, sequence: int, disks: tuple[DiskRequest, ...]) -> QPushButton:
        button = QPushButton(self._disk_text(disks))
        button.setToolTip("编辑此台虚拟机的新增硬盘")
        button.clicked.connect(lambda _checked=False, seq=sequence: self._edit_disks(seq))
        return button

    def _commit(self, sequence: int, field: str, value) -> None:
        if sequence not in self._drafts:
            return
        if field == "ip_address":
            value = str(value).strip() or None
        elif field in {"vm_name", "hostname", "datastore_name"}:
            value = str(value).strip()
        self._drafts[sequence] = replace(self._drafts[sequence], **{field: value})
        self._dirty_fields.setdefault(sequence, set()).add(field)
        self.items_changed.emit(self.items())

    def _edit_disks(self, sequence: int) -> None:
        dialog = DiskEditorDialog(self._drafts[sequence].disk_requests, self.table)
        if dialog.exec() != QDialog.Accepted:
            return
        disks = dialog.disks()
        self._drafts[sequence] = replace(self._drafts[sequence], disk_requests=disks)
        self._dirty_fields.setdefault(sequence, set()).add("disk_requests")
        row = self._sequence_order.index(sequence)
        button = self.table.cellWidget(row, 8)
        if button is not None:
            button.setText(self._disk_text(disks))
        cell = self.table.item(row, 8)
        if cell is not None:
            cell.setText(self._disk_text(disks))
            cell.setToolTip(self._disk_text(disks))
        card_button = self._card_widgets.get(sequence, {}).get("disk_requests")
        if card_button is not None:
            card_button.setText(self._disk_text(disks))
        self.items_changed.emit(self.items())
