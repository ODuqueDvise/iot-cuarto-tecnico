#!/usr/bin/env bash
# Memoria disponible y los procesos que más consumen. Anotar el resultado en docs/bitacora.md.
echo "== free -m"; free -m
echo; echo "== zram"; zramctl 2>/dev/null || true
echo; echo "== procesos por memoria residente (MB)"
ps -eo rss,comm --sort=-rss | awk 'NR==1{print "RSS_MB COMANDO"; next} NR<=12{printf "%6.0f %s\n", $1/1024, $2}'
echo; echo "== temperatura del SoC"; vcgencmd measure_temp 2>/dev/null || true
