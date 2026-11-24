"""来源归属与归属交付测试。

完整复现业务场景：同一批次标签下甲、乙都采到 SKU-3（甲报价 10、乙报价 12），
各自还有独有货号；先撤回甲，再模拟乙确认消息迟到的两次补发，
并覆盖撤回语义、收件人受限视图、凭据齐备现场确认、重复确认幂等等规则。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.store import store
from app.services.source_attribution import (
    SourceAttributionService,
    STATUS_PENDING,
    STATUS_CONFIRMED,
    STATUS_WITHDRAWN,
)
from app.services.export_channel import ExportChannelService


BATCH = "BATCH-S11"
JIA = "甲"
YI = "乙"
R_JIA = "收件人甲"
R_YI = "收件人乙"


def _full_evidence(source, sku, quote):
    return {
        "报价快照": f"{source} 对 {sku} 的原始报价 {quote}",
        "来源凭据": f"{source}-票据-{sku}",
        "采集时间": "2026-11-24 09:00:00",
        "报价": quote,
    }


def _seed_shared_batch():
    """构造同标签两来源、共享 SKU-3 加各自独有货号的批次。"""
    svc = SourceAttributionService()
    # 甲：共享 SKU-3 报价 10，独有 SKU-A
    svc.register_raw_row(BATCH, JIA, "SKU-3", 10, R_JIA,
                         evidence=_full_evidence(JIA, "SKU-3", 10))
    svc.register_raw_row(BATCH, JIA, "SKU-A", 100, R_JIA,
                         evidence=_full_evidence(JIA, "SKU-A", 100))
    # 乙：共享 SKU-3 报价 12，独有 SKU-B
    svc.register_raw_row(BATCH, YI, "SKU-3", 12, R_YI,
                         evidence=_full_evidence(YI, "SKU-3", 12))
    svc.register_raw_row(BATCH, YI, "SKU-B", 200, R_YI,
                         evidence=_full_evidence(YI, "SKU-B", 200))
    return svc


@pytest.fixture(autouse=True)
def _reset_store():
    # 每个用例都从干净的内存仓库开始
    for table in ("source_row", "source_attribution", "export_channel", "crawl_audit"):
        store.rows(table).clear()
    yield
    for table in ("source_row", "source_attribution", "export_channel", "crawl_audit"):
        store.rows(table).clear()


class TestRawRowAndAttribution:
    def test_two_sources_same_sku_keep_separate_rows(self):
        svc = _seed_shared_batch()
        rows = [r for r in store.rows("source_row") if r["货号"] == "SKU-3"]
        assert {r["来源方"] for r in rows} == {JIA, YI}
        quotes = {r["来源方"]: r["报价"] for r in rows}
        assert quotes == {JIA: 10, YI: 12}

        attributions = svc.sku_confirmation_status(BATCH, "SKU-3")
        assert len(attributions) == 2
        assert {a["收件人"] for a in attributions} == {R_JIA, R_YI}
        assert all(a["确认状态"] == STATUS_PENDING for a in attributions)

    def test_register_raw_row_is_idempotent(self):
        svc = _seed_shared_batch()
        before = len(store.rows("source_row"))
        result = svc.register_raw_row(BATCH, YI, "SKU-3", 12, R_YI,
                                      evidence=_full_evidence(YI, "SKU-3", 12))
        assert result["created"] is False
        assert len(store.rows("source_row")) == before
        assert len(svc.list_attributions(batch_label=BATCH)) == 4


class TestWithdraw:
    def test_withdraw_only_marks_attribution_and_keeps_history(self):
        svc = _seed_shared_batch()
        result = svc.withdraw_source(BATCH, JIA)
        assert result["count"] == 2  # 甲的 SKU-3 与独有 SKU-A
        for attribution in svc.list_attributions(batch_label=BATCH, recipient=R_JIA):
            assert attribution["确认状态"] == STATUS_WITHDRAWN
            assert attribution["撤回时间"] is not None

        # 原始行与凭据仍然保留，可事后核对
        jia_rows = [r for r in store.rows("source_row")
                    if r["来源方"] == JIA and r["批次标签"] == BATCH]
        assert len(jia_rows) == 2
        assert all(r["来源凭据"] for r in jia_rows)

        # 乙的归属不受甲撤回影响
        yi_status = svc.sku_confirmation_status(BATCH, "SKU-3", recipient=R_YI)
        assert yi_status[0]["确认状态"] == STATUS_PENDING

    def test_withdrawn_attribution_cannot_be_confirmed(self):
        svc = _seed_shared_batch()
        svc.withdraw_source(BATCH, JIA)
        result = svc.confirm_attribution(BATCH, JIA, "SKU-3", R_JIA)
        assert result["ok"] is False
        assert "撤回" in result["message"]

    def test_withdraw_only_affects_future_delivery(self):
        svc = _seed_shared_batch()
        export_svc = ExportChannelService()
        # 撤回前先确认并交付一次甲的 SKU-A
        svc.confirm_attribution(BATCH, JIA, "SKU-A", R_JIA)
        first = export_svc.deliver_attributed(BATCH, R_JIA)
        assert first["delivered_skus"] == ["SKU-A"]

        svc.withdraw_source(BATCH, JIA)
        # 已交付的行仍可按当时归属权限和原始凭据核对
        task_id = first["delivery"]["任务标识"]
        verified = export_svc.verify_delivered_line(task_id, "SKU-A")
        assert verified["ok"] is True
        assert verified["frozen_line"]["原始凭据"] == "甲-票据-SKU-A"

        # 撤回后再补发，甲没有任何可交付行
        second = export_svc.deliver_attributed(BATCH, R_JIA)
        assert second["delivered_skus"] == []


class TestLateConfirmationScenario:
    def test_full_late_confirmation_redelivery_flow(self):
        svc = _seed_shared_batch()
        export_svc = ExportChannelService()

        # 1. 先撤回甲
        svc.withdraw_source(BATCH, JIA)

        # 2. 乙的原始报价已入库，但确认消息迟到：SKU-3 仍是待确认
        yi_sku3 = svc.sku_confirmation_status(BATCH, "SKU-3", recipient=R_YI)[0]
        assert yi_sku3["确认状态"] == STATUS_PENDING

        # 3. 乙独有 SKU-B 已确认，立即补发乙
        svc.confirm_attribution(BATCH, YI, "SKU-B", R_YI)
        first_delivery = export_svc.deliver_attributed(BATCH, R_YI)

        # 第一次补发：只有 SKU-B；SKU-3 仍在等待确认，未进入交付批次
        assert first_delivery["delivered_skus"] == ["SKU-B"]
        assert "SKU-3" in first_delivery["delivery"]["等待确认货号"]
        assert all(line["货号"] != "SKU-3"
                   for line in first_delivery["delivery"]["交付明细"])

        # 4. 从收件明细和归属记录都能查出 SKU-3 的状态：等待乙确认
        statuses = svc.sku_confirmation_status(BATCH, "SKU-3")
        yi_record = next(s for s in statuses if s["来源方"] == YI)
        assert yi_record["确认状态"] == STATUS_PENDING
        assert any(item["货号"] == "SKU-3"
                   for item in svc.pending_skus(BATCH, R_YI))

        # 5. 迟到的确认到达
        confirm_result = svc.confirm_attribution(BATCH, YI, "SKU-3", R_YI)
        assert confirm_result["ok"] is True
        assert confirm_result["already_confirmed"] is False
        assert confirm_result["attribution"]["确认状态"] == STATUS_CONFIRMED

        # 6. 再补发：SKU-3 按乙的凭据（报价 12）进入批次，且同货号只出现一次
        second_delivery = export_svc.deliver_attributed(BATCH, R_YI)
        assert second_delivery["delivered_skus"] == ["SKU-3"]
        sku3_line = next(line for line in second_delivery["lines"]
                         if line["货号"] == "SKU-3")
        assert sku3_line["来源方"] == YI
        assert sku3_line["报价"] == 12
        assert sku3_line["原始凭据"] == "乙-票据-SKU-3"

        # 7. 再补发不会重复交付，同货号在所有乙的交付批次中只出现一次
        third_delivery = export_svc.deliver_attributed(BATCH, R_YI)
        assert third_delivery["delivered_skus"] == []
        all_yi = export_svc.list_deliveries(batch_label=BATCH, recipient=R_YI)
        delivered_sku3 = [
            line["货号"]
            for delivery in all_yi
            for line in delivery["交付明细"]
            if line["货号"] == "SKU-3"
        ]
        assert delivered_sku3 == ["SKU-3"]
        # SKU-B 同样只在第一次批次出现一次
        delivered_sku_b = [
            line["货号"]
            for delivery in all_yi
            for line in delivery["交付明细"]
            if line["货号"] == "SKU-B"
        ]
        assert delivered_sku_b == ["SKU-B"]

    def test_jia_exclusive_sku_never_enters_yi_delivery(self):
        svc = _seed_shared_batch()
        export_svc = ExportChannelService()
        svc.withdraw_source(BATCH, JIA)
        svc.confirm_attribution(BATCH, YI, "SKU-B", R_YI)
        svc.confirm_attribution(BATCH, YI, "SKU-3", R_YI)

        delivery = export_svc.deliver_attributed(BATCH, R_YI)
        assert set(delivery["delivered_skus"]) == {"SKU-3", "SKU-B"}
        assert "SKU-A" not in delivery["delivered_skus"]
        # 乙的任何交付明细里都不可能出现甲独有货号
        for line in delivery["lines"]:
            assert line["来源方"] == YI


class TestRecipientView:
    def test_recipient_only_sees_attributed_raw_rows(self):
        svc = _seed_shared_batch()
        view_yi = svc.recipient_view(BATCH, R_YI)
        assert {row["货号"] for row in view_yi["raw_rows"]} == {"SKU-3", "SKU-B"}
        assert all(row["来源方"] == YI for row in view_yi["raw_rows"])

        view_jia = svc.recipient_view(BATCH, R_JIA)
        assert {row["货号"] for row in view_jia["raw_rows"]} == {"SKU-3", "SKU-A"}

        # 甲撤回后，乙的视图内容不发生变化
        svc.withdraw_source(BATCH, JIA)
        view_yi_after = svc.recipient_view(BATCH, R_YI)
        assert view_yi_after["count"] == view_yi["count"]


class TestRepeatedConfirmation:
    def test_repeated_confirmation_counts_once(self):
        svc = _seed_shared_batch()
        first = svc.confirm_attribution(BATCH, YI, "SKU-3", R_YI)
        first_time = first["attribution"]["确认时间"]
        second = svc.confirm_attribution(BATCH, YI, "SKU-3", R_YI)
        third = svc.confirm_attribution(BATCH, YI, "SKU-3", R_YI)

        assert second["ok"] is True
        assert second["already_confirmed"] is True
        assert third["already_confirmed"] is True
        # 确认时间不被覆盖，归属记录不新增
        assert second["attribution"]["确认时间"] == first_time
        yi_rows = [a for a in svc.list_attributions(batch_label=BATCH)
                   if a["来源方"] == YI and a["货号"] == "SKU-3"]
        assert len(yi_rows) == 1


class TestOnSiteResend:
    def test_complete_evidence_confirms_on_site(self):
        svc = SourceAttributionService()
        result = svc.confirm_on_site(
            BATCH, YI, "SKU-C", R_YI,
            evidence=_full_evidence(YI, "SKU-C", 300))
        assert result["ok"] is True
        attribution = result["attribution"]
        assert attribution["确认状态"] == STATUS_CONFIRMED
        assert attribution["凭据齐备"] is True
        # 现场确认的行立即可交付
        lines = svc.deliverable_lines(BATCH, R_YI)
        assert any(line["货号"] == "SKU-C" for line in lines)

    def test_incomplete_evidence_stays_pending(self):
        svc = SourceAttributionService()
        result = svc.confirm_on_site(
            BATCH, YI, "SKU-D", R_YI,
            evidence={"报价快照": "only snapshot", "报价": 9})
        assert result["ok"] is False
        assert result["attribution"]["确认状态"] == STATUS_PENDING
        assert svc.deliverable_lines(BATCH, R_YI) == []

    def test_on_site_repeat_confirm_is_idempotent(self):
        svc = SourceAttributionService()
        svc.confirm_on_site(BATCH, YI, "SKU-E", R_YI,
                            evidence=_full_evidence(YI, "SKU-E", 50))
        again = svc.confirm_on_site(BATCH, YI, "SKU-E", R_YI,
                                    evidence=_full_evidence(YI, "SKU-E", 50))
        assert again["ok"] is True
        assert again.get("already_confirmed") is True
        assert len(svc.list_attributions(batch_label=BATCH, sku="SKU-E")) == 1


class TestAuditTrail:
    def test_attribution_events_are_audited(self):
        svc = _seed_shared_batch()
        svc.withdraw_source(BATCH, JIA)
        svc.confirm_attribution(BATCH, YI, "SKU-3", R_YI)
        audit_types = {row["操作类型"] for row in store.rows("crawl_audit")}
        assert "来源归属" in audit_types
        assert "来源撤回" in audit_types
        assert "来源确认" in audit_types

    def test_delivery_is_audited(self):
        svc = _seed_shared_batch()
        svc.confirm_attribution(BATCH, YI, "SKU-B", R_YI)
        ExportChannelService().deliver_attributed(BATCH, R_YI)
        assert any(row["操作类型"] == "归属交付"
                   for row in store.rows("crawl_audit"))


class TestDeliveredLineVerification:
    def test_frozen_snapshot_survives_later_withdraw(self):
        svc = _seed_shared_batch()
        export_svc = ExportChannelService()
        svc.confirm_attribution(BATCH, YI, "SKU-3", R_YI)
        delivery = export_svc.deliver_attributed(BATCH, R_YI)
        task_id = delivery["delivery"]["任务标识"]

        # 交付后乙再撤回（模拟后续变化），已交付行仍按当时凭据核对
        svc.withdraw_source(BATCH, YI)
        verified = export_svc.verify_delivered_line(task_id, "SKU-3")
        assert verified["ok"] is True
        assert verified["frozen_line"]["确认状态"] == STATUS_CONFIRMED
        assert verified["frozen_line"]["报价快照"]
        current_states = {a["确认状态"] for a in verified["current_attributions"]}
        assert STATUS_WITHDRAWN in current_states
