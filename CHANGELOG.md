# Changelog

All notable changes to the Finance will be documented in this file.

## [0.41.0] — 2026-11-08

### Added
- An account is owned by one person, one person plus the household, or the household only - no other combination; old settings keep their meaning, and changing an account's owners re-derives the stored bookings without a bank call while your corrections stay
- On a person-plus-household account every expense is assigned by one chain - your correction, a merchant rule, the plan position, a decided recurring series, a household category (groceries, housing by default, configurable), the AI hint, otherwise the person; each assignment records where it came from and how sure it is
- The categorisation call also hints whether a merchant is shared or personal (no names, same payload, no extra call, cached per merchant); the categorisation consent text names this and is asked again once
- The owner of any booking, or of all bookings of a merchant or recurring series, can be corrected; the AI can be run on a list of unclear merchants within the monthly budget and with consent
- Per person, what they owe the household (personal spend from the joint account) or the household owes them (household spend from a personal account)

## [0.40.1] — 2026-11-08

### Changed
- Repository links, issue tracker and code owner point to the renamed GitHub account JerryT2T (#187)
- The README explains how to remove the leftover add-on repository from the Home Assistant app store, where it shows up as "unknown" (#187)

## [0.40.0] — 2026-11-04

### Added
- Cash withdrawals, bank fees and person-to-person payments get their own categories (#172)

### Changed
- The unused month_cycle.py is gone (#169)

### Fixed
- Every view now counts the same bookings by one rule - monthly summary, sensors, plan vs actual, home, household summary, notifications, contracts and the wizards show the same total for the same period (#166)
- Money moved between your own accounts no longer counts as spending, however many accounts it crosses; the merchant's debit is the purchase and counts once (#166)
- A payment to or from your own name or a linked IBAN is a transfer, not "other", and a withdrawal from your savings is neither income nor a salary; mark any other counterparty as "this is an account of mine" once and it applies to all past and future bookings (#171)
- A purchase and an unrelated credit of the same amount on two accounts are no longer linked silently; such a pair is asked once as a question (#174)
- A confirmed or rejected transfer stays decided after a refresh, a reprocess and a restart (#173)
- A PayPal purchase counts once, on the PayPal line with the real merchant; the bank debit, top-ups and pay-later instalments are marked as transfers in the list (#167)
- PayPal and pending rows carry their date everywhere - the list shows and filters it, they land in the right cycle and in contract detection, and two equal monthly PayPal payments stay two bookings (#168)
- The monthly summary, sensors, budget events and plan vs actual use the same income cycle as the panel, so income is never zero right after payday; a selected month means the cycle holding its 15th (#169)
- Refunds and settlement credits reduce the cost they belong to in every view and are no income; plan vs actual category and position totals agree, and fixed costs have one definition (#170)
- Cycles start on the real payday even after a large one-off credit: the salary is what recurs per payer, a bonus on payday still opens the cycle, a mid-cycle one does not (#176)
- "Huber" is no Uber, "Bahnhofstraße" no train, "Depotgebühr" no groceries; the holder's own name never decides a category; more energy suppliers are recognised (#172)
- Saved owner corrections now reach the household totals and the split; a booking matches at most one plan position, the most specific, and a position named after a person no longer claims that person's debits (#175)
- A contract's category is now what its bookings count under in every total, the same one the list shows (#177)

## [0.39.0] — 2026-11-03

### Added
- The cycle view leads with a hero - free money until the cycle end, a verdict pill, a labelled bar (today with day count, dashed "Soll bis heute") and three tiles (income, spending, free per day; in the household view shared costs and each person's share) - and below it the latest bookings grouped by day next to "Als Nächstes" and one "Einrichten" strip instead of the separate setup cards
- On desktop the status chip, the horizon tabs and the question count share one top row; the household view uses a neutral blue-grey, orange only ever means over budget or urgent, and purple only marks the "Nur am Desktop" chip
- The transaction list is now reachable on phones and tablets - read-only, grouped by day, searchable; the account column shows only when the list spans several accounts, pending bookings are dashed; categorising stays on desktop
- The home payload carries the last 14 days of bookings for administrators only (no IBAN, no purpose text); other users get no booking rows
- On the cycle view the analysis, account and pot cards sit behind one closed disclosure on desktop, so the Einrichten strip leads

### Fixed
- No text below 12 px in the touched views
- A negative remainder always reads as over the frame; the household tiles name each person's own spending; the data chip says "Aktuell · heute 06:30"

## [0.38.1] — 2026-11-03

### Fixed
- Assigning a refund to another expense on its card now has a search over merchant, text, amount and date, and shows at most 7 entries at a time; the expense you are looking for no longer falls off a list of the 8 newest bookings
- The pick list only offers expenses that are not refunded in full yet, medical ones first; what you already picked stays on top while you search

## [0.38.0] — 2026-11-02

### Added
- The booking-history import now also reads PDF bank statements - the text is extracted on your Home Assistant (no external call), every booking line with date and amount becomes a row, and you get the same preview (new, duplicates, overlap with the bank's own period, invalid rows) and the same per-import undo as with CSV or XLSX
- A PDF whose amounts carry no debit marker is not guessed - it is offered to your own AI provider only after the separate consent, with IBANs masked; password-protected and scanned PDFs get a clear message instead

## [0.37.0] — 2026-11-02

### Added
- The contracts tab gets a search over name and payment purpose, filter chips for type and status (active, overdue, ended, candidate), a filter sheet for category, label, owner and monthly amount, and sorting by deadline or amount; the totals card sums exactly what the filter shows and the filter is remembered per browser
- Optional AI search - ask in your own words ("was zahlen wir im Jahr für Energie?") and your own AI provider turns the question into a filter that Finance applies itself; only the question and the names of categories, labels and persons are sent, never amounts, IBANs, dates or bookings, and only after a separate consent for this purpose that counts against your monthly AI budget
- An AI answer that cannot be read fully shows the understood filter and what was dropped, so you correct it instead of getting an error

## [0.36.0] — 2026-11-02

### Added
- Every contract can be fully edited in one sheet - name, category, rhythm, type, plan amount, owner, notice terms and labels - and reset to the detected defaults
- Merge series that belong together, split one payee by contract number or amount, and assign single bookings (settlements, refunds, PayPal payments) to a contract; merges with a different rhythm or direction are refused, every step can be undone
- Add yearly contracts by hand that the bank has not shown yet; "Kein Vertrag" hides a series for good and releases anything merged into it
- Unsure contract candidates and price changes become questions in the weekly question flow (Vertrag, Abo, regelmäßige oder unregelmäßige Ausgabe, kein Vertrag), each answered question counts once

## [0.35.0] — 2026-11-02

### Added
- Load 13 to 24 months of booking history from your online banking's CSV or XLSX export (Einstellungen, Buchungshistorie) so yearly contracts are recognised right away instead of after two years; the file is read locally, you see a preview with new rows, duplicates and invalid rows before anything is saved, and every import can be undone as a whole
- A file whose columns are not recognised can optionally be read by your own AI provider - only after a separate one-time consent that names exactly what is sent (file content including amounts and dates, IBANs masked locally first) and with the calls counted against your monthly AI budget
- Where the bank delivers bookings itself, its data always wins - duplicates and rows inside the bank's own period are not imported, and a later bank backfill replaces matching imported rows

## [0.34.0] — 2026-11-02

### Added
- Health insurance refunds are matched to the doctor, pharmacy or therapy bills they pay back - in full, in part, or one refund for several bills, up to eight weeks later - and netted in the cycle of the bill, so health costs show what the household really pays and the refund no longer counts as income
- Unsure matches become a question in the question flow ("Gehört diese Erstattung zu dieser Ausgabe?"); in the booking dialog a refund can be assigned to several expenses by hand and reset to automatic
- Bookings labelled "Erstattungsfähig" without a refund yet show as open claims ("Erstattung offen")

## [0.33.0] — 2026-11-02

### Added
- Energy, water, heating and service-charge contracts are recognised as "Verbrauchsabhängig" - the monthly advance stays one stable contract, and the yearly settlement (Nachzahlung or Erstattung) is shown separately under "Abrechnungen" instead of breaking the series
- The expected next back-payment becomes a monthly reserve ("Erwartete Jahresabrechnung"); it is the last settlement minus what a raised advance already covers, and an expected refund lowers the contract's yearly cost instead
- A settlement without a keyword can be assigned from the payee's other bookings in the contract sheet, and removed again; "Verbrauchsabhängig" can be switched on or off

### Fixed
- A price step stays reported as a price change after the next payments at the new price, not only on the first one
- Mobile, streaming, app-store and automobile-club payments land in their life area more often

## [0.32.0] — 2026-11-02

### Added
- Contracts and bookings can carry any number of labels next to their category - 15 starter labels (Energie, Versicherung, Erstattungsfähig, Beruflich / Werbungskosten, Haushaltsnahe Dienstleistung, ...) plus your own; labels stay in Home Assistant
- Every booking of a contract shows the contract's category and labels as "vom Vertrag" - fixing the contract once fixes all its bookings; a booking can get extra labels of its own in the new booking dialog
- Automatic labels show the payment channel (PayPal, später bezahlen, Karte, Lastschrift) and "Preis gestiegen" / "Sonderkündigung möglich"; they cannot be edited

## [0.31.0] — 2026-11-02

### Added
- Spending is sorted into eight life areas - Wohnen kalt, Wohnen warm, Lebensmittel & Haushalt, Mobilität, Gesundheit & Absicherung, Freizeit, Medien & Kommunikation, Finanzen & Verpflichtungen - so every euro lands in exactly one area; income has its own areas (Lohn & Gehalt, Staatliche Leistungen, Kapitalerträge, Erstattungen, Von Privatpersonen); Umbuchungen stay a status, not a category
- On the first start after the update, learned merchants, answered questions, the AI cache, budget-plan positions, pots and contract categories move to the new areas once, after a backup of each store; energy and telecom (formerly "Nebenkosten") and groceries and eating out (formerly "Lebensmittel") are split by fixed keywords, and what no keyword places is asked again in the question flow instead of guessed
- Budget-limit entities move to the new areas and keep their limits; the limits for income and transfers are removed

### Changed
- Change(categories): general online shopping (Amazon, fashion, electronics) has no area of its own any more and lands in the question flow; restaurants and delivery services count as Freizeit

## [0.30.0] — 2026-11-01

### Added
- The contracts page shows "Fixkosten" (contracts and subscriptions) and "Regelmäßige Ausgaben" (regular and irregular spending) as separate totals; uncertain detections never count, and the API returns both totals

### Fixed
- A debit still pending at the turn of the month counts as the current payment, so the contract shows it as last payment and no longer reports "Zahlung fehlt"; amounts still come only from booked payments

## [0.29.0] — 2026-11-01

### Added
- The plan amount of a recurring payment is "Automatisch" by default: the new price after a price change, otherwise the median, so one catch-up or double charge no longer inflates monthly and yearly costs; contracts without a chosen plan amount switch from the highest payment to this rule, so some reserves and yearly costs drop
- The edit sheet lets you choose the plan amount (Automatisch, Höchster, Durchschnitt, Letzter, Median, Fester Betrag) and shows the resulting monthly and yearly cost right away

### Fixed
- A quarterly payment with one doubled instalment and a weekly meal kit with skipped weeks are detected again; skipped weeks or months show as "x × pausiert" while the cost keeps the full rhythm; a series that paused before is not marked ended inside a pause of the same length, and only fixed-price series may pause or carry an outlier

## [0.28.0] — 2026-11-01

### Added
- Every recurring payment has a kind — Vertrag, Abo, Regelmäßige Ausgabe or Unregelmäßig — suggested from the payments (yearly, contract words and numbers, subscription words, weekly or everyday spending) and changeable in the edit sheet; the choice survives new imports
- The contracts page shows the kind on every row and filters the list and its totals by kind
- Regular and irregular spending no longer shows a notice deadline or sends a notice reminder; notice defaults follow the kind (subscriptions monthly without notice, phone and internet contracts 24 months)

## [0.27.1] — 2026-11-01

### Fixed
- A loan instalment, insurance or phone bill paid to an account in your own name (an unlinked bank) is no longer invisible: with a contract word or number and a stable amount it appears under "Prüfen" with the reason "payment to an own name"; plain savings transfers stay hidden, also when their text names a contract word next to a savings word ("Sparplan Rate", "Rücklage Strom")
- Darlehen, Kredit, Mobilfunk and Strom count as contract words for the confidence score

## [0.27.0] — 2026-11-01

### Added
- The setup (Einrichtung) covers only technical and assignment steps: persons with one display name, accounts with bank account type and "data since", payday, region, notifications, AI, points; the last step opens the household plan or says when it becomes possible
- New "Haushaltsplan erstellen" wizard: income suggested from the salary credit, fixed costs from recurring payments, pots with optional account binding, savings goals and a result with monthly balance, per person and plan vs. history; it needs 3 full payday cycles of booked data and rebuilds an existing plan after a confirmation
- What is left over becomes an automatic "Taschengeld" pot per person; a shortfall is shown, saving stays possible
- A household spreadsheet serves as an idea source: position names are matched locally, unmatched names go to the AI only with a one-time consent, amounts never leave Home Assistant
- AI consent is per purpose (categorisation recurring, sheet analysis once) with up to 3 advantages and risks each, revocable on its own in Settings → KI

### Changed
- The plan is called "Haushaltsplan" everywhere; the pot button reads "Topf anpassen"
- The options dialog drops the unused refresh interval, currency and panel switch and the split model (covered by its select entity)

### Fixed
- Saving income from the wizard keeps stored insurance and tax adjustments

## [0.26.0] — 2026-11-01

### Added
- The contracts page has a "Prüfen" section (admins) listing repeating payments that do not clearly look like a contract, with a "Warum?" tooltip naming the reasons
- "Ist ein Vertrag" takes a candidate over as a contract (fixed costs, reserves, reminders); "Kein Vertrag" hides it for good, also after new imports

## [0.25.0] — 2026-11-01

### Added
- Every detected series gets a confidence score with its reasons (direct debit or contract number vs. card payment, stable amount, number of payments, regular day of month, category, contract keywords); the contracts API returns `confidence` and `candidate`

### Fixed
- Card purchases at a café, drugstore or pharmacy that happen to recur monthly are candidates, not contracts: they no longer count in fixed costs, reserves, plan proposals or notice reminders

## [0.24.4] — 2026-11-01

### Added
- The Datenstand page warns admins about accounts with bookings that carry no date at all, with the count per account

### Fixed
- Subscriptions paid through a linked PayPal account are found even when PayPal's own lines carry no booking date; the transaction date counts as the date of such a line (new field `transactionDate`, the stored booking date stays untouched)
- A bank-side PayPal debit is only dropped when a dated PayPal line of the same amount within five days already counts the purchase; otherwise it counts, so nothing disappears and nothing counts twice
- A PayPal funding credit (bank to PayPal) is no income; a pure PayPal top-up counts on neither side
- Carry-over and cycle-history texts show their amounts instead of literal "{amount}" placeholders

## [0.24.3] — 2026-11-01

### Added
- Split parts keep their ids through hashed reference and amount-band keys in the alias table (no numbers or amounts stored in clear)

### Fixed
- Two loans or contracts at one payee are two contracts with their full amounts when the transfer text names different contract, loan, customer or mandate numbers that run in parallel; a number that only changes once stays one contract
- A subscription at a payee that also sells one-off purchases (app store, BNPL provider) is found on its own; the one-offs and finite instalments ("Teil 1/3") stay out, a real price step is still one series
- Energy advances stay one contract even when a yearly settlement from the same supplier sits between them

## [0.24.2] — 2026-11-01

### Changed
- Chore(release): manifest and const carry the version again (0.24.1 had shipped with the old number)

### Fixed
- Purchases paid via PayPal, Klarna, SumUp and other processors are categorised by the remittance text (the merchant, the order), never by the processor's own name; a line without a recognisable merchant stays "other" and is asked in the question flow
- Every purchase through a processor gets its own merchant ("Ihr Einkauf bei …"), so answering one PayPal purchase no longer recategorises all of them; an earlier answer stored for the shared PayPal key no longer applies
- Counterparty names delivered as Latin-1 mojibake ("S.Ã  r.l.") are repaired at import, replacement characters are dropped

## [0.24.1] — 2026-11-01

### Added
- Name variants are remembered in an alias table in the contract store (names only, no amounts), so a contract keeps its id after the old spelling has left the bank history

### Changed
- Test: synthetic acceptance fixtures for contract detection measure recall, false positives and annual-total deviation for the Contract Detection milestone (#106)

### Fixed
- A payee whose name the bank spells differently (punctuation, legal form, broken encoding such as "S.Ã  r.l.") stays one contract with the same id, so term, notice, plan mode and category you entered are kept

## [0.24.0] — 2026-10-29

### Added
- The monthly AI budget is a number field (0-1000, default 100) instead of a 0-100 slider; free providers such as Gemini via Home Assistant no longer run dry after 100 calls
- The star page has an "Offen | Verlauf" switch; "Verlauf" lists every learned merchant newest first with its category, owner and whether you or the AI assigned it (`GET /questions/history`)
- One point per 7 answered questions (was 30), matching the visual-round concept

### Changed
- Docs(security): the AI call budget is user-set, default 100, hard cap 1000
- Test: history order and sources, 7-answer points, cached answers under a used-up budget

### Fixed
- Merchants already answered by the AI are learned from the cache without a new call, also when the budget is used up; before, a cached answer whose memory save was lost never reached the bookings

## [0.23.0] — 2026-10-29

### Added
- "Verbindung testen" in the AI settings asks the configured provider about a made-up merchant (no bank data, counts as one call, never cached) and shows the outcome with its reason (`POST /setup/ai/test`)
- The Datenstand page shows an AI card for admins — state (active / off / not set up), calls this month, merchants learned, last assignment, last test, assignments per category and the latest learned merchants
- `GET /setup/ai` also returns `usable`, `last_run`, `last_test` and `results`; the last categorisation and test outcome are stored as error codes only

### Changed
- Test: connection test outcomes (success, not opted in, no key, budget, unparsable, timeout), results summary, outcome merge

## [0.22.0] — 2026-10-29

### Added
- The panel is rebuilt to the visual-round concept — one screen with time horizons, the Person ⇄ Haushalt pill at the bottom, a gear for settings and subpages with one shared header (Datenstand, Zyklus, Buchungen, Budgetplan, Fragen, Einstellungen); the old tabs, the overview and eleven legacy components are removed
- Only an explicit "Neu importieren", the setup bootstrap and the daily schedule reach the bank; `POST /refresh` requires `{"trigger":"user_import"}` and the open-panel auto refresh is retired; "Aktualisieren" re-derives from the cache (`POST /reprocess`)
- Person view shows own items and own Spielraum (budget, spent, remaining); desktop side column with accounts, optimisation and a 6-cycle history per pot with carry-over accept/drop (`POST /pots/carry`)
- Question cards list the bookings behind them (date, amount, account, counterparty, last four IBAN digits, text) and how often the merchant occurred
- New wizard steps — plan prefilled from detected contracts, savings goals, points event (`finance_dashboard_points_awarded`, counter/input_number helper), opt-in AI categorisation (HA AI, xAI Grok, Anthropic, OpenAI; key Fernet-encrypted and write-only; at most 100 calls per month) and editable nicknames per person
- Merchants left uncategorised after derive/import are categorised by the opt-in AI provider; payload is merchant and remittance text only

### Changed
- Docs: binding UI spec `docs/dev/ui-concept-gap.md`, fetch-trigger table, setup-wizard and categorisation contracts; live-audit and visual-round concept pages
- Test: user-id `ha_users`, explicit refresh trigger, booking details, pot history and carry-over, wizard steps, AI provider gating

### Fixed
- The sensor platform no longer crashes when an account's `ha_users` holds plain user ids instead of objects; the crash left balance, bank and month sensors unavailable and the panel showed the onboarding although banks were linked
- The Lovelace budget card reads option list and value from the split/remainder select entities; the transactions-log component lost its data source and is retired

## [0.21.0] — 2026-10-28

### Added
- The budget-plan step imports the household spreadsheet directly — upload an .xlsx file or paste a Google Sheets link; before, it only pointed to the import_spreadsheet service and a file in the config folder
- `POST /budget_plan/upload` (base64 .xlsx, max 5 MB, parsed in memory, never written to disk) and `POST /budget_plan/import_url` (Google Sheets shared "anyone with the link"; only the sheet id is taken from the link and the export URL on docs.google.com is built by the integration, so a pasted link cannot target another host); both admin-only

### Changed
- Docs(security): the Google Sheets export download is the one further allowed external call — user-triggered, nothing sent
- Test: link parsing and host rejection, upload decoding, size cap, unshared-sheet detection, parsing from bytes, admin gating of both endpoints

## [0.20.2] — 2026-10-28

### Changed
- Test: middle-name and look-alike cases in the own-name filter test

### Fixed
- A payment to an account holder's own name also counts as an own transfer when the bank adds a middle name or title ("Jeremy Tim Treder" for the holder "Jeremy Treder"); every word of the holder name must appear, so a similar-looking business name stays a contract

## [0.20.1] — 2026-10-28

### Changed
- Test: 647 tests (own-transfer and own-name filters, owner kinds, freshness fallback, display name)

### Fixed
- Own transfers between household accounts are no longer listed as contracts (the whole chain counts as one transfer, also its source leg), and payments to an account holder's own name are skipped too; on the live install a transfer to the own account showed as a 46.567 €/year contract with a notice deadline, and the notice reminder used the same list
- The owner split names the household share "shared" as the contract says; before, "Der Haushalt trägt" always read 0,00 €
- Before the first logged import, "Stand" and "Letzter Import" use the newest successful bank fetch instead of claiming nothing was imported
- Contracts show the creditor as the bank writes it ("Vodafone GmbH", not "vodafone gmbh"); savings-account toggles show account name and masked IBAN instead of three identical "DKB" rows
- Source notes are shown in German in the German UI (`note_de` in the bundled dataset)

## [0.20.0] — 2026-10-28

### Added
- The Household tab runs on the household cycle instead of the calendar month (cycle starts at the highest income, or another person's highest income within the 7 days before; calendar month only without income), own transfers between household accounts are excluded, and no savings rate is shown without income
- Merchant names are normalised and a learned merchant memory (merchant → category and owner) applies before the keyword rules; one-off booking corrections win over both. Open questions are picked by euro impact, at most 10 per week
- Flash-card questions — the star on Start opens the cards; answer, skip or "always like this"; every 30 answers earn a point
- Guided setup wizard (accounts, persons, payday, region, plan, pots from history, AI opt-in, notifications) with resume on Start; a confirmed payday anchors the cycle; pots are suggested from the median of past cycles
- The bank section splits "Neu importieren" (fetch raw bank data, then reprocess) from "Aktualisieren" (reprocess the stored raw data only, no bank call); an import log and a monthly validity check feed the new freshness subpage
- Series of any interval become contracts with notice periods and deadlines; annual and irregular costs get a monthly reserve and pot coverage (Jahr tab: Verträge)
- A bundled, versioned German household benchmark dataset (state and postcode level where available), never fetched at runtime (Jahr tab: Vergleich)
- German notifications for large debits, double charges, a missing salary and expiring or expired consent, a weekly digest, and a reminder when a contract's notice deadline is near
- Household members (non-admins) get their own person view; admin actions (import, demo, add bank, renew consent) are hidden for them, and transactions stay aggregate-only

### Changed
- Test: 643 tests (household cycle, merchant memory, questions, freshness, contracts, benchmark, setup wizard and member gating)

### Fixed
- Fix: harden/polish pass — region validated before any write, missing cycle-rule label, postcode escaped, timers cleared on disconnect, recurring log without amount or name, settings and plan texts moved into the locale files

## [0.19.2] — 2026-10-28

### Fixed
- Locale files load with the version query. The static path is cached long, so after an update a browser kept the old `de.json` and Start showed raw keys such as `home.setup.assign_title`
- "Personen & Konten" offers the suggested household members directly as account owners; picking one makes them a person, so an account can be assigned to a person without first switching them on in step 1 (before, only "Haushalt" and "Offen" were offered)

## [0.19.1] — 2026-10-28

### Added
- Rent pool, Kaufland, Penny, Globus and Metro are recognised (housing / food)

### Changed
- Docs: the test skill points at the local, out-of-repo HA access file
- Test: 4 regression tests (subentry adoption, attended IBAN fill, no details on background, person-entity suggestion)

### Fixed
- Bank accounts referenced only by a bank subentry (banks linked by 0.16.0/0.16.1) are adopted into the entry on setup. The live install had none stored, so every balance carried an empty account key, "Personen & Konten" listed no account and Start stayed on "Wem gehört was?" with no way out
- An attended refresh fills a missing IBAN and bank account name once per account (details call with PSU headers, never on the background fetch); the entity key stays the same
- The household "Gesamtsaldo" counted the available-balance sensors as extra accounts — 7 instead of 4 accounts and booked plus available summed
- HA users not linked to a person entity (MQTT, wall tablet, PC logins) are no longer suggested as household people when the install has person entities

## [0.19.0] — 2026-10-28

### Added
- `GET/PUT /api/finance_dashboard/assignments` (admin only) — household persons, HA-user → person mapping with suggestions (system/inactive users flagged), account owner per IBAN identity (person, household or open); persisted in the config entry, IBAN only as last 4 digits
- The logged-in user resolves to a person through the persons list too; the home payload carries a `setup` block (persons, user mapped, accounts assigned, pots)
- Overview redesigned in the new design system — person and household cards (single accounts desktop-only), bank cards with consent pills and the automatic-fetch limit, transactions as cards, and the new "Personen & Konten" settings with an unassigned-accounts banner
- Household tab redesigned — "Meins · Deins · Unseres" person cards with person colours, plan vs actual verdict with rule-based "Was das heißt", who carries what, per category with fixed/variable tags; ledger, income, transfers and benchmark desktop-only
- Start shows a setup card instead of "0 € · passt" when there is no budget, hides the person toggle without a mapping, caps the question badge at 99+

### Changed
- The legacy colour variables alias the `--fd-*` tokens, so every remaining component follows the new design; no red anywhere
- Test: tests/test_assignments.py (GET flags and IBAN masking, persistence, validation, resolve_person, setup block, admin gating)

## [0.18.2] — 2026-10-28

### Added
- The old title bar is gone; the Start tab opens straight into the new home top bar, and the tabs use the HA primary colour of the new design
- Demo, refresh and "add bank" moved to the Overview tab; the Start tab's freshness note gains a "Refresh now" button (attended refresh, same endpoint)

### Changed
- The obsolete month label and "Finance Dashboard" heading are removed

## [0.18.1] — 2026-10-28

### Added
- A quiet desktop-only footer "Finance vX.Y.Z · Open in HACS" deep-links to the HACS repository page to check for and install updates

### Fixed
- The panel no longer stays blank forever. HA assigned hass/narrow/route/panel before the panel class was defined (the kit import delays the definition), so the values shadowed the setters and the panel never rendered; the constructor now re-assigns them through the class
- On phones the header wraps instead of pushing the freshness text off-screen, and the panel shows HA's menu button so the sidebar can be opened

## [0.18.0] — 2026-10-28

### Added
- New first tab "Start" — the home screen per horizon (Heute · Woche · Zyklus · Jahr), swipeable, with a Person ⇄ Haushalt pill; Heute shows only today's free amount and pots, Woche the daily linear budget with carry-over within the cycle, Zyklus the Soll line, "Als Nächstes" (pending bookings inline with a label), "Wusstest du schon?" and reserves, Jahr a light year view
- Income cycle rule — a person's cycle runs from their earliest highest income to the next; the household starts at the highest income unless another person's highest income falls within the 7 days before it
- Pots with a cycle-wide balance, average per day and carry-over only within the cycle; status passt / knapp (≤ +10 % over linear) / drüber
- `GET /api/finance_dashboard/home?horizon=&view=` (cache only, no bank call) and pot create/update/delete; a person view shows only that person's items, the household view shows other persons as totals only
- Design-system tokens (surfaces, status semantics, person colours, desktop-only marker) and a shared tooltip style
- Test: 45 new tests (cycle edge cases, carry-over, ±10 % status, zero line); 484 tests green

### Changed
- Docs: README marks the project as alpha, not recommended for use; roadmap records the next visual-round slices

## [0.17.2] — 2026-10-28

### Added
- The bank row reads "Bank limit: x/4 automatic fetches today (manual unlimited)" and shows the last manual fetch, so an attended refresh is visible although it never counts against the limit; the budget sensor is renamed "Automatic fetches today (bank limit)"

### Changed
- Test: 3 regression tests (UTC window, local budget day, last manual fetch)

### Fixed
- Fetch-window dates are computed in UTC. Between local and UTC midnight the local `date_to` lay in the bank's future, and PayPal rejected every refresh with HTTP 422 until 01:00
- The background fetch budget counts per local day (HA time zone) instead of per UTC day, so the 06:30 call of the day before no longer shows as "today" after midnight

## [0.17.1] — 2026-10-26

### Changed
- Test: 435 tests green

### Fixed
- Pending bank entries with no booking date (explicit null) crashed processing after a refresh, so the panel showed 0 transactions. Nulls are now normalised, and existing ledgers are rebuilt automatically (processing version 2)
- Raw bank responses and the ledger are now saved before derivation, so a later failure never loses fetched data

## [0.17.0] — 2026-10-26

### Added
- Lifelong history — the first attended fetch per bank session pulls the maximum history the bank allows (tries 3650, 730, 365, then 90 days). The raw archive and the balance history are kept forever by default (retention option 0 = forever)
- Raw snapshots carry replay metadata, so the ledger can be rebuilt from the raw archive. The ledger is rebuilt automatically when PROCESSING_VERSION changes; a backup of the old ledger is kept
- New admin service `finance_dashboard.reprocess_data` rebuilds the ledger from the raw archive on demand

### Changed
- Test: 432 tests green

### Fixed
- A short bank answer never erases older history that is already stored

## [0.16.2] — 2026-10-26

### Changed
- Test: 421 tests green (regression test for a bank linked without stored account records)

### Fixed
- "Aktualisieren" reached no account after a bank was linked, so the panel showed 0 transactions. Linking stored only account references in the bank subentry, while the refresh reads the integration's account list, which stayed empty on a fresh HACS install. Linking now also stores the account records there (merged by IBAN identity, so names and entity ids survive a re-link); the subentry still carries no account number. Accounts without an IBAN (cards) are identified by their identification or name instead of the per-session id
- Banks linked with 0.16.0/0.16.1 are fetched without re-linking — a subentry account without a stored record gets a minimal one (named "<Bank> 1", "<Bank> 2", …) until the bank is re-authorised via the subentry's reconfigure

## [0.16.1] — 2026-10-26

### Changed
- Test: 420 tests green (regression test for the details endpoint and nested IBAN)

### Fixed
- Adding a bank failed right after authorising at the bank ("Die Bank oder Enable Banking hat einen Fehler gemeldet"). Account details were requested from `/accounts/{id}`, which Enable Banking does not serve (HTTP 404); they are now read from `/accounts/{id}/details`, with the IBAN taken from the nested `account_id`. The scheduled and manual account refresh used the same call

## [0.16.0] — 2026-10-26

### Added
- Own brand icon and logo (light/dark, @2x) served from the integration's `brand/` folder
- Sidebar panel registered via `panel_custom` (admin only, cache-busted URLs); the Lovelace cards are auto-loaded on every dashboard, so they can be placed in any dashboard tab
- Banks are config subentries linked through my.home-assistant.io (redirect URL to register at Enable Banking: `https://my.home-assistant.io/redirect/oauth`), with reconfigure and a repair issue when consent expires. The old callback was built from the request host and broke across internal/external URLs
- Per-bank and per-account daily background fetch budget — the scheduled refresh uses at most 1 of the bank's 4 daily calls, attended calls stay uncapped but debounced, a 429 blocks only the affected bank for 6h, transactions are fetched incrementally and pagination has a loop guard
- Every fetch is stored as a Fernet-encrypted raw snapshot (monthly stores, 400-day retention) plus a deduplicated encrypted ledger and balance series. The previous code claimed encryption at rest but stored plaintext; the legacy plaintext cache and single-session layout are migrated automatically
- Devices per bank and per account with balance, available balance, last update, consent valid-until and state, fetch budget, blocked-until, last error and a refresh button; balance history is imported into long-term statistics; redacted diagnostics; `runtime_data`; `quality_scale.yaml`
- Facts-only panel overview (accounts, bank status, admin-only transaction search); the existing household features sit behind the new `show_household` option

### Changed
- BREAKING — HACS-only distribution (minimum HA 2026.3). The Supervisor companion add-on and its payload sync are removed; install the integration as a HACS custom repository, uninstall the old add-on and restart
- BREAKING — the split-model and remainder select entities now report slug states (`pooled_equal`, `equal`, `proportional`, `custom`) with translated labels. Automations that matched the old display text must be updated
- BREAKING — the in-panel setup wizard and its `/setup/*` endpoints are removed. Banks are added under Settings → Devices & services → Finance → Add bank
- Chore(manifest): `iot_class` is now `cloud_polling`; `my` and `recorder` added to `after_dependencies`
- Docs: CLAUDE.md slimmed to an index; developer detail moved to `docs/dev/`
- Test: 419 tests green on HA 2025.1.4 / Python 3.12 and on HA 2026.10.4 / Python 3.14, plus a boot smoke test on HA 2026.10.4

### Fixed
- `_build_stats` was missing `@staticmethod`, so every live refresh raised
- The options flow dropped the `daily_refresh_*` settings
- Panel auto-refresh referenced an undefined `DOMAIN`
- The coordinator did not pass `config_entry`, which made setup fail on HA 2026.10
- `strings.json` lacked the `services` section
- Hassfest — `cryptography` and `PyJWT` removed from `requirements` (both ship with Home Assistant core and must not be listed by a custom integration); `CONFIG_SCHEMA` declared as config-entry-only; the fixable repair issues (`consent_expired`, `consent_expiring`, `restart_required`) carry their explanation in the fix-flow step instead of a top-level description, which hassfest rejects for fixable issues

## [0.15.3] — 2026-10-19

### Fixed
- Release: v0.15.2 never published — the add-on payload copy of `api/_helpers.py` still carried the two `noqa` comments the ruff cleanup removed from the source, so the payload sync check failed both Validate and Release. Payload resynced; 0.15.3 ships the 0.15.2 delivery fix
- Test: `test_retry_after_header_wins_over_default` used a fixed +90 min Retry-After, which crossed the midnight cap on runs after 22:30 and failed; it now stays below midnight whatever the clock says

## [0.15.2] — 2026-08-20

### Changed
- Test: the delivery path had zero coverage. `tests/test_addon_installer.py` executes `run.sh` for real against a temporary root (`FD_CONFIG_ROOT` / `FD_PAYLOAD_ROOT`, `FD_RUN_ONCE`) and pins the stale-module removal, the restart marker, the Lovelace copy, a bare first install, the no-op path, and the `startup: services` contract itself — total 315 → 323
- Ci: `bash -n` on run.sh, and `.gitattributes` pins `*.sh` to LF — a CRLF checkout breaks the shebang inside the Alpine container, failing as a stopped add-on rather than an error
- Chore: cleared the 7 ruff findings that had accumulated in files this branch does not touch (two dead `noqa` directives, two unsorted import blocks, three shared mutable class attributes now `ClassVar`). `ruff` ships in the test requirements but no gate ever ran it, so the debt was invisible

### Fixed
- The companion add-on ran with `startup: once`, so it had already exited by the time Supervisor auto-updated it — and Supervisor only restarts add-ons that were *running*. The installer therefore only ever executed on a host reboot. On the reporting instance the add-on package sat at 0.14.0 while `/config` still held 0.13.0 with a file timestamp of 2026-04-25; 0.13.1, 0.14.0, 0.15.0 and 0.15.1 never reached disk. The add-on is now a resident service (`startup: services`) that installs on start and re-checks hourly, so every auto-update delivers its payload the minute it lands
- The installer replaces the integration tree instead of copying over it. `cp -r` removes nothing, so `api.py` and `manager.py` from 0.13.0 survived next to the packages of the same name that replaced them, together with their stale `__pycache__`. The delete sync is guarded by an allowlist — it deletes recursively, and only the two paths it owns
- A failed install no longer kills the container. Exiting left the add-on stopped, which is precisely the silent-failure mode that hid this outage for four months; the run is retried on the next interval instead. A TERM/INT trap plus backgrounded `sleep` lets a Supervisor stop take effect immediately rather than after the SIGKILL timeout
- The install-state file is rewritten on every check, not just on an update. Its timestamp is the only evidence visible from outside the container that the installer is alive — a stale one is what identified this bug

## [0.15.1] — 2026-08-20

### Changed
- Test: pin the empty-account-list case — total 314 -> 315

### Fixed
- The entity-registry reconciler removed every balance entity when the config entry listed no accounts. An empty list means "we do not know what is linked" — a half-configured setup, a storage-recovery round, a re-auth that cleared the list before failing — not "all orphaned". Reconciliation now returns early in that state, so it can no longer destroy history HA cannot restore. Found by re-reading the 0.15.0 diff before promoting it to stable

## [0.15.0] — 2026-08-20

### Added
- Institution catalog is cached (24h TTL). A fresh cache skips the API entirely; an outage degrades the wizard to the stale list, flagged with its date, instead of an empty one. An empty API result counts as a failure — DE always has banks
- Opening the panel triggers one attended live refresh when the cache is older than the configured threshold (default 60 min, `auto_refresh_on_open` / `auto_refresh_max_age_minutes`). Once per panel mount, never on an interval — this is what makes DKB balances current without spending the background budget

### Changed
- Test: +48 tests covering catalog rate-limit exemption and cache fallback, account identity and re-link dedup, registry migration/orphan cleanup, and the attended/background split — total 266 → 314, all green

### Fixed
- The setup wizard reported every failure as "Banken werden geladen…" — all three catch blocks assigned the LOADING string as the error message, so the real exception was discarded before anyone could read it. The wizard now surfaces the backend's `error_type` as a readable cause, appends the raw detail, distinguishes an HTTP status from a transport failure, and offers a retry button
- The bank list was gated on the 4/day ASPSP quota. `/aspsps` is Enable Banking's own catalog, not a call to any bank — it neither spends nor is bound by that quota — so a user who had refreshed four times could not connect a new bank until midnight. `_get_setup_client` now takes `enforce_rate_limit`, and the catalog opts out
- Account identity is now the IBAN, not the Enable Banking session uid. The uid is reissued on every re-link, so re-connecting a bank created a second set of entities for the same real account and orphaned the first. `account_identity.py` derives a stable key (truncated SHA-256 — the key lands in the entity registry, so it must not carry the account number), merges re-links onto it, and preserves user-owned fields (custom name, type, person, HA users) across the merge
- Entity registry is reconciled on setup — entities still on the uid-derived `unique_id` are migrated in place (entity_id and history preserved), and balance entities owned by no linked account are removed. This clears duplicates left by earlier re-links
- Attended calls are no longer gated on the rate limit. PSD2 RTS Art. 36(5)(b) caps AISP access only when the user is not in session; with PSU headers present the cap does not apply, so refusing the refresh button while rate-limited denied a call the bank permits. The refresh endpoint, the manager pre-flight check, the header button and the panel's client-side guard all now distinguish attended from background
- A 429 backs off 6h (Enable Banking's documented retry) instead of until midnight — a rate limit at 07:00 used to cost the entire day. An attended 429 is transient upstream noise and pauses 15 minutes. `Retry-After` still wins, capped at midnight where the ASPSP day counter resets

## [0.14.0] — 2026-08-17

### Added
- Budget_plan.py — cost-position ledger, the model the household spreadsheet is built on. Positions carry an explicit owner (person or shared), a signed amount (negative = reimbursement billed onward), a kind (fixed or buffer with units x unit price), an inclusive YYYY-MM validity window, and an optional debit account independent of the owner
- Spreadsheet_import.py — migrates a `Kalkulation Haushalt.xlsx` workbook into the plan. Recovers buffer factors from formulas (`=80*4.5`), validity windows from prose comments ("bis inkl. April 2027"), and cross-checks recomputed net income against the sheet's own stated net, reporting any mismatch
- Transfer_plan.py — reproduces the workbook's monthly transfer choreography (accounts x ordered steps) and enforces its central invariant in code: a pass-through account must net to zero. Contributions are liquidity-aware, so a person whose income cannot cover their share contributes what they have and the rest is carried by those with a surplus
- `settlement_delta` per person — how much one person is fronting for another. The spreadsheet contained this implicitly as the gap between account balance and entitled pocket money; it is now explicit
- `pooled_equal` split model — shared costs paid from POOLED net income, remainder split equally, each person then paying their own individual costs. Now the default. The previous models computed a materially different result and could not carry a person with negative net income
- Plan-vs-actual comparison per category and per position, with unmatched positions reported as unmatched rather than shown as zero
- BenchmarkProvider wired up — it was dead code with zero imports repo-wide. The "ours" side is now computed from the plan, plus a manual water-consumption metric (not derivable from banking data)
- /budget_plan, /transfer_plan, /plan_vs_actual, /benchmark, plus admin-gated position/income/import endpoints. Import paths are validated against `allowlist_external_dirs`
- Fd-budget-plan card — income breakdown, cost ledger grouped by owner, pocket money, transfer table with the zero-sum badge, benchmark comparison
- Once-daily scheduled refresh at a configurable time (default 06:30). One call of the 4/day/ASPSP budget, leaving three for manual refreshes
- `import_spreadsheet` (admin-only, allowlist-checked) and `get_transfer_plan`

### Changed
- Test: +81 tests covering the plan model, the split invariants, transfer-plan balancing, and the Enable Banking normalization layer that had no coverage at all — total 185 → 266, all green
- Chore(deps): openpyxl>=3.1.0 for spreadsheet import

### Fixed
- Transaction fetch could never parse a real Enable Banking response. The API returns `{"transactions": [...], "continuation_key": ...}` — a LIST — while the client called `.get("booked")` on it, raising AttributeError for every account. Swallowed by a broad handler, so refreshes reported success over an empty cache
- Derive the amount sign from `credit_debit_indicator` (CRDT/DBDT). It appeared nowhere in the codebase, so every transaction would have read as income with total expenses stuck at 0
- Honour per-transaction `status` (BOOK/PDNG) instead of hardcoding buckets; join `remittance_information`, which is an array, not a string
- Follow `continuation_key` pagination, capped at 10 pages with the truncation logged rather than silent
- Pass ISO 20022 balance codes through (CLBD/ITAV/...) and match them in the sensor's priority list, which previously listed only camelCase names and could never match — so each account showed whichever balance the bank happened to list first
- HA start crashed on every restart — a sync lambda calling `hass.async_create_task` from a worker thread tripped HA's thread-safety guard, the coroutine was never awaited, and the transaction cache was therefore never loaded. Entities stayed empty until a manual refresh
- Merge each fetch window into the cached history instead of replacing it. Every refresh previously truncated history to the rolling window, making multi-month views impossible to populate
- Only stamp `_last_refresh` when at least one account answered. A total failure used to look identical to a success, and the false timestamp survived restarts via persistence
- Tag pending transactions with account/person like booked ones
- Expose `last_refresh_stats`, `is_refreshing`, `cache_age_seconds`, `cache_is_stale` — the frontend already read these keys, which never existed, so a stale cache was visually indistinguishable from fresh data
- Honour the documented `days` field on `refresh_transactions` and month/year on `get_monthly_summary`; both were advertised and ignored
- A "Kommentar" column header was read as a person column, so every validity window in the sheet was lost
- The transfer plan reports amounts it cannot place on any account (`unplaced`) instead of dropping them. Without a joint account every shared position was skipped, no account ended up out of balance, and the plan declared itself balanced while omitting the largest cost block
- sync_changelog.py appended every entry to the BOTTOM of CHANGELOG.md — its header-detection regex alternation included `$`, which matches every blank line, so the insertion point became the last blank line of the file. `--check` read the first heading and therefore reported the CHANGELOG as permanently behind while claiming each sync succeeded. Added `--repair` and re-sorted all 44 accumulated sections newest-first

## [0.13.1] — 2026-05-16

### Added
- Global :focus-visible outline rings + prefers-reduced-motion override in SHARED_CSS
- Aria-expanded on transactions-log show-more toggle
- New design tokens in SHARED_CSS (--r-sm/md, --sh-sm/md/lg, --fs-sm/md/lg/xl, --lh-tight/normal, --sp-xs/sm/md/lg/xl) for upcoming token-migration polish

### Changed
- Remove unused TRANSACTION_REFRESH_STALENESS constant + timedelta import
- Test: +20 unit tests for events.py (11) + export.py (9 incl. OSError/OverflowError monkeypatch paths) — total 165 → 185, all green
- Chore(lint): ruff sweep across tests/ — 44 fixes (import order, unused imports, datetime.UTC migration)
- Chore(payload): re-sync addon mirror (incl. pre-existing UTC drift from v0.13.0)

### Fixed
- RateLimitExceeded on /setup/complete surfaces as error_type=rate_limited in HTTP 200 body (matches setup-wizard contract; was previously masked as generic failure)
- Categorizer None-guard with WARNING log — refresh races ahead of init fall back to category="other" instead of crashing
- Cleanup of old CSV exports swallows OSError/ValueError/OverflowError and logs cause (no more silent bare-except)

## [0.13.0] — 2026-04-25

### Added
- MultiFernet credential storage with key rotation + v1→v2 migration (S2)
- Timing-safe OAuth state validation with one-time-use, 10min TTL, 32-entry cap, cross-store fallback (S4, F1, F3, F5)
- Unified setup-wizard rate-limit gate via async_make_setup_call + persistent fresh-setup gate (S3, F2, F4)
- IBAN/account-id/EUR-amount log sanitizer; raw API bodies no longer hit ERROR-level logs (S1)
- Pre-commit secret-scan hook (.pre-commit-config.yaml + scripts/check_no_banking_data.py) (R11)
- PyJWT[crypto] migration with iss=application_id, aud=api.tilisy.com, per-request jti (A4)
- Shared aiohttp ClientSession via async_get_clientsession (A5)
- Retry-After header honored on 429 + PSU headers for online-mode (D5, D6)
- /refresh_status exposes rate_limit_per_day + cache_is_stale + cache_age_seconds (D7, D9)
- Setup-wizard modal with role/aria-modal/focus-trap/ESC (U1)
- Institution list with full keyboard navigation (role/listbox/option) (U2)
- Donut chart aria-label + visually-hidden table fallback (U3)
- Toast aria-live based on severity (assertive for warn/error) (U4)
- Cost-distribution role/group + per-segment aria-label (U5)
- I18n with locale JSON files + hass.language detection + tSync helper (U6, G1-G4)
- Skeleton/loading states across all card components (U8)
- + Bank entry-point opens wizard from header (U10)
- Countdown for setup-wizard auth-polling step (D8)
- Persistent notification after config_flow completion (U11)

### Changed
- Split api.py (1258 LOC) into api/ package (setup, refresh, data, static, demo, _helpers) (A1)
- Split manager.py (1151 LOC) into mixin modules (RefreshMixin, PersistenceMixin) (A2)
- Persistent component tree replaces full-rebuild on every data update (A3)
- SHARED_CSS adoption + CAT_COLORS/LABELS consolidation in fd-shared-styles (F2, F3)
- All hardcoded color literals replaced with CSS tokens (F4)
- Unified disconnectedCallback for memory cleanup (F5)
- Shared escHtml helper (F8)
- Month label as static span (U7)
- Chore: remove deprecated GoCardless client (F1)
- Manager.async_set_accounts encapsulation (F6)
- Perf(security): reuse audit-log Store instance (F7)
- Chore(manifest): iot_class cloud_polling → cloud_push (D2)
- Docs: align repairs.py role + sync services.yaml (D3, D4)
- Docs: precise update_interval docstring on coordinator (D10)
- Test: scaffold tests/ + pyproject.toml + requirements_test.txt (T1, T6)
- Test: cache-vs-live-boundary contract test as guardian (T2)
- Test: JWT/Fernet edge-case coverage (T3, 21 tests)
- Test: parametrized categorizer rule coverage (T4, 79 tests)
- Test: transfer-detector cascade + override + confidence (T5, 27 tests)
- Chore(ci): pytest with coverage in validate workflow (T7)
- Docs: sync CLAUDE.md phases with actual code state (D1)
- Docs: audit-synthesis concept page (Phase 2 artifact)
- Result: 165/165 tests pass; ruff 0 errors; coverage 31% (categorizer 96%, transfer_detector 91%, const 100%); payload synced

### Fixed
- /refresh and toggle_demo now require admin (R9, R14)
- Partial-refresh per-account cache prevents data loss on partial bank failure (R5, F10)
- Corrupt .storage recovery via try/except + repair-issue (R8)
- Static file serving non-blocking via async_add_executor_job + LRU cache (R12)
- Repair-issue payloads scrubbed of exception strings (R10)
- _reconstruct_pem PKCS1/PKCS8 detection corrected (C9)
- Responsive breakpoint at 980px for category section (U9)
- Mark auth+storage repairs as is_persistent (D11)
- Fix: dt_util.now() instead of datetime.now() throughout (D12)

### Changed
- Register `fd-transactions-log.js` in `LOVELACE_COMPONENTS`, append component after `fd-recurring-list` in the shell's component tree

## [0.12.1] — 2026-04-24

### Changed
- Drop unused `ENABLEBANKING_RATE_LIMIT_DAILY` import, move `RateLimitExceeded` below all imports for a clean module layout
- Replace stale "GoCardless/Nordigen" docstring in `__init__.py` with Enable Banking PSD2 reference and document the 4/day/ASPSP rate-limit gate
- Replace stale "GoCardless Open Banking API" description in `finance_dashboard_companion/config.yaml` with Enable Banking PSD2

### Fixed
- Preserve partial balances when Enable Banking rate-limit hits mid-fetch — accounts that succeeded before the 429 no longer lose their fresh value, merged into the existing cache instead of being discarded
- Reconstruct `_previous_balances` baseline from cached balances on `async_initialize` so the first refresh after every HA restart no longer fires spurious `fd_balance_changed` events for every account
- Balance-refresh end path now merges into existing cache instead of replacing — accounts that errored this round keep their last known value
- Deferred reload after setup-wizard completion now triggers a real live refresh via `manager.async_refresh_transactions()` instead of a cache-only `coordinator.async_refresh()` — entities populate with actual bank data immediately, no more "unavailable" state until the user clicks "Aktualisieren"
- `async_load_cached` failure path publishes an empty snapshot so entities stay `unknown` (recoverable) instead of `unavailable` (stuck) when cache read errors
- `refresh_accounts` service call now pushes the updated state through the coordinator so dashboards reflect the new account metadata immediately, matching `refresh_transactions` behavior
- Always load the cached snapshot into the coordinator regardless of `configured`/`demo_mode` state so half-configured entries don't leave entities permanently unavailable
- `BudgetLimitNumber` now inherits from `RestoreEntity` — user-set budget limits survive HA restarts instead of silently resetting to 0
- `SplitModelSelect` and `RemainderModeSelect` listen for config-entry updates and re-sync their current option when the options flow changes the stored key — no more stale display after external option changes
- `/demo/toggle` returns HTTP 503 when no manager is configured instead of toggling a dead `hass.data` flag that nothing reads

## [0.12.0] — 2026-04-23

### Added
- New `fd-transactions-log` card shows imported (cached) transactions after at least one bank is linked and a refresh ran — date, counterparty, description, category badge, account, coloured amount, "vorgemerkt" flag for pending items; collapses to 25 rows with "Alle N anzeigen" toggle (cap 100 from the API)
- `fd-data-provider` caches `/api/finance_dashboard/transactions` in-memory, refetches on user-triggered refresh and on first rebuild with linked accounts — entity-only state changes no longer trigger redundant fetches, and the endpoint is cache-read only (unbounded-safe, no Enable Banking call)

## [0.11.1] — 2026-04-20

### Fixed
- Btn-demo now renders neutral/ghost by default — orange fill only when demo mode is active (btn-demo-active), preventing false "already in demo" appearance
- Refresh race eliminated — after POST /refresh, poll for entity state change (≤5s, 500ms ticks) before calling _rebuild(), avoiding stale hass.states read that returned accountCount=0 and flashed onboarding screen
- _onHassChanged no longer advances _prevStateHash when _loading=true; instead sets _pendingRebuild=true so _rebuild retries immediately after the in-flight rebuild finishes, closing the concurrent-rebuild deadlock

## [0.11.0] — 2026-04-20

### Added
- Serialise user-triggered refreshes with `asyncio.Lock` to prevent double-click concurrent fetches
- Persist `rate_limited_until` and `last_refresh_stats` across HA restart so the 4/day counter is not lost on reboot
- Track structured refresh stats (outcome, accounts, transactions, new, duration_ms, errors) exposed via `manager.get_refresh_status()`
- New `POST /api/finance_dashboard/refresh` endpoint — the single user-triggered live-fetch entry point, returns stats synchronously
- New `GET /api/finance_dashboard/refresh_status` — cache-only polling endpoint, unbounded reads allowed
- `refresh_transactions` service now uses `SupportsResponse.OPTIONAL` and returns stats so automations can react to the outcome
- Refresh_transactions refreshes balances in the same user-triggered round — one click, one cache update
- Refresh button now shows a result toast ("5 Konten, 243 Transaktionen, 2 neu in 3.1s" / rate-limit / partial / error)
- Header timestamp shows live cache age ("Zuletzt 14:23 · vor 2 Std") and updates every minute
- Rate-limit and loading states surfaced clearly next to the refresh button instead of silent "Aktualisieren" reverts

### Changed
- Remove staleness-based auto-refresh — coordinator is now a pure cache projection, live fetches only via dedicated endpoint
- Docs(claude-md): replace stale GoCardless references with Enable Banking, document cache vs. live-fetch contract

### Fixed
- Separate cache-reads from live API fetches — `manager.async_get_balance()` now returns cached balances only (was hitting Enable Banking on every HTTP `/balances` call, burning the 4/day/ASPSP rate limit)
- "Noch keine Daten" state now has explicit styling + hint to click Aktualisieren

## [0.10.1] — 2026-04-19

### Fixed
- Propagate OAuth callback errors through /setup/status so the wizard surfaces them within 2s instead of timing out after 5min
- Hard-fail /setup/authorize when callback URL is HTTP (Enable Banking requires pre-registered HTTPS redirect)
- Trigger one coordinator refresh after deferred entry reload so entities populate immediately after bank link
- Raise Repairs issue on missing or invalid Enable Banking credentials, auto-clear on recovery
- Wizard polling stops on setup_error and shows the message instead of waiting for timeout
- Data provider subscribes to entity_registry_updated events so newly created sensors appear without race-prone 4s timer

## [0.10.0] — 2026-04-12

### Added
- Add inline bank connection wizard as modal overlay (4-step flow: institution search, bank authorization with polling, account assignment, success)
- Add "+ Konto" button in header to open wizard from anywhere

### Changed
- Replace onboarding "Einstellungen" link with inline "Bankkonto verbinden" button

### Fixed
- Replace fragile entity_id prefix matching with HA Entity Registry lookup — entities are now found by platform + unique_id regardless of HA-generated entity_ids
- Add 4s delay before refreshRegistry() after setup complete to wait for HA config entry reload
- Add https scheme validation on auth URLs to prevent XSS via javascript: scheme
- Update institution filter to only re-render list container (prevents cursor jump)

## [0.9.2] — 2026-04-11

### Added
- Add onboarding welcome screen with "Demo starten" CTA when no bank accounts connected
- Show "Noch keine Daten" timestamp fallback when no refresh has occurred
- Make Demo button more prominent with visible background fill

### Changed
- Remove automatic banking API calls on HA startup — coordinator now loads from cache only, no external calls until user clicks "Aktualisieren"
- Remove _first_update force-refresh flag from coordinator — staleness check is sufficient
- Remove automatic API fallback in _rebuild() — /summary endpoint only called on explicit user refresh, not on every entity change

### Fixed
- Handle loading state in _onData to prevent clearing content during demo toggle

## [0.9.1] — 2026-04-07

### Added
- Chore: sync addon payload

### Changed
- Chore: sync translations (en.json, de.json) with new issue description

### Fixed
- Add missing issue-level description to strings.json — Repairs card had no body text, rendering it invisible in some HA versions
- Add is_persistent=True to ir.async_create_issue — prevents HA from discarding the issue during internal operations
- Wrap synchronous file I/O (exists/read_text/unlink) in async_add_executor_job — HA 2024+ blocks or warns on sync I/O in event loop
- Return None for unknown issue_ids instead of generic RepairsFlow()

## [0.9.0] — 2026-04-05

### Added
- Full demo mode with realistic German banking data (3 accounts, ~35 transactions, household split, recurring patterns)
- Toggle via UI button (admin-only), service call, or options flow — persists across HA restarts
- Manual-only API refresh — coordinator update_interval=None, data only updates on explicit user action
- Demo toggle button with DEMO badge, aria-pressed accessibility, mobile breakpoint

### Fixed
- Initial coordinator refresh now works on config entry reloads (not just first HA start)
- Shutdown no longer overwrites real transaction cache when demo mode is active
- AttributeError in DemoToggleView coordinator lookup — null-safe access pattern
- GoCardless reference replaced with Enable Banking in services.yaml
- Removed dead COORDINATOR_UPDATE_INTERVAL constant and corrected all docstrings
- Rapid-click guard and loading state for demo API calls
- DemoMode flag propagated in all data events for consistent UI state

## [0.8.1] — 2026-04-02

### Added
- Chore: add .playwright-mcp/ to .gitignore

## [0.8.0] — 2026-03-28

### Changed
- Decompose monolithic panel into 10 web components (fd-data-provider, fd-header, fd-stats-row, fd-stat-card, fd-household-section, fd-person-card, fd-category-section, fd-donut-chart, fd-cost-distribution, fd-recurring-list)
- Entity-first data strategy — fd-data-provider reads HA sensor/number/select entities, falls back to API for household+recurring
- Panel shell reduced from 507 lines to ~120 lines
- Docs: ARCHITECTURE-FRONTEND.md added with component hierarchy, data flow, entity table, event system

### Fixed
- Coordinator force-refreshes transactions on first cycle — prevents stale cache showing 0,00 EUR
- Account settings API now persists `person` field for household assignment
- Monthly summary sensor exposes fixed_costs, variable_costs, household, recurring attributes

## [0.7.8] — 2026-03-28

### Fixed
- Graceful degradation for household model — exception no longer crashes coordinator
- Graceful degradation for recurring detection — failure yields empty list
- Graceful degradation for budget limit checks — log and skip on error
- Graceful degradation for event firing (balance + transaction) — never blocks data flow

## [0.7.7] — 2026-03-28

### Added
- Integrate HouseholdModel into manager — auto-builds members from account assignments, computes per-person Spielgeld splits
- Activate recurring payment detection on each transaction refresh
- Fire fd_transaction_new, fd_balance_changed, fd_budget_exceeded events
- Budget limit checking against Number entities per category
- Fixed vs variable cost computation in summary API
- Dashboard shows real bank balance from API (not income minus expenses)
- Person cards with Spielgeld, income ratio, shared costs share
- Shared Fixkosten bar with per-person distribution
- Recurring payments section with detected patterns
- German category labels (Wohnen, Mobilität, etc.)
- Responsive layout for mobile viewports

### Fixed
- XSS protection for user-provided names

## [0.7.6] — 2026-03-28


### Added
- Coordinator refreshes transactions only when cache is stale (>6 h), balances every 10 min

## [0.7.5] — 2026-03-27

### Fixed
- Expose config entry to API views (entry key was never set)
- Auto-refresh transactions on HA startup (summary panel showed zeros)

## [0.7.4] — 2026-03-26

### Added
- **Changes:** feat(frontend): status chip replaces refresh button
- New `<finance-status-chip>` Lovelace component with 4 visual states (idle/loading/success/error)
- Register status chip JS as Lovelace extra module

### Changed
- **Branch:** claude/upbeat-davinci
- Panel header uses status chip instead of refresh button + dot indicator

## [0.7.3] — 2026-03-26

### Fixed
- Setup wizard race condition — guard flag prevents wizard re-trigger during entry reload
- Account defaults in step 3 — merge existing settings into pending accounts

## [0.7.2] — 2026-03-26

### Fixed
- `setup/complete` merges new accounts with existing ones instead of replacing entry.data
- Dashboard `_refresh()` uses independent `.catch()` per endpoint instead of `Promise.all`
- Manage accounts dialog retries 3x with 2s delay before showing error

## [0.7.1] — 2026-03-26

### Fixed
- Defer settings overlay render to prevent flash on load
- Correct balance data display in account cards

## [0.7.0] — 2026-03-26

### Added
- Cascading transfer chain detection

## [0.6.15] — 2026-03-26

### Added
- Gesamtsaldo uses actual bank balances from `/balances` API instead of transaction sums
- Settings gear icon in dashboard header for account management
- Manage-accounts overlay with rename, type change, person assignment, connect new bank
- New `update_accounts` endpoint and account details in `setup/status`

## [0.6.14] — 2026-03-26

### Added
- Shimmer skeleton loaders replacing plain loading text
- Async refresh indicator (pulsing dot + timestamp) — old data stays visible
- Responsive breakpoints for tablet (≤900px) and mobile (≤480px)
- Improved empty state with SVG icon and descriptive text

## [0.6.12] — 2026-03-26

### Added
- Step 3 offers HA user multi-select chips (n:m) instead of free-text person field
- Custom display name field per account
- New `GET /api/finance_dashboard/setup/users` endpoint for HA user list
- New fields propagated through manager, sensor attributes, and transaction tagging

## [0.6.9] — 2026-03-26

### Fixed
- RepairsFlow calls `homeassistant.restart` service when user confirms
- Repair notification title says "Restart Required" instead of "Update Available"
- Updated EN and DE translations for restart repair flow

## [0.6.5] — 2026-03-25

### Fixed
- Retry logic and error handling in EnableBanking client for bank list API calls
- Graceful error handling when fetching supported banks fails
- Frontend error state with actionable feedback for bank list loading failures
- Improved error response handling for bank list endpoint

## [0.6.4] — 2026-03-25

### Fixed
- Return dict from `async_get_api_credentials` instead of tuple (callers expected dict-style access; tuple caused TypeError)

## [0.6.3] — 2026-03-25

### Fixed
- Backend returns typed errors (`error_type`) for differentiated frontend handling
- Frontend shows specific German error messages per error type
- Credential errors link to integration settings instead of retry
- 5-minute polling timeout in Step 2, cancel button to return to Step 1

## [0.6.2] — 2026-03-25

### Fixed
- Move restart marker poll outside `is_configured`, check on startup, remove persistent notification fallback

## [0.6.1] — 2026-03-25

### Fixed
- 30s timeout added to Enable Banking API, error state with retry button
- Rename "Finance Dashboard" to "Finance" everywhere

## [0.6.0] — 2026-03-25

### Changed
- **Breaking**: Bank setup moved from config flow to dashboard panel setup wizard
- Config flow reduced to credentials-only (1 step, config VERSION 3)
- Config entry migration v2→v3 preserves existing setups

### Added
- 4-step setup wizard overlay in Finance sidebar panel
- 4 new setup API endpoints (status, institutions, authorize, complete)

### Fixed
- Enable Banking API: `authorization_id` field, nested IBAN, UUID state
- Panel registration: `StaticPathConfig` with cache, correct unregister

## [0.5.5] — 2026-03-25

### Fixed
- Added granular debug logging for Enable Banking HTTP requests and responses (status code, URL, error body on non-OK responses)
- Added debug logging in bank authorization step: callback URL, institution name, full API response, and explicit error when auth URL is missing

## [0.5.2] — 2026-03-25

### Fixed
- Config flow error handling now distinguishes PEM key format errors from API auth failures
- Specific error messages for: invalid key format (PEM parsing), auth rejected (401/403), network errors

### Changed
- README fully updated: all GoCardless references replaced with Enable Banking, version synced, setup instructions rewritten
- CHANGELOG updated with v0.5.0 and v0.5.1 entries

## [0.5.1] — 2026-03-25

### Fixed
- PEM private key field now renders as multiline textarea (was single-line, truncating key)
- Removed deprecated `armhf`, `armv7`, `i386` arch values from companion add-on config
- Updated add-on description from GoCardless to Enable Banking

### Improved
- Step-by-step instructions in Enable Banking setup dialog (EN + DE)
- Config flow shows redirect URL dynamically for easy copy-paste

## [0.5.0] — 2026-03-25

### Changed
- **Breaking**: Migrated from GoCardless to Enable Banking API
  - New credentials format: Application ID + RSA Private Key (PEM) instead of Secret ID/Key
  - JWT-based per-request authentication (RS256) instead of OAuth tokens
  - Config flow version bumped to 2 (automatic reconfigure prompt for existing users)
- API client rewritten for Enable Banking endpoints with GoCardless-compatible normalization

## [0.4.3] — 2026-03-25

### Fixed
- Removed unused `nordigen-python==2.1.0` dependency from `manifest.json` that caused 500 Internal Server Error during config flow (package not installable)

## [0.4.2] — 2026-03-25

### Fixed
- Sidebar panel not appearing in HA (used wrong API: `async_register_built_in_panel` → `panel_custom.async_register_panel`)
- Non-standard `channel` field in `repository.yaml` removed
- Add-on CHANGELOG.md added (required by Supervisor for update display)

## [0.4.1] — 2026-03-24

### Fixed
- Companion add-on not showing updates in HA (missing `exec sleep infinity` — container exited immediately)
- Add-on config missing `stage`, `options`, `schema` fields required by HA Supervisor
- Wrong API permission field (`auth_api` → `homeassistant_api`)
- Brand assets using SVGs instead of PNGs (HA ignores SVGs)
- Missing dark mode icon variants (`dark_icon.png`, `dark_logo.png`)

### Added
- Procedural branding asset generator (`scripts/generate_branding_assets.py`)
- bashio logging integration for structured HA log output

## [0.4.0] — 2026-03-24

### Added
- Benchmark auto-crawl with 7 German national averages (Destatis, Bundesbank, GDV)
- Drag & drop transaction categorizer (admin-only Lovelace card)
- CSV export service with auto-cleanup (1h TTL)
- GitHub Actions release workflow (creates releases on v* tags)

## [0.3.0] — 2026-03-24

### Added
- N-person household budget model (equal, proportional, custom split)
- Recurring transaction detection (monthly pattern analysis)
- Income recognition with salary tolerance ±5 days
- Bonus detection (≥15% above 3-month average → Spielgeld)
- Month cycle logic (calendar vs. salary-based per person)
- Logical month assignment for recurring costs (bank day correction)
- Budget limit Number entities per category
- Split model + remainder mode Select entities
- 4 automation events (transaction_new, balance_changed, budget_exceeded, recurring_detected)
- Budget Config Lovelace card (split dropdown, remainder toggle, Spielgeld preview)
- Complete sidebar panel rewrite (donut chart, top-3 costs, fix vs. variable, shared costs bar)

## [0.2.0] — 2026-03-24

### Added
- GoCardless OAuth flow end-to-end (4-step config: credentials → bank → authorize → assign)
- Account balance sensors with bank logos (1 per account + optional aggregate)
- Monthly summary sensor with category breakdown
- Transaction fetching + caching in encrypted .storage/ (90-day lookback)
- Privacy-first API (admin-only transaction details, IBAN masking)
- OAuth callback endpoint with user-friendly HTML response
- Full EN/DE translations for all config flow steps

## [0.1.0] — 2026-03-24
