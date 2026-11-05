#!/usr/bin/env bash
# Instala la plataforma de procesamiento en la Raspberry Pi. Ejecutar en la Pi, desde esta carpeta, con el
# usuario que configuró InfluxDB (el CLI "influx" debe tener la configuración "administrador"):
#     bash instalar_procesamiento.sh
# Hace, de forma idempotente:
#   1. depósito cuarto_procesado sin límite de retención (el crudo "cuarto" conserva sus 90 días);
#   2. token del procesador: lectura de cuarto, lectura y escritura de cuarto_procesado, en
#      /etc/puente/procesador.env (solo si no existe);
#   3. entorno Python en /opt/procesador con pandas e influxdb-client, y el procesador;
#   4. servicio y temporizador de systemd (cada 10 min, últimos 30 min);
#   5. tareas Flux agregado_5m, resumen_1h y calidad_1h (se crean o se actualizan);
#   6. fuente de datos "InfluxDB procesado" en Grafana (token de solo lectura de los dos depósitos) y el
#      tablero procesado.json, si Grafana está instalado.
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
ORG="cuarto"
CRUDO="cuarto"
PROCESADO="cuarto_procesado"
ENV_PROC="/etc/puente/procesador.env"

echo "== 1. depósito $PROCESADO"
if ! influx bucket list --org "$ORG" --name "$PROCESADO" --hide-headers >/dev/null 2>&1; then
  influx bucket create --org "$ORG" --name "$PROCESADO" --retention 0 >/dev/null
  echo "   creado (retención: sin límite)"
else
  echo "   ya existe"
fi
ID_CRUDO="$(influx bucket list --org "$ORG" --name "$CRUDO" --hide-headers | awk '{print $1}')"
ID_PROC="$(influx bucket list --org "$ORG" --name "$PROCESADO" --hide-headers | awk '{print $1}')"

echo "== 2. token del procesador"
if [ ! -f "$ENV_PROC" ]; then
  TOKEN="$(influx auth create --org "$ORG" --description procesador \
     --read-bucket "$ID_CRUDO" --read-bucket "$ID_PROC" --write-bucket "$ID_PROC" --hide-headers | awk '{print $3}')"
  sudo install -d -o puente -g puente -m 750 /etc/puente
  sed "s#^INFLUX_TOKEN=.*#INFLUX_TOKEN=$TOKEN#" "$AQUI/procesador.env.ejemplo" | sudo tee "$ENV_PROC" >/dev/null
  sudo chown puente:puente "$ENV_PROC"; sudo chmod 600 "$ENV_PROC"
  echo "   creado en $ENV_PROC (no se muestra)"
else
  echo "   $ENV_PROC ya existe: se conserva"
fi

echo "== 3. entorno y programa en /opt/procesador"
sudo install -d -o puente -g puente /opt/procesador
sudo install -o puente -g puente -m 644 "$AQUI/procesador.py" "$AQUI/requirements.txt" /opt/procesador/
[ -x /opt/procesador/.venv/bin/python ] || sudo -u puente python3 -m venv /opt/procesador/.venv
sudo -u puente /opt/procesador/.venv/bin/pip install --quiet -r /opt/procesador/requirements.txt
echo "   pandas $(sudo -u puente /opt/procesador/.venv/bin/python -c 'import pandas; print(pandas.__version__)')"

echo "== 4. servicio y temporizador"
sudo install -m 644 "$AQUI/procesador.service" /etc/systemd/system/procesador.service
sudo install -m 644 "$AQUI/procesador.timer" /etc/systemd/system/procesador.timer
sudo systemctl daemon-reload
sudo systemctl enable --now procesador.timer >/dev/null
echo "   temporizador: $(systemctl is-active procesador.timer)"

echo "== 5. tareas Flux"
for archivo in "$AQUI"/tareas/*.flux; do
  nombre="$(basename "$archivo" .flux)"
  id="$(influx task list --org "$ORG" --hide-headers 2>/dev/null | awk -v n="$nombre" '$2==n {print $1}' | head -1)"
  if [ -n "$id" ]; then
    influx task update --id "$id" --file "$archivo" >/dev/null && echo "   $nombre actualizada"
  else
    influx task create --org "$ORG" --file "$archivo" >/dev/null && echo "   $nombre creada"
  fi
done
influx task list --org "$ORG"

echo "== 6. Grafana: fuente de datos y tablero del procesado"
if [ -d /etc/grafana/provisioning/datasources ] && [ -f "$AQUI/grafana/datasource_procesado.yaml" ]; then
  FUENTE=/etc/grafana/provisioning/datasources/influx_procesado.yaml
  if [ ! -f "$FUENTE" ]; then
    TOKEN_G="$(influx auth create --org "$ORG" --description grafana-procesado \
       --read-bucket "$ID_CRUDO" --read-bucket "$ID_PROC" --hide-headers | awk '{print $3}')"
    sed "s/__TOKEN__/$TOKEN_G/" "$AQUI/grafana/datasource_procesado.yaml" | sudo tee "$FUENTE" >/dev/null
    sudo chmod 640 "$FUENTE"; sudo chown root:grafana "$FUENTE"
    echo "   fuente de datos creada"
  else
    echo "   fuente de datos ya existe: se conserva"
  fi
  sudo install -d -o grafana -g grafana /var/lib/grafana/dashboards/cuarto
  sudo install -o grafana -g grafana -m 644 "$AQUI/grafana/procesado.json" /var/lib/grafana/dashboards/cuarto/procesado.json
  sudo systemctl restart grafana-server
  for i in $(seq 1 30); do curl -sf http://localhost:3000/api/health >/dev/null && break; sleep 2; done
  echo "   grafana-server: $(systemctl is-active grafana-server). Tablero: http://$(hostname -I | awk '{print $1}'):3000/d/procesado"
else
  echo "   sin Grafana o sin grafana/datasource_procesado.yaml: se omite"
fi

echo "== primera corrida del procesador sobre las últimas 24 h"
sudo -u puente \
  /opt/procesador/.venv/bin/python /opt/procesador/procesador.py --influx --ventana 24h --config "$ENV_PROC" | tail -25
echo "listo. Ver: systemctl list-timers procesador.timer; journalctl -u procesador -n 20"
