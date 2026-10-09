# FleetSheet

**Track your equipment to the bank.** A one-desk equipment rental tracker with compliance checks and invoicing/accounts receivable — built for the small construction-adjacent shop where one person does it all.

FleetSheet is free to download and use. It is not open source: the source is public to read, but redistribution is prohibited — see [LICENSE](LICENSE). It is provided as-is with no support — see [EULA.md](EULA.md).

**Author and maintainer:** Jason McWhirter — created, owned, and maintained by Jason McWhirter ([@jrmcw-source](https://github.com/jrmcw-source)), the developer behind this repository and its releases.

---

## What it does

Small equipment rental businesses live in spreadsheets, whiteboards, and memory. FleetSheet replaces that with one dense, fast desktop application:

- **Equipment & rentals** — units, rental tickets, reservations, check in/out with condition capture, soft-reservation conflict handling
- **Invoicing & A/R** — invoice lines that mirror the customer's PO exactly (free-text labels and units, because real POs relabel things), payments, credit memos, petty cash, AR aging
- **Compliance tracking** — every certification, calibration, and inspection with an expiration date, in one place; per-unit "who does this" vendor/crew assignments; due/overdue alerts with the phone number to call
- **Quotes, change orders & work orders** — the full rental-desk workflow, not just the happy path
- **Yard devices** — QR-code pairing authorizes phones/tablets/scanners on the shop Wi-Fi for limited check-in/out, with expiration and instant revocation
- **Reports & BI export** — prebuilt weekly reports plus CSV/Excel/JSON exports shaped for Power BI and Tableau

## Tech stack

- **Python 3, standard library only for the core** — `http.server` + `sqlite3`, zero required dependencies. Deliberate: the app must install and run on a shop PC with no internet and no toolchain.
- **SQLite** — single-file database; the simplest backup story in the industry
- **Server-rendered HTML** — no frontend framework, no build step, no npm. Dense, keyboard-friendly business UI
- **Offline-first** — no cloud, no accounts, no telemetry. Your data stays in your shop
- **Optional:** `reportlab` (PDF packs), `segno` (QR codes), `pypdf` — vendored as wheels for offline install

## Screenshots

> Screenshots coming with the first packaged release. The UI follows a compact design standard: dense professional business software (think Dynamics/Great Plains), every page fitting one screen where possible, zero wasted space.

## Installation (Windows)

1. Download `FleetSheet-Setup-1.0.exe` from [Releases](../../releases)
2. Run the installer — it installs per-user (into your AppData folder), no admin rights needed
3. Launch FleetSheet from the Start Menu — the server starts and opens a clean browser window
4. First run walks you through setup: company → customers → job sites → vendors → security PIN → billing → backups → devices

Your data lives in a single SQLite file on your machine. Automatic daily backups are on by default — check the System Health page to confirm.

> **Mac:** not currently packaged. The code is cross-platform Python; a Mac package may follow.

## Development setup

```bash
git clone https://github.com/jrmcw-source/FleetSheet.git
cd FleetSheet
python3 -m venv venv
source venv/bin/activate   # or venv\Scripts\activate on Windows
# Core has zero dependencies. Optional extras:
pip install reportlab segno pypdf
python3 app.py             # serves on http://127.0.0.1:8765
```

The test suite lives alongside the app: `test_ux.py`, `test_business_rules.py`, `test_compliance.py`, `test_schema.py`, `test_tabecho.py`.

## Project status

- **Free to use, no redistribution** under the FleetSheet License — see [LICENSE](LICENSE)
- **No support is offered.** This is a side project by a solo developer. The [EULA](EULA.md) is AS-IS / NO SUPPORT / NO LIABILITY / USE AT YOUR OWN RISK. The app includes a self-diagnostics System Health page; beyond that, you're on your own (politely).
- **No warranty, no professional advice.** FleetSheet is a record-keeping tool. It does not provide tax, legal, or financial advice, and it never infers tax — every rate and jurisdiction is your explicit decision.

## Contributing

Bug reports and pull requests are welcome. This is a nights-and-weekends project, so response times are "eventually." The most useful contributions: bug fixes with a failing test, and documentation improvements.

Please don't open issues asking for support using the software — see "no support" above.

## Why it exists

Built by someone who spent 17 years at the rental desk — as an asset manager, field engineer, and the person who had to make the invoice match the PO or not get paid. The conviction: if software gets messy real-world invoicing right, everything else follows.

---

