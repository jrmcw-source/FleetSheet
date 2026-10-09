"""Tab-echo guard (2026-10-04).

Jason's rule: the active tab/sub-tab IS the page title. No H1 in the page
body may echo it — no exact repeats, no plurals, no rephrases. Shared views
that render both standalone and embedded take a `bare` parameter that
suppresses their header.

This test renders every page route and fails if any H1 echoes its tab
context, so the pattern can never regress silently.
"""
import re
import urllib.request

BASE = "http://127.0.0.1:8765"

# route -> (nav tab, sub-tab or None)
ROUTES = {
    "/": ("Today", None),
    "/ticket/new": ("Rentals", "Rental"),
    "/ticket/new?kind=quote": ("Rentals", "Quote"),
    "/ticket/new?kind=change": ("Rentals", "Change Order"),
    "/ticket/new?kind=workorder": ("Rentals", "Work Order"),
    "/ticket/new?kind=checkinout": ("Rentals", "Check In/Out"),
    "/money": ("Billing", "New Invoice"),
    "/money?tab=pay": ("Billing", "Record Payment"),
    "/money?tab=credit": ("Billing", "Credit Memo"),
    "/money?tab=petty": ("Billing", "Petty Cash"),
    "/money/all": ("Billing", None),
    "/assets": ("Assets", None),
    "/assets/all": ("Assets", None),
    "/unit/new": ("Assets", None),
    "/compliance": ("Compliance", None),
    "/reports": ("Reports", None),
    "/setup": ("Setup", None),
    "/setup/devices": ("Setup", "Devices"),
    "/setup/security": ("Setup", "Security"),
    "/setup/health": ("Setup", "Data Health"),
    "/quotes": ("Rentals", "Quote"),
    "/changes": ("Rentals", "Change Order"),
    "/customers": ("Setup", "Customers"),
    "/sites": ("Setup", "Sites"),
    "/invoices": ("Billing", None),
    "/backup": ("Setup", None),
    "/done": ("Today", None),
}


def norm(s):
    s = re.sub(r"\s+", " ", s.lower().strip())
    return s


def echoes(header, tab, sub):
    """True if the header repeats the tab/sub-tab (exact, plural, rephrase)."""
    nh, nt = norm(header), norm(tab)
    ns = norm(sub) if sub else ""
    # strip trailing 's' for plural-insensitive compare
    candidates = {nt, nt.rstrip("s")}
    if ns:
        candidates |= {ns, ns.rstrip("s")}
    h = nh.rstrip("s")
    if h in candidates:
        return True
    # rephrase: header's significant words are all tab words (e.g. "Change orders")
    stop = {"the", "a", "an", "new", "all", "my", "of"}
    hw = set(w for w in nh.split() if w not in stop)
    tw = set((nt + " " + ns).split()) - stop
    if hw and hw <= tw:
        return True
    return False


def main():
    failures = []
    for route, (tab, sub) in ROUTES.items():
        try:
            raw = urllib.request.urlopen(BASE + route, timeout=10).read().decode("utf-8", "replace")
        except Exception as e:
            failures.append(f"{route}: could not render ({e})")
            continue
        html = re.sub(r"<script.*?</script>", "", raw, flags=re.S)
        html = re.sub(r"<style.*?</style>", "", html, flags=re.S)
        for m in re.finditer(r"<h1[^>]*>(.*?)</h1>", html, re.S):
            if "cardtitle" in m.group(0)[:60]:
                continue
            txt = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if not txt or len(txt) > 60:
                continue
            if echoes(txt, tab, sub):
                failures.append(
                    f"{route}: H1 '{txt}' echoes tab '{tab}'"
                    + (f" / sub-tab '{sub}'" if sub else "")
                )
    if failures:
        print("TAB-ECHO FAILURES:")
        for f in failures:
            print("  " + f)
        raise SystemExit(1)
    print(f"OK: {len(ROUTES)} routes, no H1 echoes its tab.")


if __name__ == "__main__":
    main()
