# -*- coding: utf-8 -*-
"""Pruebas de la conversión de mensajes del puente, sin MQTT ni InfluxDB.

En la Pi, con el entorno del puente:
    cd borde/puente && /opt/puente/.venv/bin/python prueba_puente.py
"""
import json
import os

for k in ("MQTT_HOST", "MQTT_CA", "MQTT_CERT", "MQTT_KEY", "INFLUX_URL", "INFLUX_TOKEN", "INFLUX_ORG", "INFLUX_BUCKET"):
    os.environ.setdefault(k, "http://localhost:1" if k == "INFLUX_URL" else "prueba")

import puente  # noqa: E402

fallos = 0


def revisar(nombre, condicion, detalle=""):
    global fallos
    print(f"{'ok   ' if condicion else 'FALLA'}  {nombre}" + (f"  ({detalle})" if not condicion and detalle else ""))
    fallos += not condicion


def lp(mensaje):
    punto, con_hora = puente.punto_desde("cuarto/nodo1/telemetria", json.dumps(mensaje))
    return punto.to_line_protocol(), con_hora


# Mensaje completo del firmware de la etapa 2, con hora.
linea, con_hora = lp({"nodo": "nodo1", "ts": 1791732900, "seq": 9, "periodo": 30, "retraso_ms": 1, "t": 22.78,
                      "hr": 47.29, "pr": 10.97, "i": 1.673, "i_max": 1.699, "puerta": False, "puerta_n": 0,
                      "agua": False, "agua_n": 0, "est": 16, "origen": "simulado"})
revisar("con hora va a la medición telemetria", con_hora and linea.startswith("telemetria,nodo=nodo1 "), linea)
revisar("marca de tiempo en segundos", linea.endswith(" 1791732900"), linea)
# En protocolo de línea un float entero se escribe sin decimales ("seq=9"); un entero llevaría "i".
revisar("seq sigue siendo float (tipo ya existente)", "seq=9," in linea and "seq=9i" not in linea, linea)
revisar("enteros con sufijo i", all(f"{c}i" in linea for c in ("est=16", "retraso_ms=1", "periodo=30", "puerta_n=0")), linea)
revisar("campos nuevos presentes", "pr=10.97" in linea and "i_max=1.699" in linea, linea)

# Mensaje sin hora (el nodo arrancó sin el borde): medición aparte y hora de llegada en nanosegundos.
linea, con_hora = lp({"nodo": "nodo1", "seq": 0, "t": 22.06, "est": 40, "origen": "simulado"})
revisar("sin hora va a telemetria_sin_hora", not con_hora and linea.startswith("telemetria_sin_hora,"), linea)
revisar("hora de llegada en nanosegundos", len(linea.rsplit(" ", 1)[1]) >= 19, linea)

# Dos mensajes sin hora seguidos no comparten marca de tiempo.
a, _ = lp({"seq": 0, "t": 1.0})
b, _ = lp({"seq": 1, "t": 1.0})
revisar("dos mensajes sin hora no se sobrescriben", a.rsplit(" ", 1)[1] != b.rsplit(" ", 1)[1])

# Campos ausentes o nulos no se escriben (sensor ausente).
linea, _ = lp({"ts": 1791732930, "seq": 10, "i": None, "puerta": None, "origen": "sensor"})
revisar("nulos y ausentes se omiten", "i=" not in linea and "puerta=" not in linea and "t=" not in linea, linea)

# Mensaje del firmware de la etapa 1 (compatibilidad).
linea, con_hora = lp({"nodo": "nodo1", "ts": 1791673000, "seq": 3, "t": 22.1, "hr": 48.2, "i": 1.43,
                      "puerta": False, "agua": False, "origen": "simulado"})
revisar("mensaje de la etapa 1 sigue funcionando", con_hora and "t=22.1" in linea and "agua=false" in linea, linea)

# Una hora booleana no se acepta como hora.
_, con_hora = lp({"ts": True, "seq": 1})
revisar("ts booleano no cuenta como hora", not con_hora)

# Salud del borde con archivos de ejemplo (en la Pi se leen los reales).
import tempfile  # noqa: E402
with tempfile.TemporaryDirectory() as d:
    tmp_t, tmp_m = os.path.join(d, "temp"), os.path.join(d, "meminfo")
    open(tmp_t, "w").write("55537\n")
    open(tmp_m, "w").write("MemTotal:  925000 kB\nMemFree:  100000 kB\nMemAvailable:  499712 kB\n")
    linea = puente.punto_borde(tmp_t, tmp_m).to_line_protocol()
    revisar("salud del borde: temperatura y memoria", linea.startswith("borde ") and "t_soc=55.537" in linea
            and "mem_disp_mb=488" in linea, linea)
    revisar("salud del borde sin archivos devuelve None", puente.punto_borde(tmp_t + "x", tmp_m + "x") is None)
if os.path.exists(puente.ARCHIVO_TEMPERATURA):
    revisar("salud del borde con los archivos reales", puente.punto_borde() is not None)

print("\nTodas las pruebas pasaron" if fallos == 0 else f"\n{fallos} pruebas fallaron")
raise SystemExit(fallos != 0)
