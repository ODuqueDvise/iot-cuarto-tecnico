#!/usr/bin/env bash
# Instalación del borde en Raspberry Pi OS Lite (64 bits), Raspberry Pi 4 de 1 GB.
# Ejecutar con sudo desde el directorio borde/ del repositorio.
set -euo pipefail

RED_IOT="192.168.50.0/24"   # subred de la VLAN de IoT; chrony solo atiende a esta red
AQUI="$(cd "$(dirname "$0")" && pwd)"

[ "$(id -u)" -eq 0 ] || { echo "ejecutar con sudo"; exit 1; }

echo "== Paquetes base"
apt-get update
apt-get install -y apt-transport-https wget gnupg curl zram-tools chrony mosquitto mosquitto-clients python3-venv python3-pip

echo "== Sin intercambio en la microSD; zram en su lugar"
systemctl disable --now dphys-swapfile 2>/dev/null || true
install -m 644 "$AQUI/sistema/zramswap" /etc/default/zramswap
systemctl restart zramswap

echo "== Registros del sistema en memoria"
install -d /etc/systemd/journald.conf.d
install -m 644 "$AQUI/sistema/journald-volatil.conf" /etc/systemd/journald.conf.d/volatil.conf
systemctl restart systemd-journald
install -m 644 "$AQUI/sistema/99-iot.conf" /etc/sysctl.d/99-iot.conf
sysctl --system >/dev/null

echo "== chrony sirve la hora a la VLAN de IoT"
grep -q "^allow $RED_IOT" /etc/chrony/chrony.conf || echo "allow $RED_IOT" >> /etc/chrony/chrony.conf
systemctl restart chrony

echo "== Mosquitto"
install -m 644 "$AQUI/mosquitto/iot.conf" /etc/mosquitto/conf.d/iot.conf
install -m 644 "$AQUI/mosquitto/acl.conf" /etc/mosquitto/acl.conf
# Arranca cuando existan los certificados (docs/02_borde.md)

echo "== Repositorio de InfluxData"
install -d /etc/apt/keyrings
curl --silent --location -o /tmp/influxdata-archive.key https://repos.influxdata.com/influxdata-archive.key
gpg --show-keys --with-fingerprint --with-colons /tmp/influxdata-archive.key 2>&1 \
  | grep -q '^fpr:\+24C975CBA61A024EE1B631787C3D57159FC2F927:$' \
  || { echo "la huella de la clave de InfluxData no coincide"; exit 1; }
gpg --dearmor < /tmp/influxdata-archive.key > /etc/apt/keyrings/influxdata-archive.gpg
echo 'deb [signed-by=/etc/apt/keyrings/influxdata-archive.gpg] https://repos.influxdata.com/debian stable main' > /etc/apt/sources.list.d/influxdata.list

echo "== Repositorio de Grafana"
wget -qO /etc/apt/keyrings/grafana.asc https://apt.grafana.com/gpg-full.key
chmod 644 /etc/apt/keyrings/grafana.asc
echo "deb [signed-by=/etc/apt/keyrings/grafana.asc] https://apt.grafana.com stable main" > /etc/apt/sources.list.d/grafana.list

apt-get update
apt-get install -y influxdb2 influxdb2-cli grafana

echo "== InfluxDB ajustado a 1 GB"
install -m 644 "$AQUI/influxdb/config.toml" /etc/influxdb/config.toml
systemctl enable --now influxdb
systemctl enable --now grafana-server

echo
echo "Listo. Siguiente: docs/02_borde.md (certificados, InfluxDB, puente)."
echo "Memoria actual:"
free -m
