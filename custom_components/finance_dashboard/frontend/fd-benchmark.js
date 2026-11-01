/**
 * fd-benchmark — household plan vs. official benchmark per dimension.
 * Opened from the Start "Jahr" tab ("Vergleich").
 *
 *   GET finance_dashboard/benchmark
 *     {dataset, location, comparisons:[...], references:[...], unavailable:[{id,label,note}], has_plan}
 *   Every figure is shown with statistic, source and year; 403 (non-admin) shows a plain note.
 *
 * Properties: hass (required). No events.
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
    "bm.dataset": "Datensatz $version, Stand $date"
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
    "bm.dataset": "Dataset $version, as of $date"
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
.cols > div { min-width: 0; }
.root { overflow-wrap: anywhere; container: bench / inline-size; color: var(--fd-t1); font-size: 13px; line-height: 1.4; }
button, a { font: inherit; }
h3 { margin: 0 0 4px; font-size: 15px; font-weight: 500; }
.card { margin: 0 0 12px; padding: 12px 14px; border-radius: var(--fd-r-card); background: var(--fd-card); box-shadow: var(--fd-sh1); }
.muted { color: var(--fd-t2); font-size: 11.5px; }
.msg { padding: 28px 12px; text-align: center; color: var(--fd-t2); }
.btn { min-height: var(--fd-touch); margin-top: 12px; padding: 0 16px; border: 1px solid transparent; border-radius: var(--fd-r-pill); background: var(--fd-a700); color: #fff; font-weight: 500; cursor: pointer; }
.cmp + .cmp, .ref + .ref { border-top: 1px solid var(--fd-line); }
.cmp, .ref { padding: 12px 0; }
.l1 { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 8px; }
.l1 b { font-weight: 500; }
.bars { margin: 8px 0 4px; display: grid; gap: 4px; }
.bar { display: grid; grid-template-columns: 84px minmax(0, 1fr) auto; align-items: center; gap: 8px; font-size: 12px; }
.bar .tr { height: 10px; border-radius: 5px; background: var(--fd-sunk); overflow: hidden; }
.bar .tr i { display: block; height: 100%; border-radius: 5px; background: var(--fd-a500); }
.bar.ref .tr i { background: var(--fd-t3); }
.bar .v { text-align: right; font-weight: 500; white-space: nowrap; }
.diff { font-size: 12.5px; }
.src { display: flex; flex-wrap: wrap; align-items: center; gap: 2px 6px; margin-top: 4px; }
.pill { display: inline-flex; padding: 0 8px; border-radius: var(--fd-r-pill); font-size: 10.5px; font-weight: 500; background: var(--fd-sunk); color: var(--fd-t2); }
.pill.fb { background: var(--fd-near-bg); color: color-mix(in srgb, var(--fd-near) 72%, var(--fd-t1)); }
a { color: var(--fd-a700); display: inline-flex; align-items: center; min-height: 28px; }
.mean { margin-top: 6px; padding: 8px 10px; border-left: 4px solid var(--fd-a500); border-radius: 8px; background: var(--fd-a50); color: var(--fd-a900); font-size: 12px; }
.mean b { display: block; font-size: 10.5px; letter-spacing: .06em; text-transform: uppercase; color: var(--fd-a700); }
.floor { border-left: 4px solid var(--fd-gold); padding-left: 10px; }
.un { padding: 6px 0; }
.un + .un { border-top: 1px solid var(--fd-line); }
a:focus-visible, button:focus-visible { outline: 2px solid var(--fd-a500); outline-offset: 2px; }
@container bench (min-width: 760px) {
  .cols { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(280px, 1fr); gap: 16px; align-items: start; }
  .bar { grid-template-columns: 110px 1fr auto; }
}
`;

class FdBenchmark extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._data = null;
    this._state = "loading"; // loading | ok | denied | error
  }

  get hass() { return this._hass; }
  set hass(h) {
    const first = !this._hass;
    this._hass = h;
    if (first) this.load();
  }

  async load() {
    if (!this._hass) return;
    await window._fd.t("bm.title");
    this._state = "loading";
    this._render();
    try {
      this._data = await this._hass.callApi("GET", `${DOMAIN}/benchmark`);
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

  _cmp(c) {
    const e = window._fd.escHtml;
    const mx = Math.max(c.user_value, c.benchmark_value, 1);
    const diff = c.difference || 0;
    const tol = Math.abs(c.benchmark_value) * 0.02;
    const dtxt = Math.abs(diff) <= tol ? tr("bm.diff_same")
      : tr(diff < 0 ? "bm.diff_less" : "bm.diff_more", { amount: this._val(Math.abs(diff), c.unit) });
    const housing = c.category === "housing_cold" || c.category === "housing_warm" || c.dimension === "housing_energy";
    const meaning = Math.abs(diff) <= tol ? "" : `<div class="mean"><b>${e(tr("bm.meaning"))}</b>${e(tr(diff > 0 ? "bm.meaning_more" : "bm.meaning_less"))}
      ${diff > 0 ? " " + e(tr(housing ? "bm.next_housing" : "bm.next_other")) : ""}</div>`;
    return `<div class="cmp"><div class="l1"><b>${e(this._label(c))}</b><span class="diff">${e(dtxt)}</span></div>
  <div class="bars">
    <div class="bar"><span>${e(tr("bm.you"))}</span><span class="tr"><i style="width:${(c.user_value / mx) * 100}%"></i></span><span class="v">${e(this._val(c.user_value, c.unit))}</span></div>
    <div class="bar ref"><span>${e(tr("bm.ref"))}</span><span class="tr"><i style="width:${(c.benchmark_value / mx) * 100}%"></i></span><span class="v">${e(this._val(c.benchmark_value, c.unit))}</span></div>
  </div>${this._source(c)}${meaning}</div>`;
  }

  _ref(r) {
    const e = window._fd.escHtml;
    const floor = r.id === "regelbedarf";
    return `<div class="ref${floor ? " floor" : ""}"><div class="l1"><b>${e(this._label(r))}${floor ? ` · ${e(tr("bm.floor"))}` : ""}</b><span>${e(this._val(r.value, r.unit))}</span></div>
  ${floor ? `<div class="muted">${e(tr("bm.floor_note"))}</div>` : (this._note(r) ? `<div class="muted">${e(this._note(r))}</div>` : "")}${this._source(r)}</div>`;
  }

  _body() {
    const e = window._fd.escHtml;
    const d = this._data || {};
    const cmps = d.comparisons || [];
    const refs = d.references || [];
    const un = d.unavailable || [];
    const loc = d.location || {};
    const place = loc.postcode ? loc.postcode : (STATES[loc.state] || loc.state || "");
    const size = loc.household_size ? tr("bm.location_size", { size: loc.household_size }) : "";
    const locLine = place && size ? tr("bm.location", { place, size }) : place || size ? tr("bm.location", { place: place || "DE", size: size || "–" }) : "";
    const ds = d.dataset || {};
    const left = `<div><section class="card"><p class="muted" style="margin:0">${e(tr("bm.intro"))}</p>
      ${locLine ? `<p class="muted" style="margin:6px 0 0">${e(locLine)}</p>` : ""}</section>
      <section class="card">${cmps.length ? cmps.map((c) => this._cmp(c)).join("")
        : `<p class="muted">${e(d.has_plan === false ? tr("bm.no_plan") : tr("bm.empty"))}</p>`}</section></div>`;
    const right = `<div>${refs.length ? `<section class="card"><h3>${e(tr("bm.context"))}</h3>${refs.map((r) => this._ref(r)).join("")}</section>` : ""}
      ${un.length ? `<section class="card"><h3>${e(tr("bm.unavailable"))}</h3><p class="muted" style="margin:0 0 4px">${e(tr("bm.unavailable_note"))}</p>
        ${un.map((u) => `<div class="un"><b>${e(u.label || u.id)}</b>${this._note(u) ? `<div class="muted">${e(this._note(u))}</div>` : ""}</div>`).join("")}</section>` : ""}
      ${ds.dataset_version ? `<p class="muted">${e(tr("bm.dataset", { version: ds.dataset_version, date: ds.generated || "" }))}</p>` : ""}</div>`;
    return `<div class="cols">${left}${right}</div>`;
  }
}

window._fd.defineOnce("fd-benchmark", FdBenchmark);
