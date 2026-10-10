# -*- coding: utf-8 -*-
"""Mide el costo del detector de personas en el borde con imágenes fijas.

Reporta el tiempo de carga del modelo, el tiempo por imagen (media, mediana y percentil 95),
el tiempo estimado de una ráfaga de 20 cuadros (RF4: 10 s a 2 cuadros por segundo) y el pico
de memoria residente del proceso. Si se pasan fotos, cuenta las personas detectadas en cada una.

Uso:
  python medir_detector.py --modelo ../modelos/ssd_mobilenet_v2_coco.onnx [foto1.jpg foto2.jpg ...]
"""
import argparse
import resource
import statistics
import time

import numpy as np
import onnxruntime as ort
from PIL import Image

CLASE_PERSONA = 1  # en el mapa de etiquetas de COCO del TF Model Zoo
LADO = 320         # resolución de entrada del modelo exportado


def pico_mb():
    """Pico de memoria residente del proceso, en MB (Linux reporta KB)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def preparar(ruta):
    img = Image.open(ruta).convert("RGB").resize((LADO, LADO))
    return np.asarray(img, dtype=np.uint8)[None, ...]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelo", required=True)
    ap.add_argument("--umbral", type=float, default=0.5)
    ap.add_argument("--repeticiones", type=int, default=30)
    ap.add_argument("--hilos", type=int, default=4)
    ap.add_argument("fotos", nargs="*")
    a = ap.parse_args()

    base = pico_mb()
    opciones = ort.SessionOptions()
    opciones.intra_op_num_threads = a.hilos
    t0 = time.perf_counter()
    sesion = ort.InferenceSession(a.modelo, opciones, providers=["CPUExecutionProvider"])
    carga_s = time.perf_counter() - t0
    tras_carga = pico_mb()

    entrada = sesion.get_inputs()[0]
    nombres = [o.name for o in sesion.get_outputs()]
    print(f"entrada: {entrada.name} {entrada.shape} {entrada.type}")

    if a.fotos:
        lotes = [preparar(f) for f in a.fotos]
    else:
        rng = np.random.default_rng(0)
        lotes = [rng.integers(0, 256, (1, LADO, LADO, 3), dtype=np.uint8)]
        print("sin fotos: se mide solo el tiempo, con una imagen de ruido")

    sesion.run(None, {entrada.name: lotes[0]})  # calentamiento
    tiempos = []
    for i in range(a.repeticiones):
        x = lotes[i % len(lotes)]
        t = time.perf_counter()
        sesion.run(None, {entrada.name: x})
        tiempos.append((time.perf_counter() - t) * 1000)

    tiempos.sort()
    p95 = tiempos[int(0.95 * (len(tiempos) - 1))]
    media = statistics.mean(tiempos)
    print(f"carga del modelo: {carga_s:.2f} s")
    print(f"inferencia: media {media:.0f} ms, mediana {statistics.median(tiempos):.0f} ms, p95 {p95:.0f} ms ({a.repeticiones} corridas, {a.hilos} hilos)")
    print(f"ráfaga de 20 cuadros (RF4): {media * 20 / 1000:.1f} s estimados")
    print(f"memoria del proceso: {base:.0f} MB antes, {tras_carga:.0f} MB tras cargar, {pico_mb():.0f} MB pico")

    for ruta, x in zip(a.fotos, lotes):
        r = dict(zip(nombres, sesion.run(None, {entrada.name: x})))
        clases = r["detection_classes"][0].astype(int)
        puntajes = r["detection_scores"][0]
        n = int(np.sum((clases == CLASE_PERSONA) & (puntajes >= a.umbral)))
        print(f"{ruta}: {n} persona(s) con puntaje >= {a.umbral}")


if __name__ == "__main__":
    main()
