#!/bin/bash
# Instala en la Raspberry Pi el tablero "Operación del cuarto técnico" y, si existe /etc/grafana/correo.env, las seis
# reglas de alerta con envío por correo (Actividad 5). Lo ejecuta herramientas/nodo.sh operacion desde el Mac, sobre los
# archivos copiados a /tmp/operacion_nueva.
#
#   1. comprobaciones: Grafana activo y fuente "InfluxDB procesado" instalada (nodo.sh procesamiento)
#   2. cada consulta del tablero y de las alertas contra InfluxDB (últimos 30 min); luego el tablero sobre 7 días,
#      solo para medir tiempos
#   3. tablero en /var/lib/grafana/dashboards/cuarto (carpeta "Cuarto técnico", proveedor de nodo.sh panel)
#   4. límite de memoria de Grafana (memoria.conf), correo: drop-in de systemd que carga /etc/grafana/correo.env (600, root) y reglas en
#      /etc/grafana/provisioning/alerting/cuarto.yaml con la dirección de destino
#   5. reinicio de Grafana y revisión del registro
#
# Nunca imprime la contraseña ni el contenido de correo.env.
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
ENV=/etc/grafana/correo.env
ALERTAS=/etc/grafana/provisioning/alerting/cuarto.yaml

echo "== 1. Comprobaciones"
systemctl is-active --quiet grafana-server || { echo "grafana-server no está activo"; exit 1; }
sudo test -f /etc/grafana/provisioning/datasources/influx_procesado.yaml \
    || { echo "falta la fuente InfluxDB procesado: correr antes nodo.sh procesamiento"; exit 1; }
echo "   memoria disponible: $(free -m | awk '/^Mem:/ {print $7}') MB"

echo "== 2. Consultas contra InfluxDB"
python3 "$AQUI/probar_consultas.py" "$AQUI/operacion.json"
python3 "$AQUI/probar_consultas.py" "$AQUI/consultas_alertas.json"
echo "-- tiempos con el rango por defecto del tablero (7 días):"
python3 "$AQUI/probar_consultas.py" "$AQUI/operacion.json" nodo1 -7d \
    || echo "   AVISO: alguna consulta falló sobre 7 días; el tablero se instala igual, revisar arriba"
echo "   memoria disponible después: $(free -m | awk '/^Mem:/ {print $7}') MB"

echo "== 3. Tableros"
sudo install -d -o grafana -g grafana /var/lib/grafana/dashboards/cuarto
sudo install -o grafana -g grafana -m 644 "$AQUI/operacion.json" /var/lib/grafana/dashboards/cuarto/operacion.json
sudo install -o grafana -g grafana -m 644 "$AQUI/procesado.json" /var/lib/grafana/dashboards/cuarto/procesado.json

echo "== 4. Límite de memoria de Grafana, correo y alertas"
sudo install -d /etc/systemd/system/grafana-server.service.d
sudo install -m 644 "$AQUI/memoria.conf" /etc/systemd/system/grafana-server.service.d/memoria.conf
CON_ALERTAS=no
if sudo test -f "$ENV"; then
    sudo chown root:root "$ENV"; sudo chmod 600 "$ENV"
    for v in GF_SMTP_ENABLED GF_SMTP_HOST GF_SMTP_USER GF_SMTP_PASSWORD GF_SMTP_FROM_ADDRESS CORREO_DESTINO; do
        sudo grep -q "^$v=." "$ENV" || { echo "   falta $v en $ENV"; exit 1; }
    done
    if sudo grep -q "ejemplo.com\|contraseña_de_aplicacion" "$ENV"; then
        echo "   $ENV todavía tiene valores del ejemplo"; exit 1
    fi
    DESTINO="$(sudo sed -n 's/^CORREO_DESTINO=//p' "$ENV" | head -1 | tr -d '"' | tr -d "'")"
    sudo install -d /etc/systemd/system/grafana-server.service.d
    sudo install -m 644 "$AQUI/correo.conf" /etc/systemd/system/grafana-server.service.d/correo.conf
    sudo mkdir -p /etc/grafana/provisioning/alerting
    sed "s|__CORREO_DESTINO__|$DESTINO|" "$AQUI/alertas.yaml" | sudo tee "$ALERTAS" >/dev/null
    sudo chown root:grafana "$ALERTAS"; sudo chmod 640 "$ALERTAS"
    echo "   reglas instaladas; destinatarios: $(echo "$DESTINO" | tr ';' '\n' | grep -c @)"
    CON_ALERTAS=si
else
    echo "   no existe $ENV: se instala solo el tablero (ver correo.env.ejemplo)"
fi

echo "== 5. Reinicio de Grafana"
sudo systemctl daemon-reload
sudo systemctl restart grafana-server
for _ in $(seq 1 45); do curl -sf http://localhost:3000/api/health >/dev/null && break; sleep 2; done
echo "   grafana-server: $(systemctl is-active grafana-server)"
PID="$(systemctl show -p MainPID --value grafana-server)"
echo "   GOMEMLIMIT en Grafana: $(sudo cat "/proc/$PID/environ" | tr '\0' '\n' | grep '^GOMEMLIMIT=' | cut -d= -f2)"
echo "   memoria de Grafana al arrancar: $(ps -o rss= -p "$PID" | awk '{printf "%d MB", $1/1024}')"
if [ "$CON_ALERTAS" = si ]; then
    echo "   variables de correo cargadas en Grafana: $(sudo cat "/proc/$PID/environ" | tr '\0' '\n' | grep -c '^GF_SMTP_')"
fi
echo "-- errores del proceso nuevo de Grafana (vacío es bueno; los del apagado del anterior no cuentan):"
sudo journalctl -u grafana-server --since "-2 min" --no-pager | grep "grafana\[$PID\]" \
    | grep -iE 'level=error|provision.*(fail|error)|alert.*(fail|error)|smtp.*(fail|error)' | tail -10 || true
echo "Tablero: http://$(hostname -I | awk '{print $1}'):3000/d/operacion"
