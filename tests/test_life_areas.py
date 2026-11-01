"""Life areas and the one-time category migration (#112)."""

from __future__ import annotations

import asyncio
import copy

import pytest

from custom_components.finance_dashboard import taxonomy_migration as tm
from custom_components.finance_dashboard.const import DEFAULT_CATEGORIES
from custom_components.finance_dashboard.life_areas import (
    ALL_CATEGORIES,
    INCOME_AREAS,
    LIFE_AREAS,
    is_income,
    migrate_slug,
    migrate_targets,
)


@pytest.mark.parametrize(
    ("slug", "text", "expected"),
    [
        ("housing", "Miete Whg 3", "housing_cold"),
        ("housing", "Nebenkosten Abrechnung", "housing_warm"),
        ("utilities", "stadtwerke koblenz", "housing_warm"),
        ("utilities", "Gas Abschlag", "housing_warm"),
        ("utilities", "deutsche telekom", "media"),
        ("utilities", "rundfunkbeitrag", "media"),
        ("utilities", "unbekannt gmbh", "other"),
        ("utilities", "gastro eck", "other"),  # "gas" never hits "gastro"
        ("food", "rewe", "groceries"),
        ("food", "pizzeria roma", "leisure"),
        ("shopping", "rossmann", "groceries"),
        ("shopping", "zalando", "other"),
        ("transport", "", "mobility"),
        ("insurance", "allianz hausrat", "housing_cold"),
        ("insurance", "kfz versicherung", "mobility"),
        ("insurance", "tk", "health"),
        ("subscriptions", "netflix", "media"),
        ("subscriptions", "mcfit", "leisure"),
        ("loans", "baufinanzierung", "housing_cold"),
        ("loans", "klarna", "finance"),
        ("telecom", "", "media"),
        ("cleaning", "", "groceries"),
        ("income", "Gehalt Oktober", "income_work"),
        ("income", "Kindergeld", "income_state"),
        ("income", "Zinsen", "income_capital"),
        ("income", "", "income_work"),
    ],
)
def test_legacy_slug_maps_by_fixed_keywords(slug, text, expected):
    assert migrate_slug(slug, text) == expected


@pytest.mark.parametrize("slug", [*ALL_CATEGORIES, "my_custom", None, ""])
def test_migration_of_a_new_or_unknown_slug_is_a_no_op(slug):
    assert migrate_slug(slug, "Gehalt Miete Strom") == slug


def test_every_area_is_exactly_one_set():
    assert len(set(LIFE_AREAS)) == 8
    assert not set(LIFE_AREAS) & set(INCOME_AREAS)
    assert set(DEFAULT_CATEGORIES) == {*LIFE_AREAS, "other"}
    assert all(is_income(a) for a in INCOME_AREAS) and is_income("income")
    assert not any(is_income(a) for a in LIFE_AREAS)


def test_targets_of_a_key_set_never_guess_other():
    assert migrate_targets("utilities") == ("media", "housing_warm")
    assert migrate_targets("food") == ("groceries", "leisure")
    assert migrate_targets("shopping") == ("groceries",)
    assert migrate_targets("transport") == ("mobility",)
    assert migrate_targets("custom") == ("custom",)


class _Disk:
    """Keyed in-memory stand-in for HA's .storage."""

    def __init__(self):
        self.files: dict[str, object] = {}
        self.broken: set[str] = set()

    def store(self, _hass, _version, key):
        disk = self

        class _S:
            async def async_load(self):
                if key in disk.broken:
                    raise ValueError("broken")
                return copy.deepcopy(disk.files.get(key))

            async def async_save(self, data):
                disk.files[key] = copy.deepcopy(data)

        return _S()


def _legacy_disk() -> _Disk:
    disk = _Disk()
    disk.files[tm.STORAGE_KEY_MERCHANTS] = {
        "merchants": {
            "stadtwerke koblenz": {"category": "utilities"},
            "telekom": {"category": "utilities", "owner": "Anna"},
            "unbekannt": {"category": "utilities"},
            "rewe": {"category": "groceries"},  # already new
        },
        "bookings": {"L1": {"category": "food"}, "L2": {"category": "utilities"}},
        "answered": 3,
    }
    disk.files[tm.STORAGE_KEY_AI] = {
        "cache": {"netflix": "subscriptions", "aral": "transport"},
        "last_run": {"at": "x", "ok": True, "category": "food"},
    }
    disk.files[tm.STORAGE_KEY_BUDGET_PLAN] = {
        "positions": [
            {"name": "Strom", "category": "utilities"},
            {"name": "Handy", "category": "utilities"},
            {"name": "Miete", "category": "housing"},
        ],
    }
    disk.files[tm.STORAGE_KEY_POTS] = {
        "pots": [
            {"id": "p1", "category_keys": ["food", "shopping"]},
            {"id": "p2", "category_keys": ["leisure"]},
        ],
    }
    disk.files[tm.STORAGE_KEY_CONTRACTS] = {
        "contracts": {
            "s1": {"category": "insurance"},
            "s2": {"category": "utilities"},
            "s3": {"category": None},
        },
    }
    return disk


def _run(disk, monkeypatch, entry_id=None):
    monkeypatch.setattr(tm, "Store", disk.store)
    return asyncio.run(tm.async_migrate_taxonomy(None, entry_id))


def test_migration_rewrites_every_store_after_a_backup(monkeypatch):
    disk = _legacy_disk()
    before = copy.deepcopy(disk.files)
    assert _run(disk, monkeypatch) is True

    mem = disk.files[tm.STORAGE_KEY_MERCHANTS]
    assert mem["merchants"]["stadtwerke koblenz"]["category"] == "housing_warm"
    assert mem["merchants"]["telekom"] == {"category": "media", "owner": "Anna"}
    assert mem["merchants"]["unbekannt"]["category"] == "other"  # asked again
    assert mem["bookings"] == {"L1": {"category": "groceries"}, "L2": {"category": "other"}}
    assert mem["answered"] == 3
    assert disk.files[tm.STORAGE_KEY_AI]["cache"] == {"netflix": "media", "aral": "mobility"}
    assert [p["category"] for p in disk.files[tm.STORAGE_KEY_BUDGET_PLAN]["positions"]] == [
        "housing_warm", "media", "housing_cold",
    ]
    pots = disk.files[tm.STORAGE_KEY_POTS]["pots"]
    assert pots[0]["category_keys"] == ["groceries", "leisure"]
    assert pots[1]["category_keys"] == ["leisure"]
    contracts = disk.files[tm.STORAGE_KEY_CONTRACTS]["contracts"]
    assert contracts["s1"]["category"] == "health"
    assert contracts["s2"]["category"] is None  # follows detection again
    assert contracts["s3"]["category"] is None

    for key, data in before.items():
        assert disk.files[key + tm.BACKUP_SUFFIX] == data
    assert disk.files[tm.STORAGE_KEY_TAXONOMY]["version"] == tm.TAXONOMY_VERSION


def test_migration_runs_once(monkeypatch):
    disk = _legacy_disk()
    _run(disk, monkeypatch)
    disk.files[tm.STORAGE_KEY_AI]["cache"]["late"] = "food"  # written by old code
    assert _run(disk, monkeypatch) is False
    assert disk.files[tm.STORAGE_KEY_AI]["cache"]["late"] == "food"


def test_unreadable_store_is_left_and_retried(monkeypatch):
    disk = _legacy_disk()
    disk.broken.add(tm.STORAGE_KEY_POTS)
    _run(disk, monkeypatch)
    assert tm.STORAGE_KEY_TAXONOMY not in disk.files
    assert disk.files[tm.STORAGE_KEY_MERCHANTS]["bookings"]["L1"]["category"] == "groceries"
    backup = disk.files[tm.STORAGE_KEY_MERCHANTS + tm.BACKUP_SUFFIX]
    disk.broken.clear()
    _run(disk, monkeypatch)
    assert disk.files[tm.STORAGE_KEY_POTS]["pots"][0]["category_keys"] == ["groceries", "leisure"]
    # the retry never overwrites the first backup with migrated data
    assert disk.files[tm.STORAGE_KEY_MERCHANTS + tm.BACKUP_SUFFIX] == backup
    assert disk.files[tm.STORAGE_KEY_TAXONOMY]["version"] == tm.TAXONOMY_VERSION


def test_fresh_install_writes_only_the_marker(monkeypatch):
    disk = _Disk()
    _run(disk, monkeypatch)
    assert set(disk.files) == {tm.STORAGE_KEY_TAXONOMY}


def test_number_entities_move_to_the_new_slugs(monkeypatch):
    class _Entity:
        def __init__(self, entity_id, unique_id, domain="number"):
            self.entity_id, self.unique_id, self.domain = entity_id, unique_id, domain

    class _Registry:
        def __init__(self):
            self.entities = [
                _Entity("number.a", "finance_dashboard_budget_food"),
                _Entity("number.b", "finance_dashboard_budget_income"),
                _Entity("number.c", "finance_dashboard_budget_other"),
                _Entity("number.d", "finance_dashboard_budget_housing"),
                _Entity("number.e", "finance_dashboard_budget_housing_cold"),
                _Entity("sensor.x", "finance_dashboard_budget_food", "sensor"),
            ]
            self.updates, self.removed = {}, []

        def async_get_entity_id(self, _domain, _platform, unique_id):
            return next((e.entity_id for e in self.entities if e.unique_id == unique_id), None)

        def async_update_entity(self, entity_id, new_unique_id):
            self.updates[entity_id] = new_unique_id

        def async_remove(self, entity_id):
            self.removed.append(entity_id)

    reg = _Registry()
    monkeypatch.setattr(tm.er, "async_get", lambda _hass: reg)
    monkeypatch.setattr(tm.er, "async_entries_for_config_entry", lambda r, _e: r.entities)
    tm.migrate_number_entities(None, "entry")
    assert reg.updates == {"number.a": "finance_dashboard_budget_groceries"}
    # income has no target; housing's target already exists (no duplicate)
    assert reg.removed == ["number.b", "number.d"]


# --- QA #112 regressions -----------------------------------------------------


def _cat(text, amount):
    from custom_components.finance_dashboard.categorizer import TransactionCategorizer

    return TransactionCategorizer().categorize(
        {"remittanceInformationUnstructured": text, "transactionAmount": {"amount": str(amount)}}
    )


@pytest.mark.parametrize(
    ("text", "amount", "expected"),
    [
        ("Deutsche Rentenversicherung Rente", 1200, "income_state"),
        ("Erstattung Finanzamt", 100, "income_refund"),
        ("Rueckerstattung Versicherung", 50, "income_refund"),
        ("Unterhalt von Vater", 300, "income_private"),
        ("Miete Dezember", -900, "housing_cold"),
        ("Rentenversicherung Beitrag", -100, "health"),
        ("Betrag gezahlt", -20, "other"),
        ("Tierarzt Praxis", -80, "health"),
        ("Metropol Kino", -12, "leisure"),
    ],
)
def test_direction_and_short_keywords(text, amount, expected):
    assert _cat(text, amount) == expected


def test_savings_goal_caps_move_with_their_category(monkeypatch):
    disk = _Disk()
    disk.files[tm.STORAGE_KEY_GOALS] = {
        "goals": [
            {"kind": "category_cap", "name": "Essen", "category": "food", "cap_amount": 500},
            {"kind": "savings_rate", "name": "Rate", "rate_percent": 10},
        ]
    }
    _run(disk, monkeypatch)
    goals = disk.files[tm.STORAGE_KEY_GOALS]["goals"]
    assert goals[0]["category"] == "groceries"
    assert "category" not in goals[1]


def test_insurer_without_the_word_versicherung_is_a_contract():
    from custom_components.finance_dashboard.contract_kind import KIND_CONTRACT, suggest_kind

    row = (None, -210.0, {"remittanceInformationUnstructured": "Beitrag", "creditorName": "AOK Nordost"})
    assert suggest_kind([row] * 4, "monthly", "health") == KIND_CONTRACT


def test_demo_data_speaks_only_life_areas():
    from custom_components.finance_dashboard import demo

    allowed = {*ALL_CATEGORIES}
    assert {t["cat"] for t in demo._TRANSACTION_TEMPLATES} <= allowed  # noqa: SLF001
    assert {t["category"] for t in demo._RECURRING_TEMPLATES} <= allowed  # noqa: SLF001
    assert {k for p in demo.DEMO_POTS for k in p["category_keys"]} <= allowed
