from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.preflight import PreflightValidator  # noqa: E402
from app.domain.models import NetworkConfig  # noqa: E402
from app.domain.planning import build_clone_plan  # noqa: E402

from test_domain import make_form, make_inventory  # noqa: E402


def test_preflight_validator_returns_the_same_complete_clone_plan():
    form = make_form(network=NetworkConfig(ip_mode="dhcp"))

    plan = PreflightValidator().validate(form, make_inventory())

    assert plan.source_vm.name == "template"
    assert plan.inheritance["datastore"] == "source"
    assert plan.cpu_hot_add_enabled is True


def test_preflight_validator_reuses_domain_errors_for_invalid_parameters():
    form = make_form(quantity=0)

    with pytest.raises(ValueError, match="克隆数量"):
        PreflightValidator().validate(form, make_inventory())
