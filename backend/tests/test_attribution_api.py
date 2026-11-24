"""来源归属 HTTP 端到端测试：通过真实 FastAPI 路由复现 SKU-3 迟到确认场景。"""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app.main import app
from app.store import store

client = TestClient(app)

BATCH = "BATCH-HTTP"
JIA = "甲"
YI = "乙"
R_JIA = "收件人甲"
R_YI = "收件人乙"


def _evidence(source, sku, quote):
    return {
        "报价快照": f"{source} 对 {sku} 的原始报价 {quote}",
        "来源凭据": f"{source}-票据-{sku}",
        "采集时间": "2026-11-24 09:00:00",
        "报价": quote,
    }


def _register(source, sku, quote, recipient):
    response = client.post("/api/attributions/raw-rows", json={
        "batch_label": BATCH,
        "source": source,
        "sku": sku,
        "quote": quote,
        "recipient": recipient,
        "evidence": _evidence(source, sku, quote),
    })
    assert response.status_code == 200
    return response.json()


@pytest.fixture(autouse=True)
def _reset_store():
    for table in ("source_row", "source_attribution", "export_channel", "crawl_audit"):
        store.rows(table).clear()
    yield
    for table in ("source_row", "source_attribution", "export_channel", "crawl_audit"):
        store.rows(table).clear()


def test_full_sku3_late_confirmation_scenario_over_http():
    # 同标签：甲报价 10、乙报价 12，各自带独有货号
    _register(JIA, "SKU-3", 10, R_JIA)
    _register(JIA, "SKU-A", 100, R_JIA)
    _register(YI, "SKU-3", 12, R_YI)
    _register(YI, "SKU-B", 200, R_YI)

    # 先撤回甲
    withdrawn = client.post("/api/attributions/withdraw", json={
        "batch_label": BATCH, "source": JIA}).json()
    assert withdrawn["count"] == 2

    # 乙确认消息迟到：SKU-3 仍待确认；先确认独有货号 SKU-B 并立即补发
    status = client.get("/api/attributions/sku-status",
                        params={"batch_label": BATCH, "sku": "SKU-3"}).json()
    yi_record = next(r for r in status["records"] if r["来源方"] == YI)
    assert yi_record["确认状态"] == "待确认"

    client.post("/api/attributions/confirm", json={
        "batch_label": BATCH, "source": YI, "sku": "SKU-B", "recipient": R_YI})
    first = client.post("/api/attributions/deliver", json={
        "batch_label": BATCH, "recipient": R_YI}).json()
    assert first["delivered_skus"] == ["SKU-B"]
    assert "SKU-3" in first["delivery"]["等待确认货号"]

    # 迟到的确认到达后再补发：SKU-3 按乙凭据只出现一次
    confirm = client.post("/api/attributions/confirm", json={
        "batch_label": BATCH, "source": YI, "sku": "SKU-3", "recipient": R_YI}).json()
    assert confirm["ok"] is True
    # 反复确认只算一次
    again = client.post("/api/attributions/confirm", json={
        "batch_label": BATCH, "source": YI, "sku": "SKU-3", "recipient": R_YI}).json()
    assert again["already_confirmed"] is True

    second = client.post("/api/attributions/deliver", json={
        "batch_label": BATCH, "recipient": R_YI}).json()
    assert second["delivered_skus"] == ["SKU-3"]
    line = second["lines"][0]
    assert line["报价"] == 12
    assert line["原始凭据"] == "乙-票据-SKU-3"

    # 再补发为空：同货号不重复
    third = client.post("/api/attributions/deliver", json={
        "batch_label": BATCH, "recipient": R_YI}).json()
    assert third["delivered_skus"] == []

    # 甲独有货号从未进入乙的任何交付批次
    deliveries = client.get("/api/attributions/deliveries",
                            params={"batch_label": BATCH, "recipient": R_YI}).json()
    all_skus = [sku for d in deliveries["items"] for sku in d["交付货号"]]
    assert "SKU-A" not in all_skus
    assert sorted(all_skus) == ["SKU-3", "SKU-B"]


def test_recipient_view_is_scoped_over_http():
    _register(JIA, "SKU-3", 10, R_JIA)
    _register(YI, "SKU-3", 12, R_YI)
    view = client.get("/api/attributions/recipient-view",
                      params={"batch_label": BATCH, "recipient": R_YI}).json()
    assert view["count"] == 1
    assert view["raw_rows"][0]["来源方"] == YI
    assert all(row["收件人"] != R_JIA for row in view["attributions"])


def test_on_site_complete_evidence_over_http():
    response = client.post("/api/attributions/confirm-on-site", json={
        "batch_label": BATCH,
        "source": YI,
        "sku": "SKU-X",
        "recipient": R_YI,
        "evidence": _evidence(YI, "SKU-X", 88),
    })
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["attribution"]["确认状态"] == "已确认"


def test_generic_resource_list_still_works():
    _register(YI, "SKU-9", 5, R_YI)
    response = client.get("/api/source_attribution", params={"size": 100})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert any(item["货号"] == "SKU-9" for item in payload["items"])
