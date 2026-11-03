# Build Log

## 0.39.0 — 2026-11-03
Version: 0.39.0
Branch: feat/home-hero-ledger
Changes:
- feat(home): the cycle view leads with a hero - free money until the cycle end, a verdict pill, a labelled bar (today with day count, dashed "Soll bis heute") and three tiles (income, spending, free per day; in the household view shared costs and each person's share) - and below it the latest bookings grouped by day next to "Als Nächstes" and one "Einrichten" strip instead of the separate setup cards
- feat(home): on desktop the status chip, the horizon tabs and the question count share one top row; the household view uses a neutral blue-grey, orange only ever means over budget or urgent, and purple only marks the "Nur am Desktop" chip
- feat(transactions): the transaction list is now reachable on phones and tablets - read-only, grouped by day, searchable; the account column shows only when the list spans several accounts, pending bookings are dashed; categorising stays on desktop
- feat(home): the home payload carries the last 14 days of bookings for administrators only (no IBAN, no purpose text) and cycle income/spending totals; other users see totals only
- fix(ui): no text below 12 px in the touched views
- feat(home): on the cycle view the analysis, account and pot cards sit behind one closed disclosure on desktop, so the Einrichten strip leads
- fix(home): a negative remainder always reads as over the frame; the household tiles name each person's own spending; the data chip says "Aktuell · heute 06:30"

## 0.38.0 — 2026-11-02
Version: 0.38.0
Branch: claude/reverent-merkle-1b5657
Changes:
- feat(import): the booking-history import now also reads PDF bank statements - the text is extracted on your Home Assistant (no external call), every booking line with date and amount becomes a row, and you get the same preview (new, duplicates, overlap with the bank's own period, invalid rows) and the same per-import undo as with CSV or XLSX
- feat(import): a PDF whose amounts carry no debit marker is not guessed - it is offered to your own AI provider only after the separate consent, with IBANs masked; password-protected and scanned PDFs get a clear message instead

## 0.37.0 — 2026-11-02
Version: 0.37.0
Branch: feat/118-contract-search
Changes:
- feat(contracts): the contracts tab gets a search over name and payment purpose, filter chips for type and status (active, overdue, ended, candidate), a filter sheet for category, label, owner and monthly amount, and sorting by deadline or amount; the totals card sums exactly what the filter shows and the filter is remembered per browser
- feat(contracts): optional AI search - ask in your own words ("was zahlen wir im Jahr für Energie?") and your own AI provider turns the question into a filter that Finance applies itself; only the question and the names of categories, labels and persons are sent, never amounts, IBANs, dates or bookings, and only after a separate consent for this purpose that counts against your monthly AI budget
- feat(contracts): an AI answer that cannot be read fully shows the understood filter and what was dropped, so you correct it instead of getting an error

## 0.36.0 — 2026-11-02
Version: 0.36.0
Branch: feat/117-contract-review
Changes:
- feat(contracts): every contract can be fully edited in one sheet - name, category, rhythm, type, plan amount, owner, notice terms and labels - and reset to the detected defaults
- feat(contracts): merge series that belong together, split one payee by contract number or amount, and assign single bookings (settlements, refunds, PayPal payments) to a contract; merges with a different rhythm or direction are refused, every step can be undone
- feat(contracts): add yearly contracts by hand that the bank has not shown yet; "Kein Vertrag" hides a series for good and releases anything merged into it
- feat(questions): unsure contract candidates and price changes become questions in the weekly question flow (Vertrag, Abo, regelmäßige oder unregelmäßige Ausgabe, kein Vertrag), each answered question counts once

## 0.35.0 — 2026-11-02
Version: 0.35.0
Branch: feat/121-history-import
Changes:
- feat(import): load 13 to 24 months of booking history from your online banking's CSV or XLSX export (Einstellungen, Buchungshistorie) so yearly contracts are recognised right away instead of after two years; the file is read locally, you see a preview with new rows, duplicates and invalid rows before anything is saved, and every import can be undone as a whole
- feat(import): a file whose columns are not recognised can optionally be read by your own AI provider - only after a separate one-time consent that names exactly what is sent (file content including amounts and dates, IBANs masked locally first) and with the calls counted against your monthly AI budget
- feat(import): where the bank delivers bookings itself, its data always wins - duplicates and rows inside the bank's own period are not imported, and a later bank backfill replaces matching imported rows

## 0.34.0 — 2026-11-02
Version: 0.34.0
Branch: feat/119-refund-matching
Changes:
- feat(refunds): health insurance refunds are matched to the doctor, pharmacy or therapy bills they pay back - in full, in part, or one refund for several bills, up to eight weeks later - and netted in the cycle of the bill, so health costs show what the household really pays and the refund no longer counts as income
- feat(refunds): unsure matches become a question in the question flow ("Gehört diese Erstattung zu dieser Ausgabe?"); in the booking dialog a refund can be assigned to several expenses by hand and reset to automatic
- feat(refunds): bookings labelled "Erstattungsfähig" without a refund yet show as open claims ("Erstattung offen")

## 0.33.0 — 2026-11-02
Version: 0.33.0
Branch: feat/116-advance-settlement
Changes:
- feat(contracts): energy, water, heating and service-charge contracts are recognised as "Verbrauchsabhängig" - the monthly advance stays one stable contract, and the yearly settlement (Nachzahlung or Erstattung) is shown separately under "Abrechnungen" instead of breaking the series
- feat(contracts): the expected next back-payment becomes a monthly reserve ("Erwartete Jahresabrechnung"); it is the last settlement minus what a raised advance already covers, and an expected refund lowers the contract's yearly cost instead
- feat(contracts): a settlement without a keyword can be assigned from the payee's other bookings in the contract sheet, and removed again; "Verbrauchsabhängig" can be switched on or off
- fix(contracts): a price step stays reported as a price change after the next payments at the new price, not only on the first one
- fix(categories): mobile, streaming, app-store and automobile-club payments land in their life area more often

## 0.32.0 — 2026-11-02
Version: 0.32.0
Branch: feat/113-labels
Changes:
- feat(labels): contracts and bookings can carry any number of labels next to their category - 15 starter labels (Energie, Versicherung, Erstattungsfähig, Beruflich / Werbungskosten, Haushaltsnahe Dienstleistung, ...) plus your own; labels stay in Home Assistant
- feat(labels): every booking of a contract shows the contract's category and labels as "vom Vertrag" - fixing the contract once fixes all its bookings; a booking can get extra labels of its own in the new booking dialog
- feat(labels): automatic labels show the payment channel (PayPal, später bezahlen, Karte, Lastschrift) and "Preis gestiegen" / "Sonderkündigung möglich"; they cannot be edited

## 0.31.0 — 2026-11-02
Version: 0.31.0
Branch: feat/112-life-areas
Changes:
- feat(categories): spending is sorted into eight life areas - Wohnen kalt, Wohnen warm, Lebensmittel & Haushalt, Mobilität, Gesundheit & Absicherung, Freizeit, Medien & Kommunikation, Finanzen & Verpflichtungen - so every euro lands in exactly one area; income has its own areas (Lohn & Gehalt, Staatliche Leistungen, Kapitalerträge, Erstattungen, Von Privatpersonen); Umbuchungen stay a status, not a category
- feat(categories): on the first start after the update, learned merchants, answered questions, the AI cache, budget-plan positions, pots and contract categories move to the new areas once, after a backup of each store; energy and telecom (formerly "Nebenkosten") and groceries and eating out (formerly "Lebensmittel") are split by fixed keywords, and what no keyword places is asked again in the question flow instead of guessed
- feat(categories): budget-limit entities move to the new areas and keep their limits; the limits for income and transfers are removed
- change(categories): general online shopping (Amazon, fashion, electronics) has no area of its own any more and lands in the question flow; restaurants and delivery services count as Freizeit

## 0.30.0 — 2026-11-01
Version: 0.30.0
Branch: feat/115-pending-and-kind-totals
Changes:
- feat(contracts): the contracts page shows "Fixkosten" (contracts and subscriptions) and "Regelmäßige Ausgaben" (regular and irregular spending) as separate totals; uncertain detections never count, and the API returns both totals
- fix(contracts): a debit still pending at the turn of the month counts as the current payment, so the contract shows it as last payment and no longer reports "Zahlung fehlt"; amounts still come only from booked payments

## 0.29.0 — 2026-11-01
Version: 0.29.0
Branch: feat/114-plan-amount-auto
Changes:
- feat(contracts): the plan amount of a recurring payment is "Automatisch" by default: the new price after a price change, otherwise the median, so one catch-up or double charge no longer inflates monthly and yearly costs; contracts without a chosen plan amount switch from the highest payment to this rule, so some reserves and yearly costs drop
- feat(contracts): the edit sheet lets you choose the plan amount (Automatisch, Höchster, Durchschnitt, Letzter, Median, Fester Betrag) and shows the resulting monthly and yearly cost right away
- fix(contracts): a quarterly payment with one doubled instalment and a weekly meal kit with skipped weeks are detected again; skipped weeks or months show as "x × pausiert" while the cost keeps the full rhythm; a series that paused before is not marked ended inside a pause of the same length, and only fixed-price series may pause or carry an outlier

## 0.28.0 — 2026-11-01
Version: 0.28.0
Branch: feat/111-contract-kinds
Changes:
- feat(contracts): every recurring payment has a kind — Vertrag, Abo, Regelmäßige Ausgabe or Unregelmäßig — suggested from the payments (yearly, contract words and numbers, subscription words, weekly or everyday spending) and changeable in the edit sheet; the choice survives new imports
- feat(contracts): the contracts page shows the kind on every row and filters the list and its totals by kind
- feat(contracts): regular and irregular spending no longer shows a notice deadline or sends a notice reminder; notice defaults follow the kind (subscriptions monthly without notice, phone and internet contracts 24 months)

## 0.27.1 — 2026-11-01
Version: 0.27.1
Branch: fix/109-own-name-candidates
Changes:
- fix(contracts): a loan instalment, insurance or phone bill paid to an account in your own name (an unlinked bank) is no longer invisible: with a contract word or number and a stable amount it appears under "Prüfen" with the reason "payment to an own name"; plain savings transfers stay hidden, also when their text names a contract word next to a savings word ("Sparplan Rate", "Rücklage Strom")
- fix(contracts): Darlehen, Kredit, Mobilfunk and Strom count as contract words for the confidence score

## 0.27.0 — 2026-11-01
Version: 0.27.0
Branch: claude/einrichtungsdialoge-ueberarbeiten-6752b6
Changes:
- feat(setup): the setup (Einrichtung) covers only technical and assignment steps: persons with one display name, accounts with bank account type and "data since", payday, region, notifications, AI, points; the last step opens the household plan or says when it becomes possible
- feat(plan): new "Haushaltsplan erstellen" wizard: income suggested from the salary credit, fixed costs from recurring payments, pots with optional account binding, savings goals and a result with monthly balance, per person and plan vs. history; it needs 3 full payday cycles of booked data and rebuilds an existing plan after a confirmation
- feat(plan): what is left over becomes an automatic "Taschengeld" pot per person; a shortfall is shown, saving stays possible
- feat(plan): a household spreadsheet serves as an idea source: position names are matched locally, unmatched names go to the AI only with a one-time consent, amounts never leave Home Assistant
- feat(ai): AI consent is per purpose (categorisation recurring, sheet analysis once) with up to 3 advantages and risks each, revocable on its own in Settings → KI
- refactor(ui): the plan is called "Haushaltsplan" everywhere; the pot button reads "Topf anpassen"
- refactor(options): the options dialog drops the unused refresh interval, currency and panel switch and the split model (covered by its select entity)
- fix(plan): saving income from the wizard keeps stored insurance and tax adjustments

## 0.26.0 — 2026-11-01
Version: 0.26.0
Branch: feat/130-review-candidates
Changes:
- feat(contracts): the contracts page has a "Prüfen" section (admins) listing repeating payments that do not clearly look like a contract, with a "Warum?" tooltip naming the reasons
- feat(contracts): "Ist ein Vertrag" takes a candidate over as a contract (fixed costs, reserves, reminders); "Kein Vertrag" hides it for good, also after new imports

## 0.25.0 — 2026-11-01
Version: 0.25.0
Branch: feat/110-series-confidence
Changes:
- feat(contracts): every detected series gets a confidence score with its reasons (direct debit or contract number vs. card payment, stable amount, number of payments, regular day of month, category, contract keywords); the contracts API returns `confidence` and `candidate`
- fix(contracts): card purchases at a café, drugstore or pharmacy that happen to recur monthly are candidates, not contracts: they no longer count in fixed costs, reserves, plan proposals or notice reminders

## 0.24.4 — 2026-11-01
Version: 0.24.4
Branch: fix/107-paypal-transaction-date
Changes:
- fix(contracts): subscriptions paid through a linked PayPal account are found even when PayPal's own lines carry no booking date; the transaction date counts as the date of such a line (new field `transactionDate`, the stored booking date stays untouched)
- fix(household): a bank-side PayPal debit is only dropped when a dated PayPal line of the same amount within five days already counts the purchase; otherwise it counts, so nothing disappears and nothing counts twice
- feat(freshness): the Datenstand page warns admins about accounts with bookings that carry no date at all, with the count per account
- fix(household): a PayPal funding credit (bank to PayPal) is no income; a pure PayPal top-up counts on neither side
- fix(home): carry-over and cycle-history texts show their amounts instead of literal "{amount}" placeholders

## 0.24.3 — 2026-11-01
Version: 0.24.3
Branch: fix/108-payee-split
Changes:
- fix(contracts): two loans or contracts at one payee are two contracts with their full amounts when the transfer text names different contract, loan, customer or mandate numbers that run in parallel; a number that only changes once stays one contract
- fix(contracts): a subscription at a payee that also sells one-off purchases (app store, BNPL provider) is found on its own; the one-offs and finite instalments ("Teil 1/3") stay out, a real price step is still one series
- fix(contracts): energy advances stay one contract even when a yearly settlement from the same supplier sits between them
- feat(contracts): split parts keep their ids through hashed reference and amount-band keys in the alias table (no numbers or amounts stored in clear)

## 0.24.2 — 2026-11-01
Version: 0.24.2
Branch: fix/120-processor-merchants
Changes:
- fix(categorizer): purchases paid via PayPal, Klarna, SumUp and other processors are categorised by the remittance text (the merchant, the order), never by the processor's own name; a line without a recognisable merchant stays "other" and is asked in the question flow
- fix(questions): every purchase through a processor gets its own merchant ("Ihr Einkauf bei …"), so answering one PayPal purchase no longer recategorises all of them; an earlier answer stored for the shared PayPal key no longer applies
- fix(banking): counterparty names delivered as Latin-1 mojibake ("S.Ã  r.l.") are repaired at import, replacement characters are dropped
- chore(release): manifest and const carry the version again (0.24.1 had shipped with the old number)

## 0.24.1 — 2026-11-01
Version: 0.24.1
Branch: chore/122-stable-contract-ids
Changes:
- fix(contracts): a payee whose name the bank spells differently (punctuation, legal form, broken encoding such as "S.Ã  r.l.") stays one contract with the same id, so term, notice, plan mode and category you entered are kept
- feat(contracts): name variants are remembered in an alias table in the contract store (names only, no amounts), so a contract keeps its id after the old spelling has left the bank history
- test: synthetic acceptance fixtures for contract detection measure recall, false positives and annual-total deviation for the Contract Detection milestone (#106)

## 0.24.0 — 2026-10-29
Version: 0.24.0
Branch: claude/ai-budget-points-history
Changes:
- feat(ai): the monthly AI budget is a number field (0-1000, default 100) instead of a 0-100 slider; free providers such as Gemini via Home Assistant no longer run dry after 100 calls
- fix(ai): merchants already answered by the AI are learned from the cache without a new call, also when the budget is used up; before, a cached answer whose memory save was lost never reached the bookings
- feat(questions): the star page has an "Offen | Verlauf" switch; "Verlauf" lists every learned merchant newest first with its category, owner and whether you or the AI assigned it (`GET /questions/history`)
- feat(points): one point per 7 answered questions (was 30), matching the visual-round concept
- docs(security): the AI call budget is user-set, default 100, hard cap 1000
- test: history order and sources, 7-answer points, cached answers under a used-up budget

## 0.23.0 — 2026-10-29
Version: 0.23.0
Branch: claude/grohk-app-consumer-integration-1de45f
Changes:
- feat(ai): "Verbindung testen" in the AI settings asks the configured provider about a made-up merchant (no bank data, counts as one call, never cached) and shows the outcome with its reason (`POST /setup/ai/test`)
- feat(freshness): the Datenstand page shows an AI card for admins — state (active / off / not set up), calls this month, merchants learned, last assignment, last test, assignments per category and the latest learned merchants
- feat(ai): `GET /setup/ai` also returns `usable`, `last_run`, `last_test` and `results`; the last categorisation and test outcome are stored as error codes only
- test: connection test outcomes (success, not opted in, no key, budget, unparsable, timeout), results summary, outcome merge

## 0.22.0 — 2026-10-29
Version: 0.22.0
Branch: claude/suspicious-dewdney-12be4e
Changes:
- fix(sensor): the sensor platform no longer crashes when an account's `ha_users` holds plain user ids instead of objects; the crash left balance, bank and month sensors unavailable and the panel showed the onboarding although banks were linked
- feat(panel): the panel is rebuilt to the visual-round concept — one screen with time horizons, the Person ⇄ Haushalt pill at the bottom, a gear for settings and subpages with one shared header (Datenstand, Zyklus, Buchungen, Budgetplan, Fragen, Einstellungen); the old tabs, the overview and eleven legacy components are removed
- feat(refresh): only an explicit "Neu importieren", the setup bootstrap and the daily schedule reach the bank; `POST /refresh` requires `{"trigger":"user_import"}` and the open-panel auto refresh is retired; "Aktualisieren" re-derives from the cache (`POST /reprocess`)
- feat(home): person view shows own items and own Spielraum (budget, spent, remaining); desktop side column with accounts, optimisation and a 6-cycle history per pot with carry-over accept/drop (`POST /pots/carry`)
- feat(questions): question cards list the bookings behind them (date, amount, account, counterparty, last four IBAN digits, text) and how often the merchant occurred
- feat(setup): new wizard steps — plan prefilled from detected contracts, savings goals, points event (`finance_dashboard_points_awarded`, counter/input_number helper), opt-in AI categorisation (HA AI, xAI Grok, Anthropic, OpenAI; key Fernet-encrypted and write-only; at most 100 calls per month) and editable nicknames per person
- feat(ai): merchants left uncategorised after derive/import are categorised by the opt-in AI provider; payload is merchant and remittance text only
- fix(cards): the Lovelace budget card reads option list and value from the split/remainder select entities; the transactions-log component lost its data source and is retired
- docs: binding UI spec `docs/dev/ui-concept-gap.md`, fetch-trigger table, setup-wizard and categorisation contracts; live-audit and visual-round concept pages
- test: user-id `ha_users`, explicit refresh trigger, booking details, pot history and carry-over, wizard steps, AI provider gating

## 0.21.0 — 2026-10-28
Version: 0.21.0
Branch: claude/gifted-cartwright-cb042e
Changes:
- feat(setup): the budget-plan step imports the household spreadsheet directly — upload an .xlsx file or paste a Google Sheets link; before, it only pointed to the import_spreadsheet service and a file in the config folder
- feat(api): `POST /budget_plan/upload` (base64 .xlsx, max 5 MB, parsed in memory, never written to disk) and `POST /budget_plan/import_url` (Google Sheets shared "anyone with the link"; only the sheet id is taken from the link and the export URL on docs.google.com is built by the integration, so a pasted link cannot target another host); both admin-only
- docs(security): the Google Sheets export download is the one further allowed external call — user-triggered, nothing sent
- test: link parsing and host rejection, upload decoding, size cap, unshared-sheet detection, parsing from bytes, admin gating of both endpoints

## 0.20.2 — 2026-10-28
Version: 0.20.2
Branch: claude/finance-own-name-0-20-2
Changes:
- fix(contracts): a payment to an account holder's own name also counts as an own transfer when the bank adds a middle name or title ("Jeremy Tim Treder" for the holder "Jeremy Treder"); every word of the holder name must appear, so a similar-looking business name stays a contract
- test: middle-name and look-alike cases in the own-name filter test

## 0.20.1 — 2026-10-28
Version: 0.20.1
Branch: claude/finance-live-fixes-0-20-1
Changes:
- fix(contracts): own transfers between household accounts are no longer listed as contracts (the whole chain counts as one transfer, also its source leg), and payments to an account holder's own name are skipped too; on the live install a transfer to the own account showed as a 46.567 €/year contract with a notice deadline, and the notice reminder used the same list
- fix(household): the owner split names the household share "shared" as the contract says; before, "Der Haushalt trägt" always read 0,00 €
- fix(freshness): before the first logged import, "Stand" and "Letzter Import" use the newest successful bank fetch instead of claiming nothing was imported
- fix(contracts): contracts show the creditor as the bank writes it ("Vodafone GmbH", not "vodafone gmbh"); savings-account toggles show account name and masked IBAN instead of three identical "DKB" rows
- fix(benchmark): source notes are shown in German in the German UI (`note_de` in the bundled dataset)
- test: 647 tests (own-transfer and own-name filters, owner kinds, freshness fallback, display name)

## 0.20.0 — 2026-10-28
Version: 0.20.0
Branch: claude/home-assistant-live-analysis-c86a08
Changes:
- feat(household): the Household tab runs on the household cycle instead of the calendar month (cycle starts at the highest income, or another person's highest income within the 7 days before; calendar month only without income), own transfers between household accounts are excluded, and no savings rate is shown without income
- feat(categorize): merchant names are normalised and a learned merchant memory (merchant → category and owner) applies before the keyword rules; one-off booking corrections win over both. Open questions are picked by euro impact, at most 10 per week
- feat(frontend): flash-card questions — the star on Start opens the cards; answer, skip or "always like this"; every 30 answers earn a point
- feat(setup): guided setup wizard (accounts, persons, payday, region, plan, pots from history, AI opt-in, notifications) with resume on Start; a confirmed payday anchors the cycle; pots are suggested from the median of past cycles
- feat(reprocess): the bank section splits "Neu importieren" (fetch raw bank data, then reprocess) from "Aktualisieren" (reprocess the stored raw data only, no bank call); an import log and a monthly validity check feed the new freshness subpage
- feat(contracts): series of any interval become contracts with notice periods and deadlines; annual and irregular costs get a monthly reserve and pot coverage (Jahr tab: Verträge)
- feat(benchmark): a bundled, versioned German household benchmark dataset (state and postcode level where available), never fetched at runtime (Jahr tab: Vergleich)
- feat(notify): German notifications for large debits, double charges, a missing salary and expiring or expired consent, a weekly digest, and a reminder when a contract's notice deadline is near
- feat(frontend): household members (non-admins) get their own person view; admin actions (import, demo, add bank, renew consent) are hidden for them, and transactions stay aggregate-only
- fix: harden/polish pass — region validated before any write, missing cycle-rule label, postcode escaped, timers cleared on disconnect, recurring log without amount or name, settings and plan texts moved into the locale files
- test: 643 tests (household cycle, merchant memory, questions, freshness, contracts, benchmark, setup wizard and member gating)

## 0.19.2 — 2026-10-28
Version: 0.19.2
Branch: claude/home-assistant-live-analysis-c86a08
Changes:
- fix(frontend): locale files load with the version query. The static path is cached long, so after an update a browser kept the old `de.json` and Start showed raw keys such as `home.setup.assign_title`
- fix(frontend): "Personen & Konten" offers the suggested household members directly as account owners; picking one makes them a person, so an account can be assigned to a person without first switching them on in step 1 (before, only "Haushalt" and "Offen" were offered)

## 0.19.1 — 2026-10-28
Version: 0.19.1
Branch: claude/home-assistant-live-analysis-c86a08
Changes:
- fix(core): bank accounts referenced only by a bank subentry (banks linked by 0.16.0/0.16.1) are adopted into the entry on setup. The live install had none stored, so every balance carried an empty account key, "Personen & Konten" listed no account and Start stayed on "Wem gehört was?" with no way out
- fix(refresh): an attended refresh fills a missing IBAN and bank account name once per account (details call with PSU headers, never on the background fetch); the entity key stays the same
- fix(frontend): the household "Gesamtsaldo" counted the available-balance sensors as extra accounts — 7 instead of 4 accounts and booked plus available summed
- fix(api): HA users not linked to a person entity (MQTT, wall tablet, PC logins) are no longer suggested as household people when the install has person entities
- feat(categorizer): rent pool, Kaufland, Penny, Globus and Metro are recognised (housing / food)
- docs: the test skill points at the local, out-of-repo HA access file
- test: 4 regression tests (subentry adoption, attended IBAN fill, no details on background, person-entity suggestion)

## 0.19.0 — 2026-10-28
Version: 0.19.0
Branch: claude/promote-stable-3d9130
Changes:
- feat(api): `GET/PUT /api/finance_dashboard/assignments` (admin only) — household persons, HA-user → person mapping with suggestions (system/inactive users flagged), account owner per IBAN identity (person, household or open); persisted in the config entry, IBAN only as last 4 digits
- feat(core): the logged-in user resolves to a person through the persons list too; the home payload carries a `setup` block (persons, user mapped, accounts assigned, pots)
- feat(frontend): Overview redesigned in the new design system — person and household cards (single accounts desktop-only), bank cards with consent pills and the automatic-fetch limit, transactions as cards, and the new "Personen & Konten" settings with an unassigned-accounts banner
- feat(frontend): Household tab redesigned — "Meins · Deins · Unseres" person cards with person colours, plan vs actual verdict with rule-based "Was das heißt", who carries what, per category with fixed/variable tags; ledger, income, transfers and benchmark desktop-only
- feat(frontend): Start shows a setup card instead of "0 € · passt" when there is no budget, hides the person toggle without a mapping, caps the question badge at 99+
- refactor(frontend): the legacy colour variables alias the `--fd-*` tokens, so every remaining component follows the new design; no red anywhere
- test: tests/test_assignments.py (GET flags and IBAN masking, persistence, validation, resolve_person, setup block, admin gating)

## 0.18.2 — 2026-10-28
Version: 0.18.2
Branch: claude/promote-stable-3d9130
Changes:
- feat(frontend): the old title bar is gone; the Start tab opens straight into the new home top bar, and the tabs use the HA primary colour of the new design
- feat(frontend): demo, refresh and "add bank" moved to the Overview tab; the Start tab's freshness note gains a "Refresh now" button (attended refresh, same endpoint)
- refactor(frontend): the obsolete month label and "Finance Dashboard" heading are removed

## 0.18.1 — 2026-10-28
Version: 0.18.1
Branch: claude/promote-stable-3d9130
Changes:
- fix(frontend): the panel no longer stays blank forever. HA assigned hass/narrow/route/panel before the panel class was defined (the kit import delays the definition), so the values shadowed the setters and the panel never rendered; the constructor now re-assigns them through the class
- fix(frontend): on phones the header wraps instead of pushing the freshness text off-screen, and the panel shows HA's menu button so the sidebar can be opened
- feat(frontend): a quiet desktop-only footer "Finance vX.Y.Z · Open in HACS" deep-links to the HACS repository page to check for and install updates

## 0.18.0 — 2026-10-28
Version: 0.18.0
Branch: worktree-concept-finance-visual-m4r8
Changes:
- feat(frontend): new first tab "Start" — the home screen per horizon (Heute · Woche · Zyklus · Jahr), swipeable, with a Person ⇄ Haushalt pill; Heute shows only today's free amount and pots, Woche the daily linear budget with carry-over within the cycle, Zyklus the Soll line, "Als Nächstes" (pending bookings inline with a label), "Wusstest du schon?" and reserves, Jahr a light year view
- feat(core): income cycle rule — a person's cycle runs from their earliest highest income to the next; the household starts at the highest income unless another person's highest income falls within the 7 days before it
- feat(core): pots with a cycle-wide balance, average per day and carry-over only within the cycle; status passt / knapp (≤ +10 % over linear) / drüber
- feat(api): `GET /api/finance_dashboard/home?horizon=&view=` (cache only, no bank call) and pot create/update/delete; a person view shows only that person's items, the household view shows other persons as totals only
- feat(frontend): design-system tokens (surfaces, status semantics, person colours, desktop-only marker) and a shared tooltip style
- docs: README marks the project as alpha, not recommended for use; roadmap records the next visual-round slices
- test: 45 new tests (cycle edge cases, carry-over, ±10 % status, zero line); 484 tests green

## 0.17.2 — 2026-10-28
Version: 0.17.2
Branch: claude/gifted-cartwright-cb042e
Changes:
- fix(refresh): fetch-window dates are computed in UTC. Between local and UTC midnight the local `date_to` lay in the bank's future, and PayPal rejected every refresh with HTTP 422 until 01:00
- fix(budget): the background fetch budget counts per local day (HA time zone) instead of per UTC day, so the 06:30 call of the day before no longer shows as "today" after midnight
- feat(frontend): the bank row reads "Bank limit: x/4 automatic fetches today (manual unlimited)" and shows the last manual fetch, so an attended refresh is visible although it never counts against the limit; the budget sensor is renamed "Automatic fetches today (bank limit)"
- test: 3 regression tests (UTC window, local budget day, last manual fetch)

## 0.17.1 — 2026-10-26
Version: 0.17.1
Branch: fix/null-booking-date
Changes:
- fix(data): pending bank entries with no booking date (explicit null) crashed processing after a refresh, so the panel showed 0 transactions. Nulls are now normalised, and existing ledgers are rebuilt automatically (processing version 2)
- fix(storage): raw bank responses and the ledger are now saved before derivation, so a later failure never loses fetched data
- test: 435 tests green

## 0.17.0 — 2026-10-26
Version: 0.17.0
Branch: worktree-lifelong-history-k3x9
Changes:
- feat(data): lifelong history — the first attended fetch per bank session pulls the maximum history the bank allows (tries 3650, 730, 365, then 90 days). The raw archive and the balance history are kept forever by default (retention option 0 = forever)
- fix(data): a short bank answer never erases older history that is already stored
- feat(storage): raw snapshots carry replay metadata, so the ledger can be rebuilt from the raw archive. The ledger is rebuilt automatically when PROCESSING_VERSION changes; a backup of the old ledger is kept
- feat(services): new admin service `finance_dashboard.reprocess_data` rebuilds the ledger from the raw archive on demand
- test: 432 tests green

## 0.16.2 — 2026-10-26
Version: 0.16.2
Branch: fix/subentry-accounts
Changes:
- fix(connect): "Aktualisieren" reached no account after a bank was linked, so the panel showed 0 transactions. Linking stored only account references in the bank subentry, while the refresh reads the integration's account list, which stayed empty on a fresh HACS install. Linking now also stores the account records there (merged by IBAN identity, so names and entity ids survive a re-link); the subentry still carries no account number. Accounts without an IBAN (cards) are identified by their identification or name instead of the per-session id
- fix(refresh): banks linked with 0.16.0/0.16.1 are fetched without re-linking — a subentry account without a stored record gets a minimal one (named "<Bank> 1", "<Bank> 2", …) until the bank is re-authorised via the subentry's reconfigure
- test: 421 tests green (regression test for a bank linked without stored account records)

## 0.16.1 — 2026-10-26
Version: 0.16.1
Branch: fix/account-details-endpoint
Changes:
- fix(enablebanking): adding a bank failed right after authorising at the bank ("Die Bank oder Enable Banking hat einen Fehler gemeldet"). Account details were requested from `/accounts/{id}`, which Enable Banking does not serve (HTTP 404); they are now read from `/accounts/{id}/details`, with the IBAN taken from the nested `account_id`. The scheduled and manual account refresh used the same call
- test: 420 tests green (regression test for the details endpoint and nested IBAN)

## 0.16.0 — 2026-10-26
Version: 0.16.0
Branch: feat/rethink-foundation
Changes:
- refactor(packaging): BREAKING — HACS-only distribution (minimum HA 2026.3). The Supervisor companion add-on and its payload sync are removed; install the integration as a HACS custom repository, uninstall the old add-on and restart
- refactor(core): BREAKING — the split-model and remainder select entities now report slug states (`pooled_equal`, `equal`, `proportional`, `custom`) with translated labels. Automations that matched the old display text must be updated
- refactor(frontend): BREAKING — the in-panel setup wizard and its `/setup/*` endpoints are removed. Banks are added under Settings → Devices & services → Finance → Add bank
- feat(branding): own brand icon and logo (light/dark, @2x) served from the integration's `brand/` folder
- feat(frontend): sidebar panel registered via `panel_custom` (admin only, cache-busted URLs); the Lovelace cards are auto-loaded on every dashboard, so they can be placed in any dashboard tab
- feat(connect): banks are config subentries linked through my.home-assistant.io (redirect URL to register at Enable Banking: `https://my.home-assistant.io/redirect/oauth`), with reconfigure and a repair issue when consent expires. The old callback was built from the request host and broke across internal/external URLs
- feat(refresh): per-bank and per-account daily background fetch budget — the scheduled refresh uses at most 1 of the bank's 4 daily calls, attended calls stay uncapped but debounced, a 429 blocks only the affected bank for 6h, transactions are fetched incrementally and pagination has a loop guard
- feat(storage): every fetch is stored as a Fernet-encrypted raw snapshot (monthly stores, 400-day retention) plus a deduplicated encrypted ledger and balance series. The previous code claimed encryption at rest but stored plaintext; the legacy plaintext cache and single-session layout are migrated automatically
- feat(entities): devices per bank and per account with balance, available balance, last update, consent valid-until and state, fetch budget, blocked-until, last error and a refresh button; balance history is imported into long-term statistics; redacted diagnostics; `runtime_data`; `quality_scale.yaml`
- feat(frontend): facts-only panel overview (accounts, bank status, admin-only transaction search); the existing household features sit behind the new `show_household` option
- fix(refresh): `_build_stats` was missing `@staticmethod`, so every live refresh raised
- fix(config): the options flow dropped the `daily_refresh_*` settings
- fix(frontend): panel auto-refresh referenced an undefined `DOMAIN`
- fix(core): the coordinator did not pass `config_entry`, which made setup fail on HA 2026.10
- fix(i18n): `strings.json` lacked the `services` section
- chore(manifest): `iot_class` is now `cloud_polling`; `my` and `recorder` added to `after_dependencies`
- fix(manifest): hassfest — `cryptography` and `PyJWT` removed from `requirements` (both ship with Home Assistant core and must not be listed by a custom integration); `CONFIG_SCHEMA` declared as config-entry-only; the fixable repair issues (`consent_expired`, `consent_expiring`, `restart_required`) carry their explanation in the fix-flow step instead of a top-level description, which hassfest rejects for fixable issues
- docs: CLAUDE.md slimmed to an index; developer detail moved to `docs/dev/`
- test: 419 tests green on HA 2025.1.4 / Python 3.12 and on HA 2026.10.4 / Python 3.14, plus a boot smoke test on HA 2026.10.4

## 0.15.2 — 2026-08-20
Version: 0.15.2
Branch: claude/das-update-ha-missing-56b4b8
Changes:
- fix(addon): the companion add-on ran with `startup: once`, so it had already exited by the time Supervisor auto-updated it — and Supervisor only restarts add-ons that were *running*. The installer therefore only ever executed on a host reboot. On the reporting instance the add-on package sat at 0.14.0 while `/config` still held 0.13.0 with a file timestamp of 2026-04-25; 0.13.1, 0.14.0, 0.15.0 and 0.15.1 never reached disk. The add-on is now a resident service (`startup: services`) that installs on start and re-checks hourly, so every auto-update delivers its payload the minute it lands
- fix(addon): the installer replaces the integration tree instead of copying over it. `cp -r` removes nothing, so `api.py` and `manager.py` from 0.13.0 survived next to the packages of the same name that replaced them, together with their stale `__pycache__`. The delete sync is guarded by an allowlist — it deletes recursively, and only the two paths it owns
- fix(addon): a failed install no longer kills the container. Exiting left the add-on stopped, which is precisely the silent-failure mode that hid this outage for four months; the run is retried on the next interval instead. A TERM/INT trap plus backgrounded `sleep` lets a Supervisor stop take effect immediately rather than after the SIGKILL timeout
- fix(addon): the install-state file is rewritten on every check, not just on an update. Its timestamp is the only evidence visible from outside the container that the installer is alive — a stale one is what identified this bug
- test: the delivery path had zero coverage. `tests/test_addon_installer.py` executes `run.sh` for real against a temporary root (`FD_CONFIG_ROOT` / `FD_PAYLOAD_ROOT`, `FD_RUN_ONCE`) and pins the stale-module removal, the restart marker, the Lovelace copy, a bare first install, the no-op path, and the `startup: services` contract itself — total 315 → 323
- ci: `bash -n` on run.sh, and `.gitattributes` pins `*.sh` to LF — a CRLF checkout breaks the shebang inside the Alpine container, failing as a stopped add-on rather than an error
- chore(lint): cleared the 7 ruff findings that had accumulated in files this branch does not touch (two dead `noqa` directives, two unsorted import blocks, three shared mutable class attributes now `ClassVar`). `ruff` ships in the test requirements but no gate ever ran it, so the debt was invisible

## 0.15.1 — 2026-08-20
Version: 0.15.1
Branch: claude/fix-reconcile-empty-accounts
Changes:
- fix(core): the entity-registry reconciler removed every balance entity when the config entry listed no accounts. An empty list means "we do not know what is linked" — a half-configured setup, a storage-recovery round, a re-auth that cleared the list before failing — not "all orphaned". Reconciliation now returns early in that state, so it can no longer destroy history HA cannot restore. Found by re-reading the 0.15.0 diff before promoting it to stable
- test: pin the empty-account-list case — total 314 -> 315

## 0.15.0 — 2026-08-20
Version: 0.15.0
Branch: claude/bank-api-provider-comparison-f24ce7
Changes:
- fix(frontend): the setup wizard reported every failure as "Banken werden geladen…" — all three catch blocks assigned the LOADING string as the error message, so the real exception was discarded before anyone could read it. The wizard now surfaces the backend's `error_type` as a readable cause, appends the raw detail, distinguishes an HTTP status from a transport failure, and offers a retry button
- fix(api): the bank list was gated on the 4/day ASPSP quota. `/aspsps` is Enable Banking's own catalog, not a call to any bank — it neither spends nor is bound by that quota — so a user who had refreshed four times could not connect a new bank until midnight. `_get_setup_client` now takes `enforce_rate_limit`, and the catalog opts out
- feat(api): institution catalog is cached (24h TTL). A fresh cache skips the API entirely; an outage degrades the wizard to the stale list, flagged with its date, instead of an empty one. An empty API result counts as a failure — DE always has banks
- fix(core): account identity is now the IBAN, not the Enable Banking session uid. The uid is reissued on every re-link, so re-connecting a bank created a second set of entities for the same real account and orphaned the first. `account_identity.py` derives a stable key (truncated SHA-256 — the key lands in the entity registry, so it must not carry the account number), merges re-links onto it, and preserves user-owned fields (custom name, type, person, HA users) across the merge
- fix(core): entity registry is reconciled on setup — entities still on the uid-derived `unique_id` are migrated in place (entity_id and history preserved), and balance entities owned by no linked account are removed. This clears duplicates left by earlier re-links
- fix(refresh): attended calls are no longer gated on the rate limit. PSD2 RTS Art. 36(5)(b) caps AISP access only when the user is not in session; with PSU headers present the cap does not apply, so refusing the refresh button while rate-limited denied a call the bank permits. The refresh endpoint, the manager pre-flight check, the header button and the panel's client-side guard all now distinguish attended from background
- fix(refresh): a 429 backs off 6h (Enable Banking's documented retry) instead of until midnight — a rate limit at 07:00 used to cost the entire day. An attended 429 is transient upstream noise and pauses 15 minutes. `Retry-After` still wins, capped at midnight where the ASPSP day counter resets
- feat(frontend): opening the panel triggers one attended live refresh when the cache is older than the configured threshold (default 60 min, `auto_refresh_on_open` / `auto_refresh_max_age_minutes`). Once per panel mount, never on an interval — this is what makes DKB balances current without spending the background budget
- test: +48 tests covering catalog rate-limit exemption and cache fallback, account identity and re-link dedup, registry migration/orphan cleanup, and the attended/background split — total 266 → 314, all green

## 0.14.0 — 2026-08-17
Version: 0.14.0
Branch: claude/projekt-excel-migration-7c449b
Changes:
- feat(core): budget_plan.py — cost-position ledger, the model the household spreadsheet is built on. Positions carry an explicit owner (person or shared), a signed amount (negative = reimbursement billed onward), a kind (fixed or buffer with units x unit price), an inclusive YYYY-MM validity window, and an optional debit account independent of the owner
- feat(core): spreadsheet_import.py — migrates a `Kalkulation Haushalt.xlsx` workbook into the plan. Recovers buffer factors from formulas (`=80*4.5`), validity windows from prose comments ("bis inkl. April 2027"), and cross-checks recomputed net income against the sheet's own stated net, reporting any mismatch
- feat(core): transfer_plan.py — reproduces the workbook's monthly transfer choreography (accounts x ordered steps) and enforces its central invariant in code: a pass-through account must net to zero. Contributions are liquidity-aware, so a person whose income cannot cover their share contributes what they have and the rest is carried by those with a surplus
- feat(core): `settlement_delta` per person — how much one person is fronting for another. The spreadsheet contained this implicitly as the gap between account balance and entitled pocket money; it is now explicit
- fix(core): the transfer plan reports amounts it cannot place on any account (`unplaced`) instead of dropping them. Without a joint account every shared position was skipped, no account ended up out of balance, and the plan declared itself balanced while omitting the largest cost block; a person with no account, or a position with no resolvable debit account, vanished the same way. Such a plan now counts as unbalanced and the UI names what could not be booked
- feat(household): `pooled_equal` split model — shared costs paid from POOLED net income, remainder split equally, each person then paying their own individual costs. Now the default. The previous models computed a materially different result and could not carry a person with negative net income
- feat(core): plan-vs-actual comparison per category and per position, with unmatched positions reported as unmatched rather than shown as zero
- feat(benchmark): BenchmarkProvider wired up — it was dead code with zero imports repo-wide. The "ours" side is now computed from the plan, plus a manual water-consumption metric (not derivable from banking data)
- feat(api): /budget_plan, /transfer_plan, /plan_vs_actual, /benchmark, plus admin-gated position/income/import endpoints. Import paths are validated against `allowlist_external_dirs`
- feat(frontend): fd-budget-plan card — income breakdown, cost ledger grouped by owner, pocket money, transfer table with the zero-sum badge, benchmark comparison
- feat(core): once-daily scheduled refresh at a configurable time (default 06:30). One call of the 4/day/ASPSP budget, leaving three for manual refreshes
- fix(banking): transaction fetch could never parse a real Enable Banking response. The API returns `{"transactions": [...], "continuation_key": ...}` — a LIST — while the client called `.get("booked")` on it, raising AttributeError for every account. Swallowed by a broad handler, so refreshes reported success over an empty cache
- fix(banking): derive the amount sign from `credit_debit_indicator` (CRDT/DBDT). It appeared nowhere in the codebase, so every transaction would have read as income with total expenses stuck at 0
- fix(banking): honour per-transaction `status` (BOOK/PDNG) instead of hardcoding buckets; join `remittance_information`, which is an array, not a string
- fix(banking): follow `continuation_key` pagination, capped at 10 pages with the truncation logged rather than silent
- fix(banking): pass ISO 20022 balance codes through (CLBD/ITAV/...) and match them in the sensor's priority list, which previously listed only camelCase names and could never match — so each account showed whichever balance the bank happened to list first
- fix(core): HA start crashed on every restart — a sync lambda calling `hass.async_create_task` from a worker thread tripped HA's thread-safety guard, the coroutine was never awaited, and the transaction cache was therefore never loaded. Entities stayed empty until a manual refresh
- fix(refresh): merge each fetch window into the cached history instead of replacing it. Every refresh previously truncated history to the rolling window, making multi-month views impossible to populate
- fix(refresh): only stamp `_last_refresh` when at least one account answered. A total failure used to look identical to a success, and the false timestamp survived restarts via persistence
- fix(refresh): tag pending transactions with account/person like booked ones
- fix(sensor): expose `last_refresh_stats`, `is_refreshing`, `cache_age_seconds`, `cache_is_stale` — the frontend already read these keys, which never existed, so a stale cache was visually indistinguishable from fresh data
- fix(services): honour the documented `days` field on `refresh_transactions` and month/year on `get_monthly_summary`; both were advertised and ignored
- fix(import): a "Kommentar" column header was read as a person column, so every validity window in the sheet was lost
- feat(services): `import_spreadsheet` (admin-only, allowlist-checked) and `get_transfer_plan`
- test: +81 tests covering the plan model, the split invariants, transfer-plan balancing, and the Enable Banking normalization layer that had no coverage at all — total 185 → 266, all green
- fix(devops): sync_changelog.py appended every entry to the BOTTOM of CHANGELOG.md — its header-detection regex alternation included `$`, which matches every blank line, so the insertion point became the last blank line of the file. `--check` read the first heading and therefore reported the CHANGELOG as permanently behind while claiming each sync succeeded. Added `--repair` and re-sorted all 44 accumulated sections newest-first (0.13.1 had been stranded at the bottom since May)
- chore(deps): openpyxl>=3.1.0 for spreadsheet import

## 0.13.1 — 2026-05-16
Version: 0.13.1
Branch: claude/upbeat-brattain-fcffef
Changes:
- feat(a11y): global :focus-visible outline rings + prefers-reduced-motion override in SHARED_CSS
- feat(a11y): aria-expanded on transactions-log show-more toggle
- feat(frontend): new design tokens in SHARED_CSS (--r-sm/md, --sh-sm/md/lg, --fs-sm/md/lg/xl, --lh-tight/normal, --sp-xs/sm/md/lg/xl) for upcoming token-migration polish
- fix(setup): RateLimitExceeded on /setup/complete surfaces as error_type=rate_limited in HTTP 200 body (matches setup-wizard contract; was previously masked as generic failure)
- fix(refresh): categorizer None-guard with WARNING log — refresh races ahead of init fall back to category="other" instead of crashing
- fix(export): cleanup of old CSV exports swallows OSError/ValueError/OverflowError and logs cause (no more silent bare-except)
- refactor(coordinator): remove unused TRANSACTION_REFRESH_STALENESS constant + timedelta import
- test: +20 unit tests for events.py (11) + export.py (9 incl. OSError/OverflowError monkeypatch paths) — total 165 → 185, all green
- chore(lint): ruff sweep across tests/ — 44 fixes (import order, unused imports, datetime.UTC migration)
- chore(payload): re-sync addon mirror (incl. pre-existing UTC drift from v0.13.0)

## 0.13.0 — 2026-04-25
Version: 0.13.0
Branch: claude/eager-nobel-e572f9
Changes:
- feat(security): MultiFernet credential storage with key rotation + v1→v2 migration (S2)
- feat(security): timing-safe OAuth state validation with one-time-use, 10min TTL, 32-entry cap, cross-store fallback (S4, F1, F3, F5)
- feat(security): unified setup-wizard rate-limit gate via async_make_setup_call + persistent fresh-setup gate (S3, F2, F4)
- feat(security): IBAN/account-id/EUR-amount log sanitizer; raw API bodies no longer hit ERROR-level logs (S1)
- feat(security): pre-commit secret-scan hook (.pre-commit-config.yaml + scripts/check_no_banking_data.py) (R11)
- feat(banking): PyJWT[crypto] migration with iss=application_id, aud=api.tilisy.com, per-request jti (A4)
- feat(banking): shared aiohttp ClientSession via async_get_clientsession (A5)
- feat(banking): Retry-After header honored on 429 + PSU headers for online-mode (D5, D6)
- feat(api): /refresh_status exposes rate_limit_per_day + cache_is_stale + cache_age_seconds (D7, D9)
- fix(security): /refresh and toggle_demo now require admin (R9, R14)
- fix(security): partial-refresh per-account cache prevents data loss on partial bank failure (R5, F10)
- fix(security): corrupt .storage recovery via try/except + repair-issue (R8)
- fix(security): static file serving non-blocking via async_add_executor_job + LRU cache (R12)
- fix(security): repair-issue payloads scrubbed of exception strings (R10)
- fix(security): _reconstruct_pem PKCS1/PKCS8 detection corrected (C9)
- refactor(api): split api.py (1258 LOC) into api/ package (setup, refresh, data, static, demo, _helpers) (A1)
- refactor(manager): split manager.py (1151 LOC) into mixin modules (RefreshMixin, PersistenceMixin) (A2)
- refactor(frontend): persistent component tree replaces full-rebuild on every data update (A3)
- refactor(frontend): SHARED_CSS adoption + CAT_COLORS/LABELS consolidation in fd-shared-styles (F2, F3)
- refactor(frontend): all hardcoded color literals replaced with CSS tokens (F4)
- refactor(frontend): unified disconnectedCallback for memory cleanup (F5)
- refactor(frontend): shared escHtml helper (F8)
- feat(a11y): setup-wizard modal with role/aria-modal/focus-trap/ESC (U1)
- feat(a11y): institution list with full keyboard navigation (role/listbox/option) (U2)
- feat(a11y): donut chart aria-label + visually-hidden table fallback (U3)
- feat(a11y): toast aria-live based on severity (assertive for warn/error) (U4)
- feat(a11y): cost-distribution role/group + per-segment aria-label (U5)
- feat(frontend): i18n with locale JSON files + hass.language detection + tSync helper (U6, G1-G4)
- feat(frontend): skeleton/loading states across all card components (U8)
- feat(frontend): + Bank entry-point opens wizard from header (U10)
- feat(frontend): countdown for setup-wizard auth-polling step (D8)
- feat(setup): persistent notification after config_flow completion (U11)
- fix(frontend): responsive breakpoint at 980px for category section (U9)
- refactor(frontend): month label as static span (U7)
- chore: remove deprecated GoCardless client (F1)
- refactor(api): manager.async_set_accounts encapsulation (F6)
- perf(security): reuse audit-log Store instance (F7)
- chore(manifest): iot_class cloud_polling → cloud_push (D2)
- docs: align repairs.py role + sync services.yaml (D3, D4)
- docs: precise update_interval docstring on coordinator (D10)
- fix(repairs): mark auth+storage repairs as is_persistent (D11)
- fix: dt_util.now() instead of datetime.now() throughout (D12)
- test: scaffold tests/ + pyproject.toml + requirements_test.txt (T1, T6)
- test: cache-vs-live-boundary contract test as guardian (T2)
- test: JWT/Fernet edge-case coverage (T3, 21 tests)
- test: parametrized categorizer rule coverage (T4, 79 tests)
- test: transfer-detector cascade + override + confidence (T5, 27 tests)
- chore(ci): pytest with coverage in validate workflow (T7)
- docs: sync CLAUDE.md phases with actual code state (D1)
- docs: audit-synthesis concept page (Phase 2 artifact)
- Result: 165/165 tests pass; ruff 0 errors; coverage 31% (categorizer 96%, transfer_detector 91%, const 100%); payload synced

## [unreleased] Wave G2 — Phase-4 RedTeam Security Fixes (F1–F5, F10)
Version: 0.12.1 (no bump)
Branch: claude/eager-nobel-e572f9
Changes:
- fix(security): F1 — OAuth state cross-scope race eliminated; _register_oauth_state() writes to BOTH manager._oauth_states AND hass.data[DOMAIN]["_oauth_states"]; _validate_oauth_state() checks both stores and removes on match from both; setup.py uses _register_oauth_state() exclusively
- fix(security): F2 — fresh-setup rate-limit gate added; _set_rate_limited() mirrors reset timestamp to hass.data["_global_rate_limit_until"]; async_initialize() mirrors on storage load; _get_setup_client() checks hass.data global key before creating client
- fix(security): F3 — UTC-aware OAuth state timestamps throughout; assume-UTC logic for naive timestamps in async_validate_oauth_state() and _parse_utc_dt() helper in api/_helpers.py; TypeError on naive/aware subtraction impossible
- fix(security): F4 — async_make_setup_call() wired into setup wizard; gains optional client= param for setup-credential bypass; institutions and authorize endpoints route through manager gate when available
- chore(security): F5 — _oauth_states dict bounded at 32 entries; oldest 16 evicted on cap; hass.data fallback also enforces 32-entry cap in _register_oauth_state()
- fix(banking): F10 — __unknown__ tx bucket dropped after first successful live refresh (accounts_hit > 0); migration-era legacy data no longer pollutes flat transaction list
- test: 2 new tests in test_oauth_state.py: test_timezone_mismatch_safe (F3 guard), test_oauth_states_dict_bounded (F5 eviction)
- Result: 165/165 tests pass; all changed files pass py_compile

## [unreleased] Wave F — Backend Test-Detail (T3, T4, T5, T6, T7)
Version: 0.12.1 (no bump)
Branch: claude/eager-nobel-e572f9
Changes:
- test(security): T3 — expand JWT/Fernet edge-cases; test_jwt.py gains 4 tests (wrong-algo rejection, expired-token rejection, clock-skew iat guard, cross-key signature mismatch); test_credential_manager.py gains 4 tests (middle-key decrypt across 3-key rotation, corrupt-key migration error, session-timeout flag reset, uninitialized-manager RuntimeError); total 21 tests
- test(categorizer): T4 — 79 parametrized tests covering all 9 rule categories (housing, food, transport, insurance, subscriptions, loans, utilities, income, transfers), positive-amount income fallback, custom-rule injection, case-insensitivity, multi-field (remittance array, creditorName) matching; also fixes shallow-copy bug in get_rules() — inner lists were shared, mutations polluted instance
- test(transfer-detector): T5 — 27 tests: simple 2-account transfer (source/destination assignment, confidence >= 0.60), 3-stage cascade chain (DKB -> PayPal -> HelloFresh, intermediate leg detection), manual override confirm/reject, false-positive guard (same amount != transfer, tolerance boundary, date window, pending status), confidence tiers, refund detection (storno keyword, timing direction), enrich_transactions field population
- chore(lint): T6 — ruff check passes with 0 errors; ruff format applied to 28 files; fixes: F401 unused imports, F841 unused variables, RUF005 list spread, RUF046 int(round()) -> round(), PLR1714 membership test, RUF002/003 ambiguous Unicode, RUF022 __all__ with noqa, E402 import order, RUF012 mutable attrs; per-file-ignores in pyproject.toml for structural PLR violations (too-many-branches/statements in complex handlers)
- chore(ci): T7 — pytest step adds --cov + --cov-report=xml/term-missing; coverage.xml uploaded as artifact; requirements_test.txt gains PyJWT>=2.8, cryptography>=42.0, aiohttp>=3.9
- Result: 163/163 tests pass; coverage 31% total (const 100%, categorizer 96%, transfer_detector 91%); ruff 0 errors

## [unreleased] Wave F — Frontend Refactors (A3, F2, F3, F4, F5, F8)
Branch: claude/eager-nobel-e572f9
Changes:
- refactor(frontend): F8 — escHtml() (regex-based, no DOM round-trip) exported from fd-shared-styles.js; window._fd object exposes all shared constants (CAT_COLORS, CAT_LABELS, MEMBER_COLORS, MONTH_NAMES, SHARED_CSS, escHtml, esc, eur, pct) for classic-script consumers
- refactor(frontend): F2 — local TX_CAT_LABELS, REC_CAT_LABELS, DIST_CAT_COLORS/LABELS, CAT_COLORS/LABELS, MONTH_NAMES duplicates removed from fd-transactions-log, fd-recurring-list, fd-cost-distribution, fd-category-section, fd-categorize, fd-header; all read from window._fd
- refactor(frontend): F3 — SHARED_CSS adopted via <style>${SHARED_CSS}${LOCAL_CSS}</style> in fd-stats-row, fd-stat-card, fd-household-section, fd-person-card, fd-donut-chart, fd-category-section, fd-cost-distribution, fd-recurring-list, fd-transactions-log, fd-header; removes ~120 lines of duplicated :host token definitions
- refactor(frontend): F4 — hard-coded #e74c3c, #0a0a0f, #f39c12, #12121a literals replaced with var(--dg/--error-color), var(--bg/--primary-background-color), var(--warning-color) tokens in fd-budget-config, fd-setup-wizard, finance-dashboard-panel, fd-header; fd-categorize catColors now reads window._fd.CAT_COLORS
- refactor(frontend): F5 — disconnectedCallback added to finance-status-chip (clears _successTimer); stub disconnectedCallbacks in fd-stat-card, fd-household-section, fd-person-card, fd-donut-chart (no active cleanup, guards future additions)
- refactor(frontend): A3 — FinanceDashboardPanel._onData() no longer rebuilds DOM on every fd-data-updated event; _ensureComponents() creates 6 child components once; _onData() pushes .data to persistent refs; loading/error/onboarding states use #overlay div toggled via .hidden class; onboarding listener rebind guarded by overlayState check
- Result: 49/49 tests pass; all 17 frontend JS files pass node --check

## [unreleased] Wave E — Backend Refactor + Polish (F1, F6, F7, D1-D12)
Branch: claude/eager-nobel-e572f9
Changes:
- chore: F1 — remove `_gocardless_client_deprecated.py`; no callers remained (GOCARDLESS_BASE_URL was only referenced internally in the deleted file); no companion-payload copy existed
- refactor(api): F6 — add `manager.async_set_accounts(accounts: list)` with isinstance validation + config-entry persistence; replace direct `manager._accounts = existing` in `api/setup.py` with the new method
- perf(security): F7 — CredentialManager stores single `_audit_store` instance in `__init__`; `_audit_log()` and `async_get_audit_log()` reuse it instead of creating `Store()` on every call; imports `AUDIT_MAX_ENTRIES` and `STORAGE_KEY_AUDIT` at module top; test helper updated to include `_audit_store = FakeStore()` and `test_audit_log_on_rotate` patching strategy updated for the new design
- chore(manifest): D2 — `iot_class` `cloud_polling` → `cloud_push` (data only enters on user-triggered push, not background poll)
- docs: D3 — `repairs.py` docstring explains intentional thin re-export design; issue creation lives in manager mixins which have execution context
- docs: D4 — CLAUDE.md service count corrected from 7 to 8 (`toggle_demo` was missing); all 8 services verified present in `services.yaml` and `const.py`
- feat(banking): D5 — `RateLimitExceeded` carries optional `retry_after_seconds: int | None`; `_async_request` parses `Retry-After` header on 429; `_set_rate_limited(retry_after_dt=None)` uses `min(midnight, retry_after_dt)` reset; both 429 catch-sites in `_do_refresh` and `_async_refresh_balances_live` forward the parsed value
- feat(banking): D6 — `_async_request` accepts optional `psu_ip`/`psu_ua` params; `async_get_transactions` and `async_get_balances` pass `psu_ua=self._PSU_UA` (canonical `HomeAssistant-Finance-Dashboard/<version>` string, class-level constant); `async_refresh_transactions(psu_ip=None)` accepts and forwards PSU IP all the way to client calls; `api/refresh.py` passes `request.remote` as `psu_ip`
- fix(repairs): D11 — `_raise_credentials_issue` sets `is_persistent=True` (auth issues survive restart); `_raise_storage_corrupt_issue` sets `is_persistent=True` (corrupt file requires manual intervention)
- fix: D12 — replace all `datetime.now()` in `manager/_refresh.py` and rate-limit comparison in `manager/__init__.py` with `dt_util.now()` (tz-aware, consistent with HA conventions); `from homeassistant.util import dt as dt_util` added to both files
- feat(api): D7 — `get_refresh_status()` includes `rate_limit_per_day: ENABLEBANKING_RATE_LIMIT_DAILY` (currently 4); frontend can render the cap label dynamically without hardcoding
- feat(api): D9 — `get_refresh_status()` includes `cache_is_stale: bool` (True when `cache_age_seconds > 6h`); `_CACHE_STALE_THRESHOLD_SECONDS = 6 * 3600` class constant
- docs: D10 — `FinanceDashboardCoordinator.__init__` docstring rewritten to precisely explain cache-only contract, `update_interval=None` rationale, and 4/day rate-limit constraint
- docs: D1 — CLAUDE.md architecture block updated to show `manager/` and `api/` as packages with sub-files; Phase 1 all checkboxed; Phase 2 items marked [x]/[ ] per actual code state; Phase 3 marked frozen; service count 8; next version hint 0.13.0
- Result: 49/49 tests pass

## [unreleased] Wave D — Architecture Refactors (A1, A2, A4, A5)
Branch: claude/eager-nobel-e572f9
Changes:
- feat(security): A4 — replace manual base64/cryptography JWT with PyJWT[crypto]>=2.8.0; iss=application_id, aud=api.tilisy.com per current Enable Banking docs; adds unique jti per request (replay protection); adds tests/test_jwt.py (8 cases: decode, iss, aud, TTL, jti presence, jti uniqueness, kid header, RS256 algorithm)
- refactor(banking): A5 — EnableBankingClient accepts optional session parameter; HA-managed session injected via async_get_clientsession in both manager.py and api/_helpers.py; private session lazily created only when none injected; async_close() cleans up private session only (owner=True); eliminates per-request TCP handshake overhead
- refactor(api): A1 — split 1373-line api.py into api/ package: _helpers.py (shared utils), setup.py (7 setup-wizard views + OAuth callback), refresh.py (RefreshTriggerView + RefreshStatusView), data.py (BalancesView, TransactionsView, SummaryView, TransferChainsView), static.py (LRU file serving), demo.py (DemoToggleView + DemoDataView), __init__.py (async_register_api + full re-exports); from .api import async_register_api still works; test patch target updated to api.refresh._get_manager
- refactor(manager): A2 — split 1321-line manager.py into manager/ package with two mixins: RefreshMixin (_refresh.py: async_refresh_transactions, _do_refresh, _async_refresh_balances_live, _set_rate_limited, OAuth state, setup proxy, client factory, credential issue helpers), PersistenceMixin (_persistence.py: _persist_transactions, _async_load_transfer_overrides, storage corrupt issue); FinanceDashboardManager inherits both (MRO: Manager → RefreshMixin → PersistenceMixin); from .manager import FinanceDashboardManager unchanged

## Wave A — Test Infrastructure — 2026-04-25
Version: 0.12.1 (no bump)
Branch: claude/eager-nobel-e572f9
Changes:
- test(infra): scaffold tests/ directory — __init__.py, conftest.py with Windows-compatible event loop policy fix (pytest-homeassistant-custom-component uses HassEventLoopPolicy + socket guard that conflicts with Windows ProactorEventLoop socketpair; fixed via event_loop_policy fixture wrapping new_event_loop with socket enable/disable)
- test(infra): pyproject.toml with pytest asyncio_mode=auto, ruff lint config (E/F/W/I/B/UP/PLR/RUF, line-length=100, py312), mypy strict for custom_components/
- test(infra): requirements_test.txt (pytest>=8.0, pytest-asyncio, pytest-cov, pytest-homeassistant-custom-component, ruff, mypy, ha-customapps>=0.3.0)
- test(smoke): test_smoke.py — import smoke test, DOMAIN/VERSION/SERVICE_* constants validation
- test(coordinator): test_coordinator_contract.py — GUARDIAN tests asserting coordinator._async_update_data() and async_load_cached() never call any EnableBankingClient live method (async_get_transactions, async_get_balances, async_get_account_details, async_get_institutions, async_create_auth, async_create_session, async_test_connection); update_interval=None assertion
- ci: add pytest job to validate.yml (parallel to validate, Python 3.12, pip install requirements_test.txt, pytest tests/ -v)
- Result: 7/7 tests pass locally

## [unreleased] Wave C — Security Audit (R5, R8, R9, R10, R11, R12, R14, C9)
Branch: claude/eager-nobel-e572f9
Changes:
- fix(core): R5 — per-account transaction cache (`_tx_by_account: dict[str, list]`); partial refresh failure leaves intact account untouched, stale data preserved; storage migrates old flat-list format on load; flat `_transactions` rebuilt deterministically from dict
- fix(core): R8 — wrap `async_load()` in `async_initialize` with try/except (JSONDecodeError, ValueError, OSError); on decode error log sanitized ERROR + full stack at DEBUG only; raise `storage_corrupt` Repair issue with error_class only (no str(exc) leakage)
- fix(api): R9 — `FinanceDashboardRefreshTriggerView.post` gated by `user.is_admin`; non-admin returns 403 admin_required before any API call
- fix(services): R14 — `handle_toggle_demo` service checks `call.context.user_id`, fetches user via `hass.auth.async_get_user`, raises `HomeAssistantError("admin_required")` for non-admin; backup/restore real transaction data around demo enable/disable
- fix(enablebanking): C9 — `_reconstruct_pem` detects PKCS1/PKCS8 marker BEFORE stripping headers; is_pkcs1 flag set on raw string, not residue
- fix(api): R12 — `FinanceDashboardStaticView` uses `hass.async_add_executor_job(file_path.read_bytes)` instead of synchronous read; mtime-aware LRU cache (16 entries) for hot files
- fix(core): R10 — Repair issues never include `str(exc)` or tracebacks in `translation_placeholders`; only `error_class = type(exc).__name__`; PEM-load failure logs class-only at ERROR, full stack at DEBUG; `storage_corrupt` and `credentials_invalid_pem` issues use translation-key-only pattern; new `storage_corrupt` translation key added to en.json + de.json
- feat(precommit): R11 — `.pre-commit-config.yaml` with standard hooks + local `no-banking-data` hook; `scripts/check_no_banking_data.py` blocks real DE IBANs / long account numbers / EUR amounts; allowlists tests/ path and DE89370400440532013000 (public test IBAN); exits 0 for clean files, 1 for violations
- test: R5 — `tests/test_partial_refresh.py` (3 cases: partial success, full success, migration)
- test: R8 — `tests/test_storage_recovery.py` (2 cases: corrupt → starts empty + repair, valid → loads normally)
- test: R9 — `tests/test_admin_gating.py` (3 cases: non-admin 403, no-user 403, admin passes gate)
- test: C9 — `tests/test_pem_reconstruct.py` (5 cases: PKCS8 detection, PKCS1 detection, escaped newlines both formats, 64-char chunking)
- test: R11 — `tests/test_banking_data_hook.py` (6 cases: clean, real IBAN blocked, test IBAN allowed, path allowlist, main exit codes)

## [unreleased] Wave B — Security-Critical (S1-S4)
Branch: security/wave-b-s1-s4
Changes:
- fix(security): sanitize banking responses in error logs (S1) — _LOGGER.error no longer emits raw response body; IBANs, 16-19 digit account IDs, and EUR amounts are masked via _sanitize_log() before reaching DEBUG-level log; exception messages also sanitized
- feat(security): MultiFernet with key rotation + migration (S2) — credential_manager.py now stores keys as a versioned list (schema v2); async_rotate_key() prepends a new primary key, retains max 3; legacy v1 "encryption_key" string auto-migrated on init; audit entry "key_rotated" on every rotation
- fix(security): route setup-wizard live calls through rate-limit gate (S3) — all 4 direct EnableBankingClient() instantiations in setup-wizard endpoints replaced with _get_setup_client(hass); checks manager.rate_limited_until before issuing any live call; async_make_setup_call() added to FinanceDashboardManager as the canonical gate
- fix(security): validate OAuth state with timing-safe compare (S4) — async_register_oauth_state() / async_validate_oauth_state() added to FinanceDashboardManager using secrets.compare_digest() with 10min TTL and one-time-use; OAuth callback validates state before processing authorization code

## 0.12.1 — 2026-04-24
Version: 0.12.1
Branch: claude/charming-cohen-05563c
PR: (pending)
Changes:
- fix(core): preserve partial balances when Enable Banking rate-limit hits mid-fetch — accounts that succeeded before the 429 no longer lose their fresh value, merged into the existing cache instead of being discarded
- fix(core): reconstruct `_previous_balances` baseline from cached balances on `async_initialize` so the first refresh after every HA restart no longer fires spurious `fd_balance_changed` events for every account
- fix(core): balance-refresh end path now merges into existing cache instead of replacing — accounts that errored this round keep their last known value
- fix(setup): deferred reload after setup-wizard completion now triggers a real live refresh via `manager.async_refresh_transactions()` instead of a cache-only `coordinator.async_refresh()` — entities populate with actual bank data immediately, no more "unavailable" state until the user clicks "Aktualisieren"
- fix(coordinator): `async_load_cached` failure path publishes an empty snapshot so entities stay `unknown` (recoverable) instead of `unavailable` (stuck) when cache read errors
- fix(core): `refresh_accounts` service call now pushes the updated state through the coordinator so dashboards reflect the new account metadata immediately, matching `refresh_transactions` behavior
- fix(core): always load the cached snapshot into the coordinator regardless of `configured`/`demo_mode` state so half-configured entries don't leave entities permanently unavailable
- fix(number): `BudgetLimitNumber` now inherits from `RestoreEntity` — user-set budget limits survive HA restarts instead of silently resetting to 0
- fix(select): `SplitModelSelect` and `RemainderModeSelect` listen for config-entry updates and re-sync their current option when the options flow changes the stored key — no more stale display after external option changes
- fix(api): `/demo/toggle` returns HTTP 503 when no manager is configured instead of toggling a dead `hass.data` flag that nothing reads
- refactor(enablebanking_client): drop unused `ENABLEBANKING_RATE_LIMIT_DAILY` import, move `RateLimitExceeded` below all imports for a clean module layout
- docs(__init__): replace stale "GoCardless/Nordigen" docstring with Enable Banking PSD2 reference, document the 4/day/ASPSP rate-limit gate
- docs(addon): replace stale "GoCardless Open Banking API" description in `finance_dashboard_companion/config.yaml` with Enable Banking PSD2

## 0.12.0 — 2026-04-23
Version: 0.12.0
Branch: claude/gallant-mestorf-fcf6f0
PR: (pending)
Changes:
- feat(frontend): new `fd-transactions-log` card shows imported (cached) transactions after at least one bank is linked and a refresh ran — date, counterparty, description, category badge, account, coloured amount, "vorgemerkt" flag for pending items; collapses to 25 rows with "Alle N anzeigen" toggle (cap 100 from the API)
- feat(frontend): `fd-data-provider` caches `/api/finance_dashboard/transactions` in-memory, refetches on user-triggered refresh and on first rebuild with linked accounts — entity-only state changes no longer trigger redundant fetches, and the endpoint is cache-read only (unbounded-safe, no Enable Banking call)
- refactor(panel): register `fd-transactions-log.js` in `LOVELACE_COMPONENTS`, append component after `fd-recurring-list` in the shell's component tree

## 0.11.1 — 2026-04-20
Version: 0.11.1
Branch: claude/fix-refresh-demo-race-0-11-1
PR: (pending)
Changes:
- fix(frontend): btn-demo now renders neutral/ghost by default — orange fill only when demo mode is active (btn-demo-active), preventing false "already in demo" appearance
- fix(frontend): refresh race eliminated — after POST /refresh, poll for entity state change (≤5s, 500ms ticks) before calling _rebuild(), avoiding stale hass.states read that returned accountCount=0 and flashed onboarding screen
- fix(frontend): _onHassChanged no longer advances _prevStateHash when _loading=true; instead sets _pendingRebuild=true so _rebuild retries immediately after the in-flight rebuild finishes, closing the concurrent-rebuild deadlock

## 0.11.0 — 2026-04-20
Version: 0.11.0
Branch: claude/bold-swirles-d0afe6
PR: (pending)
Changes:
- fix(core): separate cache-reads from live API fetches — `manager.async_get_balance()` now returns cached balances only (was hitting Enable Banking on every HTTP `/balances` call, burning the 4/day/ASPSP rate limit)
- feat(core): serialise user-triggered refreshes with `asyncio.Lock` to prevent double-click concurrent fetches
- feat(core): persist `rate_limited_until` and `last_refresh_stats` across HA restart so the 4/day counter is not lost on reboot
- feat(core): track structured refresh stats (outcome, accounts, transactions, new, duration_ms, errors) exposed via `manager.get_refresh_status()`
- feat(api): new `POST /api/finance_dashboard/refresh` endpoint — the single user-triggered live-fetch entry point, returns stats synchronously
- feat(api): new `GET /api/finance_dashboard/refresh_status` — cache-only polling endpoint, unbounded reads allowed
- feat(core): `refresh_transactions` service now uses `SupportsResponse.OPTIONAL` and returns stats so automations can react to the outcome
- feat(core): refresh_transactions refreshes balances in the same user-triggered round — one click, one cache update
- feat(frontend): refresh button now shows a result toast ("5 Konten, 243 Transaktionen, 2 neu in 3.1s" / rate-limit / partial / error)
- feat(frontend): header timestamp shows live cache age ("Zuletzt 14:23 · vor 2 Std") and updates every minute
- feat(frontend): rate-limit and loading states surfaced clearly next to the refresh button instead of silent "Aktualisieren" reverts
- fix(frontend): "Noch keine Daten" state now has explicit styling + hint to click Aktualisieren
- refactor(coordinator): remove staleness-based auto-refresh — coordinator is now a pure cache projection, live fetches only via dedicated endpoint
- docs(claude-md): replace stale GoCardless references with Enable Banking, document cache vs. live-fetch contract

## 0.10.1 — 2026-04-19
Version: 0.10.1
Branch: claude/pensive-rosalind-793ad9
PR: (pending)
Changes:
- fix(setup): propagate OAuth callback errors through /setup/status so the wizard surfaces them within 2s instead of timing out after 5min
- fix(setup): hard-fail /setup/authorize when callback URL is HTTP (Enable Banking requires pre-registered HTTPS redirect)
- fix(setup): trigger one coordinator refresh after deferred entry reload so entities populate immediately after bank link
- fix(core): raise Repairs issue on missing or invalid Enable Banking credentials, auto-clear on recovery
- fix(frontend): wizard polling stops on setup_error and shows the message instead of waiting for timeout
- fix(frontend): data provider subscribes to entity_registry_updated events so newly created sensors appear without race-prone 4s timer

## 0.10.0 — 2026-04-12
Version: 0.10.0
Branch: claude/sweet-nightingale
PR: (pending)
Changes:
- feat(frontend): add inline bank connection wizard as modal overlay (4-step flow: institution search, bank authorization with polling, account assignment, success)
- fix(frontend): replace fragile entity_id prefix matching with HA Entity Registry lookup — entities are now found by platform + unique_id regardless of HA-generated entity_ids
- feat(frontend): add "+ Konto" button in header to open wizard from anywhere
- refactor(frontend): replace onboarding "Einstellungen" link with inline "Bankkonto verbinden" button
- fix(frontend): add 4s delay before refreshRegistry() after setup complete to wait for HA config entry reload
- fix(frontend): add https scheme validation on auth URLs to prevent XSS via javascript: scheme
- fix(frontend): update institution filter to only re-render list container (prevents cursor jump)

## 0.9.2 — 2026-04-11
Version: 0.9.2
Branch: claude/sharp-shockley
PR: (pending)
Changes:
- refactor(core): remove automatic banking API calls on HA startup — coordinator now loads from cache only, no external calls until user clicks "Aktualisieren"
- refactor(core): remove _first_update force-refresh flag from coordinator — staleness check is sufficient
- refactor(frontend): remove automatic API fallback in _rebuild() — /summary endpoint only called on explicit user refresh, not on every entity change
- feat(frontend): add onboarding welcome screen with "Demo starten" CTA when no bank accounts connected
- feat(frontend): show "Noch keine Daten" timestamp fallback when no refresh has occurred
- feat(frontend): make Demo button more prominent with visible background fill
- fix(frontend): handle loading state in _onData to prevent clearing content during demo toggle

## 0.9.1 — 2026-04-07
Version: 0.9.1
Branch: claude/optimistic-merkle
PR: (pending)
Changes:
- fix(restart): add missing issue-level description to strings.json — Repairs card had no body text, rendering it invisible in some HA versions
- fix(restart): add is_persistent=True to ir.async_create_issue — prevents HA from discarding the issue during internal operations
- fix(restart): wrap synchronous file I/O (exists/read_text/unlink) in async_add_executor_job — HA 2024+ blocks or warns on sync I/O in event loop
- fix(repairs): return None for unknown issue_ids instead of generic RepairsFlow()
- chore: sync translations (en.json, de.json) with new issue description
- chore: sync addon payload

## 0.9.0 — 2026-04-05
Version: 0.9.0
Branch: claude/practical-fermi
PR: (pending)
Changes:
- feat(demo): full demo mode with realistic German banking data (3 accounts, ~35 transactions, household split, recurring patterns)
- feat(demo): toggle via UI button (admin-only), service call, or options flow — persists across HA restarts
- feat(core): manual-only API refresh — coordinator update_interval=None, data only updates on explicit user action
- fix(core): initial coordinator refresh now works on config entry reloads (not just first HA start)
- fix(core): shutdown no longer overwrites real transaction cache when demo mode is active
- fix(api): AttributeError in DemoToggleView coordinator lookup — null-safe access pattern
- fix(api): GoCardless reference replaced with Enable Banking in services.yaml
- fix(coordinator): removed dead COORDINATOR_UPDATE_INTERVAL constant and corrected all docstrings
- feat(frontend): demo toggle button with DEMO badge, aria-pressed accessibility, mobile breakpoint
- fix(frontend): rapid-click guard and loading state for demo API calls
- fix(frontend): demoMode flag propagated in all data events for consistent UI state

## 0.8.1 — 2026-04-02
Version: 0.8.1
Branch: claude/frosty-hoover, claude/competent-payne
PR: #59
Changes:
- fix(frontend): fd-data-provider never called _rebuild when no fd_ entities exist — dashboard stuck on "Lade Finanzdaten..." forever. Added _initialRebuildDone flag to ensure first rebuild always runs.
- fix(core): restart notification deleted by race condition — async_setup_entry unconditionally cleared restart_required issue before polling timer could detect marker. Now preserves issue when marker file exists and polls immediately on setup.
- fix(frontend): prevent infinite loading spinner when no fd_ entities exist — data provider now always triggers initial rebuild
- chore: add .playwright-mcp/ to .gitignore

## 0.8.0 — 2026-03-28
Version: 0.8.0
Branch: claude/compassionate-kowalevski
PR: #56
Changes:
- refactor(frontend): decompose monolithic panel into 10 web components (fd-data-provider, fd-header, fd-stats-row, fd-stat-card, fd-household-section, fd-person-card, fd-category-section, fd-donut-chart, fd-cost-distribution, fd-recurring-list)
- refactor(frontend): entity-first data strategy — fd-data-provider reads HA sensor/number/select entities, falls back to API for household+recurring
- refactor(frontend): panel shell reduced from 507 lines to ~120 lines
- fix(core): coordinator force-refreshes transactions on first cycle — prevents stale cache showing 0,00 EUR
- fix(core): account settings API now persists `person` field for household assignment
- fix(core): monthly summary sensor exposes fixed_costs, variable_costs, household, recurring attributes
- docs: ARCHITECTURE-FRONTEND.md added with component hierarchy, data flow, entity table, event system

## 0.7.8 — 2026-03-28
Version: 0.7.8
Branch: main (hotfix)
Changes:
- fix(core): graceful degradation for household model — exception no longer crashes coordinator
- fix(core): graceful degradation for recurring detection — failure yields empty list
- fix(core): graceful degradation for budget limit checks — log and skip on error
- fix(core): graceful degradation for event firing (balance + transaction) — never blocks data flow

## 0.7.7 — 2026-03-28
Version: 0.7.7
Branch: claude/zen-satoshi
PR: #55
Changes:
- feat(core): integrate HouseholdModel into manager — auto-builds members from account assignments, computes per-person Spielgeld splits
- feat(core): activate recurring payment detection on each transaction refresh
- feat(core): fire fd_transaction_new, fd_balance_changed, fd_budget_exceeded events
- feat(core): budget limit checking against Number entities per category
- feat(core): fixed vs variable cost computation in summary API
- feat(frontend): dashboard shows real bank balance from API (not income minus expenses)
- feat(frontend): person cards with Spielgeld, income ratio, shared costs share
- feat(frontend): shared Fixkosten bar with per-person distribution
- feat(frontend): recurring payments section with detected patterns
- feat(frontend): German category labels (Wohnen, Mobilität, etc.)
- feat(frontend): responsive layout for mobile viewports
- fix(frontend): XSS protection for user-provided names

## 0.7.6 — 2026-03-28
Version: 0.7.6
Branch: claude/stoic-wing
Changes:
- fix(core): add DataUpdateCoordinator — entities no longer call banking API directly
- fix(core): sensor update interval 10 min via coordinator (was ~30 s per entity → rate-limit exhaustion)
- fix(frontend): panel refresh on connectedCallback + 10-min auto-timer instead of every hass setter
- fix(frontend): Lovelace card throttles API calls to max once per 10 min (was every hass setter)
- feat(core): coordinator refreshes transactions only when cache is stale (>6 h), balances every 10 min
- fix(core): manual refresh_transactions service triggers coordinator push to entities


## 0.7.5 — 2026-03-27
Version: 0.7.5
Branch: claude/keen-meninsky
Changes:
- fix(core): expose config entry to API views (entry key was never set)
- fix(core): auto-refresh transactions on HA startup (summary panel showed zeros)

## 0.4.0 — 2026-03-24
Version: 0.4.0
Branch: main
PR: #17
Commit: 513ff1b
Changes:
- Benchmark auto-crawl with 7 German national averages (Destatis, Bundesbank, GDV)
- Drag & drop transaction categorizer (admin-only Lovelace card)
- CSV export service with auto-cleanup (1h TTL)
- GitHub Actions release workflow (creates releases on v* tags)

## 0.3.0 — 2026-03-24
Version: 0.3.0
Branch: main
PR: #16
Commit: 37aa2b8
Changes:
- N-person household budget model (equal, proportional, custom split)
- Recurring transaction detection (monthly pattern analysis)
- Income recognition with salary tolerance ±5 days
- Bonus detection (≥15% above 3-month average → Spielgeld)
- Month cycle logic (calendar vs. salary-based per person)
- Budget limit Number entities per category
- Split model + remainder mode Select entities
- 4 automation events (transaction_new, balance_changed, budget_exceeded, recurring_detected)
- Budget Config Lovelace card (split dropdown, remainder toggle, Spielgeld preview)
- Complete sidebar panel rewrite (donut chart, top-3 costs, fix vs. variable, shared costs bar)

## 0.2.0 — 2026-03-24
Version: 0.2.0
Branch: main
PR: #15
Commit: caedb35
Changes:
- GoCardless OAuth flow end-to-end (4-step config flow)
- Account balance sensors with bank logos (1 per account + optional aggregate)
- Monthly summary sensor with category breakdown
- Transaction fetching + caching in encrypted .storage/ (90-day lookback)
- Privacy-first API (admin-only transaction details, IBAN masking)
- OAuth callback endpoint with user-friendly HTML response
- Full EN/DE translations for all config flow steps

## initial — 2026-03-24
Version: 0.1.0
Branch: main
PR: —
Commit: initial
Changes:
- Initial project scaffold with complete architecture
- GoCardless Open Banking API client skeleton
- Secure credential manager with Fernet encryption + audit log
- Rule-based transaction auto-categorizer
- Companion add-on (Dockerfile, run.sh, payload sync)
- Sidebar panel + Lovelace card (web components)
- Config flow (GoCardless setup + options)
- Version management scripts + CI/CD pipeline
- EN/DE translations
