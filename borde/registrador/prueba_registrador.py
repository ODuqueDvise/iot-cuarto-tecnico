# -*- coding: utf-8 -*-
"""Pruebas del registrador CSV sin MQTT.

En la Pi, con el entorno del puente:
    cd borde/registrador && /opt/puente/.venv/bin/python prueba_registrador.py
"""
import csv
import os
import tempfile

from registrador_csv import COLUMNAS, Registro, fila_desde

fallos = 0


def revisar(nombre, condicion, detalle=""):
    global fallos
    print(f"{'ok   ' if condicion else 'FALLA'}  {nombre}" + (f"  ({detalle})" if not condicion and detalle else ""))
    fallos += not condicion


# Mismo mensaje que produjo la línea serie REG,9,1791732900,2026-10-11T10:35:00-05:00,1,22.78,47.29,10.97,...
m = {"nodo": "nodo1", "ts": 1791732900, "seq": 9, "periodo": 30, "retraso_ms": 1, "t": 22.78, "hr": 47.29,
     "pr": 10.97, "i": 1.673, "i_max": 1.699, "puerta": False, "puerta_n": 0, "agua": False, "agua_n": 0,
     "est": 16, "origen": "simulado"}
serie = "9,1791732900,2026-10-11T10:35:00-05:00,1,22.78,47.29,10.97,1.673,1.699,0,0,0,0,16,simulado".split(",")
fila = fila_desde(m)
revisar("fila igual a la línea serie", fila == serie, f"{fila} != {serie}")
revisar("15 columnas", len(fila) == len(COLUMNAS))
revisar("sin hora no se registra", fila_desde({"seq": 0, "t": 22.0}) is None)
revisar("ts booleano no es hora", fila_desde({"ts": True, "seq": 1}) is None)

# Sensores ausentes: celdas vacías y contadores en 0, igual que la línea serie.
f2 = fila_desde({"ts": 1791732930, "seq": 10, "retraso_ms": 2, "est": 0, "origen": "sensor"})
revisar("ausentes vacíos y contadores en 0", f2[4:15] == ["", "", "", "", "", "", "0", "", "0", "0", "sensor"], f2)

with tempfile.TemporaryDirectory() as d:
    r = Registro(d)
    revisar("primera escritura", r.escribir("nodo1", fila))
    revisar("duplicado descartado", not r.escribir("nodo1", fila))
    revisar("siguiente muestra escrita", r.escribir("nodo1", f2))
    ruta = os.path.join(d, "nodo1_20261011.csv")
    with open(ruta, newline="", encoding="utf-8") as f:
        filas = list(csv.reader(f))
    revisar("archivo del día con cabecera y dos filas", filas[0] == COLUMNAS and len(filas) == 3, len(filas))
    # Un registrador nuevo (reinicio del servicio) lee lo escrito y no duplica.
    r2 = Registro(d)
    revisar("tras reinicio, el duplicado sigue descartado", not r2.escribir("nodo1", fila))
    # Medianoche en Colombia: 05:00 UTC del 12 de octubre va al archivo del 12.
    f3 = fila_desde(dict(m, ts=1791781200, seq=11))
    r2.escribir("nodo1", f3)
    revisar("cambio de día por hora local", os.path.exists(os.path.join(d, "nodo1_20261012.csv")))

print("\nTodas las pruebas pasaron" if fallos == 0 else f"\n{fallos} pruebas fallaron")
raise SystemExit(fallos != 0)
