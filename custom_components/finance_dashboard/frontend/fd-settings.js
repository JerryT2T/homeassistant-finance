/**
 * fd-settings — household settings (admin only; renders nothing otherwise).
 *
 * Modes
 *   mode="page"            the body of the settings subpage: every section stacked, a section
 *                          nav (left column on desktop, scroll row on phones). `section` scrolls to it.
 *                          The shell draws the subpage header + back button.
 *   section="<id>" [embedded]   one section only (setup wizard embeds persons, accounts, goals,
 *                          points, ai). `embedded` hides the own Save bar; the wizard calls save().
 *   (neither)              legacy "Personen & Konten" card (persons + accounts) used by fd-overview.
 *
 * Sections: persons, accounts, payday, region, notifications, ai, points, goals, banks, advanced.
 *
 *   GET/PUT finance_dashboard/assignments
 *     {persons:[{name, display_name, ha_users:[id]}], ha_users:[...],
 *      accounts:[{key,name,institution,iban_last4,owner,account_type,earliest_booked}]}   PUT: {persons:[{name,display_name,ha_users}], accounts:[{key,owner}]}
 *   GET/PUT finance_dashboard/setup            payday, region, notifications
 *   GET/PUT finance_dashboard/setup/ai         provider, model, api key (write-only), monthly budget
 *   GET/PUT finance_dashboard/setup/ai/consents  per-purpose consent {consents:{p:{granted,mode,granted_at,used_at}}, purposes:{p:{mode,pros,risks}}}
 *                                              PUT {purpose, granted}; the setup shows only "categorize", Settings lists all
 *   GET/PUT finance_dashboard/setup/points     {entity_id}
 *   GET/POST finance_dashboard/setup/goals, DELETE setup/goals/{id}
 *   POST finance_dashboard/demo/toggle
 *
 * Properties: hass (required), data (optional pre-loaded /assignments payload).
 * Events (bubbling, composed):
 *   fd-toast              {message, type}
 *   fd-assignments-saved  {payload}
 *   fd-settings-saved     {section}
 *   fd-navigate           {target:"setup"}  ("Einrichtung erneut starten")
 */

const DOMAIN = "finance_dashboard";
const ALL = ["persons", "accounts", "payday", "region", "notifications", "ai", "points", "goals", "banks", "advanced"];
const POINTS_EVENT = "finance_dashboard_points_awarded";
const STATES = [
  ["DE-BW", "Baden-Württemberg"], ["DE-BY", "Bayern"], ["DE-BE", "Berlin"], ["DE-BB", "Brandenburg"],
  ["DE-HB", "Bremen"], ["DE-HH", "Hamburg"], ["DE-HE", "Hessen"], ["DE-MV", "Mecklenburg-Vorpommern"],
  ["DE-NI", "Niedersachsen"], ["DE-NW", "Nordrhein-Westfalen"], ["DE-RP", "Rheinland-Pfalz"], ["DE-SL", "Saarland"],
  ["DE-SN", "Sachsen"], ["DE-ST", "Sachsen-Anhalt"], ["DE-SH", "Schleswig-Holstein"], ["DE-TH", "Thüringen"],
];
const AI_LABELS = { ha: "Home Assistant", xai: "Grok (xAI)", anthropic: "Claude", openai: "ChatGPT" };

/** One line for a stored AI test outcome ({at, ok, category, error} or null). */
function aiTestText(t) {
  if (!t) return tr("settings.ai.test_none");
  const time = window._fd.fmtDate(t.at, true);
  if (t.ok) return tr("settings.ai.test_ok", { time, cat: window._fd.CAT_LABELS[t.category] || t.category });
  const why = tr("ai.err." + t.error);
  return tr("settings.ai.test_fail", { time, why: why === "ai.err." + t.error ? (t.error || "?") : why });
}
const GOAL_KINDS = ["target_by_date", "category_cap", "savings_rate", "reserve_topup"];
const NOTIF = ["large_debit", "double_charge", "missing_salary", "consent_expiring", "digest_enabled"];

// Fallback texts: used until locales/*.json carry the settings.* keys.
const FB = {
  de: {
    "settings.title": "Personen & Konten",
    "settings.intro": "Lege fest, wer zum Haushalt gehört und welchem Konto wer zugeordnet ist. Die Zuordnung ist nur der Standard – Haushaltsplan und Korrekturen gehen vor.",
    "settings.step1": "Wer gehört zum Haushalt?",
    "settings.step1_hint": "Jeder Home-Assistant-Benutzer, der zum Haushalt gehört, wird zu einer Person. Der Anzeigename wird überall angezeigt.",
    "settings.user_toggle": "Gehört zum Haushalt",
    "settings.suggested": "Vorgeschlagen",
    "settings.admin": "Admin",
    "settings.reason.person": "Bereits Person",
    "settings.reason.active_user": "Aktiver Benutzer",
    "settings.reason.system": "Systembenutzer",
    "settings.reason.inactive": "Inaktiv",
    "settings.reason.no_person": "Keine Person in Home Assistant",
    "settings.more_users": "Weitere Benutzer ($n)",
    "settings.person_name": "Name der Person",
    "settings.nickname": "Anzeigename",
    "settings.person_remove": "Person entfernen",
    "settings.persons_free": "Personen ohne Benutzer",
    "settings.add_person": "Person hinzufügen",
    "settings.step2": "Welches Konto gehört wem?",
    "settings.step2_hint": "Offen heißt: noch nicht entschieden. Haushalt = gemeinsames Konto.",
    "settings.owner_shared": "Haushalt",
    "settings.owner_none": "Offen",
    "settings.no_accounts": "Noch keine Konten verbunden.",
    "settings.connect_bank": "Bank verbinden",
    "settings.acc.since": "Daten ab $month",
    "settings.acc.type.CACC": "Girokonto",
    "settings.acc.type.SVGS": "Sparkonto",
    "settings.acc.type.CARD": "Kreditkarte",
    "settings.ai.consent_title": "Zustimmung je Zweck",
    "settings.ai.consent_on": "Zugestimmt am $date",
    "settings.ai.consent_off": "Nicht zugestimmt",
    "settings.ai.used": "Zuletzt genutzt: $date",
    "settings.ai.used_never": "Noch nie genutzt",
    "settings.ai.pros": "Vorteile",
    "settings.ai.risks": "Risiken",
    "settings.ai.consent_err": "Zustimmung konnte nicht gespeichert werden",
    "ai.mode.once": "einmalig",
    "ai.mode.recurring": "regelmäßig",
    "ai.purpose.categorize.title": "Buchungen kategorisieren",
    "ai.purpose.sheet_analysis.title": "Haushaltstabelle analysieren",
    "settings.no_persons": "Lege zuerst oben mindestens eine Person fest.",
    "settings.save": "Speichern",
    "settings.saving": "Speichere…",
    "settings.saved": "Gespeichert",
    "settings.error": "Speichern fehlgeschlagen",
    "settings.err_name": "Jede Person braucht einen Namen.",
    "settings.err_dup": "Jeder Name darf nur einmal vorkommen.",
    "settings.load_error": "Konnte nicht geladen werden.",
    "settings.nav": "Bereiche",
    "settings.sec.persons": "Personen",
    "settings.sec.accounts": "Konten",
    "settings.sec.payday": "Zahltag",
    "settings.sec.region": "Region",
    "settings.sec.notifications": "Benachrichtigungen",
    "settings.sec.ai": "KI",
    "settings.sec.points": "Punkte",
    "settings.sec.goals": "Sparziele",
    "settings.sec.banks": "Banken",
    "settings.sec.advanced": "Erweitert",
    "settings.payday_hint": "Dein Monat beginnt mit dem Gehalt. Leer lassen heißt: Kalendermonat.",
    "settings.payday_day": "Tag im Monat",
    "settings.payday_err": "Der Tag muss zwischen 1 und 31 liegen.",
    "settings.region_hint": "Das Bundesland brauchen wir nur für den Vergleich mit typischen Ausgaben. Die Postleitzahl ist freiwillig.",
    "settings.postcode": "Postleitzahl (optional)",
    "settings.postcode_err": "Die Postleitzahl hat 5 Ziffern.",
    "settings.notif_hint": "Ruhig und selten: nur Ausnahmen und eine Wochenübersicht.",
    "settings.notif.enabled": "Benachrichtigungen",
    "settings.notif.large_debit": "Ungewöhnlich hohe Abbuchung",
    "settings.notif.double_charge": "Doppelt abgebucht",
    "settings.notif.missing_salary": "Gehalt nicht eingegangen",
    "settings.notif.consent_expiring": "Bankzugang läuft bald ab",
    "settings.notif.digest_enabled": "Wochenübersicht",
    "settings.ai.toggle": "KI-Kategorisierung erlauben",
    "settings.ai.privacy": "Gesendet werden nur Händlername und Verwendungszweck, nie Betrag, IBAN oder Datum. Ohne Zustimmung bleibt alles lokal.",
    "settings.ai.provider": "Anbieter",
    "settings.ai.ha": "Home Assistant (zuerst)",
    "settings.ai.ha_hint": "Zuerst wird die KI deiner Home-Assistant-Installation genutzt. Es verlässt nichts dein System außer dem, was dein HA-Agent selbst sendet.",
    "settings.ai.ha_agent": "Agent (optional)",
    "settings.ai.model": "Modell",
    "settings.ai.key": "API-Schlüssel",
    "settings.ai.key_ph": "Neuen Schlüssel einfügen",
    "settings.ai.key_saved": "Schlüssel gespeichert",
    "settings.ai.key_none": "Noch kein Schlüssel",
    "settings.ai.key_remove": "Schlüssel entfernen",
    "settings.ai.key_hint": "Der Schlüssel wird verschlüsselt abgelegt und nie wieder angezeigt.",
    "settings.ai.key_removed": "Schlüssel entfernt",
    "settings.ai.budget": "Monatsbudget (Aufrufe)",
    "settings.ai.budget_hint": "0 bis $cap Aufrufe pro Monat. Ist das Budget aufgebraucht, pausiert die KI bis zum nächsten Monat. Mit Home Assistant (z. B. Gemini gratis) kostet ein Aufruf nichts, mit eigenem Schlüssel zahlst du je Aufruf.",
    "settings.ai.budget_err": "Bitte eine ganze Zahl von 0 bis $cap eingeben.",
    "settings.ai.usage": "Diesen Monat: $calls von $cap Aufrufen, $left übrig",
    "settings.ai.test": "Verbindung testen",
    "settings.ai.test_busy": "Teste …",
    "settings.ai.test_hint": "Fragt die KI mit einem erfundenen Händler – keine Bankdaten, zählt als ein Aufruf. Gespeicherte Änderungen gelten erst nach „Speichern“.",
    "settings.ai.test_none": "Noch nicht getestet",
    "settings.ai.test_ok": "Test erfolgreich ($time): Antwort „$cat“",
    "settings.ai.test_fail": "Test fehlgeschlagen ($time): $why",
    "ai.err.not_opted_in": "KI-Kategorisierung ist nicht erlaubt",
    "ai.err.no_key": "kein API-Schlüssel gespeichert",
    "ai.err.no_provider": "keine KI in Home Assistant eingerichtet",
    "ai.err.budget_exhausted": "Monatsbudget aufgebraucht",
    "ai.err.timeout": "keine Antwort in 20 s",
    "ai.err.request_failed": "Anfrage fehlgeschlagen",
    "ai.err.no_answer": "leere Antwort oder Fehler beim Anbieter",
    "ai.err.unparsable": "Antwort war keine bekannte Kategorie",
    "settings.points.intro": "Alle $every beantworteten Fragen löst Finance das Home-Assistant-Ereignis $event aus (mit der Person). Eure Automatisierung vergibt damit die Punkte im eigenen System.",
    "settings.points.entity": "Hilfs-Entität (optional)",
    "settings.points.entity_hint": "Ein Zähler oder Eingabezahl-Helfer, den deine Automatisierung hochzählt. Finance führt selbst kein Punktekonto.",
    "settings.points.search": "Entität suchen",
    "settings.points.none": "Keine passende Entität gefunden.",
    "settings.points.clear": "Entität entfernen",
    "settings.points.answered": "Bisher beantwortet: $n",
    "settings.goals.intro": "Ziele, die Finance im Blick behält. Du kannst jederzeit weitere anlegen oder entfernen.",
    "settings.goals.empty": "Noch keine Sparziele.",
    "settings.goals.add": "Ziel hinzufügen",
    "settings.goals.remove": "Ziel entfernen",
    "settings.goals.removed": "Ziel entfernt",
    "settings.goals.added": "Ziel angelegt",
    "settings.goals.name": "Name",
    "settings.goals.owner": "Für wen",
    "settings.goals.kind.target_by_date": "Betrag bis Datum",
    "settings.goals.kind.category_cap": "Kategorie-Limit",
    "settings.goals.kind.savings_rate": "Sparquote",
    "settings.goals.kind.reserve_topup": "Rücklage auffüllen",
    "settings.goals.target_amount": "Zielbetrag (€)",
    "settings.goals.target_date": "Bis wann (JJJJ-MM-TT)",
    "settings.goals.category": "Kategorie",
    "settings.goals.cap_amount": "Limit pro Monat (€)",
    "settings.goals.rate_percent": "Sparquote (% vom Einkommen)",
    "settings.goals.reserve_id": "Rücklage (Kennung)",
    "settings.goals.monthly_amount": "Monatlich zurücklegen (€)",
    "settings.goals.err": "Bitte alle Felder ausfüllen.",
    "settings.goals.sum.target_by_date": "$amount bis $date",
    "settings.goals.sum.category_cap": "max. $amount pro Monat · $category",
    "settings.goals.sum.savings_rate": "$rate % des Einkommens",
    "settings.goals.sum.reserve_topup": "$amount pro Monat · $reserve",
    "settings.banks.body": "Bankverbindungen verwaltest du auf der Integrationsseite von Home Assistant: neue Bank hinzufügen, Zugang erneuern oder entfernen.",
    "settings.banks.open": "Integrationsseite öffnen",
    "settings.adv.demo": "Demo-Modus umschalten",
    "settings.adv.demo_hint": "Zeigt Beispieldaten statt deiner Bankdaten. Deine echten Daten bleiben unberührt.",
    "settings.adv.demo_done": "Demo-Modus umgeschaltet",
    "settings.adv.setup": "Einrichtung erneut starten",
    "settings.adv.setup_hint": "Geht die Einrichtungsschritte noch einmal durch. Bereits Gespeichertes bleibt erhalten.",
  },
  en: {
    "settings.title": "People & accounts",
    "settings.intro": "Decide who belongs to the household and which account belongs to whom. This is only the default – the household plan and corrections take precedence.",
    "settings.step1": "Who is part of the household?",
    "settings.step1_hint": "Every Home Assistant user who belongs to the household becomes a person. The display name is shown everywhere.",
    "settings.user_toggle": "Part of the household",
    "settings.suggested": "Suggested",
    "settings.admin": "Admin",
    "settings.reason.person": "Already a person",
    "settings.reason.active_user": "Active user",
    "settings.reason.system": "System user",
    "settings.reason.inactive": "Inactive",
    "settings.reason.no_person": "No person in Home Assistant",
    "settings.more_users": "More users ($n)",
    "settings.person_name": "Person name",
    "settings.nickname": "Display name",
    "settings.person_remove": "Remove person",
    "settings.persons_free": "People without a user",
    "settings.add_person": "Add person",
    "settings.step2": "Which account belongs to whom?",
    "settings.step2_hint": "Open means not decided yet. Household = shared account.",
    "settings.owner_shared": "Household",
    "settings.owner_none": "Open",
    "settings.no_accounts": "No accounts connected yet.",
    "settings.connect_bank": "Connect a bank",
    "settings.acc.since": "Data from $month",
    "settings.acc.type.CACC": "Current account",
    "settings.acc.type.SVGS": "Savings account",
    "settings.acc.type.CARD": "Credit card",
    "settings.ai.consent_title": "Consent per purpose",
    "settings.ai.consent_on": "Consent given on $date",
    "settings.ai.consent_off": "No consent",
    "settings.ai.used": "Last used: $date",
    "settings.ai.used_never": "Never used",
    "settings.ai.pros": "Advantages",
    "settings.ai.risks": "Risks",
    "settings.ai.consent_err": "Consent could not be saved",
    "ai.mode.once": "one-time",
    "ai.mode.recurring": "recurring",
    "ai.purpose.categorize.title": "Categorise transactions",
    "ai.purpose.sheet_analysis.title": "Analyse household spreadsheet",
    "settings.no_persons": "Add at least one person above first.",
    "settings.save": "Save",
    "settings.saving": "Saving…",
    "settings.saved": "Saved",
    "settings.error": "Saving failed",
    "settings.err_name": "Every person needs a name.",
    "settings.err_dup": "Each name may appear only once.",
    "settings.load_error": "Could not be loaded.",
    "settings.nav": "Sections",
    "settings.sec.persons": "People",
    "settings.sec.accounts": "Accounts",
    "settings.sec.payday": "Payday",
    "settings.sec.region": "Region",
    "settings.sec.notifications": "Notifications",
    "settings.sec.ai": "AI",
    "settings.sec.points": "Points",
    "settings.sec.goals": "Savings goals",
    "settings.sec.banks": "Banks",
    "settings.sec.advanced": "Advanced",
    "settings.payday_hint": "Your month starts with your salary. Leave empty to use the calendar month.",
    "settings.payday_day": "Day of month",
    "settings.payday_err": "The day must be between 1 and 31.",
    "settings.region_hint": "We only need the state to compare against typical spending. The postcode is optional.",
    "settings.postcode": "Postcode (optional)",
    "settings.postcode_err": "The postcode has 5 digits.",
    "settings.notif_hint": "Calm and rare: exceptions and a weekly digest only.",
    "settings.notif.enabled": "Notifications",
    "settings.notif.large_debit": "Unusually large debit",
    "settings.notif.double_charge": "Charged twice",
    "settings.notif.missing_salary": "Salary not received",
    "settings.notif.consent_expiring": "Bank access expires soon",
    "settings.notif.digest_enabled": "Weekly digest",
    "settings.ai.toggle": "Allow AI categorisation",
    "settings.ai.privacy": "Only merchant name and remittance text are sent, never amount, IBAN or date. Without consent everything stays local.",
    "settings.ai.provider": "Provider",
    "settings.ai.ha": "Home Assistant (first)",
    "settings.ai.ha_hint": "Your Home Assistant's own AI is used first. Nothing leaves your system except what your HA agent itself sends.",
    "settings.ai.ha_agent": "Agent (optional)",
    "settings.ai.model": "Model",
    "settings.ai.key": "API key",
    "settings.ai.key_ph": "Paste a new key",
    "settings.ai.key_saved": "Key stored",
    "settings.ai.key_none": "No key yet",
    "settings.ai.key_remove": "Remove key",
    "settings.ai.key_hint": "The key is stored encrypted and never shown again.",
    "settings.ai.key_removed": "Key removed",
    "settings.ai.budget": "Monthly budget (calls)",
    "settings.ai.budget_hint": "0 to $cap calls per month. Once the budget is used up, the AI pauses until next month. Through Home Assistant (e.g. free Gemini) a call costs nothing; with an own key you pay per call.",
    "settings.ai.budget_err": "Please enter a whole number from 0 to $cap.",
    "settings.ai.usage": "This month: $calls of $cap calls used, $left left",
    "settings.ai.test": "Test connection",
    "settings.ai.test_busy": "Testing …",
    "settings.ai.test_hint": "Asks the AI about a made-up merchant – no bank data, counts as one call. Unsaved changes apply only after \"Save\".",
    "settings.ai.test_none": "Not tested yet",
    "settings.ai.test_ok": "Test succeeded ($time): answer \"$cat\"",
    "settings.ai.test_fail": "Test failed ($time): $why",
    "ai.err.not_opted_in": "AI categorisation is not allowed",
    "ai.err.no_key": "no API key stored",
    "ai.err.no_provider": "no AI set up in Home Assistant",
    "ai.err.budget_exhausted": "monthly budget used up",
    "ai.err.timeout": "no answer within 20 s",
    "ai.err.request_failed": "request failed",
    "ai.err.no_answer": "empty answer or provider error",
    "ai.err.unparsable": "answer was not a known category",
    "settings.points.intro": "Every $every answered questions Finance fires the Home Assistant event $event (with the person). Your own automation turns it into points in your household's system.",
    "settings.points.entity": "Helper entity (optional)",
    "settings.points.entity_hint": "A counter or number helper your automation increments. Finance keeps no points ledger itself.",
    "settings.points.search": "Search entity",
    "settings.points.none": "No matching entity found.",
    "settings.points.clear": "Remove entity",
    "settings.points.answered": "Answered so far: $n",
    "settings.goals.intro": "Goals Finance keeps an eye on. Add or remove them at any time.",
    "settings.goals.empty": "No savings goals yet.",
    "settings.goals.add": "Add goal",
    "settings.goals.remove": "Remove goal",
    "settings.goals.removed": "Goal removed",
    "settings.goals.added": "Goal added",
    "settings.goals.name": "Name",
    "settings.goals.owner": "For whom",
    "settings.goals.kind.target_by_date": "Amount by date",
    "settings.goals.kind.category_cap": "Category cap",
    "settings.goals.kind.savings_rate": "Savings rate",
    "settings.goals.kind.reserve_topup": "Top up a reserve",
    "settings.goals.target_amount": "Target amount (€)",
    "settings.goals.target_date": "By when (YYYY-MM-DD)",
    "settings.goals.category": "Category",
    "settings.goals.cap_amount": "Cap per month (€)",
    "settings.goals.rate_percent": "Savings rate (% of income)",
    "settings.goals.reserve_id": "Reserve (identifier)",
    "settings.goals.monthly_amount": "Set aside per month (€)",
    "settings.goals.err": "Please fill in all fields.",
    "settings.goals.sum.target_by_date": "$amount by $date",
    "settings.goals.sum.category_cap": "max. $amount per month · $category",
    "settings.goals.sum.savings_rate": "$rate % of income",
    "settings.goals.sum.reserve_topup": "$amount per month · $reserve",
    "settings.banks.body": "Manage bank connections on Home Assistant's integration page: add a bank, renew access or remove one.",
    "settings.banks.open": "Open integration page",
    "settings.adv.demo": "Toggle demo mode",
    "settings.adv.demo_hint": "Shows sample data instead of your bank data. Your real data stays untouched.",
    "settings.adv.demo_done": "Demo mode toggled",
    "settings.adv.setup": "Restart setup",
    "settings.adv.setup_hint": "Walks through the setup steps again. Anything already saved is kept.",
  },
};

function tr(key, vars = {}) {
  let s = window._fd.tSync(key, vars);
  if (s !== key) return s;
  const raw = ((window._fd._hass && window._fd._hass.language) || navigator.language || "en").toLowerCase();
  s = (FB[raw.startsWith("de") ? "de" : "en"][key]) || key;
  for (const [k, v] of Object.entries(vars)) s = s.replace(new RegExp(`\\$${k}`, "g"), String(v));
  return s;
}

const PERSON_COLORS = ["var(--fd-person-a)", "var(--fd-person-b)", "#ef6c00", "#5e35b1", "#6d4c41"];

const CSS = `
:host { display: block; min-width: 0; }
.root { color: var(--fd-t1); font-size: 13px; line-height: 1.4; min-width: 0; container: settings / inline-size; }
button { font: inherit; color: inherit; cursor: pointer; }
.card { box-sizing: border-box; min-width: 0; padding: 14px; border-radius: var(--fd-r-card); background: var(--fd-card); box-shadow: var(--fd-sh1); border: 0; }
.card + .card { margin-top: 12px; }
h3 { margin: 0 0 2px; font-size: 16px; font-weight: 500; }
h4 { margin: 18px 0 2px; font-size: 14px; font-weight: 500; }
.muted { color: var(--fd-t2); font-size: 11.5px; margin: 0 0 8px; overflow-wrap: anywhere; }
.row { display: flex; align-items: center; gap: 10px; min-height: var(--fd-touch); padding: 6px 0; flex-wrap: wrap; min-width: 0; }
.row + .row { border-top: 1px solid var(--fd-line); }
.row .who { flex: 1 1 140px; min-width: 0; display: flex; flex-direction: column; }
.row .who b { font-weight: 500; overflow-wrap: anywhere; }
.row .who span { color: var(--fd-t2); font-size: 11.5px; }
.row .who span.ok { color: var(--fd-ok); font-weight: 500; }
.row .who span.warn { color: var(--fd-over); font-weight: 500; }
.chip { display: inline-flex; align-items: center; padding: 1px 9px; border-radius: var(--fd-r-pill); font-size: 11.5px; font-weight: 500; background: var(--fd-a50); color: var(--fd-a900); margin-left: 6px; }
.hit { flex: none; box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center; width: 52px; min-width: 52px; min-height: var(--fd-touch); }
.sw { box-sizing: border-box; flex: none; position: relative; width: 52px; min-width: 52px; max-width: 52px; height: 32px; border-radius: 16px; border: 1px solid var(--fd-line); background: var(--fd-sunk); padding: 0; margin: 0; }
.sw::after { content: ""; position: absolute; top: 3px; left: 3px; width: 24px; height: 24px; border-radius: 50%; background: var(--fd-t3); transition: transform .15s, background .15s; }
.sw[aria-checked="true"] { background: var(--fd-a700); border-color: var(--fd-a700); }
.sw[aria-checked="true"]::after { transform: translateX(20px); background: #fff; }
input[type=text], input[type=password], input[type=number] { box-sizing: border-box; flex: 1 1 160px; min-width: 0; width: 100%; min-height: var(--fd-touch); padding: 0 12px; border: 1px solid var(--fd-line); border-radius: 10px; background: var(--fd-page); color: var(--fd-t1); font: inherit; }
.f { display: flex; flex-direction: column; gap: 4px; margin: 8px 0; min-width: 0; }
.f > label, .lbl { color: var(--fd-t2); font-size: 11.5px; }
.btn { box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center; min-height: var(--fd-touch); padding: 0 16px; border: 1px solid transparent; border-radius: var(--fd-r-pill); background: var(--fd-a700); color: #fff; font-weight: 500; text-decoration: none; }
.btn.ghost { background: transparent; color: var(--fd-a700); border-color: var(--fd-a100); }
.btn.sm { min-height: 36px; padding: 0 12px; font-size: 12px; }
.btn:disabled { opacity: .5; cursor: default; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 0; }
.chips button { min-height: 36px; padding: 0 14px; border: 1px dashed var(--fd-a300); border-radius: var(--fd-r-pill); background: transparent; color: var(--fd-a700); }
details { margin-top: 8px; }
summary { min-height: var(--fd-touch); display: flex; align-items: center; color: var(--fd-t2); cursor: pointer; }
.acc { padding: 8px 0; min-width: 0; }
.acc + .acc { border-top: 1px solid var(--fd-line); }
.acc .nm { overflow-wrap: anywhere; min-width: 0; }
.acc .nm b { font-weight: 500; }
.acc .nm span { display: block; color: var(--fd-t2); font-size: 11.5px; }
.seg { display: flex; flex-wrap: nowrap; gap: 6px; margin-top: 6px; overflow-x: auto; scroll-snap-type: x proximity; padding-bottom: 2px; min-width: 0; }
.seg button { flex: none; scroll-snap-align: start; min-height: 40px; padding: 0 12px 0 6px; border: 1px solid var(--fd-line); border-radius: var(--fd-r-pill); background: transparent; display: inline-flex; align-items: center; gap: 6px; max-width: 100%; }
.seg .av { flex: none; width: 24px; height: 24px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; background: var(--c, var(--fd-t3)); color: #fff; font-size: 11.5px; font-weight: 600; }
.seg .lb { max-width: 16ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.seg button[aria-checked="true"] { background: var(--fd-a50); border-color: var(--c, var(--fd-a500)); color: var(--fd-a900); font-weight: 500; }
.opts { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0; }
.opts button { min-height: 40px; padding: 0 14px; border: 1px solid var(--fd-line); border-radius: var(--fd-r-pill); background: transparent; }
.opts button[aria-checked="true"], .opts button[aria-pressed="true"] { background: var(--fd-a50); border-color: var(--fd-a500); color: var(--fd-a900); font-weight: 500; }
.states { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; margin: 8px 0; }
@container (min-width: 520px) { .states { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
.states button { min-height: var(--fd-touch); padding: 4px 10px; border: 1px solid var(--fd-line); border-radius: 12px; background: transparent; text-align: left; overflow-wrap: anywhere; }
.states button[aria-checked="true"] { background: var(--fd-a50); border-color: var(--fd-a500); color: var(--fd-a900); font-weight: 500; }
.cons { padding: 6px 0 10px; border-top: 1px solid var(--fd-line); }
.cons ul.pc { margin: 2px 0 8px; padding-left: 18px; font-size: 12.5px; color: var(--fd-t2); }
.cons ul.pc li { margin: 2px 0; }
.bar { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 10px; margin-top: 16px; }
.err { margin-right: auto; color: var(--fd-over); font-size: 12px; min-width: 0; overflow-wrap: anywhere; }
.ok { color: var(--fd-ok); font-size: 12px; }
.note { padding: 12px; border-radius: 10px; background: var(--fd-sunk); color: var(--fd-t2); font-size: 12.5px; margin: 8px 0; overflow-wrap: anywhere; }
code { font-size: 11.5px; background: var(--fd-sunk); padding: 1px 5px; border-radius: 4px; overflow-wrap: anywhere; }
input[type=range] { width: 100%; min-height: var(--fd-touch); accent-color: var(--fd-a700); margin: 0; }
.rng { display: flex; align-items: center; gap: 12px; }
.rng output { flex: none; min-width: 3ch; text-align: right; font-weight: 500; }
.pick { max-height: 220px; overflow-y: auto; border: 1px solid var(--fd-line); border-radius: 10px; margin-top: 6px; }
.pick button { display: flex; flex-direction: column; align-items: flex-start; width: 100%; min-height: var(--fd-touch); padding: 4px 12px; border: 0; background: transparent; text-align: left; overflow-wrap: anywhere; }
.pick button + button { border-top: 1px solid var(--fd-line); }
.pick button span { color: var(--fd-t2); font-size: 11.5px; }
.goal { display: flex; align-items: center; gap: 10px; padding: 8px 0; min-width: 0; }
.goal + .goal { border-top: 1px solid var(--fd-line); }
.goal .who { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; }
.goal .who b { font-weight: 500; overflow-wrap: anywhere; }
.goal .who span { color: var(--fd-t2); font-size: 11.5px; overflow-wrap: anywhere; }
.nav { display: flex; gap: 6px; overflow-x: auto; scroll-snap-type: x proximity; padding: 2px 0 10px; margin: 0; list-style: none; min-width: 0; }
.nav li { flex: none; scroll-snap-align: start; }
.nav button { min-height: 40px; padding: 0 14px; border: 1px solid var(--fd-line); border-radius: var(--fd-r-pill); background: var(--fd-card); white-space: nowrap; }
.nav button[aria-current="true"] { background: var(--fd-a50); border-color: var(--fd-a500); color: var(--fd-a900); font-weight: 500; }
.page { display: block; min-width: 0; }
@container settings (min-width: 760px) {
  .page { display: grid; grid-template-columns: 210px minmax(0, 1fr); gap: 16px; align-items: start; }
  .nav { position: sticky; top: 8px; flex-direction: column; overflow: visible; padding: 0; }
  .nav button { width: 100%; text-align: left; border-radius: 12px; }
  .nav button:not([aria-current="true"]) { border-color: transparent; background: transparent; }
}
button:focus-visible, input:focus-visible, summary:focus-visible, a:focus-visible { outline: 2px solid var(--fd-a500); outline-offset: 2px; }
[hidden] { display: none !important; }
.flds { flex: 1 1 100%; display: grid; grid-template-columns: minmax(0, 1fr); gap: 0 10px; min-width: 0; }
.f > label { display: flex; flex-direction: column; gap: 4px; }
.f input[type=text], .f input[type=password], .f input[type=number], .flds input { flex: none; }
@container (min-width: 520px) { .flds { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@container (min-width: 700px) {
  .acc { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
  .acc .seg { margin-top: 0; justify-content: flex-end; }
}
`;

class FdSettings extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._data = null;
    this._draft = null;
    this._error = "";
    this._saving = false;
    this._loadFailed = false;
    this._wired = false;
    this._d = {};      // server payloads: setup, ai, points, goals
    this._dr = { payday: {}, region: {}, notif: {}, ai: {}, points: { q: "" }, goal: null };
    this._msg = {};    // per section error text
    this._loaded = new Set();
  }

  get hass() { return this._hass; }
  set hass(h) {
    const first = !this._hass;
    this._hass = h;
    if (first && !this._needsAssign) this._render();
    else if (first && !this._data) this.load();
    else if (first) this._render();
  }

  static get observedAttributes() { return ["section", "embedded", "mode"]; }
  attributeChangedCallback(name) {
    if (!this._hass || (this._needsAssign && !this._draft)) return;
    if (name === "section" && this._isPage) this._scrollTo(this._section);
    else this._render();
  }
  get _needsAssign() { return this._sections.some((s) => s === "persons" || s === "accounts"); }
  get _section() { return this.getAttribute("section") || ""; }
  get _isPage() { return this.getAttribute("mode") === "page"; }
  get _embedded() { return this.hasAttribute("embedded"); }
  /** Section ids rendered in this mode. */
  get _sections() {
    if (this._isPage) return ALL;
    return this._section ? [this._section] : ["persons", "accounts"];
  }

  /** Save what this section holds; resolves true on success (used by the setup wizard). */
  async save() {
    switch (this._section) {
      case "ai": return this._saveAi();
      case "points": return this._savePoints();
      case "goals": return true;
      default: return this._save();
    }
  }

  get data() { return this._data; }
  set data(d) {
    this._data = d || null;
    this._draft = d ? this._makeDraft(d) : null;
    this._render();
  }

  get _isAdmin() {
    return !!(this._hass && this._hass.user && this._hass.user.is_admin);
  }

  async load() {
    if (!this._hass || !this._isAdmin) return this._render();
    await window._fd.t("settings.title");
    try {
      this.data = await this._hass.callApi("GET", `${DOMAIN}/assignments`);
      this._loadFailed = false;
    } catch (e) {
      console.warn("fd-settings: load failed:", e);
      this._loadFailed = true;
      this._render();
    }
  }

  /** Lazy per-section data (everything except persons/accounts). */
  async _ensure(sec) {
    const need = {
      payday: [["setup", "setup"]], region: [["setup", "setup"]], notifications: [["setup", "setup"]],
      goals: [["setup", "setup"], ["goals", "setup/goals"]],
      ai: [["ai", "setup/ai"], ["consents", "setup/ai/consents"]], points: [["points", "setup/points"]],
    }[sec] || [];
    for (const [key, path] of need) {
      if (this._loaded.has(key)) continue;
      this._loaded.add(key);
      try {
        const res = await this._hass.callApi("GET", `${DOMAIN}/${path}`);
        this._d[key] = key === "goals" ? (res.goals || []) : res;
        this._initDraft(key);
      } catch (e) {
        console.warn(`fd-settings: ${path} failed:`, e);
        this._loaded.delete(key);
        this._msg[sec] = tr("settings.load_error");
      }
    }
    this._renderSec(sec);
  }

  _initDraft(key) {
    const v = this._d[key];
    if (key === "setup") {
      const paydays = {};
      for (const p of v.persons || []) {
        const day = p.payday && typeof p.payday === "object" ? p.payday.day : p.payday;
        paydays[p.name] = day ? String(day) : "";
      }
      this._dr.payday = paydays;
      this._dr.region = { state: (v.region || {}).state || "", postcode: (v.region || {}).postcode || "" };
      this._dr.notif = { ...(v.notifications || {}) };
    } else if (key === "ai") {
      this._dr.ai = {
        provider: v.provider || "ha", model: v.model || "", ha_agent: v.ha_agent || "",
        budget_cap: (v.budget || {}).cap ?? 100, api_key: "",
      };
    } else if (key === "points") {
      this._dr.points = { entity_id: v.entity_id || "", q: "" };
    }
  }

  _makeDraft(d) {
    return {
      persons: (d.persons || []).map((p) => ({
        name: p.name, ha_users: [...(p.ha_users || [])],
        display_name: p.display_name && p.display_name !== p.name ? p.display_name : "",
      })),
      owners: Object.fromEntries((d.accounts || []).map((a) => [a.key, a.owner || ""])),
    };
  }

  _dn(p) { return (p.display_name || "").trim() || p.name; }
  _personOf(userId) { return this._draft.persons.find((p) => p.ha_users.includes(userId)); }

  _toggleUser(u) {
    const p = this._personOf(u.id);
    if (p) {
      p.ha_users = p.ha_users.filter((x) => x !== u.id);
      if (!p.ha_users.length) this._removePerson(p);
    } else {
      this._draft.persons.push({ name: u.name, ha_users: [u.id], display_name: "" });
    }
  }

  _removePerson(p) {
    this._draft.persons = this._draft.persons.filter((x) => x !== p);
    for (const k of Object.keys(this._draft.owners)) {
      if (this._draft.owners[k] === p.name) this._draft.owners[k] = "";
    }
  }

  _color(name) {
    const i = this._draft.persons.findIndex((p) => p.name === name);
    return PERSON_COLORS[(i < 0 ? 0 : i) % PERSON_COLORS.length];
  }

  /** Persons for owner pickers: draft first, else whatever the server sent. */
  _personList() {
    if (this._draft) return this._draft.persons.filter((p) => p.name.trim());
    return ((this._d.setup || {}).persons || []);
  }

  // ---- shell ------------------------------------------------------------
  _render() {
    const sh = this.shadowRoot;
    if (!this._isAdmin) { sh.innerHTML = ""; return; }
    const { escHtml } = window._fd;
    const head = `<style>${window._fd.SHARED_CSS}${CSS}</style>`;
    if (this._needsAssign && !this._draft) {
      sh.innerHTML = `${head}<div class="root"><div class="card">
        <h3>${escHtml(tr("settings.title"))}</h3>
        ${this._loadFailed ? `<p class="muted">${escHtml(tr("settings.load_error"))}</p>` : ""}</div></div>`;
      return;
    }
    const secs = this._sections;
    const legacy = !this._isPage && !this._section;
    const card = (s) => `<section class="${this._embedded ? "" : "card"}" id="sec-${s}" data-sec="${s}"></section>`;
    let body;
    if (this._isPage) {
      const nav = `<ul class="nav" role="list" aria-label="${escHtml(tr("settings.nav"))}">${ALL.map((s) =>
        `<li><button type="button" data-nav="${s}">${escHtml(tr("settings.sec." + s))}</button></li>`).join("")}</ul>`;
      body = `<div class="page">${nav}<div class="secs">${secs.map(card).join("")}</div></div>`;
    } else if (legacy) {
      body = `<div class="card"><h3>${escHtml(tr("settings.title"))}</h3><p class="muted">${escHtml(tr("settings.intro"))}</p>
        <div data-sec="persons"></div><div data-sec="accounts"></div></div>`;
    } else {
      body = secs.map(card).join("");
    }
    sh.innerHTML = `${head}<div class="root">${body}</div>`;
    if (!this._wired) { this._wired = true; this._wire(); }
    for (const s of secs) {
      this._renderSec(s);
      this._ensure(s);
    }
    if (this._isPage) this._markNav(this._section || "persons");
    if (this._isPage && this._section && this._section !== "persons") requestAnimationFrame(() => this._scrollTo(this._section));
  }

  _scrollTo(sec) {
    const el = this.shadowRoot.getElementById(`sec-${sec}`);
    if (!el) return;
    this._markNav(sec);
    el.scrollIntoView({ block: "start", behavior: "smooth" });
    el.querySelector("h3")?.focus?.();
  }

  _markNav(sec) {
    this.shadowRoot.querySelectorAll("[data-nav]").forEach((b) => {
      if (b.dataset.nav === sec) b.setAttribute("aria-current", "true"); else b.removeAttribute("aria-current");
    });
  }

  _secBox(sec) { return this.shadowRoot.querySelector(`[data-sec="${sec}"]`); }

  _renderSec(sec) {
    const box = this._secBox(sec);
    if (!box || (this._needsAssign && !this._draft)) return;
    const { escHtml } = window._fd;
    const legacy = !this._isPage && !this._section;
    const showTitle = this._isPage && !this._embedded;
    const title = showTitle ? `<h3 tabindex="-1">${escHtml(tr("settings.sec." + sec))}</h3>` : "";
    const fn = this[`_s_${sec}`];
    const inner = fn ? fn.call(this, legacy) : "";
    const err = this._msg[sec] ? `<p class="err" role="alert">${escHtml(this._msg[sec])}</p>` : "";
    box.innerHTML = `${title}${inner}${err}`;
  }

  _bar(action, label) {
    const { escHtml } = window._fd;
    if (this._embedded) return `<div class="bar" role="presentation"></div>`;
    return `<div class="bar"><button type="button" class="btn" data-save="${action}">${escHtml(label || tr("settings.save"))}</button></div>`;
  }

  _sw(id, on, label) {
    const { escHtml } = window._fd;
    return `<div class="row"><div class="who"><b>${escHtml(label)}</b></div><span class="hit"><button type="button" class="sw" role="switch" aria-checked="${on}" data-t="${id}" aria-label="${escHtml(label)}"></button></span></div>`;
  }

  // ---- sections ---------------------------------------------------------
  _s_persons(legacy) {
    const { escHtml } = window._fd;
    const d = this._data;
    const users = d.ha_users || [];
    const main = users.filter((u) => u.suggested || this._personOf(u.id));
    const more = users.filter((u) => !main.includes(u));
    const free = this._draft.persons.filter((p) => !p.ha_users.length);
    return `${legacy ? `<h4>1 · ${escHtml(tr("settings.step1"))}</h4>` : ""}
  <p class="muted">${escHtml(tr("settings.step1_hint"))}</p>
  <div>${main.map((u) => this._userRow(u)).join("")}</div>
  ${more.length ? `<details><summary>${escHtml(tr("settings.more_users", { n: more.length }))}</summary>${more.map((u) => this._userRow(u)).join("")}</details>` : ""}
  ${free.length ? `<h4>${escHtml(tr("settings.persons_free"))}</h4>${free.map((p) => this._freeRow(p)).join("")}` : ""}
  <div class="chips"><button type="button" id="addp">+ ${escHtml(tr("settings.add_person"))}</button></div>
  <p class="err" id="err-persons" role="alert">${escHtml(this._error)}</p>
  ${legacy ? "" : this._bar("assign")}`;
  }

  /** One field per person: the display name (shown everywhere). `name` stays the internal key. */
  _nick(p, attr) {
    const { escHtml } = window._fd;
    return `<div class="f"><label>${escHtml(tr("settings.nickname"))}<input type="text" ${attr} value="${escHtml(p.isNew ? p.name : (p.display_name || p.name))}" maxlength="40"></label></div>`;
  }

  _userRow(u) {
    const { escHtml } = window._fd;
    const p = this._personOf(u.id);
    const on = !!p;
    const rkey = `settings.reason.${u.reason || "active_user"}`;
    const reason = tr(rkey) === rkey ? "" : tr(rkey);
    return `<div class="row" data-user="${escHtml(u.id)}">
  <div class="who"><b>${escHtml(u.name)}${u.is_admin ? `<span class="chip">${escHtml(tr("settings.admin"))}</span>` : ""}</b>
    <span>${escHtml(u.suggested ? tr("settings.suggested") + " · " : "")}${escHtml(reason)}</span></div>
  <span class="hit"><button type="button" class="sw" role="switch" aria-checked="${on}" data-sw="${escHtml(u.id)}"
    aria-label="${escHtml(tr("settings.user_toggle") + ": " + u.name)}"></button></span>
  ${on ? `<div class="flds">${this._nick(p, `data-nick-user="${escHtml(u.id)}"`)}</div>` : ""}
</div>`;
  }

  _freeRow(p) {
    const { escHtml } = window._fd;
    const i = this._draft.persons.indexOf(p);
    return `<div class="row">
  <div class="flds">${this._nick(p, p.isNew ? `data-free="${i}"` : `data-nick-free="${i}"`)}</div>
  <button type="button" class="btn ghost sm" data-rm="${i}">${escHtml(tr("settings.person_remove"))}</button>
</div>`;
  }

  _s_accounts(legacy) {
    const { escHtml } = window._fd;
    const head = `${legacy ? `<h4>2 · ${escHtml(tr("settings.step2"))}</h4>` : ""}<p class="muted">${escHtml(tr("settings.step2_hint"))}</p>`;
    const accounts = this._data.accounts || [];
    if (!accounts.length) return `${head}<p class="muted">${escHtml(tr("settings.no_accounts"))}</p>
      <a class="btn" href="/config/integrations/integration/${DOMAIN}">${escHtml(tr("settings.connect_bank"))}</a>`;
    const persons = this._draft.persons;
    // Suggested users that are not persons yet are offered right here.
    const candidates = (this._data.ha_users || []).filter((u) => u.suggested && !this._personOf(u.id));
    const note = persons.length || candidates.length ? "" : `<p class="muted">${escHtml(tr("settings.no_persons"))}</p>`;
    const rows = accounts.map((a) => {
      const cur = this._draft.owners[a.key] || "";
      const opt = (val, label, color, full) =>
        `<button type="button" role="radio" aria-checked="${cur === val}" data-acc="${escHtml(a.key)}" data-owner="${escHtml(val)}" style="--c:${color}" aria-label="${escHtml(full || label)}"><span class="av" aria-hidden="true">${escHtml((label || "?").trim().charAt(0).toUpperCase())}</span><span class="lb">${escHtml(label)}</span></button>`;
      const opts = persons.map((p) => opt(p.name, this._dn(p), this._color(p.name), p.name))
        .concat(candidates.map((u, i) => opt(`user:${u.id}`, u.name, PERSON_COLORS[(persons.length + i) % PERSON_COLORS.length])))
        .concat([opt("shared", tr("settings.owner_shared"), "var(--fd-household)"), opt("", tr("settings.owner_none"), "var(--fd-t3)")]);
      const kind = a.account_type && tr(`settings.acc.type.${a.account_type}`) !== `settings.acc.type.${a.account_type}` ? tr(`settings.acc.type.${a.account_type}`) : "";
      const since = this._sinceText(a.earliest_booked);
      const meta = [a.institution || "", kind, since].filter(Boolean).join(" · ");
      return `<div class="acc"><div class="nm"><b>${escHtml(a.name)}</b><span>${escHtml(meta)}${a.iban_last4 ? ` · ••${escHtml(a.iban_last4)}` : ""}</span></div>
  <div class="seg" role="radiogroup" aria-label="${escHtml(a.name)}">${opts.join("")}</div></div>`;
    }).join("");
    return `${head}${note}${rows}${this._bar("assign")}`;
  }

  /** "Daten ab Oktober 2025" from a YYYY-MM-DD date; empty without one. */
  _sinceText(iso) {
    const m = /^(\d{4})-(\d{2})/.exec(iso || "");
    if (!m) return "";
    const lang = (this._hass && this._hass.language) || navigator.language || "en";
    const month = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, 1)).toLocaleDateString(lang, { month: "long", year: "numeric", timeZone: "UTC" });
    return tr("settings.acc.since", { month });
  }

  _loading(sec) {
    const { escHtml } = window._fd;
    return `<p class="muted">${escHtml(this._msg[sec] || "…")}</p>`;
  }

  _s_payday() {
    const { escHtml } = window._fd;
    const s = this._d.setup;
    if (!s) return this._loading("payday");
    const persons = s.persons || [];
    const rows = persons.map((p) => `<div class="row"><div class="who"><b>${escHtml(this._dn(p))}</b></div>
      <input type="number" min="1" max="31" step="1" inputmode="numeric" style="flex:0 0 96px" data-b="payday.${escHtml(p.name)}" value="${escHtml(this._dr.payday[p.name] ?? "")}" aria-label="${escHtml(tr("settings.payday_day") + ": " + this._dn(p))}"></div>`).join("");
    return `<p class="muted">${escHtml(tr("settings.payday_hint"))}</p>${rows}${this._bar("payday")}`;
  }

  _s_region() {
    const { escHtml } = window._fd;
    if (!this._d.setup) return this._loading("region");
    const r = this._dr.region;
    const chips = STATES.map(([code, name]) => `<button type="button" role="radio" aria-checked="${r.state === code}" data-state="${code}">${escHtml(name)}</button>`).join("");
    return `<p class="muted">${escHtml(tr("settings.region_hint"))}</p>
      <div class="states" role="radiogroup" aria-label="${escHtml(tr("settings.sec.region"))}">${chips}</div>
      <div class="f"><label for="pc">${escHtml(tr("settings.postcode"))}</label>
      <input type="text" id="pc" inputmode="numeric" maxlength="5" autocomplete="postal-code" data-b="region.postcode" value="${escHtml(r.postcode)}"></div>
      ${this._bar("region")}`;
  }

  _s_notifications() {
    const { escHtml } = window._fd;
    if (!this._d.setup) return this._loading("notifications");
    const n = this._dr.notif;
    const rows = n.enabled === false ? "" : NOTIF.map((k) => this._sw(`notif.${k}`, n[k] !== false, tr(`settings.notif.${k}`))).join("");
    return `<p class="muted">${escHtml(tr("settings.notif_hint"))}</p>${this._sw("notif.enabled", n.enabled !== false, tr("settings.notif.enabled"))}${rows}${this._bar("notif")}`;
  }

  _s_ai() {
    const { escHtml } = window._fd;
    const v = this._d.ai;
    if (!v) return this._loading("ai");
    const a = this._dr.ai;
    const provs = (v.providers || []).map((p) => (typeof p === "string" ? { id: p } : p));
    const list = provs.length ? provs : Object.keys(AI_LABELS).map((id) => ({ id, needs_key: id !== "ha" }));
    const cur = list.find((p) => p.id === a.provider) || {};
    const label = (id) => (id === "ha" ? tr("settings.ai.ha") : AI_LABELS[id] || id);
    const opts = list.map((p) => `<button type="button" role="radio" aria-checked="${a.provider === p.id}" data-c="ai.provider=${escHtml(p.id)}">${escHtml(label(p.id))}</button>`).join("");
    const b = v.budget || {};
    const hard = b.hard_cap || 1000;
    let prov;
    if (a.provider === "ha") {
      prov = `<p class="muted">${escHtml(tr("settings.ai.ha_hint"))}</p>
        <div class="f"><label for="ai-agent">${escHtml(tr("settings.ai.ha_agent"))}</label>
        <input type="text" id="ai-agent" data-b="ai.ha_agent" value="${escHtml(a.ha_agent)}" placeholder="conversation.home_assistant" autocomplete="off" autocapitalize="off" spellcheck="false"></div>`;
    } else {
      prov = `<div class="f"><label for="ai-model">${escHtml(tr("settings.ai.model"))}</label>
        <input type="text" id="ai-model" data-b="ai.model" value="${escHtml(a.model)}" placeholder="${escHtml(cur.default_model || v.effective_model || "")}" autocomplete="off" autocapitalize="off" spellcheck="false"></div>
        <div class="f"><label for="ai-key">${escHtml(tr("settings.ai.key"))}</label>
        <input type="password" id="ai-key" data-b="ai.api_key" value="" placeholder="${escHtml(tr("settings.ai.key_ph"))}" autocomplete="new-password" spellcheck="false"></div>
        <div class="row" style="border:0;padding:0"><div class="who"><span class="${v.has_key ? "ok" : ""}" role="status">${escHtml(v.has_key ? tr("settings.ai.key_saved") : tr("settings.ai.key_none"))}</span>
          <span>${escHtml(tr("settings.ai.key_hint"))}</span></div>
          ${v.has_key ? `<button type="button" class="btn ghost sm" data-ai-rmkey>${escHtml(tr("settings.ai.key_remove"))}</button>` : ""}</div>`;
    }
    return `<div class="note">${escHtml(tr("settings.ai.privacy"))}</div>
      ${this._consentsHtml()}
      <div class="lbl" style="margin-top:8px" id="ai-prov">${escHtml(tr("settings.ai.provider"))}</div>
      <div class="opts" role="radiogroup" aria-labelledby="ai-prov">${opts}</div>
      ${prov}
      <div class="f"><label for="ai-bud">${escHtml(tr("settings.ai.budget"))}</label>
        <input type="number" id="ai-bud" min="0" max="${hard}" step="1" inputmode="numeric" style="max-width:160px" data-b="ai.budget_cap" value="${escHtml(a.budget_cap)}">
        <span class="muted">${escHtml(tr("settings.ai.budget_hint", { cap: hard }))}</span>
        <span class="muted" role="status">${escHtml(tr("settings.ai.usage", { calls: b.calls ?? 0, cap: b.cap ?? a.budget_cap, left: b.remaining ?? 0 }))}</span></div>
      <div class="row" style="border:0;padding:0"><div class="who"><span class="${v.last_test ? (v.last_test.ok ? "ok" : "warn") : ""}" role="status">${escHtml(aiTestText(v.last_test))}</span>
        <span>${escHtml(tr("settings.ai.test_hint"))}</span></div>
        <button type="button" class="btn ghost sm" data-ai-test ${this._aiTesting ? "disabled aria-busy=\"true\"" : ""}>${escHtml(tr(this._aiTesting ? "settings.ai.test_busy" : "settings.ai.test"))}</button></div>
      ${this._bar("ai")}`;
  }

  /** Per-purpose consent: switch, mode, pros/risks, consent date and last use. Setup shows "categorize" only. */
  _consentsHtml() {
    const { escHtml, fmtDate } = window._fd;
    const c = this._d.consents;
    if (!c) return "";
    const purposes = c.purposes || {};
    let ids = Object.keys(purposes);
    if (!ids.length) ids = Object.keys(c.consents || {});
    if (this._embedded) ids = ids.filter((id) => id === "categorize");
    const line = (key, purpose) => {
      const k = String(key).includes(".") ? String(key) : `ai.purpose.${purpose}.${key}`;
      return `<li>${escHtml(tr(k))}</li>`;
    };
    const blocks = ids.map((id) => {
      const info = purposes[id] || {};
      const st = (c.consents || {})[id] || {};
      const on = !!st.granted;
      const mode = st.mode || info.mode;
      const tk = `ai.purpose.${id}.title`;
      const title = tr(tk) === tk ? id : tr(tk);
      const meta = [on && st.granted_at ? tr("settings.ai.consent_on", { date: fmtDate(st.granted_at, true) }) : tr("settings.ai.consent_off"),
        st.used_at ? tr("settings.ai.used", { date: fmtDate(st.used_at, true) }) : tr("settings.ai.used_never")].join(" · ");
      const pros = (info.pros || []).slice(0, 3), risks = (info.risks || []).slice(0, 3);
      return `<div class="cons"><div class="row" style="border:0"><div class="who"><b>${escHtml(title)}${mode ? `<span class="chip">${escHtml(tr("ai.mode." + mode))}</span>` : ""}</b><span>${escHtml(meta)}</span></div>
          <span class="hit"><button type="button" class="sw" role="switch" aria-checked="${on}" data-consent="${escHtml(id)}" aria-label="${escHtml(title)}"></button></span></div>
        ${pros.length ? `<div class="lbl">${escHtml(tr("settings.ai.pros"))}</div><ul class="pc">${pros.map((k) => line(k, id)).join("")}</ul>` : ""}
        ${risks.length ? `<div class="lbl">${escHtml(tr("settings.ai.risks"))}</div><ul class="pc">${risks.map((k) => line(k, id)).join("")}</ul>` : ""}</div>`;
    }).join("");
    return this._embedded ? blocks : `<div class="lbl" style="margin-top:8px">${escHtml(tr("settings.ai.consent_title"))}</div>${blocks}`;
  }

  async _toggleConsent(purpose) {
    const cur = ((this._d.consents || {}).consents || {})[purpose] || {};
    try {
      const res = await this._put("setup/ai/consents", { purpose, granted: !cur.granted });
      this._d.consents = res && res.consents ? res : await this._hass.callApi("GET", `${DOMAIN}/setup/ai/consents`);
      this._msg.ai = "";
      this._renderSec("ai");
      this._toast(tr("settings.saved"), "success");
    } catch (e) { this._fail(`${tr("settings.ai.consent_err")}${this._errText(e).replace(tr("settings.error"), "")}`, "ai"); }
  }

  async _testAi() {
    if (this._aiTesting) return;
    this._aiTesting = true;
    this._renderSec("ai");
    try {
      const r = await this._hass.callApi("POST", `${DOMAIN}/setup/ai/test`, {});
      this._d.ai = r.ai;
      const t = r.test || {};
      this._toast(aiTestText(t), t.ok ? "success" : "error");
    } catch (e) { this._fail(this._errText(e), "ai"); }
    this._aiTesting = false;
    this._renderSec("ai");
  }

  _s_points() {
    const { escHtml } = window._fd;
    const v = this._d.points;
    if (!v) return this._loading("points");
    const p = this._dr.points;
    const ev = v.event || POINTS_EVENT;
    const every = v.every || 7;
    const intro = tr("settings.points.intro", { event: "\u0001", every }).replace("\u0001", `<code>${escHtml(ev)}</code>`);
    const states = (this._hass && this._hass.states) || {};
    const q = (p.q || "").trim().toLowerCase();
    const matches = Object.keys(states).filter((id) => /^(counter|input_number)\./.test(id))
      .filter((id) => !q || id.toLowerCase().includes(q) || String((states[id].attributes || {}).friendly_name || "").toLowerCase().includes(q))
      .sort().slice(0, 8);
    const sel = p.entity_id
      ? `<div class="row"><div class="who"><b>${escHtml(((states[p.entity_id] || {}).attributes || {}).friendly_name || p.entity_id)}</b><span>${escHtml(p.entity_id)}</span></div>
          <button type="button" class="btn ghost sm" data-pt-clear>${escHtml(tr("settings.points.clear"))}</button></div>` : "";
    const list = matches.length
      ? `<div class="pick" role="group" aria-label="${escHtml(tr("settings.points.entity"))}">${matches.map((id) =>
          `<button type="button" data-pt="${escHtml(id)}" aria-pressed="${p.entity_id === id}"><b>${escHtml((states[id].attributes || {}).friendly_name || id)}</b><span>${escHtml(id)}</span></button>`).join("")}</div>`
      : `<p class="muted">${escHtml(tr("settings.points.none"))}</p>`;
    return `<p class="muted" style="font-size:12.5px">${intro}</p>
      <div class="f"><label for="pt-q">${escHtml(tr("settings.points.entity"))}</label>
      <p class="muted" style="margin:0">${escHtml(tr("settings.points.entity_hint"))}</p>${sel}
      <input type="text" id="pt-q" data-b="points.q" value="${escHtml(p.q || "")}" placeholder="${escHtml(tr("settings.points.search"))}" autocomplete="off" autocapitalize="off" spellcheck="false" aria-label="${escHtml(tr("settings.points.search"))}">
      ${list}</div>
      ${v.answered_total != null ? `<p class="muted">${escHtml(tr("settings.points.answered", { n: v.answered_total }))}</p>` : ""}
      ${this._bar("points")}`;
  }

  _goalSummary(g) {
    const eur = (x) => new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(Number(x) || 0);
    const cats = window._fd.CAT_LABELS || {};
    return tr(`settings.goals.sum.${g.kind}`, {
      amount: eur(g.target_amount ?? g.cap_amount ?? g.monthly_amount), date: g.target_date || "",
      category: cats[g.category] || g.category || "", rate: g.rate_percent ?? "", reserve: g.reserve_id || "",
    });
  }

  _s_goals() {
    const { escHtml } = window._fd;
    const goals = this._d.goals;
    if (!goals) return this._loading("goals");
    const persons = (this._d.setup || {}).persons || [];
    const ownerName = (o) => (o === "shared" ? tr("settings.owner_shared") : this._dn(persons.find((p) => p.name === o) || { name: o }));
    const list = goals.length
      ? goals.map((g) => `<div class="goal"><div class="who"><b>${escHtml(g.name)}</b><span>${escHtml(tr("settings.goals.kind." + g.kind))} · ${escHtml(this._goalSummary(g))} · ${escHtml(ownerName(g.owner))}</span></div>
          <button type="button" class="btn ghost sm" data-goal-rm="${escHtml(g.id)}" aria-label="${escHtml(tr("settings.goals.remove") + ": " + g.name)}">${escHtml(tr("settings.goals.remove"))}</button></div>`).join("")
      : `<p class="muted">${escHtml(tr("settings.goals.empty"))}</p>`;
    const g = this._dr.goal || (this._dr.goal = { kind: "target_by_date", name: "", owner: "shared" });
    const kinds = GOAL_KINDS.map((k) => `<button type="button" role="radio" aria-checked="${g.kind === k}" data-c="goal.kind=${k}">${escHtml(tr("settings.goals.kind." + k))}</button>`).join("");
    const owners = [["shared", tr("settings.owner_shared")]].concat(persons.map((p) => [p.name, this._dn(p)]))
      .map(([v, l]) => `<button type="button" role="radio" aria-checked="${g.owner === v}" data-c="goal.owner=${escHtml(v)}">${escHtml(l)}</button>`).join("");
    const num = (k, extra = "") => `<div class="f"><label for="g-${k}">${escHtml(tr("settings.goals." + k))}</label>
      <input type="number" id="g-${k}" min="0" step="any" inputmode="decimal" data-b="goal.${k}" value="${escHtml(g[k] ?? "")}" ${extra}></div>`;
    const txt = (k, ph = "") => `<div class="f"><label for="g-${k}">${escHtml(tr("settings.goals." + k))}</label>
      <input type="text" id="g-${k}" data-b="goal.${k}" value="${escHtml(g[k] ?? "")}" placeholder="${escHtml(ph)}" autocomplete="off"></div>`;
    const cats = window._fd.CAT_LABELS || {};
    const catField = Object.keys(cats).length
      ? `<div class="lbl" id="g-cat-l">${escHtml(tr("settings.goals.category"))}</div><div class="opts" role="radiogroup" aria-labelledby="g-cat-l">${Object.entries(cats).map(([k, l]) =>
          `<button type="button" role="radio" aria-checked="${g.category === k}" data-c="goal.category=${escHtml(k)}">${escHtml(l)}</button>`).join("")}</div>`
      : txt("category", "groceries");
    const fields = {
      target_by_date: num("target_amount") + txt("target_date", "2027-06-30"),
      category_cap: catField + num("cap_amount"),
      savings_rate: num("rate_percent", 'max="100"'),
      reserve_topup: txt("reserve_id") + num("monthly_amount"),
    }[g.kind];
    return `<p class="muted">${escHtml(tr("settings.goals.intro"))}</p>${list}
      <h4>${escHtml(tr("settings.goals.add"))}</h4>
      <div class="opts" role="radiogroup" aria-label="${escHtml(tr("settings.goals.add"))}">${kinds}</div>
      ${txt("name")}
      <div class="lbl" id="g-own-l">${escHtml(tr("settings.goals.owner"))}</div><div class="opts" role="radiogroup" aria-labelledby="g-own-l">${owners}</div>
      ${fields}
      <div class="bar"><button type="button" class="btn" data-goal-add>${escHtml(tr("settings.goals.add"))}</button></div>`;
  }

  _s_banks() {
    const { escHtml } = window._fd;
    return `<p class="muted" style="font-size:12.5px">${escHtml(tr("settings.banks.body"))}</p>
      <a class="btn ghost" href="/config/integrations/integration/${DOMAIN}">${escHtml(tr("settings.banks.open"))}</a>`;
  }

  _s_advanced() {
    const { escHtml } = window._fd;
    return `<div class="row" style="border:0"><div class="who"><b>${escHtml(tr("settings.adv.demo"))}</b><span>${escHtml(tr("settings.adv.demo_hint"))}</span></div>
        <button type="button" class="btn ghost" data-adv="demo">${escHtml(tr("settings.adv.demo"))}</button></div>
      <div class="row"><div class="who"><b>${escHtml(tr("settings.adv.setup"))}</b><span>${escHtml(tr("settings.adv.setup_hint"))}</span></div>
        <button type="button" class="btn ghost" data-adv="setup">${escHtml(tr("settings.adv.setup"))}</button></div>`;
  }

  // ---- events -----------------------------------------------------------
  _bindSet(path, value) {
    const dot = path.indexOf(".");
    const ns = path.slice(0, dot), k = path.slice(dot + 1);
    if (ns === "ai" && k === "provider") { this._dr.ai.provider = value; return; }
    this._dr[ns][k] = value;
  }

  _wire() {
    const sh = this.shadowRoot;
    sh.addEventListener("click", (ev) => {
      const t = ev.target.closest("button");
      if (!t) return;
      const d = t.dataset;
      if (d.nav) { this._scrollTo(d.nav); return; }
      if (d.sw) {
        const u = (this._data.ha_users || []).find((x) => x.id === d.sw);
        if (u) { this._toggleUser(u); this._renderSec("persons"); this._renderSec("accounts"); }
      } else if (t.id === "addp") {
        this._draft.persons.push({ name: "", ha_users: [], display_name: "", isNew: true });
        this._renderSec("persons");
        const inputs = sh.querySelectorAll("[data-free]");
        inputs[inputs.length - 1]?.focus();
      } else if (d.rm !== undefined) {
        this._removePerson(this._draft.persons[Number(d.rm)]);
        this._renderSec("persons"); this._renderSec("accounts");
      } else if (d.acc && d.owner.startsWith("user:")) {
        const u = (this._data.ha_users || []).find((x) => `user:${x.id}` === d.owner);
        if (!u) return;
        if (!this._personOf(u.id)) this._toggleUser(u);
        this._draft.owners[d.acc] = this._personOf(u.id).name;
        this._renderSec("persons"); this._renderSec("accounts");
      } else if (d.acc) {
        this._draft.owners[d.acc] = d.owner;
        this._renderSec("accounts");
      } else if (d.save) {
        this._saveSection(d.save);
      } else if (d.state) {
        const r = this._dr.region;
        r.state = r.state === d.state ? "" : d.state;
        this._renderSec("region");
      } else if (d.t) {
        const [ns, k] = [d.t.slice(0, d.t.indexOf(".")), d.t.slice(d.t.indexOf(".") + 1)];
        const o = this._dr[ns];
        o[k] = ns === "notif" ? o[k] === false : !o[k];
        this._renderSec(ns === "notif" ? "notifications" : ns);
      } else if (d.c) {
        const [path, ...rest] = d.c.split("=");
        this._bindSet(path, rest.join("="));
        this._renderSec(path.startsWith("ai.") ? "ai" : "goals");
      } else if (d.pt) {
        this._dr.points.entity_id = d.pt;
        this._renderSec("points");
      } else if (d.ptClear !== undefined) {
        this._dr.points.entity_id = "";
        this._renderSec("points");
      } else if (d.consent) {
        this._toggleConsent(d.consent);
      } else if (d.aiRmkey !== undefined) {
        this._removeKey();
      } else if (d.aiTest !== undefined) {
        this._testAi();
      } else if (d.goalAdd !== undefined) {
        this._addGoal();
      } else if (d.goalRm) {
        this._removeGoal(d.goalRm);
      } else if (d.adv === "demo") {
        this._toggleDemo();
      } else if (d.adv === "setup") {
        this.dispatchEvent(new CustomEvent("fd-navigate", { bubbles: true, composed: true, detail: { target: "setup" } }));
      }
    });
    sh.addEventListener("input", (ev) => {
      const el = ev.target;
      const d = el.dataset;
      if (d.b) {
        const v = el.type === "range" ? Number(el.value) : el.value;
        this._bindSet(d.b, v);
        if (el.type === "range") {
          const out = sh.querySelector(`[data-out="${d.b}"]`);
          if (out) out.textContent = String(v);
        } else if (d.b === "points.q") {
          this._renderSec("points");
          const q = sh.getElementById("pt-q");
          if (q) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
        }
        return;
      }
      let person = null;
      if (d.name) person = this._personOf(d.name);
      else if (d.free !== undefined) person = this._draft.persons[Number(d.free)];
      else if (d.nickUser) { person = this._personOf(d.nickUser); if (person) person.display_name = el.value; this._renderSec("accounts"); return; }
      else if (d.nickFree !== undefined) { person = this._draft.persons[Number(d.nickFree)]; if (person) person.display_name = el.value; this._renderSec("accounts"); return; }
      if (!person) return;
      const old = person.name;
      person.name = el.value;
      for (const k of Object.keys(this._draft.owners)) if (this._draft.owners[k] === old) this._draft.owners[k] = el.value;
      this._renderSec("accounts");
    });
  }

  _fail(msg, sec = "persons") {
    this._error = msg;
    this._msg[sec] = sec === "persons" ? "" : msg;
    const el = this.shadowRoot.getElementById("err-persons");
    if (sec === "persons" && el) el.textContent = msg;
    else if (sec !== "persons") this._renderSec(sec);
    this._toast(msg, "error");
  }

  _toast(message, type) {
    this.dispatchEvent(new CustomEvent("fd-toast", { bubbles: true, composed: true, detail: { message, type } }));
  }

  _errText(e) {
    const detail = (e && e.body && (e.body.detail || e.body.error)) || (e && e.message) || "";
    return detail ? `${tr("settings.error")}: ${detail}` : tr("settings.error");
  }

  _done(sec, payload) {
    this._msg[sec] = "";
    this._toast(tr("settings.saved"), "success");
    this.dispatchEvent(new CustomEvent("fd-settings-saved", { bubbles: true, composed: true, detail: { section: sec, payload } }));
  }

  _saveSection(kind) {
    return { assign: () => this._save(), payday: () => this._savePayday(), region: () => this._saveRegion(),
      notif: () => this._saveNotif(), ai: () => this._saveAi(), points: () => this._savePoints() }[kind]?.();
  }

  async _put(path, body) {
    return this._hass.callApi("PUT", `${DOMAIN}/${path}`, body);
  }

  async _savePayday() {
    const paydays = [];
    for (const [person, v] of Object.entries(this._dr.payday)) {
      if (v === "") continue;
      const day = Number(v);
      if (!Number.isInteger(day) || day < 1 || day > 31) return this._fail(`${person}: ${tr("settings.payday_err")}`, "payday"), false;
      paydays.push({ person, day });
    }
    if (!paydays.length) return true;
    try {
      this._d.setup = await this._put("setup", { paydays });
      this._initDraft("setup");
      this._renderSec("payday"); this._done("payday", this._d.setup);
      return true;
    } catch (e) { this._fail(this._errText(e), "payday"); return false; }
  }

  async _saveRegion() {
    const r = this._dr.region;
    if (r.postcode && !/^\d{5}$/.test(r.postcode)) return this._fail(tr("settings.postcode_err"), "region"), false;
    if (!r.state) return true;
    try {
      this._d.setup = await this._put("setup", { region: { state: r.state, ...(r.postcode ? { postcode: r.postcode } : {}) } });
      this._initDraft("setup");
      this._renderSec("region"); this._done("region", this._d.setup);
      return true;
    } catch (e) { this._fail(this._errText(e), "region"); return false; }
  }

  async _saveNotif() {
    try {
      this._d.setup = await this._put("setup", { notifications: { ...this._dr.notif } });
      this._initDraft("setup");
      this._renderSec("notifications"); this._done("notifications", this._d.setup);
      return true;
    } catch (e) { this._fail(this._errText(e), "notifications"); return false; }
  }

  async _saveAi() {
    if (!this._d.ai) return true;
    const a = this._dr.ai;
    const cap = Number(a.budget_cap);
    const hard = (this._d.ai.budget || {}).hard_cap || 1000;
    if (!Number.isInteger(cap) || cap < 0 || cap > hard) return this._fail(tr("settings.ai.budget_err", { cap: hard }), "ai"), false;
    const body = { provider: a.provider, budget_cap: cap };
    if (a.provider === "ha") body.ha_agent = (a.ha_agent || "").trim();
    else body.model = (a.model || "").trim();
    if (a.api_key) body.api_key = a.api_key;
    try {
      this._d.ai = await this._put("setup/ai", body);
      this._initDraft("ai");
      this._renderSec("ai"); this._done("ai", this._d.ai);
      return true;
    } catch (e) { this._fail(this._errText(e), "ai"); return false; }
  }

  async _removeKey() {
    try {
      this._d.ai = await this._put("setup/ai", { api_key: "" });
      const keep = { ...this._dr.ai, api_key: "" };
      this._initDraft("ai");
      this._dr.ai = { ...keep };
      this._renderSec("ai");
      this._toast(tr("settings.ai.key_removed"), "success");
    } catch (e) { this._fail(this._errText(e), "ai"); }
  }

  async _savePoints() {
    if (!this._d.points) return true;
    const entity_id = this._dr.points.entity_id || "";
    if (entity_id === (this._d.points.entity_id || "")) return true;
    try {
      this._d.points = await this._put("setup/points", { entity_id });
      this._initDraft("points");
      this._renderSec("points"); this._done("points", this._d.points);
      return true;
    } catch (e) { this._fail(this._errText(e), "points"); return false; }
  }

  async _addGoal() {
    const g = this._dr.goal;
    const body = { kind: g.kind, name: (g.name || "").trim(), owner: g.owner || "shared" };
    const need = { target_by_date: ["target_amount", "target_date"], category_cap: ["category", "cap_amount"],
      savings_rate: ["rate_percent"], reserve_topup: ["reserve_id", "monthly_amount"] }[g.kind];
    if (!body.name || need.some((k) => g[k] === undefined || g[k] === "")) return this._fail(tr("settings.goals.err"), "goals");
    for (const k of need) body[k] = /amount|percent/.test(k) ? Number(g[k]) : String(g[k]).trim();
    try {
      await this._hass.callApi("POST", `${DOMAIN}/setup/goals`, body);
      this._d.goals = (await this._hass.callApi("GET", `${DOMAIN}/setup/goals`)).goals || [];
      this._dr.goal = null;
      this._msg.goals = "";
      this._renderSec("goals");
      this._toast(tr("settings.goals.added"), "success");
      this.dispatchEvent(new CustomEvent("fd-settings-saved", { bubbles: true, composed: true, detail: { section: "goals" } }));
    } catch (e) { this._fail(this._errText(e), "goals"); }
  }

  async _removeGoal(id) {
    try {
      await this._hass.callApi("DELETE", `${DOMAIN}/setup/goals/${encodeURIComponent(id)}`);
      this._d.goals = (this._d.goals || []).filter((g) => g.id !== id);
      this._renderSec("goals");
      this._toast(tr("settings.goals.removed"), "success");
      this.dispatchEvent(new CustomEvent("fd-settings-saved", { bubbles: true, composed: true, detail: { section: "goals" } }));
    } catch (e) { this._fail(this._errText(e), "goals"); }
  }

  async _toggleDemo() {
    try {
      await this._hass.callApi("POST", `${DOMAIN}/demo/toggle`);
      this._toast(tr("settings.adv.demo_done"), "success");
      this.dispatchEvent(new CustomEvent("fd-settings-saved", { bubbles: true, composed: true, detail: { section: "advanced" } }));
    } catch (e) { this._fail(this._errText(e), "advanced"); }
  }

  async _save() {
    if (this._saving) return false;
    const names = this._draft.persons.map((p) => p.name.trim());
    if (names.some((n) => !n)) return this._fail(tr("settings.err_name")), false;
    if (new Set(names.map((n) => n.toLowerCase())).size !== names.length) return this._fail(tr("settings.err_dup")), false;
    const body = {
      persons: this._draft.persons.map((p) => ({ name: p.name.trim(), display_name: (p.display_name || "").trim(), ha_users: p.ha_users })),
      accounts: (this._data.accounts || []).map((a) => ({
        key: a.key,
        owner: (this._draft.owners[a.key] || "").trim(),
      })),
    };
    this._saving = true;
    const btns = this.shadowRoot.querySelectorAll("[data-save=assign]");
    btns.forEach((b) => { b.disabled = true; b.textContent = tr("settings.saving"); });
    try {
      const resp = await this._hass.callApi("PUT", `${DOMAIN}/assignments`, body);
      this._error = "";
      this._saving = false;
      this.data = resp;
      this._toast(tr("settings.saved"), "success");
      this.dispatchEvent(new CustomEvent("fd-assignments-saved", { bubbles: true, composed: true, detail: { payload: resp } }));
      // Names changed: owner pickers elsewhere on the page show the nickname.
      this._loaded.delete("setup");
      if (this._isPage) { this._ensure("payday"); this._ensure("goals"); }
      return true;
    } catch (e) {
      this._saving = false;
      btns.forEach((b) => { b.disabled = false; b.textContent = tr("settings.save"); });
      this._fail(this._errText(e));
      return false;
    }
  }
}

window._fd.defineOnce("fd-settings", FdSettings);
