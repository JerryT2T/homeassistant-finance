/**
 * Finance Dashboard — Start (the one screen): Heute · Woche · Zyklus · Jahr
 *
 * Cache reads only, never a bank call:
 *   GET /home?horizon&view            the screen itself (contract: briefs/home-api-contract.md)
 *   GET /household_summary            Spielraum fallback while there are no pots and /home
 *                                     carries no person_budget yet (person view: view=person)
 *   GET /balances (+ /assignments)    desktop "Konten" column (assignments: admin only)
 *   POST/PUT/DELETE /pots             pot sheet and desktop pot management
 *
 * Navigation (same on every width, docs/dev/ui-concept-gap.md § 1.1–1.2):
 *   top bar   [HA menu (narrow)] [freshness ✓ 06:30] · [Eilmeldung pill] · [star] [gear]
 *   segment   Heute · Woche · Zyklus · Jahr with sub-labels, swipeable, arrow keys
 *   bottom    Person ⇄ Haushalt pill toggle, fixed to the bottom of the panel, in
 *             both views (hidden only for a user that maps to no person)
 * Desktop (@container ≥ 760 px) adds the side column per horizon (purple ◆ marker):
 *   Zyklus → Zyklus im Detail + Optimierung, Woche → Budget anpassen,
 *   Jahr → Optimierung light + Verträge; every horizon → Konten + pot management.
 *
 * Person view without own pots (spec § 1.4): own Spielraum (own income − own
 * spend, Soll-Linie), own next debits, an empty "Deine Töpfe" card with "+"
 * and suggestions. Never "share of the shared pots".
 *
 * Events out (bubbling, composed):
 *   fd-navigate {target, section?}  freshness | settings | questions | contracts |
 *                                   benchmark | plan | setup
 *   fd-demo-toggle                  "Demo starten" on the not-configured screen
 *
 * Properties in: hass, demo (boolean, demo data via ?demo=1). Light DOM: an
 * element with slot="menu" (the shell's ha-menu-button) lands in the top bar.
 */

const DOMAIN = "finance_dashboard";
const HORIZONS = ["today", "week", "cycle", "year"];
const DISMISS_KEY = "fd_home_dismissed_suggestions";
const SUGGEST_SKIP = { has: (k) => k === "other" || k === "transfers" || String(k).startsWith("income") };
const CONTRACT_CATS = new Set(["housing_cold", "housing_warm", "media", "finance", "health"]);
const PERSON_COLORS = ["var(--fd-person-a)", "var(--fd-person-b)", "var(--fd-desktop)", "var(--fd-a700)"];

const CSS = `
:host { display: block; }
.root { container: home / inline-size; position: relative; min-width: 0; color: var(--fd-t1); font-size: 13px; line-height: 1.4; }
button { font: inherit; color: inherit; cursor: pointer; }
.top { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); grid-template-areas: "tl tc tr" "seg seg seg"; align-items: center; gap: 6px; padding: 4px 0 0; }
.tl { grid-area: tl; } .tc { grid-area: tc; } .tr { grid-area: tr; } .top > .seg { grid-area: seg; }
.tl, .tr { display: flex; align-items: center; gap: 2px; min-width: 0; }
.tr { justify-content: flex-end; }
.tc { min-width: 0; display: flex; justify-content: center; }
.ib { display: inline-flex; align-items: center; justify-content: center; min-width: var(--fd-touch); min-height: var(--fd-touch); border: 0; background: transparent; border-radius: var(--fd-r-pill); padding: 0; }
.ib:hover { background: var(--fd-sunk); }
.fresh { gap: 6px; padding: 0 10px 0 8px; min-width: 0; max-width: 100%; }
.fresh i { flex: none; display: flex; align-items: center; justify-content: center; width: 24px; height: 24px; border-radius: 50%; font-style: normal; font-size: 13px; background: var(--fd-ok-bg); color: var(--fd-ok); }
.fresh.stale i { background: var(--fd-near-bg); color: var(--fd-near); }
.fresh.error i { background: var(--fd-over-bg); color: var(--fd-over); }
.fresh .tm, .fresh .t { font-size: 12.5px; color: var(--fd-t2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fresh .t { display: none; }
.pill { display: inline-flex; align-items: center; gap: 8px; min-height: var(--fd-touch); max-width: 100%; min-width: 0; padding: 6px 14px 6px 10px; border: 1px solid var(--fd-line); border-left: 4px solid var(--fd-attn); border-radius: var(--fd-r-pill); background: var(--fd-card); box-shadow: var(--fd-sh2); font-size: 12.5px; font-weight: 500; }
.pill.info { border-left-color: var(--fd-a500); }
.pill i { flex: none; width: 8px; height: 8px; border-radius: 50%; background: var(--fd-attn); box-shadow: 0 0 0 3px color-mix(in srgb, var(--fd-attn) 24%, transparent); }
.pill span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.ask { position: relative; width: var(--fd-touch); height: var(--fd-touch); }
.ask .qt { display: none; }
.ask .ring { display: flex; align-items: center; justify-content: center; width: 36px; height: 36px; box-sizing: border-box; padding: 3px; border-radius: 50%; background: conic-gradient(var(--fd-gold) 0 var(--p, 0%), var(--fd-sunk) 0); }
.ask .ring span { display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; border-radius: 50%; font-size: 15px; background: var(--fd-card); color: var(--fd-gold); }
.ask b { position: absolute; top: 0; right: 0; min-width: 18px; height: 18px; padding: 0 5px; box-sizing: border-box; border-radius: 9px; font-size: 12px; line-height: 18px; text-align: center; background: var(--fd-a700); color: #fff; }
.gear svg { width: 22px; height: 22px; fill: var(--fd-t2); }
.gear:hover svg { fill: var(--fd-a700); }
.tr [data-tip]::after { left: auto; right: 0; transform: none; }
.panel { margin: 0 0 12px; padding: 8px; border-radius: var(--fd-r-card); background: var(--fd-card); box-shadow: var(--fd-sh2); }
.alert { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 10px; border-left: 4px solid var(--fd-a500); border-radius: 8px; }
.alert > span:first-child { min-width: 0; overflow-wrap: anywhere; }
.alert.warn { border-left-color: var(--fd-attn); }
.alert + .alert { margin-top: 6px; }
.seg { display: flex; gap: 2px; margin: 0 0 12px; border-bottom: 1px solid var(--fd-line); }
.seg button { flex: 1 1 0; min-width: 0; min-height: var(--fd-touch); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 0; padding: 4px 2px; border: 0; border-bottom: 3px solid transparent; margin-bottom: -1px; background: transparent; color: var(--fd-t2); font-size: 14px; line-height: 1.2; }
.seg button small { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: var(--fd-t3); }
.seg button[aria-selected="true"] { color: var(--fd-a900); font-weight: 500; border-bottom-color: var(--fd-a500); }
.seg button[aria-selected="true"] small { color: var(--fd-t2); font-weight: 400; }
.seg .wide { display: none; }
.layout { display: block; }
.side { display: none; }
.main { min-width: 0; touch-action: pan-y; min-height: 40vh; padding-bottom: 88px; }
.main.slide-l { animation: slidel .2s ease-out; }
.main.slide-r { animation: slider .2s ease-out; }
/* The slide-in would push the page sideways at its peak: clip only while it runs. */
.layout:has(> .main.slide-l), .layout:has(> .main.slide-r) { overflow-x: clip; }
@keyframes slidel { from { opacity: 0; transform: translateX(24px); } }
@keyframes slider { from { opacity: 0; transform: translateX(-24px); } }
.card { margin: 0 0 12px; padding: 12px 14px; border-radius: var(--fd-r-card); background: var(--fd-card); box-shadow: var(--fd-sh1); min-width: 0; }
.h { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin: 0 0 8px; font-size: 14px; font-weight: 500; }
.h > span { min-width: 0; }
.h .sub { flex: none; font-size: 12px; font-weight: 400; color: var(--fd-t2); }
.muted { color: var(--fd-t2); font-size: 12px; }
.st-ok { --c: var(--fd-ok); --cbg: var(--fd-ok-bg); --cfg: color-mix(in srgb, var(--fd-ok) 72%, var(--fd-t1)); }
.st-near { --c: var(--fd-near); --cbg: var(--fd-near-bg); --cfg: color-mix(in srgb, var(--fd-near) 72%, var(--fd-t1)); }
.st-over { --c: var(--fd-over); --cbg: var(--fd-over-bg); --cfg: color-mix(in srgb, var(--fd-over) 72%, var(--fd-t1)); }
.chip { display: inline-flex; align-items: center; gap: 4px; padding: 1px 9px; border-radius: var(--fd-r-pill); font-size: 12px; font-weight: 500; white-space: nowrap; background: var(--cbg); color: var(--cfg); }
.big { font-size: 40px; font-weight: 500; line-height: 1.05; color: var(--cfg, var(--fd-t1)); overflow-wrap: anywhere; }
.cap { margin-top: 4px; font-size: 12.5px; color: var(--fd-t2); }
.meter { position: relative; height: 12px; margin: 14px 0 6px; border-radius: 6px; background: var(--fd-sunk); overflow: hidden; }
.meter > i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 6px; background: var(--c); }
.pot { display: grid; grid-template-columns: 4px minmax(0, 1fr) auto; align-items: center; column-gap: 10px; padding: 9px 0; }
.pot + .pot { border-top: 1px solid var(--fd-line); }
.pot > i { align-self: stretch; border-radius: 2px; background: var(--c); }
.pot > span { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.pot > span b { font-weight: 500; overflow-wrap: anywhere; }
.pot > em { font-style: normal; font-size: 18px; font-weight: 500; color: var(--cfg); white-space: nowrap; }
.add { flex: none; width: var(--fd-touch); height: var(--fd-touch); margin: -10px -10px -10px 0; border: 0; border-radius: 50%; background: transparent; color: var(--fd-t2); font-size: 22px; line-height: 1; }
.add:hover { background: var(--fd-sunk); color: var(--fd-a700); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.sgc { min-height: var(--fd-touch); padding: 0 14px; border: 1px dashed var(--fd-a300); border-radius: var(--fd-r-pill); background: transparent; color: var(--fd-a700); font-size: 12.5px; }
.band { margin: -12px -14px 12px; padding: 14px; border-radius: var(--fd-r-card) var(--fd-r-card) 0 0; background: var(--cbg); }
.band .big { font-size: 30px; }
.carry { display: flex; align-items: center; gap: 10px; margin: 0 0 12px; padding: 8px 10px; border-radius: 10px; background: var(--fd-a50); color: var(--fd-a900); font-size: 12.5px; }
.carry b { flex: none; padding: 3px 9px; border-radius: var(--fd-r-pill); background: var(--fd-card); }
.chart { position: relative; height: 130px; border-radius: 10px; background: var(--fd-sunk); }
.chart svg { position: absolute; inset: 0; width: 100%; height: 100%; }
.days { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 4px; margin-top: 6px; text-align: center; font-size: 12px; color: var(--fd-t2); }
.days b { display: block; font-weight: 500; color: var(--fd-t1); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.days .today { color: var(--fd-a900); font-weight: 600; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 8px; font-size: 12px; color: var(--fd-t2); }
.legend i { display: inline-block; width: 14px; height: 8px; margin-right: 4px; border-radius: 2px; background: var(--fd-ok); vertical-align: 0; }
.legend i.l1 { height: 0; border-top: 2px solid var(--fd-a900); border-radius: 0; background: none; vertical-align: 3px; }
.legend i.l2 { height: 0; border-top: 1px dashed var(--fd-t3); border-radius: 0; background: none; vertical-align: 3px; }
.tiles { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 12px; }
.tiles.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.tile { min-width: 0; padding: 8px 10px; border-radius: 10px; background: var(--fd-sunk); }
.tile span { display: block; font-size: 12px; color: var(--fd-t2); overflow-wrap: anywhere; }
.tile b { display: block; font-size: 17px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nx { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: start; gap: 2px 10px; padding: 7px 0; }
.nx + .nx { border-top: 1px solid var(--fd-line); }
.nx .lb { min-width: 0; overflow-wrap: anywhere; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.nx .mt { grid-column: 1; display: flex; flex-wrap: wrap; align-items: center; gap: 4px 6px; }
.nx .amt { grid-column: 2; grid-row: 1 / span 2; flex: none; white-space: nowrap; font-variant-numeric: tabular-nums; }
.row { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 7px 0; }
.row + .row { border-top: 1px solid var(--fd-line); }
.row > span:first-child { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row .amt { flex: none; white-space: nowrap; font-variant-numeric: tabular-nums; }
.tag { padding: 0 7px; border: 1px dashed var(--fd-t3); border-radius: var(--fd-r-pill); font-size: 12px; color: var(--fd-t2); white-space: nowrap; }
.more { display: flex; align-items: center; width: 100%; min-height: var(--fd-touch); margin-top: 2px; padding: 0; border: 0; border-top: 1px solid var(--fd-line); background: transparent; color: var(--fd-a700); text-align: left; }
.link { min-height: var(--fd-touch); padding: 0 4px; border: 0; background: transparent; color: var(--fd-a700); font-weight: 500; text-decoration: underline; text-underline-offset: 2px; }
.tank { position: relative; height: 96px; margin-top: 10px; border-radius: 12px; background: var(--fd-a50); overflow: hidden; }
.tank > i { position: absolute; left: 0; top: 0; bottom: 0; background: var(--c); opacity: .85; }
.tank > b { position: absolute; top: 0; bottom: 0; width: 0; border-left: 2px dashed var(--fd-a900); }
.tank > .ta { position: absolute; right: 14px; bottom: 10px; max-width: calc(100% - 28px); text-align: right; font-size: 28px; font-weight: 500; line-height: 1.05; color: var(--fd-t1); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tank > .ta small { display: block; font-size: 12px; font-weight: 400; color: var(--fd-t2); }
.flip { animation: flipin .28s ease-out; }
@keyframes flipin { from { opacity: 0; transform: rotateY(60deg); } }
.info { flex: none; box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center; width: var(--fd-touch); height: var(--fd-touch); margin: -10px 0 -10px -6px; border: 0; border-radius: 50%; background: transparent; color: var(--fd-a700); font-size: 15px; vertical-align: middle; }
.verdict { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px; }
.verdict .chip { padding: 3px 12px; font-size: 14px; }
.know { display: flex; gap: 10px; align-items: flex-start; border-left: 4px solid var(--fd-a500); }
.know b { display: block; margin-bottom: 2px; font-size: 12px; letter-spacing: .06em; text-transform: uppercase; color: var(--fd-a700); }
.cyc { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 4px; }
.cyc span { display: flex; align-items: flex-end; justify-content: center; height: 36px; padding-bottom: 2px; border-radius: 6px; font-size: 12px; color: #fff; background: var(--c, var(--fd-sunk)); overflow: hidden; }
.cyc span.run { background: repeating-linear-gradient(135deg, var(--fd-near) 0 4px, color-mix(in srgb, var(--fd-near) 60%, #fff) 4px 8px); }
.cyc span.fut { background: var(--fd-sunk); color: var(--fd-t3); }
.cmp { height: 8px; margin: 4px 0; border-radius: 4px; background: var(--fd-sunk); overflow: hidden; }
.cmp i { display: block; height: 100%; background: var(--fd-a500); }
.cmp.prev i { background: var(--fd-t3); }
.entry { display: flex; align-items: center; gap: 10px; width: 100%; min-height: var(--fd-touch); margin: 0 0 12px; padding: 10px 14px; border: 0; border-radius: var(--fd-r-card); background: var(--fd-card); box-shadow: var(--fd-sh1); text-align: left; }
.entry > i { flex: none; display: flex; align-items: center; justify-content: center; width: 34px; height: 34px; border-radius: 10px; font-style: normal; background: var(--fd-a50); color: var(--fd-a700); }
.entry > span { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.dtag { display: inline-flex; align-items: center; gap: 4px; padding: 1px 8px; border-radius: var(--fd-r-pill); font-size: 12px; font-weight: 500; background: var(--fd-desktop-bg); color: var(--fd-desktop); white-space: nowrap; }
.dtag::before { content: "\\25C6"; font-size: 8px; }
.btn { min-height: var(--fd-touch); padding: 0 16px; border: 1px solid transparent; border-radius: var(--fd-r-pill); background: var(--fd-a700); color: #fff; font-weight: 500; }
.btn.ghost { background: transparent; color: var(--fd-a700); border-color: var(--fd-a100); }
.btn.sm { min-height: 36px; padding: 0 12px; font-size: 12px; }
.btn.danger { background: transparent; color: var(--fd-over); border-color: var(--fd-over-bg); }
.btn.dsk { background: var(--fd-a700); color: #fff; }
.btn.dsk.ghost { background: transparent; color: var(--fd-a700); border: 1px solid var(--fd-a100); }
.btn:disabled { opacity: .5; cursor: not-allowed; }
.setup h3 { margin: 0 0 6px; font-size: 16px; font-weight: 600; }
.acts { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; margin-top: 12px; }
.msg { padding: 32px 12px; text-align: center; color: var(--fd-t2); }
.msg .btn { margin-top: 12px; }
/* Bottom pill toggle: fixed to the panel's content box (left/width set from JS). */
.nav { position: fixed; bottom: max(12px, env(safe-area-inset-bottom)); left: 0; right: 0; z-index: 20; display: flex; justify-content: center; pointer-events: none; padding: 0 8px; box-sizing: border-box; }
.nav[hidden] { display: none; }
.toggle { pointer-events: auto; display: inline-flex; gap: 2px; max-width: 100%; padding: 4px; box-sizing: border-box; border-radius: var(--fd-r-pill); background: var(--fd-card); box-shadow: var(--fd-sh2); border: 1px solid var(--fd-line); }
.toggle button { display: inline-flex; align-items: center; gap: 8px; min-width: 0; min-height: var(--fd-touch); padding: 4px 16px 4px 6px; border: 0; border-radius: var(--fd-r-pill); background: transparent; color: var(--fd-t2); text-align: left; }
.toggle button > i { flex: none; display: flex; align-items: center; justify-content: center; width: 30px; height: 30px; border-radius: 50%; font-style: normal; font-size: 13px; font-weight: 600; background: color-mix(in srgb, var(--pc) 16%, var(--fd-card)); color: var(--pc); }
.toggle button > span { display: flex; flex-direction: column; min-width: 0; line-height: 1.15; }
.toggle button b { max-width: 12ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
.toggle button small { font-size: 12px; white-space: nowrap; opacity: .85; }
.toggle button[aria-checked="true"] { background: var(--pc); color: #fff; }
.toggle button[aria-checked="true"] > i { background: #fff; color: var(--pc); }
.toggle [data-tip]::after { top: auto; bottom: calc(100% + 10px); }
.live { position: fixed; left: 50%; bottom: 84px; transform: translateX(-50%); z-index: 40; max-width: calc(100vw - 24px); padding: 8px 14px; border-radius: var(--fd-r-pill); background: var(--fd-card); border: 1px solid var(--fd-line); box-shadow: var(--fd-sh2); }
.scrim { position: fixed; inset: 0; z-index: 50; display: flex; align-items: flex-end; justify-content: center; background: rgba(0,0,0,.4); }
.sheet { box-sizing: border-box; width: min(480px, 100%); max-height: 90dvh; overflow: auto; padding: 16px; border-radius: 18px 18px 0 0; background: var(--fd-card); box-shadow: var(--fd-sh2); }
.sheet label, .lbl { display: block; margin: 12px 0 4px; font-size: 12px; color: var(--fd-t2); }
input[type=text], input[type=number], select { box-sizing: border-box; width: 100%; min-height: var(--fd-touch); padding: 0 12px; border: 1px solid var(--fd-line); border-radius: 10px; background: var(--fd-page); color: var(--fd-t1); font: inherit; }
select { appearance: none; -webkit-appearance: none; padding-right: 32px; background-image: linear-gradient(45deg, transparent 50%, var(--fd-t2) 50%), linear-gradient(135deg, var(--fd-t2) 50%, transparent 50%); background-position: calc(100% - 17px) 50%, calc(100% - 12px) 50%; background-size: 5px 5px; background-repeat: no-repeat; }
input:focus-visible, select:focus-visible { outline: 2px solid var(--fd-a500); outline-offset: 1px; }
.opts { display: flex; flex-wrap: wrap; gap: 6px; }
.opts button { min-height: var(--fd-touch); padding: 0 14px; border: 1px solid var(--fd-line); border-radius: var(--fd-r-pill); background: transparent; }
.opts button[aria-pressed="true"], .opts button[aria-checked="true"] { background: var(--fd-a50); border-color: var(--fd-a500); color: var(--fd-a900); font-weight: 500; }
.err { margin-top: 8px; color: var(--fd-over); font-size: 12px; }
.mg { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 0; }
.mg + .mg { border-top: 1px solid var(--fd-line); }
.mg > span { min-width: 0; display: flex; flex-direction: column; }
.mg > span b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
.mg .btns { display: flex; gap: 6px; flex: none; }
.sug { padding: 8px 10px; border: 1px dashed var(--fd-a300); border-radius: 10px; background: var(--fd-a50); }
.sug + .sug { margin-top: 6px; }
.hrow { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 4px 10px; padding: 8px 0; }
.hrow + .hrow { border-top: 1px solid var(--fd-line); }
.hrow .hn { min-width: 0; overflow-wrap: anywhere; }
.hist { width: 84px; height: 28px; overflow: visible; }
.hist .hb { fill: var(--fd-a500); }
.hist .hb.over { fill: var(--fd-over, #c0392b); }
.hist .hl { stroke: var(--fd-t3); stroke-width: 1; stroke-dasharray: 2 2; }
.hist-none { font-size: 12px; }
.hcarry { grid-column: 1 / -1; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 6px 10px; font-size: 12.5px; min-width: 0; }
.hcarry > span:first-child { min-width: 0; overflow-wrap: anywhere; }
.hcarry .btns { display: flex; flex-wrap: wrap; gap: 6px; }
.opt { padding: 10px 0; }
.opt + .opt { border-top: 1px solid var(--fd-line); }
.opt .row { padding: 0; }
.opt p { margin: 4px 0 0; color: var(--fd-t2); font-size: 12px; }
.opt .acts { justify-content: flex-start; margin-top: 8px; }
.grid2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.acc { padding: 8px 0; }
.acc + .acc { border-top: 1px solid var(--fd-line); }
.acc .nm { display: flex; align-items: center; gap: 8px; font-weight: 500; }
.acc .nm i { flex: none; width: 10px; height: 10px; border-radius: 50%; background: var(--c); }
.acc .nm span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.acc .nm em { margin-left: auto; flex: none; font-style: normal; white-space: nowrap; font-variant-numeric: tabular-nums; }
.acc .row { padding: 4px 0 4px 18px; font-size: 12px; }
.acc .row + .row { border-top: 0; }
#cdslot:empty { display: none; }

.hhchip { display: none; align-items: center; height: 36px; padding: 0 14px; border-radius: var(--fd-r-pill); font-size: 12px; font-weight: 500; background: var(--fd-household-bg); color: color-mix(in srgb, var(--fd-household) 80%, var(--fd-t1)); }
.hero { padding: 16px 18px; }
.hero-in { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; align-items: center; }
.hero .hcap { display: flex; align-items: center; gap: 4px; font-size: 12px; color: var(--fd-t2); }
.hero .hcap .info { margin: -12px 0 -12px -2px; }
.hero .hbig { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px; }
.hero .big { font-size: 32px; font-weight: 700; line-height: 1.1; color: var(--fd-t1); }
.vpill { display: inline-flex; align-items: center; padding: 3px 12px; border-radius: var(--fd-r-pill); font-size: 12px; font-weight: 600; background: var(--cbg); color: var(--cfg); white-space: nowrap; }
.hbar { position: relative; height: 10px; margin: 32px 0 28px; border-radius: 5px; background: var(--fd-sunk); }
.hbar > i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 5px; background: var(--bar, var(--fd-a500)); }
.hbar > .tm { position: absolute; top: -6px; bottom: -6px; width: 2px; margin-left: -1px; background: var(--fd-t1); }
.hbar > .tg { position: absolute; top: -8px; bottom: -8px; width: 0; border-left: 2px dashed var(--fd-t2); }
.hbar .lbl { position: absolute; font-size: 12px; color: var(--fd-t2); white-space: nowrap; }
.hbar .lt { top: -26px; left: clamp(52px, var(--x), calc(100% - 52px)); transform: translateX(-50%); }
.hbar .lb { bottom: -24px; left: clamp(44px, var(--x), calc(100% - 44px)); transform: translateX(-50%); }
.hrule { margin: 8px 0 0; font-size: 12px; color: var(--fd-t2); }
.kpis { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.kpi { min-width: 0; padding: 8px 10px; border-radius: 10px; background: var(--fd-sunk); }
.kpi span { display: block; font-size: 12px; color: var(--fd-t2); overflow-wrap: anywhere; }
.kpi b { display: block; font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.hl-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; align-items: start; }
.hl-side { min-width: 0; }
.lday { margin: 14px 0 4px; font-size: 12px; letter-spacing: .06em; text-transform: uppercase; color: var(--fd-t3); }
.lday:first-child { margin-top: 0; }
.lcard { margin: 0 0 4px; padding: 2px 14px; border-radius: var(--fd-r-card); background: var(--fd-card); box-shadow: var(--fd-sh1); }
.lrow { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 9px 0; }
.lrow + .lrow { border-top: 1px solid var(--fd-line); }
.lrow > span:first-child { min-width: 0; overflow-wrap: anywhere; }
.lrow .lc2 { color: var(--fd-t2); font-size: 12px; }
.lrow .tag { margin-left: 6px; font-size: 12px; }
.lrow .amt { flex: none; min-width: 84px; text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
.lrow .amt.in { color: var(--fd-ok); }
.lmore { display: flex; align-items: center; justify-content: center; width: 100%; min-height: var(--fd-touch); border: 0; background: transparent; color: var(--fd-a700); font-weight: 500; }
.strip { display: flex; align-items: center; gap: 10px; margin: 0 0 12px; padding: 11px 14px; border: 1px dashed var(--fd-line); border-radius: 12px; color: var(--fd-t2); }
.strip > span:first-child { flex: 1; min-width: 0; }
.strip .btn { min-height: 36px; background: transparent; color: var(--fd-a700); border-color: var(--fd-a500); }
.hl .side { margin-top: 4px; }
@container home (min-width: 640px) {
  .hero-in { grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 18px; }
  .hl-grid { grid-template-columns: minmax(0, 1.7fr) minmax(0, 1fr); }
}
@container home (max-width: 639px) {
  .hero .big { font-size: 28px; }
  .strip:not(.blocker) { display: none; }
}
@container home (min-width: 760px) {
  .layout { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(280px, 1fr); gap: 16px; align-items: start; }
  .side { display: block; min-width: 0; padding-bottom: 88px; }
  .scrim { align-items: center; }
  .sheet { border-radius: 18px; }
  .fresh .t { display: inline; }
  .seg .wide { display: inline; }
  .seg .narrow { display: none; }
  .layout.hl { display: block; }
  .layout.hl .side { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; align-items: start; }
  .layout.hl .side #cdslot { grid-column: 1 / -1; }
  .top { grid-template-columns: auto auto minmax(0, 1fr) auto; grid-template-areas: "tl seg tc tr"; gap: 10px; padding-bottom: 12px; }
  .tc { justify-content: flex-end; }
  .top > .seg { margin: 0; padding: 4px; gap: 4px; border: 0; border-radius: var(--fd-r-pill); background: var(--fd-sunk); width: max-content; }
  .top > .seg button { flex: none; flex-direction: row; min-height: 36px; padding: 0 16px; margin: 0; border: 0; border-radius: var(--fd-r-pill); font-size: 13px; }
  .top > .seg button small { display: none; }
  .top > .seg button[aria-selected="true"] { background: var(--fd-a700); color: #fff; }
  .fresh { background: var(--cbg, var(--fd-sunk)); color: var(--cfg, var(--fd-t2)); min-height: 36px; }
  .fresh i { background: transparent; color: inherit; }
  .fresh .t, .fresh .tm { color: inherit; }
  .fresh.ok { --cbg: var(--fd-ok-bg); --cfg: color-mix(in srgb, var(--fd-ok) 72%, var(--fd-t1)); }
  .fresh.stale { --cbg: var(--fd-near-bg); --cfg: color-mix(in srgb, var(--fd-near) 72%, var(--fd-t1)); }
  .fresh.error { --cbg: var(--fd-over-bg); --cfg: color-mix(in srgb, var(--fd-over) 72%, var(--fd-t1)); }
  .ask { width: auto; height: 36px; padding: 0 14px; border-radius: var(--fd-r-pill); background: var(--fd-sunk); }
  .ask .ring, .ask b { display: none; }
  .hhchip { display: inline-flex; }
  .ask .qt { display: inline; font-size: 12px; font-weight: 500; color: var(--fd-t2); }
}
`;

const GEAR = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19.14 12.94c.04-.31.06-.62.06-.94s-.02-.63-.06-.94l2.03-1.58a.5.5 0 0 0 .12-.64l-1.92-3.32a.5.5 0 0 0-.61-.22l-2.39.96a7.03 7.03 0 0 0-1.63-.94l-.36-2.54A.5.5 0 0 0 13.9 2h-3.8a.5.5 0 0 0-.49.42l-.36 2.54c-.59.24-1.13.56-1.63.94l-2.39-.96a.5.5 0 0 0-.61.22L2.7 8.48a.5.5 0 0 0 .12.64l2.03 1.58c-.04.31-.07.63-.07.94s.03.63.07.94l-2.03 1.58a.5.5 0 0 0-.12.64l1.92 3.32c.13.22.39.31.61.22l2.39-.96c.5.38 1.04.7 1.63.94l.36 2.54c.05.24.25.42.49.42h3.8c.24 0 .45-.18.49-.42l.36-2.54c.59-.24 1.13-.56 1.63-.94l2.39.96c.22.09.48 0 .61-.22l1.92-3.32a.5.5 0 0 0-.12-.64l-2.03-1.58zM12 15.6A3.6 3.6 0 1 1 12 8.4a3.6 3.6 0 0 1 0 7.2z"/></svg>`;

class FdHome extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._demo = false;
    this._horizon = "today";
    this._view = "person";
    this._data = null;
    this._err = null; // "nc" | "err" | null
    this._seq = 0;
    this._flipped = false;
    this._moreNext = false;
    this._alertsOpen = false;
    this._sheet = null;
    this._rendered = false;
    this._toastTimer = null;
    this._me = null;          // {id, name, display_name} of the viewer's person
    this._mapped = undefined; // does the viewer map to a person? undefined = not known yet
    this._cycle = null;       // last known cycle (segment sub-labels)
    this._sum = {};           // household_summary per view (Spielraum fallback)
    this._acc = undefined;    // {accounts, assign} for the Konten column
    this._wide = false;
    this._cd = null;          // fd-cycle-detail instance
    this._cdKey = "";
  }

  set hass(h) {
    const first = !this._hass;
    this._hass = h;
    if (first) {
      this._renderShell();
      this._load();
      if (this._isAdmin) {
        const gp = window._fd._planGate && Date.now() - window._fd._planGate.at < 60000 ? window._fd._planGate.p
          : (window._fd._planGate = { at: Date.now(), p: h.callApi("GET", `${DOMAIN}/plan_wizard/gate`).catch(() => null) }).p;
        gp.then((g) => { this._gate = g; if (this._data) this._paint(); });
      }
    }
  }

  get demo() { return this._demo; }
  set demo(v) {
    v = !!v;
    if (v === this._demo) return;
    this._demo = v;
    if (this._hass) this.reload();
  }

  /** Re-read everything from the cache (after a save, an import or a reprocess). */
  reload() {
    this._sum = {};
    this._acc = undefined;
    return this._load();
  }

  disconnectedCallback() {
    this._ro?.disconnect();
    window.removeEventListener("resize", this._onResize);
  }

  connectedCallback() {
    if (this._rendered) this._observe();
  }

  // ---- data -------------------------------------------------------------
  async _load(dir) {
    if (!this._hass) return;
    const seq = ++this._seq;
    const asked = this._view;
    const q = `horizon=${this._horizon}&view=${asked}${this._demo ? "&demo=1" : ""}`;
    try {
      const d = await this._hass.callApi("GET", `${DOMAIN}/home?${q}`);
      if (seq !== this._seq) return;
      this._data = d;
      this._err = null;
      if (d && d.cycle) this._cycle = d.cycle;
      // Who am I? viewer_person (newer backend) wins; else learn it from the person view.
      if (d && d.viewer_person !== undefined) this._mapped = !!d.viewer_person;
      if (d && d.person) { this._me = d.person; this._mapped = true; }
      else if (d && asked === "person" && d.view === "household" && d.viewer_person === undefined) this._mapped = false;
      if (d && d.view && d.view !== this._view) this._view = d.view;
    } catch (e) {
      if (seq !== this._seq) return;
      this._err = e && e.status_code === 404 ? "nc" : "err";
    }
    this._paint(dir);
    const d = this._data;
    if (d && !this._err && this._horizon !== "year" && this._needsSummary(d)) this._loadSummary(d.view);
    if (d && this._wide && this._acc === undefined) this._loadAccounts();
  }

  _needsSummary(d) {
    if (this._budgetTotals(d).budget > 0) return false;
    if (d.view === "person" && d.person_budget && d.person_budget.budget > 0) return false;
    return this._sum[d.view] === undefined;
  }

  async _loadSummary(view) {
    this._sum[view] = null;
    try {
      const s = await this._hass.callApi("GET", `${DOMAIN}/household_summary?cycle=current${view === "person" ? "&view=person" : ""}`);
      this._sum[view] = s || null;
    } catch (e) {
      this._sum[view] = false;
    }
    if (this._data && this._data.view === view) this._paint();
  }

  async _loadAccounts() {
    this._acc = null;
    let accounts = [], assign = null;
    try {
      const b = await this._hass.callApi("GET", `${DOMAIN}/balances`);
      accounts = Object.entries(b || {}).filter(([, a]) => a && typeof a === "object" && !a.error).map(([id, a]) => ({ id, ...a }));
    } catch (e) { /* the column says it has nothing */ }
    if (this._isAdmin) {
      try { assign = await this._hass.callApi("GET", `${DOMAIN}/assignments`); } catch (e) { /* admin only */ }
    }
    this._acc = { accounts, assign };
    this._paintSide();
  }

  _setHorizon(h) {
    if (!HORIZONS.includes(h) || h === this._horizon) return;
    const from = HORIZONS.indexOf(this._horizon);
    const dir = HORIZONS.indexOf(h) > from ? "l" : "r";
    this._horizon = h;
    this._flipped = false;
    this._moreNext = false;
    this._paint(dir);
    this._load(dir);
  }

  _step(delta) {
    const i = HORIZONS.indexOf(this._horizon) + delta;
    if (i >= 0 && i < HORIZONS.length) this._setHorizon(HORIZONS[i]);
  }

  _setView(v) {
    if (v === this._view) return;
    this._view = v;
    this._paint();
    this._load();
  }

  // ---- helpers ----------------------------------------------------------
  get _t() { return window._fd.tSync; }
  get _isAdmin() { return !!(this._hass && this._hass.user && this._hass.user.is_admin); }
  _e(s) { return window._fd.escHtml(s); }
  _m(v, dec) {
    return new Intl.NumberFormat("de-DE", {
      style: "currency", currency: "EUR",
      minimumFractionDigits: dec ? 2 : 0, maximumFractionDigits: dec ? 2 : 0,
    }).format(v || 0);
  }
  _lang() { return (this._hass && this._hass.language) || navigator.language || "de"; }
  _date(iso) { return new Date(`${iso}T12:00:00`); }
  _day(iso) {
    const d = this._date(iso);
    return isNaN(d) ? "" : d.toLocaleDateString(this._lang(), { day: "numeric", month: "short" });
  }
  _dm(iso) {
    const d = iso instanceof Date ? iso : this._date(iso);
    return isNaN(d) ? "" : d.toLocaleDateString(this._lang(), { day: "2-digit", month: "2-digit" });
  }
  _wd(iso) {
    const d = this._date(iso);
    return isNaN(d) ? "" : d.toLocaleDateString(this._lang(), { weekday: "short" });
  }
  _kw(date) {
    const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
    const day = d.getUTCDay() || 7;
    d.setUTCDate(d.getUTCDate() + 4 - day);
    const y0 = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
    return Math.ceil(((d - y0) / 86400000 + 1) / 7);
  }
  _plural(key, n, vars) { return this._t(n === 1 ? `${key}_one` : key, { n, ...(vars || {}) }); }
  _cls(s) { return s === "over" ? "st-over" : s === "knapp" ? "st-near" : "st-ok"; }
  _statusOf(spent, linear) {
    if (spent <= linear + 0.005) return "good";
    return spent <= linear * 1.1 ? "knapp" : "over";
  }
  _chip(s) { return `<span class="chip ${this._cls(s)}">${this._t("home.status." + (s === "good" || !s ? "good" : s))}</span>`; }
  _nav(target, extra) {
    this.dispatchEvent(new CustomEvent("fd-navigate", { bubbles: true, composed: true, detail: { target, ...(extra || {}) } }));
  }
  _toast(msg) {
    const el = this.shadowRoot.getElementById("live");
    if (!el) return;
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => { el.hidden = true; }, 3200);
  }
  _shortName(p) {
    if (!p) return this._t("home.view.person");
    const n = String(p.display_name || p.nickname || p.name || p.id || "").trim();
    return p.display_name || p.nickname ? n : (n.split(/\s+/)[0] || n);
  }
  _fullName(p) { return p ? String(p.name || p.display_name || p.id || "") : ""; }

  // ---- shell ------------------------------------------------------------
  _renderShell() {
    const sh = this.shadowRoot;
    sh.innerHTML = `<style>${window._fd.SHARED_CSS}${CSS}</style>
<div class="root" id="root">
  <div class="top"><div class="tl"><slot name="menu"></slot><span id="fresh"></span></div><div class="tc" id="center"></div><div class="tr" id="right"></div>
    <div class="seg" id="seg" role="tablist" aria-label="${this._t("home.h.label")}"></div></div>
  <div id="panels"></div>
  <div class="layout" id="layout">
    <div class="main" id="main" role="tabpanel" aria-live="polite"></div>
    <aside class="side" id="side" aria-label="${this._t("home.desk.side")}"></aside>
  </div>
  <div class="nav" id="nav"><div class="toggle" id="toggle" role="radiogroup" aria-label="${this._t("home.view.label")}"></div></div>
  <div class="live" id="live" role="status" hidden></div>
  <div id="sheet"></div>
</div>`;
    sh.addEventListener("click", (e) => this._onClick(e));
    sh.addEventListener("keydown", (e) => this._onKey(e));
    sh.addEventListener("change", (e) => this._onChange(e));
    const main = sh.getElementById("main");
    let sx = 0, sy = 0, down = false;
    main.addEventListener("pointerdown", (e) => {
      if (e.target.closest("button, input, select, a")) return;
      down = true; sx = e.clientX; sy = e.clientY;
    });
    main.addEventListener("pointerup", (e) => {
      if (!down) return;
      down = false;
      const dx = e.clientX - sx, dy = e.clientY - sy;
      if (Math.abs(dx) > 56 && Math.abs(dx) > Math.abs(dy) * 1.6) this._step(dx < 0 ? 1 : -1);
    });
    main.addEventListener("pointercancel", () => { down = false; });
    main.addEventListener("animationend", () => main.classList.remove("slide-l", "slide-r"));
    this._rendered = true;
    this._observe();
    this._paint();
  }

  /** Width tracking: desktop column switch and the fixed pill's position. */
  _observe() {
    const root = this.shadowRoot.getElementById("root");
    if (!root) return;
    this._onResize = this._onResize || (() => this._measure());
    if (!this._ro && typeof ResizeObserver !== "undefined") this._ro = new ResizeObserver(this._onResize);
    this._ro?.observe(root);
    window.addEventListener("resize", this._onResize);
    this._measure();
  }

  _measure() {
    const root = this.shadowRoot.getElementById("root");
    const nav = this.shadowRoot.getElementById("nav");
    if (!root || !nav) return;
    const r = root.getBoundingClientRect();
    if (r.width > 0) {
      nav.style.left = `${Math.max(0, r.left)}px`;
      nav.style.right = "auto";
      nav.style.width = `${r.width}px`;
    }
    const wide = r.width >= 760;
    if (wide !== this._wide) {
      this._wide = wide;
      if (wide && this._data && this._acc === undefined) this._loadAccounts();
      // The cycle-detail slot moves between main (mobile) and side (desktop).
      if (this._data && this._horizon === "cycle") this._paint();
    }
  }

  _onKey(e) {
    if (e.key === "Escape" && this._sheet) { this._closeSheet(); return; }
    if (this._sheet) return;
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    if (e.target.closest && e.target.closest("#seg")) {
      this._step(e.key === "ArrowRight" ? 1 : -1);
      this.shadowRoot.querySelector(`#seg [data-h="${this._horizon}"]`)?.focus();
    } else if (e.target.closest && e.target.closest("#toggle")) {
      const v = e.key === "ArrowRight" ? "household" : "person";
      if (v === "person" && this._mapped === false) return;
      this._setView(v);
      this.shadowRoot.querySelector(`#toggle [data-v="${v}"]`)?.focus();
    }
  }

  _paint(dir) {
    if (!this._rendered) return;
    const sh = this.shadowRoot;
    const d = this._data;
    sh.getElementById("fresh").innerHTML = this._freshHtml();
    sh.getElementById("center").innerHTML = this._pillHtml();
    sh.getElementById("right").innerHTML = this._rightHtml();
    sh.getElementById("panels").innerHTML = this._panelsHtml();
    sh.getElementById("seg").innerHTML = this._segHtml();
    sh.getElementById("layout").classList.toggle("hl", this._horizon === "cycle" && !!d && !this._err);
    const main = sh.getElementById("main");
    main.classList.remove("slide-l", "slide-r");
    if (dir) { void main.offsetWidth; main.classList.add("slide-" + dir); }
    let body;
    if (this._err === "nc" && !d) body = this._notConfigured();
    else if (this._err && !d) body = `<div class="msg">${this._t("home.error")}<br><button class="btn" data-act="retry">${this._t("home.retry")}</button></div>`;
    else if (!d) body = `<div class="msg">${this._t("home.loading")}</div>`;
    else body = this._body(d);
    main.innerHTML = body;
    this._paintSide();
    this._paintToggle();
  }

  _paintSide() {
    const side = this.shadowRoot.getElementById("side");
    if (!side) return;
    const d = this._data;
    side.innerHTML = d && !this._err ? this._sideHtml(d) : "";
    this._placeCycleDetail();
  }

  _paintToggle() {
    const sh = this.shadowRoot;
    const nav = sh.getElementById("nav");
    // Only a user that maps to no person has a single view; everyone else always sees the pill.
    nav.hidden = this._mapped === false || this._err === "nc";
    const me = this._me;
    const short = this._shortName(me);
    const full = this._fullName(me) || short;
    const initial = (short || "?").trim().charAt(0).toUpperCase();
    const pTip = full !== short ? ` data-tip="${this._e(full)}"` : "";
    sh.getElementById("toggle").innerHTML = `
      <button role="radio" data-v="person" aria-checked="${this._view === "person"}" tabindex="${this._view === "person" ? 0 : -1}" style="--pc:var(--fd-person-a)" aria-label="${this._e(full)} · ${this._t("home.view.person_sub")}"${pTip}><i aria-hidden="true">${this._e(initial)}</i><span><b>${this._e(short)}</b><small>${this._t("home.view.person_sub")}</small></span></button>
      <button role="radio" data-v="household" aria-checked="${this._view === "household"}" tabindex="${this._view === "household" ? 0 : -1}" style="--pc:var(--fd-household)"><i aria-hidden="true">⌂</i><span><b>${this._t("home.view.household")}</b><small>${this._t("home.view.household_sub")}</small></span></button>`;
    requestAnimationFrame(() => this._measure());
  }

  /** fd-cycle-detail (agent A2): mobile under the Zyklus card, desktop at the top of the side column. */
  _placeCycleDetail() {
    const sh = this.shadowRoot;
    const d = this._data;
    if (!d || this._horizon !== "cycle" || this._err) return;
    const slot = sh.querySelector(this._wide ? "#side #cdslot" : "#main #cdslot");
    if (!slot) return;
    // fd-cycle-detail takes the person's display name; layout: strip in the main column, analysis in the side column.
    const person = d.view === "person" && this._me ? this._shortName(this._me) : "";
    const key = `${d.view}|${person}|${this._demo}`;
    if (!this._cd || this._cdKey !== key) {
      this._cd = document.createElement("fd-cycle-detail");
      this._cd.setAttribute("view", d.view === "person" ? "person" : "household");
      if (person) this._cd.setAttribute("person", person);
      this._cd.hass = this._hass;
      this._cdKey = key;
    }
    this._cd.setAttribute("layout", this._wide ? "full" : "strip");
    if (this._cd.parentNode !== slot) slot.appendChild(this._cd);
  }

  _notConfigured() {
    return `<section class="card setup"><h3>${this._t("home.nc.title")}</h3><p class="muted">${this._t("home.nc.body")}</p>
  <div class="acts">${this._isAdmin ? `<button class="btn" data-act="connect">${this._t("home.nc.connect")}</button>` : ""}<button class="btn ghost" data-act="demo">${this._t("home.demo")}</button></div></section>`;
  }

  // ---- top bar ----------------------------------------------------------
  _freshHtml() {
    const d = this._data || {};
    const fr = d.freshness || { status: "fresh" };
    const st = fr.status || "fresh";
    const icon = st === "error" ? "!" : st === "stale" ? "↻" : "✓";
    const time = this._freshTime(fr.as_of);
    const word = this._t("home.fresh." + st);
    const aria = time ? `${word} · ${time} – ${this._t("home.fresh.open")}` : `${word} – ${this._t("home.fresh.open")}`;
    return `<button class="ib fresh ${st === "fresh" ? "ok" : st}" data-act="fresh" aria-label="${this._e(aria)}" data-tip="${this._e(this._t("home.fresh.open"))}"><i aria-hidden="true">${icon}</i><span class="t">${this._e(word)}${time ? " ·" : ""}</span>${time ? `<span class="tm">${this._e(time)}</span>` : ""}</button>`;
  }

  /** "06:30" today, "gestern 06:30", else "28.10." */
  _freshTime(iso) {
    if (!iso) return "";
    const t = new Date(iso);
    if (isNaN(t)) return "";
    const now = new Date();
    const hm = t.toLocaleTimeString(this._lang(), { hour: "2-digit", minute: "2-digit" });
    const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
    if (sameDay(t, now)) return hm;
    const y = new Date(now); y.setDate(now.getDate() - 1);
    if (sameDay(t, y)) return this._t("home.fresh.yesterday", { time: hm });
    return this._dm(t);
  }

  _pillHtml() {
    const alerts = (this._data && this._data.alerts) || [];
    if (!alerts.length) return "";
    const worst = alerts.find((a) => a.severity === "warn") || alerts[0];
    return `<button class="pill ${worst.severity === "warn" ? "" : "info"}" data-act="alerts" aria-expanded="${this._alertsOpen}" aria-label="${this._t("home.alert.open")}"><i></i><span>${this._e(this._alertTitle(worst))}</span>${alerts.length > 1 ? `<span class="muted">+${alerts.length - 1}</span>` : ""}</button>`;
  }

  _rightHtml() {
    const q = (this._data && this._data.questions_open) || 0;
    const star = q ? this._t("home.star", { n: q }) : this._t("home.star.none");
    const gear = this._t("home.settings");
    const hhc = this._view === "household" ? `<span class="hhchip">${this._t("home.view.household")}</span>` : "";
    return `${hhc}<button class="ib ask" data-act="ask" data-tip="${this._e(star)}" aria-label="${this._e(star)}">
    <span class="ring" style="--p:${q ? 86 : 100}%"><span>★</span></span>${q ? `<b>${Math.min(q, 10)}</b>` : ""}<span class="qt">${this._e(q ? this._plural("home.top.questions", q) : this._t("home.top.questions_none"))}</span></button>
  <button class="ib gear" data-act="settings" data-tip="${this._e(gear)}" aria-label="${this._e(gear)}">${GEAR}</button>`;
  }

  _alertTitle(a) {
    const key = "home.alert." + a.kind;
    const s = this._t(key, { bank: a.title || "" });
    return s === key ? (a.title || "") : s;
  }

  _panelsHtml() {
    const d = this._data || {};
    if (!this._alertsOpen || !(d.alerts || []).length) return "";
    return `<div class="panel" role="region" aria-label="${this._t("home.alert.open")}">${d.alerts.map((a) => `
        <div class="alert ${a.severity}"><span>${this._e(this._alertTitle(a))}</span>
        <span><button class="btn sm" data-act="renew">${this._t("home.alert.renew")}</button></span></div>`).join("")}
        <div class="acts"><button class="btn ghost sm" data-act="alerts">${this._t("home.alert.close")}</button></div></div>`;
  }

  // ---- segment ----------------------------------------------------------
  _segHtml() {
    const now = new Date();
    const cy = this._cycle;
    const subs = {
      today: `<small>${this._e(now.toLocaleDateString(this._lang(), { weekday: "short", day: "2-digit", month: "2-digit" }))}</small>`,
      week: `<small>${this._t("home.h.week_sub", { n: this._kw(now) })}</small>`,
      cycle: cy && cy.days ? `<small><span class="narrow">${this._e(this._cycleLeft(cy))}</span><span class="wide">${this._e(`${this._dm(cy.start)}–${this._dm(cy.end)}`)}</span></small>` : "<small>&nbsp;</small>",
      year: `<small>${now.getFullYear()}</small>`,
    };
    return HORIZONS.map((h) => {
      const on = h === this._horizon;
      return `<button role="tab" data-h="${h}" aria-selected="${on}" tabindex="${on ? 0 : -1}"><span>${this._t("home.h." + h)}</span>${subs[h]}</button>`;
    }).join("");
  }

  _cycleLeft(cy) {
    const n = Math.max(0, (cy.days || 0) - (cy.day || 0));
    return n === 0 ? this._t("home.h.cycle_last") : this._plural("home.h.cycle_left", n);
  }

  // ---- bodies -----------------------------------------------------------
  _body(d) {
    let h = "";
    if (this._horizon !== "year" && this._horizon !== "cycle") h += this._setupCard(d);
    switch (this._horizon) {
      case "today": return h + this._today(d);
      case "week": return h + this._week(d);
      case "cycle": return h + this._cycle_(d);
      default: return this._year(d);
    }
  }

  /** One calm card above the content, only while something is genuinely missing. */
  _setupCard(d) {
    const wiz = this._wizardCard(d);
    if (wiz) return wiz;
    const st = d.setup || {};
    if (!this._demo && st.accounts_total === 0) {
      return `<section class="card setup"><h3>${this._t("home.setup.bank_title")}</h3><p class="muted">${this._t("home.setup.bank_body")}</p>
  ${this._isAdmin ? `<div class="acts"><button class="btn" data-act="connect">${this._t("home.nc.connect")}</button></div>` : ""}</section>`;
    }
    if (st.persons === 0 || (st.accounts_total || 0) > (st.accounts_assigned || 0)) {
      return `<section class="card setup"><h3>${this._t("home.setup.assign_title")}</h3><p class="muted">${this._t("home.setup.assign_body")}</p>
  <div class="acts"><button class="btn" data-act="settings" data-section="accounts">${this._t("home.setup.assign_cta")}</button></div></section>`;
    }
    return "";
  }

  /** Guided setup: resume card while the wizard is not completed (admin: CTA, member: calm note). */
  _wizardCard(d) {
    const admin = this._isAdmin;
    const w = admin ? this._wizard : { completed: false, steps: {}, current_step: "persons" };
    if (admin && w === undefined) this._loadWizard();
    if (!w || w.completed) return "";
    if (!admin) {
      const st = (d && d.setup) || {};
      if (!(st.persons === 0 || (st.accounts_total || 0) > (st.accounts_assigned || 0))) return "";
      return `<section class="card setup"><h3>${this._t("home.setup.member_title")}</h3><p class="muted">${this._t("home.setup.member_body")}</p></section>`;
    }
    const order = ["persons", "accounts", "payday", "region", "notifications", "ai", "points", "done"];
    const n = Math.max(0, order.indexOf(w.current_step)) + 1;
    const started = Object.values(w.steps || {}).some((s) => s && s !== "pending");
    return `<section class="card setup"><h3>${this._t(started ? "home.setup.resume_title" : "home.setup.start_title", { n, total: order.length })}</h3>
  <p class="muted">${this._t("home.setup.resume_body")}</p><div class="acts"><button class="btn" data-act="wizard">${this._t(started ? "home.setup.resume_cta" : "home.setup.start_cta")}</button></div></section>`;
  }

  async _loadWizard() {
    this._wizard = null;
    try { this._wizard = await this._hass.callApi("GET", `${DOMAIN}/setup`); }
    catch (e) { this._wizard = { completed: true }; }
    this._paint();
  }

  _budgetTotals(d) {
    const pots = d.pots || [], pers = d.persons || [];
    const budget = pots.reduce((s, p) => s + (p.cycle_budget || 0), 0) + pers.reduce((s, p) => s + (p.budget || 0), 0);
    const spent = pots.reduce((s, p) => s + (p.spent || 0), 0) + pers.reduce((s, p) => s + (p.spent || 0), 0);
    return { budget, spent };
  }

  _soll(d) {
    const cy = d.cycle || {};
    return cy.days > 0 ? Math.min(1, (cy.day || 0) / cy.days) : 0;
  }

  _daysLeft(d) {
    const cy = d.cycle || {};
    return Math.max(1, (cy.days || 1) - (cy.day || 1) + 1);
  }

  /**
   * The free money of this view: pots when there are any; else the person's
   * own budget (/home person_budget) or the cycle's income − spend from
   * /household_summary (person view: the viewer's own row only).
   */
  _spielraum(d) {
    const tot = this._budgetTotals(d);
    if (tot.budget > 0) return { kind: "pots", budget: tot.budget, spent: tot.spent, remaining: d.remaining || 0, status: d.status };
    const soll = this._soll(d);
    const mk = (budget, spent, extra) => {
      const remaining = budget - spent;
      return { kind: "own", budget, spent, remaining, status: this._statusOf(spent, budget * soll), ...(extra || {}) };
    };
    const pb = d.view === "person" ? d.person_budget : null;
    if (pb && pb.budget > 0) return mk(pb.budget, pb.spent || 0, { source: pb.source });
    const s = this._sum[d.view];
    if (s === undefined || s === null) return { kind: "loading" };
    if (s === false) return { kind: "none" };
    const row = d.view === "person"
      ? (s.owners || []).find((o) => o.kind === "person" && !o.restricted) || null
      : s;
    if (!row) return { kind: "none" };
    const income = row.income || 0, exp = row.expenses || 0;
    return mk(income, exp, { source: "history", pending: !!s.income_pending, expected: s.expected_income_date || null, noIncome: income <= 0 });
  }

  _srCaption(sr, d) {
    if (sr.kind === "pots") return this._t("home.today.remaining");
    return this._t(d.view === "person" ? "home.sr.person" : "home.sr.household");
  }

  _srNote(sr) {
    if (sr.kind !== "own") return "";
    if (sr.noIncome) {
      return `<div class="muted" style="margin-top:6px">${sr.pending && sr.expected ? this._t("home.sr.income_expected", { date: this._e(this._day(sr.expected)) }) : this._t("home.sr.no_income")}</div>`;
    }
    return `<div class="muted" style="margin-top:6px">${this._t(sr.source === "plan" ? "home.sr.from_plan" : "home.sr.from_history", { income: this._m(sr.budget, false), spent: this._m(sr.spent, false) })}</div>`;
  }

  _srEmpty(sr) {
    if (sr.kind === "loading") return `<section class="card"><div class="muted">${this._t("home.loading")}</div></section>`;
    return `<section class="card"><div class="h"><span>${this._t("home.sr.none_title")}</span></div><p class="muted" style="margin:0">${this._t("home.sr.none_body")}</p></section>`;
  }

  _today(d) {
    const sr = this._spielraum(d);
    if (sr.kind === "loading" || sr.kind === "none") return this._srEmpty(sr) + this._potsCard(d);
    const c = this._cls(sr.status);
    const t = d.today || {};
    const left = Math.max(0, sr.remaining);
    const pctFill = sr.budget > 0 ? Math.min(100, (left / sr.budget) * 100) : 0;
    const daily = sr.kind === "pots" && t.daily_budget > 0 ? t.daily_budget : left / this._daysLeft(d);
    const days = sr.kind === "pots" && t.daily_budget > 0 ? Math.floor(left / t.daily_budget) : null;
    const end = d.cycle && d.cycle.end ? this._day(d.cycle.end) : "";
    return `<section class="card ${c}">
  <div class="big">${this._m(sr.remaining, false)}</div><div class="cap">${this._srCaption(sr, d)}${end ? ` · ${this._t("home.today.until", { date: this._e(end) })}` : ""}</div>
  ${sr.budget > 0 ? `<div class="meter" role="img" aria-label="${this._e(this._t("home.today.bar"))}: ${this._m(left, false)} / ${this._m(sr.budget, false)}"><i style="width:${pctFill.toFixed(1)}%"></i></div>
    <div class="muted">${this._t("home.today.bar_of", { amount: this._m(sr.budget, false) })}</div>` : ""}
  ${this._srNote(sr)}
  <div class="tiles two">
    <div class="tile"><span>${this._t("home.today.spent")}</span><b>${t.spent !== undefined ? this._m(t.spent, true) : "–"}</b></div>
    <div class="tile"><span>${days !== null ? this._plural("home.today.days", days) : this._t("home.week.per_day")}</span><b>${this._t("home.today.per_day", { amount: this._m(daily, true) })}</b></div>
  </div></section>${this._potsCard(d)}`;
  }

  _potRows(pots) {
    return pots.map((p) => `<div class="pot ${this._cls(p.status)}"><i></i>
      <span><b>${this._e(p.name)}</b><small class="muted">${this._t("home.pots.per_day", { amount: this._m(p.per_day, true) })}</small></span>
      <em>${this._m(p.balance, false)}</em></div>`).join("");
  }

  _potsCard(d) {
    const hh = d.view === "household";
    const pots = d.pots || [];
    const persons = hh ? (d.persons || []) : [];
    const personRows = persons.map((p) => `<div class="pot ${this._cls(p.status)}"><i></i>
      <span><b>${this._e(p.display_name || p.name)}</b><small class="muted">${this._t("home.persons.left")}</small></span>
      <em>${this._m(p.balance, false)}</em></div>`).join("");
    let empty = "";
    if (!pots.length) {
      const sug = this._suggestions(d).slice(0, 2);
      const cats = window._fd.CAT_LABELS || {};
      empty = `<div class="muted">${this._t(hh ? "home.pots.empty_household" : "home.pots.empty")}</div>
        ${sug.length ? `<div class="chips">${sug.map((k) => `<button class="sgc" data-act="sugcreate" data-k="${this._e(k)}">+ ${this._e(cats[k] || k)}</button>`).join("")}</div>` : ""}`;
    }
    return `<section class="card"><div class="h"><span>${this._t(hh ? "home.pots.household" : "home.pots.person")}</span>
      <button class="add" data-act="addpot" data-tip="${this._t("home.pots.add")}" aria-label="${this._t("home.pots.add")}">+</button></div>
      ${pots.length ? this._potRows(pots) : empty}
      ${persons.length ? `<div class="h" style="margin-top:10px"><span class="muted">${this._t("home.persons.title")}</span></div>${personRows}` : ""}</section>`;
  }

  _nextRows(items) {
    return (items || []).map((i) => `<div class="nx"><span class="lb">${this._e(i.label)}</span>
      <span class="amt">${this._m(i.amount, true)}</span>
      <span class="mt"><small class="muted">${this._day(i.date)}</small>${i.pending ? `<span class="tag">${this._t("home.pending")}</span>` : ""}</span></div>`).join("");
  }

  _upcoming(items, title, sum, tail) {
    return `<section class="card"><div class="h"><span>${title}</span>${sum !== undefined ? `<span class="sub">${this._m(sum, true)}</span>` : ""}</div>
      ${this._nextRows(items) || `<div class="muted">${this._t("home.upcoming.none")}</div>`}${tail || ""}</section>`;
  }

  _week(d) {
    const w = d.week;
    const up = (w && w.upcoming) || {};
    const upcoming = this._upcoming(up.items, this._t("home.week.upcoming"), up.sum);
    if (!w || !(w.week_budget > 0)) return this._weekOwn(d) + upcoming;
    const days = w.days || [];
    const lin = w.linear_line || [], zero = w.zero_carry_line || [];
    let acc = 0;
    const cum = days.map((x) => (acc += x.actual || 0));
    const tIdx = Math.max(0, days.findIndex((x) => x.today));
    const st = this._statusOf(cum[tIdx] || 0, lin[tIdx] || 0);
    const cc = this._cls(st);
    const ymax = Math.max(1, ...lin, ...zero, ...cum) * 1.12;
    const X = (i) => i * 100 + 50, Y = (v) => 140 - (Math.max(0, v) / ymax) * 132;
    const bars = days.map((x, i) => {
      if (x.future) return "";
      const s = this._statusOf(cum[i], lin[i] || 0);
      const col = s === "over" ? "var(--fd-over)" : s === "knapp" ? "var(--fd-near)" : "var(--fd-ok)";
      const h = Math.max(0, (cum[i] / ymax) * 132);
      return `<rect x="${i * 100 + 18}" width="64" y="${140 - h}" height="${h}" rx="4" fill="${col}"/>`;
    }).join("");
    const pts = (a) => a.map((v, i) => `${X(i)},${Y(v)}`).join(" ");
    const carry = w.carry_over || 0;
    return `<section class="card ${cc}"><div class="band"><div class="big">${this._m(w.remaining, false)}</div>
      <div class="cap">${this._t("home.week.left")}</div></div>
    ${Math.abs(carry) >= 0.5 ? `<div class="carry"><b>${carry > 0 ? "+" : "−"}${this._m(Math.abs(carry), false)}</b><span>${this._carryText(d, carry)}</span></div>` : ""}
    <div class="chart"><svg viewBox="0 0 700 140" preserveAspectRatio="none" role="img" aria-label="${this._t("home.week.chart")}">
      ${bars}<polyline points="${pts(zero)}" fill="none" stroke="var(--fd-t3)" stroke-width="1" stroke-dasharray="4 4" vector-effect="non-scaling-stroke"/>
      <polyline points="${pts(lin)}" fill="none" stroke="var(--fd-a900)" stroke-width="2.2" vector-effect="non-scaling-stroke"/></svg></div>
    <div class="days">${days.map((x) => `<div class="${x.today ? "today" : ""}">${this._wd(x.date)}<b>${!x.in_cycle ? "–" : x.future ? "&nbsp;" : this._m(x.actual, false)}</b></div>`).join("")}</div>
    <div class="legend"><span><i></i>${this._t("home.week.legend_spent")}</span><span><i class="l1"></i>${this._t("home.week.legend_soll")}</span><span><i class="l2"></i>${this._t("home.week.legend_zero")}</span></div>
    <div class="tiles"><div class="tile"><span>${this._t("home.week.spent")}</span><b>${this._m(w.spent, false)}</b></div>
      <div class="tile"><span>${this._t("home.week.per_day")}</span><b>${this._m(w.daily_budget, false)}</b></div>
      <div class="tile"><span>${this._t("home.week.budget")}</span><b>${this._m(w.week_budget, false)}</b></div></div></section>
    ${upcoming}`;
  }

  /** "+21 € aus KW 43 mitgenommen" when the cycle started before last week's Monday ended, else "aus den Vorwochen". */
  _carryText(d, carry) {
    const w = d.week || {};
    const start = w.start ? this._date(w.start) : null;
    const cs = d.cycle && d.cycle.start ? this._date(d.cycle.start) : null;
    if (start && cs && !isNaN(start) && !isNaN(cs)) {
      const prevMon = new Date(start); prevMon.setDate(start.getDate() - 7);
      if (cs >= prevMon) {
        const prev = new Date(start); prev.setDate(start.getDate() - 1);
        return this._t(carry > 0 ? "home.week.carry_plus_kw" : "home.week.carry_minus_kw", { n: this._kw(prev) });
      }
    }
    return this._t(carry > 0 ? "home.week.carry_plus" : "home.week.carry_minus");
  }

  /** Week without pots: the own (or household) Spielraum, spread over the days left. */
  _weekOwn(d) {
    const sr = this._spielraum(d);
    if (sr.kind === "loading" || sr.kind === "none") return this._srEmpty(sr);
    const perDay = Math.max(0, sr.remaining) / this._daysLeft(d);
    const inWeek = Math.min(7 - ((new Date().getDay() + 6) % 7), this._daysLeft(d));
    return `<section class="card ${this._cls(sr.status)}"><div class="band"><div class="big">${this._m(perDay * inWeek, false)}</div>
      <div class="cap">${this._t("home.week.own_left")}</div></div>
      ${this._srNote(sr)}
      <div class="tiles two"><div class="tile"><span>${this._t("home.week.per_day")}</span><b>${this._m(perDay, false)}</b></div>
      <div class="tile"><span>${this._srCaption(sr, d)}</span><b>${this._m(sr.remaining, false)}</b></div></div></section>`;
  }

  _cycleBlock(d) {
    const cy = d.cycle || {};
    const range = `${this._day(cy.start)} – ${this._day(cy.end)}`;
    const infoLbl = this._flipped ? this._t("home.cycle.back") : this._t("home.cycle.info");
    const head = (extra) => `<div class="h"><span>${this._t("home.cycle.title")} ${this._e(range)}<button class="info" data-act="flip" data-tip="${this._e(infoLbl)}" aria-label="${this._e(infoLbl)}" aria-pressed="${this._flipped}">${this._flipped ? "×" : "ⓘ"}</button></span><span class="sub">${extra}</span></div>`;
    const dayTxt = this._t("home.cycle.day", { n: cy.day, total: cy.days });
    if (this._flipped) {
      const rule = this._t(`home.cycle.rule.${cy.rule || "calendar_fallback"}`, { name: this._e(cy.anchor || "") });
      return `<section class="card flip">${head(dayTxt)}<p style="margin:6px 0 0">${rule}</p></section>`;
    }
    const sr = this._spielraum(d);
    if (sr.kind === "loading" || sr.kind === "none") return `<section class="card">${head(dayTxt)}</section>${this._srEmpty(sr)}`;
    const frac = sr.budget > 0 ? Math.min(1, Math.max(0, sr.spent / sr.budget)) : 0;
    const soll = this._soll(d);
    const delta = sr.budget * soll - sr.spent;
    const verdictKey = sr.status === "over" ? "over" : sr.status === "knapp" ? "knapp" : "good";
    return `<section class="card ${this._cls(sr.status)} flip">${head(dayTxt)}
      <div class="verdict"><span class="chip">${this._t("home.cycle.verdict." + verdictKey)}</span>
        ${sr.budget > 0 ? `<span class="muted">${this._t(delta >= 0 ? "home.cycle.ahead" : "home.cycle.behind", { amount: this._m(Math.abs(delta), false) })}</span>` : ""}</div>
      <div class="tank" role="img" aria-label="${this._e(this._srCaption(sr, d))}: ${this._m(sr.remaining, false)}">
        <i style="width:${(frac * 100).toFixed(1)}%"></i><b style="left:${(soll * 100).toFixed(1)}%" aria-hidden="true"></b>
        <div class="ta">${this._m(sr.remaining, false)}<small>${this._srCaption(sr, d)}</small></div></div>
      ${this._srNote(sr)}
      <div class="tiles"><div class="tile"><span>${this._t(sr.kind === "pots" ? "home.cycle.budget" : "home.cycle.income")}</span><b>${this._m(sr.budget, false)}</b></div>
        <div class="tile"><span>${this._t("home.cycle.spent")}</span><b>${this._m(sr.spent, false)}</b></div>
        <div class="tile"><span>${this._t("home.cycle.per_day")}</span><b>${this._m(Math.max(0, sr.remaining) / this._daysLeft(d), false)}</b></div></div></section>`;
  }

  /** "Haushaltsplan erstellen" while the plan gate is open (or unknown); else the expected date. */
  _planCta(cls) {
    const g = this._gate;
    if (g && !g.ready) {
      const when = g.ready_from ? window._fd.fmtDate(g.ready_from) : "";
      return `<span class="muted" role="status">${when ? this._t("home.plan.gate", { date: when }) : this._t("home.plan.gate_nodata")}</span>`;
    }
    return `<button class="${cls}" data-act="planwizard">${this._t("home.cycle.plan_create")}</button>`;
  }

  _fixed(d) {
    if (d.fixed_costs_covered === null || d.fixed_costs_covered === undefined) {
      return `<div style="margin:0 0 12px" class="muted">${this._t("home.cycle.fixed_noplan")} ${this._planCta("link")}</div>`;
    }
    return `<div style="margin:0 0 12px"><span class="chip ${d.fixed_costs_covered ? "st-ok" : "st-near"}">${d.fixed_costs_covered ? "✓ " : ""}${this._t(d.fixed_costs_covered ? "home.cycle.fixed_ok" : "home.cycle.fixed_no")}</span></div>`;
  }

  _dyk(d) {
    const k = d.did_you_know;
    if (!k) return "";
    const p = k.params || {};
    const cat = (window._fd.CAT_LABELS || {})[p.category] || p.category;
    const key = "home.dyk." + k.key;
    let text = this._t(key, { share: Math.round((p.share || 0) * 100), category: cat });
    if (text === key) text = k.text || "";
    return `<section class="card know"><span><b>${this._t("home.dyk.title")}</b>${this._e(text)}</span></section>`;
  }

  _next(d) {
    const all = d.next_all || d.next || [];
    const total = Math.max(d.next_total || 0, all.length);
    const items = this._moreNext ? all : (d.next || []).slice(0, 3);
    const hidden = Math.max(0, total - items.length);
    const toggle = hidden > 0
      ? `<button class="more" data-act="more">${this._t("home.next.more", { n: hidden })}</button>`
      : (this._moreNext && total > 3 ? `<button class="more" data-act="more">${this._t("home.next.less")}</button>` : "");
    return this._upcoming(items, this._t("home.next.title"), undefined, toggle);
  }

  _reserves(d) {
    const r = d.reserves || [];
    return `<section class="card"><div class="h"><span>${this._t("home.reserves.title")}</span></div>
      ${r.length ? r.map((p) => `<div class="pot st-ok"><i></i><span><b>${this._e(p.name)}</b><small class="muted">${this._t("home.pots.per_day", { amount: this._m(p.per_day, true) })}</small></span><em style="color:var(--fd-t1)">${this._m(p.balance, false)}</em></div>`).join("")
        : `<div class="muted">${this._t("home.reserves.empty")}</div>`}</section>`;
  }

  _cycle_(d) {
    // H1 · Held oben, Kassenbuch darunter: hero, then ledger | Als Nächstes + Einrichten.
    // fd-cycle-detail sits under the grid on mobile (desktop: analysis cards below, see _sideHtml).
    return this._hero(d) + this._fixed(d)
      + `<div class="hl-grid"><div class="hl-main">${this._ledger(d)}</div><div class="hl-side">${this._next(d)}${this._strip(d)}</div></div>`
      + (this._wide ? "" : `<div id="cdslot"></div>`);
  }

  /** The cycle's verdict: free money, pill, labelled bar (today + Soll) and three KPI tiles. */
  _hero(d) {
    const sr = this._spielraum(d);
    if (sr.kind === "loading" || sr.kind === "none") return this._srEmpty(sr);
    const hh = d.view === "household";
    const cy = d.cycle || {};
    const soll = this._soll(d);
    const frac = sr.budget > 0 ? Math.min(1, Math.max(0, sr.spent / sr.budget)) : 0;
    const vkey = sr.status === "over" ? "over" : sr.status === "knapp" ? "knapp" : "good";
    const bar = sr.status === "over" ? "var(--fd-over)" : hh ? "var(--fd-household)" : "var(--fd-a500)";
    const end = cy.end ? this._day(cy.end) : "";
    const cap = this._t(hh ? "home.hero.cap_household" : "home.hero.cap", { date: this._e(end) });
    const infoLbl = this._flipped ? this._t("home.cycle.back") : this._t("home.cycle.info");
    const rule = this._flipped ? `<p class="hrule">${this._t(`home.cycle.rule.${cy.rule || "calendar_fallback"}`, { name: this._e(cy.anchor || "") })}</p>` : "";
    const left = Math.max(0, sr.remaining) / this._daysLeft(d);
    const flow = d.cycle_flow || {};
    const money = (v) => this._m(v, false);
    const tile = (label, val) => `<div class="kpi"><span>${this._e(label)}</span><b>${val}</b></div>`;
    let tiles;
    if (hh) {
      const ps = (d.persons || []).slice(0, 2);
      tiles = tile(this._t("home.hero.kpi_shared"), money(sr.kind === "pots" ? sr.spent : (flow.expenses ?? sr.spent)))
        + ps.map((p) => tile(this._t("home.hero.kpi_share", { name: p.display_name || p.name }), money(p.spent))).join("")
        + (ps.length < 2 ? tile(this._t("home.cycle.per_day"), money(left)) : "");
    } else {
      tiles = tile(this._t("home.cycle.income"), money(flow.income ?? (sr.kind === "own" ? sr.budget : 0)))
        + tile(this._t("home.hero.kpi_spent"), money(flow.expenses ?? sr.spent))
        + tile(this._t("home.hero.kpi_per_day"), money(left));
    }
    const x = `${(soll * 100).toFixed(1)}%`;
    const day = this._t("home.hero.today", { n: cy.day, total: cy.days });
    return `<section class="card hero ${this._cls(sr.status)}"><div class="hero-in"><div>
      <div class="hcap"><span>${cap}</span><button class="info" data-act="flip" data-tip="${this._e(infoLbl)}" aria-label="${this._e(infoLbl)}" aria-pressed="${this._flipped}">${this._flipped ? "×" : "ⓘ"}</button></div>${rule}
      <div class="hbig"><span class="big">${money(sr.remaining)}</span><span class="vpill">${this._t("home.cycle.verdict." + vkey)}</span></div>
      ${sr.budget > 0 ? `<div class="hbar" style="--bar:${bar};--x:${x}" role="img" aria-label="${this._e(cap)}: ${money(sr.remaining)}"><i style="width:${(frac * 100).toFixed(1)}%"></i>
        <b class="tm" style="left:${x}" aria-hidden="true"></b><b class="tg" style="left:${x}" aria-hidden="true"></b>
        <span class="lbl lt">${this._e(day)}</span><span class="lbl lb">${this._t("home.hero.target")}</span></div>` : ""}
      ${this._srNote(sr)}</div>
      <div class="kpis">${tiles}</div></div></section>`;
  }

  /** Recent bookings by day (admin only: the API sends no rows to anyone else). */
  _ledger(d) {
    const head = `<div class="h"><span>${this._t("home.ledger.title")}</span></div>`;
    if (d.recent === undefined || !this._isAdmin) {
      return `<section class="card">${head}<div class="muted">${this._t(this._isAdmin ? "home.ledger.none" : "home.ledger.admin_only")}</div></section>`;
    }
    if (!d.recent.length) return `<section class="card">${head}<div class="muted">${this._t("home.ledger.none")}</div></section>`;
    const now = new Date();
    const key = (dt) => `${dt.getFullYear()}-${dt.getMonth()}-${dt.getDate()}`;
    const yest = new Date(now); yest.setDate(now.getDate() - 1);
    const dayName = (iso) => {
      const dt = this._date(iso);
      if (key(dt) === key(now)) return this._t("home.ledger.today");
      if (key(dt) === key(yest)) return this._t("home.ledger.yesterday");
      return `${this._wd(iso)}, ${this._day(iso)}`;
    };
    const cat = (window._fd.catLabel || ((k) => k));
    const groups = [];
    for (const r of d.recent.slice(0, 12)) {
      const g = groups[groups.length - 1];
      if (g && g.date === r.date) g.rows.push(r); else groups.push({ date: r.date, rows: [r] });
    }
    const amt = (v) => `${v > 0 ? "+" : ""}${this._m(v, true)}`.replace("-", "−");
    return groups.map((g) => `<div class="lday">${this._e(dayName(g.date))}</div><div class="lcard">${g.rows.map((r) => `
      <div class="lrow"><span>${this._e(r.label)}${r.category ? ` <span class="lc2">· ${this._e(cat(r.category))}</span>` : ""}${r.pending ? `<span class="tag">${this._t("home.pending")}</span>` : ""}</span>
        <span class="amt${r.amount > 0 ? " in" : ""}">${amt(r.amount)}</span></div>`).join("")}</div>`).join("")
      + `<button class="lmore" data-act="nav" data-target="transactions">${this._t("home.ledger.all")} ▸</button>`;
  }

  /** What is still open to set up (blockers first). One strip instead of the pot / suggestion / accounts cards. */
  _todos(d) {
    const st = d.setup || {};
    const admin = this._isAdmin;
    const out = [];
    if (admin && this._wizard === undefined) this._loadWizard();
    if (admin && this._wizard && !this._wizard.completed) out.push({ act: "wizard", blocker: true });
    if (!this._demo && st.accounts_total === 0) out.push({ act: "connect", blocker: true });
    else if (admin && (st.persons === 0 || (st.accounts_total || 0) > (st.accounts_assigned || 0))) out.push({ act: "assign" });
    if (!(d.pots || []).length && !(d.reserves || []).length) out.push({ act: "addpot" });
    return out;
  }

  _strip(d) {
    const todos = this._todos(d);
    if (!todos.length) return "";
    return `<div class="strip${todos.some((x) => x.blocker) ? " blocker" : ""}"><span>⚑ ${this._t("home.strip.title", { n: todos.length })}</span>
      <button class="btn sm" data-act="setupopen">${this._t("home.strip.open")}</button></div>`;
  }

  _openSetup() {
    const first = this._todos(this._data || {})[0];
    if (!first) return;
    if (first.act === "wizard") this._nav("setup");
    else if (first.act === "connect") window._fd.navigate(window._fd.INTEGRATION_PATH);
    else if (first.act === "assign") this._nav("settings", { section: "accounts" });
    else this._openSheet(null);
  }

  _year(d) {
    const y = d.year || {};
    const year = new Date().getFullYear();
    const byMonth = new Map();
    for (const c of y.cycles || []) {
      if (!c || !c.start || Number(c.start.slice(0, 4)) !== year) continue;
      byMonth.set(Number(c.start.slice(5, 7)) - 1, c);
    }
    const cyc = Array.from({ length: 12 }, (_, m) => {
      const lab = new Date(year, m, 15).toLocaleDateString(this._lang(), { month: "short" });
      const c = byMonth.get(m);
      if (!c) return `<span class="fut" data-tip="${this._e(`${lab} · ${this._t("home.year.no_data")}`)}" aria-label="${this._e(`${lab} ${this._t("home.year.no_data")}`)}" tabindex="0">${this._e(lab)}</span>`;
      const known = c.status === "good" || c.status === "knapp" || c.status === "over";
      const cls = c.current ? "run" : known ? "" : "fut";
      const col = c.status === "over" ? "var(--fd-over)" : c.status === "knapp" ? "var(--fd-near)" : "var(--fd-ok)";
      const st = c.current ? this._t("home.year.running") : known ? this._t("home.status." + c.status) : this._t("home.year.no_data");
      return `<span class="${cls}" style="--c:${col}" data-tip="${this._e(`${lab} · ${st}`)}" aria-label="${this._e(`${lab} ${st}`)}" tabindex="0">${this._e(lab)}</span>`;
    }).join("");
    const v = y.vs_last_year || {};
    let vs;
    if (v.available) {
      const mx = Math.max(v.spent, v.spent_last_year, 1);
      vs = `<div class="row"><span>${this._t("home.year.this")}</span><span class="amt">${this._m(v.spent, false)}</span></div>
        <div class="cmp"><i style="width:${(v.spent / mx) * 100}%"></i></div>
        <div class="row"><span>${this._t("home.year.last")}</span><span class="amt">${this._m(v.spent_last_year, false)}</span></div>
        <div class="cmp prev"><i style="width:${(v.spent_last_year / mx) * 100}%"></i></div>
        <div class="muted">${this._t(v.delta <= 0 ? "home.year.vs_less" : "home.year.vs_more", { amount: this._m(Math.abs(v.delta), false) })}</div>`;
    } else vs = `<div class="muted">${this._t("home.year.vs_na")}</div>`;
    const entry = (target, icon, title, sub) => `<button class="entry" data-act="nav" data-target="${target}"><i aria-hidden="true">${icon}</i><span><b>${this._t(title)}</b><small class="muted">${this._t(sub)}</small></span><span aria-hidden="true">›</span></button>`;
    return `<section class="card"><div class="h"><span>${this._t("home.year.title", { year })}</span></div><div class="cyc">${cyc}</div></section>
      <section class="card"><div class="h"><span>${this._t("home.year.vs")}</span></div>${vs}</section>
      ${entry("contracts", "☰", "home.year.contracts", "home.year.contracts_sub")}
      ${entry("benchmark", "≈", "home.year.benchmark", "home.year.benchmark_sub")}
      ${entry("plan", "▤", "home.year.plan", "home.year.plan_sub")}
      ${this._dyk(d)}${this._reserves(d)}`;
  }

  // ---- desktop side column ----------------------------------------------
  _allPots(d) {
    return [...(d.pots || []), ...(d.reserves || [])];
  }

  _suggestions(d) {
    let dismissed = [];
    try { dismissed = JSON.parse(localStorage.getItem(DISMISS_KEY) || "[]"); } catch (_) { /* ignore */ }
    const used = new Set(this._allPots(d).flatMap((p) => p.category_keys || []));
    return Object.keys(window._fd.CAT_LABELS || {})
      .filter((k) => !SUGGEST_SKIP.has(k) && !used.has(k) && !dismissed.includes(k))
      .slice(0, 3);
  }

  _dhead(key, extra) {
    return `<div class="h"><span>${this._t(key)} <span class="dtag">${this._t("home.desk.marker")}</span></span>${extra || ""}</div>`;
  }

  _sideHtml(d) {
    let h = "";
    if (this._horizon === "cycle") h += `<div id="cdslot"></div>${this._optimise(d, false)}`;
    else if (this._horizon === "week") h += this._adjust(d);
    else if (this._horizon === "year") h += this._optimise(d, true);
    return h + this._history(d) + this._accounts(d) + this._manage(d);
  }

  /** Per spend pot: the last finished cycles as mini bars (spent vs. budget) + carry-over decision. */
  _history(d) {
    const pots = (d.pots || []).filter((p) => (p.cycle_budget || 0) > 0 && p.kind !== "reserve");
    if (!pots.length) return "";
    const rows = pots.map((p) => {
      const h = p.history || [];
      let chart = `<span class="muted hist-none">${this._t("home.hist.none")}</span>`;
      if (h.length) {
        const top = Math.max(1, ...h.map((c) => Math.max(c.spent || 0, c.budget || 0)));
        const w = 8, gap = 4, H = 28;
        const bars = h.map((c, i) => {
          const bh = Math.max(1, Math.round(H * Math.max(0, c.spent || 0) / top));
          const over = (c.spent || 0) > (c.budget || 0) + 0.005;
          return `<rect x="${i * (w + gap)}" y="${H - bh}" width="${w}" height="${bh}" rx="1.5" class="${over ? "hb over" : "hb"}"/>`;
        }).join("");
        const line = Math.round(H - H * (h[h.length - 1].budget || 0) / top);
        const label = this._t("home.hist.aria", {
          name: p.name,
          list: h.map((c) => this._t("home.hist.aria_item", { from: this._day(c.start), spent: this._m(c.spent, false), budget: this._m(c.budget, false) })).join("; "),
        });
        chart = `<svg class="hist" viewBox="0 0 ${h.length * (w + gap)} ${H}" role="img" aria-label="${this._e(label)}" preserveAspectRatio="xMinYMax meet"><line x1="0" x2="${h.length * (w + gap)}" y1="${line}" y2="${line}" class="hl"/>${bars}</svg>`;
      }
      return `<div class="hrow"><span class="hn"><b>${this._e(p.name)}</b></span>${chart}${this._carryAction(p)}</div>`;
    }).join("");
    return `<section class="card">${this._dhead("home.hist.title")}${rows}</section>`;
  }

  /** "Übertrag übernehmen / verwerfen" for the carry a pot brings into the current week. */
  _carryAction(p) {
    const c = p.carry_in_week || 0;
    if (Math.abs(c) < 0.5) return "";
    const amt = `${c > 0 ? "+" : "−"}${this._m(Math.abs(c), false)}`;
    const dec = p.carry_decision;
    if (dec) {
      const other = dec === "drop" ? "accept" : "drop";
      const txt = this._t(dec === "drop" ? "home.carry.dropped" : "home.carry.accepted", { amount: amt });
      return `<div class="hcarry"><span>${txt}</span>${this._isAdmin ? `<button class="btn sm ghost" data-act="carry" data-id="${this._e(p.id)}" data-do="${other}">${this._t(other === "drop" ? "home.carry.drop" : "home.carry.accept")}</button>` : ""}</div>`;
    }
    return `<div class="hcarry"><span>${this._t("home.carry.line", { amount: amt })}</span>${this._isAdmin ? `<span class="btns"><button class="btn sm dsk" data-act="carry" data-id="${this._e(p.id)}" data-do="accept">${this._t("home.carry.accept")}</button>
      <button class="btn sm dsk ghost" data-act="carry" data-id="${this._e(p.id)}" data-do="drop">${this._t("home.carry.drop")}</button></span>` : ""}</div>`;
  }

  async _doCarry(id, action) {
    try {
      await this._hass.callApi("POST", `${DOMAIN}/pots/carry`, { id, action });
      this._toast(this._t(action === "drop" ? "home.carry.toast_drop" : "home.carry.toast_accept"));
      this._load();
    } catch (e) {
      this._toast(this._t("home.pot.failed"));
    }
  }

  /** Optimierung: per spend pot plan, deviation from the Soll-Linie, a rule-based reading and next steps. */
  _optimise(d, light) {
    const pots = (d.pots || []).filter((p) => (p.cycle_budget || 0) > 0);
    const soll = this._soll(d);
    let body;
    if (!pots.length) {
      body = `<p class="muted" style="margin:0">${this._t("home.opt.no_pots")}</p>
        <div class="acts" style="justify-content:flex-start"><button class="btn sm dsk" data-act="addpot">+ ${this._t("home.pot.new")}</button>
        ${d.fixed_costs_covered === null || d.fixed_costs_covered === undefined ? this._planCta("btn sm dsk ghost") : ""}</div>`;
    } else {
      const ranked = pots.map((p) => {
        const linear = (p.cycle_budget || 0) * soll;
        const dev = (p.spent || 0) - linear;
        const proj = soll > 0 ? (p.spent || 0) / soll - p.cycle_budget : 0;
        return { p, dev, proj };
      }).sort((a, b) => b.dev - a.dev).slice(0, light ? 3 : 6);
      body = ranked.map(({ p, dev, proj }) => {
        const over = dev > 0.5;
        const cats = p.category_keys || [];
        const reading = over
          ? this._t("home.opt.over", { amount: this._m(dev, false), proj: this._m(Math.max(0, proj), false) })
          : this._t("home.opt.under", { amount: this._m(Math.abs(dev), false) });
        const acts = light ? "" : `<div class="acts">
          <button class="btn sm dsk ghost" data-act="editpot" data-id="${this._e(p.id)}">${this._t("home.opt.adjust")}</button>
          ${over ? `<button class="btn sm dsk ghost" data-act="nav" data-target="questions">${this._t("home.opt.rule")}</button>` : ""}
          ${cats.some((c) => CONTRACT_CATS.has(c)) ? `<button class="btn sm dsk ghost" data-act="nav" data-target="contracts">${this._t("home.opt.contract")}</button>` : ""}</div>`;
        return `<div class="opt ${this._cls(p.status)}"><div class="row"><span><b>${this._e(p.name)}</b></span><span class="amt">${this._m(p.spent, false)} / ${this._m(p.cycle_budget, false)}</span></div>
          <p><span class="chip">${over ? "+" : "−"}${this._m(Math.abs(dev), false)}</span> ${reading}</p>${acts}</div>`;
      }).join("");
    }
    const extra = light ? `<button class="btn sm ghost" data-act="nav" data-target="contracts">${this._t("home.year.contracts")}</button>` : "";
    return `<section class="card">${this._dhead(light ? "home.opt.title_year" : "home.opt.title", extra)}${body}</section>`;
  }

  /** Budget anpassen: move cycle budget from one spend pot to another (two PUT /pots). */
  _adjust(d) {
    const pots = (d.pots || []).filter((p) => p.kind !== "reserve");
    if (pots.length < 2) return `<section class="card">${this._dhead("home.adj.title")}<p class="muted" style="margin:0">${this._t("home.adj.need_two")}</p></section>`;
    const a = this._adj || {};
    const opt = (sel) => pots.map((p) => `<option value="${this._e(p.id)}" ${sel === p.id ? "selected" : ""}>${this._e(p.name)} · ${this._m(p.cycle_budget, false)}</option>`).join("");
    const from = a.from || pots[0].id, to = a.to || pots[1].id;
    return `<section class="card">${this._dhead("home.adj.title")}
      <p class="muted" style="margin:0 0 4px">${this._t("home.adj.say")}</p>
      <div class="grid2"><div><label class="lbl" for="adjFrom">${this._t("home.adj.from")}</label><select id="adjFrom" data-adj="from">${opt(from)}</select></div>
      <div><label class="lbl" for="adjTo">${this._t("home.adj.to")}</label><select id="adjTo" data-adj="to">${opt(to)}</select></div></div>
      <label class="lbl" for="adjAmt">${this._t("home.adj.amount")}</label><input id="adjAmt" type="number" inputmode="decimal" min="1" step="1" value="${this._e(String(a.amount || ""))}">
      <div class="err" role="alert">${this._e(a.error || "")}</div>
      <div class="acts"><button class="btn sm dsk" data-act="adjust">${this._t("home.adj.move")}</button></div></section>`;
  }

  async _doAdjust() {
    const sh = this.shadowRoot;
    const pots = (this._data && this._data.pots) || [];
    const from = pots.find((p) => p.id === sh.getElementById("adjFrom")?.value);
    const to = pots.find((p) => p.id === sh.getElementById("adjTo")?.value);
    const amt = parseFloat(String(sh.getElementById("adjAmt")?.value || "").replace(",", "."));
    this._adj = { from: from && from.id, to: to && to.id, amount: amt || "" };
    if (!from || !to || from.id === to.id || !(amt > 0) || amt > (from.cycle_budget || 0)) {
      this._adj.error = this._t("home.adj.invalid");
      this._paintSide();
      return;
    }
    const put = (p, budget) => this._hass.callApi("PUT", `${DOMAIN}/pots`, {
      id: p.id, name: p.name, owner: p.owner, kind: p.kind || "spend", category_keys: p.category_keys || [], cycle_budget: budget,
    });
    try {
      await put(from, Math.round(((from.cycle_budget || 0) - amt) * 100) / 100);
      await put(to, Math.round(((to.cycle_budget || 0) + amt) * 100) / 100);
      this._adj = null;
      this._toast(this._t("home.adj.done", { amount: this._m(amt, false) }));
      this._load();
    } catch (e) {
      this._adj.error = this._t("home.pot.failed");
      this._paintSide();
    }
  }

  /** Konten (desktop only): own accounts in detail; another person's accounts as a total only. */
  _accounts(d) {
    const head = this._dhead("home.acc.title");
    const a = this._acc;
    if (a === undefined || a === null) return `<section class="card">${head}<div class="muted">${this._t("home.loading")}</div></section>`;
    if (!a.accounts.length) return `<section class="card">${head}<div class="muted">${this._t("home.acc.empty")}</div></section>`;
    const sum = (list) => list.reduce((s, x) => { const v = x.booked ? parseFloat(x.booked.amount) : NaN; return isNaN(v) ? s : s + v; }, 0);
    const rows = (list) => list.map((x) => {
      const v = x.booked ? parseFloat(x.booked.amount) : NaN;
      return `<div class="row"><span>${this._e(x.account_name || "")}${x.iban_masked ? ` · ${this._e(x.iban_masked)}` : ""}</span><span class="amt">${isNaN(v) ? "–" : this._m(v, true)}</span></div>`;
    }).join("");
    const group = (color, label, list, detail, note) => `<div class="acc" style="--c:${color}"><div class="nm"><i></i><span>${this._e(label)}</span><em>${this._m(sum(list), true)}</em></div>
      ${detail ? rows(list) : `<div class="muted" style="padding-left:18px">${this._e(note || "")}</div>`}</div>`;
    if (!a.assign) {
      return `<section class="card">${head}${group("var(--fd-a500)", this._t("home.acc.all"), a.accounts, true)}</section>`;
    }
    const ownerOf = {};
    for (const x of a.assign.accounts || []) ownerOf[x.key] = x.owner || "";
    const mine = (o) => a.accounts.filter((x) => (ownerOf[x.account_key] || "") === o);
    const meKey = this._me ? String(this._me.id || this._me.name || "") : "";
    const persons = a.assign.persons || [];
    let html = "";
    persons.forEach((p, i) => {
      const list = mine(p.name);
      const isMe = p.name === meKey || p.name === (this._me && this._me.name);
      if (d.view === "person" && !isMe) return;
      if (!list.length && !isMe) return;
      const label = p.display_name || p.nickname || p.name;
      const n = list.length;
      html += group(PERSON_COLORS[i % PERSON_COLORS.length], label, list, isMe,
        this._t(n === 1 ? "home.acc.only_one" : "home.acc.only", { n, name: label }));
    });
    if (d.view === "household") {
      const shared = mine("shared");
      if (shared.length) html += group("var(--fd-household)", this._t("home.view.household"), shared, true);
      const open = mine("");
      if (open.length) html += group("var(--fd-t3)", this._t("home.acc.open"), open, true);
    }
    return `<section class="card">${head}${html || `<div class="muted">${this._t("home.acc.empty")}</div>`}</section>`;
  }

  _manage(d) {
    const pots = this._allPots(d);
    const sug = this._suggestions(d);
    const cats = window._fd.CAT_LABELS || {};
    return `<section class="card">${this._dhead("home.desk.manage")}
      ${pots.length ? pots.map((p) => this._confirmId === p.id ? `<div class="mg" role="alertdialog" aria-label="${this._e(this._t("home.pot.delete_confirm", { name: p.name }))}"><span>${this._e(this._t("home.pot.delete_confirm", { name: p.name }))}</span>
        <span class="btns"><button class="btn ghost sm" data-act="delno">${this._t("home.pot.cancel")}</button>
        <button class="btn danger sm" data-act="delyes" data-id="${this._e(p.id)}">${this._t("home.pot.delete")}</button></span></div>` : `<div class="mg"><span><b>${this._e(p.name)}</b><small class="muted">${this._m(p.cycle_budget, false)} · ${p.owner === "shared" ? this._t("home.pot.owner.shared") : this._e(p.owner)}</small></span>
        <span class="btns"><button class="btn ghost sm" data-act="editpot" data-id="${this._e(p.id)}">${this._t("home.pot.edit_btn")}</button>
        <button class="btn danger sm" data-act="delpot" data-id="${this._e(p.id)}">${this._t("home.pot.delete")}</button></span></div>`).join("")
        : `<div class="muted">${this._t("home.pots.none")}</div>`}
      <div class="acts"><button class="btn dsk" data-act="addpot">+ ${this._t("home.pot.new")}</button></div>
      <div class="h" style="margin-top:14px"><span>${this._t("home.desk.suggest")}</span></div>
      ${sug.length ? sug.map((k) => `<div class="sug"><div>${this._t("home.desk.suggest_text", { category: this._e(cats[k] || k) })}</div>
        <div class="acts" style="margin-top:6px"><button class="btn ghost sm" data-act="sugdismiss" data-k="${this._e(k)}">${this._t("home.desk.suggest_dismiss")}</button>
        <button class="btn sm dsk" data-act="sugcreate" data-k="${this._e(k)}">${this._t("home.desk.suggest_create")}</button></div></div>`).join("")
        : `<div class="muted">${this._t("home.desk.suggest_none")}</div>`}</section>`;
  }

  // ---- pot sheet --------------------------------------------------------
  _ownerKey() {
    return this._me ? String(this._me.name || this._me.id || "") : "";
  }

  _openSheet(pot, preset) {
    const d = this._data || {};
    const base = pot || { name: "", cycle_budget: "", kind: "spend", category_keys: [], owner: d.view === "household" || !this._me ? "shared" : this._ownerKey(), ...(preset || {}) };
    this._sheet = { id: pot ? pot.id : null, name: base.name, budget: base.cycle_budget, kind: base.kind || "spend", owner: base.owner, cats: [...(base.category_keys || [])], error: "" };
    this._returnFocus = this.shadowRoot.activeElement;
    this._paintSheet();
  }

  _closeSheet() {
    this._sheet = null;
    this.shadowRoot.getElementById("sheet").innerHTML = "";
    if (this._returnFocus && this._returnFocus.focus) this._returnFocus.focus();
  }

  _paintSheet() {
    const s = this._sheet;
    const host = this.shadowRoot.getElementById("sheet");
    if (!s) { host.innerHTML = ""; return; }
    const owners = [["shared", this._t("home.pot.owner.shared")]];
    if (this._me) owners.unshift([this._ownerKey(), this._shortName(this._me)]);
    const cats = Object.entries(window._fd.CAT_LABELS || {}).filter(([k]) => !SUGGEST_SKIP.has(k));
    host.innerHTML = `<div class="scrim" data-act="scrim"><form class="sheet" role="dialog" aria-modal="true" aria-label="${this._t(s.id ? "home.pot.edit" : "home.pot.new")}" data-form>
      <div class="h"><span>${this._t(s.id ? "home.pot.edit" : "home.pot.new")}</span></div>
      <label for="pn">${this._t("home.pot.name")}</label><input id="pn" type="text" maxlength="60" value="${this._e(s.name)}" autocomplete="off">
      <label for="pb">${this._t("home.pot.budget")}</label><input id="pb" type="number" inputmode="decimal" min="0" step="1" value="${this._e(String(s.budget))}">
      <div class="lbl">${this._t("home.pot.kind")}</div><div class="opts" role="radiogroup">${["spend", "reserve"].map((k) => `<button type="button" role="radio" data-kind="${k}" aria-checked="${s.kind === k}">${this._t("home.pot.kind." + k)}</button>`).join("")}</div>
      <div class="lbl">${this._t("home.pot.owner")}</div><div class="opts" role="radiogroup">${owners.map(([v, l]) => `<button type="button" role="radio" data-owner="${this._e(v)}" aria-checked="${s.owner === v}">${this._e(l)}</button>`).join("")}</div>
      <div class="lbl">${this._t("home.pot.categories")}</div><div class="opts">${cats.map(([k, l]) => `<button type="button" data-cat="${k}" aria-pressed="${s.cats.includes(k)}">${this._e(l)}</button>`).join("")}</div>
      <div class="err" id="sheeterr" role="alert">${this._e(s.error)}</div>
      <div class="acts"><button type="button" class="btn ghost" data-act="cancel">${this._t("home.pot.cancel")}</button><button type="submit" class="btn">${this._t("home.pot.save")}</button></div></form></div>`;
    const form = host.querySelector("[data-form]");
    form.addEventListener("submit", (e) => { e.preventDefault(); this._savePot(); });
    form.addEventListener("input", () => {
      s.name = host.querySelector("#pn").value;
      s.budget = host.querySelector("#pb").value;
    });
    host.querySelector("#pn")?.focus();
  }

  async _savePot() {
    const s = this._sheet;
    const budget = parseFloat(String(s.budget).replace(",", "."));
    if (!s.name.trim() || !(budget >= 0) || String(s.budget) === "") {
      s.error = this._t("home.pot.invalid");
      this.shadowRoot.getElementById("sheeterr").textContent = s.error;
      return;
    }
    const body = { name: s.name.trim(), owner: s.owner, cycle_budget: budget, category_keys: s.cats, kind: s.kind };
    if (s.id) body.id = s.id;
    try {
      await this._hass.callApi(s.id ? "PUT" : "POST", `${DOMAIN}/pots`, body);
      this._closeSheet();
      this._toast(this._t("home.pot.saved"));
      this._load();
    } catch (e) {
      s.error = this._t("home.pot.failed");
      this.shadowRoot.getElementById("sheeterr").textContent = s.error;
    }
  }

  async _deletePot(id) {
    const p = this._allPots(this._data || {}).find((x) => x.id === id);
    this._confirmId = null;
    if (!p) return;
    try {
      await this._hass.callApi("DELETE", `${DOMAIN}/pots?id=${encodeURIComponent(id)}`);
      this._load();
    } catch (e) {
      this._toast(this._t("home.pot.failed"));
    }
  }

  // ---- events -----------------------------------------------------------
  _onChange(e) {
    const t = e.target;
    if (t && t.dataset && t.dataset.adj) {
      this._adj = { ...(this._adj || {}), [t.dataset.adj]: t.value, error: "" };
    }
  }

  _onClick(e) {
    const t = e.target.closest("[data-h],[data-v],[data-act],[data-kind],[data-owner],[data-cat]");
    if (!t) return;
    const s = this._sheet;
    if (t.dataset.kind && s) { s.kind = t.dataset.kind; this._paintSheet(); return; }
    if (t.dataset.owner !== undefined && s) { s.owner = t.dataset.owner; this._paintSheet(); return; }
    if (t.dataset.cat && s) {
      s.cats = s.cats.includes(t.dataset.cat) ? s.cats.filter((c) => c !== t.dataset.cat) : [...s.cats, t.dataset.cat];
      this._paintSheet();
      return;
    }
    if (t.dataset.h) { this._setHorizon(t.dataset.h); return; }
    if (t.dataset.v) { this._setView(t.dataset.v); return; }
    const pot = (id) => this._allPots(this._data || {}).find((p) => p.id === id);
    switch (t.dataset.act) {
      case "alerts": this._alertsOpen = !this._alertsOpen; this._paint(); break;
      case "fresh": this._nav("freshness"); break;
      case "settings": this._nav("settings", t.dataset.section ? { section: t.dataset.section } : {}); break;
      case "nav": this._nav(t.dataset.target); break;
      case "ask": this._nav("questions"); break;
      case "renew":
      case "connect": window._fd.navigate(window._fd.INTEGRATION_PATH, e); break;
      case "retry": this._load(); break;
      case "demo": this.dispatchEvent(new CustomEvent("fd-demo-toggle", { bubbles: true, composed: true })); break;
      case "flip": this._flipped = !this._flipped; this._paint(); break;
      case "more": this._moreNext = !this._moreNext; this._paint(); break;
      case "addpot": this._openSheet(null); break;
      case "wizard": this._nav("setup"); break;
      case "setupopen": this._openSetup(); break;
      case "planwizard": this.dispatchEvent(new CustomEvent("fd-open-plan-wizard", { bubbles: true, composed: true })); break;
      case "editpot": this._openSheet(pot(t.dataset.id)); break;
      case "delpot": this._confirmId = t.dataset.id; this._paintSide(); break;
      case "delyes": this._deletePot(t.dataset.id); break;
      case "delno": this._confirmId = null; this._paintSide(); break;
      case "adjust": this._doAdjust(); break;
      case "carry": this._doCarry(t.dataset.id, t.dataset.do); break;
      case "cancel": this._closeSheet(); break;
      case "scrim": if (e.target === t) this._closeSheet(); break;
      case "sugcreate": {
        const k = t.dataset.k;
        this._openSheet(null, { name: (window._fd.CAT_LABELS || {})[k] || k, category_keys: [k] });
        break;
      }
      case "sugdismiss": {
        let list = [];
        try { list = JSON.parse(localStorage.getItem(DISMISS_KEY) || "[]"); } catch (_) { /* ignore */ }
        list.push(t.dataset.k);
        try { localStorage.setItem(DISMISS_KEY, JSON.stringify(list)); } catch (_) { /* ignore */ }
        this._paint();
        break;
      }
      default: break;
    }
  }
}

window._fd.defineOnce("fd-home", FdHome);
