from __future__ import annotations

from dataclasses import replace

from .customization import linux_customization_warning
from .models import CloneForm, CloneItem, ClonePlan, DiskRequest, InventorySnapshot
from .validation import (
    parse_ipv4,
    parse_ipv4_range,
    validate_optional_ipv4,
    validate_hostname,
    validate_vm_name,
)


def _numbered(value: str, quantity: int) -> tuple[str, ...]:
    if quantity == 1:
        return (value.strip(),)
    return tuple(f"{value.strip()}{index}" for index in range(1, quantity + 1))


def _validate_disks(disks: tuple[DiskRequest, ...]) -> tuple[DiskRequest, ...]:
    normalized = []
    for disk in disks:
        if disk.unit not in {"GB", "TB"}:
            raise ValueError("硬盘单位只支持 GB 或 TB")
        if disk.size <= 0:
            raise ValueError("硬盘容量必须大于 0")
        normalized.append(disk)
    return tuple(normalized)


def apply_clone_item_edits(
    plan: ClonePlan,
    edited_items: tuple[CloneItem, ...] | list[CloneItem],
    inventory: InventorySnapshot,
) -> ClonePlan:
    """Validate and apply the effective settings edited for each batch row."""
    expected_sequences = tuple(item.sequence for item in plan.items)
    provided = tuple(edited_items)
    if tuple(item.sequence for item in provided) != expected_sequences:
        raise ValueError("批次预览行与克隆数量不一致")

    normalized: list[CloneItem] = []
    for item in provided:
        vm_name = validate_vm_name(item.vm_name)
        hostname = validate_hostname(item.hostname)
        ip_address = None
        if item.ip_address is not None and str(item.ip_address).strip() not in {"", "DHCP"}:
            ip_address = parse_ipv4(str(item.ip_address))

        datastore_name = str(item.datastore_name or plan.datastore_name).strip()
        if datastore_name not in inventory.datastores:
            raise ValueError(f"第 {item.sequence} 行找不到目标 datastore: {datastore_name}")

        portgroup_name = item.portgroup_name
        if portgroup_name is not None:
            portgroup_name = str(portgroup_name).strip() or None
        if portgroup_name is not None and portgroup_name not in inventory.portgroups:
            raise ValueError(f"第 {item.sequence} 行找不到目标端口组: {portgroup_name}")

        cpu_count = int(item.cpu_count)
        memory_gb = int(item.memory_gb)
        if cpu_count <= 0 or memory_gb <= 0:
            raise ValueError(f"第 {item.sequence} 行 CPU 和内存必须大于 0")

        normalized.append(
            replace(
                item,
                vm_name=vm_name,
                hostname=hostname,
                ip_address=ip_address,
                datastore_name=datastore_name,
                portgroup_name=portgroup_name,
                cpu_count=cpu_count,
                memory_gb=memory_gb,
                disk_requests=_validate_disks(tuple(item.disk_requests)),
            )
        )

    names = [item.vm_name for item in normalized]
    if len(set(names)) != len(names):
        raise ValueError("批次内生成了重复的名称")
    hostnames = [item.hostname for item in normalized]
    if len(set(hostnames)) != len(hostnames):
        raise ValueError("批次内生成了重复的 hostname")
    addresses = [item.ip_address for item in normalized if item.ip_address]
    if len(set(addresses)) != len(addresses):
        raise ValueError("批次内生成了重复的 IP 地址")
    if any(item.ip_address for item in normalized) and len(plan.source_vm.networks) > 1:
        raise ValueError("源虚拟机多网卡时禁止使用静态 IP")
    if plan.network.ip_mode == "static" and any(item.ip_address is None for item in normalized):
        raise ValueError("静态 IPv4 模式下每台虚拟机都必须有 IP 地址")

    existing_names = {
        vm.name for vm in inventory.vms if vm.moid != plan.source_vm.moid
    }
    reported_ips = {vm.ip_address for vm in inventory.vms if vm.ip_address}
    conflict_messages: list[str] = []
    name_conflicts = sorted(existing_names.intersection(names))
    ip_conflicts = sorted(reported_ips.intersection(addresses))
    if name_conflicts:
        conflict_messages.append(f"名称已存在: {', '.join(name_conflicts)}")
    if ip_conflicts:
        conflict_messages.append(f"IP 可能已被使用: {', '.join(ip_conflicts)}")
    if conflict_messages and not plan.force_ip_conflicts:
        raise ValueError("；".join(conflict_messages))

    return replace(
        plan,
        items=tuple(normalized),
        warnings=tuple(conflict_messages),
    )


def build_clone_plan(form: CloneForm, inventory: InventorySnapshot) -> ClonePlan:
    if not isinstance(form.quantity, int) or form.quantity < 1 or form.quantity > 1000:
        raise ValueError("克隆数量必须是 1 到 1000 之间的整数")
    if not isinstance(form.concurrency, int) or not 1 <= form.concurrency <= 10:
        raise ValueError("克隆并发必须是 1 到 10 之间的整数")

    source = inventory.vm_by_id(form.source_vm_id)
    if source is None:
        raise ValueError("找不到源虚拟机")
    compute = inventory.compute_by_id(form.compute_resource_id)
    if compute is None:
        raise ValueError("找不到目标计算资源")

    vm_prefix = validate_vm_name(form.vm_name_prefix)
    hostname_prefix = validate_hostname(form.hostname_prefix)
    vm_names = tuple(validate_vm_name(name) for name in _numbered(vm_prefix, form.quantity))
    hostnames = tuple(validate_hostname(name) for name in _numbered(hostname_prefix, form.quantity))

    if form.folder_path.strip() == "":
        raise ValueError("虚拟机文件夹不能为空")

    inheritance: dict[str, str] = {}
    if form.datastore_name:
        if form.datastore_name not in inventory.datastores:
            raise ValueError(f"找不到目标 datastore: {form.datastore_name}")
        datastore_name = form.datastore_name
        inheritance["datastore"] = "custom"
    elif len(source.datastores) == 1:
        datastore_name = source.datastores[0]
        inheritance["datastore"] = "source"
    elif len(source.datastores) > 1:
        raise ValueError("源虚拟机有多个 datastore，必须手动选择目标存储")
    else:
        raise ValueError("源虚拟机没有可继承的 datastore")

    if form.portgroup_name:
        if form.portgroup_name not in inventory.portgroups:
            raise ValueError(f"找不到目标端口组: {form.portgroup_name}")
        portgroup_name = form.portgroup_name
        inheritance["portgroup"] = "custom"
    else:
        portgroup_name = None
        inheritance["portgroup"] = "source"

    network = form.network
    if network.ip_mode not in {"dhcp", "static"}:
        raise ValueError("IP 模式必须是 DHCP 或静态")
    if network.dns_mode not in {"dhcp", "manual"}:
        raise ValueError("DNS 模式必须是 DHCP 或手动")
    if len(source.networks) > 1 and network.ip_mode == "static":
        raise ValueError("源虚拟机多网卡时禁止使用静态 IP")

    addresses: tuple[str, ...] = ()
    if network.ip_mode == "static":
        addresses = parse_ipv4_range(network.ip_input)
        if len(addresses) != form.quantity:
            raise ValueError("IP 地址数量必须等于克隆数量")
        validate_optional_ipv4(network.subnet_mask, "子网掩码")
        validate_optional_ipv4(network.gateway, "网关")
        if network.dns_mode == "manual":
            if not 1 <= len(network.dns_servers) <= 2:
                raise ValueError("手动 DNS 必须填写 1 到 2 个地址")
            for dns in network.dns_servers:
                parse_ipv4_range(dns)
    elif network.dns_mode == "manual":
        if not 1 <= len(network.dns_servers) <= 2:
            raise ValueError("手动 DNS 必须填写 1 到 2 个地址")
        for dns in network.dns_servers:
            parse_ipv4_range(dns)

    customization_name = form.customization_spec_name or None
    if customization_name and customization_name not in inventory.customization_specs:
        raise ValueError(f"找不到自定义规范: {customization_name}")

    cpu_count = form.cpu_count if form.cpu_count is not None else source.cpu_count
    memory_gb = form.memory_gb if form.memory_gb is not None else max(1, round(source.memory_mb / 1024))
    if cpu_count <= 0 or memory_gb <= 0:
        raise ValueError("CPU 和内存必须大于 0")
    disk_requests = _validate_disks(form.disks)

    existing_names = {vm.name for vm in inventory.vms if vm.moid != source.moid}
    name_conflicts = sorted(existing_names.intersection(vm_names))
    reported_ips = {vm.ip_address for vm in inventory.vms if vm.ip_address}
    ip_conflicts = sorted(reported_ips.intersection(addresses))
    warnings = []
    conflicts = []
    if name_conflicts:
        conflicts.append(f"名称已存在: {', '.join(name_conflicts)}")
    if ip_conflicts:
        conflicts.append(f"IP 可能已被使用: {', '.join(ip_conflicts)}")
    if conflicts and not form.force_ip_conflicts:
        raise ValueError("；".join(conflicts))
    if conflicts:
        warnings.extend(conflicts)

    items = tuple(
        CloneItem(
            sequence=index,
            vm_name=vm_names[index - 1],
            hostname=hostnames[index - 1],
            ip_address=addresses[index - 1] if addresses else None,
            datastore_name=datastore_name,
            portgroup_name=portgroup_name,
            cpu_count=cpu_count,
            memory_gb=memory_gb,
            disk_requests=disk_requests,
        )
        for index in range(1, form.quantity + 1)
    )
    if len(set(vm_names)) != len(vm_names):
        raise ValueError("批次内生成了重复的虚拟机名称")
    if len(set(hostnames)) != len(hostnames):
        raise ValueError("批次内生成了重复的 hostname")
    if len(set(addresses)) != len(addresses):
        raise ValueError("批次内生成了重复的 IP 地址")

    inheritance["cpu"] = "source" if form.cpu_count is None else "custom"
    inheritance["memory"] = "source" if form.memory_gb is None else "custom"
    environment_warnings = tuple(
        warning
        for warning in (linux_customization_warning(source.guest_id),)
        if warning
    )
    return ClonePlan(
        source_vm=source,
        compute_resource=compute,
        folder_path=form.folder_path.strip(),
        datastore_name=datastore_name,
        portgroup_name=portgroup_name,
        customization_spec_name=customization_name,
        cpu_count=cpu_count,
        memory_gb=memory_gb,
        cpu_hot_add_enabled=True,
        memory_hot_add_enabled=True,
        disk_requests=disk_requests,
        network=network,
        remark=form.remark,
        power_on_after=form.power_on_after,
        items=items,
        inheritance=inheritance,
        warnings=tuple(warnings),
        concurrency=form.concurrency,
        environment_warnings=environment_warnings,
        force_ip_conflicts=form.force_ip_conflicts,
    )
