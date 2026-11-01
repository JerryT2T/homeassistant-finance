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
