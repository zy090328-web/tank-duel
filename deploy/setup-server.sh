#!/usr/bin/env bash
# Sets up Graph Paper Tank Duel on a fresh Ubuntu server (e.g. a Hong Kong cloud server).
# Run as root:  curl -fsSL https://raw.githubusercontent.com/zy090328-web/tank-duel/main/deploy/setup-server.sh | bash
# Afterwards the game is at http://<server-ip>/ and it updates itself from GitHub every 5 minutes.
set -euo pipefail

REPO=https://github.com/zy090328-web/tank-duel
DIR=/opt/tank-duel

echo "== installing git, curl and Node.js 20"
apt-get update -y
apt-get install -y git curl ca-certificates
if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 18 ]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

echo "== fetching the game"
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull --ff-only; else git clone --depth 1 "$REPO" "$DIR"; fi

echo "== running it as a service on port 80"
cat > /etc/systemd/system/tank-duel.service <<EOF
[Unit]
Description=Graph Paper Tank Duel relay
After=network-online.target

[Service]
WorkingDirectory=$DIR
Environment=PORT=80
ExecStart=$(command -v node) server.js
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

echo "== checking GitHub for updates every 5 minutes"
cat > /usr/local/bin/tank-duel-update <<EOF
#!/usr/bin/env bash
cd $DIR || exit 0
before=\$(git rev-parse HEAD)
git pull --ff-only -q || exit 0
[ "\$(git rev-parse HEAD)" != "\$before" ] && systemctl restart tank-duel
exit 0
EOF
chmod +x /usr/local/bin/tank-duel-update
cat > /etc/systemd/system/tank-duel-update.service <<EOF
[Unit]
Description=Pull Tank Duel updates from GitHub
[Service]
Type=oneshot
ExecStart=/usr/local/bin/tank-duel-update
EOF
cat > /etc/systemd/system/tank-duel-update.timer <<EOF
[Unit]
Description=Pull Tank Duel updates every 5 minutes
[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now tank-duel.service tank-duel-update.timer
sleep 2
if curl -fsS http://127.0.0.1/relay.json >/dev/null; then
  ip=$(curl -fsS -4 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
  echo
  echo "== done. Open http://$ip/ in a browser."
  echo "   If it does not load, open port 80 (HTTP) in the server's firewall settings in the cloud console."
else
  echo "== the service did not start; showing its log:"
  journalctl -u tank-duel -n 30 --no-pager
fi
