from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import ClonePlan, InventorySnapshot
from app.persistence.credentials import CredentialStore, VCenterProfile
from app.persistence.logging_config import configure_logging
from app.ui.inventory_panel import InventoryPanel
from app.ui.styles import APP_STYLE
from app.ui.wizard_panel import WizardPanel
from app.ui.worker import Worker


class MainWindow(QMainWindow):
    def __init__(self, parent=None, *, data_dir: str | Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("vm-clone")
        self.resize(1680, 1000)
        self.setMinimumSize(1280, 800)
        self.setStyleSheet(APP_STYLE)

        default_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "vm-clone"
        self.data_dir = Path(data_dir) if data_dir else default_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.credential_store = CredentialStore(self.data_dir)
        self.logger = configure_logging(self.data_dir)
        self.thread_pool = QThreadPool.globalInstance()
        self.session: VCenterSession | None = None
        self.snapshot = InventorySnapshot()
        self._active_worker: Worker | None = None
        self._active_plan: ClonePlan | None = None
        self._last_report = None

        self._build_ui()
        self._load_profiles()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_top_bar())

        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("MainSplitter")
        splitter.setChildrenCollapsible(False)
        self.main_splitter = splitter
        self.inventory_panel = InventoryPanel()
        self.inventory_panel.setMinimumWidth(360)
        self.inventory_panel.setMaximumWidth(560)
        self.wizard_panel = WizardPanel()
        splitter.addWidget(self.inventory_panel)
        splitter.addWidget(self.wizard_panel)
        splitter.setSizes([430, 1250])
        root.addWidget(splitter, 1)
        self.setCentralWidget(central)

        status = QStatusBar()
        status.showMessage("未连接 vCenter")
        self.setStatusBar(status)
        self.status = status

        self.inventory_panel.vm_selected.connect(self.wizard_panel.set_source_vm)
        self.inventory_panel.refresh_requested.connect(self.refresh_inventory)
        self.wizard_panel.execute_requested.connect(self.execute_plan)

    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("TopBar")
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(18, 11, 18, 10)
        layout.setSpacing(9)

        first_row = QHBoxLayout()
        first_row.setSpacing(9)
        brand_mark = QFrame()
        brand_mark.setObjectName("BrandMark")
        brand_mark.setFixedSize(34, 34)
        brand_mark_layout = QVBoxLayout(brand_mark)
        brand_mark_layout.setContentsMargins(0, 0, 0, 0)
        brand_glyph = QLabel("V")
        brand_glyph.setObjectName("BrandGlyph")
        brand_glyph.setAlignment(Qt.AlignCenter)
        brand_mark_layout.addWidget(brand_glyph)
        first_row.addWidget(brand_mark)
        brand = QVBoxLayout()
        brand.setSpacing(0)
        title = QLabel("vm-clone")
        title.setObjectName("AppTitle")
        subtitle = QLabel("批量克隆控制室")
        subtitle.setObjectName("AppSubtitle")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        first_row.addLayout(brand)
        first_row.addSpacing(12)
        self.connection_status = QLabel("● 未连接")
        self.connection_status.setObjectName("ConnectionStatus")
        first_row.addWidget(self.connection_status)
        first_row.addStretch()

        self.profile_combo = QComboBox()
        self.profile_combo.setPlaceholderText("已保存配置")
        self.profile_combo.setMinimumWidth(150)
        self.profile_combo.currentIndexChanged.connect(self._load_selected_profile)
        first_row.addWidget(self.profile_combo)
        self.save_profile_button = QPushButton("保存配置")
        self.save_profile_button.setObjectName("QuietButton")
        self.save_profile_button.clicked.connect(self.save_profile)
        first_row.addWidget(self.save_profile_button)
        layout.addLayout(first_row)

        connection_row = QHBoxLayout()
        connection_row.setSpacing(7)
        connection_label = QLabel("VCENTER")
        connection_label.setObjectName("Eyebrow")
        connection_row.addWidget(connection_label)
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("vCenter 地址")
        self.host_edit.setMinimumWidth(210)
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("用户名")
        self.user_edit.setMinimumWidth(150)
        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("密码")
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setMinimumWidth(130)
        connection_row.addWidget(self.host_edit, 2)
        connection_row.addWidget(self.user_edit, 1)
        connection_row.addWidget(self.password_edit, 1)
        self.connect_button = QPushButton("连接")
        self.connect_button.setObjectName("PrimaryButton")
        self.disconnect_button = QPushButton("断开")
        self.refresh_button = QPushButton("刷新")
        self.export_json_button = QPushButton("导出 JSON")
        self.export_excel_button = QPushButton("导出 Excel")
        self.retry_button = QPushButton("只重试失败项")
        self.retry_button.setEnabled(False)
        self.export_json_button.setEnabled(False)
        self.export_excel_button.setEnabled(False)
        self.disconnect_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        connection_row.addWidget(self.connect_button)
        connection_row.addStretch()
        layout.addLayout(connection_row)

        self.actions_bar = QFrame()
        self.actions_bar.setObjectName("ActionsBar")
        actions_layout = QHBoxLayout(self.actions_bar)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(7)
        actions_label = QLabel("工具")
        actions_label.setObjectName("Eyebrow")
        actions_layout.addWidget(actions_label)
        actions_layout.addWidget(self.disconnect_button)
        actions_layout.addWidget(self.refresh_button)
        actions_layout.addSpacing(8)
        actions_layout.addWidget(self.export_json_button)
        actions_layout.addWidget(self.export_excel_button)
        actions_layout.addWidget(self.retry_button)
        actions_layout.addStretch()
        layout.addWidget(self.actions_bar)
        for button in (
            self.connect_button,
            self.disconnect_button,
            self.refresh_button,
            self.export_json_button,
            self.export_excel_button,
            self.retry_button,
        ):
            button.setMinimumHeight(31)
        self.connect_button.clicked.connect(self.connect_vcenter)
        self.disconnect_button.clicked.connect(self.disconnect_vcenter)
        self.refresh_button.clicked.connect(self.refresh_inventory)
        self.export_json_button.clicked.connect(lambda: self.export_report("json"))
        self.export_excel_button.clicked.connect(lambda: self.export_report("excel"))
        self.retry_button.clicked.connect(self.retry_failed)
        return bar

    def _load_profiles(self) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for profile in self.credential_store.list_profiles():
            self.profile_combo.addItem(f"{profile.name} · {profile.username}", profile.profile_id)
        self.profile_combo.blockSignals(False)

    def _load_selected_profile(self, index: int) -> None:
        if index < 0:
            return
        profile_id = self.profile_combo.itemData(index)
        profile = self.credential_store.load(profile_id) if profile_id else None
        if profile is None:
            return
        self.host_edit.setText(profile.host)
        self.user_edit.setText(profile.username)
        self.password_edit.setText(self.credential_store.get_password(profile) or "")

    def save_profile(self) -> None:
        host = self.host_edit.text().strip()
        username = self.user_edit.text().strip()
        password = self.password_edit.text()
        if not host or not username:
            self.status.showMessage("保存配置前请填写 vCenter 地址和用户名", 5000)
            return
        profile_id = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{username}@{host}")
        profile = VCenterProfile(profile_id=profile_id, name=host, host=host, username=username)
        self.credential_store.save(profile, password)
        self._load_profiles()
        self.profile_combo.setCurrentIndex(self.profile_combo.findData(profile_id))
        self.status.showMessage(f"已保存配置：{host}", 5000)

    def connect_vcenter(self) -> None:
        if self._active_worker is not None:
            return
        host = self.host_edit.text().strip()
        username = self.user_edit.text().strip()
        password = self.password_edit.text()
        if not host or not username or not password:
            self.status.showMessage("请输入 vCenter 地址、用户名和密码", 5000)
            return
        from app.vmware.session import VCenterSession

        session = VCenterSession(host, username, password)
        self.session = session
        self._set_connection_busy(True, "正在连接 vCenter…")

        def connect_and_load(_progress):
            from app.vmware.inventory import InventoryService

            completed = False
            try:
                session.connect()
                snapshot = InventoryService(session).load(progress=_progress)
                completed = True
                return snapshot
            finally:
                if not completed:
                    try:
                        session.disconnect()
                    except Exception:
                        pass

        self._run_worker(
            connect_and_load,
            self._on_inventory_loaded,
            self._on_background_error,
            self._on_connection_finished,
            self._on_inventory_progress,
        )

    def refresh_inventory(self) -> None:
        if self.session is None or self._active_worker is not None:
            return
        session = self.session

        self._set_connection_busy(True, "正在刷新 vCenter 资源…")
        self._run_worker(
            lambda progress: self._load_inventory(session, progress),
            self._on_inventory_loaded,
            self._on_background_error,
            lambda: self._set_connection_busy(False, "资源刷新完成"),
            self._on_inventory_progress,
        )

    @staticmethod
    def _load_inventory(session, progress):
        from app.vmware.inventory import InventoryService

        return InventoryService(session).load(progress=progress)

    def disconnect_vcenter(self) -> None:
        if self._active_worker is not None:
            self.status.showMessage("后台任务进行中，完成后再断开连接", 5000)
            return
        if self.session is not None:
            self.session.disconnect()
        self.session = None
        self.snapshot = InventorySnapshot()
        self.inventory_panel.clear()
        self.wizard_panel.set_snapshot(self.snapshot)
        self.wizard_panel.set_source_vm(None)
        self._set_connection_busy(False, "已断开 vCenter")

    def _on_inventory_loaded(self, snapshot: InventorySnapshot) -> None:
        self.snapshot = snapshot
        self.inventory_panel.set_snapshot(snapshot)
        self.wizard_panel.set_snapshot(snapshot)
        self.status.showMessage(f"已加载 {len(snapshot.vms)} 台虚拟机、{len(snapshot.compute_resources)} 个计算资源")
        self.connection_status.setText(f"● 已连接 · {self.host_edit.text().strip()}")
        self.connection_status.setProperty("connected", True)
        self.connection_status.style().unpolish(self.connection_status)
        self.connection_status.style().polish(self.connection_status)

    def _on_background_error(self, message: str) -> None:
        self.logger.error(message)
        self.status.showMessage(f"操作失败：{message}", 8000)
        self.connection_status.setText("● 连接失败")
        self.connection_status.setProperty("connected", False)
        if self.session is not None and not self.session.is_connected and self.snapshot.vms == ():
            self.session = None

    def _on_inventory_progress(self, message: str) -> None:
        self.status.showMessage(message)

    def _on_connection_finished(self) -> None:
        self._set_connection_busy(False, self.status.currentMessage())

    def _set_connection_busy(self, busy: bool, message: str) -> None:
        self.connect_button.setEnabled(not busy and self.session is None)
        self.disconnect_button.setEnabled(not busy and self.session is not None)
        self.refresh_button.setEnabled(not busy and self.session is not None)
        self.save_profile_button.setEnabled(not busy)
        self.status.showMessage(message)

    def _run_worker(self, function, on_result, on_error, on_finished, on_progress=None) -> None:
        worker = Worker(function)
        self._active_worker = worker
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)
        worker.signals.finished.connect(self._worker_finished)
        worker.signals.finished.connect(on_finished)
        if on_progress is not None:
            worker.signals.progress.connect(on_progress)
        self.thread_pool.start(worker)

    def _worker_finished(self) -> None:
        self._active_worker = None
        self._set_connection_busy(False, self.status.currentMessage())

    def execute_plan(self, plan: ClonePlan, item_sequences: tuple[int, ...] | None = None) -> None:
        if self._active_worker is not None:
            self.status.showMessage("已有后台任务正在执行", 5000)
            return
        if not self.host_edit.text().strip() or not self.user_edit.text().strip() or not self.password_edit.text():
            self.status.showMessage("执行前需要保持 vCenter 登录信息", 5000)
            return
        self._active_plan = plan
        self.retry_button.setEnabled(False)
        self._set_connection_busy(True, "正在执行批量克隆…")

        host = self.host_edit.text().strip()
        username = self.user_edit.text().strip()
        password = self.password_edit.text()
        from app.vmware.clone_executor import CloneExecutor
        from app.vmware.clone_gateway import VmwareCloneGateway
        from app.vmware.session import VCenterSession

        def gateway_factory():
            session = VCenterSession(host, username, password)
            session.connect()
            return VmwareCloneGateway(session)

        def execute(_progress):
            executor = CloneExecutor(
                gateway_factory,
                max_workers=plan.concurrency,
                retry_count=2,
                retry_delay=3,
            )
            return executor.execute(
                plan,
                item_sequences=item_sequences,
                on_progress=_progress,
            )

        self._run_worker(
            execute,
            self._on_execution_finished,
            self._on_background_error,
            self._on_execution_worker_finished,
            self._on_execution_progress,
        )

    def _on_execution_progress(self, result) -> None:
        self.wizard_panel.set_execution_progress(result)
        self.status.showMessage(f"第 {result.sequence} 台 {'成功' if result.success else '失败'}：{result.vm_name}")

    def _on_execution_finished(self, report) -> None:
        self._last_report = report
        self.wizard_panel.set_execution_report(report)
        self.retry_button.setEnabled(any(
            not result.success and result.retryable
            for result in report.results
        ))
        self.export_json_button.setEnabled(True)
        self.export_excel_button.setEnabled(True)
        self.status.showMessage(f"批量克隆完成：成功 {report.success_count} 台，失败 {report.failed_count} 台")

    def _on_execution_worker_finished(self) -> None:
        self._set_connection_busy(False, self.status.currentMessage())

    def retry_failed(self) -> None:
        if self._last_report is None or self._active_plan is None:
            return
        sequences = tuple(
            result.sequence
            for result in self._last_report.results
            if not result.success and result.retryable
        )
        if sequences:
            self.execute_plan(self._active_plan, sequences)

    def export_report(self, format_name: str) -> None:
        if self._last_report is None:
            self.status.showMessage("暂无可导出的执行报告", 5000)
            return
        suffix = "json" if format_name == "json" else "xlsx"
        default_dir = self.data_dir / "reports"
        default_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        default_path = default_dir / f"clone-report-{stamp}.{suffix}"
        path, _ = QFileDialog.getSaveFileName(self, "导出克隆报告", str(default_path), f"*.{suffix}")
        if not path:
            return
        from app.reports.exporter import ReportExporter

        exporter = ReportExporter()
        if format_name == "json":
            exporter.to_json(self._last_report, path)
        else:
            exporter.to_excel(self._last_report, path)
        self.status.showMessage(f"报告已导出：{path}", 8000)

    def closeEvent(self, event) -> None:
        if self._active_worker is None and self.session is not None and self.session.is_connected:
            self.session.disconnect()
        self.session = None
        super().closeEvent(event)
