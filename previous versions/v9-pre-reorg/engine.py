"""Shared mortgage-calculation engine and small UI helpers used by both app.py (v1) and app_v2.py."""

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

GLOSSARY = {
    "Principal": "The amount you borrow (and still owe) from the lender. Interest is calculated on this "
    "outstanding balance each period — pay it down faster and you pay less interest overall.",
    "Interest": "The lender's charge for lending you the principal, calculated on the outstanding balance "
    "each period. This is the actual cost of borrowing.",
    "Deposit": "Cash you put in upfront from your own savings. It reduces how much you need to borrow but "
    "isn't part of the loan itself, so it never accrues mortgage interest.",
    "Term": "How long you have to repay the loan in full, e.g. 25 years.",
    "Overpayment": "Extra money paid on top of the required monthly payment, applied entirely to principal.",
    "Lump sum": "A one-off extra payment applied to the balance in a specific month, e.g. a bonus or inheritance.",
    "Amortization": "Paying off a loan through scheduled payments that cover both interest and principal, so "
    "the balance reaches exactly zero by the end of the term.",
    "Upfront costs": "One-off costs like stamp duty, legal fees, or surveys — real cash spent that isn't part "
    "of the loan.",
    "Balance": "The outstanding principal you still owe at a given point in time.",
    "Offset": "A savings balance held alongside the mortgage that is netted off the loan balance before "
    "interest is calculated, without the savings actually being used to repay the loan.",
    "APR": "Annual Percentage Rate — the cost of a loan per year including most fees, expressed as a single "
    "rate, meant for comparing deals on a like-for-like basis.",
    "ERC": "Early Repayment Charge — a fee some lenders charge for leaving a fixed or discounted deal before "
    "it ends, usually a percentage of the remaining balance.",
    "Income multiple": "How many times your annual income a lender will typically offer as a mortgage, e.g. "
    "4.5× combined income.",
}


def gterm(word: str, key: str | None = None) -> str:
    """Inline HTML span: dotted-underline word with an instant hover tooltip."""
    definition = GLOSSARY[key or word]
    return f'<span class="gterm">{word}<span class="gtip">{definition}</span></span>'


def caption_html(html: str):
    st.markdown(f'<div class="capline">{html}</div>', unsafe_allow_html=True)


def inject_glossary_css():
    st.markdown(
        """
        <style>
        .gterm { border-bottom: 1px dotted #808495; cursor: help; position: relative; font-weight: inherit; }
        .gterm .gtip {
          visibility: hidden; opacity: 0; position: absolute; z-index: 999;
          top: 130%; left: 0; width: 260px; background: #31333f; color: #fff;
          padding: 8px 10px; border-radius: 6px; font-size: 12.5px; line-height: 1.4;
          transition: opacity .1s; font-weight: normal; pointer-events: none;
        }
        .gterm:hover .gtip { visibility: visible; opacity: 1; }
        .capline { color: #808495; font-size: 14px; margin: -8px 0 10px 0; line-height: 1.5; }
        </style>
        """,
        unsafe_allow_html=True,
    )


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
    interest_only: bool = False,
) -> pd.DataFrame:
    rate_changes = sorted(rate_changes or [])
    rate_map = dict(rate_changes)
    lump_map: dict[int, float] = {}
    for m, amt in (lump_sums or []):
        lump_map[m] = lump_map.get(m, 0.0) + amt

    balance = principal
    current_rate = annual_rate_pct
    remaining_months = term_months
    payment = 0.0 if interest_only else monthly_payment(balance, current_rate, remaining_months)

    rows = []
    month_idx = 0

    while balance > 0.01 and month_idx < term_months * 3:  # hard safety cap
        month_idx += 1

        # apply a rate change effective this month -> re-amortize over remaining term
        if month_idx in rate_map:
            current_rate = rate_map[month_idx]
            remaining_months = term_months - month_idx + 1
            if not interest_only:
                payment = monthly_payment(balance, current_rate, remaining_months)

        period_date = add_months(start_date, month_idx)

        if method == "daily_actual":
            days = monthrange(period_date.year, period_date.month)[1]
            interest = balance * (current_rate / 100 / 365) * days
        else:
            interest = balance * (current_rate / 100 / 12)

        if interest_only:
            # interest-only: pay just the interest each month; principal only clears on the final month
            is_last_month = month_idx >= term_months
            lump_sum_amt = lump_map.get(month_idx, 0.0)
            scheduled_payment = interest
            principal_paid = balance if is_last_month else 0.0
            principal_paid = min(principal_paid + lump_sum_amt + extra_payment, balance)
            total_payment = interest + principal_paid
            balance -= principal_paid
            rows.append(
                {
                    "Month": month_idx, "Date": period_date, "Rate (%)": current_rate,
                    "ScheduledPayment": scheduled_payment, "Payment": total_payment,
                    "Interest": interest, "Principal": principal_paid, "LumpSum": lump_sum_amt, "Balance": balance,
                }
            )
            if balance <= 0:
                break
            continue

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


def build_offset_schedule(
    principal: float,
    annual_rate_pct: float,
    term_months: int,
    start_date: date,
    offset_balance: float,
    method: str = "monthly",
) -> pd.DataFrame:
    """Like build_schedule, but interest each month is charged on (balance - offset_balance), while the
    payment stays fixed at the original (non-offset) required payment — so any interest saved goes straight
    toward paying down the balance faster."""
    balance = principal
    payment = monthly_payment(principal, annual_rate_pct, term_months)
    rows = []
    month_idx = 0
    while balance > 0.01 and month_idx < term_months * 3:
        month_idx += 1
        period_date = add_months(start_date, month_idx)
        netted = max(balance - offset_balance, 0.0)
        if method == "daily_actual":
            days = monthrange(period_date.year, period_date.month)[1]
            interest = netted * (annual_rate_pct / 100 / 365) * days
        else:
            interest = netted * (annual_rate_pct / 100 / 12)
        principal_paid = payment - interest
        if principal_paid >= balance:
            principal_paid = balance
            payment_this_month = principal_paid + interest
            balance = 0.0
        else:
            balance -= principal_paid
            payment_this_month = payment
        rows.append({
            "Month": month_idx, "Date": period_date, "Interest": interest,
            "Principal": principal_paid, "Payment": payment_this_month, "Balance": balance,
        })
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
        "total_lump_sums": df["LumpSum"].sum() if "LumpSum" in df.columns else 0,
    }


def yearly_stats(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Year", "Interest", "Principal", "Payment", "MeanPayment", "MeanInterest", "MeanPrincipal", "Months"])
    d = df.copy()
    d["Year"] = pd.to_datetime(d["Date"]).dt.year
    g = d.groupby("Year").agg(
        Interest=("Interest", "sum"),
        Principal=("Principal", "sum"),
        Payment=("Payment", "sum"),
        MeanPayment=("Payment", "mean"),
        MeanInterest=("Interest", "mean"),
        MeanPrincipal=("Principal", "mean"),
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

    # an invisible trace bound to xaxis2 is required for Plotly to actually render the
    # secondary axis; an all-None y series contributes nothing to the y-axis autorange
    fig.add_trace(
        go.Scatter(
            x=tickvals, y=[None] * len(tickvals), xaxis="x2",
            mode="markers", marker=dict(opacity=0), showlegend=False, hoverinfo="skip",
        )
    )
    fig.update_layout(
        xaxis=dict(range=[pd.Timestamp(min_date), pd.Timestamp(max_date)], fixedrange=True),
        xaxis2=dict(
            overlaying="x",
            side="top",
            anchor="y",
            range=[pd.Timestamp(min_date), pd.Timestamp(max_date)],
            tickmode="array",
            tickvals=tickvals,
            ticktext=ticktext,
            title=dict(text="Months since start", font=dict(size=11)),
            showgrid=False,
            fixedrange=True,
        ),
    )


# ---------------------------------------------------------------------------
# Scenario data model (used by the v1 projection dashboard)
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


def save_session(scenarios: list[Scenario], path: Path):
    path.write_text(json.dumps([asdict(s) for s in scenarios], indent=2))


def load_session(path: Path) -> list[Scenario]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [Scenario(**s) for s in data]
