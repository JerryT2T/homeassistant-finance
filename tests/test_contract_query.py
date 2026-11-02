"""POST /contracts/query (#118): consent, payload and failure handling (fakes, no HA core)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.finance_dashboard import ai_provider
from custom_components.finance_dashboard.api import contracts as api


class _Json:
    def json(self, data, status_code=200):
        return SimpleNamespace(_data=data, _status=status_code)


class _Request:
    def __init__(self, body):
        self._body = body
        self.app = {"hass": MagicMock()}

    def get(self, key, default=None):
        return SimpleNamespace(is_admin=False) if key == "hass_user" else default

    async def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _Call:
    """``run_contract_query`` with the same result shape the view answers with."""

    async def post(self, request):
        body = None
        try:
            body = await request.json()
        except ValueError:
            pass
        data, status = await api.run_contract_query(request.app["hass"], api._get_manager(None), body)  # noqa: SLF001
        return SimpleNamespace(_data=data, _status=status)


def _view():
    return _Call()


@pytest.fixture
def env(monkeypatch):
    """Consent granted, provider usable; captures what is sent and what is spent."""
    state = SimpleNamespace(consent=True, usable=True, remaining=50, prompts=[], answer="{}", used=0,
                            error=None)
    manager = SimpleNamespace(persons=[{"name": "Anna"}, {"name": "Ben"}], _credential_manager=None)
    monkeypatch.setattr(api, "_get_manager", lambda _h: manager)

    async def status(_h, _m):
        return {"usable": state.usable, "consented": state.consent, "remaining": state.remaining}

    async def vocab(_h, _m):
        return {"categories": ["media", "finance", "other"], "labels": {"home": None, "gift": "Geschenke"},
                "owners": {"Anna", "Ben"}}

    async def ask(_hass, **kw):
        state.prompts.extend(kw["prompts"])
        return (None, state.error) if state.error else ([state.answer], None)

    async def used(_h, purpose):
        assert purpose == "contract_query"
        state.used += 1

    monkeypatch.setattr(api, "_query_ai_status", status)
    monkeypatch.setattr(api, "_query_vocab", vocab)
    monkeypatch.setattr(api.ai_provider, "async_extract_history", ask)
    monkeypatch.setattr(api.ai_consent, "async_mark_used", used)
    return state


@pytest.mark.asyncio
async def test_without_consent_nothing_is_sent(env) -> None:
    env.consent = False
    res = await _view().post(_Request({"question": "alle Abos"}))
    assert res._status == 403 and res._data["error"] == "consent_required"
    assert env.prompts == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("flag", "value", "error"), [("usable", False, "no_provider"), ("remaining", 0, "budget_exhausted")])
async def test_no_provider_or_budget_refuses(env, flag, value, error) -> None:
    setattr(env, flag, value)
    res = await _view().post(_Request({"question": "alle Abos"}))
    assert res._status == 400 and res._data["error"] == error
    assert env.prompts == []


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"question": "  "}, {"question": 5}, [], ValueError("bad")])
async def test_bad_body_is_400(env, body) -> None:
    res = await _view().post(_Request(body))
    assert res._status == 400
    assert env.prompts == []


@pytest.mark.asyncio
async def test_payload_has_no_amounts_ibans_dates_or_contract_names(env) -> None:
    env.answer = json.dumps({"kinds": ["subscription"], "owners": ["ich"], "amount_min": 20})
    q = "Abos von mir ueber 20 Euro, Konto DE89 3704 0044 0532 0130 00, Nr 123456789"
    res = await _view().post(_Request({"question": q}))
    assert res._status == 200
    assert res._data["spec"]["kinds"] == ["subscription"]
    assert res._data["spec"]["owners"] == ["me"]
    assert res._data["spec"]["amount_min"] == 20
    assert res._data["errors"] == []
    (prompt,) = env.prompts
    for secret in ("DE89", "0532", "123456789"):
        assert secret not in prompt
    # only the question and the allowed names: persons, labels, categories
    for name in ("Anna", "Ben", "Geschenke", "media", "finance"):
        assert name in prompt
    assert env.used == 1


@pytest.mark.asyncio
async def test_invalid_ai_json_gives_errors_not_a_crash(env) -> None:
    env.answer = "Sorry, I cannot do that."
    res = await _view().post(_Request({"question": "alle Abos"}))
    assert res._status == 200
    assert res._data["errors"] == [{"field": "_", "reason": "unparsable"}]
    assert res._data["spec"]["kinds"] == []


@pytest.mark.asyncio
async def test_partial_spec_keeps_valid_parts_and_reports_the_rest(env) -> None:
    env.answer = '{"kinds": ["subscription", "weird"], "owners": ["Clara"], "categories": ["media"], "sort": 3}'
    res = await _view().post(_Request({"question": "x"}))
    data = res._data
    assert data["spec"]["kinds"] == ["subscription"]
    assert data["spec"]["categories"] == ["media"]
    assert data["spec"]["owners"] == []
    assert {e["field"] for e in data["errors"]} == {"kinds", "owners", "sort"}


@pytest.mark.asyncio
async def test_provider_failure_is_502_and_spends_no_consent_use(env) -> None:
    env.error = "timeout"
    res = await _view().post(_Request({"question": "x"}))
    assert res._status == 502 and res._data["error"] == "timeout"
    assert env.used == 0


def test_ai_call_counts_against_the_shared_budget() -> None:
    """The query goes through the budget-checked provider path used by the import."""
    import inspect

    assert "spend_call" in inspect.getsource(ai_provider.async_extract_history)
