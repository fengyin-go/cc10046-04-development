"""导出通道领域服务。

除原有按批次导出能力外，新增面向「来源归属记录」的交付批次组装：
交付批次只包含收件人已确认、来源未撤回的原始行，并把当时的归属权限和
原始凭据快照一并落档，保证已交付的行事后仍可核对。
"""
from __future__ import annotations

import time
from typing import Any

from app.services.base import BaseModuleService


class ExportChannelService(BaseModuleService):
    MODULE = "export_channel"
    ENTITY = "导出任务"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["任务标识", "来源批次", "导出格式", "目标路径", "字段筛选", "导出状态", "文件大小", "完成时间"]
    REQUIRED_FIELDS = ["任务标识", "来源批次", "导出格式"]
    STATUS_ORDER = ["排队中", "导出中", "已完成", "导出失败"]
    ACTION_RULES = {"启动导出": "排队中", "取消导出": "导出中"}
    NEGATIVE_ACTIONS = []

    def domain_export(self, batch_id: str, export_format: str = "csv",
                      fields: list[str] | None = None) -> dict:
        """导出批次数据到指定格式。"""
        from app.store import store
        rows = store.rows(self.MODULE)
        now = time.strftime("%Y-%m-%d")
        file_size = (len(batch_id) * 1024) + 512
        entry = {
            "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
            "任务标识": f"EXPORT-{batch_id}",
            "来源批次": batch_id,
            "导出格式": export_format,
            "目标路径": f"/exports/{batch_id}.{export_format}",
            "字段筛选": ",".join(fields or []),
            "导出状态": "已完成",
            "文件大小": f"{file_size}",
            "完成时间": now,
            "status": "已完成",
            "pending": False,
            "abnormal": False,
        }
        rows.append(entry)
        return entry

    # ------------------------------------------------------------------
    # 来源归属驱动的交付批次
    # ------------------------------------------------------------------
    def deliver_attributed(self, batch_label: str, recipient: str,
                           export_format: str = "csv",
                           operator: str = "system") -> dict[str, Any]:
        """按来源归属记录为收件人组装一次交付（补发）批次。

        - 只消费归属给该收件人、已确认且来源未撤回的归属记录；
        - 甲独有货号因从未归属给乙，天然不会进入乙的交付批次；
        - 已交付过的行不再重复进入后续批次，同货号只出现一次；
        - 交付明细保存当时的归属标识、确认状态与原始凭据快照，
          撤回发生在交付之后也不影响按当时权限核对。
        """
        from app.services.source_attribution import SourceAttributionService
        from app.store import store

        attribution_service = SourceAttributionService()
        lines = attribution_service.deliverable_lines(batch_label, recipient)
        pending = attribution_service.pending_skus(batch_label, recipient)

        rows = store.rows(self.MODULE)
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        today = time.strftime("%Y-%m-%d")
        sequence = sum(
            1 for row in rows
            if row.get("来源批次标签") == batch_label and row.get("收件人") == recipient
        ) + 1
        task_id = f"DELIVERY-{batch_label}-{recipient}-{sequence}"
        # 交付时冻结凭据快照，后续撤回/修改都不改变已交付内容
        frozen_lines = [dict(line) for line in lines]
        entry = {
            "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
            "任务标识": task_id,
            "来源批次": batch_label,
            "来源批次标签": batch_label,
            "收件人": recipient,
            "交付序号": sequence,
            "导出格式": export_format,
            "目标路径": f"/exports/delivery/{task_id}.{export_format}",
            "字段筛选": "货号,来源方,报价,原始凭据,报价快照",
            "导出状态": "已完成",
            "文件大小": str(len(frozen_lines) * 1024 + 256),
            "完成时间": today,
            "交付时间": now,
            "交付明细": frozen_lines,
            "交付货号": [line["货号"] for line in frozen_lines],
            "交付行数": len(frozen_lines),
            "等待确认货号": [item["货号"] for item in pending],
            "status": "已完成",
            "pending": False,
            "abnormal": False,
        }
        rows.append(entry)

        from app.services.crawl_audit import CrawlAuditService
        CrawlAuditService().domain_audit(
            "归属交付", task_id,
            f"收件人 {recipient} 的交付批次含 {len(frozen_lines)} 条已确认原始行；"
            f"等待确认 {len(pending)} 条", operator)
        return {
            "delivery": entry,
            "lines": frozen_lines,
            "pending": pending,
            "delivered_skus": entry["交付货号"],
            "message": (f"交付批次 {task_id} 含 {len(frozen_lines)} 条已确认原始行，"
                        f"{len(pending)} 条仍在等待确认"),
        }

    def list_deliveries(self, batch_label: str | None = None,
                        recipient: str | None = None) -> list[dict[str, Any]]:
        """查询交付批次及其收件明细。"""
        from app.store import store
        rows = [
            row for row in store.rows(self.MODULE)
            if row.get("交付明细") is not None
        ]
        if batch_label is not None:
            rows = [row for row in rows if row.get("来源批次标签") == batch_label]
        if recipient is not None:
            rows = [row for row in rows if row.get("收件人") == recipient]
        return rows

    def verify_delivered_line(self, task_id: str, sku: str) -> dict[str, Any]:
        """按当时的归属权限和原始凭据核对一条已交付行。"""
        from app.store import store
        delivery = next(
            (row for row in store.rows(self.MODULE) if row.get("任务标识") == task_id),
            None,
        )
        if delivery is None:
            return {"ok": False, "message": f"交付批次 {task_id} 不存在"}
        line = next(
            (item for item in delivery.get("交付明细", []) if item.get("货号") == sku),
            None,
        )
        if line is None:
            return {
                "ok": False,
                "message": f"货号 {sku} 不在交付批次 {task_id} 中",
                "task_id": task_id,
            }
        # 与当前归属记录比对：撤回只影响后续交付，不改变已交付行的核对结论
        from app.services.source_attribution import SourceAttributionService
        current = SourceAttributionService().list_attributions(
            batch_label=delivery.get("来源批次标签"), sku=sku)
        return {
            "ok": True,
            "task_id": task_id,
            "frozen_line": line,
            "current_attributions": current,
            "verifiable": True,
            "message": "已交付行可按交付时冻结的归属权限与原始凭据核对",
        }
