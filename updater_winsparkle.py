"""WinSparkle updater wrapper (FleetSheet, Windows installs only).

Implements packaging/WINSPARKLE.md section 3a. Every entry point is a
safe no-op when WinSparkle is unavailable — not Windows, DLL absent, or
no public key baked in yet — so the rest of the app never has to care
whether the updater is live. The DLL (WinSparkle.dll, x64) ships next
to this module in the installed app folder. The copy in this repo is
the official WinSparkle 0.9.4 release binary, SHA-256 verified against
the upstream GitHub release on 2026-10-08:
9b43b1c16ee39fb9a91b5bd75138767898779510e0836be2919250607cdbe8ab

The Ed25519 PUBLIC key below is the trust root for update signatures.
It is safe to ship in source. The matching PRIVATE key never enters
this repo: it lives on the build machine only and signs each release's
installer for the appcast (see WINSPARKLE.md section 5).
"""
import ctypes
import os
import sys

# Ed25519 PUBLIC key (base64). Pairing VERIFIED 2026-10-08: Jason ran
# winsparkle-tool public-key against eddsa_priv.pem on the build
# laptop (%LOCALAPPDATA%\FleetSheet\UpdateSigning) and the derived
# string matched the agent build's updater_config.json exactly. The
# private key never leaves that folder (plus Jason's USB backup).
_ed_pubkey_b64 = "GbNJ0rT+GOjRhNm0PpTa36mMWxCQsMlBylRBXtk1Rc4="

_APPCAST_URL = ("https://github.com/jrmcw-source/FleetSheet"
                "/releases/latest/download/appcast.xml")

_ws = None
_shutdown_cb = None  # ctypes callback object — kept alive at module level


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
    # WinSparkle 0.9.x renamed the Ed25519 setter: the export is
    # win_sparkle_set_eddsa_public_key (the 0.8 name no longer exists).
    _ws.win_sparkle_set_eddsa_public_key.argtypes = [ctypes.c_char_p]
    _ws.win_sparkle_set_eddsa_public_key.restype = ctypes.c_int
    return _ws


def init(version, on_shutdown_request=None):
    """Start the updater once, after the server is up. Returns True when
    the updater is live. on_shutdown_request, when given, is called on
    WinSparkle's thread when the user accepts an update, so the app can
    stop its HTTP server before the new installer runs."""
    global _shutdown_cb
    if not _ed_pubkey_b64:
        return False
    ws = _load()
    if not ws:
        return False
    try:
        ws.win_sparkle_set_app_details("FleetSheet", "FleetSheet", version)
        ws.win_sparkle_set_appcast_url(_APPCAST_URL.encode("utf-8"))
        # 0.9.x semantics: returns 1 on success, 0 on failure.
        if ws.win_sparkle_set_eddsa_public_key(
                _ed_pubkey_b64.encode("utf-8")) != 1:
            return False
        if on_shutdown_request is not None:
            cb_type = ctypes.CFUNCTYPE(None)

            def _ask_shutdown():
                try:
                    on_shutdown_request()
                except Exception:
                    pass

            _shutdown_cb = cb_type(_ask_shutdown)
            ws.win_sparkle_set_shut_down_request_callback(_shutdown_cb)
        ws.win_sparkle_set_automatic_check_for_updates(1)
        ws.win_sparkle_set_update_check_interval(7 * 24 * 3600)  # weekly
        ws.win_sparkle_init()
        return True
    except Exception:
        return False


def check_now():
    """Menu action: 'Check for Updates'. Shows WinSparkle's own UI.
    Returns True when the check was actually handed to WinSparkle."""
    ws = _load()
    if not ws or not _ed_pubkey_b64:
        return False
    try:
        ws.win_sparkle_check_update_with_ui()
        return True
    except Exception:
        return False


def cleanup():
    ws = _load()
    if ws:
        try:
            ws.win_sparkle_cleanup()
        except Exception:
            pass
