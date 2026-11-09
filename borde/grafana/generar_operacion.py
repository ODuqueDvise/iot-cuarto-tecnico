#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Genera el tablero de operación del cuarto técnico y sus alertas (Actividad 5).

    python3 generar_operacion.py            # escribe operacion.json, alertas.yaml y consultas_alertas.json

Tres franjas, de lo urgente a lo analítico:
  1. Ahora: el último valor de cada variable (crudo, últimos 15 min) y el estado de las alertas.
  2. Últimas 24 h: tendencia en tiempo real (crudo) con las bandas de la recomendación ASHRAE para salas técnicas.
  3. Periodo seleccionado: análisis básico sobre el nivel procesado (datos limpios): descriptiva, correlación,
     perfil por hora del día, distribución, anomalías por desviación estándar y totales por día.

Umbrales: ASHRAE, intervalo recomendado para equipos de TI (temperatura de 18 a 27 °C, HR hasta 60 %, punto de rocío
hasta 15 °C). Son los mismos del tablero del nodo sensor.

Usa la fuente "InfluxDB procesado" (uid influx-procesado), cuyo token solo lee los depósitos cuarto y cuarto_procesado.
alertas.yaml lleva la marca __CORREO_DESTINO__, que instalar_operacion.sh reemplaza con la dirección de
/etc/grafana/correo.env; la dirección no entra al repositorio.
"""
import json
import pathlib

AQUI = pathlib.Path(__file__).resolve().parent
DS = {"type": "influxdb", "uid": "influx-procesado"}
NODO = '"${nodo}"'
RANGO = "range(start: v.timeRangeStart, stop: v.timeRangeStop)"   # probar_consultas.py reconoce este texto

T_MIN, T_MAX, HR_MAX, PR_MAX = 18, 27, 60, 15
SIN_DATOS_S = 90          # tres periodos de 30 s sin muestra
PUERTA_MIN = 10           # minutos seguidos con la puerta abierta
SOSTENIDO = "15m"         # las variables ambientales deben seguir sobre el umbral este tiempo antes del correo
MANTENER = "30m"          # y la alerta sigue activa este tiempo tras bajar del umbral (une los cortes breves)

# ---------------------------------------------------------------- consultas


def crudo_ahora(campo, booleano=False):
    conv = '  |> map(fn: (r) => ({r with _value: if r._value then 1 else 0}))\n' if booleano else ""
    return ('from(bucket: "cuarto")\n  |> range(start: -15m)\n'
            f'  |> filter(fn: (r) => r._measurement == "telemetria" and r.nodo == {NODO} and r._field == "{campo}")\n'
            f'  |> last()\n{conv}  |> keep(columns: ["_time", "_value"])')


Q_POTENCIA = ('from(bucket: "cuarto")\n  |> range(start: -15m)\n'
              f'  |> filter(fn: (r) => r._measurement == "telemetria" and r.nodo == {NODO} and r._field == "i")\n'
              '  |> last()\n  |> map(fn: (r) => ({_time: r._time, _value: r._value * 120.0}))')

Q_EDAD = ('from(bucket: "cuarto")\n  |> range(start: -24h)\n'
          f'  |> filter(fn: (r) => r._measurement == "telemetria" and r.nodo == {NODO} and r._field == "seq")\n'
          '  |> last()\n'
          '  |> map(fn: (r) => ({_time: r._time, _value: float(v: int(v: now()) - int(v: r._time)) / 1000000000.0}))')

# energía desde la medianoche de Bogotá (UTC-5 todo el año) en el nivel procesado
Q_ENERGIA_HOY = ('dia = 86400000000000\ndesfase = 18000000000000\n'
                 'inicio = time(v: (int(v: now()) - desfase) / dia * dia + desfase)\n'
                 'from(bucket: "cuarto_procesado")\n  |> range(start: inicio)\n'
                 f'  |> filter(fn: (r) => r._measurement == "telemetria_limpia" and r.nodo == {NODO} and r._field == "energia_vah")\n'
                 '  |> sum()\n  |> keep(columns: ["_value"])')


def crudo_serie(campos):
    filtro = " or ".join(f'r._field == "{c}"' for c in campos)
    return ('from(bucket: "cuarto")\n'
            f'  |> {RANGO}\n'
            f'  |> filter(fn: (r) => r._measurement == "telemetria" and r.nodo == {NODO})\n'
            f'  |> filter(fn: (r) => {filtro})\n'
            '  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)\n'
            '  |> keep(columns: ["_time", "_value", "_field"])')


Q_VA_24H = ('from(bucket: "cuarto")\n'
            f'  |> {RANGO}\n'
            f'  |> filter(fn: (r) => r._measurement == "telemetria" and r.nodo == {NODO} and r._field == "i")\n'
            '  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)\n'
            '  |> map(fn: (r) => ({_time: r._time, _value: r._value * 120.0, _field: "potencia aparente"}))')


def crudo_estado(campo, nombre):
    return ('from(bucket: "cuarto")\n'
            f'  |> {RANGO}\n'
            f'  |> filter(fn: (r) => r._measurement == "telemetria" and r.nodo == {NODO} and r._field == "{campo}")\n'
            f'  |> map(fn: (r) => ({{_time: r._time, _value: if r._value then 1 else 0, _field: "{nombre}"}}))')


LIMPIA = ('from(bucket: "cuarto_procesado")\n'
          f'  |> {RANGO}\n'
          f'  |> filter(fn: (r) => r._measurement == "telemetria_limpia" and r.nodo == {NODO})\n')

Q_MUESTRAS = (LIMPIA + '  |> filter(fn: (r) => r._field == "seq")\n  |> count()\n  |> keep(columns: ["_value"])')

Q_COMPLETITUD = ('from(bucket: "cuarto_procesado")\n'
                 f'  |> {RANGO}\n'
                 f'  |> filter(fn: (r) => r._measurement == "calidad_1h" and r.nodo == {NODO})\n'
                 '  |> filter(fn: (r) => r._field == "muestras" or r._field == "faltantes")\n'
                 '  |> keep(columns: ["_field", "_value"])\n  |> group()\n'
                 '  |> reduce(identity: {m: 0.0, f: 0.0}, fn: (r, accumulator) => ({\n'
                 '      m: if r._field == "muestras" then accumulator.m + float(v: r._value) else accumulator.m,\n'
                 '      f: if r._field == "faltantes" then accumulator.f + float(v: r._value) else accumulator.f}))\n'
                 '  |> map(fn: (r) => ({_value: if r.m + r.f > 0.0 then 100.0 * r.m / (r.m + r.f) else 0.0}))')


def dentro(campo, condicion):
    """Porcentaje de las muestras limpias que cumplen la condición."""
    return (LIMPIA + f'  |> filter(fn: (r) => r._field == "{campo}")\n'
            f'  |> map(fn: (r) => ({{r with _value: if {condicion} then 100.0 else 0.0}}))\n'
            '  |> mean()\n  |> keep(columns: ["_value"])')


Q_DESCRIPTIVA = (
    'datos = ' + LIMPIA +
    '  |> filter(fn: (r) => r._field == "t" or r._field == "hr" or r._field == "pr" or r._field == "i")\n'
    '  |> keep(columns: ["_time", "_field", "_value"])\n'
    '  |> group(columns: ["_field"])\n\n'
    'est = (tablas, nombre, orden) => tablas\n'
    '  |> keep(columns: ["_field", "_value"])\n'
    '  |> map(fn: (r) => ({_field: r._field, _value: float(v: r._value), estadistico: nombre, orden: orden}))\n\n'
    'rango = datos\n'
    '  |> reduce(identity: {mx: -1000000.0, mn: 1000000.0}, fn: (r, accumulator) => ({\n'
    '      mx: if r._value > accumulator.mx then r._value else accumulator.mx,\n'
    '      mn: if r._value < accumulator.mn then r._value else accumulator.mn}))\n'
    '  |> map(fn: (r) => ({_field: r._field, _value: r.mx - r.mn}))\n\n'
    'union(tables: [\n'
    '    est(tablas: datos |> mean(), nombre: "Media", orden: 1),\n'
    '    est(tablas: datos |> median(method: "exact_mean"), nombre: "Mediana", orden: 2),\n'
    '    est(tablas: datos |> stddev(), nombre: "Desviación estándar", orden: 3),\n'
    '    est(tablas: datos |> min(), nombre: "Mínimo", orden: 4),\n'
    '    est(tablas: datos |> max(), nombre: "Máximo", orden: 5),\n'
    '    est(tablas: rango, nombre: "Rango", orden: 6),\n'
    '])\n'
    '  |> group()\n'
    '  |> pivot(rowKey: ["orden", "estadistico"], columnKey: ["_field"], valueColumn: "_value")\n'
    '  |> sort(columns: ["orden"])\n'
    '  |> drop(columns: ["orden"])')

# Correlación de Pearson en una sola pasada: pivot por marca de tiempo sobre los agregados de 5 min y sumas con reduce.
# La versión con pearsonr() (un join por pareja) tardaba 231 s sobre 7 días de datos de 30 s en la Pi.
PARES = [("t", "hr"), ("t", "pr"), ("t", "i"), ("hr", "pr"), ("hr", "i"), ("pr", "i")]
_v = ["t", "hr", "pr", "i"]
_ident = ", ".join(["n: 0.0"] + [f"s{a}: 0.0" for a in _v] + [f"q{a}: 0.0" for a in _v] + [f"p{a}{b}: 0.0" for a, b in PARES])
_acum = (",\n".join(["      n: accumulator.n + 1.0"] +
                     [f"      s{a}: accumulator.s{a} + r.{a}" for a in _v] +
                     [f"      q{a}: accumulator.q{a} + r.{a} * r.{a}" for a in _v] +
                     [f"      p{a}{b}: accumulator.p{a}{b} + r.{a} * r.{b}" for a, b in PARES]))
_r = {f"{a}{b}": f"pearson(sxy: s.p{a}{b}, sx: s.s{a}, sy: s.s{b}, sxx: s.q{a}, syy: s.q{b}, n: s.n)" for a, b in PARES}


def _celda(a, b):
    if a == b:
        return "1.0"
    return _r.get(f"{a}{b}") or _r[f"{b}{a}"]


_nombres = {"t": "Temperatura", "hr": "HR", "pr": "Punto de rocío", "i": "Corriente"}
_filas = ",\n".join("    {fila: \"%s\", %s}" % (_nombres[a], ", ".join(f"{b}: {_celda(a, b)}" for b in _v)) for a in _v)
Q_CORRELACION = (
    'import "array"\nimport "math"\n\n'
    'pearson = (sxy, sx, sy, sxx, syy, n) => (n * sxy - sx * sy) / math.sqrt(x: (n * sxx - sx * sx) * (n * syy - sy * sy))\n\n'
    's = from(bucket: "cuarto_procesado")\n'
    f'  |> {RANGO}\n'
    f'  |> filter(fn: (r) => r._measurement == "telemetria_5m" and r.nodo == {NODO})\n'
    '  |> filter(fn: (r) => r._field == "t" or r._field == "hr" or r._field == "pr" or r._field == "i")\n'
    '  |> keep(columns: ["_time", "_field", "_value"])\n'
    '  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")\n'
    '  |> filter(fn: (r) => exists r.t and exists r.hr and exists r.pr and exists r.i)\n'
    f'  |> reduce(identity: {{{_ident}}}, fn: (r, accumulator) => ({{\n{_acum}}}))\n'
    '  |> findRecord(fn: (key) => true, idx: 0)\n\n'
    f'array.from(rows: [\n{_filas},\n])')


def perfil(campo):
    # hora local de Bogotá: hora UTC menos 5 (Colombia no cambia de hora)
    return ('from(bucket: "cuarto_procesado")\n'
            f'  |> {RANGO}\n'
            f'  |> filter(fn: (r) => r._measurement == "telemetria_5m" and r.nodo == {NODO} and r._field == "{campo}")\n'
            '  |> map(fn: (r) => ({r with hora: (int(v: r._time) / 3600000000000 + 19) % 24}))\n'
            '  |> keep(columns: ["hora", "_value"])\n'
            '  |> group(columns: ["hora"])\n  |> mean()\n  |> group()\n'
            '  |> sort(columns: ["hora"])\n'
            '  |> map(fn: (r) => ({hora: if r.hora < 10 then "0" + string(v: r.hora) else string(v: r.hora), media: r._value}))')


# Conteo por intervalos de 0,1 °C calculado en InfluxDB (unas 40 filas) en vez de traer las 20.000 muestras a Grafana.
Q_HISTOGRAMA = (LIMPIA + '  |> filter(fn: (r) => r._field == "t")\n'
                '  |> keep(columns: ["_value"])\n'
                '  |> map(fn: (r) => ({intervalo: float(v: int(v: r._value * 10.0)) / 10.0, n: 1}))\n'
                '  |> group(columns: ["intervalo"])\n  |> count(column: "n")\n'
                '  |> group()\n  |> sort(columns: ["intervalo"])\n'
                '  |> map(fn: (r) => ({intervalo: string(v: r.intervalo), muestras: r.n}))')


def banda(campo, nombre):
    return ('datos = from(bucket: "cuarto_procesado")\n'
            f'  |> {RANGO}\n'
            f'  |> filter(fn: (r) => r._measurement == "telemetria_5m" and r.nodo == {NODO} and r._field == "{campo}")\n'
            '  |> keep(columns: ["_time", "_value"])\n\n'
            'm = (datos |> mean() |> findRecord(fn: (key) => true, idx: 0))._value\n'
            's = (datos |> stddev() |> findRecord(fn: (key) => true, idx: 0))._value\n\n'
            f'datos |> map(fn: (r) => ({{_time: r._time, {nombre}: r._value, limite_superior: m + 3.0 * s, limite_inferior: m - 3.0 * s}}))')


def fuera_de_banda(campo):
    return ('datos = from(bucket: "cuarto_procesado")\n'
            f'  |> {RANGO}\n'
            f'  |> filter(fn: (r) => r._measurement == "telemetria_5m" and r.nodo == {NODO} and r._field == "{campo}")\n'
            '  |> keep(columns: ["_time", "_value"])\n\n'
            'm = (datos |> mean() |> findRecord(fn: (key) => true, idx: 0))._value\n'
            's = (datos |> stddev() |> findRecord(fn: (key) => true, idx: 0))._value\n\n'
            'datos\n'
            '  |> map(fn: (r) => ({r with _value: if r._value > m + 3.0 * s or r._value < m - 3.0 * s then 1 else 0}))\n'
            '  |> sum()\n  |> keep(columns: ["_value"])')


def por_dia(medicion, campo, factor, nombre):
    """Suma por día local (ventanas de 1 d desplazadas 5 h, de medianoche a medianoche en Bogotá)."""
    return ('from(bucket: "cuarto_procesado")\n'
            f'  |> {RANGO}\n'
            f'  |> filter(fn: (r) => r._measurement == "{medicion}" and r.nodo == {NODO} and r._field == "{campo}")\n'
            '  |> map(fn: (r) => ({r with _value: float(v: r._value)}))\n'
            '  |> aggregateWindow(every: 1d, offset: 5h, fn: sum, createEmpty: false, timeSrc: "_start")\n'
            f'  |> map(fn: (r) => ({{_time: r._time, _value: r._value * {factor}, _field: "{nombre}"}}))')


Q_EVENTOS = ('from(bucket: "cuarto_procesado")\n'
             f'  |> {RANGO}\n'
             f'  |> filter(fn: (r) => r._measurement == "eventos" and r.nodo == {NODO})\n'
             '  |> filter(fn: (r) => r.tipo == "puerta_abierta" or r.tipo == "agua" or r.tipo == "apagado" or r.tipo == "hueco")\n'
             '  |> filter(fn: (r) => r._field == "fin")\n'
             '  |> group()\n'
             '  |> map(fn: (r) => ({time: r._time, timeEnd: time(v: r._value * 1000000000), text: r.tipo, tags: r.tipo}))')

# ---------------------------------------------------------------- paneles

panel_id = 0


def nuevo_id():
    global panel_id
    panel_id += 1
    return panel_id


def panel(tipo, titulo, pos, consultas, descripcion, unidad="none", opciones=None, defaults=None, overrides=None,
          transformaciones=None, tiempo=None):
    p = {"id": nuevo_id(), "type": tipo, "title": titulo, "description": descripcion, "datasource": DS,
         "gridPos": dict(zip(("x", "y", "w", "h"), pos)),
         "fieldConfig": {"defaults": {"unit": unidad}, "overrides": overrides or []},
         "options": opciones or {},
         "targets": [{"refId": chr(65 + i), "datasource": DS, "query": q} for i, q in enumerate(consultas)]}
    if defaults:
        p["fieldConfig"]["defaults"].update(defaults)
    if transformaciones:
        p["transformations"] = transformaciones
    if tiempo:
        p["timeFrom"] = tiempo
    return p


def fila(titulo, y):
    return {"id": nuevo_id(), "type": "row", "title": titulo, "collapsed": False, "panels": [],
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}}


def umbrales(*pasos):
    """pasos: (color, valor) con el primero de valor None."""
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in pasos]}


def stat(texto="value", grafico="none", calc="lastNotNull", fondo=True):
    return {"reduceOptions": {"calcs": [calc], "fields": "", "values": False},
            "colorMode": "background" if fondo else "none",
            "graphMode": grafico, "textMode": texto, "justifyMode": "center", "orientation": "auto",
            "wideLayout": True, "showPercentChange": False}


def mapeo(*pares):
    return [{"type": "value", "options": {str(v): {"text": t, "color": c, "index": i}
                                          for i, (v, t, c) in enumerate(pares)}}]


def serie(min_=None, max_=None, area=True, barras=False, umbral=None, decimales=None):
    d = {"custom": {"drawStyle": "bars" if barras else "line", "lineWidth": 1 if barras else 2,
                    "fillOpacity": 70 if barras else (10 if area else 0), "showPoints": "never",
                    "spanNulls": False, "thresholdsStyle": {"mode": "line+area" if umbral else "off"}},
         "color": {"mode": "palette-classic"}}
    if min_ is not None:
        d["min"] = min_
    if max_ is not None:
        d["max"] = max_
    if umbral:
        d["thresholds"] = umbral
    if decimales is not None:
        d["decimals"] = decimales
    return d


leyenda = {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
           "tooltip": {"mode": "multi", "sort": "none"}}
sin_leyenda = {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": False},
               "tooltip": {"mode": "single", "sort": "none"}}
TRANSPARENTE = "transparent"
ROJO_SUAVE = "rgba(242, 73, 92, 0.18)"
AZUL_SUAVE = "rgba(87, 148, 242, 0.18)"
U_T = umbrales((AZUL_SUAVE, None), (TRANSPARENTE, T_MIN), (ROJO_SUAVE, T_MAX))
U_HR = umbrales((TRANSPARENTE, None), (ROJO_SUAVE, HR_MAX))
U_PR = umbrales((TRANSPARENTE, None), (ROJO_SUAVE, PR_MAX))

paneles = []
y = 0

# ---- franja 1: ahora -------------------------------------------------------
paneles.append(fila("Ahora: último valor de cada variable (crudo, últimos 15 min)", y)); y += 1
ahora = [
    ("Temperatura", crudo_ahora("t"), "celsius", 1,
     umbrales(("blue", None), ("green", T_MIN), ("red", T_MAX)),
     f"¿Está el cuarto dentro de {T_MIN} a {T_MAX} °C (ASHRAE)? Rojo: revisar el aire acondicionado y la carga del rack."),
    ("Humedad relativa", crudo_ahora("hr"), "humidity", 1,
     umbrales(("green", None), ("red", HR_MAX)),
     f"¿Supera el {HR_MAX} %? Es la variable con menos margen: en la línea base llegó a 59,8 %."),
    ("Punto de rocío", crudo_ahora("pr"), "celsius", 1,
     umbrales(("green", None), ("red", PR_MAX)),
     f"Sobre {PR_MAX} °C aumenta el riesgo de condensación en los equipos."),
    ("Potencia aparente", Q_POTENCIA, "voltamp", 0,
     None,
     "Corriente del circuito del rack por 120 V nominales. Sin factor de potencia conocido, no son vatios."),
]
for i, (titulo, q, unidad, dec, u, desc) in enumerate(ahora):
    paneles.append(panel("stat", titulo, (4 * i, y, 4, 4), [q], desc, unidad, stat(fondo=u is not None),
                         {"decimals": dec, "thresholds": u or umbrales(("text", None)), "color": {"mode": "thresholds"}}))
paneles.append(panel("stat", "Puerta", (0, y + 4, 4, 4), [crudo_ahora("puerta", True)],
                     f"Abierta en ámbar. Si sigue abierta más de {PUERTA_MIN} min, llega un correo.", "none", stat(),
                     {"mappings": mapeo((0, "Cerrada", "green"), (1, "Abierta", "orange")),
                      "thresholds": umbrales(("green", None)), "color": {"mode": "thresholds"}}))
paneles.append(panel("stat", "Agua en el piso", (4, y + 4, 4, 4), [crudo_ahora("agua", True)],
                     "AGUA en rojo: ir de inmediato, posible filtración sobre los equipos. El correo sale con dos muestras seguidas.",
                     "none", stat(),
                     {"mappings": mapeo((0, "Seco", "green"), (1, "AGUA", "red")),
                      "thresholds": umbrales(("green", None)), "color": {"mode": "thresholds"}}))
paneles.append(panel("stat", "Última muestra del nodo", (8, y + 4, 4, 4), [Q_EDAD],
                     f"Segundos desde la última muestra. Más de {SIN_DATOS_S} s: el nodo, la red o el borde fallaron, "
                     "y el resto del tablero ya no es confiable.", "s", stat(),
                     {"decimals": 0, "noValue": "sin datos en 24 h",
                      "thresholds": umbrales(("green", None), ("red", SIN_DATOS_S)), "color": {"mode": "thresholds"}}))
paneles.append(panel("stat", "Energía aparente de hoy", (12, y + 4, 4, 4), [Q_ENERGIA_HOY],
                     "Desde la medianoche, sobre el nivel procesado (se actualiza cada 10 min).", "none", stat(fondo=False),
                     {"decimals": 1, "unit": "VA·h", "thresholds": umbrales(("text", None)),
                      "color": {"mode": "thresholds"}}))
paneles.append({"id": nuevo_id(), "type": "alertlist", "title": "Alertas (se envían por correo)",
                "description": "Estado de las seis reglas, las disparadas primero. Crítica: correo inmediato, repite cada 4 h. "
                               "Alta y media: un correo por episodio.",
                "gridPos": {"x": 16, "y": y, "w": 8, "h": 8},
                "options": {"viewMode": "list", "groupMode": "default", "groupBy": [], "maxItems": 10,
                            "sortOrder": 3, "dashboardAlerts": False, "alertName": "", "alertInstanceLabelFilter": "",
                            "folder": None, "showInstances": False,
                            "stateFilter": {"firing": True, "pending": True, "noData": True, "normal": True,
                                            "error": True}}})
y += 8

# ---- franja 2: últimas 24 h --------------------------------------------------
paneles.append(fila("Últimas 24 horas: tendencia en tiempo real (crudo). Zonas rojas: fuera de la recomendación ASHRAE", y)); y += 1
ids_tendencia = []
for i, (titulo, campos, unidad, mn, mx, u, desc) in enumerate([
        ("Temperatura (°C)", ["t"], "celsius", 15, 30, U_T,
         "Escala fija de 15 a 30 °C para ver el margen hasta el límite; la variación fina está en el análisis."),
        ("Humedad relativa (%)", ["hr"], "humidity", 30, 80, U_HR, "Escala fija de 30 a 80 %."),
        ("Punto de rocío (°C)", ["pr"], "celsius", 5, 20, U_PR, "Escala fija de 5 a 20 °C.")]):
    p = panel("timeseries", titulo, (8 * i, y, 8, 8), [crudo_serie(campos)], desc, unidad, sin_leyenda,
              serie(mn, mx, umbral=u, decimales=1), tiempo="24h")
    ids_tendencia.append(p["id"]); paneles.append(p)
y += 8
p = panel("timeseries", "Potencia aparente (VA)", (0, y, 12, 7), [Q_VA_24H],
          "Cada escalón es un equipo que enciende o apaga en el circuito del rack.", "voltamp", sin_leyenda,
          serie(min_=0, decimales=0), tiempo="24h")
ids_tendencia.append(p["id"]); paneles.append(p)
paneles.append(panel("state-timeline", "Puerta y agua", (12, y, 12, 7),
                     [crudo_estado("puerta", "Puerta"), crudo_estado("agua", "Agua")],
                     "Cuándo y cuánto tiempo estuvo abierta la puerta o hubo agua.", "none",
                     {"showValue": "never", "rowHeight": 0.8, "mergeValues": True, "alignValue": "left",
                      "legend": {"showLegend": False, "displayMode": "list", "placement": "bottom"},
                      "tooltip": {"mode": "single", "sort": "none"}},
                     {"mappings": mapeo((0, "cerrada / seco", "green"), (1, "abierta / agua", "red")),
                      "thresholds": umbrales(("green", None)), "color": {"mode": "thresholds"},
                      "custom": {"fillOpacity": 80, "lineWidth": 0}}, tiempo="24h"))
y += 7

# ---- franja 3: análisis -----------------------------------------------------
paneles.append(fila("Análisis del periodo seleccionado arriba a la derecha (nivel procesado: datos limpios)", y)); y += 1
indicadores = [
    ("Muestras válidas", Q_MUESTRAS, "none", 0, None,
     "Muestras de telemetria_limpia en el periodo (una cada 30 s)."),
    ("Completitud", Q_COMPLETITUD, "percent", 1, umbrales(("red", None), ("orange", 95), ("green", 99)),
     "Muestras recibidas sobre esperadas, por hora (tarea calidad_1h). Bajo 95 %: las conclusiones pierden peso."),
    (f"Temperatura en {T_MIN}–{T_MAX} °C", dentro("t", f"r._value >= {T_MIN}.0 and r._value <= {T_MAX}.0"),
     "percent", 1, umbrales(("red", None), ("green", 99.9)), "Porcentaje del tiempo dentro de la recomendación."),
    (f"HR hasta {HR_MAX} %", dentro("hr", f"r._value <= {HR_MAX}.0"), "percent", 1,
     umbrales(("red", None), ("green", 99.9)), "Porcentaje del tiempo dentro de la recomendación."),
    (f"Rocío hasta {PR_MAX} °C", dentro("pr", f"r._value <= {PR_MAX}.0"), "percent", 1,
     umbrales(("red", None), ("green", 99.9)), "Porcentaje del tiempo dentro de la recomendación."),
    ("Ventanas inusuales de temperatura", fuera_de_banda("t"), "none", 0,
     umbrales(("green", None), ("orange", 1)),
     "Ventanas de 5 min fuera de media ± 3 desviaciones del periodo: anomalías estadísticas, aunque estén dentro de la norma."),
]
for i, (titulo, q, unidad, dec, u, desc) in enumerate(indicadores):
    paneles.append(panel("stat", titulo, (4 * i, y, 4, 4), [q], desc, unidad, stat(fondo=u is not None),
                         {"decimals": dec, "thresholds": u or umbrales(("text", None)), "color": {"mode": "thresholds"}}))
y += 4

columnas = {"t": "Temperatura (°C)", "hr": "HR (%)", "pr": "Punto de rocío (°C)", "i": "Corriente (A)"}
paneles.append(panel("table", "Estadística descriptiva", (0, y, 12, 8), [Q_DESCRIPTIVA],
                     "Resumen del periodo por variable. La moda no se incluye: con decimales casi no se repiten valores.",
                     "none", {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}},
                     {"decimals": 2, "custom": {"align": "auto", "cellOptions": {"type": "auto"}}},
                     [{"matcher": {"id": "byName", "options": "Corriente (A)"},
                       "properties": [{"id": "decimals", "value": 3}]}],
                     [{"id": "organize", "options": {
                         "indexByName": {"estadistico": 0, "t": 1, "hr": 2, "pr": 3, "i": 4},
                         "renameByName": {**columnas, "estadistico": "Estadístico"}}}]))
paneles.append(panel("table", "Correlación de Pearson entre variables", (12, y, 12, 8), [Q_CORRELACION],
                     "Sobre las medias de 5 min. De −1 (azul, una sube cuando la otra baja) a +1 (rojo, suben juntas). Correlación no es causalidad.",
                     "none", {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}},
                     {"decimals": 2, "min": -1, "max": 1, "color": {"mode": "continuous-BlYlRd"},
                      "custom": {"align": "center", "cellOptions": {"type": "color-background", "mode": "basic"}}},
                     [{"matcher": {"id": "byName", "options": "Variable"},
                       "properties": [{"id": "custom.cellOptions", "value": {"type": "auto"}},
                                      {"id": "custom.align", "value": "left"}]}],
                     [{"id": "organize", "options": {
                         "indexByName": {"fila": 0, "t": 1, "hr": 2, "pr": 3, "i": 4},
                         "renameByName": {"fila": "Variable", "t": "Temperatura", "hr": "HR", "pr": "Punto de rocío",
                                          "i": "Corriente"}}}]))
y += 8

barras_perfil = {"orientation": "vertical", "xField": "hora", "showValue": "never", "stacking": "none",
                 "groupWidth": 0.8, "barWidth": 0.9, "xTickLabelRotation": 0, "xTickLabelSpacing": 0,
                 "legend": {"showLegend": False, "displayMode": "list", "placement": "bottom"},
                 "tooltip": {"mode": "single", "sort": "none"}}
paneles.append(panel("barchart", "Perfil por hora del día: temperatura media (°C)", (0, y, 8, 8), [perfil("t")],
                     "Promedio de cada hora local sobre todos los días del periodo: muestra el ciclo diario.",
                     "none", barras_perfil, {"decimals": 1, "min": 20, "color": {"mode": "fixed", "fixedColor": "red"},
                                             "custom": {"fillOpacity": 70, "lineWidth": 0}},
                     [{"matcher": {"id": "byName", "options": "media"}, "properties": [{"id": "unit", "value": "celsius"}]}]))
paneles.append(panel("barchart", "Perfil por hora del día: humedad relativa media (%)", (8, y, 8, 8), [perfil("hr")],
                     "Promedio de cada hora local sobre todos los días del periodo.", "none", barras_perfil,
                     {"decimals": 1, "min": 40, "color": {"mode": "fixed", "fixedColor": "blue"},
                      "custom": {"fillOpacity": 70, "lineWidth": 0}},
                     [{"matcher": {"id": "byName", "options": "media"}, "properties": [{"id": "unit", "value": "humidity"}]}]))
paneles.append(panel("barchart", "Distribución de la temperatura (muestras limpias)", (16, y, 8, 8), [Q_HISTOGRAMA],
                     "Cuántas muestras cayeron en cada intervalo de 0,1 °C (eje en °C).", "none",
                     {**barras_perfil, "xField": "intervalo", "xTickLabelSpacing": 60},
                     {"decimals": 0, "min": 0, "color": {"mode": "fixed", "fixedColor": "red"},
                      "custom": {"fillOpacity": 70, "lineWidth": 0}}))
y += 8

paneles.append(panel("timeseries", "Anomalías: temperatura (media de 5 min) y banda de media ± 3σ", (0, y, 12, 8),
                     [banda("t", "temperatura")],
                     "Lo que sale de la banda es inusual para este cuarto aunque esté dentro de la norma ASHRAE.",
                     "celsius", leyenda, serie(area=False, decimales=2),
                     [{"matcher": {"id": "byName", "options": "limite_superior"},
                       "properties": [{"id": "displayName", "value": "media + 3σ"}]},
                      {"matcher": {"id": "byName", "options": "limite_inferior"},
                       "properties": [{"id": "displayName", "value": "media − 3σ"}]},
                      {"matcher": {"id": "byRegexp", "options": "^media .*"},
                       "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}},
                                      {"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}},
                                      {"id": "custom.lineWidth", "value": 1}]}]))
paneles.append(panel("timeseries", "Puerta por día: minutos abierta y aperturas", (12, y, 6, 8),
                     [por_dia("telemetria_5m", "puerta_fraccion", 5.0, "minutos abierta"),
                      por_dia("telemetria_limpia", "puerta_n", 1.0, "aperturas")],
                     "Totales por día, no aperturas individuales: la hora de cada ingreso puede identificar a una persona "
                     "(Ley 1581 de 2012). Los días de los extremos del periodo están incompletos.", "none", leyenda, serie(min_=0, barras=True, decimales=0)))
paneles.append(panel("timeseries", "Energía aparente por día (VA·h)", (18, y, 6, 8),
                     [por_dia("telemetria_1h", "energia_vah", 1.0, "energía")],
                     "Suma diaria de la tarea resumen_1h. El primer y el último día del periodo están incompletos.", "none", sin_leyenda, serie(min_=0, barras=True, decimales=0)))
y += 8

tablero = {
    "uid": "operacion", "title": "Operación del cuarto técnico", "tags": ["iot", "operacion"],
    "description": "Actividad 5: tablero para decidir. Franja 1, qué pasa ahora; franja 2, últimas 24 h; "
                   "franja 3, análisis del periodo elegido.",
    "timezone": "America/Bogota", "editable": True, "refresh": "1m", "schemaVersion": 39, "version": 1,
    "time": {"from": "now-7d", "to": "now"}, "graphTooltip": 1, "liveNow": False,
    "timepicker": {"refresh_intervals": ["30s", "1m", "5m", "15m"]},
    "annotations": {"list": [{
        "name": "Eventos (puerta, agua, apagados, huecos)", "datasource": DS, "enable": True, "iconColor": "purple",
        "target": {"refId": "Anno", "query": Q_EVENTOS},
        "filter": {"exclude": False, "ids": ids_tendencia}}]},
    "templating": {"list": [
        {"name": "nodo", "label": "Nodo", "type": "query", "datasource": DS, "refresh": 1, "hide": 0,
         "query": 'import "influxdata/influxdb/schema"\nschema.tagValues(bucket: "cuarto", tag: "nodo")',
         "definition": 'import "influxdata/influxdb/schema"\nschema.tagValues(bucket: "cuarto", tag: "nodo")',
         "current": {"text": "nodo1", "value": "nodo1"}, "options": [], "sort": 1, "includeAll": False,
         "multi": False}]},
    "panels": paneles,
}

# ---------------------------------------------------------------- alertas


def regla_serie(campo, booleano=False):
    conv = '  |> map(fn: (r) => ({r with _value: if r._value then 1.0 else 0.0}))\n' if booleano else ""
    return ('from(bucket: "cuarto")\n'
            f'  |> {RANGO}\n'
            f'  |> filter(fn: (r) => r._measurement == "telemetria" and r._field == "{campo}")\n'
            f'{conv}  |> group(columns: ["nodo"])\n'
            '  |> keep(columns: ["_time", "_value", "nodo"])')


Q_REGLA_EDAD = ('from(bucket: "cuarto")\n'
                f'  |> {RANGO}\n'
                '  |> filter(fn: (r) => r._measurement == "telemetria" and r._field == "seq")\n'
                '  |> group(columns: ["nodo"])\n  |> last()\n'
                '  |> map(fn: (r) => ({_time: r._time, nodo: r.nodo, _value: float(v: int(v: now()) - int(v: r._time)) / 1000000000.0}))')

REGLAS = [
    # uid, título, consulta, ventana (s), reductor, umbral, severidad, sin datos, tiempo sostenido, resumen
    ("cuarto-agua", "Agua en el piso del cuarto técnico", regla_serie("agua", True), 65, "min", 0.5, "critica", "OK", "0s",
     "Agua detectada en {{ $labels.nodo }} en dos muestras seguidas. Ir al cuarto de inmediato: posible filtración sobre los equipos."),
    ("cuarto-nodo", "Nodo sin datos", Q_REGLA_EDAD, 3600, "last", SIN_DATOS_S, "critica", "Alerting", "0s",
     "{{ $labels.nodo }} no envía muestras hace {{ printf \"%.0f\" $values.B.Value }} s. El tablero ya no refleja el cuarto: revisar alimentación, Wi-Fi y borde."),
    ("cuarto-temperatura", f"Temperatura sobre {T_MAX} °C", regla_serie("t"), 300, "mean", T_MAX, "alta", "OK", SOSTENIDO,
     "Temperatura media de 5 min en {{ $labels.nodo }}: {{ printf \"%.1f\" $values.B.Value }} °C. Revisar el aire acondicionado y la carga del rack."),
    ("cuarto-humedad", f"Humedad relativa sobre {HR_MAX} %", regla_serie("hr"), 300, "mean", HR_MAX, "alta", "OK", SOSTENIDO,
     "HR media de 5 min en {{ $labels.nodo }}: {{ printf \"%.1f\" $values.B.Value }} %. Revisar deshumidificación y filtraciones."),
    ("cuarto-rocio", f"Punto de rocío sobre {PR_MAX} °C", regla_serie("pr"), 300, "mean", PR_MAX, "alta", "OK", SOSTENIDO,
     "Punto de rocío medio de 5 min en {{ $labels.nodo }}: {{ printf \"%.1f\" $values.B.Value }} °C. Riesgo de condensación."),
    ("cuarto-puerta", f"Puerta abierta más de {PUERTA_MIN} min", regla_serie("puerta", True), PUERTA_MIN * 60, "min",
     0.5, "media", "OK", "0s",
     "La puerta del cuarto ({{ $labels.nodo }}) lleva más de " + str(PUERTA_MIN) + " min abierta. Confirmar si hay una intervención en curso."),
]


def yaml_texto(s, sangria):
    """Bloque literal de YAML con la sangría dada."""
    pad = " " * sangria
    return "|\n" + "\n".join(pad + linea for linea in s.splitlines())


def yaml_cadena(s):
    return json.dumps(s, ensure_ascii=False)   # una cadena JSON es una cadena YAML válida


def alertas_yaml():
    l = ["# Generado por generar_operacion.py. instalar_operacion.sh reemplaza __CORREO_DESTINO__ y lo copia a",
         "# /etc/grafana/provisioning/alerting/cuarto.yaml (640, root:grafana).",
         "apiVersion: 1", "groups:", "  - orgId: 1", "    name: cuarto_tecnico", "    folder: Cuarto técnico",
         "    interval: 30s", "    rules:"]
    for uid, titulo, q, ventana, reductor, umbral, sev, sin_datos, sostenido, resumen in REGLAS:
        l += [f"      - uid: {uid}", f"        title: {yaml_cadena(titulo)}", "        condition: C", "        data:",
              "          - refId: A", "            relativeTimeRange:", f"              from: {ventana}",
              "              to: 0", "            datasourceUid: influx-procesado", "            model:",
              "              refId: A", "              intervalMs: 30000", "              maxDataPoints: 43200",
              "              query: " + yaml_texto(q, 16),
              "          - refId: B", "            datasourceUid: __expr__", "            model:",
              "              refId: B", "              type: reduce", "              expression: A",
              f"              reducer: {reductor}", "              settings:", "                mode: dropNN",
              "          - refId: C", "            datasourceUid: __expr__", "            model:",
              "              refId: C", "              type: threshold", "              expression: B",
              "              conditions:", "                - evaluator:", "                    type: gt",
              f"                    params: [{umbral}]",
              f"        noDataState: {sin_datos}", "        execErrState: Error", f"        for: {sostenido}",
              f"        keep_firing_for: {MANTENER if sostenido != '0s' else '0s'}",
              "        isPaused: false", "        annotations:", f"          summary: {yaml_cadena(resumen)}",
              "          dashboardUId: operacion", "        labels:", f"          severidad: {sev}"]
    # Dos puntos de contacto al mismo buzón con políticas distintas. Crítica (agua, nodo): correo en 10 s, repite cada
    # 4 h y avisa al resolver. Alta y media (ambiente, puerta): un correo por episodio, repite a las 24 h si persiste y
    # no avisa al resolver. Con la política única (repetir cada 4 h y resolver) llegaron 16 correos de humedad y punto
    # de rocío entre el 6 y el 8 de noviembre por excursiones nocturnas de varias horas.
    l += ["deleteContactPoints:", "  - orgId: 1", "    uid: correo-cuarto",   # punto único de la primera versión
          "contactPoints:", "  - orgId: 1", "    name: Correo urgente", "    receivers:",
          "      - uid: correo-urgente", "        type: email", "        settings:",
          "          addresses: __CORREO_DESTINO__", "          singleEmail: true",
          "          subject: \"[Cuarto técnico] {{ .CommonLabels.alertname }}: actuar ahora\"",
          "        disableResolveMessage: false",
          "  - orgId: 1", "    name: Correo informativo", "    receivers:",
          "      - uid: correo-informativo", "        type: email", "        settings:",
          "          addresses: __CORREO_DESTINO__", "          singleEmail: true",
          "          subject: \"[Cuarto técnico] {{ .CommonLabels.alertname }}\"",
          "        disableResolveMessage: true",
          "policies:", "  - orgId: 1", "    receiver: Correo urgente", "    group_by:",
          "      - alertname", "      - nodo", "    group_wait: 10s", "    group_interval: 1m",
          "    repeat_interval: 4h", "    routes:",
          "      - receiver: Correo informativo", "        object_matchers:",
          "          - [severidad, =~, \"alta|media\"]",
          "        group_wait: 1m", "        group_interval: 5m", "        repeat_interval: 24h"]
    return "\n".join(l) + "\n"


if __name__ == "__main__":
    (AQUI / "operacion.json").write_text(json.dumps(tablero, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (AQUI / "alertas.yaml").write_text(alertas_yaml(), encoding="utf-8")
    pruebas = {"panels": [{"title": f"alerta: {r[1]}", "targets": [{"query": r[2]}]} for r in REGLAS]}
    (AQUI / "consultas_alertas.json").write_text(json.dumps(pruebas, ensure_ascii=False, indent=1) + "\n",
                                                 encoding="utf-8")
    print(f"operacion.json: {len(paneles)} paneles; alertas.yaml: {len(REGLAS)} reglas")
