# Windows Code Signing — Current Status and Future Path

**DECISION (Jason McWhirter, 2026-10-09): FleetSheet v1.0 ships UNSIGNED.**
No code-signing certificate has been purchased, and none will be for v1.0.
This file records why, and what the path looks like if signing ever returns.

**Windows-only.** No Mac content in this workstream.

---

## 1. Why v1.0 is unsigned

- **The Certum open-source route is closed.** It required FleetSheet to be
  open source under an OSI-approved license (e.g. MIT). FleetSheet is **not**
  open source: it is source-available under the custom FleetSheet License
  (free to download and use; redistribution, sublicensing, and resale
  prohibited — see `LICENSE`). The license changed on 2026-10-08; any older
  note in this repo describing FleetSheet as MIT-licensed is stale.
- **The strategy caps spend at ~$0.** FleetSheet is released free under a
  maximal AS-IS / no-support EULA. A commercial certificate (~$100–300/yr)
  buys less SmartScreen friction, not a different outcome, at this scale.
- **Accepted cost:** SmartScreen will show an "unrecognized app" warning for
  the unsigned installer, and Windows 11 Smart App Control can block
  unsigned executables outright on machines where it is enabled. That is a
  known, accepted trade-off for v1.0, not an oversight.

**Do not buy an EV certificate for SmartScreen purposes, ever.** Microsoft
removed EV's instant-reputation behavior in 2024; OV and EV are treated
identically ("unrecognized until reputation accumulates"). An EV cert bought
for SmartScreen is $200–500/yr set on fire.

Reputation reality (for any future signed release): every new file hash
starts at zero reputation, so each release re-triggers the warning until
reputation rebuilds (weeks + hundreds of installs). Signing removes
"Unknown publisher"; it does not remove the warning on day one.

---

## 2. Update signing is separate — and it IS active

Do not confuse code signing (Authenticode, this document) with the
**WinSparkle update channel**, which is signed with an Ed25519 keypair:

- The **public key** is baked into the shipped build.
- The **private key** (`eddsa_priv.pem`) lives only on the maintainer's
  machine at `%LOCALAPPDATA%\FleetSheet\UpdateSigning\`, with a secure
  backup. **Never** commit it to this repo, and never send it through chat
  or email.
- Every `appcast.xml` release entry must carry the EdDSA signature produced
  with that private key (WinSparkle's `generate_appcast` / sign-update
  tooling), or installed copies will refuse the update.

Losing that private key means losing the ability to update existing
installs. Guard it accordingly.

---

## 3. If signing returns (paid v2.0 / real traction)

Trigger: download volume or a paid tier that justifies the spend. Path:

1. Buy a **standard commercial OV certificate** issued to **Jason
   McWhirter** personally — Sectigo/DigiCert via a reseller (~$100–300/yr)
   or Microsoft Artifact Signing (~$9.99/mo, cloud-based, no USB token;
   confirm individual eligibility at signup). **Not** an open-source
   program certificate: the FleetSheet License does not qualify, and
   open-source program certs are revoked if used to sign commercially
   distributed software.
2. Install the **Windows SDK** on the build machine for `signtool.exe`
   (`C:\Program Files (x86)\Windows Kits\10\bin\<ver>\x64\signtool.exe`).
3. Record the certificate **thumbprint** (40 hex chars, no spaces):
   `certutil -store My | findstr /C:"Cert Hash"` — store it safely,
   **not** in this repo.
4. Sign at Inno compile time (this also signs the uninstaller, which is
   what `SignedUninstaller=yes` in `FleetSheet.iss` is for):

   ```bat
   iscc /S"certsign=signtool sign /fd SHA256 /sha1 <THUMBPRINT> /tr http://timestamp.digicert.com /td SHA256 $p" FleetSheet.iss
   ```

   Fallback timestamp server: `http://timestamp.sectigo.com`. **Never skip
   the `/tr` timestamp** — it is what keeps the signature valid after the
   certificate expires.
5. To sign an already-built installer by hand:

   ```bat
   signtool sign /fd SHA256 /sha1 <THUMBPRINT-NOHYPHENS> /tr http://timestamp.digicert.com /td SHA256 "FleetSheet-Setup-1.0.exe"
   ```

6. Verify before publishing:

   ```bat
   signtool verify /pa /v "FleetSheet-Setup-1.0.exe"
   ```

   Expected: `Successfully verified`, a certificate chain ending in a
   trusted root, and a timestamp present. Cross-check via right-click →
   Properties → **Digital Signatures**. Then test a fresh download on a
   clean Windows machine and note exactly what SmartScreen shows.

Signed-release checklist:

- [ ] Commercial OV cert issued to Jason McWhirter; thumbprint recorded (outside the repo)
- [ ] `signtool.exe` available on the build machine
- [ ] Inno compiled with the `/S"certsign=..."` define → installer AND uninstaller signed
- [ ] `signtool verify /pa /v` passes; timestamp present
- [ ] Clean-machine download test: SmartScreen behavior noted
- [ ] Appcast entry signed with the WinSparkle Ed25519 key (section 2 — required either way)
