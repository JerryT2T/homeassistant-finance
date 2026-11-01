"""Transaction auto-categorizer.

Uses rule-based pattern matching to classify banking transactions
into budget categories. Users can customize rules via the UI.

No ML/AI dependencies — pure keyword matching for reliability and
transparency. Categories are deterministic and auditable.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .const import CATEGORIZATION_RULES, CATEGORY_OTHER
from .life_areas import INCOME_REFUND, income_area_for, is_income, is_refund
from .text_norm import is_processor_only, processor_remittance

_LOGGER = logging.getLogger(__name__)

# German-retail keywords on top of ``CATEGORIZATION_RULES``.  Appended after the
# base rules of the same area, so the base order (and its priorities) never
# changes.  General retail (Amazon, eBay, fashion, electronics) has no life
# area of its own: it stays ``other`` and the question flow asks (#112).
EXTRA_RULES: dict[str, list[str]] = {
    "housing_cold": ["mietpool", "warmmiete", "kaltmiete", "grundsteuer", "hausverwaltung"],
    "housing_warm": [
        "vattenfall", "eon ", "e.on", "enbw", "rwe", "stadtwerke", "evm", "eprimo",
        "fernwärme", "müllabfuhr", "abfallwirtschaft",
    ],
    "media": [
        "telefónica", "telefonica", "1&1", "1und1", "congstar", "o2 ", "mobilcom",
        "drillisch", "winsim", "klarmobil", "freenet", "otelo", "aldi talk", "ja!mobil",
        "rundfunk", "beitragsservice", "ard zdf", "pyur", "unitymedia",
        "kabel deutschland", "apple.com/bill", "apple services", "dazn", "sky ", "wow ",
        "rtl+", "joyn", "audible", "applemusic", "apple music", "disneyplus", "paramount",
        "crunchyroll", "openai", "chatgpt", "github", "dropbox", "microsoft 365", "adobe",
        "patreon", "playstation", "nintendo", "steam", "twitch", "zeit online", "spiegel+",
        "nordvpn", "1password",
    ],
    "groceries": [
        "netto marken", "denn's", "denns", "alnatura", "bäckerei", "baeckerei", "bakery",
        "metzger", "fleischerei", "markthalle", "flink", "gorillas", "too good to go",
        "dm drogerie", "dm-drogerie", "dm fil", "rossmann", "müller drogerie",
        "muller drogerie", "ikea", "obi ", "bauhaus", "hornbach", "toom", "action ",
        "tedi", "depot",
    ],
    "leisure": [
        "mcdonald", "burger king", "subway", "starbucks", "dominos", "domino's", "pizza",
        "pizzeria", "döner", "doner", "cafe", "café", "bistro", "gastro", "wolt",
        "kino", "cinemaxx", "cineplex", "theater", "konzert", "eventim", "ticketmaster",
        "fitness", "mcfit", "urban sports", "john reebok", "schwimmbad", "freizeitpark",
        "booking.com", "bookingkit", "airbnb", "ryanair", "lufthansa", "eurowings",
        "easyjet", "hotel", "tui ", "museum", "zoo ",
    ],
    "mobility": [
        "esso", "total energies", "totalenergies", "jet tank", "hem tank",
        "flixbus", "bolt", "freenow", "free now", "sixt", "parkhaus", "parkgebühr",
        "kvb", "bvg", "rmv", "vrs", "mvg", "hvv", "lime", "tier mobility",
    ],
    "health": [
        "allianz", "huk", "devk", "ergo", "axa", "generali", "signal iduna", "debeka",
        "hdi", "versicherungskammer", "r+v", "ruv", "techniker krankenkasse", "dak",
        "ikk", "hansemerkur", "cosmosdirekt", "check24 versicherung",
        "apotheke", "apothek", "docmorris", "shop-apotheke", "arzt", "zahnarzt",
        "praxis", "klinik", "krankenhaus", "optiker", "fielmann", "apollo", "physio",
        "sanitätshaus", "sanitaetshaus", "labor ",
    ],
}

_WORD_MAX = 3  # keywords this short (after stripping) are whole words ("gez" never hits "gezahlt")


def _kw_match(keyword: str, haystack: str) -> bool:
    """Keyword hit; short keywords ("gas", "dm", "o2") must be whole words."""
    kw = keyword.lower().strip()
    if not kw:
        return False
    if len(kw) <= _WORD_MAX:
        tail = "(?![a-z0-9äöüß])"
        return re.search(rf"(?<![a-z0-9äöüß]){re.escape(kw)}{tail}", haystack) is not None
    return kw in haystack


class TransactionCategorizer:
    """Categorize banking transactions by keyword matching."""

    def __init__(
        self,
        custom_rules: dict[str, list[str]] | None = None,
        memory: Any | None = None,
    ) -> None:
        """Initialize with default + optional custom rules.

        ``memory`` is a :class:`merchants.MerchantMemory`; its corrections
        (one-off booking answers, then learned merchants) outrank keywords.
        """
        self._memory = memory
        self._rules = {k: list(v) for k, v in CATEGORIZATION_RULES.items()}
        if custom_rules:
            for category, keywords in custom_rules.items():
                existing = self._rules.get(category, [])
                self._rules[category] = list(set(existing + keywords))
        for category, keywords in EXTRA_RULES.items():
            merged = self._rules.get(category, [])
            self._rules[category] = merged + [k for k in keywords if k not in merged]

    def categorize(self, transaction: dict[str, Any]) -> str:
        """Categorize a single transaction.

        Checks remittance info, creditor name, and debtor name
        against keyword patterns.

        Args:
            transaction: Transaction object (normalized format)

        Returns:
            Category slug (a life area, an income area, 'transfers' or 'other')
        """
        return self.resolve(transaction)[0]

    def resolve(self, transaction: dict[str, Any]) -> tuple[str, str | None]:
        """Run the chain; returns ``(category, owner_override)``.

        Order: user corrections / merchant memory -> keyword rules -> income
        fallback (positive amount) -> ``other``.
        """
        if self._memory is not None:
            rule = self._memory.resolve(transaction)
            if rule and rule.get("category"):
                return str(rule["category"]), rule.get("owner") or None
        return self._by_keywords(transaction), None

    def _by_keywords(self, transaction: dict[str, Any]) -> str:
        # Extract searchable text from transaction
        search_text = self._processor_text(transaction)
        if search_text is None:
            search_text = self._extract_searchable_text(transaction)
        if not search_text:
            return CATEGORY_OTHER

        search_lower = search_text.lower()

        # Check amount direction for income detection
        amount = float(transaction.get("transactionAmount", {}).get("amount", 0))

        # Money coming in: income rules first, then a refund, only then the
        # areas (a shop's credit nets in its area). Income rules never match
        # money going out ("Zinsen" on a loan is a cost).
        if amount > 0:
            for category, keywords in self._rules.items():
                if is_income(category) and any(_kw_match(k, search_lower) for k in keywords):
                    return category
            if is_refund(search_lower):
                return INCOME_REFUND
        for category, keywords in self._rules.items():
            if is_income(category):
                continue
            for keyword in keywords:
                if _kw_match(keyword, search_lower):
                    return category

        # Fallback: positive amounts without category -> an income area
        if amount > 0:
            return income_area_for(search_lower)

        return CATEGORY_OTHER

    def update_rules(self, category: str, keywords: list[str]) -> None:
        """Add or update categorization rules for a category."""
        existing = self._rules.get(category, [])
        self._rules[category] = list(set(existing + keywords))

    def get_rules(self) -> dict[str, list[str]]:
        """Get current categorization rules (deep copy — mutations are safe)."""
        return {category: list(keywords) for category, keywords in self._rules.items()}

    @staticmethod
    def _processor_text(transaction: dict[str, Any]) -> str | None:
        """Text to search for a processor-only line, None for any other line.

        The processor's own name ("PayPal Europe ...") never decides the
        category: only the remittance (the merchant, the order) does. Nothing
        recognisable -> "" -> ``other``, which the question flow picks up.
        """
        try:
            amount = float((transaction.get("transactionAmount") or {}).get("amount", 0) or 0)
        except (TypeError, ValueError):
            amount = 0.0
        names = (transaction.get("creditorName"), transaction.get("debtorName"))
        name = (names[0] or names[1]) if amount <= 0 else (names[1] or names[0])
        if not is_processor_only(str(name or "")):
            return None
        remittance = str(transaction.get("remittanceInformationUnstructured") or "")
        return processor_remittance(remittance)

    @staticmethod
    def _extract_searchable_text(
        transaction: dict[str, Any],
    ) -> str:
        """Extract all searchable text fields from a transaction."""
        parts = []

        # Remittance information (payment reference)
        remittance = transaction.get("remittanceInformationUnstructured", "")
        if remittance:
            parts.append(remittance)

        remittance_array = transaction.get("remittanceInformationUnstructuredArray", [])
        if remittance_array:
            parts.extend(remittance_array)

        # Creditor (who receives money)
        creditor = transaction.get("creditorName", "")
        if creditor:
            parts.append(creditor)

        # Debtor (who sends money)
        debtor = transaction.get("debtorName", "")
        if debtor:
            parts.append(debtor)

        # Additional info
        additional = transaction.get("additionalInformation", "")
        if additional:
            parts.append(additional)

        return " ".join(parts)
