"""Tests for the migrated spreadsheet model.

All amounts here are invented. Real household figures live only in HA's
``.storage/`` and must never appear in the repository.

The numbers are chosen so the expected results are checkable by hand:
pooled net income 5000 + (-300) = 4700, shared costs 4000, remainder
(4700 - 4000) / 2 = 350 per person.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from custom_components.finance_dashboard.budget_plan import (
    BudgetPlan,
    CostPosition,
    IncomeEntry,
    actual_amount_to_plan_sign,
    slugify_position,
)
from custom_components.finance_dashboard.const import (
    OWNER_SHARED,
    POSITION_KIND_BUFFER,
    SPLIT_MODEL_EQUAL,
    SPLIT_MODEL_POOLED_EQUAL,
)
from custom_components.finance_dashboard.household import model_from_plan
from custom_components.finance_dashboard.spreadsheet_import import (
    categorize_position,
    parse_validity,
)
from custom_components.finance_dashboard.transfer_plan import build_transfer_plan

MONTH, YEAR = 6, 2026


def _plan() -> BudgetPlan:
    """A two-person plan mirroring the spreadsheet's structure."""
    plan = BudgetPlan()
    plan.set_income(IncomeEntry(person="A", deposit=6000.0, insurance_mandatory=-1000.0))
    plan.set_income(IncomeEntry(person="B", deposit=0.0, insurance_mandatory=-300.0))
    # shared: 4200 of expenses minus a 200 reimbursement = 4000 net
    plan.upsert_position(
        CostPosition(id="rent", name="Rent", owner=OWNER_SHARED, amount=3000.0)
    )
    plan.upsert_position(
        CostPosition(id="power", name="Power", owner=OWNER_SHARED, amount=1200.0)
    )
    plan.upsert_position(
        CostPosition(
            id="onward", name="Music billed onward", owner=OWNER_SHARED, amount=-200.0
        )
    )
    plan.upsert_position(CostPosition(id="gym_b", name="Gym", owner="B", amount=50.0))
    plan.upsert_position(CostPosition(id="hair_a", name="Hairdresser", owner="A", amount=20.0))
    return plan


class TestCostPosition:
    """Position-level arithmetic and validity."""

    def test_buffer_amount_is_units_times_price(self):
        position = CostPosition(
            id="food",
            name="Food buffer",
            owner=OWNER_SHARED,
            kind=POSITION_KIND_BUFFER,
            buffer_units=4.5,
            buffer_unit_price=80.0,
        )
        assert position.planned_amount == 360.0

    def test_buffer_ignores_the_amount_field(self):
        position = CostPosition(
            id="food",
            name="Food buffer",
            owner=OWNER_SHARED,
            amount=99999.0,
            kind=POSITION_KIND_BUFFER,
            buffer_units=2.0,
            buffer_unit_price=10.0,
        )
        assert position.planned_amount == 20.0

    @pytest.mark.parametrize(
        ("month", "year", "expected"),
        [
            (4, 2027, True),  # last valid month — bound is inclusive
            (5, 2027, False),  # first month after expiry
            (3, 2027, True),
        ],
    )
    def test_valid_until_is_inclusive(self, month, year, expected):
        position = CostPosition(
            id="prime",
            name="Prime",
            owner=OWNER_SHARED,
            amount=5.98,
            valid_until="2027-04",
        )
        assert position.is_active(month, year) is expected

    def test_out_of_validity_contributes_nothing(self):
        position = CostPosition(
            id="prime", name="Prime", owner=OWNER_SHARED, amount=5.98, valid_until="2027-04"
        )
        assert position.effective_amount(5, 2027) == 0.0
        assert position.effective_amount(4, 2027) == 5.98

    def test_malformed_validity_bound_keeps_position_active(self):
        # A typo in a bound must never silently hide a real cost.
        position = CostPosition(
            id="x", name="X", owner=OWNER_SHARED, amount=10.0, valid_until="not-a-date"
        )
        assert position.is_active(MONTH, YEAR) is True

    def test_slug_separates_same_name_for_different_owners(self):
        assert slugify_position("Google One", OWNER_SHARED) != slugify_position("Google One", "A")

    def test_round_trip_preserves_every_field(self):
        original = CostPosition(
            id="p",
            name="P",
            owner="A",
            amount=-8.0,
            kind=POSITION_KIND_BUFFER,
            buffer_units=3.0,
            buffer_unit_price=7.0,
            valid_from="2026-01",
            valid_until="2027-04",
            note="hi",
            debit_account="acc1",
        )
        assert CostPosition.from_dict(original.to_dict()) == original


class TestBudgetPlan:
    """Plan-level aggregation."""

    def test_negative_net_income_is_preserved(self):
        plan = _plan()
        assert plan.income_net("B") == -300.0
        assert plan.income_net("A") == 5000.0
        assert plan.income_net_total() == 4700.0

    def test_reimbursements_reduce_shared_costs(self):
        plan = _plan()
        # 3000 + 1200 - 200
        assert plan.cost_shared(MONTH, YEAR) == 4000.0

    def test_individual_costs_are_per_owner(self):
        plan = _plan()
        assert plan.cost_individual("A", MONTH, YEAR) == 20.0
        assert plan.cost_individual("B", MONTH, YEAR) == 50.0

    def test_income_share_may_exceed_one_when_a_person_is_negative(self):
        plan = _plan()
        assert plan.income_rel("A") > 1.0
        assert plan.income_rel("B") < 0.0

    def test_income_share_is_zero_when_pool_is_zero(self):
        plan = BudgetPlan()
        plan.set_income(IncomeEntry(person="A", deposit=100.0))
        plan.set_income(IncomeEntry(person="B", deposit=-100.0))
        assert plan.income_net_total() == 0.0
        assert plan.income_rel("A") == 0.0

    def test_buffer_and_fixed_totals_are_addressable_separately(self):
        plan = _plan()
        plan.upsert_position(
            CostPosition(
                id="food",
                name="Food buffer",
                owner=OWNER_SHARED,
                kind=POSITION_KIND_BUFFER,
                buffer_units=4.0,
                buffer_unit_price=25.0,
            )
        )
        assert plan.buffer_total(MONTH, YEAR, OWNER_SHARED) == 100.0
        assert plan.fixed_total(MONTH, YEAR, OWNER_SHARED) == 4000.0

    def test_upsert_replaces_by_id_without_duplicating(self):
        plan = _plan()
        before = len(plan.positions)
        plan.upsert_position(
            CostPosition(id="rent", name="Rent", owner=OWNER_SHARED, amount=3100.0)
        )
        assert len(plan.positions) == before
        assert plan.cost_shared(MONTH, YEAR) == 4100.0

    def test_from_dict_heals_a_drifted_person_list(self):
        raw = {
            "persons": [],  # drifted: empty despite positions naming an owner
            "income": [{"person": "A", "deposit": 100.0}],
            "positions": [{"name": "Gym", "owner": "B", "amount": 10.0}],
        }
        plan = BudgetPlan.from_dict(raw)
        assert set(plan.persons) == {"A", "B"}

    def test_bank_sign_is_flipped_to_plan_sign(self):
        assert actual_amount_to_plan_sign(-42.5) == 42.5
        assert actual_amount_to_plan_sign(42.5) == -42.5


class TestPooledEqualSplit:
    """The spreadsheet's split model."""

    def test_remainder_is_split_equally_from_the_pool(self):
        plan = _plan()
        model, shared = model_from_plan(
            plan, MONTH, YEAR, split_mode=SPLIT_MODEL_POOLED_EQUAL
        )
        results = {r.person: r for r in model.calculate_split(shared)}
        # (4700 - 4000) / 2 = 350 each
        assert results["A"].remainder_share == 350.0
        assert results["B"].remainder_share == 350.0

    def test_pocket_money_differs_only_by_individual_costs(self):
        plan = _plan()
        model, shared = model_from_plan(
            plan, MONTH, YEAR, split_mode=SPLIT_MODEL_POOLED_EQUAL
        )
        results = {r.person: r for r in model.calculate_split(shared)}
        assert results["A"].spielgeld == 330.0  # 350 - 20
        assert results["B"].spielgeld == 300.0  # 350 - 50

    def test_totals_reconcile(self):
        plan = _plan()
        model, shared = model_from_plan(
            plan, MONTH, YEAR, split_mode=SPLIT_MODEL_POOLED_EQUAL
        )
        results = model.calculate_split(shared)
        expected = (
            plan.income_net_total()
            - plan.cost_shared(MONTH, YEAR)
            - sum(plan.cost_individual(p, MONTH, YEAR) for p in plan.persons)
        )
        assert sum(r.spielgeld for r in results) == pytest.approx(expected, abs=0.01)

    def test_pooled_model_carries_a_person_with_negative_income(self):
        plan = _plan()
        pooled, shared = model_from_plan(
            plan, MONTH, YEAR, split_mode=SPLIT_MODEL_POOLED_EQUAL
        )
        equal, _ = model_from_plan(plan, MONTH, YEAR, split_mode=SPLIT_MODEL_EQUAL)

        pooled_b = {r.person: r for r in pooled.calculate_split(shared)}["B"].spielgeld
        equal_b = {r.person: r for r in equal.calculate_split(shared)}["B"].spielgeld

        assert pooled_b > 0  # carried by the pool
        assert equal_b < 0  # left with their own negative income
        assert pooled_b != equal_b

    def test_remainder_mode_does_not_flatten_individual_costs(self):
        # equal_split would make both persons identical, erasing the very
        # difference the pooled model exists to preserve.
        plan = _plan()
        model, shared = model_from_plan(
            plan,
            MONTH,
            YEAR,
            split_mode=SPLIT_MODEL_POOLED_EQUAL,
            remainder_mode="equal_split",
        )
        results = {r.person: r for r in model.calculate_split(shared)}
        assert results["A"].spielgeld != results["B"].spielgeld


class TestTransferPlan:
    """The monthly choreography and its invariants."""

    ACCOUNTS: ClassVar[list[dict[str, str]]] = [
        {"id": "a_main", "name": "A main", "person": "A", "type": "personal"},
        {"id": "joint", "name": "Joint living costs", "person": "A", "type": "shared"},
        {"id": "b_main", "name": "B main", "person": "B", "type": "personal"},
    ]

    def _build(self, plan=None):
        plan = plan or _plan()
        model, shared = model_from_plan(
            plan, MONTH, YEAR, split_mode=SPLIT_MODEL_POOLED_EQUAL
        )
        results = model.calculate_split(shared)
        return build_transfer_plan(plan, self.ACCOUNTS, MONTH, YEAR, split_results=results)

    def test_pass_through_account_nets_to_zero(self):
        tp = self._build()
        assert tp.balanced, f"unbalanced: {tp.imbalances}"
        assert tp.final_balances["joint"] == 0.0

    def test_a_person_without_liquidity_contributes_nothing(self):
        tp = self._build()
        transfer = next(
            r for r in tp.rows if r.label == "Umbuchung Lebenshaltungskosten"
        )
        # B has negative net income, so A funds the entire shared total.
        assert transfer.amounts.get("b_main", 0.0) == 0.0
        assert transfer.amounts["a_main"] == pytest.approx(-4000.0, abs=0.01)

    def test_settlement_exposes_who_fronts_for_whom(self):
        tp = self._build()
        assert tp.settlements["A"]["settlement_delta"] > 0
        assert tp.settlements["B"]["settlement_delta"] < 0
        # The two sides of the same fronting cancel out.
        total = sum(s["settlement_delta"] for s in tp.settlements.values())
        assert total == pytest.approx(0.0, abs=0.05)

    def test_rows_are_ordered_and_end_with_a_subtotal(self):
        tp = self._build()
        orders = [r.order for r in tp.rows]
        assert orders == sorted(orders)
        assert tp.rows[-1].kind == "subtotal"

    def test_individual_position_debited_from_the_joint_account_still_balances(self):
        plan = _plan()
        # B's gym is debited from the joint account but stays B's own cost.
        plan.upsert_position(
            CostPosition(
                id="gym_b", name="Gym", owner="B", amount=50.0, debit_account="joint"
            )
        )
        tp = self._build(plan)
        assert tp.balanced, f"unbalanced: {tp.imbalances}"

    def test_shared_costs_without_a_joint_account_are_reported(self):
        # Without a pass-through account every shared position is skipped, no
        # account ends up out of balance, and the plan would declare itself
        # balanced while omitting the largest cost block.
        personal_only = [
            {"id": "a_main", "name": "A main", "person": "A", "type": "personal"},
            {"id": "b_main", "name": "B main", "person": "B", "type": "personal"},
        ]
        plan = _plan()
        model, shared = model_from_plan(
            plan, MONTH, YEAR, split_mode=SPLIT_MODEL_POOLED_EQUAL
        )
        tp = build_transfer_plan(
            plan, personal_only, MONTH, YEAR, split_results=model.calculate_split(shared)
        )
        assert not tp.balanced
        reasons = {u["reason"] for u in tp.unplaced}
        assert "no_shared_account" in reasons

    def test_person_without_an_account_is_reported(self):
        no_account_for_b = [
            {"id": "a_main", "name": "A main", "person": "A", "type": "personal"},
            {"id": "joint", "name": "Joint", "person": "A", "type": "shared"},
        ]
        plan = _plan()
        model, shared = model_from_plan(
            plan, MONTH, YEAR, split_mode=SPLIT_MODEL_POOLED_EQUAL
        )
        tp = build_transfer_plan(
            plan, no_account_for_b, MONTH, YEAR, split_results=model.calculate_split(shared)
        )
        unplaced = [u for u in tp.unplaced if u["reason"] == "no_account_for_person"]
        assert unplaced
        assert unplaced[0]["person"] == "B"

    def test_a_complete_plan_reports_nothing_unplaced(self):
        tp = self._build()
        assert tp.unplaced == []

    def test_imbalance_is_reported_not_hidden(self):
        # Nobody can fund the shared costs -> the pass-through cannot balance.
        plan = BudgetPlan()
        plan.set_income(IncomeEntry(person="A", deposit=0.0))
        plan.upsert_position(
            CostPosition(id="rent", name="Rent", owner=OWNER_SHARED, amount=1000.0)
        )
        model, shared = model_from_plan(
            plan, MONTH, YEAR, split_mode=SPLIT_MODEL_POOLED_EQUAL
        )
        tp = build_transfer_plan(
            plan, self.ACCOUNTS, MONTH, YEAR, split_results=model.calculate_split(shared)
        )
        assert not tp.balanced
        assert "joint" in tp.imbalances


class TestSpreadsheetImportHelpers:
    """Parsing helpers that recover structure from prose and formulas."""

    @pytest.mark.parametrize(
        ("comment", "expected"),
        [
            ("bis inkl. April 2027", (None, "2027-04")),
            ("ab Mai 2026", ("2026-05", None)),
            ("", (None, None)),
            ("irgendein Hinweis", (None, None)),
        ],
    )
    def test_parse_validity(self, comment, expected):
        assert parse_validity(comment) == expected

    def test_loan_from_a_health_insurer_is_a_loan(self):
        # The generic keyword rules check the insurance keyword "tk " before
        # the loan keyword, which files this as insurance.
        assert categorize_position("TK Kredit") == "finance"

    @pytest.mark.parametrize(
        ("name", "category"),
        [
            ("Miete (warm)", "housing_cold"),
            ("Strom Abschlag", "housing_warm"),
            ("Essen Hellofresh Puffer", "groceries"),
            ("Deutschland Ticket", "mobility"),
            ("Netflix", "media"),
            ("Klarna", "finance"),
            ("Privathaftpflichversicherung", "health"),
            ("Rundfunkbeitrag", "media"),
            ("Gastro Budget", "other"),
        ],
    )
    def test_position_categories(self, name, category):
        assert categorize_position(name) == category
