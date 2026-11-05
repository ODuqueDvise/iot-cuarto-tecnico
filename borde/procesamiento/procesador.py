#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Procesador de telemetría del cuarto técnico (Actividad 4).

Toma la telemetría cruda del nodo (depósito "cuarto" de InfluxDB, o un CSV de la captura serie o del
registrador) y produce tres cosas en el depósito "cuarto_procesado" (o en archivos, con --csv):

  telemetria_limpia  una fila por muestra válida, con los valores inválidos retirados y una máscara
                     "calidad" que dice qué se tocó y por qué;
  eventos            aperturas de puerta, presencia de agua, arranques del nodo, huecos, apagados
                     (lapsos sin muestras antes de un arranque) y tramos entregados con retraso
                     (inicio, fin, duración);
  resumen            conteos de cada paso (cuántas filas entraron, cuántas se retiraron y por qué),
                     que son la evidencia del preprocesamiento.

Pasos, en orden: normalizar, filtrar por origen, deduplicar, validar rangos, marcar arranques,
retirar lecturas con fallo de sensor, marcar huecos y entregas tardías, histéresis de agua, derivar
potencia aparente, extraer eventos. Las agregaciones de 5 min y 1 h las hacen las tareas Flux de
InfluxDB sobre telemetria_limpia (ver tareas/).

Uso:
  procesador.py --csv ../../datos/borde/nodo1_20261020.csv --salida /tmp/procesado
  procesador.py --influx --desde 2026-10-20T08:00:00 --hasta 2026-10-20T12:00:00
  procesador.py --influx --ventana 30m          # modo del temporizador: últimos 30 min, idempotente

Con --influx lee la configuración de /etc/puente/procesador.env (INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG,
INFLUX_BUCKET_CRUDO, INFLUX_BUCKET_PROCESADO). Solo usa pandas y, con --influx, influxdb-client.
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

log = logging.getLogger("procesador")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ZONA = "America/Bogota"
PERIODO_S = 30                 # periodo nominal; el real se toma del campo "periodo" si viene
ARRANQUE_S = 90                # tras un arranque, la corriente de este lapso no es de la carga
CONTEXTO_S = 3 * 3600          # con --influx se leen además estas horas previas, para ver la muestra anterior a un
                               # apagado o a un arranque y para detectar huecos; coincide con la cola de 3 h del nodo
RANGOS = {"t": (-10.0, 60.0), "hr": (0.0, 100.0), "i": (0.0, 20.0), "i_max": (0.0, 20.0),
          "retraso_ms": (0, 5000)}
V_NOMINAL = 120.0              # tensión nominal para la potencia aparente estimada (VA)

# Máscara "calidad" de cada muestra procesada. 0 = muestra sin observaciones.
CAL_FUERA_RANGO = 1            # algún valor fuera de rango: se retiró ese valor
CAL_ARRANQUE = 2               # dentro de ARRANQUE_S tras un arranque: corriente retirada
CAL_FALLO_SENSOR = 4           # el nodo marcó fallo (bits 1, 2 o 4 de est): valor retirado
CAL_SIN_HORA = 8               # bit 8 del nodo: reloj sin sincronizar
CAL_CUADRICULA = 16            # bit 16 del nodo: cuadrícula recalculada (muestra válida)
CAL_TARDIA = 32                # bit 32 del nodo: registrada sin MQTT, entregada desde la cola
CAL_HUECO_ANTES = 64           # faltan muestras entre la anterior y esta
CAL_AGUA_REBOTE = 128          # "agua" en una sola muestra aislada: suprimida por histéresis

# Bits de estado_sensores del firmware (nodo/main/sensores.h)
EST_SHT31_FALLO, EST_CORRIENTE_FALLO, EST_AGUA_FALLO, EST_SIN_HORA, EST_SALTO, EST_SIN_MQTT = 1, 2, 4, 8, 16, 32

COLUMNAS_CSV = {"seq": "seq", "ts_epoch": "ts_epoch", "retraso_ms": "retraso_ms", "t_c": "t", "hr_pct": "hr",
                "punto_rocio_c": "pr", "i_media_a": "i", "i_max_a": "i_max", "puerta": "puerta",
                "puerta_aperturas": "puerta_n", "agua": "agua", "agua_eventos": "agua_n",
                "estado_sensores": "est", "origen": "origen"}
CAMPOS = ["seq", "retraso_ms", "t", "hr", "pr", "i", "i_max", "puerta", "puerta_n", "agua", "agua_n",
          "est", "origen"]


# ----------------------------------------------------------------------------------------------------
# Lectura
# ----------------------------------------------------------------------------------------------------
def leer_csv(ruta, nodo="nodo1"):
    """CSV de la captura serie o del registrador del borde (columnas largas) a la forma canónica."""
    d = pd.read_csv(ruta)
    faltan = [c for c in COLUMNAS_CSV if c not in d.columns]
    if faltan:
        sys.exit(f"{ruta}: faltan columnas {faltan}")
    d = d.rename(columns=COLUMNAS_CSV)[list(COLUMNAS_CSV.values())]
    d["ts"] = pd.to_datetime(d.pop("ts_epoch"), unit="s", utc=True)
    d["nodo"] = nodo
    return normalizar(d)


def leer_influx(cliente, org, deposito, desde, hasta):
    """Telemetría cruda de InfluxDB, pivotada a una fila por muestra."""
    flux = f'''
from(bucket: "{deposito}")
  |> range(start: {desde.isoformat()}, stop: {hasta.isoformat()})
  |> filter(fn: (r) => r._measurement == "telemetria")
  |> pivot(rowKey: ["_time", "nodo"], columnKey: ["_field"], valueColumn: "_value")
  |> drop(columns: ["_start", "_stop", "_measurement"])
'''
    tablas = cliente.query_api().query_data_frame(flux, org=org)
    if isinstance(tablas, list):
        tablas = pd.concat(tablas, ignore_index=True) if tablas else pd.DataFrame()
    if tablas.empty:
        return pd.DataFrame(columns=["ts", "nodo"] + CAMPOS)
    d = tablas.rename(columns={"_time": "ts"}).drop(columns=["result", "table"], errors="ignore")
    for c in CAMPOS:
        if c not in d.columns:
            d[c] = pd.NA
    return normalizar(d[["ts", "nodo"] + CAMPOS])


def normalizar(d):
    """Tipos canónicos: ts en UTC, enteros, booleanos y flotantes; texto en origen."""
    d = d.copy()
    d["ts"] = pd.to_datetime(d["ts"], utc=True)
    for c in ("t", "hr", "pr", "i", "i_max"):
        d[c] = pd.to_numeric(d[c], errors="coerce").astype("float64")
    for c in ("seq", "retraso_ms", "puerta_n", "agua_n", "est"):
        d[c] = pd.to_numeric(d[c], errors="coerce").astype("Int64")
    for c in ("puerta", "agua"):
        d[c] = pd.to_numeric(d[c], errors="coerce").map(lambda v: pd.NA if pd.isna(v) else bool(v)).astype("boolean")
    d["origen"] = d["origen"].astype("string").fillna("")
    d["nodo"] = d["nodo"].astype("string")
    return d.sort_values(["nodo", "ts"]).reset_index(drop=True)


# ----------------------------------------------------------------------------------------------------
# Pasos de preprocesamiento y filtrado. Cada uno devuelve (datos, resumen_del_paso).
# ----------------------------------------------------------------------------------------------------
def filtrar_origen(d):
    """Solo muestras del sensor real; las de prueba y simuladas (octubre 10, 11 y 17) no entran."""
    cuenta = d["origen"].value_counts().to_dict()
    d = d[d["origen"] == "sensor"].copy()
    return d, {"entrada": int(sum(cuenta.values())), "por_origen": {k: int(v) for k, v in cuenta.items()},
               "salida": len(d)}


def deduplicar(d):
    """Una muestra por nodo y marca de tiempo; ante duplicado se conserva la última recibida."""
    n = len(d)
    d = d.drop_duplicates(subset=["nodo", "ts"], keep="last").copy()
    return d, {"duplicadas": n - len(d)}


def validar_rangos(d):
    """Valores fuera del rango físico del sensor se retiran (NaN) y la muestra queda marcada."""
    d = d.copy()
    d["calidad"] = 0
    retirados = {}
    for c, (lo, hi) in RANGOS.items():
        malos = d[c].notna() & ((d[c] < lo) | (d[c] > hi))
        retirados[c] = int(malos.sum())
        if malos.any():
            d.loc[malos, c] = pd.NA if c == "retraso_ms" else float("nan")
            d.loc[malos, "calidad"] |= CAL_FUERA_RANGO
    # punto de rocío por encima de la temperatura es físicamente imposible
    malos = d["pr"].notna() & d["t"].notna() & (d["pr"] > d["t"] + 0.5)
    retirados["pr"] = int(malos.sum())
    d.loc[malos, "pr"] = float("nan")
    d.loc[malos, "calidad"] |= CAL_FUERA_RANGO
    return d, {"fuera_de_rango": retirados}


def marcar_arranques(d):
    """Un arranque es seq == 0 o un seq menor que el anterior. En los ARRANQUE_S siguientes la corriente
    refleja la asociación Wi-Fi y el apretón TLS del propio nodo, no la carga: se retira."""
    d = d.copy()
    d["arranque"] = False
    arranques = []
    for nodo, g in d.groupby("nodo", sort=False):
        seq = g["seq"].astype("float")
        es_arranque = (seq == 0) | (seq < seq.shift(1))
        d.loc[g.index[es_arranque.fillna(False)], "arranque"] = True
        for ts in g.loc[es_arranque.fillna(False), "ts"]:
            arranques.append((nodo, ts))
            ventana = (d["nodo"] == nodo) & (d["ts"] >= ts) & (d["ts"] < ts + pd.Timedelta(ARRANQUE_S, unit="s"))
            d.loc[ventana, ["i", "i_max"]] = float("nan")
            d.loc[ventana, "calidad"] |= CAL_ARRANQUE
    return d, {"arranques": len(arranques), "corriente_retirada": int((d["calidad"] & CAL_ARRANQUE > 0).sum())}


def retirar_fallos(d):
    """Lo que el propio nodo marcó como fallido no se usa; los bits informativos pasan a calidad."""
    d = d.copy()
    est = d["est"].fillna(0).astype(int)
    sht = est & EST_SHT31_FALLO > 0
    cor = est & EST_CORRIENTE_FALLO > 0
    agu = est & EST_AGUA_FALLO > 0
    d.loc[sht, ["t", "hr", "pr"]] = float("nan")
    d.loc[cor, ["i", "i_max"]] = float("nan")
    d.loc[agu, "agua"] = pd.NA
    d.loc[sht | cor | agu, "calidad"] |= CAL_FALLO_SENSOR
    d.loc[est & EST_SIN_HORA > 0, "calidad"] |= CAL_SIN_HORA
    d.loc[est & EST_SALTO > 0, "calidad"] |= CAL_CUADRICULA
    d.loc[est & EST_SIN_MQTT > 0, "calidad"] |= CAL_TARDIA
    return d, {"fallo_sht31": int(sht.sum()), "fallo_corriente": int(cor.sum()), "fallo_agua": int(agu.sum()),
               "sin_hora": int((est & EST_SIN_HORA > 0).sum()), "cuadricula": int((est & EST_SALTO > 0).sum()),
               "tardias": int((est & EST_SIN_MQTT > 0).sum())}


def marcar_huecos(d):
    """El nodo numera sus muestras (seq): un salto en seq dentro del mismo arranque es un hueco, sea cual
    sea el periodo vigente. Se marca la muestra posterior y se cuenta cuántas faltaron. El periodo de cada
    muestra se toma de la separación con la anterior (informativo; cambia con el comando "periodo")."""
    d = d.copy()
    d["periodo"] = PERIODO_S
    d["faltantes"] = 0
    huecos, apagados = [], []
    for nodo, g in d.groupby("nodo", sort=False):
        delta = g["ts"].diff().dt.total_seconds()
        d.loc[g.index, "periodo"] = delta.where((delta > 0) & ~g["arranque"]).fillna(PERIODO_S).round().astype(int)
        salto = g["seq"].astype("float").diff()
        hueco = (salto > 1) & ~g["arranque"]
        faltan = (salto - 1).where(hueco, 0).fillna(0).astype(int)
        d.loc[g.index, "faltantes"] = faltan
        d.loc[g.index[hueco.fillna(False)], "calidad"] |= CAL_HUECO_ANTES
        for idx in g.index[hueco.fillna(False)]:
            huecos.append({"nodo": nodo, "inicio": g.loc[idx, "ts"] - pd.Timedelta(seconds=float(delta[idx])),
                           "fin": g.loc[idx, "ts"], "faltantes": int(faltan[idx]), "tipo": "hueco"})
        # Un arranque precedido de más de 1,5 periodos sin muestras es un apagado: el nodo no registró nada en
        # ese lapso (sin energía, sin reloj o reiniciando). Se cuenta aparte, con las muestras que habrían cabido.
        periodo_prev = d.loc[g.index, "periodo"].shift(1)
        apagado = g["arranque"] & (delta > 1.5 * periodo_prev)
        for idx in g.index[apagado.fillna(False)]:
            apagados.append({"nodo": nodo, "inicio": g.loc[idx, "ts"] - pd.Timedelta(seconds=float(delta[idx])),
                             "fin": g.loc[idx, "ts"], "faltantes": int(round(delta[idx] / periodo_prev[idx]) - 1), "tipo": "apagado"})
    return d, {"huecos": len(huecos), "muestras_faltantes": int(d["faltantes"].sum()), "apagados": len(apagados),
               "muestras_sin_registrar": int(sum(a["faltantes"] for a in apagados))}, huecos + apagados


def histeresis_agua(d):
    """La sonda de agua es un umbral sobre un ADC: una sola muestra en 'agua' rodeada de 'seco' es rebote.
    Se exige presencia en dos muestras consecutivas para darla por válida."""
    d = d.copy()
    d["agua_f"] = d["agua"]
    suprimidas = 0
    for nodo, g in d.groupby("nodo", sort=False):
        a = g["agua"].fillna(False).astype(bool)
        aislada = a & ~a.shift(1, fill_value=False) & ~a.shift(-1, fill_value=False)
        d.loc[g.index[aislada], "agua_f"] = False
        d.loc[g.index[aislada], "calidad"] |= CAL_AGUA_REBOTE
        suprimidas += int(aislada.sum())
    return d, {"agua_rebotes_suprimidos": suprimidas}


def derivar(d):
    """Potencia aparente estimada con la tensión nominal. El factor de potencia de la carga del cuarto no se
    conoce, así que no se convierte a vatios."""
    d = d.copy()
    d["potencia_va"] = (d["i"] * V_NOMINAL).round(1)
    d["energia_vah"] = (d["potencia_va"] * d["periodo"] / 3600.0).round(4)   # por muestra; se suma por ventana
    return d, {"v_nominal": V_NOMINAL, "energia_vah_total": round(float(d["energia_vah"].sum()), 2)}


def extraer_eventos(d, huecos):
    """Tabla de eventos a partir de las transiciones de las señales ya filtradas."""
    eventos = []
    for nodo, g in d.groupby("nodo", sort=False):
        g = g.reset_index(drop=True)
        for senal, tipo in (("puerta", "puerta_abierta"), ("agua_f", "agua")):
            s = g[senal].fillna(False).astype(bool)
            inicio = None
            for k in range(len(g)):
                if s[k] and inicio is None:
                    inicio = g.loc[k, "ts"]
                elif not s[k] and inicio is not None:
                    eventos.append({"nodo": nodo, "tipo": tipo, "inicio": inicio, "fin": g.loc[k, "ts"],
                                    "duracion_s": (g.loc[k, "ts"] - inicio).total_seconds()})
                    inicio = None
            if inicio is not None:
                eventos.append({"nodo": nodo, "tipo": tipo, "inicio": inicio, "fin": pd.NaT, "duracion_s": float("nan")})
        for ts in g.loc[g["arranque"], "ts"]:
            eventos.append({"nodo": nodo, "tipo": "arranque", "inicio": ts, "fin": ts, "duracion_s": 0.0})
        tard = (g["calidad"] & CAL_TARDIA) > 0
        inicio = None
        for k in range(len(g)):
            if tard[k] and inicio is None:
                inicio = g.loc[k, "ts"]
            elif not tard[k] and inicio is not None:
                eventos.append({"nodo": nodo, "tipo": "entrega_tardia", "inicio": inicio, "fin": g.loc[k - 1, "ts"],
                                "duracion_s": (g.loc[k - 1, "ts"] - inicio).total_seconds()})
                inicio = None
    for h in huecos:
        eventos.append({"nodo": h["nodo"], "tipo": h.get("tipo", "hueco"), "inicio": h["inicio"], "fin": h["fin"],
                        "duracion_s": (h["fin"] - h["inicio"]).total_seconds(), "faltantes": h["faltantes"]})
    e = pd.DataFrame(eventos, columns=["nodo", "tipo", "inicio", "fin", "duracion_s", "faltantes"])
    return e.sort_values(["inicio", "tipo"]).reset_index(drop=True)


def procesar(d):
    """Encadena los pasos y devuelve (limpia, eventos, resumen)."""
    resumen = {"entrada": len(d)}
    d, r = filtrar_origen(d); resumen["origen"] = r
    d, r = deduplicar(d); resumen["duplicados"] = r
    d, r = validar_rangos(d); resumen["rangos"] = r
    d, r = marcar_arranques(d); resumen["arranques"] = r
    d, r = retirar_fallos(d); resumen["fallos"] = r
    d, r, huecos = marcar_huecos(d); resumen["huecos"] = r
    d, r = histeresis_agua(d); resumen["agua"] = r
    d, r = derivar(d); resumen["derivados"] = r
    eventos = extraer_eventos(d, huecos)
    resumen["salida"] = len(d)
    resumen["con_observaciones"] = int((d["calidad"] > 0).sum())
    resumen["eventos"] = eventos["tipo"].value_counts().to_dict() if len(eventos) else {}
    columnas = ["ts", "nodo", "seq", "periodo", "retraso_ms", "t", "hr", "pr", "i", "i_max", "potencia_va",
                "energia_vah", "puerta", "puerta_n", "agua", "agua_f", "agua_n", "est", "calidad", "arranque", "faltantes"]
    return d[columnas].reset_index(drop=True), eventos, resumen


# ----------------------------------------------------------------------------------------------------
# Salidas
# ----------------------------------------------------------------------------------------------------
def escribir_archivos(limpia, eventos, resumen, salida, nombre):
    os.makedirs(salida, exist_ok=True)
    l = limpia.copy()
    l["ts_local"] = l["ts"].dt.tz_convert(ZONA).dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    l.to_csv(os.path.join(salida, f"{nombre}_limpia.csv"), index=False)
    e = eventos.copy()
    for c in ("inicio", "fin"):
        e[c] = pd.to_datetime(e[c], utc=True).dt.tz_convert(ZONA).dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    e.to_csv(os.path.join(salida, f"{nombre}_eventos.csv"), index=False)
    with open(os.path.join(salida, f"{nombre}_resumen.json"), "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2, default=str)
    log.info("escrito %s_{limpia,eventos}.csv y %s_resumen.json en %s", nombre, nombre, salida)


def escribir_influx(cliente, org, deposito, limpia, eventos):
    from influxdb_client import Point, WritePrecision
    from influxdb_client.client.write_api import SYNCHRONOUS
    w = cliente.write_api(write_options=SYNCHRONOUS)
    puntos = []
    for fila in limpia.itertuples(index=False):
        p = Point("telemetria_limpia").tag("nodo", fila.nodo).time(fila.ts.to_pydatetime(), WritePrecision.S)
        for c in ("t", "hr", "pr", "i", "i_max", "potencia_va", "energia_vah"):
            v = getattr(fila, c)
            if pd.notna(v):
                p = p.field(c, float(v))
        for c in ("seq", "periodo", "retraso_ms", "puerta_n", "agua_n", "est", "calidad", "faltantes"):
            v = getattr(fila, c)
            if pd.notna(v):
                p = p.field(c, int(v))
        for c in ("puerta", "agua", "agua_f", "arranque"):
            v = getattr(fila, c)
            if pd.notna(v):
                p = p.field(c, bool(v))
        puntos.append(p)
    for ev in eventos.itertuples(index=False):
        p = (Point("eventos").tag("nodo", ev.nodo).tag("tipo", ev.tipo)
             .time(pd.Timestamp(ev.inicio).to_pydatetime(), WritePrecision.S))
        if pd.notna(ev.duracion_s):
            p = p.field("duracion_s", float(ev.duracion_s))
        if pd.notna(ev.fin):
            p = p.field("fin", int(pd.Timestamp(ev.fin).timestamp()))
        if pd.notna(ev.faltantes):
            p = p.field("faltantes", int(ev.faltantes))
        puntos.append(p)
    for k in range(0, len(puntos), 500):                 # por lotes, para no exceder el tiempo de espera
        w.write(bucket=deposito, org=org, record=puntos[k:k + 500])
    w.close()
    log.info("escritos %d puntos en %s", len(puntos), deposito)


def escribir_resumen_influx(cliente, org, deposito, resumen, desde, hasta):
    """Un punto por corrida con los conteos, para el panel y para la evidencia del informe."""
    from influxdb_client import Point, WritePrecision
    from influxdb_client.client.write_api import SYNCHRONOUS
    p = (Point("procesador").time(hasta, WritePrecision.S)
         .field("entrada", int(resumen["entrada"])).field("salida", int(resumen["salida"]))
         .field("con_observaciones", int(resumen["con_observaciones"]))
         .field("duplicadas", int(resumen["duplicados"]["duplicadas"]))
         .field("arranques", int(resumen["arranques"]["arranques"]))
         .field("huecos", int(resumen["huecos"]["huecos"])).field("apagados", int(resumen["huecos"]["apagados"]))
         .field("tardias", int(resumen["fallos"]["tardias"]))
         .field("desde", int(desde.timestamp())))
    w = cliente.write_api(write_options=SYNCHRONOUS)
    w.write(bucket=deposito, org=org, record=p)
    w.close()


# ----------------------------------------------------------------------------------------------------
def leer_configuracion(ruta):
    cfg = {}
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                k, v = linea.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"')
    faltan = [k for k in ("INFLUX_URL", "INFLUX_TOKEN", "INFLUX_ORG", "INFLUX_BUCKET_CRUDO",
                          "INFLUX_BUCKET_PROCESADO") if k not in cfg]
    if faltan:
        sys.exit(f"{ruta}: faltan {faltan}")
    return cfg


def duracion(texto):
    unidades = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return timedelta(seconds=int(texto[:-1]) * unidades[texto[-1]])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", help="procesar este archivo CSV en lugar de InfluxDB")
    ap.add_argument("--salida", default="procesado", help="carpeta de salida con --csv")
    ap.add_argument("--nodo", default="nodo1", help="nombre del nodo para los CSV")
    ap.add_argument("--influx", action="store_true", help="leer de InfluxDB y escribir al depósito procesado")
    ap.add_argument("--config", default="/etc/puente/procesador.env")
    ap.add_argument("--desde", help="inicio (hora local ISO o UTC con Z)")
    ap.add_argument("--hasta", help="fin (por defecto, ahora)")
    ap.add_argument("--ventana", help="procesar los últimos N (por ejemplo 30m, 2h, 1d)")
    ap.add_argument("--simular", action="store_true", help="con --influx: no escribir, solo mostrar el resumen")
    a = ap.parse_args()

    if a.csv:
        d = leer_csv(a.csv, a.nodo)
        limpia, eventos, resumen = procesar(d)
        nombre = os.path.splitext(os.path.basename(a.csv))[0]
        escribir_archivos(limpia, eventos, resumen, a.salida, nombre)
        print(json.dumps(resumen, ensure_ascii=False, indent=2, default=str))
        return

    if not a.influx:
        ap.error("indique --csv o --influx")
    from influxdb_client import InfluxDBClient
    cfg = leer_configuracion(a.config)
    hasta = pd.Timestamp(a.hasta).tz_localize(ZONA) if a.hasta and "Z" not in a.hasta and "+" not in a.hasta \
        else (pd.Timestamp(a.hasta) if a.hasta else pd.Timestamp.now(tz="UTC"))
    hasta = hasta.tz_convert("UTC")
    if a.ventana:
        desde = hasta - duracion(a.ventana)
    elif a.desde:
        desde = pd.Timestamp(a.desde)
        desde = (desde.tz_localize(ZONA) if desde.tzinfo is None else desde).tz_convert("UTC")
    else:
        ap.error("indique --desde o --ventana")
    # Se leen CONTEXTO_S antes del inicio: sin la muestra anterior no se ve un arranque, un hueco ni un apagado que
    # empiece antes de la ventana. Solo se escriben las muestras de la ventana y los eventos que terminan en ella.
    # tiempo de espera largo: en la Pi una escritura grande puede tardar más de los 10 s por defecto
    with InfluxDBClient(url=cfg["INFLUX_URL"], token=cfg["INFLUX_TOKEN"], org=cfg["INFLUX_ORG"], timeout=120_000) as cliente:
        d = leer_influx(cliente, cfg["INFLUX_ORG"], cfg["INFLUX_BUCKET_CRUDO"],
                        desde - timedelta(seconds=CONTEXTO_S), hasta)
        limpia, eventos, resumen = procesar(d)
        limpia = limpia[limpia["ts"] >= desde]
        if len(eventos):
            fin = pd.to_datetime(eventos["fin"], utc=True).fillna(hasta)
            eventos = eventos[fin >= desde]
        resumen["desde"], resumen["hasta"] = desde.isoformat(), hasta.isoformat()
        print(json.dumps(resumen, ensure_ascii=False, indent=2, default=str))
        if not a.simular:
            escribir_influx(cliente, cfg["INFLUX_ORG"], cfg["INFLUX_BUCKET_PROCESADO"], limpia, eventos)
            escribir_resumen_influx(cliente, cfg["INFLUX_ORG"], cfg["INFLUX_BUCKET_PROCESADO"], resumen,
                                    desde.to_pydatetime(), hasta.to_pydatetime())


if __name__ == "__main__":
    main()
