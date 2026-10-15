from __future__ import annotations

from collections.abc import Iterable

from pyVmomi import vim

from app.domain.models import ComputeResource, InventorySnapshot, VmRecord
from .session import VCenterSession


class InventoryService:
    def __init__(self, session: VCenterSession):
        self.session = session

    def load(self, progress=None) -> InventorySnapshot:
        report = progress or (lambda _message: None)
        report("已连接，正在读取虚拟机清单…")
        vms = tuple(self._vm_record(vm) for vm in self._objects([vim.VirtualMachine]))
        report(f"已读取 {len(vms)} 台虚拟机，正在读取计算资源…")
        clusters = [self._compute_record(cluster, "cluster") for cluster in self._objects([vim.ClusterComputeResource])]
        cluster_ids = {cluster.moid for cluster in clusters}
        hosts = []
        for host in self._objects([vim.HostSystem]):
            parent = getattr(host, "parent", None)
            if getattr(parent, "_moId", "") in cluster_ids:
                continue
            hosts.append(self._compute_record(host, "host"))

        report("计算资源已读取，正在读取 datastore、文件夹和端口组…")
        datastores = sorted({getattr(ds, "name", "") for ds in self._objects([vim.Datastore]) if getattr(ds, "name", "")})
        folders = sorted(
            {
                path
                for folder in self._objects([vim.Folder])
                for path in (self._vm_folder_path(folder),)
                if path
            }
        )
        portgroups = sorted({getattr(network, "name", "") for network in self._objects([vim.Network]) if getattr(network, "name", "")})
        customization_specs = self._customization_specs()
        report("资源清单读取完成")
        return InventorySnapshot(
            vms=tuple(sorted(vms, key=lambda item: item.name.casefold())),
            compute_resources=tuple(sorted((*clusters, *hosts), key=lambda item: item.name.casefold())),
            datastores=tuple(datastores),
            folders=tuple(folders),
            portgroups=tuple(portgroups),
            customization_specs=customization_specs,
        )

    def _objects(self, vim_types: list[type]) -> list[object]:
        content = self.session.content
        container = content.viewManager.CreateContainerView(content.rootFolder, vim_types, True)
        try:
            return list(container.view)
        finally:
            container.Destroy()

    def _vm_record(self, vm) -> VmRecord:
        config = getattr(vm, "config", None)
        runtime = getattr(vm, "runtime", None)
        guest = getattr(vm, "guest", None)
        hardware = getattr(config, "hardware", None)
        host = getattr(runtime, "host", None)
        datastores = tuple(sorted({getattr(ds, "name", "") for ds in getattr(vm, "datastore", ()) if getattr(ds, "name", "")}))
        networks = self._vm_networks(vm)
        return VmRecord(
            moid=getattr(vm, "_moId", ""),
            name=getattr(vm, "name", ""),
            is_template=bool(getattr(config, "template", False)),
            power_state=str(getattr(runtime, "powerState", "")),
            uuid=getattr(config, "instanceUuid", "") or getattr(config, "uuid", ""),
            ip_address=getattr(guest, "ipAddress", "") or "",
            host_name=getattr(host, "name", "") or "",
            cluster_name=self._cluster_name(host),
            datastores=datastores,
            networks=networks,
            folder_path=self._vm_folder_path(getattr(vm, "parent", None)),
            guest_id=getattr(config, "guestId", "") or "",
            guest_os=getattr(config, "guestFullName", "") or getattr(guest, "guestFullName", "") or "",
            cpu_count=int(getattr(hardware, "numCPU", 0) or 0),
            memory_mb=int(getattr(hardware, "memoryMB", 0) or 0),
            cpu_hot_add_enabled=bool(getattr(config, "cpuHotAddEnabled", False)),
            memory_hot_add_enabled=bool(getattr(config, "memoryHotAddEnabled", False)),
            tools_status=str(getattr(guest, "toolsStatus", "")),
        )

    @staticmethod
    def _vm_networks(vm) -> tuple[str, ...]:
        names = []
        config = getattr(vm, "config", None)
        hardware = getattr(config, "hardware", None)
        for device in getattr(hardware, "device", ()) or ():
            if not isinstance(device, vim.vm.device.VirtualEthernetCard):
                continue
            backing = getattr(device, "backing", None)
            network_name = getattr(backing, "deviceName", "") or getattr(backing, "networkName", "")
            network = getattr(backing, "network", None)
            network_name = network_name or getattr(network, "name", "")
            if network_name:
                names.append(network_name)
        if not names:
            names.extend(getattr(network, "name", "") for network in getattr(vm, "network", ()) if getattr(network, "name", ""))
        return tuple(names)

    @staticmethod
    def _cluster_name(host) -> str:
        parent = getattr(host, "parent", None)
        return getattr(parent, "name", "") if isinstance(parent, vim.ClusterComputeResource) else ""

    def _compute_record(self, resource, kind: str) -> ComputeResource:
        pool = getattr(resource, "resourcePool", None)
        return ComputeResource(
            moid=getattr(resource, "_moId", ""),
            name=getattr(resource, "name", ""),
            kind=kind,
            datacenter_name=self._datacenter_name(resource),
            resource_pool_moid=getattr(pool, "_moId", "") or "",
        )

    @staticmethod
    def _datacenter_name(obj) -> str:
        current = obj
        while current is not None:
            if isinstance(current, vim.Datacenter):
                return getattr(current, "name", "")
            current = getattr(current, "parent", None)
        return ""

    @staticmethod
    def _vm_folder_path(folder) -> str:
        if folder is None:
            return ""
        parts = []
        current = folder
        while isinstance(current, vim.Folder):
            parent = getattr(current, "parent", None)
            if isinstance(parent, vim.Datacenter):
                vm_root = getattr(parent, "vmFolder", None)
                if not InventoryService._same_managed_object(current, vm_root):
                    return ""
                return "/" + "/".join(reversed(parts)) if parts else ""
            if getattr(current, "name", ""):
                parts.append(current.name)
            current = parent
        return ""

    @staticmethod
    def _same_managed_object(left, right) -> bool:
        if left is right:
            return True
        left_moid = getattr(left, "_moId", "")
        right_moid = getattr(right, "_moId", "")
        return bool(left_moid and right_moid and left_moid == right_moid)

    def _customization_specs(self) -> tuple[str, ...]:
        try:
            manager = self.session.content.customizationSpecManager
            return tuple(sorted(getattr(spec, "name", "") for spec in manager.info if getattr(spec, "name", "")))
        except Exception:
            return ()
