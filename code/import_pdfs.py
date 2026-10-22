"""Import invoice PDFs from a folder: parse each one, keep a copy, and store it.

A stand-in for the Gmail ingest until the email forwarding workflow is set up. The dashboard's
Refresh runs the same import over INBOX_DIR (default `sample_docs/`).

    uv run python code/import_pdfs.py [folder]
"""

import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from db import DEFAULT_DB, PROJECT_ROOT, init_db, record_refresh, save_parsed_invoice
from invoice_parser import parse_invoice_pdf

DEFAULT_INBOX = os.environ.get("INBOX_DIR") or os.path.join(PROJECT_ROOT, "sample_docs")
DEFAULT_ATTACHMENTS = os.path.join(PROJECT_ROOT, "attachments")


def import_folder(conn, folder=DEFAULT_INBOX, attachments_dir=DEFAULT_ATTACHMENTS, now=None):
    """Import every PDF in `folder`. Returns {"saved", "flagged", "new_invoice_ids"}."""
    now = now or datetime.now().astimezone().isoformat(timespec="seconds")
    Path(attachments_dir).mkdir(parents=True, exist_ok=True)
    result = {"saved": 0, "flagged": 0, "new_invoice_ids": []}
    for path in sorted(Path(folder).glob("*.pdf"), key=lambda p: p.name):
        parsed = parse_invoice_pdf(path)
        parsed["source_file"] = path.name
        shutil.copy2(path, Path(attachments_dir) / path.name)
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
        invoice_id, created = save_parsed_invoice(conn, parsed, pdf_file=path.name, sent_at=modified, now=now)
        if created:
            result["new_invoice_ids"].append(invoice_id)
        result["flagged" if parsed["needs_review"] else "saved"] += 1
    return result


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_INBOX
    conn = init_db(DEFAULT_DB)
    result = import_folder(conn, folder)
    record_refresh(conn, datetime.now().astimezone().isoformat(timespec="seconds"))
    print(f"{result['saved']} read cleanly, {result['flagged']} need attention, "
          f"{len(result['new_invoice_ids'])} new")


if __name__ == "__main__":
    main()
