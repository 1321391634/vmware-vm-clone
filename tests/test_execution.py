from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from zipfile import ZipFile
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.models import DiskRequest, NetworkConfig  # noqa: E402
from app.domain.planning import build_clone_plan  # noqa: E402
from app.reports.exporter import ReportExporter  # noqa: E402
from app.vmware.clone_executor import CloneExecutor, CloneOutcome, TransientCloneError  # noqa: E402

from test_domain import make_form, make_inventory  # noqa: E402


class FakeGateway:
    def __init__(self, state):
        self.state = state

    def clone_one(self, plan, item):
        self.state["clone_calls"] += 1
        if self.state["transient_failures"]:
            self.state["transient_failures"] -= 1
            raise TransientCloneError("HostConnectFault")
        self.state["created"].add(item.vm_name)
        target_vm = self.state.setdefault("targets", {}).setdefault(item.vm_name, object())
        return CloneOutcome("克隆成功", target_vm)

    def find_vm_by_name(self, name):
        return name if name in self.state["created"] else None

    def power_on_vm(self, vm):
        self.state["power_calls"] += 1
        if self.state.get("power_failure"):
            raise RuntimeError("开机失败")


class DisconnectFailGateway(FakeGateway):
    def disconnect(self):
        raise RuntimeError("断开连接失败")


class DirectPowerGateway:
    def __init__(self, state):
        self.state = state

    def clone_one(self, plan, item):
        return SimpleNamespace(message="克隆成功", vm=self.state["target_vm"])

    def power_on_vm(self, vm):
        raise AssertionError("power-on must be requested in CloneSpec")

    def find_vm_by_name(self, _name):
        raise AssertionError("direct clone result should be used instead of name lookup")


class WarningGateway:
    def clone_one(self, plan, item):
        return CloneOutcome("克隆成功", object(), warning="Linux 客户机自定义依赖 /usr/bin/perl")

    def find_vm_by_name(self, _name):
        return None


class PowerOnFailureGateway:
    def clone_one(self, plan, item):
        return CloneOutcome(
            "克隆成功，但自动开机失败",
            object(),
            warning="自动开机失败: insufficient resources",
            success=False,
            retryable=False,
        )

    def find_vm_by_name(self, _name):
        raise AssertionError("a completed clone with power-on failure must not be retried")


class NonRetryableTaskFailureGateway:
    def clone_one(self, plan, item):
        error = RuntimeError("任务状态无法确认")
        error.retryable = False
        raise error

    def find_vm_by_name(self, _name):
        raise AssertionError("an uncertain task must not be checked as a transient clone")


def test_transient_failure_retries_without_duplicate_creation():
    state = {"clone_calls": 0, "power_calls": 0, "transient_failures": 1, "created": set()}
    plan = build_clone_plan(
        make_form(quantity=1, network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )
    factory_calls = {"count": 0}

    def gateway_factory():
        factory_calls["count"] += 1
        return FakeGateway(state)

    report = CloneExecutor(gateway_factory, retry_delay=0).execute(plan)

    assert report.results[0].success is True
    assert state["clone_calls"] == 2
    assert state["created"] == {"testvm"}
    assert factory_calls["count"] == 2


def test_guest_customization_warning_is_preserved_on_the_task_result():
    plan = build_clone_plan(make_form(network=NetworkConfig(ip_mode="dhcp")), make_inventory())

    report = CloneExecutor(lambda: WarningGateway(), retry_delay=0).execute(plan)

    assert report.results[0].success is True
    assert "/usr/bin/perl" in report.results[0].warning


def test_power_on_failure_is_reported_without_marking_item_retryable():
    plan = build_clone_plan(
        make_form(quantity=1, network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )

    report = CloneExecutor(lambda: PowerOnFailureGateway(), retry_delay=0).execute(plan)

    assert report.failed_count == 1
    assert report.results[0].success is False
    assert report.results[0].retryable is False
    assert "自动开机失败" in report.results[0].message


def test_non_retryable_task_failure_is_not_offered_for_retry():
    plan = build_clone_plan(
        make_form(quantity=1, network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )

    report = CloneExecutor(lambda: NonRetryableTaskFailureGateway(), retry_delay=0).execute(plan)

    assert report.failed_count == 1
    assert report.results[0].retryable is False


def test_uncertain_transient_failure_stops_when_target_already_exists():
    state = {"clone_calls": 0, "power_calls": 0, "transient_failures": 1, "created": {"testvm"}}
    plan = build_clone_plan(
        make_form(quantity=1, network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )
    report = CloneExecutor(lambda: FakeGateway(state), retry_delay=0).execute(plan)

    assert report.results[0].success is True
    assert "已存在" in report.results[0].message
    assert "停止重试" in report.results[0].warning
    assert state["clone_calls"] == 1


def test_power_on_is_requested_by_clone_spec_without_a_second_power_task():
    target_vm = object()
    state = {"target_vm": target_vm}
    plan = build_clone_plan(
        make_form(
            quantity=1,
            power_on_after=True,
            network=NetworkConfig(ip_mode="dhcp"),
        ),
        make_inventory(),
    )

    report = CloneExecutor(lambda: DirectPowerGateway(state), retry_delay=0).execute(plan)

    assert report.results[0].success is True
    assert report.results[0].warning == ""


def test_failed_only_execution_runs_only_selected_items():
    state = {"clone_calls": 0, "power_calls": 0, "transient_failures": 0, "created": set()}
    plan = build_clone_plan(make_form(network=NetworkConfig(ip_mode="dhcp")), make_inventory())
    report = CloneExecutor(lambda: FakeGateway(state), retry_delay=0).execute(
        plan, item_sequences=(2,)
    )

    assert [result.sequence for result in report.results] == [2]
    assert state["created"] == {"testvm2"}


def test_gateway_factory_failure_is_recorded_as_a_task_failure():
    plan = build_clone_plan(
        make_form(quantity=1, network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )

    def failing_factory():
        raise RuntimeError("连接 vCenter 失败")

    report = CloneExecutor(failing_factory, retry_delay=0).execute(plan)

    assert report.failed_count == 1
    assert "连接 vCenter 失败" in report.results[0].message


def test_disconnect_failure_does_not_turn_a_successful_clone_into_failure():
    state = {"clone_calls": 0, "power_calls": 0, "transient_failures": 0, "created": set()}
    plan = build_clone_plan(
        make_form(quantity=1, network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )

    report = CloneExecutor(lambda: DisconnectFailGateway(state), retry_delay=0).execute(plan)

    assert report.success_count == 1
    assert report.results[0].success is True
    assert "断开连接失败" in report.results[0].warning


def test_one_unexpected_worker_exception_does_not_drop_the_rest_of_the_batch():
    state = {"clone_calls": 0, "power_calls": 0, "transient_failures": 0, "created": set()}
    plan = build_clone_plan(
        make_form(quantity=2, network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )
    executor = CloneExecutor(lambda: FakeGateway(state), retry_delay=0)
    original_execute_one = executor._execute_one

    def execute_one_with_crash(plan, item):
        if item.sequence == 1:
            raise RuntimeError("worker crashed")
        return original_execute_one(plan, item)

    executor._execute_one = execute_one_with_crash
    report = executor.execute(plan)

    assert [result.sequence for result in report.results] == [1, 2]
    assert report.results[0].success is False
    assert "worker crashed" in report.results[0].message
    assert report.results[1].success is True


def test_report_exporter_writes_json_and_excel(tmp_path):
    state = {"clone_calls": 0, "power_calls": 0, "transient_failures": 0, "created": set()}
    plan = build_clone_plan(
        make_form(quantity=1, network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )
    report = CloneExecutor(lambda: FakeGateway(state), retry_delay=0).execute(plan)
    exporter = ReportExporter()

    json_path = exporter.to_json(report, tmp_path / "report.json")
    excel_path = exporter.to_excel(report, tmp_path / "report.xlsx")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["results"][0]["vm_name"] == "testvm"
    assert payload["inheritance"]["datastore"] == "source"
    assert payload["disk_requests"][1]["size_gb"] == 1024
    assert payload["network"]["ip_mode"] == "dhcp"
    assert excel_path.exists()


def test_report_exports_effective_settings_for_each_preview_row(tmp_path):
    plan = build_clone_plan(
        make_form(quantity=2, network=NetworkConfig(ip_mode="dhcp")),
        make_inventory(),
    )
    plan = replace(
        plan,
        items=(
            replace(
                plan.items[0],
                vm_name="web-a",
                hostname="web-a",
                portgroup_name="VLAN100",
                cpu_count=4,
                memory_gb=8,
                disk_requests=(DiskRequest(20, "GB"),),
            ),
            replace(
                plan.items[1],
                vm_name="web-b",
                hostname="web-b",
                portgroup_name="VLAN200",
                cpu_count=12,
                memory_gb=32,
                disk_requests=(),
            ),
        ),
    )
    report = CloneExecutor(lambda: FakeGateway({"clone_calls": 0, "power_calls": 0, "transient_failures": 0, "created": set()}), retry_delay=0).execute(plan)
    exporter = ReportExporter()

    json_path = exporter.to_json(report, tmp_path / "effective.json")
    excel_path = exporter.to_excel(report, tmp_path / "effective.xlsx")
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert payload["items"][0]["portgroup_name"] == "VLAN100"
    assert payload["items"][0]["cpu_count"] == 4
    assert payload["items"][0]["disk_requests"][0]["size_gb"] == 20
    assert payload["results"][1]["memory_gb"] == 32
    with ZipFile(excel_path) as package:
        worksheet_xml = package.read("xl/worksheets/sheet2.xml").decode("utf-8")
    assert "VLAN200" in worksheet_xml
