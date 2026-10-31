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

Build 'ar' (2026-10-29): init() read the Ed25519 key call's return
backwards. WinSparkle returns 1 when the key is valid and set, 0 when
it is not; the wrapper treated any nonzero return as failure, so the
updater never initialized in any install and every check silently did
nothing. init() now fails only on a 0 return, records WHY it failed in
module state (see status()), and registers the DLL's completion
callbacks. A check that starts but never completes is killed on a
timer: CHECK_TIMEOUT_S after it starts, the wrapper cleans the DLL up
and initializes it again, so one hung check cannot wedge the updater
for the life of the process.

Every call in this module is a safe no-op when the DLL is absent (dev
machines, Mac builds), the platform isn't Windows, WinSparkle was never
initialized, or no real public key has been configured. The updater can
never break app startup.
"""
import ctypes
import os
import sys
import threading
import time

_APPCAST_URL = "https://raw.githubusercontent.com/jrmcw-source/FleetSheet/main/appcast.xml"

# PLACEHOLDER PUBLIC KEY — NOT A REAL KEY. Jason generates the real
# Ed25519 keypair on his own laptop (gen_keys.py, build machine only)
# and pastes ONLY the public key here. The private key NEVER enters the
# repo and is never sent anywhere. Until a real key is pasted, init()
# refuses to configure WinSparkle and every call in this module is a
# no-op — the updater is inert, never half-wired.
_ED_PUBKEY_B64_PLACEHOLDER = "REPLACE_WITH_REAL_PUBLIC_KEY"
_ED_PUBKEY_B64 = _ED_PUBKEY_B64_PLACEHOLDER

# Jason's kill timer (2026-10-29): a check that has not completed
# within this many seconds of starting is treated as hung — the DLL
# is cleaned up and initialized again, and the check is recorded as
# timed out. Read at arm time so tests can shorten it.
CHECK_TIMEOUT_S = 60.0

_ws = None
_initialized = False
_shutdown_cb_ref = None  # keep the CFUNCTYPE alive: GC of it would crash
_cb_refs = []            # completion-callback CFUNCTYPEs: same rule

# Outcome state, recorded for status() and the Admin page.
# _init_state:  not_started | ready | not_configured | dll_missing |
#               key_rejected | init_failed
# _check_state: idle | checking | found | none | error | timeout
_init_state = "not_started"
_check_state = "idle"
_check_started = None    # time.monotonic() when the live check started
_version = None          # init() arguments, kept so the kill timer's
_shutdown_handler = None  # reset can initialize the DLL again as-was
_state_lock = threading.Lock()
_watchdog = None         # threading.Timer for the live check, if any


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
        ws.win_sparkle_set_eddsa_public_key.argtypes = [ctypes.c_char_p]
        ws.win_sparkle_set_eddsa_public_key.restype = ctypes.c_int
        ws.win_sparkle_set_automatic_check_for_updates.argtypes = [ctypes.c_int]
        ws.win_sparkle_set_shutdown_request_callback.argtypes = [
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


def _set_init(state):
    global _init_state
    with _state_lock:
        _init_state = state


def _cancel_watchdog():
    global _watchdog
    t = _watchdog
    _watchdog = None
    if t is not None:
        try:
            t.cancel()
        except Exception:
            pass


def _arm_watchdog():
    """Start the kill timer for the check that just began."""
    global _watchdog
    _cancel_watchdog()
    try:
        t = threading.Timer(CHECK_TIMEOUT_S, _on_check_timeout)
        t.daemon = True
        t.start()
        _watchdog = t
    except Exception:
        _watchdog = None


def _on_check_complete(outcome):
    """A completion callback fired: the live check is over."""
    global _check_state
    with _state_lock:
        if _check_state != "checking":
            return  # late word about a check already reset; ignore it
        _check_state = outcome
    _cancel_watchdog()


def _on_check_timeout():
    """Kill timer: the check started CHECK_TIMEOUT_S ago and no
    completion callback has arrived. Clean the DLL up and initialize
    it again so the next check starts from a reset updater."""
    global _initialized, _check_state, _watchdog
    with _state_lock:
        if _check_state != "checking":
            return
        _check_state = "timeout"
        _watchdog = None
    ws = _load()
    if ws is not None:
        try:
            ws.win_sparkle_cleanup()
        except Exception:
            pass
    _initialized = False
    init(_version, _shutdown_handler)  # records the new init state


def _register_completion_callbacks(ws):
    """Register the DLL's check-completion callbacks — only the
    exports this DLL actually carries. Signatures were verified
    against the shipped WinSparkle.dll's export table (build 'ar'):
    win_sparkle_set_did_find_update_callback,
    win_sparkle_set_did_not_find_update_callback, and the error
    setter, which this DLL exports as win_sparkle_set_error_callback
    (there is no win_sparkle_set_update_error_callback)."""
    global _cb_refs
    specs = (("win_sparkle_set_did_find_update_callback", "found"),
             ("win_sparkle_set_did_not_find_update_callback", "none"),
             ("win_sparkle_set_error_callback", "error"),
             ("win_sparkle_set_update_error_callback", "error"))
    refs = []
    for setter_name, outcome in specs:
        setter = getattr(ws, setter_name, None)
        if setter is None:
            continue
        try:
            cb = ctypes.CFUNCTYPE(None)(
                lambda o=outcome: _on_check_complete(o))
            setter(cb)
            refs.append(cb)
        except Exception:
            pass
    _cb_refs = refs


def init(version, on_shutdown_request=None):
    """Configure WinSparkle once at app startup (after the server binds).
    Returns True when the updater is live. Never raises. No-op (False)
    when the DLL is absent, the platform isn't Windows, or the
    placeholder key is still in place. The outcome — including which
    failure stopped it — is recorded for status()."""
    global _initialized, _shutdown_cb_ref, _version, _shutdown_handler
    if _initialized:
        return True
    _version = version
    _shutdown_handler = on_shutdown_request
    if not _key_configured():
        _set_init("not_configured")
        return False
    ws = _load()
    if ws is None:
        # A DLL file that is present but would not load or configure
        # is an init failure; no file at all is a missing DLL.
        _set_init("init_failed" if os.path.isfile(_dll_path())
                  else "dll_missing")
        return False
    try:
        ws.win_sparkle_set_app_details("FleetSheet", "FleetSheet",
                                       str(version))
        ws.win_sparkle_set_appcast_url(_APPCAST_URL.encode("utf-8"))
        # WinSparkle returns 1 when the key is valid and set, 0 when
        # it is not — fail only on 0. (Build 'ar': this test stood
        # backwards through 1.1.1, so init never once succeeded.)
        if ws.win_sparkle_set_eddsa_public_key(
                _ED_PUBKEY_B64.encode("utf-8")) == 0:
            _set_init("key_rejected")
            return False
        # Decision B (menu-only): NO automatic checks. The only trigger
        # is the operator clicking Admin → "Check for Updates…".
        ws.win_sparkle_set_automatic_check_for_updates(0)
        _register_completion_callbacks(ws)
        if on_shutdown_request is not None:
            # Fired when the operator accepts an update: the app must quit
            # so the new installer can replace it.
            _shutdown_cb_ref = ctypes.CFUNCTYPE(None)(
                lambda: _invoke_shutdown(on_shutdown_request))
            ws.win_sparkle_set_shutdown_request_callback(_shutdown_cb_ref)
        ws.win_sparkle_init()
        _initialized = True
        _set_init("ready")
        return True
    except Exception:
        _set_init("init_failed")
        return False


def check_now():
    """Operator-triggered check (Admin → "Check for Updates…"). Shows
    WinSparkle's own dialog. Returns True when a check was actually
    triggered; False when the updater is unavailable (never initialized,
    no DLL, not Windows, placeholder key). Never raises."""
    global _check_state, _check_started
    if not _initialized:
        return False
    with _state_lock:
        if _check_state == "checking":
            return True  # a check is already underway
    ws = _load()
    if ws is None:
        return False
    try:
        ws.win_sparkle_check_update_with_ui()
    except Exception:
        with _state_lock:
            _check_state = "error"
        return False
    with _state_lock:
        _check_state = "checking"
        _check_started = time.monotonic()
    _arm_watchdog()
    return True


def status():
    """The updater's recorded state, for the Admin page. Never raises.
    Returns a dict: init (the init outcome), check (the last check's
    state), ready (True when a check can run), and line — one short
    formal line for the page."""
    with _state_lock:
        init_state = _init_state
        check_state = _check_state
        ready = _initialized
    if init_state == "ready":
        if check_state == "checking":
            line = "Updater: Checking for updates…"
        elif check_state == "found":
            line = "Updater: Ready. Last check found an update."
        elif check_state == "none":
            line = "Updater: Ready. Last check found no update."
        elif check_state == "error":
            line = "Updater: Ready. Last check ended in error."
        elif check_state == "timeout":
            line = ("Updater: Ready. Last check received no answer "
                    "and was reset.")
        else:
            line = "Updater: Ready."
    elif init_state == "not_configured":
        line = "Updater: Not configured."
    elif init_state == "dll_missing":
        line = "Updater: Not available — update library missing."
    elif init_state == "key_rejected":
        line = "Updater: Not ready — update key rejected."
    elif init_state == "not_started":
        line = "Updater: Not started."
    else:
        line = "Updater: Not ready."
    return {"init": init_state, "check": check_state,
            "ready": ready, "line": line}


def cleanup():
    """Shut WinSparkle down. Safe no-op when it was never initialized."""
    global _check_state
    _cancel_watchdog()
    if not _initialized:
        return
    ws = _load()
    if ws is None:
        return
    try:
        ws.win_sparkle_cleanup()
    except Exception:
        pass
    with _state_lock:
        _check_state = "idle"
