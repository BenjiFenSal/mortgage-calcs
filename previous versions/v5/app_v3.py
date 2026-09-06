import copy
import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import (
    CURRENCY_OPTIONS, GLOSSARY, inject_glossary_css, stepper,
    build_schedule, build_offset_schedule, summarize, add_months,
)

SESSIONS_FILE = Path(__file__).parent / "sessions" / "v3_sessions.json"
SESSIONS_FILE.parent.mkdir(exist_ok=True)

st.set_page_config(page_title="Mortgage Dashboard", layout="wide", initial_sidebar_state="collapsed")
inject_glossary_css()

PRIMARY = "#3f51b5"
PRIMARY_DARK = "#303f9f"
ACCENT = "#ff4081"

SVG_CONFIG = {"toImageButtonOptions": {"format": "svg", "filename": "mortgage_chart", "scale": 1}, "displaylogo": False}

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');
    html, body, [class*="css"] {{ font-family: 'Roboto', -apple-system, BlinkMacSystemFont, sans-serif; }}
    .stApp {{ background: #f4f5f9; }}
    div[data-testid="stVerticalBlockBorderWrapper"] {{
        background: #ffffff; border-radius: 10px !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.09), 0 1px 2px rgba(0,0,0,0.06);
        border: 1px solid #e8e9ee !important;
    }}
    .stButton button {{ border-radius: 6px; font-weight: 500; letter-spacing: .15px; }}
    .stButton button[kind="primary"] {{ background: {PRIMARY}; border-color: {PRIMARY}; }}
    .stButton button[kind="primary"]:hover {{ background: {PRIMARY_DARK}; border-color: {PRIMARY_DARK}; }}
    [data-testid="stMetricValue"] {{ color: {PRIMARY_DARK}; font-weight: 700; }}
    [data-testid="stMetricLabel"] {{ color: #6b6f76; font-weight: 500; }}
    h1, h2, h3, h4 {{ font-weight: 500 !important; color: #202124; }}
    .verdict-card {{
        background: linear-gradient(135deg, {PRIMARY} 0%, {PRIMARY_DARK} 100%);
        color: #fff; border-radius: 10px; padding: 16px 20px; margin: 8px 0;
        box-shadow: 0 3px 10px rgba(63,81,181,0.35);
    }}
    .module-title {{ display:flex; align-items:center; gap:8px; margin-bottom: 4px; }}
    .session-row {{ padding: 6px 0; border-bottom: 1px solid #eee; font-size: 13.5px; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Calculator registry & default state
# ---------------------------------------------------------------------------

CALC_META = [
    ("basic", "🏠", "Basic mortgage calculator"),
    ("compare2", "⚖️", "Compare two mortgages"),
    ("overpay", "💷", "Overpayment calculator"),
    ("offset", "🔄", "Offset mortgage vs savings"),
    ("deposit", "🐷", "Saving for a deposit"),
    ("comparefixed", "📊", "Compare fixed rate mortgages"),
    ("ditchfix", "🚪", "Ditch your fix"),
    ("borrow", "🧮", "How much can I borrow"),
]
CALC_LABELS = {k: f"{icon} {title}" for k, icon, title in CALC_META}
LABEL_TO_KEY = {v: k for k, v in CALC_LABELS.items()}

DEFAULT_STATE = {
    "basic": {"loan": 250_000, "term": 25, "rate": 4.5, "type": "Repayment", "fee": 0, "addfee": False},
    "compare2": {"a_loan": 250_000, "a_term": 25, "a_rate": 4.5, "a_fee": 999,
                 "b_loan": 250_000, "b_term": 25, "b_rate": 4.2, "b_fee": 1499},
    "overpay": {"loan": 250_000, "term": 25, "rate": 4.5, "extra": 200},
    "offset": {"loan": 250_000, "term": 25, "rate": 4.5, "savings": 30_000, "srate": 3.0, "tax": 20.0},
    "deposit": {"target": 40_000, "current": 5_000, "monthly": 500, "rate": 3.0},
    "comparefixed": {"loan": 250_000, "term": 25,
                      "a_rate": 4.5, "a_fixed": 2, "a_fee": 999, "a_addfee": False, "a_cashback": 0,
                      "b_rate": 4.2, "b_fixed": 5, "b_fee": 1499, "b_addfee": False, "b_cashback": 250},
    "ditchfix": {"balance": 220_000, "remterm": 22.0, "monthsleft": 8, "crate": 5.5, "erc": 3.0,
                 "nrate": 4.3, "nfees": 999},
    "borrow": {"inc1": 40_000, "inc2": 0, "mult": 4.5, "deposit": 30_000},
}

st.session_state.setdefault("gen", 0)
st.session_state.setdefault("state", copy.deepcopy(DEFAULT_STATE))
st.session_state.setdefault("currency_choice", "£ British Pound (GBP)")
st.session_state.setdefault("visible_calcs", [CALC_LABELS["basic"]])

GEN = st.session_state.gen


def sfield(calc, field):
    return st.session_state.state[calc][field]


def sset(calc, field, value):
    st.session_state.state[calc][field] = value


def CUR():
    return CURRENCY_OPTIONS[st.session_state.currency_choice]


def fmt(x):
    return f"{CUR()}{x:,.0f}"


def smoney(calc, field, label, step=1000, **kwargs):
    val = stepper(label, sfield(calc, field), step=step, min_value=0, decimals=0, prefix=CUR(),
                   thousands=True, key=f"{calc}_{field}_{GEN}", **kwargs)
    sset(calc, field, val)
    return val


def sstepper(calc, field, label, **kwargs):
    val = stepper(label, sfield(calc, field), key=f"{calc}_{field}_{GEN}", **kwargs)
    sset(calc, field, val)
    return val


def sslider(calc, field, label, **kwargs):
    val = st.slider(label, value=sfield(calc, field), key=f"{calc}_{field}_{GEN}", **kwargs)
    sset(calc, field, val)
    return val


def sradio(calc, field, label, options, **kwargs):
    cur_val = sfield(calc, field)
    idx = options.index(cur_val) if cur_val in options else 0
    val = st.radio(label, options, index=idx, key=f"{calc}_{field}_{GEN}", **kwargs)
    sset(calc, field, val)
    return val


def scheckbox(calc, field, label, **kwargs):
    val = st.checkbox(label, value=sfield(calc, field), key=f"{calc}_{field}_{GEN}", **kwargs)
    sset(calc, field, val)
    return val


def csv_button(df, filename, label="⬇️ CSV"):
    st.download_button(label, data=df.to_csv(index=False), file_name=filename, mime="text/csv",
                        key=f"csv_{filename}_{GEN}_{id(df)}")


# ---------------------------------------------------------------------------
# Session library (named saves, comments, load/delete, JSON export/import)
# ---------------------------------------------------------------------------

def load_all_sessions() -> list[dict]:
    if not SESSIONS_FILE.exists():
        return []
    return json.loads(SESSIONS_FILE.read_text())


def write_all_sessions(sessions: list[dict]):
    SESSIONS_FILE.write_text(json.dumps(sessions, indent=2))


def render_session_bar():
    with st.expander("💾 Sessions & settings", expanded=False):
        c1, c2 = st.columns([1, 3])
        with c1:
            st.session_state.currency_choice = st.selectbox(
                "Currency", list(CURRENCY_OPTIONS.keys()),
                index=list(CURRENCY_OPTIONS.keys()).index(st.session_state.currency_choice),
                help="Display symbol only — no exchange-rate conversion is applied.",
            )
        st.divider()

        st.markdown("**Save current session**")
        sc1, sc2 = st.columns([1, 2])
        name = sc1.text_input("Name", key="session_name_input", placeholder="e.g. 'First house, base case'")
        comment = sc2.text_input("Comment / notes", key="session_comment_input", placeholder="Optional notes to remind yourself later")
        if st.button("💾 Save session", type="primary", disabled=not name.strip()):
            sessions = load_all_sessions()
            sessions = [s for s in sessions if s["name"] != name.strip()]
            sessions.append({
                "name": name.strip(),
                "comment": comment.strip(),
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                "currency": st.session_state.currency_choice,
                "visible_calcs": st.session_state.visible_calcs,
                "state": st.session_state.state,
            })
            write_all_sessions(sessions)
            st.success(f"Saved session '{name.strip()}'.")

        st.divider()
        st.markdown("**Saved sessions**")
        sessions = load_all_sessions()
        if not sessions:
            st.caption("No saved sessions yet.")
        else:
            for sess in sorted(sessions, key=lambda s: s["saved_at"], reverse=True):
                r1, r2, r3, r4 = st.columns([2, 3, 1, 1])
                r1.markdown(f"**{sess['name']}**  \n<span style='color:#888;font-size:12px'>{sess['saved_at']}</span>", unsafe_allow_html=True)
                r2.markdown(f"<span style='color:#555'>{sess.get('comment') or '—'}</span>", unsafe_allow_html=True)
                if r3.button("Load", key=f"load_{sess['name']}"):
                    st.session_state.state = copy.deepcopy(sess["state"])
                    st.session_state.currency_choice = sess.get("currency", st.session_state.currency_choice)
                    st.session_state.visible_calcs = sess.get("visible_calcs", st.session_state.visible_calcs)
                    st.session_state.gen += 1
                    st.success(f"Loaded '{sess['name']}'.")
                    st.rerun()
                if r4.button("🗑️", key=f"del_{sess['name']}"):
                    write_all_sessions([s for s in sessions if s["name"] != sess["name"]])
                    st.rerun()

        st.divider()
        e1, e2 = st.columns(2)
        with e1:
            st.download_button(
                "⬇️ Export current session (.json)",
                data=json.dumps({
                    "name": name.strip() or "Untitled",
                    "comment": comment.strip(),
                    "saved_at": datetime.now().isoformat(timespec="seconds"),
                    "currency": st.session_state.currency_choice,
                    "visible_calcs": st.session_state.visible_calcs,
                    "state": st.session_state.state,
                }, indent=2),
                file_name="mortgage_session.json",
                mime="application/json",
            )
        with e2:
            uploaded = st.file_uploader("⬆️ Import session (.json)", type="json", label_visibility="collapsed")
            if uploaded is not None:
                data = json.loads(uploaded.read())
                st.session_state.state = copy.deepcopy(data["state"])
                st.session_state.currency_choice = data.get("currency", st.session_state.currency_choice)
                st.session_state.visible_calcs = data.get("visible_calcs", st.session_state.visible_calcs)
                st.session_state.gen += 1
                st.success("Session imported.")
                st.rerun()


# ---------------------------------------------------------------------------
# Calculator modules — each reads/writes via the s* helpers so it round-trips
# through save/load, and exposes CSV + SVG-ready plot exports.
# ---------------------------------------------------------------------------

def module_basic():
    left, right = st.columns([1, 1.5], gap="large")
    with left:
        loan = smoney("basic", "loan", "Mortgage amount")
        term = sslider("basic", "term", "Term (years)", min_value=1, max_value=40)
        rate = sstepper("basic", "rate", "Interest rate (%)", step=0.05, min_value=0, max_value=25, decimals=2, suffix="%")
        mtype = sradio("basic", "type", "Mortgage type", ["Repayment", "Interest-only"], horizontal=True)
        fee = smoney("basic", "fee", "Product fee", step=50)
        addfee = scheckbox("basic", "addfee", "Add fee to the loan")

    principal = loan + fee if addfee else loan
    df = build_schedule(principal, rate, term * 12, date.today(), method="daily_actual",
                         interest_only=(mtype == "Interest-only"))
    summ = summarize(df)
    total_repayable = summ["total_paid"] + (0 if addfee else fee)

    with right:
        m1, m2, m3 = st.columns(3)
        m1.metric("Monthly payment", fmt(df.iloc[0]["Payment"]))
        m2.metric("Total interest", fmt(summ["total_interest"]))
        m3.metric("Total repayable", fmt(total_repayable))
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["Date"], y=df["Balance"], mode="lines", line=dict(color=PRIMARY, width=2.5)))
        fig.update_layout(height=260, margin=dict(t=10, b=10, l=10, r=10), yaxis_title=f"Balance ({CUR()})",
                           xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
        st.plotly_chart(fig, use_container_width=True, config=SVG_CONFIG)
        csv_button(df, "basic_mortgage_schedule.csv")


def module_compare2():
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown("**Deal A**")
        loan_a = smoney("compare2", "a_loan", "Mortgage amount")
        term_a = sslider("compare2", "a_term", "Term (years)", min_value=1, max_value=40)
        rate_a = sstepper("compare2", "a_rate", "Interest rate (%)", step=0.05, min_value=0, max_value=25, decimals=2, suffix="%")
        fee_a = smoney("compare2", "a_fee", "Product fee", step=50)
    with c2:
        st.markdown("**Deal B**")
        loan_b = smoney("compare2", "b_loan", "Mortgage amount")
        term_b = sslider("compare2", "b_term", "Term (years)", min_value=1, max_value=40)
        rate_b = sstepper("compare2", "b_rate", "Interest rate (%)", step=0.05, min_value=0, max_value=25, decimals=2, suffix="%")
        fee_b = smoney("compare2", "b_fee", "Product fee", step=50)

    df_a = build_schedule(loan_a, rate_a, term_a * 12, date.today(), method="daily_actual")
    df_b = build_schedule(loan_b, rate_b, term_b * 12, date.today(), method="daily_actual")
    total_a = summarize(df_a)["total_paid"] + fee_a
    total_b = summarize(df_b)["total_paid"] + fee_b

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Deal A — monthly", fmt(df_a.iloc[0]["Payment"]))
    m2.metric("Deal B — monthly", fmt(df_b.iloc[0]["Payment"]))
    m3.metric("Deal A — total cost", fmt(total_a))
    m4.metric("Deal B — total cost", fmt(total_b))
    cheaper = "A" if total_a < total_b else "B"
    st.markdown(f'<div class="verdict-card">💡 <b>Deal {cheaper} is cheaper overall</b> by {fmt(abs(total_a-total_b))}.</div>', unsafe_allow_html=True)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_a["Date"], y=df_a["Balance"], mode="lines", name="Deal A", line=dict(color=PRIMARY, width=2.5)))
    fig.add_trace(go.Scatter(x=df_b["Date"], y=df_b["Balance"], mode="lines", name="Deal B", line=dict(color=ACCENT, width=2.5)))
    fig.update_layout(height=280, margin=dict(t=10, b=10, l=10, r=10), yaxis_title=f"Balance ({CUR()})",
                       xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
    st.plotly_chart(fig, use_container_width=True, config=SVG_CONFIG)
    cc1, cc2 = st.columns(2)
    with cc1:
        csv_button(df_a, "deal_a_schedule.csv", "⬇️ Deal A CSV")
    with cc2:
        csv_button(df_b, "deal_b_schedule.csv", "⬇️ Deal B CSV")


def module_overpay():
    left, right = st.columns([1, 1.5], gap="large")
    with left:
        loan = smoney("overpay", "loan", "Mortgage amount")
        term = sslider("overpay", "term", "Term (years)", min_value=1, max_value=40)
        rate = sstepper("overpay", "rate", "Interest rate (%)", step=0.05, min_value=0, max_value=25, decimals=2, suffix="%")
        extra = smoney("overpay", "extra", "Extra monthly overpayment", step=50)

    base = build_schedule(loan, rate, term * 12, date.today(), method="daily_actual")
    over = build_schedule(loan, rate, term * 12, date.today(), method="daily_actual", extra_payment=extra)
    base_summ, over_summ = summarize(base), summarize(over)
    months_saved = base_summ["months"] - over_summ["months"]

    with right:
        m1, m2, m3 = st.columns(3)
        m1.metric("Term shortened by", f"{months_saved // 12}y {months_saved % 12}m")
        m2.metric("Interest saved", fmt(base_summ["total_interest"] - over_summ["total_interest"]))
        m3.metric("New payoff date", over_summ["payoff_date"].isoformat() if over_summ["payoff_date"] else "—")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=base["Date"], y=base["Balance"], mode="lines", name="No overpayment", line=dict(color="#9aa0a6", width=2, dash="dot")))
        fig.add_trace(go.Scatter(x=over["Date"], y=over["Balance"], mode="lines", name="With overpayment", line=dict(color=PRIMARY, width=2.5)))
        fig.update_layout(height=260, margin=dict(t=10, b=10, l=10, r=10), yaxis_title=f"Balance ({CUR()})",
                           xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
        st.plotly_chart(fig, use_container_width=True, config=SVG_CONFIG)
        cc1, cc2 = st.columns(2)
        with cc1:
            csv_button(base, "overpay_baseline.csv", "⬇️ Baseline CSV")
        with cc2:
            csv_button(over, "overpay_with_overpayment.csv", "⬇️ Overpaid CSV")


def module_offset():
    left, right = st.columns([1, 1.5], gap="large")
    with left:
        loan = smoney("offset", "loan", "Mortgage amount")
        term = sslider("offset", "term", "Term (years)", min_value=1, max_value=40)
        rate = sstepper("offset", "rate", "Mortgage interest rate (%)", step=0.05, min_value=0, max_value=25, decimals=2, suffix="%")
        offset_bal = smoney("offset", "savings", "Savings held in offset account", step=1000,
                             help=GLOSSARY["Offset"])
        srate = sstepper("offset", "srate", "Alternative savings rate (%)", step=0.1, min_value=0, max_value=15, decimals=2, suffix="%")
        tax = sstepper("offset", "tax", "Tax on savings interest (%)", step=1, min_value=0, max_value=60, decimals=0, suffix="%")

    base = build_schedule(loan, rate, term * 12, date.today(), method="daily_actual")
    off = build_offset_schedule(loan, rate, term * 12, date.today(), offset_balance=offset_bal, method="daily_actual")
    base_summ, off_summ = summarize(base), summarize(off)
    months_saved = base_summ["months"] - off_summ["months"]
    breakeven = rate / (1 - tax / 100) if tax < 100 else float("inf")

    with right:
        m1, m2, m3 = st.columns(3)
        m1.metric("Interest saved by offsetting", fmt(base_summ["total_interest"] - off_summ["total_interest"]))
        m2.metric("Term shortened by", f"{months_saved // 12}y {months_saved % 12}m")
        m3.metric("Break-even savings rate", f"{breakeven:.2f}%")
        st.markdown(
            f'<div class="verdict-card">💡 Offsetting = a guaranteed tax-free return of <b>{rate:.2f}%</b>. '
            f'Elsewhere you\'d need &gt;{breakeven:.2f}% before tax to beat it.</div>',
            unsafe_allow_html=True,
        )
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=base["Date"], y=base["Balance"], mode="lines", name="No offset", line=dict(color="#9aa0a6", width=2, dash="dot")))
        fig.add_trace(go.Scatter(x=off["Date"], y=off["Balance"], mode="lines", name="Offset", line=dict(color=PRIMARY, width=2.5)))
        fig.update_layout(height=240, margin=dict(t=10, b=10, l=10, r=10), yaxis_title=f"Balance ({CUR()})",
                           xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
        st.plotly_chart(fig, use_container_width=True, config=SVG_CONFIG)
        cc1, cc2 = st.columns(2)
        with cc1:
            csv_button(base, "offset_baseline.csv", "⬇️ No-offset CSV")
        with cc2:
            csv_button(off, "offset_schedule.csv", "⬇️ Offset CSV")


def module_deposit():
    left, right = st.columns([1, 1.5], gap="large")
    with left:
        target = smoney("deposit", "target", "Deposit target", step=1000)
        current = smoney("deposit", "current", "Current savings", step=500)
        monthly = smoney("deposit", "monthly", "Monthly saving", step=50)
        rate = sstepper("deposit", "rate", "Savings interest rate (%)", step=0.1, min_value=0, max_value=15, decimals=2, suffix="%")

    balances = [current]
    months = 0
    balance = current
    reached = balance >= target
    while not reached and months < 600:
        months += 1
        balance = balance * (1 + rate / 100 / 12) + monthly
        balances.append(balance)
        reached = balance >= target
    dates = [add_months(date.today(), m) for m in range(len(balances))]
    growth_df = pd.DataFrame({"Month": range(len(balances)), "Date": [d.isoformat() for d in dates], "Savings": balances})

    with right:
        if reached:
            years, rem_months = divmod(months, 12)
            m1, m2, m3 = st.columns(3)
            m1.metric("Time to reach target", f"{years}y {rem_months}m")
            m2.metric("Target date", add_months(date.today(), months).isoformat())
            m3.metric("Total saved (contributions)", fmt(monthly * months))
        else:
            st.warning("Won't reach target within 50 years at this rate — try a higher monthly saving.")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=dates, y=balances, mode="lines", line=dict(color=PRIMARY, width=2.5), fill="tozeroy", fillcolor="rgba(63,81,181,0.10)"))
        fig.add_hline(y=target, line_dash="dash", line_color=ACCENT, annotation_text="Target")
        fig.update_layout(height=280, margin=dict(t=10, b=10, l=10, r=10), yaxis_title=f"Savings ({CUR()})",
                           xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
        st.plotly_chart(fig, use_container_width=True, config=SVG_CONFIG)
        csv_button(growth_df, "deposit_savings_growth.csv")


def module_comparefixed():
    sc1, sc2 = st.columns(2)
    with sc1:
        loan = smoney("comparefixed", "loan", "Shared mortgage amount")
    with sc2:
        term = sslider("comparefixed", "term", "Full mortgage term (years)", min_value=1, max_value=40)

    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown("**Deal A**")
        rate_a = sstepper("comparefixed", "a_rate", "Interest rate (%)", step=0.05, min_value=0, max_value=25, decimals=2, suffix="%")
        fixed_a = int(sstepper("comparefixed", "a_fixed", "Fixed period (years)", step=1, min_value=1, max_value=10, decimals=0, suffix=" yrs"))
        fee_a = smoney("comparefixed", "a_fee", "Product fee", step=50)
        addfee_a = scheckbox("comparefixed", "a_addfee", "Add fee to loan")
        cashback_a = smoney("comparefixed", "a_cashback", "Cashback offered", step=50)
    with c2:
        st.markdown("**Deal B**")
        rate_b = sstepper("comparefixed", "b_rate", "Interest rate (%)", step=0.05, min_value=0, max_value=25, decimals=2, suffix="%")
        fixed_b = int(sstepper("comparefixed", "b_fixed", "Fixed period (years)", step=1, min_value=1, max_value=10, decimals=0, suffix=" yrs"))
        fee_b = smoney("comparefixed", "b_fee", "Product fee", step=50)
        addfee_b = scheckbox("comparefixed", "b_addfee", "Add fee to loan")
        cashback_b = smoney("comparefixed", "b_cashback", "Cashback offered", step=50)

    principal_a = loan + fee_a if addfee_a else loan
    principal_b = loan + fee_b if addfee_b else loan
    df_a = build_schedule(principal_a, rate_a, term * 12, date.today(), method="daily_actual")
    df_b = build_schedule(principal_b, rate_b, term * 12, date.today(), method="daily_actual")
    months_a, months_b = min(fixed_a * 12, len(df_a)), min(fixed_b * 12, len(df_b))
    paid_a = df_a.iloc[:months_a]["Payment"].sum() + (0 if addfee_a else fee_a) - cashback_a
    paid_b = df_b.iloc[:months_b]["Payment"].sum() + (0 if addfee_b else fee_b) - cashback_b

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Deal A — monthly", fmt(df_a.iloc[0]["Payment"]))
    m2.metric("Deal B — monthly", fmt(df_b.iloc[0]["Payment"]))
    m3.metric(f"Deal A — true cost ({fixed_a}y)", fmt(paid_a))
    m4.metric(f"Deal B — true cost ({fixed_b}y)", fmt(paid_b))
    cheaper = "A" if paid_a < paid_b else "B"
    st.markdown(
        f'<div class="verdict-card">💡 <b>Deal {cheaper} costs less</b> over its own fixed period — remember '
        f'the periods differ in length, so also weigh up the rate you might face afterward.</div>',
        unsafe_allow_html=True,
    )
    cc1, cc2 = st.columns(2)
    with cc1:
        csv_button(df_a, "compare_fixed_deal_a.csv", "⬇️ Deal A CSV")
    with cc2:
        csv_button(df_b, "compare_fixed_deal_b.csv", "⬇️ Deal B CSV")


def module_ditchfix():
    left, right = st.columns([1, 1.5], gap="large")
    with left:
        st.markdown("**Current deal**")
        balance = smoney("ditchfix", "balance", "Remaining balance", step=1000)
        remaining_term = sstepper("ditchfix", "remterm", "Remaining overall term (years)", step=0.5, min_value=1, max_value=40, decimals=1, suffix=" yrs")
        months_left = int(sstepper("ditchfix", "monthsleft", "Months left on current fix", step=1, min_value=1, max_value=60, decimals=0))
        current_rate = sstepper("ditchfix", "crate", "Current rate (%)", step=0.05, min_value=0, max_value=25, decimals=2, suffix="%")
        erc_pct = sstepper("ditchfix", "erc", "Early repayment charge (%)", step=0.25, min_value=0, max_value=15, decimals=2, suffix="%")
        st.markdown("**New deal**")
        new_rate = sstepper("ditchfix", "nrate", "New rate (%)", step=0.05, min_value=0, max_value=25, decimals=2, suffix="%")
        new_fees = smoney("ditchfix", "nfees", "New deal fees", step=50)

    stay = build_schedule(balance, current_rate, int(remaining_term * 12), date.today(), method="daily_actual")
    switch = build_schedule(balance, new_rate, int(remaining_term * 12), date.today(), method="daily_actual")
    stay_cost = stay.iloc[:months_left]["Interest"].sum()
    switch_cost = switch.iloc[:months_left]["Interest"].sum() + balance * erc_pct / 100 + new_fees
    saving = stay_cost - switch_cost

    with right:
        m1, m2, m3 = st.columns(3)
        m1.metric("Cost if you stay", fmt(stay_cost))
        m2.metric("Cost if you switch now", fmt(switch_cost))
        m3.metric("Net saving by switching", fmt(saving))
        verdict = "switching now looks worth it" if saving > 0 else "it's cheaper to stay put until the fix ends"
        st.markdown(
            f'<div class="verdict-card">💡 Based on these numbers, <b>{verdict}</b> — '
            f'{"you save" if saving > 0 else "you\'d lose"} {fmt(abs(saving))} over the remaining {months_left} months.</div>',
            unsafe_allow_html=True,
        )
        fig = go.Figure()
        fig.add_trace(go.Bar(x=["Stay", "Switch now"], y=[stay_cost, switch_cost], marker_color=["#9aa0a6", PRIMARY]))
        fig.update_layout(height=240, margin=dict(t=10, b=10, l=10, r=10), yaxis_title=f"Cost over remaining fix ({CUR()})",
                           xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
        st.plotly_chart(fig, use_container_width=True, config=SVG_CONFIG)
        cc1, cc2 = st.columns(2)
        with cc1:
            csv_button(stay, "ditch_fix_stay_schedule.csv", "⬇️ Stay CSV")
        with cc2:
            csv_button(switch, "ditch_fix_switch_schedule.csv", "⬇️ Switch CSV")


def module_borrow():
    left, right = st.columns([1, 1.5], gap="large")
    with left:
        income1 = smoney("borrow", "inc1", "Applicant 1 annual income", step=1000)
        income2 = smoney("borrow", "inc2", "Applicant 2 annual income (0 if none)", step=1000)
        multiple = sstepper("borrow", "mult", "Income multiple", step=0.1, min_value=2.5, max_value=6, decimals=1, suffix="×")
        deposit = smoney("borrow", "deposit", "Deposit available", step=1000)

    max_loan = (income1 + income2) * multiple
    max_price = max_loan + deposit
    summary_df = pd.DataFrame([{
        "Applicant 1 income": income1, "Applicant 2 income": income2, "Income multiple": multiple,
        "Deposit": deposit, "Max loan": max_loan, "Max property price": max_price,
    }])

    with right:
        m1, m2, m3 = st.columns(3)
        m1.metric("Estimated max loan", fmt(max_loan))
        m2.metric("Plus your deposit", fmt(deposit))
        m3.metric("Estimated max property price", fmt(max_price))
        fig = go.Figure()
        fig.add_trace(go.Bar(y=["Property price"], x=[max_loan], name="Loan", orientation="h", marker_color=PRIMARY))
        fig.add_trace(go.Bar(y=["Property price"], x=[deposit], name="Deposit", orientation="h", marker_color=ACCENT))
        fig.update_layout(barmode="stack", height=140, margin=dict(t=10, b=10, l=10, r=10), xaxis_title=f"({CUR()})",
                           xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
        st.plotly_chart(fig, use_container_width=True, config=SVG_CONFIG)
        st.caption("Rough guide only — actual affordability depends on lender stress tests, outgoings, and credit history.")
        csv_button(summary_df, "borrowing_estimate.csv")


MODULE_FUNCS = {
    "basic": module_basic, "compare2": module_compare2, "overpay": module_overpay,
    "offset": module_offset, "deposit": module_deposit, "comparefixed": module_comparefixed,
    "ditchfix": module_ditchfix, "borrow": module_borrow,
}


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.title("🏡 Mortgage Dashboard")
st.caption("All calculators on one page — toggle the ones you need. Every plot's camera icon exports SVG; every table exports CSV.")

render_session_bar()

st.session_state.visible_calcs = st.multiselect(
    "Show calculators",
    list(CALC_LABELS.values()),
    default=[v for v in st.session_state.visible_calcs if v in CALC_LABELS.values()],
)

if not st.session_state.visible_calcs:
    st.info("Toggle on a calculator above to get started.")

for label in st.session_state.visible_calcs:
    key = LABEL_TO_KEY[label]
    icon, title = CALC_META[[m[0] for m in CALC_META].index(key)][1:]
    with st.container(border=True):
        st.markdown(f'<div class="module-title"><h4>{icon} {title}</h4></div>', unsafe_allow_html=True)
        MODULE_FUNCS[key]()
