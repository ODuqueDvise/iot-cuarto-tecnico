# -*- coding: utf-8 -*-
"""Registrador CSV del borde (tarea N-05 de la Actividad 2).

Se suscribe a la telemetría de los nodos y escribe un CSV por nodo y por día, con las mismas columnas que la
captura serie del Mac (herramientas/capturar_serie.py), para poder contrastar ambos archivos. Es independiente
del puente y de InfluxDB: si alguno de los dos falla, el archivo se sigue llenando.

- Solo registra mensajes con hora válida del nodo; los que no la traen quedan en el registro del servicio.
- Cada línea se vacía a disco en cuanto llega.
- QoS 1 puede entregar un mensaje dos veces: una marca de tiempo ya escrita en el archivo del día no se repite.
- Sesión persistente de MQTT 5 (una hora): si el servicio se reinicia, Mosquitto le entrega lo que llegó mientras
  tanto.

Variables de entorno: las de /etc/puente/puente.env (MQTT_HOST, MQTT_PUERTO, MQTT_CA, MQTT_CERT, MQTT_KEY) y
REGISTRO_DIR (por defecto /var/lib/registrador).
"""
import csv
import json
import logging
import os
import signal
import sys
from datetime import datetime, timedelta, timezone

log = logging.getLogger("registrador")

COLUMNAS = ["seq", "ts_epoch", "ts_local_iso", "retraso_ms", "t_c", "hr_pct", "punto_rocio_c",
            "i_media_a", "i_max_a", "puerta", "puerta_aperturas", "agua", "agua_eventos",
            "estado_sensores", "origen"]
ZONA = timezone(timedelta(hours=-5))   # Colombia, sin horario de verano
TS_MINIMO = 1_600_000_000


def fila_desde(d):
    """Convierte el JSON del nodo en una fila con el formato de la línea serie, o None si no trae hora válida."""
    ts = d.get("ts")
    if not (isinstance(ts, (int, float)) and not isinstance(ts, bool) and ts > TS_MINIMO):
        return None

    def num(c, decimales):
        v = d.get(c)
        return "" if v is None else f"{float(v):.{decimales}f}"

    def ent(c, defecto=""):
        v = d.get(c)
        return defecto if v is None else str(int(v))

    def tri(c):
        v = d.get(c)
        return "" if v is None else ("1" if v else "0")

    ts = int(ts)
    iso = datetime.fromtimestamp(ts, ZONA).strftime("%Y-%m-%dT%H:%M:%S-05:00")
    # Los contadores van en 0 cuando el sensor está ausente, igual que en la línea serie.
    return [ent("seq"), str(ts), iso, ent("retraso_ms"), num("t", 2), num("hr", 2), num("pr", 2),
            num("i", 3), num("i_max", 3), tri("puerta"), ent("puerta_n", "0"), tri("agua"),
            ent("agua_n", "0"), ent("est"), str(d.get("origen", ""))]


class Registro:
    """Archivos CSV por nodo y día, con supresión de duplicados por marca de tiempo."""

    def __init__(self, directorio):
        self.directorio = directorio
        os.makedirs(directorio, exist_ok=True)
        self.vistos = {}   # ruta del archivo -> conjunto de ts ya escritos

    def ruta(self, nodo, ts):
        fecha = datetime.fromtimestamp(ts, ZONA).strftime("%Y%m%d")
        return os.path.join(self.directorio, f"{nodo}_{fecha}.csv")

    def _cargar(self, ruta):
        vistos = set()
        if os.path.exists(ruta):
            with open(ruta, newline="", encoding="utf-8") as f:
                for fila in csv.DictReader(f):
                    vistos.add(fila["ts_epoch"])
        # Solo se conservan los archivos del día en curso y el anterior.
        if len(self.vistos) > 2:
            for r in sorted(self.vistos)[:-2]:
                self.vistos.pop(r, None)
        self.vistos[ruta] = vistos
        return vistos

    def escribir(self, nodo, fila):
        """Escribe la fila; devuelve False si esa marca de tiempo ya estaba en el archivo."""
        ruta = self.ruta(nodo, int(fila[1]))
        vistos = self.vistos.get(ruta)
        if vistos is None:
            vistos = self._cargar(ruta)
        if fila[1] in vistos:
            return False
        nuevo = not os.path.exists(ruta) or os.path.getsize(ruta) == 0
        with open(ruta, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if nuevo:
                w.writerow(COLUMNAS)
            w.writerow(fila)
            f.flush()
            os.fsync(f.fileno())
        vistos.add(fila[1])
        return True


def main():
    import paho.mqtt.client as mqtt
    from paho.mqtt.packettypes import PacketTypes
    from paho.mqtt.properties import Properties

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = {k: os.environ[k] for k in ("MQTT_HOST", "MQTT_CA", "MQTT_CERT", "MQTT_KEY")}
    puerto = int(os.environ.get("MQTT_PUERTO", "8883"))
    registro = Registro(os.environ.get("REGISTRO_DIR", "/var/lib/registrador"))

    def al_conectar(cliente, datos, banderas, codigo, propiedades):
        log.info("MQTT conectado: %s (sesión previa: %s)", codigo, banderas.session_present)
        cliente.subscribe("cuarto/+/telemetria", qos=1)

    def al_mensaje(cliente, datos, msg):
        try:
            nodo = msg.topic.split("/")[1]
            d = json.loads(msg.payload)
            fila = fila_desde(d)
            if fila is None:
                log.warning("mensaje de %s sin hora válida (seq %s): no se registra", nodo, d.get("seq"))
            elif not registro.escribir(nodo, fila):
                log.info("duplicado de %s ts %s descartado", nodo, fila[1])
        except Exception as e:  # un mensaje malformado no debe detener el registrador
            log.warning("mensaje descartado en %s: %s", msg.topic, e)

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="borde-registrador", protocol=mqtt.MQTTv5)
    cliente.tls_set(ca_certs=cfg["MQTT_CA"], certfile=cfg["MQTT_CERT"], keyfile=cfg["MQTT_KEY"])
    cliente.on_connect = al_conectar
    cliente.on_message = al_mensaje
    sesion = Properties(PacketTypes.CONNECT)
    sesion.SessionExpiryInterval = 3600
    # connect_async: si el intermediario todavía no responde, loop_forever reintenta en lugar de terminar.
    cliente.connect_async(cfg["MQTT_HOST"], puerto, keepalive=30, clean_start=False, properties=sesion)

    def salir(*_):
        log.info("cerrando")
        cliente.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGTERM, salir)
    signal.signal(signal.SIGINT, salir)
    log.info("registrando en %s", registro.directorio)
    cliente.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
