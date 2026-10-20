#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validador del archivo de registros (tarea N-05). Se ejecuta en el Mac; solo usa la biblioteca estándar,
salvo --xlsx, que necesita openpyxl.

Revisa un CSV con las columnas de la captura serie o del registrador del borde:
  - número de filas (con --muestras), seq consecutivo y separación constante entre marcas de tiempo;
  - celdas vacías (una columna vacía entera se informa como sensor ausente, no como falla);
  - origen (en la prueba oficial todo debe ser "sensor"), bits de estado_sensores y retraso;
  - valores fuera de los rangos de RF1 y series congeladas (el mismo valor durante mucho tiempo).

Ejemplos:
    validar_archivo.py ../datos/oficial_20261027_1000.csv --muestras 360 --oficial
    validar_archivo.py ../datos/borde/nodo1_20261027.csv --desde 2026-10-27T10:00:00 --muestras 360 \\
        --recortar ../datos/oficial_borde.csv
    validar_archivo.py ../datos/oficial_20261027_1000.csv --comparar ../datos/oficial_borde.csv
    validar_archivo.py ../datos/oficial_20261027_1000.csv --xlsx

Termina con código 0 si no hay fallas.
"""
import argparse
import csv
import os
import sys
from datetime import datetime, timedelta, timezone

COLUMNAS = ["seq", "ts_epoch", "ts_local_iso", "retraso_ms", "t_c", "hr_pct", "punto_rocio_c",
            "i_media_a", "i_max_a", "puerta", "puerta_aperturas", "agua", "agua_eventos",
            "estado_sensores", "origen"]
NUMERICAS = {"seq", "ts_epoch", "retraso_ms", "t_c", "hr_pct", "punto_rocio_c", "i_media_a", "i_max_a",
             "puerta", "puerta_aperturas", "agua", "agua_eventos", "estado_sensores"}
# Rangos de medición de RF1 (propuesta de la Actividad 1, Tabla I).
RANGOS = {"t_c": (0.0, 50.0), "hr_pct": (20.0, 90.0), "i_media_a": (0.0, 5.0), "i_max_a": (0.0, 5.0)}
BITS = {1: "fallo SHT31", 2: "fallo corriente", 4: "fallo sonda de agua", 8: "sin hora",
        16: "cuadrícula recalculada", 32: "sin MQTT al registrar"}
# Tolerancia al comparar: una unidad del último decimal impreso (la serie y el borde redondean distinto).
TOLERANCIA = {"t_c": 0.011, "hr_pct": 0.011, "punto_rocio_c": 0.011, "i_media_a": 0.0011, "i_max_a": 0.0011}
ZONA = timezone(timedelta(hours=-5))


def leer(ruta):
    with open(ruta, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        faltan = [c for c in COLUMNAS if c not in (r.fieldnames or [])]
        if faltan:
            sys.exit(f"{ruta}: faltan columnas {faltan}")
        return list(r)


def escribir(ruta, filas):
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)


def validar(filas, muestras, periodo, oficial):
    fallas, avisos = [], []
    n = len(filas)
    print(f"filas: {n}")
    if muestras and n != muestras:
        fallas.append(f"se esperaban {muestras} filas y hay {n}")
    if not filas:
        return fallas, avisos

    seq = [int(f["seq"]) for f in filas if f["seq"] != ""]
    saltos = [(a, b) for a, b in zip(seq, seq[1:]) if b != a + 1]
    print(f"seq: de {seq[0]} a {seq[-1]}, discontinuidades: {len(saltos)}")
    if saltos:
        fallas.append(f"seq no es consecutivo en {len(saltos)} puntos, por ejemplo {saltos[:3]}")

    ts = [int(f["ts_epoch"]) for f in filas if f["ts_epoch"] not in ("", "0")]
    if len(ts) < n:
        fallas.append(f"{n - len(ts)} filas sin hora")
    if ts:
        difs = [b - a for a, b in zip(ts, ts[1:])]
        malas = [d for d in difs if d != periodo]
        inicio = datetime.fromtimestamp(ts[0], ZONA).strftime("%Y-%m-%d %H:%M:%S")
        fin = datetime.fromtimestamp(ts[-1], ZONA).strftime("%H:%M:%S")
        duracion = (ts[-1] - ts[0] + periodo) / 3600
        print(f"intervalo: {inicio} a {fin} (hora de Colombia), {duracion:.2f} h incluyendo el último periodo")
        if malas:
            fallas.append(f"{len(malas)} separaciones distintas de {periodo} s: {sorted(set(malas))[:5]}")

    for c in COLUMNAS:
        vacias = sum(1 for f in filas if f[c] == "")
        if c == "ts_local_iso" or vacias == 0:
            continue
        if vacias == n:
            avisos.append(f"columna {c} vacía en todas las filas (sensor ausente)")
        else:
            fallas.append(f"columna {c} vacía en {vacias} filas")

    origenes = sorted({f["origen"] for f in filas})
    print(f"origen: {origenes}")
    if oficial and origenes != ["sensor"]:
        fallas.append("la prueba oficial solo admite origen 'sensor'")

    conteo = {b: 0 for b in BITS}
    for f in filas:
        e = int(f["estado_sensores"] or 0)
        for b in BITS:
            if e & b:
                conteo[b] += 1
    activos = {BITS[b]: k for b, k in conteo.items() if k}
    print(f"bits de estado activos: {activos or 'ninguno'}")
    for b in (1, 2, 4, 8):
        if conteo[b]:
            fallas.append(f"{conteo[b]} filas con {BITS[b]}")
    if conteo[32]:
        avisos.append(f"{conteo[32]} filas registradas sin conexión MQTT (quedaron en la cola del nodo)")

    retrasos = [int(f["retraso_ms"]) for f in filas if f["retraso_ms"] != ""]
    if retrasos:
        print(f"retraso respecto de la cuadrícula: mín {min(retrasos)} ms, máx {max(retrasos)} ms")

    for c, (lo, hi) in RANGOS.items():
        fuera = [float(f[c]) for f in filas if f[c] != "" and not lo <= float(f[c]) <= hi]
        if fuera:
            avisos.append(f"{len(fuera)} valores de {c} fuera del rango de RF1 [{lo}, {hi}]: {fuera[:3]}")

    # Series congeladas: mismo valor de temperatura y HR durante 20 muestras seguidas (10 min a 30 s).
    racha, maxima = 1, 1
    for a, b in zip(filas, filas[1:]):
        racha = racha + 1 if (a["t_c"], a["hr_pct"]) == (b["t_c"], b["hr_pct"]) and a["t_c"] != "" else 1
        maxima = max(maxima, racha)
    if maxima >= 20:
        avisos.append(f"temperatura y HR idénticas durante {maxima} muestras seguidas (¿sensor congelado?)")
    return fallas, avisos


def comparar(a, b):
    """Contrasta dos archivos por marca de tiempo; devuelve una lista de diferencias."""
    ia = {f["ts_epoch"]: f for f in a if f["ts_epoch"] not in ("", "0")}
    if ia:
        # El archivo del borde trae el día completo: solo cuenta el intervalo que cubre el primero.
        lo, hi = min(map(int, ia)), max(map(int, ia))
        b = [f for f in b if f["ts_epoch"] not in ("", "0") and lo <= int(f["ts_epoch"]) <= hi]
    ib = {f["ts_epoch"]: f for f in b}
    difs = []
    solo_a, solo_b = sorted(set(ia) - set(ib)), sorted(set(ib) - set(ia))
    if solo_a:
        difs.append(f"{len(solo_a)} marcas solo en el primer archivo, por ejemplo {solo_a[:3]}")
    if solo_b:
        difs.append(f"{len(solo_b)} marcas solo en el segundo archivo, por ejemplo {solo_b[:3]}")
    distintas = 0
    for ts in sorted(set(ia) & set(ib)):
        for c in COLUMNAS:
            va, vb = ia[ts][c], ib[ts][c]
            if va == vb:
                continue
            if c in TOLERANCIA and va != "" and vb != "" and abs(float(va) - float(vb)) <= TOLERANCIA[c]:
                continue
            distintas += 1
            if distintas <= 5:
                difs.append(f"ts {ts}, {c}: {va!r} frente a {vb!r}")
    if distintas > 5:
        difs.append(f"... {distintas} diferencias en total")
    print(f"comparación: {len(set(ia) & set(ib))} marcas en común")
    return difs


def a_xlsx(ruta_csv, filas):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except ImportError:
        sys.exit("--xlsx necesita openpyxl: python3 -m pip install --user openpyxl")
    libro = Workbook()
    hoja = libro.active
    hoja.title = "registros"
    hoja.append(COLUMNAS)
    for celda in hoja[1]:
        celda.font = Font(bold=True)
    for f in filas:
        hoja.append([(float(f[c]) if "." in f[c] else int(f[c])) if c in NUMERICAS and f[c] != "" else f[c]
                     for c in COLUMNAS])
    hoja.freeze_panes = "A2"
    for i, c in enumerate(COLUMNAS, start=1):
        hoja.column_dimensions[hoja.cell(row=1, column=i).column_letter].width = max(10, len(c) + 2)
    hoja.column_dimensions["C"].width = 27
    destino = os.path.splitext(ruta_csv)[0] + ".xlsx"
    libro.save(destino)
    print(f"xlsx: {destino}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archivo")
    ap.add_argument("--muestras", type=int, default=0, help="número exacto de filas esperado (360 en la prueba)")
    ap.add_argument("--periodo", type=int, default=30)
    ap.add_argument("--oficial", action="store_true", help="exige origen 'sensor' en todas las filas")
    ap.add_argument("--desde", help="hora local AAAA-MM-DDTHH:MM:SS; toma las filas desde ahí (con --muestras, solo esas)")
    ap.add_argument("--recortar", help="guarda en este archivo las filas seleccionadas con --desde")
    ap.add_argument("--comparar", help="otro CSV con las mismas columnas para contrastar por marca de tiempo")
    ap.add_argument("--xlsx", action="store_true", help="genera un .xlsx junto al CSV (las filas seleccionadas)")
    a = ap.parse_args()

    filas = leer(a.archivo)
    if a.desde:
        desde = int(datetime.strptime(a.desde, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=ZONA).timestamp())
        filas = [f for f in filas if f["ts_epoch"] not in ("", "0") and int(f["ts_epoch"]) >= desde]
        if a.muestras:
            filas = filas[:a.muestras]
    if a.recortar:
        escribir(a.recortar, filas)
        print(f"recorte guardado en {a.recortar}")

    print(f"== {a.archivo}")
    fallas, avisos = validar(filas, a.muestras, a.periodo, a.oficial)
    if a.comparar:
        fallas += comparar(filas, leer(a.comparar))
    if a.xlsx:
        a_xlsx(a.recortar or a.archivo, filas)

    for x in avisos:
        print(f"AVISO  {x}")
    for x in fallas:
        print(f"FALLA  {x}")
    print("\nResultado: " + ("sin fallas" if not fallas else f"{len(fallas)} fallas"))
    sys.exit(1 if fallas else 0)


if __name__ == "__main__":
    main()
