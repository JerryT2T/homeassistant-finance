"""Series detection, contract derivations, reserves and pot coverage."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.finance_dashboard.account_identity import account_key
from custom_components.finance_dashboard.contracts import (
    Contract,
    ContractError,
    ContractStore,
    build_contracts,
    build_reserves,
    category_defaults,
    next_notice_deadline,
    special_termination_default,
)
from custom_components.finance_dashboard.pots import Pot, pot_coverage
from custom_components.finance_dashboard.recurring import (
    add_months,
    detect_recurring,
    detect_series,
    plan_amount,
)


def txn(day: str, amount: float, name: str = "Acme", category: str = "other", **extra):
    return {
        "_status": "booked",
        "bookingDate": day,
        "creditorName": name,
        "transactionAmount": {"amount": str(amount), "currency": "EUR"},
        "category": category,
        **extra,
    }


def monthly(amounts, name="Netflix", start=date(2026, 1, 10), **kw):
    return [txn(add_months(start, i).isoformat(), a, name, **kw) for i, a in enumerate(amounts)]


TODAY = date(2026, 6, 15)


def blank_store() -> ContractStore:
    """A store without Home Assistant storage behind it."""
    store = ContractStore.__new__(ContractStore)
    store.contracts, store.notified, store.aliases, store.manual = {}, set(), {}, {}
    store._aliases_changed = False  # noqa: SLF001
    return store


def test_monthly_series_and_next_date():
    (s,) = detect_series(monthly([-10, -10, -10, -10, -10]), today=TODAY)
    assert s["interval"] == "monthly"
    assert s["next_expected"] == "2026-06-10"
    assert s["annual_cost"] == 120.0


def test_missing_and_ended_state():
    rows = monthly([-10, -10, -10])  # last: 2026-03-10, next 04-10
    (s,) = detect_series(rows, today=date(2026, 4, 20))
    assert s["status"] == "missing"
    (s,) = detect_series(rows, today=date(2026, 8, 1))
    assert s["status"] == "ended"
    (s,) = detect_series(rows, today=date(2026, 4, 12))
    assert s["status"] == "active"


@pytest.mark.parametrize(
    ("rows", "interval"),
    [
        ([txn(f"2026-01-{d:02d}", -5) for d in (1, 8, 15, 22, 29)], "weekly"),
        (
            [txn("2025-01-05", -90), txn("2025-04-05", -90), txn("2025-07-05", -90)],
            "quarterly",
        ),
        ([txn("2025-01-05", -300), txn("2025-07-05", -300)], "half_yearly"),
        ([txn("2024-03-01", -480), txn("2025-03-01", -480)], "yearly"),
    ],
)
def test_other_intervals(rows, interval):
    (s,) = detect_series(rows, today=date(2026, 12, 31))
    assert s["interval"] == interval


def test_irregular_gaps_rejected():
    rows = [txn("2026-01-01", -10), txn("2026-01-20", -10), txn("2026-04-02", -10)]
    assert detect_series(rows, today=TODAY) == []


def test_tolerances_configurable():
    rows = monthly([-10, -13, -17])  # two +30 % steps
    assert detect_series(rows, today=TODAY) == []
    assert len(detect_series(rows, today=TODAY, amount_tolerance=0.4)) == 1


def test_price_change_detected_with_step_beyond_tolerance():
    (s,) = detect_series(monthly([-10, -10, -10, -15]), today=TODAY)
    pc = s["price_change"]
    assert pc["increase"] is True
    assert pc["previous"] == -10.0 and pc["last"] == -15.0
    assert pc["change_pct"] == 50.0


def test_plan_modes():
    amounts = [-10.0, -12.0, -20.0, -14.0]
    assert plan_amount(amounts) == 13.0  # auto: no clean step -> median (#114)
    assert plan_amount(amounts, "highest") == 20.0
    assert plan_amount(amounts, "average") == 14.0
    assert plan_amount(amounts, "last") == 14.0
    assert plan_amount(amounts, "median") == 13.0
    assert plan_amount(amounts, "fixed", 99) == 99.0


def test_plan_mode_override_applies():
    rows = monthly([-10, -12, -11])
    (a,) = detect_series(rows, today=TODAY)
    (b,) = detect_series(
        rows, today=TODAY, overrides={a["id"]: {"plan_mode": "fixed", "plan_fixed_amount": 50}}
    )
    assert a["plan_amount"] == -11.0 and b["plan_amount"] == -50.0


def test_legacy_monthly_detector_untouched():
    out = detect_recurring([dict(t, _status="booked") for t in monthly([-10, -10, -10])])
    assert out and out[0]["frequency"] == "monthly"


def test_add_months_clamps():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 3, 15), -3) == date(2025, 12, 15)


def test_category_defaults():
    assert category_defaults("health")["notice_value"] == 3
    assert category_defaults("telecom")["min_term_months"] == 24
    assert category_defaults("media")["notice_value"] == 0
    assert category_defaults("whatever")["renewal_months"] == 1


def test_notice_deadline_end_of_term_and_rollover():
    # 1y term from 2026-01-01, 3 months notice -> term end 2027-01-01, deadline 2026-10-01
    d, eff = next_notice_deadline(
        date(2026, 1, 1), 12, 12, 3, "months", "end_of_term", date(2026, 6, 15)
    )
    assert (d, eff) == (date(2026, 10, 1), date(2027, 1, 1))
    # deadline passed -> next renewal period
    d, _ = next_notice_deadline(
        date(2026, 1, 1), 12, 12, 3, "months", "end_of_term", date(2026, 11, 1)
    )
    assert d == date(2027, 10, 1)


def test_notice_deadline_end_of_month_reference():
    d, eff = next_notice_deadline(
        date(2026, 1, 10), 24, 12, 1, "months", "end_of_month", date(2026, 6, 1)
    )
    assert eff == date(2028, 1, 31) and d == date(2027, 12, 31)


def test_special_termination_pattern():
    even = monthly([-10, -10, -15])
    (s,) = detect_series(even, today=TODAY)
    assert special_termination_default(s) is True
    # amount, day and gap all vary -> usage-based billing
    messy = [
        txn("2026-01-03", -30),
        txn("2026-02-12", -45),
        txn("2026-03-27", -38),
    ]
    s2 = {
        "dates": [t["bookingDate"] for t in messy],
        "amounts": [-30, -45, -38],
    }
    assert special_termination_default(s2) is False


def test_build_contracts_sorted_and_flags(monkeypatch):
    store = blank_store()
    rows = monthly([-10, -10, -10, -15], name="Strom AG", category="utilities") + monthly(
        [-9.99] * 4, name="Streamingdienst", category="subscriptions"
    )
    out = build_contracts(rows, store, today=TODAY)
    assert {c["creditor"] for c in out} == {"strom ag", "streamingdienst"}
    assert {c["display_name"] for c in out} == {"Strom AG", "Streamingdienst"}
    deadlines = [c["next_deadline"] for c in out]
    assert deadlines == sorted(deadlines)
    strom = next(c for c in out if c["creditor"] == "strom ag")
    assert strom["special_termination_available"] is True
    assert strom["contract"]["notice_unit"] == "months"
    store.contracts[strom["id"]] = Contract(strom["id"], special_termination=False)
    out = build_contracts(rows, store, today=TODAY)
    assert next(c for c in out if c["id"] == strom["id"])["special_termination_available"] is False


def test_contract_validation():
    c = Contract("s_x")
    c.apply({"min_term_months": 12, "notice_unit": "weeks", "start": "2026-01-01"})
    assert c.min_term_months == 12
    for bad in (
        {"notice_unit": "years"},
        {"start": "nope"},
        {"min_term_months": -1},
        {"min_term_months": True},
        {"plan_mode": "fixed"},
        {"bogus": 1},
        {"special_termination": "yes"},
    ):
        with pytest.raises(ContractError):
            Contract("s_x").apply(bad)


def test_reserves_from_irregular_series():
    store = blank_store()
    rows = [
        txn("2025-03-01", -120, "Haftpflicht", "insurance"),
        txn("2026-03-01", -120, "Haftpflicht", "insurance"),
    ] + monthly([-10] * 4, name="Netflix")
    res = build_reserves(build_contracts(rows, store, today=TODAY))
    assert [i["creditor"] for i in res["items"]] == ["haftpflicht"]
    assert res["items"][0]["monthly_reserve"] == 10.0
    assert res["total_monthly"] == 10.0


def test_pot_coverage():
    acc = {"id": "u1", "iban": "DE89370400440532013000", "name": "Spar", "savings": True}
    key = account_key(acc)
    pots = [
        Pot(id="a", name="Urlaub", cycle_budget=300, kind="reserve", account_key=key),
        Pot(id="b", name="Auto", cycle_budget=200, kind="reserve", account_key=key),
        Pot(id="c", name="Food", cycle_budget=400, kind="spend", account_key=key),
        Pot(id="d", name="Orphan", cycle_budget=50, kind="reserve"),
    ]

    def bal(amount):
        return {
            "u1": {
                "balances": [{"balanceType": "closingBooked", "balanceAmount": {"amount": amount}}]
            }
        }

    short = pot_coverage(pots, [acc], bal("420.00"))
    row = short["accounts"][0]
    assert row["virtual_total"] == 500.0 and row["status"] == "shortfall"
    assert row["top_up"] == 80.0 and short["unassigned_pots"] == 1 and row["savings"]
    ok = pot_coverage(pots, [acc], bal("500.00"))
    assert ok["status"] == "covered" and ok["total_top_up"] == 0.0
    assert pot_coverage(pots, [acc], {})["accounts"][0]["status"] == "unknown"


def test_pot_account_key_roundtrip():
    p = Pot.from_dict({"name": "X", "kind": "reserve", "account_key": " k1 "})
    assert Pot.from_dict(p.to_dict()).account_key == "k1"


async def test_notice_due_event_fires_once(monkeypatch):
    from custom_components.finance_dashboard import contracts as mod

    store = blank_store()

    async def _noop():
        return None

    store.async_save = _noop

    async def _get(_hass):
        return store

    monkeypatch.setattr(mod, "async_get_store", _get)
    fired = []

    class Bus:
        def async_fire(self, event, data):
            fired.append((event, data))

    hass = type("H", (), {"bus": Bus()})()
    rows = monthly([-30] * 4, name="Versicherung", category="health", start=date(2026, 3, 10))
    from custom_components.finance_dashboard.recurring import series_id

    sid = series_id("versicherung", True)
    store.contracts[sid] = Contract(sid, start="2025-10-01")
    today = date(2026, 6, 20)
    n = await mod.async_fire_notice_due(hass, rows, today=today)
    assert n == 1 and fired[0][0] == "finance_dashboard_notice_due"
    assert "amount" not in fired[0][1]
    assert await mod.async_fire_notice_due(hass, rows, today=today) == 0


def test_set_account_savings_flags_known_key_without_mutating_source() -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from custom_components.finance_dashboard.contracts import set_account_savings

    acc = {"id": "uid1", "iban": "DE00000000000000000001"}
    mgr = SimpleNamespace(_accounts=[acc], async_set_accounts=MagicMock())
    assert set_account_savings(mgr, account_key(acc), True) is True
    written = mgr.async_set_accounts.call_args.args[0]
    assert written[0]["savings"] is True and "savings" not in acc
    mgr.async_set_accounts.reset_mock()
    assert set_account_savings(mgr, "unknown", True) is False
    mgr.async_set_accounts.assert_not_called()


def test_member_contract_view_is_gated_and_reduced() -> None:
    from custom_components.finance_dashboard.contracts import aggregate_view, visible_to

    shared, anna = {"owner": "shared"}, {"owner": "Anna"}
    assert visible_to(shared, None) and visible_to(anna, "Anna")
    assert not visible_to(anna, "Max") and not visible_to(anna, None) and not visible_to(anna, "")

    store = blank_store()
    items = build_contracts(
        monthly([-9.99] * 4, name="Streamingdienst", category="subscriptions"), store, today=TODAY
    )
    assert items
    for item in items:
        view = aggregate_view(item)
        assert "contract" not in view and set(view) < set(item)
        assert view["id"] == item["id"]


def test_own_transfers_are_not_contracts():
    from custom_components.finance_dashboard.household_summary import counted_transactions

    store = blank_store()
    own = [
        {**r, "_transfer_chain_id": f"c{i}", "_transfer_role": "source"}
        for i, r in enumerate(monthly([-500] * 4, name="Herr Max Muster"))
    ]
    real = monthly([-9.99] * 4, name="Streamingdienst", category="subscriptions")
    out = build_contracts(counted_transactions(own + real, []), store, today=TODAY)
    assert {c["creditor"] for c in out} == {"streamingdienst"}


def test_payments_to_own_account_holders_are_not_contracts():
    from custom_components.finance_dashboard.contracts import own_account_names

    names = own_account_names([{"name": "Max Muster und Erika Muster"}, {"name": "PayPal"}])
    assert names == {"max muster", "erika muster"}
    store = blank_store()
    rows = (
        monthly([-500] * 4, name="Herr Max Muster")
        + monthly([-300] * 4, name="Max Peter Muster")
        + monthly([-20] * 4, name="Maxi Musterhaus")
        + monthly([-9.99] * 4, name="Streamingdienst", category="subscriptions")
    )
    out = build_contracts(rows, store, today=TODAY, own_names=names)
    assert {c["creditor"] for c in out} == {"streamingdienst", "maxi musterhaus"}


# ---------------------------------------------------------------------------
# Stable ids across payee spellings (#122)
# ---------------------------------------------------------------------------


def test_canonical_name_ignores_spelling_legal_form_and_encoding():
    from custom_components.finance_dashboard.text_norm import canonical_name, repair_mojibake

    assert repair_mojibake("Streamly S.\u00c3\u00a0 r.l.") == "Streamly S.\u00e0 r.l."
    variants = [
        "Streamly S.\u00e0 r.l.",
        "Streamly S.\u00c3\u00a0 r.l.",
        "STREAMLY SARL",
        "Streamly S.a.r.l.",
    ]
    assert {canonical_name(v) for v in variants} == {"streamly"}
    assert canonical_name("Autoclub Muster e.V.") == "autoclub muster"
    assert canonical_name("Müller GmbH & Co. KG") == "mueller"
    assert canonical_name("PayPal Europe S.a.r.l. et Cie S.C.A") == "paypal europe"
    assert canonical_name("AG") == "ag"  # never empty for a real name
    # numbered or lettered payees and non-latin names stay apart
    assert canonical_name("Kita 1") != canonical_name("Kita 2")
    assert canonical_name("Apotheke A") != canonical_name("Apotheke B")
    assert canonical_name("Иван") != canonical_name("Петр")
    assert canonical_name("Иван")


def test_unchanged_payee_keeps_its_previous_id():
    from custom_components.finance_dashboard.recurring import series_id

    (s,) = detect_series(monthly([-10] * 4, name="Netflix International B.V."), today=TODAY)
    assert s["id"] == series_id("netflix international b.v.", True)


def _renamed_rows():
    old = monthly([-12.99] * 3, name="Streamly S.\u00e0 r.l.", start=date(2026, 1, 10))
    new = monthly([-12.99] * 2, name="Streamly S.\u00c3\u00a0 r.l.", start=date(2026, 4, 10))
    return old + new


def test_renamed_payee_keeps_contract_id_and_fields():
    from custom_components.finance_dashboard.recurring import series_id

    store = blank_store()
    sid = series_id("streamly s.\u00e0 r.l.", True)
    store.contracts[sid] = Contract(sid, notice_value=2, notice_unit="weeks")
    (c,) = build_contracts(_renamed_rows(), store, today=TODAY)
    assert c["id"] == sid
    assert c["occurrences"] == 5
    assert (c["contract"]["notice_value"], c["contract"]["notice_unit"]) == (2, "weeks")


def test_alias_keeps_id_after_old_spelling_leaves_history():
    store = blank_store()
    (first,) = build_contracts(_renamed_rows(), store, today=TODAY)
    assert store.aliases == {first["alias_key"]: first["id"]}
    only_new = [r for r in _renamed_rows() if "\u00c3" in r["creditorName"]]
    (again,) = build_contracts(only_new, store, today=TODAY)
    assert again["id"] == first["id"]


async def test_aliases_persist_and_hold_no_amounts(monkeypatch):
    from custom_components.finance_dashboard import contracts as mod
    from tests.fakes import FakeStore

    monkeypatch.setattr(mod, "Store", FakeStore)
    store = mod.ContractStore(None)
    build_contracts(_renamed_rows(), store, today=TODAY)
    await store.async_save_if_changed()
    raw = await store._store.async_load()  # noqa: SLF001
    assert set(raw["aliases"]) == {"streamly|out"}
    assert "12.99" not in str(raw["aliases"])
    reloaded = mod.ContractStore(None)
    reloaded._store = store._store  # noqa: SLF001
    await reloaded.async_load()
    assert reloaded.aliases == store.aliases


def test_spellings_that_each_own_a_contract_stay_separate():
    from custom_components.finance_dashboard.recurring import series_id

    store = blank_store()
    gmbh, ag = series_id("acme gmbh", True), series_id("acme ag", True)
    store.contracts[gmbh] = Contract(gmbh, notice_value=1)
    store.contracts[ag] = Contract(ag, notice_value=2)
    rows = monthly([-10] * 3, name="Acme GmbH") + monthly([-50] * 3, name="Acme AG")
    out = build_contracts(rows, store, today=TODAY)
    assert {c["id"] for c in out} == {gmbh, ag}


# --- one payee, several series (#108) ---------------------------------------


@pytest.mark.parametrize(
    ("text", "ref"),
    [
        ("Darlehen 4711001 Rate 08/2026", "4711001"),
        ("Beitrag Vertrag HR-20031", "hr-20031"),
        ("Abschlag Kd-Nr 5550123", "5550123"),
        ("Mandatsreferenz: ABC12345", "abc12345"),
        ("Abo Cloudspeicher 200 GB", ""),
        ("Ratenkauf 88123 Teil 1/3", ""),
        ("Rechnung 89002", ""),
        ("Kreditkartenabrechnung 12345678", ""),
    ],
)
def test_contract_reference(text, ref):
    from custom_components.finance_dashboard.recurring import contract_reference

    assert contract_reference(text) == ref


def _loans(months=4, second_from=0):
    rows = []
    for i in range(months):
        day = add_months(date(2026, 2, 1), i).isoformat()
        rows.append(
            txn(day, -250, "Musterbank AG", remittanceInformationUnstructured="Darlehen 4711001")
        )
        if i >= second_from:
            rows.append(
                txn(
                    day, -180, "Musterbank AG", remittanceInformationUnstructured="Darlehen 4711002"
                )
            )
    return rows


def test_two_loans_of_one_lender_become_two_series_with_full_amounts():
    from custom_components.finance_dashboard.recurring import series_id

    out = detect_series(_loans(), today=TODAY)
    assert sorted(abs(s["plan_amount"]) for s in out) == [180.0, 250.0]
    base = series_id("musterbank ag", True)
    assert base in {s["id"] for s in out}, "the earliest stream keeps the payee id"
    assert len({s["id"] for s in out}) == 2


def test_split_ids_stay_put_when_a_loan_ends():
    store = blank_store()
    first = {abs(c["plan_amount"]): c["id"] for c in build_contracts(_loans(), store, today=TODAY)}
    only_second = [r for r in _loans() if "4711002" in r["remittanceInformationUnstructured"]]
    (again,) = build_contracts(only_second, store, today=TODAY)
    assert again["id"] == first[180.0]


def test_aliases_of_split_series_hold_no_reference_numbers():
    store = blank_store()
    build_contracts(_loans(), store, today=TODAY)
    assert "4711001" not in str(store.aliases) and "250" not in str(store.aliases)


def test_successor_reference_is_not_a_second_contract():
    rows = [
        txn(
            add_months(date(2026, 1, 3), i).isoformat(),
            -30,
            "Fitness Club",
            remittanceInformationUnstructured=f"Mitglieds-Nr {'1001' if i < 3 else '2002'}",
        )
        for i in range(6)
    ]
    (s,) = detect_series(rows, today=TODAY)
    assert s["occurrences"] == 6


def test_subscription_is_found_among_one_off_purchases():
    rows = monthly([-9.99] * 4, name="Appstore", start=date(2026, 2, 5))
    rows += [
        txn("2026-02-17", -2.99, "Appstore"),
        txn("2026-03-21", -24.99, "Appstore"),
        txn("2026-04-14", -0.99, "Appstore"),
    ]
    (s,) = detect_series(rows, today=TODAY)
    assert s["plan_amount"] == -9.99 and s["occurrences"] == 4


def test_finite_instalments_never_form_a_series_inside_a_mixed_payee():
    rows = monthly([-4.99] * 3, name="Klarnetta", start=date(2026, 3, 20))
    rows += [
        txn("2026-03-02", -33.33, "Klarnetta", remittanceInformationUnstructured="Teil 1/3"),
        txn("2026-04-02", -33.33, "Klarnetta", remittanceInformationUnstructured="Teil 2/3"),
        txn("2026-04-25", -18.50, "Klarnetta"),
    ]
    (s,) = detect_series(rows, today=TODAY)
    assert s["plan_amount"] == -4.99


def test_price_step_stays_one_series():
    from custom_components.finance_dashboard.recurring import series_id

    (s,) = detect_series(monthly([-10, -10, -10, -10, -13]), today=TODAY)
    assert s["occurrences"] == 5
    assert s["id"] == series_id("netflix", True)
    assert s["price_change"]["increase"]


def test_two_similar_purchases_inside_a_busy_shop_are_no_series():
    rows = [
        txn("2026-02-03", -182.00, "Baumarkt"),
        txn("2026-02-11", -12.40, "Baumarkt"),
        txn("2026-02-27", -47.10, "Baumarkt"),
        txn("2026-03-04", -189.00, "Baumarkt"),
        txn("2026-03-19", -7.95, "Baumarkt"),
    ]
    assert detect_series(rows, today=TODAY) == []


def test_price_step_beside_a_one_off_stays_one_series():
    rows = monthly([-9.99] * 6 + [-11.99] * 6, name="Streamly", start=date(2025, 6, 10))
    rows.append(txn("2025-09-21", -25.00, "Streamly"))
    (s,) = detect_series(rows, today=TODAY)
    assert s["occurrences"] == 12
    assert s["price_change"] is None or s["last_amount"] == -11.99


def test_same_day_split_gives_the_payee_id_independent_of_input_order():
    first = {abs(s["plan_amount"]): s["id"] for s in detect_series(_loans(), today=TODAY)}
    flipped = {abs(s["plan_amount"]): s["id"] for s in detect_series(_loans()[::-1], today=TODAY)}
    assert first == flipped


def test_parts_of_one_payee_never_share_an_id():
    from custom_components.finance_dashboard.recurring import _part_id, _Part

    part = _Part([], "monthly", "~same")
    used: set[str] = set()
    ids = []
    for _ in range(3):
        sid = _part_id(
            part,
            is_base=False,
            canonical="x",
            names=["x"],
            negative=True,
            aliases={},
            known=set(),
            used=used,
        )
        used.add(sid)
        ids.append(sid)
    assert len(set(ids)) == 3


def test_a_reference_on_two_invoices_does_not_split_a_contract():
    rows = monthly([-40] * 5, name="Stadtwerke", start=date(2026, 1, 10))
    for r in rows:
        r["remittanceInformationUnstructured"] = "Abschlag Kd-Nr 5550123"
    rows += [
        txn(
            "2026-02-14",
            -12,
            "Stadtwerke",
            remittanceInformationUnstructured="Vertrag 77001 Gebuehr",
        ),
        txn(
            "2026-04-02",
            -35,
            "Stadtwerke",
            remittanceInformationUnstructured="Vertrag 77001 Zaehler",
        ),
    ]
    (s,) = detect_series(rows, today=TODAY)
    assert s["occurrences"] == 5


def test_series_uses_the_transaction_date_when_no_booking_date_exists():
    rows = monthly([-13.99, -13.99, -17.99], name="Streamly")
    for r in rows:
        r["transactionDate"], r["bookingDate"] = r["bookingDate"], ""
    (s,) = detect_series(rows, today=TODAY)
    assert s["interval"] == "monthly"
    assert s["price_change"]["increase"]


def test_candidates_get_no_reserve():
    from custom_components.finance_dashboard.contracts import build_reserves

    base = {
        "interval": "yearly",
        "status": "active",
        "annual_cost": 120.0,
        "owner": "",
        "next_expected": "2026-09-01",
        "category": "insurance",
        "plan_amount": -120.0,
    }
    sure = {**base, "id": "a", "creditor": "a", "candidate": False}
    unsure = {**base, "id": "b", "creditor": "b", "candidate": True}
    items = build_reserves([sure, unsure])["items"]
    assert [i["series_id"] for i in items] == ["a"]


def test_a_contract_the_user_edited_is_never_a_candidate():
    rows = monthly([-12.4, -13.1, -11.8], name="Cafe Bohne", category="food")
    for r in rows:
        r["remittanceInformationUnstructured"] = "VISA Debitkarte"
    store = blank_store()
    (first,) = build_contracts(rows, store, today=TODAY)
    assert first["candidate"] is True
    store.contracts[first["id"]] = Contract(first["id"], notice_value=1)
    (again,) = build_contracts(rows, store, today=TODAY)
    assert again["candidate"] is False


def _cafe_rows():
    rows = monthly([-12.4, -13.1, -11.8], name="Cafe Bohne", category="food")
    for r in rows:
        r["remittanceInformationUnstructured"] = "VISA Debitkarte"
    return rows


def test_not_a_contract_answer_hides_the_series_for_good():
    store = blank_store()
    (first,) = build_contracts(_cafe_rows(), store, today=TODAY)
    store.contracts[first["id"]] = Contract(first["id"], review="not_contract")
    assert build_contracts(_cafe_rows() + _cafe_rows()[:0], store, today=TODAY) == []


def test_confirmed_candidate_counts_as_a_contract():
    store = blank_store()
    (first,) = build_contracts(_cafe_rows(), store, today=TODAY)
    assert first["candidate"] is True
    store.contracts[first["id"]] = Contract(first["id"], review="contract")
    (again,) = build_contracts(_cafe_rows(), store, today=TODAY)
    assert again["candidate"] is False
    assert again["contract"]["stored"]["review"] == "contract"


def test_unknown_review_answer_is_rejected():
    with pytest.raises(ContractError) as err:
        Contract("s_x").apply({"review": "maybe"})
    assert err.value.code == "invalid_review"


def _to_own(text, amounts=(-320.0,) * 4):
    rows = monthly(list(amounts), name="Erika Mustermann")
    for r in rows:
        r["remittanceInformationUnstructured"] = text
    return rows


def test_instalment_to_own_name_is_a_candidate_question():
    own = frozenset({"erika mustermann"})
    (c,) = build_contracts(_to_own("Rate Sparbank 99887766"), blank_store(), today=TODAY, own_names=own)
    assert c["candidate"] is True
    assert c["confidence"]["reasons"][0] == "own_name"


def test_savings_transfer_to_own_name_stays_hidden():
    own = frozenset({"erika mustermann"})
    assert build_contracts(_to_own("Sparen"), blank_store(), today=TODAY, own_names=own) == []
    varying = _to_own("Rate", amounts=(-100.0, -250.0, -80.0, -300.0))
    assert build_contracts(varying, blank_store(), today=TODAY, own_names=own) == []
    # a contract word next to a savings word is still savings (QA #109)
    for text in ("Sparplan Rate", "Rücklage Strom", "Sparen Kredit", "Umbuchung Miete Rücklage"):
        assert build_contracts(_to_own(text), blank_store(), today=TODAY, own_names=own) == [], text


def test_sparkasse_loan_to_own_name_is_still_a_candidate():
    own = frozenset({"erika mustermann"})
    (c,) = build_contracts(_to_own("Kredit Sparkasse"), blank_store(), today=TODAY, own_names=own)
    assert c["candidate"] is True


def test_confirmed_own_name_contract_counts():
    own = frozenset({"erika mustermann"})
    store = blank_store()
    (c,) = build_contracts(_to_own("Darlehen Rate"), store, today=TODAY, own_names=own)
    store.contracts[c["id"]] = Contract(c["id"], review="contract")
    (again,) = build_contracts(_to_own("Darlehen Rate"), store, today=TODAY, own_names=own)
    assert again["candidate"] is False
