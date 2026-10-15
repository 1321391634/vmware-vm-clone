from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.models import (  # noqa: E402
    CloneForm,
    CloneItem,
    ComputeResource,
    DiskRequest,
    InventorySnapshot,
    NetworkConfig,
    VmRecord,
)
from app.domain.planning import apply_clone_item_edits, build_clone_plan  # noqa: E402
from app.domain.validation import (  # noqa: E402
    HostnameValidationError,
    autofill_ipv4_range,
    ipv4_range_end,
    parse_ipv4_range,
    validate_hostname,
)


def make_inventory(
    *,
    datastores: tuple[str, ...] = ("template-ds",),
    networks: tuple[str, ...] = ("VLAN100",),
    existing_names: tuple[str, ...] = (),
    existing_ips: tuple[str, ...] = (),
) -> InventorySnapshot:
    source = VmRecord(
        moid="vm-1",
        name="template",
        is_template=True,
        power_state="poweredOff",
        uuid="uuid-1",
        ip_address="192.168.100.10",
        host_name="esxi-01",
        cluster_name="cluster-a",
        datastores=datastores,
        networks=networks,
        folder_path="/Templates",
        guest_id="windows9Server64Guest",
        cpu_count=2,
        memory_mb=4096,
    )
    existing = tuple(
        VmRecord(
            moid=f"vm-existing-{idx}",
            name=name,
            is_template=False,
            power_state="poweredOn",
            uuid=f"uuid-existing-{idx}",
            ip_address=ip,
            datastores=("template-ds",),
            networks=("VLAN100",),
        )
        for idx, (name, ip) in enumerate(
            zip(existing_names, existing_ips or ("",) * len(existing_names))
        )
    )
    return InventorySnapshot(
        vms=(source, *existing),
        compute_resources=(
            ComputeResource(
                moid="domain-c1",
                name="cluster-a",
                kind="cluster",
                datacenter_name="dc-1",
                resource_pool_moid="resgroup-c1",
            ),
        ),
        datastores=tuple(datastores),
        folders=("/Templates", "/Production"),
        portgroups=("VLAN100", "VLAN200"),
        customization_specs=("Windows-Standard",),
    )


def make_form(**overrides) -> CloneForm:
    values = {
        "source_vm_id": "vm-1",
        "quantity": 2,
        "compute_resource_id": "domain-c1",
        "folder_path": "/Production",
        "datastore_name": None,
        "customization_spec_name": None,
        "vm_name_prefix": "testvm",
        "hostname_prefix": "testvm",
        "portgroup_name": None,
        "cpu_count": None,
        "memory_gb": None,
        "disks": (DiskRequest(100, "GB"), DiskRequest(1, "TB")),
        "network": NetworkConfig(ip_mode="static", ip_input="192.168.100.101-192.168.100.102"),
        "remark": "batch-created",
        "power_on_after": False,
        "force_ip_conflicts": False,
    }
    values.update(overrides)
    return CloneForm(**values)


def test_multi_clone_names_and_hostnames_are_numbered_from_one():
    plan = build_clone_plan(make_form(), make_inventory())

    assert [item.vm_name for item in plan.items] == ["testvm1", "testvm2"]
    assert [item.hostname for item in plan.items] == ["testvm1", "testvm2"]


def test_single_clone_keeps_the_entered_name():
    form = make_form(
        quantity=1,
        vm_name_prefix="single-vm",
        hostname_prefix="single-vm",
        network=NetworkConfig(ip_mode="dhcp"),
    )

    plan = build_clone_plan(form, make_inventory())

    assert plan.items[0].vm_name == "single-vm"
    assert plan.items[0].hostname == "single-vm"
    assert plan.items[0].ip_address is None


def test_static_ipv4_range_must_match_clone_quantity():
    form = make_form(
        quantity=3,
        network=NetworkConfig(ip_mode="static", ip_input="192.168.100.101-192.168.100.102"),
    )

    with pytest.raises(ValueError, match="IP 地址数量必须等于克隆数量"):
        build_clone_plan(form, make_inventory())


def test_hostname_rejects_non_ascii_and_invalid_edges():
    with pytest.raises(HostnameValidationError):
        validate_hostname("服务器-01")
    with pytest.raises(HostnameValidationError):
        validate_hostname("-invalid")
    with pytest.raises(HostnameValidationError):
        validate_hostname("invalid-")


def test_ipv4_range_expands_inclusive_endpoints():
    assert parse_ipv4_range("192.168.1.101-192.168.1.104") == (
        "192.168.1.101",
        "192.168.1.102",
        "192.168.1.103",
        "192.168.1.104",
    )


def test_ipv4_autofill_uses_clone_quantity_for_a_single_start_address():
    assert autofill_ipv4_range("192.168.1.11", 3) == "192.168.1.11-192.168.1.13"


def test_ipv4_autofill_does_not_overwrite_manual_ranges_or_single_clone_input():
    assert autofill_ipv4_range("192.168.1.11-192.168.1.20", 3) == "192.168.1.11-192.168.1.20"
    assert autofill_ipv4_range("192.168.1.11", 1) == "192.168.1.11"


def test_ipv4_range_end_calculates_from_the_full_address_integer():
    assert ipv4_range_end("192.168.1.191", 3) == "192.168.1.193"


def test_ipv4_range_end_rejects_address_overflow():
    with pytest.raises(ValueError, match="超出 IPv4 地址范围"):
        ipv4_range_end("255.255.255.255", 2)


def test_each_generated_item_carries_effective_clone_settings():
    plan = build_clone_plan(
        make_form(
            quantity=2,
            cpu_count=8,
            memory_gb=16,
            portgroup_name="VLAN200",
            disks=(DiskRequest(50, "GB"),),
            network=NetworkConfig(ip_mode="dhcp"),
        ),
        make_inventory(),
    )

    assert all(item.datastore_name == "template-ds" for item in plan.items)
    assert all(item.portgroup_name == "VLAN200" for item in plan.items)
    assert all(item.cpu_count == 8 for item in plan.items)
    assert all(item.memory_gb == 16 for item in plan.items)
    assert all(item.disk_requests == (DiskRequest(50, "GB"),) for item in plan.items)


def test_empty_disk_form_produces_empty_effective_item_disk_lists():
    plan = build_clone_plan(
        make_form(disks=(), network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )

    assert plan.disk_requests == ()
    assert all(item.disk_requests == () for item in plan.items)


def test_row_edits_create_a_valid_plan_with_independent_effective_values():
    plan = build_clone_plan(
        make_form(quantity=2, network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )
    edited = (
        replace(
            plan.items[0],
            vm_name="web-a",
            hostname="web-a",
            datastore_name="template-ds",
            portgroup_name="VLAN100",
            cpu_count=4,
            memory_gb=8,
            disk_requests=(DiskRequest(20, "GB"),),
        ),
        replace(
            plan.items[1],
            vm_name="web-b",
            hostname="web-b",
            ip_address=None,
            datastore_name="template-ds",
            portgroup_name="VLAN200",
            cpu_count=12,
            memory_gb=32,
            disk_requests=(),
        ),
    )

    updated = apply_clone_item_edits(plan, edited, make_inventory())

    assert updated.items == edited
    assert updated.items[0].disk_requests == (DiskRequest(20, "GB"),)
    assert updated.items[1].portgroup_name == "VLAN200"


def test_row_edits_reject_duplicate_names_and_ips():
    plan = build_clone_plan(
        make_form(quantity=2, network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )
    duplicate_name = replace(plan.items[1], vm_name=plan.items[0].vm_name)
    with pytest.raises(ValueError, match="批次内.*名称"):
        apply_clone_item_edits(plan, (plan.items[0], duplicate_name), make_inventory())

    static_plan = build_clone_plan(
        make_form(
            quantity=2,
            network=NetworkConfig(ip_mode="static", ip_input="192.168.100.101-192.168.100.102"),
        ),
        make_inventory(),
    )
    duplicate_ip = replace(static_plan.items[1], ip_address=static_plan.items[0].ip_address)
    with pytest.raises(ValueError, match="批次内.*IP"):
        apply_clone_item_edits(
            static_plan,
            (static_plan.items[0], duplicate_ip),
            make_inventory(),
        )


def test_row_edits_reject_unknown_resources_and_invalid_hardware():
    plan = build_clone_plan(
        make_form(network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )
    with pytest.raises(ValueError, match="datastore"):
        apply_clone_item_edits(
            plan,
            (replace(plan.items[0], datastore_name="missing-ds"), plan.items[1]),
            make_inventory(),
        )
    with pytest.raises(ValueError, match="CPU"):
        apply_clone_item_edits(
            plan,
            (replace(plan.items[0], cpu_count=0), plan.items[1]),
            make_inventory(),
        )


def test_single_source_datastore_is_inherited_and_hot_add_is_forced():
    form = make_form(network=NetworkConfig(ip_mode="dhcp"))

    plan = build_clone_plan(form, make_inventory())

    assert plan.datastore_name == "template-ds"
    assert plan.inheritance["datastore"] == "source"
    assert plan.cpu_hot_add_enabled is True
    assert plan.memory_hot_add_enabled is True


def test_multiple_source_datastores_require_explicit_target():
    form = make_form(network=NetworkConfig(ip_mode="dhcp"))

    with pytest.raises(ValueError, match="多个 datastore"):
        build_clone_plan(form, make_inventory(datastores=("ds-1", "ds-2")))


def test_multi_nic_source_cannot_receive_static_ip_without_override():
    form = make_form(network=NetworkConfig(ip_mode="static", ip_input="192.168.100.101-192.168.100.102"))

    with pytest.raises(ValueError, match="多网卡"):
        build_clone_plan(form, make_inventory(networks=("VLAN100", "VLAN200")))


def test_multi_nic_source_still_rejects_static_ip_when_portgroup_is_overridden():
    form = make_form(
        portgroup_name="VLAN200",
        network=NetworkConfig(ip_mode="static", ip_input="192.168.100.101-192.168.100.102"),
    )

    with pytest.raises(ValueError, match="多网卡"):
        build_clone_plan(form, make_inventory(networks=("VLAN100", "VLAN200")))


def test_existing_name_and_ip_conflicts_are_reported_and_can_be_forced():
    inventory = make_inventory(existing_names=("testvm1",), existing_ips=("192.168.100.102",))
    with pytest.raises(ValueError, match="名称已存在"):
        build_clone_plan(make_form(), inventory)

    plan = build_clone_plan(make_form(force_ip_conflicts=True), inventory)
    assert plan.warnings
    assert any("testvm1" in warning for warning in plan.warnings)
    assert any("192.168.100.102" in warning for warning in plan.warnings)


def test_disk_units_use_binary_terabyte_conversion():
    plan = build_clone_plan(make_form(network=NetworkConfig(ip_mode="dhcp")), make_inventory())

    assert plan.disk_requests[0].size_gb == 100
    assert plan.disk_requests[1].size_gb == 1024


def test_clone_concurrency_defaults_to_five_and_accepts_one_to_ten():
    default_plan = build_clone_plan(
        make_form(network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )
    custom_plan = build_clone_plan(
        make_form(network=NetworkConfig(ip_mode="dhcp"), concurrency=8),
        make_inventory(),
    )

    assert default_plan.concurrency == 5
    assert custom_plan.concurrency == 8

    with pytest.raises(ValueError, match="并发"):
        build_clone_plan(
            make_form(network=NetworkConfig(ip_mode="dhcp"), concurrency=11),
            make_inventory(),
        )
