# Setup and plan wizards — target design (decided 2026-11-01)

Decision record from the walkthrough of the setup dialogs. Not implemented yet; the current
behaviour is described in `contracts/setup-wizard.md`. This page is the target.

## Naming

Two terms, never mixed:

| Term (de / en) | What it is | Covers |
|---|---|---|
| **Einrichtung** / Setup | One-time technical and assignment work | persons, account owners, payday, region, notifications, AI consent, points |
| **Haushaltsplan** / Household plan | The plan side of plan vs. actual (`budget_plan.py`) | income, fixed costs, pots, savings goals, result |

- The plan page, its menu entry and every reference are called **Haushaltsplan** everywhere.
  "Budgetplan" and "Monatsplan" go away (`sub.plan`, `setup.plan.*`, `home.year.plan`,
  `bm.*`, `settings.plan_persons`, ...).
- An entry point that opens the setup says "Einrichtung …"; one that opens the plan wizard
  says "Haushaltsplan erstellen" / "… anpassen".
- `home.opt.adjust` ("Plan anpassen") edits a pot today → rename to "Topf anpassen".

## Two wizards

### 1. Einrichtung (technical, assignments)

`Personen → Konten → Zahltag → Region (optional) → Benachrichtigungen → KI (optional) →
Punkte (optional) → Fertig`

- **Personen**: one field per person, "Anzeigename" (prefilled from the HA user). The separate
  "Name der Person" / "Spitzname" pair and the "Aus dem Budgetplan" chips are removed.
- **Konten**: owner per account (person / Haushalt / Offen) as today, plus a line
  "Daten ab <Monat Jahr>" per account from the ledger's earliest booked date
  (`ledger.meta.history[akey].earliest_booked`). The bank's account type (`cash_account_type`:
  giro, savings, card) is shown, never asked. No purpose field: purpose is implicit through
  pot → account binding in the plan. Without any account: a "Bank verbinden" button that opens
  the HA config flow (bank subentry), since the bank redirect has to run there.
- **Zahltag**, **Benachrichtigungen**: as today.
- **KI**: per-purpose consent (see *AI consent* below). Only the purpose "Buchungen
  kategorisieren" (recurring) is asked here.
- **Fertig**: summary, then the plan gate (below): either "Haushaltsplan erstellen" or
  "Haushaltsplan ab ca. <Datum> möglich (noch X Monate Daten)".

### 2. Haushaltsplan erstellen

`Einkommen → Fixkosten → Töpfe → Sparziele → Ergebnis`

Every number comes from the processed data as a **suggestion the user may change**. Nothing is
typed from scratch.

- **Einkommen**: net income per person, suggested from the recognised salary credit (same
  source as the payday suggestion, `detect_recurring` on the person's accounts).
- **Fixkosten**: recurring series (today's `plan_prefill`), owner per position. Optional
  "Haushaltstabelle als Ideengeber" (see below).
- **Töpfe**: variable spending from history (today's `pot_suggestions`), plus per pot
  "gilt für alle Konten / nur für <Konto …>". This binding is how account purpose
  (savings / living costs / pocket money) is expressed.
- **Sparziele**: as today's goals section.
- **Ergebnis**:
  1. monthly balance: income − fixed costs − pots − savings goals = left over, with a clear
     verdict "geht auf" / "es fehlen X €";
  2. per person: contribution and what is left as pocket money (exists in `fd-budget-plan`);
  3. plan vs. history: the plan next to how the household actually lived on average over the
     imported months.

Decided after the backend wave:

- **Rebuild, not merge**: starting the plan wizard on an existing plan rebuilds it — plan
  positions and income are replaced (after an explicit confirmation). Pots and goals keep
  their history and are shown prefilled.
- **Remainder = Taschengeld**: not everything has to be planned. Whatever is left over per
  person becomes an automatic pot "Taschengeld" (one per person, managed by the wizard,
  `auto: "remainder"`). A negative remainder is shown as "es fehlen X €"; saving stays possible.
- **Revoking AI consent**: Settings → KI lists every purpose with its switch, mode, consent
  date and last use.

### Plan gate

The plan wizard opens only with **at least 3 full payday cycles** of booked data (earliest
booked date in the ledger, per the person's payday). Until then every plan entry point shows
the expected date instead of a button.

History depth is the bank's call: the first attended fetch after a consent already asks for
10 years and steps down (2 y → 1 y → 90 d, `HISTORY_BACKFILL_DAYS`). More than 90 days is only
granted right after the SCA of a fresh consent; later fetches never get it back until the next
consent. Nothing to widen on our side; the setup only makes the result visible.

## Spreadsheet as idea source

The `.xlsx` / Google Sheets import no longer supplies numbers to the wizard. Its position
names (e.g. "Puffer Auto", "Rücklage Urlaub") are useful because they name buffers and
reserves the bank data cannot show:

1. Match position names locally against recurring series and categories.
2. Only names that do not match go to the AI, **name only, never an amount**, HA AI first —
   and only after the one-time consent for this purpose (below).
3. Results come back as extra plan suggestions with an empty or data-derived amount.

The import service (`import_budget_plan`) and the plan page import stay for existing users.

## AI consent (applies to every AI use)

- Consent is **per purpose**, never global. Each purpose states whether it runs **once** or
  **recurring**, and shows at most 3 advantages and at most 3 risks.
- A purpose is asked where it is needed: categorisation in the setup, spreadsheet analysis at
  the spreadsheet upload in the plan wizard.
- Every consent is revocable on its own in the settings. Without consent nothing leaves HA.

## HA dialogs

- Options flow: remove `refresh_interval_minutes` (contradicts the no-polling rule); review and
  drop obsolete fields (`split_model`, ...); tighten texts.
- Config flow texts stay, the panel setup links to "Bank hinzufügen".
