"""History import (#121): regressions found by QA round 1."""

from __future__ import annotations

import csv
from datetime import date

import pytest

from custom_components.finance_dashboard import history_import as hi
from custom_components.finance_dashboard.data_store import Ledger
from custom_components.finance_dashboard.reprocess import merge_uncovered
from tests.test_history_import import _ledger_with_bank_rows, _parse

TODAY = date(2026, 11, 1)


def _add_batch(ledger: Ledger, day: str, batch: str = "b9") -> int:
    row = {"line": 1, "date": day, "amount": -9.0, "counterparty": "Foo", "text": "t", "currency": "EUR"}
    return ledger.add_import_batch("acc", batch, hi.to_ledger_transactions([row], batch), hi.batch_summary([row]))


def test_full_fetch_keeps_imported_rows_even_inside_its_window():
    ledger = _ledger_with_bank_rows()
    _add_batch(ledger, "2026-08-15")  # inside the span a full fetch reports
    ledger.ingest("acc", [], [], date_from="2026-01-01")
    assert [t for t in ledger.transactions("acc") if t.get("_source")]
    assert ledger.import_batches()[0]["count"] == 1


def test_reprocess_carries_imported_rows_inside_archive_coverage():
    ledger = _ledger_with_bank_rows()
    _add_batch(ledger, "2026-08-15")
    new = {"acc": {"transactions": [], "balances": []}}
    carried = merge_uncovered(ledger.data["accounts"], new, {"acc": "2026-01-01"})
    assert carried == 1 and new["acc"]["transactions"][0]["_source"] == "import:b9"


def test_overlap_uses_the_fetch_window_not_the_earliest_booking():
    ledger = Ledger(None)
    old = {
        "transactionId": "x",
        "bookingDate": "2025-01-05",
        "transactionAmount": {"amount": "-5.00", "currency": "EUR"},
        "creditorName": "Z",
        "remittanceInformationUnstructured": "",
    }
    ledger.ingest("acc", [old], [], date_from=None, truncated=True)  # a backfill reached far back
    base = {"counterparty": "Foo", "text": "", "currency": "EUR", "amount": -9.0}
    rows = [
        {"line": 1, "date": "2025-06-01", **base},  # after the earliest booking, before the window
        {"line": 2, "date": "2026-09-01", **base},
    ]
    out, _ = hi.classify_rows(rows, ledger.transactions("acc"), window_start="2026-08-03")
    assert [r["status"] for r in out] == ["new", "overlap"]


def test_imported_rows_do_not_move_fetch_boundaries():
    ledger = _ledger_with_bank_rows()
    _add_batch(ledger, "2026-10-30")
    _add_batch(ledger, "2024-01-01", "b8")
    assert ledger.last_booked_date("acc") == "2026-09-01"
    assert ledger.first_booked_date("acc") == "2026-09-01"


def test_xlsx_numbers_stay_numbers():
    table = hi.Table(
        rows=[
            ["Buchungstag", "Name", "Betrag"],
            ["2025-03-01", "A", -12.345],
            ["2025-03-02", "B", 19.990000000000002],
            ["2025-03-03", "C", 1e-05],
            ["2025-03-04", "D", 1.234],
        ],
        kind="xlsx",
    )
    cands, _mapping = hi.rows_from_table(table)
    valid, invalid = hi.validate_rows(cands, today=TODAY)
    assert [r["amount"] for r in valid] == [-12.35, 19.99, 1.23]  # 1.234 is 1.23 EUR, not 1234
    assert [i["reason"] for i in invalid] == ["amount_out_of_range"]


def test_csv_guess_does_not_mutate_the_shared_dialect():
    before = csv.excel.delimiter
    hi.read_table(b"a b c\nd e f\n")
    hi.read_table(b"x;y\n1;2\n")
    assert csv.excel.delimiter == before == ","


def test_csv_parse_errors_become_import_errors():
    huge = b"Datum;Name;Betrag\n01.01.2025;" + b"x" * (csv.field_size_limit() + 10) + b";-1,00\n"
    with pytest.raises(hi.ImportFileError) as exc:
        hi.read_table(huge)
    assert exc.value.code == "unreadable"
    wide = (";".join(["c"] * 250) + "\n").encode()
    with pytest.raises(hi.ImportFileError) as exc:
        hi.read_table(wide)
    assert exc.value.code == "too_many_columns"


def test_hyphenated_iban_is_masked_and_s_suffix_is_negative():
    assert "3704" not in hi.mask_sensitive("Ref DE89-3704-0044-0532-0130-00 end")
    assert hi.parse_amount("89,00S") == -89.0
    assert hi.parse_amount("89,00 H") == 89.0


def test_common_header_variants_map_locally():
    text = "Buchungstag;Zahlungsempfänger*in;Verwendungszweck;Betrag (€)\n01.10.2025;Muster;x;-5,00\n"
    valid, invalid = _parse(text.encode("utf-8"))
    assert len(valid) == 1 and not invalid
    assert len(_parse(b"Datum;Name;Umsatz in EUR\n01.10.2025;Muster;-5,00\n")[0]) == 1


def test_consent_is_spent_before_anything_is_sent_and_stays_spent_on_failure():
    import asyncio
    from unittest.mock import MagicMock, patch

    from custom_components.finance_dashboard.api import history_import as api

    order: list[str] = []

    async def mark_used(_hass, _purpose):
        order.append("consent")

    async def extract(*_a, **_k):
        order.append("send")
        return None, "request_failed"

    with (
        patch.object(api.ai_consent, "async_mark_used", mark_used),
        patch.object(api.ai_provider, "async_extract_history", extract),
    ):
        rows, error = asyncio.run(api._ask_ai(MagicMock(), MagicMock(), {"usable": True}, ["x"]))
    assert order == ["consent", "send"] and error == "request_failed" and rows == []


def test_commit_reclassifies_against_the_current_ledger():
    ledger = Ledger(None)
    row = {"line": 1, "date": "2025-02-01", "amount": -9.0, "counterparty": "Foo", "text": "", "currency": "EUR"}
    previewed, _ = hi.classify_rows([row], ledger.transactions("acc"), window_start="2026-08-03")
    assert previewed[0]["status"] == "new"
    # the same booking arrives from the bank between preview and commit
    bank = {
        "transactionId": "b", "bookingDate": "2025-02-01",
        "transactionAmount": {"amount": "-9.00", "currency": "EUR"}, "creditorName": "Foo",
        "remittanceInformationUnstructured": "",
    }
    ledger.ingest("acc", [bank], [], date_from=None, truncated=True)
    assert hi.rows_to_commit(previewed, ledger.transactions("acc"), window_start="2026-08-03") == []


def _bank_tx(tid: str, day: str, amount: str, party: str) -> dict:
    return {
        "transactionId": tid,
        "bookingDate": day,
        "transactionAmount": {"amount": amount, "currency": "EUR"},
        "creditorName": party,
        "remittanceInformationUnstructured": "",
    }


def test_later_bank_backfill_wins_over_imported_rows():
    ledger = Ledger(None)
    rows = [
        {"line": n, "date": d, "amount": a, "counterparty": "Autoclub Muster", "text": "", "currency": "EUR"}
        for n, (d, a) in enumerate([("2025-03-10", -89.0), ("2025-04-10", -89.0), ("2025-05-10", -12.0)], 1)
    ]
    ledger.add_import_batch("acc", "bb", hi.to_ledger_transactions(rows, "bb"), hi.batch_summary(rows))
    # the bank now reaches back: 2 days off (covered), same date but another amount (kept), other payee (kept)
    bank = [
        _bank_tx("a", "2025-03-12", "-89.00", "AUTOCLUB  Muster"),
        _bank_tx("b", "2025-04-10", "-89.50", "Autoclub Muster"),
        _bank_tx("c", "2025-05-10", "-12.00", "Someone Else"),
    ]
    ledger.ingest("acc", bank, [], date_from="2025-01-01", truncated=True)
    left = [t for t in ledger.transactions("acc") if t.get("_source")]
    assert [t["bookingDate"] for t in left] == ["2025-05-10", "2025-04-10"]
    batch = ledger.import_batches()[0]
    assert batch["count"] == 2 and batch["removed_by_bank"] == 1
    assert ledger.remove_import_batch("bb") == 2  # undo stays consistent with the rows that remain


def test_rebuild_reconciles_imports_with_bank_rows():
    ledger = Ledger(None)
    row = {"line": 1, "date": "2025-03-10", "amount": -89.0, "counterparty": "Verein", "text": "", "currency": "EUR"}
    ledger.add_import_batch("acc", "bc", hi.to_ledger_transactions([row], "bc"), hi.batch_summary([row]))
    ledger.data["accounts"]["acc"]["transactions"].append(
        dict(_bank_tx("z", "2025-03-10", "-89.00", "Verein"), _status="booked", _ledger_id="id:z")
    )
    assert ledger.reconcile_imports() == 1
    assert ledger.import_batches()[0]["removed_by_bank"] == 1


def test_one_preview_at_a_time():
    from unittest.mock import MagicMock

    from custom_components.finance_dashboard.api import history_import as api

    hass = MagicMock()
    hass.data = {}
    assert api._preview_lock(hass) is api._preview_lock(hass)
