#!/usr/bin/env bash
# Installation complète sur Ubuntu 24.04 (Oracle ARM ou Hetzner). À lancer en root :
#   sudo bash deploy/setup.sh
set -euo pipefail
APP=/opt/clipper
SRC="$(cd "$(dirname "$0")/.." && pwd)"

apt-get update
apt-get install -y ffmpeg python3-venv fonts-dejavu-core caddy iptables-persistent curl

# Utilisateur dédié + code
id clipper >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin clipper
mkdir -p "$APP/data/out"
cp -r "$SRC/clipper" "$SRC/config.yaml" "$SRC/requirements.txt" "$APP/"
python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q --upgrade pip
"$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"
chown -R clipper:clipper "$APP"

# Ollama (modèle local pour les titres)
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:3b

# Préchargement du modèle Whisper (évite un premier run lent)
sudo -u clipper HOME="$APP" "$APP/.venv/bin/python" -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"

# HTTPS gratuit sans nom de domaine : <ip>.sslip.io + certificat Let's Encrypt via Caddy
IP=$(curl -s https://api.ipify.org)
DOMAIN="${IP//./-}.sslip.io"
cat > /etc/caddy/Caddyfile <<EOF
$DOMAIN {
    handle_path /v/* {
        root * $APP/data/out
        file_server
    }
    respond 404
}
EOF
# Les images Oracle bloquent 80/443 par défaut au niveau iptables
iptables -C INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null || iptables -I INPUT 6 -p tcp --dport 80 -j ACCEPT
iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || iptables -I INPUT 6 -p tcp --dport 443 -j ACCEPT
netfilter-persistent save
usermod -aG clipper caddy
chmod 750 "$APP/data" "$APP/data/out"
systemctl restart caddy

# Fichier de secrets
if [ ! -f /etc/clipper.env ]; then
    cp "$SRC/deploy/clipper.env.example" /etc/clipper.env
    sed -i "s#^PUBLIC_BASE_URL=.*#PUBLIC_BASE_URL=https://$DOMAIN/v#" /etc/clipper.env
    chmod 600 /etc/clipper.env
fi

cp "$SRC"/deploy/systemd/* /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now clipper-run.timer clipper-publish.timer clipper-recap.timer clipper-bot.service

echo "OK. URL publique des vidéos : https://$DOMAIN/v/"
echo "Reste à remplir /etc/clipper.env puis : systemctl restart clipper-bot"
