from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class VmRecord:
    moid: str
    name: str
    is_template: bool
    power_state: str
    uuid: str = ""
    ip_address: str = ""
    host_name: str = ""
    cluster_name: str = ""
    datastores: tuple[str, ...] = ()
    networks: tuple[str, ...] = ()
    folder_path: str = ""
    guest_id: str = ""
    guest_os: str = ""
    cpu_count: int = 0
    memory_mb: int = 0
    cpu_hot_add_enabled: bool = False
    memory_hot_add_enabled: bool = False
    tools_status: str = ""


@dataclass(frozen=True)
class ComputeResource:
    moid: str
    name: str
    kind: Literal["cluster", "host"]
    datacenter_name: str = ""
    resource_pool_moid: str = ""


@dataclass(frozen=True)
class NetworkConfig:
    ip_mode: Literal["dhcp", "static"] = "dhcp"
    ip_input: str = ""
    subnet_mask: str = "255.255.255.0"
    gateway: str = ""
    dns_mode: Literal["dhcp", "manual"] = "dhcp"
    dns_servers: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiskRequest:
    size: float
    unit: Literal["GB", "TB"]

    @property
    def size_gb(self) -> int:
        return int(self.size * (1024 if self.unit == "TB" else 1))


@dataclass(frozen=True)
class CloneForm:
    source_vm_id: str
    quantity: int
    compute_resource_id: str
    folder_path: str
    datastore_name: str | None
    customization_spec_name: str | None
    vm_name_prefix: str
    hostname_prefix: str
    portgroup_name: str | None
    cpu_count: int | None
    memory_gb: int | None
    disks: tuple[DiskRequest, ...]
    network: NetworkConfig
    remark: str = ""
    power_on_after: bool = False
    force_ip_conflicts: bool = False
    concurrency: int = 5


@dataclass(frozen=True)
class CloneItem:
    sequence: int
    vm_name: str
    hostname: str
    ip_address: str | None
    datastore_name: str = ""
    portgroup_name: str | None = None
    cpu_count: int = 0
    memory_gb: int = 0
    disk_requests: tuple[DiskRequest, ...] = ()


@dataclass(frozen=True)
class InventorySnapshot:
    vms: tuple[VmRecord, ...] = ()
    compute_resources: tuple[ComputeResource, ...] = ()
    datastores: tuple[str, ...] = ()
    folders: tuple[str, ...] = ()
    portgroups: tuple[str, ...] = ()
    customization_specs: tuple[str, ...] = ()

    def vm_by_id(self, moid: str) -> VmRecord | None:
        return next((vm for vm in self.vms if vm.moid == moid), None)

    def compute_by_id(self, moid: str) -> ComputeResource | None:
        return next((item for item in self.compute_resources if item.moid == moid), None)


@dataclass(frozen=True)
class ClonePlan:
    source_vm: VmRecord
    compute_resource: ComputeResource
    folder_path: str
    datastore_name: str
    portgroup_name: str | None
    customization_spec_name: str | None
    cpu_count: int
    memory_gb: int
    cpu_hot_add_enabled: bool
    memory_hot_add_enabled: bool
    disk_requests: tuple[DiskRequest, ...]
    network: NetworkConfig
    remark: str
    power_on_after: bool
    items: tuple[CloneItem, ...]
    inheritance: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    concurrency: int = 5
    environment_warnings: tuple[str, ...] = ()
    force_ip_conflicts: bool = False
