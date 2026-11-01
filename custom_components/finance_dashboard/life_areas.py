"""Life areas: the category taxonomy (#112).

Every expense lands in exactly one of eight mutually exclusive life areas;
income has its own set. ``other`` is "not known yet" (the question flow asks),
``transfers`` is a system status for money moved between own accounts, not a
category of spending.

The legacy taxonomy (housing, food, utilities, ...) mixed purpose and payment
type. ``migrate_slug`` maps a legacy slug to its life area; the ambiguous ones
(utilities held both energy and telecom, food both groceries and restaurants)
are split by fixed keywords on the text that belongs to the value. What no
keyword places becomes ``other`` - never a guess.
"""

from __future__ import annotations

import re

HOUSING_COLD = "housing_cold"
HOUSING_WARM = "housing_warm"
GROCERIES = "groceries"
MOBILITY = "mobility"
HEALTH = "health"
LEISURE = "leisure"
MEDIA = "media"
FINANCE = "finance"

LIFE_AREAS: tuple[str, ...] = (
    HOUSING_COLD,
    HOUSING_WARM,
    GROCERIES,
    MOBILITY,
    HEALTH,
    LEISURE,
    MEDIA,
    FINANCE,
)

INCOME_WORK = "income_work"
INCOME_STATE = "income_state"
INCOME_CAPITAL = "income_capital"
INCOME_REFUND = "income_refund"
INCOME_PRIVATE = "income_private"

INCOME_AREAS: tuple[str, ...] = (
    INCOME_WORK,
    INCOME_STATE,
    INCOME_CAPITAL,
    INCOME_REFUND,
    INCOME_PRIVATE,
)

OTHER = "other"
TRANSFERS = "transfers"

# Slugs the categorizer may write. Order matters nowhere but the UI.
ALL_CATEGORIES: tuple[str, ...] = (*LIFE_AREAS, *INCOME_AREAS, OTHER, TRANSFERS)

# Areas whose spending is bound by a contract more often than not.
CONTRACT_AREAS = frozenset({HOUSING_COLD, HOUSING_WARM, MEDIA, FINANCE})
# Spending that recurs by habit, not by contract.
EVERYDAY_AREAS = frozenset({GROCERIES, LEISURE})


def is_income(category: str | None) -> bool:
    """Any income area (and the legacy ``income`` slug)."""
    return bool(category) and (category == "income" or str(category).startswith("income_"))


def is_spending(category: str | None) -> bool:
    """A life area or ``other`` - what counts as an expense."""
    return category in LIFE_AREAS or category == OTHER


def _words(*words: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z0-9äöüß])(" + "|".join(words) + r")", re.IGNORECASE)


# Fixed keyword splits. Each pattern matches at a word start, so "gas" never
# hits "Gastro" only because the pattern says "gas(?!t)".
_WARM = _words(
    r"strom", r"gas(?!t)", r"erdgas", r"wasser", r"abwasser", r"fernwärme", r"fernwaerme",
    r"heiz\w*", r"nebenkosten", r"betriebskosten", r"abschlag\w*", r"energie\w*",
    r"stadtwerke", r"vattenfall", r"e\.on", r"eon\b", r"enbw", r"rwe\b", r"eprimo",
    r"evm\b", r"müll\w*", r"muell\w*", r"abfall\w*",
)
_MEDIA = _words(
    r"telekom", r"vodafone", r"o2\b", r"telef[oó]nica", r"1&1", r"1und1", r"congstar",
    r"mobilcom", r"drillisch", r"winsim", r"klarmobil", r"freenet", r"otelo",
    r"aldi talk", r"ja!mobil", r"pyur", r"unitymedia", r"kabel\w*", r"dsl\b",
    r"glasfaser", r"internet", r"mobilfunk", r"handy\w*", r"festnetz",
    r"rundfunk\w*", r"beitragsservice", r"ard zdf", r"gez\b",
)
_GASTRO = _words(
    r"restaurant\w*", r"gastro\w*", r"caf[eé]\b", r"bistro", r"pizza\w*", r"pizzeria",
    r"döner", r"doner", r"imbiss", r"mcdonald\w*", r"burger king", r"subway",
    r"starbucks", r"domino\w*", r"lieferando", r"uber eats", r"wolt\b", r"bar\b",
)
_HOUSEHOLD = _words(
    r"dm\b", r"dm[- ]drogerie", r"rossmann", r"müller drogerie", r"muller drogerie",
    r"drogerie\w*", r"ikea", r"obi\b", r"bauhaus", r"hornbach", r"toom\b", r"action\b",
    r"tedi\b", r"depot\b", r"haushalt\w*", r"putz\w*", r"reinigung\w*",
)
_HOME_INSURANCE = _words(r"hausrat\w*", r"wohngebäude\w*", r"wohngebaeude\w*", r"gebäude\w*")
_CAR = _words(r"kfz\w*", r"auto\w*", r"fahrzeug\w*", r"kasko\w*")
_FITNESS = _words(
    r"fitness\w*", r"mcfit", r"urban sports", r"john reebok", r"gym\b", r"sportverein",
    r"verein\w*",
)
_MORTGAGE = _words(
    r"baufinanz\w*", r"hypothek\w*", r"immobilien\w*", r"bauspar\w*", r"wohnungsbau\w*",
)
_STATE = _words(
    r"kindergeld", r"elterngeld", r"wohngeld", r"bafög", r"bafoeg", r"rente\w*",
    r"bundesagentur", r"agentur für arbeit", r"arbeitslosengeld", r"familienkasse",
    r"finanzamt", r"steuererstattung", r"krankengeld", r"pflegegeld",
)
_CAPITAL = _words(r"zins\w*", r"dividende\w*", r"ausschüttung\w*", r"ertrag\w*", r"kupon")
_REFUND = _words(
    r"erstattung\w*", r"rückerstattung\w*", r"rueckerstattung\w*", r"gutschrift\w*", r"storno\w*",
    r"retoure\w*", r"refund\w*", r"rückzahlung\w*", r"rueckzahlung\w*",
)
_WORK = _words(r"gehalt\w*", r"lohn\w*", r"salary", r"bezüge", r"vergütung\w*", r"honorar\w*")


# Insurers and health funds: under health they are a contract, not a doctor.
INSURER = re.compile(
    r"(?<![a-z0-9äöüß])(\w*versicher\w*|krankenkasse|pflegekasse|police|tk|aok|barmer|dak"
    r"|ikk|hkk|bkk\w*|allianz|huk\w*|devk|ergo|axa|debeka|signal iduna|hansemerkur"
    r"|generali|cosmosdirekt)(?![a-z0-9äöüß])",
    re.IGNORECASE,
)


def _first(text: str, splits: tuple[tuple[re.Pattern[str], str], ...]) -> str | None:
    for pattern, area in splits:
        if pattern.search(text):
            return area
    return None


def _income_area(text: str, default: str) -> str:
    splits = (
        (_STATE, INCOME_STATE),
        (_CAPITAL, INCOME_CAPITAL),
        (_REFUND, INCOME_REFUND),
        (_WORK, INCOME_WORK),
    )
    return _first(text, splits) or default


# legacy slug -> (keyword splits in priority order, area when no keyword hits)
_LEGACY: dict[str, tuple[tuple[tuple[re.Pattern[str], str], ...], str]] = {
    "housing": (((_WARM, HOUSING_WARM),), HOUSING_COLD),
    "utilities": (((_MEDIA, MEDIA), (_WARM, HOUSING_WARM)), OTHER),
    "telecom": ((), MEDIA),
    "food": (((_GASTRO, LEISURE),), GROCERIES),
    "shopping": (((_HOUSEHOLD, GROCERIES),), OTHER),
    "cleaning": ((), GROCERIES),
    "transport": ((), MOBILITY),
    "insurance": (((_HOME_INSURANCE, HOUSING_COLD), (_CAR, MOBILITY)), HEALTH),
    "subscriptions": (((_FITNESS, LEISURE),), MEDIA),
    "loans": (((_MORTGAGE, HOUSING_COLD),), FINANCE),
    "gastro": ((), LEISURE),
    "entertainment": ((), LEISURE),
}

LEGACY_SLUGS = frozenset({*_LEGACY, "income"})


def migrate_slug(slug: str | None, text: str = "") -> str | None:
    """The life area for a legacy ``slug``; anything else is returned unchanged.

    ``text`` is what belongs to the value (merchant, remittance, position
    name) and decides the keyword splits. Idempotent: a life area, an income
    area, ``other``, ``transfers`` and unknown custom slugs pass through.
    """
    if not slug:
        return slug
    if slug == "income":
        return _income_area(text, INCOME_WORK)
    rule = _LEGACY.get(slug)
    if rule is None:
        return slug
    splits, default = rule
    return _first(text, splits) or default


def migrate_targets(slug: str) -> tuple[str, ...]:
    """Every area a legacy slug can land in (for a key set such as a pot's)."""
    if slug == "income":
        return INCOME_AREAS
    rule = _LEGACY.get(slug)
    if rule is None:
        return (slug,)
    splits, default = rule
    areas = [area for _p, area in splits]
    if default != OTHER:
        areas.insert(0, default)
    return tuple(dict.fromkeys(areas)) or (default,)


def is_refund(text: str) -> bool:
    """A refund or credit note in the booking text."""
    return bool(_REFUND.search(text))


def income_area_for(text: str) -> str:
    """Income area of a booking text; unrecognised money from a person is private."""
    return _income_area(text, INCOME_PRIVATE)
