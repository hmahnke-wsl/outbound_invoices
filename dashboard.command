#!/bin/zsh
#
# dashboard.command -- launches the Outbound Invoices dashboard.
#
# Double-click from Finder (works from any location -- it resolves its own
# directory first). It:
#   1. boots the API (FastAPI, code/api.py) on $PORT_API
#   2. boots the web app (Vite dev server) on $PORT_WEB
#   3. opens the dashboard in your default browser once both are ready
#   4. on Ctrl+C / closing this window, stops both cleanly
#
# Ports come from ports.env (3040/5040); each repo in ../PORTS.md has its own
# block so every dashboard can run at once.
#
# Set DASHBOARD_LOGIN=1 (or double-click dashboard-login.command) to run with
# the LDAP login gate on instead, on $PORT_API_LOGIN/$PORT_WEB_LOGIN,
# against WSL's directory.
# If this dashboard is already running, it says so and exits rather than
# starting a conflicting second copy.
#
set -u

PROJECT_DIR="${0:A:h}"
cd "$PROJECT_DIR" || {
  print -u2 "dashboard.command: cannot cd to $PROJECT_DIR"
  exit 1
}

source ./ports.env  # this repo's port block -- see ../PORTS.md

LOGIN_MODE="${DASHBOARD_LOGIN:-0}"
if [[ "$LOGIN_MODE" == "1" ]]; then
  BACKEND_PORT=$PORT_API_LOGIN
  FRONTEND_PORT=$PORT_WEB_LOGIN
else
  BACKEND_PORT=$PORT_API
  FRONTEND_PORT=$PORT_WEB
fi

pause() {
  print ""
  print -n "Press any key to close this window... "
  read -k1 -s 2>/dev/null
  print ""
}

# true (exit 0) if something is listening on the port.
port_in_use() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN -t >/dev/null 2>&1
}

# SIGTERM a process and every descendant (uvicorn and vite each spawn children).
kill_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    kill_tree "$child"
  done
  kill -TERM "$pid" 2>/dev/null
}

# Wait until something listens on PORT, or fail after TIMEOUT seconds.
wait_for_port() {
  local port="$1" timeout="$2" start=$SECONDS
  while ! port_in_use "$port"; do
    (( SECONDS - start >= timeout )) && return 1
    sleep 0.2
  done
  return 0
}

if [[ "$LOGIN_MODE" == "1" ]]; then
  print "Outbound Invoices (login demo -- LDAP sign-in required)"
else
  print "Outbound Invoices"
fi
print "  project: $PROJECT_DIR"
print ""

if ! command -v uv >/dev/null 2>&1; then
  print -u2 "uv is not installed (or not on PATH). See README.md for first-time setup."
  pause
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  print -u2 "npm is not installed (or not on PATH)."
  pause
  exit 1
fi
if [[ ! -d web/node_modules ]]; then
  print -u2 "Web app dependencies aren't installed."
  print -u2 "Run 'npm install' in web/ (see README.md), then re-launch."
  pause
  exit 1
fi

busy=()
port_in_use "$BACKEND_PORT" && busy+=("API (port $BACKEND_PORT)")
port_in_use "$FRONTEND_PORT" && busy+=("web app (port $FRONTEND_PORT)")
if (( ${#busy} > 0 )); then
  print -u2 "dashboard.command: already running -- ${(j:, :)busy} still in use."
  print -u2 "Close the other dashboard window first, or wait for it to shut down."
  pause
  exit 1
fi

backend_log="$(mktemp -t outbound_invoices_api.XXXXXX)"
frontend_log="$(mktemp -t outbound_invoices_web.XXXXXX)"

BACKEND_PID=""
FRONTEND_PID=""
cleaned_up=0
cleanup() {
  (( cleaned_up )) && return
  cleaned_up=1
  print ""
  print "Shutting down..."
  [[ -n "$BACKEND_PID" ]] && kill_tree "$BACKEND_PID"
  [[ -n "$FRONTEND_PID" ]] && kill_tree "$FRONTEND_PID"
  rm -f "$backend_log" "$frontend_log"
}
# INT/TERM exit (the EXIT trap cleans up) instead of returning into the port
# watch below, which would report "stopped unexpectedly" and wait for a key.
# server_ops/auto_deploy.sh stops a dashboard this way before restarting it.
trap cleanup EXIT
trap "exit 0" INT TERM

print "Starting API on :$BACKEND_PORT ..."
if [[ "$LOGIN_MODE" == "1" ]]; then
  # Login demo: same settings as the api-wsl-ldap preview config. Needs the
  # corporate network/VPN to reach SMCADC1. The certificate check is off and
  # the session secret is fresh per launch, so restarting signs everyone out.
  SESSION_SECRET="$(openssl rand -hex 32)" \
  SESSION_COOKIE_SECURE=false \
  LDAP_URL=ldaps://SMCADC1.corp.worldsurfleague.com \
  LDAP_TLS_VERIFY=false \
  LDAP_USER_TEMPLATE='{username}@worldsurfleague.com' \
  uv run uvicorn api:build_app --factory --app-dir code --port "$BACKEND_PORT" \
    >"$backend_log" 2>&1 &
else
  # AUTH_DISABLED: this launcher is the operator's own Mac -- the LDAP login
  # gate is for the IT-hosted deployment.
  AUTH_DISABLED=true uv run uvicorn api:build_app --factory --app-dir code --port "$BACKEND_PORT" \
    >"$backend_log" 2>&1 &
fi
BACKEND_PID=$!

if ! wait_for_port "$BACKEND_PORT" 30; then
  print -u2 ""
  print -u2 "API didn't come up within 30s. Last output:"
  print -u2 "-------------------------------------------"
  tail -n 20 "$backend_log" >&2
  pause
  exit 1
fi
print "API ready."

print "Starting web app on :$FRONTEND_PORT ..."
# Login mode listens on the office network too (--host) so colleagues can try
# the sign-in; the API stays on 127.0.0.1 and is reached via Vite's proxy.
# Plain HTTP: only use this on a network you trust.
host_args=()
[[ "$LOGIN_MODE" == "1" ]] && host_args=(--host)
(cd web && API_PORT="$BACKEND_PORT" npm run dev -- --port "$FRONTEND_PORT" --strictPort "${host_args[@]}") \
  >"$frontend_log" 2>&1 &
FRONTEND_PID=$!

if ! wait_for_port "$FRONTEND_PORT" 20; then
  print -u2 ""
  print -u2 "Web app didn't come up within 20s. Last output:"
  print -u2 "-----------------------------------------------"
  tail -n 20 "$frontend_log" >&2
  pause
  exit 1
fi
print "Web app ready."

# DASHBOARD_NO_BROWSER=1: set by server_ops/auto_deploy.sh when it restarts a
# dashboard on the server, where a new browser tab per deploy is clutter.
if [[ "${DASHBOARD_NO_BROWSER:-0}" != "1" ]]; then
  print ""
  print "Opening http://localhost:$FRONTEND_PORT"
  open "http://localhost:$FRONTEND_PORT"
fi
if [[ "$LOGIN_MODE" == "1" ]]; then
  lan_ip="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)"
  if [[ -n "$lan_ip" ]]; then
    print "Others on the network: http://$lan_ip:$FRONTEND_PORT"
  fi
fi

print ""
print "Dashboard running. Close this window (or Ctrl+C) to stop it."

# Watch the ports, not the PIDs: `uv run` can outlive the uvicorn it started.
while port_in_use "$BACKEND_PORT" && port_in_use "$FRONTEND_PORT"; do
  sleep 0.5
done
if port_in_use "$BACKEND_PORT"; then
  print -u2 ""
  print -u2 "Web app stopped unexpectedly. Last output:"
  print -u2 "------------------------------------------"
  tail -n 20 "$frontend_log" >&2
else
  print -u2 ""
  print -u2 "API stopped unexpectedly. Last output:"
  print -u2 "--------------------------------------"
  tail -n 20 "$backend_log" >&2
fi
pause
exit 1
