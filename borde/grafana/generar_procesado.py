#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Genera procesado.json, el tablero de Grafana del depósito procesado (Actividad 4).

    python3 generar_procesado.py > procesado.json

Usa la fuente de datos aprovisionada "InfluxDB procesado" (uid influx-procesado), cuyo token lee los dos
depósitos; así el panel de "antes y después" puede leer el crudo y el limpio a la vez.
"""
import json

DS = {"type": "influxdb", "uid": "influx-procesado"}
NODO = '"${nodo}"'


def consulta(medicion, campos, deposito="cuarto_procesado", extra=""):
    filtro = " or ".join(f'r._field == "{c}"' for c in campos)
    return (f'from(bucket: "{deposito}")\n'
            f'  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n'
            f'  |> filter(fn: (r) => r._measurement == "{medicion}" and r.nodo == {NODO})\n'
            f'  |> filter(fn: (r) => {filtro})\n{extra}'
            f'  |> keep(columns: ["_time", "_value", "_field"])')


def renombrar(nombres):
    cond = " else ".join(f'if r._field == "{k}" then "{v}"' for k, v in nombres.items())
    return f'  |> map(fn: (r) => ({{r with _field: {cond} else r._field}}))\n'


panel_id = 0


def panel(tipo, titulo, x, y, w, h, targets, unidad="none", opciones=None, campos=None, descripcion=""):
    global panel_id
    panel_id += 1
    p = {"id": panel_id, "type": tipo, "title": titulo, "description": descripcion, "datasource": DS,
         "gridPos": {"x": x, "y": y, "w": w, "h": h},
         "fieldConfig": {"defaults": {"unit": unidad, "custom": {"lineWidth": 1, "fillOpacity": 8, "showPoints": "never"}},
                         "overrides": []},
         "options": opciones or {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
         "targets": [{"refId": chr(65 + i), "datasource": DS, "query": q} for i, q in enumerate(targets)]}
    if campos:
        p["fieldConfig"]["defaults"].update(campos)
    return p


def fila(titulo, y):
    global panel_id
    panel_id += 1
    return {"id": panel_id, "type": "row", "title": titulo, "collapsed": False, "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}}


stat = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "colorMode": "value",
        "graphMode": "none", "textMode": "value_and_name", "justifyMode": "center"}
barras = {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}

panels = [
    fila("Agregados de 5 min (tarea agregado_5m)", 0),
    panel("timeseries", "Temperatura (media, mínimo y máximo de 5 min)", 0, 1, 8, 8,
          [consulta("telemetria_5m", ["t", "t_min", "t_max"]) ], "celsius"),
    panel("timeseries", "Humedad relativa (media, mínimo y máximo de 5 min)", 8, 1, 8, 8,
          [consulta("telemetria_5m", ["hr", "hr_min", "hr_max"])], "humidity"),
    panel("timeseries", "Corriente (media y máximo de 5 min)", 16, 1, 8, 8,
          [consulta("telemetria_5m", ["i", "i_max"])], "amp"),
    panel("timeseries", "Fracción del tiempo con puerta abierta y con agua", 0, 9, 8, 7,
          [consulta("telemetria_5m", ["puerta_fraccion", "agua_f_fraccion"])], "percentunit",
          campos={"min": 0, "max": 1}),
    panel("timeseries", "Energía aparente por hora (VA·h, tarea resumen_1h)", 8, 9, 8, 7,
          [consulta("telemetria_1h", ["energia_vah"])], "none",
          campos={"custom": {"drawStyle": "bars", "fillOpacity": 60, "lineWidth": 1}}),
    panel("timeseries", "Punto de rocío (media de 5 min) y temperatura", 16, 9, 8, 7,
          [consulta("telemetria_5m", ["pr", "t"])], "celsius"),

    fila("Calidad del dato (tarea calidad_1h)", 16),
    panel("timeseries", "Muestras por hora (esperadas: 120 con periodo de 30 s)", 0, 17, 8, 7,
          [consulta("calidad_1h", ["muestras", "faltantes"])], "none",
          campos={"custom": {"drawStyle": "bars", "fillOpacity": 60, "lineWidth": 1}}),
    panel("timeseries", "Muestras con observaciones y entregadas tarde, por hora", 8, 17, 8, 7,
          [consulta("calidad_1h", ["con_observaciones", "tardias"])], "none",
          campos={"custom": {"drawStyle": "bars", "fillOpacity": 60, "lineWidth": 1}}),
    panel("timeseries", "Retraso máximo del muestreo por hora", 16, 17, 8, 7,
          [consulta("calidad_1h", ["retraso_ms_max"])], "ms"),

    fila("Procesador (cada 10 min) y eventos", 24),
    panel("stat", "Última corrida del procesador", 0, 25, 8, 5,
          ['from(bucket: "cuarto_procesado")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n'
           '  |> filter(fn: (r) => r._measurement == "procesador")\n'
           '  |> filter(fn: (r) => r._field == "entrada" or r._field == "salida" or r._field == "con_observaciones" or r._field == "huecos")\n'
           '  |> last()\n' + renombrar({"entrada": "Entrada", "salida": "Salida", "con_observaciones": "Con observaciones", "huecos": "Huecos"}) +
           '  |> keep(columns: ["_time", "_value", "_field"])'], "none", stat),
    panel("table", "Eventos (puerta, agua, arranques, huecos, entregas tardías)", 8, 25, 16, 9,
          ['from(bucket: "cuarto_procesado")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n'
           f'  |> filter(fn: (r) => r._measurement == "eventos" and r.nodo == {NODO})\n'
           '  |> filter(fn: (r) => r._field == "duracion_s")\n'
           '  |> keep(columns: ["_time", "tipo", "_value"])\n'
           '  |> rename(columns: {_time: "inicio", _value: "duración (s)"})\n'
           '  |> sort(columns: ["inicio"], desc: true)'], "none",
          {"showHeader": True, "sortBy": [{"displayName": "inicio", "desc": True}]}),
    panel("timeseries", "Antes y después: corriente cruda y corriente limpia (arranques retirados)", 0, 30, 8, 8,
          [consulta("telemetria", ["i"], deposito="cuarto", extra=renombrar({"i": "cruda"})),
           consulta("telemetria_limpia", ["i"], extra=renombrar({"i": "limpia"}))], "amp",
          descripcion="La cruda incluye la corriente del propio nodo en los 90 s tras cada arranque; la limpia la retira."),
]

tablero = {
    "uid": "procesado", "title": "Procesamiento del cuarto técnico", "tags": ["iot", "procesado"],
    "timezone": "America/Bogota", "editable": True, "refresh": "1m", "schemaVersion": 39, "version": 1,
    "time": {"from": "now-24h", "to": "now"}, "graphTooltip": 1,
    "annotations": {"list": []},
    "templating": {"list": [
        {"name": "nodo", "label": "Nodo", "type": "query", "datasource": DS, "refresh": 1, "hide": 0,
         "query": 'import "influxdata/influxdb/schema"\nschema.tagValues(bucket: "cuarto_procesado", tag: "nodo")',
         "definition": 'import "influxdata/influxdb/schema"\nschema.tagValues(bucket: "cuarto_procesado", tag: "nodo")',
         "current": {"text": "nodo1", "value": "nodo1"}, "options": [], "sort": 1, "includeAll": False, "multi": False}]},
    "panels": panels,
}
print(json.dumps(tablero, ensure_ascii=False, indent=1))
