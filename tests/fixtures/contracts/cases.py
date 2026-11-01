"""Synthetic acceptance cases for contract detection (#106).

Every case encodes one failure pattern found when the contract tab was
reviewed against real household data. Names, merchants, IBANs and amounts are
invented; nothing here comes from a real account.

A case is ``(accounts, transactions)`` in the shape the manager holds after a
ledger rebuild, minus the derived fields the acceptance pipeline adds itself
(category, transfer chains). The expected result of each case lives in
``expected.json`` under the same key.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

GIRO = {
    "id": "acc-giro",
    "name": "Erika Mustermann",
    "institution": "Sparbank Musterstadt",
    "iban": "DE00000000000000000001",
    "type": "personal",
    "person": "erika",
}
PAYPAL = {
    "id": "acc-paypal",
    "name": "PayPal",
    "institution": "PayPal",
    "type": "personal",
    "person": "erika",
}

PAYPAL_BANK_NAME = "PayPal Europe S.a.r.l. et Cie S.C.A"


def _months(start: date, count: int, step: int = 1) -> list[date]:
    out = []
    for i in range(count):
        year, month0 = divmod(start.year * 12 + start.month - 1 + i * step, 12)
        out.append(date(year, month0 + 1, start.day))
    return out


class _Book:
    """Collects bookings with unique ids."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def add(
        self,
        day: date | None,
        amount: float,
        name: str,
        text: str = "",
        *,
        account: dict[str, Any] = GIRO,
        status: str = "booked",
        transaction_date: date | None = None,
    ) -> None:
        iso = day.isoformat() if day else ""
        tx_day = transaction_date or day
        self.rows.append(
            {
                "transactionId": f"t{len(self.rows) + 1:04d}",
                "_status": status,
                "bookingDate": iso,
                "valueDate": iso,
                "transactionDate": tx_day.isoformat() if tx_day else "",
                "transactionAmount": {"amount": f"{amount:.2f}", "currency": "EUR"},
                "creditorName" if amount < 0 else "debtorName": name,
                "remittanceInformationUnstructured": text,
                "_account_id": account["id"],
                "_account_key": account["id"],
                "_account_type": account["type"],
                "_account_person": account["person"],
            }
        )


def baseline_streaming(b: _Book) -> list[dict[str, Any]]:
    for d in _months(date(2026, 8, 3), 3):
        b.add(d, -12.99, "Streamflix GmbH", "VISA Debitkarte Streamflix")
    return [GIRO]


def baseline_rent(b: _Book) -> list[dict[str, Any]]:
    for d in _months(date(2026, 8, 1), 3):
        b.add(d, -950.00, "Hausverwaltung Beispiel GmbH", "Miete Whg 3 links")
    return [GIRO]


def paypal_subscription(b: _Book) -> list[dict[str, Any]]:
    # PayPal's own lines carry no booking or value date, only the transaction
    # date; the bank side mirrors each purchase as a PayPal debit.
    prices = (-13.99, -13.99, -17.99)
    for d, amount in zip(_months(date(2026, 8, 12), 3), prices, strict=True):
        b.add(None, amount, "Streamly Media", "Abo Streamly", account=PAYPAL, transaction_date=d)
        text = f"PP.4471.PP . Streamly Media, Ihr Einkauf bei Streamly Media {d:%d.%m}"
        b.add(d, amount, PAYPAL_BANK_NAME, text)
    return [GIRO, PAYPAL]


def two_loans_same_lender(b: _Book) -> list[dict[str, Any]]:
    for d in _months(date(2026, 8, 1), 3):
        b.add(d, -250.00, "Musterbank AG", f"Darlehen 4711001 Rate {d:%m/%Y}")
        b.add(d, -180.00, "Musterbank AG", f"Darlehen 4711002 Rate {d:%m/%Y}")
    return [GIRO]


def subscription_plus_oneoffs(b: _Book) -> list[dict[str, Any]]:
    for d in _months(date(2026, 8, 5), 3):
        b.add(d, -9.99, "Appstore Digital Services", "Abo Cloudspeicher 200 GB")
    b.add(date(2026, 8, 17), -2.99, "Appstore Digital Services", "App-Kauf")
    b.add(date(2026, 9, 21), -24.99, "Appstore Digital Services", "App-Kauf")
    b.add(date(2026, 10, 14), -0.99, "Appstore Digital Services", "App-Kauf")
    return [GIRO]


def bnpl_membership(b: _Book) -> list[dict[str, Any]]:
    for d in _months(date(2026, 8, 20), 3):
        b.add(d, -4.99, "Klarnetta Bank", "Mitgliedschaft Plus")
    b.add(date(2026, 8, 2), -33.33, "Klarnetta Bank", "Ratenkauf 88123 Teil 1/3")
    b.add(date(2026, 8, 25), -18.50, "Klarnetta Bank", "Ratenkauf 88544 Teil 1/2")
    b.add(date(2026, 9, 2), -33.33, "Klarnetta Bank", "Ratenkauf 88123 Teil 2/3")
    b.add(date(2026, 9, 28), -41.00, "Klarnetta Bank", "Rechnung 89002")
    return [GIRO]


def loan_to_own_name(b: _Book) -> list[dict[str, Any]]:
    # The instalment goes to an own account at a bank that is not linked.
    for d in _months(date(2026, 8, 15), 3):
        b.add(d, -320.00, "Erika Mustermann", "Rate Sparbank 99887766")
    return [GIRO]


def mobile_via_family(b: _Book) -> list[dict[str, Any]]:
    for d in _months(date(2026, 8, 28), 3):
        b.add(d, -29.99, "Hans Mustermann", "Funkfix Mobilfunk Erika")
    return [GIRO]


def weekly_meal_kit_with_skips(b: _Book) -> list[dict[str, Any]]:
    skipped = {date(2026, 8, 28), date(2026, 9, 25)}
    for i in range(12):
        d = date(2026, 8, 7) + timedelta(weeks=i)
        if d not in skipped:
            b.add(d, -59.90, "Kochkiste GmbH", "Kochkiste Box Woche")
    return [GIRO]


def energy_advance_and_settlement(b: _Book) -> list[dict[str, Any]]:
    for d in _months(date(2025, 11, 10), 9):
        b.add(d, -85.00, "Stadtwerke Musterstadt", "Abschlag Kd-Nr 5550123")
    settlement = "Jahresabrechnung 2025 Kd-Nr 5550123 Nachzahlung"
    b.add(date(2026, 7, 24), -240.00, "Stadtwerke Musterstadt", settlement)
    for d in _months(date(2026, 8, 10), 3):
        b.add(d, -95.00, "Stadtwerke Musterstadt", "Abschlag Kd-Nr 5550123")
    return [GIRO]


def quarterly_with_doubled_instalment(b: _Book) -> list[dict[str, Any]]:
    for d in _months(date(2024, 12, 15), 8, step=3):
        amount = -300.00 if d == date(2025, 9, 15) else -150.00
        b.add(d, amount, "Hausrat Muster VVaG", "Beitrag Vertrag HR-20031")
    return [GIRO]


def occasional_card_purchases(b: _Book) -> list[dict[str, Any]]:
    shops = {
        "Cafe Bohne": (
            (date(2026, 8, 6), -12.40),
            (date(2026, 9, 5), -13.10),
            (date(2026, 10, 6), -11.80),
        ),
        "Drogerie Rosig": (
            (date(2026, 8, 14), -23.50),
            (date(2026, 9, 13), -25.00),
            (date(2026, 10, 12), -26.10),
        ),
        "Linden-Apotheke": ((date(2026, 9, 2), -18.20), (date(2026, 10, 2), -19.90)),
    }
    for shop, visits in shops.items():
        for d, amount in visits:
            b.add(d, amount, shop, f"VISA Debitkarte {shop}")
    return [GIRO]


def health_refunds(b: _Book) -> list[dict[str, Any]]:
    b.add(date(2026, 8, 4), -120.00, "Dr. med. Anna Beispiel", "Rechnung 2026-0815")
    b.add(date(2026, 8, 20), -42.30, "Rosen-Apotheke", "Rezept 7781")
    b.add(date(2026, 9, 19), -85.50, "Dr. med. Anna Beispiel", "Rechnung 2026-0977")
    # full refund of the first bill
    b.add(date(2026, 8, 29), 120.00, "Kranken AG", "KV-LSTG. 04.08.2026")
    # one refund covering the pharmacy fully and the second bill partly
    b.add(date(2026, 10, 10), 110.70, "Kranken AG", "KV-LSTG. 20.08.2026 19.09.2026")
    return [GIRO]


def pending_debit_at_month_end(b: _Book) -> list[dict[str, Any]]:
    for d in _months(date(2026, 7, 30), 3):
        b.add(d, -45.00, "Fitnessclub Kraftwerk", "Mitgliedsbeitrag")
    b.add(date(2026, 10, 30), -45.00, "Fitnessclub Kraftwerk", "Mitgliedsbeitrag", status="pending")
    return [GIRO]


def yearly_contracts_long_history(b: _Book) -> list[dict[str, Any]]:
    b.add(date(2024, 11, 20), -89.00, "Autoclub Muster e.V.", "Jahresbeitrag Mitgl 334455")
    b.add(date(2025, 11, 20), -89.00, "Autoclub Muster e.V.", "Jahresbeitrag Mitgl 334455")
    b.add(date(2025, 1, 10), -64.50, "Haftpflicht Muster AG", "Jahresbeitrag PHV 77001")
    b.add(date(2026, 1, 10), -64.50, "Haftpflicht Muster AG", "Jahresbeitrag PHV 77001")
    return [GIRO]


CASES = {
    fn.__name__: fn
    for fn in (
        baseline_streaming,
        baseline_rent,
        paypal_subscription,
        two_loans_same_lender,
        subscription_plus_oneoffs,
        bnpl_membership,
        loan_to_own_name,
        mobile_via_family,
        weekly_meal_kit_with_skips,
        energy_advance_and_settlement,
        quarterly_with_doubled_instalment,
        occasional_card_purchases,
        health_refunds,
        pending_debit_at_month_end,
        yearly_contracts_long_history,
    )
}


def build(case: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Accounts and fresh transaction dicts for ``case``."""
    book = _Book()
    accounts = CASES[case](book)
    return [dict(a) for a in accounts], book.rows
