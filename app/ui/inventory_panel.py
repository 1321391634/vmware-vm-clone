from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import InventorySnapshot, VmRecord


class InventoryPanel(QFrame):
    vm_selected = Signal(object)
    refresh_requested = Signal()

    HEADERS = ["虚拟机", "类型", "电源", "主机", "集群", "IP", "存储", "文件夹", "Tools"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("InventoryPanel")
        self.records: tuple[VmRecord, ...] = ()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 14, 14)
        layout.setSpacing(11)

        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.setSpacing(1)
        eyebrow = QLabel("INVENTORY")
        eyebrow.setObjectName("Eyebrow")
        title = QLabel("虚拟机资源")
        title.setObjectName("SectionTitle")
        caption = QLabel("选择一个源对象开始批量克隆")
        caption.setObjectName("SectionCaption")
        title_block.addWidget(eyebrow)
        title_block.addWidget(title)
        title_block.addWidget(caption)
        header.addLayout(title_block)
        header.addStretch()
        refresh = QPushButton("刷新")
        refresh.setObjectName("QuietButton")
        refresh.setToolTip("刷新当前 vCenter 资源")
        refresh.clicked.connect(self.refresh_requested)
        header.addWidget(refresh)
        layout.addLayout(header)

        metrics = QHBoxLayout()
        metrics.setSpacing(7)
        self.total_metric = self._metric(metrics, "0", "全部")
        self.template_metric = self._metric(metrics, "0", "模板")
        self.powered_on_metric = self._metric(metrics, "0", "运行中")
        layout.addLayout(metrics)

        filter_surface = QFrame()
        filter_surface.setObjectName("FilterSurface")
        filters = QVBoxLayout(filter_surface)
        filters.setContentsMargins(10, 10, 10, 10)
        filters.setSpacing(7)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索名称、UUID、IP、主机、集群、存储或文件夹")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filters)
        search_row.addWidget(self.search, 1)
        filters.addLayout(search_row)
        filter_row = QHBoxLayout()
        self.type_filter = QComboBox()
        self.type_filter.addItems(["全部类型", "模板", "普通虚拟机"])
        self.type_filter.currentTextChanged.connect(self._apply_filters)
        self.power_filter = QComboBox()
        self.power_filter.addItems(["全部电源", "poweredOn", "poweredOff", "suspended"])
        self.power_filter.currentTextChanged.connect(self._apply_filters)
        filter_row.addWidget(self.type_filter)
        filter_row.addWidget(self.power_filter)
        filter_row.addStretch()
        filters.addLayout(filter_row)
        layout.addWidget(filter_surface)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setObjectName("InventoryTable")
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setMinimumSectionSize(70)
        self.table.itemSelectionChanged.connect(self._emit_selection)
        layout.addWidget(self.table, 1)

        self.empty_label = QLabel("连接 vCenter 后加载虚拟机资源")
        self.empty_label.setObjectName("Muted")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setVisible(True)
        layout.addWidget(self.empty_label)

        selection = QFrame()
        selection.setObjectName("SelectionSurface")
        selection_layout = QVBoxLayout(selection)
        selection_layout.setContentsMargins(11, 9, 11, 9)
        selection_layout.setSpacing(2)
        selection_caption = QLabel("当前源对象")
        selection_caption.setObjectName("Eyebrow")
        self.selection_name = QLabel("尚未选择")
        self.selection_name.setObjectName("SelectionName")
        self.selection_meta = QLabel("从上方列表选择模板或普通虚拟机")
        self.selection_meta.setObjectName("SectionCaption")
        selection_layout.addWidget(selection_caption)
        selection_layout.addWidget(self.selection_name)
        selection_layout.addWidget(self.selection_meta)
        layout.addWidget(selection)

    @staticmethod
    def _metric(container: QHBoxLayout, value: str, label: str) -> QLabel:
        tile = QFrame()
        tile.setObjectName("MetricTile")
        tile_layout = QVBoxLayout(tile)
        tile_layout.setContentsMargins(9, 7, 9, 7)
        tile_layout.setSpacing(1)
        value_label = QLabel(value)
        value_label.setObjectName("MetricValue")
        label_label = QLabel(label)
        label_label.setObjectName("MetricLabel")
        tile_layout.addWidget(value_label)
        tile_layout.addWidget(label_label)
        container.addWidget(tile, 1)
        return value_label

    def set_snapshot(self, snapshot: InventorySnapshot):
        self.records = snapshot.vms
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        template_count = sum(vm.is_template for vm in self.records)
        powered_on_count = sum(vm.power_state == "poweredOn" for vm in self.records)
        self.total_metric.setText(str(len(self.records)))
        self.template_metric.setText(str(template_count))
        self.powered_on_metric.setText(str(powered_on_count))
        for row, vm in enumerate(self.records):
            self.table.insertRow(row)
            values = [
                vm.name,
                "模板" if vm.is_template else "普通虚拟机",
                vm.power_state,
                vm.host_name,
                vm.cluster_name,
                vm.ip_address,
                ", ".join(vm.datastores),
                vm.folder_path,
                vm.tools_status,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                item.setData(Qt.UserRole, vm.moid)
                self.table.setItem(row, column, item)
        self.table.setSortingEnabled(True)
        self._apply_filters()
        self.empty_label.setVisible(not bool(self.records))
        self._clear_selection_summary()

    def clear(self):
        self.records = ()
        self.table.setRowCount(0)
        self.total_metric.setText("0")
        self.template_metric.setText("0")
        self.powered_on_metric.setText("0")
        self.empty_label.setText("连接 vCenter 后加载虚拟机资源")
        self.empty_label.setVisible(True)
        self._clear_selection_summary()

    def _clear_selection_summary(self):
        self.selection_name.setText("尚未选择")
        self.selection_meta.setText("从上方列表选择模板或普通虚拟机")

    def _apply_filters(self):
        query = self.search.text().strip().casefold()
        type_filter = self.type_filter.currentText()
        power_filter = self.power_filter.currentText()
        records_by_id = {record.moid: record for record in self.records}
        visible = 0
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            moid = item.data(Qt.UserRole) if item else ""
            vm = records_by_id.get(moid)
            if vm is None:
                self.table.setRowHidden(row, True)
                continue
            haystack = " ".join(
                (vm.name, vm.uuid, vm.ip_address, vm.host_name, vm.cluster_name, " ".join(vm.datastores), vm.folder_path)
            ).casefold()
            type_match = type_filter == "全部类型" or (type_filter == "模板" and vm.is_template) or (type_filter == "普通虚拟机" and not vm.is_template)
            power_match = power_filter == "全部电源" or power_filter == vm.power_state
            matches = (not query or query in haystack) and type_match and power_match
            self.table.setRowHidden(row, not matches)
            visible += matches
        self.empty_label.setVisible(not self.records or visible == 0)
        if self.records and visible == 0:
            self.empty_label.setText("没有匹配的虚拟机")
        elif not self.records:
            self.empty_label.setText("连接 vCenter 后加载虚拟机资源")

    def _emit_selection(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        item = self.table.item(row, 0)
        moid = item.data(Qt.UserRole) if item else ""
        vm = next((record for record in self.records if record.moid == moid), None)
        if vm:
            self.selection_name.setText(vm.name)
            kind = "模板" if vm.is_template else "普通虚拟机"
            self.selection_meta.setText(f"{kind} · {vm.power_state} · {vm.cpu_count} vCPU · {max(1, round(vm.memory_mb / 1024))} GB")
            self.vm_selected.emit(vm)

