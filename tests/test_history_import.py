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


def test_binary_is_rejected():
    with pytest.raises(hi.ImportFileError):
        hi.read_table(b"\x00\x01\x02" * 100)


# --- PDF statements (#147) ------------------------------------------------------------
# Invented sample statements only: no real names, accounts or amounts.


def _pdf(pages: list[list[tuple[float, str]]] | list[list[list[tuple[float, str]]]]) -> bytes:
    """A minimal text PDF.  Each page is a list of lines, each line a list of (x, text) cells."""

    def esc(text: str) -> bytes:
        raw = text.encode("cp1252")
        return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")

    objects: list[bytes] = []
    kids = []
    font_id = 3
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"")  # pages, filled below
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    for page in pages:
        ops = []
        y = 800
        for line in page:
            for x, text in line:
                ops.append(b"BT /F1 9 Tf %d %d Td (" % (x, y) + esc(text) + b") Tj ET")
            y -= 14
        stream = b"\n".join(ops)
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        content_id = len(objects)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents %d 0 R "
            b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (content_id, font_id)
        )
        kids.append(len(objects))
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids),
        len(kids),
    )
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def _cells(*cells: str) -> list[tuple[float, str]]:
    """One table row: booking day, value day, description, amount, balance at fixed columns."""
    xs = (40, 90, 140, 420, 500)
    return [(x, c) for x, c in zip(xs, cells) if c]


STATEMENT = [
    [
        [(40, "Musterbank - Kontoauszug 3/2025")],
        [(40, "IBAN DE00 1234 5678 9012 3456 78")],
        [(40, "Zeitraum 01.03.2025 bis 31.03.2025")],
        _cells("Buchung", "Valuta", "Vorgang", "Betrag", "Saldo"),
        _cells("01.03.", "01.03.", "Alter Kontostand", "", "1.000,00"),
        _cells("03.03.", "03.03.", "SEPA-Lastschrift Stadtwerke Beispielstadt", "-89,00", "911,00"),
        [(140, "Abschlag Strom März")],
        [(140, "Kundennr 4711")],
        _cells("15.03.", "15.03.", "Gutschrift", "2.500,00", "3.411,00"),
        [(140, "Erika Beispiel")],
        [(140, "Gehalt März")],
        _cells("20.03.", "20.03.", "Kartenzahlung Bäckerei Kornfeld", "12,40-", "3.398,60"),
    ],
    [
        [(40, "Seite 2 von 2")],
        _cells("28.03.", "28.03.", "Dauerauftrag Muster Wohnbau GmbH", "-800,00", "2.598,60"),
        [(140, "Miete Wohnung 3 OG")],
        _cells("31.03.", "31.03.", "Neuer Kontostand", "", "2.598,60"),
    ],
]


def test_pdf_statement_rows_through_the_same_validation():
    pytest.importorskip("pypdf")
    table = hi.read_table(_pdf(STATEMENT))
    assert table.kind == "pdf"
    cands, mapping = hi.rows_from_table(table)
    assert mapping == {}
    valid, invalid = hi.validate_rows(cands, today=TODAY)
    assert not invalid
    assert [(r["date"], r["amount"]) for r in valid] == [
        ("2025-03-03", -89.0),
        ("2025-03-15", 2500.0),
        ("2025-03-20", -12.4),
        ("2025-03-28", -800.0),
    ]
    first, credit, card, rent = valid
    assert first["counterparty"] == "Stadtwerke Beispielstadt"
    assert "Abschlag Strom März" in first["text"] and first["text"].startswith("SEPA-Lastschrift")
    assert credit["counterparty"] == "Erika Beispiel" and "Gehalt März" in credit["text"]
    assert card["counterparty"] == "Bäckerei Kornfeld"
    # the page header between bookings is not swallowed as purpose text
    assert rent["counterparty"] == "Muster Wohnbau GmbH" and "Seite" not in rent["text"]


def test_pdf_preview_classifies_like_csv():
    pytest.importorskip("pypdf")
    _, cands, mapping = hi.parse_upload(_pdf(STATEMENT))
    valid, _ = hi.validate_rows(cands, today=TODAY)
    ledger = Ledger(None)
    ledger.ingest(
        "acc",
        [
            {
                "transactionId": "b1",
                "bookingDate": "2025-03-03",
                "transactionAmount": {"amount": "-89.00", "currency": "EUR"},
                "creditorName": "Stadtwerke Beispielstadt",
                "remittanceInformationUnstructured": "Abschlag",
            }
        ],
        [],
        date_from="2025-03-01",
    )
    rows, summary = hi.classify_rows(valid, ledger.transactions("acc"), window_start="2025-03-25")
    assert [r["status"] for r in rows] == ["duplicate", "new", "new", "overlap"]
    assert (summary["new"], summary["duplicate"], summary["overlap"]) == (2, 1, 1)
    new = [r for r in rows if r["status"] == "new"]
    assert ledger.add_import_batch("acc", "p1", hi.to_ledger_transactions(new, "p1"), hi.batch_summary(new)) == 2
    assert ledger.remove_import_batch("p1") == 2


def test_pdf_lines_year_rollover_and_markers():
    lines = [
        "Kontoauszug 1/2026 vom 02.01.2026",
        "30.12. 30.12. Lastschrift",
        "Versicherung Beispiel AG",
        "Beitrag 2026 120,00 S",
        "02.01. Gutschrift Erstattung Beispiel 15,00 H",
        "02.01.2026 Abschluss Entgelt -4,90",
    ]
    rows = hi.rows_from_pdf_lines(lines)
    assert [(r["date"], r["amount"], r["counterparty"]) for r in rows] == [
        ("2025-12-30", -120.0, "Versicherung Beispiel AG"),  # amount from the line below
        ("2026-01-02", 15.0, "Erstattung Beispiel"),
        ("2026-01-02", -4.9, "Entgelt"),
    ]


def test_pdf_without_debit_markers_goes_the_ai_way():
    # separate Soll/Haben columns flatten to unsigned numbers: never guess the sign
    lines = ["Datum Text Soll Haben", "03.03.2025 Stadtwerke 89,00", "15.03.2025 Gehalt 2.500,00"]
    assert hi.rows_from_pdf_lines(lines) is None
    assert hi.rows_from_pdf_lines(["Sehr geehrte Kundin", "Ihr Auszug liegt bei"]) is None


def test_pdf_ai_fallback_masks_the_text():
    pytest.importorskip("pypdf")
    data = _pdf([[[(40, "Umsatz an DE00 1234 5678 9012 3456 78 Stadtwerke 89,00")]]])
    table, cands, mapping = hi.parse_upload(data)
    assert mapping is None and not cands
    chunk = "\n".join(hi.ai_chunks(table))
    assert "Stadtwerke" in chunk and "5678" not in chunk and "[IBAN]" in chunk


def test_pdf_without_text_and_with_password_are_rejected():
    pypdf = pytest.importorskip("pypdf")
    import io

    with pytest.raises(hi.ImportFileError) as exc:
        hi.read_table(_pdf([[]]))
    assert exc.value.code == "pdf_no_text"

    def encrypted(user_password: str) -> bytes:
        writer = pypdf.PdfWriter(clone_from=io.BytesIO(_pdf(STATEMENT)))
        writer.encrypt(user_password=user_password, owner_password="owner-x", algorithm="AES-128")
        buf = io.BytesIO()
        writer.write(buf)
        return buf.getvalue()

    with pytest.raises(hi.ImportFileError) as exc:
        hi.read_table(encrypted("secret"))
    assert exc.value.code == "pdf_encrypted"
    # print/copy protection with an empty user password is readable
    assert hi.rows_from_table(hi.read_table(encrypted("")))[1] == {}


def test_damaged_pdf_is_unreadable():
    pytest.importorskip("pypdf")
    with pytest.raises(hi.ImportFileError) as exc:
        hi.read_table(b"%PDF-1.7 truncated garbage")
    assert exc.value.code in ("unreadable", "pdf_no_text")


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
    out, summary = hi.classify_rows(rows, ledger.transactions("acc"), window_start="2026-08-03")
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
    again, _ = hi.classify_rows(rows, ledger.transactions("acc"), window_start="2026-08-03")
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
    rows, summary = hi.classify_rows(valid, [], window_start=None)
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


@pytest.mark.parametrize(
    "iban", ["DE89370400440532013000", "DE89 3704 0044 0532 0130 00", "de89370400440532013000",
     "GB29 NWBK 6016 1331 9268 19"]
)
def test_every_iban_spelling_is_masked(iban):
    # Codex #121: a short last group left the IBAN readable
    from custom_components.finance_dashboard.history_import import _IBAN

    assert _IBAN.sub("X", f"Miete {iban} Juni") == "Miete X Juni"
