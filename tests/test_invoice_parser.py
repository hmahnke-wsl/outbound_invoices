"""Tests for code/invoice_parser.py against WSL's NetSuite invoice template."""

from pathlib import Path

import pytest

from invoice_parser import normalize_customer, parse_invoice_text, parse_money

FIXTURES = Path(__file__).parent / "fixtures"
TUDOR = (FIXTURES / "tudor_inv7025.txt").read_text()
TUDOR_FILE = "Tudor - 2026-2027 Nazare Sponsorship (1 of 2) - INV7025.pdf"


def _usd_invoice(date_line="9/15/2026 Net 30 10/15/2026", amount_line="Amount Due $42,000.00"):
    """The same template as the Tudor invoice, for a US customer billed in dollars."""
    return f"""WORLD SURF LEAGUE
4840 Alla Road, Suite 200
Los Angeles, CA 90066
Invoice
INV7100
1 of 1
Bill To Invoice Date Terms Due Date
Acme Beverage Co
123 Main St
Austin, TX 78701
{date_line}
Description Quantity Price Amount
2026 Event Sponsorship
1 $42,000.00 $42,000.00
Total $42,000.00
{amount_line}
PO # 4500123
Memo
2026 Event Sponsorship
Remit To
Association of Surfing Professionals LLC
"""


def test_reads_every_field_from_the_tudor_invoice():
    invoice = parse_invoice_text(TUDOR, TUDOR_FILE)
    assert invoice["customer"] == "Montres TUDOR SA"
    assert invoice["invoice_number"] == "INV7025"
    assert invoice["invoice_date"] == "2026-10-01"
    assert invoice["due_date"] == "2026-11-01"
    assert invoice["terms"] is None
    assert invoice["amount"] == 287500.00
    assert invoice["currency"] == "EUR"
    assert invoice["memo"] == "2026/2027 Nazare Sponsorship (1 of 2)"
    assert invoice["po_number"] is None
    assert invoice["needs_review"] is False
    assert invoice["review_reasons"] == []


def test_never_reads_the_remit_to_bank_details():
    invoice = parse_invoice_text(TUDOR, TUDOR_FILE)
    assert not any("0000000000" in str(value) for value in invoice.values())


def test_reads_terms_between_the_dates_and_a_dollar_amount():
    invoice = parse_invoice_text(_usd_invoice())
    assert invoice["customer"] == "Acme Beverage Co"
    assert invoice["invoice_number"] == "INV7100"
    assert invoice["invoice_date"] == "2026-09-15"
    assert invoice["terms"] == "Net 30"
    assert invoice["due_date"] == "2026-10-15"
    assert invoice["amount"] == 42000.00
    assert invoice["currency"] == "USD"
    assert invoice["po_number"] == "4500123"
    assert invoice["needs_review"] is False


def test_a_missing_due_date_is_not_flagged():
    invoice = parse_invoice_text(_usd_invoice(date_line="9/15/2026"))
    assert invoice["invoice_date"] == "2026-09-15"
    assert invoice["due_date"] is None
    assert invoice["needs_review"] is False


def test_a_missing_amount_is_flagged_not_guessed():
    invoice = parse_invoice_text(_usd_invoice(amount_line="Amount Due"))
    assert invoice["amount"] is None
    assert invoice["review_reasons"] == ["no amount found"]
    assert invoice["needs_review"] is True


def test_invoice_number_falls_back_to_the_file_name():
    text = TUDOR.replace("INV7025\n", "")
    invoice = parse_invoice_text(text, TUDOR_FILE)
    assert invoice["invoice_number"] == "INV7025"


def test_a_scan_with_no_text_is_flagged():
    invoice = parse_invoice_text("  \n ", "scan.pdf")
    assert invoice["review_reasons"] == ["no readable text in the PDF (scanned image?)"]


def test_another_companys_invoice_is_flagged():
    invoice = parse_invoice_text("ACME SUPPLY INC\nInvoice\nINV-1\nTotal $10.00\n" + "x" * 40)
    assert "not on WSL's invoice template" in invoice["review_reasons"][0]
    assert invoice["needs_review"] is True


@pytest.mark.parametrize("text, expected", [
    ("€287 500,00 EUR", (287500.00, "EUR")),
    ("€287\xa0500,00", (287500.00, "EUR")),
    ("$42,000.00", (42000.00, "USD")),
    ("$42,000.00 USD", (42000.00, "USD")),
    ("£1.234,56", (1234.56, "GBP")),
    ("A$5,000.00 AUD", (5000.00, "AUD")),
    ("12,500.00", (12500.00, None)),
    ("€0,00", (0.0, "EUR")),
    ("", (None, None)),
])
def test_parse_money(text, expected):
    assert parse_money(text) == expected


@pytest.mark.parametrize("raw, name", [
    ("Montres TUDOR SA_EUR", "Montres TUDOR SA"),
    ("OMD Digital_AU", "OMD Digital"),
    ("OCEANPTEVENTS, SA_USD", "OCEANPTEVENTS, SA"),
    ("Vissla_210", "Vissla"),
    ("Huntington Surf & Sport_315", "Huntington Surf & Sport"),
    ("Florence Marine X - 210", "Florence Marine X"),
    ("Rip Curl International Pty Ltd_210 (EUR)", "Rip Curl International Pty Ltd"),
    ("Rip Curl (Merchandise)_AUD", "Rip Curl (Merchandise)"),
    ("Upper Deck (DO NOT USE)", "Upper Deck (DO NOT USE)"),
    ("GLOBO COMUNICAÇÃO E PARTICIPAÇÕES S.A", "GLOBO COMUNICAÇÃO E PARTICIPAÇÕES S.A"),
    ("  ", None),
])
def test_normalizes_netsuite_customer_names(raw, name):
    assert normalize_customer(raw) == name
