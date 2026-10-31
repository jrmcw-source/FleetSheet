# FleetSheet Changelog

Newest first.

## v1.1.2 — 10/31/2026

- The update checker now starts. A success signal from the
  update library was being read as a failure, so the checker
  never ran and Check for Updates waited without an answer.
  The signal is now read correctly.
- A check that gets no answer now resets itself after a
  minute instead of waiting forever.
- The Administration page now reports the update checker's
  state.
- The "↩ list" button on line-item rows works as intended:
  it leaves a typed-over entry and returns the field to the
  choice that stood before. On rows added with Add Item on
  the Invoice and Credit Memo forms, a typed-over Type or
  Unit is now recorded on its own row — before, it was
  recorded on the first row.
- The Payment form's header holds the same open space as
  the other money forms, so the rule under the header
  stands at the same height on every form.
- The Reports page carries an Export card — the door to
  the Data page, with its quick exports, custom builds,
  and saved presets.
- A new Payment no longer shows an "RP" number. That
  prefix belonged to no document kind. The form now shows
  the payment's own next number before saving, and saving
  records the payment under the number shown.
- Correcting a payment follows the same rule as every
  other document: the corrected payment carries the
  original's number with a revision mark (Rev. 1, Rev. 2,
  and so on), the voided original names its revision on
  its summary, and no number is taken from the sequence
  for a correction.
- Every line row on a money form shows its own total at
  the right end of the row — quantity, unit, price, and
  total, the same on the invoice, quotation, work order,
  change order, credit memo, and sales ticket forms.
- The write-in above the subtotal — a description and an
  amount of the operator's own, with its own Tax flag —
  now stands on every money form: invoice, quotation,
  work order, change order, credit memo, sales ticket,
  and rental ticket. Entered, it counts in the
  document's total and prints with the document; blank,
  it does not print. Before, it stood on the invoice
  only.
- A credit memo opened from its record shows its own
  number in the form's header. Before, the header showed
  the next new memo's number.
- A weekly rate now bills whole weeks and a monthly rate
  whole months: a part of a period bills as a full period,
  and the rental line states the number of periods, so
  its quantity, unit, rate, and amount agree. Before, a
  weekly or monthly rental was prorated by the day while
  its line stated the days. Two settings stand beside
  Minimum Rental Billing Days — Minimum Rental Billing
  Weeks and Minimum Rental Billing Months — setting the
  least number of periods a weekly or monthly contract
  bills.
- A rental ticket's computed charge can be written over on
  the ticket form itself, in the Rental Charge field. The
  written figure is the rental amount everywhere — the
  ticket's total, its waiver and environmental charges,
  and the amount carried onto an invoice — and the computed
  charge stands beside the field, so what was replaced is
  always in view. Clearing the field restores the computed
  charge. Each setting and each clearing is recorded with
  the operator's name and the time.
- A quotation converted to a rental now reckons a month as
  28 days, the same count rental billing itself uses.
- Editing a posted or issued document now opens a working
  copy of it. Nothing is voided while the copy is being
  worked on, and opening Edit again returns to the same
  copy. Saving or printing the copy is the single step
  that voids the original and posts the copy in its place,
  under a revision number standing ready in the number
  field — the original's number with "Rev. N" — which can
  be written over with any unused number. Money recorded
  against any document in a revision chain counts toward
  the chain's head, and an optional revision note, never
  printed, can record why the revision was made.
- On a revision, every line of the original stands in the
  form ready to edit — including lines carried onto an
  invoice from a rental ticket or a work order, which
  before stood below the form read-only — and each such
  line keeps the tax rate recorded on it. A credit memo
  revision opens with its reason and notes standing, and
  a payment revision keeps the original's recorded
  allocations.
- A revised document's balance is now the chain's true
  balance everywhere it is reported: registers, aging,
  and lookups agree, and a voided original no longer
  counts a second time in the aging totals.
- Every Print button now opens one small centered box
  carrying the same choices in the same order — PRINT,
  Print to Screen, Print to Location — and Print to
  Screen presents the document inside the app window.
  No print action opens a separate browser window or tab.
- The document number field widens to fit the number
  standing in it, so a long number — a factory-length
  number with a revision mark — stands whole in its box
  on every form.

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
