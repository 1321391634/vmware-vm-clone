from __future__ import annotations

import copy
import logging
import socket
import threading
import time

from pyVim.task import WaitForTask
from pyVmomi import vim

from app.domain.models import CloneItem, ClonePlan
from .clone_executor import CloneOutcome, TransientCloneError
from .session import VCenterSession


logger = logging.getLogger("vm-clone")


class TaskWaitTimeout(RuntimeError):
    """The task state could not be confirmed before the safety deadline."""

    retryable = False


class VmwareCloneGateway:
    _folder_creation_lock = threading.RLock()

    def __init__(self, session: VCenterSession):
        self.session = session

    def disconnect(self) -> None:
        self.session.disconnect()

    def clone_one(self, plan: ClonePlan, item: CloneItem) -> CloneOutcome:
        try:
            source = self._find_by_moid(vim.VirtualMachine, plan.source_vm.moid)
            compute = self._find_by_moid(vim.ClusterComputeResource if plan.compute_resource.kind == "cluster" else vim.HostSystem, plan.compute_resource.moid)
            if source is None:
                raise RuntimeError("找不到源虚拟机")
            if compute is None:
                raise RuntimeError("找不到目标计算资源")
            datacenter = self._datacenter_for(compute)
            if datacenter is None:
                raise RuntimeError("无法确定目标数据中心")
            folder = self._get_or_create_folder(datacenter.vmFolder, plan.folder_path)
            datastore_name = item.datastore_name or plan.datastore_name
            datastore = self._find_datastore(compute, datastore_name)
            if datastore is None:
                raise RuntimeError(f"找不到目标 datastore: {datastore_name}")
            resource_pool = getattr(compute, "resourcePool", None)
            if resource_pool is None:
                raise RuntimeError("无法获取目标资源池")

            logger.info(
                "clone source name=%s moid=%s power_state=%s nics=%s",
                getattr(source, "name", item.vm_name),
                getattr(source, "_moId", ""),
                self._power_state(source),
                self._describe_vm_devices(source),
            )
            config = self._build_config_spec(source, plan, datastore, item)
            customization = self._build_customization(source, plan, item)
            logger.info(
                "clone config name=%s num_cpus=%s memory_mb=%s cpu_hot_add=%s memory_hot_add=%s annotation=%s device_changes=%s",
                item.vm_name,
                getattr(config, "numCPUs", None),
                getattr(config, "memoryMB", None),
                getattr(config, "cpuHotAddEnabled", None),
                getattr(config, "memoryHotAddEnabled", None),
                bool(getattr(config, "annotation", "")),
                self._describe_device_changes(getattr(config, "deviceChange", ()) or ()),
            )
            logger.info(
                "clone customization name=%s present=%s identity=%s nic_mapping_count=%s",
                item.vm_name,
                customization is not None,
                self._describe_identity(getattr(customization, "identity", None)),
                len(getattr(customization, "nicSettingMap", ()) or ()) if customization is not None else 0,
            )
            location = vim.vm.RelocateSpec(
                datastore=datastore,
                pool=resource_pool,
                host=None if plan.compute_resource.kind == "cluster" else compute,
            )
            clone_spec = vim.vm.CloneSpec(
                # Submit all device changes while the clone is powered off. The
                # optional power-on is sent directly to the returned VM object
                # after CloneVM_Task completes.
                powerOn=False,
                template=False,
                location=location,
                config=config,
                customization=customization,
            )
            logger.info(
                "clone request name=%s source_moid=%s target_folder=%s datastore=%s compute=%s power_on_after=%s clone_spec_power_on=%s customization=%s portgroup=%s",
                item.vm_name,
                getattr(source, "_moId", ""),
                getattr(folder, "_moId", ""),
                getattr(datastore, "name", datastore_name),
                getattr(compute, "name", plan.compute_resource.name),
                plan.power_on_after,
                getattr(clone_spec, "powerOn", None),
                bool(customization),
                item.portgroup_name or "inherit",
            )
            clone_task = source.Clone(folder=folder, name=item.vm_name, spec=clone_spec)
            logger.info(
                "clone task submitted name=%s task=%s",
                item.vm_name,
                self._describe_task(clone_task),
            )
            self._wait_for_task(clone_task, "克隆")
            logger.info(
                "clone task waited name=%s task=%s",
                item.vm_name,
                self._describe_task(clone_task),
            )
            cloned_vm = getattr(getattr(clone_task, "info", None), "result", None)
            if cloned_vm is None:
                raise RuntimeError("克隆任务已完成，但 vCenter 未返回目标虚拟机对象")
            logger.info(
                "clone task completed name=%s target=%s",
                item.vm_name,
                self._describe_vm(cloned_vm),
            )
            if plan.power_on_after:
                try:
                    self._power_on_created_vm(cloned_vm, item.vm_name)
                except Exception as exc:
                    warning = self._join_warnings(
                        plan.environment_warnings,
                        f"自动开机失败: {exc}",
                    )
                    logger.error(
                        "power-on failed after clone name=%s target_moid=%s error=%s",
                        item.vm_name,
                        getattr(cloned_vm, "_moId", ""),
                        exc,
                    )
                    return CloneOutcome(
                        "克隆成功，但自动开机失败",
                        cloned_vm,
                        warning=warning,
                        success=False,
                        retryable=False,
                    )
            return CloneOutcome(
                "克隆成功",
                cloned_vm,
                warning="；".join(plan.environment_warnings),
            )
        except Exception as exc:
            logger.error(
                "clone failed diagnostic name=%s details=%s",
                item.vm_name,
                self._describe_exception(exc),
            )
            logger.exception("clone failed stack name=%s", item.vm_name)
            if isinstance(exc, TaskWaitTimeout):
                raise
            if self._is_transient(exc):
                raise TransientCloneError(str(exc)) from exc
            raise

    def _power_on_created_vm(self, vm, name: str) -> None:
        """Power on the object returned by CloneVM_Task without name polling."""
        logger.info("power-on begin name=%s target=%s", name, self._describe_vm(vm))
        runtime = getattr(vm, "runtime", None)
        if getattr(runtime, "powerState", None) == vim.VirtualMachinePowerState.poweredOn:
            logger.info("power-on skipped; already powered on name=%s", name)
            return

        logger.info(
            "power-on submitted name=%s target_moid=%s",
            name,
            getattr(vm, "_moId", ""),
        )
        power_task = vm.PowerOnVM_Task()
        logger.info(
            "power-on task submitted name=%s target_moid=%s task=%s",
            name,
            getattr(vm, "_moId", ""),
            self._describe_task(power_task),
        )
        self._wait_for_task(power_task, "开机")

        power_state = getattr(getattr(vm, "runtime", None), "powerState", None)
        if isinstance(power_state, str) and power_state != vim.VirtualMachinePowerState.poweredOn:
            raise RuntimeError(f"目标虚拟机当前状态为 {power_state}")
        logger.info(
            "power-on completed name=%s target=%s task=%s",
            name,
            self._describe_vm(vm),
            self._describe_task(power_task),
        )

    def _wait_for_task(self, task, label: str) -> None:
        """Wait without losing a submitted task when a SOAP read times out."""
        configured_timeout = self._safe_attr(self.session, "task_wait_timeout", 1800)
        deadline = time.monotonic() + max(1.0, float(configured_timeout))
        timeout_count = 0
        while True:
            try:
                WaitForTask(task)
                return
            except Exception as exc:
                if not self._is_task_read_timeout(exc):
                    raise
                timeout_count += 1
                state, task_error = self._read_task_state(task)
                logger.warning(
                    "task wait read timeout label=%s task=%s count=%s state=%s error=%s",
                    label,
                    self._safe_attr(task, "_moId", "") or "",
                    timeout_count,
                    state or "unknown",
                    self._describe_exception(task_error) if task_error is not None else None,
                )
                if state == vim.TaskInfo.State.success:
                    return
                if state == vim.TaskInfo.State.error:
                    if task_error is not None:
                        raise task_error
                    raise RuntimeError(f"{label}任务报告失败，但 vCenter 未返回错误详情")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TaskWaitTimeout(
                        f"{label}任务状态在 {configured_timeout:g} 秒内无法确认，已停止重试以避免重复创建"
                    ) from exc
                time.sleep(min(1.0, remaining))

    @classmethod
    def _read_task_state(cls, task):
        try:
            info = cls._safe_attr(task, "info")
            return cls._safe_attr(info, "state"), cls._safe_attr(info, "error")
        except Exception as exc:
            if cls._is_task_read_timeout(exc):
                return None, None
            raise

    @staticmethod
    def _is_task_read_timeout(exc: Exception) -> bool:
        text = str(exc).casefold()
        return isinstance(exc, (TimeoutError, socket.timeout)) or "read operation timed out" in text

    @staticmethod
    def _join_warnings(*groups: tuple[str, ...] | list[str] | str) -> str:
        values = []
        for group in groups:
            if isinstance(group, str):
                if group:
                    values.append(group)
            else:
                values.extend(value for value in group if value)
        return "；".join(values)

    def find_vm_by_name(self, name: str):
        return self._find_by_name(vim.VirtualMachine, name)

    @staticmethod
    def _safe_attr(obj, name: str, default=None):
        try:
            return getattr(obj, name, default)
        except Exception:
            return default

    @classmethod
    def _describe_device(cls, device) -> dict[str, object]:
        backing = cls._safe_attr(device, "backing")
        port = cls._safe_attr(backing, "port")
        connectable = cls._safe_attr(device, "connectable")
        network = cls._safe_attr(backing, "network")
        return {
            "device_class": type(device).__name__,
            "device_key": cls._safe_attr(device, "key"),
            "backing_class": type(backing).__name__ if backing is not None else "",
            "device_name": cls._safe_attr(backing, "deviceName", "") or "",
            "network_name": cls._safe_attr(backing, "networkName", "") or "",
            "network_object_name": cls._safe_attr(network, "name", "") or "",
            "portgroup_key": cls._safe_attr(port, "portgroupKey", "") or "",
            "port_key": cls._safe_attr(port, "portKey", "") or "",
            "switch_uuid": cls._safe_attr(port, "switchUuid", "") or "",
            "start_connected": cls._safe_attr(connectable, "startConnected"),
            "connected": cls._safe_attr(connectable, "connected"),
            "allow_guest_control": cls._safe_attr(connectable, "allowGuestControl"),
            "wake_on_lan": cls._safe_attr(device, "wakeOnLanEnabled"),
            "external_id": cls._safe_attr(device, "externalId", "") or "",
            "sriov_backing_class": type(cls._safe_attr(device, "sriovBacking")).__name__
            if cls._safe_attr(device, "sriovBacking") is not None
            else "",
        }

    @classmethod
    def _describe_vm_devices(cls, vm) -> list[dict[str, object]]:
        config = cls._safe_attr(vm, "config")
        hardware = cls._safe_attr(config, "hardware")
        return [
            cls._describe_device(device)
            for device in cls._safe_attr(hardware, "device", ()) or ()
            if isinstance(device, vim.vm.device.VirtualEthernetCard)
        ]

    @classmethod
    def _describe_device_changes(cls, changes) -> list[dict[str, object]]:
        result = []
        for change in changes:
            device = cls._safe_attr(change, "device")
            result.append(
                {
                    "operation": cls._safe_attr(change, "operation", ""),
                    "file_operation": cls._safe_attr(change, "fileOperation", ""),
                    "device": cls._describe_device(device) if device is not None else None,
                }
            )
        return result

    @classmethod
    def _describe_vm(cls, vm) -> dict[str, object]:
        runtime = cls._safe_attr(vm, "runtime")
        host = cls._safe_attr(runtime, "host")
        return {
            "moid": cls._safe_attr(vm, "_moId", "") or "",
            "name": cls._safe_attr(vm, "name", "") or "",
            "power_state": cls._safe_attr(runtime, "powerState", "") or "",
            "host": cls._safe_attr(host, "name", "") or "",
            "nics": cls._describe_vm_devices(vm),
        }

    @classmethod
    def _power_state(cls, vm) -> object:
        return cls._safe_attr(cls._safe_attr(vm, "runtime"), "powerState", "") or ""

    @classmethod
    def _describe_task(cls, task) -> dict[str, object]:
        info = cls._safe_attr(task, "info")
        error = cls._safe_attr(info, "error")
        return {
            "type": type(task).__name__ if task is not None else "",
            "moid": cls._safe_attr(task, "_moId", "") or "",
            "state": cls._safe_attr(info, "state", "") or "",
            "error": cls._describe_exception(error) if error is not None else None,
            "result_type": type(cls._safe_attr(info, "result")).__name__
            if cls._safe_attr(info, "result") is not None
            else "",
        }

    @classmethod
    def _describe_identity(cls, identity) -> dict[str, object] | None:
        if identity is None:
            return None
        user_data = cls._safe_attr(identity, "userData")
        computer_name = cls._safe_attr(user_data, "computerName")
        host_name = cls._safe_attr(identity, "hostName")
        fixed_name = computer_name or host_name
        return {
            "class": type(identity).__name__,
            "hostname": cls._safe_attr(fixed_name, "name", "") or "",
        }

    @classmethod
    def _describe_exception(cls, exc) -> dict[str, object]:
        if exc is None:
            return {}
        fault_messages = []
        raw_messages = cls._safe_attr(exc, "faultMessage", ()) or ()
        if not isinstance(raw_messages, (list, tuple)):
            raw_messages = (raw_messages,)
        for fault_message in raw_messages:
            message = cls._safe_attr(fault_message, "message", fault_message)
            if message:
                fault_messages.append(str(message))
        return {
            "type": f"{type(exc).__module__}.{type(exc).__name__}",
            "text": str(exc),
            "repr": repr(exc),
            "localized_message": cls._safe_attr(exc, "localizedMessage", "") or "",
            "msg": cls._safe_attr(exc, "msg", "") or "",
            "fault_messages": fault_messages,
        }

    def _build_config_spec(
        self,
        source,
        plan: ClonePlan,
        datastore=None,
        item: CloneItem | None = None,
    ):
        item = item or plan.items[0]
        config = vim.vm.ConfigSpec()
        config.numCPUs = item.cpu_count
        config.memoryMB = item.memory_gb * 1024
        config.cpuHotAddEnabled = True
        config.memoryHotAddEnabled = True
        config.guestId = getattr(getattr(source, "config", None), "guestId", "")
        config.annotation = plan.remark
        config.deviceChange = []
        if item.portgroup_name:
            self._replace_network(config, source, item.portgroup_name)
        else:
            self._normalize_inherited_dvs_ports(config, source)
        self._append_disks(config, source, item, datastore)
        return config

    @staticmethod
    def _normalize_inherited_dvs_ports(config, source) -> None:
        """Keep the source DVS port group but never reuse its concrete port."""
        hardware = getattr(getattr(source, "config", None), "hardware", None)
        for device in getattr(hardware, "device", ()) or ():
            if not isinstance(device, vim.vm.device.VirtualEthernetCard):
                continue
            backing = getattr(device, "backing", None)
            if not isinstance(
                backing,
                vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo,
            ):
                continue
            port = getattr(backing, "port", None)
            port_key = getattr(port, "portKey", "") if port is not None else ""
            portgroup_key = getattr(port, "portgroupKey", "") if port is not None else ""
            switch_uuid = getattr(port, "switchUuid", "") if port is not None else ""
            if not port_key or not portgroup_key or not switch_uuid:
                continue

            cloned_device = copy.deepcopy(device)
            cloned_device.backing = vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo(
                port=vim.dvs.PortConnection(
                    portgroupKey=portgroup_key,
                    switchUuid=switch_uuid,
                )
            )
            config.deviceChange.append(
                vim.vm.device.VirtualDeviceSpec(
                    device=cloned_device,
                    operation=vim.vm.device.VirtualDeviceSpec.Operation.edit,
                )
            )

    def _replace_network(self, config, source, portgroup_name: str) -> None:
        hardware = getattr(getattr(source, "config", None), "hardware", None)
        for device in getattr(hardware, "device", ()) or ():
            if isinstance(device, vim.vm.device.VirtualEthernetCard):
                config.deviceChange.append(
                    vim.vm.device.VirtualDeviceSpec(
                        device=device,
                        operation=vim.vm.device.VirtualDeviceSpec.Operation.remove,
                    )
                )
        network = self._find_network_by_name(portgroup_name)
        if network is None:
            raise RuntimeError(f"找不到目标端口组: {portgroup_name}")
        network_config = getattr(network, "config", None)
        dvs = getattr(network_config, "distributedVirtualSwitch", None)
        logger.info(
            "selected network name=%s class=%s moid=%s key=%s config_class=%s is_dvs=%s dvs_moid=%s dvs_uuid=%s",
            getattr(network, "name", portgroup_name),
            type(network).__name__,
            getattr(network, "_moId", ""),
            getattr(network, "key", ""),
            type(network_config).__name__ if network_config is not None else "",
            isinstance(network, vim.dvs.DistributedVirtualPortgroup),
            getattr(dvs, "_moId", "") if dvs is not None else "",
            getattr(dvs, "uuid", "") if dvs is not None else "",
        )
        nic = vim.vm.device.VirtualVmxnet3()
        nic.key = -100
        nic.addressType = "generated"
        nic.wakeOnLanEnabled = True
        nic.connectable = vim.vm.device.VirtualDevice.ConnectInfo(
            startConnected=True,
            allowGuestControl=True,
            connected=True,
        )
        nic.backing = self._network_backing(network)
        config.deviceChange.append(
            vim.vm.device.VirtualDeviceSpec(
                device=nic,
                operation=vim.vm.device.VirtualDeviceSpec.Operation.add,
            )
        )

    @staticmethod
    def _network_backing(network):
        dvs = getattr(getattr(network, "config", None), "distributedVirtualSwitch", None)
        if isinstance(network, vim.dvs.DistributedVirtualPortgroup) or dvs is not None:
            if dvs is None:
                raise RuntimeError(
                    f"DVS 端口组缺少 distributedVirtualSwitch 引用: {getattr(network, 'name', '')}"
                )
            switch_uuid = getattr(dvs, "uuid", "")
            portgroup_key = getattr(network, "key", "")
            if not switch_uuid or not portgroup_key:
                raise RuntimeError(
                    "DVS 端口组缺少有效的 portgroup key 或 switch UUID: "
                    f"{getattr(network, 'name', '')}"
                )
            return vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo(
                port=vim.dvs.PortConnection(
                    portgroupKey=portgroup_key,
                    switchUuid=switch_uuid,
                )
            )
        return vim.vm.device.VirtualEthernetCard.NetworkBackingInfo(
            deviceName=network.name,
            network=network,
        )

    def _find_network_by_name(self, name: str):
        """Resolve DVS port groups before generic Network objects.

        vCenter can contain a standard network and a DVS port group with the
        same display name. Resolving through vim.Network alone makes the
        result order-dependent and can silently produce the wrong backing.
        """
        dvs_portgroup = self._find_by_name(vim.dvs.DistributedVirtualPortgroup, name)
        return dvs_portgroup or self._find_by_name(vim.Network, name)

    @staticmethod
    def _append_disks(config, source, plan_or_item, datastore=None) -> None:
        if not plan_or_item.disk_requests:
            return
        devices = getattr(getattr(getattr(source, "config", None), "hardware", None), "device", ()) or ()
        controllers = [
            device
            for device in devices
            if isinstance(
                device,
                (
                    vim.vm.device.VirtualSCSIController,
                    vim.vm.device.ParaVirtualSCSIController,
                    vim.vm.device.VirtualLsiLogicController,
                    vim.vm.device.VirtualLsiLogicSASController,
                ),
            )
        ]
        if not controllers:
            raise RuntimeError("源虚拟机没有可用的 SCSI 控制器")
        controller = controllers[0]
        used_units = {
            device.unitNumber
            for device in devices
            if isinstance(device, vim.vm.device.VirtualDisk) and device.controllerKey == controller.key
        }
        unit_number = 1
        for request in plan_or_item.disk_requests:
            while unit_number in used_units or unit_number == 7:
                unit_number += 1
            disk = vim.vm.device.VirtualDisk()
            disk.key = -200 - len(config.deviceChange)
            disk.controllerKey = controller.key
            disk.unitNumber = unit_number
            disk.capacityInKB = request.size_gb * 1024 * 1024
            disk.backing = vim.vm.device.VirtualDisk.FlatVer2BackingInfo(
                fileName="",
                diskMode="persistent",
                thinProvisioned=True,
            )
            if datastore is not None:
                disk.backing.datastore = datastore
            spec = vim.vm.device.VirtualDeviceSpec(
                operation=vim.vm.device.VirtualDeviceSpec.Operation.add,
                fileOperation=vim.vm.device.VirtualDeviceSpec.FileOperation.create,
                device=disk,
            )
            config.deviceChange.append(spec)
            used_units.add(unit_number)
            unit_number += 1

    def _build_customization(self, source, plan: ClonePlan, item: CloneItem):
        # Match the original VMCloner: one adapter mapping is submitted even
        # when the source VM keeps multiple inherited network adapters.
        mappings = [self._adapter_mapping(plan, item)]
        dns_servers = list(plan.network.dns_servers) if plan.network.dns_mode == "manual" else []
        guest_id = (getattr(getattr(source, "config", None), "guestId", "") or "").lower()
        if plan.customization_spec_name:
            try:
                manager = self.session.content.customizationSpecManager
                base = manager.GetCustomizationSpec(name=plan.customization_spec_name).spec
                identity = copy.deepcopy(getattr(base, "identity", None))
                if not self._set_identity_hostname(identity, item.hostname):
                    identity = self._default_identity(guest_id, item.hostname)
                global_ip = copy.deepcopy(getattr(base, "globalIPSettings", None))
                global_ip = global_ip or vim.vm.customization.GlobalIPSettings()
                if dns_servers:
                    global_ip.dnsServerList = dns_servers
                return vim.vm.customization.Specification(
                    identity=identity,
                    globalIPSettings=global_ip,
                    nicSettingMap=mappings,
                )
            except Exception:
                # Keep hostname/IP customization working even when a saved spec is incomplete.
                pass

        return vim.vm.customization.Specification(
            identity=self._default_identity(guest_id, item.hostname),
            globalIPSettings=vim.vm.customization.GlobalIPSettings(
                dnsServerList=dns_servers if dns_servers else None
            ),
            nicSettingMap=mappings,
        )

    @staticmethod
    def _default_identity(guest_id: str, hostname: str):
        if "windows" in guest_id:
            identity = vim.vm.customization.Sysprep()
            identity.userData = vim.vm.customization.UserData(
                computerName=vim.vm.customization.FixedName(name=hostname),
                fullName="Administrator",
                orgName="Organization",
            )
            identity.guiUnattended = vim.vm.customization.GuiUnattended(timeZone=85)
            identity.identification = vim.vm.customization.Identification(joinWorkgroup="WORKGROUP")
            return identity
        return vim.vm.customization.LinuxPrep(
            hostName=vim.vm.customization.FixedName(name=hostname),
            domain="localdomain",
        )

    def _adapter_mapping(self, plan: ClonePlan, item: CloneItem):
        settings = vim.vm.customization.IPSettings()
        if item.ip_address:
            settings.ip = vim.vm.customization.FixedIp(ipAddress=item.ip_address)
            settings.subnetMask = plan.network.subnet_mask or "255.255.255.0"
            if plan.network.gateway:
                settings.gateway = [plan.network.gateway]
        else:
            settings.ip = vim.vm.customization.DhcpIpGenerator()
        mapping = vim.vm.customization.AdapterMapping()
        mapping.adapter = settings
        return mapping

    @staticmethod
    def _set_identity_hostname(identity, hostname: str) -> bool:
        if isinstance(identity, vim.vm.customization.Sysprep):
            identity.userData = identity.userData or vim.vm.customization.UserData()
            identity.userData.computerName = vim.vm.customization.FixedName(name=hostname)
            return True
        elif isinstance(identity, vim.vm.customization.LinuxPrep):
            identity.hostName = vim.vm.customization.FixedName(name=hostname)
            return True
        return False

    def _find_datastore(self, compute, name: str):
        hosts = getattr(compute, "host", ()) if isinstance(compute, vim.ClusterComputeResource) else (compute,)
        for host in hosts:
            for datastore in getattr(host, "datastore", ()) or ():
                if getattr(datastore, "name", "") == name:
                    return datastore
        return self._find_by_name(vim.Datastore, name)

    def _get_or_create_folder(self, root, folder_path: str):
        parts = [part.strip() for part in folder_path.replace("\\", "/").split("/") if part.strip()]
        root_name = getattr(root, "name", "") or ""
        if parts and root_name and parts[0].casefold() == root_name.casefold():
            parts = parts[1:]

        with self._folder_creation_lock:
            current = root
            for part in parts:
                child = self._find_child_folder(current, part)
                if child is not None:
                    current = child
                    continue
                try:
                    current = current.CreateFolder(part)
                except Exception as exc:
                    child = self._find_child_folder(current, part)
                    if child is None and self._is_duplicate_name_error(exc):
                        child = self._find_folder_by_parent(current, part)
                    if child is None or not self._is_duplicate_name_error(exc):
                        raise
                    current = child
            return current

    @staticmethod
    def _find_child_folder(parent, name: str):
        return next(
            (
                entity
                for entity in getattr(parent, "childEntity", ()) or ()
                if isinstance(entity, vim.Folder) and getattr(entity, "name", "") == name
            ),
            None,
        )

    def _find_folder_by_parent(self, parent, name: str):
        try:
            folders = self._objects([vim.Folder])
        except Exception:
            return None
        parent_moid = getattr(parent, "_moId", "")
        return next(
            (
                folder
                for folder in folders
                if getattr(folder, "name", "") == name
                and (
                    getattr(folder, "parent", None) is parent
                    or (
                        parent_moid
                        and getattr(getattr(folder, "parent", None), "_moId", "") == parent_moid
                    )
                )
            ),
            None,
        )

    @staticmethod
    def _is_duplicate_name_error(exc: Exception) -> bool:
        text = str(exc).casefold()
        return any(
            marker in text
            for marker in (
                "duplicatename",
                "duplicate name",
                "already exists",
                "alreadyexist",
                "名称已存在",
                "已存在",
            )
        )

    @staticmethod
    def _datacenter_for(obj):
        current = obj
        while current is not None:
            if isinstance(current, vim.Datacenter):
                return current
            current = getattr(current, "parent", None)
        return None

    def _find_by_moid(self, vim_type, moid: str):
        return next((obj for obj in self._objects([vim_type]) if getattr(obj, "_moId", "") == moid), None)

    def _find_by_name(self, vim_type, name: str):
        return next((obj for obj in self._objects([vim_type]) if getattr(obj, "name", "") == name), None)

    def _objects(self, vim_types: list[type]):
        content = self.session.content
        container = content.viewManager.CreateContainerView(content.rootFolder, vim_types, True)
        try:
            return list(container.view)
        finally:
            container.Destroy()

    @staticmethod
    def _is_transient(exc: Exception) -> bool:
        text = str(exc).lower()
        return any(marker in text for marker in ("hostconnectfault", "cannot connect to host", "connect to host", "timed out", "timeout"))
