"""Extract invoice fields from the text of a WSL outbound invoice PDF.

Every outbound invoice comes out of NetSuite on one template, so this reads that layout
directly rather than guessing across vendors' layouts (as invoice_tracking's parser must):

    WORLD SURF LEAGUE / address
    Invoice
    INV7025
    Bill To Invoice Date Terms Due Date
    <customer>                          <- first line after the header
    <customer address lines>
    10/1/2026 [Net 30] 11/1/2026         <- invoice date, optional terms, due date
    ...
    Amount Due €287 500,00 EUR
    PO # ...
    Memo
    <memo>
    Remit To ...                         <- WSL's bank details: never read

An invoice is only "confident" when every required field was found; anything else is flagged
with the reasons and never guessed.
"""

import re
import unicodedata
from datetime import datetime

FIELD_LABELS = {
    "customer": "customer",
    "invoice_number": "invoice number",
    "invoice_date": "invoice date",
    "amount": "amount",
}
# The due date is read when the invoice states one, but is not required: an invoice with
# no due date is still outstanding, just never overdue.

TEMPLATE_MARK = "world surf league"
MIN_READABLE_CHARS = 30

INVOICE_NUMBER = re.compile(r"^INV-?\d+$", re.IGNORECASE)
FILENAME_NUMBER = re.compile(r"\b(INV-?\d+)\.pdf$", re.IGNORECASE)
HEADER = re.compile(r"^bill to\b.*\binvoice date\b", re.IGNORECASE)
DATE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")
# NetSuite keeps one customer record per billing currency, e.g. "Montres TUDOR SA_EUR".
CURRENCY_SUFFIX = re.compile(r"_[A-Z]{3}$")
AMOUNT_DUE = re.compile(r"^amount due\b\s*(.*)$", re.IGNORECASE)
PO_NUMBER = re.compile(r"^PO\s*#\s*(.*)$", re.IGNORECASE)
# Everything from here on is WSL's own bank details.
REMIT_TO = re.compile(r"^remit to\b", re.IGNORECASE)

SYMBOLS = {"€": "EUR", "£": "GBP", "¥": "JPY", "A$": "AUD", "AU$": "AUD", "C$": "CAD", "NZ$": "NZD", "$": "USD"}
MONEY = re.compile(r"(?P<symbol>[A-Z]{0,2}\$|[€£¥])?\s*(?P<number>\d[\d.,\s]*\d|\d)\s*(?P<code>[A-Z]{3})?\b")


def _normalize(text):
    """Fold ligatures (ﬁ) and non-breaking spaces so label matching is predictable."""
    return unicodedata.normalize("NFKC", text or "")


def _lines(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    end = next((i for i, line in enumerate(lines) if REMIT_TO.match(line)), len(lines))
    return lines[:end]


def _iso(value):
    return datetime.strptime(value, "%m/%d/%Y").date().isoformat()


def parse_money(text):
    """(amount, currency code) from a figure like "€287 500,00 EUR" or "$42,000.00".

    Handles both "1,234.56" and the European "1.234,56" / "1 234,56". The currency is the
    trailing ISO code when there is one, else the symbol's; None when neither is shown.
    """
    match = MONEY.search(_normalize(text))
    if not match:
        return None, None
    number = re.sub(r"\s", "", match["number"])
    if re.search(r",\d{2}$", number):  # decimal comma
        number = number.replace(".", "").replace(",", ".")
    else:
        number = number.replace(",", "")
    currency = match["code"] or SYMBOLS.get(match["symbol"] or "")
    return float(number), currency


def _find_invoice_number(lines, filename):
    for i, line in enumerate(lines[:-1]):
        if line.lower() == "invoice" and INVOICE_NUMBER.match(lines[i + 1]):
            return lines[i + 1]
    match = FILENAME_NUMBER.search(filename or "")
    return match.group(1) if match else None


def _bill_to_block(lines):
    """(customer, invoice date, terms, due date) from the block under the "Bill To" header."""
    start = next((i for i, line in enumerate(lines) if HEADER.match(line)), None)
    if start is None:
        return None, None, None, None
    block = lines[start + 1:]
    at = next((i for i, line in enumerate(block) if DATE.search(line)), None)
    customer = block[0] if block and at != 0 else None
    if customer:
        customer = CURRENCY_SUFFIX.sub("", customer).strip() or None
    if at is None:
        return customer, None, None, None
    date_line = block[at]
    dates = DATE.findall(date_line)
    terms = DATE.sub("", date_line).strip() or None
    invoice_date = _iso(dates[0])
    due_date = _iso(dates[1]) if len(dates) > 1 else None
    return customer, invoice_date, terms, due_date


def _find_amount(lines):
    for line in lines:
        match = AMOUNT_DUE.match(line)
        if match:
            return parse_money(match.group(1))
    return None, None


def _find_po_number(lines):
    for line in lines:
        match = PO_NUMBER.match(line)
        if match:
            return match.group(1).strip() or None
    return None


def _find_memo(lines):
    for i, line in enumerate(lines[:-1]):
        if line.lower() == "memo":
            return lines[i + 1]
    return None


def _review_reasons(invoice, text):
    if len(text.strip()) < MIN_READABLE_CHARS:
        return ["no readable text in the PDF (scanned image?)"]
    if TEMPLATE_MARK not in text.lower():
        return ["not on WSL's invoice template (is this an outbound invoice?)"]
    return [f"no {label} found" for field, label in FIELD_LABELS.items() if invoice[field] in (None, "")]


def parse_invoice_text(text, filename=""):
    """Parse one invoice's text into fields plus a `needs_review` verdict."""
    text = _normalize(text)
    lines = _lines(text)
    customer, invoice_date, terms, due_date = _bill_to_block(lines)
    amount, currency = _find_amount(lines)
    invoice = {
        "customer": customer,
        "invoice_number": _find_invoice_number(lines, filename),
        "invoice_date": invoice_date,
        "terms": terms,
        "due_date": due_date,
        "amount": amount,
        "currency": currency or "USD",
        "memo": _find_memo(lines),
        "po_number": _find_po_number(lines),
    }
    invoice["review_reasons"] = _review_reasons(invoice, text)
    invoice["needs_review"] = bool(invoice["review_reasons"])
    return invoice


def parse_invoice_pdf(path):
    """Parse a PDF file on disk (see `parse_invoice_text`)."""
    from pathlib import Path

    from pypdf import PdfReader

    text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    return parse_invoice_text(text, Path(path).name)
