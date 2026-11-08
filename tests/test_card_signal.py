"""Card-suffix signal: a household-only account used with a person's own card."""

from __future__ import annotations

import pytest

from custom_components.finance_dashboard.account_identity import account_key
from custom_components.finance_dashboard.const import OWNER_SHARED
from custom_components.finance_dashboard.manager import AssignmentError, FinanceDashboardManager
from custom_components.finance_dashboard.ownership import card_person, resolve_owner_detail
from tests.test_assignments import USERS, _mgr
from tests.test_ownership import POS, _tx

_PERSONS = [{"name": "Anna", "ha_users": []}, {"name": "Max", "ha_users": []}]


def _card_tx(kind="household", **extra):
    return _tx(
        kind=kind,
        _card_person="Anna",
        remittanceInformationUnstructured="KARTENZAHLUNG Kino Karte *4321",
        **extra,
    )


def test_suffix_parsing_needs_a_card_marker() -> None:
    owners = {"4321": "Anna"}
    assert card_person({"remittanceInformationUnstructured": "Kino Karte *4321"}, owners) == "Anna"
    assert card_person({"remittanceInformationUnstructured": "VISA xxxx 4321 Kino"}, owners) == "Anna"
    assert card_person({"cardNumber": "1234 5678 9012 4321"}, owners) == "Anna"
    assert card_person({"remittanceInformationUnstructured": "Rechnung 4321"}, owners) == ""
    assert card_person({"remittanceInformationUnstructured": "Max 4321"}, owners) == ""
    assert card_person({"remittanceInformationUnstructured": "Kino *9999"}, owners) == ""
    assert card_person({"remittanceInformationUnstructured": "Kino *4321"}, None) == ""


def test_mapped_card_applies_on_household_account() -> None:
    assert resolve_owner_detail(_card_tx()) == ("Anna", "card", 80)


def test_household_category_stays_household() -> None:
    owner, source, _ = resolve_owner_detail(_card_tx(category="groceries"))
    assert (owner, source) == (OWNER_SHARED, "account")


def test_unmapped_suffix_is_household() -> None:
    tx = _tx(kind="household", _card_person="", remittanceInformationUnstructured="Karte *9999")
    assert resolve_owner_detail(tx)[0] == OWNER_SHARED


def test_other_accounts_unaffected() -> None:
    assert resolve_owner_detail(_card_tx(kind="person", person="Max"))[:2] == ("Max", "account")
    assert resolve_owner_detail(_card_tx(kind="open"))[0] == "open"
    assert resolve_owner_detail(_card_tx(kind="person_household", person="Max"))[0] == "Max"


def test_higher_signals_win() -> None:
    assert resolve_owner_detail(_card_tx(), correction="Max")[1] == "correction"
    assert resolve_owner_detail(_card_tx(_owner_override="Max"))[1] == "merchant_rule"
    assert resolve_owner_detail(_card_tx(), position=POS)[1] == "plan"
    assert resolve_owner_detail(_card_tx(_series_owner="Max"))[1] == "account"


def _set_cards(mgr, owner, cards):
    item = {"key": account_key(mgr._accounts[1]), "owner": owner, "household": False}
    if cards is not None:
        item["card_owners"] = cards
    return FinanceDashboardManager.async_set_assignments(
        mgr, {"persons": _PERSONS, "accounts": [item]}, USERS
    )


def test_mapping_saved_only_on_household_account() -> None:
    mgr = _mgr(_PERSONS)
    assert _set_cards(mgr, "shared", {"4321": "Anna"}) is True
    assert mgr._accounts[1]["card_owners"] == {"4321": "Anna"}
    out = FinanceDashboardManager.get_assignments(mgr, USERS)
    assert out["accounts"][1]["card_owners"] == {"4321": "Anna"}
    _set_cards(mgr, "Anna", None)  # no longer household-only: mapping dropped
    assert "card_owners" not in mgr._accounts[1]


@pytest.mark.parametrize(
    ("bad", "code"),
    [
        ({"12": "Anna"}, "invalid_card_suffix"),
        ({"abcd": "Anna"}, "invalid_card_suffix"),
        ({"4321": "Nobody"}, "unknown_card_person"),
        ([], "invalid_card_owners"),
    ],
)
def test_mapping_validation(bad, code) -> None:
    mgr = _mgr(_PERSONS)
    with pytest.raises(AssignmentError) as err:
        _set_cards(mgr, "shared", bad)
    assert err.value.code == code
