# Finance Dashboard for Home Assistant

**Your personal finance command center — right inside Home Assistant.**

> [!WARNING]
> **Alpha — not recommended for use.** Finance is under active redesign. Features, data model and storage format may change without migration, and things may break. Do not rely on it for your real finances yet.

[![Version](https://img.shields.io/github/v/release/JerryT2T/homeassistant-finance?style=flat-square)](https://github.com/JerryT2T/homeassistant-finance/releases)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![HACS](https://img.shields.io/badge/HACS-compatible-orange?style=flat-square)](https://hacs.xyz)
[![CI](https://img.shields.io/github/actions/workflow/status/JerryT2T/homeassistant-finance/validate.yml?style=flat-square&label=CI)](https://github.com/JerryT2T/homeassistant-finance/actions)
[![HA](https://img.shields.io/badge/Home%20Assistant-2026.3+-41BDF5?style=flat-square&logo=homeassistant&logoColor=white)](https://www.home-assistant.io)

<!-- TODO: Add screenshot of the Finance Dashboard sidebar panel -->

## Table of Contents

- [What is this?](#-what-is-this)
- [Features](#-features)
- [Getting Started](#-getting-started)
- [How to Use](#-how-to-use)
- [Architecture](#-architecture)
- [Security](#-security)
- [Contributing](#-contributing)
- [License](#-license)

## 💡 What is this?

Finance Dashboard connects your bank accounts to Home Assistant via [Enable Banking](https://enablebanking.com) (PSD2 Open Banking), giving you a real-time overview of balances, transactions, and household budgets. Track spending across multiple people, auto-categorize transactions, and see where your money goes — all from your HA dashboard, with banking-grade security.

## ✨ Features

- 🏦 **Live Banking Data** — Connect European banks via the Enable Banking PSD2 API (free restricted mode for your own accounts)
- 📊 **Auto-Categorization** — Transactions are automatically classified (housing, food, transport, subscriptions, etc.)
- 👥 **Multi-Person Households** — Configurable budget split models for any number of household members
- 🔒 **Banking-Grade Security** — Fernet encryption, token rotation, session timeouts, full audit trail
- 📱 **Sidebar Panel** — Dedicated finance overview accessible from the HA sidebar
- 🎴 **Lovelace Card** — Compact balance widget for any dashboard
- 🔄 **HACS Distribution** — Install and update through HACS
- 🌍 **Multilingual** — English and German translations included
- 🤖 **HA Automations** — Expose services for balance checks, transaction refresh, and monthly summaries

## 🚀 Getting Started

### Prerequisites

- Home Assistant 2026.3 or newer
- [HACS](https://hacs.xyz) installed
- A free [Enable Banking](https://enablebanking.com) application in restricted mode (links only your own accounts, non-commercial use)
- A bank supported by Enable Banking (e.g. DKB)

### Installation via HACS

HACS is the only supported install path. The integration is not yet in the HACS default list, so add it as a custom repository first.

1. Open HACS in Home Assistant
2. Open the three-dot menu → **Custom repositories**
3. Add `https://github.com/JerryT2T/homeassistant-finance` with category **Integration**
4. Search for **Finance** in HACS and download it
5. Restart Home Assistant
6. Go to **Settings → Devices & services → Add integration** and select **Finance**

Updates are offered by HACS whenever a new GitHub Release is published.

> **Upgrading from the old companion add-on?** This repository no longer ships an add-on (app). If it is still listed under **Settings → Apps → App store → ⋮ → Repositories** (shown as `unknown`), remove it there.

### Manual Installation

1. Copy `custom_components/finance_dashboard/` to your HA `config/custom_components/` directory
2. Restart Home Assistant

The sidebar panel and the Lovelace cards ship inside the integration and load automatically — no Lovelace resource needs to be added.

## 📖 How to Use

### 1. Create an Enable Banking application

1. Sign up at the [Enable Banking control panel](https://enablebanking.com/cp/applications)
2. Create a production application in restricted mode and download its RSA private key
3. Register the redirect URL `https://my.home-assistant.io/redirect/oauth`

### 2. Configure the Integration

1. Go to **Settings** → **Devices & Services** → **Add Integration** and select **Finance**
2. Enter the application ID and paste the private key
3. On the integration page choose **Add bank**, pick country and bank, and approve access in your banking app
4. Repeat step 3 for every bank. When a bank's consent nears expiry, a repair notice links to **Reconfigure** for that bank

### 3. View Your Finances

- **Sidebar**: Click the Finance Dashboard icon in the HA sidebar for the full overview
- **Lovelace Card**: Add a `custom:finance-dashboard-card` to any dashboard

```yaml
type: custom:finance-dashboard-card
show_transactions: true
max_transactions: 5
```

#### Keeping the data current

Banks cap PSD2 account access at four fetches per 24h — but only for requests
made while you are *not* in session. Anything you trigger yourself (the
"Neu importieren" button) carries PSU headers, counts as attended, and is not
capped. Opening the dashboard or pressing "Aktualisieren" never calls the bank;
they only read or re-process stored data.

The scheduled daily refresh (`daily_refresh_hour`, default 06:30) runs without
a user session and does spend one of the four background fetches — as does a
`refresh_transactions` service call from an automation.

### 4. Use in Automations

```yaml
# Refresh transactions daily
automation:
  - alias: "Daily Finance Refresh"
    trigger:
      - platform: time
        at: "08:00:00"
    action:
      - service: finance_dashboard.refresh_transactions
```

## 🏗 Architecture

```
┌─────────────────────────────────────────────────┐
│                 Home Assistant                   │
│                                                  │
│  ┌──────────────┐  ┌─────────────────────────┐  │
│  │  Sidebar      │  │  Lovelace Card          │  │
│  │  Panel (JS)   │  │  (JS Web Component)     │  │
│  └──────┬───────┘  └──────────┬──────────────┘  │
│         │     HTTP API         │                 │
│  ┌──────┴──────────────────────┴──────────────┐  │
│  │         Finance Dashboard Integration       │  │
│  │  ┌──────────┐ ┌────────────┐ ┌──────────┐  │  │
│  │  │ Manager  │ │ Categorizer│ │ Cred Mgr │  │  │
│  │  └────┬─────┘ └────────────┘ └──┬───────┘  │  │
│  │       │                          │          │  │
│  │  ┌────┴──────────────────────────┴───────┐  │  │
│  │  │     Enable Banking API Client         │  │  │
│  │  └────────────────┬──────────────────────┘  │  │
│  └───────────────────┼─────────────────────────┘  │
│                      │                            │
└──────────────────────┼─────────────────────────┘
                       │ HTTPS
              ┌────────┴────────┐
              │ Enable Banking  │
              │  (Open Banking)  │
              └────────┬────────┘
                       │ PSD2
              ┌────────┴────────┐
              │   Your Bank      │
              └─────────────────┘
```

## 🔒 Security

Finance Dashboard follows banking-grade security practices:

| Layer | Protection |
|-------|-----------|
| **Credential Storage** | Fernet symmetric encryption (AES-128-CBC + HMAC) in HA `.storage/` |
| **Token Management** | Auto-rotation before expiry, forced re-auth after 90 days |
| **Session Security** | 30-minute inactivity timeout |
| **Data Display** | IBANs masked to last 4 digits in all API responses |
| **Audit Trail** | Every credential operation logged (event type + timestamp only) |
| **API Security** | All endpoints require HA Bearer token authentication |
| **Git Safety** | `.gitignore` blocks all runtime data, credentials, and tokens |
| **Bank Data at Rest** | Raw bank responses and the transaction ledger are Fernet-encrypted in `.storage/` |
| **Network** | HTTPS-only communication with Enable Banking; no telemetry |

**No financial data is ever stored in git, logs, or configuration files.**

## 🤝 Contributing

Contributions are welcome! Please note the strict security requirements — any PR that could leak financial data will be rejected.

1. Fork the repository
2. Create a feature branch (`feat/42-your-feature`)
3. Run validation: `python scripts/bump_versions.py --check`
4. Submit a Pull Request

## 📄 License

[MIT](LICENSE) — Copyright (c) 2026 Jerry0022
