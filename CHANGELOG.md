# FleetSheet Changelog

Newest first.

## v1.1.1 — 10/26/2026

- Update checks now run. In 1.1.0 the updater never started —
  the program addressed the update library by two function
  names the library does not carry — so Check for Updates
  silently did nothing. The calls now use the library's real
  names, and the shipped library is the current one.
- Books created by v1.0 now open. The startup migration
  stopped on older books whose line tables predated the
  current layout, and the program closed without a message.
  The migration now carries those books forward with every
  record kept, including a book a failed start already
  partly migrated.

## v1.1 — 10/20/2026

- Developed under the working number 1.0.2, released as 1.1:
  a backward-compatible feature release (a minor bump, not a
  patch round). Three-number form: 1.1.0.
- Single build going forward: the 10/18/2026 merge of the phone
  v1.0.1 work line and the web glimpse line, replacing the two
  forked lines.
- Today is a glimpse dashboard: 1 hero item plus at most 2 quiet
  mentions, with sticky notes as a card on Today.
- One defer word everywhere: Snooze, with a single minutes stepper.
  Using the stepper teaches the learned standard; the factory
  standard is 30 minutes.
- Desk idle lock only: the separate server idle timeout was removed.
- Print is global and offers three choices everywhere: Print to
  Screen, Print to Location (saves into the folder set in
  Setup → Administration), and PRINT.
- Invoice rebuilt: "Remit To:" and "Billing Address:" blocks; a Job
  Info print box with 12 operator toggles (Setup → Billing) printing
  in a fixed order; a header bar with a blank free-type box, Contact
  Name, and Shipped by; per-line tax toggles that print as asterisks
  after taxed line totals; typed Job Info uploads that print as
  separate pages after the invoice; and envelope placement options
  — Business Envelope #10, Business Envelope #9, or Plain Paper
  Print.
- Invoice totals print on the last page only.

## v1.0.1 — 10/13/2026

- Internal revision rounds on the shipped v1.0 base; not a separate
  public release.
- The v1.0.1 operation manual was stamped 2026-10-13a.

## v1.0 — 10/10/2026

- First public release: GitHub Release with FleetSheet-Setup-1.0.exe
  and a signed update feed (appcast).
- Free and source-available under the FleetSheet License. The
  installer ships unsigned by design, under the $0 Lottery Ticket
  strategy.
