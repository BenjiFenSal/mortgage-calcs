import bisect
import json
from dataclasses import dataclass, field, asdict
from datetime import date
from calendar import monthrange
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

SESSION_FILE = Path(__file__).parent / "sessions" / "last_session.json"
SESSION_FILE.parent.mkdir(exist_ok=True)

st.set_page_config(page_title="Mortgage Projection Dashboard", layout="wide")

TERM_CHECKPOINTS = [1, 5, 10, 15, 20, 25, 30, 35, 40]
PALETTE = ["#ff4b4b", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf"]

CURRENCY_OPTIONS = {
    "£ British Pound (GBP)": "£",
    "€ Euro (EUR)": "€",
    "$ US Dollar (USD)": "$",
    "$ Canadian Dollar (CAD)": "CA$",
    "$ Australian Dollar (AUD)": "AU$",
    "Fr Swiss Franc (CHF)": "Fr",
}

LUMP_SUM_MODES = {
    "shorten_term": "Keep the payment the same → pay off earlier",
    "reduce_payment": "Recalculate the payment → keep the original payoff date",
}


# ---------------------------------------------------------------------------
# Custom "press-and-hold" numeric stepper component
# ---------------------------------------------------------------------------

_STEPPER_DIR = Path(__file__).parent / "components" / "stepper"
_stepper_component = components.declare_component("stepper", path=str(_STEPPER_DIR))


def stepper(
    label: str,
    value: float,
    step: float = 1.0,
    min_value: float | None = None,
    max_value: float | None = None,
    decimals: int = 0,
    prefix: str = "",
    suffix: str = "",
    thousands: bool = False,
    help: str | None = None,
    key: str | None = None,
) -> float:
    """A numeric +/- stepper that repeats and accelerates while held down."""
    result = _stepper_component(
        label=label,
        value=float(value),
        step=float(step),
        min_value=min_value,
        max_value=max_value,
        decimals=decimals,
        prefix=prefix,
        suffix=suffix,
        thousands=thousands,
        help=help,
        key=key,
        default=float(value),
    )
    return float(result) if result is not None else float(value)


# ---------------------------------------------------------------------------
# Amortization engine
# ---------------------------------------------------------------------------

def add_months(d: date, months: int) -> date:
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


def monthly_payment(balance: float, annual_rate_pct: float, remaining_months: int) -> float:
    if remaining_months <= 0:
        return balance
    r = annual_rate_pct / 100 / 12
    if r == 0:
        return balance / remaining_months
    return balance * r / (1 - (1 + r) ** -remaining_months)


def build_schedule(
    principal: float,
    annual_rate_pct: float,
    term_months: int,
    start_date: date,
    method: str = "monthly",          # "monthly" or "daily_actual"
    extra_payment: float = 0.0,
    rate_changes: list[tuple[int, float]] | None = None,   # (month_index_from_1, new_annual_rate_pct)
    lump_sums: list[tuple[int, float]] | None = None,       # (month_index_from_1, amount)
    lump_sum_mode: str = "shorten_term",                     # "shorten_term" or "reduce_payment"
) -> pd.DataFrame:
    rate_changes = sorted(rate_changes or [])
    rate_map = dict(rate_changes)
    lump_map: dict[int, float] = {}
    for m, amt in (lump_sums or []):
        lump_map[m] = lump_map.get(m, 0.0) + amt

    balance = principal
    current_rate = annual_rate_pct
    remaining_months = term_months
    payment = monthly_payment(balance, current_rate, remaining_months)

    rows = []
    month_idx = 0

    while balance > 0.01 and month_idx < term_months * 3:  # hard safety cap
        month_idx += 1

        # apply a rate change effective this month -> re-amortize over remaining term
        if month_idx in rate_map:
            current_rate = rate_map[month_idx]
            remaining_months = term_months - month_idx + 1
            payment = monthly_payment(balance, current_rate, remaining_months)

        period_date = add_months(start_date, month_idx)

        if method == "daily_actual":
            days = monthrange(period_date.year, period_date.month)[1]
            interest = balance * (current_rate / 100 / 365) * days
        else:
            interest = balance * (current_rate / 100 / 12)

        # the scheduled/required payment BEFORE this month's extras — i.e. what the
        # baseline amortization says is due, unaffected by a lump sum applied this month
        scheduled_payment = payment

        lump_sum_amt = lump_map.get(month_idx, 0.0)
        total_payment = payment + extra_payment + lump_sum_amt
        principal_paid = total_payment - interest

        if principal_paid >= balance:
            principal_paid = balance
            total_payment = principal_paid + interest
            balance = 0.0
        else:
            balance -= principal_paid

        # a lump sum can either shorten the term (payment stays the same) or, if chosen,
        # recalculate the payment from the NEXT month onward to keep the original payoff date
        if lump_sum_amt and lump_sum_mode == "reduce_payment" and balance > 0:
            remaining_months = term_months - month_idx
            if remaining_months > 0:
                payment = monthly_payment(balance, current_rate, remaining_months)

        rows.append(
            {
                "Month": month_idx,
                "Date": period_date,
                "Rate (%)": current_rate,
                "ScheduledPayment": scheduled_payment,
                "Payment": total_payment,
                "Interest": interest,
                "Principal": principal_paid,
                "LumpSum": lump_sum_amt,
                "Balance": balance,
            }
        )

        if balance <= 0:
            break

    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"total_paid": 0, "total_interest": 0, "payoff_date": None, "months": 0, "total_lump_sums": 0}
    return {
        "total_paid": df["Payment"].sum(),
        "total_interest": df["Interest"].sum(),
        "payoff_date": df["Date"].iloc[-1],
        "months": len(df),
        "total_lump_sums": df["LumpSum"].sum(),
    }


def yearly_stats(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Year", "Interest", "Principal", "Payment", "MeanPayment", "Months"])
    d = df.copy()
    d["Year"] = pd.to_datetime(d["Date"]).dt.year
    g = d.groupby("Year").agg(
        Interest=("Interest", "sum"),
        Principal=("Principal", "sum"),
        Payment=("Payment", "sum"),
        MeanPayment=("Payment", "mean"),
        Months=("Payment", "count"),
    )
    return g.reset_index()


def cumulative_upfront(dates: list, upfront_costs: list[list]) -> np.ndarray:
    """Running total of upfront costs as of each date in `dates`."""
    if not upfront_costs:
        return np.zeros(len(dates))
    parsed = sorted(
        ((date.fromisoformat(c[2]), float(c[1])) for c in upfront_costs),
        key=lambda x: x[0],
    )
    cdates = [p[0] for p in parsed]
    cum = np.cumsum([p[1] for p in parsed])
    out = []
    for dt in dates:
        idx = bisect.bisect_right(cdates, dt) - 1
        out.append(cum[idx] if idx >= 0 else 0.0)
    return np.array(out)


def add_month_axis(fig: go.Figure, ref_start: date, max_months: int, min_date, max_date):
    """Adds a secondary top x-axis showing months elapsed since ref_start."""
    if max_months <= 0:
        return
    step = 12 if max_months > 60 else (6 if max_months > 24 else 1)
    months = list(range(0, max_months + 1, step))
    if months[-1] != max_months:
        months.append(max_months)
    tickvals = [pd.Timestamp(add_months(ref_start, m)) for m in months]
    ticktext = [str(m) for m in months]
    fig.update_layout(
        xaxis=dict(range=[pd.Timestamp(min_date), pd.Timestamp(max_date)]),
        xaxis2=dict(
            overlaying="x",
            side="top",
            range=[pd.Timestamp(min_date), pd.Timestamp(max_date)],
            tickmode="array",
            tickvals=tickvals,
            ticktext=ticktext,
            title=dict(text="Months since start", font=dict(size=11)),
            showgrid=False,
        ),
    )


# ---------------------------------------------------------------------------
# Scenario data model
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    name: str
    principal: float
    annual_rate_pct: float
    term_years: float
    start_date: str
    method: str
    extra_payment: float
    rate_changes: list = field(default_factory=list)      # [[month, new_rate], ...]
    deposit: float = 0.0
    upfront_costs: list = field(default_factory=list)      # [[name, amount, date_iso], ...]
    lump_sums: list = field(default_factory=list)          # [[month, amount, label], ...]
    milestones: list = field(default_factory=list)         # [[month, label], ...]
    lump_sum_mode: str = "shorten_term"

    def term_months(self) -> int:
        return int(round(self.term_years * 12))

    def schedule(self) -> pd.DataFrame:
        return build_schedule(
            principal=self.principal,
            annual_rate_pct=self.annual_rate_pct,
            term_months=self.term_months(),
            start_date=date.fromisoformat(self.start_date),
            method=self.method,
            extra_payment=self.extra_payment,
            rate_changes=[tuple(rc) for rc in self.rate_changes],
            lump_sums=[(int(ls[0]), float(ls[1])) for ls in self.lump_sums],
            lump_sum_mode=self.lump_sum_mode,
        )

    def upfront_costs_total(self) -> float:
        return sum(float(c[1]) for c in self.upfront_costs)


def save_session(scenarios: list[Scenario], path: Path = SESSION_FILE):
    path.write_text(json.dumps([asdict(s) for s in scenarios], indent=2))


def load_session(path: Path = SESSION_FILE) -> list[Scenario]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [Scenario(**s) for s in data]


# ---------------------------------------------------------------------------
# App state
# ---------------------------------------------------------------------------

if "scenarios" not in st.session_state:
    st.session_state.scenarios = load_session()

st.title("🏠 Mortgage Projection Dashboard")
st.caption(
    "Reducing-balance amortization with optional daily-accrual interest and mid-term rate changes, "
    "so you can reproduce how a bank actually schedules payments."
)
st.info(
    "**Principal** is the amount you borrow (and still owe) — interest is charged on this outstanding "
    "balance each period. **Interest** is the lender's charge for lending it to you. Every payment splits "
    "between the two: early on it's mostly interest, later it's mostly principal, which is why the "
    "'Cumulative interest vs principal' chart below curves the way it does.",
    icon="📘",
)

# --- Sidebar: settings + scenario management (not the editing form) --------
st.sidebar.header("⚙️ Settings")
currency_choice = st.sidebar.selectbox(
    "Currency",
    list(CURRENCY_OPTIONS.keys()),
    help="Changes the currency symbol shown throughout the app. This is a display label only — "
    "amounts are not converted between currencies.",
)
CUR = CURRENCY_OPTIONS[currency_choice]

st.sidebar.divider()
st.sidebar.header("📁 Scenarios")
edit_names = ["<new scenario>"] + [s.name for s in st.session_state.scenarios]
edit_choice = st.sidebar.selectbox("Edit existing scenario", edit_names)

if edit_choice != "<new scenario>":
    base = next(s for s in st.session_state.scenarios if s.name == edit_choice)
else:
    base = Scenario(
        name=f"Scenario {len(st.session_state.scenarios) + 1}",
        principal=250_000,
        annual_rate_pct=4.5,
        term_years=25,
        start_date=date.today().isoformat(),
        method="monthly",
        extra_payment=0,
        rate_changes=[],
        deposit=0.0,
        upfront_costs=[],
        lump_sums=[],
        milestones=[],
        lump_sum_mode="shorten_term",
    )

skey = edit_choice  # component keys are suffixed with this so switching scenarios resets local widget state

if st.sidebar.button("Clear all scenarios"):
    st.session_state.scenarios = []

st.sidebar.divider()
st.sidebar.header("💾 Session")
persist_col1, persist_col2 = st.sidebar.columns(2)
if persist_col1.button("Save to disk"):
    save_session(st.session_state.scenarios)
    st.sidebar.success("Session saved.")
if persist_col2.button("Reload saved"):
    st.session_state.scenarios = load_session()
    st.sidebar.success("Session reloaded.")

st.sidebar.download_button(
    "⬇️ Export session (.json)",
    data=json.dumps([asdict(s) for s in st.session_state.scenarios], indent=2),
    file_name="mortgage_session.json",
    mime="application/json",
)
uploaded = st.sidebar.file_uploader("⬆️ Import session (.json)", type="json")
if uploaded is not None:
    imported = [Scenario(**s) for s in json.loads(uploaded.read())]
    st.session_state.scenarios = imported
    st.sidebar.success(f"Imported {len(imported)} scenario(s).")


# ---------------------------------------------------------------------------
# Main page: scenario builder (tabs, not sidebar)
# ---------------------------------------------------------------------------

st.header("✏️ Editing: " + (edit_choice if edit_choice != "<new scenario>" else "new scenario"))

name = st.text_input("Scenario name", base.name)

tab_basics, tab_deposit, tab_rates, tab_lumps, tab_milestones = st.tabs(
    ["💰 Loan basics", "🏦 Deposit & costs", "📈 Rate changes", "💵 Lump sums", "🚩 Milestones"]
)

with tab_basics:
    c1, c2 = st.columns(2)
    with c1:
        principal = stepper(
            f"Loan amount — Principal ({CUR})", base.principal, step=1000, min_value=0, decimals=0, prefix=CUR, thousands=True,
            help="The principal: the amount you're borrowing (and still owe). Interest each period is charged "
            "on this outstanding balance, so anything that shrinks it (a bigger deposit, overpayments) reduces "
            "future interest too.",
            key=f"principal_{skey}",
        )
        term_years = st.slider("Term (years)", min_value=1, max_value=40, value=int(base.term_years), step=1)
        term_years_fine = stepper(
            "Term (years, fine-tune)", term_years, step=0.5, min_value=0.5, max_value=40, decimals=1, suffix=" yrs",
            help="The mortgage term: how long you have to repay the loan in full. A longer term lowers the "
            "monthly payment but increases total interest paid, since the balance stays higher for longer.",
            key=f"term_{skey}",
        )
        start_date_val = st.date_input(
            "Start date", date.fromisoformat(base.start_date),
            help="The date your first mortgage payment is due. Used to project every future payment date.",
        )
    with c2:
        annual_rate_pct = stepper(
            "Starting annual interest rate (%)", base.annual_rate_pct, step=0.05, min_value=0, max_value=25, decimals=2, suffix="%",
            help="The nominal annual interest rate the lender charges. For a reducing-balance mortgage this is "
            "applied to the outstanding principal each period, not the original loan amount.",
            key=f"rate_{skey}",
        )
        method = st.radio(
            "Interest accrual method",
            options=["monthly", "daily_actual"],
            index=0 if base.method == "monthly" else 1,
            format_func=lambda m: "Monthly (rate/12)" if m == "monthly" else "Daily actual/365 (bank-style)",
            help="Monthly: interest = balance × rate/12, the textbook approximation. Daily actual/365: interest "
            "= balance × rate/365 × days in that month — what many UK lenders (trackers/SVR) actually do, which "
            "is usually why a spreadsheet estimate drifts from your real statement.",
        )
        extra_payment = stepper(
            f"Extra monthly overpayment ({CUR})", base.extra_payment, step=50, min_value=0, decimals=0, prefix=CUR, thousands=True,
            help="A fixed amount paid on top of the required monthly payment, every month, applied entirely to "
            "principal. Shortens the term and cuts total interest, since less balance is left to accrue "
            "interest each period.",
            key=f"extra_{skey}",
        )

with tab_deposit:
    deposit = stepper(
        f"Deposit ({CUR})", base.deposit, step=1000, min_value=0, decimals=0, prefix=CUR, thousands=True,
        help="Cash you put in upfront, e.g. from savings. It reduces how much you need to borrow but isn't part "
        "of the loan itself, so it doesn't accrue mortgage interest — it's still real money you've spent, "
        "though, which is why it's included in your total cash outlay.",
        key=f"deposit_{skey}",
    )
    st.caption(
        "One-off costs like stamp duty, legal/conveyancing fees, surveys, or moving costs — real cash spent "
        "that isn't part of the loan. Give each one a name, amount, and the date it was (or will be) paid."
    )
    uc_df_default = (
        pd.DataFrame(base.upfront_costs, columns=["Name", "Amount", "Date"])
        if base.upfront_costs
        else pd.DataFrame(columns=["Name", "Amount", "Date"])
    )
    if not uc_df_default.empty:
        uc_df_default["Date"] = pd.to_datetime(uc_df_default["Date"])
    uc_df = st.data_editor(
        uc_df_default,
        num_rows="dynamic",
        use_container_width=True,
        key=f"uc_editor_{skey}",
        column_config={
            "Name": st.column_config.TextColumn("Name", help="What the cost was for, e.g. 'Stamp duty' or 'Survey'."),
            "Amount": st.column_config.NumberColumn(f"Amount ({CUR})", help="How much you paid or expect to pay."),
            "Date": st.column_config.DateColumn("Date", help="When this cost is/was incurred."),
        },
    )
    upfront_costs = [
        [str(row["Name"]), float(row["Amount"]), pd.Timestamp(row["Date"]).date().isoformat()]
        for _, row in uc_df.dropna().iterrows()
        if row["Name"] and row["Amount"] not in (None, "")
    ]

with tab_rates:
    st.caption("e.g. tracker/SVR reverting after a fixed period. Payment is recalculated over the remaining term.")
    rc_df_default = pd.DataFrame(base.rate_changes, columns=["Month", "New Rate (%)"]) if base.rate_changes else pd.DataFrame(
        columns=["Month", "New Rate (%)"]
    )
    rc_df = st.data_editor(
        rc_df_default,
        num_rows="dynamic",
        use_container_width=True,
        key=f"rc_editor_{skey}",
        column_config={
            "Month": st.column_config.NumberColumn("Month", help="Payment number (1 = first payment) this new rate takes effect from."),
            "New Rate (%)": st.column_config.NumberColumn("New Rate (%)", help="The new annual rate from that month onward. Payment is recalculated over the remaining term."),
        },
    )
    rate_changes = [
        [int(row["Month"]), float(row["New Rate (%)"])]
        for _, row in rc_df.dropna().iterrows()
        if row["Month"] and row["New Rate (%)"] not in (None, "")
    ]

with tab_lumps:
    st.caption("A one-off overpayment, e.g. a bonus or inheritance, applied entirely to the balance in a given month.")
    ls_df_default = (
        pd.DataFrame(base.lump_sums, columns=["Month", "Amount", "Label"])
        if base.lump_sums
        else pd.DataFrame(columns=["Month", "Amount", "Label"])
    )
    ls_df = st.data_editor(
        ls_df_default,
        num_rows="dynamic",
        use_container_width=True,
        key=f"ls_editor_{skey}",
        column_config={
            "Month": st.column_config.NumberColumn("Month", help="Payment number the lump sum is applied in."),
            "Amount": st.column_config.NumberColumn(f"Amount ({CUR})", help="The one-off amount paid, on top of the normal payment, applied to principal."),
            "Label": st.column_config.TextColumn("Label", help="A short note, e.g. 'Bonus' or 'Inheritance'."),
        },
    )
    lump_sums = [
        [int(row["Month"]), float(row["Amount"]), str(row.get("Label") or "")]
        for _, row in ls_df.dropna(subset=["Month", "Amount"]).iterrows()
        if row["Month"] and row["Amount"] not in (None, "")
    ]

    st.divider()
    st.markdown("**What happens after a lump sum?**")
    st.caption(
        "The starting monthly payment always stays untouched before the lump sum's month. From that month "
        "onward, choose whether it goes toward finishing early or lowering the payment."
    )
    lump_sum_mode = st.radio(
        "Lump sum behaviour",
        options=list(LUMP_SUM_MODES.keys()),
        index=list(LUMP_SUM_MODES.keys()).index(base.lump_sum_mode if base.lump_sum_mode in LUMP_SUM_MODES else "shorten_term"),
        format_func=lambda m: LUMP_SUM_MODES[m],
        help="'Keep the payment the same' applies the lump sum entirely to the balance and leaves the required "
        "monthly payment unchanged, so the mortgage finishes sooner. 'Recalculate the payment' re-amortizes "
        "the new (lower) balance over the months remaining in the original term, so the payoff date doesn't "
        "move but the monthly payment drops from the next payment onward.",
    )

with tab_milestones:
    st.caption("Label-only markers on the charts, e.g. 'Fixed period ends' — no effect on the numbers.")
    ms_df_default = (
        pd.DataFrame(base.milestones, columns=["Month", "Label"])
        if base.milestones
        else pd.DataFrame(columns=["Month", "Label"])
    )
    ms_df = st.data_editor(
        ms_df_default,
        num_rows="dynamic",
        use_container_width=True,
        key=f"ms_editor_{skey}",
        column_config={
            "Month": st.column_config.NumberColumn("Month", help="Payment number to mark on the charts."),
            "Label": st.column_config.TextColumn("Label", help="What to call this marker, e.g. 'Fixed period ends'."),
        },
    )
    milestones = [
        [int(row["Month"]), str(row["Label"])]
        for _, row in ms_df.dropna().iterrows()
        if row["Month"] and row["Label"]
    ]

col_a, col_b, col_c = st.columns([1, 1, 4])
add_clicked = col_a.button("💾 Save scenario", type="primary")
del_clicked = col_b.button("🗑️ Delete") if edit_choice != "<new scenario>" else False

new_scenario = Scenario(
    name=name,
    principal=principal,
    annual_rate_pct=annual_rate_pct,
    term_years=term_years_fine,
    start_date=start_date_val.isoformat(),
    method=method,
    extra_payment=extra_payment,
    rate_changes=rate_changes,
    deposit=deposit,
    upfront_costs=upfront_costs,
    lump_sums=lump_sums,
    milestones=milestones,
    lump_sum_mode=lump_sum_mode,
)

if add_clicked:
    st.session_state.scenarios = [s for s in st.session_state.scenarios if s.name != edit_choice]
    st.session_state.scenarios = [s for s in st.session_state.scenarios if s.name != name]
    st.session_state.scenarios.append(new_scenario)
    st.success(f"Saved '{name}'")

if del_clicked:
    st.session_state.scenarios = [s for s in st.session_state.scenarios if s.name != edit_choice]
    st.success(f"Deleted '{edit_choice}'")


# ---------------------------------------------------------------------------
# Dashboard: compare & visualize saved scenarios
# ---------------------------------------------------------------------------

st.divider()
st.header("📊 Dashboard")

if not st.session_state.scenarios:
    st.info("Build a scenario above and click **Save scenario** to get started.")
    st.stop()

compare_names = st.multiselect(
    "Scenarios to compare",
    [s.name for s in st.session_state.scenarios],
    default=[s.name for s in st.session_state.scenarios],
)
active = [s for s in st.session_state.scenarios if s.name in compare_names]

if not active:
    st.warning("Select at least one scenario to view.")
    st.stop()

include_upfront = st.checkbox(
    "Include deposit & upfront costs in totals and the outlay chart",
    value=True,
    help="Deposit and one-off costs (stamp duty, legal fees, etc.) are real cash you spend but aren't part of "
    "the loan. Turn this off to see the mortgage numbers on their own, or on to see your true total cost of "
    "buying the property.",
)

schedules = {s.name: s.schedule() for s in active}
ref_start = min(date.fromisoformat(s.start_date) for s in active)
max_months_all = max(len(schedules[s.name]) for s in active)
min_date_all = min(schedules[s.name]["Date"].iloc[0] for s in active)
max_date_all = max(schedules[s.name]["Date"].iloc[-1] for s in active)

# --- Summary metrics ---
st.subheader("Summary")
cols = st.columns(len(active))
for col, s in zip(cols, active):
    df = schedules[s.name]
    summ = summarize(df)
    with col:
        st.markdown(f"**{s.name}**")
        st.metric(
            "Total paid",
            f"{CUR}{summ['total_paid']:,.0f}",
            help="The sum of every mortgage payment over the life of the loan: all principal plus all interest "
            "(including any overpayments and lump sums), but not the deposit or upfront costs.",
        )
        st.metric(
            "Total interest",
            f"{CUR}{summ['total_interest']:,.0f}",
            help="The total cost of borrowing: everything you pay the lender beyond the original principal.",
        )
        st.metric(
            "Payoff date",
            summ["payoff_date"].isoformat() if summ["payoff_date"] else "—",
            help="The date the outstanding balance reaches zero, given the term, rate changes, and any "
            "overpayments or lump sums.",
        )
        st.metric(
            "Months to pay off",
            summ["months"],
            help="How many monthly payments it actually takes to clear the balance — shorter than the nominal "
            "term if you overpay or make lump sums that shorten the term.",
        )
        if include_upfront:
            total_cash = summ["total_paid"] + s.deposit + s.upfront_costs_total()
            st.metric(
                "Total cash invested",
                f"{CUR}{total_cash:,.0f}",
                help="Total paid on the mortgage, plus your deposit and upfront costs — the true all-in cost of "
                "buying and paying off the property.",
            )

        with st.expander("Advanced view"):
            st.caption("Mean monthly payment by year")
            ys = yearly_stats(df)
            start_year = date.fromisoformat(s.start_date).year
            rows = []
            for k in TERM_CHECKPOINTS:
                target_year = start_year + k - 1
                match = ys[ys["Year"] == target_year]
                if not match.empty and k <= s.term_years + 1:
                    rows.append({"Year": f"Year {k}", "Mean monthly payment": f"{CUR}{match['MeanPayment'].iloc[0]:,.0f}"})
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.caption("—")

            st.caption("Scenario inputs")
            info_rows = [
                {"Field": "Loan amount (principal)", "Value": f"{CUR}{s.principal:,.0f}"},
                {"Field": "Starting rate", "Value": f"{s.annual_rate_pct:.2f}%"},
                {"Field": "Term", "Value": f"{s.term_years:g} years"},
                {"Field": "Start date", "Value": s.start_date},
                {"Field": "Interest method", "Value": "Monthly (rate/12)" if s.method == "monthly" else "Daily actual/365"},
                {"Field": "Extra monthly overpayment", "Value": f"{CUR}{s.extra_payment:,.0f}"},
                {"Field": "Deposit", "Value": f"{CUR}{s.deposit:,.0f}"},
                {"Field": "Upfront costs total", "Value": f"{CUR}{s.upfront_costs_total():,.0f}"},
                {"Field": "Rate changes", "Value": str(len(s.rate_changes))},
                {"Field": "Lump sum payments", "Value": f"{len(s.lump_sums)} ({CUR}{summ['total_lump_sums']:,.0f})"},
                {"Field": "Lump sum behaviour", "Value": LUMP_SUM_MODES.get(s.lump_sum_mode, s.lump_sum_mode)},
            ]
            st.dataframe(pd.DataFrame(info_rows), use_container_width=True, hide_index=True)

show_events = len(active) <= 2

# --- Balance over time ---
st.subheader("Balance over time")
st.caption(
    "The outstanding loan balance ('what you still owe') month by month, i.e. the principal remaining. It "
    "falls faster than a straight line because early payments are mostly interest and later payments are "
    "mostly principal."
)
fig_balance = go.Figure()
for i, s in enumerate(active):
    df = schedules[s.name]
    color = PALETTE[i % len(PALETTE)]
    fig_balance.add_trace(go.Scatter(x=df["Date"], y=df["Balance"], mode="lines", name=s.name, line=dict(color=color)))

    if show_events:
        d0 = date.fromisoformat(s.start_date)
        for m, new_rate in s.rate_changes:
            fig_balance.add_vline(
                x=pd.Timestamp(add_months(d0, int(m))), line_dash="dot", line_color=color, opacity=0.5,
                annotation_text=f"{s.name}: rate → {new_rate:g}%", annotation_textangle=-90, annotation_font_size=10,
            )
        for m, amt, label in s.lump_sums:
            txt = f"{s.name}: lump sum {CUR}{amt:,.0f}" + (f" ({label})" if label else "")
            fig_balance.add_vline(
                x=pd.Timestamp(add_months(d0, int(m))), line_dash="dash", line_color=color, opacity=0.5,
                annotation_text=txt, annotation_textangle=-90, annotation_font_size=10,
            )
        for m, label in s.milestones:
            fig_balance.add_vline(
                x=pd.Timestamp(add_months(d0, int(m))), line_dash="dashdot", line_color="#808495", opacity=0.6,
                annotation_text=f"{s.name}: {label}", annotation_textangle=-90, annotation_font_size=10,
            )
if not show_events and any(s.rate_changes or s.lump_sums or s.milestones for s in active):
    st.caption("Event markers (rate changes, lump sums, milestones) are hidden when comparing more than 2 scenarios — select fewer to see them on the chart.")
fig_balance.update_layout(yaxis_title=f"Outstanding balance ({CUR})", xaxis_title="Date", height=440)
add_month_axis(fig_balance, ref_start, max_months_all, min_date_all, max_date_all)
st.plotly_chart(fig_balance, use_container_width=True)

# --- Monthly payment over time ---
st.subheader("Monthly payment over time")
st.caption(
    "The required scheduled payment (excluding any extra overpayment). Steps down or up whenever a rate "
    "change or a lump sum (in 'recalculate the payment' mode) takes effect."
)
fig_payment = go.Figure()
for i, s in enumerate(active):
    df = schedules[s.name]
    color = PALETTE[i % len(PALETTE)]
    fig_payment.add_trace(go.Scatter(x=df["Date"], y=df["ScheduledPayment"], mode="lines", name=s.name, line=dict(color=color, shape="hv")))
fig_payment.update_layout(yaxis_title=f"Scheduled monthly payment ({CUR})", xaxis_title="Date", height=380)
add_month_axis(fig_payment, ref_start, max_months_all, min_date_all, max_date_all)
st.plotly_chart(fig_payment, use_container_width=True)

# --- Total cash outlay ---
st.subheader("Total cash outlay over time")
st.caption(
    "Cumulative cash spent: mortgage payments, plus (if included above) your deposit and upfront costs at the "
    "point they occur."
)
fig_outlay = go.Figure()
for i, s in enumerate(active):
    df = schedules[s.name].copy()
    color = PALETTE[i % len(PALETTE)]
    df["CumPayment"] = df["Payment"].cumsum()
    if include_upfront:
        upfront_cum = cumulative_upfront(list(df["Date"]), s.upfront_costs)
        df["Outlay"] = s.deposit + upfront_cum + df["CumPayment"]
    else:
        df["Outlay"] = df["CumPayment"]
    fig_outlay.add_trace(go.Scatter(x=df["Date"], y=df["Outlay"], mode="lines", name=s.name, line=dict(color=color)))

    if include_upfront and (s.deposit or s.upfront_costs):
        event_dates = [date.fromisoformat(s.start_date)] if s.deposit else []
        event_amts = [s.deposit] if s.deposit else []
        event_labels = ["Deposit"] if s.deposit else []
        for cname, camt, cdate in s.upfront_costs:
            event_dates.append(date.fromisoformat(cdate))
            event_amts.append(camt)
            event_labels.append(cname)
        marker_y = cumulative_upfront(
            event_dates, s.upfront_costs + ([["__deposit__", s.deposit, s.start_date]] if s.deposit else [])
        )
        fig_outlay.add_trace(
            go.Scatter(
                x=[pd.Timestamp(d) for d in event_dates],
                y=marker_y,
                mode="markers",
                marker=dict(color=color, size=9, symbol="diamond"),
                name=f"{s.name}: upfront events",
                text=[f"{lbl}: {CUR}{amt:,.0f}" for lbl, amt in zip(event_labels, event_amts)],
                hovertemplate="%{text}<extra></extra>",
                showlegend=False,
            )
        )
fig_outlay.update_layout(yaxis_title=f"Cumulative cash outlay ({CUR})", xaxis_title="Date", height=420)
add_month_axis(fig_outlay, ref_start, max_months_all, min_date_all, max_date_all)
st.plotly_chart(fig_outlay, use_container_width=True)

# --- Yearly interest paid ---
st.subheader("Interest paid per year")
st.caption("How much of each calendar year's payments went purely to interest (the cost of borrowing), not principal.")
fig_yearly = go.Figure()
for s in active:
    y = yearly_stats(schedules[s.name])
    fig_yearly.add_trace(go.Bar(x=y["Year"], y=y["Interest"], name=s.name))
fig_yearly.update_layout(barmode="group", yaxis_title=f"Interest ({CUR})", xaxis_title="Year", height=380)
st.plotly_chart(fig_yearly, use_container_width=True)

# --- Cumulative interest vs principal ---
st.subheader("Cumulative interest vs principal repaid")
st.caption(
    "How your total payments split between interest (the lender's charge for borrowing) and principal "
    "(the loan amount you're paying back — i.e. the equity you're buying back)."
)
fig_cum = go.Figure()
for s in active:
    df = schedules[s.name].copy()
    df["Cum Interest"] = df["Interest"].cumsum()
    df["Cum Principal"] = df["Principal"].cumsum()
    fig_cum.add_trace(go.Scatter(x=df["Date"], y=df["Cum Interest"], mode="lines", name=f"{s.name} – interest"))
    fig_cum.add_trace(
        go.Scatter(x=df["Date"], y=df["Cum Principal"], mode="lines", name=f"{s.name} – principal", line=dict(dash="dot"))
    )
fig_cum.update_layout(yaxis_title=f"Cumulative {CUR}", xaxis_title="Date", height=420)
add_month_axis(fig_cum, ref_start, max_months_all, min_date_all, max_date_all)
st.plotly_chart(fig_cum, use_container_width=True)

# --- Month-by-month table ---
st.subheader("Month-by-month schedule")
sel_scenario = st.selectbox("Scenario", [s.name for s in active])
df_show = schedules[sel_scenario].copy()
df_show["Date"] = df_show["Date"].astype(str)
for c in ["ScheduledPayment", "Payment", "Interest", "Principal", "LumpSum", "Balance"]:
    df_show[c] = df_show[c].round(2)
st.dataframe(df_show, use_container_width=True, height=400)

st.download_button(
    f"⬇️ Download {sel_scenario} schedule (CSV)",
    data=df_show.to_csv(index=False),
    file_name=f"{sel_scenario.replace(' ', '_')}_schedule.csv",
    mime="text/csv",
)
