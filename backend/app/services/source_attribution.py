"""来源归属领域服务。

采集审计过去只保存批次标签，无法说明一条采集原始行究竟归属于哪个来源/收件人。
本服务在批次标签之下新增两层记录：

1. 采集原始行（``source_row`` 表）：来源方实际采到的报价行，带原始凭据；
2. 来源归属记录（``source_attribution`` 表）：把原始行按批次标签归属给收件人，
   并维护「待确认 / 已确认 / 已撤回」的来源确认状态。

关键约束（与业务规则一一对应）：

- 同一份批次标签下，不同来源对同一货号各自保留独立原始行与归属记录；
- 撤回只标记归属记录，不删除任何历史数据，且只影响后续交付批次；
- 同一原始行反复确认幂等，只算一次；
- 现场补发对凭据齐备的行可在补发同时确认来源；
- 收件人视图只能看到当次已归属给自己的原始行；
- 某来源独有货号永远不会进入其他来源对应收件人的交付批次。
"""
from __future__ import annotations

import time
from typing import Any

from app.services.base import BaseModuleService


# 归属记录状态
STATUS_PENDING = "待确认"
STATUS_CONFIRMED = "已确认"
STATUS_WITHDRAWN = "已撤回"

# 凭据齐备判定：现场补发即时确认要求这些字段全部非空
EVIDENCE_FIELDS = ("报价快照", "来源凭据", "采集时间")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class SourceAttributionService(BaseModuleService):
    MODULE = "source_attribution"
    ENTITY = "来源归属记录"
    OPERATION_TERM = "采集"
    LIST_FIELDS = [
        "归属标识", "批次标签", "货号", "来源方", "收件人",
        "原始行标识", "确认状态", "凭据齐备", "确认时间",
    ]
    REQUIRED_FIELDS = ["归属标识", "批次标签", "货号", "来源方", "收件人"]
    STATUS_ORDER = [STATUS_PENDING, STATUS_CONFIRMED, STATUS_WITHDRAWN]
    # 通用动作仅保留合规的状态流转；撤回/确认等带业务判断的动作走专属接口
    ACTION_RULES = {"标记复核": STATUS_CONFIRMED}
    NEGATIVE_ACTIONS = []

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _next_id(self, table: str) -> int:
        rows = store_rows(table)
        return max((int(row.get("id", 0)) for row in rows), default=0) + 1

    def _audit(self, operation_type: str, target: str, summary: str,
               operator: str = "system") -> dict[str, Any]:
        # 延迟导入，避免服务注册表之间的循环依赖
        from app.services.crawl_audit import CrawlAuditService
        entry = CrawlAuditService().domain_audit(operation_type, target, operator)
        entry["审计摘要"] = summary
        return entry

    def _find_row(self, batch_label: str, source: str, sku: str) -> dict[str, Any] | None:
        for row in store_rows("source_row"):
            if (row.get("批次标签") == batch_label
                    and row.get("来源方") == source
                    and row.get("货号") == sku):
                return row
        return None

    def _find_attribution(self, batch_label: str, source: str, sku: str,
                          recipient: str) -> dict[str, Any] | None:
        for row in store_rows(self.MODULE):
            if (row.get("批次标签") == batch_label
                    and row.get("来源方") == source
                    and row.get("货号") == sku
                    and row.get("收件人") == recipient):
                return row
        return None

    @staticmethod
    def _evidence_complete(raw_row: dict[str, Any]) -> bool:
        return all(str(raw_row.get(field, "")).strip() for field in EVIDENCE_FIELDS)

    # ------------------------------------------------------------------
    # 1. 原始行登记 + 来源归属
    # ------------------------------------------------------------------
    def register_raw_row(self, batch_label: str, source: str, sku: str,
                         quote: Any, recipient: str,
                         evidence: dict[str, Any] | None = None,
                         operator: str = "system") -> dict[str, Any]:
        """登记一条采集原始行并建立归属给收件人的来源归属记录。

        同一（批次标签, 来源方, 货号）重复登记幂等，返回既有原始行和归属记录，
        不会产生第二条归属。
        """
        evidence = evidence or {}
        existing_row = self._find_row(batch_label, source, sku)
        if existing_row is not None:
            attribution = self._find_attribution(batch_label, source, sku, recipient)
            return {
                "raw_row": existing_row,
                "attribution": attribution,
                "created": False,
                "message": "原始行已存在，归属记录保持不变",
            }

        raw_row = {
            "id": self._next_id("source_row"),
            "原始行标识": f"ROW-{batch_label}-{source}-{sku}",
            "批次标签": batch_label,
            "来源方": source,
            "货号": sku,
            "报价": quote,
            "报价快照": str(evidence.get("报价快照", f"{source} 对 {sku} 的原始报价 {quote}")),
            "来源凭据": str(evidence.get("来源凭据", "")),
            "采集时间": str(evidence.get("采集时间", _now())),
            "登记时间": _now(),
            "status": "已入库",
            "pending": False,
            "abnormal": False,
        }
        store_rows("source_row").append(raw_row)

        attribution = {
            "id": self._next_id(self.MODULE),
            "归属标识": f"ATTR-{batch_label}-{source}-{sku}",
            "批次标签": batch_label,
            "货号": sku,
            "来源方": source,
            "收件人": recipient,
            "原始行标识": raw_row["原始行标识"],
            "确认状态": STATUS_PENDING,
            "凭据齐备": self._evidence_complete(raw_row),
            "确认时间": None,
            "撤回时间": None,
            "报价": quote,
            "登记时间": _now(),
            "status": STATUS_PENDING,
            "pending": True,
            "abnormal": False,
        }
        store_rows(self.MODULE).append(attribution)
        self._audit(
            "来源归属", raw_row["原始行标识"],
            f"批次 {batch_label} 中 {source} 的 {sku} 已归属给收件人 {recipient}，"
            f"状态为{STATUS_PENDING}", operator)
        return {
            "raw_row": raw_row,
            "attribution": attribution,
            "created": True,
            "message": "原始行已入库并建立来源归属",
        }

    # ------------------------------------------------------------------
    # 2. 撤回：只影响后续交付，历史归属与凭据保留
    # ------------------------------------------------------------------
    def withdraw_source(self, batch_label: str, source: str,
                        operator: str = "system") -> dict[str, Any]:
        """撤回某来源在指定批次标签下的全部有效归属记录。"""
        affected: list[dict[str, Any]] = []
        for attribution in store_rows(self.MODULE):
            if (attribution.get("批次标签") == batch_label
                    and attribution.get("来源方") == source
                    and attribution.get("确认状态") != STATUS_WITHDRAWN):
                attribution["确认状态"] = STATUS_WITHDRAWN
                attribution["撤回时间"] = _now()
                attribution["status"] = STATUS_WITHDRAWN
                attribution["pending"] = False
                affected.append(attribution)
                self._audit(
                    "来源撤回", attribution["归属标识"],
                    f"来源 {source} 撤回批次 {batch_label} 中 {attribution['货号']} 的归属，"
                    "仅影响后续交付，历史凭据保留", operator)
        return {
            "batch_label": batch_label,
            "source": source,
            "withdrawn": affected,
            "count": len(affected),
            "message": f"来源 {source} 已撤回 {len(affected)} 条归属，仅影响后续交付",
        }

    # ------------------------------------------------------------------
    # 3. 确认：迟到确认可补登记；同一原始行反复确认只算一次
    # ------------------------------------------------------------------
    def confirm_attribution(self, batch_label: str, source: str, sku: str,
                            recipient: str | None = None,
                            operator: str = "system") -> dict[str, Any]:
        """按来源凭据确认一条归属记录，幂等。"""
        attribution = self._locate_attribution(batch_label, source, sku, recipient)
        if attribution is None:
            return {"ok": False, "message": "未找到匹配的来源归属记录", "attribution": None}

        if attribution["确认状态"] == STATUS_WITHDRAWN:
            return {
                "ok": False,
                "message": "归属已被撤回，不能再确认；撤回只影响后续交付",
                "attribution": attribution,
            }
        if attribution["确认状态"] == STATUS_CONFIRMED:
            # 反复确认：不新增记录、不改确认时间，只算一次
            return {
                "ok": True,
                "attribution": attribution,
                "already_confirmed": True,
                "message": "该原始行此前已确认，重复确认只算一次",
            }

        attribution["确认状态"] = STATUS_CONFIRMED
        attribution["确认时间"] = _now()
        attribution["status"] = STATUS_CONFIRMED
        attribution["pending"] = False
        self._audit(
            "来源确认", attribution["归属标识"],
            f"收件人 {attribution['收件人']} 按 {source} 的原始凭据确认 {sku}",
            operator)
        return {
            "ok": True,
            "attribution": attribution,
            "already_confirmed": False,
            "message": "来源归属已按原始凭据确认",
        }

    def confirm_on_site(self, batch_label: str, source: str, sku: str,
                        recipient: str, evidence: dict[str, Any],
                        operator: str = "system") -> dict[str, Any]:
        """现场补发：凭据齐备的行在补发同时确认来源。

        凭据不齐备时拒绝确认，归属仍停留在「待确认」。
        """
        raw_row = self._find_row(batch_label, source, sku)
        if raw_row is None:
            # 现场补采：先把原始行入库再走确认
            registered = self.register_raw_row(
                batch_label, source, sku, evidence.get("报价", ""),
                recipient, evidence=evidence, operator=operator)
            raw_row = registered["raw_row"]

        # 用本次齐备凭据补齐原始行
        for field in EVIDENCE_FIELDS:
            if not str(raw_row.get(field, "")).strip() and evidence.get(field):
                raw_row[field] = str(evidence[field])
        attribution = self._find_attribution(batch_label, source, sku, recipient)
        if attribution is not None:
            attribution["凭据齐备"] = self._evidence_complete(raw_row)

        if not self._evidence_complete(raw_row):
            self._audit(
                "现场补发待确认", raw_row["原始行标识"],
                f"{source} 的 {sku} 凭据不齐备，保持{STATUS_PENDING}", operator)
            return {
                "ok": False,
                "raw_row": raw_row,
                "attribution": attribution,
                "message": "凭据不齐备，不能在补发时确认来源",
            }
        result = self.confirm_attribution(batch_label, source, sku, recipient, operator)
        result["raw_row"] = raw_row
        if result.get("already_confirmed"):
            result["message"] = "凭据齐备，但该原始行已确认过，重复确认只算一次"
        else:
            result["message"] = "现场补发凭据齐备，来源已同时确认"
        return result

    # ------------------------------------------------------------------
    # 4. 查询：归属记录、SKU 确认状态、收件人受限视图
    # ------------------------------------------------------------------
    def list_attributions(self, batch_label: str | None = None,
                          recipient: str | None = None,
                          sku: str | None = None) -> list[dict[str, Any]]:
        rows = list(store_rows(self.MODULE))
        if batch_label is not None:
            rows = [r for r in rows if r.get("批次标签") == batch_label]
        if recipient is not None:
            rows = [r for r in rows if r.get("收件人") == recipient]
        if sku is not None:
            rows = [r for r in rows if r.get("货号") == sku]
        return rows

    def sku_confirmation_status(self, batch_label: str, sku: str,
                                recipient: str | None = None) -> list[dict[str, Any]]:
        """查询某货号在批次内按各来源凭据的确认状态（含等待确认）。"""
        return [
            {
                "货号": row["货号"],
                "来源方": row["来源方"],
                "收件人": row["收件人"],
                "归属标识": row["归属标识"],
                "原始行标识": row["原始行标识"],
                "确认状态": row["确认状态"],
                "确认时间": row["确认时间"],
            }
            for row in self.list_attributions(batch_label=batch_label, sku=sku,
                                              recipient=recipient)
        ]

    def recipient_view(self, batch_label: str, recipient: str) -> dict[str, Any]:
        """收件方视图：只能看到这一次已归属给自己的原始行。"""
        visible_raw_rows: list[dict[str, Any]] = []
        visible_attributions: list[dict[str, Any]] = []
        for attribution in self.list_attributions(batch_label=batch_label,
                                                  recipient=recipient):
            raw_row = next(
                (r for r in store_rows("source_row")
                 if r.get("原始行标识") == attribution["原始行标识"]),
                None,
            )
            if raw_row is not None:
                visible_raw_rows.append(raw_row)
                visible_attributions.append(attribution)
        return {
            "batch_label": batch_label,
            "recipient": recipient,
            "raw_rows": visible_raw_rows,
            "attributions": visible_attributions,
            "count": len(visible_raw_rows),
            "message": f"收件人 {recipient} 仅可见归属给自己的 {len(visible_raw_rows)} 条原始行",
        }

    # ------------------------------------------------------------------
    # 5. 交付消费：导出通道按归属记录组装交付批次
    # ------------------------------------------------------------------
    def deliverable_lines(self, batch_label: str, recipient: str,
                          exclude_delivered: bool = True) -> list[dict[str, Any]]:
        """返回某收件人在该批次标签下可交付的明细行。

        - 只取归属给该收件人、且来源未撤回、状态为已确认的归属记录；
        - 同一货号只出现一次（同货号多条已确认归属时取最早确认的一条）；
        - 已在历史交付批次中交付过的行默认排除，保证补发不重复。
        """
        delivered_keys: set[tuple[str, str]] = set()
        if exclude_delivered:
            from app.services.export_channel import ExportChannelService
            for delivery in store_rows("export_channel"):
                if delivery.get("来源批次标签") != batch_label:
                    continue
                if delivery.get("收件人") != recipient:
                    continue
                for line in delivery.get("交付明细", []):
                    delivered_keys.add((line["货号"], line["原始行标识"]))

        candidates = [
            row for row in self.list_attributions(batch_label=batch_label,
                                                  recipient=recipient)
            if row.get("确认状态") == STATUS_CONFIRMED
        ]
        # 同货号去重：保留确认时间最早的归属
        by_sku: dict[str, dict[str, Any]] = {}
        for row in candidates:
            current = by_sku.get(row["货号"])
            if current is None or str(row.get("确认时间") or "") < str(current.get("确认时间") or ""):
                by_sku[row["货号"]] = row

        lines: list[dict[str, Any]] = []
        for sku in sorted(by_sku):
            attribution = by_sku[sku]
            key = (sku, attribution["原始行标识"])
            if key in delivered_keys:
                continue
            raw_row = next(
                (r for r in store_rows("source_row")
                 if r.get("原始行标识") == attribution["原始行标识"]),
                None,
            )
            lines.append({
                "货号": sku,
                "来源方": attribution["来源方"],
                "原始行标识": attribution["原始行标识"],
                "归属标识": attribution["归属标识"],
                "报价": attribution.get("报价", raw_row.get("报价") if raw_row else ""),
                "确认状态": STATUS_CONFIRMED,
                "确认时间": attribution["确认时间"],
                "原始凭据": raw_row.get("来源凭据", "") if raw_row else "",
                "报价快照": raw_row.get("报价快照", "") if raw_row else "",
            })
        return lines

    def pending_skus(self, batch_label: str, recipient: str) -> list[dict[str, Any]]:
        """仍在等待确认（或来源已撤回）、本次不能交付的货号。"""
        return [
            {
                "货号": row["货号"],
                "来源方": row["来源方"],
                "确认状态": row["确认状态"],
                "原始行标识": row["原始行标识"],
            }
            for row in self.list_attributions(batch_label=batch_label, recipient=recipient)
            if row.get("确认状态") != STATUS_CONFIRMED
        ]

    def _locate_attribution(self, batch_label: str, source: str, sku: str,
                            recipient: str | None) -> dict[str, Any] | None:
        if recipient is not None:
            return self._find_attribution(batch_label, source, sku, recipient)
        matches = [
            row for row in store_rows(self.MODULE)
            if (row.get("批次标签") == batch_label
                and row.get("来源方") == source
                and row.get("货号") == sku)
        ]
        return matches[0] if matches else None


def store_rows(table: str) -> list[dict[str, Any]]:
    """模块级辅助，保持与各领域服务一致的仓库访问方式。"""
    from app.store import store
    return store.rows(table)
