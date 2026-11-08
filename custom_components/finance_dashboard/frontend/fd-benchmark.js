/**
 * fd-benchmark — your actual yearly spend vs. the typical household, per dimension.
 * Reachable ONLY from Haushalt -> Jahr (fd-home "Vergleich"); the route itself stays.
 *
 *   GET finance_dashboard/benchmark[?demo=1]
 *     {comparisons:[{basis, user_value, actual_value, plan_value, benchmark_value, deviation_pct,
 *       plan_deviation_pct, position (0..1, .5 typical), band (below|typical|above), extrapolated,
 *       months_covered, year, label, unit, statistic, source, source_url, publisher, reference_year,
 *       level, requested_level, derived, household_size}], basis:{year, months_covered, extrapolated,
 *       has_actual, scale}, teaser, dataset, location, references, unavailable, has_plan}
 *   Overview first: every dimension on one shared deviation scale (outliers first, typical band
 *   shaded, dot = you, hollow diamond = plan); a tap expands statistic, source, year, fallback
 *   level, extrapolation note, meaning and next step. Every figure keeps statistic + source + year.
 *   403 (non-admin) shows a plain note.
 *
 * Properties: hass (required), demo (boolean, ?demo=1). No events (fd-navigate back via the header).
 */

const DOMAIN = "finance_dashboard";

// Fallback texts: used until locales/*.json carry the bm.* keys.
const FB = {
  "de": {
    "bm.title": "Vergleich mit dem Durchschnitt",
    "bm.back": "Zurück",
    "bm.loading": "Lade Vergleich…",
    "bm.error": "Der Vergleich konnte nicht geladen werden.",
    "bm.retry": "Erneut versuchen",
    "bm.denied": "Der Vergleich ist nur für Administratoren sichtbar.",
    "bm.intro": "Dein geplantes Budget neben amtlichen Durchschnittswerten. Eine Orientierung, kein Ziel: Wohnort, Alter und Lebenssituation erklären viele Unterschiede.",
    "bm.no_plan": "Für den Vergleich fehlt noch ein Haushaltsplan.",
    "bm.empty": "Zu deinem Plan gibt es noch keinen passenden Vergleichswert.",
    "bm.you": "Dein Plan",
    "bm.ref": "Vergleichswert",
    "bm.diff_less": "$amount weniger als der Vergleichswert",
    "bm.diff_more": "$amount mehr als der Vergleichswert",
    "bm.diff_same": "Etwa gleich wie der Vergleichswert",
    "bm.meaning": "Was das heißt",
    "bm.meaning_more": "Ein Wert über dem Durchschnitt hat oft nachvollziehbare Gründe, etwa Wohnort oder Haushaltsgröße.",
    "bm.meaning_less": "Ein Wert unter dem Durchschnitt zeigt, dass hier Luft ist. Ob das passt, entscheidest du.",
    "bm.next_housing": "Möglicher nächster Schritt: Strom-, Gas- und Internetverträge unter „Verträge“ ansehen.",
    "bm.next_other": "Möglicher nächster Schritt: die Posten im Haushaltsplan ansehen.",
    "bm.stat.median": "Median",
    "bm.stat.mean": "Durchschnitt (Ø)",
    "bm.stat.aggregate_ratio": "Gesamtverhältnis",
    "bm.stat.statutory": "gesetzlich festgelegt",
    "bm.stat.threshold_60pct_median": "60 % des Medians",
    "bm.stat.manual": "eigene Angabe",
    "bm.fallback": "Bundeswert – für deine Region gibt es keinen genaueren Wert",
    "bm.fallback_level": "Wert auf Ebene „$used“ statt „$wanted“",
    "bm.level.postcode": "Postleitzahl",
    "bm.level.district": "Landkreis",
    "bm.level.state": "Bundesland",
    "bm.level.country": "Bund",
    "bm.derived": "aus einer veröffentlichten Zahl berechnet",
    "bm.size": "Haushaltsgröße: $size",
    "bm.source": "Quelle",
    "bm.year": "Stand $year",
    "bm.location": "Verglichen mit: $place, $size",
    "bm.location_size": "$size Personen",
    "bm.floor": "Untergrenze",
    "bm.floor_note": "Der Regelbedarf ist das gesetzliche Minimum, kein Durchschnitt, den man unterbieten soll.",
    "bm.context": "Weitere Orientierung",
    "bm.unavailable": "Noch keine amtliche Quelle",
    "bm.unavailable_note": "Für diese Bereiche zeigen wir bewusst keinen Wert.",
    "bm.dataset": "Datensatz $version, Stand $date",
    "bm.head.above": "$n Bereiche deutlich über typisch",
    "bm.head.above_one": "1 Bereich deutlich über typisch",
    "bm.head.below": "$n Bereiche deutlich unter typisch",
    "bm.head.below_one": "1 Bereich deutlich unter typisch",
    "bm.head.typical": "Alles im typischen Bereich",
    "bm.head.sub": "$n Bereiche verglichen",
    "bm.basis_actual": "Deine echten Ausgaben $year",
    "bm.basis_extrap": "Deine echten Ausgaben $year, hochgerechnet aus $n Monaten",
    "bm.basis_plan": "Noch keine Buchungen im Jahr $year: verglichen wird dein Plan",
    "bm.scale_below": "unter typisch",
    "bm.scale_typical": "typisch",
    "bm.scale_above": "über typisch",
    "bm.band.below": "unter typisch",
    "bm.band.typical": "typisch",
    "bm.band.above": "über typisch",
    "bm.dev_up": "$pct % über typisch",
    "bm.dev_down": "$pct % unter typisch",
    "bm.dev_same": "typisch",
    "bm.you_actual": "Du (Ist)",
    "bm.you_plan": "Du (Plan)",
    "bm.typical": "Typisch",
    "bm.plan_mark": "Plan",
    "bm.on_plan": "auf Basis deines Plans",
    "bm.extrap": "hochgerechnet aus $n Monaten",
    "bm.details": "Details",
    "bm.legend_you": "Du",
    "bm.legend_plan": "Plan",
    "bm.legend_band": "typischer Bereich (±10 %)",
    "bm.more": "Weitere Orientierung und fehlende Quellen"
  },
  "en": {
    "bm.title": "Comparison with the average",
    "bm.back": "Back",
    "bm.loading": "Loading comparison…",
    "bm.error": "The comparison could not be loaded.",
    "bm.retry": "Try again",
    "bm.denied": "The comparison is only visible to administrators.",
    "bm.intro": "Your planned budget next to official averages. A guide, not a target: location, age and circumstances explain many differences.",
    "bm.no_plan": "A household plan is needed for the comparison.",
    "bm.empty": "There is no matching reference value for your plan yet.",
    "bm.you": "Your plan",
    "bm.ref": "Reference",
    "bm.diff_less": "$amount less than the reference",
    "bm.diff_more": "$amount more than the reference",
    "bm.diff_same": "About the same as the reference",
    "bm.meaning": "What it means",
    "bm.meaning_more": "A value above the average often has understandable reasons, such as location or household size.",
    "bm.meaning_less": "A value below the average shows some room here. Whether that fits is up to you.",
    "bm.next_housing": "Possible next step: look at electricity, gas and internet under \"Contracts\".",
    "bm.next_other": "Possible next step: look at the items in the household plan.",
    "bm.stat.median": "Median",
    "bm.stat.mean": "Average (mean)",
    "bm.stat.aggregate_ratio": "Aggregate ratio",
    "bm.stat.statutory": "set by law",
    "bm.stat.threshold_60pct_median": "60% of the median",
    "bm.stat.manual": "own entry",
    "bm.fallback": "National value – no more specific value exists for your region",
    "bm.fallback_level": "Value at level \"$used\" instead of \"$wanted\"",
    "bm.level.postcode": "postcode",
    "bm.level.district": "district",
    "bm.level.state": "state",
    "bm.level.country": "country",
    "bm.derived": "calculated from a published figure",
    "bm.size": "Household size: $size",
    "bm.source": "Source",
    "bm.year": "as of $year",
    "bm.location": "Compared with: $place, $size",
    "bm.location_size": "$size people",
    "bm.floor": "Floor",
    "bm.floor_note": "The standard need is the legal minimum, not an average to undercut.",
    "bm.context": "More context",
    "bm.unavailable": "No official source yet",
    "bm.unavailable_note": "We deliberately show no value for these areas.",
    "bm.dataset": "Dataset $version, as of $date",
    "bm.head.above": "$n areas clearly above typical",
    "bm.head.above_one": "1 area clearly above typical",
    "bm.head.below": "$n areas clearly below typical",
    "bm.head.below_one": "1 area clearly below typical",
    "bm.head.typical": "Everything in the typical range",
    "bm.head.sub": "$n areas compared",
    "bm.basis_actual": "Your actual spend $year",
    "bm.basis_extrap": "Your actual spend $year, extrapolated from $n months",
    "bm.basis_plan": "No bookings in $year yet: your plan is compared",
    "bm.scale_below": "below typical",
    "bm.scale_typical": "typical",
    "bm.scale_above": "above typical",
    "bm.band.below": "below typical",
    "bm.band.typical": "typical",
    "bm.band.above": "above typical",
    "bm.dev_up": "$pct % above typical",
    "bm.dev_down": "$pct % below typical",
    "bm.dev_same": "typical",
    "bm.you_actual": "You (actual)",
    "bm.you_plan": "You (plan)",
    "bm.typical": "Typical",
    "bm.plan_mark": "Plan",
    "bm.on_plan": "based on your plan",
    "bm.extrap": "extrapolated from $n months",
    "bm.details": "Details",
    "bm.legend_you": "You",
    "bm.legend_plan": "Plan",
    "bm.legend_band": "typical range (±10 %)",
    "bm.more": "More context and missing sources"
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

const STATES = {
  BW: "Baden-Württemberg", BY: "Bayern", BE: "Berlin", BB: "Brandenburg", HB: "Bremen", HH: "Hamburg",
  HE: "Hessen", MV: "Mecklenburg-Vorpommern", NI: "Niedersachsen", NW: "Nordrhein-Westfalen",
  RP: "Rheinland-Pfalz", SL: "Saarland", SN: "Sachsen", ST: "Sachsen-Anhalt", SH: "Schleswig-Holstein", TH: "Thüringen",
};

const CSS = `
:host { display: block; }
.root { overflow-wrap: anywhere; container: bench / inline-size; color: var(--fd-t1); font-size: 13px; line-height: 1.4; }
button, a { font: inherit; }
h3 { margin: 0 0 4px; font-size: 15px; font-weight: 500; }
.card { margin: 0 0 12px; padding: 12px 14px; border-radius: var(--fd-r-card); background: var(--fd-card); box-shadow: var(--fd-sh1); }
.muted { color: var(--fd-t2); font-size: 11.5px; }
.msg { padding: 28px 12px; text-align: center; color: var(--fd-t2); }
.btn { min-height: var(--fd-touch); margin-top: 12px; padding: 0 16px; border: 1px solid transparent; border-radius: var(--fd-r-pill); background: var(--fd-a700); color: #fff; font-weight: 500; cursor: pointer; }

/* hero: one sentence, then the basis */
.hero { background: linear-gradient(135deg, var(--fd-a50), var(--fd-card) 70%); border-left: 4px solid var(--fd-a500); }
.hero h2 { margin: 0; font-size: 20px; line-height: 1.25; font-weight: 500; color: var(--fd-a900); }
.hero.flag { border-left-color: var(--fd-near); }
.hero .sub { margin-top: 4px; color: var(--fd-t2); font-size: 12px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.cnt { display: inline-flex; align-items: center; gap: 6px; min-height: 28px; padding: 0 10px; border-radius: var(--fd-r-pill); font-size: 12px; font-weight: 500; background: var(--fd-sunk); color: var(--fd-t1); }
.cnt i { width: 8px; height: 8px; border-radius: 50%; background: var(--fd-t3); }
.cnt.above i { background: var(--fd-near); }
.cnt.below i { background: var(--fd-a500); }
.cnt.typical i { background: var(--fd-ok); }

/* overview: one shared scale */
.axis { display: grid; grid-template-columns: 1fr auto 1fr; font-size: 10.5px; color: var(--fd-t2); letter-spacing: .04em; text-transform: uppercase; padding-bottom: 4px; }
.axis span:last-child { text-align: right; }
.axis span:nth-child(2) { color: var(--fd-t1); }
.rows { list-style: none; margin: 0; padding: 0; }
.row { border-top: 1px solid var(--fd-line); }
.row:first-child { border-top: 0; }
.rowbtn { all: unset; box-sizing: border-box; display: block; width: 100%; padding: 10px 2px; cursor: pointer; border-radius: 8px; }
.rowbtn:focus-visible { outline: 2px solid var(--fd-a500); outline-offset: 2px; }
.rowbtn:hover { background: var(--fd-sunk); }
.top { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 2px 8px; }
.top b { font-weight: 500; font-size: 13.5px; }
.badge { font-size: 12px; font-weight: 500; padding: 0 8px; border-radius: var(--fd-r-pill); white-space: nowrap; }
.badge.above { background: var(--fd-near-bg); color: color-mix(in srgb, var(--fd-near) 72%, var(--fd-t1)); }
.badge.below { background: var(--fd-a100); color: var(--fd-a900); }
.badge.typical { background: var(--fd-ok-bg); color: color-mix(in srgb, var(--fd-ok) 72%, var(--fd-t1)); }
.scale { position: relative; display: block; height: 26px; margin: 4px 8px 0; }
.scale .rail { position: absolute; left: 0; right: 0; top: 12px; height: 2px; border-radius: 1px; background: var(--fd-line); }
.scale .band { position: absolute; left: 40%; width: 20%; top: 6px; height: 14px; border-radius: 7px; background: var(--fd-ok-bg); border: 1px dashed color-mix(in srgb, var(--fd-ok) 50%, transparent); box-sizing: border-box; }
.scale .mid { position: absolute; left: 50%; top: 4px; width: 2px; height: 18px; margin-left: -1px; background: var(--fd-t3); border-radius: 1px; }
.scale .dot { position: absolute; top: 6px; width: 14px; height: 14px; margin-left: -7px; border-radius: 50%; background: var(--fd-a700); border: 2px solid var(--fd-card); box-shadow: 0 0 0 1px var(--fd-a700); box-sizing: border-box; }
.scale .dot.above { background: var(--fd-near); box-shadow: 0 0 0 1px var(--fd-near); }
.scale .dot.typical { background: var(--fd-ok); box-shadow: 0 0 0 1px var(--fd-ok); }
.scale .plan { position: absolute; top: 9px; width: 8px; height: 8px; margin-left: -4px; transform: rotate(45deg); border: 2px solid var(--fd-t2); background: var(--fd-card); box-sizing: border-box; }
.vals { display: flex; flex-wrap: wrap; gap: 0 14px; font-size: 12px; color: var(--fd-t2); }
.vals b { color: var(--fd-t1); font-weight: 500; }
.chev { display: inline-block; margin-left: 6px; transition: transform .15s; color: var(--fd-t3); }
.rowbtn[aria-expanded="true"] .chev { transform: rotate(90deg); }
.det { padding: 2px 4px 12px; }
.det[hidden] { display: none; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 8px; font-size: 11px; color: var(--fd-t2); align-items: center; }
.legend i { display: inline-block; vertical-align: middle; margin-right: 4px; }
.legend .l-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--fd-a700); }
.legend .l-plan { width: 8px; height: 8px; transform: rotate(45deg); border: 2px solid var(--fd-t2); box-sizing: border-box; }
.legend .l-band { width: 16px; height: 8px; border-radius: 4px; background: var(--fd-ok-bg); border: 1px dashed color-mix(in srgb, var(--fd-ok) 50%, transparent); box-sizing: border-box; }

.src { display: flex; flex-wrap: wrap; align-items: center; gap: 2px 6px; margin-top: 4px; }
.pill { display: inline-flex; padding: 0 8px; border-radius: var(--fd-r-pill); font-size: 10.5px; font-weight: 500; background: var(--fd-sunk); color: var(--fd-t2); }
.pill.fb { background: var(--fd-near-bg); color: color-mix(in srgb, var(--fd-near) 72%, var(--fd-t1)); }
a { color: var(--fd-a700); display: inline-flex; align-items: center; min-height: 28px; }
.mean { margin-top: 6px; padding: 8px 10px; border-left: 4px solid var(--fd-a500); border-radius: 8px; background: var(--fd-a50); color: var(--fd-a900); font-size: 12px; }
.mean b { display: block; font-size: 10.5px; letter-spacing: .06em; text-transform: uppercase; color: var(--fd-a700); }
.ref + .ref, .un + .un { border-top: 1px solid var(--fd-line); }
.ref { padding: 10px 0; }
.l1 { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 8px; }
.l1 b { font-weight: 500; }
.floor { border-left: 4px solid var(--fd-gold); padding-left: 10px; }
.un { padding: 6px 0; }
details.more > summary { cursor: pointer; min-height: var(--fd-touch); display: flex; align-items: center; font-weight: 500; font-size: 13px; }
details.more > summary:focus-visible { outline: 2px solid var(--fd-a500); outline-offset: 2px; }
a:focus-visible, button:focus-visible { outline: 2px solid var(--fd-a500); outline-offset: 2px; }
@container bench (min-width: 760px) {
  .rowbtn { display: grid; grid-template-columns: minmax(150px, 1fr) minmax(260px, 2fr) minmax(200px, 1fr); align-items: center; gap: 4px 16px; }
  .rowbtn .top { display: block; }
  .rowbtn .scale { margin-top: 0; }
  .axis { margin-left: calc(25% + 12px); margin-right: calc(25% + 12px); }
}
@media (prefers-reduced-motion: reduce) { .chev { transition: none; } }
`;

class FdBenchmark extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._data = null;
    this._demo = false;
    this._state = "loading"; // loading | ok | denied | error
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

  async load() {
    if (!this._hass) return;
    await window._fd.t("bm.title");
    this._state = "loading";
    this._render();
    const demo = this._demo || /[?&]demo=1\b/.test(location.search);
    try {
      this._data = await this._hass.callApi("GET", `${DOMAIN}/benchmark${demo ? "?demo=1" : ""}`);
      this._state = "ok";
    } catch (e) {
      console.warn("fd-benchmark: load failed:", e);
      this._state = e && (e.status_code === 403 || e.status === 403) ? "denied" : "error";
    }
    this._render();
  }

  _lang() { return (this._hass && this._hass.language) || navigator.language || "de"; }

  /** Value with its unit, e.g. "505 €/Monat" – decimals follow the magnitude of the unit. */
  _val(v, unit) {
    const n = (x, d) => new Intl.NumberFormat(this._lang(), { minimumFractionDigits: d, maximumFractionDigits: d }).format(x);
    const de = this._lang().toLowerCase().startsWith("de");
    switch (unit) {
      case "EUR/month": return `${n(v, 0)} €${de ? "/Monat" : "/month"}`;
      case "EUR/month/person": return `${n(v, 0)} €${de ? "/Monat und Person" : "/month/person"}`;
      case "EUR/m²/month": return `${n(v, 2)} €/m²${de ? "/Monat" : "/month"}`;
      case "EUR/kWh": return `${n(v, 3)} €/kWh`;
      case "kWh/year": return `${n(v, 0)} kWh${de ? "/Jahr" : "/year"}`;
      case "%": return `${n(v, 1)} %`;
      case "x Ø": return `${n(v, 1)}× Ø`;
      default: return `${n(v, 2)} ${unit || ""}`.trim();
    }
  }

  _stat(s) {
    const k = `bm.stat.${s}`;
    const t = tr(k);
    return t === k ? s || "" : t;
  }

  _label(x) {
    const en = !this._lang().toLowerCase().startsWith("de");
    return (en && x.label_en) || x.label || x.id || "";
  }

  _render() {
    const e = window._fd.escHtml;
    let body;
    if (this._state === "loading") body = `<div class="msg">${e(tr("bm.loading"))}</div>`;
    else if (this._state === "denied") body = `<div class="msg">${e(tr("bm.denied"))}</div>`;
    else if (this._state === "error") body = `<div class="msg">${e(tr("bm.error"))}<br><button class="btn" id="retry">${e(tr("bm.retry"))}</button></div>`;
    else body = this._body();
    const head = this.hasAttribute("embedded") ? "" : `<fd-subpage-header title="${e(tr("bm.title"))}"></fd-subpage-header>`;
    this.shadowRoot.innerHTML = `<style>${window._fd.SHARED_CSS}${CSS}</style><div class="root">${head}${body}</div>`;
    const r = this.shadowRoot.getElementById("retry");
    if (r) r.addEventListener("click", () => this.load());
    this.shadowRoot.querySelectorAll(".rowbtn").forEach((b) => b.addEventListener("click", () => {
      const open = b.getAttribute("aria-expanded") !== "true";
      b.setAttribute("aria-expanded", String(open));
      const det = this.shadowRoot.getElementById(b.getAttribute("aria-controls"));
      if (det) det.hidden = !open;
    }));
  }

  /** Source note in the UI language (dataset notes are English, `note_de` German). */
  _note(x) {
    const de = this._lang().toLowerCase().startsWith("de");
    return (de ? x.note_de : x.note) || (de ? "" : x.note_de) || "";
  }

  _source(x) {
    const e = window._fd.escHtml;
    const bits = [`<span class="pill">${e(this._stat(x.statistic))}</span>`];
    if (x.reference_year) bits.push(`<span class="muted">${e(x.source || "")} · ${e(tr("bm.year", { year: x.reference_year }))}</span>`);
    else if (x.source) bits.push(`<span class="muted">${e(x.source)}</span>`);
    if (x.household_size && x.household_size !== "all") bits.push(`<span class="muted">${e(tr("bm.size", { size: x.household_size }))}</span>`);
    if (x.level && x.requested_level && x.level !== x.requested_level) {
      const lv = (l) => tr(`bm.level.${l}`);
      const txt = x.level === "country" ? tr("bm.fallback") : tr("bm.fallback_level", { used: lv(x.level), wanted: lv(x.requested_level) });
      bits.push(`<span class="pill fb">${e(txt)}</span>`);
    }
    if (x.derived) bits.push(`<span class="pill">${e(tr("bm.derived"))}</span>`);
    // Only http(s) links: the URL comes from the bundled dataset, but never render javascript: URLs.
    if (x.source_url && /^https?:\/\//i.test(x.source_url)) {
      bits.push(`<a href="${e(x.source_url)}" target="_blank" rel="noopener noreferrer">${e(tr("bm.source"))}${x.publisher ? ": " + e(x.publisher) : ""} ↗</a>`);
    }
    return `<div class="src">${bits.join("")}</div>`;
  }

  _devText(c) {
    const p = Math.round(Math.abs(c.deviation_pct || 0) * 100);
    if (c.band === "typical" || p === 0) return tr("bm.dev_same");
    return tr(c.band === "above" ? "bm.dev_up" : "bm.dev_down", { pct: p });
  }

  /** Plan marker in percent (0..100) on the same scale as the dot, or null. */
  _planPos(c) {
    if (c.plan_deviation_pct == null || !isFinite(c.plan_deviation_pct)) return null;
    return Math.min(1, Math.max(0, 0.5 + c.plan_deviation_pct)) * 100;
  }

  _row(c, i) {
    const e = window._fd.escHtml;
    const band = c.band || "typical";
    const pos = Math.min(1, Math.max(0, c.position == null ? 0.5 : c.position)) * 100;
    const pp = c.basis === "plan" ? null : this._planPos(c);
    const bits = [];
    bits.push(`<span><b>${e(this._val(c.user_value, c.unit))}</b> ${e(tr(c.basis === "plan" ? "bm.you_plan" : "bm.you_actual"))}</span>`);
    bits.push(`<span>${e(tr("bm.typical"))} <b>${e(this._val(c.benchmark_value, c.unit))}</b></span>`);
    if (pp != null && c.plan_value != null) bits.push(`<span>${e(tr("bm.plan_mark"))} <b>${e(this._val(c.plan_value, c.unit))}</b></span>`);
    const housing = c.category === "housing_cold" || c.category === "housing_warm" || c.dimension === "housing_energy";
    const meaning = band === "typical" ? "" : `<div class="mean"><b>${e(tr("bm.meaning"))}</b>${e(tr(band === "above" ? "bm.meaning_more" : "bm.meaning_less"))}
      ${band === "above" ? " " + e(tr(housing ? "bm.next_housing" : "bm.next_other")) : ""}</div>`;
    const notes = [];
    if (c.extrapolated && c.months_covered) notes.push(`<span class="pill">${e(tr("bm.extrap", { n: c.months_covered }))}</span>`);
    if (c.basis === "plan") notes.push(`<span class="pill">${e(tr("bm.on_plan"))}</span>`);
    const id = `det${i}`;
    const aria = `${this._label(c)}: ${this._devText(c)}`;
    return `<li class="row"><button type="button" class="rowbtn" aria-expanded="false" aria-controls="${id}" aria-label="${e(aria)}">
  <span class="top"><b>${e(this._label(c))}</b><span><span class="badge ${band}">${e(this._devText(c))}</span><span class="chev" aria-hidden="true">›</span></span></span>
  <span class="scale" aria-hidden="true"><span class="rail"></span><span class="band"></span><span class="mid"></span>${pp != null ? `<span class="plan" style="left:${pp}%"></span>` : ""}<span class="dot ${band}" style="left:${pos}%"></span></span>
  <span class="vals">${bits.join("")}</span>
</button><div class="det" id="${id}" hidden>${notes.length ? `<div class="src">${notes.join("")}</div>` : ""}${this._source(c)}${meaning}</div></li>`;
  }

  _ref(r) {
    const e = window._fd.escHtml;
    const floor = r.id === "regelbedarf";
    return `<div class="ref${floor ? " floor" : ""}"><div class="l1"><b>${e(this._label(r))}${floor ? ` · ${e(tr("bm.floor"))}` : ""}</b><span>${e(this._val(r.value, r.unit))}</span></div>
  ${floor ? `<div class="muted">${e(tr("bm.floor_note"))}</div>` : (this._note(r) ? `<div class="muted">${e(this._note(r))}</div>` : "")}${this._source(r)}</div>`;
  }

  _hero(cmps, d) {
    const e = window._fd.escHtml;
    const n = (b) => cmps.filter((c) => c.band === b).length;
    const up = n("above"), down = n("below"), same = n("typical");
    const line = (k, c) => tr(c === 1 ? `bm.head.${k}_one` : `bm.head.${k}`, { n: c });
    const parts = [];
    if (up) parts.push(line("above", up));
    if (down) parts.push(line("below", down));
    const headline = parts.length ? parts.join(" · ") : tr("bm.head.typical");
    const b = d.basis || {};
    let basis = "";
    if (b.has_actual === false || (!b.has_actual && cmps.every((c) => c.basis === "plan"))) basis = tr("bm.basis_plan", { year: b.year || "" });
    else if (b.extrapolated && b.months_covered) basis = tr("bm.basis_extrap", { year: b.year || "", n: b.months_covered });
    else if (b.year) basis = tr("bm.basis_actual", { year: b.year });
    const loc = d.location || {};
    const place = loc.postcode ? loc.postcode : (STATES[loc.state] || loc.state || "");
    const size = loc.household_size ? tr("bm.location_size", { size: loc.household_size }) : "";
    const locLine = place && size ? tr("bm.location", { place, size }) : place || size ? tr("bm.location", { place: place || "DE", size: size || "–" }) : "";
    const chips = [["above", up], ["typical", same], ["below", down]].filter(([, c]) => c)
      .map(([k, c]) => `<span class="cnt ${k}"><i></i>${c} ${e(tr(`bm.band.${k}`))}</span>`).join("");
    return `<section class="card hero${up ? " flag" : ""}"><h2>${e(headline)}</h2>
      ${basis ? `<div class="sub">${e(basis)}</div>` : ""}${locLine ? `<div class="sub">${e(locLine)}</div>` : ""}
      <div class="chips">${chips}</div><p class="muted" style="margin:10px 0 0">${e(tr("bm.intro"))}</p></section>`;
  }

  _body() {
    const e = window._fd.escHtml;
    const d = this._data || {};
    // Outliers first: distance from "typical" on the shared scale.
    const cmps = [...(d.comparisons || [])].sort((a, b) => Math.abs((b.position ?? 0.5) - 0.5) - Math.abs((a.position ?? 0.5) - 0.5));
    const refs = d.references || [];
    const un = d.unavailable || [];
    const ds = d.dataset || {};
    if (!cmps.length) {
      return `<section class="card"><p class="muted" style="margin:0">${e(d.has_plan === false ? tr("bm.no_plan") : tr("bm.empty"))}</p></section>`;
    }
    const overview = `<section class="card" aria-label="${e(tr("bm.title"))}">
      <div class="axis" aria-hidden="true"><span>← ${e(tr("bm.scale_below"))}</span><span>${e(tr("bm.scale_typical"))}</span><span>${e(tr("bm.scale_above"))} →</span></div>
      <ul class="rows">${cmps.map((c, i) => this._row(c, i)).join("")}</ul>
      <div class="legend"><span><i class="l-dot"></i>${e(tr("bm.legend_you"))}</span><span><i class="l-plan"></i>${e(tr("bm.legend_plan"))}</span><span><i class="l-band"></i>${e(tr("bm.legend_band"))}</span></div></section>`;
    const more = refs.length || un.length ? `<section class="card"><details class="more"><summary>${e(tr("bm.more"))}</summary>
      ${refs.length ? `<h3 style="margin-top:8px">${e(tr("bm.context"))}</h3>${refs.map((r) => this._ref(r)).join("")}` : ""}
      ${un.length ? `<h3 style="margin-top:12px">${e(tr("bm.unavailable"))}</h3><p class="muted" style="margin:0 0 4px">${e(tr("bm.unavailable_note"))}</p>
        ${un.map((u) => `<div class="un"><b>${e(u.label || u.id)}</b>${this._note(u) ? `<div class="muted">${e(this._note(u))}</div>` : ""}</div>`).join("")}` : ""}
      </details></section>` : "";
    const foot = ds.dataset_version ? `<p class="muted">${e(tr("bm.dataset", { version: ds.dataset_version, date: ds.generated || "" }))}</p>` : "";
    return `${this._hero(cmps, d)}${overview}${more}${foot}`;
  }
}

window._fd.defineOnce("fd-benchmark", FdBenchmark);
