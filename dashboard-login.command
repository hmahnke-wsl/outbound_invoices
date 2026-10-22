#!/bin/zsh
#
# dashboard-login.command -- launches Outbound Invoices with the LDAP login gate
# on (:5041 API, :3041 web app, reachable on the office network), for demoing
# sign-in. Double-click from Finder. Needs the corporate network/VPN.
# See dashboard.command.
#
DASHBOARD_LOGIN=1 exec "${0:A:h}/dashboard.command"
