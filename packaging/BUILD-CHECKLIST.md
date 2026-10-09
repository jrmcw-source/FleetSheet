# FleetSheet Windows Build Checklist

Do these on your Windows laptop, in order. Each step says what to check.

## 1. Install tools
- [ ] Install **Inno Setup 6.x** (with ISPP — it's included in the standard installer)
- [ ] Download **Python embeddable zip** (64-bit, matching the version in `app/packages/` — check the wheel filenames) from python.org → extract to `packaging\stage\`

## 2. Assemble `packaging\stage\`
From the repo (`repo-staging/`), build this layout next to `FleetSheet.iss`:

```
packaging\
  FleetSheet.iss
  VERSION                  <- copy from app/VERSION
  stage\
    pythonw.exe            <- from the embeddable Python zip (plus its DLLs, Lib\, etc.)
    app\
      app.py               <- all .py files from repo root
      ...                  <- everything else (fonts\, packages\, etc.)
      .eula_required       <- empty file; create it: `type nul > app\.eula_required`
    FleetSheet-Launcher.py <- from packaging\
    FleetSheet-Start.bat   <- from packaging\
    EULA.txt               <- from repo root
    README.txt             <- convert from README.md (plain text is fine)
```

- [ ] `VERSION` copied next to the .iss
- [ ] `app\.eula_required` exists (empty file — enables the EULA gate on first run)
- [ ] **No** `fleetsheet.db`, `*.db-wal`, `*.db-shm`, or `fleetsheet-launch.log` anywhere in `stage\` (a shipped stub DB breaks clean installs)
- [ ] `app\packages\` wheels present (offline deps: pillow, reportlab, etc.)

## 3. Set the repo URL
- [ ] In `FleetSheet.iss`, replace `https://github.com/` (3 spots: AppPublisherURL, AppSupportURL, AppUpdatesURL) with your actual repo URL

## 4. Compile (unsigned test build first)
```
cd packaging
iscc FleetSheet.iss
```
- [ ] Output: `packaging\output\FleetSheet-Setup-<VERSION>.exe`
- [ ] Install it on your laptop (per-user, no UAC prompt should appear)
- [ ] Launch from the Start Menu shortcut — Chrome app window opens, EULA shows on first run, setup wizard completes
- [ ] Uninstall from Add/Remove Programs — clean removal, no leftovers

## 5. Signing (after the Certum token arrives)
See `packaging/SIGNING.md`. Short version:
```
iscc /S"certsign=signtool sign /fd SHA256 /sha1 <THUMBPRINT> /tr http://timestamp.digicert.com /td SHA256 $p" FleetSheet.iss
```
- [ ] Verify: `signtool verify /pa /v FleetSheet-Setup-<VERSION>.exe`
- [ ] The signed uninstaller is automatic (`SignedUninstaller=yes` is already in the .iss)

## 6. Ship it
- [ ] Upload the signed `.exe` to a GitHub Release on your repo
- [ ] Users download, run, no warnings (after SmartScreen reputation builds — first downloads may still show "unrecognized app"; this fades with download volume, nothing to do about it)

## Before v1.0 ships (do not skip)
- [ ] Generate the WinSparkle Ed25519 keypair (`packaging/WINSPARKLE.md`) — the **public** key must be baked into the app before the first release. No retrofit: an updater can't update itself into existence.
