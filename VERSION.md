# Version history

- **v1** (`versions/v1/`): initial dashboard — amortization engine, deposit/upfront costs,
  lump sums, milestones, press-and-hold steppers, currency selector, sidebar-based layout.
- **v2** (current `app.py` / `versions/v2/`):
  - Lump-sum behaviour is now a choice: "keep payment the same" (shortens term) vs
    "recalculate the payment" (keeps the original payoff date), with a new "Monthly payment
    over time" chart to show the effect.
  - Instant hover tooltips (custom CSS/JS) replace the slow native browser tooltips, both on
    the stepper "i" icons and on dotted-underlined glossary terms (Principal, Interest,
    Deposit, Balance, etc.) used throughout the captions.
  - Daily actual/365 interest accrual is now the default (was monthly).
  - Fixed the secondary "months since start" axis, which wasn't actually rendering — Plotly
    needs a trace bound to the secondary axis to draw it, not just the layout config.
  - Sidebar removed entirely. Settings/scenario-management/session moved into a collapsible
    "⚙️ Settings, scenarios & session" section on the main page.
  - Scenario-builder tabs replaced with independent expanders, so multiple sections (e.g.
    Loan basics + Lump sums) can be open at once instead of only one tab at a time.
  - Advanced view now shows mean interest and mean principal alongside mean payment per
    year checkpoint, not just the payment figure.

- **v4 / v2 app** (`app_v2.py`, current):
  - New multi-calculator app modeled on MoneySavingExpert's 8 mortgage calculators: Basic mortgage
    calculator, Compare two mortgages, Overpayment calculator, Offset mortgage vs savings, Saving for
    a deposit, Compare fixed rate mortgages, Ditch your fix, How much can I borrow.
  - Landing screen is a grid of calculator cards (matches the MSE "choose a calculator" pattern).
  - Material-Design-inspired visual language: Roboto font, indigo primary palette, elevated card
    containers, styled metrics, gradient "verdict" callouts.
  - Desktop-first layout: each calculator uses a compact two-column (inputs | results) layout so
    everything fits on one screen without scrolling, instead of v1's long vertical stack.
  - Shared calculation engine (`engine.py`) extracted out of `app.py` so v1 and v2 don't duplicate
    amortization/offset/stepper-component logic — v1 (`app.py`) now imports from it and is otherwise
    unchanged in behavior.

- **v5 / v3 app** (`app_v3.py`, current):
  - Single-page dashboard: all 8 calculators from v2 are now toggleable modules on one page via a
    "Show calculators" multiselect, instead of separate navigation screens — turn on as many as you
    want, side by side.
  - Proper session library: named saves with a comment/notes field, a browsable list of saved sessions
    (name, comment, timestamp) with Load/Delete per entry, persisted to `sessions/v3_sessions.json`.
    Still supports export/import as a standalone `.json` file.
  - Every chart's built-in camera/download button now exports SVG (vector) instead of PNG.
  - Every calculator's schedule/results table has a CSV download button.
  - Reuses `engine.py` and the same calculation logic as v1/v2 — no duplicated formulas.

- **v6 / v3 refresh** (`app_v3.py`, current):
  - Brought back the full v1 timeline toolkit into every mortgage-schedule calculator (Basic, Compare,
    Overpayment): rate changes over time, lump sums with a "shorten term vs recalculate payment" choice,
    milestones, deposit & upfront costs at their own dates.
  - Every calculator now supports multiple scenarios ("+ Add another mortgage / deal / option / plan")
    plotted together on the same chart, not just Compare's original two.
  - Confirmed banks'-style daily actual/365 accrual is the default everywhere (was already the case).
  - Export is both individual (one CSV per scenario) and combined (one CSV with all scenarios stacked,
    tagged by name) — every calculator now offers both.
  - Verified a subtle but correct interaction: a rate change recalculates the payment against the
    original contractual remaining term, so it "absorbs" an earlier lump sum's term-shortening effect
    into a lower payment instead — matching how lenders actually reprice mid-term.

- **v7 / v4 app** (`app_v4.py`, new):
  - Full visual redesign inspired by a "Donezo"-style project-management dashboard: green palette
    (#12805c primary), rounded 18px cards with soft shadows, Plus Jakarta Sans typeface.
  - Real sidebar navigation (checkbox list of the 8 calculators + currency) replacing the top
    multiselect, matching the reference's left-hand menu structure.
  - A stat-tile row under the page header (Calculators Active / Total Scenarios / Saved Sessions /
    Interest Model), first tile dark-filled like the reference's "Total Projects" tile — all populated
    from real state, no decorative/fake numbers.
  - All v3 functionality (timeline events, multi-scenario comparison, session library, CSV/SVG export)
    is unchanged — this is a presentation-layer pass only, verified the numbers and interactions still
    work identically after the reskin.
  - Session data is stored separately (`sessions/v4_sessions.json`) so v3 and v4 sessions don't collide.

- **v8 / v4 refinements** (`app_v4.py`, current):
  - New categorical colour palette: green stays the brand anchor, but chart series now alternate
    warm/cool hues (green, amber, blue, red, violet, teal, magenta, brown) so adjacent scenarios are
    never two shades of the same colour.
  - Per-scenario metrics (monthly payment, total interest, payoff date, etc.) now lay out horizontally
    in one row per scenario, instead of stacking vertically — much shorter for 1-2 scenarios, the
    common case.
  - Every tool card is now independently collapsible (▾/▸ toggle in its header) without hiding it from
    the sidebar or losing its state — separate from the sidebar checkbox that shows/hides it entirely.
  - Sidebar gained a "Sessions" section with a quick "Load previous session" picker.
  - Fixed a real ordering bug found while building the above: the sidebar read the saved-sessions list
    before the main "Save session" button's handler ran (Streamlit executes top-to-bottom), so a
    freshly-saved session didn't show in the sidebar until an unrelated second interaction. Fixed by
    forcing an immediate rerun after save/load/delete and persisting the settings-panel's open state
    across that rerun.
