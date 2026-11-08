"""Contract detection is memoised per data version for the year view / review."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from custom_components.finance_dashboard.manager import _review
from custom_components.finance_dashboard.manager._banks import BankMixin
from custom_components.finance_dashboard.manager._review import ReviewMixin


def _mgr():
    return SimpleNamespace(
        _hass=object(),
        _transactions=[],
        _accounts=[{"id": "a1", "type": "personal", "person": "Anna"}],
        _contracts_cache_key=None,
    )


def _store():
    return SimpleNamespace(
        contracts={}, aliases={}, manual={}, structure=None, async_save_if_changed=AsyncMock()
    )


def _run(mgr, store, calls):
    def fake_build(*_a, **_k):
        calls.append(1)
        return [{"id": "s1"}]

    async def go():
        with (
            patch.object(_review, "async_get_store", AsyncMock(return_value=store)),
            patch.object(_review, "build_contracts", fake_build),
        ):
            mgr._contracts_cache_key = lambda s: ReviewMixin._contracts_cache_key(mgr, s)
            return await ReviewMixin._contracts_list(mgr)

    return asyncio.run(go())


def test_two_year_requests_run_detection_once_and_rederive_invalidates() -> None:
    mgr, store, calls = _mgr(), _store(), []
    first = _run(mgr, store, calls)
    first[0]["id"] = "mutated"  # a caller must not poison the cache
    assert _run(mgr, store, calls) == [{"id": "s1"}]
    assert len(calls) == 1

    mgr._derive_version = getattr(mgr, "_derive_version", 0) + 1  # what _derive_from_ledger does
    _run(mgr, store, calls)
    assert len(calls) == 2


def test_contract_decision_invalidates() -> None:
    mgr, store, calls = _mgr(), _store(), []
    _run(mgr, store, calls)
    store.aliases["netflix"] = "s1"  # a learned alias / user decision
    _run(mgr, store, calls)
    assert len(calls) == 2


def test_derive_from_ledger_bumps_version() -> None:
    import inspect

    assert "_derive_version" in inspect.getsource(BankMixin._derive_from_ledger)
