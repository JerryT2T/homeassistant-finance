"""Search, filters and the optional AI query for the contracts tab (#118).

Pure and deterministic. One **filter spec** describes a view of the contract
list; the user sets it by hand (search box, chips, filter sheet) or the AI
returns it from a question. Both paths end in the same spec and the same
``apply``. ``frontend/fd-contract-filter.js`` is the JavaScript twin; the
shared cases in ``tests/fixtures/contract_filter_cases.json`` run against both,
so the two cannot drift.

Spec fields (all always present after ``validate_spec``)::

    q            free text; every word must occur in name, display name,
                 detected name or remittance text (case, umlauts, accents ignored)
    kinds        subset of contract_kind.KINDS
    statuses     subset of active | overdue | ended | candidate
    categories   life-area ids
    labels       label ids
    owners       "me" | "partner" | "shared" | a person name
    amount_min   lower bound of the monthly equivalent in EUR, or None
    amount_max   upper bound, or None
    sort         "deadline" | "amount"
    aggregate    "month" | "year" | None (which total the user asked for)

Fields inside one list are OR, different fields are AND.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from typing import Any

from .contract_kind import KIND_CONTRACT, KIND_REGULAR, KIND_IRREGULAR, KINDS

STATUSES = ("active", "overdue", "ended", "candidate")
SORTS = ("deadline", "amount")
AGGREGATES = ("month", "year")
OWNER_ME = "me"
OWNER_PARTNER = "partner"
OWNER_SHARED = "shared"
OWNER_TOKENS = (OWNER_ME, OWNER_PARTNER, OWNER_SHARED)

MAX_Q = 100
MAX_ITEMS = 20
MAX_ITEM = 60
MAX_AMOUNT = 1_000_000

# recurring.STATUS_MISSING is shown as "overdue"
_STATUS_OF_RAW = {"active": "active", "missing": "overdue", "ended": "ended"}
_OWNER_ALIASES = {"ich": OWNER_ME, "wir": OWNER_SHARED, "haushalt": OWNER_SHARED,
                  "household": OWNER_SHARED}
_NO_NOTICE = (KIND_REGULAR, KIND_IRREGULAR)
_COMBINING = re.compile(r"[̀-ͯ]")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def default_spec() -> dict[str, Any]:
    return {
        "q": "",
        "kinds": [],
        "statuses": [],
        "categories": [],
        "labels": [],
        "owners": [],
        "amount_min": None,
        "amount_max": None,
        "sort": "deadline",
        "aggregate": None,
    }


def fold(text: Any) -> str:
    """Lower case without accents; ``ß`` -> ``ss``. Mirrors ``fold`` in the JS twin."""
    s = unicodedata.normalize("NFKD", str(text or "").lower())
    return _COMBINING.sub("", s).replace("ß", "ss")


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def _err(errors: list[dict[str, str]], field: str, reason: str, value: Any = None) -> None:
    item = {"field": field, "reason": reason}
    if value is not None:
        item["value"] = str(value)[:MAX_ITEM]
    errors.append(item)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0 or value > MAX_AMOUNT:
        return None
    return float(value)


def _items(
    raw: Any, field: str, allowed: Any, errors: list[dict[str, str]]
) -> list[str]:
    """Valid, de-duplicated members of a list field; the rest goes to ``errors``.

    ``allowed`` is a collection of accepted values, a mapping folded alias ->
    value, or None (any short string).
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        _err(errors, field, "not_a_list")
        return []
    out: list[str] = []
    for item in raw[:MAX_ITEMS]:
        if not isinstance(item, str) or not item.strip() or len(item) > MAX_ITEM:
            _err(errors, field, "invalid_value", item if isinstance(item, str) else None)
            continue
        value = item.strip()
        if allowed is not None:
            if isinstance(allowed, dict):
                value = allowed.get(fold(value))
            elif value not in allowed:
                value = None
            if value is None:
                _err(errors, field, "unknown_value", item)
                continue
        if value not in out:
            out.append(value)
    if len(raw) > MAX_ITEMS:
        _err(errors, field, "too_many")
    return out


def validate_spec(
    raw: Any, vocab: dict[str, Any] | None = None
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """``(spec, errors)``: every valid part is kept, every invalid one dropped and reported.

    Never raises. ``vocab`` (optional) narrows categories, labels and owners to
    what exists: ``{"categories": {ids}, "labels": {id: name}, "owners": {names}}``;
    labels and owners are also matched by name / case-insensitively.
    """
    spec = default_spec()
    errors: list[dict[str, str]] = []
    if not isinstance(raw, dict):
        _err(errors, "_", "not_an_object")
        return spec, errors
    for key in raw:
        if key not in spec:
            _err(errors, str(key)[:MAX_ITEM], "unknown_field")

    q = raw.get("q")
    if q is not None:
        if isinstance(q, str):
            spec["q"] = " ".join(q.split())[:MAX_Q]
        else:
            _err(errors, "q", "invalid_value")

    spec["kinds"] = _items(raw.get("kinds"), "kinds", KINDS, errors)
    spec["statuses"] = _items(raw.get("statuses"), "statuses", STATUSES, errors)

    v = vocab or {}
    cats = v.get("categories")
    spec["categories"] = _items(raw.get("categories"), "categories", cats, errors)
    labels = v.get("labels")
    label_map = None
    if labels is not None:
        label_map = {fold(i): i for i in labels}
        label_map.update({fold(n): i for i, n in labels.items() if n})
    spec["labels"] = _items(raw.get("labels"), "labels", label_map, errors)
    owners = v.get("owners")
    owner_map = None
    if owners is not None:
        owner_map = {fold(o): o for o in owners}
        owner_map.update({fold(t): t for t in OWNER_TOKENS})
        owner_map.update(_OWNER_ALIASES)
    found = _items(raw.get("owners"), "owners", owner_map, errors)
    if owner_map is None:  # no vocabulary: only the spoken aliases are translated
        found = [_OWNER_ALIASES.get(fold(o), o) for o in found]
    spec["owners"] = list(dict.fromkeys(found))

    lo = hi = None
    for name in ("amount_min", "amount_max"):
        value = raw.get(name)
        if value is None:
            continue
        number = _number(value)
        if number is None:
            _err(errors, name, "invalid_value", value if isinstance(value, str) else None)
        elif name == "amount_min":
            lo = number
        else:
            hi = number
    if lo is not None and hi is not None and lo > hi:
        _err(errors, "amount_max", "below_min")
        hi = None
    spec["amount_min"], spec["amount_max"] = lo, hi

    sort = raw.get("sort")
    if sort in SORTS:
        spec["sort"] = sort
    elif sort is not None:
        _err(errors, "sort", "invalid_value", sort if isinstance(sort, str) else None)

    agg = raw.get("aggregate")
    if agg in AGGREGATES:
        spec["aggregate"] = agg
    elif agg is not None:
        _err(errors, "aggregate", "invalid_value", agg if isinstance(agg, str) else None)
    return spec, errors


def is_default(spec: dict[str, Any]) -> bool:
    base = default_spec()
    return all(spec.get(k) == v for k, v in base.items() if k not in ("sort", "aggregate"))


# --------------------------------------------------------------------------
# Applying
# --------------------------------------------------------------------------


def status_of(item: dict[str, Any]) -> str:
    """Filter status of one contract: active, overdue, ended or candidate."""
    raw = _STATUS_OF_RAW.get(str(item.get("status") or "active"), "active")
    if item.get("candidate") and raw != "ended":
        return "candidate"
    return raw


def _kind_of(item: dict[str, Any]) -> str:
    return item.get("kind") or KIND_CONTRACT


def _monthly(item: dict[str, Any]) -> float:
    return abs(float(item.get("monthly_equivalent") or 0))


def _haystack(item: dict[str, Any]) -> str:
    parts = [item.get("display_name"), item.get("creditor"), item.get("display_name_detected")]
    rem = item.get("remittance")
    if isinstance(rem, list):
        parts.extend(rem)
    return fold(" ".join(str(p) for p in parts if p))


def _owner_set(owners: list[str], me: str | None, persons: Any) -> set[str]:
    out: set[str] = set()
    for o in owners:
        if o == OWNER_ME:
            if me:
                out.add(me)
        elif o == OWNER_PARTNER:
            out.update(p for p in persons if p and p != me and p != OWNER_SHARED)
        else:
            out.add(o)
    return out


def apply(
    contracts: list[dict[str, Any]],
    spec: dict[str, Any],
    *,
    me: str | None = None,
    persons: Any = (),
) -> dict[str, Any]:
    """``{"items": [...], "totals": {...}}`` for a validated spec.

    ``me`` is the logged-in user's person, ``persons`` every person of the
    household; they resolve the owner tokens "me" and "partner".
    """
    words = fold(spec.get("q")).split()
    kinds, cats, labels = spec["kinds"], spec["categories"], spec["labels"]
    statuses = spec["statuses"]
    owners = _owner_set(spec["owners"], me, persons) if spec["owners"] else None
    lo, hi = spec["amount_min"], spec["amount_max"]
    wanted = set(statuses) if statuses else {"active", "overdue", "ended"}

    shown = []
    for c in contracts:
        if status_of(c) not in wanted:
            continue
        if kinds and _kind_of(c) not in kinds:
            continue
        if cats and c.get("category") not in cats:
            continue
        if labels and not set(labels) & set(c.get("labels") or []):
            continue
        if owners is not None and c.get("owner") not in owners:
            continue
        m = _monthly(c)
        if (lo is not None and m < lo) or (hi is not None and m > hi):
            continue
        if words:
            hay = _haystack(c)
            if not all(w in hay for w in words):
                continue
        shown.append(c)

    def name(c: dict[str, Any]) -> str:
        return fold(c.get("display_name") or c.get("creditor"))

    def ended(c: dict[str, Any]) -> int:
        return 1 if status_of(c) == "ended" else 0

    if spec["sort"] == "amount":
        shown.sort(key=lambda c: (ended(c), -_monthly(c), name(c), str(c.get("id"))))
    else:
        shown.sort(
            key=lambda c: (ended(c), c.get("next_deadline") is None,
                           str(c.get("next_deadline") or ""), name(c), str(c.get("id")))
        )
    return {"items": shown, "totals": totals(shown, explicit_status=bool(statuses))}


def totals(items: list[dict[str, Any]], *, explicit_status: bool = False) -> dict[str, Any]:
    """Monthly / yearly sums of a filtered set, split like ``contract_totals`` (#115).

    Without an explicit status filter ended contracts do not count (they are
    only listed); candidates only appear when the user asked for them.
    """
    out = {g: {"monthly": 0.0, "yearly": 0.0, "count": 0} for g in ("fixed", "regular")}
    for c in items:
        if not explicit_status and status_of(c) == "ended":
            continue
        group = out["regular" if _kind_of(c) in _NO_NOTICE else "fixed"]
        yearly = c.get("annual_total", c.get("annual_cost"))
        group["yearly"] = round(group["yearly"] + float(yearly or 0), 2)
        group["count"] += 1
    for g in out.values():
        g["monthly"] = round(g["yearly"] / 12, 2)
    out["yearly"] = round(out["fixed"]["yearly"] + out["regular"]["yearly"], 2)
    out["monthly"] = round(out["yearly"] / 12, 2)
    out["count"] = out["fixed"]["count"] + out["regular"]["count"]
    return out


# --------------------------------------------------------------------------
# AI query (purpose "contract_query")
# --------------------------------------------------------------------------

_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{3,4}){3,8}\b", re.I)
_LONG_NUM = re.compile(r"\d[\d.,\s]{4,}\d")
MAX_QUESTION = 200
QUERY_MAX_TOKENS = 400

_CATEGORY_HINTS = {
    "housing_cold": "rent, mortgage, house insurance",
    "housing_warm": "energy, heating, water",
    "groceries": "food, household goods",
    "mobility": "car, fuel, public transport",
    "health": "health, insurance, doctor, pharmacy",
    "leisure": "leisure, sport, restaurants",
    "media": "phone, internet, streaming, press",
    "finance": "loans, savings, fees",
    "other": "everything else",
}


def clean_question(text: Any) -> str:
    """The user's question, without IBANs and long numbers; amounts like "50" stay."""
    s = str(text or "")
    for pattern in (_IBAN, _LONG_NUM):
        s = pattern.sub(" ", s)
    return " ".join(s.split())[:MAX_QUESTION]


def build_query_prompt(question: str, vocab: dict[str, Any]) -> str:
    """The ONLY thing sent for ``contract_query``: the question plus allowed names.

    ``vocab``: ``categories`` (ids), ``labels`` ({id: name}), ``owners`` (person
    names). No amounts, IBANs, dates, bookings or contract names.
    """
    cats = "; ".join(
        f"{c} ({_CATEGORY_HINTS[c]})" if c in _CATEGORY_HINTS else c for c in vocab["categories"]
    )
    labels = ", ".join(sorted({n or i for i, n in vocab["labels"].items()}))
    people = ", ".join(sorted(vocab["owners"]))
    return (
        "Turn a question about a household's recurring payments (contracts, subscriptions) into a "
        "JSON filter. Answer with one JSON object only, no text around it. Leave out fields the "
        "question does not mention.\n"
        'Fields: "q" (search words in a name), '
        f'"kinds" (any of {", ".join(KINDS)}), '
        f'"statuses" (any of {", ".join(STATUSES)}), '
        '"categories" (from the list below), "labels" (from the list below), '
        '"owners" ("me" for I/my, "shared" for we/household/joint, "partner" for the other '
        "person, or a person name from the list), "
        '"amount_min" and "amount_max" (EUR per month, numbers), '
        f'"sort" (any of {", ".join(SORTS)}), "aggregate" ("month" or "year" when a total is asked).\n'
        f"Categories: {cats}\nLabels: {labels or '-'}\nPersons: {people or '-'}\n"
        f"Question: {clean_question(question)}"
    )


def parse_answer(text: Any) -> Any:
    """The JSON object in an AI answer (code fences and chatter tolerated), else None."""
    s = _FENCE.sub("", str(text or "").strip())
    for candidate in (s, s[s.find("{") : s.rfind("}") + 1] if "{" in s else ""):
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return None
