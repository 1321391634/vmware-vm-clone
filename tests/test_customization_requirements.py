from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.customization import linux_customization_warning  # noqa: E402
from app.domain.models import NetworkConfig  # noqa: E402
from app.domain.planning import build_clone_plan  # noqa: E402
from test_domain import make_form, make_inventory  # noqa: E402


def test_linux_guest_customization_exposes_the_required_guest_executors():
    warning = linux_customization_warning("rhel9_64Guest")

    assert warning is not None
    assert "/usr/bin/cloud-init" in warning
    assert "/usr/bin/perl" in warning
    assert "127" in warning


def test_windows_guest_does_not_receive_the_linux_customization_warning():
    assert linux_customization_warning("windows9Server64Guest") is None


def test_linux_clone_plan_carries_the_customization_warning_into_execution():
    inventory = make_inventory()
    source = replace(inventory.vms[0], guest_id="rhel9_64Guest")
    inventory = replace(inventory, vms=(source, *inventory.vms[1:]))

    plan = build_clone_plan(
        make_form(network=NetworkConfig(ip_mode="dhcp")),
        inventory,
    )

    assert plan.environment_warnings
    assert "/usr/bin/perl" in plan.environment_warnings[0]
