"""Demo data generator for Finance Dashboard.

Generates realistic German banking data for demo/testing purposes.
All data is synthetic — no real financial information.

Each call to generate_demo_data() produces a complete, randomized dataset
that matches the exact shape the frontend expects (unified data object).
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any

from .life_areas import migrate_slug
from .tx_dates import effective_date_str

# ---------------------------------------------------------------------------
# Demo bank accounts
# ---------------------------------------------------------------------------

DEMO_ACCOUNTS_CONFIG: list[dict[str, Any]] = [
    {
        "id": "demo-sparkasse-anna",
        "iban": "DE89370400440532013000",
        "name": "Girokonto",
        "custom_name": "Anna Sparkasse",
        "institution": "Sparkasse",
        "institution_id": "SPARKASSE_DE",
        "logo": "",
        "currency": "EUR",
        "type": "personal",
        "person": "Anna",
        "ha_users": [],
    },
    {
        "id": "demo-dkb-max",
        "iban": "DE27100110012621953188",
        "name": "Girokonto",
        "custom_name": "Max DKB",
        "institution": "DKB",
        "institution_id": "DKB_DE",
        "logo": "",
        "currency": "EUR",
        "type": "personal",
        "person": "Max",
        "ha_users": [],
    },
    {
        "id": "demo-ing-shared",
        "iban": "DE60500105175418543281",
        "name": "Gemeinschaftskonto",
        "custom_name": "Haushaltskonto",
        "institution": "ING",
        "institution_id": "ING_DE",
        "logo": "",
        "currency": "EUR",
        "type": "shared",
        "person": "",
        "ha_users": [],
    },
]

# Base balances per account (randomized ±15%)
_BASE_BALANCES = {
    "demo-sparkasse-anna": 3250.00,
    "demo-dkb-max": 2180.00,
    "demo-ing-shared": 1520.00,
}

# ---------------------------------------------------------------------------
# Transaction templates — amounts are jittered at generation time
# ---------------------------------------------------------------------------

_TRANSACTION_TEMPLATES: list[dict[str, Any]] = [
    # --- Shared account (ING) ---
    {
        "creditor": "Hausverwaltung GmbH",
        "desc": "Miete {month_name} {year}",
        "base": -1150.0,
        "cat": "housing",
        "day": 1,
        "acc": "demo-ing-shared",
    },
    {
        "creditor": "Stadtwerke München",
        "desc": "Strom Abschlag",
        "base": -85.0,
        "cat": "utilities",
        "day": 3,
        "acc": "demo-ing-shared",
    },
    {
        "creditor": "Telekom",
        "desc": "Festnetz + Internet",
        "base": -44.95,
        "cat": "utilities",
        "day": 5,
        "acc": "demo-ing-shared",
    },
    {
        "creditor": "Allianz Versicherung",
        "desc": "Haftpflichtversicherung",
        "base": -12.50,
        "cat": "insurance",
        "day": 1,
        "acc": "demo-ing-shared",
    },
    {
        "creditor": "GEZ",
        "desc": "Rundfunkbeitrag",
        "base": -18.36,
        "cat": "utilities",
        "day": 1,
        "acc": "demo-ing-shared",
    },
    {
        "creditor": "REWE Markt",
        "desc": "REWE Großeinkauf",
        "base": -89.45,
        "cat": "food",
        "day": 4,
        "acc": "demo-ing-shared",
    },
    {
        "creditor": "HelloFresh",
        "desc": "HelloFresh Kochbox KW14",
        "base": -49.99,
        "cat": "food",
        "day": 8,
        "acc": "demo-ing-shared",
    },
    # --- Anna (Sparkasse) ---
    {
        "creditor": "Arbeitgeber GmbH",
        "desc": "Gehalt {month_name}",
        "base": 3250.0,
        "cat": "income",
        "day": 25,
        "acc": "demo-sparkasse-anna",
    },
    {
        "creditor": "REWE Markt",
        "desc": "REWE SAGT DANKE 4823",
        "base": -47.83,
        "cat": "food",
        "day": 2,
        "acc": "demo-sparkasse-anna",
    },
    {
        "creditor": "EDEKA",
        "desc": "EDEKA Einkauf",
        "base": -32.15,
        "cat": "food",
        "day": 5,
        "acc": "demo-sparkasse-anna",
    },
    {
        "creditor": "Netflix",
        "desc": "Netflix Abo",
        "base": -13.99,
        "cat": "subscriptions",
        "day": 8,
        "acc": "demo-sparkasse-anna",
    },
    {
        "creditor": "Spotify",
        "desc": "Spotify Premium Family",
        "base": -17.99,
        "cat": "subscriptions",
        "day": 1,
        "acc": "demo-sparkasse-anna",
    },
    {
        "creditor": "DB Vertrieb",
        "desc": "Deutschlandticket",
        "base": -49.00,
        "cat": "transport",
        "day": 1,
        "acc": "demo-sparkasse-anna",
    },
    {
        "creditor": "ALDI",
        "desc": "ALDI SÜD Filiale 2847",
        "base": -28.47,
        "cat": "food",
        "day": 10,
        "acc": "demo-sparkasse-anna",
    },
    {
        "creditor": "dm-drogerie",
        "desc": "dm Drogeriemarkt",
        "base": -15.99,
        "cat": "other",
        "day": 7,
        "acc": "demo-sparkasse-anna",
    },
    {
        "creditor": "REWE Markt",
        "desc": "REWE SAGT DANKE 5121",
        "base": -52.30,
        "cat": "food",
        "day": 12,
        "acc": "demo-sparkasse-anna",
    },
    {
        "creditor": "Lieferando",
        "desc": "Lieferando Bestellung",
        "base": -24.90,
        "cat": "food",
        "day": 14,
        "acc": "demo-sparkasse-anna",
    },
    {
        "creditor": "HUK-COBURG",
        "desc": "KFZ Versicherung",
        "base": -45.80,
        "cat": "insurance",
        "day": 1,
        "acc": "demo-sparkasse-anna",
    },
    {
        "creditor": "LIDL",
        "desc": "LIDL SAGT DANKE",
        "base": -19.62,
        "cat": "food",
        "day": 16,
        "acc": "demo-sparkasse-anna",
    },
    {
        "creditor": "Rossmann",
        "desc": "Rossmann Filiale",
        "base": -8.49,
        "cat": "other",
        "day": 18,
        "acc": "demo-sparkasse-anna",
    },
    # --- Max (DKB) ---
    {
        "creditor": "Tech AG",
        "desc": "Gehalt {month_name}",
        "base": 2850.0,
        "cat": "income",
        "day": 27,
        "acc": "demo-dkb-max",
    },
    {
        "creditor": "REWE Markt",
        "desc": "REWE Einkauf",
        "base": -38.92,
        "cat": "food",
        "day": 3,
        "acc": "demo-dkb-max",
    },
    {
        "creditor": "Lidl",
        "desc": "LIDL DIENSTL",
        "base": -22.47,
        "cat": "food",
        "day": 6,
        "acc": "demo-dkb-max",
    },
    {
        "creditor": "Disney Plus",
        "desc": "Disney+ Abo",
        "base": -8.99,
        "cat": "subscriptions",
        "day": 15,
        "acc": "demo-dkb-max",
    },
    {
        "creditor": "Xbox",
        "desc": "Xbox Game Pass Ultimate",
        "base": -14.99,
        "cat": "subscriptions",
        "day": 10,
        "acc": "demo-dkb-max",
    },
    {
        "creditor": "Shell",
        "desc": "Shell Tankstelle München",
        "base": -65.40,
        "cat": "transport",
        "day": 8,
        "acc": "demo-dkb-max",
    },
    {
        "creditor": "Amazon",
        "desc": "Amazon.de Bestellung",
        "base": -34.99,
        "cat": "other",
        "day": 11,
        "acc": "demo-dkb-max",
    },
    {
        "creditor": "EDEKA",
        "desc": "EDEKA Center",
        "base": -41.23,
        "cat": "food",
        "day": 9,
        "acc": "demo-dkb-max",
    },
    {
        "creditor": "McFIT",
        "desc": "McFIT Mitgliedschaft",
        "base": -29.90,
        "cat": "other",
        "day": 1,
        "acc": "demo-dkb-max",
    },
    {
        "creditor": "ARAL",
        "desc": "ARAL Tankstelle",
        "base": -58.20,
        "cat": "transport",
        "day": 15,
        "acc": "demo-dkb-max",
    },
    {
        "creditor": "HypoVereinsbank",
        "desc": "Autokredit Rate 48/60",
        "base": -285.00,
        "cat": "loans",
        "day": 5,
        "acc": "demo-dkb-max",
    },
    {
        "creditor": "Barmer",
        "desc": "Zusatzversicherung Zahn",
        "base": -28.50,
        "cat": "insurance",
        "day": 1,
        "acc": "demo-dkb-max",
    },
    {
        "creditor": "Google",
        "desc": "Google One 200 GB",
        "base": -2.99,
        "cat": "subscriptions",
        "day": 12,
        "acc": "demo-dkb-max",
    },
    {
        "creditor": "REWE Markt",
        "desc": "REWE Abend-Einkauf",
        "base": -31.78,
        "cat": "food",
        "day": 17,
        "acc": "demo-dkb-max",
    },
]

# Recurring patterns for demo
_RECURRING_TEMPLATES: list[dict[str, Any]] = [
    {
        "creditor": "Hausverwaltung GmbH",
        "average_amount": -1150.0,
        "frequency": "monthly",
        "category": "housing",
        "occurrences": 12,
        "expected_day": 1,
    },
    {
        "creditor": "Stadtwerke München",
        "average_amount": -85.0,
        "frequency": "monthly",
        "category": "utilities",
        "occurrences": 12,
        "expected_day": 3,
    },
    {
        "creditor": "Telekom",
        "average_amount": -44.95,
        "frequency": "monthly",
        "category": "utilities",
        "occurrences": 12,
        "expected_day": 5,
    },
    {
        "creditor": "Netflix",
        "average_amount": -13.99,
        "frequency": "monthly",
        "category": "subscriptions",
        "occurrences": 8,
        "expected_day": 8,
    },
    {
        "creditor": "Spotify",
        "average_amount": -17.99,
        "frequency": "monthly",
        "category": "subscriptions",
        "occurrences": 11,
        "expected_day": 1,
    },
    {
        "creditor": "DB Vertrieb",
        "average_amount": -49.00,
        "frequency": "monthly",
        "category": "transport",
        "occurrences": 10,
        "expected_day": 1,
    },
    {
        "creditor": "HypoVereinsbank",
        "average_amount": -285.00,
        "frequency": "monthly",
        "category": "loans",
        "occurrences": 12,
        "expected_day": 5,
    },
    {
        "creditor": "HelloFresh",
        "average_amount": -49.99,
        "frequency": "monthly",
        "category": "food",
        "occurrences": 6,
        "expected_day": 8,
    },
]

# Month names for German formatting
def _migrate_templates() -> None:
    """Demo templates name legacy categories; translate them to life areas (#112)."""
    for tpl in _TRANSACTION_TEMPLATES:
        tpl["cat"] = migrate_slug(tpl["cat"], f"{tpl['creditor']} {tpl.get('desc', '')}")
    for tpl in _RECURRING_TEMPLATES:
        tpl["category"] = migrate_slug(tpl["category"], tpl["creditor"])


_migrate_templates()

_MONTH_NAMES = [
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_demo_data() -> dict[str, Any]:
    """Generate a complete demo dataset matching the frontend unified data shape.

    Returns a dict with keys: accounts, totalBalance, accountCount, summary,
    budgets, splitModel, household, recurring, loading, error, lastRefresh,
    rateLimitedUntil, _demo_accounts, _demo_transactions, _demo_balances.

    The _demo_* keys are internal — used by the manager to populate entities.
    """
    rng = random.Random()
    now = datetime.now()
    month = now.month
    year = now.year
    month_name = _MONTH_NAMES[month - 1]

    accounts = _build_accounts()
    transactions = _build_transactions(rng, month, year, month_name)
    balances = _build_balances(rng, accounts)

    # Compute summary from transactions
    category_totals: dict[str, float] = {}
    total_income = 0.0
    total_expenses = 0.0

    for txn in transactions:
        amount = float(txn["transactionAmount"]["amount"])
        cat = txn.get("category", "other")
        if amount > 0:
            total_income += amount
        else:
            total_expenses += abs(amount)
        category_totals[cat] = category_totals.get(cat, 0) + amount

    fixed_cats = {"housing_cold", "housing_warm", "finance", "health"}
    fixed_total = sum(abs(category_totals.get(c, 0)) for c in fixed_cats)
    variable_total = total_expenses - fixed_total

    # Build household data
    household = _build_household(rng, transactions, total_expenses)

    # Build frontend account list
    fe_accounts = []
    total_balance = 0.0
    for acc in accounts:
        acc_id = acc["id"]
        bal_data = balances.get(acc_id, {})
        raw_bals = bal_data.get("balances", [])
        bal_val = 0.0
        if raw_bals:
            bal_val = float(raw_bals[0].get("balanceAmount", {}).get("amount", 0))
        iban = acc.get("iban", "")
        fe_accounts.append(
            {
                "entityId": f"sensor.fd_demo_{acc_id.replace('-', '_')}",
                "name": acc.get("custom_name") or acc.get("name", ""),
                "institution": acc.get("institution", ""),
                "balance": bal_val,
                "ibanMasked": f"****{iban[-4:]}" if len(iban) >= 4 else "****",
                "currency": acc.get("currency", "EUR"),
                "person": acc.get("person", ""),
            }
        )
        total_balance += bal_val

    # Budget limits (demo defaults)
    budgets = {
        "housing_cold": 1200.0,
        "housing_warm": 200.0,
        "groceries": 600.0,
        "mobility": 200.0,
        "media": 100.0,
        "health": 150.0,
        "finance": 300.0,
        "other": 200.0,
    }

    return {
        # Frontend unified data shape
        "accounts": fe_accounts,
        "totalBalance": round(total_balance, 2),
        "accountCount": len(fe_accounts),
        "summary": {
            "totalIncome": round(total_income, 2),
            "totalExpenses": round(total_expenses, 2),
            "balance": round(total_income - total_expenses, 2),
            "categories": {k: round(v, 2) for k, v in category_totals.items()},
            "transactionCount": len(transactions),
            "fixedCosts": round(fixed_total, 2),
            "variableCosts": round(variable_total, 2),
            "month": month,
            "year": year,
        },
        "budgets": budgets,
        "splitModel": "proportional",
        "household": household,
        "recurring": _RECURRING_TEMPLATES[:8],
        "loading": False,
        "error": None,
        "lastRefresh": now.isoformat(),
        "rateLimitedUntil": None,
        # Internal keys for manager/coordinator
        "_demo_accounts": accounts,
        "_demo_transactions": transactions,
        "_demo_balances": balances,
    }


# ---------------------------------------------------------------------------
# Internal builders
# ---------------------------------------------------------------------------


def _build_accounts() -> list[dict[str, Any]]:
    """Return a deep copy of demo accounts."""
    return [dict(a) for a in DEMO_ACCOUNTS_CONFIG]


def _build_transactions(
    rng: random.Random,
    month: int,
    year: int,
    month_name: str,
) -> list[dict[str, Any]]:
    """Generate demo transactions for the given month."""
    today = datetime.now().day
    transactions: list[dict[str, Any]] = []

    # Build account lookup for tagging
    acc_map = {a["id"]: a for a in DEMO_ACCOUNTS_CONFIG}

    for i, tpl in enumerate(_TRANSACTION_TEMPLATES):
        day = tpl["day"]
        # Skip future dates within the month (including future salaries)
        if day > today:
            continue

        # Jitter amount by ±8% (except fixed amounts like rent, salary)
        base = tpl["base"]
        if abs(base) > 100 and tpl["cat"] not in ("income_work", "housing_cold", "finance"):
            jitter = rng.uniform(-0.08, 0.08)
            amount = round(base * (1 + jitter), 2)
        elif abs(base) < 100:
            jitter = rng.uniform(-0.12, 0.12)
            amount = round(base * (1 + jitter), 2)
        else:
            amount = base

        booking_date = f"{year}-{month:02d}-{day:02d}"
        desc = tpl["desc"].format(month_name=month_name, year=year)
        acc_id = tpl["acc"]
        acc = acc_map.get(acc_id, {})

        transactions.append(
            {
                "transactionId": f"demo-{i:04d}-{rng.randint(1000, 9999)}",
                "bookingDate": booking_date,
                "transactionAmount": {
                    "amount": str(amount),
                    "currency": "EUR",
                },
                "creditorName": tpl["creditor"],
                "remittanceInformationUnstructured": desc,
                "category": tpl["cat"],
                "_account_id": acc_id,
                "_account_name": acc.get("custom_name") or acc.get("name", ""),
                "_account_type": acc.get("type", "personal"),
                "_account_person": acc.get("person", ""),
                "_account_ha_users": [],
                "_status": "booked",
            }
        )

    # Sort newest first
    transactions.sort(key=effective_date_str, reverse=True)
    return transactions


def _build_balances(
    rng: random.Random,
    accounts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate demo balance data per account."""
    today = datetime.now().strftime("%Y-%m-%d")
    balances: dict[str, Any] = {}

    for acc in accounts:
        acc_id = acc["id"]
        base = _BASE_BALANCES.get(acc_id, 1000.0)
        amount = round(base * rng.uniform(0.85, 1.15), 2)
        iban = acc.get("iban", "")

        balances[acc_id] = {
            "account_name": acc.get("custom_name") or acc.get("name", ""),
            "iban": iban,
            "iban_masked": f"****{iban[-4:]}" if len(iban) >= 4 else "****",
            "institution": acc.get("institution", ""),
            "logo": acc.get("logo", ""),
            "balances": [
                {
                    "balanceType": "closingBooked",
                    "balanceAmount": {
                        "amount": str(amount),
                        "currency": "EUR",
                    },
                    "referenceDate": today,
                }
            ],
        }

    return balances


def _build_household(
    rng: random.Random,
    transactions: list[dict[str, Any]],
    total_expenses: float,
) -> dict[str, Any]:
    """Build household split data from demo transactions."""
    persons: dict[str, dict[str, float]] = {}
    shared_costs = 0.0

    for txn in transactions:
        amount = float(txn["transactionAmount"]["amount"])
        acc_type = txn.get("_account_type", "personal")
        person = txn.get("_account_person", "")

        if acc_type == "shared":
            if amount < 0:
                shared_costs += abs(amount)
        elif person:
            if person not in persons:
                persons[person] = {"income": 0.0, "individual_costs": 0.0}
            if amount > 0:
                persons[person]["income"] += amount
            else:
                persons[person]["individual_costs"] += abs(amount)

    if not persons:
        return None

    # Calculate proportional split
    total_income = sum(p["income"] for p in persons.values())
    members = []
    for name, data in persons.items():
        ratio = data["income"] / total_income if total_income > 0 else 0.5
        share = shared_costs * ratio
        spielgeld = data["income"] - data["individual_costs"] - share

        members.append(
            {
                "person": name,
                "gross_income": round(data["income"], 2),
                "net_income": round(data["income"], 2),
                "income_ratio": round(ratio * 100, 1),
                "shared_costs_share": round(share, 2),
                "individual_costs": round(data["individual_costs"], 2),
                "spielgeld": round(spielgeld, 2),
                "bonus_amount": 0.0,
            }
        )

    return {
        "members": members,
        "split_model": "proportional",
        "remainder_mode": "none",
        "total_shared_costs": round(shared_costs, 2),
    }


# ---------------------------------------------------------------------------
# Home-screen contract in demo mode
# ---------------------------------------------------------------------------

DEMO_POTS: list[dict[str, Any]] = [
    {
        "id": "demo_food",
        "name": "Lebensmittel",
        "owner": "shared",
        "cycle_budget": 520.0,
        "category_keys": ["groceries"],
        "kind": "spend",
    },
    {
        "id": "demo_anna_fun",
        "name": "Anna Freizeit",
        "owner": "Anna",
        "cycle_budget": 180.0,
        "category_keys": ["other", "leisure", "media"],
        "kind": "spend",
    },
    {
        "id": "demo_max_mobility",
        "name": "Max Mobilität",
        "owner": "Max",
        "cycle_budget": 140.0,
        "category_keys": ["mobility"],
        "kind": "spend",
    },
    {
        "id": "demo_holiday",
        "name": "Urlaub",
        "owner": "shared",
        "cycle_budget": 150.0,
        "category_keys": [],
        "kind": "reserve",
    },
]

# (account, creditor, category, amount, days before today) - invented
_DEMO_HOME_SPENDING: list[tuple[str, str, str, float, int]] = [
    ("demo-ing-shared", "Markt Frisch", "food", -62.4, 1),
    ("demo-ing-shared", "Markt Frisch", "food", -48.1, 4),
    ("demo-ing-shared", "Bäckerei", "food", -9.8, 6),
    ("demo-ing-shared", "Markt Frisch", "food", -77.3, 9),
    ("demo-ing-shared", "Wochenmarkt", "food", -31.0, 13),
    ("demo-sparkasse-anna", "Kino", "other", -24.0, 2),
    ("demo-sparkasse-anna", "Streamingdienst", "subscriptions", -9.99, 8),
    ("demo-dkb-max", "Tankstelle", "transport", -58.7, 3),
    ("demo-dkb-max", "ÖPNV", "transport", -49.0, 10),
]


def generate_demo_home(
    *,
    person: str | None,
    view: str,
    horizon: str,
    now: datetime | None = None,
    include_recent: bool = False,
) -> dict[str, Any]:
    """Home contract built from invented data - same shape as the live one.

    Anna's salary lands on the 1st, Max's on the 28th: the household cycle
    therefore starts on Max's pay day (7-day rule), which demonstrates the rule.
    """
    from .home import build_home
    from .pots import Pot

    now = now or datetime.now().astimezone()
    accounts, txs, plan = demo_world(now)

    if view == "person" and person not in {"Anna", "Max"}:
        person = "Anna"
    out = build_home(
        accounts=accounts,
        transactions=txs,
        plan=plan,
        pots=[Pot.from_dict(p) for p in DEMO_POTS],
        recurring=[],
        banks=[],
        as_of=now,
        now=now,
        person=person if view == "person" else None,
        view=view,
        horizon=horizon,
        include_recent=include_recent,
    )
    # Demo has no HA-user mapping: always expose a person so the frontend can
    # switch back from the household view, and show a covered-costs verdict.
    if out.get("person") is None:
        out["person"] = {"id": "Anna", "name": "Anna"}
    out["setup"] = {
        "persons": 2,
        "user_mapped": True,
        "accounts_total": len(accounts),
        "accounts_assigned": len(accounts),
        "pots": len(DEMO_POTS),
    }
    if horizon == "year":
        from .year_view import fixed_year

        out["year"]["fixed_year"] = fixed_year(
            _DEMO_CONTRACTS, out["view"], (out.get("person") or {}).get("id")
        )
    if horizon == "year" and include_recent:
        bench = generate_demo_benchmark()
        out["year"]["benchmark_teaser"] = bench["teaser"]
        steps = generate_demo_review()["steps"]
        open_groups = [g for s in steps if s["id"] != "check" for g in s["groups"] if not g["auto"]]
        out["year"]["review_hint"] = {
            "open_groups": len(open_groups),
            "open_amount": round(sum(abs(g["amount"]) for g in open_groups), 2),
        }
    if horizon in ("cycle", "year") and out.get("fixed_costs_covered") is None:
        out["fixed_costs_covered"] = True
    return out


# ---------------------------------------------------------------------------
# One invented household for every demo payload (home, year, review, benchmark)
# ---------------------------------------------------------------------------

_HISTORY_MONTHS = 26  # two full years: the prior-year comparison has data to show
_MONTHLY: list[tuple[str, str, str, float, int]] = [
    # account, creditor, category, amount, day of month
    ("demo-ing-shared", "Vermieter Schmidt", "housing_cold", -1150.0, 3),
    ("demo-ing-shared", "Stadtwerke", "housing_warm", -118.0, 5),
    ("demo-sparkasse-anna", "Streamingdienst", "media", -9.99, 8),
    ("demo-sparkasse-anna", "Fitnessstudio", "leisure", -29.9, 9),
    ("demo-dkb-max", "Autoversicherung", "insurance", -64.5, 12),
    ("demo-dkb-max", "Tankstelle", "mobility", -58.7, 14),
    ("demo-ing-shared", "Markt Frisch", "groceries", -78.0, 6),
    ("demo-ing-shared", "Markt Frisch", "groceries", -64.0, 13),
    ("demo-ing-shared", "Markt Frisch", "groceries", -91.0, 20),
    ("demo-ing-shared", "Wochenmarkt", "groceries", -31.0, 25),
    ("demo-sparkasse-anna", "Kino", "other", -24.0, 17),
    ("demo-sparkasse-anna", "Restaurant Bella", "leisure", -46.0, 22),
    ("demo-dkb-max", "Baumarkt Hornbach", "other", -52.0, 19),
]
_ONE_OFFS: dict[int, tuple[str, str, str, float, int]] = {
    3: ("demo-ing-shared", "Reisebuero Sonne", "leisure", -1480.0, 11),
    8: ("demo-ing-shared", "Elektro Markt", "other", -649.0, 16),
    14: ("demo-dkb-max", "Reisebuero Sonne", "leisure", -980.0, 10),
}


def demo_plan() -> Any:
    """A small invented household plan (two persons, seven positions).

    The variable positions sit close to the invented monthly spending, so the
    year bars read ok / knapp / over instead of all "over".
    """
    from .budget_plan import BudgetPlan

    return BudgetPlan.from_dict(
        {
            "persons": ["Anna", "Max"],
            "income": [
                {"person": "Anna", "deposit": 3100.0},
                {"person": "Max", "deposit": 2400.0},
            ],
            "positions": [
                {"id": "miete", "name": "Vermieter Schmidt", "owner": "shared", "amount": 1150.0, "category": "housing_cold"},
                {"id": "strom", "name": "Stadtwerke", "owner": "shared", "amount": 118.0, "category": "housing_warm"},
                {"id": "essen", "name": "Lebensmittel", "owner": "shared", "kind": "buffer", "buffer_units": 4.5, "buffer_unit_price": 62.0, "category": "groceries"},
                {"id": "mobil", "name": "Tanken", "owner": "Max", "kind": "buffer", "buffer_units": 1.0, "buffer_unit_price": 60.0, "category": "mobility"},
                {"id": "freizeit", "name": "Freizeit", "owner": "shared", "kind": "buffer", "buffer_units": 3.0, "buffer_unit_price": 50.0, "category": "leisure"},
                {"id": "stream", "name": "Streamingdienst", "owner": "Anna", "amount": 9.99, "category": "media"},
                {"id": "kfz", "name": "Autoversicherung", "owner": "Max", "amount": 64.5, "category": "insurance"},
            ],
        }
    )


def demo_world(now: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Any]:
    """``(accounts, transactions, plan)``: two years of invented bookings."""
    from datetime import timedelta

    from .account_identity import account_key

    today = now.date()
    accounts = _build_accounts()
    acc_map = {a["id"]: a for a in accounts}
    counter = {"n": 0}

    def _tx(acc_id: str, creditor: str, cat: str, amount: float, day, *, pending=False):
        acc = acc_map[acc_id]
        counter["n"] += 1
        tid = f"demo-home-{counter['n']}"
        return {
            "transactionId": tid,
            "_ledger_id": tid,
            "bookingDate": day.isoformat(),
            "transactionAmount": {"amount": str(amount), "currency": "EUR"},
            "creditorName": creditor,
            "category": migrate_slug(cat, creditor),
            "_account_id": acc_id,
            "_account_key": account_key(acc),
            "_account_name": acc.get("custom_name", ""),
            "_account_type": acc.get("type", "personal"),
            "_account_person": acc.get("person", ""),
            "_status": "pending" if pending else "booked",
        }

    txs: list[dict[str, Any]] = []
    first = today.replace(day=1)
    for i in range(_HISTORY_MONTHS):
        if i:
            first = (first - timedelta(days=1)).replace(day=1)
        txs.append(_tx("demo-sparkasse-anna", "Arbeitgeber A", "income", 3100.0, first))
        prev_end = first - timedelta(days=1)
        txs.append(_tx("demo-dkb-max", "Arbeitgeber M", "income", 2400.0, prev_end.replace(day=28)))
        wobble = 1 + ((i * 7) % 5 - 2) / 40  # a few percent up and down, deterministic
        for acc_id, creditor, cat, amount, dom in _MONTHLY:
            if i == 0 and first.replace(day=dom) > today:
                continue
            txs.append(_tx(acc_id, creditor, cat, round(amount * (wobble if cat in ("groceries", "mobility", "leisure") else 1), 2), first.replace(day=dom)))
        if i in _ONE_OFFS and i > 0:
            acc_id, creditor, cat, amount, dom = _ONE_OFFS[i]
            txs.append(_tx(acc_id, creditor, cat, amount, first.replace(day=dom)))
    for acc_id, creditor, cat, amount, ago in _DEMO_HOME_SPENDING:
        txs.append(_tx(acc_id, creditor, cat, amount, today - timedelta(days=ago)))
    txs.append(_tx("demo-ing-shared", "Markt Frisch", "food", -18.5, today, pending=True))
    txs.append(_tx("demo-sparkasse-anna", "Streamingdienst", "subscriptions", -9.99, today, pending=True))
    txs = [t for t in txs if t["_status"] == "pending" or effective_date_str(t) <= today.isoformat()]
    txs.sort(key=effective_date_str, reverse=True)
    return accounts, txs, demo_plan()


def _demo_context(now: datetime | None = None):
    """Everything the pure review / benchmark code needs, from the invented household."""
    from .counted import counted_transactions, net_counted
    from .household_summary import Classifier, plan_persons

    now = now or datetime.now().astimezone()
    accounts, txs, plan = demo_world(now)
    counted = net_counted(counted_transactions(txs, accounts))
    clf = Classifier(plan, [], None, plan_persons(plan, accounts))
    return now, accounts, txs, counted, plan, clf


def generate_demo_review() -> dict[str, Any]:
    """The review payload for ``?demo=1`` (same code path as the live one)."""
    from . import review as rv
    from .household_summary import plan_persons

    now, accounts, txs, counted, plan, clf = _demo_context()
    return rv.build_review(
        raw=txs, txs=counted, accounts=accounts, plan=plan, clf=clf,
        persons=plan_persons(plan, accounts), series_list=[], state={}, today=now.date(),
        ai_merchants={"baumarkt hornbach": "housing_cold"},
    )


def generate_demo_report() -> dict[str, Any]:
    """The review report for ``?demo=1`` (viewer: Anna)."""
    from . import review as rv
    from .household_summary import plan_persons

    now, accounts, txs, counted, plan, clf = _demo_context()
    payload = generate_demo_review()
    names = plan_persons(plan, accounts)
    state = {
        "started_snapshot": {
            "owners": {"__shared__": 9000.0, "Anna": 3100.0, "Max": 2500.0, "open": 400.0},
            "open_groups": 9, "open_amount": 1500.0, "settle": {"Anna": 0.0, "Max": 0.0},
        },
        "reviewed_at": None,
    }
    return rv.build_report(
        txs=counted, plan=plan, clf=clf, persons_cfg=[{"name": n} for n in names],
        person_names=names, today=now.date(), viewer_person="Anna", contracts=[],
        review=payload, state=state,
    )


def generate_demo_benchmark() -> dict[str, Any]:
    """The benchmark payload for ``?demo=1``: demo actuals against the bundled dataset."""
    from .benchmark import BenchmarkProvider, compare_all, teaser
    from .const import BENCHMARK_METRIC_SOURCES
    from .year_view import actual_year

    now, _accounts, _txs, counted, plan, clf = _demo_context()
    provider = BenchmarkProvider()
    actual = actual_year(counted, clf, [{"name": "Anna"}, {"name": "Max"}], now.date())
    income = plan.income_net_total()
    location = {"state": None, "postcode": None, "household_size": 2}
    comparisons = compare_all(
        provider, BENCHMARK_METRIC_SOURCES,
        actual_monthly=actual["by_category_monthly"],
        plan_monthly=plan.category_totals(now.month, now.year),
        income_actual=actual["income_monthly"], income_plan=income,
        months_covered=actual["months_covered"], year=now.year, location=location,
    )
    return {
        "month": now.month, "year": now.year, "income_net_total": income,
        "comparisons": comparisons, "teaser": teaser(comparisons),
        "basis": {
            "year": now.year, "months_covered": actual["months_covered"],
            "extrapolated": 0 < actual["months_covered"] < 12, "has_actual": actual["months_covered"] > 0,
            "scale": {"typical_tolerance": 0.1, "min": 0.0, "max": 1.0},
        },
        "references": provider.references(**location), "unavailable": provider.unavailable(),
        "dataset": provider.dataset_info(), "location": location, "has_plan": True, "demo": True,
    }


_DEMO_CONTRACTS: list[dict[str, Any]] = [
    {"id": "demo-miete", "display_name": "Vermieter Schmidt", "owner": "shared", "annual_cost": 13800.0, "interval": "monthly", "kind": "contract", "status": "active"},
    {"id": "demo-strom", "display_name": "Stadtwerke", "owner": "shared", "annual_cost": 1416.0, "interval": "monthly", "kind": "contract", "status": "active"},
    {"id": "demo-stream", "display_name": "Streamingdienst", "owner": "Anna", "annual_cost": 119.88, "interval": "monthly", "kind": "subscription", "status": "active"},
    {"id": "demo-kfz", "display_name": "Autoversicherung", "owner": "Max", "annual_cost": 774.0, "interval": "monthly", "kind": "contract", "status": "active"},
]
