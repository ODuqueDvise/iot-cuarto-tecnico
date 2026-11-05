#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Análisis fuera de línea de la telemetría limpia (Actividad 4). Corre en el Mac o en el contenedor.

Entrada: uno o más CSV "*_limpia.csv" del procesador (o CSV crudos, que se procesan primero).
Salida, en la carpeta indicada: tablas CSV y un JSON con los resultados, para el informe:

  descriptiva.csv     media, mediana, desviación, mínimo, máximo y n por variable
  correlaciones.csv   matriz de Pearson entre t, hr, pr, i y puerta
  dia_noche.csv       descriptiva por franja (día 06:00 a 18:00, noche el resto, hora local)
  horaria.csv         perfil por hora del día (media de t, hr, i)
  regresion.json      modelo lineal que predice t (y hr) a 30 min, 1 h y 6 h con las últimas muestras,
                      evaluado por división temporal (entrena con el primer 70 %, prueba con el resto)
                      y comparado con la persistencia (el valor futuro es el actual)

Uso:
  analisis.py --limpia datos/procesado/*_limpia.csv --salida datos/analisis
  analisis.py --crudo datos/oficial_20261020_0837.csv datos/borde/nodo1_20261020.csv --salida datos/analisis

Solo pandas y numpy. La regresión es por mínimos cuadrados sin bibliotecas de aprendizaje automático,
para que el procedimiento quede a la vista.
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import procesador as P  # noqa: E402

ZONA = "America/Bogota"
VARIABLES = ["t", "hr", "pr", "i", "i_max", "potencia_va", "retraso_ms"]
NOMBRES = {"t": "temperatura (°C)", "hr": "humedad relativa (%)", "pr": "punto de rocío (°C)",
           "i": "corriente media (A)", "i_max": "corriente máxima (A)", "potencia_va": "potencia aparente (VA)",
           "retraso_ms": "retraso (ms)", "puerta": "puerta abierta (0/1)"}
DIA = (6, 18)   # horas locales [inicio, fin) de la franja "día"


def cargar(rutas_limpias=(), rutas_crudas=()):
    partes = []
    for r in rutas_limpias:
        d = pd.read_csv(r)
        d["ts"] = pd.to_datetime(d["ts"], utc=True)
        partes.append(d)
    for r in rutas_crudas:
        limpia, _, _ = P.procesar(P.leer_csv(r))
        partes.append(limpia)
    if not partes:
        sys.exit("sin archivos de entrada")
    d = pd.concat(partes, ignore_index=True).drop_duplicates(subset=["nodo", "ts"], keep="last")
    d = d.sort_values("ts").reset_index(drop=True)
    d["local"] = d["ts"].dt.tz_convert(ZONA)
    d["hora"] = d["local"].dt.hour
    d["franja"] = np.where((d["hora"] >= DIA[0]) & (d["hora"] < DIA[1]), "día", "noche")
    d["puerta"] = d["puerta"].astype("float")
    return d


def descriptiva(d, variables=VARIABLES):
    filas = []
    for v in variables:
        s = d[v].dropna()
        if s.empty:
            continue
        filas.append({"variable": NOMBRES.get(v, v), "n": int(s.size), "media": s.mean(), "mediana": s.median(),
                      "desviacion": s.std(ddof=1) if s.size > 1 else float("nan"), "minimo": s.min(), "maximo": s.max()})
    return pd.DataFrame(filas).round(3)


def correlaciones(d):
    cols = ["t", "hr", "pr", "i", "puerta"]
    m = d[cols].corr(method="pearson").round(3)
    m.index = [NOMBRES[c] for c in cols]
    m.columns = [NOMBRES[c] for c in cols]
    return m


def dia_noche(d):
    filas = []
    for franja, g in d.groupby("franja"):
        for v in ("t", "hr", "pr", "i"):
            s = g[v].dropna()
            if s.empty:
                continue
            filas.append({"franja": franja, "variable": NOMBRES[v], "n": int(s.size), "media": s.mean(),
                          "desviacion": s.std(ddof=1) if s.size > 1 else float("nan"), "minimo": s.min(), "maximo": s.max()})
    return pd.DataFrame(filas).round(3)


def horaria(d):
    g = d.groupby("hora")[["t", "hr", "i"]].agg(["mean", "count"])
    g.columns = ["t_media", "t_n", "hr_media", "hr_n", "i_media", "i_n"]
    return g.round(3).reset_index()


def regresion(d, objetivo="t", horizonte_s=1800, rezagos=(0, 300, 900, 1800), periodo_s=30):
    """Predice objetivo(t + horizonte) con una combinación lineal de objetivo en t, t-5 min, t-15 min y
    t-30 min, la humedad en t y la hora del día (seno y coseno). Serie regular: se remuestrea al periodo
    nominal y solo se usan ventanas completas (sin huecos)."""
    otra = "hr" if objetivo != "hr" else "t"
    s = d.set_index("ts")[[objetivo, otra]].resample(f"{periodo_s}s").mean()
    hora = s.index.tz_convert(ZONA).hour + s.index.tz_convert(ZONA).minute / 60.0
    X = pd.DataFrame(index=s.index)
    for r in rezagos:
        X[f"{objetivo}_menos_{r // 60}min"] = s[objetivo].shift(r // periodo_s)
    X[otra] = s[otra]
    X["sen_hora"] = np.sin(2 * np.pi * hora / 24)
    X["cos_hora"] = np.cos(2 * np.pi * hora / 24)
    y = s[objetivo].shift(-horizonte_s // periodo_s)
    datos = pd.concat([X, y.rename("y")], axis=1).dropna()
    if len(datos) < 40:
        return {"objetivo": objetivo, "horizonte_min": horizonte_s // 60, "n": len(datos),
                "aviso": "menos de 40 ventanas completas: no se ajusta el modelo"}
    corte = int(len(datos) * 0.7)
    ent, pru = datos.iloc[:corte], datos.iloc[corte:]
    A = np.column_stack([np.ones(len(ent)), ent.drop(columns="y").values])
    coef, *_ = np.linalg.lstsq(A, ent["y"].values, rcond=None)
    Ap = np.column_stack([np.ones(len(pru)), pru.drop(columns="y").values])
    pred = Ap @ coef
    err = pru["y"].values - pred
    # referencia ingenua: "dentro de 30 min la temperatura será la de ahora"
    err_ingenuo = pru["y"].values - pru[f"{objetivo}_menos_0min"].values
    rmse = float(np.sqrt(np.mean(err ** 2)))
    rmse_ingenuo = float(np.sqrt(np.mean(err_ingenuo ** 2)))
    ss_res, ss_tot = float(np.sum(err ** 2)), float(np.sum((pru["y"] - pru["y"].mean()) ** 2))
    return {"objetivo": objetivo, "horizonte_min": horizonte_s // 60, "n_entrenamiento": len(ent), "n_prueba": len(pru),
            "coeficientes": {k: round(float(v), 4) for k, v in zip(["intercepto"] + list(ent.drop(columns="y").columns), coef)},
            "rmse_prueba": round(rmse, 3), "mae_prueba": round(float(np.mean(np.abs(err))), 3),
            "r2_prueba": round(1 - ss_res / ss_tot, 3) if ss_tot > 0 else None,
            "rmse_ingenuo": round(rmse_ingenuo, 3),
            "mejora_sobre_ingenuo_pct": round(100 * (1 - rmse / rmse_ingenuo), 1) if rmse_ingenuo > 0 else None}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limpia", nargs="*", default=[], help="CSV *_limpia.csv del procesador (admite comodines)")
    ap.add_argument("--crudo", nargs="*", default=[], help="CSV crudos (captura serie o registrador)")
    ap.add_argument("--salida", default="analisis")
    a = ap.parse_args()
    limpias = [f for patron in a.limpia for f in sorted(glob.glob(patron))]
    d = cargar(limpias, a.crudo)
    os.makedirs(a.salida, exist_ok=True)
    resumen = {"muestras": len(d), "desde": str(d["local"].min()), "hasta": str(d["local"].max()),
               "dias": sorted(d["local"].dt.strftime("%Y-%m-%d").unique().tolist()),
               "por_franja": d["franja"].value_counts().to_dict()}
    descriptiva(d).to_csv(os.path.join(a.salida, "descriptiva.csv"), index=False)
    correlaciones(d).to_csv(os.path.join(a.salida, "correlaciones.csv"))
    dia_noche(d).to_csv(os.path.join(a.salida, "dia_noche.csv"), index=False)
    horaria(d).to_csv(os.path.join(a.salida, "horaria.csv"), index=False)
    resumen["regresion_t_30min"] = regresion(d, "t", 1800)
    resumen["regresion_t_60min"] = regresion(d, "t", 3600)
    resumen["regresion_t_360min"] = regresion(d, "t", 21600)
    resumen["regresion_hr_30min"] = regresion(d, "hr", 1800)
    resumen["regresion_hr_360min"] = regresion(d, "hr", 21600)
    with open(os.path.join(a.salida, "regresion.json"), "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    print(json.dumps(resumen, ensure_ascii=False, indent=2))
    print(descriptiva(d).to_string(index=False))
    print(correlaciones(d).to_string())


if __name__ == "__main__":
    main()
