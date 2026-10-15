from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QLineEdit, QSpinBox  # noqa: E402

from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.widgets import SearchableComboBox  # noqa: E402
from test_domain import make_inventory  # noqa: E402


def test_resource_combo_is_an_explicit_searchable_dropdown():
    application = QApplication.instance() or QApplication([])
    combo = SearchableComboBox()
    combo.set_items([("Datastore A", "ds-a"), ("Datastore B", "ds-b")])

    assert combo.isEditable() is True
    assert combo.property("resourceSelector") is True
    assert combo.maxVisibleItems() == 12
    assert combo.view().minimumWidth() >= 280
    assert combo.currentData() == "ds-a"

    combo.close()
    application.processEvents()


def test_connection_error_does_not_disconnect_from_gui_thread():
    application = QApplication.instance() or QApplication([])
    window = MainWindow()

    class FakeSession:
        is_connected = False

        def disconnect(self):
            raise AssertionError("disconnect must be owned by the worker")

    session = FakeSession()
    window.session = session

    window._on_background_error("连接超时")

    assert window.session is None
    window.close()
    application.processEvents()


def test_main_window_initializes_with_b_layout():
    application = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert window.windowTitle() == "vm-clone"
    assert window.inventory_panel is not None
    assert window.wizard_panel is not None
    assert window.wizard_panel.page_count() == 7
    assert window.findChild(type(window.inventory_panel), "InventoryPanel") is window.inventory_panel
    assert window.findChild(type(window.wizard_panel), "WizardPanel") is window.wizard_panel
    assert window.findChild(type(window.wizard_panel.preview_table), "PreviewTable") is window.wizard_panel.preview_table
    assert window.connection_status.objectName() == "ConnectionStatus"
    assert window.inventory_panel.total_metric.text() == "0"
    assert window.actions_bar.objectName() == "ActionsBar"
    assert window.main_splitter.objectName() == "MainSplitter"
    assert window.wizard_panel.compute_combo.property("resourceSelector") is True
    assert window.wizard_panel.folder_combo.property("resourceSelector") is True
    assert window.wizard_panel.datastore_combo.property("resourceSelector") is True
    assert window.wizard_panel.customization_combo.property("resourceSelector") is True
    assert window.wizard_panel.portgroup_combo.property("resourceSelector") is True
    assert window.wizard_panel.preview_table.columnCount() == 10
    assert window.wizard_panel.preview_table.horizontalHeaderItem(4).text() == "存储"
    assert window.wizard_panel.preview_table.horizontalHeaderItem(5).text() == "端口组"
    assert window.wizard_panel.preview_table.horizontalHeaderItem(6).text() == "CPU"
    assert window.wizard_panel.preview_table.horizontalHeaderItem(7).text() == "内存"

    window.close()
    application.processEvents()


def test_static_ipv4_start_and_end_fields_use_full_address_arithmetic():
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    panel = window.wizard_panel

    panel.quantity.setValue(3)
    panel.static_radio.setChecked(True)
    panel.ip_start_input.setText("192.168.1.191")

    assert panel.ip_start_input.text() == "192.168.1.191"
    assert panel.ip_end_input.text() == "192.168.1.193"
    assert panel._build_form().network.ip_input == "192.168.1.191-192.168.1.193"

    window.close()
    application.processEvents()


def test_preview_shows_full_storage_portgroup_cpu_and_memory_values():
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    panel = window.wizard_panel

    plan = type(
        "PreviewPlan",
        (),
        {
            "items": (type("Item", (), {"vm_name": "testvm1", "hostname": "testvm1", "ip_address": None})(),),
            "compute_resource": type("Compute", (), {"name": "wh-vsan"})(),
            "datastore_name": "vsanDatastore-349TB",
            "portgroup_name": "DPortGroup-vlan10",
            "cpu_count": 8,
            "memory_gb": 16,
            "disk_requests": (),
            "power_on_after": True,
            "concurrency": 5,
            "inheritance": {"datastore": "custom", "cpu": "source", "memory": "custom"},
            "warnings": (),
            "environment_warnings": (),
        },
    )()
    panel.validate_plan = lambda show_feedback=False: plan
    panel._refresh_preview()

    values = [panel.preview_table.item(0, column).text() for column in range(10)]
    assert values[4] == "vsanDatastore-349TB（已指定）"
    assert values[5] == "DPortGroup-vlan10"
    assert values[6] == "8 vCPU（继承模板）"
    assert values[7] == "16 GB（已覆盖）"

    window.close()
    application.processEvents()


def test_new_disk_list_starts_empty_and_removal_updates_plan_immediately():
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    panel = window.wizard_panel
    snapshot = make_inventory()
    panel.set_snapshot(snapshot)
    panel.set_source_vm(snapshot.vms[0])
    panel._add_disk_row(100, "GB")
    assert len(panel.disk_rows) == 1
    panel._remove_disk_row()
    application.processEvents()

    assert panel.disk_rows == []
    assert panel.current_plan is not None
    assert panel.current_plan.disk_requests == ()
    assert panel.preview_table.item(0, 8).text() == "无新增"

    window.close()
    application.processEvents()


def test_preview_rows_are_editable_and_item_edits_update_the_effective_plan():
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    panel = window.wizard_panel
    snapshot = make_inventory()
    panel.set_snapshot(snapshot)
    panel.set_source_vm(snapshot.vms[0])
    application.processEvents()

    name_editor = panel.preview_table.cellWidget(0, 0)
    cpu_editor = panel.preview_table.cellWidget(0, 6)
    datastore_editor = panel.preview_table.cellWidget(0, 4)
    assert isinstance(name_editor, QLineEdit)
    assert isinstance(cpu_editor, QSpinBox)
    assert isinstance(datastore_editor, SearchableComboBox)
    assert datastore_editor.property("resourceSelector") is True

    name_editor.setText("row-custom")
    cpu_editor.setValue(6)
    application.processEvents()

    assert panel.current_plan is not None
    assert panel.current_plan.items[0].vm_name == "row-custom"
    assert panel.current_plan.items[0].cpu_count == 6

    window.close()
    application.processEvents()


def test_form_changes_update_untouched_row_fields_without_losing_row_drafts():
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    panel = window.wizard_panel
    snapshot = make_inventory()
    panel.set_snapshot(snapshot)
    panel.set_source_vm(snapshot.vms[0])

    name_editor = panel.preview_table.cellWidget(0, 0)
    name_editor.setText("kept-row-name")
    panel.cpu_count.setValue(8)
    application.processEvents()

    assert panel.current_plan is not None
    assert panel.current_plan.items[0].vm_name == "kept-row-name"
    assert panel.current_plan.items[0].cpu_count == 8

    cpu_editor = panel.preview_table.cellWidget(0, 6)
    cpu_editor.setValue(6)
    panel.cpu_count.setValue(10)
    application.processEvents()
    assert panel.current_plan.items[0].cpu_count == 6

    window.close()
    application.processEvents()


def test_batch_preview_uses_readable_stacked_edit_cards():
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    panel = window.wizard_panel
    snapshot = make_inventory()
    panel.set_snapshot(snapshot)
    panel.set_source_vm(snapshot.vms[0])
    application.processEvents()

    assert panel.preview_cards_area.objectName() == "PreviewCardsArea"
    assert panel.preview_table.isHidden() is True
    card = panel.preview_editor.card_for_sequence(1)
    assert card is not None
    assert card.minimumHeight() >= 150
    assert len(card.findChildren(SearchableComboBox)) == 2

    window.close()
    application.processEvents()
