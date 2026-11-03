# Frontend Component Architecture

## Overview

The Finance panel is built with vanilla Web Components (Custom Elements, Shadow DOM). Every component
reads the integration's **cache-only HTTP API** itself; no component reads sensor attributes. The panel
follows the decided visual concept (`docs/concepts/20261027-2210-finance-visual-round/`,
gap spec `docs/dev/ui-concept-gap.md`): **one screen, no tab bar**.

- Axis 1, horizon: segment control Heute · Woche · Zyklus · Jahr at the top (with sub-labels, swipeable).
- Axis 2, perspective: Person ⇄ Haushalt as an oval pill toggle fixed to the bottom of the screen, in both views.
- Everything else sits behind an icon or entry and opens a **subpage** with a back button.

## Component tree

```
finance-dashboard-panel            shell: fd-home + subpage router + toast host
 |-- fd-home                       Start (the one screen)
 |    |-- [slot menu] ha-menu-button   narrow screens only, inside the top bar
 |    '-- fd-cycle-detail          Zyklus: strip under the tank (mobile) / analysis in the side column (desktop)
 '-- subpage (one at a time, #viewSub)
      |-- fd-subpage-header + fd-freshness       Datenstand
      |-- fd-subpage-header + fd-settings mode=page section=…   Einstellungen
      |-- fd-transactions          (own header) transaction list (read-only on phones and tablets, categorising on desktop)
      |-- fd-questions             (own header) Fragen / flash cards
      |-- fd-contracts             (own header) Verträge
      |-- fd-benchmark             (own header) Vergleich
      '-- fd-budget-plan           (own header) Haushaltsplan
 fd-setup                          Einrichtung wizard (persons, accounts, payday, region, notifications, AI, points, done), its own full-screen layer
 fd-categorize (dialog)            desktop link from Fragen
```

Lovelace cards (`finance-dashboard-card`, `finance-status-chip`, `fd-budget-config`, `fd-categorize`)
are separate and not part of the panel. None of them reads sensor attributes: `fd-budget-config`
drives the split/remainder select entities and takes its option list from them.

## Start (`fd-home.js`)

Top bar: `[menu (narrow)] [freshness ✓ 06:30] · [Eilmeldung pill, only with alerts] · [★ questions] [⚙ settings]`.
No "Finance" title. The freshness button shows the `as_of` time (`HH:MM` today, `gestern HH:MM`, else `dd.mm.`;
desktop prefixes the status word, "aktuell · 06:30") and opens **Datenstand**. The gear opens **Einstellungen**
on every width. The star opens **Fragen**.

Segment sub-labels: `Mi., 29.10.` · `KW 44` · `noch N Tage` (desktop: `dd.mm.–dd.mm.`) · `2026`.

Bottom pill: avatar initial + `person.display_name` (fallback: first token of the name; ellipsis, full name in the
tooltip and aria-label) with "deine Töpfe", and ⌂ Haushalt with "gemeinsam". `position: fixed`, aligned to the
panel's content box from JS (ResizeObserver), so it never floats mid-screen and clears the HA sidebar. It stays
visible in the household view; it is hidden only when the viewer maps to no person (`viewer_person: null`).

Horizons (person view = own items only; household view = shared pots + persons as totals):

| Horizon | Main column |
|---|---|
| Heute | coloured "noch frei" figure (no status chip), meter of what is left, today's spend, per day; "Deine/Gemeinsame Töpfe" with "+" and up to two suggestion chips when empty; persons totals in the household view |
| Woche | verdict band, carry-over "+x € aus KW nn mitgenommen", day bars vs. the Soll line, thin dashed zero-carry line, day amounts for past days only, "wird diese Woche noch abgebucht" |
| Zyklus | **hero** (free money until cycle end, verdict pill, labelled bar with today marker and dashed Soll, three KPI tiles; household: shared costs + shares, neutral blue-grey; ⓘ flips to the cycle rule), Fixkosten gedeckt or "Plan fehlt", then two columns: **ledger** of the last 14 days by day (`recent` in `/home`, admin only; link "Alle Buchungen" to fd-transactions) and Als Nächstes (top 3 + mehr) + one **Einrichten · N offen** strip (hidden on phones unless a blocker) replacing the setup cards; fd-cycle-detail under the grid (mobile) or in the desktop cards below |
| Jahr | Jan–Dec status squares of the calendar year ("keine Daten" for empty months), vs. Vorjahr, entries Verträge · Vergleich · Haushaltsplan |

**Spielraum without pots** (spec § 1.4): with no pot budget the screen never collapses to "Noch keine Töpfe".
It shows the view's own Spielraum: `person_budget {budget, spent, remaining, source}` from `/home` (person view),
else `GET household_summary?cycle=current[&view=person]` — the viewer's own owner row (person view) or the
household totals (household view): income − expenses, Soll-Linie over the cycle, "Gehalt erwartet am …" while
income is pending.

A setup card sits *above* the content only while something is missing: wizard not completed (admin: CTA;
member: calm note), no bank connected, or accounts unassigned (→ Einstellungen › accounts).

Desktop side column (`@container ≥ 760 px`, purple ◆ marker):

| Horizon | Side column |
|---|---|
| Zyklus | fd-cycle-detail analysis, **Optimierung** (per pot: spent / plan, deviation from the Soll-Linie, projected gap, buttons Plan anpassen · Regel anlegen · Zum Vertrag) |
| Woche | **Budget anpassen** (move cycle budget between two pots via two `PUT /pots`) |
| Jahr | Optimierung light + Verträge |
| all | **Konten** (`/balances` + `/assignments`): own accounts in detail, another person's accounts as a total only ("Details sieht nur X"); pot management + dismissible "neuer Topf" suggestions |

## Subpage router (`finance-dashboard-panel.js`)

`fd-navigate {target, section?}` (bubbling, composed) from any component:

| target | opens |
|---|---|
| `freshness` | Datenstand (fd-freshness, shell draws fd-subpage-header) |
| `settings` | `<fd-settings mode="page" section=…>` (shell draws the header) |
| `transactions`, `questions`, `contracts`, `benchmark`, `plan` | the component, which draws its own header |
| `setup` | the wizard layer (fd-setup) |
| `back`, `settings-closed` | closes the subpage |

Opening a subpage pushes a history entry `#sub=<target>`; browser back and the header's back button close it, and
a reload with the hash reopens it. Esc closes it too. Legacy close events `fd-questions-close` and
`fd-freshness-back` are honoured.

The Haushaltsplan subpage gets its actuals from `GET /household_summary` (mapped onto the `data` shape
fd-budget-plan reads), not from the retired sensor tree.

## Bank calls and data actions

Opening the panel **never** fetches from the bank. The only live fetch is the Datenstand button
**Neu importieren** → `fd-refresh-requested` → the shell POSTs `finance_dashboard/refresh` with body
`{"trigger":"user_import"}` (the backend refuses a bare POST with 400). The request carries the PSU context,
so it is attended and not bound to the bank's background 4/day cap. **Aktualisieren** →
`fd-reprocess-requested` → `POST finance_dashboard/reprocess` (stored raw data only). Both report through the
shell's toast host and reload Start and Datenstand. In demo mode Neu importieren only shows a note.

Datenstand (`fd-freshness`) shows Stand, last import / processing, the bank connections from `/bank_status`
(consent, today's background budget, last manual fetch, block, last error, renew / manage link), the import log,
monthly validity and the derivation check (`/freshness`, admin details). Desktop pointers get a link to the
transaction list.

## Events

| Event | Source | Handled by | Purpose |
|---|---|---|---|
| `fd-navigate {target, section?}` | fd-home, fd-freshness, fd-subpage-header, fd-cycle-detail, fd-settings, … | shell | subpage router (above) |
| `fd-open-plan-wizard` | fd-setup (done step), fd-home, fd-budget-plan, fd-cycle-detail | shell | open the plan wizard ("Haushaltsplan erstellen"); entry points show the expected date instead of a button while `GET /plan_wizard/gate` is not ready |
| `fd-refresh-requested` | fd-freshness | shell | Neu importieren (attended bank fetch) |
| `fd-reprocess-requested` | fd-freshness | shell | Aktualisieren (`POST /reprocess`) |
| `fd-toast {message, type}` | any | shell | toast host |
| `fd-assignments-saved`, `fd-settings-saved`, `fd-pots-changed` | fd-settings, … | shell | reload Start |
| `fd-demo-toggle` | fd-home (not configured), settings | shell | `POST /demo/toggle`, Start reads `?demo=1` |
| `fd-categorize-requested` | (legacy) | shell | opens Fragen |
| `fd-questions-all` | fd-questions | shell | categorise dialog (desktop) |

## Data sources (all cache reads)

`/home`, `/household_summary`, `/plan_vs_actual`, `/budget_plan`, `/balances`, `/assignments` (admin),
`/bank_status`, `/freshness`, `/refresh_status`, `/transactions` (admin), `/pots`. Writes: `/pots`,
`/setup…`, `/assignments`, `/demo/toggle`, `/reprocess`, `/refresh` (explicit trigger only).

## Localisation

`frontend/locales/de.json` and `en.json` hold the shell, Start and Datenstand strings (`sub.*`, `shell.*`,
`home.*`, `fr.*`, …). Components built in parallel (fd-cycle-detail, fd-transactions, fd-subpage-header,
fd-setup, fd-settings, fd-questions, fd-contracts, fd-benchmark) carry fallback dictionaries in their own file.
Placeholders use `$name`; plurals use a `_one` sibling key.

## Kit loading

`finance-dashboard-kit.js` is the single entry point: it loads `fd-shared-styles.js` first (defines
`window._fd`, tokens, tooltip and scrollbar styles), then every component with `Promise.allSettled`, so one
broken module leaves its element undefined instead of blanking the panel. The panel and every card share
the same `?v=<VERSION>` query for cache-busting.

## Responsive and overflow rules

- Every flex/grid text column has `min-width: 0`; amounts are `flex: none` / `white-space: nowrap`.
- Long merchant labels (Als Nächstes, upcoming) wrap with `overflow-wrap: anywhere`, clamped to two lines; the
  `vorgemerkt` tag sits inline after the date.
- Names in the pill, pot rows and account rows truncate with an ellipsis; the full name is in the tooltip.
- Touch targets ≥ 44 px; tooltips via `data-tip` (never `title`); every action has a touch path.
- Panel padding: 24 px desktop, 8 px below 600 px.

## Security

- IBANs arrive masked from the API; the Konten column shows `iban_masked` only.
- Individual transactions are admin-only (`/transactions`); another person's accounts appear as totals only.
- All user-provided text goes through `window._fd.escHtml`; amounts never go into `data-*` attributes.
- Shadow DOM per component for style isolation.
