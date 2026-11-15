"""Biweekly Bill Tracker — Streamlit UI.

Run with:  streamlit run bill_tracker_app.py
(Install Streamlit first:  pip install streamlit)

All state lives in bill_tracker_data.json next to this file, seeded from
the live Biweekly Bill Tracker on first launch.
"""

import os
from datetime import date

import streamlit as st

import bill_tracker_model as m

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = m.data_path(APP_DIR)

st.set_page_config(page_title="Biweekly Bill Tracker", layout="wide")


# ---------------------------------------------------------------------------
# Data loading / saving
# ---------------------------------------------------------------------------

def load() -> m.TrackerData:
    if "data" not in st.session_state:
        st.session_state.data = m.load_data(DATA_FILE)
    return st.session_state.data


def save(data: m.TrackerData) -> None:
    m.save_data(data, DATA_FILE)


def purge_checkbox_state() -> None:
    """Drop persisted checkbox widget state so boxes re-render from data.

    Streamlit keeps a checkbox's value in session state by key across
    reruns, so changing the data alone would leave old checkmarks visible.
    """
    for k in [k for k in st.session_state.keys()
              if k.startswith(("bill_", "groc_", "recv_"))]:
        del st.session_state[k]


data = load()
settings = data.settings


# ---------------------------------------------------------------------------
# Month navigation
# ---------------------------------------------------------------------------

if "view_year" not in st.session_state or "view_month" not in st.session_state:
    today = date.today()
    st.session_state.view_year, st.session_state.view_month = today.year, today.month

vy, vm = st.session_state.view_year, st.session_state.view_month
month_label = date(vy, vm, 1).strftime("%B %Y")

st.title("💸 Biweekly Bill Tracker")

nav_l, nav_c, nav_r = st.columns([1, 3, 1])
with nav_l:
    if st.button("◀ Prev", use_container_width=True):
        if vm == 1:
            st.session_state.view_year, st.session_state.view_month = vy - 1, 12
        else:
            st.session_state.view_month = vm - 1
        st.rerun()
with nav_c:
    st.markdown(f"<h3 style='text-align:center'>{month_label}</h3>",
                unsafe_allow_html=True)
with nav_r:
    if st.button("Next ▶", use_container_width=True):
        if vm == 12:
            st.session_state.view_year, st.session_state.view_month = vy + 1, 1
        else:
            st.session_state.view_month = vm + 1
        st.rerun()

vy, vm = st.session_state.view_year, st.session_state.view_month
paydays = m.paydays_in_month(data, vy, vm)


# ---------------------------------------------------------------------------
# Sidebar: settings + CSV export
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("⚙️ Settings")

    paycheck = st.number_input("Paycheck amount ($)", min_value=0.0,
                               value=settings.paycheck_amount_cents / 100,
                               step=50.0, format="%.2f")
    grocery = st.number_input("Groceries per paycheck ($)", min_value=0.0,
                              value=settings.grocery_amount_cents / 100,
                              step=25.0, format="%.2f")
    anchor = st.text_input("Payday anchor (YYYY-MM-DD)",
                           value=settings.payday_anchor)

    if st.button("Save settings"):
        settings.paycheck_amount_cents = round(paycheck * 100)
        settings.grocery_amount_cents = round(grocery * 100)
        settings.payday_anchor = anchor.strip()
        save(data)
        st.success("Settings saved.")
        st.rerun()

    st.divider()
    st.header(f"📅 {month_label}")
    st.caption("Checking and credit card debt are tracked per month — "
               "a new month starts at $0. Changes save automatically.")
    m_check, m_debt = m.get_month_finances(data, vy, vm)

    def _save_month_finances():
        # on_change runs before the script re-executes; the widget's new
        # value is already in session state under its key.
        m.set_month_finances(
            data, vy, vm,
            round(st.session_state[f"mcheck_{vy}-{vm}"] * 100),
            round(st.session_state[f"mdebt_{vy}-{vm}"] * 100))
        save(data)

    st.number_input("Checking balance ($)",
                    value=m_check / 100,
                    step=50.0, format="%.2f",
                    key=f"mcheck_{vy}-{vm}",
                    on_change=_save_month_finances)
    st.number_input("Credit card debt ($)", min_value=0.0,
                    value=m_debt / 100,
                    step=50.0, format="%.2f",
                    key=f"mdebt_{vy}-{vm}",
                    on_change=_save_month_finances)

    st.divider()
    st.header("📥 Export")
    csv_text = m.build_csv(data, vy, vm, date.today())
    fname = f"bill_tracker_{vy}-{vm:02d}.csv"
    st.download_button("Save to CSV", data=csv_text, file_name=fname,
                       mime="text/csv", use_container_width=True)

    st.divider()
    st.header("🗑 Data")
    if st.session_state.get("confirm_clear"):
        st.warning("Delete ALL bills and clear every paid checkmark? "
                   "Settings are kept.")
        cc1, cc2 = st.columns(2)
        if cc1.button("Yes, clear", use_container_width=True):
            data.bills = []
            data.paid_keys = set()
            data.received_paychecks = set()
            save(data)
            purge_checkbox_state()
            st.session_state.confirm_clear = False
            st.rerun()
        if cc2.button("Cancel", use_container_width=True):
            st.session_state.confirm_clear = False
            st.rerun()
    elif st.session_state.get("confirm_uncheck"):
        st.warning("Uncheck every bill, grocery item, and 'already received' "
                   "box? Bills and settings stay put.")
        uc1, uc2 = st.columns(2)
        if uc1.button("Yes, uncheck all", use_container_width=True):
            data.paid_keys = set()
            data.received_paychecks = set()
            save(data)
            purge_checkbox_state()
            st.session_state.confirm_uncheck = False
            st.rerun()
        if uc2.button("Cancel", use_container_width=True):
            st.session_state.confirm_uncheck = False
            st.rerun()
    else:
        if st.button("Clear all checkmarks", use_container_width=True):
            st.session_state.confirm_uncheck = True
            st.rerun()
        if st.button("Clear all bills", use_container_width=True):
            st.session_state.confirm_clear = True
            st.rerun()


# ---------------------------------------------------------------------------
# Monthly cash flow
# ---------------------------------------------------------------------------

cf = m.monthly_cash_flow(data, paydays, vy, vm, date.today())
st.subheader("Monthly cash flow")
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Upcoming income", m.cents_to_str(cf["income_cents"]))
c2.metric("Checking", m.cents_to_str(cf["checking_cents"]))
c3.metric("CC debt", m.cents_to_str(-cf["debt_cents"]))
c4.metric("Unpaid bills", m.cents_to_str(-cf["unpaid_bills_cents"]))
c5.metric("Unpaid groceries", m.cents_to_str(-cf["unpaid_groceries_cents"]))
net = cf["net_cents"]
c6.metric("Net cash flow", m.cents_to_str(net),
          delta="OK" if net >= 0 else "OVER", delta_color="normal" if net >= 0 else "inverse")
st.divider()


# ---------------------------------------------------------------------------
# Paycheck columns
# ---------------------------------------------------------------------------

assign_labels = {m.ASSIGN_FIRST: "First paycheck",
                 m.ASSIGN_SECOND: "Second paycheck",
                 m.ASSIGN_DUE: "By due date"}

# Single Add bill form (used to be one per paycheck column).
with st.expander("➕ Add bill"):
    with st.form("add_bill"):
        name = st.text_input("Name")
        amount = st.text_input("Amount ($)", value="0.00")
        due_day = st.number_input("Due day of month", min_value=1,
                                  max_value=31, value=1)
        assignment = st.selectbox("Paycheck",
                                  options=list(assign_labels),
                                  format_func=assign_labels.get)
        autopay = st.checkbox("Autopay")
        if st.form_submit_button("Add"):
            try:
                cents = m.parse_money_to_cents(amount)
                m.add_bill(data, name or "Untitled", cents,
                           int(due_day), assignment, autopay)
                save(data)
                st.success(f"Added {name}.")
                st.rerun()
            except ValueError as e:
                st.error(f"Bad amount: {e}")

cols = st.columns(len(paydays)) if paydays else []

for i, payday in enumerate(paydays):
    summ = m.paycheck_summary(data, paydays, i, vy, vm)
    with cols[i]:
        st.markdown(f"### Paycheck {i + 1} — {payday.strftime('%a %b %d')}")
        st.caption(f"Income: {m.cents_to_str(summ['income_cents'])}")

        recv = st.checkbox("Already received",
                           value=summ["received"],
                           key=f"recv_{vy}-{vm}-{payday.isoformat()}")
        if recv != summ["received"]:
            m.toggle_paycheck_received(data, payday)
            save(data)
            st.rerun()

        st.markdown("**Bills**")
        for b in summ["bills"]:
            paid = m.is_bill_paid(data, b.id)
            badge = " 🔁" if b.is_autopay else ""
            label = f"{b.name}{badge} — {m.cents_to_str(b.amount_cents)} (due {b.due_day})"
            new_val = st.checkbox(label, value=paid,
                                  key=f"bill_{vy}-{vm}-{payday.isoformat()}-{b.id}")
            if new_val != paid:
                m.toggle_bill_paid(data, b.id)
                save(data)
                st.rerun()

        st.markdown("**Groceries**")
        for g_idx, g in enumerate(summ["groceries"]):
            glabel = f"{g['label']} — {m.cents_to_str(g['amount_cents'])}"
            new_val = st.checkbox(glabel, value=g["paid"],
                                  key=f"groc_{vy}-{vm}-{payday.isoformat()}-{g_idx}")
            if new_val != g["paid"]:
                m.toggle_grocery_paid(data, payday, g_idx)
                save(data)
                st.rerun()

        st.markdown("---")
        st.write(f"Expenses: **{m.cents_to_str(summ['expenses_cents'])}**")
        st.write(f"Paid: {m.cents_to_str(summ['paid_cents'])} · "
                 f"Outstanding: {m.cents_to_str(summ['unpaid_cents'])}")
        rem = summ["remaining_cents"]
        st.write(f"Planned surplus: "
                 f"{':green[' if rem >= 0 else ':red['}"
                 f"{m.cents_to_str(rem)}]")


# ---------------------------------------------------------------------------
# Manage bills (edit / delete)
# ---------------------------------------------------------------------------

st.divider()
with st.expander("🛠 Manage bills (edit / delete)"):
    if not data.bills:
        st.write("No bills yet.")
    for b in sorted(data.bills, key=lambda x: x.id):
        with st.expander(f"{b.name} — {m.cents_to_str(b.amount_cents)}"):
            with st.form(f"edit_{b.id}"):
                name = st.text_input("Name", value=b.name)
                amount = st.text_input("Amount ($)",
                                       value=f"{b.amount_cents / 100:.2f}")
                due_day = st.number_input("Due day of month", min_value=1,
                                          max_value=31, value=b.due_day)
                assignment = st.selectbox(
                    "Paycheck", options=list(assign_labels),
                    index=list(assign_labels).index(b.assignment),
                    format_func=assign_labels.get)
                autopay = st.checkbox("Autopay", value=b.is_autopay)
                c_save, c_del = st.columns(2)
                do_save = c_save.form_submit_button("Save changes")
                do_del = c_del.form_submit_button("Delete bill")
                if do_save:
                    try:
                        m.update_bill(data, b.id, name=name.strip() or b.name,
                                      amount_cents=m.parse_money_to_cents(amount),
                                      due_day=int(due_day),
                                      assignment=assignment, is_autopay=autopay)
                        save(data)
                        st.success("Saved.")
                        st.rerun()
                    except ValueError as e:
                        st.error(f"Bad amount: {e}")
                if do_del:
                    m.delete_bill(data, b.id)
                    save(data)
                    st.success(f"Deleted {b.name}.")
                    st.rerun()

st.caption("Data auto-saves to bill_tracker_data.json in this folder.")
