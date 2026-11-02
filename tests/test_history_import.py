"""History import (#121): local parsing, validation, duplicates, batches, detection."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.finance_dashboard import history_import as hi
from custom_components.finance_dashboard.categorizer import TransactionCategorizer
from custom_components.finance_dashboard.contracts import build_contracts, own_account_names
from custom_components.finance_dashboard.data_store import Ledger
from custom_components.finance_dashboard.household_summary import counted_transactions, pending_debits
from custom_components.finance_dashboard.transfer_detector import (
    detect_transfer_chains,
    enrich_transactions,
)
from tests.fixtures.contracts.cases import GIRO, build
from tests.test_contract_acceptance import EXPECTED, SPEC, _pair
from tests.test_contracts import blank_store

TODAY = date(2026, 11, 1)


def _german_csv(txns: list[dict]) -> bytes:
    """A bank-style export of fixture rows: preamble, German headers, decimal comma."""
    lines = [
        "Umsatzanzeige;;;",
        "Konto;Muster;;",
        "",
        "Buchungstag;Beguenstigter/Zahlungspflichtiger;Verwendungszweck;Betrag",
    ]
    for t in txns:
        d = date.fromisoformat(t["bookingDate"])
        amt = float(t["transactionAmount"]["amount"])
        name = t.get("creditorName") or t.get("debtorName")
        text = t["remittanceInformationUnstructured"]
        lines.append(f"{d:%d.%m.%Y};{name};{text};" + f"{amt:.2f}".replace(".", ","))
    return ("\n".join(lines) + "\n").encode("cp1252")


def _parse(data: bytes):
    table = hi.read_table(data)
    cands, mapping = hi.rows_from_table(table)
    assert mapping is not None
    return hi.validate_rows(cands, today=TODAY)


def test_amount_formats():
    assert hi.parse_amount("-1.234,56") == -1234.56
    assert hi.parse_amount("89,00-") == -89.0
    assert hi.parse_amount("1,234.56") == 1234.56
    assert hi.parse_amount("+12.5 EUR") == 12.5
    assert hi.parse_amount("1.234") == 1234.0
    assert hi.parse_amount("abc") is None


def test_date_formats():
    assert hi.parse_date("20.11.2025") == date(2025, 11, 20)
    assert hi.parse_date("2025-11-20T00:00:00") == date(2025, 11, 20)
    assert hi.parse_date("31.02.2025") is None


def test_german_csv_with_preamble_and_debit_credit_columns():
    csv = (
        "Auszug\n\nDatum;Name;Zweck;Soll;Haben\n"
        "01.10.2025;Muster GmbH;Miete;800,00;\n05.10.2025;Arbeitgeber;Lohn;;2.500,00\n"
    )
    valid, invalid = _parse(csv.encode("utf-8"))
    assert not invalid
    assert [r["amount"] for r in valid] == [-800.0, 2500.0]


def test_invalid_rows_are_listed_not_dropped():
    csv = "Datum;Name;Betrag\n01.10.2025;A;-5,00\nkaputt;B;-3,00\n02.10.2025;C;viel\n02.10.2099;D;-1,00\n"
    valid, invalid = _parse(csv.encode())
    assert len(valid) == 1
    assert [i["reason"] for i in invalid] == ["bad_date", "bad_amount", "date_out_of_range"]
    assert all(i["line"] for i in invalid)


def test_unreadable_layout_has_no_mapping():
    table = hi.read_table(b"foo bar\nbaz qux\n")
    assert hi.rows_from_table(table)[1] is None


def test_pdf_and_binary_are_rejected():
    with pytest.raises(hi.ImportFileError) as exc:
        hi.read_table(b"%PDF-1.7 ...")
    assert exc.value.code == "pdf_unsupported"
    with pytest.raises(hi.ImportFileError):
        hi.read_table(b"\x00\x01\x02" * 100)


def test_ai_payload_masks_ibans():
    table = hi.read_table(
        b"Datum;Name;Zweck;Betrag\n01.10.2025;X;DE89 3704 0044 0532 0130 00 Ref 123456789012;-5,00\n"
    )
    chunk = "\n".join(hi.ai_chunks(table))
    assert "DE89" not in chunk and "0532" not in chunk and "123456789012" not in chunk
    assert "[IBAN]" in chunk and "[NUM]" in chunk


def test_ai_answer_parsing_and_validation():
    answer = (
        'Here you go:\n```json\n[{"date":"2025-03-01","amount":-12.5,"counterparty":"Shop","text":"x"},'
        '{"date":"nope","amount":1,"counterparty":"Y"}, 5]\n```'
    )
    rows = hi.parse_ai_answer(answer)
    valid, invalid = hi.validate_rows(rows, today=TODAY)
    assert len(valid) == 1 and valid[0]["currency"] == "EUR"
    assert [i["reason"] for i in invalid] == ["bad_date", "not_an_object"]
    assert hi.parse_ai_answer("no json here") is None


def _ledger_with_bank_rows() -> Ledger:
    ledger = Ledger(None)
    bank = [
        {
            "transactionId": "b1",
            "bookingDate": "2026-09-01",
            "transactionAmount": {"amount": "-50.00", "currency": "EUR"},
            "creditorName": "Strom AG",
            "remittanceInformationUnstructured": "Abschlag",
        }
    ]
    ledger.ingest("acc", bank, [], date_from="2026-08-01")
    return ledger


def test_classification_duplicate_overlap_new():
    ledger = _ledger_with_bank_rows()
    base = {"text": "", "currency": "EUR"}
    rows = [
        {"line": 1, "date": "2026-09-01", "amount": -50.0, "counterparty": "STROM AG", **base},
        {"line": 2, "date": "2026-09-10", "amount": -9.0, "counterparty": "Foo", **base},
        {"line": 3, "date": "2025-01-10", "amount": -9.0, "counterparty": "Foo", **base},
    ]
    out, summary = hi.classify_rows(rows, ledger.transactions("acc"))
    assert [r["status"] for r in out] == ["duplicate", "overlap", "new"]
    assert summary["new"] == summary["duplicate"] == summary["overlap"] == 1


def test_batch_commit_reimport_and_undo():
    ledger = _ledger_with_bank_rows()
    row = {"line": 1, "date": "2025-01-10", "amount": -9.0, "counterparty": "Foo", "text": "t", "currency": "EUR"}
    rows = [row, dict(row, line=2)]
    txs = hi.to_ledger_transactions(rows, "b2")
    assert ledger.add_import_batch("acc", "b2", txs, hi.batch_summary(rows)) == 2  # genuine twins kept
    assert len(ledger.transactions("acc")) == 3
    assert ledger.import_batches()[0]["count"] == 2
    # the same file again is all duplicates
    again, _ = hi.classify_rows(rows, ledger.transactions("acc"))
    assert {r["status"] for r in again} == {"duplicate"}
    # a later bank fetch keeps history older than its window
    ledger.ingest("acc", [], [], date_from="2026-08-01", truncated=False)
    assert len([t for t in ledger.transactions("acc") if t.get("_source")]) == 2
    assert ledger.remove_import_batch("b2") == 2
    assert ledger.import_batches() == []
    assert not [t for t in ledger.transactions("acc") if t.get("_source")]


def test_yearly_contracts_detected_after_import():
    """Fixture 'yearly contracts in 13-24 months' through the import path (#121)."""
    case = "yearly_contracts_long_history"
    accounts, fixture_txns = build(case)
    valid, invalid = _parse(_german_csv(fixture_txns))
    assert not invalid and len(valid) == len(fixture_txns)

    ledger = Ledger(None)
    rows, summary = hi.classify_rows(valid, [])
    assert summary["new"] == len(valid)
    ledger.add_import_batch(GIRO["id"], "t1", hi.to_ledger_transactions(rows, "t1"), hi.batch_summary(rows))

    categorizer = TransactionCategorizer()
    txns = ledger.transactions(GIRO["id"])
    for tx in txns:
        tx.update(
            {
                "_account_id": GIRO["id"],
                "_account_key": GIRO["id"],
                "_account_type": GIRO["type"],
                "_account_person": GIRO["person"],
            }
        )
        tx["category"] = categorizer.categorize(tx)
    chains, refunds = detect_transfer_chains(txns, accounts)
    txns = enrich_transactions(txns, chains, refunds)
    counted = counted_transactions(txns, accounts) + pending_debits(txns)
    found = build_contracts(
        counted,
        blank_store(),
        today=date.fromisoformat(SPEC[case].get("today", EXPECTED["today"])),
        own_names=own_account_names(accounts),
    )
    pairs, _ = _pair(found, SPEC[case]["contracts"])
    assert not [w for w, hit in pairs if hit is None]


def test_xlsx_roundtrip():
    openpyxl = pytest.importorskip("openpyxl")
    import io

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Buchungstag", "Name", "Verwendungszweck", "Betrag"])
    ws.append([date(2025, 3, 1), "Verein", "Beitrag", -30.0])
    buf = io.BytesIO()
    wb.save(buf)
    valid, invalid = _parse(buf.getvalue())
    assert not invalid and valid[0]["date"] == "2025-03-01" and valid[0]["amount"] == -30.0
