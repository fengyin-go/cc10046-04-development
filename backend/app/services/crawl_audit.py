"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class CrawlAuditService(BaseModuleService):
    MODULE = "crawl_audit"
    ENTITY = "审计记录"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["记录标识", "操作类型", "操作对象", "操作时间", "操作人", "变更前值", "变更后值", "审计摘要"]
    REQUIRED_FIELDS = ["记录标识", "操作类型", "操作对象"]
    STATUS_ORDER = ["已记录", "已复核", "异常记录"]
    ACTION_RULES = {"标记复核": "已记录", "上报异常": "异常记录"}
    NEGATIVE_ACTIONS = []

    def domain_audit(self, operation_type: str, target: str,
                     operator: str = "system", summary: str | None = None) -> dict:
        """记录采集操作审计日志。"""
        from app.store import store
        import time
        rows = store.rows(self.MODULE)
        now = time.strftime("%Y-%m-%d")
        entry = {
            "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
            "记录标识": f"AUDIT-{int(time.time()*1000)}-{len(rows)+1}",
            "操作类型": operation_type,
            "操作对象": target,
            "操作时间": now,
            "操作人": operator,
            "变更前值": "",
            "变更后值": operation_type,
            "审计摘要": summary or f"{operator} 执行了 {operation_type} 操作于 {target}",
            "status": "已记录",
            "pending": True,
            "abnormal": False,
        }
        rows.append(entry)
        return entry
