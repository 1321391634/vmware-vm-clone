from __future__ import annotations

import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Protocol

from app.domain.models import ClonePlan, CloneItem
from app.reports.models import ExecutionReport, TaskResult


logger = logging.getLogger("vm-clone")


class TransientCloneError(RuntimeError):
    """A connection-level error that is safe to retry after checking the target."""


@dataclass(frozen=True)
class CloneOutcome:
    """The completed clone and the managed object returned by CloneVM_Task."""

    message: str
    vm: object
    warning: str = ""
    success: bool = True
    retryable: bool = False


class CloneGateway(Protocol):
    def clone_one(self, plan: ClonePlan, item: CloneItem) -> CloneOutcome: ...

    def find_vm_by_name(self, name: str): ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CloneExecutor:
    def __init__(
        self,
        gateway_factory: Callable[[], CloneGateway],
        *,
        max_workers: int = 5,
        retry_count: int = 2,
        retry_delay: float = 3.0,
    ):
        self.gateway_factory = gateway_factory
        self.max_workers = max(1, min(10, int(max_workers)))
        self.retry_count = max(0, int(retry_count))
        self.retry_delay = max(0.0, float(retry_delay))

    def execute(
        self,
        plan: ClonePlan,
        *,
        item_sequences: tuple[int, ...] | None = None,
        on_progress: Callable[[TaskResult], None] | None = None,
    ) -> ExecutionReport:
        selected = set(item_sequences) if item_sequences is not None else None
        items = tuple(item for item in plan.items if selected is None or item.sequence in selected)
        started_at = _now()
        results: list[TaskResult] = []
        with ThreadPoolExecutor(max_workers=min(self.max_workers, max(1, len(items)))) as pool:
            futures = {pool.submit(self._execute_one, plan, item): item for item in items}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = self._failure(item, f"任务执行异常: {exc}", 1, _now())
                results.append(result)
                if on_progress:
                    on_progress(result)
        results.sort(key=lambda result: result.sequence)
        return ExecutionReport(
            plan=plan,
            results=tuple(results),
            started_at=started_at,
            finished_at=_now(),
        )

    def _execute_one(self, plan: ClonePlan, item: CloneItem) -> TaskResult:
        task_started = _now()
        attempts = 0
        while True:
            gateway = None
            result = None
            retry = False
            disconnect_warning = ""
            attempts += 1
            try:
                gateway = self.gateway_factory()
                try:
                    outcome = gateway.clone_one(plan, item)
                    logger.info(
                        "clone result name=%s sequence=%s target_moid=%s",
                        item.vm_name,
                        item.sequence,
                        getattr(outcome.vm, "_moId", ""),
                    )
                    result = TaskResult(
                        sequence=item.sequence,
                        vm_name=item.vm_name,
                        hostname=item.hostname,
                        ip_address=item.ip_address,
                        success=getattr(outcome, "success", True),
                        message=outcome.message or "克隆成功",
                        warning=getattr(outcome, "warning", ""),
                        retryable=getattr(outcome, "retryable", False),
                        attempts=attempts,
                        started_at=task_started,
                        finished_at=_now(),
                    )
                except TransientCloneError as exc:
                    try:
                        target_exists = gateway.find_vm_by_name(item.vm_name) is not None
                    except Exception as lookup_exc:
                        result = self._failure(
                            item,
                            f"临时错误且无法确认目标是否已存在，已停止重试: {lookup_exc}",
                            attempts,
                            task_started,
                        )
                    else:
                        if target_exists:
                            result = TaskResult(
                                sequence=item.sequence,
                                vm_name=item.vm_name,
                                hostname=item.hostname,
                                ip_address=item.ip_address,
                                success=True,
                                message="目标虚拟机已存在，视为克隆已完成",
                                warning=f"vCenter 返回临时错误，已停止重试，请核对目标状态: {exc}",
                                attempts=attempts,
                                started_at=task_started,
                                finished_at=_now(),
                            )
                        elif attempts > self.retry_count:
                            result = self._failure(item, str(exc), attempts, task_started)
                        else:
                            retry = True
                except Exception as exc:
                    logger.error("clone failed name=%s sequence=%s error=%s", item.vm_name, item.sequence, exc)
                    result = self._failure(
                        item,
                        str(exc),
                        attempts,
                        task_started,
                        retryable=getattr(exc, "retryable", True),
                    )
            except Exception as exc:
                logger.error("clone failed name=%s sequence=%s error=%s", item.vm_name, item.sequence, exc)
                result = self._failure(
                    item,
                    str(exc),
                    attempts,
                    task_started,
                    retryable=getattr(exc, "retryable", True),
                )
            finally:
                disconnect = getattr(gateway, "disconnect", None) if gateway is not None else None
                if disconnect:
                    try:
                        disconnect()
                    except Exception as exc:
                        disconnect_warning = f"断开连接失败: {exc}"

            if retry:
                if self.retry_delay:
                    time.sleep(self.retry_delay * attempts)
                continue
            if result is None:
                result = self._failure(item, "任务没有返回结果", attempts, task_started)
            if disconnect_warning:
                result = replace(result, warning=self._append_warning(result.warning, disconnect_warning))
            return result

    @staticmethod
    def _append_warning(existing: str, new_warning: str) -> str:
        return "；".join(value for value in (existing, new_warning) if value)

    @staticmethod
    def _failure(
        item: CloneItem,
        message: str,
        attempts: int,
        started_at: str,
        *,
        retryable: bool = True,
    ) -> TaskResult:
        return TaskResult(
            sequence=item.sequence,
            vm_name=item.vm_name,
            hostname=item.hostname,
            ip_address=item.ip_address,
            success=False,
            message=message or "克隆失败",
            retryable=retryable,
            attempts=attempts,
            started_at=started_at,
            finished_at=_now(),
        )
