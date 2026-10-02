#!/bin/bash
# Installs the read-only host status collector for Ten druhý's watchdog (systemd timer, every 5 min, as root).
# Writes /opt/tendruhy/data/state/host.json; the app only reads it. Idempotent. Run with sudo from this directory.
set -euo pipefail
install -m 755 "$(dirname "$0")/tendruhy-hoststatus.py" /usr/local/bin/tendruhy-hoststatus
cat > /etc/systemd/system/tendruhy-hoststatus.service <<'UNIT'
[Unit]
Description=Ten druhy host status collector (read-only)
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/tendruhy-hoststatus
Nice=10
UNIT
cat > /etc/systemd/system/tendruhy-hoststatus.timer <<'UNIT'
[Unit]
Description=Ten druhy host status every 5 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now tendruhy-hoststatus.timer
systemctl start tendruhy-hoststatus.service
ls -la /opt/tendruhy/data/state/host.json
systemctl list-timers tendruhy-hoststatus.timer --no-pager | head -3
