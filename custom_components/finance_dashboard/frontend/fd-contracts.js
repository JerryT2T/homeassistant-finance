/**
 * fd-contracts — "Verträge und Abos" with notice deadlines, plus the reserves
 * for yearly payments and the pot coverage. Opened from the Start "Jahr" tab.
 *
 *   GET  finance_dashboard/contracts            {contracts:[series + contract block + deadlines]}
 *        (non-admins get aggregates only: no `amounts`/`contract`, so no edit and no chart)
 *   PUT  finance_dashboard/contracts/{id}       partial edit (admin) -> the updated series
 *   POST finance_dashboard/contracts            add by hand (admin, #117 D) -> the new contract (source "manual")
 *   DELETE finance_dashboard/contracts/{id}     delete a manual contract (admin)
 *   POST finance_dashboard/contract_overrides   {action: merge|unmerge|split|unsplit|assign|unassign, ...}
 *        (admin, #117 E/F) -> {contracts, totals}
 *   GET  finance_dashboard/transactions?q=      booking search for "assign" in the sheet (admin)
 *   GET  finance_dashboard/reserves             {reserves:{items,by_owner,total_monthly}, coverage|null}
 *   PUT  finance_dashboard/accounts/{key}/savings {savings:bool} (admin)
 *   GET  finance_dashboard/balances             account list for the savings toggles (admin)
 *
 * Every series carries a `kind` (contract · subscription · regular · irregular,
 * #111); regular and irregular spending has no notice deadline.
 *
 * Properties: hass (required).
 * Events (bubbling, composed): fd-toast {message, type}.
 */

const DOMAIN = "finance_dashboard";

// Fallback texts: used until locales/*.json carry the ct.* / rs.* keys.
const FB = {
  "de": {
    "ct.next_open": "nächste Fälligkeit offen",
    "ct.add.start_hint": "Bestimmt die Fälligkeiten. Ohne Datum bleibt die nächste Fälligkeit offen.",
    "ct.add.err.manual_duplicate": "Einen Vertrag mit diesem Namen gibt es schon.",
    "ct.add.err.invalid_start": "Das Datum muss zwischen 2000 und einem Jahr ab heute liegen.",
    "ct.add.err.invalid_owner": "Diese Person ist unbekannt.",
    "ct.st.merge_none": "Keine andere Zahlungsreihe mit dem Rhythmus „$interval“ zum Zusammenführen.",
    "ct.st.err.merge_interval_mismatch": "Nur Zahlungsreihen mit gleichem Rhythmus lassen sich zusammenführen.",
    "ct.st.err.merge_sign_mismatch": "Ausgaben und Einnahmen lassen sich nicht zusammenführen.",
    "ct.st.err.invalid_merge": "Diese Zahlungsreihe steckt schon in der anderen.",
    "ct.st.title": "Zusammenführen, teilen, Buchungen",
    "ct.st.say": "Wirkt sofort und lässt sich jederzeit rückgängig machen.",
    "ct.st.merged": "zusammengeführt",
    "ct.st.unmerge": "Wieder trennen",
    "ct.st.merge_with": "Mit einer anderen Zahlungsreihe zusammenführen (z. B. PayPal und Bank)",
    "ct.st.merge": "Zusammenführen",
    "ct.st.split_ref": "Nach Vertragsnummer teilen",
    "ct.st.split_amount": "Nach Betrag teilen",
    "ct.st.unsplit": "Teilung aufheben",
    "ct.st.assigned": "Von Hand zugeordnete Buchungen",
    "ct.st.none": "Keine.",
    "ct.st.search": "Buchung suchen und zuordnen",
    "ct.st.search_ph": "Name oder Verwendungszweck",
    "ct.st.no_hits": "Keine passende Buchung gefunden.",
    "ct.st.now_in": "jetzt bei $name",
    "ct.st.assign": "Zuordnen",
    "ct.st.unassign": "Zuordnung entfernen",
    "ct.st.done.merge": "Zusammengeführt",
    "ct.st.done.unmerge": "Wieder getrennt",
    "ct.st.done.split": "Geteilt",
    "ct.st.done.unsplit": "Teilung aufgehoben",
    "ct.st.done.assign": "Buchung zugeordnet",
    "ct.st.done.unassign": "Zuordnung entfernt",
    "ct.st.err.nothing_to_split": "Keine zweite Zahlungsreihe gefunden – hier gibt es nichts zu teilen.",
    "ct.st.err.unknown_series": "Diese Zahlungsreihe gibt es nicht mehr. Lade die Seite neu.",
    "ct.st.err.unknown_booking": "Diese Buchung gibt es nicht mehr.",
    "ct.manual": "von Hand",
    "ct.f.amount": "Betrag pro Zahlung",
    "ct.delete": "Löschen",
    "ct.delete_confirm": "„$name“ löschen?",
    "ct.deleted": "Vertrag gelöscht",
    "ct.add.open": "+ Vertrag hinzufügen",
    "ct.add.title": "Vertrag hinzufügen",
    "ct.add.say": "Manche Verträge zahlst du nur einmal im Jahr oder über Dritte. Wähle, was fehlt – ✓ heißt: schon in der Liste.",
    "ct.add.found": "vorhanden",
    "ct.add.other": "Etwas anderes",
    "ct.add.back": "Zurück",
    "ct.add.save": "Hinzufügen",
    "ct.add.done": "Vertrag hinzugefügt",
    "ct.add.need_name": "Bitte einen Namen eingeben.",
    "ct.add.need_amount": "Bitte einen Betrag größer 0 eingeben.",
    "ct.add.private": "Der Betrag bleibt in Home Assistant. Er geht weder an die Bank noch an eine KI.",
    "ct.add.t.car": "Kfz-Versicherung",
    "ct.add.t.liability": "Haftpflichtversicherung",
    "ct.add.t.contents": "Hausratversicherung",
    "ct.add.t.broadcast": "Rundfunkbeitrag",
    "ct.add.t.auto_club": "Automobilclub",
    "ct.add.t.membership": "Mitgliedschaft",
    "ct.add.t.software": "Domain oder Software",
    "ct.f.name": "Name",
    "ct.f.category": "Kategorie",
    "ct.f.interval": "Rhythmus",
    "ct.interval_detected": "Erkannt war: $interval. Jahreskosten und nächste Zahlung folgen deiner Wahl.",
    "ct.title": "Verträge und Abos",
    "ct.back": "Zurück",
    "ct.loading": "Lade Verträge…",
    "ct.error": "Verträge konnten nicht geladen werden.",
    "ct.retry": "Erneut versuchen",
    "ct.total_month": "Pro Monat",
    "ct.total_year": "Pro Jahr",
    "ct.total_note": "Feste Kosten aus $n Verträgen und Abos",
    "ct.empty": "Noch keine wiederkehrenden Zahlungen erkannt. Sobald ein Posten mehrfach gebucht wurde, erscheint er hier.",
    "ct.member_note": "Du siehst die Verträge, die dir oder dem Haushalt gehören, als Überblick.",
    "ct.notice_by": "Kündigen bis $date",
    "ct.days_left": "noch $n Tage",
    "ct.days_one": "noch 1 Tag",
    "ct.days_today": "heute",
    "ct.next_deadline": "Nächste Kündigungsfrist",
    "ct.effective_end": "Laufzeitende",
    "ct.price_up": "Preis +$pct %",
    "ct.price_down": "Preis $pct %",
    "ct.price_change": "Preisänderung: von $previous auf $last",
    "ct.special": "Sonderkündigung möglich",
    "ct.missing": "Zahlung steht aus",
    "ct.ended": "Nicht mehr aktiv",
    "ct.next": "Nächste Zahlung $date",
    "ct.per_year": "$amount pro Jahr",
    "ct.per_month": "$amount pro Monat",
    "ct.payments": "Letzte Zahlungen",
    "ct.interval.weekly": "wöchentlich",
    "ct.interval.monthly": "monatlich",
    "ct.interval.quarterly": "vierteljährlich",
    "ct.interval.half_yearly": "halbjährlich",
    "ct.interval.yearly": "jährlich",
    "ct.edit": "Vertrag bearbeiten",
    "ct.f.start": "Vertragsbeginn",
    "ct.f.min_term": "Mindestlaufzeit (Monate)",
    "ct.f.renewal": "Verlängerung um (Monate)",
    "ct.f.notice": "Kündigungsfrist",
    "ct.f.reference": "Die Frist gilt zum",
    "ct.f.owner": "Gehört zu",
    "ct.f.special": "Sonderkündigungsrecht bei Preiserhöhung",
    "ct.special_prefilled": "Aus den letzten Zahlungen vorbelegt – bitte prüfen.",
    "ct.unit.days": "Tage",
    "ct.unit.weeks": "Wochen",
    "ct.unit.months": "Monate",
    "ct.ref.end_of_term": "Laufzeitende",
    "ct.ref.end_of_month": "Monatsende",
    "ct.owner.shared": "Haushalt",
    "ct.defaults": "Üblich für $cat: $term Monate Laufzeit, Verlängerung um $renewal Monate, Kündigungsfrist $notice $unit.",
    "ct.reset": "Auf Standard zurücksetzen",
    "ct.save": "Speichern",
    "ct.saving": "Speichere…",
    "ct.cancel": "Abbrechen",
    "ct.saved": "Vertrag gespeichert",
    "ct.save_failed": "Speichern fehlgeschlagen",
    "ct.cat.telecom": "Telekommunikation",
    "rs.title": "Rücklagen für jährliche Zahlungen",
    "rs.intro": "Seltene Zahlungen, auf den Monat verteilt. So liegt das Geld bereit, wenn sie fällig werden.",
    "rs.total": "Zusammen $amount pro Monat",
    "rs.month": "$amount pro Monat",
    "rs.due": "fällig $date",
    "st.title": "Abrechnungen",
    "st.usage": "Verbrauchsabhängig (Abschlag + Jahresabrechnung)",
    "st.detected": "erkannt",
    "st.none": "Noch keine Abrechnung zugeordnet.",
    "st.back": "Nachzahlung $amount",
    "st.refund": "Erstattung $amount",
    "st.src.keyword": "erkannt",
    "st.src.manual": "zugeordnet",
    "st.remove": "Zuordnung entfernen",
    "st.expected_back": "Erwartet: Nachzahlung $amount bis $date · Rücklage $month/Monat",
    "st.expected_refund": "Erwartet: Erstattung $amount bis $date · senkt die Jahreskosten",
    "st.expected_none": "Keine Nachzahlung erwartet: der neue Abschlag deckt die letzte Abrechnung.",
    "st.step": "Abschlag seit der letzten Abrechnung $step/Monat geändert",
    "st.candidates": "Weitere Buchungen dieses Zahlungsempfängers",
    "st.assign": "Als Abrechnung",
    "st.recalc": "Wird nach dem Speichern neu berechnet.",
    "rs.settlement": "Erwartete Jahresabrechnung",
    "rs.empty": "Keine jährlichen oder vierteljährlichen Zahlungen erkannt.",
    "rs.owner_total": "$owner: $amount pro Monat",
    "rs.coverage": "Töpfe und Kontostand",
    "rs.covered": "Gedeckt",
    "rs.shortfall": "Es fehlen $amount",
    "rs.unknown": "Kontostand noch unbekannt",
    "rs.virtual": "Töpfe $amount",
    "rs.real": "Kontostand $amount",
    "rs.topup": "Zum Auffüllen: $amount",
    "rs.unassigned": "Töpfe ohne Konto: $n",
    "rs.accounts": "Sparkonten",
    "rs.accounts_hint": "Markiere Konten, auf denen Rücklagen liegen.",
    "rs.savings": "Ist ein Sparkonto",
    "rs.savings_failed": "Konnte nicht gespeichert werden"
  },
  "en": {
    "ct.next_open": "next due date open",
    "ct.add.start_hint": "Sets the due dates. Without a date the next due date stays open.",
    "ct.add.err.manual_duplicate": "A contract with this name already exists.",
    "ct.add.err.invalid_start": "The date must lie between 2000 and one year from today.",
    "ct.add.err.invalid_owner": "This person is unknown.",
    "ct.st.merge_none": "No other payment series with the rhythm “$interval” to merge with.",
    "ct.st.err.merge_interval_mismatch": "Only payment series with the same rhythm can be merged.",
    "ct.st.err.merge_sign_mismatch": "Expenses and income cannot be merged.",
    "ct.st.err.invalid_merge": "This payment series is already part of the other one.",
    "ct.st.title": "Merge, split, bookings",
    "ct.st.say": "Takes effect right away and can be undone at any time.",
    "ct.st.merged": "merged",
    "ct.st.unmerge": "Separate again",
    "ct.st.merge_with": "Merge with another payment series (e.g. PayPal and bank)",
    "ct.st.merge": "Merge",
    "ct.st.split_ref": "Split by contract number",
    "ct.st.split_amount": "Split by amount",
    "ct.st.unsplit": "Undo split",
    "ct.st.assigned": "Bookings assigned by hand",
    "ct.st.none": "None.",
    "ct.st.search": "Find and assign a booking",
    "ct.st.search_ph": "Name or remittance text",
    "ct.st.no_hits": "No matching booking found.",
    "ct.st.now_in": "now in $name",
    "ct.st.assign": "Assign",
    "ct.st.unassign": "Remove assignment",
    "ct.st.done.merge": "Merged",
    "ct.st.done.unmerge": "Separated again",
    "ct.st.done.split": "Split",
    "ct.st.done.unsplit": "Split undone",
    "ct.st.done.assign": "Booking assigned",
    "ct.st.done.unassign": "Assignment removed",
    "ct.st.err.nothing_to_split": "No second payment series found – nothing to split here.",
    "ct.st.err.unknown_series": "This payment series no longer exists. Reload the page.",
    "ct.st.err.unknown_booking": "This booking no longer exists.",
    "ct.manual": "added by hand",
    "ct.f.amount": "Amount per payment",
    "ct.delete": "Delete",
    "ct.delete_confirm": "Delete “$name”?",
    "ct.deleted": "Contract deleted",
    "ct.add.open": "+ Add contract",
    "ct.add.title": "Add contract",
    "ct.add.say": "Some contracts are paid once a year or through a third party. Pick what is missing – ✓ means it is already listed.",
    "ct.add.found": "listed",
    "ct.add.other": "Something else",
    "ct.add.back": "Back",
    "ct.add.save": "Add",
    "ct.add.done": "Contract added",
    "ct.add.need_name": "Please enter a name.",
    "ct.add.need_amount": "Please enter an amount above 0.",
    "ct.add.private": "The amount stays in Home Assistant. It never goes to the bank or an AI.",
    "ct.add.t.car": "Car insurance",
    "ct.add.t.liability": "Liability insurance",
    "ct.add.t.contents": "Contents insurance",
    "ct.add.t.broadcast": "Broadcasting fee",
    "ct.add.t.auto_club": "Automobile club",
    "ct.add.t.membership": "Membership",
    "ct.add.t.software": "Domain or software",
    "ct.f.name": "Name",
    "ct.f.category": "Category",
    "ct.f.interval": "Rhythm",
    "ct.interval_detected": "Detected: $interval. Yearly cost and next payment follow your choice.",
    "ct.title": "Contracts and subscriptions",
    "ct.back": "Back",
    "ct.loading": "Loading contracts…",
    "ct.error": "Contracts could not be loaded.",
    "ct.retry": "Try again",
    "ct.total_month": "Per month",
    "ct.total_year": "Per year",
    "ct.total_note": "Fixed costs from $n contracts and subscriptions",
    "ct.empty": "No recurring payments detected yet. Once an item has been booked several times it shows up here.",
    "ct.member_note": "You see the contracts that belong to you or the household as an overview.",
    "ct.notice_by": "Cancel by $date",
    "ct.days_left": "$n days left",
    "ct.days_one": "1 day left",
    "ct.days_today": "today",
    "ct.next_deadline": "Next notice deadline",
    "ct.effective_end": "End of term",
    "ct.price_up": "Price +$pct %",
    "ct.price_down": "Price $pct %",
    "ct.price_change": "Price change: from $previous to $last",
    "ct.special": "Special termination possible",
    "ct.missing": "Payment is due",
    "ct.ended": "No longer active",
    "ct.next": "Next payment $date",
    "ct.per_year": "$amount per year",
    "ct.per_month": "$amount per month",
    "ct.payments": "Recent payments",
    "ct.interval.weekly": "weekly",
    "ct.interval.monthly": "monthly",
    "ct.interval.quarterly": "quarterly",
    "ct.interval.half_yearly": "half-yearly",
    "ct.interval.yearly": "yearly",
    "ct.edit": "Edit contract",
    "ct.f.start": "Contract start",
    "ct.f.min_term": "Minimum term (months)",
    "ct.f.renewal": "Renews by (months)",
    "ct.f.notice": "Notice period",
    "ct.f.reference": "The period counts to",
    "ct.f.owner": "Belongs to",
    "ct.f.special": "Special termination right on a price increase",
    "ct.special_prefilled": "Prefilled from the latest payments – please check.",
    "ct.unit.days": "days",
    "ct.unit.weeks": "weeks",
    "ct.unit.months": "months",
    "ct.ref.end_of_term": "End of term",
    "ct.ref.end_of_month": "End of month",
    "ct.owner.shared": "Household",
    "ct.defaults": "Usual for $cat: $term months term, renewal by $renewal months, notice period $notice $unit.",
    "ct.reset": "Reset to defaults",
    "ct.save": "Save",
    "ct.saving": "Saving…",
    "ct.cancel": "Cancel",
    "ct.saved": "Contract saved",
    "ct.save_failed": "Saving failed",
    "ct.cat.telecom": "Telecom",
    "rs.title": "Reserves for yearly payments",
    "rs.intro": "Rare payments spread over the months, so the money is ready when they fall due.",
    "rs.total": "Together $amount per month",
    "rs.month": "$amount per month",
    "rs.due": "due $date",
    "st.title": "Settlements",
    "st.usage": "Usage-based (advance + annual settlement)",
    "st.detected": "detected",
    "st.none": "No settlement assigned yet.",
    "st.back": "Back-payment $amount",
    "st.refund": "Refund $amount",
    "st.src.keyword": "detected",
    "st.src.manual": "assigned",
    "st.remove": "Remove assignment",
    "st.expected_back": "Expected: back-payment $amount by $date · reserve $month/month",
    "st.expected_refund": "Expected: refund $amount by $date · lowers the yearly cost",
    "st.expected_none": "No back-payment expected: the new advance covers the last settlement.",
    "st.step": "Advance changed by $step/month since the last settlement",
    "st.candidates": "Other bookings of this payee",
    "st.assign": "As settlement",
    "st.recalc": "Recalculated after saving.",
    "rs.settlement": "Expected annual settlement",
    "rs.empty": "No yearly or quarterly payments detected.",
    "rs.owner_total": "$owner: $amount per month",
    "rs.coverage": "Pots and account balance",
    "rs.covered": "Covered",
    "rs.shortfall": "$amount missing",
    "rs.unknown": "Balance not known yet",
    "rs.virtual": "Pots $amount",
    "rs.real": "Balance $amount",
    "rs.topup": "To top up: $amount",
    "rs.unassigned": "Pots without an account: $n",
    "rs.accounts": "Savings accounts",
    "rs.accounts_hint": "Mark the accounts that hold reserves.",
    "rs.savings": "Is a savings account",
    "rs.savings_failed": "Could not be saved"
  }
};

// Old servers without `contract.defaults`: mirrors contracts.CATEGORY_DEFAULTS.
const CAT_DEFAULTS = {
  health: [12, 12, 3, "months"],
  housing_warm: [12, 12, 1, "months"],
  finance: [12, 12, 3, "months"],
  housing_cold: [12, 12, 3, "months"],
};
const FALLBACK_DEFAULTS = [1, 1, 0, "days"];
const KINDS = ["contract", "subscription", "regular", "irregular"];
const NO_NOTICE = new Set(["regular", "irregular"]);
const PLAN_MODES = ["auto", "highest", "average", "last", "median", "fixed"];
const PER_YEAR = { weekly: 52, monthly: 12, quarterly: 4, half_yearly: 2, yearly: 1 };

// Mirrors recurring.plan_amount (#114) for the live preview in the sheet.
function planAmount(amounts, mode, fixed) {
  const m = (amounts || []).map((a) => Math.abs(a));
  // No payments (a contract added by hand): the fixed amount is the plan.
  if (!m.length) return fixed != null && fixed !== "" ? Math.round(Math.abs(Number(fixed)) * 100) / 100 : 0;
  const r2 = (v) => Math.round(v * 100) / 100;
  const median = (xs) => { const s = [...xs].sort((a, b) => a - b); const h = s.length >> 1; return s.length % 2 ? s[h] : (s[h - 1] + s[h]) / 2; };
  if (mode === "fixed" && fixed != null && fixed !== "") return r2(Math.abs(Number(fixed)));
  if (mode === "average") return r2(m.reduce((a, b) => a + b, 0) / m.length);
  if (mode === "last") return r2(m[m.length - 1]);
  if (mode === "median") return r2(median(m));
  if (mode === "highest" || mode === "fixed") return r2(Math.max(...m));  // fixed without amount: like the server
  const last = r2(m[m.length - 1]);
  let tail = 0;
  for (let i = m.length - 1; i >= 0 && r2(m[i]) === last; i--) tail++;
  const before = m.slice(0, m.length - tail);
  if (before.length) {
    const base = median(before);
    if (tail >= 2 && r2(base) !== last) return last;
    const steady = Math.max(...before) <= Math.min(...before) * 1.01;
    if (tail === 1 && steady && base && last / base > 0.5 && last / base < 1.8) return last;
  }
  return r2(median(m));
}

// Typical yearly contracts a bank rarely shows as a series (#117 D). `words`
// mark an entry as already found when a contract name contains one of them.
const CHECKLIST = [
  { id: "car", interval: "yearly", kind: "contract", category: "mobility", words: ["kfz", "autoversicherung"] },
  { id: "liability", interval: "yearly", kind: "contract", category: "finance", words: ["haftpflicht", "liability"] },
  { id: "contents", interval: "yearly", kind: "contract", category: "finance", words: ["hausrat", "contents"] },
  { id: "broadcast", interval: "quarterly", kind: "contract", category: "media", words: ["rundfunk", "beitragsservice"] },
  { id: "auto_club", interval: "yearly", kind: "contract", category: "mobility", words: ["adac", "automobil", "acv", "avd"] },
  { id: "membership", interval: "yearly", kind: "contract", category: "leisure", words: ["verein", "mitglied", "membership"] },
  { id: "software", interval: "yearly", kind: "subscription", category: "media", words: ["domain", "software", "lizenz", "license"] },
];

const TERM_FIELDS = ["min_term_months", "renewal_months", "notice_value", "notice_unit", "notice_reference"];

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
.root { container: contracts / inline-size; position: relative; color: var(--fd-t1); font-size: 13px; line-height: 1.4; }
button { font: inherit; color: inherit; cursor: pointer; }
h3 { margin: 0 0 4px; font-size: 15px; font-weight: 500; }
.card { margin: 0 0 12px; padding: 12px 14px; border-radius: var(--fd-r-card); background: var(--fd-card); box-shadow: var(--fd-sh1); }
.muted { color: var(--fd-t2); font-size: 11.5px; }
.root, .cols > div { min-width: 0; }
.ct .l3 > * { min-width: 0; }
.rw > span:first-child, .cov .l1 > * { overflow-wrap: anywhere; }
.msg { padding: 28px 12px; text-align: center; color: var(--fd-t2); }
.msg .btn { margin-top: 12px; }
.tot { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 8px; }
.tot > div { padding: 8px 10px; border-radius: 10px; background: var(--fd-sunk); }
.tot span { display: block; font-size: 11px; color: var(--fd-t2); }
.tot b { display: block; font-size: 22px; font-weight: 500; }
.tl { margin: 0 0 2px; font-size: 13px; color: var(--fd-t2); }
.tsep { height: 1px; margin: 12px 0; background: var(--fd-line); }
.ct { display: block; width: 100%; padding: 10px 0; border: 0; background: transparent; text-align: left; }
.ct + .ct { border-top: 1px solid var(--fd-line); }
button.ct { min-height: var(--fd-touch); }
.ct .l1 { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.ct .nm { min-width: 0; display: flex; align-items: center; gap: 8px; font-weight: 500; }
.ct .nm i { flex: none; font-style: normal; }
.ct .nm span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ct .amt { flex: none; text-align: right; }
.ct .amt b { display: block; font-weight: 500; }
.ct .l2 { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 6px; margin-top: 4px; }
.ct .l3 { display: flex; align-items: flex-end; justify-content: space-between; gap: 10px; margin-top: 4px; }
.ct.ended { opacity: .6; }
.badge { display: inline-flex; align-items: center; padding: 1px 9px; border-radius: var(--fd-r-pill); font-size: 11.5px; font-weight: 500; white-space: nowrap; background: var(--fd-sunk); color: var(--fd-t2); }
.badge.due { background: var(--fd-near-bg); color: color-mix(in srgb, var(--fd-near) 72%, var(--fd-t1)); }
.badge.ok { background: var(--fd-ok-bg); color: color-mix(in srgb, var(--fd-ok) 72%, var(--fd-t1)); }
.badge.info { background: var(--fd-a50); color: var(--fd-a900); }
.spark { flex: none; width: 96px; height: 26px; }
.spark rect { fill: var(--fd-a300); }
.spark rect.last { fill: var(--fd-a700); }
.sw { flex: none; position: relative; width: 48px; height: 28px; border-radius: 14px; border: 1px solid var(--fd-line); background: var(--fd-sunk); padding: 0; }
.sw::after { content: ""; position: absolute; top: 3px; left: 3px; width: 20px; height: 20px; border-radius: 50%; background: var(--fd-t3); transition: transform .15s, background .15s; }
.sw[aria-checked="true"] { background: var(--fd-a700); border-color: var(--fd-a700); }
.sw[aria-checked="true"]::after { transform: translateX(20px); background: #fff; }
.hit { display: inline-flex; align-items: center; min-height: var(--fd-touch); }
.rw { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 0; }
.rw + .rw { border-top: 1px solid var(--fd-line); }
.rw > span:first-child { min-width: 0; display: flex; flex-direction: column; }
.rw b { font-weight: 500; }
.cov { padding: 10px 0; }
.cov + .cov { border-top: 1px solid var(--fd-line); }
.cov .bar { position: relative; height: 10px; margin: 8px 0 4px; border-radius: 5px; background: var(--fd-sunk); overflow: hidden; }
.cov .bar i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 5px; background: var(--fd-ok); }
.cov.short .bar i { background: var(--fd-near); }
.cov .l1 { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.btn { min-height: var(--fd-touch); padding: 0 16px; border: 1px solid transparent; border-radius: var(--fd-r-pill); background: var(--fd-a700); color: #fff; font-weight: 500; }
.rv { padding: 10px 0; }
.rv + .rv { border-top: 1px solid var(--fd-line); }
.rv .sub { font-size: 12.5px; margin: 2px 0 8px; }
.rvb { display: flex; gap: 8px; flex-wrap: wrap; }
.kf { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 4px; }
.kf button { min-height: 40px; padding: 0 12px; border: 1px solid var(--fd-line); border-radius: var(--fd-r-pill); background: transparent; font-size: 12.5px; }
.kf button[aria-pressed="true"] { background: var(--fd-a50); border-color: var(--fd-a500); color: var(--fd-a900); font-weight: 500; }
.btn.ghost { background: transparent; color: var(--fd-a700); border-color: var(--fd-a100); }
.btn:disabled { opacity: .5; cursor: default; }
.scrim { position: fixed; inset: 0; z-index: 50; display: flex; align-items: flex-end; justify-content: center; background: rgba(0,0,0,.4); }
.sheet:focus { outline: none; }
.sheet { width: min(480px, 100%); max-height: 90dvh; overflow: auto; padding: 16px; border-radius: 18px 18px 0 0; background: var(--fd-card); box-shadow: var(--fd-sh2); }
.sheet label, .sheet .lbl { display: block; margin: 12px 0 4px; font-size: 12px; color: var(--fd-t2); }
.sheet input[type=number], .sheet input[type=date], .sheet input[type=text], .sheet input[type=search], .sheet select { box-sizing: border-box; width: 100%; min-height: var(--fd-touch); padding: 0 12px; border: 1px solid var(--fd-line); border-radius: 10px; background: var(--fd-page); color: var(--fd-t1); font: inherit; }
.nrow { display: grid; grid-template-columns: 90px 1fr; gap: 8px; align-items: center; }
.opts { display: flex; flex-wrap: wrap; gap: 6px; }
.opts button { min-height: 40px; padding: 0 14px; border: 1px solid var(--fd-line); border-radius: var(--fd-r-pill); background: transparent; }
.opts button[aria-checked="true"] { background: var(--fd-a50); border-color: var(--fd-a500); color: var(--fd-a900); font-weight: 500; }
.hint { margin-top: 10px; padding: 8px 10px; border-radius: 10px; background: var(--fd-sunk); color: var(--fd-t2); font-size: 11.5px; }
.acts { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.err { margin-top: 8px; color: var(--fd-over); font-size: 12px; }
button:focus-visible, input:focus-visible, select:focus-visible { outline: 2px solid var(--fd-a500); outline-offset: 2px; }
@container contracts (min-width: 760px) {
  .cols { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(280px, 1fr); gap: 16px; align-items: start; }
  .scrim { align-items: center; }
  .sheet { border-radius: 18px; }
  .spark { width: 140px; height: 30px; }
}
`;

class FdContracts extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._items = null;
    this._kind = "all";
    this._reserves = null;
    this._coverage = null;
    this._accounts = [];
    this._err = false;
    this._sheet = null;
    this._wired = false;
  }

  get hass() { return this._hass; }
  set hass(h) {
    const first = !this._hass;
    this._hass = h;
    if (first) this.load();
  }

  get _isAdmin() { return !!(this._hass && this._hass.user && this._hass.user.is_admin); }

  async load() {
    if (!this._hass) return;
    await window._fd.t("ct.title");
    this._err = false;
    this._render();
    try {
      const r = await this._hass.callApi("GET", `${DOMAIN}/contracts`);
      this._labels = await window._fd.getLabels(this._hass);
      // Candidates (#129) are not sure to be contracts: kept out of the list
      // and the totals, asked under "Prüfen" (#130).
      const all = (r && r.contracts) || [];
      this._items = all.filter((c) => !c.candidate);
      this._candidates = all.filter((c) => c.candidate && c.status !== "ended");
    } catch (e) {
      console.warn("fd-contracts: load failed:", e);
      this._err = true;
      this._items = null;
    }
    // Reserves are an add-on: a failure there must not hide the contracts.
    try {
      const r = await this._hass.callApi("GET", `${DOMAIN}/reserves`);
      this._reserves = (r && r.reserves) || null;
      this._coverage = (r && r.coverage) || null;
    } catch (e) {
      this._reserves = null;
      this._coverage = null;
    }
    this._accounts = [];
    if (this._isAdmin) {
      try {
        const b = await this._hass.callApi("GET", `${DOMAIN}/balances`);
        const saved = new Map(((this._coverage && this._coverage.accounts) || []).map((a) => [a.account_key, a.savings]));
        this._accounts = Object.values(b || {})
          .filter((a) => a && typeof a === "object" && !a.error && a.account_key)
          .map((a) => ({
            key: a.account_key,
            name: a.custom_name || a.account_name || a.name || a.institution || a.account_key,
            institution: [a.institution, a.iban_masked].filter(Boolean).join(" · "),
            savings: a.savings != null ? !!a.savings : !!saved.get(a.account_key),
          }));
      } catch (e) { /* no account list: the toggles simply stay hidden */ }
    }
    this._render();
  }

  // ---- formatting -------------------------------------------------------
  _m(v, dec = 0) {
    return new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR", minimumFractionDigits: dec, maximumFractionDigits: dec }).format(v || 0);
  }
  _lang() { return (this._hass && this._hass.language) || navigator.language || "de"; }
  _date(iso, long = false) {
    const d = new Date(`${iso}T12:00:00`);
    if (isNaN(d)) return "";
    return d.toLocaleDateString(this._lang(), long ? { day: "numeric", month: "short", year: "numeric" } : { day: "numeric", month: "short" });
  }
  _catLabel(c) {
    const k = `ct.cat.${c}`;
    const s = tr(k);
    return s !== k ? s : (window._fd.CAT_LABELS || {})[c] || c || "";
  }
  _catIcon(c) { return (window._fd.CAT_ICONS || {})[c] || "📦"; }
  _ownerLabel(o) { return o === "shared" ? tr("ct.owner.shared") : o || ""; }

  // ---- render -----------------------------------------------------------
  _render() {
    const sh = this.shadowRoot;
    const e = window._fd.escHtml;
    let body;
    if (this._err) body = `<div class="msg">${e(tr("ct.error"))}<br><button class="btn" data-act="retry">${e(tr("ct.retry"))}</button></div>`;
    else if (!this._items) body = `<div class="msg">${e(tr("ct.loading"))}</div>`;
    else body = this._main();
    const head = this.hasAttribute("embedded") ? "" : `<fd-subpage-header title="${e(tr("ct.title"))}"></fd-subpage-header>`;
    // A re-render (e.g. reserves arriving late) must not drop the keyboard focus (QA #117).
    const keep = this._focusAfter || this._focusSel();
    this._focusAfter = null;
    const top = sh.querySelector(".sheet")?.scrollTop || 0;
    sh.innerHTML = `<style>${window._fd.SHARED_CSS}${CSS}</style><div class="root">${head}<div class="cols">${body}</div><div id="sheet"></div></div>`;
    if (this._sheet || this._add) this._paintSheet();
    const sc = sh.querySelector(".sheet");
    if (sc) sc.scrollTop = top;
    if (keep) sh.querySelector(keep)?.focus();
    this._keepFocusInSheet();
    if (!this._wired) { this._wired = true; this._wire(); }
  }

  /** Selector of the focused control (its id or its data-* attributes), to find it again after a repaint. */
  _focusSel() {
    const a = this.shadowRoot.activeElement;
    if (!a) return null;
    if (a.id) return `#${CSS.escape(a.id)}`;
    const ds = Object.entries(a.dataset || {});
    if (!ds.length) return null;
    const attr = (k) => k.replace(/[A-Z]/g, (m) => `-${m.toLowerCase()}`);
    return a.tagName.toLowerCase() + ds.map(([k, v]) => `[data-${attr(k)}="${CSS.escape(v)}"]`).join("");
  }

  _kindOf(c) { return c.kind || "contract"; }

  _kindFilterHtml() {
    const e = window._fd.escHtml;
    const count = (k) => this._items.filter((c) => this._kindOf(c) === k).length;
    const kinds = KINDS.filter((k) => count(k));
    if (kinds.length < 2) return "";
    const btn = (k, label, n) => `<button type="button" data-kind="${k}" aria-pressed="${this._kind === k}">${e(label)} · ${n}</button>`;
    return `<div class="kf" role="group" aria-label="${e(tr("ct.kind.filter"))}">${btn("all", tr("ct.kind.all"), this._items.length)}${kinds.map((k) => btn(k, tr(`ct.kind.${k}`), count(k))).join("")}</div>`;
  }

  _main() {
    const e = window._fd.escHtml;
    const kinds = new Set(this._items.map((c) => this._kindOf(c)));
    if (this._kind !== "all" && !kinds.has(this._kind)) this._kind = "all";
    const shown = this._kind === "all" ? this._items : this._items.filter((c) => this._kindOf(c) === this._kind);
    const live = shown.filter((c) => c.status !== "ended");
    const sorted = [...shown].sort((a, b) =>
      (a.status === "ended") - (b.status === "ended") || String(a.next_deadline || "9").localeCompare(String(b.next_deadline || "9")));
    const list = sorted.length
      ? sorted.map((c) => this._row(c)).join("")
      : `<p class="muted">${e(tr("ct.empty"))}</p>`;
    return `<div>
  ${live.length || !this._isAdmin ? `<section class="card">
    ${live.length ? this._totalsHtml(live) : ""}
    ${this._isAdmin ? "" : `<p class="muted" style="margin:8px 0 0">${e(tr("ct.member_note"))}</p>`}
  </section>` : ""}
  <section class="card" aria-label="${e(tr("ct.title"))}">${this._kindFilterHtml()}${list}
    ${this._isAdmin ? `<div class="acts" style="margin-top:8px"><button type="button" class="btn ghost" data-act="add">${e(tr("ct.add.open"))}</button></div>` : ""}</section>
  ${this._reviewHtml()}
</div>
<div>${this._reservesHtml()}</div>`;
  }

  // Mirrors contracts.contract_totals (#115): fixed = contracts + subscriptions,
  // regular = regular + irregular spending; candidates are never in _items.
  _totalsHtml(live) {
    const e = window._fd.escHtml;
    const block = (items, label, note) => {
      const year = items.reduce((s, c) => s + (c.annual_cost || 0), 0);
      return `${label ? `<h3 class="tl">${e(label)}</h3>` : ""}<div class="tot"><div><span>${e(tr("ct.total_month"))}</span><b>${e(this._m(year / 12))}</b></div>
      <div><span>${e(tr("ct.total_year"))}</span><b>${e(this._m(year))}</b></div></div>
      <p class="muted" style="margin:8px 0 0">${e(note)}</p>`;
    };
    if (this._kind !== "all") {
      return block(live, "", tr("ct.total_note_kind", { n: live.length, kind: tr(`ct.kind.${this._kind}`) }));
    }
    const regular = live.filter((c) => NO_NOTICE.has(this._kindOf(c)));
    const fixed = live.filter((c) => !NO_NOTICE.has(this._kindOf(c)));
    if (!regular.length) return block(fixed, "", tr("ct.total_note", { n: fixed.length }));
    const parts = [];
    if (fixed.length) parts.push(block(fixed, tr("ct.total_fixed"), tr("ct.total_note", { n: fixed.length })));
    parts.push(block(regular, tr("ct.total_regular"), tr("ct.total_regular_note", { n: regular.length })));
    return parts.join(`<div class="tsep"></div>`);
  }

  _reviewHtml() {
    const cands = this._isAdmin ? this._candidates || [] : [];
    if (!cands.length) return "";
    const e = window._fd.escHtml;
    const rows = cands.map((c) => {
      const why = ((c.confidence && c.confidence.reasons) || []).map((r) => tr(`ct.reason.${r}`)).join(" · ");
      const sub = [tr(`ct.interval.${c.interval}`), tr("ct.per_month", { amount: this._m(c.monthly_equivalent, 2) })].join(" · ");
      const busy = this._reviewing === c.id ? " disabled" : "";
      return `<div class="rv"><div class="l1"><span class="nm"><i aria-hidden="true">${this._catIcon(c.category)}</i><span>${e(c.display_name || c.creditor)}</span></span>
  <span class="badge info" data-tip="${e(why)}" aria-label="${e(tr("ct.review.why") + ": " + why)}">${e(tr("ct.review.why"))}</span></div>
<div class="sub muted">${e(sub)}</div>
<div class="rvb"><button type="button" class="btn" data-review="contract" data-id="${e(c.id)}"${busy}>${e(tr("ct.review.yes"))}</button>
  <button type="button" class="btn ghost" data-review="not_contract" data-id="${e(c.id)}"${busy}>${e(tr("ct.review.no"))}</button></div></div>`;
    }).join("");
    return `<section class="card" aria-label="${e(tr("ct.review.title"))}"><h3>${e(tr("ct.review.title"))}</h3>
  <p class="muted" style="margin:0 0 8px">${e(tr("ct.review.say"))}</p>${rows}</section>`;
  }

  async _review(id, answer) {
    if (this._reviewing) return;
    this._reviewing = id;
    this._render();
    try {
      const upd = await this._hass.callApi("PUT", `${DOMAIN}/contracts/${encodeURIComponent(id)}`, { review: answer });
      this._candidates = (this._candidates || []).filter((c) => c.id !== id);
      if (upd && !upd.dismissed && !upd.candidate) this._items = [...(this._items || []), upd];
      this._toast(tr(answer === "contract" ? "ct.review.done_yes" : "ct.review.done_no"));
    } catch (e) {
      this._toast(tr("ct.review.failed"), "error");
    } finally {
      this._reviewing = null;
      this._render();
    }
  }

  _spark(c) {
    const a = (c.amounts || []).map((v) => Math.abs(v));
    if (a.length < 2) return "";
    const mx = Math.max(...a, 1);
    const w = 100 / a.length;
    const bars = a.map((v, i) => {
      const h = Math.max(2, (v / mx) * 24);
      return `<rect class="${i === a.length - 1 ? "last" : ""}" x="${(i * w + w * 0.12).toFixed(2)}" y="${(26 - h).toFixed(2)}" width="${(w * 0.76).toFixed(2)}" height="${h.toFixed(2)}" rx="1"/>`;
    }).join("");
    return `<svg class="spark" viewBox="0 0 100 26" preserveAspectRatio="none" role="img" aria-label="${window._fd.escHtml(tr("ct.payments"))}">${bars}</svg>`;
  }

  _row(c) {
    const e = window._fd.escHtml;
    const ended = c.status === "ended";
    const badges = [`<span class="badge">${e(tr(`ct.kind.${this._kindOf(c)}`))}</span>`];
    if (c.source === "manual") badges.push(`<span class="badge info">${e(tr("ct.manual"))}</span>`);
    if (ended) badges.push(`<span class="badge">${e(tr("ct.ended"))}</span>`);
    else if (c.status === "missing") badges.push(`<span class="badge due">${e(tr("ct.missing"))}</span>`);
    const notice = !ended && !NO_NOTICE.has(this._kindOf(c));
    if (notice && c.notice_due_soon) {
      const n = c.days_until_deadline;
      const left = n <= 0 ? tr("ct.days_today") : n === 1 ? tr("ct.days_one") : tr("ct.days_left", { n });
      badges.push(`<span class="badge due">${e(tr("ct.notice_by", { date: this._date(c.next_deadline) }))} · ${e(left)}</span>`);
    } else if (notice && c.next_deadline) {
      badges.push(`<span class="badge">${e(tr("ct.next_deadline"))}: ${e(this._date(c.next_deadline, true))}</span>`);
    }
    const pc = c.price_change;
    if (pc && pc.change_pct != null) {
      const pct = (pc.change_pct > 0 ? "+" : "") + String(pc.change_pct).replace(".", ",");
      const tip = tr("ct.price_change", { previous: this._m(Math.abs(pc.previous), 2), last: this._m(Math.abs(pc.last), 2) });
      badges.push(`<span class="badge info" data-tip="${e(tip)}" aria-label="${e(tip)}">${pc.increase ? "▲ " : "▼ "}${e(pct.replace(/^\+/, "+") + " %")}</span>`);
    }
    if (!ended && c.pauses_recent > 0) badges.push(`<span class="badge">${e(tr("ct.paused", { n: c.pauses_recent }))}</span>`);
    if (c.special_termination_available) badges.push(`<span class="badge ok">${e(tr("ct.special"))}</span>`);
    // Auto labels are not stored on the contract; the price / special-termination ones already have badges above.
    const own = (c.labels || []).map((id) => window._fd.labelChip(id, this._labels, "own"));
    if (own.length) badges.push(...own);
    const interval = tr(`ct.interval.${c.interval}`);
    const next = c.next_expected ? tr("ct.next", { date: this._date(c.next_expected) }) : tr("ct.next_open");
    const sub = [interval, ended ? "" : next, this._ownerLabel(c.owner)].filter(Boolean).join(" · ");
    const inner = `<div class="l1"><span class="nm"><i aria-hidden="true">${this._catIcon(c.category)}</i><span>${e(c.display_name || c.creditor)}</span></span>
  <span class="amt"><b>${e(tr("ct.per_year", { amount: this._m(c.annual_cost) }))}</b><span class="muted">${e(tr("ct.per_month", { amount: this._m(c.monthly_equivalent, 2) }))}</span></span></div>
<div class="l2">${badges.join("")}</div>
<div class="l3"><span class="muted">${e(sub)}</span>${this._spark(c)}</div>`;
    return this._isAdmin && c.contract
      ? `<button type="button" class="ct${ended ? " ended" : ""}" data-edit="${e(c.id)}" aria-label="${e(tr("ct.edit") + ": " + (c.display_name || c.creditor))}">${inner}</button>`
      : `<div class="ct${ended ? " ended" : ""}">${inner}</div>`;
  }

  _reservesHtml() {
    const e = window._fd.escHtml;
    const r = this._reserves;
    if (!r) return "";
    const items = r.items || [];
    const owners = Object.entries(r.by_owner || {});
    let h = `<section class="card"><h3>${e(tr("rs.title"))}</h3><p class="muted" style="margin:0 0 6px">${e(tr("rs.intro"))}</p>`;
    if (!items.length) h += `<p class="muted">${e(tr("rs.empty"))}</p>`;
    else {
      h += items.map((i) => `<div class="rw"><span><b>${e(i.display_name || i.creditor)}</b><span class="muted">${e(i.type === "settlement" ? tr("rs.settlement") : tr(`ct.interval.${i.interval}`))} · ${e(i.next_due ? tr("rs.due", { date: this._date(i.next_due) }) : tr("ct.next_open"))}</span></span>
        <b>${e(tr("rs.month", { amount: this._m(i.monthly_reserve, 2) }))}</b></div>`).join("");
      h += `<div class="rw"><span><b>${e(tr("rs.total", { amount: this._m(r.total_monthly, 2) }))}</b>${owners.length > 1
        ? `<span class="muted">${owners.map(([o, v]) => e(tr("rs.owner_total", { owner: this._ownerLabel(o), amount: this._m(v, 2) }))).join(" · ")}</span>` : ""}</span></div>`;
    }
    h += `</section>`;
    const cov = this._coverage;
    if (cov && (cov.accounts || []).length) {
      h += `<section class="card"><h3>${e(tr("rs.coverage"))}</h3>`;
      h += cov.accounts.map((a) => {
        const short = a.status === "shortfall";
        const unknown = a.status === "unknown";
        const pct = unknown || !a.virtual_total ? 0 : Math.min(100, Math.max(0, (a.real_balance / a.virtual_total) * 100));
        const badge = unknown ? `<span class="badge">${e(tr("rs.unknown"))}</span>`
          : short ? `<span class="badge due">${e(tr("rs.shortfall", { amount: this._m(a.top_up, 2) }))}</span>`
            : `<span class="badge ok">${e(tr("rs.covered"))}</span>`;
        return `<div class="cov${short ? " short" : ""}"><div class="l1"><b>${e(a.name)}</b>${badge}</div>
          <div class="bar" role="img" aria-label="${Math.round(pct)} %"><i style="width:${pct}%"></i></div>
          <div class="muted">${e(tr("rs.virtual", { amount: this._m(a.virtual_total, 2) }))}${a.real_balance != null ? " · " + e(tr("rs.real", { amount: this._m(a.real_balance, 2) })) : ""}${short ? " · " + e(tr("rs.topup", { amount: this._m(a.top_up, 2) })) : ""}</div></div>`;
      }).join("");
      if (cov.unassigned_pots) h += `<p class="muted">${e(tr("rs.unassigned", { n: cov.unassigned_pots }))}</p>`;
      h += `</section>`;
    }
    if (this._accounts.length) {
      h += `<section class="card"><h3>${e(tr("rs.accounts"))}</h3><p class="muted" style="margin:0 0 4px">${e(tr("rs.accounts_hint"))}</p>`;
      h += this._accounts.map((a) => `<div class="rw"><span><b>${e(a.name)}</b><span class="muted">${e(a.institution)}</span></span>
        <span class="hit"><button type="button" class="sw" role="switch" aria-checked="${a.savings}" data-sav="${e(a.key)}" aria-label="${e(tr("rs.savings") + ": " + a.name)}" data-tip="${e(tr("rs.savings"))}"></button></span></div>`).join("");
      h += `</section>`;
    }
    return h;
  }

  // ---- edit sheet ---------------------------------------------------------
  _defaultsFor(c, kind) {
    const k = c.contract || {};
    const byKind = k.defaults_by_kind || {};
    // Kinds without notice keep the contract terms for a later switch back.
    const d = byKind[kind] || byKind.contract || k.defaults;
    if (d) return { ...d };
    const [term, renewal, notice, unit] = CAT_DEFAULTS[c.category] || FALLBACK_DEFAULTS;
    return { min_term_months: term, renewal_months: renewal, notice_value: notice, notice_unit: unit, notice_reference: "end_of_term" };
  }

  _openSheet(id) {
    const c = (this._items || []).find((x) => x.id === id);
    if (!c || !c.contract) return;
    const k = c.contract;
    this._add = null;
    this._sheet = {
      id, c, error: "", saving: false, touched: new Set(),
      d: {
        start: k.start || c.first_seen || "",
        min_term_months: k.min_term_months, renewal_months: k.renewal_months,
        notice_value: k.notice_value, notice_unit: k.notice_unit, notice_reference: k.notice_reference,
        owner: c.owner || "shared", special_termination: !!k.special_termination,
        kind: this._kindOf(c),
        plan_mode: c.plan_mode || "auto",
        plan_fixed_amount: c.plan_fixed_amount ?? "",
        labels: [...(c.labels || [])],
        usage_based: !!(c.settlement && c.settlement.usage_based),
        settlements: [...((k.stored || {}).settlements || [])],
        display_name: (k.stored || {}).display_name || "",
        category: c.category || "other",
        interval: c.interval,
      },
    };
    this._paintSheet();
    this.shadowRoot.querySelector("#sheet button, #sheet input")?.focus();
  }

  _closeSheet() {
    const back = this._sheet ? this._sheet.id : null;
    this._sheet = null;
    this._add = null;
    // keyboard users land back on the row they opened
    if (back) setTimeout(() => [...this.shadowRoot.querySelectorAll("[data-edit]")].find((b) => b.dataset.edit === back)?.focus(), 0);
    const el = this.shadowRoot.getElementById("sheet");
    if (el) el.innerHTML = "";
  }

  /** Expense areas a contract can sit in (no income, no transfers), the current one always included. */
  _categoryOptions(cur) {
    const keys = Object.keys(window._fd.CAT_LABELS || {}).filter((k) => !k.startsWith("income") && k !== "transfers");
    if (cur && !keys.includes(cur)) keys.push(cur);
    return keys;
  }

  _owners(s) {
    const set = new Set(["shared"]);
    for (const c of this._items || []) if (c.owner) set.add(c.owner);
    if (s.d.owner) set.add(s.d.owner);
    return [...set];
  }

  // ---- manual contracts (#117 D) -------------------------------------------
  _openAdd() {
    this._sheet = null;
    this._add = { step: "pick", error: "", saving: false, d: null };
    this._paintSheet();
    this.shadowRoot.querySelector("#sheet button")?.focus();
  }

  _pickTemplate(i) {
    const t = CHECKLIST[i];
    this._add.d = t
      ? { name: tr(`ct.add.t.${t.id}`), amount: "", interval: t.interval, kind: t.kind, category: t.category, start: "", owner: "shared" }
      : { name: "", amount: "", interval: "yearly", kind: "contract", category: "other", start: "", owner: "shared" };
    this._add.step = "form";
    this._paintSheet();
    this.shadowRoot.querySelector("#sheet input")?.focus();
  }

  /** A checklist entry whose word already shows up in a contract name counts as "found". */
  _found(t) {
    const names = (this._items || []).map((c) => String(c.display_name || c.creditor || "").toLowerCase());
    return t.words.some((w) => names.some((n) => n.includes(w)));
  }

  _paintAdd(el) {
    const a = this._add;
    const e = window._fd.escHtml;
    let inner;
    if (a.step === "pick") {
      inner = `<h3 id="addh">${e(tr("ct.add.title"))}</h3><p class="muted" style="margin:0 0 8px">${e(tr("ct.add.say"))}</p>
  <div class="opts" role="group" aria-labelledby="addh">${CHECKLIST.map((t, i) => {
        const found = this._found(t);
        return `<button type="button" data-pick="${i}"${found ? ` aria-describedby="found${i}"` : ""}>${e(tr(`ct.add.t.${t.id}`))}${found ? ` <span id="found${i}" class="muted">✓ ${e(tr("ct.add.found"))}</span>` : ""}</button>`;
      }).join("")}
    <button type="button" data-pick="-1">${e(tr("ct.add.other"))}</button></div>
  <div class="acts"><button type="button" class="btn ghost" data-act="cancel">${e(tr("ct.cancel"))}</button></div>`;
    } else {
      const d = a.d;
      const opt = (grp, val, label) => `<button type="button" role="radio" aria-checked="${d[grp] === val}" data-agrp="${grp}" data-val="${e(val)}">${e(label)}</button>`;
      inner = `<h3 id="addh">${e(tr("ct.add.title"))}</h3>
  <label for="a-name">${e(tr("ct.f.name"))}</label><input id="a-name" type="text" maxlength="80" autocomplete="off" data-af="name" value="${e(d.name)}">
  <label for="a-amt">${e(tr("ct.f.amount"))}</label><input id="a-amt" type="number" min="0" step="0.01" inputmode="decimal" data-af="amount" value="${e(String(d.amount))}">
  <div class="lbl" id="a-ivh">${e(tr("ct.f.interval"))}</div>
  <div class="opts" role="radiogroup" aria-labelledby="a-ivh">${Object.keys(PER_YEAR).map((iv) => opt("interval", iv, tr(`ct.interval.${iv}`))).join("")}</div>
  <div class="lbl" id="a-kh">${e(tr("ct.f.kind"))}</div>
  <div class="opts" role="radiogroup" aria-labelledby="a-kh">${KINDS.map((k) => opt("kind", k, tr(`ct.kind.${k}`))).join("")}</div>
  <label for="a-cat">${e(tr("ct.f.category"))}</label><select id="a-cat" data-af="category">${this._categoryOptions(d.category).map((k) => `<option value="${e(k)}"${k === d.category ? " selected" : ""}>${e(this._catLabel(k))}</option>`).join("")}</select>
  <label for="a-start">${e(tr("ct.f.start"))}</label><input id="a-start" type="date" data-af="start" min="2000-01-01" value="${e(d.start)}" aria-describedby="a-start-h">
  <div class="muted" id="a-start-h" style="margin-top:4px">${e(tr("ct.add.start_hint"))}</div>
  <div class="lbl" id="a-oh">${e(tr("ct.f.owner"))}</div>
  <div class="opts" role="radiogroup" aria-labelledby="a-oh">${this._owners({ d }).map((o) => opt("owner", o, this._ownerLabel(o))).join("")}</div>
  <div class="hint">${e(tr("ct.add.private"))}</div>
  <div class="err" role="alert">${e(a.error)}</div>
  <div class="acts"><button type="button" class="btn ghost" data-act="add-back">${e(tr("ct.add.back"))}</button>
    <button type="button" class="btn" data-act="add-save" ${a.saving ? "disabled" : ""}>${e(tr(a.saving ? "ct.saving" : "ct.add.save"))}</button></div>`;
    }
    el.innerHTML = `<div class="scrim" data-act="scrim"><div class="sheet" role="dialog" aria-modal="true" aria-labelledby="addh" tabindex="-1">${inner}</div></div>`;
  }

  async _saveAdd() {
    const a = this._add;
    if (!a || a.saving || !a.d) return;
    const d = a.d;
    const amount = Number(d.amount);
    // a validation error puts the focus on the field to fix
    const invalid = (key, sel) => { a.error = tr(key); this._paintSheet(); this.shadowRoot.querySelector(sel)?.focus(); };
    if (!String(d.name).trim()) return invalid("ct.add.need_name", "#a-name");
    if (!(amount > 0)) return invalid("ct.add.need_amount", "#a-amt");
    a.saving = true;
    a.error = "";
    this._paintSheet();
    try {
      const body = { name: String(d.name).trim(), amount, interval: d.interval, kind: d.kind, category: d.category, owner: d.owner };
      if (d.start) body.start = d.start;
      const item = await this._hass.callApi("POST", `${DOMAIN}/contracts`, body);
      this._items = [...(this._items || []), item];
      this._closeSheet();
      this._focusAfter = `[data-edit="${CSS.escape(item.id)}"]`; // the new row
      this._render();
      this._toast(tr("ct.add.done"), "success");
      this._reloadReserves();
    } catch (err) {
      a.saving = false;
      const code = (err && err.body && err.body.error) || "";
      const field = { manual_duplicate: "#a-name", invalid_name: "#a-name", invalid_amount: "#a-amt", invalid_start: "#a-start" }[code];
      const known = code && tr(`ct.add.err.${code}`) !== `ct.add.err.${code}`;
      const detail = (err && err.body && err.body.detail) || code;
      a.error = known ? tr(`ct.add.err.${code}`) : detail ? `${tr("ct.save_failed")}: ${detail}` : tr("ct.save_failed");
      this._paintSheet();
      this.shadowRoot.querySelector(field || '[data-act="add-save"]')?.focus();
    }
  }

  async _deleteManual() {
    const s = this._sheet;
    if (!s || s.saving) return;
    if (!window.confirm(tr("ct.delete_confirm", { name: s.c.display_name || s.c.creditor }))) return;
    s.saving = true;
    this._paintSheet();
    try {
      await this._hass.callApi("DELETE", `${DOMAIN}/contracts/${encodeURIComponent(s.id)}`);
      this._items = this._items.filter((c) => c.id !== s.id);
      this._sheet = null;
      this._closeSheet();
      this._render();
      this._toast(tr("ct.deleted"), "success");
      this._reloadReserves();
    } catch (err) {
      s.saving = false;
      s.error = tr("ct.save_failed");
      this._paintSheet();
    }
  }

  async _reloadReserves() {
    try {
      const r = await this._hass.callApi("GET", `${DOMAIN}/reserves`);
      this._reserves = (r && r.reserves) || null;
      this._coverage = (r && r.coverage) || null;
      this._render();
    } catch (e) { /* reserves stay as they were */ }
  }

  /** Repaint the open sheet; the focused control keeps the focus (QA #117). */
  _paintSheet() {
    const keep = this._focusSel();
    this._paintSheetRaw();
    if (keep && !this.shadowRoot.activeElement) this.shadowRoot.querySelector(keep)?.focus();
    this._keepFocusInSheet();
  }

  _paintSheetRaw() {
    if (this._add) {
      const host = this.shadowRoot.getElementById("sheet");
      if (host) this._paintAdd(host);
      return;
    }
    const s = this._sheet;
    const el = this.shadowRoot.getElementById("sheet");
    if (!s || !el) return;
    const e = window._fd.escHtml;
    const d = s.d;
    const def = this._defaultsFor(s.c, d.kind);
    const notice = !NO_NOTICE.has(d.kind);
    const manual = s.c.source === "manual";
    const opt =(grp, val, label, cur) => `<button type="button" role="radio" aria-checked="${cur === val}" data-grp="${grp}" data-val="${e(val)}">${e(label)}</button>`;
    el.innerHTML = `<div class="scrim" data-act="scrim"><div class="sheet" role="dialog" aria-modal="true" aria-label="${e(tr("ct.edit"))}" tabindex="-1">
  <h3>${e(s.c.display_name || s.c.creditor)}</h3>
  <p class="muted" style="margin:0">${e(this._catLabel(s.c.category))} · ${e(tr(`ct.interval.${s.c.interval}`))}${manual ? ` · ${e(tr("ct.manual"))}` : ""}</p>
  <label for="f-name">${e(tr("ct.f.name"))}</label><input id="f-name" type="text" maxlength="80" autocomplete="off" data-f="display_name" value="${e(d.display_name)}" placeholder="${e(s.c.display_name_detected || s.c.creditor || "")}">
  <label for="f-cat">${e(tr("ct.f.category"))}</label><select id="f-cat" data-f="category">${this._categoryOptions(d.category).map((k) => `<option value="${e(k)}"${k === d.category ? " selected" : ""}>${e(this._catLabel(k))}</option>`).join("")}</select>
  <div class="lbl" id="ivh">${e(tr("ct.f.interval"))}</div>
  <div class="opts" role="radiogroup" aria-labelledby="ivh">${Object.keys(PER_YEAR).map((iv) => opt("interval", iv, tr(`ct.interval.${iv}`), d.interval)).join("")}</div>
  ${s.c.interval_detected && d.interval !== s.c.interval_detected ? `<div class="hint">${e(tr("ct.interval_detected", { interval: tr(`ct.interval.${s.c.interval_detected}`) }))}</div>` : ""}
  <div class="lbl">${e(tr("ct.f.kind"))}</div>
  <div class="opts" role="radiogroup" aria-label="${e(tr("ct.f.kind"))}">${KINDS.map((k) => opt("kind", k, tr(`ct.kind.${k}`), d.kind)).join("")}</div>
  ${manual ? "" : `<div class="lbl">${e(tr("ct.f.plan_mode"))}</div>
  <div class="opts" role="radiogroup" aria-label="${e(tr("ct.f.plan_mode"))}">${PLAN_MODES.map((m) => opt("plan_mode", m, tr(`ct.mode.${m}`), d.plan_mode)).join("")}</div>`}
  ${d.plan_mode === "fixed" ? `<label for="f-fixed">${e(tr(manual ? "ct.f.amount" : "ct.f.fixed"))}</label><input id="f-fixed" type="number" min="0" step="0.01" data-f="plan_fixed_amount" value="${e(String(d.plan_fixed_amount ?? ""))}">` : ""}
  <div class="hint" id="planprev">${e(this._previewText(s))}</div>
  ${notice ? `<label for="f-start">${e(tr("ct.f.start"))}</label><input id="f-start" type="date" data-f="start" value="${e(d.start)}">
  <label for="f-term">${e(tr("ct.f.min_term"))}</label><input id="f-term" type="number" min="0" max="240" data-f="min_term_months" value="${d.min_term_months ?? ""}">
  <label for="f-ren">${e(tr("ct.f.renewal"))}</label><input id="f-ren" type="number" min="1" max="240" data-f="renewal_months" value="${d.renewal_months ?? ""}">
  <div class="lbl">${e(tr("ct.f.notice"))}</div>
  <div class="nrow"><input type="number" min="0" max="3650" data-f="notice_value" value="${d.notice_value ?? ""}" aria-label="${e(tr("ct.f.notice"))}">
    <div class="opts" role="radiogroup">${["days", "weeks", "months"].map((u) => opt("notice_unit", u, tr("ct.unit." + u), d.notice_unit)).join("")}</div></div>
  <div class="lbl">${e(tr("ct.f.reference"))}</div>
  <div class="opts" role="radiogroup">${["end_of_term", "end_of_month"].map((u) => opt("notice_reference", u, tr("ct.ref." + u), d.notice_reference)).join("")}</div>` : `<div class="hint">${e(tr("ct.kind.no_notice"))}</div>`}
  <div class="lbl">${e(tr("ct.f.owner"))}</div>
  <div class="opts" role="radiogroup">${this._owners(s).map((o) => opt("owner", o, this._ownerLabel(o), d.owner)).join("")}</div>
  ${notice ? `<div class="rw" style="margin-top:8px"><span><b>${e(tr("ct.f.special"))}</b>${s.c.contract.special_termination_prefilled ? `<span class="muted">${e(tr("ct.special_prefilled"))}</span>` : ""}</span>
    <span class="hit"><button type="button" class="sw" role="switch" aria-checked="${d.special_termination}" data-grp="special" aria-label="${e(tr("ct.f.special"))}"></button></span></div>
  <div class="hint">${e(tr("ct.defaults", { cat: d.kind === "contract" ? this._catLabel(s.c.category) : tr(`ct.kind.${d.kind}`), term: def.min_term_months, renewal: def.renewal_months, notice: def.notice_value, unit: tr("ct.unit." + def.notice_unit) }))}</div>` : ""}
  ${this._settlementHtml(s)}
  ${this._structureHtml(s)}
  <div class="lbl" id="lbh">${e(tr("lb.title"))}</div>
  <div class="opts" role="group" aria-labelledby="lbh">${(this._labels || []).filter((l) => l.kind !== "auto").map((l) => `<button type="button" role="checkbox" aria-checked="${d.labels.includes(l.id)}" data-lbl="${e(l.id)}">${e(window._fd.labelName(l.id, this._labels))}</button>`).join("") || `<span class="muted">${e(tr("lb.none"))}</span>`}</div>
  <div class="err" id="sheeterr" role="alert">${e(s.error)}</div>
  <div class="acts">${manual ? `<button type="button" class="btn ghost" data-act="delete" ${s.saving ? "disabled" : ""}>${e(tr("ct.delete"))}</button>` : ""}<button type="button" class="btn ghost" data-act="reset">${e(tr("ct.reset"))}</button>
    <button type="button" class="btn ghost" data-act="cancel">${e(tr("ct.cancel"))}</button>
    <button type="button" class="btn" data-act="save" ${s.saving ? "disabled" : ""}>${e(tr(s.saving ? "ct.saving" : "ct.save"))}</button></div>
</div></div>`;
  }

  _settlementHtml(s) {
    const st = s.c.settlement;
    if (!st) return ""; // aggregate view: no amounts per payment
    const e = window._fd.escHtml;
    const d = s.d;
    const money = (v) => this._m(Math.abs(v), 2);
    let h = `<div class="rw" style="margin-top:8px"><span><b>${e(tr("st.usage"))}</b>${st.usage_based_detected ? `<span class="muted">${e(tr("st.detected"))}</span>` : ""}</span>
    <span class="hit"><button type="button" class="sw" role="switch" aria-checked="${d.usage_based}" data-grp="usage" aria-label="${e(tr("st.usage"))}"></button></span></div>`;
    if (!d.usage_based) return h;
    const manual = new Set(d.settlements);
    const stored = new Set((s.c.contract.stored || {}).settlements || []);
    const dirty = manual.size !== stored.size || [...manual].some((k) => !stored.has(k)) || d.usage_based !== st.usage_based;
    // keyword hits stay; manual ones follow the sheet's current selection
    const pool = [...st.history, ...st.candidates];
    const rows = pool.filter((x) => (x.source === "keyword") || (x.key && manual.has(x.key)))
      .sort((a, b) => (a.date < b.date ? -1 : 1));
    const loose = st.candidates.concat(st.history.filter((x) => x.source === "manual"))
      .filter((x) => x.key && !manual.has(x.key));
    const label = (x) => tr(x.amount < 0 ? "st.back" : "st.refund", { amount: money(x.amount) });
    h += `<div class="lbl" id="sth">${e(tr("st.title"))}</div><div role="group" aria-labelledby="sth">`;
    h += rows.length ? rows.map((x) => `<div class="rw"><span><b>${e(label(x))}</b><span class="muted">${e(this._date(x.date, true))} · ${e(tr(x.source === "keyword" ? "st.src.keyword" : "st.src.manual"))}</span></span>${x.source === "keyword" ? ""
      : `<span class="hit"><button type="button" class="btn ghost" data-stl-rm="${e(x.key)}" aria-label="${e(`${tr("st.remove")}: ${label(x)}, ${this._date(x.date, true)}`)}">✕</button></span>`}</div>`).join("")
      : `<p class="muted" style="margin:4px 0">${e(tr("st.none"))}</p>`;
    h += `</div>`;
    const x = st.expected;
    if (dirty) h += `<div class="hint">${e(tr("st.recalc"))}</div>`;
    else if (x) {
      const key = x.amount > 0 ? "st.expected_back" : x.amount < 0 ? "st.expected_refund" : "st.expected_none";
      h += `<div class="hint">${e(tr(key, { amount: money(x.amount), date: this._date(x.next_due, true), month: this._m(x.monthly_reserve, 2) }))}${x.advance_step ? ` · ${e(tr("st.step", { step: (x.advance_step > 0 ? "+" : "−") + money(x.advance_step) }))}` : ""}</div>`;
    }
    if (loose.length) {
      h += `<div class="lbl" id="stc">${e(tr("st.candidates"))}</div><div role="group" aria-labelledby="stc">`;
      h += loose.map((c) => `<div class="rw"><span><b>${e(label(c))}</b><span class="muted">${e(this._date(c.date, true))}</span></span>
        <span class="hit"><button type="button" class="btn ghost" data-stl-add="${e(c.key)}" aria-label="${e(`${tr("st.assign")}: ${label(c)}, ${this._date(c.date, true)}`)}">${e(tr("st.assign"))}</button></span></div>`).join("");
      h += `</div>`;
    }
    return h;
  }

  // ---- merge / split / booking assignment (#117 E, F) ------------------------
  // These act right away (own endpoint), separate from "Speichern".
  _structureHtml(s) {
    const e = window._fd.escHtml;
    const c = s.c;
    const busy = s.structBusy ? " disabled" : "";
    const money = (v) => this._m(Math.abs(v), 2);
    let h = `<div class="lbl" id="sth2">${e(tr("ct.st.title"))}</div><div role="group" aria-labelledby="sth2"><p class="muted" style="margin:0 0 4px">${e(tr("ct.st.say"))}</p>`;
    if (c.source !== "manual") {
      for (const m of c.merged_from || []) {
        h += `<div class="rw"><span><b>${e(m.name)}</b><span class="muted">${e(tr("ct.st.merged"))}</span></span>
        <span class="hit"><button type="button" class="btn ghost" data-st="unmerge" data-sid="${e(m.id)}"${busy}>${e(tr("ct.st.unmerge"))}</button></span></div>`;
      }
      // only what the server accepts: same direction, same rhythm (merge_*_mismatch otherwise)
      const others = (this._items || []).filter((x) => x.id !== c.id && x.source !== "manual"
        && x.interval === c.interval && (x.direction || "out") === (c.direction || "out"));
      if (others.length) {
        h += `<label for="f-merge">${e(tr("ct.st.merge_with"))}</label><div class="nrow" style="grid-template-columns:1fr auto">
        <select id="f-merge">${others.map((x) => `<option value="${e(x.id)}"${x.id === s.mergeWith ? " selected" : ""}>${e(x.display_name || x.creditor)} · ${e(tr(`ct.interval.${x.interval}`))}</option>`).join("")}</select>
        <button type="button" class="btn ghost" data-st="merge"${busy}>${e(tr("ct.st.merge"))}</button></div>`;
      } else {
        h += `<p class="muted" style="margin:4px 0">${e(tr("ct.st.merge_none", { interval: tr(`ct.interval.${c.interval}`) }))}</p>`;
      }
      h += `<div class="opts" style="margin-top:8px">${c.split_by
        ? `<button type="button" data-st="unsplit"${busy}>${e(tr("ct.st.unsplit"))}</button>`
        : `<button type="button" data-st="split" data-by="reference"${busy}>${e(tr("ct.st.split_ref"))}</button><button type="button" data-st="split" data-by="amount"${busy}>${e(tr("ct.st.split_amount"))}</button>`}</div>`;
    }
    const assigned = c.assigned || [];
    h += `<div class="lbl" id="asg">${e(tr("ct.st.assigned"))}</div>`;
    h += assigned.length ? assigned.map((a) => `<div class="rw"><span><b>${e(a.name || "—")}</b><span class="muted">${e(this._date(a.date, true))} · ${e(money(a.amount))}</span></span>
      <span class="hit"><button type="button" class="btn ghost" data-st="unassign" data-key="${e(a.key)}" aria-label="${e(`${tr("ct.st.unassign")}: ${a.name}, ${this._date(a.date, true)}`)}"${busy}>✕</button></span></div>`).join("")
      : `<p class="muted" style="margin:4px 0">${e(tr("ct.st.none"))}</p>`;
    h += `<label for="f-bq">${e(tr("ct.st.search"))}</label><input id="f-bq" type="search" autocomplete="off" value="${e(s.q || "")}" placeholder="${e(tr("ct.st.search_ph"))}">`;
    const own = new Set(c.ledger_ids || []);
    const hits = (s.hits || []).filter((x) => x.ledger_id && !own.has(x.ledger_id));
    if (s.hits) {
      h += hits.length ? hits.map((x) => {
        const who = x.creditor || x.debtor || x.description || "";
        return `<div class="rw"><span><b>${e(who)}</b><span class="muted">${e(this._date(x.date, true))} · ${e(money(Number(x.amount)))}${x.contract_name ? ` · ${e(tr("ct.st.now_in", { name: x.contract_name }))}` : ""}</span></span>
        <span class="hit"><button type="button" class="btn ghost" data-st="assign" data-key="${e(x.ledger_id)}" aria-label="${e(`${tr("ct.st.assign")}: ${who}, ${this._date(x.date, true)}`)}"${busy}>${e(tr("ct.st.assign"))}</button></span></div>`;
      }).join("") : `<p class="muted" style="margin:4px 0">${e(tr("ct.st.no_hits"))}</p>`;
    }
    return `${h}<div class="err" role="alert">${e(s.structError || "")}</div></div>`;
  }

  _search(q) {
    const s = this._sheet;
    if (!s) return;
    s.q = q;
    clearTimeout(this._qTimer);
    if (q.trim().length < 2) { s.hits = null; return this._paintKeep("#f-bq"); }
    this._qTimer = setTimeout(async () => {
      try {
        const r = await this._hass.callApi("GET", `${DOMAIN}/transactions?q=${encodeURIComponent(q.trim())}&limit=8`);
        if (this._sheet !== s || s.q !== q) return;
        s.hits = (r && r.transactions) || (r && r.items) || [];
      } catch (_) {
        if (this._sheet !== s) return;
        s.hits = [];
      }
      this._paintKeep("#f-bq");
    }, 300);
  }

  /** Repaint the sheet and put the focus (and caret) back where it was. */
  _paintKeep(sel) {
    const sc = this.shadowRoot.querySelector(".sheet");
    const top = sc ? sc.scrollTop : 0;
    this._paintSheet();
    const sc2 = this.shadowRoot.querySelector(".sheet");
    if (sc2) sc2.scrollTop = top;
    const el = sel && this.shadowRoot.querySelector(sel);
    if (el) {
      el.focus();
      if (el.setSelectionRange && el.type === "search") el.setSelectionRange(el.value.length, el.value.length);
    }
    this._keepFocusInSheet();
  }

  /** A disabled or vanished control drops the focus to <body>, where Escape no longer reaches the
   *  sheet: park it on the dialog itself instead. */
  _keepFocusInSheet() {
    if (!this.shadowRoot.activeElement) this.shadowRoot.querySelector("#sheet .sheet")?.focus();
  }

  async _structure(action, data) {
    const s = this._sheet;
    if (!s || s.structBusy) return;
    const from = this._focusSel();
    s.structBusy = true;
    s.structError = "";
    this._paintKeep(from);
    try {
      const r = await this._hass.callApi("POST", `${DOMAIN}/contract_overrides`, { action, ...data });
      const all = (r && r.contracts) || [];
      this._items = all.filter((c) => !c.candidate);
      this._candidates = all.filter((c) => c.candidate && c.status !== "ended");
      this._toast(tr(`ct.st.done.${action}`), "success");
      const still = this._items.find((c) => c.id === s.id);
      if (still) {
        // The sheet shows the new structure, the unsaved edits stay (QA #117).
        const keep = { d: s.d, touched: s.touched, reset: s.reset, q: s.q, hits: s.hits };
        this._openSheet(s.id);
        Object.assign(this._sheet, keep);
        const next = {
          assign: "#f-bq", unassign: "#f-bq", merge: "#f-merge", unmerge: "#f-merge",
          split: '[data-st="unsplit"]', unsplit: '[data-st="split"]',
        }[action];
        this._focusAfter = next;
        this._render(); // the control may be gone (last merge undone): the sheet keeps the focus
      } else {
        this._closeSheet();
        this._focusAfter = '[data-act="add"]';
        this._render();
      }
      this._reloadReserves(); // re-renders later; _render keeps the focus
    } catch (err) {
      s.structBusy = false;
      const code = err && err.body && err.body.error;
      s.structError = code && tr(`ct.st.err.${code}`) !== `ct.st.err.${code}` ? tr(`ct.st.err.${code}`) : tr("ct.save_failed");
      this._paintKeep(from);
    }
  }

  _previewText(s) {
    const plan = planAmount(s.c.amounts, s.d.plan_mode, s.d.plan_fixed_amount);
    const year = plan * (PER_YEAR[s.d.interval || s.c.interval] || 12);
    return tr(s.d.plan_mode === "auto" ? "ct.plan_preview_auto" : "ct.plan_preview",
      { month: this._m(year / 12, 2), year: this._m(year, 2) });
  }

  async _save() {
    const s = this._sheet;
    if (!s || s.saving) return;
    const k = s.c.contract;
    const d = s.d;
    const num = (v) => (v === "" || v == null ? null : Number(v));
    const body = {};
    // Only fields the user edited and that differ from what the contract shows
    // are sent: terms prefilled by a kind switch must not overwrite stored ones.
    const same = (a, b) => (a ?? null) === (b ?? null);
    const next = {
      start: d.start || null,
      min_term_months: num(d.min_term_months), renewal_months: num(d.renewal_months), notice_value: num(d.notice_value),
      notice_unit: d.notice_unit, notice_reference: d.notice_reference, special_termination: !!d.special_termination,
    };
    for (const f of Object.keys(next)) {
      const before = f === "start" ? (k.start || s.c.first_seen || null) : k[f];
      if (s.touched.has(f) && !same(next[f], before)) body[f] = next[f];
    }
    const name = String(d.display_name || "").trim();
    if (name !== ((k.stored || {}).display_name || "")) body.display_name = name || null;
    if (d.category !== (s.c.category || "other")) body.category = d.category;
    // The detected rhythm is stored as null, so a later better detection still applies.
    if (d.interval !== s.c.interval) body.interval = d.interval === s.c.interval_detected ? null : d.interval;
    const prevLabels = s.c.labels || [];
    if (d.labels.length !== prevLabels.length || d.labels.some((id) => !prevLabels.includes(id))) body.labels = d.labels.length ? d.labels : null;
    if (d.owner !== (s.c.owner || "shared")) body.owner = d.owner;
    const st = s.c.settlement;
    if (st) {
      if (d.usage_based !== st.usage_based) body.usage_based = d.usage_based === st.usage_based_detected ? null : d.usage_based;
      const prev = (k.stored || {}).settlements || [];
      if (d.settlements.length !== prev.length || d.settlements.some((x) => !prev.includes(x))) body.settlements = d.settlements.length ? d.settlements : null;
    }
    const mode = d.plan_mode === "auto" ? null : d.plan_mode;
    const fixed = mode === "fixed" ? num(d.plan_fixed_amount) : null;
    if (mode === "fixed" && fixed == null) {
      s.error = tr("ct.fixed_missing");
      this._paintSheet();
      return;
    }
    if ((s.c.plan_mode || "auto") !== d.plan_mode || (mode === "fixed" && fixed !== s.c.plan_fixed_amount)) {
      body.plan_mode = mode;
      body.plan_fixed_amount = fixed;
    }
    // The suggested kind is stored as null, so a better suggestion later still applies.
    if (d.kind !== this._kindOf(s.c)) body.kind = d.kind === s.c.kind_suggested ? null : d.kind;
    if (s.reset) {
      // After "reset": fields still at the kind's default go back to null (= follow the default).
      const def = this._defaultsFor(s.c, d.kind);
      for (const f of Object.keys(def)) body[f] = next[f] === def[f] ? null : next[f];
      if (d.kind === s.c.kind_suggested && (s.c.contract.stored || {}).kind) body.kind = null;
    }
    s.saving = true;
    this._paintSheet();
    try {
      const upd = await this._hass.callApi("PUT", `${DOMAIN}/contracts/${encodeURIComponent(s.id)}`, body);
      this._items = this._items.map((c) => (c.id === s.id ? { ...c, ...upd } : c));
      this._closeSheet();
      this._render();
      this._toast(tr("ct.saved"), "success");
      this._reloadReserves();
    } catch (err) {
      s.saving = false;
      const detail = (err && err.body && (err.body.detail || err.body.error)) || "";
      s.error = detail ? `${tr("ct.save_failed")}: ${detail}` : tr("ct.save_failed");
      this._paintSheet();
    }
  }

  async _toggleSavings(key) {
    const a = this._accounts.find((x) => x.key === key);
    if (!a) return;
    const want = !a.savings;
    a.savings = want;
    this._render();
    try {
      await this._hass.callApi("PUT", `${DOMAIN}/accounts/${encodeURIComponent(key)}/savings`, { savings: want });
    } catch (e) {
      a.savings = !want;
      this._render();
      this._toast(tr("rs.savings_failed"), "error");
    }
  }

  _toast(message, type) {
    this.dispatchEvent(new CustomEvent("fd-toast", { bubbles: true, composed: true, detail: { message, type } }));
  }

  _wire() {
    const sh = this.shadowRoot;
    sh.addEventListener("click", (ev) => {
      const t = ev.target.closest("button, [data-act]");
      if (!t) return;
      const s = this._sheet;
      if (t.dataset.edit) return this._openSheet(t.dataset.edit);
      if (t.dataset.sav) return this._toggleSavings(t.dataset.sav);
      if (t.dataset.review) return this._review(t.dataset.id, t.dataset.review);
      if (t.dataset.kind) { this._kind = t.dataset.kind; return this._render(); }
      if ((t.dataset.stlAdd || t.dataset.stlRm) && s) {
        const key = t.dataset.stlAdd || t.dataset.stlRm;
        s.d.settlements = s.d.settlements.filter((x) => x !== key);
        if (t.dataset.stlAdd) s.d.settlements.push(key);
        this._paintSheet();
        return this.shadowRoot.querySelector("[data-grp=usage]")?.focus();
      }
      if (t.dataset.lbl && s) {
        const i = s.d.labels.indexOf(t.dataset.lbl);
        if (i >= 0) s.d.labels.splice(i, 1); else s.d.labels.push(t.dataset.lbl);
        this._paintSheet();
        return [...this.shadowRoot.querySelectorAll("[data-lbl]")].find((b) => b.dataset.lbl === t.dataset.lbl)?.focus();
      }
      if (t.dataset.st && s) {
        const st = t.dataset.st;
        if (st === "merge") {
          const src = this.shadowRoot.getElementById("f-merge");
          return src && src.value && this._structure("merge", { target: s.id, source: src.value });
        }
        if (st === "unmerge") return this._structure("unmerge", { target: s.id, source: t.dataset.sid });
        if (st === "split") return this._structure("split", { series_id: s.id, by: t.dataset.by });
        if (st === "unsplit") return this._structure("unsplit", { series_id: s.id });
        if (st === "assign") return this._structure("assign", { booking: t.dataset.key, series_id: s.id });
        if (st === "unassign") return this._structure("unassign", { booking: t.dataset.key });
      }
      if (t.dataset.pick !== undefined && this._add) return this._pickTemplate(Number(t.dataset.pick));
      if (t.dataset.agrp && this._add && this._add.d) {
        const { agrp, val } = t.dataset;
        this._add.d[agrp] = val;
        this._paintSheet();
        return [...this.shadowRoot.querySelectorAll("[data-agrp]")].find((b) => b.dataset.agrp === agrp && b.dataset.val === val)?.focus();
      }
      if (t.dataset.grp && s) {
        const grp = t.dataset.grp;
        if (grp === "special") s.d.special_termination = !s.d.special_termination;
        else if (grp === "usage") s.d.usage_based = !s.d.usage_based;
        else if (grp === "kind" && s.d.kind !== t.dataset.val) {
          // Untouched terms the user never stored follow the new kind's defaults.
          const def = this._defaultsFor(s.c, t.dataset.val);
          const stored = s.c.contract.stored || {};
          for (const f of TERM_FIELDS) if (!s.touched.has(f) && stored[f] == null) s.d[f] = def[f];
          s.d.kind = t.dataset.val;
        } else s.d[grp] = t.dataset.val;
        if (grp !== "kind" && grp !== "owner" && grp !== "plan_mode" && grp !== "usage") s.touched.add(grp === "special" ? "special_termination" : grp);
        return this._paintSheet();
      }
      switch (t.dataset.act) {
        case "retry": this.load(); break;
        case "cancel": this._closeSheet(); break;
        case "scrim": if (ev.target === t) this._closeSheet(); break;
        case "save": this._save(); break;
        case "add": this._openAdd(); break;
        case "add-save": this._saveAdd(); break;
        case "add-back": if (this._add) { this._add.step = "pick"; this._add.error = ""; this._paintSheet(); this.shadowRoot.querySelector("#sheet button")?.focus(); } break;
        case "delete": this._deleteManual(); break;
        case "reset": {
          if (!s) break;
          // null = back to the kind's default; the sheet shows those values right away.
          const kind = s.c.kind_suggested || s.d.kind;
          Object.assign(s.d, this._defaultsFor(s.c, kind), { kind });
          s.reset = true;
          this._paintSheet();
          break;
        }
        default: break;
      }
    });
    sh.addEventListener("input", (ev) => {
      const af = ev.target.dataset && ev.target.dataset.af;
      if (af && this._add && this._add.d) { this._add.d[af] = ev.target.value; return; }
      if (ev.target.id === "f-bq" && this._sheet) return this._search(ev.target.value);
      if (ev.target.id === "f-merge" && this._sheet) { this._sheet.mergeWith = ev.target.value; return; }
      const f = ev.target.dataset && ev.target.dataset.f;
      if (f && this._sheet) {
        this._sheet.d[f] = ev.target.value;
        this._sheet.touched.add(f);
        const prev = this.shadowRoot.getElementById("planprev");
        if (prev && f === "plan_fixed_amount") prev.textContent = this._previewText(this._sheet);
      }
    });
    sh.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && (this._sheet || this._add)) { ev.stopPropagation(); this._closeSheet(); }
      if (ev.key === "Enter" && ev.target.id === "f-bq") ev.preventDefault();
    });
  }
}

window._fd.defineOnce("fd-contracts", FdContracts);
