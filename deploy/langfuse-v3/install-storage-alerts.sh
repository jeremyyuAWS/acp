#!/usr/bin/env bash
# Run on the existing telemetry VM as root. Does not modify retained telemetry.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
install -m 0755 "$HERE/storage_check.py" /usr/local/bin/acp-telemetry-storage-check
cat > /etc/systemd/system/acp-telemetry-storage.service <<'UNIT'
[Unit]
Description=ACP telemetry disk space and inode alerts
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/acp-telemetry-storage-check
User=root
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
StandardOutput=journal
StandardError=journal
SyslogIdentifier=acp-telemetry-storage
SyslogLevelPrefix=true
UNIT
cat > /etc/systemd/system/acp-telemetry-storage.timer <<'UNIT'
[Unit]
Description=Check retained telemetry capacity every five minutes

[Timer]
OnBootSec=1min
OnCalendar=*:0/5
Persistent=true

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now acp-telemetry-storage.timer
# A critical initial reading remains visible as a failed service, not a false successful install.
systemctl start acp-telemetry-storage.service
