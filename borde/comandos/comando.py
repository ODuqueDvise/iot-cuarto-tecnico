#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Envía un comando a un nodo por MQTT y espera su respuesta. Se ejecuta en la Raspberry Pi.

Usa el certificado del puente (/etc/puente/puente.env), que la lista de control del intermediario
autoriza a escribir en cuarto/<nodo>/comandos. Los nodos solo pueden leer sus comandos y escribir sus
propios temas, así que ningún nodo puede comandar a otro.

Ejemplos (en la Pi, como el usuario puente):
    sudo -u puente /opt/puente/.venv/bin/python /opt/puente/comando.py nodo1 '{"periodo": 10}'
    sudo -u puente /opt/puente/.venv/bin/python /opt/puente/comando.py nodo1 '{"led": "on"}'
    sudo -u puente /opt/puente/.venv/bin/python /opt/puente/comando.py nodo1 '{"periodo": 30, "led": "auto"}'

Termina con 0 si el nodo respondió "ok": true; 1 si respondió con error; 2 si no respondió a tiempo.
"""
import argparse
import json
import os
import sys
import threading
import time

import paho.mqtt.client as mqtt

ENV = "/etc/puente/puente.env"


def leer_env(ruta):
    cfg = {}
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                k, v = linea.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("nodo", help="identificador del nodo, por ejemplo nodo1")
    ap.add_argument("comando", help="objeto JSON, por ejemplo '{\"periodo\": 10}'")
    ap.add_argument("--espera", type=float, default=10.0, help="segundos de espera por la respuesta")
    a = ap.parse_args()

    try:
        orden = json.loads(a.comando)
    except json.JSONDecodeError as e:
        sys.exit(f"el comando no es JSON válido: {e}")
    if not isinstance(orden, dict):
        sys.exit("el comando debe ser un objeto JSON")
    orden["id"] = int(time.time() * 1000) % 1000000   # correlación entre comando y respuesta

    cfg = leer_env(os.environ.get("PUENTE_ENV", ENV))
    tema_comandos = f"cuarto/{a.nodo}/comandos"
    tema_respuestas = f"cuarto/{a.nodo}/respuestas"
    respuesta = {}
    listo = threading.Event()

    def al_conectar(c, u, flags, codigo, props=None):
        c.subscribe(tema_respuestas, qos=1)

    def al_suscribir(c, u, mid, codigos, props=None):
        c.publish(tema_comandos, json.dumps(orden), qos=1)
        print(f"comando -> {tema_comandos}: {json.dumps(orden)}")

    def al_mensaje(c, u, msg):
        try:
            r = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if r.get("id") == orden["id"]:
            respuesta.update(r)
            listo.set()

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="borde-comando", protocol=mqtt.MQTTv5)
    cliente.tls_set(ca_certs=cfg["MQTT_CA"], certfile=cfg["MQTT_CERT"], keyfile=cfg["MQTT_KEY"])
    cliente.on_connect = al_conectar
    cliente.on_subscribe = al_suscribir
    cliente.on_message = al_mensaje
    cliente.connect(cfg["MQTT_HOST"], int(cfg.get("MQTT_PUERTO", "8883")), keepalive=30)
    cliente.loop_start()
    ok = listo.wait(a.espera)
    cliente.loop_stop()
    cliente.disconnect()
    if not ok:
        print(f"sin respuesta del nodo en {a.espera:g} s (¿está conectado?)")
        sys.exit(2)
    print(f"respuesta <- {tema_respuestas}: {json.dumps(respuesta, ensure_ascii=False)}")
    sys.exit(0 if respuesta.get("ok") else 1)


if __name__ == "__main__":
    main()
