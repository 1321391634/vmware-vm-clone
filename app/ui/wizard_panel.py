from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import (
    CloneForm,
    ClonePlan,
    ComputeResource,
    DiskRequest,
    InventorySnapshot,
    NetworkConfig,
    VmRecord,
)
from app.domain.preflight import PreflightValidator
from app.domain.planning import apply_clone_item_edits
from app.domain.validation import ipv4_range_end, validate_hostname
from .preview_editor import PreviewEditor
from .widgets import Card, HostnameLineEdit, SearchableComboBox


class WizardPanel(QWidget):
    """Seven-step clone form with a continuously rebuilt domain plan preview."""

    plan_changed = Signal(object)
    execute_requested = Signal(object)

    STEP_TITLES = (
        "源虚拟机与数量",
        "计算资源与存储",
        "自定义规范",
        "名称与 hostname",
        "网络与地址",
        "CPU、内存与磁盘",
        "预览、校验与执行",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WizardPanel")
        self.snapshot = InventorySnapshot()
        self.source_vm: VmRecord | None = None
        self.current_plan: ClonePlan | None = None
        self.validator = PreflightValidator()
        self.disk_rows: list[tuple[QDoubleSpinBox, QComboBox, QWidget]] = []
        self._auto_vm_name = True
        self._auto_hostname = True
        self._build_ui()
        self._connect_form_signals()
        self._refresh_preview()

    def page_count(self) -> int:
        return self.pages.count()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 16)
        outer.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(9)
        heading = QVBoxLayout()
        heading.setSpacing(1)
        eyebrow = QLabel("CLONE WORKSPACE")
        eyebrow.setObjectName("Eyebrow")
        self.page_title = QLabel(self.STEP_TITLES[0])
        self.page_title.setObjectName("SectionTitle")
        self.page_hint = QLabel("先选择源虚拟机，再填写批量克隆参数")
        self.page_hint.setObjectName("SectionCaption")
        heading.addWidget(eyebrow)
        heading.addWidget(self.page_title)
        heading.addWidget(self.page_hint)
        header.addLayout(heading)
        header.addStretch()
        self.preview_status = QLabel("等待源虚拟机")
        self.preview_status.setObjectName("ConnectionStatus")
        header.addWidget(self.preview_status)
        outer.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("WizardSplitter")
        splitter.setChildrenCollapsible(False)
        self.steps = QListWidget()
        self.steps.setObjectName("StepList")
        self.steps.setFixedWidth(205)
        self.steps.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.steps.setTextElideMode(Qt.ElideRight)
        for index, title in enumerate(self.STEP_TITLES):
            item = QListWidgetItem(f"{index + 1:02d}  {title}")
            item.setData(Qt.UserRole, index)
            self.steps.addItem(item)
        self.steps.setCurrentRow(0)
        self.steps.currentRowChanged.connect(self._show_page)
        splitter.addWidget(self.steps)

        self.pages = QStackedWidget()
        self.pages.setObjectName("FormPages")
        self.pages.setMinimumHeight(500)
        self.pages.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.pages.addWidget(self._build_source_page())
        self.pages.addWidget(self._build_target_page())
        self.pages.addWidget(self._build_customization_page())
        self.pages.addWidget(self._build_identity_page())
        self.pages.addWidget(self._build_network_page())
        self.pages.addWidget(self._build_hardware_page())
        self.pages.addWidget(self._build_review_page())
        page_scroll = QScrollArea()
        page_scroll.setObjectName("FormScrollArea")
        page_scroll.setFrameShape(QFrame.NoFrame)
        page_scroll.setWidgetResizable(True)
        page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page_scroll.setWidget(self.pages)
        splitter.addWidget(page_scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, 1)

        preview_card = QFrame()
        preview_card.setObjectName("PreviewBar")
        preview_card.setMinimumHeight(300)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(11, 9, 11, 9)
        preview_layout.setSpacing(6)
        preview_header = QHBoxLayout()
        preview_title = QLabel("批次预览")
        preview_title.setObjectName("SectionTitle")
        self.preview_count = QLabel("0 台")
        self.preview_count.setObjectName("SectionCaption")
        self.preview_target = QLabel("等待参数")
        self.preview_target.setObjectName("SectionCaption")
        preview_header.addWidget(preview_title)
        preview_header.addWidget(self.preview_count)
        preview_header.addSpacing(7)
        preview_header.addWidget(self.preview_target)
        preview_header.addStretch()
        preview_layout.addLayout(preview_header)

        self.preview_cards_area = QScrollArea()
        self.preview_cards_area.setObjectName("PreviewCardsArea")
        self.preview_cards_area.setFrameShape(QFrame.NoFrame)
        self.preview_cards_area.setWidgetResizable(True)
        self.preview_cards_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.preview_cards_content = QWidget()
        self.preview_cards_content.setObjectName("PreviewCardsContent")
        self.preview_cards_layout = QVBoxLayout(self.preview_cards_content)
        self.preview_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_cards_layout.setSpacing(8)
        self.preview_cards_area.setWidget(self.preview_cards_content)
        preview_layout.addWidget(self.preview_cards_area, 1)

        self.preview_table = QTableWidget(0, 10)
        self.preview_table.setObjectName("PreviewTable")
        self.preview_table.setHorizontalHeaderLabels(
            ["名称", "Hostname", "IP", "计算资源", "存储", "端口组", "CPU", "内存", "新增磁盘", "电源"]
        )
        self.preview_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.preview_table.setSelectionMode(QTableWidget.NoSelection)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setWordWrap(False)
        self.preview_table.setTextElideMode(Qt.ElideNone)
        self.preview_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.preview_table.setMinimumHeight(145)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.verticalHeader().setDefaultSectionSize(30)
        preview_header_view = self.preview_table.horizontalHeader()
        preview_header_view.setStretchLastSection(False)
        preview_header_view.setSectionsMovable(True)
        preview_header_view.setSectionResizeMode(QHeaderView.Interactive)
        self.preview_table.setVisible(False)
        preview_layout.addWidget(self.preview_table)
        self.preview_editor = PreviewEditor(
            self.preview_table,
            self,
            card_layout=self.preview_cards_layout,
        )
        self.preview_editor.items_changed.connect(self._on_preview_items_changed)
        outer.addWidget(preview_card)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        self.back_button = QPushButton("上一步")
        self.back_button.setObjectName("QuietButton")
        self.next_button = QPushButton("下一步")
        self.next_button.setObjectName("PrimaryButton")
        self.validate_button = QPushButton("校验参数")
        self.execute_button = QPushButton("开始克隆")
        self.execute_button.setObjectName("PrimaryButton")
        self.back_button.clicked.connect(lambda: self.steps.setCurrentRow(max(0, self.steps.currentRow() - 1)))
        self.next_button.clicked.connect(self._next_page)
        self.validate_button.clicked.connect(self.validate_plan)
        self.execute_button.clicked.connect(self._execute)
        footer.addWidget(self.back_button)
        footer.addStretch()
        footer.addWidget(self.validate_button)
        footer.addWidget(self.next_button)
        footer.addWidget(self.execute_button)
        outer.addLayout(footer)

    def _build_source_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox("源虚拟机")
        form = QFormLayout(group)
        self.source_label = QLabel("请在左侧资源列表中选择源虚拟机")
        self.source_label.setWordWrap(True)
        self.source_label.setObjectName("Muted")
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 1000)
        self.quantity.setValue(1)
        self.quantity.setSuffix(" 台")
        self.quantity.setToolTip("1 台使用输入名称；多台自动追加 1、2、3……")
        form.addRow("源虚拟机", self.source_label)
        form.addRow("克隆数量", self.quantity)
        layout.addWidget(group)
        note = QLabel("普通虚拟机和模板都可以作为源对象。虚拟机名称、hostname、IP 会在实时预览中展开。")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        return page

    def _build_target_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox("目标位置")
        form = QFormLayout(group)
        self.compute_combo = SearchableComboBox()
        self.compute_combo.setPlaceholderText("搜索集群或独立 ESXi 主机")
        self.folder_combo = SearchableComboBox()
        self.folder_combo.setEditable(True)
        self.folder_combo.setPlaceholderText("输入或搜索文件夹层级路径")
        self.datastore_combo = SearchableComboBox()
        self.datastore_combo.setPlaceholderText("搜索 datastore")
        form.addRow("计算资源", self.compute_combo)
        form.addRow("虚拟机文件夹", self.folder_combo)
        form.addRow("目标存储", self.datastore_combo)
        layout.addWidget(group)
        note = QLabel("计算资源支持集群和独立 ESXi。文件夹不存在时，执行阶段会按层级自动创建。多 datastore 源必须手动选择目标存储。")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        return page

    def _build_customization_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox("客户机自定义")
        form = QFormLayout(group)
        self.customization_combo = SearchableComboBox()
        self.customization_combo.setPlaceholderText("搜索自定义规范")
        form.addRow("自定义规范", self.customization_combo)
        layout.addWidget(group)
        note = QLabel(
            "不选择时使用工具生成的 DHCP/静态网络和 hostname 配置；选择后会复制规范并覆盖本批次 hostname 与 IP 设置。"
            " Linux 源模板必须至少安装 /usr/bin/cloud-init 或 /usr/bin/perl，否则客户机自定义会返回 127。"
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        return page

    def _build_identity_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox("名称规则")
        form = QFormLayout(group)
        self.vm_name = QLineEdit()
        self.vm_name.setPlaceholderText("例如 testvm")
        self.hostname = HostnameLineEdit()
        form.addRow("虚拟机名称", self.vm_name)
        form.addRow("Hostname", self.hostname)
        layout.addWidget(group)
        note = QLabel("单台保留输入名称；多台自动生成 testvm1、testvm2……Hostname 仅允许英文字母、数字和连字符，最多 63 个字符。")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        return page

    def _build_network_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox("端口组与 IPv4")
        form = QFormLayout(group)
        self.portgroup_combo = SearchableComboBox()
        self.portgroup_combo.setPlaceholderText("搜索端口组")
        self.dhcp_radio = QRadioButton("DHCP（默认）")
        self.static_radio = QRadioButton("静态 IPv4")
        self.dhcp_radio.setChecked(True)
        ip_mode = QHBoxLayout()
        ip_mode.addWidget(self.dhcp_radio)
        ip_mode.addWidget(self.static_radio)
        ip_mode.addStretch()
        self.ip_start_input = QLineEdit()
        self.ip_start_input.setPlaceholderText("例如 192.168.1.191")
        self.ip_start_input.setToolTip("输入第一台虚拟机的 IPv4，结束地址会按克隆数量自动计算")
        self.ip_end_input = QLineEdit()
        self.ip_end_input.setReadOnly(True)
        self.ip_end_input.setPlaceholderText("根据数量自动计算")
        self.ip_end_input.setToolTip("只读：按初始地址和克隆数量自动计算")
        self.subnet_mask = QLineEdit("255.255.255.0")
        self.gateway = QLineEdit()
        form.addRow("端口组", self.portgroup_combo)
        form.addRow("地址模式", ip_mode)
        form.addRow("IPv4 分配初始地址", self.ip_start_input)
        form.addRow("IPv4 分配结束地址", self.ip_end_input)
        form.addRow("子网掩码", self.subnet_mask)
        form.addRow("网关", self.gateway)
        layout.addWidget(group)

        dns_group = QGroupBox("DNS")
        dns_form = QFormLayout(dns_group)
        self.dns_dhcp_radio = QRadioButton("DHCP")
        self.dns_manual_radio = QRadioButton("手动")
        self.dns_dhcp_radio.setChecked(True)
        dns_mode = QHBoxLayout()
        dns_mode.addWidget(self.dns_dhcp_radio)
        dns_mode.addWidget(self.dns_manual_radio)
        dns_mode.addStretch()
        self.dns_primary = QLineEdit()
        self.dns_secondary = QLineEdit()
        self.dns_primary.setPlaceholderText("DNS 1")
        self.dns_secondary.setPlaceholderText("DNS 2（可选）")
        dns_form.addRow("DNS 模式", dns_mode)
        dns_form.addRow("DNS 1", self.dns_primary)
        dns_form.addRow("DNS 2", self.dns_secondary)
        layout.addWidget(dns_group)
        note = QLabel("跳过 IPv4 时所有网卡使用 DHCP。静态模式只需输入初始地址，结束地址会按数量自动计算。源虚拟机多网卡时禁止静态 IP；指定端口组会改为一块 VMXNET3 网卡。")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        self.dhcp_radio.toggled.connect(self._update_network_enabled)
        self.dns_dhcp_radio.toggled.connect(self._update_dns_enabled)
        self._update_network_enabled(True)
        self._update_dns_enabled(True)
        return page

    def _build_hardware_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox("CPU 与内存")
        form = QFormLayout(group)
        self.cpu_count = QSpinBox()
        self.cpu_count.setRange(0, 512)
        self.cpu_count.setSpecialValueText("继承模板")
        self.cpu_count.setSuffix(" vCPU")
        self.memory_gb = QSpinBox()
        self.memory_gb.setRange(0, 65536)
        self.memory_gb.setSpecialValueText("继承模板")
        self.memory_gb.setSuffix(" GB")
        form.addRow("CPU", self.cpu_count)
        form.addRow("内存", self.memory_gb)
        layout.addWidget(group)

        disk_group = QGroupBox("新增硬盘")
        disk_layout = QVBoxLayout(disk_group)
        self.disk_container = QWidget()
        self.disk_form = QFormLayout(self.disk_container)
        disk_layout.addWidget(self.disk_container)
        disk_buttons = QHBoxLayout()
        add_disk = QPushButton("添加硬盘")
        remove_disk = QPushButton("移除最后一块")
        add_disk.clicked.connect(lambda: self._add_disk_row())
        remove_disk.clicked.connect(self._remove_disk_row)
        disk_buttons.addWidget(add_disk)
        disk_buttons.addWidget(remove_disk)
        disk_buttons.addStretch()
        disk_layout.addLayout(disk_buttons)
        layout.addWidget(disk_group)

        remark_group = QGroupBox("备注与电源")
        remark_layout = QFormLayout(remark_group)
        self.remark = QTextEdit()
        self.remark.setFixedHeight(70)
        self.power_on_after = QCheckBox("成功后自动开机")
        remark_layout.addRow("备注", self.remark)
        remark_layout.addRow("电源策略", self.power_on_after)
        layout.addWidget(remark_group)
        note = QLabel("CPU 和内存为 0 时继承源配置，同时强制开启 CPU/内存热添加。新增磁盘默认精简置备、持久模式，1 TB 按 1024 GB 计算。")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        return page

    def _build_review_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox("执行前校验")
        group_layout = QVBoxLayout(group)
        concurrency_row = QHBoxLayout()
        concurrency_row.addWidget(QLabel("克隆并发"))
        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 10)
        self.concurrency.setValue(5)
        self.concurrency.setSuffix(" 个任务")
        concurrency_row.addWidget(self.concurrency)
        concurrency_row.addStretch()
        self.force_ip_conflicts = QCheckBox("检测到已上报 IP 或名称冲突时强制继续，并在报告中记录警告")
        self.validation_label = QLabel("修改参数后会自动生成预览。")
        self.validation_label.setWordWrap(True)
        self.validation_label.setObjectName("Muted")
        group_layout.addLayout(concurrency_row)
        group_layout.addWidget(self.force_ip_conflicts)
        group_layout.addWidget(self.validation_label)
        layout.addWidget(group)
        note = QLabel("执行前会再次校验对象存在性、存储可见性、网络对象、名称/IP 重复以及多 datastore/多网卡规则。每台克隆独立记录结果，失败项可单独重试。")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        return page

    def _connect_form_signals(self) -> None:
        for widget in (
            self.quantity,
            self.compute_combo,
            self.folder_combo,
            self.datastore_combo,
            self.customization_combo,
            self.vm_name,
            self.hostname,
            self.portgroup_combo,
            self.ip_start_input,
            self.subnet_mask,
            self.gateway,
            self.dns_primary,
            self.dns_secondary,
            self.cpu_count,
            self.memory_gb,
            self.concurrency,
            self.power_on_after,
            self.force_ip_conflicts,
        ):
            if hasattr(widget, "textChanged"):
                widget.textChanged.connect(self._refresh_preview)
            elif hasattr(widget, "currentTextChanged"):
                widget.currentTextChanged.connect(self._refresh_preview)
            elif hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self._refresh_preview)
            elif hasattr(widget, "stateChanged"):
                widget.stateChanged.connect(self._refresh_preview)
        self.dhcp_radio.toggled.connect(self._refresh_preview)
        self.static_radio.toggled.connect(self._refresh_preview)
        self.quantity.valueChanged.connect(self._update_ipv4_end)
        self.ip_start_input.textChanged.connect(self._update_ipv4_end)
        self.static_radio.toggled.connect(self._on_static_mode_changed)
        self.dns_dhcp_radio.toggled.connect(self._refresh_preview)
        self.dns_manual_radio.toggled.connect(self._refresh_preview)
        self.remark.textChanged.connect(self._refresh_preview)

    def _show_page(self, index: int) -> None:
        if index < 0:
            return
        self.pages.setCurrentIndex(index)
        self.page_title.setText(self.STEP_TITLES[index])
        self.page_hint.setText(
            "实时预览会随着表单变化更新" if index == 6 else f"第 {index + 1} 步，共 {self.page_count()} 步"
        )
        self.back_button.setEnabled(index > 0)
        self.next_button.setVisible(index < self.page_count() - 1)
        self.validate_button.setVisible(index == self.page_count() - 1)
        self.execute_button.setVisible(index == self.page_count() - 1)

    def _next_page(self) -> None:
        current = self.steps.currentRow()
        if current < self.page_count() - 1:
            self.steps.setCurrentRow(current + 1)

    def _update_network_enabled(self, dhcp: bool) -> None:
        for widget in (self.ip_start_input, self.ip_end_input, self.subnet_mask, self.gateway):
            widget.setEnabled(not dhcp)

    def _on_static_mode_changed(self, enabled: bool) -> None:
        if enabled:
            self._update_ipv4_end()
        else:
            self.ip_end_input.clear()

    def _update_ipv4_end(self, *_args) -> None:
        if not self.static_radio.isChecked():
            return
        start = self.ip_start_input.text().strip()
        if not start:
            self.ip_end_input.clear()
            return
        try:
            end = ipv4_range_end(start, self.quantity.value())
        except ValueError:
            self.ip_end_input.clear()
        else:
            self.ip_end_input.setText(end)
        self._refresh_preview()

    def _update_dns_enabled(self, dhcp: bool) -> None:
        self.dns_primary.setEnabled(not dhcp)
        self.dns_secondary.setEnabled(not dhcp)

    def _add_disk_row(self, size: float = 100, unit: str = "GB") -> None:
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
        self.disk_form.addRow(f"磁盘 {len(self.disk_rows) + 1}", row)
        self.disk_rows.append((size_box, unit_box, row))
        size_box.valueChanged.connect(self._refresh_preview)
        unit_box.currentTextChanged.connect(self._refresh_preview)

    def _remove_disk_row(self) -> None:
        if not self.disk_rows:
            return
        _, _, row = self.disk_rows.pop()
        self.disk_form.removeRow(row)
        self._refresh_preview()

    def set_snapshot(self, snapshot: InventorySnapshot) -> None:
        self.snapshot = snapshot
        self._set_compute_items(snapshot.compute_resources)
        self._set_folder_items(snapshot.folders)
        self._set_datastore_items(snapshot.datastores)
        self._set_search_items(self.customization_combo, [("不使用自定义规范", None), *[(name, name) for name in snapshot.customization_specs]])
        self._set_search_items(self.portgroup_combo, [("继承源虚拟机网卡", None), *[(name, name) for name in snapshot.portgroups]])
        self._refresh_preview()

    def _set_compute_items(self, resources: tuple[ComputeResource, ...]) -> None:
        items = []
        for resource in resources:
            kind = "集群" if resource.kind == "cluster" else "ESXi"
            items.append((f"[{kind}] {resource.name}", resource.moid))
        self._set_search_items(self.compute_combo, items)

    def _set_folder_items(self, folders: tuple[str, ...]) -> None:
        current = self.folder_combo.currentText()
        self._set_search_items(self.folder_combo, [(folder, folder) for folder in folders])
        if current:
            self.folder_combo.setEditText(current)

    @staticmethod
    def _set_search_items(combo: SearchableComboBox, items: list[tuple[str, object]]) -> None:
        combo.set_items(items)

    def _set_datastore_items(self, datastores: tuple[str, ...]) -> None:
        inherited = "继承模板（等待选择源虚拟机）"
        if self.source_vm and len(self.source_vm.datastores) == 1:
            inherited = f"继承模板（{self.source_vm.datastores[0]}）"
        elif self.source_vm and len(self.source_vm.datastores) > 1:
            inherited = "必须手动选择（源虚拟机有多个 datastore）"
        self._set_search_items(
            self.datastore_combo,
            [(inherited, None), *[(name, name) for name in datastores]],
        )

    def set_source_vm(self, vm: VmRecord | None) -> None:
        self.source_vm = vm
        if vm is None:
            self.source_label.setText("请在左侧资源列表中选择源虚拟机")
            self._set_datastore_items(self.snapshot.datastores)
            self.preview_editor.clear()
            self._refresh_preview()
            return
        details = f"{vm.name} · {'模板' if vm.is_template else '普通虚拟机'} · {vm.power_state}"
        self.source_label.setText(details)
        if self._auto_vm_name or not self.vm_name.text().strip():
            self.vm_name.setText(vm.name)
            self._auto_vm_name = True
        if self._auto_hostname or not self.hostname.text().strip():
            try:
                validate_hostname(vm.name)
            except ValueError:
                self.hostname.clear()
                self._auto_hostname = False
            else:
                self.hostname.setText(vm.name)
                self._auto_hostname = True
        self._set_datastore_items(self.snapshot.datastores)
        self._refresh_preview()

    def _build_form(self) -> CloneForm:
        compute_id = self.compute_combo.selected_data() or ""
        datastore_name = self.datastore_combo.selected_data()
        customization_name = self.customization_combo.selected_data()
        portgroup_name = self.portgroup_combo.selected_data()
        dns_servers = tuple(
            value.strip()
            for value in (self.dns_primary.text(), self.dns_secondary.text())
            if value.strip()
        )
        disks = tuple(
            DiskRequest(size=size.value(), unit=unit.currentText())
            for size, unit, _ in self.disk_rows
        )
        ip_start = self.ip_start_input.text().strip()
        ip_end = self.ip_end_input.text().strip()
        ip_input = ip_start
        if self.static_radio.isChecked() and self.quantity.value() > 1 and ip_end:
            ip_input = f"{ip_start}-{ip_end}"
        network = NetworkConfig(
            ip_mode="static" if self.static_radio.isChecked() else "dhcp",
            ip_input=ip_input,
            subnet_mask=self.subnet_mask.text().strip(),
            gateway=self.gateway.text().strip(),
            dns_mode="manual" if self.dns_manual_radio.isChecked() else "dhcp",
            dns_servers=dns_servers,
        )
        return CloneForm(
            source_vm_id=self.source_vm.moid if self.source_vm else "",
            quantity=self.quantity.value(),
            compute_resource_id=compute_id,
            folder_path=self.folder_combo.currentText().strip(),
            datastore_name=datastore_name,
            customization_spec_name=customization_name,
            vm_name_prefix=self.vm_name.text().strip(),
            hostname_prefix=self.hostname.text().strip(),
            portgroup_name=portgroup_name,
            cpu_count=self.cpu_count.value() or None,
            memory_gb=self.memory_gb.value() or None,
            disks=disks,
            network=network,
            remark=self.remark.toPlainText().strip(),
            power_on_after=self.power_on_after.isChecked(),
            force_ip_conflicts=self.force_ip_conflicts.isChecked(),
            concurrency=self.concurrency.value(),
        )

    def validate_plan(self, show_feedback: bool = True) -> ClonePlan | None:
        try:
            base_plan = self.validator.validate(self._build_form(), self.snapshot)
            edited_items = self.preview_editor.items_for_plan(base_plan)
            if edited_items:
                plan = apply_clone_item_edits(base_plan, edited_items, self.snapshot)
            else:
                plan = base_plan
        except (ValueError, KeyError) as exc:
            self.current_plan = None
            self.validation_label.setText(f"校验失败：{exc}")
            self.validation_label.setStyleSheet("color: #b42318;")
            if show_feedback:
                self.preview_status.setText("参数需要修正")
            self.plan_changed.emit(None)
            return None
        self.current_plan = plan
        self.preview_editor.set_plan(plan, self.snapshot)
        self._update_preview_summary(plan)
        message = f"校验通过：{len(plan.items)} 台，继承项 {len(plan.inheritance)} 个"
        warning_count = len(plan.warnings) + len(plan.environment_warnings)
        if warning_count:
            message += f"，警告 {warning_count} 条"
        if plan.environment_warnings:
            message += f"：{plan.environment_warnings[0]}"
        self.validation_label.setText(message)
        self.validation_label.setStyleSheet("color: #159570;")
        self.plan_changed.emit(plan)
        return plan

    def _on_preview_items_changed(self, edited_items) -> None:
        try:
            base_plan = self.validator.validate(self._build_form(), self.snapshot)
            plan = apply_clone_item_edits(base_plan, tuple(edited_items), self.snapshot)
        except (ValueError, KeyError) as exc:
            self.current_plan = None
            self.validation_label.setText(f"校验失败：{exc}")
            self.validation_label.setStyleSheet("color: #b42318;")
            self.preview_status.setText("预览行参数需要修正")
            self.plan_changed.emit(None)
            return
        self.current_plan = plan
        self._update_preview_summary(plan)
        message = f"校验通过：{len(plan.items)} 台，继承项 {len(plan.inheritance)} 个"
        warning_count = len(plan.warnings) + len(plan.environment_warnings)
        if warning_count:
            message += f"，警告 {warning_count} 条"
        self.validation_label.setText(message)
        self.validation_label.setStyleSheet("color: #159570;")
        self.plan_changed.emit(plan)

    def _refresh_preview(self, *_args) -> None:
        plan = self.validate_plan(show_feedback=False)
        if plan is None:
            if not self.preview_editor.items():
                self.preview_editor.clear()
            self.preview_status.setText("填写必要参数后显示预览")
            self.preview_count.setText("0 台")
            self.preview_target.setText("等待参数")
            return
        if self.preview_editor.plan is not plan:
            self.preview_editor.set_plan(plan, self.snapshot)
        self._update_preview_summary(plan)

    def _update_preview_summary(self, plan: ClonePlan) -> None:
        self.preview_count.setText(f"{len(plan.items)} 台 · 并发 {plan.concurrency}")
        self.preview_target.setText(f"{plan.compute_resource.name} · {plan.datastore_name}")
        self.preview_status.setText(
            "参数已通过 · 请查看环境提示" if plan.environment_warnings else "参数已通过"
        )

    def _execute(self) -> None:
        plan = self.validate_plan()
        if plan is not None:
            self.execute_requested.emit(plan)

    def set_execution_progress(self, result) -> None:
        state = "成功" if result.success else "失败"
        self.preview_status.setText(f"第 {result.sequence} 台 {state}：{result.vm_name}")

    def set_execution_report(self, report) -> None:
        self.preview_status.setText(
            f"执行完成：成功 {report.success_count} 台，失败 {report.failed_count} 台"
        )
