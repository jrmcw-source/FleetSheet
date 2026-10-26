"""WinSparkle updater wrapper — Windows-only, MENU-ONLY checks.

How it works: WinSparkle (WinSparkle.dll, shipped next to this file) reads
a static appcast feed over HTTPS, compares versions, and — only when the
operator asks — shows its own "update available" dialog. If the operator
accepts, WinSparkle downloads the new installer, verifies the Ed25519
signature against the public key below, runs the installer, and asks the
app to quit (see the shutdown callback in init()).

Decision (Jason 2026-10-15), check behavior B — MENU-ONLY: the app NEVER
checks on its own. ``win_sparkle_set_automatic_check_for_updates(0)``.
The only trigger is Admin → "Check for Updates…". Nothing is ever
downloaded or installed without the operator approving in WinSparkle's
dialog. Do not flip automatic checks on without Jason's say-so.

Every call in this module is a safe no-op when the DLL is absent (dev
machines, Mac builds), the platform isn't Windows, WinSparkle was never
initialized, or no real public key has been configured. The updater can
never break app startup.
"""
import ctypes
import os
import sys

_APPCAST_URL = "https://raw.githubusercontent.com/jrmcw-source/FleetSheet/main/appcast.xml"

# PLACEHOLDER PUBLIC KEY — NOT A REAL KEY. Jason generates the real
# Ed25519 keypair on his own laptop (gen_keys.py, build machine only)
# and pastes ONLY the public key here. The private key NEVER enters the
# repo and is never sent anywhere. Until a real key is pasted, init()
# refuses to configure WinSparkle and every call in this module is a
# no-op — the updater is inert, never half-wired.
_ED_PUBKEY_B64_PLACEHOLDER = "REPLACE_WITH_REAL_PUBLIC_KEY"
_ED_PUBKEY_B64 = _ED_PUBKEY_B64_PLACEHOLDER

_ws = None
_initialized = False
_shutdown_cb_ref = None  # keep the CFUNCTYPE alive: GC of it would crash


def _dll_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "WinSparkle.dll")


def _key_configured():
    """True only when a real (non-placeholder) public key is set."""
    return bool(_ED_PUBKEY_B64) and _ED_PUBKEY_B64 != _ED_PUBKEY_B64_PLACEHOLDER


def available():
    """True when a real update check could run: Windows + DLL present +
    a real public key configured. No DLL load, safe to call anywhere."""
    return (sys.platform.startswith("win")
            and os.path.isfile(_dll_path())
            and _key_configured())


def _load():
    """Load WinSparkle.dll once; None when unavailable. Never raises."""
    global _ws
    if _ws is not None:
        return _ws
    if not sys.platform.startswith("win"):
        return None
    if not os.path.isfile(_dll_path()):
        return None
    try:
        ws = ctypes.CDLL(_dll_path())
    except Exception:
        return None
    try:
        # NOTE: win_sparkle_set_app_details takes wchar_t* (wide strings).
        ws.win_sparkle_set_app_details.argtypes = [ctypes.c_wchar_p,
                                                   ctypes.c_wchar_p,
                                                   ctypes.c_wchar_p]
        ws.win_sparkle_set_appcast_url.argtypes = [ctypes.c_char_p]
        ws.win_sparkle_set_ed25519_pub_key.argtypes = [ctypes.c_char_p]
        ws.win_sparkle_set_ed25519_pub_key.restype = ctypes.c_int
        ws.win_sparkle_set_automatic_check_for_updates.argtypes = [ctypes.c_int]
        ws.win_sparkle_set_shut_down_request_callback.argtypes = [
            ctypes.CFUNCTYPE(None)]
    except Exception:
        return None
    _ws = ws
    return _ws


def _invoke_shutdown(fn):
    try:
        fn()
    except Exception:
        pass


def init(version, on_shutdown_request=None):
    """Configure WinSparkle once at app startup (after the server binds).
    Returns True when the updater is live. Never raises. No-op (False)
    when the DLL is absent, the platform isn't Windows, or the
    placeholder key is still in place."""
    global _initialized, _shutdown_cb_ref
    if _initialized:
        return True
    if not _key_configured():
        return False
    ws = _load()
    if ws is None:
        return False
    try:
        ws.win_sparkle_set_app_details("FleetSheet", "FleetSheet",
                                       str(version))
        ws.win_sparkle_set_appcast_url(_APPCAST_URL.encode("utf-8"))
        if ws.win_sparkle_set_ed25519_pub_key(
                _ED_PUBKEY_B64.encode("utf-8")) != 0:
            return False
        # Decision B (menu-only): NO automatic checks. The only trigger
        # is the operator clicking Admin → "Check for Updates…".
        ws.win_sparkle_set_automatic_check_for_updates(0)
        if on_shutdown_request is not None:
            # Fired when the operator accepts an update: the app must quit
            # so the new installer can replace it.
            _shutdown_cb_ref = ctypes.CFUNCTYPE(None)(
                lambda: _invoke_shutdown(on_shutdown_request))
            ws.win_sparkle_set_shut_down_request_callback(_shutdown_cb_ref)
        ws.win_sparkle_init()
        _initialized = True
        return True
    except Exception:
        return False


def check_now():
    """Operator-triggered check (Admin → "Check for Updates…"). Shows
    WinSparkle's own dialog. Returns True when a check was actually
    triggered; False when the updater is unavailable (never initialized,
    no DLL, not Windows, placeholder key). Never raises."""
    if not _initialized:
        return False
    ws = _load()
    if ws is None:
        return False
    try:
        ws.win_sparkle_check_update_with_ui()
        return True
    except Exception:
        return False


def cleanup():
    """Shut WinSparkle down. Safe no-op when it was never initialized."""
    if not _initialized:
        return
    ws = _load()
    if ws is None:
        return
    try:
        ws.win_sparkle_cleanup()
    except Exception:
        pass
