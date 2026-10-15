from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.domain.models import ClonePlan


@dataclass(frozen=True)
class TaskResult:
    sequence: int
    vm_name: str
    hostname: str
    ip_address: str | None
    success: bool
    message: str
    warning: str = ""
    retryable: bool = True
    attempts: int = 1
    started_at: str = ""
    finished_at: str = ""


@dataclass(frozen=True)
class ExecutionReport:
    plan: ClonePlan
    results: tuple[TaskResult, ...]
    started_at: str
    finished_at: str

    @property
    def success_count(self) -> int:
        return sum(result.success for result in self.results)

    @property
    def failed_count(self) -> int:
        return len(self.results) - self.success_count

    def to_dict(self) -> dict[str, Any]:
        plan = self.plan
        item_by_sequence = {item.sequence: item for item in plan.items}

        def item_payload(item) -> dict[str, Any]:
            return {
                "sequence": item.sequence,
                "vm_name": item.vm_name,
                "hostname": item.hostname,
                "ip_address": item.ip_address,
                "datastore_name": item.datastore_name,
                "portgroup_name": item.portgroup_name,
                "cpu_count": item.cpu_count,
                "memory_gb": item.memory_gb,
                "disk_requests": [
                    {"size": disk.size, "unit": disk.unit, "size_gb": disk.size_gb}
                    for disk in item.disk_requests
                ],
            }

        return {
            "source_vm": plan.source_vm.name,
            "source_vm_details": {
                "moid": plan.source_vm.moid,
                "name": plan.source_vm.name,
                "uuid": plan.source_vm.uuid,
                "is_template": plan.source_vm.is_template,
                "power_state": plan.source_vm.power_state,
                "host_name": plan.source_vm.host_name,
                "cluster_name": plan.source_vm.cluster_name,
                "datastores": list(plan.source_vm.datastores),
                "networks": list(plan.source_vm.networks),
            },
            "compute_resource": plan.compute_resource.name,
            "compute_resource_details": {
                "moid": plan.compute_resource.moid,
                "name": plan.compute_resource.name,
                "kind": plan.compute_resource.kind,
                "datacenter_name": plan.compute_resource.datacenter_name,
                "resource_pool_moid": plan.compute_resource.resource_pool_moid,
            },
            "folder_path": plan.folder_path,
            "datastore": plan.datastore_name,
            "portgroup": plan.portgroup_name or "继承源网卡",
            "customization_spec": plan.customization_spec_name or "",
            "cpu_count": plan.cpu_count,
            "memory_gb": plan.memory_gb,
            "cpu_hot_add_enabled": plan.cpu_hot_add_enabled,
            "memory_hot_add_enabled": plan.memory_hot_add_enabled,
            "disk_requests": [
                {"size": disk.size, "unit": disk.unit, "size_gb": disk.size_gb}
                for disk in plan.disk_requests
            ],
            "network": {
                "ip_mode": plan.network.ip_mode,
                "ip_input": plan.network.ip_input,
                "subnet_mask": plan.network.subnet_mask,
                "gateway": plan.network.gateway,
                "dns_mode": plan.network.dns_mode,
                "dns_servers": list(plan.network.dns_servers),
            },
            "remark": plan.remark,
            "power_on_after": plan.power_on_after,
            "concurrency": plan.concurrency,
            "inheritance": dict(plan.inheritance),
            "warnings": list(plan.warnings),
            "forced_continue_warnings": list(plan.warnings),
            "environment_warnings": list(plan.environment_warnings),
            "items": [item_payload(item) for item in plan.items],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "results": [
                {
                    "sequence": result.sequence,
                    "vm_name": result.vm_name,
                    "hostname": result.hostname,
                    "ip_address": result.ip_address,
                    "success": result.success,
                    "message": result.message,
                    "warning": result.warning,
                    "retryable": result.retryable,
                    "attempts": result.attempts,
                    "started_at": result.started_at,
                    "finished_at": result.finished_at,
                    **(
                        item_payload(item_by_sequence[result.sequence])
                        if result.sequence in item_by_sequence
                        else {}
                    ),
                }
                for result in self.results
            ],
        }
