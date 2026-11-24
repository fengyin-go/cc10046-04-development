"""来源归属专属路由：归属登记、撤回、确认、收件人视图与归属交付。

通用资源路由 /api/source_attribution 继续承担列表/导出/通用动作，
本路由只承载带业务判断的来源归属操作，状态流转全部落在领域服务内。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.export_channel import ExportChannelService
from app.services.source_attribution import SourceAttributionService

router = APIRouter(prefix="/api/attributions", tags=["来源归属"])

_attribution = SourceAttributionService()
_export = ExportChannelService()


class RawRowPayload(BaseModel):
    batch_label: str
    source: str
    sku: str
    quote: Any = ""
    recipient: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    operator: str = "system"


class WithdrawPayload(BaseModel):
    batch_label: str
    source: str
    operator: str = "system"


class ConfirmPayload(BaseModel):
    batch_label: str
    source: str
    sku: str
    recipient: str | None = None
    operator: str = "system"


class OnSitePayload(BaseModel):
    batch_label: str
    source: str
    sku: str
    recipient: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    operator: str = "system"


class DeliverPayload(BaseModel):
    batch_label: str
    recipient: str
    export_format: str = "csv"
    operator: str = "system"


@router.post("/raw-rows")
def register_raw_row(payload: RawRowPayload) -> dict[str, Any]:
    return _attribution.register_raw_row(
        payload.batch_label, payload.source, payload.sku, payload.quote,
        payload.recipient, evidence=payload.evidence, operator=payload.operator)


@router.post("/withdraw")
def withdraw_source(payload: WithdrawPayload) -> dict[str, Any]:
    return _attribution.withdraw_source(
        payload.batch_label, payload.source, operator=payload.operator)


@router.post("/confirm")
def confirm_attribution(payload: ConfirmPayload) -> dict[str, Any]:
    return _attribution.confirm_attribution(
        payload.batch_label, payload.source, payload.sku,
        recipient=payload.recipient, operator=payload.operator)


@router.post("/confirm-on-site")
def confirm_on_site(payload: OnSitePayload) -> dict[str, Any]:
    return _attribution.confirm_on_site(
        payload.batch_label, payload.source, payload.sku,
        payload.recipient, evidence=payload.evidence, operator=payload.operator)


@router.get("/attributions")
def list_attributions(batch_label: str | None = None,
                      recipient: str | None = None,
                      sku: str | None = None) -> dict[str, Any]:
    items = _attribution.list_attributions(
        batch_label=batch_label, recipient=recipient, sku=sku)
    return {"items": items, "total": len(items)}


@router.get("/sku-status")
def sku_status(batch_label: str, sku: str,
               recipient: str | None = None) -> dict[str, Any]:
    return {
        "batch_label": batch_label,
        "sku": sku,
        "records": _attribution.sku_confirmation_status(
            batch_label, sku, recipient=recipient),
    }


@router.get("/recipient-view")
def recipient_view(batch_label: str, recipient: str) -> dict[str, Any]:
    return _attribution.recipient_view(batch_label, recipient)


@router.post("/deliver")
def deliver(payload: DeliverPayload) -> dict[str, Any]:
    return _export.deliver_attributed(
        payload.batch_label, payload.recipient,
        export_format=payload.export_format, operator=payload.operator)


@router.get("/deliveries")
def deliveries(batch_label: str | None = None,
               recipient: str | None = None) -> dict[str, Any]:
    items = _export.list_deliveries(batch_label=batch_label, recipient=recipient)
    return {"items": items, "total": len(items)}


@router.get("/verify-line")
def verify_line(task_id: str, sku: str) -> dict[str, Any]:
    return _export.verify_delivered_line(task_id, sku)
