from __future__ import annotations

import json
from pathlib import Path

from .models import ExecutionReport
from .xlsx_writer import write_xlsx


class ReportExporter:
    def to_json(self, report: ExecutionReport, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target

    def to_excel(self, report: ExecutionReport, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        plan = report.plan
        summary_rows = [
            ["参数", "值"],
            ("源虚拟机", plan.source_vm.name),
            ("源对象 MoID", plan.source_vm.moid),
            ("计算资源", plan.compute_resource.name),
            ("计算资源类型", plan.compute_resource.kind),
            ("文件夹", plan.folder_path),
            ("存储", plan.datastore_name),
            ("端口组", plan.portgroup_name or "继承源网卡"),
            ("自定义规范", plan.customization_spec_name or "不使用"),
            ("CPU", plan.cpu_count),
            ("内存 GB", plan.memory_gb),
            ("CPU 热添加", "是" if plan.cpu_hot_add_enabled else "否"),
            ("内存热添加", "是" if plan.memory_hot_add_enabled else "否"),
            ("备注", plan.remark),
            ("成功后开机", "是" if plan.power_on_after else "否"),
            ("克隆并发", plan.concurrency),
            ("继承项", "; ".join(f"{key}={value}" for key, value in plan.inheritance.items())),
            ("强制继续警告", "；".join(plan.warnings)),
            ("客户机环境提示", "；".join(plan.environment_warnings)),
        ]
        result_rows = [[
                "序号",
                "虚拟机名称",
                "Hostname",
                "IP地址",
                "存储",
                "端口组",
                "CPU",
                "内存 GB",
                "新增硬盘",
                "状态",
                "详情",
                "警告",
                "可重试",
                "尝试次数",
                "开始时间",
                "结束时间",
        ]]
        items_by_sequence = {item.sequence: item for item in plan.items}
        for result in report.results:
            item = items_by_sequence.get(result.sequence)
            disk_text = ""
            if item is not None:
                disk_text = ", ".join(
                    f"{disk.size:g} {disk.unit}" for disk in item.disk_requests
                )
            result_rows.append([
                    result.sequence,
                    result.vm_name,
                    result.hostname,
                    result.ip_address or "",
                    item.datastore_name if item is not None else "",
                    (item.portgroup_name or "继承源网卡") if item is not None else "",
                    item.cpu_count if item is not None else "",
                    item.memory_gb if item is not None else "",
                    disk_text,
                    "成功" if result.success else "失败",
                    result.message,
                    result.warning,
                    "是" if result.retryable else "否",
                    result.attempts,
                    result.started_at,
                    result.finished_at,
                ])
        return write_xlsx(
            target,
            {
                "批次参数": [list(row) for row in summary_rows],
                "克隆结果": result_rows,
            },
        )
