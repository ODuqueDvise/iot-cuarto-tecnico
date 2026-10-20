# -*- coding: utf-8 -*-
"""Puente MQTT a InfluxDB.

Se suscribe a la telemetría de todos los nodos y la escribe en InfluxDB por lotes.
El intervalo de vaciado es corto (10 s) porque el detector de anomalías lee de la base de datos.
Una sola etiqueta (nodo) para mantener baja la cardinalidad de series.

La hora de cada punto es la del nodo (campo "ts", sincronizado por SNTP con el borde). Un mensaje sin hora
válida no se mezcla con la serie: va a la medición "telemetria_sin_hora" con la hora de llegada en
nanosegundos, para que varios mensajes que llegan juntos desde la cola del nodo no se sobrescriban.
"""
import json
import logging
import os
import signal
import sys
import threading
import time

import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point, WriteOptions, WritePrecision

log = logging.getLogger("puente")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CFG = {k: os.environ[k] for k in ("MQTT_HOST", "MQTT_CA", "MQTT_CERT", "MQTT_KEY",
                                   "INFLUX_URL", "INFLUX_TOKEN", "INFLUX_ORG", "INFLUX_BUCKET")}
MQTT_PUERTO = int(os.environ.get("MQTT_PUERTO", "8883"))
# Los tipos de campo no pueden cambiar en InfluxDB: t, hr, i y seq ya existen como float en el depósito.
CAMPOS_FLOAT = ("t", "hr", "pr", "i", "i_max", "seq")
CAMPOS_INT = ("puerta_n", "agua_n", "est", "retraso_ms", "periodo")
CAMPOS_BOOL = ("puerta", "agua")
TS_MINIMO = 1_600_000_000   # cualquier hora anterior a septiembre de 2020 se toma como "sin hora"
PERIODO_BORDE_S = 30        # salud del borde: temperatura del SoC y memoria disponible
ARCHIVO_TEMPERATURA = "/sys/class/thermal/thermal_zone0/temp"
ARCHIVO_MEMORIA = "/proc/meminfo"

influx = InfluxDBClient(url=CFG["INFLUX_URL"], token=CFG["INFLUX_TOKEN"], org=CFG["INFLUX_ORG"])
escritor = influx.write_api(write_options=WriteOptions(batch_size=100, flush_interval=10_000,
                                                       jitter_interval=0, retry_interval=5_000,
                                                       max_retries=5))


def punto_desde(tema, carga):
    """Convierte un mensaje JSON de telemetría en un punto de InfluxDB.

    Devuelve (punto, con_hora). Un campo ausente o nulo no se escribe: el nodo omite lo que no midió.
    """
    nodo = tema.split("/")[1]
    d = json.loads(carga)
    ts = d.get("ts")
    con_hora = isinstance(ts, (int, float)) and not isinstance(ts, bool) and ts > TS_MINIMO
    p = Point("telemetria" if con_hora else "telemetria_sin_hora").tag("nodo", nodo)
    for c in CAMPOS_FLOAT:
        if d.get(c) is not None:
            p = p.field(c, float(d[c]))
    for c in CAMPOS_INT:
        if d.get(c) is not None:
            p = p.field(c, int(d[c]))
    for c in CAMPOS_BOOL:
        if d.get(c) is not None:
            p = p.field(c, bool(d[c]))
    if d.get("origen") is not None:
        p = p.field("origen", str(d["origen"]))
    if con_hora:
        p = p.time(int(ts), WritePrecision.S)
    else:
        p = p.time(time.time_ns(), WritePrecision.NS)
    return p, con_hora


def punto_borde(archivo_temperatura=ARCHIVO_TEMPERATURA, archivo_memoria=ARCHIVO_MEMORIA):
    """Salud de la Pi para el panel: temperatura del SoC (°C) y memoria disponible (MB). None si no hay datos."""
    p = Point("borde")
    hay = False
    try:
        with open(archivo_temperatura) as f:
            p = p.field("t_soc", int(f.read().strip()) / 1000.0)
            hay = True
    except (OSError, ValueError):
        pass
    try:
        with open(archivo_memoria) as f:
            for linea in f:
                if linea.startswith("MemAvailable:"):
                    p = p.field("mem_disp_mb", int(linea.split()[1]) / 1024.0)
                    hay = True
                    break
    except (OSError, ValueError):
        pass
    return p.time(time.time_ns(), WritePrecision.NS) if hay else None


def tarea_borde(detener):
    while not detener.wait(PERIODO_BORDE_S):
        punto = punto_borde()
        if punto is not None:
            escritor.write(bucket=CFG["INFLUX_BUCKET"], record=punto)


def al_conectar(cliente, datos, banderas, codigo, propiedades):
    log.info("MQTT conectado: %s", codigo)
    cliente.subscribe([("cuarto/+/telemetria", 1), ("cuarto/+/estado", 1)])


def al_mensaje(cliente, datos, msg):
    try:
        partes = msg.topic.split("/")
        if partes[-1] == "telemetria":
            punto, con_hora = punto_desde(msg.topic, msg.payload)
            escritor.write(bucket=CFG["INFLUX_BUCKET"], record=punto)
            if not con_hora:
                log.warning("mensaje de %s sin hora válida: va a telemetria_sin_hora con la hora de llegada", partes[1])
        elif partes[-1] == "estado":
            estado = msg.payload.decode(errors="replace")
            escritor.write(bucket=CFG["INFLUX_BUCKET"],
                           record=Point("estado").tag("nodo", partes[1]).field("en_linea", estado == "en_linea"))
            log.info("estado de %s: %s", partes[1], estado)
    except Exception as e:  # un mensaje malformado no debe tumbar el puente
        log.warning("mensaje descartado en %s: %s", msg.topic, e)


def main():
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="borde-puente", protocol=mqtt.MQTTv5)
    cliente.tls_set(ca_certs=CFG["MQTT_CA"], certfile=CFG["MQTT_CERT"], keyfile=CFG["MQTT_KEY"])
    cliente.on_connect = al_conectar
    cliente.on_message = al_mensaje
    cliente.connect(CFG["MQTT_HOST"], MQTT_PUERTO, keepalive=30)

    def salir(*_):
        log.info("cerrando")
        cliente.disconnect()
        escritor.close()
        influx.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, salir)
    signal.signal(signal.SIGINT, salir)
    threading.Thread(target=tarea_borde, args=(threading.Event(),), daemon=True).start()
    cliente.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
