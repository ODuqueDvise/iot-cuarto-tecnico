#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pruebas del procesador sobre los CSV reales del repositorio (datos/). Se corren en el Mac o en la Pi:

    python3 prueba_procesador.py

Cada prueba fija un hecho conocido de esos archivos (bitácora del proyecto), de modo que un cambio en el
procesador que altere el resultado se note. Termina con código 0 si todo pasa.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import procesador as P  # noqa: E402

DATOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "datos")
fallas = []


def comprobar(cond, texto):
    if cond:
        print("  ok  ", texto)
    else:
        print("  FALLA", texto)
        fallas.append(texto)


def prueba_oficial_20():
    """Prueba de 3 h del 20 de octubre: 360 muestras limpias, sin huecos, tres aperturas de puerta."""
    print("oficial_20261020_0837.csv")
    limpia, eventos, r = P.procesar(P.leer_csv(os.path.join(DATOS, "oficial_20261020_0837.csv")))
    comprobar(r["salida"] == 360, "360 muestras de salida")
    comprobar(r["huecos"]["huecos"] == 0, "sin huecos")
    comprobar(r["arranques"]["arranques"] == 1 and r["arranques"]["corriente_retirada"] == 3,
              "un arranque, corriente retirada en 3 muestras (90 s)")
    puertas = eventos[eventos.tipo == "puerta_abierta"]
    comprobar(len(puertas) == 3, "tres aperturas de puerta")
    comprobar(int(puertas.iloc[1].duracion_s) == 120, "la apertura de las 09:08 duró 2 min")
    comprobar(limpia["i"].isna().sum() == 3 and limpia["t"].isna().sum() == 0, "solo se retiró corriente")


def prueba_borde_20():
    """Registrador del 20 de octubre: nueve arranques de la mañana, un fallo de corriente, un rebote de agua."""
    print("borde/nodo1_20261020.csv")
    limpia, eventos, r = P.procesar(P.leer_csv(os.path.join(DATOS, "borde", "nodo1_20261020.csv")))
    comprobar(r["arranques"]["arranques"] == 9, "nueve arranques")
    comprobar(r["fallos"]["fallo_corriente"] == 1, "un fallo de corriente marcado por el nodo")
    comprobar(r["agua"]["agua_rebotes_suprimidos"] == 1, "un rebote de agua suprimido (12:47)")
    arranque = limpia[limpia.arranque].iloc[0]
    comprobar(pd.isna(arranque["i"]) and (arranque["calidad"] & P.CAL_ARRANQUE) > 0,
              "la corriente de 0,061 A del arranque de las 08:27 no sale")
    comprobar(eventos[eventos.tipo == "agua"].empty, "ningún evento de agua tras la histéresis")


def prueba_borde_17():
    """Registrador del 17 de octubre: mezcla de simulado y sensor, fallos del SHT31 y de corriente."""
    print("borde/nodo1_20261017.csv")
    limpia, eventos, r = P.procesar(P.leer_csv(os.path.join(DATOS, "borde", "nodo1_20261017.csv")))
    comprobar(r["origen"]["por_origen"].get("simulado") == 49 and r["salida"] == 212,
              "49 simuladas retiradas, 212 del sensor")
    comprobar(r["fallos"]["fallo_sht31"] == 1, "una lectura con fallo del SHT31 retirada")
    comprobar(limpia["t"].isna().sum() == 1, "la temperatura de esa muestra queda vacía")
    comprobar(len(eventos[eventos.tipo == "agua"]) == 4, "cuatro eventos de agua del ensayo")
    comprobar(len(eventos[eventos.tipo == "puerta_abierta"]) == 5, "cinco aperturas de puerta")


def prueba_captura_29():
    """Sesión del video del 29: cambio de periodo a 10 s (bit 16) y cortes con entrega tardía (bit 32)."""
    print("captura_20261029_1407.csv")
    limpia, eventos, r = P.procesar(P.leer_csv(os.path.join(DATOS, "captura_20261029_1407.csv")))
    comprobar(r["fallos"]["cuadricula"] == 2 and r["fallos"]["tardias"] == 7, "2 cuadrícula, 7 tardías")
    comprobar(r["huecos"]["huecos"] == 0, "el cambio de periodo no se confunde con un hueco")
    comprobar(set(limpia.periodo.unique()) == {10, 20, 30}, "periodos 30, 20 (transición) y 10 s")
    tard = eventos[eventos.tipo == "entrega_tardia"]
    comprobar(len(tard) == 4, "cuatro tramos de entrega tardía (tres cortes y el arranque)")
    comprobar(limpia["i"].notna().sum() == 64, "la corriente se conserva salvo en el arranque")


def prueba_sinteticos():
    """Casos que los archivos reales no tienen: duplicados, fuera de rango, hueco por seq, sin hora."""
    print("sintéticos")
    base = pd.Timestamp("2026-10-30T10:00:00Z")
    filas = []
    for k in range(10):
        filas.append({"ts": base + pd.Timedelta(seconds=30 * k), "nodo": "nodo1", "seq": k, "retraso_ms": 5,
                      "t": 24.0, "hr": 50.0, "pr": 13.0, "i": 0.1, "i_max": 0.1, "puerta": 0, "puerta_n": 0,
                      "agua": 0, "agua_n": 0, "est": 0, "origen": "sensor"})
    filas.append(dict(filas[5]))                      # duplicado exacto de la muestra 5
    filas[7]["t"] = 99.0                               # fuera de rango
    filas[8]["seq"] = 9                                # el nodo saltó del 7 al 9: falta una muestra
    filas[9]["seq"] = 10
    filas[9]["est"] = P.EST_SIN_HORA
    d = P.normalizar(pd.DataFrame(filas))
    limpia, eventos, r = P.procesar(d)
    comprobar(r["duplicados"]["duplicadas"] == 1, "duplicado retirado")
    comprobar(r["rangos"]["fuera_de_rango"]["t"] == 1 and limpia["t"].isna().sum() == 1, "temperatura de 99 °C retirada")
    comprobar(r["huecos"]["huecos"] == 1 and r["huecos"]["muestras_faltantes"] == 1, "un hueco de una muestra")
    comprobar(int(limpia.iloc[-1]["calidad"]) & P.CAL_SIN_HORA, "sin hora marcado en calidad")
    comprobar(r["salida"] == 10 and r["arranques"]["arranques"] == 1, "10 muestras, un arranque")


if __name__ == "__main__":
    for prueba in (prueba_oficial_20, prueba_borde_20, prueba_borde_17, prueba_captura_29, prueba_sinteticos):
        prueba()
    print()
    if fallas:
        print(f"{len(fallas)} prueba(s) fallida(s)")
        sys.exit(1)
    print("todas las pruebas pasaron")
