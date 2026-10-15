from __future__ import annotations

import threading
import time
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyVmomi import vim  # noqa: E402

from app.domain.models import NetworkConfig, DiskRequest  # noqa: E402
from app.domain.planning import build_clone_plan  # noqa: E402
from app.vmware import clone_gateway as clone_gateway_module  # noqa: E402
from app.vmware.clone_gateway import VmwareCloneGateway  # noqa: E402
from app.vmware.inventory import InventoryService  # noqa: E402
from test_domain import make_form, make_inventory  # noqa: E402


def test_diagnostic_device_summary_includes_dvs_port_identity_and_connection_state():
    nic = vim.vm.device.VirtualVmxnet3()
    nic.key = 4000
    nic.connectable = vim.vm.device.VirtualDevice.ConnectInfo(
        startConnected=False,
        allowGuestControl=False,
        connected=False,
    )
    nic.backing = vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo(
        port=vim.dvs.PortConnection(
            portgroupKey="dvportgroup-201",
            portKey="170",
            switchUuid="dvs-1",
        )
    )

    summary = VmwareCloneGateway._describe_device(nic)

    assert summary["device_key"] == 4000
    assert summary["backing_class"].endswith("DistributedVirtualPortBackingInfo")
    assert summary["portgroup_key"] == "dvportgroup-201"
    assert summary["port_key"] == "170"
    assert summary["switch_uuid"] == "dvs-1"
    assert summary["start_connected"] is False
    assert summary["connected"] is False


def test_diagnostic_exception_summary_includes_vmware_fault_fields():
    error = RuntimeError("资源正在使用。 com.vmware.vim.vpxd.dvs.portInUse.label")
    error.localizedMessage = "资源正在使用"
    error.faultMessage = (SimpleNamespace(message="DVS port is already in use"),)

    summary = VmwareCloneGateway._describe_exception(error)

    assert summary["type"].endswith("RuntimeError")
    assert "portInUse.label" in summary["text"]
    assert summary["localized_message"] == "资源正在使用"
    assert summary["fault_messages"] == ["DVS port is already in use"]


def test_task_read_timeout_is_retried_on_the_same_task_until_it_finishes(monkeypatch):
    task = SimpleNamespace(info=SimpleNamespace(state=vim.TaskInfo.State.running, error=None))
    calls = []

    def wait_for_task(current_task):
        calls.append(current_task)
        if len(calls) == 1:
            raise TimeoutError("The read operation timed out")
        current_task.info.state = vim.TaskInfo.State.success

    gateway = VmwareCloneGateway(SimpleNamespace(task_wait_timeout=5))
    monkeypatch.setattr(clone_gateway_module, "WaitForTask", wait_for_task)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    gateway._wait_for_task(task, "克隆")

    assert calls == [task, task]


def test_inherited_dvs_nic_drops_fixed_port_key_while_preserving_portgroup():
    plan = build_clone_plan(
        make_form(disks=(), network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )
    nic = vim.vm.device.VirtualVmxnet3()
    nic.key = 4000
    nic.connectable = vim.vm.device.VirtualDevice.ConnectInfo(
        startConnected=True,
        allowGuestControl=True,
        connected=False,
    )
    nic.backing = vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo(
        port=vim.dvs.PortConnection(
            portgroupKey="dvportgroup-201",
            portKey="248",
            switchUuid="dvs-1",
        )
    )
    source = SimpleNamespace(
        config=SimpleNamespace(
            guestId="linux64Guest",
            hardware=SimpleNamespace(device=(nic,)),
        )
    )

    config = VmwareCloneGateway(SimpleNamespace())._build_config_spec(source, plan)

    nic_changes = [
        change
        for change in config.deviceChange
        if isinstance(change.device, vim.vm.device.VirtualEthernetCard)
    ]
    assert len(nic_changes) == 1
    assert nic_changes[0].operation == vim.vm.device.VirtualDeviceSpec.Operation.edit
    assert nic_changes[0].device.key == 4000
    assert nic_changes[0].device.backing.port.portgroupKey == "dvportgroup-201"
    assert nic_changes[0].device.backing.port.switchUuid == "dvs-1"
    assert not getattr(nic_changes[0].device.backing.port, "portKey", "")
    assert nic_changes[0].device.connectable.connected is False


def test_new_disk_is_explicitly_placed_on_the_selected_datastore():
    plan = build_clone_plan(
        make_form(quantity=1, network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )
    controller = vim.vm.device.VirtualSCSIController()
    controller.key = 1000
    source = SimpleNamespace(config=SimpleNamespace(hardware=SimpleNamespace(device=(controller,))))
    config = vim.vm.ConfigSpec()
    config.deviceChange = []
    datastore = vim.Datastore("ds-1", None)

    VmwareCloneGateway._append_disks(config, source, plan, datastore)

    assert config.deviceChange[0].device.backing.datastore is datastore


def test_config_spec_uses_each_item_effective_settings():
    plan = build_clone_plan(
        make_form(
            quantity=2,
            datastore_name="ds-a",
            disks=(),
            network=NetworkConfig(ip_mode="dhcp"),
        ),
        make_inventory(datastores=("ds-a", "ds-b")),
    )
    item = replace(
        plan.items[1],
        datastore_name="ds-b",
        portgroup_name="VLAN200",
        cpu_count=12,
        memory_gb=32,
        disk_requests=(DiskRequest(20, "GB"),),
    )
    source_nic = vim.vm.device.VirtualVmxnet3()
    source_nic.key = 4000
    controller = vim.vm.device.VirtualSCSIController()
    controller.key = 1000
    source = SimpleNamespace(
        config=SimpleNamespace(
            guestId="linux64Guest",
            hardware=SimpleNamespace(device=(source_nic, controller)),
        )
    )
    network = Mock(spec=vim.Network)
    network.name = "VLAN200"
    gateway = VmwareCloneGateway(SimpleNamespace())
    gateway._find_by_name = Mock(return_value=network)

    first_config = gateway._build_config_spec(
        source,
        plan,
        vim.Datastore("ds-a", None),
        plan.items[0],
    )
    second_config = gateway._build_config_spec(
        source,
        plan,
        vim.Datastore("ds-b", None),
        item,
    )

    assert first_config.numCPUs == plan.items[0].cpu_count
    assert first_config.memoryMB == plan.items[0].memory_gb * 1024
    assert first_config.deviceChange == []
    assert second_config.numCPUs == 12
    assert second_config.memoryMB == 32 * 1024
    assert len(second_config.deviceChange) == 3
    assert second_config.deviceChange[-1].device.backing.datastore._moId == "ds-b"


def _folder(moid: str, name: str, parent=None):
    folder = Mock(spec=vim.Folder)
    folder._moId = moid
    folder.name = name
    folder.parent = parent
    return folder


def test_inventory_lists_only_paths_relative_to_the_datacenter_vm_folder():
    datacenter = Mock(spec=vim.Datacenter)
    datacenter.name = "dc-1"
    vm_root = _folder("group-vm", "vm", datacenter)
    other_root = _folder("group-network", "network", datacenter)
    datacenter.vmFolder = vm_root

    production = _folder("group-production", "Production", vm_root)
    nested = _folder("group-app", "App", production)
    unrelated = _folder("group-net", "Networks", other_root)
    service = InventoryService(SimpleNamespace())
    service._objects = lambda vim_types: {
        vim.Folder: [vm_root, other_root, production, nested, unrelated]
    }.get(vim_types[0], [])

    snapshot = service.load()

    assert snapshot.folders == ("/Production", "/Production/App")


def test_folder_path_compatibility_does_not_create_a_second_vm_root():
    root = _folder("group-vm", "vm")
    production = _folder("group-production", "Production", root)
    root.childEntity = (production,)
    gateway = VmwareCloneGateway(SimpleNamespace(host="vc.example"))

    result = gateway._get_or_create_folder(root, "/vm/Production")

    assert result is production
    root.CreateFolder.assert_not_called()


def test_concurrent_folder_resolution_creates_each_missing_folder_once():
    root = _folder("group-vm", "vm")
    children = []
    children_lock = threading.Lock()
    type(root).childEntity = PropertyMock(side_effect=lambda: tuple(children))
    create_calls = []

    def create_folder(name):
        create_calls.append(name)
        time.sleep(0.02)
        child = _folder(f"group-{name}", name, root)
        with children_lock:
            children.append(child)
        return child

    root.CreateFolder.side_effect = create_folder
    gateway = VmwareCloneGateway(SimpleNamespace(host="vc.example"))

    threads = [
        threading.Thread(target=gateway._get_or_create_folder, args=(root, "/Production"))
        for _ in range(5)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert create_calls == ["Production"]


def test_duplicate_folder_error_reloads_the_existing_folder_by_parent_moid():
    root = _folder("group-vm", "vm")
    root.childEntity = ()
    production = _folder("group-production", "Production", root)
    root.CreateFolder.side_effect = RuntimeError("vim.fault.DuplicateName: already exists")
    gateway = VmwareCloneGateway(SimpleNamespace(host="vc.example"))
    gateway._objects = lambda _vim_types: [production]

    result = gateway._get_or_create_folder(root, "/Production")

    assert result is production
    root.CreateFolder.assert_called_once_with("Production")


def test_clone_spec_keeps_vm_off_until_network_reconfiguration(monkeypatch):
    plan = build_clone_plan(
        make_form(quantity=1, power_on_after=True, network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )
    source = Mock(spec=vim.VirtualMachine)
    source.config = SimpleNamespace(guestId="windows9Server64Guest")
    compute = Mock(spec=vim.ClusterComputeResource)
    compute.resourcePool = Mock(spec=vim.ResourcePool)
    datacenter = Mock(spec=vim.Datacenter)
    folder = Mock(spec=vim.Folder)
    datastore = Mock(spec=vim.Datastore)
    target_vm = Mock(spec=vim.VirtualMachine)
    target_vm.config = SimpleNamespace(hardware=SimpleNamespace(device=()))
    clone_task = SimpleNamespace(info=SimpleNamespace(result=target_vm))
    source.Clone.return_value = clone_task

    gateway = VmwareCloneGateway(SimpleNamespace(host="vc.example"))
    gateway._find_by_moid = Mock(
        side_effect=lambda vim_type, _moid: source
        if vim_type is vim.VirtualMachine
        else compute
    )
    gateway._datacenter_for = Mock(return_value=datacenter)
    gateway._get_or_create_folder = Mock(return_value=folder)
    gateway._find_datastore = Mock(return_value=datastore)
    gateway._build_config_spec = Mock(return_value=vim.vm.ConfigSpec())
    gateway._build_customization = Mock(return_value=None)
    monkeypatch.setattr(clone_gateway_module, "WaitForTask", Mock())

    gateway.clone_one(plan, plan.items[0])

    clone_spec = source.Clone.call_args.kwargs["spec"]
    assert clone_spec.powerOn is False
    target_vm.PowerOnVM_Task.assert_called_once_with()


def test_clone_submits_direct_power_on_after_clone_task(monkeypatch):
    plan = build_clone_plan(
        make_form(quantity=1, power_on_after=True, network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )
    source = Mock(spec=vim.VirtualMachine)
    source.config = SimpleNamespace(guestId="windows9Server64Guest")
    compute = Mock(spec=vim.ClusterComputeResource)
    compute.resourcePool = Mock(spec=vim.ResourcePool)
    datacenter = Mock(spec=vim.Datacenter)
    folder = Mock(spec=vim.Folder)
    datastore = Mock(spec=vim.Datastore)
    target_vm = Mock(spec=vim.VirtualMachine)
    target_nic = vim.vm.device.VirtualVmxnet3()
    target_nic.key = 4001
    target_nic.connectable = vim.vm.device.VirtualDevice.ConnectInfo(
        startConnected=False,
        allowGuestControl=False,
        connected=False,
    )
    target_vm.config = SimpleNamespace(hardware=SimpleNamespace(device=(target_nic,)))
    clone_task = SimpleNamespace(info=SimpleNamespace(result=target_vm))
    reconfig_task = object()
    power_task = object()
    source.Clone.return_value = clone_task
    target_vm.ReconfigVM_Task.return_value = reconfig_task
    target_vm.PowerOnVM_Task.return_value = power_task

    gateway = VmwareCloneGateway(SimpleNamespace(host="vc.example"))
    gateway._find_by_moid = Mock(
        side_effect=lambda vim_type, _moid: source
        if vim_type is vim.VirtualMachine
        else compute
    )
    gateway._datacenter_for = Mock(return_value=datacenter)
    gateway._get_or_create_folder = Mock(return_value=folder)
    gateway._find_datastore = Mock(return_value=datastore)
    gateway._build_config_spec = Mock(return_value=vim.vm.ConfigSpec())
    wait_for_task = Mock()
    monkeypatch.setattr(clone_gateway_module, "WaitForTask", wait_for_task)

    gateway.clone_one(plan, plan.items[0])

    clone_spec = source.Clone.call_args.kwargs["spec"]
    assert clone_spec.powerOn is False
    target_vm.ReconfigVM_Task.assert_not_called()
    target_vm.PowerOnVM_Task.assert_called_once_with()
    assert wait_for_task.call_args_list[-1].args == (power_task,)


def test_clone_read_timeout_still_reaches_power_on_after_task_finishes(monkeypatch):
    plan = build_clone_plan(
        make_form(
            quantity=1,
            power_on_after=True,
            disks=(),
            network=NetworkConfig(ip_mode="dhcp"),
        ),
        make_inventory(),
    )
    source = Mock(spec=vim.VirtualMachine)
    source.config = SimpleNamespace(
        guestId="linux64Guest",
        hardware=SimpleNamespace(device=()),
    )
    compute = Mock(spec=vim.ClusterComputeResource)
    compute.resourcePool = Mock(spec=vim.ResourcePool)
    datacenter = Mock(spec=vim.Datacenter)
    folder = Mock(spec=vim.Folder)
    datastore = Mock(spec=vim.Datastore)
    target_vm = Mock(spec=vim.VirtualMachine)
    target_vm.runtime = SimpleNamespace(powerState=vim.VirtualMachinePowerState.poweredOff)
    target_vm.config = SimpleNamespace(hardware=SimpleNamespace(device=()))
    clone_task = SimpleNamespace(
        info=SimpleNamespace(
            state=vim.TaskInfo.State.running,
            error=None,
            result=target_vm,
        )
    )
    power_task = SimpleNamespace(
        info=SimpleNamespace(
            state=vim.TaskInfo.State.running,
            error=None,
        )
    )
    source.Clone.return_value = clone_task
    target_vm.PowerOnVM_Task.return_value = power_task
    calls = []

    def wait_for_task(current_task):
        calls.append(current_task)
        if current_task is clone_task and calls.count(clone_task) == 1:
            raise TimeoutError("The read operation timed out")
        current_task.info.state = vim.TaskInfo.State.success
        if current_task is power_task:
            target_vm.runtime.powerState = vim.VirtualMachinePowerState.poweredOn

    gateway = VmwareCloneGateway(SimpleNamespace(task_wait_timeout=5))
    gateway._find_by_moid = Mock(
        side_effect=lambda vim_type, _moid: source
        if vim_type is vim.VirtualMachine
        else compute
    )
    gateway._datacenter_for = Mock(return_value=datacenter)
    gateway._get_or_create_folder = Mock(return_value=folder)
    gateway._find_datastore = Mock(return_value=datastore)
    monkeypatch.setattr(clone_gateway_module, "WaitForTask", wait_for_task)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    outcome = gateway.clone_one(plan, plan.items[0])

    assert outcome.success is True
    assert target_vm.PowerOnVM_Task.call_count == 1
    assert calls == [clone_task, clone_task, power_task]


def test_power_on_failure_reports_created_vm_without_retrying_clone(monkeypatch):
    plan = build_clone_plan(
        make_form(quantity=1, power_on_after=True, network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )
    source = Mock(spec=vim.VirtualMachine)
    source.config = SimpleNamespace(guestId="windows9Server64Guest")
    compute = Mock(spec=vim.ClusterComputeResource)
    compute.resourcePool = Mock(spec=vim.ResourcePool)
    datacenter = Mock(spec=vim.Datacenter)
    folder = Mock(spec=vim.Folder)
    datastore = Mock(spec=vim.Datastore)
    target_vm = Mock(spec=vim.VirtualMachine)
    target_vm.config = SimpleNamespace(hardware=SimpleNamespace(device=()))
    target_vm.PowerOnVM_Task.side_effect = RuntimeError("开机失败: insufficient resources")
    source.Clone.return_value = SimpleNamespace(info=SimpleNamespace(result=target_vm))

    gateway = VmwareCloneGateway(SimpleNamespace(host="vc.example"))
    gateway._find_by_moid = Mock(
        side_effect=lambda vim_type, _moid: source
        if vim_type is vim.VirtualMachine
        else compute
    )
    gateway._datacenter_for = Mock(return_value=datacenter)
    gateway._get_or_create_folder = Mock(return_value=folder)
    gateway._find_datastore = Mock(return_value=datastore)
    gateway._build_config_spec = Mock(return_value=vim.vm.ConfigSpec())
    monkeypatch.setattr(clone_gateway_module, "WaitForTask", Mock())

    outcome = gateway.clone_one(plan, plan.items[0])

    assert outcome.vm is target_vm
    assert outcome.success is False
    assert outcome.retryable is False
    assert "自动开机失败" in outcome.message
    assert "insufficient resources" in outcome.warning
    target_vm.PowerOnVM_Task.assert_called_once_with()


def test_selected_portgroup_matches_original_remove_and_add_network_flow():
    plan = build_clone_plan(
        make_form(
            quantity=1,
            portgroup_name="VLAN200",
            disks=(),
            network=NetworkConfig(ip_mode="dhcp"),
        ),
        make_inventory(),
    )
    source_nic = vim.vm.device.VirtualVmxnet3()
    source_nic.key = 4000
    source = SimpleNamespace(
        config=SimpleNamespace(
            guestId="windows9Server64Guest",
            hardware=SimpleNamespace(device=(source_nic,)),
        )
    )
    network = Mock(spec=vim.dvs.DistributedVirtualPortgroup)
    network.name = "VLAN200"
    network.key = "dvportgroup-200"
    network.config = SimpleNamespace(
        distributedVirtualSwitch=SimpleNamespace(uuid="dvs-200")
    )
    gateway = VmwareCloneGateway(SimpleNamespace(host="vc.example"))
    gateway._find_by_name = Mock(return_value=network)

    config = gateway._build_config_spec(source, plan)

    assert len(config.deviceChange) == 2
    assert config.deviceChange[0].operation == vim.vm.device.VirtualDeviceSpec.Operation.remove
    added_nic = config.deviceChange[1].device
    assert isinstance(added_nic, vim.vm.device.VirtualVmxnet3)
    assert added_nic.connectable.startConnected is True
    assert added_nic.connectable.connected is True
    assert added_nic.connectable.allowGuestControl is True
    assert added_nic.backing.port.portgroupKey == "dvportgroup-200"


def test_selected_dvs_portgroup_is_resolved_before_same_name_standard_network():
    plan = build_clone_plan(
        make_form(
            quantity=1,
            portgroup_name="VLAN200",
            disks=(),
            network=NetworkConfig(ip_mode="dhcp"),
        ),
        make_inventory(),
    )
    source_nic = vim.vm.device.VirtualVmxnet3()
    source_nic.key = 4000
    source = SimpleNamespace(
        config=SimpleNamespace(
            guestId="linux64Guest",
            hardware=SimpleNamespace(device=(source_nic,)),
        )
    )
    standard_network = Mock(spec=vim.Network)
    standard_network.name = "VLAN200"
    dvs_network = Mock(spec=vim.dvs.DistributedVirtualPortgroup)
    dvs_network.name = "VLAN200"
    dvs_network.key = "dvportgroup-200"
    dvs_network.config = SimpleNamespace(
        distributedVirtualSwitch=SimpleNamespace(uuid="dvs-200")
    )
    gateway = VmwareCloneGateway(SimpleNamespace(host="vc.example"))

    def find_by_name(vim_type, name):
        assert name == "VLAN200"
        if vim_type is vim.dvs.DistributedVirtualPortgroup:
            return dvs_network
        return standard_network

    gateway._find_by_name = Mock(side_effect=find_by_name)

    config = gateway._build_config_spec(source, plan)

    added_nic = config.deviceChange[1].device
    assert isinstance(
        added_nic.backing,
        vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo,
    )
    assert added_nic.backing.port.portgroupKey == "dvportgroup-200"
    assert added_nic.backing.port.switchUuid == "dvs-200"


def test_clone_one_does_not_reconfigure_network_after_clone(monkeypatch):
    plan = build_clone_plan(
        make_form(quantity=1, network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )
    source = Mock(spec=vim.VirtualMachine)
    source.config = SimpleNamespace(guestId="windows9Server64Guest")
    compute = Mock(spec=vim.ClusterComputeResource)
    compute.resourcePool = Mock(spec=vim.ResourcePool)
    datacenter = Mock(spec=vim.Datacenter)
    folder = Mock(spec=vim.Folder)
    datastore = Mock(spec=vim.Datastore)
    target_vm = Mock(spec=vim.VirtualMachine)
    target_nic = vim.vm.device.VirtualVmxnet3()
    target_nic.key = 4001
    target_nic.connectable = vim.vm.device.VirtualDevice.ConnectInfo(
        startConnected=False,
        allowGuestControl=False,
        connected=False,
    )
    target_vm.config = SimpleNamespace(
        hardware=SimpleNamespace(device=(target_nic,))
    )
    reconfig_task = object()
    target_vm.ReconfigVM_Task.return_value = reconfig_task
    clone_task = SimpleNamespace(info=SimpleNamespace(result=target_vm))
    source.Clone.return_value = clone_task

    gateway = VmwareCloneGateway(SimpleNamespace(host="vc.example"))
    gateway._find_by_moid = Mock(
        side_effect=lambda vim_type, _moid: source
        if vim_type is vim.VirtualMachine
        else compute
    )
    gateway._datacenter_for = Mock(return_value=datacenter)
    gateway._get_or_create_folder = Mock(return_value=folder)
    gateway._find_datastore = Mock(return_value=datastore)
    gateway._build_config_spec = Mock(return_value=vim.vm.ConfigSpec())
    gateway._build_customization = Mock(return_value=None)
    wait_for_task = Mock()
    monkeypatch.setattr(clone_gateway_module, "WaitForTask", wait_for_task)

    gateway.clone_one(plan, plan.items[0])

    target_vm.ReconfigVM_Task.assert_not_called()
    assert reconfig_task not in wait_for_task.call_args_list


def test_clone_one_returns_the_target_vm_from_the_clone_task(monkeypatch):
    plan = build_clone_plan(
        make_form(quantity=1, network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )
    source = Mock(spec=vim.VirtualMachine)
    source.config = SimpleNamespace(guestId="windows9Server64Guest")
    compute = Mock(spec=vim.ClusterComputeResource)
    compute.resourcePool = Mock(spec=vim.ResourcePool)
    datacenter = Mock(spec=vim.Datacenter)
    folder = Mock(spec=vim.Folder)
    datastore = Mock(spec=vim.Datastore)
    target_vm = Mock(spec=vim.VirtualMachine)
    target_vm.config = SimpleNamespace(hardware=SimpleNamespace(device=()))
    clone_task = SimpleNamespace(info=SimpleNamespace(result=target_vm))
    source.Clone.return_value = clone_task

    gateway = VmwareCloneGateway(SimpleNamespace(host="vc.example"))
    gateway._find_by_moid = Mock(
        side_effect=lambda vim_type, _moid: source
        if vim_type is vim.VirtualMachine
        else compute
    )
    gateway._datacenter_for = Mock(return_value=datacenter)
    gateway._get_or_create_folder = Mock(return_value=folder)
    gateway._find_datastore = Mock(return_value=datastore)
    gateway._build_config_spec = Mock(return_value=vim.vm.ConfigSpec())
    gateway._build_customization = Mock(return_value=None)
    monkeypatch.setattr(clone_gateway_module, "WaitForTask", Mock())

    outcome = gateway.clone_one(plan, plan.items[0])

    assert outcome.vm is target_vm
    assert outcome.message == "克隆成功"


def test_clone_spec_contains_the_hostname_customization_for_the_target_vm(monkeypatch):
    plan = build_clone_plan(
        make_form(
            quantity=1,
            disks=(),
            power_on_after=True,
            network=NetworkConfig(ip_mode="dhcp"),
        ),
        make_inventory(),
    )
    source = Mock(spec=vim.VirtualMachine)
    source.config = SimpleNamespace(
        guestId="windows9Server64Guest",
        hardware=SimpleNamespace(device=()),
    )
    compute = Mock(spec=vim.ClusterComputeResource)
    compute.resourcePool = Mock(spec=vim.ResourcePool)
    datacenter = Mock(spec=vim.Datacenter)
    folder = Mock(spec=vim.Folder)
    datastore = Mock(spec=vim.Datastore)
    target_vm = Mock(spec=vim.VirtualMachine)
    target_vm.config = SimpleNamespace(hardware=SimpleNamespace(device=()))
    source.Clone.return_value = SimpleNamespace(info=SimpleNamespace(result=target_vm))

    gateway = VmwareCloneGateway(SimpleNamespace(host="vc.example"))
    gateway._find_by_moid = Mock(
        side_effect=lambda vim_type, _moid: source
        if vim_type is vim.VirtualMachine
        else compute
    )
    gateway._datacenter_for = Mock(return_value=datacenter)
    gateway._get_or_create_folder = Mock(return_value=folder)
    gateway._find_datastore = Mock(return_value=datastore)
    monkeypatch.setattr(clone_gateway_module, "WaitForTask", Mock())

    gateway.clone_one(plan, plan.items[0])

    customization = source.Clone.call_args.kwargs["spec"].customization
    assert customization.identity.userData.computerName.name == "testvm"


def test_inherited_networks_are_left_unchanged_like_the_original_cloner():
    plan = build_clone_plan(
        make_form(disks=(), network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )
    nic = vim.vm.device.VirtualVmxnet3()
    nic.key = 4000
    nic.connectable = vim.vm.device.VirtualDevice.ConnectInfo(
        startConnected=False,
        allowGuestControl=False,
        connected=False,
    )
    source = SimpleNamespace(
        config=SimpleNamespace(
            guestId="windows9Server64Guest",
            hardware=SimpleNamespace(device=(nic,)),
        )
    )
    gateway = VmwareCloneGateway(SimpleNamespace(host="vc.example"))

    config = gateway._build_config_spec(source, plan)
    nic_changes = [
        change
        for change in config.deviceChange
        if isinstance(change.device, vim.vm.device.VirtualEthernetCard)
    ]

    assert nic_changes == []


def test_inherited_network_customization_matches_original_single_adapter_mapping():
    plan = build_clone_plan(
        make_form(
            disks=(),
            network=NetworkConfig(ip_mode="dhcp"),
        ),
        make_inventory(networks=("VLAN100", "VLAN200")),
    )
    gateway = VmwareCloneGateway(SimpleNamespace(host="vc.example"))
    source = SimpleNamespace(
        config=SimpleNamespace(guestId="windows9Server64Guest")
    )

    customization = gateway._build_customization(source, plan, plan.items[0])

    assert len(customization.nicSettingMap) == 1
    assert isinstance(
        customization.nicSettingMap[0].adapter.ip,
        vim.vm.customization.DhcpIpGenerator,
    )


def test_customization_spec_without_identity_still_transmits_hostname():
    plan = build_clone_plan(
        make_form(
            customization_spec_name="Windows-Standard",
            network=NetworkConfig(ip_mode="dhcp"),
        ),
        make_inventory(),
    )
    base_spec = SimpleNamespace(
        identity=None,
        globalIPSettings=vim.vm.customization.GlobalIPSettings(),
        nicSettingMap=[],
    )
    manager = SimpleNamespace(
        GetCustomizationSpec=lambda name: SimpleNamespace(spec=base_spec)
    )
    session = SimpleNamespace(
        content=SimpleNamespace(customizationSpecManager=manager)
    )
    gateway = VmwareCloneGateway(session)
    source = SimpleNamespace(
        config=SimpleNamespace(guestId="windows9Server64Guest")
    )

    customization = gateway._build_customization(source, plan, plan.items[0])

    assert isinstance(customization.identity, vim.vm.customization.Sysprep)
    assert customization.identity.userData.computerName.name == "testvm1"


def test_hostname_customization_keeps_one_adapter_mapping_when_inventory_has_no_networks():
    plan = build_clone_plan(
        make_form(network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(networks=()),
    )
    gateway = VmwareCloneGateway(SimpleNamespace(host="vc.example"))
    source = SimpleNamespace(
        config=SimpleNamespace(guestId="windows9Server64Guest")
    )

    customization = gateway._build_customization(source, plan, plan.items[0])

    assert customization.identity.userData.computerName.name == "testvm1"
    assert len(customization.nicSettingMap) == 1
