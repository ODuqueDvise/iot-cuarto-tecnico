# -*- coding: utf-8 -*-
"""Puente MQTT a InfluxDB.

Se suscribe a la telemetría de todos los nodos y la escribe en InfluxDB por lotes.
El intervalo de vaciado es corto (10 s) porque el detector de anomalías lee de la base de datos.
Una sola etiqueta (nodo) para mantener baja la cardinalidad de series.
"""
import json
import logging
import os
import signal
import sys
import time

import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point, WriteOptions, WritePrecision

log = logging.getLogger("puente")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CFG = {k: os.environ[k] for k in ("MQTT_HOST", "MQTT_CA", "MQTT_CERT", "MQTT_KEY",
                                   "INFLUX_URL", "INFLUX_TOKEN", "INFLUX_ORG", "INFLUX_BUCKET")}
MQTT_PUERTO = int(os.environ.get("MQTT_PUERTO", "8883"))
CAMPOS_NUM = ("t", "hr", "i", "seq")
CAMPOS_BOOL = ("puerta", "agua")

influx = InfluxDBClient(url=CFG["INFLUX_URL"], token=CFG["INFLUX_TOKEN"], org=CFG["INFLUX_ORG"])
escritor = influx.write_api(write_options=WriteOptions(batch_size=100, flush_interval=10_000,
                                                       jitter_interval=0, retry_interval=5_000,
                                                       max_retries=5))


def punto_desde(tema, carga):
    """Convierte un mensaje JSON de telemetría en un punto de InfluxDB."""
    nodo = tema.split("/")[1]
    d = json.loads(carga)
    p = Point("telemetria").tag("nodo", nodo)
    for c in CAMPOS_NUM:
        if c in d:
            p = p.field(c, float(d[c]))
    for c in CAMPOS_BOOL:
        if c in d:
            p = p.field(c, bool(d[c]))
    if "origen" in d:
        p = p.field("origen", str(d["origen"]))
    ts = d.get("ts")
    # El nodo manda la hora en segundos desde 1970 (SNTP contra el borde). Si no es creíble, se usa la del borde.
    if isinstance(ts, (int, float)) and ts > 1_600_000_000:
        p = p.time(int(ts), WritePrecision.S)
    else:
        p = p.time(int(time.time()), WritePrecision.S)
    return p


def al_conectar(cliente, datos, banderas, codigo, propiedades):
    log.info("MQTT conectado: %s", codigo)
    cliente.subscribe([("cuarto/+/telemetria", 1), ("cuarto/+/estado", 1)])


def al_mensaje(cliente, datos, msg):
    try:
        partes = msg.topic.split("/")
        if partes[-1] == "telemetria":
            escritor.write(bucket=CFG["INFLUX_BUCKET"], record=punto_desde(msg.topic, msg.payload))
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
    cliente.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
