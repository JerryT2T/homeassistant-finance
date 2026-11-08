"""Facts-panel read endpoints: bank_status, settings, balances, transactions.

All are cache reads - the fake manager raises if anything tries a live fetch.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.finance_dashboard.api import data as api_data


class _Resp:
    def __init__(self, data, status_code=200):
        self.data = data
        self.status = status_code


def _json(self, data, status_code=200):
    return _Resp(data, status_code)


class _Manager:
    def resolve_person(self, user):
        return None

    def _classifier(self):
        from custom_components.finance_dashboard.household_summary import Classifier

        return Classifier(None, [], None, [])

    def __init__(self, options=None):
        self._entry = MagicMock()
        self._entry.options = options or {}
        self._accounts = [
            {"id": "uid-1", "key": "k1", "type": "shared"},
            {"id": "uid-2", "key": "k2"},
        ]
        self._balances = {
            "uid-1": {
                "account_name": "Giro",
                "iban_masked": "****1234",
                "iban": "DE00SECRETSECRET1234",
                "institution": "Bank",
                "balances": [
                    {"balanceType": "CLBD", "balanceAmount": {"amount": "100.00", "currency": "EUR"}},
                    {"balanceType": "ITAV", "balanceAmount": {"amount": "150.00", "currency": "EUR"}},
                ],
            }
        }
        self.live_calls = 0
        self._txs = [
            {
                "bookingDate": f"2026-01-{d:02d}",
                "transactionAmount": {"amount": str(-d), "currency": "EUR"},
                "remittanceInformationUnstructured": "Rewe Markt" if d % 2 else "Miete",
                "_account_key": "k1" if d <= 6 else "k2",
                "_account_name": "Giro",
            }
            for d in range(1, 11)
        ]

    async def async_get_balance(self):
        return dict(self._balances)

    def get_balance_history(self, key):
        return [{"at": "2026-01-01T00:00:00+00:00"}, {"at": "2026-01-02T00:00:00+00:00"}]

    def get_bank_status(self):
        return [
            {
                "bank_id": "b1",
                "title": "Bank",
                "budget_used_today": 2,
                "budget_limit": 4,
                "blocked_until": None,
                "last_success": "2026-01-02T00:00:00+00:00",
                "last_error": None,
                "consent_valid_until": "2026-06-01T00:00:00+00:00",
                "consent_state": "expiring",
                "secret_extra": "must not leak",
            }
        ]

    def get_cached_transactions(self, limit=100):
        return self._txs[:limit]

    async def async_get_monthly_summary(self):
        return {"categories": {"food": 1}, "total_income": 0, "total_expenses": 1, "transaction_count": 1}

    async def async_refresh_transactions(self, *a, **k):  # pragma: no cover
        self.live_calls += 1
        raise AssertionError("cache read must not hit the bank")


def _request(admin: bool, query: dict | None = None):
    user = MagicMock()
    user.is_admin = admin
    req = MagicMock()
    req.get.side_effect = lambda k, d=None: user if k == "hass_user" else d
    req.query = query or {}
    req.app = {"hass": MagicMock()}
    return req


async def _call(view_cls, request, manager):
    view = view_cls()
    view.json = lambda data, status_code=200: _Resp(data, status_code)
    with patch.object(api_data, "_get_manager", return_value=manager):
        return await view.get(request)


@pytest.mark.asyncio
async def test_bank_status_non_admin_ok_and_whitelisted():
    m = _Manager()
    resp = await _call(api_data.FinanceDashboardBankStatusView, _request(False), m)
    assert resp.status == 200
    bank = resp.data["banks"][0]
    assert bank["consent_state"] == "expiring"
    assert bank["budget_used_today"] == 2
    assert "secret_extra" not in bank
    assert m.live_calls == 0


@pytest.mark.asyncio
async def test_bank_status_unconfigured():
    resp = await _call(api_data.FinanceDashboardBankStatusView, _request(False), None)
    assert resp.data == {"banks": [], "configured": False}


@pytest.mark.asyncio
async def test_settings_default_true_and_option_respected():
    resp = await _call(api_data.FinanceDashboardSettingsView, _request(False), _Manager())
    assert resp.data["show_household"] is True
    resp = await _call(
        api_data.FinanceDashboardSettingsView, _request(True), _Manager({"show_household": False})
    )
    assert resp.data["show_household"] is False
    assert resp.data["is_admin"] is True


@pytest.mark.asyncio
async def test_balances_booked_available_masked():
    resp = await _call(api_data.FinanceDashboardBalanceView, _request(False), _Manager())
    acc = resp.data["uid-1"]
    assert acc["booked"]["amount"] == "100.00"
    assert acc["available"]["amount"] == "150.00"
    assert acc["last_update"] == "2026-01-02T00:00:00+00:00"
    assert acc["account_key"] == "k1"
    assert acc["iban_masked"] == "****1234"
    assert "DE00SECRET" not in str(resp.data)


@pytest.mark.asyncio
async def test_transactions_non_admin_gets_aggregate_only():
    resp = await _call(api_data.FinanceDashboardTransactionsView, _request(False), _Manager())
    assert resp.data["privacy"] == "aggregate_only"
    assert "transactions" not in resp.data


@pytest.mark.asyncio
async def test_transactions_admin_filters_and_paging():
    view = api_data.FinanceDashboardTransactionsView
    m = _Manager()

    resp = await _call(view, _request(True, {"limit": "3"}), m)
    assert resp.data["total"] == 10
    assert [t["date"] for t in resp.data["transactions"]] == [
        "2026-01-10",
        "2026-01-09",
        "2026-01-08",
    ]

    resp = await _call(view, _request(True, {"limit": "3", "offset": "9"}), m)
    assert len(resp.data["transactions"]) == 1

    resp = await _call(view, _request(True, {"q": "rewe"}), m)
    assert resp.data["total"] == 5

    resp = await _call(view, _request(True, {"account": "k2"}), m)
    assert resp.data["total"] == 4

    resp = await _call(view, _request(True, {"from": "2026-01-03", "to": "2026-01-05"}), m)
    assert resp.data["total"] == 3

    resp = await _call(view, _request(True, {"limit": "abc", "offset": "-4"}), m)
    assert resp.data["limit"] == api_data.DEFAULT_PAGE_LIMIT
    assert resp.data["offset"] == 0
    assert m.live_calls == 0


@pytest.mark.asyncio
async def test_transactions_carry_owner_fields_for_the_chip():
    """E1-backend-payload: ledger_id + owner / source / confidence on every row (admin list)."""
    resp = await _call(api_data.FinanceDashboardTransactionsView, _request(True, {"limit": "5"}), _Manager())
    rows = resp.data["transactions"]
    assert rows
    for row in rows:
        assert {"ledger_id", "owner", "owner_source", "owner_confidence"} <= row.keys()
        assert row["owner"] in ("shared", "", "Anna", "Max") or isinstance(row["owner"], str)
    assert all(isinstance(r["owner_confidence"], int) for r in rows)
