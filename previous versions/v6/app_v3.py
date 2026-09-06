import copy
import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import (
    CURRENCY_OPTIONS, GLOSSARY, LUMP_SUM_MODES, PALETTE, inject_glossary_css, stepper,
    build_schedule, build_offset_schedule, summarize, add_months, add_month_axis,
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
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Calculator registry & default state
# ---------------------------------------------------------------------------

CALC_META = [
    ("basic", "🏠", "Basic mortgage calculator"),
    ("compare2", "⚖️", "Compare mortgages"),
    ("overpay", "💷", "Overpayment calculator"),
    ("offset", "🔄", "Offset mortgage vs savings"),
    ("deposit", "🐷", "Saving for a deposit"),
    ("comparefixed", "📊", "Compare fixed rate mortgages"),
    ("ditchfix", "🚪", "Ditch your fix"),
    ("borrow", "🧮", "How much can I borrow"),
]
CALC_LABELS = {k: f"{icon} {title}" for k, icon, title in CALC_META}
LABEL_TO_KEY = {v: k for k, v in CALC_LABELS.items()}

MORTGAGE_TEMPLATE = {
    "name": "Mortgage 1", "loan": 250_000, "term": 25, "rate": 4.5,
    "start_date": date.today().isoformat(),
    "method": "daily_actual", "type": "Repayment", "fee": 0, "addfee": False,
    "extra_payment": 0, "deposit": 0, "upfront_costs": [],
    "rate_changes": [], "lump_sums": [], "lump_sum_mode": "shorten_term", "milestones": [],
}


def mortgage_template(name, **overrides):
    t = copy.deepcopy(MORTGAGE_TEMPLATE)
    t["name"] = name
    t.update(overrides)
    return t


OFFSET_TEMPLATE = {"name": "Offset 1", "loan": 250_000, "term": 25, "rate": 4.5, "savings": 30_000, "srate": 3.0, "tax": 20.0}
DEPOSIT_TEMPLATE = {"name": "Plan 1", "target": 40_000, "current": 5_000, "monthly": 500, "rate": 3.0}
FIXED_TEMPLATE = {"name": "Deal A", "loan": 250_000, "term": 25, "rate": 4.5, "fixed_years": 2, "fee": 999, "addfee": False, "cashback": 0}
DITCH_TEMPLATE = {"name": "Option 1", "balance": 220_000, "remterm": 22.0, "monthsleft": 8, "crate": 5.5, "erc": 3.0, "nrate": 4.3, "nfees": 999}
BORROW_TEMPLATE = {"name": "Scenario 1", "inc1": 40_000, "inc2": 0, "mult": 4.5, "deposit": 30_000}

DEFAULT_STATE = {
    "basic": {"scenarios": [mortgage_template("Mortgage 1")]},
    "compare2": {"scenarios": [mortgage_template("Deal A"), mortgage_template("Deal B", rate=4.2, fee=1499)]},
    "overpay": {"scenarios": [mortgage_template("No overpayment"), mortgage_template("With overpayment", extra_payment=200)]},
    "offset": {"scenarios": [copy.deepcopy(OFFSET_TEMPLATE)]},
    "deposit": {"scenarios": [copy.deepcopy(DEPOSIT_TEMPLATE)]},
    "comparefixed": {"scenarios": [dict(FIXED_TEMPLATE), dict(FIXED_TEMPLATE, name="Deal B", rate=4.2, fixed_years=5, fee=1499, cashback=250)]},
    "ditchfix": {"scenarios": [copy.deepcopy(DITCH_TEMPLATE)]},
    "borrow": {"scenarios": [copy.deepcopy(BORROW_TEMPLATE)]},
}

st.session_state.setdefault("gen", 0)
st.session_state.setdefault("state", copy.deepcopy(DEFAULT_STATE))
st.session_state.setdefault("currency_choice", "£ British Pound (GBP)")
st.session_state.setdefault("visible_calcs", [CALC_LABELS["basic"]])

GEN = st.session_state.gen


def CUR():
    return CURRENCY_OPTIONS[st.session_state.currency_choice]


def fmt(x):
    return f"{CUR()}{x:,.0f}"


def get_scenarios(calc):
    return st.session_state.state[calc]["scenarios"]


def sc_field(calc, i, field):
    return get_scenarios(calc)[i][field]


def sc_set(calc, i, field, value):
    get_scenarios(calc)[i][field] = value


def sc_money(calc, i, field, label, step=1000, **kwargs):
    val = stepper(label, sc_field(calc, i, field), step=step, min_value=0, decimals=0, prefix=CUR(),
                   thousands=True, key=f"{calc}_{i}_{field}_{GEN}", **kwargs)
    sc_set(calc, i, field, val)
    return val


def sc_stepper(calc, i, field, label, **kwargs):
    val = stepper(label, sc_field(calc, i, field), key=f"{calc}_{i}_{field}_{GEN}", **kwargs)
    sc_set(calc, i, field, val)
    return val


def sc_slider(calc, i, field, label, **kwargs):
    val = st.slider(label, value=sc_field(calc, i, field), key=f"{calc}_{i}_{field}_{GEN}", **kwargs)
    sc_set(calc, i, field, val)
    return val


def sc_radio(calc, i, field, label, options, **kwargs):
    cur_val = sc_field(calc, i, field)
    idx = options.index(cur_val) if cur_val in options else 0
    val = st.radio(label, options, index=idx, key=f"{calc}_{i}_{field}_{GEN}", **kwargs)
    sc_set(calc, i, field, val)
    return val


def sc_checkbox(calc, i, field, label, **kwargs):
    val = st.checkbox(label, value=sc_field(calc, i, field), key=f"{calc}_{i}_{field}_{GEN}", **kwargs)
    sc_set(calc, i, field, val)
    return val


def sc_text(calc, i, field, label, **kwargs):
    val = st.text_input(label, value=sc_field(calc, i, field), key=f"{calc}_{i}_{field}_{GEN}", **kwargs)
    sc_set(calc, i, field, val)
    return val


def sc_date(calc, i, field, label, **kwargs):
    val = st.date_input(label, value=date.fromisoformat(sc_field(calc, i, field)), key=f"{calc}_{i}_{field}_{GEN}", **kwargs)
    sc_set(calc, i, field, val.isoformat())
    return val


def csv_button(df, filename, label="⬇️ CSV"):
    st.download_button(label, data=df.to_csv(index=False), file_name=filename, mime="text/csv",
                        key=f"csv_{filename}_{GEN}_{id(df)}")


# ---------------------------------------------------------------------------
# Timeline-event editors (rate changes / lump sums / milestones / upfront costs)
# ---------------------------------------------------------------------------

def sc_upfront_costs_editor(calc, i):
    sc = get_scenarios(calc)[i]
    default = pd.DataFrame(sc["upfront_costs"], columns=["Name", "Amount", "Date"]) if sc["upfront_costs"] else pd.DataFrame(columns=["Name", "Amount", "Date"])
    if not default.empty:
        default["Date"] = pd.to_datetime(default["Date"])
    df = st.data_editor(
        default, num_rows="dynamic", use_container_width=True, key=f"{calc}_{i}_uc_{GEN}",
        column_config={
            "Name": st.column_config.TextColumn("Name", help="e.g. 'Stamp duty' or 'Survey'."),
            "Amount": st.column_config.NumberColumn(f"Amount ({CUR()})"),
            "Date": st.column_config.DateColumn("Date"),
        },
    )
    costs = [[str(r["Name"]), float(r["Amount"]), pd.Timestamp(r["Date"]).date().isoformat()]
             for _, r in df.dropna().iterrows() if r["Name"] and r["Amount"] not in (None, "")]
    sc["upfront_costs"] = costs
    return costs


def sc_rate_changes_editor(calc, i):
    sc = get_scenarios(calc)[i]
    default = pd.DataFrame(sc["rate_changes"], columns=["Month", "New Rate (%)"]) if sc["rate_changes"] else pd.DataFrame(columns=["Month", "New Rate (%)"])
    df = st.data_editor(
        default, num_rows="dynamic", use_container_width=True, key=f"{calc}_{i}_rc_{GEN}",
        column_config={
            "Month": st.column_config.NumberColumn("Month", help="Payment number (1 = first payment) the new rate starts from."),
            "New Rate (%)": st.column_config.NumberColumn("New Rate (%)"),
        },
    )
    rc = [[int(r["Month"]), float(r["New Rate (%)"])] for _, r in df.dropna().iterrows() if r["Month"] and r["New Rate (%)"] not in (None, "")]
    sc["rate_changes"] = rc
    return rc


def sc_lump_sums_editor(calc, i):
    sc = get_scenarios(calc)[i]
    default = pd.DataFrame(sc["lump_sums"], columns=["Month", "Amount", "Label"]) if sc["lump_sums"] else pd.DataFrame(columns=["Month", "Amount", "Label"])
    df = st.data_editor(
        default, num_rows="dynamic", use_container_width=True, key=f"{calc}_{i}_ls_{GEN}",
        column_config={
            "Month": st.column_config.NumberColumn("Month", help="Payment number the lump sum is applied in."),
            "Amount": st.column_config.NumberColumn(f"Amount ({CUR()})"),
            "Label": st.column_config.TextColumn("Label", help="e.g. 'Bonus' or 'Inheritance'."),
        },
    )
    ls = [[int(r["Month"]), float(r["Amount"]), str(r.get("Label") or "")]
          for _, r in df.dropna(subset=["Month", "Amount"]).iterrows() if r["Month"] and r["Amount"] not in (None, "")]
    sc["lump_sums"] = ls
    return ls


def sc_milestones_editor(calc, i):
    sc = get_scenarios(calc)[i]
    default = pd.DataFrame(sc["milestones"], columns=["Month", "Label"]) if sc["milestones"] else pd.DataFrame(columns=["Month", "Label"])
    df = st.data_editor(
        default, num_rows="dynamic", use_container_width=True, key=f"{calc}_{i}_ms_{GEN}",
        column_config={
            "Month": st.column_config.NumberColumn("Month", help="Payment number to mark on the chart."),
            "Label": st.column_config.TextColumn("Label", help="e.g. 'Fixed period ends'."),
        },
    )
    ms = [[int(r["Month"]), str(r["Label"])] for _, r in df.dropna().iterrows() if r["Month"] and r["Label"]]
    sc["milestones"] = ms
    return ms


def compute_mortgage_schedule(sc):
    principal = sc["loan"] + sc["fee"] if sc["addfee"] else sc["loan"]
    return build_schedule(
        principal, sc["rate"], sc["term"] * 12, date.fromisoformat(sc["start_date"]), method=sc["method"],
        extra_payment=sc["extra_payment"],
        rate_changes=[tuple(rc) for rc in sc["rate_changes"]],
        lump_sums=[(int(ls[0]), float(ls[1])) for ls in sc["lump_sums"]],
        lump_sum_mode=sc["lump_sum_mode"],
        interest_only=(sc["type"] == "Interest-only"),
    )


# ---------------------------------------------------------------------------
# Full-featured mortgage module (used by Basic / Compare / Overpayment)
# ---------------------------------------------------------------------------

def render_mortgage_scenario_form(calc, i, min_scenarios):
    scenarios = get_scenarios(calc)
    sc = scenarios[i]
    with st.expander(f"✏️ {sc['name']}", expanded=(len(scenarios) <= 1)):
        h1, h2 = st.columns([4, 1])
        with h1:
            sc_text(calc, i, "name", "Scenario name")
        with h2:
            st.write("")
            if len(scenarios) > min_scenarios and st.button("🗑 Remove", key=f"{calc}_rm_{i}_{GEN}"):
                scenarios.pop(i)
                st.rerun()

        c1, c2 = st.columns(2)
        with c1:
            sc_money(calc, i, "loan", f"Loan amount — {gterm_plain('Principal')}")
            sc_slider(calc, i, "term", "Term (years)", min_value=1, max_value=40)
            sc_stepper(calc, i, "rate", "Interest rate (%)", step=0.05, min_value=0, max_value=25, decimals=2, suffix="%")
            sc_date(calc, i, "start_date", "Start date")
        with c2:
            sc_radio(calc, i, "method", "Interest accrual", ["daily_actual", "monthly"], horizontal=True,
                      format_func=lambda m: "Daily actual/365 (bank-style)" if m == "daily_actual" else "Monthly (rate/12)")
            sc_radio(calc, i, "type", "Mortgage type", ["Repayment", "Interest-only"], horizontal=True)
            sc_money(calc, i, "fee", "Product fee", step=50)
            sc_checkbox(calc, i, "addfee", "Add fee to the loan")
            sc_money(calc, i, "extra_payment", "Extra monthly overpayment", step=50)

        with st.expander("🏦 Deposit & upfront costs", expanded=bool(sc["deposit"] or sc["upfront_costs"])):
            sc_money(calc, i, "deposit", "Deposit")
            st.caption("One-off costs (stamp duty, legal fees, survey...) at whatever date they occur.")
            sc_upfront_costs_editor(calc, i)

        with st.expander("📈 Rate changes over time", expanded=bool(sc["rate_changes"])):
            st.caption("e.g. tracker/SVR reverting after a fixed period.")
            sc_rate_changes_editor(calc, i)

        with st.expander("💵 Lump sums", expanded=bool(sc["lump_sums"])):
            st.caption("A one-off overpayment at a given month, e.g. a bonus or inheritance.")
            sc_lump_sums_editor(calc, i)
            sc_radio(calc, i, "lump_sum_mode", "After a lump sum...", list(LUMP_SUM_MODES.keys()),
                      format_func=lambda m: LUMP_SUM_MODES[m])

        with st.expander("🚩 Milestones", expanded=bool(sc["milestones"])):
            st.caption("Label-only markers on the chart — no effect on the numbers.")
            sc_milestones_editor(calc, i)


def gterm_plain(key):
    return GLOSSARY[key].split(".")[0]


def render_mortgage_results(calc, deposit_toggle_key):
    scenarios = get_scenarios(calc)
    dfs = {sc["name"]: compute_mortgage_schedule(sc) for sc in scenarios}
    summaries = {name: summarize(df) for name, df in dfs.items()}

    include_upfront = st.checkbox("Include deposit & upfront costs in totals", value=True, key=deposit_toggle_key)

    st.markdown("###### Summary")
    cols = st.columns(len(scenarios))
    for col, sc in zip(cols, scenarios):
        df, summ = dfs[sc["name"]], summaries[sc["name"]]
        with col:
            st.markdown(f"**{sc['name']}**")
            st.metric("Monthly payment", fmt(df.iloc[0]["Payment"]))
            st.metric("Total interest", fmt(summ["total_interest"]))
            st.metric("Payoff date", summ["payoff_date"].isoformat() if summ["payoff_date"] else "—")
            if include_upfront:
                total_cash = summ["total_paid"] + sc["deposit"] + sum(c[1] for c in sc["upfront_costs"])
                st.metric("Total cash invested", fmt(total_cash))

    show_events = len(scenarios) <= 2
    ref_start = min(date.fromisoformat(sc["start_date"]) for sc in scenarios)
    max_months_all = max(len(df) for df in dfs.values())
    min_date_all = min(df["Date"].iloc[0] for df in dfs.values())
    max_date_all = max(df["Date"].iloc[-1] for df in dfs.values())

    st.markdown("###### Balance over time")
    fig = go.Figure()
    for idx, sc in enumerate(scenarios):
        df = dfs[sc["name"]]
        color = PALETTE[idx % len(PALETTE)]
        fig.add_trace(go.Scatter(x=df["Date"], y=df["Balance"], mode="lines", name=sc["name"], line=dict(color=color, width=2.5)))
        if show_events:
            d0 = date.fromisoformat(sc["start_date"])
            for m, new_rate in sc["rate_changes"]:
                fig.add_vline(x=pd.Timestamp(add_months(d0, int(m))), line_dash="dot", line_color=color, opacity=0.5,
                              annotation_text=f"{sc['name']}: rate → {new_rate:g}%", annotation_textangle=-90, annotation_font_size=9)
            for m, amt, label in sc["lump_sums"]:
                txt = f"{sc['name']}: lump sum {fmt(amt)}" + (f" ({label})" if label else "")
                fig.add_vline(x=pd.Timestamp(add_months(d0, int(m))), line_dash="dash", line_color=color, opacity=0.5,
                              annotation_text=txt, annotation_textangle=-90, annotation_font_size=9)
            for m, label in sc["milestones"]:
                fig.add_vline(x=pd.Timestamp(add_months(d0, int(m))), line_dash="dashdot", line_color="#808495", opacity=0.6,
                              annotation_text=f"{sc['name']}: {label}", annotation_textangle=-90, annotation_font_size=9)
    if not show_events and any(sc["rate_changes"] or sc["lump_sums"] or sc["milestones"] for sc in scenarios):
        st.caption("Event markers are hidden when comparing more than 2 scenarios.")
    fig.update_layout(height=340, margin=dict(t=60, b=10, l=10, r=10), yaxis_title=f"Balance ({CUR()})",
                       xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
    add_month_axis(fig, ref_start, max_months_all, min_date_all, max_date_all)
    st.plotly_chart(fig, use_container_width=True, config=SVG_CONFIG)

    st.markdown("###### Monthly payment over time")
    fig2 = go.Figure()
    for idx, sc in enumerate(scenarios):
        df = dfs[sc["name"]]
        color = PALETTE[idx % len(PALETTE)]
        fig2.add_trace(go.Scatter(x=df["Date"], y=df["ScheduledPayment"], mode="lines", name=sc["name"], line=dict(color=color, width=2.5, shape="hv")))
    fig2.update_layout(height=280, margin=dict(t=10, b=10, l=10, r=10), yaxis_title=f"Scheduled payment ({CUR()})",
                        xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
    st.plotly_chart(fig2, use_container_width=True, config=SVG_CONFIG)

    st.markdown("###### Export")
    combined = pd.concat([df.assign(Scenario=name) for name, df in dfs.items()], ignore_index=True)
    ce1, ce2 = st.columns([1, 3])
    with ce1:
        csv_button(combined, f"{calc}_combined_schedule.csv", "⬇️ Combined CSV (all scenarios)")
    with ce2:
        cols2 = st.columns(len(dfs))
        for col, (name, df) in zip(cols2, dfs.items()):
            with col:
                csv_button(df, f"{name.replace(' ', '_')}_schedule.csv", f"⬇️ {name}")


def render_mortgage_module(calc, min_scenarios=1, default_template_name="Mortgage"):
    scenarios = get_scenarios(calc)
    for i in range(len(scenarios)):
        render_mortgage_scenario_form(calc, i, min_scenarios)
    if st.button("➕ Add another mortgage to compare", key=f"{calc}_add_{GEN}"):
        scenarios.append(mortgage_template(f"{default_template_name} {len(scenarios) + 1}"))
        st.rerun()
    st.divider()
    render_mortgage_results(calc, deposit_toggle_key=f"{calc}_incupfront_{GEN}")


def module_basic():
    render_mortgage_module("basic", min_scenarios=1, default_template_name="Mortgage")


def module_compare2():
    render_mortgage_module("compare2", min_scenarios=2, default_template_name="Deal")


def module_overpay():
    render_mortgage_module("overpay", min_scenarios=1, default_template_name="Scenario")


# ---------------------------------------------------------------------------
# Offset mortgage vs savings — multi-scenario
# ---------------------------------------------------------------------------

def module_offset():
    scenarios = get_scenarios("offset")
    for i, sc in enumerate(list(scenarios)):
        with st.expander(f"✏️ {sc['name']}", expanded=(len(scenarios) <= 1)):
            h1, h2 = st.columns([4, 1])
            with h1:
                sc_text("offset", i, "name", "Scenario name")
            with h2:
                st.write("")
                if len(scenarios) > 1 and st.button("🗑 Remove", key=f"offset_rm_{i}_{GEN}"):
                    scenarios.pop(i)
                    st.rerun()
            c1, c2 = st.columns(2)
            with c1:
                sc_money("offset", i, "loan", "Mortgage amount")
                sc_slider("offset", i, "term", "Term (years)", min_value=1, max_value=40)
                sc_stepper("offset", i, "rate", "Mortgage interest rate (%)", step=0.05, min_value=0, max_value=25, decimals=2, suffix="%")
            with c2:
                sc_money("offset", i, "savings", "Savings in offset account", step=1000, help=GLOSSARY["Offset"])
                sc_stepper("offset", i, "srate", "Alternative savings rate (%)", step=0.1, min_value=0, max_value=15, decimals=2, suffix="%")
                sc_stepper("offset", i, "tax", "Tax on savings interest (%)", step=1, min_value=0, max_value=60, decimals=0, suffix="%")

    if st.button("➕ Add another offset scenario", key=f"offset_add_{GEN}"):
        scenarios.append(dict(OFFSET_TEMPLATE, name=f"Offset {len(scenarios) + 1}"))
        st.rerun()
    st.divider()

    dfs_base, dfs_off = {}, {}
    for sc in scenarios:
        dfs_base[sc["name"]] = build_schedule(sc["loan"], sc["rate"], sc["term"] * 12, date.today(), method="daily_actual")
        dfs_off[sc["name"]] = build_offset_schedule(sc["loan"], sc["rate"], sc["term"] * 12, date.today(), offset_balance=sc["savings"], method="daily_actual")

    st.markdown("###### Summary")
    cols = st.columns(len(scenarios))
    for col, sc in zip(cols, scenarios):
        base_summ, off_summ = summarize(dfs_base[sc["name"]]), summarize(dfs_off[sc["name"]])
        breakeven = sc["rate"] / (1 - sc["tax"] / 100) if sc["tax"] < 100 else float("inf")
        with col:
            st.markdown(f"**{sc['name']}**")
            st.metric("Interest saved", fmt(base_summ["total_interest"] - off_summ["total_interest"]))
            st.metric("Break-even savings rate", f"{breakeven:.2f}%")

    fig = go.Figure()
    for idx, sc in enumerate(scenarios):
        color = PALETTE[idx % len(PALETTE)]
        fig.add_trace(go.Scatter(x=dfs_base[sc["name"]]["Date"], y=dfs_base[sc["name"]]["Balance"], mode="lines",
                                  name=f"{sc['name']} – no offset", line=dict(color=color, width=2, dash="dot")))
        fig.add_trace(go.Scatter(x=dfs_off[sc["name"]]["Date"], y=dfs_off[sc["name"]]["Balance"], mode="lines",
                                  name=f"{sc['name']} – offset", line=dict(color=color, width=2.5)))
    fig.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10), yaxis_title=f"Balance ({CUR()})",
                       xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
    st.plotly_chart(fig, use_container_width=True, config=SVG_CONFIG)

    combined = pd.concat(
        [df.assign(Scenario=f"{name} – no offset") for name, df in dfs_base.items()]
        + [df.assign(Scenario=f"{name} – offset") for name, df in dfs_off.items()], ignore_index=True,
    )
    csv_button(combined, "offset_combined_schedule.csv", "⬇️ Combined CSV (all scenarios)")


# ---------------------------------------------------------------------------
# Saving for a deposit — multi-scenario
# ---------------------------------------------------------------------------

def module_deposit():
    scenarios = get_scenarios("deposit")
    for i, sc in enumerate(list(scenarios)):
        with st.expander(f"✏️ {sc['name']}", expanded=(len(scenarios) <= 1)):
            h1, h2 = st.columns([4, 1])
            with h1:
                sc_text("deposit", i, "name", "Plan name")
            with h2:
                st.write("")
                if len(scenarios) > 1 and st.button("🗑 Remove", key=f"deposit_rm_{i}_{GEN}"):
                    scenarios.pop(i)
                    st.rerun()
            c1, c2 = st.columns(2)
            with c1:
                sc_money("deposit", i, "target", "Deposit target", step=1000)
                sc_money("deposit", i, "current", "Current savings", step=500)
            with c2:
                sc_money("deposit", i, "monthly", "Monthly saving", step=50)
                sc_stepper("deposit", i, "rate", "Savings interest rate (%)", step=0.1, min_value=0, max_value=15, decimals=2, suffix="%")

    if st.button("➕ Add another savings plan", key=f"deposit_add_{GEN}"):
        scenarios.append(dict(DEPOSIT_TEMPLATE, name=f"Plan {len(scenarios) + 1}"))
        st.rerun()
    st.divider()

    st.markdown("###### Summary")
    cols = st.columns(len(scenarios))
    fig = go.Figure()
    all_growth = []
    for idx, sc in enumerate(scenarios):
        balances = [sc["current"]]
        months, balance, reached = 0, sc["current"], sc["current"] >= sc["target"]
        while not reached and months < 600:
            months += 1
            balance = balance * (1 + sc["rate"] / 100 / 12) + sc["monthly"]
            balances.append(balance)
            reached = balance >= sc["target"]
        dates = [add_months(date.today(), m) for m in range(len(balances))]
        with cols[idx]:
            st.markdown(f"**{sc['name']}**")
            if reached:
                years, rem = divmod(months, 12)
                st.metric("Time to target", f"{years}y {rem}m")
                st.metric("Target date", add_months(date.today(), months).isoformat())
            else:
                st.warning("Target not reached within 50 years.")
        color = PALETTE[idx % len(PALETTE)]
        fig.add_trace(go.Scatter(x=dates, y=balances, mode="lines", name=sc["name"], line=dict(color=color, width=2.5)))
        fig.add_hline(y=sc["target"], line_dash="dash", line_color=color, opacity=0.5)
        all_growth.append(pd.DataFrame({"Month": range(len(balances)), "Date": [d.isoformat() for d in dates], "Savings": balances, "Scenario": sc["name"]}))

    fig.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10), yaxis_title=f"Savings ({CUR()})",
                       xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
    st.plotly_chart(fig, use_container_width=True, config=SVG_CONFIG)
    csv_button(pd.concat(all_growth, ignore_index=True), "deposit_combined_growth.csv", "⬇️ Combined CSV (all plans)")


# ---------------------------------------------------------------------------
# Compare fixed rate mortgages — N deals
# ---------------------------------------------------------------------------

def module_comparefixed():
    scenarios = get_scenarios("comparefixed")
    for i, sc in enumerate(list(scenarios)):
        with st.expander(f"✏️ {sc['name']}", expanded=(len(scenarios) <= 1)):
            h1, h2 = st.columns([4, 1])
            with h1:
                sc_text("comparefixed", i, "name", "Deal name")
            with h2:
                st.write("")
                if len(scenarios) > 2 and st.button("🗑 Remove", key=f"cf_rm_{i}_{GEN}"):
                    scenarios.pop(i)
                    st.rerun()
            c1, c2 = st.columns(2)
            with c1:
                sc_money("comparefixed", i, "loan", "Mortgage amount")
                sc_slider("comparefixed", i, "term", "Full term (years)", min_value=1, max_value=40)
                sc_stepper("comparefixed", i, "rate", "Interest rate (%)", step=0.05, min_value=0, max_value=25, decimals=2, suffix="%")
            with c2:
                sc_stepper("comparefixed", i, "fixed_years", "Fixed period (years)", step=1, min_value=1, max_value=10, decimals=0, suffix=" yrs")
                sc_money("comparefixed", i, "fee", "Product fee", step=50)
                sc_checkbox("comparefixed", i, "addfee", "Add fee to loan")
                sc_money("comparefixed", i, "cashback", "Cashback offered", step=50)

    if st.button("➕ Add another deal", key=f"cf_add_{GEN}"):
        scenarios.append(dict(FIXED_TEMPLATE, name=f"Deal {len(scenarios) + 1}"))
        st.rerun()
    st.divider()

    st.markdown("###### Summary")
    cols = st.columns(len(scenarios))
    dfs = {}
    costs = {}
    for idx, sc in enumerate(scenarios):
        principal = sc["loan"] + sc["fee"] if sc["addfee"] else sc["loan"]
        df = build_schedule(principal, sc["rate"], sc["term"] * 12, date.today(), method="daily_actual")
        dfs[sc["name"]] = df
        fixed_months = int(min(sc["fixed_years"] * 12, len(df)))
        cost = df.iloc[:fixed_months]["Payment"].sum() + (0 if sc["addfee"] else sc["fee"]) - sc["cashback"]
        costs[sc["name"]] = cost
        with cols[idx]:
            st.markdown(f"**{sc['name']}**")
            st.metric("Monthly", fmt(df.iloc[0]["Payment"]))
            st.metric(f"True cost ({sc['fixed_years']:g}y)", fmt(cost))

    cheapest = min(costs, key=costs.get)
    st.markdown(f'<div class="verdict-card">💡 <b>{cheapest}</b> costs least over its own fixed period — remember fixed periods may differ in length.</div>', unsafe_allow_html=True)
    combined = pd.concat([df.assign(Scenario=name) for name, df in dfs.items()], ignore_index=True)
    csv_button(combined, "compare_fixed_combined.csv", "⬇️ Combined CSV (all deals)")


# ---------------------------------------------------------------------------
# Ditch your fix — N options
# ---------------------------------------------------------------------------

def module_ditchfix():
    scenarios = get_scenarios("ditchfix")
    for i, sc in enumerate(list(scenarios)):
        with st.expander(f"✏️ {sc['name']}", expanded=(len(scenarios) <= 1)):
            h1, h2 = st.columns([4, 1])
            with h1:
                sc_text("ditchfix", i, "name", "Option name")
            with h2:
                st.write("")
                if len(scenarios) > 1 and st.button("🗑 Remove", key=f"df_rm_{i}_{GEN}"):
                    scenarios.pop(i)
                    st.rerun()
            c1, c2 = st.columns(2)
            with c1:
                sc_money("ditchfix", i, "balance", "Remaining balance", step=1000)
                sc_stepper("ditchfix", i, "remterm", "Remaining overall term (years)", step=0.5, min_value=1, max_value=40, decimals=1, suffix=" yrs")
                sc_stepper("ditchfix", i, "monthsleft", "Months left on current fix", step=1, min_value=1, max_value=60, decimals=0)
                sc_stepper("ditchfix", i, "crate", "Current rate (%)", step=0.05, min_value=0, max_value=25, decimals=2, suffix="%")
            with c2:
                sc_stepper("ditchfix", i, "erc", "Early repayment charge (%)", step=0.25, min_value=0, max_value=15, decimals=2, suffix="%", help=GLOSSARY["ERC"])
                sc_stepper("ditchfix", i, "nrate", "New rate (%)", step=0.05, min_value=0, max_value=25, decimals=2, suffix="%")
                sc_money("ditchfix", i, "nfees", "New deal fees", step=50)

    if st.button("➕ Add another option", key=f"df_add_{GEN}"):
        scenarios.append(dict(DITCH_TEMPLATE, name=f"Option {len(scenarios) + 1}"))
        st.rerun()
    st.divider()

    st.markdown("###### Summary")
    cols = st.columns(len(scenarios))
    bar_names, bar_vals, bar_colors = [], [], []
    for idx, sc in enumerate(scenarios):
        months_left = int(sc["monthsleft"])
        stay = build_schedule(sc["balance"], sc["crate"], int(sc["remterm"] * 12), date.today(), method="daily_actual")
        switch = build_schedule(sc["balance"], sc["nrate"], int(sc["remterm"] * 12), date.today(), method="daily_actual")
        stay_cost = stay.iloc[:months_left]["Interest"].sum()
        switch_cost = switch.iloc[:months_left]["Interest"].sum() + sc["balance"] * sc["erc"] / 100 + sc["nfees"]
        saving = stay_cost - switch_cost
        with cols[idx]:
            st.markdown(f"**{sc['name']}**")
            st.metric("Stay cost", fmt(stay_cost))
            st.metric("Switch cost", fmt(switch_cost))
            st.metric("Net saving", fmt(saving))
        bar_names += [f"{sc['name']}: Stay", f"{sc['name']}: Switch"]
        bar_vals += [stay_cost, switch_cost]
        bar_colors += ["#9aa0a6", PALETTE[idx % len(PALETTE)]]

    fig = go.Figure(go.Bar(x=bar_names, y=bar_vals, marker_color=bar_colors))
    fig.update_layout(height=300, margin=dict(t=10, b=10, l=10, r=10), yaxis_title=f"Cost over remaining fix ({CUR()})",
                       xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
    st.plotly_chart(fig, use_container_width=True, config=SVG_CONFIG)


# ---------------------------------------------------------------------------
# How much can I borrow — N scenarios
# ---------------------------------------------------------------------------

def module_borrow():
    scenarios = get_scenarios("borrow")
    for i, sc in enumerate(list(scenarios)):
        with st.expander(f"✏️ {sc['name']}", expanded=(len(scenarios) <= 1)):
            h1, h2 = st.columns([4, 1])
            with h1:
                sc_text("borrow", i, "name", "Scenario name")
            with h2:
                st.write("")
                if len(scenarios) > 1 and st.button("🗑 Remove", key=f"hb_rm_{i}_{GEN}"):
                    scenarios.pop(i)
                    st.rerun()
            c1, c2 = st.columns(2)
            with c1:
                sc_money("borrow", i, "inc1", "Applicant 1 income", step=1000)
                sc_money("borrow", i, "inc2", "Applicant 2 income", step=1000)
            with c2:
                sc_stepper("borrow", i, "mult", "Income multiple", step=0.1, min_value=2.5, max_value=6, decimals=1, suffix="×", help=GLOSSARY["Income multiple"])
                sc_money("borrow", i, "deposit", "Deposit available", step=1000)

    if st.button("➕ Add another scenario", key=f"hb_add_{GEN}"):
        scenarios.append(dict(BORROW_TEMPLATE, name=f"Scenario {len(scenarios) + 1}"))
        st.rerun()
    st.divider()

    st.markdown("###### Summary")
    cols = st.columns(len(scenarios))
    names, loans, deposits = [], [], []
    for idx, sc in enumerate(scenarios):
        max_loan = (sc["inc1"] + sc["inc2"]) * sc["mult"]
        max_price = max_loan + sc["deposit"]
        with cols[idx]:
            st.markdown(f"**{sc['name']}**")
            st.metric("Max loan", fmt(max_loan))
            st.metric("Max property price", fmt(max_price))
        names.append(sc["name"])
        loans.append(max_loan)
        deposits.append(sc["deposit"])

    fig = go.Figure()
    fig.add_trace(go.Bar(y=names, x=loans, name="Loan", orientation="h", marker_color=PRIMARY))
    fig.add_trace(go.Bar(y=names, x=deposits, name="Deposit", orientation="h", marker_color=ACCENT))
    fig.update_layout(barmode="stack", height=120 + 40 * len(scenarios), margin=dict(t=10, b=10, l=10, r=10), xaxis_title=f"({CUR()})",
                       xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
    st.plotly_chart(fig, use_container_width=True, config=SVG_CONFIG)
    st.caption("Rough guide only — actual affordability depends on lender stress tests, outgoings, and credit history.")


MODULE_FUNCS = {
    "basic": module_basic, "compare2": module_compare2, "overpay": module_overpay,
    "offset": module_offset, "deposit": module_deposit, "comparefixed": module_comparefixed,
    "ditchfix": module_ditchfix, "borrow": module_borrow,
}


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
                if r3.button("Load", key=f"loadbtn_{sess['name']}"):
                    st.session_state.state = copy.deepcopy(sess["state"])
                    st.session_state.currency_choice = sess.get("currency", st.session_state.currency_choice)
                    st.session_state.visible_calcs = sess.get("visible_calcs", st.session_state.visible_calcs)
                    st.session_state.gen += 1
                    st.success(f"Loaded '{sess['name']}'.")
                    st.rerun()
                if r4.button("🗑️", key=f"delbtn_{sess['name']}"):
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
# Page
# ---------------------------------------------------------------------------

st.title("🏡 Mortgage Dashboard")
st.caption(
    "All calculators on one page — toggle the ones you need, add as many mortgages to a calculator as "
    "you want to compare on the same plot. Every chart's camera icon exports SVG; every table exports CSV."
)

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
