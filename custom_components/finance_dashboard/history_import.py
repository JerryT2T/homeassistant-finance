"""Optional import of older booking history (13-24 months) from a file.

The bank API serves about 90 days; a yearly contract needs two payments 365
days apart.  This module lets the user add older bookings from a statement
export.  Everything here is pure (no storage, no network): the endpoint
(``api/history_import.py``) and the manager wire it to the ledger.

Flow: ``read_table`` (CSV/XLSX/PDF, local) -> ``rows_from_table`` (column
guess, or booking lines of a PDF statement, local) -> ``validate_rows`` ->
``classify_rows`` against the ledger -> preview -> commit as one tagged batch
(``Ledger.add_import_batch``) -> undo as a whole.

A PDF statement has no columns: its text is extracted locally (``pypdf``,
pure Python) and every line that starts with a booking date and ends with a
signed amount becomes a row; the lines below it up to the next booking are
its purpose text (``rows_from_pdf_lines``).

A file the local mapping cannot read (odd layout, no recognisable columns)
may go to the AI, but only with the ``history_import`` consent and only after
IBAN-like strings were masked here (``mask_sensitive``).  The AI answers in
the row schema below; every row is validated like a locally parsed one.

Row schema (what both paths produce)::

    {"date": "YYYY-MM-DD", "amount": -89.0, "counterparty": "...",
     "text": "...", "currency": "EUR"}

``amount`` is signed like the bank: expense negative.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import zipfile
from decimal import ROUND_HALF_UP, Decimal
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from .const import DEFAULT_FETCH_DAYS
from .tx_dates import effective_date_str

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20000
MAX_COLUMNS = 200
MAX_PREAMBLE = 40  # header row must appear within the first lines
MAX_COUNTERPARTY = 120
MAX_TEXT = 300
MAX_AMOUNT = 10_000_000
MAX_AGE_DAYS = 3660  # ten years; older is almost certainly a mis-parsed date
CURRENCIES = ("EUR", "CHF", "GBP", "USD", "SEK", "DKK", "NOK", "PLN", "CZK")

# AI limits: one call per chunk, counted against the monthly budget.
AI_CHUNK_LINES = 100
AI_MAX_CALLS = 12
AI_MAX_TOKENS = 6000

_ZIP_MAGIC = b"PK\x03\x04"
_PDF_MAGIC = b"%PDF-"
MAX_PDF_PAGES = 300
MAX_PDF_CHARS = 2_000_000
MAX_PDF_PAGE_BYTES = 4 * 1024 * 1024  # inflated content stream of one page
PDF_MAX_CONTINUATION = 3  # purpose lines kept below a booking line

_SYNONYMS: dict[str, tuple[str, ...]] = {
    "date": (
        "buchungstag", "buchungsdatum", "buchung", "datum", "booking date", "bookingdate",
        "date", "transaction date", "valuta", "wertstellung", "value date",
    ),
    "amount": ("betrag", "umsatz", "amount", "betrag eur", "betrag (eur)", "value"),
    "debit": ("soll", "belastung", "debit", "ausgang", "ausgaben"),
    "credit": ("haben", "gutschrift", "credit", "eingang", "einnahmen"),
    "counterparty": (
        "beguenstigter", "begünstigter", "zahlungsempfänger", "zahlungsempfaenger",
        "empfänger", "empfaenger", "auftraggeber", "name", "partner", "counterparty",
        "payee", "beneficiary", "name zahlungsbeteiligter", "beguenstigter/zahlungspflichtiger",
        "begünstigter/zahlungspflichtiger", "auftraggeber/empfänger", "zahlungsbeteiligter",
    ),
    "text": (
        "verwendungszweck", "buchungstext", "text", "reference", "description",
        "remittance", "beschreibung", "details", "memo", "zweck",
    ),
    "currency": ("währung", "waehrung", "currency", "curr"),
}
# date/amount synonyms in order of preference: "valuta" must not beat "buchungstag"
_FIELDS = ("date", "amount", "debit", "credit", "counterparty", "text", "currency")

# any grouping, also a short last group (DE89 3704 0044 0532 0130 00) (Codex #121)
_IBAN = re.compile(
    r"\b[A-Z]{2}\d{2}(?:[A-Z0-9]{11,30}"
    r"|[\s-][A-Z0-9]{4}(?:[\s-](?=[A-Z0-9]*\d)[A-Z0-9]{1,4}){2,7})\b",
    re.I,
)
_LONG_DIGITS = re.compile(r"\b\d{10,}\b")


class ImportFileError(ValueError):
    """The file was rejected; ``code`` is an i18n key suffix, the text is safe to show."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


@dataclass
class Table:
    """The file as text cells, header row not yet located."""

    rows: list[list[Any]]
    kind: str  # "csv" | "xlsx" | "pdf"
    lines: list[str] = field(default_factory=list)  # raw text lines (AI path)


# ---------------------------------------------------------------------------
# Reading the file
# ---------------------------------------------------------------------------


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value  # numbers stay numbers: no text round trip (1e-05, 19.990000000000002)
    return str(value).strip()


def _read_xlsx(data: bytes) -> list[list[Any]]:
    try:
        import openpyxl
    except ImportError as err:  # declared in manifest requirements
        raise ImportFileError("xlsx_unavailable", "openpyxl is not installed") from err
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as err:  # noqa: BLE001 - zip/xml damage of any kind
        raise ImportFileError("unreadable", "The workbook could not be read") from err
    try:
        sheet = wb.worksheets[0]
        rows: list[list[Any]] = []
        for raw in sheet.iter_rows(values_only=True):
            row = [_cell(c) for c in raw]
            if any(row):
                rows.append(row)
            if len(rows) > MAX_ROWS:
                raise ImportFileError("too_many_rows", f"More than {MAX_ROWS} rows")
        return rows
    finally:
        wb.close()


def _read_pdf(data: bytes) -> list[str]:
    """The text lines of a PDF, whitespace collapsed.  Local only, no OCR."""
    try:
        from pypdf import PdfReader
    except ImportError as err:  # declared in manifest requirements
        raise ImportFileError("pdf_unavailable", "pypdf is not installed") from err
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as err:  # noqa: BLE001 - any structural damage
        raise ImportFileError("unreadable", "The PDF could not be read") from err
    if reader.is_encrypted:
        # statements are often encrypted with an empty user password (print/copy rights only)
        try:
            opened = reader.decrypt("")
        except Exception:  # noqa: BLE001 - unsupported algorithm, missing crypto backend
            opened = 0
        if not opened:
            raise ImportFileError("pdf_encrypted", "The PDF is password protected")
    if len(reader.pages) > MAX_PDF_PAGES:
        raise ImportFileError("too_many_rows", f"More than {MAX_PDF_PAGES} pages")
    lines: list[str] = []
    total = 0
    for page in reader.pages:
        # a tiny compressed page may inflate to a huge content stream: refuse it before
        # the (costly) text extraction; pypdf itself caps one stream at 75 MB inflated
        try:
            contents = page.get_contents()
            size = len(contents.get_data()) if contents is not None else 0
        except Exception as err:  # noqa: BLE001 - damaged or over-limit stream
            raise ImportFileError("unreadable", "The PDF could not be read") from err
        if size > MAX_PDF_PAGE_BYTES:
            raise ImportFileError("too_many_rows", "A PDF page holds too much content")
        try:
            # layout mode keeps the cells of one table row on one line
            text = page.extract_text(extraction_mode="layout")
        except Exception:  # noqa: BLE001 - layout mode trips over some fonts
            text = page.extract_text() or ""
        for raw in text.splitlines():
            line = " ".join(raw.replace("\u2212", "-").split())  # typographic minus
            if line:
                lines.append(line)
                total += len(line)
        if total > MAX_PDF_CHARS:
            raise ImportFileError("too_many_rows", "The PDF holds too much text")
    if not any(re.search(r"\d", ln) for ln in lines):
        raise ImportFileError("pdf_no_text", "The PDF holds no text (scanned image?)")
    return lines


def _read_csv(text: str) -> list[list[str]]:
    sample = "\n".join(text.splitlines()[:50])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
    except csv.Error:
        # a copy: assigning to csv.excel itself would change the delimiter for the whole process
        dialect = type("_Guessed", (csv.excel,), {"delimiter": ";" if sample.count(";") >= sample.count(",") else ","})
    rows = []
    try:
        for raw in csv.reader(io.StringIO(text), dialect):
            row = [c.strip() for c in raw]
            if len(row) > MAX_COLUMNS:
                raise ImportFileError("too_many_columns", f"More than {MAX_COLUMNS} columns")
            if any(row):
                rows.append(row)
            if len(rows) > MAX_ROWS:
                raise ImportFileError("too_many_rows", f"More than {MAX_ROWS} rows")
    except csv.Error as err:  # field larger than the limit, stray quote, ...
        raise ImportFileError("unreadable", "The CSV could not be read") from err
    return rows


def read_table(data: bytes) -> Table:
    """Parse an uploaded CSV / XLSX / PDF / text file.  Nothing leaves the host.

    Only :class:`ImportFileError` escapes: any other failure is a bad file, not a server error.
    """
    try:
        return _read_table(data)
    except ImportFileError:
        raise
    except Exception as err:  # noqa: BLE001 - parser internals of csv / openpyxl / zip
        raise ImportFileError("unreadable", "The file could not be read") from err


def parse_upload(data: bytes) -> tuple[Table, list[dict[str, Any]], dict[str, int] | None]:
    """Everything CPU-bound about an upload (runs in the executor)."""
    table = read_table(data)
    try:
        candidates, mapping = rows_from_table(table)
    except Exception as err:  # noqa: BLE001
        raise ImportFileError("unreadable", "The file could not be read") from err
    return table, candidates, mapping


def _read_table(data: bytes) -> Table:
    if not data:
        raise ImportFileError("empty", "The file is empty")
    if len(data) > MAX_FILE_BYTES:
        raise ImportFileError("too_large", "The file is larger than 5 MB")
    if _PDF_MAGIC in data[:1024]:  # the header may follow a few junk bytes
        return Table(rows=[], kind="pdf", lines=_read_pdf(data))
    if data.startswith(_ZIP_MAGIC):
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise ImportFileError("unreadable", "The file could not be read")
        rows = _read_xlsx(data)
        return Table(rows=rows, kind="xlsx", lines=["\t".join(str(c) for c in r) for r in rows])
    if b"\x00" in data[:2048]:
        raise ImportFileError("unreadable", "The file is not a text, CSV or XLSX file")
    text = _decode(data)
    return Table(rows=_read_csv(text), kind="csv", lines=[ln for ln in text.splitlines() if ln.strip()])


# ---------------------------------------------------------------------------
# Column mapping
# ---------------------------------------------------------------------------


def _norm_header(value: Any) -> str:
    """Header label without units, brackets and gender suffixes ("Betrag (€)" -> "betrag")."""
    text = str(value or "").lower().replace("_", " ")
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", text)
    text = re.sub(r"[*:]in\b|[€*]", " ", text)
    text = re.sub(r"\b(?:in\s+)?(?:eur|euro)\b", " ", text)
    return " ".join(text.split())


def guess_mapping(header: list[str]) -> dict[str, int]:
    """Column index per schema field, from the header labels (de/en synonyms)."""
    labels = [_norm_header(h) for h in header]
    mapping: dict[str, int] = {}
    for name in _FIELDS:
        best: tuple[int, int] | None = None  # (synonym rank, column)
        for idx, label in enumerate(labels):
            if idx in mapping.values() or not label:
                continue
            for rank, syn in enumerate(_SYNONYMS[name]):
                if label == syn:
                    if best is None or rank < best[0]:
                        best = (rank, idx)
                    break
        if best is not None:
            mapping[name] = best[1]
    return mapping


def mapping_complete(mapping: dict[str, int]) -> bool:
    return "date" in mapping and ("amount" in mapping or ("debit" in mapping and "credit" in mapping))


def locate_header(rows: list[list[str]]) -> tuple[int, dict[str, int]] | None:
    """The first row (within the preamble limit) that maps to a complete schema."""
    for idx, row in enumerate(rows[:MAX_PREAMBLE]):
        mapping = guess_mapping(row)
        if mapping_complete(mapping):
            return idx, mapping
    return None


# ---------------------------------------------------------------------------
# Value parsing
# ---------------------------------------------------------------------------

_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%Y%m%d")


def parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.split("T")[0].split(" ")[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _cents(amount: float) -> float:
    """Round to cents, half away from zero, from the shortest decimal form (-12.345 -> -12.35)."""
    return float(Decimal(repr(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def parse_amount(value: Any) -> float | None:
    """Signed amount from "1.234,56", "-89,00", "89,00-", "1,234.56", "+12.5 EUR"."""
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    text = str(value or "").strip().replace(" ", " ")
    if not text:
        return None
    negative = bool(
        re.search(r"(^|[^\d])-\s*\d|\d\s*-$|\d\s*S$|\(", text.strip())
    )
    text = re.sub(r"[^\d.,]", "", text)
    if not text or not re.search(r"\d", text):
        return None
    if "," in text and "." in text:
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
    elif "," in text:
        decimal = "," if re.search(r",\d{1,2}$", text) and text.count(",") == 1 else ""
    elif "." in text:
        decimal = "." if re.search(r"\.\d{1,2}$", text) and text.count(".") == 1 else ""
    else:
        decimal = ""
    if decimal:
        thousands = "." if decimal == "," else ","
        text = text.replace(thousands, "").replace(decimal, ".")
    else:
        text = text.replace(".", "").replace(",", "")
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def rows_from_table(table: Table) -> tuple[list[dict[str, Any]], dict[str, int] | None]:
    """Candidate rows (unvalidated) from a table, or ``(…, None)`` when no mapping fits.

    A PDF has no columns: its mapping is ``{}`` when the booking lines were read.
    """
    if table.kind == "pdf":
        rows = rows_from_pdf_lines(table.lines)
        return (rows, {}) if rows is not None else ([], None)
    located = locate_header(table.rows)
    if located is None:
        return [], None
    head, mapping = located
    out: list[dict[str, Any]] = []
    for offset, row in enumerate(table.rows[head + 1 :], start=head + 2):
        def get(name: str, _row: list[str] = row) -> str:
            idx = mapping.get(name)
            return _row[idx] if idx is not None and idx < len(_row) else ""

        if "amount" in mapping:
            raw_amount: Any = get("amount")
        else:
            debit, credit = parse_amount(get("debit")), parse_amount(get("credit"))
            if debit is None and credit is None:
                raw_amount = ""
            else:
                raw_amount = (credit or 0.0) - abs(debit or 0.0)
        out.append(
            {
                "line": offset,
                "date": get("date"),
                "amount": raw_amount,
                "counterparty": get("counterparty"),
                "text": get("text"),
                "currency": get("currency"),
            }
        )
    return out, mapping


# ---------------------------------------------------------------------------
# PDF statements: booking lines from extracted text
# ---------------------------------------------------------------------------

# one or two leading dates (booking day, value day); the year may be missing ("01.03.")
_PDF_DATE = r"(?:\d{1,2}\.\d{1,2}\.(?:\d{4}|\d{2}(?!\d))?|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})"
_PDF_BOOKING = re.compile(rf"^({_PDF_DATE})(?:\s+{_PDF_DATE})?(?:\s+|$)(.*)$")
# money with exactly two decimals; dates ("01.03.2025") and long numbers never match
_PDF_MONEY = re.compile(
    r"(?<![\w.,/-])([+-]\s?)?((?:\d{1,3}(?:[.,'  ]\d{3})+|\d+)[.,]\d{2})"
    r"(\s?[+-](?![\w])|\s?[SH]\b)?(?:\s?(?:EUR|€))?(?![\w.,/])"
)
_PDF_FULL_DATE = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)")
_PDF_SKIP = re.compile(
    r"^(?:alter|neuer|anfangs|end)?\s*(?:kontostand|saldo)|^(?:übertrag|uebertrag|zwischensumme|summe)\b"
    r"|^(?:opening|closing|new|old)?\s*balance\b|^(?:carried|brought) forward",
    re.I,
)
_PDF_NOISE = re.compile(
    r"^(?:seite|page|blatt)\s+\d|^(?:iban|bic|kontoauszug|kontonummer|buchungstag|buchung|datum|date)\b",
    re.I,
)
_PDF_TYPES = (
    "sepa-basislastschrift", "sepa-lastschrift", "basislastschrift", "folgelastschrift",
    "erstlastschrift", "lastschrift", "sepa-überweisung", "echtzeitüberweisung", "überweisung",
    "dauerauftrag", "gutschrift", "kartenzahlung", "kartenumsatz", "zahlungseingang",
    "gehalt/rente", "gehalt", "rente", "entgelt", "abschluss", "bargeldauszahlung",
    "direct debit", "standing order", "card payment", "transfer", "credit",
)


def _pdf_tail_money(line: str) -> tuple[int, list[re.Match[str]]]:
    """The money tokens that end the line (amount, then perhaps a running balance)."""
    matches = list(_PDF_MONEY.finditer(line))
    tail: list[re.Match[str]] = []
    end = len(line.rstrip())
    for m in reversed(matches):
        if line[m.end() : end].strip():
            break
        tail.insert(0, m)
        end = m.start()
        if len(tail) == 2:
            break
    return (tail[0].start() if tail else len(line)), tail


def _pdf_sign(match: re.Match[str]) -> int:
    """-1 for a debit marker, +1 for a credit marker, 0 when the token carries none."""
    lead, trail = (match.group(1) or "").strip(), (match.group(3) or "").strip().upper()
    if lead == "-" or trail in ("-", "S"):
        return -1
    if lead == "+" or trail in ("+", "H"):
        return 1
    return 0


def _pdf_reference_date(lines: list[str]) -> date | None:
    """The statement's latest full date, for booking dates printed without a year."""
    best: date | None = None
    for line in lines:
        for d, m, y in _PDF_FULL_DATE.findall(line):
            try:
                day = date(int(y), int(m), int(d))
            except ValueError:
                continue
            best = day if best is None or day > best else best
    return best


def _pdf_date(token: str, ref: date | None, prev: date | None) -> date | str:
    """The date of a booking date token, or the token itself when it cannot be resolved.

    A yearless one ("01.03.") follows the booking before it (``prev``) and
    rolls the year over when the month jumps by more than half a year
    (Dec -> Jan); the first one takes its year from ``ref``, the statement's
    latest full date (a January statement lists December of the year before).
    """
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.", token)
    if not m:
        return parse_date(token) or token
    d, mo = int(m.group(1)), int(m.group(2))
    if prev is not None:
        year = prev.year + (1 if mo < prev.month - 6 else -1 if mo > prev.month + 6 else 0)
    elif ref is not None:
        year = ref.year - 1 if mo > ref.month else ref.year
    else:
        return token  # left unparsed: the row is listed as invalid
    try:
        return date(year, mo, d)
    except ValueError:
        return token


def _split_type(desc: str) -> tuple[str, str]:
    """``("SEPA-Lastschrift", "Stadtwerke")`` from ``"SEPA-Lastschrift Stadtwerke"``."""
    low = desc.lower()
    for word in _PDF_TYPES:
        if low.startswith(word) and (len(low) == len(word) or not low[len(word)].isalnum()):
            return desc[: len(word)], desc[len(word) :].strip(" :-,")
    return "", desc


def rows_from_pdf_lines(lines: list[str]) -> list[dict[str, Any]] | None:
    """Candidate rows from the text lines of a PDF statement, or None when the layout is unknown.

    A booking line starts with a date and ends with an amount (an optional
    running balance after it is ignored); up to ``PDF_MAX_CONTINUATION``
    lines below it are its purpose.  A booking whose amount sits on the
    next line is completed from there.

    None (-> the AI path) when no booking line is found, or when no amount
    in the whole statement carries a debit marker (``-``, trailing ``-``,
    ``S``): unsigned amounts in separate debit/credit columns cannot be told
    apart once the text is flat, and a guessed sign would import expenses
    as income.
    """
    ref = _pdf_reference_date(lines)
    prev: date | None = None
    out: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    signs: list[int] = []

    def close() -> None:
        nonlocal current
        if current is not None and current["amount"] != "":
            out.append(current)
        current = None

    for n, line in enumerate(lines, start=1):
        booking = _PDF_BOOKING.match(line)
        if booking:
            close()
            rest = booking.group(2)
            if _PDF_SKIP.search(rest):
                continue
            start, tail = _pdf_tail_money(rest)
            kind, party = _split_type(rest[:start].strip())
            day = _pdf_date(booking.group(1), ref, prev)
            if isinstance(day, date):
                prev = day
            current = {
                "line": n,
                "date": day.isoformat() if isinstance(day, date) else day,
                "amount": "",
                "counterparty": party,
                "text": kind,
                "currency": "",
                "_more": 0,
            }
            if tail:
                current["amount"] = _pdf_amount(tail[0], signs)
            continue
        if current is None:
            continue
        if _PDF_SKIP.search(line) or _PDF_NOISE.search(line):
            close()
            continue
        if current["amount"] == "":
            start, tail = _pdf_tail_money(line)
            if tail:
                current["amount"] = _pdf_amount(tail[0], signs)
                line = line[:start].strip()
        if line and current["_more"] < PDF_MAX_CONTINUATION:
            current["_more"] += 1
            if not current["counterparty"]:
                current["counterparty"] = line
            else:
                current["text"] = f"{current['text']} {line}".strip()
    close()

    if not out or -1 not in signs:
        return None
    for row in out:
        del row["_more"]  # an unsigned amount stays positive: a credit where debits are marked
    return out


def _pdf_amount(match: re.Match[str], signs: list[int]) -> Any:
    sign = _pdf_sign(match)
    signs.append(sign)
    value = parse_amount(match.group(2))
    if value is None:
        return ""
    return -abs(value) if sign < 0 else abs(value)


# ---------------------------------------------------------------------------
# Validation (local rows and AI rows alike)
# ---------------------------------------------------------------------------


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def validate_rows(
    candidates: list[Any], *, today: date
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split candidates into valid schema rows and invalid ones with a reason.

    Invalid rows are never dropped: they are returned with ``line`` and a
    machine-readable ``reason`` so the preview can list them.
    """
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for pos, cand in enumerate(candidates, start=1):
        if not isinstance(cand, dict):
            invalid.append({"line": pos, "reason": "not_an_object", "raw": _clean(cand, 80)})
            continue
        line = cand.get("line") if isinstance(cand.get("line"), int) else pos

        def bad(reason: str, _line: int = line, _cand: dict[str, Any] = cand) -> None:
            invalid.append(
                {
                    "line": _line,
                    "reason": reason,
                    "raw": _clean(f"{_cand.get('date')} | {_cand.get('amount')} | {_cand.get('counterparty')}", 120),
                }
            )

        day = parse_date(cand.get("date"))
        if day is None:
            bad("bad_date")
            continue
        if day > today or (today - day).days > MAX_AGE_DAYS:
            bad("date_out_of_range")
            continue
        amount = parse_amount(cand.get("amount"))
        if amount is None:
            bad("bad_amount")
            continue
        amount = _cents(amount)  # zero after rounding is no booking (Codex #121)
        if amount == 0 or abs(amount) >= MAX_AMOUNT:
            bad("amount_out_of_range")
            continue
        currency = _clean(cand.get("currency"), 3).upper() or "EUR"
        if currency not in CURRENCIES:
            bad("bad_currency")
            continue
        counterparty = _clean(cand.get("counterparty"), MAX_COUNTERPARTY)
        text = _clean(cand.get("text"), MAX_TEXT)
        if not counterparty and not text:
            bad("no_description")
            continue
        valid.append(
            {
                "line": line,
                "date": day.isoformat(),
                "amount": round(amount, 2),
                "counterparty": counterparty,
                "text": text,
                "currency": currency,
            }
        )
    return valid, invalid


# ---------------------------------------------------------------------------
# Duplicates against the ledger
# ---------------------------------------------------------------------------


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _same_party(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    return not a or not b or a == b or a in b or b in a


def _ledger_view(tx: dict[str, Any]) -> tuple[str, float, str] | None:
    amount = tx.get("transactionAmount") or {}
    try:
        value = float(amount.get("amount"))
    except (TypeError, ValueError):
        return None
    day = effective_date_str(tx)
    if not day:
        return None
    party = str(tx.get("creditorName") or tx.get("debtorName") or "")
    return day, round(value, 2), party


def rows_to_commit(
    preview_rows: list[dict[str, Any]], ledger_txs: list[dict[str, Any]], *, window_start: str | None
) -> list[dict[str, Any]]:
    """The previewed rows that are still ``new`` against the ledger as it is now."""
    bare = [{k: v for k, v in r.items() if k != "status"} for r in preview_rows]
    rows, _ = classify_rows(bare, ledger_txs, window_start=window_start)
    return [r for r in rows if r["status"] == "new"]


def fetch_window_start(today: date) -> str:
    """Start of the incremental bank fetch window (what the bank re-delivers)."""
    return (today - timedelta(days=DEFAULT_FETCH_DAYS)).isoformat()


def classify_rows(
    rows: list[dict[str, Any]], ledger_txs: list[dict[str, Any]], *, window_start: str | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Tag each valid row ``new`` | ``duplicate`` | ``overlap`` against the account.

    * ``duplicate``: the ledger already holds a booking with the same date,
      amount and counterparty.  Matching is one-to-one, so two genuine
      identical payments are not both swallowed by one ledger row.
    * ``overlap``: no match, but the row lies inside the bank's fetch window
      (``window_start``, see :func:`fetch_window_start`).  The bank delivers
      that span itself and its rows are authoritative there, so the row is
      not imported.
    * ``new``: older than the fetch window.
    """
    bank_start = window_start
    pool: dict[tuple[str, float], list[str]] = {}
    for t in ledger_txs:
        if t.get("_status", "booked") != "booked":
            continue
        view = _ledger_view(t)
        if view:
            pool.setdefault((view[0], view[1]), []).append(view[2])

    out: list[dict[str, Any]] = []
    for row in rows:
        status = "new"
        parties = pool.get((row["date"], row["amount"]), [])
        hit = next((i for i, p in enumerate(parties) if _same_party(p, row["counterparty"])), None)
        if hit is not None:
            parties.pop(hit)
            status = "duplicate"
        elif bank_start and row["date"] >= bank_start:
            status = "overlap"
        out.append({**row, "status": status})
    counts = {s: sum(1 for r in out if r["status"] == s) for s in ("new", "duplicate", "overlap")}
    return out, {**counts, "window_start": bank_start}


# ---------------------------------------------------------------------------
# Ledger transactions for the rows that are imported
# ---------------------------------------------------------------------------


def source_tag(batch_id: str) -> str:
    return f"import:{batch_id}"


def to_ledger_transactions(rows: list[dict[str, Any]], batch_id: str) -> list[dict[str, Any]]:
    """Bank-shaped ledger entries, tagged with the batch so it can be undone."""
    tag = source_tag(batch_id)
    out = []
    for n, row in enumerate(rows):
        expense = row["amount"] < 0
        out.append(
            {
                "_ledger_id": f"imp:{batch_id}:{n}",
                "_status": "booked",
                "_source": tag,
                "bookingDate": row["date"],
                "valueDate": row["date"],
                "transactionDate": row["date"],
                "transactionAmount": {"amount": f"{row['amount']:.2f}", "currency": row["currency"]},
                "creditorName" if expense else "debtorName": row["counterparty"],
                "remittanceInformationUnstructured": row["text"],
            }
        )
    return out


def batch_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    days = sorted(r["date"] for r in rows)
    return {"count": len(rows), "first": days[0] if days else None, "last": days[-1] if days else None}


# ---------------------------------------------------------------------------
# AI path: masking, chunking, prompt, answer parsing
# ---------------------------------------------------------------------------


def mask_sensitive(text: str) -> str:
    """IBAN-like strings and long account numbers -> placeholders, locally, before sending."""
    text = _IBAN.sub("[IBAN]", text)
    return _LONG_DIGITS.sub("[NUM]", text)


def ai_chunks(table: Table) -> list[str]:
    """The file as masked text chunks, one AI call each.  Empty when too large."""
    lines = [mask_sensitive(ln)[:600] for ln in table.lines]
    chunks = ["\n".join(lines[i : i + AI_CHUNK_LINES]) for i in range(0, len(lines), AI_CHUNK_LINES)]
    if len(chunks) > AI_MAX_CALLS:
        raise ImportFileError(
            "too_large_for_ai",
            f"The file needs more than {AI_MAX_CALLS} AI calls. Split it into smaller files.",
        )
    return chunks


def build_import_prompt(chunk: str) -> str:
    return (
        "The text below is part of a bank account statement export (any layout, any language). "
        "Extract every booking as one JSON object with exactly these keys: "
        '"date" (YYYY-MM-DD), "amount" (number, expense negative, income positive), '
        '"counterparty" (payee or payer name), "text" (purpose / reference), '
        '"currency" (ISO code, EUR if unknown). Skip headers, balances and summary lines. '
        "Answer with one JSON array of these objects and nothing else. Placeholders such as "
        "[IBAN] are intentional, keep them out of the fields.\n---\n" + chunk
    )


def parse_ai_answer(text: str) -> list[Any] | None:
    """The JSON array from a model answer (code fences tolerated), or None."""
    body = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", body, re.S)
    if fence:
        body = fence.group(1).strip()
    start, end = body.find("["), body.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(body[start : end + 1])
    except ValueError:
        return None
    return data if isinstance(data, list) else None
