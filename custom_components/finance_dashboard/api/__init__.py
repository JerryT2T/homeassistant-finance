"""Finance HTTP API — module package.

Exposes ``async_register_api`` as the single entry point for registering
all HTTP endpoints.  Consumers that previously imported from the flat
``api.py`` module can continue to use::

    from .api import async_register_api

because this package's ``__init__`` re-exports the same name.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from ._helpers import _get_manager, _get_setup_client
from .ai_consent import VIEWS as AI_CONSENT_VIEWS
from .history_import import VIEWS as HISTORY_IMPORT_VIEWS
from .labels import VIEWS as LABEL_VIEWS
from .ownership import VIEWS as OWNERSHIP_VIEWS
from .refunds import VIEWS as REFUND_VIEWS
from .review import VIEWS as REVIEW_VIEWS
from .assignments import FinanceDashboardAssignmentsView
from .contracts import (
    FinanceDashboardAccountSavingsView,
    FinanceDashboardContractOverridesView,
    FinanceDashboardContractQueryView,
    FinanceDashboardContractsView,
    FinanceDashboardContractView,
    FinanceDashboardReservesView,
)
from .data import (
    FinanceDashboardBalanceView,
    FinanceDashboardBankStatusView,
    FinanceDashboardSettingsView,
    FinanceDashboardSummaryView,
    FinanceDashboardTransactionsView,
    FinanceDashboardTransferChainsView,
)
from .demo import FinanceDashboardDemoDataView, FinanceDashboardDemoToggleView
from .home import (
    FinanceDashboardHomeView,
    FinanceDashboardPotCarryView,
    FinanceDashboardPotsView,
)
from .household import FinanceDashboardHouseholdSummaryView
from .plan import (
    FinanceDashboardBenchmarkView,
    FinanceDashboardBudgetPlanView,
    FinanceDashboardPlanImportUrlView,
    FinanceDashboardPlanImportView,
    FinanceDashboardPlanIncomeView,
    FinanceDashboardPlanPositionView,
    FinanceDashboardPlanUploadView,
    FinanceDashboardPlanVsActualView,
    FinanceDashboardTransferPlanView,
)
from .questions import (
    FinanceDashboardQuestionAnswerView,
    FinanceDashboardQuestionHistoryView,
    FinanceDashboardQuestionsView,
)
from .refresh import (
    FinanceDashboardFreshnessView,
    FinanceDashboardRefreshStatusView,
    FinanceDashboardRefreshTriggerView,
    FinanceDashboardReprocessView,
)
from .plan_ideas import VIEWS as PLAN_IDEAS_VIEWS
from .plan_wizard import (
    FinanceDashboardPlanWizardFixedView,
    FinanceDashboardPlanWizardGateView,
    FinanceDashboardPlanWizardIncomeSuggestionsView,
    FinanceDashboardPlanWizardIncomeView,
    FinanceDashboardPlanWizardResultView,
    FinanceDashboardPlanWizardView,
)
from .setup import (
    FinanceDashboardAiTestView,
    FinanceDashboardAiView,
    FinanceDashboardGoalsView,
    FinanceDashboardGoalView,
    FinanceDashboardPaydaySuggestionsView,
    FinanceDashboardPlanPrefillView,
    FinanceDashboardPointsView,
    FinanceDashboardPotSuggestionsView,
    FinanceDashboardSetupView,
)

_LOGGER = logging.getLogger(__name__)

__all__ = [  # noqa: RUF022  # grouped by category, not alphabetical
    "async_register_api",
    # Helpers (re-exported for backwards-compat with tests that import from .api)
    "_get_manager",
    "_get_setup_client",
    # Data endpoints
    "FinanceDashboardBalanceView",
    "FinanceDashboardBankStatusView",
    "FinanceDashboardSettingsView",
    "FinanceDashboardTransactionsView",
    "FinanceDashboardSummaryView",
    "FinanceDashboardTransferChainsView",
    # Budget plan (migrated spreadsheet model)
    "FinanceDashboardBudgetPlanView",
    "FinanceDashboardTransferPlanView",
    "FinanceDashboardPlanVsActualView",
    "FinanceDashboardBenchmarkView",
    "FinanceDashboardPlanPositionView",
    "FinanceDashboardPlanIncomeView",
    "FinanceDashboardPlanImportView",
    "FinanceDashboardPlanImportUrlView",
    "FinanceDashboardPlanUploadView",
    # Home screen + pots
    "FinanceDashboardHomeView",
    "FinanceDashboardPotsView",
    "FinanceDashboardPotCarryView",
    "FinanceDashboardAssignmentsView",
    "FinanceDashboardHouseholdSummaryView",
    "FinanceDashboardContractQueryView",
    "FinanceDashboardContractsView",
    "FinanceDashboardContractView",
    "FinanceDashboardContractOverridesView",
    "FinanceDashboardReservesView",
    "FinanceDashboardAccountSavingsView",
    "FinanceDashboardQuestionAnswerView",
    "FinanceDashboardQuestionHistoryView",
    "FinanceDashboardQuestionsView",
    "FinanceDashboardSetupView",
    "FinanceDashboardPaydaySuggestionsView",
    "FinanceDashboardPotSuggestionsView",
    "FinanceDashboardPlanWizardView",
    "FinanceDashboardPlanWizardGateView",
    "FinanceDashboardPlanWizardIncomeSuggestionsView",
    "FinanceDashboardPlanWizardIncomeView",
    "FinanceDashboardPlanWizardFixedView",
    "FinanceDashboardPlanWizardResultView",
    # Refresh
    "FinanceDashboardRefreshStatusView",
    "FinanceDashboardReprocessView",
    "FinanceDashboardFreshnessView",
    "FinanceDashboardRefreshTriggerView",
    # Demo
    "FinanceDashboardDemoToggleView",
    "FinanceDashboardDemoDataView",
]


async def async_register_api(hass: HomeAssistant) -> None:
    """Register all Finance HTTP API endpoints."""
    hass.http.register_view(FinanceDashboardBalanceView())
    hass.http.register_view(FinanceDashboardTransactionsView())
    hass.http.register_view(FinanceDashboardSummaryView())
    hass.http.register_view(FinanceDashboardRefreshStatusView())
    hass.http.register_view(FinanceDashboardRefreshTriggerView())
    hass.http.register_view(FinanceDashboardReprocessView())
    hass.http.register_view(FinanceDashboardFreshnessView())
    # Bank linking lives in the config subentry flow (Settings -> Devices & services)
    hass.http.register_view(FinanceDashboardBankStatusView())
    hass.http.register_view(FinanceDashboardSettingsView())
    hass.http.register_view(FinanceDashboardTransferChainsView())
    hass.http.register_view(FinanceDashboardDemoToggleView())
    hass.http.register_view(FinanceDashboardDemoDataView())
    # Budget plan endpoints (migrated spreadsheet model)
    hass.http.register_view(FinanceDashboardBudgetPlanView())
    hass.http.register_view(FinanceDashboardTransferPlanView())
    hass.http.register_view(FinanceDashboardPlanVsActualView())
    hass.http.register_view(FinanceDashboardBenchmarkView())
    hass.http.register_view(FinanceDashboardPlanPositionView())
    hass.http.register_view(FinanceDashboardPlanIncomeView())
    hass.http.register_view(FinanceDashboardPlanImportView())
    hass.http.register_view(FinanceDashboardPlanUploadView())
    hass.http.register_view(FinanceDashboardPlanImportUrlView())
    hass.http.register_view(FinanceDashboardHomeView())
    hass.http.register_view(FinanceDashboardPotsView())
    hass.http.register_view(FinanceDashboardPotCarryView())
    hass.http.register_view(FinanceDashboardAssignmentsView())
    hass.http.register_view(FinanceDashboardHouseholdSummaryView())
    hass.http.register_view(FinanceDashboardContractsView())
    hass.http.register_view(FinanceDashboardContractQueryView())
    hass.http.register_view(FinanceDashboardContractView())
    hass.http.register_view(FinanceDashboardContractOverridesView())
    hass.http.register_view(FinanceDashboardReservesView())
    hass.http.register_view(FinanceDashboardAccountSavingsView())
    hass.http.register_view(FinanceDashboardQuestionsView())
    hass.http.register_view(FinanceDashboardQuestionAnswerView())
    hass.http.register_view(FinanceDashboardQuestionHistoryView())
    hass.http.register_view(FinanceDashboardSetupView())
    hass.http.register_view(FinanceDashboardPaydaySuggestionsView())
    hass.http.register_view(FinanceDashboardPotSuggestionsView())
    hass.http.register_view(FinanceDashboardPlanPrefillView())
    hass.http.register_view(FinanceDashboardGoalsView())
    hass.http.register_view(FinanceDashboardGoalView())
    hass.http.register_view(FinanceDashboardPointsView())
    hass.http.register_view(FinanceDashboardAiView())
    hass.http.register_view(FinanceDashboardAiTestView())
    hass.http.register_view(FinanceDashboardPlanWizardView())
    hass.http.register_view(FinanceDashboardPlanWizardGateView())
    hass.http.register_view(FinanceDashboardPlanWizardIncomeSuggestionsView())
    hass.http.register_view(FinanceDashboardPlanWizardIncomeView())
    hass.http.register_view(FinanceDashboardPlanWizardFixedView())
    hass.http.register_view(FinanceDashboardPlanWizardResultView())
    for view in (*AI_CONSENT_VIEWS, *PLAN_IDEAS_VIEWS, *LABEL_VIEWS, *REFUND_VIEWS, *HISTORY_IMPORT_VIEWS, *OWNERSHIP_VIEWS, *REVIEW_VIEWS):
        hass.http.register_view(view())
    _LOGGER.debug("Finance API endpoints registered")
