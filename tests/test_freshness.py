"""Import log, "Aktualisieren" (reprocess only) and monthly validity."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from custom_components.finance_dashboard.freshness import (
    LOG_LIMIT,
    append_log,
    build_freshness,
    derivation_check,
    make_entry,
    monthly_validity,
    undated_accounts,
)
from tests.test_admin_gating import _FakeJsonMixin, _make_request
from tests.test_lifelong_history import _archive, _client, _manager, eb_tx

BAL = {"balances": [{"balance_type": "CLBD", "balance_amount": {"amount": "5", "currency": "EUR"}}]}


def _tx(d, amount, **extra):
    return {
        "bookingDate": d,
        "_status": "booked",
        "transactionAmount": {"amount": amount, "currency": "EUR"},
        **extra,
    }


def _pt(at, amount):
    return {"at": at, "type": "CLBD", "amount": amount, "currency": "EUR"}


def test_log_is_capped_and_holds_no_values():
    meta: dict = {}
    for i in range(LOG_LIMIT + 5):
        append_log(
            meta, make_entry("reprocess", at=f"t{i}", processing_version=2, outcome="rebuilt")
        )
    assert len(meta["import_log"]) == LOG_LIMIT
    assert set(meta["import_log"][0]) == {
        "at",
        "kind",
        "banks",
        "new",
        "total",
        "processing_version",
        "outcome",
        "duration_ms",
    }


def test_validity_ok_gap_unknown():
    accounts = {
        "k": {
            "transactions": [
                _tx("2026-02-05", "-10.00"),
                _tx("2026-02-20", "-5.50"),
                _tx("2026-03-10", "-1.00"),
            ],
            "balances": [
                _pt("2026-02-01T08:00:00+00:00", "100.00"),
                _pt("2026-02-28T08:00:00+00:00", "84.50"),
                _pt("2026-03-01T08:00:00+00:00", "84.50"),
                _pt("2026-03-30T08:00:00+00:00", "70.00"),
            ],
        }
    }
    rows = monthly_validity(accounts, {"k": "Giro"}, today=date(2026, 3, 31))
    by_month = {r["month"]: r for r in rows}
    assert by_month["2026-02"]["status"] == "ok"
    assert by_month["2026-03"]["status"] == "gap"
    assert by_month["2026-03"]["diff"] == -13.5
    assert by_month["2026-03"]["account_name"] == "Giro"
    rows = monthly_validity(
        {"k": {"transactions": [_tx("2026-01-05", "-1")]}}, {}, today=date(2026, 1, 31)
    )
    assert rows[0]["status"] == "unknown" and rows[0]["diff"] is None


def test_derivation_check_detects_lost_euro():
    ledger = [_tx("2026-01-01", "-10.00"), _tx("2026-01-02", "-5.00")]
    derived = [
        {**ledger[0], "category": "food"},
        {**ledger[1], "category": None, "_transfer_role": "destination"},
    ]
    assert derivation_check(ledger, derived)["ok"] is True
    assert derivation_check(ledger, derived[:1])["diff"] == -5.0


def test_non_admin_payload_is_minimal():
    log = [make_entry("import_attended", at="T", processing_version=2, outcome="ok")]
    kw = {"as_of": "A", "log": log, "processing_version": 2, "validity": [], "check": {}}
    assert build_freshness(admin=False, **kw) == {"as_of": "A", "last_import": "T"}
    full = build_freshness(admin=True, **kw)
    assert full["last_reprocess"] is None and full["log"][0]["kind"] == "import_attended"


def test_last_import_falls_back_to_bank_fetch_before_the_log_existed():
    kw = {"as_of": "A", "processing_version": 2, "validity": [], "check": {}}
    reprocess_only = [make_entry("reprocess", at="R", processing_version=2, outcome="ok")]
    out = build_freshness(admin=True, log=reprocess_only, last_bank_success="B", **kw)
    assert out["last_import"] == "B"
    logged = [make_entry("import_attended", at="T", processing_version=2, outcome="ok")]
    assert (
        build_freshness(admin=False, log=logged, last_bank_success="B", **kw)["last_import"] == "T"
    )
    assert build_freshness(admin=False, log=[], **kw)["last_import"] is None


@pytest.mark.asyncio
async def test_import_and_reprocess_are_logged_and_reprocess_never_calls_bank():
    client = _client(
        [
            (lambda p: "/transactions" in p, {"transactions": [eb_tx("r1", "2026-02-01")]}),
            (lambda p: "/balances" in p, BAL),
        ]
    )
    raw = _archive()
    mgr = _manager(client, raw)
    await mgr.async_refresh_transactions(psu_ip="10.0.0.9")
    await raw.async_flush()
    calls = len(client.calls)

    stats = await mgr.async_reprocess_and_derive()
    assert stats["outcome"] == "rebuilt" and stats["transaction_count"] == 1
    assert len(client.calls) == calls  # no bank call

    log = mgr._ledger.meta["import_log"]
    assert [e["kind"] for e in log] == ["import_attended", "reprocess"]
    assert log[0]["banks"] == ["DKB"] and log[0]["new"] == 1 and log[0]["total"] == 1
    assert log[1]["total"] == 1

    data = mgr.get_freshness(admin=True)
    assert data["last_import"] and data["last_reprocess"]
    assert data["log"][0]["kind"] == "reprocess"
    assert data["derivation"]["ok"] is True
    assert set(mgr.get_freshness(admin=False)) == {"as_of", "last_import"}


@pytest.mark.asyncio
async def test_views_gate_admin():
    from custom_components.finance_dashboard.api import (
        FinanceDashboardFreshnessView,
        FinanceDashboardReprocessView,
    )

    view = FinanceDashboardReprocessView()
    view.json = _FakeJsonMixin().json
    resp = await view.post(_make_request(is_admin=False))
    assert resp._status == 403

    fv = FinanceDashboardFreshnessView()
    fv.json = _FakeJsonMixin().json
    req = _make_request(is_admin=False)
    mgr = MagicMock()
    mgr.get_freshness.return_value = {"as_of": "A", "last_import": None}
    with patch("custom_components.finance_dashboard.api.refresh._get_manager", return_value=mgr):
        resp = await fv.get(req)
    mgr.get_freshness.assert_called_once_with(admin=False)
    assert resp._data["as_of"] == "A"


def test_undated_bookings_are_reported_per_account():
    accounts = {
        "pp": {
            "transactions": [
                _tx("", "-5"),
                _tx("", "-6", transactionDate="2026-04-02"),
                _tx("2026-04-03", "-1"),
            ]
        },
        "giro": {"transactions": [_tx("2026-04-03", "-1")]},
    }
    assert undated_accounts(accounts, {"pp": "PayPal", "giro": "Giro"}) == [
        {"account_name": "PayPal", "undated": 1, "total": 3}
    ]


def test_data_quality_is_admin_only():
    q = [{"account_name": "PayPal", "undated": 2, "total": 3}]
    kw = {"as_of": "x", "log": [], "processing_version": 1, "validity": [], "check": {}}
    assert build_freshness(**kw, admin=True, data_quality=q)["data_quality"] == q
    assert "data_quality" not in build_freshness(**kw, admin=False, data_quality=q)
