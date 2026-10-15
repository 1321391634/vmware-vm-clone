from __future__ import annotations

from .models import CloneForm, ClonePlan, InventorySnapshot
from .planning import build_clone_plan


class PreflightValidator:
    """Public preflight boundary used by UI and execution orchestration."""

    def validate(self, form: CloneForm, inventory: InventorySnapshot) -> ClonePlan:
        return build_clone_plan(form, inventory)

