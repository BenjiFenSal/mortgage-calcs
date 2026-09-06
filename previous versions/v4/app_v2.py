from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import (
    CURRENCY_OPTIONS, gterm, inject_glossary_css, stepper,
    build_schedule, build_offset_schedule, monthly_payment, summarize, add_month_axis, add_months,
)

st.set_page_config(page_title="Mortgage Calculators", layout="wide", initial_sidebar_state="collapsed")
inject_glossary_css()

PRIMARY = "#3f51b5"
PRIMARY_DARK = "#303f9f"
ACCENT = "#ff4081"

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');
    html, body, [class*="css"] {{ font-family: 'Roboto', -apple-system, BlinkMacSystemFont, sans-serif; }}
    .stApp {{ background: #f4f5f9; }}
    div[data-testid="stVerticalBlockBorderWrapper"] > div {{ border-radius: 10px; }}
    div[data-testid="stVerticalBlockBorderWrapper"] {{
        background: #ffffff; border-radius: 10px !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.09), 0 1px 2px rgba(0,0,0,0.06);
        border: 1px solid #e8e9ee !important;
    }}
    .stButton button {{
        border-radius: 6px; font-weight: 500; letter-spacing: .15px;
        transition: box-shadow .15s ease, transform .05s ease;
    }}
    .stButton button:hover {{ transform: translateY(-1px); }}
    .stButton button[kind="primary"] {{
        background: {PRIMARY}; border-color: {PRIMARY}; box-shadow: 0 2px 5px rgba(63,81,181,0.35);
    }}
    .stButton button[kind="primary"]:hover {{ background: {PRIMARY_DARK}; border-color: {PRIMARY_DARK}; }}
    [data-testid="stMetricValue"] {{ color: {PRIMARY_DARK}; font-weight: 700; }}
    [data-testid="stMetricLabel"] {{ color: #6b6f76; font-weight: 500; }}
    h1, h2, h3, h4 {{ font-weight: 500 !important; color: #202124; }}
    .verdict-card {{
        background: linear-gradient(135deg, {PRIMARY} 0%, {PRIMARY_DARK} 100%);
        color: #fff; border-radius: 10px; padding: 18px 22px; margin: 10px 0;
        box-shadow: 0 3px 10px rgba(63,81,181,0.35);
    }}
    .verdict-card b {{ font-size: 1.15em; }}
    .mini-label {{ color: #6b6f76; font-size: 13px; font-weight: 500; margin-bottom: 2px; }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.session_state.setdefault("calc", None)
st.session_state.setdefault("currency_choice", "£ British Pound (GBP)")

CALCULATORS = [
    ("basic", "🏠  Basic mortgage calculator", "Monthly repayments, interest-only vs repayment, and total cost."),
    ("compare2", "⚖️  Compare two mortgages", "Put two deals side by side and see which wins overall."),
    ("overpay", "💷  Overpayment calculator", "See how extra monthly payments cut your term and interest."),
    ("offset", "🔄  Offset mortgage vs savings", "Is offsetting your savings better than keeping them separate?"),
    ("deposit", "🐷  Saving for a deposit", "How long until you reach your deposit target?"),
    ("comparefixed", "📊  Compare fixed rate mortgages", "Factor in fees & cashback to find the true cheapest deal."),
    ("ditchfix", "🚪  Ditch your fix", "Is it worth an exit fee to remortgage onto a better rate now?"),
    ("borrow", "🧮  How much can I borrow", "Estimate your borrowing power from income multiples."),
]
CALC_TITLES = {k: t.strip() for k, t, _ in CALCULATORS}


def money_input(label, value, key, step=1000, decimals=0, help=None, min_value=0):
    cur = CURRENCY_OPTIONS[st.session_state.currency_choice]
    return stepper(label, value, step=step, min_value=min_value, decimals=decimals, prefix=cur,
                    thousands=True, help=help, key=key)


def fmt(x):
    cur = CURRENCY_OPTIONS[st.session_state.currency_choice]
    return f"{cur}{x:,.0f}"


# ---------------------------------------------------------------------------
# Home: choose a calculator
# ---------------------------------------------------------------------------

def render_home():
    st.markdown(
        """<style>
        .stButton button { min-height: 82px !important; text-align: left !important;
            font-size: 15.5px !important; font-weight: 500 !important; padding: 14px 18px !important; }
        </style>""",
        unsafe_allow_html=True,
    )
    st.title("🏡 Mortgage Calculators")
    st.caption("Eight focused tools for the numbers that matter when you're buying or remortgaging.")
    st.markdown("###### Choose a calculator")
    cols = st.columns(4)
    for i, (key, label, desc) in enumerate(CALCULATORS):
        with cols[i % 4]:
            if st.button(label, key=f"card_{key}", use_container_width=True):
                st.session_state.calc = key
                st.rerun()
            st.caption(desc)


def render_topbar(key):
    c1, c2, c3 = st.columns([5, 2, 1.4])
    with c1:
        st.markdown(f"## {CALC_TITLES[key]}")
    with c2:
        st.session_state.currency_choice = st.selectbox(
            "Currency", list(CURRENCY_OPTIONS.keys()),
            index=list(CURRENCY_OPTIONS.keys()).index(st.session_state.currency_choice),
            label_visibility="collapsed",
        )
    with c3:
        st.write("")
        if st.button("← All calculators", use_container_width=True):
            st.session_state.calc = None
            st.rerun()
    st.divider()


# ---------------------------------------------------------------------------
# 1. Basic mortgage calculator
# ---------------------------------------------------------------------------

def calc_basic():
    left, right = st.columns([1, 1.5], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("#### Your mortgage")
            loan = money_input(f"Mortgage amount ({CURRENCY_OPTIONS[st.session_state.currency_choice]})", 250_000, "b_loan", step=1000,
                                help="The principal: the amount you're borrowing (and will still owe). Interest is "
                                "charged on this outstanding balance each period.")
            term = st.slider("Term (years)", 1, 40, 25, key="b_term")
            rate = stepper("Interest rate (%)", 4.5, step=0.05, min_value=0, max_value=25, decimals=2, suffix="%", key="b_rate")
            mtype = st.radio("Mortgage type", ["Repayment", "Interest-only"], key="b_type", horizontal=True,
                              help="Repayment: each payment clears some interest and some principal, so the balance reaches zero by the end. "
                                   "Interest-only: payments cover interest only — you still owe the full amount at the end.")
            fee = money_input(f"Product fee ({CURRENCY_OPTIONS[st.session_state.currency_choice]})", 0, "b_fee", step=50)
            add_fee = st.checkbox("Add fee to the loan (rather than pay upfront)", key="b_addfee")

    principal = loan + fee if add_fee else loan
    df = build_schedule(principal, rate, term * 12, date.today(), method="daily_actual",
                         interest_only=(mtype == "Interest-only"))
    summ = summarize(df)
    upfront_fee = 0 if add_fee else fee
    total_repayable = summ["total_paid"] + upfront_fee

    with right:
        with st.container(border=True):
            st.markdown("#### Results")
            m1, m2, m3 = st.columns(3)
            m1.metric("Monthly payment", fmt(df.iloc[0]["Payment"]))
            m2.metric("Total interest", fmt(summ["total_interest"]))
            m3.metric("Total amount repayable", fmt(total_repayable),
                       help="Every payment over the full term, plus the fee (whether added to the loan or paid upfront).")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df["Date"], y=df["Balance"], mode="lines", line=dict(color=PRIMARY, width=2.5)))
            fig.update_layout(height=280, margin=dict(t=10, b=10, l=10, r=10),
                               yaxis_title=f"Balance ({CURRENCY_OPTIONS[st.session_state.currency_choice]})",
                               xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
            st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# 2. Compare two mortgages
# ---------------------------------------------------------------------------

def _deal_inputs(label, key_prefix, defaults):
    with st.container(border=True):
        st.markdown(f"#### {label}")
        loan = money_input(f"Mortgage amount ({CURRENCY_OPTIONS[st.session_state.currency_choice]})", defaults[0], f"{key_prefix}_loan", step=1000)
        term = st.slider("Term (years)", 1, 40, defaults[1], key=f"{key_prefix}_term")
        rate = stepper("Interest rate (%)", defaults[2], step=0.05, min_value=0, max_value=25, decimals=2, suffix="%", key=f"{key_prefix}_rate")
        fee = money_input(f"Product fee ({CURRENCY_OPTIONS[st.session_state.currency_choice]})", defaults[3], f"{key_prefix}_fee", step=50)
    return loan, term, rate, fee


def calc_compare_two():
    c1, c2 = st.columns(2, gap="large")
    with c1:
        loan_a, term_a, rate_a, fee_a = _deal_inputs("Deal A", "cmp_a", (250_000, 25, 4.5, 999))
    with c2:
        loan_b, term_b, rate_b, fee_b = _deal_inputs("Deal B", "cmp_b", (250_000, 25, 4.2, 1499))

    df_a = build_schedule(loan_a, rate_a, term_a * 12, date.today(), method="daily_actual")
    df_b = build_schedule(loan_b, rate_b, term_b * 12, date.today(), method="daily_actual")
    total_a = summarize(df_a)["total_paid"] + fee_a
    total_b = summarize(df_b)["total_paid"] + fee_b

    with st.container(border=True):
        st.markdown("#### Comparison")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Deal A — monthly", fmt(df_a.iloc[0]["Payment"]))
        m2.metric("Deal B — monthly", fmt(df_b.iloc[0]["Payment"]))
        m3.metric("Deal A — total cost", fmt(total_a))
        m4.metric("Deal B — total cost", fmt(total_b))

        cheaper = "A" if total_a < total_b else "B"
        diff = abs(total_a - total_b)
        st.markdown(
            f'<div class="verdict-card">💡 <b>Deal {cheaper} is cheaper overall</b> by {fmt(diff)} '
            f'across the full term (including fees).</div>',
            unsafe_allow_html=True,
        )
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df_a["Date"], y=df_a["Balance"], mode="lines", name="Deal A", line=dict(color=PRIMARY, width=2.5)))
        fig.add_trace(go.Scatter(x=df_b["Date"], y=df_b["Balance"], mode="lines", name="Deal B", line=dict(color=ACCENT, width=2.5)))
        fig.update_layout(height=300, margin=dict(t=10, b=10, l=10, r=10),
                           yaxis_title=f"Balance ({CURRENCY_OPTIONS[st.session_state.currency_choice]})",
                           xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
        st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# 3. Overpayment calculator
# ---------------------------------------------------------------------------

def calc_overpayment():
    left, right = st.columns([1, 1.5], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("#### Your mortgage")
            loan = money_input(f"Mortgage amount ({CURRENCY_OPTIONS[st.session_state.currency_choice]})", 250_000, "ov_loan", step=1000)
            term = st.slider("Term (years)", 1, 40, 25, key="ov_term")
            rate = stepper("Interest rate (%)", 4.5, step=0.05, min_value=0, max_value=25, decimals=2, suffix="%", key="ov_rate")
            overpay = money_input(f"Extra monthly overpayment ({CURRENCY_OPTIONS[st.session_state.currency_choice]})", 200, "ov_extra", step=50,
                                   help="Extra money paid on top of the required monthly payment, applied entirely to principal.")

    base = build_schedule(loan, rate, term * 12, date.today(), method="daily_actual")
    over = build_schedule(loan, rate, term * 12, date.today(), method="daily_actual", extra_payment=overpay)
    base_summ, over_summ = summarize(base), summarize(over)
    months_saved = base_summ["months"] - over_summ["months"]
    interest_saved = base_summ["total_interest"] - over_summ["total_interest"]

    with right:
        with st.container(border=True):
            st.markdown("#### Results")
            m1, m2, m3 = st.columns(3)
            m1.metric("Term shortened by", f"{months_saved // 12}y {months_saved % 12}m")
            m2.metric("Interest saved", fmt(interest_saved))
            m3.metric("New payoff date", over_summ["payoff_date"].isoformat() if over_summ["payoff_date"] else "—")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=base["Date"], y=base["Balance"], mode="lines", name="No overpayment", line=dict(color="#9aa0a6", width=2, dash="dot")))
            fig.add_trace(go.Scatter(x=over["Date"], y=over["Balance"], mode="lines", name="With overpayment", line=dict(color=PRIMARY, width=2.5)))
            fig.update_layout(height=300, margin=dict(t=10, b=10, l=10, r=10),
                               yaxis_title=f"Balance ({CURRENCY_OPTIONS[st.session_state.currency_choice]})",
                               xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
            st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# 4. Offset mortgage vs savings
# ---------------------------------------------------------------------------

def calc_offset():
    left, right = st.columns([1, 1.5], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("#### Your mortgage & savings")
            loan = money_input(f"Mortgage amount ({CURRENCY_OPTIONS[st.session_state.currency_choice]})", 250_000, "of_loan", step=1000)
            term = st.slider("Term (years)", 1, 40, 25, key="of_term")
            rate = stepper("Mortgage interest rate (%)", 4.5, step=0.05, min_value=0, max_value=25, decimals=2, suffix="%", key="of_rate")
            offset_bal = money_input(f"Savings held in the offset account ({CURRENCY_OPTIONS[st.session_state.currency_choice]})", 30_000, "of_savings", step=1000,
                                      help="A savings balance held alongside the mortgage that is netted off the loan balance "
                                      "before interest is calculated, without the savings actually being used to repay the loan.")
            savings_rate = stepper("Alternative savings account rate (%)", 3.0, step=0.1, min_value=0, max_value=15, decimals=2, suffix="%", key="of_srate",
                                    help="What you could earn if you kept this money in a separate savings account instead of offsetting it.")
            tax_rate = stepper("Tax on savings interest (%)", 20.0, step=1, min_value=0, max_value=60, decimals=0, suffix="%", key="of_tax",
                                help="Your marginal tax rate on savings interest — 0% if it's within an ISA or your Personal Savings Allowance.")

    base = build_schedule(loan, rate, term * 12, date.today(), method="daily_actual")
    off = build_offset_schedule(loan, rate, term * 12, date.today(), offset_balance=offset_bal, method="daily_actual")
    base_summ, off_summ = summarize(base), summarize(off)
    interest_saved = base_summ["total_interest"] - off_summ["total_interest"]
    months_saved = base_summ["months"] - off_summ["months"]
    breakeven_rate = rate / (1 - tax_rate / 100) if tax_rate < 100 else float("inf")

    with right:
        with st.container(border=True):
            st.markdown("#### Results")
            m1, m2, m3 = st.columns(3)
            m1.metric("Interest saved by offsetting", fmt(interest_saved))
            m2.metric("Term shortened by", f"{months_saved // 12}y {months_saved % 12}m")
            m3.metric("Break-even savings rate", f"{breakeven_rate:.2f}%",
                       help="A separate savings account would need to earn more than this (before tax) to beat offsetting.")
            st.markdown(
                f'<div class="verdict-card">💡 Offsetting is equivalent to a guaranteed, tax-free return of '
                f'<b>{rate:.2f}%</b> on your savings. Elsewhere you\'d need to earn more than '
                f'<b>{breakeven_rate:.2f}%</b> before tax (at a {tax_rate:.0f}% tax rate) to do better.</div>',
                unsafe_allow_html=True,
            )
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=base["Date"], y=base["Balance"], mode="lines", name="No offset", line=dict(color="#9aa0a6", width=2, dash="dot")))
            fig.add_trace(go.Scatter(x=off["Date"], y=off["Balance"], mode="lines", name="Offset", line=dict(color=PRIMARY, width=2.5)))
            fig.update_layout(height=260, margin=dict(t=10, b=10, l=10, r=10),
                               yaxis_title=f"Balance ({CURRENCY_OPTIONS[st.session_state.currency_choice]})",
                               xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
            st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# 5. Saving for a deposit
# ---------------------------------------------------------------------------

def calc_deposit():
    left, right = st.columns([1, 1.5], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("#### Your savings plan")
            target = money_input(f"Deposit target ({CURRENCY_OPTIONS[st.session_state.currency_choice]})", 40_000, "dp_target", step=1000)
            current = money_input(f"Current savings ({CURRENCY_OPTIONS[st.session_state.currency_choice]})", 5_000, "dp_current", step=500)
            monthly = money_input(f"Monthly saving ({CURRENCY_OPTIONS[st.session_state.currency_choice]})", 500, "dp_monthly", step=50)
            rate = stepper("Savings interest rate (%)", 3.0, step=0.1, min_value=0, max_value=15, decimals=2, suffix="%", key="dp_rate")

    balances = [current]
    months = 0
    balance = current
    reached = balance >= target
    while not reached and months < 600:
        months += 1
        balance = balance * (1 + rate / 100 / 12) + monthly
        balances.append(balance)
        reached = balance >= target

    with right:
        with st.container(border=True):
            st.markdown("#### Results")
            if reached:
                years, rem_months = divmod(months, 12)
                target_date = add_months(date.today(), months)
                m1, m2, m3 = st.columns(3)
                m1.metric("Time to reach target", f"{years}y {rem_months}m")
                m2.metric("Target date", target_date.isoformat())
                m3.metric("Total you'll have saved", fmt(monthly * months))
            else:
                st.warning("At this rate you won't reach your target within 50 years — try a higher monthly saving.")
            dates = [add_months(date.today(), m) for m in range(len(balances))]
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=dates, y=balances, mode="lines", line=dict(color=PRIMARY, width=2.5), fill="tozeroy", fillcolor="rgba(63,81,181,0.10)"))
            fig.add_hline(y=target, line_dash="dash", line_color=ACCENT, annotation_text="Target")
            fig.update_layout(height=300, margin=dict(t=10, b=10, l=10, r=10),
                               yaxis_title=f"Savings ({CURRENCY_OPTIONS[st.session_state.currency_choice]})",
                               xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
            st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# 6. Compare fixed rate mortgages
# ---------------------------------------------------------------------------

def _fixed_deal_inputs(label, key_prefix, defaults):
    with st.container(border=True):
        st.markdown(f"#### {label}")
        rate = stepper("Interest rate (%)", defaults[0], step=0.05, min_value=0, max_value=25, decimals=2, suffix="%", key=f"{key_prefix}_rate")
        fixed_years = stepper("Fixed period (years)", defaults[1], step=1, min_value=1, max_value=10, decimals=0, suffix=" yrs", key=f"{key_prefix}_fixed")
        fee = money_input(f"Product fee ({CURRENCY_OPTIONS[st.session_state.currency_choice]})", defaults[2], f"{key_prefix}_fee", step=50)
        add_fee = st.checkbox("Add fee to the loan", key=f"{key_prefix}_addfee")
        cashback = money_input(f"Cashback offered ({CURRENCY_OPTIONS[st.session_state.currency_choice]})", defaults[3], f"{key_prefix}_cashback", step=50)
    return rate, int(fixed_years), fee, add_fee, cashback


def calc_compare_fixed():
    with st.container(border=True):
        st.markdown("#### Shared loan details")
        sc1, sc2 = st.columns(2)
        with sc1:
            loan = money_input(f"Mortgage amount ({CURRENCY_OPTIONS[st.session_state.currency_choice]})", 250_000, "cf_loan", step=1000)
        with sc2:
            term = st.slider("Full mortgage term (years)", 1, 40, 25, key="cf_term")

    c1, c2 = st.columns(2, gap="large")
    with c1:
        rate_a, fixed_a, fee_a, addfee_a, cashback_a = _fixed_deal_inputs("Deal A", "cf_a", (4.5, 2, 999, 0))
    with c2:
        rate_b, fixed_b, fee_b, addfee_b, cashback_b = _fixed_deal_inputs("Deal B", "cf_b", (4.2, 5, 1499, 250))

    principal_a = loan + fee_a if addfee_a else loan
    principal_b = loan + fee_b if addfee_b else loan
    df_a = build_schedule(principal_a, rate_a, term * 12, date.today(), method="daily_actual")
    df_b = build_schedule(principal_b, rate_b, term * 12, date.today(), method="daily_actual")
    months_a = min(fixed_a * 12, len(df_a))
    months_b = min(fixed_b * 12, len(df_b))
    paid_a = df_a.iloc[:months_a]["Payment"].sum() + (0 if addfee_a else fee_a) - cashback_a
    paid_b = df_b.iloc[:months_b]["Payment"].sum() + (0 if addfee_b else fee_b) - cashback_b

    with st.container(border=True):
        st.markdown("#### Comparison over each fixed period")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Deal A — monthly", fmt(df_a.iloc[0]["Payment"]))
        m2.metric("Deal B — monthly", fmt(df_b.iloc[0]["Payment"]))
        m3.metric(f"Deal A — true cost ({fixed_a}y)", fmt(paid_a))
        m4.metric(f"Deal B — true cost ({fixed_b}y)", fmt(paid_b))
        cheaper = "A" if paid_a < paid_b else "B"
        st.markdown(
            f'<div class="verdict-card">💡 <b>Deal {cheaper} costs less</b> over its own fixed period once '
            f'fees and cashback are accounted for — but remember the fixed periods are different lengths, '
            f'so also compare what rate you might face after each one ends.</div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# 7. Ditch your fix
# ---------------------------------------------------------------------------

def calc_ditch_fix():
    left, right = st.columns([1, 1.5], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("#### Your current deal")
            balance = money_input(f"Remaining balance ({CURRENCY_OPTIONS[st.session_state.currency_choice]})", 220_000, "df_balance", step=1000)
            remaining_term = stepper("Remaining overall term (years)", 22.0, step=0.5, min_value=1, max_value=40, decimals=1, suffix=" yrs", key="df_remterm")
            months_left = stepper("Months left on current fix", 8, step=1, min_value=1, max_value=60, decimals=0, key="df_monthsleft")
            current_rate = stepper("Current rate (%)", 5.5, step=0.05, min_value=0, max_value=25, decimals=2, suffix="%", key="df_crate")
            erc_pct = stepper("Early repayment charge (%)", 3.0, step=0.25, min_value=0, max_value=15, decimals=2, suffix="%", key="df_erc",
                               help="A fee some lenders charge for leaving a fixed or discounted deal before it ends, "
                               "usually a percentage of the remaining balance.")
        with st.container(border=True):
            st.markdown("#### The new deal")
            new_rate = stepper("New rate (%)", 4.3, step=0.05, min_value=0, max_value=25, decimals=2, suffix="%", key="df_nrate")
            new_fees = money_input(f"New deal fees ({CURRENCY_OPTIONS[st.session_state.currency_choice]})", 999, "df_nfees", step=50)

    months_left = int(months_left)
    stay = build_schedule(balance, current_rate, int(remaining_term * 12), date.today(), method="daily_actual")
    switch = build_schedule(balance, new_rate, int(remaining_term * 12), date.today(), method="daily_actual")
    stay_cost = stay.iloc[:months_left]["Interest"].sum()
    switch_cost = switch.iloc[:months_left]["Interest"].sum() + balance * erc_pct / 100 + new_fees
    saving = stay_cost - switch_cost

    with right:
        with st.container(border=True):
            st.markdown("#### Results — over the remaining fixed period")
            m1, m2, m3 = st.columns(3)
            m1.metric("Cost if you stay", fmt(stay_cost))
            m2.metric("Cost if you switch now", fmt(switch_cost),
                       help="Interest at the new rate for the remaining months, plus the early repayment charge and new fees.")
            m3.metric("Net saving by switching", fmt(saving))
            verdict = "switching now looks worth it" if saving > 0 else "it's cheaper to stay put until the fix ends"
            st.markdown(
                f'<div class="verdict-card">💡 Based on these numbers, <b>{verdict}</b> — '
                f'{"you save" if saving > 0 else "you\'d lose"} {fmt(abs(saving))} over the remaining '
                f'{months_left} months.</div>',
                unsafe_allow_html=True,
            )
            fig = go.Figure()
            fig.add_trace(go.Bar(x=["Stay", "Switch now"], y=[stay_cost, switch_cost], marker_color=[ "#9aa0a6", PRIMARY]))
            fig.update_layout(height=260, margin=dict(t=10, b=10, l=10, r=10),
                               yaxis_title=f"Cost over remaining fix ({CURRENCY_OPTIONS[st.session_state.currency_choice]})",
                               xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
            st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# 8. How much can I borrow
# ---------------------------------------------------------------------------

def calc_borrow():
    left, right = st.columns([1, 1.5], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("#### Your income")
            income1 = money_input(f"Applicant 1 annual income ({CURRENCY_OPTIONS[st.session_state.currency_choice]})", 40_000, "hb_inc1", step=1000)
            income2 = money_input(f"Applicant 2 annual income ({CURRENCY_OPTIONS[st.session_state.currency_choice]}, 0 if none)", 0, "hb_inc2", step=1000)
            multiple = stepper("Income multiple", 4.5, step=0.1, min_value=2.5, max_value=6, decimals=1, suffix="×", key="hb_mult",
                                help="How many times your annual income a lender will typically offer as a mortgage, "
                                "e.g. 4.5× combined income.")
            deposit = money_input(f"Deposit available ({CURRENCY_OPTIONS[st.session_state.currency_choice]})", 30_000, "hb_dep", step=1000)

    max_loan = (income1 + income2) * multiple
    max_price = max_loan + deposit

    with right:
        with st.container(border=True):
            st.markdown("#### Results")
            m1, m2, m3 = st.columns(3)
            m1.metric("Estimated max loan", fmt(max_loan))
            m2.metric("Plus your deposit", fmt(deposit))
            m3.metric("Estimated max property price", fmt(max_price))
            fig = go.Figure()
            fig.add_trace(go.Bar(y=["Property price"], x=[max_loan], name="Loan", orientation="h", marker_color=PRIMARY))
            fig.add_trace(go.Bar(y=["Property price"], x=[deposit], name="Deposit", orientation="h", marker_color=ACCENT))
            fig.update_layout(barmode="stack", height=160, margin=dict(t=10, b=10, l=10, r=10),
                               xaxis_title=f"({CURRENCY_OPTIONS[st.session_state.currency_choice]})",
                               xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
            st.plotly_chart(fig, use_container_width=True)
            st.caption("This is a rough guide only — actual affordability depends on the lender's own "
                       "stress tests, your outgoings, credit history, and other debts.")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

CALC_FUNCS = {
    "basic": calc_basic,
    "compare2": calc_compare_two,
    "overpay": calc_overpayment,
    "offset": calc_offset,
    "deposit": calc_deposit,
    "comparefixed": calc_compare_fixed,
    "ditchfix": calc_ditch_fix,
    "borrow": calc_borrow,
}

if st.session_state.calc is None:
    render_home()
else:
    render_topbar(st.session_state.calc)
    CALC_FUNCS[st.session_state.calc]()
