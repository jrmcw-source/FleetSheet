# WinSparkle 0.8 Integration Plan — FleetSheet (Windows)

**Status: code implemented 2026-10-08** — app/updater_winsparkle.py + app.py startup/shutdown hooks + Setup → Admin "Check for updates" button. Still pending before v1.0: bake the real Ed25519 public key into updater_winsparkle.py and ship WinSparkle.dll in stage\app\. Code below is the original plan, kept as the reference. Implements Step 1's
"self-correcting" requirement: the installed app updates itself without
the user downloading anything manually.

**Cost: $0** beyond the code-signing certificate (already required).
No update server needed — the appcast is a static file on HTTPS.

**Windows-only.** (macOS would use Sparkle 2 — separate workstream, out of
scope here.)

---

## 1. How WinSparkle works (30-second version)

WinSparkle is a small C++ DLL (`WinSparkle.dll`, x64, MIT license) you ship
next to the app. At startup the app tells it:

- where the **appcast** lives (a static XML file over HTTPS),
- the app's name/company/version,
- an **Ed25519 public key** (the trust root).

On a schedule (or from a menu item), WinSparkle downloads the appcast,
compares versions, and if a newer release exists it shows its own
"update available" dialog, downloads the new **installer**, verifies the
**Ed25519 signature** (not just HTTPS — the signature is the trust root,
so the file host doesn't matter), runs it, and asks the app to quit.

Because FleetSheet installs **per-user with no UAC** (Inno
`PrivilegesRequired=lowest`), the downloaded installer also runs without
elevation — updates never hit a permission prompt.

---

## 2. Files to add (all new, none modify existing app code)

| File | Purpose |
|---|---|
| `app/WinSparkle.dll` (x64) | The updater engine, shipped in the installer payload (`stage\app\`) |
| `app/updater_winsparkle.py` *(new)* | ctypes wrapper: loads the DLL, exposes init/check/shutdown |
| appcast signing script | Kept OFF the repo / on the build machine only (holds the private key) |

Get `WinSparkle.dll` + `winsparkle.h` from the WinSparkle 0.8.x release
(https://github.com/vslavik/winsparkle). Verify the download hash against
the release notes before shipping it.

---

## 3. Code changes needed (for the implementation pass)

### 3a. `app/updater_winsparkle.py` (new module, stdlib `ctypes` only)

```python
"""WinSparkle updater wrapper. Windows-only; every call is a no-op when
the DLL is absent (dev machines, Mac builds) so nothing else in the app
has to care."""
import ctypes, os, sys

_ed_pubkey_b64 = "..."  # Ed25519 PUBLIC key, base64 — safe to ship in source
_APPCAST_URL = "https://raw.githubusercontent.com/<ORG>/<REPO>/main/appcast.xml"
# (or any static HTTPS URL — GitHub Releases, GitHub Pages, plain web host)

_ws = None

def _load():
    global _ws
    if _ws is not None:
        return _ws
    if not sys.platform.startswith("win"):
        return None
    dll = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "WinSparkle.dll")
    if not os.path.isfile(dll):
        return None
    try:
        _ws = ctypes.CDLL(dll)
    except Exception:
        return None
    # NOTE: win_sparkle_set_app_details takes wchar_t* (wide strings).
    _ws.win_sparkle_set_app_details.argtypes = [ctypes.c_wchar_p,
                                                ctypes.c_wchar_p,
                                                ctypes.c_wchar_p]
    _ws.win_sparkle_set_appcast_url.argtypes = [ctypes.c_char_p]
    _ws.win_sparkle_set_ed25519_pub_key.argtypes = [ctypes.c_char_p]
    _ws.win_sparkle_set_ed25519_pub_key.restype = ctypes.c_int
    return _ws

def init(version):
    """Call once at app startup (after the server is up). Safe no-op
    when WinSparkle is unavailable."""
    ws = _load()
    if not ws:
        return False
    try:
        ws.win_sparkle_set_app_details("FleetSheet", "FleetSheet", version)
        ws.win_sparkle_set_appcast_url(_APPCAST_URL.encode("utf-8"))
        if ws.win_sparkle_set_ed25519_pub_key(_ed_pubkey_b64.encode("utf-8")) != 0:
            return False
        ws.win_sparkle_set_automatic_check_for_updates(1)
        ws.win_sparkle_set_update_check_interval(7 * 24 * 3600)  # weekly
        # Ask the server to shut down cleanly when the user accepts an update:
        # register win_sparkle_set_shut_down_request_callback -> set a flag
        # the main loop checks, stopping ThreadingHTTPServer gracefully.
        ws.win_sparkle_init()
        return True
    except Exception:
        return False

def check_now():
    """Menu item: 'Check for Updates'. Shows WinSparkle's own UI."""
    ws = _load()
    if ws:
        try:
            ws.win_sparkle_check_update_with_ui()
        except Exception:
            pass

def cleanup():
    ws = _load()
    if ws:
        try:
            ws.win_sparkle_cleanup()
        except Exception:
            pass
```

### 3b. Hook points in `app.py` (implementation pass)

1. **Startup:** after the server binds, call
   `updater_winsparkle.init(APP_VERSION)` inside try/except (never let the
   updater break startup).
2. **Menu:** add a "Check for Updates…" item (Setup or Help area) calling
   `updater_winsparkle.check_now()`.
3. **Shutdown callback:** register
   `win_sparkle_set_shut_down_request_callback` so accepting an update
   stops the HTTP server gracefully before the new installer runs.
   (ctypes `CFUNCTYPE(None)`; set a threading.Event the serve loop checks.)
4. **Version format:** keep versions lexicographically sortable
   (`2026-10-08u` style works — fixed-width date prefix).

### 3c. Inno changes

- Ship `app/WinSparkle.dll` in `stage\app\` (the `[Files]` wildcard already
  covers it — no .iss change needed).
- The downloaded update is the **signed installer exe itself**
  (`FleetSheet-Setup-<VERSION>.exe`); WinSparkle runs it with `/SILENT`
  by default — confirm Inno silent mode works with the per-user install
  (it does; test once).

---

## 4. appcast.xml template (static HTTPS)

Host at the URL in `_APPCAST_URL`. One `<item>` per release, newest first.
`length` = exact byte size of the installer. `sparkle:edSignature` =
base64 Ed25519 signature of the installer file bytes.

```xml
<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <title>FleetSheet Updates</title>
    <link>https://github.com/&lt;ORG&gt;/&lt;REPO&gt;/releases</link>
    <description>FleetSheet for Windows — update feed</description>
    <language>en</language>
    <item>
      <title>FleetSheet 2026-10-08u</title>
      <pubDate>Wed, 08 Oct 2026 12:00:00 +0000</pubDate>
      <sparkle:version>2026-10-08u</sparkle:version>
      <enclosure url="https://github.com/&lt;ORG&gt;/&lt;REPO&gt;/releases/download/v2026-10-08u/FleetSheet-Setup-2026-10-08u.exe"
                 type="application/octet-stream"
                 length="41943040"
                 sparkle:version="2026-10-08u"
                 sparkle:edSignature="BASE64_SIGNATURE_OF_INSTALLER_BYTES" />
    </item>
  </channel>
</rss>
```

---

## 5. Ed25519 key generation + release signing (build machine only)

Generate ONCE. The **private key never leaves the build machine and never
enters the repo.** The public key goes into `updater_winsparkle.py`.

```python
# gen_keys.py  (run once; needs: pip install cryptography)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import base64
priv = Ed25519PrivateKey.generate()
pub = priv.public_key()
open("winsparkle_priv.bin", "wb").write(
    priv.private_bytes_raw())                       # SECRET — offline only
print("PUBLIC (paste into updater_winsparkle.py):")
print(base64.b64encode(pub.public_bytes_raw()).decode())
```

```python
# sign_release.py output\FleetSheet-Setup-2026-10-08u.exe
# (run per release; needs the privkey file + pip install cryptography)
import sys, base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
data = open(sys.argv[1], "rb").read()
priv = Ed25519PrivateKey.from_private_bytes(open("winsparkle_priv.bin","rb").read())
sig = base64.b64encode(priv.sign(data)).decode()
print("length:", len(data))
print("sparkle:edSignature:", sig)
```

Release order per version: **build → sign with signtool (SIGNING.md) →
Ed25519-sign → publish exe to GitHub Releases → update appcast.xml →
commit appcast**.

**Critical:** the updater must ship **inside v1.0**. Versions released
before WinSparkle was integrated cannot self-update — their users do one
final manual download. There is no retrofit.

---

## 6. Test plan (before calling it done)

- [ ] Clean VM, install v1 → "Check for Updates" reports none (appcast has
      only v1).
- [ ] Publish v2 appcast + installer → v1 offers update, downloads,
      verifies signature, runs installer silently, restarts on new version.
- [ ] Tampered installer (flip one byte, re-sign appcast entry) →
      WinSparkle **refuses** (signature check is the test that matters).
- [ ] No network → startup unaffected, menu item fails silently/softly.
- [ ] `WinSparkle.dll` deleted → app starts and runs normally (no-op path).
- [ ] Update while server has yard devices connected → shutdown callback
      fires, server stops gracefully, installer proceeds.

## 7. What this does NOT do

- No delta patches (full installer download each time — fine at ~40MB).
- No staged rollouts / channels (one feed; add later if ever needed).
- No Mac (Sparkle 2 is the Mac equivalent — separate workstream).
- No telemetry back to you — WinSparkle phones nothing home. Update
  *checks* hit your static file host; that's it.
