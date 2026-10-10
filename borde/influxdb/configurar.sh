#!/usr/bin/env bash
# Configuración inicial de InfluxDB 2: organización, depósito con 90 días y token para el puente y Grafana.
set -euo pipefail
ORG="cuarto"
DEPOSITO="cuarto"
RETENCION="90d"
read -rp "usuario administrador de InfluxDB: " USUARIO
read -rsp "contraseña: " CLAVE; echo

influx setup --force --org "$ORG" --bucket "$DEPOSITO" --retention "$RETENCION" \
  --username "$USUARIO" --password "$CLAVE" --name administrador >/dev/null

ID_DEPOSITO="$(influx bucket list --org "$ORG" --name "$DEPOSITO" --hide-headers | awk '{print $1}')"
TOKEN="$(influx auth create --org "$ORG" --description puente \
  --read-bucket "$ID_DEPOSITO" --write-bucket "$ID_DEPOSITO" --hide-headers | awk '{print $3}')"

echo
echo "Token del puente (guardar en borde/puente/puente.env como INFLUX_TOKEN):"
echo "$TOKEN"

if [ -d /etc/grafana/provisioning/datasources ]; then
  sed "s/__TOKEN__/$TOKEN/" "$(dirname "$0")/../grafana/datasource.yaml" | sudo tee /etc/grafana/provisioning/datasources/influx.yaml >/dev/null
  sudo systemctl restart grafana-server
  echo "Fuente de datos de Grafana aprovisionada."
fi
