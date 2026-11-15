# Biweekly Bill Tracker — Streamlit app

A desktop-web version of the Biweekly Bill Tracker, built with Streamlit.
Seeded with your October 2026 bills, paydays, and settings.

## Run it

1. Install Python 3.9+ (https://www.python.org/downloads/)
   ```
   winget install --id Python.Python.3.13 -e
   ```
2. Install Streamlit:
   ```
   pip install streamlit
   ```
3. From this folder, run:
   ```
   streamlit run bill_tracker_app.py
   ```
   Your browser opens the app automatically.

## Files

- `bill_tracker_app.py` — the Streamlit UI (run this)
- `bill_tracker_model.py` — data model + bill/cash-flow/CSV logic
- `test_model.py` — sanity tests for the model (`python3 test_model.py`)
- `bill_tracker_data.json` — created on first launch; holds your bills,
  paid checkmarks, and settings. Delete it to reset to the seed data.

## Features

- Per-paycheck bill checklists with Autopay 🔁 badges
- Two $250 grocery items per paycheck, checkable like bills
- "Already received" checkbox per paycheck (income excluded from cash flow
  so it isn't double-counted with your checking balance)
- Monthly cash-flow panel: upcoming paycheck income + checking balance −
  credit-card debt − unpaid bills − unpaid groceries
- Add / edit / delete bills; due-date bills auto-assign to a paycheck
  (rent and Nelnet stay on the second paycheck)
- Settings sidebar: paycheck amount, checking balance, CC debt, grocery
  budget, payday anchor
- **Save to CSV** button in the sidebar: downloads every bill and grocery
  line for the viewed month plus the cash-flow summary
- Month navigation (◀ Prev / Next ▶); everything auto-saves to the JSON file
