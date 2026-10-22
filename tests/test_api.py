"""End-to-end API tests: import the fixture invoices, then read, mark paid, fix and summarize."""

import pytest
from fastapi.testclient import TestClient

from api import create_app
from db import init_db, save_parsed_invoice
from invoice_parser import parse_invoice_text
from test_invoice_parser import TUDOR, TUDOR_FILE, _usd_invoice

NOW = "2026-10-22T09:00:00-07:00"


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "invoices.db"
    conn = init_db(path)
    for text, name in [(TUDOR, TUDOR_FILE), (_usd_invoice(), "acme.pdf"),
                       (_usd_invoice(amount_line="Amount Due").replace("INV7100", "INV7101"), "broken.pdf")]:
        parsed = parse_invoice_text(text, name) | {"source_file": name}
        save_parsed_invoice(conn, parsed, now=NOW)
    conn.close()
    return path


@pytest.fixture
def client(db_path, tmp_path):
    return TestClient(create_app(db_path, today="2026-10-22", now=NOW, attachments_dir=tmp_path,
                                 run_ingest=lambda conn, _: {"saved": 0, "flagged": 0, "new_invoice_ids": []}))


def _by_number(rows):
    return {r["invoice_number"]: r for r in rows}


def test_open_invoices_carry_overdue_and_days_open(client):
    rows = _by_number(client.get("/api/invoices").json())
    assert set(rows) == {"INV7025", "INV7100"}
    acme, tudor = rows["INV7100"], rows["INV7025"]
    assert acme["overdue"] is True and acme["days_open"] == 37  # 9/15 -> 10/22
    assert tudor["overdue"] is False and tudor["days_open"] == 21
    assert tudor["currency"] == "EUR"


def test_flagged_invoice_waits_in_needs_attention_until_fixed(client):
    [item] = client.get("/api/needs-attention").json()
    assert item["invoice_number"] == "INV7101" and item["reason"] == "no amount found"
    assert client.patch(f"/api/invoices/{item['id']}", json={"amount": 500}).status_code == 200
    assert client.get("/api/needs-attention").json() == []
    assert "INV7101" in _by_number(client.get("/api/invoices").json())


def test_mark_paid_moves_it_to_paid_with_history(client):
    acme = _by_number(client.get("/api/invoices").json())["INV7100"]
    assert client.patch(f"/api/invoices/{acme['id']}", json={"status": "paid"}).status_code == 400
    assert client.patch(f"/api/invoices/{acme['id']}", json={"status": "paid", "paid_at": "2026-10-20"}).status_code == 200
    assert "INV7100" not in _by_number(client.get("/api/invoices").json())
    paid = _by_number(client.get("/api/paid-invoices").json())["INV7100"]
    assert paid["paid_at"] == "2026-10-20" and paid["days_open"] == 35 and paid["overdue"] is False
    assert [h["status"] for h in client.get(f"/api/invoices/{acme['id']}/history").json()] == ["open", "paid"]
    # And back to open.
    client.patch(f"/api/invoices/{acme['id']}", json={"status": "open"})
    assert "INV7100" in _by_number(client.get("/api/invoices").json())


def test_history_orders_mixed_time_zones_by_instant(db_path, client):
    conn = init_db(db_path)
    # 08:00 Pacific is 15:00 UTC: after the 14:00 UTC import, though it sorts first as text.
    conn.execute("INSERT INTO status_history (invoice_id, status, changed_at, source) "
                 "VALUES (1, 'paid', '2026-10-23T08:00:00-07:00', 'manual'), (1, 'open', '2026-10-23T14:00:00+00:00', 'import')")
    conn.commit()
    conn.close()
    times = [h["changed_at"] for h in client.get("/api/invoices/1/history").json()]
    assert times[-2:] == ["2026-10-23T14:00:00+00:00", "2026-10-23T08:00:00-07:00"]


def test_summary_keeps_currencies_apart(client):
    summary = client.get("/api/summary").json()
    assert summary["outstanding"] == {"count": 2, "amounts": [{"currency": "USD", "amount": 42000.0},
                                                               {"currency": "EUR", "amount": 287500.0}]}
    assert summary["overdue"]["count"] == 1
    assert summary["days_overdue"]["days"] == 7  # due 10/15
    assert summary["days_open"] == {"days": 29.0, "based_on": 2}


def test_reimport_does_not_duplicate_or_undo_a_fix(db_path, client):
    item = client.get("/api/needs-attention").json()[0]
    client.patch(f"/api/invoices/{item['id']}", json={"amount": 500})
    conn = init_db(db_path)
    parsed = parse_invoice_text(_usd_invoice(amount_line="Amount Due").replace("INV7100", "INV7101"), "broken.pdf")
    _, created = save_parsed_invoice(conn, parsed | {"source_file": "broken.pdf"}, now=NOW)
    conn.close()
    assert created is False
    assert _by_number(client.get("/api/invoices").json())["INV7101"]["amount"] == 500


def test_only_flagged_invoices_can_be_ignored(client):
    acme = _by_number(client.get("/api/invoices").json())["INV7100"]
    assert client.patch(f"/api/invoices/{acme['id']}", json={"ignored": True}).status_code == 400
    item = client.get("/api/needs-attention").json()[0]
    assert client.patch(f"/api/invoices/{item['id']}", json={"ignored": True}).status_code == 200
    assert client.get("/api/needs-attention").json() == []
    assert len(client.get("/api/ignored").json()) == 1
