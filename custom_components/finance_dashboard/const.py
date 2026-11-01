"""Constants for the Finance integration."""

DOMAIN = "finance_dashboard"
PLATFORMS = ["sensor", "number", "select"]

# Version — must match manifest.json and companion config.yaml
VERSION = "0.24.4"

# Panel
PANEL_URL_PATH = "finance-dashboard"
PANEL_TITLE = "Finance"
PANEL_ICON = "mdi:finance"
PANEL_COMPONENT_NAME = "finance-dashboard-panel"
# Frontend delivery: ONE static mount, two shells (sidebar panel + Lovelace
# cards) built from the same web-component kit.  The ?v= query busts the
# browser cache on every release (the static path is served with long-lived
# cache headers).
FRONTEND_URL_BASE = f"/{DOMAIN}_static"
PANEL_MODULE_PATH = f"{FRONTEND_URL_BASE}/finance-dashboard-panel.js?v={VERSION}"
# Auto-loaded on every dashboard (registers the kit + all Lovelace cards).
CARDS_MODULE_PATH = f"{FRONTEND_URL_BASE}/finance-dashboard-kit.js?v={VERSION}"

# Storage keys — all sensitive data stored in HA .storage/
STORAGE_KEY_CREDENTIALS = f"{DOMAIN}_credentials"
STORAGE_KEY_TOKENS = f"{DOMAIN}_tokens"
STORAGE_KEY_AUDIT = f"{DOMAIN}_audit_log"
# Institution catalog cache — the /aspsps bank list.  Cached so the setup
# wizard still offers a bank list when Enable Banking is unreachable.
STORAGE_KEY_INSTITUTIONS = f"{DOMAIN}_institutions"

# Backoff after HTTP 429.  Enable Banking documents that background
# fetches should resume after 6 hours; blocking until midnight punished
# a 07:00 rate limit with a whole lost day.  Attended calls (PSU headers
# present) are exempt from the ASPSP 4/day rule entirely, so a 429 there
# is a transient upstream condition and gets a short pause instead.
RATE_LIMIT_BACKOFF_HOURS = 6
RATE_LIMIT_ATTENDED_BACKOFF_MINUTES = 15
# Catalog entries older than this are refreshed from the API on next open.
INSTITUTION_CACHE_TTL_HOURS = 24
STORAGE_VERSION = 1

# Two-layer data storage (encrypted, versioned).  The raw layer is an
# immutable archive of bank responses, chunked one Store per month; the
# ledger is the processed per-account transaction + balance history.
STORAGE_KEY_LEDGER = f"{DOMAIN}_ledger"
STORAGE_KEY_RAW_PREFIX = f"{DOMAIN}_raw_"  # + YYYY_MM
STORAGE_KEY_RAW_INDEX = f"{DOMAIN}_raw_index"
LEDGER_STORAGE_VERSION = 1
LEDGER_STORAGE_MINOR_VERSION = 1
RAW_STORAGE_VERSION = 1
RAW_STORAGE_MINOR_VERSION = 1
OPT_RAW_RETENTION_DAYS = "raw_retention_days"
# 0 = keep forever.  The raw archive is the only source a changed processing
# schema can be rebuilt from, so lifelong history is the default.
DEFAULT_RAW_RETENTION_DAYS = 0
STORAGE_KEY_LEDGER_BACKUP = f"{DOMAIN}_ledger_backup_v"  # + previous version

# Version of the raw → ledger processing (normalisation, ingest, identity).
# Bump it whenever that logic changes: on the next start the ledger is rebuilt
# from the raw archive and the previous ledger is kept as a backup store.
# 2: explicit nulls from the bank (booking_date, names) normalise to "".
PROCESSING_VERSION = 2

# Per-bank fetch budget.  The 4/day cap is the bank's and applies only to
# background (non-PSU) access; the scheduled daily refresh may use one slot.
SCHEDULED_BACKGROUND_SHARE = 1
ATTENDED_DEBOUNCE_SECONDS = 60
INCREMENTAL_OVERLAP_DAYS = 7
DEFAULT_FETCH_DAYS = 90
# First attended fetch of an account per bank session asks for as much history
# as the bank gives, stepping down when it rejects the period.
HISTORY_BACKFILL_DAYS = (3650, 730, 365, DEFAULT_FETCH_DAYS)
TRANSACTION_MAX_PAGES = 200

# Bank config subentries + consent expiry
SUBENTRY_TYPE_BANK = "bank"
CONSENT_EXPIRY_WARN_DAYS = 14
LEGACY_BANK_ID = "legacy"

# Enable Banking
ENABLEBANKING_BASE_URL = "https://api.enablebanking.com"
# Sandbox uses a different app registration
ENABLEBANKING_SANDBOX_URL = "https://api.enablebanking.com"
TOKEN_MAX_AGE_DAYS = 90  # Force re-auth after 90 days (our own policy)
SESSION_MAX_DAYS = 180  # Enable Banking session validity
SESSION_TIMEOUT_MINUTES = 30
ENABLEBANKING_RATE_LIMIT_DAILY = 4

# Transaction categorization
CATEGORY_HOUSING = "housing"
CATEGORY_FOOD = "food"
CATEGORY_TRANSPORT = "transport"
CATEGORY_INSURANCE = "insurance"
CATEGORY_SUBSCRIPTIONS = "subscriptions"
CATEGORY_LOANS = "loans"
CATEGORY_UTILITIES = "utilities"
CATEGORY_INCOME = "income"
CATEGORY_TRANSFERS = "transfers"
CATEGORY_OTHER = "other"

DEFAULT_CATEGORIES = [
    CATEGORY_HOUSING,
    CATEGORY_FOOD,
    CATEGORY_TRANSPORT,
    CATEGORY_INSURANCE,
    CATEGORY_SUBSCRIPTIONS,
    CATEGORY_LOANS,
    CATEGORY_UTILITIES,
    CATEGORY_INCOME,
    CATEGORY_TRANSFERS,
    CATEGORY_OTHER,
]

# Categorization rules — keyword-based auto-detection
# These are default patterns; users can customize via UI
CATEGORIZATION_RULES = {
    CATEGORY_HOUSING: [
        "miete",
        "rent",
        "wohnung",
        "hausgeld",
        "nebenkosten",
        "mietpool",
    ],
    CATEGORY_FOOD: [
        "rewe",
        "edeka",
        "aldi",
        "lidl",
        "kaufland",
        "penny",
        "globus",
        "metro",
        "hellofresh",
        "lieferando",
        "uber eats",
        "supermarkt",
        "lebensmittel",
        "restaurant",
    ],
    CATEGORY_TRANSPORT: [
        "deutschland ticket",
        "deutschlandticket",
        "db ",
        "bahn",
        "tankstelle",
        "shell",
        "aral",
        "uber",
        "taxi",
    ],
    CATEGORY_INSURANCE: [
        "versicherung",
        "insurance",
        "haftpflicht",
        "rechtsschutz",
        "krankenversicherung",
        "tk ",
        "aok",
        "barmer",
    ],
    CATEGORY_SUBSCRIPTIONS: [
        "netflix",
        "spotify",
        "amazon prime",
        "disney",
        "xbox",
        "google one",
        "icloud",
        "youtube premium",
    ],
    CATEGORY_LOANS: [
        "kredit",
        "tilgung",
        "darlehen",
        "loan",
        "finanzierung",
    ],
    CATEGORY_UTILITIES: [
        "strom",
        "gas",
        "wasser",
        "fernwärme",
        "telekom",
        "vodafone",
        "o2",
        "rundfunkbeitrag",
        "gez",
    ],
    CATEGORY_INCOME: [
        "gehalt",
        "lohn",
        "salary",
        "vergütung",
        "überweisung",
    ],
    CATEGORY_TRANSFERS: [
        "umbuchung",
        "übertrag",
        "transfer",
        "sparplan",
    ],
}

# Services
SERVICE_REFRESH_ACCOUNTS = "refresh_accounts"
SERVICE_REFRESH_TRANSACTIONS = "refresh_transactions"
SERVICE_CATEGORIZE = "categorize_transactions"
SERVICE_GET_BALANCE = "get_balance"
SERVICE_GET_SUMMARY = "get_monthly_summary"
SERVICE_SET_BUDGET_LIMIT = "set_budget_limit"
SERVICE_EXPORT_CSV = "export_csv"
SERVICE_REPROCESS_DATA = "reprocess_data"

# Audit log
AUDIT_EVENT_AUTH = "authentication"
AUDIT_EVENT_TOKEN_REFRESH = "token_refresh"
AUDIT_EVENT_DATA_ACCESS = "data_access"
AUDIT_EVENT_CONFIG_CHANGE = "config_change"
AUDIT_EVENT_ERROR = "error"
AUDIT_MAX_ENTRIES = 1000

# Transfer chain detection
TRANSFER_AMOUNT_TOLERANCE = 0.50  # EUR tolerance for fee differences
TRANSFER_TIME_WINDOW_DAYS = 3  # ±days for date matching
TRANSFER_REFUND_WINDOW_DAYS = 14  # Lookback for refund matching
TRANSFER_AUTO_CONFIDENCE = 0.60  # Auto-link threshold (0.0-1.0)
STORAGE_KEY_TRANSFER_OVERRIDES = f"{DOMAIN}_transfer_overrides"

# Refund keywords — transaction text must contain one for refund detection
REFUND_KEYWORDS = [
    "storno",
    "gutschrift",
    "refund",
    "rueckzahlung",
    "rückzahlung",
    "erstattung",
    "retoure",
    "reversal",
    "chargeback",
]

# Household model
SPLIT_MODEL_POOLED_EQUAL = "pooled_equal"
SPLIT_MODEL_EQUAL = "equal"
SPLIT_MODEL_PROPORTIONAL = "proportional"
SPLIT_MODEL_CUSTOM = "custom"

SPLIT_MODELS = [
    SPLIT_MODEL_POOLED_EQUAL,
    SPLIT_MODEL_EQUAL,
    SPLIT_MODEL_PROPORTIONAL,
    SPLIT_MODEL_CUSTOM,
]

# The household spreadsheet this integration replaces uses the pooled model:
# shared costs are paid from the POOLED net income, the remainder is split
# equally, and each person then pays their own individual fixed costs.
DEFAULT_SPLIT_MODEL = SPLIT_MODEL_POOLED_EQUAL

# Budget plan — the migrated spreadsheet model (cost positions + income plan).
# Amounts live in HA .storage/ only; never in git.
STORAGE_KEY_BUDGET_PLAN = f"{DOMAIN}_budget_plan"

# Pots (household budget envelopes) - plan data, stored like the budget plan.
STORAGE_KEY_POTS = f"{DOMAIN}_pots"

# Cost position ownership: a position belongs to a person by NAME, or is shared.
# Ownership is a property of the position, not of the account it is debited from.
OWNER_SHARED = "__shared__"

# Cost position kinds
POSITION_KIND_FIXED = "fixed"  # a recurring fixed debit
POSITION_KIND_BUFFER = "buffer"  # budgeted variable cost: units x unit price
POSITION_KINDS = [POSITION_KIND_FIXED, POSITION_KIND_BUFFER]

# Demo mode
SERVICE_TOGGLE_DEMO = "toggle_demo"

# Budget plan services
SERVICE_IMPORT_SPREADSHEET = "import_spreadsheet"
SERVICE_GET_TRANSFER_PLAN = "get_transfer_plan"
SERVICE_SET_COST_POSITION = "set_cost_position"
SERVICE_DELETE_COST_POSITION = "delete_cost_position"

# Transfer plan — a pass-through account must net to zero. Tolerance in EUR
# absorbs rounding across per-person shares.
TRANSFER_PLAN_ZERO_TOLERANCE = 0.02

# Benchmark metrics — which planned cost categories form the numerator of each
# comparison against the German average. Mirrors the spreadsheet's definitions:
# housing counted rent plus utilities together, food counted both buffers.
BENCHMARK_METRIC_SOURCES = {
    "housing": [CATEGORY_HOUSING, CATEGORY_UTILITIES],
    "food": [CATEGORY_FOOD],
    "loans": [CATEGORY_LOANS],
    "insurance": [CATEGORY_INSURANCE],
    "transport": [CATEGORY_TRANSPORT],
    "subscriptions": [CATEGORY_SUBSCRIPTIONS],
}

# Benchmark location (setup wizard / options). The comparison uses the finest
# level the bundled dataset carries: postcode -> district -> state -> country.
OPT_BENCHMARK_STATE = "benchmark_state"
OPT_BENCHMARK_POSTCODE = "benchmark_postcode"

# Water consumption cannot be derived from banking data — only the utility
# statement knows it. Kept as a manual option so the spreadsheet's water
# comparison survives the migration. Value is a multiple of the German average.
OPT_WATER_RATIO = "water_consumption_ratio"
DEFAULT_WATER_BENCHMARK = 1.0

# Balance selection. Enable Banking returns ISO 20022 balance-type codes, not
# the GoCardless camelCase names. A priority list built from camelCase names
# never matches a real response and silently falls through to "whichever
# balance the bank listed first" — which can be an expected or forward-available
# balance rather than the booked one. Both spellings are listed so demo data
# (camelCase) and live data (ISO) resolve identically.
BALANCE_TYPE_PRIORITY = [
    "CLBD",  # closing booked — the authoritative booked balance
    "closingBooked",
    "ITBD",  # interim booked
    "interimBooked",
    "CLAV",  # closing available
    "closingAvailable",
    "ITAV",  # interim available
    "interimAvailable",
    "OPBD",  # opening booked
    "PRCD",  # previously closed booked
    "XPCD",  # expected
    "FWAV",  # forward available
    "VALU",  # value date
    "OTHR",
    "INFO",
]

# Daily scheduled refresh. Exactly one live fetch per day: a quarter of the
# 4/day/ASPSP budget, leaving three manual refreshes. Not polling — a single
# fixed-time trigger.
OPT_DAILY_REFRESH = "daily_refresh_enabled"
OPT_DAILY_REFRESH_HOUR = "daily_refresh_hour"
OPT_DAILY_REFRESH_MINUTE = "daily_refresh_minute"
DEFAULT_DAILY_REFRESH = True
DEFAULT_DAILY_REFRESH_HOUR = 6
DEFAULT_DAILY_REFRESH_MINUTE = 30

# Body value POST /refresh must carry; anything else never reaches the bank.
EXPLICIT_IMPORT_TRIGGER = "user_import"

# NOTE: there is deliberately no "refresh on panel open" option.  Opening the
# panel is a cache read; live bank calls come only from the explicit import,
# the setup bootstrap and the one daily schedule (see docs/dev/architecture.md,
# "Fetch triggers").


# --- Bank connect flow / config subentries (Phase 2.1) ---
SUBENTRY_TYPE_BANK = "bank"
CONF_ASPSP_NAME = "aspsp_name"
CONF_ASPSP_COUNTRY = "aspsp_country"
CONF_VALID_UNTIL = "valid_until"
CONF_SUBENTRY_ACCOUNTS = "accounts"
# Repairs issue id prefixes (issue creation lives in the manager)
ISSUE_CONSENT_EXPIRING_PREFIX = "consent_expiring_"
ISSUE_CONSENT_EXPIRED_PREFIX = "consent_expired_"


# --- Entities, devices, statistics (Phase 1.4 / 3.1) ---
OPT_SHOW_HOUSEHOLD = "show_household"
DEFAULT_SHOW_HOUSEHOLD = True
# Retention option: 0 (forever) or MIN..MAX days.
MIN_RAW_RETENTION_DAYS = 30
MAX_RAW_RETENTION_DAYS = 36500
STATISTICS_SOURCE = DOMAIN
# ISO 20022 / camelCase names of balances that mean "available to spend".
AVAILABLE_BALANCE_TYPES = ("CLAV", "ITAV", "closingAvailable", "interimAvailable")
# Class-level error codes the "last error" sensor can show (translated).
BANK_ERROR_OPTIONS = (
    "none",
    "consent_expired",
    "rate_limited",
    "unauthorized",
    "server_error",
    "network",
    "other",
)
CONSENT_STATES = ("ok", "expiring", "expired")
