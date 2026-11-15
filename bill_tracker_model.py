"""Data model and business logic for the Biweekly Bill Tracker.

Pure Python — no UI dependencies — so the logic can be tested directly.
The Streamlit UI lives in ``bill_tracker_app.py`` and imports from here.

Data file ``bill_tracker_data.json`` sits next to the app and is rewritten
on every change, so state survives between runs.
"""

import calendar
import csv
import io
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

DATA_FILENAME = "bill_tracker_data.json"

ASSIGN_FIRST = "first_paycheck"
ASSIGN_SECOND = "second_paycheck"
ASSIGN_DUE = "due_date"
ASSIGNMENTS = (ASSIGN_FIRST, ASSIGN_SECOND, ASSIGN_DUE)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def cents_to_str(cents: int) -> str:
    """123456 -> '$1,234.56' ; negative values show '-$1,234.56'."""
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


def parse_money_to_cents(text: str) -> int:
    """'$1,234.56' / '1234.56' / '85' -> cents. Raises ValueError on junk."""
    cleaned = re.sub(r"[$,\s]", "", (text or "").strip())
    if not cleaned:
        raise ValueError("empty amount")
    return int(round(float(cleaned) * 100))


def iso(d: date) -> str:
    return d.isoformat()


def bill_key(bill_id: int) -> str:
    return f"bill:{bill_id}"


def grocery_key(payday: date, idx: int) -> str:
    return f"grocery:{payday.isoformat()}:{idx}"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Bill:
    id: int
    name: str
    amount_cents: int
    due_day: int
    assignment: str = ASSIGN_DUE  # first_paycheck | second_paycheck | due_date
    is_autopay: bool = False


@dataclass
class Settings:
    paycheck_amount_cents: int = 270000
    # Legacy: checking/debt used to live here as single global values.
    # They are now tracked per month (see monthly_finances on TrackerData);
    # these fields are kept only so older data files still load.
    checking_balance_cents: int = 38500
    credit_card_debt_cents: int = 120500
    grocery_amount_cents: int = 50000
    payday_anchor: str = "2026-10-08"  # ISO date of a payday; repeats every 14 days


@dataclass
class TrackerData:
    settings: Settings = field(default_factory=Settings)
    bills: list = field(default_factory=list)            # list[Bill]
    paid_keys: set = field(default_factory=set)         # set[str]
    received_paychecks: set = field(default_factory=set)  # set of ISO pay dates
    # Per-month finances: "YYYY-MM" -> {"checking_cents": int, "debt_cents": int}.
    # A month with no entry starts at 0 for both.
    monthly_finances: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Seed data — mirrors the live Biweekly Bill Tracker (October 2026)
# ---------------------------------------------------------------------------

def seed_data() -> TrackerData:
    data = TrackerData()
    data.settings = Settings(
        paycheck_amount_cents=270000,
        checking_balance_cents=38500,
        credit_card_debt_cents=120500,
        grocery_amount_cents=50000,
        payday_anchor="2026-10-08",
    )
    seed_bills = [
        # id, name, amount_cents, due_day, assignment, autopay
        (1, "Nelnet", 12500, 27, ASSIGN_SECOND, False),
        (2, "Diapers", 8500, 1, ASSIGN_DUE, False),
        (3, "K loans", 94000, 1, ASSIGN_DUE, False),
        (4, "Heat", 39806, 1, ASSIGN_DUE, False),
        (5, "Electric", 30000, 1, ASSIGN_DUE, False),
        (6, "Sprint", 9400, 30, ASSIGN_DUE, True),
        (7, "Dog food", 5000, 1, ASSIGN_DUE, False),
        (8, "Rent", 140000, 1, ASSIGN_SECOND, False),
        (9, "Fidium", 8500, 21, ASSIGN_DUE, True),
        (10, "Peleton", 1500, 25, ASSIGN_DUE, True),
        (11, "Apple storage", 400, 25, ASSIGN_DUE, True),
    ]
    data.bills = [Bill(id=i, name=n, amount_cents=a, due_day=d,
                       assignment=asg, is_autopay=ap)
                  for (i, n, a, d, asg, ap) in seed_bills]
    # Paid state carried over from the live app.
    data.paid_keys = {"bill:2", "bill:4", "bill:7", "bill:11",
                      "grocery:2026-10-22:1"}
    data.received_paychecks = set()
    return data


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def data_path(app_dir: str) -> str:
    return os.path.join(app_dir, DATA_FILENAME)


def save_data(data: TrackerData, path: str) -> None:
    payload = {
        "settings": asdict(data.settings),
        "bills": [asdict(b) for b in data.bills],
        "paid_keys": sorted(data.paid_keys),
        "received_paychecks": sorted(data.received_paychecks),
        "monthly_finances": data.monthly_finances,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def load_data(path: str) -> TrackerData:
    """Load from disk; seeds with live-app data on first run."""
    if not os.path.exists(path):
        data = seed_data()
        save_data(data, path)
        return data
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    settings = Settings(**payload.get("settings", {}))
    bills = [Bill(**b) for b in payload.get("bills", [])]
    return TrackerData(
        settings=settings,
        bills=bills,
        paid_keys=set(payload.get("paid_keys", [])),
        received_paychecks=set(payload.get("received_paychecks", [])),
        monthly_finances=payload.get("monthly_finances", {}),
    )


# ---------------------------------------------------------------------------
# Payday math
# ---------------------------------------------------------------------------

def anchor_date(data: TrackerData) -> date:
    return date.fromisoformat(data.settings.payday_anchor)


def paydays_in_month(data: TrackerData, year: int, month: int) -> list:
    """All pay dates (from the 14-day cycle anchored at payday_anchor)
    whose date falls inside the given month."""
    first = date(year, month, 1)
    payday = anchor_date(data)
    # Step back to a payday on or before the 1st, then forward to the
    # latest such payday.
    while payday > first:
        payday -= timedelta(days=14)
    while payday + timedelta(days=14) <= first:
        payday += timedelta(days=14)
    # Move to the first payday actually inside the month.
    if payday < first:
        payday += timedelta(days=14)
    out = []
    while payday.year == year and payday.month == month:
        out.append(payday)
        payday += timedelta(days=14)
    return out


def window_end(paydays: list, idx: int) -> date:
    """End (exclusive) of a paycheck's coverage window."""
    if idx + 1 < len(paydays):
        return paydays[idx + 1]
    return paydays[idx] + timedelta(days=14)


# ---------------------------------------------------------------------------
# Bill assignment
# ---------------------------------------------------------------------------

def due_date_for(year: int, month: int, due_day: int) -> date:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(max(due_day, 1), last))


def assign_bill(bill: Bill, paydays: list, year: int, month: int) -> int:
    """Index into ``paydays`` for this bill.

    Explicit first/second-paycheck assignments win. Otherwise the bill
    lands on the paycheck whose coverage window contains its due date
    (due dates before the month's first payday go on paycheck 1).
    """
    if not paydays:
        return 0
    if bill.assignment == ASSIGN_FIRST:
        return 0
    if bill.assignment == ASSIGN_SECOND:
        return min(1, len(paydays) - 1)
    due = due_date_for(year, month, bill.due_day)
    for i in range(len(paydays)):
        if due < window_end(paydays, i):
            return i
    return len(paydays) - 1


def bills_for_paycheck(data: TrackerData, paydays: list, idx: int,
                       year: int, month: int) -> list:
    return sorted(
        (b for b in data.bills if assign_bill(b, paydays, year, month) == idx),
        key=lambda b: (b.due_day, b.name),
    )


# ---------------------------------------------------------------------------
# Paid / received state
# ---------------------------------------------------------------------------

def is_bill_paid(data: TrackerData, bill_id: int) -> bool:
    return bill_key(bill_id) in data.paid_keys


def toggle_bill_paid(data: TrackerData, bill_id: int) -> None:
    key = bill_key(bill_id)
    if key in data.paid_keys:
        data.paid_keys.discard(key)
    else:
        data.paid_keys.add(key)


def grocery_items(data: TrackerData, payday: date) -> list:
    """Two grocery items per paycheck; each is half the monthly setting."""
    half = data.settings.grocery_amount_cents // 2
    items = []
    for idx in range(2):
        amount = half + (data.settings.grocery_amount_cents % 2 if idx == 1 else 0)
        key = grocery_key(payday, idx)
        items.append({
            "label": f"Groceries #{idx + 1}",
            "amount_cents": amount,
            "paid": key in data.paid_keys,
            "key": key,
        })
    return items


def toggle_grocery_paid(data: TrackerData, payday: date, idx: int) -> None:
    key = grocery_key(payday, idx)
    if key in data.paid_keys:
        data.paid_keys.discard(key)
    else:
        data.paid_keys.add(key)


def is_paycheck_received(data: TrackerData, payday: date) -> bool:
    return payday.isoformat() in data.received_paychecks


def toggle_paycheck_received(data: TrackerData, payday: date) -> None:
    key = payday.isoformat()
    if key in data.received_paychecks:
        data.received_paychecks.discard(key)
    else:
        data.received_paychecks.add(key)


# ---------------------------------------------------------------------------
# Per-month finances (checking balance + credit card debt)
# ---------------------------------------------------------------------------

def month_key(year: int, month: int) -> str:
    return f"{year}-{month:02d}"


def get_month_finances(data: TrackerData, year: int, month: int) -> tuple:
    """(checking_cents, debt_cents) for a month; a month with no saved
    entry starts at 0 for both."""
    entry = data.monthly_finances.get(month_key(year, month), {})
    return entry.get("checking_cents", 0), entry.get("debt_cents", 0)


def set_month_finances(data: TrackerData, year: int, month: int,
                       checking_cents: int, debt_cents: int) -> None:
    data.monthly_finances[month_key(year, month)] = {
        "checking_cents": checking_cents,
        "debt_cents": debt_cents,
    }


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------

def paycheck_summary(data: TrackerData, paydays: list, idx: int,
                     year: int, month: int) -> dict:
    """Totals for one paycheck's column."""
    payday = paydays[idx]
    bills = bills_for_paycheck(data, paydays, idx, year, month)
    groceries = grocery_items(data, payday)
    income = data.settings.paycheck_amount_cents
    bill_total = sum(b.amount_cents for b in bills)
    grocery_total = sum(g["amount_cents"] for g in groceries)
    expenses = bill_total + grocery_total
    unpaid = (sum(b.amount_cents for b in bills if not is_bill_paid(data, b.id))
              + sum(g["amount_cents"] for g in groceries if not g["paid"]))
    paid = expenses - unpaid
    return {
        "payday": payday,
        "income_cents": income,
        "bills": bills,
        "groceries": groceries,
        "expenses_cents": expenses,
        "paid_cents": paid,
        "unpaid_cents": unpaid,
        "remaining_cents": income - expenses,   # planned surplus/deficit
        "received": is_paycheck_received(data, payday),
    }


def monthly_cash_flow(data: TrackerData, paydays: list, year: int, month: int,
                      today: date) -> dict:
    """Cash-flow math mirrors the live app:

    - only paychecks dated today or later count as upcoming income
    - a paycheck marked 'already received' is subtracted so it isn't
      double-counted with the checking balance
    - checked-off bills/groceries come out of the unpaid (outstanding) totals
    - checking balance and credit card debt are the *viewed month's* own
      values; a month with nothing saved starts at 0 for both
    """
    s = data.settings
    checking_cents, debt_cents = get_month_finances(data, year, month)
    upcoming = [p for p in paydays if p >= today]
    income = sum(s.paycheck_amount_cents for p in upcoming
                 if not is_paycheck_received(data, p))
    unpaid_bills = 0
    unpaid_groceries = 0
    for i, p in enumerate(paydays):
        for b in bills_for_paycheck(data, paydays, i, year, month):
            if not is_bill_paid(data, b.id):
                unpaid_bills += b.amount_cents
        for g in grocery_items(data, p):
            if not g["paid"]:
                unpaid_groceries += g["amount_cents"]
    net = (income + checking_cents - debt_cents
           - unpaid_bills - unpaid_groceries)
    return {
        "income_cents": income,
        "checking_cents": checking_cents,
        "debt_cents": debt_cents,
        "unpaid_bills_cents": unpaid_bills,
        "unpaid_groceries_cents": unpaid_groceries,
        "net_cents": net,
        "upcoming_count": len(upcoming),
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def next_bill_id(data: TrackerData) -> int:
    return max((b.id for b in data.bills), default=0) + 1


def add_bill(data: TrackerData, name: str, amount_cents: int, due_day: int,
             assignment: str, is_autopay: bool) -> Bill:
    bill = Bill(id=next_bill_id(data), name=name.strip(),
                amount_cents=amount_cents, due_day=due_day,
                assignment=assignment, is_autopay=is_autopay)
    data.bills.append(bill)
    return bill


def update_bill(data: TrackerData, bill_id: int, **changes) -> Bill:
    bill = next(b for b in data.bills if b.id == bill_id)
    for k, v in changes.items():
        setattr(bill, k, v)
    return bill


def delete_bill(data: TrackerData, bill_id: int) -> None:
    data.bills = [b for b in data.bills if b.id != bill_id]
    data.paid_keys.discard(bill_key(bill_id))


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def build_csv(data: TrackerData, year: int, month: int, today: date) -> str:
    """One CSV with every bill + grocery line, then a cash-flow summary."""
    paydays = paydays_in_month(data, year, month)
    month_label = date(year, month, 1).strftime("%B %Y")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Type", "Paycheck", "Pay date", "Item", "Amount",
                "Due day", "Autopay", "Paid"])
    for i, p in enumerate(paydays):
        tag = f"Paycheck {i + 1}"
        for b in bills_for_paycheck(data, paydays, i, year, month):
            w.writerow(["Bill", tag, p.isoformat(), b.name,
                        f"{b.amount_cents / 100:.2f}", b.due_day,
                        "yes" if b.is_autopay else "no",
                        "yes" if is_bill_paid(data, b.id) else "no"])
        for g in grocery_items(data, p):
            w.writerow(["Grocery", tag, p.isoformat(), g["label"],
                        f"{g['amount_cents'] / 100:.2f}", "",
                        "", "yes" if g["paid"] else "no"])
    cf = monthly_cash_flow(data, paydays, year, month, today)
    w.writerow([])
    w.writerow(["Monthly summary", month_label, "", "", "", "", "", ""])
    rows = [
        ("Upcoming paycheck income", cf["income_cents"]),
        ("Checking balance", cf["checking_cents"]),
        ("Credit card debt", -cf["debt_cents"]),
        ("Unpaid bills", -cf["unpaid_bills_cents"]),
        ("Unpaid groceries", -cf["unpaid_groceries_cents"]),
        ("Net cash flow", cf["net_cents"]),
    ]
    for label, cents in rows:
        w.writerow(["Summary", label, "", "", f"{cents / 100:.2f}",
                    "", "", ""])
    return buf.getvalue()
