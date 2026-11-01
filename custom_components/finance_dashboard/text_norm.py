"""Name normalisation shared by series detection and contract ids.

Banks change how they spell a payee: a legal form appears or drops away, the
punctuation moves, or a UTF-8 name arrives decoded as Latin-1 ("S.Ã  r.l."
for "S.à r.l."). ``canonical_name`` maps all of those to one key, so a payee
keeps one series and one contract id.
"""

from __future__ import annotations

import re
import unicodedata

_MOJIBAKE_MARKERS = ("Ã", "Â", "â€")
_LEGAL_FORMS = {
    "gmbh", "mbh", "ag", "kg", "ohg", "ug", "se", "eg", "ev", "gbr", "kgaa", "co",
    "inc", "ltd", "llc", "plc", "bv", "nv", "sa", "sarl", "sas", "sca", "cie", "et",
}
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def repair_mojibake(text: str) -> str:
    """Undo UTF-8 text that was decoded as Latin-1 / cp1252; drop U+FFFD."""
    if not text:
        return ""
    fixed = text
    if any(m in text for m in _MOJIBAKE_MARKERS):
        for codec in ("cp1252", "latin-1"):
            try:
                fixed = text.encode(codec).decode("utf-8")
                break
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
    return fixed.replace("�", "")


def canonical_name(name: str) -> str:
    """Spelling-independent key of a counterparty name ("" for no name)."""
    repaired = " ".join(repair_mojibake(name or "").lower().split())
    text = unicodedata.normalize("NFKD", repaired.translate(_UMLAUTS))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    # dotted legal forms are one token each ("s.à r.l.", "s.c.a.", "e.v."), so
    # the single letters of a real name ("Apotheke A", "Kita 1") stay apart
    text = re.sub(r"\bs\.?\s?a\.?\s?r\.?\s?l\b\.?", " sarl ", text)
    text = re.sub(r"\b([a-z])\.(?=[a-z](?:\.|\b))", r"\1", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [t for t in text.split() if t not in _LEGAL_FORMS]
    # a name without latin letters or digits (Cyrillic, Greek) keeps itself
    return " ".join(tokens) or " ".join(text.split()) or repaired


# Payment processors: their own name says how something was paid, never what.
_PROCESSOR_BRANDS = {
    "paypal", "pp", "klarna", "sumup", "ratepay", "afterpay", "clearpay", "stripe",
    "adyen", "mollie", "unzer", "payone", "zettle", "square", "sq",
}
_PROCESSOR_FILLER = {
    "europe", "bank", "payments", "payment", "services", "deutschland", "de", "ab",
    "international", "luxembourg", "s", "a", "r", "l", "c",
}
_PROCESSOR_REF = re.compile(r"\bpp\.\d+\.pp\b\s*\.?", re.IGNORECASE)
_PROCESSOR_MERCHANT = re.compile(
    r"(?:ihr einkauf bei|einkauf bei|purchase at|zahlung an)\s+([^,;/]+)", re.IGNORECASE
)


def is_processor_only(name: str) -> bool:
    """The counterparty is a payment processor itself ("PayPal Europe S.a r.l.").

    A processor name that still carries the merchant ("PAYPAL *BOOKINGKIT")
    is not: its merchant is right there in the name.
    """
    tokens = set(canonical_name(name).split())
    return bool(tokens & _PROCESSOR_BRANDS) and tokens <= _PROCESSOR_BRANDS | _PROCESSOR_FILLER


def processor_merchant_text(remittance: str) -> str:
    """Merchant part of a processor line's remittance ("" when none is named).

    "PP.4471.PP . Streamly Media, Ihr Einkauf bei Streamly Media" -> "Streamly Media".
    """
    text = repair_mojibake(remittance or "")
    match = _PROCESSOR_MERCHANT.search(text)
    if match:
        return match.group(1).strip(" .")
    rest = _PROCESSOR_REF.sub(" ", text)
    if rest != text:  # "PP.1234.PP . Merchant, ..." -> the part before the comma
        return rest.split(",", 1)[0].strip(" .")
    return ""


def processor_remittance(remittance: str) -> str:
    """Remittance of a processor line without the processor's own references."""
    return " ".join(_PROCESSOR_REF.sub(" ", repair_mojibake(remittance or "")).split())
