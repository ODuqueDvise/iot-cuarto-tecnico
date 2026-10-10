#!/usr/bin/env bash
# Instala el puente como servicio de systemd con usuario propio. Ejecutar con sudo desde borde/puente.
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
CERTS="$AQUI/../certificados/salida"
[ -f "$AQUI/puente.env" ] || { echo "falta puente.env (copiar de puente.env.ejemplo)"; exit 1; }
id puente >/dev/null 2>&1 || useradd --system --home /opt/puente --shell /usr/sbin/nologin puente
install -d -o puente -g puente /opt/puente /etc/puente
install -o puente -g puente -m 644 "$AQUI/puente.py" "$AQUI/requirements.txt" /opt/puente/
install -o puente -g puente -m 600 "$AQUI/puente.env" /etc/puente/puente.env
install -o puente -g puente -m 640 "$CERTS/ca.crt" "$CERTS/borde-puente.crt" "$CERTS/borde-puente.key" /etc/puente/
sudo -u puente python3 -m venv /opt/puente/.venv
sudo -u puente /opt/puente/.venv/bin/pip install --quiet -r /opt/puente/requirements.txt
install -m 644 "$AQUI/puente.service" /etc/systemd/system/puente.service
systemctl daemon-reload
systemctl enable --now puente
systemctl status puente --no-pager
