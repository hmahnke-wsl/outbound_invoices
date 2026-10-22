#!/bin/zsh
#
# import-netsuite.command -- imports NetSuite's invoice and payment exports.
#
# Double-click from Finder (works from any location -- it resolves its own
# directory first). It:
#   1. backs up invoices.db (invoices.db.bak-<date>-<time>, git-ignored)
#   2. imports the newest "Invoice History*" and "Payment History*" exports in
#      sample_docs/ (or $INBOX_DIR): uv run python code/import_netsuite.py
#   3. on success, opens the dashboard if it's running
#   4. on failure, prints a loud, visible message and keeps this window open
#
# Re-running on the same exports adds nothing. See HISTORY_BACKFILL.md.
#
set -u

PROJECT_DIR="${0:A:h}"
cd "$PROJECT_DIR" || {
  print -u2 "import-netsuite.command: cannot cd to $PROJECT_DIR"
  exit 1
}

source ./ports.env  # this repo's port block -- see ../PORTS.md

pause() {
  print ""
  print -n "Press any key to close this window... "
  read -k1 -s 2>/dev/null
  print ""
}

print "Outbound Invoices -- NetSuite import"
print "  project: $PROJECT_DIR"
print ""

if ! command -v uv >/dev/null 2>&1; then
  print -u2 "uv is not installed (or not on PATH). See README.md for first-time setup."
  pause
  exit 1
fi

# --- 1. back up the database (the import writes in one transaction, but a copy is cheap) ---
if [[ -f invoices.db ]]; then
  backup="invoices.db.bak-$(date +%Y%m%d-%H%M%S)"
  cp invoices.db "$backup"
  print "Backed up the database to $backup"
  print ""
fi

# --- 2. run the import ---------------------------------------------------------
uv run python code/import_netsuite.py
rc=$?

if [[ $rc -ne 0 ]]; then
  print ""
  print "***************************************************************"
  print "*  IMPORT FAILED (exit $rc)"
  print "*  See the messages above. Nothing was changed in the database."
  print "*  Check both exports are in sample_docs/, then re-run."
  print "***************************************************************"
  pause
  exit $rc
fi

# --- 3. show the result --------------------------------------------------------
print ""
if lsof -nP -iTCP:"$PORT_WEB" -sTCP:LISTEN -t >/dev/null 2>&1; then
  print "Opening the dashboard (refresh the page if it was already open)."
  open "http://localhost:$PORT_WEB"
else
  print "Double-click dashboard.command to see the result."
fi

pause
exit 0
