/**
 * fd-review — the Abgleich (G1-G7): a re-openable review that makes owners, categories
 * and links consistent, ending in one verified report. Admin-only, cache-only.
 *
 * Steps (one stepper): Konten -> Verknüpfungen -> Fixkosten & Verträge -> Haushalt oder
 * Person -> Kategorien -> Abschluss-Check. Each step shows what Finance recognised
 * ("N Gruppen, M automatisch (>= 85 %)"), groups sorted by euro impact, confirm/change in one
 * tap, bookings on expand (with <fd-owner-chip>), "KI fragen" for the still-unclear groups.
 *
 *   POST finance_dashboard/review/start               on entry (before-snapshot, idempotent)
 *   GET  finance_dashboard/review[?since=last]        {steps[], start_step, reviewed_at, ...}
 *   POST finance_dashboard/review/confirm             {group_id, kind, owner?, category?, confirmed?, suspended?}
 *   POST finance_dashboard/review/ai                  {group_ids} -> {asked, categorized, tendencies, skipped_budget, reason, groups}
 *   GET  finance_dashboard/review/report              hh_year, hh_cycle, p_year, p_cycle, settle, diff
 *   POST finance_dashboard/review/complete            -> {reviewed_at}
 *
 * Properties: hass (required), demo (boolean, appends ?demo=1).
 * Events: fd-navigate {target:"settings", section:"ai"} (AI consent), fd-navigate {target:"back"},
 *         fd-toast {message, type}.
 */

const DOMAIN = "finance_dashboard";
const STEPS = ["acc", "links", "fixed", "owner", "cat", "check"];
const AI_STEPS = new Set(["fixed", "owner", "cat"]);
const SHARED = "__shared__";
const TABS = ["hh_year", "hh_cycle", "p_year", "p_cycle", "settle", "diff"];

const FB = {
  de: {
    "review.title": "Abgleich",
    "review.loading": "Lade Abgleich…",
    "review.error": "Der Abgleich konnte nicht geladen werden.",
    "review.retry": "Erneut versuchen",
    "review.denied": "Der Abgleich ist nur für Administratoren sichtbar.",
    "review.stepper": "Schritte des Abgleichs",
    "review.step_of": "Schritt $n von $total",
    "review.step.acc": "Konten",
    "review.step.links": "Verknüpfungen",
    "review.step.fixed": "Fixkosten & Verträge",
    "review.step.owner": "Haushalt oder Person",
    "review.step.cat": "Kategorien",
    "review.step.check": "Abschluss-Check",
    "review.hint.acc": "Wem gehört welches Konto? Ein Konto gehört einer Person, einer Person und dem Haushalt oder nur dem Haushalt.",
    "review.hint.links": "Umbuchungen zwischen eigenen Konten, PayPal und Erstattungen: bestätigen, was zusammengehört, damit nichts doppelt zählt.",
    "review.hint.fixed": "Wiederkehrende Posten gegen den Haushaltsplan: stimmen Zuordnung und Plan-Position?",
    "review.hint.owner": "Gehört die Ausgabe dem Haushalt oder einer Person? Alles, was nicht Haushalt ist, gehört der Person.",
    "review.hint.cat": "Die Kategorien der größten offenen Posten.",
    "review.recognized": "von Finance erkannt: $n Gruppen, $m automatisch (≥ 85 %)",
    "review.recognized_one": "von Finance erkannt: 1 Gruppe, $m automatisch (≥ 85 %)",
    "review.open_n": "$n offen · $amount",
    "review.open_none": "Nichts mehr offen",
    "review.open": "Offen",
    "review.auto": "Automatisch erkannt ($n)",
    "review.empty": "In diesem Schritt gibt es nichts zu prüfen.",
    "review.skip": "Schritt überspringen",
    "review.next": "Weiter",
    "review.prev": "Zurück",
    "review.bookings": "$n Buchungen",
    "review.bookings_one": "1 Buchung",
    "review.no_booking": "ohne Buchung",
    "review.bookings_more": "Zeigt die neuesten $n Buchungen.",
    "review.confirm": "Bestätigen",
    "review.confirm_as": "Bestätigen: $what",
    "review.change": "Ändern",
    "review.confirm_all": "Alle $n bestätigen",
    "review.confirmed": "Bestätigt",
    "review.saving": "Speichert…",
    "review.saved": "Gespeichert",
    "review.save_error": "Das konnte nicht gespeichert werden.",
    "review.pick_owner": "Wem gehört das?",
    "review.pick_cat": "Welche Kategorie?",
    "review.owner.shared": "Haushalt",
    "review.owner.open": "Offen",
    "review.transfer_yes": "Ja, Umbuchung",
    "review.transfer_no": "Nein, zählt normal",
    "review.transfer_is": "Als Umbuchung bestätigt",
    "review.transfer_isnt": "Als normale Buchung bestätigt",
    "review.suspend": "Ausgesetzt",
    "review.unsuspend": "Wieder aktiv",
    "review.suspended": "Ausgesetzt",
    "review.plan_pos": "Plan: $name",
    "review.conf": "$pct % sicher",
    "review.reason.confirmed": "Von dir bestätigt",
    "review.reason.correction": "Deine Korrektur",
    "review.reason.merchant_rule": "Regel für diesen Händler",
    "review.reason.plan": "Vermutung: passt zu einer Plan-Position",
    "review.reason.series": "Vermutung: wiederkehrende Serie",
    "review.reason.category": "Vermutung: Kategorie $cat",
    "review.reason.ai": "KI-Vorschlag",
    "review.reason.account": "Vermutung: Standard des Kontos",
    "review.reason.other": "Vermutung",
    "review.suggest_cat": "Vorschlag: $cat",
    "review.ai": "KI fragen",
    "review.ai_sub": "Die KI schlägt für die $n unklaren Gruppen Haushalt/Person und Kategorie vor.",
    "review.ai_busy": "KI prüft…",
    "review.ai_done": "KI hat $n Gruppen bewertet. Die Vorschläge sind Vermutungen, du bestätigst sie.",
    "review.ai_done_one": "KI hat 1 Gruppe bewertet. Die Vorschläge sind Vermutungen, du bestätigst sie.",
    "review.ai_budget": "$n Gruppen blieben wegen des Monatsbudgets offen.",
    "review.ai_budget_one": "1 Gruppe blieb wegen des Monatsbudgets offen.",
    "review.ai_nothing": "Die KI hatte keinen Vorschlag.",
    "review.ai_none_open": "Keine unklaren Gruppen für die KI.",
    "review.ai_no_consent": "Die KI darf noch nicht fragen: Für Kategorien fehlt deine Zustimmung.",
    "review.ai_provider_unusable": "Der KI-Anbieter ist nicht nutzbar (Schlüssel oder Verbindung prüfen).",
    "review.ai_unavailable": "Die KI ist gerade nicht erreichbar.",
    "review.ai_settings": "KI-Einstellungen öffnen",
    "review.check_title": "Stimmt alles zusammen?",
    "review.check_ok": "Alle fünf Kriterien erfüllt",
    "review.check_open": "Noch nicht alles erfüllt",
    "review.crit_ok": "erfüllt",
    "review.crit_fail": "offen",
    "review.crit.accounts": "Jedes Konto hat seine Besitzer",
    "review.crit.accounts_fail": "Ohne Besitzer: $names",
    "review.crit.open_ownership": "Keine offene Zuordnung über $limit",
    "review.crit.open_ownership_fail": "Offen sind $amount (Grenze $limit)",
    "review.crit.transfers": "Umbuchungen zählen nirgends als Ausgabe",
    "review.crit.transfers_fail": "$n Umbuchungen zählen noch als Ausgabe",
    "review.crit.reconcile": "Haushalt + Personen = Ausgaben aller Konten, auf den Cent",
    "review.crit.reconcile_fail": "Abweichung $diff",
    "review.crit.plan": "Jede Plan-Position hat eine Buchung oder ist ausgesetzt",
    "review.crit.plan_fail": "Ohne Buchung: $names",
    "review.jump": "Zu den Gruppen",
    "review.complete": "Abschließen",
    "review.complete_hint": "Du kannst jederzeit erneut abgleichen. Offene Punkte bleiben sichtbar.",
    "review.completed": "Abgleich abgeschlossen. Stand geprüft am $date.",
    "review.close": "Zurück zum Jahr",
    "review.report": "Ergebnis",
    "review.tab.hh_year": "Haushalt · Jahr",
    "review.tab.hh_cycle": "Haushalt · Zyklus",
    "review.tab.p_year": "Person · Jahr",
    "review.tab.p_cycle": "Person · Zyklus",
    "review.tab.settle": "Ausgleich",
    "review.tab.diff": "Vorher / Nachher",
    "review.rep.income": "Einnahmen",
    "review.rep.expenses": "Ausgaben",
    "review.rep.saved": "Gespart",
    "review.rep.rate": "Sparquote",
    "review.rep.fixed": "Fix",
    "review.rep.variable": "Variabel",
    "review.rep.shared": "Davon Haushalt",
    "review.rep.persons": "Personen",
    "review.rep.open": "Ohne Zuordnung",
    "review.rep.cats": "Größte Kategorien",
    "review.rep.positions": "Plan gegen Ist",
    "review.rep.planned": "Plan",
    "review.rep.actual": "Ist",
    "review.rep.no_booking": "keine Buchung",
    "review.rep.restricted": "Nur Summen, die Details sieht die Person selbst.",
    "review.rep.cycle": "Zyklus $start – $end",
    "review.rep.empty": "Dazu gibt es noch keine Zahlen.",
    "review.settle.cycle": "Dieser Zyklus",
    "review.settle.year": "Dieses Jahr",
    "review.settle.owes": "$name schuldet dem Haushalt $amount",
    "review.settle.owed": "Der Haushalt schuldet $name $amount",
    "review.settle.even": "$name: ausgeglichen",
    "review.settle.none": "Kein Ausgleich nötig.",
    "review.diff.none": "Der Vorher-Stand wird festgehalten, sobald der Abgleich gestartet ist.",
    "review.diff.owners": "Ausgaben nach Besitzer (Jahr)",
    "review.diff.open_groups": "Offene Gruppen",
    "review.diff.open_amount": "Offener Betrag",
    "review.diff.settle": "Ausgleich",
    "review.diff.before": "Vorher",
    "review.diff.after": "Nachher",
    "review.diff.delta": "Änderung",
    "review.bk_none": "Keine Buchungen"
  },
  en: {
    "review.title": "Reconciliation",
    "review.loading": "Loading reconciliation…",
    "review.error": "The reconciliation could not be loaded.",
    "review.retry": "Try again",
    "review.denied": "The reconciliation is only visible to administrators.",
    "review.stepper": "Reconciliation steps",
    "review.step_of": "Step $n of $total",
    "review.step.acc": "Accounts",
    "review.step.links": "Links",
    "review.step.fixed": "Fixed costs & contracts",
    "review.step.owner": "Household or person",
    "review.step.cat": "Categories",
    "review.step.check": "Final check",
    "review.hint.acc": "Whose account is it? An account belongs to one person, to a person and the household, or to the household only.",
    "review.hint.links": "Transfers between your own accounts, PayPal and refunds: confirm what belongs together so nothing counts twice.",
    "review.hint.fixed": "Recurring items against the household plan: do owner and plan position fit?",
    "review.hint.owner": "Does the expense belong to the household or to a person? Anything that is not household belongs to the person.",
    "review.hint.cat": "The categories of the biggest open items.",
    "review.recognized": "recognised by Finance: $n groups, $m automatic (≥ 85 %)",
    "review.recognized_one": "recognised by Finance: 1 group, $m automatic (≥ 85 %)",
    "review.open_n": "$n open · $amount",
    "review.open_none": "Nothing left open",
    "review.open": "Open",
    "review.auto": "Recognised automatically ($n)",
    "review.empty": "There is nothing to check in this step.",
    "review.skip": "Skip step",
    "review.next": "Next",
    "review.prev": "Back",
    "review.bookings": "$n bookings",
    "review.bookings_one": "1 booking",
    "review.no_booking": "no booking",
    "review.bookings_more": "Showing the newest $n bookings.",
    "review.confirm": "Confirm",
    "review.confirm_as": "Confirm: $what",
    "review.change": "Change",
    "review.confirm_all": "Confirm all $n",
    "review.confirmed": "Confirmed",
    "review.saving": "Saving…",
    "review.saved": "Saved",
    "review.save_error": "Could not save that.",
    "review.pick_owner": "Whose is this?",
    "review.pick_cat": "Which category?",
    "review.owner.shared": "Household",
    "review.owner.open": "Open",
    "review.transfer_yes": "Yes, a transfer",
    "review.transfer_no": "No, counts normally",
    "review.transfer_is": "Confirmed as a transfer",
    "review.transfer_isnt": "Confirmed as a normal booking",
    "review.suspend": "Suspended",
    "review.unsuspend": "Active again",
    "review.suspended": "Suspended",
    "review.plan_pos": "Plan: $name",
    "review.conf": "$pct % sure",
    "review.reason.confirmed": "Confirmed by you",
    "review.reason.correction": "Your correction",
    "review.reason.merchant_rule": "Rule for this merchant",
    "review.reason.plan": "Guess: matches a plan position",
    "review.reason.series": "Guess: recurring series",
    "review.reason.category": "Guess: category $cat",
    "review.reason.ai": "AI suggestion",
    "review.reason.account": "Guess: account default",
    "review.reason.other": "Guess",
    "review.suggest_cat": "Suggestion: $cat",
    "review.ai": "Ask AI",
    "review.ai_sub": "The AI suggests household/person and category for the $n unclear groups.",
    "review.ai_busy": "AI is checking…",
    "review.ai_done": "The AI rated $n groups. Its suggestions are guesses, you confirm them.",
    "review.ai_done_one": "The AI rated 1 group. Its suggestions are guesses, you confirm them.",
    "review.ai_budget": "$n groups stayed open because of the monthly budget.",
    "review.ai_budget_one": "1 group stayed open because of the monthly budget.",
    "review.ai_nothing": "The AI had no suggestion.",
    "review.ai_none_open": "No unclear groups for the AI.",
    "review.ai_no_consent": "The AI may not ask yet: your consent for categories is missing.",
    "review.ai_provider_unusable": "The AI provider is not usable (check key or connection).",
    "review.ai_unavailable": "The AI is not reachable right now.",
    "review.ai_settings": "Open AI settings",
    "review.check_title": "Does everything add up?",
    "review.check_ok": "All five criteria met",
    "review.check_open": "Not everything is met yet",
    "review.crit_ok": "met",
    "review.crit_fail": "open",
    "review.crit.accounts": "Every account has its owners",
    "review.crit.accounts_fail": "Without owner: $names",
    "review.crit.open_ownership": "No open assignment above $limit",
    "review.crit.open_ownership_fail": "$amount is open (limit $limit)",
    "review.crit.transfers": "Transfers count nowhere as spending",
    "review.crit.transfers_fail": "$n transfers still count as spending",
    "review.crit.reconcile": "Household + persons = expenses of all accounts, to the cent",
    "review.crit.reconcile_fail": "Difference $diff",
    "review.crit.plan": "Every plan position has a booking or is suspended",
    "review.crit.plan_fail": "Without booking: $names",
    "review.jump": "Go to the groups",
    "review.complete": "Finish",
    "review.complete_hint": "You can reconcile again at any time. Open points stay visible.",
    "review.completed": "Reconciliation finished. Checked on $date.",
    "review.close": "Back to the year",
    "review.report": "Result",
    "review.tab.hh_year": "Household · year",
    "review.tab.hh_cycle": "Household · cycle",
    "review.tab.p_year": "Person · year",
    "review.tab.p_cycle": "Person · cycle",
    "review.tab.settle": "Settlement",
    "review.tab.diff": "Before / after",
    "review.rep.income": "Income",
    "review.rep.expenses": "Expenses",
    "review.rep.saved": "Saved",
    "review.rep.rate": "Savings rate",
    "review.rep.fixed": "Fixed",
    "review.rep.variable": "Variable",
    "review.rep.shared": "Of which household",
    "review.rep.persons": "Persons",
    "review.rep.open": "Unassigned",
    "review.rep.cats": "Biggest categories",
    "review.rep.positions": "Plan vs. actual",
    "review.rep.planned": "Plan",
    "review.rep.actual": "Actual",
    "review.rep.no_booking": "no booking",
    "review.rep.restricted": "Totals only; the person sees the details.",
    "review.rep.cycle": "Cycle $start – $end",
    "review.rep.empty": "There are no figures for this yet.",
    "review.settle.cycle": "This cycle",
    "review.settle.year": "This year",
    "review.settle.owes": "$name owes the household $amount",
    "review.settle.owed": "The household owes $name $amount",
    "review.settle.even": "$name: settled",
    "review.settle.none": "No settlement needed.",
    "review.diff.none": "The before state is recorded once the reconciliation has started.",
    "review.diff.owners": "Expenses by owner (year)",
    "review.diff.open_groups": "Open groups",
    "review.diff.open_amount": "Open amount",
    "review.diff.settle": "Settlement",
    "review.diff.before": "Before",
    "review.diff.after": "After",
    "review.diff.delta": "Change",
    "review.bk_none": "No bookings"
  }
};

function tr(key, vars = {}) {
  let s = window._fd.tSync(key, vars);
  if (s !== key) return s;
  const raw = ((window._fd._hass && window._fd._hass.language) || navigator.language || "en").toLowerCase();
  s = (FB[raw.startsWith("de") ? "de" : "en"][key]) || key;
  for (const [k, v] of Object.entries(vars)) s = s.replace(new RegExp(`\\$${k}`, "g"), String(v));
  return s;
}

const CSS = `
:host { display: block; }
.root { container: rv / inline-size; overflow-wrap: anywhere; color: var(--fd-t1); font-size: 13px; line-height: 1.4; }
button { font: inherit; color: inherit; cursor: pointer; }
button:focus-visible, a:focus-visible, summary:focus-visible { outline: 2px solid var(--fd-a500); outline-offset: 2px; }
h2 { margin: 0; font-size: 18px; font-weight: 500; }
h3 { margin: 0 0 4px; font-size: 15px; font-weight: 500; }
h4 { margin: 12px 0 4px; font-size: 12px; font-weight: 500; letter-spacing: .04em; text-transform: uppercase; color: var(--fd-t2); }
.card { margin: 0 0 12px; padding: 12px 14px; border-radius: var(--fd-r-card); background: var(--fd-card); box-shadow: var(--fd-sh1); }
.muted { color: var(--fd-t2); font-size: 11.5px; }
.msg { padding: 28px 12px; text-align: center; color: var(--fd-t2); }
.b { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: var(--fd-touch); padding: 0 16px; border: 1px solid var(--fd-line); border-radius: var(--fd-r-pill); background: transparent; font-weight: 500; }
.b:hover { border-color: var(--fd-a500); }
.b.pri { background: var(--fd-a700); border-color: var(--fd-a700); color: #fff; }
.b.pri:hover { filter: brightness(1.08); }
.b[disabled] { opacity: .55; cursor: default; }
.b.sm { min-height: 36px; padding: 0 12px; font-size: 12.5px; }
@media (pointer: coarse) { .b.sm { min-height: var(--fd-touch); } }

/* stepper */
.stepper { list-style: none; margin: 0 0 12px; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; }
.stepper li { display: contents; }
.stp { display: inline-flex; align-items: center; gap: 6px; min-height: 36px; padding: 0 12px 0 6px; border: 1px solid var(--fd-line); border-radius: var(--fd-r-pill); background: var(--fd-card); font-size: 12.5px; }
.stp .n { display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; border-radius: 50%; background: var(--fd-sunk); font-size: 11.5px; font-weight: 600; }
.stp.cur { border-color: var(--fd-a500); background: var(--fd-a50); color: var(--fd-a900); font-weight: 500; }
.stp.cur .n { background: var(--fd-a700); color: #fff; }
.stp.done .n { background: var(--fd-ok-bg); color: color-mix(in srgb, var(--fd-ok) 72%, var(--fd-t1)); }
.stp .k { min-width: 18px; padding: 0 5px; border-radius: var(--fd-r-pill); background: var(--fd-near-bg); color: color-mix(in srgb, var(--fd-near) 72%, var(--fd-t1)); font-size: 11px; font-weight: 600; text-align: center; }
@media (max-width: 599px) { .stp .t { display: none; } .stp.cur .t { display: inline; } .stp { padding-right: 8px; } .stp.cur { padding-right: 12px; } }
.progress { margin: 0 0 4px; color: var(--fd-t2); font-size: 11.5px; }

/* step header */
.sh { background: linear-gradient(135deg, var(--fd-a50), var(--fd-card) 70%); border-left: 4px solid var(--fd-a500); }
.sh .rec { margin-top: 6px; font-weight: 500; color: var(--fd-a900); }
.sh .st { margin-top: 2px; color: var(--fd-t2); }
.ai { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; margin-top: 10px; padding: 10px 12px; border-radius: 12px; background: var(--fd-card); border: 1px solid var(--fd-a300); }
.ai .tx { flex: 1 1 220px; min-width: 0; font-size: 12px; color: var(--fd-t2); }
.ai .b { flex: none; }
.aimsg { margin-top: 8px; padding: 8px 10px; border-radius: 8px; background: var(--fd-sunk); font-size: 12px; }
.aimsg.warn { background: var(--fd-near-bg); }
.aimsg .b { margin-top: 6px; }

/* groups */
.grps { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.grp { padding: 10px 12px; border: 1px solid var(--fd-line); border-radius: 12px; background: var(--fd-card); }
.grp.done { background: var(--fd-ok-bg); border-color: transparent; }
.grp.hl { border-color: var(--fd-near); box-shadow: 0 0 0 2px var(--fd-near-bg); }
.gh { all: unset; box-sizing: border-box; display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 2px 10px; width: 100%; cursor: pointer; border-radius: 8px; }
.gh:focus-visible { outline: 2px solid var(--fd-a500); outline-offset: 2px; }
.gh .nm { font-weight: 500; font-size: 14px; min-width: 0; }
.gh .am { font-weight: 600; white-space: nowrap; font-variant-numeric: tabular-nums; }
.gh .chev { color: var(--fd-t3); margin-left: 6px; display: inline-block; transition: transform .15s; }
.gh[aria-expanded="true"] .chev { transform: rotate(90deg); }
.meta { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 6px; margin-top: 4px; }
.pill { display: inline-flex; align-items: center; gap: 5px; min-height: 22px; padding: 0 8px; border-radius: var(--fd-r-pill); font-size: 11.5px; font-weight: 500; background: var(--fd-sunk); color: var(--fd-t2); }
.pill .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--c, var(--fd-t3)); }
.pill.own { color: var(--fd-t1); }
.pill.conf { background: var(--fd-near-bg); color: color-mix(in srgb, var(--fd-near) 72%, var(--fd-t1)); }
.pill.conf.hi { background: var(--fd-ok-bg); color: color-mix(in srgb, var(--fd-ok) 72%, var(--fd-t1)); }
.pill.ai { display: inline-flex; margin: 0; padding: 0 8px; border: 0; background: var(--fd-a100); color: var(--fd-a900); }
.act { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.pick { margin-top: 8px; padding: 10px; border-radius: 10px; background: var(--fd-sunk); }
.pick .q { font-size: 12px; font-weight: 500; margin-bottom: 6px; }
.opts { display: flex; flex-wrap: wrap; gap: 6px; }
.opts .b { min-height: 40px; }
.bk { margin-top: 8px; border-top: 1px solid var(--fd-line); }
.bk[hidden], .pick[hidden] { display: none; }
.bk ul { list-style: none; margin: 0; padding: 0; }
.bk li { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 4px 10px; padding: 6px 0; border-bottom: 1px solid var(--fd-line); font-size: 12.5px; }
.bk li:last-child { border-bottom: 0; }
.bk .d { color: var(--fd-t2); font-size: 11.5px; white-space: nowrap; }
.bk .l { min-width: 0; }
.bk .a { font-weight: 500; white-space: nowrap; font-variant-numeric: tabular-nums; }
.bk .c { grid-column: 2 / -1; }
details.autos > summary { cursor: pointer; min-height: var(--fd-touch); display: flex; align-items: center; font-weight: 500; font-size: 13px; color: var(--fd-t2); }
.nav { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; margin: 12px 0 24px; }

/* check */
.crit { list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 6px; }
.crit li { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: start; gap: 4px 10px; padding: 8px 10px; border-radius: 10px; background: var(--fd-sunk); }
.crit .ic { width: 22px; height: 22px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px; }
.crit .ok .ic, .crit li.ok .ic { background: var(--fd-ok); color: #fff; }
.crit li.bad .ic { background: var(--fd-near); color: #fff; }
.crit .w { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--fd-t2); }
.crit li.ok .w { color: color-mix(in srgb, var(--fd-ok) 72%, var(--fd-t1)); }
.crit li.bad .w { color: color-mix(in srgb, var(--fd-near) 72%, var(--fd-t1)); }
.crit .why { font-size: 12px; color: var(--fd-t2); }
.tabs { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 12px; }
.tabs .b { min-height: 36px; font-size: 12.5px; padding: 0 12px; }
.tabs .b[aria-pressed="true"] { background: var(--fd-a50); border-color: var(--fd-a500); color: var(--fd-a900); }
.figs { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px; margin: 6px 0; }
.fig { padding: 8px 10px; border-radius: 10px; background: var(--fd-sunk); }
.fig .v { font-size: 16px; font-weight: 600; font-variant-numeric: tabular-nums; }
.fig .k { font-size: 11px; color: var(--fd-t2); }
.tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.tbl th { text-align: left; font-weight: 500; color: var(--fd-t2); font-size: 11px; padding: 4px 6px; }
.tbl td { padding: 6px; border-top: 1px solid var(--fd-line); }
.tbl .r, .tbl th.r { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.sc { overflow-x: auto; }
.pos { color: color-mix(in srgb, var(--fd-near) 72%, var(--fd-t1)); }
.neg { color: color-mix(in srgb, var(--fd-ok) 72%, var(--fd-t1)); }
.done-card { border-left: 4px solid var(--fd-ok); }
@container rv (min-width: 760px) { .stp .t { display: inline !important; } .grps { grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: start; } }
@media (prefers-reduced-motion: reduce) { .gh .chev { transition: none; } }
`;

class FdReview extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._demo = false;
    this._state = "loading"; // loading | ok | denied | error
    this._data = null;
    this._report = null;
    this._i = 0;
    this._open = new Set();     // expanded group ids
    this._hl = new Set();       // highlighted group ids (jump from the check)
    this._pick = null;          // group id with the picker open
    this._busy = new Set();     // group ids being saved
    this._ai = null;            // {kind, text, consent}
    this._aiBusy = false;
    this._tab = "hh_year";
    this._done = null;          // reviewed_at after "Abschließen"
    this._persons = [];
    this._started = false;
  }

  get hass() { return this._hass; }
  set hass(h) {
    const first = !this._hass;
    this._hass = h;
    if (first) this.load();
  }

  get demo() { return this._demo; }
  set demo(v) { this._demo = !!v; }

  reload() { return this.load(); }

  _q(path, extra = "") {
    const demo = this._demo || /[?&]demo=1\b/.test(location.search);
    const params = [extra, demo ? "demo=1" : ""].filter(Boolean).join("&");
    return `${DOMAIN}/${path}${params ? "?" + params : ""}`;
  }

  async load() {
    if (!this._hass) return;
    await window._fd.t("review.title");
    this._state = "loading";
    this._render();
    try {
      try {
        const a = await this._hass.callApi("GET", `${DOMAIN}/assignments`);
        this._persons = (a.persons || []).map((p) => ({ name: p.name, display_name: p.display_name }));
      } catch (_) { this._persons = []; }
      await this._hass.callApi("POST", this._q("review/start"), {});
      let res = await this._hass.callApi("GET", this._q("review"));
      if (res && res.reviewed_at) res = await this._hass.callApi("GET", this._q("review", "since=last"));
      this._data = res;
      const s = res.start_step;
      const idx = typeof s === "number" ? s : STEPS.indexOf(s);
      this._i = Math.min(STEPS.length - 1, Math.max(0, idx));
      this._state = "ok";
      this._done = null;
      this._ai = null;
    } catch (e) {
      console.warn("fd-review: load failed:", e);
      this._state = e && (e.status_code === 403 || e.status === 403) ? "denied" : "error";
    }
    this._render();
    if (this._state === "ok" && STEPS[this._i] === "check") this._loadReport();
  }

  /** Re-read the groups after a booking-level correction, keeping position and expanded groups. */
  async _refresh() {
    try {
      const res = await this._hass.callApi("GET", this._q("review"));
      this._data = res;
      this._render();
    } catch (e) { console.warn("fd-review: refresh failed:", e); }
  }

  async _loadReport() {
    try {
      this._report = await this._hass.callApi("GET", this._q("review/report"));
    } catch (e) {
      console.warn("fd-review: report failed:", e);
      this._report = { error: true };
    }
    this._render();
  }

  // ---- helpers ---------------------------------------------------------------
  _lang() { return (this._hass && this._hass.language) || navigator.language || "de"; }
  _eur(v) { return window._fd.eur(v); }
  _stepData(id) { return ((this._data && this._data.steps) || []).find((s) => s.id === id) || { id, groups: [], open_count: 0, auto_count: 0, open_amount: 0 }; }
  _catLabel(c) { return (window._fd.CAT_LABELS && window._fd.CAT_LABELS[c]) || c || ""; }
  _personName(n) {
    const p = this._persons.find((x) => x.name === n);
    return (p && (p.display_name || p.name)) || n;
  }
  _ownerLabel(o) {
    if (o === SHARED || o === "shared") return tr("review.owner.shared");
    if (!o || o === "open") return tr("review.owner.open");
    return this._personName(o);
  }
  _ownerColor(o) {
    if (o === SHARED || o === "shared") return "var(--fd-household)";
    if (!o || o === "open") return "var(--fd-t3)";
    const i = this._persons.findIndex((p) => p.name === o);
    return i === 1 ? "var(--fd-person-b)" : "var(--fd-person-a)";
  }
  _fmtDate(iso) { try { return window._fd.fmtDate(iso, true); } catch (_) { return iso || ""; } }
  _openGroups(step) { return (step.groups || []).filter((g) => !g.auto && !g.confirmed); }

  /** Counts that follow local confirmations: groups open when loaded and confirmed since. */
  _counts(step) {
    const gs = step.groups || [];
    const done = gs.filter((g) => !g.auto && g.confirmed);
    const open = Math.max(0, (step.open_count || 0) - done.length);
    const amount = Math.max(0, (step.open_amount || 0) - done.reduce((s, g) => s + Math.abs(g.amount || 0), 0));
    return { open, amount: Math.round(amount * 100) / 100, total: (step.open_count || 0) + (step.auto_count || 0), auto: step.auto_count || 0 };
  }

  _reason(g) {
    const src = g.reason || g.source || "other";
    if (g.confirmed) return tr("review.reason.confirmed");
    if (src === "category") return tr("review.reason.category", { cat: this._catLabel(g.reason_category || g.category) });
    const k = `review.reason.${src}`;
    const t = tr(k);
    return t === k ? tr("review.reason.other") : t;
  }

  // ---- render ----------------------------------------------------------------
  _render() {
    const e = window._fd.escHtml;
    let body;
    if (this._state === "loading") body = `<div class="msg" role="status">${e(tr("review.loading"))}</div>`;
    else if (this._state === "denied") body = `<div class="msg">${e(tr("review.denied"))}</div>`;
    else if (this._state === "error") body = `<div class="msg">${e(tr("review.error"))}<br><br><button type="button" class="b pri" id="retry">${e(tr("review.retry"))}</button></div>`;
    else body = this._body();
    const head = this.hasAttribute("embedded") ? "" : `<fd-subpage-header title="${e(tr("review.title"))}"></fd-subpage-header>`;
    // keep the scroll position through re-renders (a confirm must not jump the page)
    const y = window.scrollY;
    this.shadowRoot.innerHTML = `<style>${window._fd.SHARED_CSS}${CSS}</style><div class="root">${head}${body}</div>`;
    this._wire();
    if (y) window.scrollTo?.({ top: y });
    this.shadowRoot.querySelectorAll(".bk:not([hidden])").forEach((b) => this._mountChips(b));
  }

  _body() {
    const e = window._fd.escHtml;
    const id = STEPS[this._i];
    const openCount = (sid) => this._counts(this._stepData(sid)).open;
    const stepper = `<ol class="stepper" aria-label="${e(tr("review.stepper"))}">${STEPS.map((sid, k) => {
      const cur = k === this._i;
      const c = sid === "check" ? 0 : openCount(sid);
      const done = sid !== "check" && c === 0 && k !== this._i;
      return `<li><button type="button" class="stp${cur ? " cur" : ""}${done ? " done" : ""}" data-step="${k}" ${cur ? 'aria-current="step"' : ""}>
        <span class="n" aria-hidden="true">${done ? "✓" : k + 1}</span><span class="t">${e(tr("review.step." + sid))}</span>${c ? `<span class="k" aria-label="${e(tr("review.open_n", { n: c, amount: this._eur(this._counts(this._stepData(sid)).amount) }))}">${c}</span>` : ""}</button></li>`;
    }).join("")}</ol>`;
    const progress = `<div class="progress">${e(tr("review.step_of", { n: this._i + 1, total: STEPS.length }))}</div>`;
    const main = id === "check" ? this._checkStep() : this._groupStep(id);
    return `${progress}${stepper}${main}`;
  }

  _groupStep(id) {
    const e = window._fd.escHtml;
    const step = this._stepData(id);
    const c = this._counts(step);
    const gs = [...(step.groups || [])].sort((a, b) => Math.abs(b.amount || 0) - Math.abs(a.amount || 0));
    const open = gs.filter((g) => !g.auto);
    const autos = gs.filter((g) => g.auto);
    const rec = c.total === 1 ? tr("review.recognized_one", { m: c.auto }) : tr("review.recognized", { n: c.total, m: c.auto });
    const status = c.open ? tr("review.open_n", { n: c.open, amount: this._eur(c.amount) }) : tr("review.open_none");
    const unclear = this._openGroups(step);
    const aiBox = AI_STEPS.has(id) ? this._aiBox(id, unclear.length) : "";
    const bulk = unclear.length > 1 && id !== "links" && unclear.every((g) => this._hasValue(id, g))
      ? `<button type="button" class="b sm" data-all="${id}">${e(tr("review.confirm_all", { n: unclear.length }))}</button>` : "";
    const list = open.length ? `<ul class="grps">${open.map((g) => this._group(id, g)).join("")}</ul>` : `<p class="muted">${e(tr("review.empty"))}</p>`;
    const autoList = autos.length ? `<details class="autos"><summary>${e(tr("review.auto", { n: c.auto }))}</summary><ul class="grps">${autos.map((g) => this._group(id, g)).join("")}</ul></details>` : "";
    const last = this._i === STEPS.length - 1;
    return `<section class="card sh"><h2>${e(tr("review.step." + id))}</h2><p class="muted" style="margin:4px 0 0">${e(tr("review.hint." + id))}</p>
      <div class="rec">${e(rec)}</div><div class="st">${e(status)}</div>${aiBox}</section>
      ${bulk ? `<div class="act" style="margin:0 0 8px">${bulk}</div>` : ""}${list}${autoList}
      <div class="nav"><button type="button" class="b" data-go="-1" ${this._i === 0 ? "disabled" : ""}>${e(tr("review.prev"))}</button>
      <button type="button" class="b${c.open ? "" : " pri"}" data-go="1">${e(tr(c.open ? "review.next" : (open.length || autos.length ? "review.next" : "review.skip")))}${last ? "" : " ›"}</button></div>`;
  }

  _aiBox(id, n) {
    const e = window._fd.escHtml;
    let msg = "";
    if (this._ai && this._ai.step === id) {
      msg = `<div class="aimsg${this._ai.warn ? " warn" : ""}" role="status">${e(this._ai.text)}${this._ai.consent
        ? `<br><button type="button" class="b sm" data-ai-settings>${e(tr("review.ai_settings"))}</button>` : ""}</div>`;
    }
    return `<div class="ai"><div class="tx">${e(n ? tr("review.ai_sub", { n }) : tr("review.ai_none_open"))}</div>
      <button type="button" class="b pri" data-ai="${id}" ${n && !this._aiBusy ? "" : "disabled"} ${this._aiBusy ? 'aria-busy="true"' : ""}>${this._aiBusy ? e(tr("review.ai_busy")) : "✦ " + e(tr("review.ai"))}</button></div>${msg}`;
  }

  /** Whether the group already carries a value to confirm in one tap. */
  _hasValue(id, g) {
    if (id === "cat") return !!(g.suggested_category || g.category);
    if (id === "links") return false;
    return !!g.owner && g.owner !== "open";
  }

  _group(id, g) {
    const e = window._fd.escHtml;
    const gid = e(g.group_id);
    const expanded = this._open.has(g.group_id);
    const busy = this._busy.has(g.group_id);
    const conf = Number.isFinite(g.confidence) ? Math.round(g.confidence) : null;
    const isOwnerish = id !== "cat" && id !== "links";
    const metas = [];
    if (isOwnerish) metas.push(`<span class="pill own" style="--c:${this._ownerColor(g.owner)}"><span class="dot"></span>${e(this._ownerLabel(g.owner))}</span>`);
    if (id === "cat" || id === "fixed") metas.push(`<span class="pill own">${e(this._catLabel(g.suggested_category || g.category))}</span>`);
    if (g.plan_position) metas.push(`<span class="pill">${e(tr("review.plan_pos", { name: g.plan_position.name || g.plan_position }))}</span>`);
    if (g.iban_last4) metas.push(`<span class="pill">…${e(g.iban_last4)}</span>`);
    if (g.suspended) metas.push(`<span class="pill">${e(tr("review.suspended"))}</span>`);
    if (conf != null) metas.push(`<span class="pill conf${g.auto || g.confirmed ? " hi" : ""}">${e(tr("review.conf", { pct: conf }))}</span>`);
    metas.push(`<span class="muted">${e(g.source === "ai" || g.reason === "ai" ? tr("review.reason.ai") : this._reason(g))}</span>`);
    const bcount = !g.count ? tr("review.no_booking") : g.count === 1 ? tr("review.bookings_one") : tr("review.bookings", { n: g.count });
    return `<li class="grp${g.confirmed ? " done" : ""}${this._hl.has(g.group_id) ? " hl" : ""}" data-g="${gid}">
      <button type="button" class="gh" data-toggle="${gid}" aria-expanded="${expanded}" aria-controls="bk-${gid}">
        <span class="nm">${e(g.label || g.key)} <span class="muted">· ${e(bcount)}</span></span>
        <span><span class="am">${e(this._eur(g.amount))}</span><span class="chev" aria-hidden="true">›</span></span></button>
      <div class="meta">${metas.join("")}</div>
      ${this._actions(id, g, busy)}
      <div class="pick" id="pick-${gid}" ${this._pick === g.group_id ? "" : "hidden"}>${this._pick === g.group_id ? this._picker(id, g) : ""}</div>
      <div class="bk" id="bk-${gid}" ${expanded ? "" : "hidden"}>${expanded ? this._bookings(g) : ""}</div></li>`;
  }

  _actions(id, g, busy) {
    const e = window._fd.escHtml;
    const gid = e(g.group_id);
    const dis = busy ? "disabled" : "";
    if (id === "links") {
      if (g.confirmed) {
        return `<div class="act"><span class="muted">${e(tr(g.is_transfer === false ? "review.transfer_isnt" : "review.transfer_is"))}</span>
          <button type="button" class="b sm" data-link="${gid}" data-v="${g.is_transfer === false ? "1" : "0"}" ${dis}>${e(tr("review.change"))}</button></div>`;
      }
      return `<div class="act"><button type="button" class="b sm pri" data-link="${gid}" data-v="1" ${dis}>${e(tr("review.transfer_yes"))}</button>
        <button type="button" class="b sm" data-link="${gid}" data-v="0" ${dis}>${e(tr("review.transfer_no"))}</button></div>`;
    }
    const what = id === "cat" ? this._catLabel(g.suggested_category || g.category) : this._ownerLabel(g.owner);
    const susp = id === "fixed" && g.plan_position
      ? `<button type="button" class="b sm" data-susp="${gid}" data-v="${g.suspended ? "0" : "1"}" ${dis}>${e(tr(g.suspended ? "review.unsuspend" : "review.suspend"))}</button>` : "";
    if (g.confirmed) {
      return `<div class="act"><span class="muted">✓ ${e(tr("review.confirmed"))}</span><button type="button" class="b sm" data-change="${gid}">${e(tr("review.change"))}</button>${susp}</div>`;
    }
    return `<div class="act"><button type="button" class="b sm pri" data-confirm="${gid}" ${dis}>${e(busy ? tr("review.saving") : tr("review.confirm_as", { what }))}</button>
      <button type="button" class="b sm" data-change="${gid}" ${dis}>${e(tr("review.change"))}</button>${susp}</div>`;
  }

  _picker(id, g) {
    const e = window._fd.escHtml;
    const gid = e(g.group_id);
    if (id === "cat") {
      const cats = Object.keys(window._fd.CAT_COLORS || {}).filter((c) => !c.startsWith("income_") && c !== "transfers");
      return `<div class="q">${e(tr("review.pick_cat"))}</div><div class="opts">${cats.map((c) =>
        `<button type="button" class="b sm" data-set-cat="${gid}" data-v="${e(c)}">${e(this._catLabel(c))}</button>`).join("")}</div>`;
    }
    const owners = [SHARED, ...this._persons.map((p) => p.name)];
    return `<div class="q">${e(tr("review.pick_owner"))}</div><div class="opts">${owners.map((o) =>
      `<button type="button" class="b sm" data-set-owner="${gid}" data-v="${e(o)}"><span class="pill own" style="--c:${this._ownerColor(o)};background:transparent;padding:0"><span class="dot"></span></span>${e(this._ownerLabel(o))}</button>`).join("")}</div>`;
  }

  _bookings(g) {
    const e = window._fd.escHtml;
    const bs = g.bookings || [];
    if (!bs.length) return `<p class="muted">${e(tr("review.bk_none"))}</p>`;
    const more = (g.count || 0) > bs.length ? `<p class="muted">${e(tr("review.bookings_more", { n: bs.length }))}</p>` : "";
    return `<ul>${bs.map((b) => `<li><span class="d">${e(b.date ? window._fd.fmtDate(b.date) : "")}</span><span class="l">${e(b.label || "")}</span>
      <span class="a">${e(this._eur(b.amount))}</span><span class="c"><span class="bkchip" data-lid="${e(b.ledger_id || "")}" data-owner="${e(b.owner || "")}" data-src="${e(b.owner_source || "")}" data-conf="${b.owner_confidence ?? ""}" data-merchant="${e(g.kind === "merchant" ? g.label || "" : "")}"></span></span></li>`).join("")}</ul>${more}`;
  }

  /** Reuse of <fd-owner-chip> (E1): properties are set after insertion. */
  _mountChips(root) {
    root.querySelectorAll(".bkchip:not([data-mounted])").forEach((host) => {
      host.dataset.mounted = "1";
      const lid = host.dataset.lid;
      if (!lid || !customElements.get("fd-owner-chip")) return;
      const chip = document.createElement("fd-owner-chip");
      host.append(chip);
      chip.hass = this._hass;
      chip.ledgerId = lid;
      chip.owner = host.dataset.owner || "";
      chip.source = host.dataset.src || "";
      if (host.dataset.conf !== "") chip.confidence = Number(host.dataset.conf);
      if (host.dataset.merchant) chip.merchant = host.dataset.merchant;
      if (this._persons.length) chip.persons = this._persons;
    });
  }

  // ---- final check + report --------------------------------------------------
  _crit(c) {
    const e = window._fd.escHtml;
    const limit = this._eur(c.limit != null ? c.limit : 50);
    let name = tr(`review.crit.${c.id}`, { limit });
    let why = "";
    if (!c.ok) {
      const vars = { names: "", n: c.count || 0, amount: this._eur(c.amount || 0), limit, diff: this._eur(c.difference || 0) };
      if (c.id === "accounts") vars.names = (c.open || []).join(", ");
      if (c.id === "plan") vars.names = (c.shortfalls || []).map((s) => s.name).join(", ");
      why = tr(`review.crit.${c.id}_fail`, vars);
    }
    const target = { accounts: "acc", open_ownership: "owner", transfers: "links", reconcile: "owner", plan: "fixed" }[c.id];
    const jump = !c.ok && target ? `<button type="button" class="b sm" data-jump="${target}" data-ids="${e((c.group_ids || []).join("|"))}">${e(tr("review.jump"))}</button>` : "";
    return `<li class="${c.ok ? "ok" : "bad"}"><span class="ic" aria-hidden="true">${c.ok ? "✓" : "✗"}</span>
      <div><div>${e(name)}</div>${why ? `<div class="why">${e(why)}</div>` : ""}${jump}</div>
      <span class="w">${e(tr(c.ok ? "review.crit_ok" : "review.crit_fail"))}</span></li>`;
  }

  _checkStep() {
    const e = window._fd.escHtml;
    const step = this._stepData("check");
    const crit = Array.isArray(step.criteria) ? step.criteria : [];
    const ok = step.ok != null ? step.ok : crit.every((c) => c.ok);
    const rep = this._report;
    let report;
    if (this._done) report = "";
    else if (!rep) report = `<div class="msg" role="status">${e(tr("review.loading"))}</div>`;
    else if (rep.error) report = `<div class="msg">${e(tr("review.error"))}</div>`;
    else report = this._reportCard(rep);
    const finish = this._done
      ? `<section class="card done-card"><h3>${e(tr("review.completed", { date: this._fmtDate(this._done) }))}</h3>
         <div class="act"><button type="button" class="b pri" data-close>${e(tr("review.close"))}</button></div></section>`
      : `<div class="nav"><button type="button" class="b" data-go="-1">${e(tr("review.prev"))}</button>
         <button type="button" class="b pri" data-complete ${this._busy.has("complete") ? "disabled" : ""}>${e(tr("review.complete"))}</button></div>
         <p class="muted" style="margin-top:-12px">${e(tr("review.complete_hint"))}</p>`;
    return `<section class="card sh"><h2>${e(tr("review.step.check"))}</h2>
      <div class="rec">${e(tr(ok ? "review.check_ok" : "review.check_open"))}</div>
      <ul class="crit">${crit.map((c) => this._crit(c)).join("")}</ul></section>${report}${finish}`;
  }

  _fig(k, v, cls = "") { return `<div class="fig"><div class="v ${cls}">${window._fd.escHtml(v)}</div><div class="k">${window._fd.escHtml(k)}</div></div>`; }
  _pct(v) { return v == null ? "–" : `${new Intl.NumberFormat(this._lang(), { maximumFractionDigits: 1 }).format(v * 100)} %`; }

  _positions(rows) {
    const e = window._fd.escHtml;
    if (!rows || !rows.length) return "";
    return `<h4>${e(tr("review.rep.positions"))}</h4><div class="sc"><table class="tbl"><thead><tr><th>${e(tr("review.rep.positions"))}</th><th class="r">${e(tr("review.rep.planned"))}</th><th class="r">${e(tr("review.rep.actual"))}</th></tr></thead><tbody>${rows.map((p) =>
      `<tr><td>${e(p.name)}${p.suspended ? ` <span class="muted">(${e(tr("review.suspended"))})</span>` : ""}</td><td class="r">${e(this._eur(p.planned))}</td><td class="r">${p.actual == null ? `<span class="muted">${e(tr("review.rep.no_booking"))}</span>` : e(this._eur(p.actual))}</td></tr>`).join("")}</tbody></table></div>`;
  }

  _cats(rows) {
    const e = window._fd.escHtml;
    if (!rows || !rows.length) return "";
    return `<h4>${e(tr("review.rep.cats"))}</h4><div class="sc"><table class="tbl"><tbody>${rows.slice(0, 6).map((c) =>
      `<tr><td>${e(this._catLabel(c.category))}</td><td class="r">${e(this._eur(c.amount))}</td><td class="r muted">${e(this._pct(c.share))}</td></tr>`).join("")}</tbody></table></div>`;
  }

  _reportCard(rep) {
    const e = window._fd.escHtml;
    const tabs = `<div class="tabs" role="group" aria-label="${e(tr("review.report"))}">${TABS.map((t) =>
      `<button type="button" class="b" data-tab="${t}" aria-pressed="${this._tab === t}">${e(tr("review.tab." + t))}</button>`).join("")}</div>`;
    return `<section class="card"><h3>${e(tr("review.report"))}</h3>${tabs}${this._tabBody(rep)}</section>`;
  }

  _tabBody(rep) {
    const e = window._fd.escHtml;
    const empty = `<p class="muted">${e(tr("review.rep.empty"))}</p>`;
    const money = (k, v) => this._fig(tr("review.rep." + k), this._eur(v));
    const t = this._tab;
    if (t === "hh_year") {
      const y = rep.hh_year;
      if (!y || !y.balance) return empty;
      const b = y.balance, sp = y.split || {};
      const persons = Object.entries(sp.persons || {}).map(([n, v]) => `<tr><td>${e(this._personName(n))}</td><td class="r">${e(this._eur(v))}</td></tr>`).join("");
      return `<div class="figs">${money("income", b.income)}${money("expenses", b.expenses)}${money("saved", b.saved)}${this._fig(tr("review.rep.rate"), this._pct(b.savings_rate))}</div>
        <h4>${e(tr("review.rep.expenses"))}</h4><div class="sc"><table class="tbl"><tbody>
        <tr><td>${e(tr("review.owner.shared"))}</td><td class="r">${e(this._eur(sp.shared))}</td></tr>${persons}
        ${sp.open ? `<tr><td>${e(tr("review.rep.open"))}</td><td class="r">${e(this._eur(sp.open))}</td></tr>` : ""}</tbody></table></div>${this._cats(y.categories)}`;
    }
    if (t === "hh_cycle") {
      const c = rep.hh_cycle;
      if (!c) return empty;
      return `<p class="muted">${e(tr("review.rep.cycle", { start: window._fd.fmtDate(c.start), end: window._fd.fmtDate(c.end) }))}</p>
        <div class="figs">${money("income", c.income)}${money("expenses", c.expenses)}${money("saved", c.saved)}${money("fixed", c.fixed)}${money("variable", c.variable)}${money("shared", c.shared)}</div>${this._positions(c.positions)}`;
    }
    if (t === "p_year" || t === "p_cycle") {
      const src = t === "p_year" ? rep.p_year : rep.p_cycle;
      const names = Object.keys(src || {});
      if (!names.length) return empty;
      return names.map((n) => {
        const p = src[n];
        const figs = [money("income", p.income), money("expenses", p.expenses), money("saved", p.saved)];
        if (t === "p_year") figs.push(this._fig(tr("review.rep.rate"), this._pct(p.savings_rate)));
        else if (!p.restricted) figs.push(money("fixed", p.fixed), money("variable", p.variable));
        const extra = p.restricted ? `<p class="muted">${e(tr("review.rep.restricted"))}</p>`
          : (t === "p_year" ? this._cats(p.categories) : this._positions(p.positions));
        return `<h4>${e(this._personName(n))}</h4><div class="figs">${figs.join("")}</div>${extra}`;
      }).join("");
    }
    if (t === "settle") {
      const block = (title, bal) => {
        const rows = Object.entries(bal || {}).map(([n, v]) => {
          const net = v.net || 0;
          const txt = net > 0 ? tr("review.settle.owes", { name: this._personName(n), amount: this._eur(net) })
            : net < 0 ? tr("review.settle.owed", { name: this._personName(n), amount: this._eur(-net) }) : tr("review.settle.even", { name: this._personName(n) });
          return `<li>${e(txt)}</li>`;
        }).join("");
        return `<h4>${e(title)}</h4>${rows ? `<ul style="margin:0;padding-left:18px">${rows}</ul>` : `<p class="muted">${e(tr("review.settle.none"))}</p>`}`;
      };
      const s = rep.settle || {};
      return block(tr("review.settle.cycle"), s.cycle && s.cycle.balances) + block(tr("review.settle.year"), s.year);
    }
    // diff
    const d = rep.diff;
    if (!d) return `<p class="muted">${e(tr("review.diff.none"))}</p>`;
    const row = (label, x, money_ = true) => {
      const f = (v) => (money_ ? this._eur(v) : String(v));
      const cls = x.delta > 0 ? "pos" : x.delta < 0 ? "neg" : "";
      return `<tr><td>${e(label)}</td><td class="r">${e(f(x.before))}</td><td class="r">${e(f(x.after))}</td><td class="r ${cls}">${x.delta > 0 ? "+" : ""}${e(f(x.delta))}</td></tr>`;
    };
    const head = `<thead><tr><th></th><th class="r">${e(tr("review.diff.before"))}</th><th class="r">${e(tr("review.diff.after"))}</th><th class="r">${e(tr("review.diff.delta"))}</th></tr></thead>`;
    const owners = Object.entries(d.owners || {}).map(([n, x]) => row(n === SHARED ? tr("review.owner.shared") : this._ownerLabel(n), x)).join("");
    const settle = Object.entries(d.settle || {}).map(([n, x]) => row(this._personName(n), x)).join("");
    return `<div class="sc"><table class="tbl">${head}<tbody>
      ${row(tr("review.diff.open_groups"), d.open_groups, false)}${row(tr("review.diff.open_amount"), d.open_amount)}</tbody></table></div>
      ${owners ? `<h4>${e(tr("review.diff.owners"))}</h4><div class="sc"><table class="tbl">${head}<tbody>${owners}</tbody></table></div>` : ""}
      ${settle ? `<h4>${e(tr("review.diff.settle"))}</h4><div class="sc"><table class="tbl">${head}<tbody>${settle}</tbody></table></div>` : ""}`;
  }

  // ---- events ----------------------------------------------------------------
  _wire() {
    const sh = this.shadowRoot;
    const on = (sel, fn) => sh.querySelectorAll(sel).forEach((el) => el.addEventListener("click", () => fn(el)));
    on("#retry", () => this.load());
    on("[data-step]", (el) => this._goto(Number(el.dataset.step)));
    on("[data-go]", (el) => this._goto(this._i + Number(el.dataset.go)));
    on("[data-toggle]", (el) => this._toggle(el.dataset.toggle, el));
    on("[data-confirm]", (el) => this._confirm(el.dataset.confirm));
    on("[data-change]", (el) => { this._pick = this._pick === el.dataset.change ? null : el.dataset.change; this._render(); });
    on("[data-set-owner]", (el) => this._confirm(el.dataset.setOwner, { owner: el.dataset.v }));
    on("[data-set-cat]", (el) => this._confirm(el.dataset.setCat, { category: el.dataset.v }));
    on("[data-link]", (el) => this._confirm(el.dataset.link, { confirmed: el.dataset.v === "1" }));
    on("[data-susp]", (el) => this._confirm(el.dataset.susp, { suspended: el.dataset.v === "1" }));
    on("[data-all]", (el) => this._confirmAll(el.dataset.all));
    on("[data-ai]", (el) => this._askAi(el.dataset.ai));
    on("[data-ai-settings]", () => this._nav({ target: "settings", section: "ai" }));
    on("[data-jump]", (el) => this._jump(el.dataset.jump, (el.dataset.ids || "").split("|").filter(Boolean)));
    on("[data-tab]", (el) => { this._tab = el.dataset.tab; this._render(); });
    on("[data-complete]", () => this._complete());
    on("[data-close]", () => this._nav({ target: "back" }));
    sh.addEventListener("fd-owner-changed", () => this._refresh());
  }

  _nav(detail) { this.dispatchEvent(new CustomEvent("fd-navigate", { bubbles: true, composed: true, detail })); }
  _toast(message, type = "info") { this.dispatchEvent(new CustomEvent("fd-toast", { bubbles: true, composed: true, detail: { message, type } })); }

  _goto(k) {
    if (k < 0 || k >= STEPS.length) return;
    this._i = k;
    this._pick = null;
    this._hl = new Set();
    window.scrollTo?.({ top: 0 });
    this._render();
    if (STEPS[k] === "check") this._loadReport();
  }

  _findGroup(gid) {
    for (const s of (this._data && this._data.steps) || []) {
      const g = (s.groups || []).find((x) => x.group_id === gid);
      if (g) return { step: s, group: g };
    }
    return null;
  }

  _toggle(gid, btn) {
    const open = !this._open.has(gid);
    if (open) this._open.add(gid); else this._open.delete(gid);
    btn.setAttribute("aria-expanded", String(open));
    const box = this.shadowRoot.getElementById(`bk-${gid}`);
    const f = this._findGroup(gid);
    if (!box || !f) return;
    box.hidden = !open;
    if (open) { box.innerHTML = this._bookings(f.group); this._mountChips(box); } else box.innerHTML = "";
  }

  async _confirm(gid, extra = {}) {
    const f = this._findGroup(gid);
    if (!f || this._busy.has(gid)) return false;
    const { group: g, step } = f;
    const body = { group_id: g.group_id, kind: g.kind };
    if (step.id === "cat") body.category = extra.category || g.suggested_category || g.category;
    else if (step.id === "links") body.confirmed = extra.confirmed !== undefined ? extra.confirmed : true;
    else body.owner = extra.owner || g.owner;
    if (extra.suspended !== undefined) body.suspended = extra.suspended;
    if (extra.suspended !== undefined) { delete body.owner; }
    this._busy.add(gid);
    this._render();
    try {
      const res = await this._hass.callApi("POST", this._q("review/confirm"), body);
      g.confirmed = true;
      g.confidence = (res && res.confidence) || 95;
      g.reason = "confirmed";
      g.source = "confirmed";
      if (body.owner) {
        g.owner = (res && res.owner) || body.owner;
        for (const b of g.bookings || []) { b.owner = g.owner; b.owner_source = "confirmed"; b.owner_confidence = g.confidence; }
        if (this._open.has(gid)) this._open.delete(gid), this._open.add(gid);
      }
      if (body.category) { g.category = body.category; g.suggested_category = body.category; }
      if (body.confirmed !== undefined) g.is_transfer = body.confirmed;
      if (body.suspended !== undefined) g.suspended = body.suspended;
      this._pick = null;
      this._busy.delete(gid);
      this._render();
      return true;
    } catch (e) {
      console.warn("fd-review: confirm failed:", e);
      this._busy.delete(gid);
      this._toast(tr("review.save_error"), "error");
      this._render();
      return false;
    }
  }

  async _confirmAll(stepId) {
    for (const g of this._openGroups(this._stepData(stepId))) {
      const ok = await this._confirm(g.group_id);
      if (!ok) break;
    }
  }

  async _askAi(stepId) {
    const ids = this._openGroups(this._stepData(stepId)).map((g) => g.group_id).slice(0, 200);
    if (!ids.length || this._aiBusy) return;
    this._aiBusy = true;
    this._ai = null;
    this._render();
    try {
      const res = await this._hass.callApi("POST", this._q("review/ai"), { group_ids: ids });
      if (res.reason) {
        const k = `review.ai_${res.reason}`;
        const t = tr(k);
        this._ai = { step: stepId, warn: true, text: t === k ? tr("review.ai_unavailable") : t, consent: res.reason === "no_consent" };
      } else {
        for (const r of res.groups || []) {
          const f = this._findGroup(r.group_id);
          if (f) Object.assign(f.group, r);
        }
        const n = (res.categorized || 0) + (res.tendencies || 0);
        const rated = (res.groups || []).length || n;
        const parts = [n ? tr(rated === 1 ? "review.ai_done_one" : "review.ai_done", { n: rated }) : tr("review.ai_nothing")];
        if (res.skipped_budget) parts.push(tr(res.skipped_budget === 1 ? "review.ai_budget_one" : "review.ai_budget", { n: res.skipped_budget }));
        this._ai = { step: stepId, warn: !!res.skipped_budget, text: parts.join(" ") };
      }
    } catch (e) {
      console.warn("fd-review: ai failed:", e);
      this._ai = { step: stepId, warn: true, text: tr("review.ai_unavailable") };
    }
    this._aiBusy = false;
    this._render();
  }

  _jump(stepId, ids) {
    const k = STEPS.indexOf(stepId);
    this._i = k;
    this._hl = new Set(ids);
    ids.forEach((i) => this._open.add(i));
    this._render();
    const first = ids[0] && [...this.shadowRoot.querySelectorAll("[data-g]")].find((el) => el.dataset.g === ids[0]);
    if (first) first.scrollIntoView?.({ block: "center" });
    else window.scrollTo?.({ top: 0 });
  }

  async _complete() {
    if (this._busy.has("complete")) return;
    this._busy.add("complete");
    this._render();
    try {
      const res = await this._hass.callApi("POST", this._q("review/complete"), {});
      this._done = (res && res.reviewed_at) || new Date().toISOString();
    } catch (e) {
      console.warn("fd-review: complete failed:", e);
      this._toast(tr("review.save_error"), "error");
    }
    this._busy.delete("complete");
    this._render();
  }
}

window._fd.defineOnce("fd-review", FdReview);
