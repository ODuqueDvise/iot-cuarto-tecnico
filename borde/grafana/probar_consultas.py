# -*- coding: utf-8 -*-
"""Ejecuta en la Pi cada consulta Flux del tablero contra InfluxDB, con las variables de Grafana reemplazadas.

    python3 probar_consultas.py nodo_sensor.json [nodo1]

Usa la CLI `influx` ya configurada para el usuario. Informa por panel si la consulta corre y cuántas filas devuelve;
una consulta con error de sintaxis o de tipos aparece aquí antes de verla vacía en Grafana.
"""
import json
import subprocess
import sys

archivo = sys.argv[1]
nodo = sys.argv[2] if len(sys.argv) > 2 else "nodo1"
tablero = json.load(open(archivo, encoding="utf-8"))
fallas = 0
for p in tablero["panels"]:
    for t in p.get("targets", []):
        q = (t["query"].replace("v.timeRangeStart, stop: v.timeRangeStop", "-30m")
             .replace("v.windowPeriod", "1m").replace("${nodo}", nodo))
        r = subprocess.run(["influx", "query", "--raw", q], capture_output=True, text=True)
        filas = [l for l in r.stdout.splitlines() if l and not l.startswith("#") and not l.startswith(",result")]
        if r.returncode != 0 or "error" in r.stderr.lower():
            fallas += 1
            print(f"FALLA  {p['title']}: {r.stderr.strip()[:200]}")
        else:
            print(f"ok     {p['title']}: {len(filas)} filas")
print("\nTodas las consultas corren" if fallas == 0 else f"\n{fallas} consultas con error")
sys.exit(1 if fallas else 0)
