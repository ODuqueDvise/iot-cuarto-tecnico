#!/usr/bin/env bash
# Vuelve a correr las tres tareas Flux sobre un rango dado (por ejemplo, tras reprocesar el nivel limpio).
# Ejecutar en la Pi:  bash rehacer.sh 2026-11-04T22:00:00Z 2026-11-05T02:00:00Z
set -euo pipefail
DESDE="$1"; HASTA="$2"
AQUI="$(cd "$(dirname "$0")" && pwd)"
for t in agregado_5m resumen_1h calidad_1h; do
  sed -e '/^option task/d' -e "s#range(start: -[0-9hm]*)#range(start: $DESDE, stop: $HASTA)#" "$AQUI/$t.flux" > "/tmp/$t.rehacer.flux"
  influx query --org cuarto -f "/tmp/$t.rehacer.flux" >/dev/null && echo "$t rehecha de $DESDE a $HASTA"
done
