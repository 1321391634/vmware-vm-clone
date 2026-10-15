from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.domain.models import InventorySnapshot, VmRecord  # noqa: E402
from app.ui.inventory_panel import InventoryPanel  # noqa: E402


def test_inventory_filter_uses_the_vm_id_stored_in_sorted_table_rows():
    application = QApplication.instance() or QApplication([])
    panel = InventoryPanel()
    snapshot = InventorySnapshot(
        vms=(
            VmRecord(moid="vm-z", name="zulu", is_template=False, power_state="poweredOn"),
            VmRecord(moid="vm-a", name="alpha", is_template=True, power_state="poweredOff"),
        )
    )

    panel.set_snapshot(snapshot)
    panel.table.sortItems(0)
    panel.search.setText("alpha")

    assert panel.table.isRowHidden(0) is False
    assert panel.table.item(0, 0).data(0x0100) == "vm-a"
    assert panel.table.isRowHidden(1) is True

    panel.close()
    application.processEvents()
