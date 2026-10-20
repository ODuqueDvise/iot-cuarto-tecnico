#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Captura serie del nodo (decisión D8 del plan de la Actividad 2). Se ejecuta en el Mac.

Lee el puerto serie del ESP32, muestra cada registro en pantalla como una fila de una tabla con
rótulos y lo agrega a un CSV con la línea tal como la imprime el nodo. El nodo imprime cada muestra
como una línea que empieza por "REG,"; las demás líneas (mensajes de registro de ESP-IDF) se
muestran solo con --todo y nunca van al archivo. La pantalla es la vista en vivo de la estación de
medición durante la prueba; el archivo es el registro.

Ejemplos:
    python3 capturar_serie.py --puerto /dev/cu.usbserial-0001 --salida ../datos/prueba.csv
    python3 capturar_serie.py --puerto /dev/cu.usbserial-0001 --salida oficial.csv --muestras 360

Al terminar (por --muestras o con Ctrl+C) imprime un resumen: filas, huecos en seq, separación entre
marcas de tiempo, celdas vacías y origen. Requiere pyserial, que ya trae el entorno de ESP-IDF.
"""
import argparse
import csv
import os
import sys
import time

import serial

BITS = {1: "SHT31", 2: "corriente", 4: "agua", 8: "sin hora", 16: "cuadrícula", 32: "sin MQTT"}

COLUMNAS = ["seq", "ts_epoch", "ts_local_iso", "retraso_ms", "t_c", "hr_pct", "punto_rocio_c",
            "i_media_a", "i_max_a", "puerta", "puerta_aperturas", "agua", "agua_eventos",
            "estado_sensores", "origen"]


def abrir(puerto, baudios):
    # DTR y RTS en falso antes de abrir: en el DevKit esas líneas manejan el reinicio y el modo de
    # carga, y abrir el puerto con los valores por defecto puede reiniciar el nodo.
    s = serial.serial_for_url(puerto, baudios, timeout=1, do_not_open=True)
    s.dtr = False
    s.rts = False
    s.open()
    return s


def estado_texto(valor):
    """Bits de estado_sensores como palabras; vacío si todo está bien."""
    try:
        e = int(valor or 0)
    except ValueError:
        return valor
    return " ".join(n for b, n in BITS.items() if e & b)


CABECERA = (f"{'n':>4s}  {'hora local':19s}  {'T °C':>6s}  {'HR %':>6s}  {'rocío':>6s}  {'I med A':>8s}  "
            f"{'I máx A':>8s}  {'puerta':10s}  {'agua':8s}  {'ret ms':>6s}  estado")


def mostrar(n, fila):
    """Una fila de la tabla en pantalla. Entre paréntesis, los eventos contados en el intervalo."""
    hora = fila["ts_local_iso"][:19].replace("T", " ") if fila["ts_local_iso"] else "sin hora"
    puerta = ("abierta" if fila["puerta"] == "1" else "cerrada" if fila["puerta"] == "0" else "-")
    agua = ("AGUA" if fila["agua"] == "1" else "seca" if fila["agua"] == "0" else "-")
    if fila["puerta_aperturas"] not in ("", "0"):
        puerta += f"({fila['puerta_aperturas']})"
    if fila["agua_eventos"] not in ("", "0"):
        agua += f"({fila['agua_eventos']})"
    print(f"{n:4d}  {hora:19s}  {fila['t_c'] or '-':>6s}  {fila['hr_pct'] or '-':>6s}  "
          f"{fila['punto_rocio_c'] or '-':>6s}  {fila['i_media_a'] or '-':>8s}  {fila['i_max_a'] or '-':>8s}  "
          f"{puerta:10s}  {agua:8s}  {fila['retraso_ms']:>6s}  {estado_texto(fila['estado_sensores'])}", flush=True)


def resumir(filas, periodo):
    print("\nResumen de la captura")
    print(f"  filas: {len(filas)}")
    if not filas:
        return
    seqs = [int(f["seq"]) for f in filas]
    huecos = [(a, b) for a, b in zip(seqs, seqs[1:]) if b != a + 1]
    print(f"  seq de {seqs[0]} a {seqs[-1]}; discontinuidades: {len(huecos)} {huecos[:5]}")
    ts = [int(f["ts_epoch"]) for f in filas if f["ts_epoch"] not in ("", "0")]
    difs = sorted({b - a for a, b in zip(ts, ts[1:])})
    print(f"  filas con hora: {len(ts)}; separaciones distintas (s): {difs[:10]}"
          + ("" if difs in ([], [periodo]) else f"  <- se esperaba solo {periodo}"))
    vacias = {c: sum(1 for f in filas if f[c] == "") for c in COLUMNAS if c != "ts_local_iso"}
    print("  celdas vacías por columna: " + (", ".join(f"{c}={n}" for c, n in vacias.items() if n) or "ninguna"))
    retrasos = [int(f["retraso_ms"]) for f in filas if f["retraso_ms"] != ""]
    if retrasos:
        print(f"  retraso respecto de la cuadrícula (ms): mín {min(retrasos)}, máx {max(retrasos)}")
    print(f"  origen: {sorted({f['origen'] for f in filas})}")
    con_estado = sum(1 for f in filas if f["estado_sensores"] not in ("", "0"))
    print(f"  filas con algún bit de estado activo: {con_estado}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--puerto", required=True, help="por ejemplo /dev/cu.usbserial-0001 (ls /dev/cu.*)")
    ap.add_argument("--baudios", type=int, default=115200)
    ap.add_argument("--salida", required=True, help="archivo CSV; si existe, se agregan filas")
    ap.add_argument("--muestras", type=int, default=0, help="terminar tras N registros (0: hasta Ctrl+C)")
    ap.add_argument("--periodo", type=int, default=30, help="periodo esperado en s, para el resumen")
    ap.add_argument("--todo", action="store_true", help="mostrar también los mensajes de registro del nodo")
    a = ap.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(a.salida)), exist_ok=True)
    nuevo = not os.path.exists(a.salida) or os.path.getsize(a.salida) == 0
    filas = []
    with abrir(a.puerto, a.baudios) as s, open(a.salida, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(COLUMNAS)
            f.flush()
        print(f"Estación de medición: nodo en {a.puerto}; registro en {os.path.abspath(a.salida)}"
              + (f"; se detiene en {a.muestras} registros" if a.muestras else "; Ctrl+C para terminar"))
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  esperando la primera muestra del nodo (una cada {a.periodo} s)")
        print(CABECERA)
        try:
            while not a.muestras or len(filas) < a.muestras:
                linea = s.readline().decode("utf-8", errors="replace").strip()
                if not linea:
                    continue
                if not linea.startswith("REG,"):
                    if a.todo:
                        print(f"  {linea}")
                    continue
                valores = linea[4:].split(",")
                if len(valores) != len(COLUMNAS):
                    print(f"  línea incompleta descartada: {linea}", file=sys.stderr)
                    continue
                w.writerow(valores)
                f.flush()
                os.fsync(f.fileno())
                fila = dict(zip(COLUMNAS, valores))
                filas.append(fila)
                if len(filas) % 30 == 1 and len(filas) > 1:
                    print(CABECERA)   # la cabecera se repite cada 30 filas (15 min) para leerla en pantalla
                mostrar(len(filas), fila)
        except KeyboardInterrupt:
            pass
    resumir(filas, a.periodo)


if __name__ == "__main__":
    main()
