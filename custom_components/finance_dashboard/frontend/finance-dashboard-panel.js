/**
 * Finance Dashboard — Sidebar Panel Shell
 *
 * One screen, no tab bar (docs/dev/ui-concept-gap.md § 1.1): the shell hosts
 * fd-home (horizon segment on top, Person ⇄ Haushalt pill at the bottom) and a
 * subpage router. Everything else opens as a full-screen subpage via the
 * bubbling `fd-navigate {target}` event:
 *
 *   freshness     Datenstand (fd-freshness): bank connections, import log,
 *                 "Neu importieren", "Aktualisieren", validity check
 *   settings      Einstellungen (<fd-settings mode="page" section=…>)
 *   transactions  Transaktionen (fd-transactions, desktop entry from Datenstand)
 *   questions     Fragen (fd-questions, star in the Start top bar)
 *   contracts     Verträge (fd-contracts)
 *   benchmark     Vergleich (fd-benchmark), reachable only from Haushalt -> Jahr
 *   review        Abgleich (fd-review), from Einstellungen -> Abgleich
 *   plan          Haushaltsplan (fd-budget-plan)
 *   setup         the guided setup wizard (fd-setup, its own full-screen layer)
 *   back          closes the open subpage (fd-subpage-header's back button)
 *
 * Subpages the shell frames itself (freshness, settings) get
 * <fd-subpage-header title=…>; transactions, questions, contracts, benchmark
 * and the budget plan draw that header inside their own component. Browser back closes a
 * subpage (history entry with #sub=<target>).
 *
 * Bank calls: opening the panel never fetches from the bank. The only live
 * fetch is the Datenstand button "Neu importieren", which this shell turns
 * into POST finance_dashboard/refresh with {"trigger":"user_import"} (the
 * backend refuses a bare POST and derives the PSU headers from this very
 * request, so the call is attended). "Aktualisieren" is POST /reprocess:
 * stored raw data only, never a bank call.
 *
 * Data: every component reads the cache-only HTTP API itself; the shell reads
 * no sensor attributes. Toasts from any component land in the shell's toast host.
 *
 * See docs/ARCHITECTURE-FRONTEND.md for the full architecture.
 */

// One kit, two shells: load the shared components before defining the shell.
// Same ?v= query as this module, so the kit instance is shared and cache-busted.
await import(new URL("finance-dashboard-kit.js" + new URL(import.meta.url).search, import.meta.url).href);

const DOMAIN = "finance_dashboard";
// The module URL carries ?v=<VERSION> (panel.py), so the footer needs no API call.
const VERSION = new URL(import.meta.url).searchParams.get("v") || "";
// HACS routes a repository page by its GitHub repository id (JerryT2T/homeassistant-finance).
const HACS_REPO_PATH = "/hacs/repository/1190753760";

/** Subpage targets: element tag, title key, and whether the shell draws the header. */
const SUBPAGES = {
  freshness: { tag: "fd-freshness", title: "sub.freshness", header: true },
  settings: { tag: "fd-settings", title: "sub.settings", header: true },
  transactions: { tag: "fd-transactions", title: "sub.transactions", header: false },
  questions: { tag: "fd-questions", title: "sub.questions", header: false },
  contracts: { tag: "fd-contracts", title: "sub.contracts", header: false },
  benchmark: { tag: "fd-benchmark", title: "sub.benchmark", header: false },
  review: { tag: "fd-review", title: "sub.review", header: false },
  plan: { tag: "fd-budget-plan", title: "sub.plan", header: false },
};

class FinanceDashboardPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._rendered = false;
    this._sub = null;       // open subpage target or null
    this._subEl = null;     // its body element
    this._importing = false;
    this._reprocessing = false;
    this._demo = false;
    this._toastTimer = null;
    this._onPop = () => this._syncFromLocation();
    // The top-level kit import delays customElements.define, so HA can create
    // the element and assign hass/narrow/route/panel before this class exists.
    // Those land as own properties that shadow the setters - the panel would
    // stay blank forever. Re-assign them through the class.
    for (const prop of ["hass", "narrow", "route", "panel"]) {
      if (Object.prototype.hasOwnProperty.call(this, prop)) {
        const value = this[prop];
        delete this[prop];
        this[prop] = value;
      }
    }
  }

  connectedCallback() { window.addEventListener("popstate", this._onPop); }
  disconnectedCallback() { window.removeEventListener("popstate", this._onPop); }

  set hass(hass) {
    this._hass = hass;
    // Expose hass for i18n language detection
    if (window._fd) window._fd._hass = hass;
    if (!this._rendered) {
      if (!this._rendering) {
        this._rendering = true;
        // Load the user's locale first so the very first render is translated.
        window._fd.t("panel.loading").finally(() => {
          this._render();
          this._rendered = true;
          this._dismissSetupNotification(this._hass);
          this.hass = this._hass;
          this._syncFromLocation();
        });
      }
      return;
    }
    this._syncMenu();
    const home = this.shadowRoot.querySelector("fd-home");
    if (home) home.hass = hass;
    if (this._subEl && "hass" in this._subEl) this._subEl.hass = hass;
  }

  set narrow(value) {
    this._narrow = !!value;
    this._syncMenu();
  }

  get narrow() {
    return this._narrow;
  }

  /** HA hides its sidebar on narrow screens; the menu button sits in fd-home's top bar (slot "menu"). */
  _syncMenu() {
    const menu = this.shadowRoot && this.shadowRoot.getElementById("menu");
    if (!menu) return;
    menu.hass = this._hass;
    menu.narrow = this._narrow;
    menu.hidden = !this._narrow;
  }

  _dismissSetupNotification(hass) {
    if (!hass) return;
    hass.callService("persistent_notification", "dismiss", {
      notification_id: "fd_setup_complete",
    }).catch(() => {
      // Notification may not exist - silently ignore
    });
  }

  _render() {
    const { tSync, SHARED_CSS } = window._fd;
    this.shadowRoot.innerHTML = `
<style>
${SHARED_CSS}
:host {
  display: block;
  font-family: 'Segoe UI', system-ui, sans-serif;
  background: var(--fd-page);
  color: var(--fd-t1);
  min-height: 100vh;
}
.fd { box-sizing: border-box; max-width: 1200px; min-width: 0; margin: 0 auto; padding: 16px 24px 24px; }
@media (max-width: 600px) { .fd { padding: 4px 8px 16px; } }
[hidden] { display: none !important; }
#menu { display: block; color: var(--fd-t1); }
#viewSub { min-width: 0; }
.subbody { min-width: 0; }
/* Store link: a quiet footer for desktop pointers only - a phone never sees it. */
.foot { display: none; margin-top: 48px; text-align: right; font-size: 11px; color: var(--fd-t2); opacity: .45; }
.foot:hover, .foot:focus-within { opacity: 1; }
.foot a { color: inherit; text-decoration: none; }
.foot a:hover { color: var(--fd-a700); text-decoration: underline; }
@media (hover: hover) and (pointer: fine) and (min-width: 900px) { .foot { display: block; } }
/* Toast host: one for the whole panel, above the bottom pill. */
.toast { position: fixed; left: 50%; bottom: calc(max(12px, env(safe-area-inset-bottom)) + 72px); z-index: 70;
  box-sizing: border-box; max-width: min(480px, calc(100vw - 24px)); padding: 10px 16px;
  border: 1px solid var(--fd-line); border-left: 4px solid var(--fd-a500); border-radius: 12px;
  background: var(--fd-card); color: var(--fd-t1); box-shadow: var(--fd-sh2); font-size: 13px;
  overflow-wrap: anywhere; opacity: 0; visibility: hidden; transform: translate(-50%, 8px);
  transition: opacity .15s, transform .15s, visibility .15s; }
.toast.show { opacity: 1; visibility: visible; transform: translate(-50%, 0); }
.toast.success { border-left-color: var(--fd-ok); }
.toast.warn { border-left-color: var(--fd-attn); }
.toast.error { border-left-color: var(--fd-over); }
</style>
<div class="fd">
  <div id="viewHome"><fd-home><ha-menu-button id="menu" slot="menu" hidden></ha-menu-button></fd-home></div>
  <div id="viewSub" role="region" hidden></div>
  <div class="foot">Finance ${VERSION ? `v${VERSION} · ` : ""}<a id="storeLink" href="${HACS_REPO_PATH}" data-tip="${tSync("panel.footer.store_title")}">${tSync("panel.footer.store")}</a></div>
</div>
<div class="toast" id="toast" role="status" aria-live="polite"></div>`;

    const sh = this.shadowRoot;
    this._syncMenu();
    sh.getElementById("storeLink").addEventListener("click", (e) => window._fd.navigate(HACS_REPO_PATH, e));

    sh.addEventListener("fd-navigate", (e) => {
      const d = e.detail || {};
      if (d.target === "back" || d.target === "settings-closed") this._back();
      else if (d.target === "setup") this._openSetup();
      else if (d.target === "plan-wizard") this._openPlanWizard();
      else if (SUBPAGES[d.target]) this._openSub(d.target, d, true);
    });
    // Legacy close events of components that predate fd-subpage-header.
    sh.addEventListener("fd-questions-close", () => this._back());
    sh.addEventListener("fd-freshness-back", () => this._back());
    sh.addEventListener("fd-categorize-requested", () => this._openSub("questions", {}, true));
    sh.addEventListener("fd-questions-all", () => this._openCategorize());
    sh.addEventListener("fd-open-setup", () => this._openSetup());
    sh.addEventListener("fd-open-plan-wizard", () => this._openPlanWizard());

    // Datenstand actions (admin): the shell performs both calls.
    sh.addEventListener("fd-refresh-requested", () => this._import());
    sh.addEventListener("fd-reprocess-requested", () => this._reprocess());

    sh.addEventListener("fd-toast", (e) => {
      const d = e.detail || {};
      this._toast(d.message || "", d.type || "info");
    });
    for (const ev of ["fd-assignments-saved", "fd-settings-saved", "fd-pots-changed"]) {
      sh.addEventListener(ev, () => sh.querySelector("fd-home")?.reload?.());
    }
    sh.addEventListener("fd-demo-toggle", () => this._toggleDemo());
    sh.getElementById("viewSub").addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !e.defaultPrevented) this._back();
    });
  }

  // ---- subpage router ---------------------------------------------------

  /** Open a subpage (target from SUBPAGES). push=false when restoring from the URL. */
  _openSub(target, detail, push) {
    const cfg = SUBPAGES[target];
    if (!cfg || !this._hass) return;
    const sh = this.shadowRoot;
    const { tSync } = window._fd;
    const host = sh.getElementById("viewSub");
    if (this._sub !== target || !this._subEl) {
      host.innerHTML = "";
      if (cfg.header) {
        const hd = document.createElement("fd-subpage-header");
        hd.setAttribute("title", tSync(cfg.title));
        host.append(hd);
      }
      const el = document.createElement(cfg.tag);
      if (target === "settings") {
        el.setAttribute("mode", "page");
        if (detail && detail.section) el.setAttribute("section", detail.section);
      }
      el.classList.add("subbody");
      if (target === "freshness" || target === "benchmark" || target === "review") el.demo = this._demo;
      el.hass = this._hass;
      host.append(el);
      this._subEl = el;
      if (target === "plan") this._feedPlanActuals(el);
    } else if (target === "settings" && detail && detail.section) {
      this._subEl.setAttribute("section", detail.section);
    } else {
      this._subEl.reload?.();
    }
    this._sub = target;
    sh.getElementById("viewHome").hidden = true;
    host.hidden = false;
    if (push) {
      try { history.pushState({ fdSub: target }, "", `${location.pathname}${location.search}#sub=${target}`); }
      catch (_) { /* sandboxed iframe: the in-page back button still works */ }
    }
    window.scrollTo?.({ top: 0 });
    requestAnimationFrame(() => {
      const hd = host.querySelector("fd-subpage-header");
      const focusable = hd?.shadowRoot?.querySelector("button") || this._subEl?.shadowRoot?.querySelector("button, h2");
      focusable?.focus?.();
    });
  }

  _closeSub() {
    const sh = this.shadowRoot;
    if (!this._sub) return;
    this._sub = null;
    this._subEl = null;
    const host = sh.getElementById("viewSub");
    host.innerHTML = "";
    host.hidden = true;
    sh.getElementById("viewHome").hidden = false;
    sh.querySelector("fd-home")?.reload?.();
  }

  /**
   * fd-budget-plan compares the plan with what was booked. Its actuals used to
   * come from the retired sensor tree (window._fd._actual); now they come from
   * GET /household_summary (cache read), mapped onto the shape it reads:
   * {summary:{totalExpenses, fixedCosts, variableCosts, categories{cat: bank sign}},
   *  household:{total_shared_costs, members[{person, individual_costs}]}}.
   */
  async _feedPlanActuals(el) {
    let s = null;
    try { s = await this._hass.callApi("GET", `${DOMAIN}/household_summary?cycle=current`); } catch (_) { return; }
    if (!s || this._subEl !== el) return;
    const categories = {};
    for (const o of s.owners || []) {
      for (const c of o.categories || []) categories[c.category] = (categories[c.category] || 0) - (c.amount || 0);
    }
    const owners = s.owners || [];
    const shared = owners.find((o) => o.kind === "shared");
    el.data = {
      summary: {
        totalExpenses: s.expenses || 0,
        fixedCosts: s.fixed || 0,
        variableCosts: s.variable || 0,
        categories,
      },
      household: {
        total_shared_costs: shared ? shared.expenses || 0 : 0,
        members: owners.filter((o) => o.kind === "person").map((o) => ({ person: o.owner, individual_costs: o.expenses || 0 })),
      },
    };
  }

  /** In-page back: pop our own history entry when we pushed one, else just close. */
  _back() {
    // One gesture can reach here twice (Esc on the panel and on the subpage
    // header, fd-questions re-emitting close); a second history.back() would
    // leave the panel.
    if (this._backPending) return;
    this._backPending = true;
    setTimeout(() => { this._backPending = false; }, 300);
    if (history.state && history.state.fdSub) history.back();
    else {
      this._closeSub();
      if (location.hash.startsWith("#sub=")) {
        try { history.replaceState(null, "", `${location.pathname}${location.search}`); } catch (_) { /* ignore */ }
      }
    }
  }

  /** Browser back/forward and a reload with #sub=… */
  _syncFromLocation() {
    if (!this._rendered) return;
    const m = /^#sub=([a-z]+)/.exec(location.hash || "");
    const target = m && SUBPAGES[m[1]] ? m[1] : null;
    if (target) this._openSub(target, {}, false);
    else this._closeSub();
  }

  // ---- layers -----------------------------------------------------------

  _openSetup() {
    const sh = this.shadowRoot;
    if (sh.querySelector("fd-setup") || !this._hass) return;
    const wiz = document.createElement("fd-setup");
    wiz.hass = this._hass;
    wiz.addEventListener("fd-setup-close", () => {
      wiz.remove();
      const home = sh.querySelector("fd-home");
      if (home) { home._wizard = undefined; home.reload?.(); }
      this._subEl?.reload?.();
    });
    sh.append(wiz);
    wiz.shadowRoot?.querySelector("h2, button")?.focus();
  }

  /** "Haushaltsplan erstellen": full-screen overlay like the setup; Start reloads afterwards. */
  _openPlanWizard() {
    const sh = this.shadowRoot;
    if (sh.querySelector("fd-plan-wizard") || !this._hass) return;
    const wiz = document.createElement("fd-plan-wizard");
    wiz.hass = this._hass;
    wiz.addEventListener("fd-plan-wizard-close", () => {
      wiz.remove();
      const home = sh.querySelector("fd-home");
      if (home) home.reload?.();
      this._subEl?.reload?.();
    });
    sh.append(wiz);
    wiz.shadowRoot?.querySelector("h2, button")?.focus();
  }

  /** Desktop link inside the questions view: the existing categorise card in a dialog. */
  _openCategorize() {
    const sh = this.shadowRoot;
    if (sh.getElementById("catDialog") || !this._hass) return;
    const { tSync } = window._fd;
    const wrap = document.createElement("div");
    wrap.id = "catDialog";
    wrap.setAttribute("role", "dialog");
    wrap.setAttribute("aria-modal", "true");
    wrap.setAttribute("aria-label", tSync("home.categorize.title"));
    wrap.style.cssText = "position:fixed;inset:0;z-index:60;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.4);padding:12px;";
    const box = document.createElement("div");
    box.style.cssText = "width:min(720px,100%);max-height:90dvh;overflow:auto;border-radius:16px;background:var(--fd-card);";
    const close = document.createElement("button");
    close.textContent = tSync("home.alert.close");
    close.style.cssText = "display:block;margin:8px 8px 0 auto;min-height:44px;padding:0 16px;border:0;border-radius:999px;background:transparent;color:var(--fd-a700);font:inherit;cursor:pointer;";
    const card = document.createElement("fd-categorize");
    card.setConfig?.({});
    card.hass = this._hass;
    const done = () => { wrap.remove(); this._subEl?.reload?.(); };
    close.addEventListener("click", done);
    wrap.addEventListener("click", (e) => { if (e.target === wrap) done(); });
    wrap.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); done(); } });
    box.append(close, card);
    wrap.append(box);
    sh.append(wrap);
    close.focus();
  }

  // ---- toasts -----------------------------------------------------------

  _toast(message, type) {
    const el = this.shadowRoot.getElementById("toast");
    if (!el || !message) return;
    el.textContent = message;
    el.className = `toast ${type || "info"} show`;
    el.setAttribute("aria-live", type === "error" || type === "warn" ? "assertive" : "polite");
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => el.classList.remove("show"), type === "error" ? 6000 : 4000);
  }

  // ---- Datenstand actions -----------------------------------------------

  _syncBusy() {
    const fr = this.shadowRoot.querySelector("fd-freshness");
    if (fr) {
      fr.importing = this._importing;
      fr.reprocessing = this._reprocessing;
    }
  }

  _afterDataChange() {
    const sh = this.shadowRoot;
    sh.querySelector("fd-home")?.reload?.();
    sh.querySelector("fd-freshness")?.reload?.();
  }

  /**
   * "Neu importieren": the one attended live bank fetch. The explicit trigger
   * body is required by the backend; the request itself carries the PSU
   * context, so the bank's unattended 4/day cap does not apply. A debounced or
   * rate-limited answer is reported, not retried.
   */
  async _import() {
    if (this._importing || this._reprocessing || !this._hass) return;
    const { tSync } = window._fd;
    if (this._demo) { this._toast(tSync("shell.toast.demo"), "info"); return; }
    this._importing = true;
    this._syncBusy();
    let detail;
    try {
      const resp = await this._hass.callApi("POST", `${DOMAIN}/refresh`, { trigger: "user_import" });
      const status = resp && resp.status;
      detail = {
        status,
        reason: resp && resp.ok === false
          ? (resp.reason || "error")
          : (status && status.stats && status.stats.outcome) || "ok",
      };
    } catch (e) {
      const denied = e && (e.status_code === 403 || (e.body && e.body.error === "admin_required"));
      detail = { reason: denied ? "admin_required" : "error" };
    } finally {
      this._importing = false;
      this._syncBusy();
    }
    this._toastImport(detail);
    this._afterDataChange();
  }

  _toastImport(d) {
    const { tSync } = window._fd;
    const s = (d.status && d.status.stats) || {};
    const reason = d.reason || s.outcome || "error";
    if (reason === "ok") {
      this._toast(tSync("shell.toast.import_ok", {
        accounts: s.accounts || 0,
        tx: s.transactions || 0,
        new: s.new || 0,
        duration: `${((s.duration_ms || 0) / 1000).toFixed(1)} s`,
      }), "success");
    } else if (reason === "partial") {
      const errs = (s.errors || []).slice(0, 2).join(" · ");
      this._toast(`${tSync("shell.toast.import_partial", { accounts: s.accounts || 0, tx: s.transactions || 0 })}${errs ? ` ${errs}` : ""}`, "warn");
    } else if (reason === "debounced") {
      this._toast(tSync("shell.toast.import_debounced"), "info");
    } else if (reason === "rate_limited") {
      this._toast(tSync("shell.toast.import_rate_limited"), "warn");
    } else if (reason === "admin_required") {
      this._toast(tSync("shell.toast.admin"), "warn");
    } else {
      const errs = (s.errors || []).slice(0, 2).join(" · ");
      this._toast(`${tSync("shell.toast.import_error")}${errs ? ` ${errs}` : ""}`, "error");
    }
  }

  /** "Aktualisieren": POST /reprocess — re-derive from stored raw data, never a bank call. */
  async _reprocess() {
    if (this._importing || this._reprocessing || !this._hass) return;
    const { tSync } = window._fd;
    this._reprocessing = true;
    this._syncBusy();
    try {
      const r = await this._hass.callApi("POST", `${DOMAIN}/reprocess`);
      const st = (r && r.stats) || {};
      if (r && r.ok && st.outcome === "rebuilt") {
        this._toast(tSync("shell.toast.reprocess_ok", { tx: st.transactions ?? 0, snapshots: st.snapshots ?? 0, version: st.version ?? "" }), "success");
      } else if (r && r.ok) {
        this._toast(tSync("shell.toast.reprocess_empty"), "info");
      } else if (st.outcome === "unavailable") {
        this._toast(tSync("shell.toast.reprocess_unavailable"), "warn");
      } else {
        this._toast(tSync("shell.toast.reprocess_error"), "error");
      }
    } catch (e) {
      const denied = e && (e.status_code === 403 || (e.body && e.body.error === "admin_required"));
      this._toast(tSync(denied ? "shell.toast.admin" : "shell.toast.reprocess_error"), denied ? "warn" : "error");
    } finally {
      this._reprocessing = false;
      this._syncBusy();
    }
    this._afterDataChange();
  }

  /** Demo mode on/off (Start's not-configured screen; settings › Erweitert). */
  async _toggleDemo() {
    if (!this._hass || this._demoBusy) return;
    const { tSync } = window._fd;
    this._demoBusy = true;
    try {
      const r = await this._hass.callApi("POST", `${DOMAIN}/demo/toggle`);
      this._demo = !!(r && r.demo_mode);
      const home = this.shadowRoot.querySelector("fd-home");
      if (home) home.demo = this._demo;
      this._toast(tSync(this._demo ? "toast.demo_started" : "toast.demo_stopped"), "info");
    } catch (e) {
      this._toast(tSync("shell.toast.demo_failed"), "error");
    } finally {
      this._demoBusy = false;
    }
  }
}

window._fd.defineOnce("finance-dashboard-panel", FinanceDashboardPanel);
