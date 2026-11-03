"""One rule for every number (#166-#177): transfers, PayPal, periods, categories. Invented figures."""

from __future__ import annotations

import ast
import asyncio
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.finance_dashboard import cycle as cycle_mod
from custom_components.finance_dashboard.budget_plan import BudgetPlan, CostPosition
from custom_components.finance_dashboard.categorizer import TransactionCategorizer
from custom_components.finance_dashboard.counted import (
    MOVEMENT_CHAIN,
    MOVEMENT_OWN,
    MOVEMENT_PAY_LATER,
    MOVEMENT_PAYPAL,
    MOVEMENT_TOPUP,
    counted_transactions,
    movement_reasons,
    net_counted,
)
from custom_components.finance_dashboard.cycle import salary_starts
from custom_components.finance_dashboard.data_store import Ledger, fingerprint, is_pending_match
from custom_components.finance_dashboard.home import build_home
from custom_components.finance_dashboard.household_summary import (
    build_household_summary,
    cycle_windows,
    month_of_window,
)
from custom_components.finance_dashboard.labels import (
    apply_contract_categories,
    contract_categories,
    resolve_bookings,
)
from custom_components.finance_dashboard.manager import FinanceDashboardManager
from custom_components.finance_dashboard.merchants import MerchantMemory, merchant_key
from custom_components.finance_dashboard.own_accounts import OwnAccounts
from custom_components.finance_dashboard.plan_match import assign_positions, best_position
from custom_components.finance_dashboard.transfer_detector import (
    detect_transfer_chains,
    enrich_transactions,
    transfer_questions,
)
from custom_components.finance_dashboard.tx_dates import effective_date_str

NOW = datetime(2026, 4, 15, 12, 0)
ACCOUNTS = [
    {"id": "a1", "type": "personal", "person": "Anna", "name": "Anna Muster", "institution": "Bank A",
     "iban": "DE00111"},
    {"id": "a2", "type": "personal", "person": "Max", "name": "Max Beispiel", "institution": "Bank B",
     "iban": "DE00222"},
    {"id": "s1", "type": "shared", "person": "", "name": "Anna Muster und Max Beispiel",
     "institution": "Bank A", "iban": "DE00333"},
    {"id": "pp", "type": "personal", "person": "Anna", "name": "Konto", "institution": "PayPal"},
]
_OWNERS = {"a1": ("personal", "Anna"), "a2": ("personal", "Max"), "s1": ("shared", ""),
           "pp": ("personal", "Anna")}
_seq = {"n": 0}


def tx(acc, amount, day, name="Shop", *, month=4, cat="other", year=2026, **extra):
    _seq["n"] += 1
    kind, person = _OWNERS[acc]
    side = "creditorName" if amount < 0 else "debtorName"
    row = {
        "transactionId": f"t{_seq['n']}",
        "_ledger_id": f"id:t{_seq['n']}",
        "_account_key": f"key-{acc}",
        "bookingDate": f"{year}-{month:02d}-{day:02d}",
        "transactionAmount": {"amount": str(amount), "currency": "EUR"},
        side: name,
        "remittanceInformationUnstructured": "",
        "category": cat,
        "_account_id": acc,
        "_account_name": kind,
        "_account_type": kind,
        "_account_person": person,
        "_status": "booked",
    }
    row.update(extra)
    return row


def pp_line(amount, day, name, *, month=4, cat="other", **extra):
    """A PayPal line: only a transaction date, often no transaction id."""
    row = tx("pp", amount, day, name, month=month, cat=cat, **extra)
    row["transactionDate"] = row.pop("bookingDate")
    return row


def chain(*legs, chain_id="c"):
    roles = ["source", *["intermediate"] * (len(legs) - 2), "destination"]
    for leg, role in zip(legs, roles, strict=True):
        leg.update(_transfer_chain_id=chain_id, _transfer_role=role, _transfer_confirmed=None)
    return list(legs)


SALARIES = [
    tx("a1", 3000, 1, "ACME GmbH", month=m, cat="income_work") for m in (2, 3, 4)
]


def _manager(transactions, *, accounts=ACCOUNTS, plan=None, persons=None, recurring=None):
    mgr = FinanceDashboardManager.__new__(FinanceDashboardManager)
    hass = MagicMock()
    hass.data = {}
    hass.states.get.return_value = None
    mgr._hass = hass
    mgr._entry = SimpleNamespace(data={"persons": persons or []}, options={})
    mgr._accounts = accounts
    mgr._transactions = transactions
    mgr._recurring_patterns = recurring or []
    mgr._plan_store = SimpleNamespace(plan=plan or BudgetPlan())
    mgr._pot_store = SimpleNamespace(pots=[])
    mgr._demo_mode = False
    mgr._last_refresh = None
    mgr._last_refresh_stats = {}
    mgr._refresh_in_flight = False
    mgr._rate_limited_until = None
    mgr._contract_categories = {}
    mgr._transfer_overrides = {}
    return mgr


@pytest.fixture
def frozen(monkeypatch):
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: NOW)


def _summary(mgr, **kw):
    return asyncio.run(mgr.async_get_monthly_summary(**kw))


def _totals_of_all_views(transactions, accounts=ACCOUNTS):
    mgr = _manager(transactions, accounts=accounts)
    summary = _summary(mgr)
    household = mgr.get_household_summary(is_admin=True)
    home = mgr.get_home(person=None, view="household", horizon="cycle")
    plan = mgr.get_plan_vs_actual()
    return summary, household, home, plan


# ---------------------------------------------------------------------------
# #166 own transfers
# ---------------------------------------------------------------------------


def test_two_leg_transfer_counts_nowhere(frozen):
    txs = [
        *SALARIES,
        *chain(tx("a1", -500, 3, "Max Beispiel"), tx("a2", 500, 3, "Anna Muster")),
        tx("a1", -40, 5, "REWE", cat="groceries"),
    ]
    summary, household, home, plan = _totals_of_all_views(txs)
    assert summary["total_expenses"] == 40
    assert household["expenses"] == 40
    assert home["totals"]["expenses"] == 40
    assert sum(c["actual"] for c in plan["categories"]) == 40
    assert summary["excluded_transfers"]["excluded_txn_count"] == 2


def test_pots_do_not_see_a_chain(frozen):
    from custom_components.finance_dashboard.pots import Pot

    txs = [*SALARIES, *chain(tx("a1", -500, 3, "x", cat="groceries"), tx("a2", 500, 3, "y"))]
    pot = Pot("g", "Food", "Anna", 300.0, ["groceries"])
    out = build_home(accounts=ACCOUNTS, transactions=txs, plan=None, pots=[pot], recurring=[],
                     banks=[], as_of=NOW, now=NOW, person="Anna", view="person", horizon="cycle")
    assert out["pots"][0]["spent"] == 0


def test_cascade_counts_the_merchant_debit_once(frozen):
    txs = [
        *SALARIES,
        *chain(
            tx("a2", -39.9, 5, "Anna Muster"),
            tx("a1", 39.9, 5, "Max Beispiel"),
            tx("a1", -39.9, 6, "PayPal"),
            pp_line(39.9, 6, "Anna Muster"),
        ),
        pp_line(-39.9, 6, "HelloFresh", cat="groceries"),
    ]
    summary, household, home, _ = _totals_of_all_views(txs)
    assert summary["total_expenses"] == household["expenses"] == home["totals"]["expenses"] == 39.9


def test_rejected_chain_counts_again(frozen):
    legs = chain(tx("a1", -70, 3, "x"), tx("a2", 70, 3, "y"))
    for leg in legs:
        leg["_transfer_confirmed"] = False
    assert len(counted_transactions(legs, ACCOUNTS)) == 2


def test_views_agree_on_the_total_of_a_mixed_period(frozen):
    txs = [
        *SALARIES,
        *chain(tx("a1", -500, 3, "s"), tx("a2", 500, 3, "t")),
        tx("a1", -200, 4, "Eigenes Sparkonto", cat="transfers"),
        tx("a1", -19.9, 5, "PayPal"),
        pp_line(-19.9, 5, "Spotify", cat="media"),
        tx("a1", -60, 6, "Stadtwerke", cat="housing_warm"),
        tx("a1", 15, 8, "Stadtwerke", cat="housing_warm"),
        tx("s1", -80, 9, "REWE", cat="groceries"),
    ]
    summary, household, home, plan = _totals_of_all_views(txs)
    assert summary["total_expenses"] == household["expenses"] == home["totals"]["expenses"] == 144.9
    assert summary["total_income"] == household["income"] == home["totals"]["income"] == 3000
    assert round(sum(c["actual"] for c in plan["categories"]), 2) == 144.9


# ---------------------------------------------------------------------------
# #167 PayPal
# ---------------------------------------------------------------------------


def test_paypal_purchase_counts_once_on_the_paypal_side():
    debit = tx("a1", -25, 10, "PayPal Europe S.a r.l.", remittanceInformationUnstructured="PP.1.PP")
    line = pp_line(-25, 11, "Shop GmbH", cat="groceries")
    counted = counted_transactions([debit, line], ACCOUNTS)
    assert counted == [line]
    assert movement_reasons([debit, line], ACCOUNTS)[id(debit)] == MOVEMENT_PAYPAL


def test_paypal_counts_once_in_every_view(frozen):
    txs = [
        *SALARIES,
        tx("a1", -25, 10, "PayPal Europe S.a r.l."),
        pp_line(-25, 11, "Shop GmbH", cat="groceries"),
    ]
    summary, household, home, plan = _totals_of_all_views(txs)
    assert summary["total_expenses"] == household["expenses"] == home["totals"]["expenses"] == 25
    assert [c["actual"] for c in plan["categories"] if c["actual"]] == [25]
    assert summary["categories"]["groceries"] == -25


def test_second_equal_purchase_is_not_swallowed():
    txs = [
        tx("a1", -25, 10, "PayPal Europe S.a r.l."),
        pp_line(-25, 10, "Shop A"),
        pp_line(-25, 11, "Shop B"),
    ]
    assert len(counted_transactions(txs, ACCOUNTS)) == 2


def test_debit_without_paypal_line_is_the_only_trace():
    debit = tx("a1", -25, 10, "PayPal Europe S.a r.l.")
    assert counted_transactions([debit], ACCOUNTS) == [debit]
    no_paypal = [a for a in ACCOUNTS if a["id"] != "pp"]
    assert counted_transactions([debit], no_paypal) == [debit]


def test_top_up_moves_money_on_both_sides():
    debit = tx("a1", -100, 10, "PayPal Europe S.a r.l.")
    credit = pp_line(100, 10, "Bank Einzug")
    assert counted_transactions([debit, credit], ACCOUNTS) == []
    assert movement_reasons([debit, credit], ACCOUNTS)[id(credit)] == MOVEMENT_TOPUP


def test_pay_later_instalment_repays_what_paypal_already_counted():
    instalment = tx("a1", -33, 10, "PayPal Europe S.a r.l.",
                    remittanceInformationUnstructured="PayPal Pay Later Rate 2/3")
    assert counted_transactions([instalment], ACCOUNTS) == []
    assert movement_reasons([instalment], ACCOUNTS)[id(instalment)] == MOVEMENT_PAY_LATER
    # Without PayPal linked it is the only trace of the purchase.
    assert counted_transactions([instalment], ACCOUNTS[:3]) == [instalment]


def test_list_marks_the_bank_debit_and_adds_up_once():
    from custom_components.finance_dashboard.api.data import _list_totals

    txs = [tx("a1", -25, 10, "PayPal Europe S.a r.l."), pp_line(-25, 11, "Shop GmbH", cat="groceries")]
    assert _list_totals(txs, movement_reasons(txs, ACCOUNTS)) == {"income": 0.0, "expenses": 25.0}


# ---------------------------------------------------------------------------
# #168 dates
# ---------------------------------------------------------------------------


def test_list_date_of_a_paypal_row():
    assert effective_date_str(pp_line(-5, 7, "Shop")) == "2026-04-07"


def test_no_direct_booking_date_read_outside_tx_dates():
    """AST lint: ``x.get("bookingDate")`` / ``x["bookingDate"]`` only in ``tx_dates.py``."""
    root = Path(__file__).parent.parent / "custom_components" / "finance_dashboard"
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "tx_dates.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            is_get = (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "bookingDate"
            )
            is_item = (
                isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and node.slice.value == "bookingDate"
                and isinstance(node.ctx, ast.Load)
            )
            if is_get or is_item:
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def test_dateless_pending_row_matches_only_inside_the_window():
    pending = {"transactionAmount": {"amount": "-9", "currency": "EUR"}, "creditorName": "Shop"}
    old = {**pending, "bookingDate": "2026-01-02"}
    fresh = {**pending, "bookingDate": "2026-04-14"}
    assert not is_pending_match(pending, old, today=date(2026, 4, 15))
    assert is_pending_match(pending, fresh, today=date(2026, 4, 15))
    assert not is_pending_match(pending, fresh)  # no date at all proves nothing


def _pp_raw(day, amount=-9.99):
    return {
        "transactionDate": day,
        "transactionAmount": {"amount": str(amount), "currency": "EUR"},
        "creditorName": "Streaming Co",
        "remittanceInformationUnstructured": "Abo",
    }


def test_two_equal_monthly_paypal_payments_stay_two_rows():
    led = Ledger(None)
    led.ingest("k", [_pp_raw("2026-03-05")], [], date_from="2026-03-01")
    led.ingest("k", [_pp_raw("2026-04-05")], [], date_from="2026-04-01")
    rows = led.transactions("k")
    assert sorted(effective_date_str(r) for r in rows) == ["2026-03-05", "2026-04-05"]


def test_paypal_row_outside_the_fetched_window_survives_and_refetch_is_idempotent():
    led = Ledger(None)
    led.ingest("k", [_pp_raw("2026-03-05"), _pp_raw("2026-04-05")], [], date_from="2026-03-01")
    led.ingest("k", [_pp_raw("2026-04-05")], [], date_from="2026-04-01")
    assert len(led.transactions("k")) == 2


def test_fingerprint_of_a_row_with_booking_date_is_unchanged():
    row = {"bookingDate": "2026-04-05", "transactionDate": "2026-04-04",
           "transactionAmount": {"amount": "-1", "currency": "EUR"}, "creditorName": "x"}
    assert fingerprint(row) == fingerprint({k: v for k, v in row.items() if k != "transactionDate"})


def test_old_ledger_ids_migrate_and_one_off_answers_follow():
    led = Ledger(None)
    old_id = f"fp:{fingerprint({**_pp_raw(''), 'transactionDate': ''})}"
    row = {**_pp_raw("2026-03-05"), "_ledger_id": old_id, "_status": "booked"}
    led.data["accounts"]["k"] = {"transactions": [row], "balances": []}
    renames = led.migrate_fingerprint_ids()
    new_id = renames["k"][old_id]
    assert new_id == f"fp:{fingerprint(row)}" and led.transactions("k")[0]["_ledger_id"] == new_id
    assert led.migrate_fingerprint_ids() == {}  # idempotent

    memory = MerchantMemory(store=MagicMock())
    memory.learn_booking(old_id, "media")
    assert memory.rename_bookings({old_id: new_id})
    assert memory.booking_rule({"_ledger_id": new_id}) == {"category": "media"}


def test_a_refetch_after_migration_finds_the_same_row():
    led = Ledger(None)
    old_id = f"fp:{fingerprint({**_pp_raw(''), 'transactionDate': ''})}"
    led.data["accounts"]["k"] = {
        "transactions": [{**_pp_raw("2026-03-05"), "_ledger_id": old_id, "_status": "booked"}],
        "balances": [],
    }
    led.migrate_fingerprint_ids()
    led.ingest("k", [_pp_raw("2026-03-05")], [], date_from="2026-03-01")
    assert len(led.transactions("k")) == 1


# ---------------------------------------------------------------------------
# #169 period
# ---------------------------------------------------------------------------


def _month_end_salaries():
    return [tx("a1", 3000, 28, "ACME GmbH", month=m, cat="income_work") for m in (1, 2, 3)]


def test_summary_uses_the_cycle_not_the_calendar_month(monkeypatch):
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 4, 2, 12, 0))
    txs = [*_month_end_salaries(), tx("a1", -50, 30, "REWE", month=3, cat="groceries")]
    summary = _summary(_manager(txs))
    # Salary on 28 March: a few days into April the income is not zero.
    assert summary["total_income"] == 3000 and summary["total_expenses"] == 50
    assert summary["period"]["start"] == "2026-03-28"
    assert (summary["month"], summary["year"]) == (4, 2026)


def test_summary_plan_and_household_report_the_same_window(monkeypatch):
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 4, 2, 12, 0))
    mgr = _manager(_month_end_salaries())
    summary = _summary(mgr)
    plan = mgr.get_plan_vs_actual()
    household = mgr.get_household_summary(is_admin=True)
    home = mgr.get_home(person=None, view="household", horizon="cycle")
    assert summary["period"]["start"] == plan["period"]["start"] == household["cycle"]["start"]
    assert summary["period"]["end"] == plan["period"]["end"] == household["cycle"]["end"]
    assert home["cycle"]["start"] == household["cycle"]["start"]
    assert (summary["month"], summary["year"]) == (plan["month"], plan["year"])


def test_month_selection_means_the_cycle_holding_its_15th(frozen):
    mgr = _manager(_month_end_salaries())
    summary = _summary(mgr, month=2, year=2026)
    assert summary["period"]["start"] == "2026-01-28" and summary["period"]["end"] == "2026-02-27"
    assert (summary["month"], summary["year"]) == (2, 2026)
    assert mgr.get_plan_vs_actual(2, 2026)["period"] == summary["period"]


def test_month_before_any_salary_is_the_calendar_month(frozen):
    summary = _summary(_manager(_month_end_salaries()), month=11, year=2025)
    assert summary["period"]["start"] == "2025-11-01"
    assert summary["period"]["rule"] == "calendar_fallback"


def test_period_uses_the_home_assistant_clock_not_the_os_clock(monkeypatch):
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2031, 7, 15, 0, 5))
    assert _summary(_manager([]))["period"]["start"] == "2031-07-01"


def test_confirmed_payday_is_the_window_without_a_salary(frozen):
    persons = [{"name": "Anna", "payday": {"day": 25, "confirmed": True}}]
    mgr = _manager([], persons=persons)
    assert _summary(mgr)["period"]["start"] == "2026-03-25"
    assert mgr.get_home(person=None, view="household", horizon="cycle")["cycle"]["start"] == "2026-03-25"


def test_month_of_window():
    assert month_of_window((date(2026, 3, 29), date(2026, 4, 27))) == (4, 2026)
    assert month_of_window((date(2026, 4, 1), date(2026, 4, 30))) == (4, 2026)
    assert month_of_window((date(2026, 12, 20), date(2027, 1, 19))) == (1, 2027)


# ---------------------------------------------------------------------------
# #170 transfers category and refunds
# ---------------------------------------------------------------------------


def test_transfers_never_reach_income_expense_or_plan_rows(frozen):
    txs = [
        *SALARIES,
        tx("a1", -300, 5, "Depot", cat="transfers"),
        tx("a1", 200, 6, "Sparkonto", cat="transfers"),
    ]
    summary, household, _home, plan = _totals_of_all_views(txs)
    assert summary["total_expenses"] == 0 and summary["total_income"] == 3000
    assert "transfers" not in summary["categories"]
    assert household["income"] == 3000
    assert "transfers" not in {c["category"] for c in plan["categories"]}


def test_detector_refund_reduces_the_expense_category_everywhere(frozen):
    original = tx("a1", -100, 4, "Modehaus", cat="leisure", _refund_pair_id="r", _refund_role="original")
    refund = tx("a1", 40, 6, "Modehaus", cat="income_refund", _refund_pair_id="r", _refund_role="refund")
    refund["transactionAmount"]["amount"] = "100"
    summary, household, home, plan = _totals_of_all_views([*SALARIES, original, refund])
    assert summary["total_expenses"] == household["expenses"] == home["totals"]["expenses"] == 0
    assert summary["total_income"] == household["income"] == 3000


def test_partial_settlement_credit_lowers_the_cost_and_is_no_income(frozen):
    txs = [
        *SALARIES,
        tx("a1", -100, 4, "Stadtwerke", cat="housing_warm"),
        tx("a1", 30, 8, "Stadtwerke", cat="income_refund"),
    ]
    summary, household, home, plan = _totals_of_all_views(txs)
    assert summary["total_income"] == household["income"] == 3000
    assert summary["total_expenses"] == household["expenses"] == home["totals"]["expenses"] == 70
    assert summary["categories"]["housing_warm"] == -70
    assert [c["actual"] for c in plan["categories"] if c["category"] == "housing_warm"] == [70]


def test_refund_without_any_expense_stays_income():
    credit = tx("a1", 30, 8, "Fremde Firma", cat="income_refund")
    assert net_counted([credit]) == [credit]


def test_category_and_position_agree_for_the_same_booking(frozen):
    plan = BudgetPlan(
        persons=["Anna"],
        positions=[CostPosition(id="n", name="Netflix Abo", owner="Anna", amount=15.0,
                                category="media")],
    )
    txs = [
        *SALARIES,
        tx("a1", -15, 3, "NETFLIX", cat="media"),
        tx("a1", 5, 9, "NETFLIX", cat="media"),
    ]
    out = _manager(txs, plan=plan).get_plan_vs_actual()
    assert out["positions"][0]["actual"] == 10
    assert [c["actual"] for c in out["categories"] if c["category"] == "media"] == [10]


def test_fixed_costs_share_one_definition(frozen):
    recurring = [{"creditor": "stadtwerke", "average_amount": -60.0, "expected_day": 6}]
    txs = [
        *SALARIES,
        tx("a1", -60, 6, "Stadtwerke", cat="housing_warm"),
        tx("a1", -80, 7, "Apotheke", cat="health"),  # was fixed by its category alone
    ]
    mgr = _manager(txs, recurring=recurring)
    summary = _summary(mgr)
    household = mgr.get_household_summary(is_admin=True)
    assert summary["fixed_costs"] == household["fixed"] == 60
    assert summary["variable_costs"] == household["variable"] == 80


# ---------------------------------------------------------------------------
# #171 own accounts
# ---------------------------------------------------------------------------


def _categorizer(memory=None, accounts=ACCOUNTS):
    cat = TransactionCategorizer(memory=memory)
    cat.set_own_accounts(OwnAccounts.of(accounts))
    return cat


def test_debit_to_own_name_or_iban_is_a_transfer():
    cat = _categorizer()
    assert cat.categorize(tx("a1", -500, 3, "Anna Maria Muster")) == "transfers"
    assert cat.categorize(tx("a1", -500, 3, "Muster, Anna")) == "transfers"
    assert cat.categorize(tx("a1", -500, 3, "Max Beispiel")) == "transfers"
    assert cat.categorize(tx("a1", -500, 3, "Unbekannt", creditorAccount={"iban": "DE 00222"})) == "transfers"


def test_a_business_with_a_holder_word_is_no_transfer():
    assert _categorizer().categorize(tx("a1", -5, 3, "Muster Gartenbau GmbH")) == "other"


def test_only_the_counterparty_side_decides():
    # The bank fills the debtor of a debit with the holder: that is no own transfer.
    assert _categorizer().categorize(tx("a1", -5, 3, "", debtorName="Anna Muster")) != "transfers"


def test_a_bank_named_like_the_account_is_no_own_name():
    own = OwnAccounts.of([{"name": "Deutsche Bank", "institution": "Deutsche Bank"}])
    assert not own.matches(tx("a1", -5, 3, "Deutsche Bank"))


def test_paypal_named_account_does_not_swallow_purchases():
    own = OwnAccounts.of([{"name": "PayPal Europe", "institution": "PayPal"}])
    assert not own.matches(tx("a1", -5, 3, "PayPal Europe"))


def test_credit_from_own_savings_is_neither_income_nor_salary_candidate(frozen):
    cat = _categorizer()
    credit = tx("a1", 9000, 10, "Anna Muster")
    credit["category"] = cat.categorize(credit)
    assert credit["category"] == "transfers"
    txs = [*SALARIES, credit]
    summary, household, _home, _plan = _totals_of_all_views(txs)
    assert summary["total_income"] == household["income"] == 3000
    assert household["cycle"]["start"] == "2026-04-01"


def test_marking_a_counterparty_applies_retroactively():
    memory = MerchantMemory(store=MagicMock())
    old = tx("a1", -200, 3, "Depot Verwahrung X", month=1)
    cat = _categorizer(memory)
    assert cat.categorize(old) != "transfers"
    memory.learn_merchant(merchant_key(old), "transfers")
    assert cat.categorize(old) == "transfers"
    assert cat.categorize(tx("a1", -210, 3, "Depot Verwahrung X", month=4)) == "transfers"


# ---------------------------------------------------------------------------
# #172 categoriser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("Franz Huber", ""),
        ("Gruber GmbH", ""),
        ("Hausverwaltung Nord", "Bahnhofstrasse 4"),
        ("Autohaus West", "Bahnhofstraße 12"),
        ("Bank A", "Depotgebühr 2026"),
    ],
)
def test_not_mobility_or_groceries(name, text):
    row = tx("a1", -12, 3, name, remittanceInformationUnstructured=text)
    assert TransactionCategorizer().categorize(row) not in ("mobility", "groceries")


def test_real_keywords_still_hit():
    cat = TransactionCategorizer()
    assert cat.categorize(tx("a1", -12, 3, "UBER BV")) == "mobility"
    assert cat.categorize(tx("a1", -12, 3, "Deutsche Bahn")) == "mobility"
    assert cat.categorize(tx("a1", -12, 3, "SHELL 1234")) == "mobility"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Bargeldauszahlung Geldautomat", "cash"),
        ("GA-Auszahlung Sparkasse", "cash"),
        ("Bargeld REWE Kasse", "cash"),
        ("Kontoführungsentgelt 03/26", "bank_fees"),
        ("Depotgebühr 2026", "bank_fees"),
        ("Wero an Freundin", "p2p"),
        ("PayPal Pay Later Rate 2/3", "finance"),
    ],
)
def test_payment_buckets(text, expected):
    row = tx("a1", -12, 3, "Irgendwer", remittanceInformationUnstructured=text)
    assert TransactionCategorizer().categorize(row) == expected


def test_cash_debit_with_a_shop_name_is_cash_but_a_card_payment_is_not():
    assert TransactionCategorizer().categorize(tx("a1", -12, 3, "REWE Markt")) == "groceries"


def test_finance_terms_win_over_groceries_words():
    row = tx("a1", -50, 3, "Trade Republic", remittanceInformationUnstructured="Sparplan REWE Aktie")
    assert TransactionCategorizer().categorize(row) == "finance"


def test_standing_order_with_a_real_purpose_keeps_the_purpose():
    row = tx("a1", -700, 3, "Vermieter", remittanceInformationUnstructured="Dauerauftrag Kaltmiete")
    assert TransactionCategorizer().categorize(row) == "housing_cold"


def test_energy_suppliers():
    assert TransactionCategorizer().categorize(tx("a1", -70, 3, "LichtBlick SE")) == "housing_warm"


def test_holder_surname_in_debtor_never_decides():
    # "Bahn" as a surname of the holder; the debit's counterparty says nothing.
    row = tx("a1", -9, 3, "Kiosk", debtorName="Rewe Bahn")
    assert TransactionCategorizer().categorize(row) == "other"


# ---------------------------------------------------------------------------
# #173 stable chains, #174 evidence
# ---------------------------------------------------------------------------


def _pair():
    out = tx("a1", -250, 3, "Max Beispiel")
    into = tx("a2", 250, 3, "Anna Muster")
    return out, into


def test_chain_id_is_stable_for_the_same_bookings():
    a = [dict(t) for t in _pair()]
    b = [dict(t) for t in reversed(a)]
    id_a = detect_transfer_chains(a, ACCOUNTS)[0][0].chain_id
    id_b = detect_transfer_chains(b, ACCOUNTS)[0][0].chain_id
    assert id_a == id_b and id_a.startswith("chain:")


def _ledger_manager(rows_by_account, overrides=None):
    mgr = _manager([])
    mgr._ledger = Ledger(None)
    mgr._ledger.data["accounts"] = {
        f"key-{acc}": {"transactions": [dict(r) for r in rows], "balances": []}
        for acc, rows in rows_by_account.items()
    }
    mgr._categorizer = None
    mgr._transfer_overrides = overrides or {}
    for acc in mgr._accounts:
        acc.setdefault("_keep", True)
    return mgr


def test_rejection_survives_refresh_reprocess_and_restart(monkeypatch):
    import custom_components.finance_dashboard.account_identity as identity

    monkeypatch.setattr(identity, "account_key", lambda a: f"key-{a.get('id')}")
    out, into = _pair()
    mgr = _ledger_manager({"a1": [out], "a2": [into]})
    first = mgr._derive_from_ledger({})
    chain_id = next(t["_transfer_chain_id"] for t in first if t.get("_transfer_chain_id"))

    overrides = {chain_id: False}
    # Refresh and reprocess re-derive; a restart is a new manager over the same ledger.
    for manager in (mgr, _ledger_manager({"a1": [out], "a2": [into]})):
        rows = manager._derive_from_ledger(overrides)
        legs = [t for t in rows if t.get("_transfer_chain_id")]
        assert {t["_transfer_chain_id"] for t in legs} == {chain_id}
        assert all(t["_transfer_confirmed"] is False for t in legs)
        assert len(counted_transactions(rows, ACCOUNTS)) == 2


def test_stale_random_override_ids_are_dropped_and_stable_ones_kept():
    store = MagicMock()
    saved = {}

    async def load():
        return {"3f2a-uuid": False, "chain:abc": False}

    async def save(data):
        saved.update(data)

    store.async_load, store.async_save = load, save
    mgr = _manager([])
    mgr._transfer_override_store = store
    assert asyncio.run(mgr._async_load_transfer_overrides()) == {"chain:abc": False}
    assert saved == {"chain:abc": False}


def _unrelated():
    return tx("a1", -49.99, 3, "Elektromarkt"), tx("a2", 49.99, 3, "Oma Erna")


def test_amount_and_date_alone_never_link():
    txs = list(_unrelated())
    chains, _ = detect_transfer_chains(txs, ACCOUNTS)
    assert chains == []


def test_such_a_pair_becomes_a_question():
    txs = list(_unrelated())
    questions = transfer_questions(txs, ACCOUNTS)
    assert len(questions) == 1
    assert questions[0]["out"] is txs[0] and questions[0]["in"] is txs[1]


def test_answer_yes_links_answer_no_stays_two_bookings():
    txs = list(_unrelated())
    qid = transfer_questions(txs, ACCOUNTS)[0]["id"]
    chains, _ = detect_transfer_chains(txs, ACCOUNTS, overrides={qid: True})
    assert [c.chain_id for c in chains] == [qid]
    assert transfer_questions(txs, ACCOUNTS, {qid: True}) == []
    assert detect_transfer_chains(txs, ACCOUNTS, overrides={qid: False})[0] == []
    assert transfer_questions(txs, ACCOUNTS, {qid: False}) == []


def test_answering_a_transfer_question_links_and_keeps_it(monkeypatch):
    import custom_components.finance_dashboard.account_identity as identity

    monkeypatch.setattr(identity, "account_key", lambda a: f"key-{a.get('id')}")
    out, into = _unrelated()
    mgr = _ledger_manager({"a1": [out], "a2": [into]})
    mgr._memory = MerchantMemory(store=MagicMock())

    async def noop(*_a, **_k):
        return None

    mgr._memory.async_save = noop
    mgr._transfer_override_store = SimpleNamespace(async_save=noop)
    mgr._derive_from_ledger({})
    card = mgr.get_transfer_questions()[0]
    assert card["kind"] == "transfer" and card["id"].startswith("transfer:chain:")
    asyncio.run(mgr.async_answer_question(
        question_id=card["id"], category="", reach="", choice="confirm"))
    assert mgr.get_transfer_questions() == []
    assert counted_transactions(mgr._transactions, ACCOUNTS) == []


@pytest.mark.parametrize(
    "evidence",
    [
        {"creditorAccount": {"iban": "DE00222"}},
        {"remittanceInformationUnstructured": "Bank B Umbuchung"},
    ],
)
def test_iban_or_name_evidence_links(evidence):
    out = tx("a1", -49.99, 3, "Unbekannt", **evidence)
    out["_account_name"], into = "Bank A", tx("a2", 49.99, 3, "Unbekannt")
    into["_account_name"] = "Bank B"
    assert len(detect_transfer_chains([out, into], ACCOUNTS)[0]) == 1


def test_paypal_rows_without_ids_pair_up_individually():
    """No transaction id on PayPal lines: their ledger ids keep them apart."""
    a = pp_line(30, 5, "Anna Muster", transactionId="")
    b = pp_line(40, 5, "Anna Muster", transactionId="")
    debit_a, debit_b = tx("a1", -30, 5, "PayPal"), tx("a1", -40, 5, "PayPal")
    txs = [a, b, debit_a, debit_b]
    chains, refunds = detect_transfer_chains(txs, ACCOUNTS)
    enrich_transactions(txs, chains, refunds)
    assert len(chains) == 2 and all(t["_transfer_chain_id"] for t in txs)


def test_salary_and_equal_purchase_do_not_cancel(frozen):
    """The audited harm: a purchase hid the salary and moved the cycle."""
    salary = tx("a2", 3000, 1, "ACME GmbH", cat="income_work")
    purchase = tx("a1", -3000, 1, "Autohaus", cat="mobility")
    assert detect_transfer_chains([salary, purchase], ACCOUNTS)[0] == []


# ---------------------------------------------------------------------------
# #175 owners
# ---------------------------------------------------------------------------


def test_owner_correction_changes_household_and_home_totals(frozen):
    txs = [
        *SALARIES,
        tx("s1", -30, 3, "Kiosk", cat="groceries"),
        tx("a1", -20, 4, "Sportverein", cat="leisure", _owner_override="Max"),
        tx("a2", -10, 5, "Bäcker", cat="groceries", _owner_override="shared"),
    ]
    mgr = _manager(txs)
    owners = {o["owner"]: o for o in mgr.get_household_summary(is_admin=True)["owners"]}
    assert owners["Max"]["expenses"] == 20
    assert "Anna" not in owners or owners["Anna"]["expenses"] == 0
    assert owners["__shared__"]["expenses"] == 40
    assert owners["__shared__"]["kind"] == "shared"

    home = build_home(accounts=ACCOUNTS, transactions=txs, plan=None, pots=[], recurring=[],
                      banks=[], as_of=NOW, now=NOW, person="Max", view="person", horizon="cycle")
    assert home["totals"]["expenses"] == 20


def test_plan_position_overrides_account_in_home_too():
    plan = BudgetPlan(
        persons=["Anna", "Max"],
        positions=[CostPosition(id="n", name="Netflix", owner="Max", amount=15.0)],
    )
    txs = [*SALARIES, tx("a1", -15, 3, "NETFLIX")]
    home = build_home(accounts=ACCOUNTS, transactions=txs, plan=plan, pots=[], recurring=[],
                      banks=[], as_of=NOW, now=NOW, person="Max", view="person", horizon="cycle")
    assert home["totals"]["expenses"] == 15


def test_correction_beats_plan_position(frozen):
    plan = BudgetPlan(
        persons=["Anna", "Max"],
        positions=[CostPosition(id="n", name="Netflix", owner="Max", amount=15.0)],
    )
    txs = [*SALARIES, tx("a1", -15, 3, "NETFLIX", _owner_override="Anna")]
    owners = {o["owner"]: o for o in _manager(txs, plan=plan).get_household_summary(is_admin=True)["owners"]}
    assert owners["Anna"]["expenses"] == 15


def test_a_booking_matches_at_most_one_position():
    plan = [
        CostPosition(id="a", name="Telekom", owner="Anna", amount=1.0),
        CostPosition(id="b", name="Telekom Festnetz", owner="Max", amount=1.0),
    ]
    row = tx("a1", -40, 3, "Telekom", remittanceInformationUnstructured="Festnetz April")
    assert best_position(row, plan).id == "b"
    assigned = assign_positions([row], plan)
    assert set(assigned) == {"b"} and len(assigned["b"]) == 1


def test_position_named_after_a_person_does_not_claim_their_debits():
    position = CostPosition(id="a", name="Handy Anna", owner="Anna", amount=20.0)
    row = tx("a2", -80, 3, "Anna Muster", remittanceInformationUnstructured="Danke Anna")
    assert best_position(row, [position], ["Anna", "Max"]) is None
    assert best_position(tx("a2", -20, 3, "Vodafone Handy"), [position], ["Anna", "Max"]) is position


def test_generic_word_in_a_position_claims_nothing():
    position = CostPosition(id="a", name="Sonstige Kosten", owner="Anna", amount=20.0)
    assert best_position(tx("a2", -20, 3, "Kosten GmbH"), [position]) is None


# ---------------------------------------------------------------------------
# #176 salary cycles
# ---------------------------------------------------------------------------


def _regular(amount=3000, payer="ACME"):
    return [(date(2026, m, 1), amount, payer) for m in range(1, 7)]


def test_one_large_credit_does_not_move_the_cycle_starts():
    regular = _regular()
    expected = salary_starts(regular)
    assert expected == [date(2026, m, 1) for m in range(1, 7)]
    assert salary_starts([*regular, (date(2026, 3, 14), 25000, "Autokäufer")]) == expected
    # the same without payers: the amount alone says one-off
    bare = [r[:2] for r in regular]
    assert salary_starts([*bare, (date(2026, 3, 14), 25000)]) == expected


def test_one_old_outlier_from_an_import_breaks_nothing():
    regular = _regular()
    assert salary_starts([(date(2019, 2, 3), 90000, "Notar"), *regular]) == salary_starts(regular)


def test_one_off_of_salary_size_from_another_payer_opens_no_cycle():
    assert salary_starts([*_regular(), (date(2026, 3, 14), 3000, "Kautionsrückzahlung")]) == salary_starts(_regular())


def test_christmas_bonus_with_the_salary_still_opens_the_cycle():
    rows = [r if r[0].month != 5 else (r[0], 4500, "ACME") for r in _regular()]
    assert date(2026, 5, 1) in salary_starts(rows)


def test_bonus_paid_mid_cycle_opens_no_cycle():
    assert date(2026, 3, 14) not in salary_starts([*_regular(), (date(2026, 3, 14), 4500, "ACME")])


def test_a_raise_keeps_old_and_new_paydays():
    rows = [(date(2026, m, 1), 3000 if m < 7 else 4200, "ACME") for m in range(1, 13)]
    assert salary_starts(rows) == [date(2026, m, 1) for m in range(1, 13)]


def test_small_recurring_credits_are_no_salary():
    rows = [*_regular(), *[(date(2026, m, 10), 250, "Familienkasse") for m in range(1, 7)]]
    assert salary_starts(rows) == salary_starts(_regular())


def test_a_second_job_of_similar_size_still_counts():
    rows = [*_regular(), *[(date(2026, m, 15), 2900, "Beta AG") for m in range(1, 7)]]
    assert date(2026, 3, 15) in salary_starts(rows)


def test_single_credit_is_still_the_best_guess():
    assert salary_starts([(date(2026, 4, 1), 3000, "ACME")]) == [date(2026, 4, 1)]


def test_household_anchor_is_not_stolen_by_a_one_off():
    from custom_components.finance_dashboard.cycle import household_starts

    incomes = {
        "Anna": _regular(3000, "ACME"),
        "Max": [*_regular(2500, "Beta"), (date(2026, 3, 20), 40000, "Erbe")],
    }
    assert {who for _d, who in household_starts(incomes)} == {"Anna"}


def test_own_credit_and_refund_are_no_candidates(frozen):
    txs = [
        *SALARIES,
        tx("a1", 9000, 10, "Sparkonto", cat="transfers"),
        tx("a1", 8000, 12, "Versicherer", cat="income_refund"),
        tx("a1", 7000, 13, "Shop", cat="groceries"),
    ]
    windows, _rule, _anchor = cycle_windows(counted_transactions(txs, ACCOUNTS), date(2026, 4, 15))
    assert windows[0][0] == date(2026, 4, 1)


def test_month_cycle_module_is_gone():
    assert not hasattr(cycle_mod, "month_cycle")
    root = Path(__file__).parent.parent / "custom_components" / "finance_dashboard"
    assert not (root / "month_cycle.py").exists()


# ---------------------------------------------------------------------------
# #177 one category
# ---------------------------------------------------------------------------


def _contract_booking():
    return tx("a1", -12, 3, "Fitnessgerät Abo", cat="other")


def test_contract_category_is_what_the_booking_counts_under(frozen):
    row = _contract_booking()
    txs = [*SALARIES, row]
    key = f"{row['_account_key']}|{row['_ledger_id']}"
    contracts = [{"id": "c1", "category": "media", "ledger_ids": [key], "display_name": "Abo"}]
    mgr = _manager(txs)
    mgr.remember_contract_categories(contracts)

    listed = resolve_bookings([row], contracts, {})[key]
    assert listed["category"] == "media" and listed["category_source"] == "contract"
    assert row["category"] == listed["category"]
    assert _summary(mgr)["categories"]["media"] == -12
    assert "other" not in _summary(mgr)["categories"]
    assert [c["actual"] for c in mgr.get_plan_vs_actual()["categories"] if c["category"] == "media"] == [12]
    owners = mgr.get_household_summary(is_admin=True)["owners"]
    anna = next(o for o in owners if o["owner"] == "Anna")
    assert {c["category"]: c["amount"] for c in anna["categories"]} == {"media": 12}


def test_booking_gets_its_own_category_back_when_it_leaves_the_contract():
    row = tx("a1", -12, 3, "Abo", cat="leisure")
    key = f"{row['_account_key']}|{row['_ledger_id']}"
    apply_contract_categories([row], {key: "media"})
    assert row["category"] == "media" and row["_own_category"] == "leisure"
    apply_contract_categories([row], {})
    assert row["category"] == "leisure" and "_own_category" not in row


def test_candidates_pass_nothing_on():
    assert contract_categories([{"candidate": True, "category": "media", "ledger_ids": ["k"]}]) == {}


def test_derive_keeps_the_contract_category(monkeypatch):
    import custom_components.finance_dashboard.account_identity as identity

    monkeypatch.setattr(identity, "account_key", lambda a: f"key-{a.get('id')}")
    row = tx("a1", -12, 3, "Abo", cat="leisure")
    mgr = _ledger_manager({"a1": [row]})
    mgr._contract_categories = {f"key-a1|{row['_ledger_id']}": "media"}
    assert mgr._derive_from_ledger({})[0]["category"] == "media"


# ---------------------------------------------------------------------------
# Regression: figures for a view stay what the household summary says
# ---------------------------------------------------------------------------


def test_build_household_summary_counts_movement_out():
    txs = [*SALARIES, tx("a1", -200, 4, "x", cat="transfers"), *chain(tx("a1", -1, 2), tx("a2", 1, 2))]
    out = build_household_summary(accounts=ACCOUNTS, transactions=txs, plan=None, recurring=[],
                                  now=NOW, is_admin=True)
    assert out["expenses"] == 0 and out["income"] == 3000


def test_movement_reasons_name_the_reason():
    a = tx("a1", -200, 4, "x", cat="transfers")
    legs = chain(tx("a1", -1, 2), tx("a2", 1, 2))
    reasons = movement_reasons([a, *legs], ACCOUNTS)
    assert reasons[id(a)] == MOVEMENT_OWN and reasons[id(legs[0])] == MOVEMENT_CHAIN


def test_counterparty_iban_is_kept_for_the_own_account_check():
    from custom_components.finance_dashboard.enablebanking_client import EnableBankingClient

    row = EnableBankingClient._normalize_transaction({
        "transaction_amount": {"amount": "5", "currency": "EUR"},
        "credit_debit_indicator": "DBDT",
        "creditor": {"name": "Unbekannt"},
        "creditor_account": {"iban": "DE00222"},
    })
    assert OwnAccounts.of(ACCOUNTS).matches(row)


# ---------------------------------------------------------------------------
# Red-team findings on this overhaul
# ---------------------------------------------------------------------------


def test_answer_on_a_contract_booking_is_not_overwritten_by_an_unplaced_contract():
    row = tx("a1", -12, 3, "Abo", cat="leisure")
    key = f"{row['_account_key']}|{row['_ledger_id']}"
    contracts = [{"id": "c", "category": "other", "ledger_ids": [key]}]
    assert contract_categories(contracts) == {}
    assert resolve_bookings([row], contracts, {})[key]["category"] == "leisure"


def test_series_category_comes_from_the_own_category():
    from custom_components.finance_dashboard.recurring import detect_series

    rows = [
        tx("a1", -12, 3, "Abo GmbH", month=m, cat="media", _own_category="leisure")
        for m in (1, 2, 3, 4)
    ]
    series = detect_series(rows, today=date(2026, 4, 15))
    assert series and series[0]["category"] == "leisure"


@pytest.mark.parametrize("name", ["Miete", "Abschlag"])
def test_position_named_by_a_common_word_still_matches(name):
    position = CostPosition(id="a", name=name, owner="Anna", amount=700.0)
    row = tx("a2", -700, 3, "Vermieter", remittanceInformationUnstructured=f"{name} April")
    assert best_position(row, [position]) is position


def test_short_institution_name_is_no_evidence_inside_a_word():
    accounts = [{**ACCOUNTS[0], "institution": "ING"}, {**ACCOUNTS[1], "institution": "Bank B"}]
    out = tx("a1", -3000, 1, "Leasing Consulting")
    into = tx("a2", 3000, 1, "Holding AG", cat="income_work")
    assert detect_transfer_chains([out, into], accounts)[0] == []


def test_partner_credit_and_foreign_debit_are_no_transfer():
    rent = tx("a2", -900, 2, "Vermieter", cat="housing_cold")
    partner = tx("s1", 900, 2, "Anna Muster")
    assert detect_transfer_chains([rent, partner], ACCOUNTS)[0] == []
    assert len(transfer_questions([rent, partner], ACCOUNTS)) == 1


def test_real_transfer_wins_the_credit_over_an_unproven_pair():
    purchase = tx("a2", -250, 3, "Elektromarkt", cat="other")
    real = tx("a1", -250, 3, "Max Beispiel")
    credit = tx("a2", 250, 3, "Anna Muster")
    other = tx("s1", -250, 3, "Elektro GmbH")
    chains, _ = detect_transfer_chains([other, purchase, real, credit], ACCOUNTS)
    assert len(chains) == 1 and set(chains[0].txn_ids) == {real["_account_key"] + "|" + real["_ledger_id"],
                                                           credit["_account_key"] + "|" + credit["_ledger_id"]}


def test_equal_ledger_ids_on_two_accounts_stay_apart():
    out, into = tx("a1", -10, 3, "Max Beispiel"), tx("a2", 10, 3, "Anna Muster")
    out["_ledger_id"] = into["_ledger_id"] = "fp:same"
    chains, refunds = detect_transfer_chains([out, into], ACCOUNTS)
    enrich_transactions([out, into], chains, refunds)
    assert out["_transfer_role"] == "source" and into["_transfer_role"] == "destination"


def test_merchant_refund_on_paypal_is_no_top_up():
    debit = tx("a1", -60, 10, "PayPal Europe S.a r.l.")
    refund = pp_line(60, 12, "Shop", cat="income_refund")
    reasons = movement_reasons([debit, refund], ACCOUNTS)
    assert id(refund) not in reasons and id(debit) not in reasons
    shop_credit = pp_line(60, 12, "Shop", cat="groceries")
    assert id(shop_credit) not in movement_reasons([debit, shop_credit], ACCOUNTS)


def test_refund_is_matched_to_the_counted_side(frozen):
    mgr = _manager([tx("a1", -60, 10, "PayPal"), pp_line(-60, 10, "Apotheke", cat="health")])
    assert mgr.get_refund_analysis()["allocations"] == {}
    from custom_components.finance_dashboard import refund_matcher

    seen = []
    real = refund_matcher.analyse
    refund_matcher.analyse = lambda txs, **kw: (seen.extend(txs), real(txs, **kw))[1]
    try:
        mgr.get_refund_analysis()
    finally:
        refund_matcher.analyse = real
    assert len(seen) == 1 and seen[0]["creditorName"] == "Apotheke"


def test_empty_paypal_answer_drops_nothing():
    led = Ledger(None)
    led.ingest("k", [_pp_raw("2026-04-05")], [], date_from="2026-04-01")
    led.ingest("k", [], [], date_from="2026-04-01")
    assert len(led.transactions("k")) == 1


def test_short_paypal_answer_keeps_rows_below_it():
    led = Ledger(None)
    led.ingest("k", [_pp_raw("2026-03-20")], [], date_from="2026-03-01")
    led.ingest("k", [_pp_raw("2026-04-05")], [], date_from="2026-03-15")
    assert len(led.transactions("k")) == 2


def test_paypal_row_missing_inside_the_answer_is_a_reversal():
    led = Ledger(None)
    led.ingest("k", [_pp_raw("2026-04-05"), _pp_raw("2026-04-07", -3.0)], [], date_from="2026-04-01")
    led.ingest("k", [_pp_raw("2026-04-05")], [], date_from="2026-04-01")
    assert [effective_date_str(t) for t in led.transactions("k")] == ["2026-04-05"]


def test_future_value_date_does_not_move_the_fetch_window():
    led = Ledger(None)
    led.ingest("k", [{**_pp_raw("2020-01-05")},
                     {"valueDate": "2999-01-01", "transactionAmount": {"amount": "-1", "currency": "EUR"},
                      "creditorName": "x"}], [], date_from="2020-01-01", truncated=True)
    assert led.last_booked_date("k") == "2020-01-05"


def test_failed_reference_migration_is_retried(monkeypatch):
    mgr = _manager([])
    led = Ledger(None)
    old_id = f"fp:{fingerprint({**_pp_raw(''), 'transactionDate': ''})}"
    led.data["accounts"]["k"] = {
        "transactions": [{**_pp_raw("2026-03-05"), "_ledger_id": old_id, "_status": "booked"}],
        "balances": [],
    }
    mgr._ledger, mgr._ledger_writable = led, True
    calls = []

    async def boom(renames):
        calls.append(renames)
        if len(calls) == 1:
            raise OSError("disk")

    monkeypatch.setattr(mgr, "_async_rename_booking_refs", boom, raising=False)
    asyncio.run(mgr._async_migrate_ledger_ids())
    assert old_id in led.meta["lid_renames"]["k"]
    asyncio.run(mgr._async_migrate_ledger_ids())  # next start: no new renames, still moved
    assert calls[1] == calls[0] and "lid_renames" not in led.meta


def test_lower_paid_new_job_opens_cycles():
    old = [(date(2025, m, 1), 4000, "Alt AG") for m in range(1, 13)]
    new = [(date(2026, m, 3), 3000, "Neu AG") for m in range(1, 7)]
    starts = salary_starts([*old, *new])
    assert date(2026, 5, 3) in starts and date(2025, 5, 1) in starts


def test_same_size_bonus_off_payday_opens_no_cycle():
    assert date(2026, 3, 14) not in salary_starts([*_regular(), (date(2026, 3, 14), 3000, "ACME")])


def test_recent_payer_sets_the_level_not_an_old_small_one():
    rows = [*_regular(), *[(date(2024, m, 10), 200, "Alt") for m in range(1, 4)]]
    assert salary_starts(rows) == salary_starts(_regular())
