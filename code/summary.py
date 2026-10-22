"""Topline figures for the dashboard's summary strip, computed from the open (unpaid) invoices.

Invoices are billed in several currencies (Tudor in EUR, most in USD), so money is never summed
across them: every total carries one amount per currency.
"""

from datetime import date

# Days past the due date. "Current" holds invoices not yet due and those with no due date.
AGING_BUCKETS = (("Current", None, 0), ("1-30 days", 1, 30), ("31-60 days", 31, 60),
                 ("61-90 days", 61, 90), ("90+ days", 91, None))

# Health thresholds as (green up to, amber up to); anything above is red. Placeholders until
# accounting sets its own targets.
OVERDUE_PCT = (9, 25)
DAYS_OVERDUE = (15, 30)
DAYS_OPEN = (30, 60)
STATUSES = ("good", "watch", "action")  # best to worst


def _total(invoices):
    amounts = {}
    for i in invoices:
        amounts[i["currency"]] = round(amounts.get(i["currency"], 0) + (i["amount"] or 0), 2)
    # USD first, then the larger balances.
    ordered = sorted(amounts.items(), key=lambda kv: (kv[0] != "USD", -kv[1]))
    return {"count": len(invoices), "amounts": [{"currency": c, "amount": a} for c, a in ordered]}


def days_past_due(invoice, today):
    return max((today - date.fromisoformat(invoice["due_date"])).days, 0) if invoice.get("due_date") else 0


def days_open(invoice, today):
    """Days from the invoice date until it was paid, or until today while it is open."""
    if not invoice.get("invoice_date"):
        return None
    end = date.fromisoformat(invoice["paid_at"]) if invoice.get("paid_at") else today
    return (end - date.fromisoformat(invoice["invoice_date"])).days


def _average(values):
    return {"days": round(sum(values) / len(values), 1) if values else None, "based_on": len(values)}


def _whole(value):
    """Rounded half up, as the dashboard rounds (Python's round() goes half to even)."""
    return int(value + 0.5)


def _rate(value, thresholds, reason):
    if value is None:
        return {"status": None, "reason": None}
    green_max, amber_max = thresholds
    status = "good" if value <= green_max else "watch" if value <= amber_max else "action"
    return {"status": status, "reason": reason.format(_whole(value))}


def summarize(invoices, today):
    """Totals, averages and aging for the open invoices (dicts from `db.list_open`). `today` is an ISO date."""
    today = date.fromisoformat(today)
    aging = []
    for label, low, high in AGING_BUCKETS:
        bucket = [i for i in invoices
                  if (low is None or days_past_due(i, today) >= low) and (high is None or days_past_due(i, today) <= high)]
        aging.append({"label": label, **_total(bucket)})
    overdue = [i for i in invoices if days_past_due(i, today) > 0]
    late = _average([days_past_due(i, today) for i in overdue])
    open_days = _average([d for d in (days_open(i, today) for i in invoices) if d is not None])

    pct = _whole(len(overdue) / len(invoices) * 100) if invoices else 0
    ratings = [_rate(pct, OVERDUE_PCT, "{}% of invoices overdue"), _rate(late["days"], DAYS_OVERDUE, "avg {} days past due")]
    worst = max((r["status"] for r in ratings if r["status"]), key=STATUSES.index)
    return {
        "outstanding": _total(invoices),
        "overdue": _total(overdue),
        "days_overdue": late,
        "days_open": open_days,
        "aging": aging,
        "health": {
            "overdue": {"status": worst, "reason": "; ".join(r["reason"] for r in ratings if r["status"] == worst)},
            "days_open": _rate(open_days["days"], DAYS_OPEN, "avg {} days open"),
        },
    }
