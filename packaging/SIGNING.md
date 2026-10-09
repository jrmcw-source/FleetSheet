# Windows Code Signing — Cheapest Legal Path

**Goal:** sign `FleetSheet-Setup-<VERSION>.exe` (and the Inno uninstaller)
so non-technical users don't hit SmartScreen / Smart App Control walls.
**Windows-only.** No Mac content in this workstream.

**Status: not yet purchased.** Do this before the first public listing.

---

## 1. What to buy (cheapest first)

| Option | Cost | Notes |
|---|---|---|
| **Certum Open-Source Code Signing (OV)** | **~$25–70/yr** | **Cheapest legal route — but ONLY if FleetSheet is open-source** (public repo, OSI-approved license such as MIT). Apply through Certum's open-source program. Identity validation required. Ships on a cryptographic card/token — allow 1–3 weeks for the token to arrive by mail. |
| Sectigo / DigiCert OV via reseller | ~$100–300/yr | Standard commercial OV cert. No open-source requirement. Reputation builds the same way. |
| Microsoft Artifact Signing | ~$9.99/mo (~$120/yr) | Microsoft's recommended non-Store path. Cloud-based signing, **no USB token**, CI-friendly. Confirm individual/sole-proprietor eligibility at signup. |

**Pick:** Certum open-source if the repo is public + MIT (it is, per the plan).
Otherwise the Sectigo-reseller OV is the next cheapest.

### ⚠️ DO NOT buy an EV certificate for SmartScreen

**EV ($200–500/yr) no longer grants SmartScreen bypass.** Microsoft removed
the instant-reputation behavior in 2024. Since then, OV and EV are treated
identically: both show "unrecognized until reputation accumulates." An EV
cert for SmartScreen purposes is $200–500/yr set on fire.

Reputation reality (both OV and EV):
- Every NEW file hash starts at zero reputation — **each release re-triggers
  the warning until reputation rebuilds** (weeks + hundreds of installs).
- Unsigned is strictly worse: warning on every build, forever, and
  Windows 11 Smart App Control can block unsigned executables outright.
- Signing is necessary but not sufficient. Ship it anyway — it's the floor.

---

## 2. How to apply (Certum open-source program)

1. Publish the repo publicly with an OSI-approved license (MIT).
2. Apply at Certum's site under their open-source / community program.
   You'll need: proof of the public repo, personal identity documents
   (individual) — the certificate is issued to a **legal name** for
   individual enrollment.
3. Complete their identity validation (email + document checks).
4. Receive the cryptographic token by mail. Install Certum's middleware
   so Windows sees the certificate.
5. Export the certificate **thumbprint** (see step 4) — you'll need it for
   every signing command.

Keep the token physically safe. If it's lost/stolen, revoke through Certum
immediately — a compromised signing cert is worse than none.

---

## 3. How to sign the installer (after Inno builds it)

You need `signtool.exe` — ships with the **Windows SDK**
(`C:\Program Files (x86)\Windows Kits\10\bin\<ver>\x64\signtool.exe`).
Install the SDK once on the build machine.

```bat
:: 1. Find your certificate thumbprint (40 hex chars, no spaces):
certutil -store My | findstr /C:"Cert Hash"

:: 2. Sign the installer (SHA-256 only — SHA-1 dual-signing is obsolete):
signtool sign /fd SHA256 /sha1 <THUMBPRINT-NOHYPHENS> ^
  /tr http://timestamp.digicert.com /td SHA256 ^
  "output\FleetSheet-Setup-2026-10-08u.exe"

:: 3. Sign EVERYTHING you ship that executes: the uninstaller is handled
::    by Inno (SignedUninstaller=yes + /S flag, see FleetSheet.iss header),
::    but also sign FleetSheet-Start.bat? No — .bat files can't be signed.
::    Sign: the setup exe, the uninstaller (via Inno), pythonw.exe is
::    already signed by the PSF — leave vendor binaries alone.
```

**Timestamp servers** (RFC 3161 — the timestamp is what keeps the signature
valid after the cert expires; NEVER skip `/tr`):
- `http://timestamp.digicert.com` (primary)
- `http://timestamp.sectigo.com` (fallback)

**Inno integration** (signs at compile time, including the uninstaller):
```bat
iscc /S"certsign=signtool sign /fd SHA256 /sha1 <THUMBPRINT> /tr http://timestamp.digicert.com /td SHA256 $p" FleetSheet.iss
```
The `;SignTool=certsign $p` line in FleetSheet.iss is commented out until
you have a thumbprint — uncomment it when you do. (`$p` = file to sign,
`$f` also works; `$q...$q` quotes.)

---

## 4. How to verify the signature

```bat
:: Full verification (chain, timestamp, file hash):
signtool verify /pa /v "output\FleetSheet-Setup-2026-10-08u.exe"
```
Expected: `Successfully verified` + `Signing Certificate Chain` ending in
a trusted root + `Timestamp` present.

Manual check: right-click the exe → Properties → **Digital Signatures** tab
→ select the signature → Details → "This digital signature is OK" and the
timestamp counter-signature is listed.

Also verify on a **clean Windows 10/11 VM** (or a friend's PC) that has
never seen the file: download it fresh and confirm what the user sees.
Expect the SmartScreen "unrecognized app" interstitial on early releases —
that is the reputation system working as designed, not a signing failure.

---

## 5. Release checklist (signing portion)

- [ ] Certum open-source cert issued, token in hand, thumbprint recorded
- [ ] `signtool.exe` installed on the build machine (Windows SDK)
- [ ] `;SignTool=` line in FleetSheet.iss uncommented
- [ ] Inno compiled with `/S` flag → installer AND uninstaller signed
- [ ] `signtool verify /pa /v` passes on the output exe
- [ ] Timestamp present (check with `/v`)
- [ ] Clean-VM download test: note exactly what SmartScreen shows
- [ ] Thumbprint + token stored safely (NOT in the repo)

## 6. Costs, blunt summary

| Item | Cost |
|---|---|
| Certum open-source OV (Windows) | ~$25–70/yr |
| Apple Developer (Mac — separate workstream) | $99/yr |
| Windows SDK / signtool | $0 |
| **EV certificate** | **$0 — do not buy** |

Minimum viable trust spend for Windows: **~$25–70/yr**. Everything else
in the packaging workstream is developer time.
