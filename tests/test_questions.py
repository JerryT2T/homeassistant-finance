"""Merchant normalisation, learned memory, categorisation chain and open questions."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.finance_dashboard.budget_plan import BudgetPlan
from custom_components.finance_dashboard.categorizer import TransactionCategorizer
from custom_components.finance_dashboard.home import build_home
from custom_components.finance_dashboard.manager._questions import (
    QuestionError,
    QuestionsMixin,
)
from custom_components.finance_dashboard.merchants import (
    MerchantMemory,
    display_name,
    merchant_key,
)
from custom_components.finance_dashboard.questions import select_questions
from tests.fakes import FakeStore

NOW = datetime(2026, 10, 28, 12, 0).astimezone()


def _tx(creditor="", remit="", amount=-10.0, day=20, lid="", chain=None, debtor=""):
    return {
        "bookingDate": f"2026-10-{day:02d}",
        "transactionAmount": {"amount": str(amount), "currency": "EUR"},
        "creditorName": creditor,
        "debtorName": debtor,
        "remittanceInformationUnstructured": remit,
        "_ledger_id": lid,
        "_transfer_chain_id": chain,
        "_account_type": "shared",
        "_account_person": "",
        "_status": "booked",
    }


@pytest.mark.parametrize(
    ("creditor", "remit", "key"),
    [
        ("Globus.Markthalle/Koblenz", "VISA Debitkartenumsatz vom 27.10.2026", "globus markthalle"),
        ("SumUp...The.Studio/Koblenz", "VISA Debitkartenumsatz vom 01.10.2026", "the studio"),
        ("PAYPAL...BOOKINGKIT/3060985033", "", "bookingkit"),
        ("PP.1234.PP . Spotify", "", "spotify"),
        ("REWE Markt GmbH", "", "rewe markt"),
        ("Foo Bar SE", "", "foo bar"),
        ("", "VISA Debitkartenumsatz vom 27.10.2026 Bäckerei Kamps 12345678", "baeckerei kamps"),
        # the processor itself is the counterparty: the merchant comes from the text
        (
            "PayPal Europe S.a.r.l. et Cie S.C.A",
            "PP.4471.PP . Streamly Media, Ihr Einkauf bei Streamly Media",
            "streamly media",
        ),
        (
            "PayPal (Europe) S.à r.l. et Cie, S.C.A.",
            "1040123 PP.5555.PP . Lieferheld",
            "lieferheld",
        ),
    ],
)
def test_merchant_key(creditor, remit, key) -> None:
    assert merchant_key(_tx(creditor, remit)) == key


def test_purchases_through_one_processor_keep_separate_merchants() -> None:
    paypal = "PayPal Europe S.a.r.l. et Cie S.C.A"
    pizza = _tx(paypal, "PP.1.PP . Pizzeria Roma, Ihr Einkauf bei Pizzeria Roma")
    taxi = _tx(paypal, "PP.2.PP . Taxi Zentrale, Ihr Einkauf bei Taxi Zentrale")
    assert merchant_key(pizza) != merchant_key(taxi)
    assert "europe" not in merchant_key(pizza)


def test_same_merchant_different_cities_and_dates_share_a_key() -> None:
    a = _tx("Globus.Markthalle/Koblenz", "VISA Debitkartenumsatz vom 27.10.2026")
    b = _tx("GLOBUS.MARKTHALLE/Mainz", "VISA Debitkartenumsatz vom 03.09.2026")
    assert merchant_key(a) == merchant_key(b)
    assert display_name(a) == "Globus Markthalle"


def test_income_uses_the_debtor() -> None:
    assert merchant_key(_tx(creditor="Me", debtor="Acme GmbH", amount=100)) == "acme"


@pytest.mark.parametrize(
    ("creditor", "cat"),
    [("dm-drogerie markt", "groceries"), ("Rossmann", "groceries"), ("IKEA", "groceries"),
     ("Stadt-Apotheke", "health"), ("Esso Tankstelle", "mobility"), ("Gastronomie X", "leisure"),
     ("Mietpool Koblenz", "housing_cold"), ("ARD ZDF Beitragsservice", "media"),
     ("Zalando", "other")],
)
def test_extended_keywords(creditor, cat) -> None:
    assert TransactionCategorizer().categorize(_tx(creditor)) == cat


def test_short_keywords_need_word_start() -> None:
    cat = TransactionCategorizer()
    assert cat.categorize(_tx("Adm Foo")) == "other"  # "dm" inside a word
    assert cat.categorize(_tx("Mogas Bar")) == "other"


@pytest.mark.asyncio
async def test_chain_order_booking_then_merchant_then_keywords() -> None:
    mem = MerchantMemory(store=FakeStore())
    cat = TransactionCategorizer(memory=mem)
    tx = _tx("Rossmann", lid="L1")
    assert cat.categorize(tx) == "groceries"  # keyword
    mem.learn_merchant("rossmann", "health", "Anna")
    assert cat.resolve(tx) == ("health", "Anna")  # merchant memory beats keywords
    mem.learn_booking("L1", "food")
    assert cat.resolve(tx) == ("food", None)  # one-off beats merchant


@pytest.mark.asyncio
async def test_memory_persists_without_amounts_or_dates() -> None:
    store = FakeStore()
    mem = MerchantMemory(store=store)
    mem.learn_merchant("the studio", "leisure")
    mem.record_answer(date(2026, 10, 28))
    await mem.async_save()
    assert "amount" not in str(store._data) and "2026-10" not in str(store._data["merchants"])
    again = MerchantMemory(store=store)
    await again.async_load()
    assert again.known_merchants() == {"the studio": {"category": "leisure"}}
    assert again.answered == 1 and again.week_answered(date(2026, 10, 29)) == 1
    assert again.week_answered(date(2026, 11, 9)) == 0  # next week


def test_points_every_seven_answers() -> None:
    mem = MerchantMemory(store=FakeStore())
    awarded = [mem.record_answer(date(2026, 10, 28)) for _ in range(14)]
    assert [i for i, a in enumerate(awarded, 1) if a] == [7, 14]
    assert mem.points == 2


def test_history_is_newest_first_and_a_user_answer_moves_the_merchant_up() -> None:
    mem = MerchantMemory(store=FakeStore())
    mem.learn_merchant("rewe", "food")
    assert mem.learn_ai_merchant("aral", "transport")
    mem.learn_merchant("ikea", "shopping", "shared")
    mem.learn_merchant("aral", "leisure")  # user overrides the AI entry
    mem.learn_booking("lid-1", "health")
    h = mem.history()
    assert [i["merchant"] for i in h["items"]] == ["aral", "ikea", "rewe"]
    assert h["items"][0] == {
        "merchant": "aral", "category": "leisure", "owner": None, "source": "user"
    }
    assert h["items"][1]["owner"] == "shared"
    assert (h["total"], h["by_user"], h["by_ai"], h["bookings"]) == (3, 3, 0, 1)
    assert mem.learn_ai_merchant("dm", "health")
    assert mem.history(limit=1)["items"] == [
        {"merchant": "dm", "category": "health", "owner": None, "source": "ai"}
    ]
    assert mem.history()["by_ai"] == 1


def test_select_groups_orders_and_caps() -> None:
    cands = [
        {"merchant": f"m{i}", "display": f"M{i}", "amount": -float(i), "date": date(2026, 10, 1),
         "lid": f"l{i}"}
        for i in range(1, 16)
    ]
    cands.append({"merchant": "m1", "display": "M1", "amount": -100.0, "date": date(2026, 10, 9)})
    visible, total = select_questions(cands)
    assert total == 15 and len(visible) == 10
    assert visible[0]["id"] == "m1" and visible[0]["count"] == 2 and visible[0]["total"] == 101.0
    assert visible[0]["dates"] == ["2026-10-09", "2026-10-01"]
    # Answered questions count against the weekly quota.
    visible, total = select_questions(cands, week_answered=4)
    assert len(visible) == 6 and total == 15
    assert select_questions(cands, week_answered=12)[0] == []


def _home(txs, **kw):
    return build_home(
        accounts=[{"id": "a3", "type": "shared"}], transactions=txs, plan=BudgetPlan(), pots=[],
        recurring=[], banks=[], as_of=NOW, now=NOW, person=None, view="household",
        horizon="cycle", **kw,
    )


def test_home_counts_open_merchant_questions_not_chain_not_pending() -> None:
    txs = [
        _tx("Globus.Markthalle/Koblenz", amount=-30, lid="a"),
        _tx("Globus.Markthalle/Koblenz", amount=-20, lid="b", day=21),
        _tx("Unknown Kiosk", amount=-5, lid="c"),
        _tx("Own Transfer", amount=-500, lid="d", chain="chain-1"),
        {**_tx("Pending Shop", amount=-9, lid="e"), "_status": "pending"},
        {**_tx("Known", amount=-9, lid="f"), "category": "food"},
    ]
    for t in txs:
        t.setdefault("category", "other")
    out = _home(txs)
    assert out["questions_open"] == 2 and out["questions_total"] == 2
    assert "questions" not in out
    full = _home(txs, include_questions=True)
    assert [q["id"] for q in full["questions"]] == ["globus markthalle", "unknown kiosk"]
    assert full["questions"][0]["count"] == 2 and full["questions"][0]["total"] == 50.0


def test_question_card_carries_bookings_and_history_masked() -> None:
    old = {**_tx("Treder", remit="Miete Garage", amount=-50, lid="o"), "bookingDate": "2026-03-20",
           "category": "food"}
    txs = [old] + [
        {**_tx("Treder", remit=f"Ueberweisung {d}", amount=-(400 + d), lid=f"t{d}", day=d),
         "_account_name": "Girokonto", "creditorAccount": {"iban": "DE89 3704 0044 0532 0130 00"},
         "category": "other"}
        for d in (1, 2)
    ]
    q = _home(txs, include_questions=True)["questions"][0]
    first = q["bookings"][0]
    assert first == {"date": "2026-10-02", "amount": -402.0, "account": "Girokonto",
                     "counterparty": "Treder", "iban_last4": "3000", "text": "Ueberweisung 2"}
    assert len(q["bookings"]) == 2
    assert "DE89" not in str(q)  # IBAN never leaves beyond the last four digits
    # History spans every expense of the merchant, also already categorised ones.
    assert q["history"] == {"count": 3, "first": "2026-03-20", "last": "2026-10-02", "months": 2}


def test_home_questions_capped_at_ten_but_total_shows_backlog() -> None:
    txs = [{**_tx(f"Shop {chr(97 + i)}x", amount=-(i + 1), lid=str(i)), "category": "other"}
           for i in range(14)]
    out = _home(txs)
    assert out["questions_open"] == 10 and out["questions_total"] == 14


def test_did_you_know_never_reports_other() -> None:
    txs = [{**_tx("Mystery", amount=-100, lid="x"), "category": "other"},
           {**_tx("Edeka", amount=-10, lid="y"), "category": "food"}]
    dyk = _home(txs)["did_you_know"]
    assert dyk is None or dyk["params"]["category"] != "other"


class _Mgr(QuestionsMixin):
    def __init__(self, txs):
        self._memory = MerchantMemory(store=FakeStore())
        self._categorizer = TransactionCategorizer(memory=self._memory)
        self._transactions = txs
        self._transfer_overrides = {}
        self._accounts = [{"id": "a3", "type": "shared", "person": "Anna"}]
        self.persons = [{"name": "Anna"}]
        self._demo_mode = False
        self._hass = MagicMock()
        self.derived = 0

    def _derive_from_ledger(self, _o=None):
        self.derived += 1
        for t in self._transactions:
            t["category"], t["_owner_override"] = self._categorizer.resolve(t)

    def get_home(self, **kw):
        return _home(self._transactions, **self._question_kwargs(),
                     include_questions=kw.get("include_questions", False))


def _mgr():
    txs = [_tx("SumUp...The.Studio/Koblenz", amount=-30, lid="a"),
           _tx("SumUp...The.Studio/Koblenz", amount=-20, lid="b", day=21),
           _tx("Unknown Kiosk", amount=-5, lid="c")]
    m = _Mgr(txs)
    m._derive_from_ledger()
    return m


@pytest.mark.asyncio
async def test_answer_merchant_recategorises_all_and_counts_once() -> None:
    m = _mgr()
    with patch("custom_components.finance_dashboard.manager._questions.dt_util") as du:
        du.now.return_value = NOW
        out = await m.async_answer_question(
            question_id="the studio", category="leisure", reach="merchant", owner="Anna")
    assert out == {"answered_total": 1, "week_answered": 1, "point_awarded": False}
    assert {t["category"] for t in m._transactions[:2]} == {"leisure"}
    assert m._transactions[0]["_owner_override"] == "Anna"
    assert m.get_questions()["questions_open"] == 1  # only the kiosk is left
    assert m._memory.known_merchants()["the studio"]["category"] == "leisure"


@pytest.mark.asyncio
async def test_answer_booking_reach_is_one_off_and_7th_fires_point() -> None:
    m = _mgr()
    m._memory._data["answered"] = 6
    with patch("custom_components.finance_dashboard.manager._questions.dt_util") as du:
        du.now.return_value = NOW
        out = await m.async_answer_question(
            question_id="unknown kiosk", category="leisure", reach="booking", user_id="u1")
    assert out["point_awarded"] is True
    m._hass.bus.async_fire.assert_called_once_with(
        "finance_dashboard_points_awarded",
        {"user_id": "u1", "person": None, "points": 1, "answered_total": 7})
    assert m._memory.known_merchants() == {}  # no merchant rule
    assert m._transactions[2]["category"] == "leisure"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kw", "code"),
    [({"category": "other"}, "invalid_category"), ({"category": "Bad Cat!"}, "invalid_category"),
     ({"reach": "everything"}, "invalid_reach"), ({"owner": "Mallory"}, "invalid_owner"),
     ({"question_id": ""}, "invalid_id"), ({"question_id": "nope", "reach": "booking"},
                                           "unknown_question")],
)
async def test_answer_validation(kw, code) -> None:
    args = {"question_id": "unknown kiosk", "category": "food", "reach": "merchant"} | kw
    with pytest.raises(QuestionError) as err:
        await _mgr().async_answer_question(**args)
    assert err.value.code == code


@pytest.mark.asyncio
async def test_views_admin_only() -> None:
    from custom_components.finance_dashboard.api.questions import (
        FinanceDashboardQuestionAnswerView,
        FinanceDashboardQuestionsView,
    )

    def _j(data, status_code=200):
        return SimpleNamespace(_data=data, _status=status_code)

    def _req(admin, body=None):
        req = MagicMock()
        user = SimpleNamespace(is_admin=admin, id="u1")
        req.get.side_effect = lambda k, d=None: user if k == "hass_user" else d
        req.__getitem__.side_effect = lambda k: user
        req.app = {"hass": MagicMock()}
        req.json = AsyncMock(return_value=body)
        return req

    lst, ans = FinanceDashboardQuestionsView(), FinanceDashboardQuestionAnswerView()
    lst.json = ans.json = _j
    assert (await lst.get(_req(False)))._status == 403
    assert (await ans.post(_req(False, {})))._status == 403
    mgr = _mgr()
    target = "custom_components.finance_dashboard.api.questions._get_manager"
    with patch(target, return_value=mgr):
        resp = await lst.get(_req(True))
        assert resp._status == 200 and resp._data["questions_open"] == 2
        assert len(resp._data["questions"][0]["suggested"]) == 3
        resp = await ans.post(_req(True, {"id": "x", "category": "other", "reach": "merchant"}))
        assert resp._status == 400 and resp._data["error"] == "invalid_category"
        resp = await ans.post(_req(True, [1]))
        assert resp._data["error"] == "invalid_body"


def test_forget_merchant_removes_only_that_rule() -> None:
    mem = MerchantMemory(store=FakeStore())
    mem.learn_merchant("rossmann", "health")
    mem.learn_merchant("aldi", "food")
    assert mem.forget_merchant("rossmann") is True
    assert mem.forget_merchant("rossmann") is False
    assert mem.resolve(_tx("Rossmann")) is None
    assert mem.resolve(_tx("Aldi"))["category"] == "food"
